#!/usr/bin/env python3
"""
fetch_nport.py — Download N-PORT filings, parse portfolio holdings, load into DuckDB.

Builds:
  - fund_universe table: active equity mutual funds with metadata
  - fund_holdings table: individual portfolio positions from N-PORT filings

Run: python3 scripts/fetch_nport.py                       # Full build (all quarters)
     python3 scripts/fetch_nport.py --quarter 2025Q4       # Single quarter
     python3 scripts/fetch_nport.py --fund "Fidelity Contrafund" --quarter 2025Q4
     python3 scripts/fetch_nport.py --test                 # Test on 5 funds only
"""

import os
import sys
import time
import argparse
import csv
import re
from datetime import datetime, timedelta
from collections import Counter

import requests
import duckdb
import pandas as pd
from lxml import etree

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import get_db_path, crash_handler
RAW_DIR = os.path.join(BASE_DIR, "data", "nport_raw")
LOG_DIR = os.path.join(BASE_DIR, "logs")

SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_DELAY = 0.2  # seconds between requests
NS = {"n": "http://www.sec.gov/edgar/nport"}

# Quarter mapping: our label → N-PORT report period target months
# Each quarter has 3 months. The third month is the quarter-end.
# Dec 2024→2025Q1, Mar 2025→2025Q2, Jun 2025→2025Q3, Sep 2025→2025Q4
QUARTER_TARGETS = {
    "2025Q1": (2024, 12),  # report period ending ~Dec 2024 (quarter-end)
    "2025Q2": (2025, 3),   # report period ending ~Mar 2025 (quarter-end)
    "2025Q3": (2025, 6),   # report period ending ~Jun 2025 (quarter-end)
    "2025Q4": (2025, 9),   # report period ending ~Sep 2025 (quarter-end)
}

# Monthly targets: all 3 months per quarter
# SEC releases months 1 & 2 after the quarter ends
MONTHLY_TARGETS = {
    "2025Q1": [(2024, 10), (2024, 11), (2024, 12)],
    "2025Q2": [(2025, 1), (2025, 2), (2025, 3)],
    "2025Q3": [(2025, 4), (2025, 5), (2025, 6)],
    "2025Q4": [(2025, 7), (2025, 8), (2025, 9)],
}

# EDGAR quarters to search for filings (filing dates, not report dates)
# Dec 2024 reports filed ~Feb 2025 → EDGAR Q1 2025
# Mar 2025 reports filed ~May 2025 → EDGAR Q2 2025
# Jun 2025 reports filed ~Aug 2025 → EDGAR Q3 2025
# Sep 2025 reports filed ~Nov 2025 → EDGAR Q4 2025
EDGAR_QUARTERS = [
    (2025, 1),
    (2025, 2),
    (2025, 3),
    (2025, 4),
]

# Index fund name patterns (excluded from active fund universe)
INDEX_PATTERNS = re.compile(
    r"\b(index|idx|s&p\s*500|russell\s*\d|nasdaq|dow\s*jones|"
    r"total\s*(stock|bond|market)|wilshire|msci|ftse|"
    r"barclays|aggregate|broad\s*market)\b",
    re.IGNORECASE,
)

# ETF/money market/bond-only/fund-of-funds exclusion patterns
EXCLUDE_PATTERNS = re.compile(
    r"\b(etf|exchange[\s-]*traded|money\s*market|"
    r"treasury|government\s*money|prime\s*money|"
    r"fund\s*of\s*funds|master\s*fund|feeder\s*fund)\b",
    re.IGNORECASE,
)

# Test funds (CIKs verified against EDGAR NPORT-P index)
TEST_FUNDS = {
    "Fidelity Contrafund": {"cik": 24238},
    "Vanguard Wellington Fund": {"cik": 105563},
    "T. Rowe Price Blue Chip Growth": {"cik": 902259},
    "Dodge & Cox Funds": {"cik": 29440},
    "Growth Fund of America": {"cik": 44201},
}


