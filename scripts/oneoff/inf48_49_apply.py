"""
INF48 / INF49 — adviser entity dedup (staging).

Two duplicate adviser entities, identical pattern:

  INF48 — NEOS Investment Management
    survivor : eid=20105 "NEOS Investment Management, LLC" (NCEN, with comma)
    duplicate: eid=10825 "NEOS Investment Management LLC"  (managers, no comma)
    distinguishing identifier on dup: cik=0002001019

  INF49 — Segall Bryant & Hamill
    survivor : eid=18157 "Segall Bryant and Hamill LLC"     (NCEN, mixed case)
    duplicate: eid=254   "SEGALL BRYANT & HAMILL, LLC"      (managers, ADV)
    identifiers on dup: cik=0001006378, crd=001006378, crd=106505
    NOTE: dup's crd=001006378 is excluded from transfer (see
    TRANSFER_EXCLUSIONS below) — it is a CIK-misread-as-CRD record
    from cik_crd_direct, numerically identical to the dup's own CIK,
    not a legitimate alternate CRD.

Both duplicates are already dynamically attached to their canonicals via
orphan_scan: an active wholly_owned/orphan_scan parent→child relationship
plus an orphan_scan rollup row in both EC and DM. This pass hardens that
into permanent SCD merged_into rows and writes entity_overrides_persistent
rows so the merge survives a --reset replay.

Per-merge mechanics (mirrors INF23 / INF4 with one addition: identifier
transfer per the user's INF48/49 spec — INSERT on survivor BEFORE close
on duplicate, never break total_aum gate):

  a) Transfer identifiers: for each active identifier on the duplicate,
     INSERT it on the survivor if not already present (same type+value),
     then close it on the duplicate.
  b) Add the duplicate's preferred name as a secondary alias on the
     survivor with alias_type='legal_name'.
  c) Re-point any active relationships where the duplicate is parent or
     child to point at the survivor instead — except for the inverted
     orphan_scan edges that go survivor→duplicate (parent=survivor,
     child=duplicate); close those rather than re-point, otherwise we'd
     create a self-edge on the survivor.
  d) Close the duplicate's active aliases, classification, and rollup
     rows (SCD valid_to = CURRENT_DATE).
  e) Insert merged_into rollup rows on the duplicate (one EC, one DM)
     pointing at the survivor — structural gate per INF4.
  f) Write an entity_overrides_persistent row with action='merge',
     identifier_type/value keyed off the duplicate's CIK,
     new_value=<survivor eid>, reason='INF48/INF49: ...'.

Writes against STAGING ONLY. Promotion is a separate step
(promote_staging.py --approved).

Idempotent: each step checks for already-applied state before mutating.
"""

import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")
ANALYST = "claude-inf48_49"
SENTINEL_OPEN = "DATE '9999-12-31'"

# Identifiers on the duplicate that should NOT transfer to the survivor.
# Closed on the dup as usual but never re-opened on the survivor.
# Keyed as (src_eid, identifier_type, identifier_value).
TRANSFER_EXCLUSIONS = {
    # INF49: padded CRD 001006378 on eid=254 is a CIK-misread-as-CRD
    # record from cik_crd_direct (numerically equal to its own CIK),
    # not a legitimate alternate CRD. Excluded by user direction
    # before promote.
    (254, "crd", "001006378"),
}


def transfer_identifiers(con, src_eid, dst_eid):
    """Step a — INSERT-then-close. Survivor first, then duplicate (per CIK transfer rule)."""
    rows = con.execute(
        """SELECT identifier_type, identifier_value, source
             FROM entity_identifiers
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
            ORDER BY identifier_type, identifier_value""",
        [src_eid],
    ).fetchall()
    for itype, ivalue, isource in rows:
        if (src_eid, itype, ivalue) in TRANSFER_EXCLUSIONS:
            print(f"    {itype}={ivalue}: EXCLUDED from transfer (closing on dup only)")
            con.execute(
                """UPDATE entity_identifiers SET valid_to = CURRENT_DATE
                    WHERE entity_id = ?
                      AND identifier_type = ?
                      AND identifier_value = ?
                      AND valid_to = DATE '9999-12-31'""",
                [src_eid, itype, ivalue],
            )
            continue
        existing = con.execute(
            """SELECT 1 FROM entity_identifiers
                WHERE entity_id = ?
                  AND identifier_type = ?
                  AND identifier_value = ?
                  AND valid_to = DATE '9999-12-31'""",
            [dst_eid, itype, ivalue],
        ).fetchone()
        if existing:
            print(f"    {itype}={ivalue}: already on survivor eid={dst_eid}, just closing on dup")
        else:
            con.execute(
                """INSERT INTO entity_identifiers
                     (entity_id, identifier_type, identifier_value, source,
                      valid_from, valid_to)
                   VALUES (?, ?, ?, ?, CURRENT_DATE, DATE '9999-12-31')""",
                [dst_eid, itype, ivalue, isource],
            )
            print(f"    {itype}={ivalue}: transferred to survivor eid={dst_eid} (source={isource})")
        con.execute(
            """UPDATE entity_identifiers SET valid_to = CURRENT_DATE
                WHERE entity_id = ?
                  AND identifier_type = ?
                  AND identifier_value = ?
                  AND valid_to = DATE '9999-12-31'""",
            [src_eid, itype, ivalue],
        )


