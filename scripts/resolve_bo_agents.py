#!/usr/bin/env python3
"""
resolve_bo_agents.py — Fix filing agent names in beneficial_ownership.

Resolves rows where filer_name is a filing agent (Toppan Merrill/FA,
Unknown (filing agent), etc.) to the actual beneficial owner.

Two-source strategy with automatic failover:
  1. EFTS search-index API (efts.sec.gov) — fast, separate rate limits
  2. SEC .hdr.sgml header download (www.sec.gov) — reliable fallback

Restart-safe: resolved rows are UPDATEd immediately. The WHERE clause
filters on filer_name IN (agent names), so resolved rows are automatically
skipped on restart. CHECKPOINT every 500 rows flushes to disk.

Usage:
    python3 scripts/resolve_bo_agents.py              # dry-run (10 samples)
    python3 scripts/resolve_bo_agents.py --apply      # resolve all
"""

import argparse
import functools
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime

# Intentional shadow: force flush=True so background-run logs appear
# in real time. See feedback_buffered_output. Rename would require
# updating every print() call site in this script — do not refactor.
print = functools.partial(print, flush=True)  # pylint: disable=redefined-builtin

import duckdb

from db import get_db_path, set_staging_mode

SEC_UA = "serge.tismen@gmail.com"

AGENT_NAMES = [
    "Toppan Merrill/FA",
    "Unknown (filing agent)",
]

KNOWN_AGENT_CIKS = {
    "0001104659", "0001193125", "0001445546", "0001398344", "0001493152",
    "0001567619", "0001213900", "0001532155", "0001214659", "0001072613",
    "0000902664", "0001193805", "0001623632", "0000929638", "0001178913",
    "0000950170", "0001062993", "0001437749", "0001041062", "0001628280",
    "0001564590",
}

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
_EFTS_MIN_INTERVAL = 0.13   # ~7.7 req/s — EFTS is more lenient
_SEC_MIN_INTERVAL = 0.12    # ~8.3 req/s — SEC is stricter, but fine at this rate
_last_efts_time = 0.0
_last_sec_time = 0.0


def _wait_efts():
    global _last_efts_time
    now = time.monotonic()
    wait = _EFTS_MIN_INTERVAL - (now - _last_efts_time)
    if wait > 0:
        time.sleep(wait)
    _last_efts_time = time.monotonic()


def _wait_sec():
    global _last_sec_time
    now = time.monotonic()
    wait = _SEC_MIN_INTERVAL - (now - _last_sec_time)
    if wait > 0:
        time.sleep(wait)
    _last_sec_time = time.monotonic()


# ---------------------------------------------------------------------------
# Source 1: EFTS search-index API
# ---------------------------------------------------------------------------
def _fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def resolve_via_efts(acc, subject_cik):
    """EFTS search-index — returns (name, cik) or (None, None)."""
    _wait_efts()
    data = _fetch_json(f"https://efts.sec.gov/LATEST/search-index?q=%22{acc}%22")
    if not data:
        return None, None

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None, None

    src = hits[0]["_source"]
    ciks = src.get("ciks", [])
    names = src.get("display_names", [])
    subject_padded = str(subject_cik).zfill(10)

    for cik, display in zip(ciks, names):
        if cik == subject_padded or cik in KNOWN_AGENT_CIKS:
            continue
        clean = re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", display).strip()
        clean = re.sub(r"\s*\(\w+\)\s*$", "", clean).strip()
        if len(clean) > 3:
            return clean, cik

    return None, None


