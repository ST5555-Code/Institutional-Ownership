#!/usr/bin/env python3
"""
run_openfigi_retry.py — drain cusip_retry_queue through OpenFIGI v3.

Processes ``cusip_retry_queue`` where ``status='pending'`` AND
``attempt_count < MAX_ATTEMPTS``. For each batch of 10 CUSIPs:
  1. POST to OpenFIGI v3.
  2. On match (``data`` list non-empty): upsert _cache_openfigi, update
     cusip_classifications (ticker, figi, exchange, market_sector,
     confidence='high', ticker_source='openfigi'), mark retry_queue
     status='resolved'.
  3. On no-match (empty ``data`` or ``warning`` key): bump attempt_count;
     mark 'unmappable' at the attempt limit.
  4. On HTTP error: bump attempt_count, leave status='pending', record error.

FOREIGN CUSIPs whose OpenFIGI exchange is US-priceable get flipped to
``is_priceable=TRUE, ticker_expected=TRUE`` inline — the initial
classification stamped them non-priceable pending exchange resolution.

Rate: 25 req/min × 10 jobs/req = 250 CUSIPs/min (confirmed live).
Resume-safe: all writes are idempotent (UPSERT / targeted UPDATE).

Usage:
    python3 scripts/run_openfigi_retry.py                # prod
    python3 scripts/run_openfigi_retry.py --staging
    python3 scripts/run_openfigi_retry.py --staging --limit 100
    python3 scripts/run_openfigi_retry.py --staging --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

import duckdb
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.cusip_classifier import MAX_ATTEMPTS, US_PRICEABLE_EXCHANGES  # noqa: E402


OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
BATCH_SIZE = 10
RATE_LIMIT_SLEEP = 2.4      # 60s / 25 req = 2.4s between requests
RETRY_SLEEP_429 = 62
PROGRESS_EVERY_BATCHES = 100  # print progress every 100 batches (~1,000 CUSIPs)

# OpenFIGI v3 composite exchCode for US-listed equities. The plan v1.4
# ``US_PRICEABLE_EXCHANGES`` set keeps fine-grained codes for the yfinance
# path; this wider set covers the composite returned by /v3/mapping
# when no exchange filter is applied.
_US_COMPOSITE_EXCHANGES = US_PRICEABLE_EXCHANGES | {'US'}


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    key = os.environ.get("OPENFIGI_API_KEY")
    if key:
        h["X-OPENFIGI-APIKEY"] = key
    return h


def _post_batch(cusips: list[str], batch_num: int) -> Optional[list[dict]]:
    """POST one batch. Return response list on success, None on hard failure."""
    jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
    headers = _headers()
    try:
        r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        if r.status_code == 429:
            print(f"    [batch {batch_num}] 429 rate limit — sleeping "
                  f"{RETRY_SLEEP_429}s", flush=True)
            time.sleep(RETRY_SLEEP_429)
            r = requests.post(OPENFIGI_URL, json=jobs, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"    [batch {batch_num}] error: {exc}", flush=True)
        return None


def _update_resolved(con, cusip: str, item: dict) -> None:
    """Write OpenFIGI result to cusip_classifications / _cache_openfigi /
    cusip_retry_queue. Flips FOREIGN → priceable when applicable."""
    figi = item.get('compositeFIGI') or item.get('figi')
    ticker = item.get('ticker') or None
    exchange = item.get('exchCode') or None
    market_sector = item.get('marketSector') or None
    security_type = item.get('securityType') or None

    # FOREIGN post-recheck — flip to priceable if OpenFIGI says US.
    row = con.execute(
        "SELECT canonical_type FROM cusip_classifications WHERE cusip = ?",
        [cusip],
    ).fetchone()
    is_foreign = row and row[0] == 'FOREIGN'
    priceable_patch = ""
    if is_foreign and exchange and exchange in _US_COMPOSITE_EXCHANGES:
        priceable_patch = (", is_priceable = TRUE, ticker_expected = TRUE")

    con.execute(
        f"""
        UPDATE cusip_classifications
        SET ticker                 = COALESCE(?, ticker),
            figi                   = COALESCE(?, figi),
            exchange               = COALESCE(?, exchange),
            market_sector          = COALESCE(?, market_sector),
            openfigi_status        = 'success',
            openfigi_attempts      = openfigi_attempts + 1,
            last_openfigi_attempt  = NOW(),
            ticker_source          = COALESCE(ticker_source, 'openfigi'),
            confidence             = 'high',
            updated_at             = NOW()
            {priceable_patch}
        WHERE cusip = ?
        """,
        [ticker, figi, exchange, market_sector, cusip],
    )

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

    con.execute(
        """
        UPDATE cusip_retry_queue
        SET status           = 'resolved',
            resolved_ticker  = ?,
            resolved_figi    = ?,
            attempt_count    = attempt_count + 1,
            last_attempted   = NOW(),
            updated_at       = NOW()
        WHERE cusip = ?
        """,
        [ticker, figi, cusip],
    )


def _update_no_match(con, cusip: str, reason: str) -> None:
    """Bump attempt count; mark unmappable at the attempt limit."""
    con.execute(
        """
        UPDATE cusip_classifications
        SET openfigi_status       = 'no_result',
            openfigi_attempts     = openfigi_attempts + 1,
            last_openfigi_attempt = NOW(),
            updated_at            = NOW()
        WHERE cusip = ?
        """,
        [cusip],
    )
    con.execute(
        """
        UPDATE cusip_retry_queue
        SET attempt_count  = attempt_count + 1,
            last_attempted = NOW(),
            last_error     = ?,
            status         = CASE
                WHEN attempt_count + 1 >= ? THEN 'unmappable'
                ELSE 'pending'
            END,
            updated_at     = NOW()
        WHERE cusip = ?
        """,
        [reason, MAX_ATTEMPTS, cusip],
    )


def _update_error(con, cusip: str, reason: str) -> None:
    """Hard HTTP error — bump attempts, leave status='pending'."""
    con.execute(
        """
        UPDATE cusip_classifications
        SET openfigi_status       = 'error',
            openfigi_attempts     = openfigi_attempts + 1,
            last_openfigi_attempt = NOW(),
            updated_at            = NOW()
        WHERE cusip = ?
        """,
        [cusip],
    )
    con.execute(
        """
        UPDATE cusip_retry_queue
        SET attempt_count  = attempt_count + 1,
            last_attempted = NOW(),
            last_error     = ?,
            updated_at     = NOW()
        WHERE cusip = ?
        """,
        [reason, cusip],
    )


def run_retry(con, limit: Optional[int] = None, dry_run: bool = False) -> dict:
    where_limit = f"LIMIT {int(limit)}" if limit else ""
    queue = con.execute(f"""
        SELECT cusip, issuer_name, canonical_type
        FROM cusip_retry_queue
        WHERE status = 'pending'
          AND attempt_count < {MAX_ATTEMPTS}
        ORDER BY attempt_count ASC, first_attempted ASC
        {where_limit}
    """).fetchdf()

    total = len(queue)
    print(f"Queue: {total:,} CUSIPs to process")
    if total == 0:
        return {'attempted': 0, 'resolved': 0, 'no_match': 0, 'errors': 0}

    est_min = total / 250.0
    print(f"Estimated time: {est_min:.1f} min ({est_min/60:.2f}h) "
          f"at 250 CUSIPs/min")

    if dry_run:
        print("DRY RUN — no API calls, no writes")
        print("First 10 rows:")
        print(queue.head(10).to_string())
        return {'attempted': 0, 'resolved': 0, 'no_match': 0, 'errors': 0}

    cusips = queue['cusip'].tolist()
    resolved = no_match = errors = 0
    t0 = time.time()

    for batch_num, start in enumerate(range(0, len(cusips), BATCH_SIZE), start=1):
        batch = cusips[start:start + BATCH_SIZE]
        response = _post_batch(batch, batch_num)

        if response is None:
            for cusip in batch:
                _update_error(con, cusip, 'http_error')
                errors += 1
            time.sleep(RATE_LIMIT_SLEEP)
            continue

        for cusip, result in zip(batch, response):
            if 'data' in result and result['data']:
                _update_resolved(con, cusip, result['data'][0])
                resolved += 1
            elif 'warning' in result:
                _update_no_match(con, cusip, 'no_result')
                no_match += 1
            elif 'error' in result:
                _update_error(con, cusip, str(result.get('error'))[:200])
                errors += 1
            else:
                # empty data list is also "no match" in v3
                _update_no_match(con, cusip, 'no_result')
                no_match += 1

        if batch_num % PROGRESS_EVERY_BATCHES == 0:
            done = batch_num * BATCH_SIZE
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate / 60 if rate else 0
            print(f"  [{done:>6,}/{total:,} = {done/total*100:4.1f}%] "
                  f"resolved={resolved:,} no_match={no_match:,} errors={errors:,} "
                  f"rate={rate:.0f}/s eta={eta:.1f}min", flush=True)
            # Periodic checkpoint so interrupted runs flush prior work.
            con.execute("CHECKPOINT")

        time.sleep(RATE_LIMIT_SLEEP)

    con.execute("CHECKPOINT")
    elapsed = time.time() - t0
    print(f"\nComplete: {len(cusips):,} processed in {elapsed/60:.1f} min")
    print(f"  resolved={resolved:,} no_match={no_match:,} errors={errors:,}")
    return {
        'attempted': len(cusips),
        'resolved': resolved,
        'no_match': no_match,
        'errors': errors,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="OpenFIGI retry for cusip_retry_queue")
    p.add_argument("--staging", action="store_true",
                   help="Write to staging DB (default: prod)")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only N CUSIPs then stop (resume on next run)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print queue sample; no API calls, no writes")
    args = p.parse_args()

    db = STAGING_DB if args.staging else PROD_DB
    print("run_openfigi_retry.py — Plan v1.4 Session 2")
    print("=" * 60)
    print(f"  DB: {db}")
    if args.limit:
        print(f"  limit: {args.limit}")
    if args.dry_run:
        print("  mode: DRY RUN")
    print()

    con = duckdb.connect(db)
    try:
        try:
            con.execute("SELECT 1 FROM cusip_retry_queue LIMIT 1")
        except Exception as exc:
            print(f"ERROR: cusip_retry_queue missing from {db}. "
                  f"Run Migration 003 + build_classifications.py first. ({exc})")
            sys.exit(1)

        summary = run_retry(con, limit=args.limit, dry_run=args.dry_run)
    finally:
        con.close()

    # Post-run status snapshot
    con = duckdb.connect(db, read_only=True)
    counts = con.execute(
        "SELECT status, COUNT(*) AS n FROM cusip_retry_queue "
        "GROUP BY status ORDER BY n DESC"
    ).fetchdf()
    con.close()
    print("\nRetry queue status:")
    print(counts.to_string(index=False))
    print(f"\nSummary: {summary}")


if __name__ == "__main__":
    main()
