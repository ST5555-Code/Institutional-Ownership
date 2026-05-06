"""Read-only helper: load PENDING_CP5_5 cohort from extended Bundle C inventory.

Used by recon (PR #305) to confirm 9-row cohort and per-feature distribution
without drift since PR #304.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

INVENTORY = Path(__file__).resolve().parents[2] / "data/working/cp-5-bundle-c-readers-extended.csv"


def load_pending() -> list[dict]:
    with INVENTORY.open() as f:
        return [r for r in csv.DictReader(f) if r["migration_status"] == "PENDING_CP5_5"]


def main() -> int:
    rows = load_pending()
    print(f"PENDING_CP5_5 count: {len(rows)}")
    print(f"feature distribution: {dict(Counter(r['feature'] for r in rows))}")
    for r in rows:
        print(f"  {r['file']}:{r['line']} | fn={r['function']} | feature={r['feature']}")
    return 0 if len(rows) == 9 else 1


if __name__ == "__main__":
    sys.exit(main())
