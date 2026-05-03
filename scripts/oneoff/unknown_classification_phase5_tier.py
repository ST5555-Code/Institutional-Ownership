"""Phase 5: tier the 3,852 ECH unknown cohort into A/B/C buckets.

Tier A — HIGH-CONFIDENCE auto-resolvable:
  - sig_c_label is unambiguous ('active' / 'passive') AND no conflict with sig_d, OR
  - sig_d_mgr_type unambiguous (not 'mixed', not 'unknown'), OR
  - sig_a_strategy unambiguous (not 'unknown' and not NULL).

Tier B — MEDIUM-CONFIDENCE (chat review):
  - sig_c_label='hedge_fund_candidate' (LP suffix only — weak), OR
  - sig_d_mgr_type='mixed', OR
  - signals conflict (e.g., name says PASSIVE, manager_type says active).

Tier C — LOW-CONFIDENCE residual:
  - No signals at all (all four return NULL/False).

Wave assignments per tier laid out in Phase 6; here we just attach a
recommended_wave label.
"""
import duckdb
import pandas as pd
from pathlib import Path

WT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/nervous-faraday-6ca32e")
SIGNALS = WT / "data/working/unknown-classification-signals.parquet"
DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
SENTINEL = "DATE '9999-12-31'"

UNAMBIG_MGR_TYPES = {
    "active", "passive", "strategic", "hedge_fund", "wealth_management",
    "pension_insurance", "private_equity", "quantitative",
    "endowment_foundation", "family_office", "venture_capital", "activist",
    "SWF", "multi_strategy",
}
AMBIG_MGR_TYPES = {"mixed", "unknown", None}


