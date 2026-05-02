#!/usr/bin/env python3
"""Phase 1B.3 — Wrong-shelf rollup.

Read-only. For each SYN_<cik> series in fund_holdings_v2 (is_latest=TRUE),
compare:
  registered_name = managers.manager_name (by cik) OR entities.canonical_name (by entity_id matching cik via SYN parse)
  rollup_name     = fund_holdings_v2.dm_rollup_name

Token-set similarity (custom normalize then SequenceMatcher ratio).
Threshold <0.4 → mismatch.
"""
import duckdb
import re
from difflib import SequenceMatcher

DB = 'data/13f.duckdb'

STOP = {
    'inc', 'inc.', 'incorporated', 'llc', 'l.l.c.', 'lp', 'l.p.',
    'lllp', 'plc', 'co', 'co.', 'company', 'corp', 'corp.', 'corporation',
    'fund', 'funds', 'trust', 'the', 'of', '&', 'and',
    'mgmt', 'management', 'mgt', 'capital', 'partners', 'group',
    'holdings', 'holding', 'gp', 'lp.', 'sa', 'ag', 'na', 'nv',
    'limited', 'ltd', 'ltd.', 'series', 'advisors', 'advisers',
    'asset', 'investments', 'investment', 'co/de', 'co/'
}

def normalize_tokens(s):
    if not s:
        return set()
    s = s.lower()
    s = re.sub(r"[^\w\s]", ' ', s)
    toks = [t for t in s.split() if t and t not in STOP]
    return set(toks)

def token_set_sim(a, b):
    ta = normalize_tokens(a)
    tb = normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    jacc = len(inter) / len(union) if union else 0.0
    # Also string ratio of joined sorted tokens
    sr = SequenceMatcher(None, ' '.join(sorted(ta)), ' '.join(sorted(tb))).ratio()
    return max(jacc, sr)

def fmt_aum(v):
    if v is None: return '$0'
    return f"${v/1e9:,.2f}B"

def main():
    con = duckdb.connect(DB, read_only=True)

    # Pull SYN series rollup signals.
    # WHY two flavours: SYN funds use the fund's own CIK as a synthetic series.
    # We flag in two ways:
    #   (a) name-mismatch: fund-name vs rollup-name token sim (noisy — fund names rarely match sponsor brands)
    #   (b) sponsor-shelf-mismatch: when fund_cik appears in managers table as a registered filer,
    #       compare managers.manager_name (the registered filer) to dm_rollup_name. This catches the
    #       Calamos-shape / ASA-shape — where the fund's *own* CIK identifies the right institution but
    #       the rollup points elsewhere.
    rows = con.execute("""
        SELECT
          fh.series_id,
          fh.fund_cik,
          fh.dm_rollup_entity_id,
          fh.dm_rollup_name,
          MAX(fh.fund_name) AS fund_name,
          MAX(m.manager_name) AS reg_manager_name,
          MAX(e.canonical_name) AS cik_canonical,
          MAX(e_ei.entity_id) AS cik_entity_id,
          COUNT(*) AS n_rows,
          SUM(market_value_usd) AS aum
        FROM fund_holdings_v2 fh
        LEFT JOIN managers m ON m.cik = fh.fund_cik
        LEFT JOIN entity_identifiers ei
          ON ei.identifier_type='cik' AND ei.identifier_value = fh.fund_cik
        LEFT JOIN entities e_ei ON e_ei.entity_id = ei.entity_id
        LEFT JOIN entities e ON e.entity_id = ei.entity_id
        WHERE fh.is_latest=TRUE AND fh.series_id LIKE 'SYN_%'
        GROUP BY 1,2,3,4
    """).fetchall()
    print(f"SYN series groups (is_latest=TRUE): {len(rows):,}")

    # (a) Loose name-mismatch (informational only)
    name_flagged = []
    for r in rows:
        series_id, fund_cik, dm_rollup_id, rollup_name, fund_name, reg_name, cik_canon, cik_eid, n, aum = r
        cmp_name = fund_name or cik_canon
        if not cmp_name or not rollup_name:
            continue
        sim = token_set_sim(cmp_name, rollup_name)
        if sim < 0.4:
            name_flagged.append((series_id, fund_cik, cmp_name, rollup_name, sim, n, aum or 0))
    print(f"\n(a) NAME-MISMATCH (fund_name vs rollup_name sim<0.4): groups={len(name_flagged):,}")
    print('    Note: this is INFORMATIONAL — fund names rarely match sponsor brand. Most are correct rollups.')

    # (b) Sponsor-shelf-mismatch: fund_cik IS a registered filer in managers, AND the registered
    #     manager name does not match the rollup name AND the entity_id behind the CIK does not match
    #     the rollup entity. This is the "ASA shape".
    shelf_flagged = []
    total_flag_rows = 0
    total_flag_aum = 0.0
    for r in rows:
        series_id, fund_cik, dm_rollup_id, rollup_name, fund_name, reg_name, cik_canon, cik_eid, n, aum = r
        if not reg_name:
            continue  # CIK not a registered 13F filer — skip
        if not rollup_name:
            continue
        sim = token_set_sim(reg_name, rollup_name)
        # Exclude cases where the entity_id linked to this CIK matches the rollup id directly.
        cik_matches_rollup = (cik_eid is not None and dm_rollup_id is not None and cik_eid == dm_rollup_id)
        if sim < 0.4 and not cik_matches_rollup:
            shelf_flagged.append((series_id, fund_cik, reg_name, rollup_name, sim, n, aum or 0, cik_eid, dm_rollup_id))
            total_flag_rows += n
            total_flag_aum += (aum or 0)

    shelf_flagged.sort(key=lambda x: -x[6])
    print(f"\n(b) SPONSOR-SHELF-MISMATCH (fund_cik is a registered filer but rollup name diverges):")
    print(f"    groups={len(shelf_flagged):,}  rows={total_flag_rows:,}  aum={fmt_aum(total_flag_aum)}")
    print('\nTop 25 (by AUM):')
    print(f"  {'series_id':<22} {'cik':<12} {'sim':>5}  manager_name  ||  rollup_name  ||  cik_eid->dm_rollup_eid  ||  rows  ||  aum")
    for f in shelf_flagged[:25]:
        series_id, fund_cik, reg_name, rollup_name, sim, n, aum, ceid, deid = f
        print(f"  {series_id:<22} {fund_cik:<12} {sim:.2f}  {reg_name!r:<55} || {rollup_name!r:<55} || {ceid}->{deid} || {n} || {fmt_aum(aum)}")

    # Output full lists count summary
    print(f"\nSummary: name_flagged={len(name_flagged)} shelf_flagged={len(shelf_flagged)}")

if __name__ == '__main__':
    main()
