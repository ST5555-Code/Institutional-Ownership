# 13F Ownership — Next Session Context

_Last updated: 2026-04-13 (session close — FreshnessBadge rollout to all 11 tabs + Phase 0-B2 smoke CI shipped. HEAD: 8cf0d82)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main`
- **HEAD:** `8cf0d82` (Phase 0-B2 — smoke CI fixture + response snapshot tests)
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - Flask — `scripts/app.py` (~1400 lines) + `scripts/admin_bp.py` (~700 lines, admin Blueprint, INF12)
  - DuckDB — `data/13f.duckdb` (prod), `data/13f_staging.duckdb` (staging)
  - Vanilla JS — `web/static/app.js` (~5600 lines, **retired 2026-04-13 pending 1-week stability**)
  - Jinja templates — `web/templates/admin.html` (admin page only; `web/templates/index.html` orphaned but retained for rollback)
  - **React full-app (Phase 4 COMPLETE)** — `web/react-app/` is now the primary frontend served by Flask at :8001 from `web/react-app/dist/`. Vanilla-JS frontend (web/static/app.js, web/templates/index.html) still on disk — retirement window opens 2026-04-20. React dev server on :5174 still available for development.

---

## First 5 minutes — read these

1. **`~/ClaudeWorkspace/CLAUDE.md`** — workspace rules
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF18. COMPLETED section at line ~260+. ARCHITECTURE BACKLOG section tracks ARCH-1A through ARCH-4C + BL-1 through BL-6.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — React app migration plan
5. **`ARCHITECTURE_REVIEW.md`** — 6-phase stack upgrade plan (2026-04-12). Start here for architecture work.
6. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`

---

## Backend cleanup — 2026-04-12 session

Three related fixes landed on top of Phase 3. See ROADMAP row dated 2026-04-12 for full detail.

| Fix | Commit | Impact |
|---|---|---|
| Dropped `log_shadow_diff()` | `c2c5441` | Removed function + `_SHADOW_LOG_PATH` + 4 call sites. Phase 4 shadow logging no longer needed. |
| Threaded `quarter` param through query endpoints | `94b0402` | `api_query` + `api_export` read `quarter` from request args (default LATEST_QUARTER); 25 query functions gained `quarter=LQ` kwarg. All defaults preserve existing caller behavior. `get_nport_children_q2` intentionally left alone (FQ↔LQ delta helper). Smoke test: `EQT` Q1=69 rows vs Q4=89 rows — divergence confirms wiring. **New capability:** clients can now pass `?quarter=2025Q1` etc. to every `/api/query<N>` + `/api/export/query<N>` endpoint. |
| Vectorized `portfolio_context._compute_metrics` | `251072b` | 2.7s → 730ms HTTP warm. GICS sector mapping moved into SQL `CASE WHEN` columns on all 3 portfolio queries; iterrows/apply eliminated; groupby + idxmax replace the row loops. Remaining hotspot is `get_nport_children` N+1 loop (286ms) — next optimization target. |

---

## Entity infrastructure — COMPLETE

All entity data quality and infrastructure work from this session is done. The entity layer is in its cleanest state since launch.

### What shipped (2026-04-11 + 2026-04-12)

