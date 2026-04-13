# 13F Institutional Ownership — Architecture & Upgrade Plan

_Prepared: April 12, 2026_
_Scope: Stack decisions, API contracts, modularization, deployment, and data
layer schema changes that directly support the architecture (freshness
metadata, precomputed artifact tables). Pipeline operations and data quality
work remain in ROADMAP._

---

## 1. Current Stack

```
React 19 + TypeScript + Vite + Tailwind CSS v3 + AG Grid Community v35 + Zustand
           ↕  HTTP/JSON  (untyped contract, proxied via Vite → Flask)
Flask + Python  (scripts/app.py ~1,400 lines + scripts/admin_bp.py + scripts/queries.py ~5,400 lines)
           ↕  DuckDB Python driver  (thread-local connection cache)
DuckDB  (data/13f.duckdb)
```

**React status:** Phase 3 complete (commit `c836813`). Phase 4 cutover pending.
Two frontends currently live — React at port 5174, vanilla-JS at port 8001.

**Zustand store shape:**
```typescript
interface AppState {
  ticker: string
  company: CompanyData | null
  quarter: string
  rollupType: string        // economic_control_v1 | decision_maker_v1
  loading: boolean
  setTicker, loadCompany, setQuarter, setRollupType
}
```

---

## 2. What Is Solid — Do Not Change

- **DuckDB.** Correct for this analytical workload. Single-writer, zero ops overhead.
  Multi-user reads work fine. Only revisit if write concurrency becomes a problem
  at team scale.
- **Entity MDM temporal graph.** SCD Type 2, dual rollup types, staging/validation/
  rollback. Solved correctly. The staging workflow (sync → diff → validate → promote
  → snapshot) is the right operational pattern.
- **Thread-local connection caching.** `get_db()` via `_threading.local()` — no
  per-request connection opens. Already correct.
- **Query result caching.** `_cached()` with 5-min TTL in `queries.py`. Already
  correct. Make cache keys explicit constants during the queries.py split (Phase 4),
  but keep the mechanism.
- **Snapshot + switchback monitor.** `_resolve_db_path()` fallback to
  `13f_readonly.duckdb` when primary is write-locked. 60s background poll
  auto-returns to primary. Already correct.
- **Precomputed `investor_flows` + `ticker_flow_stats`.** Right pattern at 12M+
  row scale. Extend, do not replace.
- **Admin Blueprint with token auth (INF12).** Right separation. Already correct.
- **React 19 + TypeScript + AG Grid Community v35.** Right frontend choice for
  tabular institutional data. Tailwind v3 stable. Zustand correct scope —
  enforce the rule that tab-local state stays in components, not in the global store.

---

## 2b. Endpoint Performance Budgets

Guidance, not SLOs. Regressions vs. these budgets require commit-message
justification. Measured p95, warm cache, local (`localhost:8001`).

| Endpoint class | Budget |
|---|---|
| Tabular data (`/register`, `/conviction`, `/flow_analysis`) | ≤800ms |
| Drilldown (`/fund_portfolio_managers`, `/query7`) | ≤500ms |
| Small lookups (`/summary`, `/tickers`, `/config/quarters`) | ≤150ms |
| Precomputed artifacts (`/portfolio_context`, future) | ≤50ms |

---

## 3. Architecture Gaps

### Stack layer gaps

**G1 — Untyped API contract (highest value before team sharing)**
Flask returns untyped JSON. React TypeScript types in `src/types/` and `api.ts`
(60+ interfaces) were written by hand. There is no enforcement. A column rename
or null change in a query breaks the frontend silently at runtime, not at build
time. This is the highest-value gap to close before the tool gets shared with a
second operator.

Options in order of value:
- **FastAPI + openapi-typescript** — Pydantic response models auto-generate an
  OpenAPI spec; `openapi-typescript` generates React types from that spec. Any
  shape change becomes a compile error. Migration cost is low — same `queries.py`,
  mostly decorator changes. This is the right call before team sharing.
- **Flask + Pydantic manually** — wraps endpoints in Pydantic models, gets
  server-side validation without changing frameworks. 60% of the benefit, stays
  on Flask. Sufficient for single-operator use.