# ---------------------------------------------------------------------------
# Filing index
# ---------------------------------------------------------------------------
def build_filing_index():
    """Get all NPORT-P accession numbers from EDGAR via edgartools."""
    from edgar import set_identity, get_filings

    set_identity("13f-research serge.tismen@gmail.com")

    all_filings = []
    for year, quarter in EDGAR_QUARTERS:
        print(f"  Fetching EDGAR {year}Q{quarter} index...")
        f = get_filings(year=year, quarter=quarter, form="NPORT-P")
        df = f.data.to_pandas()
        df["edgar_quarter"] = f"{year}Q{quarter}"
        all_filings.append(df)
        print(f"    {len(df):,} filings")

    combined = pd.concat(all_filings, ignore_index=True)
    print(f"  Total: {len(combined):,} filings across {combined['cik'].nunique():,} CIKs")
    return combined


def map_report_period_to_quarter(rep_pd_end_str):
    """Map an N-PORT report period end date to our quarter label.

    Finds the closest target quarter using all monthly targets.
    Returns (quarter_label, report_date, report_month) or (None, None, None).
    """
    if not rep_pd_end_str:
        return None, None, None

    try:
        rep_date = datetime.strptime(rep_pd_end_str, "%Y-%m-%d")
    except ValueError:
        return None, None, None

    report_month = rep_date.strftime("%Y-%m")
    best_quarter = None
    best_diff = timedelta(days=999)

    # Check all monthly targets for best match
    for qlabel, months in MONTHLY_TARGETS.items():
        for year, month in months:
            if month == 12:
                target = datetime(year, 12, 31)
            elif month in (1, 3, 5, 7, 8, 10):
                target = datetime(year, month, 31)
            elif month in (4, 6, 9, 11):
                target = datetime(year, month, 30)
            elif month == 2:
                target = datetime(year, month, 28)

            diff = abs(rep_date - target)
            if diff < best_diff and diff <= timedelta(days=15):
                best_diff = diff
                best_quarter = qlabel

    # Fallback to old quarter-only matching (wider tolerance)
    if not best_quarter:
        for qlabel, (year, month) in QUARTER_TARGETS.items():
            if month == 12:
                target = datetime(year, 12, 31)
            elif month in (1, 3, 5, 7, 8, 10):
                target = datetime(year, month, 31)
            elif month in (4, 6, 9, 11):
                target = datetime(year, month, 30)
            elif month == 2:
                target = datetime(year, month, 28)

            diff = abs(rep_date - target)
            if diff < best_diff and diff <= timedelta(days=45):
                best_diff = diff
                best_quarter = qlabel

    return best_quarter, rep_pd_end_str, report_month


# ---------------------------------------------------------------------------
# XML download and parse
# ---------------------------------------------------------------------------
def download_xml(cik, accession_number, quarter_label):
    """Download N-PORT XML and save to disk. Returns XML bytes or None."""
    acc_fmt = accession_number.replace("-", "")

    # Check local cache
    save_dir = os.path.join(RAW_DIR, str(cik))
    os.makedirs(save_dir, exist_ok=True)

    # Try to determine quarter label for filename
    save_path = os.path.join(save_dir, f"{accession_number}.xml")
    if os.path.exists(save_path) and os.path.getsize(save_path) > 100:
        with open(save_path, "rb") as f:
            return f.read()

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_fmt}/primary_doc.xml"
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=60)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        time.sleep(SEC_DELAY)
        return r.content
    except Exception as e:
        # Some filings use different XML filenames — try index page
        try:
            idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_fmt}/{accession_number}-index.htm"
            r2 = requests.get(idx_url, headers=SEC_HEADERS, timeout=30)
            r2.raise_for_status()
            xml_links = re.findall(r'href="([^"]+\.xml)"', r2.text)
            # Filter for primary XML (not XSLT version)
            for link in xml_links:
                if "xsl" not in link.lower():
                    full_url = f"https://www.sec.gov{link}" if link.startswith("/") else link
                    r3 = requests.get(full_url, headers=SEC_HEADERS, timeout=60)
                    r3.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(r3.content)
                    time.sleep(SEC_DELAY)
                    return r3.content
        except Exception:
            pass
        return None


