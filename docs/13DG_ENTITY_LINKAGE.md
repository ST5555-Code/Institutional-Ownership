# 13D/G Entity Linkage

_Shipped 2026-04-16. Commit `e231633`._

Wires `beneficial_ownership_v2` (and derived `beneficial_ownership_current`)
into the entity MDM with the same Group 2 shape as `holdings_v2`. Prior to
this change, 13D/G filers were disconnected from the rollup graph — any
query walking `rollup_entity_id` or `dm_rollup_entity_id` silently skipped
activist / beneficial-ownership data.

## Problem

- `beneficial_ownership_v2.entity_id` existed (populated ~77% by a legacy
  pass that joined against `entity_identifiers(type='cik')`) but the
  four rollup columns were absent entirely.
- `beneficial_ownership_current` carried **no entity columns at all** —
  `promote_13dg.py:131 _rebuild_current()` dropped them by omission from
  the SELECT.
- Net: 13D/G rows had a filer entity but no EC or DM rollup target,
  and the L4 view had neither.

## Solution (Option C — promote-time enrichment + standalone full-refresh)

Two complementary entry points sharing one bulk-update function:

1. **`promote_13dg.py` (scoped)** — calls `bulk_enrich_bo_filers()`
   against only the filer CIKs touched by the current run. Runs
   between `_promote()` and `_rebuild_current()`. Keeps newly-promoted
   rows enriched immediately without re-touching history.

2. **`scripts/enrich_13dg.py` (full-refresh)** — on-demand script for
   drift repair after entity merges or CRD backfills. Single atomic
   `UPDATE` across the entire table. Restart-safe by being one
   statement. Also used to backfill historical rows after the initial
   migration 005 column addition.

## Schema changes — migration 005

`scripts/migrations/005_beneficial_ownership_entity_rollups.py`

```sql
ALTER TABLE beneficial_ownership_v2 ADD COLUMN rollup_entity_id    BIGINT;
ALTER TABLE beneficial_ownership_v2 ADD COLUMN rollup_name         VARCHAR;
ALTER TABLE beneficial_ownership_v2 ADD COLUMN dm_rollup_entity_id BIGINT;
ALTER TABLE beneficial_ownership_v2 ADD COLUMN dm_rollup_name      VARCHAR;
```

- `entity_id BIGINT` was already present; migration does not touch it.
- `beneficial_ownership_current` is DROP+CREATE AS SELECT by
  `rebuild_beneficial_ownership_current()`, so it picks up the new
  columns natively on next rebuild — no ALTER required.
- Idempotent (probes `duckdb_columns()` before each ALTER).
- Stamps `schema_versions` with `version='005_beneficial_ownership_entity_rollups'`.
- Flags: `--staging` / `--path PATH` / `--dry-run`.

Staging DB does not currently have `beneficial_ownership_v2` — migration
SKIPs cleanly there. Prod was migrated 2026-04-16 08:56 UTC.

## Enrichment shape — `scripts/pipeline/shared.py`

### `bulk_enrich_bo_filers(con, filer_ciks)`

Scoped or full-refresh bulk UPDATE. Mirrors `promote_nport.py`'s
`_bulk_enrich_run` in shape but keyed on `filer_cik` instead of
`series_id`. `filer_ciks=None` → full refresh.

Resolved columns:

| Target column (BO v2) | Source |
|---|---|
| `entity_id` | `entity_identifiers.entity_id` where `identifier_type='cik'` and active |
| `rollup_entity_id` | `entity_rollup_history` active row, `rollup_type='economic_control_v1'` |
| `rollup_name` | `entity_aliases.alias_name` where `is_preferred=TRUE`, joined on `ec.rollup_entity_id` |
| `dm_rollup_entity_id` | `entity_rollup_history` active row, `rollup_type='decision_maker_v1'` |
| `dm_rollup_name` | `entity_aliases.alias_name` where `is_preferred=TRUE`, joined on `dm.rollup_entity_id` |

Join is `LEFT JOIN` on both rollup worldviews and both alias lookups —
so a filer present in MDM but missing one worldview's rollup row still
gets `entity_id` + the present worldview, with the absent worldview
left NULL. Unmatched filers (no active `entity_identifiers` row) leave
all five columns NULL.

