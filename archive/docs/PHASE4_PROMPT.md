> **STATUS: SUPERSEDED — retained for history only (2026-04-20).**
> This prompt drove the Entity MDM Phase 4 production migration (sessions
> pre-2026-04-12). The React Phase 4 cutover completed 2026-04-13 (see
> `REACT_MIGRATION.md`); the Entity MDM Phase 4 work shipped earlier in
> the same lineage. Canonical entity IDs listed here are historical
> snapshots; query `entity_aliases` / `entity_identifiers` live rather
> than treating the list inline as authoritative. Do not paste this at
> the start of a new session — read `docs/NEXT_SESSION_CONTEXT.md`.

Continue work on the 13f-ownership project
Before anything else — save this prompt: Replace the entire contents of PHASE4_PROMPT.md with this prompt exactly as provided. Do not summarize or modify. Commit with message "Replace Phase 4 prompt with authoritative version from Claude.ai" and push. Show me the first 10 lines of the saved file to confirm. Then proceed with the rest of the instructions below.
 
Execute Phase 4 of the Entity MDM system — production migration. Read PHASE4_STATE.md and ENTITY_ARCHITECTURE.md Phase 4 section before starting. Stop and report at every stage gate. Do not proceed past any gate without explicit authorization.
 
First — update two docs before any migration work:
1.    Update PHASE4_STATE.md — change "Migration Approach" section to: "New data primary, old data shadow. App switches to entity-backed tables after pre-cutover scan passes. Legacy tables retained 30 days post-cutover, no fixed validation window — cutover authorized when background log is clean."
2.    Update ENTITY_ARCHITECTURE.md — in Phase 4 section, change shadow read duration from "2 weeks" to "No fixed window — legacy tables retained 30 days post-cutover. Background log reviewed periodically. Cutover authorized when log shows only expected discrepancies (name_change, new_gain)."
Commit both with message "Update Phase 4 approach: 30-day retention, no fixed validation window" and push before starting any migration work.
 
Critical context:
AUM parity confirmed: 50/50 match at 0.00% difference across $27T in top 50 tickers. Entity system produces identical dollar totals to legacy — difference is consolidation only (fewer parent rows, same AUM).
Canonical entity IDs for top parents:
•    Fidelity/FMR: eid=10443
•    BlackRock/iShares: eid=2
•    State Street/SSGA: eid=7984
•    Capital Group: eid=12
•    Dimensional: eid=5026
•    Morgan Stanley: eid=2920
•    T. Rowe Price: eid=17924
•    Vanguard: eid=4375
•    Ameriprise: eid=10178
•    Northern Trust: eid=4435
•    Wellington: eid=11220
•    Franklin: eid=4805
•    PGIM: eid=1589
•    First Trust: eid=136
Operating AM rollup policy: chain stops at operating asset manager. Never rolls to bank, insurance, or holding company parent. Morgan Stanley Investment Management and MS Wealth are separate self-rollup entities in economic_control_v1.
Correct JOIN pattern for all new queries:
JOIN entity_identifiers ei
    ON h.cik = ei.identifier_value
    AND ei.identifier_type = 'CIK'
    AND ei.valid_to = '9999-12-31'
JOIN entity_rollup_history erh
    ON ei.entity_id = erh.entity_id
    AND erh.rollup_type = 'economic_control_v1'
    AND erh.valid_to = '9999-12-31'
JOIN entity_aliases ea
    ON erh.rollup_entity_id = ea.entity_id
    AND ea.is_preferred = TRUE
    AND ea.valid_to = '9999-12-31'
-- Always use LEFT JOIN + COALESCE for standalone filers:
-- COALESCE(ea.alias_name, h.inst_parent_name) as display_name
 
