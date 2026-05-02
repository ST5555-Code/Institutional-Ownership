"""Phase 1A.1 — institution-level current state distributions.

Read-only. Queries holdings_v2 for entity_type / manager_type distributions
on is_latest=TRUE rows, divergence cross-tab, and sample CIKs.

Verified zero write SQL: grep -E 'INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE' returns nothing.
"""
import duckdb

DB = 'data/13f.duckdb'


def fmt_aum(x):
    if x is None:
        return '—'
    return f"${x/1e9:,.1f}B"


def main():
    con = duckdb.connect(DB, read_only=True)

    print("=" * 80)
    print("Phase 1A.1 — entity_type distribution (is_latest=TRUE)")
    print("=" * 80)
    rows = con.execute("""
        SELECT entity_type,
               COUNT(*) AS rows_ct,
               SUM(market_value_usd) AS aum,
               COUNT(DISTINCT cik) AS cik_ct
          FROM holdings_v2
         WHERE is_latest = TRUE
         GROUP BY entity_type
         ORDER BY rows_ct DESC
    """).fetchall()
    print(f"{'entity_type':<25} {'rows':>12} {'AUM':>14} {'CIKs':>10}")
    print("-" * 65)
    for r in rows:
        print(f"{str(r[0]):<25} {r[1]:>12,} {fmt_aum(r[2]):>14} {r[3]:>10,}")

    print("\n" + "=" * 80)
    print("Phase 1A.1 — manager_type distribution (is_latest=TRUE)")
    print("=" * 80)
    rows = con.execute("""
        SELECT manager_type,
               COUNT(*) AS rows_ct,
               SUM(market_value_usd) AS aum,
               COUNT(DISTINCT cik) AS cik_ct
          FROM holdings_v2
         WHERE is_latest = TRUE
         GROUP BY manager_type
         ORDER BY rows_ct DESC
    """).fetchall()
    print(f"{'manager_type':<25} {'rows':>12} {'AUM':>14} {'CIKs':>10}")
    print("-" * 65)
    for r in rows:
        print(f"{str(r[0]):<25} {r[1]:>12,} {fmt_aum(r[2]):>14} {r[3]:>10,}")

    print("\n" + "=" * 80)
    print("Phase 1A.1 — (entity_type, manager_type) cross-tab on CIK basis")
    print("=" * 80)
    # Per-CIK dominant pairing
    rows = con.execute("""
        WITH per_cik AS (
            SELECT cik,
                   ANY_VALUE(entity_type) AS entity_type,
                   ANY_VALUE(manager_type) AS manager_type
              FROM holdings_v2
             WHERE is_latest = TRUE
             GROUP BY cik
        )
        SELECT entity_type, manager_type, COUNT(*) AS cik_ct
          FROM per_cik
         GROUP BY entity_type, manager_type
         ORDER BY cik_ct DESC
    """).fetchall()
    print(f"{'entity_type':<22} {'manager_type':<22} {'CIKs':>10}")
    print("-" * 60)
    for r in rows:
        print(f"{str(r[0]):<22} {str(r[1]):<22} {r[2]:>10,}")

    print("\n" + "=" * 80)
    print("Phase 1A.1 — divergent (entity_type, manager_type) pairs (different stories)")
    print("=" * 80)
    # Definition: pairings where entity_type and manager_type are non-NULL and
    # differ semantically. Treat NULLs as equality with same NULL.
    rows = con.execute("""
        WITH per_cik AS (
            SELECT cik,
                   ANY_VALUE(entity_type) AS entity_type,
                   ANY_VALUE(manager_type) AS manager_type,
                   ANY_VALUE(manager_name) AS manager_name,
                   SUM(market_value_usd) AS aum
              FROM holdings_v2
             WHERE is_latest = TRUE
             GROUP BY cik
        )
        SELECT entity_type, manager_type, COUNT(*) AS cik_ct, SUM(aum) AS aum_total
          FROM per_cik
         WHERE COALESCE(entity_type,'∅') <> COALESCE(manager_type,'∅')
         GROUP BY entity_type, manager_type
         ORDER BY cik_ct DESC
    """).fetchall()
    print(f"{'entity_type':<22} {'manager_type':<22} {'CIKs':>8} {'AUM':>14}")
    print("-" * 70)
    for r in rows:
        print(f"{str(r[0]):<22} {str(r[1]):<22} {r[2]:>8,} {fmt_aum(r[3]):>14}")

    print("\n" + "=" * 80)
    print("Phase 1A.1 — top 5 sample CIKs per dominant entity_type")
    print("=" * 80)
    et_list = con.execute("""
        SELECT entity_type FROM (
          SELECT entity_type, COUNT(*) c FROM holdings_v2 WHERE is_latest=TRUE
          GROUP BY entity_type ORDER BY c DESC LIMIT 8
        )
    """).fetchall()
    for (et,) in et_list:
        print(f"\n--- entity_type = {et} ---")
        samples = con.execute("""
            SELECT cik, ANY_VALUE(manager_name), SUM(market_value_usd)
              FROM holdings_v2
             WHERE is_latest=TRUE
               AND entity_type IS NOT DISTINCT FROM ?
             GROUP BY cik
             ORDER BY SUM(market_value_usd) DESC NULLS LAST
             LIMIT 5
        """, [et]).fetchall()
        for s in samples:
            print(f"  cik={s[0]:<10} {str(s[1])[:50]:<50} {fmt_aum(s[2])}")

    con.close()


if __name__ == '__main__':
    main()
