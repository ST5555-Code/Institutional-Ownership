"""
calamos-merge-tier4-classify — two coordinated entity-table edits, one PR.

Writes against PROD (not staging). Pre-write backup is the operator's
responsibility (see commit message); the script bails if the backup
sentinel arg is missing on --confirm.

A) Calamos eid 20207 → 20206 merge (Tier 4 follow-up).
   Pattern follows INF48/49 (`scripts/oneoff/inf48_49_apply.py`) with
   one simplification: the duplicate (20207) is already orphaned by
   `dera-synthetic-tier4` — 0 open identifiers, 0 holdings rows, an
   identical-text brand alias, active classification, EC+DM rollups
   to sponsor 8553, and a parallel sponsor relationship 16134 that
   shadows the survivor's 16133. Identifier transfer is a no-op; the
   parallel sponsor edge gets closed (not re-pointed) to avoid creating
   a duplicate (8553→20206) row.

B) Tier 4 classification sweep — keyword-based active/passive labels
   over the 657 `created_source='bootstrap_tier4'` entities that all
   have an open `classification='unknown'` row. For each matched
   entity: close the 'unknown' row at CURRENT_DATE, insert a new row
   (active|passive) at CURRENT_DATE with source='tier4_keyword_sweep'.

   Keywords (per spec):
     PASSIVE: SPDR, iShares, Vanguard, ETF, Index
     ACTIVE : Closed-End, CEF, Interval, Municipal, BDC,
              Business Development, Income Fund

   Discovery on prod (read-only, this session) showed 230 matches
   (1 passive "Index", 229 active); 0 ambiguous (no overlap); 427
   unmatched stay 'unknown' per spec.

Usage:
    python -m scripts.oneoff.calamos_merge_tier4_classify_apply --dry-run
    python -m scripts.oneoff.calamos_merge_tier4_classify_apply --confirm

Idempotent: each step checks for already-applied state.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PROD_DB = os.path.join(ROOT, "data", "13f.duckdb")

ANALYST = "claude-calamos-merge-tier4-classify"
SENTINEL_OPEN_LITERAL = "DATE '9999-12-31'"

# --- Calamos merge constants ---------------------------------------------
CAL_DUP_EID = 20207
CAL_SURV_EID = 20206
CAL_DUP_NAME = "CALAMOS GLOBAL TOTAL RETURN FUND"  # identical to survivor name
CAL_CIK = "0001285650"

# --- Tier 4 classification keywords --------------------------------------
PASSIVE_KEYWORDS: list[tuple[str, str]] = [
    ("SPDR", r"\bSPDR\b"),
    ("iShares", r"\biShares\b"),
    ("Vanguard", r"\bVanguard\b"),
    ("ETF", r"\bETF\b"),
    ("Index", r"\bIndex\b"),
]
ACTIVE_KEYWORDS: list[tuple[str, str]] = [
    ("Closed-End", r"\bClosed[-\s]End\b"),
    ("CEF", r"\bCEF\b"),
    ("Interval", r"\bInterval\b"),
    ("Municipal", r"\bMunicipal\b"),
    ("Business Development", r"\bBusiness\s+Development\b"),
    ("BDC", r"\bBDC\b"),
    ("Income Fund", r"\bIncome\s+Fund\b"),
]
SWEEP_SOURCE = "tier4_keyword_sweep"


# =========================================================================
# A) Calamos merge
# =========================================================================
def calamos_transfer_identifiers(con) -> None:
    rows = con.execute(
        f"""SELECT identifier_type, identifier_value, source
              FROM entity_identifiers
             WHERE entity_id = ? AND valid_to = {SENTINEL_OPEN_LITERAL}""",
        [CAL_DUP_EID],
    ).fetchall()
    if not rows:
        print("    (a) transfer: 0 open identifiers on dup — no-op")
        return
    for itype, ivalue, isource in rows:
        existing = con.execute(
            f"""SELECT 1 FROM entity_identifiers
                 WHERE entity_id = ?
                   AND identifier_type = ?
                   AND identifier_value = ?
                   AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [CAL_SURV_EID, itype, ivalue],
        ).fetchone()
        if not existing:
            con.execute(
                f"""INSERT INTO entity_identifiers
                      (entity_id, identifier_type, identifier_value,
                       confidence, source, is_inferred, valid_from, valid_to)
                    VALUES (?, ?, ?, 'exact', ?, FALSE,
                            CURRENT_DATE, {SENTINEL_OPEN_LITERAL})""",
                [CAL_SURV_EID, itype, ivalue, isource],
            )
            print(f"    (a) {itype}={ivalue}: transferred to survivor")
        else:
            print(f"    (a) {itype}={ivalue}: already on survivor — close-only on dup")
        con.execute(
            f"""UPDATE entity_identifiers SET valid_to = CURRENT_DATE
                 WHERE entity_id = ?
                   AND identifier_type = ?
                   AND identifier_value = ?
                   AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [CAL_DUP_EID, itype, ivalue],
        )


def calamos_add_legal_name_alias(con) -> None:
    existing = con.execute(
        f"""SELECT 1 FROM entity_aliases
             WHERE entity_id = ?
               AND alias_name = ?
               AND alias_type = 'legal_name'
               AND valid_to = {SENTINEL_OPEN_LITERAL}""",
        [CAL_SURV_EID, CAL_DUP_NAME],
    ).fetchone()
    if existing:
        print(f"    (b) legal_name alias '{CAL_DUP_NAME}' already on survivor — skipped")
        return
    con.execute(
        f"""INSERT INTO entity_aliases
              (entity_id, alias_name, alias_type, is_preferred,
               preferred_key, source_table, is_inferred,
               valid_from, valid_to)
            VALUES (?, ?, 'legal_name', FALSE, NULL, 'calamos_merge', FALSE,
                    CURRENT_DATE, {SENTINEL_OPEN_LITERAL})""",
        [CAL_SURV_EID, CAL_DUP_NAME],
    )
    print(f"    (b) legal_name alias '{CAL_DUP_NAME}' added on survivor")


def calamos_close_redundant_relationship(con) -> None:
    """The dup carries a parallel sponsor edge (8553→20207) that shadows
    the survivor's existing 8553→20206 edge. Close it as redundant; do
    not re-point (would create duplicate). Any non-parallel edges where
    the dup is parent or child get re-pointed."""
    parent_rows = con.execute(
        f"""SELECT relationship_id, parent_entity_id, relationship_type, source
              FROM entity_relationships
             WHERE child_entity_id = ?
               AND valid_to = {SENTINEL_OPEN_LITERAL}""",
        [CAL_DUP_EID],
    ).fetchall()
    for rel_id, parent, rtype, rsource in parent_rows:
        twin = con.execute(
            f"""SELECT 1 FROM entity_relationships
                 WHERE parent_entity_id = ?
                   AND child_entity_id = ?
                   AND relationship_type = ?
                   AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [parent, CAL_SURV_EID, rtype],
        ).fetchone()
        if twin:
            con.execute(
                "UPDATE entity_relationships SET valid_to = CURRENT_DATE "
                "WHERE relationship_id = ?",
                [rel_id],
            )
            print(f"    (c) closed redundant edge rel_id={rel_id} "
                  f"({parent}→{CAL_DUP_EID}, type={rtype}) — twin exists on survivor")
        else:
            con.execute(
                "UPDATE entity_relationships SET child_entity_id = ? "
                "WHERE relationship_id = ?",
                [CAL_SURV_EID, rel_id],
            )
            print(f"    (c) re-pointed edge rel_id={rel_id} "
                  f"({parent}→{CAL_DUP_EID}) → child={CAL_SURV_EID}")

    child_rows = con.execute(
        f"""SELECT relationship_id, child_entity_id, relationship_type, source
              FROM entity_relationships
             WHERE parent_entity_id = ?
               AND valid_to = {SENTINEL_OPEN_LITERAL}""",
        [CAL_DUP_EID],
    ).fetchall()
    for rel_id, child, rtype, rsource in child_rows:
        twin = con.execute(
            f"""SELECT 1 FROM entity_relationships
                 WHERE parent_entity_id = ?
                   AND child_entity_id = ?
                   AND relationship_type = ?
                   AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [CAL_SURV_EID, child, rtype],
        ).fetchone()
        if twin:
            con.execute(
                "UPDATE entity_relationships SET valid_to = CURRENT_DATE "
                "WHERE relationship_id = ?",
                [rel_id],
            )
            print(f"    (c) closed redundant edge rel_id={rel_id} "
                  f"({CAL_DUP_EID}→{child}, type={rtype}) — twin exists on survivor")
        else:
            con.execute(
                "UPDATE entity_relationships SET parent_entity_id = ? "
                "WHERE relationship_id = ?",
                [CAL_SURV_EID, rel_id],
            )
            print(f"    (c) re-pointed edge rel_id={rel_id} "
                  f"({CAL_DUP_EID}→{child}) → parent={CAL_SURV_EID}")


def calamos_close_dup_aliases_class_rollups(con) -> None:
    for tbl in ("entity_aliases", "entity_classification_history", "entity_rollup_history"):
        n = con.execute(
            f"""SELECT COUNT(*) FROM {tbl}
                 WHERE entity_id = ? AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [CAL_DUP_EID],
        ).fetchone()[0]
        con.execute(
            f"""UPDATE {tbl} SET valid_to = CURRENT_DATE
                 WHERE entity_id = ? AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [CAL_DUP_EID],
        )
        print(f"    (d) closed {n} active row(s) in {tbl} on dup eid={CAL_DUP_EID}")


def calamos_insert_merged_into_rollups(con) -> None:
    for rt in ("economic_control_v1", "decision_maker_v1"):
        existing = con.execute(
            f"""SELECT 1 FROM entity_rollup_history
                 WHERE entity_id = ?
                   AND rollup_entity_id = ?
                   AND rollup_type = ?
                   AND rule_applied = 'merged_into'
                   AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [CAL_DUP_EID, CAL_SURV_EID, rt],
        ).fetchone()
        if existing:
            print(f"    (e) merged_into rollup already present ({rt}) — skipped")
            continue
        con.execute(
            f"""INSERT INTO entity_rollup_history
                  (entity_id, rollup_entity_id, rollup_type, rule_applied,
                   confidence, valid_from, valid_to)
                VALUES (?, ?, ?, 'merged_into', 'exact',
                        CURRENT_DATE, {SENTINEL_OPEN_LITERAL})""",
            [CAL_DUP_EID, CAL_SURV_EID, rt],
        )
        print(f"    (e) inserted merged_into rollup eid={CAL_DUP_EID} → {CAL_SURV_EID} ({rt})")


