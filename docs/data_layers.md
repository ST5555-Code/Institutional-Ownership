# Data Layers — Table Classification

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_
_Revised: 2026-04-15 — CUSIP v1.4 layer live (4 new tables + 7 new
`securities` columns); N-PORT DERA backfill live (`fund_holdings_v2`
6.39M → 9.32M, `fund_universe` 6,677 → 8,459, newest `report_date`
2026-01-31); control-plane tables live in prod; migration 002
(`fund_universe.strategy_*`) applied. Parallel 2026-04-14 workstream
(commit 831e5b4) wired `record_freshness` on 8 non-v2 scripts and
drafted `scripts/migrations/add_last_refreshed_at.py` (pending on
`entity_relationships`) — see `docs/NEXT_SESSION_CONTEXT.md` open-items
list._

This document is the single source of truth for how every table in the
prod DB is classified across the four-layer model. Each owning script
must stay within its assigned layer. A promote script for a table whose
DDL drifts from its owner-script INSERT is blocked until the drift is
resolved (see `docs/canonical_ddl.md`).

---

## 1. Layer definitions

**L0 — Control plane.** Pipeline machinery. Records what was fetched,
what passed validation, what got promoted, what is waiting on entity
resolution, and which migrations have been applied. Small, operational,
wall-clock-timestamped. Never contains analytical data.
_Tables: `ingestion_manifest`, `ingestion_impacts`,
`pending_entity_resolution`, `data_freshness`, `cusip_retry_queue`,
`schema_versions`._
_Pipeline writes here at every stage boundary._

**L1 — Raw.** Byte-level mirror of external source data — SEC filing
XML, FINRA CSV, Yahoo JSON — parsed into columns but otherwise
unmodified. Re-fetch is idempotent; a full re-parse must reproduce this
layer exactly. No joins, no enrichment.
_Tables: `raw_submissions`, `raw_infotable`, `raw_coverpage`, `filings`,
`filings_deduped`._

**L2 — Normalized.** Light shaping on top of raw: deduplicated, typed,
column-renamed. No cross-source joins, no entity resolution. A file that
passes L1 → L2 must be fully replayable from L1 without network access.
In practice this layer is narrow — most source pipelines skip it and
write directly to L3 staging because L2 and L3 for an accession share
keys 1:1.

**L3 — Canonical.** The authoritative fact tables the application reads.
Every row carries `entity_id` (and `rollup_entity_id` where applicable)
resolved through the entity MDM. Promote writes here are gate-protected
(see `scripts/pipeline/shared.entity_gate_check`) and go through
`staging_db → prod_db` via `sync → diff → promote`. L3 DDL changes
require a migration script; no ALTER TABLE at runtime.
_Tables: `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`,
`securities`, `market_data`, `short_interest`, `fund_universe`,
`shares_outstanding_history`, `adv_managers`, `ncen_adviser_map`,
`filings`, `filings_deduped`, `cusip_classifications`, `_cache_openfigi`,
and the full entity MDM (`entities`, `entity_identifiers`,
`entity_relationships`, `entity_aliases`,
`entity_classification_history`, `entity_rollup_history`,
`entity_overrides_persistent`)._

**L4 — Derived.** Rebuilt from L3 by deterministic compute scripts. No
external fetch. Fully regenerable. Missing an L4 table never blocks a
pipeline run — it blocks only the downstream app tab.
_Tables: `beneficial_ownership_current`, `summary_by_parent`,
`summary_by_ticker`, `investor_flows`, `ticker_flow_stats`,
`managers`, `benchmark_weights`, `fund_best_index`,
`fund_index_scores`, `fund_name_map`, `index_proxies`,
`fund_classes`, `peer_groups`, `fund_family_patterns`,
`entity_current` (VIEW)._

---

## 2. Complete table inventory

Every table returned by `SHOW TABLES` on prod (counts below as of
2026-04-15) is classified. Entity `_snapshot_*` rollback artifacts from
`promote_staging.py` and `entity_*_staging` tables are grouped at the
bottom.

