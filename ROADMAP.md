# 13F Institutional Ownership Database — Roadmap

_Last updated: April 3, 2026_

---

## IN PROGRESS

| # | Item | Notes |
|---|------|-------|
| P1 | Full 13D/G fetch — `fetch_13dg.py` | Done | 60,135 filings parsed (99.8%). 112 remaining are HTTP 404s or regex-hang filings — not recoverable |
| P2 | `fetch_market.py` batch rewrite | Done | Batch yf.download(), persistent cache (7-day), upsert-only. --metadata-only mode, price-only fallback. Production tested |
| P3 | `compute_flows.py` set-based rewrite | Done | Single INSERT per period via window functions. 9.4M rows in 10s. Production tested |

---

## PIPELINE 1 — 13D/G Beneficial Ownership

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 1 | Amendment tracking | Done | `rebuild_current` uses ROW_NUMBER by filing_date DESC + amendment_count column |
| 3 | Crossed 5% threshold flag | Done | `crossed_5pct` boolean in beneficial_ownership_current via first_13g CTE |
| 4 | Intent change tracking | Done | `prior_intent` column via LAG() window function |
| 5 | `pct_owned` null improvement — tune regex for null cases | Done | Added 4 new patterns for 13D cover page format (Row 11, multi-line). 13G: 95.7% hit rate. 13D: structural gap (cover page layout) — new patterns improve coverage |

---

## PIPELINE 8 — Short Interest (FINRA)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 9 | Short vs long comparison — same manager long 13F and short N-PORT | Done | `get_short_long_comparison()` in queries.py, `/api/short_long` endpoint. Matches 13F long parents to N-PORT short fund advisers |
| 10 | Short squeeze signal — high crowding + high short interest flag | Done | `get_short_squeeze_candidates()` in queries.py, `/api/short_squeeze` endpoint. Flags tickers with ≥15% short + high institutional ownership. Squeeze score = short_pct × inst/float |

---

## APP — Flow Analysis Tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 11 | Chart.js fix | Done | CDN present, setTimeout 100ms added, destroy-before-reinit in place |
| 12 | Run `compute_flows.py` after full fetch completes | Done | 9.4M investor_flows rows, 19K ticker_flow_stats. 4 periods (4Q/3Q/2Q/1Q) |
| 13 | Refresh readonly snapshot | Done | Auto-refreshed after each pipeline run |

---

## APP — New Features (unlocked by short interest data)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 14 | Conviction tab — short interest column | Done | `short_pct` added to query3 results from short_interest table |
| 15 | Crowding tab — short crowding overlay | Done | `/api/crowding` endpoint, top holders + short history table |
| 16 | Smart Money tab — net exposure view | Done | `/api/smart_money` endpoint, long by type + N-PORT shorts |
| 17 | Activist tab — short interest context | Done | `short_interest` section added to query6 return data |
| 18 | New/Exits tab — short interest available | Done | Short data accessible via Crowding/Smart Money tabs |

---

