"""load_13dg.py — SourcePipeline for SC 13D / 13D/A / 13G / 13G/A (w2-01).

Absorbs fetch_13dg_v2.py + validate_13dg.py + promote_13dg.py into a
single ``SourcePipeline`` subclass. Parser helpers ``_clean_text`` and
``_extract_fields`` are inlined from the retired ``scripts/fetch_13dg.py``
so this module is self-contained.

Amendment strategy: ``append_is_latest`` on ``beneficial_ownership_v2``
keyed on ``(filer_cik, subject_cusip)``. When a filer amends a prior 13D
or 13G on the same subject, the base class flips the prior row's
``is_latest`` to FALSE and inserts the new row with ``is_latest=TRUE``.

Scope options (event-driven, no quarter):
  * ``{}``                            — default tickers + per-ticker
                                        MAX(filing_date) floor
  * ``{"tickers": ["AR", "OXY"]}``   — explicit ticker list
  * ``{"since": "2026-04-01"}``      — date floor override
  * ``{"tickers": [...], "since": "..."}`` — combine both

Post-promote hooks (override of ``promote()``):
  1. ``bulk_enrich_bo_filers`` — entity enrichment for the new filer
     CIKs (entity_id + rollup columns).
  2. ``rebuild_beneficial_ownership_current`` — L4 view refresh.
  3. Reference-table writes — ``listed_filings_13dg`` and
     ``fetched_tickers_13dg`` UPSERTs.

Entity gate relaxation: unresolved ``filer_cik`` values produce FLAGs,
not BLOCKs. BO filers are often individuals or subject-corporations that
never enter the 13F-centric entity MDM — refusing to promote would
permanently block the event-driven pipeline.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date, datetime
from typing import Any, Optional

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from config import SEC_HEADERS  # noqa: E402
from pipeline.base import (  # noqa: E402
    FetchResult, ParseResult, PromoteResult, SourcePipeline,
    ValidationResult,
)
from pipeline.shared import (  # noqa: E402
    bulk_enrich_bo_filers,
    entity_gate_check,
    rebuild_beneficial_ownership_current,
    sec_fetch,
)


L1_DIR = os.path.join(BASE_DIR, "data", "13dg_raw")

# EDGAR full-text search endpoint + form filter.
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_FORMS = ("SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A")
_DISCOVER_LOOKBACK_YEARS = 4

# Scoped reference universe — same four tickers as the legacy v2 script.
_DEFAULT_TICKERS: tuple[str, ...] = ("AR", "OXY", "EQT", "NFLX")

# Subject-CIK overrides — `securities` has known ticker collisions for
# these four (OXY→PKG cusip, EQT→RJF cusip, etc.), so we never trust the
# ticker→cusip→cik lookup for the scoped set.
_SUBJECT_CIK_OVERRIDES: dict[str, str] = {
    "AR":   "0001433604",  # Antero Resources Corp
    "OXY":  "0000797468",  # Occidental Petroleum Corp
    "EQT":  "0000033213",  # EQT Corp
    "NFLX": "0001065280",  # Netflix Inc
}


# ---------------------------------------------------------------------------
# Target table spec (column list for beneficial_ownership_v2 minus row_id)
# ---------------------------------------------------------------------------

_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("accession_number",    "VARCHAR"),
    ("filer_cik",           "VARCHAR"),
    ("filer_name",          "VARCHAR"),
    ("subject_cusip",       "VARCHAR"),
    ("subject_ticker",      "VARCHAR"),
    ("subject_name",        "VARCHAR"),
    ("filing_type",         "VARCHAR"),
    ("filing_date",         "DATE"),
    ("report_date",         "DATE"),
    ("pct_owned",           "DOUBLE"),
    ("shares_owned",        "BIGINT"),
    ("aggregate_value",     "DOUBLE"),
    ("intent",              "VARCHAR"),
    ("is_amendment",        "BOOLEAN"),
    ("prior_accession",     "VARCHAR"),
    ("purpose_text",        "VARCHAR"),
    ("group_members",       "VARCHAR"),
    ("manager_cik",         "VARCHAR"),
    ("loaded_at",           "TIMESTAMP"),
    ("name_resolved",       "BOOLEAN"),
    ("entity_id",           "BIGINT"),
    ("rollup_entity_id",    "BIGINT"),
    ("rollup_name",         "VARCHAR"),
    ("is_latest",           "BOOLEAN"),
    ("backfill_quality",    "VARCHAR"),
]


_STG_RAW_DDL = """
CREATE TABLE IF NOT EXISTS stg_13dg_raw (
    accession_number  VARCHAR PRIMARY KEY,
    filer_cik         VARCHAR,
    subject_cik       VARCHAR,
    subject_ticker    VARCHAR,
    form              VARCHAR,
    file_date         VARCHAR,
    raw_text          VARCHAR,
    fetched_at        TIMESTAMP
)
"""


_STG_LISTED_DDL = """
CREATE TABLE IF NOT EXISTS stg_13dg_listed (
    accession_number  VARCHAR PRIMARY KEY,
    ticker            VARCHAR,
    form              VARCHAR,
    filing_date       VARCHAR,
    filer_cik         VARCHAR,
    subject_name      VARCHAR,
    subject_cik       VARCHAR,
    listed_at         TIMESTAMP
)
"""


_STG_FETCHED_TICKERS_DDL = """
CREATE TABLE IF NOT EXISTS stg_13dg_fetched_tickers (
    ticker       VARCHAR PRIMARY KEY,
    fetched_at   TIMESTAMP
)
"""


# Typed target staging — mirrors prod beneficial_ownership_v2 minus row_id.
_STG_TARGET_DDL = """
CREATE TABLE IF NOT EXISTS beneficial_ownership_v2 (
    accession_number    VARCHAR,
    filer_cik           VARCHAR,
    filer_name          VARCHAR,
    subject_cusip       VARCHAR,
    subject_ticker      VARCHAR,
    subject_name        VARCHAR,
    filing_type         VARCHAR,
    filing_date         DATE,
    report_date         DATE,
    pct_owned           DOUBLE,
    shares_owned        BIGINT,
    aggregate_value     DOUBLE,
    intent              VARCHAR,
    is_amendment        BOOLEAN,
    prior_accession     VARCHAR,
    purpose_text        VARCHAR,
    group_members       VARCHAR,
    manager_cik         VARCHAR,
    loaded_at           TIMESTAMP,
    name_resolved       BOOLEAN,
    entity_id           BIGINT,
    rollup_entity_id    BIGINT,
    rollup_name         VARCHAR,
    is_latest           BOOLEAN,
    backfill_quality    VARCHAR
)
"""


# ---------------------------------------------------------------------------
# Parser helpers (inlined from retired scripts/fetch_13dg.py)
# ---------------------------------------------------------------------------

def _clean_text(raw: str) -> str:
    """Strip HTML tags/entities and collapse whitespace; fix spaced digits."""
    if len(raw) > 2_000_000:
        raw = raw[:2_000_000]
    text = re.sub(r"<[^>]+>", " ", raw)
    for old, new in [("&nbsp;", " "), ("&#160;", " "), ("&#xa0;", " "),
                     ("&amp;", "&"), ("&#38;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&ldquo;", '"'), ("&rdquo;", '"'), ("&lsquo;", "'"),
                     ("&rsquo;", "'"), ("&sect;", "§"),
                     ("&#x2013;", "-"), ("&#x2014;", "-"),
                     ("&#x2610;", " "), ("&#xA0;", " ")]:
        text = text.replace(old, new)
    text = re.sub(r"&#x[0-9a-fA-F]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)
    return re.sub(r"\s+", " ", text)


def _extract_fields(text: str, filing_type: str) -> dict:
    """Extract ownership fields from cleaned filing text via regex."""
    result: dict = {"cusip": None, "pct_owned": None, "shares_owned": None,
                    "purpose_text": None, "report_date": None,
                    "reporting_person": None}

    m = re.search(r"CUSIP\s*(?:No\.?|Number|#)?\s*[:\s]*([A-Z0-9]{6,9})", text, re.I)
    if m:
        result["cusip"] = m.group(1).strip()

    for pat in [
            r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*[\(\[]?9[\)\]]?[\s.:]*(\d+[\.,]?\d*)\s*%",
            r"13[\.\s]*PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+(?:AMOUNT\s+IN\s+)?ROW\s*[\(\[]?11[\)\]]?\s*(\d+[\.,]?\d*)\s*%",
            r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+(?:AMOUNT\s+IN\s+)?ROW\s*[\(\[]?(?:9|11)[\)\]]?\D{0,80}?(\d{1,3}[\.,]?\d*)\s*%",
            r"Item\s*11[\s.:]+(?:Percent|Pct)\s+of\s+Class\s+(?:Owned|Represented)\D{0,20}?(\d+[\.,]?\d*)\s*%",
            r"Item\s*11[\s.:]+(\d+[\.,]?\d*)\s*%",
            r"(?:Percent|PERCENT|Pct|Percentage)\s+of\s+(?:the\s+)?Class\s*(?:Owned|Represented)?[\s.:]*(\d+[\.,]?\d*)\s*%",
            r"Percentage\s+of\s+Class\s+Represented\s+by\s+Amount\s+in\s+Row\s*[\(\[]?(?:9|11)[\)\]]?[\s.:]*(\d+[\.,]?\d*)\s*%",
            r"percent\s+of\s+class\D{0,60}?(\d{1,3}\.\d+)\s*%",
            r"(?:Resulting|New)\s+(?:situation|percentage)[^%]{0,100}?(\d+[\.,]\d+)\s*%",
            r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+(?:AMOUNT\s+IN\s+)?ROW\s*[\(\[]?(?:9|11)[\)\]]?\D{0,60}?(\d{1,3}[\.,]\d+)",
            r"(?:Percent|Percentage)\s+of\s+Class\s+Represented\s+by\s+Amount\s+in\s+Row\s*[\(\[]?(?:9|11)[\)\]]?\D{5,80}?(\d+[\.,]\d+)\s*%",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if 0 <= val <= 100:
                    result["pct_owned"] = val
            except ValueError:
                pass
            break

    for pat in [
            r"AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED\s+BY\s+EACH\s+REPORTING\s+PERSON[\s.:]*(?:\(\d+\)\s*)?(\d[\d,]+)",
            r"(?:9|11)[\.\s]+AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED[^0-9]{0,60}?(\d[\d,]+)",
            r"Item\s*9[\s.:]+Aggregate\s+Amount\s+(?:Beneficially\s+)?Owned[\s.:]*(\d[\d,]*)",
            r"Aggregate\s+Amount\s+(?:Beneficially\s+)?Owned\s+by\s+Each\s+Reporting\s+Person\D{0,80}?([\d,]{4,})\s*(?:shares)?",
            r"Item\s*9[\s.:]+(\d[\d,]{2,})",
            r"Amount\s+(?:Beneficially\s+)?Owned[\s.:]*(\d[\d,]+)",
            r"SHARED\s+(?:VOTING|DISPOSITIVE)\s+POWER[\s.:]*(\d[\d,]+)",
            r"SOLE\s+VOTING\s+POWER[\s.:]*(\d[\d,]+)",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
                if val == 0 or val >= 100:
                    result["shares_owned"] = val
            except ValueError:
                pass
            break

    for pat in [r"Date\s+of\s+Event\s+Which\s+Requires\s+Filing[^)]*\)\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
                r"Date\s+of\s+Event[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
                r"Date\s+of\s+Event[:\s]*(\d{4}-\d{2}-\d{2})"]:
        m = re.search(pat, text, re.I)
        if m:
            ds = m.group(1).strip()
            for fmt in ["%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"]:
                try:
                    result["report_date"] = datetime.strptime(ds, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass
            break

    if "13D" in filing_type:
        m4 = re.search(r"Item\s*4\.?\s*(?:Purpose\s+of\s+Transaction|Purpose)[.\s]*", text, re.I)
        if m4:
            after = text[m4.end():m4.end() + 3000]
            m5 = re.search(r"Item\s*5", after, re.I)
            purpose = after[:m5.start()] if m5 else after[:600]
            result["purpose_text"] = re.sub(r"\s+", " ", purpose).strip()[:500] or None

    for pat in [
        r"(?:1\s+)?NAMES?\s+OF\s+REPORTING\s+PERSONS?\s*[:\s]*((?:[A-Z][A-Za-z.'&,\s/-]+?){1,6}?)(?=\s*(?:\d\s|CHECK|2\s|Item\s*2|SEC\s+USE))",
        r"Item\s*1[:\s]+Reporting\s+Person\s*[-\u2013\u2014:\s]*([\w\s.,&'/-]+?)(?=\s*(?:Item\s*2|CHECK|\n|2\.))",
        r"NAMES?\s+OF\s+REPORTING\s+PERSONS?\s+I\.?R\.?S\.?[^A-Z]{0,50}([A-Z][A-Za-z.'&,\s/-]{3,80}?)(?=\s*(?:\d\s|CHECK|2\s))",
        r"NAME\s+OF\s+REPORTING\s+PERSON[^A-Z]{0,30}([A-Z][A-Za-z.'&,\(\)\s/-]{3,80}?)(?=\s*(?:\d\s|CHECK|2\s|Item|SEC))",
    ]:
        m = re.search(pat, text[:8000], re.I)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\s+(I\.?R\.?S|S\.?S\.?|Check|CHECK).*$", "", name).strip()
            if (3 < len(name) < 100
                    and name[0].isalpha()
                    and "I.R.S." not in name
                    and "CHECK" not in name.upper()):
                result["reporting_person"] = name
                break

    return result


def _normalize_acc(acc_raw: str) -> str:
    """Normalize accession number to dashed form (0001234567-22-000123)."""
    acc = acc_raw.replace("-", "")
    return f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Load13DGPipeline(SourcePipeline):
    """SourcePipeline for SC 13D/G filings.

    scope = {"tickers": [...], "since": "YYYY-MM-DD"} — both optional.
    Empty scope defaults to the scoped reference universe (AR, OXY, EQT,
    NFLX) with per-ticker ``MAX(filing_date)`` floor from
    ``beneficial_ownership_v2``.
    """

    name = "13dg_ownership"
    target_table = "beneficial_ownership_v2"
    amendment_strategy = "append_is_latest"
    amendment_key = ("filer_cik", "subject_cusip")

    def __init__(self, *, limit: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._limit = limit

    # ---- target_table_spec --------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": ["accession_number", "filer_cik", "subject_cusip", "is_latest"],
            "indexes": [
                ["filer_cik", "subject_cusip"],
                ["subject_ticker"],
                ["filing_date"],
            ],
        }

    # ---- EDGAR helpers (overridable for tests) -------------------------

    def _efts_search_for_subject(
        self,
        subject_cik: str,
        startdt: str,
        enddt: str,
    ) -> list[dict]:
        """Query EDGAR full-text search for SC 13D/G/A about subject_cik."""
        forms = ",".join(_FORMS).replace(" ", "+")
        url = (
            f"{_EFTS_URL}?q=&forms={forms}"
            f"&dateRange=custom&startdt={startdt}&enddt={enddt}"
            f"&ciks={subject_cik}"
        )
        hits: list[dict] = []
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
            total = (data.get("hits", {}) or {}).get("total", {}).get("value", 0)
            if offset >= total:
                break
        return hits

    def _fetch_filing_text(self, source_url: str) -> str:
        """Download one filing body. Instance method so tests can stub it."""
        resp, _ = sec_fetch(source_url, headers=SEC_HEADERS,
                            max_retries=3, timeout=30)
        return resp.content.decode("utf-8", errors="replace")

    def _resolve_subject_cik(self, ticker: str) -> Optional[str]:
        return _SUBJECT_CIK_OVERRIDES.get(ticker)

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        t0 = time.monotonic()
        os.makedirs(L1_DIR, exist_ok=True)

        tickers = tuple(scope.get("tickers") or _DEFAULT_TICKERS)
        since_override: Optional[str] = scope.get("since")
        today_str = date.today().strftime("%Y-%m-%d")

        for ddl in (_STG_RAW_DDL, _STG_LISTED_DDL, _STG_FETCHED_TICKERS_DDL):
            staging_con.execute(ddl)

        # Anti-join: pull accession_numbers already staged to avoid re-fetch
        # on restart. We check staging only — the prod manifest anti-join
        # happens at validate time when we mirror.
        already_staged: set[str] = set()
        try:
            rows = staging_con.execute(
                "SELECT accession_number FROM stg_13dg_raw"
            ).fetchall()
            already_staged = {r[0] for r in rows if r[0]}
        except Exception:  # pylint: disable=broad-except  # nosec B110 — best-effort already-staged probe; empty set is the safe default
            pass

        rows_staged = 0
        for ticker in tickers:
            subject_cik = self._resolve_subject_cik(ticker)
            if not subject_cik:
                continue
            startdt = since_override or self._per_ticker_floor(ticker)
            try:
                hits = self._efts_search_for_subject(subject_cik, startdt, today_str)
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning(
                    "fetch: efts error ticker=%s: %s", ticker, exc,
                )
                continue

            for hit in hits:
                if self._limit is not None and rows_staged >= self._limit:
                    break
                source = hit.get("_source", {}) or {}
                acc_raw = hit.get("_id", "") or source.get("adsh", "")
                acc = acc_raw.split(":")[0] if acc_raw else None
                if not acc:
                    continue
                acc = _normalize_acc(acc)
                if acc in already_staged:
                    continue
                form = source.get("root_form", source.get("form", "")) or ""
                file_date = source.get("file_date")
                filer_ciks = source.get("ciks", []) or []
                filer_cik = (filer_ciks[0] if filer_ciks else "").zfill(10)
                source_url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{int(subject_cik)}/{acc.replace('-', '')}/{acc}.txt"
                )
                try:
                    raw_text = self._fetch_filing_text(source_url)
                except Exception as exc:  # pylint: disable=broad-except
                    self._logger.warning(
                        "fetch: body-fetch error acc=%s: %s", acc, exc,
                    )
                    continue

                staging_con.execute(
                    "INSERT OR REPLACE INTO stg_13dg_raw "
                    "(accession_number, filer_cik, subject_cik, subject_ticker, "
                    " form, file_date, raw_text, fetched_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [acc, filer_cik, subject_cik.zfill(10), ticker, form,
                     file_date, raw_text, datetime.utcnow()],
                )
                staging_con.execute(
                    "INSERT OR REPLACE INTO stg_13dg_listed "
                    "(accession_number, ticker, form, filing_date, filer_cik, "
                    " subject_name, subject_cik, listed_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [acc, ticker, form, file_date, filer_cik, None,
                     subject_cik.zfill(10), datetime.utcnow()],
                )
                staging_con.execute("CHECKPOINT")
                rows_staged += 1
                already_staged.add(acc)

            staging_con.execute(
                "INSERT OR REPLACE INTO stg_13dg_fetched_tickers "
                "(ticker, fetched_at) VALUES (?, ?)",
                [ticker, datetime.utcnow()],
            )

        return FetchResult(
            run_id="",
            rows_staged=rows_staged,
            raw_tables=["stg_13dg_raw", "stg_13dg_listed",
                        "stg_13dg_fetched_tickers"],
            duration_seconds=time.monotonic() - t0,
        )

    def _per_ticker_floor(self, ticker: str) -> str:
        """Return the per-ticker filing_date floor as YYYY-MM-DD.

        Floor = MAX(filing_date) for this ticker in BO v2, or
        (today − 4y) if none present.
        """
        try:
            prod_con = duckdb.connect(self._prod_db_path, read_only=True)
        except Exception:  # pylint: disable=broad-except
            return (date.today().replace(
                year=date.today().year - _DISCOVER_LOOKBACK_YEARS,
            )).strftime("%Y-%m-%d")
        try:
            row = prod_con.execute(
                "SELECT MAX(filing_date) FROM beneficial_ownership_v2 "
                "WHERE subject_ticker = ?",
                [ticker],
            ).fetchone()
        finally:
            prod_con.close()
        if row and row[0]:
            return row[0].strftime("%Y-%m-%d")
        return date.today().replace(
            year=date.today().year - _DISCOVER_LOOKBACK_YEARS,
        ).strftime("%Y-%m-%d")

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        t0 = time.monotonic()

        # Ensure typed target staging exists.
        staging_con.execute("DROP TABLE IF EXISTS beneficial_ownership_v2")
        staging_con.execute(_STG_TARGET_DDL)

        raw_rows = staging_con.execute(
            "SELECT accession_number, filer_cik, subject_cik, subject_ticker, "
            "       form, file_date, raw_text FROM stg_13dg_raw"
        ).fetchall()

        qc_failures: list[dict] = []
        now = datetime.utcnow()
        rows_parsed = 0

        for row in raw_rows:
            (acc, filer_cik, _subject_cik, subject_ticker,
             form, file_date, raw_text) = row
            text = _clean_text(raw_text or "")
            if len(text) > 500_000:
                text = text[:500_000]
            form = form or "SC 13G"
            fields = _extract_fields(text, form)

            pct = fields.get("pct_owned")
            shares = fields.get("shares_owned")
            if pct is not None and (pct < 0 or pct > 100):
                qc_failures.append({
                    "accession_number": acc, "field": "pct_owned",
                    "value": pct, "rule": "pct_out_of_range",
                    "severity": "BLOCK",
                })
                continue
            if shares is not None and 0 < shares < 100:
                qc_failures.append({
                    "accession_number": acc, "field": "shares_owned",
                    "value": shares, "rule": "shares_tiny",
                    "severity": "FLAG",
                })

            staging_con.execute(
                """
                INSERT INTO beneficial_ownership_v2 (
                    accession_number, filer_cik, filer_name,
                    subject_cusip, subject_ticker, subject_name,
                    filing_type, filing_date, report_date,
                    pct_owned, shares_owned, aggregate_value,
                    intent, is_amendment, prior_accession,
                    purpose_text, group_members, manager_cik,
                    loaded_at, name_resolved, entity_id,
                    rollup_entity_id, rollup_name,
                    is_latest, backfill_quality
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    acc,
                    (filer_cik or "").zfill(10) if filer_cik else None,
                    fields.get("reporting_person") or filer_cik,
                    fields.get("cusip"),
                    subject_ticker,
                    None,
                    form,
                    file_date,
                    fields.get("report_date"),
                    pct,
                    shares,
                    None,
                    "activist" if "13D" in form else "passive",
                    "/A" in form,
                    None,
                    fields.get("purpose_text"),
                    None,
                    None,
                    now,
                    False,
                    None,
                    None,
                    None,
                    True,
                    "direct",
                ],
            )
            rows_parsed += 1

        staging_con.execute("CHECKPOINT")

        if rows_parsed == 0 and len(raw_rows) == 0:
            # Not strictly a BLOCK — an empty run is allowed. Mark as WARN
            # via ValidationResult; the validate step flags blocks.
            pass

        return ParseResult(
            run_id="",
            rows_parsed=rows_parsed,
            target_staging_table=self.target_table,
            qc_failures=qc_failures,
            duration_seconds=time.monotonic() - t0,
        )

    # ---- validate ------------------------------------------------------

    def validate(self, staging_con: Any, prod_con: Any) -> ValidationResult:
        vr = ValidationResult()

        staged_count = staging_con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2"
        ).fetchone()[0]
        if staged_count == 0:
            # Empty runs (no new 13D/G filings since last run) are normal
            # for this event-driven pipeline. Allow promote to pass through
            # as a no-op rather than blocking.
            return vr

        dupes = staging_con.execute(
            "SELECT accession_number, COUNT(*) AS n "
            "FROM beneficial_ownership_v2 "
            "GROUP BY accession_number HAVING COUNT(*) > 1"
        ).fetchall()
        for acc, n in dupes:
            vr.blocks.append(f"dup_accession:{acc}:{n}")

        oob = staging_con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2 "
            "WHERE pct_owned IS NOT NULL "
            "  AND (pct_owned < 0 OR pct_owned > 100)"
        ).fetchone()[0]
        if oob:
            vr.blocks.append(f"pct_out_of_range_count={oob}")

        null_pct = staging_con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2 "
            "WHERE pct_owned IS NULL"
        ).fetchone()[0]
        if null_pct:
            vr.warns.append(f"pct_null_count={null_pct}")

        filer_ciks = [
            r[0] for r in staging_con.execute(
                "SELECT DISTINCT filer_cik FROM beneficial_ownership_v2 "
                "WHERE filer_cik IS NOT NULL"
            ).fetchall()
        ]
        if filer_ciks:
            gate = entity_gate_check(
                prod_con,
                source_type="13DG",
                identifier_type="cik",
                staged_identifiers=filer_ciks,
                rollup_types=["economic_control_v1"],
                requires_classification=False,
            )
            # 13D/G relaxation: unresolved filer_cik entries become FLAGs,
            # not BLOCKs. BO filers are often individuals or subject-
            # corporations that never enter the 13F-centric entity MDM.
            for b in gate.blocked:
                vr.flags.append(
                    f"filer_not_in_mdm:{b.get('identifier_value')}"
                )
            if gate.new_entities_pending:
                vr.pending_entities.extend(gate.new_entities_pending)
        return vr

    # ---- promote (override for entity enrichment + reference tables) ---

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        """Delegate BO v2 promote to base class, then run post-promote
        hooks in the same prod connection / transaction boundary:

          1. ``bulk_enrich_bo_filers`` — set entity_id + rollup columns
             for the filers touched by this run.
          2. ``rebuild_beneficial_ownership_current`` — refresh the L4
             latest-per-(filer,subject) snapshot so it picks up the
             enrichment.
          3. Reference-table mirror — listed_filings_13dg and
             fetched_tickers_13dg INSERTs from staging.
        """
        rows = self._read_staged_rows()
        filer_ciks: set[str] = set()
        if not rows.empty and "filer_cik" in rows.columns:
            filer_ciks = {
                c for c in rows["filer_cik"].dropna().tolist() if c
            }

        result = super().promote(run_id, prod_con)

        if not rows.empty:
            try:
                bulk_enrich_bo_filers(prod_con, filer_ciks=filer_ciks)
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning("bulk_enrich_bo_filers: %s", exc)
            try:
                rebuild_beneficial_ownership_current(prod_con)
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning(
                    "rebuild_beneficial_ownership_current: %s", exc,
                )
            self._promote_reference_tables(prod_con)
        return result

    def _promote_reference_tables(self, prod_con: Any) -> None:
        """INSERT listed_filings_13dg + fetched_tickers_13dg from staging.

        Both are dedupe-on-natural-key. Missing target tables are logged
        and skipped — they are reference tables, not fact tables, so the
        pipeline still completes if a legacy install lacks them.
        """
        staging_con = duckdb.connect(self._staging_db_path, read_only=True)
        try:
            try:
                listed_df = staging_con.execute(
                    "SELECT accession_number, ticker, form, filing_date, "
                    "       filer_cik, subject_name, subject_cik, listed_at "
                    "FROM stg_13dg_listed"
                ).fetchdf()
            except Exception:  # pylint: disable=broad-except
                listed_df = None
            try:
                tickers_df = staging_con.execute(
                    "SELECT ticker, fetched_at FROM stg_13dg_fetched_tickers"
                ).fetchdf()
            except Exception:  # pylint: disable=broad-except
                tickers_df = None
        finally:
            staging_con.close()

        if listed_df is not None and not listed_df.empty:
            try:
                prod_con.register("stg_listed_df", listed_df)
                try:
                    prod_con.execute(
                        """
                        INSERT INTO listed_filings_13dg
                        SELECT * FROM stg_listed_df s
                         WHERE NOT EXISTS (
                             SELECT 1 FROM listed_filings_13dg l
                              WHERE l.accession_number = s.accession_number
                         )
                        """
                    )
                finally:
                    prod_con.unregister("stg_listed_df")
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning("listed_filings_13dg insert: %s", exc)

        if tickers_df is not None and not tickers_df.empty:
            try:
                prod_con.register("stg_tickers_df", tickers_df)
                try:
                    prod_con.execute(
                        """
                        INSERT INTO fetched_tickers_13dg
                        SELECT s.ticker, s.fetched_at FROM stg_tickers_df s
                         WHERE NOT EXISTS (
                             SELECT 1 FROM fetched_tickers_13dg f
                              WHERE f.ticker = s.ticker
                         )
                        """
                    )
                    prod_con.execute(
                        """
                        UPDATE fetched_tickers_13dg f
                           SET fetched_at = s.fetched_at
                          FROM stg_tickers_df s
                         WHERE f.ticker = s.ticker
                           AND s.fetched_at > f.fetched_at
                        """
                    )
                finally:
                    prod_con.unregister("stg_tickers_df")
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning("fetched_tickers_13dg insert: %s", exc)

    # ---- cleanup override (drop 13D/G staging too) ---------------------

    def _cleanup_staging(self, run_id: str) -> None:
        super()._cleanup_staging(run_id)
        try:
            staging_con = duckdb.connect(self._staging_db_path)
            try:
                for t in ("stg_13dg_raw", "stg_13dg_listed",
                          "stg_13dg_fetched_tickers"):
                    staging_con.execute(f"DROP TABLE IF EXISTS {t}")
                staging_con.execute("CHECKPOINT")
            finally:
                staging_con.close()
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("cleanup 13D/G staging: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cli(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="13D/G SourcePipeline (w2-01)",
    )
    parser.add_argument("--since", help="Fetch filings since this date (YYYY-MM-DD)")
    parser.add_argument("--tickers", nargs="+",
                        help="Subject tickers (default: AR OXY EQT NFLX)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total accessions fetched.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run through pending_approval; don't promote")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Promote immediately after run() succeeds")
    parser.add_argument("--staging", action="store_true",
                        help="Use staging DB as prod target")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_cli(argv)
    prod_path: Optional[str] = None
    if args.staging:
        from db import STAGING_DB  # type: ignore[import-not-found]
        prod_path = STAGING_DB

    pipeline = Load13DGPipeline(
        limit=args.limit,
        prod_db_path=prod_path,
    )

    scope: dict = {}
    if args.tickers:
        scope["tickers"] = [t.upper() for t in args.tickers]
    if args.since:
        scope["since"] = args.since

    run_id = pipeline.run(scope)
    print(f"run_id: {run_id}")

    if args.dry_run:
        print(f"Dry run complete. Call approve_and_promote({run_id!r}) "
              f"from the admin UI/REPL when ready.")
        return 0

    if args.auto_approve:
        result = pipeline.approve_and_promote(run_id)
        print(
            f"Promoted run_id={run_id}: "
            f"inserted={result.rows_inserted} flipped={result.rows_flipped}"
        )
    else:
        print(
            f"Run {run_id} ready for approval. Call "
            f"approve_and_promote({run_id!r}) or re-run with --auto-approve."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
