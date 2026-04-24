# Deferred Followups — Tracking Index

Single index of INF## items outside the active work stream. Reconciled 2026-04-22
after conv-12 (Phase 2 admin refresh + Wave 2 pipeline migrations closed; see
`docs/REMEDIATION_PLAN.md §Changelog (2026-04-22 conv-12)`).

Last refreshed: 2026-04-22 (conv-12 doc-sync).

## Open items

| ID | Title | Source doc | Priority | Status |
|----|-------|-----------|----------|--------|
| INF25 | BLOCK-DENORM-RETIREMENT Step 4 — `ticker` / `entity_id` / `rollup_entity_id` / `lei` drops on v2 fact tables | `ROADMAP.md §Open items`; `docs/data_layers.md §7`; `docs/findings/int-09-p0-findings.md §4` | Architectural | **UNBLOCKED post-Phase-2.** Exit criteria from int-09 Phase 0 now all satisfied (mig-12 done via p2-05, read-site audit tool `scripts/audit_read_sites.py` shipped, join pattern proven, `is_latest` sweep covered 149 sites across `queries.py`). Remaining prerequisite: dual-graph resolution decision for `rollup_entity_id` (two worldviews — EC + DM). Schedulable any time. |
| INF27 | CUSIP residual-coverage tracking tier | `ROADMAP.md §Open items`; `docs/data_layers.md §11` | Standing | **STANDING curation** — pipeline handles automatically via `build_classifications.py` + `run_openfigi_retry.py`. Revisit trigger: net-increase in `pending` rows across two consecutive runs. |
| INF37 | `backfill_manager_types` residual — 9 entities / 14,368 rows | `ROADMAP.md §Open items` | Standing | **STANDING curation** — add missing entities to `categorized_institutions_funds_v2.csv` and re-run `backfill_manager_types.py` opportunistically. |
| INF38 | BLOCK-FLOAT-HISTORY — true float-adjusted `pct_of_float` denominator | `docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md §14.10`; `ROADMAP.md §Open items` | Low-Medium | **UNBLOCKED post-Phase-2.** First new `SourcePipeline` subclass has landed (`load_13f_v2.py`). Still needs a new float-history data source before the tier can be implemented in `enrich_holdings.py` Pass B. |
| P2-FU-01 | Legacy `run_script` allowlist references retired scripts | `scripts/admin_bp.py` (INF12 router, `/run_script` endpoint) | Low | **NEW (conv-12).** After w2-01 … w2-05 retirements the `run_script` allowlist in `admin_bp.py` still names `fetch_nport.py` / `fetch_adv.py` / `fetch_market.py` / `fetch_ncen.py` / `fetch_13dg.py`. Endpoint will 500 if invoked against a retired script; prune after one clean quarterly cycle against the framework so any stale Makefile/scheduler paths surface first. |
| P2-FU-03 | ADV SCD Type 2 conversion | `scripts/pipeline/load_adv.py` (w2-05 chose `direct_write`); `docs/data_layers.md` (`adv_managers` row) | Medium | **NEW (conv-12).** Wave 2 shipped ADV as `direct_write` on `(crd,)` natural key. SCD Type 2 is the natural long-term shape given ADV amendments; deferred because (a) which columns carry history is an open design question and (b) no prod workflow needs point-in-time ADV today. Follow-up when a downstream consumer asks for history. |
| int-22 | Prod `is_latest` inversion on `holdings_v2` 2025Q4 — rollback executed | `docs/findings/int-22-p0-findings.md`; `scripts/rollback_run.py` | — | **CLOSED 2026-04-22 (int-22-prod-execute-and-verify)** — Option C rollback executed on prod. Finding #1 cleared (0 false-positive `is_latest=TRUE` rows on `holdings_v2` 2025Q4). Finding #2 cleared (`/api/v1/tickers` + `query1` recovered). Readonly snapshot refreshed. |
| int-23 | `load_13f_v2.py` idempotency + enrichment sequencing | `docs/findings/int-23-design.md`; `scripts/pipeline/base.py` | — | **CLOSED 2026-04-23 (int-23-impl)** — Option (a) shipped: `_promote_append_is_latest` refuses the flip when staged rows would downgrade `ticker` / `entity_id` / `rollup_entity_id` from non-NULL to NULL. PRAGMA existence guard skips retired columns. Whole run fails on any refusal; manifest `error_message` stores truncated JSON payload. 7 new unit tests in `tests/pipeline/test_base_downgrade_refusal.py`. |

## Closed during Remediation Program (2026-04-22)

