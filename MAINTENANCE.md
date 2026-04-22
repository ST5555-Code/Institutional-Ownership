# 13F Ownership Database — Maintenance Guide

_Last updated: April 21, 2026_

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

`backup_db.py` runs on two paths:

1. **Scheduled, as step 8 of `make quarterly-update`** — the
   `backup-db` Makefile target invokes
   `python3 scripts/backup_db.py --no-confirm` automatically during every
   quarterly refresh. The full pipeline does not commit a backup on its
   own cron; it runs when an analyst kicks `quarterly-update`.
2. **Ad-hoc, before risky sessions** — analysts run `backup_db.py`
   manually around work that falls outside `quarterly-update`. Manual
   invocations prompt for confirmation before doing anything; pass
   `--no-confirm` to bypass for scripted use.

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

**When to back up (outside `quarterly-update`):**

- Before any DM13 / DM14 / DM15 audit pass
- Before Stage 5 cleanup (on or after 2026-05-09)
- Before any non-routine entity migration
- At analyst discretion before risky manual edits

Day-to-day entity edits do NOT require full backups — `promote_staging.py`
takes an automatic intra-DB snapshot of every entity table before applying
changes, and auto-rolls back on structural validation failure. Full
backups are reserved for known-risky sessions where the snapshot
mechanism alone isn't enough insurance.

**Retention.** `data/backups/` is gitignored and accumulates ~2.6 G per
full snapshot. Keep every backup in the **current quarter** and the
**current month** in full. Older backups may be pruned manually by the
analyst once the quarterly refresh they guard is fully promoted and a
replacement `quarterly-update` has produced a new baseline. There is no
automated retention script today — flag disk pressure explicitly if
`data/backups/` passes 50 G.

Observed cadence (as of 2026-04-21): 12 snapshots covering
2026-04-10 → 2026-04-19; ~31 G on disk. Apparent size variation across
snapshots tracks schema evolution (table adds/drops) rather than partial
backups — see [docs/findings/obs-08-p1-findings.md](docs/findings/obs-08-p1-findings.md).

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

### Concrete workflow — OpenFIGI / CUSIP refetch

The general pattern above specialises to a five-step loop for CUSIP /
OpenFIGI refetches (int-01 and successors). The loop is fully
restart-safe: each step is idempotent and checkpoints to
`cusip_retry_queue` (re-queue) or `cusip_classifications` (resolution).

```bash
# 1. Re-queue affected items (no external API calls; metadata only)
python3 scripts/oneoff/int_01_requeue.py

# 2. Retry against staging (only step that hits OpenFIGI)
python3 scripts/run_openfigi_retry.py --staging

# 3. Propagate resolved rows through the staging CUSIP tables
python3 scripts/build_cusip.py --staging --skip-openfigi

# 4. Verify acceptance criteria — read-only SQL checks
#    Use scripts/validate_classifications.py or ad-hoc duckdb queries
#    against data/13f_staging.duckdb: row counts, nullability deltas,
#    priceability gain/loss, and parity against prod for unchanged rows.
python3 scripts/validate_classifications.py --staging

# 5. Promote staging → prod (authorization required)
python3 scripts/promote_staging.py --approved --tables cusip_classifications,securities
```

**Authorization note.** Step 5 is the only step that writes to
`data/13f.duckdb`. Never run it without explicit approval — the
staging → prod mirror is destructive on the target rows.
`promote_staging.py` takes the intra-DB snapshot automatically and
auto-rolls back on structural validation failure.

**Why this shape.** Steps 1-4 are fully restart-safe and side-effect
free against prod. Step 2 is the only network round-trip. Steps 3-4
converge to a deterministic staging state regardless of interruption.
Step 5 is atomic per table and reversible via
`rollback_promotion.py --restore`.

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

## Post-hoc Writer Ordering on `managers`

Three scripts mutate the `managers` table in sequence, and later
writers depend on the earlier writers' schema state:

1. **`build_managers.py`** — canonical builder. DROP+CTAS rebuild;
   materializes the base schema.
2. **`fetch_13dg.py`** Phase 3 — runs after `build_managers.py`;
   `ALTER TABLE managers ADD COLUMN has_13dg BOOLEAN` + `UPDATE` to
   stamp the 13D/G-filer flag.
3. **`fetch_ncen.py`** — runs after `build_managers.py`; `ALTER
   TABLE managers ADD COLUMN adviser_cik VARCHAR` + `UPDATE` from
   `ncen_adviser_map`.

The ordering is currently implicit — enforced only by the Makefile
`quarterly-update` target and the scheduler that invokes it. There
is no code-level sentinel that refuses to run `fetch_13dg` or
`fetch_ncen` if `build_managers` has not run in the current cycle.

**Hazard scenarios.**
- If `build_managers.py` runs without `fetch_13dg.py` / `fetch_ncen.py`
  afterward, `managers` ends the cycle with the base schema only —
  `has_13dg` and `adviser_cik` are missing. Downstream readers that
  expect either column will error.
- If `fetch_13dg.py` or `fetch_ncen.py` runs before `build_managers.py`
  in a cycle, the ALTER+UPDATE writes against the *previous cycle's*
  `managers` table (`build_managers` uses DROP+CTAS, so every cycle
  starts fresh). The writes succeed but are immediately overwritten
  on the next `build_managers.py` invocation.

**Current discipline.** Makefile + scheduler sequencing. Adequate for
the quarterly cadence; the hazard window is narrow because the chain
is automated end-to-end.

**Follow-on candidates (not scheduled).**
- (x) Sentinel check at top of `fetch_13dg.py` Phase 3 and
  `fetch_ncen.py`: read `data_freshness('managers')` and fail if the
  stamp is older than the current cycle's `build_managers.py` run.
  Makes the ordering contract explicit at the code layer. Small fix,
  straightforward.
- (y) Document and rely on ops discipline (status quo). Accept the
  hazard as bounded to manual out-of-sequence invocations.

If writer ordering is ever bundled into broader convention-hardening
work, fold into `INF31` (BLOCK-MARKET-DATA-WRITER-CONVENTION), which
covers the analogous issue for `market_data` writers.

This section captures the state, not a change.
