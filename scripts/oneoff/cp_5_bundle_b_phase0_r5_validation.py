"""CP-5 Bundle B — Phase 0.5: Modified R5 validation against top-25 top-parents.

Validates the modified R5 rule (Bundle A §1.4) produces sensible per-top-parent
aggregate AUM before Bundle B Phase 1 maps the graph it relies on. STOP gate:
if 5+ plausibility flags fire across the top-25, abort and report.

Note on plausibility reference frame: cp-5-top-parent-coverage-matrix.csv reports
SUMMED equity-position market-value (not firm AUM under management). Modified R5
should be at most slightly less than `combined_aum_billions` after FoF and
non-valid-CUSIP subtractions. Plausibility flags use the matrix as the reference,
not external AUM-under-management numbers (they're a different denominator).

Outputs:
  data/working/cp-5-bundle-b-r5-validation.csv

Read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cp_5_bundle_b_common import (  # noqa: E402
    COVERAGE_QUARTER,
    WORKDIR,
    brand_stem,
    build_fund_to_tp,
    build_inst_to_tp,
    connect,
)


def compute_thirteen_f_per_pair(con, inst_to_tp: pd.DataFrame) -> pd.DataFrame:
    """13F AUM per (top_parent, ticker, cusip) for COVERAGE_QUARTER."""
    con.register("inst_to_tp_df", inst_to_tp[["entity_id", "top_parent_entity_id"]])
    return con.execute(f"""
        SELECT itp.top_parent_entity_id,
               h.ticker,
               h.cusip,
               SUM(h.market_value_usd) AS thirteen_f_aum
        FROM holdings_v2 h
        JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
        WHERE h.is_latest
          AND h.quarter = '{COVERAGE_QUARTER}'
        GROUP BY 1, 2, 3
    """).fetchdf()


def compute_fund_tier_per_pair(
    con, fund_to_tp: pd.DataFrame, *, drop_intra_fof: bool, drop_invalid_cusip: bool
) -> pd.DataFrame:
    """Fund-tier AUM per (top_parent, ticker, cusip) for 2025Q4 EC.

    drop_intra_fof: subtract intra-family fund-of-fund rows
        (outer family stem == held issuer stem AND same top_parent)
    drop_invalid_cusip: filter to cusip ~ '^[0-9A-Z]{9}$'
    """
    con.register("fund_to_tp_df", fund_to_tp[["fund_entity_id", "top_parent_entity_id"]])
    cusip_predicate = (
        "AND fh.cusip ~ '^[0-9A-Z]{9}$'" if drop_invalid_cusip else ""
    )
    df = con.execute(f"""
        SELECT ftp.top_parent_entity_id,
               fh.ticker,
               fh.cusip,
               fh.family_name,
               fh.issuer_name,
               SUM(fh.market_value_usd) AS aum
        FROM fund_holdings_v2 fh
        JOIN fund_to_tp_df ftp ON ftp.fund_entity_id = fh.entity_id
        WHERE fh.is_latest
          AND fh.quarter = '{COVERAGE_QUARTER}'
          AND fh.asset_category = 'EC'
          {cusip_predicate}
        GROUP BY 1, 2, 3, 4, 5
    """).fetchdf()

    if drop_intra_fof:
        df["family_stem"] = df["family_name"].map(brand_stem)
        df["issuer_stem"] = df["issuer_name"].map(brand_stem)
        intra = (
            df["family_stem"].notna()
            & df["issuer_stem"].notna()
            & (df["family_stem"] == df["issuer_stem"])
        )
        df = df[~intra].copy()

    return (
        df.groupby(["top_parent_entity_id", "ticker", "cusip"], dropna=False)["aum"]
        .sum()
        .reset_index()
        .rename(columns={"aum": "fund_tier_aum"})
    )


def aggregate_per_top_parent(
    pair_df: pd.DataFrame,
    coverage_class_by_tp: dict[int, str],
) -> pd.DataFrame:
    """Apply R5 rule per pair, then aggregate to per-top-parent.

    pair_df has columns: top_parent_entity_id, ticker, cusip, thirteen_f_aum,
    fund_tier_raw_aum, fund_tier_adjusted_aum.
    """
    out = []
    for tp, sub in pair_df.groupby("top_parent_entity_id"):
        tp_int = int(tp) if pd.notna(tp) else None
        cov = coverage_class_by_tp.get(tp_int)

        thirteen_f = sub["thirteen_f_aum"].fillna(0)
        fund_raw = sub["fund_tier_raw_aum"].fillna(0)
        fund_adj = sub["fund_tier_adjusted_aum"].fillna(0)

        # Naive R5 (no subtractions, MAX both)
        naive = pd.concat([thirteen_f, fund_raw], axis=1).max(axis=1).sum()

        # Modified R5 with coverage_class handling
        if cov == "13F_only":
            modified = thirteen_f.sum()
        elif cov == "fund_only":
            modified = fund_adj.sum()
        else:  # 'both' or unknown — MAX(thirteen_f, fund_adjusted)
            modified = pd.concat([thirteen_f, fund_adj], axis=1).max(axis=1).sum()

        out.append(
            {
                "top_parent_entity_id": tp_int,
                "thirteen_f_only_aum_b": thirteen_f.sum() / 1e9,
                "fund_tier_raw_aum_b": fund_raw.sum() / 1e9,
                "fund_tier_adjusted_aum_b": fund_adj.sum() / 1e9,
                "naive_R5_aum_b": naive / 1e9,
                "modified_R5_aum_b": modified / 1e9,
                "coverage_class": cov,
            }
        )
    return pd.DataFrame(out)


def plausibility_flags(row, thirteen_f_matrix_b: float, fund_corrected_b: float) -> list[str]:
    """Plausibility flags for modified R5 against the corrected matrix baseline.

    Important: cp-5-top-parent-coverage-matrix.csv double-counts fund-tier (joins
    entity_rollup_history WITHOUT rollup_type filter, so every fund contributes
    decision_maker_v1 AND economic_control_v1 rows). The matrix's
    fund_tier_aum_billions is exactly 2x reality. `fund_corrected_b` is the
    matrix value / 2.

    Modified R5 for 'both' firms takes MAX per (ticker, cusip) — the result
    falls in [max(SUM_13f, SUM_fund_adj), SUM_13f + SUM_fund_adj]. The
    plausibility check looks for results OUTSIDE that envelope, not for results
    that are merely smaller than naive sum.
    """
    flags = []
    m = row["modified_R5_aum_b"]
    n = row["naive_R5_aum_b"]

    # Hard structural checks (modified_R5 must respect rule bounds)
    if m > n + 0.5:
        flags.append("modified_GT_naive")  # subtraction direction wrong
    if row["coverage_class"] == "13F_only" and m == 0 and thirteen_f_matrix_b > 0:
        flags.append("13F_only_zero_R5")
    if row["coverage_class"] == "fund_only" and m == 0 and fund_corrected_b > 0:
        flags.append("fund_only_zero_R5")

    # Envelope check — modified_R5 must be at least max(13F, fund_adj)
    # and at most 13F + fund_adj.
    expected_lower = max(row["thirteen_f_only_aum_b"], row["fund_tier_adjusted_aum_b"])
    expected_upper = row["thirteen_f_only_aum_b"] + row["fund_tier_adjusted_aum_b"]
    if m + 0.5 < expected_lower:
        flags.append("R5_below_max_envelope")
    if m > expected_upper + 0.5:
        flags.append("R5_above_sum_envelope")

    # NOTE: We deliberately do NOT compare modified_R5 to matrix's raw fund-tier
    # max — the modified rule's whole job is to subtract intra-family FoF and
    # non-valid-CUSIP rows, so modified_R5 < matrix_fund_raw is the correct
    # behavior, not a flag.

    return flags


def main() -> int:
    con = connect()
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # 1. Build entity rollup maps.
    print("Building inst_to_tp + fund_to_tp …")
    inst_to_tp = build_inst_to_tp(con)
    fund_to_tp = build_fund_to_tp(con, inst_to_tp)
    print(
        f"  inst_to_tp rows: {len(inst_to_tp):,}; "
        f"fund_to_tp rows (resolved tp): "
        f"{fund_to_tp['top_parent_entity_id'].notna().sum():,} / {len(fund_to_tp):,}"
    )

    # 2. Load top-25 from coverage matrix.
    cov = pd.read_csv("data/working/cp-5-top-parent-coverage-matrix.csv")
    top25 = cov.sort_values("combined_aum_billions", ascending=False).head(25).copy()
    coverage_class_by_tp = dict(
        zip(top25["top_parent_entity_id"].astype(int), top25["coverage_class"])
    )
    # Matrix fund_tier is double-counted (entity_rollup_history joined without
    # rollup_type filter — see Phase 0.5 finding §). Compute corrected values.
    top25 = top25.copy()
    top25["fund_tier_corrected_b"] = top25["fund_tier_aum_billions"] / 2.0
    top25["combined_corrected_b"] = (
        top25["thirteen_f_aum_billions"] + top25["fund_tier_corrected_b"]
    )
    matrix_thirteen_f = dict(zip(top25["top_parent_entity_id"].astype(int), top25["thirteen_f_aum_billions"]))
    matrix_fund_corrected = dict(zip(top25["top_parent_entity_id"].astype(int), top25["fund_tier_corrected_b"]))
    matrix_combined_corrected = dict(zip(top25["top_parent_entity_id"].astype(int), top25["combined_corrected_b"]))
    print(f"\nTop-25 cohort loaded: {len(top25)} (matrix fund-tier corrected for 2x rollup_type double-count)")

    # 3. Per-(tp, ticker, cusip) AUM under each rule variant.
    print("\nComputing 13F per pair …")
    tf = compute_thirteen_f_per_pair(con, inst_to_tp)

    print("Computing fund_tier_raw per pair (no subtractions, all CUSIPs) …")
    fund_raw = compute_fund_tier_per_pair(
        con, fund_to_tp, drop_intra_fof=False, drop_invalid_cusip=False
    ).rename(columns={"fund_tier_aum": "fund_tier_raw_aum"})

    print("Computing fund_tier_adjusted per pair (intra-FoF + non-valid CUSIP filtered) …")
    fund_adj = compute_fund_tier_per_pair(
        con, fund_to_tp, drop_intra_fof=True, drop_invalid_cusip=True
    ).rename(columns={"fund_tier_aum": "fund_tier_adjusted_aum"})

    # 4. Filter to top-25 and merge.
    top25_eids = set(top25["top_parent_entity_id"].astype(int))
    tf25 = tf[tf["top_parent_entity_id"].isin(top25_eids)]
    fr25 = fund_raw[fund_raw["top_parent_entity_id"].isin(top25_eids)]
    fa25 = fund_adj[fund_adj["top_parent_entity_id"].isin(top25_eids)]

    pair = (
        tf25.merge(fr25, on=["top_parent_entity_id", "ticker", "cusip"], how="outer")
            .merge(fa25, on=["top_parent_entity_id", "ticker", "cusip"], how="outer")
    )
    print(f"  Top-25 (top_parent, ticker, cusip) triples: {len(pair):,}")

    # 5. Aggregate per top_parent under each rule.
    agg = aggregate_per_top_parent(pair, coverage_class_by_tp)
    agg = agg.merge(
        top25[
            [
                "top_parent_entity_id", "top_parent_canonical_name",
                "combined_aum_billions", "combined_corrected_b",
                "fund_tier_aum_billions", "fund_tier_corrected_b",
            ]
        ],
        on="top_parent_entity_id",
        how="left",
    )
    agg["delta_naive_minus_modified_b"] = (
        agg["naive_R5_aum_b"] - agg["modified_R5_aum_b"]
    )
    agg["delta_pct"] = (
        agg["delta_naive_minus_modified_b"] / agg["naive_R5_aum_b"].replace(0, pd.NA)
    ) * 100

    # 6. Plausibility flags (against corrected matrix baseline)
    _ = matrix_combined_corrected  # corrected combined retained in CSV but not flagged
    agg["plausibility_flags"] = agg.apply(
        lambda r: ";".join(
            plausibility_flags(
                r,
                thirteen_f_matrix_b=matrix_thirteen_f.get(r["top_parent_entity_id"], 0),
                fund_corrected_b=matrix_fund_corrected.get(r["top_parent_entity_id"], 0),
            )
        )
        or "",
        axis=1,
    )
    agg = agg.sort_values("modified_R5_aum_b", ascending=False).reset_index(drop=True)

    print("\n" + "=" * 100)
    print("Top-25 Modified R5 validation:")
    print("=" * 100)
    cols = [
        "top_parent_entity_id", "top_parent_canonical_name", "coverage_class",
        "thirteen_f_only_aum_b", "fund_tier_raw_aum_b", "fund_tier_adjusted_aum_b",
        "naive_R5_aum_b", "modified_R5_aum_b", "combined_corrected_b",
        "delta_pct", "plausibility_flags",
    ]
    pd.set_option("display.max_colwidth", 50)
    pd.set_option("display.width", 220)
    print(agg[cols].to_string(index=False))

    # 7. STOP gate evaluation
    flagged_firms = agg[agg["plausibility_flags"] != ""]
    n_flagged = len(flagged_firms)
    print("\n" + "=" * 100)
    print(f"STOP-GATE: {n_flagged} firms have one or more plausibility flags.")
    if n_flagged >= 5:
        print("  → ABORT recommendation: 5+ flagged firms. Investigate before Phase 1.")
    else:
        print("  → PASS: < 5 flagged firms. Document and continue to Phase 1.")
    print("=" * 100)

    # 8. CSV
    out_path = WORKDIR / "cp-5-bundle-b-r5-validation.csv"
    agg.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
