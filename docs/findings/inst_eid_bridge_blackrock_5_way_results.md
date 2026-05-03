# inst-eid-bridge-blackrock-5-way (CP-4b-blackrock) — Phase 3-5 results

Generated 2026-05-02 by `scripts/oneoff/inst_eid_bridge_blackrock_5_way.py --confirm`.

## Per-pair execution

| pair | child eid | brand | new relationship_id | fund AUM bridged |
|---:|---:|---|---:|---:|
| 1 | 7586  | BlackRock Fund Advisors                | 20815 | $1,303.29B |
| 2 | 3586  | BLACKROCK ADVISORS LLC                 | 20816 |   $645.07B |
| 3 | 17970 | BlackRock Investment Management, LLC   | 20817 |   $426.48B |
| 4 | 8453  | BLACKROCK FINANCIAL MANAGEMENT INC/DE  | 20818 |   $149.54B |
| 5 | 18030 | BlackRock International Limited        | 20819 |    $16.32B |
|   |       | **Total**                              |       | **$2,540.70B (~$2.54T)** |

All 5 INSERTs landed in a single `BEGIN/COMMIT` transaction with the
prepared `relationship_id` range (20815–20819) intact (no concurrent
writes drifted MAX). Per-pair post-INSERT sanity check:
`SELECT COUNT(*)=1` for each `(parent=3241, child=brand_eid,
relationship_type='wholly_owned', control_type='control', valid_to=open)`
tuple — all 5 pass.

## Aggregate

- `entity_relationships` row count: **18,365 → 18,370** (Δ +5, expected 5)
- `MAX(relationship_id)`: **20,814 → 20,819**
- Total fund AUM bridged: **$2,540.70B (~$2.54T)**
- Filer eid=3241 hv2 AUM (unchanged): $21,642.7B
- `fund_holdings_v2` rows touched: **0** (CP-4b is bridge-only)

## Phase 4 — peer_rotation_flows rebuild

`python3 scripts/pipeline/compute_peer_rotation.py`:
- pre-rebuild rows: **17,489,564**
- post-rebuild rows: **17,489,564** (Δ 0, exact match)
- promote: 183.2s

Expected and observed: BRIDGE preserves brand-side attribution, no
`fund_holdings_v2` re-pointing, so `peer_rotation_flows` is unaffected.

## Phase 5 — validation

- `pytest tests/`: **373 passed** in 79.40s (no regression vs PR #256
  baseline 373/373).
- `cd web/react-app && npm run build`: 0 errors / 20 chunks / 2.60s.
- `inst_eid_bridge_phase1b_eid_level.py` re-run (replicated against
  current DB; helper itself uses snapshot of investigation logic):

  | Metric | Pre-CP-4b | Post-CP-4b | Δ |
  |---|---:|---:|---:|
  | Total invisible brands | 1,337 | 1,337 | 0 |
  | TRUE_BRIDGE_ENCODED (≥1 hv2-counterparty rel) | 191 | 196 | **+5** |
  | Unbridged | 1,146 | 1,141 | −5 |
  | TRUE_BRIDGE_ENCODED AUM | $46,976.2B | $49,516.9B | **+$2,540.7B** |
  | Unbridged AUM | $24,615.8B | $22,075.1B | **−$2,540.7B** |

  TRUE_BRIDGE_ENCODED **delta is +5, not +6**: eid=2 (BlackRock /
  iShares, $15.7T fund AUM) was already TRUE_BRIDGE_ENCODED before
  this PR — it has an open `fund_sponsor` row to eid=3241
  (`relationship_id=153`, source=`parent_bridge`). The CP-4b-blackrock
  PR adds 5 new `wholly_owned` rows for the other 5 BlackRock
  sub-brands. Total BlackRock bridges to eid=3241 = **6** (5 new +
  1 pre-existing).