def parse_nport_xml(xml_bytes):
    """Parse N-PORT XML. Returns (metadata_dict, list_of_holdings) or (None, None)."""
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return None, None

    gen = root.find(".//n:genInfo", NS)
    fund_info = root.find(".//n:fundInfo", NS)
    if gen is None:
        return None, None

    def get_text(parent, tag):
        el = parent.find(f"n:{tag}", NS)
        return el.text.strip() if el is not None and el.text else None

    metadata = {
        "reg_name": get_text(gen, "regName"),
        "reg_cik": get_text(gen, "regCik"),
        "series_name": get_text(gen, "seriesName"),
        "series_id": get_text(gen, "seriesId"),
        "rep_pd_end": get_text(gen, "repPdEnd"),
        "rep_pd_date": get_text(gen, "repPdDate"),
        "is_final": get_text(gen, "isFinalFiling"),
    }

    if fund_info is not None:
        metadata["net_assets"] = get_text(fund_info, "netAssets")
        metadata["tot_assets"] = get_text(fund_info, "totAssets")

    # Parse holdings
    holdings = []
    for inv in root.findall(".//n:invstOrSec", NS):
        h = {}
        h["name"] = get_text(inv, "name")
        h["cusip"] = get_text(inv, "cusip")
        h["balance"] = get_text(inv, "balance")
        h["units"] = get_text(inv, "units")
        h["val_usd"] = get_text(inv, "valUSD")
        h["pct_val"] = get_text(inv, "pctVal")
        h["payoff_profile"] = get_text(inv, "payoffProfile")
        h["fair_val_level"] = get_text(inv, "fairValLevel")
        h["is_restricted"] = get_text(inv, "isRestrictedSec")

        # Asset category — can be direct element or conditional attribute
        cat_el = inv.find("n:assetCat", NS)
        if cat_el is not None and cat_el.text:
            h["asset_cat"] = cat_el.text.strip()
        else:
            cond = inv.find("n:assetConditional", NS)
            if cond is not None:
                h["asset_cat"] = cond.get("assetCat", "")
            else:
                h["asset_cat"] = ""

        # ISIN — stored as attribute
        isin_el = inv.find(".//n:isin", NS)
        if isin_el is not None:
            h["isin"] = isin_el.get("value", "")
        else:
            h["isin"] = ""

        # Ticker — try multiple paths
        ticker_el = inv.find(".//n:ticker", NS)
        if ticker_el is not None:
            h["ticker"] = ticker_el.get("value", "") or (ticker_el.text or "")
        else:
            h["ticker"] = ""

        # Currency
        h["cur_cd"] = get_text(inv, "curCd") or "USD"

        holdings.append(h)

    return metadata, holdings


def classify_fund(metadata, holdings):
    """Classify a fund. Returns (is_active_equity, fund_category, is_actively_managed)."""
    series_name = (metadata.get("series_name") or metadata.get("reg_name") or "").strip()

    # Exclusions
    if INDEX_PATTERNS.search(series_name):
        return False, "index", False
    if EXCLUDE_PATTERNS.search(series_name):
        return False, "excluded", False
    if metadata.get("is_final") == "Y":
        return False, "final_filing", False

    # Count asset categories
    cats = Counter(h.get("asset_cat", "") for h in holdings)
    total = len(holdings)
    if total == 0:
        return False, "empty", False

    equity_count = cats.get("EC", 0) + cats.get("EP", 0)
    debt_count = cats.get("DBT", 0) + cats.get("ABS-MBS", 0) + cats.get("ABS-O", 0)
    equity_pct = equity_count / total if total > 0 else 0

    # Compute value-weighted equity percentage
    total_val = sum(float(h.get("val_usd") or 0) for h in holdings)
    equity_val = sum(
        float(h.get("val_usd") or 0)
        for h in holdings
        if h.get("asset_cat") in ("EC", "EP")
    )
    equity_val_pct = equity_val / total_val if total_val > 0 else 0

    # Classify
    if equity_val_pct >= 0.60:
        if equity_val_pct >= 0.90:
            category = "equity"
        else:
            category = "balanced"
        return True, category, True
    elif equity_val_pct >= 0.30:
        return True, "multi_asset", True

    return False, "bond_or_other", False