| Table | Layer | Owner script | Promote strategy | Notes |
|-------|-------|--------------|------------------|-------|
| `raw_submissions` | L1 | `load_13f.py` | direct_write | 13F SUBMISSION.tsv mirror; 43,358 rows |
| `raw_infotable` | L1 | `load_13f.py` | direct_write | 13F INFOTABLE.tsv mirror; 13.5M rows |
| `raw_coverpage` | L1 | `load_13f.py` | direct_write | 13F COVERPAGE.tsv mirror; 43,358 rows |
| `filings` | L3 | `fetch_13dg.py` + `load_13f.py` | upsert on accession_number | 43,358 rows; mixed 13F + 13D/G accession metadata |
| `filings_deduped` | L3 | derived from `filings` | rebuild | 40,140 rows; dedup-on-accession view materialized as table |
| `holdings_v2` | L3 | `load_13f.py` → `enrich_holdings.py` (Batch 3, unblocked) | delete_insert on (quarter) | 12.27M rows; canonical 13F fact table |
| `fund_holdings_v2` | L3 | `fetch_nport_v2.py` + `fetch_dera_nport.py` → `promote_nport.py` | delete_insert on (series_id, report_month) | **9,315,568 rows** (2026-04-15); oldest 2024-10-31, newest 2026-01-31; DERA bulk path is primary |
| `beneficial_ownership_v2` | L3 | `fetch_13dg_v2.py` → `promote_13dg.py` | upsert on accession_number | 51,905 rows; canonical 13D/G fact table |
| `beneficial_ownership_current` | L4 | `promote_13dg.py` step 7 | rebuild | 24,753+ rows; latest-per-(filer_cik, subject_cusip) with amendment logic |
| `fund_universe` | L3 | `fetch_nport_v2.py` → `promote_nport.py` | upsert on series_id | **8,459 rows** (2026-04-15); now includes bond / index / MM funds via DERA path. Has `strategy_narrative`, `strategy_source`, `strategy_fetched_at` (migration 002; not yet populated) |
| `securities` | L3 | `build_cusip.py` + `normalize_securities.py` | upsert on cusip | **132,618 rows** (2026-04-15); 7 CUSIP-classification columns populated (`canonical_type`, `canonical_type_source`, `is_equity`, `is_priceable`, `ticker_expected`, `is_active`, `figi`) |
| `market_data` | L3 | `fetch_market.py` | upsert on ticker | 6,424 rows; latest price, market_cap, float, sector |
| `short_interest` | L3 | `fetch_finra_short.py` | upsert on (ticker, report_date) | 328,595 rows; daily FINRA short vol (app reads directly at `api_market.py:191`) |
| `shares_outstanding_history` | L3 | `build_shares_history.py` | upsert on (ticker, as_of_date) | 317,049 rows; SEC XBRL-sourced outstanding shares history |
| `adv_managers` | L3 | `fetch_adv.py` | upsert on crd | 16,606 rows; ADV Part 1 metadata per CRD |
| `ncen_adviser_map` | L3 | `fetch_ncen.py` | rebuild | 11,106 rows; series → primary/sub adviser CRD from N-CEN |
| `cik_crd_direct` | L3 | `fetch_adv.py` | rebuild | 4,059 rows; direct CIK↔CRD pairs from ADV filings |
| `cik_crd_links` | L3 | `resolve_long_tail.py` | rebuild | 448 rows; inferred CIK↔CRD links via SEC company search |
| `lei_reference` | L3 | `fetch_adv.py` | rebuild | 13,143 rows; GLEIF LEI → legal name reference |
| `other_managers` | L3 | `load_13f.py` | rebuild | 15,405 rows; other-manager references from 13F coverpage |
| `parent_bridge` | L3 | `build_entities.py` legacy | rebuild | 11,135 rows; legacy keyword-match parent bridge — retained as evidence source, superseded by ADV/N-CEN |
| `fetched_tickers_13dg` | L3 | `fetch_13dg.py` | upsert on ticker | 6,075 rows; ticker-level fetch progress marker |
| `listed_filings_13dg` | L3 | `fetch_13dg.py` | upsert on accession | 60,247 rows; EDGAR 13D/G accession index |
| `entities` | L3 | `build_entities.py` | staging→promote | 20,205 rows; entity MDM root |
| `entity_identifiers` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | 29,092 rows; CIK/CRD/SERIES_ID bridge |
| `entity_relationships` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | 13,685 rows; graph with `is_primary` parent flag |
| `entity_aliases` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | 20,541 rows; name variants with type + preferred |
| `entity_classification_history` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | 20,248 rows |
| `entity_rollup_history` | L3 | `build_entities.py` step 7 | staging→promote (SCD) | 46,854 rows; both rollup_type worldviews × 20,205 entities = ~40k, plus history |
| `entity_overrides_persistent` | L3 | manual via CSV / `entity_sync.py` | staging→promote | 47 rows; replayed on `build_entities.py --reset` |
| `entity_identifiers_staging` | L3 (staging-only) | `entity_sync.py` | staging_only | 3,503 rows; conflict soft-landing queue |
| `entity_relationships_staging` | L3 (staging-only) | `entity_sync.py` | staging_only | 0 rows (INF1 framework live) |
| `entity_current` | L4 (VIEW) | `entity_schema.sql` | rebuild (view) | VIEW over entity_identifiers JOIN entity_relationships JOIN entity_rollup_history — open rows only |
| `summary_by_parent` | L4 | `build_summaries.py` | rebuild per quarter | 8,417 rows; **DDL drift vs owner script — see canonical_ddl.md** |
| `summary_by_ticker` | L4 | `build_summaries.py` | rebuild per quarter | 24,570 rows |
| `investor_flows` | L4 | `compute_flows.py` | rebuild | 9.38M rows; set-based window-function rebuild |
| `ticker_flow_stats` | L4 | `compute_flows.py` | rebuild | 18,986 rows |
| `managers` | L4 | `build_managers.py` | rebuild | 12,005 rows; rebuilt from `entity_current` + `adv_managers` (decision D1 — keep, do not retire yet) |
| `fund_classes` | L4 | `build_fund_classes.py` | rebuild | 31,056 rows; fund class → series mapping |
| `fund_family_patterns` | L4 | `migrate_batch_3a.py` | seeded once, manual edits | 83 rows; N-PORT fund-family regex patterns (ARCH-3A) |
| `fund_best_index` | L4 | `build_fund_classes.py` step 2 | rebuild | 6,151 rows; best-fit index per series |
| `fund_index_scores` | L4 | `build_fund_classes.py` step 1 | rebuild | 80,271 rows; index correlation scores |
| `fund_name_map` | L4 | `build_fund_classes.py` | rebuild | 6.23M rows; fund-name → entity_id lookup (large because includes every N-PORT row) |
| `index_proxies` | L4 | `build_fund_classes.py` | rebuild | 13,641 rows |
| `benchmark_weights` | L4 | `build_benchmark_weights.py` | rebuild | 55 rows; per-quarter US-equity sector weights from Vanguard Total Stock Market |
| `peer_groups` | L4 | manual seed | rebuild | 27 rows; sector peer-group reference |
| `data_freshness` | L0 | every pipeline at end-of-run via `db.record_freshness()` — 8 non-v2 scripts wired in commit 831e5b4 (2026-04-14); v2 SourcePipelines stamp through their promote paths | upsert on table_name | 4 rows on prod (stamped by recent promotes); `scripts/check_freshness.py` is the gate + `make freshness` reads it |
| `ingestion_manifest` | L0 | `scripts/pipeline/manifest.py` | direct_write | **20,807 rows** — live since migration 001 (Batch 1). DERA_ZIP and per-accession keys for N-PORT |
| `ingestion_impacts` | L0 | `scripts/pipeline/manifest.py` | direct_write | **20,799 rows** — one per promoted `(series_id, report_month)` tuple plus per-quarter DERA ZIP impacts |
| `pending_entity_resolution` | L0 | `scripts/pipeline/shared.entity_gate_check()` + `validate_nport_subset.py` | direct_write | **5,924 rows** — 5,921 N-PORT series queued for MDM follow-up (bond / index / MM funds) + 3 from 13D/G |
| `cusip_classifications` | L3 | `build_classifications.py` + `run_openfigi_retry.py` | upsert on cusip | **132,618 rows** (migration 003, prod promoted 2026-04-15) — canonical_type, is_equity, is_priceable, ticker_expected, OpenFIGI metadata. Feeds `normalize_securities.py` |
| `cusip_retry_queue` | L0 | `build_classifications.py` + `run_openfigi_retry.py` | direct_write | **37,925 rows** — 15,807 resolved via OpenFIGI, 22,118 unmappable (private / delisted / exotic); status = pending \| resolved \| unmappable |
| `_cache_openfigi` | L3 (reference cache) | `run_openfigi_retry.py` | upsert on cusip | **15,807 rows** — full v3 response per CUSIP (figi, ticker, exchange, security_type, market_sector). Durable cache; survives re-runs |
| `schema_versions` | L0 | migration scripts (001, 002, 003) | direct_write | 1 row currently (003 stamped 2026-04-15); prior migrations not retroactively stamped |
| `positions` | **RETIRE** | `unify_positions.py` (RETIRE) | — | 18.68M rows; legacy combined-positions table. Decision D2: delete. No app reads confirmed (only `unify_positions.py` self-reads). Not retired this session — documented only. |
| `fund_classification` | **RETIRE** | `fix_fund_classification.py` (RETIRE) | — | 5,717 rows; superseded by `fund_best_index` + `fund_universe.best_index`. Decision: fold into `fund_universe`; only one script reads it — `fix_fund_classification.py` (itself RETIRE). |
| `entities_snapshot_*` (16 tables) | L3 rollback artifact | `promote_staging.py` | auto-created | Intra-DB promotion snapshots. Retention policy is **D7 (open decision)**. |
| `entity_aliases_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_classification_history_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_identifiers_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_identifiers_staging_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_overrides_persistent_snapshot_*` (6) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_relationships_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_relationships_staging_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_rollup_history_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |

**Unclassified — none.** Every prod table is assigned a layer.

---

## 3. Column ownership — `holdings_v2`

Prod DDL (2026-04-13):

```sql
CREATE TABLE holdings_v2(
    accession_number VARCHAR, cik VARCHAR, manager_name VARCHAR,
    crd_number VARCHAR, inst_parent_name VARCHAR, "quarter" VARCHAR,
    report_date VARCHAR, cusip VARCHAR, ticker VARCHAR, issuer_name VARCHAR,
    security_type VARCHAR, market_value_usd BIGINT, shares BIGINT,
    pct_of_portfolio DOUBLE, pct_of_float DOUBLE, manager_type VARCHAR,
    is_passive BOOLEAN, is_activist BOOLEAN, discretion VARCHAR,
    vote_sole BIGINT, vote_shared BIGINT, vote_none BIGINT,
    put_call VARCHAR, market_value_live DOUBLE,
    security_type_inferred VARCHAR, fund_name VARCHAR,
    classification_source VARCHAR, entity_id BIGINT,
    rollup_entity_id BIGINT, rollup_name VARCHAR, entity_type VARCHAR,
    dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR
);
```

### Group 1 — Core 13F facts (owner: `promote_13f.py` [proposed], NOT NULL)

Written at promote time, sourced directly from the SEC filing. These are
the irreducible facts that define a 13F holding.

