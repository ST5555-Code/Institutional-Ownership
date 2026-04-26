"""
DM13-A — suppress 131 self-referential ADV_SCHEDULE_A edges (parser bug).

Category A of the DM13 cleanup. The ADV Schedule A parser produced edges
where parent_entity_id == child_entity_id. These are nonsensical (an entity
cannot wholly-own itself) and trace to a single parser bug.

Scope: every entity_relationships row with
  source = 'ADV_SCHEDULE_A' AND parent_entity_id = child_entity_id
This includes 1 currently-active row plus 130 already-closed rows. Persistent
overrides are written for ALL 131 so that any future build_entities.py --reset
that re-introduces these edges will close them again.

Action per row: write one suppress_relationship override into
entity_overrides_persistent. The override engine
(scripts/build_entities.py:854) reads relationship_context JSON, resolves
parent/child via CIK or entity_id fallback, then closes the edge.

Writes against STAGING ONLY. Promotion is a separate step
(promote_staging.py --approved).

Idempotent: re-running skips rows where an override with matching reason +
relationship_id already exists.

Verification (post-promote):
  - SELECT COUNT(*) FROM entity_relationships
    WHERE source='ADV_SCHEDULE_A' AND parent_entity_id=child_entity_id
      AND valid_to=DATE '9999-12-31'   -- expect 0
  - SELECT COUNT(*) FROM entity_overrides_persistent
    WHERE reason ILIKE '%DM13-A%'      -- expect 131
"""

import json
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")
ANALYST = "claude-dm13a"
REASON = "DM13-A: self-referential ADV_SCHEDULE_A edge (parser bug)"


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    # MIN(cik) per entity to deduplicate when an entity has multiple active CIK
    # rows (4 such cases observed). Picks deterministically, doesn't duplicate.
    rows = con.execute("""
        SELECT er.relationship_id,
               er.parent_entity_id,
               er.relationship_type,
               (SELECT MIN(ei.identifier_value)
                  FROM entity_identifiers ei
                 WHERE ei.entity_id = er.parent_entity_id
                   AND ei.identifier_type = 'cik'
                   AND ei.valid_to = DATE '9999-12-31') AS cik
          FROM entity_relationships er
         WHERE er.source = 'ADV_SCHEDULE_A'
           AND er.parent_entity_id = er.child_entity_id
         ORDER BY er.relationship_id
    """).fetchall()
    print(f"BEFORE: {len(rows)} ADV_SCHEDULE_A self-loop rows in staging")

    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    baseline_active = con.execute("""
        SELECT COUNT(*) FROM entity_relationships
         WHERE source='ADV_SCHEDULE_A'
           AND parent_entity_id = child_entity_id
           AND valid_to = DATE '9999-12-31'
    """).fetchone()[0]
    print(f"BEFORE: overrides={baseline_ov}  active self-loops={baseline_active}")

    con.execute("BEGIN TRANSACTION")
    inserted = 0
    skipped = 0
    try:
        for rel_id, eid, rel_type, cik in rows:
            existing = con.execute("""
                SELECT override_id FROM entity_overrides_persistent
                 WHERE action = 'suppress_relationship'
                   AND reason = ?
                   AND old_value = ?
                   AND still_valid = TRUE
            """, [REASON, str(rel_id)]).fetchone()
            if existing:
                skipped += 1
                continue

            ctx = {
                "parent_entity_id": int(eid),
                "child_entity_id": int(eid),
                "relationship_type": rel_type,
            }
            if cik is not None:
                ctx["parent_cik"] = cik
                ctx["child_cik"] = cik

            new_id = con.execute(
                "SELECT COALESCE(MAX(override_id), 0) + 1 "
                "FROM entity_overrides_persistent"
            ).fetchone()[0]
            con.execute("""
                INSERT INTO entity_overrides_persistent (
                    override_id, entity_cik, action, field, old_value,
                    new_value, reason, analyst, still_valid,
                    identifier_type, identifier_value, rollup_type,
                    relationship_context
                ) VALUES (
                    ?, NULL, 'suppress_relationship',
                    'relationship_id', ?, 'suppress',
                    ?, ?, TRUE,
                    'cik', NULL, 'economic_control_v1',
                    ?
                )
            """, [new_id, str(rel_id), REASON, ANALYST, json.dumps(ctx)])
            inserted += 1

        # Immediate edge closure (matches DM14b pattern). Persistent overrides
        # protect against rebuild re-introducing the edges; this UPDATE
        # closes whatever is currently active so verification passes now
        # without waiting for the next build_entities.py replay.
        closed = con.execute("""
            UPDATE entity_relationships
               SET valid_to = CURRENT_DATE
             WHERE source = 'ADV_SCHEDULE_A'
               AND parent_entity_id = child_entity_id
               AND valid_to = DATE '9999-12-31'
        """).fetchall()
        # DuckDB's UPDATE doesn't return affected count via fetchall; re-query.
        remaining_active = con.execute("""
            SELECT COUNT(*) FROM entity_relationships
             WHERE source = 'ADV_SCHEDULE_A'
               AND parent_entity_id = child_entity_id
               AND valid_to = DATE '9999-12-31'
        """).fetchone()[0]
        print(f"  immediate close: {remaining_active} active self-loops remaining "
              "(expect 0)")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    after_dm13 = con.execute("""
        SELECT COUNT(*) FROM entity_overrides_persistent
         WHERE reason ILIKE '%DM13-A%'
    """).fetchone()[0]
    print(f"\nAFTER:  inserted={inserted}  skipped={skipped}")
    print(f"AFTER:  overrides={after_ov}  DM13-A overrides={after_dm13}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
