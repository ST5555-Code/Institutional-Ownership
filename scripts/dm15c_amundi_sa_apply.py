"""
DM15c — Amundi SA global parent correction (staging).

Corrects the parent_bridge_sync artifact that routed 9 geographic Amundi
subsidiaries into eid=752 Amundi Taiwan Ltd. as if Taiwan were the global
parent. Amundi Taiwan is a regional operating sub. The true global parent
is eid=2214 (Paris HQ, CIK 0001330387, CRD 334151) — already in MDM as a
self-rolling entity with canonical_name='Amundi' and classification='passive'.

Scope (12 entities rerouted to eid=2214 on BOTH worldviews):
  1318   0001696432  AMUNDI AUSTRIA GMBH
  1414   0001696433  AMUNDI HONG KONG LTD
  3217   0001932771  Amundi SGR S.p.A. (Italy)
  3975   0001905668  Amundi Singapore Ltd
  4248   0001280690  Amundi Asset Management (French op sub; DM14c revert)
  4667   0001731532  Amundi Deutschland GmbH
  5403   0001482818  Amundi Japan Ltd.
  6006   0001732769  Amundi Czech Republic Asset Management, a.s.
  7079   0001935264  Amundi Czech Republic Investicni Spolecnost, a.s.
  8338   0001935237  Amundi (UK) Ltd
  10266  0001768066  Amundi Ireland Ltd (currently mis-routed to 4294 Ameraudi)
  752    0001941328  Amundi Taiwan Ltd. (self-rolling, rerouted to 2214)

Parent edits on eid=2214:
  - entities.canonical_name: 'Amundi' -> 'Amundi SA'
  - entity_aliases: SCD-close preferred alias 'Amundi', open new 'Amundi SA'
  - entity_classification_history: SCD-close 'passive', open 'active'

Plus eid=752 reclassified 'unknown' -> 'active' (regional operating sub).

Override accounting: 12 entities x 2 worldviews = 24 override rows
(IDs 222-245 approx). All targets carry CIK (0001330387) — no replay
gaps, migration 007 NULL-tolerance not needed.

Writes against STAGING ONLY. Single transaction.
"""
from __future__ import annotations

import os
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")

PARENT_EID = 2214
PARENT_CIK = "0001330387"
PARENT_NEW_NAME = "Amundi SA"
PARENT_NEW_CLASSIFICATION = "active"

# (child_eid, child_cik, short_name)
CHILDREN = [
    (1318,  "0001696432", "AMUNDI AUSTRIA GMBH"),
    (1414,  "0001696433", "AMUNDI HONG KONG LTD"),
    (3217,  "0001932771", "Amundi SGR S.p.A."),
    (3975,  "0001905668", "Amundi Singapore Ltd"),
    (4248,  "0001280690", "Amundi Asset Management (France)"),
    (4667,  "0001731532", "Amundi Deutschland GmbH"),
    (5403,  "0001482818", "Amundi Japan Ltd."),
    (6006,  "0001732769", "Amundi Czech Republic Asset Management"),
    (7079,  "0001935264", "Amundi Czech Republic Investicni Spolecnost"),
    (8338,  "0001935237", "Amundi (UK) Ltd"),
    (10266, "0001768066", "Amundi Ireland Ltd"),
    (752,   "0001941328", "Amundi Taiwan Ltd."),
]
ROLLUP_TYPES = ("economic_control_v1", "decision_maker_v1")
ANALYST = "claude-dm15c"
SOURCE = "dm15c_amundi_sa"

# eid=752 additional reclassification (regional sub)
TAIWAN_EID = 752
TAIWAN_NEW_CLASSIFICATION = "active"


