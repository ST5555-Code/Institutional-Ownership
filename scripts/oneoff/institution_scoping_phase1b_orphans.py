#!/usr/bin/env python3
"""Phase 1B.1 — Orphan funds in fund_holdings_v2 (is_latest=TRUE).

Read-only. Counts and AUM for fund-side rollup integrity failure modes:
- entity_id IS NULL or not in entities
- rollup_entity_id IS NULL or not in entities
- dm_entity_id IS NULL or not in entities
- dm_rollup_entity_id IS NULL or not in entities

Prints structured output (sections + sample rows).
"""
import duckdb

DB = 'data/13f.duckdb'

def banner(s):
    print('\n' + '=' * 70)
    print(s)
    print('=' * 70)

def fmt_aum(v):
    if v is None:
        return '$0'
    return f"${v/1e9:,.2f}B"

def main():
    con = duckdb.connect(DB, read_only=True)

    banner('1B.1 ORPHAN FUNDS — fund_holdings_v2 is_latest=TRUE')

    # Universe baseline
    total = con.execute("""
        SELECT COUNT(*) AS n_rows, COALESCE(SUM(market_value_usd),0) AS aum
        FROM fund_holdings_v2 WHERE is_latest=TRUE
    """).fetchone()
    print(f"BASELINE: rows={total[0]:,}  aum={fmt_aum(total[1])}")

    cols = ['entity_id', 'rollup_entity_id', 'dm_entity_id', 'dm_rollup_entity_id']

    for col in cols:
        banner(f"  {col} — NULL counts")
        r = con.execute(f"""
            SELECT COUNT(*) AS n_rows, COALESCE(SUM(market_value_usd),0) AS aum
            FROM fund_holdings_v2
            WHERE is_latest=TRUE AND {col} IS NULL
        """).fetchone()
        print(f"  NULL: rows={r[0]:,}  aum={fmt_aum(r[1])}")

        # not in entities
        r2 = con.execute(f"""
            SELECT COUNT(*) AS n_rows, COALESCE(SUM(market_value_usd),0) AS aum
            FROM fund_holdings_v2 fh
            WHERE fh.is_latest=TRUE
              AND fh.{col} IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM entities e WHERE e.entity_id = fh.{col})
        """).fetchone()
        print(f"  NOT in entities: rows={r2[0]:,}  aum={fmt_aum(r2[1])}")

        # samples (any failure)
        samples = con.execute(f"""
            SELECT fh.fund_cik, fh.fund_name, fh.series_id, fh.entity_id, fh.rollup_entity_id, fh.dm_rollup_entity_id, fh.market_value_usd
            FROM fund_holdings_v2 fh
            WHERE fh.is_latest=TRUE AND ( fh.{col} IS NULL OR NOT EXISTS (SELECT 1 FROM entities e WHERE e.entity_id = fh.{col}) )
            LIMIT 10
        """).fetchall()
        for s in samples:
            print(f"    {s}")

    # fund_universe completeness check (lacks rollup ids; check fund_cik presence in fund_holdings_v2 vs missing series_id)
    banner('1B.1b FUND_UNIVERSE — basic integrity (no rollup column on this table)')
    fu = con.execute("""
        SELECT
          COUNT(*) AS rows,
          SUM(CASE WHEN series_id IS NULL THEN 1 ELSE 0 END) AS null_series,
          SUM(CASE WHEN total_net_assets IS NULL THEN 1 ELSE 0 END) AS null_aum
        FROM fund_universe
    """).fetchone()
    print(f"  rows={fu[0]:,}  null_series={fu[1]}  null_total_net_assets={fu[2]}")

    # Funds in fund_universe with no presence in fund_holdings_v2 latest
    fu_orphan = con.execute("""
        SELECT COUNT(*) AS n_rows, COALESCE(SUM(total_net_assets),0) AS aum
        FROM fund_universe fu
        WHERE NOT EXISTS (
            SELECT 1 FROM fund_holdings_v2 fh
            WHERE fh.is_latest=TRUE AND fh.series_id = fu.series_id AND fh.fund_cik = fu.fund_cik
        )
    """).fetchone()
    print(f"  fund_universe rows with NO is_latest fund_holdings_v2 match: rows={fu_orphan[0]:,} aum_tna={fmt_aum(fu_orphan[1])}")

if __name__ == '__main__':
    main()