- `accession_number` — SEC accession (PK component with cusip)
- `cik` — filer CIK (zero-padded 10-digit)
- `manager_name` — coverpage-reported manager name
- `crd_number` — filer CRD if resolvable at promote time
- `inst_parent_name` — pre-rollup parent label (legacy; kept for app compatibility)
- `quarter` — `YYYYQN`
- `report_date` — filing report period
- `cusip` — CUSIP9
- `issuer_name` — infotable NAMEOFISSUER
- `security_type` — SSHPRNAMTTYPE
- `shares` — SSHPRNAMT
- `market_value_usd` — VALUE × 1000 (13F amounts are in thousands)
- `pct_of_portfolio` — `market_value_usd / SUM(market_value_usd) PARTITION BY accession_number`
- `discretion` — INVESTMENTDISCRETION
- `vote_sole`, `vote_shared`, `vote_none` — voting authority counts
- `put_call` — PUTCALL (if option)
- `fund_name` — parsed from coverpage where present

### Group 2 — Entity enrichment (owner: `promote_13f.py` [proposed], reads `entity_current`, NOT NULL)

Resolved at promote time from the entity MDM. Promote is blocked if any
required `cik` is not present in `entity_identifiers` with an active row
— see `entity_gate_check()`.

- `entity_id` — resolved filer entity_id
- `rollup_entity_id` — economic_control_v1 rollup target
- `rollup_name` — display name of rollup target
- `dm_rollup_entity_id` — decision_maker_v1 rollup target (for sub-adviser-aware views)
- `dm_rollup_name` — display name of dm rollup target
- `entity_type` — classification from `entity_classification_history` active row
- `manager_type` — derived from `entity_type` plus activist override; canonical app-facing type column
- `is_passive`, `is_activist` — booleans derived from classification + `entity_classification_history.is_activist`
- `classification_source` — provenance of the classification (ADV, N-CEN, SIC, manual_l4, etc.)

### Group 3 — Market/reference enrichment (owner: `enrich_holdings.py` [proposed], NULLABLE)

Enrichment pass that runs **after** promote — NOT at promote time
(Decision D4). Nullability guarantee: queries.py must handle every
column in this group as potentially NULL. Enrichment pass rewrites these
columns in place with a row-level UPDATE joined on
`(accession_number, cusip)`.