| ID | Title | Closure |
|----|-------|---------|
| INF26 | OpenFIGI retry hygiene — `_update_error()` permanent-pending bug | **CLOSED 2026-04-22** (int-10) |
| INF28 | Schema constraint hygiene — `securities.cusip` PK + VALIDATOR_MAP | **CLOSED 2026-04-22** (int-12, PR #95, migration 011) |
| INF29 | Priceability refinement — `is_otc` flag for OTC grey-market | **CLOSED 2026-04-22** (int-13, PR #97, migration 012) |
| INF30 | BLOCK-MERGE-UPSERT-MODE — NULL-only merge in `merge_staging.py` | **CLOSED 2026-04-22** (int-14) |
| INF31 | BLOCK-MARKET-DATA-WRITER-CONVENTION — `fetch_date` discipline | **CLOSED 2026-04-22** (int-15, PR #90) |
| INF32 | BLOCK-QUARTERLY-UPDATE-INTEGRITY — Makefile 13F load step | **CLOSED 2026-04-22** (obs-10) |
| INF33 | BLOCK-CI-ACTIONS-NODE20-DEPRECATION — Node 24 upgrade | **CLOSED 2026-04-22** (obs-12) |
| INF34 | `queries.py` `rollup_type` filter on summary_by_parent / investor_flows reads | **CLOSED 2026-04-19** (`62ad0eb`) |
| INF35 | f-string interpolation cleanup in `build_summaries.py` | **CLOSED 2026-04-22** (int-16) |
| INF36 | NULL `top10_*` placeholders — columns dropped | **CLOSED 2026-04-22** (int-17, PR #99, migration 013) |
| INF39 | BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE — pre-flight schema diff | **CLOSED 2026-04-19** (`f22312e`) |
| INF40 | BLOCK-L3-SURROGATE-ROW-ID — stable surrogate PK | **CLOSED 2026-04-22** (mig-06, PRs #103 #104, migration 014) |
| INF41 | BLOCK-READ-SITE-INVENTORY-DISCIPLINE — rename sweep | **CLOSED 2026-04-22** (mig-07, PR #101, `scripts/audit_read_sites.py`) |
| INF42 | BLOCK-DERIVED-ARTIFACT-HYGIENE — fixture provenance + CI gate | **CLOSED 2026-04-22** (mig-08, PR #86) |
| INF45 | BLOCK-SCHEMA-DIFF-L4-EXTENSION | **CLOSED 2026-04-22** (mig-09) |
| INF46 | BLOCK-SCHEMA-DIFF-L0-EXTENSION | **CLOSED 2026-04-22** (mig-10) |
| INF47 | BLOCK-SCHEMA-DIFF-CI-WIRING | **CLOSED 2026-04-22** (mig-11) |
| P2-FU-02 | `scheduler.py` / `update.py` / `benchmark.py` stale-reference audit | **CLOSED 2026-04-22** (p2fu-02) — scheduler/update/benchmark repointed to SourcePipeline subclasses. |
| P2-FU-04 | ADV ownership boundary for `cik_crd_direct` + `lei_reference` | **CLOSED 2026-04-22** (p2fu-04) — boundary documented in data_layers.md §ADV managers + admin_refresh_system_design.md cross-ref. |

Closed / non-open INF## items (INF1–INF24 plus INF9a–e) are not repeated here —
see `ROADMAP.md §Closed items` for their closure records.

## Deferred tactical corrections

Items too small to warrant their own INF## but tracked for future doc-update sessions:

| Item | Source | Status |
|------|--------|--------|
| `validate_entities` baseline header correction: 8/1/7 → 8/2/6 | `ROADMAP.md` current-state header; `docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md §14.10` | **APPLIED 2026-04-19** |
| Rename historical refs `block/pct-of-float-period-accuracy` → `block/pct-of-so-period-accuracy` | Various findings docs | Next batched doc-update |
| `pct_of_float` → `pct_of_so` terminology retirement across project | `ROADMAP.md`; `docs/data_layers.md` Appendix A; `docs/pipeline_inventory.md` | Next batched doc-update |
| `docs/data_layers.md §7`: add `pct_of_so_source` as Class B audit column | `docs/data_layers.md §7` | Next batched doc-update |
| `docs/pipeline_violations.md`: close `pct_of_float` violation entries with Phase 1b/1c/4b commit citations | `docs/pipeline_violations.md` | Next batched doc-update |

## v2-table migration hardening package

INF39 + INF40 + INF41 + INF42 form a coherent package covering the distinct
failure classes seen during pct-of-so. **All four closed 2026-04-22** (INF39 at
2026-04-19). Any future L3 canonical schema migration should reference this
package for pre-flight discipline:

- **INF39** — pre-flight schema divergence detection (`scripts/pipeline/validate_schema_parity.py` + `make schema-parity-check`)
- **INF40** — stable surrogate row-ID for rollback replay (migration 014)
- **INF41** — mechanically exhaustive rename sweep (`scripts/audit_read_sites.py`)
- **INF42** — derived-artifact hygiene (`build_fixture.py` provenance + CI gate)

## Schema-parity extension package

INF45 + INF46 + INF47 extend the INF39 parity gate to L4 + L0 + CI.
**All three closed 2026-04-22** (mig-09 / mig-10 / mig-11). `make schema-parity-check --layer all` now covers L0, L3, L4, and the `entity_current` VIEW.

## Conventions

- **Source doc** = authoritative prose on scope, rationale, and resolution criteria.
- **Priority** = author's best judgment at capture time. Medium = prevents a repeating failure class or unblocks work; Low = isolated hygiene; Architectural = non-trivial sequencing required.
- **Status**: Open, Deferred, Standing, or date-stamped closure note.
