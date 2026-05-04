# backup-pruning-and-archive — results

**PR:** backup-pruning-and-archive
**Workstream type:** P3 ops
**Date:** 2026-05-04
**Author session:** cranky-black-acfac8 worktree

## Outcome

44 backups archived to `BackupToDrive/` as md5-verified `.tar.gz` files; sources pruned from `data/backups/`. Three most recent backups (KEEP_LOCAL) untouched per retention rule. User uploads `BackupToDrive/` contents to Google Drive `ShareholderProject/13f-backups/` manually, then removes `BackupToDrive/` locally.

- `data/backups/`: 71 GB → 9.6 GB (3 directories retained)
- `BackupToDrive/`: 0 → 49.5 GB staged (44 archives across 3 sections)
- Net local disk freed once user removes `BackupToDrive/` after upload: ~61 GB
- pytest 416/416 passing, React build 0 errors, no DB writes, no code changes outside `.gitignore`

## 1. Phase 1 inventory snapshot

| Section | Pattern | Count | Disposition |
|---|---|---:|---|
| Full-DB exports | `13f_backup_<YYYYMMDD>_<HHMMSS>/` | 20 dirs | 3 KEEP_LOCAL (newest), 17 ARCHIVE_AND_PRUNE |
| Staging backup | `13f_staging_backup_*` | 1 dir | 1 ARCHIVE_AND_PRUNE |
| Pipeline snapshots | `<table>_<event>_<timestamp>.duckdb` | 26 files | 26 ARCHIVE_AND_PRUNE |

**KEEP_LOCAL** (3 newest full-DB exports, untouched):
- `13f_backup_20260503_121103/`
- `13f_backup_20260503_110616/`
- `13f_backup_20260503_082307/`

## 1.5 Scope expansion (chat decision 2026-05-03)

Original plan limited ARCHIVE_AND_PRUNE to full-DB export directories; pipeline-snapshot single-files and the staging-backup directory were flagged "do not include without explicit chat decision." Per chat instruction, scope expanded to all three categories in a single workstream.

Rationale: pipeline snapshots (peer_rotation, sector_flows, parent_fund_map, 13f_holdings, nport_holdings) are stale, recoverable by re-running the originating pipeline against the live `13f.duckdb`, and redundant with the full-DB exports covering the same period. The staging-backup is a one-off pre-INF1 snapshot that no longer matches current schema. None are referenced from live code paths.

## 1.6 Compressed-total estimate revision

Original plan estimated `BackupToDrive/` at ~12-15 GB. Actual: **49.5 GB**. Both estimates rooted in the same wrong premise (see Section 4 calibration notes). Sources are pre-compressed parquet, so re-gzipping yields ~17% additional savings — not the 80-90% the original assumption implied.

Forward-looking sizing: budget ~3 GB compressed per full-DB export (vs. ~3.2 GB uncompressed source).

## 2. Phase 2 — staging directory

- `BackupToDrive/` created at main-repo root.
- `.gitignore` updated with `BackupToDrive/` entry adjacent to existing `data/backups/` rule (line 23).

## 3. Phase 3+4 — interleaved compress + verify + delete

The plan as written presents Phase 3 (compress all) and Phase 4 (delete all sources) sequentially. Free disk at session start (24 GB on a 460 GB volume, 95% full) made the literal interpretation infeasible — peak working set under sequential phases would have been ~82 GB. Per chat decision, phases were interleaved per-entry: compress → tar -tzf → md5sum → ratio gate → size gate → `rm -rf` source → next.

Order: source size descending, so each large source deleted early frees disk for subsequent iterations. Disk free **rose** from 22 GB at start of compression to 35 GB at end of pass.

Per-section aggregate stats:

| Section | files | source GB | archive GB | mean ratio |
|---|---:|---:|---:|---:|
| 1_full_db_exports | 17 | 53.85 | 44.78 | 0.832 |
| 2_staging_backup | 1 | 1.83 | 1.50 | 0.820 |
| 3_pipeline_snapshots | 26 | 5.55 | 3.19 | 0.574 |
| **total** | **44** | **61.22** | **49.46** | **0.808** |

