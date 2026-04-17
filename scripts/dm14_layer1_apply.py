"""
DM14 Layer 1 — apply 8 intra-firm DM rollup retargets (staging).

Extends the DM8 intra-firm collapse to cases where the fund's EC
rollup and the sub-adviser reach a common wholly_owned / parent_brand
ancestor via chain walk (up to 4 hops, bilateral).

Scope (discovered via chain-walk audit 2026-04-16):
  rel=826  fund=14384 (Natixis Oakmark Fund)            → 8386 Natixis IM
  rel=1200 fund=16072 (Calvert EM Focused)              → 2920 MORGAN STANLEY
  rel=2639 fund=14382 (Vaughan Nelson Small Cap Fund)   → 8386 Natixis IM
  rel=4460 fund=11635 (AMG Frontier Small Cap Growth)   → 8968 AMG
  rel=7221 fund=12826 (AMG Yacktman Global Fund)        → 8968 AMG
  rel=7225 fund=12827 (AMG Yacktman Special Opportunities) → 8968 AMG
  rel=7235 fund=12829 (AMG Yacktman Fund)               → 8968 AMG
  rel=7237 fund=12824 (AMG Yacktman Focused Fund)       → 8968 AMG

4 sub-advisers / 8 funds / $12.15B combined AUM.

Writes against STAGING ONLY. For each row:
  1. Close existing active entity_rollup_history(decision_maker_v1)
  2. Insert new row with rollup_entity_id = common_id,
     rule_applied = 'manual_override'
  3. Insert entity_overrides_persistent row with
     action='merge', rollup_type='decision_maker_v1',
     identifier_type='series_id', new_value=<parent CIK>

Survives build_entities.py --reset via replay_persistent_overrides.
"""

import os
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")

CANDIDATES = [
    # (fund_id, fund_series_id, target_entity_id, target_cik, reason)
    (14384, "S000008033", 8386, "0001053187",
     "DM14 intra-firm: Vaughan Nelson (Natixis affiliate) → Natixis IM"),
    (16072, "S000079266", 2920, "0000895421",
     "DM14 intra-firm: Morgan Stanley IM Co (MS subsidiary) → MORGAN STANLEY"),
    (14382, "S000006661", 8386, "0001053187",
     "DM14 intra-firm: Vaughan Nelson (Natixis affiliate) → Natixis IM"),
    (11635, "S000009910", 8968, "0001004434",
     "DM14 intra-firm: Frontier Capital (AMG affiliate) → AMG"),
    (12826, "S000056045", 8968, "0001004434",
     "DM14 intra-firm: Yacktman (AMG affiliate) → AMG"),
    (12827, "S000045879", 8968, "0001004434",
     "DM14 intra-firm: Yacktman (AMG affiliate) → AMG"),
    (12829, "S000037566", 8968, "0001004434",
     "DM14 intra-firm: Yacktman (AMG affiliate) → AMG"),
    (12824, "S000037565", 8968, "0001004434",
     "DM14 intra-firm: Yacktman (AMG affiliate) → AMG"),
]
ANALYST = "claude-dm14-layer1"


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    # Pre-flight sanity
    baseline_dm = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to = DATE '9999-12-31'"
    ).fetchone()[0]
    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"BEFORE: entity_rollup_history(DM, active) = {baseline_dm}")
    print(f"        entity_overrides_persistent       = {baseline_ov}")

    print(f"\nApplying {len(CANDIDATES)} DM14 Layer 1 retargets against staging...")

    con.execute("BEGIN TRANSACTION")
    try:
        for (fund_id, series_id, target_eid, target_cik, reason) in CANDIDATES:
            # Resolve current DM rollup for context
            cur = con.execute(
                """SELECT rollup_entity_id, rule_applied
                     FROM entity_rollup_history
                    WHERE entity_id = ? AND rollup_type = 'decision_maker_v1'
                      AND valid_to = DATE '9999-12-31'""",
                [fund_id],
            ).fetchone()
            if cur is None:
                print(f"  SKIP  fund={fund_id} no active DM rollup")
                continue
            cur_target, cur_rule = cur
            if cur_target == target_eid and cur_rule == "manual_override":
                print(f"  SKIP  fund={fund_id} already targeted at {target_eid}/manual_override")
                continue

            # Close existing active row
            con.execute(
                """UPDATE entity_rollup_history SET valid_to = CURRENT_DATE
                    WHERE entity_id = ? AND rollup_type = 'decision_maker_v1'
                      AND valid_to = DATE '9999-12-31'""",
                [fund_id],
            )
            # Insert new row
            con.execute(
                """INSERT INTO entity_rollup_history
                     (entity_id, rollup_entity_id, rollup_type, rule_applied,
                      confidence, valid_from, valid_to)
                   VALUES (?, ?, 'decision_maker_v1', 'manual_override',
                           'exact', CURRENT_DATE, DATE '9999-12-31')""",
                [fund_id, target_eid],
            )
            print(
                f"  DONE  fund={fund_id} DM {cur_target}(rule={cur_rule}) "
                f"→ {target_eid} (manual_override)"
            )

            # Idempotent override insert (reuse key: fund series_id + target CIK)
            existing_override = con.execute(
                """SELECT override_id FROM entity_overrides_persistent
                    WHERE action = 'merge'
                      AND rollup_type = 'decision_maker_v1'
                      AND identifier_type = 'series_id'
                      AND identifier_value = ?
                      AND new_value = ?
                      AND still_valid = TRUE""",
                [series_id, target_cik],
            ).fetchone()
            if existing_override:
                print(f"        override_id={existing_override[0]} already present — skipped")
                continue

            new_override_id = con.execute(
                "SELECT COALESCE(MAX(override_id), 0) + 1 "
                "FROM entity_overrides_persistent"
            ).fetchone()[0]
            # still_valid is explicit: staging tables lose column DEFAULTs
            # via sync_staging's CTAS (gotcha N), and the prod schema's
            # NOT NULL would trip on the NULL default at promote time.
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

    # Post-flight
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
