# Entity Master Data Management (MDM) Architecture

_Last updated: April 4, 2026_
_Status: Phase 1 — In Progress_

---

## Overview

This document tracks the design, implementation status, deferred items, and validation gates for the Entity MDM system. This system replaces the brittle string-matching and keyword-based parent rollup logic with a production-grade temporal graph model.

**Primary goal:** Eliminate silent data corruption from name-based entity matching. Provide mathematically precise institutional ownership rollups suitable for M&A analysis and board-level reporting.

**Runs parallel to existing system.** Zero breaking changes until Phase 4 explicitly authorized.

---

## Architecture Summary

### Five Core Tables + One View

| Table | Purpose | Key Constraint |
|-------|---------|---------------|
| `entities` | Immutable master registry | BIGINT PK via sequence |
| `entity_identifiers` | CIK/CRD/SERIES_ID bridge | ux_identifier_active — one active mapping per identifier globally |
| `entity_relationships` | Graph of institutional relationships | ux_er_active + ux_primary_parent |
| `entity_aliases` | All name variants with types | ux_ea_preferred — one preferred alias per entity |
| `entity_classification_history` | SCD Type 2 classification | ux_ech_active — one active classification per entity |
| `entity_rollup_history` | Persisted rollup outcomes | ux_rollup_active — rollup stored as data not logic |
| `entity_current` | Standard VIEW (Phase 1) | Upgrade to MATERIALIZED VIEW in Phase 4 |

### Two Strategic Principles

1. **Identity vs Aggregation are separate concerns**
   - Identity = `entity_id` (what is this entity?)
   - Aggregation = `entity_rollup_history` (how does it roll up?)
   - Never conflated — sub_adviser relationships exist in graph but never drive rollup

2. **Deterministic current state enforced at DB level**
   - Exactly one active row per entity per dimension
   - Enforced by partial unique indexes, not application logic
   - Application logic is second line of defense only

### Rollup Type
All rollups use `rollup_type = 'economic_control_v1'`. Future rollup worldviews (regulatory_parent_v1, brand_parent_v1) can coexist via this field without schema changes.

---

## Implementation Phases

### Phase 1 — Build and Seed ⏳ IN PROGRESS
**Scope:** Create all tables, seed top 50 parents, populate from existing data, run validation gates.
**Status:** Prompt sent to Claude Code. Awaiting completion.
**Validation gate:** All 11 gates must pass before merge to production.

### Phase 2 — Wire N-CEN as Primary Feeder ⬜ NOT STARTED
**Scope:** Update fetch_ncen.py to populate entity_relationships on each run. Add entity_identifiers_staging table for conflict resolution before promotion to canonical table.
**Depends on:** Phase 1 validation gate passed.
**Validation gate:** Wellington sub-advisory relationships correctly modeled.

### Phase 3 — Long-tail Filer Resolution ⬜ NOT STARTED
**Scope:** Batch resolve ~5,000 unmatched CIKs via SEC company search API. Populate entity_aliases. Attempt parent matching.
**Target:** >80% of 5,000 CIKs resolved.

### Phase 3.5 — Form ADV Schedules A/B ⬜ NOT STARTED
**Scope:** Parse ADV Schedule A (Direct Owners) and B (Indirect Owners). Populate entity_relationships with wholly_owned and parent_brand types. Handle JV and multi-adviser structures.
**Notes:** This is where multi-parent / JV structures will be properly modeled. See Deferred Items #1.

### Phase 4 — Migration ⛔ REQUIRES EXPLICIT AUTHORIZATION
**Scope:** Migrate holdings, fund_holdings, beneficial_ownership to use entity_id FK.
**Migration approach:** Dual-write → shadow reads → parity validation → cutover. NOT a fast table swap.
**Stages:**
1. Create holdings_v2 with entity_id FK, backfill, build indexes
2. Shadow reads — run both queries, compare results, log discrepancies (2 weeks)
3. Parity validation — zero unexplained differences, manual sign-off
4. Cutover — switch reads to holdings_v2, keep holdings as fallback 30 days
5. Cleanup — rename tables, upgrade entity_current to MATERIALIZED VIEW, add REFRESH to run_pipeline.sh
**Rollback:** holdings_legacy retained 30 days post-cutover.

---

## Deferred Items

These items were explicitly scoped out of Phase 1 but must not be forgotten. Each has a target phase.

