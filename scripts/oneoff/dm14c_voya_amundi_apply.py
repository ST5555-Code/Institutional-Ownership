#!/usr/bin/env python3
"""dm14c_voya_amundi_apply.py — staging-only DM chain-walk + Amundi re-route.

Applies two items in one transaction against the staging DB:

**Item 1 — Voya DM14c.** Voya Financial Inc (eid=2489) is the top-of-group
holding parent. Three known operating subsidiaries live separately in MDM:
  - eid=17915 "Voya Investment Management Co. LLC"  (CRD 106494)
  - eid=4071  "VOYA INVESTMENTS, LLC"               (CIK 1077479, CRD 111091)
  - eid=1591  "Voya Investment Management LLC"      (CIK 1068837, CRD 108934)

This script adds three `wholly_owned` edges 2489→{17915, 4071, 1591}, then
DM chain-walks all series currently decision_maker_v1-rolled to any of the
three subs up to eid=2489 (Voya Financial). EC rollups unchanged.

**Item 4 — Amundi / Victory re-route.** Amundi US merged into Victory Capital
Holdings Inc (CIK 0001570827) — transaction closed April 1, 2025. Post-merger
structure we encode:
  - Victory Capital Holdings (eid=24864, bootstrapped) = top parent
  - wholly_owned edge: 24864 → 9130 "VICTORY CAPITAL MANAGEMENT INC" (operating)
  - Re-target eid=4294 "Ameraudi / Amundi Asset Management, Inc." (Amundi US)
    rollups (both worldviews) from self → 24864 via `merged_into` rule.
  - Close the incorrect eid=4248 → eid=752 "Amundi Taiwan Ltd." rollup
    (parent_bridge_sync artifact); flip eid=4248 back to self-rollup pending
    a proper Amundi SA parent.
  - Other 9 children of eid=752 (eid 1318/1414/3217/3975/4667/5403/6006/
    7079/8338) are NOT re-routed this round — they need an Amundi
    geo/legal-entity audit (SA/Japan/Australia/etc.) before attribution to
    Victory or any Amundi SA parent. Flagged for DM15c follow-up.

Every rollup change is SCD-closed (valid_to set to prior day) and a new
open row is inserted with the correct rollup_entity_id. `entity_overrides_
persistent` rows are added for replay safety.

Usage:
    python3 scripts/dm14c_voya_amundi_apply.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

SOURCE = "dm14c_voya_amundi_2026_04_17"
OPEN = date(9999, 12, 31)


def _add_wholly_owned(con, parent_eid: int, child_eid: int) -> bool:
    existing = con.execute(
        """SELECT 1 FROM entity_relationships
           WHERE parent_entity_id=? AND child_entity_id=?
             AND relationship_type='wholly_owned'
             AND valid_to = DATE '9999-12-31'""",
        [parent_eid, child_eid],
    ).fetchone()
    if existing:
        print(f"  [edge-exists] {parent_eid}→{child_eid}")
        return False
    con.execute(
        """INSERT INTO entity_relationships
             (parent_entity_id, child_entity_id, relationship_type,
              control_type, is_primary, confidence, source, is_inferred,
              valid_from, valid_to, created_at, last_refreshed_at)
           VALUES (?, ?, 'wholly_owned', 'full', TRUE, 'exact',
                   ?, FALSE, DATE '2000-01-01', DATE '9999-12-31',
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        [parent_eid, child_eid, SOURCE],
    )
    print(f"  [edge-added]  {parent_eid}→{child_eid} wholly_owned")
    return True


def _retarget_dm_rollups(con, child_eid: int, new_parent_eid: int) -> int:
    """Close all DM rollups pointing at `child_eid` and insert new rows
    pointing at `new_parent_eid`. Returns number of series retargeted.
    Does NOT touch the `entity_id=child_eid, rollup_entity_id=child_eid`
    self rollup — only series rolled to child are moved up."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    rows = con.execute(
        """SELECT entity_id, rule_applied, confidence, source,
                  routing_confidence
             FROM entity_rollup_history
            WHERE rollup_entity_id = ?
              AND rollup_type = 'decision_maker_v1'
              AND valid_to = DATE '9999-12-31'
              AND entity_id != ?""",
        [child_eid, child_eid],
    ).fetchall()
    if not rows:
        return 0

    con.execute(
        """UPDATE entity_rollup_history SET valid_to = ?
            WHERE rollup_entity_id = ?
              AND rollup_type = 'decision_maker_v1'
              AND valid_to = DATE '9999-12-31'
              AND entity_id != ?""",
        [yesterday, child_eid, child_eid],
    )
    for entity_id, _rule, _conf, _src, _rconf in rows:
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to, computed_at, source,
                  routing_confidence)
               VALUES (?, ?, 'decision_maker_v1', 'manual_override',
                       'exact', ?, DATE '9999-12-31', CURRENT_TIMESTAMP,
                       ?, 'high')""",
            [entity_id, new_parent_eid, today, SOURCE],
        )
    return len(rows)


def _retarget_rollup_pair(con, entity_eid: int, new_parent_eid: int,
                          rule: str) -> int:
    """Close self/other rollups for `entity_eid` (both worldviews) and
    insert a new row pointing at `new_parent_eid`. For the Amundi US
    `merged_into` retarget."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    n = con.execute(
        """SELECT COUNT(*) FROM entity_rollup_history
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
        [entity_eid],
    ).fetchone()[0]
    if n == 0:
        return 0
    con.execute(
        """UPDATE entity_rollup_history SET valid_to = ?
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
        [yesterday, entity_eid],
    )
    for worldview in ("economic_control_v1", "decision_maker_v1"):
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to, computed_at, source,
                  routing_confidence)
               VALUES (?, ?, ?, ?, 'exact',
                       ?, DATE '9999-12-31', CURRENT_TIMESTAMP, ?, 'high')""",
            [entity_eid, new_parent_eid, worldview, rule, today, SOURCE],
        )
    return n


