# Admin Refresh System — Design Document

**Version:** 3.2 — supersedes v3.1 (2026-04-17 later same session). Ready for Claude Code + Codex review.

**Scope:** User-triggered data refresh system backed by pure-APPEND fact tables with unified amendment semantics across all three amendable sources (13F, N-PORT, 13D/G). Delivered as a framework — `SourcePipeline` base class, shared control plane, admin UI — not a one-off loader. All six existing pipelines migrate to the framework in sequence.

---

## Current State as of 2026-04-19 (Status Annotation)

This section tracks build progress against the design. Added post-authoring; does not modify design intent.

**Live on prod DB** (`data/13f.duckdb`):

| Control-plane table | Rows | Status |
|---|---|---|
| `ingestion_manifest` | 21,339 | **DONE** (migration `001_pipeline_control_plane.py`) |
| `ingestion_impacts` | 29,531 | **DONE** |
| `data_freshness` | 25 | **DONE** (commit `731f4a0` create, `2892009`/`54bfaad`/`831e5b4` hooks) |
| `pending_entity_resolution` | 6,874 | **DONE** |
| `admin_preferences` | — | **PENDING** (table not created; blocks auto-approve) |

**Framework code** (`scripts/pipeline/`):

| Component | Status | Notes |
|---|---|---|
| `manifest.py` — ingestion_manifest + impacts helpers | **DONE** | sequence-safe inserts, open/close helpers |
| `protocol.py` — SourcePipeline/DirectWrite/Derived Protocols | **PARTIAL** | Structural `typing.Protocol` (runtime_checkable), not the ABC base class specified in §4. Three protocols exist (§4 calls for single ABC). Decision: accept divergence or retrofit to ABC. |
| `discover.py` — anti-join against ingestion_manifest | **DONE** | per-source discover() patterns |
| `registry.py` — dataset spec registry | **DONE** | owner + layer metadata |
| `shared.py` — `stamp_freshness()` wrapper | **DONE** | delegates to `db.record_freshness` |
| `cadence.py` + `PIPELINE_CADENCE` dict + probe_fns | **PENDING** | file does not exist; §6 + §7 fully blocked |
| `base.py` — concrete SourcePipeline base class with `run()` orchestrator | **PENDING** | not created; §4 shared helpers live on per-pipeline scripts today |

**Pipeline-level freshness + checkpoint retrofits:**

| Pipeline | Status | Commits |
|---|---|---|
| `load_13f.py` — record_freshness + CHECKPOINT + --dry-run + fail-fast | **DONE (as in-place rewrite, not `load_13f_v2.py`)** | `8e7d5cb`, `14a5152`, `a58c107` (phase 4 prod apply) |
| `build_shares_history.py` — CHECKPOINT/dry-run/freshness | **DONE** | `41fee8a` |
| `fetch_nport_v2.py` — 4-mode orchestrator, DERA ZIP primary, `--limit`/`--all` | **DONE** | `44bc98e`, `f02cefa` |
| `fetch_nport.py` (legacy) — retired | **DONE** | `6909031` (moved to `scripts/retired/`), `12e172b` (removed from admin run_script allowlist), `8c654d9` (pipeline inventory marked retired) |
| `fetch_ncen.py` — record_freshness stamp | **DONE** | `54bfaad` batch |
| `enrich_13dg.py` — freshness guard | **DONE** | `54bfaad` batch |
| `fetch_13dg_v3.py` on SourcePipeline (phase 7) | **PENDING** | current `fetch_13dg.py` not on framework |
| `fetch_market_v2.py` on SourcePipeline — `direct_write` (phase 8) | **PENDING** | |
| `fetch_ncen_v2.py` / `fetch_adv_v2.py` on SourcePipeline — `scd_type2` (phase 9) | **PENDING** | |

**Makefile + check_freshness gate:**

| Target | Status | Commits |
|---|---|---|
| `make freshness` / `make status` / `make quarterly-update` | **DONE** | `831e5b4` |
| `scripts/check_freshness.py` read-only gate | **DONE** | `831e5b4` |
| `make schema-parity-check` | **DONE** | `c4e802c`/`4ec0862` |

**Migration 008 (add `is_latest` / `loaded_at` / `backfill_quality` to 3 amendable tables):**

**PENDING — and number collides.** Migration slot `008_` is already used by `008_rename_pct_of_float_to_pct_of_so.py` (unrelated). Current column presence on prod:

| Table | accession_number | is_latest | loaded_at | backfill_quality |
|---|---|---|---|---|
| `holdings_v2` | ✅ (from phase 4 rewrite) | ❌ | ❌ | ❌ |
| `fund_holdings_v2` | ❌ | ❌ | ✅ | ❌ |
| `beneficial_ownership_v2` | ✅ (pre-existing) | ❌ | ✅ | ❌ |

**Decision needed:** renumber this migration to the next free slot (likely `009_`) and update §5 DDL/rollback + §12 phase 3 references. Do not reuse `008_`.

**Admin blueprint endpoints (`scripts/admin_bp.py`):**

Current router (INF12 token-gated, commit `d51db60`) exposes: `/add_ticker`, `/stats`, `/progress`, `/errors`, `/run_script`, `/manager_changes`, `/ticker_changes`, `/parent_mapping_health`, `/stale_data`, `/merger_signals`, `/new_companies`, `/data_quality`, `/staging_preview`, `/running`, `/entity_override`.

| Design endpoint (§2b, §8, §11) | Status |
|---|---|
| `POST /admin/refresh/{pipeline}` | **PENDING** |
| `GET  /admin/run/{run_id}` (poll status) | **PENDING** |
| `GET  /admin/status` (dashboard feed) | **PENDING** (approximated by `/stats` + `/stale_data` but not design shape) |
| `GET  /admin/probe/{pipeline}` (cached EDGAR probe) | **PENDING** |
| `GET  /admin/runs/pending` | **PENDING** |
| `GET  /admin/runs/{id}/diff` | **PENDING** |
| `POST /admin/runs/{id}/approve` | **PENDING** |
| `POST /admin/runs/{id}/reject` | **PENDING** |
| `POST /admin/rollback/{run_id}` | **PENDING** |

**Frontend:**

| Component | Status | Commits |
|---|---|---|
| `FreshnessBadge` wired into all 11 tabs | **DONE** | `83836ee`, `3526757` |
| Admin status dashboard tab (§8) | **PENDING** | |
| Data Source tab (§9, renders `docs/data_sources.md` + runtime timeline SVG) | **PENDING** | `Plans/data_sources.md` exists; not yet copied to `docs/` or wired to React |

**Data Source doc:**

