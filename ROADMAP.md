# 13F Institutional Ownership Database — Roadmap

_Last updated: April 2, 2026_

---

## IN PROGRESS

| # | Item | Notes |
|---|------|-------|
| P1 | Full 13D/G fetch — `fetch_13dg.py` | Phase 2 running, 55,173 filings, 4 workers, edgar library |

---

## PIPELINE 1 — 13D/G Beneficial Ownership

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 1 | Amendment tracking — upsert SC 13D/A and 13G/A by filer+subject | High | Do not insert duplicates; keep most recent amendment |
| 3 | Crossed 5% threshold flag — `crossed_5pct` boolean column | Medium | Set true on first 13G for filer+subject pair |
| 4 | Intent change tracking — `prior_intent` column | Medium | Flag activist→passive and passive→activist flips |
| 5 | `pct_owned` null improvement — tune regex for null cases | Low | Run after full fetch; needs large sample to pattern-match |

---

## PIPELINE 8 — Short Interest (FINRA)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 9 | Short vs long comparison — same manager long 13F and short FINRA | Medium | Surface in Smart Money and Activist tabs |
| 10 | Short squeeze signal — high crowding + high short interest flag | Low | Requires both Pipeline 1 and Pipeline 8 complete |

---

## APP — Flow Analysis Tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 11 | Chart.js fix — add CDN, explicit canvas height, destroy-before-reinit, setTimeout 100ms | High | Blocked on compute_flows.py running after DB unlocks |
| 12 | Run `compute_flows.py` after full fetch completes | High | Populates investor_flows table |
| 13 | Refresh readonly snapshot — `cp data/13f.duckdb data/13f_readonly.duckdb` | High | After compute_flows.py |

---

## APP — New Features (unlocked by short interest data)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 14 | Conviction tab — short interest column next to % Float | Medium | Requires FINRA data (now available) |
| 15 | Crowding tab — short crowding overlay | Medium | Requires FINRA data (now available) |
| 16 | Smart Money tab — net exposure view (long minus short per manager) | Medium | Requires FINRA data (now available) |
| 17 | Activist tab — flag managers short while exiting long position | Medium | Requires FINRA + 13D/G data |
| 18 | New/Exits tab — flag managers who went short after exiting long | Low | Requires FINRA data (now available) |

---

## INFRASTRUCTURE — Performance & Reliability

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 19 | Centralize quarter config — one shared module imported by all scripts | High | Eliminates update risk; every rollover currently requires touching 4+ files |
| 20 | Incremental market data refresh — only fetch missing/stale tickers in `fetch_market.py` | High | Cuts runtime from hours to minutes on update runs |
| 21 | Materialized summary tables for Flask — keyed by (quarter, ticker) and (quarter, parent_name) | High | Fixes app responsiveness; most-used queries hit 12M row holdings table on every request |
| 22 | Replace broad `except Exception: return None` with logged exceptions in `app.py` | High | One-line change per instance; makes production debugging possible |
| 23 | Incremental `load_13f.py` — append + rebuild latest quarter only | Medium | Grows in importance as dataset expands; not urgent at current size |
| 24 | OpenFIGI + yfinance persistent cache in `build_cusip.py` | Medium | Currently does 5,000 OpenFIGI lookups from scratch every run |
| 25 | Readonly snapshot auto-refresh after full build | Medium | Add to `start_app.sh` or post-fetch script |
| 26 | Benchmark script — time each pipeline stage | Low | Nice to have; not urgent |

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

---

## SEQUENCE — NEXT STEPS

1. Full 13D/G fetch completes (Phase 2 running)
2. Run `python3 scripts/compute_flows.py`
3. `cp data/13f.duckdb data/13f_readonly.duckdb`
4. Restart app — test Flow Analysis charts (item 11)
5. Claude Code: Items 1, 3, 4 (amendment tracking, crossed 5% flag, intent change)
6. Claude Code: Items 19, 20, 21, 22 (infrastructure — HIGH priority)
7. App features: items 14-18 (short interest integration into tabs)
