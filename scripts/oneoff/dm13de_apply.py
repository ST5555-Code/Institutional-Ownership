"""
DM13-D/E — suppress 559 dormant/residual ADV_SCHEDULE_A rollup edges.

Categories D (dormant, both endpoints zero 13F AUM at refresh) and E
(residual non-operating parent that escaped DM13-B/C). Triage source is
data/reports/dm13_de_triage.csv (671 rows, 558 SUPPRESS / 113 ACCEPT in
the file). One row is reclassified at apply time:

  relationship_id 11694 (Natixis Investment Managers SA →
  VAUGHAN NELSON INVESTMENT MANAGEMENT, L.P.) is reassigned ACCEPT → SUPPRESS
  with the rationale "Suppressed to eliminate double-count; Vaughan Nelson
  consolidated under Natixis IM LLC (US operating entity)."

Final apply set: 559 SUPPRESS / 112 ACCEPT. The ACCEPT set is left
untouched. All 559 SUPPRESS rows are still active in entity_relationships
at run time (verified disjoint from the DM13-B/C SUPPRESS set).

Per row: write one suppress_relationship override into
entity_overrides_persistent with reason = "DM13-D/E: " + the CSV
rationale (truncated to 200 chars), then UPDATE the active row to
valid_to=CURRENT_DATE. Mirrors dm13bc_apply.py except the reason is
per-row (varies with the rationale) instead of a single constant.

Writes against STAGING ONLY. Promotion is a separate step
(promote_staging.py --approved).

Idempotent: re-running skips rows where a suppress_relationship override
with reason starting "DM13-D/E:" already exists for that relationship_id.

Verification (post-promote):
  - SELECT COUNT(*) FROM entity_relationships
    WHERE relationship_id IN (559 ids)
      AND valid_to = DATE '9999-12-31'      -- expect 0
  - SELECT COUNT(*) FROM entity_overrides_persistent
    WHERE reason ILIKE 'DM13-D/E:%'         -- expect 559
  - 112 ACCEPT relationship_ids still have valid_to = DATE '9999-12-31'
"""

import csv
import json
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")
TRIAGE_CSV = os.path.join(ROOT, "data", "reports", "dm13_de_triage.csv")
ANALYST = "claude-dm13de"
REASON_PREFIX = "DM13-D/E: "
REASON_MAX_LEN = 200

# 11694 was originally tagged ACCEPT in the CSV; reclassify to SUPPRESS at
# apply time per the operator decision (Vaughan Nelson is consolidated
# under Natixis IM LLC, the US operating entity, so the SA-side edge is a
# double-count).
RECLASSIFY = {
    11694: (
        "Suppressed to eliminate double-count; Vaughan Nelson consolidated "
        "under Natixis IM LLC (US operating entity)."
    ),
}


def _load_decisions() -> tuple[list[tuple[int, str]], list[int]]:
    """Return (suppress_rows, accept_ids) after applying RECLASSIFY."""
    if not os.path.exists(TRIAGE_CSV):
        raise FileNotFoundError(f"triage CSV missing: {TRIAGE_CSV}")
    suppress: list[tuple[int, str]] = []
    accept: list[int] = []
    with open(TRIAGE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = int(row["relationship_id"])
            if rid in RECLASSIFY:
                suppress.append((rid, RECLASSIFY[rid]))
                continue
            if row["suggested_action"] == "SUPPRESS":
                suppress.append((rid, row["rationale"]))
            elif row["suggested_action"] == "ACCEPT":
                accept.append(rid)
    return suppress, accept


def _build_reason(rationale: str) -> str:
    return (REASON_PREFIX + rationale)[:REASON_MAX_LEN]


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    suppress_rows, accept_ids = _load_decisions()
    if len(suppress_rows) != 559:
        print(
            f"FATAL: expected 559 SUPPRESS rows after reclassify, "
            f"found {len(suppress_rows)}",
            file=sys.stderr,
        )
        return 2
    if len(accept_ids) != 112:
        print(
            f"FATAL: expected 112 ACCEPT rows after reclassify, "
            f"found {len(accept_ids)}",
            file=sys.stderr,
        )
        return 2

    suppress_ids = [rid for rid, _ in suppress_rows]
    rationale_by_id = dict(suppress_rows)

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
    if len(rows) != 559:
        print(
            f"FATAL: expected 559 rows in DB, found {len(rows)}",
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
                   AND old_value = ?
                   AND reason LIKE 'DM13-D/E:%'
                   AND still_valid = TRUE
                """,
                [str(rel_id)],
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

            reason = _build_reason(rationale_by_id[rel_id])

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
                [new_id, str(rel_id), reason, ANALYST, json.dumps(ctx)],
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

        # Sanity: ACCEPT rows must be untouched.
        accept_ph = ",".join("?" * len(accept_ids))
        accept_active = con.execute(
            f"""
            SELECT COUNT(*) FROM entity_relationships
             WHERE relationship_id IN ({accept_ph})
               AND valid_to = DATE '9999-12-31'
            """,
            accept_ids,
        ).fetchone()[0]
        print(
            f"  ACCEPT untouched: {accept_active} of {len(accept_ids)} still active "
            "(expect 112)"
        )
        if accept_active != len(accept_ids):
            raise RuntimeError(
                f"ACCEPT invariant broken: expected {len(accept_ids)} active, "
                f"got {accept_active}"
            )

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    after_dm13de = con.execute(
        """
        SELECT COUNT(*) FROM entity_overrides_persistent
         WHERE reason LIKE 'DM13-D/E:%'
        """
    ).fetchone()[0]
    print(f"\nAFTER:  inserted={inserted}  skipped={skipped}")
    print(f"AFTER:  overrides={after_ov}  DM13-D/E overrides={after_dm13de}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
