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

phase_start "Seed staging with reference tables"
python3 -c "import sys; sys.path.insert(0, 'scripts'); from db import set_staging_mode, seed_staging; set_staging_mode(True); seed_staging()"
phase_end "Seed staging"

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
# INF10 fix (2026-04-10): previously this step ran `merge_staging.py --all
# --drop-staging`, which merges every table currently present in staging.
# Staging normally contains the reference tables seeded by seed_staging()
# (holdings, managers, fund_holdings, market_data, adv_managers, filings,
# securities, parent_bridge) plus any entity tables left over from a prior
# sync_staging run — and for any table not in merge_staging.TABLE_KEYS the
# merge path does a full DROP+CREATE TABLE AS SELECT, replacing prod with
# whatever is in staging. Common case was a no-op because seed_staging copies
# from prod at pipeline start, but any concurrent prod write between seed
# and merge silently reverted, and any in-progress entity staging edits
# would have been promoted bypassing the INF1 workflow.
#
# Name the 13D/G output tables explicitly. If future pipelines grow new
# output tables, add them here — do not revert to `--all`.
python3 -u scripts/merge_staging.py \
  --tables beneficial_ownership,beneficial_ownership_current,fetched_tickers_13dg,listed_filings_13dg,short_interest,ncen_adviser_map \
  --drop-staging 2>&1 | tee logs/merge.log
phase_end "Merge"

echo ""
echo "--- Copying readonly snapshot ---"
cp data/13f.duckdb data/13f_readonly.duckdb
echo "  Snapshot updated."

echo ""
echo "Pipeline complete. Restart app to pick up fresh data."
echo "Finished: $(date)"
notify "13D/G Pipeline" "Pipeline complete — all phases finished, staging merged"
