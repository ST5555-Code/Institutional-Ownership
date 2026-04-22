#!/usr/bin/env python3
"""
apply_ticker_override_triage.py — apply Serge's triage decisions to
data/reference/ticker_overrides.csv.

Reads the completed triage CSV (with a `decision` column populated as
KEEP / FIX / REMOVE and an optional `corrected_ticker`), then rewrites
ticker_overrides.csv in-place:

  * KEEP   → row unchanged
  * FIX    → row's `correct_ticker` set to `corrected_ticker`
  * REMOVE → row dropped

Default is --dry-run. Pass --confirm to write back.

Usage:
    python scripts/oneoff/apply_ticker_override_triage.py [--triage PATH] [--confirm]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OVERRIDES = REPO_ROOT / "data" / "reference" / "ticker_overrides.csv"
DEFAULT_TRIAGE = Path.home() / "Downloads" / "ticker_override_triage.csv"

OVERRIDE_COLS = [
    "cusip",
    "wrong_ticker",
    "correct_ticker",
    "company_name",
    "note",
    "security_type_override",
    "method",
    "auto_applied",
]


def load_triage(path: Path) -> dict[str, dict]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    by_cusip: dict[str, dict] = {}
    for r in rows:
        cusip = r["cusip"]
        if cusip in by_cusip:
            raise SystemExit(f"Duplicate CUSIP in triage CSV: {cusip}")
        by_cusip[cusip] = r
    return by_cusip


def load_overrides(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != OVERRIDE_COLS:
            raise SystemExit(
                f"Unexpected overrides header: {reader.fieldnames}\nExpected: {OVERRIDE_COLS}"
            )
        return list(reader)


def apply(overrides: list[dict], triage: dict[str, dict]) -> tuple[list[dict], list[tuple], list[tuple], int]:
    kept = 0
    fixed: list[tuple] = []
    removed: list[tuple] = []
    out: list[dict] = []

    for row in overrides:
        cusip = row["cusip"]
        decision_row = triage.get(cusip)
        if decision_row is None:
            raise SystemExit(f"Overrides CUSIP not in triage: {cusip}")
        decision = (decision_row.get("decision") or "").strip().upper()

        if decision == "KEEP":
            kept += 1
            out.append(row)
        elif decision == "FIX":
            corrected = (decision_row.get("corrected_ticker") or "").strip()
            if not corrected:
                raise SystemExit(f"FIX row missing corrected_ticker: {cusip}")
            old = row["correct_ticker"]
            new_row = dict(row)
            new_row["correct_ticker"] = corrected
            fixed.append((cusip, old, corrected, row["company_name"]))
            out.append(new_row)
        elif decision == "REMOVE":
            removed.append((cusip, row["correct_ticker"], row["company_name"]))
        else:
            raise SystemExit(f"Unknown decision '{decision}' for CUSIP {cusip}")

    return out, fixed, removed, kept


def write_overrides(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OVERRIDE_COLS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    p.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    p.add_argument("--confirm", action="store_true", help="write changes (default: dry-run)")
    args = p.parse_args()

    if not args.triage.exists():
        print(f"Triage CSV not found: {args.triage}", file=sys.stderr)
        return 2
    if not args.overrides.exists():
        print(f"Overrides CSV not found: {args.overrides}", file=sys.stderr)
        return 2

    triage = load_triage(args.triage)
    overrides = load_overrides(args.overrides)

    triage_cusips = set(triage.keys())
    override_cusips = {r["cusip"] for r in overrides}
    missing_in_triage = override_cusips - triage_cusips
    extra_in_triage = triage_cusips - override_cusips
    if missing_in_triage:
        raise SystemExit(f"CUSIPs in overrides but not triage: {sorted(missing_in_triage)}")
    if extra_in_triage:
        print(f"WARN: {len(extra_in_triage)} triage CUSIPs not in overrides (ignored)")

    out_rows, fixed, removed, kept = apply(overrides, triage)

    mode = "APPLY" if args.confirm else "DRY-RUN"
    print(f"[{mode}] triage={args.triage}")
    print(f"[{mode}] overrides={args.overrides}")
    print(f"[{mode}] input rows: {len(overrides)}   output rows: {len(out_rows)}")
    print(f"[{mode}] kept={kept}  fixed={len(fixed)}  removed={len(removed)}")

    if fixed:
        print("\nFIX:")
        for cusip, old, new, name in fixed:
            print(f"  {cusip}  correct_ticker: {old!r} -> {new!r}   ({name})")
    if removed:
        print("\nREMOVE:")
        for cusip, ticker, name in removed:
            print(f"  {cusip}  ticker={ticker!r}   ({name})")

    if args.confirm:
        write_overrides(args.overrides, out_rows)
        print(f"\nWrote {len(out_rows)} rows -> {args.overrides}")
    else:
        print("\nDry-run only. Pass --confirm to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
