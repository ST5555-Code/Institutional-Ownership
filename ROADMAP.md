# 13F Institutional Ownership Database — Roadmap

_Last updated: April 9, 2026 (end of pre-Phase 4 session — all items complete, Phase 4 authorized)_

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
| 42 | Entity MDM — Phases 1-3 complete on staging, see ENTITY_ARCHITECTURE.md | Staging complete, awaiting Phase 4 merge | Phase 3: 5,293 long-tail CIKs resolved via SEC EDGAR (100% retrieval), 153 parent matched, 104 SIC classified, 181 aliases added. resolve_long_tail.py + entity_sync extensions. 13 validation gates (8 PASS, 5 MANUAL, 0 FAIL). |
| 43 | Fix pre-existing app.py lint debt | Done | flake8: 116→0. bandit B608: 28→0 (`.bandit` config). 17 bare `except Exception:` → `as e` + `app.logger.debug()`. `setup.cfg` added. Pre-commit unblocked. |
| 43c | Review LOW + MEDIUM confidence classifications 1-by-1 | High | ~1,095 LOW + ~2,000 MEDIUM confidence entities remain. >$10B entities reviewed and fixed this session (177 LOW >$10B cleaned). Remaining are <$10B each. Need: manual review with ADV data cross-reference, industry knowledge. Priority: hedge_fund MEDIUM (500+ entities, many ADV-sourced), active default_active (1,500+), mixed ticker_count (200+). Consider: export to CSV for manual classification, crowd-source with industry databases. |
| 43f | Review parent_seeds for passive misclassifications | Done | Moved 63 pension funds ($1.2T), 41 insurance cos ($0.2T), 2 endowments ($36B) from passive to correct categories. Passive now 45 entities = pure index/ETF providers. | parent_seeds contains pension funds, insurance companies, and endowments mixed in with index providers. Pension funds (CalPERS, HOOPP, state retirement systems) and insurance (State Farm, Zurich, Cincinnati) are classified as passive because their parent_seeds strategy_type is passive — but they're not passive index managers. Need to separate: (a) index providers/ETF issuers (Vanguard, BlackRock, SSGA, Geode) = passive, (b) pension/insurance = pension_insurance, (c) endowments = endowment_foundation. Also review fund-level: many pension/insurance funds hold index ETFs (correctly passive at fund level) but the manager should be pension_insurance. |
| 43e | Family office classification | Medium | Currently family offices are split between hedge_fund (Soros, Moore, ICONIQ — active style) and strategic (Longview, Briar Hall, Consulta, Allen — concentrated). A separate `family_office` manager_type would improve accuracy. Requires: curated list of known family offices, ADV cross-reference (many register as exempt reporting advisers). |
| 43d | Fund-level classification cleanup | Done | L1 fund_strategy: 895 NULL series classified (231 passive, 744 active via keyword + fund_universe fallback). 295 conflicts resolved: 55 active→passive (ProShares leveraged ETFs, MML index), 240 passive→active (AQR, AB, Avantis — false keyword matches). entity_classification_history synced. Zero NULLs, zero conflicts with fund_universe. Richer manager types (hedge_fund, quantitative) structurally absent from N-PORT — only registered funds file. |
| 43h | CIK-level type differentiation | Done | `entity_type` column on holdings_v2: per-entity classification from entity_classification_history + ADV strategy enrichment. 1,245 entities reclassified ($11.7T AUM). Key moves: $3.3T active→hedge_fund, $2.6T mixed→active, $1.5T wealth→active. Active Only filter now uses entity_type instead of parent-inherited manager_type. |
| 43g | Drop redundant type columns — migrate queries | Medium | Two redundant columns to deprecate after full classification chain cleanup: (1) `fund_universe.is_actively_managed` → replace with `fund_strategy` (14 query refs), (2) `holdings_v2.manager_type` → replace with `entity_type` (65 remaining refs in SELECT/GROUP BY/display). Also update `build_managers.py` pipeline to write `entity_type` instead of `manager_type` on new data loads. Single pass after L1-L5 audit complete. |
| 43b | app.py remaining hardening | Low | B110: 8 try-except patterns now log but still swallow (review if any should surface errors). B603/B607: subprocess calls in admin endpoints — consider allowlist validation. B104: Flask bind `0.0.0.0` — restrict to localhost for production. |
| 44 | Entity MDM Phase 3.5 — ADV ownership | Done | 3,585 CRDs parsed (98.2%), 26,822 rows, 1,059 relationships. Dual-parser: pymupdf primary (88.3% recall, 99.5% accuracy, 20 min) + pdfplumber fallback. `--refresh` mode for updates (4 workers). QC report, manual adds, interactive review HTML. See ENTITY_ARCHITECTURE.md. |
| 45 | PyMuPDF parser for ADV | Done | 100-400x faster than pdfplumber. 88.3% recall, 99.5% accuracy, +1,151 net entities. Handles all oversized PDFs. Used as primary in `--refresh` mode. pdfplumber retained as fallback. |
| 46 | ADV pipeline hardening | Done | Atomic SCD, deterministic matching, duplicate staging guard, PDF validation, explicit checkpoint, alias cache reuse, evidence resolution policy, scan-based ownership code extraction, expanded match universe (all aliases). |
| 47 | Interactive entity review tool | Done | `data/reference/adv_entity_review.html` — 1,926 unresolved CRDs, 20,416 searchable aliases, pre-populated recommendations, export to `adv_manual_adds.csv`. |
| 48 | Phase 3.5 deferred items | Partially done | D1 ✅ (accuracy audit), D7 ✅ (oversized pass). Remaining: D2 (pymupdf recall 88→95%), D4 (match quality benchmark), D5 (IAPD API), D10 (admin UI), D11 (auto-promoter). |
| 49 | D1 accuracy audit | Done | 90 PDFs, 6 strata. 75% parser agreement, zero false positives. Pymupdf recall gap = Schedule B indirect owners. |
| 50 | Entity review complete | Done | 1,926 CRDs triaged: 99 wired to parents, 1,827 confirmed independent. 12 new entities created. 174 orphan subsidiaries consolidated. DBA/legal name check added to QC. |
| 51 | Phase 4 — Migration | Stage 4 complete | Cutover 2026-04-09. App running on entity-backed v2 tables. 100% entity/rollup coverage, 0.00% AUM diff, 8/8 parity gates pass, zero 500 errors. Shadow log clean. Original tables retained for 30-day rollback. Stage 5 cleanup scheduled on or after 2026-05-09 — requires explicit authorization. |
| 52 | Phase 4 post-cutover: brand 13F consolidation | Done | T. Rowe Price: 3 fragments (eid=3616, 13, 17924) consolidated under eid=3616 ($1,013B + 32K N-PORT). MFS: fund entities flattened from eid=5047→eid=17 ($287B + 15K N-PORT). Neuberger Berman: was rolling to Man Group (wrong), fixed to eid=55 ($129B + 1.8K N-PORT). HSBC: no fragmentation found. |
| 53 | Post-Phase 4: 13D/G entity coverage | Done | Added 51 CIK identifiers for 13D/G filers matched by name to existing entities. Coverage: 53.7% → 77.1% (+23.4pp). Remaining unmatched are individuals, fund-level CIKs, and small filers without entity entries. |
| 54 | Post-Phase 4: Voya rollup wiring fix | Done | Voya (eid=1591) set to self-rollup. Was rolling to VVR Holdings (eid=2110). Display name cleaned to "Voya Investment Management". |
| 55 | Post-Phase 4: 13D/G exit validation | Done | 381 exits with pct=0% but shares>0 fixed (shares set to 0). beneficial_ownership_current rebuilt: 13,799 with prior_intent, 166 intent changes detected (92 passive→activist, 74 activist→passive). crossed_5pct flag validated: 22,349 crossed, 6,810 subsequently reduced below 5%. Exit validation confirmed correct for direct filer CIKs (4/4 verified against EDGAR). Filing agent CIK gap (902664, 1213900, 1341004) cannot be verified via standard EDGAR index path — requires filer CIK lookup. Deferred to beneficial_ownership entity coverage expansion item (#53). |

---

## COMPLETED

| Date | Item | Details |
|------|------|---------|
| 2026-04-09 | Item 2 — Filing agent name resolution | `resolve_bo_agents.py`: dual-source (EFTS primary + SEC .hdr.sgml fallback) with auto-failover after 10 consecutive failures. Incremental UPDATE + CHECKPOINT every 500 rows. Restart-safe (WHERE clause skips resolved rows). 14,870 agent rows → 100% resolved. |
| 2026-04-09 | Item 9 — Final pre-Phase 4 validation | ALL GATES PASS. beneficial_ownership: 51,905 rows clean. holdings: 14 categories, 0 NULL, $67.3T. parent_bridge: 0 dupes. fund_classification: 5,717 series. Entity tables: 20K entities, 13.7K relationships. READY FOR PHASE 4. |
| 2026-04-09 | Item 8 — Investor type classification (full review) | Manager-level: NULL 787→0 via 6 sources (parent_seeds, adv_strategy, ticker_count, keyword, manual_review, default_active). Fund-level: 6,325 series classified (passive 1,056 $12.6T, active 4,845 $10.2T, mixed 424 $3.1T). S&P500 overlap + 8-index cross-validation. 210 funds reclassified by multi-index correlation. New: fund_classification, index_proxies, fund_index_scores tables. |
| 2026-04-09 | Item 7 — app.py lint debt | flake8 116→0, bandit B608 28→0, 17 bare exceptions → as e + logging. setup.cfg + .bandit config. |
| 2026-04-09 | Item 6 — R1/R2/R3 13D/G data quality audit | R1: 13G null 4-5% (good), 13D 96-98% (structural). 34 outliers >100% nullified, avg corrected 3,880%→8.61%. R2: 12.3% match 13F parents (expected — individuals/small funds). R3: 8,227 duplicates removed (60,135→51,908). 0 remaining. |
| 2026-04-09 | Item 5 — Fidelity intl sub-adviser dedup verification | Confirmed N13/N14/N15 all working: series-level dedup (GROUP BY series_id + MAX) in 4 queries, Geode exclusion active, 174 shared series correctly handled. ~116% ratio is structural (monthly MAX vs quarter-end). No code changes needed. |
| 2026-04-09 | Item 4 — Top 50 self-rollup verification | Capital Group: unwired 44 false matches, consolidated $1.9T (Capital World $735B + Capital International $638B). Franklin Templeton +ClearBridge +advisers = $533B. Ameriprise +Columbia Threadneedle = $443B. MFS consolidated $310B. BMO $289B. PGIM +Jennison = $256B. parent_bridge deduplicated 12,005→11,135. |
| 2026-04-09 | Item 3 — International parent entities | 77 rows wired in parent_bridge across 10 groups: Amundi ($368B, 14), MUFG AM ($190B, 4), Sumitomo Trust ($183B, 4), Allianz AM ($99B, 10), Natixis IM ($28B, 5), Macquarie ($23B, 3), Nikko AM ($17B, 4), BNP Paribas AM (7), Daiwa (8), AXA IM (6). Banks/insurance/brokers left independent per operating AM rollup policy. |
| 2026-04-09 | Process rules for large-data scripts | `docs/PROCESS_RULES.md`: 9 rules — incremental save, restart-safe design, multi-source failover, rate limiting per endpoint, error thresholds (>5% = STOP, 1-5% = WARN), progress reporting, dry-run default. Applies to all future batch/fetch scripts. |
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
| 2026-04-05 | fetch_market.py rewrite (H8-H11) | Bypassed yfinance entirely via new `yahoo_client.py` (direct curl_cffi to Yahoo's JSON API). Added `sec_shares_client.py` for authoritative shares outstanding from SEC XBRL (EntityCommonStockSharesOutstanding + EntityPublicFloat, from 10-K/10-Q covers, 90-day cache). New incremental update protocol: prices 7d / metadata 30d / SEC 90d staleness thresholds; `--force`, `--missing-only`, `--metadata-only`, `--sec-only`, `--limit` flags. Ticker pre-filter flags bonds/warrants/preferreds/FX-suffix as unfetchable. pct_of_float now uses SEC shares_outstanding as primary source. Schema additions: unfetchable, unfetchable_reason, metadata_date, sec_date, public_float_usd, shares_as_of, shares_form, shares_filed, cik. |
| 2026-04-06 | Sector Rotation tab redesign (H15) | Multi-quarter institutional money flow analysis by GICS sector. Financial-statement layout showing active dollar flows (shares × price, stripping price effects) across all quarter transitions. Expandable detail: top 5 net buyers/sellers per sector per quarter. By Parent/By Fund + Active Only toggles. Pre-aggregated holdings prevent cross-product inflation. Short Squeeze tab removed (broken SQL + stale data). |
| 2026-04-06 | Period-accurate pct_of_float (H14) | New `shares_outstanding_history` table (317K facts, 4,450 tickers). DuckDB ASOF JOIN matches each holding to period-correct SEC shares. GOOGL 2020 pct_of_float corrected from 0.4% to 7.3% (20:1 split). `build_shares_history.py` script with `--update-holdings` flag. |
| 2026-04-06 | Peer Rotation tab | Per-ticker substitution analysis within sector. Shows subject vs sector flow summary with grouped bar chart, substitution waterfall chart (top 5 peer swaps), industry + broader sector peer tables with expandable entity detail, top 5 sector movers with horizontal bar chart, and top 10 entity rotation stories. Three Chart.js charts. By Parent/By Fund + Active Only toggles. N-PORT fund-level support. New `get_peer_rotation()` + `get_peer_rotation_detail()` in queries.py, `/api/peer_rotation` + `/api/peer_rotation_detail` endpoints. |
| 2026-04-07 | Phase 3.5 parse hardening | Memory leak fix (4.5GB→300MB), parallel parse (4 workers), SIGALRM timeout (180s), crash resilience (checkpoint file, SIGTERM handler, temp CSV recovery), progress logging. 6 bug fixes: atomic SCD, deterministic matching, duplicate staging guard, PDF validation, explicit checkpoint, alias cache reuse. |
| 2026-04-07 | Phase 3.5 full parse run | 3,026 PDFs parsed in 9.8h (4 workers, pdfplumber). 21,695 rows, 833 relationships. |
| 2026-04-07 | Phase 3.5 parser fixes | Scan-based ownership_code extraction, expanded match universe (all aliases not just rollup parents), evidence resolution policy (ADV supersedes legacy at score ≥90). Match: 12→895 owners, 8→833 relationships. |
| 2026-04-08 | PyMuPDF parser | 100-400x faster. 88.3% recall, 99.5% accuracy vs pdfplumber. Parsed all 112 oversized PDFs in 391s (pdfplumber: 0 in 8h). 15,902 new rows. Full coverage: 3,585 CRDs (98.2%). |
| 2026-04-08 | Phase 3.5 match on full data | 1,059 ADV relationships in DB (350 wholly_owned primary, 157 mutual_structure, 56 parent_brand). 825 JV structures. SCD integrity: 0 broken. |
| 2026-04-08 | --refresh mode + QC + manual adds | Dual-parser pipeline (pymupdf primary → pdfplumber fallback, 4 workers, ~25 min). QC report (1,926 CRDs with 0 entity owners). Manual adds via CSV. Interactive review HTML (1,926 items, 20,416 searchable aliases). |
| 2026-04-08 | External review import | 17 high-confidence + 20 medium corporate parents wired. 12 new parent entities created (Pacific Life, Stowers Institute, TA Associates, Virtus, Himalaya Capital, F-Prime, etc.). Total: 36 manual relationships, $3.8T AUM covered. |
| 2026-04-08 | Orphan subsidiary scan | Full dataset scan: 11,644 self-rollup entities vs 866 parents. 174 orphans wired (Dimensional $836B, Lord Abbett $270B, Thornburg $45B, 150+ others). Firm identity verification prevents false merges. |
| 2026-04-08 | Entity review complete | 1,926 unresolved CRDs triaged: 99 wired, 1,827 confirmed independent. Baillie Gifford Overseas ($163B) → Baillie Gifford & Co. |
| 2026-04-08 | D1 accuracy audit | 90 PDFs, 6 strata. Zero false positives. 75% parser agreement on comparable files. Pymupdf recall gap = Schedule B indirect owners. |
| 2026-04-08 | DBA/legal name check | 236 firms flagged where firm_name ≠ legal_name. Integrated into --qc pipeline. Catches holding company structures missed by ADV parser. |
| 2026-04-08 | Name normalization | Corp/Corporation, Inc/Incorporated, Co/Company standardized before fuzzy matching. BNY Mellon 83→100, Franklin Resources 83→97. |
| 2026-04-08 | Phase 3.5 complete | 12,862 relationships, 20,205 entities. All deferred items (D1, D7) resolved. Phase 4 ready to scope. |
| 2026-04-08 | N-PORT orphan cleanup | 858 of 920 orphan fund series wired (99.3%). BlackRock/iShares 278, SPDR 80, Fidelity 67, Allspring 27, and 30+ others. $337B → $2.4B remaining. |
| 2026-04-08 | Rollup chain flatten + circle fix | 23 circular pairs broken (Vanguard↔Vanguard Group Inc, etc.). All multi-level chains flattened to one-hop. Zero remaining chains. |
| 2026-04-08 | Classification sync | 974 unknowns classified from ADV strategy_inferred. 204 corrections (active→hedge_fund/PE). 5 PE misclassifications fixed. Unknown: 7,607→6,633. |
| 2026-04-08 | Operating AM rollup policy | Only asset managers as rollup targets. PE, insurance, foundation, VC unwired: Stowers (117 children), Pacific Life (63), TA Associates (40), DAG Ventures (3). |
| 2026-04-08 | Final data quality audit | 0 chains, 0 circles, 0 SCD breaks, 0 multi-primary, 0 orphan rels, 0 duplicate IDs, 0 pending staging. 13,541 active relationships. |

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
| H8 | fetch_market.py rewrite — bypass yfinance | Done | yfinance 1.2.0 ignores `session=` param; internal requests hit YFRateLimitError at scale. New `scripts/yahoo_client.py` hits `/v7/quote`, `/v10/quoteSummary`, `/v8/chart` directly via curl_cffi with chrome impersonation. No rate limiting. 1,079 symbols/sec on batch quote. |
| H9 | SEC XBRL shares outstanding | Done | `scripts/sec_shares_client.py` pulls `EntityCommonStockSharesOutstanding` + `EntityPublicFloat` from SEC companyfacts. Sourced from 10-K/10-Q cover pages — authoritative. 90-day cache on disk per CIK. `pct_of_float` now prefers SEC shares_outstanding over Yahoo float_shares. **`market_cap` is computed as `shares_outstanding (SEC) × price_live (Yahoo)`** — Yahoo's marketCap field is never written. NULL if either input is missing (no silent fallback). |
| H10 | Ticker pre-filter for Yahoo | Done | `classify_unfetchable()` flags bonds (" " in ticker), warrants (WT/-WT/WS suffix), preferreds (-P*), class markers (*), FX-suffixed foreign OTC. Persisted as `market_data.unfetchable` + reason. Skipped on future runs. |
| H11 | Incremental update protocol | Done | fetch_market.py defaults to incremental: skip prices <7d old, metadata <30d, SEC shares <90d. New flags: `--force`, `--missing-only`, `--metadata-only`, `--sec-only`, `--limit N`. Schema additions: `metadata_date`, `sec_date`, `public_float_usd`, `shares_as_of`, `shares_form`, `shares_filed`, `cik`, `unfetchable`, `unfetchable_reason`. |
| H12 | Migrate remaining yfinance callers to yahoo_client | Done | All 6 scripts migrated: `refetch_missing_sectors.py`, `approve_overrides.py` (also fixed latent `FROM d` bug), `enrich_tickers.py`, `build_cusip.py`, `auto_resolve.py` (3 call sites), `app.py` `/api/add_ticker`. Zero `yfinance` imports remain in `scripts/`. yfinance dependency can be dropped from requirements. Along the way: added `long_name`/`short_name` to YahooClient.fetch_metadata, added `us-gaap:CommonStockSharesOutstanding` + `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` fallbacks to SECSharesClient (for multi-class filers like GOOGL/META/F/CMCSA), 2-year staleness guard on SEC facts (rejects BRK's 2011 legacy record), new `market_data.shares_source_tag` column for provenance, and `data/reference/shares_overrides.csv` for filers with broken XBRL (Visa, BRK-A/B). |
| H13 | merge_staging.py column-swap bug | Done | Root cause: `merge_table()` built INSERT using staging's column order (positional), causing value corruption when staging and production had the same columns in different order. Hit during 2026-04-05 market_data merge — `cik` and `shares_source_tag` values were swapped in production after first merge. Fix: explicit named columns on both sides of `INSERT INTO t (cols) SELECT cols FROM staging_db.t`, with intersection of staging and production column sets (schema-drift tolerant). Regression test added. |
| H14 | Period-accurate pct_of_float (historical shares outstanding) | Done | Previously `holdings.pct_of_float` used `market_data.shares_outstanding` (latest) as denominator for ALL historical quarters — materially wrong across splits, buybacks, offerings. GOOGL 2020Q1 was 18× off; TSLA 2019Q4 20× off; AAPL 2020Q1 3.4× off. New `shares_outstanding_history` table populated from SEC XBRL (all facts, not just latest) via `scripts/build_shares_history.py`. New `SECSharesClient.fetch_history()` method iterates all share facts from local companyfacts cache with same tag-preference fallback as `fetch()`. Holdings update uses DuckDB ASOF JOIN on `strptime(report_date, '%d-%b-%Y')::DATE >= soh.as_of_date`. 317K historical facts across 4,450 tickers, 70% of (ticker, report_date) pairs match to SEC history. Fallback to latest market_data shares for tickers without SEC XBRL coverage. `market_data.shares_outstanding` retains "latest" semantic for current market_cap calculation. |
| H15 | Sector Rotation tab redesign | Done |
| H16 | Pre-computed entity×ticker flow cache | Not started | `sector_flows_cache` table: entity, ticker, sector, industry, q_from, q_to, active_flow, manager_type. Materialized once after each pipeline run (post merge_staging or fetch_market). Eliminates per-request CTE recomputation for both Sector Rotation and Peer Rotation tabs. Both 13F (cik/inst_parent) and N-PORT (series_id/fund_name) levels. Responses drop from seconds to milliseconds. Build as pipeline step in `compute_flows.py` or standalone script. | Replaced old query13 (buyer/seller counts) with multi-quarter institutional money flow analysis. Shows active dollar flows by GICS sector across all quarter transitions in financial-statement layout (one row per sector, columns per quarter, green/red). Strips price effects via `active_flow = (shares_cur - shares_prior) × implied_price`. Expandable detail per sector/quarter: top 5 net buyers + top 5 net sellers. By Parent / By Fund toggle + Active Only filter. Pre-aggregates holdings per (cik, ticker, quarter) to prevent cross-product inflation. Short Squeeze tab removed (broken + stale data). New endpoints: `/api/sector_flows`, `/api/sector_flow_movers`. Old query13 + QUERY_COLUMNS[9]/[13] removed. |

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
| R1 | Data quality audit — 13D/G `pct_owned` coverage | Done | Item 6: 13G null 4-5% (good). 13D null 96-98% (structural — cover page layout). 34 outliers >100% nullified. See R7 for 13D parser fix. |
| R2 | Data quality audit — 13D/G name matching to 13F parents | Done | Item 6: 12.3% match (591 filers). 87.7% unmatched expected: ~1,976 individuals, ~639 funds/trusts, ~32 law firms, ~5 agents. See R8 for entity linking. |
| R3 | 13D/G data cleanup — dedup, amendment reconciliation, stale filing removal | Done | Item 6: 8,227 duplicates removed (60,135→51,908). ROW_NUMBER dedup keeps latest per filer/ticker. |
| R7 | 13D/G full data quality pass — shares + pct | Done | Multi-pass: (1) `reparse_13d.py` 7,271 13D filings re-parsed, pct 96%→6.3%. (2) `reparse_all_nulls.py` 3,330 remaining filings (13G+13D) with improved patterns for compact/colon formats. (3) 2,333 suspect shares QC'd and re-parsed. (4) 1,117 exit filings (pct=0%) marked shares=0. (5) 168 shares computed from pct×outstanding. (6) 159 shares cross-validated from 13F holdings. Full rescan of 928 suspect rows: 908 shares + 55 pct corrected. 3 duplicate pairs resolved. 5 manual pct fixes from filing text. Final: 51,905 rows, pct_null=0, shares_null=1, duplicates=0, range errors=0. DATA QUALITY: CLEAN. All 3 parser scripts synced (12 pct + 8 shares patterns, QC gates, enhanced clean_text). |
| R7b | 13D amendment backfill | Done | Same-filer+ticker backfill from most recent non-null filing. 13D: 215 pct + 67 shares backfilled (96%→3.4% pct null, 16.5%→2.8% shares null). 13G: +214 pct + 322 shares. All types now 2-3.5% null. |
| R9 | Foreign filer format parser (HM Treasury) | Done | 37 HM Treasury/NWG TR-1 filings parsed — pct_owned extracted from "Resulting situation" field. All 37 pct fixed. Shares still null (TR-1 reports disposals not holdings; would need pct × shares_outstanding). |
| R10 | Residual filing agent name resolution | Done | 5,128 of 5,130 agent/law-firm filer names resolved to actual beneficial owners via .hdr.sgml headers. Edgarfilings Ltd (995), Adviser Compliance (870), Advisor Consultant (650), Olshan (629), Seward & Kissel (476), etc. 2 Foley & Lardner rows unresolved. |
| R8 | 13D/G filer → entity linking for non-13F filers | Medium | 4,223 unique filers in beneficial_ownership_current have no parent_bridge entry: ~1,976 individuals, ~639 funds/trusts, ~32 law firms. Phase 4 entity_id FK will cover the 591 institutional matches; the rest need entity_ids as individuals/small filers. Not blocking Phase 4 but improves activist tab. |
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
| N22 | Validate benchmark_weights against external source | Medium | We derive US market sector weights from Vanguard Total Stock Market Index Fund (S000002848) N-PORT holdings, per quarter. Need periodic validation against external sources to confirm accuracy. Options: (1) Fetch iShares ITOT or Schwab SCHB sector weights and cross-check, (2) Scrape S&P 500 sector weights from S&P factsheet and compare (will differ since SPX vs total market), (3) Pull sector ETF AUM (XLK/XLF/XLE/etc.) as an alternate benchmark, (4) Add a validation report to the quarterly pipeline showing weight deltas between our derived values and external sources. Flag any sector with >1pp deviation for review. Current Q4 2025 weights: TEC 33.5%, FIN 13.3%, CND 10.9%, COM 9.5%, HCR 9.5%, IND 8.8%, CNS 4.6%, ENE 3.1%, REA 2.6%, UTL 2.3%, MAT 1.8% — need external confirmation these are reasonable |
| N21 | Investor type classification overhaul (audit + rebuild) | **In Progress** | **Key finding:** ALL investor type classifications in the system are DERIVED BY US, not from SEC. **Sub-item DONE (2026-04-05): fund_universe.is_actively_managed backfilled.** The field was hardcoded to `true` for every fund by `fetch_nport.py` classify_fund(). Created `scripts/fix_fund_classification.py` to backfill via name-pattern keyword matching (INDEX, ETF, SPDR, iShares, S&P 500, Russell, MSCI, etc.). Ran in staging, verified spot-checks, merged to production. Result: 6,671 funds → 5,636 active / 1,035 passive (was 6,671 / 0). Also fixed fetch_nport.py so new data arrives correct — classify_fund now returns `not is_passive_name` for is_actively_managed. **Still TODO:** (a) holdings.manager_type — 40% NULL rate from PARENT_SEEDS gap, (b) managers.strategy_type, (c) adv_managers is_activist, (d) classification source/confidence audit column, (e) PARENT_SEEDS expansion 50 → 250, (f) spot-validate 100 largest holders across 10 benchmark tickers |
| N23 | Document classification methodology in user docs | Done | Updated OneDrive platform documentation (20260404): added "Data Classification Methodology" section explaining all types are derived by us, not SEC. Documented 5 classification sources (entity_classification_history, ADV strategy, parent_seeds, keywords, defaults), entity_type vs manager_type distinction, confidence levels, known gaps. Added caveats to Type column description. Updated database architecture for Phase 4 v2 tables and entity MDM. Created `docs/CLASSIFICATION_METHODOLOGY.md` developer reference. |
| N20 | Fill sector/industry data gaps (Unknown reduction) | Done | Reduced from 30.0% → 1.4% missing across 3 phases: (1) ETF detection via securities.security_type_inferred + curated known-ETF list of 249 tickers — caught 956 ETFs, (2) yfinance refetch for 848 non-ETF missing — recovered 328, (3) Expanded ETF pattern matching via issuer names + preferred/warrant parent inheritance + derivative tagging + targeted yfinance pass on residual — recovered 434 more. Final: 4,563 real GICS sectors (75.8%), 1,276 ETF-tagged (21.2%), 96 Derivative-tagged (1.6%), 86 still missing (1.4%). Remaining are edge cases: delisted tickers, SPAC units, fund wrapper codes (XEVVX, XBOEX), preferred shares without parents. REIT handling added via industry keyword match. Exported to 20260405_missing_sectors_final.csv for manual review |
| N19 | Full investor portfolio concentration review | Medium | Dedicated tab for deep-dive into a specific investor's full portfolio. Shows: complete sector breakdown as horizontal bar chart, top holdings ranked, HHI concentration index, top 10 vs rest ratio, sector peers within each sector (e.g., their full Energy book), overweight/underweight vs benchmark (S&P 500 sector weights), quarterly sector rotation trend (% changes across quarters). Triggered by clicking an investor name from Register, Conviction, or Fund Portfolio tabs. Separates the per-holder deep dive from the cross-holder Conviction tab which only shows summary columns |
| U9 | Summary dashboard tab | Medium | New tab (or landing view) with visual charts summarizing key analysis for a ticker at a glance. Candidates: (1) Ownership composition donut — active/passive/hedge/other by value, (2) QoQ share change waterfall — retained + new - exits = current, (3) Top 10 holders horizontal bar ranked by % float, (4) Active share retention trend sparkline (last 3 quarters), (5) Flow intensity mini bar chart (same as Flow tab but inline), (6) Short interest vs institutional ownership scatter or dual-axis chart, (7) Holder count trend line across quarters. Goal: one-page executive view before drilling into individual tabs. Should load fast — pull from precomputed summary tables where possible. Consider making this the default landing view when a ticker is entered |

---

## SEQUENCE — NEXT STEPS

1. ~~N-PORT index/ETF download + merge~~ Done
2. ~~Data quality fixes (market_value, manager_type, flows, pct_of_float)~~ Done
3. ~~FINRA short interest refresh + enrich_tickers~~ Done
4. ~~Retry `fetch_market.py --staging` when Yahoo rate limit resets~~ Done (2026-04-05) — root cause was yfinance 1.2.0 ignoring passed sessions; bypassed via direct curl_cffi client (H8). SEC XBRL added for authoritative shares outstanding (H9).
5. ~~N12 — Investor name standardization~~ Done
6. ~~N2 — Short squeeze UI tab~~ Done
7. ~~N3 — Short vs long UI integration~~ Done
8. ~~N13 — N-PORT series-level deduplication~~ Done
9. ~~N14 — Geode/Fidelity sub-adviser exclusion~~ Done
10. ~~U1 — N-PORT coverage disclaimer tooltip~~ Done
11. ~~P4 — iShares Trust N-PORT~~ Done
**PRE-PHASE 4 REQUIRED:**
12. ~~N15 — Fidelity international sub-adviser deduplication~~ ✅ Done (Item 5)
13. ~~R1/R2/R3 — 13D/G data quality audit + cleanup~~ ✅ Done (Item 6 + R7/R7b/R9/R10). pct_null 96%→0.02%, shares_null 16.5%→0.02%. 20K+ agent names resolved. Parser hardened.
14. ~~Item 43 — app.py lint debt fix~~ ✅ Done (Item 7). flake8 0, bandit B608 0.
15. ~~N21 TODOs a/b/c — investor type classification~~ ✅ Done (Item 8). Manager-level: NULL 787→0, 14 categories, 8,639 managers, $67.3T. ALL categories reviewed 1-by-1: passive 45 ($22.2T), mixed 1,657 ($16.1T), active 4,126 ($14.2T), WM 500 ($4.5T), quant 68 ($4.3T), HF 1,342 ($2.4T), pension 139 ($2.0T), strategic 543 ($0.6T), SWF 17 ($0.3T), endowment 61 ($0.3T), PE 76 ($0.2T), activist 31 ($0.1T), VC 32, multi 2. 177 LOW>$10B manually fixed. Fund-level: 5,717 series via S&P500 overlap + 8-index correlation.

**POST-PHASE 4:**
16. M1/M2/M3 — Monthly N-PORT update flow design — design decisions, not migration blockers
17. R4/R5/R6 — 13D/G Register integration — UI integration, pending Phase 4 cutover
18. M4/M5/M6 — Incremental N-PORT updates — operational cadence, implement after cutover
19. H16 — Pre-computed entity×ticker flow cache — performance enhancement
20. U6, U8, N17, N18, N19, N22, N23 — UI/UX enhancements
21. Refresh readonly snapshot
22. Items N4-N10 as capacity allows
