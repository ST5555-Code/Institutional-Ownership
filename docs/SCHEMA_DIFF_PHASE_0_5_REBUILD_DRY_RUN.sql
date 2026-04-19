-- ============================================================
-- PHASE 0.5 STAGING REBUILD — DRY-RUN SQL
-- ============================================================
-- INF39 / BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE
-- Generated: 2026-04-19
-- Source:    data/13f.duckdb (prod, read-only)
-- Target:    data/13f_staging.duckdb (staging, WOULD-BE writes)
-- Status:    DRY-RUN — DO NOT EXECUTE
--
-- Strategy C: per-table capture-and-recreate.
-- For each of 30 L3 tables: DROP staging table + its indexes,
-- recreate from captured prod DDL, re-load data via ATTACH,
-- verify row count + index count + column list.
--
-- Exceptions (not straight prod mirrors):
--   _cache_openfigi           — STAGING AHEAD (+484 rows). See §11.4 surprise S1.
--   ncen_adviser_map          — PROD AHEAD (+103 rows). Normal drift.
--   fetched_tickers_13dg      — staging empty; prod has 6,075.
--   listed_filings_13dg       — staging empty; prod has 60,247.
--   entity_identifiers_staging, entity_relationships_staging — soft-landing queues.
-- ============================================================

-- Pre-flight: attach prod read-only
ATTACH 'data/13f.duckdb' AS p (READ_ONLY);

BEGIN TRANSACTION;

-- ------------------------------------------------------------
-- TABLE: holdings_v2  (prod_rows=12,270,984 stg_rows=12,270,984 idx=4 tier=XL)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 12270984
SELECT COUNT(*) AS prod_row_count FROM p.holdings_v2;

DROP INDEX IF EXISTS idx_hv2_cik_quarter;
DROP INDEX IF EXISTS idx_hv2_entity_id;
DROP INDEX IF EXISTS idx_hv2_rollup;
DROP INDEX IF EXISTS idx_hv2_ticker_quarter;
DROP TABLE IF EXISTS holdings_v2;

-- Recreate from captured prod DDL
CREATE TABLE holdings_v2(accession_number VARCHAR, cik VARCHAR, manager_name VARCHAR, crd_number VARCHAR, inst_parent_name VARCHAR, "quarter" VARCHAR, report_date VARCHAR, cusip VARCHAR, ticker VARCHAR, issuer_name VARCHAR, security_type VARCHAR, market_value_usd BIGINT, shares BIGINT, pct_of_portfolio DOUBLE, pct_of_so DOUBLE, manager_type VARCHAR, is_passive BOOLEAN, is_activist BOOLEAN, discretion VARCHAR, vote_sole BIGINT, vote_shared BIGINT, vote_none BIGINT, put_call VARCHAR, market_value_live DOUBLE, security_type_inferred VARCHAR, fund_name VARCHAR, classification_source VARCHAR, entity_id BIGINT, rollup_entity_id BIGINT, rollup_name VARCHAR, entity_type VARCHAR, dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR, pct_of_so_source VARCHAR);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_hv2_cik_quarter ON holdings_v2(cik, "quarter");
CREATE INDEX idx_hv2_entity_id ON holdings_v2(entity_id);
CREATE INDEX idx_hv2_rollup ON holdings_v2(rollup_entity_id, "quarter");
CREATE INDEX idx_hv2_ticker_quarter ON holdings_v2(ticker, "quarter");

-- Reload data from prod (ATTACH-based copy)
INSERT INTO holdings_v2 SELECT * FROM p.holdings_v2;

-- Post-check: row count parity
-- EXPECTED: 12270984 rows, 4 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM holdings_v2;

-- ------------------------------------------------------------
-- TABLE: fund_holdings_v2  (prod_rows=14,090,397 stg_rows=14,090,397 idx=3 tier=XL)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 14090397
SELECT COUNT(*) AS prod_row_count FROM p.fund_holdings_v2;

DROP INDEX IF EXISTS idx_fhv2_entity;
DROP INDEX IF EXISTS idx_fhv2_rollup;
DROP INDEX IF EXISTS idx_fhv2_series;
DROP TABLE IF EXISTS fund_holdings_v2;

