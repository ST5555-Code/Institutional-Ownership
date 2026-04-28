#!/usr/bin/env python3
"""
run_audits.py — single entry point for repo-wide audit / validation checks.

Wraps existing read-only audit scripts (validate_*, check_*, verify_*) in a
common runner that captures pass/fail/manual results, prints a summary table,
and returns a non-zero exit code if any check fails.

The wrapped scripts are NOT modified — each is invoked as a subprocess so its
own exit codes, logging, and side files (logs/*.json, logs/staging_diff_*.txt)
remain authoritative.

Usage:
  python3 scripts/run_audits.py            # run all checks against prod
  python3 scripts/run_audits.py --quick    # skip slow checks
  python3 scripts/run_audits.py --verbose  # show full subprocess stdout/stderr

Exit codes:
  0 — every check returned PASS or MANUAL
  1 — at least one check returned FAIL

See MAINTENANCE.md §"Running Audits" for descriptions and baseline results.
"""
from __future__ import annotations

import argparse
import subprocess  # nosec B404 — invoking trusted in-repo audit scripts
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


# (name, [argv after python3], slow?, description)
AUDITS: list[tuple[str, list[str], bool, str]] = [
    (
        "check_freshness",
        [str(SCRIPTS / "check_freshness.py")],
        False,
        "data_freshness staleness gate against prod",
    ),
    (
        "verify_migration_stamps",
        [str(SCRIPTS / "verify_migration_stamps.py"), "--prod"],
        False,
        "every migration file has a schema_versions row on prod",
    ),
    (
        "validate_classifications",
        [str(SCRIPTS / "validate_classifications.py")],
        False,
        "CUSIP / fund-class classification BLOCK + WARN gates on prod",
    ),
    (
        "validate_entities",
        [str(SCRIPTS / "validate_entities.py"), "--prod"],
        True,
        "entity MDM structural + semantic gates (writes logs/entity_validation_report.json)",
    ),
    (
        "validate_phase4",
        [str(SCRIPTS / "validate_phase4.py")],
        True,
        "Phase 4 holdings_v2 / fund_holdings_v2 parity gates",
    ),
]


def _classify(returncode: int, stdout: str) -> str:
    """Translate a subprocess exit code into PASS / FAIL / MANUAL.

    Convention across the wrapped scripts:
      0  → PASS
      1  → FAIL (non-structural / block / stale)
      2  → FAIL (structural — validate_entities only)
      Any 'MANUAL' token in stdout downgrades a 0 to MANUAL (validate_phase4
      reports manual review without changing exit code).
    """
    if returncode == 0:
        if "Manual review required" in stdout or "manual_review" in stdout.lower():
            return "MANUAL"
        return "PASS"
    return "FAIL"


def run_check(name: str, argv: list[str], verbose: bool) -> tuple[str, str, float, str]:
    """Run one audit. Returns (name, status, elapsed_s, detail)."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(  # nosec B603 — fixed argv from in-repo scripts
            [sys.executable, *argv],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(ROOT),
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return name, "FAIL", time.monotonic() - t0, f"runner exception: {e}"

    elapsed = time.monotonic() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    status = _classify(proc.returncode, stdout)

    if verbose:
        print(f"\n----- {name} stdout -----")
        print(stdout.rstrip())
        if stderr.strip():
            print(f"----- {name} stderr -----")
            print(stderr.rstrip())
        print(f"----- {name} exit={proc.returncode} -----\n")

    # Extract a one-line detail: prefer the last non-blank stdout line, else
    # the first non-blank stderr line, else the exit code.
    detail = ""
    for line in reversed(stdout.splitlines()):
        if line.strip():
            detail = line.strip()
            break
    if not detail:
        for line in stderr.splitlines():
            if line.strip():
                detail = line.strip()
                break
    if not detail:
        detail = f"exit={proc.returncode}"
    if len(detail) > 100:
        detail = detail[:97] + "..."

    return name, status, elapsed, detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--quick", action="store_true",
        help="Skip slow checks (validate_entities, validate_phase4).",
    )
    ap.add_argument(
        "--verbose", action="store_true",
        help="Print full stdout/stderr from each check.",
    )
    args = ap.parse_args()

    selected = [a for a in AUDITS if not (args.quick and a[2])]
    skipped = [a[0] for a in AUDITS if args.quick and a[2]]

    print("=" * 78)
    print(f"run_audits.py — {len(selected)} check(s)"
          + (f" (skipping {len(skipped)} slow: {', '.join(skipped)})" if skipped else ""))
    print("=" * 78)

    results: list[tuple[str, str, float, str]] = []
    for name, argv, _slow, desc in selected:
        print(f"\n→ {name}: {desc}")
        results.append(run_check(name, argv, args.verbose))
        last = results[-1]
        print(f"  {last[1]} ({last[2]:.1f}s) — {last[3]}")

    # Summary table
    print()
    print("=" * 78)
    print(f"{'Check':<28} {'Status':<8} {'Time':>8}  Detail")
    print("-" * 78)
    summary = {"PASS": 0, "FAIL": 0, "MANUAL": 0}
    for name, status, elapsed, detail in results:
        summary[status] = summary.get(status, 0) + 1
        det = detail if len(detail) <= 32 else detail[:29] + "..."
        print(f"{name:<28} {status:<8} {elapsed:>7.1f}s  {det}")
    print("-" * 78)
    print(
        f"Summary: PASS={summary['PASS']} FAIL={summary['FAIL']} "
        f"MANUAL={summary['MANUAL']}"
    )
    print("=" * 78)

    return 1 if summary["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