## INFRASTRUCTURE — Performance & Reliability

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 19 | Centralize quarter config | Done | `config.py` created, imported by fetch_13f, load_13f, fetch_market, build_summaries, compute_flows. app.py SQL quarters need dedicated pass (60+ queries) |
| 20 | Incremental market data refresh | Done | `get_stale_tickers()` skips tickers fetched <7 days. `save_market_data()` upserts, never drops |
| 21 | Materialized summary tables | Done | `build_summaries.py` creates `summary_by_ticker` + `summary_by_parent`. --rebuild flag |
| 22 | Logged exceptions in app.py | Done | All bare `except Exception:` replaced with `as e` + `app.logger.error()` in endpoint handlers |
| 23 | Incremental `load_13f.py` — append + rebuild latest quarter only | Done | `--quarter 2025Q4` flag deletes+reloads single quarter from staging tables, then rebuilds filings+holdings from all data. Also added `--staging` and crash handler |
| 24 | OpenFIGI + yfinance persistent cache in `build_cusip.py` | Done | `_cache_openfigi` and `_cache_yfinance` tables, 30-day yfinance freshness |
| 25 | Readonly snapshot auto-refresh | Done | `scripts/refresh_snapshot.sh` — copies production to readonly with lock check |
| 26 | Benchmark script — time each pipeline stage | Done | `scripts/benchmark.py` with --run flag, stage timing, dry-run check |
| 27 | app.py quarter centralization — convert SQL strings to use config.py vars | Done | All 6 hardcoded quarter strings replaced with `{LQ}` / `{PQ}` variables. Zero hardcoded quarters remain in app.py |
| 28 | Pyflakes cleanup — unused imports removed from 17 scripts | Done | 31 unused imports fixed |
| 29 | SHOW TABLES removed from Flask endpoints — cached via `has_table()` | Done | 6 per-request queries replaced with startup-time cache |
| 30 | Snapshot switchback monitor — background thread auto-recovers from snapshot | Done | 60s polling, logs switchover |
| 31 | `queries.py` service layer — extract SQL from app.py route handlers | Done | 34 functions, 1,789 lines. app.py 2,362→618 lines |
| 32 | `export.py` — extract Excel export logic from app.py | Done | `build_excel()` + style constants, 83 lines |
| 33 | `run_pipeline.sh` hardened — process guard, timestamps, macOS notification | Done | pgrep check, phase start/end, osascript notify |
| 34 | Global SEC rate limiter — 2 req/s across all workers, Retry-After parsing | Done | `_rate_limit()` with shared lock, Phase 2 workers reduced to 2 |
| 35 | Phase 2 stall fix — reduced retry timeouts, per-future timeout | Done | Retry 3→2, sleep 10→5s, HTTP timeout 15→10s, fut.result(timeout=60) |
| 36 | `--phase1-only`, `--phase2-only`, `--phase3-only` CLI flags | Done | Each phase independently runnable and resumable |
| 37 | Crash handler on all fetch scripts | Done | db.crash_handler() writes traceback to logs/<script>_crash.log |
| 38 | Test isolation — `--test` uses `13f_test.duckdb`, write guard | Done | `db.py` centralized, assert_write_safe() |
| 39 | Bug 6 — fetch_market.py upsert, never drops table | Done | Unique index on ticker, delete-then-insert per batch |
| 40 | Bug 7 — app.py snapshot switchback monitor | Done | Background thread, 60s poll, auto-switch + log |
| 41 | Chart.js fix — setTimeout 100ms before chart init | Done | Lets DOM render canvas before Chart.js init |

---

## COMPLETED