**G2 — No error contract**
No standard error shape across endpoints. React tabs have no consistent error
boundary. A 500 either silently renders an empty table or crashes the component.

**G3 — Quarter/rollup params not universally enforced**
Quarter threading is done (all 25 query functions accept `quarter=LQ` as default).
Rollup type is plumbed via `_rollup_col()`. Neither has input validation at the
route layer — bad values fall through silently.

**G4 — `quarter_config` in wrong namespace**
`/api/admin/quarter_config` is ungated because the public React UI fetches it on
every page load. Public endpoint in admin namespace. Should be `/api/config/quarters`.

**G5 — No API versioning**
All public endpoints are `/api/*` flat. Once React is the primary consumer, any
contract change breaks it with no migration path. Adding `/api/v1/` prefix costs
one Blueprint registration change now; it is expensive to add retroactively.

### Backend structural gaps

**G6 — `app.py` is a monolith**
~1,400 lines, 50+ routes, single file. The admin Blueprint pattern (INF12) is
the right model — extend it. Domain split reduces file sizes to ~300 lines each
and makes the codebase navigable.

**G7 — `queries.py` mixes too many concerns**
5,400+ lines combining SQL construction, response shaping, caching, and business
semantics (rollup selection, sub-adviser exclusions). These are distinct concerns
that should be separated when splitting to service layers.

**G8 — `FAMILY_MAP` dict belongs in the database**
50+ N-PORT fund family patterns hardcoded in `app.py`. Every new fund family
requires a code change. Should be a `fund_family_patterns` table — editable
without touching Python.

### Operational gaps

**G9 — Three snapshot roles are conflated**
The system has three distinct snapshot concerns sharing infrastructure:
- **Serving snapshot** (`13f_readonly.duckdb`) — read fallback during write lock.
  Needs a defined freshness SLA.
- **Promotion rollback snapshots** — intra-DB tables created by `promote_staging.py`.
  Scoped to entity safety.
- **Cold backup/archive** — full `EXPORT DATABASE` directory. Disaster recovery.
Defining these as three explicit artifacts with different retention and ownership
rules would improve operational clarity.

**G10 — No CI on push**
Pre-commit hooks (pylint, bandit) exist. No GitHub Actions workflow. The B608
bug lived undetected for weeks because no automated check ran against actual
endpoints. A minimal workflow — pre-commit + smoke test against 5 critical
endpoints — would have caught it.

**G11 — No pipeline dependency enforcement**
Run sequence is documented in ROADMAP.md but not enforced in code. A Makefile
with prerequisite rules or a lightweight DAG prevents silent out-of-order runs.

### Out of scope for this document

The following are real gaps but covered in separate docs to keep the
architecture plan focused:

- **Testing strategy** — unit tests for `queries.py`, contract tests between
  React types and API responses, Playwright CI integration.
  _Separate doc: `docs/TESTING_STRATEGY.md` (TODO)._
- **Observability** — structured logs, request tracing, audit log for staging
  promotions, latency metrics.
  _Separate doc: `docs/OBSERVABILITY_PLAN.md` (TODO)._

---

## 4. Execution Logic

Structural work before stable contracts spreads ambiguity across more files.
The dependency chain is fixed:

```
CI baseline → Freeze contracts → Fix correctness → Precompute analytics
    → Modularize backend → Deploy for production use
```

Each phase has an explicit exit gate. Phase N+1 does not start until that gate
is met. Each batch is sized to hand directly to Claude Code as a self-contained
unit.

_Estimates below are authoring time for the batch. Smoke-testing, deployment,
and React type regeneration are separate steps — budget an additional 30–60 min
per batch for these. Exit gates assume smoke-testing has run._

---

## Phase 0 — Prerequisite (BL-1 promoted, split into 0-A and 0-B)

### Phase 0-A — Lint + static analysis CI
_~1 hour · new `.github/workflows/lint.yml` · low risk · **gates Phase 1**_

Pre-commit hooks (pylint + bandit + ruff) wired to run on every push. No
runtime smoke tests in this batch — just static analysis.

**Done means:** CI runs on every push. A B608-class bug (mis-placed `nosec`
injecting `#` into SQL) fails CI before it reaches production. `pylint`,
`bandit`, and `ruff` all pass on `main`. Phase 0-A complete.