def _retarget_rollup(con, entity_id: int, rollup_type: str,
                     target_eid: int) -> tuple[int | None, str | None]:
    """Close active rollup row and insert a new one pointing at target_eid.
    Returns (prior_target, prior_rule) for logging, or (None, None) if idempotent.
    """
    cur = con.execute(
        """SELECT rollup_entity_id, rule_applied
             FROM entity_rollup_history
            WHERE entity_id = ? AND rollup_type = ?
              AND valid_to = DATE '9999-12-31'""",
        [entity_id, rollup_type],
    ).fetchone()
    if cur is None:
        return None, None
    cur_target, cur_rule = cur
    if cur_target == target_eid and cur_rule == "manual_override":
        return cur_target, cur_rule  # idempotent — no SCD churn
    con.execute(
        """UPDATE entity_rollup_history SET valid_to = CURRENT_DATE
            WHERE entity_id = ? AND rollup_type = ?
              AND valid_to = DATE '9999-12-31'""",
        [entity_id, rollup_type],
    )
    con.execute(
        """INSERT INTO entity_rollup_history
             (entity_id, rollup_entity_id, rollup_type, rule_applied,
              confidence, valid_from, valid_to, computed_at, source,
              routing_confidence)
           VALUES (?, ?, ?, 'manual_override', 'exact',
                   CURRENT_DATE, DATE '9999-12-31',
                   CURRENT_TIMESTAMP, ?, 'high')""",
        [entity_id, target_eid, rollup_type, SOURCE],
    )
    return cur_target, cur_rule


def _insert_override(con, entity_cik: str, rollup_type: str, reason: str) -> int:
    """Insert a merge override keyed on child CIK -> parent CIK.
    Idempotent — existing active row is left untouched.
    """
    existing = con.execute(
        """SELECT override_id FROM entity_overrides_persistent
            WHERE action = 'merge'
              AND rollup_type = ?
              AND identifier_type = 'cik'
              AND identifier_value = ?
              AND new_value = ?
              AND still_valid = TRUE""",
        [rollup_type, entity_cik, PARENT_CIK],
    ).fetchone()
    if existing:
        return existing[0]
    new_id = con.execute(
        "SELECT COALESCE(MAX(override_id), 0) + 1 "
        "FROM entity_overrides_persistent"
    ).fetchone()[0]
    con.execute(
        """INSERT INTO entity_overrides_persistent
             (override_id, entity_cik, action, field, old_value,
              new_value, reason, analyst, still_valid,
              identifier_type, identifier_value, rollup_type)
           VALUES (?, ?, 'merge', NULL, NULL,
                   ?, ?, ?, TRUE, 'cik', ?, ?)""",
        [new_id, None, PARENT_CIK, reason, ANALYST, entity_cik, rollup_type],
    )
    return new_id