- `ticker` — resolved from `securities` by cusip. Null when CUSIP has no listed equity.
- `security_type_inferred` — derived from `securities.security_type_inferred`
- `market_value_live` — `shares × market_data.price` at latest market_data snapshot. Null for delisted / foreign / non-equity.
- `pct_of_float` — `shares × 100.0 / market_data.float_shares`. Null when float is missing.

---

## 4. Column ownership — `fund_holdings_v2`

Prod DDL (2026-04-13):

```sql
CREATE TABLE fund_holdings_v2(
    fund_cik VARCHAR, fund_name VARCHAR, family_name VARCHAR,
    series_id VARCHAR, "quarter" VARCHAR, report_month VARCHAR,
    report_date DATE, cusip VARCHAR, isin VARCHAR, issuer_name VARCHAR,
    ticker VARCHAR, asset_category VARCHAR, shares_or_principal DOUBLE,
    market_value_usd DOUBLE, pct_of_nav DOUBLE, fair_value_level VARCHAR,
    is_restricted BOOLEAN, payoff_profile VARCHAR, loaded_at TIMESTAMP,
    fund_strategy VARCHAR, best_index VARCHAR, entity_id BIGINT,
    rollup_entity_id BIGINT, dm_entity_id BIGINT,
    dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR
);
```

### Group 1 — Core N-PORT facts (owner: `promote_nport.py` [proposed], NOT NULL where indicated)

- `fund_cik` — N-PORT filer CIK
- `fund_name` — N-PORT filer name
- `family_name` — funds-family label parsed from N-PORT header
- `series_id` — SEC SERIES_ID (`S000######`)
- `quarter` — `YYYYQN` — quarter the report rolls up into
- `report_month` — monthly grain the N-PORT was filed for (e.g. `2025-09`)
- `report_date` — exact period-of-report date
- `cusip` — investment CUSIP
- `isin` — investment ISIN where present
- `issuer_name` — investment NAMEOFISSUER
- `asset_category` — N-PORT assetCat
- `shares_or_principal` — balance
- `market_value_usd` — valUSD
- `pct_of_nav` — PCT of NAV
- `fair_value_level` — 1/2/3
- `is_restricted` — restricted boolean
- `payoff_profile` — derivatives payoff profile
- `loaded_at` — pipeline-set timestamp

### Group 2 — Entity + fund-strategy enrichment (owner: `promote_nport.py`, reads `entity_current` + `fund_universe`, NOT NULL for entity columns)

- `entity_id` — resolved fund filer entity_id via fund_cik
- `rollup_entity_id` — economic_control_v1 rollup target (fund sponsor)
- `dm_entity_id` — decision_maker_v1 entity per `ncen_adviser_map` sub-adviser
- `dm_rollup_entity_id` — decision_maker_v1 rollup target
- `dm_rollup_name` — display name
- `fund_strategy` — copied from `fund_universe.fund_strategy` at promote time
- `best_index` — copied from `fund_universe.best_index`

### Group 3 — Reference enrichment (owner: `enrich_holdings.py` [proposed], NULLABLE)

Same post-promote pass as `holdings_v2`.

- `ticker` — resolved from `securities` by cusip. Null for bonds, illiquid, or unlisted.

---

## 5. Option B split contract

**Option B** refers to splitting the promote vs enrichment responsibilities
so the pipeline can produce a valid L3 row *without* market data being
available. Group 3 columns are the split boundary.

**Split boundary columns:**
- `holdings_v2.{ticker, security_type_inferred, market_value_live, pct_of_float}`
- `fund_holdings_v2.ticker`

**Nullability guarantee:** these columns are allowed to be NULL in
production. `queries.py` must treat them as nullable in every read path.
Grep of prod `scripts/queries.py` confirms existing code already uses
`NULLS LAST`, `SUM(... market_value_live)` which naturally tolerates
NULL, and `COUNT(CASE WHEN market_value_live IS NOT NULL ...)` probes —
so the query layer is already Option-B-compatible.

**What must be true before Option B can be safely enabled:**

1. `promote_13f.py` sets `ticker`, `market_value_live`, `pct_of_float`,
   `security_type_inferred` to NULL on insert — never joins `securities`
   or `market_data` at promote time.
2. `enrich_holdings.py` runs as a separate step, owns an UPDATE that
   rewrites these four columns in place using a join to `securities` and
   `market_data`. Idempotent; safe to re-run.
