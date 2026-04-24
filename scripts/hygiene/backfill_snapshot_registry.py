#!/usr/bin/env python3
"""
backfill_snapshot_registry.py — populate ``snapshot_registry`` from the
existing ``%_snapshot_%`` corpus inside a DuckDB file.

Intended as a **one-off migration companion** to run immediately after
``018_snapshot_registry.py`` lands the sidecar table. Re-running is
safe (idempotent on ``snapshot_table_name`` PK via INSERT OR IGNORE).

Backfill rules (see ``docs/findings/2026-04-24-snapshot-inventory.md``
and the ``snapshot-policy`` session memo):

  * ``snapshot_table_name`` — literal discovered name.
  * ``base_table`` — everything before the last ``_snapshot_``.
  * ``created_at`` — parsed from the name suffix. Accepts two forms:
      ``YYYYMMDD_HHMMSS`` (promote_staging.py, 290 rows) and ``YYYYMMDD``
      (the 2 one-off holdings_v2 snapshots). Unparseable suffixes fall
      back to the DuckDB catalog table-creation time.
  * ``created_by`` / ``purpose`` — inferred from the creation-site map
    below (centralized in ``CREATION_SITES``).
  * ``applied_policy`` — ``carve_out`` for the 2 holdings_v2 V2-cutover
    snapshots (approver=Serge, expiration=2026-05-31, purpose "V2
    cutover insurance"). All other rows get ``default_14d`` with
    ``expiration = created_at::DATE + 14 days``.

Usage::

    python3 scripts/hygiene/backfill_snapshot_registry.py --dry-run
    python3 scripts/hygiene/backfill_snapshot_registry.py --apply
    python3 scripts/hygiene/backfill_snapshot_registry.py --path <db> --apply

The script refuses to proceed if ``snapshot_registry`` does not exist —
run migration 018 first.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

import duckdb


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "13f.duckdb")

SEP = "_snapshot_"

# Carve-out declaration for the 2 V2 cutover insurance snapshots.
# See session memo: approved by Serge 2026-04-24, retained through the
# Q1 2026 cycle close per ROADMAP Phase B2.5 gate.
CARVE_OUTS: dict[str, dict] = {
    "holdings_v2_manager_type_legacy_snapshot_20260419": {
        "created_by": "scripts/retired/snapshot_manager_type_legacy.py",
        "purpose": "V2 cutover insurance — pre-phase-4 manager_type legacy reference",
        "expiration": date(2026, 5, 31),
        "approver": "Serge",
        "applied_policy": "carve_out",
        "notes": "Commit c2c2bac; full 12.27M-row copy of holdings_v2 pre-COALESCE apply.",
    },
    "holdings_v2_pct_of_so_pre_apply_snapshot_20260419": {
        "created_by": "pct_of_so Phase 4b apply (inline session script)",
        "purpose": "V2 cutover insurance — pre-apply pct_of_so reference",
        "expiration": date(2026, 5, 31),
        "approver": "Serge",
        "applied_policy": "carve_out",
        "notes": "Commit 5cea20c; full 12.27M-row copy of holdings_v2 pre-pct-of-so apply.",
    },
}

DEFAULT_RETENTION_DAYS = 14


def _parse_suffix(suffix: str) -> datetime | None:
    """Parse the timestamp suffix emitted by the snapshot creation sites.

    Accepts ``YYYYMMDD_HHMMSS`` (the ``promote_staging.py`` format) and
    ``YYYYMMDD`` (the retired one-off holdings_v2 scripts). Returns
    ``None`` if neither format matches.
    """
    for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(suffix, fmt)
        except ValueError:
            continue
    return None


def _split_name(name: str) -> tuple[str, str] | None:
    """Split a snapshot table name into ``(base_table, suffix)``.

    Uses the **last** occurrence of ``_snapshot_`` as the split point so
    base tables containing ``_snapshot_`` themselves (none today, but
    forward-compatible) parse correctly.
    """
    idx = name.rfind(SEP)
    if idx < 0:
        return None
    return name[:idx], name[idx + len(SEP):]


def _fallback_created_at() -> datetime:
    """Fallback timestamp when the snapshot name suffix cannot be parsed.

    DuckDB 1.4.x exposes no public column for per-table creation time
    (``duckdb_tables()`` / ``information_schema.tables`` / ``duckdb_databases()``
    all omit it), so we return ``now()`` — a valid value that will
    expire 14 days out under the default policy. In practice no
    2026-04-24 snapshot hits this branch (all 292 parse cleanly); this
    path is insurance against future name-format drift.
    """
    return datetime.now()


def discover_snapshots(con) -> list[tuple[str, str, datetime, bool]]:
    """Return ``[(name, base, created_at, parsed_ok), ...]`` for every
    ``%_snapshot_%`` table in the main schema.
    """
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE '%_snapshot_%' "
        "ORDER BY table_name"
    ).fetchall()

    out: list[tuple[str, str, datetime, bool]] = []
    for (name,) in rows:
        parts = _split_name(name)
        if parts is None:
            out.append((name, name, _fallback_created_at(), False))
            continue
        base, suffix = parts
        ts = _parse_suffix(suffix)
        if ts is None:
            out.append((name, base, _fallback_created_at(), False))
        else:
            out.append((name, base, ts, True))
    return out


def build_row(name: str, base: str, created_at: datetime, parsed_ok: bool) -> dict:
    """Derive the full registry row payload for a discovered snapshot."""
    if name in CARVE_OUTS:
        row = dict(CARVE_OUTS[name])
        row.update({
            "snapshot_table_name": name,
            "base_table": base,
            "created_at": created_at,
        })
        return row

    # Default path: treat as promote_staging.py TOOL-AUTO output.
    expiration = (created_at.date() + timedelta(days=DEFAULT_RETENTION_DAYS))
    notes = None if parsed_ok else (
        "Timestamp suffix unparseable; created_at set to backfill run time."
    )
    return {
        "snapshot_table_name": name,
        "base_table": base,
        "created_at": created_at,
        "created_by": "scripts/promote_staging.py",
        "purpose": "Pre-promote rollback snapshot",
        "expiration": expiration,
        "approver": None,
        "applied_policy": "default_14d",
        "notes": notes,
    }


INSERT_SQL = """
INSERT OR IGNORE INTO snapshot_registry (
    snapshot_table_name, base_table, created_at, created_by,
    purpose, expiration, approver, applied_policy, notes
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def run(db_path: str, apply_mode: bool) -> int:
    if not os.path.exists(db_path):
        print(f"  ABORT: {db_path} does not exist", file=sys.stderr)
        return 2

    con = duckdb.connect(db_path, read_only=not apply_mode)
    try:
        table_present = con.execute(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = 'snapshot_registry'"
        ).fetchone()
        if not table_present:
            print(
                "  ABORT: snapshot_registry missing. "
                "Run scripts/migrations/018_snapshot_registry.py first.",
                file=sys.stderr,
            )
            return 3

        discovered = discover_snapshots(con)
        print(f"  discovered: {len(discovered)} snapshot tables")

        by_policy = {"default_14d": 0, "carve_out": 0}
        unparseable = []
        rows_to_insert = []

        for name, base, created_at, parsed_ok in discovered:
            row = build_row(name, base, created_at, parsed_ok)
            by_policy[row["applied_policy"]] = by_policy.get(row["applied_policy"], 0) + 1
            if not parsed_ok:
                unparseable.append(name)
            rows_to_insert.append(row)

        print(f"  default_14d: {by_policy.get('default_14d', 0)}")
        print(f"  carve_out:   {by_policy.get('carve_out', 0)}")
        if unparseable:
            print(f"  unparseable timestamps: {len(unparseable)}")
            for n in unparseable:
                print(f"    {n}")

        if not apply_mode:
            print("  DRY-RUN: no writes performed")
            return 0

        con.execute("BEGIN TRANSACTION")
        try:
            for row in rows_to_insert:
                con.execute(
                    INSERT_SQL,
                    [
                        row["snapshot_table_name"],
                        row["base_table"],
                        row["created_at"],
                        row["created_by"],
                        row["purpose"],
                        row["expiration"],
                        row["approver"],
                        row["applied_policy"],
                        row["notes"],
                    ],
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("CHECKPOINT")

        final = con.execute("SELECT COUNT(*) FROM snapshot_registry").fetchone()[0]
        print(f"  snapshot_registry row count AFTER: {final}")
        return 0
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DEFAULT_DB,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Report planned inserts; no writes. (Default if --apply not passed.)")
    mode.add_argument("--apply", action="store_true",
                      help="Execute the inserts.")
    args = parser.parse_args()

    apply_mode = bool(args.apply)  # default = dry-run
    sys.exit(run(args.path, apply_mode=apply_mode))


if __name__ == "__main__":
    main()
