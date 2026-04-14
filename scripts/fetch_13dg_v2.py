#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# This pipeline checkpoints after every unit of work listed below.
# A restart never reprocesses more than one unit.
# fetch_13dg_v2.py unit: one accession (one filing)
# Per-accession writes: manifest row (fetch_started_at → complete|failed),
# L1 artifact at data/13dg_raw/{accession}.txt, stg_13dg_filings row,
# ingestion_impacts row. On kill, the next run's discover anti-joins
# the manifest and skips completed accessions.
"""fetch_13dg_v2.py — SourcePipeline for SC 13D / 13D/A / 13G / 13G/A filings.

Scoped reference vertical for the v1.2 framework proof:
AR, OXY, EQT, NFLX. First full SourcePipeline — every subsequent
SourcePipeline (N-PORT, 13F, ADV, N-CEN) copies this pattern.

Stages:
  discover()        → EDGAR full-text search per subject CIK, anti-join
                      ingestion_manifest on accession_number.
  fetch()           → pipeline.shared.sec_fetch() → local artifact at
                      data/13dg_raw/{accession}.txt + manifest row.
  parse()           → regex extraction via scripts/fetch_13dg._clean_text
                      + _extract_fields. §5b QC gates: pct 0–100, shares
                      0 or ≥100, aggregate_value vs shares×price ±20%.
  load_to_staging() → stg_13dg_filings (staging DB) + ingestion_impacts
                      per (filer_cik, subject_cusip, accession).

Reuses the proven parser from the original fetch_13dg.py rather than
duplicating it — the legacy script stays on the REWRITE list (writes
to the dropped `beneficial_ownership` table) but its parser is isolated
and correct.

Flags:
  --dry-run     Show discovery, no DB writes.
  --tickers L   Comma-separated subject ticker list
                (default: AR,OXY,EQT,NFLX).
  --staging     Write stg_13dg_filings to data/13f_staging.duckdb
                (default).
  --limit N     Cap total accessions fetched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import (  # noqa: E402
    get_db_path, get_read_db_path, set_staging_mode, is_staging_mode,
    crash_handler,
)
from fetch_13dg import _clean_text, _extract_fields  # noqa: E402

from pipeline.manifest import (  # noqa: E402
    get_or_create_manifest_row, update_manifest_status, write_impact,
)
from pipeline.protocol import (  # noqa: E402
    DownloadTarget, FetchResult, ParseResult, QCFailure,
)
from pipeline.shared import sec_fetch  # noqa: E402


SCOPED_TICKERS: tuple[str, ...] = ("AR", "OXY", "EQT", "NFLX")
L1_DIR = os.path.join(BASE_DIR, "data", "13dg_raw")
SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}

# 13D/G windows are narrow — we go back 4 years to be safe against
# pipeline gaps. Anti-join against manifest will de-duplicate anything
# already fetched.
_DISCOVER_LOOKBACK_YEARS = 4
_FORMS = ("SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A")
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"


# ---------------------------------------------------------------------------
# Ticker → subject CIK lookup (CUSIP-anchored, best-effort)
# ---------------------------------------------------------------------------

# Hardcoded known mappings for the scoped universe — securities has some
# ticker collisions (OXY → PKG cusip, EQT → RJF cusip, etc.) so we can't
# trust `SELECT cusip FROM securities WHERE ticker = ?` for these four.
# These CIKs are canonical; the securities table cleanup is tracked
# separately.
_SUBJECT_CIK_OVERRIDES: dict[str, str] = {
    "AR":   "0001433604",  # Antero Resources Corp
    "OXY":  "0000797468",  # Occidental Petroleum Corp
    "EQT":  "0000033213",  # EQT Corp
    "NFLX": "0001065280",  # Netflix Inc
}


def _resolve_subject_cik(ticker: str, con_prod: Any) -> Optional[str]:
    """Resolve a subject ticker to its 10-digit zero-padded CIK.

    First consult the hardcoded override map for the scoped universe
    (avoids known data-quality ticker reuse in `securities`). Fall back
    to a lookup through holdings_v2 + filings (for any future
    subject_ticker that enters the scoped list).
    """
    if ticker in _SUBJECT_CIK_OVERRIDES:
        return _SUBJECT_CIK_OVERRIDES[ticker]
    # Best-effort: any cik in filings_deduped whose manager_name contains
    # the ticker as a word. Intentionally narrow — non-match is fine.
    hit = con_prod.execute(
        "SELECT DISTINCT cik FROM filings_deduped "
        "WHERE UPPER(manager_name) LIKE ? LIMIT 1",
        [f"%{ticker.upper()}%"],
    ).fetchone()
    return hit[0].zfill(10) if hit else None


# ---------------------------------------------------------------------------
# EDGAR full-text search (efts.sec.gov)
# ---------------------------------------------------------------------------

def _efts_search_for_subject(
    subject_cik: str,
    startdt: str,
    enddt: str,
) -> list[dict[str, Any]]:
    """Query EDGAR full-text search for SC 13D/G/A filings about subject_cik.

    Returns flat list of hit dicts with at least:
      accession_no, filed (YYYY-MM-DD), form, file (accession as filename),
      root_forms, display_names, ciks[0] (filer CIK).
    Rate-limited via shared.rate_limit('efts.sec.gov').
    """
    forms = ",".join(_FORMS).replace(" ", "+")
    params = (
        f"?q=&forms={forms}"
        f"&dateRange=custom&startdt={startdt}&enddt={enddt}"
        f"&ciks={subject_cik}"
    )
    url = f"{_EFTS_URL}{params}"

    hits: list[dict[str, Any]] = []
    offset = 0
    page_size = 100
    while True:
        page_url = f"{url}&from={offset}&size={page_size}"
        resp, _ = sec_fetch(page_url, headers=SEC_HEADERS)
        data = resp.json()
        page_hits = (data.get("hits", {}) or {}).get("hits", []) or []
        if not page_hits:
            break
        hits.extend(page_hits)
        offset += page_size
        if offset >= (data.get("hits", {}) or {}).get("total", {}).get("value", 0):
            break
    return hits


def _normalize_acc(acc_raw: str) -> str:
    """Normalize accession number to dashed form (0001234567-22-000123)."""
    acc = acc_raw.replace("-", "")
    return f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"


# ---------------------------------------------------------------------------
# Staging DDL
# ---------------------------------------------------------------------------

_STAGING_DDL = """
CREATE TABLE IF NOT EXISTS stg_13dg_filings (
    accession_number  VARCHAR PRIMARY KEY,
    filer_cik         VARCHAR,
    filer_name        VARCHAR,
    subject_cusip     VARCHAR,
    subject_ticker    VARCHAR,
    subject_name      VARCHAR,
    filing_type       VARCHAR,
    filing_date       DATE,
    report_date       DATE,
    pct_owned         DOUBLE,
    shares_owned      BIGINT,
    aggregate_value   DOUBLE,
    intent            VARCHAR,
    is_amendment      BOOLEAN,
    prior_accession   VARCHAR,
    purpose_text      VARCHAR,
    group_members     VARCHAR,
    manager_cik       VARCHAR,
    loaded_at         TIMESTAMP,
    name_resolved     BOOLEAN,
    entity_id         BIGINT,
    -- control-plane extras
    manifest_id       BIGINT,
    parse_status      VARCHAR,
    qc_flags          VARCHAR
)
"""


def _ensure_staging_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_STAGING_DDL)


# ---------------------------------------------------------------------------
# SourcePipeline
# ---------------------------------------------------------------------------

class Dg13DgPipeline:
    """SourcePipeline for scoped 13D/G. Conforms structurally to
    scripts.pipeline.protocol.SourcePipeline.

    Parser helpers live in fetch_13dg._clean_text / _extract_fields.
    This class is the framework wrapper (manifest / impacts / gating).
    """

    source_type = "13DG"

    def __init__(self, *, run_id: str,
                 subject_tickers: tuple[str, ...] = SCOPED_TICKERS,
                 limit: Optional[int] = None) -> None:
        self.run_id = run_id
        self.subject_tickers = tuple(subject_tickers)
        self.limit = limit

    # ----- discover ------------------------------------------------------

    def discover(self, run_id: str) -> list[DownloadTarget]:
        """EDGAR full-text search for each subject CIK in the scoped set.

        Anti-joins ingestion_manifest on accession_number to skip
        already-fetched filings. Date floor = (today − 4y) OR
        max(filing_date) per-ticker in beneficial_ownership_v2, whichever
        is later (minimizes redundant discovery calls once prod is warm).
        """
        os.makedirs(L1_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")

        con = duckdb.connect(get_read_db_path(), read_only=True)
        try:
            already = set(con.execute(
                "SELECT accession_number FROM ingestion_manifest "
                "WHERE source_type = ? AND fetch_status = 'complete'",
                [self.source_type],
            ).fetchdf()["accession_number"].tolist())
            # Per-ticker floor
            floors = {}
            for t in self.subject_tickers:
                row = con.execute(
                    "SELECT MAX(filing_date) FROM beneficial_ownership_v2 "
                    "WHERE subject_ticker = ?",
                    [t],
                ).fetchone()
                floor = row[0] if row and row[0] else None
                if floor is None:
                    floors[t] = (
                        datetime.now()
                        .replace(year=datetime.now().year - _DISCOVER_LOOKBACK_YEARS)
                        .strftime("%Y-%m-%d")
                    )
                else:
                    floors[t] = floor.strftime("%Y-%m-%d")
            subject_ciks = {
                t: _resolve_subject_cik(t, con)
                for t in self.subject_tickers
            }
        finally:
            con.close()

        targets: list[DownloadTarget] = []
        for ticker in self.subject_tickers:
            subject_cik = subject_ciks.get(ticker)
            if not subject_cik:
                print(f"  discover: no subject_cik for {ticker}, skipping",
                      flush=True)
                continue
            startdt = floors[ticker]
            print(
                f"  discover: efts query subject={ticker} (cik={subject_cik}) "
                f"from {startdt} to {today}",
                flush=True,
            )
            try:
                hits = _efts_search_for_subject(subject_cik, startdt, today)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  discover: efts error for {ticker}: {exc}", flush=True)
                continue

            for hit in hits:
                source = hit.get("_source", {}) or {}
                acc_raw = hit.get("_id", "")  # format: '0001234567-22-000123:primary_doc.xml'
                acc = acc_raw.split(":")[0] if acc_raw else source.get("adsh")
                if not acc:
                    continue
                acc = _normalize_acc(acc)
                if acc in already:
                    continue
                form = source.get("root_form", source.get("form", "")) or ""
                file_date = source.get("file_date")
                filer_ciks = source.get("ciks", []) or []
                filer_cik = filer_ciks[0] if filer_ciks else None
                subject_url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{int(subject_cik)}/{acc.replace('-', '')}/{acc}.txt"
                )
                targets.append(DownloadTarget(
                    source_type=self.source_type,
                    object_type="TXT",
                    source_url=subject_url,
                    accession_number=acc,
                    filing_date=None,
                    extras={
                        "subject_ticker": ticker,
                        "subject_cik": subject_cik,
                        "filer_cik": filer_cik,
                        "form": form,
                        "file_date": file_date,
                    },
                ))

        if self.limit:
            targets = targets[: self.limit]
        return targets

    # ----- fetch ---------------------------------------------------------

    def fetch(self, target: DownloadTarget, run_id: str) -> FetchResult:
        """Download one filing text; write L1 artifact + manifest row."""
        acc = target.accession_number
        local_path = os.path.join(L1_DIR, f"{acc}.txt")

        con = duckdb.connect(get_db_path())
        manifest_id: Optional[int] = None
        try:
            manifest_id = get_or_create_manifest_row(
                con,
                source_type=self.source_type,
                object_type="TXT",
                source_url=target.source_url,
                accession_number=acc,
                run_id=run_id,
                object_key=acc,  # accession is the natural stable key
                fetch_status="fetching",
                fetch_started_at=datetime.now(),
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()

        # If artifact already present locally and manifest says complete
        # we'd short-circuit; for the scoped run we always fetch once.
        http_code = None
        source_bytes = 0
        error_message: Optional[str] = None
        success = True

        try:
            resp, log = sec_fetch(target.source_url, headers=SEC_HEADERS,
                                  max_retries=3, timeout=30)
            content = resp.content
            source_bytes = len(content)
            http_code = log.http_code
            with open(local_path, "wb") as fh:
                fh.write(content)
        except Exception as exc:  # pylint: disable=broad-except
            success = False
            error_message = str(exc)[:500]

        con = duckdb.connect(get_db_path())
        try:
            update_manifest_status(
                con, manifest_id,
                "complete" if success else "failed",
                fetch_completed_at=datetime.now(),
                http_code=http_code,
                source_bytes=source_bytes,
                local_path=local_path if success else None,
                error_message=error_message,
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()

        return FetchResult(
            target=target,
            manifest_id=manifest_id,
            local_path=local_path if success else None,
            http_code=http_code,
            source_bytes=source_bytes,
            source_checksum=None,
            success=success,
            error_message=error_message,
        )

    # ----- parse ---------------------------------------------------------

    def parse(self, fetch_result: FetchResult) -> ParseResult:
        """Apply regex extractor + §5b QC gates."""
        qc: list[QCFailure] = []
        rows: list[dict[str, Any]] = []
        status = "complete"

        if not fetch_result.success or not fetch_result.local_path:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version="1", schema_version="1",
                qc_failures=[QCFailure(
                    field="_", value=None, rule="fetch_failed", severity="BLOCK"
                )],
            )

        try:
            with open(fetch_result.local_path, "rb") as fh:
                raw = fh.read().decode("utf-8", errors="replace")
        except Exception as exc:  # pylint: disable=broad-except
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version="1", schema_version="1",
                qc_failures=[QCFailure(
                    field="_", value=None, rule=f"read_error:{exc}",
                    severity="BLOCK",
                )],
            )

        text = _clean_text(raw)
        # Truncate to avoid regex pathologies on 2MB+ filings
        if len(text) > 500_000:
            text = text[:500_000]

        extras = fetch_result.target.extras
        form = extras.get("form") or "SC 13G"
        fields = _extract_fields(text, form)

        pct = fields.get("pct_owned")
        shares = fields.get("shares_owned")
        if pct is not None and (pct < 0 or pct > 100):
            qc.append(QCFailure(field="pct_owned", value=pct,
                                rule="pct_out_of_range", severity="BLOCK"))
        if shares is not None and shares != 0 and shares < 100:
            qc.append(QCFailure(field="shares_owned", value=shares,
                                rule="shares_tiny", severity="FLAG"))

        acc = fetch_result.target.accession_number
        filer_cik = (extras.get("filer_cik") or acc.split("-")[0]).zfill(10)
        subject_cik = (extras.get("subject_cik") or "").zfill(10)
        subject_ticker = extras.get("subject_ticker")
        file_date = extras.get("file_date")

        row = {
            "accession_number": acc,
            "filer_cik":        filer_cik,
            "filer_name":       fields.get("reporting_person") or filer_cik,
            "subject_cusip":    fields.get("cusip"),
            "subject_ticker":   subject_ticker,
            "subject_name":     None,
            "filing_type":      form,
            "filing_date":      file_date,
            "report_date":      fields.get("report_date"),
            "pct_owned":        pct,
            "shares_owned":     shares,
            "aggregate_value":  None,
            "intent":           "activist" if "13D" in form else "passive",
            "is_amendment":     "/A" in form,
            "prior_accession":  None,
            "purpose_text":     fields.get("purpose_text"),
            "group_members":    None,
            "manager_cik":      None,
            "name_resolved":    False,
            "entity_id":        None,
            "subject_cik":      subject_cik,
        }
        rows.append(row)

        if any(q.severity == "BLOCK" for q in qc):
            status = "partial"

        return ParseResult(
            fetch_result=fetch_result, rows=rows, parse_status=status,
            parser_version="1", schema_version="1", qc_failures=qc,
        )

    # ----- load_to_staging ----------------------------------------------

    def load_to_staging(self, parse_result: ParseResult,
                        staging_db_path: str, run_id: str) -> int:
        """Upsert stg_13dg_filings + write ingestion_impacts row."""
        if not parse_result.rows:
            return 0
        con = duckdb.connect(staging_db_path)
        try:
            _ensure_staging_schema(con)
            now = datetime.now()
            written = 0
            for row in parse_result.rows:
                qc_flags = json.dumps([
                    {"field": q.field, "rule": q.rule, "severity": q.severity}
                    for q in parse_result.qc_failures
                ]) if parse_result.qc_failures else None
                con.execute(
                    """
                    INSERT OR REPLACE INTO stg_13dg_filings (
                        accession_number, filer_cik, filer_name,
                        subject_cusip, subject_ticker, subject_name,
                        filing_type, filing_date, report_date,
                        pct_owned, shares_owned, aggregate_value,
                        intent, is_amendment, prior_accession,
                        purpose_text, group_members, manager_cik,
                        loaded_at, name_resolved, entity_id,
                        manifest_id, parse_status, qc_flags
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        row["accession_number"], row["filer_cik"], row["filer_name"],
                        row["subject_cusip"], row["subject_ticker"], row["subject_name"],
                        row["filing_type"], row["filing_date"], row["report_date"],
                        row["pct_owned"], row["shares_owned"], row["aggregate_value"],
                        row["intent"], row["is_amendment"], row["prior_accession"],
                        row["purpose_text"], row["group_members"], row["manager_cik"],
                        now, row["name_resolved"], row["entity_id"],
                        parse_result.fetch_result.manifest_id,
                        parse_result.parse_status, qc_flags,
                    ],
                )
                written += 1
                # One impact row per (filer_cik, subject_cusip, accession)
                unit_key = json.dumps({
                    "filer_cik": row["filer_cik"],
                    "subject_cusip": row["subject_cusip"],
                    "accession_number": row["accession_number"],
                })
                write_impact(
                    con,
                    manifest_id=parse_result.fetch_result.manifest_id,
                    target_table="beneficial_ownership_v2",
                    unit_type="filer_subject_accession",
                    unit_key_json=unit_key,
                    report_date=row["report_date"],
                    rows_staged=1,
                    load_status=(
                        "loaded"
                        if parse_result.parse_status == "complete"
                        else "partial"
                    ),
                )
            con.execute("CHECKPOINT")
            return written
        finally:
            con.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_last_run(run_id: str) -> None:
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "logs", "last_run_id.txt"), "w") as fh:
        fh.write(run_id)


