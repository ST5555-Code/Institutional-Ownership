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
import csv
import os
import re
import time
from datetime import datetime

import duckdb
import requests
from lxml import etree
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# INF17b — Brand-token verification gate (same logic as build_managers.py)
# ---------------------------------------------------------------------------
_BRAND_STOPWORDS = frozenset({
    "llc", "lp", "inc", "ltd", "co", "corp", "fund", "capital", "management",
    "advisors", "partners", "holdings", "group", "the", "and", "of", "asset",
    "investment", "financial", "services", "wealth",
})


def _brand_tokens(name):
    """Non-stopword brand tokens from a firm name (INF17b)."""
    if not name:
        return set()
    raw = re.split(r"[^a-z0-9]+", str(name).lower())
    return {t for t in raw if len(t) >= 3 and t not in _BRAND_STOPWORDS}


def _brand_tokens_overlap(a, b):
    """True if two firm names share at least one brand token."""
    ta = _brand_tokens(a)
    tb = _brand_tokens(b)
    return bool(ta and tb and (ta & tb))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import set_staging_mode, get_db_path, crash_handler, record_freshness
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
        except requests.RequestException:
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
        root = etree.fromstring(xml_content)  # pylint: disable=c-extension-no-member
    except etree.XMLSyntaxError:  # pylint: disable=c-extension-no-member
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
# Routing drift check
# ---------------------------------------------------------------------------