def _update_parent(con) -> None:
    """Rename + reclassify eid=2214 Amundi -> Amundi SA / active."""
    # canonical_name update
    con.execute(
        "UPDATE entities SET canonical_name = ? WHERE entity_id = ?",
        [PARENT_NEW_NAME, PARENT_EID],
    )
    print(f"  entities.canonical_name[{PARENT_EID}] -> '{PARENT_NEW_NAME}'")

    # SCD alias: close preferred, open new preferred
    cur_alias = con.execute(
        """SELECT alias_name FROM entity_aliases
            WHERE entity_id = ? AND is_preferred = TRUE
              AND valid_to = DATE '9999-12-31'
            LIMIT 1""",
        [PARENT_EID],
    ).fetchone()
    if cur_alias and cur_alias[0] != PARENT_NEW_NAME:
        con.execute(
            """UPDATE entity_aliases SET valid_to = CURRENT_DATE
                WHERE entity_id = ? AND is_preferred = TRUE
                  AND valid_to = DATE '9999-12-31'""",
            [PARENT_EID],
        )
        con.execute(
            """INSERT INTO entity_aliases
                 (entity_id, alias_name, alias_type, is_preferred, preferred_key,
                  source_table, is_inferred, valid_from, valid_to)
               VALUES (?, ?, 'brand', TRUE, ?, ?, FALSE,
                       CURRENT_DATE, DATE '9999-12-31')""",
            [PARENT_EID, PARENT_NEW_NAME, PARENT_EID, SOURCE],
        )
        print(f"  alias[{PARENT_EID}] SCD '{cur_alias[0]}' -> '{PARENT_NEW_NAME}'")
    else:
        print(f"  alias[{PARENT_EID}] already '{PARENT_NEW_NAME}' — skip")

    # SCD classification: close current, open active
    cur_cls = con.execute(
        """SELECT classification FROM entity_classification_history
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
            LIMIT 1""",
        [PARENT_EID],
    ).fetchone()
    if cur_cls and cur_cls[0] != PARENT_NEW_CLASSIFICATION:
        con.execute(
            """UPDATE entity_classification_history SET valid_to = CURRENT_DATE
                WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
            [PARENT_EID],
        )
        con.execute(
            """INSERT INTO entity_classification_history
                 (entity_id, classification, is_activist, confidence,
                  source, is_inferred, valid_from, valid_to)
               VALUES (?, ?, FALSE, 'exact', ?, FALSE,
                       CURRENT_DATE, DATE '9999-12-31')""",
            [PARENT_EID, PARENT_NEW_CLASSIFICATION, SOURCE],
        )
        print(f"  classification[{PARENT_EID}] SCD "
              f"'{cur_cls[0]}' -> '{PARENT_NEW_CLASSIFICATION}'")
    else:
        print(f"  classification[{PARENT_EID}] already "
              f"'{PARENT_NEW_CLASSIFICATION}' — skip")


def _reclassify_taiwan(con) -> None:
    """eid=752 Amundi Taiwan: 'unknown' -> 'active' (regional operating sub)."""
    cur_cls = con.execute(
        """SELECT classification FROM entity_classification_history
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
            LIMIT 1""",
        [TAIWAN_EID],
    ).fetchone()
    if cur_cls and cur_cls[0] != TAIWAN_NEW_CLASSIFICATION:
        con.execute(
            """UPDATE entity_classification_history SET valid_to = CURRENT_DATE
                WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
            [TAIWAN_EID],
        )
        con.execute(
            """INSERT INTO entity_classification_history
                 (entity_id, classification, is_activist, confidence,
                  source, is_inferred, valid_from, valid_to)
               VALUES (?, ?, FALSE, 'exact', ?, FALSE,
                       CURRENT_DATE, DATE '9999-12-31')""",
            [TAIWAN_EID, TAIWAN_NEW_CLASSIFICATION, SOURCE],
        )
        print(f"  classification[{TAIWAN_EID}] SCD "
              f"'{cur_cls[0]}' -> '{TAIWAN_NEW_CLASSIFICATION}'")
    else:
        print(f"  classification[{TAIWAN_EID}] already "
              f"'{TAIWAN_NEW_CLASSIFICATION}' — skip")


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    baseline_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE valid_to = DATE '9999-12-31'"
    ).fetchone()[0]
    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"BEFORE: entity_rollup_history(active) = {baseline_dm}")
    print(f"        entity_overrides_persistent   = {baseline_ov}")
    print()

    con.execute("BEGIN TRANSACTION")
    try:
        # (a) Parent rename + reclassify on eid=2214
        print("=== (a) Parent eid=2214 — rename + reclassify ===")
        _update_parent(con)

        # (b) 12 children × 2 worldviews retarget + override
        print(f"\n=== (b) Retarget {len(CHILDREN)} children × "
              f"{len(ROLLUP_TYPES)} worldviews -> eid={PARENT_EID} ===")
        for child_eid, child_cik, name in CHILDREN:
            for rollup_type in ROLLUP_TYPES:
                prior_tgt, prior_rule = _retarget_rollup(
                    con, child_eid, rollup_type, PARENT_EID
                )
                if prior_tgt is None:
                    print(f"  SKIP  eid={child_eid:<6} {rollup_type:20s} "
                          f"no active rollup row ({name})")
                    continue
                if prior_tgt == PARENT_EID and prior_rule == "manual_override":
                    print(f"  SKIP  eid={child_eid:<6} {rollup_type:20s} "
                          f"already at {PARENT_EID}/manual_override ({name})")
                    continue
                reason = (
                    f"DM15c: {name} -> Amundi SA global parent (eid={PARENT_EID}) "
                    f"— replaces parent_bridge_sync artifact"
                )
                oid = _insert_override(con, child_cik, rollup_type, reason)
                print(f"  DONE  eid={child_eid:<6} {rollup_type:20s} "
                      f"{prior_tgt}({prior_rule}) -> {PARENT_EID}  "
                      f"override_id={oid}  ({name})")

        # (c) eid=752 reclassify (reroute handled in (b) since 752 is in CHILDREN)
        print("\n=== (c) eid=752 Amundi Taiwan — reclassify ===")
        _reclassify_taiwan(con)

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    post_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE valid_to = DATE '9999-12-31'"
    ).fetchone()[0]
    post_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"\nAFTER:  entity_rollup_history(active) = {post_dm}  (Δ {post_dm - baseline_dm})")
    print(f"        entity_overrides_persistent   = {post_ov}  (Δ {post_ov - baseline_ov})")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
