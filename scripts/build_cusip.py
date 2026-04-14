#!/usr/bin/env python3
"""
build_cusip.py — v2 securities builder backed by the classification layer.

Reads cusip_classifications (the primary classification target populated by
scripts/build_classifications.py) and runs OpenFIGI v3 against the
cusip_retry_queue to resolve tickers for equity CUSIPs. UPSERTs results
into both ``_cache_openfigi`` and ``securities`` — never DROP + CREATE.

Scope (Plan v1.4 Session 1):
  - Initial OpenFIGI call path is implemented but stubbed: Session 1 keeps
    Task 3 / Task 4 as the authoritative rule-based run and defers the
    real API retry to Session 2. Session 2 calls ``openfigi_retry`` at
    full rate against cusip_retry_queue.
  - ``update_securities_from_classifications`` ports classification flags
    (canonical_type, is_equity, is_priceable, ticker_expected, figi)
    into the securities table via UPSERT.
  - ``handle_unfetchable`` marks a ticker is_priceable=FALSE in
    cusip_classifications; unknown tickers are logged to
    logs/unfetchable_orphans.csv for review.

Legacy script preserved at scripts/retired/build_cusip_legacy.py for
reference.

MANUAL TICKER OVERRIDES
-----------------------
OpenFIGI sometimes returns foreign exchange codes. ``data/reference/
ticker_overrides.csv`` takes precedence over OpenFIGI results via
``scripts/build_classifications.py``'s manual override step — any CUSIP
listed there gets the correct ticker + canonical_type applied last,
with source='manual' / confidence='exact'.

Usage:
    python3 scripts/build_cusip.py                # prod
    python3 scripts/build_cusip.py --staging
    python3 scripts/build_cusip.py --dry-run      # no API calls, no writes
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from typing import Optional

import duckdb
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import set_staging_mode, get_db_path  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH_SIZE = 10           # v3 caps batches at 10 jobs per request
OPENFIGI_SLEEP_SECONDS = 2.4       # 25 req/min observed from live headers
OPENFIGI_MAX_RETRIES_PER_CUSIP = 3  # mirrors cusip_classifier.MAX_ATTEMPTS
LOG_DIR = os.path.join(BASE_DIR, "logs")
ORPHAN_LOG = os.path.join(LOG_DIR, "unfetchable_orphans.csv")


# ---------------------------------------------------------------------------
# OpenFIGI cache — _cache_openfigi stores the full v3 response columns
# ---------------------------------------------------------------------------

def save_figi_cache(
    con,
    cusip: str,
    figi: Optional[str],
    ticker: Optional[str],
    exchange: Optional[str],
    security_type: Optional[str],
    market_sector: Optional[str],
) -> None:
    """Persist one OpenFIGI response row. Upsert on CUSIP."""
    con.execute(
        """
        INSERT INTO _cache_openfigi
            (cusip, figi, ticker, exchange, security_type, market_sector, cached_at)
        VALUES (?, ?, ?, ?, ?, ?, NOW())
        ON CONFLICT (cusip) DO UPDATE SET
            figi          = excluded.figi,
            ticker        = excluded.ticker,
            exchange      = excluded.exchange,
            security_type = excluded.security_type,
            market_sector = excluded.market_sector,
            cached_at     = NOW()
        """,
        [cusip, figi, ticker, exchange, security_type, market_sector],
    )


def load_figi_cache(con, cusips: list[str]) -> dict[str, dict]:
    """Return cached rows for the given CUSIPs, keyed by CUSIP."""
    if not cusips:
        return {}
    rows = con.execute(
        "SELECT cusip, figi, ticker, exchange, security_type, market_sector "
        "FROM _cache_openfigi WHERE cusip IN (SELECT UNNEST(?))",
        [cusips],
    ).fetchall()
    return {
        r[0]: {
            "figi": r[1],
            "ticker": r[2],
            "exchange": r[3],
            "security_type": r[4],
            "market_sector": r[5],
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# OpenFIGI API — v3
# ---------------------------------------------------------------------------

def _post_batch(cusips: list[str], batch_num: int = 0) -> list[dict]:
    """POST one batch of ≤10 CUSIPs to OpenFIGI v3. Returns raw response
    list (one element per CUSIP, preserving order). Handles 429 backoff.
    """
    jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        if r.status_code == 429:
            print(f"    Rate limited at batch {batch_num}; sleeping 60s", flush=True)
            time.sleep(60)
            r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"    OpenFIGI error at batch {batch_num}: {exc}", flush=True)
        return []


def openfigi_retry(con_write, limit: Optional[int] = None) -> dict:
    """Drain cusip_retry_queue against OpenFIGI v3, upserting results.

    Selects rows where ``status='pending'`` AND ``attempt_count``
    < OPENFIGI_MAX_RETRIES_PER_CUSIP. For each batch:
      1. Call OpenFIGI v3.
      2. On a match (``result.data`` non-empty): upsert _cache_openfigi,
         update cusip_classifications (ticker, figi, exchange, market_sector,
         openfigi_attempts+1, openfigi_status='success'), mark
         retry_queue row status='resolved'.
      3. On a warning-only response (v3 'no match'): update
         cusip_classifications (openfigi_attempts+1, openfigi_status='no_result'),
         bump retry_queue.attempt_count; mark 'unmappable' if the attempt
         limit is hit.
      4. On a hard error: bump attempt_count + last_error; leave status='pending'.

    Returns a summary dict.
    """
    pending = con_write.execute(
        """
        SELECT cusip
        FROM cusip_retry_queue
        WHERE status = 'pending'
          AND attempt_count < ?
        ORDER BY last_attempted NULLS FIRST, cusip
        """,
        [OPENFIGI_MAX_RETRIES_PER_CUSIP],
    ).fetchdf()['cusip'].tolist()

    if limit:
        pending = pending[:limit]

    if not pending:
        print("  openfigi_retry: queue is empty")
        return {'attempted': 0, 'resolved': 0, 'no_match': 0, 'errors': 0}

    print(f"  openfigi_retry: {len(pending):,} CUSIPs, "
          f"batch_size={OPENFIGI_BATCH_SIZE}, "
          f"sleep={OPENFIGI_SLEEP_SECONDS}s")

    resolved = no_match = errors = 0
    for batch_num, start in enumerate(range(0, len(pending), OPENFIGI_BATCH_SIZE)):
        batch = pending[start:start + OPENFIGI_BATCH_SIZE]
        results = _post_batch(batch, batch_num)

        if not results:
            errors += len(batch)
            for cusip in batch:
                con_write.execute(
                    """
                    UPDATE cusip_retry_queue
                    SET attempt_count = attempt_count + 1,
                        last_attempted = NOW(),
                        last_error = 'http_error',
                        updated_at = NOW()
                    WHERE cusip = ?
                    """,
                    [cusip],
                )
            time.sleep(OPENFIGI_SLEEP_SECONDS)
            continue

        for cusip, result in zip(batch, results):
            data = result.get("data") or []
            if data:
                item = data[0]
                ticker = item.get("ticker") or None
                figi = item.get("compositeFIGI") or item.get("figi")
                exchange = item.get("exchCode")
                security_type = item.get("securityType")
                market_sector = item.get("marketSector")

                save_figi_cache(con_write, cusip, figi, ticker,
                                exchange, security_type, market_sector)

                con_write.execute(
                    """
                    UPDATE cusip_classifications
                    SET ticker                = COALESCE(?, ticker),
                        figi                  = COALESCE(?, figi),
                        exchange              = COALESCE(?, exchange),
                        market_sector         = COALESCE(?, market_sector),
                        openfigi_attempts     = openfigi_attempts + 1,
                        last_openfigi_attempt = NOW(),
                        openfigi_status       = 'success',
                        ticker_source         = COALESCE(ticker_source, 'openfigi'),
                        updated_at            = NOW()
                    WHERE cusip = ?
                    """,
                    [ticker, figi, exchange, market_sector, cusip],
                )
                con_write.execute(
                    """
                    UPDATE cusip_retry_queue
                    SET status = 'resolved',
                        attempt_count = attempt_count + 1,
                        last_attempted = NOW(),
                        resolved_ticker = ?,
                        resolved_figi = ?,
                        updated_at = NOW()
                    WHERE cusip = ?
                    """,
                    [ticker, figi, cusip],
                )
                resolved += 1
            else:
                no_match += 1
                con_write.execute(
                    """
                    UPDATE cusip_classifications
                    SET openfigi_attempts     = openfigi_attempts + 1,
                        last_openfigi_attempt = NOW(),
                        openfigi_status       = 'no_result',
                        updated_at            = NOW()
                    WHERE cusip = ?
                    """,
                    [cusip],
                )
                con_write.execute(
                    """
                    UPDATE cusip_retry_queue
                    SET attempt_count = attempt_count + 1,
                        last_attempted = NOW(),
                        last_error = 'no_match',
                        status = CASE
                            WHEN attempt_count + 1 >= ? THEN 'unmappable'
                            ELSE 'pending'
                        END,
                        updated_at = NOW()
                    WHERE cusip = ?
                    """,
                    [OPENFIGI_MAX_RETRIES_PER_CUSIP, cusip],
                )
        time.sleep(OPENFIGI_SLEEP_SECONDS)

    print(f"  resolved={resolved:,} no_match={no_match:,} errors={errors:,}")
    return {
        'attempted': len(pending),
        'resolved': resolved,
        'no_match': no_match,
        'errors': errors,
    }


# ---------------------------------------------------------------------------
# securities — populate 7 new columns from cusip_classifications
# ---------------------------------------------------------------------------

SECURITIES_UPSERT_SQL = """
INSERT INTO securities (
    cusip, issuer_name, ticker, security_type, exchange, market_sector,
    canonical_type, canonical_type_source,
    is_equity, is_priceable, ticker_expected, is_active, figi
)
SELECT
    cc.cusip, cc.issuer_name, cc.ticker, cc.raw_type_mode, cc.exchange,
    cc.market_sector,
    cc.canonical_type, cc.canonical_type_source,
    cc.is_equity, cc.is_priceable, cc.ticker_expected, cc.is_active,
    cc.figi
