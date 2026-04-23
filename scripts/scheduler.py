#!/usr/bin/env python3
"""
scheduler.py — Simple cron-like scheduler for pipeline tasks.

Runs in the background, checks schedule every minute, triggers scripts
when their next run time arrives.

Run: python3 scripts/scheduler.py           # Start scheduler
     python3 scripts/scheduler.py --list    # Show current schedule
"""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_FILE = os.path.join(BASE_DIR, "data", "schedule.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")

DEFAULT_SCHEDULE = [
    {
        "name": "13D/G Update",
        "script": "pipeline/load_13dg.py",
        "flags": ["--staging"],
        "interval_hours": 720,  # monthly (30 days)
        "enabled": False,
    },
    {
        "name": "FINRA Short Interest",
        "script": "fetch_finra_short.py",
        "flags": ["--staging", "--update"],
        "interval_hours": 168,  # weekly
        "enabled": False,
    },
    {
        "name": "Market Data Refresh",
        "script": "pipeline/load_market.py",
        "flags": [],
        "interval_hours": 24,  # daily
        "enabled": False,
    },
    {
        "name": "Merge Staging",
        "script": "merge_staging.py",
        "flags": ["--all", "--drop-staging"],
        "interval_hours": 24,
        "enabled": False,
    },
    {
        "name": "Refresh Snapshot",
        "script": "refresh_snapshot.sh",
        "flags": [],
        "interval_hours": 24,
        "enabled": False,
    },
]


def load_schedule():
    """Load schedule from JSON file, or create with defaults."""
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            return json.load(f)
    save_schedule(DEFAULT_SCHEDULE)
    return DEFAULT_SCHEDULE


def save_schedule(schedule):
    """Save schedule to JSON file."""
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, 'w') as f:
        json.dump(schedule, f, indent=2, default=str)


def is_due(task):
    """Check if a task is due to run."""
    if not task.get("enabled"):
        return False
    last_run = task.get("last_run")
    if not last_run:
        return True
    last_dt = datetime.fromisoformat(last_run)
    interval = timedelta(hours=task.get("interval_hours", 24))
    return datetime.now() - last_dt >= interval


def run_task(task):
    """Execute a scheduled task."""
    script = task["script"]
    flags = task.get("flags", [])
    script_path = os.path.join(BASE_DIR, "scripts", script)

    if script.endswith('.sh'):
        cmd = ["bash", script_path] + flags
    else:
        cmd = ["python3", "-u", script_path] + flags

    log_name = os.path.basename(script).replace('.py', '').replace('.sh', '')
    log_path = os.path.join(LOG_DIR, f"sched_{log_name}.log")

    print(f"  [{datetime.now().strftime('%H:%M')}] Running {task['name']}...", flush=True)
    with open(log_path, 'a') as log:
        log.write(f"\n{'='*40}\nScheduled run: {datetime.now().isoformat()}\n{'='*40}\n")
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=BASE_DIR)

    task["last_run"] = datetime.now().isoformat()
    task["last_status"] = "ok" if result.returncode == 0 else f"failed (exit {result.returncode})"
    return result.returncode == 0


def show_schedule():
    """Print current schedule."""
    schedule = load_schedule()
    print(f"\n{'Task':30s} {'Interval':>10s} {'Enabled':>8s} {'Last Run':>20s} {'Status':>10s}")
    print(f"{'-'*30} {'-'*10} {'-'*8} {'-'*20} {'-'*10}")
    for t in schedule:
        interval = f"{t['interval_hours']}h"
        enabled = "YES" if t.get('enabled') else "no"
        last = t.get('last_run', '—')[:19] if t.get('last_run') else '—'
        status = t.get('last_status', '—')
        print(f"  {t['name']:28s} {interval:>10s} {enabled:>8s} {last:>20s} {status:>10s}")


def run_scheduler():
    """Main scheduler loop — checks every 60s."""
    os.makedirs(LOG_DIR, exist_ok=True)
    print(f"Scheduler started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Schedule file: {SCHEDULE_FILE}")
    show_schedule()
    print("\nWatching... (Ctrl+C to stop)\n")

    while True:
        schedule = load_schedule()
        for task in schedule:
            if is_due(task):
                success = run_task(task)
                save_schedule(schedule)
                if success:
                    print(f"  [{datetime.now().strftime('%H:%M')}] {task['name']}: complete", flush=True)
                else:
                    print(f"  [{datetime.now().strftime('%H:%M')}] {task['name']}: FAILED", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline scheduler")
    parser.add_argument("--list", action="store_true", help="Show current schedule")
    args = parser.parse_args()

    if args.list:
        show_schedule()
    else:
        run_scheduler()
