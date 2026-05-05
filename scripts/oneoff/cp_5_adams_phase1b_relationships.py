#!/usr/bin/env python3
"""cp_5_adams_phase1b_relationships.py — probe relationship shapes per pair.

Inspects entity_relationships for each (canonical, duplicate) pair to determine:
  - Op B' shape: pre-existing canonical<->duplicate edges that need closing
  - Op B count: rows where parent_entity_id=duplicate AND child!=canonical
  - Cross-pair contamination: do duplicates share relationships?

Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DB = BASE_DIR / "data" / "13f.duckdb"

OPEN_DATE = "9999-12-31"

PAIRS: list[tuple[int, int, str]] = [
    (4909, 19509, "Adams Asset Advisors"),
    (2961, 20213, "Adams Diversified Equity Fund"),
    (2961, 20214, "Adams Diversified Equity Fund"),
    (2961, 20215, "Adams Diversified Equity Fund"),
    (6471, 20210, "Adams Natural Resources Fund"),
    (6471, 20211, "Adams Natural Resources Fund"),
    (6471, 20212, "Adams Natural Resources Fund"),
]


def probe_pair(con, canonical: int, duplicate: int, label: str) -> None:
    print(f"\n{'='*90}\nPair: {label} canonical={canonical} duplicate={duplicate}\n{'='*90}")

    # Op B' candidates — direct canonical<->duplicate open relationships
    bp = con.execute(
        """
        SELECT relationship_id, parent_entity_id, child_entity_id, relationship_type, source
        FROM entity_relationships
        WHERE valid_to = DATE '9999-12-31'
          AND ( (parent_entity_id = ? AND child_entity_id = ?)
             OR (parent_entity_id = ? AND child_entity_id = ?) )
        """,
        [canonical, duplicate, duplicate, canonical],
    ).fetchall()
    print(f"  Op B' candidates ({len(bp)} row(s)):")
    for r in bp:
        print(f"    rel_id={r[0]} parent={r[1]} child={r[2]} type={r[3]} source={r[4]}")

    # Op B candidates — duplicate as parent, child != canonical
    b_parent = con.execute(
        """
        SELECT relationship_id, parent_entity_id, child_entity_id, relationship_type, source
        FROM entity_relationships
        WHERE parent_entity_id = ?
          AND child_entity_id != ?
          AND valid_to = DATE '9999-12-31'
        """,
        [duplicate, canonical],
    ).fetchall()
    print(f"  Op B parent-side candidates ({len(b_parent)} row(s) — duplicate as parent, child != canonical):")
    for r in b_parent:
        print(f"    rel_id={r[0]} parent={r[1]} child={r[2]} type={r[3]} source={r[4]}")

    # Op B candidates — duplicate as child, parent != canonical (NEW per plan)
    b_child = con.execute(
        """
        SELECT relationship_id, parent_entity_id, child_entity_id, relationship_type, source
        FROM entity_relationships
        WHERE child_entity_id = ?
          AND parent_entity_id != ?
          AND valid_to = DATE '9999-12-31'
        """,
        [duplicate, canonical],
    ).fetchall()
    print(f"  Op B child-side candidates ({len(b_child)} row(s) — duplicate as child, parent != canonical):")
    for r in b_child:
        print(f"    rel_id={r[0]} parent={r[1]} child={r[2]} type={r[3]} source={r[4]}")

    # Aliases
    aliases = con.execute(
        """
        SELECT alias_name, alias_type, is_preferred, source_table
        FROM entity_aliases
        WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
        """,
        [duplicate],
    ).fetchall()
    print(f"  duplicate aliases ({len(aliases)} row(s)):")
    for a in aliases:
        print(f"    name={a[0]!r} type={a[1]} preferred={a[2]} source={a[3]}")

    canonical_aliases = con.execute(
        """
        SELECT alias_name, alias_type, is_preferred
        FROM entity_aliases
        WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
        ORDER BY is_preferred DESC, alias_type
        """,
        [canonical],
    ).fetchall()
    print(f"  canonical aliases ({len(canonical_aliases)} row(s)):")
    for a in canonical_aliases:
        print(f"    name={a[0]!r} type={a[1]} preferred={a[2]}")

    # ERH AT-side detail (Op H scope)
    erh_at = con.execute(
        """
        SELECT entity_id, rollup_type, rule_applied, confidence, source
        FROM entity_rollup_history
        WHERE rollup_entity_id = ? AND valid_to = DATE '9999-12-31'
        ORDER BY entity_id, rollup_type
        """,
        [duplicate],
    ).fetchall()
    print(f"  Op H AT-side rows ({len(erh_at)} row(s)):")
    for r in erh_at:
        canonical_marker = "  [SELF-ROLLUP CASE]" if int(r[0]) == canonical else ""
        print(f"    entity_id={r[0]} rollup_type={r[1]} rule={r[2]} conf={r[3]} src={r[4]}{canonical_marker}")

    # ERH FROM-side detail (Op F scope)
    erh_from = con.execute(
        """
        SELECT rollup_entity_id, rollup_type, rule_applied, confidence, source
        FROM entity_rollup_history
        WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
        ORDER BY rollup_type
        """,
        [duplicate],
    ).fetchall()
    print(f"  Op F FROM-side rows ({len(erh_from)} row(s)):")
    for r in erh_from:
        print(f"    rollup_entity_id={r[0]} rollup_type={r[1]} rule={r[2]} conf={r[3]} src={r[4]}")

    # Identifiers
    ids = con.execute(
        """
        SELECT identifier_type, identifier_value, valid_to
        FROM entity_identifiers
        WHERE entity_id = ?
        ORDER BY identifier_type, valid_from
        """,
        [duplicate],
    ).fetchall()
    print(f"  duplicate identifiers ({len(ids)} row(s)):")
    for r in ids:
        print(f"    type={r[0]} value={r[1]} valid_to={r[2]}")

    # Pre-flight collision check for Op H Branch 1
    # Are there any open ERH rows for fund_eids that already have an open row at canonical_eid AND that fund_eid will be re-pointed?
    if erh_at:
        fund_eids = list({int(r[0]) for r in erh_at if int(r[0]) != canonical})
        if fund_eids:
            collisions = con.execute(
                """
                SELECT entity_id, rollup_type, rollup_entity_id
                FROM entity_rollup_history
                WHERE entity_id IN ?
                  AND rollup_entity_id = ?
                  AND valid_to = DATE '9999-12-31'
                """,
                [fund_eids, canonical],
            ).fetchall()
            print(f"  Op H Branch 1 collision check: {len(collisions)} pre-existing rows on canonical")
            for c in collisions:
                print(f"    [COLLISION] entity_id={c[0]} rollup_type={c[1]} rollup_entity_id={c[2]}")


def main() -> int:
    if not DB.exists():
        print(f"ERROR: db not found: {DB}", file=sys.stderr)
        return 1
    con = duckdb.connect(str(DB), read_only=True)
    try:
        for canonical, duplicate, label in PAIRS:
            probe_pair(con, canonical, duplicate, label)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
