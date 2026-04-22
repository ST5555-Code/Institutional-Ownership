#!/usr/bin/env python3
"""
update.py — legacy master update script. Kept as a convenience wrapper
for a minimal, pre-staging-era pipeline. The canonical quarterly
orchestration lives in the top-level Makefile (`make quarterly-update`).

Run: python3 scripts/update.py

Sequence:
  1. fetch_adv.py       — Stage SEC ADV data (staging DB; prints run_id)
  2. fetch_13f.py       — Download 13F quarterly ZIPs
  3. load_13f.py        — Load 13F TSVs into DuckDB
  4. build_managers.py  — Build manager/parent tables
  5. build_cusip.py     — Build securities table
  6. fetch_market.py    — Pull yfinance market data
  7. auto_resolve.py    — Auto-resolve ticker gaps
  8. fetch_nport_v2.py  — Stage N-PORT mutual fund holdings

Retired steps (removed from this script):
  - fetch_nport.py       → replaced by fetch_nport_v2.py
  - unify_positions.py   → retired; no longer part of the pipeline

ADV + N-PORT promotion (staging → prod) is not invoked here; run
`make promote-adv RUN_ID=<id>` (and validate_nport + promote_nport)
separately after inspecting the staged run.
"""

import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")


def run_script(name):
    """Run a script and return success/failure."""
    path = os.path.join(SCRIPTS_DIR, name)
    print(f"\n{'=' * 60}")
    print(f"Running {name}...")
    print(f"{'=' * 60}")
    result = subprocess.run([sys.executable, path], cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"\nERROR: {name} failed with exit code {result.returncode}")
        return False
    return True


def main():
    print("=" * 60)
    print("13-F OWNERSHIP DATABASE — Full Update")
    print("=" * 60)

    steps = [
        "fetch_adv.py",
        "fetch_13f.py",
        "load_13f.py",
        "build_managers.py",
        "build_cusip.py",
        "fetch_market.py",
    ]

    for script in steps:
        if not run_script(script):
            print(f"\nPipeline stopped at {script}.")
            sys.exit(1)

    # Auto-resolve new ticker gaps
    if not run_script("auto_resolve.py"):
        print("\nPipeline stopped at auto_resolve.py.")
        sys.exit(1)

    # Fetch N-PORT mutual fund holdings (staging). fetch_nport_v2.py is the
    # DERA-bulk orchestrator — it auto-detects missing quarters, so no
    # --quarter flag is passed (and none is accepted).
    print(f"\n{'=' * 60}")
    print("Running fetch_nport_v2.py --staging...")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "fetch_nport_v2.py"),
         "--staging"],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print(f"\nPipeline stopped at fetch_nport_v2.py (exit {result.returncode}).")
        sys.exit(1)

    # Notify if pending overrides exist
    import pandas as pd
    pending_path = os.path.join(BASE_DIR, "data", "reference", "ticker_overrides_pending.csv")
    if os.path.exists(pending_path):
        df = pd.read_csv(pending_path)
        if len(df) > 0:
            print(f"\n{len(df)} overrides pending review.")
            print("Run: python3 scripts/approve_overrides.py")

    print("\nUpdate complete.")


if __name__ == "__main__":
    main()
