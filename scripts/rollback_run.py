#!/usr/bin/env python3
"""Rollback a completed SourcePipeline run from the command line.

Thin CLI wrapper around ``SourcePipeline.rollback(run_id)``. The base
class already contains the full rollback logic (LIFO over
``ingestion_impacts`` → per-action reversal via ``_rollback_insert`` /
``_rollback_flip`` / ``_rollback_scd``) plus a valid-state-transition
guard on ``ingestion_manifest.fetch_status``. This wrapper only
provides:

  * dry-run reporting: manifest status, impact counts, pre-state row
    summary on the target table, and what the rollback would do
  * safety flags: ``--confirm`` + ``--i-understand-this-writes`` gate
    any write; ``--allow-prod`` required when the DB path resolves to
    ``data/13f.duckdb``
  * idempotency: refuses to re-rollback a run already in
    ``rolled_back`` status with a clear message

Use cases:

  * int-22 — reverse the re-load of ``13f_holdings`` for
    ``quarter=2025Q4`` on 2026-04-22 (run_id
    ``13f_holdings_quarter=2025Q4_20260422_200854``) that reset
    ``is_latest`` on tickerless rows and flipped the enriched
    population to FALSE.

Examples::

    # dry-run against staging (default; never writes)
    python3 scripts/rollback_run.py \\
        --run-id 13f_holdings_quarter=2025Q4_20260422_200854 \\
        --db data/13f_staging.duckdb

    # execute against staging
    python3 scripts/rollback_run.py \\
        --run-id 13f_holdings_quarter=2025Q4_20260422_200854 \\
        --db data/13f_staging.duckdb \\
        --confirm --i-understand-this-writes

    # execute against prod (Terminal-only per staging-write protocol)
    python3 scripts/rollback_run.py \\
        --run-id 13f_holdings_quarter=2025Q4_20260422_200854 \\
        --confirm --i-understand-this-writes --allow-prod
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


PROD_DB_BASENAME = "13f.duckdb"


def _is_prod_path(db_path: str) -> bool:
    """True if ``db_path`` resolves to the prod DB file name."""
    return os.path.basename(os.path.abspath(db_path)) == PROD_DB_BASENAME


def _load_manifest_row(con: Any, run_id: str) -> dict | None:
    row = con.execute(
        "SELECT manifest_id, source_type, fetch_status "
        "FROM ingestion_manifest WHERE run_id = ? "
        "ORDER BY manifest_id DESC LIMIT 1",
        [run_id],
    ).fetchone()
    if not row:
        return None
    return {
        "manifest_id": int(row[0]),
        "source_type": row[1],
        "fetch_status": row[2],
    }


def _impact_counts(con: Any, manifest_id: int) -> list[tuple[str, int]]:
    rows = con.execute(
        "SELECT unit_type, COUNT(*) "
        "FROM ingestion_impacts WHERE manifest_id = ? "
        "GROUP BY unit_type ORDER BY unit_type",
        [manifest_id],
    ).fetchall()
    return [(r[0], int(r[1])) for r in rows]


def _holdings_v2_quarter_report(con: Any, quarter: str) -> dict:
    """Pre/post state snapshot for a single quarter on holdings_v2.

    Reports the four cells of the is_latest × ticker matrix that the
    int-22 diagnosis used."""
    row = con.execute(
        "SELECT "
        "  SUM(CASE WHEN is_latest THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN is_latest AND ticker IS NULL THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN is_latest AND ticker IS NOT NULL THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN NOT is_latest THEN 1 ELSE 0 END), "
        "  COUNT(*) "
        "FROM holdings_v2 WHERE quarter = ?",
        [quarter],
    ).fetchone()  # nosec B608
    return {
        "is_latest_TRUE": int(row[0] or 0),
        "is_latest_TRUE_AND_ticker_NULL": int(row[1] or 0),
        "is_latest_TRUE_AND_ticker_NOT_NULL": int(row[2] or 0),
        "is_latest_FALSE": int(row[3] or 0),
        "total": int(row[4] or 0),
    }


def _print_report(label: str, rep: dict) -> None:
    print(f"  {label}")
    print(f"    is_latest=TRUE              : {rep['is_latest_TRUE']:>12,}")
    print(f"    is_latest=TRUE & ticker NULL: {rep['is_latest_TRUE_AND_ticker_NULL']:>12,}")
    print(f"    is_latest=TRUE & ticker set : {rep['is_latest_TRUE_AND_ticker_NOT_NULL']:>12,}")
    print(f"    is_latest=FALSE             : {rep['is_latest_FALSE']:>12,}")
    print(f"    total rows                  : {rep['total']:>12,}")


def _reporting_quarter_for(run_id: str) -> str | None:
    """Extract ``quarter=YYYYQN`` from run_id if present. Only used to
    scope the before/after reporting summary."""
    for part in run_id.split("_"):
        if part.startswith("quarter="):
            return part.split("=", 1)[1]
    return None


def _build_pipeline(source_type: str, db_path: str) -> Any:
    """Instantiate the pipeline for ``source_type`` pointed at ``db_path``."""
    # pylint: disable=import-outside-toplevel
    from pipeline.pipelines import PIPELINE_REGISTRY  # type: ignore[import-not-found]

    if source_type not in PIPELINE_REGISTRY:
        raise SystemExit(
            f"  ABORT: source_type {source_type!r} not in PIPELINE_REGISTRY. "
            f"Known: {sorted(PIPELINE_REGISTRY.keys())}"
        )
    entry = PIPELINE_REGISTRY[source_type]
    cls = entry() if callable(entry) and not isinstance(entry, type) else entry
    return cls(prod_db_path=db_path, staging_db_path=db_path)


def run(
    run_id: str,
    db_path: str,
    dry_run: bool,
    i_understand: bool,
    allow_prod: bool,
) -> int:
    if not os.path.exists(db_path):
        print(f"  ABORT: DB not found: {db_path}")
        return 2

    if not dry_run:
        if not i_understand:
            print(
                "  ABORT: --confirm without --i-understand-this-writes. "
                "This operation writes to the database; pass "
                "--i-understand-this-writes to proceed."
            )
            return 2
        if _is_prod_path(db_path) and not allow_prod:
            print(
                f"  ABORT: {db_path} resolves to the prod DB "
                f"({PROD_DB_BASENAME}) but --allow-prod was not passed. "
                "Prod writes from this wrapper require explicit opt-in."
            )
            return 2

    # ---- dry-run read-only probe -----------------------------------------
    ro = duckdb.connect(db_path, read_only=True)
    try:
        manifest = _load_manifest_row(ro, run_id)
        if manifest is None:
            print(f"  ABORT: run_id not found in ingestion_manifest: {run_id!r}")
            return 2

        status = manifest["fetch_status"]
        source_type = manifest["source_type"]
        manifest_id = manifest["manifest_id"]

        print(f"  DB           : {db_path}")
        print(f"  run_id       : {run_id}")
        print(f"  source_type  : {source_type}")
        print(f"  manifest_id  : {manifest_id}")
        print(f"  fetch_status : {status}")
        print(f"  mode         : {'dry-run' if dry_run else 'confirm'}")

        if status == "rolled_back":
            print(
                "  NOOP: run is already in 'rolled_back' status. "
                "Nothing to do."
            )
            return 0

        if status != "complete":
            print(
                f"  ABORT: rollback requires fetch_status='complete'; "
                f"current status is {status!r}."
            )
            return 2

        impacts = _impact_counts(ro, manifest_id)
        if not impacts:
            print(
                "  ABORT: no ingestion_impacts rows for this manifest. "
                "Rollback would be a no-op and cannot reverse anything."
            )
            return 2
        print("  impact summary:")
        for unit_type, n in impacts:
            print(f"    {unit_type:<20} {n:>10,}")

        quarter = _reporting_quarter_for(run_id)
        if quarter and source_type == "13f_holdings":
            pre = _holdings_v2_quarter_report(ro, quarter)
            print(f"  pre-state holdings_v2 quarter={quarter}:")
            _print_report("", pre)
    finally:
        ro.close()

    if dry_run:
        print("  DRY-RUN: no writes performed. Pass --confirm to execute.")
        return 0

    # ---- execute rollback ------------------------------------------------
    pipeline = _build_pipeline(source_type, db_path)
    print(f"  executing pipeline.rollback({run_id!r}) ...")
    pipeline.rollback(run_id)
    print("  rollback complete.")

    # ---- post-state report -----------------------------------------------
    ro = duckdb.connect(db_path, read_only=True)
    try:
        manifest = _load_manifest_row(ro, run_id)
        status = manifest["fetch_status"] if manifest else "unknown"
        print(f"  post status  : {status}")
        quarter = _reporting_quarter_for(run_id)
        if quarter and source_type == "13f_holdings":
            post = _holdings_v2_quarter_report(ro, quarter)
            print(f"  post-state holdings_v2 quarter={quarter}:")
            _print_report("", post)
    finally:
        ro.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id", required=True,
        help="run_id of the completed pipeline run to reverse.",
    )
    parser.add_argument(
        "--db", default=None,
        help="DB path. Defaults to data/13f.duckdb (prod).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report actions; no writes. Default when --confirm is absent.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Execute the rollback. Requires --i-understand-this-writes.",
    )
    parser.add_argument(
        "--i-understand-this-writes", action="store_true",
        dest="i_understand_this_writes",
        help="Explicit acknowledgement that --confirm writes to the DB.",
    )
    parser.add_argument(
        "--allow-prod", action="store_true",
        help=f"Permit writes when --db resolves to {PROD_DB_BASENAME}.",
    )
    args = parser.parse_args()

    if args.db is None:
        args.db = str(ROOT / "data" / "13f.duckdb")

    dry_run = not args.confirm
    return run(
        run_id=args.run_id,
        db_path=args.db,
        dry_run=dry_run,
        i_understand=args.i_understand_this_writes,
        allow_prod=args.allow_prod,
    )


if __name__ == "__main__":
    sys.exit(main())