# ---------------------------------------------------------------------------
# DuckDB operations
# ---------------------------------------------------------------------------
def create_tables(con):
    """Create fund_universe and fund_holdings tables if they do not exist."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS fund_universe (
            fund_cik VARCHAR,
            fund_name VARCHAR,
            series_id VARCHAR,
            family_name VARCHAR,
            total_net_assets DOUBLE,
            fund_category VARCHAR,
            is_actively_managed BOOLEAN,
            total_holdings_count INTEGER,
            equity_pct DOUBLE,
            top10_concentration DOUBLE,
            last_updated TIMESTAMP,
            PRIMARY KEY (series_id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS fund_holdings (
            fund_cik VARCHAR,
            fund_name VARCHAR,
            family_name VARCHAR,
            series_id VARCHAR,
            quarter VARCHAR,
            report_month VARCHAR,
            report_date DATE,
            cusip VARCHAR,
            isin VARCHAR,
            issuer_name VARCHAR,
            ticker VARCHAR,
            asset_category VARCHAR,
            shares_or_principal DOUBLE,
            market_value_usd DOUBLE,
            pct_of_nav DOUBLE,
            fair_value_level VARCHAR,
            is_restricted BOOLEAN,
            payoff_profile VARCHAR,
            loaded_at TIMESTAMP
        )
    """)

    # Create indexes (ignore if exist)
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_fh_cusip ON fund_holdings(cusip)",
        "CREATE INDEX IF NOT EXISTS idx_fh_ticker ON fund_holdings(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_fh_fund_cik ON fund_holdings(fund_cik)",
        "CREATE INDEX IF NOT EXISTS idx_fh_quarter ON fund_holdings(quarter)",
        "CREATE INDEX IF NOT EXISTS idx_fh_series_quarter ON fund_holdings(series_id, quarter)",
    ]:
        try:
            con.execute(idx_sql)
        except Exception:
            pass


def is_already_loaded(con, series_id, quarter, report_month=None):
    """Check if a fund-quarter(-month) combination is already in fund_holdings."""
    if report_month:
        # Check month-level granularity
        try:
            result = con.execute(
                "SELECT COUNT(*) FROM fund_holdings WHERE series_id = ? AND report_month = ?",
                [series_id, report_month],
            ).fetchone()
            return result[0] > 0
        except Exception:
            pass  # report_month column may not exist yet
    result = con.execute(
        "SELECT COUNT(*) FROM fund_holdings WHERE series_id = ? AND quarter = ?",
        [series_id, quarter],
    ).fetchone()
    return result[0] > 0


def load_holdings_to_db(con, metadata, holdings, quarter_label, report_date, report_month=None):
    """Insert parsed holdings into fund_holdings table."""
    series_id = metadata.get("series_id") or "UNKNOWN"
    fund_cik = (metadata.get("reg_cik") or "").lstrip("0").zfill(10)
    fund_name = metadata.get("series_name") or metadata.get("reg_name") or ""
    family_name = metadata.get("reg_name") or ""
    now = datetime.now().isoformat()

    rows = []
    for h in holdings:
        rows.append((
            fund_cik,
            fund_name,
            family_name,
            series_id,
            quarter_label,
            report_month,
            report_date,
            h.get("cusip"),
            h.get("isin") or None,
            h.get("name"),
            h.get("ticker") or None,
            h.get("asset_cat"),
            float(h["balance"]) if h.get("balance") else None,
            float(h["val_usd"]) if h.get("val_usd") else None,
            float(h["pct_val"]) if h.get("pct_val") else None,
            h.get("fair_val_level"),
            h.get("is_restricted") == "Y" if h.get("is_restricted") else False,
            h.get("payoff_profile"),
            now,
        ))

    if rows:
        con.executemany(
            """INSERT INTO fund_holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)


def update_fund_universe(con, metadata, holdings, fund_category):
    """Insert or update fund_universe entry."""
    series_id = metadata.get("series_id") or "UNKNOWN"
    fund_cik = (metadata.get("reg_cik") or "").lstrip("0").zfill(10)
    fund_name = metadata.get("series_name") or metadata.get("reg_name") or ""
    family_name = metadata.get("reg_name") or ""
    net_assets = float(metadata.get("net_assets") or 0)
    now = datetime.now().isoformat()

    # Compute stats
    total_count = len(holdings)
    total_val = sum(float(h.get("val_usd") or 0) for h in holdings)
    equity_val = sum(
        float(h.get("val_usd") or 0)
        for h in holdings
        if h.get("asset_cat") in ("EC", "EP")
    )
    equity_pct = equity_val / total_val if total_val > 0 else 0

    # Top 10 concentration
    vals = sorted(
        [float(h.get("val_usd") or 0) for h in holdings],
        reverse=True,
    )
    top10_val = sum(vals[:10])
    top10_pct = top10_val / total_val if total_val > 0 else 0

    # Upsert
    existing = con.execute(
        "SELECT series_id FROM fund_universe WHERE series_id = ?", [series_id]
    ).fetchone()

    if existing:
        con.execute(
            """UPDATE fund_universe
               SET fund_cik = ?, fund_name = ?, family_name = ?,
                   total_net_assets = ?, fund_category = ?, is_actively_managed = true,
                   total_holdings_count = ?, equity_pct = ?, top10_concentration = ?,
                   last_updated = ?
               WHERE series_id = ?""",
            [fund_cik, fund_name, family_name, net_assets, fund_category,
             total_count, equity_pct, top10_pct, now, series_id],
        )
    else:
        con.execute(
            """INSERT INTO fund_universe VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [fund_cik, fund_name, series_id, family_name, net_assets, fund_category,
             True, total_count, equity_pct, top10_pct, now],
        )