| # | Item | Target Phase | Reason Deferred | Notes |
|---|------|-------------|-----------------|-------|
| 1 | Multi-parent / JV structures | Phase 3.5 | Requires ADV Schedule A/B data to model correctly | is_primary = FALSE on secondary relationships preserves them in graph now |
| 2 | Indirect ownership chains | Phase 4+ | Requires recursive CTE — design supports it, not needed for Phase 1 rollups | Current design only supports direct relationships — must document this limitation in UI |
| 3 | Staging table for identifier conflicts (entity_identifiers_staging) | Phase 2 | Phase 1 hard-fails on conflicts which is correct for top 50 parents — long-tail needs softer landing | Add before N-CEN wiring to prevent pipeline brittleness |
| 4 | Structural integrity validation in CI | Phase 2 | Phase 1 runs validation manually — automate in pipeline | Add to run_pipeline.sh post-merge checks |
| 5 | is_inferred flag on synthetic dates | Phase 1 ✓ | Already implemented — all '2000-01-01' seed dates marked is_inferred = TRUE | Enables future distinction of real vs synthetic history |
| 6 | rollup_type label | Phase 1 ✓ | Already implemented — rollup_type = 'economic_control_v1' on all records | Future rollup worldviews coexist via this field |
| 7 | Upgrade entity_current to MATERIALIZED VIEW | Phase 4 | Standard VIEW acceptable at current scale | Must add REFRESH MATERIALIZED VIEW to run_pipeline.sh at Phase 4 cutover |
| 8 | True historical data pre-2000 | Never/Optional | No historical filing data available — synthetic inception date is correct choice | is_inferred = TRUE clearly marks these |
| 9 | Full indirect ownership / voting control computation | Phase 4+ | Requires recursive graph traversal — not needed for current use cases | Design supports via recursive CTE when needed |
| 10 | Multiple rollup worldviews (regulatory_parent, brand_parent) | Phase 4+ | economic_control_v1 sufficient for current analysis | rollup_type field already supports this without schema changes |

---

## Validation Gates

All 11 gates must pass before Phase 1 merge to production. Gates 1-4 are structural (zero tolerance). Gates 5-11 are output correctness.

| # | Gate | Test | Threshold | Type |
|---|------|------|-----------|------|
| 1 | structural_aliases | Entities with >1 preferred active alias | Exactly 0 | Structural |
| 2 | structural_identifiers | Identifier uniqueness violations | Exactly 0 | Structural |
| 3 | structural_no_identifier | Entities with no identifier | <5% of total | Structural |
| 4 | structural_no_rollup | Non-standalone entities with no rollup parent | Exactly 0 | Structural |
| 5 | top_50_parents | Case-insensitive set overlap for top 50 parents | PASS at 50/50; MANUAL at 48-49/50 (documented legacy corrections); FAIL below | Output |
| 6 | top_50_aum | AUM match for top 50 parents | PASS: per-name ≤0.01% AND total ≤0.01%; MANUAL: total ≤0.5% with ≤2 per-name diffs (documented legacy corrections); FAIL above | Output |
| 7 | random_sample | n=100 random CIK→parent mappings | 100% match | Output |
| 8 | known_edge_cases | Geode not under Fidelity, Wellington not as parent | Manual sign-off | Output |
| 9 | standalone_filers | Filers with no parent appear in rollup | Count matches legacy | Output |
| 10 | total_aum | Sum of all inst holdings value | <0.01% difference | Output |
| 11 | row_count | Entity count >= managers count | New >= existing | Output |

Validation results saved to `logs/entity_validation_report.json` after each run.

---

## Known Limitations (Phase 1)

These are architectural limitations of the current design, not bugs. Must be documented in the UI where relevant.

1. **Direct relationships only** — entity_relationships models one-hop parent/child. Indirect ownership chains (grandparent) not computed until Phase 4+.

2. **Synthetic inception dates** — all seed data uses '2000-01-01' as valid_from. True historical relationship data (pre-2000 or between 2000 and first filing date) is not available. All such records marked is_inferred = TRUE.

3. **Single rollup worldview** — economic_control_v1 is the only rollup type in Phase 1. Regulatory parent and brand parent views deferred to Phase 4+.