| Date | Item | Details |
|------|------|---------|
| 2026-04-02 | Pipeline 1 — 13D/G beneficial ownership | `fetch_13dg.py`: 74 filings tested (AR,AM,DVN,WBD,CVX), `beneficial_ownership` + `beneficial_ownership_current` tables, activist tab upgraded to 4-section view |
| 2026-04-02 | Pipeline 2 — N-CEN identity join | `fetch_ncen.py`: 9,363 adviser-series mappings, 978 advisers, Wellington found subadvising 123 series across Hartford/JH/etc |
| 2026-04-02 | Pipeline 3 — Unified position table | `unify_positions.py`: 18.7M rows (12.3M 13F + 6.4M N-PORT), added to `update.py` |
| 2026-04-02 | Pipeline 4 — Monthly N-PORT | `fetch_nport.py` updated: `report_month` column, `MONTHLY_TARGETS` for all 3 months/quarter, backfilled 4.2M rows |
| 2026-04-02 | Pipeline 5 — Share class + LEI | `build_fund_classes.py`: 31,056 classes, 13,143 LEIs, `fund_classes` + `lei_reference` tables, 99% LEI coverage on fund_holdings |
| 2026-04-02 | Pipeline 6 — Peer groups | `peer_groups` table seeded (5 groups), `/api/peer_groups` endpoint, cross-ownership dropdown |
| 2026-04-02 | Pipeline 7 — LEI standardization | LEI column on positions table, `/api/fund_behavioral_profile` endpoint |
| 2026-04-02 | Pipeline 8 — FINRA short volume | `fetch_finra_short.py`: 102K rows, 9 dates, 12K tickers. `short_interest` table with daily short sale volume |
| 2026-04-02 | N-PORT short positions | `/api/nport_shorts` endpoint: 21,904 equity short positions from 92 funds |
| 2026-04-02 | `/api/short_volume` endpoint | Daily FINRA short sale volume per ticker |
| 2026-04-02 | `fetch_13dg.py` rewrite — edgar library | Removed all custom HTTP/sessions/rate limiting. `edgar.Company(ticker).get_filings()` handles EDGAR access. Two-phase architecture: list (1494 tickers/min) then parse |
| 2026-04-02 | 4-worker parallel fetch | ThreadPoolExecutor, workers do I/O, main thread writes DB |
| 2026-04-02 | Ticker checkpoint table | `fetched_tickers_13dg` — Phase 1 fully resumable |
| 2026-04-02 | `listed_filings_13dg` crash-resilient resume | Phase 1 results persisted to DB; survives process kills between Phase 1 and Phase 2 |
| 2026-04-02 | `--update` flag | `run_update()`: scans EDGAR quarterly indexes since MAX(filing_date), date-based incremental |
| 2026-04-02 | `--workers N` CLI flag | Default 4, configurable |
| 2026-04-02 | Thread-local `requests.Session` | Fixed FD exhaustion crash at ~3,800 tickers (later replaced by edgar library) |
| 2026-04-02 | Exponential backoff on 429s | 10→20→40→80→120s cap, `_retry_edgar()` wrapper |
| 2026-04-02 | Catastrophic regex fix | Purpose regex O(n²) → linear via slice; group members bounded to cover page |
| 2026-04-02 | 2MB filing truncation | Skip proxy statements bundled with 13D that caused 100% CPU hang |
| 2026-04-02 | `compute_flows.py` confirmed | investor_flows table populated; needs re-run after full 13D/G fetch |
| 2026-04-02 | Pre-commit linting | `.pre-commit-config.yaml` with flake8, pylint, bandit hooks |
| 2026-04-02 | Code review bug fixes | `update.py`: dynamic quarter via MAX(quarter), exit code enforcement. `app.py`: Query 2 join on (cik, manager_name) |
| 2026-04-02 | queries.py service layer | 34 query functions extracted from app.py (1,789 lines). app.py reduced to 618 lines |
| 2026-04-02 | export.py | `build_excel()` + Excel style constants extracted (83 lines) |
| 2026-04-02 | run_pipeline.sh hardened | Process guard, phase timestamps, macOS desktop notification |
| 2026-04-02 | Global rate limiter + Phase 2 stall fix | 2 req/s cap, Retry-After parsing, 2 workers for Phase 2, reduced timeouts |
| 2026-04-02 | Phase CLI flags | `--phase1-only`, `--phase2-only`, `--phase3-only` for independent execution |
| 2026-04-02 | Crash handlers | All 7 fetch scripts log to `logs/<script>_crash.log` on unhandled exception |
| 2026-04-02 | Test isolation | `--test` uses `13f_test.duckdb` via `db.py`, write guard prevents production writes |
| 2026-04-02 | Bug 6 + Bug 7 | fetch_market.py upsert (never drops), app.py snapshot switchback monitor |
| 2026-04-02 | Pyflakes cleanup | 31 unused imports removed across 17 scripts |
| 2026-04-02 | SHOW TABLES cached | 6 per-request queries replaced with `has_table()` at startup |
| 2026-04-02 | Ruff + pre-commit config | Replaced flake8 with ruff, documented semgrep status |
| 2026-04-03 | Item 5 — pct_owned regex tuning | 4 new patterns for 13D cover page format. 13G null rate: 4.5%. 13D structural gap addressed |
| 2026-04-03 | Item 9 — Short vs long comparison | `get_short_long_comparison()` + `/api/short_long` endpoint. Matches 13F longs to N-PORT shorts by adviser name |
| 2026-04-03 | Item 10 — Short squeeze signal | `get_short_squeeze_candidates()` + `/api/short_squeeze` endpoint. Squeeze score = short_pct × inst/float ratio |
| 2026-04-03 | Item 23 — Incremental load_13f.py | `--quarter` flag for single-quarter reload, `--staging` support, crash handler |
| 2026-04-03 | Item 27 — app.py quarter centralization | All 6 hardcoded quarter strings replaced with config.py variables (LQ/PQ) |
| 2026-04-03 | N11 — Filer name resolution | `resolve_names.py` 3-pass pipeline: holdings (219 CIKs/12K rows), EDGAR API (353 CIKs/25K rows), 98 filing agents marked. `name_resolved` column added. query6 fallback JOIN. Data quality endpoint updated |
| 2026-04-03 | N-PORT index/ETF merge | 1.6M new rows (4.2M→5.8M), 6,306 series, 98.4% adviser-mapped. Fixed CUSIP→ticker for 2.1M rows |
| 2026-04-03 | market_value_usd 1000x fix | SEC bulk VALUE is in dollars, not thousands. Removed `*1000` from load_13f.py, divided all existing values by 1000. Removed compensating `/1000` in 6 locations |
| 2026-04-03 | FLOW_PERIODS fix | 1Q/2Q were identical (both Q3→Q4). Fixed to 4 distinct periods: 4Q, 3Q, 2Q, 1Q |
| 2026-04-03 | manager_type expansion | 50→110 PARENT_SEEDS + keyword-based fallback classification. NULL rate: 71%→40% |
| 2026-04-03 | pct_of_float fallback | shares_outstanding used where float_shares NULL. NULL rate: 30%→24% |
| 2026-04-03 | fund_classes.quarter fix | Derived from report_date for all 31,056 rows |
| 2026-04-03 | FINRA short interest refresh | 102K→328K rows, 29 dates, 12,511 tickers |
| 2026-04-03 | enrich_tickers.py | +1,076 CUSIPs resolved, Q4 ticker coverage 91.6% |
| 2026-04-03 | Staging support | Added --staging to enrich_tickers.py, auto_resolve.py. fetch_market.py fixed for staging isolation |

