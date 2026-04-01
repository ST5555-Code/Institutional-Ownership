#!/usr/bin/env python3
"""
build_cusip.py — Build securities table mapping CUSIP to ticker and metadata.
                 Sources: SEC 13F securities list, OpenFIGI API, yfinance.

Run: python3 scripts/build_cusip.py

MANUAL TICKER OVERRIDES
-----------------------
OpenFIGI sometimes returns foreign exchange codes instead of US tickers
(e.g. NDQ instead of QQQ, CHV instead of CVX). These are corrected via
a manual override file:

    data/reference/ticker_overrides.csv

The override file has highest priority — any CUSIP listed there will use
the correct_ticker value regardless of what OpenFIGI returns.

To add a new override:
  1. Open data/reference/ticker_overrides.csv
  2. Add a row with: cusip, wrong_ticker, correct_ticker, company_name, note, security_type_override
     - cusip: the 9-character CUSIP from the holdings table
     - wrong_ticker: the bad ticker currently assigned (leave blank if no ticker exists)
     - correct_ticker: the correct US ticker symbol
     - company_name: human-readable name
     - note: why the override is needed (e.g. "OpenFIGI foreign code")
     - security_type_override: equity, etf, derivative, or money_market
  3. Re-run this script — overrides are applied after the OpenFIGI step

To find a CUSIP for a company, run:
    SELECT cusip, issuer_name FROM holdings WHERE UPPER(issuer_name) LIKE '%COMPANY%'
"""

import os
import sys
import time
import json
import requests
import pandas as pd
import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")
REF_DIR = os.path.join(BASE_DIR, "data", "reference")

SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_DELAY = 0.5

# SIC codes for sector flags
ENERGY_SICS = {1311, 1321, 1381, 1382, 1389, 4922, 4923, 4924, 4941, 5171, 5172, 2911}
MEDIA_SICS = {4833, 4832, 4813, 4899, 7812, 7922, 2711, 2721}

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_RATE_LIMIT = 25  # requests per minute
OPENFIGI_BATCH_SIZE = 10  # CUSIPs per request


def get_unique_cusips(con):
    """Get unique CUSIPs from holdings with issuer names."""
    df = con.execute("""
        SELECT
            cusip,
            MAX(issuer_name) as issuer_name,
            MAX(security_type) as security_type,
            COUNT(*) as holdings_count,
            SUM(market_value_usd) as total_value
        FROM holdings
        GROUP BY cusip
        ORDER BY total_value DESC
    """).fetchdf()
    print(f"  Unique CUSIPs in holdings: {len(df):,}")
    return df


def lookup_openfigi(cusips, batch_num=0):
    """Look up tickers via OpenFIGI API for a batch of CUSIPs."""
    jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
    headers = {"Content-Type": "application/json"}

    try:
        r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        if r.status_code == 429:
            print(f"    Rate limited at batch {batch_num}, sleeping 60s...")
            time.sleep(60)
            r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        r.raise_for_status()
        results = r.json()
    except Exception as e:
        print(f"    OpenFIGI error at batch {batch_num}: {e}")
        return {}

    ticker_map = {}
    for cusip, result in zip(cusips, results):
        if "data" in result and len(result["data"]) > 0:
            item = result["data"][0]
            ticker = item.get("ticker", "")
            if ticker:
                ticker_map[cusip] = {
                    "ticker": ticker,
                    "name": item.get("name", ""),
                    "exchCode": item.get("exchCode", ""),
                    "securityType": item.get("securityType", ""),
                    "marketSector": item.get("marketSector", ""),
                }
    return ticker_map


