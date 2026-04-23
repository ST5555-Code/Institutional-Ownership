"""
DM15 Layer 2 — apply 17 external-sub-adviser DM rollup retargets (staging).

Routes `decision_maker_v1` from fund-sponsor umbrellas (NYLI IM, Principal
Global, SEI IM, Voya Financial Inc) to the actual external sub-adviser per
N-CEN role='subadviser' rows, using the N-CEN ingestion from DM15b
(2026-04-17 — fetch_ncen.py --ciks, commit 9ce5b17).

Scope (17 series / ~$8.95B AUM / 7 sub-advisers, all already in MDM):

  Voya Investment Management Co. LLC   (eid=17915)  4 series  $3.06B
  MACKAY SHIELDS LLC                   (eid= 6290)  6 series  $2.40B
  Spectrum Asset Management, Inc.      (eid=10034)  2 series  $1.56B
  Winslow Capital Management, LLC      (eid= 5046)  2 series  $1.41B
  PRINCIPAL REAL ESTATE INVESTORS LLC  (eid= 8652)  1 series  $0.40B
  Dynamic Beta Investments LLC         (eid=19093)  1 series  $0.18B
  CBRE INVESTMENT MGMT LISTED REAL ASS (eid=11166)  1 series  $0.01B

CBRE tiebreak: eid=11166 (CIK+CRD, $6.81B own AUM) chosen over eid=18645
(CRD-only padded variant, $0 AUM). eid=18645 flagged as merge candidate
for a future INF pass — NOT merged this commit.

Replay caveat: Voya IM 17915 and Dynamic Beta 19093 have no CIK in MDM.
Their override rows use NULL new_value (same INF9d / DM15 L1 precedent —
Smith Capital, Milliman). 13 overrides carry CIKs, 4 are NULL-CIK.

Writes against STAGING ONLY. For each row:
  1. Close existing active entity_rollup_history(decision_maker_v1)
  2. Insert new row with rollup_entity_id = target_eid,
     rule_applied = 'manual_override'
  3. Insert entity_overrides_persistent row with
     action='merge', rollup_type='decision_maker_v1',
     identifier_type='series_id', new_value=<target CIK or NULL>
"""

import os
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")

