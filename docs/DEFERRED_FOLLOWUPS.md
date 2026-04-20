# Deferred Followups — Tracking Index

Single index of open INF## items awaiting a batched doc-update session or
dedicated fix block. Source of truth for the next doc-update session.

Last refreshed: 2026-04-19 (`block/schema-diff-inf39` Phase 1 close).

## Open items

| ID | Title | Source doc | Priority | Status |
|----|-------|-----------|----------|--------|
| INF25 | BLOCK-DENORM-RETIREMENT sequencing | `ROADMAP.md` §Open items; `docs/data_layers.md` §7 | Architectural | Open |
| INF26 | OpenFIGI retry hygiene — `_update_error()` permanent-pending bug | `ROADMAP.md` §Open items | Low | Open |
| INF27 | CUSIP residual coverage gap | `ROADMAP.md` §Open items | Low | Open |
| INF28 | Schema constraint hygiene — `securities.cusip` PK + VALIDATOR_MAP | `ROADMAP.md` §Open items | Medium | Open |
| INF29 | Priceability refinement — OTC grey-market `is_priceable=TRUE` | `docs/data_layers.md` §6 S1 | Low | Open |
| INF30 | BLOCK-MERGE-UPSERT-MODE — NULL-only / column-scoped merge | `ROADMAP.md` §Open items | Medium | Open |
| INF31 | BLOCK-MARKET-DATA-WRITER-CONVENTION — `fetch_date` discipline | `ROADMAP.md` §Open items | Low | Open |
| INF32 | BLOCK-QUARTERLY-UPDATE-INTEGRITY — missing 13F load step | `ROADMAP.md` §Open items | Medium | Open |
| INF33 | BLOCK-CI-ACTIONS-NODE20-DEPRECATION | `ROADMAP.md` §Open items | Low | Open |
| INF34 | `queries.py` `rollup_type` filter missing on `summary_by_parent` / `investor_flows` reads | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.10 addendum; `ROADMAP.md` §Open items | Low | **CLEARED 2026-04-19** |
| INF35 | f-string interpolation refinement in `build_summaries.py` | `ROADMAP.md` §Open items; `docs/REWRITE_BUILD_SUMMARIES_FINDINGS.md` | Low | Open |
| INF36 | NULL `top10_*` placeholders in `summary_by_parent` | `ROADMAP.md` §Open items; `docs/REWRITE_BUILD_SUMMARIES_FINDINGS.md` | Low | Open |
| INF37 | `backfill_manager_types` residual — 9 entities / 14,368 rows | `ROADMAP.md` §Open items | Low | Open (standing curation) |
| INF38 | BLOCK-FLOAT-HISTORY — true float-adjusted `pct_of_float` | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.10 | Low-Medium | Open |
| INF39 | BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE — pre-flight schema diff | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.10; `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` §13 | Medium | **Implementation complete 2026-04-19; pending Serge merge sign-off** |
| INF40 | BLOCK-L3-SURROGATE-ROW-ID — stable surrogate PK for rollback | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.5 / §14.11.4 | Medium | Open |
| INF41 | BLOCK-READ-SITE-INVENTORY-DISCIPLINE — mechanically exhaustive rename sweep | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.11.4 / §14.11.5 | Medium | Open |
| INF42 | BLOCK-DERIVED-ARTIFACT-HYGIENE — stale dist/fixture detection | `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.10 addendum | Medium | Open (new 2026-04-19) |
| INF45 | BLOCK-SCHEMA-DIFF-L4-EXTENSION — extend parity check to L4 derived tables + `entity_current` VIEW | `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` §9 / §14 | Low | Open (new 2026-04-19, sibling of INF39) |
| INF46 | BLOCK-SCHEMA-DIFF-L0-EXTENSION — extend parity check to L0 control-plane tables | `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` §9 / §14 | Low | Open (new 2026-04-19, sibling of INF39) |
| INF47 | BLOCK-SCHEMA-DIFF-CI-WIRING — add `validate_schema_parity.py --json` to smoke CI once fixture reproduces canonical L3 structure | `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` §10 Q5 / §14 | Low | Open (new 2026-04-19, sibling of INF39) |

Closed / non-open INF## items (INF1–INF24 plus INF9a–e) are not repeated here —
see `ROADMAP.md` §Completed items for their closure records.

## Deferred tactical corrections

Items too small to warrant their own INF## but that the next batched doc-update
session must apply:

| Item | Source | Target session |
|------|--------|---------------|
| `validate_entities` baseline header correction: 8/1/7 → 8/2/6 | `ROADMAP.md` current-state header; `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.10 | Next batched doc-update |
| Rename historical references `block/pct-of-float-period-accuracy` → `block/pct-of-so-period-accuracy` | Various docs (findings, NEXT_SESSION_CONTEXT, etc.) | Next batched doc-update |
| `pct_of_float` terminology retired across project; `pct_of_so` is canonical going forward | `ROADMAP.md`; `docs/canonical_ddl.md` (rename DDL block); `docs/pipeline_inventory.md` (enrich_holdings Pass B) | Next batched doc-update |
| `docs/data_layers.md` §7: add `pct_of_so_source` as Class B audit column | `docs/data_layers.md` §7 | Next batched doc-update |
| `docs/pipeline_violations.md`: close any `pct_of_float` violation entry with Phase 1b/1c/4b commit citations | `docs/pipeline_violations.md` | Next batched doc-update |
| `docs/NEXT_SESSION_CONTEXT.md`: add pct-of-so block closure + Phase 5 post-merge fix note | `docs/NEXT_SESSION_CONTEXT.md` | Next batched doc-update |

