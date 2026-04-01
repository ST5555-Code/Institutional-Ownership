#!/usr/bin/env python3
"""
fetch_adv.py — Download SEC bulk ADV data, parse key fields, classify managers,
               flag activists, and save to DuckDB.

Run: python3 scripts/fetch_adv.py
"""

import os
import sys
import time
import zipfile
import io
import re
import requests
import pandas as pd
import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
REF_DIR = os.path.join(DATA_DIR, "reference")
DB_PATH = os.path.join(DATA_DIR, "13f.duckdb")

SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_DELAY = 0.5  # seconds between SEC requests

ADV_ZIP_URL = (
    "https://www.sec.gov/files/investment/data/other/"
    "information-about-registered-investment-advisers-exempt-reporting-advisers/"
    "ia030226.zip"
)

# ---------------------------------------------------------------------------
# Activist seed list — we look up CRD by name match
# ---------------------------------------------------------------------------
ACTIVIST_NAMES = [
    "Elliott Investment Management",
    "Elliott Management",
    "Icahn Capital",
    "Icahn Enterprises",
    "Starboard Value",
    "ValueAct Capital",
    "ValueAct Holdings",
    "Jana Partners",
    "Engine No. 1",
    "Engine No 1",
    "Third Point",
    "Pershing Square",
    "Corvex Management",
    "Legion Partners",
    "Land & Buildings",
    "Land and Buildings",
    "Sachem Head",
    "Barington Capital",
    "Blue Harbour",
    "Blue Harbor",
    "Ancora Holdings",
    "Ancora Advisors",
]

# ---------------------------------------------------------------------------
# Strategy classification keywords
# ---------------------------------------------------------------------------
PASSIVE_KEYWORDS = ["INDEX", "ETF", "S&P", "RUSSELL", "MSCI", "PASSIVE"]
HEDGE_FUND_KEYWORDS = ["CAPITAL PARTNERS", "MASTER FUND", "OFFSHORE", "CAYMAN"]
QUANT_KEYWORDS = [
    "QUANT", "SYSTEMATIC", "ALGORITHMIC", "AQR", "TWO SIGMA",
    "RENAISSANCE", "DE SHAW", "WINTON",
]
MULTI_STRAT_KEYWORDS = ["MULTI-STRATEGY", "MULTI STRATEGY", "DIVERSIFIED"]
PE_KEYWORDS = ["PRIVATE EQUITY", "BUYOUT", "VENTURE", "GROWTH EQUITY"]


def download_adv_zip():
    """Download the most recent ADV bulk ZIP from SEC."""
    print(f"Downloading ADV data from SEC...")
    print(f"  URL: {ADV_ZIP_URL}")
    r = requests.get(ADV_ZIP_URL, headers=SEC_HEADERS, timeout=120)
    r.raise_for_status()
    print(f"  Downloaded {len(r.content) / 1_000_000:.1f} MB")
    time.sleep(SEC_DELAY)
    return r.content


def extract_csv(zip_bytes):
    """Extract the CSV from the ADV ZIP file."""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    csv_names = [n for n in z.namelist() if n.upper().endswith(".CSV")]
    if not csv_names:
        raise FileNotFoundError(f"No CSV found in ZIP. Files: {z.namelist()}")
    csv_name = csv_names[0]
    print(f"  Extracting: {csv_name}")

    # Save raw CSV to reference dir
    csv_path = os.path.join(REF_DIR, "adv_raw.csv")
    with z.open(csv_name) as src, open(csv_path, "wb") as dst:
        dst.write(src.read())
    print(f"  Saved raw CSV to {csv_path}")
    return csv_path


