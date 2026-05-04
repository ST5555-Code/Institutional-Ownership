"""CP-5 Bundle C — Probe 7.3: securities.canonical_type defect.

Read-only investigation. Quantifies the institutional-share-class mis-classification
flagged in Bundle A §5: VSMPX, VGTSX, VTBIX etc. are tagged 'COM' (common stock)
in `securities.canonical_type` instead of 'MUTUAL_FUND'. Locates writers, traces
read-side blast radius.

Outputs:
  data/working/cp-5-bundle-c-canonical-type-defect.csv
  data/working/cp-5-bundle-c-canonical-type-readers.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
COVERAGE_QUARTER = "2025Q4"
WORKDIR = Path("data/working")


# Known institutional share-class tickers from Bundle A §5
KNOWN_FUND_TICKERS = [
    "VSMPX", "VGTSX", "VTBIX", "VTSMX", "VTBLX", "VTILX", "VTIIX", "VTAPX",
    "VRTPX", "VFINX", "VTSAX", "VTIAX", "VBTLX", "VFFSX", "VITPX", "VITSX",
    "FSKAX", "FXAIX", "FXNAX", "FZILX", "FZROX",  # Fidelity index/zero
    "SWTSX", "SWPPX", "SWAGX",  # Schwab
    "SPTM", "AGG", "BND", "VTI", "VOO",  # major ETFs (legitimately ETF in canonical_type)
]


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # === 7.3a — defect scope ===
    print("=" * 78)
    print("PHASE 7.3a — securities.canonical_type defect scope")
    print("=" * 78)

    # 1) Distribution
    dist = con.execute("""
        SELECT canonical_type, canonical_type_source, COUNT(*) AS n
        FROM securities GROUP BY 1, 2 ORDER BY 3 DESC
    """).fetchdf()
    print(f"\n  canonical_type × source distribution:")
    pd.set_option("display.width", 220)
    print(dist.to_string(index=False))

    # 2) Known fund tickers mis-classified as 'COM'
    tickers_in_clause = ",".join(f"'{t}'" for t in KNOWN_FUND_TICKERS)
    misclass = con.execute(f"""
        SELECT s.cusip, s.ticker, s.issuer_name, s.canonical_type, s.canonical_type_source,
               s.security_type, s.security_type_inferred
        FROM securities s
        WHERE s.ticker IN ({tickers_in_clause})
        ORDER BY s.ticker
    """).fetchdf()
    print(f"\n  Known fund tickers — current securities row state:")
    print(misclass.to_string(index=False))

    # 3) Estimate broader cohort: securities flagged COM whose issuer_name
    #    contains fund-typed keywords (FUND, ETF, INDEX, TRUST + cap-class hints)
    cohort_estimate = con.execute("""
        SELECT canonical_type,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE issuer_name ILIKE '%FUND%' OR issuer_name ILIKE '%TRUST%'
                                 OR issuer_name ILIKE '%ETF%' OR issuer_name ILIKE '%INDEX%'
                                 OR issuer_name ILIKE '%PORTFOLIO%') AS likely_fund_like
        FROM securities GROUP BY 1 ORDER BY 2 DESC
    """).fetchdf()
    print(f"\n  Issuer-name fund-keyword overlap by canonical_type:")
    print(cohort_estimate.to_string(index=False))

    # 4) AUM-weighted blast radius — how much fund-tier AUM sits in 'COM'
    #    securities that are actually fund-typed by name?
    blast = con.execute(f"""
        SELECT
          COUNT(*) AS n_rows,
          COUNT(DISTINCT fh.cusip) AS n_cusips,
          SUM(fh.market_value_usd) / 1e9 AS aum_b
        FROM fund_holdings_v2 fh
        JOIN securities s ON s.cusip = fh.cusip
        WHERE fh.is_latest AND fh.quarter = '{COVERAGE_QUARTER}'
          AND fh.asset_category = 'EC'
          AND s.canonical_type = 'COM'
          AND (s.issuer_name ILIKE '%FUND%' OR s.issuer_name ILIKE '%TRUST%'
               OR s.issuer_name ILIKE '%ETF%' OR s.issuer_name ILIKE '%INDEX%'
               OR s.issuer_name ILIKE '%PORTFOLIO%')
      """).fetchone()
    print(f"\n  Blast: 2025Q4 EC fund_holdings_v2 rows joined to COM-typed fund-named securities:")
    print(f"    rows: {blast[0]:,}; distinct cusips: {blast[1]:,}; AUM: ${blast[2] or 0:,.1f}B")

    # Top 25 mis-classified by AUM
    top = con.execute(f"""
        SELECT s.cusip, s.ticker, s.issuer_name,
               COUNT(*) AS n_rows, SUM(fh.market_value_usd)/1e9 AS aum_b
        FROM fund_holdings_v2 fh
        JOIN securities s ON s.cusip = fh.cusip
        WHERE fh.is_latest AND fh.quarter = '{COVERAGE_QUARTER}'
          AND fh.asset_category = 'EC'
          AND s.canonical_type = 'COM'
          AND (s.issuer_name ILIKE '%FUND%' OR s.issuer_name ILIKE '%TRUST%'
               OR s.issuer_name ILIKE '%ETF%' OR s.issuer_name ILIKE '%INDEX%'
               OR s.issuer_name ILIKE '%PORTFOLIO%')
        GROUP BY 1,2,3 ORDER BY aum_b DESC NULLS LAST LIMIT 50
    """).fetchdf()
    print(f"\n  Top-25 mis-classified-as-COM by 2025Q4 EC AUM:")
    print(top.head(25).to_string(index=False))
    top.to_csv(WORKDIR / "cp-5-bundle-c-canonical-type-defect.csv", index=False)

    # === 7.3b — locate writers ===
    print()
    print("=" * 78)
    print("PHASE 7.3b — canonical_type writer location (grep)")
    print("=" * 78)
    print()
    print("  Writers identified via grep on 'canonical_type' = ... assignment:")
    print("    scripts/normalize_securities.py — primary classifier (canonical_type_source")
    print("      = 'normalize_securities')")
    print("    scripts/build_cusip.py — CUSIP/OpenFIGI ingestion (canonical_type_source")
    print("      = 'cusip_classifier' / 'openfigi')")
    print("    scripts/pipeline/cusip_classifier.py — runtime classifier helper")
    print("    migrations/003_canonical_type.sql — initial backfill (one-shot)")
    print()
    print("  Hypothesis: OpenFIGI's marketSector='Equity' → classifier maps to 'COM'.")
    print("  Institutional fund share classes (VSMPX, VTSMX) ARE marketSector='Equity'")
    print("  in OpenFIGI but securityType2='Mutual Fund'. Classifier likely keys on")
    print("  marketSector only and misses securityType2.")

    # === 7.3c — read-side blast radius ===
    print()
    print("=" * 78)
    print("PHASE 7.3c — readers filtering on canonical_type")
    print("=" * 78)

    # Empirical grep: canonical_type / is_equity / is_priceable are NOT consumed
    # by any user-facing reader (api_*.py, queries/, queries_helpers.py).
    # Only pipeline/classification code reads them. Read-side blast radius is
    # therefore zero for CP-5 reads. The defect affects classification-pipeline
    # invariants and any future reader that begins to filter on securities flags.
    readers = pd.DataFrame([
        {"path": "scripts/enrich_holdings.py",
         "filter": "canonical_type, is_equity, is_priceable",
         "purpose": "loader: writes per-holding sector/industry from securities classification",
         "user_facing": False},
        {"path": "scripts/validate_classifications.py",
         "filter": "canonical_type assertion suite",
         "purpose": "data-quality gate; asserts known fund tickers ARE classified MUTUAL_FUND/ETF/CEF",
         "user_facing": False},
        {"path": "scripts/build_classifications.py",
         "filter": "canonical_type, is_equity",
         "purpose": "feeds entity-level classifier",
         "user_facing": False},
        {"path": "scripts/oneoff/cp_5_bundle_a_probe1_r5_defects.py",
         "filter": "canonical_type IN ('ETF','MUTUAL_FUND','CEF') for FoF Pass A",
         "purpose": "Bundle A FoF detection; mis-classification reduces Pass A coverage 2/3 (Bundle A §1.1)",
         "user_facing": False},
        {"path": "(future) CP-5 reader if it filters on canonical_type='COM'",
         "filter": "n/a",
         "purpose": "would silently include institutional fund shares as common stock",
         "user_facing": True},
    ])
    print()
    print(readers.to_string(index=False))
    readers.to_csv(WORKDIR / "cp-5-bundle-c-canonical-type-readers.csv", index=False)

    print()
    print(f"  Wrote {WORKDIR / 'cp-5-bundle-c-canonical-type-defect.csv'}")
    print(f"  Wrote {WORKDIR / 'cp-5-bundle-c-canonical-type-readers.csv'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
