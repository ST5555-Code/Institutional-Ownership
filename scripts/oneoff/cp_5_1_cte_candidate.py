"""CP-5.1 view-vs-CTE benchmark candidate (DRAFT).

Read-only investigation. NO DB writes (read_only=True; CREATE TEMP VIEW
in a session is in-memory and cleared on disconnect — no persistence).

Compares three implementation strategies for the unified institutional-
ownership read layer specified in cp-5-comprehensive-remediation §2.1
and cp-5-discovery §5:

    (i)   direct query — baseline, current rollup_name/inst_parent_name
          COALESCE pattern with no R5 (= today's reader shape)
    (ii)  VIEW path    — CREATE TEMP VIEW cp5_unified_holdings_view AS
          (the candidate definition in cp_5_1_view_candidate.sql),
          then readers SELECT from the view per call
    (iii) CTE composition — readers compose a builder-helper that
          emits the same definition as a CTE inside each query

Five representative reader patterns, each run 3 times per condition,
warm-cache median reported. Climb tables (inst_to_top_parent,
fund_to_top_parent) are precomputed once via the Python iterative
algorithm from scripts/oneoff/cp_5_coverage_matrix_revalidation.py
and registered as temp tables — the recursive CTE in the candidate
view is NOT exercised here because (a) it would dominate runtime
unfairly and (b) CP-5.1b will materialize the climb tables either
way (precomputed register or recursive CTE evaluated per call).

Output: data/working/cp-5-1-view-vs-cte-benchmark.csv.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
QUARTER = "2025Q4"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")
REPEATS = 3


def build_inst_to_top_parent(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    types_sql = ", ".join(f"'{t}'" for t in ROLLUP_CTRL_TYPES)
    edges = con.execute(f"""
        SELECT er.child_entity_id, er.parent_entity_id
        FROM entity_relationships er
        JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
        JOIN entity_current cec ON cec.entity_id = er.child_entity_id
        WHERE er.valid_to = {SENTINEL}
          AND er.control_type IN ({types_sql})
          AND pec.entity_type = 'institution'
          AND cec.entity_type = 'institution'
    """).fetchdf()
    edges = edges.sort_values(["child_entity_id", "parent_entity_id"]).drop_duplicates(
        "child_entity_id", keep="first"
    )
    edge_map = dict(zip(edges["child_entity_id"], edges["parent_entity_id"]))
    seed = con.execute(
        "SELECT entity_id FROM entity_current WHERE entity_type='institution'"
    ).fetchdf()
    cur = {ent: ent for ent in seed["entity_id"]}
    visited = {ent: {ent} for ent in cur}
    for _ in range(20):
        changed = 0
        for ent, tp in list(cur.items()):
            nxt = edge_map.get(tp)
            if nxt is None or nxt == tp or nxt in visited[ent]:
                continue
            visited[ent].add(nxt)
            cur[ent] = nxt
            changed += 1
        if changed == 0:
            break
    return pd.DataFrame({
        "entity_id": list(cur.keys()),
        "top_parent_entity_id": list(cur.values()),
    })


def build_fund_to_top_parent(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    fund_to_inst = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id,
               erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec ON ec.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND erh.rollup_type = 'decision_maker_v1'
          AND ec.entity_type = 'fund'
    """).fetchdf()
    return fund_to_inst


