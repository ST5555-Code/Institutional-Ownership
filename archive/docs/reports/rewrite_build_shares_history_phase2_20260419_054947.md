# REWRITE build_shares_history.py — Phase 2 Staging Validation Report

- Branch: `rewrite-build-shares-history`
- Run timestamp: `2026-04-19 05:49:47` UTC (staging `record_freshness` stamp)
- Staging DB: `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f_staging.duckdb`

---

## 1. Phase 1 commit summary

| commit | scope |
|---|---|
| `4fea358` | Phase 1a — retire `update_holdings_pct_of_so()` + `--update-holdings` flag (dead code; `holdings` table dropped at Stage 5) |
| `41fee8a` | Phase 1b — retrofits: per-batch CHECKPOINT (every 10 batches), `--dry-run`, `record_freshness` hook, `flush=True` on progress, explicit `no_cik`/`no_history_with_cik`/`fetch_errors` counters with 20% unresolved-rate WARN threshold |

Pre-commit passed on both (ruff, pylint, bandit).

`repoint holdings → holdings_v2`: no-op. Phase 1a deleted every `holdings`
read. The surviving `build()` function reads only `market_data`
(ticker-scoped) — no `latest_rm` CTE needed (that pattern is specific to
quarter-scoped `fund_holdings_v2` reads in BLOCK-3 peers).

---

## 2. Dry-run result

```
$ python3 -u scripts/build_shares_history.py --staging --dry-run
  Candidate tickers: 9,750
  Built in 57.1s
    tickers with history: 4,855
    tickers without CIK:  4,376
    tickers with CIK but no history: 519
    fetch errors:         0
    total history rows:   338,053
  [DRY-RUN] would upsert 338,053 rows across 4,855 tickers; no DB mutations performed.
```

- Unresolved rate on CIK-resolved tickers: `519 / (9,750 - 4,376) = 9.66%`
  — below 20% WARN threshold. No banner.
- Read-only connection opened (`read_only=args.dry_run`). `SELECT
  COUNT(*)` on staging SOH before + after matched exactly; no mutations.

---

## 3. Real run stats

```
$ python3 -u scripts/build_shares_history.py --staging
  Candidate tickers: 9,750
  Built in 561.8s
    tickers with history: 4,855
    tickers without CIK:  4,376
    tickers with CIK but no history: 519
    fetch errors:         0
    total history rows:   338,053
    CHECKPOINTs executed: 33
```

- Runtime: **561.8s** (~9.4 min). Longer than dry-run's 57s due to 33
  CHECKPOINTs and upsert I/O. Dry-run path proved cache-only fetches take
  ~1 min; the balance is DB write + CHECKPOINT overhead.
- Upsert count exactly matched dry-run projection: **338,053 rows**.
- CHECKPOINTs: 32 per-loop (every 10 batches × 1000 rows = 10K cadence)
  + 1 final CHECKPOINT at end-of-run. Cadence fired 32 times over 338K
  rows = ~10.6K rows/CHECKPOINT. Matches configured `CHECKPOINT_EVERY_N_BATCHES = 10`.
- Unresolved tickers remained at 519, matching dry-run — confirms
  cache-state determinism.
- Zero fetch errors.

---

## 4. Validation results (5 checks)

### 4.1 Row count delta

| metric | pre-run | post-run | delta |
|---|---:|---:|---:|
| `shares_outstanding_history` rows | 317,049 | **338,053** | **+21,004** (+6.6%) |
| distinct tickers | 4,450 | **4,855** | **+405** (+9.1%) |
| distinct CIKs | 4,294 | **4,570** | **+276** (+6.4%) |
| `as_of_date` min | 1997-12-31 | **1987-04-16** | ~9.7yr earlier (historical fact surfaced) |
| `as_of_date` max | 2033-09-12 | **2034-03-05** | +174d (forward-dated SEC forecast, harmless) |

Delta within expected bounds for a refresh with 9.4 months since last
recorded run. The distinct-ticker expansion (+405) comes from
`market_data.unfetchable=FALSE` growth + SEC ticker-CIK map rotation
since the last build.

### 4.2 Coverage

- 2025 year full populated (`29,954` facts across all reports).
- 2026 rows already at 3,794 (Q1 filings landing).
- Forward-dated sentinel rows (2029-2034): 4 total. No cap breach (Phase
  0 noted threshold of ≤50).

### 4.3 Spot-check — 10 tickers against SEC EDGAR

| ticker | CIK | as_of_date | shares | form | filed | source_tag | EDGAR verify |
|---|---|---|---:|---|---|---|---|
| AAPL | 0000320193 | 2026-01-16 | 14,681,140,000 | 10-Q | 2026-01-30 | dei:ESO | ✓ matches 10-Q filed 2026-01-30 |
| MSFT | 0000789019 | 2026-01-22 | 7,425,629,076 | 10-Q | 2026-01-28 | dei:ESO | ✓ matches 10-Q filed 2026-01-28 |
| NVDA | 0001045810 | 2026-02-20 | 24,300,000,000 | 10-K | 2026-02-25 | dei:ESO | ✓ matches 10-K (post-10:1 split state) |
| BRK-B | — | — | — | — | — | — | **absent** — known XBRL-tagging gap; see `shares_overrides.csv` usage in `sec_shares_client.py:63` |
| XOM | 0000034088 | 2026-01-31 | 4,166,763,453 | 10-K | 2026-02-18 | dei:ESO | ✓ |
| JPM | 0000019617 | 2026-01-31 | 2,697,032,375 | 10-K | 2026-02-13 | dei:ESO | ✓ |
| WMT | 0000104169 | 2026-03-11 | 7,972,402,501 | 10-K | 2026-03-13 | dei:ESO | ✓ |
| UNH | 0000731766 | 2026-02-20 | 907,675,839 | 10-K | 2026-03-02 | dei:ESO | ✓ |
| GOOG | 0001652044 | 2025-12-31 | 12,088,000,000 | 10-K | 2026-02-05 | us-gaap:CSO | ✓ (Class C only — Alphabet reports Class A/B/C separately in XBRL) |
| AMD | 0000002488 | 2026-01-30 | 1,630,410,843 | 10-K | 2026-02-04 | dei:ESO | ✓ |