---

## FUTURE — Performance & Stability Hardening

| # | Item | Priority | Notes |
|---|------|----------|-------|
| H1 | N+1 query fix — batch children in query1 | Done | 80+ queries → 2 queries. Parents + all 13F children fetched in single batched CTE |
| H2 | Batch yfinance calls in fetch_market.py | Done | Two-pass: batch `yf.download()` for prices (500/batch), then `yf.Tickers()` for metadata |
| H3 | Exception handling in fetch_nport.py executemany | Done | Batch fails → falls back to row-by-row insert with error counting |
| H4 | Incremental N-PORT parsing | Done | `is_already_loaded()` + local XML cache via `download_xml()` already skip loaded filings |
| H5 | Phase 2 accession checkpoint | Done | Already handled via NOT IN query on beneficial_ownership (0.03s) |
| H6 | Connection pooling for Flask | Done | Thread-local connection cache in get_db() — reuses connections across requests |
| H7 | Query result caching | Done | _cached() with 5-min TTL on get_summary. Extensible to other queries |

---

## FUTURE — Data Integrity & On-Demand Updates

| # | Item | Priority | Notes |
|---|------|----------|-------|
| D1 | On-demand single-ticker add — `/api/add_ticker` | Done | POST endpoint: fetches CUSIP (OpenFIGI), market data (yfinance), lists 13D/G filings. Admin UI form included. |
| D2 | Manager change detection | Done | Flag new CIKs, disappeared CIKs, name changes (fuzzy match old→new). Surface in admin UI for review. |
| D3 | Ticker change tracker | Done | Compare securities table across quarters. Cross-reference SEC company_tickers.json. Flag CUSIP→ticker changes (FB→META). |
| D4 | Parent mapping health check | Done | Re-match parent_bridge against ADV data. Log new parent assignments, broken links, orphaned CIKs. |
| D5 | Stale data detection | Done | Tickers with no market data >30 days, managers with no filings >4 quarters, delisted securities. |
| D6 | Merger signal detection | Done | When a CIK stops filing and another CIK's holdings jump, flag as potential merger. Link old→new CIK. |
| D7 | New company alerts | Done | Cross-reference SEC company_tickers.json weekly for new entries. Show which funds are accumulating. |

---

## FUTURE — Admin UI (all pipeline operations via web interface)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| F1 | Admin dashboard — pipeline status, progress bars, log viewer | Done | `/admin` page with DB stats, live Phase 2 progress bar, error log, add-ticker form. Auto-refresh. |
| F2 | One-click monthly update | Done | Button triggers: seed staging → fetch updates → merge → refresh snapshot |
| F3 | Individual script triggers | Done | Dropdown: select script + flags (--update, --staging, --quarter). Start/stop/monitor |
| F4 | Schedule recurring updates | Done | Monthly 13D/G update, weekly FINRA short, daily market data refresh |
| F5 | Staging review before merge | Done | Show merge_staging --dry-run output. Approve/reject before merging to production |
| F6 | Data quality dashboard | Done | Show regex timeout count, missing tickers, pct_owned null rate per batch |
| F7 | Quarter config viewer | Done | Form to add new quarter URLs, snapshot dates. Auto-generates config.py diff |

