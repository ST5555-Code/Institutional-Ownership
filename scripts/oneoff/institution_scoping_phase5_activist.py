"""Phase 5 — activist-as-flag architecture decision support.

Read-only. Computes the current state of manager_type='activist' vs
is_activist=TRUE on holdings_v2 and managers, plus entity_classification_history.

Verified zero write SQL.
"""
import duckdb

DB = 'data/13f.duckdb'


def fmt_aum(x):
    if x is None:
        return '—'
    return f"${x/1e9:,.2f}B"


def main():
    con = duckdb.connect(DB, read_only=True)

    print("=" * 80)
    print("Phase 5.1 — manager_type='activist' on holdings_v2 (is_latest=TRUE)")
    print("=" * 80)
    row = con.execute("""
        SELECT COUNT(*), SUM(market_value_usd), COUNT(DISTINCT cik)
          FROM holdings_v2
         WHERE is_latest = TRUE AND manager_type = 'activist'
    """).fetchone()
    print(f"rows={row[0]:,}  aum={fmt_aum(row[1])}  CIKs={row[2]:,}")

    print("\nentity_type='activist' on holdings_v2 (is_latest=TRUE):")
    row = con.execute("""
        SELECT COUNT(*), SUM(market_value_usd), COUNT(DISTINCT cik)
          FROM holdings_v2
         WHERE is_latest = TRUE AND entity_type = 'activist'
    """).fetchone()
    print(f"rows={row[0]:,}  aum={fmt_aum(row[1])}  CIKs={row[2]:,}")

    print("\nis_activist=TRUE on holdings_v2 (is_latest=TRUE):")
    row = con.execute("""
        SELECT COUNT(*), SUM(market_value_usd), COUNT(DISTINCT cik)
          FROM holdings_v2
         WHERE is_latest = TRUE AND is_activist = TRUE
    """).fetchone()
    print(f"rows={row[0]:,}  aum={fmt_aum(row[1])}  CIKs={row[2]:,}")

    print("\n" + "=" * 80)
    print("Phase 5.1 — overlap cross-tab (per CIK, holdings_v2)")
    print("=" * 80)
    rows = con.execute("""
        WITH per_cik AS (
            SELECT cik,
                   BOOL_OR(manager_type = 'activist') AS mt_activist,
                   BOOL_OR(entity_type = 'activist')  AS et_activist,
                   BOOL_OR(is_activist = TRUE)        AS flag_activist,
                   ANY_VALUE(manager_name)            AS manager_name,
                   SUM(market_value_usd)              AS aum
              FROM holdings_v2
             WHERE is_latest = TRUE
             GROUP BY cik
        )
        SELECT mt_activist, et_activist, flag_activist,
               COUNT(*) AS cik_ct, SUM(aum) AS aum_total
          FROM per_cik
         WHERE mt_activist OR et_activist OR flag_activist
         GROUP BY 1, 2, 3
         ORDER BY cik_ct DESC
    """).fetchall()
    print(f"{'mt_activist':<14} {'et_activist':<14} {'is_activist':<14} {'CIKs':>6} {'AUM':>14}")
    print("-" * 70)
    for r in rows:
        print(f"{str(r[0]):<14} {str(r[1]):<14} {str(r[2]):<14} {r[3]:>6,} {fmt_aum(r[4]):>14}")

    # Sample names per cell
    print("\nSamples — CIKs where manager_type='activist' AND NOT is_activist:")
    rows = con.execute("""
        WITH per_cik AS (
            SELECT cik, ANY_VALUE(manager_name) mname,
                   BOOL_OR(manager_type='activist') mt,
                   BOOL_OR(is_activist=TRUE) flag,
                   SUM(market_value_usd) aum
              FROM holdings_v2 WHERE is_latest=TRUE GROUP BY cik
        )
        SELECT cik, mname, aum FROM per_cik
         WHERE mt AND NOT flag ORDER BY aum DESC NULLS LAST LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  cik={r[0]:<10} {str(r[1])[:50]:<50} {fmt_aum(r[2])}")

    print("\nSamples — CIKs where is_activist=TRUE AND manager_type<>'activist':")
    rows = con.execute("""
        WITH per_cik AS (
            SELECT cik, ANY_VALUE(manager_name) mname,
                   ANY_VALUE(manager_type) mt,
                   BOOL_OR(is_activist=TRUE) flag,
                   SUM(market_value_usd) aum
              FROM holdings_v2 WHERE is_latest=TRUE GROUP BY cik
        )
        SELECT cik, mname, mt, aum FROM per_cik
         WHERE flag AND COALESCE(mt,'') <> 'activist'
         ORDER BY aum DESC NULLS LAST LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  cik={r[0]:<10} {str(r[1])[:40]:<40} mt={str(r[2]):<14} {fmt_aum(r[3])}")

    print("\nSamples — CIKs where BOTH manager_type='activist' AND is_activist=TRUE:")
    rows = con.execute("""
        WITH per_cik AS (
            SELECT cik, ANY_VALUE(manager_name) mname,
                   BOOL_OR(manager_type='activist') mt,
                   BOOL_OR(is_activist=TRUE) flag,
                   SUM(market_value_usd) aum
              FROM holdings_v2 WHERE is_latest=TRUE GROUP BY cik
        )
        SELECT cik, mname, aum FROM per_cik
         WHERE mt AND flag ORDER BY aum DESC NULLS LAST LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  cik={r[0]:<10} {str(r[1])[:50]:<50} {fmt_aum(r[2])}")

    print("\n" + "=" * 80)
    print("Phase 5.1 — managers table activist signals")
    print("=" * 80)
    row = con.execute("""
        SELECT COUNT(*), SUM(aum_total), COUNT(DISTINCT cik)
          FROM managers WHERE is_activist = TRUE
    """).fetchone()
    print(f"managers.is_activist=TRUE: rows={row[0]:,}  aum={fmt_aum(row[1])}  CIKs={row[2]:,}")

    row = con.execute("""
        SELECT COUNT(*), SUM(aum_total), COUNT(DISTINCT cik)
          FROM managers WHERE strategy_type = 'activist'
    """).fetchone()
    print(f"managers.strategy_type='activist': rows={row[0]:,}  aum={fmt_aum(row[1])}  CIKs={row[2]:,}")

    print("\nmanagers cross-tab strategy_type x is_activist:")
    rows = con.execute("""
        SELECT strategy_type, is_activist, COUNT(*) ct, SUM(aum_total) aum
          FROM managers
         WHERE strategy_type='activist' OR is_activist=TRUE
         GROUP BY 1,2 ORDER BY ct DESC
    """).fetchall()
    for r in rows:
        print(f"  strategy_type={str(r[0]):<14} is_activist={str(r[1]):<6} CIKs={r[2]:>5,}  aum={fmt_aum(r[3])}")

    print("\n" + "=" * 80)
    print("Phase 5.1 — entity_classification_history activist signals")
    print("=" * 80)
    try:
        row = con.execute("""
            SELECT COUNT(*) FROM entity_classification_history
             WHERE classification = 'activist' AND valid_to = DATE '9999-12-31'
        """).fetchone()
        print(f"ECH classification='activist' (open rows): {row[0]:,}")

        row = con.execute("""
            SELECT COUNT(*) FROM entity_classification_history
             WHERE is_activist = TRUE AND valid_to = DATE '9999-12-31'
        """).fetchone()
        print(f"ECH is_activist=TRUE (open rows): {row[0]:,}")

        rows = con.execute("""
            SELECT classification, is_activist, COUNT(*) ct
              FROM entity_classification_history
             WHERE valid_to = DATE '9999-12-31'
               AND (classification='activist' OR is_activist=TRUE)
             GROUP BY 1,2 ORDER BY ct DESC
        """).fetchall()
        print("ECH cross-tab (open rows) classification x is_activist:")
        for r in rows:
            print(f"  classification={str(r[0]):<14} is_activist={str(r[1]):<6} ct={r[2]:>5,}")
    except Exception as e:
        print(f"ECH query error: {e}")

    print("\n" + "=" * 80)
    print("Phase 5.2 — underlying classification mapping for current activists")
    print("=" * 80)
    # For CIKs where holdings_v2.manager_type='activist', what does
    # managers.strategy_type say if we drop the activist label?
    rows = con.execute("""
        WITH activist_ciks AS (
            SELECT DISTINCT cik FROM holdings_v2
             WHERE is_latest=TRUE AND manager_type='activist'
        )
        SELECT m.strategy_type, COUNT(*) ct, SUM(m.aum_total) aum
          FROM activist_ciks a
          LEFT JOIN managers m ON m.cik = a.cik
         GROUP BY m.strategy_type ORDER BY ct DESC
    """).fetchall()
    print("managers.strategy_type for the manager_type='activist' CIK universe:")
    for r in rows:
        print(f"  strategy_type={str(r[0]):<16} CIKs={r[1]:>4}  aum={fmt_aum(r[2])}")

    # Also check entity_classification_history
    try:
        rows = con.execute("""
            WITH activist_ciks AS (
                SELECT DISTINCT cik, ANY_VALUE(entity_id) eid
                  FROM holdings_v2
                 WHERE is_latest=TRUE AND manager_type='activist'
                 GROUP BY cik
            )
            SELECT ech.classification, COUNT(*) ct
              FROM activist_ciks a
              LEFT JOIN entity_classification_history ech
                ON ech.entity_id = a.eid AND ech.valid_to = DATE '9999-12-31'
             GROUP BY ech.classification ORDER BY ct DESC
        """).fetchall()
        print("\nECH.classification for the manager_type='activist' CIK universe (via entity_id):")
        for r in rows:
            print(f"  classification={str(r[0]):<16} CIKs={r[1]}")
    except Exception as e:
        print(f"ECH lookup error: {e}")

    con.close()


if __name__ == '__main__':
    main()
