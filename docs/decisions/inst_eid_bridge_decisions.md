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

### BLOCKER 2 — addendum (cp-4b-blocker2-corroboration-probe, 2026-05-03)

The four-signal corroboration probe (X1 normalized name equality, X2
entity_aliases cross-link, X3 CIK reuse, X4 N-CEN cross-link) was tested
against the 19 LOW LOW residual cohort ($11.44T) from cp-4b-discovery.
Result: 6 brands surfaced corroborating signals; 2 of 6 were false
positives driven by suffix-stripping normalization collapsing unrelated
sub-entities onto the same stem (Transamerica AM → Transamerica Financial
Advisors LLC; PIMCO → unrelated "PACIFIC"-stem firms).

BLOCKER 2 strict rule REMAINS in force. Multi-signal corroboration is
NOT sufficient to author bridges at-scale.

CARVE-OUT (4 manually-verified brands, split into 3 PRs per chat
decision 2026-05-03):

  - **cp-4b-author-first-trust** (this PR, [#TBD](https://github.com/ST5555-Code/Institutional-Ownership/pulls)):
    brand eid 8 (First Trust) → filer eid 136 (FIRST TRUST ADVISORS LP)
    via `wholly_owned` / `control`. $232.7B fund AUM bridged. BRIDGE
    shape per PR #267 (cp-4b-author-trowe) precedent. `confidence='medium'`,
    `source='CP-4b-author-first-trust|...|signals=X1+X2|public_record_verified=...'`.
    Single INSERT into entity_relationships, no SCD closure, no
    fund_holdings_v2 re-point, no recompute.

  - **cp-4b-merge-fmr-ssga** (next): two-pair MERGE following PR #256
    (CP-4a Vanguard/PIMCO) precedent. Re-points `fund_holdings_v2`
    from brand eids 11 (Fidelity / FMR) and 3 (State Street / SSGA)
    to filer eids 10443 (FMR LLC) and 7984 (State Street Corp)
    respectively. Closes brand-side `entity_relationships`,
    `entity_aliases` re-point with filer-side preferred-conflict
    demotion, and runs both Op F (FROM-side `entity_rollup_history`
    close) and Op H (AT-side `entity_rollup_history` re-point with
    filer-self-rollup recreate). ~$717.2B combined.

  - **Equitable IM** (brand eid 2562 → candidate eid 9526):
    DEFERRED to `cp-4c-manual-sourcing`. Methodology there resolves
    the public-parent-vs-operating-IA question correctly via 10-K
    Item 1 subsidiary lists. Eid 9526 is Equitable Holdings Inc. —
    the public parent — and may not be the correct operating-filer
    counterparty under the operating-AM rollup policy.

DEFER: the remaining 15 brands (Bucket C residual + Bucket D, ~$10.27T)
to a manual-sourcing arc (`cp-4c-manual-sourcing`) using 10-K subsidiary
schedules, ADV Schedule A/B parsing, or curated public-record mapping.
Includes Equitable IM. The strict-ADV cross-ref methodology cannot
author them without unacceptable false-positive risk at the $11T scale.

Failure modes the probe exposed (do not propose for general adoption):

  - X1 alone (any single-token stem) — collides on common business
    namespace words.
  - X4 sub-probe 4c (multi-adviser registrant) — pattern indicator,
    no candidate filer; not a corroboration signal.
  - 2-signal corroboration without manual verification — Transamerica
    proves this fails on aggressive suffix-stripping.

Cross-ref: [docs/findings/cp-4b-blocker2-corroboration-probe.md](../findings/cp-4b-blocker2-corroboration-probe.md).

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

CP-4b (AUTHOR_NEW_BRIDGE, originally top-25 by AUM, split into 3 sub-PRs per chat 2026-05-02):
  86 (now 191 per current-state requery) TRUE_BRIDGE_ENCODED brands
  need no `entity_relationships` write, only CP-5 read traversal.

  **Path-B split per chat 2026-05-02.** Phase 0 of the original
  CP-4b prompt surfaced two contradictions: (1) the Phase 0.3
  filter (`counterparty NOT in hv2`) selects a different cohort
  than the spec's cited examples — the §4.3 list (Wellington
  9935→11220, Dimensional 7→5026, Franklin 28→4805, T. Rowe Price
  13→4627, etc.) is exactly the TRUE_BRIDGE_ENCODED cohort that
  needs no writes; (2) investigation numbers have drifted post-
  CP-4a — invisible brands 1,225 → 1,337; brands with ≥1 hv2-
  counterparty rel 86 → 191; unbridged AUM ~$26.0T → $24.6T. Per-
  brand discovery for the unbridged-cohort brands needs ADV cross-
  ref + parent-corp lookup that the original prompt did not supply.
  Resolution:

  - **CP-4b-blackrock** (S, pre-cycle): 5 mechanically-discoverable
    BlackRock sub-brand `wholly_owned` bridges to filer eid=3241
    via direct prod write (single transaction). Pairings come
    direct from investigation §7.3 with the eid=2 fund_sponsor
    pre-existing-bridge note layered in. **Shipped 2026-05-02**
    ([#258](https://github.com/ST5555-Code/Institutional-Ownership/pull/258)).
    5 new entity_relationships rows (relationship_id 20815–20819);
    $2,540.70B fund AUM bridged; TRUE_BRIDGE_ENCODED 191 → 196 (Δ
    +5, not +6 — eid=2 pre-existing per CP-4a discovery); Total
    BlackRock bridges to 3241 = 6 (5 new + 1 pre-existing).
    `peer_rotation_flows` Δ 0 (BRIDGE preserves brand-side
    attribution). pytest 373/373; npm build clean. See
    `docs/findings/inst_eid_bridge_blackrock_5_way_results.md`.

  - **CP-4b-discovery** (S, pre-cycle, read-only): per-brand filer
    pairings for top-20 AUTHOR_NEW_BRIDGE candidates by AUM,
    derived from `adv_managers` ADV cross-ref + parent-corp lookup.
    Confidence-tiered manifest. **Pending — separate session.**
    Manifest must derive from current state (direct query against
    `entity_relationships` + `holdings_v2`), not from
    `data/working/inst_eid_bridge/eid_inventory.csv` snapshots
    (single-rel-per-brand structure undercounts existing bridges).

  - **CP-4b-author-top20** (M, pre-cycle, execution): apply
    CP-4b-discovery manifest pairings as new entity_relationships
    rows. **Pending — depends on CP-4b-discovery.**

  Same shape as PR #249 (cef-scoping) → PR #251 (cef-asa-flip-and-
  relabel) precedent.

  **Staging-workflow note (added 2026-05-02 per CP-4b-blackrock
  results):** `docs/staging_workflow_live.md` does not exist as
  a file. CP-4a (PR #256) and CP-4b-blackrock (PR #258) both wrote
  direct to prod `entity_relationships` in single transactions.
  The `entity_relationships_staging` table has a different schema
  (id auto-seq, owner_name, ownership_pct, conflict_reason,
  review_status default 'pending', reviewer, reviewed_at,
  resolution) — it is a human-review queue, not a parallel write
  twin. Direct-prod-write is the live precedent for entity-layer
  oneoff PRs until a staging twin is built as its own
  architectural workstream.

CP-4c (AUTHOR_NEW_BRIDGE, next-75 of top-100, M):
  Manual pairing list + `adv_managers` cross-ref.
  Post-cycle (Q1 2026 13F cycle ~May 15) — needs cycle data
  to surface any new fund-tier rollup targets.

CP-5 (`parent-level-display-canonical-reads`):
  Depends on CP-4a + CP-4b-blackrock + CP-4b-author-top20 minimum
  (~$24T of $27.8T bridged). CP-4c parallelizable.

CP-2 (`ingestion-manifest-reconcile`):
  No eid-layer dependency on CP-1 per investigation §8.2. Can
  ship in parallel with CP-4a.

## MERGE op-shape extension — Adjustment 1 (close-on-collision in Op G)

Added 2026-05-05 with `cp-5-adams-duplicates` (Adams cohort,
first P0 pre-execution PR per CP-5 comprehensive remediation).

cp-4a precedent (PR #256, Vanguard/PIMCO MERGE) established
the 8-op shape (A, B, B', C, E, F, G, H) but did NOT
encounter PK collisions on `entity_aliases` re-point because
Vanguard/PIMCO each had at most 1 duplicate per canonical and
the alias_names were distinct.

Adams duplicates (PR `cp-5-adams-duplicates`, 7 pairs across 3
canonicals) encountered PK collisions where
`(canonical, alias_name, alias_type, valid_from)` already
exists. Two cases:

  1. **Direct collision**: duplicate's alias is identical to
     canonical's existing alias. Pair 1 (4909 ← 19509) hits
     this — both eids hold `('Adams Asset Advisors, LLC',
     'brand', 2000-01-01)` with `is_preferred=TRUE`.
  2. **Chained collision**: pair N's duplicate alias is
     identical to pair M's just-re-pointed alias (M < N,
     same canonical). Pairs 3/4 (canonical 2961) and pairs
     6/7 (canonical 6471) hit this — pair 2 / pair 5
     re-point first, then 3/4 / 6/7 collide against the
     just-re-pointed mixed-case alias.

`entity_aliases` PK is `(entity_id, alias_name, alias_type,
valid_from)`. Re-pointing `entity_id` cannot be retried or
salvaged once a PK conflict exists.

### Adjustment 1 — Op G extended logic

Per duplicate-side alias D, before re-pointing:

  collision = EXISTS (
    SELECT 1 FROM entity_aliases
    WHERE entity_id = canonical_eid
      AND alias_name = D.alias_name
      AND alias_type = D.alias_type
      AND valid_from = D.valid_from
      AND valid_to = DATE '9999-12-31'
  )

  IF collision:
    Branch CLOSE-ON-COLLISION:
      UPDATE entity_aliases SET valid_to = CURRENT_DATE
      WHERE entity_id = duplicate_eid
        AND alias_name = D.alias_name
        AND alias_type = D.alias_type
        AND valid_from = D.valid_from
        AND valid_to = DATE '9999-12-31';
      (Canonical's existing alias preserved; duplicate's
      redundant. No demotion changes on canonical.)

  ELSE:
    Branch RE-POINT (cp-4a precedent + scoped preferred-
    conflict resolution):
      IF D.is_preferred AND canonical has open
      `is_preferred=TRUE` alias of same `alias_type` AND
      `alias_name != D.alias_name`:
        Demote those canonical preferred=TRUE rows (set
        `is_preferred=FALSE`).
      UPDATE entity_aliases SET entity_id = canonical_eid
      WHERE entity_id = duplicate_eid
        AND alias_name = D.alias_name
        AND alias_type = D.alias_type
        AND valid_from = D.valid_from
        AND valid_to = DATE '9999-12-31';

This is a SUPERSET of cp-4a Op G: cases that didn't collide
in cp-4a still re-point as before; cases that would collide
(which cp-4a couldn't have hit at scale) close cleanly.

### Pair processing order

Chained-collision pairs require pair-ordering within a single
transaction. Process pairs by `(canonical_eid, pair_id)`
ascending so pair M re-points before pair N re-points/closes
against pair M's row. Demotion in the RE-POINT branch is
scoped to `alias_name != D.alias_name` so pair N's
re-pointed-by-M row is not unset when pair N processes its
own (now-collision-bound) duplicate.

### Scope of canonical state

Adjustment 1 is canonical for all future MERGE work:

  - cp-5-cycle-truncated-merges (21 pairs across 2-3 batched
    PRs, CP-5 P0 pre-execution scope) — chained-collision
    expected throughout;
  - hypothetical institutional-merge passes that group
    multiple eid families;
  - any cp-4a/4b/4c/cp-5 successor merges where >1 duplicate
    per canonical exists or alias_names are not distinct.

Single-duplicate-per-canonical merges (cp-4a Vanguard/PIMCO)
are unaffected — collision check returns false and the
RE-POINT branch matches cp-4a literally.

### References

- PR #256 (cp-4a precedent — `inst-eid-bridge-fix-aliases`)
- PR `cp-5-adams-duplicates` (Adams cohort, first
  Adjustment 1 application, 7 pairs)
- `docs/findings/cp-5-adams-duplicates-results.md` (concrete
  per-pair op counts, including `op_g_closed` distinct from
  `op_g_repointed`)
