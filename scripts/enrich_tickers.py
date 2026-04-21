#!/usr/bin/env python3
"""
enrich_tickers.py — Improve CUSIP-to-ticker coverage using:
  1. SEC 13(f) securities list (CUSIP + issuer name for name matching)
  2. SEC company_tickers_exchange.json (ticker + company name + exchange)
  3. Cross-reference by normalized company name

Then re-run yfinance for newly resolved tickers only.

Run: python3 scripts/enrich_tickers.py
"""

import os
import time
import re
import requests
import pandas as pd
import duckdb
from rapidfuzz import fuzz, process

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import get_db_path, set_staging_mode
from config import SEC_HEADERS
REF_DIR = os.path.join(BASE_DIR, "data", "reference")

SEC_DELAY = 0.5

SEC_13F_LIST_URL = "https://www.sec.gov/files/investment/13flist2025q4.txt"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


def get_baseline(con):
    """Get current coverage stats."""
    total_cusips = con.execute("SELECT COUNT(*) FROM securities").fetchone()[0]
    with_ticker = con.execute("SELECT COUNT(*) FROM securities WHERE ticker IS NOT NULL").fetchone()[0]
    total_holdings = con.execute("SELECT COUNT(*) FROM holdings WHERE quarter = '2025Q4'").fetchone()[0]
    holdings_ticker = con.execute("SELECT COUNT(*) FROM holdings WHERE quarter = '2025Q4' AND ticker IS NOT NULL").fetchone()[0]
    holdings_live = con.execute("SELECT COUNT(*) FROM holdings WHERE quarter = '2025Q4' AND market_value_live IS NOT NULL").fetchone()[0]
    mkt_tickers = con.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
    return {
        "total_cusips": total_cusips,
        "cusips_with_ticker": with_ticker,
        "total_holdings_q4": total_holdings,
        "holdings_with_ticker": holdings_ticker,
        "holdings_with_live": holdings_live,
        "market_data_tickers": mkt_tickers,
    }


def parse_13f_list():
    """Download and parse the SEC 13(f) securities list TXT file."""
    print("\n--- Source 1: SEC 13(f) Securities List ---")
    print(f"  Downloading {SEC_13F_LIST_URL}...")
    r = requests.get(SEC_13F_LIST_URL, headers=SEC_HEADERS, timeout=60)
    r.raise_for_status()
    time.sleep(SEC_DELAY)

    lines = r.text.strip().split("\n")
    print(f"  Lines: {len(lines):,}")

    records = []
    for line in lines:
        if len(line) < 10:
            continue
        # Fixed-width: CUSIP is first 9 chars, optional * at pos 9
        cusip = line[:9].strip()
        if not cusip or len(cusip) < 6:
            continue
        # Remove leading/trailing * from CUSIP
        has_star = line[9] == "*" if len(line) > 9 else False
        # Issuer name starts after CUSIP+star
        rest = line[10:] if has_star else line[9:]
        # The issuer name is roughly first 33 chars of rest
        issuer = rest[:33].strip()
        # Class/type follows
        sec_class = rest[33:55].strip() if len(rest) > 33 else ""
        # Status flag at end
        status = line[-1].strip() if line else ""

        records.append({
            "cusip": cusip,
            "issuer_name_13f": issuer,
            "sec_class": sec_class,
            "status": status,
        })

    df = pd.DataFrame(records)
    print(f"  Parsed: {len(df):,} securities")
    print(f"  Unique CUSIPs: {df['cusip'].nunique():,}")

    # Save for reference
    df.to_csv(os.path.join(REF_DIR, "sec_13f_list.csv"), index=False)
    return df


