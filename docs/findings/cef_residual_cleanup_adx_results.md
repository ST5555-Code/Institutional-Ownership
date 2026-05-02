# cef-residual-cleanup-adx — Phase 3–5 results

**Date:** 2026-05-02
**Branch:** `cef-residual-cleanup-adx`
**Scope:** Adams Diversified Equity Fund (CIK `0000002230`, NYSE: ADX). Flip
the 96 byte-identical `series_id='UNKNOWN'` duplicate rows in
`fund_holdings_v2` to `is_latest=FALSE`. ASA Gold (CIK `0001230869`, 350 rows)
out of scope — separate PR `cef-asa-period-backfill`.

Closes the ADX side of the BRANCH 2 cohort deferred from PR #247
(`fund-stale-unknown-cleanup`) per the PR #249 (`cef-scoping`) reframe:
the 446 UNKNOWN-series CEF residual is migration-015 residue from the
retired loader `scripts/retired/fetch_nport.py`, not a CEF architecture
gap. ADX has live `SYN_0000002230` companions for all 96 UNKNOWN rows;
this PR drops the duplicate UNKNOWN side. ASA's `SYN_0001230869` rows do
not yet exist (PR-B will run the v2 loader against 3 ASA periods first).

Backup boundary: `data/backups/13f_backup_20260502_131809` (carried over
from the morning's run; the only writes between this backup and the
flip are the 96-row UPDATE plus the peer_rotation_flows rebuild).

---

## Phase 3 — `--confirm` execution

```
[confirm] cohort OK: rows=96, aum=$2,988,710,095.76, syn_latest=291
[confirm] pre-flip ADX UNKNOWN is_latest=TRUE rows: 96
[confirm] flipping 96 rows by (cusip, report_date)
[confirm] post-flip ADX UNKNOWN is_latest=TRUE rows: 0 (Δ=96)
[confirm] DONE — flipped is_latest on 96 ADX UNKNOWN rows.
          UNKNOWN is_latest=TRUE: 96 → 0.
```

| metric | pre-flip | post-flip | Δ |
|---|---:|---:|---:|
| ADX UNKNOWN is_latest=TRUE rows | 96 | 0 | -96 |
| ADX UNKNOWN is_latest=FALSE rows | 0 | 96 | +96 |
| ADX SYN_0000002230 is_latest=TRUE rows | 291 | 291 | 0 |
| Global UNKNOWN is_latest=TRUE rows | 446 | 350 | -96 |

Single accession in the cohort: `BACKFILL_MIG015_UNKNOWN_2025-09`. All
96 rows for period 2025-09-30 only — though the SYN_ side spans three
periods (2025-06-30: 100 rows / $2.806B; 2025-09-30: 96 / $2.989B;
2025-12-31: 95 / $3.032B), the UNKNOWN side was only ever written for
2025-09. Period-level AUM at 2025-09-30 is identical between the
UNKNOWN and SYN_ sides ($2,988,710,095.76 each).

All hard guards passed: cohort drift gate (0% on row count + AUM),
expected-vs-actual flip delta (96 == 96), `BEGIN/COMMIT`-wrapped UPDATE.

## Phase 4 — peer_rotation_flows rebuild

```
2026-05-02 13:37:52,716 INFO parse complete: 17,489,567 total rows in 56.6s
2026-05-02 13:37:54,187 INFO run(): pending_approval inserts=17,489,567
2026-05-02 13:37:57,017 INFO snapshot created
                              data/backups/peer_rotation_peer_rotation_empty_20260502_173654.duckdb
run() complete: run_id=peer_rotation_empty_20260502_173654 (59.4s)
promoted: rows_upserted=17,489,567 (193.4s)
```

| metric | pre-rebuild (post-PR #247) | post-rebuild | Δ |
|---|---:|---:|---:|
| `peer_rotation_flows` row count | 17,489,751 | 17,489,567 | -184 (0.001%) |

The -184 row delta is well within the brief's ±0.5% tolerance and is
explained by 96 holdings rows leaving the `is_latest=TRUE` universe.
Most of those rows were already collapsing into existing
`SYN_0000002230` aggregates in the prior run (the case-aligned
`Adams Diversified Equity Fund` entity), so the net change in
`(quarter_pair × sector × entity × ticker)` distinct tuples is small.

## Phase 5 — validation

### `pytest tests/`

```
======================= 373 passed, 1 warning in 54.53s ========================
```

Same 373/373 pass count as PR #248 baseline (no regressions).

### `audit_unknown_inventory.py` re-run

```
fund_universe rows: 13,924  NULL strategy: 0
orphan series count: 1  rows (is_latest): 350  AUM: $1.75B
Cohort A (series_id='UNKNOWN'): rows=350  AUM=$1.75B
                                distinct_names=1 distinct_ciks=1
```

Residual exactly matches plan expectation: ASA Gold only (CIK
`0001230869`, 350 rows / $1.752B). The ADX cohort is closed.

### `audit_orphan_inventory.py` re-run

`phase1_totals_is_latest`: `[1, 350, 1752484930.87]` — single series,
350 rows, $1.752B. Per-quarter breakdown: 2024Q4 (108 rows / $0.440B),
2025Q1 (112 / $0.521B), 2025Q3 (130 / $0.791B). All ASA.

### `cd web/react-app && npm run build`

```
✓ built in 1.66s
```

0 errors.

### Spot-check — 3 random ADX `(cusip, period)` pairs

Sample drawn at random from the flipped manifest (seed=42):

| cusip | period | SYN row (is_latest) | UNKNOWN row (is_latest) | MV match |
|---|---|---|---|---|
| `L8681T102` | 2025-09-30 | TRUE / $6,351,800 | FALSE / $6,351,800 | ✓ |
| `533900106` | 2025-09-30 | TRUE / $19,102,230 | FALSE / $19,102,230 | ✓ |
| `228368106` | 2025-09-30 | TRUE / $14,527,136 | FALSE / $14,527,136 | ✓ |

For every spot-check pair, exactly one row is `is_latest=TRUE` (the
SYN_ side), confirming the duplicate is dead and the canonical row is
preserved.

---

## Architecture / safety

- UPDATE-only on the `is_latest` flag. No INSERT, no `fund_universe`
  touched, no `series_id` rewrite, no synthesized `SYN_` rows.
- No write-path module modified — `load_nport.py`, `load_13f_v2.py`,
  `classify_fund()`, pipeline writers all untouched. The retired
  `scripts/retired/fetch_nport.py` (the source of the residue) is also
  untouched.
- PR-2 pipeline lock not on critical path: `fund_holdings_v2` is the
  affected table, not `fund_universe`.
- BEGIN/COMMIT-wrapped single-transaction UPDATE; row-delta gate
  before COMMIT.

## Out of scope

- ASA Gold (CIK `0001230869`, 350 rows / $1.752B): no live
  `SYN_0001230869` companion exists; deferred to PR-B
  `cef-asa-period-backfill` per the PR #249 reframe.
- Patching the v2 loader retroactively to flip `is_latest` on legacy
  UNKNOWN rows: separate watchpoint (`v2-loader-is-latest-watchpoint`).
- Removing the retired loader: separate watchpoint
  (`retired-loader-residue-watchpoint`).

## Outputs

- `scripts/oneoff/cleanup_adx_unknown_duplicates.py`
- `data/working/adx_unknown_cleanup_manifest.csv` (96-row record)
- `docs/findings/cef_residual_cleanup_adx_dryrun.md`
- `docs/findings/cef_residual_cleanup_adx_results.md` (this file)
