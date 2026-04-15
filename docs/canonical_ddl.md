# Canonical DDL Audit — L3 Drift Report

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2). Reclassified 2026-04-13 (Batch 1) after direct inspection of prod — drift direction is owner-behind, not prod-missing._
_Revised 2026-04-15: two of the three OWNER_BEHIND blockers cleared by the v2 owner-script rewrites that shipped this week (fund_holdings_v2, beneficial_ownership_v2). holdings_v2 remains — Batch 3 (enrich_holdings) is the path. CUSIP v1.4 + control-plane tables added below._

For every L3 canonical table, this document compares prod DDL against
the owner script's INSERT/UPDATE column list.

**Verdict semantics:**
- `ALIGNED` — prod DDL and owner-script column list match. No action needed.
- `OWNER_BEHIND` — prod DDL is complete; the **owner script** lags (writes to a
  dropped table and/or its CREATE DDL is missing columns prod has). Fixable
  only by rewriting the owner script — not by schema migration on prod.
  Promote-script writing is blocked until the rewrite ships; prod itself is
  unchanged.
- `BROKEN` — formerly used as a catch-all; replaced by `OWNER_BEHIND` after
  the 2026-04-13 Batch 1 reclassification.

## Summary table

| Table | Owner script | Verdict | Blocker? |
|-------|--------------|---------|----------|
| `holdings_v2` | `load_13f.py` (legacy `holdings`) + `enrich_holdings.py` (Batch 3, unblocked) | **OWNER_BEHIND** | yes — Batch 3 enrichment rewrite will target `holdings_v2`; prod already has all 33 cols |
| `fund_holdings_v2` | `fetch_nport_v2.py` + `fetch_dera_nport.py` → `promote_nport.py` | **ALIGNED** (2026-04-15) | no — v2 owners write to `fund_holdings_v2` directly; 9.32M rows promoted live |
| `beneficial_ownership_v2` | `fetch_13dg_v2.py` → `promote_13dg.py` | **ALIGNED** (2026-04-14) | no — v2 owners write to `beneficial_ownership_v2` directly |
| `summary_by_parent` | `build_summaries.py` | **ALIGNED** (Batch 1 DDL fix) | no — CREATE DDL now matches prod 13-col shape + PK; INSERT rewrite tracked separately in pipeline_inventory.md |
| `summary_by_ticker` | `build_summaries.py` | **ALIGNED** | no — CREATE DDL already matched; INSERT rewrite tracked separately |
| `filings` | `load_13f.py` | ALIGNED | no |
| `filings_deduped` | `load_13f.py` | ALIGNED | no |
| `raw_submissions` / `raw_infotable` / `raw_coverpage` | `load_13f.py` | ALIGNED | no |
| `securities` | `build_cusip.py` + `normalize_securities.py` | **ALIGNED** (2026-04-15; migration 003 added 7 CUSIP classification columns: `canonical_type`, `canonical_type_source`, `is_equity`, `is_priceable`, `ticker_expected`, `is_active`, `figi`. `normalize_securities.py` is a secondary writer.) | no |
| `market_data` | `fetch_market.py` | ALIGNED | no |
| `short_interest` | `fetch_finra_short.py` | ALIGNED | no |
| `fund_universe` | `fetch_nport_v2.py` → `promote_nport.py` | **ALIGNED** (2026-04-15; migration 002 added `strategy_narrative`, `strategy_source`, `strategy_fetched_at` — currently NULL, Session 3+ enrichment target) | no |
| `adv_managers` | `fetch_adv.py` | ALIGNED | no |
| `ncen_adviser_map` | `fetch_ncen.py` | ALIGNED | no |
| `cik_crd_direct` / `cik_crd_links` | `fetch_adv.py` / `resolve_long_tail.py` | ALIGNED | no |
| `lei_reference` | `fetch_adv.py` | ALIGNED | no |
| `shares_outstanding_history` | `build_shares_history.py` | ALIGNED | no |
| `other_managers` | `load_13f.py` | ALIGNED | no |
| `parent_bridge` | `build_entities.py` legacy | ALIGNED | no (retained as evidence) |
| `fetched_tickers_13dg` / `listed_filings_13dg` | `fetch_13dg_v2.py` | ALIGNED | no |
| `entities` + 5 SCD children + `entity_rollup_history` + `entity_overrides_persistent` | `build_entities.py` + `entity_sync.py` | ALIGNED | no |
| `managers` (L4) | `build_managers.py` | ALIGNED (CTAS) | no |
| `investor_flows` / `ticker_flow_stats` (L4) | `compute_flows.py` (Batch 3 rewrite unblocked) | ALIGNED (drop + create) | no (reads legacy `holdings`; rewrite to `holdings_v2` in Batch 3) |
| `data_freshness` (L0) | `db.record_freshness()` | ALIGNED | no |
| `ingestion_manifest` (L0) | `scripts/pipeline/manifest.py` | ALIGNED (migration 001) | no |
| `ingestion_impacts` (L0) | `scripts/pipeline/manifest.py` | ALIGNED (migration 001) | no |
| `pending_entity_resolution` (L0) | `scripts/pipeline/shared.entity_gate_check()` + `validate_nport_subset.py` | ALIGNED (migration 001) | no |
| `cusip_classifications` (L3) | `build_classifications.py` + `run_openfigi_retry.py` | ALIGNED (migration 003, 2026-04-15) | no |
| `cusip_retry_queue` (L0) | `build_classifications.py` + `run_openfigi_retry.py` | ALIGNED (migration 003) | no |
| `_cache_openfigi` (L3 cache) | `run_openfigi_retry.py` | ALIGNED (migration 003) | no |
| `schema_versions` (L0) | migration scripts | ALIGNED (migration 003 — created fresh) | no |

