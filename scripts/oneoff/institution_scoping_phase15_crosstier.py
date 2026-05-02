#!/usr/bin/env python3
"""Phase 1.5 — Cross-tier consistency.

Read-only.
1.5.1 — Institutions receiving fund rollups but invisible in holdings_v2 (institution-level).
1.5.2 — AUM plausibility (fund_aum vs institution_aum) per receiving institution.
1.5.3 — Receiving institutions that are deprecated (entity_classification_history.valid_to != '9999-12-31'
        or appear in entity_relationships with valid_to closed).
"""
import duckdb

DB = 'data/13f.duckdb'

def fmt_aum(v):
    if v is None: return '$0'
    return f"${v/1e9:,.2f}B"

def banner(s):
    print('\n' + '=' * 70)
    print(s)
    print('=' * 70)

def main():
    con = duckdb.connect(DB, read_only=True)

    # Build aggregate per receiving institution from fund_holdings_v2
    # Use dm_rollup_entity_id as the "institution" the fund rolls up to.
    banner('1.5  AGGREGATE: distinct fund-rollup-target institutions')
    fund_aum = con.execute("""
        SELECT
          fh.dm_rollup_entity_id AS eid,
          MAX(fh.dm_rollup_name) AS name,
          COUNT(*) AS fund_rows,
          SUM(market_value_usd) AS fund_aum
        FROM fund_holdings_v2 fh
        WHERE fh.is_latest=TRUE AND fh.dm_rollup_entity_id IS NOT NULL
        GROUP BY 1
    """).fetchall()
    print(f"distinct dm_rollup_entity_id targets (with non-null id): {len(fund_aum):,}")

    # Pre-compute institution-level holdings_v2 per entity (try entity_id and rollup_entity_id)
    inst_eid = dict(con.execute("""
        SELECT entity_id, SUM(market_value_usd)
        FROM holdings_v2
        WHERE is_latest=TRUE AND entity_id IS NOT NULL
        GROUP BY 1
    """).fetchall())
    inst_reid = dict(con.execute("""
        SELECT rollup_entity_id, SUM(market_value_usd)
        FROM holdings_v2
        WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
        GROUP BY 1
    """).fetchall())
    inst_dmreid = dict(con.execute("""
        SELECT dm_rollup_entity_id, SUM(market_value_usd)
        FROM holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        GROUP BY 1
    """).fetchall())
    print(f"holdings_v2 distinct entity_id (latest): {len(inst_eid):,}")
    print(f"holdings_v2 distinct rollup_entity_id (latest): {len(inst_reid):,}")
    print(f"holdings_v2 distinct dm_rollup_entity_id (latest): {len(inst_dmreid):,}")

    # 1.5.1 invisible institutions: receive fund rollups, NO match in any of the 3 holdings_v2 keys
    banner('1.5.1 INVISIBLE INSTITUTIONS — receive fund rollups, missing from holdings_v2')
    invisible = []
    for eid, name, rows, aum in fund_aum:
        if eid in inst_eid or eid in inst_reid or eid in inst_dmreid:
            continue
        invisible.append((eid, name, rows, aum or 0))
    invisible.sort(key=lambda x: -x[3])
    invis_aum = sum(x[3] for x in invisible)
    print(f"INVISIBLE: count={len(invisible):,}  fund_aum={fmt_aum(invis_aum)}")
    print('\nTop 25 (by fund AUM):')
    for inv in invisible[:25]:
        eid, name, rows, aum = inv
        print(f"  eid={eid} name={name!r}  rows={rows:,}  fund_aum={fmt_aum(aum)}")

    # 1.5.2 AUM plausibility — pick whichever institution-side bucket gives non-zero
    banner('1.5.2 AUM PLAUSIBILITY — fund_aum vs institution_aum')
    # Decide which join: count which has more matches
    match_eid = sum(1 for x in fund_aum if x[0] in inst_eid)
    match_reid = sum(1 for x in fund_aum if x[0] in inst_reid)
    match_dmreid = sum(1 for x in fund_aum if x[0] in inst_dmreid)
    print(f"  match counts — entity_id={match_eid}  rollup_entity_id={match_reid}  dm_rollup_entity_id={match_dmreid}")
    use = 'dm_rollup_entity_id' if match_dmreid >= max(match_eid, match_reid) else (
          'rollup_entity_id' if match_reid >= match_eid else 'entity_id')
    inst_map = {'entity_id': inst_eid, 'rollup_entity_id': inst_reid, 'dm_rollup_entity_id': inst_dmreid}[use]
    print(f"  Using holdings_v2.{use} as join key (most matches).")

    mismatches = []
    no_match = 0
    for eid, name, rows, faum in fund_aum:
        iaum = inst_map.get(eid)
        if iaum is None:
            no_match += 1
            continue
        delta = (faum or 0) - iaum
        ratio = (faum or 0) / iaum if iaum > 0 else None
        if ratio is None or ratio > 1.5:
            mismatches.append((eid, name, faum or 0, iaum, delta, ratio))
    mismatches.sort(key=lambda x: -abs(x[4]))
    print(f"  Receiving institutions with NO match in holdings_v2.{use}: {no_match:,}")
    print(f"  IMPLAUSIBLE (fund_aum > 1.5x institution_aum, including div-by-zero): {len(mismatches):,}")
    print('\nTop 25 mismatches by |delta|:')
    for m in mismatches[:25]:
        eid, name, faum, iaum, delta, ratio = m
        rs = f"{ratio:.2f}x" if ratio is not None else 'inf'
        print(f"  eid={eid} {name!r:<55} fund={fmt_aum(faum)} inst={fmt_aum(iaum)} delta={fmt_aum(delta)} ratio={rs}")

    # Also flag fund_aum > institution_aum at all (not just 1.5x), but separately count
    soft_count = 0
    for eid, name, rows, faum in fund_aum:
        iaum = inst_map.get(eid)
        if iaum is None: continue
        if (faum or 0) > iaum:
            soft_count += 1
    print(f"\n  Soft flag: fund_aum > institution_aum (any amount): {soft_count:,} institutions")

    # 1.5.3 deprecated entities
    banner('1.5.3 DEPRECATED — receiving institutions whose latest classification is closed (valid_to != 9999-12-31)')
    # latest classification per entity
    deprecated = con.execute("""
        WITH latest AS (
          SELECT entity_id, valid_to,
                 ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY valid_from DESC, valid_to DESC) AS rn
          FROM entity_classification_history
        )
        SELECT entity_id, valid_to FROM latest WHERE rn=1
    """).fetchall()
    dep_map = {row[0]: row[1] for row in deprecated}
    OPEN_SENTINEL = '9999-12-31'

    deprecated_targets = []
    for eid, name, rows, faum in fund_aum:
        vt = dep_map.get(eid)
        if vt is None:
            continue
        if str(vt) != OPEN_SENTINEL:
            deprecated_targets.append((eid, name, str(vt), rows, faum or 0))
    deprecated_targets.sort(key=lambda x: -x[4])
    dep_aum = sum(x[4] for x in deprecated_targets)
    print(f"DEPRECATED RECEIVING TARGETS: count={len(deprecated_targets):,}  fund_aum={fmt_aum(dep_aum)}")
    print('\nTop 25 (by fund AUM):')
    for d in deprecated_targets[:25]:
        eid, name, vt, rows, aum = d
        print(f"  eid={eid} valid_to={vt} {name!r}  rows={rows:,}  fund_aum={fmt_aum(aum)}")

    # Also entities appearing as child_entity_id in entity_relationships with closed valid_to
    banner('1.5.3b SUPERSEDED — receiving institutions appearing as a closed child in entity_relationships')
    closed_children = con.execute("""
        SELECT DISTINCT child_entity_id, parent_entity_id, relationship_type, valid_to
        FROM entity_relationships
        WHERE valid_to IS NOT NULL AND valid_to <> DATE '9999-12-31'
    """).fetchall()
    closed_map = {row[0]: row for row in closed_children}
    super_targets = []
    for eid, name, rows, faum in fund_aum:
        if eid in closed_map:
            super_targets.append((eid, name, closed_map[eid], rows, faum or 0))
    super_targets.sort(key=lambda x: -x[4])
    print(f"  SUPERSEDED RECEIVING TARGETS: {len(super_targets):,}")
    for s in super_targets[:25]:
        eid, name, rel, rows, aum = s
        print(f"  eid={eid} {name!r}  rel={rel}  rows={rows:,}  fund_aum={fmt_aum(aum)}")

if __name__ == '__main__':
    main()
