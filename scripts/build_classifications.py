#!/usr/bin/env python3
"""
build_classifications.py — initial rule-based CUSIP classification.

Reads the 3-source CUSIP universe (securities / fund_holdings_v2 /
beneficial_ownership_v2), applies ``pipeline.cusip_classifier.classify_cusip``
to each row, UPSERTs into ``cusip_classifications``, and populates
``cusip_retry_queue`` for CUSIPs that need an OpenFIGI round-trip.

No OpenFIGI API calls. Session 2 runs the retry over cusip_retry_queue.

Read/write convention:
  - Read source data from PROD (13f.duckdb).  Staging DB does not hold
    holdings_v2 / fund_holdings_v2 / beneficial_ownership_v2.
  - Write cusip_classifications / cusip_retry_queue to the target DB
    (staging in --staging mode, else prod).

Usage:
    python3 scripts/build_classifications.py                 # prod
    python3 scripts/build_classifications.py --staging       # staging
    python3 scripts/build_classifications.py --staging --dry-run
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import date
from typing import Iterable

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.cusip_classifier import classify_cusip, get_cusip_universe  # noqa: E402


BATCH_SIZE = 1_000
PROGRESS_EVERY = 10_000
OVERRIDES_PATH = os.path.join(BASE_DIR, "data", "reference", "ticker_overrides.csv")
OVERRIDE_TRIAGE_PATH = os.path.join(BASE_DIR, "logs", "override_triage_queue.csv")

# RC3 triage — tokens stripped from both override.company_name and the
# system-believed issuer_name before comparing. Covers legal-form suffixes,
# share-class markers, and currency/ADR tags observed in the datasets.
_NAME_NOISE_TOKENS = frozenset({
    'INC', 'INCORPORATED', 'CORP', 'CORPORATION', 'CO', 'COMPANY',
    'LTD', 'LIMITED', 'LLC', 'LP', 'LLP', 'PLC', 'COM',
    'HOLDINGS', 'HLDGS', 'HOLDING', 'HLDG', 'GROUP', 'GRP',
    'TRUST', 'TR', 'FUND', 'PARTNERS', 'PARTNERSHIP',
    'ASSOCIATION', 'ASSOC', 'BANCORP',
    'NV', 'SA', 'SE', 'AG', 'SPA', 'AB', 'AS', 'OYJ', 'BV',
    'USD', 'EUR', 'GBP', 'CAD', 'JPY',
    'SHARES', 'SHS', 'CLASS', 'SPONSORED', 'ADR', 'ADS',
    'REIT', 'REITS',
    'THE', 'AND', '&',
    'A', 'B', 'C',
})


def _normalize_name(name: str) -> str:
    """Uppercase, strip punctuation, drop trailing legal-form suffixes.

    Used only for RC3 override triage comparisons. Not authoritative.
    """
    if not name:
        return ''
    s = re.sub(r'[^A-Z0-9 ]', ' ', name.upper())
    s = re.sub(r'\s+', ' ', s).strip()
    tokens = s.split()
    # Strip noise tokens from the tail AND head so "THE APPLE INC" matches
    # "APPLE", but preserve at least one token.
    while len(tokens) > 1 and tokens[-1] in _NAME_NOISE_TOKENS:
        tokens.pop()
    while len(tokens) > 1 and tokens[0] in _NAME_NOISE_TOKENS:
        tokens.pop(0)
    return ' '.join(tokens)


def _triage_severity(override_company: str, system_issuer: str) -> str:
    """Classify (override.company_name, system.issuer_name) similarity.

    Returns one of 'exact', 'fuzzy', 'none'. 'exact' rows are not logged to
    the triage queue — they confirm the override targets the right CUSIP.
    """
    a = _normalize_name(override_company)
    b = _normalize_name(system_issuer)
    if not a or not b:
        return 'none'
    if a == b:
        return 'exact'
    if a in b or b in a:
        return 'fuzzy'
    return 'none'


UPSERT_SQL = """
INSERT INTO cusip_classifications (
    cusip, canonical_type, canonical_type_source,
    raw_type_mode, raw_type_count,
    security_type_inferred, asset_category_seed, market_sector,
    issuer_name, ticker, figi, exchange, country_code,
    is_equity, ticker_expected, is_priceable, is_otc, is_permanent, is_active,
    classification_source, ticker_source, confidence,
    openfigi_attempts, last_openfigi_attempt, openfigi_status,
    last_priceable_check,
    first_seen_date, last_confirmed_date,
    inactive_since, inactive_reason,
    notes
) VALUES (
    ?, ?, ?,
    ?, ?,
    ?, ?, ?,
    ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?,
    ?, ?, ?,
    ?, ?, ?,
    ?,
    ?, ?,
    ?, ?,
    ?
)
ON CONFLICT (cusip) DO UPDATE SET
    canonical_type          = excluded.canonical_type,
    canonical_type_source   = excluded.canonical_type_source,
    raw_type_mode           = excluded.raw_type_mode,
    raw_type_count          = excluded.raw_type_count,
    security_type_inferred  = excluded.security_type_inferred,
    asset_category_seed     = excluded.asset_category_seed,
    market_sector           = excluded.market_sector,
    issuer_name             = excluded.issuer_name,
    ticker                  = excluded.ticker,
    figi                    = excluded.figi,
    exchange                = excluded.exchange,
    country_code            = excluded.country_code,
    is_equity               = excluded.is_equity,
    ticker_expected         = excluded.ticker_expected,
    is_priceable            = excluded.is_priceable,
    is_otc                  = excluded.is_otc,
    is_permanent            = excluded.is_permanent,
    is_active               = excluded.is_active,
    classification_source   = excluded.classification_source,
    ticker_source           = excluded.ticker_source,
    confidence              = excluded.confidence,
    openfigi_attempts       = GREATEST(excluded.openfigi_attempts,
                                       cusip_classifications.openfigi_attempts),
    last_openfigi_attempt   = COALESCE(cusip_classifications.last_openfigi_attempt,
                                       excluded.last_openfigi_attempt),
    openfigi_status         = COALESCE(cusip_classifications.openfigi_status,
                                       excluded.openfigi_status),
    last_priceable_check    = COALESCE(cusip_classifications.last_priceable_check,
                                       excluded.last_priceable_check),
    last_confirmed_date     = excluded.last_confirmed_date,
    inactive_since          = excluded.inactive_since,
    inactive_reason         = excluded.inactive_reason,
    notes                   = excluded.notes,
    updated_at              = NOW()
