#!/usr/bin/env python3
"""
promote_staging.py — promote staging entity tables to production atomically.

Workflow:
  1. Refuse to run without --approved (hard gate; the diff must have been
     reviewed by a human first).
  2. Snapshot every entity table to {table}_snapshot_{timestamp} inside
     production. Snapshots are intra-DB so rollback is a single SQL pass.
  3. Apply staging → production via DELETE-then-INSERT against the diff
     PK set per table. No full table replace.
  4. Reset entity sequences to MAX(id)+1 of the merged production state.
  5. Run validate_entities.py against production. If any structural gate
     fails, automatically restore from the snapshot taken in step 2.
  6. Append a summary to logs/promotion_history.log.

Usage:
  python3 scripts/promote_staging.py --approved
  python3 scripts/promote_staging.py --approved --rollback 20260410_143022
  python3 scripts/promote_staging.py --list-snapshots
  python3 scripts/promote_staging.py --tables entity_relationships,entity_rollup_history --approved
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

PROMOTION_LOG = ROOT / "logs" / "promotion_history.log"

# Primary key columns per entity table — used to compute the diff PK
# set and to drive DELETE/INSERT during apply.
PK_COLUMNS = {
    "entities": ["entity_id"],
    "entity_identifiers": ["entity_id", "identifier_type", "identifier_value", "valid_from"],
    "entity_relationships": ["relationship_id"],
    "entity_aliases": ["entity_id", "alias_name", "valid_from"],
    "entity_classification_history": ["entity_id", "valid_from"],
    "entity_rollup_history": ["entity_id", "rollup_type", "valid_from"],
    "entity_identifiers_staging": ["staging_id"],
    "entity_relationships_staging": ["id"],
    "entity_overrides_persistent": ["override_id"],
}


def _log(msg: str) -> None:
    PROMOTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(PROMOTION_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _snapshot_name(table: str, sid: str) -> str:
    return f"{table}_snapshot_{sid}"


def _take_snapshot(con, snapshot_id: str, tables: list[str]) -> None:
    _log(f"  taking snapshot {snapshot_id} ...")
    for t in tables:
        snap = _snapshot_name(t, snapshot_id)
        con.execute(f"DROP TABLE IF EXISTS {snap}")
        con.execute(f"CREATE TABLE {snap} AS SELECT * FROM {t}")
        n = con.execute(f"SELECT COUNT(*) FROM {snap}").fetchone()[0]
        _log(f"    snapshot {snap}: {n} rows")


def _restore_snapshot(con, snapshot_id: str, tables: list[str]) -> None:
    _log(f"  RESTORING from snapshot {snapshot_id} ...")
    # Reverse order so child tables drop first (FK-safe)
    for t in reversed(tables):
        snap = _snapshot_name(t, snapshot_id)
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [snap],
        ).fetchone()[0]
        if not exists:
            _log(f"    WARN: no snapshot for {t} ({snap}) — skipping")
            continue
        con.execute(f"DELETE FROM {t}")
    for t in tables:
        snap = _snapshot_name(t, snapshot_id)
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [snap],
        ).fetchone()[0]
        if not exists:
            continue
        con.execute(f"INSERT INTO {t} SELECT * FROM {snap}")
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        _log(f"    {t}: restored {n} rows")
    _reset_sequences(con)


def _reset_sequences(con) -> None:
    """DROP + CREATE the sequence at MAX(id)+1. DuckDB does not support
    ALTER SEQUENCE ... RESTART WITH N. Safe in prod because nextval() is
    only called explicitly by application code (entity_sync.py); none of
    the entity tables in prod's degraded schema use sequence DEFAULTs."""
    for seq, table, col in db.ENTITY_SEQUENCES:
        try:
            # Skip silently if the underlying table is missing in prod
            exists = con.execute(
                "SELECT COUNT(*) FROM duckdb_tables() "
                "WHERE database_name = current_database() AND table_name = ?",
                [table],
            ).fetchone()[0]
            if not exists:
                continue
            row = con.execute(
                f"SELECT COALESCE(MAX({col}), 0) + 1 FROM {table}"
            ).fetchone()
            next_val = int(row[0]) if row and row[0] is not None else 1
            con.execute(f"DROP SEQUENCE IF EXISTS {seq}")
            con.execute(f"CREATE SEQUENCE {seq} START WITH {next_val}")
            _log(f"    sequence {seq} restart with {next_val}")
        except Exception as e:
            _log(f"    sequence {seq}: WARN {e}")