| Category | Items | Summary |
|---|---|---|
| **Admin auth** | INF12 | 15 admin routes gated with `ADMIN_TOKEN` + `hmac.compare_digest` |
| **Entity merges** | INF4, INF4d, INF4c, INF6, INF8, INF4f | 101 CRD-format fragmented pairs merged (Loomis $83B, Boston Partners $97B, 96 batch, Tortoise, Trian, NorthStar). ~$287B combined AUM consolidated. |
| **CRD normalization** | INF4b, INF17b | `_normalize_crd()` in entity resolver + fetch_ncen.py. LTRIM retroactive lookup. Prevents new fragmentation. |
| **Fuzzy-match gates** | INF17 Phase 3, INF17b | Brand-token overlap gate in `build_managers.py` + `fetch_ncen.py`. 21-word stopword list. Rejection logging. |
| **Managers cleanup** | INF17 Phase 1, INF7 | 127 CRD/AUM scrubs + 3 Soros/Peter Soros manual fixes + 2 Trian parent_name scrubs |
| **Misattribution fixes** | INF17 Phase 2 | 5 entities self-rooted ($1.27B corrected) |
| **Classification fixes** | L4-1, L4-2 | 6 reclassifications (3 passive→mixed, 3 mixed→active) |
| **Sub-adviser rollup** | 43i, INF18 | 4 Baird sub-advisers self-rooted for EC. 2 NorthStar orphan_scan edges closed. Financial Partners Group confirmed legitimate. |
| **Rollup preservation** | INF17 Phase 4 | 3 coincidentally-correct rollups preserved via merge overrides (Carillon→RJF, Nikko→Sumitomo, Nikko EU→JP). Carillon DM fixed to self-root. |
| **Override framework** | INF9e, INF9a/b/c/d | `entity_overrides_persistent` live in prod (47 rows). diff/promote coverage. 5 action types. entity_id fallback for ghost parents. |
| **Relationship suppression** | INF9c + follow-up | 6 bad parent_bridge edges suppressed. entity_id fallback for PARENT_SEEDS ghosts. |
| **Snapshot fallback** | INF13 | Verified: fail-fast already in place, no shutil.copy2 |
| **CRD audit** | INF4e | 4 borderline pairs confirmed as CRD pollutions, added to managers scrub |

### Production state

- **validate_entities.py --prod:** 9 PASS / 0 FAIL / 7 MANUAL
- **entity_overrides_persistent:** 47 rows (24 reclassify + 2 set_activist + 9 merge/DM + 6 suppress_relationship + 6 merge/Phase4)
- **managers.crd_number:** 127 polluted rows scrubbed to NULL
- **Entity fragmentation:** 101 pairs merged. 15 excluded as CRD pollutions (added to managers scrub).

---

## Open items — current priority order

### ⭐ Next tasks in order

_FreshnessBadge rolled out to all 11 tabs 2026-04-13 (`83836ee`).
Phase 0-B2 smoke CI shipped 2026-04-13 (`8cf0d82`) — fixture DB,
build script, smoke workflow, and 8 passing tests all committed.
Phase 4 Batch 4-A (Blueprint split) is now unblocked._

**1. Phase 4 Batch 4-A — Blueprint split — ~1 day, large refactor.** Split `scripts/app.py` (~1,400 lines) into domain Blueprints per `ARCHITECTURE_REVIEW.md` Phase 4-A. Target files: `app_db.py` (web-layer DB helpers, distinct from pipeline `scripts/db.py`), `app_bootstrap.py` (≤100 lines), `api_register.py`, `api_flows.py`, `api_entities.py`, `api_market.py`, `api_config.py`. Smoke CI from Phase 0-B2 is the regression guardrail: `test_smoke_response_equality` must stay green on the 4 monitored endpoints. Feature branch recommended. `app.py` kept as `app_legacy.py` until smoke passes for ≥1 week. Does NOT include FastAPI swap (moved to Phase 4+).

**2. Phase 4 Batch 4-B — queries.py service layer split — ~half day.** Follows 4-A. Split `queries.py` (~5,400 lines) into SQL construction (`queries.py`, leaner), response shaping (`serializers.py`), and cache helpers (`cache.py` with explicit key constants).

**Known pre-existing issues — do not absorb:**
- BL-3 — Write-path consistency implementation (T2 drop+recreate scripts). Follow-on to the 2-A audit. Substantial work.
- BL-8 — Re-enable suppressed pre-commit rules.
- BL-9 — `/api/short_long` returns 500 with `KeyError 'long_value_k'`.
- BL-10 — `/api/export/query<N>` still 500s for q6/q10/q11/q15 (multi-table shapes).