"""


RETRY_UPSERT_SQL = """
INSERT INTO cusip_retry_queue (
    cusip, issuer_name, canonical_type, status
) VALUES (?, ?, ?, 'pending')
ON CONFLICT (cusip) DO UPDATE SET
    issuer_name    = excluded.issuer_name,
    canonical_type = excluded.canonical_type,
    updated_at     = NOW()
"""


def _row_to_params(cls_row: dict) -> list:
    """Flatten a classify_cusip() dict to the UPSERT_SQL parameter order."""
    return [
        cls_row['cusip'],
        cls_row['canonical_type'],
        cls_row['canonical_type_source'],
        cls_row['raw_type_mode'],
        cls_row['raw_type_count'],
        cls_row['security_type_inferred'],
        cls_row['asset_category_seed'],
        cls_row['market_sector'],
        cls_row['issuer_name'],
        cls_row['ticker'],
        cls_row['figi'],
        cls_row['exchange'],
        cls_row['country_code'],
        cls_row['is_equity'],
        cls_row['ticker_expected'],
        cls_row['is_priceable'],
        cls_row['is_otc'],
        cls_row['is_permanent'],
        cls_row['is_active'],
        cls_row['classification_source'],
        cls_row['ticker_source'],
        cls_row['confidence'],
        cls_row['openfigi_attempts'],
        cls_row['last_openfigi_attempt'],
        cls_row['openfigi_status'],
        cls_row['last_priceable_check'],
        cls_row['first_seen_date'],
        cls_row['last_confirmed_date'],
        cls_row['inactive_since'],
        cls_row['inactive_reason'],
        cls_row['notes'],
    ]


def _load_manual_overrides() -> dict[str, dict]:
    """Load data/reference/ticker_overrides.csv keyed by CUSIP.

    Overrides are applied AFTER rule classification (Step 5). They set
    ticker / canonical_type (from security_type_override) / source='manual'
    / confidence='exact'.
    """
    if not os.path.exists(OVERRIDES_PATH):
        return {}
    result: dict[str, dict] = {}
    with open(OVERRIDES_PATH, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cusip = (row.get('cusip') or '').strip()
            if len(cusip) != 9:
                continue
            result[cusip] = {
                'ticker': (row.get('correct_ticker') or '').strip() or None,
                'security_type_override': (row.get('security_type_override') or '').strip() or None,
                'note': (row.get('note') or '').strip() or None,
                'company_name': (row.get('company_name') or '').strip() or None,
            }
    return result


_OVERRIDE_TYPE_MAP = {
    'equity': ('COM', True, True, False, True),
    'etf': ('ETF', True, True, False, True),
    'derivative': ('OPTION', False, False, True, False),
    'money_market': ('CASH', False, False, True, False),
}


def _apply_override(cls_row: dict, ov: dict) -> dict:
    """Mutate + return cls_row with override values."""
    sto = ov.get('security_type_override')
    if sto and sto in _OVERRIDE_TYPE_MAP:
        ct, eq, pr, perm, tx = _OVERRIDE_TYPE_MAP[sto]
        cls_row['canonical_type'] = ct
        cls_row['is_equity'] = eq
        cls_row['is_priceable'] = pr
        cls_row['is_permanent'] = perm
        cls_row['ticker_expected'] = tx
    if ov.get('ticker'):
        cls_row['ticker'] = ov['ticker']
        cls_row['ticker_source'] = 'manual'
    cls_row['canonical_type_source'] = 'manual'
    cls_row['classification_source'] = 'manual'
    cls_row['confidence'] = 'exact'
    if ov.get('note'):
        existing = cls_row.get('notes') or ''
        cls_row['notes'] = (existing + ' | ' + ov['note']).strip(' |') if existing else ov['note']
    return cls_row


def _chunks(iterable: Iterable, size: int):
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def run(read_db: str, write_db: str, *, dry_run: bool = False) -> dict:
    """Classify the whole universe. Returns summary dict."""
    print(f"Reading universe from {read_db}")
    read_con = duckdb.connect(read_db, read_only=True)
    try:
        universe = get_cusip_universe(read_con)
    finally:
        read_con.close()

    total = len(universe)
    print(f"  Universe: {total:,} CUSIPs")

    if total == 0:
        return {'total': 0}

    overrides = _load_manual_overrides()
    print(f"  Manual overrides loaded: {len(overrides):,}")

    today = date.today()
    rows_iter = universe.to_dict('records')

    classified: list[dict] = []
    retry_rows: list[tuple] = []
    type_counts: dict[str, int] = {}
    triage_rows: list[dict] = []  # RC3 — override/system issuer_name mismatches

    t0 = time.time()
    for i, src in enumerate(rows_iter, start=1):
        row_for_cls = {
            'cusip': src['cusip'],
            'issuer_name': src.get('issuer_name_sample'),
            'raw_type_mode': src.get('raw_type_mode'),
            'raw_type_count': src.get('raw_type_count'),
            'security_type_inferred': src.get('security_type_inferred'),
            'asset_category_seed': src.get('asset_category_seed'),
            'market_sector': None,
            'exchange': None,
            'figi': None,
            'ticker': None,
            'first_seen_date': today,
        }
        cls = classify_cusip(row_for_cls)

        ov = overrides.get(src['cusip'])
        if ov is not None:
            # RC3 — compare override.company_name to system-believed issuer
            # name BEFORE applying the override (the override does not touch
            # issuer_name, so pre/post values are identical for this field,
            # but we snapshot at the moment of decision for clarity).
            sev = _triage_severity(ov.get('company_name') or '',
                                   cls.get('issuer_name') or '')
            if sev != 'exact':
                triage_rows.append({
                    'cusip': src['cusip'],
                    'override_ticker': ov.get('ticker') or '',
                    'override_company': ov.get('company_name') or '',
                    'openfigi_name': cls.get('issuer_name') or '',
                    'mismatch_severity': sev,
                })
            cls = _apply_override(cls, ov)

        classified.append(cls)
        type_counts[cls['canonical_type']] = type_counts.get(cls['canonical_type'], 0) + 1

        # Retry queue: equity CUSIPs without a ticker, non-permanent.
        if cls['ticker_expected'] and not cls['ticker'] and not cls['is_permanent']:
            retry_rows.append((
                cls['cusip'],
                cls['issuer_name'],
                cls['canonical_type'],
            ))

        if i % PROGRESS_EVERY == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            print(f"    classified {i:,}/{total:,} ({rate:,.0f} rows/s)")

    elapsed = time.time() - t0
    print(f"  Classification complete: {total:,} rows in {elapsed:.1f}s "
          f"({total/elapsed:,.0f} rows/s)")

    # RC3 — write the triage queue regardless of dry_run. The queue is an
    # observational artifact, not part of DB state, and users may want to
    # inspect it during dry-run inspection.
    if triage_rows:
        os.makedirs(os.path.dirname(OVERRIDE_TRIAGE_PATH), exist_ok=True)
        with open(OVERRIDE_TRIAGE_PATH, 'w', newline='') as f:
            w = csv.DictWriter(
                f,
                fieldnames=['cusip', 'override_ticker', 'override_company',
                            'openfigi_name', 'mismatch_severity'],
            )
            w.writeheader()
            w.writerows(triage_rows)
        sev_counts: dict[str, int] = {}
        for r in triage_rows:
            sev_counts[r['mismatch_severity']] = sev_counts.get(r['mismatch_severity'], 0) + 1
        print(f"  RC3 override triage queue: {len(triage_rows):,} mismatches "
              f"→ {OVERRIDE_TRIAGE_PATH} (severity: {dict(sev_counts)})")
    else:
        print("  RC3 override triage queue: 0 mismatches (all override "
              "company_name values matched system issuer_name)")

    summary = {
        'total': total,
        'type_counts': dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        'retry_queue': len(retry_rows),
        'triage_queue': len(triage_rows),
        'other_pct': type_counts.get('OTHER', 0) * 100.0 / total if total else 0.0,
    }

    if dry_run:
        print("  [dry-run] skipping DB writes")
        return summary

    # --- Persist ---
    print(f"Writing to {write_db}")
    write_con = duckdb.connect(write_db)
    try:
        write_con.execute("BEGIN")
        written = 0
        for batch in _chunks(classified, BATCH_SIZE):
            params = [_row_to_params(r) for r in batch]
            write_con.executemany(UPSERT_SQL, params)
            written += len(batch)
            if written % (PROGRESS_EVERY) == 0:
                # Checkpoint commit-in-flight for long runs.
                write_con.execute("COMMIT")
                write_con.execute("BEGIN")
                print(f"    upserted {written:,}/{total:,} cusip_classifications")
        write_con.execute("COMMIT")

        if retry_rows:
            write_con.execute("BEGIN")
            for batch in _chunks(retry_rows, BATCH_SIZE):
                write_con.executemany(RETRY_UPSERT_SQL, batch)
            write_con.execute("COMMIT")
            print(f"  cusip_retry_queue: {len(retry_rows):,} pending rows upserted")

        write_con.execute("CHECKPOINT")
    finally:
        write_con.close()

    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Initial CUSIP classification")
    p.add_argument("--staging", action="store_true",
                   help="Write to staging DB (reads still from prod)")
    p.add_argument("--dry-run", action="store_true",
                   help="Classify but do not persist")
    args = p.parse_args()

    write_db = STAGING_DB if args.staging else PROD_DB
    read_db = PROD_DB  # always read source data from prod

    print("build_classifications.py — initial CUSIP classification")
    print("=" * 60)
    print(f"  read:  {read_db}")
    print(f"  write: {write_db}")
    if args.dry_run:
        print("  mode: DRY RUN")
    print()

    summary = run(read_db, write_db, dry_run=args.dry_run)

    print()
    print("Summary")
    print("-" * 60)
    print(f"  Total classified: {summary['total']:,}")
    print(f"  OTHER: {summary.get('other_pct', 0):.1f}%")
    print(f"  Retry queue pending: {summary.get('retry_queue', 0):,}")
    print()
    print("  Top canonical_type counts:")
    for ct, n in list(summary.get('type_counts', {}).items())[:15]:
        print(f"    {ct:15s} {n:>10,}")


if __name__ == "__main__":
    main()
