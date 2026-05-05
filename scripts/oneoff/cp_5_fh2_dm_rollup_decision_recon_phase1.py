"""CP-5 fh2.dm_rollup decision recon — Phase 1.

Read-only investigation. Quantifies the live drift between Method A
(read-time entity_rollup_history JOIN) and Method B (denormalized
fund_holdings_v2.dm_rollup_entity_id) across the top 50 top-parents
by combined fund_holdings_v2 AUM. Confirms SSGA-class drift
(documented in cp-5-bundle-c-discovery.md §7.1) and surfaces any
other firms with material drift.

Outputs:
  data/working/cp-5-fh2-dm-rollup-drift.csv

Refs:
  docs/findings/cp-5-bundle-c-discovery.md §7.1, §7.5
  scripts/oneoff/cp_5_coverage_matrix_revalidation.py (Method A pattern)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
ROLLUP_TYPE_CANONICAL = "decision_maker_v1"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")
COVERAGE_QUARTER = "2025Q4"

REPO = Path(__file__).resolve().parents[2]
WORKDIR = REPO / "data" / "working"


def build_inst_to_top_parent(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cycle-safe institution→top-parent climb. Mirrors
    scripts/oneoff/cp_5_coverage_matrix_revalidation.py:38-79."""
    types_sql = ", ".join(f"'{t}'" for t in ROLLUP_CTRL_TYPES)
    edges = con.execute(f"""
        SELECT er.child_entity_id, er.parent_entity_id
        FROM entity_relationships er
        JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
        JOIN entity_current cec ON cec.entity_id = er.child_entity_id
        WHERE er.valid_to = {SENTINEL}
          AND er.control_type IN ({types_sql})
          AND pec.entity_type = 'institution'
          AND cec.entity_type = 'institution'
    """).fetchdf()
    edges = edges.sort_values(["child_entity_id", "parent_entity_id"]).drop_duplicates(
        "child_entity_id", keep="first"
    )
    edge_map = dict(zip(edges["child_entity_id"], edges["parent_entity_id"]))

    seed = con.execute("""
        SELECT entity_id FROM entity_current WHERE entity_type = 'institution'
    """).fetchdf()
    cur = {ent: ent for ent in seed["entity_id"]}
    visited = {ent: {ent} for ent in cur}
    cycles = set()
    for _ in range(20):
        changed = 0
        for ent, tp in list(cur.items()):
            if ent in cycles:
                continue
            nxt = edge_map.get(tp)
            if nxt is None or nxt == tp:
                continue
            if nxt in visited[ent]:
                cycles.add(ent)
                continue
            visited[ent].add(nxt)
            cur[ent] = nxt
            changed += 1
        if changed == 0:
            break
    return pd.DataFrame({
        "institution_entity_id": list(cur.keys()),
        "top_parent_entity_id": list(cur.values()),
    })


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB_PATH, read_only=True)

    # === Step 1a — column population status ===
    print("=" * 78)
    print("PHASE 1a — column population status (fund_holdings_v2)")
    print("=" * 78)
    pop = con.execute("""
        SELECT
          COUNT(*) AS total_rows,
          COUNT(dm_rollup_entity_id) AS dm_rollup_eid_populated,
          COUNT(dm_rollup_name)      AS dm_rollup_name_populated,
          COUNT(*) FILTER (WHERE dm_rollup_entity_id IS NULL
                           AND dm_rollup_name IS NOT NULL) AS name_only_no_eid,
          COUNT(*) FILTER (WHERE dm_rollup_entity_id IS NOT NULL
                           AND dm_rollup_name IS NULL) AS eid_only_no_name,
          COUNT(*) FILTER (WHERE is_latest = TRUE) AS is_latest_rows
        FROM fund_holdings_v2
    """).fetchone()
    print(f"  total_rows               : {pop[0]:>15,}")
    print(f"  dm_rollup_eid_populated  : {pop[1]:>15,} ({pop[1]/max(pop[0],1)*100:.2f}%)")
    print(f"  dm_rollup_name_populated : {pop[2]:>15,} ({pop[2]/max(pop[0],1)*100:.2f}%)")
    print(f"  name_only_no_eid         : {pop[3]:>15,}")
    print(f"  eid_only_no_name         : {pop[4]:>15,}")
    print(f"  is_latest_rows           : {pop[5]:>15,} ({pop[5]/max(pop[0],1)*100:.2f}%)")

    # === Step 1c — is_latest=FALSE breakdown ===
    print()
    print("=" * 78)
    print("PHASE 1c — is_latest=FALSE rows (historical SCD-closed)")
    print("=" * 78)
    hist = con.execute("""
        SELECT
          COUNT(*) AS not_latest_rows,
          COUNT(dm_rollup_entity_id) AS not_latest_dm_pop,
          COUNT(dm_rollup_name)      AS not_latest_name_pop
        FROM fund_holdings_v2
        WHERE is_latest = FALSE
    """).fetchone()
    print(f"  is_latest=FALSE rows     : {hist[0]:>15,}")
    print(f"    dm_rollup_eid pop      : {hist[1]:>15,} ({hist[1]/max(hist[0],1)*100:.2f}%)")
    print(f"    dm_rollup_name pop     : {hist[2]:>15,} ({hist[2]/max(hist[0],1)*100:.2f}%)")

    # === Step 1b — drift quantification ===
    print()
    print("=" * 78)
    print(f"PHASE 1b — drift quantification (top 50 top-parents by combined AUM, "
          f"is_latest=TRUE, {COVERAGE_QUARTER})")
    print("=" * 78)

    inst_to_tp = build_inst_to_top_parent(con)
    con.register("inst_to_tp", inst_to_tp)
    print(f"  inst_to_tp size: {len(inst_to_tp):,} institutions")

    # Method A: live ERH JOIN at read time (rollup_type filter applied)
    method_a = con.execute(f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id           AS fund_entity_id,
                 erh.rollup_entity_id    AS dm_rollup_eid_a
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT
          COALESCE(itp.top_parent_entity_id, dr.dm_rollup_eid_a) AS top_parent_eid,
          SUM(fh.market_value_usd) AS aum_method_a
        FROM fund_holdings_v2 fh
        LEFT JOIN dm_rollup dr  ON dr.fund_entity_id = fh.entity_id
        LEFT JOIN inst_to_tp itp ON itp.institution_entity_id = dr.dm_rollup_eid_a
        WHERE fh.is_latest = TRUE
          AND fh.market_value_usd IS NOT NULL
        GROUP BY top_parent_eid
    """).fetchdf()

    # Method B: denormalized fh.dm_rollup_entity_id read at row time
    method_b = con.execute(f"""
        SELECT
          COALESCE(itp.top_parent_entity_id, fh.dm_rollup_entity_id) AS top_parent_eid,
          SUM(fh.market_value_usd) AS aum_method_b
        FROM fund_holdings_v2 fh
        LEFT JOIN inst_to_tp itp ON itp.institution_entity_id = fh.dm_rollup_entity_id
        WHERE fh.is_latest = TRUE
          AND fh.market_value_usd IS NOT NULL
        GROUP BY top_parent_eid
    """).fetchdf()

    drift = method_a.merge(method_b, on="top_parent_eid", how="outer").fillna(0.0)
    drift["delta_aum"] = drift["aum_method_a"] - drift["aum_method_b"]
    drift["abs_delta_aum"] = drift["delta_aum"].abs()
    drift["combined_aum"] = drift["aum_method_a"] + drift["aum_method_b"]

    # Resolve names
    name_lookup = con.execute("""
        SELECT entity_id, display_name FROM entity_current
    """).fetchdf()
    drift = drift.merge(
        name_lookup.rename(columns={"entity_id": "top_parent_eid"}),
        on="top_parent_eid", how="left",
    )

    # Top 50 by combined AUM
    drift_top = drift.sort_values("combined_aum", ascending=False).head(50).copy()
    drift_top["aum_method_a_b"] = (drift_top["aum_method_a"] / 1e9).round(2)
    drift_top["aum_method_b_b"] = (drift_top["aum_method_b"] / 1e9).round(2)
    drift_top["delta_aum_b"]    = (drift_top["delta_aum"]   / 1e9).round(2)
    drift_top["delta_pct"]      = (drift_top["delta_aum"]   /
                                   drift_top["aum_method_a"].where(
                                       drift_top["aum_method_a"] != 0)).round(4)

    out_df = drift_top[[
        "top_parent_eid", "display_name",
        "aum_method_a_b", "aum_method_b_b",
        "delta_aum_b", "delta_pct",
    ]].rename(columns={"display_name": "top_parent_name"})

    out_path = WORKDIR / "cp-5-fh2-dm-rollup-drift.csv"
    out_df.to_csv(out_path, index=False)
    print(f"\n  Wrote {out_path} ({len(out_df)} rows)")

    print("\n  Top 25 top-parents by |delta_aum|:")
    top25 = drift.sort_values("abs_delta_aum", ascending=False).head(25).copy()
    for _, r in top25.iterrows():
        nm = r["display_name"] if isinstance(r["display_name"], str) else "(no-name)"
        print(f"    eid={int(r['top_parent_eid']) if pd.notna(r['top_parent_eid']) else 'NaN':>6} "
              f"{nm[:45]:<45} "
              f"A=${r['aum_method_a']/1e9:>9,.2f}B "
              f"B=${r['aum_method_b']/1e9:>9,.2f}B "
              f"Δ=${r['delta_aum']/1e9:>9,.2f}B")

    # Per-fund alignment check (replicate Bundle C §7.1 metric)
    print()
    print("  Per-fund alignment (active 2025Q4 funds: dm_rollup_eid Method A vs Method B):")
    aligned = con.execute(f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id, erh.rollup_entity_id
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        ),
        per_fund AS (
          SELECT DISTINCT fh.entity_id,
                 fh.dm_rollup_entity_id    AS method_b_eid,
                 dr.rollup_entity_id       AS method_a_eid
          FROM fund_holdings_v2 fh
          LEFT JOIN dm_rollup dr ON dr.entity_id = fh.entity_id
          WHERE fh.is_latest = TRUE
            AND fh.entity_id IS NOT NULL
        )
        SELECT
          COUNT(*) AS n_funds,
          SUM(CASE WHEN method_a_eid IS NOT DISTINCT FROM method_b_eid
                   THEN 1 ELSE 0 END) AS n_aligned,
          SUM(CASE WHEN method_a_eid IS DISTINCT FROM method_b_eid
                   THEN 1 ELSE 0 END) AS n_diverged
        FROM per_fund
    """).fetchone()
    print(f"    n_funds   : {aligned[0]:>8,}")
    print(f"    n_aligned : {aligned[1]:>8,}  ({aligned[1]/max(aligned[0],1)*100:.2f}%)")
    print(f"    n_diverged: {aligned[2]:>8,}  ({aligned[2]/max(aligned[0],1)*100:.2f}%)")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
