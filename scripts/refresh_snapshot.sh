#!/bin/bash
# refresh_snapshot.sh — Copy production DB to readonly snapshot.
# Run after any pipeline completes to update the app's data.
#
# INF13 (2026-04-10): Uses DuckDB's own `COPY FROM DATABASE` command
# rather than a file-level `cp`. DuckDB stores the WAL inside the main
# .duckdb file; writers append to the WAL section during transactions,
# so a byte-level copy taken while a writer is active can capture
# internally-inconsistent state (torn pages, header pointing at
# unwritten checkpoints). `COPY FROM DATABASE` reads through DuckDB's
# MVCC view of a consistent snapshot and writes a fresh file — safe
# even when a writer is concurrently active on the source.

set -e
cd "$(dirname "$0")/.."

SRC="data/13f.duckdb"
DST="data/13f_readonly.duckdb"
TMP="${DST}.tmp"

if [ ! -f "$SRC" ]; then
    echo "ERROR: $SRC not found"
    exit 1
fi

# Remove any leftover tmp from a prior interrupted run.
rm -f "$TMP"

echo "Snapshotting $SRC → $DST via DuckDB COPY FROM DATABASE..."
python3 - <<PY
import duckdb
import os
import sys

src = "$SRC"
tmp = "$TMP"

# Verify src opens read-only — confirms it is a valid DuckDB file at a
# consistent version. If a writer is actively doing something that
# prevents read-only access at this exact moment, we exit nonzero and
# let the operator retry.
try:
    probe = duckdb.connect(src, read_only=True)
    probe.execute("SELECT 1").fetchone()
    probe.close()
except Exception as e:
    print(f"ERROR: cannot open {src} read-only: {e}", file=sys.stderr)
    sys.exit(1)

con = duckdb.connect(":memory:")
con.execute(f"ATTACH '{src}' AS src (READ_ONLY)")
con.execute(f"ATTACH '{tmp}' AS dst")
con.execute("COPY FROM DATABASE src TO dst")
con.execute("DETACH src")
con.execute("DETACH dst")
con.close()

# Sanity check the result opens.
verify = duckdb.connect(tmp, read_only=True)
table_count = verify.execute(
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main'"
).fetchone()[0]
verify.close()
if table_count == 0:
    print(f"ERROR: snapshot at {tmp} has zero tables", file=sys.stderr)
    os.remove(tmp)
    sys.exit(1)
print(f"  snapshot staged at {tmp} with {table_count} tables")
PY

# Atomic rename into place.
mv "$TMP" "$DST"
echo "Snapshot updated: $(date)"
echo "Size: $(du -h "$DST" | cut -f1)"