def enrich_with_openfigi(df_cusips):
    """Look up tickers for CUSIPs without one via OpenFIGI."""
    print("\nLooking up tickers via OpenFIGI API...")

    # Get top CUSIPs by value (limit to avoid excessive API calls)
    cusips_to_lookup = df_cusips["cusip"].tolist()
    # Limit to top 5000 by value to stay within API limits
    max_lookups = 5000
    cusips_to_lookup = cusips_to_lookup[:max_lookups]
    print(f"  Looking up {len(cusips_to_lookup):,} CUSIPs")

    all_results = {}
    batches = [cusips_to_lookup[i:i + OPENFIGI_BATCH_SIZE]
               for i in range(0, len(cusips_to_lookup), OPENFIGI_BATCH_SIZE)]

    for batch_num, batch in enumerate(batches):
        results = lookup_openfigi(batch, batch_num)
        all_results.update(results)

        # Rate limiting: 25 req/min
        if (batch_num + 1) % OPENFIGI_RATE_LIMIT == 0:
            print(f"    Pausing for rate limit after {batch_num + 1} batches ({len(all_results):,} matches)...")
            time.sleep(62)

        if (batch_num + 1) % 50 == 0:
            print(f"    Processed {batch_num + 1}/{len(batches)} batches ({len(all_results):,} matches)")

        # Small delay between requests
        time.sleep(0.1)

    print(f"  OpenFIGI results: {len(all_results):,} CUSIPs matched to tickers")
    return all_results


def enrich_with_yfinance(tickers):
    """Get sector, exchange, and other metadata from yfinance."""
    import yfinance as yf

    print(f"\nEnriching {len(tickers):,} tickers with yfinance metadata...")

    results = {}
    batch_size = 100
    ticker_list = list(tickers)

    for i in range(0, len(ticker_list), batch_size):
        batch = ticker_list[i:i + batch_size]
        try:
            # Use download to validate tickers exist
            for tkr in batch:
                try:
                    info = yf.Ticker(tkr).info
                    if info and info.get("regularMarketPrice"):
                        results[tkr] = {
                            "sector": info.get("sector", ""),
                            "industry": info.get("industry", ""),
                            "exchange": info.get("exchange", ""),
                            "market_cap": info.get("marketCap", 0),
                            "sic_code": None,  # yfinance doesn't always provide SIC
                        }
                except Exception:
                    pass
        except Exception as e:
            print(f"    yfinance batch error: {e}")

        if (i + batch_size) % 500 == 0:
            print(f"    Processed {min(i + batch_size, len(ticker_list)):,}/{len(ticker_list):,} ({len(results):,} enriched)")

    print(f"  yfinance enrichment: {len(results):,} tickers enriched")
    return results


