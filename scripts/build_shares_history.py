#!/usr/bin/env python3
"""
build_shares_history.py — Populate `shares_outstanding_history` table from SEC XBRL.

For every ticker with a CIK mapping, pulls ALL historical
EntityCommonStockSharesOutstanding / CommonStockSharesOutstanding facts from
the local SEC companyfacts cache (refresh via fetch_market.py --sec-only).

The resulting table is the canonical period-accurate share-count source.
Consumers matching a holding's `report_date` to the most recent XBRL fact
on-or-before that date (e.g. via DuckDB ASOF JOIN) get a denominator that
respects splits, buybacks, and offerings between report_date and today.

Writer discipline note: this script is the sole writer of
`shares_outstanding_history`. The historical `update_holdings_pct_of_float`
path that wrote `holdings.pct_of_float` via ASOF JOIN was retired in the
2026-04-19 rewrite after the `holdings` table was dropped at Stage 5.
Period-accurate denominator restoration landed under
BLOCK-PCT-OF-SO-PERIOD-ACCURACY (2026-04-19 — ASOF moved into
`enrich_holdings.py` Pass B, column renamed `pct_of_float` → `pct_of_so`
via migration 008).

Usage:
    python3 scripts/build_shares_history.py [--staging] [--dry-run]

Flags:
    --staging            Write to staging DB instead of production
    --dry-run            Project what would be written; no DB mutations
"""

import argparse
import os
import sys
import time
# from datetime import datetime  # unused

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import set_staging_mode, is_staging_mode, get_db_path, connect_read, record_freshness  # noqa: E402
from sec_shares_client import SECSharesClient  # noqa: E402


# Warn threshold: fraction of CIK-resolved tickers that yield no XBRL history.
# Above this, the summary prints a WARN banner — indicates systemic cache or
# parser problems. Does not raise; the build still completes so partial
# coverage is preserved.
UNRESOLVED_WARN_THRESHOLD = 0.20


SCHEMA = """
CREATE TABLE IF NOT EXISTS shares_outstanding_history (
    ticker      VARCHAR NOT NULL,
    cik         VARCHAR,
    as_of_date  DATE NOT NULL,
    shares      BIGINT NOT NULL,
    form        VARCHAR,
    filed_date  DATE,
    source_tag  VARCHAR,
    PRIMARY KEY (ticker, as_of_date)
)
"""


def build(con, client: SECSharesClient, dry_run: bool = False):
    # Source of tickers: everything in market_data that has either a CIK (SEC
    # resolved) or could potentially resolve. Read from prod in staging mode
    # so market_data stays the source of truth.
    read_con = connect_read() if is_staging_mode() else con
    tickers = read_con.execute("""
        SELECT DISTINCT ticker FROM market_data
        WHERE (unfetchable IS NULL OR unfetchable = FALSE)
    """).fetchdf()["ticker"].tolist()
    print(f"  Candidate tickers: {len(tickers):,}", flush=True)

    if not dry_run:
        con.execute(SCHEMA)

    total_rows = 0
    with_history = 0
    no_cik = 0
    no_history_with_cik = 0
    fetch_errors = 0
    checkpoints = 0
    t0 = time.time()

    batch = []
    BATCH = 1000
    CHECKPOINT_EVERY_N_BATCHES = 10  # flush WAL every ~10K rows
    batches_since_checkpoint = 0

    for i, tkr in enumerate(tickers, 1):
        try:
            history = client.fetch_history(tkr)
        except Exception as e:  # pylint: disable=broad-except
            fetch_errors += 1
            print(f"    [fetch_error] {tkr}: {type(e).__name__}: {e}", flush=True)
            continue

        if not history:
            if client.get_cik(tkr) is None:
                no_cik += 1
            else:
                no_history_with_cik += 1
            continue

        with_history += 1
        for row in history:
            filed = row.get("filed")
            batch.append((
                row["ticker"],
                row.get("cik"),
                row["as_of_date"],
                row["shares"],
                row.get("form"),
                filed,
                row.get("source_tag"),
            ))
        total_rows += len(history)

        if len(batch) >= BATCH:
            if not dry_run:
                _upsert_batch(con, batch)
                batches_since_checkpoint += 1
                if batches_since_checkpoint >= CHECKPOINT_EVERY_N_BATCHES:
                    con.execute("CHECKPOINT")
                    checkpoints += 1
                    batches_since_checkpoint = 0
            batch.clear()

        if i % 500 == 0:
            print(f"    [{i:,}/{len(tickers):,}] with_history={with_history:,} "
                  f"total_rows={total_rows:,}", flush=True)

    if batch and not dry_run:
        _upsert_batch(con, batch)
        batches_since_checkpoint += 1

    dt = time.time() - t0
    print(f"\n  Built in {dt:.1f}s", flush=True)
    print(f"    tickers with history: {with_history:,}", flush=True)
    print(f"    tickers without CIK:  {no_cik:,}", flush=True)
    print(f"    tickers with CIK but no history: {no_history_with_cik:,}", flush=True)
    print(f"    fetch errors:         {fetch_errors:,}", flush=True)
    print(f"    total history rows:   {total_rows:,}", flush=True)

    # Unresolved-% gate: CIK-resolved tickers that yielded no XBRL history.
    with_cik = len(tickers) - no_cik
    if with_cik > 0:
        unresolved_pct = no_history_with_cik / with_cik
        if unresolved_pct > UNRESOLVED_WARN_THRESHOLD:
            print(f"\n  [WARN] unresolved rate {100*unresolved_pct:.1f}% exceeds "
                  f"{100*UNRESOLVED_WARN_THRESHOLD:.0f}% threshold — possible "
                  f"systemic cache or parser issue.", flush=True)

    if dry_run:
        print(f"\n  [DRY-RUN] would upsert {total_rows:,} rows across "
              f"{with_history:,} tickers; no DB mutations performed.", flush=True)
    else:
        # Index + final CHECKPOINT
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_soh_ticker_date
            ON shares_outstanding_history(ticker, as_of_date)
        """)
        con.execute("CHECKPOINT")
        checkpoints += 1
        print(f"    CHECKPOINTs executed: {checkpoints}", flush=True)

    if is_staging_mode() and read_con is not con:
        read_con.close()


def _upsert_batch(con, batch):
    """INSERT OR REPLACE batch of rows via executemany."""
    con.executemany("""
        INSERT INTO shares_outstanding_history
            (ticker, cik, as_of_date, shares, form, filed_date, source_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (ticker, as_of_date) DO UPDATE SET
            cik        = excluded.cik,
            shares     = excluded.shares,
            form       = excluded.form,
            filed_date = excluded.filed_date,
            source_tag = excluded.source_tag
    """, batch)


def main():
    parser = argparse.ArgumentParser(description="Build shares_outstanding_history from SEC XBRL")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB instead of production")
    parser.add_argument("--dry-run", action="store_true",
                        help="Project what would be written; no DB mutations")
    args = parser.parse_args()

    if args.staging:
        set_staging_mode(True)

    print("=" * 60)
    print("build_shares_history.py — SEC XBRL period-accurate shares")
    print(f"  staging={is_staging_mode()}  dry_run={args.dry_run}")
    print("=" * 60)

    con = duckdb.connect(get_db_path(), read_only=args.dry_run)
    client = SECSharesClient()
    build(con, client, dry_run=args.dry_run)

    if not args.dry_run:
        try:
            record_freshness(con, "shares_outstanding_history")
        except Exception as e:  # pylint: disable=broad-except
            print(f"  [warn] record_freshness(shares_outstanding_history) failed: {e}",
                  flush=True)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