`docs/data_sources.md` — **PENDING move-and-commit.** Content authored at `Plans/data_sources.md` (2026-04-17); needs to be moved into repo at `docs/data_sources.md` before UI tab can import it.

### Gate list before Admin UI tab (§13) can ship

Ordered dependencies derived from §12:

1. Renumber migration 008 → 009 (or next free) in §5 + §12 phase 3.
2. Create `scripts/pipeline/base.py` with concrete `SourcePipeline.run()` orchestrator (phase 2) — or reconcile existing structural Protocols with §4's ABC contract.
3. Apply migration 009 on three amendable tables + backfill with quality stats (phase 3).
4. `queries.py` sweep adds `WHERE is_latest=TRUE` across all 13F/N-PORT/13D/G read paths (phase 4).
5. First pipeline on the framework with `append_is_latest`: formal `load_13f_v2.py` or extract-to-base of current `load_13f.py` (phase 5).
6. `scripts/pipeline/cadence.py` with `PIPELINE_CADENCE` + probe_fns + stale thresholds + `expected_delta` anomaly ranges (phase 10).
7. Create `admin_preferences` table + 9 admin endpoints listed above (phase 11).
8. Move `Plans/data_sources.md` → `docs/data_sources.md` + ship read-only Data Source tab (phase 12).
9. Ship Admin status dashboard tab (phase 13).

Steps 6–9 are the critical path; steps 1–5 gate them. Nothing on the critical path is currently in progress.

---

**Prior version changes (v3.1 → v3.2):**
- Section 2b added: diff review and approval workflow for runs of any size. Tiered presentation, automatic anomaly detection, asynchronous approval with 24-hour staging retention, opt-in auto-approval per pipeline, special-case handling for migration 008 and historical backfills.
- Section 2a step 4 updated to reference the approval gate. Run state machine expanded with `pending_approval`, `approved`, `rejected`, `expired` states.
- `PIPELINE_CADENCE` extended with `expected_delta` ranges per pipeline for anomaly detection.
- New control-plane table `admin_preferences` for per-user per-pipeline auto-approval configuration.

**Prior version changes (v3.0 → v3.1):**
- Staging-first flow promoted to a first-class core principle (section 2) and documented as an explicit eight-step sequence (section 2a). No pipeline writes to prod before step 5 under any circumstance.
- `SourcePipeline` abstract contract updated: `fetch()` and `parse()` receive staging connections only; prod connection is not exposed to subclasses.
- Reviewer questions expanded to include staging flow completeness.

**Prior version changes (v2 → v3):**
- No deadline. Build this right takes precedence over May 16 readiness.
- Migration 008 expanded from `holdings_v2` only to all three amendable tables (`holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`).
- `SourcePipeline` base class formalized. All six pipelines migrate to it.
- `entity_gate_check` and control-plane write patterns standardized across pipelines while the code is open.
- Backup retention decided: 14 days, pruned on promote.
- Timeline SVG: runtime render from `PIPELINE_CADENCE` config.
- Test plan added.

---

## 1. Three Deliverables

1. **Data Source documentation** — markdown at `docs/data_sources.md` rendered in a read-only UI tab with runtime-generated filing cadence timeline. Content authored 2026-04-17.
2. **Admin tab** — per-pipeline status cards with latest update date, next expected date, stale flag, new-data-available probe, row counts from last run, manual refresh button, run history drilldown.
3. **Pipeline framework** — `SourcePipeline` base class + migration 008 + six pipeline migrations. Target is a uniform refresh mechanism across 13F, N-PORT, 13D/G, N-CEN, ADV, and market data.

---

## 2. Core Principles

1. **User-triggered only.** No cron. Reminders surface overdue refreshes; user clicks a button to run. Optional auto-refresh is future work.
2. **Staging-first, always.** No pipeline writes directly to prod under any circumstances. Every run follows the eight-step staging flow documented in section 2a. This rule applies to all amendment strategies (`append_is_latest`, `scd_type2`, `direct_write`). A pipeline that bypasses staging is a bug, not an optimization.
3. **Pure APPEND.** No row is ever deleted from a fact table. Amendments land as new rows; prior rows have `is_latest` flipped to FALSE. Storage grows monotonically. History queryable at any point-in-time via `accession_number` and `loaded_at`.
4. **One framework, six pipelines.** `SourcePipeline` base class owns control-plane writes, staging flow, validation gates, promote, snapshot, rollback, entity gate, and freshness stamping. Concrete pipelines override three abstract methods: `fetch()`, `parse()`, `target_table_spec()`.
5. **Idempotent.** Running the same refresh twice against unchanged EDGAR state produces zero net change. Accession-level dedupe at the fetch stage is the gate.
6. **Observable.** Every run writes one row to `ingestion_manifest` and N rows to `ingestion_impacts`. Per-tuple actions recorded: `insert`, `flip_is_latest`, `scd_supersede`.
7. **Reversible.** `ingestion_impacts` supports `/admin/rollback/{run_id}` — DELETE inserted rows, flip `is_latest` back on superseded rows, reverse SCD Type 2 closures. Snapshot retained for 14 days as a second layer of safety.
8. **Fail safe.** A broken fetch cannot corrupt prod. Validation failures halt before promote. Prod snapshot taken before every promote.
9. **Reference data uses SCD Type 2.** N-CEN and ADV carry `valid_from` / `valid_to`. Latest version wins for current-view queries; history preserved for point-in-time.

---

## 2a. The Staging Flow

Every refresh runs these eight steps in order. The admin UI surfaces each step as a progress indicator on the run detail view.

```
Step   Action                    DB written        Reversible without rollback?
───    ───────────────────       ────────────      ───────────────────────────
1      fetch                     13f_staging       yes (drop staging table)
2      parse                     13f_staging       yes
3      validate                  read-only         n/a
4      diff (review summary)     read-only         n/a
5      snapshot prod             backups/          yes (keep snapshot)
6      promote                   13f.duckdb        no (impacts log is reverse plan)
7      verify post-promote       read-only         n/a
8      cleanup staging           13f_staging       yes
```

**Step 1 — Fetch.** `fetch()` writes raw source data into staging DB only. Staging DB path: `data/13f_staging.duckdb`. Manifest row created with `status='fetching'`. EDGAR rate limits respected per PROCESS_RULES §4.

**Step 2 — Parse.** `parse()` transforms raw staging tables into typed staging tables matching the target schema. Manifest row updated to `status='parsing'`.

**Step 3 — Validate.** Validation runs read-only queries against staging. Three severity levels: BLOCK (refuse to promote), FLAG (record, continue), WARN (log only). Entity gate check runs here — unresolved CIKs / series_ids are queued into `pending_entity_resolution` on prod but do not block promote (they are post-facto resolvable).