def enrich_tickers(con):
    """Join fund_holdings to securities table to fill missing tickers."""
    result = con.execute("""
        UPDATE fund_holdings
        SET ticker = s.ticker
        FROM securities s
        WHERE fund_holdings.cusip = s.cusip
          AND (fund_holdings.ticker IS NULL OR fund_holdings.ticker = '')
          AND s.ticker IS NOT NULL
          AND s.ticker != ''
    """)
    count = con.execute("""
        SELECT COUNT(*) FROM fund_holdings
        WHERE ticker IS NOT NULL AND ticker != ''
    """).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM fund_holdings").fetchone()[0]
    print(f"  Ticker enrichment: {count:,} / {total:,} holdings have tickers")


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------
def log_error(fund_cik, fund_name, quarter, error_msg):
    """Append error to logs/nport_errors.csv."""
    os.makedirs(LOG_DIR, exist_ok=True)
    error_path = os.path.join(LOG_DIR, "nport_errors.csv")
    file_exists = os.path.exists(error_path)
    with open(error_path, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["fund_cik", "fund_name", "quarter", "error", "timestamp"])
        writer.writerow([fund_cik, fund_name, quarter, error_msg, datetime.now().isoformat()])


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process_filing(con, cik, accession_number, company_name, target_quarters=None):
    """Download, parse, classify, and load a single N-PORT filing.

    Returns: list of (quarter_label, series_id, holdings_count) for successful loads,
             or empty list if skipped/failed.
    """
    xml_bytes = download_xml(cik, accession_number, None)
    if xml_bytes is None:
        log_error(cik, company_name, "N/A", "Download failed")
        return []

    metadata, holdings = parse_nport_xml(xml_bytes)
    if metadata is None:
        log_error(cik, company_name, "N/A", "XML parse failed")
        return []

    # Map report period to our quarter (use repPdDate — the actual quarter end,
    # not repPdEnd which is the fiscal year end)
    quarter_label, report_date, report_month = map_report_period_to_quarter(
        metadata.get("rep_pd_date") or metadata.get("rep_pd_end")
    )
    if quarter_label is None:
        return []  # Report period not in our target range

    # Filter to requested quarters
    if target_quarters and quarter_label not in target_quarters:
        return []

    series_id = metadata.get("series_id") or "UNKNOWN"

    # Skip if already loaded (check at month level for monthly data)
    if is_already_loaded(con, series_id, quarter_label, report_month):
        return []

    # Classify
    is_equity, category, is_active = classify_fund(metadata, holdings)
    if not is_equity:
        return []

    # Load holdings
    count = load_holdings_to_db(con, metadata, holdings, quarter_label, report_date, report_month)

    # Update universe
    update_fund_universe(con, metadata, holdings, category)

    return [(quarter_label, series_id, count)]


