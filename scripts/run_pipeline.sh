#!/bin/bash
set -e

cd "$(dirname "$0")/.."
mkdir -p logs

echo "============================================================"
echo "13D/G Pipeline — $(date)"
echo "============================================================"

echo ""
echo "--- Phase 1: Listing filings ---"
python3 -u scripts/fetch_13dg.py --phase1-only "$@" 2>&1 | tee logs/phase1.log

echo ""
echo "--- Phase 2: Parsing filings ---"
python3 -u scripts/fetch_13dg.py --phase2-only "$@" 2>&1 | tee logs/phase2.log

echo ""
echo "--- Phase 3: Post-processing ---"
python3 -u scripts/fetch_13dg.py --phase3-only "$@" 2>&1 | tee logs/phase3.log

echo ""
echo "--- Copying readonly snapshot ---"
cp data/13f.duckdb data/13f_readonly.duckdb
echo "  Snapshot updated."

echo ""
echo "Pipeline complete. Restart app to pick up fresh data."
echo "Finished: $(date)"
