# BLOCK-SECTOR-COVERAGE-BACKGROUND — closeout

**Run ID:** 20260419_052804
**Branch:** `block-sector-coverage-background`
**HEAD at closeout:** `f3584ca`
**Seed baseline:** 2026-04-18 08:06 UTC (prod market_data row count 10,064,
sector NOT NULL 6,777)
**Merge complete:** 2026-04-19 05:27 UTC

---

## 1. Scope and objective

Background sweep to re-fetch `market_data.sector` for every ticker in prod
where `sector IS NULL AND ticker IS NOT NULL`. Staging-only writes until a
manual merge trigger. Parallel workstream to BLOCK-TICKER-BACKFILL; no
interaction with BLOCK-3 branches or prod tables other than `market_data`
(columns `sector` and `industry` only).

Ticker universe at seed time: **3,287 distinct NULL-sector tickers**.

---

## 2. Two-run history

### 2.1 Initial run (halted)

| Item | Value |
|---|---|
| PID | 47045 |
| Started | 2026-04-18 ~13:06 UTC |
| Halted | 2026-04-18 ~13:09 UTC |
| Tickers processed | 550 / 3,287 |
| Populated | 4 |
| Still-null | 546 |
| Reason for halt | BLOCK-SECURITIES-DATA-AUDIT pending — paused until `market_data.ticker` integrity confirmed |

Prior to this successful run, an earlier launch (PID 46170) was killed within
seconds of start because the initial throttle heuristic (5 consecutive Nones
= cooldown) tripped on the alphabetically-sorted head of the ticker list
(`07WA`, `0E41`, `0HQK`, `0VVB`, `1B2`, ...) — every one of those is a
foreign or structured-instrument code that Yahoo genuinely cannot resolve.
The cooldown was a false positive; the heuristic was rewritten before the
successful 2026-04-18 run (see §3).

### 2.2 Resumed run (to completion)

| Item | Value |
|---|---|
| PID | 86036 |
| Started | 2026-04-19 04:16 UTC |
| Completed cleanly | 2026-04-19 08:27 UTC (last ticker `ZZF`) |
| Tickers processed | 2,737 (resume pickup: 3,287 − 550 already done) |
| Populated in this run | 9 |
| Still-null in this run | 2,728 |
| Errors / aborts | 0 / 0 |
| Cooldown fires | 0 |

### 2.3 Combined totals

- **3,287 / 3,287** tickers processed
- **13 populated** (4 + 9)
- **3,274 still-null**
- **0 errors, 0 aborts, 0 rate-limit cooldowns**
- **Yahoo yield: 13 / 3,287 = 0.4%**

---

## 3. Throttle heuristic validation

The three-state heuristic committed in `3738179` (success-gated, 200-failure
hard cap):

- `resolved_count == 0` → 100 consecutive Nones before cooldown
- `resolved_count > 0`  → 15 consecutive Nones before cooldown
- Any state             → 200 consecutive Nones aborts the run

**Never fired cooldown across 3,287 tickers.** No false positives, no true
positives, no aborts. The heuristic correctly absorbed the dense prefix of
unresolvable head-of-list codes while keeping a tight post-success threshold
for legitimate throttling — which Yahoo never delivered on this run.

Success-gating was worth it: with the original 5-threshold, the initial run
would have spent hours in cooldown loops on unresolvable foreign codes
before reaching any real ticker. See `3738179` commit body for the
1B2 false-positive incident that motivated the rewrite.

---

## 4. 0.4% Yahoo yield — finding

Only 13 of 3,287 NULL-sector tickers resolved on Yahoo. This is the
**terminal state for Yahoo-only sector coverage** on the residual universe.
The 3,274 unresolved tickers are a mix of:

- Preferred-stock class suffixes (`-PA`, `-PR`, `-PE`, `-PC`) that Yahoo's
  `quoteSummary` endpoint doesn't carry profile data for
- Foreign-exchange cross-listings with no US Yahoo profile
- Delisted symbols (tender offers, mergers, bankruptcies)
- Structured instruments with free-form tickers containing spaces and
  metadata (`ZTO 1.5 09/01/27`)
- Shell companies and blank-check vehicles