def _add_override(con, action: str, rollup_type, identifier_type,
                  identifier_value, new_value, reason: str) -> None:
    con.execute(
        """INSERT INTO entity_overrides_persistent
             (action, rollup_type, identifier_type, identifier_value,
              new_value, reason, analyst, still_valid,
              applied_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, TRUE,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        [action, rollup_type, identifier_type, identifier_value, new_value,
         reason, SOURCE],
    )


def main() -> None:
    db.set_staging_mode(True)
    print(f"dm14c_voya_amundi_apply.py — staging DB: {db.get_db_path()}")
    con = db.connect_write()
    try:
        # ---------------- Item 1 — Voya DM14c ----------------
        print("\n=== Item 1: Voya DM14c ===")
        VOYA_FIN = 2489
        VOYA_SUBS = [17915, 4071, 1591]
        edges_added = 0
        for sub in VOYA_SUBS:
            if _add_wholly_owned(con, VOYA_FIN, sub):
                edges_added += 1

        retargeted_total = 0
        for sub in VOYA_SUBS:
            n = _retarget_dm_rollups(con, sub, VOYA_FIN)
            print(f"  DM retargeted: eid={sub} → {VOYA_FIN}: {n} series")
            retargeted_total += n

        # Replay-safety override rows (one per retargeted series would be
        # heavy; record a single semantic merge per sub → parent).
        for sub in VOYA_SUBS:
            _add_override(
                con, action="merge", rollup_type="decision_maker_v1",
                identifier_type="entity_id", identifier_value=str(sub),
                new_value=str(VOYA_FIN),
                reason=f"DM14c: Voya sub {sub} rolls to Voya Financial "
                       "(eid=2489); wholly_owned evidence in entity_relationships.",
            )

        # ---------------- Item 4 — Amundi / Victory ----------------
        print("\n=== Item 4: Amundi / Victory re-route ===")
        VICTORY_HOLDINGS = 24864  # just bootstrapped
        VICTORY_OP       = 9130
        AMUNDI_US        = 4294  # absorbs eid=830 already via merged_into
        AMUNDI_830       = 830
        AMUNDI_SA        = 4248  # currently mis-rolled to eid=752 Amundi Taiwan
        AMUNDI_TAIWAN    = 752

        # wholly_owned edge Victory Holdings → Victory Capital Mgmt (operating)
        if _add_wholly_owned(con, VICTORY_HOLDINGS, VICTORY_OP):
            edges_added += 1

        # Re-route Amundi US (eid=4294) self-rollup → Victory Holdings
        n4294 = _retarget_rollup_pair(
            con, AMUNDI_US, VICTORY_HOLDINGS, "merged_into",
        )
        print(f"  Amundi US eid={AMUNDI_US}: retargeted {n4294} rollup rows → {VICTORY_HOLDINGS}")

        # eid=830 already rolls to 4294 (merged_into); retarget 830 → Victory too
        # so chain walks straight to Victory without going through 4294.
        n830 = _retarget_rollup_pair(
            con, AMUNDI_830, VICTORY_HOLDINGS, "merged_into",
        )
        print(f"  Amundi eid={AMUNDI_830} (shell): retargeted {n830} rollup rows → {VICTORY_HOLDINGS}")

        # Close incorrect eid=4248 → eid=752 rollup; revert to self until
        # proper Amundi SA parent established
        today = date.today()
        yesterday = today - timedelta(days=1)
        con.execute(
            """UPDATE entity_rollup_history SET valid_to = ?
                WHERE entity_id = ?
                  AND rollup_entity_id = ?
                  AND valid_to = DATE '9999-12-31'""",
            [yesterday, AMUNDI_SA, AMUNDI_TAIWAN],
        )
        for worldview in ("economic_control_v1", "decision_maker_v1"):
            con.execute(
                """INSERT INTO entity_rollup_history
                     (entity_id, rollup_entity_id, rollup_type, rule_applied,
                      confidence, valid_from, valid_to, computed_at, source,
                      routing_confidence)
                   VALUES (?, ?, ?, 'self', 'exact',
                           ?, DATE '9999-12-31', CURRENT_TIMESTAMP, ?, 'high')""",
                [AMUNDI_SA, AMUNDI_SA, worldview, today, SOURCE],
            )
        print(f"  Amundi SA eid={AMUNDI_SA}: closed rollup to Taiwan eid={AMUNDI_TAIWAN}; reverted to self")

        # Overrides for replay
        _add_override(
            con, "merge", "economic_control_v1", "entity_id",
            str(AMUNDI_US), str(VICTORY_HOLDINGS),
            "Item 4: Amundi US absorbed into Victory Capital Holdings "
            "(April 1, 2025 merger).",
        )
        _add_override(
            con, "merge", "decision_maker_v1", "entity_id",
            str(AMUNDI_US), str(VICTORY_HOLDINGS),
            "Item 4: Amundi US DM routing post-merger.",
        )
        _add_override(
            con, "suppress_relationship", None, "entity_id",
            str(AMUNDI_SA),
            f"self",
            f"Item 4: closed parent_bridge_sync rollup "
            f"{AMUNDI_SA}→{AMUNDI_TAIWAN} (Amundi Taiwan was artifact).",
        )

        con.execute("CHECKPOINT")
        print(f"\nEdges added (total this run): {edges_added}")
        print(f"Voya DM retargets: {retargeted_total} series")
    finally:
        con.close()


if __name__ == "__main__":
    main()
