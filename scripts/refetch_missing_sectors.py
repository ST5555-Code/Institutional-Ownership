"""
Re-fetch sector/industry for tickers missing sector.

Reads a ticker list (default `/tmp/refetch_tickers.txt`, override via
`--ticker-file PATH`), fetches sector+industry via `scripts/yahoo_client.py`
(direct Yahoo JSON API), writes results back to the active write DB.

Safe to re-run — only updates rows where sector is still NULL. Combined with
`--resume`, supports long-running background sweeps (BLOCK-SECTOR-COVERAGE
workstream): progress is persisted per ticker to a JSON file and previously
processed tickers are skipped on restart.

NOTE: This script is largely subsumed by `fetch_market.py --staging
--metadata-only`, which handles the same use case end-to-end with the full
incremental update protocol. Kept for targeted manual fixes from an explicit
ticker list, and for the BLOCK-SECTOR-COVERAGE background workstream.

Usage:
    python3 scripts/refetch_missing_sectors.py
    python3 scripts/refetch_missing_sectors.py --staging \\
        --ticker-file logs/sector_coverage_tickers_<date>.txt --resume
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import duckdb  # noqa: E402

import db  # noqa: E402
from yahoo_client import YahooClient  # noqa: E402

DEFAULT_TICKER_FILE = '/tmp/refetch_tickers.txt'  # nosec B108 — legacy default; override with --ticker-file
DEFAULT_PROGRESS_FILE = 'logs/sector_coverage_progress.json'

# Rate-limit detection thresholds.
#
# Three-state heuristic, tuned after the 2026-04-18 1B2 false-positive: the
# alphabetically-sorted NULL-sector ticker list starts with a long tail of
# foreign/structured-instrument codes (07WA, 0E41, 0HQK, 1B2, ...) that Yahoo
# genuinely cannot resolve. A flat 5-consecutive-None threshold trips cooldown
# on these head-of-list junk tickers even though nothing is throttled.
#
#   1. Before the first successful sector resolution, tolerate a long run of
#      Nones — they are head-of-list data quality, not throttle.
#   2. After the first success, Yahoo is proven reachable; a shorter streak of
#      Nones is a more credible throttle signal, but still loosened from the
#      original 5 to reduce cooldown trips on natural clusters of unresolvable
#      codes mid-list.
#   3. Regardless of state, 200 consecutive Nones is a hard-stop — at that
#      point either Yahoo is rate-limiting us out or the run is broken; keep
#      sleeping is not useful. Abort so a human can investigate.
#
# Cooldown schedule and 5-retry per-ticker cap are unchanged.
THROTTLE_TRIGGER_BEFORE_FIRST_SUCCESS = 100
THROTTLE_TRIGGER_AFTER_FIRST_SUCCESS  = 15
CONSECUTIVE_FAILURE_ABORT             = 200
THROTTLE_INITIAL_SLEEP = 60   # seconds for first cooldown
THROTTLE_MAX_SLEEP     = 600  # cap per cooldown step
THROTTLE_MAX_RETRIES   = 5    # cooldown attempts on the stuck ticker

FLUSH_EVERY = 25  # progress + log cadence


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load_progress(path):
    """Return (entries, processed_ticker_set). Missing or empty file -> ([], set())."""
    if not os.path.exists(path):
        return [], set()
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Progress file {path} exists but is unreadable: {e}") from e
    entries = data.get('entries', []) if isinstance(data, dict) else data
    processed = {e.get('ticker') for e in entries if e.get('ticker')}
    return entries, processed


def write_progress_atomic(path, entries):
    """Atomic write — write to .tmp, then rename."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'entries': entries}, f, indent=0)
    os.rename(tmp, path)


def cooldown_retry(client, ticker, progress_entries, resolved_count):
    """Progressive backoff retry for a single ticker. Logs each attempt.

    Returns (sector, industry) or None if all retries exhausted.
    `resolved_count` is recorded in each progress entry so a post-hoc review
    can tell whether cooldown fired before/after the first real success —
    the heuristic's primary failure mode.
    """
    sleep_s = THROTTLE_INITIAL_SLEEP
    for attempt in range(1, THROTTLE_MAX_RETRIES + 1):
        progress_entries.append({
            'processed_at': now_iso(),
            'ticker': ticker,
            'result': 'rate_limit',
            'cooldown_attempt': attempt,
            'sleep_s': sleep_s,
            'resolved_count_at_entry': resolved_count,
        })
        print(f"  [rate-limit] suspected throttle on {ticker}; sleeping {sleep_s}s "
              f"(attempt {attempt}/{THROTTLE_MAX_RETRIES}, resolved_count={resolved_count})",
              flush=True)
        time.sleep(sleep_s)
        m = client.fetch_metadata(ticker)
        if m is not None:
            return (m.get('sector') or None, m.get('industry') or None)
        sleep_s = min(sleep_s * 2, THROTTLE_MAX_SLEEP)
    return None


