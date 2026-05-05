# cp-5-cycle-truncated-merges — Phase 1 Recon Results

**Date:** 2026-05-05
**Branch:** `cp-5-cycle-truncated-merges-recon`
**HEAD baseline:** `86a2409` (PR #283 cp-5-adams-duplicates)
**Methodology:** Read-only. Reproduces Bundle B Phase 2.1 cycle detection via
`scripts/oneoff/cp_5_bundle_b_common.build_inst_to_tp` (cycle-safe inst→top-parent
climb under `control_type IN ('control','mutual','merge')`), pairs cycle entities
via SCC traversal of the deduplicated parent-edge map, and applies cp-5-adams
selection rules + cp-4a op-shape audit framework.

**Refs:**
- [docs/findings/cp-5-bundle-b-discovery.md §2.2](cp-5-bundle-b-discovery.md)
- [docs/findings/cp-5-comprehensive-remediation.md §3.1](cp-5-comprehensive-remediation.md)
- [docs/findings/cp-5-adams-duplicates-results.md](cp-5-adams-duplicates-results.md) (PR #283)
- [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (cp-4a + Adjustment 1 op-shape)
- Recon: [scripts/oneoff/cp_5_cycle_truncated_merges_recon.py](../../scripts/oneoff/cp_5_cycle_truncated_merges_recon.py)
- Outputs: [pair-manifest.csv](../../data/working/cp-5-cycle-truncated-pair-manifest.csv),
  [collision-matrix.csv](../../data/working/cp-5-cycle-truncated-collision-matrix.csv),
  [pre-merge-state.csv](../../data/working/cp-5-cycle-truncated-pre-merge-state.csv)

---

## 1. Cohort re-validation

**Result:** 21 cycle-truncated entities, drift 0.0% from Bundle B baseline.
SCC traversal yields **10 distinct 2-cycles → 10 merge pairs** (one entity per
cycle slot). Confirms Bundle B §2.2's "21 entities → ~10-11 pairs" framing,
landing at the lower bound. No 3+-cycles surfaced.

**Wording correction vs the recon prompt:** the prompt described the cohort as
"21 cycle-truncated pairs"; both Bundle B §2.2 and remediation §3.1 say "21
entities → ~10-11 pairs". This recon resolves it: **21 entities = 10 pairs.**

The 21 entities, listed here for orientation:

| eid | type | cik | name |
| ---: | --- | --- | --- |
| 22 | institution | – | Goldman Sachs Asset Management |
| 17941 | institution | – | Goldman Sachs Asset Management, L.P. |
| 58 | institution | – | Lazard Asset Management |
| 18070 | institution | – | Lazard Asset Management LLC |
| 70 | institution | – | Ariel Investments |
| 18357 | institution | – | Ariel Investments, LLC |
| 893 | institution | 0000728100 | LORD, ABBETT & CO. LLC |
| 17916 | institution | – | Lord, Abbett & Co. LLC |
| 1600 | institution | 0001731169 | Financial Partners Group, Inc |
| 9722 | institution | 0001965246 | Financial Partners Group, LLC |
| 2562 | institution | 0001965856 | Equitable Investment Management, LLC |
| 9668 | institution | 0001536185 | Equitable Investment Management Group, LLC |
| 2925 | institution | 0001145020 | THORNBURG INVESTMENT MANAGEMENT INC |
| 18537 | institution | – | Thornburg Investment Management, Inc. |
| 7558 | institution | 0000937729 | Fayez Sarofim & Co |
| 18029 | institution | – | Fayez Sarofim & Co., LLC |
| 7655 | institution | 0000924181 | LEAVELL INVESTMENT MANAGEMENT, INC. |
| 18649 | institution | – | Leavell Investment Management, Inc. |
| 10501 | institution | 0001600035 | Stonebridge Capital Advisors LLC |
| 19846 | institution | – | Stonebridge Capital Advisors, LLC |
| 858 | institution | 0000230518 | Sarofim Trust Co |

**Note on Sarofim Trust Co (eid 858).** Despite appearing in Phase 2.1's
cycle-truncated set, eid 858's 2-cycle partner via SCC traversal lands on
eid 7558 (Fayez Sarofim & Co), not on eid 18029 — explained below in §3.

---

## 2. Pair manifest

10 pairs, all clean 2-cycles. Selection rule precedence:
1. Active 13F filer (holdings_v2 rows > 0)
2. Greater AUM among active filers
3. Greater fund_holdings_v2 rollup footprint
4. Lowest eid (tie-break)

| pair | canonical | duplicate | rule | canonical name | duplicate name | dup fh-AUM $B | dup 13F-AUM $B |
| ---: | ---: | ---: | --- | --- | --- | ---: | ---: |
| 1 | 22 | 17941 | rule 3 fh footprint | Goldman Sachs Asset Management | Goldman Sachs Asset Management, L.P. | 46.501 | 0.000 |
| 2 | 58 | 18070 | rule 3 fh footprint | Lazard Asset Management | Lazard Asset Management LLC | 0.000 | 0.000 |
| 3 | 70 | 18357 | rule 3 fh footprint | Ariel Investments | Ariel Investments, LLC | 0.000 | 0.000 |
| 4 | 893 | 17916 | rule 1 active filer | LORD, ABBETT & CO. LLC | Lord, Abbett & Co. LLC | 0.000 | 0.000 |
| 5 | 1600 | 9722 | rule 1 active filer | Financial Partners Group, Inc | Financial Partners Group, LLC | 0.000 | 0.507 |
| 6 | 2562 | 9668 | rule 3 fh footprint | Equitable Investment Management, LLC | Equitable Investment Management Group, LLC | 0.000 | 0.000 |
| 7 | 2925 | 18537 | rule 1 active filer | THORNBURG INVESTMENT MANAGEMENT INC | Thornburg Investment Management, Inc. | 0.000 | 0.000 |
| 8 | 7558 | 18029 | rule 1 active filer | Fayez Sarofim & Co | Fayez Sarofim & Co., LLC | 2.104 | 0.000 |
| 9 | 7655 | 18649 | rule 1 active filer | LEAVELL INVESTMENT MANAGEMENT, INC. | Leavell Investment Management, Inc. | 0.000 | 0.000 |
| 10 | 10501 | 19846 | rule 1 active filer | Stonebridge Capital Advisors LLC | Stonebridge Capital Advisors, LLC | 2.341 | 0.000 |

Zero ambiguous-selection flags — all rule applications had clear winners.

**All 10 cycle edges are uniformly shaped** as `(control_type='control',
relationship_type='wholly_owned', source='orphan_scan')` — the orphan-scan
loader created mutual-control edges in both directions, producing the
2-cycles. relationship_id pairs (per `inst_inst_relationship_ids` column in
the manifest CSV):

| pair | rel_id (canon→dup) | rel_id (dup→canon) |
| ---: | ---: | ---: |
| 1 | 15227 | 15230 |
| 2 | 15223 | 15224 |
| 3 | 15254 | 15256 |
| 4 | 15101 | 15123 |
| 5 | 15214 | 15215 |
| 6 | 15239 | 15240 |
| 7 | 15102 | 15189 |
| 8 | 15103 | 15265 |
| 9 | 15112 | 15136 |
| 10 | 15113 | 15177 |

---

## 3. Sarofim singleton — clarification

The recon's SCC traversal returns 21 cycle-truncated entities forming **10
two-cycles**, plus eid 858 (Sarofim Trust Co) which traces to the same cycle
as eid 7558 → eid 18029 (Fayez Sarofim & Co ↔ Fayez Sarofim & Co., LLC). 858
is not itself a cycle slot — its parent edge points into the Sarofim cycle but
it is not a cycle member. Bundle B §2.2's `build_inst_to_tp` flagged 858 as
cycle-truncated because its climb terminates inside that cycle.

The recon includes 858 in baseline collection but does not assign it to a
merge pair. **Treatment recommendation for 858:** out of scope for the
cycle-merge cohort; flag for separate triage as a non-cycle entity that's
mis-rolled. Likely needs its own bridge/relationship cleanup separate from
this cohort.

---

## 4. Pair-shape categorization

**Category I (1 duplicate per canonical):** 10 pairs.
**Category II (2+ duplicates per canonical):** 0 pairs.

Every canonical has exactly one duplicate. **Adjustment 1 close-on-collision
logic from PR #283 is structurally not exercised by this cohort** — but the
execute PR should still implement it for safety / consistency with Adams
precedent.

This is a meaningful simplification from the prompt's anticipated split: the
prompt sized 6-11 Category II pairs based on Bundle B examples. Reality:
zero. **Recommended PR sizing: single batched execute PR for all 10 pairs.**

---

## 5. Collision pattern enumeration

Cohort-level totals across 10 pairs / 10 duplicate-side aliases:
- **DIRECT_COLLISION: 0**
- **WILL_RE_POINT: 10**
- **CHAINED_COLLISION_RISK: 0**

Each duplicate has exactly 1 open alias (the entity's own canonical_name),
which differs from the canonical's alias (different casing / suffix). All 10
will re-point cleanly via Op G branch RE-POINT.

**Preferred-conflict pre-image:** 10 of 10 pairs have `canonical_side_preferred=true`
AND `duplicate_side_preferred=true`. Op G demote logic (cp-4a precedent) will
fire on every pair: when re-pointing the duplicate's preferred alias to canonical
where canonical already has a different preferred alias, demote the canonical's
existing preferred to FALSE.

---

## 6. Inverted-rollup audit

Cohort-level rollup direction classification:
- **DUPLICATE_TO_CANONICAL: 10** (all 10 pairs)
- INVERTED: 0
- AMBIGUOUS_BOTH_DIRECTIONS: 0

Every duplicate currently rolls up to its paired canonical via
`entity_rollup_history.rollup_entity_id`. **Op H Branch 2 (canonical
self-rollup recreate) is not needed for any pair.**

Op H Branch 1 (general AT-side re-point) IS needed for several pairs where
the duplicate is the rollup target of fund entities. Per-pair Branch 1
scope from `open_erh_at` baseline:

| pair | duplicate eid | open_erh_at (Branch 1 work) |
| ---: | ---: | ---: |
| 1 | 17941 | 64 |
| 2 | 18070 | 6 |
| 3 | 18357 | 0 |
| 4 | 17916 | 1 |
| 5 | 9722 | 0 |
| 6 | 9668 | 0 |
| 7 | 18537 | 0 |
| 8 | 18029 | 9 |
| 9 | 18649 | 0 |
| 10 | 19846 | 8 |

**Branch 1 total: 88 ERH AT-side rows to re-point across the cohort.** Note:
the duplicate's own self-row (entity_id=duplicate, rollup_entity_id=duplicate)
appears in `open_erh_from` (=2 per duplicate, the two `rollup_type` siblings)
and is closed by Op F, not Branch 1.

---

## 7. Pre-merge state baselines (cohort-level summary)

| metric | canonical sum | duplicate sum |
| --- | ---: | ---: |
| holdings_v2 13F AUM | $279.16B | $0.51B |
| fund_holdings_v2 rollup AUM | $2,011.01B | $50.95B |
| holdings_v2 row count | 12,389 | 169 |
| fund_holdings_v2 rollup row count | 418,288 | 27,729 |

**Total cohort fund-tier AUM impact (transferred to canonicals): $50.95B.**
Goldman pair (17941 → 22) carries 91% of that ($46.5B / 25,067 fh_rollup
rows). Op A scope concentrates on Goldman.

Notable entity-level gradients:
- Canonical 22 (Goldman): largest fh_rollup footprint at $782.7B / 124,984 rows.
- Canonical 7558 (Sarofim): largest 13F footprint at $166.7B / 2,280 rows.
- Duplicate 17941: 132 open child relationships (Op B re-point scope) and
  64 open ERH AT-side rows (Op H Branch 1 scope).
- Duplicate 9668 (Equitable): 111 open child relationships — largest Op B
  scope of any duplicate.
- Duplicate 9722 (Financial Partners): the only duplicate with active 13F
  holdings (169 rows / $0.507B). Requires holdings_v2 re-point op.

Per-pair detail in [pre-merge-state.csv](../../data/working/cp-5-cycle-truncated-pre-merge-state.csv).

---

## 8. Op-shape deviations from Adams (PR #283) precedent

The cycle-truncated cohort differs from Adams in three load-bearing ways
that require execute-PR adjustments:

### 8.1 Op B' — TWO subsumed cycle edges per pair (not 0/1)

Adams's `Op B'` raises `RuntimeError` if more than one canonical↔duplicate
edge exists. Every cycle pair has **exactly two** edges (both directions of
the cycle). All 20 cycle edges have shape
`(control, wholly_owned, orphan_scan)` so there's no semantic distinction
between them.

**Required adjustment:** loosen Op B' assertion to `len(subsumed) <= 2`,
close both edges, and capture both relationship_ids in the Op E audit-row
`source` string (e.g.,
`subsumes:control/22->17941/orphan_scan;control/17941->22/orphan_scan`).

### 8.2 Holdings_v2 re-point — Pair 5 only

Adams's `Op A` only re-points `fund_holdings_v2.rollup_entity_id` /
`dm_rollup_entity_id`; it explicitly skips `entity_id` and `dm_entity_id`
because Adams duplicates were fund-typed and never carried as 13F filer
identity. **Pair 5 (Financial Partners 1600 ← 9722) is different:** the
duplicate is itself an active 13F filer with 169 holdings_v2 rows / $0.507B.

**Required adjustment:** add an `Op A2` step that re-points
`holdings_v2.entity_id` from duplicate → canonical, scoped to pair 5 only.

### 8.3 CIK transfer — Pair 5 only

Per memory rule "Always transfer CIK in batch merges — INSERT on survivor
before closing source" (~$166B INF4c lesson): pair 5 has different CIKs on
each side (1600 = 0001731169, 9722 = 0001965246). The merge should add
0001965246 to canonical 1600 as a second CIK before closing the duplicate's
identifier rows.

All other 9 pairs have the duplicate without a CIK (only canonical carries
one), so CIK transfer is a no-op for them.

### 8.4 Op A re-point scope is non-trivial for 5 pairs (vs no-op for Adams pairs 2-7)

Adams pairs 2-7 had `fh_dup_rows=0` (Op A no-op). This cohort has substantial
duplicate-side fh_v2 footprint:

| pair | dup eid | dup fh_rollup_rows | dup fh_dmrollup_rows |
| ---: | ---: | ---: | ---: |
| 1 | 17941 | 25,067 | 53,380 |
| 2 | 18070 | 0 | 5,158 |
| 3 | 18357 | 0 | 0 |
| 4 | 17916 | 0 | 1,832 |
| 5 | 9722 | 0 | 0 |
| 6 | 9668 | 0 | 0 |
| 7 | 18537 | 0 | 0 |
| 8 | 18029 | 795 | 1,742 |
| 9 | 18649 | 0 | 0 |
| 10 | 19846 | 1,042 | 1,042 |

**Op A is meaningful for pairs 1, 2, 4, 8, 10.** Total fund_holdings_v2 row
re-point: 25,862 `rollup_entity_id` rows + 63,154 `dm_rollup_entity_id` rows
(some may overlap). The Adams-shape Op A SQL handles this correctly without
changes.

---

## 9. Execute PR sizing recommendation

Per chat decision 2026-05-05 (recon-first split):

**Recommended:** single batched execute PR for all 10 pairs.

**Rationale:**
- All 10 pairs are Category I (no chained-collision risk requiring Adjustment 1).
- All 10 cycle edges are uniformly shaped (consistent Op B' treatment).
- 88 ERH AT-side re-points + 5 non-trivial Op A re-points + 1 Op A2
  (holdings_v2) is well within transactional scope; the Adams 7-pair PR
  successfully wrapped all ops in a single BEGIN/COMMIT.
- Splitting into "simple" vs "Goldman-only" or "Goldman + others" creates
  no review-load benefit — the per-pair complexity gradient is smooth.
- Single PR matches PR #283 cadence (7 pairs / single transaction).

**Pre-execution prompts needed:** 1.

If chat decides to split anyway, the natural seam is:
- Batch A (5 pairs): pairs 3, 5, 6, 7, 9 — duplicate has zero fh_v2 footprint
  (Op A no-op).
- Batch B (5 pairs): pairs 1, 2, 4, 8, 10 — duplicate has fh_v2 footprint
  requiring Op A.

But Batch A is a degenerate case — review burden ≈ Adams pair 2-7. Single PR
is the cleaner option.

---

## 10. Chat decisions needed before execute PR is written

Consolidated, in priority order:

1. **Op B' adjustment to handle 2 cycle edges per pair (load-bearing).** Adams
   asserts ≤1; cohort has exactly 2 in every pair. Recommended: loosen to ≤2,
   close both, capture both rel_ids in audit-row source. (See §8.1.)

2. **Op A2 — holdings_v2.entity_id re-point for Pair 5 only.** Add a new op
   between Op A and Op B that handles the 169-row duplicate-side 13F
   footprint. (See §8.2.)

3. **CIK transfer for Pair 5.** INSERT 0001965246 onto canonical 1600 as a
   second CIK row before closing duplicate 9722's identifier rows. (See §8.3.)
   This needs a new op between Op C and Op E (call it Op C').

4. **Sarofim Trust Co (eid 858) treatment.** Not a cycle pair member — its
   climb terminates inside the Sarofim 7558↔18029 cycle. Recommend leaving
   out of this PR; route to a separate triage. (See §3.)

5. **Capital Group umbrella interaction.** Bundle B §1.3 noted Capital Group
   is the only multi-filer-arm umbrella pattern. None of its eids (12, 6657,
   7125, 7136) appear in this cycle-truncated cohort, so no interaction. No
   action needed.

**Non-blocking observations (no chat decision required):**
- Adjustment 1 close-on-collision logic from PR #283 still implemented
  defensively, but never exercised at runtime (zero direct collisions across
  cohort).
- Op H Branch 2 (canonical self-rollup recreate) never invoked (zero inverted
  rollups). Code path remains in place for safety.
- All canonicals already carry their own self-rollup row (per `rollup_self_rows`
  audit in pre-merge-state.csv); merge does not need to introduce one.

---

## 11. Out-of-scope discoveries

- **Sarofim Trust Co (eid 858) classification.** The entity has CIK
  0000230518, 0 holdings_v2 rows, 0 fh_v2 footprint, 1 open ECH, 0 open
  aliases, 0 open rels (parent or child). It's a near-empty institution
  whose climb hits the Sarofim 7558 cycle. Likely a legitimate distinct
  legal entity (Sarofim Trust Company is a separate trust company affiliate)
  or a stale stub. Out of scope for this cohort.
- **`source='orphan_scan'` is the universal lineage** for all 20 cycle
  edges. Suggests the orphan-scan loader is generating mutual-control edges
  systematically when it encounters two unlinked institutions with similar
  names. Worth a Bundle C-style follow-up to harden the loader's guard
  against creating cycles. Backlog candidate.
- **Equitable Investment Management Group (eid 9668) has 111 open child
  relationships** while having $0 13F and $0 fh_v2 footprint. Means it is
  effectively a routing hub: 110+ funds parent through it. Op B will fan
  these all to canonical 2562. Worth confirming post-merge that 2562's child
  count grows accordingly.
- **Goldman canonical (eid 22) has 258 open ERH AT-side rows** — the largest
  rollup-target in the cohort. Goldman's fh_v2 routing is heavily
  concentrated.
- **Naming pattern is uniform:** every cycle pair is `<NAME>` ↔ `<NAME>,
  LLC` or `<NAME>` ↔ `<NAME>, L.P.`. The orphan-scan loader appears to have
  created the duplicate for each entity once the legal-suffix variant
  registered (e.g., when the LLC form filed with SEC). Loader hardening
  should treat normalized-name match as a duplicate signal, not create a
  new entity.

---

## 12. Recon completeness sign-off

- ✓ Cohort drift validated (0.0%, 21 entities)
- ✓ All 10 pairs identified, canonical/duplicate selected per Phase 1c rules
- ✓ Category split confirmed (10 Category I / 0 Category II)
- ✓ Collision matrix enumerated (0 direct, 10 re-point, 0 chain risk)
- ✓ Rollup direction classified (10 DUPLICATE_TO_CANONICAL, 0 inverted/ambiguous)
- ✓ Per-pair pre-merge baselines captured (CSV)
- ✓ Op-shape deviations from Adams documented (3 load-bearing changes)
- ✓ Execute PR sizing recommended (1 batched PR)
- ✓ Chat-blocking decisions surfaced (4 items, all design-side not data-side)

Recon is complete. Ready for chat-side review and execute-PR authoring.