def build_securities_table(con, df_cusips, figi_results):
    """Build the securities table in DuckDB."""
    print("\nBuilding securities table...")

    records = []
    for _, row in df_cusips.iterrows():
        cusip = row["cusip"]
        figi = figi_results.get(cusip, {})
        ticker = figi.get("ticker", "")

        records.append({
            "cusip": cusip,
            "issuer_name": row["issuer_name"],
            "ticker": ticker if ticker else None,
            "security_type": figi.get("securityType", row.get("security_type", "")),
            "exchange": figi.get("exchCode", ""),
            "market_sector": figi.get("marketSector", ""),
            "sector": None,  # Filled by yfinance
            "industry": None,
            "sic_code": None,
            "is_energy": False,
            "is_media": False,
            "holdings_count": int(row["holdings_count"]),
            "total_value": float(row["total_value"]) if pd.notna(row["total_value"]) else 0,
        })

    df_sec = pd.DataFrame(records)

    # Enrich top tickers with yfinance (limit to 500 most-held to avoid slow API)
    top_tickers = df_sec[df_sec["ticker"].notna()].nlargest(500, "total_value")["ticker"].unique().tolist()
    if top_tickers:
        yf_data = enrich_with_yfinance(top_tickers)
        for tkr, meta in yf_data.items():
            mask = df_sec["ticker"] == tkr
            if mask.any():
                df_sec.loc[mask, "sector"] = meta.get("sector", "")
                df_sec.loc[mask, "industry"] = meta.get("industry", "")

                # Flag energy
                sector = str(meta.get("sector", "")).lower()
                if sector == "energy":
                    df_sec.loc[mask, "is_energy"] = True

                # Flag media
                if sector == "communication services":
                    df_sec.loc[mask, "is_media"] = True

    # Apply manual ticker overrides before saving.
    # See docstring at top of file for how to add new overrides.
    overrides_path = os.path.join(REF_DIR, "ticker_overrides.csv")
    if os.path.exists(overrides_path):
        print(f"\nApplying manual ticker overrides from {overrides_path}...")
        df_overrides = pd.read_csv(overrides_path, dtype=str)
        applied = 0
        skipped = 0
        for _, row in df_overrides.iterrows():
            cusip = row["cusip"]
            correct = row.get("correct_ticker", "")
            if pd.isna(correct) or not str(correct).strip():
                continue  # Security-type-only override, no ticker change
            correct = str(correct).strip()
            mask = df_sec["cusip"] == cusip
            if mask.any():
                old = df_sec.loc[mask, "ticker"].iloc[0]
                df_sec.loc[mask, "ticker"] = correct
                applied += 1
            else:
                skipped += 1
        print(f"  Overrides applied: {applied} total")
        if "method" in df_overrides.columns:
            method_counts = df_overrides[df_overrides["cusip"].isin(
                df_sec["cusip"]
            )].groupby("method").size()
            for method, count in method_counts.items():
                print(f"    {method}: {count}")
        if skipped > 0:
            print(f"  Skipped: {skipped} (CUSIP not in securities)")
    else:
        print(f"\nNo ticker overrides file found at {overrides_path} — skipping")

    # Save to DuckDB
    con.execute("DROP TABLE IF EXISTS securities")
    con.execute("CREATE TABLE securities AS SELECT * FROM df_sec")

    # Update holdings ticker from securities
    print("\nUpdating holdings.ticker from securities...")
    try:
        con.execute("ALTER TABLE holdings ALTER COLUMN ticker TYPE VARCHAR")
    except Exception:
        pass
    con.execute("""
        UPDATE holdings h
        SET ticker = s.ticker
        FROM securities s
        WHERE h.cusip = s.cusip AND s.ticker IS NOT NULL
    """)

    # Coverage stats
    total = con.execute("SELECT COUNT(*) FROM securities").fetchone()[0]
    with_ticker = con.execute("SELECT COUNT(*) FROM securities WHERE ticker IS NOT NULL").fetchone()[0]
    holdings_total = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    holdings_with_ticker = con.execute("SELECT COUNT(*) FROM holdings WHERE ticker IS NOT NULL").fetchone()[0]

    print(f"\n  securities table: {total:,} rows")
    print(f"  CUSIPs with ticker: {with_ticker:,} ({with_ticker / total * 100:.1f}%)")
    print(f"  Holdings with ticker: {holdings_with_ticker:,} / {holdings_total:,} ({holdings_with_ticker / holdings_total * 100:.1f}%)")

    energy = con.execute("SELECT COUNT(*) FROM securities WHERE is_energy = true").fetchone()[0]
    media = con.execute("SELECT COUNT(*) FROM securities WHERE is_media = true").fetchone()[0]
    print(f"  Energy securities: {energy:,}")
    print(f"  Media securities: {media:,}")

    return total


def main():
    print("=" * 60)
    print("SCRIPT 6 — build_cusip.py")
    print("=" * 60)

    con = duckdb.connect(DB_PATH)

    # Step 1: Get unique CUSIPs
    print("\nGetting unique CUSIPs from holdings...")
    df_cusips = get_unique_cusips(con)

    # Step 2: OpenFIGI lookup
    figi_results = enrich_with_openfigi(df_cusips)

    # Step 3: Build and save securities table
    build_securities_table(con, df_cusips, figi_results)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