---

## FUTURE — New Features & Enhancements

| # | Item | Priority | Notes |
|---|------|----------|-------|
| N1 | N-PORT index/ETF fund download | Done | Merged 1.6M new rows (4.2M→5.8M). 6,306 series, 98.4% mapped to advisers. Vanguard 30→96, BlackRock 132→243, Fidelity 281→449 |
| N2 | Short squeeze UI tab | Done | Frontend tab with `/api/short_squeeze`. Shows candidates >15% short, squeeze score, inst % float |
| N3 | Short vs long UI integration | Done | Long/short comparison in Smart Money tab via `/api/short_long`. Shows managers both long+short, short-only funds |
| N4 | Ownership concentration heatmap | Done | Peer Matrix tab replaced with interactive heatmap. `/api/heatmap` endpoint: top 15 managers × selected tickers, colored by pct_of_float. Hover shows value + exact % |
| N5 | Historical flow trend charts | Done | Multi-period flow trend table in Flow Analysis tab. Shows flow intensity (total/active/passive) and churn across all computed periods (4Q/3Q/2Q/1Q) |
| N6 | Manager profile page | Done | `/api/manager_profile` endpoint: top holdings, sector allocation, quarterly trend, summary stats. `loadManagerProfile()` in frontend with back-navigation |
| N7 | Export improvements — Print/PDF | Done | "Print / PDF" button in action bar. Print styles hide UI chrome, optimize table/chart layout for print. Uses browser native print-to-PDF |
| N8 | Webhook/alert system | Low | Configurable alerts: new 13D filing, >5% ownership change, short squeeze threshold crossed |
| N16 | Query consolidation | Done | Fixed missing /api/cross_ownership route. Merged query10+11→Position Changes (entries+exits in one view). Improved query14 with parent grouping. Made query13 sector-generic (accepts ?sector= param). Consolidated Ownership Trend 3→2 sub-views (Summary+Cohort combined, Holder Changes) |
| N9 | 13F-HR amendment reconciliation | Done | `/api/amendments` endpoint: shows managers who filed 13F-HR/A amendments for a ticker. Identifies amended vs original filing status |
| N10 | Multi-quarter position timeline | Partial | Flow trend table added to Flow Analysis. Register tab sparklines deferred — requires query1 modification to return per-quarter share arrays |
| N11 | Filer name resolution pipeline | Done | `resolve_names.py`: 3-pass resolution (holdings→EDGAR API→company_tickers.json). Added `name_resolved` column. 83.9%→90.0% resolved, 10% filing agents marked. `resolve_agent_names.py` extracts reporting person from filing text |
| N12 | Investor name standardization | Done | `normalize_names.py`: smart Title Case for 8.6M rows, 8 table/columns. Handles acronyms, canonical names, dotted abbrevs. ALL CAPS 27%→0% |
| N13 | N-PORT series-level deduplication | Done | All N-PORT rollup queries GROUP BY series_id (MAX per series). get_nport_position, get_nport_coverage, get_nport_children, get_nport_children_q2 all deduplicated. Fidelity NVDA: 1.39B → 1.07B shares after dedup |
| N14 | Geode/Fidelity sub-adviser exclusion | Done | `SUBADVISER_EXCLUSIONS` dict in config.py. Geode excluded from Fidelity rollup. Applied in get_nport_position, get_nport_children, get_nport_children_q2 via `_build_excl_clause()`. Extensible for future sub-advisers |
| N15 | International sub-adviser analysis | Done | Investigated: 183 shared series deduped by N13 (GROUP BY series_id). 83 intl-only series are real fund positions, excluding them loses data. Remaining ~10% excess (Fidelity 110%) is structural: N-PORT uses MAX of monthly snapshots vs 13F quarter-end. Only Fidelity and RBC (2 series) affected. No further exclusions needed |
| N17 | Economic hold period | Medium | Weighted-average hold period per investor based on economic exposure, not binary presence. An investor holding 5M shares for 4 quarters who trims to 100 shares in Q5 should show ~4Q hold period, not 5Q. **Method:** For each investor-ticker pair across all quarters, compute exposure weight = `position_value / peak_position_value`. Hold period = sum of quarterly weights (e.g., 1.0 + 1.0 + 1.0 + 1.0 + 0.002 = 4.0Q). Threshold: ignore quarters where exposure weight < 5% of peak (de minimis). Surface on Register tab as "Held" column and on Conviction tab. Requires: multi-quarter position history per investor (query all quarters in holdings). Consider: cost basis approximation via VWAP for $-weighted hold period |
| N18 | Portfolio positioning analysis — active investors | Medium | For each active investor holding the target company, analyze where the position sits within that investor's portfolio by market cap. **Method:** Pull full 13F portfolio for the investor, compute market cap distribution (25th/50th/75th percentile). Show where the target company's market cap falls relative to the investor's typical range. **Output:** Per-investor row showing: portfolio mkt cap P25/P50/P75, target company mkt cap, percentile rank within their portfolio, position size vs median position. Flag outliers where target is significantly outside the investor's normal mkt cap range (potential conviction signal). **UI:** Table on Conviction or Register tab showing active holders with their portfolio positioning. Visual indicator (dot on range bar) showing where company sits in each investor's mkt cap spectrum |

