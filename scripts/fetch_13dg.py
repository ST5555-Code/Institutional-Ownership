#!/usr/bin/env python3
"""
fetch_13dg.py — Download and parse SC 13D/G beneficial ownership filings from EDGAR.

Builds:
  - beneficial_ownership table: all parsed 13D/G filings
  - beneficial_ownership_current table: latest filing per filer+subject
  - Updates managers.has_13dg flag

Run: python3 scripts/fetch_13dg.py                          # Full build (all target tickers)
     python3 scripts/fetch_13dg.py --tickers AR,DVN,CVX     # Specific tickers
     python3 scripts/fetch_13dg.py --test                   # Test on 5 tickers
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime

import duckdb
import requests
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")
LOG_DIR = os.path.join(BASE_DIR, "logs")

SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_DELAY = 0.5  # seconds between requests
MIN_DATE = "2022-01-01"

TARGET_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}

TEST_TICKERS = ["AR", "AM", "DVN", "WBD", "CVX"]

os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# SEC API helpers
# ---------------------------------------------------------------------------

def sec_get(url, max_retries=3):
    """GET with rate limiting and retry."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                return None
            print(f"  HTTP {resp.status_code} for {url}")
            time.sleep(2)
        except requests.RequestException as e:
            print(f"  Request error: {e}")
            time.sleep(5)
    return None


def get_ticker_to_company_cik():
    """Download SEC ticker→CIK mapping."""
    print("Downloading SEC company tickers mapping...")
    resp = sec_get("https://www.sec.gov/files/company_tickers.json")
    if not resp:
        print("ERROR: Could not download company tickers")
        sys.exit(1)
    data = resp.json()
    mapping = {}
    for entry in data.values():
        mapping[entry["ticker"]] = str(entry["cik_str"]).zfill(10)
    print(f"  {len(mapping)} tickers mapped")
    return mapping


def get_company_filings_13dg(company_cik):
    """Get list of 13D/G filings for a company CIK from EDGAR submissions JSON."""
    url = f"https://data.sec.gov/submissions/CIK{company_cik}.json"
    resp = sec_get(url)
    if not resp:
        return []

    data = resp.json()
    company_name = data.get("name", "")
    recent = data["filings"]["recent"]
    forms = recent["form"]
    dates = recent["filingDate"]
    accessions = recent["accessionNumber"]
    primary_docs = recent["primaryDocument"]

    results = []
    for i, form in enumerate(forms):
        if form in TARGET_FORMS and dates[i] >= MIN_DATE:
            filer_cik = accessions[i].split("-")[0]
            results.append({
                "accession_number": accessions[i],
                "filing_type": form,
                "filing_date": dates[i],
                "filer_cik": filer_cik,
                "subject_cik": company_cik,
                "subject_name": company_name,
                "primary_doc": primary_docs[i],
            })

    # Check older filings if they exist
    for old_file in data["filings"].get("files", []):
        old_url = f"https://data.sec.gov/submissions/{old_file['name']}"
        old_resp = sec_get(old_url)
        if not old_resp:
            continue
        time.sleep(SEC_DELAY)
        old_data = old_resp.json()
        for i, form in enumerate(old_data["form"]):
            if form in TARGET_FORMS and old_data["filingDate"][i] >= MIN_DATE:
                filer_cik = old_data["accessionNumber"][i].split("-")[0]
                results.append({
                    "accession_number": old_data["accessionNumber"][i],
                    "filing_type": form,
                    "filing_date": old_data["filingDate"][i],
                    "filer_cik": filer_cik,
                    "subject_cik": company_cik,
                    "subject_name": old_data.get("name", company_name),
                    "primary_doc": old_data["primaryDocument"][i],
                })

    return results


_filer_name_cache = {}


def get_filer_name(filer_cik):
    """Look up filer name from CIK via EDGAR JSON. Cached."""
    if filer_cik in _filer_name_cache:
        return _filer_name_cache[filer_cik]
    url = f"https://data.sec.gov/submissions/CIK{filer_cik}.json"
    resp = sec_get(url)
    name = "UNKNOWN"
    if resp:
        try:
            name = resp.json().get("name", "UNKNOWN")
        except Exception:
            pass
    _filer_name_cache[filer_cik] = name
    time.sleep(SEC_DELAY)
    return name