Pre-migration checklist — run before touching any production tables:
1.    Run validate_entities.py against staging — must show 0 FAILs. Report results. Stop if any structural gate fails.
2.    Confirm commit 18d88dd is current HEAD on main branch.
3.    Check production DB not locked: lsof | grep 13f.duckdb
4.    Confirm app is running from readonly snapshot before starting.
5.    Confirm disk space: v2 tables will add ~3GB to production DB.
Report checklist results. Stop if any item fails. Do not touch production tables until checklist passes.
 
Stage 1 — Copy entity tables to production and build v2 tables
Step 1a — Copy entity tables from staging to production 13f.duckdb:
ATTACH 'data/13f_staging.duckdb' AS staging (READ_ONLY);

CREATE TABLE entities AS SELECT * FROM staging.entities;
CREATE TABLE entity_identifiers AS SELECT * FROM staging.entity_identifiers;
CREATE TABLE entity_relationships AS SELECT * FROM staging.entity_relationships;
CREATE TABLE entity_aliases AS SELECT * FROM staging.entity_aliases;
CREATE TABLE entity_classification_history AS SELECT * FROM staging.entity_classification_history;
CREATE TABLE entity_rollup_history AS SELECT * FROM staging.entity_rollup_history;
CREATE TABLE entity_identifiers_staging AS SELECT * FROM staging.entity_identifiers_staging;
CREATE TABLE entity_overrides_persistent AS SELECT * FROM staging.entity_overrides_persistent;

CREATE SEQUENCE entity_id_seq START (SELECT MAX(entity_id) + 1 FROM entities);
CREATE SEQUENCE relationship_id_seq START (SELECT MAX(relationship_id) + 1 FROM entity_relationships);

DETACH staging;
Recreate all indexes from entity_schema.sql. Recreate entity_current VIEW.
Verify row counts match staging exactly:
tables = ['entities', 'entity_identifiers', 'entity_relationships',
          'entity_aliases', 'entity_classification_history', 'entity_rollup_history']
for t in tables:
    staging_count = staging_con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    prod_count = prod_con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    assert staging_count == prod_count, f'{t}: staging={staging_count} prod={prod_count}'
    print(f'{t}: {prod_count} rows ✓')
Step 1b — Create holdings_v2:
CREATE TABLE holdings_v2 AS SELECT * FROM holdings;
ALTER TABLE holdings_v2 ADD COLUMN entity_id BIGINT;
ALTER TABLE holdings_v2 ADD COLUMN rollup_entity_id BIGINT;
ALTER TABLE holdings_v2 ADD COLUMN rollup_name VARCHAR;

UPDATE holdings_v2 h
SET entity_id = ei.entity_id
FROM entity_identifiers ei
WHERE h.cik = ei.identifier_value
    AND ei.identifier_type = 'CIK'
    AND ei.valid_to = '9999-12-31';

UPDATE holdings_v2 h
SET rollup_entity_id = erh.rollup_entity_id
FROM entity_rollup_history erh
WHERE h.entity_id = erh.entity_id
    AND erh.rollup_type = 'economic_control_v1'
    AND erh.valid_to = '9999-12-31';

UPDATE holdings_v2 h
SET rollup_name = ea.alias_name
FROM entity_aliases ea
WHERE h.rollup_entity_id = ea.entity_id
    AND ea.is_preferred = TRUE
    AND ea.valid_to = '9999-12-31';
Step 1c — Create fund_holdings_v2:
CREATE TABLE fund_holdings_v2 AS SELECT * FROM fund_holdings;
ALTER TABLE fund_holdings_v2 ADD COLUMN entity_id BIGINT;
ALTER TABLE fund_holdings_v2 ADD COLUMN rollup_entity_id BIGINT;

UPDATE fund_holdings_v2 fh
SET entity_id = ei.entity_id
FROM entity_identifiers ei
WHERE fh.series_id = ei.identifier_value
    AND ei.identifier_type = 'SERIES_ID'
    AND ei.valid_to = '9999-12-31';