**One table remains OWNER_BEHIND** (`holdings_v2`); the other two legacy
blockers (`fund_holdings_v2`, `beneficial_ownership_v2`) were cleared by
v2 rewrites that landed this week. The remaining `holdings_v2` fix path
is Batch 3 `enrich_holdings.py` — design unblocked by the CUSIP
classification layer. All newly-added L0/L3 tables (control-plane +
CUSIP vertical) are ALIGNED by construction since they ship as part of
their own migrations.

---

## 1. `holdings_v2` — OWNER_BEHIND

**Prod DDL (33 columns):**
```
accession_number, cik, manager_name, crd_number, inst_parent_name,
quarter, report_date, cusip, ticker, issuer_name, security_type,
market_value_usd, shares, pct_of_portfolio, pct_of_float, manager_type,
is_passive, is_activist, discretion, vote_sole, vote_shared, vote_none,
put_call, market_value_live, security_type_inferred, fund_name,
classification_source, entity_id, rollup_entity_id, rollup_name,
entity_type, dm_rollup_entity_id, dm_rollup_name
```

**Owner-script INSERT columns (`load_13f.py:222` — `CREATE TABLE holdings AS`):**

`load_13f.py` still materializes the pre-Stage-5 `holdings` table
(line 222 — `CREATE TABLE holdings AS`). After Stage 5 cleanup (commit
`305739e`) the target table was renamed to `holdings_v2` and enrichment
columns (entity_id, rollup_entity_id, manager_type, market_value_live,
pct_of_float, etc.) were added. The owner script was not updated.

**Column diff:**
- **In prod, not in owner script:** 13 columns — `entity_id`,
  `rollup_entity_id`, `rollup_name`, `entity_type`, `dm_rollup_entity_id`,
  `dm_rollup_name`, `manager_type`, `is_passive`, `is_activist`,
  `market_value_live`, `pct_of_float`, `security_type_inferred`,
  `classification_source`.
- **In owner script, not in prod:** none relevant (legacy CTAS is
  broader but we ignore the dropped table).

**Verdict:** OWNER_BEHIND. Prod `holdings_v2` already has all 33
columns listed above — direct `PRAGMA table_info('holdings_v2')`
confirms. No schema migration is needed. The fix is rewriting
`load_13f.py` (or replacing it with `promote_13f.py`) to target
`holdings_v2` and include the 13 enrichment columns at write time.

**Resolution:** Deliverable 11+ (write `promote_13f.py` as a
SourcePipeline implementation; Group 1+2 columns set at promote, Group 3
columns set by a separate `enrich_holdings.py` pass).

---