**Gate:** Phase 1 does not start until Phase 0-A CI is green on `main`.

**Not doing here:** Runtime smoke tests. Fixture DB. Those are Phase 0-B —
phase-independent and do not gate Phase 1.

---

### Phase 0-B1 — Fixture DB design (phase-independent, no gate)
_~1 hour · documentation only · no code_

Document the chosen fixture approach from three options:
1. Seed script that builds a minimal DuckDB from SQL fixtures at CI startup
2. Committed small binary snapshot (minimal rows, no PII)
3. Stripped `EXPORT DATABASE` dump checked into repo

Decision committed to `docs/ci_fixture_design.md`. Implementation deferred
until design is approved.

**Done means:** `docs/ci_fixture_design.md` exists and specifies the chosen
approach, its tradeoffs, and an estimated implementation time.

**Gate:** None — phase-independent. Does not gate any phase.

---

### Phase 0-B2 — Smoke test CI implementation (gates Phase 4-A)
_~2–3 hours · new `.github/workflows/smoke.yml` · medium risk_
_Prerequisite: Phase 0-B1 design approved._

Implement the fixture approach chosen in 0-B1. Wire four-endpoint smoke test
into CI: `/api/tickers`, `/api/query1`, `/api/entity_graph`, `/api/summary`.
Each test asserts HTTP 200 + non-empty JSON body against the fixture DB.

**Done means:**
- Smoke workflow runs on push against the fixture DB.
- Four endpoints (`/api/tickers`, `/api/query1`, `/api/entity_graph`,
  `/api/summary`) return HTTP 200 and non-empty JSON body.
- Response snapshots committed to `tests/fixtures/responses/*.json` —
  one file per endpoint, captured at CI setup time.
- `test_smoke_response_equality()` diffs post-split responses against
  committed snapshots on: JSON top-level keys present, row count within
  ±5%, and at least one sentinel value per endpoint (e.g. a known ticker
  appearing in `/api/tickers` response). A broken field rename or dropped
  key fails the test.
- Snapshot updates require an explicit commit with reviewer approval —
  they are not auto-updated on test failure.
- A breaking schema change on any of the four endpoints fails CI.
- Fixture builds successfully in a clean CI environment.

**Gate:** Phase 0-B2 must complete before Phase 4-A begins. Phase 4-A
requires a regression baseline to validate the Blueprint split — a documented
design alone does not satisfy this requirement. Phases 1, 2, and 3 are
unaffected and do not require 0-B2.

---

## Phase 1 — Contract Stabilization
_Freeze endpoint semantics before any structural change._
_Gate on: do not start Phase 2 until exit criteria below are met._

_Note: Batch 1-A input guards and Batch 1-B2 hand-written Pydantic schemas are
transitional. FastAPI (Batch 4-C) auto-validates via Pydantic and auto-generates
schemas from response models — these hand-written artifacts are scaffolding,
not permanent code. Batch 1-B1 (endpoint classification + export parity) is
the permanent contract artifact Phase 4 consumes._

---

### Batch 1-A — Routing hygiene
_~1 hour · `scripts/app.py` only · low risk_

| Item | Action |
|------|--------|
| `quarter_config` namespace | Move `/api/admin/quarter_config` → `/api/config/quarters`. Update React fetch call in same commit. |
| API versioning (dual-mount) | Dual-mount: register public routes under BOTH `/api/*` (existing) and `/api/v1/*` (new) during the React Phase 4 cutover window. Old frontend at :8001 continues to call `/api/*`; React migrates to `/api/v1/*` first. Deprecation: remove `/api/*` mount as a **React Phase 4 cleanup step** after cutover is confirmed stable ≥1 week. Not a backend-phase prerequisite — lives in the React migration lane. |
| Rollup param audit | Verify `rollup_type` reaches every query function that should respect it. Fix any gaps. |
| Input guards | Add route-layer validation: ticker regex `^[A-Z]{1,6}(\.[A-Z])?$` (accepts `BRK.B`, `BF.B`, ADRs), quarter format `^20\d{2}Q[1-4]$`, `rollup_type` against `VALID_ROLLUP_TYPES`. Return 400 on invalid input. DB-universe validation (lookup against `tickers` table) is a follow-on — tracked as BL-7 below. Deferred from 1-A to avoid coupling the route layer to a DB query. _Transitional — replaced by FastAPI Pydantic validation in Batch 4-C._ _Regex corrected 2026-04-13: prior literal `^[A-Z]{1,6}[.A-Z]?$` matched only one of {trailing dot, trailing letter} and so rejected `BRK.B`._ |

