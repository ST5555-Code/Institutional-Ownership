#!/usr/bin/env python3
"""backfill_fund_strategy.py — PR-1a fund-strategy reconciliation.

Reconciles fund-level classification across `fund_universe` and
`fund_holdings_v2` so that `fund_strategy = fund_category` everywhere
and `is_actively_managed` is never NULL.

Three phases:

  Phase 1 — fund_universe legacy residuals (333 rows where
            fund_strategy ∈ {'active','passive','mixed'}). Set
            fund_strategy = fund_category and recompute
            is_actively_managed.

  Phase 2 — fund_universe SYN funds (658 rows where
            fund_strategy IS NULL or ''). Resolve from
            fund_holdings_v2 majority count, tiebreaker = most-recent
            quarter. Populate fund_strategy, fund_category, and
            is_actively_managed.

  Phase 3 — fund_holdings_v2 legacy residuals (~5.47M rows where
            fund_strategy ∈ {'active','passive','mixed'}). Set
            fund_strategy = fund_universe.fund_category via inner
            join.

Safety:
  - --dry-run is the DEFAULT. Writes require --confirm.
  - --orphan-policy controls handling of fund_holdings_v2 rows with
    no fund_universe match (currently 3,184 rows on
    series_id='UNKNOWN', all legacy `active`):
      skip   — leave legacy value intact (default; safe but leaves
               residuals; validate will fail post-condition)
      equity — map to canonical equivalents: active→equity,
               passive→index, mixed→balanced
      error  — abort if any orphans found
  - Phase 3 cannot use staging (fund_holdings_v2 is not mirrored to
    staging — only entity tables are). Phase 1 and Phase 2 work
    against either DB.
  - All UPDATEs are idempotent: re-running on a clean DB updates 0
    rows.

Usage:
  # Default dry-run, prod, default orphan policy
  python3 scripts/oneoff/backfill_fund_strategy.py

  # Dry-run on staging
  python3 scripts/oneoff/backfill_fund_strategy.py --staging

  # Execute on prod (requires explicit --confirm)
  python3 scripts/oneoff/backfill_fund_strategy.py --confirm

  # Subset to one phase
  python3 scripts/oneoff/backfill_fund_strategy.py --phase 1
  python3 scripts/oneoff/backfill_fund_strategy.py --phase 2
  python3 scripts/oneoff/backfill_fund_strategy.py --phase 3 --orphan-policy equity
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402

# Functional dependency: is_actively_managed = f(fund_strategy)
# Per nport_classification_scoping.md §1.1.
ACTIVELY_MANAGED_TRUE = ("equity", "balanced", "multi_asset")
ACTIVELY_MANAGED_FALSE = ("bond_or_other", "excluded", "final_filing", "index")
CANONICAL_VALUES = ACTIVELY_MANAGED_TRUE + ACTIVELY_MANAGED_FALSE
LEGACY_VALUES = ("active", "passive", "mixed")
LEGACY_TO_CANONICAL = {"active": "equity", "passive": "index", "mixed": "balanced"}


def _is_actively_managed_case_sql(col_expr: str) -> str:
    return (
        "CASE "
        f"WHEN {col_expr} IN {ACTIVELY_MANAGED_TRUE} THEN TRUE "
        f"WHEN {col_expr} IN {ACTIVELY_MANAGED_FALSE} THEN FALSE "
        "ELSE NULL END"
    )


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _hr(label: str) -> None:
    print()
    print("=" * 72)
    print(label)
    print("=" * 72)


def phase1(con, dry_run: bool) -> int:
    _hr("PHASE 1 — fund_universe legacy residuals")
    rows = con.execute(
        """
        SELECT fund_strategy, fund_category, COUNT(*) AS n
        FROM fund_universe
        WHERE fund_strategy IN ('active','passive','mixed')
        GROUP BY fund_strategy, fund_category ORDER BY fund_strategy, n DESC
        """
    ).fetchall()
    total = sum(r[2] for r in rows)
    print(f"  Found {total} legacy residuals:")
    for r in rows:
        print(f"    {r[0]:8s} -> {r[1]:14s} : {r[2]:>4d}")

    if total == 0:
        print("  Nothing to do (idempotent re-run).")
        return 0

    if dry_run:
        print("  DRY-RUN — no UPDATE issued.")
        return total

    case_sql = _is_actively_managed_case_sql("fund_category")
    con.execute(
        f"""
        UPDATE fund_universe
        SET fund_strategy = fund_category,
            is_actively_managed = {case_sql}
        WHERE fund_strategy IN ('active','passive','mixed')
        """
    )
    after = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IN ('active','passive','mixed')"
    ).fetchone()[0]
    print(f"  After UPDATE: {after} legacy residuals remain (expected 0).")
    return total


def phase2(con, dry_run: bool) -> int:
    _hr("PHASE 2 — fund_universe SYN funds (NULL/empty fund_strategy)")
    syn_count = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IS NULL OR fund_strategy = ''"
    ).fetchone()[0]
    print(f"  Found {syn_count} SYN funds with NULL/empty fund_strategy.")

    if syn_count == 0:
        print("  Nothing to do.")
        return 0

    # Build resolution table: majority count, tiebreaker most-recent quarter.
    con.execute("DROP TABLE IF EXISTS _syn_resolved_strategy")
    con.execute(
        """
        CREATE TEMP TABLE _syn_resolved_strategy AS
        WITH syn_funds AS (
          SELECT series_id FROM fund_universe
          WHERE fund_strategy IS NULL OR fund_strategy = ''
        ),
        holdings_counts AS (
          SELECT fh.series_id, fh.fund_strategy, COUNT(*) AS n_rows,
                 MAX(fh.quarter) AS latest_quarter
          FROM fund_holdings_v2 fh
          JOIN syn_funds sf USING (series_id)
          WHERE fh.fund_strategy IS NOT NULL AND fh.fund_strategy != ''
          GROUP BY fh.series_id, fh.fund_strategy
        ),
        ranked AS (
          SELECT series_id, fund_strategy, n_rows, latest_quarter,
                 ROW_NUMBER() OVER (
                   PARTITION BY series_id
                   ORDER BY n_rows DESC, latest_quarter DESC
                 ) AS rn
          FROM holdings_counts
        )
        SELECT series_id, fund_strategy AS resolved_strategy,
               n_rows, latest_quarter
        FROM ranked WHERE rn = 1
        """
    )
    distrib = con.execute(
        "SELECT resolved_strategy, COUNT(*) FROM _syn_resolved_strategy GROUP BY resolved_strategy ORDER BY COUNT(*) DESC"
    ).fetchall()
    resolved = sum(r[1] for r in distrib)
    print(f"  Resolved {resolved}/{syn_count} via majority count + most-recent tiebreaker:")
    for r in distrib:
        print(f"    {r[0]:18s} : {r[1]:>4d}")

    unresolved = syn_count - resolved
    if unresolved:
        print(f"  WARNING: {unresolved} SYN funds have no holdings to resolve from.")

    if dry_run:
        print("  DRY-RUN — no UPDATE issued.")
        return resolved

    case_sql = _is_actively_managed_case_sql("r.resolved_strategy")
    con.execute(
        f"""
        UPDATE fund_universe
        SET fund_strategy = r.resolved_strategy,
            fund_category = r.resolved_strategy,
            is_actively_managed = {case_sql}
        FROM _syn_resolved_strategy r
        WHERE fund_universe.series_id = r.series_id
        """
    )
    after = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IS NULL OR fund_strategy = ''"
    ).fetchone()[0]
    print(f"  After UPDATE: {after} SYN funds remain unresolved (expected {unresolved}).")
    return resolved


def phase3(con, dry_run: bool, orphan_policy: str) -> int:
    _hr("PHASE 3 — fund_holdings_v2 legacy residuals")

    # Confirm STOP-condition: no unexpected legacy values.
    canonical_tup = CANONICAL_VALUES + LEGACY_VALUES
    placeholders = "(" + ",".join(f"'{v}'" for v in canonical_tup) + ")"
    unexpected = con.execute(
        f"""
        SELECT fund_strategy, COUNT(*) AS rows_affected, COUNT(DISTINCT series_id) AS funds
        FROM fund_holdings_v2
        WHERE fund_strategy NOT IN {placeholders}
          AND fund_strategy IS NOT NULL AND fund_strategy != ''
        GROUP BY fund_strategy ORDER BY rows_affected DESC
        """
    ).fetchall()
    if unexpected:
        print("  STOP — unexpected legacy values found:")
        for r in unexpected:
            print(f"    {r[0]!r:18s} : rows={r[1]:>10,d}  funds={r[2]:>5d}")
        print("  Aborting Phase 3. Investigate before proceeding.")
        raise SystemExit(2)

    by_legacy = con.execute(
        """
        SELECT fund_strategy, COUNT(*) AS rows_affected, COUNT(DISTINCT series_id) AS funds
        FROM fund_holdings_v2
        WHERE fund_strategy IN ('active','passive','mixed')
        GROUP BY fund_strategy ORDER BY rows_affected DESC
        """
    ).fetchall()
    total_legacy = sum(r[1] for r in by_legacy)
    print(f"  Found {total_legacy:,d} legacy rows:")
    for r in by_legacy:
        print(f"    {r[0]:8s} : rows={r[1]:>10,d}  funds={r[2]:>5d}")

    if total_legacy == 0:
        print("  Nothing to do.")
        return 0

    # Orphan check: rows with no fund_universe join target.
    orphan_rows = con.execute(
        """
        SELECT fh.series_id, fh.fund_strategy, COUNT(*) AS rows
        FROM fund_holdings_v2 fh
        LEFT JOIN fund_universe fu USING (series_id)
        WHERE fh.fund_strategy IN ('active','passive','mixed')
          AND fu.series_id IS NULL
        GROUP BY fh.series_id, fh.fund_strategy
        ORDER BY rows DESC
        """
    ).fetchall()
    orphan_total = sum(r[2] for r in orphan_rows)
    if orphan_total:
        print(f"  Orphan rows (no fund_universe match): {orphan_total:,d}")
        for r in orphan_rows[:10]:
            print(f"    series_id={r[0]!s:12s} legacy={r[1]:8s} rows={r[2]:>6,d}")
        if orphan_policy == "error":
            print("  --orphan-policy=error — aborting.")
            raise SystemExit(3)

    if dry_run:
        print("  DRY-RUN — no UPDATE issued.")
        return total_legacy

    # Main UPDATE: inner-join semantics via UPDATE ... FROM.
    con.execute(
        """
        UPDATE fund_holdings_v2 AS fh
        SET fund_strategy = fu.fund_category
        FROM fund_universe AS fu
        WHERE fh.series_id = fu.series_id
          AND fh.fund_strategy IN ('active','passive','mixed')
          AND fu.fund_category IS NOT NULL AND fu.fund_category != ''
        """
    )
    main_after = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE fund_strategy IN ('active','passive','mixed')"
    ).fetchone()[0]
    print(f"  After main UPDATE: {main_after:,d} legacy rows remain.")

    # Orphan policy: equity → blanket-map remaining legacy values.
    if orphan_policy == "equity" and main_after:
        for legacy_val, canonical_val in LEGACY_TO_CANONICAL.items():
            con.execute(
                "UPDATE fund_holdings_v2 SET fund_strategy = ? WHERE fund_strategy = ?",
                [canonical_val, legacy_val],
            )
        post_orphan = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 WHERE fund_strategy IN ('active','passive','mixed')"
        ).fetchone()[0]
        print(f"  After orphan map (active→equity etc.): {post_orphan:,d} remain.")

    return total_legacy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    db_grp = parser.add_mutually_exclusive_group()
    db_grp.add_argument("--prod", action="store_true", help="Target prod DB (default).")
    db_grp.add_argument("--staging", action="store_true", help="Target staging DB.")
    db_grp.add_argument("--db-path", help="Explicit DB path (overrides --prod/--staging).")
    parser.add_argument("--confirm", action="store_true", help="Execute UPDATEs (default is dry-run).")
    parser.add_argument("--phase", choices=("1", "2", "3", "all"), default="all")
    parser.add_argument(
        "--orphan-policy",
        choices=("skip", "equity", "error"),
        default="skip",
        help="Phase 3 handling of rows with no fund_universe match.",
    )
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        db_path = STAGING_DB if args.staging else PROD_DB
    dry_run = not args.confirm

    if args.staging and args.phase in ("3", "all"):
        # fund_holdings_v2 is not mirrored to staging.
        from contextlib import suppress
        with suppress(Exception):
            con_chk = duckdb.connect(db_path, read_only=True)
            try:
                con_chk.execute("SELECT 1 FROM fund_holdings_v2 LIMIT 1")
            except Exception:
                print(
                    "ERROR: fund_holdings_v2 is not present in staging — Phase 3 cannot be "
                    "smoke-tested there. Run Phase 1/2 against staging if desired, then run "
                    "all phases against prod with --confirm. Re-run with --phase 1 or "
                    "--phase 2 to scope to staging-compatible work.",
                    file=sys.stderr,
                )
                return 4
            finally:
                con_chk.close()

    target = "prod" if not args.staging else "staging"
    mode = "DRY-RUN" if dry_run else "WRITE"
    _log(f"target={target}  db={db_path}  mode={mode}  phase={args.phase}  orphan_policy={args.orphan_policy}")

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        if args.phase in ("1", "all"):
            phase1(con, dry_run)
        if args.phase in ("2", "all"):
            phase2(con, dry_run)
        if args.phase in ("3", "all"):
            phase3(con, dry_run, args.orphan_policy)
        if not dry_run:
            con.execute("CHECKPOINT")
            _log("CHECKPOINT complete.")
    finally:
        con.close()

    if dry_run:
        print()
        _log("Dry-run complete. Re-run with --confirm to execute.")
    else:
        print()
        _log("Backfill complete. Run validate_fund_strategy_backfill.py to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
