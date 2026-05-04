"""CP-5 Bundle B — Phase 4: entity graph temporal stability.

Goal: characterize current schema's capability for time-versioned entity
relationships, and recommend an architecture for future 10+ year history loads.

Empirical inputs:
  4.1 entity_relationships SCD usage (valid_from / valid_to / closed rows)
  4.2 'merge' control_type cohort (encoded M&A events?)
  4.3 entity_relationships valid_from distribution

Outputs (no CSV — finds are documented in the findings doc directly):
  prints to stdout for capture into findings §4.

Read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cp_5_bundle_b_common import (  # noqa: E402
    SENTINEL,
    connect,
)


def main() -> int:
    con = connect()

    print("=" * 80)
    print("Phase 4 — entity graph temporal stability")
    print("=" * 80)

    # 4.1 — entity_relationships SCD usage
    print("\n  4.1 — entity_relationships SCD shape")
    print(con.execute(f"""
      SELECT
        COUNT(*) AS total_rows,
        SUM(CASE WHEN valid_to = {SENTINEL} THEN 1 ELSE 0 END) AS open_rows,
        SUM(CASE WHEN valid_to <> {SENTINEL} THEN 1 ELSE 0 END) AS closed_rows,
        MIN(valid_from) AS earliest_valid_from,
        MAX(valid_from) AS latest_valid_from,
        MIN(CASE WHEN valid_to <> {SENTINEL} THEN valid_to END) AS earliest_close,
        MAX(CASE WHEN valid_to <> {SENTINEL} THEN valid_to END) AS latest_close
      FROM entity_relationships
    """).fetchdf().to_string(index=False))

    # 4.2 — control_type='merge' cohort
    print("\n  4.2 — entity_relationships control_type='merge' rows")
    merges = con.execute(f"""
      SELECT er.relationship_id, er.parent_entity_id, er.child_entity_id,
             pec.display_name AS parent_name,
             cec.display_name AS child_name,
             er.valid_from, er.valid_to, er.source, er.is_inferred
      FROM entity_relationships er
      JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
      JOIN entity_current cec ON cec.entity_id = er.child_entity_id
      WHERE er.control_type = 'merge'
      ORDER BY er.valid_from
    """).fetchdf()
    print(f"    'merge' rows: {len(merges)}")
    print(merges.to_string(index=False, max_colwidth=50))

    # 4.3 — closed rows hint at corporate-action history
    print("\n  4.3 — sample of closed entity_relationships (valid_to != sentinel)")
    closed = con.execute(f"""
      SELECT er.relationship_id, er.parent_entity_id, er.child_entity_id,
             pec.display_name AS parent_name,
             cec.display_name AS child_name,
             er.control_type, er.valid_from, er.valid_to, er.source
      FROM entity_relationships er
      JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
      JOIN entity_current cec ON cec.entity_id = er.child_entity_id
      WHERE er.valid_to <> {SENTINEL}
        AND pec.entity_type='institution' AND cec.entity_type='institution'
      ORDER BY er.valid_to DESC
      LIMIT 30
    """).fetchdf()
    print(f"    inst-inst closed rows surfaced: {len(closed)}")
    if len(closed):
        print(closed.to_string(index=False, max_colwidth=40))

    # 4.4 — distribution of valid_from for OPEN inst-inst control rows
    print("\n  4.4 — valid_from year distribution for OPEN inst-inst control rows")
    vf = con.execute(f"""
      SELECT EXTRACT(YEAR FROM valid_from) AS year, COUNT(*) AS n
      FROM entity_relationships er
      JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
      JOIN entity_current cec ON cec.entity_id = er.child_entity_id
      WHERE er.valid_to = {SENTINEL}
        AND er.control_type IN ('control','mutual','merge')
        AND pec.entity_type='institution' AND cec.entity_type='institution'
      GROUP BY 1
      ORDER BY 1
    """).fetchdf()
    print(vf.to_string(index=False))

    # 4.5 — Are M&A events from public knowledge represented as inst→inst
    # parent edges in the current graph? Probe a few known 2017-2025 cases.
    probes = [
        ("Janus Henderson 2017 merger (Janus → Henderson)", ["JANUS", "HENDERSON"]),
        ("Franklin / Legg Mason 2020", ["FRANKLIN", "LEGG MASON"]),
        ("BlackRock acquired Aperio 2021", ["BLACKROCK", "APERIO"]),
        ("Morgan Stanley acquired Eaton Vance 2021", ["MORGAN STANLEY", "EATON VANCE"]),
        ("Affiliated Managers Group rollups", ["AFFILIATED MANAGERS"]),
    ]
    print("\n  4.5 — known M&A event coverage probe (current graph)")
    for label, terms in probes:
        like = " AND ".join([f"UPPER(pec.display_name) LIKE '%{t}%'" for t in terms[:1]])
        rev = " AND ".join([f"UPPER(cec.display_name) LIKE '%{t}%'" for t in terms[1:]])
        cond = f"({like}) AND ({rev})" if rev else f"({like})"
        rs = con.execute(f"""
          SELECT er.parent_entity_id, pec.display_name AS parent_name,
                 er.child_entity_id, cec.display_name AS child_name,
                 er.control_type, er.valid_from, er.valid_to
          FROM entity_relationships er
          JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
          JOIN entity_current cec ON cec.entity_id = er.child_entity_id
          WHERE {cond}
            AND pec.entity_type='institution' AND cec.entity_type='institution'
          ORDER BY er.valid_from
          LIMIT 10
        """).fetchdf()
        print(f"    {label}: {len(rs)} matching ER rows")
        if len(rs):
            print(rs.to_string(index=False, max_colwidth=35))

    return 0


if __name__ == "__main__":
    sys.exit(main())
