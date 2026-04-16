#!/usr/bin/env python3
"""
resolve_agent_names.py — Re-download and re-parse filing agent filings to extract
the actual reporting person name.

These are 13D/G filings where filer_cik is a filing agent (Donnelley, etc.)
and the real beneficial owner name is in the filing text.

Usage:
    python3 scripts/resolve_agent_names.py              # dry-run (5 samples)
    python3 scripts/resolve_agent_names.py --apply      # re-parse all agent filings
    python3 scripts/resolve_agent_names.py --apply --workers 4
"""

import argparse
import functools
import re
import subprocess
import time
from datetime import datetime

# Force unbuffered prints
print = functools.partial(print, flush=True)

import duckdb

from db import get_db_path, set_staging_mode

SEC_UA = "serge.tismen@gmail.com"


def clean_text(raw):
    """Strip HTML tags and entities."""
    if len(raw) > 2_000_000:
        raw = raw[:2_000_000]
    text = re.sub(r"<[^>]+>", " ", raw)
    for old, new in [("&nbsp;", " "), ("&#160;", " "), ("&#xa0;", " "),
                     ("&amp;", "&"), ("&#38;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&ldquo;", '"'), ("&rdquo;", '"'), ("&lsquo;", "'"),
                     ("&rsquo;", "'"), ("&#146;", "'"), ("&#147;", '"'),
                     ("&#148;", '"')]:
        text = text.replace(old, new)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    return re.sub(r"\s+", " ", text)


def extract_reporting_person(text):
    """Extract the reporting person name from cleaned filing text.
    Returns the name or None."""
    # Search first 8000 chars (cover page area)
    search_area = text[:8000]

    # Simple, non-backtracking approach: find the keyword, grab text after it
    # until we hit a known stop marker
    for keyword in [
        "NAME OF REPORTING PERSON",
        "NAMES OF REPORTING PERSONS",
        "Item 1",
        "FILED BY",
        "Filed by",
    ]:
        idx = search_area.upper().find(keyword.upper())
        if idx < 0:
            continue
        # Grab 200 chars after keyword
        after = search_area[idx + len(keyword):idx + len(keyword) + 200]
        # Strip leading non-alpha (colons, spaces, dashes, numbers)
        after = re.sub(r"^[\s:.\-\d()\u2013\u2014]+", "", after)
        # Remove I.R.S. identification line if present
        after = re.sub(r"^I\.?R\.?S\.?[^A-Z]*", "", after, flags=re.I)
        after = after.strip()
        # Take text until a stop marker
        m = re.match(r"([A-Z][A-Za-z.'&,\(\)\s/-]{2,80}?)(?=\s*(?:\d\s|CHECK|Item|SEC\s+USE|Pursuant|PURSUANT|S\.?S\.?))",
                     after, re.I)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            # Strip single-letter prefix artifacts (e.g., "S The Phoenix")
            name = re.sub(r"^[A-Z]\s+(?=[A-Z])", "", name)
            # Validate
            if (5 < len(name) < 100
                    and name[0].isalpha()
                    and "I.R.S." not in name
                    and "CHECK" not in name.upper()
                    and "Name of" not in name
                    and not re.match(r"^\d+$", name)
                    and not re.match(r"^[a-z]", name)):
                return name
    return None


def download_filing(acc, subject_cik, filer_cik):
    """Download filing text, trying subject_cik first."""
    for cik in [subject_cik, filer_cik]:
        cik_raw = str(cik).lstrip("0") or "0"
        acc_path = acc.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_path}/{acc}.txt"
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", "-m", "8", "--connect-timeout", "5",
                 "-H", f"User-Agent: {SEC_UA}", url],
                capture_output=True, text=True, timeout=12,
                check=False
            )
            if result.returncode == 0 and len(result.stdout) > 100:
                return result.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.15)
    return None


def process_one(row):
    """Download and extract reporting person for one filing."""
    acc, filer_cik, subject_cik, ticker, form = row
    raw = download_filing(acc, subject_cik, filer_cik)
    if not raw:
        return acc, None, "download_failed"

    text = clean_text(raw)
    if len(text) > 20_000:
        text = text[:20_000]

    name = extract_reporting_person(text)
    if name:
        return acc, name, "ok"
    return acc, None, "no_match"