## v2-table migration hardening package

INF39 + INF40 + INF41 + INF42 form a coherent package covering the distinct
failure classes seen in pct-of-so:

- **INF39** — schema divergence between staging and prod detected pre-flight
  (**implementation complete 2026-04-19**; ships `scripts/pipeline/validate_schema_parity.py`
  + `config/schema_parity_accept.yaml` + `make schema-parity-check`. See
  `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` §13.)
- **INF40** — stable surrogate row-ID so rollback can replay writer semantics
- **INF41** — mechanically exhaustive rename sweep (grep-based, scripted)
- **INF42** — derived-artifact hygiene (React dist, CI fixture) — newest,
  introduced by the pct-of-so post-merge regressions of 2026-04-19

Any future L3 canonical schema migration (column rename, type change, index
rebuild) should reference this index for pre-flight checks. Three of the four
items in the package (INF39/INF40/INF42) carry a medium priority — they
prevent a repeating class of silent failure, not a one-off bug.

## Schema-parity extension package (sibling of INF39)

INF45 + INF46 + INF47 extend the INF39 parity gate incrementally. All three
are low-priority — INF39 covers the blast radius (L3 canonical tables) on
day 1, and the extensions only matter once the trigger conditions fire:

- **INF45** — L4 derived + `entity_current` VIEW. Trigger: an L4 build fails
  on prod after passing on staging.
- **INF46** — L0 control-plane. Trigger: a control-plane migration produces
  silent staging/prod drift.
- **INF47** — CI wiring. Trigger: CI fixture starts reproducing canonical
  L3 structure (today it's a fresh rebuild per run and cannot exhibit drift).

## Conventions

- **Source doc** = the authoritative prose on scope, rationale, and resolution
  criteria. ROADMAP.md entries are typically one-line summaries; depth lives
  in the findings docs.
- **Priority** is the author's best judgment at the time of capture and may be
  revised in a future session. Medium = prevents a repeating class of failure
  or unblocks other work; Low = isolated hygiene or cosmetic; Architectural =
  non-trivial sequencing / dependency analysis required before implementation.
- **Status**: Open, Cleared, or a date-stamped closure note.