4. **~5,000 long-tail filers unresolved** — CIKs not matching any PARENT_SEEDS entry remain as standalone entities. Resolution in Phase 3.

5. **Wellington / multi-family sub-advisory** — Wellington sub-advises Hartford, John Hancock, and other fund families. In Phase 1 Wellington appears as sub_adviser in those relationships (is_primary = FALSE). Full multi-parent modeling deferred to Phase 3.5.

---

## Files

| File | Purpose |
|------|---------|
| `scripts/entity_schema.sql` | Complete DDL for all tables, sequences, indexes, view |
| `scripts/build_entities.py` | Phase 1 population script |
| `scripts/validate_entities.py` | Validation gate runner |
| `logs/entity_build.log` | Transaction log from build_entities.py |
| `logs/entity_build_conflicts.log` | Identifier conflicts during population |
| `logs/entity_validation_report.json` | Validation gate results |
| `logs/entity_overrides.log` | Manual override audit trail |

---

## Admin Override Process

Priority 6 overrides (manual corrections) handled via CSV upload to `POST /admin/entity_override`.

CSV format:
```
entity_id, action, field, old_value, new_value, reason, analyst
1001, reclassify, classification, unknown, hedge_fund, "Confirmed HF via ADV", ST
1002, merge, parent_entity_id, NULL, 500, "Subsidiary of Blackstone confirmed", ST
1003, alias_add, alias_name, NULL, "Blackstone Real Estate", "Known brand name", ST
```

All overrides written with `source='manual'`, `confidence='exact'`. Logged to `logs/entity_overrides.log` with timestamp and analyst initials.

UI for overrides: deferred until override volume exceeds ~500 entries or additional analysts onboarded.

---

## Design Decision Log

| Date | Decision | Rationale | Alternative Rejected |
|------|----------|-----------|---------------------|
| Apr 4 2026 | BIGINT PK via sequence, not VARCHAR | JOIN performance on 18M row tables | VARCHAR slugs — brittle on name changes |
| Apr 4 2026 | Graph not tree (entity_relationships) | Wellington/Geode sub-advisory cannot be modeled as tree | self-referencing parent_entity_id on entities table |
| Apr 4 2026 | SCD Type 2 on all mutable facts | Historical queries must be point-in-time accurate | Overwrite-in-place — destroys history |
| Apr 4 2026 | Rollup persisted to entity_rollup_history | Rollup as data not logic — queryable in SQL, historically auditable | Compute rollup in Python on every query |
| Apr 4 2026 | N-CEN as primary feeder, keyword as fallback | N-CEN is structured data — keyword matching is fragile | Keyword matching as primary |
| Apr 4 2026 | Partial unique indexes for active rows | DB-level enforcement — application logic is second line only | Application-level duplicate checks only |
| Apr 4 2026 | Standard VIEW for entity_current (Phase 1) | Always fresh, acceptable at current scale | MATERIALIZED VIEW — needs explicit REFRESH |
| Apr 4 2026 | is_primary BOOLEAN on relationships | Makes rollup parent explicit not implicit | LIMIT 1 with ORDER BY priority_rank |
| Apr 4 2026 | alias_type + is_preferred (not one alias per entity) | Legal/brand/filing names are distinct use cases | Single alias per entity — too restrictive |
| Apr 4 2026 | Dual-write migration (Phase 4) | Zero downtime, fully reversible | Fast table swap — lock contention risk |
| Apr 5 2026 | Sentinel date 9999-12-31 instead of NULL for valid_to | DuckDB does not support partial unique indexes — sentinel date preserves DB-level uniqueness enforcement via full unique constraints | NULL semantics with partial indexes — not supported in DuckDB |
| Apr 5 2026 | Nullable key columns (primary_parent_key, preferred_key) for flag-gated uniqueness | DuckDB allows multiple NULLs in UNIQUE and does not support constraints on generated columns — app-maintained nullable key gives equivalent enforcement | Generated column with CASE — constraints on generated columns unsupported in DuckDB 1.4 |
| Apr 5 2026 | Amova/Nikko consolidation accepted as legacy data correction | Amova Asset Management is former name of Nikko Asset Management — legacy system split them into two separate parents ($213.8B each), new entity model correctly merges under Nikko ($427.5B). This is the first documented legacy data correction caught by the validation gates. | Keeping Amova split to force gate 5/6 to exact match — would enshrine known bug |
