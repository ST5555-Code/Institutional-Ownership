# 13F Ownership — Next Session Context

_Last updated: 2026-04-23 (post entity-curation-w1 — INF37 cleared + int-21 SELF-fallback reviewed + 43e de-scoped). Main HEAD at branch point: `e1b11e1`. entity-curation-w1 branch pending PR._

**entity-curation-w1 closed this session.** Batch-closed two of three standing curation items:
- **INF37 CLEARED** — 9 entities / 14,368 `holdings_v2` rows flipped from NULL/unknown to correct `manager_type` (8 `wealth_management` + 1 `active`). Zero residuals. CSV edit + prod backfill. See `docs/findings/entity-curation-w1-log.md`.
- **int-21 SELF-fallback CLOSED** — all 12 entities (plan said 11, actual 12) reviewed and confirmed SELF-rooted. All are inert MDM entries: 0 holdings as manager, 0 child rollups, 0 relationships, 0 N-CEN adviser matches. No writes; defer individual parent reassignment to on-demand triage if/when holdings data lands.
- **43e de-scoped** — downstream enum surface (`scripts/build_summaries.py:173,181` + `scripts/queries.py:1724` closed-list `manager_type IN (…)` checks) makes adding `family_office` a taxonomy refactor, not a one-line add. Re-filed in ROADMAP for a dedicated follow-on that also resolves pre-existing `multi_strategy` / `SWF` bucket-membership ambiguity.

Prod state: `validate_entities.py` baseline 8 PASS / 1 FAIL / 7 MANUAL preserved; `summary_by_ticker` 47,642 → 47,732 (+90 from newly classified entities); `summary_by_parent` 63,916 unchanged.

