#!/usr/bin/env python3
"""
resolve_names.py — Resolve raw CIK filer_names in beneficial_ownership.

Three-pass resolution:
  1. Match filer_cik against holdings.cik for manager_name / inst_parent_name
  2. Batch lookup remaining CIKs via SEC EDGAR submissions API
  3. Add name_resolved column for audit trail

Usage:
    python3 scripts/resolve_names.py              # dry-run audit only
    python3 scripts/resolve_names.py --apply      # apply fixes to production DB
    python3 scripts/resolve_names.py --staging    # apply to staging DB
"""

import argparse
import json
import re
import subprocess
import time
from datetime import datetime

import duckdb

from db import get_db_path, set_staging_mode

CIK_PATTERN = re.compile(r'^\d{7,10}$')
SEC_UA = "serge.tismen@gmail.com"


def get_unresolved(con):
    """Return dict of filer_cik -> (filer_name, row_count) for unresolved rows."""
    rows = con.execute("""
        SELECT filer_cik, filer_name, COUNT(*) as cnt
        FROM beneficial_ownership
        WHERE filer_name IS NULL OR filer_name = ''
           OR regexp_matches(filer_name, '^\\d{7,10}$')
        GROUP BY filer_cik, filer_name
        ORDER BY cnt DESC
    """).fetchall()
    result = {}
    for cik, name, cnt in rows:
        result[cik] = (name, cnt)
    return result


def resolve_via_holdings(con, unresolved_ciks):
    """Match unresolved CIKs against holdings table manager_name / inst_parent_name."""
    resolved = {}
    rows = con.execute("""
        SELECT DISTINCT cik,
               COALESCE(inst_parent_name, manager_name) as resolved_name
        FROM holdings
        WHERE manager_name IS NOT NULL AND manager_name != ''
          AND NOT regexp_matches(manager_name, '^\\d{7,10}$')
    """).fetchall()

    holdings_map = {r[0]: r[1] for r in rows}

    for cik in unresolved_ciks:
        # Try direct match, also try zero-padded to 10 digits
        padded = cik.lstrip('0').zfill(10)
        if padded in holdings_map:
            resolved[cik] = holdings_map[padded]
        elif cik in holdings_map:
            resolved[cik] = holdings_map[cik]

    return resolved


