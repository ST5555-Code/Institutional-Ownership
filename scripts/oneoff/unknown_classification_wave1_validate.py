"""Wave 1 Phase 1: re-validate cohort + compute Wave 1 candidate subset.

Read-only. Per plan + docs/findings/unknown-classification-discovery.md §5.1+§6.

Tightened keyword set (whole-phrase, case-insensitive, word-boundary):
  ACTIVE:   Income Fund, Closed-End, CEF, Municipal, Interval Fund, BDC,
            Business Development, MuniYield, High Yield, High Income
  PASSIVE:  SPDR, iShares, Vanguard, ETF, Index, PowerShares, Direxion,
            ProShares, ProFund, WisdomTree, Innovator

Wave 1 candidate paths:
  Path 1 (name_pattern_active):  tier='A' AND name matches active phrase set
                                 AND signal_D_value NULL or matches 'active'
  Path 2 (name_pattern_passive): tier='A' AND name matches passive keyword set
  Path 3 (adv_strategy):         tier='A' AND signal_A_hit AND
                                 adv_strategy_inferred IN
                                 ('active','passive','quantitative',
                                  'hedge_fund','strategic')
"""
from __future__ import annotations
from pathlib import Path
import re
import duckdb
import pandas as pd

WT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/sleepy-wright-49f441")
DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
TIER_A_CSV = WT / "data/working/unknown-classification-tier-a.csv"
SENTINEL = "DATE '9999-12-31'"

# Refined ACTIVE keyword set v2 — phrase-only matches.
ACTIVE_PHRASES = [
    "Income Fund", "Income Trust", "Closed-End", "Closed End", "CEF",
    "Municipal", "MuniYield", "Interval Fund", "BDC", "Business Development",
    "High Yield", "High Income",
    "Opportunity Fund", "Opportunity Trust", "Opportunity Inc",
]
PASSIVE_PHRASES = [
    "SPDR", "iShares", "Vanguard", "ETF", "Index", "PowerShares",
    "Direxion", "ProShares", "ProFund", "WisdomTree", "Innovator",
]
# Qualified "Trust" right-anchored suffixes (trailing punctuation allowed).
TRUST_SUFFIXES = [
    "Trust", "Trust Inc", "Trust Inc.", "Trust, Inc.",
    "Trust LLC", "Trust LP", "Trust L.P.",
]
TRUST_EXCLUDE_TOKENS = ["Bank", "Bancorp", "Trust Company"]
# Qualified "Private" phrase set (anywhere in name).
PRIVATE_PHRASES = [
    "Private Capital", "Private Credit", "Private Equity Fund",
    "Private Markets", "Private Lending", "Private Income",
]
ADV_STRATEGY_ALLOW = {"active", "passive", "quantitative", "hedge_fund", "strategic"}

# Compile once, case-insensitive, word-boundary.
ACTIVE_PATTERNS = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in ACTIVE_PHRASES]
PASSIVE_PATTERNS = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in PASSIVE_PHRASES]
PRIVATE_PATTERNS = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in PRIVATE_PHRASES]
# Right-anchored Trust suffix: allow optional trailing punctuation/whitespace.
TRUST_SUFFIX_PATTERNS = [
    (s, re.compile(rf"\b{re.escape(s)}[\s,.]*$", re.IGNORECASE)) for s in TRUST_SUFFIXES
]
TRUST_EXCLUDE_PATTERNS = [
    re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in TRUST_EXCLUDE_TOKENS
]


def first_match(name, patterns):
    if not isinstance(name, str):
        return None
    for label, pat in patterns:
        if pat.search(name):
            return label
    return None


def trust_match(name):
    """Right-anchored Trust suffix, with bank/adviser exclusion."""
    if not isinstance(name, str):
        return None
    if any(p.search(name) for p in TRUST_EXCLUDE_PATTERNS):
        return None
    for s, pat in TRUST_SUFFIX_PATTERNS:
        if pat.search(name):
            return f"Trust ({s})"
    return None


def private_match(name):
    return first_match(name, PRIVATE_PATTERNS)


