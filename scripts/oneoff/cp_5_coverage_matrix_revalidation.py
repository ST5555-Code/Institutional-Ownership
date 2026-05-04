"""CP-5 coverage matrix re-validation — corrects the rollup_type defect.

Read-only investigation. Re-cuts the cp-5-discovery (PR #276) Phase 1d
coverage matrix and Phase 2 overlap probe with the corrected
entity_rollup_history join (rollup_type filter applied). Bundle B
(PR #278) Phase 0.5 §0.3 surfaced that the original artifacts joined
entity_rollup_history without filtering on rollup_type, double-counting
every fund's market_value (one row per rollup_type × N rollup_types).

Outputs:
  data/working/cp-5-coverage-matrix-corrected.csv
  data/working/cp-5-overlap-probe-corrected.csv

Refs:
  docs/findings/cp-5-discovery.md (original artifacts, retained as audit trail)
  docs/findings/cp-5-bundle-a-discovery.md §1.4 (modified R5 rule)
  docs/findings/cp-5-bundle-b-discovery.md §0.3 (defect identification)
  scripts/oneoff/cp_5_discovery_phase1_inventory.py:158-165 (defective query)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
COVERAGE_QUARTER = "2025Q4"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")
ROLLUP_TYPE_CANONICAL = "decision_maker_v1"
SAMPLE_TICKERS = ["AAPL", "NEE", "AVDX"]
TOP_FIVE_FIRMS = [4375, 10443, 3241, 5026, 2]  # Vanguard, FMR, BlackRock Inc., DFA, BlackRock/iShares


def build_inst_to_top_parent(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Replicates Phase 1's institution→top_parent climb (unaffected by defect)."""
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
        "entity_id": list(cur.keys()),
        "top_parent_entity_id": list(cur.values()),
    })


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    # === Phase 1a — rollup_type inventory ===
    print("=" * 72)
    print("PHASE 1a — rollup_type inventory (entity_rollup_history open rows)")
    print("=" * 72)
    rt_inv = con.execute(f"""
        SELECT rollup_type, COUNT(*) AS n_rows
        FROM entity_rollup_history
        WHERE valid_to = {SENTINEL}
        GROUP BY rollup_type
        ORDER BY n_rows DESC
    """).fetchdf()
    print(rt_inv.to_string(index=False))

    rt_inv_fund = con.execute(f"""
        SELECT erh.rollup_type, COUNT(*) AS n_rows
        FROM entity_rollup_history erh
        JOIN entity_current ec ON ec.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND ec.entity_type = 'fund'
        GROUP BY erh.rollup_type
        ORDER BY n_rows DESC
    """).fetchdf()
    print("\nfund-typed entities only:")
    print(rt_inv_fund.to_string(index=False))

    if ROLLUP_TYPE_CANONICAL not in set(rt_inv["rollup_type"]):
        print(f"\nABORT: canonical rollup_type '{ROLLUP_TYPE_CANONICAL}' not present", file=sys.stderr)
        return 2

    # === Phase 1b — confirm 2× inflation on 5-firm cohort ===
    print()
    print("=" * 72)
    print("PHASE 1b — empirical 2× confirmation (5 firms, fund_tier_aum_billions)")
    print("=" * 72)

    inst_to_tp = build_inst_to_top_parent(con)
    con.register("inst_to_tp_df", inst_to_tp)

    # Defective fund_chain (PR #276 shape — no rollup_type filter)
    fund_chain_orig = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id,
               erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND ec_f.entity_type = 'fund'
    """).fetchdf().merge(
        inst_to_tp.rename(columns={"entity_id": "institution_entity_id"}),
        on="institution_entity_id", how="left",
    )

    # Corrected fund_chain (rollup_type filter)
    fund_chain_corr = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id,
               erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
          AND ec_f.entity_type = 'fund'
    """).fetchdf().merge(
        inst_to_tp.rename(columns={"entity_id": "institution_entity_id"}),
        on="institution_entity_id", how="left",
    )
    print(f"  fund_chain_orig rows: {len(fund_chain_orig):,}")
    print(f"  fund_chain_corr rows: {len(fund_chain_corr):,}")
    print(f"  ratio: {len(fund_chain_orig) / max(len(fund_chain_corr), 1):.4f}")

    con.register("fund_chain_orig_df", fund_chain_orig)
    con.register("fund_chain_corr_df", fund_chain_corr)

    # Per-rollup_type fund_chain (for sum-identity gate + rollup_type sensitivity)
    fund_chain_dm = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id, erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND erh.rollup_type = 'decision_maker_v1'
          AND ec_f.entity_type = 'fund'
    """).fetchdf().merge(
        inst_to_tp.rename(columns={"entity_id": "institution_entity_id"}),
        on="institution_entity_id", how="left",
    )
    fund_chain_ec = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id, erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND erh.rollup_type = 'economic_control_v1'
          AND ec_f.entity_type = 'fund'
    """).fetchdf().merge(
        inst_to_tp.rename(columns={"entity_id": "institution_entity_id"}),
        on="institution_entity_id", how="left",
    )
    con.register("fc_dm_df", fund_chain_dm)
    con.register("fc_ec_df", fund_chain_ec)

    # rollup_type alignment audit
    align = con.execute(f"""
        WITH fund_rollups AS (
            SELECT erh.entity_id,
                   MAX(CASE WHEN erh.rollup_type = 'decision_maker_v1' THEN erh.rollup_entity_id END) AS dm_r,
                   MAX(CASE WHEN erh.rollup_type = 'economic_control_v1' THEN erh.rollup_entity_id END) AS ec_r
            FROM entity_rollup_history erh
            JOIN entity_current ec ON ec.entity_id = erh.entity_id
            WHERE erh.valid_to = {SENTINEL} AND ec.entity_type = 'fund'
            GROUP BY erh.entity_id
        )
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN dm_r = ec_r THEN 1 ELSE 0 END) AS aligned,
               SUM(CASE WHEN dm_r != ec_r THEN 1 ELSE 0 END) AS diverged
        FROM fund_rollups
    """).fetchone()
    align_pct = 100.0 * align[1] / align[0]
    print(f"\n  rollup_type alignment: {align[1]:,}/{align[0]:,} aligned ({align_pct:.1f}%); "
          f"{align[2]:,} diverged ({100-align_pct:.1f}%)")
    if align[2] > 0:
        print(f"  NOTE: dm vs ec are NOT identical for every fund — Bundle B §0.3 was approximate.")

    rows = []
    for tp_id in TOP_FIVE_FIRMS:
        name = con.execute(
            "SELECT ANY_VALUE(display_name) FROM entity_current WHERE entity_id = ?",
            [tp_id],
        ).fetchone()[0]
        def sum_for(table_alias, ttp=tp_id):
            return con.execute(f"""
                SELECT COALESCE(SUM(fh.market_value_usd) / 1e9, 0)
                FROM fund_holdings_v2 fh
                JOIN {table_alias} fc ON fc.fund_entity_id = fh.entity_id
                WHERE fh.is_latest = TRUE
                  AND fh.quarter = '{COVERAGE_QUARTER}'
                  AND fh.asset_category = 'EC'
                  AND fc.top_parent_entity_id = {ttp}
            """).fetchone()[0]

        orig = sum_for("fund_chain_orig_df")
        corr = sum_for("fund_chain_corr_df")  # decision_maker_v1
        ec_only = sum_for("fc_ec_df")  # economic_control_v1
        sum_identity = corr + ec_only
        delta = orig - sum_identity
        rows.append({
            "top_parent_entity_id": tp_id,
            "name": name,
            "orig_b": round(orig, 2),
            "dm_b": round(corr, 2),
            "ec_b": round(ec_only, 2),
            "dm_plus_ec_b": round(sum_identity, 2),
            "sum_identity_residual_b": round(delta, 2),
            "ratio_orig_dm": round(orig / corr, 4) if corr > 0 else None,
            "rollup_sensitivity_pct": round(100 * abs(corr - ec_only) / max(corr, ec_only), 2)
                                       if max(corr, ec_only) > 0 else None,
        })
    cohort_df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print()
    print(cohort_df.to_string(index=False))

    # Stricter gate: orig must equal dm + ec within rounding (defect signature
    # = "sum of both rollup_types"). Tolerance 0.5B per firm.
    residuals = cohort_df["sum_identity_residual_b"].abs()
    if (residuals > 0.5).any():
        print()
        print("ABORT: orig != dm+ec for some firms (max residual "
              f"{residuals.max():.2f}B). Defect is more complex than rollup_type union.",
              file=sys.stderr)
        return 3
    print(f"\n  PASS: orig = dm + ec across all {len(cohort_df)} firms (max residual {residuals.max():.3f}B)")
    print(f"        Defect confirmed as 'sum of both rollup_types', i.e. UNION-without-filter.")
    print(f"        Per-firm rollup_type sensitivity ranges from "
          f"{cohort_df['rollup_sensitivity_pct'].min():.1f}% to "
          f"{cohort_df['rollup_sensitivity_pct'].max():.1f}% — choice of canonical rollup_type matters.")

    # === Phase 2 — corrected coverage matrix ===
    print()
    print("=" * 72)
    print("PHASE 2 — corrected coverage matrix (top-100 by combined AUM)")
    print("=" * 72)

    # Top-parent enumeration (unchanged from PR #276)
    types_sql = ", ".join(f"'{t}'" for t in ROLLUP_CTRL_TYPES)
    top_parents = con.execute(f"""
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
        SELECT ec.entity_id AS top_parent_entity_id,
               ec.display_name AS top_parent_canonical_name
        FROM ec_uniq ec
        LEFT JOIN has_inst_parent hip ON hip.eid = ec.entity_id
        WHERE ec.entity_type = 'institution' AND hip.eid IS NULL
    """).fetchdf()

    h13f = con.execute(f"""
        SELECT itp.top_parent_entity_id,
               SUM(h.market_value_usd) / 1e9 AS thirteen_f_aum_billions
        FROM holdings_v2 h
        JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
        WHERE h.is_latest = TRUE AND h.quarter = '{COVERAGE_QUARTER}'
        GROUP BY 1
    """).fetchdf()

    fund_aum_corr = con.execute(f"""
        SELECT fc.top_parent_entity_id,
               SUM(fh.market_value_usd) / 1e9 AS fund_tier_aum_billions
        FROM fund_holdings_v2 fh
        JOIN fund_chain_corr_df fc ON fc.fund_entity_id = fh.entity_id
        WHERE fh.is_latest = TRUE AND fh.quarter = '{COVERAGE_QUARTER}'
          AND fh.asset_category = 'EC'
        GROUP BY 1
    """).fetchdf()

    n_funds = fund_chain_corr.groupby("top_parent_entity_id").size().reset_index(name="n_funds_under")
    n_inst = inst_to_tp.groupby("top_parent_entity_id").size().reset_index(name="n_inst_subsidiaries")

    cov = top_parents.merge(h13f, on="top_parent_entity_id", how="left") \
                     .merge(fund_aum_corr, on="top_parent_entity_id", how="left")
    cov["thirteen_f_aum_billions"] = cov["thirteen_f_aum_billions"].fillna(0)
    cov["fund_tier_aum_billions"] = cov["fund_tier_aum_billions"].fillna(0)
    cov["combined_aum_billions"] = cov["thirteen_f_aum_billions"] + cov["fund_tier_aum_billions"]
    cov = cov.merge(n_funds, on="top_parent_entity_id", how="left").fillna({"n_funds_under": 0})
    cov = cov.merge(n_inst, on="top_parent_entity_id", how="left").fillna({"n_inst_subsidiaries": 0})
    cov["n_funds_under"] = cov["n_funds_under"].astype(int)
    cov["n_inst_subsidiaries"] = cov["n_inst_subsidiaries"].astype(int)

    def classify(r):
        if r["thirteen_f_aum_billions"] > 0 and r["fund_tier_aum_billions"] > 0:
            return "both"
        if r["thirteen_f_aum_billions"] > 0:
            return "13F_only"
        if r["fund_tier_aum_billions"] > 0:
            return "fund_only"
        return "neither"

    cov["coverage_class"] = cov.apply(classify, axis=1)
    cov = cov.sort_values("combined_aum_billions", ascending=False).reset_index(drop=True)
    top100 = cov.head(100).copy()

    # === Phase 2c — diff vs original PR #276 matrix ===
    orig = pd.read_csv("data/working/cp-5-top-parent-coverage-matrix.csv")
    diff = top100.merge(
        orig[["top_parent_entity_id", "thirteen_f_aum_billions", "fund_tier_aum_billions",
              "combined_aum_billions", "coverage_class"]].rename(columns={
            "thirteen_f_aum_billions": "thirteen_f_orig",
            "fund_tier_aum_billions": "fund_tier_orig",
            "combined_aum_billions": "combined_orig",
            "coverage_class": "coverage_class_orig",
        }),
        on="top_parent_entity_id", how="left",
    )
    diff["delta_combined_b"] = diff["combined_aum_billions"] - diff["combined_orig"]
    diff["delta_pct"] = (diff["delta_combined_b"] / diff["combined_orig"]).where(diff["combined_orig"] > 0)
    print()
    print(f"  total combined AUM: orig=${orig['combined_aum_billions'].sum():,.0f}B  "
          f"corr=${top100['combined_aum_billions'].sum():,.0f}B  "
          f"delta=${(top100['combined_aum_billions'].sum() - orig['combined_aum_billions'].sum()):,.0f}B")
    print()
    print("  Top-25 pre/post diff:")
    show_cols = ["top_parent_canonical_name", "thirteen_f_aum_billions",
                 "fund_tier_orig", "fund_tier_aum_billions",
                 "combined_orig", "combined_aum_billions", "delta_combined_b", "delta_pct"]
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 38)
    print(diff[show_cols].head(25).to_string(index=False))

    # Coverage_class transitions
    transitions = diff.groupby(["coverage_class_orig", "coverage_class"]).size().reset_index(name="n_firms")
    print()
    print("  Coverage_class transitions (orig → corrected):")
    print(transitions.to_string(index=False))
    n_unchanged = (diff["coverage_class_orig"] == diff["coverage_class"]).sum()
    n_moved = (diff["coverage_class_orig"] != diff["coverage_class"]).sum()
    print(f"  unchanged: {n_unchanged}  moved: {n_moved}")

    # === Output corrected matrix ===
    out_dir = Path("data/working")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_matrix = out_dir / "cp-5-coverage-matrix-corrected.csv"
    top100.to_csv(out_matrix, index=False)
    print(f"\nwrote {out_matrix} ({len(top100)} rows)")

    # === Phase 3 — corrected overlap probe ===
    print()
    print("=" * 72)
    print("PHASE 3 — corrected overlap probe (Set B with rollup_type filter)")
    print("=" * 72)
    print(f"  defect characterization: PR #276 Phase 2 reads _cp5_fund_chain.parquet")
    print(f"  produced by Phase 1's defective query → Set B was 2× inflated.")

    both_corr = top100[top100["coverage_class"] == "both"].head(20).reset_index(drop=True)
    print(f"\n  cohort: top-20 'both' under corrected matrix")

    overlap_rows = []
    for _, c in both_corr.iterrows():
        tp_id = int(c["top_parent_entity_id"])
        tp_name = c["top_parent_canonical_name"]
        for ticker in SAMPLE_TICKERS:
            set_a = con.execute(f"""
                SELECT COALESCE(SUM(h.market_value_usd) / 1e9, 0), COUNT(*)
                FROM holdings_v2 h
                JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
                WHERE h.is_latest = TRUE AND h.quarter = '{COVERAGE_QUARTER}'
                  AND h.ticker = '{ticker}' AND itp.top_parent_entity_id = {tp_id}
            """).fetchone()
            a_aum, a_filers = float(set_a[0]), int(set_a[1])

            set_b = con.execute(f"""
                SELECT COALESCE(SUM(fh.market_value_usd) / 1e9, 0), COUNT(*)
                FROM fund_holdings_v2 fh
                JOIN fund_chain_corr_df fc ON fc.fund_entity_id = fh.entity_id
                WHERE fh.is_latest = TRUE AND fh.quarter = '{COVERAGE_QUARTER}'
                  AND fh.asset_category = 'EC' AND fh.ticker = '{ticker}'
                  AND fc.top_parent_entity_id = {tp_id}
            """).fetchone()
            b_aum, b_funds = float(set_b[0]), int(set_b[1])

            if a_aum == 0 and b_aum == 0:
                cls, ratio = "neither", None
            elif a_aum == 0:
                cls, ratio = "fund_only", float("inf")
            elif b_aum == 0:
                cls, ratio = "13F_only", 0.0
            else:
                ratio = b_aum / a_aum
                if 0.85 <= ratio <= 1.15:
                    cls = "13F_covers_fund"
                elif ratio > 1.15:
                    cls = "fund_extends_13F"
                else:
                    cls = "13F_dominant"

            overlap_rows.append({
                "top_parent_entity_id": tp_id,
                "top_parent_canonical_name": tp_name,
                "ticker": ticker,
                "set_A_13F_aum_b": round(a_aum, 4),
                "set_A_filers": a_filers,
                "set_B_fund_aum_b": round(b_aum, 4),
                "set_B_funds": b_funds,
                "ratio_B_over_A": round(ratio, 3) if ratio is not None and ratio != float("inf") else ratio,
                "classification": cls,
            })

    overlap_corr = pd.DataFrame(overlap_rows)
    out_overlap = out_dir / "cp-5-overlap-probe-corrected.csv"
    overlap_corr.to_csv(out_overlap, index=False)
    print(f"\n  classification distribution (corrected):")
    print(overlap_corr["classification"].value_counts().to_string())

    overlap_orig = pd.read_csv("data/working/cp-5-overlap-probe.csv")
    print(f"\n  classification distribution (original PR #276):")
    print(overlap_orig["classification"].value_counts().to_string())

    o = overlap_corr[overlap_corr["classification"].isin(
        ["13F_covers_fund", "fund_extends_13F", "13F_dominant"])]
    if len(o):
        print(f"\n  corrected ratio summary (n={len(o)}):")
        print(f"    median B/A: {o['ratio_B_over_A'].median():.3f}")
        print(f"    mean B/A:   {o['ratio_B_over_A'].mean():.3f}")
        print(f"    p10/p90:    {o['ratio_B_over_A'].quantile(0.1):.3f} / {o['ratio_B_over_A'].quantile(0.9):.3f}")

    n_pairs_corr = len(overlap_corr)
    pct_dom = 100.0 * (overlap_corr["classification"] == "13F_dominant").sum() / n_pairs_corr
    pct_ext = 100.0 * (overlap_corr["classification"] == "fund_extends_13F").sum() / n_pairs_corr
    pct_cov = 100.0 * (overlap_corr["classification"] == "13F_covers_fund").sum() / n_pairs_corr
    print(f"\n  corrected bimodal split: 13F_dominant {pct_dom:.0f}%  fund_extends_13F {pct_ext:.0f}%  "
          f"13F_covers_fund {pct_cov:.0f}%  (PR #276 reported 47/42 dominant/extending)")
    print(f"\nwrote {out_overlap} ({n_pairs_corr} rows)")

    # === Phase 4 — modified R5 fit verdict ===
    print()
    print("=" * 72)
    print("PHASE 4 — modified R5 fit on corrected matrix")
    print("=" * 72)
    print()
    print("  Methodology: re-apply Bundle B Phase 0.5's 4 structural envelope flags")
    print("  to Bundle B's published R5 numbers (cp-5-bundle-b-r5-validation.csv).")
    print("  Bundle B's helper already used the corrected (rollup_type-filtered) join,")
    print("  so its R5 numbers are the corrected R5 numbers. This phase re-verifies the")
    print("  envelope check holds against the corrected matrix's 13F + fund_tier_corr.")
    print()
    print("  External-AUM anchor reference frame note: top-parent entities split by")
    print("  brand-vs-filer (e.g., BlackRock = eid 2 + eid 3241) so a single firm's")
    print("  reported total AUM is NOT a valid envelope for any one top_parent's R5.")
    print("  The structural envelope below is the correct gate.")

    r5_b = pd.read_csv("data/working/cp-5-bundle-b-r5-validation.csv")
    # Sanity: do Bundle B's fund_tier_corrected values align with our corrected matrix?
    join = top100[["top_parent_entity_id", "fund_tier_aum_billions"]].merge(
        r5_b[["top_parent_entity_id", "fund_tier_corrected_b"]],
        on="top_parent_entity_id", how="inner",
    )
    join["match_residual_b"] = (join["fund_tier_aum_billions"] - join["fund_tier_corrected_b"]).abs()
    max_resid = join["match_residual_b"].max()
    print()
    print(f"  Bundle-B-vs-our-matrix fund_tier match: {len(join)} firms compared, "
          f"max residual {max_resid:.4f}B")
    if max_resid > 0.5:
        print(f"  WARNING: Bundle B's fund_tier_corrected_b differs from our matrix by >0.5B for some firms.")

    # Apply Bundle B's structural envelope flags to its top-25 R5 results
    def envelope_flags(row):
        flags = []
        m = row["modified_R5_aum_b"]
        n = row["naive_R5_aum_b"]
        thirteen_f = row["thirteen_f_only_aum_b"]
        fund_adj = row["fund_tier_adjusted_aum_b"]
        if m > n + 0.5:
            flags.append("modified_GT_naive")
        if row["coverage_class"] == "13F_only" and m == 0 and thirteen_f > 0:
            flags.append("13F_only_zero_R5")
        if row["coverage_class"] == "fund_only" and m == 0 and fund_adj > 0:
            flags.append("fund_only_zero_R5")
        lower = max(thirteen_f, fund_adj)
        upper = thirteen_f + fund_adj
        if m + 0.5 < lower:
            flags.append("R5_below_max_envelope")
        if m > upper + 0.5:
            flags.append("R5_above_sum_envelope")
        return ";".join(flags)

    r5_b["flags"] = r5_b.apply(envelope_flags, axis=1)
    fail_count = (r5_b["flags"] != "").sum()

    print()
    show = ["top_parent_canonical_name", "coverage_class", "thirteen_f_only_aum_b",
            "fund_tier_adjusted_aum_b", "naive_R5_aum_b", "modified_R5_aum_b", "flags"]
    print(r5_b[show].to_string(index=False))
    print()
    print(f"  envelope flag count: {fail_count}/{len(r5_b)} firms")

    # Verdict
    print()
    print("  VERDICT:")
    # n_moved here = NaN-comparisons + true class transitions. Re-compute true transitions
    # excluding "new in top-100 corrected" cases (NaN coverage_class_orig).
    moved_real = (diff["coverage_class_orig"] != diff["coverage_class"]) \
                 & diff["coverage_class_orig"].notna()
    n_real_moved = int(moved_real.sum())
    n_new_in_top100 = int(diff["coverage_class_orig"].isna().sum())
    print(f"    coverage_class real transitions (within firms in both top-100s): {n_real_moved}")
    print(f"    firms newly in corrected top-100 (re-rank effect): {n_new_in_top100}")

    if fail_count == 0 and n_real_moved == 0:
        verdict = "A"
        print("    A — R5 LOCKED. 0 envelope flags; no true class transitions.")
    elif fail_count == 0:
        verdict = "B"
        print(f"    B — R5 LOCKED with notes. 0 envelope flags; "
              f"{n_real_moved} class transitions handled naturally by MAX.")
    else:
        verdict = "C"
        print(f"    C — R5 NEEDS REVISION. {fail_count} envelope flag failure(s).")

    # Persist verdict for findings doc
    print()
    print("  R5 VERDICT EXPORT:")
    print(f"    verdict={verdict}")
    print(f"    n_real_class_transitions={n_real_moved}")
    print(f"    n_new_in_top100_corrected={n_new_in_top100}")
    print(f"    n_envelope_flag_failures={fail_count}")
    print(f"    total_combined_orig_b={orig['combined_aum_billions'].sum():.1f}")
    print(f"    total_combined_corr_b={top100['combined_aum_billions'].sum():.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
