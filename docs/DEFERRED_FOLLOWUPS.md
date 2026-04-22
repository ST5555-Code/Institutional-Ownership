# Deferred Followups — Tracking Index

Single index of INF## items outside the active work stream. Reconciled 2026-04-22
after the Remediation Program closed (105 PRs, ~66 items; `docs/REMEDIATION_PLAN.md §Changelog`).

Last refreshed: 2026-04-22 (phase2-prep doc-sync).

## Open items

| ID | Title | Source doc | Priority | Status |
|----|-------|-----------|----------|--------|
| INF25 | BLOCK-DENORM-RETIREMENT sequencing (Step 4 — `ticker`/`entity_id`/`rollup_entity_id`/`lei` drops on v2 fact tables) | `ROADMAP.md §Open items`; `docs/data_layers.md §7`; `docs/findings/int-09-p0-findings.md §4` | Architectural | **DEFERRED to Phase 2** — execute after queries.py `is_latest` sweep + read-site audit. Dual-graph resolution decision still open. |
| INF27 | CUSIP residual-coverage tracking tier | `ROADMAP.md §Open items`; `docs/data_layers.md §11` | Standing | **STANDING curation** — pipeline handles automatically via `build_classifications.py` + `run_openfigi_retry.py`. Revisit trigger: net-increase in `pending` rows across two consecutive runs. |
| INF37 | `backfill_manager_types` residual — 9 entities / 14,368 rows | `ROADMAP.md §Open items` | Standing | **STANDING curation** — add missing entities to `categorized_institutions_funds_v2.csv` and re-run `backfill_manager_types.py` opportunistically. |
| INF38 | BLOCK-FLOAT-HISTORY — true float-adjusted `pct_of_float` denominator | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md §14.10`; `ROADMAP.md §Open items` | Low-Medium | **DEFERRED to Phase 2** — needs new float-history data source; execute after first new `SourcePipeline` subclass lands. |

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

Closed / non-open INF## items (INF1–INF24 plus INF9a–e) are not repeated here —
see `ROADMAP.md §Closed items` for their closure records.

## Deferred tactical corrections

Items too small to warrant their own INF## but tracked for future doc-update sessions:

| Item | Source | Status |
|------|--------|--------|
| `validate_entities` baseline header correction: 8/1/7 → 8/2/6 | `ROADMAP.md` current-state header; `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md §14.10` | **APPLIED 2026-04-19** |
| Rename historical refs `block/pct-of-float-period-accuracy` → `block/pct-of-so-period-accuracy` | Various findings docs | Next batched doc-update |
| `pct_of_float` → `pct_of_so` terminology retirement across project | `ROADMAP.md`; `docs/canonical_ddl.md`; `docs/pipeline_inventory.md` | Next batched doc-update |
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