def resolve_via_edgar(unresolved_ciks, rate_limit=5):
    """Batch lookup CIK names from SEC EDGAR submissions endpoint."""
    resolved = {}
    errors = []
    delay = 1.0 / rate_limit  # 0.2s for 5 req/s

    total = len(unresolved_ciks)
    print(f"  Looking up {total} CIKs from SEC EDGAR...")

    for i, cik in enumerate(unresolved_ciks):
        # Strip leading zeros for API, then zero-pad to 10
        cik_num = cik.lstrip('0')
        cik_padded = cik_num.zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

        try:
            result = subprocess.run(
                ["curl", "-s", "-H", f"User-Agent: {SEC_UA}", url],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                name = data.get("name", "").strip()
                if name and not CIK_PATTERN.match(name):
                    resolved[cik] = name
                else:
                    errors.append((cik, "no name in response"))
            else:
                errors.append((cik, f"curl error rc={result.returncode}"))
        except subprocess.TimeoutExpired:
            errors.append((cik, "timeout"))
        except json.JSONDecodeError:
            errors.append((cik, "invalid JSON"))
        except Exception as e:
            errors.append((cik, str(e)))

        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{total} looked up, {len(resolved)} resolved so far")

        time.sleep(delay)

    if errors:
        print(f"  {len(errors)} lookup errors")
        for cik, err in errors[:10]:
            print(f"    CIK {cik}: {err}")

    return resolved


def resolve_via_company_tickers(unresolved_ciks):
    """Try SEC company_tickers.json for any CIKs not found via submissions API."""
    print("  Downloading SEC company_tickers.json...")
    result = subprocess.run(
        ["curl", "-sL", "-H", f"User-Agent: {SEC_UA}",
         "https://www.sec.gov/files/company_tickers.json"],
        capture_output=True, text=True, timeout=30
    )
    data = json.loads(result.stdout)
    cik_map = {str(e['cik_str']).zfill(10): e['title'] for e in data.values()}
    print(f"  Loaded {len(cik_map):,} CIK→name mappings")

    resolved = {}
    for cik in unresolved_ciks:
        padded = cik.lstrip('0').zfill(10)
        if padded in cik_map:
            resolved[cik] = cik_map[padded]
    return resolved


def apply_resolutions(con, resolved_map, source_label):
    """UPDATE beneficial_ownership.filer_name for resolved CIKs."""
    updated = 0
    for cik, name in resolved_map.items():
        count = con.execute("""
            UPDATE beneficial_ownership
            SET filer_name = ?
            WHERE filer_cik = ?
              AND (filer_name IS NULL OR filer_name = '' OR regexp_matches(filer_name, '^\\d{7,10}$'))
        """, [name, cik]).fetchone()
        if count:
            updated += count[0]
    print(f"  [{source_label}] Updated {updated:,} rows across {len(resolved_map)} CIKs")
    return updated


def add_name_resolved_column(con):
    """Add name_resolved boolean column if it doesn't exist, then populate."""
    # Check if column exists
    cols = [c[0] for c in con.execute("DESCRIBE beneficial_ownership").fetchall()]
    if 'name_resolved' not in cols:
        con.execute("ALTER TABLE beneficial_ownership ADD COLUMN name_resolved BOOLEAN DEFAULT FALSE")
        print("  Added name_resolved column")

    # Mark all rows with proper names as resolved
    count = con.execute("""
        UPDATE beneficial_ownership
        SET name_resolved = TRUE
        WHERE filer_name IS NOT NULL AND filer_name != ''
          AND NOT regexp_matches(filer_name, '^\\d{7,10}$')
          AND (name_resolved IS NULL OR name_resolved = FALSE)
    """).fetchone()
    resolved_count = count[0] if count else 0
    print(f"  Marked {resolved_count:,} rows as name_resolved = TRUE")

    # Mark unresolved rows explicitly FALSE
    count2 = con.execute("""
        UPDATE beneficial_ownership
        SET name_resolved = FALSE
        WHERE (filer_name IS NULL OR filer_name = '' OR regexp_matches(filer_name, '^\\d{7,10}$'))
          AND (name_resolved IS NULL OR name_resolved = TRUE)
    """).fetchone()
    unresolved_count = count2[0] if count2 else 0
    print(f"  Marked {unresolved_count:,} rows as name_resolved = FALSE")


def rebuild_current(con):
    """Rebuild beneficial_ownership_current to pick up new filer_names."""
    print("  Rebuilding beneficial_ownership_current...")
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute("""CREATE TABLE beneficial_ownership_current AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY filer_cik, subject_ticker ORDER BY filing_date DESC) as rn,
                COUNT(*) OVER (PARTITION BY filer_cik, subject_ticker) as amendment_count,
                LAG(intent) OVER (PARTITION BY filer_cik, subject_ticker ORDER BY filing_date DESC) as next_older_intent
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
            CASE WHEN CAST(CURRENT_DATE - r.filing_date AS INTEGER) <= 365 THEN TRUE ELSE FALSE END AS is_current,
            r.accession_number,
            CASE WHEN f.first_13g_date IS NOT NULL THEN TRUE ELSE FALSE END AS crossed_5pct,
            r.next_older_intent AS prior_intent,
            r.amendment_count
        FROM ranked r
        LEFT JOIN first_13g f ON r.filer_cik = f.filer_cik AND r.subject_ticker = f.subject_ticker
        WHERE r.rn = 1
    """)
    count = con.execute("SELECT COUNT(*) FROM beneficial_ownership_current").fetchone()[0]
    print(f"  beneficial_ownership_current: {count:,} rows")


def main(apply=False):
    db_path = get_db_path()
    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN' if not apply else 'APPLY'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    t_start = time.time()

    con = duckdb.connect(db_path)

    # --- Audit before ---
    print("\n--- BEFORE ---")
    unresolved = get_unresolved(con)
    total_unresolved_rows = sum(cnt for _, cnt in unresolved.values())
    total_rows = con.execute("SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    print(f"  Total rows: {total_rows:,}")
    print(f"  Unresolved: {total_unresolved_rows:,} rows across {len(unresolved)} CIKs ({100*total_unresolved_rows/total_rows:.1f}%)")

    # Already resolved (have real names)
    already_resolved = total_rows - total_unresolved_rows
    print(f"  Already resolved: {already_resolved:,} rows")

    if not apply:
        # Dry run: just show what would happen
        print("\n--- Pass 1: Holdings cross-reference (dry run) ---")
        holdings_resolved = resolve_via_holdings(con, set(unresolved.keys()))
        rows_fixable = sum(unresolved[cik][1] for cik in holdings_resolved if cik in unresolved)
        print(f"  Would resolve {len(holdings_resolved)} CIKs ({rows_fixable:,} rows) via holdings")
        for cik, name in list(holdings_resolved.items())[:10]:
            print(f"    {cik} → {name}  ({unresolved[cik][1]} rows)")

        remaining = set(unresolved.keys()) - set(holdings_resolved.keys())
        remaining_rows = sum(unresolved[cik][1] for cik in remaining)
        print(f"\n  Remaining for EDGAR lookup: {len(remaining)} CIKs ({remaining_rows:,} rows)")
        print("\nRun with --apply to execute updates.")
        con.close()
        return

    # --- Pass 1: Resolve via holdings ---
    print("\n--- Pass 1: Resolve via holdings table ---")
    holdings_resolved = resolve_via_holdings(con, set(unresolved.keys()))
    if holdings_resolved:
        apply_resolutions(con, holdings_resolved, "holdings")

    # --- Pass 2: Resolve via EDGAR submissions API ---
    remaining_ciks = set(unresolved.keys()) - set(holdings_resolved.keys())
    print(f"\n--- Pass 2: Resolve via SEC EDGAR ({len(remaining_ciks)} CIKs) ---")
    edgar_resolved = {}
    if remaining_ciks:
        edgar_resolved = resolve_via_edgar(sorted(remaining_ciks))
        if edgar_resolved:
            apply_resolutions(con, edgar_resolved, "EDGAR")

    # --- Pass 2b: Try company_tickers.json for remaining ---
    remaining_ciks -= set(edgar_resolved.keys())
    ct_resolved = {}
    if remaining_ciks:
        print(f"\n--- Pass 2b: Resolve via company_tickers.json ({len(remaining_ciks)} CIKs) ---")
        ct_resolved = resolve_via_company_tickers(remaining_ciks)
        if ct_resolved:
            apply_resolutions(con, ct_resolved, "company_tickers")

    # --- Pass 2c: Mark remaining as filing agents ---
    remaining_ciks -= set(ct_resolved.keys())
    if remaining_ciks:
        print(f"\n--- Pass 2c: Mark {len(remaining_ciks)} remaining as filing agents ---")
        marked = 0
        for cik in remaining_ciks:
            count = con.execute("""
                UPDATE beneficial_ownership
                SET filer_name = 'Unknown (filing agent)'
                WHERE filer_cik = ?
                  AND (filer_name IS NULL OR filer_name = ''
                       OR regexp_matches(filer_name, '^\\d{7,10}$'))
            """, [cik]).fetchone()
            if count:
                marked += count[0]
        print(f"  Marked {marked:,} rows as 'Unknown (filing agent)'")

    # --- Pass 3: Add name_resolved column ---
    print("\n--- Pass 3: Add name_resolved column ---")
    add_name_resolved_column(con)

    # --- Rebuild current view ---
    print("\n--- Rebuilding current view ---")
    rebuild_current(con)

    # --- Audit after ---
    print("\n--- AFTER ---")
    unresolved_after = get_unresolved(con)
    total_unresolved_after = sum(cnt for _, cnt in unresolved_after.values())
    named = total_rows - total_unresolved_after
    agent_rows = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership WHERE filer_name = 'Unknown (filing agent)'"
    ).fetchone()[0]
    print(f"  Total rows:        {total_rows:,}")
    print(f"  Named filers:      {named:,} ({100*named/total_rows:.1f}%)")
    print(f"  Filing agents:     {agent_rows:,} ({100*agent_rows/total_rows:.1f}%)")
    print(f"  Raw CIK remaining: {total_unresolved_after:,}")
    print("  Resolved this run:")
    print(f"    via holdings:         {len(holdings_resolved)} CIKs")
    print(f"    via EDGAR:            {len(edgar_resolved)} CIKs")
    print(f"    via company_tickers:  {len(ct_resolved)} CIKs")

    con.execute("CHECKPOINT")
    con.close()

    elapsed = time.time() - t_start
    print(f"\nCompleted in {elapsed:.0f}s")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Resolve raw CIK filer_names in beneficial_ownership")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default is dry-run audit)")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("resolve_names")(lambda: main(apply=args.apply))