**Files:** `scripts/app.py`, React config fetch call.

**Done means:** Every public endpoint mounted under BOTH `/api/*` and
`/api/v1/*`. `quarter_config` off admin namespace. `rollup_type` verified
end-to-end on Register, Conviction, Ownership Trend, Fund Portfolio. Invalid
ticker returns 400, not a DuckDB error.

**Rollback:** Single git revert. React URL updated in same commit.

**Not doing here:** Response schemas, error envelope, any `queries.py` changes
beyond rollup gap fixes. Vanilla-JS frontend retirement is a separate React
Phase 4 cutover task — `/api/*` legacy mount stays until then.

---

### Batch 1-B1 — Endpoint classification + export parity
_~2 hours · `app.py` + `queries.py` (export path only) · low risk · no React gate_

| Item | Action |
|------|--------|
| Endpoint classification | Produce and commit a table: every endpoint marked latest-only or quarter-aware. Add as comment block in `app.py`. This is the freeze artifact that Phase 4 consumes. |
| Export parity | Verify `api_export()` passes same `quarter` + `rollup_type` as the on-screen table. Fix any mismatches. |

**Files:** `scripts/app.py`, `scripts/queries.py` (export path only).

**Done means:** Endpoint classification table committed. Export matches
on-screen state for 3 manually tested ticker/quarter/rollup combinations.

**Rollback:** Classification comment is additive — remove to revert. Export
fix is a query change — straightforward revert.

**Not doing here:** Error envelope, Pydantic schemas, React changes. Those
are 1-B2.

---

### Batch 1-B2 — Error envelope + Pydantic schemas + React error boundaries
_~half day · `app.py` + new `schemas.py` + React · medium risk_
_⚠ Batch 1-B2 is gated on React Phase 4 cutover complete. The error envelope
`{ data, error, meta }` changes the response shape on all handlers. Because
Phase 1-A dual-mounts the same handlers on both `/api/*` and `/api/v1/*`,
this shape change would hit both prefixes simultaneously and break the
vanilla-JS frontend at port 8001, which dereferences raw fields directly
(e.g. `s.company_name`, `s.market_cap`). Gate: vanilla-JS frontend must be
retired before Batch 1-B2 executes._

| Item | Action |
|------|--------|
| Pydantic schemas | New `scripts/schemas.py`. Add Pydantic response models for 6 priority endpoints: `/register`, `/tickers`, `/conviction`, `/flow_analysis`, `/ownership_trend`, `/entity_graph`. Validate on the way out. _Transitional — regenerated from FastAPI response models via openapi-typescript in Batch 4-C._ |
| Error envelope | Standardize `{ data, error, meta }` on all endpoints. `meta` carries `quarter`, `rollup_type`, `generated_at`. |
| React error boundaries | New `src/components/ErrorBoundary.tsx`. Per-tab wrapper. Catches envelope `error` field, renders consistent error state. |
| React type sync | Update hand-written types in `src/types/` to match Pydantic schemas. Single source of truth until FastAPI generates them automatically (Batch 4-C). |

**Files:** `scripts/app.py`, new `scripts/schemas.py`,
`web/react-app/src/types/`, new
`web/react-app/src/components/ErrorBoundary.tsx`.

**Done means:** 6 priority endpoints have Pydantic validation. All endpoints
return `{ data, error, meta }`. React has per-tab error boundaries.

**Rollback:** Pydantic is additive — revert to `jsonify()`. Error envelope
is a shape change; React types updated in same commit so one revert covers both.

**Not doing here:** `queries.py` restructure, Flask → FastAPI, Blueprint
split, any data layer changes.

---

