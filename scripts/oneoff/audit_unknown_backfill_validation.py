"""Phase 2.2 + 2.3 - three-lens re-validation of PR #245 orphan backfill.

For each of the 301 fund_universe rows with strategy_source='orphan_backfill_2026Q2',
run three lens checks:
  Lens A - INDEX_PATTERNS / EXCLUDE_PATTERNS / active-signal keyword check on fund_name.
  Lens B - holdings shape from fund_holdings_v2 (equity / bond / derivative pct).
  Lens C - fund_strategy_at_filing snapshot distribution (was PR #245 majority claim 100% support?).

Output a CSV + a top-flagged summary.
"""
from __future__ import annotations

import csv
import os
import re
import sys

import duckdb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
# pylint: disable=wrong-import-position
from scripts.pipeline.nport_parsers import EXCLUDE_PATTERNS, INDEX_PATTERNS

DB = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"

ACTIVE_FUND_STRATEGIES = {'active', 'balanced', 'multi_asset'}
PASSIVE_FUND_STRATEGIES = {'passive', 'bond_or_other', 'excluded', 'final_filing'}

ACTIVE_SIGNAL = re.compile(
    r"\b(income\s*fund|municipal|closed[-\s]*end|interval|bdc|cef|"
    r"opportunit(?:y|ies)|hedge|alpha|absolute\s*return|long[-\s]*short|"
    r"equity\s*income|dividend\s*growth)\b",
    re.IGNORECASE,
)
BOND_CARVE_OUT = re.compile(
    r"\b(bond|fixed[-\s]*income|treasury|municipal|credit|income\s*fund|high[-\s]*yield)\b",
    re.IGNORECASE,
)


def lens_a(fund_name, strategy):
    """Mirror classify_fund() name-rule contract."""
    if not fund_name:
        return ('PASS', 'no name')
    is_idx = bool(INDEX_PATTERNS.search(fund_name))
    is_exc = bool(EXCLUDE_PATTERNS.search(fund_name))
    if is_idx:
        if strategy != 'passive':
            return ('FLAG_PASSIVE_NAME', f"INDEX_PATTERN match but strategy={strategy}")
        return ('PASS', 'INDEX_PATTERN -> passive (consistent)')
    if is_exc:
        if strategy != 'excluded':
            return ('FLAG_EXCLUDE_NAME', f"EXCLUDE_PATTERN match but strategy={strategy}")
        return ('PASS', 'EXCLUDE_PATTERN -> excluded (consistent)')
    if ACTIVE_SIGNAL.search(fund_name) and strategy not in ACTIVE_FUND_STRATEGIES:
        if not BOND_CARVE_OUT.search(fund_name):
            return ('FLAG_ACTIVE_NAME', f"ACTIVE_SIGNAL match but strategy={strategy} (no bond carve-out hit)")
    return ('PASS', 'name-pattern consistent')


def lens_b(fund_name, strategy, eq_val, bd_val, dr_val, _un_val, tot_val):
    """Holdings shape vs canonical strategy. Skipped when name short-circuits classifier."""
    if not tot_val or tot_val <= 0:
        return ('NO_HOLDINGS', 'no holdings to validate against', None, None, None)
    eq_pct = (eq_val or 0) / tot_val * 100
    bd_pct = (bd_val or 0) / tot_val * 100
    dr_pct = (dr_val or 0) / tot_val * 100

    name_idx = fund_name and bool(INDEX_PATTERNS.search(fund_name))
    name_exc = fund_name and bool(EXCLUDE_PATTERNS.search(fund_name))
    if (strategy == 'passive' and name_idx) or (strategy == 'excluded' and name_exc):
        return ('PASS', f"name-driven {strategy}; shape skipped (eq={eq_pct:.1f}%)", eq_pct, bd_pct, dr_pct)
    if strategy == 'final_filing':
        return ('PASS', 'final_filing; shape skipped', eq_pct, bd_pct, dr_pct)

    if eq_pct >= 90:
        expected = {'active'}
    elif 60 <= eq_pct < 90:
        expected = {'balanced'}
    elif 30 <= eq_pct < 60:
        expected = {'multi_asset'}
    else:
        expected = {'bond_or_other'}
    near_boundary = (
        (80 <= eq_pct < 90 and strategy in {'active', 'balanced'})
        or (50 <= eq_pct < 60 and strategy in {'multi_asset', 'balanced'})
        or (20 <= eq_pct < 30 and strategy in {'bond_or_other', 'multi_asset'})
    )
    if strategy in expected or near_boundary:
        return ('PASS', f"shape eq={eq_pct:.1f}% bd={bd_pct:.1f}% matches {strategy}", eq_pct, bd_pct, dr_pct)
    return ('FLAG_SHAPE',
            f"eq={eq_pct:.1f}% bd={bd_pct:.1f}% dr={dr_pct:.1f}% expected {expected} but strategy={strategy}",
            eq_pct, bd_pct, dr_pct)


def lens_c(strategy, snapshot_rows):
    if not snapshot_rows:
        return ('NO_SNAPSHOT', 'no snapshot rows', None, None)
    total_w = sum(r[1] for r in snapshot_rows)
    if total_w <= 0:
        return ('NO_SNAPSHOT', 'zero-weight snapshot', None, None)
    by_strategy = {}
    for snap_strat, weight, _n in snapshot_rows:
        by_strategy[snap_strat] = by_strategy.get(snap_strat, 0) + weight
    dom_strat, dom_weight = max(by_strategy.items(), key=lambda kv: kv[1])
    support_pct = dom_weight / total_w * 100
    if dom_strat == strategy and support_pct >= 99.5:
        return ('PASS', f"snapshot 100% {dom_strat}", dom_strat, support_pct)
    if dom_strat != strategy:
        return ('FLAG_SNAPSHOT_DIVERGE',
                f"snapshot dominant {dom_strat} ({support_pct:.1f}%) but canonical {strategy}",
                dom_strat, support_pct)
    return ('FLAG_SUPPORT_LT_100',
            f"snapshot dominant {dom_strat} only {support_pct:.1f}% support",
            dom_strat, support_pct)