# ---------------------------------------------------------------------------
# Filing text parser
# ---------------------------------------------------------------------------

def parse_filing_text(filing_info):
    """Download and parse a 13D/G filing's primary document for ownership data."""
    acc = filing_info["accession_number"]
    acc_path = acc.replace("-", "")
    subject_cik_raw = filing_info["subject_cik"].lstrip("0") or "0"
    filer_cik_raw = filing_info["filer_cik"].lstrip("0") or "0"
    primary_doc = filing_info["primary_doc"]

    # 13D/G filings are stored under subject company CIK on EDGAR
    url = f"https://www.sec.gov/Archives/edgar/data/{subject_cik_raw}/{acc_path}/{primary_doc}"
    resp = sec_get(url)
    if not resp:
        # Fallback: try filer CIK path
        url = f"https://www.sec.gov/Archives/edgar/data/{filer_cik_raw}/{acc_path}/{primary_doc}"
        resp = sec_get(url)
        if not resp:
            return None

    raw_text = resp.text

    # Strip HTML tags and entities for parsing
    text = re.sub(r"<[^>]+>", " ", raw_text)
    text = re.sub(r"&nbsp;|&#160;|&#xa0;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&amp;|&#38;", "&", text)
    text = re.sub(r"&lt;|&#60;", "<", text)
    text = re.sub(r"&gt;|&#62;", ">", text)
    text = re.sub(r"&ldquo;|&rdquo;|&#8220;|&#8221;", '"', text)
    text = re.sub(r"&lsquo;|&rsquo;|&#8216;|&#8217;", "'", text)
    text = re.sub(r"&#\d+;", " ", text)  # remaining numeric entities
    text = re.sub(r"&\w+;", " ", text)   # remaining named entities
    text = re.sub(r"\s+", " ", text)

    result = {
        "cusip": None,
        "pct_owned": None,
        "shares_owned": None,
        "aggregate_value": None,
        "purpose_text": None,
        "group_members": None,
        "report_date": None,
        "reporting_person": None,
    }

    # --- Reporting Person (Item 1 on cover page) ---
    rp_patterns = [
        # "Item 1: Reporting Person - Name"
        r"Item\s*1[:\s]+Reporting\s+Person\s*[-–—]\s*([\w\s.,&'/-]+?)(?=\s*(?:Item\s*2|CHECK|\n))",
        # "NAMES OF REPORTING PERSONS   Name"
        r"NAMES?\s+OF\s+REPORTING\s+PERSONS?\s+((?:[A-Z][A-Za-z.'&,\s-]+){1,5}?)(?=\s*(?:CHECK|2\.|Item\s*2))",
        # "Name of Person Filing: Name"
        r"Name\s+of\s+Person\s+Filing[:\s]+([\w\s.,&'/-]+?)(?=\s*(?:Item|Address|\n))",
    ]
    for pat in rp_patterns:
        rp_match = re.search(pat, text, re.IGNORECASE)
        if rp_match:
            name = rp_match.group(1).strip()
            # Filter out junk: must start with a letter, no "I.R.S.", no numbers at start
            if (3 < len(name) < 100
                    and name[0].isalpha()
                    and "I.R.S." not in name
                    and "CUSIP" not in name.upper()):
                result["reporting_person"] = name
                break

    # --- CUSIP ---
    cusip_match = re.search(
        r"CUSIP\s*(?:No\.?|Number|#)?\s*[:\s]*([A-Z0-9]{6,9})", text, re.IGNORECASE
    )
    if cusip_match:
        result["cusip"] = cusip_match.group(1).strip()

    # --- Percentage of class (Item 11 on cover page or Item 4(b)) ---
    pct_patterns = [
        # Cover page: PERCENT OF CLASS ... ROW 9 ... X%
        r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*[\(]?9[\)]?\s+(\d+[\.,]?\d*)\s*%",
        # Item 11 on cover page (various formats)
        r"Item\s*11[\s.:]+(\d+[\.,]?\d*)\s*%",
        # Item 4(b) in body
        r"Percent\s+of\s+Class[:\s]+(\d+[\.,]?\d*)\s*%",
        # PERCENT OF CLASS without ROW 9 reference
        r"PERCENT\s+OF\s+CLASS[\s.:]*(\d+[\.,]?\d*)\s*%",
        # Generic percentage pattern near "percent"
        r"(\d{1,3}\.\d{1,3})\s*%\s*(?:of\s+(?:class|outstanding))",
    ]
    for pat in pct_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result["pct_owned"] = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
            break

    # --- Shares (Item 9 on cover page or Item 4(a)) ---
    shares_patterns = [
        # Item 9 on cover page
        r"(?:Item\s*9|AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED)[\s.:]*(?:BY\s+EACH\s+REPORTING\s+PERSON)?\s*([\d,]+)",
        # Item 4(a)
        r"Amount\s+Beneficially\s+Owned[:\s]*([\d,]+)",
        # Cover page Item 9 simple format
        r"Item\s+9[:\s]+([\d,]+)",
    ]
    for pat in shares_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result["shares_owned"] = int(m.group(1).replace(",", ""))
            except ValueError:
                pass
            break

    # --- Report date (Date of Event) ---
    date_patterns = [
        r"Date\s+of\s+Event\s+Which\s+Requires\s+Filing[^)]*\)\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        r"Date\s+of\s+Event[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
        r"Date\s+of\s+Event[:\s]*(\d{4}-\d{2}-\d{2})",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            date_str = m.group(1).strip()
            try:
                for fmt in ["%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"]:
                    try:
                        result["report_date"] = datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
            break

    # --- Purpose of Transaction (Item 4 for 13D) ---
    if "13D" in filing_info["filing_type"].upper():
        purpose_match = re.search(
            r"Item\s*4\.?\s*(?:Purpose\s+of\s+Transaction|Purpose)[.\s]*(.*?)(?=Item\s*5|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if purpose_match:
            purpose = purpose_match.group(1).strip()
            # Clean up and truncate
            purpose = re.sub(r"\s+", " ", purpose)
            result["purpose_text"] = purpose[:500] if purpose else None

    # --- Group members (from cover page or Item 2) ---
    # Look for multiple reporting persons
    reporting_persons = re.findall(
        r"(?:Item\s*1[:\s]*|NAMES?\s+OF\s+REPORTING\s+PERSONS?[:\s]*)\s*([A-Z][A-Za-z\s.,&'-]+?)(?=\s*(?:Item|CHECK|SEC\s+USE|\d\.))",
        text,
        re.IGNORECASE,
    )
    if len(reporting_persons) > 1:
        # Clean up names
        members = []
        for p in reporting_persons:
            name = p.strip()
            if len(name) > 3 and len(name) < 100:
                members.append(name)
        if len(members) > 1:
            result["group_members"] = "; ".join(members[:5])

    return result


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def create_tables(con):
    """Create beneficial ownership tables."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS beneficial_ownership (
            accession_number VARCHAR PRIMARY KEY,
            filer_cik VARCHAR,
            filer_name VARCHAR,
            subject_cusip VARCHAR,
            subject_ticker VARCHAR,
            subject_name VARCHAR,
            filing_type VARCHAR,
            filing_date DATE,
            report_date DATE,
            pct_owned DOUBLE,
            shares_owned BIGINT,
            aggregate_value DOUBLE,
            intent VARCHAR,
            is_amendment BOOLEAN,
            prior_accession VARCHAR,
            purpose_text VARCHAR,
            group_members VARCHAR,
            manager_cik VARCHAR,
            loaded_at TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS beneficial_ownership_current (
            filer_cik VARCHAR,
            filer_name VARCHAR,
            subject_ticker VARCHAR,
            subject_cusip VARCHAR,
            latest_filing_type VARCHAR,
            latest_filing_date DATE,
            pct_owned DOUBLE,
            shares_owned BIGINT,
            intent VARCHAR,
            crossing_date DATE,
            days_since_filing INTEGER,
            is_current BOOLEAN,
            accession_number VARCHAR
        )
    """)


def get_existing_accessions(con):
    """Get set of already-loaded accession numbers."""
    try:
        rows = con.execute(
            "SELECT accession_number FROM beneficial_ownership"
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def insert_filing(con, record):
    """Insert a single filing record into beneficial_ownership."""
    con.execute("""
        INSERT OR REPLACE INTO beneficial_ownership
        (accession_number, filer_cik, filer_name, subject_cusip, subject_ticker,
         subject_name, filing_type, filing_date, report_date, pct_owned,
         shares_owned, aggregate_value, intent, is_amendment, prior_accession,
         purpose_text, group_members, manager_cik, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        record["accession_number"],
        record["filer_cik"],
        record["filer_name"],
        record.get("subject_cusip"),
        record.get("subject_ticker"),
        record.get("subject_name"),
        record["filing_type"],
        record["filing_date"],
        record.get("report_date"),
        record.get("pct_owned"),
        record.get("shares_owned"),
        record.get("aggregate_value"),
        record["intent"],
        record["is_amendment"],
        record.get("prior_accession"),
        record.get("purpose_text"),
        record.get("group_members"),
        record.get("manager_cik"),
        datetime.now().isoformat(),
    ])


def rebuild_current_view(con):
    """Rebuild beneficial_ownership_current from beneficial_ownership."""
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute("""
        CREATE TABLE beneficial_ownership_current AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY filer_cik, subject_ticker
                    ORDER BY filing_date DESC
                ) as rn
            FROM beneficial_ownership
            WHERE subject_ticker IS NOT NULL
        )
        SELECT
            filer_cik,
            filer_name,
            subject_ticker,
            subject_cusip,
            filing_type AS latest_filing_type,
            filing_date AS latest_filing_date,
            pct_owned,
            shares_owned,
            intent,
            report_date AS crossing_date,
            CAST(CURRENT_DATE - filing_date AS INTEGER) AS days_since_filing,
            CASE WHEN filing_date >= CURRENT_DATE - INTERVAL '2 years' THEN TRUE ELSE FALSE END AS is_current,
            accession_number
        FROM ranked
        WHERE rn = 1
    """)
    count = con.execute("SELECT COUNT(*) FROM beneficial_ownership_current").fetchone()[0]
    print(f"\n  beneficial_ownership_current rebuilt: {count} rows")


def fuzzy_match_managers(con):
    """Match filer_name to managers.manager_name using fuzzy matching."""
    print("\nFuzzy-matching filers to managers table...")

    # Get distinct filer CIKs and names
    filers = con.execute("""
        SELECT DISTINCT filer_cik, filer_name
        FROM beneficial_ownership
        WHERE filer_name IS NOT NULL AND filer_name != 'UNKNOWN'
    """).fetchall()

    # Get managers
    managers = con.execute("""
        SELECT cik, manager_name FROM managers
    """).fetchall()

    # First: direct CIK match
    manager_ciks = {m[0]: m[1] for m in managers}
    matched = 0
    fuzzy_matched = 0

    for filer_cik, filer_name in filers:
        # Direct CIK match
        if filer_cik in manager_ciks:
            con.execute("""
                UPDATE beneficial_ownership
                SET manager_cik = ?
                WHERE filer_cik = ? AND manager_cik IS NULL
            """, [filer_cik, filer_cik])
            matched += 1
            continue

        # Fuzzy match on name
        best_score = 0
        best_cik = None
        for mgr_cik, mgr_name in managers:
            score = fuzz.token_sort_ratio(filer_name.upper(), mgr_name.upper())
            if score > best_score:
                best_score = score
                best_cik = mgr_cik

        if best_score >= 85:
            con.execute("""
                UPDATE beneficial_ownership
                SET manager_cik = ?
                WHERE filer_cik = ? AND manager_cik IS NULL
            """, [best_cik, filer_cik])
            fuzzy_matched += 1

    print(f"  Direct CIK matches: {matched}")
    print(f"  Fuzzy name matches (≥85): {fuzzy_matched}")
    print(f"  Unmatched: {len(filers) - matched - fuzzy_matched}")


def update_managers_has_13dg(con):
    """Add has_13dg flag to managers table."""
    # Add column if not exists
    try:
        con.execute("ALTER TABLE managers ADD COLUMN has_13dg BOOLEAN DEFAULT FALSE")
    except Exception:
        pass  # column already exists

    con.execute("""
        UPDATE managers
        SET has_13dg = TRUE
        WHERE cik IN (
            SELECT DISTINCT filer_cik FROM beneficial_ownership
        )
    """)
    count = con.execute("SELECT COUNT(*) FROM managers WHERE has_13dg = TRUE").fetchone()[0]
    print(f"\n  managers.has_13dg set for {count} managers")


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def init_error_log():
    """Initialize error CSV log."""
    log_path = os.path.join(LOG_DIR, "fetch_13dg_errors.csv")
    if not os.path.exists(log_path):
        with open(log_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "ticker", "accession", "error"])
    return log_path


def log_error(log_path, ticker, accession, error):
    """Append error to log."""
    with open(log_path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), ticker, accession, str(error)])


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def get_target_tickers(con):
    """Get tickers with >$500M institutional value in latest quarter."""
    rows = con.execute("""
        SELECT ticker
        FROM holdings
        WHERE quarter = (SELECT MAX(quarter) FROM holdings)
          AND ticker IS NOT NULL AND ticker != ''
        GROUP BY ticker
        HAVING SUM(market_value_usd) > 500000000
        ORDER BY SUM(market_value_usd) DESC
    """).fetchall()
    return [r[0] for r in rows]


def run(tickers=None, test_mode=False):
    """Main entry point."""
    con = duckdb.connect(DB_PATH)
    create_tables(con)
    error_log = init_error_log()

    existing = get_existing_accessions(con)
    print(f"Already loaded: {len(existing)} filings")

    # Get target tickers
    if test_mode:
        target_tickers = TEST_TICKERS
    elif tickers:
        target_tickers = [t.strip().upper() for t in tickers]
    else:
        target_tickers = get_target_tickers(con)

    print(f"Target tickers: {len(target_tickers)}")

    # Get ticker → company CIK mapping
    ticker_cik_map = get_ticker_to_company_cik()
    time.sleep(SEC_DELAY)

    # Also get CUSIP mapping from securities table
    ticker_cusip = {}
    rows = con.execute("""
        SELECT ticker, cusip FROM securities
        WHERE ticker IS NOT NULL
    """).fetchall()
    for ticker, cusip in rows:
        ticker_cusip[ticker] = cusip

    # Phase 1: Collect all filing metadata
    print("\n--- Phase 1: Listing 13D/G filings ---")
    all_filings = []
    skipped_no_cik = 0

    for i, ticker in enumerate(target_tickers):
        company_cik = ticker_cik_map.get(ticker)
        if not company_cik:
            skipped_no_cik += 1
            continue

        if (i + 1) % 100 == 0 or i < 5:
            print(f"  [{i+1}/{len(target_tickers)}] {ticker} (CIK {company_cik})...")

        try:
            filings = get_company_filings_13dg(company_cik)
            for f in filings:
                if f["accession_number"] not in existing:
                    f["subject_ticker"] = ticker
                    f["subject_cusip"] = ticker_cusip.get(ticker)
                    all_filings.append(f)
        except Exception as e:
            log_error(error_log, ticker, "", str(e))

        time.sleep(SEC_DELAY)

    print(f"\n  Found {len(all_filings)} new filings to download")
    print(f"  Skipped {skipped_no_cik} tickers (no company CIK)")

    if not all_filings:
        print("No new filings to process.")
        rebuild_current_view(con)
        con.close()
        return

    # Phase 2: Get filer names (cached, deduplicated)
    print("\n--- Phase 2: Resolving filer names ---")
    unique_filer_ciks = set(f["filer_cik"] for f in all_filings)
    print(f"  {len(unique_filer_ciks)} unique filers to look up")

    for i, cik in enumerate(unique_filer_ciks):
        if (i + 1) % 50 == 0:
            print(f"    [{i+1}/{len(unique_filer_ciks)}] resolving filer names...")
        get_filer_name(cik)  # populates cache

    # Phase 3: Download and parse each filing
    print(f"\n--- Phase 3: Downloading & parsing {len(all_filings)} filings ---")
    success = 0
    errors = 0
    batch_size = 50

    for i, filing_info in enumerate(all_filings):
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(all_filings)}] parsed {success} OK, {errors} errors")

        acc = filing_info["accession_number"]
        ticker = filing_info["subject_ticker"]

        try:
            # Get filer name from cache (filing agent CIKs may return UNKNOWN)
            filer_name = _filer_name_cache.get(filing_info["filer_cik"], "UNKNOWN")

            # Parse filing text
            parsed = parse_filing_text(filing_info)
            if parsed is None:
                log_error(error_log, ticker, acc, "Could not download filing")
                errors += 1
                time.sleep(SEC_DELAY)
                continue

            # Determine intent
            form = filing_info["filing_type"]
            intent = "activist" if "13D" in form else "passive"
            is_amendment = "/A" in form

            # Use reporting person name when filer is unknown or a filing agent
            filing_agents = {"Toppan Merrill/FA", "UNKNOWN", "Donnelley Financial Solutions",
                             "ADVISER COMPLIANCE ASSOCIATES LLC"}
            if filer_name in filing_agents and parsed.get("reporting_person"):
                filer_name = parsed["reporting_person"]

            # Build record
            record = {
                "accession_number": acc,
                "filer_cik": filing_info["filer_cik"],
                "filer_name": filer_name,
                "subject_cusip": parsed.get("cusip") or filing_info.get("subject_cusip"),
                "subject_ticker": ticker,
                "subject_name": filing_info.get("subject_name"),
                "filing_type": form,
                "filing_date": filing_info["filing_date"],
                "report_date": parsed.get("report_date"),
                "pct_owned": parsed.get("pct_owned"),
                "shares_owned": parsed.get("shares_owned"),
                "aggregate_value": parsed.get("aggregate_value"),
                "intent": intent,
                "is_amendment": is_amendment,
                "prior_accession": None,
                "purpose_text": parsed.get("purpose_text"),
                "group_members": parsed.get("group_members"),
                "manager_cik": None,
            }

            insert_filing(con, record)
            success += 1

        except Exception as e:
            log_error(error_log, ticker, acc, str(e))
            errors += 1

        time.sleep(SEC_DELAY)

        # Periodic commit
        if (i + 1) % batch_size == 0:
            con.execute("CHECKPOINT")

    con.execute("CHECKPOINT")
    print(f"\n  Phase 3 complete: {success} inserted, {errors} errors")

    # Phase 4: Cross-reference with managers
    fuzzy_match_managers(con)

    # Phase 5: Update managers.has_13dg
    update_managers_has_13dg(con)

    # Phase 6: Rebuild current view
    rebuild_current_view(con)

    # Final summary
    total = con.execute("SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    by_type = con.execute("""
        SELECT filing_type, COUNT(*) as cnt
        FROM beneficial_ownership
        GROUP BY filing_type
        ORDER BY cnt DESC
    """).fetchall()

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total beneficial_ownership rows: {total}")
    for ft, cnt in by_type:
        print(f"  {ft}: {cnt}")

    if test_mode or tickers:
        check_tickers = TEST_TICKERS if test_mode else [t.strip().upper() for t in tickers] if isinstance(tickers, list) else TEST_TICKERS
        print(f"\nPer-ticker counts:")
        for t in check_tickers:
            row = con.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE intent = 'activist') as n_13d,
                    COUNT(*) FILTER (WHERE intent = 'passive') as n_13g
                FROM beneficial_ownership
                WHERE subject_ticker = ?
            """, [t]).fetchone()
            print(f"  {t}: 13D={row[0]}, 13G={row[1]}")

    con.close()
    print("\nDone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch 13D/G beneficial ownership filings")
    parser.add_argument("--tickers", type=str, help="Comma-separated tickers")
    parser.add_argument("--test", action="store_true", help="Test mode (5 tickers only)")
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else None
    run(tickers=tickers, test_mode=args.test)