**Phase 1 exit gate:** Batch 1-A complete (routing hygiene, dual-mount,
input guards). Batch 1-B1 complete (endpoint classification committed,
export parity confirmed). Batch 1-B2 gated on React Phase 4 cutover —
defers cleanly without blocking Phase 4 modularization.

---

## Phase 2 — Correctness Fixes
_Fix remaining API/UI gaps while code is in current shape._
_Easier to find and fix now than after modularization moves things around._

---

### Batch 2-A — Known gaps
_~2 hours · `queries.py` · low risk_

| Item | Action |
|------|--------|
| `get_nport_children` N+1 loop | Batch N-PORT children into a single SQL `IN` clause. Measured hotspot from `portfolio_context` vectorization work. |
| `summary_by_parent` path check | Verify it is read, not recomputed, on every request path. If any path recomputes on demand, move to a pipeline rebuild step. |
| Write-path consistency audit | Map all non-entity pipeline scripts. Identify which can partially apply vs roll back on failure. **Audit only — no code changes.** Output: one-page risk map in `docs/`. |

**Files:** `scripts/queries.py`, `docs/write_path_risk_map.md` (new, audit output).

**Done means:** `get_nport_children` batched — batched call completes ≤50ms
for a 25-fund portfolio (down from 286ms measured 2026-04-12).
`summary_by_parent` confirmed read-only on request path. Write-path risk map
committed.

**Not doing here:** Fixing write-path consistency (audit only). Any structural refactor.

---

**Phase 2 exit gate:** N+1 loop removed. Write-path risk map documented.

---

## Phase 3 — Precompute + Data Layer
_Move expensive stable analytics to pipeline artifacts. Clean DB schema._
_Architecture concern: consistent freshness model and reducing on-request computation._

---

### Batch 3-A — DB schema cleanup
_~2 hours · DuckDB DDL · staging workflow_

| Item | Action |
|------|--------|
| `FAMILY_MAP` → DB table | Create `fund_family_patterns (pattern TEXT, inst_parent_name TEXT)`. Migrate 50+ hardcoded entries from `app.py`. Update `match_nport_family()` to query it. |
| `data_freshness` table | Create `data_freshness (table_name TEXT, last_computed_at TIMESTAMP, row_count BIGINT)`. Pipeline scripts write a row after each successful rebuild. API exposes via `/api/v1/freshness`. React surfaces as footer badge per tab. **Staleness SLA per table:** `investor_flows` fresh ≤24h / stale >24h (footer amber); `ticker_flow_stats` fresh ≤24h / stale >24h (footer amber); `summary_by_parent` fresh ≤quarter+7d / stale >quarter+30d (footer red); `beneficial_ownership_current` fresh ≤48h / stale >7d (footer amber)†; `fund_holdings_v2` fresh ≤quarter+60d / stale >quarter+120d (footer red). Thresholds are pragmatic (reflect pipeline cadence), not regulatory. Stale ≠ wrong — surfaces "data older than expected" for the operator. **† Filing-lag dependent — threshold reflects SEC reporting cadence, not pipeline cadence. Treat as aspirational.** |

_Note: Stage 5 table drops (original holdings/fund_holdings) are a data ops
item — tracked in ROADMAP, not here._

**Files:** `data/13f.duckdb` (DDL via staging workflow), `scripts/app.py`
(`match_nport_family()` update), pipeline scripts (freshness writes), React
footer component.

**Done means:** `match_nport_family()` queries DB — no hardcoded dict. `data_freshness`
populated for `investor_flows`, `ticker_flow_stats`, `summary_by_parent`. Footer
badge visible in React on at least one tab.

**Rollback:** `fund_family_patterns` + `data_freshness` are additive DDL — drop
to revert. `match_nport_family()` revert restores dict lookup.

---

**Phase 3 exit gate:** `FAMILY_MAP` in DB. `data_freshness` table live and
visible in React. portfolio_context precompute is Phase 3+ — does not gate
this phase.

---

## Phase 3+ — portfolio_context quarterly artifact
_Triggered when: portfolio_context latency becomes a bottleneck again, or
quarterly pipeline cadence is established and precompute fits naturally._
_Prerequisite: Phase 3 complete. Not a blocker for Phase 4._

