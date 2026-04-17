# Entity Master Data Management (MDM) Architecture

_Last updated: April 16, 2026 (part 2 — end of session)_
_Status: Phase 4 cutover complete (2026-04-09). Stage 5 cleanup complete (2026-04-13 — legacy `holdings`, `fund_holdings`, `beneficial_ownership` dropped). **Entity MDM at 24,632 entities / 33,521 identifiers / 18,105 relationships / 24,968 aliases / 24,675 classification rows / 55,708 rollup rows.** 2026-04-16 part-2 additions on top of earlier 4,141 series-resolve: `bootstrap_residual_advisers.py` added 6 new institution entities (Stone Ridge 24348, Bitwise 24349, Volatility Shares 24350, Dupree 24351, Baron 24352, Grayscale 24353) and `resolve_pending_series.py` +32 SUPPLEMENTARY_BRANDS (25 Tier A + 7 Tier B) resolved 279 more pending N-PORT series. `entity_relationships.last_refreshed_at TIMESTAMP` column is now **live on prod** (migration `add_last_refreshed_at.py` applied 2026-04-16; 13,685 / 17,826 rows = 76.77% backfilled from `created_at`; the rest will fill organically via `entity_sync.insert_relationship_idempotent`'s probe-gated stamping on next N-CEN / ADV refresh). 13D/G entity linkage shipped (commit `e231633`) — `beneficial_ownership_v2` now carries `rollup_entity_id` / `rollup_name` / `dm_rollup_entity_id` / `dm_rollup_name` alongside pre-existing `entity_id` (40,009 / 51,905 rows enriched = 77.08%). Pending residual: 1,805 N-PORT (337 Tier C real ETF specialty requiring per-family research + 1,186 deferred synthetics per D13 + misc ambiguous) + 2,591 13D/G-only filer CIKs outside the MDM (follow-up: `resolve_13dg_filers.py`)._

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

### Rollup Types

Two rollup worldviews coexist via the `rollup_type` field. Each entity has one row per type in `entity_rollup_history` (~24,347 entities × 2 worldviews ≈ 49K active rows; 55,138 total including closed history rows). As of 2026-04-16, both worldviews are also wired into the L4 derived tables: `summary_by_parent` PK is `(quarter, rollup_type, rollup_entity_id)` (per migration 004), and `investor_flows` / `ticker_flow_stats` carry `rollup_type` columns with EC + DM rows written per period.

| Rollup Type | Purpose | Data Source | Status |
|-------------|---------|-------------|--------|
| `economic_control_v1` | Fund sponsor / voting authority. Rolls fund series to brand parent (who owns the fund, votes the shares). | N-CEN primary adviser, ADV Schedule A wholly_owned, parent_bridge sync, orphan_scan | Live since 2026-04-09 (Phase 4 cutover) |
| `decision_maker_v1` | Entity making active investment decisions. Routes actively managed sub-advised funds to the sub-adviser. Passive funds copy `economic_control_v1`. | N-CEN sub-adviser relationships (2,389 routings), with intra-firm collapse | Live since 2026-04-10 |

**decision_maker_v1 details:**
- 2,389 N-CEN sub-adviser routings applied (rule: `ncen_sub_adviser`)
- 2,371 produce a different rollup than `economic_control_v1`
- **DM8 intra-firm fix (2026-04-10)**: 621 routings collapsed back to brand parent where sub-adviser is a wholly-owned subsidiary of the primary adviser (Fidelity HK/UK → Fidelity, DFA Australia → Dimensional, BlackRock Singapore → BlackRock, T. Rowe Price International → T. Rowe Price)
  - 485 via shared `economic_control_v1` rollup
  - 17 via `entity_relationships` parent links
  - 119 via name-based brand matching
- **DM13 BlueCove sweep (2026-04-16, `ef3f302`)**: 20 `sub_adviser` false-match relationships closed, 17 DM rollups retargeted to correct EC parents ($235B+ Strategic Advisers Fidelity funds moved back to FMR LLC; Boston Partners / Matson Money / Altair retargeted), 15 sub-adviser parents classified unknown→active. 35 `entity_overrides_persistent` rows written. Broader 410-row non-BlueCove false-match audit still pending.
- **DM14 Layer 1 (2026-04-16, `d684e4e`)**: 8 additional intra-firm collapses via bilateral `wholly_owned` / `parent_brand` chain walk (extending DM8 beyond the shared-EC case). Retargets: 4 AMG Yacktman + 1 AMG Frontier ($9.65B) → AMG; 2 Vaughan Nelson ($2.50B) → Natixis IM; 1 Calvert EM ($0.01B) → MORGAN STANLEY. Rule applied: `manual_override`. $12.15B AUM total.
- **DM14b (pending)**: 7 bigger ROADMAP-named candidates (Manulife IM / FIAM / Principal RE / Voya / Davis / PGIM Ltd / Cohen & Steers Asia) blocked on missing `wholly_owned` / `parent_brand` edges in the graph — ~$170B AUM, 123 funds. Per-entity ADV corroboration required before edges land. Once added, DM14 Layer 1 chain walk picks them up automatically. See ROADMAP.md row DM14b.
- Top cross-firm routings visible: BlueCove-cleared funds now back to FMR ($235B+), GQG Partners ($107B from Goldman), Franklin Advisers ($83B from Putnam), T. Rowe Price ($88B from Fidelity Strategic Advisers), Jennison ($58B from Harbor), Sands Capital ($52B from Bessemer), Wellington ($36B from Hartford)

**Global UI toggle** in app header selects between "Fund Sponsor / Voting" (`economic_control_v1`, default) and "Decision Maker" (`decision_maker_v1`). Toggle propagates via `?rollup_type=` query param to all 20+ parameterized query functions.

**voting_control_v1** was designed but closed 2026-04-10 — `economic_control_v1` serves as voting proxy (fund sponsor votes shares in >95% of cases). UI label "Fund Sponsor / Voting" makes this explicit.

**Pending (deferred parser work):**
- **D12** — ADV Section 7.B sub-adviser extraction from existing PDF cache (not in current parse)
- **D13** — N-PORT XML sub-adviser metadata extraction (not in current fetch)

Future worldviews (`regulatory_parent_v1`, `brand_parent_v1`) can coexist via this field without schema changes.

### Rollup Policy — Operating Asset Manager Rule
**Rollup targets must be operating asset managers only.** The rollup chain stops at the top-level entity that actually manages money and files 13F/N-PORT.

Non-operating ownership entities stay in the relationship graph as informational records but **never drive rollup**:
- **PE firms** (TA Associates, Bain Capital) — own managers through fund structures, not as operators
- **Insurance companies** (Pacific Life, MassMutual) — own subsidiaries but the subsidiary is the operating manager
- **Foundations** (Stowers Institute) — endowment ownership, not asset management
- **Holding companies** (Stonegate, International Assets Advisory) — financial holding, not operating
- **VC firms** (F-Prime, DAG Ventures) — fund-level ownership

**Examples:**
- American Century self-rollups (not → Stowers Institute foundation)
- Russell Investments self-rollups (not → TA Associates PE fund)
- Pacific Life Fund Advisors self-rollups (not → Pacific Life Insurance Company)
- Envestnet self-rollups (not → Bain Capital Fund XIII)

**What drives rollup:**
- `fund_sponsor` — fund series → operating adviser (from N-CEN)
- `wholly_owned` — subsidiary manager → parent manager (from ADV Schedule A)
- `orphan_scan` — duplicate entities consolidated by name similarity

### Classification Categories

`entity_classification_history.classification` — 15 active values (as of 2026-04-10, post-Section 3 L4 audit). No DB-level CHECK constraint; values enforced by `build_entities.py` and `validate_entities.py`.

| Classification | Definition | Top examples |
|---|---|---|
| `passive` | Pure index/ETF providers — fund or index issuers whose AUM is dominated by passive vehicles | Vanguard, BlackRock, State Street/SSGA, Geode, Northern Trust |
| `active` | Active asset managers — discretionary security selection across mutual funds, separate accounts, or institutional mandates | Fidelity/FMR, Morgan Stanley IM, Capital Group (World/International), Wellington Management, T. Rowe Price |
| `mixed` | Diversified financial holding companies filing 13F at the consolidated holdco level — blend of asset management, brokerage, prop trading, treasury, and (where applicable) market making | JPMorgan Chase, Bank of America, Goldman Sachs Group, UBS, RBC, BNY Mellon Corp, Wells Fargo, Barclays, Deutsche Bank, BMO, Citigroup, BNP Paribas |
| `hedge_fund` | Discretionary or fundamental hedge fund managers — distinct from systematic market makers below | Citadel Advisors, Bridgewater, Millennium, D.E. Shaw, Renaissance Tech, Two Sigma Investments, Elliott |
| `market_maker` | **Systematic liquidity providers — market makers, HFT firms, electronic trading firms. Structurally distinct from hedge funds and quantitative managers because reported AUM is dominated by inventory hedging rather than directional positioning. Zero N-PORT series by definition.** Added 2026-04-10 (Section 3 L4 audit). | Jane Street, Susquehanna International Group, Citadel Securities, Virtu Financial, IMC Financial Markets, Optiver, CTC Trading Group, Hudson River Trading, Two Sigma Securities, Flow Traders, DRW Securities |
| `quantitative` | Systematic quant managers — factor-based, statistical arbitrage, model-driven discretionary | DFA, AQR, Two Sigma Investments, Acadian, Renaissance Tech (some sleeves) |
| `wealth_management` | Independent broker-dealers, wirehouses, RIA aggregators, and platform wealth management firms | LPL Financial, Raymond James, PNC, Jones Financial, Northwestern Mutual Wealth, Edward Jones |
| `pension_insurance` | Pension funds and insurance company general accounts that file 13F directly | CalPERS, Norges Bank, NYS Common Retirement, MetLife, Prudential, Pacific Life Insurance Company |
| `endowment_foundation` | University endowments, hospital systems, charitable foundations, and other non-profit investment offices | Yale, Harvard, Stanford, Stowers Institute for Medical Research |
| `strategic` | Corporate strategics filing 13F for treasury, balance-sheet, or family-office investment purposes — distinct from operating asset managers | Berkshire Hathaway, NVIDIA, Markel, Loews, Exor (Agnelli), Glencore, Amazon, Alphabet, Briar Hall, Hancock Prospecting |
| `private_equity` | PE firms that file 13F for public equity sleeves of their funds | Brookfield Corp, Carlyle Group, Thoma Bravo, BC Partners, KKR |
| `venture_capital` | VC firms with public-equity exposure (post-IPO holdings, growth-stage public investments) | Sequoia Capital US (SC US/E), Greylock, Lightspeed, a16z Perennial |
| `activist` | Activist investors — concentrated positions taken to influence target company strategy. Always paired with `is_activist=TRUE` | Elliott (also hedge_fund-tagged in some contexts), Mantle Ridge, Trian Fund Management, JANA Partners |
| `SWF` | Sovereign wealth funds | Norges Bank Investment Management, Temasek, GIC, Public Sector Pension Investment Board |
| `unknown` | Default for entities with no resolvable signal — typically non-13F-filer entities encountered via N-CEN/managers feeds for graph completeness only. Zero AUM contribution. | (3,539 entities, all $0 AUM) |

**`is_activist` boolean:** Independent of `classification`. Set to `TRUE` only when the entity is in fact an activist; classification stays as the entity's primary type. Most activists are also `hedge_fund` or `activist` classified, but the flag is the source of truth for activist filtering.

**Singleton categories removed 2026-04-10 (Section 3 L4 audit):**
- `insurance` (1 entity, Pacific Life Insurance Company) → merged into `pension_insurance`
- `foundation` (1 entity, Stowers Institute for Medical Research) → merged into `endowment_foundation`
- `holding_company` (2 entities) → split: Stonegate Global Financial → `strategic` (interim placeholder, flagged as DM15 candidate); International Assets Advisory LLC → `wealth_management` (independent broker-dealer/RIA platform)

---

## Implementation Phases

### Phase 1 — Build and Seed ✅ COMPLETE
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

### Phase 3.5 — Form ADV Schedules A/B ✅ COMPLETE
**Scope:** Parse ADV Schedule A (Direct Owners) and B (Indirect Owners). Populate entity_relationships with wholly_owned and parent_brand types. Handle JV and multi-adviser structures.
**Data source:** ADV PDFs from `reports.adviserinfo.sec.gov/reports/ADV/{crd}/PDF/{crd}.pdf` (IAPD API returns 403; XML feed lacks schedules; PDFs are accessible).
**Ownership code mapping:** E/D (≥50%) → wholly_owned, C (25-50%) → parent_brand, NA on entities → mutual_structure (Vanguard pattern), A/B (<25%) → skip.

**Results (Apr 8 2026):**
- 3,585 of 3,652 CRDs parsed (98.2%), 26,822 rows in `adv_schedules.csv`
- 13,541 total active relationships in DB
- 20,205 total entities (12 new parent entities created)
- 825 JV structures identified
- 858 N-PORT orphan fund series wired to parent advisers (920 → 62, 99.3% coverage)
- 174 orphan subsidiaries consolidated via name similarity scan
- All multi-level rollup chains flattened (every entity points directly to ultimate parent)
- 23 circular rollup pairs broken (duplicate entities like Vanguard Group ↔ Vanguard Group Inc)
- 1,926 unresolved CRDs triaged: 99 wired to parents, 1,827 confirmed independent
- Rollup policy enforced: only operating asset managers as rollup targets
- Classification sync: 974 unknowns classified from ADV strategy, 204 corrections validated
- D1 accuracy audit: 90 PDFs, 6 strata, zero false positives, 75% parser agreement
- SCD integrity: 0 broken, 0 duplicate rollups, 0 circular references, 0 multi-level chains
- Staging queue: 0 pending (3,503 informational entries auto-resolved)

**Dual-parser architecture:**
- **pymupdf** (primary): `parse_adv_pdf_pymupdf()` — 100-400x faster than pdfplumber, no size limit. 88.3% recall vs pdfplumber, 99.5% code accuracy, +1,151 net entity gain. Handles all oversized PDFs (PIMCO 45MB in 20s).
- **pdfplumber** (fallback): `parse_adv_pdf()` — retained as legacy parser for CRDs where pymupdf finds 0 entity owners (~5% gap). Higher recall on some text layouts.
- **`--refresh` mode**: runs pymupdf on all targets (4 workers, ~20 min), then pdfplumber fallback on gaps, then match. Standard workflow for updates.

**Quality control:**
- `--qc` report: 1,659 CRDs with ≥1 entity owner, 1,926 with 0 (mostly individual-only firms)
- `logs/phase35_qc_report.csv`: all CRDs with issues for review
- `data/reference/adv_entity_review.html`: interactive review tool (1,926 items, 20,416 searchable aliases, pre-populated recommendations)
- `data/reference/adv_manual_adds.csv`: manual entity additions, auto-loaded during `--refresh`

**Deliverables:**
- `entity_sync.py`: `parse_adv_pdf()`, `parse_adv_pdf_pymupdf()`, `insert_adv_ownership()`, `build_alias_cache()`, `_AliasCache`
- `resolve_adv_ownership.py`: full pipeline with `--download-only`, `--parse-only`, `--match-only`, `--oversized`, `--refresh`, `--qc`, `--manual-add`
- `entity_overrides_persistent` table + replay in `build_entities.py --reset`
- `mutual_structure` relationship type + `mutual` control type in schema
- `entity_identifiers_staging_review` deduplicated view
- Evidence resolution policy: ADV supersedes legacy sources at score ≥90

**Operational safeguards:**

| Safeguard | How it works |
|-----------|-------------|
| **No DB lock during parse** | `--parse-only` opens DB briefly to read target CRDs, then closes. Parse reads local PDFs + writes CSV only. |
| **Checkpoint file** | `data/cache/adv_parsed.txt` — append-only, one CRD per line after every PDF (success/error/timeout). Survives crashes. |
| **Partitioned parallel** | 4 independent worker processes, each with own temp CSV. Workers never block each other. |
| **SIGALRM timeout** | 180s default. Clean per-PDF timeout in each worker process. |
| **SIGTERM handler** | Workers flush CSV and exit cleanly on kill signal. |
| **Memory-safe** | pdfplumber: context manager + page.close() + gc.collect() (300 MB/worker). pymupdf: no leak. |
| **Crash recovery** | Leftover temp CSVs merged on restart. Checkpoint prevents re-parsing. |
| **PDF validation** | `%PDF` header check on download and before parse. Invalid files logged to `phase35_failed_crds.csv`. |
| **Atomic SCD** | `begin()/commit()` around all rollup close+open pairs with self-heal on rerun. |
| **Deterministic matching** | Score DESC → entity_id ASC tiebreaker. All alias queries ORDER BY entity_id, alias_name. |
| **Firm identity verification** | `verify_firm_identity()` checks city, state, legal name from adv_managers before wiring name-similar entities. Prevents false merges (e.g., two "Capstone Wealth Management" firms in different states). |
| **Name normalization** | `_normalize_entity_name()` standardizes Corp/Corporation, Inc/Incorporated, Co/Company, Ltd/Limited before fuzzy matching. Eliminates suffix-only mismatches. |

**Validation rules for entity linking:**
1. **Name similarity alone is insufficient** — firms with score ≥85 but different states/cities are NOT wired
2. **Same legal name + same state** → confirmed same firm, auto-wire
3. **Same city + same state** → likely same firm, auto-wire
4. **Different states** → different firms regardless of name score, skip
5. **IAPD API blocked (403)** — use local adv_managers data for city/state/legal name verification
6. **DBA/legal name mismatch** — firm_name ≠ legal_name (score <80) signals holding company or DBA structure. Flagged in `--qc` report and `logs/phase35_legal_name_review.csv`. Example: ETF Architect (firm) = Empowered Funds LLC (legal), Brown Advisory = Signature Financial Management Inc.
7. **Manual review items** export to `adv_manual_adds.csv` via interactive HTML tool

**Update workflow:**
```bash
# Full refresh (standard for updates)
python3 scripts/resolve_adv_ownership.py --refresh --staging --all

# Manual review
open data/reference/adv_entity_review.html  # review in browser, export CSV
# Place exported CSV at data/reference/adv_manual_adds.csv
python3 scripts/resolve_adv_ownership.py --refresh --staging --all  # picks up manual adds

# Quality check
python3 scripts/resolve_adv_ownership.py --qc --staging
```

### Phase 4 — Migration ✅ STAGE 4 COMPLETE (cutover 2026-04-09)
**Scope:** Migrate holdings, fund_holdings, beneficial_ownership to use entity_id FK.
**Migration approach:** New data primary, old data shadow. App switched to entity-backed v2 tables.

**Pre-conditions (all complete):**
1. ~~Validation gate failures resolved~~ ✅ Done — 10 phantom PARENT_SEEDS merged into real CIK filers ($16.2T corrected), rollup chains flattened, circles broken. Gate thresholds updated: 0 FAILs, 8 PASS, 7 MANUAL (all documented).
2. ~~N15 — Fidelity international sub-adviser deduplication~~ ✅ Done — series-level dedup verified in all 4 N-PORT rollup queries. Geode exclusion active. 174 shared series correctly handled. ~116% ratio is structural (monthly MAX vs quarter-end). No code changes needed.
3. ~~R1/R2/R3 — 13D/G data quality audit~~ ✅ Done — 51,905 rows, pct_null=0, shares_null=1, duplicates=0. Started at 96% pct null / 16.5% shares null. 8,227 duplicates removed, 20,000+ agent names resolved, 1,287 exits validated, 928 suspects rescanned, parser hardened in all 3 scripts. DATA QUALITY: CLEAN. See PRE_PHASE4_STATUS.md Item 6.
4. ~~Item 43 — app.py lint debt fix~~ ✅ Done — flake8 0 issues, bandit 0 high/B608. Pre-commit unblocked.
5. ~~N21 TODOs a/b/c — investor type classification~~ ✅ Done — 14 categories, 8,639 managers, $67.3T, 0 NULL. ALL categories reviewed 1-by-1 with confidence scoring. 177 LOW>$10B manually fixed. Pension/insurance separated from passive ($1.4T moved). Activist expanded to 31 per industry reference. Fund-level: 5,717 series via S&P500 + 8-index correlation.

**Stages completed:**
1. ✅ Entity tables copied to production, holdings_v2/fund_holdings_v2/beneficial_ownership_v2 created with entity_id FK, 100% entity coverage, 100% rollup coverage
2. ✅ App switched to v2 tables — all 34 query functions updated, COALESCE(rollup_name, inst_parent_name) pattern, shadow logging on 5 key endpoints
3. ✅ Parity validation — 8/8 gates pass: row_count exact, entity/rollup coverage 100%, total AUM 0.00% diff, top 50 entity AUM 0.00% diff, 10/10 known merges, shadow log clean
4. ✅ Cutover authorized 2026-04-09 — app running cleanly on v2 tables, zero 500 errors, shadow log shows only expected discrepancies (new_gain, legacy_only name changes, value_diff consolidation)
5. ✅ Stage 5 cleanup — legacy `holdings`, `fund_holdings`, `beneficial_ownership` tables dropped 2026-04-13 from both prod and staging DBs after `EXPORT DATABASE` backup, zero code references confirmed via grep, validate_entities.py 9 PASS / 0 FAIL / 7 MANUAL unchanged. Holdings_v2/fund_holdings_v2/beneficial_ownership_v2 are the canonical fact tables.

**Batch 3 (2026-04-16) — Group 3 enrichment + L4 rebuild path live.** With Stage 5 complete, the Batch 3 trio (`enrich_holdings.py` + `compute_flows.py` rewrite + `build_summaries.py` rewrite + migration 004) closes the entity-MDM-driven rebuild path: every L4 derived table now reads from `holdings_v2` / `fund_holdings_v2` and writes both rollup worldviews. See `docs/data_layers.md` for the per-table state.

**Rollup wiring fixes applied during migration:**
- Northern Trust (eid=4435), Wellington (eid=11220), Franklin (eid=4805), Dimensional (eid=5026), Ameriprise (eid=10178), First Trust (eid=136) — corrected from subsidiary-rollup to self-rollup
- Display names updated: ALL CAPS legal names → curated proper-case display names for top 25 parents

**Rollback:** Original holdings, fund_holdings, beneficial_ownership tables untouched. Instant rollback by reverting queries.py to pre-Stage 2 commit.

---

## Operational Procedures

_Effective: April 10, 2026_

All entity changes — fixes, audits, pipeline updates, maintenance — go through
staging before production. No exceptions.

### Standard workflow for every entity change session

1. **SYNC**     — `python3 scripts/sync_staging.py`
2. **WORK**     — apply all changes in `data/13f_staging.duckdb` only
3. **VALIDATE** — `python3 scripts/validate_entities.py --staging`
4. **DIFF**     — `python3 scripts/diff_staging.py`
5. **REVIEW**   — review diff in conversation before proceeding
6. **APPROVE**  — explicit authorization required
7. **PROMOTE**  — `python3 scripts/promote_staging.py --approved`
8. **VERIFY**   — `python3 scripts/validate_entities.py`  *(default = production)*
9. **COMMIT**   — git commit with session summary

### What goes through staging (mandatory)

- All entity relationship changes (entity_relationships)
- All classification changes (entity_classification_history)
- All sub-adviser routing changes (DM12, DM13, DM14, DM15)
- All rollup corrections (entity_rollup_history)
- All `build_entities.py` runs
- All ADV / N-CEN / pipeline updates that touch entity tables
- All audit fix batches (L4, L5, any future layers)
- Manual entity overrides (entity_overrides_persistent)

### What does NOT need staging

- `holdings_v2`, `fund_holdings_v2` backfill — derives from entity tables, re-stamped after promotion
- Market data, price data, 13F position data
- Non-entity pipeline tables (beneficial_ownership, fetched_tickers_13dg, market_data, etc.)
  → these go through `merge_staging.py` (separate workflow)

### Validation gate exit codes

`validate_entities.py` distinguishes failure severity:

| Exit | Meaning | promote_staging.py behavior |
|------|---------|----------------------------|
| `0` | All gates green | promotion proceeds |
| `1` | Non-structural FAIL (e.g. wellington_sub_advisory) | promotion proceeds; printed for review |
| `2` | Structural FAIL (PK / FK / orphan) | **auto-rollback to snapshot** |

### Rollback options

- **Promotion snapshot** (intra-DB tables in production, automatic):
  `python3 scripts/rollback_promotion.py --restore SNAPSHOT_ID`
- **Full DB restore** from EXPORT DATABASE backup (manual, see backup protocol below):
  ```
  python3 scripts/backup_db.py --list
  # then duckdb data/13f.duckdb -c "IMPORT DATABASE 'data/backups/...'"
  ```
- **SCD Type 2 history** — query entity tables at any historical `valid_from` for point-in-time view (not a rollback, but proves what was true when)

### Backup protocol

`backup_db.py` runs **manually**, never on a schedule. Every invocation
prompts for confirmation before doing anything (EXPORT DATABASE scans
the entire DB and writes ~3 GB of parquet — not something you want
triggered by accident). Pass `--no-confirm` to bypass the prompt for
scripted / automated runs.

When to back up:

- Before any DM13 / DM14 / DM15 audit pass
- Before Stage 5 cleanup (on or after 2026-05-09)
- Before any non-routine entity migration
- At analyst discretion before risky manual edits

Backups are NOT part of the monthly maintenance checklist — promotion
snapshots taken automatically by `promote_staging.py` already cover
day-to-day rollback needs. Full backups are reserved for known-risky
sessions where the snapshot mechanism alone isn't enough insurance.

### Monthly maintenance checklist

- `python3 scripts/validate_entities.py` — production health check (expect 1 non-structural FAIL on `wellington_sub_advisory` until INF3 lands)
- Review `manual_routing_review` gate output for overdue routings
- `python3 scripts/diff_staging.py` — confirm staging matches production at month boundary
- (Backups are NOT monthly — see Backup protocol above)

### Schema drift caveat (Apr 10 2026)

Production currently has a degraded schema relative to `entity_schema.sql`:
- `entities` and other tables were created without `PRIMARY KEY` / `NOT NULL` constraints
- `entity_overrides_persistent` exists in prod (**90 rows as of 2026-04-16** — 82 originals + 8 added by DM14 Layer 1; all `override_id`s now assigned post-INF22 heal: 58 NULL rows backfilled to 25-82 via `_heal_override_ids`, new rows at 83-90). Schema still has no DEFAULT / sequence on `override_id` — hotfix `_heal_override_ids` runs on every `promote_staging` invocation; migration 006 pending to add `DEFAULT nextval('override_id_seq')` at the schema level.
- Some `entity_identifiers` rows have NULL `confidence` despite the schema's `NOT NULL` declaration

`sync_staging.py` works around this by using `CREATE TABLE AS SELECT` to mirror production's column structure rather than re-applying `entity_schema.sql`. Staging therefore inherits the same constraint-free schema. Hardening the production schema is tracked separately and is out of scope for the staging framework.

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
| ~~D1~~ | ~~Labeled accuracy audit~~ ✅ | ~~Phase 3.5 post-run~~ | Completed Apr 8 2026. 90 PDFs sampled across 6 strata. 75% parser agreement on comparable files. Zero false positives. Pymupdf recall gap confined to Schedule B indirect owners. See `data/reference/adv_accuracy_audit.csv`. |
| D2 | pymupdf parser rewrite — 196x speed improvement, cuts full run from 4.7h to ~90min | Phase 3.5b | Requires rewriting table parser to use regex on pymupdf text output |
| D3 | Parse tail optimization — p95 parse time 158s | Phase 3.5b | Acceptable now, will matter at scale |
| D4 | Match quality benchmark — 209 unmatched rows scored 50-69, 39 scored 70-84 near threshold | Phase 3.5 post-run | Cannot trust ADV coverage rate as quality signal until benchmark done |
| D5 | IAPD API access — Schedule A/B via live API blocked (403) | Phase 3.5b | Resume when SEC opens API |
| D6 | ADV filing date tracking — current snapshots have no filing date context | Phase 4 | Important for point-in-time historical accuracy |
| ~~D7~~ | ~~Oversized PDF pass~~ ✅ | ~~Phase 3.5 post-run~~ | Completed Apr 8 2026. 112 PDFs parsed via pymupdf in 391s. 15,902 rows. Full 100% CRD coverage achieved. |
| D8 | Rollup worldviews — regulatory_parent, brand_parent | Phase 4+ | economic_control_v1 sufficient now |
| D9 | Recursive indirect ownership chains | Phase 4+ | Design supports via recursive CTE |
| D10 | Admin UI for entity_identifiers_staging review | Phase 3.5b | Defer until override volume exceeds 500 entries |
| D11 | Auto-promoter for high-confidence staging rows | Phase 3.5b | Promote rows score ≥95 with no conflicts automatically |

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

3. **~~Single rollup worldview~~** → **Two rollup worldviews live (2026-04-10)** — economic_control_v1 (fund sponsor / voting) and decision_maker_v1 (sub-adviser routing). Global UI toggle switches between them. Regulatory parent and brand parent views remain deferred. See "Rollup Types" section.

4. **~~5,000 long-tail filers~~ → 4,881 standalone after Phase 3** — of 5,328 originally unresolved CIKs, 153 matched to existing parents via fuzzy match, 104 reclassified via SIC codes. Remaining 4,881 are legitimate standalone filers (corporates, banks, insurance companies) correctly self-rolled. No further resolution expected without expanding PARENT_SEEDS or Phase 3.5 ADV parsing.

5. **Wellington / multi-family sub-advisory** — Wellington sub-advises Hartford, John Hancock, and other fund families. In Phase 1 Wellington appears as sub_adviser in those relationships (is_primary = FALSE). Full multi-parent modeling deferred to Phase 3.5.

---

## Files

| File | Purpose |
|------|---------|
| `scripts/entity_schema.sql` | Complete DDL for all tables, sequences, indexes, view, staging table |
| `scripts/entity_sync.py` | Shared feeder module — entity lookup, creation, conflict routing, ADV parsers (pdfplumber + pymupdf) |
| `scripts/build_entities.py` | Full rebuild population script (`--reset`, `--refresh-reference-tables`) |
| `scripts/validate_entities.py` | Validation gate runner (12 gates including Wellington) |
| `scripts/fetch_ncen.py` | N-CEN feeder — incremental entity sync via `--staging` flag (Phase 2) |
| `scripts/resolve_long_tail.py` | Phase 3 batch CIK resolver via SEC EDGAR (`--limit`, `--all`, `--dry-run`) |
| `scripts/resolve_adv_ownership.py` | Phase 3.5 ADV ownership resolver (`--refresh`, `--parse-only`, `--match-only`, `--oversized`, `--qc`, `--manual-add`) |
| `data/reference/adv_schedules.csv` | Parsed ADV Schedule A/B data (26,822 rows, 3,585 CRDs) |
| `data/reference/adv_manual_adds.csv` | Manual entity additions (auto-loaded during `--refresh`) |
| `data/reference/adv_entity_review.html` | Interactive review tool for unresolved CRDs (1,926 items, 20,416 searchable aliases) |
| `data/cache/adv_parsed.txt` | Checkpoint file — one CRD per line, append-only |
| `data/cache/adv_pdfs/` | Cached ADV PDFs (3,654 files, 8.4 GB, gitignored) |
| `logs/phase35_parse_progress.log` | Real-time parse progress (`tail -f`) |
| `logs/phase35_qc_report.csv` | QC issues (CRDs with 0 entity owners, missing codes) |
| `logs/phase35_legal_name_review.csv` | DBA/legal name mismatches — firms where firm_name ≠ legal_name (holding company signal) |
| `data/reference/adv_legal_name_review.csv` | Full legal name review (1,828 firms with match scores) |
| `logs/phase35_errors.csv` | Parse errors with timestamps and tracebacks |
| `logs/phase35_timed_out.csv` | PDFs that exceeded timeout |
| `logs/phase35_oversized.csv` | PDFs exceeding size limit |
| `logs/phase35_resolution_results.csv` | Match phase results |
| `logs/phase35_jv_entities.csv` | JV structures identified |
| `logs/phase35_unmatched_owners.csv` | Unmatched owners with best fuzzy scores |
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
| Apr 7 2026 | ADV evidence resolution policy: ADV supersedes legacy sources at score ≥90 | ADV Schedule A ownership data is authoritative (SEC filing). Legacy sources (parent_bridge from keyword matching, fuzzy_match from SEC name search) are heuristic. When ADV match score ≥90 and existing primary source is parent_bridge or fuzzy_match, ADV wins and replaces the existing primary. Existing wholly_owned from prior ADV run is kept. Score <90 keeps existing regardless. Policy logged as resolution_policy field on relationship. | Always keep existing — would let heuristic data block authoritative data. Always replace — would let low-confidence ADV matches override correct keyword matches. |
| Apr 7 2026 | Expanded match universe: all entity aliases, not just rollup parents | Original _AliasCache only loaded aliases of entities serving as rollup targets. This missed subsidiaries and entities that could serve as parents but hadn't been wired yet. Expanded to all entities with active aliases. Match count improved 12 → 87 (7.25x). HSBC, BNP Paribas, Federated Hermes all now match. | Restrict to rollup parents — missed valid matches because the parent hadn't been wired yet |
| Apr 7 2026 | Scan-based ownership code extraction in ADV parser | Fixed-position column extraction failed when pdfplumber inserted extra empty cells (Fayez Sarofim PDF). New approach scans remaining cells after jurisdiction for valid ownership code pattern (A-E, NA) instead of fixed offset. Zero missing ownership codes on entity rows. | Fixed-position extraction — fragile across PDF layouts |
| Apr 7 2026 | Deduplicated staging review view (entity_identifiers_staging_review) | Raw entity_identifiers_staging table preserved as full audit trail (316 rows). View deduplicates on (entity_id, identifier_type, identifier_value, review_status) keeping highest confidence + most recent. Reduces pending review from 316 to 280 items. All QA queries use view. | DELETE duplicates from table — destroys audit trail |
| Apr 8 2026 | Firm identity verification before wiring name-similar entities | `verify_firm_identity()` checks city, state, and legal name from adv_managers before wiring entities matched by name similarity. Caught 3 false positives in orphan scan: Capstone (PA vs OR), Compass Financial (SD vs FL), Cornerstone Wealth (MO vs OH, different legal names). Name similarity score alone is insufficient — many small RIAs share generic names. IAPD API blocked (403); local adv_managers data used instead. | Wire based on name score only — produces false merges between unrelated firms in different states |
| Apr 8 2026 | Entity name normalization for fuzzy matching | `_normalize_entity_name()` standardizes Corp/Corporation → CORP, Inc/Incorporated → INC, Co/Company → CO, Ltd/Limited → LTD before fuzzy matching. Eliminates suffix-only mismatches: BNY Mellon 83→100, Franklin Resources 83→97, MassMutual 93→100. Applied to both alias cache and query names. | Raw string matching — false mismatches on identical entities with different legal suffixes |
| Apr 8 2026 | Orphan subsidiary scan as standard pipeline step | Full-dataset scan of self-rollup entities against parent entities by name similarity + firm identity verification. Found 158 genuine orphans (same firm, different entity_ids from 13F vs N-CEN registration paths). Consolidated Dimensional ($836B), Lord Abbett ($270B), Thornburg ($45B), Sarofim ($35B) and 150+ others. | Manual discovery only — orphans accumulate silently as new entities enter via different feeders |
| Apr 8 2026 | N-PORT orphan series wiring via fund family name | 858 of 920 orphan fund series wired to parent advisers using fund_holdings.family_name → entity alias matching. Coverage 89.2% → 99.3%. Major consolidations: BlackRock/iShares (278), State Street/SPDR (80), Fidelity (67), Allspring (27), T. Rowe Price, BNY Mellon, DWS, and 30+ others. | Leave orphan series as independent — fragments parent-level ownership analysis |
| Apr 8 2026 | Circular rollup pair resolution | 23 circular pairs found where duplicate entities pointed at each other (Vanguard eid=1 ↔ Vanguard Group Inc eid=4375). Canonical parent chosen by child count. All circles broken, all multi-level chains flattened to one-hop. | Leave cycles — produces infinite loops in rollup queries |
| Apr 8 2026 | Operating Asset Manager rollup policy | Rollup targets must be operating asset managers only. PE funds, insurance companies, foundations, VC firms, and holding companies recorded in relationship graph but never drive rollup. American Century self-rollups (not → Stowers), Russell self-rollups (not → TA Associates), Pacific Life Fund Advisors self-rollups (not → Pacific Life Insurance). Ownership ≠ operational control for rollup purposes. | Roll up to ultimate owner — would attribute 13F holdings to PE funds and insurance companies that don't manage money |
| Apr 8 2026 | Classification sync from ADV strategy_inferred | 974 unknowns classified, 204 corrections validated. Misclassified PE fixed: Thrivent, Muzinich, Bridges → active. fund_sponsor control_type standardized to advisory. Staging queue cleared (3,503 informational entries rejected). | Leave classifications from Phase 1 only — misses ADV data that's already in the DB |
| Apr 10 2026 | routing_confidence + review_due_date on entity_rollup_history | Manual sub-adviser routings (umbrella trust fixes, name-based matches, orphan scans) need periodic review as fund sub-adviser relationships change over time. Three tiers: high (N-CEN/ADV/self-rollup — authoritative), medium (fuzzy match, name similarity, inferred), low (manual, manual_umbrella_trust). Annual review is forced via `validate_entities.py` manual_routing_review MANUAL gate when `review_due_date < CURRENT_DATE`. Staleness between N-CEN refreshes and manual overrides is logged by `fetch_ncen.check_routing_drift()` to `logs/ncen_routing_drift.log` so operators see when a manual routing contradicts the latest N-CEN filing. | Rely on one-time manual fixes without review cadence — routings silently go stale as advisers change sub-advisers |
| Apr 10 2026 | Pre-insert ADV verification (DM13 Phase 1) | ADV alias-cache fuzzy matches can silently bind a child entity to a similarly-named but unrelated parent (e.g., Securian Asset Management → Sterling Financial Group, $43.8B firm wired under a $16M Pasadena RIA). `entity_sync._verify_adv_relationship()` runs Tier 1 (parent ADV AUM ≥ 50% of child) and Tier 2 (state match) before insert; failures land in `entity_relationships_staging` with `conflict_reason='adv_ownership_verification_failed'` for operator review. Tiers 3-6 (EDGAR full-text, CRD cross-reference, OpenCorporates, web search) deferred to DM13 batch audit. | Trust the alias-cache score alone — produces silent false matches that propagate via `transitive_flatten` to child fund series and corrupt rollups under both economic_control_v1 and decision_maker_v1. |
| Apr 10 2026 | All entity changes go through staging (Operational Procedures) | Entity edits are high-stakes — a single bad UPDATE can poison rollups across millions of holdings rows and the rebuild path costs hours. Staging-first workflow gives the operator a chance to inspect the diff before changes touch production, an automatic intra-DB snapshot for fast rollback on validation failure, and a validate_entities.py exit-code contract (rc=2 structural FAIL → auto-rollback, rc=1 non-structural → human review, rc=0 clean) that distinguishes hard schema violations from transient gate noise. CTAS is used for the sync because production has a degraded constraint-free schema relative to entity_schema.sql; faithful mirroring beats schema strictness for the diff use case. Staging schema mismatch with prod is documented and accepted. | Edit production directly — every previous bad ADV match (Securian/Sterling, NYL/Millennium, Engaged/Harbor, etc.) would have been caught by the diff-review step. The cost of one extra command is far smaller than the cost of an undetected wrong rollup propagating through holdings_v2. |
