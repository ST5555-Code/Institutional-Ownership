# cp-5-fh2-dm-rollup-drop — Migration Results

**Date:** 2026-05-05  
**PR:** #289  
**Branch:** `cp-5-fh2-dm-rollup-drop`  
**Source plan:** Bundle C §7.5 (Gap 2), chat decision 2026-05-05 (Path 1 — drop)

---

## 1. Motivation

`fund_holdings_v2.dm_rollup_entity_id` and `dm_rollup_name` were populated at
load time as a denormalized cache of the DM rollup. Recon (PR #288) found that
188K rows / 1.30% carried drift vs the canonical `entity_rollup_history` (ERH)
source; of those, 63% were confirmed STALE. An additional semantic defect was
found in the writer: `dm_rollup_name` was computed by joining `entity_aliases`
on the EC rollup entity instead of the DM rollup entity.

Chat decision 2026-05-05 chose Path 1 (drop both columns). Method A — read-time
ERH JOIN on `rollup_type='decision_maker_v1' AND valid_to=DATE '9999-12-31'` —
was already established as canonical by PR #280.

---

## 2. Schema Changes

Migration `024_drop_fh2_dm_rollup_denorm.py` executed against `data/13f.duckdb`
at 2026-05-05 14:22:47.

**DDL applied:**

```sql
-- DuckDB requires all indexes dropped before DROP COLUMN
DROP INDEX IF EXISTS idx_fhv2_entity;
DROP INDEX IF EXISTS idx_fhv2_rollup;
DROP INDEX IF EXISTS idx_fhv2_series;
DROP INDEX IF EXISTS idx_fh_v2_accession;
DROP INDEX IF EXISTS idx_fh_v2_latest;
DROP INDEX IF EXISTS idx_fund_holdings_v2_row_id;

ALTER TABLE fund_holdings_v2 DROP COLUMN dm_rollup_entity_id;
ALTER TABLE fund_holdings_v2 DROP COLUMN dm_rollup_name;

CREATE INDEX idx_fhv2_entity ON fund_holdings_v2(entity_id);
CREATE INDEX idx_fhv2_rollup ON fund_holdings_v2(rollup_entity_id, "quarter");
CREATE INDEX idx_fhv2_series ON fund_holdings_v2(series_id, "quarter");
CREATE INDEX idx_fh_v2_accession ON fund_holdings_v2(accession_number);
CREATE INDEX idx_fh_v2_latest ON fund_holdings_v2(is_latest, report_month);
CREATE UNIQUE INDEX idx_fund_holdings_v2_row_id ON fund_holdings_v2(row_id);
```

`schema_versions` stamp: `024_drop_fh2_dm_rollup_denorm` at 2026-05-05 14:22:47.

---

## 3. Reader Migrations (6 sites)

All 6 production reader sites migrated from Method B (direct column) to Method A
(ERH JOIN). Full change inventory in
`data/working/cp-5-fh2-dm-rollup-drop-migration-manifest.csv`.

| ID | File | Function / CTE | Change |
|----|------|----------------|--------|
| R1 | `scripts/queries/cross.py` | `_cross_ownership_query` — `fund_parents` CTE | `dm_rollup_name` SELECT → ERH JOIN → `entities.canonical_name` |
| R2 | `scripts/queries/cross.py` | `get_cross_ownership_fund_detail` | `dm_rollup_name = ?` → `EXISTS (ERH JOIN)` |
| R3 | `scripts/queries/cross.py` | `get_overlap_institution_detail` — `inst_funds` CTE | Same EXISTS pattern as R2 |
| R4 | `scripts/build_summaries.py` | `_build_summary_by_parent` / `_ROLLUP_SPECS` | 3-tuple spec; DM path uses ERH JOIN CTE for `nport_per_rollup` |
| R5 | `scripts/build_fixture.py` | `seed_sql` UNION | Deleted `dm_rollup_entity_id` branch from `fh_src`; `h_src` branch retained |
| R6 | `web/react-app/src/types/api.ts` | `CrossOwnershipInvestor` comment | Doc comment updated; no runtime change |

---

## 4. Writer Retirements (6 sites)

| ID | File | Function | Change |
|----|------|----------|--------|
| W1 | `scripts/pipeline/load_nport.py` | `_TARGET_TABLE_COLUMNS` + `_STG_TARGET_DDL` | Removed 2-column definitions from staging DDL |
| W2 | `scripts/pipeline/load_nport.py` | `_promote_append_is_latest` INSERT | Removed columns from INSERT list and `NULL AS …` SELECT |
| W3 | `scripts/pipeline/load_nport.py` | `_enrich_staging_entities` | Removed `dm` ERH JOIN, `ea` aliases JOIN, 3 SET clauses → 1 |
| W4 | `scripts/pipeline/load_nport.py` | `_bulk_enrich_run` | Same retirements as W3 (safety-net path) |
| W5 | `scripts/enrich_fund_holdings_v2.py` | `_LOOKUP_DDL` temp table | Removed `dm` + `ea` JOINs, 2 columns from SELECT |
| W6 | `scripts/enrich_fund_holdings_v2.py` | `_apply_batch` UPDATE | Removed 2 SET clauses |

---

## 5. Validation Guards

All 7 hard gates PASS.

| Gate | Check | Result |
|------|-------|--------|
| G1 | `dm_rollup_entity_id` ABSENT from `fund_holdings_v2` | PASS |
| G2 | `dm_rollup_name` ABSENT from `fund_holdings_v2` | PASS |
| G3 | Row count unchanged (14,569,125) | PASS |
| G4 | No `entity_id IS NULL` rows introduced (pre-existing 84,363 unchanged) | PASS |
| G5 | Method A sample non-null rate 100/100 | PASS |
| G6 | pytest 416/416 | PASS |
| G7 | React build clean (0 errors, 0 type errors) | PASS |

Indexes after migration (6 restored):  
`idx_fh_v2_accession`, `idx_fh_v2_latest`, `idx_fhv2_entity`, `idx_fhv2_rollup`,
`idx_fhv2_series`, `idx_fund_holdings_v2_row_id`

---

## 6. App Smoke Test

App restarted against `data/13f.duckdb` with worktree scripts. Three endpoints
exercised (MSFT / GOOGL, 2025Q4, BlackRock / iShares):

| Endpoint | Result |
|----------|--------|
| `GET /api/v1/cross_ownership?tickers=MSFT&quarter=2025Q4` | 25 investors returned; Method A name resolution confirmed |
| `GET /api/v1/cross_ownership_fund_detail?tickers=MSFT&quarter=2025Q4&anchor=MSFT&institution=BlackRock+%2F+iShares` | 5 funds returned (iShares Core S&P 500 ETF etc.) |
| `GET /api/v1/overlap_institution_detail?quarter=2025Q4&institution=BlackRock+%2F+iShares&subject=MSFT&second=GOOGL` | 5 overlapping / 5 ticker-a-only / 5 ticker-b-only funds |

No errors or 500s after switching to ERH-JOIN queries.

---

## 7. Peer-Rotation Smoke (Phase 4)

`scripts/compute_peer_rotation.py --test` ran without error. The script
references `holdings_v2.dm_rollup_name` (the sister table, not `fund_holdings_v2`),
so it is unaffected by this PR — confirmed by inline comment at line 88.

---

## 8. Out-of-Scope Notes

- Sister tables (`holdings_v2`, `holdings_v3`) retain their `dm_rollup_*`
  columns. Dropping them is a separate workstream.
- `data/13f_staging.duckdb` not migrated in this PR (staging is rebuilt from
  prod on demand).
- `dm_rollup_name` semantic defect (alias joined on EC entity, not DM entity)
  retired automatically with the column — no separate fix required.
