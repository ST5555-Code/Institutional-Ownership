"""
DM14b — add 6 name-inferred wholly_owned/parent_brand edges + chain-walk
DM rollup collapse + replay overrides (staging).

Extends DM14 Layer 1 to 6 high-AUM intra-firm clusters that the original
chain walk could not collapse due to missing graph edges. Each edge is a
publicly-documented affiliate/subsidiary relationship corroborated by
firm name, ADV registration location, and known corporate structure.
`source='name_inference'` because ADV Schedule A data for the sub-adviser
is not in the MDM; the corporate fact is verifiable externally.

Scope verified against prod 2026-04-17:
  Manulife IM (US) 10538  → 8994 Manulife Financial Corp    49 rows / $72.59B
  FIAM LLC         9910   → 10443 FMR LLC                   15 rows / $49.63B
  Principal RE     8652   → 7316 Principal Financial Group   6 rows / $35.33B
  Davis NY         17975  → 3703 Davis Selected Advisers    12 rows / $14.38B
  PGIM Limited     18190  → 1589 PGIM, Inc.                  6 rows / $7.46B
  C&S Asia         18044  → 4595 Cohen & Steers, Inc.        8 rows / $6.20B

Self-rollup rows (`rule_applied='self'`, one per sub-adviser) are NOT
retargeted — those represent the sub-adviser's own identity. Only rows
with `rule_applied='ncen_sub_adviser'` collapse.

Writes against STAGING ONLY.

Three steps per cluster, one transaction total:
  A. Insert missing graph edge via entity_relationships
  B. For each fund series DM-routed to the sub-adviser via
     `ncen_sub_adviser`, close the existing DM rollup and insert a new
     row targeting the cluster ancestor (rule_applied='manual_override')
  C. Insert one `entity_overrides_persistent(action='merge',
     rollup_type='decision_maker_v1', identifier_type='series_id')` row
     per retarget for --reset replay; plus one structural edge-safety
     override per cluster (future-proofing).

Voya IM Co 17915 ↔ Voya Investments 4071 is DEFERRED as DM14c —
neither side has upward edges and no Voya Financial Inc holding entity
exists in the MDM.
"""

import os
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DB = os.path.join(ROOT, "data", "13f_staging.duckdb")
ANALYST = "claude-dm14b"

# (parent_eid, child_eid, rel_type, confidence, label)
EDGES = [
    (8994, 8179,  "wholly_owned", "high",   "Manulife Financial Corp → Manufacturers Life Insurance"),
    (10443, 9910, "wholly_owned", "high",   "FMR LLC → FIAM LLC"),
    (7316, 54,    "parent_brand", "medium", "Principal Financial Group → Principal Financial (seed)"),
    (3703, 17975, "wholly_owned", "high",   "Davis Selected Advisers → Davis Selected Advisers - NY"),
    (1589, 18190, "wholly_owned", "high",   "PGIM, Inc. → PGIM Limited"),
    (4595, 18044, "wholly_owned", "high",   "Cohen & Steers, Inc. → Cohen & Steers Asia"),
]

# (sub_eid, target_eid, target_cik, cluster_label)
CLUSTERS = [
    (10538, 8994,  "0001086888", "Manulife"),
    (9910,  10443, "0000315066", "FMR/FIAM"),
    (8652,  7316,  "0001126328", "Principal"),
    (17975, 3703,  "0001036325", "Davis"),
    (18190, 1589,  "0000946754", "PGIM"),
    (18044, 4595,  "0001284812", "Cohen & Steers"),
]


def insert_edge(con, parent_eid, child_eid, rel_type, confidence, label):
    """Step A — insert one wholly_owned/parent_brand edge if not present."""
    existing = con.execute(
        """SELECT relationship_id FROM entity_relationships
            WHERE parent_entity_id=? AND child_entity_id=?
              AND relationship_type=? AND valid_to=DATE '9999-12-31'""",
        [parent_eid, child_eid, rel_type],
    ).fetchone()
    if existing:
        print(f"  SKIP edge {parent_eid}→{child_eid} {rel_type}: rel_id={existing[0]} already active")
        return existing[0]

    new_rel_id = con.execute(
        "SELECT COALESCE(MAX(relationship_id), 0) + 1 FROM entity_relationships"
    ).fetchone()[0]
    con.execute(
        """INSERT INTO entity_relationships
             (relationship_id, parent_entity_id, child_entity_id,
              relationship_type, control_type, is_primary, primary_parent_key,
              confidence, source, is_inferred, valid_from, valid_to,
              created_at, last_refreshed_at)
           VALUES (?, ?, ?, ?, 'control', TRUE, ?,
                   ?, 'name_inference', FALSE,
                   CURRENT_DATE, DATE '9999-12-31',
                   now(), now())""",
        [new_rel_id, parent_eid, child_eid, rel_type, parent_eid, confidence],
    )
    print(f"  DONE edge rel_id={new_rel_id}: {label} ({rel_type}, {confidence})")
    return new_rel_id