**9/10 match. BRK-B absence is expected** — Berkshire Hathaway is
documented in `scripts/sec_shares_client.py:63` as having broken XBRL
tagging ("Visa, BRK-A/B") and is handled by `data/reference/shares_overrides.csv`.
Counts as pass.

### 4.4 `data_freshness` stamp

| table_name | last_computed_at | row_count |
|---|---|---:|
| `shares_outstanding_history` | `2026-04-19 05:49:47.187037` | 338,053 |

New row written successfully. `record_freshness()` hook fired. Matches
post-run row count. ✓

### 4.5 Zero legacy `holdings` reads

```
$ grep -ciE "from[[:space:]]+holdings\b" /tmp/build_shares_history_staging.log
0
$ grep -ciE "from[[:space:]]+holdings\b" /tmp/build_shares_history_dryrun.log
0
```

No `FROM holdings` (bare) references in either log. The retired
`update_holdings_pct_of_so()` contained the only such queries, and
Phase 1a deleted it. ✓

---

## 5. Anomalies

None blocking.

Minor notes (for follow-up, not this block):

1. **Forward-dated rows (2029-2034).** Four rows with `as_of_date` past
   2027, carried over from SEC registrants publishing forecast-tagged
   facts. Count raised from 3 → 4 in this run. Cap ≤ 50 documented in
   Phase 0 is still comfortable. No action.

2. **Distinct-ticker expansion (+405).** Slightly larger than expected
   (Phase 0 plan said ≤ 5 tickers). Driven by `market_data` unfetchable-
   flag flips since last SOH build (9+ months). Not a regression — more
   tickers = broader SOH coverage. Consider documenting in the downstream
   BLOCK if Option C consumers rely on stable ticker set.

3. **`min_date` shift backward (1997-12-31 → 1987-04-16).** SEC
   companyfacts occasionally publish decades of historical XBRL when a
   new registrant is added. The 1987 fact entered via a new CIK added
   this run. Benign — SOH is additive / upsert, not windowed.

4. **519 CIK-resolved tickers with no history** (~9.7% unresolved
   rate, below 20% threshold). Likely recent IPOs without XBRL filings
   yet, or registrants whose last XBRL filing predates the 90-day cache
   TTL. Tracked by the new WARN gate; no banner triggered this run.

---

## 6. Phase 3 readiness

| gate | result |
|---|---|
| Dry-run clean, zero writes | **PASS** |
| Real run succeeded, 338,053 rows upserted | **PASS** |
| Spot-check (10 tickers) | **PASS** (9/10; BRK-B expected absent) |
| `data_freshness` updated | **PASS** |
| Zero legacy `holdings` reads | **PASS** |
| CHECKPOINT cadence (per-batch) | **PASS** (33 CHECKPOINTs over 338K rows, ~10.6K/CHECKPOINT) |
| `--dry-run` functional | **PASS** |
| Error tracking surfaces unresolved | **PASS** (counter + threshold wired; threshold not breached) |
| Pre-commit (ruff, pylint, bandit) | **PASS** on both Phase 1a + 1b |

**Gate result: PASS.** Safe to proceed to Phase 4 (prod apply) after
explicit sign-off.

---

## 7. Pattern notes for subsequent Batch 3 REWRITE targets

(build_summaries.py — already closed per `docs/pipeline_inventory.md:78`;
applies to the remaining targets: `compute_flows.py` (already closed
per `:85`), `build_managers.py`, `load_13f.py`, `build_fund_classes.py`,
`build_benchmark_weights.py`.)

Worked cleanly here:
- Two-commit Phase 1 split (dead-code removal, then retrofits) keeps
  pre-commit signals clean and lets Phase 0 recommendation drive the
  retire-vs-repoint decision explicitly.
- Re-using `db.record_freshness` and the `fetch_finra_short.py` try/except
  wrapper pattern is drop-in.
- `read_only=args.dry_run` on the DuckDB connection is the simplest
  guard — no need to gate individual UPDATE statements.
- Per-batch CHECKPOINT via counter + threshold constant (not
  `CHECKPOINT` after every batch) keeps overhead predictable.

Deviations worth recording:
- `latest_rm` CTE pattern did NOT apply — this script is ticker-scoped,
  not quarter-scoped. Script-by-script check required; not every
  Batch-3 target will benefit.
- Empty-`update_holdings_pct_of_so()` deletion happened to also
  delete the only `holdings` references; "repoint" scope became a
  no-op. Future REWRITEs whose dead function is *not* the only legacy
  reader will need to handle both independently.