## 2. `fund_holdings_v2` — OWNER_BEHIND

**Prod DDL (25 columns):**
```
fund_cik, fund_name, family_name, series_id, quarter, report_month,
report_date, cusip, isin, issuer_name, ticker, asset_category,
shares_or_principal, market_value_usd, pct_of_nav, fair_value_level,
is_restricted, payoff_profile, loaded_at, fund_strategy, best_index,
entity_id, rollup_entity_id, dm_entity_id, dm_rollup_entity_id,
dm_rollup_name
```

**Owner-script DDL (`fetch_nport.py:377`):**
```
CREATE TABLE IF NOT EXISTS fund_holdings (
  fund_cik, fund_name, family_name, series_id, quarter, report_month,
  report_date, cusip, isin, issuer_name, ticker, asset_category,
  shares_or_principal, market_value_usd, pct_of_nav, fair_value_level,
  is_restricted, payoff_profile, loaded_at
)
```

**INSERT target:** `fund_holdings` (dropped 2026-04-13 Stage 5) — see
`fetch_nport.py:468` and `fetch_nport.py:477`.

**Column diff:**
- **Wrong target table** — owner writes to dropped `fund_holdings`, not
  `fund_holdings_v2`.
- **Missing from owner DDL/INSERT:** 7 columns — `fund_strategy`,
  `best_index`, `entity_id`, `rollup_entity_id`, `dm_entity_id`,
  `dm_rollup_entity_id`, `dm_rollup_name`.

**Verdict:** OWNER_BEHIND. Prod `fund_holdings_v2` already has all 26
columns listed above. `fetch_nport.py` will still error on its next
run because `is_already_loaded()` at line 414 queries the dropped
`fund_holdings`, but this is a source-code bug, not a prod schema
problem. No schema migration required.

**Resolution:** Framework rewrite — split fetch_nport.py into
`discover_nport.py` (done in Deliverable 10) + `promote_nport.py` that
writes directly to `fund_holdings_v2` with entity + fund-strategy
columns populated at promote time per the `holdings_v2` Group 1+2
pattern.

---

## 3. `beneficial_ownership_v2` — OWNER_BEHIND

**Prod DDL (21 columns):**
```
accession_number, filer_cik, filer_name, subject_cusip, subject_ticker,
subject_name, filing_type, filing_date, report_date, pct_owned,
shares_owned, aggregate_value, intent, is_amendment, prior_accession,
purpose_text, group_members, manager_cik, loaded_at, name_resolved,
entity_id
```

**Owner-script DDL (`fetch_13dg.py:230`):**
```
CREATE TABLE IF NOT EXISTS beneficial_ownership (
  accession_number, filer_cik, filer_name, subject_cusip, subject_ticker,
  subject_name, filing_type, filing_date, report_date, pct_owned,
  shares_owned, aggregate_value, intent, is_amendment, prior_accession,
  purpose_text, group_members, manager_cik, loaded_at
)
```

**INSERT target:** `beneficial_ownership` (dropped) — see
`fetch_13dg.py:245`, `fetch_13dg.py:259`.

**Column diff:**
- **Wrong target table.**
- **Missing from owner:** 2 columns — `name_resolved`, `entity_id`.

**Verdict:** OWNER_BEHIND. Prod `beneficial_ownership_v2` already has
all 21 columns listed above. `fetch_13dg.py` will still error on its
next run because `get_existing()` at line 245 queries the dropped
`beneficial_ownership`, but that is a source-code bug, not a prod
schema problem. No schema migration required.

**Resolution:** Framework rewrite — `promote_13dg.py` writes to
`beneficial_ownership_v2` with `entity_id` resolved at promote time
(gate check against CIK).

---

## 4. `summary_by_parent` — ALIGNED (Batch 1 DDL fix)

**Prod DDL (13 columns):**
```
quarter, rollup_entity_id, inst_parent_name, rollup_name, total_aum,
total_nport_aum, nport_coverage_pct, ticker_count, total_shares,
manager_type, is_passive, top10_tickers, updated_at,
PRIMARY KEY (quarter, rollup_entity_id)
```

