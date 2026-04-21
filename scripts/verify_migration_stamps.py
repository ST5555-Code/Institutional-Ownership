#!/usr/bin/env python3
"""Verify every migration in `scripts/migrations/` has a row in
`schema_versions` on the target DB.

Mechanizes the `verify_migration_applied()` invariant referenced in
`docs/REMEDIATION_PLAN.md:111,324` (Phase 1 of mig-04). For each
`.py` file under `scripts/migrations/`, extracts a top-level
``VERSION = "..."`` constant (or falls back to the filename stem) and
asserts one row per migration in `schema_versions`.

Exit code 0 on full parity, 1 on any gap (with a printout of the
missing versions). Suitable for wiring into `make validate` or CI.

Usage::

    python3 scripts/verify_migration_stamps.py --prod
    python3 scripts/verify_migration_stamps.py --staging
    python3 scripts/verify_migration_stamps.py --both
    python3 scripts/verify_migration_stamps.py --path /abs/path.duckdb
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

import duckdb


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BASE_DIR, "scripts", "migrations")
PROD_DB = os.path.join(BASE_DIR, "data", "13f.duckdb")
STAGING_DB = os.path.join(BASE_DIR, "data", "13f_staging.duckdb")


def _extract_version_constant(path: str) -> str | None:
    """Return the string value of a top-level ``VERSION = "..."``
    assignment in `path`, or None if not present.

    Also accepts ``MIGRATION_VERSION = "..."`` (used by migration 003)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id not in ("VERSION", "MIGRATION_VERSION"):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


def expected_versions() -> list[str]:
    """Build the expected stamp set from `scripts/migrations/*.py`."""
    out: list[str] = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        if not name.endswith(".py"):
            continue
        if name.startswith("_") or name == "__init__.py":
            continue
        path = os.path.join(MIGRATIONS_DIR, name)
        version = _extract_version_constant(path) or os.path.splitext(name)[0]
        out.append(version)
    return out


def verify(db_path: str, label: str) -> int:
    """Verify one DB. Returns 0 on parity, 1 on any gap."""
    if not os.path.exists(db_path):
        print(f"[{label}] FAIL: {db_path} does not exist")
        return 1

    expected = expected_versions()
    con = duckdb.connect(db_path, read_only=True)
    try:
        row = con.execute(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = 'schema_versions'"
        ).fetchone()
        if not row:
            print(f"[{label}] FAIL: schema_versions table missing")
            return 1
        present = {
            r[0] for r in con.execute(
                "SELECT version FROM schema_versions"
            ).fetchall()
        }
    finally:
        con.close()

    missing = [v for v in expected if v not in present]
    extra = sorted(present - set(expected))

    print(f"[{label}] DB: {db_path}")
    print(f"[{label}] expected migrations ({len(expected)}):")
    for v in expected:
        mark = "OK" if v in present else "MISSING"
        print(f"[{label}]   {mark:<8s} {v}")

    if extra:
        print(f"[{label}] extra stamps in schema_versions (not in "
              f"migrations dir): {extra}")

    if missing:
        print(f"[{label}] FAIL: {len(missing)} missing stamp(s): {missing}")
        return 1
    print(f"[{label}] OK: all {len(expected)} migrations stamped")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--prod", action="store_true")
    target.add_argument("--staging", action="store_true")
    target.add_argument("--both", action="store_true")
    target.add_argument("--path", default=None)
    args = p.parse_args()

    if not (args.prod or args.staging or args.both or args.path):
        p.error("specify one of --prod / --staging / --both / --path")

    rc = 0
    if args.path:
        rc |= verify(args.path, "custom")
    if args.prod or args.both:
        rc |= verify(PROD_DB, "prod")
    if args.staging or args.both:
        rc |= verify(STAGING_DB, "staging")
    sys.exit(rc)


if __name__ == "__main__":
    main()
