# Phase 4 — Entity Migration

Continue work on the 13f-ownership project. This is Phase 4 of the Entity MDM system.

## Read first
- `PHASE4_STATE.md` — current entity counts, coverage stats, canonical entity IDs, validation gate results
- `ENTITY_ARCHITECTURE.md` — Phase 4 section for migration stages and approach
- `ROADMAP.md` — full context on what's been done

## Context
- Items 1-9 (pre-Phase 4) are complete. All validation gates pass. Commit: `ee5e7cb`
- Entity tables exist in `data/13f_staging.duckdb` (20,205 entities, 29,023 identifiers, 13,715 relationships)
- Production tables in `data/13f.duckdb` (holdings 3.2M rows, fund_holdings 6.4M rows, beneficial_ownership 52K rows)
- 100% CIK coverage: all 9,121 CIKs in holdings have entity_id in entity_identifiers
- 100% series_id coverage: 8,547 entity_identifiers for 6,671 fund_holdings series

## Migration approach
**New data primary, old data shadow.** App switches to entity-backed tables immediately. Old tables kept as `_legacy` for 2-week validation, then dropped.

## What to do

**Stage 1 — Build entity-backed tables:**
1. Copy entity tables from staging → production DB
2. Add `entity_id` + `parent_entity_id` columns to `holdings`, backfill from `entity_identifiers` + `entity_rollup_history`
3. Add `entity_id` to `fund_holdings`, backfill from `entity_identifiers` (series_id → entity_id)
4. Add `entity_id` to `beneficial_ownership`, backfill from `entity_identifiers` (cik → entity_id)
5. Build indexes on new columns

**Stage 2 — Switch app to new data:**
1. Update `queries.py` — replace `inst_parent_name` string matching with `parent_entity_id` JOINs
2. Update `app.py` endpoints that reference parent rollup
3. Verify: top 10 tickers show same ownership totals with new vs old rollup

**Stage 3 — Shadow old tables:**
1. Rename original columns/tables with `_legacy` suffix where needed
2. Build comparison query: old rollup vs new rollup for validation
3. Log discrepancy report

## Key entity table JOINs
```sql
-- CIK → entity_id
entity_identifiers WHERE identifier_type = 'cik' AND valid_to = '9999-12-31'

-- entity_id → rollup parent
entity_rollup_history WHERE valid_to = '9999-12-31'

-- entity_id → preferred name
entity_aliases WHERE alias_type = 'preferred' AND valid_to = '9999-12-31'

-- series_id → entity_id  
entity_identifiers WHERE identifier_type = 'series_id' AND valid_to = '9999-12-31'
```

## Do not
- Do not start Phase 4 without reading PHASE4_STATE.md first
- Do not drop any tables — rename to `_legacy` only
- Do not modify entity tables in staging — copy to production first
- Follow `docs/PROCESS_RULES.md` for any batch operations
