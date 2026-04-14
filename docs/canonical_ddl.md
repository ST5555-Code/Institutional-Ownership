# Canonical DDL Audit — L3 Drift Report

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_

For every L3 canonical table, this document compares prod DDL against
the owner script's INSERT/UPDATE column list. **A promote script for a
table with `DRIFT` / `MISSING_COLUMNS` / `SCHEMA_MISMATCH` / `BROKEN`
verdict cannot be written until the drift is resolved.**

## Summary table

| Table | Owner script | Verdict | Blocker? |
|-------|--------------|---------|----------|
| `holdings_v2` | `load_13f.py` (legacy `holdings`) + in-place Phase 4 migration | **BROKEN** | yes — owner writes to dropped `holdings` |
| `fund_holdings_v2` | `fetch_nport.py` | **BROKEN** | yes — owner writes to dropped `fund_holdings` and lacks 7 columns |
| `beneficial_ownership_v2` | `fetch_13dg.py` | **BROKEN** | yes — owner writes to dropped `beneficial_ownership` |
| `summary_by_parent` | `build_summaries.py` | **BROKEN + MISSING_COLUMNS** | yes — reads dropped `holdings`; DDL lacks 4 columns |
| `summary_by_ticker` | `build_summaries.py` | **BROKEN** | yes — reads dropped `holdings` |
| `filings` | `load_13f.py` | ALIGNED | no |
| `filings_deduped` | `load_13f.py` | ALIGNED | no |
| `raw_submissions` / `raw_infotable` / `raw_coverpage` | `load_13f.py` | ALIGNED | no |
| `securities` | `build_cusip.py` | ALIGNED | no |
| `market_data` | `fetch_market.py` | ALIGNED | no |
| `short_interest` | `fetch_finra_short.py` | ALIGNED | no |
| `fund_universe` | `fetch_nport.py` | ALIGNED | no |
| `adv_managers` | `fetch_adv.py` | ALIGNED | no |
| `ncen_adviser_map` | `fetch_ncen.py` | ALIGNED | no |
| `cik_crd_direct` / `cik_crd_links` | `fetch_adv.py` / `resolve_long_tail.py` | ALIGNED | no |
| `lei_reference` | `fetch_adv.py` | ALIGNED | no |
| `shares_outstanding_history` | `build_shares_history.py` | ALIGNED | no |
| `other_managers` | `load_13f.py` | ALIGNED | no |
| `parent_bridge` | `build_entities.py` legacy | ALIGNED | no (retained as evidence) |
| `fetched_tickers_13dg` / `listed_filings_13dg` | `fetch_13dg.py` | ALIGNED | no |
| `entities` + 5 SCD children + `entity_rollup_history` + `entity_overrides_persistent` | `build_entities.py` + `entity_sync.py` | ALIGNED | no |
| `managers` (L4) | `build_managers.py` | ALIGNED (CTAS) | no |
| `investor_flows` / `ticker_flow_stats` (L4) | `compute_flows.py` | ALIGNED (drop + create) | no |
| `data_freshness` (L0) | `db.record_freshness()` | ALIGNED | no |

Seven tables fail the gate; twenty are aligned. All seven failures
trace back to the Stage 5 legacy-table drops on 2026-04-13. Owner
scripts were never updated to write to the `_v2` successor tables.

---

## 1. `holdings_v2` — BROKEN

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

**Verdict:** BROKEN. No working owner script for `holdings_v2` exists
today. Stage 5 completed the table rename; the companion promote
rewrite was deferred — it is exactly the new `promote_13f.py` that the
framework calls for.

**Resolution:** Deliverable 11+ (write `promote_13f.py` as a
SourcePipeline implementation; Group 1+2 columns set at promote, Group 3
columns set by a separate `enrich_holdings.py` pass).

---

## 2. `fund_holdings_v2` — BROKEN

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

**Verdict:** BROKEN. `fetch_nport.py` will error on its next run because
its first write (`is_already_loaded()` at line 414) queries
`fund_holdings`, which no longer exists.

**Resolution:** Framework rewrite — split fetch_nport.py into
`discover_nport.py` (done in Deliverable 10) + `promote_nport.py` that
writes directly to `fund_holdings_v2` with entity + fund-strategy
columns populated at promote time per the `holdings_v2` Group 1+2
pattern.

---

## 3. `beneficial_ownership_v2` — BROKEN

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

**Verdict:** BROKEN. Next `fetch_13dg.py` invocation will fail at
`get_existing()` line 245 (`SELECT accession_number FROM beneficial_ownership`).

**Resolution:** Framework rewrite — `promote_13dg.py` writes to
`beneficial_ownership_v2` with `entity_id` resolved at promote time
(gate check against CIK).

---

## 4. `summary_by_parent` — BROKEN + MISSING_COLUMNS

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

**Verdict:** BROKEN (reads dropped `holdings`) + MISSING_COLUMNS (DDL
drift: 4 columns missing, PK differs).

**Resolution:** Migration script 002 (follow-on) updates
`build_summaries.py` to (a) read `holdings_v2` + `fund_holdings_v2`
with rollup-based aggregation (per the 2026-04-10 ROADMAP session
summary), (b) extend the CREATE TABLE IF NOT EXISTS to include all
4 missing columns with the new PK. D8 open-decision confirms migration
script pattern.

---

## 5. `summary_by_ticker` — BROKEN

**Prod DDL (12 columns):**
```
quarter, ticker, company_name, total_value, total_shares, holder_count,
active_value, passive_value, active_pct, pct_of_float, top10_holders,
updated_at, PRIMARY KEY (quarter, ticker)
```

**Owner-script DDL (`build_summaries.py:34`):** identical to prod — OK.

**Reads from:** `FROM holdings h` (line 73) — dropped Stage 5.

**Column diff:** none.

**Verdict:** BROKEN because source reads are on dropped tables, even
though DDL is ALIGNED.

**Resolution:** Swap source reads `holdings` → `holdings_v2`. Simple
retrofit, no schema migration needed.

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
- Promote scripts for tables marked BROKEN / MISSING_COLUMNS /
  SCHEMA_MISMATCH must not be written until the drift is resolved.
- All 5 broken L3/L4 tables (holdings_v2, fund_holdings_v2,
  beneficial_ownership_v2, summary_by_parent, summary_by_ticker) are
  downstream of Stage 5 cleanup — they share one root cause.
- The fix order is: (a) update `load_13f.py` + `fetch_nport.py` +
  `fetch_13dg.py` to write the `_v2` target directly; (b) add missing
  Group-2 entity columns at promote time via `entity_gate_check`;
  (c) extend `build_summaries.py` DDL to match prod's 13-column
  shape with the new PK and rollup-based source query; (d) migrate
  via `002_l3_owner_rewrite.py` once promote scripts are written.

None of this is done in this session — this document is the gate
artifact that blocks each such promote script from being written
without first resolving its row in the summary table above.