UPDATE fund_holdings_v2 fh
SET rollup_entity_id = erh.rollup_entity_id
FROM entity_rollup_history erh
WHERE fh.entity_id = erh.entity_id
    AND erh.rollup_type = 'economic_control_v1'
    AND erh.valid_to = '9999-12-31';
Step 1d — Create beneficial_ownership_v2:
CREATE TABLE beneficial_ownership_v2 AS SELECT * FROM beneficial_ownership;
ALTER TABLE beneficial_ownership_v2 ADD COLUMN entity_id BIGINT;

UPDATE beneficial_ownership_v2 b
SET entity_id = ei.entity_id
FROM entity_identifiers ei
WHERE b.filer_cik = ei.identifier_value
    AND ei.identifier_type = 'CIK'
    AND ei.valid_to = '9999-12-31';
Step 1e — Build indexes:
CREATE INDEX idx_hv2_ticker_quarter ON holdings_v2(ticker, quarter);
CREATE INDEX idx_hv2_entity_id ON holdings_v2(entity_id);
CREATE INDEX idx_hv2_rollup ON holdings_v2(rollup_entity_id, quarter);
CREATE INDEX idx_hv2_cik_quarter ON holdings_v2(cik, quarter);
CREATE INDEX idx_fhv2_series ON fund_holdings_v2(series_id, quarter);
CREATE INDEX idx_fhv2_entity ON fund_holdings_v2(entity_id);
CREATE INDEX idx_fhv2_rollup ON fund_holdings_v2(rollup_entity_id, quarter);
CREATE INDEX idx_bov2_entity ON beneficial_ownership_v2(entity_id);
Step 1f — Coverage report (stop and report before Stage 1.5):
checks = [
    ('holdings_v2', 'entity_id', 95),
    ('holdings_v2', 'rollup_entity_id', 90),
    ('fund_holdings_v2', 'entity_id', 95),
    ('fund_holdings_v2', 'rollup_entity_id', 90),
    ('beneficial_ownership_v2', 'entity_id', 60),  # 13D/G filers include fund CIKs, individuals, and filing agents not in entity system — 53.7% is structural ceiling for current scope
]
for table, col, target in checks:
    total = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    covered = con.execute(f'SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL').fetchone()[0]
    pct = covered/total*100
    status = '✓' if pct >= target else '✗ BELOW TARGET'
    print(f'{table}.{col}: {pct:.1f}% ({covered}/{total}) target={target}% {status}')
Stop and report. Do not proceed to Stage 1.5 if any coverage target missed.
 
Stage 1.5 — Full ticker pre-cutover scan
Run before any app changes. Pure SQL comparison — no impact on users. Runtime: 2-5 minutes.
For every ticker in the holdings universe, compare top 25 parent rollup between legacy (inst_parent_name) and new (entity_id JOIN):
import duckdb
import pandas as pd

con = duckdb.connect('data/13f.duckdb')

tickers = [r[0] for r in con.execute(
    "SELECT DISTINCT ticker FROM holdings WHERE quarter='2025Q4' ORDER BY ticker"
).fetchall()]

