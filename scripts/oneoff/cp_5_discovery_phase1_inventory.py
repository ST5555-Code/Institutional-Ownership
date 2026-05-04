"""CP-5 discovery — Phase 1: top-parent inventory + form coverage profile.

Read-only investigation. Enumerates top-parent institutions, traces every
institution to its top parent via entity_relationships (control/mutual/merge),
links every fund to a top parent via entity_rollup_history → institution →
top-parent, and computes per-top-parent 13F vs fund-tier AUM coverage.

Outputs:
  data/working/cp-5-top-parent-coverage-matrix.csv
  scripts/oneoff/_cp5_inst_to_topparent.parquet (working artifact for Phase 2)

Refs ROADMAP CP-5 entry, docs/findings/institution_scoping.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"

# is_latest=TRUE holds multi-period rows in both tables (holdings_v2: 4Q rolling;
# fund_holdings_v2: 6Q rolling with bulk in latest). For point-in-time coverage,
# pin to 2025Q4 — the latest quarter both tables fully populate.
COVERAGE_QUARTER = "2025Q4"

# Institution-to-institution rollup control_types. Plan-original 'beneficial'
# does not exist in this schema; actual values dominated by 'control' (370
# inst-inst), with 'mutual' (23) and 'merge' (2) as additional cases. Pure
# IA-to-fund 'advisory' rows are excluded from the institution chain.
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    sentinel_count = con.execute(
        f"SELECT COUNT(*) FROM entity_relationships WHERE valid_to = {SENTINEL}"
    ).fetchone()[0]
    if sentinel_count == 0:
        print("ABORT: entity_relationships sentinel missing", file=sys.stderr)
        return 2
    print(f"entity_relationships open rows: {sentinel_count:,}")

    # === Step 1a — top-parent enumeration ===
    types_sql = ", ".join(f"'{t}'" for t in ROLLUP_CTRL_TYPES)
    top_parent_sql = f"""
    WITH ec_uniq AS (
        SELECT entity_id, ANY_VALUE(display_name) AS display_name,
               ANY_VALUE(entity_type) AS entity_type
        FROM entity_current GROUP BY entity_id
    ),
    has_inst_parent AS (
        SELECT DISTINCT er.child_entity_id AS eid
        FROM entity_relationships er
        JOIN ec_uniq pec ON pec.entity_id = er.parent_entity_id
        JOIN ec_uniq cec ON cec.entity_id = er.child_entity_id
        WHERE er.valid_to = {SENTINEL}
          AND er.control_type IN ({types_sql})
          AND pec.entity_type = 'institution'
          AND cec.entity_type = 'institution'
    )
    SELECT ec.entity_id,
           ec.display_name AS canonical_name
    FROM ec_uniq ec
    LEFT JOIN has_inst_parent hip ON hip.eid = ec.entity_id
    WHERE ec.entity_type = 'institution'
      AND hip.eid IS NULL
    """
    top_parents = con.execute(top_parent_sql).fetchdf()
    print(f"\n=== Step 1a — top-parent institutions ===")
    print(f"  total: {len(top_parents):,}")
    print(f"  sample:\n{top_parents.head(5).to_string()}")

    # === Step 1b — institution → top_parent climb (iterative) ===
    # Seed: every institution starts pointing to itself
    inst_seed_sql = """
    SELECT entity_id, entity_id AS top_parent_entity_id, 0 AS hop_count
    FROM entity_current
    WHERE entity_type = 'institution'
    """
    climb = con.execute(inst_seed_sql).fetchdf()
    initial = len(climb)
    print(f"\n=== Step 1b — institution top-parent climb ===")
    print(f"  seed institutions: {initial:,}")

    # Build edge map: child → parent (only inst-inst rollup edges)
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
    print(f"  inst-inst rollup edges: {len(edges):,}")

    # Multi-edge detection (multiple parents per child)
    multi_parent = edges.groupby("child_entity_id").size()
    n_multi = (multi_parent > 1).sum()
    if n_multi > 0:
        print(f"  WARNING: {n_multi} children have multiple parents (picking deterministic min)")
        # Deterministic: keep min parent_entity_id per child
        edges = edges.sort_values(["child_entity_id", "parent_entity_id"]).drop_duplicates("child_entity_id", keep="first")

    edge_map = dict(zip(edges["child_entity_id"], edges["parent_entity_id"]))

    # Iterative climb in pandas
    max_hops = 20
    cur = climb.set_index("entity_id")["top_parent_entity_id"].to_dict()
    hop = climb.set_index("entity_id")["hop_count"].to_dict()
    visited = {ent: {ent} for ent in cur}
    cycles = set()
    for h in range(1, max_hops + 1):
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
            hop[ent] = h
            changed += 1
        if changed == 0:
            break
    print(f"  converged after {h} iterations (max_hops={max_hops})")
    if cycles:
        print(f"  entities in cycle (path repeats): {len(cycles)}")

    inst_to_tp = pd.DataFrame({
        "entity_id": list(cur.keys()),
        "top_parent_entity_id": list(cur.values()),
    })
    inst_to_tp["hop_count"] = inst_to_tp["entity_id"].map(hop).fillna(0).astype(int)
    print(f"  hop distribution:")
    for hopn, n in inst_to_tp["hop_count"].value_counts().sort_index().items():
        print(f"    hop={hopn}: {n:,}")
    max_h = inst_to_tp["hop_count"].max()
    print(f"  max hop_count: {max_h}")

    # Orphans: institutions whose top-parent is themselves AND have no children claiming them
    # (i.e., truly standalone — visible)
    standalone = (inst_to_tp["entity_id"] == inst_to_tp["top_parent_entity_id"]) & \
                 (~inst_to_tp["entity_id"].isin(edges["parent_entity_id"]))
    print(f"  standalone institutions (no parent, no children): {standalone.sum():,}")

    # === Step 1c — fund → top-parent ===
    fund_chain_sql = f"""
    SELECT erh.entity_id AS fund_entity_id,
           erh.rollup_entity_id AS institution_entity_id
    FROM entity_rollup_history erh
    JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
    WHERE erh.valid_to = {SENTINEL}
      AND ec_f.entity_type = 'fund'
    """
    fund_chain = con.execute(fund_chain_sql).fetchdf()
    fund_chain = fund_chain.merge(
        inst_to_tp[["entity_id", "top_parent_entity_id"]].rename(
            columns={"entity_id": "institution_entity_id"}
        ),
        on="institution_entity_id", how="left"
    )
    n_fund_no_tp = fund_chain["top_parent_entity_id"].isna().sum()
    print(f"\n=== Step 1c — fund → top-parent ===")
    print(f"  total fund→institution rollup rows: {len(fund_chain):,}")
    print(f"  funds without resolved top-parent: {n_fund_no_tp:,}")
    funds_per_tp = fund_chain.groupby("top_parent_entity_id").size().sort_values(ascending=False)
    print(f"  top-50 top-parents by fund count:")
    top50_funds = funds_per_tp.head(50)
    ec_names = con.execute("""
        SELECT entity_id, display_name AS name
        FROM entity_current WHERE entity_type='institution'
    """).fetchdf().set_index("entity_id")["name"].to_dict()
    for tp_id, n in top50_funds.items():
        print(f"    {ec_names.get(int(tp_id), '?'):>50s}  funds={n}")

    # === Step 1d — per-top-parent form coverage ===
    print(f"\n=== Step 1d — form coverage matrix (per top-parent) ===")
    # Register working frames in DuckDB for join
    con.register("inst_to_tp_df", inst_to_tp)
    con.register("fund_chain_df", fund_chain)

    # 13F AUM by top-parent (point-in-time = COVERAGE_QUARTER)
    h13f_sql = f"""
    SELECT itp.top_parent_entity_id,
           SUM(h.market_value_usd) / 1e9 AS thirteen_f_aum_billions
    FROM holdings_v2 h
    JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
    WHERE h.is_latest = TRUE
      AND h.quarter = '{COVERAGE_QUARTER}'
    GROUP BY 1
    """
    h13f = con.execute(h13f_sql).fetchdf()

    # Fund-tier AUM by top-parent (point-in-time, equity only for apples-to-apples)
    fund_aum_sql = f"""
    SELECT fc.top_parent_entity_id,
           SUM(fh.market_value_usd) / 1e9 AS fund_tier_aum_billions
    FROM fund_holdings_v2 fh
    JOIN fund_chain_df fc ON fc.fund_entity_id = fh.entity_id
    WHERE fh.is_latest = TRUE
      AND fh.quarter = '{COVERAGE_QUARTER}'
      AND fh.asset_category = 'EC'
    GROUP BY 1
    """
    fund_aum = con.execute(fund_aum_sql).fetchdf()

    # n_funds and n_inst_subsidiaries per top-parent
    n_funds_per_tp = fund_chain.groupby("top_parent_entity_id").size().reset_index(name="n_funds_under")
    n_inst_per_tp = inst_to_tp.groupby("top_parent_entity_id").size().reset_index(name="n_inst_subsidiaries")

    # Merge into coverage frame
    cov = top_parents.rename(columns={"entity_id": "top_parent_entity_id",
                                       "canonical_name": "top_parent_canonical_name"})
    cov = cov.merge(h13f, on="top_parent_entity_id", how="left")
    cov = cov.merge(fund_aum, on="top_parent_entity_id", how="left")
    cov["thirteen_f_aum_billions"] = cov["thirteen_f_aum_billions"].fillna(0)
    cov["fund_tier_aum_billions"] = cov["fund_tier_aum_billions"].fillna(0)
    cov["combined_aum_billions"] = cov["thirteen_f_aum_billions"] + cov["fund_tier_aum_billions"]
    cov = cov.merge(n_funds_per_tp, on="top_parent_entity_id", how="left").fillna({"n_funds_under": 0})
    cov = cov.merge(n_inst_per_tp, on="top_parent_entity_id", how="left").fillna({"n_inst_subsidiaries": 0})
    cov["n_funds_under"] = cov["n_funds_under"].astype(int)
    cov["n_inst_subsidiaries"] = cov["n_inst_subsidiaries"].astype(int)

    def classify(row):
        if row["thirteen_f_aum_billions"] > 0 and row["fund_tier_aum_billions"] > 0:
            return "both"
        if row["thirteen_f_aum_billions"] > 0:
            return "13F_only"
        if row["fund_tier_aum_billions"] > 0:
            return "fund_only"
        return "neither"

    cov["coverage_class"] = cov.apply(classify, axis=1)
    cov = cov.sort_values("combined_aum_billions", ascending=False).reset_index(drop=True)

    # Bucket totals
    print(f"\n  coverage class buckets:")
    bk = cov.groupby("coverage_class").agg(
        n_top_parents=("top_parent_entity_id", "count"),
        thirteen_f_aum_b=("thirteen_f_aum_billions", "sum"),
        fund_tier_aum_b=("fund_tier_aum_billions", "sum"),
        combined_aum_b=("combined_aum_billions", "sum"),
    ).reset_index()
    print(bk.to_string())

    # Top-100 by combined AUM
    top100 = cov.head(100).copy()
    print(f"\n  top-20 by combined AUM (preview):")
    print(top100.head(20)[["top_parent_canonical_name", "thirteen_f_aum_billions",
                            "fund_tier_aum_billions", "combined_aum_billions",
                            "coverage_class", "n_funds_under"]].to_string(index=False))

    # === Outputs ===
    out_dir = Path("data/working")
    out_dir.mkdir(parents=True, exist_ok=True)
    cov_path = out_dir / "cp-5-top-parent-coverage-matrix.csv"
    top100.to_csv(cov_path, index=False)
    print(f"\nwrote {cov_path} (top-100 by combined AUM)")

    # Working artifact for Phase 2 — full inst→top_parent map
    artifact_path = Path("scripts/oneoff/_cp5_inst_to_topparent.parquet")
    inst_to_tp.to_parquet(artifact_path, index=False)
    fund_chain_path = Path("scripts/oneoff/_cp5_fund_chain.parquet")
    fund_chain.to_parquet(fund_chain_path, index=False)
    print(f"wrote {artifact_path}")
    print(f"wrote {fund_chain_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