### 1. Stage 5 cleanup — scheduled 2026-05-09+, requires explicit authorization

Original tables retained for 30-day rollback after Phase 4 cutover (2026-04-09). Cleanup list:
- Delete 4 INF9d ghost entities (eid=20194, 20196, 20201, 20203 — no aliases, no identifiers, no holdings)
- Drop legacy pre-entity tables (holdings v1, old parent_bridge snapshots, etc.)
- Requires explicit user authorization before any deletion

### 2. N-PORT data refresh

`fund_holdings_v2` data is stale through Oct 2025. Pipeline run needed to fetch current N-PORT filings. Run manually from terminal:
```bash
! python3 -u scripts/fetch_nport.py --test  # test first
! python3 -u scripts/fetch_nport.py          # full run (authorized)
```
This is a pipeline operation, NOT a data QC task. Do not run without explicit user authorization.

### 3. Vanilla-JS retirement — earliest 2026-04-20

Retirement window opens 2026-04-20 (1 week stable after Phase 4 cutover).
Requires explicit user authorization. Files to delete:
- web/react-src/ (POC)
- web/templates/index.html
- web/static/app.js
Do not delete before 2026-04-20. Do not delete without explicit confirmation.

### 4. Architecture upgrade — next steps (see ARCHITECTURE_REVIEW.md)

Phase 0-A: ✅ DONE 2026-04-13 (commit `e201885`). See ROADMAP COMPLETED.
Phase 1 Batch 1-A: ✅ DONE 2026-04-13 (commit `a8dd77a`). See ROADMAP COMPLETED.
Phase 1 Batch 1-B1: ✅ DONE 2026-04-13 (commit `d3a2fcb`). See ROADMAP COMPLETED.
Phase 2 Batch 2-A: ✅ DONE 2026-04-13 (commit `700bcdb`). See ROADMAP COMPLETED.
Phase 3 Batch 3-A: ✅ DONE 2026-04-13 (commit `731f4a0`). See ROADMAP COMPLETED.
Phase 0-B1: ✅ DONE 2026-04-13 (commit `7f62b7d`). Option 2 (committed binary snapshot).
data_freshness pipeline write hooks + FreshnessBadge: ✅ DONE 2026-04-13 (commit `2892009`).
Phase 1 Batch 1-B2: error envelope + Pydantic schemas + React error boundaries.
**Gated on vanilla-JS retirement (≥2026-04-20)** — the `{data, error, meta}`
envelope would break the legacy frontend at port 8001 if landed before then.
Phase 0-B2: smoke CI with committed binary fixture. Half day. Gates Batch 4-A.
Next recommended task.
Phase 3+ (portfolio_context precompute): trigger-based, runs in parallel to
Phase 4. Not urgent (730ms current perf acceptable after Batch 2-A).
Phase 4 Batch 4-A (Blueprint split): gated on Phase 0-B2.
FreshnessBadge rollout to remaining tabs: follow-up to 2892009.
BL-3: write-path consistency implementation (follow-on to 2-A audit).
BL-8: re-enable suppressed pre-commit rules. Small rule-by-rule PRs.
BL-9: `/api/short_long` 500 — pre-existing `KeyError 'long_value_k'`.
BL-10: `/api/export/query<N>` 500 on q6/q10/q11/q15 — multi-table shape
mismatches.

### 5. Minor follow-ups

- **Amundi → Amundi Taiwan rollup** — eid=830 + eid=4248 roll to eid=752 Amundi Taiwan via parent_bridge_sync/manual. Should roll to global Amundi SA parent. Separate manual fix.
- **Financial Partners Group fragmentation** — eid=1600 "Inc" vs eid=9722 "LLC" with circular orphan_scan. Minor structural cleanup.
- **INF9c suppress_relationship entity_id stability** — PARENT_SEEDS entity_ids are deterministic in practice but not contractually guaranteed. The 6 suppress rows use entity_id fallback which is best-effort across full --reset. Full fix would require adding CIK identifiers to PARENT_SEEDS brand ghosts.

