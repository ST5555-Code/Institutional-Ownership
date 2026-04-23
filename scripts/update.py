#!/usr/bin/env python3
"""
update.py — legacy master update script. Kept as a convenience wrapper
for a minimal, pre-staging-era pipeline. The canonical quarterly
orchestration lives in the top-level Makefile (`make quarterly-update`).

Run: python3 scripts/update.py

Sequence:
  1. pipeline/load_adv.py   — Stage SEC ADV data (w2-05; staging DB)
  2. fetch_13f.py           — Download 13F quarterly ZIPs
  3. load_13f.py            — Load 13F TSVs into DuckDB
  4. build_managers.py      — Build manager/parent tables
  5. build_cusip.py         — Build securities table
  6. pipeline/load_market.py — Pull yfinance market data
  7. auto_resolve.py        — Auto-resolve ticker gaps
  8. pipeline/load_nport.py — Stage N-PORT mutual fund holdings (w2-03)

Retired steps (removed from this script):
  - fetch_nport.py       → replaced by pipeline/load_nport.py (w2-03)
  - fetch_nport_v2.py    → replaced by pipeline/load_nport.py (w2-03)
  - fetch_adv.py         → replaced by pipeline/load_adv.py (w2-05)
  - promote_adv.py       → replaced by LoadADVPipeline.approve_and_promote
  - unify_positions.py   → retired; no longer part of the pipeline

ADV + N-PORT promotion (staging → prod) is not invoked here. Use the
admin refresh UI (or pipeline.approve_and_promote(run_id) in a REPL) to
promote once a staged run is reviewed.
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

    # load_adv is a framework pipeline — dispatch it directly rather
    # than via run_script so --staging lands in the staging DB.
    print(f"\n{'=' * 60}")
    print("Running pipeline/load_adv.py --staging...")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [sys.executable,
         os.path.join(SCRIPTS_DIR, "pipeline", "load_adv.py"),
         "--staging"],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print(f"\nPipeline stopped at load_adv.py (exit {result.returncode}).")
        sys.exit(1)

    steps = [
        "fetch_13f.py",
        "load_13f.py",
        "build_managers.py",
        "build_cusip.py",
        "pipeline/load_market.py",
    ]

    for script in steps:
        if not run_script(script):
            print(f"\nPipeline stopped at {script}.")
            sys.exit(1)

    # Auto-resolve new ticker gaps
    if not run_script("auto_resolve.py"):
        print("\nPipeline stopped at auto_resolve.py.")
        sys.exit(1)

    # Fetch N-PORT mutual fund holdings. load_nport.py is the w2-03
    # SourcePipeline subclass — DERA-bulk orchestrator by default, with
    # auto-discovery of missing quarters. --staging writes to the staging
    # DB; the admin approval UI promotes.
    print(f"\n{'=' * 60}")
    print("Running pipeline/load_nport.py --staging...")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [sys.executable,
         os.path.join(SCRIPTS_DIR, "pipeline", "load_nport.py"),
         "--staging"],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print(f"\nPipeline stopped at load_nport.py (exit {result.returncode}).")
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
