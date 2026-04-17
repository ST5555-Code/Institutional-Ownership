"""
INF23 — entity fragmentation cleanup (staging).

Four items in one transaction:
  1. Milliman Financial Risk Management (eid=18304) CIK backfill.
  2. Morningstar IM merge: eid=19596 (padded CRD) → eid=10513 (canonical,
     CIK 0001673385).
  3. DFA merge: eid=18096 (padded CRD) → eid=5026 (canonical,
     CIK 0000354204).
  4. DM15 NULL-CIK override backfill: 6 Milliman rows (IDs 98-103)
     updated with the newly-backfilled CIK 0001547927.

Smith Capital Investors (eid=18899) CIK backfill is DEFERRED — adv_managers
row has `cik=None`; would require SEC-EDGAR external lookup. DM15 overrides
93-94 remain as NULL-CIK replay gap.

Merge mechanics mirror INF4 pattern:
  - Re-point active entity_relationships from source → survivor
  - Re-point active entity_rollup_history rollup_entity_id source → survivor
  - Close source's aliases, classification, identifier, rollup rows
    (SCD valid_to = CURRENT_DATE)
  - Insert merged_into rollup rows on source (EC + DM) pointing to survivor
    — structural gate per INF4
  - Add secondary alias on survivor (ADV-canonical uppercase form)
  - Add entity_overrides_persistent row with action='merge',
    identifier_type='crd', identifier_value=<padded CRD>,
    new_value=<survivor CIK> for --reset replay safety

Writes against STAGING ONLY.
"""

import os
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")
ANALYST = "claude-inf23"


def do_cik_backfill(con, eid, cik, source, name_for_log):
    """Item 1/4-ish — add entity_identifiers(type='cik') row."""
    existing = con.execute(
        """SELECT 1 FROM entity_identifiers
           WHERE entity_id=? AND identifier_type='cik' AND valid_to=DATE '9999-12-31'""",
        [eid],
    ).fetchone()
    if existing:
        print(f"  SKIP  eid={eid} ({name_for_log}): already has active CIK")
        return
    con.execute(
        """INSERT INTO entity_identifiers
             (entity_id, identifier_type, identifier_value, source,
              valid_from, valid_to)
           VALUES (?, 'cik', ?, ?, CURRENT_DATE, DATE '9999-12-31')""",
        [eid, cik, source],
    )
    print(f"  DONE  eid={eid} ({name_for_log}): CIK {cik} added (source={source})")


