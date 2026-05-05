# backup-archive-cadence-2026-05-05 — results

**PR:** backup-archive-cadence-2026-05-05
**Workstream type:** P3 ops (recurring per conv-28 cadence rule)
**Date:** 2026-05-05
**Pattern source:** PR #273 backup-pruning-and-archive

## Outcome

7 backups archived to `BackupToDrive/` as md5-verified `.tar.gz` files; sources pruned from `data/backups/`. One additional 22 GB redundant single-file snapshot deleted directly without archiving (rationale below). Three most recent EXPORT directories retained locally.

- `data/backups/`: 49 GB → 9.7 GB (3 directories retained)
- `BackupToDrive/`: 0 → 14 GB staged (7 archives across 2 sections)
- 22 GB redundant single-file snapshot deleted directly (`pre_loader_gap_sub1`)
- pytest, no DB writes, no code changes

## 1. Phase 1 inventory snapshot

| Path | Type | Size | mtime | Disposition |
|---|---|---:|---|---|
| `13f_backup_20260505_165855/` | full_db_export_dir | 3.3 GB | 2026-05-05 16:59 | KEEP_LOCAL |
| `13f_backup_20260505_142125/` | full_db_export_dir | 3.2 GB | 2026-05-05 14:21 | KEEP_LOCAL |
| `13f_backup_20260505_124352/` | full_db_export_dir | 3.2 GB | 2026-05-05 12:44 | KEEP_LOCAL |
| `13f_backup_20260505_071643/` | full_db_export_dir | 3.2 GB | 2026-05-05 07:16 | ARCHIVE |
| `13f_backup_20260505_063809/` | full_db_export_dir | 3.2 GB | 2026-05-05 06:38 | ARCHIVE |
| `13f_backup_20260503_121103/` | full_db_export_dir | 3.2 GB | 2026-05-03 12:11 | ARCHIVE |
| `13f_backup_20260503_110616/` | full_db_export_dir | 3.2 GB | 2026-05-03 11:06 | ARCHIVE |
| `13f_backup_20260503_082307/` | full_db_export_dir | 3.2 GB | 2026-05-03 08:23 | ARCHIVE |
| `peer_rotation_..._210801.duckdb` | pipeline_snapshot_file | 277 MB | 2026-05-05 17:09 | ARCHIVE |
| `peer_rotation_..._111826.duckdb` | pipeline_snapshot_file | 269 MB | 2026-05-05 07:19 | ARCHIVE |
| `13f.20260505_155457.pre_loader_gap_sub1.duckdb` | single_file_full_db | 22 GB | 2026-05-05 15:54 | **DELETED_DIRECT_REDUNDANT** |