def list_snapshots() -> None:
    import duckdb

    con = duckdb.connect(db.PROD_DB, read_only=True)
    rows = con.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name LIKE '%_snapshot_%'
        ORDER BY table_name
        """
    ).fetchall()
    con.close()
    if not rows:
        print("No snapshots found in production DB.")
        return
    # Group by snapshot_id (the part after the last _snapshot_)
    groups: dict[str, list[str]] = {}
    for (name,) in rows:
        idx = name.find("_snapshot_")
        if idx < 0:
            continue
        sid = name[idx + len("_snapshot_") :]
        groups.setdefault(sid, []).append(name[:idx])
    print(f"Snapshots in {db.PROD_DB}:")
    for sid in sorted(groups.keys(), reverse=True):
        tables = sorted(groups[sid])
        print(f"  {sid}  ({len(tables)} tables)")
        for t in tables:
            print(f"    - {t}")


def _apply_table(con, table: str) -> dict:
    """Apply staging → production for one table via diff-based DELETE+INSERT."""
    pk = PK_COLUMNS[table]
    pk_csv = ", ".join(pk)
    pk_join = " AND ".join(f"prod.{c} = stg.{c}" for c in pk)

    # 1. Find PKs in prod that are NOT in staging → delete
    deleted = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT {pk_csv} FROM {table}
          EXCEPT
          SELECT {pk_csv} FROM stg.{table}
        )
        """
    ).fetchone()[0]
    if deleted:
        con.execute(
            f"""
            DELETE FROM {table}
            WHERE ({pk_csv}) IN (
              SELECT {pk_csv} FROM {table}
              EXCEPT
              SELECT {pk_csv} FROM stg.{table}
            )
            """
        )

    # 2. Find rows where PK matches but content differs → DELETE+INSERT
    #    (we use EXCEPT on the full row, then re-INSERT below)
    modified = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT * FROM stg.{table}
          EXCEPT
          SELECT * FROM {table}
        ) s
        WHERE EXISTS (
          SELECT 1 FROM {table} prod
          WHERE {' AND '.join(f'prod.{c} = s.{c}' for c in pk)}
        )
        """
    ).fetchone()[0]
    if modified:
        con.execute(
            f"""
            DELETE FROM {table}
            WHERE ({pk_csv}) IN (
              SELECT {pk_csv} FROM (
                SELECT * FROM stg.{table}
                EXCEPT
                SELECT * FROM {table}
              ) s
              WHERE EXISTS (
                SELECT 1 FROM {table} p
                WHERE {' AND '.join(f'p.{c} = s.{c}' for c in pk)}
              )
            )
            """
        )

    # 3. Find PKs in staging not in prod (now includes the just-deleted modified rows) → insert
    added_or_replaced = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT {pk_csv} FROM stg.{table}
          EXCEPT
          SELECT {pk_csv} FROM {table}
        )
        """
    ).fetchone()[0]
    if added_or_replaced:
        con.execute(
            f"""
            INSERT INTO {table}
            SELECT * FROM stg.{table}
            WHERE ({pk_csv}) IN (
              SELECT {pk_csv} FROM stg.{table}
              EXCEPT
              SELECT {pk_csv} FROM {table}
            )
            """
        )

    return {
        "deleted": deleted,
        "modified": modified,
        "inserted_or_replaced": added_or_replaced,
        "added_only": added_or_replaced - modified,
    }