**Step 4 — Diff and approval.** Compute row-level delta between staging and prod for the affected scope. Run anomaly detection against expected-range rules from `PIPELINE_CADENCE`. Render summary dashboard plus anomaly flags in admin UI. Run enters `pending_approval` state. User reviews and clicks Approve or Reject. See section 2b for full presentation design, anomaly detection rules, and async approval workflow.

**Step 5 — Snapshot.** Take a snapshot of the prod target table before mutation. Location: `data/backups/{pipeline}_{run_id}.duckdb`. Retention: 14 days (section 10). This is second-layer safety beyond `ingestion_impacts`.

**Step 6 — Promote.** Atomic transaction against prod DB. Dispatch by amendment strategy:
- `append_is_latest` — UPDATE `is_latest=FALSE` on prior rows, INSERT staged rows.
- `scd_type2` — UPDATE `valid_to=now()` on superseded rows, INSERT staged rows.
- `direct_write` — UPSERT staged rows on natural key.

Every row mutation recorded in `ingestion_impacts` with `run_id`, action, rowkey, prior_accession. Manifest row updated to `status='complete'`.

**Step 7 — Verify.** Re-run validation gates against prod (not staging). This catches the rare case where promote writes differ from staging intent. If verify fails, manifest row flagged `status='verify_failed'` and alert surfaced in admin UI.

**Step 8 — Cleanup.** Drop staging tables for this run unless `--keep-staging` flag was passed. Prune snapshots older than 14 days. Refresh `13f_readonly.duckdb` snapshot for app reads.

### What never happens

- No pipeline ever opens prod DB in write mode during steps 1 to 4.
- No pipeline ever writes to prod DB during validation failure.
- No pipeline ever uses DROP+CTAS or TRUNCATE on prod fact tables.
- Staging DB is ephemeral. Staging data does not survive past step 8 unless explicitly retained.

### Admin UI integration

Clicking `[ Refresh 13F ]` triggers all eight steps as one action. The run detail view shows a progress bar with the current step highlighted. If validation fails at step 3, the diff and staging data are preserved for human inspection; the user sees a failure card with a link to the validation report and a `[ Retry after fixing ]` button.

---

## 2b. Diff Review and Approval

### The problem

Step 4 of the staging flow (diff review) is the human gate before mutation. But diff sizes vary by three orders of magnitude:

- **Daily market refresh**: ~6,000 rows changed
- **13F amendment refresh**: ~500 to 2,000 rows changed
- **Full 13F quarterly refresh**: ~3 million rows inserted
- **Missing-quarter backfill**: ~3 million rows inserted
- **Migration 008 backfill**: 12 million plus rows mutated (handled separately, see below)

A human cannot row-review 3 million inserts. But an unreviewed 3 million insert promote is exactly where things silently go wrong. The design has to make structured review tractable at every scale without dropping the gate.

### Design principles

1. **Review is always required.** No diff skips the human gate. The question is only what the human reviews.
2. **Presentation scales with diff size.** Small diffs show full row lists; large diffs show summaries plus anomaly flags plus samples.
3. **Anomaly detection runs automatically.** The system computes expected-range checks before the human sees the diff. Outliers surface as flags, not as silent approvals.
4. **Approval is asynchronous.** Staging data persists for up to 24 hours awaiting user approval. User reviews on their own schedule, not blocked at terminal.
5. **Auto-approval is opt-in, per pipeline, with conditions.** Never default. User can configure "auto-approve market data refresh when delta is within 10 percent of expected" but must explicitly enable it.

### Tiered diff presentation

| Diff size | What the UI shows |
|---|---|
| **Small** (<1,000 rows) | Full row list. Side-by-side comparison of prior vs new values. Expandable row detail. |
| **Medium** (1K–100K rows) | Row list with pagination, plus summary dashboard, plus anomaly flags, plus random sample of 50 rows across the delta. |
| **Large** (100K+ rows) | Summary dashboard only. Anomaly flags. Stratified sample of 100 rows (10 largest, 10 smallest, 10 from each decile by market value). No full list. |

### Summary dashboard — always shown

Every diff, regardless of size, renders this at the top:

```
┌──────────────────────────────────────────────────────────────────┐
│  13F Holdings — 2026Q1 refresh pending approval                  │
│  Run ID: load_13f_2026Q1_20260516_143022                         │
│  Staging completed: 2026-05-16 14:35:18 UTC                      │
│  Staging retained until: 2026-05-17 14:35:18 UTC                 │
├──────────────────────────────────────────────────────────────────┤
│  Row-level delta                                                 │
│  ─────────────────────────────────────────────                  │
│  Inserts:              2,847,193                                 │
│  is_latest flips:              0                                 │
│  Touched rows total:   2,847,193                                 │
│                                                                  │
│  Filer-level delta                                               │
│  ─────────────────────────────────────────────                  │
│  New filers this quarter:       147                              │
│  Returning filers:          11,700                               │
│  Filers with amendments:          0                              │
│  Filers pending entity resolution: 42                            │
│                                                                  │
│  Comparison to prior quarter                                     │
│  ─────────────────────────────────────────────                  │
│  Prior Q4 2025 rows added: 2,913,847                             │
│  Delta vs prior:           −2.3% (within expected ±20%)          │
│  Top 100 institutions:     100 of 100 present ✅                 │
│                                                                  │
│  Data quality                                                    │
│  ─────────────────────────────────────────────                  │
│  QC BLOCK:   0  ✅                                               │
│  QC FLAG:    7  (click to review)                                │
│  QC WARN:   23                                                   │
├──────────────────────────────────────────────────────────────────┤
│  ⚠️ Anomalies (3)                                                │
│  • Ticker NVDA: holder count up 340% QoQ (642 → 2,826 filers)    │
│  • Ticker XYZZY: 0 filers (was 12 in Q4) — delisted?             │
│  • Filer CIK 0001234567: reported $0 AUM (was $4.2B in Q4)       │
├──────────────────────────────────────────────────────────────────┤
│  [ View sample rows ]  [ View QC flags ]  [ View anomalies ]    │
│                                                                  │
│  [ ✅ Approve and promote ]  [ ❌ Reject and review staging ]    │
└──────────────────────────────────────────────────────────────────┘
```

### Anomaly detection

Computed automatically at diff time. Each pipeline declares its expected-range rules in `PIPELINE_CADENCE`. Baseline checks for 13F:

- **Total row delta vs prior quarter**: flag if outside ±20%.
- **Filer count delta**: flag if outside ±10%.
- **Top 100 institutions by AUM**: alert if any missing from this quarter.
- **Per-ticker holder count**: flag tickers with >50% QoQ change in holder count.
- **Per-filer AUM**: flag filers with >50% QoQ AUM change.
- **QC failures**: any BLOCK auto-rejects; FLAGs listed for review; WARNs shown in summary.
- **Pending entity resolution count**: flag if >100 new pending CIKs (suggests a new fund family or filer that should be resolved before promote).

