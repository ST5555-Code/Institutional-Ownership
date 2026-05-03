# Brand-vs-filer eid bridge — chat decisions

Locks the seven §9 open questions from
`docs/findings/inst_eid_bridge_investigation.md` (PR #254).
Decisions resolved 2026-05-02 in chat ahead of CP-4a / CP-4b /
CP-4c execution.

## BLOCKER 1 — Bridge mode for top-100: hybrid per-brand-shape

Classification rule (applied per brand in CP-4 manifest):

- Brand has a CIK and an independent SEC registration → **BRIDGE**.
  Action: AUTHOR_NEW_BRIDGE — insert `entity_relationships` row of
  type `wholly_owned` (`parent_entity_id = filer_eid`,
  `child_entity_id = brand_eid`). Read sites traverse via CP-5.
  Preserves brand-name display (iShares, BlackRock Fund Advisors,
  Wellington Management Co LLP).
- Brand is name-only, no CIK, synthetic → **MERGE**.
  Action: BRAND_TO_FILER — re-point `fund_holdings_v2` 4 rollup
  columns from `brand_eid` to `filer_eid`; close `brand_eid`
  `valid_to`; close brand-side `entity_relationships` and ECH
  rows. PR #251 ASA precedent.

Examples:

- Vanguard `eid=1` (no CIK, name-only) → `eid=4375`: MERGE.
- PIMCO `eid=30` (no CIK, name-only) → `eid=2322`: MERGE.
- BlackRock 6 sub-brand eids (each has its own CIK) → `eid=3241`:
  BRIDGE × 6.
- Wellington `eid=9935` (has CIK) → `eid=11220`: BRIDGE.
- Dimensional `eid=7` (has CIK) → `eid=5026`: BRIDGE.

## BLOCKER 2 — Pairing source for top-100 AUTHOR_NEW_BRIDGE: ADV-first then manual

For the ~14 of top-100 brands without an existing
`entity_relationships` row pointing to a holdings_v2 counterparty:

1. Form ADV cross-ref via `adv_managers` table. Authoritative SEC
   adviser registration data; pairs filer/brand identities
   without inference.
2. Residual where ADV cross-ref returns no match: manual pairing
   list authored in CP-4b prompt with named-brand inputs.

Rejected: regex / fuzzy-name match. The Calvert → "Stanley
Capital Management" anomaly (investigation §4.3) is the prototype
of fuzzy-match failure. False-positive risk at $27T scale is
unacceptable.

## BLOCKER 3 — PIMCO 13F gap: split into two items

Two distinct issues, two distinct treatments:

1. **Bridge the alias pair now.** `eid=30` → `eid=2322` in CP-4a
   as a standard BRAND_TO_FILER MERGE. Solves rollup attribution
   regardless of the ingestion gap. Both eids carry $0 filer AUM
   today, so the merge is consistent with current data.

2. **Surface the ingestion gap as separate P2 item.** CIK
   `0001163368` (PACIFIC INVESTMENT MANAGEMENT CO LLC) should
   appear in `holdings_v2.cik` and does not. Possible causes:
   form-13F-NT filtering, Allianz parent-rollup logic, known-
   broken filer pattern. Out of CP-4 scope. New ROADMAP item:
   `pimco-13f-ingestion-gap` (P2). Investigation-first,
   fix-second.

## Non-blockers

| # | Question | Disposition |
|---|----------|-------------|
| 4 | Calvert → "Stanley Capital Management" anomaly | Spot-check in CP-4b dry-run. If mis-merged, close existing `entity_relationships` row in same PR. |
| 5 | 31 orphan `entity_type='fund'` brands | Defer to `fund-holdings-orphan-investigation` (P2). Cross-reference in CP-4 results, do not action. |
| 6 | BlackRock sub-brand two-tier bridge | NO. Single-tier — every sub-brand bridges directly to `eid=3241`. Org-chart precision is not the goal; correct attribution is. Two-tier doubles read complexity for marginal accuracy. |
| 7 | Long-tail BRAND_ORPHAN (723 brands / $943B) | Defer to new P3 ROADMAP item: `inst-eid-bridge-orphan-triage`. Per-brand effort high, AUM low ($1.3B avg). Ship only if triggering display gap surfaces. |

## Sequencing post-decisions

CP-4a (BRAND_TO_FILER alias merges, 2 brands, S):
  Vanguard `eid=1` → `4375`
  PIMCO `eid=30` → `2322`
  ~~Plus 3 small alias-pairs surfaced during CP-4a Phase 1
  re-validation.~~ Phase 1 discovery returned zero qualifying
  candidates: only 4 `BRAND_HAS_NAME_MATCH` rows exist in
  `data/working/inst_eid_bridge/eid_inventory.csv`, all
  MEDIUM/LOW confidence with brand_name significantly
  different from filer_name (Aperio/Ascent, Altaba/Alphabet,
  Oaktree/Olstein, Robinson/Revelation) — exactly the
  Calvert → "Stanley Capital Management" false-positive
  prototype rejected by BLOCKER 2 above. Per prompt
  instruction, no synthesis from lower-confidence tiers.
  Pattern: PR #251 ASA fix shape, **adapted** — Phase 1
  re-validation surfaced 5 schema corrections to the
  original op shape (entities has no valid_to; OP A reduced
  to (rollup_entity_id, dm_rollup_entity_id, dm_rollup_name)
  scope; OP A WHERE uses OR on both rollup columns; OP B
  re-points fund_sponsor edges rather than closing them;
  OPs F + G added for entity_rollup_history close +
  entity_aliases re-point with filer-side preferred-conflict
  demotion). See `docs/findings/inst_eid_bridge_aliases_dryrun.md`.
  Pre-cycle eligible. Pre-flight: backup, app-off.
  **Shipped 2026-05-02** ([#256](https://github.com/ST5555-Code/Institutional-Ownership/pull/256)).
  Vanguard 267,751 rows / $2,541.53B + PIMCO 289,132 rows /
  $1,717.00B = 556,883 fund_holdings_v2 rows / ~$4.26T
  re-pointed; AUM conservation Δ = $0.000000B per pair.
  See `docs/findings/inst_eid_bridge_aliases_results.md`.

  **Op F clarification (added post-execution per chat 2026-05-02):**
  Op F as originally specified closed `entity_rollup_history` rows
  where `entity_id = brand_eid` (FROM-side). Phase 5 surfaced an
  AT-side residual: rows where `rollup_entity_id = brand_eid` (other
  entities rolling up TO the deprecated brand) were not closed,
  leaving `entity_current.rollup_entity_id` stale for filer 2322
  and 220 fund_eids. Resolved in the same PR via **Op H** —
  general fund-tier AT-side re-point (close + insert at filer
  preserving `rule_applied`/`confidence`/`source`) plus
  filer-self-rollup recreate (`rule_applied='self'`,
  `source='CP-4a-merge:inst-eid-bridge-fix-aliases'`). Standard
  op shape for any future BRAND_TO_FILER merge: BOTH Op F
  (FROM-side) AND Op H (AT-side) are required to fully invalidate
  the brand_eid's rollup-history footprint.

CP-4b (AUTHOR_NEW_BRIDGE, top-25 by AUM, M):
  86 TRUE_BRIDGE_ENCODED brands need no `entity_relationships`
  write, only CP-5 read traversal.
  ~25 hv2-counterparty-discoverable AUTHOR_NEW_BRIDGE writes via
  staging→sync→promote per `staging_workflow_live.md`.
  Pre-cycle eligible.

CP-4c (AUTHOR_NEW_BRIDGE, next-75 of top-100, M):
  Manual pairing list + `adv_managers` cross-ref.
  Post-cycle (Q1 2026 13F cycle ~May 15) — needs cycle data
  to surface any new fund-tier rollup targets.

CP-5 (`parent-level-display-canonical-reads`):
  Depends on CP-4a + CP-4b minimum (~$24T of $27.8T bridged).
  CP-4c parallelizable.

CP-2 (`ingestion-manifest-reconcile`):
  No eid-layer dependency on CP-1 per investigation §8.2. Can
  ship in parallel with CP-4a.
