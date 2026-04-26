"""
DM13-B/C — suppress 107 non-operating/redundant ADV_SCHEDULE_A rollup edges.

Categories B (AUM-inverted / consolidator) and C (non-operating parent /
graph noise) of the DM13 cleanup. The triage source is
data/reports/dm13_bc_triage.csv (214 rows, 107 SUPPRESS / 107 ACCEPT). The
ACCEPT set is left untouched; only the 107 SUPPRESS rows are closed here.

Of the 107 SUPPRESS rows:
  - 78 currently_drives_rollup=True (closing changes AUM totals)
  - 29 currently_drives_rollup=False (graph noise, no AUM change)
All 107 are still active in entity_relationships at run time.

Action per row: write one suppress_relationship override into
entity_overrides_persistent (so any future build_entities.py --reset
re-introducing the edge will close it again), then UPDATE the active row
to valid_to=CURRENT_DATE. Mirrors the DM13-A pattern.

Writes against STAGING ONLY. Promotion is a separate step
(promote_staging.py --approved).

Idempotent: re-running skips rows where an override with matching reason +
relationship_id already exists.

Verification (post-promote):
  - SELECT COUNT(*) FROM entity_relationships
    WHERE relationship_id IN (107 ids)
      AND valid_to=DATE '9999-12-31'   -- expect 0
  - SELECT COUNT(*) FROM entity_overrides_persistent
    WHERE reason ILIKE '%DM13-B/C%'    -- expect 107
"""

import csv
import json
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")
TRIAGE_CSV = os.path.join(ROOT, "data", "reports", "dm13_bc_triage.csv")
ANALYST = "claude-dm13bc"
REASON = "DM13-B/C: non-operating/redundant ADV_SCHEDULE_A rollup edge"


def _load_suppress_ids() -> list[int]:
    if not os.path.exists(TRIAGE_CSV):
        raise FileNotFoundError(f"triage CSV missing: {TRIAGE_CSV}")
    ids: list[int] = []
    with open(TRIAGE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["suggested_action"] == "SUPPRESS":
                ids.append(int(row["relationship_id"]))
    return ids


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    suppress_ids = _load_suppress_ids()
    if len(suppress_ids) != 107:
        print(
            f"FATAL: expected 107 SUPPRESS rows, found {len(suppress_ids)}",
            file=sys.stderr,
        )
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    placeholders = ",".join("?" * len(suppress_ids))
    rows = con.execute(
        f"""
        SELECT er.relationship_id,
               er.parent_entity_id,
               er.child_entity_id,
               er.relationship_type,
               (SELECT MIN(ei.identifier_value)
                  FROM entity_identifiers ei
                 WHERE ei.entity_id = er.parent_entity_id
                   AND ei.identifier_type = 'cik'
                   AND ei.valid_to = DATE '9999-12-31') AS parent_cik,
               (SELECT MIN(ei.identifier_value)
                  FROM entity_identifiers ei
                 WHERE ei.entity_id = er.child_entity_id
                   AND ei.identifier_type = 'cik'
                   AND ei.valid_to = DATE '9999-12-31') AS child_cik
          FROM entity_relationships er
         WHERE er.relationship_id IN ({placeholders})
         ORDER BY er.relationship_id
        """,
        suppress_ids,
    ).fetchall()
    print(f"BEFORE: {len(rows)} target relationships found in staging")
    if len(rows) != 107:
        print(
            f"FATAL: expected 107 rows in DB, found {len(rows)}",
            file=sys.stderr,
        )
        con.close()
        return 2

    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    baseline_active = con.execute(
        f"""
        SELECT COUNT(*) FROM entity_relationships
         WHERE relationship_id IN ({placeholders})
           AND valid_to = DATE '9999-12-31'
        """,
        suppress_ids,
    ).fetchone()[0]
    print(f"BEFORE: overrides={baseline_ov}  active SUPPRESS rows={baseline_active}")

    con.execute("BEGIN TRANSACTION")
    inserted = 0
    skipped = 0
    try:
        for rel_id, parent_eid, child_eid, rel_type, parent_cik, child_cik in rows:
            existing = con.execute(
                """
                SELECT override_id FROM entity_overrides_persistent
                 WHERE action = 'suppress_relationship'
                   AND reason = ?
                   AND old_value = ?
                   AND still_valid = TRUE
                """,
                [REASON, str(rel_id)],
            ).fetchone()
            if existing:
                skipped += 1
                continue

            ctx = {
                "parent_entity_id": int(parent_eid),
                "child_entity_id": int(child_eid),
                "relationship_type": rel_type,
            }
            if parent_cik is not None:
                ctx["parent_cik"] = parent_cik
            if child_cik is not None:
                ctx["child_cik"] = child_cik

            new_id = con.execute(
                "SELECT COALESCE(MAX(override_id), 0) + 1 "
                "FROM entity_overrides_persistent"
            ).fetchone()[0]
            con.execute(
                """
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
                """,
                [new_id, str(rel_id), REASON, ANALYST, json.dumps(ctx)],
            )
            inserted += 1

        con.execute(
            f"""
            UPDATE entity_relationships
               SET valid_to = CURRENT_DATE
             WHERE relationship_id IN ({placeholders})
               AND valid_to = DATE '9999-12-31'
            """,
            suppress_ids,
        )
        remaining_active = con.execute(
            f"""
            SELECT COUNT(*) FROM entity_relationships
             WHERE relationship_id IN ({placeholders})
               AND valid_to = DATE '9999-12-31'
            """,
            suppress_ids,
        ).fetchone()[0]
        print(
            f"  immediate close: {remaining_active} active SUPPRESS rows remaining "
            "(expect 0)"
        )

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    after_dm13bc = con.execute(
        """
        SELECT COUNT(*) FROM entity_overrides_persistent
         WHERE reason ILIKE '%DM13-B/C%'
        """
    ).fetchone()[0]
    print(f"\nAFTER:  inserted={inserted}  skipped={skipped}")
    print(f"AFTER:  overrides={after_ov}  DM13-B/C overrides={after_dm13bc}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