Implication: **future sector-coverage work targeting these residual 3,274
(and the broader `market_data.sector IS NULL` universe as it drifts) needs
a non-Yahoo data source.** OpenFIGI already resolves security metadata for
many of these in other flows (CUSIP coverage). A sector-coverage pass could
plausibly chain Yahoo → OpenFIGI → SEC profile data, with cost and latency
tradeoffs per hop.

---

## 5. Merge result

| Item | Value |
|---|---|
| Merge path | Scoped 12-row subset via staging.market_data swap-and-restore |
| Resolved tickers merged | 12 (`ADC-PA`, `C-PR`, `CMRE-PC`, `CODI-PC`, `CTO-PA`, `GNL-PE`, `PAI`, `PCN`, `QETA`, `SABK`, `SKFRY`, `TGOPF`) |
| Dropped from merge | 1 (`RILY` — see §7) |
| merge_staging.py report | 0 added, 12 replaced |
| Prod `sector NOT NULL` before | 6,778 |
| Prod `sector NOT NULL` after | 6,790 |
| Delta | +12 (exact match) |
| Row count before / after | 10,064 / 10,064 (unchanged) |
| NULL-clobber regressions | 0 |
| Sector-value changes on non-merged tickers | 0 |
| Snapshot | `data/backups/13f_backup_pre_sector_merge_20260419_052625/` (EXPORT DATABASE PARQUET, 2.6GB, 318 files) |

Spot-check:

- `ADC-PA` → Real Estate / REIT - Retail
- `PCN` → Financial Services / Asset Management
- `SKFRY` → Industrials / Tools & Accessories

---

## 6. Commits on branch

| Hash | Message |
|---|---|
| `c0262ed` | `feat(refetch_missing_sectors): staging flag + resume support for background workstream` |
| `91264c6` | `chore(block-sector-coverage): ticker list generated, 3287 tickers pending` (allow-empty milestone) |
| `3738179` | `fix(refetch_missing_sectors): success-gated throttle heuristic, 200-failure hard cap` |
| `f3584ca` | `chore(block-sector-coverage): merge staging subset → prod, 12 sector rows populated` (allow-empty merge marker) |
| (this) | `docs(block-sector-coverage): closeout + upsert-mode gap + silent writer finding` |

---

## 7. Follow-on: `merge_staging.py` upsert-mode gap

**Context.** `merge_staging.py`'s PK-table path (hit by `market_data` via
`TABLE_KEYS["market_data"] = ["ticker"]`) does:

```
DELETE FROM prod.<table> p
  WHERE EXISTS (SELECT 1 FROM staging.<table> s WHERE <pk match>);
INSERT INTO prod.<table> (<cols>) SELECT <cols> FROM staging.<table>;
```

This is a **full-row replace** for every staging row. It is correct only
when staging is authoritative for every column of every matched row —
typically true for entity tables where staging is built from scratch per
merge cycle, but **unsafe when staging is a full-table mirror** of prod
subject to drift on columns outside the scope of the current change.

**Concrete failure mode in this block.** The sector sweep touches only
`sector` and `industry`. Staging was seeded on 2026-04-18 and held prod's
as-of-seed values for every other column (`price_live`, `market_cap`,
`fifty_two_week_high`, `fetch_date`, `public_float_usd`, `shares_as_of`,
etc.). If prod had drifted on any of those columns for any of the 12 merged
tickers since seed, a vanilla merge of the whole staging `market_data` would
have silently reverted those columns to yesterday's snapshot.

We sidestepped the risk in two ways:

1. Subsetting staging to the 12 tickers we actually changed (scoping
   reduces blast radius).
2. Dropping `RILY` specifically because its prod row had been touched
   by a non-`fetch_market.py` path since seed (see §8).

Neither is a general solution. **An upsert-NULL-only mode is needed.**
Proposed follow-on:

- **BLOCK-MERGE-UPSERT-MODE** — either a new mode in `merge_staging.py`
  (`--upsert-null <table>:<col>[,...]` that generates
  `UPDATE prod SET col = s.col FROM staging s WHERE p.pk = s.pk AND p.col IS NULL`)
  or fold into BLOCK-SCHEMA-CONSTRAINT-HYGIENE (INF28) if that block is
  already touching merge-path machinery.

