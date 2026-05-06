"""Read-only parity probe for compute_aum_for_subtree vs hypothetical
top-parent grain SUM, on three known umbrella entities for 2025Q4.

CP-5: cp-5-aum-subtree-callers-recon. Compares filer-CIK SUM (current
behavior) vs top-parent grain SUM via unified_holdings.

Run: python3 scripts/oneoff/cp_5_aum_subtree_parity_probe.py
"""
import csv
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
# Worktrees don't carry data/; resolve to the main repo if the local path
# is missing.
DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/"
          "13f-ownership/data/13f.duckdb")
QUARTER = "2025Q4"
ENTITIES = [
    (4375, "Vanguard family"),
    (3241, "BlackRock"),
    (12, "Capital Group umbrella"),
]


def filer_grain_sum(con, eid, q):
    row = con.execute("""
        WITH RECURSIVE descendants(entity_id, depth) AS (
            SELECT CAST(? AS BIGINT), 0
            UNION ALL
            SELECT er.child_entity_id, d.depth + 1
            FROM entity_relationships er
            JOIN descendants d ON d.entity_id = er.parent_entity_id
            WHERE er.valid_to = DATE '9999-12-31'
              AND er.relationship_type != 'sub_adviser'
              AND d.depth < 4
        ),
        subtree_ciks AS (
            SELECT DISTINCT ei.identifier_value AS cik
            FROM descendants d
            JOIN entity_identifiers ei
              ON ei.entity_id = d.entity_id
             AND ei.identifier_type = 'cik'
             AND ei.valid_to = DATE '9999-12-31'
        )
        SELECT SUM(h.market_value_usd), COUNT(DISTINCT h.cik)
        FROM holdings_v2 h
        WHERE h.cik IN (SELECT cik FROM subtree_ciks)
          AND h.quarter = ?
          AND h.is_latest = TRUE
    """, [int(eid), q]).fetchone()
    return (float(row[0]) if row and row[0] is not None else None,
            int(row[1]) if row else 0)


def top_parent_grain_sum(con, eid, q):
    """Top-parent grain SUM via the CP-5.1 inst_to_top_parent view.

    Maps every holdings_v2 row through h.entity_id → ittp.entity_id →
    ittp.top_parent_entity_id, then sums where top-parent matches the
    target. This is the canonical grain that unified_holdings exposes
    as a precomputed view.
    """
    row = con.execute("""
        SELECT SUM(h.market_value_usd), COUNT(DISTINCT h.cik)
        FROM holdings_v2 h
        JOIN inst_to_top_parent ittp ON ittp.entity_id = h.entity_id
        WHERE ittp.top_parent_entity_id = ?
          AND h.quarter = ?
          AND h.is_latest = TRUE
    """, [int(eid), q]).fetchone()
    return (float(row[0]) if row and row[0] is not None else None,
            int(row[1]) if row else 0)


def main():
    if not DB.exists():
        print(f"DB not found: {DB}", file=sys.stderr)
        sys.exit(1)
    con = duckdb.connect(str(DB), read_only=True)

    rows = []
    print(f"{'eid':>6} {'name':<28} {'filer_sum':>16} {'tp_sum':>16} "
          f"{'delta':>14} {'pct':>8}  ciks  rows_tp")
    for eid, name in ENTITIES:
        f_sum, n_ciks = filer_grain_sum(con, eid, QUARTER)
        t_sum, n_rows_tp = top_parent_grain_sum(con, eid, QUARTER)
        delta = (t_sum or 0) - (f_sum or 0)
        pct = (delta / f_sum * 100.0) if f_sum else 0.0
        print(f"{eid:>6} {name:<28} {f_sum or 0:>16,.0f} {t_sum or 0:>16,.0f} "
              f"{delta:>14,.0f} {pct:>7.2f}% {n_ciks:>5} {n_rows_tp:>8,}")
        rows.append({
            "entity_id": eid, "name": name, "quarter": QUARTER,
            "filer_grain_sum": f_sum, "top_parent_grain_sum": t_sum,
            "delta": delta, "delta_pct": round(pct, 4),
            "filer_cik_count": n_ciks, "top_parent_row_count": n_rows_tp,
        })

    out = ROOT / "data" / "working" / "cp-5-aum-subtree-parity-probe.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
