#!/usr/bin/env python3
"""close_fund_typed_ech_apply.py — final PR in the
fund-typed-ech-cleanup workstream.

Closes every open entity_classification_history row whose entity is
typed 'fund'. After --confirm, ECH carries zero fund-typed open rows.
Fund classification reads route entirely through
fund_universe.fund_strategy via classify_fund_strategy() (PR #264).
Writer paths gated against fund-typed targets in PR #263.

Modes:
  --dry-run (default) — emit rollback manifest CSV with the full
                        row state of every open fund-typed ECH row.
                        No DB writes. Refuses if any open fund-typed
                        rows exist outside {active, passive, unknown}.
  --confirm           — single-transaction SCD close. Pre-execution and
                        post-execution guards must all pass or
                        ROLLBACK. Hard-fails the run if cohort drifted
                        from the manifest count, if institution-side
                        baseline shifted, or if any fund-typed open
                        rows remain post-update.

Outputs:
  data/working/close-fund-typed-ech-manifest.csv

Refs:
  docs/decisions/d4-classification-precedence.md
  docs/findings/fund-typed-ech-audit.md (PR #262)
  docs/findings/disable-fund-typed-ech-writers.md (PR #263)
  docs/findings/migrate-fund-typed-ech-readers.md (PR #264)
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "close-fund-typed-ech-manifest.csv"

ALLOWED_CLS = {"active", "passive", "unknown"}


def fetch_open_fund_rows(con):
    return con.execute(
        """
        SELECT ech.entity_id,
               e.canonical_name,
               e.entity_type,
               ech.classification,
               ech.is_activist,
               ech.confidence,
               ech.source,
               ech.is_inferred,
               ech.valid_from,
               ech.valid_to
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'fund'
          AND ech.valid_to = DATE '9999-12-31'
        ORDER BY ech.entity_id
        """
    ).fetchall()


def count_institution_open(con):
    return con.execute(
        """
        SELECT COUNT(*)
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'institution'
          AND ech.valid_to = DATE '9999-12-31'
        """
    ).fetchone()[0]


def count_fund_open(con):
    return con.execute(
        """
        SELECT COUNT(*)
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'fund'
          AND ech.valid_to = DATE '9999-12-31'
        """
    ).fetchone()[0]


def count_fund_closed_today(con):
    return con.execute(
        """
        SELECT COUNT(*)
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'fund'
          AND ech.valid_to = CURRENT_DATE
        """
    ).fetchone()[0]


def write_manifest(rows, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "entity_id",
            "canonical_name",
            "entity_type",
            "classification",
            "is_activist",
            "confidence",
            "source",
            "is_inferred",
            "valid_from",
            "valid_to",
        ])
        for r in rows:
            w.writerow(r)


def assert_manifest_invariants(rows) -> None:
    if not rows:
        raise SystemExit("manifest gate: zero open fund-typed ECH rows found — nothing to do")
    bad_type = [r for r in rows if r[2] != "fund"]
    if bad_type:
        raise SystemExit(f"manifest gate: {len(bad_type)} rows with entity_type != 'fund'")
    bad_open = [r for r in rows if str(r[9]) != "9999-12-31"]
    if bad_open:
        raise SystemExit(f"manifest gate: {len(bad_open)} rows with valid_to != 9999-12-31")
    bad_cls = [r for r in rows if r[3] not in ALLOWED_CLS]
    if bad_cls:
        sample = ", ".join(sorted({str(r[3]) for r in bad_cls}))
        raise SystemExit(
            f"manifest gate: {len(bad_cls)} rows with classification outside "
            f"{sorted(ALLOWED_CLS)} (saw: {sample})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True,
                   help="default: build manifest, no DB writes")
    g.add_argument("--confirm", action="store_true",
                   help="execute single-transaction SCD close")
    parser.add_argument("--db-path", default=str(DEFAULT_DB),
                        help=f"path to 13f.duckdb (default: {DEFAULT_DB})")
    parser.add_argument("--manifest", default=str(MANIFEST_CSV),
                        help=f"manifest CSV path (default: {MANIFEST_CSV})")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: db not found at {db_path}", file=sys.stderr)
        return 2
    manifest_path = Path(args.manifest)

    if args.confirm:
        return run_confirm(db_path, manifest_path)
    return run_dry_run(db_path, manifest_path)


def run_dry_run(db_path: Path, manifest_path: Path) -> int:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = fetch_open_fund_rows(con)
        institution_baseline = count_institution_open(con)
    finally:
        con.close()

    assert_manifest_invariants(rows)
    write_manifest(rows, manifest_path)

    by_cls = {"active": 0, "passive": 0, "unknown": 0}
    for r in rows:
        by_cls[r[3]] = by_cls.get(r[3], 0) + 1

    print("=== close-fund-typed-ech-rows DRY RUN ===")
    print(f"  manifest written: {manifest_path}")
    print(f"  total open fund-typed ECH rows: {len(rows)}")
    for cls in ("active", "passive", "unknown"):
        print(f"    {cls}: {by_cls.get(cls, 0)}")
    print(f"  institution-side open ECH baseline: {institution_baseline}")
    print(f"  manifest invariants: PASS")
    print("  next step: rerun with --confirm after backup is in place")
    return 0


def run_confirm(db_path: Path, manifest_path: Path) -> int:
    if not manifest_path.exists():
        print(f"ERROR: manifest not found at {manifest_path}; run --dry-run first",
              file=sys.stderr)
        return 2

    with manifest_path.open() as f:
        manifest_rows = list(csv.DictReader(f))
    manifest_count = len(manifest_rows)
    if manifest_count == 0:
        print("ERROR: manifest is empty", file=sys.stderr)
        return 2

    con = duckdb.connect(str(db_path), read_only=False)
    try:
        pre_fund = count_fund_open(con)
        pre_inst = count_institution_open(con)

        print("=== close-fund-typed-ech-rows EXECUTE ===")
        print(f"  manifest count:                  {manifest_count}")
        print(f"  pre-execution fund-typed open:   {pre_fund}")
        print(f"  pre-execution institution open:  {pre_inst}")

        if pre_fund != manifest_count:
            raise SystemExit(
                f"PRE-GUARD FAIL: live fund-typed open count {pre_fund} != "
                f"manifest {manifest_count} (cohort drifted between dry-run and confirm)"
            )

        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                """
                UPDATE entity_classification_history
                  SET valid_to = CURRENT_DATE
                WHERE entity_id IN (
                    SELECT entity_id FROM entities WHERE entity_type = 'fund'
                  )
                  AND valid_to = DATE '9999-12-31'
                """
            )

            post_fund = count_fund_open(con)
            post_inst = count_institution_open(con)
            post_closed_today = count_fund_closed_today(con)

            print(f"  post-execution fund-typed open:  {post_fund}")
            print(f"  post-execution institution open: {post_inst}")
            print(f"  fund-typed rows closed today:    {post_closed_today}")

            if post_fund != 0:
                raise RuntimeError(
                    f"POST-GUARD FAIL: {post_fund} fund-typed open rows remain"
                )
            if post_inst != pre_inst:
                raise RuntimeError(
                    f"POST-GUARD FAIL: institution open count drifted "
                    f"{pre_inst} -> {post_inst}"
                )
            if post_closed_today != manifest_count:
                raise RuntimeError(
                    f"POST-GUARD FAIL: closed-today count {post_closed_today} != "
                    f"manifest {manifest_count}"
                )

            print("  all guards: PASS")
            con.execute("COMMIT")
            print("  COMMITTED")
        except Exception as exc:
            con.execute("ROLLBACK")
            print(f"  ROLLED BACK: {exc}", file=sys.stderr)
            return 3
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
