"""CP-5 Bundle B — Phase 1: entity tier inventory + Capital Group umbrella case study.

Phases:
  1.2 Per-tier counts (T1-T9)
  1.3 Capital Group umbrella probe + similar-firm survey (Wellington, Janus,
      Invesco, Federated, AB, Eaton Vance)
  1.4 Coverage gaps per tier (narrative-side; computes raw inputs)

Outputs:
  data/working/cp-5-bundle-b-tier-inventory.csv
  data/working/cp-5-bundle-b-umbrella-cohort.csv

Read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cp_5_bundle_b_common import (  # noqa: E402
    SENTINEL,
    WORKDIR,
    build_fund_to_tp,
    build_inst_to_tp,
    connect,
)


def phase_1_2_tier_inventory(con) -> pd.DataFrame:
    """Per-tier counts for T1-T9."""
    print("\n" + "=" * 80)
    print("Phase 1.2 — entity tier inventory")
    print("=" * 80)

    # T1 — top parent institutions (no inst-inst control parent)
    t1_q = con.execute(f"""
        SELECT COUNT(*) FROM entity_current ec
        WHERE ec.entity_type='institution'
          AND NOT EXISTS (
            SELECT 1 FROM entity_relationships er
            JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
            WHERE er.child_entity_id = ec.entity_id
              AND er.valid_to = {SENTINEL}
              AND er.control_type IN ('control','mutual','merge')
              AND pec.entity_type = 'institution'
          )
    """).fetchone()[0]

    # T2 — mid-level (has parent AND has children)
    t2_q = con.execute(f"""
        WITH has_parent AS (
          SELECT DISTINCT er.child_entity_id
          FROM entity_relationships er
          JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
          WHERE er.valid_to = {SENTINEL}
            AND er.control_type IN ('control','mutual','merge')
            AND pec.entity_type = 'institution'
        ),
        has_children AS (
          SELECT DISTINCT er.parent_entity_id
          FROM entity_relationships er
          JOIN entity_current cec ON cec.entity_id = er.child_entity_id
          WHERE er.valid_to = {SENTINEL}
            AND er.control_type IN ('control','mutual','merge')
            AND cec.entity_type = 'institution'
        )
        SELECT COUNT(*)
        FROM entity_current ec
        WHERE ec.entity_type='institution'
          AND ec.entity_id IN (SELECT child_entity_id FROM has_parent)
          AND ec.entity_id IN (SELECT parent_entity_id FROM has_children)
    """).fetchone()[0]

    # T3 + T4 + T5 — partition operating-AM and brands by holdings_v2 row count
    rowcounts = con.execute("""
        SELECT entity_id, COUNT(*) AS h13f_rows, SUM(market_value_usd)/1e9 AS h13f_aum_b
        FROM holdings_v2
        WHERE is_latest
        GROUP BY 1
    """).fetchdf()
    inst = con.execute(
        "SELECT entity_id FROM entity_current WHERE entity_type='institution'"
    ).fetchdf()
    inst = inst.merge(rowcounts, on="entity_id", how="left").fillna(
        {"h13f_rows": 0, "h13f_aum_b": 0}
    )

    # T3 — active 13F reporters (>= 100 rows of latest holdings)
    t3 = inst[inst["h13f_rows"] >= 100]

    # Brands: institutions in entity_aliases as alias_type='brand'
    brand_eids = con.execute(f"""
        SELECT DISTINCT entity_id FROM entity_aliases
        WHERE alias_type='brand' AND valid_to={SENTINEL}
    """).fetchdf()["entity_id"]
    brand_eids = set(brand_eids)

    # Compute fund-tier rollup AUM per top_parent (use Phase 0.5 helpers)
    inst_to_tp = build_inst_to_tp(con)
    fund_to_tp = build_fund_to_tp(con, inst_to_tp)
    con.register("fund_to_tp_df", fund_to_tp[["fund_entity_id", "top_parent_entity_id"]])
    fund_aum_by_tp = con.execute(f"""
        SELECT ftp.top_parent_entity_id AS entity_id,
               SUM(fh.market_value_usd)/1e9 AS fund_tier_aum_b
        FROM fund_holdings_v2 fh
        JOIN fund_to_tp_df ftp ON ftp.fund_entity_id = fh.entity_id
        WHERE fh.is_latest AND fh.quarter='2025Q4' AND fh.asset_category='EC'
        GROUP BY 1
    """).fetchdf()
    inst = inst.merge(fund_aum_by_tp, on="entity_id", how="left").fillna({"fund_tier_aum_b": 0})

    # T4 — operating IA non-reporting: zero holdings_v2 rows but fund_tier > 0
    t4 = inst[(inst["h13f_rows"] == 0) & (inst["fund_tier_aum_b"] > 0)]

    # T5 — brand: zero holdings_v2 rows AND in brand alias table
    t5 = inst[(inst["h13f_rows"] == 0) & (inst["entity_id"].isin(brand_eids))]

    # T6 — sub-adviser via ncen_adviser_map. Linkage requires CIK match
    # (ncen_adviser_map.adviser_crd ⇄ entity_identifiers.crd is the cleanest;
    # here we count distinct adviser CIKs that map to an institution eid).
    sub_adv_distinct_advisers = con.execute(f"""
        SELECT COUNT(DISTINCT adviser_crd)
        FROM ncen_adviser_map
        WHERE valid_to = {SENTINEL} AND role IN ('sub_adviser','subadviser','sub-adviser')
    """).fetchone()[0]
    sub_adv_resolved = con.execute(f"""
        WITH adv AS (
          SELECT DISTINCT adviser_crd
          FROM ncen_adviser_map
          WHERE valid_to = {SENTINEL} AND role IN ('sub_adviser','subadviser','sub-adviser')
            AND adviser_crd IS NOT NULL AND adviser_crd <> ''
        )
        SELECT COUNT(DISTINCT ei.entity_id)
        FROM adv
        JOIN entity_identifiers ei
          ON ei.identifier_type='crd' AND ei.identifier_value = adv.adviser_crd
         AND ei.valid_to = {SENTINEL}
    """).fetchone()[0]

    # T7 — fund-typed entities
    t7 = con.execute(
        "SELECT COUNT(*) FROM entity_current WHERE entity_type='fund'"
    ).fetchone()[0]

    # T8 — share class: not currently broken out (placeholder count)
    t8 = 0

    # T9 — holdings rows (latest only)
    t9_h13f = con.execute(
        "SELECT COUNT(*) FROM holdings_v2 WHERE is_latest"
    ).fetchone()[0]
    t9_fund = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest"
    ).fetchone()[0]

    rows = [
        {"tier": "T1", "label": "top parent (no inst parent)", "n": t1_q, "aum_exposure_b": ""},
        {"tier": "T2", "label": "mid-level holding (has parent + children)", "n": t2_q, "aum_exposure_b": ""},
        {"tier": "T3", "label": "operating IA reporting (>=100 holdings_v2 rows)",
         "n": int(len(t3)), "aum_exposure_b": round(t3["h13f_aum_b"].sum(), 1)},
        {"tier": "T4", "label": "operating IA non-reporting (0 holdings, fund-tier>0 as TP)",
         "n": int(len(t4)), "aum_exposure_b": round(t4["fund_tier_aum_b"].sum(), 1)},
        {"tier": "T5", "label": "brand (alias_type='brand', 0 holdings_v2 rows)",
         "n": int(len(t5)), "aum_exposure_b": ""},
        {"tier": "T6a", "label": "sub-adviser (distinct adviser_crd)", "n": int(sub_adv_distinct_advisers), "aum_exposure_b": ""},
        {"tier": "T6b", "label": "sub-adviser resolved to entity (via crd)", "n": int(sub_adv_resolved), "aum_exposure_b": ""},
        {"tier": "T7", "label": "fund series (entity_type='fund')", "n": int(t7), "aum_exposure_b": ""},
        {"tier": "T8", "label": "share class (not broken out — placeholder)", "n": t8, "aum_exposure_b": ""},
        {"tier": "T9a", "label": "holdings_v2 latest rows", "n": int(t9_h13f), "aum_exposure_b": ""},
        {"tier": "T9b", "label": "fund_holdings_v2 latest rows", "n": int(t9_fund), "aum_exposure_b": ""},
    ]
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    df.to_csv(WORKDIR / "cp-5-bundle-b-tier-inventory.csv", index=False)
    print(f"\nWrote {WORKDIR / 'cp-5-bundle-b-tier-inventory.csv'}")
    return df


def phase_1_3_umbrella(con) -> pd.DataFrame:
    """Capital Group umbrella + similar-firm survey."""
    print("\n" + "=" * 80)
    print("Phase 1.3 — umbrella case study (Capital Group + 6 similar firms)")
    print("=" * 80)

    # Targeted seeds: known canonical eids per family (Bundle A + cp-5-discovery
    # references). Avoids broad name-search noise like "Crescent Capital Group"
    # matching the Capital Group label.
    family_seed_eids = {
        "Capital Group": [12, 6657, 7136, 7125],   # umbrella + 3 filer arms
        "Wellington Management": [11220, 9935],
        "Janus Henderson": [51, 1399, 9192, 11231],
        "Invesco": [4, 569, 9297],
        "Federated Hermes": [4635, 18926],
        "AllianceBernstein": [57, 8497, 17917, 18762],
        "Eaton Vance": [19, 8459, 17940, 5282],
    }
    families = {}  # not used, kept for legacy variable but skipped
    rows_combined: list[dict] = []

    inst_to_tp = build_inst_to_tp(con)

    rows = []
    for family_label, eid_list in family_seed_eids.items():
        eid_csv = ", ".join(str(e) for e in eid_list)
        cand = con.execute(f"""
            SELECT entity_id, entity_type, display_name
            FROM entity_current
            WHERE entity_id IN ({eid_csv})
            ORDER BY entity_id
        """).fetchdf()

        for _, r in cand.iterrows():
            eid = int(r["entity_id"])
            # Top parent + has children?
            tp_row = inst_to_tp[inst_to_tp["entity_id"] == eid]
            tp = int(tp_row["top_parent_entity_id"].iloc[0]) if len(tp_row) else eid
            tp_name = con.execute(
                f"SELECT display_name FROM entity_current WHERE entity_id={tp}"
            ).fetchone()
            tp_name = tp_name[0] if tp_name else None

            # holdings_v2 footprint
            h13f_rows = con.execute(
                f"SELECT COUNT(*), SUM(market_value_usd)/1e9 FROM holdings_v2 "
                f"WHERE is_latest AND entity_id={eid}"
            ).fetchone()

            # number of inst-inst children (own subsidiaries)
            n_children = con.execute(f"""
                SELECT COUNT(*) FROM entity_relationships er
                JOIN entity_current cec ON cec.entity_id = er.child_entity_id
                WHERE er.parent_entity_id = {eid}
                  AND er.valid_to = {SENTINEL}
                  AND er.control_type IN ('control','mutual','merge')
                  AND cec.entity_type = 'institution'
            """).fetchone()[0]

            # alias / brand info
            alias_types = con.execute(f"""
                SELECT alias_type, COUNT(*) FROM entity_aliases
                WHERE entity_id={eid} AND valid_to={SENTINEL}
                GROUP BY 1 ORDER BY 1
            """).fetchall()
            alias_summary = ";".join(f"{t}:{n}" for t, n in alias_types) or "(none)"

            rows.append({
                "family": family_label,
                "entity_id": eid,
                "display_name": r["display_name"],
                "top_parent_entity_id": tp,
                "top_parent_name": tp_name,
                "is_self_top_parent": (tp == eid),
                "n_inst_children": int(n_children),
                "h13f_rows": int(h13f_rows[0] or 0),
                "h13f_aum_b": round(h13f_rows[1] or 0, 2),
                "alias_summary": alias_summary,
            })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv(WORKDIR / "cp-5-bundle-b-umbrella-cohort.csv", index=False)
    print(f"\nWrote {WORKDIR / 'cp-5-bundle-b-umbrella-cohort.csv'}")

    # Frequency / pattern summary
    print("\n  Pattern analysis per family:")
    for family in family_seed_eids:
        sub = df[df["family"] == family]
        if sub.empty:
            print(f"    {family}: NO MATCH")
            continue
        # Are the top-parents the same across all candidate eids? Or distinct?
        unique_tp = sub["top_parent_entity_id"].nunique()
        n_filer_arms = (sub["h13f_rows"] >= 100).sum()
        n_brand_only = (sub["h13f_rows"] == 0).sum()
        print(
            f"    {family}: {len(sub)} eids, "
            f"{unique_tp} distinct top_parents, "
            f"{n_filer_arms} active filer arms (>=100 rows), "
            f"{n_brand_only} brand-only/no-13F"
        )
    return df


def main() -> int:
    con = connect()
    WORKDIR.mkdir(parents=True, exist_ok=True)
    phase_1_2_tier_inventory(con)
    phase_1_3_umbrella(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
