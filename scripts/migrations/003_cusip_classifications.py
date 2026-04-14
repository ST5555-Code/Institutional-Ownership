#!/usr/bin/env python3
"""
Migration 003 — CUSIP & ticker classification (L3 reference vertical).

Adds the classification layer on top of ``securities``:
  - cusip_classifications  — one row per CUSIP with canonical_type,
                              priceable/equity/permanence flags, OpenFIGI
                              retry counters, and issuer/ticker/FIGI fields.
                              Primary classification target.
  - cusip_retry_queue      — work queue for CUSIPs that need an OpenFIGI
                              round-trip (ticker_expected=TRUE AND
                              ticker IS NULL).
  - _cache_openfigi        — persistent OpenFIGI response cache. Migration
                              003 creates it fresh with the full v3 column
                              set (prior legacy build_cusip.py created a
                              subset on the fly; we supersede that).
  - schema_versions        — one-row stamp per migration (created fresh
                              here; prior migrations didn't stamp).

Also extends ``securities`` with 7 columns populated in Session 2:
  canonical_type, canonical_type_source, is_equity, is_priceable,
  ticker_expected, is_active (DEFAULT TRUE), figi.
``securities.market_sector`` already exists (column 6) — NOT re-added.

Idempotent: every CREATE/ALTER uses IF NOT EXISTS. Safe to re-run. Never
drops a table or column.

Usage:
    python3 scripts/migrations/003_cusip_classifications.py              # prod
    python3 scripts/migrations/003_cusip_classifications.py --staging    # staging
    python3 scripts/migrations/003_cusip_classifications.py --both       # both
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402


MIGRATION_VERSION = "003_cusip_classifications"


MIGRATION_SQL = [
    # --- schema_versions (created fresh; prior migrations did not stamp) ---
    """
    CREATE TABLE IF NOT EXISTS schema_versions (
        version     VARCHAR PRIMARY KEY,
        applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notes       VARCHAR
    )
    """,

    # --- cusip_classifications ---
    """
    CREATE TABLE IF NOT EXISTS cusip_classifications (
        cusip                   VARCHAR PRIMARY KEY,

        canonical_type          VARCHAR NOT NULL,
        canonical_type_source   VARCHAR NOT NULL,
            -- 'market_sector'  from OpenFIGI marketSector  (highest confidence)
            -- 'security_type'  from OpenFIGI securityType
            -- 'asset_category' from fund_holdings_v2.asset_category (N-PORT seed)
            -- 'inferred'       from security_type_inferred seed + rules
            -- 'manual'         operator override

        raw_type_mode           VARCHAR,
        raw_type_count          INTEGER,
        security_type_inferred  VARCHAR,
        asset_category_seed     VARCHAR,
        market_sector           VARCHAR,

        issuer_name             VARCHAR,
        ticker                  VARCHAR,
        figi                    VARCHAR,
        exchange                VARCHAR,
        country_code            VARCHAR,

        is_equity               BOOLEAN NOT NULL DEFAULT FALSE,
        ticker_expected         BOOLEAN NOT NULL DEFAULT FALSE,
        is_priceable            BOOLEAN NOT NULL DEFAULT FALSE,
        is_permanent            BOOLEAN NOT NULL DEFAULT FALSE,
        is_active               BOOLEAN NOT NULL DEFAULT TRUE,

        classification_source   VARCHAR NOT NULL,
        ticker_source           VARCHAR,
        confidence              VARCHAR NOT NULL
            CHECK (confidence IN ('exact','high','medium','low')),

        openfigi_attempts       INTEGER NOT NULL DEFAULT 0,
        last_openfigi_attempt   TIMESTAMP,
        openfigi_status         VARCHAR
            CHECK (openfigi_status IN ('success','no_result','rate_limited','error')
                   OR openfigi_status IS NULL),

        last_priceable_check    TIMESTAMP,
        first_seen_date         DATE NOT NULL,
        last_confirmed_date     DATE,
        inactive_since          DATE,
        inactive_reason         VARCHAR
            CHECK (inactive_reason IN (
                'delisted','merged','suspended',
                'no_yf_data','wrong_classification','manual'
            ) OR inactive_reason IS NULL),

        notes                   VARCHAR,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    "CREATE INDEX IF NOT EXISTS idx_cc_priceable_active "
    "ON cusip_classifications (is_priceable, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_cc_canonical "
    "ON cusip_classifications (canonical_type)",
    "CREATE INDEX IF NOT EXISTS idx_cc_retry "
    "ON cusip_classifications (ticker_expected, is_permanent, openfigi_attempts)",

    # --- cusip_retry_queue ---
    """
    CREATE TABLE IF NOT EXISTS cusip_retry_queue (
        cusip               VARCHAR PRIMARY KEY,
        issuer_name         VARCHAR,
        canonical_type      VARCHAR,
        attempt_count       INTEGER NOT NULL DEFAULT 0,
        first_attempted     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_attempted      TIMESTAMP,
        last_error          VARCHAR,
        status              VARCHAR NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','resolved','unmappable','manual')),
        resolved_ticker     VARCHAR,
        resolved_figi       VARCHAR,
        notes               VARCHAR,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_crq_pending "
    "ON cusip_retry_queue (status, last_attempted)",

    # --- _cache_openfigi — created fresh with full v3 column set ---
    """
    CREATE TABLE IF NOT EXISTS _cache_openfigi (
        cusip           VARCHAR PRIMARY KEY,
        figi            VARCHAR,
        ticker          VARCHAR,
        exchange        VARCHAR,
        security_type   VARCHAR,
        market_sector   VARCHAR,
        cached_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # --- ALTER securities — 7 new columns (market_sector already exists) ---
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS canonical_type        VARCHAR",
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS canonical_type_source VARCHAR",
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS is_equity             BOOLEAN",
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS is_priceable          BOOLEAN",
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS ticker_expected       BOOLEAN",
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS is_active             BOOLEAN DEFAULT TRUE",
    "ALTER TABLE securities ADD COLUMN IF NOT EXISTS figi                  VARCHAR",
]


EXPECTED_NEW_TABLES = (
    "cusip_classifications",
    "cusip_retry_queue",
    "_cache_openfigi",
    "schema_versions",
)

EXPECTED_NEW_SECURITIES_COLS = (
    "canonical_type",
    "canonical_type_source",
    "is_equity",
    "is_priceable",
    "ticker_expected",
    "is_active",
    "figi",
)


def _table_exists(con, name: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {name} LIMIT 1")
        return True
    except Exception:
        return False


def _securities_columns(con) -> list[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'securities' ORDER BY ordinal_position"
    ).fetchall()
    return [r[0] for r in rows]


def run_migration(db_path: str) -> None:
    """Apply migration 003 to one DB. Idempotent."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path)

    # ---- before state ----
    before_tables = {t: _table_exists(con, t) for t in EXPECTED_NEW_TABLES}
    before_cols = set(_securities_columns(con))

    # market_sector must already exist — assert it, never re-create
    if "market_sector" not in before_cols:
        con.close()
        raise RuntimeError(
            f"{db_path}: securities.market_sector is missing. "
            "Migration 003 assumes it exists (column 6). Aborting."
        )

    # ---- apply (rollback on failure) ----
    con.execute("BEGIN")
    try:
        for stmt in MIGRATION_SQL:
            con.execute(stmt)
        # Stamp schema_versions (INSERT OR IGNORE — idempotent)
        con.execute(
            "INSERT OR IGNORE INTO schema_versions (version, notes) VALUES (?, ?)",
            [MIGRATION_VERSION, "CUSIP & ticker classification layer"],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        raise

    con.execute("CHECKPOINT")

    # ---- after / verification ----
    after_tables = {t: _table_exists(con, t) for t in EXPECTED_NEW_TABLES}
    after_cols = set(_securities_columns(con))

    # Hard asserts
    for t in EXPECTED_NEW_TABLES:
        assert after_tables[t], f"{db_path}: table {t} missing after migration"
    for c in EXPECTED_NEW_SECURITIES_COLS:
        assert c in after_cols, f"{db_path}: securities.{c} missing after migration"
    # market_sector must appear exactly once
    all_cols = _securities_columns(con)
    ms_count = sum(1 for c in all_cols if c == "market_sector")
    assert ms_count == 1, (
        f"{db_path}: securities.market_sector appears {ms_count}× (expected 1)"
    )

    stamp = con.execute(
        "SELECT applied_at FROM schema_versions WHERE version = ?",
        [MIGRATION_VERSION],
    ).fetchone()

    con.close()

    print(f"  DB: {db_path}")
    for t in EXPECTED_NEW_TABLES:
        status = "existed" if before_tables[t] else "created"
        print(f"    {t:26s} {status}")
    new_cols = [c for c in EXPECTED_NEW_SECURITIES_COLS if c not in before_cols]
    added = ", ".join(new_cols) if new_cols else "(all already present)"
    print(f"    securities: added {len(new_cols)}/7 columns → {added}")
    print(f"    schema_versions stamp: {MIGRATION_VERSION} @ {stamp[0] if stamp else '?'}")


def main() -> None:
    p = argparse.ArgumentParser(description="CUSIP classification migration (003)")
    p.add_argument("--staging", action="store_true",
                   help="Apply to staging DB only")
    p.add_argument("--both", action="store_true",
                   help="Apply to staging then prod")
    args = p.parse_args()

    print("Migration 003 — CUSIP classification layer")
    print("=" * 60)

    if args.both:
        run_migration(STAGING_DB)
        run_migration(PROD_DB)
    elif args.staging:
        run_migration(STAGING_DB)
    else:
        run_migration(PROD_DB)

    print("Done.")


if __name__ == "__main__":
    main()