With the vectorization shipped (2.7s → 730ms), the current on-demand path
is acceptable. Full precompute as a quarterly artifact is the right end
state architecturally but is not urgent. Defer until latency regresses or
pipeline scheduling (Phase 5, Priority 3) makes a natural home for it.

### Batch 3B — portfolio_context quarterly artifact
_~half day · new pipeline script + `queries.py`_

| Item | Action |
|------|--------|
| Precomputed table | Create `portfolio_context_cache (ticker, quarter, sector, value_usd, pct_portfolio, ...)`. |
| Pipeline script | New `scripts/compute_portfolio_context.py`. Runs after `compute_flows.py`. Writes `data_freshness` row on completion. |
| Thin endpoint | `portfolio_context()` in `queries.py` → single `SELECT` from `portfolio_context_cache`. No pandas. |
| Legacy fallback | Keep `_portfolio_context_legacy()` until one full pipeline run validates the table. Remove after. |

**Files:** `data/13f.duckdb`, new `scripts/compute_portfolio_context.py`,
`scripts/queries.py`.

**Done means:** Fund Portfolio tab latency ≤50ms. `portfolio_context()` has
no pandas computation. `data_freshness` row present. Legacy fallback removed
after first validated run.

**Rollback:** Revert `queries.py` to legacy function. Precomputed table is
additive — drop to clean up.

---

## Phase 3++ — build_analytics.py quarterly precompute pipeline
_Triggered when: on-demand query latency becomes user-visible, or quarterly
pipeline cadence is established and precompute fits naturally._
_Prerequisite: Phase 3 complete. Not a blocker for Phase 4 or 4+._

Most stable analytical views (Register, Conviction, Ownership Trend,
Cross-Ownership) are deterministic per ticker×quarter×rollup_type. Running
them on demand means re-executing complex SQL on every page load. The right
pattern — already established by `investor_flows` and `ticker_flow_stats` —
is to precompute them in the pipeline and serve thin SELECTs from shaped
tables.

New `scripts/build_analytics.py` pipeline step runs after `compute_flows.py`:
- `register_cache (ticker, quarter, rollup_type, rank, institution, ...)`
- `conviction_cache (ticker, quarter, rollup_type, ...)`
- `ownership_trend_cache (ticker, quarter, ...)`
- `cross_ownership_cache (ticker_a, ticker_b, quarter, ...)`

Each table gets a `data_freshness` row on completion. API endpoints become
single-table SELECTs. Target latency: ≤50ms across all precomputed tabs.

Stays on-demand (user-driven, dynamic):
- Fund Portfolio — scoped to manager selected by user
- Entity Graph — user picks root entity, dynamic traversal
- Flow Analysis period selector — user picks window

---

## Phase 4 — Backend Modularization
_Split app.py and queries.py into well-bounded modules._
_Do not start until Batches 1-A and 1-B1 are complete — endpoint
classification table must be committed and export parity confirmed.
Batch 1-B2 (error envelope + Pydantic) is React-cutover-gated and does
not block Phase 4._
_Scope: Batches 4-A and 4-B only. The Flask → FastAPI swap (formerly Batch
4-C) has been moved into **Phase 4+**, triggered on team sharing rather than
executed as part of this phase. **Phase 3+** (portfolio_context precompute)
is likewise trigger-based and runs in parallel to Phase 4 without blocking._

---

### Batch 4-A — Runtime surface split
_~1 day · large refactor · feature branch required_

Split `scripts/app.py` (~1,400 lines) into:

| New file | Contents |
|----------|----------|
| `scripts/app_db.py` | `get_db()`, `_resolve_db_path()`, `_start_switchback_monitor()`, `_refresh_table_list()`, `has_table()` — web-serving DB helpers only. **Note:** scripts/db.py already exists as the pipeline/staging write-path utility. Do not overwrite or merge with it. `scripts/app_db.py` is a distinct module for web-layer concerns only. |
| `scripts/app_bootstrap.py` | Flask app creation, Blueprint registration, `_init_db_path()`, startup logging. Target ≤100 lines. |
| `scripts/api_register.py` | `/register`, `/tickers`, `/summary` routes |
| `scripts/api_flows.py` | `/flow_analysis`, `/investor_flows`, `/ownership_trend` routes |
| `scripts/api_entities.py` | `/entity_graph`, `/entity_search`, `/entity_children`, `/entity_resolve` routes |
| `scripts/api_market.py` | `/sector_rotation`, `/short_interest`, `/crowding`, `/smart_money` routes |
| `scripts/api_config.py` | `/config/quarters`, `/freshness` routes |
| `scripts/admin_bp.py` | Unchanged |

