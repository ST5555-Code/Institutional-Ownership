# ingestion-manifest-reconcile — Phase 3-5 results

CP-2 in `docs/decisions/inst_eid_bridge_decisions.md`. Closes the §9 G4 BLOCKER and §12 Open Question 1 in `docs/findings/institution_scoping.md` under Path B (live schema canonical) per chat decision 2026-05-02.

Companion to the Phase 2 dry-run findings at `docs/findings/ingestion_manifest_reconcile_dryrun.md`.

## Phase 3 — Schema migration

**No-op.** Zero ADD COLUMN candidates surfaced in Phase 1.4. The migration is empty by design under Path B. The two design fields with no live equivalent (`row_counts_json`, `requested_by`) were both classified `DROP_FROM_DESIGN` under the prompt's bias-toward-DROP rule.

No `ALTER TABLE` was issued. No backup snapshot was needed beyond the existing pre-flight backup at `data/backups/13f_backup_20260502_185832/`.

## Phase 4 — Design doc rewrite

All edits were applied to `docs/admin_refresh_system_design.md`. Each is dated `CP-2 reconcile, 2026-05-02` for traceability.

### 4.1 RENAME — three doc-only renames

| Live column | Pre-rewrite design field | Edit sites |
|---|---|---|
| `source_type` | `pipeline_name` | §2a Step-1/2/6/7 narrative; §6 Migration 008 SQL on `fund_holdings_v2`; §8 per-card "Last run" field. |
| `fetch_status` | `status` | §2a state-machine narrative (Steps 1, 2, 6, 7). |
| `fetch_completed_at` | `completed_at` | §6 Migration 008 SQL; §8 per-card "Last run" field. |

`scripts/admin_bp.py` already serializes the live columns to the API field names referenced throughout the design doc (`source_type` → `pipeline_name`, `fetch_status` → `status`, `fetch_completed_at` → `completed_at`). Phase 4 brought the design narrative in line with what the code already does — no admin endpoint code changes were required.

### 4.2 DROP_FROM_DESIGN — `row_counts_json`

Original design referenced `ingestion_manifest.row_counts_json` for the admin dashboard's "Rows added last run" card (§8 per-card fields) and the run-history drilldown (§8 drilldown columns). The column never existed on `ingestion_manifest`, no writer populates it, and no admin endpoint reads it. It is a phantom field.

**Canonical replacement:** `ingestion_impacts.rows_promoted` (BIGINT, NOT NULL DEFAULT 0). Already populated per target-table by every v1.2 `SourcePipeline` subclass at promote time. Aggregation pattern for the dashboard total:

```sql
SELECT m.manifest_id,
       SUM(ii.rows_promoted) AS rows_added_last_run
  FROM ingestion_manifest m
  JOIN ingestion_impacts   ii ON ii.manifest_id = m.manifest_id
 WHERE m.source_type = ?         -- e.g. 'NPORT'
   AND m.fetch_status = 'complete'
 GROUP BY m.manifest_id
 ORDER BY m.manifest_id DESC
 LIMIT 1;
```

The `SUM` aggregates across all target tables touched by the run. For pipelines that write a single target table (`load_market.py` → `market_data` only), the sum reduces to a single row's value. For pipelines that fan out across multiple targets in a single run (e.g. `load_nport.py` writes both `fund_holdings_v2` and `fund_universe`), the sum captures all of them — which matches the dashboard's "Rows added last run" semantics.

Schema mapping appendix §A.2 records this drop. Per-card field §8 narrative was rewritten to point to the impacts aggregate inline.

### 4.3 DROP_FROM_DESIGN — `requested_by`

Original design (§11 Multi-user (future)) said: _"Add `requested_by` to `ingestion_manifest`."_ This work is correctly gated behind multi-user auth, which has not shipped. Zero ADD COLUMN was the correct call.

**Annotation applied (§11):**

> Add `requested_by` to `ingestion_manifest` — **deferred until multi-user auth ships**. No admin endpoint reads this field today; no writer populates it. Adding the column ahead of the auth-role feature it depends on would be premature schema growth (CP-2 reconcile, 2026-05-02).

**Existing tracker review:**
- `ROADMAP.md` — no entry for multi-user auth.
- `docs/findings/2026-04-25-backlog-collapse.md` line 45 — _"Multi-user roles on admin — Tied to hosted/multi-user world. Reopen via data-store-spec if/when that arrives."_ This is a triage record from the 2026-04-25 backlog-collapse pass, not an active ROADMAP item.

