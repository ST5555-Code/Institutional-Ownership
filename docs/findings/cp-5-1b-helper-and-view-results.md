# cp-5-1b-helper-and-view — results

PR: `cp-5-1b-helper-and-view` (#299)
Branch: `cp-5-1b-helper-and-view`
Status: shipped 2026-05-06
Foundation: 1/6 CP-5.x execution PRs (CP-5.1).

## 1. Phase 1 pre-flight — null result

PR #298 recon flagged 6 fund-typed entities with
`economic_control_v1` open-row ERH but no
`decision_maker_v1` open-row ERH:

```
SELECT COUNT(*) FROM entities e
WHERE e.entity_type = 'fund'
  AND EXISTS (… ec_v1 open …)
  AND NOT EXISTS (… dm_v1 open …);
```

Re-running the query at PR #299 execute time returned **0
rows**. Cohort drift = −6 between recon and execute. An
intervening process (likely a downstream remediation cron or
a closed companion PR) backfilled the missing `dm_v1` rows.
**No INSERTs needed.** A regression test
(`test_T5_no_fund_missing_dm_v1`) pins the null result so
future drift surfaces immediately.

### Adjacent surprise (out of scope)

A separate query found 6 fund-typed entities with **NEITHER**
rollup type open:

```
eid 20210/20211/20212  Adams Natural Resources Fund, Inc.   (3 dupes)
eid 20213/20214/20215  Adams Diversified Equity Fund, Inc.  (3 dupes)
```

These are duplicate eids merged INTO canonical eids 2961 and
6471 in PR #283 Adams MERGE cohort. Tracked as P3 follow-up
`cp-5-adams-residual-cleanup`.

## 2. View DDL final shape

Migration 027 ships two read-only views via
`CREATE OR REPLACE` (idempotent, schema-stamped, zero row
mutations).

### `inst_to_top_parent`

```sql
WITH RECURSIVE entity_climb AS (
    SELECT entity_id AS climber_entity_id,
           entity_id AS top_parent,
           0 AS hops
    FROM entities
    UNION ALL
    SELECT ec.climber_entity_id, er.parent_entity_id, ec.hops+1
    FROM entity_climb ec
    JOIN entity_relationships er
      ON er.child_entity_id = ec.top_parent
    WHERE er.valid_to = DATE '9999-12-31'
      AND er.control_type IN ('control', 'mutual', 'merge')
      AND ec.hops < 10
)
SELECT climber_entity_id AS entity_id,
       ARG_MAX(top_parent, ROW(hops, -top_parent))
           AS top_parent_entity_id,
       MAX(hops) AS hops_at_top
FROM entity_climb
GROUP BY climber_entity_id
```

Anchor: every entity (not just institutions) — the historical
`inst_` prefix is retained for naming continuity but the
shape is more general. Funds, non-institutional rollup
targets, and other entity types all appear in the climb;
those with no incoming ownership edges self-rollup at
`hops_at_top = 0`.

Recursive step: walks up via `control` / `mutual` / `merge`
only. The `advisory` `control_type` (15,919 fund-sponsor /
sub-adviser rows) is excluded per the two-relationship-layer
coexistence pattern (PR #287) — sponsor-layer attribution is
a separate read concern.

Tie-break: `ARG_MAX(top_parent, ROW(hops, -top_parent))`
selects the deepest climb, then the smallest `top_parent`
entity_id at that depth. Deterministic across runs (verified
by `test_T7_climb_determinism`).

Cycle guard: hops ≤ 10. Prod has zero climbers at the limit
post PR #285 (cycle truncation). The migration's G3 hard
guard rolls back if any climber reaches `hops = 10`.

### `unified_holdings`

```sql
WITH thirteen_f_leg AS (
    SELECT ittp.top_parent_entity_id, h.cusip, h.ticker,
           SUM(h.market_value_usd) / 1e9 AS thirteen_f_aum_b
    FROM holdings_v2 h
    JOIN inst_to_top_parent ittp
      ON ittp.entity_id = h.entity_id
    WHERE h.is_latest = TRUE
    GROUP BY 1, 2, 3
),
fund_tier_leg AS (
    SELECT ittp.top_parent_entity_id, fh.cusip, fh.ticker,
           SUM(fh.market_value_usd) / 1e9 AS fund_tier_aum_b
    FROM fund_holdings_v2 fh
    JOIN entity_rollup_history erh
      ON erh.entity_id = fh.entity_id
      AND erh.rollup_type = 'decision_maker_v1'
      AND erh.valid_to = DATE '9999-12-31'
    JOIN inst_to_top_parent ittp
      ON ittp.entity_id = erh.rollup_entity_id
    WHERE fh.is_latest = TRUE
      AND fh.cusip IS NOT NULL AND fh.cusip <> ''
    GROUP BY 1, 2, 3
)
SELECT
    COALESCE(t.top_parent_entity_id, f.top_parent_entity_id)
        AS top_parent_entity_id,
    e.canonical_name AS top_parent_name,
    COALESCE(t.cusip, f.cusip) AS cusip,
    COALESCE(t.ticker, f.ticker) AS ticker,
    COALESCE(t.thirteen_f_aum_b, 0) AS thirteen_f_aum_b,
    COALESCE(f.fund_tier_aum_b, 0) AS fund_tier_aum_b,
    GREATEST(COALESCE(t.thirteen_f_aum_b, 0),
             COALESCE(f.fund_tier_aum_b, 0)) AS r5_aum_b,
    CASE WHEN COALESCE(t.thirteen_f_aum_b, 0)
              >= COALESCE(f.fund_tier_aum_b, 0)
         THEN '13F' ELSE 'fund_tier' END AS source_winner
FROM thirteen_f_leg t
FULL OUTER JOIN fund_tier_leg f
  ON f.top_parent_entity_id = t.top_parent_entity_id
  AND f.cusip = t.cusip AND f.ticker = t.ticker
JOIN entities e
  ON e.entity_id = COALESCE(t.top_parent_entity_id,
                            f.top_parent_entity_id)
```

Units: `holdings_v2.market_value_usd` is BIGINT USD;
`fund_holdings_v2.market_value_usd` is DOUBLE USD. Both
divide by `1e9` to land in `$B`. The original prompt's
`value_usd_millions / 1000.0` was a schema misread (column
does not exist).

## 3. Recursive CTE behavior on prod data

Distribution of `hops_at_top` per climber (prod, 2026-05-06):

| `hops_at_top` | climbers |
| ---: | ---: |
| 0 | 26,962 |
| 1 | 335 |
| 2 | 12 |
| 3 | 3 |

Total climbers = 27,312 = total entities. Max depth = 3.
Cycle suspects (`hops_at_top = 10`) = 0.

Capital Group umbrella (eid 12, PR #287): all 3
`wholly_owned` arms (eid 6657, 7125, 7136) climb to
`top_parent_entity_id = 12` at `hops = 1`. G4 hard guard
PASSED.

## 4. R5 logic

`r5_aum_b = GREATEST(thirteen_f_aum_b, fund_tier_aum_b)`.
`source_winner = '13F'` when 13F ≥ fund-tier (tie goes to
13F).

**Modified R5 ships without intra-family FoF subtraction.**
Bundle A §1.4 specified the subtraction but the data model
does not support it: fund entities lack CUSIP identifiers in
`entity_identifiers`, so there is no canonical
CUSIP→fund-entity path. Vanguard `fund_tier_aum` ships as
raw rollup, not adjusted. Tracked as P2 follow-up
`cp-5-fof-subtraction-cusip-linkage`.

Spot-checked top-10 firms by `SUM(r5_aum_b)` (multi-quarter
sums per `is_latest = TRUE` policy):

| eid | name | 13F | fund-tier | r5 |
| ---: | --- | ---: | ---: | ---: |
| 4375 | VANGUARD GROUP INC | $25.3T | $41.3T | $42.4T |
| 3241 | BlackRock, Inc. | $21.6T | $2.5T | $22.8T |
| 10443 | FMR LLC | $7.2T | $20.9T | $21.7T |
| 12 | Capital Group / American Funds | $7.2T | $14.6T | $15.2T |
| 7984 | STATE STREET CORP | $11.0T | $5.5T | $12.2T |

These are aggregates across all `is_latest = TRUE` rows
(many quarters); single-quarter readers continue to query
the source tables directly.

## 5. `top_parent_holdings_join()` helper

Lives at `scripts/queries/common.py`. Returns a SQL JOIN
fragment for fund_holdings_v2 readers that need
top-parent attribution outside the view:

```python
def top_parent_holdings_join(alias='fh'):
    return (
        " JOIN entity_rollup_history erh_top "
        f"ON erh_top.entity_id = {alias}.entity_id "
        "AND erh_top.rollup_type = 'decision_maker_v1' "
        "AND erh_top.valid_to = DATE '9999-12-31' "
        "JOIN inst_to_top_parent ittp_top "
        "ON ittp_top.entity_id = erh_top.rollup_entity_id "
    )
```

Stable aliases `erh_top` / `ittp_top` for caller WHERE /
GROUP BY use. For 13F (`holdings_v2`) callers, no ERH JOIN
is needed — JOIN `inst_to_top_parent` directly on
`h.entity_id`. CP-5.2 onward consumes this helper.

## 6. Test coverage (`tests/test_cp5_unified_holdings.py`)

10 added tests, of which 4 skip on the historical fixture
(which pre-dates PR #285 cycle truncation and PR #287
Capital Group bridges). Skip-markers are gated on data
shape, not environment, so the same tests pass against the
prod-quality DB.

| Test | Coverage | Fixture | Prod |
| --- | --- | --- | --- |
| T1 climb covers every entity | shape | ✓ | ✓ |
| T1 climb max hops < 10 | cycle | skip | ✓ |
| T1 every climber has top_parent | shape | ✓ | ✓ |
| T2 r5 = GREATEST | invariant | ✓ | ✓ |
| T2 source_winner matches r5 | invariant | ✓ | ✓ |
| T3 Capital Group arms → eid 12 | data | skip | ✓ |
| T3 umbrella self-rollup | data | skip | ✓ |
| T4 fund_tier = raw rollup | invariant (FoF deferred) | ✓ | ✓ |
| T5 no fund missing dm_v1 | regression (Phase 1 null) | ✓ | ✓ |
| T6 helper SQL parses | helper | ✓ | ✓ |
| T7 climb determinism | invariant | ✓ | ✓ |
| T8 zero climbers at hops=10 | cycle | skip | ✓ |
| nonempty + columns | smoke | ✓ | ✓ |

Pytest baseline: 416 passing → 426 passing (10 new + 4
skipped).

## 7. Phase 5 validation

- `pytest tests/` — all 426 passing (4 skipped).
- `npm run build` — 0 errors, 1.59s build.
- App smoke — booted on :8001, served `/`, port released
  cleanly.
- 5 hard guards (G1 entity coverage, G2 distinct climbers,
  G3 cycle detection, G4 Capital Group arms, G5 unified
  nonempty) all PASSED on prod migration apply.

## 8. CP-5 status

**1 / 6 CP-5.x PRs shipped.** This is the foundation; CP-5.2
onward consumes `inst_to_top_parent` + `unified_holdings` +
`top_parent_holdings_join()`.

Next: **CP-5.2 — Register tab reader migration.** Migrate
the Register tab reader to source from `unified_holdings`
where its R5 column is currently computed inline. Open
question for chat: Register is single-quarter, but
`unified_holdings` is multi-quarter — design call needed on
either (a) parameterizing the view by quarter, (b) adding a
quarter-specific sister view, or (c) keeping Register on
direct source-table reads with the helper supporting only
the climb step.

## 9. Out-of-scope discoveries / surprises

1. **Phase 1 cohort drift = −6.** Recon→execute window had
   an intervening backfill. Documented; T5 pins regression.

2. **6 Adams residuals with NO open rollup rows.** P3
   follow-up `cp-5-adams-residual-cleanup`.

3. **No CUSIP→fund-entity bridge in the data model.**
   Surfaced when prototyping Bundle A §1.4 FoF subtraction.
   P2 follow-up `cp-5-fof-subtraction-cusip-linkage`.

4. **`fund_holdings_v2.dm_entity_id` denorm survives PR
   #289.** Migration 024 dropped `dm_rollup_*` columns but
   `dm_entity_id` remains. Method A canonical reading still
   uses ERH JOIN (PR #280); the surviving denorm is a
   read-time hot-path optimization that is not authoritative.
   Out of scope here; flagged.

5. **Vanguard duplicate top eids.** "Vanguard Group" (eid 1)
   and "VANGUARD GROUP INC" (eid 4375) both appear as
   institutions. Different filer arms map to different tops.
   Out of scope; flagged for a future MERGE-op cohort.

6. **`schema_versions` table missing from fixture DB.**
   Tests bootstrap it before applying migration 027. Worth
   eventually rebuilding the fixture to current shape.