results = []
for ticker in tickers:
    legacy = {r[0]: r[1] for r in con.execute("""
        SELECT inst_parent_name, SUM(market_value_live) as aum
        FROM holdings
        WHERE ticker=? AND quarter='2025Q4'
        GROUP BY inst_parent_name
        ORDER BY aum DESC LIMIT 25
    """, [ticker]).fetchall()}

    new = {r[0]: r[1] for r in con.execute("""
        SELECT COALESCE(ea.alias_name, h.inst_parent_name) as parent_name,
               SUM(h.market_value_live) as aum
        FROM holdings_v2 h
        LEFT JOIN entity_rollup_history erh
            ON h.entity_id = erh.entity_id
            AND erh.rollup_type = 'economic_control_v1'
            AND erh.valid_to = '9999-12-31'
        LEFT JOIN entity_aliases ea
            ON erh.rollup_entity_id = ea.entity_id
            AND ea.is_preferred = TRUE
            AND ea.valid_to = '9999-12-31'
        WHERE h.ticker=? AND h.quarter='2025Q4'
        GROUP BY parent_name
        ORDER BY aum DESC LIMIT 25
    """, [ticker]).fetchall()}

    for parent, aum in new.items():
        if parent not in legacy:
            results.append({'ticker': ticker, 'type': 'new_gain',
                          'parent': parent, 'new_aum': aum,
                          'legacy_aum': 0, 'diff': aum})
        elif abs(aum - legacy[parent]) / max(legacy[parent], 1) > 0.001:
            results.append({'ticker': ticker, 'type': 'value_diff',
                          'parent': parent, 'new_aum': aum,
                          'legacy_aum': legacy[parent],
                          'diff': abs(aum - legacy[parent])})

    for parent, aum in legacy.items():
        if parent not in new:
            results.append({'ticker': ticker, 'type': 'legacy_only',
                          'parent': parent, 'new_aum': 0,
                          'legacy_aum': aum, 'diff': aum})

df = pd.DataFrame(results)
df.sort_values('diff', ascending=False).to_csv('logs/phase4_prescan.csv', index=False)

print(f'Tickers scanned: {len(tickers)}')
print(f'Zero discrepancy: {len(tickers) - df.ticker.nunique() if len(df) > 0 else len(tickers)}')
if len(df) > 0:
    print(df.type.value_counts())
    print('\nTop 20 by dollar difference:')
    print(df.sort_values('diff', ascending=False).head(20).to_string())
Save to logs/phase4_prescan.csv. Stop and report results here before Stage 2.
Decision gate:
•    Zero value_diff + zero legacy_only → Stage 2 authorized immediately
•    value_diff or legacy_only found → paste top discrepancies here, I will diagnose before authorizing Stage 2
•    new_gain and name_change only → expected, Stage 2 authorized
 
Stage 2 — Switch app to new system (after scan authorized)
Only after I authorize based on scan results.
Step 2a — Update queries.py — all 34 query functions: Replace GROUP BY inst_parent_name with entity_id JOIN pattern:
-- OLD pattern
SELECT inst_parent_name, SUM(market_value_live)
FROM holdings
WHERE ticker = ? AND quarter = ?
GROUP BY inst_parent_name

-- NEW pattern
SELECT COALESCE(ea.alias_name, h.inst_parent_name) as inst_parent_name,
       erh.rollup_entity_id as entity_id,
       SUM(h.market_value_live)
FROM holdings_v2 h
LEFT JOIN entity_rollup_history erh
    ON h.entity_id = erh.entity_id
    AND erh.rollup_type = 'economic_control_v1'
    AND erh.valid_to = '9999-12-31'
LEFT JOIN entity_aliases ea
    ON erh.rollup_entity_id = ea.entity_id
    AND ea.is_preferred = TRUE
    AND ea.valid_to = '9999-12-31'
WHERE h.ticker = ? AND h.quarter = ?
GROUP BY inst_parent_name, erh.rollup_entity_id
COALESCE is mandatory — standalone filers with no rollup parent must fall back to inst_parent_name. Zero data loss.
Step 2b — Add shadow logging for 5 highest-traffic endpoints (Register, Conviction, Ownership Trend, Flow Analysis, Cross-Ownership):
def log_shadow_diff(endpoint, ticker, quarter, new_results, legacy_results):
    """Run legacy query in background, log differences. Never affects user response."""
    # Log format: timestamp|endpoint|ticker|quarter|type|parent|new_value|legacy_value|diff_pct
    # Types: value_diff, legacy_only, new_gain, name_change
    with open('logs/phase4_shadow.log', 'a') as f:
        # compare and write discrepancies only
        pass
