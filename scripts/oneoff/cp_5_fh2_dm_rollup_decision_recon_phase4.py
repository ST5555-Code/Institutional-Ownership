"""CP-5 fh2.dm_rollup decision recon — Phase 4 + 5 perf benchmarks.

Read-only investigation. Empirical perf numbers to inform the drop-column
vs backfill-contract decision:

  * Phase 4 — Method A read-side cost: time a Method-A query against
    fund_holdings_v2 with a top-25 firm aggregate. Compare to Method B
    using the denormalized column.
  * Phase 5 — backfill UPDATE cost: simulate the full-table refresh by
    running a SELECT ... FROM fund_holdings_v2 LEFT JOIN ERH on entity_id
    that matches the UPDATE shape. (We don't actually execute the
    UPDATE; read_only=True.)

No DB writes. The READ-ONLY connection prevents UPDATE; the timed query
is the SELECT shape that mirrors the UPDATE's join cost.

Refs:
  docs/findings/cp-5-bundle-c-discovery.md §7.1 (Method A canonical)
  docs/findings/cp-5-discovery.md (PR #276 read-side benchmark precedent)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
ROLLUP_TYPE_CANONICAL = "decision_maker_v1"

REPO = Path(__file__).resolve().parents[2]


def time_query(con, label: str, sql: str) -> float:
    """Run twice; return wall time of second run (warm cache)."""
    con.execute(sql).fetchall()  # warm-up
    t0 = time.perf_counter()
    rows = con.execute(sql).fetchall()
    elapsed = time.perf_counter() - t0
    n = len(rows)
    print(f"  {label:<55} {elapsed*1000:>8.1f} ms ({n:,} rows)")
    return elapsed


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    print("=" * 78)
    print("PHASE 4 — Method A read-side cost (top-25 firms aggregate)")
    print("=" * 78)

    # Method A: read-time ERH JOIN
    method_a = f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id, erh.rollup_entity_id
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT dr.rollup_entity_id, SUM(fh.market_value_usd)
        FROM fund_holdings_v2 fh
        LEFT JOIN dm_rollup dr ON dr.entity_id = fh.entity_id
        WHERE fh.is_latest = TRUE
          AND fh.market_value_usd IS NOT NULL
        GROUP BY dr.rollup_entity_id
        ORDER BY 2 DESC NULLS LAST
        LIMIT 25
    """
    # Method B: denormalized column
    method_b = """
        SELECT fh.dm_rollup_entity_id, SUM(fh.market_value_usd)
        FROM fund_holdings_v2 fh
        WHERE fh.is_latest = TRUE
          AND fh.market_value_usd IS NOT NULL
        GROUP BY fh.dm_rollup_entity_id
        ORDER BY 2 DESC NULLS LAST
        LIMIT 25
    """

    print("\n  Pure aggregate (no inst→top_parent climb):")
    t_a = time_query(con, "Method A (read-time ERH JOIN)", method_a)
    t_b = time_query(con, "Method B (denormalized column)", method_b)
    print(f"\n  Method A overhead vs Method B: "
          f"{(t_a - t_b)*1000:+.1f} ms ({(t_a/t_b - 1)*100:+.1f}%)")

    # Single-firm ticker-list query (more realistic reader pattern)
    method_a_single = f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id, erh.rollup_entity_id
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT fh.ticker, SUM(fh.market_value_usd)
        FROM fund_holdings_v2 fh
        LEFT JOIN dm_rollup dr ON dr.entity_id = fh.entity_id
        WHERE fh.is_latest = TRUE
          AND fh.quarter = '2025Q4'
          AND dr.rollup_entity_id = 4375
        GROUP BY fh.ticker
        ORDER BY 2 DESC NULLS LAST
        LIMIT 100
    """
    method_b_single = """
        SELECT fh.ticker, SUM(fh.market_value_usd)
        FROM fund_holdings_v2 fh
        WHERE fh.is_latest = TRUE
          AND fh.quarter = '2025Q4'
          AND fh.dm_rollup_entity_id = 4375
        GROUP BY fh.ticker
        ORDER BY 2 DESC NULLS LAST
        LIMIT 100
    """
    print("\n  Single-firm filter (Vanguard top-100 tickers in 2025Q4):")
    t_a2 = time_query(con, "Method A (read-time ERH JOIN, filtered)", method_a_single)
    t_b2 = time_query(con, "Method B (denormalized column, filtered)", method_b_single)
    print(f"\n  Method A overhead vs Method B: "
          f"{(t_a2 - t_b2)*1000:+.1f} ms ({(t_a2/t_b2 - 1)*100:+.1f}%)")

    # === Phase 5 — backfill UPDATE cost simulation ===
    print()
    print("=" * 78)
    print("PHASE 5 — backfill UPDATE cost simulation (read-only SELECT shape)")
    print("=" * 78)

    backfill_shape = f"""
        SELECT
          fh.row_id,
          dl.live_dm_eid,
          ea.alias_name AS dm_rollup_name
        FROM fund_holdings_v2 fh
        LEFT JOIN (
          SELECT erh.entity_id, erh.rollup_entity_id AS live_dm_eid
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        ) dl ON dl.entity_id = fh.entity_id
        LEFT JOIN entity_aliases ea
               ON ea.entity_id = dl.live_dm_eid
              AND ea.is_preferred = TRUE
              AND ea.valid_to = {SENTINEL}
        WHERE fh.is_latest = TRUE
    """
    print("  Full-table backfill JOIN (SELECT shape, LIMIT 1):")
    # Limit-1 for safety; we only want the plan/exec time of the JOIN
    # against all is_latest rows.
    t0 = time.perf_counter()
    n = con.execute(f"SELECT COUNT(*) FROM ({backfill_shape}) t").fetchone()[0]
    elapsed = time.perf_counter() - t0
    print(f"    full backfill JOIN cardinality: {n:,} rows in {elapsed*1000:.1f} ms")
    print(f"    (Wall time of equivalent UPDATE will be larger — write IO,")
    print(f"     SCD invalidation. This SELECT is a lower bound on UPDATE cost.)")

    # === Bonus: count diverged rows that backfill would correct ===
    print()
    print("  Diverged-only SELECT shape (rows backfill would actually change):")
    diverged_shape = f"""
        WITH dm_live AS (
          SELECT erh.entity_id, erh.rollup_entity_id AS live_dm_eid
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT COUNT(*)
        FROM fund_holdings_v2 fh
        JOIN dm_live dl ON dl.entity_id = fh.entity_id
        LEFT JOIN entity_aliases ea
               ON ea.entity_id = dl.live_dm_eid
              AND ea.is_preferred = TRUE
              AND ea.valid_to = {SENTINEL}
        WHERE fh.is_latest = TRUE
          AND (fh.dm_rollup_entity_id IS DISTINCT FROM dl.live_dm_eid
               OR fh.dm_rollup_name      IS DISTINCT FROM ea.alias_name)
    """
    t0 = time.perf_counter()
    n_div = con.execute(diverged_shape).fetchone()[0]
    elapsed = time.perf_counter() - t0
    print(f"    rows where backfill would change something: {n_div:,} "
          f"({elapsed*1000:.1f} ms)")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
