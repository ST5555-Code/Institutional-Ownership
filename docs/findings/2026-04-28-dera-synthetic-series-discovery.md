# DERA synthetic-series discovery — 2026-04-28

Closure for ROADMAP P3 item *DERA 1,187 NULL-series synthetics cleanup*. The
"NULL series" framing is inherited from `docs/data_layers.md:92` (snapshot
2026-04-21) and is imprecise: rows are not NULL — they carry a synthetic
fallback key of the form `{cik_no_leading_zeros}_{accession_number}` minted by
`scripts/fetch_dera_nport.py:460` whenever DERA `FUND_REPORTED_INFO.SERIES_ID`
is missing in the source XML. Matching pattern: `series_id NOT LIKE 'S%'`.

## Discovery (read-only, prod `data/13f.duckdb`)

| Metric | Value |
|---|---|
| `fund_holdings_v2` total rows | 14,568,775 |
| `fund_holdings_v2` rows with `series_id IS NULL` | **0** |
| `fund_holdings_v2` rows with synthetic series_id | **2,172,757** (14.9%) |
| Distinct synthetic series in `fund_holdings_v2` | 1,236 (vs 1,187 doc'd 2026-04-21 — +49 from intervening DERA loads) |
| Distinct fund_ciks | 714 |
| Distinct accessions | 1,247 |
| All `is_latest=TRUE` | yes (no historical-shadow rows) |
| Quarter spread | 16 quarters (2022Q3–2026Q2); 87% concentrated 2025Q3–2026Q2 |
| `fund_universe` total rows | 12,971 |
| `fund_universe` synthetic series | 64 (the rest of the synthetic holdings have no `fund_universe` row at all) |
| Synthetic holdings AUM exposure | **$2,553B / $161,599B = 1.58%** of total `is_latest=TRUE` market value |
| `entity_id` resolved on synthetic | 5,383 / 2,172,757 = **0.25%** |
| `parent_fund_map` coverage | 395 / 1,236 distinct synthetic series = 32% |

Sample synthetic series_ids (first 5):

```
2044327_0001049169-25-000602
2055004_0001193125-26-066572
2059436_0001410368-25-032711
2060415_0002071691-26-007379
2060934_0000910472-26-003530
```

## Downstream impact

- `queries.py` has no `series_id IS NULL` branch reading from `fund_holdings_v2`.
  Hits for `series_id IS NULL` are in `enrich_fund_holdings_v2.py:186`,
  `pipeline/compute_peer_rotation.py:578`, `pipeline/compute_sector_flows.py:430,450`
  (peer-rotation / sector-flows handle the `c.series_id IS NULL` JOIN-miss case
  for new-vs-change classification, not orphan filtering) and
  `retired/validate_nport.py`.
- Most synthetic rows are correctly excluded from manager rollups via
  `parent_fund_map` (only 32% of synthetic series resolve through the rollup).
  The pre-aggregation in `compute_parent_fund_map.py` is keyed on real
  `(series_id, quarter)` tuples; synthetic keys that do not match an entity
  rollup carry through as fund-level holdings only.
- Validator already FLAGs them via `series_id_synthetic_fallback`
  (`scripts/fetch_dera_nport.py:759`, `scripts/pipeline/load_nport.py:437`) and
  `scripts/resolve_pending_series.py:843` classifies them as
  `deferred_synthetic` when the fund_cik has no entity match.

## Decision — FLAG (option c, defer)

The original task brief offered (a) DELETE / (b) RESOLVE / (c) FLAG. **FLAG.**

- **Not a DELETE candidate.** $2.55T NAV (1.58% of `is_latest=TRUE` market
  value) belongs to real N-PORT filings; the only defect is the missing
  `SERIES_ID` field in the source XML. Dropping the rows would erase real
  positions to clean up a metadata gap.
- **Not a one-shot RESOLVE candidate.** Real series_ids would have to be
  recovered via cross-referencing DERA registrant tables, N-CEN adviser map,
  or by ad-hoc series-from-fund_cik inference. `resolve_pending_series.py`
  already has a `deferred_synthetic` tier (`series_id_synthetic_fallback`
  rule, `scripts/resolve_pending_series.py:830-847`) and existing tier logic
  (T1 N-CEN / S1 fund_cik-as-entity / T2 family brand) — but the tier-S2
  default for synthetic-with-no-fund_cik-entity is *defer*, by design. A
  proper resolution session needs to: (i) extend the resolver tiers for
  synthetic keys, (ii) backfill `entity_id`/`rollup_entity_id` on the affected
  rows once series→entity is known, (iii) re-emit `parent_fund_map` to pick
  up the new linkages. Scope is multi-day, not a quick win.
- **No active downstream regression.** Aggregates that key off
  `parent_fund_map` (`holder_momentum` parent path, `peer_rotation`,
  `sector_flows`) only see synthetic rows when their fund_cik happens to
  resolve to an entity (5,383 rows / 0.25%). The rest are silently
  fund-level-only — already the right behaviour pending real series_id
  recovery.

## Recommended trigger for the next pass

Reactivate this item when **(any one of)**:
1. `resolve_pending_series.py` is being touched for unrelated tier work
   (S1/S2 logic refresh) — extend tiers for synthetic keys in the same PR.
2. The Q1 2026 DERA bulk (~late May 2026) lands — re-measure synthetic
   counts after that drop and decide whether the percentage warrants a
   targeted resolution sprint. If percentage stays under ~2% of NAV, leave
   FLAGGED.
3. A specific analytical workflow (activist defense, ownership rotation
   research) hits a fund whose holdings are stuck behind a synthetic
   series_id and the gap becomes user-visible.

Until then, keep the validator FLAG in place; aggregates already exclude.

## Changes this session

- No DB writes. No staging diff. No promote.
- `validate_entities.py --prod` baseline confirmed: PASS=7 / FAIL=2 / MANUAL=7
  (matches INF51 close 2026-04-27; both FAILs are documented baselines —
  `wellington_sub_advisory`, `phase3_resolution_rate`).