Per-entry detail in `data/working/backup-archive-manifest.csv` (44 rows × 10 columns).

## 4. Gate calibration

Two iterations were needed to land on the right ratio gate:

**Calibration #1** (full-DB lower bound 0.05 → 0.30, then dropped):
First abort hit on entry 1 (`13f_backup_20260502_080830/`, ratio 0.832). Plan's `[0.05, 0.50]` gate assumed ~80-90% gzip compression. DuckDB `EXPORT DATABASE PARQUET` writes Snappy-compressed parquet files — re-gzipping yields ~10-20% incremental savings, not 80-90%. Per chat instruction, raised lower bound to 0.30 to match the single-file gate.

**Calibration #2** (lower bound dropped entirely):
Second abort hit on entry 38 (`sector_flows_*_20260430_085831.duckdb`, ratio 0.023). Sector_flows files are ~524 KB schema-only parquets dominated by file headers; gzip compresses them to ~12 KB. Per chat instruction, dropped the ratio lower bound entirely; upper bound remains at `<= 0.95` to flag suspiciously-undercompressed archives.

**Final rule:**
- `tar -tzf` integrity check (catches silent compress failures)
- `md5sum` recorded
- archive size > 1024 bytes (single-file) / > 1 MB (full-DB tarballs)
- ratio ≤ 0.95

The lower-bound's intent (catch silent failures) is fully covered by the integrity + md5 + size checks. The dropped lower bound is documented here so future runs of this workflow inherit the calibrated gate.

## 5. Phase 4 — deletion confirmation

All 44 sources removed via `shutil.rmtree` (directories) or `Path.unlink` (single files), with post-delete existence check before manifest row was written. Manifest `deletion_status` column = `'deleted'` for all 44 rows.

Final `data/backups/` directory listing:
```
13f_backup_20260503_082307/
13f_backup_20260503_110616/
13f_backup_20260503_121103/
```

## 6. Final disk state

| Path | Before | After |
|---|---:|---:|
| `data/backups/` | 71 GB | 9.6 GB |
| `BackupToDrive/` | — | 49.5 GB |
| Free disk on `/System/Volumes/Data` | 24 GB | 35 GB |

After user uploads `BackupToDrive/` to Drive and removes the local staging directory: `data/backups/` 9.6 GB, `BackupToDrive/` 0, free disk ~85 GB (current 35 + reclaimed 50).

## 7. Upload instructions

See [`BackupToDrive/UPLOAD_INSTRUCTIONS.md`](../../BackupToDrive/UPLOAD_INSTRUCTIONS.md) for the manual Drive upload procedure. Drive folder layout:

```
ShareholderProject/13f-backups/
  full-db-exports/     (17 .tar.gz from Section 1)
  staging-backup/      (1 .tar.gz from Section 2)
  pipeline-snapshots/  (26 .tar.gz from Section 3)
```

Per-section md5 tables included in the upload doc for spot-verification.

## 8. Future cadence

This workflow re-runs whenever `data/backups/` accumulates beyond 3 directories. Pattern:

1. Inventory + retention partition (newest 3 stay).
2. Per-entry interleaved compress → tar -tzf → md5sum → ratio ≤ 0.95 → delete source.
3. Append manifest CSV row per entry.
4. User uploads `BackupToDrive/` to Drive, then removes locally.

A small wrapper script (`scripts/oneoff/prune_and_archive_backups.py`) was used in this PR but kept outside the repo (one-shot, not yet on a regular cadence). If pruning becomes routine, lift the script into `scripts/` in a follow-up PR.

## 9. Validation

- `pytest tests/` → 416 passed, 1 warning, 63s
- `cd web/react-app && npm ci && npm run build` → built in 1.57s, 0 errors
- `data/backups/` contents → exactly 3 KEEP_LOCAL directories
- `BackupToDrive/` contents → 44 `.tar.gz` files + `UPLOAD_INSTRUCTIONS.md`
- `git check-ignore -v BackupToDrive/` → ignored via `.gitignore:23`
- No DB writes, no code changes outside `.gitignore`
