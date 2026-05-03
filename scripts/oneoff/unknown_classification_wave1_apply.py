"""Wave 1 Phase 2/3 apply — Tier A name-pattern + ADV strategy auto-resolution.

Two modes:
  --dry-run   write manifest CSV only; no DB writes
  (default)   execute SCD update in a single transaction

Per docs/findings/unknown-classification-discovery.md §5.1+§6 + chat
refined-keyword-set v2 (2026-05-03).

Refined ACTIVE keyword set v2:
  Phrase-only: Income Fund, Income Trust, Closed-End, Closed End, CEF,
               Municipal, MuniYield, Interval Fund, BDC,
               Business Development, High Yield, High Income,
               Opportunity Fund, Opportunity Trust, Opportunity Inc.
  Qualified Trust: right-anchored Trust suffix (Trust, Trust Inc,
               Trust Inc., Trust, Inc., Trust LLC, Trust LP, Trust L.P.)
               with optional trailing punctuation,
               AND name does NOT contain Bank | Bancorp | Trust Company.
  Qualified Private: Private Capital | Private Credit |
               Private Equity Fund | Private Markets | Private Lending |
               Private Income.

PASSIVE keyword set:
  SPDR, iShares, Vanguard, ETF, Index, PowerShares, Direxion,
  ProShares, ProFund, WisdomTree, Innovator.

ADV path: signal_A_hit AND adv_strategy_inferred IN
  {active, passive, quantitative, hedge_fund, strategic} -> classification = adv value verbatim.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import re
import sys
import duckdb
import pandas as pd

WT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/sleepy-wright-49f441")
DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
TIER_A_CSV = WT / "data/working/unknown-classification-tier-a.csv"
MANIFEST_CSV = WT / "data/working/unknown-classification-wave1-manifest.csv"
SENTINEL = "DATE '9999-12-31'"

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
TRUST_SUFFIXES = [
    "Trust", "Trust Inc", "Trust Inc.", "Trust, Inc.",
    "Trust LLC", "Trust LP", "Trust L.P.",
]
TRUST_EXCLUDE_TOKENS = ["Bank", "Bancorp", "Trust Company"]
PRIVATE_PHRASES = [
    "Private Capital", "Private Credit", "Private Equity Fund",
    "Private Markets", "Private Lending", "Private Income",
]
ADV_STRATEGY_ALLOW = {"active", "passive", "quantitative", "hedge_fund", "strategic"}

ACTIVE_PATTERNS = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in ACTIVE_PHRASES]
PASSIVE_PATTERNS = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in PASSIVE_PHRASES]
PRIVATE_PATTERNS = [(p, re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)) for p in PRIVATE_PHRASES]
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
    return first_match(name, ACTIVE_PATTERNS) or trust_match(name) or private_match(name)


def build_manifest(con) -> pd.DataFrame:
    """Compose the Wave 1 manifest. Returns the manifest DataFrame."""
    tier_a = pd.read_csv(TIER_A_CSV)
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

    open_check = con.execute(
        f"""
        SELECT entity_id FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
          AND entity_id IN (SELECT UNNEST(?))
        """,
        [eids],
    ).fetch_df()
    still_open = set(open_check["entity_id"].tolist())
    df = tier_a[tier_a["entity_id"].isin(still_open)].copy()

    df["active_match"] = df["canonical_name"].apply(active_keyword_match)
    df["passive_match"] = df["canonical_name"].apply(lambda n: first_match(n, PASSIVE_PATTERNS))
    df["adv_strategy_clean"] = df["adv_strategy_inferred"].fillna("").astype(str)
    df["adv_path_eligible"] = df["adv_hit"] & df["adv_strategy_clean"].isin(ADV_STRATEGY_ALLOW)

    rows = []
    for _, r in df.iterrows():
        sig_d = r.get("signal_D_value")
        sig_d_norm = sig_d.strip().lower() if isinstance(sig_d, str) else None

        # Priority: ADV > active name > passive name.
        if r["adv_path_eligible"]:
            new_cls = r["adv_strategy_clean"]
            rows.append({
                "entity_id": int(r["entity_id"]),
                "canonical_name": r["canonical_name"],
                "current_classification": "unknown",
                "new_classification": new_cls,
                "derived_via": "adv_strategy",
                "source_string": "wave1_adv_strategy",
                "confidence": "exact",
                "signal_C_matched_keyword": r["adv_strategy_clean"],
                "signal_D_value": sig_d if isinstance(sig_d, str) else "",
                "institution_aum_usd": float(r.get("institution_aum_usd") or 0),
                "fund_rollup_aum_usd": float(r.get("fund_rollup_aum_usd") or 0),
            })
        elif r["active_match"]:
            # Conflict check: signal_D non-null and not 'active' -> drop to wave 4e.
            if sig_d_norm and sig_d_norm != "active":
                continue
            rows.append({
                "entity_id": int(r["entity_id"]),
                "canonical_name": r["canonical_name"],
                "current_classification": "unknown",
                "new_classification": "active",
                "derived_via": "name_pattern_active",
                "source_string": "wave1_name_pattern_active",
                "confidence": "high",
                "signal_C_matched_keyword": r["active_match"],
                "signal_D_value": sig_d if isinstance(sig_d, str) else "",
                "institution_aum_usd": float(r.get("institution_aum_usd") or 0),
                "fund_rollup_aum_usd": float(r.get("fund_rollup_aum_usd") or 0),
            })
        elif r["passive_match"]:
            if sig_d_norm and sig_d_norm != "passive":
                continue
            rows.append({
                "entity_id": int(r["entity_id"]),
                "canonical_name": r["canonical_name"],
                "current_classification": "unknown",
                "new_classification": "passive",
                "derived_via": "name_pattern_passive",
                "source_string": "wave1_name_pattern_passive",
                "confidence": "high",
                "signal_C_matched_keyword": r["passive_match"],
                "signal_D_value": sig_d if isinstance(sig_d, str) else "",
                "institution_aum_usd": float(r.get("institution_aum_usd") or 0),
                "fund_rollup_aum_usd": float(r.get("fund_rollup_aum_usd") or 0),
            })

    return pd.DataFrame(rows).sort_values("entity_id").reset_index(drop=True)


def write_manifest(manifest: pd.DataFrame) -> None:
    manifest.to_csv(MANIFEST_CSV, index=False)
    print(f"Wrote manifest: {MANIFEST_CSV}  ({len(manifest):,} rows)")


def assert_entry_gates(con, manifest: pd.DataFrame) -> None:
    """Phase 3 entry gate per plan."""
    # Gate 1: zero conflicts (signal_D contradicts derived) — already filtered out of manifest.
    # Manifest only contains accepted rows; verify by re-running the conflict check.
    bad_conflict = manifest[
        manifest["signal_D_value"].astype(str).str.strip().str.lower().isin(
            {"active", "passive", "strategic", "hedge_fund", "wealth_management",
             "pension_insurance", "private_equity", "quantitative",
             "endowment_foundation", "family_office", "venture_capital", "activist",
             "SWF".lower(), "multi_strategy"}
        )
        & (manifest["signal_D_value"].astype(str).str.strip().str.lower()
           != manifest["new_classification"].str.lower())
    ]
    assert bad_conflict.empty, f"manifest contains {len(bad_conflict)} signal-D conflicts"

    # Gate 2: zero ambiguities — each entity appears at most once in the manifest.
    dup = manifest[manifest["entity_id"].duplicated()]
    assert dup.empty, f"manifest contains {len(dup)} duplicate entity_id rows"

    # Gate 3: zero already-classified entities (every manifest eid open ECH 'unknown').
    eids = manifest["entity_id"].tolist()
    open_unknown = con.execute(
        f"""
        SELECT entity_id FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
          AND entity_id IN (SELECT UNNEST(?))
        """,
        [eids],
    ).fetch_df()
    open_unknown_eids = set(open_unknown["entity_id"].tolist())
    not_open = set(eids) - open_unknown_eids
    assert not not_open, f"{len(not_open)} manifest entities not in open unknown cohort: {sorted(not_open)[:10]}"

    # Gate 4: exactly one open ECH row per manifest eid.
    counts = con.execute(
        f"""
        SELECT entity_id, COUNT(*) AS n
        FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
          AND entity_id IN (SELECT UNNEST(?))
        GROUP BY entity_id
        HAVING COUNT(*) <> 1
        """,
        [eids],
    ).fetch_df()
    assert counts.empty, f"{len(counts)} manifest entities have != 1 open unknown ECH row"

    print(f"Phase 3 entry gates: OK ({len(manifest):,} candidates pass all 4 gates)")


def execute_scd(con, manifest: pd.DataFrame) -> int:
    """Execute the SCD close + open in a single transaction. Returns flipped count."""
    eids = manifest["entity_id"].tolist()
    pre_unknown = con.execute(
        f"""
        SELECT COUNT(*) FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
        """
    ).fetchone()[0]

    pre_cohort = con.execute(
        f"""
        SELECT COUNT(*) FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
          AND entity_id IN (SELECT UNNEST(?))
        """,
        [eids],
    ).fetchone()[0]
    assert pre_cohort == len(manifest), f"pre-execution cohort {pre_cohort} != manifest {len(manifest)}"

    con.execute("BEGIN")
    flipped = 0
    try:
        for _, r in manifest.iterrows():
            eid = int(r["entity_id"])
            new_cls = r["new_classification"]
            confidence = r["confidence"]
            source = r["source_string"]
            con.execute(
                f"""
                UPDATE entity_classification_history
                   SET valid_to = CURRENT_DATE
                 WHERE entity_id = ?
                   AND classification = 'unknown'
                   AND valid_to = {SENTINEL}
                """,
                [eid],
            )
            con.execute(
                f"""
                INSERT INTO entity_classification_history
                    (entity_id, classification, is_activist, confidence, source,
                     is_inferred, valid_from, valid_to)
                VALUES (?, ?, FALSE, ?, ?, FALSE, CURRENT_DATE, {SENTINEL})
                """,
                [eid, new_cls, confidence, source],
            )
            flipped += 1

        # Post-execution guards before COMMIT.
        post_unknown = con.execute(
            f"""
            SELECT COUNT(*) FROM entity_classification_history
            WHERE classification='unknown' AND valid_to = {SENTINEL}
            """
        ).fetchone()[0]
        expected_post = pre_unknown - flipped
        assert post_unknown == expected_post, (
            f"post-unknown count {post_unknown} != expected {expected_post}"
        )

        # Every manifest eid: exactly one open ECH row with new classification, no leftover unknown.
        bad = con.execute(
            f"""
            WITH m AS (SELECT UNNEST(?) AS eid),
            open_rows AS (
                SELECT entity_id, classification, COUNT(*) AS n
                FROM entity_classification_history
                WHERE valid_to = {SENTINEL}
                  AND entity_id IN (SELECT eid FROM m)
                GROUP BY entity_id, classification
            )
            SELECT m.eid,
                   (SELECT SUM(n) FROM open_rows o WHERE o.entity_id = m.eid) AS total_open,
                   (SELECT SUM(n) FROM open_rows o WHERE o.entity_id = m.eid
                        AND o.classification = 'unknown') AS still_unknown
            FROM m
            """,
            [eids],
        ).fetch_df()
        # Expect total_open >= 1 (at minimum the new row) and still_unknown is NULL/0.
        bad_rows = bad[(bad["total_open"].fillna(0) < 1) | (bad["still_unknown"].fillna(0) > 0)]
        assert bad_rows.empty, f"{len(bad_rows)} manifest entities have invalid post-state"

        con.execute("COMMIT")
        print(f"Phase 3 commit OK — flipped {flipped:,} entities")
    except Exception:
        con.execute("ROLLBACK")
        raise

    return flipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        con = duckdb.connect(str(DB), read_only=True)
        manifest = build_manifest(con)
        write_manifest(manifest)
        # Print entry-gate status (read-only check).
        try:
            assert_entry_gates(con, manifest)
        except AssertionError as e:
            print(f"GATE FAIL: {e}")
            sys.exit(2)
        # Print summary.
        print(f"\nManifest summary:")
        print(f"  count           : {len(manifest):,}")
        print(f"  by derived_via  : {manifest['derived_via'].value_counts().to_dict()}")
        print(f"  by classification: {manifest['new_classification'].value_counts().to_dict()}")
        inst = manifest['institution_aum_usd'].sum() / 1e9
        fund = manifest['fund_rollup_aum_usd'].sum() / 1e9
        print(f"  AUM             : inst=${inst:,.2f}B  fund=${fund:,.2f}B")
        return

    # Execute path: re-derive manifest fresh from current DB state.
    con = duckdb.connect(str(DB), read_only=False)
    manifest = build_manifest(con)
    write_manifest(manifest)
    assert_entry_gates(con, manifest)
    execute_scd(con, manifest)
    con.close()


if __name__ == "__main__":
    main()
