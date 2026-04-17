"""
DM15 Layer 1 — apply 15 external-sub-adviser DM rollup retargets (staging).

Routes `decision_maker_v1` from umbrella advisers to the actual external
sub-adviser per `ncen_adviser_map` for the 4 umbrellas with N-CEN
role='subadviser' rows already populated and sub-adviser entities already
in MDM.

Scope (N-CEN subadviser rows 2026-04-17):
  ALPS Advisors       (7 series) → CoreCommodity / Smith / Morningstar
  Valmark Advisers    (6 series) → Milliman Financial Risk Management
  Focus Partners ASL  (1 series) → DFA (canonical eid=5026)
  Manning & Napier    (1 series) → Callodine Capital Management

4 sub-advisers / 15 funds / ~$10.3B combined AUM.

Replay caveat: 8 of 15 rows target entities with no CIK in MDM
(Smith 18899, Milliman 18304 — plus Morningstar fragmentation below).
These overrides apply immediately but won't survive `build_entities.py
--reset` via CIK lookup. Same INF9d precedent. Fragmentation cleanup
queued as INF23 (Morningstar 19596→10513, DFA 18096→5026, + CIK
backfill for Smith/Milliman/Callodine).

For fragmented targets this pass routes to CANONICAL eids with CIKs
(Morningstar 10513, DFA 5026) — not the fragmented eids DM1 used.
This creates eid mix within cluster; resolved by INF23.

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
    # ALPS Advisors umbrella (7) — parent CRD 000134340, eid=6785
    (18898, "S000028470", 7050, "0001301743",
     "DM15: ALPS umbrella → CoreCommodity Management, LLC per N-CEN subadviser"),
    (18900, "S000062210", 7050, "0001301743",
     "DM15: ALPS umbrella → CoreCommodity Management, LLC per N-CEN subadviser"),
    (18901, "S000085672", 18899, None,
     "DM15: ALPS umbrella → Smith Capital Investors, LLC per N-CEN subadviser (target has no CIK; replay gap, INF9d precedent)"),
    (18902, "S000069461", 18899, None,
     "DM15: ALPS umbrella → Smith Capital Investors, LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    (19595, "S000015808", 10513, "0001673385",
     "DM15: ALPS umbrella → Morningstar Investment Management LLC (canonical eid=10513) per N-CEN subadviser"),
    (19597, "S000015809", 10513, "0001673385",
     "DM15: ALPS umbrella → Morningstar Investment Management LLC (canonical eid=10513) per N-CEN subadviser"),
    (19598, "S000015811", 10513, "0001673385",
     "DM15: ALPS umbrella → Morningstar Investment Management LLC (canonical eid=10513) per N-CEN subadviser"),
    # Valmark Advisers umbrella (6) — parent CRD 000108050, eid=6063
    (19576, "S000031506", 18304, None,
     "DM15: Valmark umbrella → Milliman Financial Risk Management LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    (19577, "S000031503", 18304, None,
     "DM15: Valmark umbrella → Milliman Financial Risk Management LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    (19578, "S000031502", 18304, None,
     "DM15: Valmark umbrella → Milliman Financial Risk Management LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    (19579, "S000031505", 18304, None,
     "DM15: Valmark umbrella → Milliman Financial Risk Management LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    (19580, "S000031507", 18304, None,
     "DM15: Valmark umbrella → Milliman Financial Risk Management LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    (19581, "S000040836", 18304, None,
     "DM15: Valmark umbrella → Milliman Financial Risk Management LLC per N-CEN subadviser (target has no CIK; replay gap)"),
    # Focus Partners Advisor Solutions umbrella (1 remaining gap) — parent CRD 000143319, eid=8861
    (19279, "S000015875", 5026, "0000354204",
     "DM15: Focus Partners umbrella → Dimensional Fund Advisors (canonical eid=5026) per N-CEN subadviser"),
    # Manning & Napier Advisors umbrella (1) — parent CRD 000105992, eid=5673
    (18246, "S000063205", 246, "0001741675",
     "DM15: Manning & Napier umbrella → Callodine Capital Management, LP per N-CEN subadviser"),
]
ANALYST = "claude-dm15-layer1"


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

    print(f"\nApplying {len(CANDIDATES)} DM15 Layer 1 retargets against staging...")

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

            # Idempotent override insert — key on series_id + target identity.
            # For NULL-CIK targets, dedupe on (series_id, new_value IS NULL).
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
