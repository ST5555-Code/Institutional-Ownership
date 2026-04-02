#!/usr/bin/env python3
"""
fetch_ncen.py — Download N-CEN filings and build adviser-to-series mapping.

N-CEN is the annual census filing for registered investment companies.
It maps Investment Adviser CIK → Fund Series IDs they manage/subadvise.

Builds:
  - ncen_adviser_map table: adviser/subadviser → series_id mapping
  - Updates managers.adviser_cik via fuzzy match

Run: python3 scripts/fetch_ncen.py                  # Full build
     python3 scripts/fetch_ncen.py --test            # Test on 10 fund CIKs
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime

import duckdb
import requests
from lxml import etree
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import get_db_path, crash_handler
LOG_DIR = os.path.join(BASE_DIR, "logs")

SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_DELAY = 0.5
NS = {"n": "http://www.sec.gov/edgar/ncen"}

os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# SEC API helpers
# ---------------------------------------------------------------------------

def sec_get(url, max_retries=3):
    """GET with rate limiting and retry."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=SEC_HEADERS, timeout=60)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if resp.status_code == 404:
                return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(5)
    return None


def find_ncen_filing(cik):
    """Find the most recent N-CEN filing for a fund CIK. Returns (accession, primary_doc) or None."""
    padded_cik = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{padded_cik}.json"
    resp = sec_get(url)
    if not resp:
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    forms = data["filings"]["recent"]["form"]
    accessions = data["filings"]["recent"]["accessionNumber"]
    primary_docs = data["filings"]["recent"]["primaryDocument"]
    dates = data["filings"]["recent"]["filingDate"]

    for i, form in enumerate(forms):
        if form == "N-CEN":
            return {
                "accession": accessions[i],
                "primary_doc": primary_docs[i],
                "filing_date": dates[i],
                "registrant_name": data.get("name", ""),
                "registrant_cik": padded_cik,
            }

    return None


def download_ncen_xml(cik_raw, accession, primary_doc):
    """Download the N-CEN XML file."""
    cik_num = str(cik_raw).lstrip("0") or "0"
    acc_path = accession.replace("-", "")

    # If primary_doc includes a path (xslFormN-CEN_X01/primary_doc.xml), get raw XML
    # Raw XML is always at primary_doc.xml in the root of the filing directory
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_path}/primary_doc.xml"
    resp = sec_get(url)
    if resp:
        return resp.content

    # Fallback: try the specified primary_doc path
    clean_doc = primary_doc.split("/")[-1]
    url2 = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_path}/{clean_doc}"
    resp2 = sec_get(url2)
    if resp2:
        return resp2.content

    return None


def parse_ncen_xml(xml_content, filing_info):
    """Parse N-CEN XML and extract adviser-to-series mappings."""
    try:
        root = etree.fromstring(xml_content)
    except etree.XMLSyntaxError:
        return []

    # Get registrant info
    registrant_cik = filing_info["registrant_cik"]
    registrant_name = filing_info["registrant_name"]
    filing_date = filing_info["filing_date"]

    # Find report date
    report_date = root.findtext(".//n:reportPeriodDate", namespaces=NS) or filing_date

    # Get series (managementInvestmentQuestion) and their advisers/subadvisers
    miq_elements = root.findall(".//n:managementInvestmentQuestion", NS)
    adviser_elements = root.findall(".//n:investmentAdviser", NS)
    subadviser_elements = root.findall(".//n:subAdviser", NS)

    records = []

    for i in range(len(miq_elements)):
        series_id = miq_elements[i].findtext("n:mgmtInvSeriesId", namespaces=NS) or ""
        series_name = miq_elements[i].findtext("n:mgmtInvFundName", namespaces=NS) or ""

        # Primary adviser
        if i < len(adviser_elements):
            adv = adviser_elements[i]
            adv_name = adv.findtext("n:investmentAdviserName", namespaces=NS) or ""
            adv_file = adv.findtext("n:investmentAdviserFileNo", namespaces=NS) or ""
            adv_crd = adv.findtext("n:investmentAdviserCrdNo", namespaces=NS) or ""
            adv_lei = adv.findtext("n:investmentAdviserLei", namespaces=NS) or ""

            if adv_name:
                records.append({
                    "registrant_cik": registrant_cik,
                    "registrant_name": registrant_name,
                    "adviser_name": adv_name,
                    "adviser_sec_file": adv_file,
                    "adviser_crd": adv_crd,
                    "adviser_lei": adv_lei,
                    "role": "adviser",
                    "series_id": series_id,
                    "series_name": series_name,
                    "report_date": report_date,
                    "filing_date": filing_date,
                })

        # Subadviser
        if i < len(subadviser_elements):
            sub = subadviser_elements[i]
            sub_name = sub.findtext("n:subAdviserName", namespaces=NS) or ""
            sub_file = sub.findtext("n:subAdviserFileNo", namespaces=NS) or ""
            sub_crd = sub.findtext("n:subAdviserCrdNo", namespaces=NS) or ""
            sub_lei = sub.findtext("n:subAdviserLei", namespaces=NS) or ""

            if sub_name:
                records.append({
                    "registrant_cik": registrant_cik,
                    "registrant_name": registrant_name,
                    "adviser_name": sub_name,
                    "adviser_sec_file": sub_file,
                    "adviser_crd": sub_crd,
                    "adviser_lei": sub_lei,
                    "role": "subadviser",
                    "series_id": series_id,
                    "series_name": series_name,
                    "report_date": report_date,
                    "filing_date": filing_date,
                })

    return records


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def create_tables(con):
    """Create ncen_adviser_map table."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS ncen_adviser_map (
            registrant_cik VARCHAR,
            registrant_name VARCHAR,
            adviser_name VARCHAR,
            adviser_sec_file VARCHAR,
            adviser_crd VARCHAR,
            adviser_lei VARCHAR,
            role VARCHAR,
            series_id VARCHAR,
            series_name VARCHAR,
            report_date DATE,
            filing_date DATE,
            loaded_at TIMESTAMP
        )
    """)