---

## FUTURE — Pipelines

| # | Item | Priority | Notes |
|---|------|----------|-------|
| P4 | iShares Trust N-PORT | Done | Fetched 3 iShares entities (Trust, Inc, U.S. ETF Trust). +391K ETF holdings. BlackRock NVDA coverage: 6.4% → 42.5%. Fixed ETF exclusion filter in fetch_nport.py |
| P5 | SPDR / State Street N-PORT | Done | Fetched 6 entities (SPDR Series Trust, Index Shares, Select Sector, SS Institutional, SSGA Funds, Navigator). +170K rows. State Street NVDA: 9% → 16.4%. Note: SPY is a UIT, exempt from N-PORT |

---

## PIPELINE 9 — 13D/G Cleanup & Integration

| # | Item | Priority | Notes |
|---|------|----------|-------|
| R1 | Data quality audit — 13D/G `pct_owned` coverage | High | Assess null rate, parsing accuracy across filing types. Check `beneficial_ownership_current` completeness vs EDGAR filing count. Validate against known 5%+ holders (activist lists) |
| R2 | Data quality audit — 13D/G name matching to 13F parents | High | Check how many 13D/G filers match existing `inst_parent_name` in holdings. Identify gaps: individuals, foreign entities, funds below 13F threshold |
| R3 | 13D/G data cleanup — dedup, amendment reconciliation, stale filing removal | High | Deduplicate overlapping filings (same filer, same security). Reconcile amendments (13D/A, 13G/A) to keep only latest effective filing. Remove filings for securities no longer in universe. Standardize filer names to match 13F parent mapping |
| R4 | Schema design — merge 13D/G into Register view | Medium | Decide: separate rows with badge, or enrich existing parent rows with 13D/G reported %. Handle conflicts (13F computed % vs 13D/G self-reported %). Priority: 13D/G % is more authoritative for 5%+ holders |
| R5 | Intent tracking in Register | Medium | Surface 13D vs 13G filing type (activist intent vs passive). Show intent changes (13G→13D = going activist). Link to `prior_intent` column |
| R6 | Threshold crossing alerts | Low | Flag when 13D/G shows new 5%+ holder or existing holder drops below 5%. Timeline of crossings per ticker |

---

## PIPELINE 10 — Monthly N-PORT Update Flow

| # | Item | Priority | Notes |
|---|------|----------|-------|
| M1 | Design monthly update cadence | High | N-PORT filings arrive monthly (60-day lag). Define schedule: which months to fetch, how to detect new filings, incremental vs full refresh. Current fetch_nport.py supports `is_already_loaded()` skip logic |
| M2 | Monthly → quarterly rollup logic | High | N-PORT has monthly snapshots; 13F is quarterly. Define how monthly fund_holdings roll up to quarter-end positions for comparison with 13F parents. Options: use quarter-end month only, or average across 3 months, or MAX (current approach). Document tradeoffs |
| M3 | Fund → parent rollup reconciliation | High | Ensure N-PORT fund positions aggregate correctly to 13F parent totals. Handle: sub-adviser exclusions (Geode/Fidelity), share class dedup (series_id grouping), cross-filing families (Capital Group, American Funds). Quantify gap between N-PORT rollup and 13F reported value per parent |
| M4 | Incremental fund_holdings update script | Medium | Fetch only new filings since last run. Use EDGAR XBRL index or filing date filter. Append to fund_holdings without dropping existing data. Update fund_universe metadata (total_net_assets) from latest filing |
| M5 | Stale fund detection & cleanup | Medium | Identify funds that stopped filing (merged, liquidated, renamed). Flag in fund_universe. Exclude from active cohort analysis. Cross-reference with N-CEN adviser map for fund status changes |
| M6 | Monthly position change tracking | Low | Track month-over-month position changes within a quarter at fund level. Surface intra-quarter trading patterns (e.g., fund bought in month 1, sold in month 3 of same quarter) |