Flags are descriptive, not blocking. The user decides whether a 340% jump in NVDA holders is real (AI rally) or a parsing bug. Flags just make sure the user sees it.

### Pipeline-specific expected ranges

Added to `PIPELINE_CADENCE`:

```python
"13f_holdings": {
    # ...existing fields...
    "expected_delta": {
        "row_delta_vs_prior": (-0.20, +0.20),   # ±20%
        "filer_delta_vs_prior": (-0.10, +0.10),  # ±10%
        "min_rows": 2_000_000,   # alert if below
        "max_rows": 4_000_000,   # alert if above
        "max_new_pending": 100,
    },
},
"nport_holdings": {
    "expected_delta": {
        "row_delta_vs_prior_month": (-0.15, +0.15),
        "min_rows": 800_000,
        "max_rows": 1_500_000,
    },
},
"market_data": {
    "expected_delta": {
        "row_delta_vs_prior_day": (-0.05, +0.05),
        "min_rows": 5_000,
        "max_rows": 7_000,
    },
},
# ...others...
```

### Asynchronous approval workflow

Update to step flow from section 2a:

```
Step   Action                    Run status
───    ───────────────────       ───────────────────
1      fetch                     fetching
2      parse                     parsing
3      validate                  validating
4      diff + anomaly scan       pending_approval  ← NEW waiting state
4a     [human reviews in UI]     pending_approval
4b     [human approves]          approved
5      snapshot prod             promoting
6      promote                   promoting
7      verify                    verifying
8      cleanup                   complete
```

Run states: `fetching`, `parsing`, `validating`, `pending_approval`, `approved`, `promoting`, `verifying`, `complete`, `failed`, `rejected`, `expired`.

**`pending_approval`**: staging data written, diff computed, awaiting user click. Visible in admin UI as a highlighted card. Staging data retained up to 24 hours.

**`approved`**: user clicked Approve. Promote begins. Cannot be recalled once promote starts (rollback endpoint is the recourse after).

**`rejected`**: user clicked Reject. Staging retained with reject reason for inspection. Manifest row marked rejected; no prod mutation.

**`expired`**: 24 hours elapsed without user action. Staging dropped. Run marked expired. User sees notification next login. No prod mutation.

### Approval endpoints

```
GET  /admin/runs/pending        → list of runs awaiting approval
GET  /admin/runs/{id}/diff      → diff summary + anomalies + samples
POST /admin/runs/{id}/approve   → transition pending_approval → approved
POST /admin/runs/{id}/reject    → transition pending_approval → rejected
                                   body: {reason: str}
```

### Opt-in auto-approval (configurable per pipeline)

Per-user preference stored in `admin_preferences` table (new, trivial schema):

```sql
CREATE TABLE admin_preferences (
    user_id VARCHAR,
    pipeline_name VARCHAR,
    auto_approve_enabled BOOLEAN DEFAULT FALSE,
    auto_approve_conditions JSON,  -- e.g. {"max_anomalies": 0, "within_expected_range": true}
    PRIMARY KEY (user_id, pipeline_name)
);
```

If auto-approve enabled for a pipeline AND all conditions met (no anomalies, within expected range, zero QC blocks), run transitions directly from `validating` → `approved` → `promoting`. User is notified post-hoc. Can revoke any run within the 24-hour staging window via rollback if they change their mind.

Default is disabled for every pipeline. Market data is the most likely candidate to enable after a few clean runs establish the baseline.

### Special case — Migration 008

Migration 008 is not a refresh. Workflow is different:

1. Run against staging DB first (`data/13f_staging.duckdb`), not a temp staging table on prod.
2. Generate backfill quality report: direct vs inferred counts per table. This is the diff.
3. User reviews the report. If >2% inferred on any table, abort and investigate.
4. On approval, apply to prod with full DB backup taken first.
5. Post-migration verification: row counts match, all `is_latest=TRUE` correct, no orphan accession_numbers.

Migration 008 approval surface is a one-time dedicated admin action, separate from pipeline refresh. Button labeled "Run Migration 008" under a distinct "Migrations" section of the admin tab.

### Special case — Historical backfill (missing quarters)

Loading a quarter never previously loaded (e.g., backfilling 2023Q1 into a 2024-onward database) uses the normal refresh flow with a `--backfill` flag. Differences from normal refresh:

- Expected range checks relaxed (no prior quarter to compare to).
- Human approval required explicitly, even if auto-approve enabled.
- User confirms expected row count in the approval modal before promote begins.
- `backfill_quality='direct'` enforced — no inferred rows for historical loads.

### Special case — Rollback

Rollback is always synchronous and always human-approved. No auto-rollback, no async queue. User clicks rollback, sees the reverse impact summary, confirms. Rollback executes immediately. Rationale: rollback is rare, high-stakes, and always warrants direct attention.

---


### The pattern

```
Quarter 2026Q1 loaded for filer CIK 0001234567:

Initial 13F-HR filing, accession A1, loaded T1:
  INSERT 42 rows with accession_number=A1, is_latest=TRUE, loaded_at=T1

Amendment 13F-HR/A, accession A2, loaded T2 > T1:
  UPDATE holdings_v2
    SET is_latest = FALSE
    WHERE cik = 1234567 AND quarter = '2026Q1' AND accession_number = A1
  INSERT 40 rows with accession_number=A2, is_latest=TRUE, loaded_at=T2

Result:
  82 rows total in holdings_v2 for this filer+quarter
  40 rows with is_latest=TRUE (current truth)
  42 rows with is_latest=FALSE (audit trail)
```

### Application read path

All app queries filter `WHERE is_latest=TRUE` unless performing point-in-time or audit reads. The `queries.py` sweep is part of phase 4 — one commit updating every 13F/N-PORT/13D/G read path.

### Why this over alternatives

| Option | Approach | Why not |
|---|---|---|
| A (chosen) | APPEND rows, UPDATE `is_latest` on superseded rows | One UPDATE per amendment is cheap (amendment-size, not table-size). Read path is simple `WHERE is_latest=TRUE`. Storage grows with amendment count (acceptable). |
| B | APPEND only, compute latest via `ROW_NUMBER() OVER(...)` in a VIEW | Every read pays window-function cost on 12M+ rows. Not viable at current scale. |
| C | APPEND to `_raw` table, rebuild `_current` table on each run | Doubles storage and rebuild cost. Two tables to keep in sync. |

### Applied uniformly across three tables

