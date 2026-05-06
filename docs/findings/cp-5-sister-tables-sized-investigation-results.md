# cp-5-sister-tables-sized-investigation — Results

**Date:** 2026-05-06
**Branch:** `cp-5-sister-tables-sized-investigation`
**Scope:** Read-only. Sizes drift state on `holdings_v2` and
`beneficial_ownership_v2` — both flagged by PR #288 fh2 recon as
carrying the same denormalize-from-ERH pattern that
`fund_holdings_v2` had before PR #289 dropped its columns.

**Drives:** chat-side decision — does each sister-table drop PR ship
before CP-5.1 (drift material), with CP-5.1, or after (low drift,
schema consistency only)?

**HEAD:** `cf04983` (PR #294 cleanup merged) at investigation start.

---

## 1. holdings_v2 state

### 1.1 Column existence + population

DESCRIBE confirms both denormalized columns present:
`dm_rollup_entity_id BIGINT`, `dm_rollup_name VARCHAR`.

| Metric | Value |
|---|---|
| total rows | 12,270,984 |
| `dm_rollup_entity_id` populated | 12,270,984 (100.00%) |
| `dm_rollup_name` populated | 12,270,984 (100.00%) |
| `is_latest = TRUE` rows | 12,270,984 (100.00%) |

`is_latest = FALSE` rows: 0. The legacy 13F holdings table runs as a
single live cohort — no SCD history maintained on this table.

### 1.2 Drift quantification (Method A vs Method B)

Method A: read-time JOIN to `entity_rollup_history` filtered on
`rollup_type = 'decision_maker_v1'` + `valid_to = DATE '9999-12-31'`,
then institution→top-parent climb (cycle-safe).
Method B: denormalized `holdings_v2.dm_rollup_entity_id` read at row
time, then same top-parent climb.

| Metric | Value |
|---|---|
| diverged rows (Method A ≠ Method B) | **147,500 (1.20%)** |
| top-parents with non-zero AUM drift | **42** |
| absolute drift, sum across top-parents | **~$8,164B** |

**Top 10 by |Δ AUM| (≥ $20B):**

| Top-parent | Method A | Method B | Δ |
|---|---:|---:|---:|
| UBS AM, a distinct business unit of UBS AS (eid=3583) | $1,818.04B | $0.00B | +$1,818.04B |
| UBS Asset Management (eid=24) | $2,381.31B | $4,199.36B | −$1,818.04B |
| Equitable Holdings, Inc. (eid=9526) | $50.89B | $1,268.12B | −$1,217.23B |
| AllianceBernstein Holding L.P. (eid=18762) | $1,217.23B | $0.00B | +$1,217.23B |
| Victory Capital (eid=69) | $0.00B | $601.02B | −$601.02B |
| VICTORY CAPITAL MANAGEMENT INC (eid=9130) | $601.02B | $0.00B | +$601.02B |
| GP Brinson Investments LLC (eid=627) | $268.88B | $1.38B | +$267.49B |
| Artisan Partners (eid=59) | $0.00B | $267.49B | −$267.49B |
| NEW YORK LIFE INVESTMENT MANAGEMENT LLC (eid=8473) | $75.01B | $0.00B | +$75.01B |
| NEW YORK LIFE INSURANCE CO (eid=5382) | $45.68B | $120.69B | −$75.01B |

These pair up: brand/sponsor eid carries the value under one method
while the merged-into target carries it under the other. This is the
same merge-induced drift signature seen in PR #288 (SSGA, FMR,
First Trust, Capital Group) — the cached column lags entity merges
that ERH already reflects.

Per-row alignment: 12,123,484 aligned (98.80%) / 147,500 diverged
(1.20%). Roughly the same order of magnitude as fh2 (1.30%).

### 1.3 Staleness mechanism (Step 2b)

10 sample diverged rows for entity 135: `row_loaded_at` = 2025-05-14;
`erh_computed_at` is NULL on the ERH row (the DM rollup row predates
the ERH `computed_at` audit column). Cannot be timestamp-confirmed
STALE in this sample, but the merge-induced drift shape (UBS AM /
AllianceBernstein / Victory / NY Life pair-flipping) **is the same
mode** PR #288 documented for fh2. Mechanism: ERH absorbed merges
post-load, the cached columns never refreshed.

### 1.4 Reader + writer scope

**Production readers — use `_rollup_col(rollup_type)` helper that
returns `'dm_rollup_name'` against `holdings_v2`:**

| File | Sites |
|---|---|
| `scripts/queries/cross.py` | 1 (line 33) |
| `scripts/queries/trend.py` | 2 (lines 35, 331) plus 1 dm_rollup_entity_id site (line 111) |
| `scripts/queries/register.py` | 7 (lines 42, 270, 449, 775, 1088, 1119, plus 1 internal) |
| `scripts/queries/fund.py` | 1 (line 48) |
| `scripts/queries/market.py` | 1 (line 585) |
| `scripts/queries/flows.py` | 3 (lines 211, 320, 461) |
| `scripts/queries/common.py` | 1 helper site (line 719) |