# ---------- the unified definition, parameterized as a SQL fragment ----------
UNIFIED_CTE_BODY = """
WITH thirteen_f AS (
    SELECT itp.top_parent_entity_id,
           h.cusip, h.ticker,
           SUM(h.market_value_usd) AS thirteen_f_aum
    FROM holdings_v2 h
    JOIN inst_to_top_parent itp ON itp.entity_id = h.entity_id
    WHERE h.is_latest = TRUE AND h.quarter = '{q}'
    GROUP BY itp.top_parent_entity_id, h.cusip, h.ticker
),
fund_climb AS (
    SELECT f2i.fund_entity_id, itp.top_parent_entity_id
    FROM fund_to_inst f2i
    JOIN inst_to_top_parent itp ON itp.entity_id = f2i.institution_entity_id
),
fund_tier AS (
    SELECT fc.top_parent_entity_id,
           fh.cusip, fh.ticker,
           SUM(fh.market_value_usd) AS fund_tier_aum
    FROM fund_holdings_v2 fh
    JOIN fund_climb fc ON fc.fund_entity_id = fh.entity_id
    WHERE fh.is_latest = TRUE AND fh.quarter = '{q}'
      AND fh.asset_category = 'EC'
      AND fh.cusip IS NOT NULL
      AND fh.cusip NOT IN ('000000000', '999999999')
    GROUP BY fc.top_parent_entity_id, fh.cusip, fh.ticker
),
unified AS (
    SELECT
      COALESCE(tf.top_parent_entity_id, ft.top_parent_entity_id) AS top_parent_entity_id,
      COALESCE(tf.cusip,  ft.cusip)  AS cusip,
      COALESCE(tf.ticker, ft.ticker) AS ticker,
      COALESCE(tf.thirteen_f_aum, 0) AS thirteen_f_aum,
      COALESCE(ft.fund_tier_aum,  0) AS fund_tier_aum,
      GREATEST(COALESCE(tf.thirteen_f_aum, 0),
               COALESCE(ft.fund_tier_aum, 0)) AS r5_aum,
      CASE
        WHEN tf.thirteen_f_aum IS NULL THEN 'fund_only'
        WHEN ft.fund_tier_aum  IS NULL THEN '13F_only'
        WHEN tf.thirteen_f_aum >= ft.fund_tier_aum THEN '13F_wins'
        ELSE 'fund_wins'
      END AS source_winner
    FROM thirteen_f tf
    FULL OUTER JOIN fund_tier ft
      ON tf.top_parent_entity_id = ft.top_parent_entity_id
     AND tf.cusip                = ft.cusip
)
"""


def view_setup_sql() -> str:
    """The same body as a CREATE TEMP VIEW (Condition ii)."""
    body = UNIFIED_CTE_BODY.format(q=QUARTER)
    return body.replace("WITH", "CREATE TEMP VIEW cp5_unified_holdings_view AS WITH",
                        1).rstrip() + " SELECT u.*, ec.display_name AS top_parent_name " \
                                       "FROM unified u LEFT JOIN entity_current ec " \
                                       "ON ec.entity_id = u.top_parent_entity_id"