-- Recreate from captured prod DDL
CREATE TABLE fund_holdings_v2(fund_cik VARCHAR, fund_name VARCHAR, family_name VARCHAR, series_id VARCHAR, "quarter" VARCHAR, report_month VARCHAR, report_date DATE, cusip VARCHAR, isin VARCHAR, issuer_name VARCHAR, ticker VARCHAR, asset_category VARCHAR, shares_or_principal DOUBLE, market_value_usd DOUBLE, pct_of_nav DOUBLE, fair_value_level VARCHAR, is_restricted BOOLEAN, payoff_profile VARCHAR, loaded_at TIMESTAMP, fund_strategy VARCHAR, best_index VARCHAR, entity_id BIGINT, rollup_entity_id BIGINT, dm_entity_id BIGINT, dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_fhv2_entity ON fund_holdings_v2(entity_id);
CREATE INDEX idx_fhv2_rollup ON fund_holdings_v2(rollup_entity_id, "quarter");
CREATE INDEX idx_fhv2_series ON fund_holdings_v2(series_id, "quarter");

-- Reload data from prod (ATTACH-based copy)
INSERT INTO fund_holdings_v2 SELECT * FROM p.fund_holdings_v2;

-- Post-check: row count parity
-- EXPECTED: 14090397 rows, 3 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM fund_holdings_v2;

-- ------------------------------------------------------------
-- TABLE: beneficial_ownership_v2  (prod_rows=51,905 stg_rows=51,905 idx=1 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 51905
SELECT COUNT(*) AS prod_row_count FROM p.beneficial_ownership_v2;

DROP INDEX IF EXISTS idx_bov2_entity;
DROP TABLE IF EXISTS beneficial_ownership_v2;

-- Recreate from captured prod DDL
CREATE TABLE beneficial_ownership_v2(accession_number VARCHAR, filer_cik VARCHAR, filer_name VARCHAR, subject_cusip VARCHAR, subject_ticker VARCHAR, subject_name VARCHAR, filing_type VARCHAR, filing_date DATE, report_date DATE, pct_owned DOUBLE, shares_owned BIGINT, aggregate_value DOUBLE, intent VARCHAR, is_amendment BOOLEAN, prior_accession VARCHAR, purpose_text VARCHAR, group_members VARCHAR, manager_cik VARCHAR, loaded_at TIMESTAMP, name_resolved BOOLEAN, entity_id BIGINT, rollup_entity_id BIGINT, rollup_name VARCHAR, dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_bov2_entity ON beneficial_ownership_v2(entity_id);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO beneficial_ownership_v2 SELECT * FROM p.beneficial_ownership_v2;

-- Post-check: row count parity
-- EXPECTED: 51905 rows, 1 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM beneficial_ownership_v2;

-- ------------------------------------------------------------
-- TABLE: securities  (prod_rows=430,149 stg_rows=430,149 idx=0 tier=M)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 430149
SELECT COUNT(*) AS prod_row_count FROM p.securities;

DROP TABLE IF EXISTS securities;

-- Recreate from captured prod DDL
CREATE TABLE securities(cusip VARCHAR, issuer_name VARCHAR, ticker VARCHAR, security_type VARCHAR, exchange VARCHAR, market_sector VARCHAR, sector VARCHAR, industry VARCHAR, sic_code INTEGER, is_energy BOOLEAN, is_media BOOLEAN, holdings_count BIGINT, total_value DOUBLE, security_type_inferred VARCHAR, canonical_type VARCHAR, canonical_type_source VARCHAR, is_equity BOOLEAN, is_priceable BOOLEAN, ticker_expected BOOLEAN, is_active BOOLEAN DEFAULT(CAST('t' AS BOOLEAN)), figi VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO securities SELECT * FROM p.securities;

-- Post-check: row count parity
-- EXPECTED: 430149 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM securities;

-- ------------------------------------------------------------
-- TABLE: market_data  (prod_rows=10,064 stg_rows=10,064 idx=1 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 10064
SELECT COUNT(*) AS prod_row_count FROM p.market_data;

DROP INDEX IF EXISTS idx_market_ticker;
DROP TABLE IF EXISTS market_data;

-- Recreate from captured prod DDL
CREATE TABLE market_data(ticker VARCHAR, price_live DOUBLE, market_cap DOUBLE, float_shares DOUBLE, shares_outstanding DOUBLE, fifty_two_week_high DOUBLE, fifty_two_week_low DOUBLE, avg_volume_30d DOUBLE, sector VARCHAR, industry VARCHAR, exchange VARCHAR, fetch_date VARCHAR, price_2025Q1 INTEGER, price_2025Q2 INTEGER, price_2025Q3 INTEGER, price_2025Q4 INTEGER, unfetchable BOOLEAN, unfetchable_reason VARCHAR, metadata_date VARCHAR, sec_date VARCHAR, public_float_usd DOUBLE, shares_as_of VARCHAR, shares_form VARCHAR, shares_filed VARCHAR, shares_source_tag VARCHAR, cik VARCHAR);

-- Recreate indexes from captured prod DDL
CREATE UNIQUE INDEX idx_market_ticker ON market_data(ticker);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO market_data SELECT * FROM p.market_data;

-- Post-check: row count parity
-- EXPECTED: 10064 rows, 1 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM market_data;

-- ------------------------------------------------------------
-- TABLE: short_interest  (prod_rows=328,595 stg_rows=328,595 idx=0 tier=M)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 328595
SELECT COUNT(*) AS prod_row_count FROM p.short_interest;

DROP TABLE IF EXISTS short_interest;

-- Recreate from captured prod DDL
CREATE TABLE short_interest(ticker VARCHAR, short_volume BIGINT, short_exempt_volume BIGINT, total_volume BIGINT, report_date DATE, report_month VARCHAR, short_pct DOUBLE, loaded_at TIMESTAMP, PRIMARY KEY(ticker, report_date));

-- Reload data from prod (ATTACH-based copy)
INSERT INTO short_interest SELECT * FROM p.short_interest;

-- Post-check: row count parity
-- EXPECTED: 328595 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM short_interest;

-- ------------------------------------------------------------
-- TABLE: fund_universe  (prod_rows=12,870 stg_rows=12,870 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 12870
SELECT COUNT(*) AS prod_row_count FROM p.fund_universe;

DROP TABLE IF EXISTS fund_universe;

-- Recreate from captured prod DDL
CREATE TABLE fund_universe(fund_cik VARCHAR, fund_name VARCHAR, series_id VARCHAR, family_name VARCHAR, total_net_assets DOUBLE, fund_category VARCHAR, is_actively_managed BOOLEAN, total_holdings_count INTEGER, equity_pct DOUBLE, top10_concentration DOUBLE, last_updated TIMESTAMP, fund_strategy VARCHAR, best_index VARCHAR, strategy_narrative VARCHAR, strategy_source VARCHAR, strategy_fetched_at TIMESTAMP, PRIMARY KEY(series_id));

-- Reload data from prod (ATTACH-based copy)
INSERT INTO fund_universe SELECT * FROM p.fund_universe;

-- Post-check: row count parity
-- EXPECTED: 12870 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM fund_universe;

-- ------------------------------------------------------------
-- TABLE: shares_outstanding_history  (prod_rows=338,053 stg_rows=338,053 idx=1 tier=M)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 338053
SELECT COUNT(*) AS prod_row_count FROM p.shares_outstanding_history;

DROP INDEX IF EXISTS idx_soh_ticker_date;
DROP TABLE IF EXISTS shares_outstanding_history;

-- Recreate from captured prod DDL
CREATE TABLE shares_outstanding_history(ticker VARCHAR, cik VARCHAR, as_of_date DATE, shares BIGINT NOT NULL, form VARCHAR, filed_date DATE, source_tag VARCHAR, PRIMARY KEY(ticker, as_of_date));

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_soh_ticker_date ON shares_outstanding_history(ticker, as_of_date);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO shares_outstanding_history SELECT * FROM p.shares_outstanding_history;

-- Post-check: row count parity
-- EXPECTED: 338053 rows, 1 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM shares_outstanding_history;

-- ------------------------------------------------------------
-- TABLE: adv_managers  (prod_rows=16,606 stg_rows=16,606 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 16606
SELECT COUNT(*) AS prod_row_count FROM p.adv_managers;

DROP TABLE IF EXISTS adv_managers;

-- Recreate from captured prod DDL
CREATE TABLE adv_managers(crd_number VARCHAR, sec_file_number VARCHAR, cik VARCHAR, firm_name VARCHAR, legal_name VARCHAR, city VARCHAR, state VARCHAR, address VARCHAR, adv_5f_raum DOUBLE, adv_5f_raum_discrtnry DOUBLE, adv_5f_raum_non_discrtnry DOUBLE, adv_5f_num_accts BIGINT, pct_discretionary DOUBLE, strategy_inferred VARCHAR, is_activist BOOLEAN, has_hedge_funds VARCHAR, has_pe_funds VARCHAR, has_vc_funds VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO adv_managers SELECT * FROM p.adv_managers;

-- Post-check: row count parity
-- EXPECTED: 16606 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM adv_managers;

-- ------------------------------------------------------------
-- TABLE: ncen_adviser_map  (prod_rows=11,209 stg_rows=11,106 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 11209
SELECT COUNT(*) AS prod_row_count FROM p.ncen_adviser_map;

DROP TABLE IF EXISTS ncen_adviser_map;

-- Recreate from captured prod DDL
CREATE TABLE ncen_adviser_map(registrant_cik VARCHAR, registrant_name VARCHAR, adviser_name VARCHAR, adviser_sec_file VARCHAR, adviser_crd VARCHAR, adviser_lei VARCHAR, "role" VARCHAR, series_id VARCHAR, series_name VARCHAR, report_date DATE, filing_date DATE, loaded_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO ncen_adviser_map SELECT * FROM p.ncen_adviser_map;

-- Post-check: row count parity
-- EXPECTED: 11209 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM ncen_adviser_map;

-- ------------------------------------------------------------
-- TABLE: filings  (prod_rows=43,358 stg_rows=43,358 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 43358
SELECT COUNT(*) AS prod_row_count FROM p.filings;

DROP TABLE IF EXISTS filings;

-- Recreate from captured prod DDL
CREATE TABLE filings(accession_number VARCHAR, cik VARCHAR, manager_name VARCHAR, crd_number VARCHAR, "quarter" VARCHAR, report_date VARCHAR, filing_type VARCHAR, amended BOOLEAN, filed_date VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO filings SELECT * FROM p.filings;

-- Post-check: row count parity
-- EXPECTED: 43358 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM filings;

-- ------------------------------------------------------------
-- TABLE: filings_deduped  (prod_rows=40,140 stg_rows=40,140 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 40140
SELECT COUNT(*) AS prod_row_count FROM p.filings_deduped;

DROP TABLE IF EXISTS filings_deduped;

-- Recreate from captured prod DDL
CREATE TABLE filings_deduped(accession_number VARCHAR, cik VARCHAR, manager_name VARCHAR, crd_number VARCHAR, "quarter" VARCHAR, report_date VARCHAR, filing_type VARCHAR, amended BOOLEAN, filed_date VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO filings_deduped SELECT * FROM p.filings_deduped;

-- Post-check: row count parity
-- EXPECTED: 40140 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM filings_deduped;

-- ------------------------------------------------------------
-- TABLE: cusip_classifications  (prod_rows=430,149 stg_rows=430,149 idx=3 tier=M)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 430149
SELECT COUNT(*) AS prod_row_count FROM p.cusip_classifications;

DROP INDEX IF EXISTS idx_cc_canonical;
DROP INDEX IF EXISTS idx_cc_priceable_active;
DROP INDEX IF EXISTS idx_cc_retry;
DROP TABLE IF EXISTS cusip_classifications;

-- Recreate from captured prod DDL
CREATE TABLE cusip_classifications(cusip VARCHAR PRIMARY KEY, canonical_type VARCHAR NOT NULL, canonical_type_source VARCHAR NOT NULL, raw_type_mode VARCHAR, raw_type_count INTEGER, security_type_inferred VARCHAR, asset_category_seed VARCHAR, market_sector VARCHAR, issuer_name VARCHAR, ticker VARCHAR, figi VARCHAR, exchange VARCHAR, country_code VARCHAR, is_equity BOOLEAN DEFAULT(CAST('f' AS BOOLEAN)) NOT NULL, ticker_expected BOOLEAN DEFAULT(CAST('f' AS BOOLEAN)) NOT NULL, is_priceable BOOLEAN DEFAULT(CAST('f' AS BOOLEAN)) NOT NULL, is_permanent BOOLEAN DEFAULT(CAST('f' AS BOOLEAN)) NOT NULL, is_active BOOLEAN DEFAULT(CAST('t' AS BOOLEAN)) NOT NULL, classification_source VARCHAR NOT NULL, ticker_source VARCHAR, confidence VARCHAR NOT NULL, openfigi_attempts INTEGER DEFAULT(0) NOT NULL, last_openfigi_attempt TIMESTAMP, openfigi_status VARCHAR, last_priceable_check TIMESTAMP, first_seen_date DATE NOT NULL, last_confirmed_date DATE, inactive_since DATE, inactive_reason VARCHAR, notes VARCHAR, created_at TIMESTAMP DEFAULT(CURRENT_TIMESTAMP), updated_at TIMESTAMP DEFAULT(CURRENT_TIMESTAMP), CHECK((confidence IN ('exact', 'high', 'medium', 'low'))), CHECK(((openfigi_status IN ('success', 'no_result', 'rate_limited', 'error')) OR (openfigi_status IS NULL))), CHECK(((inactive_reason IN ('delisted', 'merged', 'suspended', 'no_yf_data', 'wrong_classification', 'manual')) OR (inactive_reason IS NULL))));

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_cc_canonical ON cusip_classifications(canonical_type);
CREATE INDEX idx_cc_priceable_active ON cusip_classifications(is_priceable, is_active);
CREATE INDEX idx_cc_retry ON cusip_classifications(ticker_expected, is_permanent, openfigi_attempts);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO cusip_classifications SELECT * FROM p.cusip_classifications;

-- Post-check: row count parity
-- EXPECTED: 430149 rows, 3 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM cusip_classifications;

-- ------------------------------------------------------------
-- TABLE: _cache_openfigi  (prod_rows=15,807 stg_rows=16,291 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 15807
SELECT COUNT(*) AS prod_row_count FROM p._cache_openfigi;

DROP TABLE IF EXISTS _cache_openfigi;

-- Recreate from captured prod DDL
CREATE TABLE _cache_openfigi(cusip VARCHAR PRIMARY KEY, figi VARCHAR, ticker VARCHAR, exchange VARCHAR, security_type VARCHAR, market_sector VARCHAR, cached_at TIMESTAMP DEFAULT(CURRENT_TIMESTAMP));

-- Reload data from prod (ATTACH-based copy)
INSERT INTO _cache_openfigi SELECT * FROM p._cache_openfigi;

-- Post-check: row count parity
-- EXPECTED: 15807 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM _cache_openfigi;

-- ------------------------------------------------------------
-- TABLE: entities  (prod_rows=26,535 stg_rows=26,535 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 26535
SELECT COUNT(*) AS prod_row_count FROM p.entities;

DROP TABLE IF EXISTS entities;

-- Recreate from captured prod DDL
CREATE TABLE entities(entity_id BIGINT, entity_type VARCHAR, canonical_name VARCHAR, created_source VARCHAR, is_inferred BOOLEAN, created_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entities SELECT * FROM p.entities;

-- Post-check: row count parity
-- EXPECTED: 26535 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entities;

-- ------------------------------------------------------------
-- TABLE: entity_identifiers  (prod_rows=35,444 stg_rows=35,444 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 35444
SELECT COUNT(*) AS prod_row_count FROM p.entity_identifiers;

DROP TABLE IF EXISTS entity_identifiers;

-- Recreate from captured prod DDL
CREATE TABLE entity_identifiers(entity_id BIGINT, identifier_type VARCHAR, identifier_value VARCHAR, confidence VARCHAR, "source" VARCHAR, is_inferred BOOLEAN, valid_from DATE, valid_to DATE, created_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_identifiers SELECT * FROM p.entity_identifiers;

-- Post-check: row count parity
-- EXPECTED: 35444 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_identifiers;

-- ------------------------------------------------------------
-- TABLE: entity_relationships  (prod_rows=18,365 stg_rows=18,365 idx=2 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 18365
SELECT COUNT(*) AS prod_row_count FROM p.entity_relationships;

DROP INDEX IF EXISTS idx_er_child;
DROP INDEX IF EXISTS idx_er_parent;
DROP TABLE IF EXISTS entity_relationships;

-- Recreate from captured prod DDL
CREATE TABLE entity_relationships(relationship_id BIGINT, parent_entity_id BIGINT, child_entity_id BIGINT, relationship_type VARCHAR, control_type VARCHAR, is_primary BOOLEAN, primary_parent_key BIGINT, confidence VARCHAR, "source" VARCHAR, is_inferred BOOLEAN, valid_from DATE, valid_to DATE, created_at TIMESTAMP, last_refreshed_at TIMESTAMP);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_er_child ON entity_relationships(child_entity_id);
CREATE INDEX idx_er_parent ON entity_relationships(parent_entity_id);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_relationships SELECT * FROM p.entity_relationships;

-- Post-check: row count parity
-- EXPECTED: 18365 rows, 2 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_relationships;

-- ------------------------------------------------------------
-- TABLE: entity_aliases  (prod_rows=26,874 stg_rows=26,874 idx=2 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 26874
SELECT COUNT(*) AS prod_row_count FROM p.entity_aliases;

DROP INDEX IF EXISTS idx_ea_active;
DROP INDEX IF EXISTS idx_ea_name;
DROP TABLE IF EXISTS entity_aliases;

-- Recreate from captured prod DDL
CREATE TABLE entity_aliases(entity_id BIGINT, alias_name VARCHAR, alias_type VARCHAR, is_preferred BOOLEAN, preferred_key BIGINT, source_table VARCHAR, is_inferred BOOLEAN, valid_from DATE, valid_to DATE, created_at TIMESTAMP);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_ea_active ON entity_aliases(entity_id, valid_to);
CREATE INDEX idx_ea_name ON entity_aliases(alias_name);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_aliases SELECT * FROM p.entity_aliases;

-- Post-check: row count parity
-- EXPECTED: 26874 rows, 2 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_aliases;

-- ------------------------------------------------------------
-- TABLE: entity_classification_history  (prod_rows=26,595 stg_rows=26,595 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 26595
SELECT COUNT(*) AS prod_row_count FROM p.entity_classification_history;

DROP TABLE IF EXISTS entity_classification_history;

-- Recreate from captured prod DDL
CREATE TABLE entity_classification_history(entity_id BIGINT, classification VARCHAR, is_activist BOOLEAN, confidence VARCHAR, "source" VARCHAR, is_inferred BOOLEAN, valid_from DATE, valid_to DATE, created_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_classification_history SELECT * FROM p.entity_classification_history;

-- Post-check: row count parity
-- EXPECTED: 26595 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_classification_history;

-- ------------------------------------------------------------
-- TABLE: entity_rollup_history  (prod_rows=59,804 stg_rows=59,804 idx=1 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 59804
SELECT COUNT(*) AS prod_row_count FROM p.entity_rollup_history;

DROP INDEX IF EXISTS idx_rollup_parent;
DROP TABLE IF EXISTS entity_rollup_history;

-- Recreate from captured prod DDL
CREATE TABLE entity_rollup_history(entity_id BIGINT, rollup_entity_id BIGINT, rollup_type VARCHAR, rule_applied VARCHAR, confidence VARCHAR, valid_from DATE, valid_to DATE, computed_at TIMESTAMP, "source" VARCHAR, routing_confidence VARCHAR DEFAULT('high'), review_due_date DATE);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_rollup_parent ON entity_rollup_history(rollup_entity_id, valid_to);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_rollup_history SELECT * FROM p.entity_rollup_history;

-- Post-check: row count parity
-- EXPECTED: 59804 rows, 1 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_rollup_history;

-- ------------------------------------------------------------
-- TABLE: entity_overrides_persistent  (prod_rows=245 stg_rows=245 idx=0 tier=XS)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 245
SELECT COUNT(*) AS prod_row_count FROM p.entity_overrides_persistent;

DROP TABLE IF EXISTS entity_overrides_persistent;

-- Recreate from captured prod DDL
CREATE TABLE entity_overrides_persistent(override_id BIGINT DEFAULT(nextval('override_id_seq')) NOT NULL, entity_cik VARCHAR, "action" VARCHAR NOT NULL, field VARCHAR, old_value VARCHAR, new_value VARCHAR, reason VARCHAR, analyst VARCHAR, still_valid BOOLEAN DEFAULT(CAST('t' AS BOOLEAN)) NOT NULL, applied_at TIMESTAMP DEFAULT(now()), created_at TIMESTAMP DEFAULT(now()), identifier_type VARCHAR DEFAULT('cik'), identifier_value VARCHAR, rollup_type VARCHAR DEFAULT('economic_control_v1'), relationship_context VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_overrides_persistent SELECT * FROM p.entity_overrides_persistent;

-- Post-check: row count parity
-- EXPECTED: 245 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_overrides_persistent;

-- ------------------------------------------------------------
-- TABLE: cik_crd_direct  (prod_rows=4,059 stg_rows=4,059 idx=0 tier=XS)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 4059
SELECT COUNT(*) AS prod_row_count FROM p.cik_crd_direct;

DROP TABLE IF EXISTS cik_crd_direct;

-- Recreate from captured prod DDL
CREATE TABLE cik_crd_direct(cik VARCHAR, crd_number VARCHAR, match_type VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO cik_crd_direct SELECT * FROM p.cik_crd_direct;

-- Post-check: row count parity
-- EXPECTED: 4059 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM cik_crd_direct;

-- ------------------------------------------------------------
-- TABLE: cik_crd_links  (prod_rows=353 stg_rows=353 idx=0 tier=XS)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 353
SELECT COUNT(*) AS prod_row_count FROM p.cik_crd_links;

DROP TABLE IF EXISTS cik_crd_links;

-- Recreate from captured prod DDL
CREATE TABLE cik_crd_links(cik VARCHAR, crd_number VARCHAR, filing_name VARCHAR, adv_name VARCHAR, match_score DOUBLE);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO cik_crd_links SELECT * FROM p.cik_crd_links;

-- Post-check: row count parity
-- EXPECTED: 353 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM cik_crd_links;

-- ------------------------------------------------------------
-- TABLE: lei_reference  (prod_rows=13,143 stg_rows=13,143 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 13143
SELECT COUNT(*) AS prod_row_count FROM p.lei_reference;

DROP TABLE IF EXISTS lei_reference;

-- Recreate from captured prod DDL
CREATE TABLE lei_reference(lei VARCHAR PRIMARY KEY, entity_name VARCHAR, entity_type VARCHAR, series_id VARCHAR, fund_cik VARCHAR, updated_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO lei_reference SELECT * FROM p.lei_reference;

-- Post-check: row count parity
-- EXPECTED: 13143 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM lei_reference;

-- ------------------------------------------------------------
-- TABLE: other_managers  (prod_rows=15,405 stg_rows=15,405 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 15405
SELECT COUNT(*) AS prod_row_count FROM p.other_managers;

DROP TABLE IF EXISTS other_managers;

-- Recreate from captured prod DDL
CREATE TABLE other_managers(accession_number VARCHAR, sequence_number VARCHAR, other_cik VARCHAR, form13f_file_number VARCHAR, crd_number VARCHAR, sec_file_number VARCHAR, "name" VARCHAR, "quarter" VARCHAR);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO other_managers SELECT * FROM p.other_managers;

-- Post-check: row count parity
-- EXPECTED: 15405 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM other_managers;

-- ------------------------------------------------------------
-- TABLE: parent_bridge  (prod_rows=11,135 stg_rows=11,135 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 11135
SELECT COUNT(*) AS prod_row_count FROM p.parent_bridge;

DROP TABLE IF EXISTS parent_bridge;

-- Recreate from captured prod DDL
CREATE TABLE parent_bridge(cik VARCHAR, manager_name VARCHAR, crd_number VARCHAR, parent_name VARCHAR, strategy_type VARCHAR, is_activist BOOLEAN, manually_verified BOOLEAN);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO parent_bridge SELECT * FROM p.parent_bridge;

-- Post-check: row count parity
-- EXPECTED: 11135 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM parent_bridge;

-- ------------------------------------------------------------
-- TABLE: fetched_tickers_13dg  (prod_rows=6,075 stg_rows=0 idx=0 tier=XS)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 6075
SELECT COUNT(*) AS prod_row_count FROM p.fetched_tickers_13dg;

DROP TABLE IF EXISTS fetched_tickers_13dg;

-- Recreate from captured prod DDL
CREATE TABLE fetched_tickers_13dg(ticker VARCHAR PRIMARY KEY, fetched_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO fetched_tickers_13dg SELECT * FROM p.fetched_tickers_13dg;

-- Post-check: row count parity
-- EXPECTED: 6075 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM fetched_tickers_13dg;

-- ------------------------------------------------------------
-- TABLE: listed_filings_13dg  (prod_rows=60,247 stg_rows=0 idx=0 tier=S)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 60247
SELECT COUNT(*) AS prod_row_count FROM p.listed_filings_13dg;

DROP TABLE IF EXISTS listed_filings_13dg;

-- Recreate from captured prod DDL
CREATE TABLE listed_filings_13dg(accession_number VARCHAR PRIMARY KEY, ticker VARCHAR, form VARCHAR, filing_date VARCHAR, filer_cik VARCHAR, subject_name VARCHAR, subject_cik VARCHAR, listed_at TIMESTAMP);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO listed_filings_13dg SELECT * FROM p.listed_filings_13dg;

-- Post-check: row count parity
-- EXPECTED: 60247 rows, 0 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM listed_filings_13dg;

-- ------------------------------------------------------------
-- TABLE: entity_identifiers_staging  (prod_rows=3,503 stg_rows=3,503 idx=3 tier=XS)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 3503
SELECT COUNT(*) AS prod_row_count FROM p.entity_identifiers_staging;

DROP INDEX IF EXISTS idx_eis_entity;
DROP INDEX IF EXISTS idx_eis_identifier;
DROP INDEX IF EXISTS idx_eis_pending;
DROP TABLE IF EXISTS entity_identifiers_staging;

-- Recreate from captured prod DDL
CREATE TABLE entity_identifiers_staging(staging_id BIGINT, entity_id BIGINT, identifier_type VARCHAR, identifier_value VARCHAR, confidence VARCHAR, "source" VARCHAR, conflict_reason VARCHAR, existing_entity_id BIGINT, review_status VARCHAR, reviewed_by VARCHAR, reviewed_at TIMESTAMP, notes VARCHAR, created_at TIMESTAMP);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_eis_entity ON entity_identifiers_staging(entity_id);
CREATE INDEX idx_eis_identifier ON entity_identifiers_staging(identifier_type, identifier_value);
CREATE INDEX idx_eis_pending ON entity_identifiers_staging(review_status, created_at);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_identifiers_staging SELECT * FROM p.entity_identifiers_staging;

-- Post-check: row count parity
-- EXPECTED: 3503 rows, 3 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_identifiers_staging;

-- ------------------------------------------------------------
-- TABLE: entity_relationships_staging  (prod_rows=0 stg_rows=0 idx=2 tier=XS)
-- ------------------------------------------------------------
-- Pre-check: captured prod row count = 0
SELECT COUNT(*) AS prod_row_count FROM p.entity_relationships_staging;

DROP INDEX IF EXISTS idx_ers_child;
DROP INDEX IF EXISTS idx_ers_status;
DROP TABLE IF EXISTS entity_relationships_staging;

-- Recreate from captured prod DDL
CREATE TABLE entity_relationships_staging(id BIGINT DEFAULT(nextval('identifier_staging_id_seq')), child_entity_id BIGINT NOT NULL, parent_entity_id BIGINT, owner_name VARCHAR NOT NULL, relationship_type VARCHAR, ownership_pct FLOAT, "source" VARCHAR, confidence VARCHAR, conflict_reason VARCHAR, review_status VARCHAR DEFAULT('pending'), created_at TIMESTAMP DEFAULT(CURRENT_TIMESTAMP), reviewer VARCHAR, reviewed_at TIMESTAMP, resolution VARCHAR);

-- Recreate indexes from captured prod DDL
CREATE INDEX idx_ers_child ON entity_relationships_staging(child_entity_id);
CREATE INDEX idx_ers_status ON entity_relationships_staging(review_status);

-- Reload data from prod (ATTACH-based copy)
INSERT INTO entity_relationships_staging SELECT * FROM p.entity_relationships_staging;

-- Post-check: row count parity
-- EXPECTED: 0 rows, 2 non-PK indexes
SELECT COUNT(*) AS staging_row_count FROM entity_relationships_staging;

-- COMMIT once all post-checks pass. ROLLBACK to abort.
COMMIT;  -- or ROLLBACK;

DETACH p;

CHECKPOINT;