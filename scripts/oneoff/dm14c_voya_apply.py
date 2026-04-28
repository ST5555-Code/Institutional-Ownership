"""
DM14c Voya residual — DM re-route 49 actively-managed Voya series from
the holding co (eid=2489 Voya Financial, Inc.) down to the operating
sub-adviser (eid=17915 Voya Investment Management Co. LLC).

Same pattern as DM14b (scripts/oneoff/dm14b_apply.py).

Background:
- Prior DM14c oneoff (scripts/oneoff/dm14c_voya_amundi_apply.py) added the
  three wholly_owned edges 2489 -> {17915, 4071, 1591} and rolled all
  Voya-Voya intra-firm sub-advised series UP to eid=2489 (the Voya
  Financial holding co). That collapsed identity (which entity is this
  fund's home shop?) but conflated DM with EC: per architecture spec,
  decision_maker_v1 should point at the entity actually making investment
  decisions (the operating sub-adviser), not the holding parent. EC was
  always correctly at eid=4071 (VOYA INVESTMENTS, LLC) via fund_sponsor.

Scope (verified read-only against prod 2026-04-28):
- adviser_crd = 000111091 (Voya Investments LLC, eid=4071)
- subadviser_crd = 000106494 (Voya Investment Management Co. LLC, eid=17915)
- fund_universe.is_actively_managed = TRUE
- 49 series, $21.74B total AUM
- All 49 currently have erh.rollup_entity_id=2489 with
  rule_applied='manual_override' on decision_maker_v1.

What this script does (one transaction against staging):
  Step 1. SCD-close the 49 DM rollup rows pointing at 2489.
  Step 2. SCD-open 49 new DM rollup rows pointing at 17915 with
          rule_applied='manual_override', confidence='exact'.
  Step 3. Insert one entity_overrides_persistent row per series for
          replay safety (action='merge', rollup_type='decision_maker_v1',
          identifier_type='series_id', new_value='17915').
  Step 4. CHECKPOINT.

NOT done:
- No new entity created. eid=2489 already exists.
- No new wholly_owned edges. The three 2489->{17915,4071,1591} edges
  exist from the prior DM14c oneoff.
- economic_control_v1 untouched.
- Passive Voya-Voya series (the 32 funds at eid=2489 with
  is_actively_managed=FALSE) intentionally NOT retargeted -- per
  architecture, passive funds should mirror EC (eid=4071), but that's a
  separate cleanup pass.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

ANALYST = "claude-dm14c-voya-2026-04-28"
SUBADVISER_CRD = "000106494"  # Voya Investment Management Co. LLC
SUBADVISER_EID = 17915
WRONG_PARENT_EID = 2489       # Voya Financial, Inc. (holding co)
ADVISER_CRD = "000111091"     # Voya Investments LLC


SCOPE_SQL = """
WITH ss AS (
  SELECT DISTINCT a.series_id
    FROM ncen_adviser_map a
    JOIN ncen_adviser_map s ON s.series_id = a.series_id
                          AND s.valid_to = DATE '9999-12-31'
   WHERE a.adviser_crd = ?
     AND a.role = 'adviser'
     AND a.valid_to = DATE '9999-12-31'
     AND s.adviser_crd = ?
     AND s.role = 'subadviser'
)
SELECT ei.entity_id AS fund_eid,
       e.canonical_name AS fund_name,
       ss.series_id,
       fu.total_net_assets AS aum
  FROM ss
  JOIN entity_identifiers ei ON ei.identifier_value = ss.series_id
                            AND ei.identifier_type = 'series_id'
                            AND ei.valid_to = DATE '9999-12-31'
  JOIN entities e ON e.entity_id = ei.entity_id
  JOIN entity_rollup_history erh ON erh.entity_id = ei.entity_id
                                AND erh.rollup_type = 'decision_maker_v1'
                                AND erh.valid_to = DATE '9999-12-31'
                                AND erh.rollup_entity_id = ?
  JOIN fund_universe fu ON fu.series_id = ss.series_id
 WHERE fu.is_actively_managed
 ORDER BY fu.total_net_assets DESC NULLS LAST
