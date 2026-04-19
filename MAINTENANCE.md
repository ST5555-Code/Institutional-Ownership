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
# Production health check
# (Expect 1 non-structural FAIL on wellington_sub_advisory until INF3 lands.)
python3 scripts/validate_entities.py

# Review unreviewed staging diffs (if any)
ls -lt logs/staging_diff_*.txt | head -5

# Check for overdue manual routings
# (look for the manual_routing_review gate row in the report)
cat logs/entity_validation_report.json | python3 -m json.tool | grep -A3 manual_routing_review
```

**Backups are NOT part of monthly maintenance.** See "Backup Protocol" below.

## Backup Protocol

`backup_db.py` runs **manually**, never on a schedule. Every invocation
prompts for confirmation before doing anything — pass `--no-confirm` to
bypass for scripted / automated use.

```bash
# Take a backup (interactive prompt)
python3 scripts/backup_db.py

# Bypass the prompt (scripted)
python3 scripts/backup_db.py --no-confirm

# List existing backups
python3 scripts/backup_db.py --list

# Back up the staging DB instead of production
python3 scripts/backup_db.py --staging
```

**When to back up:**

- Before any DM13 / DM14 / DM15 audit pass
- Before Stage 5 cleanup (on or after 2026-05-09)
- Before any non-routine entity migration
- At analyst discretion before risky manual edits

Day-to-day entity edits do NOT require full backups — `promote_staging.py`
takes an automatic intra-DB snapshot of every entity table before applying
changes, and auto-rolls back on structural validation failure. Full
backups are reserved for known-risky sessions where the snapshot
mechanism alone isn't enough insurance.

## Refetch Pattern for Prod Apply

When a prod apply requires refetching external data (market prices,
CUSIP classifications, N-PORT holdings), **do not re-hit the external
API from the prod path.** Run the refetch in staging first, then mirror
the staging output to prod via an ephemeral helper script.

**Principle:** prod applies are idempotent, deterministic, and make no
external API calls. Staging owns every external round-trip.

**When to use:**

- Any BLOCK closeout whose prod apply touches a table that was refetched
  in staging (first documented in BLOCK-3 Phase 4 prod apply —
  `fund_holdings_v2.ticker` populate mirrored from staging without
  re-hitting Yahoo).
- Any backfill of canonical-table columns populated via an external
  lookup (OpenFIGI, yfinance, SEC XBRL).

**Shape of the helper:**

```bash
# 1. Run refetch in staging (owns external round-trips)
python3 scripts/<refetch>.py --staging

# 2. Validate row-level parity against prod
python3 scripts/<parity_check>.py --staging

# 3. Ephemeral mirror helper: ATTACH staging read-only, UPDATE prod
#    from staging join. No external network calls in this step.
python3 scripts/<mirror>_to_prod.py

# 4. Checkpoint prod, stamp data_freshness
```

**Guardrails:**

- The mirror helper MUST NOT import any external-API client (yfinance,
  openfigi, edgartools, curl_cffi). Enforce at code review.
- The mirror helper MUST NOT write outside the target table(s) and the
  `data_freshness` control-plane row.
- `CHECKPOINT` before and after the mirror write.
- If staging-prod parity check fails, stop — do not mirror.

**Precedent:** BLOCK-3 Phase 4 prod apply mirrored
`fund_holdings_v2.ticker` (+1.45M rows) from staging without
re-hitting Yahoo; runtime seconds, fully restart-safe.

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