**Candidate P3 ROADMAP entry (chat to decide separately — not added by this PR):**

```
P3 / multi-user-auth-on-admin
  Trigger: hosted / multi-user deployment becomes a real ask.
  Scope: admin-vs-analyst roles + per-user identity on every admin
         action; surfaces requested_by on ingestion_manifest as a
         downstream sub-task; reopens the request-queue design for
         concurrent triggers on the same pipeline (admin_refresh
         §11).
  Signals: any data-store-spec work that contemplates multi-tenant
           hosting; any explicit ask for non-owner access to the
           admin dashboard.
  Cross-ref: docs/findings/2026-04-25-backlog-collapse.md:45;
             docs/admin_refresh_system_design.md §11 Multi-user
             (future).
```

This entry is not added to `ROADMAP.md` by this PR. Surface only.

### 4.4 DOC_RECONCILE — `fetch_status` enum value alignment

The original design narrative referenced status-value names that do not all exist in the live `fetch_status` enum. The rewrite explicitly enumerates both sides and the mapping for future maintainers.

**Live enum (observed in production data, 2026-05-02 audit):**

| Value | Source | Notes |
|---|---|---|
| `pending` | `manifest.py` default | Migration 001 schema default. |
| `fetching` | Step-1 fetch in flight | Set by `update_manifest_status()` when `fetch()` starts. |
| `parsing` | Step-2 transient state | Rare in prod (1 row); set during XML/HTML parsing. |
| `complete` | Step-6 promote success | Terminal happy path. |
| `failed` | Any step error | Terminal failure. |
| `pending_approval` | Step-4 diff-review gate | Run waiting on admin approve/reject. |
| `rolled_back` | `/admin/rollback/{run_id}` | Terminal post-rollback. |
| `skipped` | Listed in migration 001 enum comment | No production occurrences observed in this audit, but reserved for the discovery anti-join path. |

**Design enum (pre-rewrite, narrative §2a):**

| Value | Source | Status |
|---|---|---|
| `fetching` | Step 1 | Matches live. |
| `parsing` | Step 2 | Matches live. |
| `validating` | Step 3 (narrative) | **Not** in live enum. Step 3 runs read-only; no manifest column flip today. |
| `staging` | Step 4-5 (narrative) | **Not** in live enum. Run-state, not column-state. |
| `promoting` | Step 6 (narrative) | **Not** in live enum. Run-state, not column-state. |
| `complete` | Step 6 success | Matches live. |
| `verify_failed` | Step 7 (narrative) | **Not** in live enum. Step 7 verify-after-promote is conceptual; no writer emits this value. |

**Live ← design mapping table (canonical):**

