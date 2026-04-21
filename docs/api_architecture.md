# API Architecture

_Created 2026-04-21 under remediation ops-09 (DOC_UPDATE_PROPOSAL item 6
group). Inventory of the FastAPI router split introduced in Batch 4-C
(2026-04-13, Flask → FastAPI) and the admin write-surface covered by
sec-03-p0._

## Entry point

`scripts/app.py` — the FastAPI application. Phase 4+ Batch 4-C swapped
the original Flask Blueprint layout for FastAPI `APIRouter`s; the
pre-FastAPI Flask entry was deleted once this module proved stable
(see `docs/REACT_MIGRATION.md` and ROADMAP).

Layout summary:

- `app.py` — FastAPI app, lifespan handler, router registration, two
  top-level HTML pages (`/`, `/admin`).
- `app_db.py` — DB helpers (`get_db`, `has_table`, `init_db_path`,
  snapshot fallback).
- `api_common.py` — envelope helpers (`envelope_success`,
  `envelope_error`), the `validate_query_params_dep` dependency, regex
  constants, `_RT_AWARE_QUERIES`, `QUERY_FUNCTIONS`.
- `api_*.py` — seven domain routers (below).
- `admin_bp.py` — admin router (filename retained for git history
  continuity; it is a FastAPI `APIRouter`, not a Flask Blueprint).

## Domain routers

All seven domain routers share the same shape:

```python
<name>_router = APIRouter(
    prefix='/api/v1',
    tags=['<tag>'],
    dependencies=[Depends(validate_query_params_dep)],
)
```

`validate_query_params_dep` (api_common.py) is the ARCH-1A input guard
— it raises `HTTPException(400, ...)` on invalid input. All read-only.

| Router | Module | Prefix | Auth dep | GET | POST | Notes |
|---|---|---|---|---|---|---|
| `config_router` | `api_config.py` | `/api/v1` | validate_query_params_dep | 2 | 0 | `/config/quarters`, `/freshness` |
| `register_router` | `api_register.py` | `/api/v1` | validate_query_params_dep | 7 | 0 | Tickers, summary, query1..queryN, amendments, manager_profile |
| `fund_router` | `api_fund.py` | `/api/v1` | validate_query_params_dep | 4 | 0 | Fund rollup/portfolio/behavioral/N-PORT shorts |
| `flows_router` | `api_flows.py` | `/api/v1` | validate_query_params_dep | 7 | 0 | Flow analysis, cohort, momentum, peer rotation, portfolio context |
| `entities_router` | `api_entities.py` | `/api/v1` | validate_query_params_dep | 5 | 0 | Entity search / children / graph / resolve / market summary |
| `market_router` | `api_market.py` | `/api/v1` | validate_query_params_dep | 9 | 0 | Sector flows, short/crowding/smart-money/heatmap |
| `cross_router` | `api_cross.py` | `/api/v1` | validate_query_params_dep | 6 | 0 | Cross-ownership, two-company overlap, peer groups |

**Totals:** 7 read-only routers, 40 GET endpoints, 0 POST/PUT/DELETE.

Every domain router is read-only by construction — neither the router
nor its endpoints import any mutating `queries._*_write` helpers or
directly execute `INSERT`/`UPDATE`/`DELETE` statements against
`data/13f.duckdb`.

## Admin router

```python
admin_router = APIRouter(
    prefix='/api/admin',
    tags=['admin'],
    dependencies=[Depends(require_admin_session)],
)
```

`require_admin_session` (admin_bp.py) enforces a session cookie set by
`/api/admin/login`. The dep short-circuits on `/login` itself.

| Router | Module | Prefix | Auth dep | GET | POST | Notes |
|---|---|---|---|---|---|---|
| `admin_router` | `admin_bp.py` | `/api/admin` | require_admin_session | 12 | 6 | 6 writes; flock-guarded. |

### Write-surface (6 POST endpoints)

See `docs/findings/sec-03-p0-findings.md` §2 for the full audit table.
Summary:

| Endpoint | Guard | Writes to |
|---|---|---|
| `/api/admin/login` | CSRF token + rate limit | `session_tokens` |
| `/api/admin/logout` | session cookie | `session_tokens` |
| `/api/admin/logout_all` | session cookie | `session_tokens` |
| `/api/admin/add_ticker` | `fcntl.flock` on `data/.add_ticker_lock` (sec-03-p1); input validated | dispatches to `fetch_market.py` + enrichment pipelines |
| `/api/admin/run_script` | `fcntl.flock` on `data/.run_script_lock` (sec-02-p1); allow-list of scripts | dispatches to any approved pipeline script |
| `/api/admin/entity_override` | 409 on concurrent write (sec-03-p1); default `target='staging'` | `entity_overrides` (staging or prod) |

### Read endpoints (12 GET)

`/stats`, `/progress`, `/errors`, `/manager_changes`,
`/ticker_changes`, `/parent_mapping_health`, `/stale_data`,
`/merger_signals`, `/new_companies`, `/data_quality`,
`/staging_preview`, `/running`.

All read-only; no writes.

## Router registration

`app.py` registers routers in a fixed order:

```python
app.include_router(admin_router)  # admin first — its auth dep is per-router
for router in (config_router, register_router, fund_router, flows_router,
               entities_router, market_router, cross_router):
    app.include_router(router)
```

Top-level HTML routes (`/`, `/admin`) are registered directly on
`app`, not via a router, because they serve Jinja / static responses
rather than JSON envelopes.

## Static assets + templates

- `/assets/*` → `web/react-app/dist/assets/` (React build output).
  Mounted conditionally: the `os.path.isdir` check keeps the app
  importable when `npm run build` has not been run (fresh clone, CI
  smoke).
- `/admin` → `web/templates/admin.html` via Jinja2 templates. The API
  endpoints under `/api/admin/*` return pure JSON; only the HTML
  shell uses templates.

## Lifespan

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db_path()   # resolve DB path (main or snapshot fallback)
    yield
```

DB path resolution happens eagerly in `__main__` to ensure the
startup banner and the server import see the same resolved path.

## Cross-references

- Full route classification table: `docs/endpoint_classification.md`.
- Admin write-surface audit: `docs/findings/sec-03-p0-findings.md` §2.
- Concurrency guards: `docs/findings/sec-02-p1-findings.md`,
  `docs/findings/sec-03-p1-findings.md`.
- Flask → FastAPI migration history: `docs/REACT_MIGRATION.md`,
  ROADMAP Batch 4-C entries.

## Follow-on

- Phase 2 admin refresh (ROADMAP) is expected to add ~9 new admin
  endpoints. When landing net-new endpoints, update this doc alongside
  `docs/endpoint_classification.md` so the inventory does not drift.