---

## Critical gotchas — discovered the hard way

### a–e: Flask, IIFEs, switchTab, bandit 1.8.3, nosec B608

See full text in `87bc812` version.

### f. Data model traps

- **`entity_overrides_persistent`** — 47 rows in prod. 5 action types (reclassify, set_activist, alias_add, merge, suppress_relationship). 4 extension columns. Resolution via `(identifier_type, identifier_value)` with CRD normalization. suppress_relationship uses entity_id fallback for ghost parents.
- **`managers.aum_total` + `crd_number`** — 127 rows scrubbed to NULL. Use `SUM(holdings_v2.market_value_usd)` for AUM.
- **`_resolve_db_path()`** — fail-fast RuntimeError when DB locked. No shutil.copy2 (INF13 verified).
- **CRD normalization** — `entity_sync._normalize_crd()` strips leading zeros. LTRIM retroactive lookup.
- **13F-NT vs 13F-HR** — NT filers have zero `holdings_v2` rows.

### g–h: React/AG Grid/Tailwind landmines, inline style cascade

See `87bc812` version.

### i. Fuzzy name matching — brand-token Jaccard

Both `build_managers.py` and `fetch_ncen.py` have `_BRAND_STOPWORDS` + `_brand_tokens_overlap()`.

### j–r: DuckDB similarity gap, audit join bug, merge_staging DROP+CREATE, sync SKIP, manually_verified unreliable, 13F-NT AUM distortion, CRD normalization, CIK transfer rule, LOW_COV classification rule

See prior versions for full text.

### s. Sub-adviser vs subsidiary for EC rollup

When non-fund entity rolls under parent for EC via transitive_flatten/orphan_scan, verify if subsidiary (keep) or sub-adviser (self-root). 43i found 28 zero-overlap institution pairs; 24 legitimate, 4 Baird sub-advisers fixed.

### t. Conviction tab is served by two separate endpoints

`/api/query3` → `query3()` (Active holder market cap analysis) and `/api/portfolio_context` → `portfolio_context()` (holder sector concentration) are both labeled "Conviction" but are independent. Optimizing one does not speed up the other. `query3` remains slow (~1.4s) due to per-CIK percentile subqueries; `portfolio_context` is ~730ms after the 2026-04-12 vectorization.

### aa. `DATE '9999-12-31'` is the SCD open-row sentinel (not NULL) — Phase 0-B2 discovery

Across every entity SCD table — `entity_rollup_history`, `entity_aliases`,
`entity_identifiers`, `entity_classification_history`, `entity_relationships`
— "currently open" rows have `valid_to = DATE '9999-12-31'`. `valid_to IS
NULL` matches zero rows in prod. Any filter that tries to select the
current row must use the sentinel explicitly (see `scripts/build_fixture.py`
for the pattern). The `entity_current` view enforces this correctly;
derivative code should query the view instead of re-rolling the filter.

### bb. `entity_current` is a VIEW, not a table — Phase 0-B2 discovery

`entity_current` is the only user-defined view in the DB. Any fixture build
or snapshot that copies tables into a fresh DB must **recreate the view**
after tables land. The view definition is mirrored in
`scripts/build_fixture.py` and must stay in sync with prod — if prod
redefines the view (via a migration), update the build script in the
same PR.

### cc. `entity_identifiers.identifier_type` is lowercase — Phase 0-B2 discovery

Identifier type values are lowercase strings: `'cik'`, `'crd'`, `'series_id'`.
Filters using uppercase (`WHERE identifier_type = 'CIK'`) silently return
zero rows. Spot-checked during fixture build after the initial `managers`
filter returned 0. No `UPPER()` normalization in prod; everything assumes
lowercase.

