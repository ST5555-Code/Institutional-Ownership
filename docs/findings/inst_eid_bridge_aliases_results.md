# inst-eid-bridge-fix-aliases (CP-4a) — Phase 3-5 results

Generated 2026-05-02 by `scripts/oneoff/inst_eid_bridge_aliases_merge.py --confirm`,
followed by `compute_peer_rotation.py`, `pytest tests/`, `npm run build`, and
`scripts/oneoff/inst_eid_bridge_phase1b_eid_level.py`.

PR [#256](https://github.com/ST5555-Code/Institutional-Ownership/pull/256).
Branch `inst-eid-bridge-fix-aliases`.

## Phase 3 — execute merges (single transaction)

Both pairs landed in a single BEGIN/COMMIT-wrapped transaction. Pre-image
drift gate (5%): clean. AUM conservation tolerance ($0.01B per pair):
exceeded comfortably — both pairs hit **$0.000000B** delta.

### Vanguard (brand_eid=1 → filer_eid=4375)

| Op | Effect | Rows |
|---|---|---:|
| A | `fund_holdings_v2` re-point (`rollup_entity_id`, `dm_rollup_entity_id`, `dm_rollup_name`) | 267,751 |
| B | `entity_relationships` re-point (`parent_entity_id` brand → filer, fund_sponsor edges) | 57 |
| B' | close brand↔filer alias-bridge row (id=15251 wholly_owned 4375→1, source=orphan_scan) | 1 |
| C | close `entity_classification_history` brand-side | 1 |
| E | INSERT audit row (parent_brand / merge), `relationship_id=20813` | 1 |
| F | close `entity_rollup_history` brand-side (entity_id=1) | 2 |
| G | re-point `entity_aliases` (no open brand aliases) | 0 |

- Post-merge filer AUM: **$41,271.3277B** (= pre-merge $38,729.7960B + brand $2,541.5317B)
- AUM conservation Δ: **$0.000000B**

Op E source field captures the subsumed-row reference per Adjustment 3:

```
CP-4a-merge:inst-eid-bridge-fix-aliases|subsumes:wholly_owned/4375->1/orphan_scan
```

### PIMCO (brand_eid=30 → filer_eid=2322)

| Op | Effect | Rows |
|---|---|---:|
| A | `fund_holdings_v2` re-point | 289,132 |
| B | `entity_relationships` re-point (parent=30 → 2322, excludes self-loop case) | 25 |
| B' | close brand↔filer self-loop row (id=115 fund_sponsor 30→2322, source=parent_bridge) | 1 |
| C | close `entity_classification_history` brand-side | 1 |
| E | INSERT audit row (parent_brand / merge), `relationship_id=20814` | 1 |
| F | close `entity_rollup_history` brand-side (entity_id=30) | 2 |
| G | re-point `entity_aliases` (`PIMCO` brand + `PACIFIC INVESTMENT` filing) | 2 |
| G demote | filer 2322's `PACIFIC INVESTMENT MANAGEMENT CO LLC` (brand, was preferred=TRUE) → preferred=FALSE | 1 |

- Post-merge filer AUM: **$2,044.1990B** (= pre-merge $327.1979B + brand $1,717.0011B)
- AUM conservation Δ: **$0.000000B**

Op E source field:

```
CP-4a-merge:inst-eid-bridge-fix-aliases|subsumes:fund_sponsor/30->2322/parent_bridge
```

Op G demotion direction confirmed per Adjustment 1: incoming brand-side
trade name `PIMCO` wins as `is_preferred=TRUE`; filer's prior legal-name
preferred is demoted. Post-merge `entity_current.display_name` for
eid=2322 reads `PIMCO`.

## Phase 4 — peer_rotation_flows rebuild

`scripts/pipeline/compute_peer_rotation.py` (no `--staging` — full prod path).

- run() complete: **105.0s**
- snapshot: `data/backups/peer_rotation_peer_rotation_empty_20260502_234253.duckdb`
- promote: **361.7s** — `rows_upserted=17,489,564`
- pre-rebuild row count: 17,489,564
- post-rebuild row count: 17,489,564
- Δ = 0 rows (0%, well within ±0.5% tolerance)

Total wall-clock for compute + promote: ~7.8 min. The exact row-count
match indicates the merge re-pointed rollups within the existing
fund-tier coverage; no new (quarter, sector, entity) tuples were
created or destroyed by the rollup shift.

## Phase 5 — validation

### pytest

`pytest tests/` → **373 passed, 1 warning in 52.60s**. No regression
vs PR #248 baseline (373/373).

### React build

`cd web/react-app && npm run build` → **0 errors, 8.13s, 20 chunks**.
Worktree-local symlink to parent `node_modules` to avoid a fresh
`npm install` in the worktree.

### inst_eid_bridge_phase1b helper re-run

Re-ran `scripts/oneoff/inst_eid_bridge_phase1b_eid_level.py` against
post-merge state. Comparison with the pre-merge JSON committed by
PR #254:

| metric | pre-merge (PR #254) | post-CP-4a | Δ |
|---|---:|---:|---:|
| `brand_eid_count` | 1,707 | 1,705 | **−2** (eid=1, eid=30 dropped) |
| `invisible_brand_count` | 1,225 | 1,223 | **−2** |
| `invisible_brand_rows` | 6,929,560 | 6,661,809 | **−267,751** |
| `invisible_brand_aum_usd` | $27,797,705,080,058 | $25,256,173,335,561 | **−$2,541.53B** |
| `invisible_with_open_relationship` | 498 | 496 | **−2** |
| `name_match_summary.brands_named` | 1,225 | 1,223 | **−2** |

**Important nuance — Vanguard fully bridged, PIMCO still invisible.**
The `invisible_brand_rows` and `invisible_brand_aum` deltas reflect
**Vanguard only** (267,751 rows / $2,541.53B). PIMCO's 289,132 rows /
$1,717.00B were re-pointed from `eid=30` to `eid=2322` as designed,
but `eid=2322` itself has no `holdings_v2` presence (PIMCO does not
file 13F under that CIK), so PIMCO remains "invisible" in the
phase1b sense — just under filer eid instead of brand eid. This
matches the existing **`pimco-13f-ingestion-gap`** P2 ROADMAP entry:
the alias mismatch (CP-4a scope) and the ingestion gap (separate
workstream) are decoupled per the decisions doc, and CP-4a fixes
exactly what it set out to fix.

The prompt's expected drop of "~$4.26T+" was based on the assumption
both pairs would become visible. Reality is $2.54T — the difference
($1.72T) is exactly PIMCO's brand AUM, which awaits
`pimco-13f-ingestion-gap` resolution before `eid=2322` becomes
visible to `holdings_v2`.

### Post-merge state spot-check

| check | result |
|---|---|
| `fund_holdings_v2` rows referencing brand_eid=1 (rollup or dm_rollup) | 0 |
| `fund_holdings_v2` rows referencing brand_eid=30 | 0 |
| `entity_relationships` open referencing brand_eid=1 | 1 (the OP E audit row) |
| `entity_relationships` open referencing brand_eid=30 | 1 (the OP E audit row) |
| `entity_classification_history` brand=1, brand=30 | both closed at 2026-05-02 |
| `entity_aliases` filer 2322 preferred brand alias | `PIMCO` (per Adjustment 1) |
| `entity_aliases` filer 2322 demoted brand alias | `PACIFIC INVESTMENT MANAGEMENT CO LLC` |
| `entity_current.display_name` for eid=2322 | `PIMCO` |
| `entity_current.display_name` for eid=4375 | `Vanguard Group` (unchanged) |

`dm_rollup_name` cosmetic note: filer 4375's fund_holdings_v2 rows
now have two distinct values — `Vanguard Group` (569,793 pre-merge
rows, untouched) and `VANGUARD GROUP INC` (267,751 newly re-pointed
rows, set to filer canonical_name per Op A). Either could be
canonicalized later via a one-shot UPDATE; not in scope here.

## Out-of-scope discoveries surfaced for chat decision

Per ROADMAP discipline ("flag duplicate ROADMAP items; do not silently
create"), the following were noticed during validation and are
**surfaced here for chat decision** rather than added to ROADMAP by
this PR (except item B, which the user explicitly authorized):

### A. `entity_rollup_history` AT-side residual — CP-4a scope gap

Op F as designed closed `entity_rollup_history` rows where
`entity_id = brand_eid`. It did NOT close rows where
`rollup_entity_id = brand_eid` (the AT-side / target-side). Post-merge
counts:

- 114 rows / 57 distinct fund_eids still rolling up TO `eid=1`
  (`alias_match` source — these mirror the closed brand-side
  fund_sponsor `entity_relationships` from Op B but were not propagated
  to the parallel rollup_history layer).
- 325 rows / 163 distinct entity_ids still rolling up TO `eid=30`
  (`alias_match` source for ~162 fund_eids, plus filer 2322's own
  self-rollup-to-30 `manual` row).
- Filer eid=2322's `entity_current.rollup_entity_id` therefore
  reads as **30** (deprecated brand) instead of **2322** (self).

This is genuinely a CP-4a scope gap, not a separate workstream. The
fix is mechanical: re-point `entity_rollup_history` rows where
`rollup_entity_id IN (1, 30)` to the filer eid (close the open row
+ insert a new open row at filer), and re-create filer 2322's
self-rollup. Scope: ~3 SQL statement pairs across both rollup_types.
**For chat decision:** ship a corrective Op H supplement before
PR #256 merges, or open a follow-up PR
`inst-eid-bridge-aliases-rollup-residual` (P2)?

### B. `source-type-value-canonicalization` — new P3 entry (added in this commit per chat)

Surfaced by PR #255 §A.5 (`ingestion_manifest_reconcile`). Per chat
instruction, added to ROADMAP §P3 in this commit:

> `ingestion_manifest.source_type` uses `'NPORT'` from direct writes
> vs `'nport_holdings'` from SourcePipeline-base writes; affects
> `admin_bp.py:1346` last-run lookup. Workstream: audit +
> canonicalization PR, parallel to critical path.

### C. Migration 008/015 join-key verification — candidate P3 (no action)

Per chat instruction: surface in this results doc as candidate, do
not create new entry without chat confirmation. PR #255 §6 fixed
the design-doc SQL by switching from `(series_id, report_month)` to
`accession_number` join key on `ingestion_manifest`, but flagged
that the working backfill SQL still needs verification before
migration 008 ships. There is no dedicated tracker entry for this
verification — it lives only inside the PR #255 ROADMAP body.
**For chat decision:** create a P3 tracker
`migration-008-backfill-join-key-verification` (S, pre-migration-008
gate), or leave inline reference in the PR #255 entry as
sufficient?

### D. `requested_by` — do NOT add (per chat instruction)

Defer indefinitely. Design-doc annotation (Phase 1.4 of PR #255)
already sufficient. Not added to ROADMAP.

## Decisions doc correction

Per "single audit trail" directive, `docs/decisions/inst_eid_bridge_decisions.md`
is updated alongside this commit (NOT in a separate PR):

- CP-4a sequencing line: `~5 brands` → `2 brands` with rationale.
- "Plus 3 small alias-pairs surfaced during CP-4a Phase 1 re-validation"
  marked as struck-through with rationale (zero-discovery against
  `eid_inventory.csv`'s 4 BRAND_HAS_NAME_MATCH rows, all matching
  the BLOCKER 2 fuzzy-match false-positive prototype).
- OP A/B/C/F/G shape recorded with the 5 schema corrections from
  Phase 1 re-validation.
- `relationship_type='parent_brand'` + `control_type='merge'` reuse
  decision recorded.
- CP-4a completion stamp with results doc reference.

## Architecture / safety

- Single BEGIN/COMMIT transaction across both pairs; ROLLBACK on
  any constraint violation. The only mid-flight error was the first
  `--confirm` attempt failing on `SELECT changes()` (a SQLite
  function not present in DuckDB); the transaction rolled back
  cleanly with zero post-image drift, then the script was patched
  to use cursor `fetchone()` and re-run successfully.
- 5 hard guards per pair: (1) zero leftover brand refs in
  `fund_holdings_v2`; (2) ≤1 open relationship referencing brand
  (the OP E audit row); (3) zero open ECH rows; (4) zero open ERH
  FROM-side rows; (5) zero open alias rows on brand. AUM
  conservation gate $0.01B per pair, both hit $0.000000B.
- No `--reset` anywhere.
- No write-path module (`load_nport.py`, `load_13f_v2.py`,
  `classify_fund()`, etc.) modified.
- PR #251 ASA pattern was the cited precedent but the op shape was
  re-derived from scratch given the manager-vs-fund-level
  divergence; full rationale in
  `docs/findings/inst_eid_bridge_aliases_dryrun.md` Phase 1
  schema findings.

## Files

- `scripts/oneoff/inst_eid_bridge_aliases_merge.py` — 7-op merge
  script (A/B/B'/C/E/F/G), `--dry-run` and `--confirm` modes.
- `data/working/inst_eid_bridge_aliases_manifest.csv` — pre-image
  capture per pair.
- `docs/findings/inst_eid_bridge_aliases_dryrun.md` — Phase 1
  schema findings + per-pair pre-image counts.
- `docs/findings/inst_eid_bridge_aliases_results.md` — this file.
- `docs/findings/_inst_eid_bridge_phase1b.json` — re-generated by
  the helper re-run, captures post-merge invisible-brand inventory.
- `data/working/inst_eid_bridge/eid_inventory.csv` — re-generated
  by the helper re-run (1,225 → 1,223 brand rows).
- `docs/decisions/inst_eid_bridge_decisions.md` — updated with the
  CP-4a sequencing correction and completion stamp.
- `ROADMAP.md` — CP-4a moved to COMPLETED; new P3 entry
  `source-type-value-canonicalization`.
