# Snapshot Roles

Three distinct snapshot roles exist in this system. They serve different purposes, live in different places, and are managed by different scripts. Conflating them has caused confusion in the past — keep them separate.

| Role | Location | Created by | Managed by |
|---|---|---|---|
| Serving | `data/13f_readonly.duckdb` | `scripts/refresh_snapshot.sh` | (none — overwrite-in-place) |
| Rollback | `*_snapshot_YYYYMMDD_HHMMSS` tables inside prod DB | `scripts/promote_staging.py` | `scripts/hygiene/snapshot_retention.py` |
| Archive | `data/backups/<timestamp>/` | `scripts/backup_db.py` | manual (see `MAINTENANCE.md`) |

## 1. Serving snapshot

A read-only copy of `data/13f.duckdb` written to `data/13f_readonly.duckdb`. The Flask app (`scripts/app_db.py`) opens prod read-only and falls back to this snapshot when prod is locked by a writer (e.g. an active pipeline). Without it, the app errors out for the duration of the write lock.

Created by `scripts/refresh_snapshot.sh` using DuckDB's `COPY FROM DATABASE` (MVCC-safe). INF13 (2026-04-10) removed the legacy hot-path `shutil.copy2` because byte-level copies of a live DuckDB file can capture torn pages — the WAL lives inside the main `.duckdb` file. Run `scripts/refresh_snapshot.sh` after each pipeline cycle; `scripts/run_pipeline.sh` calls it automatically. Not versioned, not retained — overwritten in place each refresh.

## 2. Rollback snapshot

Tables of the form `{base_table}_snapshot_{YYYYMMDD_HHMMSS}` created inside the prod DB by `scripts/promote_staging.py` before every staging→prod promotion. Purpose: instant rollback via `scripts/rollback_promotion.py` if a promote corrupts data.

Each snapshot is registered in the `snapshot_registry` table (migration 018) with `created_at`, `applied_policy`, `expiration`, and an optional `approver` for carve-outs. Default policy is 14 days from creation — see `docs/findings/2026-04-24-snapshot-inventory.md` for the policy memo.

Pruning is enforced by `scripts/hygiene/snapshot_retention.py`. Default mode is `--dry-run`; `--apply` is required for any DROP. Wired into `make snapshot-retention` (and `make snapshot-retention-dry`) and runs automatically as part of `make quarterly-update` after `backup-db` completes (PR #164).

## 3. Archive snapshot

Full DuckDB `EXPORT DATABASE` dumps written to `data/backups/<timestamp>/` as a directory of parquet files plus schema SQL. Self-contained — restorable on any machine without access to the original WAL.

Created by `scripts/backup_db.py` (`--no-confirm` for scripted runs). Triggered automatically by `make backup-db` inside `make quarterly-update`, and ad-hoc by analysts before risky entity sessions (DM13 / DM14 / DM15, Stage 5 cleanup, manual edits).

Retention is manual per `MAINTENANCE.md` §"Backup retention" — keep the current quarter and the current month in full; older backups may be pruned manually once `data/backups/` passes 50 GB. Directory is gitignored.