- BlackRock 6-way confirmation (post-write spot-check):

  | brand eid | brand | open rels to 3241 |
  |---:|---|---|
  | 7586  | BlackRock Fund Advisors                | (20815, 3241, 7586,  wholly_owned, control, CP-4b-blackrock-author\|pair=1\|...) |
  | 3586  | BLACKROCK ADVISORS LLC                 | (20816, 3241, 3586,  wholly_owned, control, CP-4b-blackrock-author\|pair=2\|...) |
  | 17970 | BlackRock Investment Management, LLC   | (20817, 3241, 17970, wholly_owned, control, CP-4b-blackrock-author\|pair=3\|...) |
  | 8453  | BLACKROCK FINANCIAL MANAGEMENT INC/DE  | (20818, 3241, 8453,  wholly_owned, control, CP-4b-blackrock-author\|pair=4\|...) |
  | 18030 | BlackRock International Limited        | (20819, 3241, 18030, wholly_owned, control, CP-4b-blackrock-author\|pair=5\|...) |
  | 2     | BlackRock / iShares                    | (153,   2,    3241,  fund_sponsor, advisory, parent_bridge) — pre-existing |

## Investigation-numbers drift note

Investigation snapshot (PR #254, 2026-05-02 18:43) → CP-4b execution
state (2026-05-02 22:00):

| Metric | PR #254 §4 | This PR | Drift cause |
|---|---:|---:|---|
| Total invisible brands | 1,225 | 1,337 | New invisible-brand surfacing post-PR #255 (CP-2) and post-CP-4a side-effects on rollup re-pointing |
| TRUE_BRIDGE_ENCODED (distinct) | 86 | 191 | PR #254 used a single-rel-per-brand inventory keyed off `rel_other_eid`; multi-rel brands undercount. Direct query against `entity_relationships` + `holdings_v2` returns the true 191. |
| Unbridged AUM | $26.0T (cohort) | $24.6T → $22.1T post-CP-4b | Combined effect of CP-4a $4.26T re-point + CP-4b-blackrock $2.54T bridge add |

**Implication for CP-4b-discovery:** the next read-only PR must derive
its top-20 manifest from the **current state**, not from
`data/working/inst_eid_bridge/eid_inventory.csv` snapshots. The CSV's
single-rel-per-brand structure undercounts existing bridges and would
mis-classify TRUE_BRIDGE_ENCODED brands as discovery candidates. CP-4b-
discovery should query `entity_relationships` directly with the
`(brand, hv2-counterparty)`-pair shape used in the Phase 0 audit here
(see `scripts/oneoff/inst_eid_bridge_blackrock_5_way.py` Phase 0 SQL
for the working pattern).

## Staging-workflow live status

`docs/staging_workflow_live.md` does not exist as a file. Memory entries
(`project_staging_workflow_live`) and several findings docs reference it
as if it does, but neither CP-4a (PR #256) nor this PR found a doc to
read; both wrote DIRECT to prod `entity_relationships` in single
transactions. The `entity_relationships_staging` table exists but has a
different schema (`id` auto-seq, `owner_name`, `ownership_pct`,
`conflict_reason`, `review_status` default `'pending'`, `reviewer`,
`reviewed_at`, `resolution`) — it is a human-review queue, not a
parallel write twin.

Status: **direct-prod-write is the live precedent for entity-layer
oneoff PRs** until a staging twin is built as its own architectural
workstream. ROADMAP entry annotated.

## Architecture / safety

- Single transaction across all 5 INSERTs.
- No `--reset` anywhere.
- No write-path module modified (`load_nport.py`, `load_13f_v2.py`,
  `classify_fund()`, `fetch_nport_v2.py` all untouched).
- Pre-flight backup at `data/backups/13f_backup_20260502_202932`.
- Pure new-row INSERT — no MERGE, no re-point, no SCD closure. Brand
  eids stay alive as canonical brand-name attribution sources.
- `entity_relationships` has no `notes` column; audit metadata encoded
  into the `source` field as
  `CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|pair=:N|pairing_source=investigation_§7.3|confidence=HIGH`.
- `relationship_id` assigned via `MAX(relationship_id) + N` per CP-4a
  precedent (no SEQUENCE/AUTO).

## Out-of-scope discoveries (NOT added to ROADMAP by this PR)

None surfaced. Phase 5 spot-checks all clean; no AT-side residuals to
worry about because CP-4b is INSERT-only (no closure of any other SCD
layer that would leave AT-side dangling references).

## Files

- `scripts/oneoff/inst_eid_bridge_blackrock_5_way.py`
- `data/working/inst_eid_bridge_blackrock_5_way_manifest.csv`
- `docs/findings/inst_eid_bridge_blackrock_5_way_dryrun.md` (Phase 2)
- `docs/findings/inst_eid_bridge_blackrock_5_way_results.md` (this doc)

ROADMAP + decisions doc updates land in the same squash commit per the
single-audit-trail directive.