def promote(tables: list[str], snapshot_id: str) -> dict:
    import duckdb

    if not os.path.exists(db.PROD_DB):
        raise RuntimeError(f"Production DB not found: {db.PROD_DB}")
    if not os.path.exists(db.STAGING_DB):
        raise RuntimeError(f"Staging DB not found: {db.STAGING_DB}")

    con = duckdb.connect(db.PROD_DB)
    con.execute(f"ATTACH '{db.STAGING_DB}' AS stg (READ_ONLY)")

    # Skip any tables that don't exist in prod (e.g.,
    # entity_overrides_persistent, declared in schema but never created
    # in production). They cannot be snapshotted or promoted into.
    # The primary connection's database name is the file basename ('13f'),
    # not 'main' — use current_database() to filter portably.
    existing_in_prod = {
        r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name = current_database()"
        ).fetchall()
    }
    skipped = [t for t in tables if t not in existing_in_prod]
    if skipped:
        for t in skipped:
            _log(f"  SKIP {t}: not present in production (cannot promote)")
        tables = [t for t in tables if t in existing_in_prod]

    summary = {"snapshot_id": snapshot_id, "tables": {}}
    try:
        # Step 2 — snapshot
        _take_snapshot(con, snapshot_id, tables)

        # Step 3 — apply changes inside one transaction so the
        # whole promotion is atomic from prod's point of view
        _log(f"  applying staging → production ...")
        con.execute("BEGIN TRANSACTION")
        try:
            for t in tables:
                stats = _apply_table(con, t)
                summary["tables"][t] = stats
                _log(
                    f"    {t}: deleted={stats['deleted']}  "
                    f"modified={stats['modified']}  "
                    f"added={stats['added_only']}"
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        # Step 4 — sequence reset
        _reset_sequences(con)

    finally:
        con.execute("DETACH stg")
        con.close()

    # Step 5 — validate (subprocess so it gets a fresh connection
    # and clean staging-mode state).
    #
    # validate_entities.py exit codes:
    #   0 = all gates PASS
    #   1 = at least one non-structural gate FAILed (do NOT auto-rollback;
    #       these gates can have transient or expected failures, and a
    #       human should decide whether they block this promotion)
    #   2 = at least one STRUCTURAL gate FAILed (auto-rollback — the DB
    #       is in a logically broken state)
    _log("  running validate_entities.py against production ...")
    result = subprocess.run(
        [sys.executable, "-u", "scripts/validate_entities.py", "--prod"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    summary["validate_returncode"] = result.returncode
    summary["validate_stdout_tail"] = "\n".join(result.stdout.splitlines()[-20:])

    if result.returncode == 0:
        _log("  validation PASSED (all gates green)")
    elif result.returncode == 1:
        _log("  validation: non-structural FAILs present (NOT auto-rolling back)")
        _log("    review logs/entity_validation_report.json before next session")
        for line in result.stdout.splitlines()[-6:]:
            if line.strip():
                _log(f"    {line}")
    elif result.returncode == 2:
        _log(f"  validation: STRUCTURAL FAILURE (rc=2) — auto-restoring snapshot")
        for line in result.stdout.splitlines()[-6:]:
            if line.strip():
                _log(f"    {line}")
        con = duckdb.connect(db.PROD_DB)
        try:
            con.execute("BEGIN TRANSACTION")
            try:
                _restore_snapshot(con, snapshot_id, tables)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
        _log("  rollback complete; production restored to pre-promotion state")
        summary["restored"] = True
    else:
        _log(f"  validation: unexpected exit code {result.returncode} — leaving promotion in place")

    return summary


def rollback(snapshot_id: str, tables: list[str]) -> None:
    import duckdb

    con = duckdb.connect(db.PROD_DB)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            _restore_snapshot(con, snapshot_id, tables)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--approved", action="store_true",
                   help="REQUIRED. Confirms human review of diff_staging.py output.")
    p.add_argument("--tables", default=None,
                   help="comma-separated subset of entity tables (default: all)")
    p.add_argument("--rollback", metavar="SNAPSHOT_ID",
                   help="restore production from the named snapshot")
    p.add_argument("--list-snapshots", action="store_true",
                   help="list snapshot tables in production DB")
    args = p.parse_args()

    if args.list_snapshots:
        list_snapshots()
        return

    if args.tables:
        requested = [t.strip() for t in args.tables.split(",") if t.strip()]
        invalid = [t for t in requested if t not in db.ENTITY_TABLES]
        if invalid:
            print(f"ERROR: unknown entity tables: {invalid}", file=sys.stderr)
            sys.exit(2)
        tables = requested
    else:
        tables = list(db.ENTITY_TABLES)

    if args.rollback:
        if not args.approved:
            print("ERROR: --rollback also requires --approved.", file=sys.stderr)
            sys.exit(2)
        _log(f"=== ROLLBACK START — snapshot={args.rollback} ===")
        rollback(args.rollback, tables)
        _log("=== ROLLBACK DONE ===")
        return

    if not args.approved:
        print(
            "ERROR: --approved is required. The staging diff MUST be reviewed "
            "by a human before promotion.",
            file=sys.stderr,
        )
        sys.exit(2)

    snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log(f"=== PROMOTE START — snapshot_id={snapshot_id} tables={len(tables)} ===")
    summary = promote(tables, snapshot_id)

    if summary.get("restored"):
        _log("=== PROMOTE FAILED — production restored from snapshot ===")
        sys.exit(1)

    total_changes = sum(
        s["deleted"] + s["modified"] + s["added_only"]
        for s in summary["tables"].values()
    )
    _log(f"=== PROMOTE DONE — snapshot_id={snapshot_id} total_changes={total_changes} ===")


if __name__ == "__main__":
    main()