def do_merge(con, src_eid, dst_eid, src_crd_padded, dst_cik,
             survivor_alias_uppercase, label):
    """Items 2-3 — merge src → dst per INF4 pattern."""
    print(f"\n--- MERGE {label}: eid={src_eid} → eid={dst_eid} ---")

    # Counts before
    n_rels_parent = con.execute(
        """SELECT COUNT(*) FROM entity_relationships
            WHERE parent_entity_id=? AND valid_to=DATE '9999-12-31'""",
        [src_eid],
    ).fetchone()[0]
    n_rels_child = con.execute(
        """SELECT COUNT(*) FROM entity_relationships
            WHERE child_entity_id=? AND valid_to=DATE '9999-12-31'""",
        [src_eid],
    ).fetchone()[0]
    n_rollups_target = con.execute(
        """SELECT COUNT(*) FROM entity_rollup_history
            WHERE rollup_entity_id=? AND valid_to=DATE '9999-12-31'""",
        [src_eid],
    ).fetchone()[0]
    print(f"  before: as_parent={n_rels_parent} as_child={n_rels_child} "
          f"rollup_target={n_rollups_target}")

    # Re-point relationships where source is parent — skip inverted
    # orphan_scan edges that go src → dst (these are the bad "fragmented
    # owns canonical" edges; close rather than re-point, else we create
    # self-edges on the survivor).
    inverted_rows = con.execute(
        """SELECT relationship_id FROM entity_relationships
            WHERE parent_entity_id=? AND child_entity_id=?
              AND valid_to=DATE '9999-12-31'""",
        [src_eid, dst_eid],
    ).fetchall()
    for (rel_id,) in inverted_rows:
        con.execute(
            """UPDATE entity_relationships SET valid_to=CURRENT_DATE
                WHERE relationship_id=?""",
            [rel_id],
        )
        print(f"  closed inverted src→dst edge rel_id={rel_id}")

    # Re-point remaining relationships where source is parent
    n_re_parent = con.execute(
        """UPDATE entity_relationships SET parent_entity_id=?
            WHERE parent_entity_id=? AND valid_to=DATE '9999-12-31'""",
        [dst_eid, src_eid],
    ).fetchone()
    # Re-point remaining where source is child (also close inverted dst→src
    # orphan_scan edges first to avoid self-edge).
    inverted_child_rows = con.execute(
        """SELECT relationship_id FROM entity_relationships
            WHERE parent_entity_id=? AND child_entity_id=?
              AND valid_to=DATE '9999-12-31'""",
        [dst_eid, src_eid],
    ).fetchall()
    for (rel_id,) in inverted_child_rows:
        con.execute(
            """UPDATE entity_relationships SET valid_to=CURRENT_DATE
                WHERE relationship_id=?""",
            [rel_id],
        )
        print(f"  closed inverted dst→src edge rel_id={rel_id}")
    con.execute(
        """UPDATE entity_relationships SET child_entity_id=?
            WHERE child_entity_id=? AND valid_to=DATE '9999-12-31'""",
        [dst_eid, src_eid],
    )

    # Re-point rollup history: rollup_entity_id source → survivor
    con.execute(
        """UPDATE entity_rollup_history SET rollup_entity_id=?
            WHERE rollup_entity_id=? AND valid_to=DATE '9999-12-31'""",
        [dst_eid, src_eid],
    )

    # Close source's own active rows (aliases, classification, identifier,
    # rollup_history as entity_id)
    for tbl in (
        "entity_aliases",
        "entity_classification_history",
        "entity_identifiers",
        "entity_rollup_history",
    ):
        con.execute(
            f"""UPDATE {tbl} SET valid_to=CURRENT_DATE
                WHERE entity_id=? AND valid_to=DATE '9999-12-31'""",
            [src_eid],
        )

    # Insert merged_into rollup rows on source (EC + DM) pointing to
    # survivor — structural gate so source reads as "merged" under both
    # worldviews.
    for rt in ("economic_control_v1", "decision_maker_v1"):
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to)
               VALUES (?, ?, ?, 'merged_into', 'exact',
                       CURRENT_DATE, DATE '9999-12-31')""",
            [src_eid, dst_eid, rt],
        )

    # Secondary alias on survivor (ADV-canonical uppercase form)
    existing_alias = con.execute(
        """SELECT 1 FROM entity_aliases
           WHERE entity_id=? AND alias_name=? AND valid_to=DATE '9999-12-31'""",
        [dst_eid, survivor_alias_uppercase],
    ).fetchone()
    if not existing_alias:
        con.execute(
            """INSERT INTO entity_aliases
                 (entity_id, alias_name, alias_type, is_preferred,
                  preferred_key, source_table, is_inferred,
                  valid_from, valid_to)
               VALUES (?, ?, 'brand', FALSE, NULL, 'inf23_merge', FALSE,
                       CURRENT_DATE, DATE '9999-12-31')""",
            [dst_eid, survivor_alias_uppercase],
        )
        print(f"  secondary alias added on eid={dst_eid}: '{survivor_alias_uppercase}'")

    # Persistent override for --reset replay safety
    reason = (
        f"INF23: {label} fragmentation merge — padded-CRD entity "
        f"(eid={src_eid}, CRD {src_crd_padded}) merged into canonical "
        f"(eid={dst_eid}, CIK {dst_cik}). CRD format normalization per INF4b."
    )
    existing_override = con.execute(
        """SELECT override_id FROM entity_overrides_persistent
            WHERE action='merge'
              AND identifier_type='crd'
              AND identifier_value=?
              AND new_value=?
              AND still_valid=TRUE""",
        [src_crd_padded, dst_cik],
    ).fetchone()
    if existing_override:
        print(f"  override_id={existing_override[0]} already present — skipped")
    else:
        new_id = con.execute(
            "SELECT COALESCE(MAX(override_id), 0) + 1 "
            "FROM entity_overrides_persistent"
        ).fetchone()[0]
        con.execute(
            """INSERT INTO entity_overrides_persistent
                 (override_id, entity_cik, action, field, old_value,
                  new_value, reason, analyst, still_valid,
                  identifier_type, identifier_value, rollup_type)
               VALUES (?, NULL, 'merge', NULL, NULL,
                       ?, ?, ?, TRUE, 'crd', ?, 'economic_control_v1')""",
            [new_id, dst_cik, reason, ANALYST, src_crd_padded],
        )
        print(f"  override_id={new_id} inserted (crd={src_crd_padded} → cik={dst_cik})")


def do_dm15_override_backfill(con, override_ids, new_cik):
    """Item 4 — UPDATE NULL new_value with now-available CIK."""
    updated = 0
    for oid in override_ids:
        row = con.execute(
            """SELECT new_value FROM entity_overrides_persistent
                WHERE override_id=?""",
            [oid],
        ).fetchone()
        if row is None:
            print(f"  override_id={oid} NOT FOUND — skipping")
            continue
        if row[0] is not None:
            print(f"  override_id={oid} new_value already set to {row[0]} — skipping")
            continue
        con.execute(
            """UPDATE entity_overrides_persistent SET new_value=?
                WHERE override_id=?""",
            [new_cik, oid],
        )
        updated += 1
    print(f"  backfilled {updated} / {len(override_ids)} overrides with new_value={new_cik}")


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    baseline = {
        "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "identifiers": con.execute("SELECT COUNT(*) FROM entity_identifiers WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "relationships_active": con.execute("SELECT COUNT(*) FROM entity_relationships WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "rollups_active": con.execute("SELECT COUNT(*) FROM entity_rollup_history WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "aliases_active": con.execute("SELECT COUNT(*) FROM entity_aliases WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "overrides": con.execute("SELECT COUNT(*) FROM entity_overrides_persistent").fetchone()[0],
    }
    print("BEFORE:", baseline)

    con.execute("BEGIN TRANSACTION")
    try:
        print("\n### Step 1 — Milliman CIK backfill ###")
        do_cik_backfill(con, 18304, "0001547927", "adv_managers",
                        "Milliman Financial Risk Management LLC")

        print("\n### Step 2 — Morningstar merge (19596 → 10513) ###")
        do_merge(con, 19596, 10513,
                 src_crd_padded="000108031",
                 dst_cik="0001673385",
                 survivor_alias_uppercase="MORNINGSTAR INVESTMENT MANAGEMENT LLC",
                 label="Morningstar")

        print("\n### Step 3 — DFA merge (18096 → 5026) ###")
        do_merge(con, 18096, 5026,
                 src_crd_padded="000106482",
                 dst_cik="0000354204",
                 survivor_alias_uppercase="DIMENSIONAL FUND ADVISORS LP",
                 label="DFA")

        print("\n### Step 4 — DM15 override new_value backfill (Milliman rows 98-103) ###")
        do_dm15_override_backfill(con,
                                   override_ids=[98, 99, 100, 101, 102, 103],
                                   new_cik="0001547927")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after = {
        "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "identifiers": con.execute("SELECT COUNT(*) FROM entity_identifiers WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "relationships_active": con.execute("SELECT COUNT(*) FROM entity_relationships WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "rollups_active": con.execute("SELECT COUNT(*) FROM entity_rollup_history WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "aliases_active": con.execute("SELECT COUNT(*) FROM entity_aliases WHERE valid_to=DATE '9999-12-31'").fetchone()[0],
        "overrides": con.execute("SELECT COUNT(*) FROM entity_overrides_persistent").fetchone()[0],
    }
    print("\nAFTER:", after)
    for k in after:
        delta = after[k] - baseline[k]
        if delta:
            print(f"  Δ {k}: {delta:+}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
