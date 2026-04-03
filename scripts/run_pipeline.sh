#!/bin/bash
set -e

cd "$(dirname "$0")/.."
mkdir -p logs

# Guard: check no fetch process is already running
if pgrep -f "fetch_13dg.py" > /dev/null 2>&1; then
    echo "ERROR: fetch_13dg.py is already running. Aborting."
    exit 1
fi

notify() {
    local title="$1"
    local msg="$2"
    osascript -e "display notification \"$msg\" with title \"$title\"" 2>/dev/null || true
}

phase_start() {
    echo ""
    echo "--- $1 — started $(date '+%H:%M:%S') ---"
}

phase_end() {
    echo "--- $1 — ended $(date '+%H:%M:%S') ---"
}

echo "============================================================"
echo "13D/G Pipeline — $(date)"
echo "============================================================"
echo "  All writes go to staging DB. Production stays unlocked."
echo ""

phase_start "Phase 1: Listing filings"
python3 -u scripts/fetch_13dg.py --staging --phase1-only "$@" 2>&1 | tee logs/phase1.log
phase_end "Phase 1"

phase_start "Phase 2: Parsing filings"
python3 -u scripts/fetch_13dg.py --staging --phase2-only "$@" 2>&1 | tee logs/phase2.log
phase_end "Phase 2"

phase_start "Phase 3: Post-processing"
python3 -u scripts/fetch_13dg.py --staging --phase3-only "$@" 2>&1 | tee logs/phase3.log
phase_end "Phase 3"

phase_start "Merge staging → production"
python3 -u scripts/merge_staging.py --all --drop-staging 2>&1 | tee logs/merge.log
phase_end "Merge"

echo ""
echo "--- Copying readonly snapshot ---"
cp data/13f.duckdb data/13f_readonly.duckdb
echo "  Snapshot updated."

echo ""
echo "Pipeline complete. Restart app to pick up fresh data."
echo "Finished: $(date)"
notify "13D/G Pipeline" "Pipeline complete — all phases finished, staging merged"