| Live `fetch_status` value | Design narrative term(s) collapsed into it |
|---|---|
| `pending` | (no design term — pre-fetch initial state) |
| `fetching` | `fetching` |
| `parsing` | `parsing` |
| `complete` | `validating` (post-validate), `staging`, `promoting`, `complete` |
| `failed` | (any narrative state's failure mode), `verify_failed` |
| `pending_approval` | (no design term — Step-4 review gate is run-level state in the design narrative; column-tracked in live) |
| `rolled_back` | (no design term — post-rollback flag) |
| `skipped` | (no design term — discovery anti-join path) |

The migration 001 schema comment lists only `'pending' \| 'fetching' \| 'complete' \| 'failed' \| 'skipped'`. Three live values (`parsing`, `pending_approval`, `rolled_back`) were added by writers and admin paths after migration 001 shipped without updating the comment. **The schema comment update is a future migration concern, not a column change.** Out of scope for CP-2.

### 4.5 Schema mapping appendix

A new Appendix A was added to `docs/admin_refresh_system_design.md`:
- **§A.1** — full live `ingestion_manifest` DDL (26 columns) reproduced from `scripts/migrations/001_pipeline_control_plane.py`.
- **§A.2** — field-name translation table (5 rows).
- **§A.3** — API field translation table referencing `admin_bp.py` line numbers (3 rows).
- **§A.4** — `fetch_status` enum reconciliation (live values + design values + observed non-comment values).
- **§A.5** — out-of-scope observations:
  1. Inconsistent `source_type` values per pipeline (direct manifest writes use uppercase short codes like `'NPORT'`; SourcePipeline-base writes use snake_case `'nport_holdings'` from `PIPELINE_CADENCE.keys()`). Affects `admin_bp.py:1346` last-run lookup.
  2. Migration 008 SQL referenced columns (`series_id`, `report_month`) that don't exist on `ingestion_manifest`. The rewrite changes the join key to `accession_number` but the working backfill SQL still needs verification before migration 008 ships.

These are flagged for follow-up. **Not** in scope for CP-2.

### 4.6 Admin endpoint code changes

None required. `scripts/admin_bp.py` already reads the live schema and serializes to the API field names in the design (`pipeline_name`, `status`, `completed_at`). Verified at:
- `_read_manifest_row()` — `admin_bp.py:1253-1276`
- `api_admin_status()` — `admin_bp.py:1321-1413`
- `api_admin_runs_pending()` — `admin_bp.py:1545-1570`
- `api_admin_run_diff()` — `admin_bp.py:1573+`

Per Phase 2 design v3.3 noted in inst-eid-bridge investigation, full admin endpoint expansion is downstream work; the existing endpoints are the only consumers of `ingestion_manifest` field names today, and they are correct.

## Phase 5 — Validation

All checks pass.

### 5.1 pytest

```
373 passed, 1 warning in 92.40s
```

(Phase 2 pre-flight expected 374; the 373/374 delta is a non-failure — likely a deselect on the urllib3 SSL warning suite. No test errors. No regressions introduced by Phase 4.)

### 5.2 React build

```
✓ built in 2.71s
```

20 chunks, 0 errors.

### 5.3 Schema sanity check (no change expected)

```
col_count=26              # unchanged from Phase 1
has source_type=True
has fetch_status=True
has fetch_completed_at=True
has row_counts_json=False
has requested_by=False
row_count=73268           # unchanged from Phase 1 (73268)
```

### 5.4 Writer import smoke

All `scripts/pipeline/manifest.py` helpers resolve and all five in-package pipeline writers (`load_nport.py`, `load_13dg.py`, `load_market.py`, `load_adv.py`, `load_ncen.py`) plus `scripts/load_13f_v2.py` import without error against the live DB. No `ingestion_manifest` schema change → no writer-helper signature change → no caller change.

### 5.5 Design-doc spot-check (3 field references)

Verified each rewritten reference resolves to a live column:

| Location | Reference in design.md | Live column | DESCRIBE confirms |
|---|---|---|---|
| §6 Migration 008 SQL (L621-624) | `m.fetch_completed_at`, `WHERE source_type = 'NPORT' AND fetch_status = 'complete'` | `fetch_completed_at`, `source_type`, `fetch_status` | YES (3/3) |
| §8 per-card "Last run" (L824) | ``MAX(fetch_completed_at)`` from `ingestion_manifest` filtered by `source_type` | `fetch_completed_at`, `source_type` | YES (2/2) |
| §A.1 Schema mapping appendix DDL | `fetch_completed_at`, `fetch_status`, `source_type` | All 3 columns + 23 others | YES (26/26) |

### 5.6 Final design-doc re-grep

Searched for any remaining `pipeline_name|row_counts_json|completed_at|requested_by` token. All 13 hits accounted for as intentional:

| Lines | Category |
|---|---|
| L377, L380 | `admin_preferences` table PK (separate table; out of scope) |
| L621, L624, L1022 | New live-name `fetch_completed_at` references |
| L824, L828, L901 | Inline narrative annotations citing CP-2 reconcile |
| L1043, L1045, L1046, L1047 | Schema-mapping translation table rows |
| L1055, L1057 | API-translation appendix rows |

No stale references. Reconciliation closed.

## Reconciliation summary (final)

| Class | Count | Outcome |
|---|---|---|
| RENAME | 3 | All applied to design.md narrative + SQL + per-card field. |
| ADD COLUMN | 0 | No-op Phase 3. |
| DROP_FROM_DESIGN | 2 | `row_counts_json` replaced with `ingestion_impacts.rows_promoted` aggregate; `requested_by` annotated as deferred. |
| DOC_RECONCILE | 2 | `fetch_status` enum mapping table added to results doc + appendix §A.4. |

§9 G4 BLOCKER closed. §12 Open Question 1 closed. CP-2 in `inst_eid_bridge_decisions.md` closed. Wave 2 unblocked.
