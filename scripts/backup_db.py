#!/usr/bin/env python3
"""
backup_db.py — full DuckDB EXPORT DATABASE snapshot of 13f.duckdb.

Used as a belt-and-suspenders safety net around any risky entity
mutation. Backups are stored under data/backups/ as DuckDB EXPORT
DATABASE directories (one per snapshot, fully self-contained).

Backups run MANUALLY, not on a schedule. Every invocation prompts for
confirmation before doing anything (because EXPORT DATABASE scans the
whole DB and writes ~3 GB of parquet — not something you want triggered
by accident). Pass --no-confirm to bypass the prompt for scripted /
automated runs.

When to back up:
  - Before any DM13 / DM14 / DM15 audit pass
  - Before Stage 5 cleanup (on or after 2026-05-09)
  - Before any non-routine entity migration
  - At analyst discretion before risky manual edits

Usage:
  python3 scripts/backup_db.py                   # take a backup (prompts)
  python3 scripts/backup_db.py --no-confirm      # skip prompt (scripted)
  python3 scripts/backup_db.py --list            # list existing backups
  python3 scripts/backup_db.py --staging         # back up the staging DB
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

BACKUP_ROOT = ROOT / "data" / "backups"


def _format_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f}{unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f}TB"


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def list_backups() -> None:
    if not BACKUP_ROOT.exists():
        print("No backups directory yet.")
        return
    rows = []
    for d in sorted(BACKUP_ROOT.iterdir()):
        if not d.is_dir():
            continue
        size = _dir_size(d)
        mtime = datetime.fromtimestamp(d.stat().st_mtime)
        rows.append((d.name, _format_size(size), mtime.strftime("%Y-%m-%d %H:%M")))
    if not rows:
        print(f"No backups under {BACKUP_ROOT}")
        return
    print(f"Backups under {BACKUP_ROOT}:")
    print(f"{'name':<40}  {'size':>10}  {'created':<20}")
    print("-" * 76)
    for name, size, mtime in rows:
        print(f"{name:<40}  {size:>10}  {mtime:<20}")


def confirm_backup(backup_dir: Path, src_size_gb: float) -> None:
    """Interactive confirmation prompt before any backup. Bypassed by --no-confirm."""
    print(f"About to create full DB backup at: {backup_dir}")
    print(f"  source size:    ~{src_size_gb:.1f} GB")
    print(f"  this scans the entire DB and writes ~{src_size_gb * 0.4:.1f} GB of parquet")
    response = input("Confirm backup? (yes/no): ").strip().lower()
    if response != "yes":
        print("Backup cancelled.")
        sys.exit(0)


def take_backup(staging: bool, no_confirm: bool) -> Path:
    import duckdb

    src = db.STAGING_DB if staging else db.PROD_DB
    label = "13f_staging" if staging else "13f"
    if not os.path.exists(src):
        print(f"ERROR: source DB not found: {src}", file=sys.stderr)
        sys.exit(2)

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_ROOT / f"{label}_backup_{ts}"
    if dest.exists():
        print(f"ERROR: backup directory already exists: {dest}", file=sys.stderr)
        sys.exit(2)

    src_size_gb = os.path.getsize(src) / (1024 ** 3)
    if not no_confirm:
        confirm_backup(dest, src_size_gb)

    print(f"Backing up {src} → {dest}")
    print("(EXPORT DATABASE — this scans the entire DB; please wait)")
    try:
        con = duckdb.connect(src, read_only=True)
        # EXPORT DATABASE writes a directory with schema + per-table parquet files
        con.execute(f"EXPORT DATABASE '{dest}' (FORMAT PARQUET)")
        con.close()
    except Exception:
        # Clean up partial directory on failure
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise

    size = _format_size(_dir_size(dest))
    print(f"Backup complete: {dest}  ({size})")
    return dest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list", action="store_true", help="list existing backups")
    p.add_argument("--staging", action="store_true",
                   help="back up the staging DB instead of production")
    p.add_argument("--no-confirm", action="store_true",
                   help="bypass the interactive confirmation prompt "
                        "(for scripted / automated use)")
    args = p.parse_args()

    if args.list:
        list_backups()
        return
    take_backup(staging=args.staging, no_confirm=args.no_confirm)


if __name__ == "__main__":
    main()
