# 13F Ownership Database — Maintenance Guide

_Last updated: April 28, 2026 (dm14c-voya — end-of-leg sync after the post-conv-15 trio (PRs #189 BL-3+INF53, #190 perf-P2 scoping, #191 perf-P2 holder_momentum) plus this session's 7 ROADMAP priority moves and DM14c Voya residual DM re-route. **Migration 023 (`parent_fund_map`)** stamped — new precompute table (PK `(rollup_entity_id, rollup_type, series_id, quarter)`, 109,723 rows; 55K EC + 54K DM × 147 distinct parents that have N-PORT children) populated by new `scripts/pipeline/compute_parent_fund_map.py` `SourcePipeline` subclass (`name='parent_fund_map'`, `direct_write` strategy, ~115s end-to-end). `queries.holder_momentum` parent path rewritten to issue ONE batched JOIN against `parent_fund_map` covering all top-25 parents at once, replacing 25 sequential ILIKE family-name patterns against `fund_holdings_v2`; AAPL parent EC 800ms → 142ms (5.6×). **DM14c Voya residual** — 49 actively-managed Voya-Voya intra-firm series ($21.74B AUM) DM-retargeted from holding co eid=2489 (Voya Financial, Inc.) to operating sub-adviser eid=17915 (Voya Investment Management Co. LLC, CRD 106494); override IDs 1057–1105; promote snapshot `20260428_081209`; EC untouched. **BL-3 + INF53** closed as recommendation-only (PR #189) — N-PORT multi-row-per-key is by design (Long+Short pairs, multiple lots, placeholder CUSIPs); `row_id BIGINT` is the PK, the natural-key tuple was never unique. ROADMAP re-prioritization (this session): 7 Deferred → active backlog. Predecessor: conv-15-doc-sync / PR #188._

## Pipeline refresh via admin dashboard

Phase 2 + Wave 2 (2026-04-22) put all six ingest pipelines (`13f_holdings`, `13dg_ownership`, `nport_holdings`, `market_data`, `ncen_advisers`, `adv_registrants`) behind a single `SourcePipeline` framework with a user-triggered refresh UI. There are two equivalent entry points.

**Web UI (preferred for interactive reviews).**

1. Navigate to `http://localhost:8001/admin/dashboard`.
2. Authenticate (INF12 token via the login surface at `/admin/login`).
3. Click the refresh button on the pipeline's status card. A run starts and transitions through `fetching → parsing → validating → pending_approval`.
4. On `pending_approval`, the diff dashboard surfaces row-level delta + anomaly flags. Click **Approve and promote** to continue, or **Reject** to abort (staging retained 24h for inspection).
5. Status card polls `/admin/run/{run_id}` every ~10s until `complete` / `failed` / `rejected`.

Auto-approve can be turned on per-pipeline through the `admin_preferences` table (migration 016). Default is **OFF** on every pipeline; enable only after observing a clean baseline.

**CLI (for scripted or headless runs).**

```bash
# 13F — quarterly cadence, append_is_latest
python3 scripts/load_13f_v2.py --quarter 2026Q1 --dry-run
python3 scripts/load_13f_v2.py --quarter 2026Q1 --auto-approve

# 13D/G — event-driven, append_is_latest
python3 scripts/pipeline/load_13dg.py --since 2026-04-01 --dry-run
python3 scripts/pipeline/load_13dg.py --tickers AAPL,NVDA --auto-approve

# N-PORT — monthly-topup XML or DERA ZIP bulk, append_is_latest
python3 scripts/pipeline/load_nport.py --monthly-topup --dry-run
python3 scripts/pipeline/load_nport.py --quarter 2026Q1 --zip data/nport_raw/dera/2026q1_nport.zip --auto-approve

# Market data — daily cadence, direct_write
python3 scripts/pipeline/load_market.py --stale-days 3 --dry-run
python3 scripts/pipeline/load_market.py --tickers AAPL,MSFT --auto-approve

# N-CEN — annual-rolling, scd_type2
python3 scripts/pipeline/load_ncen.py --ciks 0000102909 --since 2026-01-01 --dry-run
python3 scripts/pipeline/load_ncen.py --auto-approve

# ADV — annual, direct_write
python3 scripts/pipeline/load_adv.py --dry-run
python3 scripts/pipeline/load_adv.py --zip data/adv/IA_Firm_SEC_Feed_04_22_2026.zip --auto-approve
```

All CLI flags thread through the `SourcePipeline.run()` orchestrator: `--dry-run` stops after step 4 (diff), `--auto-approve` bypasses the approval gate, and every run writes one `ingestion_manifest` row + N `ingestion_impacts` rows regardless of outcome.

**Full reload (13F).** `load_13f_v2.py` requires `--quarter` per invocation; there is no full-reload mode. To reload historical quarters, loop:

```bash
for q in 2025Q1 2025Q2 2025Q3 2025Q4; do
  make load-13f QUARTER=$q
done
```

This replaces the legacy `python3 scripts/load_13f.py` (no-arg) full-reload pattern that was retired at the V2 cutover (phase-b2-5, 2026-04-23). The legacy `scripts/load_13f.py` remains on disk as a break-glass fallback until phase B3 (2-cycle gate, ~Aug 2026).

**Stop the app before promote.** DuckDB allows a single writer per file; the framework opens prod in write mode at step 5 (snapshot) and step 6 (promote). If the FastAPI process holds the file open, promote errors with "unable to open file". Standard pattern: `./scripts/start_app.sh stop` → run pipeline → `./scripts/start_app.sh start`.

**Writer ordering now handled by the framework.** `SourcePipeline` manifests are sequenced at the control-plane level; per-pipeline `_bulk_enrich_run` / `stamp_freshness` / `refresh_snapshot` hooks fire deterministically in the subclass's `approve_and_promote()`. The `adviser_cik` stamping on `managers` now runs inside `scripts/pipeline/load_ncen.py._update_managers_adviser_cik` during promote — the legacy post-hoc writer-ordering hazard (fetch_13dg Phase 3 + fetch_ncen running after build_managers) is gone with those scripts' retirement in Wave 2.

**Precompute / rollup pipelines (L4 derived).** Three `SourcePipeline` subclasses materialize precomputed views read by hot-path query endpoints. All run on quarterly cadence — trigger after the source pipelines (`13f_holdings`, `nport_holdings`, `market_data`) have promoted for the new period.

| Precompute | Pipeline name | Script | Source tables | Reader | Cadence trigger |
|---|---|---|---|---|---|
| `peer_rotation_flows` (perf-P0, migration 019) | `peer_rotation` | `scripts/pipeline/compute_peer_rotation.py` | `holdings_v2` + `fund_holdings_v2` + `market_data` | `queries.get_peer_rotation` / `get_peer_rotation_detail` (and `get_sector_flow_movers` `level='parent'` after perf-P1) | Quarterly — after the new-period 13F + N-PORT promotes land |
| `sector_flows_rollup` (perf-P1, migration 021) | `sector_flows` | `scripts/pipeline/compute_sector_flows.py` | `holdings_v2` + `fund_holdings_v2` + `market_data` | `queries.get_sector_flows` | Quarterly — same as above; ~2.1s end-to-end rebuild |
| `parent_fund_map` (perf-P2, migration 023) | `parent_fund_map` | `scripts/pipeline/compute_parent_fund_map.py` | `holdings_v2` + `fund_holdings_v2` + `ncen_adviser_map` + `fund_family_patterns` | `queries.holder_momentum` parent path | Quarterly — same as above; ~115s end-to-end rebuild (~38s parse + ~77s promote); 109,723 rows (55K EC + 54K DM × 147 parents with N-PORT children); rebuilds when the source tables advance |

All three pipelines use `amendment_strategy='direct_write'` (truncate-and-rewrite the precompute table from current source rows). Manual rebuild:

```bash
# perf-P0 — peer_rotation_flows
python3 scripts/pipeline/compute_peer_rotation.py --auto-approve

# perf-P1 — sector_flows_rollup
# (no flag = full fetch+parse+validate+promote; --staging halts at pending_approval; --dry-run = read-only)
python3 scripts/pipeline/compute_sector_flows.py

# perf-P2 — parent_fund_map
python3 scripts/pipeline/compute_parent_fund_map.py
```

Both subclasses are wired into `PIPELINE_REGISTRY` and `DATASET_REGISTRY` (L4) and stamp `data_freshness` via the base ABC's `approve_and_promote` step.

---

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

## Standing curation

Recurring curation that the pipelines absorb on each run. No action unless the trigger fires.

- **INF27 — CUSIP residual coverage.** `build_classifications.py` + `run_openfigi_retry.py` re-attempt unresolved CUSIPs on every classification rebuild. **Trigger to revisit:** net-increase in `pending` rows across two consecutive runs. Current scope is automatic; no human attention required while pending counts trend down or hold flat.

## Running Audits

`make audit` is the single entry point for the read-only audit / validation
suite. The runner (`scripts/run_audits.py`) invokes each underlying script as
a subprocess, captures pass/fail/manual results, prints a summary table, and
exits non-zero if any check fails.

```bash
make audit                          # all checks (recommended monthly)
make audit-quick                    # skip slow checks
python3 scripts/run_audits.py --verbose  # show full subprocess output
```

The runner does NOT alter any underlying script's logic — it only orchestrates
and summarises. Each wrapped script remains independently runnable.

| Check | Slow? | Description | Baseline |
|---|---|---|---|
| `check_freshness` | no | `data_freshness` staleness gate. Fails if any tracked-and-thresholded table is older than its threshold or untracked. | All critical tables fresh. |
| `verify_migration_stamps` | no | Every file in `scripts/migrations/` has a row in `schema_versions` on prod. Mechanises the `verify_migration_applied()` invariant from `docs/REMEDIATION_PLAN.md`. | All migrations stamped. |
| `validate_classifications` | no | CUSIP / fund-class classification BLOCK + WARN gates. BLOCK on missing classifications above tolerance; WARN on coverage degradation. | `READY: YES`, optional WARN tokens. |
| `validate_entities` | yes | Entity MDM structural + semantic gates (916 LOC). Writes `logs/entity_validation_report.json`. Structural gates exit 2 and block; non-structural exit 1 and surface for review. | All structural PASS; expect 1 non-structural FAIL on `wellington_sub_advisory` until INF3 lands. |
| `validate_phase4` | yes | Holdings/fund-holdings parity gates carried forward from the Phase 4 cutover. | All gates PASS post-Phase-4 promotion. |

Interpretation:

- **PASS** — exit 0 from the wrapped script. No action.
- **FAIL** — exit 1 (non-structural / BLOCK / staleness) or exit 2
  (structural). Open `logs/entity_validation_report.json` (entities) or the
  printed BLOCK token (classifications) and triage. A persistent expected
  failure (e.g. INF3) should be referenced in the relevant findings doc.
- **MANUAL** — exit 0 but stdout signals manual review needed
  (`validate_phase4` uses this for parity gates that need human sign-off).

For deeper triage on a single check, run it directly with `--verbose` or pass
`--prod` / `--staging` flags as documented in the script's own `--help`. The
runner targets prod by default — staging audits are out of scope for `make
audit` (use `python3 scripts/validate_entities.py --staging` etc.).

## Monthly maintenance

INF2 — run on the 1st of each month:

```bash
# Production health check
# (Expect 1 non-structural FAIL on wellington_sub_advisory until INF3 lands.)
python3 scripts/validate_entities.py

# Review unreviewed staging diffs (if any)
ls -lt logs/staging_diff_*.txt | head -5

# Check for overdue manual routings
# (look for the manual_routing_review gate row in the report)
cat logs/entity_validation_report.json | python3 -m json.tool | grep -A3 manual_routing_review

# Diff staging vs prod entity layer (catches drift between cycles)
python3 scripts/diff_staging.py
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

## Pipeline CLI contracts

### `scripts/fetch_finra_short.py` — `--dry-run` / `--apply`

Added in the `fetch-finra-short-dry-run` session (pre-Phase-B V5 gap). The
script downloads FINRA daily CNMS short-sale-volume files and writes
`short_interest` (PK `(ticker, report_date)`, upsert via `INSERT OR
IGNORE`) plus the `data_freshness` row for `short_interest`.

| Mode | Behaviour |
|------|-----------|
| `--apply` | Execute writes. Matches prior default behaviour exactly. |
| `--dry-run` | Fetch runs; DDL, inserts, `CHECKPOINT`, and `record_freshness` are all skipped. Prints `[DRY-RUN]` lines naming each intended write. |
| neither flag | Prints a stderr deprecation warning, then applies. Preserved for backward compatibility with any manual operator muscle memory. **Scheduled for removal on 2026-07-23** — tracked as `finra-default-flip` in ROADMAP Current backlog. |
| `--dry-run --apply` | Rejected by argparse (mutex group). |

The Makefile target `make fetch-finra-short` now passes `--apply`
explicitly. The disabled `scripts/scheduler.py` FINRA entry keeps its
existing `--staging --update` flags — when it is re-enabled, add
`--apply` at the same time to silence the deprecation warning.

**Tests:** `tests/pipeline/test_fetch_finra_short.py` exercises the CLI
surface via `subprocess.run`, with a local HTTP 404 stub bound to
`FINRA_BASE_URL_OVERRIDE` so FINRA's CDN is not contacted. DB isolation
uses the `--test` path (`data/13f_test.duckdb`), re-seeded per test.

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

## Log Rotation

The `logs/` directory accumulates run output, parity reports, and
staging diffs across every pipeline invocation. Without rotation it
grows unboundedly — 189 files / 31 MB by April 2026, with some entries
dating to the start of the project.

**Policy:**

| Age        | Action                         |
|------------|--------------------------------|
| 0–7 days   | keep uncompressed              |
| >7 days    | compress with `gzip`           |
| >90 days   | delete (compressed or not)     |

The "compress >7d, delete >90d" rule gives roughly three months of
searchable history in ~10% of the raw disk footprint.

**How to run:**

```bash
# Preview actions without touching files
make rotate-logs-dry

# Apply the policy
make rotate-logs
```

Both targets shell out to `scripts/rotate_logs.sh`. The script is
idempotent, restart-safe, and ignores symlinks and non-regular files.
Zero-byte files are skipped on the compress step (gzip'ing an empty
file is wasted work).

**Recommended cadence:** weekly, or immediately before any
`make quarterly-update` run if `du -sh logs/` is above ~50 MB. Not
wired into `quarterly-update` itself — the pipeline should not silently
discard diagnostic output mid-run.

**First-time rollout:** run `make rotate-logs-dry` first and review the
action list. Some logs (e.g. `phase35_resolution_results.csv`,
`entity_build_conflicts.log`) may be worth archiving manually before
letting the 90-day delete rule take effect.

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

## Snapshot retention

Every `%_snapshot_%` table has a governance row in `snapshot_registry`
(created by migration `018_snapshot_registry`). The registry records
the base table, creator, purpose, expiration, and approver so
retention can be enforced without parsing table names.

**Policy**

- **Default retention:** 14 days from `created_at`. Every snapshot
  minted by `scripts/promote_staging.py` writes a registry row with
  `applied_policy='default_14d'` and `expiration = created_at + 14
  days`.
- **Carve-outs:** declared at creation (or via manual UPDATE against
  the registry) with `applied_policy='carve_out'`, an explicit
  `expiration` date, and a named `approver`. Carve-outs are retained
  until their expiration passes.
- **Untagged snapshots:** if a `%_snapshot_%` table appears in the DB
  without a registry row, the enforcement script reports it as
  `UNREGISTERED` and **never auto-deletes** it. An operator must
  register it (or drop it manually) to bring it under policy.

**Enforcement — `scripts/hygiene/snapshot_retention.py`**

```bash
# Report only — no writes, no DDL. Default mode.
python3 scripts/hygiene/snapshot_retention.py --dry-run

# Execute: DROP TABLE + DELETE from snapshot_registry where expiration <= today().
# Also prunes registry rows whose snapshot table has gone missing.
python3 scripts/hygiene/snapshot_retention.py --apply
```

Exit codes: `0` clean run, `2` DB missing, `3` `snapshot_registry`
missing (run migration 018 first).

**Cadence.** Recommended weekly run against production. The default
`--dry-run` mode is safe to wire into CI or a nightly cron; operator
review is only needed before `--apply`.

**Restoring a carve-out after deletion.** Once `--apply` has dropped a
snapshot, it is unrecoverable short of a DuckDB EXPORT DATABASE
restore. Mark carve-outs in the registry **before** the expiration
date passes.

## Pending Audit Work

All items below must go through the staging workflow:

- **L5 parents 201-720 audit** (batches of 100)
- **L4 classification audit** (13 categories)
- **DM15e** — 7 prospectus-blocked umbrella trusts (Gotham, Mairs & Power, Brandes, Crawford, Bridges, Champlain, FPA). Blocked behind DM6 (N-1A parser) or DM3 (N-PORT metadata extension); not actionable in current Tier 2 scope.

## Completed Audit Work

- **Securian / Sterling** — **Closed 2026-04-10 (DM12, `ada58ac`)**. Confirmed stale and re-verified read-only against prod by `docs/findings/dm-open-surface-2026-04-22.md` §3.1.
- **HC Capital Trust (7 sub-adviser routings)** — **Closed 2026-04-10 (DM12, `ada58ac`)**. Original MAINTENANCE count of 5 was understated; actual scope 7. Re-verified §3.2 of the dm-open-surface audit.
- **CRI / Christian Brothers (5 missing series routings)** — **Closed 2026-04-10 (DM12, `ada58ac`)**. Original MAINTENANCE count of 4 was understated; actual scope 5. Re-verified §3.3 of the dm-open-surface audit.
- **DM13 ADV Schedule A residual sweep** — **Closed 2026-04-26/27 across PRs #168 / #169 / #170 / #173**. 797 relationships suppressed (Cat A self-loops 131; Cat B+C non-operating / redundant 107; Cat D+E dormant / residual 559) + 2 hard-deleted by DM15f/g. Override ID ranges 258–388 / 389–495 / 496–1054. Promote snapshots `20260426_134015` / `20260426_171207` / `20260426_174146` / `20260427_045843`.
- **DM15d (N-CEN-resolvable umbrella trusts)** — **Closed 2026-04-27 as no-op (PR #174)**. Sterling Capital / NEOS / Segall Bryant are single-adviser trusts (52 rows are all `role='adviser'`, zero `role='subadviser'`); the DM15b/L2 retarget pattern is not applicable. Two entity-merge candidates surfaced as side-observations: INF48 (NEOS dupe eids 10825 vs 20105) and INF49 (Segall Bryant dupe eids 254 vs 18157).
- **DM15f / DM15g** — **Closed 2026-04-26 (PR #170)**. 2 ADV Schedule A false-positive `wholly_owned` edges hard-`DELETE`d (StoneX→StepStone rel 14408; Pacer→Mercer rel 12022) along with their DM13-B/C suppression overrides (override_ids 425, 488).

## Stage 5 Cleanup — CLOSED 2026-04-13

Legacy `holdings` / `fund_holdings` / `beneficial_ownership` tables dropped from prod and staging. EXPORT DATABASE backup taken before mutation. Four INF9d eids verified as live PARENT_SEEDS brand shells and preserved. All writers repointed to v2 successors. Commits: `305739e` (primary drop), `7247689` (write-path follow-up).

## Post-hoc Writer Ordering on `managers` — CLOSED (Wave 2 retirement)

The post-hoc writer-ordering hazard documented in prior revisions (three writers — `build_managers.py`, `fetch_13dg.py` Phase 3 `has_13dg` stamp, `fetch_ncen.py` `adviser_cik` stamp — running in implicit Makefile-enforced sequence) no longer applies:

- `fetch_13dg.py` retired to `scripts/retired/` (Wave 2 w2-01). `has_13dg` post-hoc stamp on `managers` was not ported; the live `Load13DGPipeline` writes only `beneficial_ownership_v2` + `beneficial_ownership_current`.
- `fetch_ncen.py` retired to `scripts/retired/` (Wave 2 w2-04). The `adviser_cik` stamp on `managers` is now owned by `scripts/pipeline/load_ncen.py._update_managers_adviser_cik` and fires atomically inside the subclass's `approve_and_promote()`.
- `build_managers.py` no longer carries the `has_13dg` / `adviser_cik` ALTER+UPDATE tail; those columns are not populated from the canonical builder.

Sequencing for the remaining `managers` writer (`build_managers.py` DROP+CTAS) is handled by the Makefile `quarterly-update` target. The "Follow-on candidate (x) sentinel check in fetch_13dg.py / fetch_ncen.py" proposal is retired — it targeted scripts that no longer exist in the ingest path.