# ---------------------------------------------------------------------------
# Source 2: SEC .hdr.sgml header download
# ---------------------------------------------------------------------------
def resolve_via_header(acc, subject_cik, filer_cik):
    """.hdr.sgml header — returns (name, cik) or (None, None)."""
    acc_clean = acc.replace("-", "")
    for cik in [subject_cik, filer_cik]:
        if not cik:
            continue
        cik_raw = str(cik).lstrip("0") or "0"
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{cik_raw}/{acc_clean}/{acc}.hdr.sgml")
        _wait_sec()
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", "-m", "8", "--connect-timeout", "5",
                 "-H", f"User-Agent: {SEC_UA}", url],
                capture_output=True, text=True, timeout=12, check=False,
            )
            if result.returncode == 0 and "<FILED-BY>" in result.stdout:
                fb = re.search(
                    r"<FILED-BY>(.*?)(?:</FILED-BY>|</SEC-HEADER>|\Z)",
                    result.stdout, re.DOTALL)
                if fb:
                    nm = re.search(r"<CONFORMED-NAME>([^\n<]+)", fb.group(1))
                    ck = re.search(r"<CIK>(\d+)", fb.group(1))
                    if nm and ck:
                        name = nm.group(1).strip()
                        cik_val = ck.group(1).zfill(10)
                        if cik_val not in KNOWN_AGENT_CIKS:
                            return name, cik_val
        except subprocess.TimeoutExpired:
            pass
    return None, None


# ---------------------------------------------------------------------------
# Dual-source resolver with automatic failover
# ---------------------------------------------------------------------------
# Consecutive failure counters — switch source after FAILOVER_THRESHOLD
FAILOVER_THRESHOLD = 10


def resolve_one(acc, filer_cik, subject_cik, source_state):
    """Try primary source, failover to secondary after consecutive failures.

    source_state is a mutable dict:
      primary: "efts" or "sec"
      efts_fails: consecutive EFTS failure count
      sec_fails:  consecutive SEC failure count
    """
    primary = source_state["primary"]

    # Try primary
    if primary == "efts":
        name, cik = resolve_via_efts(acc, subject_cik)
        if name and cik:
            source_state["efts_fails"] = 0
            return name, cik, "efts"
        source_state["efts_fails"] += 1
        # Failover?
        if source_state["efts_fails"] >= FAILOVER_THRESHOLD:
            print(f"    EFTS: {FAILOVER_THRESHOLD} consecutive failures — "
                  f"switching primary to SEC .hdr.sgml")
            source_state["primary"] = "sec"
            source_state["efts_fails"] = 0
    else:
        name, cik = resolve_via_header(acc, subject_cik, filer_cik)
        if name and cik:
            source_state["sec_fails"] = 0
            return name, cik, "sec"
        source_state["sec_fails"] += 1
        if source_state["sec_fails"] >= FAILOVER_THRESHOLD:
            print(f"    SEC: {FAILOVER_THRESHOLD} consecutive failures — "
                  f"switching primary to EFTS")
            source_state["primary"] = "efts"
            source_state["sec_fails"] = 0

    # Try secondary
    if primary == "efts":
        name, cik = resolve_via_header(acc, subject_cik, filer_cik)
        if name and cik:
            source_state["sec_fails"] = 0
            return name, cik, "sec"
        source_state["sec_fails"] += 1
    else:
        name, cik = resolve_via_efts(acc, subject_cik)
        if name and cik:
            source_state["efts_fails"] = 0
            return name, cik, "efts"
        source_state["efts_fails"] += 1

    return None, None, "failed"


# ---------------------------------------------------------------------------
# beneficial_ownership_current rebuild
# ---------------------------------------------------------------------------
REBUILD_CURRENT_SQL = """\
CREATE TABLE beneficial_ownership_current AS
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
"""