### `rebuild_beneficial_ownership_current(con)`

Lifted from `promote_13dg._rebuild_current()` so `promote_13dg.py` and
`enrich_13dg.py` share one rebuild SQL. `DROP + CREATE AS SELECT` with
`ROW_NUMBER() PARTITION BY (filer_cik, subject_ticker) ORDER BY
filing_date DESC`. New SELECT carries all five entity columns through
to the L4 table.

## Freshness

Three `data_freshness` rows are stamped at end of each enrichment run:

- `beneficial_ownership_v2` — stamped by `promote_13dg.py` at promote
  time (unchanged from Batch 2B behavior).
- `beneficial_ownership_current` — stamped after rebuild.
- `beneficial_ownership_v2_enrichment` — **new logical label**. Tracks
  when the enrichment pass last ran; `row_count` is the number of
  rows with resolved `entity_id`. Passed explicitly (label is not a
  real table — `record_freshness` default `COUNT(*)` would raise).

## Prod state (first run, 2026-04-16)

| Table | Total | entity_id | rollup_entity_id | Coverage |
|---|---|---|---|---|
| `beneficial_ownership_v2` | 51,905 | 40,009 | 40,009 | 77.08% |
| `beneficial_ownership_current` | 24,756 | 18,229 | 18,229 | 73.64% |

### Drift caught

First full-refresh reconciled **66 rows** where the legacy `entity_id`
diverged from the currently-resolved MDM entity (entity merges since
the legacy pass ran). All rollup columns went from 0 → 40,009 rows as
expected from the migration introducing them NULL.

### Coverage gap — 22.92% of rows still NULL

11,896 rows across 2,591 distinct filer CIKs have no
`entity_identifiers(type='cik')` row. These are 13D/G long-tail filers:
individuals, small corporations, activist investors filing one or two
Schedule 13Ds and never appearing in 13F, ADV, or N-CEN. `resolve_long_tail.py`
does **not** cover them — it targets entities *already* in the MDM with
`classification='unknown'`.

Resolution path (follow-up): a `resolve_13dg_filers.py` that
SEC-EDGAR-looks-up each unmatched CIK and creates placeholder entities
(`entities` + `entity_identifiers` + `entity_aliases` + self-rollup),
parallel to `resolve_pending_series.py`'s T1-T3 pattern. Not in scope
for this session.

## Operational

### Scoped run (inside promote_13dg.py)

Automatic on every `promote_13dg.py --run-id R`. Scoped to the filer
CIKs in that run's staged rows. No separate invocation needed.

### Full-refresh (enrich_13dg.py)

```bash
# dry-run (projection only — no writes)
python3 scripts/enrich_13dg.py --dry-run

# scope to one filer for debugging
python3 scripts/enrich_13dg.py --filer-cik 0001018963 --dry-run

# prod full refresh (~10s on 51,905 rows)
python3 scripts/enrich_13dg.py
```

Dry-run prints per-column delta predictions so operators can preview
the effect of an entity merge before writing.

### When to run the full-refresh

- After an entity merge (`build_entities.py --reset` or manual SCD
  edits) that changed a CIK's rollup target.
- After `resolve_long_tail.py` or a CRD backfill adds new
  `entity_identifiers` rows.
- On demand during QC to verify coverage.

The 9-step Makefile quarterly pipeline does **not** call
`enrich_13dg.py` — the promote-time scoped enrichment is sufficient
for steady-state runs.

## Files

- `scripts/migrations/005_beneficial_ownership_entity_rollups.py` — new
- `scripts/pipeline/shared.py` — `bulk_enrich_bo_filers`,
  `rebuild_beneficial_ownership_current`
- `scripts/promote_13dg.py` — imports + wired enrichment call + stamps
  `beneficial_ownership_v2_enrichment`
- `scripts/enrich_13dg.py` — new standalone

## Follow-ups

1. `resolve_13dg_filers.py` — placeholder entity creation for the 2,591
   unmatched filer CIKs. Would push row coverage from 77.08% toward
   ~95%+.
2. Add an `enrich_13dg.py` step to any quarterly Makefile variant that
   needs drift-proof historical rollups (not the default — promote-time
   scoped enrichment is the standard path).