def add_legal_name_alias(con, dst_eid, alias_name):
    """Step b — secondary legal_name alias on survivor."""
    existing = con.execute(
        """SELECT 1 FROM entity_aliases
            WHERE entity_id = ?
              AND alias_name = ?
              AND alias_type = 'legal_name'
              AND valid_to = DATE '9999-12-31'""",
        [dst_eid, alias_name],
    ).fetchone()
    if existing:
        print(f"    legal_name alias '{alias_name}' already present on eid={dst_eid}, skipped")
        return
    con.execute(
        """INSERT INTO entity_aliases
             (entity_id, alias_name, alias_type, is_preferred,
              preferred_key, source_table, is_inferred,
              valid_from, valid_to)
           VALUES (?, ?, 'legal_name', FALSE, NULL, 'inf48_49_merge', FALSE,
                   CURRENT_DATE, DATE '9999-12-31')""",
        [dst_eid, alias_name],
    )
    print(f"    legal_name alias '{alias_name}' added on eid={dst_eid}")


def repoint_relationships(con, src_eid, dst_eid):
    """Step c — re-point parent/child; close inverted survivor↔duplicate edges."""
    inverted_parent = con.execute(
        """SELECT relationship_id, relationship_type, source
             FROM entity_relationships
            WHERE parent_entity_id = ?
              AND child_entity_id = ?
              AND valid_to = DATE '9999-12-31'""",
        [dst_eid, src_eid],
    ).fetchall()
    for rel_id, rtype, rsource in inverted_parent:
        con.execute(
            """UPDATE entity_relationships SET valid_to = CURRENT_DATE
                WHERE relationship_id = ?""",
            [rel_id],
        )
        print(f"    closed inverted edge rel_id={rel_id} (parent={dst_eid}→child={src_eid}, "
              f"type={rtype}, source={rsource})")

    inverted_child = con.execute(
        """SELECT relationship_id, relationship_type, source
             FROM entity_relationships
            WHERE parent_entity_id = ?
              AND child_entity_id = ?
              AND valid_to = DATE '9999-12-31'""",
        [src_eid, dst_eid],
    ).fetchall()
    for rel_id, rtype, rsource in inverted_child:
        con.execute(
            """UPDATE entity_relationships SET valid_to = CURRENT_DATE
                WHERE relationship_id = ?""",
            [rel_id],
        )
        print(f"    closed inverted edge rel_id={rel_id} (parent={src_eid}→child={dst_eid}, "
              f"type={rtype}, source={rsource})")

    n_parent = con.execute(
        """SELECT COUNT(*) FROM entity_relationships
            WHERE parent_entity_id = ? AND valid_to = DATE '9999-12-31'""",
        [src_eid],
    ).fetchone()[0]
    if n_parent:
        con.execute(
            """UPDATE entity_relationships SET parent_entity_id = ?
                WHERE parent_entity_id = ? AND valid_to = DATE '9999-12-31'""",
            [dst_eid, src_eid],
        )
        print(f"    re-pointed {n_parent} active edges where dup was parent → survivor")

    n_child = con.execute(
        """SELECT COUNT(*) FROM entity_relationships
            WHERE child_entity_id = ? AND valid_to = DATE '9999-12-31'""",
        [src_eid],
    ).fetchone()[0]
    if n_child:
        con.execute(
            """UPDATE entity_relationships SET child_entity_id = ?
                WHERE child_entity_id = ? AND valid_to = DATE '9999-12-31'""",
            [dst_eid, src_eid],
        )
        print(f"    re-pointed {n_child} active edges where dup was child → survivor")


def close_dup_aliases_class_rollups(con, src_eid):
    """Step d — close active aliases, classification, rollups on duplicate."""
    for tbl in ("entity_aliases", "entity_classification_history", "entity_rollup_history"):
        n = con.execute(
            f"""SELECT COUNT(*) FROM {tbl}
                 WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
            [src_eid],
        ).fetchone()[0]
        con.execute(
            f"""UPDATE {tbl} SET valid_to = CURRENT_DATE
                 WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
            [src_eid],
        )
        print(f"    closed {n} active row(s) in {tbl} on dup eid={src_eid}")