FROM cusip_classifications cc
LEFT JOIN securities s ON cc.cusip = s.cusip
WHERE s.cusip IS NULL
"""

SECURITIES_UPDATE_SQL = """
UPDATE securities s
SET ticker                = COALESCE(cc.ticker, s.ticker),
    exchange              = COALESCE(cc.exchange, s.exchange),
    market_sector         = COALESCE(cc.market_sector, s.market_sector),
    canonical_type        = cc.canonical_type,
    canonical_type_source = cc.canonical_type_source,
    is_equity             = cc.is_equity,
    is_priceable          = cc.is_priceable,
    ticker_expected       = cc.ticker_expected,
    is_active             = cc.is_active,
    figi                  = COALESCE(cc.figi, s.figi)
FROM cusip_classifications cc
WHERE s.cusip = cc.cusip
"""


def update_securities_from_classifications(con_write) -> dict:
    """Port cusip_classifications → securities. UPDATE existing rows,
    INSERT rows for CUSIPs that exist in classifications but not in
    securities (13D/G-only CUSIPs fall in this bucket)."""
    before = con_write.execute("SELECT COUNT(*) FROM securities").fetchone()[0]
    con_write.execute("BEGIN")
    try:
        con_write.execute(SECURITIES_UPDATE_SQL)
        con_write.execute(SECURITIES_UPSERT_SQL)
        con_write.execute("COMMIT")
    except Exception:
        con_write.execute("ROLLBACK")
        raise
    after = con_write.execute("SELECT COUNT(*) FROM securities").fetchone()[0]
    print(f"  securities: {before:,} → {after:,} rows (+{after-before:,})")
    return {'before': before, 'after': after}


# ---------------------------------------------------------------------------
# handle_unfetchable — mark ticker not priceable, log orphan tickers
# ---------------------------------------------------------------------------

def handle_unfetchable(con_write, ticker: str, reason: str) -> None:
    """Mark a ticker is_priceable=FALSE in cusip_classifications.

    If no CUSIP row has this ticker, append to logs/unfetchable_orphans.csv
    for manual review — this happens when a ticker hasn't yet been resolved
    to a CUSIP by OpenFIGI.
    """
    hit = con_write.execute(
        "SELECT cusip FROM cusip_classifications WHERE ticker = ? LIMIT 1",
        [ticker],
    ).fetchone()

    if hit:
        con_write.execute(
            """
            UPDATE cusip_classifications
            SET is_priceable         = FALSE,
                last_priceable_check = NOW(),
                notes                = COALESCE(notes || ' | ', '') || ?,
                updated_at           = NOW()
            WHERE ticker = ?
            """,
            [reason, ticker],
        )
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(ORPHAN_LOG)
    with open(ORPHAN_LOG, 'a', newline='') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['ticker', 'reason', 'timestamp'])
        w.writerow([ticker, reason, datetime.utcnow().isoformat()])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="v2 securities builder")
    p.add_argument("--staging", action="store_true",
                   help="Write to staging DB")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip API calls and DB writes")
    p.add_argument("--limit", type=int, default=None,
                   help="Limit number of CUSIPs processed (testing)")
    p.add_argument("--skip-openfigi", action="store_true",
                   help="Skip OpenFIGI retry; only port classifications→securities")
    args = p.parse_args()

    if args.staging:
        set_staging_mode(True)

    write_db = get_db_path()
    print("build_cusip.py v2 — classification-backed securities builder")
    print("=" * 60)
    print(f"  write: {write_db}")
    print(f"  dry-run: {args.dry_run}")
    if args.dry_run:
        print("  [dry-run] no API calls, no writes — exiting")
        return

    con = duckdb.connect(write_db)
    try:
        # Guard: cusip_classifications must exist (Migration 003 applied)
        try:
            con.execute("SELECT 1 FROM cusip_classifications LIMIT 1")
        except Exception as exc:
            print(f"ERROR: cusip_classifications missing from {write_db}. "
                  f"Run Migration 003 first. ({exc})")
            return

        if not args.skip_openfigi:
            openfigi_retry(con, limit=args.limit)
        else:
            print("  --skip-openfigi: skipping retry step")

        update_securities_from_classifications(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    print("Done.")


if __name__ == "__main__":
    main()
