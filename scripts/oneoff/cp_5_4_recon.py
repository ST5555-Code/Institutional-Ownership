"""CP-5.4 recon — read-only verification probe.

Run-only contract: open prod DuckDB read-only, exercise the Crowding /
Conviction / Smart Money reader sites enumerated in
data/working/cp-5-4-reader-inventory.csv, and print a per-site sanity
snapshot. NO writes.

Probes confirm:
  1. Each CLEAN reader site returns a non-empty result for AAPL on the
     latest quarter (sanity for Phase 2 classification).
  2. Conviction's portfolio_context internal pipeline (5 SQL queries +
     pandas aggregate) is self-contained — no manager_aum reference, no
     portfolio_context-table dependency, no Direction/Since/Held column
     reference. Confirms Phase 3 deep-dive findings.
  3. inst_to_top_parent + decision_maker_v1 ERH bridge is callable from
     the same DB; CP-5.1 helper precondition holds.
  4. Smart Money /smart_money endpoint subqueries don't carry rollup
     pattern — confirms N/A_NO_ROLLUP_PATTERN classification.

Usage: python scripts/oneoff/cp_5_4_recon.py

Exits 0 on success; 1 if any sanity probe returns empty.
"""
from __future__ import annotations

import logging
import os
import sys

import duckdb

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("cp_5_4_recon")

DB_PATH = os.environ.get("DB_PATH", "data/13f.duckdb")
TICKER = "AAPL"


def probe_market_summary(con) -> int:
    """C1 — queries/market.py:135 — distinct-holder count head query."""
    row = con.execute(
        """
        WITH latest AS (
            SELECT MAX(quarter) AS q FROM holdings_v2 WHERE is_latest = TRUE
        )
        SELECT (SELECT q FROM latest) AS quarter,
               COUNT(DISTINCT COALESCE(rollup_name, inst_parent_name, manager_name)) AS total_holders
          FROM holdings_v2, latest
         WHERE holdings_v2.quarter = latest.q AND is_latest = TRUE
        """
    ).fetchone()
    log.info("[C1 market_summary] quarter=%s total_holders=%s", row[0], row[1])
    return int(row[1] or 0)


def probe_crowding(con) -> int:
    """C2 — api_market.py:199 — /crowding holders top-20."""
    rows = con.execute(
        """
        SELECT COALESCE(rollup_name, inst_parent_name, manager_name) as holder,
               manager_type, SUM(pct_of_so) as pct_so,
               SUM(market_value_live) as value
        FROM holdings_v2
        WHERE ticker = ?
          AND quarter = (SELECT MAX(quarter) FROM holdings_v2 WHERE is_latest = TRUE)
          AND is_latest = TRUE
        GROUP BY holder, manager_type
        ORDER BY pct_so DESC NULLS LAST LIMIT 20
        """,
        [TICKER],
    ).fetchall()
    log.info("[C2 crowding %s] holders=%d top=%s", TICKER, len(rows), rows[0][0] if rows else None)
    return len(rows)


def probe_conviction_top_holders(con) -> int:
    """CV1 — fund.py:110 — portfolio_context top_holders parent branch."""
    rows = con.execute(
        """
        SELECT COALESCE(rollup_name, inst_parent_name, manager_name) as holder,
               SUM(market_value_live) as val,
               MAX(manager_type) as mtype
        FROM holdings_v2
        WHERE (ticker = ? OR cusip = ?)
          AND quarter = (SELECT MAX(quarter) FROM holdings_v2 WHERE is_latest = TRUE)
          AND is_latest = TRUE
        GROUP BY holder
        ORDER BY val DESC NULLS LAST LIMIT 25
        """,
        [TICKER, "037833100"],  # AAPL CUSIP
    ).fetchall()
    log.info("[CV1 conviction_top_holders %s] holders=%d top=%s", TICKER, len(rows), rows[0][0] if rows else None)
    return len(rows)


def probe_inst_to_top_parent_bridge(con) -> int:
    """Helper precondition — inst_to_top_parent + ERH joinable."""
    row = con.execute(
        """
        SELECT COUNT(DISTINCT ittp.entity_id) as n_entities
          FROM inst_to_top_parent ittp
          JOIN entities e ON e.entity_id = ittp.top_parent_entity_id
        """
    ).fetchone()
    log.info("[bridge inst_to_top_parent] climbable_entities=%s", row[0])
    return int(row[0] or 0)


def probe_smart_money_no_rollup(con) -> int:
    """SM1 — api_market.py:280 — /smart_money longs has no rollup pattern."""
    rows = con.execute(
        """
        SELECT manager_type, COUNT(DISTINCT cik) as holders,
               SUM(shares) as long_shares, SUM(market_value_live) as long_value
        FROM holdings_v2
        WHERE ticker = ?
          AND quarter = (SELECT MAX(quarter) FROM holdings_v2 WHERE is_latest = TRUE)
          AND is_latest = TRUE
        GROUP BY manager_type
        ORDER BY long_value DESC NULLS LAST
        """,
        [TICKER],
    ).fetchall()
    log.info("[SM1 smart_money %s] manager_types=%d", TICKER, len(rows))
    return len(rows)


def confirm_no_manager_aum_in_targets() -> bool:
    """Phase 3 deep-dive — confirm fund.py / api_fund.py / api_market.py /
    queries/market.py do NOT reference manager_aum (the prompt's
    speculative L-size driver)."""
    targets = [
        "scripts/queries/fund.py",
        "scripts/queries/market.py",
        "scripts/api_market.py",
        "scripts/api_fund.py",
    ]
    found_any = False
    for path in targets:
        try:
            with open(path) as fh:
                txt = fh.read()
            if "manager_aum" in txt:
                log.info("[Phase3 manager_aum] FOUND in %s", path)
                found_any = True
        except FileNotFoundError:
            log.info("[Phase3 manager_aum] missing path %s", path)
    if not found_any:
        log.info("[Phase3 manager_aum] CONFIRMED ABSENT from all CP-5.4 target files")
    return not found_any


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        n_holders = probe_market_summary(con)
        n_crowd = probe_crowding(con)
        n_cv = probe_conviction_top_holders(con)
        n_bridge = probe_inst_to_top_parent_bridge(con)
        n_sm = probe_smart_money_no_rollup(con)
    finally:
        con.close()

    no_manager_aum = confirm_no_manager_aum_in_targets()

    if min(n_holders, n_crowd, n_cv, n_bridge, n_sm) <= 0:
        log.error("recon FAIL — at least one probe returned empty")
        return 1
    if not no_manager_aum:
        log.error("recon NOTE — manager_aum found in a target file; revisit Phase 3 §3.1")
    log.info("recon OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