def attach_aum(df: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    eids = df["entity_id"].tolist()
    aum_inst = con.execute(
        f"""
        SELECT entity_id, COALESCE(SUM(market_value_usd), 0) AS aum
        FROM holdings_v2
        WHERE is_latest AND entity_id = ANY(?)
        GROUP BY entity_id
        """,
        [eids],
    ).fetch_df()
    aum_fund = con.execute(
        f"""
        SELECT dm_rollup_entity_id AS entity_id, COALESCE(SUM(market_value_usd), 0) AS fund_aum
        FROM fund_holdings_v2
        WHERE is_latest AND dm_rollup_entity_id = ANY(?)
        GROUP BY dm_rollup_entity_id
        """,
        [eids],
    ).fetch_df()
    out = df.merge(aum_inst, on="entity_id", how="left").merge(aum_fund, on="entity_id", how="left")
    out["aum"] = out["aum"].fillna(0).astype("float64")
    out["fund_aum"] = out["fund_aum"].fillna(0).astype("float64")
    return out


def tier_row(r) -> tuple[str, str, str]:
    """Return (tier, recommended_wave, rationale)."""
    name_label = r["sig_c_label"]
    mgr_type = r["sig_d_mgr_type"]
    adv_strat = r["sig_a_strategy"]
    sig_a = bool(r["sig_a_hit"]) if pd.notna(r["sig_a_hit"]) else False
    sig_b = bool(r["sig_b_hit"]) if pd.notna(r["sig_b_hit"]) else False
    sig_c = bool(r["sig_c_hit"]) if pd.notna(r["sig_c_hit"]) else False
    sig_d = bool(r["sig_d_hit"]) if pd.notna(r["sig_d_hit"]) else False

    # Tier A first
    # 1) Name-pattern unambiguous (active or passive — not LP suffix)
    if name_label in ("active", "passive"):
        # Conflict check vs manager_type
        if mgr_type and mgr_type in UNAMBIG_MGR_TYPES and mgr_type != name_label:
            # E.g., name says active, manager_type says hedge_fund — surface to Tier B.
            return ("B", "4", f"name={name_label} conflicts with manager_type={mgr_type}")
        return ("A", "1", f"name-pattern={name_label}")

    # 2) ADV strategy unambiguous
    if sig_a and adv_strat and adv_strat != "unknown":
        return ("A", "2", f"adv_strategy={adv_strat}")

    # 3) Manager_type unambiguous
    if mgr_type in UNAMBIG_MGR_TYPES:
        return ("A", "3", f"manager_type={mgr_type}")

    # Tier B
    if name_label == "hedge_fund_candidate":
        return ("B", "4", "LP-suffix candidate (weak)")
    if mgr_type == "mixed":
        return ("B", "4", "manager_type=mixed (ambiguous)")
    if mgr_type == "unknown":
        return ("B", "4", "manager_type=unknown (placeholder)")
    if sig_a and adv_strat == "unknown":
        return ("B", "4", "ADV present but strategy_inferred=unknown")
    if sig_b and not (sig_c or sig_d):
        # N-CEN tells us role but no class signal
        return ("B", "4", f"N-CEN role={r['sig_b_role']} only (no class signal)")

    # Tier C
    return ("C", "RESIDUAL", "no signal")


def main() -> None:
    df = pd.read_parquet(SIGNALS)
    df = attach_aum(df)

    out = df.apply(tier_row, axis=1, result_type="expand")
    out.columns = ["tier", "recommended_wave", "rationale"]
    df = pd.concat([df, out], axis=1)

    print("PHASE 5 — tiered cohort\n")

    print("(a) tier counts + AUM exposure:")
    grp = df.groupby("tier").agg(
        n=("entity_id", "count"),
        inst_aum=("aum", "sum"),
        fund_aum=("fund_aum", "sum"),
    )
    grp["combined_aum"] = grp["inst_aum"] + grp["fund_aum"]
    for tier, row in grp.iterrows():
        print(f"  Tier {tier}: {int(row['n']):>5,} entities  "
              f"inst=${row['inst_aum']/1e9:>8,.2f}B  "
              f"fund=${row['fund_aum']/1e9:>8,.2f}B  "
              f"combined=${row['combined_aum']/1e9:>8,.2f}B")

    print("\n(b) wave counts (all tiers combined):")
    print(df["recommended_wave"].value_counts().to_string())

    print("\n(c) Tier A wave breakdown:")
    print(df[df["tier"] == "A"]["recommended_wave"].value_counts().to_string())

    print("\n(d) Tier B rationale breakdown (top 10):")
    print(df[df["tier"] == "B"]["rationale"].value_counts().head(10).to_string())

    # Sample 25 names per tier — sorted by combined AUM desc
    print("\n(e) Top-25 sample names per tier (by combined AUM):")
    for tier in ("A", "B", "C"):
        sub = df[df["tier"] == tier].copy()
        sub["combined_aum"] = sub["aum"] + sub["fund_aum"]
        sub = sub.sort_values("combined_aum", ascending=False).head(25)
        print(f"\n  ---- Tier {tier} top 25 by AUM ----")
        for _, r in sub.iterrows():
            print(f"  ${(r['aum']+r['fund_aum'])/1e9:>8,.2f}B  eid={int(r['entity_id']):>6d}  "
                  f"{(r['canonical_name'] or '')[:60]:<60s}  rationale={r['rationale']}")

    # Cross-validate: any Tier A hits with conflict?
    print("\n(f) sanity: any Tier A rows where name-pattern + manager_type would conflict?")
    print("  (these would be in Tier B rationale containing 'conflicts')")
    print(df[df["rationale"].str.contains("conflicts", na=False)].shape[0], "rows")

    # Persist enriched table
    out_pq = WT / "data/working/unknown-classification-tiered.parquet"
    df.to_parquet(out_pq, index=False)
    print(f"\nWrote: {out_pq}")

    # Per-tier CSVs (Phase 7 requirement — write here so Phase 7 just calls)
    csv_cols = [
        "entity_id", "canonical_name", "entity_type", "ech_source",
        "aum", "fund_aum",
        "sig_a_hit", "sig_b_hit", "sig_c_hit", "sig_c_label",
        "sig_d_hit", "sig_d_mgr_type", "sig_e_hit", "sig_e_h_entity_type",
        "tier", "recommended_wave", "rationale",
    ]
    rename = {
        "aum": "institution_aum_usd",
        "fund_aum": "fund_rollup_aum_usd",
        "ech_source": "ECH_source",
        "entity_type": "entity_type_entities",
        "sig_d_mgr_type": "signal_D_value",
        "sig_e_h_entity_type": "signal_E_value",
        "sig_c_label": "signal_C_label",
        "sig_a_hit": "signal_A_hit",
        "sig_b_hit": "signal_B_hit",
        "sig_c_hit": "signal_C_hit",
        "sig_d_hit": "signal_D_hit",
        "sig_e_hit": "signal_E_hit",
    }
    for tier in ("A", "B", "C"):
        sub = df[df["tier"] == tier][csv_cols].rename(columns=rename)
        sub = sub.sort_values(["institution_aum_usd", "fund_rollup_aum_usd"], ascending=False)
        out = WT / f"data/working/unknown-classification-tier-{tier.lower()}.csv"
        sub.to_csv(out, index=False)
        print(f"Wrote: {out}  ({len(sub):,} rows)")


if __name__ == "__main__":
    main()