**Done means:** `app_bootstrap.py` ≤100 lines. No domain routes in bootstrap.
`app_db.py` importable independently of `app_bootstrap.py`. Each Blueprint
independently importable. `pylint` + `bandit` pass. All endpoints smoke-tested
against Phase 0-B2 fixture baseline — `test_smoke_response_equality()` passes
on all four monitored endpoints, confirming no field-level regressions from
the Blueprint split.

**Rollback:** Feature branch. Old `app.py` retained as `app_legacy.py` until
smoke test passes.

**Not doing here:** `queries.py` split, FastAPI migration.

---

### Batch 4-B — Service layer split
_~half day · follows Batch 4-A_

Split `scripts/queries.py` (~5,400 lines) into:

| New file | Contents |
|----------|----------|
| `scripts/queries.py` | SQL construction + execution only. No response shaping. Returns raw DuckDB results or DataFrames. |
| `scripts/serializers.py` | `clean_for_json()`, `df_to_records()`, field renaming, `schemas.py` integration. All response shaping. |
| `scripts/cache.py` | `_cached()`, `_query_cache`, `CACHE_TTL`. Cache keys as explicit string constants. |

**Done means:** `queries.py` has no `jsonify()` calls. All response shaping in
`serializers.py`. Cache keys are constants, not inline f-strings. `pylint` passes.

_Note: `queries.py` remains large after this split (SQL-only, ~3,500 lines
estimated). Per-domain split — `queries_register.py`, `queries_flows.py`,
`queries_entities.py`, `queries_market.py` — is explicitly deferred to Phase 6
as a follow-on. Do not attempt in 4-B._

**Rollback:** Module merge — straightforward revert.

---

**Phase 4 exit gate:** All domain files ≤400 lines. `queries.py` contains no
response shaping. `serializers.py` handles all response shaping. `cache.py`
holds explicit cache key constants. `pylint` + `bandit` pass on all new files.
All endpoints smoke-tested against pre-split baseline.

---

## Phase 4+ — Flask → FastAPI
_Triggered when: first second operator joins, or tool moves to shared/hosted use._
_Prerequisite: Phase 4 complete._

_Note: Batches 4-A and 4-B must complete before this phase starts. The
hand-written Pydantic schemas from Batch 1-B2 are replaced by auto-generated
types from the OpenAPI spec in this phase._

### Batch 4-C — Flask → FastAPI
_~2–3 days · follows 4-A + 4-B · do before team sharing_

| Item | Action |
|------|--------|
| Framework swap | Replace Flask with FastAPI. Domain Blueprint files become FastAPI routers. Same `queries.py` — no query changes. |
| Thread-local preservation | FastAPI routes declared as `def`, NOT `async def`. Sync routes run in FastAPI's threadpool, preserving `_threading.local()` semantics and the `get_db()` cache. Any future async route must explicitly opt out of the cache or use an async DuckDB adapter (not currently used). |
| Pydantic integration | `schemas.py` models become FastAPI `response_model` declarations. Auto OpenAPI spec at `/docs`. |
| openapi-typescript | Run against generated spec. React types generated, not hand-written. `src/types/` becomes auto-generated. |
| Input validation | Route params validated automatically via Pydantic — removes manual guards from Batch 1-A. |

**Files:** All `scripts/api_*.py` routers, `scripts/app_bootstrap.py`,
`web/react-app/src/types/` (regenerated).

**Known risks:** `before_request` token guard in `admin_bp.py` requires FastAPI
`Depends()` conversion — estimate includes this. Every `jsonify()` call must
become a Pydantic return type or `JSONResponse`. CORS + startup hooks need
explicit FastAPI equivalents. These are why the estimate is 2–3 days, not
half a day.