def fetch_company_tickers():
    """Fetch SEC company_tickers_exchange.json."""
    print("\n--- Source 2: SEC Company Tickers Exchange ---")
    print(f"  Downloading {SEC_TICKERS_URL}...")
    r = requests.get(SEC_TICKERS_URL, headers=SEC_HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(SEC_DELAY)

    data = r.json()
    fields = data["fields"]  # ['cik', 'name', 'ticker', 'exchange']
    rows = data["data"]
    print(f"  Records: {len(rows):,}")

    df = pd.DataFrame(rows, columns=fields)
    # Clean ticker
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    # Remove duplicates — keep first (sorted by CIK, largest companies first)
    df = df.drop_duplicates(subset="ticker", keep="first")
    print(f"  Unique tickers: {len(df):,}")

    # Save for reference
    df.to_csv(os.path.join(REF_DIR, "sec_company_tickers.csv"), index=False)
    return df


def normalize_name(name):
    """Normalize company name for matching."""
    if not name or pd.isna(name):
        return ""
    s = str(name).upper()
    # Remove common suffixes
    for suffix in [" INC", " CORP", " CO", " LTD", " LLC", " LP", " PLC",
                   " SA", " NV", " SE", " AG", " GROUP", " HOLDINGS",
                   " INTERNATIONAL", " INTL", " TECHNOLOGIES", " TECHNOLOGY",
                   ",", ".", "/DE/", "/MD/", "/NY/", "/NV/"]:
        s = s.replace(suffix, "")
    # Remove special chars
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def enrich_securities(con, df_13f, df_tickers):
    """Cross-reference to add tickers to securities table."""
    print("\n--- Enriching securities table ---")

    # Get securities without tickers
    no_ticker = con.execute("""
        SELECT cusip, issuer_name, total_value
        FROM securities
        WHERE ticker IS NULL
        ORDER BY total_value DESC
    """).fetchdf()
    print(f"  Securities without ticker: {len(no_ticker):,}")

    # ======================================================================
    # Method 1: Direct CUSIP match from 13F list → company_tickers by name
    # ======================================================================
    print("\n  Method 1: 13F list CUSIP → name → company_tickers name match")

    # Build name→ticker lookup from company_tickers
    ticker_lookup = {}
    for _, row in df_tickers.iterrows():
        norm = normalize_name(row["name"])
        if norm and row["ticker"]:
            ticker_lookup[norm] = row["ticker"]

    # Build CUSIP→normalized_name from 13F list
    cusip_to_name_13f = {}
    for _, row in df_13f.iterrows():
        norm = normalize_name(row["issuer_name_13f"])
        if norm:
            cusip_to_name_13f[row["cusip"]] = norm

    # Match: CUSIP in securities → name from 13F list → ticker from company_tickers
    method1_matches = {}
    for _, row in no_ticker.iterrows():
        cusip = row["cusip"]
        if cusip in cusip_to_name_13f:
            name_13f = cusip_to_name_13f[cusip]
            if name_13f in ticker_lookup:
                method1_matches[cusip] = ticker_lookup[name_13f]

    print(f"  Method 1 exact matches: {len(method1_matches):,}")

    # ======================================================================
    # Method 2: Fuzzy name match — securities issuer_name vs company_tickers
    # ======================================================================
    print("\n  Method 2: Fuzzy name match (securities issuer_name → company_tickers)")

    # Only do fuzzy for CUSIPs not yet matched, top 10000 by value
    remaining = no_ticker[~no_ticker["cusip"].isin(method1_matches)]
    remaining = remaining.head(10000)

    # Build lookup arrays for fuzzy matching
    ticker_names = list(ticker_lookup.keys())
    ticker_by_name = ticker_lookup

    method2_matches = {}
    for i, (_, row) in enumerate(remaining.iterrows()):
        norm = normalize_name(row["issuer_name"])
        if not norm or len(norm) < 3:
            continue

        result = process.extractOne(
            norm, ticker_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=90
        )
        if result:
            matched_name, score, _ = result
            method2_matches[row["cusip"]] = {
                "ticker": ticker_by_name[matched_name],
                "score": score,
                "matched_name": matched_name,
                "original_name": row["issuer_name"],
            }

        if (i + 1) % 2000 == 0:
            print(f"    Processed {i + 1:,}/{len(remaining):,} ({len(method2_matches):,} matches)")

    print(f"  Method 2 fuzzy matches: {len(method2_matches):,}")

    # ======================================================================
    # Method 3: Direct name match using holdings issuer_name
    # ======================================================================
    print("\n  Method 3: Direct name match (holdings issuer_name → company_tickers)")

    # For CUSIPs still unmatched, try matching the issuer_name from 13F filings
    still_unmatched = remaining[
        ~remaining["cusip"].isin(method1_matches) &
        ~remaining["cusip"].isin(method2_matches)
    ]

    method3_matches = {}
    for _, row in still_unmatched.iterrows():
        norm = normalize_name(row["issuer_name"])
        if norm in ticker_lookup:
            method3_matches[row["cusip"]] = ticker_lookup[norm]

    print(f"  Method 3 exact matches: {len(method3_matches):,}")

    # ======================================================================
    # Combine all matches
    # ======================================================================
    all_matches = {}
    for cusip, ticker in method1_matches.items():
        all_matches[cusip] = ticker
    for cusip, info in method2_matches.items():
        if cusip not in all_matches:
            all_matches[cusip] = info["ticker"]
    for cusip, ticker in method3_matches.items():
        if cusip not in all_matches:
            all_matches[cusip] = ticker

    print(f"\n  Total new ticker matches: {len(all_matches):,}")

    # Dedupe: skip tickers that are already in the securities table
    existing = set(con.execute(
        "SELECT DISTINCT ticker FROM securities WHERE ticker IS NOT NULL"
    ).fetchdf()["ticker"].tolist())

    new_tickers = set(all_matches.values()) - existing
    print(f"  New unique tickers (not already known): {len(new_tickers):,}")

    return all_matches, new_tickers


def update_securities(con, all_matches):
    """Update the securities table with new tickers."""
    print("\nUpdating securities table...")

    updated = 0
    for cusip, ticker in all_matches.items():
        con.execute(
            "UPDATE securities SET ticker = ? WHERE cusip = ? AND ticker IS NULL",
            [ticker, cusip]
        )
        updated += 1

    print(f"  Updated {updated:,} rows in securities")

    # Propagate to holdings
    print("  Propagating to holdings table...")
    con.execute("""
        UPDATE holdings h
        SET ticker = s.ticker
        FROM securities s
        WHERE h.cusip = s.cusip AND s.ticker IS NOT NULL AND h.ticker IS NULL
    """)

    new_holdings = con.execute(
        "SELECT COUNT(*) FROM holdings WHERE ticker IS NOT NULL"
    ).fetchone()[0]
    print(f"  Holdings with ticker now: {new_holdings:,}")

    return updated


def fetch_market_for_new_tickers(con, new_tickers):
    """Fetch market data for newly resolved tickers via YahooClient + SEC XBRL.

    Canonical sources:
      - price, sector, industry, 52w, volume: YahooClient (/v7 batch + /v10 per-symbol)
      - shares_outstanding: SEC XBRL (authoritative, 10-K/10-Q cover)
      - market_cap: computed as shares_outstanding × price_live
    """
    from datetime import datetime
    from yahoo_client import YahooClient
    from sec_shares_client import SECSharesClient

    print(f"\nFetching market data for {len(new_tickers):,} new tickers...")

    existing = set(con.execute(
        "SELECT ticker FROM market_data"
    ).fetchdf()["ticker"].tolist())
    to_fetch = sorted(new_tickers - existing)
    print(f"  After removing already-fetched: {len(to_fetch):,} tickers to fetch")

    if not to_fetch:
        print("  Nothing to fetch.")
        return 0

    yc = YahooClient()
    sc = SECSharesClient()
    today = datetime.now().strftime("%Y-%m-%d")

    # Pass 1: batch quotes for prices (fast, 150/call)
    quotes = {}
    for i in range(0, len(to_fetch), 150):
        chunk = to_fetch[i:i + 150]
        try:
            quotes.update(yc.fetch_quote_batch(chunk))
        except Exception as e:
            print(f"    batch {i} err: {e}")

    # Pass 2: per-symbol metadata for sector/industry/float
    records = []
    failed = []
    for idx, tkr_str in enumerate(to_fetch, 1):
        try:
            m = yc.fetch_metadata(tkr_str)
            q = quotes.get(tkr_str, {})
            price = (m or {}).get("price") or q.get("price")
            if not price:
                failed.append(tkr_str)
                continue
            sec = sc.fetch(tkr_str) or {}
            shares_out = sec.get("shares_outstanding")
            market_cap = (shares_out * price) if (shares_out and price) else None
            records.append({
                "ticker":              tkr_str,
                "price_live":          price,
                "market_cap":          market_cap,
                "float_shares":        (m or {}).get("float_shares"),
                "shares_outstanding":  shares_out,
                "fifty_two_week_high": (m or {}).get("fifty_two_week_high") or q.get("fifty_two_week_high"),
                "fifty_two_week_low":  (m or {}).get("fifty_two_week_low")  or q.get("fifty_two_week_low"),
                "avg_volume_30d":      (m or {}).get("avg_volume_30d") or q.get("avg_volume_30d"),
                "sector":              (m or {}).get("sector"),
                "industry":            (m or {}).get("industry"),
                "exchange":            (m or {}).get("exchange") or q.get("exchange"),
                "fetch_date":          today,
            })
        except Exception:
            failed.append(tkr_str)

        if idx % 100 == 0:
            print(f"    [{idx:,}/{len(to_fetch):,}] ok={len(records):,} failed={len(failed):,}")

    print(f"\n  New market data fetched: {len(records):,}")
    print(f"  Failed: {len(failed):,}")

    if records:
        df_new = pd.DataFrame(records)
        con.register("df_new", df_new)
        cols = ",".join(records[0].keys())
        con.execute(f"INSERT INTO market_data ({cols}) SELECT {cols} FROM df_new")
        con.unregister("df_new")
        print(f"  Appended {len(records):,} rows to market_data")

    return len(records)


def update_holdings_live(con):
    """Update holdings market_value_live and pct_of_float for newly enriched rows."""
    print("\nUpdating holdings live values...")

    con.execute("""
        UPDATE holdings h
        SET market_value_live = h.shares * m.price_live
        FROM market_data m
        WHERE h.ticker = m.ticker
          AND m.price_live IS NOT NULL
          AND h.market_value_live IS NULL
    """)

    con.execute("""
        UPDATE holdings h
        SET pct_of_float = ROUND(h.shares * 100.0 / m.float_shares, 4)
        FROM market_data m
        WHERE h.ticker = m.ticker
          AND m.float_shares IS NOT NULL
          AND m.float_shares > 0
          AND h.pct_of_float IS NULL
    """)

    live = con.execute("SELECT COUNT(*) FROM holdings WHERE market_value_live IS NOT NULL").fetchone()[0]
    flt = con.execute("SELECT COUNT(*) FROM holdings WHERE pct_of_float IS NOT NULL").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    print(f"  Holdings with live value: {live:,} / {total:,} ({live/total*100:.1f}%)")
    print(f"  Holdings with float %: {flt:,} / {total:,} ({flt/total*100:.1f}%)")


def main():
    print("=" * 60)
    print("ENRICH TICKERS — Improve CUSIP-to-ticker coverage")
    print("=" * 60)

    con = duckdb.connect(get_db_path())

    # Baseline
    print("\n--- BEFORE ---")
    before = get_baseline(con)
    for k, v in before.items():
        print(f"  {k}: {v:,}")

    # Source 1: SEC 13F list
    df_13f = parse_13f_list()

    # Source 2: Company tickers
    df_tickers = fetch_company_tickers()

    # Cross-reference
    all_matches, new_tickers = enrich_securities(con, df_13f, df_tickers)

    # Update database
    update_securities(con, all_matches)

    # Fetch market data for new tickers
    fetch_market_for_new_tickers(con, new_tickers)

    # Update holdings live values
    update_holdings_live(con)

    # Final stats
    print("\n--- AFTER ---")
    after = get_baseline(con)
    for k, v in after.items():
        print(f"  {k}: {v:,}")

    # Delta report
    print("\n--- IMPROVEMENT ---")
    print(f"  CUSIPs with ticker:   {before['cusips_with_ticker']:,} → {after['cusips_with_ticker']:,} "
          f"(+{after['cusips_with_ticker'] - before['cusips_with_ticker']:,})")
    print(f"  Holdings with ticker: {before['holdings_with_ticker']:,} → {after['holdings_with_ticker']:,} "
          f"(+{after['holdings_with_ticker'] - before['holdings_with_ticker']:,})")
    print(f"  Holdings with live $: {before['holdings_with_live']:,} → {after['holdings_with_live']:,} "
          f"(+{after['holdings_with_live'] - before['holdings_with_live']:,})")
    print(f"  Market data tickers:  {before['market_data_tickers']:,} → {after['market_data_tickers']:,} "
          f"(+{after['market_data_tickers'] - before['market_data_tickers']:,})")

    pct_before = before['holdings_with_ticker'] / before['total_holdings_q4'] * 100
    pct_after = after['holdings_with_ticker'] / after['total_holdings_q4'] * 100
    print(f"\n  Q4 ticker coverage: {pct_before:.1f}% → {pct_after:.1f}%")

    pct_live_before = before['holdings_with_live'] / before['total_holdings_q4'] * 100
    pct_live_after = after['holdings_with_live'] / after['total_holdings_q4'] * 100
    print(f"  Q4 live value coverage: {pct_live_before:.1f}% → {pct_live_after:.1f}%")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Enrich CUSIP-to-ticker coverage")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("enrich_tickers")(main)
