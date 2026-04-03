#!/bin/bash
# refresh_snapshot.sh — Copy production DB to readonly snapshot.
# Run after any pipeline completes to update the app's data.

set -e
cd "$(dirname "$0")/.."

SRC="data/13f.duckdb"
DST="data/13f_readonly.duckdb"

if [ ! -f "$SRC" ]; then
    echo "ERROR: $SRC not found"
    exit 1
fi

# Check if production DB is locked (active write)
if lsof "$SRC" 2>/dev/null | grep -q "WRITE\|python"; then
    echo "WARNING: $SRC appears to be locked by a running process."
    echo "Proceeding anyway — the snapshot may be stale."
fi

echo "Copying $SRC → $DST..."
cp "$SRC" "$DST"
echo "Snapshot updated: $(date)"
echo "Size: $(du -h "$DST" | cut -f1)"