| Table | Current strategy | Post-migration 008 |
|---|---|---|
| `holdings_v2` | `delete_insert(quarter)` | APPEND + `is_latest` |
| `fund_holdings_v2` | `delete_insert(series_id, report_month)` | APPEND + `is_latest` |
| `beneficial_ownership_v2` | `upsert(accession_number)` | APPEND + `is_latest` (already has accession_number, additive) |

Non-amendable tables (`market_data`, `ncen_adviser_map`, `adv_managers`) are unaffected. They use different patterns (direct_write, SCD Type 2) documented in section 4.

---

## 4. SourcePipeline Base Class

### Purpose

Today each pipeline re-implements the same patterns with subtle drift: staging DB connection, manifest insert, impact recording, entity gate, freshness stamp, snapshot, promote. The framework converges these onto a single base class. Concrete pipelines contain only source-specific logic — fetch, parse, schema mapping.

### Abstract contract

Concrete pipelines override three methods:

```python
class SourcePipeline(ABC):
    """Base class for all ingest pipelines.

    The base class enforces the staging-first discipline defined in section 2a.
    Concrete pipelines cannot bypass this — fetch() and parse() receive a
    staging-only connection; prod connection is never exposed to subclasses
    before step 5 (snapshot).
    """

    name: str                    # e.g. "13f_holdings"
    target_table: str            # e.g. "holdings_v2"
    amendment_strategy: str      # "append_is_latest" | "scd_type2" | "direct_write"
    amendment_key: tuple[str]    # e.g. ("cik", "quarter") for 13F

    @abstractmethod
    def fetch(self, scope: dict, staging_con: Connection) -> FetchResult:
        """Pull source data into raw staging tables.
           scope = {"quarter": "2026Q1"} or {"month": "2026-03"} etc.
           Writes only to staging_con. Returns list of accessions discovered + staged."""

    @abstractmethod
    def parse(self, staging_con: Connection) -> ParseResult:
        """Transform raw staging to typed staging ready for promote.
           Writes only to staging_con. Returns row counts, QC flags, errors."""

    @abstractmethod
    def target_table_spec(self) -> TableSpec:
        """Return column list, PK, indexes for the target fact table.
           Used by base class to drive promote SQL generation."""
```

### Shared base class methods

The base class provides these concrete methods. Pipelines inherit them unchanged. The `run()` method orchestrates the eight-step staging flow from section 2a.

```python
def run(self, scope: dict) -> str:
    """Full pipeline: steps 1-8 from section 2a.
       Returns run_id. Writes manifest + impacts throughout.
       Opens staging_con in write mode for steps 1-2,
       prod_con read-only for steps 3-4,
       prod_con in write mode only from step 5 onward."""

def validate(self) -> ValidationResult:
    """Run QC gates on staged data. Returns BLOCK/FLAG/WARN counts."""

def promote(self, run_id: str) -> PromoteResult:
    """Dispatch by amendment_strategy:
         append_is_latest -> _promote_append_is_latest()
         scd_type2        -> _promote_scd_type2()
         direct_write     -> _promote_direct_write()"""

def rollback(self, run_id: str) -> None:
    """Reverse all impacts from a run. DELETE insert actions,
       flip is_latest back on flip_is_latest actions, reverse SCD closures."""

def record_impact(self, run_id, action, rowkey, prior_accession=None) -> None:
    """Standardized ingestion_impacts write."""

def entity_gate_check(self, staged_rows) -> list[PendingEntity]:
    """Check every filer CIK / series_id resolves in entity_identifiers.
       Queue unresolved into pending_entity_resolution. Return list."""

def snapshot_before_promote(self) -> str:
    """DB snapshot of target_table before promote. Return snapshot_id."""

def prune_old_snapshots(self, retention_days: int = 14) -> int:
    """Drop snapshots older than retention_days. Return count pruned."""

def stamp_freshness(self, con: Connection) -> None:
    """data_freshness write, uniform signature."""
```

### Three amendment strategies

| Strategy | Used by | Promote SQL pattern |
|---|---|---|
| `append_is_latest` | 13F, N-PORT, 13D/G | UPDATE `is_latest=FALSE` on prior rows by `amendment_key`; INSERT new rows with `is_latest=TRUE`. |
| `scd_type2` | N-CEN, ADV | UPDATE `valid_to=now()` on superseded rows by `natural_key`; INSERT new rows with `valid_from=now()`, `valid_to=NULL`. |
| `direct_write` | Market data | UPSERT on natural key. No history preserved. |

### Why standardize now

The six pipelines today have near-identical patterns that diverged through iterative development. Since all six are being touched in this workstream anyway, converging them is the cheapest moment. The base class becomes genuine shared code rather than a template. Subsequent pipelines (future FINRA CAT, DTCC, etc.) plug in by implementing three abstract methods.

---

## 5. Schema Migration 008

### DDL

Three columns added to three tables. Identical column names and types across all three.

```sql
-- holdings_v2
ALTER TABLE holdings_v2 ADD COLUMN accession_number VARCHAR;
ALTER TABLE holdings_v2 ADD COLUMN is_latest BOOLEAN DEFAULT TRUE;
ALTER TABLE holdings_v2 ADD COLUMN loaded_at TIMESTAMP DEFAULT now();
ALTER TABLE holdings_v2 ADD COLUMN backfill_quality VARCHAR;  -- 'direct' | 'inferred'

-- fund_holdings_v2
ALTER TABLE fund_holdings_v2 ADD COLUMN accession_number VARCHAR;
ALTER TABLE fund_holdings_v2 ADD COLUMN is_latest BOOLEAN DEFAULT TRUE;
ALTER TABLE fund_holdings_v2 ADD COLUMN loaded_at TIMESTAMP DEFAULT now();
ALTER TABLE fund_holdings_v2 ADD COLUMN backfill_quality VARCHAR;

-- beneficial_ownership_v2 (already has accession_number, add only two columns)
ALTER TABLE beneficial_ownership_v2 ADD COLUMN is_latest BOOLEAN DEFAULT TRUE;
ALTER TABLE beneficial_ownership_v2 ADD COLUMN loaded_at TIMESTAMP DEFAULT now();
ALTER TABLE beneficial_ownership_v2 ADD COLUMN backfill_quality VARCHAR;

-- Indexes (DuckDB does not support partial indexes; non-partial is fine here)
CREATE INDEX idx_holdings_v2_accession ON holdings_v2(accession_number);
CREATE INDEX idx_holdings_v2_latest ON holdings_v2(is_latest, quarter);
CREATE INDEX idx_fund_holdings_v2_accession ON fund_holdings_v2(accession_number);
CREATE INDEX idx_fund_holdings_v2_latest ON fund_holdings_v2(is_latest, report_month);
CREATE INDEX idx_bo_v2_latest ON beneficial_ownership_v2(is_latest, subject_cik);
```