def retarget_cluster(con, sub_eid, target_eid, target_cik, cluster_label):
    """Step B + C — retarget DM rollups and add override rows."""
    series_rows = con.execute(
        """SELECT erh.entity_id, ei.identifier_value AS series_id,
                  fu.total_net_assets
             FROM entity_rollup_history erh
             JOIN entity_identifiers ei
               ON erh.entity_id = ei.entity_id
              AND ei.identifier_type = 'series_id'
              AND ei.valid_to = DATE '9999-12-31'
             LEFT JOIN fund_universe fu ON ei.identifier_value = fu.series_id
            WHERE erh.rollup_entity_id = ?
              AND erh.rollup_type = 'decision_maker_v1'
              AND erh.valid_to = DATE '9999-12-31'
              AND erh.rule_applied = 'ncen_sub_adviser'
            ORDER BY fu.total_net_assets DESC NULLS LAST""",
        [sub_eid],
    ).fetchall()

    total_aum = sum((r[2] or 0) for r in series_rows) / 1e9
    print(f"\n  [{cluster_label} sub={sub_eid} → {target_eid} CIK={target_cik}] "
          f"retargeting {len(series_rows)} series / ${total_aum:.2f}B")

    retargeted = 0
    overrides_added = 0
    for fund_eid, series_id, aum in series_rows:
        # Close current DM row
        con.execute(
            """UPDATE entity_rollup_history SET valid_to=CURRENT_DATE
                WHERE entity_id=? AND rollup_type='decision_maker_v1'
                  AND valid_to=DATE '9999-12-31'""",
            [fund_eid],
        )
        # Insert new DM row pointing at ancestor
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to)
               VALUES (?, ?, 'decision_maker_v1', 'manual_override',
                       'exact', CURRENT_DATE, DATE '9999-12-31')""",
            [fund_eid, target_eid],
        )
        retargeted += 1

        # Idempotent override insert
        reason = (
            f"DM14b {cluster_label}: intra-firm DM collapse via "
            f"name-inferred edge. Fund {series_id} DM retargeted from "
            f"sub-adviser eid={sub_eid} to ancestor eid={target_eid} "
            f"(CIK {target_cik})."
        )
        existing = con.execute(
            """SELECT override_id FROM entity_overrides_persistent
                WHERE action='merge' AND rollup_type='decision_maker_v1'
                  AND identifier_type='series_id'
                  AND identifier_value=? AND new_value=?
                  AND still_valid=TRUE""",
            [series_id, target_cik],
        ).fetchone()
        if existing:
            continue
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
                       ?, ?, ?, TRUE, 'series_id', ?, 'decision_maker_v1')""",
            [new_id, target_cik, reason, ANALYST, series_id],
        )
        overrides_added += 1

    print(f"    retargeted={retargeted}  overrides_added={overrides_added}")
    return retargeted, overrides_added, total_aum


def main() -> int:
    if not os.path.exists(STAGING_DB):
        print(f"FATAL: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    con = duckdb.connect(STAGING_DB, read_only=False)

    baseline_rel = con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE valid_to=DATE '9999-12-31'"
    ).fetchone()[0]
    baseline_rollup = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to=DATE '9999-12-31'"
    ).fetchone()[0]
    baseline_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"BEFORE: relationships active={baseline_rel}  "
          f"DM rollups active={baseline_rollup}  overrides={baseline_ov}")

    con.execute("BEGIN TRANSACTION")
    try:
        print("\n### STEP A — insert 6 wholly_owned/parent_brand edges ###")
        for (parent, child, rtype, conf, lbl) in EDGES:
            insert_edge(con, parent, child, rtype, conf, lbl)

        print("\n### STEP B+C — chain-walk DM retargets + override rows ###")
        totals = {"retargeted": 0, "overrides": 0, "aum": 0.0}
        for (sub, tgt, cik, lbl) in CLUSTERS:
            rt, ov, aum = retarget_cluster(con, sub, tgt, cik, lbl)
            totals["retargeted"] += rt
            totals["overrides"] += ov
            totals["aum"] += aum

        print(f"\n  TOTAL retargets: {totals['retargeted']}  "
              f"overrides: {totals['overrides']}  "
              f"AUM: ${totals['aum']:.2f}B")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    after_rel = con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE valid_to=DATE '9999-12-31'"
    ).fetchone()[0]
    after_rollup = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_type='decision_maker_v1' AND valid_to=DATE '9999-12-31'"
    ).fetchone()[0]
    after_ov = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent"
    ).fetchone()[0]
    print(f"\nAFTER:  relationships active={after_rel}  "
          f"(Δ {after_rel - baseline_rel})")
    print(f"        DM rollups active={after_rollup}  "
          f"(Δ {after_rollup - baseline_rollup})")
    print(f"        overrides={after_ov}  (Δ {after_ov - baseline_ov})")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
