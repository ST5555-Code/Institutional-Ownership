# 13F Institutional Ownership Database — Roadmap

_Last updated: April 2, 2026_

---

## IN PROGRESS

| # | Item | Notes |
|---|------|-------|
| P1 | Full 13D/G fetch — `fetch_13dg.py` | 57,612 unparsed filings in listed_filings_13dg. Awaiting authorization to run Phase 2 |
| P2 | `fetch_market.py` batch rewrite | Done — batch yf.download(), persistent cache (7-day), upsert-only. Needs production test |
| P3 | `compute_flows.py` set-based rewrite | Done — single INSERT per period via window functions. Needs production test |

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
| 19 | Centralize quarter config | Done | `config.py` created, imported by fetch_13f, load_13f, fetch_market, build_summaries, compute_flows. app.py SQL quarters need dedicated pass (60+ queries) |
| 20 | Incremental market data refresh | Done | `get_stale_tickers()` skips tickers fetched <7 days. `save_market_data()` upserts, never drops |
| 21 | Materialized summary tables | Done | `build_summaries.py` creates `summary_by_ticker` + `summary_by_parent`. --rebuild flag |
| 22 | Logged exceptions in app.py | Done | All bare `except Exception:` replaced with `as e` + `app.logger.error()` in endpoint handlers |
| 23 | Incremental `load_13f.py` — append + rebuild latest quarter only | Medium | Grows in importance as dataset expands; not urgent at current size |
| 24 | OpenFIGI + yfinance persistent cache in `build_cusip.py` | Done | `_cache_openfigi` and `_cache_yfinance` tables, 30-day yfinance freshness |
| 25 | Readonly snapshot auto-refresh after full build | Medium | Add to `start_app.sh` or post-fetch script. Bug 7 switchback monitor added |
| 26 | Benchmark script — time each pipeline stage | Done | `scripts/benchmark.py` with --run flag, stage timing, dry-run check |
| 27 | app.py quarter centralization — convert 60+ SQL strings to use config.py vars | Medium | Requires f-string conversion of triple-quoted SQL; deferred for dedicated pass |
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

---

## SEQUENCE — NEXT STEPS

1. Authorize full 13D/G Phase 2 run (57,612 unparsed filings)
2. `fetch_market.py` batch rewrite (Item P2)
3. `compute_flows.py` set-based rewrite (Item P3)
4. Run `python3 scripts/compute_flows.py`
5. `cp data/13f.duckdb data/13f_readonly.duckdb`
6. Restart app — test Flow Analysis charts
7. Items 1, 3, 4 (amendment tracking, crossed 5% flag, intent change)
8. App features: items 14-18 (short interest integration into tabs)