# ---------- 5 representative queries, in three conditions each ----------
QUERIES = {
    "q1_top25_aapl": {
        "direct": f"""
            SELECT COALESCE(rollup_name, inst_parent_name, manager_name) AS holder,
                   SUM(market_value_usd) AS aum
            FROM holdings_v2
            WHERE ticker = 'AAPL' AND quarter = '{QUARTER}' AND is_latest = TRUE
            GROUP BY holder
            ORDER BY aum DESC NULLS LAST LIMIT 25
        """,
        "view": """
            SELECT top_parent_entity_id, top_parent_name, r5_aum
            FROM cp5_unified_holdings_view WHERE ticker = 'AAPL'
            ORDER BY r5_aum DESC LIMIT 25
        """,
        "cte": UNIFIED_CTE_BODY.format(q=QUARTER) + """
            SELECT u.top_parent_entity_id, ec.display_name AS top_parent_name, u.r5_aum
            FROM unified u LEFT JOIN entity_current ec ON ec.entity_id = u.top_parent_entity_id
            WHERE u.ticker = 'AAPL'
            ORDER BY u.r5_aum DESC LIMIT 25
        """,
    },
    "q2_top50_combined": {
        "direct": f"""
            SELECT COALESCE(rollup_name, inst_parent_name, manager_name) AS holder,
                   SUM(market_value_usd) AS aum
            FROM holdings_v2
            WHERE quarter = '{QUARTER}' AND is_latest = TRUE
            GROUP BY holder
            ORDER BY aum DESC NULLS LAST LIMIT 50
        """,
        "view": """
            SELECT top_parent_entity_id, top_parent_name, SUM(r5_aum) AS aum
            FROM cp5_unified_holdings_view
            GROUP BY top_parent_entity_id, top_parent_name
            ORDER BY aum DESC LIMIT 50
        """,
        "cte": UNIFIED_CTE_BODY.format(q=QUARTER) + """
            SELECT u.top_parent_entity_id, ec.display_name AS top_parent_name,
                   SUM(u.r5_aum) AS aum
            FROM unified u LEFT JOIN entity_current ec ON ec.entity_id = u.top_parent_entity_id
            GROUP BY u.top_parent_entity_id, ec.display_name
            ORDER BY aum DESC LIMIT 50
        """,
    },
    "q3_vanguard_positions": {
        # Vanguard top_parent_entity_id = 4375 per cp_5_coverage_matrix_revalidation.
        "direct": f"""
            SELECT ticker, SUM(market_value_usd) AS aum
            FROM holdings_v2
            WHERE rollup_entity_id = 4375 AND quarter = '{QUARTER}' AND is_latest = TRUE
            GROUP BY ticker
            ORDER BY aum DESC NULLS LAST LIMIT 100
        """,
        "view": """
            SELECT ticker, r5_aum
            FROM cp5_unified_holdings_view
            WHERE top_parent_entity_id = 4375
            ORDER BY r5_aum DESC LIMIT 100
        """,
        "cte": UNIFIED_CTE_BODY.format(q=QUARTER) + """
            SELECT u.ticker, u.r5_aum
            FROM unified u
            WHERE u.top_parent_entity_id = 4375
            ORDER BY u.r5_aum DESC LIMIT 100
        """,
    },
    "q4_crowding_count": {
        "direct": f"""
            SELECT manager_type,
                   COUNT(DISTINCT COALESCE(rollup_name, inst_parent_name, manager_name)) AS holders,
                   SUM(market_value_usd) AS aum
            FROM holdings_v2
            WHERE quarter = '{QUARTER}' AND is_latest = TRUE
            GROUP BY manager_type
            ORDER BY aum DESC
        """,
        "view": """
            SELECT COUNT(DISTINCT top_parent_entity_id) AS holders,
                   SUM(r5_aum) AS aum
            FROM cp5_unified_holdings_view
        """,
        "cte": UNIFIED_CTE_BODY.format(q=QUARTER) + """
            SELECT COUNT(DISTINCT u.top_parent_entity_id) AS holders,
                   SUM(u.r5_aum) AS aum
            FROM unified u
        """,
    },
    "q5_cross_pivot_3tickers": {
        "direct": f"""
            SELECT COALESCE(rollup_name, inst_parent_name, manager_name) AS investor,
                   SUM(CASE WHEN ticker = 'AAPL' THEN market_value_usd END) AS aapl,
                   SUM(CASE WHEN ticker = 'MSFT' THEN market_value_usd END) AS msft,
                   SUM(CASE WHEN ticker = 'NVDA' THEN market_value_usd END) AS nvda
            FROM holdings_v2
            WHERE ticker IN ('AAPL','MSFT','NVDA') AND quarter = '{QUARTER}' AND is_latest = TRUE
            GROUP BY investor
            ORDER BY (COALESCE(SUM(CASE WHEN ticker='AAPL' THEN market_value_usd END),0)
                     + COALESCE(SUM(CASE WHEN ticker='MSFT' THEN market_value_usd END),0)
                     + COALESCE(SUM(CASE WHEN ticker='NVDA' THEN market_value_usd END),0)) DESC
            LIMIT 25
        """,
        "view": """
            SELECT top_parent_entity_id, top_parent_name,
                   SUM(CASE WHEN ticker = 'AAPL' THEN r5_aum END) AS aapl,
                   SUM(CASE WHEN ticker = 'MSFT' THEN r5_aum END) AS msft,
                   SUM(CASE WHEN ticker = 'NVDA' THEN r5_aum END) AS nvda
            FROM cp5_unified_holdings_view
            WHERE ticker IN ('AAPL','MSFT','NVDA')
            GROUP BY top_parent_entity_id, top_parent_name
            ORDER BY COALESCE(SUM(CASE WHEN ticker='AAPL' THEN r5_aum END),0)
                   + COALESCE(SUM(CASE WHEN ticker='MSFT' THEN r5_aum END),0)
                   + COALESCE(SUM(CASE WHEN ticker='NVDA' THEN r5_aum END),0) DESC
            LIMIT 25
        """,
        "cte": UNIFIED_CTE_BODY.format(q=QUARTER) + """
            SELECT u.top_parent_entity_id, ec.display_name AS top_parent_name,
                   SUM(CASE WHEN u.ticker = 'AAPL' THEN u.r5_aum END) AS aapl,
                   SUM(CASE WHEN u.ticker = 'MSFT' THEN u.r5_aum END) AS msft,
                   SUM(CASE WHEN u.ticker = 'NVDA' THEN u.r5_aum END) AS nvda
            FROM unified u LEFT JOIN entity_current ec ON ec.entity_id = u.top_parent_entity_id
            WHERE u.ticker IN ('AAPL','MSFT','NVDA')
            GROUP BY u.top_parent_entity_id, ec.display_name
            ORDER BY COALESCE(SUM(CASE WHEN u.ticker='AAPL' THEN u.r5_aum END),0)
                   + COALESCE(SUM(CASE WHEN u.ticker='MSFT' THEN u.r5_aum END),0)
                   + COALESCE(SUM(CASE WHEN u.ticker='NVDA' THEN u.r5_aum END),0) DESC
            LIMIT 25
        """,
    },
}