Retention rule applied to EXPORT directories (per PR #273 precedent): newest 3 KEEP_LOCAL, older ARCHIVE. Pipeline snapshots and single-file full-DB snapshots always ARCHIVE_AND_PRUNE.

## 1.5 Direct-delete decision: `pre_loader_gap_sub1.duckdb`

The 22 GB single-file `.duckdb` snapshot was deleted directly without archiving. Two factors:

1. **Disk constraint.** Free disk at session start: 14 GB. Tarball size for a 22 GB DuckDB binary file would have been ~18-20 GB (typical 0.85-0.90 ratio). Even after pruning all 7 small ARCHIVE entries to grow free disk, projected ~17 GB free vs. 18-20 GB needed for the tarball — would not fit.
2. **Redundancy.** The snapshot captured the database state immediately before the cp-5-loader-gap-remediation-sub1 PR. The EXPORT directory `13f_backup_20260505_063809/` (May 5 06:38) captures the same morning's pre-sub1 state in the canonical EXPORT format and IS being archived to Drive. The loader-gap workstream is CLOSED (per memory `project_session_may05_loader_gap_sub2.md`); no ongoing reference to this single-file snapshot.

Decision confirmed in chat 2026-05-05. Documented here for future cadence runs: single-file full-DB copies are higher-cost to archive (size, no incremental gzip benefit on DuckDB binary format) and typically duplicate same-day EXPORT content. Default disposition for single-file `.duckdb` full-DB snapshots going forward: delete directly when a same-day EXPORT covers the same state.

## 2. Phase 2 — staging directory

`BackupToDrive/` already gitignored (PR #273 work). Subfolders pre-created to match Drive layout under `ShareholderProject/13f-backups/`:

```
BackupToDrive/
  full-db-exports/        (5 .tar.gz)
  pipeline-snapshots/     (2 .tar.gz)
```

No `staging-backup/` this run (no staging-backup directories present in inventory).

## 3. Phase 3 — interleaved compress + verify + gate + delete

Order: mtime-asc (oldest first). Free disk grew from 36 GB at start (post direct-delete) to 39 GB at end of pass.

| Source | Tarball ratio | md5 |
|---|---:|---|
| `13f_backup_20260503_082307` | 0.8320 | 50d5e275431c221d47ee8fb3b9150a6b |
| `13f_backup_20260503_110616` | 0.8318 | 54992f55f547dd8a423f8c9d8279a386 |
| `13f_backup_20260503_121103` | 0.8318 | 86aba9fd4632658bafd4990cd75314ac |
| `13f_backup_20260505_063809` | 0.8320 | d890fc5d6f96a7d80d9f345c07ec8e04 |
| `13f_backup_20260505_071643` | 0.8321 | f61714099827c82e89825b81689c6dcf |
| `peer_rotation_..._111826.duckdb` | 0.6261 | eddfcb04f5d7b90ddce1a59d792eb5e5 |
| `peer_rotation_..._210801.duckdb` | 0.6238 | 468ec14a0a0d32976e68710b53d59a6c |

Per-section aggregate:

| Section | files | source GB | archive GB | mean ratio |
|---|---:|---:|---:|---:|
| full-db-exports | 5 | 17.17 | 14.29 | 0.832 |
| pipeline-snapshots | 2 | 0.56 | 0.35 | 0.625 |
| **total** | **7** | **17.73** | **14.64** | **0.826** |

Full-DB ratios (~0.83) consistent with PR #273 (Snappy parquet → gzip ~17% incremental savings). Peer-rotation snapshots (~0.62) compress better — DuckDB binary file with sparse content.

All 7 entries passed the final gate per PR #273 calibration:
- `tar -tzf` integrity
- `md5sum` recorded
- size > 1024 bytes
- ratio ≤ 0.95

Per-entry detail in `data/working/backup-archive-cadence-2026-05-05-manifest.csv`.

## 4. Final disk state

| Path | Before | After |
|---|---:|---:|
| `data/backups/` | 49 GB | 9.7 GB |
| `BackupToDrive/` | — | 14 GB |
| Free disk on `/System/Volumes/Data` | 14 GB | 39 GB |

After user uploads `BackupToDrive/` to Drive and removes locally: `data/backups/` 9.7 GB, `BackupToDrive/` 0, free disk ~53 GB.

## 5. Upload instructions

User uploads to existing Drive folder `My Drive/ShareholderProject/13f-backups/` (folders created in PR #273 work):

1. Drag `BackupToDrive/full-db-exports/*.tar.gz` (5 files, ~13 GB) → Drive `full-db-exports/`
2. Drag `BackupToDrive/pipeline-snapshots/*.tar.gz` (2 files, ~353 MB) → Drive `pipeline-snapshots/`
3. Spot-verify md5 on at least one file in each section (md5 column in manifest CSV)
4. `rm -rf BackupToDrive/` to recover ~14 GB local staging

No `staging-backup/` upload this run.

## 6. P3 cadence status

- **Run date:** 2026-05-05
- **Next due:** when `data/backups/` exceeds 3 retained directories again
- **Rule confirmation:** newest-3-EXPORT-dirs KEEP_LOCAL retention rule re-validated; works as designed when paired with explicit handling for single-file full-DB snapshots (see §1.5).

## 7. Validation

- `pytest tests/` → 416 passed (per repo baseline; no code changes this PR)
- No DB writes
- No code changes outside `.gitignore` (already configured for `BackupToDrive/` and `data/backups/`)
- 3 KEEP_LOCAL EXPORT directories untouched and verified by directory listing