CANDIDATES = [
    # (fund_eid, series_id, target_eid, target_cik_or_None, reason)
    # Voya Investment Management Co. LLC — eid=17915 (no CIK in MDM)
    (24405, "S000038555", 17915, None,
     "DM15 L2: retarget to Voya Investment Management Co. LLC per N-CEN subadviser "
     "(target has no CIK; replay gap, INF9d precedent)"),
    (24406, "S000039383", 17915, None,
     "DM15 L2: retarget to Voya Investment Management Co. LLC per N-CEN subadviser "
     "(target has no CIK; replay gap)"),
    (24484, "S000079627", 17915, None,
     "DM15 L2: retarget to Voya Investment Management Co. LLC per N-CEN subadviser "
     "(target has no CIK; replay gap)"),
    (24485, "S000079681", 17915, None,
     "DM15 L2: retarget to Voya Investment Management Co. LLC per N-CEN subadviser "
     "(target has no CIK; replay gap)"),
    # MacKay Shields LLC — eid=6290, CIK 0000061227
    (24434, "S000057661", 6290, "0000061227",
     "DM15 L2: retarget to MacKay Shields LLC per N-CEN subadviser"),
    (24433, "S000057660", 6290, "0000061227",
     "DM15 L2: retarget to MacKay Shields LLC per N-CEN subadviser"),
    (24456, "S000071156", 6290, "0000061227",
     "DM15 L2: retarget to MacKay Shields LLC per N-CEN subadviser"),
    (24506, "S000084196", 6290, "0000061227",
     "DM15 L2: retarget to MacKay Shields LLC per N-CEN subadviser"),
    (24481, "S000077600", 6290, "0000061227",
     "DM15 L2: retarget to MacKay Shields LLC per N-CEN subadviser"),
    (24450, "S000069622", 6290, "0000061227",
     "DM15 L2: retarget to MacKay Shields LLC per N-CEN subadviser"),
    # Spectrum Asset Management, Inc. — eid=10034, CIK 0001318293
    (24429, "S000054767", 10034, "0001318293",
     "DM15 L2: retarget to Spectrum Asset Management, Inc. per N-CEN subadviser"),
    (24443, "S000061644", 10034, "0001318293",
     "DM15 L2: retarget to Spectrum Asset Management, Inc. per N-CEN subadviser"),
    # Winslow Capital Management, LLC — eid=5046, CIK 0000900973
    (24471, "S000075560", 5046, "0000900973",
     "DM15 L2: retarget to Winslow Capital Management, LLC per N-CEN subadviser"),
    (24472, "S000075561", 5046, "0000900973",
     "DM15 L2: retarget to Winslow Capital Management, LLC per N-CEN subadviser"),
    # Principal Real Estate Investors LLC — eid=8652, CIK 0001218333
    (24494, "S000080686", 8652, "0001218333",
     "DM15 L2: retarget to Principal Real Estate Investors LLC per N-CEN subadviser"),
    # Dynamic Beta Investments LLC — eid=19093 (no CIK in MDM)
    (24601, "S000093461", 19093, None,
     "DM15 L2: retarget to Dynamic Beta Investments LLC per N-CEN subadviser "
     "(target has no CIK; replay gap)"),
    # CBRE Investment Management Listed Real Assets LLC — eid=11166, CIK 0001033984
    # (chosen over eid=18645 shell; 18645 flagged as merge candidate)
    (24488, "S000079855", 11166, "0001033984",
     "DM15 L2: retarget to CBRE Investment Management Listed Real Assets LLC "
     "per N-CEN subadviser (eid=11166 canonical; eid=18645 shell flagged)"),
]
ANALYST = "claude-dm15-layer2"


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    baseline_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to = DATE '9999-12-31'"
    ).fetchone()[0]
    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"BEFORE: entity_rollup_history(DM, active) = {baseline_dm}")
    print(f"        entity_overrides_persistent       = {baseline_ov}")

    print(f"\nApplying {len(CANDIDATES)} DM15 Layer 2 retargets against staging...")

    con.execute("BEGIN TRANSACTION")
    try:
        for (fund_eid, series_id, target_eid, target_cik, reason) in CANDIDATES:
            cur = con.execute(
                """SELECT rollup_entity_id, rule_applied
                     FROM entity_rollup_history
                    WHERE entity_id = ? AND rollup_type = 'decision_maker_v1'
                      AND valid_to = DATE '9999-12-31'""",
                [fund_eid],
            ).fetchone()
            if cur is None:
                print(f"  SKIP  fund={fund_eid} no active DM rollup")
                continue
            cur_target, cur_rule = cur
            if cur_target == target_eid and cur_rule == "manual_override":
                print(f"  SKIP  fund={fund_eid} already targeted at {target_eid}/manual_override")
                continue

            con.execute(
                """UPDATE entity_rollup_history SET valid_to = CURRENT_DATE
                    WHERE entity_id = ? AND rollup_type = 'decision_maker_v1'
                      AND valid_to = DATE '9999-12-31'""",
                [fund_eid],
            )
            con.execute(
                """INSERT INTO entity_rollup_history
                     (entity_id, rollup_entity_id, rollup_type, rule_applied,
                      confidence, valid_from, valid_to)
                   VALUES (?, ?, 'decision_maker_v1', 'manual_override',
                           'exact', CURRENT_DATE, DATE '9999-12-31')""",
                [fund_eid, target_eid],
            )
            cik_tag = target_cik or "NULL-CIK"
            print(
                f"  DONE  fund={fund_eid} series={series_id} DM {cur_target}(rule={cur_rule}) "
                f"→ {target_eid} ({cik_tag})"
            )

            if target_cik is not None:
                existing = con.execute(
                    """SELECT override_id FROM entity_overrides_persistent
                        WHERE action = 'merge'
                          AND rollup_type = 'decision_maker_v1'
                          AND identifier_type = 'series_id'
                          AND identifier_value = ?
                          AND new_value = ?
                          AND still_valid = TRUE""",
                    [series_id, target_cik],
                ).fetchone()
            else:
                existing = con.execute(
                    """SELECT override_id FROM entity_overrides_persistent
                        WHERE action = 'merge'
                          AND rollup_type = 'decision_maker_v1'
                          AND identifier_type = 'series_id'
                          AND identifier_value = ?
                          AND new_value IS NULL
                          AND reason = ?
                          AND still_valid = TRUE""",
                    [series_id, reason],
                ).fetchone()
            if existing:
                print(f"        override_id={existing[0]} already present — skipped")
                continue

            new_override_id = con.execute(
                "SELECT COALESCE(MAX(override_id), 0) + 1 "
                "FROM entity_overrides_persistent"
            ).fetchone()[0]
            con.execute(
                """INSERT INTO entity_overrides_persistent
                     (override_id, entity_cik, action, field, old_value,
                      new_value, reason, analyst, still_valid,
                      identifier_type, identifier_value, rollup_type)
                   VALUES (?, ?, 'merge', NULL, NULL,
                           ?, ?, ?, TRUE, 'series_id', ?, 'decision_maker_v1')""",
                [new_override_id, None, target_cik, reason, ANALYST, series_id],
            )
            print(f"        override_id={new_override_id} inserted")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    post_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to = DATE '9999-12-31'"
    ).fetchone()[0]
    post_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"\nAFTER:  entity_rollup_history(DM, active) = {post_dm}  (Δ {post_dm - baseline_dm})")
    print(f"        entity_overrides_persistent       = {post_ov}  (Δ {post_ov - baseline_ov})")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