### Backfill plan per table

**`beneficial_ownership_v2`** (simplest — already has `accession_number`):
```sql
-- For each (filer_cik, subject_cik), mark the most recent accession is_latest=TRUE,
-- and all older accessions is_latest=FALSE.
UPDATE beneficial_ownership_v2 SET is_latest = FALSE;
UPDATE beneficial_ownership_v2 SET is_latest = TRUE
  WHERE (filer_cik, subject_cik, accession_number) IN (
    SELECT filer_cik, subject_cik, accession_number FROM (
      SELECT filer_cik, subject_cik, accession_number,
             ROW_NUMBER() OVER (PARTITION BY filer_cik, subject_cik
                                ORDER BY filing_date DESC) AS rn
      FROM beneficial_ownership_v2
    ) WHERE rn = 1
  );
UPDATE beneficial_ownership_v2 SET backfill_quality = 'direct';
UPDATE beneficial_ownership_v2 SET loaded_at = <manifest lookup or epoch>;
```

**`fund_holdings_v2`** (medium — join to `ingestion_manifest` by `(series_id, report_month)`):
```sql
-- Populate accession_number from ingestion_manifest where available.
UPDATE fund_holdings_v2 f
  SET accession_number = m.accession_number,
      loaded_at = m.completed_at,
      backfill_quality = 'direct',
      is_latest = TRUE
  FROM (SELECT series_id, report_month, accession_number, completed_at
        FROM ingestion_manifest
        WHERE pipeline_name = 'nport' AND status = 'complete') m
  WHERE f.series_id = m.series_id AND f.report_month = m.report_month;

-- Rows without a manifest match (pre-control-plane data) get inferred backfill.
UPDATE fund_holdings_v2
  SET accession_number = 'UNKNOWN_PRE_MIGRATION_008_' || series_id || '_' || report_month,
      is_latest = TRUE,
      backfill_quality = 'inferred',
      loaded_at = '2026-01-01'::TIMESTAMP
  WHERE accession_number IS NULL;
```

**`holdings_v2`** (hardest — legacy DELETE+INSERT collapsed amendments):
```sql
-- Step 1: Join holdings_v2 to filings_deduped on (cik, quarter).
-- Where exactly one accession matches, copy it directly (backfill_quality='direct').
-- Where multiple accessions match (~0.5%), take the newest (backfill_quality='inferred').
UPDATE holdings_v2 h
  SET accession_number = latest.accession_number,
      loaded_at = latest.filing_date::TIMESTAMP,
      is_latest = TRUE,
      backfill_quality = CASE WHEN latest.match_count = 1 THEN 'direct' ELSE 'inferred' END
  FROM (
    SELECT cik, quarter, accession_number, filing_date,
           COUNT(*) OVER (PARTITION BY cik, quarter) AS match_count,
           ROW_NUMBER() OVER (PARTITION BY cik, quarter
                              ORDER BY filing_date DESC) AS rn
    FROM filings_deduped
    WHERE form_type IN ('13F-HR', '13F-HR/A')
  ) latest
  WHERE h.cik = latest.cik AND h.quarter = latest.quarter AND latest.rn = 1;

-- Step 2: Rows with no matching accession (rare, expected <0.1%) get sentinel.
UPDATE holdings_v2
  SET accession_number = 'UNKNOWN_PRE_MIGRATION_008_' || cik || '_' || quarter,
      is_latest = TRUE,
      backfill_quality = 'inferred',
      loaded_at = '2026-01-01'::TIMESTAMP
  WHERE accession_number IS NULL;
```

### Rollback

Migration 008 is reversible:
```sql
ALTER TABLE holdings_v2 DROP COLUMN accession_number;
ALTER TABLE holdings_v2 DROP COLUMN is_latest;
ALTER TABLE holdings_v2 DROP COLUMN loaded_at;
ALTER TABLE holdings_v2 DROP COLUMN backfill_quality;
DROP INDEX idx_holdings_v2_accession;
DROP INDEX idx_holdings_v2_latest;
-- repeat for fund_holdings_v2 and beneficial_ownership_v2
```

Full DB backup taken before migration runs per PROCESS_RULES.

### Expected backfill stats

| Table | Rows | `direct` expected | `inferred` expected |
|---|---|---|---|
| `holdings_v2` | 12.27M | ~99.5% | ~0.5% (multi-accession (cik, quarter)) |
| `fund_holdings_v2` | 14.0M | depends on manifest coverage | balance |
| `beneficial_ownership_v2` | 51.9K | 100% (already has accession) | 0% |

Anomalies over 2% trigger abort plus investigation before the migration proceeds.

---

## 6. Per-Pipeline Cadence Metadata

`scripts/pipeline/cadence.py` — single Python dict drives admin UI reminders, "next expected" calculations, stale thresholds, and the runtime-rendered timeline SVG.

```python
from datetime import date, timedelta

PIPELINE_CADENCE = {
    "13f_holdings": {
        "display_name": "13F Holdings",
        "filing_form": "13F-HR",
        "cadence": "quarterly",
        "deadline_rule_days": 45,
        "amendment_window_days": 90,
        "stale_threshold_days": 135,
        "next_expected_fn": next_13f_deadline,
        "probe_fn": probe_13f_accessions,
    },
    "nport_holdings": {
        "display_name": "N-PORT Holdings",
        "filing_form": "NPORT-P",
        "cadence": "monthly",
        "public_lag_days": 60,
        "stale_threshold_days": 75,
        "next_expected_fn": next_nport_public_date,
        "probe_fn": probe_nport_accessions,
    },
    "13dg_ownership": {
        "display_name": "13D/G Ownership",
        "filing_form": ["SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"],
        "cadence": "event_driven",
        "stale_threshold_days": 14,
        "next_expected_fn": None,  # no predicted date
        "probe_fn": probe_13dg_accessions,
    },
    "ncen_advisers": {
        "display_name": "N-CEN Advisers",
        "filing_form": "N-CEN",
        "cadence": "annual_rolling",
        "stale_threshold_days": 400,
        "next_expected_fn": next_ncen_batch_date,
        "probe_fn": probe_ncen_accessions,
    },
    "adv_registrants": {
        "display_name": "ADV Registrants",
        "filing_form": "Form ADV",
        "cadence": "annual",
        "stale_threshold_days": 400,
        "next_expected_fn": next_adv_deadline,
        "probe_fn": probe_adv_filings,
    },
    "market_data": {
        "display_name": "Market Data",
        "filing_form": None,
        "cadence": "daily",
        "stale_threshold_days": 3,
        "next_expected_fn": next_trading_day,
        "probe_fn": None,  # no EDGAR probe; staleness is time-based only
    },
}
```