def parse_args():
    p = argparse.ArgumentParser(description="Refetch missing sector/industry from Yahoo")
    p.add_argument("--staging", action="store_true",
                   help="Write to staging DB instead of production")
    p.add_argument("--ticker-file", default=DEFAULT_TICKER_FILE,
                   help=f"Path to ticker list (one per line). Default: {DEFAULT_TICKER_FILE}")
    p.add_argument("--resume", action="store_true",
                   help=f"Skip tickers already present in {DEFAULT_PROGRESS_FILE}")
    p.add_argument("--progress-file", default=DEFAULT_PROGRESS_FILE,
                   help="Override progress file path")
    return p.parse_args()


def main():
    args = parse_args()
    if args.staging:
        db.set_staging_mode(True)

    db_path = db.get_db_path()
    print("=" * 60)
    print("refetch_missing_sectors.py")
    print(f"  staging       = {db.is_staging_mode()}")
    print(f"  db_path       = {db_path}")
    print(f"  ticker_file   = {args.ticker_file}")
    print(f"  progress_file = {args.progress_file}")
    print(f"  resume        = {args.resume}")
    print("=" * 60)

    if not os.path.exists(args.ticker_file):
        print(f"ERROR: ticker file not found: {args.ticker_file}", file=sys.stderr)
        sys.exit(1)

    with open(args.ticker_file) as f:
        all_tickers = [line.strip() for line in f if line.strip()]
    print(f"Loaded {len(all_tickers)} tickers from {args.ticker_file}")

    progress_entries, processed = ([], set())
    if args.resume:
        progress_entries, processed = load_progress(args.progress_file)
        print(f"Resume: {len(processed)} tickers already processed; "
              f"{len(all_tickers) - len(processed)} pending")

    pending = [t for t in all_tickers if t not in processed]
    if not pending:
        print("Nothing to do.")
        return

    client = YahooClient()
    con = duckdb.connect(db_path, read_only=False)
    fixed = 0
    still_null = 0
    errors = 0
    consecutive_failures = 0
    resolved_count = 0
    aborted = False

    try:
        for i, tk in enumerate(pending, 1):
            try:
                m = client.fetch_metadata(tk)
            except Exception as e:  # noqa: BLE001 — never let a single ticker kill the run
                m = None
                print(f"  [error] {tk}: {e}", flush=True)

            if m is None:
                consecutive_failures += 1

                # Hard cap — regardless of state, this many in a row means
                # something is systemically wrong. Don't keep sleeping.
                if consecutive_failures >= CONSECUTIVE_FAILURE_ABORT:
                    msg = (f"ABORT: {CONSECUTIVE_FAILURE_ABORT} consecutive failures "
                           f"— likely genuine throttle or systemic issue, not data "
                           f"quality. Re-launch with --resume after investigation.")
                    print(msg, flush=True)
                    progress_entries.append({
                        'processed_at': now_iso(),
                        'ticker': tk,
                        'result': 'abort',
                        'consecutive_failures': consecutive_failures,
                        'resolved_count_at_abort': resolved_count,
                    })
                    aborted = True
                    break

                # Success-gated cooldown trigger. Before the first resolution
                # we tolerate a long run of Nones (head-of-list junk). After,
                # a much shorter streak is a more credible throttle signal.
                trigger = (THROTTLE_TRIGGER_BEFORE_FIRST_SUCCESS
                           if resolved_count == 0
                           else THROTTLE_TRIGGER_AFTER_FIRST_SUCCESS)

                if consecutive_failures >= trigger:
                    recovered = cooldown_retry(client, tk, progress_entries, resolved_count)
                    if recovered is None:
                        # All retries exhausted; mark error and reset counter
                        # so we don't immediately re-enter cooldown on the
                        # next genuinely-missing ticker.
                        result = 'error'
                        sector, industry = (None, None)
                        errors += 1
                        consecutive_failures = 0
                    else:
                        sector, industry = recovered
                        result = 'populated' if sector else 'still_null'
                        if sector:
                            fixed += 1
                            resolved_count += 1
                        else:
                            still_null += 1
                        consecutive_failures = 0
                else:
                    sector, industry = (None, None)
                    result = 'still_null'
                    still_null += 1
            else:
                consecutive_failures = 0
                sector = m.get('sector') or None
                industry = m.get('industry') or None
                if sector:
                    result = 'populated'
                    fixed += 1
                    resolved_count += 1
                else:
                    result = 'still_null'
                    still_null += 1

            if sector:
                con.execute(
                    "UPDATE market_data SET sector = ?, industry = ? "
                    "WHERE ticker = ? AND sector IS NULL",
                    [sector, industry, tk]
                )

            progress_entries.append({
                'processed_at': now_iso(),
                'ticker': tk,
                'result': result,
            })

            if i % FLUSH_EVERY == 0 or i == len(pending):
                write_progress_atomic(args.progress_file, progress_entries)
                print(f"  {i}/{len(pending)}  populated={fixed} still_null={still_null} "
                      f"errors={errors}", flush=True)
    finally:
        # Always flush + close, even on KeyboardInterrupt or unexpected exit.
        write_progress_atomic(args.progress_file, progress_entries)
        con.close()

    print(f"\nDone. populated={fixed}  still_null={still_null}  errors={errors}")
    if aborted:
        sys.exit(2)


if __name__ == '__main__':
    main()
