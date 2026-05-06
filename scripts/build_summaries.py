#!/usr/bin/env python3
"""build_summaries.py — Rebuild summary_by_ticker + summary_by_parent.

Rewrite (Batch 3-3, 2026-04-16): swapped source from legacy `holdings`
(dropped 2026-04-13 Stage 5) to `holdings_v2`. Adds N-PORT aggregation
from `fund_holdings_v2` for `summary_by_parent.total_nport_aum` and
`nport_coverage_pct`. Now writes both rollup worldviews (EC + DM) per
the migration-004 schema (`PRIMARY KEY (quarter, rollup_type,
rollup_entity_id)`).

summary_by_ticker:
  * Rollup-agnostic. One row per (quarter, ticker).
  * `total_value = SUM(COALESCE(market_value_live, market_value_usd))`
    so the table is correct both before and after `enrich_holdings.py`
    has run for the quarter.
  * `holder_count = COUNT(DISTINCT cik)` (filer-level, not entity).

summary_by_parent:
  * One row per (quarter, rollup_type, rollup_entity_id).
  * `total_aum = SUM(holdings_v2.market_value_usd)` — Group 1, 100%
    complete, filing-date semantics.
  * `total_nport_aum = SUM(fund_holdings_v2.market_value_usd)` grouped
    by the same rollup, scoped to the latest report_month per series_id
    within the quarter (avoids triple-counting monthly snapshots).
  * `nport_coverage_pct = MIN(100, total_nport_aum / total_aum * 100)`
    — formula reverse-engineered from live 8,417 rows (2026-04-16).

CLI:
  --staging    Write to staging DB (default: prod).
  --dry-run    Project per-(quarter × worldview) row counts, no writes.
  --rebuild    All quarters in config.QUARTERS (default: LATEST_QUARTER only).

Run:
  python3 scripts/build_summaries.py --dry-run --rebuild
  python3 scripts/build_summaries.py                    # latest quarter only
  python3 scripts/build_summaries.py --rebuild          # all quarters
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  pylint: disable=wrong-import-position

try:
    from config import QUARTERS, LATEST_QUARTER  # noqa: E402
except ImportError:
    QUARTERS = ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    LATEST_QUARTER = QUARTERS[-1]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")

_ROLLUP_SPECS = [
    # (rollup_type label, rid SQL expression, rname SQL expression).
    # Expressions assume the holdings_v2 alias ``h``. PR #295 dropped the
    # denormalized DM columns; DM resolves at read time via correlated
    # subqueries against ``entity_rollup_history`` (Method A, canonical
    # per PR #280).
    (
        "economic_control_v1",
        "h.rollup_entity_id",
        "h.rollup_name",
    ),
    (
        "decision_maker_v1",
        "(SELECT erh.rollup_entity_id FROM entity_rollup_history erh "
        "WHERE erh.entity_id = h.entity_id "
        "AND erh.rollup_type = 'decision_maker_v1' "
        "AND erh.valid_to = DATE '9999-12-31')",
        "(SELECT e.canonical_name FROM entity_rollup_history erh "
        "JOIN entities e ON e.entity_id = erh.rollup_entity_id "
        "WHERE erh.entity_id = h.entity_id "
        "AND erh.rollup_type = 'decision_maker_v1' "
        "AND erh.valid_to = DATE '9999-12-31')",
    ),
]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _Tee:
    """Mirror prints to stdout and a log file. Use as a context manager."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._fh = None

    def __enter__(self) -> "_Tee":
        self._fh = open(  # pylint: disable=consider-using-with
            self.path, "w", encoding="utf-8", buffering=1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._fh is not None:
            self._fh.close()

    def line(self, msg: str = "") -> None:
        """Write a line to stdout and the log file."""
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
        if self._fh is not None:
            self._fh.write(msg + "\n")


# ---------------------------------------------------------------------------
# DDL — ensure target tables exist (idempotent)
# ---------------------------------------------------------------------------

def _ensure_tables(con) -> None:
    """CREATE TABLE IF NOT EXISTS for both output tables.

    `summary_by_parent` DDL must match the post-migration-004 shape with
    `rollup_type` as part of the PK. CREATE IF NOT EXISTS does NOT alter
    existing tables — relying on migration 004 having already run.
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS summary_by_ticker (
            quarter VARCHAR,
            ticker VARCHAR,
            company_name VARCHAR,
            total_value DOUBLE,
            total_shares BIGINT,
            holder_count INTEGER,
            active_value DOUBLE,
            passive_value DOUBLE,
            active_pct DOUBLE,
            pct_of_so DOUBLE,
            updated_at TIMESTAMP,
            PRIMARY KEY (quarter, ticker)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS summary_by_parent (
            quarter VARCHAR,
            rollup_type VARCHAR,
            rollup_entity_id BIGINT,
            inst_parent_name VARCHAR,
            rollup_name VARCHAR,
            total_aum DOUBLE,
            total_nport_aum DOUBLE,
            nport_coverage_pct DOUBLE,
            ticker_count INTEGER,
            total_shares BIGINT,
            manager_type VARCHAR,
            is_passive BOOLEAN,
            updated_at TIMESTAMP,
            PRIMARY KEY (quarter, rollup_type, rollup_entity_id)
        )
    """)


