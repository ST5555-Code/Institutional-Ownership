#!/usr/bin/env python3
"""
benchmark.py — Time each pipeline stage and report results.

Run: python3 scripts/benchmark.py              # Time all stages (dry run — reports only)
     python3 scripts/benchmark.py --run         # Actually run each stage and time it
"""

import argparse
import os
import subprocess
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STAGES = [
    ("pipeline/load_adv.py --staging", "Download SEC ADV data (w2-05)"),
    ("fetch_13f.py", "Download 13F quarterly ZIPs"),
    ("load_13f.py", "Load TSVs into DuckDB"),
    ("build_managers.py", "Build manager/parent tables"),
    ("build_cusip.py", "Build securities table (OpenFIGI + yfinance)"),
    ("fetch_market.py", "Pull yfinance market data"),
    ("auto_resolve.py", "Auto-resolve ticker gaps"),
    ("fetch_nport.py --quarter 2025Q4", "Download N-PORT mutual fund holdings"),
    ("compute_flows.py", "Compute investor flow analytics"),
    ("unify_positions.py", "Merge 13F + N-PORT into positions table"),
    ("build_summaries.py", "Build materialized summary tables"),
]


def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds / 3600:.1f}h"


def check_stage(script_name):
    """Check if a script exists and is runnable."""
    path = os.path.join(BASE_DIR, "scripts", script_name.split()[0])
    return os.path.exists(path)


def run_stage(script_cmd):
    """Run a pipeline stage and return (success, elapsed_seconds)."""
    parts = script_cmd.split()
    script = parts[0]
    args = parts[1:] if len(parts) > 1 else []
    path = os.path.join(BASE_DIR, "scripts", script)

    t0 = time.time()
    result = subprocess.run(
        ["python3", path] + args,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0
    return result.returncode == 0, elapsed


def main():
    parser = argparse.ArgumentParser(description="Benchmark pipeline stages")
    parser.add_argument("--run", action="store_true", help="Actually run each stage")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"Pipeline Benchmark — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"{'Mode:':>12} {'RUN' if args.run else 'DRY RUN (check only)'}")
    print()

    results = []
    total_time = 0

    for script_cmd, description in STAGES:
        exists = check_stage(script_cmd)
        if not exists:
            print(f"  {'MISSING':>8}  {script_cmd:40s}  {description}")
            results.append((script_cmd, description, None, False))
            continue

        if args.run:
            print(f"  {'RUNNING':>8}  {script_cmd:40s}  {description}...", end="", flush=True)
            success, elapsed = run_stage(script_cmd)
            total_time += elapsed
            status = "OK" if success else "FAIL"
            print(f"  {format_duration(elapsed):>8}  [{status}]")
            results.append((script_cmd, description, elapsed, success))
            if not success:
                print(f"           ⚠ {script_cmd} failed — stopping benchmark")
                break
        else:
            print(f"  {'READY':>8}  {script_cmd:40s}  {description}")
            results.append((script_cmd, description, None, True))

    # Summary
    print(f"\n{'='*60}")
    if args.run:
        print(f"Total elapsed: {format_duration(total_time)}")
        print(f"\n{'Script':40s} {'Time':>10s}  {'Status':>6s}")
        print(f"{'-'*40} {'-'*10}  {'-'*6}")
        for script, desc, elapsed, success in results:
            t = format_duration(elapsed) if elapsed is not None else "—"
            s = "OK" if success else "FAIL"
            print(f"{script:40s} {t:>10s}  {s:>6s}")
    else:
        ready = sum(1 for _, _, _, ok in results if ok)
        print(f"Ready: {ready}/{len(STAGES)} stages")
        print("Run with --run to execute and time all stages.")


if __name__ == "__main__":
    main()
