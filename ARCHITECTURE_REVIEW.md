# 13F Institutional Ownership — Architecture & Upgrade Plan

_Prepared: April 12, 2026_
_Scope: Stack decisions, API contracts, modularization, deployment. No data ops or pipeline work._

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

## 3. Architecture Gaps

### Stack layer gaps

**G1 — Untyped API contract (highest consequence gap)**
Flask returns untyped JSON. React TypeScript types in `src/types/` and `api.ts`
(60+ interfaces) were written by hand. There is no enforcement. A column rename
or null change in a query breaks the frontend silently at runtime, not at build
time. This is the most consequential gap in the current stack.

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

---

## 4. Execution Logic

Structural work before stable contracts spreads ambiguity across more files.
The dependency chain is fixed:

```
Freeze contracts → Fix correctness → Precompute analytics
    → Modularize backend → Deploy for production use
```

Each phase has an explicit exit gate. Phase N+1 does not start until that gate
is met. Each batch is sized to hand directly to Claude Code as a self-contained
unit.

---

## Phase 1 — Contract Stabilization
_Freeze endpoint semantics before any structural change._
_Gate on: do not start Phase 2 until exit criteria below are met._

---

### Batch 1-A — Routing hygiene
_~1 hour · `scripts/app.py` only · low risk_

| Item | Action |
|------|--------|
| `quarter_config` namespace | Move `/api/admin/quarter_config` → `/api/config/quarters`. Update React fetch call in same commit. |
| API versioning | Add `/api/v1/` prefix to all public routes via Blueprint `url_prefix`. One registration change. |
| Rollup param audit | Verify `rollup_type` reaches every query function that should respect it. Fix any gaps. |
| Input guards | Add route-layer validation: ticker regex `^[A-Z]{1,5}$`, quarter format `^20\d{2}Q[1-4]$`, rollup_type against `VALID_ROLLUP_TYPES`. Return 400 on invalid input. |

**Files:** `scripts/app.py`, React config fetch call.

**Done means:** Every public endpoint under `/api/v1/`. `quarter_config` off
admin namespace. `rollup_type` verified end-to-end on Register, Conviction,
Ownership Trend, Fund Portfolio. Invalid ticker returns 400, not a DuckDB error.

**Rollback:** Single git revert. React URL updated in same commit.

**Not doing here:** Response schemas, error envelope, any `queries.py` changes
beyond rollup gap fixes.

---

### Batch 1-B — Response contract
_~half day · `app.py` + new `schemas.py` + React · medium risk_

| Item | Action |
|------|--------|
| Endpoint classification | Produce and commit a table: every endpoint marked latest-only or quarter-aware. Add as comment block in `app.py`. This is the freeze artifact. |
| Export parity | Verify `api_export()` passes same `quarter` + `rollup_type` as the on-screen table. Fix any mismatches. |
| Pydantic schemas | New `scripts/schemas.py`. Add Pydantic response models for 6 priority endpoints: `/register`, `/tickers`, `/conviction`, `/flow_analysis`, `/ownership_trend`, `/entity_graph`. Validate on the way out. |
| Error envelope | Standardize `{ data, error, meta }` on all endpoints. `meta` carries `quarter`, `rollup_type`, `generated_at`. |
| React error boundaries | New `src/components/ErrorBoundary.tsx`. Per-tab wrapper. Catches envelope `error` field, renders consistent error state. |
| React type sync | Update hand-written types in `src/types/` to match Pydantic schemas. Single source of truth until FastAPI generates them automatically (Phase 4-C). |

**Files:** `scripts/app.py`, new `scripts/schemas.py`, `scripts/queries.py`
(export path only), `web/react-app/src/types/`, new
`web/react-app/src/components/ErrorBoundary.tsx`.

**Done means:** Endpoint classification table committed. 6 priority endpoints
have Pydantic validation. All endpoints return `{ data, error, meta }`. Excel
export matches on-screen state for 3 manually tested ticker/quarter/rollup
combinations. React has per-tab error boundaries.

**Rollback:** Pydantic is additive — revert to `jsonify()`. Error envelope
is a shape change; React types updated in same commit so one revert covers both.

**Not doing here:** `queries.py` restructure, Flask → FastAPI, Blueprint split,
any data layer changes.

---

**Phase 1 exit gate:** Endpoint classification table committed. Pydantic covers
6 priority endpoints. Export parity confirmed. React error boundaries in place.

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

**Done means:** `get_nport_children` batched. `summary_by_parent` confirmed read-only
on request path. Write-path risk map committed.

**Not doing here:** Fixing write-path consistency (audit only). Any structural refactor.

---

**Phase 2 exit gate:** N+1 loop removed. Write-path risk map documented.

---

## Phase 3 — Precompute + Data Layer
_Move expensive stable analytics to pipeline artifacts. Clean DB schema._
_Architecture concern: consistent freshness model and reducing on-request computation._

---