def calamos_write_override(con) -> None:
    existing = con.execute(
        """SELECT override_id FROM entity_overrides_persistent
            WHERE action = 'merge'
              AND identifier_type = 'cik'
              AND identifier_value = ?
              AND new_value = ?
              AND still_valid = TRUE""",
        [CAL_CIK, str(CAL_SURV_EID)],
    ).fetchone()
    if existing:
        print(f"    (f) override_id={existing[0]} already present — skipped")
        return
    new_id = con.execute(
        "SELECT COALESCE(MAX(override_id), 0) + 1 FROM entity_overrides_persistent"
    ).fetchone()[0]
    reason = (
        "Calamos eid 20207 merge into 20206 (Tier 4 follow-up). "
        "Duplicate fund eid for CIK 0001285650 left orphaned by "
        "dera-synthetic-tier4 (0 holdings, 0 open identifiers); "
        "rollups + classification + alias closed on dup, merged_into "
        "rollups written for EC + DM, parallel sponsor edge closed."
    )
    con.execute(
        """INSERT INTO entity_overrides_persistent
              (override_id, entity_cik, action, field, old_value,
               new_value, reason, analyst, still_valid,
               identifier_type, identifier_value, rollup_type)
            VALUES (?, NULL, 'merge', NULL, NULL,
                    ?, ?, ?, TRUE, 'cik', ?, 'economic_control_v1')""",
        [new_id, str(CAL_SURV_EID), reason, ANALYST, CAL_CIK],
    )
    print(f"    (f) override_id={new_id} inserted "
          f"(merge cik={CAL_CIK} → eid={CAL_SURV_EID})")


