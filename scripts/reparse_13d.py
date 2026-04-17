#!/usr/bin/env python3
"""
reparse_13d.py — Re-download SC 13D/13D-A filings and extract shares_owned + pct_owned.

The original parser missed ~96% of 13D pct_owned and ~16% of shares_owned due to
cover page format differences vs 13G. This script re-downloads the filing text and
applies improved regex patterns.

Restart-safe: only processes rows where shares_owned IS NULL OR pct_owned IS NULL.
Incremental: UPDATEs each row immediately, CHECKPOINTs every 500.

Usage:
    python3 scripts/reparse_13d.py              # dry-run (10 samples)
    python3 scripts/reparse_13d.py --apply      # re-parse all
"""

import argparse
import functools
import re
import subprocess
import time
from datetime import datetime

# Intentional shadow: force flush=True so background-run logs appear
# in real time. See feedback_buffered_output. Rename would require
# updating every print() call site in this script — do not refactor.
print = functools.partial(print, flush=True)  # pylint: disable=redefined-builtin

import duckdb

from db import get_db_path, set_staging_mode

SEC_UA = "serge.tismen@gmail.com"

# Rate limiter
_last_request_time = 0.0
_MIN_INTERVAL = 0.13


def _rate_wait():
    global _last_request_time  # pylint: disable=W0603  # module-level cache: SEC rate-limit timestamp
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _last_request_time)
    if wait > 0:
        time.sleep(wait)
    _last_request_time = time.monotonic()