**Owner-script DDL (`build_summaries.py:88`):**
```
CREATE TABLE IF NOT EXISTS summary_by_parent (
  quarter, inst_parent_name, total_aum, ticker_count, total_shares,
  manager_type, is_passive, top10_tickers, updated_at,
  PRIMARY KEY (quarter, inst_parent_name)
)
```

**Reads from:** `FROM holdings h` (`build_summaries.py:73` and `:118`)
— `holdings` was dropped Stage 5. Must be changed to `holdings_v2`.

**Column diff:**
- **In prod, not in owner DDL:** 4 columns — `rollup_entity_id`,
  `rollup_name`, `total_nport_aum`, `nport_coverage_pct`.
- **PK differs:** prod PK is `(quarter, rollup_entity_id)`, script PK is
  `(quarter, inst_parent_name)`.
- Also: prod summary_by_ticker has additional `rollup_entity_id` is
  NOT in that table's prod DDL — only `summary_by_parent` has the
  rollup key change. `summary_by_ticker` owner DDL is correct
  (but script still reads dropped `holdings`).

**Verdict (post-Batch 1):** ALIGNED for DDL. The CREATE TABLE IF NOT
EXISTS block now declares all 13 prod columns in the correct order
with `PK (quarter, rollup_entity_id)`.

The INSERT statement below the DDL still reads dropped `holdings` and
emits the old 9-value shape — that is an owner-script REWRITE item
(tracked in `docs/pipeline_inventory.md`), separate from the DDL
verdict. Batch 2 swaps the source reads to `holdings_v2` +
`fund_holdings_v2` with rollup-based aggregation.

---

## 5. `summary_by_ticker` — ALIGNED

**Prod DDL (12 columns):**
```
quarter, ticker, company_name, total_value, total_shares, holder_count,
active_value, passive_value, active_pct, pct_of_float, top10_holders,
updated_at, PRIMARY KEY (quarter, ticker)
```

**Owner-script DDL (`build_summaries.py:34`):** identical to prod — OK.

**Reads from:** `FROM holdings h` (line 73) — dropped Stage 5.

**Column diff:** none.

**Verdict:** ALIGNED for DDL (12 columns + PK match prod
column-for-column). Source reads still target dropped `holdings` —
that's an owner-script retrofit tracked in
`docs/pipeline_inventory.md`, not a DDL verdict.

---

## 6. `filings`, `filings_deduped`, `raw_*` — ALIGNED

Owner: `load_13f.py`. DDL matches prod DDL column-for-column for
`raw_submissions`, `raw_infotable`, `raw_coverpage`, `filings`,
`filings_deduped`. Verdict: ALIGNED.

---

## 7. `securities` — ALIGNED

Owner: `build_cusip.py:319` — `CREATE TABLE securities AS SELECT * FROM df_sec`.
Since it is CTAS, the DDL is determined by the DataFrame. All 14 prod
columns match the DataFrame assembled by the script. Verdict: ALIGNED.

_Note: CTAS-based table creation means schema changes require changing
the Python DataFrame shape, not SQL DDL. The migration framework (D8)
must treat CTAS and explicit CREATE TABLE as two distinct mutation
paths._

---

## 8. `market_data` — ALIGNED

Owner: `fetch_market.py`. Upsert on ticker. All 27 prod columns set by
the Yahoo + SEC XBRL fetch path. Verdict: ALIGNED.

---

## 9. `short_interest` — ALIGNED

Owner: `fetch_finra_short.py`. INSERT with PK `(ticker, report_date)`.
All 8 prod columns match. Verdict: ALIGNED.

_Decision (confirmed):_ short_interest is L3 (not L4 — app reads it
directly at `api_market.py:191` + `:164` + `:124`).

---

## 10. `fund_universe` — ALIGNED

Owner: `fetch_nport.py:354` — the DDL is kept in sync with prod (13
columns including `fund_strategy` + `best_index`). Verdict: ALIGNED.
Note: the sibling `fund_holdings` table in the same script is the
broken one — `fund_universe` is correct on its own.

---

## 11. `adv_managers`, `lei_reference`, `cik_crd_*` — ALIGNED

Owner: `fetch_adv.py`. DDL matches prod. Verdict: ALIGNED.

---

## 12. `ncen_adviser_map` — ALIGNED