Stale flag thresholds:
- **Green**: age < 50% of `stale_threshold_days`
- **Yellow**: age 50 to 100%
- **Red**: age at or above `stale_threshold_days`

---

## 7. "New Data Available" EDGAR Probe

### Requirement

Admin tab shows a blue dot when EDGAR has filings newer than our latest. Probe is cheap (returns index pages, not filing bodies) and cached.

### Implementation

Each pipeline's `probe_fn(con)` returns:
```python
{
    "new_count": int,                 # filings on EDGAR newer than our latest
    "latest_accession": str | None,   # newest accession observed
    "probed_at": datetime,
}
```

### Cache discipline

- **TTL cache**: 15 minutes in Flask app memory, keyed by pipeline name.
- **Rate limit**: probes go through `scripts/pipeline/shared.sec_fetch()`. Shared SEC 10 req/s budget.
- **Manual bypass**: admin tab button "Check for new filings now" forces a probe, ignoring cache.
- **Failure visible**: UI shows grey indicator plus "probe failed at HH:MM" tooltip when EDGAR errors.

### Failure does not block refresh

If the probe fails, the refresh button still works. Probe is informational. A failed probe is a UI signal, not a runtime dependency.

---

## 8. Admin UI — Status Dashboard

### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Data Refresh Status                        [Check all probes ↻]        │
├─────────────────────────────────────────────────────────────────────────┤
│  Pipeline          Last Run      Age    Status    New?   Rows Added    │
│  ─────────────────────────────────────────────────────────────────────  │
│  13F Holdings      2026-04-17    0 d    ● Green   —      +42,183       │
│  N-PORT Holdings   2026-04-16    1 d    ● Green   🔵 3    +10,503       │
│  13D/G Ownership   2026-04-16    1 d    ● Green   —      +3            │
│  N-CEN Advisers    2026-04-17    0 d    ● Green   —      +78           │
│  ADV Registrants   2026-03-15    33 d   ● Yellow  🔵 12   —            │
│  Market Data       2026-04-16    1 d    ● Yellow  —      +5,874 tickers│
├─────────────────────────────────────────────────────────────────────────┤
│  Next expected:  13F 2026Q1 — May 15   |   N-PORT Mar 2026 — May 31    │
├─────────────────────────────────────────────────────────────────────────┤
│  [ Refresh 13F ]  [ Refresh N-PORT ]  [ Refresh 13D/G ]                 │
│  [ Refresh N-CEN ]  [ Refresh ADV ]  [ Refresh Market ]                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ⚠️ Reminders:                                                          │
│  • 12 new ADV amendments available since last refresh                   │
│  • 3 new N-PORT filings available                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Per-card fields

- **Pipeline name** from `PIPELINE_CADENCE.display_name`.
- **Last run** — `MAX(completed_at)` from `ingestion_manifest` filtered by `pipeline_name`.
- **Age** — today minus last run.
- **Status** — green/yellow/red from `stale_threshold_days`.
- **New?** — count from cached probe; dash when zero or no probe.
- **Rows added last run** — from `ingestion_manifest.row_counts_json`.
- **Refresh button** — launches `POST /admin/refresh/{pipeline}`.

### Refresh click flow

1. User clicks `[ Refresh 13F ]`.
2. UI opens modal: "Refresh 13F Holdings for quarter: [2026Q1 ▼]". Default is newest overdue.
3. User confirms.
4. UI `POST /admin/refresh/13f_holdings?quarter=2026Q1`.
5. Server spawns subprocess, returns `run_id` immediately.
6. UI polls `GET /admin/run/{run_id}` every 10 seconds.
7. On complete, UI refreshes the status table.

### Run history drilldown

Clicking a pipeline row expands to last 20 runs: `run_id`, scope, start, duration, status, `rows_added`, `rows_flipped`, `pending_queued`. Clicking `run_id` opens full manifest detail plus log link.

---

## 9. Data Source UI Tab

Content in `docs/data_sources.md` — committed to repo, single source of truth.

Tab component:
- Fetches `/api/docs/data_sources` (returns markdown).
- Renders via existing markdown renderer (same one used in About tab).
- Generates cadence timeline SVG at runtime from `PIPELINE_CADENCE`. No hand-drawn SVG to maintain.

Timeline SVG spec:
```
Horizontal axis: days from quarter end (0, 30, 45, 60, 75, 90)
Events placed at their deadline offsets, colored by source
Tooltips on hover showing filing type + our coverage status
```

Tab is read-only. No buttons, no forms.

---

## 10. Backup and Snapshot Retention

### Per-run snapshots
- Taken by `SourcePipeline.snapshot_before_promote()` before each promote.
- Stored at `data/backups/{pipeline}_{run_id}.duckdb`.
- **Retention: 14 days.** Pruned by `prune_old_snapshots(14)` on every successful promote.

### Full DB backups
- Taken manually via `backup_db.py` before migrations, audit passes, or risky sessions.
- Not on a schedule. User decides frequency.
- Retention is user-managed.

### Rollback precedence
- First: `/admin/rollback/{run_id}` reverses impacts via `ingestion_impacts`.
- Second: restore snapshot taken before that run.
- Last resort: restore full DB backup.

---

## 11. Non-Functional Requirements

### Authentication
All admin endpoints gated by INF12 token middleware. Every admin action logged with user identity, timestamp, args.

### Concurrency
Same pipeline cannot run twice simultaneously. 409 Conflict returned. Different pipelines may run in parallel.

### Observability
- `ingestion_manifest` — one row per run.
- `ingestion_impacts` — per-tuple actions.
- `logs/{pipeline}_{run_id}.log` — per-run log file. UI links directly.
- Prometheus metrics export deferred.

### Multi-user (future)
- Add `requested_by` to `ingestion_manifest`.
- Admin vs analyst roles.
- Request queue for concurrent triggers on the same pipeline.

---

## 12. Implementation Sequence

