"""CP-5.4 execute smoke — read-only post-migration parity probe.

Exercises each migrated reader site against prod DuckDB (read_only) and
prints the resulting row counts / top values for parity comparison
against the recon probe (cp_5_4_recon.py).

Sites:
  C1 — get_market_summary head query (distinct-holder count)
  C2 — /crowding holders panel
  CV1 — portfolio_context top_holders_df parent branch
  CV2 — portfolio_context portfolio_df parent branch
  FPM1 — /fund_portfolio_managers GROUP BY

Usage: python scripts/oneoff/cp_5_4_execute_smoke.py
"""
from __future__ import annotations

import logging
import os
import sys

# Make `from queries...` import work without going through scripts/api.py
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(THIS_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import duckdb  # noqa: E402

from queries.common import top_parent_canonical_name_sql  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("cp_5_4_execute_smoke")

DB_PATH = os.environ.get("DB_PATH", "data/13f.duckdb")
TICKER = "AAPL"
QUARTER = "2025Q4"


def main() -> int:
    if not os.path.exists(DB_PATH):
        log.error("DB not found at %s", DB_PATH)
        return 1
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        tpn_h = top_parent_canonical_name_sql('h')

        # C1
        c1 = con.execute(
            f"""
            WITH latest AS (
                SELECT MAX(quarter) AS q FROM holdings_v2 WHERE is_latest = TRUE
            )
            SELECT (SELECT q FROM latest) AS quarter,
                   COUNT(DISTINCT {tpn_h}) AS total_holders
              FROM holdings_v2 h, latest
             WHERE h.quarter = latest.q AND h.is_latest = TRUE
            """
        ).fetchone()
        log.info("[C1 market_summary] quarter=%s total_holders=%s", c1[0], c1[1])

        # C2
        c2 = con.execute(
            f"""
            SELECT {tpn_h} as holder, h.manager_type,
                   SUM(h.pct_of_so) as pct_so, SUM(h.market_value_live) as value
            FROM holdings_v2 h
            WHERE h.ticker = ? AND h.quarter = ? AND h.is_latest = TRUE
            GROUP BY holder, h.manager_type
            ORDER BY pct_so DESC NULLS LAST LIMIT 20
            """, [TICKER, QUARTER]
        ).fetchdf()
        log.info("[C2 crowding %s] holders=%d top=%s",
                 TICKER, len(c2), c2.iloc[0]['holder'] if len(c2) else None)

        # CV1
        cv1 = con.execute(
            f"""
            SELECT {tpn_h} as holder, SUM(h.market_value_live) as val,
                   MAX(h.manager_type) as mtype
            FROM holdings_v2 h
            WHERE h.ticker = ? AND h.quarter = ? AND h.is_latest = TRUE
            GROUP BY holder ORDER BY val DESC NULLS LAST LIMIT 25
            """, [TICKER, QUARTER]
        ).fetchdf()
        log.info("[CV1 conviction_top_holders %s] holders=%d top=%s",
                 TICKER, len(cv1), cv1.iloc[0]['holder'] if len(cv1) else None)

        # CV2 — verify SELECT/WHERE pair returns rows for those same holders
        if len(cv1):
            top_holders = cv1['holder'].tolist()
            ph = ",".join(["?"] * len(top_holders))
            cv2 = con.execute(
                f"""
                SELECT {tpn_h} as holder, h.ticker,
                       SUM(h.market_value_live) as value
                FROM holdings_v2 h
                WHERE h.quarter = ?
                  AND {tpn_h} IN ({ph})
                  AND h.market_value_live > 0
                  AND h.is_latest = TRUE
                GROUP BY holder, h.ticker
                """, [QUARTER] + top_holders
            ).fetchdf()
            distinct = cv2['holder'].nunique()
            log.info("[CV2 portfolio_df] rows=%d distinct_holders=%d (expect=%d)",
                     len(cv2), distinct, len(top_holders))
            if distinct != len(top_holders):
                missing = set(top_holders) - set(cv2['holder'].unique())
                log.warning("CV2 missing holders: %s", missing)

        # FPM1
        fpm1 = con.execute(
            f"""
            SELECT h.cik, h.fund_name,
                   MAX({tpn_h}) as inst_parent_name,
                   SUM(h.market_value_live) as position_value,
                   MAX(h.manager_type) as manager_type
            FROM holdings_v2 h
            WHERE h.ticker = ? AND h.quarter = ?
              AND h.entity_type NOT IN ('passive')
              AND h.is_latest = TRUE
            GROUP BY h.cik, h.fund_name
            ORDER BY position_value DESC NULLS LAST LIMIT 50
            """, [TICKER, QUARTER]
        ).fetchdf()
        log.info("[FPM1 fund_portfolio_managers %s] rows=%d top=%s",
                 TICKER, len(fpm1), fpm1.iloc[0]['inst_parent_name'] if len(fpm1) else None)

        log.info("smoke OK")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
