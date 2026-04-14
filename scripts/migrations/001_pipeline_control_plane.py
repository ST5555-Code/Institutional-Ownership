#!/usr/bin/env python3
"""
Migration 001 — Pipeline control plane (L0).

Creates the L0 machinery that the v1.2 framework requires:
  - manifest_id_seq, impact_id_seq, resolution_id_seq (three separate sequences)
  - ingestion_manifest (one row per fetched source object)
  - ingestion_impacts  (one row per (manifest, unit) — tracks what an
                        accession contributed to which canonical table
                        and quarter)
  - pending_entity_resolution (unresolved identifiers queued from
                               entity_gate_check)
  - data_freshness (DDL confirmation — ARCH-3A already created it)
  - ingestion_manifest_current (VIEW — latest non-superseded per
                                 source object_key)

Idempotent: every CREATE uses IF NOT EXISTS. Safe to re-run.

Usage:
    python3 scripts/migrations/001_pipeline_control_plane.py              # prod
    python3 scripts/migrations/001_pipeline_control_plane.py --staging    # staging
    python3 scripts/migrations/001_pipeline_control_plane.py --both       # both

Never drops a table. Never drops or recreates a sequence.
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402


MIGRATION_SQL = [
    # --- Sequences (three separate, per v1.2 correction) ---
    "CREATE SEQUENCE IF NOT EXISTS manifest_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS impact_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS resolution_id_seq START 1",

    # --- ingestion_manifest ---
    # object_key is the synthetic uniqueness column: accession_number when
    # present, else sha256(source_url + run_id). Avoids the original v1.1
    # design of UNIQUE(source_type, accession_number, source_url) with a
    # nullable accession column, which would silently allow dup fetches
    # for any source that does not have an accession (market data, FINRA).
    """
    CREATE TABLE IF NOT EXISTS ingestion_manifest (
        manifest_id          BIGINT PRIMARY KEY DEFAULT nextval('manifest_id_seq'),
        source_type          VARCHAR NOT NULL,         -- '13F' | 'NPORT' | '13DG' | 'ADV' | 'NCEN' | 'MARKET' | 'FINRA_SHORT'
        object_type          VARCHAR NOT NULL,         -- 'ZIP' | 'XML' | 'PDF' | 'HTML' | 'CSV' | 'JSON'
        object_key           VARCHAR NOT NULL UNIQUE,  -- accession_number OR sha256(source_url + run_id)
        source_url           VARCHAR,
        accession_number     VARCHAR,
        report_period        DATE,
        filing_date          DATE,
        accepted_at          TIMESTAMP,
        run_id               VARCHAR NOT NULL,
        discovered_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fetch_started_at     TIMESTAMP,
        fetch_completed_at   TIMESTAMP,
        fetch_status         VARCHAR NOT NULL DEFAULT 'pending',
                                                        -- 'pending' | 'fetching' | 'complete' | 'failed' | 'skipped'
        http_code            INTEGER,
        source_bytes         BIGINT,
        source_checksum      VARCHAR,
        local_path           VARCHAR,
        retry_count          INTEGER NOT NULL DEFAULT 0,
        error_message        VARCHAR,
        parser_version       VARCHAR,
        schema_version       VARCHAR,
        is_amendment         BOOLEAN NOT NULL DEFAULT FALSE,
        prior_accession      VARCHAR,
        superseded_by_manifest_id BIGINT,
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # --- ingestion_impacts ---
    # One row per (manifest, canonical-target, unit). For a single 13F
    # accession the unit is typically (quarter); for N-PORT it is
    # (series_id, report_month); for 13D/G it is (filer_cik, subject_cusip).
    """
    CREATE TABLE IF NOT EXISTS ingestion_impacts (
        impact_id            BIGINT PRIMARY KEY DEFAULT nextval('impact_id_seq'),
        manifest_id          BIGINT NOT NULL,
        target_table         VARCHAR NOT NULL,          -- 'holdings_v2' | 'fund_holdings_v2' | 'beneficial_ownership_v2' | ...
        unit_type            VARCHAR NOT NULL,          -- 'quarter' | 'series_month' | 'filer_subject' | 'ticker' | ...
        unit_key_json        VARCHAR NOT NULL,          -- JSON-encoded key, e.g. '{"quarter":"2025Q4"}'
        report_date          DATE,
        rows_staged          INTEGER NOT NULL DEFAULT 0,
        rows_promoted        INTEGER NOT NULL DEFAULT 0,
        load_status          VARCHAR NOT NULL DEFAULT 'pending',
                                                        -- 'pending' | 'loading' | 'loaded' | 'failed'
        validation_tier      VARCHAR,                   -- 'PASS' | 'WARN' | 'FLAG' | 'BLOCK' | NULL
        validation_report    VARCHAR,                   -- JSON blob or logs/ path
        promote_status       VARCHAR NOT NULL DEFAULT 'pending',
                                                        -- 'pending' | 'promoting' | 'promoted' | 'failed' | 'skipped'
        promote_duration_ms  BIGINT,
        validate_duration_ms BIGINT,
        promoted_at          TIMESTAMP,
        error_message        VARCHAR,
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # --- pending_entity_resolution ---
    # Sentinel pattern (DuckDB does not support partial indexes — see
    # entity_schema.sql's primary_parent_key / preferred_key design).
    # pending_key mirrors the natural uniqueness column for rows with
    # resolution_status='pending', NULL otherwise. UNIQUE is enforced on
    # pending_key only; resolved rows are unconstrained (multiple can
    # coexist with the same identifier over time, representing history).
    """
    CREATE TABLE IF NOT EXISTS pending_entity_resolution (
        resolution_id        BIGINT PRIMARY KEY DEFAULT nextval('resolution_id_seq'),
        manifest_id          BIGINT,
        source_type          VARCHAR NOT NULL,
        identifier_type      VARCHAR NOT NULL,         -- 'cik' | 'crd' | 'series_id' (lowercase!)
        identifier_value     VARCHAR NOT NULL,
        context_json         VARCHAR,                   -- original row / accession / hints
        resolution_status    VARCHAR NOT NULL DEFAULT 'pending',
                                                        -- 'pending' | 'resolved' | 'rejected'
        pending_key          VARCHAR UNIQUE,            -- identifier_type||':'||identifier_value while pending; NULL otherwise
        resolved_entity_id   BIGINT,
        resolved_by          VARCHAR,
        resolved_at          TIMESTAMP,
        resolution_notes     VARCHAR,
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # --- data_freshness (DDL confirmation — ARCH-3A already created it) ---
    """
    CREATE TABLE IF NOT EXISTS data_freshness (
        table_name       VARCHAR PRIMARY KEY,
        last_computed_at TIMESTAMP,
        row_count        BIGINT
    )
    """,

    # --- Indexes ---
    "CREATE INDEX IF NOT EXISTS idx_manifest_source_run ON ingestion_manifest(source_type, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_manifest_fetch_status ON ingestion_manifest(fetch_status)",
    "CREATE INDEX IF NOT EXISTS idx_manifest_accession ON ingestion_manifest(accession_number)",
    "CREATE INDEX IF NOT EXISTS idx_impacts_manifest ON ingestion_impacts(manifest_id)",
    "CREATE INDEX IF NOT EXISTS idx_impacts_promote_status ON ingestion_impacts(promote_status, validation_tier)",
    "CREATE INDEX IF NOT EXISTS idx_impacts_target ON ingestion_impacts(target_table)",
    "CREATE INDEX IF NOT EXISTS idx_pending_entity_status ON pending_entity_resolution(resolution_status)",

    # --- ingestion_manifest_current VIEW ---
    # Replace on every migration run so the definition stays in lockstep
    # with any column changes. CREATE OR REPLACE VIEW is idempotent and
    # does not require a DROP step.
    """
    CREATE OR REPLACE VIEW ingestion_manifest_current AS
    SELECT m.*
    FROM ingestion_manifest m
    WHERE m.superseded_by_manifest_id IS NULL
    """,
]


def run_migration(db_path: str) -> None:
    """Apply migration 001 to one DB. Idempotent."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path)

    # ---- before counts ----
    before = {}
    for t in ("ingestion_manifest", "ingestion_impacts",
              "pending_entity_resolution", "data_freshness"):
        try:
            before[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            before[t] = None

    # ---- apply ----
    for stmt in MIGRATION_SQL:
        con.execute(stmt)

    con.execute("CHECKPOINT")

    # ---- after counts ----
    after = {}
    for t in ("ingestion_manifest", "ingestion_impacts",
              "pending_entity_resolution", "data_freshness"):
        after[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    # ---- view sanity ----
    view_rows = con.execute(
        "SELECT COUNT(*) FROM ingestion_manifest_current"
    ).fetchone()[0]

    con.close()

    print(f"  DB: {db_path}")
    for t in ("ingestion_manifest", "ingestion_impacts",
              "pending_entity_resolution", "data_freshness"):
        bstr = "new" if before[t] is None else f"{before[t]}"
        print(f"    {t:30s} before={bstr:<6s} after={after[t]}")
    print(f"    ingestion_manifest_current view rows: {view_rows}")


def main() -> None:
    p = argparse.ArgumentParser(description="Pipeline control plane migration")
    p.add_argument("--staging", action="store_true",
                   help="Apply to staging DB only")
    p.add_argument("--both", action="store_true",
                   help="Apply to staging then prod")
    args = p.parse_args()

    print("Migration 001 — pipeline control plane")
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
