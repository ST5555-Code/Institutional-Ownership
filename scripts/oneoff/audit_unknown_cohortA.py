"""Phase 1.4 - reattribute series_id='UNKNOWN' rows to real series_ids.

The 'UNKNOWN' literal is a pre-DERA-Session-2 loader fallback. We try to map
each (cik, fund_name) pair to a real series_id by:
  HIGH:   exact CIK + exact normalized fund_name match in fund_universe
  HIGH-H: exact CIK + exact normalized fund_name match in fund_holdings_v2 (real series_id)
  MEDIUM: exact CIK + fuzzy fund_name match (token-set / prefix overlap)
  LOW:    CIK only (single real series)
  NONE:   no match
"""
from __future__ import annotations

import csv
import os
import re
from collections import Counter

import duckdb

DB = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"


def norm(text):
    if not text:
        return ''
    out = text.lower().strip()
    out = re.sub(r"[^a-z0-9]+", " ", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def build_match_fn(fu_idx, fu_by_cik, fh_by_cik):
    """Closure that resolves a (cik, name) pair against fund_universe + fund_holdings_v2."""
    fu_strategy_by_series = {row[2]: row[3] for row in fu_idx}

    def lookup(cik, fund_name):
        name_n = norm(fund_name)
        for n2, s2, strat in fu_by_cik.get(cik, []):
            if norm(n2) == name_n:
                return ('HIGH', s2, strat, n2)
        for n2, s2 in fh_by_cik.get(cik, []):
            if norm(n2) == name_n:
                return ('HIGH-H', s2, fu_strategy_by_series.get(s2), n2)
        candidates_fu = fu_by_cik.get(cik, [])
        candidates_fh = fh_by_cik.get(cik, [])
        name_tokens = set(name_n.split())
        if not name_tokens:
            return ('NONE', None, None, None)
        best = None
        best_score = 0.0
        for n2, s2, strat in candidates_fu:
            t2 = set(norm(n2).split())
            if not t2:
                continue
            score = len(name_tokens & t2) / max(len(name_tokens | t2), 1)
            if score > best_score:
                best_score = score
                best = ('MEDIUM', s2, strat, n2)
        for n2, s2 in candidates_fh:
            t2 = set(norm(n2).split())
            if not t2:
                continue
            score = len(name_tokens & t2) / max(len(name_tokens | t2), 1)
            if score > best_score:
                best_score = score
                best = ('MEDIUM', s2, fu_strategy_by_series.get(s2), n2)
        if best and best_score >= 0.6:
            return best
        union = {s for _, s, _ in candidates_fu} | {s for _, s in candidates_fh}
        if len(union) == 1:
            s_only = next(iter(union))
            return ('LOW', s_only, fu_strategy_by_series.get(s_only), '<single-series-under-cik>')
        return ('NONE', None, None, None)

    return lookup


def main():
    con = duckdb.connect(DB, read_only=True)

    unk_q = """
    SELECT fund_cik, fund_name,
           COUNT(*) AS row_count,
           SUM(COALESCE(market_value_usd,0))/1e9 AS aum_b,
           ANY_VALUE(family_name) AS family_name,
           ANY_VALUE(quarter) AS sample_quarter,
           ANY_VALUE(report_date) AS sample_report_date,
           MIN(loaded_at) AS first_loaded,
           MAX(loaded_at) AS last_loaded
    FROM fund_holdings_v2
    WHERE series_id='UNKNOWN' AND is_latest=TRUE
    GROUP BY fund_cik, fund_name
    ORDER BY aum_b DESC
    """
    unk_rows = con.execute(unk_q).fetchall()
    print(f"=== Cohort A members (cik, fund_name) pairs: {len(unk_rows)} ===\n")

    fu_idx = con.execute(
        "SELECT fund_cik, fund_name, series_id, fund_strategy FROM fund_universe"
    ).fetchall()
    print(f"  fund_universe rows: {len(fu_idx):,}")

    fh_real = con.execute(
        """
        SELECT DISTINCT fund_cik, fund_name, series_id
        FROM fund_holdings_v2
        WHERE series_id <> 'UNKNOWN' AND series_id IS NOT NULL
        """
    ).fetchall()
    print(f"  distinct (cik, name, series) in fund_holdings_v2 (real series): {len(fh_real):,}")

    fu_by_cik = {}
    for cik_v, name_v, sid_v, strat_v in fu_idx:
        fu_by_cik.setdefault(cik_v, []).append((name_v, sid_v, strat_v))

    fh_by_cik = {}
    for cik_v, name_v, sid_v in fh_real:
        fh_by_cik.setdefault(cik_v, []).append((name_v, sid_v))

    lookup = build_match_fn(fu_idx, fu_by_cik, fh_by_cik)

    print("\n--- per-row attribution ---")
    print(f"{'CIK':<12} {'rows':>6} {'aum_b':>8}  {'conf':<8} {'target':<14} {'strategy':<14} | name | matched_to")
    results = []
    for cik_v, name_v, rc, aumb, fam, _qtr, _rdt, _fl, _ll in unk_rows:
        conf, target, strat, matched = lookup(cik_v, name_v)
        results.append((cik_v, name_v, rc, aumb, conf, target, strat, matched, fam))
        display_name = (name_v[:55] if name_v else '')
        print(f"{cik_v:<12} {rc:>6,d} {aumb:>8.3f}  {conf:<8} {str(target):<14} {str(strat):<14} | {display_name} | {matched}")

    print("\n--- aggregate by confidence ---")
    agg = Counter()
    agg_rows = Counter()
    agg_aum = Counter()
    for r in results:
        agg[r[4]] += 1
        agg_rows[r[4]] += r[2]
        agg_aum[r[4]] += r[3] or 0
    for k in ['HIGH', 'HIGH-H', 'MEDIUM', 'LOW', 'NONE']:
        print(f"  {k:<8} pairs={agg[k]:>3}  rows={agg_rows[k]:>6,d}  aum=${agg_aum[k]:>7.3f}B")

    out = os.path.join(os.path.dirname(__file__), '_unknown_cohortA_attribution.csv')
    with open(out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['cik', 'fund_name', 'row_count', 'aum_billions', 'confidence',
                         'target_series_id', 'target_strategy', 'matched_to_name', 'family_name'])
        for r in results:
            writer.writerow(r)
    print(f"\nWrote {out}")


if __name__ == '__main__':
    main()