3. Every query function that reads these columns continues to work when
   the value is NULL. Current grep shows ~40 references across
   `queries.py` — none dereference `.market_value_live` without a
   SUM/NULL-tolerant aggregate, and `pct_of_float` is always SUMed or
   compared with `IS NOT NULL`. Confirmed safe.
4. `enrich_holdings.py` writes to `data_freshness` with
   `table_name='holdings_v2_enrichment'` so the FreshnessBadge can
   surface enrichment-lag separately from ingest-lag.
5. The app still works when enrichment has not yet run against a
   freshly-promoted quarter — i.e., a just-promoted quarter shows
   Register / Conviction rows with null ticker/market_value_live and the
   tab handles that cleanly (degrades gracefully, doesn't 500). Covered
   today by the app's existing `NULLS LAST` + NULL-tolerant aggregates.

**Grep evidence (market_value_live + pct_of_float in queries.py):**
~40 occurrences, all inside `SUM(...)` aggregates, `NULLS LAST` ORDER
BY, or `WHERE ... IS NOT NULL` guards. No bare-deref reads in
record-shaping code. Option B is compatible today.

---

## 6. Open decisions D5–D8

These cannot be resolved without operational data from the first few
framework pipeline runs. Recorded here so the orchestrator decision at
Step 18 has a concrete list.

### D5 — Entity retro-enrichment when merges change historical `rollup_entity_id`

**Decision needed:** When an entity merge (e.g. NorthStar eid=6693→7693)
changes the rollup target, do we retro-stamp `rollup_entity_id` in
historical `holdings_v2` rows, or carry the mapping in `entity_current`
only and let the app resolve at read time?

**Options:** (a) batch-rebuild affected historical rows at promote time
with a JOIN to the new `entity_rollup_history` open row; (b) keep
historical rollup as written, look up via view; (c) hybrid — retro-stamp
the last 4 quarters at promote, accept drift beyond.

**Why unresolved:** We need two or three promote cycles to measure
retro-stamp cost at 12.27M row scale. Current `build_entities.py --reset`
rewrite takes minutes; on-promote retro would need to be measured.

### D6 — `market_value_live` refresh cadence for historical rows

**Decision needed:** Does `enrich_holdings.py` refresh every historical
row on every run, or only freshly-promoted rows? Historical
`market_value_live` is a snapshot at enrichment time, not point-in-time.

**Options:** (a) freshly-promoted only — historical values frozen at
first enrichment; (b) full refresh every run — current behavior implied
by `build_summaries.py` design; (c) refresh latest quarter only, freeze
rest.

**Why unresolved:** Depends on app semantics. If "market value live"
means "what is the position worth today" the app expects (b). If it
means "what was it worth at quarter-end" the app expects freeze-after-
first-enrichment. Worth an explicit product decision, not a pipeline
decision.

### D7 — Snapshot table retention policy

**Decision needed:** `{entity_table}_snapshot_{ts}` tables accumulate in
prod — 16 snapshots of each of 9 entity tables = 144 tables pending.
Retention: 7 days, 30 days, keep 3, keep until next validation run?

**Options:** (a) drop any snapshot older than 7 days when
`promote_staging.py` runs; (b) keep last 3 snapshots per table, drop the
rest; (c) keep indefinitely until manual sweep.

**Why unresolved:** Current prod has 16 snapshots × 9 entity tables
= 144. At ~20k rows each that's ~2.88M snapshot rows — negligible for
DuckDB. But count will grow with every promote. Sweep script can be
added to `promote_staging.py` once we see natural cadence over 2–4
weeks of pipeline runs.

### D8 — L3 canonical DDL migration framework

**Decision needed:** How do we add / alter columns on L3 canonical
tables going forward? `ALTER TABLE` at runtime is not acceptable. The
options are: (a) numbered migration scripts similar to this session's
`001_pipeline_control_plane.py`; (b) full CREATE-TABLE-AS with rename
swap; (c) rely on owner-script DDL with `CREATE TABLE IF NOT EXISTS`
plus column-diff additions in migrations.

**Why unresolved:** Need one real schema change to validate the chosen
approach. The `summary_by_parent` DDL drift (see `docs/canonical_ddl.md`)
is the obvious first candidate — the right fix is a migration script
that adds `rollup_entity_id`, `total_nport_aum`, `nport_coverage_pct`
columns to `build_summaries.py`'s `CREATE TABLE IF NOT EXISTS`, then a
rebuild. Once that ships, the pattern is proven.
