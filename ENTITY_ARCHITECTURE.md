# Entity Master Data Management (MDM) Architecture

_Last updated: April 7, 2026_
_Status: Phase 3.5 — Parse in progress_

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

### Phase 2 — Wire N-CEN as Primary Feeder ✅ COMPLETE
**Scope:** Update fetch_ncen.py to populate entity_relationships on each run. Add entity_identifiers_staging table for conflict resolution before promotion to canonical table.
**Depends on:** Phase 1 validation gate passed. ✅
**Validation gate:** Wellington sub-advisory relationships correctly modeled. ✅ PASS — 22 fund rollups verified against ncen role='adviser', 9 subsidiary rollups correct, 0 sub_adviser with is_primary=TRUE, 111 sub_adviser relationships correctly non-rollup.
**Deliverables:**
- `entity_identifiers_staging` table + sequence + indexes (schema)
- `scripts/entity_sync.py` shared module (6 functions, used by build_entities.py and fetch_ncen.py)
- `build_entities.py` step 4 refactored to use entity_sync (phase 1 gates still pass)
- `fetch_ncen.py` wired as incremental feeder (--staging flag, idempotent)
- `--refresh-reference-tables` flag on build_entities.py
- Wellington validation gate (#12) added to validate_entities.py
**Build metrics:** 20,193 entities, 29,023 identifiers, 11,621 relationships, 20,416 aliases. Validation: 8 PASS, 4 MANUAL, 0 FAIL.

### Phase 3 — Long-tail Filer Resolution ✅ COMPLETE
**Scope:** Batch resolve ~5,000 unmatched CIKs via SEC company search API. Populate entity_aliases. Attempt parent matching.
**Target:** >80% of 5,000 CIKs resolved.
**Results:**
- 5,328 target CIKs identified (self-rollup + unknown classification + non-PARENT_SEEDS)
- 5,293 processed in full run (5 already resolved in test run), **100% SEC metadata retrieval**
- 153 parent matched (fuzzy score ≥85 against existing parent aliases → `parent_brand` relationships)
- 104 SIC classified (unknown → active/hedge_fund via financial SIC codes)
- 181 alias updated (SEC-registered name added as filing alias)
- 412 total enrichment actions (7.8% of targets — remainder are legitimate standalone filers)
- 4,881 remain correctly standalone (corporates, banks, insurance companies with no parent in PARENT_SEEDS)
**Validation:** 13 gates — 8 PASS, 5 MANUAL, 0 FAIL. Resolution rate gate MANUAL: SEC >80% met, enrichment <25% documented as population characteristic.
**Deliverables:**
- `scripts/resolve_long_tail.py` — batch resolver with `--limit`, `--all`, `--dry-run`, `--staging`
- `entity_sync.py` extended: `resolve_cik_via_sec()`, `classify_from_sic()`, `attempt_parent_match()`, `update_classification_from_sic()`
- `logs/phase3_resolution_results.csv` — full results (5,293 rows)
- `logs/phase3_unmatched.csv` — unmatched entities with best fuzzy scores

### Phase 3.5 — Form ADV Schedules A/B ⏳ IN PROGRESS
**Scope:** Parse ADV Schedule A (Direct Owners) and B (Indirect Owners). Populate entity_relationships with wholly_owned and parent_brand types. Handle JV and multi-adviser structures.
**Data source:** ADV PDFs from `reports.adviserinfo.sec.gov/reports/ADV/{crd}/PDF/{crd}.pdf` (IAPD API returns 403; XML feed lacks schedules; PDFs are accessible).
**Three-phase pipeline:** `--download-only` (5 req/s) → `--parse-only` (pdfplumber, CPU-bound) → `--match-only` (alias cache + rapidfuzz).
**Ownership code mapping:** E/D (≥50%) → wholly_owned, C (25-50%) → parent_brand, NA on entities → mutual_structure (Vanguard pattern), A/B (<25%) → skip.
**Status:** Download complete (3,652 PDFs, 8.4GB). Parse in progress (~103 of 3,652 CRDs parsed). Match + validation pending.
**Deliverables built:**
- `entity_sync.py`: `parse_adv_pdf()`, `insert_adv_ownership()`, `build_alias_cache()`, `_AliasCache` (C-optimized matching)
- `resolve_adv_ownership.py`: three-phase pipeline with `--download-only`, `--parse-only`, `--match-only`
- `entity_overrides_persistent` table + replay in `build_entities.py --reset` + persistence in `POST /admin/entity_override`
- `mutual_structure` relationship type + `mutual` control type added to schema CHECK constraints
- Two new validation gates: `phase35_adv_coverage`, `phase35_jv_review`
**Notes:** This is where multi-parent / JV structures are modeled. See Deferred Items #1.

**Operational safeguards (verified Apr 7 2026):**

| Safeguard | How it works |
|-----------|-------------|
| **No DB lock during parse** | `--parse-only` opens DB briefly to read target CRDs, then closes connection. Entire parse reads local PDFs and writes to CSV only. DB not held for hours. |
| **Incremental save** | Each firm's rows written to CSV immediately with `flush()`. If process is killed mid-run, all prior firms' data is on disk. |
| **Resume on restart** | On startup, reads existing `firm_crd` values from `adv_schedules.csv` into a set and skips already-parsed CRDs. Zero duplication across restarts. |
| **Memory-safe** | pdfplumber opened via `with` context manager, `page.close()` after each page, `gc.collect()` after each PDF. Peak memory ~300 MB (flat), previously leaked to 4.5 GB. |
| **Oversized PDFs tracked** | PDFs >10 MB skipped and logged to `logs/phase35_oversized.csv` with CRD, firm name, and size. |
| **Timed-out PDFs tracked** | PDFs exceeding `--timeout` (default 30s) skipped and logged to `logs/phase35_timed_out.csv`. |

**Retry workflow for skipped PDFs:**
1. Run initial pass: `python3 -u scripts/resolve_adv_ownership.py --parse-only --all --staging`
2. Review `logs/phase35_timed_out.csv` — retry with higher timeout: `--parse-only --all --staging --timeout 120`
3. Review `logs/phase35_oversized.csv` — these are genuinely large filings (PIMCO 45 MB, Bridgewater 12 MB). Raise `MAX_SIZE_MB` in script or parse manually if needed.
4. Resume logic handles all retries automatically — only un-parsed CRDs are attempted.

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
| 1 | ~~Multi-parent / JV structures~~ | ~~Phase 3.5~~ ✅ | Resolved Apr 6 2026 — ADV Schedule A parsed, JV entities flagged (multiple owners with codes C/D/E), highest-% owner gets is_primary=TRUE | JV entities logged to phase35_jv_entities.csv for manual review |
| 2 | Indirect ownership chains | Phase 4+ | Requires recursive CTE — design supports it, not needed for Phase 1 rollups | Current design only supports direct relationships — must document this limitation in UI |
| 3 | ~~Staging table for identifier conflicts (entity_identifiers_staging)~~ | ~~Phase 2~~ ✅ | Resolved Apr 5 2026 — `entity_identifiers_staging` table created, `entity_sync.py` routes all feeder conflicts through it | Build + incremental paths both use soft-landing |
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

4. **~~5,000 long-tail filers~~ → 4,881 standalone after Phase 3** — of 5,328 originally unresolved CIKs, 153 matched to existing parents via fuzzy match, 104 reclassified via SIC codes. Remaining 4,881 are legitimate standalone filers (corporates, banks, insurance companies) correctly self-rolled. No further resolution expected without expanding PARENT_SEEDS or Phase 3.5 ADV parsing.

5. **Wellington / multi-family sub-advisory** — Wellington sub-advises Hartford, John Hancock, and other fund families. In Phase 1 Wellington appears as sub_adviser in those relationships (is_primary = FALSE). Full multi-parent modeling deferred to Phase 3.5.

---

## Files

| File | Purpose |
|------|---------|
| `scripts/entity_schema.sql` | Complete DDL for all tables, sequences, indexes, view, staging table |
| `scripts/entity_sync.py` | Shared feeder module — entity lookup, creation, conflict routing (Phase 2) |
| `scripts/build_entities.py` | Full rebuild population script (`--reset`, `--refresh-reference-tables`) |
| `scripts/validate_entities.py` | Validation gate runner (12 gates including Wellington) |
| `scripts/fetch_ncen.py` | N-CEN feeder — incremental entity sync via `--staging` flag (Phase 2) |
| `scripts/resolve_long_tail.py` | Phase 3 batch CIK resolver via SEC EDGAR (`--limit`, `--all`, `--dry-run`) |
| `scripts/resolve_adv_ownership.py` | Phase 3.5 ADV ownership resolver (`--download-only`, `--parse-only`, `--match-only`) |
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
| Apr 5 2026 | Shared entity_sync.py module instead of inline feeder logic | Phase 2 N-CEN wiring, Phase 3 long-tail, and Phase 3.5 ADV all need the same get-or-create and conflict-routing pattern — shared module prevents code duplication and ensures both --reset rebuild and incremental feeder paths use identical logic | Inline per-script feeder code — would diverge over time |
| Apr 5 2026 | DB-backed primary-parent check (replace in-memory set) | entity_sync.insert_relationship_idempotent queries entity_relationships to check for existing primary parents — correct in both batch and incremental modes, no stale-set risk | In-memory has_primary_parent set — only works in batch mode, stale across transactions |
| Apr 5 2026 | SIC→classification mapping: conservative financial-only | Only financial SIC codes (6xxx range) map to classifications; non-financial codes stay 'unknown'. This avoids misclassifying corporates that file 13F (AMD=3674, airlines=4512). Phase 3 reclassified 104 entities via SIC. | Map all SIC codes — would produce false classifications for non-financial filers |
| Apr 5 2026 | Phase 3 parent matching: fuzzy against existing parents only, never create new parents | Prevents runaway parent proliferation from noisy SEC name data. 153 matched at score ≥85 to existing PARENT_SEEDS parents. New parent creation deferred to Phase 3.5 ADV parsing where ownership data is authoritative. | Create new parent entities from SEC names — would produce unvalidated parents |
| Apr 6 2026 | ADV data source: PDFs from IAPD, not XML feed or API | IAPD API returns 403; XML compilation feed (IA_FIRM_SEC_Feed) contains Part 1A header only, no Schedule A/B data; individual PDF filings at reports.adviserinfo.sec.gov are accessible (100% access rate on random sample) | IAPD API (blocked), XML feed (no schedule data) |
| Apr 6 2026 | ADV ownership code mapping: E/D → wholly_owned, C → parent_brand, NA entities → mutual_structure | SEC ADV Schedule A uses letter codes for ownership ranges (E=75%+, D=50-75%, C=25-50%, B=10-25%, A=5-10%). Only codes C+ represent meaningful control. Entity owners with NA (no equity percentage) on Schedule A indicate mutual ownership structures (Vanguard pattern). | Map all codes including A/B — would create relationships for insignificant minority interests |
| Apr 6 2026 | mutual_structure relationship type for Vanguard-style ownership | Vanguard's 33+ fund trusts collectively own the management company with no single controlling owner (all Schedule A entries marked NA). These get relationship_type='mutual_structure', is_primary=FALSE, and the management company stays as self-rollup. | Assign arbitrary primary parent — would misrepresent the actual ownership structure |
| Apr 6 2026 | Three-phase ADV pipeline (download/parse/match) | pdfplumber PDF parsing takes ~5-30s per file; 3,652 PDFs at ~8.4GB total makes a single-pass pipeline impractical (~37 hours). Splitting into download (12 min), parse (hours, restartable), match (seconds from CSV) allows each phase to run independently with disk-based intermediaries. | Single-pass pipeline — too slow and not restartable |
| Apr 6 2026 | entity_overrides_persistent table survives --reset | Manual corrections (reclassify, alias_add, merge) must persist across build_entities.py --reset rebuilds. Table stores CIK (not entity_id) so overrides can be re-resolved after entity_id reassignment. Replayed as Step 8 after rollup computation. | Store entity_id directly — breaks across rebuilds since entity_ids are reassigned from sequence |