CHECKPOINT_INTERVAL = 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(apply=False):
    db_path = get_db_path()
    con = duckdb.connect(db_path)

    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (10 samples)' if not apply else 'APPLY'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    agent_names_sql = ", ".join(f"'{n}'" for n in AGENT_NAMES)
    filings = con.execute(f"""
        SELECT b.accession_number, b.filer_cik, l.subject_cik
        FROM beneficial_ownership b
        JOIN listed_filings_13dg l ON b.accession_number = l.accession_number
        WHERE b.filer_name IN ({agent_names_sql})
    """).fetchall()

    total = len(filings)
    print(f"Filings to process: {total:,}")

    if total == 0:
        print("Nothing to resolve — all filing agent names already fixed.")
        con.close()
        return

    if not apply:
        filings = filings[:10]
        print("  (dry-run: processing 10 samples)")

    # Source failover state
    source_state = {"primary": "efts", "efts_fails": 0, "sec_fails": 0}
    stats = {"efts": 0, "sec": 0, "failed": 0}
    t0 = time.time()

    for i, (acc, filer_cik, subject_cik) in enumerate(filings):
        name, cik, method = resolve_one(acc, filer_cik, subject_cik, source_state)

        if method in ("efts", "sec"):
            stats[method] += 1
            if apply:
                con.execute("""
                    UPDATE beneficial_ownership
                    SET filer_name = ?, filer_cik = ?, name_resolved = TRUE
                    WHERE accession_number = ?
                """, [name, cik, acc])
        else:
            stats["failed"] += 1

        # Checkpoint: flush to disk periodically
        if apply and (i + 1) % CHECKPOINT_INTERVAL == 0:
            con.execute("CHECKPOINT")

        # Progress
        if (i + 1) % 500 == 0 or (i + 1) == len(filings):
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = len(filings) - i - 1
            eta = remaining / rate if rate > 0 else 0
            resolved_so_far = stats["efts"] + stats["sec"]
            print(f"  [{i+1:,}/{len(filings):,}] "
                  f"{resolved_so_far:,} resolved "
                  f"(efts:{stats['efts']}, sec:{stats['sec']}), "
                  f"{stats['failed']} failed "
                  f"({rate:.1f}/s, ETA {eta/60:.0f}m)")

    # Final checkpoint
    if apply:
        con.execute("CHECKPOINT")

    elapsed = time.time() - t0
    resolved_total = stats["efts"] + stats["sec"]
    print(f"\nProcessing complete: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  Resolved: {resolved_total:,} "
          f"(efts:{stats['efts']}, sec:{stats['sec']})")
    print(f"  Failed:   {stats['failed']:,}")

    if not apply:
        print("\nRun with --apply to update database.")
        con.close()
        return

    # --- Post-processing ---

    # Audit unresolved
    still_agent = con.execute(f"""
        SELECT filer_name, COUNT(*) FROM beneficial_ownership
        WHERE filer_name IN ({agent_names_sql})
        GROUP BY filer_name ORDER BY COUNT(*) DESC
    """).fetchall()

    if still_agent:
        unresolved_count = sum(cnt for _, cnt in still_agent)
        total_rows = con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
        pct = 100 * unresolved_count / total_rows
        print(f"\n  WARNING: {unresolved_count:,} rows still unresolved ({pct:.1f}%)")
        for name, cnt in still_agent:
            print(f"    '{name}': {cnt:,}")
        if pct > 5.0:
            print("\n  ERROR: >5% unresolved — investigate before proceeding.")
            con.close()
            return

    # Rebuild beneficial_ownership_current
    print("\nRebuilding beneficial_ownership_current...")
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute(REBUILD_CURRENT_SQL)
    cur = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership_current").fetchone()[0]
    print(f"  beneficial_ownership_current: {cur:,} rows")

    # Final audit
    total_rows = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    resolved_db = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership WHERE name_resolved = TRUE"
    ).fetchone()[0]

    print("\n--- FINAL STATUS ---")
    print(f"  Total rows:     {total_rows:,}")
    print(f"  Resolved names: {resolved_db:,} ({100*resolved_db/total_rows:.1f}%)")
    if not still_agent:
        print("  Filing agents:  0 (all resolved)")

    con.execute("CHECKPOINT")
    con.close()
    print(f"\nDone: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Resolve filing agent names in beneficial_ownership")
    parser.add_argument("--apply", action="store_true",
                        help="Apply fixes (default is 10-sample dry run)")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("resolve_bo_agents")(
        lambda: main(apply=args.apply)
    )