def do_calamos_merge(con) -> None:
    print(f"\n--- TASK A: Calamos merge eid={CAL_DUP_EID} → eid={CAL_SURV_EID} ---")
    calamos_transfer_identifiers(con)
    calamos_add_legal_name_alias(con)
    calamos_close_redundant_relationship(con)
    calamos_close_dup_aliases_class_rollups(con)
    calamos_insert_merged_into_rollups(con)
    calamos_write_override(con)


# =========================================================================
# B) Tier 4 classification sweep
# =========================================================================
def classify_name(name: str) -> str | None:
    """Return 'passive' / 'active' / None per the keyword spec.
    Passive and active keyword sets are disjoint; 0 ambiguity in the
    Tier 4 cohort (verified read-only)."""
    if not name:
        return None
    p = any(re.search(pat, name, re.I) for _, pat in PASSIVE_KEYWORDS)
    a = any(re.search(pat, name, re.I) for _, pat in ACTIVE_KEYWORDS)
    if p and a:
        return None  # ambiguous → leave unknown
    if p:
        return "passive"
    if a:
        return "active"
    return None


def tier4_classify_sweep(con, *, dry_run: bool) -> None:
    rows = con.execute(
        f"""SELECT e.entity_id, e.canonical_name
              FROM entities e
              JOIN entity_classification_history h
                ON h.entity_id = e.entity_id
             WHERE e.created_source = 'bootstrap_tier4'
               AND h.classification = 'unknown'
               AND h.source = 'bootstrap_tier4'
               AND h.valid_to = {SENTINEL_OPEN_LITERAL}
             ORDER BY e.entity_id"""
    ).fetchall()
    print(f"\n--- TASK B: Tier 4 classification sweep ({len(rows)} candidates) ---")

    n_passive = n_active = n_unknown = 0
    for eid, name in rows:
        cls = classify_name(name)
        if cls is None:
            n_unknown += 1
            continue
        if cls == "passive":
            n_passive += 1
        else:
            n_active += 1
        if dry_run:
            continue

        # Close the existing open 'unknown' row at CURRENT_DATE; open a
        # new (cls) row at CURRENT_DATE with source='tier4_keyword_sweep'.
        con.execute(
            f"""UPDATE entity_classification_history
                   SET valid_to = CURRENT_DATE
                 WHERE entity_id = ?
                   AND classification = 'unknown'
                   AND source = 'bootstrap_tier4'
                   AND valid_to = {SENTINEL_OPEN_LITERAL}""",
            [eid],
        )
        con.execute(
            f"""INSERT INTO entity_classification_history
                  (entity_id, classification, is_activist, confidence,
                   source, is_inferred, valid_from, valid_to)
                VALUES (?, ?, FALSE, 'exact', ?, FALSE,
                        CURRENT_DATE, {SENTINEL_OPEN_LITERAL})""",
            [eid, cls, SWEEP_SOURCE],
        )
    print(f"    classified passive: {n_passive}")
    print(f"    classified active : {n_active}")
    print(f"    left unknown      : {n_unknown}")