### dd. `DB_PATH_OVERRIDE` env var lets test harnesses swap DBs — Phase 0-B2

`scripts/app.py:83` reads `DB_PATH_OVERRIDE` env var at module load and
substitutes it for the default `data/13f.duckdb`. Used by
`tests/smoke/conftest.py` to point Flask at the committed fixture DB.
Undefined in normal use. Do not couple further logic to this var — it is
a minimal override surface for test fixtures, not a general runtime
configuration mechanism.

### z. `record_freshness` + FreshnessBadge wiring (Batch 3-A follow-on)

- Pipeline scripts that rebuild a precomputed table should call `db.record_freshness(con, 'table_name')` at the end of their main() (after CHECKPOINT). Helper is no-op on a pre-Batch-3A DB that lacks `data_freshness`, so it's safe to leave in scripts that may run against old DBs.
- React `FreshnessBadge` from `common/FreshnessBadge.tsx` takes a `tableName` prop and renders a color-coded pill. It shares one fetch of `/api/v1/freshness` across the page via a module-level cache; call `resetFreshnessCache()` if the page needs to force-reload (e.g. after a post-promote hot-swap).
- SLA thresholds are **hour-based** in the component, with a 90-day quarter proxy for quarter+N thresholds from `ARCHITECTURE_REVIEW.md`. Revisit if the thresholds need to be anchored to actual quarter boundaries.
- Only FlowAnalysisTab currently uses the badge. To wire others: Register/Conviction → `summary_by_parent`; Ownership Trend / Peer Rotation / Sector Rotation → `investor_flows`; Fund Portfolio → `fund_holdings_v2`.

### y. `fund_family_patterns` + `data_freshness` (ARCH-3A)

- `get_nport_family_patterns()` in `scripts/queries.py` now reads from `fund_family_patterns` (DB) and falls back to `_FAMILY_PATTERNS_FALLBACK` (in-code dict, identical content). Memoized at module scope — restart the app to pick up a table edit. If you add a new pattern, add it to **both** the DB (via another migration or direct INSERT) **and** `_FAMILY_PATTERNS_FALLBACK` until the fallback is removed.
- `data_freshness (table_name PK, last_computed_at, row_count)` is empty on arrival. Pipeline scripts should `INSERT OR REPLACE` a row at the end of each successful rebuild. `/api/freshness` + `/api/v1/freshness` already serve whatever's in the table.
- **Staging workflow caveat:** `sync_staging.py` / `diff_staging.py` / `promote_staging.py` are **entity-graph only**. For non-entity reference tables (new tables, schema changes, seed data), use `merge_staging.py --tables <name>` with an entry in `TABLE_KEYS`, or for brand-new tables with no prod data, a one-shot migration script applied first to staging then to prod. `fund_family_patterns: None` and `data_freshness: ["table_name"]` are already registered in `TABLE_KEYS`.

### x. `get_nport_children_batch()` replaces the loop (ARCH-2A.1)

- Hot-path callers in `query1` (Register) and `portfolio_context` (Conviction) now call `get_nport_children_batch(parent_names, ticker, quarter, con, limit=5)` once and dict-lookup per parent. Do NOT reintroduce a per-parent loop — the win is 14× (297ms → 21ms for 25 parents).
- `get_nport_children()` (singular) is kept for the currently-unused `get_children()` fallback path. If you delete `get_children()`, delete the singular too.
- `get_nport_children_q2` is INTENTIONALLY not batched — it is a FQ↔LQ delta helper (gotcha u). If someone asks to batch it, that is a separate, distinct task.
- `summary_by_parent` is a read-only table on every request path. Any new code reading from it is fine; anything that would compute it on demand must instead go into `build_summaries.py` (T4 pipeline).

### w. `_RT_AWARE_QUERIES` + endpoint classification block (ARCH-1B1)