def time_query(con: duckdb.DuckDBPyConnection, sql: str, repeats: int = REPEATS):
    """Run sql `repeats` times warm; first run is warm-up, return median of remaining."""
    con.execute(sql).fetchall()  # warm-up
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times), min(times), max(times)


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    print("Building climb tables (Python iterative)...")
    inst_to_top_parent = build_inst_to_top_parent(con)
    fund_to_inst       = build_fund_to_top_parent(con)
    con.register("inst_to_top_parent", inst_to_top_parent)
    con.register("fund_to_inst",       fund_to_inst)
    print(f"  inst_to_top_parent rows: {len(inst_to_top_parent):,}")
    print(f"  fund_to_inst rows:       {len(fund_to_inst):,}")

    # Build the temp view ONCE (Condition ii setup)
    view_sql = view_setup_sql()
    con.execute(view_sql)
    nrows = con.execute("SELECT COUNT(*) FROM cp5_unified_holdings_view").fetchone()[0]
    print(f"  cp5_unified_holdings_view rows: {nrows:,}")

    print()
    print("Benchmarking (warm median across REPEATS={REPEATS} runs/query/condition)...")

    rows = []
    for qname, conds in QUERIES.items():
        for cond, sql in conds.items():
            try:
                med, lo, hi = time_query(con, sql)
                print(f"  {qname:<28} {cond:<8} median={med:7.1f} ms  min={lo:7.1f}  max={hi:7.1f}")
                rows.append({"query": qname, "condition": cond,
                             "median_ms": round(med, 1),
                             "min_ms": round(lo, 1), "max_ms": round(hi, 1)})
            except Exception as e:
                print(f"  {qname:<28} {cond:<8} FAILED: {e}")
                rows.append({"query": qname, "condition": cond,
                             "median_ms": None, "min_ms": None, "max_ms": None,
                             "error": str(e)[:200]})

    out = Path("data/working/cp-5-1-view-vs-cte-benchmark.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nWrote {out}")

    # Summary aggregation
    df = pd.DataFrame([r for r in rows if r["median_ms"] is not None])
    if not df.empty:
        agg = df.groupby("condition")["median_ms"].agg(["mean", "max", "min"]).round(1)
        print("\nPer-condition summary (median ms across 5 queries):")
        print(agg.to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