Total ~17 production reader sites read `dm_rollup_name` from
`holdings_v2` via the `rn = _rollup_col(rollup_type)` pattern. Plus
one direct `dm_rollup_entity_id` reference in `trend.py:111`.

Migration path is the same as PR #289: replace the `rn` column
reference with a CTE / JOIN to `entity_rollup_history` filtered on
`rollup_type='decision_maker_v1' AND valid_to=DATE '9999-12-31'`,
then JOIN `entity_aliases` for the preferred name. The number of
sites is roughly **3x** PR #289's fh2 cohort (6 readers).

**Writers:**

- `scripts/load_13f_v2.py:490–540` — INSERT writes NULL for both
  columns (the loader never populates them).
- No active UPDATE writer for `holdings_v2.dm_rollup_*` was found in
  `scripts/pipeline/`, `scripts/enrich_holdings.py`,
  `scripts/build_managers.py`, or `scripts/load_13f_v2.py`. The 100%
  population presumably came from a historical one-off backfill that
  is no longer in the live load path. Several `scripts/oneoff/`
  scripts (`inst_eid_bridge_aliases_merge.py`, CP-4b authors,
  `dera_synthetic_stabilize.py`) write to `holdings_v2.dm_rollup_*`
  during one-off entity merges — these are post-hoc reconcilers, not
  steady-state writers.

This means the columns drift monotonically: each new entity merge
flips ERH but never refreshes the cached column unless a one-off
script targets it.

### 1.5 Drop PR sizing