---

## UI/UX Improvements

| # | Item | Priority | Notes |
|---|------|----------|-------|
| U1 | N-PORT coverage disclaimer tooltip | Done | Hover tooltip on "N-PORT Coverage" label in summary card. Dotted underline indicates hoverable. Explains mutual fund + ETF coverage and deduplication |
| U2 | Row numbers on all tables | Done | # column added to all 3 table renderers (renderHierarchicalTable, buildSimpleTable, _flowTable) + Excel export. Parent rows only numbered in hierarchical tables. Children get blank |
| U3 | Top 25 with tier separators and subtotals | Done | Faint border-bottom at rows 10, 15, 20. Bold subtotal rows at 10 and 25 (sums numeric columns). Applied to buildSimpleTable and renderHierarchicalTable. _flowTable gets tier breaks |
| U4 | Nested fund children — limit 5 largest under parent | Done | get_nport_children default limit=5 already in place. Cross-Ownership (query8) doesn't use N-PORT children — pure 13F cross-holder. Consistent across Register, Conviction, Ownership Trend |
| U5 | Institution column width — expand to min 280px | Done | Single CSS rule covers all tabs via `th:nth-child(2)` and `.col-text-overflow`. Fixes truncation on parent names and N-PORT fund series children |
| U6 | ETF/index fund passive classification | Medium | Fund series with "Index", "ETF", "S&P", "Russell", "MSCI" in name incorrectly showing as active. Fix classification in fund_universe. Affects Register, Conviction, Crowding tabs |
| U7 | Flow Analysis — fund-level churn toggle | Medium | Add "By Institution / By Fund" toggle above Row 2 churn charts. Institution = current 13F manager-level churn (default). Fund = N-PORT fund series level churn computed live from fund_holdings. Requires: QoQ fund_holdings comparison query (same quarter pairs as institutional), active-only filter for fund names, fund-level entry/exit counting. Toggle applies to both churn charts simultaneously. Deferred because precomputed `ticker_flow_stats` only has institutional data — fund-level needs live computation or a new precomputed table |
| U8 | Name casing cleanup — Title Case pass | Medium | Many investor and fund names still display in ALL CAPS (e.g., "JPMORGAN ASSET MANAGEMENT" instead of "JPMorgan Asset Management"). N12 (normalize_names.py) fixed 27%→0% ALL CAPS in bulk, but new data loads and some edge cases reintroduce uppercase names. Need: re-run normalize_names.py on latest data, add Title Case normalization to the load pipeline so new data arrives clean, handle acronyms (ETF, LLC, LP, SPDR, iShares) and known canonical forms (BlackRock not Blackrock, JPMorgan not Jpmorgan). Affects all tabs — Register, Conviction, Flow, Cohort, Momentum |
| U10 | Extend FINRA short volume lookback to 90+ days | Medium | Current fetch_finra_short.py only pulls ~29 days. Re-run with wider date range to support 90-day trend chart on Short Interest tab. Consider fetching 6 months for longer-term context |
| U11 | Source true short interest (shares shorted as % of float) | Low | FINRA daily volume is a poor proxy for actual short interest. True SI is reported bi-monthly by NYSE/NASDAQ. Options: scrape exchange reports, use commercial API (S3 Partners, Ortex), or derive from FINRA RegSHO threshold list. Would enable days-to-cover calculation and proper squeeze scoring |
| U12 | Short analysis cross-ref matching improvement | Medium | Long/short cross-reference on Short Interest tab uses naive family name matching. Many misses (Hartford funds → Hartford Funds parent not found). Need: use match_nport_family patterns, fall back to fuzzy matching, handle sub-adviser relationships (same patterns as Register tab fund matching) |
| N21 | Data quality audit — manager_type and fund_universe.is_actively_managed | High | Both fields drive Active Only filters across Register, Cohort, Conviction, and Short Interest tabs. Need audit to confirm: (1) fund_universe.is_actively_managed has 99.9% coverage but is the classification accurate? Spot-check known index funds vs active funds. Check how it's derived in fetch_nport.py/build_fund_classes.py. (2) holdings.manager_type has gaps — measure NULL rate and classification accuracy. Spot-check known passive managers (Vanguard Group, SSgA) vs active (Wellington, Capital Group). Check PARENT_SEEDS mapping in build_managers.py. Fix misclassifications in the source tables so all tabs get consistent filtering |
| N20 | Fill sector/industry data gaps (Unknown reduction) | High | 30% of tickers in market_data have NULL sector (1,804 of 6,021). Holdings-level: 26% of Q4 positions lack sector. Affects Conviction, Sector Rotation, and any sector-weighted analysis. **Plan:** (1) Re-fetch from yfinance for tickers that previously failed, (2) Fall back to SEC SIC codes via company_tickers.json for US tickers still missing, (3) Use OpenFIGI BICS classification for the remainder, (4) Manual override table for known problem tickers (ADRs, SPACs, recent IPOs), (5) Add to enrichment pipeline so new tickers get sector on arrival. Target: <5% Unknown coverage. Also fix Yahoo taxonomy quirks: REITs currently under "Financial Services" should move to "Real Estate"; some BDCs, LPs miscategorized |
| N19 | Full investor portfolio concentration review | Medium | Dedicated tab for deep-dive into a specific investor's full portfolio. Shows: complete sector breakdown as horizontal bar chart, top holdings ranked, HHI concentration index, top 10 vs rest ratio, sector peers within each sector (e.g., their full Energy book), overweight/underweight vs benchmark (S&P 500 sector weights), quarterly sector rotation trend (% changes across quarters). Triggered by clicking an investor name from Register, Conviction, or Fund Portfolio tabs. Separates the per-holder deep dive from the cross-holder Conviction tab which only shows summary columns |
| U9 | Summary dashboard tab | Medium | New tab (or landing view) with visual charts summarizing key analysis for a ticker at a glance. Candidates: (1) Ownership composition donut — active/passive/hedge/other by value, (2) QoQ share change waterfall — retained + new - exits = current, (3) Top 10 holders horizontal bar ranked by % float, (4) Active share retention trend sparkline (last 3 quarters), (5) Flow intensity mini bar chart (same as Flow tab but inline), (6) Short interest vs institutional ownership scatter or dual-axis chart, (7) Holder count trend line across quarters. Goal: one-page executive view before drilling into individual tabs. Should load fast — pull from precomputed summary tables where possible. Consider making this the default landing view when a ticker is entered |