def active_keyword_match(name):
    """Combined active matcher: phrase-only + qualified Trust + qualified Private."""
    m = first_match(name, ACTIVE_PATTERNS)
    if m:
        return m
    m = trust_match(name)
    if m:
        return m
    m = private_match(name)
    if m:
        return m
    return None


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    # (a) cohort count + drift
    cohort_n = con.execute(
        f"""
        SELECT COUNT(*) FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
        """
    ).fetchone()[0]
    baseline = 3852
    drift = abs(cohort_n - baseline) / baseline
    print(f"(a) Open ECH classification='unknown' count: {cohort_n:,}")
    print(f"    Baseline: {baseline:,}   Drift: {drift:.2%}")
    if drift > 0.05:
        raise SystemExit(f"ABORT — cohort drift {drift:.2%} exceeds 5% gate")

    # Load Tier A CSV
    tier_a = pd.read_csv(TIER_A_CSV)
    print(f"\n(b) Tier A CSV rows: {len(tier_a):,}")

    # Re-derive ADV strategy_inferred for tier-A entities (signal_A_hit subset).
    eids = tier_a["entity_id"].tolist()
    adv = con.execute(
        f"""
        WITH crd_map AS (
            SELECT entity_id, identifier_value AS crd
            FROM entity_identifiers
            WHERE identifier_type='crd' AND valid_to = {SENTINEL}
        )
        SELECT cm.entity_id,
               BOOL_OR(am.crd_number IS NOT NULL) AS adv_hit,
               ANY_VALUE(am.strategy_inferred) AS adv_strategy_inferred
        FROM (SELECT UNNEST(?) AS entity_id) cm
        LEFT JOIN crd_map ON crd_map.entity_id = cm.entity_id
        LEFT JOIN adv_managers am ON am.crd_number = crd_map.crd
        GROUP BY cm.entity_id
        """,
        [eids],
    ).fetch_df()
    tier_a = tier_a.merge(adv, on="entity_id", how="left")
    tier_a["adv_hit"] = tier_a["adv_hit"].fillna(False)

    # Cohort confirmation: every tier-A entity must still be open ECH 'unknown'.
    open_check = con.execute(
        f"""
        SELECT entity_id FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
          AND entity_id IN (SELECT UNNEST(?))
        """,
        [eids],
    ).fetch_df()
    still_open = set(open_check["entity_id"].tolist())
    tier_a["still_open_unknown"] = tier_a["entity_id"].isin(still_open)
    n_already_resolved = int((~tier_a["still_open_unknown"]).sum())
    print(f"\n(c) Tier A entities no longer in unknown cohort: {n_already_resolved}")

    # Restrict Wave 1 logic to entities still in unknown cohort.
    df = tier_a[tier_a["still_open_unknown"]].copy()

    # Path 1: active name-pattern (refined v2 — phrase + qualified Trust/Private)
    df["active_match"] = df["canonical_name"].apply(active_keyword_match)
    # Path 2: passive name-pattern
    df["passive_match"] = df["canonical_name"].apply(lambda n: first_match(n, PASSIVE_PATTERNS))

    # Path 3: ADV-driven
    df["adv_strategy_clean"] = df["adv_strategy_inferred"].fillna("").astype(str)
    df["adv_path_eligible"] = (
        df["adv_hit"]
        & df["adv_strategy_clean"].isin(ADV_STRATEGY_ALLOW)
    )

    # Conflict check for Path 1 (active name-pattern):
    #   if signal_D_value is non-null and not equal to 'active' → conflict (drop to Wave 4e)
    def derive_active(row):
        if not row["active_match"]:
            return None
        sig_d = row.get("signal_D_value")
        if pd.notna(sig_d) and isinstance(sig_d, str) and sig_d.strip():
            if sig_d.strip().lower() != "active":
                return None  # conflict — drop
        return "active"

    df["wave1_active"] = df.apply(derive_active, axis=1)

    # Conflict check for Path 2 (passive name-pattern):
    #   if signal_D_value is non-null and not equal to 'passive' → conflict (drop)
    def derive_passive(row):
        if not row["passive_match"]:
            return None
        sig_d = row.get("signal_D_value")
        if pd.notna(sig_d) and isinstance(sig_d, str) and sig_d.strip():
            if sig_d.strip().lower() != "passive":
                return None
        return "passive"

    df["wave1_passive"] = df.apply(derive_passive, axis=1)

    # Path 3 derives classification verbatim from ADV strategy_inferred.
    df["wave1_adv"] = df.apply(
        lambda r: r["adv_strategy_clean"] if r["adv_path_eligible"] else None, axis=1
    )

    # Compose Wave 1 candidates (a single entity may have multiple paths;
    # priority: ADV > name_pattern_active > name_pattern_passive).
    def pick(r):
        if r["wave1_adv"]:
            return ("adv_strategy", "wave1_adv_strategy", r["wave1_adv"], "exact",
                    r["adv_strategy_clean"])
        if r["wave1_active"]:
            return ("name_pattern_active", "wave1_name_pattern_active",
                    "active", "high", r["active_match"])
        if r["wave1_passive"]:
            return ("name_pattern_passive", "wave1_name_pattern_passive",
                    "passive", "high", r["passive_match"])
        return (None, None, None, None, None)

    picks = df.apply(pick, axis=1, result_type="expand")
    picks.columns = [
        "derived_via", "source_string", "new_classification",
        "confidence", "signal_C_matched_keyword",
    ]
    df = pd.concat([df, picks], axis=1)

    cand = df[df["new_classification"].notna()].copy()

    # Print breakdown
    print(f"\n(d) Wave 1 candidate count: {len(cand):,}")
    print(f"    AUM exposure (institution + fund_rollup):")
    inst = cand["institution_aum_usd"].fillna(0).sum() / 1e9
    fund = cand["fund_rollup_aum_usd"].fillna(0).sum() / 1e9
    print(f"    inst=${inst:>8,.2f}B  fund=${fund:>8,.2f}B")

    print("\n(e) Per-path counts:")
    print(cand["derived_via"].value_counts().to_string())

    print("\n(f) Per-classification counts:")
    print(cand["new_classification"].value_counts().to_string())

    # Conflict counts (entities that matched a name-pattern but were dropped due to conflict)
    n_active_conflict = int(
        (df["active_match"].notna() & df["wave1_active"].isna() & df["adv_path_eligible"].eq(False))
        .sum()
    )
    n_passive_conflict = int(
        (df["passive_match"].notna() & df["wave1_passive"].isna() & df["adv_path_eligible"].eq(False))
        .sum()
    )
    print(f"\n(g) Conflicts dropped to Wave 4e:")
    print(f"    active name-pattern with signal_D!=active: {n_active_conflict}")
    print(f"    passive name-pattern with signal_D!=passive: {n_passive_conflict}")

    # Top 10 by AUM
    print("\n(h) Top 10 candidates by combined AUM:")
    cand_sorted = cand.copy()
    cand_sorted["combined_aum"] = (
        cand_sorted["institution_aum_usd"].fillna(0)
        + cand_sorted["fund_rollup_aum_usd"].fillna(0)
    )
    for _, r in cand_sorted.sort_values("combined_aum", ascending=False).head(10).iterrows():
        print(
            f"  ${r['combined_aum']/1e9:>8,.2f}B  eid={int(r['entity_id']):>6d}  "
            f"{(r['canonical_name'] or '')[:55]:<55s}  "
            f"via={r['derived_via']:<22s} -> {r['new_classification']:<13s} "
            f"kw={r['signal_C_matched_keyword']}"
        )

    # Spot-check per chat instruction v2.
    spot_in = [
        "BlackRock Science & Technology Trust",
        "Gabelli Equity Trust Inc",
        "KKR Real Estate Select Trust Inc.",
        "ROYCE SMALL-CAP TRUST, INC.",
    ]
    spot_out = [
        "Boston Trust Walden Inc.",
        "Wilmington Trust Investment Advisors, Inc.",
    ]
    cand_names = set(cand["canonical_name"].dropna().str.lower())
    print("\n(i) Spot-check INCLUDED (must be in Wave 1):")
    for n in spot_in:
        present = n.lower() in cand_names
        match = active_keyword_match(n)
        print(f"    {'OK ' if present else 'MISS'}  {n}  -> rule={match}, in_cand={present}")
    print("\n(j) Spot-check EXCLUDED (must NOT be in Wave 1):")
    for n in spot_out:
        present = n.lower() in cand_names
        match = active_keyword_match(n)
        print(f"    {'OK ' if not present else 'FAIL'}  {n}  -> rule={match}, in_cand={present}")

    # Show 5 included + 5 excluded from prior 165 dropouts.
    # The 'recommended_wave==1' rows from CSV are the prior phase-5 wave-1 set.
    prior_wave1 = tier_a[tier_a["recommended_wave"].astype(str) == "1"].copy()
    prior_wave1_eids = set(prior_wave1["entity_id"].tolist())
    included_from_prior = cand[cand["entity_id"].isin(prior_wave1_eids)].copy()
    excluded_from_prior = prior_wave1[~prior_wave1["entity_id"].isin(set(cand["entity_id"]))].copy()
    print(f"\n(k) Prior phase-5 wave-1 entities ({len(prior_wave1)}): {len(included_from_prior)} included, {len(excluded_from_prior)} excluded under v2")

    print("\n  -- 5 INCLUDED from prior dropouts (sample by AUM) --")
    inc_sample = included_from_prior.copy()
    inc_sample["combined"] = inc_sample["institution_aum_usd"].fillna(0) + inc_sample["fund_rollup_aum_usd"].fillna(0)
    for _, r in inc_sample.sort_values("combined", ascending=False).head(5).iterrows():
        print(f"    ${r['combined']/1e9:>8,.2f}B  eid={int(r['entity_id']):>6d}  "
              f"{(r['canonical_name'] or '')[:55]:<55s} kw={r['signal_C_matched_keyword']}")

    print("\n  -- 5 EXCLUDED from prior phase-5 wave-1 (sample by AUM) --")
    exc_sample = excluded_from_prior.copy()
    exc_sample["combined"] = exc_sample["institution_aum_usd"].fillna(0) + exc_sample["fund_rollup_aum_usd"].fillna(0)
    for _, r in exc_sample.sort_values("combined", ascending=False).head(5).iterrows():
        print(f"    ${r['combined']/1e9:>8,.2f}B  eid={int(r['entity_id']):>6d}  "
              f"{(r['canonical_name'] or '')[:55]:<55s}")

    # Phase 1 STOP gate
    n_cand = len(cand)
    if n_cand < 100 or n_cand > 250:
        print(f"\nABORT — Wave 1 candidate count {n_cand} outside [100, 250] gate.")
        print("Refined keyword set v2 calibration may still be off — report to chat.")
        raise SystemExit(2)

    print(f"\nPhase 1 OK — proceed to Phase 2 dry-run.")


if __name__ == "__main__":
    main()