def clean_text(raw):
    """Strip HTML tags and entities, collapse whitespace.
    Handles em-dashes, hex entities, and spaced digits."""
    if len(raw) > 200_000:
        raw = raw[:200_000]
    text = re.sub(r"<[^>]+>", " ", raw)
    for old, new in [("&nbsp;", " "), ("&#160;", " "), ("&#xa0;", " "),
                     ("&amp;", "&"), ("&#38;", "&"), ("&lt;", "<"),
                     ("&gt;", ">"), ("&rsquo;", "'"), ("&ldquo;", '"'),
                     ("&rdquo;", '"'), ("&sect;", "§"),
                     ("&#x2013;", "-"), ("&#x2014;", "-"),
                     ("&#x2610;", " "), ("&#xA0;", " ")]:
        text = text.replace(old, new)
    text = re.sub(r"&#x[0-9a-fA-F]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)
    return re.sub(r"\s+", " ", text)


def extract_pct_owned(text):
    """Extract percentage of class from 13D/G cover page. Returns float or None."""
    for pat in [
        # 13G verbose: 'PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (9): 5.3%'
        r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*[\(\[]?9[\)\]]?[\s.:]*(\d+[\.,]?\d*)\s*%",
        # 13D Row 13: '13 PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (11) 18.6%'
        r"13[\.\s]*PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+(?:AMOUNT\s+IN\s+)?ROW\s*[\(\[]?11[\)\]]?\s*(\d+[\.,]?\d*)\s*%",
        # Wide gap: 'PERCENT OF CLASS...ROW (11) (see Item 5) 9.2%'
        r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+(?:AMOUNT\s+IN\s+)?ROW\s*[\(\[]?(?:9|11)[\)\]]?\D{0,80}?(\d{1,3}[\.,]?\d*)\s*%",
        # 'Percentage of Class Represented by Amount in Row (9): 9.99%'
        r"Percentage\s+of\s+Class\s+Represented\s+by\s+Amount\s+in\s+Row\s*[\(\[]?(?:9|11)[\)\]]?[\s.:]*(\d+[\.,]?\d*)\s*%",
        # Compact: 'Item 11: Percent of Class Owned: 8.1%'
        r"Item\s*11[\s.:]+(?:Percent|Pct|Percentage)\s+of\s+Class\s+(?:Owned|Represented)\D{0,20}?(\d+[\.,]?\d*)\s*%",
        # Item 11 bare: 'Item 11  5.3%'
        r"Item\s*11[\s.:]+(\d+[\.,]?\d*)\s*%",
        # Bare: 'Percent/Percentage of Class Owned: 5.3%'
        r"(?:Percent|PERCENT|Pct|Percentage)\s+of\s+(?:the\s+)?Class\s*(?:Owned|Represented)?[\s.:]*(\d+[\.,]?\d*)\s*%",
        # Broader fallback
        r"percent\s+of\s+class\D{0,60}?(\d{1,3}\.\d+)\s*%",
        # TR-1 (UK format): 'Resulting situation ... 26.95%'
        r"(?:Resulting|New)\s+(?:situation|percentage)[^%]{0,100}?(\d+[\.,]\d+)\s*%",
        # No % sign: 'PERCENT OF CLASS...28.4 (1)'
        r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+(?:AMOUNT\s+IN\s+)?ROW\s*[\(\[]?(?:9|11)[\)\]]?\D{0,60}?(\d{1,3}[\.,]\d+)",
        # Entity-name prefix: 'Camber Capital - 12.25%'
        r"(?:Percent|Percentage)\s+of\s+Class\s+Represented\s+by\s+Amount\s+in\s+Row\s*[\(\[]?(?:9|11)[\)\]]?\D{5,80}?(\d+[\.,]\d+)\s*%",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
                if 0 <= val <= 100:
                    return val
            except ValueError:
                pass
    return None


def extract_shares_owned(text):
    """Extract aggregate shares beneficially owned from 13D/G cover page. Returns int or None."""
    for pat in [
        # Verbose with footnote stripping: '...REPORTING PERSON: (1) 11,265,678'
        r"AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED\s+BY\s+EACH\s+REPORTING\s+PERSON[\s.:]*(?:\(\d+\)\s*)?(\d[\d,]+)",
        # With row number prefix
        r"(?:9|11)[\.\s]+AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED[^0-9]{0,60}?(\d[\d,]+)",
        # Row 9 with entity name: 'Aggregate Amount...Camber Capital — 3,250,000 shares'
        r"Aggregate\s+Amount\s+(?:Beneficially\s+)?Owned\s+by\s+Each\s+Reporting\s+Person\D{0,80}?([\d,]{4,})",
        # Compact: 'Item 9: Aggregate Amount Owned: 3,007,507'
        r"Item\s*9[\s.:]+Aggregate\s+Amount\s+(?:Beneficially\s+)?Owned[\s.:]*(\d[\d,]*)",
        # Item 9 bare
        r"Item\s*9[\s.:]+(\d[\d,]{2,})",
        # Generic
        r"Amount\s+(?:Beneficially\s+)?Owned[\s.:]*(\d[\d,]+)",
        # Fallback: SHARED VOTING/DISPOSITIVE (sole can be 0)
        r"SHARED\s+(?:VOTING|DISPOSITIVE)\s+POWER[\s.:]*(\d[\d,]+)",
        # Last resort: SOLE VOTING
        r"SOLE\s+VOTING\s+POWER[\s.:]*(\d[\d,]+)",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
                if val == 0 or val >= 100:  # QC: reject tiny values (row numbers)
                    return val
            except ValueError:
                pass
    return None


def download_filing(acc, subject_cik, filer_cik):
    """Download filing text from EDGAR. Tries subject_cik first."""
    acc_clean = acc.replace("-", "")
    for cik in [subject_cik, filer_cik]:
        if not cik:
            continue
        cik_raw = str(cik).lstrip("0") or "0"
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{cik_raw}/{acc_clean}/{acc}.txt")
        _rate_wait()
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", "-m", "12", "--connect-timeout", "5",
                 "-H", f"User-Agent: {SEC_UA}", url],
                capture_output=True, text=True, timeout=18, check=False,
            )
            if result.returncode == 0 and len(result.stdout) > 200:
                return result.stdout
        except subprocess.TimeoutExpired:
            pass
    return None


CHECKPOINT_INTERVAL = 500


def main(apply=False):
    db_path = get_db_path()
    con = duckdb.connect(db_path)

    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (10 samples)' if not apply else 'APPLY'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Scope: 13D filings with null shares OR null pct
    filings = con.execute("""
        SELECT b.accession_number, b.filer_cik, l.subject_cik,
               b.shares_owned IS NULL as need_shares,
               b.pct_owned IS NULL as need_pct
        FROM beneficial_ownership b
        JOIN listed_filings_13dg l ON b.accession_number = l.accession_number
        WHERE b.filing_type LIKE 'SC 13D%'
          AND (b.shares_owned IS NULL OR b.pct_owned IS NULL)
    """).fetchall()

    total = len(filings)
    print(f"Filings to process: {total:,}")

    if total == 0:
        print("Nothing to re-parse — all 13D filings already have shares + pct.")
        con.close()
        return

    if not apply:
        filings = filings[:10]
        print("  (dry-run: processing 10 samples)")

    stats = {"pct_fixed": 0, "shares_fixed": 0, "both_fixed": 0,
             "download_failed": 0, "no_match": 0}
    t0 = time.time()

    for i, (acc, filer_cik, subject_cik, need_shares, need_pct) in enumerate(filings):
        raw = download_filing(acc, subject_cik, filer_cik)
        if not raw:
            stats["download_failed"] += 1
            if apply and (i + 1) % CHECKPOINT_INTERVAL == 0:
                con.execute("CHECKPOINT")
            continue

        text = clean_text(raw)

        pct = extract_pct_owned(text) if need_pct else None
        shares = extract_shares_owned(text) if need_shares else None

        if pct or shares:
            if apply:
                if pct and shares:
                    con.execute("""UPDATE beneficial_ownership
                        SET pct_owned = ?, shares_owned = ?
                        WHERE accession_number = ? AND pct_owned IS NULL""",
                        [pct, shares, acc])
                    stats["both_fixed"] += 1
                elif pct:
                    con.execute("""UPDATE beneficial_ownership
                        SET pct_owned = ?
                        WHERE accession_number = ? AND pct_owned IS NULL""",
                        [pct, acc])
                    stats["pct_fixed"] += 1
                elif shares:
                    con.execute("""UPDATE beneficial_ownership
                        SET shares_owned = ?
                        WHERE accession_number = ? AND shares_owned IS NULL""",
                        [shares, acc])
                    stats["shares_fixed"] += 1
            else:
                label = []
                if pct:
                    label.append(f"pct={pct:.2f}%")
                if shares:
                    label.append(f"shares={shares:,}")
                print(f"  {acc}  {', '.join(label)}")
                if pct:
                    stats["pct_fixed"] += 1
                if shares:
                    stats["shares_fixed"] += 1
        else:
            stats["no_match"] += 1

        # Checkpoint
        if apply and (i + 1) % CHECKPOINT_INTERVAL == 0:
            con.execute("CHECKPOINT")

        # Progress
        if (i + 1) % 500 == 0 or (i + 1) == len(filings):
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = len(filings) - i - 1
            eta = remaining / rate if rate > 0 else 0
            total_fixed = stats["pct_fixed"] + stats["both_fixed"]
            print(f"  [{i+1:,}/{len(filings):,}] "
                  f"pct={total_fixed:,} shares={stats['shares_fixed']+stats['both_fixed']:,} "
                  f"fail={stats['no_match']} dl_err={stats['download_failed']} "
                  f"({rate:.1f}/s, ETA {eta/60:.0f}m)")

    if apply:
        con.execute("CHECKPOINT")

    elapsed = time.time() - t0
    pct_total = stats["pct_fixed"] + stats["both_fixed"]
    shares_total = stats["shares_fixed"] + stats["both_fixed"]
    print(f"\nProcessing complete: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  pct_owned fixed:    {pct_total:,}")
    print(f"  shares_owned fixed: {shares_total:,}")
    print(f"  No match:           {stats['no_match']:,}")
    print(f"  Download failed:    {stats['download_failed']:,}")

    if not apply:
        print("\nRun with --apply to update database.")
        con.close()
        return

    # Audit
    still_null = con.execute("""
        SELECT SUM(CASE WHEN pct_owned IS NULL THEN 1 ELSE 0 END) as null_pct,
               SUM(CASE WHEN shares_owned IS NULL THEN 1 ELSE 0 END) as null_shares,
               COUNT(*) as total
        FROM beneficial_ownership WHERE filing_type LIKE 'SC 13D%'
    """).fetchone()
    total_13d = still_null[2]
    print("\n--- POST-FIX 13D STATUS ---")
    print(f"  Total 13D rows:       {total_13d:,}")
    print(f"  pct_owned still null: {still_null[0]:,} ({100*still_null[0]/total_13d:.1f}%)")
    print(f"  shares_owned null:    {still_null[1]:,} ({100*still_null[1]/total_13d:.1f}%)")

    unresolved_pct = 100 * still_null[0] / total_13d
    if unresolved_pct > 50:
        print(f"\n  WARNING: {unresolved_pct:.0f}% pct_owned still null — "
              f"may need additional patterns")

    con.execute("CHECKPOINT")
    con.close()
    print(f"\nDone: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Re-parse SC 13D filings for shares_owned + pct_owned")
    parser.add_argument("--apply", action="store_true",
                        help="Apply fixes (default is 10-sample dry run)")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("reparse_13d")(
        lambda: main(apply=args.apply)
    )
