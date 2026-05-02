"""Phase 1.2 — cross-reference CEF universe against fund_holdings_v2 (latest snapshot).

READ-ONLY. No DB writes.
For each CEF CIK from cef_universe.csv, classify into Tier A/B/C/D
based on series_id composition in fund_holdings_v2 where is_latest=TRUE.

Phase 1.3: also compute Tier A subtable with accession-prefix breakdown
and SYN_companion flag.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
DB = ROOT / "data" / "13f.duckdb"
WORK = ROOT / "data" / "working" / "cef_scoping"
UNIVERSE = WORK / "cef_universe.csv"
TIER_A_OUT = WORK / "tier_a_cohort.csv"
TIERS_OUT = WORK / "tiers_summary.csv"


def main() -> int:
    if not UNIVERSE.exists():
        print(f"ERROR: {UNIVERSE} missing — run Phase 1.1 first", flush=True)
        return 1

    universe = pd.read_csv(UNIVERSE)
    print(f"Universe loaded: {len(universe):,} CIKs", flush=True)

    con = duckdb.connect(str(DB), read_only=True)

    # Pad CIKs to 10 digits as stored, but keep raw int form too — fund_cik is VARCHAR.
    # Build a temp DataFrame and register it.
    cik_df = pd.DataFrame({
        "cik_int": universe["CIK"].astype(int),
        "cik_str": universe["CIK"].astype(int).astype(str).str.zfill(10),
        "cik_unpadded": universe["CIK"].astype(int).astype(str),
        "registrant_name": universe["registrant_name"].astype(str),
    })
    con.register("cef_universe_df", cik_df)

    # Detect what fund_cik looks like in prod — pad or no pad.
    sample_cik_format = con.execute("""
        SELECT fund_cik FROM fund_holdings_v2 WHERE is_latest = TRUE LIMIT 5
    """).fetchall()
    print(f"  fund_cik sample: {sample_cik_format}", flush=True)

    # Build per-CIK summary. Try both padded and unpadded for safety.
    summary = con.execute("""
        WITH u AS (
            SELECT DISTINCT cik_int, cik_str, cik_unpadded, registrant_name FROM cef_universe_df
        ),
        h AS (
            SELECT
                fund_cik,
                series_id,
                accession_number,
                market_value_usd
            FROM fund_holdings_v2
            WHERE is_latest = TRUE
              AND (fund_cik IN (SELECT cik_str FROM u)
                   OR fund_cik IN (SELECT cik_unpadded FROM u))
        ),
        agg AS (
            SELECT
                fund_cik,
                COUNT(*) AS rows_total,
                SUM(CASE WHEN series_id = 'UNKNOWN' THEN 1 ELSE 0 END) AS rows_unknown,
                SUM(CASE WHEN series_id LIKE 'SYN_%' THEN 1 ELSE 0 END) AS rows_syn,
                SUM(CASE WHEN series_id NOT IN ('UNKNOWN') AND series_id NOT LIKE 'SYN_%' THEN 1 ELSE 0 END) AS rows_canonical,
                SUM(market_value_usd) AS aum_total
            FROM h
            GROUP BY fund_cik
        )
        SELECT
            u.cik_int,
            u.cik_str,
            u.registrant_name,
            COALESCE(a.rows_total, 0) AS rows_total,
            COALESCE(a.rows_unknown, 0) AS rows_unknown,
            COALESCE(a.rows_syn, 0) AS rows_syn,
            COALESCE(a.rows_canonical, 0) AS rows_canonical,
            COALESCE(a.aum_total, 0.0) AS aum_total
        FROM u
        LEFT JOIN agg a ON a.fund_cik = u.cik_str OR a.fund_cik = u.cik_unpadded
    """).fetchdf()

    # Classify into tiers
    def classify(r):
        if r.rows_total == 0:
            return "D"
        if r.rows_unknown > 0:
            return "A"
        if r.rows_syn > 0:
            return "B"
        return "C"

    summary["tier"] = summary.apply(classify, axis=1)

    # Tier counts/AUM
    tiers = summary.groupby("tier").agg(
        n_ciks=("cik_int", "count"),
        rows_total=("rows_total", "sum"),
        rows_unknown=("rows_unknown", "sum"),
        rows_syn=("rows_syn", "sum"),
        rows_canonical=("rows_canonical", "sum"),
        aum_total=("aum_total", "sum"),
    ).reset_index()
    print("\n=== Tier summary ===")
    print(tiers.to_string(index=False))
    tiers.to_csv(TIERS_OUT, index=False)

    # Sample 5 per tier
    for t in ("A", "B", "C", "D"):
        sub = summary[summary["tier"] == t].sort_values("aum_total", ascending=False).head(5)
        print(f"\n=== Tier {t} sample (top 5 by AUM) ===")
        print(sub[["cik_int", "registrant_name", "rows_total", "rows_unknown", "rows_syn", "rows_canonical", "aum_total"]].to_string(index=False))

    # Phase 1.3 — Tier A deep dive
    tier_a = summary[summary["tier"] == "A"].copy()
    print(f"\n=== Tier A deep dive: {len(tier_a)} CIKs ===")
    if not tier_a.empty:
        a_ciks_str = set(tier_a["cik_str"].tolist())
        a_ciks_unp = set(str(int(c)) for c in tier_a["cik_int"].tolist())
        # accession-prefix breakdown for unknown rows
        prefix = con.execute("""
            SELECT
                fund_cik,
                COUNT(*) AS unknown_rows,
                SUM(CASE WHEN accession_number LIKE 'BACKFILL_MIG015_UNKNOWN_%' THEN 1 ELSE 0 END) AS mig015_unknown_prefix,
                SUM(CASE WHEN accession_number LIKE 'BACKFILL_%' AND accession_number NOT LIKE 'BACKFILL_MIG015_UNKNOWN_%' THEN 1 ELSE 0 END) AS other_backfill_prefix,
                SUM(CASE WHEN accession_number NOT LIKE 'BACKFILL_%' THEN 1 ELSE 0 END) AS edgar_accession
            FROM fund_holdings_v2
            WHERE is_latest = TRUE
              AND series_id = 'UNKNOWN'
              AND fund_cik IN (SELECT unnest(?))
            GROUP BY fund_cik
        """, [list(a_ciks_str | a_ciks_unp)]).fetchdf()
        print("\nTier A — UNKNOWN-row accession prefix breakdown:")
        print(prefix.to_string(index=False))

        # SYN companion flag — does this CIK also have SYN_ rows?
        tier_a["has_SYN_companion"] = tier_a["rows_syn"] > 0
        out = tier_a.merge(prefix, left_on="cik_str", right_on="fund_cik", how="left", suffixes=("", "_p"))
        if "fund_cik" in out.columns:
            out = out.drop(columns=["fund_cik"])
        # also try the unpadded join for any missed
        missed = out[out["unknown_rows"].isna()]
        if not missed.empty:
            out2 = missed.drop(columns=["unknown_rows", "mig015_unknown_prefix", "other_backfill_prefix", "edgar_accession"]) \
                .merge(prefix, left_on="cik_int", right_on="fund_cik", how="left").drop(columns=["fund_cik"], errors="ignore")
            out = pd.concat([out[~out["unknown_rows"].isna()], out2], ignore_index=True)
        out = out.sort_values("rows_unknown", ascending=False)
        out.to_csv(TIER_A_OUT, index=False)
        print(f"\nWrote {TIER_A_OUT}")
        print("\nFull Tier A table (sorted by rows_unknown desc):")
        print(out.to_string(index=False))

    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