def run_dry(subject_tickers: tuple[str, ...]) -> int:
    print("=" * 60)
    print("fetch_13dg_v2.py --dry-run")
    print(f"  subject_tickers: {', '.join(subject_tickers)}")
    print("=" * 60)
    run_id = f"13dg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_dryrun"
    pipeline = Dg13DgPipeline(run_id=run_id, subject_tickers=subject_tickers)
    targets = pipeline.discover(run_id)
    print(f"\n  discover returned {len(targets)} accession(s) to fetch")
    by_ticker: dict[str, int] = {}
    for t in targets:
        k = t.extras.get("subject_ticker", "?")
        by_ticker[k] = by_ticker.get(k, 0) + 1
    for k, n in sorted(by_ticker.items()):
        print(f"    {k}: {n}")
    print("  (no DB writes)")
    return 0


def run_pipeline(subject_tickers: tuple[str, ...],
                 limit: Optional[int]) -> int:
    run_id = f"13dg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _write_last_run(run_id)
    print("=" * 60)
    print(f"fetch_13dg_v2.py  run_id={run_id}")
    print(f"  staging={is_staging_mode()}  limit={limit}")
    print(f"  subject_tickers: {', '.join(subject_tickers)}")
    print("=" * 60)

    pipeline = Dg13DgPipeline(run_id=run_id,
                              subject_tickers=subject_tickers,
                              limit=limit)
    targets = pipeline.discover(run_id)
    print(f"\n  discovered {len(targets)} accession(s)")
    if not targets:
        print("  nothing to fetch")
        return 0

    staging_path = get_db_path()
    t0 = time.time()
    loaded = 0
    parse_failed = 0
    qc_blocked = 0
    for i, target in enumerate(targets, start=1):
        fr = pipeline.fetch(target, run_id)
        if not fr.success:
            parse_failed += 1
            print(f"  [{i}/{len(targets)}] {target.accession_number} "
                  f"FETCH FAIL — {fr.error_message!r}", flush=True)
            continue
        pr = pipeline.parse(fr)
        if pr.parse_status == "failed":
            parse_failed += 1
            continue
        if any(q.severity == "BLOCK" for q in pr.qc_failures):
            qc_blocked += 1
        written = pipeline.load_to_staging(pr, staging_path, run_id)
        loaded += written
        if i % 10 == 0 or i == len(targets):
            elapsed = time.time() - t0
            print(f"    [{i}/{len(targets)}] loaded={loaded} "
                  f"parse_failed={parse_failed} qc_blocked={qc_blocked} "
                  f"elapsed={elapsed:.1f}s", flush=True)

    print(f"\n  DONE  loaded={loaded}  parse_failed={parse_failed}  "
          f"qc_blocked={qc_blocked}  elapsed={time.time() - t0:.1f}s")
    print(f"  run_id: {run_id}  (logs/last_run_id.txt)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="13D/G SourcePipeline (scoped)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tickers", type=str, default=",".join(SCOPED_TICKERS),
                        help="Comma-separated subject tickers")
    parser.add_argument("--staging", action="store_true",
                        help="Write staging DB (default when not --dry-run)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    tickers_raw = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    subject_tickers = tuple(tickers_raw) if tickers_raw else SCOPED_TICKERS

    if args.staging or not args.dry_run:
        set_staging_mode(True)

    if args.dry_run:
        sys.exit(run_dry(subject_tickers))
    sys.exit(run_pipeline(subject_tickers, args.limit))


if __name__ == "__main__":
    crash_handler("fetch_13dg_v2")(main)
