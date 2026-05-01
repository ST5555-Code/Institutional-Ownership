"""load_nport.py — SourcePipeline for N-PORT monthly fund holdings (w2-03).

Absorbs ``scripts/fetch_nport_v2.py`` (4-mode orchestrator),
``scripts/validate_nport_subset.py`` (fast set-based QC) and
``scripts/promote_nport.py`` (DELETE+INSERT promote + Group-2 entity
enrichment + fund_universe upsert) into a single ``SourcePipeline``
subclass on ``fund_holdings_v2``.

Amendment strategy ``append_is_latest`` keyed on
``(series_id, report_month)``. When an N-PORT-P/A supersedes an earlier
filing, the base class flips the prior row's ``is_latest=FALSE`` and
inserts the new row with ``is_latest=TRUE`` — a step up from legacy
promote_nport.py which DELETE'd history entirely.

Scope options:
  * ``{"quarter": "2026Q1"}``           — DERA bulk ZIP for that quarter
  * ``{}`` (empty)                      — DERA bulk; auto-discover the
                                           missing quarters
  * ``{"monthly_topup": True}``         — per-accession XML top-up for
                                           the current calendar quarter
  * ``{"month": "2026-03"}``            — per-accession XML for one
                                           specific month
  * ``{"zip_path": "/path/to.zip"}``    — optional combinator; use a
                                           local ZIP instead of downloading
  * ``{"exclude_file": "path.csv"}``    — optional combinator; series_ids
                                           to hold out of the typed staging

Post-promote hooks (override of ``promote()``):
  1. UPSERT ``fund_universe`` from staged ``stg_nport_fund_universe``.
  2. Group 2 entity enrichment — populates ``entity_id`` /
     ``rollup_entity_id`` / ``dm_entity_id`` / ``dm_rollup_entity_id`` /
     ``dm_rollup_name`` on the newly-inserted ``is_latest=TRUE`` rows.
  3. ``refresh_snapshot()`` — copy prod to ``13f_readonly.duckdb``.

Entity gate relaxation: unresolved ``series_id`` values surface as
FLAGs, not BLOCKs. The legacy path queued them in
``pending_entity_resolution`` via the entity_gate_check side effect;
that behaviour is preserved here.

``fetch_dera_nport.py`` is imported as a transport-layer helper (ZIP
download + TSV parsing + amendment resolution); this module wraps those
primitives in the framework pattern without modifying their internals.
``pipeline.nport_parsers`` stays the shared XML parsing library for the
monthly XML top-up path.

PR-2 lock semantics (``_apply_fund_strategy_lock`` + ``_upsert_fund_universe``):
once a series_id has a non-NULL ``fund_strategy`` in prod ``fund_universe``
the value is treated as canonical and is preserved on subsequent N-PORT
loads. The classifier output is only written when (a) the series is new
(no row in ``fund_universe`` yet) or (b) the existing row carries a NULL
``fund_strategy`` (backfill case). Without this lock, every monthly top-up
would re-classify from the per-filing fund name and silently overwrite
hand-curated reclassifications like the QQQ / Target Date / leveraged ETF
sweep done in PR-2. Same lock applies to ``fund_holdings_v2`` rows being
inserted for the run — the staged ``fund_strategy`` is rewritten to the
locked value before ``super().promote()`` runs so historical and new
holdings stay consistent with the canonical fund-level value.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from typing import Any, Optional

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from config import SEC_HEADERS  # noqa: E402
from fetch_dera_nport import (  # noqa: E402
    _ensure_staging_schema,
    build_dera_dataset,
    download_dera_zip,
    parse_quarter,
    quarter_label_for_date,
    resolve_amendments,
)
from pipeline.base import (  # noqa: E402
    FetchResult, ParseResult, PromoteResult, SourcePipeline,
    ValidationResult,
)
from pipeline.nport_parsers import classify_fund, parse_nport_xml  # noqa: E402
from pipeline.shared import (  # noqa: E402
    entity_gate_check,
    refresh_snapshot,
    sec_fetch,
)


L1_DIR = os.path.join(BASE_DIR, "data", "nport_raw")

# First DERA N-PORT ZIP published for 2019Q4. Anything earlier is XML-only.
_DERA_EPOCH = (2019, 4)


# ---------------------------------------------------------------------------
# Target table spec (column list for fund_holdings_v2 minus row_id)
# ---------------------------------------------------------------------------

_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("fund_cik",             "VARCHAR"),
    ("fund_name",            "VARCHAR"),
    ("family_name",          "VARCHAR"),
    ("series_id",            "VARCHAR"),
    ("quarter",              "VARCHAR"),
    ("report_month",         "VARCHAR"),
    ("report_date",          "DATE"),
    ("cusip",                "VARCHAR"),
    ("isin",                 "VARCHAR"),
    ("issuer_name",          "VARCHAR"),
    ("ticker",               "VARCHAR"),
    ("asset_category",       "VARCHAR"),
    ("shares_or_principal",  "DOUBLE"),
    ("market_value_usd",     "DOUBLE"),
    ("pct_of_nav",           "DOUBLE"),
    ("fair_value_level",     "VARCHAR"),
    ("is_restricted",        "BOOLEAN"),
    ("payoff_profile",       "VARCHAR"),
    ("loaded_at",             "TIMESTAMP"),
    ("fund_strategy_at_filing", "VARCHAR"),
    ("entity_id",            "BIGINT"),
    ("rollup_entity_id",     "BIGINT"),
    ("dm_entity_id",         "BIGINT"),
    ("dm_rollup_entity_id",  "BIGINT"),
    ("dm_rollup_name",       "VARCHAR"),
    ("accession_number",     "VARCHAR"),
    ("is_latest",            "BOOLEAN"),
    ("backfill_quality",     "VARCHAR"),
]


# Typed target staging — mirrors prod fund_holdings_v2 minus row_id.
_STG_TARGET_DDL = (
    "CREATE TABLE fund_holdings_v2 (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)


# ---------------------------------------------------------------------------
# Helper: report_month future gate (ported from promote_nport obs-07)
# ---------------------------------------------------------------------------

def _assert_no_future_report_month(staging_con: Any) -> list[str]:
    """Return a list of BLOCK reasons for staged rows whose report_month is
    strictly greater than the current calendar month.

    N-PORT-P reports period-end holdings at monthly grain. A report_month
    in the future is always a date-parse bug or a typo. Called during
    validate().
    """
    try:
        offenders = staging_con.execute(
            """
            SELECT series_id, report_month, COUNT(*) AS rows
              FROM fund_holdings_v2
             WHERE report_month > strftime(CURRENT_DATE, '%Y-%m')
             GROUP BY 1, 2
             ORDER BY 2 DESC, 1
             LIMIT 20
            """
        ).fetchall()
    except Exception:  # pylint: disable=broad-except
        return []
    if not offenders:
        return []
    parts = [f"{sid}:{rm}:{n}" for sid, rm, n in offenders]
    return [f"report_month_in_future[{','.join(parts)}]"]


# ---------------------------------------------------------------------------
# Helper: read exclude_file if provided
# ---------------------------------------------------------------------------

def _read_exclude_file(path: Optional[str]) -> set[str]:
    if not path:
        return set()
    try:
        with open(path, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        return set()


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------

def _last_complete_dera_quarter(today: Optional[date] = None) -> tuple[int, int]:
    t = today or date.today()
    q_now = (t.month - 1) // 3 + 1
    if q_now == 1:
        return t.year - 1, 4
    return t.year, q_now - 1


def _quarter_after(year: int, quarter: int) -> tuple[int, int]:
    if quarter == 4:
        return year + 1, 1
    return year, quarter + 1


def _already_loaded_quarters(prod_con: Any) -> set[tuple[int, int]]:
    """Scan ingestion_manifest for DERA_ZIP completion markers."""
    out: set[tuple[int, int]] = set()
    try:
        rows = prod_con.execute(
            "SELECT object_key FROM ingestion_manifest "
            "WHERE source_type = 'NPORT' "
            "  AND object_type = 'DERA_ZIP' "
            "  AND fetch_status = 'complete'"
        ).fetchall()
    except Exception:  # pylint: disable=broad-except
        return out
    for (key,) in rows:
        if not key or not key.startswith("DERA_ZIP:"):
            continue
        try:
            y, q = parse_quarter(key.split(":", 1)[1])
            out.add((y, q))
        except ValueError:
            continue
    return out


def _discover_missing_quarters(
    prod_con: Any, today: Optional[date] = None,
) -> list[tuple[int, int]]:
    last = _last_complete_dera_quarter(today)
    loaded = _already_loaded_quarters(prod_con)

    try:
        prod_newest = prod_con.execute(
            "SELECT MAX(report_date) FROM fund_holdings_v2"
        ).fetchone()[0]
    except Exception:  # pylint: disable=broad-except
        prod_newest = None

    if not loaded:
        seed_count = 4 if prod_newest is None else 2
        cur = last
        picks = [cur]
        for _ in range(seed_count - 1):
            y, q = cur
            cur = (y - 1, 4) if q == 1 else (y, q - 1)
            picks.append(cur)
        candidates = sorted(picks)
    else:
        start = _quarter_after(*max(loaded))
        candidates = []
        cur = start
        while cur <= last:
            candidates.append(cur)
            cur = _quarter_after(*cur)

    return [yq for yq in candidates
            if yq >= _DERA_EPOCH and yq not in loaded]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class LoadNPortPipeline(SourcePipeline):
    """SourcePipeline for SEC N-PORT monthly fund holdings."""

    name = "nport_holdings"
    target_table = "fund_holdings_v2"
    amendment_strategy = "append_is_latest"
    amendment_key = ("series_id", "report_month")

    def __init__(self, *, limit: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._limit = limit
        self._exclude: set[str] = set()

    # ---- target_table_spec --------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": ["series_id", "report_month", "cusip", "is_latest"],
            "indexes": [
                ["series_id", "report_month"],
                ["fund_cik"],
                ["cusip"],
                ["report_date"],
            ],
        }

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        t0 = time.monotonic()

        # Capture optional exclude list for use by parse(). Surviving the
        # fetch/parse boundary via instance state keeps the scope contract
        # thin — we don't need to teach parse() about scope.
        self._exclude = _read_exclude_file(scope.get("exclude_file"))

        # Ensure raw staging tables exist on the provided connection. The
        # base class owns staging_con's lifecycle; opening a second writer
        # would deadlock DuckDB's single-writer file lock.
        _ensure_staging_schema(staging_con)

        # INF50: detect leftover rows from a prior run whose
        # _cleanup_staging silently failed. Without this guard, parse()
        # would pull both the new run's rows AND the leftovers into
        # fund_holdings_v2 typed staging (parse runs an unfiltered SELECT
        # over stg_nport_holdings).
        self._purge_stale_raw_staging(staging_con)

        if scope.get("monthly_topup") or scope.get("month"):
            return self._fetch_xml_topup(scope, staging_con, t0)

        return self._fetch_dera_bulk(scope, staging_con, t0)

    def _purge_stale_raw_staging(self, staging_con: Any) -> None:
        """Pre-fetch guard (INF50). Drop leftover rows from stg_nport_*
        before this run begins writing.

        At the start of fetch(), any rows already in raw staging are by
        definition from a prior run — _cleanup_staging is supposed to
        have dropped the tables entirely. If rows are present, the prior
        cleanup failed (historically silently). Log a WARNING with the
        count and DELETE before proceeding so parse() does not pull the
        leftovers into fund_holdings_v2.
        """
        for t in ("stg_nport_holdings", "stg_nport_fund_universe"):
            try:
                n = staging_con.execute(
                    f"SELECT COUNT(*) FROM {t}"  # nosec B608
                ).fetchone()[0]
            except duckdb.CatalogException:
                # Table absent — _ensure_staging_schema is supposed to
                # have created it; missing here means the schema helper
                # was bypassed. Skip silently; the next CREATE will
                # surface any underlying problem.
                continue
            if n > 0:
                self._logger.warning(
                    "_purge_stale_raw_staging: %s carries %d leftover "
                    "rows from a prior run; auto-purging before fetch "
                    "begins (INF50 — prior _cleanup_staging may have "
                    "silently failed)", t, n,
                )
                staging_con.execute(f"DELETE FROM {t}")  # nosec B608
        staging_con.execute("CHECKPOINT")

    # ---- fetch: DERA bulk path ----------------------------------------

    def _fetch_dera_bulk(
        self, scope: dict, staging_con: Any, t0: float,
    ) -> FetchResult:
        zip_spec = scope.get("zip_path")
        quarter_label = scope.get("quarter")

        if quarter_label:
            year, quarter = parse_quarter(quarter_label)
            quarters = [(year, quarter)]
        else:
            # Auto-discover against prod. Use a read-only prod handle so
            # staging_con stays the sole writer on the staging DB.
            prod_ro = duckdb.connect(self._prod_db_path, read_only=True)
            try:
                quarters = _discover_missing_quarters(prod_ro)
            finally:
                prod_ro.close()
            if self._limit is not None:
                quarters = quarters[:self._limit]

        total_holdings = 0
        for year, quarter in quarters:
            self._logger.info(
                "_fetch_dera_bulk: loading %dQ%d zip_spec=%s",
                year, quarter, zip_spec,
            )
            zip_path = download_dera_zip(year, quarter, zip_spec=zip_spec)
            dataset = build_dera_dataset(zip_path, filter_ciks=None)

            # Within-ZIP dedupe only — cross-ZIP dedupe would require a
            # read-only staging handle, which DuckDB refuses while the
            # write handle is live. The diff/anomaly step in validate()
            # surfaces any cross-ZIP duplicates via the dup-tuple BLOCK.
            submissions_kept = resolve_amendments(
                dataset["submissions"], staging_con=None,
            )

            total_holdings += self._write_dera_to_staging(
                dataset, submissions_kept, staging_con, year, quarter,
            )

        staging_con.execute("CHECKPOINT")

        return FetchResult(
            run_id="",
            rows_staged=total_holdings,
            raw_tables=["stg_nport_holdings", "stg_nport_fund_universe"],
            duration_seconds=time.monotonic() - t0,
        )

    def _write_dera_to_staging(
        self,
        dataset: dict,
        submissions_kept: list[dict],
        staging_con: Any,
        year: int,
        quarter: int,
    ) -> int:
        """Write DERA rows to ``stg_nport_holdings`` + ``stg_nport_fund_universe``.

        Adapted from ``fetch_dera_nport.load_to_staging`` with the
        connection injected by the framework rather than opened
        internally. Skips the legacy ingestion_manifest / ingestion_impacts
        writes in staging — the prod manifest (created by
        ``SourcePipeline.run``) is now the single control-plane record.
        """
        holdings_by_acc = dataset["holdings_by_accession"]
        now = datetime.utcnow()
        holdings_written = 0
        progress_every = 500
        t0 = time.time()
        zip_tag = f"DERA:{year}Q{quarter}"

        for idx, sub in enumerate(submissions_kept, start=1):
            acc = sub["accession_number"]
            holdings = holdings_by_acc.get(acc, [])
            if not holdings:
                continue

            metadata = {
                "series_name": sub["fund_name"],
                "reg_name": sub["family_name"],
                "series_id": sub["series_id"],
                "is_final": "Y" if sub["is_final"] else None,
                "net_assets": sub["total_net_assets"],
            }
            _is_active_equity, fund_category, is_actively_managed = classify_fund(
                metadata, holdings,
            )

            qc_flags = (
                json.dumps([{
                    "field": "series_id",
                    "rule": "series_id_synthetic_fallback",
                    "severity": "FLAG",
                }])
                if "_" in sub["series_id"]
                   and not sub["series_id"].startswith("S")
                else None
            )

            # Replace prior rows for this (series, month) — idempotent on
            # re-runs of the same quarter.
            staging_con.execute(
                "DELETE FROM stg_nport_holdings "
                "WHERE series_id = ? AND report_month = ?",
                [sub["series_id"], sub["report_month"]],
            )

            payload = [
                [
                    sub["fund_cik"], sub["fund_name"], sub["family_name"],
                    sub["series_id"], sub["quarter"], sub["report_month"],
                    sub["report_date"], h["cusip"], h["isin"],
                    h["issuer_name"], h["ticker"], h["asset_cat"],
                    h["balance"], h["val_usd"], h["pct_val"],
                    h["fair_val_level"], h["is_restricted"],
                    h["payoff_profile"], now, fund_category, None, acc,
                    None, "complete", qc_flags,
                ]
                for h in holdings
            ]
            staging_con.executemany(
                """
                INSERT INTO stg_nport_holdings (
                    fund_cik, fund_name, family_name, series_id,
                    quarter, report_month, report_date, cusip, isin,
                    issuer_name, ticker, asset_category,
                    shares_or_principal, market_value_usd, pct_of_nav,
                    fair_value_level, is_restricted, payoff_profile,
                    loaded_at, fund_strategy, best_index,
                    accession_number, manifest_id, parse_status, qc_flags
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )
            holdings_written += len(holdings)

            staging_con.execute(
                "DELETE FROM stg_nport_fund_universe WHERE series_id = ?",
                [sub["series_id"]],
            )
            staging_con.execute(
                """
                INSERT INTO stg_nport_fund_universe (
                    fund_cik, fund_name, series_id, family_name,
                    total_net_assets, fund_category, is_actively_managed,
                    total_holdings_count, equity_pct, top10_concentration,
                    last_updated, fund_strategy, best_index, manifest_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    sub["fund_cik"], sub["fund_name"], sub["series_id"],
                    sub["family_name"], sub["total_net_assets"],
                    fund_category, is_actively_managed,
                    len(holdings), None, None, now,
                    fund_category, None, None,
                ],
            )

            if idx % progress_every == 0:
                elapsed = time.time() - t0
                rate = idx / elapsed if elapsed else 0.0
                self._logger.info(
                    "%s: [%d/%d] %d holdings, %.1f acc/s",
                    zip_tag, idx, len(submissions_kept),
                    holdings_written, rate,
                )

        return holdings_written

    # ---- fetch: XML monthly top-up path --------------------------------

    def _fetch_xml_topup(
        self, scope: dict, staging_con: Any, t0: float,
    ) -> FetchResult:
        # Late import — edgar pulls in heavy deps we don't want at module
        # load for scopes that never hit this branch.
        from edgar import get_filings  # noqa: WPS433
        from config import configure_edgar_identity  # noqa: WPS433

        configure_edgar_identity()

        target_month: Optional[str] = scope.get("month")
        if target_month:
            year, month = (int(p) for p in target_month.split("-"))
            year_q = year
            q = (month - 1) // 3 + 1
        else:
            today = date.today()
            year_q, q = today.year, (today.month - 1) // 3 + 1

        try:
            q_filings = get_filings(year=year_q, quarter=q, form="NPORT-P")
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("_fetch_xml_topup: get_filings failed: %s", exc)
            return FetchResult(
                run_id="", rows_staged=0,
                raw_tables=["stg_nport_holdings", "stg_nport_fund_universe"],
                duration_seconds=time.monotonic() - t0,
            )
        if q_filings is None:
            return FetchResult(
                run_id="", rows_staged=0,
                raw_tables=["stg_nport_holdings", "stg_nport_fund_universe"],
                duration_seconds=time.monotonic() - t0,
            )

        df = q_filings.data.to_pandas()

        # Anti-join the prod manifest for accessions we already ingested.
        prod_ro = duckdb.connect(self._prod_db_path, read_only=True)
        try:
            try:
                already = {
                    r[0] for r in prod_ro.execute(
                        "SELECT accession_number FROM ingestion_manifest "
                        "WHERE source_type = 'NPORT' "
                        "  AND fetch_status = 'complete'"
                    ).fetchall()
                }
            except Exception:  # pylint: disable=broad-except
                already = set()
        finally:
            prod_ro.close()

        os.makedirs(L1_DIR, exist_ok=True)

        rows_staged = 0
        for _, row in df.iterrows():
            acc = row["accession_number"]
            if acc in already:
                continue
            if target_month:
                filing_month = str(row.get("filing_date", ""))[:7]
                if filing_month != target_month:
                    continue
            if self._limit is not None and rows_staged >= self._limit:
                break
            cik = int(row["cik"])
            url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik}/{acc.replace('-', '')}/primary_doc.xml"
            )
            try:
                resp, _ = sec_fetch(
                    url, headers=SEC_HEADERS, max_retries=3, timeout=30,
                )
                xml_bytes = resp.content
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning(
                    "_fetch_xml_topup: sec_fetch acc=%s: %s", acc, exc,
                )
                continue

            metadata, holdings = parse_nport_xml(xml_bytes)
            if metadata is None or not holdings:
                continue

            series_id = metadata.get("series_id")
            reg_cik = metadata.get("reg_cik") or str(cik).zfill(10)
            if not series_id:
                series_id = f"{reg_cik.lstrip('0') or '0'}_{acc}"

            rep_pd = metadata.get("rep_pd_date") or metadata.get("rep_pd_end")
            if not rep_pd:
                continue
            try:
                rep_dt = datetime.strptime(rep_pd, "%Y-%m-%d").date()
            except ValueError:
                continue

            report_month = rep_dt.strftime("%Y-%m")
            quarter_label = quarter_label_for_date(rep_dt)
            _is_active_equity, fund_category, is_actively_managed = classify_fund(
                metadata, holdings,
            )

            cik_padded = (reg_cik or "0").lstrip("0").zfill(10)
            fund_name = metadata.get("series_name") or metadata.get("reg_name")
            family_name = metadata.get("reg_name")
            now = datetime.utcnow()

            rows_staged += self._write_xml_to_staging(
                staging_con=staging_con,
                series_id=series_id,
                report_month=report_month,
                fund_cik=cik_padded,
                fund_name=fund_name,
                family_name=family_name,
                report_date=rep_dt,
                quarter_label=quarter_label,
                accession=acc,
                fund_category=fund_category,
                is_actively_managed=is_actively_managed,
                total_net_assets=(
                    float(metadata["net_assets"])
                    if metadata.get("net_assets") else None
                ),
                total_holdings_count=len(holdings),
                holdings=holdings,
                now=now,
            )

        staging_con.execute("CHECKPOINT")

        return FetchResult(
            run_id="",
            rows_staged=rows_staged,
            raw_tables=["stg_nport_holdings", "stg_nport_fund_universe"],
            duration_seconds=time.monotonic() - t0,
        )

    def _write_xml_to_staging(
        self,
        *,
        staging_con: Any,
        series_id: str,
        report_month: str,
        fund_cik: str,
        fund_name: Optional[str],
        family_name: Optional[str],
        report_date: date,
        quarter_label: str,
        accession: str,
        fund_category: Optional[str],
        is_actively_managed: Optional[bool],
        total_net_assets: Optional[float],
        total_holdings_count: int,
        holdings: list[dict],
        now: datetime,
    ) -> int:
        staging_con.execute(
            "DELETE FROM stg_nport_holdings "
            "WHERE series_id = ? AND report_month = ?",
            [series_id, report_month],
        )
        payload = []
        for h in holdings:
            payload.append([
                fund_cik, fund_name, family_name, series_id, quarter_label,
                report_month, report_date,
                h.get("cusip"), h.get("isin"), h.get("name"), h.get("ticker"),
                h.get("asset_cat"),
                float(h["balance"]) if h.get("balance") else None,
                float(h["val_usd"]) if h.get("val_usd") else None,
                float(h["pct_val"]) if h.get("pct_val") else None,
                h.get("fair_val_level"),
                h.get("is_restricted") == "Y" if h.get("is_restricted") else False,
                h.get("payoff_profile"), now, fund_category, None, accession,
                None, "complete", None,
            ])
        staging_con.executemany(
            """
            INSERT INTO stg_nport_holdings (
                fund_cik, fund_name, family_name, series_id,
                quarter, report_month, report_date, cusip, isin,
                issuer_name, ticker, asset_category,
                shares_or_principal, market_value_usd, pct_of_nav,
                fair_value_level, is_restricted, payoff_profile,
                loaded_at, fund_strategy, best_index,
                accession_number, manifest_id, parse_status, qc_flags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            payload,
        )

        staging_con.execute(
            "DELETE FROM stg_nport_fund_universe WHERE series_id = ?",
            [series_id],
        )
        staging_con.execute(
            """
            INSERT INTO stg_nport_fund_universe (
                fund_cik, fund_name, series_id, family_name,
                total_net_assets, fund_category, is_actively_managed,
                total_holdings_count, equity_pct, top10_concentration,
                last_updated, fund_strategy, best_index, manifest_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                fund_cik, fund_name, series_id, family_name,
                total_net_assets, fund_category, is_actively_managed,
                total_holdings_count, None, None, now,
                fund_category, None, None,
            ],
        )
        return len(payload)

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        t0 = time.monotonic()

        staging_con.execute("DROP TABLE IF EXISTS fund_holdings_v2")
        staging_con.execute(_STG_TARGET_DDL)

        exclude_list = sorted(self._exclude) if self._exclude else []
        if exclude_list:
            placeholders = ",".join("?" * len(exclude_list))
            excl_sql = f"AND s.series_id NOT IN ({placeholders})"
            params: list[Any] = list(exclude_list)
        else:
            excl_sql = ""
            params = []

        staging_con.execute(
            f"""
            INSERT INTO fund_holdings_v2 (
                fund_cik, fund_name, family_name, series_id,
                quarter, report_month, report_date, cusip, isin,
                issuer_name, ticker, asset_category,
                shares_or_principal, market_value_usd, pct_of_nav,
                fair_value_level, is_restricted, payoff_profile,
                loaded_at, fund_strategy_at_filing,
                entity_id, rollup_entity_id, dm_entity_id,
                dm_rollup_entity_id, dm_rollup_name,
                accession_number, is_latest, backfill_quality
            )
            SELECT
                s.fund_cik, s.fund_name, s.family_name, s.series_id,
                s.quarter, s.report_month, s.report_date, s.cusip, s.isin,
                s.issuer_name, s.ticker, s.asset_category,
                s.shares_or_principal, s.market_value_usd, s.pct_of_nav,
                s.fair_value_level, s.is_restricted, s.payoff_profile,
                NOW() AS loaded_at, s.fund_strategy AS fund_strategy_at_filing,
                NULL AS entity_id, NULL AS rollup_entity_id,
                NULL AS dm_entity_id, NULL AS dm_rollup_entity_id,
                NULL AS dm_rollup_name,
                s.accession_number,
                TRUE AS is_latest,
                'direct' AS backfill_quality
            FROM stg_nport_holdings s
            WHERE 1 = 1
              {excl_sql}
            """,  # nosec B608
            params,
        )
        staging_con.execute("CHECKPOINT")

        rows_parsed = staging_con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2"
        ).fetchone()[0]

        qc_failures: list[dict] = []
        if rows_parsed == 0:
            qc_failures.append({
                "field": "_", "rule": "zero_rows_parsed", "severity": "BLOCK",
            })

        dup = staging_con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT series_id, report_month, accession_number, COUNT(*) AS n "
            "  FROM fund_holdings_v2 "
            "  GROUP BY 1, 2, 3 "
            "  HAVING COUNT(*) > 1 AND COUNT(DISTINCT accession_number) > 1"
            ") t"
        ).fetchone()[0]
        if dup:
            qc_failures.append({
                "field": "accession_number",
                "rule": f"{dup}_dup_accession_per_series_month",
                "severity": "BLOCK",
            })

        if exclude_list:
            qc_failures.append({
                "field": "series_id",
                "rule": f"{len(exclude_list)}_series_excluded",
                "severity": "FLAG",
            })

        return ParseResult(
            run_id="",
            rows_parsed=int(rows_parsed),
            target_staging_table=self.target_table,
            qc_failures=qc_failures,
            duration_seconds=time.monotonic() - t0,
        )

    # ---- validate ------------------------------------------------------

    def validate(self, staging_con: Any, prod_con: Any) -> ValidationResult:
        vr = ValidationResult()

        staged_count = staging_con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2"
        ).fetchone()[0]
        if staged_count == 0:
            # Empty top-up runs are normal; let the promote step no-op.
            return vr

        # BLOCK: duplicate accessions within a (series, month) tuple.
        dupes = staging_con.execute(
            """
            SELECT series_id, report_month, COUNT(DISTINCT accession_number)
              FROM fund_holdings_v2
             GROUP BY 1, 2
            HAVING COUNT(DISTINCT accession_number) > 1
             LIMIT 20
            """
        ).fetchall()
        for sid, rm, n in dupes:
            vr.blocks.append(f"dup_accession:{sid}:{rm}:{n}")

        # BLOCK: report_month in the future (obs-07 gate).
        vr.blocks.extend(_assert_no_future_report_month(staging_con))

        # Entity gate — N-PORT relaxation: unresolved series_id → FLAG.
        series_ids = [
            r[0] for r in staging_con.execute(
                "SELECT DISTINCT series_id FROM fund_holdings_v2 "
                "WHERE series_id IS NOT NULL"
            ).fetchall()
        ]
        if series_ids:
            try:
                gate = entity_gate_check(
                    prod_con,
                    source_type="NPORT",
                    identifier_type="series_id",
                    staged_identifiers=series_ids,
                    rollup_types=[
                        "economic_control_v1", "decision_maker_v1",
                    ],
                    requires_classification=False,
                )
            except Exception as exc:  # pylint: disable=broad-except
                # In contexts where the prod DB lacks entity tables
                # (unit-test fixtures), surface as a FLAG rather than
                # aborting the pipeline.
                vr.flags.append(f"entity_gate_skipped:{exc}")
            else:
                for b in gate.blocked:
                    vr.flags.append(
                        f"series_not_in_mdm:{b.get('identifier_value')}"
                    )
                if gate.new_entities_pending:
                    vr.pending_entities.extend(gate.new_entities_pending)

        # WARN: row-count outside expected cadence range.
        try:
            from pipeline.cadence import PIPELINE_CADENCE  # noqa: WPS433
            ranges = PIPELINE_CADENCE[self.name].get("expected_delta", {})
        except Exception:  # pylint: disable=broad-except
            ranges = {}
        min_rows = ranges.get("min_rows")
        max_rows = ranges.get("max_rows")
        if min_rows is not None and staged_count < min_rows:
            vr.warns.append(
                f"row_count={staged_count} below min_rows={min_rows}"
            )
        if max_rows is not None and staged_count > max_rows:
            vr.warns.append(
                f"row_count={staged_count} above max_rows={max_rows}"
            )

        return vr

    # ---- promote (override for universe + entity enrichment) ----------

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        """Delegate holdings promote to base class, then run post-promote
        hooks in the same prod connection / transaction boundary.

        Step ordering (INF52): enrich → promote → re-enrich.

          0. Pre-promote entity enrichment — populate Group 2 columns
             (entity_id / rollup_entity_id / dm_entity_id /
             dm_rollup_entity_id / dm_rollup_name) on
             ``staging.fund_holdings_v2`` BEFORE super().promote()
             runs. Without this, the int-23 downgrade-refusal guard
             inside ``_promote_append_is_latest`` would see all-NULL
             staged values flipping is_latest on (series, month) keys
             where prod has populated values and would refuse the
             promote — which is what bit the 2026-04-27 topup on
             amendment-heavy reports.
          1. Base append_is_latest — prior (series, month) rows flip to
             is_latest=FALSE, staged rows INSERT as is_latest=TRUE.
          2. UPSERT fund_universe from stg_nport_fund_universe.
          3. Bulk Group 2 entity enrichment (safety net) — idempotent
             refresh over the touched series_ids in case prod's MDM
             state shifted between pre-enrich and promote.
        """
        rows = self._read_staged_rows()
        series_touched: set[str] = set()
        if not rows.empty and "series_id" in rows.columns:
            series_touched = {
                s for s in rows["series_id"].dropna().tolist() if s
            }

        if not rows.empty:
            self._enrich_staging_entities(prod_con, series_touched)
            # PR-2: lock prod's canonical fund_strategy before super().promote
            # writes staged holdings rows. For series whose prod
            # fund_universe row already carries a non-NULL fund_strategy,
            # the staged value is rewritten to the prod value so the new
            # holdings rows do not drift away from the canonical label.
            self._apply_fund_strategy_lock(prod_con, series_touched)

        result = super().promote(run_id, prod_con)

        if not rows.empty:
            self._upsert_fund_universe(prod_con, series_touched)
            self._bulk_enrich_run(prod_con, series_touched)
        return result

    def _enrich_staging_entities(
        self, prod_con: Any, series_touched: set[str],
    ) -> int:
        """Pre-promote enrichment of ``staging.fund_holdings_v2`` (INF52).

        Mirrors the JOIN in ``_bulk_enrich_run`` but writes to staging,
        not prod. The int-23 downgrade-refusal guard (base.py
        ``_check_no_downgrade_refusal``) inside the base
        ``_promote_append_is_latest`` reads the staged DataFrame; if
        every staged row for a (series, month) key is NULL on a
        sensitive column (entity_id / rollup_entity_id) and prod has
        non-NULL values for that key, it raises ``DowngradeRefusalError``
        and the promote rolls back. Populating the staging columns
        BEFORE super().promote() runs eliminates the false-positive
        refusal on amendments.

        Returns the number of mapped series_ids; 0 when nothing matched.
        ``_bulk_enrich_run`` still runs post-promote as a safety net.
        """
        if not series_touched:
            return 0
        sids = sorted(series_touched)
        placeholders = ",".join("?" * len(sids))

        try:
            mapping_df = prod_con.execute(
                f"""
                SELECT ei.identifier_value      AS series_id,
                       ei.entity_id             AS entity_id,
                       ec.rollup_entity_id      AS ec_rollup_entity_id,
                       dm.rollup_entity_id      AS dm_rollup_entity_id,
                       ea.alias_name            AS dm_rollup_name
                  FROM entity_identifiers ei
                  LEFT JOIN entity_rollup_history ec
                         ON ec.entity_id = ei.entity_id
                        AND ec.rollup_type = 'economic_control_v1'
                        AND ec.valid_to = DATE '9999-12-31'
                  LEFT JOIN entity_rollup_history dm
                         ON dm.entity_id = ei.entity_id
                        AND dm.rollup_type = 'decision_maker_v1'
                        AND dm.valid_to = DATE '9999-12-31'
                  LEFT JOIN entity_aliases ea
                         ON ea.entity_id = ec.rollup_entity_id
                        AND ea.is_preferred = TRUE
                        AND ea.valid_to = DATE '9999-12-31'
                 WHERE ei.identifier_type = 'series_id'
                   AND ei.valid_to = DATE '9999-12-31'
                   AND ei.identifier_value IN ({placeholders})
                """,  # nosec B608
                sids,
            ).fetchdf()
        except Exception as exc:  # pylint: disable=broad-except
            # Test fixtures and incomplete prod schemas can lack the
            # entity_* tables. Surface as a warning — the int-23 guard
            # still catches real downgrades and the post-promote
            # _bulk_enrich_run logs the same condition.
            self._logger.warning("_enrich_staging_entities: %s", exc)
            return 0

        if mapping_df.empty:
            return 0

        staging_con = duckdb.connect(self._staging_db_path)
        try:
            staging_con.register("entity_map", mapping_df)
            try:
                staging_con.execute(
                    """
                    UPDATE fund_holdings_v2 AS fh
                       SET entity_id           = m.entity_id,
                           rollup_entity_id    = m.ec_rollup_entity_id,
                           dm_entity_id        = m.entity_id,
                           dm_rollup_entity_id = m.dm_rollup_entity_id,
                           dm_rollup_name      = m.dm_rollup_name
                      FROM entity_map m
                     WHERE fh.series_id = m.series_id
                    """
                )
            finally:
                staging_con.unregister("entity_map")
            staging_con.execute("CHECKPOINT")
        finally:
            staging_con.close()

        return len(mapping_df)

    def _apply_fund_strategy_lock(
        self, prod_con: Any, series_touched: set[str],
    ) -> int:
        """PR-2 lock — preserve canonical ``fund_strategy`` on subsequent
        N-PORT loads.

        For each ``series_id`` in ``series_touched`` whose prod
        ``fund_universe`` row carries a non-NULL ``fund_strategy``, rewrite
        the staged ``fund_strategy`` (in ``stg_nport_fund_universe``) and
        the staged ``fund_holdings_v2.fund_strategy_at_filing`` to the prod
        value
        **before** ``super().promote()`` inserts the new holdings rows.
        New series (no row in prod) and series whose prod row carries NULL
        ``fund_strategy`` (the backfill case) keep the classifier output.

        Returns the number of locked series_ids; 0 when nothing matched.

        Without this step:
          * the next monthly top-up classifies from the per-filing fund
            name and silently overwrites hand-curated reclassifications
            (e.g. the QQQ / Target Date / leveraged-ETF sweep done in
            PR-2);
          * historical and new ``fund_holdings_v2`` rows for the same
            series can drift apart when the classifier output for a new
            filing differs from the canonical fund-level value.

        PR-3 cleanup: ``fund_category`` was dropped from prod
        ``fund_universe``; the lock now writes only ``fund_strategy``.
        """
        if not series_touched:
            return 0
        sids = sorted(series_touched)
        placeholders = ",".join("?" * len(sids))

        try:
            locked_df = prod_con.execute(
                f"""
                SELECT series_id, fund_strategy
                  FROM fund_universe
                 WHERE series_id IN ({placeholders})
                   AND fund_strategy IS NOT NULL
                """,  # nosec B608
                sids,
            ).fetchdf()
        except Exception as exc:  # pylint: disable=broad-except
            # fund_universe may be absent in test fixtures; surface as a
            # warning so tests without the table are not forced to seed it
            # when they exercise unrelated promote paths.
            self._logger.warning("_apply_fund_strategy_lock: %s", exc)
            return 0

        if locked_df.empty:
            return 0

        staging_con = duckdb.connect(self._staging_db_path)
        try:
            staging_con.register("lock_map", locked_df)
            try:
                staging_con.execute(
                    """
                    UPDATE fund_holdings_v2 AS fh
                       SET fund_strategy_at_filing = m.fund_strategy
                      FROM lock_map m
                     WHERE fh.series_id = m.series_id
                    """
                )
                # stg_nport_fund_universe may not exist if the run was
                # primed by the typed-staging path only; ignore absence.
                try:
                    staging_con.execute(
                        """
                        UPDATE stg_nport_fund_universe AS u
                           SET fund_strategy = m.fund_strategy
                          FROM lock_map m
                         WHERE u.series_id = m.series_id
                        """
                    )
                except duckdb.CatalogException:
                    pass
            finally:
                staging_con.unregister("lock_map")
            staging_con.execute("CHECKPOINT")
        finally:
            staging_con.close()

        return len(locked_df)

    def _upsert_fund_universe(
        self, prod_con: Any, series_touched: set[str],
    ) -> int:
        """Upsert ``fund_universe`` from staged ``stg_nport_fund_universe``.

        PR-2 lock layer (defense-in-depth on top of
        ``_apply_fund_strategy_lock``): if prod already has a row for the
        ``series_id`` with a non-NULL ``fund_strategy``, the prod value
        wins. The staged value is only honoured for new series (no prior
        row) or NULL-backfill cases. ``_apply_fund_strategy_lock`` runs
        pre-promote and rewrites staging in lock-step; this COALESCE is
        the safety net in case the helper was bypassed (e.g. promote()
        called without the wrapper).

        PR-3 cleanup: ``fund_category`` and ``is_actively_managed`` were
        dropped from prod ``fund_universe`` (both fully redundant with
        ``fund_strategy``). The upsert now reads/writes ``fund_strategy``
        only.
        """
        if not series_touched:
            return 0
        staging_con = duckdb.connect(self._staging_db_path, read_only=True)
        try:
            placeholders_s = ",".join("?" * len(series_touched))
            df = staging_con.execute(
                f"""
                SELECT fund_cik, fund_name, series_id, family_name,
                       total_net_assets,
                       total_holdings_count, equity_pct, top10_concentration,
                       last_updated, fund_strategy, best_index
                  FROM stg_nport_fund_universe
                 WHERE series_id IN ({placeholders_s})
                """,
                list(series_touched),
            ).fetchdf()
        finally:
            staging_con.close()
        if df.empty:
            return 0
        sids = df["series_id"].tolist()

        # Capture prod's current fund_strategy for each touched series_id
        # so we can preserve non-NULL canonical values across the
        # DELETE+INSERT below. Done in one round-trip.
        placeholders_p = ",".join("?" * len(sids))
        try:
            prior_df = prod_con.execute(
                f"""
                SELECT series_id,
                       fund_strategy AS prior_fund_strategy
                  FROM fund_universe
                 WHERE series_id IN ({placeholders_p})
                """,  # nosec B608
                sids,
            ).fetchdf()
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning(
                "_upsert_fund_universe prior-read failed: %s", exc,
            )
            prior_df = None

        prod_con.execute(
            f"DELETE FROM fund_universe WHERE series_id IN "
            f"({placeholders_p})",
            sids,
        )
        prod_con.register("u_df", df)
        if prior_df is None or prior_df.empty:
            import pandas as pd  # noqa: WPS433 — stdlib-equivalent for DuckDB
            prior_df = pd.DataFrame(
                columns=["series_id", "prior_fund_strategy"],
            )
        prod_con.register("p_df", prior_df)
        try:
            prod_con.execute(
                """
                INSERT INTO fund_universe (
                    fund_cik, fund_name, series_id, family_name,
                    total_net_assets,
                    total_holdings_count, equity_pct, top10_concentration,
                    last_updated, fund_strategy, best_index
                )
                SELECT u.fund_cik, u.fund_name, u.series_id, u.family_name,
                       u.total_net_assets,
                       u.total_holdings_count, u.equity_pct,
                       u.top10_concentration, u.last_updated,
                       COALESCE(p.prior_fund_strategy, u.fund_strategy)
                           AS fund_strategy,
                       u.best_index
                  FROM u_df u
                  LEFT JOIN p_df p
                         ON u.series_id = p.series_id
                """
            )
        finally:
            prod_con.unregister("u_df")
            prod_con.unregister("p_df")
        return len(df)

    def _bulk_enrich_run(
        self, prod_con: Any, series_touched: set[str],
    ) -> int:
        """Populate Group 2 entity columns on is_latest rows for the run.

        Ported from ``scripts/promote_nport.py`` — a single UPDATE...FROM
        JOIN scoped to ``series_id IN (...)``. Only the newly-inserted
        ``is_latest=TRUE`` rows are updated; historical ``FALSE`` rows
        are left untouched.
        """
        if not series_touched:
            return 0
        try:
            sids = sorted(series_touched)
            placeholders = ",".join("?" * len(sids))
            prod_con.execute(
                f"""
                UPDATE fund_holdings_v2 AS fh
                   SET entity_id           = e.entity_id,
                       rollup_entity_id    = e.ec_rollup_entity_id,
                       dm_entity_id        = e.entity_id,
                       dm_rollup_entity_id = e.dm_rollup_entity_id,
                       dm_rollup_name      = e.dm_rollup_name
                  FROM (
                      SELECT ei.identifier_value      AS series_id,
                             ei.entity_id             AS entity_id,
                             ec.rollup_entity_id      AS ec_rollup_entity_id,
                             dm.rollup_entity_id      AS dm_rollup_entity_id,
                             ea.alias_name            AS dm_rollup_name
                        FROM entity_identifiers ei
                        LEFT JOIN entity_rollup_history ec
                               ON ec.entity_id = ei.entity_id
                              AND ec.rollup_type = 'economic_control_v1'
                              AND ec.valid_to = DATE '9999-12-31'
                        LEFT JOIN entity_rollup_history dm
                               ON dm.entity_id = ei.entity_id
                              AND dm.rollup_type = 'decision_maker_v1'
                              AND dm.valid_to = DATE '9999-12-31'
                        LEFT JOIN entity_aliases ea
                               ON ea.entity_id = ec.rollup_entity_id
                              AND ea.is_preferred = TRUE
                              AND ea.valid_to = DATE '9999-12-31'
                       WHERE ei.identifier_type = 'series_id'
                         AND ei.valid_to = DATE '9999-12-31'
                         AND ei.identifier_value IN ({placeholders})
                  ) AS e
                 WHERE fh.series_id = e.series_id
                   AND fh.is_latest = TRUE
                   AND fh.series_id IN ({placeholders})
                """,  # nosec B608
                sids + sids,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("_bulk_enrich_run: %s", exc)
            return 0
        return len(series_touched)

    # ---- approve_and_promote override for snapshot refresh -------------

    def approve_and_promote(self, run_id: str) -> PromoteResult:
        result = super().approve_and_promote(run_id)
        try:
            refresh_snapshot()
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("refresh_snapshot: %s", exc)
        return result

    # ---- cleanup override (drop N-PORT raw + typed staging) ----------

    def _cleanup_staging(self, run_id: str) -> None:
        """INF50 hardening — drop the typed table AND both raw N-PORT
        staging tables in a single connection, with a post-cleanup
        assertion that fails LOUDLY (raise, not warn) if any table
        still exists after the DROPs.

        Replaces the prior super() + override pattern which (a) opened
        two separate writer connections and (b) caught all exceptions
        as warnings — silently leaving 11M+ rows in stg_nport_holdings
        when the second connection or any DROP failed. That
        contaminated the next run's parse() (unfiltered SELECT over
        stg_nport_holdings) and the contamination only surfaced at
        promote time as a row-count anomaly.

        After this rewrite a real failure surfaces as a RuntimeError
        in the approve_and_promote() path — visible immediately, with
        the offending table name in the message.
        """
        tables = (
            self.target_table,
            "stg_nport_holdings",
            "stg_nport_fund_universe",
        )
        staging_con = duckdb.connect(self._staging_db_path)
        try:
            for t in tables:
                staging_con.execute(f"DROP TABLE IF EXISTS {t}")  # nosec B608
            staging_con.execute("CHECKPOINT")

            # INF50 post-cleanup assertion. After DROP TABLE IF EXISTS
            # the table must not exist — a successful SELECT COUNT(*)
            # against it means the DROP was a no-op (or DuckDB never
            # processed it). A CatalogException is the success signal.
            for t in tables:
                try:
                    rows = staging_con.execute(
                        f"SELECT COUNT(*) FROM {t}"  # nosec B608
                    ).fetchone()[0]
                except duckdb.CatalogException:
                    continue
                raise RuntimeError(
                    f"_cleanup_staging({run_id}): {t} still exists with "
                    f"{rows} rows after DROP TABLE IF EXISTS — staging "
                    f"is contaminated and will leak into the next run."
                )
        finally:
            staging_con.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cli(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="N-PORT SourcePipeline (w2-03)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--quarter",
        help="DERA bulk load for quarter (e.g., 2026Q1)",
    )
    group.add_argument(
        "--monthly-topup", action="store_true",
        help="XML per-accession top-up for the current calendar quarter",
    )
    group.add_argument(
        "--month",
        help="XML top-up for a specific YYYY-MM",
    )
    parser.add_argument(
        "--zip",
        help="Local DERA ZIP file or directory — skips download if matched",
    )
    parser.add_argument(
        "--exclude-file",
        help="CSV/text file with one series_id per line to exclude from parse",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Mode 1: max quarters. Mode 2: max accessions.",
    )
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

    pipeline = LoadNPortPipeline(
        limit=args.limit,
        prod_db_path=prod_path,
    )

    scope: dict = {}
    if args.quarter:
        scope["quarter"] = args.quarter
    elif args.monthly_topup:
        scope["monthly_topup"] = True
    elif args.month:
        scope["month"] = args.month
    if args.zip:
        scope["zip_path"] = args.zip
    if args.exclude_file:
        scope["exclude_file"] = args.exclude_file

    run_id = pipeline.run(scope)
    print(f"run_id: {run_id}")

    if args.dry_run:
        print(
            f"Dry run complete. Call approve_and_promote({run_id!r}) "
            f"from the admin UI/REPL when ready."
        )
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