### Batch 3-A — DB schema cleanup
_~2 hours · DuckDB DDL · staging workflow · ⚠ time-sensitive: May 9 deadline_

| Item | Action |
|------|--------|
| `FAMILY_MAP` → DB table | Create `fund_family_patterns (pattern TEXT, inst_parent_name TEXT)`. Migrate 50+ hardcoded entries from `app.py`. Update `match_nport_family()` to query it. |
| `data_freshness` table | Create `data_freshness (table_name TEXT, last_computed_at TIMESTAMP, row_count BIGINT)`. Pipeline scripts write a row after each successful rebuild. API exposes via `/api/v1/freshness`. React surfaces as footer badge per tab. |

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

### Batch 3-B — portfolio_context quarterly artifact
_~half day · new pipeline script + `queries.py` · depends on Batch 3-A_

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

**Phase 3 exit gate:** `FAMILY_MAP` in DB. `data_freshness` table live and
visible in React. `portfolio_context` pipeline-built and ≤50ms.

---

## Phase 4 — Backend Modularization
_Split app.py and queries.py into well-bounded modules._
_Do not start until Phase 1 is complete — contracts must be frozen first._

---

### Batch 4-A — Runtime surface split
_~1 day · large refactor · feature branch required_

Split `scripts/app.py` (~1,400 lines) into:

| New file | Contents |
|----------|----------|
| `scripts/db.py` | `get_db()`, `_resolve_db_path()`, `_start_switchback_monitor()`, `_refresh_table_list()`, `has_table()` |
| `scripts/app_bootstrap.py` | Flask app creation, Blueprint registration, `_init_db_path()`, startup logging. Target ≤100 lines. |
| `scripts/api_register.py` | `/register`, `/tickers`, `/summary` routes |
| `scripts/api_flows.py` | `/flow_analysis`, `/investor_flows`, `/ownership_trend` routes |
| `scripts/api_entities.py` | `/entity_graph`, `/entity_search`, `/entity_children`, `/entity_resolve` routes |
| `scripts/api_market.py` | `/sector_rotation`, `/short_interest`, `/crowding`, `/smart_money` routes |
| `scripts/api_config.py` | `/config/quarters`, `/freshness` routes |
| `scripts/admin_bp.py` | Unchanged |

**Done means:** `app_bootstrap.py` ≤100 lines. No domain routes in bootstrap.
Each Blueprint independently importable. `pylint` + `bandit` pass. All endpoints
smoke-tested against pre-split baseline.

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

**Rollback:** Module merge — straightforward revert.

---

### Batch 4-C — Flask → FastAPI
_~half day · follows 4-A + 4-B · do before team sharing_

| Item | Action |
|------|--------|
| Framework swap | Replace Flask with FastAPI. Domain Blueprint files become FastAPI routers. Same `queries.py` — no query changes. |
| Pydantic integration | `schemas.py` models become FastAPI `response_model` declarations. Auto OpenAPI spec at `/docs`. |
| openapi-typescript | Run against generated spec. React types generated, not hand-written. `src/types/` becomes auto-generated. |
| Input validation | Route params validated automatically via Pydantic — removes manual guards from Batch 1-A. |

**Files:** All `scripts/api_*.py` routers, `scripts/app_bootstrap.py`,
`web/react-app/src/types/` (regenerated).

**Done means:** FastAPI starts. All endpoints respond. OpenAPI spec at `/docs`.
React types regenerated from spec. Smoke test passes.

**Rollback:** Flask preserved as `app_flask_legacy.py` until FastAPI stable
for one full week.

---

**Phase 4 exit gate:** All domain files ≤400 lines. `queries.py` has no
response shaping. FastAPI OpenAPI spec generated. React types auto-generated
and match existing types.

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
- Flask API routes and `queries.py` (modularized in Phase 4, but endpoints unchanged)
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
  api/        ← FastAPI routers
  queries/    ← SQL service layer
  pipeline/   ← ingestion + compute scripts
  entity/     ← MDM, staging, promotion
  db/         ← connection management
tests/
web/react-app/
```

---

## Backlog
_No phase dependency. Improve resilience when capacity allows._

| # | Item | Notes |
|---|------|-------|
| BL-1 | GitHub Actions CI | Pre-commit + endpoint smoke tests on push. Would have caught B608. |
| BL-2 | Pipeline dependency enforcement | Makefile or DAG. Prevents out-of-order runs. |
| BL-3 | Write-path consistency (non-entity) | Extend staging/validation to flow recompute + market data upsert. Audit in Batch 2-A first. |
| BL-4 | Three snapshot roles documented | Serving snapshot / promotion rollback / cold archive. Distinct artifacts, different retention. |
| BL-5 | Zustand scope enforcement | Document rule: global store = ticker/quarter/rollupType/company only. Tab state stays local. |
| BL-6 | Loading state standardization | Shared skeleton + empty state components across all 11 tabs. |