| Component | Size |
|---|---|
| Production readers | 17 sites across 7 files (vs 6 in PR #289) |
| Writer retirement | small (1 INSERT site only) |
| One-off writers | needs catalogue / convert to read Method A or accept retirement |
| Schema migration | 1 (DROP 2 columns, then rebuild ~6 indexes) |
| Test cohort | pytest 416/416, plus React build clean |

**Estimated PR size: MEDIUM-to-LARGE** (~3x PR #289). Pattern is
proven from PR #289, so risk is execution-volume rather than novel
mechanism.

### 1.6 Recommendation

**SHIP-BEFORE-CP-5.1.** Justification:

- 1.20% diverged rows / $8.16T abs drift is the **same magnitude** as
  the fh2 cohort PR #289 just dropped (1.30% / similar magnitude).
- Merge-induced drift is **not stationary** — every CP-5 entity
  merge increases drift further. Each sister-table drop deferred
  past CP-5.1 means more divergence accumulates across the full CP-5
  arc (cycle-truncated merges, Capital Group umbrella, future merges
  inside CP-5.1+).
- Read-side drift directly affects parent-level aggregations served
  by `cross.py` / `register.py` / `flows.py` / `fund.py` — the same
  surfaces that CP-5 is targeting.

---

## 2. beneficial_ownership_v2 state

### 2.1 Column existence + population

DESCRIBE confirms both columns present.

| Metric | Value |
|---|---|
| total rows | 51,905 |
| `dm_rollup_entity_id` populated | 49,059 (94.52%) |
| `dm_rollup_name` populated | 49,059 (94.52%) |
| `is_latest = TRUE` rows | 7,625 (14.69%) |
| `is_latest = TRUE` AND dm_eid populated | 6,693 |

13D/G filings carry full SCD history (amendments) so the
`is_latest=FALSE` portion is large by design.

### 2.2 Drift quantification

| Metric | Value |
|---|---|
| diverged rows (Method A ≠ Method B) | **3 (0.04%)** |
| top-parents with non-zero AUM drift | **0** |
| absolute drift, sum across top-parents | **~$0.00B** |

The 3 diverged rows all belong to entity 2322 (Method A → 2322,
Method B → 30). They contribute zero net AUM drift after the
top-parent climb (both routes converge at the same top-parent).

Staleness signature confirmed: row_loaded_at ≈ 2026-04-03,
erh_computed_at = 2026-05-02 → ERH was updated **after** the row
load. Same mechanism as fh2; the sample is just tiny.

### 2.3 Reader + writer scope

**Production readers using `dm_rollup_*` from
`beneficial_ownership_v2`: zero.**

The single production reader in `scripts/queries/register.py:848`
selects `filer_name, filing_type, filing_date, pct_owned,
shares_owned, intent, purpose_text` only — never references
`dm_rollup_*`. `scripts/admin_bp.py:891` and
`scripts/pipeline/shared.py:585+` similarly do not touch the
denormalized rollup columns. `_rollup_col()` is never used against
`beneficial_ownership_v2`.

**Writers:**

| File | Function | Type |
|---|---|---|
| `scripts/pipeline/shared.py:438–540` | `bulk_enrich_bo_filers` | 2 UPDATE branches (full + scoped), rollup_entity_id + rollup_name + dm_rollup_entity_id + dm_rollup_name |
| `scripts/pipeline/shared.py:563–620` | `_rebuild_beneficial_ownership_current` | references columns in CTAS rebuild |
| `scripts/pipeline/load_13dg.py:109, 178, 568` | INSERT staging + promote | column list only |
| `scripts/migrations/005_beneficial_ownership_entity_rollups.py` | one-time ADD COLUMN migration | retired by drop |
| `scripts/enrich_13dg.py` | full table refresh writer | optional batch tool |

### 2.4 Drop PR sizing

| Component | Size |
|---|---|
| Production readers | 0 |
| Writer retirement | small (3 files, ~6 sites) |
| Schema migration | 1 (DROP 2 columns + rebuild indexes if any) |
| Test cohort | pytest 416/416 |

**Estimated PR size: SMALL.** Substantially smaller than PR #289;
no production reader migration required.

### 2.5 Recommendation

**SHIP-WITH-CP-5.1** (or piggyback on the next conv-doc-sync). No
material drift today, but:

- Same architectural pattern, same drift mechanism — will re-emerge
  once 13D/G filing volume scales or post-merge entities accumulate.
- Drop PR is small and self-contained (zero reader migration), so
  the ratio of risk to architectural-cleanliness payoff is favorable.
- Holding off until "drift becomes material" defeats the point of
  the CP-5 ERH-as-canonical contract.

Not urgent enough to block CP-5.1; small enough to bundle with any
CP-5.1-adjacent doc-sync or schema-cleanup PR.

---

## 3. Combined recommendation

| Sister table | Drift today | Reader scope | Writer scope | PR size | Recommendation |
|---|---|---|---|---|---|
| `holdings_v2` | $8.16T abs / 1.20% rows / 42 top-parents | 17 sites / 7 files | 1 INSERT (NULL) + scattered one-offs | medium-large | **SHIP-BEFORE-CP-5.1** |
| `beneficial_ownership_v2` | ~$0 / 0.04% rows / 0 top-parents | 0 sites | 3 files / ~6 sites | small | **SHIP-WITH-CP-5.1** |

**PR count remaining before CP-5.1: 1** (`holdings_v2` drop).
**PR count bundled with CP-5.1: 1** (`beneficial_ownership_v2` drop).

Total residual sister-table drop work: 2 PRs.

---

## 4. Out-of-scope discoveries / surprises

1. **`holdings_v2` has no live UPDATE writer for `dm_rollup_*`.** The
   100% population came from historical backfill; current loader
   inserts NULL. This is a smaller surprise than fh2 (which had a
   live `_enrich_staging_entities` + `_bulk_enrich_run` rewriter
   chain), and it implies the holdings_v2 cached columns are
   strictly write-once-then-drift. The lack of a steady-state writer
   removes one migration site (PR #289 had 6 writer sites; sister
   PR will have 1).

2. **One-off scripts re-write `holdings_v2.dm_rollup_*` during
   merge authoring** (`scripts/oneoff/inst_eid_bridge_aliases_merge.py`,
   CP-4b authors, `dera_synthetic_stabilize.py`). These reconcilers
   become moot once the columns are dropped — Method A read-time
   JOIN replaces the need for any of them. Net code reduction.

3. **`beneficial_ownership_v2` column population (94.52%)** suggests
   ~5.48% of rows have NULL filer entity resolution. Expected — older
   13D/G filings without resolved CIKs. Not a drift symptom, just
   data-quality.

4. **`holdings_v2.dm_rollup_name` semantic defect carryover.** The
   `bulk_enrich_bo_filers` writer in `shared.py:486–500` joins
   `entity_aliases` correctly (on `dm.rollup_entity_id`), but the
   identical pattern documented in PR #289 §1 for fh2 used the EC
   rollup target instead of DM. holdings_v2 has no live writer to
   audit, so the drift may include a similar latent semantic defect
   from the historical backfill — to be verified if the drop PR
   surfaces unexpected name mismatches.

5. **The 42 top-parent drift cohort overlaps the CP-5 merge cohort.**
   UBS AM, AllianceBernstein/Equitable, NY Life, MetLife, Hartford —
   these are the same brand/sponsor/filer hierarchies CP-5 has been
   cleaning up. Drop work is best done **after** CP-5 entity merges
   stabilize, not before, so the ERH state at drop time is the
   canonical one. CP-5.1 is the boundary — schedule the holdings_v2
   drop PR after CP-5 entity merges complete and before CP-5.1
   begins.

---

## 5. References

- PR #288 — `docs/findings/cp-5-fh2-dm-rollup-decision-recon-results.md`
  (established drift quantification methodology, identified sister
  tables in §6 / outlook).
- PR #289 — `docs/findings/cp-5-fh2-dm-rollup-drop-results.md`
  (drop pattern, 6 readers + 6 writers + 1 migration).
- `docs/findings/cp-5-bundle-c-discovery.md` §7.5 (sister-table
  flagging).
- Recon script: `scripts/oneoff/cp_5_sister_tables_drift_recon.py`.
- Drift CSVs: `data/working/cp-5-sister-table-holdings_v2-drift.csv`,
  `data/working/cp-5-sister-table-beneficial_ownership_v2-drift.csv`.
