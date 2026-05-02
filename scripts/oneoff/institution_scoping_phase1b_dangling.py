#!/usr/bin/env python3
"""Phase 1B.2 — Dangling rollup ("Calamos shape").

Read-only. Counts fund_holdings_v2 (is_latest=TRUE) rows whose
dm_rollup_entity_id resolves to an entity with degenerate identity:
  - entity_type IN ('N/A','mixed','unknown',NULL)
  - canonical_name == 'N/A' (case-insensitive trim)

The PR #251 worked example: entity_id=11278 ('N/A') rollup_entity_id=63.
"""
import duckdb

DB = 'data/13f.duckdb'

def fmt_aum(v):
    if v is None:
        return '$0'
    return f"${v/1e9:,.2f}B"

def banner(s):
    print('\n' + '=' * 70)
    print(s)
    print('=' * 70)

def main():
    con = duckdb.connect(DB, read_only=True)

    banner('1B.2 DANGLING ROLLUP — dm_rollup target entity_type degenerate')

    # Baseline
    base = con.execute("""
        SELECT COUNT(*) AS n_rows, COALESCE(SUM(market_value_usd),0) AS aum
        FROM fund_holdings_v2 fh
        WHERE fh.is_latest=TRUE
    """).fetchone()
    print(f"BASELINE rows={base[0]:,}  aum={fmt_aum(base[1])}")

    # Dangling: dm_rollup_entity_id maps to N/A name OR degenerate type
    res = con.execute("""
        SELECT
          COUNT(*) AS n_rows,
          COALESCE(SUM(market_value_usd),0) AS aum
        FROM fund_holdings_v2 fh
        JOIN entities e ON e.entity_id = fh.dm_rollup_entity_id
        WHERE fh.is_latest=TRUE
          AND ( UPPER(TRIM(e.canonical_name)) = 'N/A'
                OR e.entity_type IS NULL
                OR LOWER(e.entity_type) IN ('n/a','mixed','unknown') )
    """).fetchone()
    print(f"DANGLING dm_rollup target: rows={res[0]:,}  aum={fmt_aum(res[1])}")

    # break out by reason
    print('\nBy entity_type bucket:')
    by_type = con.execute("""
        SELECT
          COALESCE(LOWER(e.entity_type),'<null>') AS bucket,
          COUNT(*) AS n_rows,
          COALESCE(SUM(market_value_usd),0) AS aum
        FROM fund_holdings_v2 fh
        JOIN entities e ON e.entity_id = fh.dm_rollup_entity_id
        WHERE fh.is_latest=TRUE
          AND ( UPPER(TRIM(e.canonical_name)) = 'N/A'
                OR e.entity_type IS NULL
                OR LOWER(e.entity_type) IN ('n/a','mixed','unknown') )
        GROUP BY 1 ORDER BY n_rows DESC
    """).fetchall()
    for b in by_type:
        print(f"  {b[0]:<12} rows={b[1]:,} aum={fmt_aum(b[2])}")

    # Quantify the entity_id=11278 ("N/A") case specifically
    banner('1B.2b — entity_id=11278 (literal "N/A") used as dm_rollup_entity_id')
    n11278 = con.execute("""
        SELECT COUNT(*) AS n_rows, COALESCE(SUM(market_value_usd),0) AS aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id = 11278
    """).fetchone()
    print(f"  rows={n11278[0]:,}  aum={fmt_aum(n11278[1])}")

    # Same for entity_id (not just dm_rollup): rows where entity_id=11278
    n11278_e = con.execute("""
        SELECT COUNT(*) AS n_rows, COALESCE(SUM(market_value_usd),0) AS aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND entity_id = 11278
    """).fetchone()
    print(f"  entity_id=11278: rows={n11278_e[0]:,}  aum={fmt_aum(n11278_e[1])}")

    banner('Sample 25 dangling rows')
    samples = con.execute("""
        SELECT
          fh.entity_id, fh.rollup_entity_id, fh.dm_rollup_entity_id,
          e.canonical_name AS rollup_canonical, e.entity_type AS rollup_type,
          fh.fund_name, fh.series_id, fh.fund_cik
        FROM fund_holdings_v2 fh
        JOIN entities e ON e.entity_id = fh.dm_rollup_entity_id
        WHERE fh.is_latest=TRUE
          AND ( UPPER(TRIM(e.canonical_name)) = 'N/A'
                OR e.entity_type IS NULL
                OR LOWER(e.entity_type) IN ('n/a','mixed','unknown') )
        LIMIT 25
    """).fetchall()
    for s in samples:
        print(f"  {s}")

if __name__ == '__main__':
    main()
