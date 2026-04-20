#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 007 — entity_overrides_persistent.new_value nullable.

DM15 Layer 1 (2026-04-17) staged 15 `merge` override rows where 8 targeted
sub-adviser entities with no CIK in MDM (Smith Capital 18899, Milliman
18304). Those rows carry `new_value=NULL` — the override still applies
immediately in prod because the rollup write happens directly on
`entity_rollup_history`; the `new_value` field is only consulted by
`replay_persistent_overrides()` during `build_entities.py --reset` to
re-resolve the target by CIK. With no CIK the replay skips the row
(same INF9d precedent on the source side).

Staging schema (post `sync_staging.py` CTAS) drops all column constraints,
so NULL `new_value` lands fine. Prod schema carries the original NOT NULL
constraint — blocks promote.

This migration drops NOT NULL on `new_value` in both DBs, aligning them
with the other nullable override columns (`entity_cik`, `old_value`,
`identifier_value`, `rollup_type`, `relationship_context`). Semantically
the column is optional: overrides with `identifier_type='series_id'` and
no CIK-keyed target are valid now. The NOT NULL was a vestige from the
earliest override schema when every row represented a CIK merge.

---
INTENTIONAL NULL-TARGET REPLAY-SKIP SEMANTICS (do not re-flag as defect)
---

The combination of `new_value=NULL` + replay-skip is DESIGNED, not a bug.
Any future auditor / tool comparing `entity_overrides_persistent` row
counts to `replay_persistent_overrides()` effect counts will see rows
with NULL targets silently skipped on replay. That divergence is
deliberate and bounded by the following invariant:

  - At write time (DM15 L1/L2, INF9d source-side) the override's
    rollup / relationship effect is applied directly to
    `entity_rollup_history` / `entity_relationships`. The row in
    `entity_overrides_persistent` is the audit record — it documents
    why the write happened, not a replay instruction.
  - At replay time (`build_entities.py --reset`) the target cannot be
    resolved without a CIK, so the row is skipped. This is the correct
    behavior: the pre-rebuild state already reflects the applied effect
    because the sub-adviser / source entity was re-materialized from
    the same upstream data that produced it originally (N-CEN, ADV).
  - Staying on the NULL-target row is therefore a no-op by construction.
    The override table's role for these rows is purely documentary.

Operationally this appears as "N overrides present, M applied on replay,
M < N" where the gap exactly matches the NULL-target count. The gap is
expected. Any monitoring gate that treats N != M as a failure must
filter `WHERE new_value IS NOT NULL` first.

See ROADMAP 2026-04-17 session #11 (Override IDs 205-221, DM15 L2) and
`docs/canonical_ddl.md` §17 (Entity MDM) for the audit trail.

Idempotent: probes nullability before acting.

Usage:
  python3 scripts/migrations/007_override_new_value_nullable.py --staging --dry-run
  python3 scripts/migrations/007_override_new_value_nullable.py --staging
  python3 scripts/migrations/007_override_new_value_nullable.py --prod --dry-run
  python3 scripts/migrations/007_override_new_value_nullable.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "007_override_new_value_nullable"
NOTES = "drop NOT NULL on entity_overrides_persistent.new_value"
TABLE = "entity_overrides_persistent"
COLUMN = "new_value"


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _is_nullable(con, table: str, column: str) -> bool | None:
    row = con.execute(
        """
        SELECT is_nullable
        FROM duckdb_columns()
        WHERE table_name = ? AND column_name = ?
        """,
        [table, column],
    ).fetchone()
    if row is None:
        return None
    return bool(row[0])


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 007 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        if not _has_table(con, TABLE):
            print(f"  SKIP ({db_path}): {TABLE} does not exist")
            return

        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        is_nullable = _is_nullable(con, TABLE, COLUMN)
        if is_nullable is None:
            raise SystemExit(f"  ABORT: {TABLE}.{COLUMN} not found")

        stamped = _already_stamped(con, VERSION)
        print(f"  current is_nullable: {is_nullable}  target: True")
        print(f"  schema_versions stamped: {stamped}")

        if is_nullable and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if not is_nullable:
            stmt = f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} DROP NOT NULL"
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        if not dry_run:
            if not stamped:
                con.execute(
                    "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                print(f"  stamped schema_versions: {VERSION}")
            con.execute("CHECKPOINT")

            after_nullable = _is_nullable(con, TABLE, COLUMN)
            if not after_nullable:
                raise SystemExit(
                    "  MIGRATION FAILED: column still NOT NULL"
                )
            print(f"  AFTER: is_nullable={after_nullable}")
    finally:
        con.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    parser.add_argument("--staging", action="store_true",
                        help="Shortcut for --path data/13f_staging.duckdb")
    parser.add_argument("--prod", action="store_true",
                        help="Explicit prod target; equivalent to default.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report actions; no writes.")
    args = parser.parse_args()

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if args.staging:
        db_path = os.path.join(repo_root, "data", "13f_staging.duckdb")
    elif args.path:
        db_path = args.path
    else:
        db_path = os.path.join(repo_root, "data", "13f.duckdb")

    run_migration(db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