| Phase | Status (2026-04-19) | Deliverable | Depends on |
|---|---|---|---|
| 1 | **DONE** | **Design doc v3.0+ + `docs/data_sources.md`** — this document. Data Source markdown authored at `Plans/data_sources.md`; not yet moved to `docs/`. | nothing |
| 2 | **PARTIAL** | **`SourcePipeline` base class** — `scripts/pipeline/base.py` with abstract contract plus shared helpers. Unit tests against a mock pipeline. *Today: three structural Protocols in `protocol.py`; no ABC base class with `run()` orchestrator.* | 1 approved |
| 3 | **PENDING (renumber to 009)** | **Migration 008** — schema change plus backfill on three tables. Run against staging first; validate backfill quality stats; promote. *Slot `008_` already used for `pct_of_float` rename; must renumber.* | 2 |
| 4 | **PENDING** | **`queries.py` sweep** — add `WHERE is_latest=TRUE` across all 13F/N-PORT/13D/G read paths. Smoke tests plus snapshot diffs. | 3 |
| 5 | **PARTIAL (in-place, not v2)** | **`load_13f_v2.py`** on `SourcePipeline` with `append_is_latest` strategy. First concrete implementation. *Today: `load_13f.py` rewritten in place (`8e7d5cb`, `a58c107`) with checkpoint/freshness/dry-run, but not yet on base class or `is_latest`.* | 2, 3, 4 |
| 6 | **PARTIAL (v2 not v3)** | **`fetch_nport_v3.py`** — retrofit N-PORT to `SourcePipeline` plus `is_latest`. Regression test amendment chains. *Today: `fetch_nport_v2.py` (`44bc98e`, `f02cefa`) is 4-mode orchestrator with DERA ZIP primary + freshness stamps, but not on base class and no `is_latest` column.* | 5 |
| 7 | **PENDING** | **`fetch_13dg_v3.py`** — retrofit 13D/G similarly. | 5 |
| 8 | **PENDING** | **`fetch_market_v2.py`** — market data on `SourcePipeline` with `direct_write` strategy. | 5 |
| 9 | **PENDING** | **`fetch_ncen_v2.py` + `fetch_adv_v2.py`** — SCD Type 2 strategy. *Current `fetch_ncen.py` has freshness stamp (`54bfaad`); not on framework.* | 5 |
| 10 | **PENDING** | **`scripts/pipeline/cadence.py`** — `PIPELINE_CADENCE` dict plus probe functions plus next-expected helpers. *File not created.* | 2 |
| 11 | **PENDING** | **Admin blueprint endpoints** — `/admin/status`, `/admin/refresh`, `/admin/run`, `/admin/probe`, `/admin/rollback`, `/admin/runs/pending`, `/admin/runs/{id}/diff`, `/admin/runs/{id}/approve`, `/admin/runs/{id}/reject`. *`admin_bp.py` carries INF12 token router (`d51db60`) with 15 unrelated endpoints; none of the 9 design endpoints present.* | 5 to 10 any subset live |
| 12 | **PENDING** | **Data Source UI tab** — React component. Renders `docs/data_sources.md` plus runtime timeline SVG. *`Plans/data_sources.md` exists; move-to-`docs/` + `/api/docs/data_sources` route + tab component pending.* | 1 (doc exists) |
| 13 | **PENDING** | **Admin UI tab** — React status dashboard plus refresh modals plus run history drilldown. *FreshnessBadge across 11 tabs is DONE (`83836ee`) but that is a read-only surface, not the dashboard.* | 11 |
| 14 | **PENDING** | **End-to-end test: full 13F refresh on Q1 2026** — first real production refresh using the framework. | 5, 11 |

Phases 6 to 9 can interleave. Phase 11 partial-ships as each pipeline migrates. Phases 12 and 13 ship in parallel once 11 exposes a stable endpoint set.

### Deferred (explicitly out of scope)
- Auto-refresh scheduler.
- Rollback UI action (endpoint exists; UI button ships in v2 of the admin tab).
- Prometheus metrics.
- Multi-user roles.

---

## 13. Test Plan

### Unit tests

- `SourcePipeline` base class — mock fetch/parse, verify correct control plane writes for each amendment strategy.
- Migration 008 backfill — against a fixture DB, verify `direct` vs `inferred` quality flags match expected ratios.
- Probe cache — verify TTL behavior, rate limit sharing.

### Integration tests

- **Amendment chain test for each pipeline**: load original, load amendment, verify `is_latest` flip is correct and audit trail preserved.
- **Idempotency test**: re-run same scope, verify zero net change.
- **Rollback test**: run then assert state A; rollback then assert state B matches pre-run state A minus this run.

### Regression tests

- Smoke test suite (existing 8/8) must pass throughout migration.
- Snapshot diffs on top 10 endpoints pre- and post-migration. No unexpected result shape changes.
- Response-count delta on key endpoints under 0.1%, allowing for corrected amendment handling.

### Manual acceptance tests

- Admin tab loads in under 2 seconds with all six probes cached.
- Refresh 13F Q1 2026 end-to-end against live EDGAR; verify UI reflects status transitions; verify `is_latest` correctness in spot-check queries.
- Data Source tab renders markdown correctly plus timeline SVG scales across viewport widths.

### Backfill acceptance

- `backfill_quality = 'direct'` must be at or above 99% on `holdings_v2`, exactly 100% on `beneficial_ownership_v2`.
- `fund_holdings_v2` direct ratio target at or above 90% (depends on manifest history completeness).
- Anomalies over 2% trigger abort plus investigation.

---

## 14. Open Questions

Only one remains:

**Migration 008 execution order.** Two options:
- **Sequential**: migrate `beneficial_ownership_v2` first (smallest, cleanest backfill), then `fund_holdings_v2`, then `holdings_v2`. Three promote cycles, more checkpoints, slower.
- **Single atomic migration**: all three tables in one transaction. Faster, but a backfill failure on `holdings_v2` rolls back the other two.

Recommend sequential. Lower risk, better observability on backfill quality stats per table. The extra time is cheap now that May 16 is not a constraint.

---

## 15. Next Step

Hand this doc to Claude Code plus Codex for review. Reviewer targets:

1. Does the staging flow in section 2a cover every pipeline pattern, including edge cases like partial fetch failures, resume-from-checkpoint, and multi-scope runs?
2. Does the diff review design in section 2b scale across diff sizes from 100 rows to 12 million? Are the tier boundaries (1K, 100K) correct, or should they shift?
3. Are the anomaly detection rules in `PIPELINE_CADENCE.expected_delta` tight enough to catch real problems without crying wolf on normal variance?
4. Is 24-hour staging retention long enough for async approval? Too long? Should it vary by pipeline?
5. Does `SourcePipeline` abstract contract cover every pattern in the six existing pipelines, or are there edge cases it cannot express?
6. Is the migration 008 backfill strategy safe on `holdings_v2`, specifically the "newest accession wins" heuristic on approximately 0.5% ambiguous rows?
7. Are the `PIPELINE_CADENCE` entries correct per SEC rules. Deadlines, public-lag windows, amendment cadences.
8. Does the probe rate-limit design respect PROCESS_RULES §4 under worst case (admin tab open in multiple browser sessions)?
9. Is the rollback design (impacts reversal plus snapshot fallback) sufficient, or do we need additional guarantees?

After review, incorporate feedback into v3.3, then write Claude Code prompts phase-by-phase starting with phase 2 (base class).