**Done means:** FastAPI starts. All endpoints respond. OpenAPI spec at `/docs`.
React types regenerated from spec. Smoke test passes. All routes are `def`,
not `async def`. Thread-local `get_db()` cache hit rate unchanged from Flask
baseline.

**Rollback:** Flask preserved as `app_flask_legacy.py` until FastAPI stable
for one full week.

---

**Phase 4+ exit gate:** FastAPI starts. All endpoints respond. OpenAPI spec
at `/docs`. React types regenerated from spec via openapi-typescript and
match existing `schemas.py` types. All routes are `def`, not `async def`.
Thread-local `get_db()` cache hit rate unchanged from Flask baseline. Smoke
test passes.

---

## Phase 5 — Backend Deployment Migration
_Production-grade serving. Gated on Phase 4 React cutover confirmed stable._
_Do not start until React Phase 4 cutover is running without regression for one full week._

The original plan referenced "frontend Phase 6 complete" as the gate. Phase 6
is not defined in REACT_MIGRATION.md — the migration defines Phases 1–4 only.
Gate restated as: **React Phase 4 cutover confirmed stable.**

| Priority | Component | Action | Trigger |
|----------|-----------|--------|---------|
| 1 | Flask serving | Gunicorn + Nginx. Replace dev server. | First external user |
| 2 | Authentication | Flask-JWT or Auth0, per-user access control. | Same time as Gunicorn |
| 3 | Pipeline scheduling | APScheduler (inside Flask) or Airflow. | Running with a team |
| 4 | PostgreSQL | Migrate entity MDM tables only if write concurrency becomes an issue. | If needed — DuckDB handles multi-user reads correctly. |
| 5 | Cloud deployment | Railway + Vercel or combined EC2. | When productizing |

**What does not change in this phase:**
- DuckDB for analytics queries
- API routes and query logic (FastAPI post-Batch 4-C, but endpoints and query
  behavior unchanged — framework swap only)
- Data pipeline scripts
- Entity staging workflow

---

## Phase 6 — Repo/Package Reshaping
_Only if Phase 4 modularization proves insufficient._

**Gate:** Do not start unless there is a concrete pain point — second operator
onboarding, independent pipeline deployment, test isolation — not aesthetic
preference.

Likely shape if needed:
```
src/
  api/            ← FastAPI routers
  queries/        ← SQL service layer (per-domain split)
    register.py
    flows.py
    entities.py
    market.py
  pipeline/       ← ingestion + compute scripts
  entity/         ← MDM, staging, promotion
  db/             ← connection management
tests/
web/react-app/
```

The per-domain `queries/*.py` split is the natural follow-on to Batch 4-B's
initial queries/serializers/cache separation — explicitly deferred here to
avoid scope creep inside Phase 4.

---

## Backlog
_No phase dependency. Improve resilience when capacity allows._

_Note: BL-1 (GitHub Actions CI) has been promoted to **Phase 0** and split
into three batches: Phase 0-A (lint/bandit, gates Phase 1), Phase 0-B1
(fixture design, phase-independent), and Phase 0-B2 (smoke CI implementation,
gates Phase 4-A only — does not gate Phases 1–3)._

| # | Item | Notes |
|---|------|-------|
| BL-2 | Pipeline dependency enforcement | Makefile or DAG. Prevents out-of-order runs. |
| BL-3 | Write-path consistency (non-entity) | Extend staging/validation to flow recompute + market data upsert. Audit in Batch 2-A first. |
| BL-4 | Three snapshot roles documented | Serving snapshot / promotion rollback / cold archive. Distinct artifacts, different retention. |
| BL-5 | Zustand scope enforcement | Document rule: global store = ticker/quarter/rollupType/company only. Tab state stays local. |
| BL-6 | Loading state standardization | Shared skeleton + empty state components across all 11 tabs. |
| BL-7 | DB-universe ticker validation | Route-layer check against the `tickers` table (or cached set). Catches typos that the regex in Batch 1-A passes. Follow-on to ARCH-1A. Keep the route layer decoupled from the DB by loading the ticker set at app startup or caching with a short TTL. |
