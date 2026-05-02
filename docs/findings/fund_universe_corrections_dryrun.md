# fund-universe-value-corrections — Phase 2 dry-run

_Generated: 2026-05-02T12:14:52Z (manifest regenerated 12:25Z to de-duplicate Rareview)_

## Block A — Rareview reclassify

- `series_id`: `S000090077`
- `fund_name`: Rareview 2x Bull Cryptocurrency & Precious Metals ETF
- Current `fund_strategy`: **excluded** (`strategy_source`=orphan_backfill_2026Q2)
- Proposed `fund_strategy`: **passive** (`strategy_source`=unknown_cleanup_2026Q2)
- Proposed `total_net_assets`: **$4,555,216** (canonical N-PORT derivation,
  same formula as Block B; only 4 holdings on most-recent quarter and
  net SUM(mv) is negative due to short positions, but pct_of_nav-based
  reconstruction gives the true NAV).

Rationale: classifier order matched leveraged-name regex (`\dx`) before
the ETF/passive pattern, tagging the fund `excluded`. Per PR #246 audit,
this is a leveraged passive ETF, not excluded. Manual override.

## Block B — total_net_assets backfill (300 rows)

- Cohort: `strategy_source='orphan_backfill_2026Q2'`, EXCLUDING Block A's
  series_id (S000090077). Pre-Block-A cohort size = 301; Block B applies
  to the remaining 300 after Rareview moves to `unknown_cleanup_2026Q2`.
- Re-validated inventory: 301 rows tagged `orphan_backfill_2026Q2`,
  0 with `total_net_assets`, 301 NULL.

Canonical derivation: `NAV = MEDIAN(market_value_usd * 100.0 / pct_of_nav)`
over most-recent-quarter `is_latest=TRUE` rows. `pct_of_nav` is stored on
the percent scale (0–100). Method validated against 10 funds with
existing `total_net_assets` (ratio = 1.000000…).

Fallback (none required for current cohort): `NAV = SUM(market_value_usd)`
for series with no usable `pct_of_nav` rows; `strategy_source` suffixed
`|aum_summed_fallback`.

### Block B summary

| Source | Series | Total NAV (USD) |
|---|---:|---:|
| canonical_nport | 300 | $450,124,179,793.11 |
| aum_summed_fallback | 0 | $0.00 |
| null_residual | 0 | — |
| **TOTAL** | **300** | **$450,124,179,793.11** |

_No NULL-residual series — full coverage._

### NAV/SUM(mv) ratio distribution

- Median: 1.004 — typical funds have NAV ≈ holdings sum.
- Min: 0.609 (S000075093 Rareview Systematic Equity ETF — small leveraged ETF, cash drag).
- Max: 39.579 (S000084371 DailyDelta Q100 Upside Option Strategy ETF —
  N-PORT shows a single MMF holding worth $9,913 representing 2.53% of NAV;
  reconstruction = $9,913 × 100 / 2.53 = $392,344, the true NAV. Option
  contracts are reported elsewhere or filtered from `fund_holdings_v2`).

## Combined manifest shape

| block | rows | role |
|---|---:|---|
| A | 1 | Rareview reclassify + NAV |
| B | 300 | AUM backfill |
| **TOTAL** | **301** | |

The Block B query in `correct_fund_universe_values.py` excludes Block A's
`series_id` to prevent Block B from silently overwriting Block A's
`strategy_source` flip when the same row qualifies for both blocks.

## Phase 3 results

See `docs/findings/fund_universe_corrections_results.md`.
