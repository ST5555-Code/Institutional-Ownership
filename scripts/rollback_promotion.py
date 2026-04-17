#!/usr/bin/env python3
"""
rollback_promotion.py — list and restore production from named snapshots.

Promotion snapshots are created by promote_staging.py as
{table}_snapshot_{YYYYMMDD_HHMMSS} sibling tables in the production DB.
This script wraps the listing + restore so callers don't have to know
the naming convention.

Usage:
  python3 scripts/rollback_promotion.py --list
  python3 scripts/rollback_promotion.py --restore 20260410_143022
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402
import promote_staging  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list", action="store_true", help="list available snapshots")
    p.add_argument("--restore", metavar="SNAPSHOT_ID",
                   help="restore production from this snapshot")
    args = p.parse_args()

    if not args.list and not args.restore:
        p.print_help()
        sys.exit(1)

    if args.list:
        promote_staging.list_snapshots()
        return

    if args.restore:
        # Use the same restore path as promote_staging so behavior is identical
        promote_staging._log(f"=== ROLLBACK START — snapshot={args.restore} ===")  # pylint: disable=W0212  # internal access: sibling module shares the same log sink
        promote_staging.rollback(args.restore, list(db.ENTITY_TABLES))
        promote_staging._log("=== ROLLBACK DONE ===")  # pylint: disable=W0212  # internal access: sibling module shares the same log sink


if __name__ == "__main__":
    main()