def check_routing_drift(con):
    """Compare current N-CEN sub-advisers against manual decision_maker_v1 routings.
    Log any series where N-CEN now shows a different sub-adviser than our manual
    routing so human reviewers can update manual fixes when source data changes.
    """
    import os  # pylint: disable=reimported
    from datetime import datetime  # pylint: disable=reimported

    try:
        drifted = con.execute("""
            SELECT
                erh.entity_id,
                ei.identifier_value AS series_id,
                ea_current.alias_name AS current_routing,
                ncen.adviser_name AS ncen_current,
                erh.rule_applied,
                erh.review_due_date
            FROM entity_rollup_history erh
            JOIN entity_aliases ea_current
                ON erh.rollup_entity_id = ea_current.entity_id
                AND ea_current.is_preferred = TRUE
                AND ea_current.valid_to = '9999-12-31'
            JOIN entity_identifiers ei
                ON erh.entity_id = ei.entity_id
                AND ei.identifier_type = 'series_id'
                AND ei.valid_to = '9999-12-31'
            LEFT JOIN ncen_adviser_map ncen
                ON ei.identifier_value = ncen.series_id
                AND ncen.role = 'subadviser'
            WHERE erh.rollup_type = 'decision_maker_v1'
              AND erh.routing_confidence IN ('low', 'medium')
              AND erh.valid_to = '9999-12-31'
              AND ncen.adviser_name IS NOT NULL
              AND LOWER(TRIM(ea_current.alias_name)) != LOWER(TRIM(ncen.adviser_name))
        """).fetchall()
    except Exception as e:
        print(f"  check_routing_drift: skipped ({e})")
        return

    if not drifted:
        print("  No drift detected — manual routings still match N-CEN")
        return

    os.makedirs('logs', exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open('logs/ncen_routing_drift.log', 'a', encoding='utf-8') as f:
        for row in drifted:
            entity_id, series_id, current, ncen_current, rule, due = row
            f.write(f"{ts}|{entity_id}|{series_id}|{current}|{ncen_current}|{rule}|{due}\n")
    print(f"  Drift detected: {len(drifted)} series — logged to logs/ncen_routing_drift.log")


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
    except Exception:  # nosec B110 — column already exists on subsequent runs
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

    # INF17b: rejection audit log — same pattern as build_managers.py Phase 3
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rejections_path = os.path.join(base_dir, "logs", "fetch_ncen_rejected_crds.csv")
    os.makedirs(os.path.dirname(rejections_path), exist_ok=True)
    matched = 0
    rejected_count = 0
    with open(rejections_path, "w", encoding="utf-8", newline="") as rej_file:
        rej_writer = csv.writer(rej_file)
        rej_writer.writerow(
            ["adviser_name", "adviser_crd", "matched_cik", "matched_name", "score", "reason"]
        )

        for adv_name, adv_crd in advisers:
            best_score = 0
            best_mgr_cik = None
            best_mgr_name = None
            for mgr_cik, mgr_name in managers:
                score = fuzz.token_sort_ratio(adv_name.upper(), mgr_name.upper())
                if score > best_score:
                    best_score = score
                    best_mgr_cik = mgr_cik
                    best_mgr_name = mgr_name

            if best_score >= 85 and adv_crd:
                # INF17b gate: brand-token overlap required
                if not _brand_tokens_overlap(adv_name, best_mgr_name):
                    rej_writer.writerow(
                        [adv_name, adv_crd, best_mgr_cik, best_mgr_name,
                         best_score, "brand_token_mismatch"]
                    )
                    rejected_count += 1
                    continue

                norm_crd = str(adv_crd).lstrip("0") or "0"  # INF4b: normalize CRD format
                con.execute("""
                    UPDATE managers
                    SET adviser_cik = ?
                    WHERE cik = ? AND adviser_cik IS NULL
                """, [norm_crd, best_mgr_cik])
                matched += 1

    print(f"  Matched {matched} advisers to managers (fuzzy ≥85, brand-token gate on)")
    print(f"  Rejected: {rejected_count}  (log: {rejections_path})")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _entity_tables_exist(con):
    """Check if entity MDM tables exist in the current DB (staging only)."""
    try:
        con.execute("SELECT 1 FROM entities LIMIT 0")
        return True
    except Exception:
        return False


def run(test_mode=False, staging=False):
    con = duckdb.connect(get_db_path())
    create_tables(con)

    # Phase 2: if staging mode and entity tables exist, wire entity_sync
    do_entity_sync = staging and _entity_tables_exist(con)
    if staging and not do_entity_sync:
        print("  [entity_sync] entity tables not found in staging — skipping entity sync.")
        print("  [entity_sync] Run build_entities.py --reset first to create entity tables.")

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

            # Phase 2: sync new ncen rows into entity MDM tables (staging only)
            if do_entity_sync:
                import entity_sync  # noqa: E402

                for rec in records:
                    entity_sync.sync_from_ncen_row(
                        con,
                        adviser_name=rec.get("adviser_name"),
                        adviser_crd=rec.get("adviser_crd"),
                        series_id=rec.get("series_id"),
                        role=rec.get("role", ""),
                    )

        # Checkpoint periodically
        if (i + 1) % 25 == 0:
            con.execute("CHECKPOINT")

    con.execute("CHECKPOINT")
    print(f"\nInserted {total_records} adviser-series mappings")
    print(f"No N-CEN found: {no_ncen}, Errors: {errors}")

    # Update managers table
    print("\nUpdating managers.adviser_cik...")
    update_managers_adviser_cik(con)

    # Check for routing drift against manual decision_maker_v1 routings
    print("\nChecking routing drift against manual sub-adviser routings...")
    check_routing_drift(con)

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
    print("SUMMARY")
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

    # Phase 2: entity sync summary (staging only)
    if do_entity_sync:
        ent_count = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        rel_count = con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0]
        staging_count = con.execute(
            "SELECT COUNT(*) FROM entity_identifiers_staging WHERE review_status='pending'"
        ).fetchone()[0]
        print(f"\n[entity_sync] entities: {ent_count}, relationships: {rel_count}")
        print(f"[entity_sync] identifier conflicts pending review: {staging_count}")

    try:
        con.execute("CHECKPOINT")
        record_freshness(con, "ncen_adviser_map")
    except Exception as e:
        print(f"  [warn] record_freshness(ncen_adviser_map) failed: {e}", flush=True)
    con.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch N-CEN adviser mappings")
    parser.add_argument("--test", action="store_true", help="Test on 10 fund CIKs")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()

    is_staging = hasattr(args, 'staging') and args.staging
    if is_staging:
        set_staging_mode(True)
    crash_handler("fetch_ncen")(lambda: run(test_mode=args.test, staging=is_staging))
