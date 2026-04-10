# 13F Ownership Database — Maintenance Guide

_Last updated: April 10, 2026_

## Entity Change Workflow

All entity changes go through staging before production. See
`ENTITY_ARCHITECTURE.md` → **Operational Procedures** for full workflow,
gate semantics, and rollback options.

Quick reference:

```bash
# 1. Pull current production state into staging
python3 scripts/sync_staging.py

# 2. [make changes in data/13f_staging.duckdb only]

# 3. Run validation against staging
python3 scripts/validate_entities.py --staging

# 4. Generate human-readable diff
python3 scripts/diff_staging.py

# 5. [review diff in conversation; get explicit authorization]

# 6. Promote staging → production (with snapshot + auto-restore on failure)
python3 scripts/promote_staging.py --approved

# 7. Verify production
python3 scripts/validate_entities.py

# 8. Commit
git commit -am "..."
```

## Monthly Maintenance

Run on the first of each month:

```bash
# Full DuckDB EXPORT DATABASE backup
python3 scripts/backup_db.py
python3 scripts/backup_db.py --list

# Production health check
python3 scripts/validate_entities.py

# Review unreviewed staging diffs (if any)
ls -lt logs/staging_diff_*.txt | head -5

# Check for overdue manual routings
# (look for the manual_routing_review gate row in the report)
cat logs/entity_validation_report.json | python3 -m json.tool | grep -A3 manual_routing_review
```

## Rollback Procedures

```bash
# List promotion snapshots stored inside production DB
python3 scripts/rollback_promotion.py --list

# Restore production from a named snapshot (taken by promote_staging.py)
python3 scripts/rollback_promotion.py --restore SNAPSHOT_ID

# Full DB restore from an EXPORT DATABASE backup directory
python3 scripts/backup_db.py --list
duckdb data/13f.duckdb -c "IMPORT DATABASE 'data/backups/13f_backup_YYYYMMDD_HHMMSS'"
```

Promotion snapshots are intra-DB tables (`{table}_snapshot_{timestamp}`)
auto-created by `promote_staging.py`. Backups are full self-contained
DuckDB EXPORT DATABASE directories.

## Pending Audit Work

All items below must go through the staging workflow:

- **Securian / Sterling fix** — `entity_relationships` 12171 + 12172 + dependent rollups + `holdings_v2` / `fund_holdings_v2` re-stamps
- **HC Capital Trust** — 5 sub-adviser routings (Parametric, Mellon, City of London, Wellington, RhumbLine, Agincourt)
- **CRI / Christian Brothers** — 4 missing series routings (Wellington, Loomis Sayles, Teachers Advisors, Parametric)
- **DM13** — ADV_SCHEDULE_A relationship quality audit (~410 suspicious relationships)
- **DM14** — DM8 extension for unlabeled intra-firm sub-advisers (~300-500 series)
- **DM15** — External sub-adviser coverage pass (~$549.7B AUM affected)
- **L5 parents 201-720 audit** (batches of 100)
- **L4 classification audit** (13 categories)

## Stage 5 Cleanup

Drop original holdings / fund_holdings / beneficial_ownership tables.
Authorized on or after **2026-05-09**. See `ROADMAP.md`.