# =========================================================================
# Snapshot + main
# =========================================================================
def snapshot(con, label: str) -> dict:
    counts = {
        "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "identifiers_active": con.execute(
            f"SELECT COUNT(*) FROM entity_identifiers WHERE valid_to = {SENTINEL_OPEN_LITERAL}"
        ).fetchone()[0],
        "relationships_active": con.execute(
            f"SELECT COUNT(*) FROM entity_relationships WHERE valid_to = {SENTINEL_OPEN_LITERAL}"
        ).fetchone()[0],
        "rollups_active": con.execute(
            f"SELECT COUNT(*) FROM entity_rollup_history WHERE valid_to = {SENTINEL_OPEN_LITERAL}"
        ).fetchone()[0],
        "aliases_active": con.execute(
            f"SELECT COUNT(*) FROM entity_aliases WHERE valid_to = {SENTINEL_OPEN_LITERAL}"
        ).fetchone()[0],
        "classifications_active": con.execute(
            f"SELECT COUNT(*) FROM entity_classification_history WHERE valid_to = {SENTINEL_OPEN_LITERAL}"
        ).fetchone()[0],
        "tier4_unknown_active": con.execute(
            f"""SELECT COUNT(*) FROM entities e
                  JOIN entity_classification_history h
                    ON h.entity_id = e.entity_id
                 WHERE e.created_source = 'bootstrap_tier4'
                   AND h.classification = 'unknown'
                   AND h.valid_to = {SENTINEL_OPEN_LITERAL}"""
        ).fetchone()[0],
        "tier4_sweep_active": con.execute(
            f"""SELECT COUNT(*) FROM entity_classification_history
                 WHERE source = '{SWEEP_SOURCE}'
                   AND valid_to = {SENTINEL_OPEN_LITERAL}"""
        ).fetchone()[0],
        "overrides_total": con.execute(
            "SELECT COUNT(*) FROM entity_overrides_persistent"
        ).fetchone()[0],
    }
    print(f"\n{label}: {counts}")
    return counts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--confirm", action="store_true")
    p.add_argument("--prod-db", default=DEFAULT_PROD_DB)
    args = p.parse_args()

    apply = bool(args.confirm)
    if not os.path.exists(args.prod_db):
        print(f"FATAL: prod DB missing: {args.prod_db}", file=sys.stderr)
        return 2

    con = duckdb.connect(args.prod_db, read_only=not apply)
    try:
        print(f"DB: {args.prod_db}  mode: {'APPLY' if apply else 'DRY-RUN'}")
        before = snapshot(con, "BEFORE")
        if apply:
            con.execute("BEGIN TRANSACTION")
            try:
                do_calamos_merge(con)
                tier4_classify_sweep(con, dry_run=False)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        else:
            # In dry-run, print the planned actions without writing.
            print("\n[DRY-RUN] Calamos merge — would run all six steps.")
            print("[DRY-RUN] Tier 4 classification sweep — counting only:")
            tier4_classify_sweep(con, dry_run=True)
        after = snapshot(con, "AFTER")
        print("\nDeltas:")
        for k in after:
            d = after[k] - before[k]
            if d:
                print(f"  Δ {k}: {d:+}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