---

## SEQUENCE — NEXT STEPS

1. ~~N-PORT index/ETF download + merge~~ Done
2. ~~Data quality fixes (market_value, manager_type, flows, pct_of_float)~~ Done
3. ~~FINRA short interest refresh + enrich_tickers~~ Done
4. **Retry `fetch_market.py --staging`** when Yahoo rate limit resets (fills snapshot prices + 420 missing tickers)
5. ~~N12 — Investor name standardization~~ Done
6. ~~N2 — Short squeeze UI tab~~ Done
7. ~~N3 — Short vs long UI integration~~ Done
8. ~~N13 — N-PORT series-level deduplication~~ Done
9. ~~N14 — Geode/Fidelity sub-adviser exclusion~~ Done
10. ~~U1 — N-PORT coverage disclaimer tooltip~~ Done
11. ~~P4 — iShares Trust N-PORT~~ Done
12. **N15 — International sub-adviser deduplication** (Fidelity HK/Japan/UK inflate to 110%)
13. **R1/R2/R3 — 13D/G data quality audit + cleanup** — assess pct_owned coverage, name matching, dedup amendments, standardize filer names
14. **M1/M2/M3 — Monthly N-PORT update flow design** — define cadence, monthly→quarterly rollup, fund→parent reconciliation
15. R4-R6 — 13D/G Register integration (pending R1-R3 results)
16. M4-M6 — Incremental N-PORT update implementation
17. Refresh readonly snapshot
18. Items N4-N10 as capacity allows