Always return new system result to user. Legacy query is background only.
Step 2c — Update app.py: All endpoints reference holdings_v2, fund_holdings_v2, beneficial_ownership_v2.
Step 2d — Upgrade entity_current to MATERIALIZED VIEW:
DROP VIEW entity_current;
CREATE MATERIALIZED VIEW entity_current AS
[same definition as current VIEW];
Add REFRESH MATERIALIZED VIEW entity_current to run_pipeline.sh after each data ingestion run.
Step 2e — Restart app and verify all 13 tabs load for EQT, AR, NVDA, WBD, DVN:
•    Register: correct top 25 parents, Vanguard consolidated (eid=4375)
•    Morgan Stanley shows correctly (eid=2920, ~$1.675T, not phantom eid=23)
•    Conviction: direction/since/held columns present, N-PORT children rendering
•    Flow Analysis: charts rendering, period selector working
•    No 500 errors in app logs
Report: startup confirmation, tab verification, error log status.
 
Stage 3 — Parity validation
Create scripts/validate_phase4.py:
PARITY_GATES = {
    'row_count': 'holdings_v2 rows = holdings rows — exact match',
    'entity_coverage': 'holdings_v2.entity_id >95%',
    'rollup_coverage': 'holdings_v2.rollup_entity_id >90%',
    'total_aum': 'Total AUM difference <0.01% between new and legacy',
    'top_50_aum': 'Top 50 parent AUM — 0.00% difference confirmed pre-Phase 4',
    'known_merges': 'All 10 phantom merges present: Vanguard eid=4375, MS eid=2920, Fidelity eid=10443, State Street eid=7984, Northern Trust eid=4435, Wellington eid=11220, Dimensional eid=5026, Franklin eid=4805, PGIM eid=1589, First Trust eid=136',
    'no_legacy_only': 'Zero legacy_only discrepancies in phase4_prescan.csv',
    'shadow_clean': 'Shadow log shows only name_change and new_gain types',
}
Run all gates. Report results. Manual sign-off required before Stage 4.
 
Stage 4 — Cutover (explicit authorization required)
Only after Stage 3 gates pass and I explicitly authorize:
1.    Confirm app running cleanly on v2 tables with no errors
2.    Review logs/phase4_shadow.log — confirm only name_change and new_gain entries
3.    Report shadow log summary here — I will authorize Stage 5 when satisfied
4.    Keep original holdings, fund_holdings, beneficial_ownership — do NOT rename or drop yet
 
Stage 5 — Cleanup (30 days post-cutover, explicit authorization required)
Only after 30 days stable operation AND explicit authorization:
ALTER TABLE holdings RENAME TO holdings_legacy;
ALTER TABLE fund_holdings RENAME TO fund_holdings_legacy;
ALTER TABLE beneficial_ownership RENAME TO beneficial_ownership_legacy;
ALTER TABLE holdings_v2 RENAME TO holdings;
ALTER TABLE fund_holdings_v2 RENAME TO fund_holdings;
ALTER TABLE beneficial_ownership_v2 RENAME TO beneficial_ownership;
Update all fetch scripts and run_pipeline.sh to write to new table names. Update ENTITY_ARCHITECTURE.md and ROADMAP.md — mark Phase 4 complete. Commit and push.
 
Rollback at every stage:
•    Stage 1: Drop v2 tables and entity tables from production — no app impact
•    Stage 1.5: No app changes — nothing to roll back
•    Stage 2: Switch queries.py back to original holdings table — instant
•    Stage 3/4: queries.py rollback to holdings — instant
•    Stage 5: Rename tables back — holdings → holdings_v2, holdings_legacy → holdings
holdings_legacy retained 30 days minimum post-Stage 5. Git history preserves full schema at every commit.
 
Stop and report gates — do not proceed past any without explicit authorization:
•    After pre-migration checklist
•    After Stage 1 coverage report
•    After Stage 1.5 prescan results — paste top 20 discrepancies here for review
•    After Stage 2 app verification
•    After Stage 3 parity gates
•    After Stage 4 shadow log review
•    Stage 5 requires explicit written authorization — 30 days minimum after Stage 4
