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

## Op H — entity_rollup_history AT-side residual cleanup (chat-authorized scope extension)

After Phase 5 surfaced the AT-side residual (see "Out-of-scope discoveries"
below for original framing), the user authorized **Option B** in chat:
extend PR #256 scope rather than open a follow-up PR. Op H added in the
same PR and run as a separate `--op-h` mode.

### Op H scope

For each pair, two branches:

- **Branch 1 — general fund-tier AT-side re-point** (excludes filer
  self-rollup case): for each open `entity_rollup_history` row where
  `rollup_entity_id IN (1, 30) AND NOT (entity_id=filer AND
  rollup_entity_id=brand)` — close (`valid_to=CURRENT_DATE`) and insert
  a new row at filer with the same `rule_applied`, `confidence`,
  `source`, `routing_confidence`, `review_due_date` (preserving
  fund-side rollup attribution metadata).
- **Branch 2 — filer self-rollup recreate**: for each open row where
  `entity_id=filer AND rollup_entity_id=brand` — close and insert
  fresh (`rollup_entity_id=filer`, `rule_applied='self'`,
  `confidence='exact'`, `source='CP-4a-merge:inst-eid-bridge-fix-aliases'`,
  `routing_confidence='high'`, `review_due_date=NULL`).

PK is `(entity_id, rollup_type, valid_from, valid_to)`. Pre-flight
collision check confirmed no fund_eid already had an open row at the
filer eid for either pair, so the new rows insert cleanly.

### Op H execution stats (single transaction, both pairs)

| Pair | Branch 1 (close + insert) | Branch 2 (filer self-rollup recreate) | Total |
|---|---:|---:|---:|
| 1 → 4375 (Vanguard) | 114 (57 fund_eids × 2 rollup_types) | 0 | 114 |
| 30 → 2322 (PIMCO) | 323 (162 fund_eids × 2 minus 1 absent rollup_type) | 2 (filer 2322 self-rollup) | 325 |
| **Total** | **437** | **2** | **439** |

Pre-image drift gate (5%): clean (114 + 325 matches the discovery
count).

### Op H sanity checks

| check | result |
|---|---|
| `entity_rollup_history` rows with `rollup_entity_id IN (1, 30)` open | **0** ✓ |
| filer 2322 `economic_control_v1` self-rollup | (2322, 2322, source=`CP-4a-merge:inst-eid-bridge-fix-aliases`) ✓ |
| filer 2322 `decision_maker_v1` self-rollup | (2322, 2322, source=`CP-4a-merge:inst-eid-bridge-fix-aliases`) ✓ |
| filer 4375 `economic_control_v1` self-rollup | (4375, 4375, source=`self`) — unchanged ✓ |
| filer 4375 `decision_maker_v1` self-rollup | (4375, 4375, source=`self`) — unchanged ✓ |
| `entity_current.rollup_entity_id` for eid=2322 | **2322** (was 30 pre-Op-H) ✓ |
| `entity_current.rollup_entity_id` for eid=4375 | **4375** (unchanged) ✓ |
| Spot-check fund eid=20322 (Vanguard intermediate-term bond): rollup_entity_id post-Op-H | **4375** ✓ |
| `peer_rotation_flows` row count (Op H is ERH-only, should not affect peer_rotation) | 17,489,564 — unchanged ✓ |
| `pytest tests/` post-Op-H | **373/373** in 54.57s ✓ |
| `phase1b` helper post-Op-H: `invisible_brand_count` | 1,223 — unchanged from post-Phase-3 (Op H affects routing-layer only, does not affect invisible-brand calculation which keys off fund_holdings_v2 / holdings_v2) ✓ |

### Op F vs Op H — distinction for CP-4b precedent

Future merge work (CP-4b AUTHOR_NEW_BRIDGE, ~25 brands) will not need Op H
in the same shape because it doesn't deprecate any brand_eid — it just
inserts new `entity_relationships` rows. But the lesson generalizes:

- **Op F (FROM-side)**: closes `entity_rollup_history` rows where
  `entity_id = deprecated_eid`. Required when the brand IS the entity
  whose rollup state needs invalidation.
- **Op H (AT-side)**: closes + re-points rows where `rollup_entity_id =
  deprecated_eid`. Required when OTHER entities were rolling up TO the
  deprecated eid — the parallel rollup-history layer for the
  `entity_relationships` edges that Op B re-pointed must be propagated
  too, otherwise `entity_current.rollup_entity_id` stays stale.

Both are needed for any future BRAND_TO_FILER merge. Codified as standard
op shape in the `inst_eid_bridge_decisions.md` Op F clarification.

## Out-of-scope discoveries surfaced for chat decision

Per ROADMAP discipline ("flag duplicate ROADMAP items; do not silently
create"), the following were noticed during validation and are
**surfaced here for chat decision** rather than added to ROADMAP by
this PR (except item B, which the user explicitly authorized):

### A. `entity_rollup_history` AT-side residual — RESOLVED via Op H (Option B authorized in chat)

Phase 5 surfaced 114 rows / 57 fund_eids still rolling up TO `eid=1`
plus 325 rows / 163 entity_ids still rolling up TO `eid=30` (incl
filer 2322's own self-rollup-to-30). User authorized **Option B** —
extend PR #256 scope rather than open a follow-up. **Op H added and
executed in this PR.** See "Op H — entity_rollup_history AT-side
residual cleanup" section above for execution stats and sanity
checks. `entity_current.rollup_entity_id` for eid=2322 now correctly
reads `2322` (self).

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