def load_and_parse(csv_path):
    """Load CSV, select key columns, compute derived fields."""
    print("Loading CSV into pandas...")

    # The SEC CSV uses quoted fields and has 452 columns.
    # Read with low_memory=False to let pandas infer types.
    df_raw = pd.read_csv(csv_path, low_memory=False, dtype=str, encoding="latin-1")
    print(f"  Raw rows: {len(df_raw):,}")
    print(f"  Raw columns: {len(df_raw.columns)}")

    # Map SEC column names to our field names
    col_map = {
        "Organization CRD#": "crd_number",
        "SEC#": "sec_file_number",
        "CIK#": "cik",
        "Primary Business Name": "firm_name",
        "Legal Name": "legal_name",
        "Main Office City": "city",
        "Main Office State": "state",
        "Main Office Street Address 1": "address",
        "5F(2)(a)": "adv_5f_raum_discrtnry",
        "5F(2)(b)": "adv_5f_raum_non_discrtnry",
        "5F(2)(c)": "adv_5f_raum",
        "5F(2)(f)": "adv_5f_num_accts",
        "Any Hedge Funds": "has_hedge_funds",
        "Any PE Funds": "has_pe_funds",
        "Any VC Funds": "has_vc_funds",
    }

    # Check which columns exist
    missing = [c for c in col_map if c not in df_raw.columns]
    if missing:
        print(f"  WARNING: Missing columns: {missing}")
        # Try to find close matches
        for m in missing:
            close = [c for c in df_raw.columns if m.lower() in c.lower()]
            if close:
                print(f"    '{m}' might be: {close[:3]}")

    # Select and rename
    available = {k: v for k, v in col_map.items() if k in df_raw.columns}
    df = df_raw[list(available.keys())].rename(columns=available).copy()

    # Clean numeric AUM fields
    for col in ["adv_5f_raum", "adv_5f_raum_discrtnry", "adv_5f_raum_non_discrtnry", "adv_5f_num_accts"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("$", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Compute pct_discretionary
    df["pct_discretionary"] = 0.0
    mask = df["adv_5f_raum"] > 0
    df.loc[mask, "pct_discretionary"] = (
        df.loc[mask, "adv_5f_raum_discrtnry"] / df.loc[mask, "adv_5f_raum"] * 100
    ).round(2)

    print(f"  Parsed rows: {len(df):,}")
    print(f"  Firms with AUM > 0: {(df['adv_5f_raum'] > 0).sum():,}")
    return df


def classify_strategy(row):
    """Assign strategy_inferred based on name keywords and AUM."""
    name = str(row.get("firm_name", "")).upper()
    pct = row.get("pct_discretionary", 0)
    has_hf = str(row.get("has_hedge_funds", "")).upper() == "Y"
    has_pe = str(row.get("has_pe_funds", "")).upper() == "Y"
    has_vc = str(row.get("has_vc_funds", "")).upper() == "Y"

    # Check passive first
    if any(kw in name for kw in PASSIVE_KEYWORDS) or pct < 10:
        return "passive"

    # Hedge fund
    if has_hf or any(kw in name for kw in HEDGE_FUND_KEYWORDS):
        return "hedge_fund"

    # Quantitative
    if any(kw in name for kw in QUANT_KEYWORDS):
        return "quantitative"

    # Multi-strategy
    if any(kw in name for kw in MULTI_STRAT_KEYWORDS):
        return "multi_strategy"

    # Private equity
    if has_pe or has_vc or any(kw in name for kw in PE_KEYWORDS):
        return "private_equity"

    # Active
    if pct >= 80:
        return "active"

    return "unknown"


def flag_activists(df):
    """Set is_activist = True for known activist managers."""
    df["is_activist"] = False

    for activist_name in ACTIVIST_NAMES:
        pattern = activist_name.upper()
        mask = df["firm_name"].str.upper().str.contains(pattern, na=False, regex=False)
        matches = df.loc[mask]
        if len(matches) > 0:
            df.loc[mask, "is_activist"] = True
            for _, m in matches.iterrows():
                print(f"  Activist flagged: CRD {m['crd_number']} — {m['firm_name']}")
        else:
            print(f"  Not found in ADV data: {activist_name}")

    activist_count = df["is_activist"].sum()
    print(f"\n  Total activists flagged: {activist_count}")
    return df


def save_to_duckdb(df):
    """Save adv_managers table to DuckDB."""
    # Select final columns
    final_cols = [
        "crd_number", "sec_file_number", "cik", "firm_name", "legal_name",
        "city", "state", "address",
        "adv_5f_raum", "adv_5f_raum_discrtnry", "adv_5f_raum_non_discrtnry",
        "adv_5f_num_accts", "pct_discretionary",
        "strategy_inferred", "is_activist",
        "has_hedge_funds", "has_pe_funds", "has_vc_funds",
    ]
    # Only include columns that exist
    final_cols = [c for c in final_cols if c in df.columns]
    df_out = df[final_cols].copy()

    # Also save CSV
    csv_out = os.path.join(REF_DIR, "adv_managers.csv")
    df_out.to_csv(csv_out, index=False)
    print(f"\n  Saved CSV: {csv_out}")

    # Save to DuckDB
    con = duckdb.connect(DB_PATH)
    con.execute("DROP TABLE IF EXISTS adv_managers")
    con.execute("CREATE TABLE adv_managers AS SELECT * FROM df_out")
    row_count = con.execute("SELECT COUNT(*) FROM adv_managers").fetchone()[0]
    print(f"  Saved to DuckDB: {DB_PATH}")
    print(f"  Table adv_managers: {row_count:,} rows")

    # Quick summary
    print("\n--- Summary ---")
    strat_counts = con.execute(
        "SELECT strategy_inferred, COUNT(*) as cnt FROM adv_managers GROUP BY 1 ORDER BY 2 DESC"
    ).fetchdf()
    print(strat_counts.to_string(index=False))

    activist_list = con.execute(
        "SELECT crd_number, firm_name, adv_5f_raum FROM adv_managers WHERE is_activist = true ORDER BY adv_5f_raum DESC"
    ).fetchdf()
    print(f"\nActivist managers ({len(activist_list)}):")
    print(activist_list.to_string(index=False))

    con.close()


def main():
    print("=" * 60)
    print("SCRIPT 1 — fetch_adv.py")
    print("=" * 60)

    # Step 1: Download
    zip_bytes = download_adv_zip()

    # Step 2: Extract
    csv_path = extract_csv(zip_bytes)

    # Step 3: Parse
    df = load_and_parse(csv_path)

    # Step 4: Classify strategy
    print("\nClassifying manager strategies...")
    df["strategy_inferred"] = df.apply(classify_strategy, axis=1)

    # Step 5: Flag activists
    print("\nFlagging activist managers...")
    df = flag_activists(df)

    # Step 6: Save
    save_to_duckdb(df)

    print("\nDone.")


if __name__ == "__main__":
    main()