The narrower variant (column-scoped upsert with NULL-only guard) covers
every data-enrichment block that writes to pre-existing prod rows:
BLOCK-SECTOR-COVERAGE, BLOCK-TICKER-BACKFILL (future), sector refreshes,
etc. The broader variant (arbitrary predicate) can come later.

Exit criteria: merge_staging.py exposes an upsert path that preserves
non-targeted columns on matched rows.

---

## 8. Follow-on: silent `market_data.sector` writer

**Finding.** During Phase 4 pre-merge drift checks, `RILY` surfaced with
`sector = 'Financial Services'` in prod. This row was NULL at staging seed
(2026-04-18 08:06) — otherwise it would not have appeared in the NULL-sector
ticker list — yet was populated by the time the merge was attempted
(2026-04-19 05:27).

Diagnostic evidence:

- Zero prod `market_data` rows have `fetch_date >= 2026-04-18`. The standard
  `fetch_market.py` write path was not used.
- Every column in staging vs. prod for `RILY` is byte-identical (including
  `fetch_date = 2026-04-16`, `metadata_date = 2026-04-16`). The value
  written to prod between seed and merge was apparently the same value this
  run resolved independently.
- Only one ticker of the 13 collides, so whatever wrote it is narrow in
  scope, not a batch-sized operation.

**Hypotheses (not investigated):**

- Manual SQL fix applied between seed and merge.
- A secondary writer elsewhere in the codebase that populates
  `market_data.sector` without updating `fetch_date`.
- A pipeline path that reads from a cache and writes to `market_data` but
  treats `fetch_date` as the fetch timestamp rather than the last-write
  timestamp — leaving it stale on enrichment-only updates.

**Risk.** If multiple writers touch `market_data.sector` without a shared
write convention, drift-vs.-staging becomes a general merge hazard, not a
one-off. The `fetch_date`-unchanged signature also means any diff-based
audit using `fetch_date` misses these writes.

**Proposed follow-on: BLOCK-MARKET-DATA-WRITER-AUDIT.** Scope:

1. Read-only `rg` survey of all scripts for `UPDATE market_data`,
   `INSERT INTO market_data`, `MERGE INTO market_data`, direct writes via
   `pandas.to_sql` or equivalent, and any non-`scripts/` entry points
   (notebooks, ad-hoc SQL files under `sql/` or `migrations/`).
2. Classify each writer by: what columns it writes, whether it touches
   `fetch_date`, and its normal-flow vs. manual-fix trigger.
3. Confirm canonical writer (`fetch_market.py`) is the only one updating
   `sector`/`industry`, or document the other paths.
4. Land a convention: any `market_data` row-touching path MUST bump
   `fetch_date` (or a new `last_write_ts` column) on update.

Scope is read-only + documentation unless a concrete misbehavior surfaces.
Estimated cost: half a session.

---

## 9. Artifacts

- Ticker list: `logs/sector_coverage_tickers_20260418.txt` (3,287 lines,
  gitignored)
- Progress file: `logs/sector_coverage_progress.json` (3,287 processed
  entries, gitignored)
- Run logs:
  - `logs/sector_coverage_run_20260418_083714.log` (initial false-positive
    run, killed)
  - `logs/sector_coverage_run_20260418_090609.log` (patched first run,
    halted at 550)
  - `logs/sector_coverage_run_resume_20260419_041626.log` (resume to
    completion)
- Pre-merge snapshot:
  `data/backups/13f_backup_pre_sector_merge_20260419_052625/`

---

## 10. Exit state

- Prod `market_data.sector NOT NULL`: **6,790** (was 6,777 at seed +13 this
  block, net +12 after dropping RILY vs. today's baseline of 6,778).
- Branch `block-sector-coverage-background` at HEAD `f3584ca` (merge) /
  this closeout on top.
- Follow-ons flagged: **BLOCK-MERGE-UPSERT-MODE** (§7),
  **BLOCK-MARKET-DATA-WRITER-AUDIT** (§8).
- Branch not pushed. No PR opened. Awaiting Serge's terminal merge call.