**Prior session (preserved):** int-22 closed (`int-22-prod-execute-and-verify`). Option C rollback of run_id `13f_holdings_quarter=2025Q4_20260422_200854` executed on prod. Post-state matches staging rehearsal to the row. Loader idempotency gap tracked separately as **int-23** (closed since by PR #119).

**Next items:**
- **Taxonomy refactor follow-on** (43e re-scope) — bucket membership for `family_office` + `multi_strategy` + `SWF` in `build_summaries.py:173,181` and `queries.py:1724`; plus React typeConfig color mapping.
- **Serge visual walkthrough on PR #107** (ui-audit-01).
- **Peer rotation precompute** — address `get_peer_rotation()` slowness.

Startup briefing for a fresh Claude Code session. Read end-to-end, then continue with ROADMAP + post-Phase-2 backlog.

---

## Program state — Phase 2 + Wave 2 COMPLETE

The **Remediation Program** closed 2026-04-22 (conv-11, 105 PRs, ~66 items across 5 themes). The **Phase 2 admin refresh system** (p2-01 through p2-10-fix) and the **Wave 2 pipeline migrations** (w2-01 through w2-05) both closed in the same window. All six ingest pipelines now run on the `SourcePipeline` framework; the admin refresh dashboard is live.

| Workstream | Scope | Status |
|---|---|---|
| Remediation Themes 1–5 | int-01..int-23, obs-01..obs-13, mig-01..mig-14, sec-01..sec-08, ops-01..ops-18 | **CLOSED** (int-09 + int-19 deferred; int-11 + int-18 standing; ops-18 blocked) |
| Phase 2 admin refresh system | p2-01 base class → p2-10-fix atomic promote | **CLOSED** (all 10 phases DONE; p2-10-fix hardened atomic promote + explicit column list in `scripts/pipeline/base.py`) |
| Wave 2 pipeline migrations | w2-01 13D/G, w2-02 Market, w2-03 N-PORT, w2-04 N-CEN, w2-05 ADV | **CLOSED** (5/5; all on `SourcePipeline`) |

Closure records: `docs/REMEDIATION_PLAN.md §Changelog (2026-04-22 conv-11)`; Phase 2 status table in `docs/admin_refresh_system_design.md §Current State`.

---

## Pipeline framework — as-shipped state

All six pipelines register in `scripts/pipeline/pipelines.py` → `PIPELINE_REGISTRY` and are dispatched by `scripts/admin_bp.py` for refresh / approve / reject / rollback.

| Pipeline name (key) | Subclass | Amendment strategy | Module |
|---|---|---|---|
| `13f_holdings` | `Load13FPipeline` | `append_is_latest` | `scripts/load_13f_v2.py` |
| `13dg_ownership` | `Load13DGPipeline` | `append_is_latest` | `scripts/pipeline/load_13dg.py` |
| `nport_holdings` | `LoadNPortPipeline` | `append_is_latest` | `scripts/pipeline/load_nport.py` |
| `market_data` | `LoadMarketPipeline` | `direct_write` | `scripts/pipeline/load_market.py` |
| `ncen_advisers` | `LoadNCENPipeline` | `scd_type2` | `scripts/pipeline/load_ncen.py` |
| `adv_registrants` | `LoadADVPipeline` | `direct_write` | `scripts/pipeline/load_adv.py` |

**Retired to `scripts/retired/`** (Wave 2): `fetch_13dg.py`, `fetch_13dg_v2.py`, `validate_13dg.py`, `promote_13dg.py`, `fetch_market.py`, `fetch_nport.py`, `fetch_nport_v2.py`, `validate_nport.py`, `validate_nport_subset.py`, `promote_nport.py`, `fetch_ncen.py`, `fetch_adv.py`, `promote_adv.py`. Kept in `scripts/` as imported transport / library helpers: `fetch_dera_nport.py` (DERA ZIP transport), `scripts/pipeline/nport_parsers.py` (XML parsing library).

**Framework surface.** `scripts/pipeline/base.py` owns the eight-step staging flow (fetch → parse → validate → diff → snapshot → promote → verify → cleanup) with atomic BEGIN/COMMIT wrap on promote, explicit column list on every INSERT (p2-10-fix), and dispatch by `amendment_strategy`. `scripts/pipeline/cadence.py` holds `PIPELINE_CADENCE` + probe functions + `expected_delta` ranges. `scripts/pipeline/manifest.py` owns control-plane writes.

**Admin dashboard.** `/admin/dashboard` (auth-gated, React) + 9 endpoints on `scripts/admin_bp.py`: `/admin/status`, `/admin/refresh/{pipeline}`, `/admin/run/{run_id}`, `/admin/probe/{pipeline}`, `/admin/runs/pending`, `/admin/runs/{id}/diff`, `/admin/runs/{id}/approve`, `/admin/runs/{id}/reject`, `/admin/rollback/{run_id}`. Auto-approve per pipeline via `admin_preferences` (migration 016).

**`load_13f_v2.py` dry-run proven on Q4 2025** — +218 net rows, validator green, manifest + impacts written. Full prod refresh not yet executed (gated on user authorization per CLAUDE.md rules).

---

## Post-Phase 2 carry-forward (open)

- **int-09 Step 4** — denorm retirement (`ticker`, `entity_id`, `rollup_entity_id`, `lei` drops on v2 fact tables). Now unblocked by `is_latest` sweep + `scripts/audit_read_sites.py`. Exit criteria: `docs/findings/int-09-p0-findings.md §4`.
- **int-19 (INF38)** — true float-adjusted `pct_of_float` denominator. Needs new float-history data source.
- **Legacy `run_script` allowlist in `scripts/admin_bp.py`** — references retired scripts (`fetch_nport.py` / `fetch_adv.py` / etc). Prune after one clean quarterly cycle against the framework.
- **`scheduler.py`, `update.py`, `benchmark.py`** — stale references to retired scripts; audit + prune.
- **ADV SCD conversion** — w2-05 shipped ADV as `direct_write`. SCD Type 2 on `adv_managers` / `cik_crd_direct` / `lei_reference` deferred (design question: which columns carry history).
- **`adv_managers` ownership boundary** — ADV pipeline does **not** manage `cik_crd_direct` or `lei_reference`; those stay under `build_managers.py` for now.
- **mig-12** — **CLOSED (absorbed by p2-05 `load_13f_v2.py`).**

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

**Migrations applied:** 001–017 on prod + staging.
- 015 — amendment-semantics columns (`is_latest`, `loaded_at`, `backfill_quality`) on `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`; `accession_number` added to `fund_holdings_v2`.
- 016 — `admin_preferences` control-plane table for per-pipeline auto-approve.
- 017 — `valid_from` / `valid_to` on `ncen_adviser_map` for SCD Type 2 promote (w2-04).

**SCD open-row sentinel:** `DATE '9999-12-31'`, not NULL.
**`entity_current`** is the only user-defined VIEW in prod — rebuild after fixture/snapshot restores.

---

## First 5 minutes — read these

1. `~/ClaudeWorkspace/CLAUDE.md` — workspace rules (file routing, tone, naming).
2. `docs/admin_refresh_system_design.md` — admin refresh design v3.2 (§Current State annotations are now all DONE).
3. `docs/REMEDIATION_PLAN.md §Changelog 2026-04-22` — closure records (conv-11 remediation close + conv-12 Phase 2 + Wave 2 close).
4. `ROADMAP.md §Open items` — remaining carry-forward (int-09, int-19, standing curation).
5. `docs/pipeline_inventory.md` — current script map with Wave 2 retirements + SourcePipeline subclasses.
6. `docs/PROCESS_RULES.md` — rules for large-data scripts.
7. Auto memory at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main`. Post-Phase-2 work lands on per-item branches.
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
git log -1 --oneline                                   # b0baebe or newer
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
| Admin refresh system design | `docs/admin_refresh_system_design.md` v3.2 (§Current State annotations all DONE) |
| Phase 2 + Wave 2 closure records | `docs/REMEDIATION_PLAN.md §Changelog (conv-12)` |
| Deferred followups | `docs/DEFERRED_FOLLOWUPS.md` |
| Script inventory + pipeline registry | `docs/pipeline_inventory.md` + `scripts/pipeline/pipelines.py` |
| SourcePipeline base class | `scripts/pipeline/base.py` (atomic promote, eight-step flow) |
| Cadence + probes + expected_delta | `scripts/pipeline/cadence.py` |
| Architecture baseline | `ARCHITECTURE_REVIEW.md` (historical — see status header) |
| Current prod DDL | `docs/canonical_ddl.md` + `docs/data_layers.md` |
| Entity architecture | `docs/ENTITY_ARCHITECTURE.md` |
| Pipeline CLI reference | `MAINTENANCE.md §Pipeline refresh` |

Regenerate the top block of this file at session close so future sessions land oriented.
