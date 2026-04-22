# 13F Ownership — Next Session Context

_Last updated: 2026-04-22 (ops-16 refresh). Main HEAD: `4484137` (conv-07 convergence doc update)._

This file is the startup briefing for a fresh Claude Code session. Read it end-to-end on open, then continue with the live ROADMAP / REMEDIATION docs for current work.

---

## Program state — remediation in flight

The **Remediation Program** (`docs/REMEDIATION_PLAN.md` + `docs/REMEDIATION_CHECKLIST.md`) is the active work stream. 67 PRs merged, 46 of ~73 items closed as of 2026-04-21.

### Theme status

| Theme | Scope | Status |
|---|---|---|
| **Theme 4 — Security hardening** | admin auth, TOCTOU, validators writing to prod, 5 unlisted direct-to-prod writers, pinned deps | **8/8 DONE** |
| **Theme 2 — Observability + audit trail** | ingestion_manifest coverage, freshness hooks, impact_id hardening, log rotation, docs headline | **13/13 DONE** |
| **Theme 3 — Migration + schema discipline** | atomic promotes, migration 004 retrofit, fetch_adv DROP→CREATE, schema_versions stamp, pipeline-violations tail | **5/14** |
| **Theme 1 — Data integrity foundation** | OpenFIGI RC1–RC4, ticker backfill, denorm retirement, INF25–INF31, INF35–INF38 | **6/~20** |
| **Theme 5 — Operational surface** | README/prompts refresh, write_path_risk_map, MAINTENANCE.md, Blueprint split doc, ROADMAP hygiene | **14/18** |

### Open theme progress

**Theme 1 (int)** — closed: int-01, int-02, int-04, int-05, int-10, int-18 (standing). Next up: Batch 1-B (int-06 ticker-backfill forward hooks); Batch 1-C merges (int-03 triage, int-07 benchmark gate, int-14 NULL-only merge, int-15 market_data fetch_date, int-21 series_id tail). int-19 deferred to Phase 2.

**Theme 3 (mig)** — closed: mig-01, mig-02, mig-03, mig-04, mig-13. Next up: mig-14 (REWRITE_BUILD_MANAGERS routing + dry-run), mig-06/mig-09/mig-10 (schema-parity extensions, INF40/45/46), mig-07/mig-08/mig-11 (rename-sweep audit, derived-artifact hygiene, CI wiring). mig-05 (admin refresh) SUPERSEDED → Phase 2. mig-12 (load_13f_v2) Phase 3.

**Theme 5 (ops)** — closed: ops-01 through ops-12, ops-15, ops-17. Remaining: ops-13 (denorm drift doc), ops-14 (INF26-29 ROADMAP rows), ops-16 (this item — DOC-UPDATE-PROPOSAL admin_bp.py revisit flag), ops-18 (BLOCKED — missing rotating_audit_schedule.md).

### Pending data ops (code shipped, `--confirm` required)

- **int-10 INF26 staging sweep** — OpenFIGI permanent-pending flip on the existing retry queue.
- **obs-04 13D/G ingestion_impacts backfill** — one-off script staged; live run gated behind `--confirm`.

---

## Next priorities

1. **Close Theme 3 next-ready items.** Pick mig-14 (REWRITE_BUILD_MANAGERS) or schema-parity extensions (mig-09 / mig-10) — both are bounded and independent.
2. **Theme 1 Batch 1-C.** int-14 (NULL-only merge mode for `merge_staging.py`) and int-15 (market_data `fetch_date` discipline) are well-scoped.
3. **Theme 5 remainder.** ops-13, ops-14, and ops-16 are doc-only closures against ROADMAP + data_layers.md. ops-18 stays BLOCKED until the missing `rotating_audit_schedule.md` source is located or formally abandoned.
4. **Phase 2 kickoff** (trigger-based): admin refresh system full scope (supersedes mig-05). Needs design doc first.

All entity mutations flow through `sync_staging.py → diff_staging.py → promote_staging.py`. Reference-table mutations use `merge_staging.py --tables <name>`. Never direct-to-prod writes.

---

## First 5 minutes — read these

