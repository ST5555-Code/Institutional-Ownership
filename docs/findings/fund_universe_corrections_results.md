# fund-universe-value-corrections — Phases 3–5 results

_Generated: 2026-05-02_

Closes the cleanup arc opened by PRs #244 (audit) → #245 (backfill) →
#246 (attribution) → #247 (stale cleanup).

## Phase 3 — execute corrections

### Initial run (`--confirm`, ~12:17:35Z)

```
[confirm] pre-update: Block A strategy='excluded', Block B with_tna=0
[confirm] DONE — Block A: 1 row → passive; Block B: 301 rows populated total_net_assets.
[confirm] stats: block_a_updates=1, block_b_updates=301, null_residual=0
```

The transaction succeeded: Rareview flipped `excluded → passive`, all
301 NULL-NAV rows populated.

### Mid-flight bug + correction

Validation immediately afterwards revealed Rareview's `strategy_source`
was still `orphan_backfill_2026Q2` instead of the intended
`unknown_cleanup_2026Q2`.

Root cause: Block B's manifest derivation (`derive_block_b_manifest`)
filtered `WHERE strategy_source='orphan_backfill_2026Q2'`, which at
dry-run time included Rareview (NULL `total_net_assets`,
`strategy_source='orphan_backfill_2026Q2'`). The execution loop applied
Block A first (correctly setting `strategy_source='unknown_cleanup_2026Q2'`),
then Block B iterated through 301 manifest entries — including Rareview —
and re-overwrote `strategy_source` back to `orphan_backfill_2026Q2`.

Block B's UPDATE matched on `WHERE series_id=? AND total_net_assets IS NULL`,
which was still true for Rareview between Block A's UPDATE (which did not
touch `total_net_assets`) and Block B's iteration over its manifest entry.

Corrective action:

```
UPDATE fund_universe
SET strategy_source='unknown_cleanup_2026Q2', last_updated=NOW()
WHERE series_id='S000090077' AND fund_strategy='passive'
  AND strategy_source='orphan_backfill_2026Q2';
-- 1 row affected, COMMITted
```

Final Rareview state: `fund_strategy='passive'`,
`strategy_source='unknown_cleanup_2026Q2'`, `total_net_assets=$4,555,216`.

### Script fixes (forward-looking)

The script `scripts/oneoff/correct_fund_universe_values.py` was patched
so a hypothetical replay against a clean cohort would not reproduce the
bug:

1. `derive_block_b_manifest` now excludes Block A's `series_id` from the
   Block B cohort.
2. `derive_block_a_nav` was added to compute Rareview's NAV using the
   same canonical formula, and Block A's UPDATE now sets
   `total_net_assets` in the same statement.
3. The execution row-count check was relaxed from `EXPECTED_BACKFILL_ROW_COUNT`
   to `EXPECTED_BACKFILL_ROW_COUNT - 1` for Block B (Rareview is now in
   Block A).

The committed manifest CSV was regenerated to match: 1 Block A entry
(with NAV) + 300 Block B entries = 301 data rows.

## Final post-state

| Cohort | Rows | with_tna | NULL_tna | Total NAV |
|---|---:|---:|---:|---:|
| `orphan_backfill_2026Q2` | 300 | 300 | 0 | $450,124,179,793 |
| `unknown_cleanup_2026Q2` | 1 | 1 | 0 | $4,555,216 |
| **Combined** | **301** | **301** | **0** | **$450,128,735,010** |

Rareview row:

| series_id | fund_name | fund_strategy | strategy_source | total_net_assets |
|---|---|---|---|---:|
| `S000090077` | Rareview 2x Bull Cryptocurrency & Precious Metals ETF | `passive` | `unknown_cleanup_2026Q2` | $4,555,216 |

## Phase 4 — pipeline script fix

`scripts/oneoff/backfill_orphan_fund_universe.py` was patched to populate
`total_net_assets` on future orphan backfills using the same canonical
derivation. This is forward-looking: the existing 301-row cohort was
already corrected in Phase 3.

The patch derives NAV per series during manifest construction and
includes it in the INSERT statement.

## Phase 5 — validation

### Counts (matches Phase 3 expectations)

```sql
SELECT strategy_source, COUNT(*), COUNT(total_net_assets)
FROM fund_universe
WHERE strategy_source LIKE '%2026Q2'
GROUP BY 1;
-- ('orphan_backfill_2026Q2', 300, 300)
-- ('unknown_cleanup_2026Q2',   1,   1)
```

### Spot-check 5 random AUM-backfilled series

| series_id | fund_name | total_net_assets | source |
|---|---|---:|---|
| S000074346 | Large Cap Core Portfolio I | $7,611,704 | orphan_backfill_2026Q2 |
| S000061584 | Procure Space ETF | $366,888,084 | orphan_backfill_2026Q2 |
| S000009108 | Hawaiian Tax-Free Trust | $374,790,376 | orphan_backfill_2026Q2 |
| S000017995 | International Income Portfolio | $211,898,949 | orphan_backfill_2026Q2 |
| S000081280 | Valkyrie Bitcoin Futures Leveraged Strategy ETF | $15,100,667 | orphan_backfill_2026Q2 |

All values plausible (positive, non-zero, in range relative to row counts
and median holding values).

### pytest

See PR description for the test suite result.

### npm build

See PR description for the React build result.

## Watchpoints / follow-ups

- **`pct_of_nav` percent-scale convention**: This PR explicitly relies on
  `pct_of_nav` being stored on the 0–100 percent scale (validated on 10
  funds with existing `total_net_assets`). Future code that derives NAV
  from holdings should use `market_value_usd * 100.0 / pct_of_nav`, not
  `market_value_usd / pct_of_nav`. Worth noting in any developer-facing
  schema docs.
- **One-shot script reuse**: `correct_fund_universe_values.py` is a
  one-shot — it refuses to re-run after Block A has already been applied
  (validate_block_a aborts on `fund_strategy='passive'`). Intentional.