def run_full_build(con, filing_index, target_quarters=None, fund_filter_ciks=None):
    """Process all filings in the index."""
    if fund_filter_ciks:
        filing_index = filing_index[filing_index["cik"].isin(fund_filter_ciks)]

    total = len(filing_index)
    start_time = time.time()
    loaded_count = 0
    skipped_count = 0
    error_count = 0
    quarter_counts = Counter()

    print(f"\nProcessing {total:,} filings...")

    for i, (_, row) in enumerate(filing_index.iterrows()):
        cik = row["cik"]
        acc = row["accession_number"]
        company = row["company"]

        try:
            results = process_filing(con, cik, acc, company, target_quarters)
            if results:
                for qlabel, sid, cnt in results:
                    quarter_counts[qlabel] += 1
                    loaded_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            log_error(cik, company, "N/A", str(e))
            error_count += 1

        # Progress every 100 filings
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta_seconds = (total - i - 1) / rate if rate > 0 else 0
            eta_min = eta_seconds / 60

            # Count unique funds loaded
            fund_count = con.execute(
                "SELECT COUNT(DISTINCT series_id) FROM fund_holdings"
            ).fetchone()[0]

            qstatus = " | ".join(
                f"{q}: {quarter_counts.get(q, 0)}"
                for q in sorted(QUARTER_TARGETS.keys())
            )
            print(
                f"Progress: {i + 1:,} / {total:,} filings | "
                f"Funds loaded: {fund_count:,} | {qstatus} | "
                f"Elapsed: {elapsed / 60:.0f}min | ETA: {eta_min:.0f}min"
            )

    elapsed = time.time() - start_time
    print(f"\nDone. {loaded_count:,} fund-quarters loaded, "
          f"{skipped_count:,} skipped, {error_count:,} errors. "
          f"Time: {elapsed / 60:.1f}min")


def run_test(con, filing_index):
    """Test on 5 specific funds."""
    print("\n" + "=" * 60)
    print("TEST MODE — 5 funds")
    print("=" * 60)

    test_ciks = set()
    for name, info in TEST_FUNDS.items():
        cik = info["cik"]
        matches = filing_index[filing_index["cik"] == cik]
        if len(matches) > 0:
            test_ciks.add(cik)
            print(f"  {name}: CIK={cik}, {len(matches)} filings")
        else:
            print(f"  {name}: CIK={cik} NOT FOUND in index")

    # Filter index to test CIKs
    test_filings = filing_index[filing_index["cik"].isin(test_ciks)]
    print(f"\n  Test filings: {len(test_filings):,} across {len(test_ciks)} CIKs")

    # Process all filings for test CIKs
    run_full_build(con, test_filings)

    # Enrich tickers
    print("\nEnriching tickers...")
    enrich_tickers(con)

    # Print results
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    funds = con.execute("""
        SELECT fund_name, series_id, fund_cik, fund_category,
               ROUND(total_net_assets / 1e9, 1) as aum_bn,
               total_holdings_count, ROUND(equity_pct * 100, 1) as eq_pct,
               ROUND(top10_concentration * 100, 1) as top10_pct
        FROM fund_universe
        ORDER BY total_net_assets DESC
    """).fetchdf()
    print(f"\nFunds in universe: {len(funds)}")
    print(funds.to_string(index=False))

    # Holdings by quarter
    q_counts = con.execute("""
        SELECT quarter, COUNT(DISTINCT series_id) as funds, COUNT(*) as holdings
        FROM fund_holdings
        GROUP BY quarter ORDER BY quarter
    """).fetchdf()
    print(f"\nHoldings by quarter:")
    print(q_counts.to_string(index=False))

    # Top 5 holdings by value for each test fund (latest quarter)
    print("\nTop 5 holdings per fund (latest quarter):")
    for _, fund_row in funds.iterrows():
        sid = fund_row["series_id"]
        fname = fund_row["fund_name"]
        top5 = con.execute(f"""
            SELECT issuer_name, cusip, ticker,
                   ROUND(market_value_usd / 1e6, 1) as value_mm,
                   ROUND(pct_of_nav, 2) as pct_nav,
                   asset_category
            FROM fund_holdings
            WHERE series_id = '{sid}'
              AND quarter = (SELECT MAX(quarter) FROM fund_holdings WHERE series_id = '{sid}')
            ORDER BY market_value_usd DESC NULLS LAST
            LIMIT 5
        """).fetchdf()
        print(f"\n  {fname} ({sid}):")
        if len(top5) > 0:
            print(top5.to_string(index=False))
        else:
            print("    No holdings found")

    # Check AR holdings
    print("\nAR (Antero Resources) holdings in fund_holdings:")
    ar = con.execute("""
        SELECT fh.fund_name, fh.quarter, fh.shares_or_principal as shares,
               ROUND(fh.market_value_usd / 1e6, 1) as value_mm,
               ROUND(fh.pct_of_nav, 3) as pct_nav
        FROM fund_holdings fh
        WHERE fh.cusip = '00130H105'
           OR fh.ticker = 'AR'
        ORDER BY fh.market_value_usd DESC NULLS LAST
    """).fetchdf()
    if len(ar) > 0:
        print(ar.to_string(index=False))
    else:
        print("  No AR holdings found in test funds")

    print("\n" + "=" * 60)
    fund_count = con.execute("SELECT COUNT(DISTINCT series_id) FROM fund_holdings").fetchone()[0]
    quarter_count = con.execute("SELECT COUNT(DISTINCT quarter) FROM fund_holdings").fetchone()[0]
    print(f"Test complete. {fund_count} funds loaded across {quarter_count} quarters.")
    print("Ready to start full build of ~4,000+ funds.")
    print("Estimated time: 4-6 hours.")
    print("Run in background with:")
    print("  nohup python3 scripts/fetch_nport.py > logs/nport_build.log 2>&1 &")
    print("Wait for confirmation before proceeding.")
    print("=" * 60)