1. `~/ClaudeWorkspace/CLAUDE.md` — workspace rules (file routing, tone, naming).
2. `docs/REMEDIATION_PLAN.md` — full program state (5 themes, acceptance criteria, items, sequencing).
3. `docs/REMEDIATION_CHECKLIST.md` — grep-friendly item status.
4. `docs/PROCESS_RULES.md` — rules for large-data scripts.
5. `ROADMAP.md` — backlog not covered by the remediation program (DM follow-ups, data-QC carry-forwards, MT-1..MT-6 future-phase).
6. Auto memory at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main`. Remediation PRs merge from per-item branches (e.g. `ops-16-p1`).
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - **FastAPI + uvicorn** — `scripts/app.py` (thin entry ~115 lines) + 9 router modules (`app_db`, `api_common`, `api_config`, `api_register`, `api_fund`, `api_flows`, `api_entities`, `api_market`, `api_cross`) + `admin_bp.py` (token auth via `Depends`). OpenAPI at `/docs` + `/redoc`. Flask retired 2026-04-13.
  - **Service layer** — `scripts/queries.py` (~5,500 lines) + `scripts/serializers.py` + `scripts/cache.py`.
  - **DuckDB** — `data/13f.duckdb` (prod), `data/13f_staging.duckdb` (staging), `data/13f_readonly.duckdb` (app snapshot).
  - **React full-app** — `web/react-app/`, served by FastAPI at :8001 from `web/react-app/dist/`. Dev server on :5174.
  - **API contract** — public at `/api/v1/*`. 6 endpoints use the Phase 1-B2 envelope. Hand-written `src/types/api.ts` still authoritative; `api-generated.ts` sparse until `schemas.py` expansion lands.

### Prod state (as of conv-07, 2026-04-21)

- `entities` ~26,535 · `entity_identifiers` ~33K · `entity_relationships` ~18K · `entity_overrides_persistent` 245.
- `holdings_v2` ~14.09M rows, `entity_id` coverage 84.13%.
- `fund_holdings_v2` ~9.3M rows, newest `report_date` 2026-02-28.
- `beneficial_ownership_v2` ~52K rows, enriched ~94.5%.
- `investor_flows` 17,396,524 · `summary_by_parent` 63,916 (EC + DM worldviews).
- `cusip_classifications` 132,618 (v1.4 prod, migration 003 applied).
- `schema_versions` stamps current; `make schema-parity-check` clean on L3 canonicals.
- `validate_entities --prod` baseline: **8 PASS / 2 FAIL (wellington_sub_advisory + phase3_resolution_rate) / 6 MANUAL**.
- `make freshness` PASS on all 7 critical tables.

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                                  # expect: ## main...origin/main, clean
git log -5 --oneline                            # expect: 4484137 or newer
pgrep -f "scripts/app.py"                       # dev server PID (if running)
python3 scripts/validate_entities.py --prod --read-only   # 8 PASS / 2 FAIL / 6 MANUAL
make freshness                                  # PASS on 7 critical tables
make schema-parity-check                        # 0 divergences on L3 canonicals
pytest tests/ -x                                # green
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization.
- Never mutate production data to simulate test conditions.
- Always update `ROADMAP.md` COMPLETED section after closing an item (date + details).
- Entity changes: `sync_staging.py → diff_staging.py → promote_staging.py`.
- Reference-table changes: `merge_staging.py --tables <name>`.
- Read files in full before editing.
- Confirm destructive actions before running.
- Use `python3 -u` for background tasks (buffered print swallows output otherwise).
- Never trust `managers.manually_verified=True`.
- Never use `fuzz.token_sort_ratio` alone for firm-name matching — use brand-token overlap (`_brand_tokens_overlap`).
- CRD values must be normalized via `_normalize_crd()`.
- Batch entity merges: always transfer CIK identifiers before closing the source row.
- N-PORT coverage < 50% → keep classification as `mixed` regardless of active/passive split.
- Sub-adviser vs subsidiary: verify before EC rollup.
- Pre-commit hooks must pass. Never `--no-verify`. Fix the underlying issue.

---

## Critical gotchas — architectural facts (preserve across sessions)

### DB schema + query patterns

**`entity_current` is a VIEW, not a table.** Only user-defined view in prod. Fixture builds or snapshot rebuilds must recreate it after tables land. Definition mirrored in `scripts/build_fixture.py` — keep in sync.

**`entity_identifiers.identifier_type` is lowercase.** `'cik'`, `'crd'`, `'series_id'`. Uppercase filters silently return zero rows. No `UPPER()` normalization anywhere.

**SCD open-row sentinel is `DATE '9999-12-31'`, not NULL.** Applies to `entity_rollup_history`, `entity_aliases`, `entity_identifiers`, `entity_classification_history`, `entity_relationships`. `valid_to IS NULL` matches zero rows in prod. Use `entity_current` view where possible.

**`holdings_v2` composite key is filing-line grain.** Not `(cik, ticker, quarter)`. True key is `(cik, ticker, quarter, put_call, security_type, discretion)` — separate rows for put vs call options, non-discretionary vs discretionary. Any "total position" aggregation must `SUM(shares), SUM(market_value_usd) GROUP BY (cik, ticker, quarter)`.

**`fund_holdings_v2` stores `'N/A'` literally** for CUSIP-less positions (~832K rows). DERA parity depends on preserving this sentinel — do not normalize to NULL without a coordinated pass.

**`DuckDB NOW() vs CURRENT_TIMESTAMP`** — use `NOW()` inside `ON CONFLICT DO UPDATE SET` with `executemany`. DuckDB binder misreads `CURRENT_TIMESTAMP` as a column name in that context.

**`DB_PATH_OVERRIDE` env var** swaps DBs for test harnesses (`scripts/app.py:83`). Used by `tests/smoke/conftest.py`. Do not couple further logic to it — narrow override surface only.

### Entity data plane

**`entity_overrides_persistent` — 245 rows** as of DM15c. 5 action types (reclassify, set_activist, alias_add, merge, suppress_relationship). Resolution via `(identifier_type, identifier_value)` with CRD normalization. `suppress_relationship` uses `entity_id` fallback for PARENT_SEEDS ghosts (not contractually stable across `--reset`).

**INF9d eids 20194 / 20196 / 20201 / 20203** are live PARENT_SEEDS brand shells (Pacific Life Insurance, Stowers Institute, Stonegate Global Financial, International Assets Advisory). Each has aliases + ADV lineage. **Do not delete** despite historic "ghost" framing.

**`PARENT_SEEDS` count is 110** in `scripts/build_entities.py:6`. Older planning docs that cite 50 are stale.

**Fragmented-CIK rule.** When merging two entities, INSERT identifiers (esp. CIK) on the survivor BEFORE closing the source row. Closing first breaks `total_aum` gate — see INF4c lesson (~$166B impact).

**Classification rule.** N-PORT coverage < 50% → keep `mixed` regardless of active/passive split.

### Pipeline + app wiring

**Staging workflow is the law.** `sync_staging.py` CTAS strips column DEFAULTs and indexes — resolver scripts must call `_ensure_staging_indexes()` to restore them. Otherwise `ON CONFLICT DO NOTHING` silently no-ops against invisible NULL-SCD rows.

**Promote atomicity (Theme 3).** `promote_nport.py` + `promote_13dg.py` now wrap `_mirror_manifest_and_impacts` + DELETE+INSERT in a single transaction (mig-01, PRs #31 #33). The audit-trail wipe bug that inflated caveats historically is fixed — no new reconstruction scaffolding needed.

**`_RT_AWARE_QUERIES` in `app.py`** — single source of truth for which `query<N>` endpoints accept `rollup_type`. If you change a `query<N>` signature to add/remove `rollup_type`, update the set AND the classification comment block above the routes.

**`/api/*` dual-mount** — `_register_v1_aliases()` near the bottom of `app.py` aliases every public `/api/*` route under `/api/v1/*`. `/api/admin/*` excluded (own token validator). `_validate_query_params()` `before_request` fires on both mounts.

**Ticker regex is `^[A-Z]{1,6}(\.[A-Z])?$`** (accepts BRK.B). The literal spec regex `^[A-Z]{1,6}[.A-Z]?$` was wrong.

**`get_nport_children_batch()`** replaces per-parent loops in `query1` (Register) and `portfolio_context` (Conviction). 14× speedup (297ms → 21ms for 25 parents). Do NOT reintroduce singular per-parent loops.

**`get_nport_children_q2` is intentionally NOT batched** — it's an FQ↔LQ delta helper pinned to the first-vs-latest quarter pair. Do not generalize without generalizing the delta semantic.

**`get_nport_family_patterns()`** reads `fund_family_patterns` (2 cols: `pattern`, `inst_parent_name`; 83 rows; PK `(inst_parent_name, pattern)`) and falls back to `_FAMILY_PATTERNS_FALLBACK`. Memoized at module scope — restart the app to pick up table edits. Any planning doc that references a 3-col shape is stale.

**`admin_bp.py:108`** — the OpenFIGI `data[0]` selector is diagnostic-only (no persistent writes back to `securities` / `cusip_classifications`). If a future PR adds write semantics to the admin OpenFIGI path, this becomes the same class of bug as BLOCK-SEC-AUD-1 (RC1) and needs disambiguation. Tracked as ops-16 doc-update item.

**`api-generated.ts` is sparser than `api.ts`** — do not delete `api.ts` until `scripts/schemas.py` is expanded to cover the ~55 response shapes. Mechanical React-tab migration before that is a compile-time type regression. Tracked as ARCH-4C-followup.

### Observability

**`record_freshness` + FreshnessBadge.** Pipeline scripts that rebuild a precomputed table must call `db.record_freshness(con, 'table_name')` at end of main (after CHECKPOINT). Helper is no-op on pre-Batch-3A DBs. React `FreshnessBadge` from `common/FreshnessBadge.tsx` shares one `/api/v1/freshness` fetch via module-level cache; `resetFreshnessCache()` forces reload.

**`ingestion_manifest` coverage.** Now covers MARKET, NPORT, 13DG, NCEN, ADV (Theme 2 closed). Any new source needs a row-per-fetch with `object_type` / `object_key`.

**`impact_id` allocation** centralized in `pipeline/manifest.py::_next_id()`. Prod sequences are drifted relative to MAX(id); do not revert to DEFAULT `nextval`.

### Type badge + formatting

**Type badges** use `getTypeStyle()` from `common/typeConfig.ts`. Never inline.

**Formatting rules** — all `%` 2 decimals with trailing zeros; zero → em-dash; highlight yellow `#fef9c3`.

---

## User collaboration preferences

- Terse, direct communication. Lead with the answer.
- Plain professional tone. No preambles, no trailing summaries unless asked.
- Quick fixes preferred over comprehensive refactors unless explicitly requested.
- User tests in Safari, occasionally Chrome.
- Suggest `! <cmd>` for commands the user should run themselves.
- Flag duplicate ROADMAP items before adding.
- Don't delete files / data / rows without explicit confirmation.
- Report scope precisely: "entities affected" ≠ "holdings at risk" ≠ "dollars at risk".
- Include SEC EDGAR filing links where applicable.
- Financial models: blue = inputs, black = formulas (IB convention).
- Cite every data point (filing type + section + date). Flag approximates with `~`.

---

## Where to look

| Question | Source |
|---|---|
| What's the current open-item queue? | `docs/REMEDIATION_CHECKLIST.md` |
| Why is an item scoped the way it is? | `docs/REMEDIATION_PLAN.md` (per-item Notes column) |
| What's the broader backlog outside remediation? | `ROADMAP.md` (§ Open items, § MT-1..MT-6) |
| What's the decision history? | `docs/findings/*.md` (per-item phase-0 and closeout findings) |
| What's the audit origin? | `docs/SYSTEM_AUDIT_2026_04_17.md` §12 |
| What's the pipeline protocol? | `scripts/pipeline/protocol.py` (Source / DirectWrite / Derived) |
| What's the current prod DDL? | `docs/canonical_ddl.md` + `docs/data_layers.md` |
| What's the data-layer coverage? | `docs/data_layers.md` §0 headline (last refreshed obs-05, PR #66) |

Regenerate the top block of this file at session close so future sessions land oriented. Keep it short — structural gotchas above the fold; session narratives belong in commit messages and findings docs, not here.