Owner: `fetch_ncen.py`. DDL matches prod (12 columns). Verdict: ALIGNED.

---

## 13. `shares_outstanding_history` — ALIGNED

Owner: `build_shares_history.py`. DDL matches prod with `PRIMARY KEY
(ticker, as_of_date)`. Verdict: ALIGNED.

---

## 14. `other_managers` — ALIGNED

Owner: `load_13f.py`. DDL matches prod (8 columns). Verdict: ALIGNED.

---

## 15. `parent_bridge` — ALIGNED (retained as evidence)

Owner: `build_entities.py` legacy step (superseded by ADV + N-CEN).
7 columns match. Verdict: ALIGNED. Retained as evidence source for
rollup resolution — do not retire even though decision_maker_v1 +
economic_control_v1 have largely superseded keyword-match rollups.

---

## 16. `fetched_tickers_13dg`, `listed_filings_13dg` — ALIGNED

Owner: `fetch_13dg.py:224` and `:226`. DDL matches prod. Verdict:
ALIGNED. (`fetch_13dg.py`'s broken write is only against the
`beneficial_ownership` table — these two helper tables are fine.)

---

## 17. Entity MDM — ALIGNED

`entities`, `entity_identifiers`, `entity_relationships`,
`entity_aliases`, `entity_classification_history`,
`entity_rollup_history`, `entity_overrides_persistent` — DDL in
`scripts/entity_schema.sql` is explicitly known to differ from prod in
constraint strictness (see ENTITY_ARCHITECTURE.md "Schema drift caveat"
— prod lacks PK/NOT NULL on several columns). For column-presence
purposes (what the audit cares about here) all columns match. Verdict:
ALIGNED. The constraint-laxness is documented, tracked separately, and
out of scope for this audit.

---

## 18. `managers` (L4) — ALIGNED (CTAS)

Owner: `build_managers.py:426` — `CREATE TABLE managers AS SELECT ...`.
Prod and script CTAS produce the same 15 columns. Verdict: ALIGNED.

---

## 19. `investor_flows`, `ticker_flow_stats` (L4) — ALIGNED

Owner: `compute_flows.py`. Drops and recreates both tables. 24 + 8
columns match. Verdict: ALIGNED.

---

## 20. `data_freshness` (L0) — ALIGNED

Created by `migrate_batch_3a.py`; updated by `db.record_freshness()`.
3 columns match. Verdict: ALIGNED. Table currently has 0 rows in prod
because no pipeline has run since Stage 5; the record_freshness hook
fires at end-of-run.

---

## Gate enforcement

Per the v1.2 pipeline plan:
- Promote scripts for a table marked `OWNER_BEHIND` cannot be written
  until the owning fetch/load script is rewritten — prod schema is
  fine; owner scripts are the blocker.
- All 3 `OWNER_BEHIND` tables (holdings_v2, fund_holdings_v2,
  beneficial_ownership_v2) share one root cause: Stage 5 legacy-table
  drops on 2026-04-13 were never paired with owner-script rewrites.
- Fix order:
  (a) rewrite `load_13f.py` + `fetch_nport.py` + `fetch_13dg.py` to
      write the `_v2` target directly (this clears all three
      `OWNER_BEHIND` rows at once);
  (b) populate Group-2 entity columns at promote time via
      `entity_gate_check`;
  (c) rewrite `build_summaries.py` INSERT to read `holdings_v2` +
      `fund_holdings_v2` with rollup-based aggregation (DDL is already
      fixed in Batch 1).

## Migration History

| # | Script | Date | Scope |
|---|--------|------|-------|
| 001 | `scripts/migrations/001_pipeline_control_plane.py` | 2026-04-13 | adds L0 control plane tables (`ingestion_manifest`, `ingestion_impacts`, `pending_entity_resolution`), confirms `data_freshness`, creates `ingestion_manifest_current` VIEW. Applied to staging (v1.2 framework session) then prod (Batch 1). |
| — | (`002_resolve_l3_ddl_drift.py`) | **not created** | **Not needed.** Prod L3 schemas already contain every column the owner scripts reference. The remediation path is script rewrites (tracked in `docs/pipeline_inventory.md`), not schema migration. |