def main(apply=False, workers=2):
    db_path = get_db_path()
    con = duckdb.connect(db_path)

    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (5 samples)' if not apply else 'APPLY'}")
    print(f"Workers: {workers}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Get all filing-agent accessions with subject_cik
    filings = con.execute("""
        SELECT b.accession_number, b.filer_cik, l.subject_cik,
               b.subject_ticker, b.filing_type
        FROM beneficial_ownership b
        JOIN listed_filings_13dg l ON b.accession_number = l.accession_number
        WHERE b.filer_name = 'Unknown (filing agent)'
        ORDER BY RANDOM()
    """).fetchall()

    total = len(filings)
    print(f"\nFilings to process: {total:,}")

    if not apply:
        filings = filings[:5]
        print("  (dry-run: processing 5 samples)")

    # Process sequentially — ThreadPoolExecutor hangs on Python 3.9/macOS with subprocess
    resolved = {}
    errors = {"download_failed": 0, "no_match": 0}
    t0 = time.time()

    for i, filing in enumerate(filings):
        acc, name, status = process_one(filing)
        if status == "ok":
            resolved[acc] = name
        else:
            errors[status] = errors.get(status, 0) + 1

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(filings) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1:,}/{len(filings):,}] "
                  f"{len(resolved):,} resolved, "
                  f"{errors['no_match']} no_match, "
                  f"{errors['download_failed']} failed "
                  f"({rate:.1f}/s, ETA {eta/60:.0f}m)")

    elapsed = time.time() - t0
    print(f"\nProcessing complete: {elapsed:.0f}s")
    print(f"  Resolved: {len(resolved):,}")
    print(f"  No match: {errors['no_match']:,}")
    print(f"  Download failed: {errors['download_failed']:,}")

    # Show samples
    for acc, name in list(resolved.items())[:10]:
        print(f"  {acc} -> {name}")

    if not apply:
        print("\nRun with --apply to update database.")
        con.close()
        return

    # Apply updates
    if resolved:
        print(f"\nUpdating {len(resolved):,} rows in beneficial_ownership...")
        updated = 0
        for acc, name in resolved.items():
            count = con.execute("""
                UPDATE beneficial_ownership
                SET filer_name = ?, name_resolved = TRUE
                WHERE accession_number = ?
                  AND filer_name = 'Unknown (filing agent)'
            """, [name, acc]).fetchone()
            if count:
                updated += count[0]
        print(f"  Updated {updated:,} rows")

    # Rebuild current view
    print("\nRebuilding beneficial_ownership_current...")
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute("""CREATE TABLE beneficial_ownership_current AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY filer_cik, subject_ticker
                                   ORDER BY filing_date DESC) as rn,
                COUNT(*) OVER (PARTITION BY filer_cik, subject_ticker) as amendment_count,
                LAG(intent) OVER (PARTITION BY filer_cik, subject_ticker
                                  ORDER BY filing_date DESC) as next_older_intent
            FROM beneficial_ownership WHERE subject_ticker IS NOT NULL
        ),
        first_13g AS (
            SELECT filer_cik, subject_ticker, MIN(filing_date) as first_13g_date
            FROM beneficial_ownership
            WHERE subject_ticker IS NOT NULL AND filing_type LIKE 'SC 13G%'
            GROUP BY filer_cik, subject_ticker
        )
        SELECT r.filer_cik, r.filer_name, r.subject_ticker, r.subject_cusip,
            r.filing_type AS latest_filing_type, r.filing_date AS latest_filing_date,
            r.pct_owned, r.shares_owned, r.intent,
            f.first_13g_date AS crossing_date,
            CAST(CURRENT_DATE - r.filing_date AS INTEGER) AS days_since_filing,
            CASE WHEN CAST(CURRENT_DATE - r.filing_date AS INTEGER) <= 365
                 THEN TRUE ELSE FALSE END AS is_current,
            r.accession_number,
            CASE WHEN f.first_13g_date IS NOT NULL THEN TRUE ELSE FALSE END AS crossed_5pct,
            r.next_older_intent AS prior_intent,
            r.amendment_count
        FROM ranked r
        LEFT JOIN first_13g f ON r.filer_cik = f.filer_cik
                              AND r.subject_ticker = f.subject_ticker
        WHERE r.rn = 1
    """)
    cur = con.execute("SELECT COUNT(*) FROM beneficial_ownership_current").fetchone()[0]
    print(f"  beneficial_ownership_current: {cur:,} rows")

    # Final audit
    total_rows = con.execute("SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    still_agent = con.execute("""
        SELECT COUNT(*) FROM beneficial_ownership
        WHERE filer_name = 'Unknown (filing agent)'
    """).fetchone()[0]
    resolved_total = con.execute("""
        SELECT COUNT(*) FROM beneficial_ownership WHERE name_resolved = TRUE
    """).fetchone()[0]

    print("\n--- FINAL STATUS ---")
    print(f"  Total rows:           {total_rows:,}")
    print(f"  Resolved names:       {resolved_total:,} ({100*resolved_total/total_rows:.1f}%)")
    print(f"  Still filing agent:   {still_agent:,} ({100*still_agent/total_rows:.1f}%)")

    con.execute("CHECKPOINT")
    con.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Re-parse filing agent filings to extract reporting person names")
    parser.add_argument("--apply", action="store_true",
                        help="Apply fixes (default is 5-sample dry run)")
    parser.add_argument("--workers", type=int, default=2,
                        help="Download workers (default 2)")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("resolve_agent_names")(
        lambda: main(apply=args.apply, workers=args.workers)
    )