def main():
    con = duckdb.connect(DB, read_only=True)
    print("Loading 301 backfilled funds + their holdings shape + snapshot distributions...")

    funds_q = """
    WITH back AS (
        SELECT series_id, fund_cik, fund_name, fund_strategy
        FROM fund_universe
        WHERE strategy_source='orphan_backfill_2026Q2'
    ),
    shape AS (
        SELECT
            h.series_id,
            SUM(CASE WHEN UPPER(h.asset_category) IN ('EC') THEN COALESCE(h.market_value_usd,0) ELSE 0 END) AS eq_val,
            SUM(CASE WHEN UPPER(h.asset_category) IN ('DBT') THEN COALESCE(h.market_value_usd,0) ELSE 0 END) AS bd_val,
            SUM(CASE WHEN UPPER(h.asset_category) IN ('DIR','OPT','FUT','FWD','SWP') THEN COALESCE(h.market_value_usd,0) ELSE 0 END) AS dr_val,
            SUM(CASE WHEN h.asset_category IS NULL OR h.asset_category='' THEN COALESCE(h.market_value_usd,0) ELSE 0 END) AS un_val,
            SUM(COALESCE(h.market_value_usd,0)) AS tot_val,
            COUNT(*) AS n_rows
        FROM fund_holdings_v2 h
        JOIN back b USING(series_id)
        WHERE h.is_latest = TRUE
        GROUP BY h.series_id
    )
    SELECT
        b.series_id, b.fund_cik, b.fund_name, b.fund_strategy,
        s.eq_val, s.bd_val, s.dr_val, s.un_val, s.tot_val, s.n_rows
    FROM back b
    LEFT JOIN shape s USING(series_id)
    """
    funds = con.execute(funds_q).fetchall()
    print(f"  fetched {len(funds)} backfilled funds")

    snap_q = """
    SELECT
        h.series_id,
        COALESCE(h.fund_strategy_at_filing, '<NULL>') AS sf,
        SUM(COALESCE(h.market_value_usd,0)) AS w_val,
        COUNT(*) AS n
    FROM fund_holdings_v2 h
    JOIN fund_universe b ON b.series_id = h.series_id AND b.strategy_source='orphan_backfill_2026Q2'
    WHERE h.is_latest = TRUE
    GROUP BY h.series_id, sf
    """
    snap_rows = con.execute(snap_q).fetchall()
    snap_by_series = {}
    for sid, sf, weight, count in snap_rows:
        snap_by_series.setdefault(sid, []).append((sf, weight, count))

    out_path = os.path.join(os.path.dirname(__file__), '_unknown_backfill_validation.csv')
    flagged = []
    counts = {'PASS_ALL': 0}
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['series_id', 'fund_cik', 'fund_name', 'strategy', 'eq_pct', 'bd_pct', 'dr_pct',
                         'lens_a', 'lens_b', 'lens_c', 'note_a', 'note_b', 'note_c',
                         'snapshot_dominant', 'snapshot_support_pct'])
        for sid, cik, fund_name, strat, eqv, bdv, drv, unv, totv, _nrows in funds:
            a_v, a_n = lens_a(fund_name, strat)
            b_v, b_n, eq_p, bd_p, dr_p = lens_b(fund_name, strat, eqv or 0, bdv or 0, drv or 0, unv or 0, totv or 0)
            c_v, c_n, dom_strat, sup_pct = lens_c(strat, snap_by_series.get(sid, []))
            writer.writerow([sid, cik, fund_name, strat,
                             f"{eq_p:.2f}" if eq_p is not None else "",
                             f"{bd_p:.2f}" if bd_p is not None else "",
                             f"{dr_p:.2f}" if dr_p is not None else "",
                             a_v, b_v, c_v, a_n, b_n, c_n,
                             str(dom_strat) if dom_strat else "",
                             f"{sup_pct:.2f}" if sup_pct is not None else ""])
            any_flag = any(v.startswith('FLAG') for v in (a_v, b_v, c_v))
            if any_flag:
                flagged.append((sid, cik, fund_name, strat, a_v, b_v, c_v, a_n, b_n, c_n))
            else:
                counts['PASS_ALL'] += 1
            for k in (a_v, b_v, c_v):
                counts[k] = counts.get(k, 0) + 1

    print(f"\nValidation written to {out_path}")
    print("\n=== Aggregate verdict counts ===")
    for k in sorted(counts):
        print(f"  {k:<26} {counts[k]}")

    print(f"\n=== Flagged funds: {len(flagged)} ===")
    for sid, cik, fund_name, strat, a_v, b_v, c_v, a_n, b_n, c_n in flagged:
        print(f"  {sid:<14} strategy={strat:<14}  A={a_v:<22} B={b_v:<22} C={c_v:<22}")
        print(f"     name: {fund_name}")
        if a_v.startswith('FLAG'):
            print(f"     A note: {a_n}")
        if b_v.startswith('FLAG'):
            print(f"     B note: {b_n}")
        if c_v.startswith('FLAG'):
            print(f"     C note: {c_n}")


if __name__ == '__main__':
    main()