- `_RT_AWARE_QUERIES = frozenset({1, 2, 3, 5, 12, 14})` at module scope in `app.py` is the single source of truth for which `query<N>` endpoints accept `rollup_type`. Both `api_query` and `api_export` dispatch on it. If you change a `query<N>` signature to add or remove `rollup_type`, update this set AND the classification comment block above the Flask routes section.
- `api_export` extracts tabular data from structured responses: q7 → `positions`, q1/q16 → `rows`, anything else → passed whole to `build_excel`. q6/q10/q11/q15 still 500 because their shapes are multi-table and the extractor doesn't know them (BL-10).
- Endpoint classification block at the top of the routes section is the freeze artifact consumed by Batch 4-A — do not add a route without adding a row there.

### v. `/api/*` dual-mount + `before_request` ordering (ARCH-1A)

- All public `/api/*` routes are aliased under `/api/v1/*` by `_register_v1_aliases()` in `app.py` (near the bottom of the file). `/api/admin/*` is excluded because it's gated by `admin_bp`'s own `before_request` for token auth.
- The app-level `_validate_query_params()` `before_request` fires on both `/api/*` and `/api/v1/*`. For `/api/admin/*` paths it returns `None` so admin_bp's own token validator gets to run.
- `/api/config/quarters` (new canonical) and `/api/admin/quarter_config` (legacy, kept for vanilla-JS until 2026-04-20 retirement) both call `_quarter_config_payload()`. Do not consolidate yet — remove legacy in a separate PR after retirement.
- Ticker regex in app.py is `^[A-Z]{1,6}(\.[A-Z])?$` (corrected from the spec's literal `^[A-Z]{1,6}[.A-Z]?$` which did not accept BRK.B despite the spec comment saying it should).

### u. `get_nport_children_q2` is a FQ↔LQ delta helper — do not add a `quarter` param

The 2026-04-12 quarter-param refactor threaded `quarter=LQ` through every query function that hardcoded LQ — except `get_nport_children_q2`. It compares `{FQ}` vs `{LQ}` inside a single SELECT (columns `q1_shares`, `q4_shares`) and is semantically pinned to the first-vs-latest quarter pair. Leave it as-is unless you also generalize the delta semantic.

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: efab352 or newer
pgrep -f "scripts/app.py"       # dev server PID
curl -s http://localhost:8001/api/tickers | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"  # 6500+
python3 scripts/validate_entities.py --prod   # 9 PASS / 0 FAIL / 7 MANUAL
python3 -c "import duckdb; print(duckdb.connect('data/13f.duckdb',read_only=True).execute('SELECT COUNT(*) FROM entity_overrides_persistent').fetchone()[0], 'overrides in prod')"  # 47
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization.
- Never mutate production data to simulate test conditions.
- Always update `ROADMAP.md` after completing a task.
- Entity changes: `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- Reference-table changes: `merge_staging.py --tables <name>`.
- Entity overrides: 47 rows in prod. 5 action types. suppress_relationship uses entity_id fallback.
- Read files in full before editing.
- Confirm destructive actions before running.
- Use `python3 -u` for background tasks.
- Never trust `managers.manually_verified=True`.
- Never use `fuzz.token_sort_ratio` alone for firm name matching.
- CRD values must be normalized via `_normalize_crd()`.
- Batch entity merges: always transfer CIK identifiers before closing.
- N-PORT coverage < 50%: keep classification as `mixed`.
- Sub-adviser vs subsidiary: verify before EC rollup.

---

## User collaboration preferences

- Terse, direct communication. Lead with the answer.
- Quick fixes preferred over comprehensive refactors unless explicitly asked.
- User tests in Safari, sometimes Chrome.
- Suggest `! <cmd>` for commands the user should run themselves.
- Flag duplicate ROADMAP items before adding.
- Don't delete files/data/rows without explicit confirmation.
- Report scope precisely: "entities affected" ≠ "holdings at risk" ≠ "dollars at risk".

---

## Session ledger (newest first — key data QC commits only)

```
8cf0d82 feat: Phase 0-B2 — smoke CI fixture + response snapshot tests
83836ee feat: FreshnessBadge rollout — wire into all 11 tabs
2892009 feat: data_freshness pipeline write hooks + FreshnessBadge component
7f62b7d docs: Phase 0-B1 — CI fixture DB design decision
731f4a0 feat: Batch 3-A — fund_family_patterns + data_freshness tables
700bcdb feat: Batch 2-A — N+1 batching + summary_by_parent audit + write-path risk map
d3a2fcb feat: Batch 1-B1 — endpoint classification + export parity
a8dd77a feat: Batch 1-A — /api/v1/ dual-mount, quarter_config rename, input guards
e201885 ci: Phase 0-A — lint/bandit CI (ruff + pylint + bandit on every push)
799dbde docs: ROADMAP + NEXT_SESSION_CONTEXT — Phase 4 cutover complete
2bac928 docs: REACT_MIGRATION + NEXT_SESSION_CONTEXT — Phase 4 cutover docs
002fab0 feat: React Phase 4 cutover — Flask serves web/react-app/dist/
a555a91 test: set playwright expect.timeout 10s in config
dc27d25 test: capture Playwright visual regression baselines (11 tabs, AAPL)
442084f docs: ARCHITECTURE_REVIEW.md — sequencing and gate fixes (3 changes)
6291c6b docs: ARCHITECTURE_REVIEW.md — final revision pass (6 changes)
2c99d34 ARCH: add ARCHITECTURE_REVIEW.md + sync ROADMAP + NEXT_SESSION_CONTEXT. 6-phase upgrade plan. Recommended next task: Batch 1-A routing hygiene (~1hr, app.py only).
573b504 docs: REACT_MIGRATION.md — Phase 2+3 complete, Phase 4 pending
b8d95af docs: ROADMAP entry for 2026-04-12 backend cleanup trio
251072b Vectorize portfolio_context._compute_metrics (2.7s → 730ms)
94b0402 Add quarter param to query endpoints + 25 query functions
c2c5441 Remove log_shadow_diff() and all 4 call sites
8403cf8 docs: backfill Phase 3 commit hash in ROADMAP + NEXT_SESSION_CONTEXT
c836813 Phase 3 visual polish: badge consolidation + cross-nav + print CSS + Playwright
11d7cce INF9c follow-up: entity_id fallback + backfill 6 rows
976733a ROADMAP: close INF9d as won't fix + Stage 5 cleanup
e0ffd4d INF4f: NorthStar CRD merge (eid=6693→7693)
67f3f51 INF17 Phase 4: preserve 3 rollups + Carillon DM + close 3 CRDs
f6076a3 43i/INF18: NorthStar orphan_scan fix + Financial Partners confirmed
b543030 INF9c: suppress 6 bad parent_bridge relationships
8f8d9f2 INF9b: 9 Securian DM12 override rows
a0d6685 INF9a/b/c/d: schema + replay extensions
47bb627 INF9e: diff/promote + 24 overrides promoted
4ff0006 INF17b: brand-token gate in fetch_ncen.py
46877c5 INF17 Phase 1: scrub 127 managers rows
1e01b6b L4-1: 3 mixed→active
73f6acd INF4c: batch merge 96 CRD-format fragmented pairs
eddb05c INF4d: Boston Partners merge ($96.58B)
d89e663 INF4b + INF17b: CRD normalization
ffa9796 INF8: Trian merge
eaab03b INF6: Tortoise Capital merge
a3c20e8 L4-2: 3 classification fixes
ff49dbc INF4: Loomis Sayles merge
0634682 INF17 Phase 3: build_managers.py fuzzy-match fix
6743f11 INF17 Phase 2: self-root 5 entities
1a43376 INF7: Soros/VSS cleanup
d51db60 INF12: admin Blueprint
b53e3fa INF9 Route A: 24 overrides to staging
```
