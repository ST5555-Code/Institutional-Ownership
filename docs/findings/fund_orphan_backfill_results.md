# fund-orphan-backfill — Phases 3–6 results

_Closes the 302-series / 160,934-row exposure surfaced by PR #244._

## Summary

Single PR delivering:

1. INSERT-only backfill of 301 canonical `fund_universe` rows for the
   S9-digit orphan cohort.
2. `cross.py` 3-way classification comments updated; NULL arm now
   explicitly documented as "unknown" (fund missing from
   `fund_universe`).
3. `OverlapAnalysisTab.tsx` active-only filter tightened to strict
   `=== true` equality (both row filter and active-KPI subset), so
   `is_active=null` (orphans) no longer rolls silently into the active
   set.

After this PR only the 1-series UNKNOWN_literal cohort (3,184 rows /
$10.0B) remains orphan, by design.

## Phase 3 — backfill execution

| Metric | Pre | Post | Δ |
|---|---:|---:|---:|
| `fund_universe` rows | 13,623 | 13,924 | +301 |
| Rows tagged `strategy_source='orphan_backfill_2026Q2'` | 0 | 301 | +301 |

Single-transaction INSERT, no UPDATE path (orphan = net-new by
definition; PR-2 pipeline lock not on critical path).

Manifest source breakdown:

| Source   | Count |
|---|---:|
| majority | 300 |
| override | 1 (S000045538 Blackstone Alt Multi-Strategy → multi_asset) |
| skip     | 0 (Calamos / Eaton Vance both live under series_id='UNKNOWN') |

Strategy distribution (INSERTs):

| Strategy | Series | Rows | AUM (USD) |
|---|---:|---:|---:|
| bond_or_other | 133 |   119,701 | $558.69B |
| excluded      | 136 |    17,619 |  $66.91B |
| passive       |  25 |    13,047 |  $20.30B |
| multi_asset   |   1 |     7,152 |   $2.54B |
| active        |   6 |       231 |   $0.03B |
| **TOTAL**     | **301** | **157,750** | **$648.46B** |

All 301 series resolved with **100% support_pct** — no mixed-vote
edge cases.

## Phase 4 — peer_rotation_flows rebuild

```
parse complete: 17,490,106 total rows in 69.7s
validate: level=fund   rollup=economic_control_v1 rows=5,065,200
validate: level=parent rollup=decision_maker_v1   rows=6,212,453
validate: level=parent rollup=economic_control_v1 rows=6,212,453
run() complete: run_id=peer_rotation_empty_20260501_235841 (73.4s)
promoted: rows_upserted=17,490,106 (222.9s)
```

Total row count held at **17,490,106 → 17,490,106** (Δ +0, well within
the ±0.5% tolerance). Snapshot:
`data/backups/peer_rotation_peer_rotation_empty_20260501_235841.duckdb`.

## Phase 5 — display layer fixes

* **`scripts/queries/cross.py`** — both 3-way CASE blocks
  (`get_two_company_overlap`, `get_two_company_subject`) now carry a
  comment referencing PR #244 + this PR explaining that the NULL arm
  is "unknown", surfaces as `is_active=null`, and is excluded from
  active-only views via strict equality at the frontend. Behavior
  unchanged at the SQL level — comments reflect new intent.
* **`scripts/queries/common.py:_fund_type_label`** — verified, no
  change needed. Already returns `'unknown'` for any value not in the
  canonical mapping (PR-1d invariant preserved).
* **`web/react-app/src/components/tabs/OverlapAnalysisTab.tsx`** —
  tightened both the row filter (line 194) and the active-KPI subset
  (line 213) from `r.is_active !== false` to `r.is_active === true`.
  Tightening line 213 alongside 194 keeps the row filter and the KPI
  tile consistent — without it, orphans (is_active=null) would be
  excluded from the active row list but still counted in the active
  KPI tile.

## Phase 6 — validation

| Check | Result |
|---|---|
| `pytest tests/` | **373 passed** (1 unrelated urllib3 warning) |
| `audit_orphan_inventory.py` re-run | residual = 1 series / 3,184 rows / $10.0B (UNKNOWN_literal only) ✓ |
| PR-1d display validator (`validate_classification_display_fix.py`) | **PASS** — all 8 endpoints canonical, no `is_active` field, no raw `fund_strategy` |
| `cd web/react-app && npm run build` | **0 errors**, 2.04s |
| Spot-check 5 random new `fund_universe` rows | all canonical strategy + `strategy_source='orphan_backfill_2026Q2'` |
| Blackstone S000045538 override | `fund_strategy='multi_asset'` ✓ |
| `peer_rotation_flows` row count | 17,490,106 (Δ 0 from pre-rebuild) |

## Files changed

| File | Type |
|---|---|
| `scripts/oneoff/backfill_orphan_fund_universe.py` | new (Phase 2) |
| `data/working/orphan_backfill_manifest.csv` | new (Phase 2 deliverable, manifest) |
| `docs/findings/fund_orphan_backfill_dryrun.md` | new (Phase 2) |
| `docs/findings/fund_orphan_backfill_results.md` | new (this doc) |
| `scripts/queries/cross.py` | edit (comment-only on both 3-way CASE blocks) |
| `web/react-app/src/components/tabs/OverlapAnalysisTab.tsx` | edit (line 194, 213: strict `=== true`) |

## Constraints honored

* **No `--reset` anywhere** — confirmed.
* **No staging twin** — `fund_universe` writes follow PR #233 / PR #243
  pattern, prod-direct.
* **No write-path module touched** — `load_nport.py`, `classify_fund()`,
  and pipeline writers untouched. Backfill is one-shot via the oneoff
  script.
* **Pipeline lock (PR-2) off critical path** — INSERT-only, no UPDATE
  collisions. Pre-flight collision check passed (0 manifest series_ids
  found existing in `fund_universe`).

## Residual orphan cohort (left orphan by design)

```
UNKNOWN_literal  series=1  rows=3,184  aum=$10.0B
```

Multiple historic fund_names funnel into the literal `series_id =
'UNKNOWN'` sentinel (notably `Calamos Global Total Return Fund` and
`Eaton Vance Tax-Advantaged Dividend Income Fund`). No canonical
resolution available without source-side rework — out of scope for
this PR per the per-fund-deferred-decisions P3 SKIP list.