def insert_merged_into_rollups(con, src_eid, dst_eid):
    """Step e — structural gate: dup → survivor in EC + DM with rule_applied='merged_into'."""
    for rt in ("economic_control_v1", "decision_maker_v1"):
        existing = con.execute(
            """SELECT 1 FROM entity_rollup_history
                WHERE entity_id = ? AND rollup_entity_id = ?
                  AND rollup_type = ? AND rule_applied = 'merged_into'
                  AND valid_to = DATE '9999-12-31'""",
            [src_eid, dst_eid, rt],
        ).fetchone()
        if existing:
            print(f"    merged_into rollup already present for eid={src_eid} → {dst_eid} ({rt}), skipped")
            continue
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to)
               VALUES (?, ?, ?, 'merged_into', 'exact',
                       CURRENT_DATE, DATE '9999-12-31')""",
            [src_eid, dst_eid, rt],
        )
        print(f"    inserted merged_into rollup eid={src_eid} → {dst_eid} ({rt})")


def write_override(con, src_eid, dst_eid, dup_cik, label, item_tag):
    """Step f — entity_overrides_persistent merge row keyed on dup CIK."""
    existing = con.execute(
        """SELECT override_id FROM entity_overrides_persistent
            WHERE action = 'merge'
              AND identifier_type = 'cik'
              AND identifier_value = ?
              AND new_value = ?
              AND still_valid = TRUE""",
        [dup_cik, str(dst_eid)],
    ).fetchone()
    if existing:
        print(f"    override_id={existing[0]} already present, skipped")
        return
    new_id = con.execute(
        "SELECT COALESCE(MAX(override_id), 0) + 1 FROM entity_overrides_persistent"
    ).fetchone()[0]
    reason = (
        f"{item_tag}: {label} entity dedup — duplicate adviser "
        f"(eid={src_eid}, CIK {dup_cik}) merged into canonical (eid={dst_eid}). "
        f"Identifiers transferred, dup aliases/classification/rollups closed, "
        f"merged_into SCD rows written for EC + DM."
    )
    con.execute(
        """INSERT INTO entity_overrides_persistent
             (override_id, entity_cik, action, field, old_value,
              new_value, reason, analyst, still_valid,
              identifier_type, identifier_value, rollup_type)
           VALUES (?, NULL, 'merge', NULL, NULL,
                   ?, ?, ?, TRUE, 'cik', ?, 'economic_control_v1')""",
        [new_id, str(dst_eid), reason, ANALYST, dup_cik],
    )
    print(f"    override_id={new_id} inserted (action=merge, cik={dup_cik} → eid={dst_eid})")


def do_merge(con, src_eid, dst_eid, dup_legal_name, dup_cik, label, item_tag):
    print(f"\n--- {item_tag} {label}: eid={src_eid} → eid={dst_eid} ---")
    print("  step a) transfer identifiers")
    transfer_identifiers(con, src_eid, dst_eid)
    print("  step b) add legal_name alias on survivor")
    add_legal_name_alias(con, dst_eid, dup_legal_name)
    print("  step c) re-point relationships (close inverted survivor↔dup edges)")
    repoint_relationships(con, src_eid, dst_eid)
    print("  step d) close dup aliases / classification / rollups")
    close_dup_aliases_class_rollups(con, src_eid)
    print("  step e) insert merged_into rollups (EC + DM)")
    insert_merged_into_rollups(con, src_eid, dst_eid)
    print("  step f) write entity_overrides_persistent row")
    write_override(con, src_eid, dst_eid, dup_cik, label, item_tag)


def snapshot(con, label):
    counts = {
        "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "identifiers_active": con.execute(
            "SELECT COUNT(*) FROM entity_identifiers WHERE valid_to = DATE '9999-12-31'"
        ).fetchone()[0],
        "relationships_active": con.execute(
            "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = DATE '9999-12-31'"
        ).fetchone()[0],
        "rollups_active": con.execute(
            "SELECT COUNT(*) FROM entity_rollup_history WHERE valid_to = DATE '9999-12-31'"
        ).fetchone()[0],
        "rollups_active_ec": con.execute(
            """SELECT COUNT(*) FROM entity_rollup_history
                WHERE valid_to = DATE '9999-12-31' AND rollup_type = 'economic_control_v1'"""
        ).fetchone()[0],
        "rollups_active_dm": con.execute(
            """SELECT COUNT(*) FROM entity_rollup_history
                WHERE valid_to = DATE '9999-12-31' AND rollup_type = 'decision_maker_v1'"""
        ).fetchone()[0],
        "aliases_active": con.execute(
            "SELECT COUNT(*) FROM entity_aliases WHERE valid_to = DATE '9999-12-31'"
        ).fetchone()[0],
        "classifications_active": con.execute(
            "SELECT COUNT(*) FROM entity_classification_history WHERE valid_to = DATE '9999-12-31'"
        ).fetchone()[0],
        "overrides_total": con.execute(
            "SELECT COUNT(*) FROM entity_overrides_persistent"
        ).fetchone()[0],
    }
    print(f"\n{label}: {counts}")
    return counts


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)
    before = snapshot(con, "BEFORE")

    con.execute("BEGIN TRANSACTION")
    try:
        do_merge(
            con,
            src_eid=10825,
            dst_eid=20105,
            dup_legal_name="NEOS Investment Management LLC",
            dup_cik="0002001019",
            label="NEOS Investment Management",
            item_tag="INF48",
        )
        do_merge(
            con,
            src_eid=254,
            dst_eid=18157,
            dup_legal_name="SEGALL BRYANT & HAMILL, LLC",
            dup_cik="0001006378",
            label="Segall Bryant & Hamill",
            item_tag="INF49",
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after = snapshot(con, "AFTER")
    print("\nDeltas:")
    for k in after:
        d = after[k] - before[k]
        if d:
            print(f"  Δ {k}: {d:+}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