def get_processed_ciks(con):
    """Get set of registrant CIKs already in ncen_adviser_map."""
    try:
        rows = con.execute(
            "SELECT DISTINCT registrant_cik FROM ncen_adviser_map"
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def insert_records(con, records):
    """Bulk insert records."""
    now = datetime.now().isoformat()
    for r in records:
        con.execute("""
            INSERT INTO ncen_adviser_map
            (registrant_cik, registrant_name, adviser_name, adviser_sec_file,
             adviser_crd, adviser_lei, role, series_id, series_name,
             report_date, filing_date, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            r["registrant_cik"], r["registrant_name"],
            r["adviser_name"], r["adviser_sec_file"],
            r["adviser_crd"], r["adviser_lei"],
            r["role"], r["series_id"], r["series_name"],
            r["report_date"], r["filing_date"], now,
        ])


def update_managers_adviser_cik(con):
    """Add adviser_cik to managers table by fuzzy matching adviser names."""
    try:
        con.execute("ALTER TABLE managers ADD COLUMN adviser_cik VARCHAR")
    except Exception:
        pass

    # Get unique advisers from ncen_adviser_map
    advisers = con.execute("""
        SELECT DISTINCT adviser_name, adviser_crd
        FROM ncen_adviser_map
        WHERE adviser_name IS NOT NULL AND adviser_name != ''
    """).fetchall()

    managers = con.execute("""
        SELECT cik, manager_name FROM managers
    """).fetchall()

    matched = 0
    for adv_name, adv_crd in advisers:
        best_score = 0
        best_mgr_cik = None
        for mgr_cik, mgr_name in managers:
            score = fuzz.token_sort_ratio(adv_name.upper(), mgr_name.upper())
            if score > best_score:
                best_score = score
                best_mgr_cik = mgr_cik

        if best_score >= 85 and adv_crd:
            con.execute("""
                UPDATE managers
                SET adviser_cik = ?
                WHERE cik = ? AND adviser_cik IS NULL
            """, [adv_crd, best_mgr_cik])
            matched += 1

    print(f"  Matched {matched} advisers to managers (fuzzy ≥85)")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(test_mode=False):
    con = duckdb.connect(get_db_path())
    create_tables(con)

    # Get target fund CIKs from fund_universe
    fund_ciks = con.execute("""
        SELECT DISTINCT fund_cik FROM fund_universe
        ORDER BY fund_cik
    """).fetchall()
    fund_ciks = [r[0] for r in fund_ciks]

    if test_mode:
        fund_ciks = fund_ciks[:10]

    processed = get_processed_ciks(con)
    print(f"Fund CIKs to process: {len(fund_ciks)} ({len(processed)} already done)")

    # Filter to unprocessed
    fund_ciks = [c for c in fund_ciks if c not in processed]
    print(f"Remaining: {len(fund_ciks)}")

    total_records = 0
    errors = 0
    no_ncen = 0

    for i, cik in enumerate(fund_ciks):
        if (i + 1) % 50 == 0 or i < 3:
            print(f"  [{i+1}/{len(fund_ciks)}] CIK {cik}... ({total_records} records so far)")

        # Find N-CEN filing
        filing = find_ncen_filing(cik)
        time.sleep(SEC_DELAY)

        if not filing:
            no_ncen += 1
            continue

        # Download XML
        xml = download_ncen_xml(cik, filing["accession"], filing["primary_doc"])
        time.sleep(SEC_DELAY)

        if not xml:
            errors += 1
            continue

        # Parse
        records = parse_ncen_xml(xml, filing)
        if records:
            insert_records(con, records)
            total_records += len(records)

        # Checkpoint periodically
        if (i + 1) % 25 == 0:
            con.execute("CHECKPOINT")

    con.execute("CHECKPOINT")
    print(f"\nInserted {total_records} adviser-series mappings")
    print(f"No N-CEN found: {no_ncen}, Errors: {errors}")

    # Update managers table
    print("\nUpdating managers.adviser_cik...")
    update_managers_adviser_cik(con)

    # Summary
    total = con.execute("SELECT COUNT(*) FROM ncen_adviser_map").fetchone()[0]
    roles = con.execute("""
        SELECT role, COUNT(*) FROM ncen_adviser_map GROUP BY role
    """).fetchall()
    unique_advisers = con.execute("""
        SELECT COUNT(DISTINCT adviser_name) FROM ncen_adviser_map
    """).fetchone()[0]
    unique_series = con.execute("""
        SELECT COUNT(DISTINCT series_id) FROM ncen_adviser_map
    """).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total ncen_adviser_map rows: {total}")
    for role, cnt in roles:
        print(f"  {role}: {cnt}")
    print(f"Unique advisers: {unique_advisers}")
    print(f"Unique series: {unique_series}")

    # Wellington test
    wellington = con.execute("""
        SELECT series_id, series_name, registrant_name, role
        FROM ncen_adviser_map
        WHERE adviser_name LIKE '%Wellington%'
        ORDER BY registrant_name, series_name
    """).fetchall()
    if wellington:
        print(f"\nWellington Management series ({len(wellington)}):")
        for r in wellington[:15]:
            print(f"  {r[0]:15s} {r[1]:45s} ({r[2]}) [{r[3]}]")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch N-CEN adviser mappings")
    parser.add_argument("--test", action="store_true", help="Test on 10 fund CIKs")
    args = parser.parse_args()
    crash_handler("fetch_ncen")(lambda: run(test_mode=args.test))