"""


def main() -> int:
    db.set_staging_mode(True)
    print(f"dm14c_voya_apply.py — staging DB: {db.get_db_path()}")
    con = db.connect_write()

    # Read fund_universe + ncen_adviser_map from prod (reference data not in staging).
    prod_path = db.PROD_DB
    con.execute(f"ATTACH '{prod_path}' AS prod (READ_ONLY)")

    # Build the in-staging series list using prod refs + staging entity tables.
    # Both ncen_adviser_map and fund_universe are reference-only and live in prod.
    series_rows = con.execute(f"""
        WITH ss AS (
          SELECT DISTINCT a.series_id
            FROM prod.ncen_adviser_map a
            JOIN prod.ncen_adviser_map s ON s.series_id = a.series_id
                                       AND s.valid_to = DATE '9999-12-31'
           WHERE a.adviser_crd = ?
             AND a.role = 'adviser'
             AND a.valid_to = DATE '9999-12-31'
             AND s.adviser_crd = ?
             AND s.role = 'subadviser'
        )
        SELECT ei.entity_id AS fund_eid,
               e.canonical_name AS fund_name,
               ss.series_id,
               fu.total_net_assets AS aum
          FROM ss
          JOIN entity_identifiers ei ON ei.identifier_value = ss.series_id
                                    AND ei.identifier_type = 'series_id'
                                    AND ei.valid_to = DATE '9999-12-31'
          JOIN entities e ON e.entity_id = ei.entity_id
          JOIN entity_rollup_history erh ON erh.entity_id = ei.entity_id
                                        AND erh.rollup_type = 'decision_maker_v1'
                                        AND erh.valid_to = DATE '9999-12-31'
                                        AND erh.rollup_entity_id = ?
          JOIN prod.fund_universe fu ON fu.series_id = ss.series_id
         WHERE fu.is_actively_managed
         ORDER BY fu.total_net_assets DESC NULLS LAST
    """, [ADVISER_CRD, SUBADVISER_CRD, WRONG_PARENT_EID]).fetchall()

    n_scope = len(series_rows)
    total_aum = sum((r[3] or 0) for r in series_rows) / 1e9
    print(f"\nScope: {n_scope} active Voya-Voya series at eid={WRONG_PARENT_EID} "
          f"(${total_aum:.2f}B)")

    if n_scope == 0:
        print("No rows in scope — nothing to do.")
        con.close()
        return 0

    baseline_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to=DATE '9999-12-31'"
    ).fetchone()[0]
    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    baseline_max_ov = con.execute(
        "SELECT MAX(override_id) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"BEFORE: DM rollups active={baseline_dm}  "
          f"overrides={baseline_ov}  MAX(override_id)={baseline_max_ov}")

    today = date.today()
    yesterday = today - timedelta(days=1)

    con.execute("BEGIN TRANSACTION")
    try:
        retargeted = 0
        overrides_added = 0
        for fund_eid, fund_name, series_id, aum in series_rows:
            # SCD-close the existing DM row pointing at 2489
            con.execute("""
                UPDATE entity_rollup_history
                   SET valid_to = ?
                 WHERE entity_id = ?
                   AND rollup_type = 'decision_maker_v1'
                   AND rollup_entity_id = ?
                   AND valid_to = DATE '9999-12-31'
            """, [yesterday, fund_eid, WRONG_PARENT_EID])

            # SCD-open a new DM row pointing at 17915
            con.execute("""
                INSERT INTO entity_rollup_history
                  (entity_id, rollup_entity_id, rollup_type, rule_applied,
                   confidence, valid_from, valid_to, computed_at, source,
                   routing_confidence)
                VALUES (?, ?, 'decision_maker_v1', 'manual_override',
                        'exact', ?, DATE '9999-12-31', CURRENT_TIMESTAMP,
                        ?, 'high')
            """, [fund_eid, SUBADVISER_EID, today, ANALYST])
            retargeted += 1

            # Idempotent override: skip if already present for this series_id
            # pointing at 17915
            existing = con.execute("""
                SELECT override_id FROM entity_overrides_persistent
                 WHERE action = 'merge'
                   AND rollup_type = 'decision_maker_v1'
                   AND identifier_type = 'series_id'
                   AND identifier_value = ?
                   AND new_value = ?
                   AND still_valid = TRUE
            """, [series_id, str(SUBADVISER_EID)]).fetchone()
            if existing:
                continue

            new_id = con.execute(
                "SELECT COALESCE(MAX(override_id), 0) + 1 "
                "FROM entity_overrides_persistent"
            ).fetchone()[0]

            reason = (
                f"DM14c Voya residual: {fund_name} (series {series_id}) "
                f"DM-routed from holding-co eid={WRONG_PARENT_EID} "
                f"(Voya Financial, Inc.) to operating sub-adviser "
                f"eid={SUBADVISER_EID} (Voya Investment Management Co. LLC, "
                f"CRD {SUBADVISER_CRD}). Active fund per "
                f"fund_universe.is_actively_managed; per architecture, DM "
                f"points at the entity making decisions, not the parent."
            )
            con.execute("""
                INSERT INTO entity_overrides_persistent
                  (override_id, entity_cik, action, field, old_value,
                   new_value, reason, analyst, still_valid,
                   applied_at, created_at,
                   identifier_type, identifier_value, rollup_type)
                VALUES (?, NULL, 'merge', NULL, ?, ?, ?, ?, TRUE,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                        'series_id', ?, 'decision_maker_v1')
            """, [new_id, str(WRONG_PARENT_EID), str(SUBADVISER_EID),
                  reason, ANALYST, series_id])
            overrides_added += 1

        con.execute("COMMIT")
        con.execute("CHECKPOINT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to=DATE '9999-12-31'"
    ).fetchone()[0]
    after_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    after_max_ov = con.execute(
        "SELECT MAX(override_id) FROM entity_overrides_persistent"
    ).fetchone()[0]
    n_at_target = con.execute("""
        SELECT COUNT(*) FROM entity_rollup_history
         WHERE rollup_type='decision_maker_v1'
           AND valid_to = DATE '9999-12-31'
           AND rollup_entity_id = ?
           AND rule_applied = 'manual_override'
    """, [SUBADVISER_EID]).fetchone()[0]
    n_residual = con.execute("""
        SELECT COUNT(*) FROM entity_rollup_history erh
         WHERE erh.rollup_type='decision_maker_v1'
           AND erh.valid_to = DATE '9999-12-31'
           AND erh.rollup_entity_id = ?
           AND erh.rule_applied = 'manual_override'
           AND erh.entity_id IN (
             SELECT ei.entity_id
               FROM entity_identifiers ei
               JOIN prod.fund_universe fu ON fu.series_id = ei.identifier_value
              WHERE ei.identifier_type='series_id'
                AND ei.valid_to=DATE '9999-12-31'
                AND fu.is_actively_managed
                AND fu.series_id IN (
                  SELECT DISTINCT a.series_id
                    FROM prod.ncen_adviser_map a
                    JOIN prod.ncen_adviser_map s ON s.series_id=a.series_id
                                              AND s.valid_to=DATE '9999-12-31'
                   WHERE a.adviser_crd=? AND a.role='adviser'
                     AND a.valid_to=DATE '9999-12-31'
                     AND s.adviser_crd=? AND s.role='subadviser'
                )
           )
    """, [WRONG_PARENT_EID, ADVISER_CRD, SUBADVISER_CRD]).fetchone()[0]

    print(f"\nAFTER:  DM rollups active={after_dm}  "
          f"(Δ {after_dm - baseline_dm}; expected 0 — same fund, retargeted)")
    print(f"        overrides={after_ov}  (Δ {after_ov - baseline_ov})")
    print(f"        MAX(override_id)={after_max_ov}  "
          f"(was {baseline_max_ov})")
    print(f"        retargeted series this run: {retargeted}")
    print(f"        new override rows: {overrides_added}")
    print(f"\nVerification:")
    print(f"  rows now at eid={SUBADVISER_EID} via manual_override = {n_at_target}")
    print(f"  active Voya-Voya residual still at eid={WRONG_PARENT_EID} = {n_residual} (must be 0)")

    if n_residual != 0:
        print("ERROR: residual at wrong parent — verification FAILED.", file=sys.stderr)
        con.close()
        return 1

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
