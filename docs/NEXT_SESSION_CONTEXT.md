# 13F Ownership — Next Session Context

_Last updated: 2026-04-22 (phase2-prep refresh). Main HEAD: `7c49471` (conv-11 remediation program complete)._

Startup briefing for a fresh Claude Code session. Read end-to-end, then continue with ROADMAP + Phase 2 design doc.

---

## Program state — remediation COMPLETE, Phase 2 ready

The **Remediation Program** (`docs/REMEDIATION_PLAN.md` + `docs/REMEDIATION_CHECKLIST.md`) closed 2026-04-22. **105 PRs merged (#5–#105), ~66 items closed across 5 themes.** All findings addressed or formally deferred with documented exit criteria.

| Theme | Scope | Status |
|---|---|---|
| Theme 1 — Data integrity foundation | int-01..int-22, OpenFIGI RC1–RC4, denorm retirement, series triage | **CLOSED** (int-09 + int-19 deferred to Phase 2; int-11 + int-18 STANDING) |
| Theme 2 — Observability + audit trail | ingestion_manifest, freshness, impact_id, log rotation | **CLOSED** (all items) |
| Theme 3 — Migration + schema discipline | mig-01..mig-14, atomic promotes, parity extensions, row_id | **CLOSED** (mig-12 deferred to Phase 3) |
| Theme 4 — Security hardening | admin auth, TOCTOU, prod-write validators, pinned deps | **CLOSED** |
| Theme 5 — Operational surface | README/prompts, MAINTENANCE, ROADMAP hygiene | **CLOSED** (ops-18 BLOCKED pending source recovery) |

Closure record: `docs/REMEDIATION_PLAN.md §Changelog (2026-04-22 conv-11)`.

---

## Phase 2 — next work stream

**Scope:** User-triggered admin refresh system. Framework-first delivery. See `docs/admin_refresh_system_design.md v3.2`.

### Major components

1. **`scripts/pipeline/base.py`** — concrete `SourcePipeline` ABC with `run()` orchestrator (today: `protocol.py` structural Protocols only — retrofit decision required).
2. **`scripts/pipeline/cadence.py`** — `PIPELINE_CADENCE` dict + probe functions + stale thresholds + `expected_delta` anomaly ranges. Does not exist yet.
3. **`is_latest` amendment semantics** — new migration (next free slot, likely 015) adds `is_latest`, `loaded_at`, `backfill_quality` to `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`. Not the same as migration 008 (pct_of_so rename).
4. **`queries.py` sweep** — add `WHERE is_latest=TRUE` across all 13F/N-PORT/13D/G read paths.
5. **9 admin endpoints** — `/admin/refresh/{pipeline}`, `/admin/run/{run_id}`, `/admin/status`, `/admin/probe/{pipeline}`, `/admin/runs/pending`, `/admin/runs/{id}/diff`, `/admin/runs/{id}/approve`, `/admin/runs/{id}/reject`, `/admin/rollback/{run_id}`. Needs new `admin_preferences` control-plane table.
6. **Admin status dashboard tab** + **Data Source tab** (move `Plans/data_sources.md` → `docs/data_sources.md` first).
7. **Six pipeline migrations** to the framework: `fetch_13dg_v3`, `fetch_market_v2`, `fetch_ncen_v2`, `fetch_adv_v2`, `load_13f_v2` (first subclass — absorbs deferred `mig-12`), plus extract-to-base of current `fetch_nport_v2`.

### Dependencies (all cleared)

- **Observability:** obs-01, obs-02, obs-03, obs-06, obs-10 DONE (ingestion_manifest coverage, freshness gate, impact_id hardening).
- **Migrations:** mig-01 (atomic promotes), mig-03 (migration 004 retrofit), mig-04 (fetch_adv DROP→CREATE), mig-09/10/11 (schema-parity L0/L4/CI), mig-13 (build_entities per-step CHECKPOINT) DONE.
- **Security:** sec-01..sec-04 DONE (token auth, TOCTOU, prod-write elimination, pinned deps).

### Deferred items Phase 2 will encounter

- **int-09 Step 4** — denorm retirement (`ticker`, `entity_id`, `rollup_entity_id`, `lei` drops on v2 fact tables). Execute **after** queries.py `is_latest` sweep and read-site audit (`scripts/audit_read_sites.py`). Exit criteria: `docs/findings/int-09-p0-findings.md §4`.
- **int-19 (INF38)** — true float-adjusted `pct_of_float` denominator. Needs new float-history data source. Execute after first new `SourcePipeline` subclass lands.
- **mig-12** — `load_13f.py` rewrite to `load_13f_v2` on framework. Becomes first full `SourcePipeline` subclass exercise in Phase 2.

---

## Database current state (prod, 2026-04-22)

| Table | Rows | Notes |
|---|---|---|
| `holdings_v2` | ~12.27M | `row_id BIGINT PK` (migration 014); denorm columns still present pending int-09 |
| `fund_holdings_v2` | ~14.09M | `row_id BIGINT PK`; `'N/A'` literal for CUSIP-less positions (~832K rows) |
| `beneficial_ownership_v2` | 51,905 | `row_id BIGINT PK`; `ingestion_impacts` backfilled (obs-04) |
| `securities` | 430,149 | `cusip PK` (migration 011); `is_otc VARCHAR` (migration 012) |
| `cusip_classifications` | 132,618 | v1.4, migration 003 |
| `entities` | ~26,602 | +67 new from int-21 series triage |
| `entity_identifiers` | ~33K+ | lowercase `identifier_type` ('cik','crd','series_id') |
| `entity_relationships` | ~18K | `last_refreshed_at TIMESTAMP` live |
| `entity_overrides_persistent` | 245 | `override_id` sequence + NOT NULL (migration 006) |
| `summary_by_parent` | 63,916 | EC + DM worldviews (migration 004 PK); `top10_*` columns dropped (migration 013) |
| `investor_flows` | 17,396,524 | EC + DM |
| `ingestion_manifest` | 21,339+ | covers MARKET / NPORT / 13DG / NCEN / ADV |
| `ingestion_impacts` | 29,531+ | 51,905 13D/G rows backfilled (obs-04) |

**Migrations applied:** 001–014 on prod + staging.
**SCD open-row sentinel:** `DATE '9999-12-31'`, not NULL.
**`entity_current`** is the only user-defined VIEW in prod — rebuild after fixture/snapshot restores.

---

## First 5 minutes — read these

1. `~/ClaudeWorkspace/CLAUDE.md` — workspace rules (file routing, tone, naming).
2. `docs/admin_refresh_system_design.md` — Phase 2 design v3.2. §1 (deliverables), §2a (staging flow), §4 (SourcePipeline), §6 (cadence), §12 (phase sequence).
3. `docs/REMEDIATION_PLAN.md §Changelog 2026-04-22` — closure record.
4. `ROADMAP.md §Open items` — remaining carry-forward (int-09, int-19, mig-12, standing curation).
5. `docs/PROCESS_RULES.md` — rules for large-data scripts.
6. Auto memory at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main`. Phase 2 work lands on per-item branches.
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - **FastAPI + uvicorn** — `scripts/app.py` (thin entry) + 9 router modules + `admin_bp.py` (token auth via `Depends`). OpenAPI at `/docs` + `/redoc`.
  - **Service layer** — `scripts/queries.py` (~5,500 lines) + `serializers.py` + `cache.py`.
  - **DuckDB** — prod `data/13f.duckdb`, staging `data/13f_staging.duckdb`, serving snapshot `data/13f_readonly.duckdb`.
  - **React** — `web/react-app/` served by FastAPI at :8001 from `dist/`. Dev server :5174.
  - **API contract** — `/api/v1/*`. 6 endpoints use the Phase 1-B2 envelope. Hand-written `src/types/api.ts` still authoritative.

---

## Tools and paths

| Tool | Path / Command |
|---|---|
| Prod DB | `data/13f.duckdb` |
| Staging DB | `data/13f_staging.duckdb` |
| Start app | `./scripts/start_app.sh` → `localhost:8001` |
| App entry | `scripts/app.py` |
| Audit tool | `scripts/audit_read_sites.py` (rename-sweep discipline, mig-07) |
| Schema parity | `scripts/pipeline/validate_schema_parity.py --layer all` / `make schema-parity-check` |
| Fixture rebuild | `scripts/build_fixture.py` (writes `_fixture_metadata` provenance row) |
| Freshness gate | `scripts/check_freshness.py` / `make freshness` |
| Log rotation | `scripts/rotate_logs.sh` / `make rotate-logs` |
| EDGAR identity | `serge.tismen@gmail.com` (centralized in `scripts/config.py`) |
| ID issuance | `scripts/pipeline/id_allocator.py` (`manifest_id` / `impact_id`) |
| Promote mirror | `_mirror_manifest_and_impacts` helper in `promote_nport.py` / `promote_13dg.py` |

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                                         # ## main...origin/main, clean
git log -1 --oneline                                   # 7c49471 or newer
pytest tests/ -x                                       # green
make freshness                                         # PASS on 7 critical tables
make schema-parity-check                               # 0 divergences on L3 canonicals
python3 scripts/validate_entities.py --prod --read-only  # 8 PASS / 2 FAIL / 6 MANUAL
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization.
- Never mutate production data to simulate test conditions.
- Update `ROADMAP.md` COMPLETED section after closing an item (date + details).
- Update `docs/NEXT_SESSION_CONTEXT.md` at end of every session; commit + push before signing off.
- Entity changes: `sync_staging.py → diff_staging.py → promote_staging.py`.
- Reference-table changes: `merge_staging.py --tables <name>`.
- Batch entity merges: transfer CIK identifiers BEFORE closing source row (INF4c lesson, ~$166B impact).
- N-PORT coverage < 50% → classification stays `mixed` regardless of active/passive split.
- Never trust `managers.manually_verified=True`.
- Never use `fuzz.token_sort_ratio` alone for firm-name matching — use brand-token overlap (`_brand_tokens_overlap`).
- CRD values normalized via `_normalize_crd()`.
- Pre-commit hooks must pass. Never `--no-verify`. Fix the underlying issue.
- `python3 -u` for background tasks (buffered print swallows output otherwise).
- B608 `# nosec` goes on the closing `"""` line of the SQL string.
- Worktree recovery: `git pull --ff-only`.

---

## Critical gotchas — architectural facts (preserve across sessions)

### DB schema + query patterns

**`entity_current` is a VIEW.** Only user-defined view in prod. Fixture / snapshot rebuilds must recreate it. Definition mirrored in `scripts/build_fixture.py`.

**`entity_identifiers.identifier_type` is lowercase.** `'cik'`, `'crd'`, `'series_id'`. Uppercase filters return zero rows.

**SCD open-row sentinel is `DATE '9999-12-31'`, not NULL.** Applies to `entity_rollup_history`, `entity_aliases`, `entity_identifiers`, `entity_classification_history`, `entity_relationships`.

**`holdings_v2` composite key is filing-line grain.** True key: `(cik, ticker, quarter, put_call, security_type, discretion)`. Total-position aggregation requires `SUM(...) GROUP BY (cik, ticker, quarter)`.

**`fund_holdings_v2` stores `'N/A'` literally** for CUSIP-less positions (~832K rows). DERA parity depends on preserving this sentinel.

**v2 fact tables have `row_id BIGINT PK`** (migration 014, mig-06). Stable surrogate for rollback replay.

**DuckDB `NOW()` vs `CURRENT_TIMESTAMP`** — use `NOW()` inside `ON CONFLICT DO UPDATE SET` with `executemany`. Binder misreads `CURRENT_TIMESTAMP` as a column name.

### Entity data plane

**Canonical entity IDs (memorize):** Vanguard 4375 · Morgan Stanley 2920 · Fidelity 10443 · State Street 7984 · Northern Trust 4435 · Wellington 11220 · Dimensional 5026 · Franklin 4805 · PGIM 1589 · First Trust 136.

**Two rollup worldviews:** `economic_control_v1` (EC) · `decision_maker_v1` (DM). `summary_by_parent` PK is `(quarter, rollup_type, rollup_entity_id)`.

**`PARENT_SEEDS` count is 110** in `scripts/build_entities.py:6`. Older planning docs that cite 50 are stale.

**INF9d eids 20194 / 20196 / 20201 / 20203** are live PARENT_SEEDS brand shells with aliases + ADV lineage. **Do not delete.**

**Fragmented-CIK rule.** INSERT identifiers on the survivor before closing source row on merges.

### Pipeline + app wiring

**Staging workflow is law.** `sync_staging.py → diff_staging.py → promote_staging.py` for entity changes. `merge_staging.py --tables <name>` for reference tables. No direct-to-prod writes.

**Promote atomicity.** `promote_nport.py` + `promote_13dg.py` wrap `_mirror_manifest_and_impacts` + DELETE+INSERT in a single transaction (mig-01). Audit-trail wipe bug fixed.

**Ticker regex is `^[A-Z]{1,6}(\.[A-Z])?$`** (accepts BRK.B). Literal `^[A-Z]{1,6}[.A-Z]?$` was wrong.

**`get_nport_children_batch()`** replaces per-parent loops — 14× speedup. Do NOT reintroduce singular per-parent loops.

**`get_nport_family_patterns()`** reads `fund_family_patterns` (2 cols: `pattern`, `inst_parent_name`; 83 rows; PK `(inst_parent_name, pattern)`). Memoized at module scope — restart app to pick up table edits.

**`api-generated.ts` is sparser than `api.ts`** — do not delete `api.ts` until `scripts/schemas.py` is expanded.

### Observability

**`record_freshness` + FreshnessBadge.** Pipeline scripts rebuilding a precomputed table call `db.record_freshness(con, 'table_name')` at end of main. React `FreshnessBadge` shares one `/api/v1/freshness` fetch via module-level cache.

**`ingestion_manifest` coverage.** Covers MARKET, NPORT, 13DG, NCEN, ADV. Any new source needs a row-per-fetch with `object_type` / `object_key`.

**`impact_id` allocation** centralized in `scripts/pipeline/id_allocator.py`. Prod sequences are drifted — do not revert to DEFAULT `nextval`.

### Design language + formatting

**Oxford Blue `#002147`** primary color for all surfaces/decks.

**Type badges** use `getTypeStyle()` from `common/typeConfig.ts`. Never inline.

**Formatting:** all `%` 2 decimals with trailing zeros; zero → em-dash; highlight yellow `#fef9c3`.

---

## Where to look

| Question | Source |
|---|---|
| Phase 2 design | `docs/admin_refresh_system_design.md` v3.2 |
| Remediation closure record | `docs/REMEDIATION_PLAN.md §Changelog` + `docs/REMEDIATION_CHECKLIST.md` |
| Deferred followups | `docs/DEFERRED_FOLLOWUPS.md` |
| Script inventory + status | `docs/pipeline_inventory.md` |
| Architecture baseline | `ARCHITECTURE_REVIEW.md` (historical — see status header) |
| Current prod DDL | `docs/canonical_ddl.md` + `docs/data_layers.md` |
| Pipeline protocol | `scripts/pipeline/protocol.py` |
| Entity architecture | `docs/ENTITY_ARCHITECTURE.md` |

Regenerate the top block of this file at session close so future sessions land oriented.
