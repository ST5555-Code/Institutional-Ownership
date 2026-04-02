#!/usr/bin/env python3
"""
update.py — Master update script. Runs the full data pipeline in order.

Run: python3 scripts/update.py

Sequence:
  1. fetch_adv.py      — Download SEC ADV data
  2. fetch_13f.py      — Download 13F quarterly ZIPs
  3. load_13f.py       — Load into DuckDB
  4. build_managers.py  — Build manager/parent tables
  5. build_cusip.py     — Build securities table
  6. fetch_market.py    — Pull yfinance market data
  7. auto_resolve.py    — Auto-resolve ticker gaps
  8. fetch_nport.py     — Download N-PORT mutual fund holdings
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

    # Fetch N-PORT mutual fund holdings for latest quarter
    import duckdb
    db_path = os.path.join(BASE_DIR, "data", "13f.duckdb")
    try:
        con = duckdb.connect(db_path, read_only=True)
        latest_quarter = con.execute("SELECT MAX(quarter) FROM holdings").fetchone()[0]
        con.close()
    except Exception:
        latest_quarter = None
    if not latest_quarter:
        print("\nERROR: Could not determine latest quarter from holdings table.")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"Running fetch_nport.py --quarter {latest_quarter}...")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "fetch_nport.py"),
         "--quarter", latest_quarter],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print(f"\nPipeline stopped at fetch_nport.py (exit {result.returncode}).")
        sys.exit(1)

    # Unify positions table (merges 13F + N-PORT)
    if not run_script("unify_positions.py"):
        print("\nPipeline stopped at unify_positions.py.")
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
