#!/usr/bin/env python3
"""
snapshot_retention.py — enforce the snapshot retention policy.

Drops expired ``%_snapshot_%`` tables recorded in
``snapshot_registry`` and prunes stale registry rows whose underlying
table is gone. Default mode is ``--dry-run`` (report-only); ``--apply``
is required for any DDL or DELETE.

Policy (authoritative: ``docs/findings/2026-04-24-snapshot-inventory.md``
+ the ``snapshot-policy`` session memo):

  * Default retention: 14 days from ``created_at`` (encoded per-row in
    ``snapshot_registry.expiration`` by the backfill / creation path).
  * Carve-outs are declared at creation with an ``approver``, explicit
    ``expiration``, and ``applied_policy='carve_out'``. Carve-outs are
    only dropped once their ``expiration`` is ``<= today()``.
  * Unregistered snapshots (present in DB, absent from registry) are
    reported but **never auto-deleted** — the operator decides.
  * Stale registrations (present in registry, absent from DB) are
    silently pruned so the registry stays aligned with reality.

Exit codes:
  * ``0`` — clean run (dry-run or apply).
  * ``2`` — DB path missing.
  * ``3`` — ``snapshot_registry`` missing (run migration 018 first).
  * ``1`` — any unexpected exception.

Usage::

    python3 scripts/hygiene/snapshot_retention.py --dry-run   # default
    python3 scripts/hygiene/snapshot_retention.py --apply
    python3 scripts/hygiene/snapshot_retention.py --path <db> --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import duckdb


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "13f.duckdb")


def _log(msg: str) -> None:
    """All operational output goes to stderr so stdout stays available
    for structured consumers if we add any later. Flush each line so
    tails render in real time under ``tee`` / CI log streams."""
    print(msg, file=sys.stderr, flush=True)


def _registry_rows(con) -> list[dict]:
    rows = con.execute(
        "SELECT snapshot_table_name, base_table, created_at, created_by, "
        "purpose, expiration, approver, applied_policy "
        "FROM snapshot_registry "
        "ORDER BY snapshot_table_name"
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "snapshot_table_name": r[0],
            "base_table": r[1],
            "created_at": r[2],
            "created_by": r[3],
            "purpose": r[4],
            "expiration": r[5],
            "approver": r[6],
            "applied_policy": r[7],
        })
    return out


def _db_snapshots(con) -> set[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE '%_snapshot_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _today() -> date:
    return date.today()


def _effective_expiration(row: dict) -> date:
    """Return the expiration date for ``row``.

    Canonical path: ``expiration`` column is always populated by the
    backfill and creation-site tagging. This function exists to
    centralize the "no expiration = 14-day default" fallback for any
    future row that slips through without one.
    """
    if row["expiration"] is not None:
        return row["expiration"]
    # 14-day default from created_at
    from datetime import timedelta
    return row["created_at"].date() + timedelta(days=14)


def classify(con) -> dict:
    """Partition registered snapshots into ``would_delete`` / ``retained``
    plus report ``unregistered`` and ``stale_registration`` sets.

    Returns a dict with five keys:
      * ``would_delete`` — list of dicts, expiration <= today.
      * ``retained``     — list of dicts, expiration > today.
      * ``unregistered`` — list of table names (in DB, absent from registry).
      * ``stale_registration`` — list of dicts (in registry, absent from DB).
      * ``today``        — the reference date.
    """
    today = _today()
    registry = _registry_rows(con)
    db_names = _db_snapshots(con)
    registry_names = {r["snapshot_table_name"] for r in registry}

    would_delete: list[dict] = []
    retained: list[dict] = []
    stale_registration: list[dict] = []

    for row in registry:
        exp = _effective_expiration(row)
        if row["snapshot_table_name"] not in db_names:
            stale_registration.append(row)
            continue
        if exp <= today:
            would_delete.append(row)
        else:
            retained.append(row)

    unregistered = sorted(db_names - registry_names)
    return {
        "would_delete": would_delete,
        "retained": retained,
        "unregistered": unregistered,
        "stale_registration": stale_registration,
        "today": today,
    }


def _fmt_retained(row: dict, today: date) -> str:
    exp = _effective_expiration(row)
    days = (exp - today).days
    return (
        f"RETAIN {row['snapshot_table_name']} "
        f"(policy={row['applied_policy']}, expires={exp}, "
        f"{days}d remaining)"
    )


def _fmt_would_delete(row: dict) -> str:
    exp = _effective_expiration(row)
    return (
        f"WOULD DELETE {row['snapshot_table_name']} "
        f"(base={row['base_table']}, created={row['created_at']}, "
        f"purpose={row['purpose']!r}, expired={exp})"
    )


def run(db_path: str, apply_mode: bool) -> int:
    if not os.path.exists(db_path):
        _log(f"ABORT: {db_path} does not exist")
        return 2

    con = duckdb.connect(db_path, read_only=not apply_mode)
    try:
        table_present = con.execute(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = 'snapshot_registry'"
        ).fetchone()
        if not table_present:
            _log(
                "ABORT: snapshot_registry missing. "
                "Run scripts/migrations/018_snapshot_registry.py first."
            )
            return 3

        report = classify(con)
        today = report["today"]

        _log(f"snapshot_retention @ {today}  (mode={'APPLY' if apply_mode else 'DRY-RUN'})")
        _log(f"  DB: {db_path}")
        _log("")

        for row in report["would_delete"]:
            _log(f"  {_fmt_would_delete(row)}")

        for row in report["retained"]:
            _log(f"  {_fmt_retained(row, today)}")

        for name in report["unregistered"]:
            _log(
                f"  UNREGISTERED {name} "
                "(present in DB, absent from registry — not deleted)"
            )

        for row in report["stale_registration"]:
            _log(
                f"  STALE_REGISTRATION {row['snapshot_table_name']} "
                "(in registry, table missing)"
            )

        _log("")
        _log(
            "  SUMMARY: "
            f"{len(report['would_delete'])} would-delete, "
            f"{len(report['retained'])} retained, "
            f"{len(report['unregistered'])} unregistered, "
            f"{len(report['stale_registration'])} stale-registration"
        )

        if not apply_mode:
            _log("  DRY-RUN: no writes performed")
            return 0

        deleted = 0
        pruned = 0
        con.execute("BEGIN TRANSACTION")
        try:
            for row in report["would_delete"]:
                name = row["snapshot_table_name"]
                con.execute(f'DROP TABLE IF EXISTS "{name}"')  # nosec B608
                con.execute(
                    "DELETE FROM snapshot_registry WHERE snapshot_table_name = ?",
                    [name],
                )
                deleted += 1
                _log(f"  DELETED {name}")

            for row in report["stale_registration"]:
                name = row["snapshot_table_name"]
                con.execute(
                    "DELETE FROM snapshot_registry WHERE snapshot_table_name = ?",
                    [name],
                )
                pruned += 1
                _log(f"  PRUNED stale registry row: {name}")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("CHECKPOINT")

        _log("")
        _log(
            f"  APPLY: deleted={deleted}, pruned_registry={pruned}, "
            f"retained={len(report['retained'])}, "
            f"unregistered={len(report['unregistered'])}"
        )
        return 0
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DEFAULT_DB,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Report actions; no DDL or deletes. (Default.)")
    mode.add_argument("--apply", action="store_true",
                      help="Execute DROP TABLE + registry DELETE for expired snapshots.")
    args = parser.parse_args()

    apply_mode = bool(args.apply)  # default = dry-run
    sys.exit(run(args.path, apply_mode=apply_mode))


if __name__ == "__main__":
    main()
