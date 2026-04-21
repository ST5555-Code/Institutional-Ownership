#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# promote_13dg.py unit: one run_id (all staged rows for a validated run).
# This is the commit-or-rollback boundary for a 13D/G scoped run.
"""promote_13dg.py — staging → prod for SC 13D/G filings.

Runs after validate_13dg.py. Refuses to promote if:
  - the validation report for the run_id is missing
  - the validation report has any BLOCK entries
  - the entity gate returned any unresolved identifiers

On success:
  - DELETE matching (accession_number) rows from prod beneficial_ownership_v2
  - INSERT staged rows into prod beneficial_ownership_v2
  - Rebuild prod beneficial_ownership_current (latest-per-filer-subject)
  - Stamp data_freshness for both tables
  - Refresh data/13f_readonly.duckdb snapshot
  - Update ingestion_impacts.promote_status = 'promoted' + promoted_at
  - Supersede prior manifest rows for any accession that amended a
    previously-loaded accession (same filer_cik + subject_cusip chain)

Usage:
  python3 scripts/promote_13dg.py --run-id R
  python3 scripts/promote_13dg.py --run-id R --exclude ACC1,ACC2
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.id_allocator import reserve_ids  # noqa: E402
from pipeline.shared import (  # noqa: E402
    bulk_enrich_bo_filers,
    rebuild_beneficial_ownership_current,
    refresh_snapshot,
    stamp_freshness,
)


REPORTS_DIR = os.path.join(BASE_DIR, "logs", "reports")


def _read_validation_report(run_id: str) -> str:
    path = os.path.join(REPORTS_DIR, f"13dg_{run_id}.md")
    if not os.path.exists(path):
        raise SystemExit(
            f"No validation report at {path} — run validate_13dg.py first"
        )
    with open(path) as fh:
        return fh.read()


def _assert_promote_ok(report_text: str) -> None:
    if "Promote-ready: **YES**" not in report_text and "Promote-ready: YES" not in report_text:
        raise SystemExit(
            "Validation report says NOT promote-ready — aborting. "
            "Review the report, resolve BLOCKs, re-validate."
        )


def _load_staged_rows(staging_con, run_id: str, exclude: set[str]):
    rows = staging_con.execute(
        """
        SELECT s.accession_number, s.filer_cik, s.filer_name,
               s.subject_cusip, s.subject_ticker, s.subject_name,
               s.filing_type, s.filing_date, s.report_date,
               s.pct_owned, s.shares_owned, s.aggregate_value,
               s.intent, s.is_amendment, s.prior_accession,
               s.purpose_text, s.group_members, s.manager_cik,
               s.loaded_at, s.name_resolved, s.entity_id,
               s.manifest_id
        FROM stg_13dg_filings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
        ORDER BY s.accession_number
        """,
        [run_id],
    ).fetchdf()
    if exclude:
        rows = rows[~rows["accession_number"].isin(exclude)]
    return rows


def _promote(prod_con, rows) -> tuple[int, int]:
    """DELETE matching accessions in prod, then INSERT staged rows.

    Returns (deleted, inserted).
    """
    if rows.empty:
        return 0, 0
    accessions = rows["accession_number"].tolist()
    placeholders = ",".join(["?"] * len(accessions))
    deleted = prod_con.execute(
        f"SELECT COUNT(*) FROM beneficial_ownership_v2 "
        f"WHERE accession_number IN ({placeholders})",
        accessions,
    ).fetchone()[0]
    prod_con.execute(
        f"DELETE FROM beneficial_ownership_v2 "
        f"WHERE accession_number IN ({placeholders})",
        accessions,
    )
    prod_con.register("stage_df", rows.drop(columns=["manifest_id"]))
    prod_con.execute(
        """
        INSERT INTO beneficial_ownership_v2 (
            accession_number, filer_cik, filer_name,
            subject_cusip, subject_ticker, subject_name,
            filing_type, filing_date, report_date,
            pct_owned, shares_owned, aggregate_value,
            intent, is_amendment, prior_accession,
            purpose_text, group_members, manager_cik,
            loaded_at, name_resolved, entity_id
        )
        SELECT accession_number, filer_cik, filer_name,
               subject_cusip, subject_ticker, subject_name,
               filing_type, filing_date, report_date,
               pct_owned, shares_owned, aggregate_value,
               intent, is_amendment, prior_accession,
               purpose_text, group_members, manager_cik,
               loaded_at, name_resolved, entity_id
        FROM stage_df
        """
    )
    prod_con.unregister("stage_df")
    inserted = len(rows)
    return int(deleted), int(inserted)


def _rebuild_current(prod_con) -> int:
    """Rebuild beneficial_ownership_current from BO v2. Delegates to shared.

    The shared implementation carries the five entity columns
    (entity_id, rollup_entity_id, rollup_name, dm_rollup_entity_id,
    dm_rollup_name) through from BO v2 — must run AFTER the bulk
    enrichment pass so L4 picks up the fresh rollups.
    """
    return rebuild_beneficial_ownership_current(prod_con)


def _update_impacts(prod_con, run_id: str) -> int:
    prod_con.execute(
        """
        UPDATE ingestion_impacts
        SET promote_status = 'promoted',
            rows_promoted = rows_staged,
            promoted_at = CURRENT_TIMESTAMP
        FROM ingestion_manifest m
        WHERE ingestion_impacts.manifest_id = m.manifest_id
          AND m.run_id = ?
          AND m.source_type = '13DG'
          AND ingestion_impacts.promote_status = 'pending'
        """,
        [run_id],
    )
    # DuckDB doesn't return affected row count directly; re-query
    return prod_con.execute(
        """
        SELECT COUNT(*) FROM ingestion_impacts i
        JOIN ingestion_manifest m ON m.manifest_id = i.manifest_id
        WHERE m.run_id = ? AND i.promote_status = 'promoted'
        """,
        [run_id],
    ).fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote 13D/G staging → prod")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--exclude", default="",
                        help="Comma-separated accession_numbers to hold out.")
    args = parser.parse_args()

    exclude = {a.strip() for a in args.exclude.split(",") if a.strip()}
    report_text = _read_validation_report(args.run_id)
    _assert_promote_ok(report_text)

    staging_con = duckdb.connect(STAGING_DB, read_only=True)
    prod_con = duckdb.connect(PROD_DB)
    try:
        rows = _load_staged_rows(staging_con, args.run_id, exclude)
        if rows.empty:
            print(f"No rows to promote for run_id={args.run_id}")
            return

        # Migration 001 must have run on prod. Also replicate on staging
        # so this script works against both — write_impact and
        # get_or_create_manifest_row both touch ingestion_manifest rows
        # that live in staging DB.
        try:
            prod_con.execute("SELECT 1 FROM ingestion_manifest LIMIT 1")
        except duckdb.CatalogException as exc:
            raise SystemExit(
                "ingestion_manifest not present in prod — run migration 001 first"
            ) from exc

        # Mirror manifest rows from staging to prod so prod's impacts FK
        # resolves. For the scoped reference vertical this is a small
        # insert; long-term the orchestrator handles manifest promotion.
        manifest_ids = set(rows["manifest_id"].tolist())
        mf_rows = staging_con.execute(
            f"SELECT * FROM ingestion_manifest WHERE manifest_id IN "
            f"({','.join('?' * len(manifest_ids))})",
            list(manifest_ids),
        ).fetchdf()
        if not mf_rows.empty:
            prod_con.register("mf", mf_rows)
            # ingestion_manifest has both PRIMARY KEY (manifest_id) and
            # UNIQUE (object_key), so DuckDB rejects a bare ON CONFLICT
            # DO UPDATE. Delete by either key first, then insert.
            m_ids = [int(x) for x in mf_rows["manifest_id"].tolist()]
            m_keys = mf_rows["object_key"].tolist()
            prod_con.execute(
                f"DELETE FROM ingestion_manifest "
                f"WHERE manifest_id IN ({','.join('?' * len(m_ids))})",
                m_ids,
            )
            prod_con.execute(
                f"DELETE FROM ingestion_manifest "
                f"WHERE object_key IN ({','.join('?' * len(m_keys))})",
                m_keys,
            )
            prod_con.execute(
                "INSERT INTO ingestion_manifest SELECT * FROM mf"
            )
            prod_con.unregister("mf")

        # Mirror the impacts too so promoted_at update below has rows
        # to hit. Audit-trail preservation (2026-04-17 bugfix): impacts
        # already `promote_status='promoted'` in prod are preserved —
        # staging rows would overwrite them with `pending` since staging
        # never marks impacts promoted, wiping the audit trail on every
        # re-promote.
        im_rows = staging_con.execute(
            f"""
            SELECT * FROM ingestion_impacts
            WHERE manifest_id IN ({','.join('?' * len(manifest_ids))})
            """,
            list(manifest_ids),
        ).fetchdf()
        if not im_rows.empty:
            prod_con.execute(
                f"""
                DELETE FROM ingestion_impacts
                 WHERE manifest_id IN ({','.join('?' * len(manifest_ids))})
                   AND promote_status <> 'promoted'
                """,
                list(manifest_ids),
            )
            # obs-03 Phase 1: allocate prod-side impact_ids via the
            # central allocator instead of carrying staging PKs across
            # the mirror. Anti-join runs in pandas so the frame we
            # INSERT has its impact_id column rewritten to the reserved
            # range; prod's PK space is never contaminated with a
            # staging-origin id.
            kept_rows = prod_con.execute(
                f"""
                SELECT manifest_id, unit_type, unit_key_json
                  FROM ingestion_impacts
                 WHERE manifest_id IN ({','.join('?' * len(manifest_ids))})
                """,
                list(manifest_ids),
            ).fetchall()
            existing_keys = {(m, u, k) for m, u, k in kept_rows}
            if existing_keys:
                mask = [
                    (int(m), u, k) not in existing_keys
                    for m, u, k in zip(
                        im_rows["manifest_id"],
                        im_rows["unit_type"],
                        im_rows["unit_key_json"],
                    )
                ]
                to_insert = im_rows[mask].copy()
            else:
                to_insert = im_rows.copy()
            if not to_insert.empty:
                new_ids = reserve_ids(
                    prod_con, "ingestion_impacts", "impact_id",
                    len(to_insert),
                )
                to_insert["impact_id"] = list(new_ids)
                prod_con.register("im", to_insert)
                prod_con.execute(
                    "INSERT INTO ingestion_impacts SELECT * FROM im"
                )
                prod_con.unregister("im")

        print(f"Promoting {len(rows)} staged rows for run_id={args.run_id}")
        deleted, inserted = _promote(prod_con, rows)
        prod_con.execute("CHECKPOINT")
        print(f"  beneficial_ownership_v2: -{deleted} +{inserted}")

        # Group 2 entity enrichment: resolve entity_id + rollup columns
        # for the filers touched by this run. Scoped — full-refresh lives
        # in scripts/enrich_13dg.py. Must run before _rebuild_current so
        # the L4 table inherits enriched values.
        filer_ciks = set(rows["filer_cik"].dropna().tolist())
        enriched = bulk_enrich_bo_filers(prod_con, filer_ciks=filer_ciks)
        prod_con.execute("CHECKPOINT")
        print(f"  bo_v2 Group 2 enriched: {enriched:+,} entity_id delta "
              f"across {len(filer_ciks)} filer_cik(s)")

        cur_rows = _rebuild_current(prod_con)
        prod_con.execute("CHECKPOINT")
        print(f"  beneficial_ownership_current rebuilt: {cur_rows:,} rows")

        stamp_freshness(prod_con, "beneficial_ownership_v2")
        stamp_freshness(prod_con, "beneficial_ownership_current")
        # Logical label (not a real table) — pass explicit row_count
        # so record_freshness does not COUNT(*) a missing table.
        bo_v2_enriched = prod_con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2 "
            "WHERE entity_id IS NOT NULL"
        ).fetchone()[0]
        stamp_freshness(
            prod_con,
            "beneficial_ownership_v2_enrichment",
            row_count=bo_v2_enriched,
        )

        promoted = _update_impacts(prod_con, args.run_id)
        prod_con.execute("CHECKPOINT")
        print(f"  ingestion_impacts promoted: {promoted}")
    finally:
        staging_con.close()
        prod_con.close()

    refresh_snapshot()
    print("DONE  promote_13dg")


if __name__ == "__main__":
    main()