def find_fund_by_name(filing_index, name_query):
    """Search filing index for a fund by name or CIK."""
    # Try as CIK
    try:
        cik = int(name_query)
        matches = filing_index[filing_index["cik"] == cik]
        if len(matches) > 0:
            return set(matches["cik"].unique())
    except ValueError:
        pass

    # Search by name
    matches = filing_index[
        filing_index["company"].str.lower().str.contains(name_query.lower(), regex=False)
    ]
    if len(matches) > 0:
        return set(matches["cik"].unique())

    return set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Fetch N-PORT filings")
    parser.add_argument("--quarter", help="Single quarter to fetch (e.g., 2025Q4)")
    parser.add_argument("--fund", help="Single fund by name or CIK")
    parser.add_argument("--test", action="store_true", help="Test mode: 5 funds only")
    args = parser.parse_args()

    print("=" * 60)
    print("FETCH N-PORT — Mutual Fund Holdings")
    print("=" * 60)

    # Ensure directories exist
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    # Build filing index
    print("\nBuilding filing index...")
    filing_index = build_filing_index()

    # Connect to DuckDB
    con = duckdb.connect(get_db_path())
    create_tables(con)

    target_quarters = None
    if args.quarter:
        if args.quarter not in QUARTER_TARGETS:
            print(f"ERROR: Invalid quarter '{args.quarter}'. Valid: {list(QUARTER_TARGETS.keys())}")
            sys.exit(1)
        target_quarters = {args.quarter}
        print(f"\nFiltering to quarter: {args.quarter}")

    if args.test:
        run_test(con, filing_index)
    elif args.fund:
        fund_ciks = find_fund_by_name(filing_index, args.fund)
        if not fund_ciks:
            print(f"ERROR: No fund found matching '{args.fund}'")
            sys.exit(1)
        print(f"\nFound CIKs for '{args.fund}': {fund_ciks}")
        run_full_build(con, filing_index, target_quarters, fund_ciks)
        enrich_tickers(con)
    else:
        run_full_build(con, filing_index, target_quarters)
        print("\nEnriching tickers...")
        enrich_tickers(con)

    # Print summary
    print("\n--- Summary ---")
    try:
        fu_count = con.execute("SELECT COUNT(*) FROM fund_universe").fetchone()[0]
        fh_count = con.execute("SELECT COUNT(*) FROM fund_holdings").fetchone()[0]
        print(f"  fund_universe: {fu_count:,} funds")
        print(f"  fund_holdings: {fh_count:,} holdings")

        q_summary = con.execute("""
            SELECT quarter, COUNT(DISTINCT series_id) as funds, COUNT(*) as holdings
            FROM fund_holdings GROUP BY quarter ORDER BY quarter
        """).fetchdf()
        print(f"\n  By quarter:")
        print(q_summary.to_string(index=False))
    except Exception:
        pass

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    crash_handler("fetch_nport")(main)