# ---------------------------------------------------------------------------
# summary_by_ticker (rollup-agnostic, per-quarter)
# ---------------------------------------------------------------------------

def _project_summary_by_ticker(con, quarter: str) -> int:
    """Dry-run projection: count distinct tickers in scope for a quarter."""
    return con.execute("""
        SELECT COUNT(DISTINCT ticker)
        FROM holdings_v2
        WHERE quarter = ?
          AND ticker IS NOT NULL AND ticker != ''
          AND is_latest = TRUE
    """, [quarter]).fetchone()[0]


def _build_summary_by_ticker(con, quarter: str) -> int:
    """DELETE+INSERT one quarter of summary_by_ticker. Returns row count."""
    con.execute("DELETE FROM summary_by_ticker WHERE quarter = ?", [quarter])
    con.execute("""
        INSERT INTO summary_by_ticker
        SELECT
            ? AS quarter,
            h.ticker,
            MODE(h.issuer_name) AS company_name,
            SUM(COALESCE(h.market_value_live, h.market_value_usd)) AS total_value,
            SUM(h.shares) AS total_shares,
            COUNT(DISTINCT h.cik) AS holder_count,
            SUM(CASE WHEN h.manager_type IN ('active','hedge_fund','quantitative','activist')
                     THEN COALESCE(h.market_value_live, h.market_value_usd)
                     ELSE 0 END) AS active_value,
            SUM(CASE WHEN h.manager_type = 'passive'
                     THEN COALESCE(h.market_value_live, h.market_value_usd)
                     ELSE 0 END) AS passive_value,
            CASE WHEN SUM(COALESCE(h.market_value_live, h.market_value_usd)) > 0
                 THEN ROUND(
                     SUM(CASE WHEN h.manager_type IN ('active','hedge_fund','quantitative','activist')
                              THEN COALESCE(h.market_value_live, h.market_value_usd)
                              ELSE 0 END) * 100.0
                     / SUM(COALESCE(h.market_value_live, h.market_value_usd)),
                     1)
                 END AS active_pct,
            SUM(h.pct_of_so) AS pct_of_so,
            CURRENT_TIMESTAMP AS updated_at
        FROM holdings_v2 h
        WHERE h.quarter = ?
          AND h.ticker IS NOT NULL AND h.ticker != ''
          AND h.is_latest = TRUE
        GROUP BY h.ticker
    """, [quarter, quarter])
    return con.execute(
        "SELECT COUNT(*) FROM summary_by_ticker WHERE quarter = ?",
        [quarter],
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# summary_by_parent (per quarter × per worldview)
# ---------------------------------------------------------------------------

def _project_summary_by_parent(con, quarter: str, rid_col: str) -> int:
    """Dry-run projection: distinct rollup_entity_ids in 13F scope."""
    return con.execute(f"""
        SELECT COUNT(DISTINCT {rid_col})
        FROM holdings_v2 h
        WHERE h.quarter = ? AND h.is_latest = TRUE
    """, [quarter]).fetchone()[0]


def _build_summary_by_parent(  # pylint: disable=too-many-positional-arguments,too-many-arguments
    con,
    quarter: str,
    rollup_type: str,
    rid_col: str,
    rname_col: str,
) -> int:
    """DELETE+INSERT one (quarter × worldview) of summary_by_parent."""
    con.execute(
        "DELETE FROM summary_by_parent "
        "WHERE quarter = ? AND rollup_type = ?",
        [quarter, rollup_type],
    )
    if rollup_type == 'decision_maker_v1':
        nport_cte = """
        nport_per_rollup AS (
            SELECT erh.rollup_entity_id AS rid,
                   SUM(fh.market_value_usd) AS total_nport_aum
            FROM fund_holdings_v2 fh
            JOIN latest_per_series l
              ON l.series_id = fh.series_id
             AND l.latest_rm = fh.report_month
            JOIN entity_rollup_history erh
              ON erh.entity_id = fh.entity_id
             AND erh.rollup_type = 'decision_maker_v1'
             AND erh.valid_to = DATE '9999-12-31'
            WHERE fh.quarter = ? AND fh.is_latest = TRUE
            GROUP BY erh.rollup_entity_id
        ),"""
    else:
        nport_cte = f"""
        nport_per_rollup AS (
            SELECT fh.rollup_entity_id AS rid,
                   SUM(fh.market_value_usd) AS total_nport_aum
            FROM fund_holdings_v2 fh
            JOIN latest_per_series l
              ON l.series_id = fh.series_id
             AND l.latest_rm = fh.report_month
            WHERE fh.quarter = ? AND fh.is_latest = TRUE
            GROUP BY fh.rollup_entity_id
        ),"""
    con.execute(f"""
        INSERT INTO summary_by_parent (
            quarter, rollup_type, rollup_entity_id,
            inst_parent_name, rollup_name,
            total_aum, total_nport_aum, nport_coverage_pct,
            ticker_count, total_shares, manager_type, is_passive,
            updated_at
        )
        WITH latest_per_series AS (
            SELECT series_id, MAX(report_month) AS latest_rm
            FROM fund_holdings_v2
            WHERE quarter = ? AND is_latest = TRUE
            GROUP BY series_id
        ),
        {nport_cte}
        parent_13f AS (
            SELECT
                {rid_col}             AS rid,
                MAX({rname_col})      AS rname,
                SUM(h.market_value_usd) AS total_aum,
                COUNT(DISTINCT h.ticker) AS ticker_count,
                SUM(h.shares)           AS total_shares,
                MAX(h.manager_type)     AS manager_type,
                BOOL_OR(h.is_passive)   AS is_passive
            FROM holdings_v2 h
            WHERE h.quarter = ? AND h.is_latest = TRUE
            GROUP BY {rid_col}
        )
        SELECT
            ? AS quarter,
            ? AS rollup_type,
            p.rid AS rollup_entity_id,
            p.rname AS inst_parent_name,
            p.rname AS rollup_name,
            p.total_aum,
            COALESCE(np.total_nport_aum, 0) AS total_nport_aum,
            CASE WHEN p.total_aum > 0
                 THEN LEAST(
                     100.0,
                     COALESCE(np.total_nport_aum, 0) * 100.0 / p.total_aum)
                 END AS nport_coverage_pct,
            p.ticker_count,
            p.total_shares,
            p.manager_type,
            p.is_passive,
            CURRENT_TIMESTAMP AS updated_at
        FROM parent_13f p
        LEFT JOIN nport_per_rollup np ON np.rid = p.rid
    """, [quarter, quarter, quarter, quarter, rollup_type])
    return con.execute(
        "SELECT COUNT(*) FROM summary_by_parent "
        "WHERE quarter = ? AND rollup_type = ?",
        [quarter, rollup_type],
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------

def _run_dry(con, log: _Tee, quarters: list[str]) -> None:
    """Project per-quarter (× per-worldview for parent) row counts."""
    log.line("Dry-run projection")
    log.line("")
    log.line(f"{'quarter':10s} {'table':22s} {'worldview':22s} {'projected rows':>16s}")
    grand_t = 0
    grand_p = 0
    for q in quarters:
        n_t = _project_summary_by_ticker(con, q)
        grand_t += n_t
        log.line(f"{q:10s} {'summary_by_ticker':22s} {'(rollup-agnostic)':22s} "
                 f"{n_t:>16,}")
        for rollup_type, rid_col, _ in _ROLLUP_SPECS:
            n_p = _project_summary_by_parent(con, q, rid_col)
            grand_p += n_p
            log.line(f"{q:10s} {'summary_by_parent':22s} {rollup_type:22s} "
                     f"{n_p:>16,}")
    log.line("")
    log.line(f"  TOTAL projected summary_by_ticker rows : {grand_t:>16,}")
    log.line(f"  TOTAL projected summary_by_parent rows : {grand_p:>16,}")
    log.line("")
    log.line("  Today's prod state for reference:")
    log.line("    summary_by_ticker : 24,570 (4 quarters)")
    log.line("    summary_by_parent : 8,417  (2025Q4 EC only — pre-rewrite)")


def _run_write(con, log: _Tee, quarters: list[str]) -> None:
    """Full rebuild for the requested quarter(s)."""
    _ensure_tables(con)

    log.line("Building summary_by_ticker (rollup-agnostic)")
    for q in quarters:
        t0 = time.time()
        n = _build_summary_by_ticker(con, q)
        con.execute("CHECKPOINT")
        log.line(f"  {q}  {n:>10,} rows  "
                 f"({time.time()-t0:.1f}s, CHECKPOINT)")
    log.line("")

    log.line("Building summary_by_parent (per quarter × per worldview)")
    for q in quarters:
        for rollup_type, rid_col, rname_col in _ROLLUP_SPECS:
            t0 = time.time()
            n = _build_summary_by_parent(
                con, q, rollup_type, rid_col, rname_col)
            con.execute("CHECKPOINT")
            log.line(f"  {q}  {rollup_type:22s}  {n:>10,} rows  "
                     f"({time.time()-t0:.1f}s, CHECKPOINT)")
    log.line("")

    total_t = con.execute(
        "SELECT COUNT(*) FROM summary_by_ticker"
    ).fetchone()[0]
    total_p = con.execute(
        "SELECT COUNT(*) FROM summary_by_parent"
    ).fetchone()[0]
    db.record_freshness(con, "summary_by_ticker", total_t)
    db.record_freshness(con, "summary_by_parent", total_p)
    log.line(f"Post-state: summary_by_ticker {total_t:,} / "
             f"summary_by_parent {total_p:,}")
    log.line("data_freshness stamped on both tables.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """CLI parser."""
    parser = argparse.ArgumentParser(
        description="Rebuild summary_by_ticker + summary_by_parent "
                    "from holdings_v2 + fund_holdings_v2.",
    )
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB (default: prod)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Project per-(quarter × worldview) counts, no writes")
    parser.add_argument("--rebuild", action="store_true",
                        help="All quarters (default: LATEST_QUARTER only)")
    return parser.parse_args()


def _open_connection(args: argparse.Namespace):
    """Open a connection per --staging / --dry-run."""
    if args.staging:
        db.set_staging_mode(True)
    if args.dry_run:
        return duckdb.connect(db.get_db_path(), read_only=True)
    return db.connect_write()


def main() -> None:
    """Entry point — orchestrates dry-run or full rebuild."""
    args = _parse_args()
    quarters = QUARTERS if args.rebuild else [LATEST_QUARTER]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"build_summaries_{ts}.log")

    with _Tee(log_path) as log:
        mode = "DRY-RUN" if args.dry_run else "WRITE"
        target = "staging" if args.staging else "prod"
        if args.staging:
            db.set_staging_mode(True)
        log.line(f"build_summaries.py — {mode} against {target} DB "
                 f"({db.get_db_path()})")
        log.line(f"  quarters   : {quarters}")
        log.line(f"  worldviews : {[r[0] for r in _ROLLUP_SPECS]}")
        log.line(f"  log        : {log_path}")
        log.line("=" * 78)

        con = _open_connection(args)
        t_start = time.time()
        try:
            if args.dry_run:
                _run_dry(con, log, quarters)
                log.line("")
                log.line("=" * 78)
                log.line("DRY-RUN: no writes. Re-run without --dry-run to apply.")
            else:
                _run_write(con, log, quarters)
        finally:
            con.close()

        log.line("")
        log.line(f"Completed in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
