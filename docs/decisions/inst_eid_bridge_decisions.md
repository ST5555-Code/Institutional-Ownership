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


---

## MERGE op-shape extension — Adjustment 2 (Op A.3 `holdings_v2.entity_id` re-point)

Authored: PR `cp-5-cycle-truncated-merges` (2026-05-05, 10-pair
cohort).

### Problem

cp-4a precedent (PR #256, Vanguard + PIMCO brand→filer bridge)
and Adjustment 1 (PR #283, Adams 7-pair) Op A only re-points
`fund_holdings_v2` rollup columns. Neither cohort had
duplicates with direct 13F holdings under the `entity_id`
column — fund eids were FUND identity (not institutional-tier)
in Adams, and brand_eids in cp-4a had brand-tier semantics not
filer identity.

cp-5-cycle-truncated-merges Pair 5 (Financial Partners Group,
Inc 1600 ← Financial Partners Group, LLC 9722) has 169 rows /
$0.5067B of direct 13F filings under duplicate's
`holdings_v2.entity_id`. Without a dedicated re-point, the
duplicate would retain those rows post-merge — an inconsistent
state where the duplicate is otherwise deprecated.

### Adjustment 2 (codified)

Standard re-point. Apply only when `h_v2_dup_rows > 0`:

    UPDATE holdings_v2 SET entity_id = canonical_eid
    WHERE entity_id = duplicate_eid AND is_latest = TRUE;

### Scope of canonical state

Adjustment 2 is canonical for all future MERGE work where
duplicate has direct 13F filings. Phase 1 of every future
MERGE PR re-verifies `h_v2_dup_rows` per pair before
authoring the helper.

### References

- PR `cp-5-cycle-truncated-merges` (this PR; first Adjustment 2
  application — Pair 5 only, 169 rows)
- `docs/findings/cp-5-cycle-truncated-merges-results.md` §7.2

---

## MERGE op-shape extension — Adjustment 3 (Op A.4 `entity_identifiers` SCD transfer)

Authored: PR `cp-5-cycle-truncated-merges` (2026-05-05, 10-pair
cohort).

### Problem

cp-4a (PR #256) and Adjustment 1 (PR #283) Op A did not
transfer `entity_identifiers`: Adams duplicates' identifiers
were redundant with canonical's, and cp-4a brand_eids carried
brand-only identifiers absorbed by Op G alias re-point.

cp-5-cycle-truncated-merges cohort has 12 distinct identifier
transfers across 10 pairs:
  - 8 pairs each transfer 1 CRD;
  - Pair 5 transfers CIK `0001965246` + CRD `000165856`;
  - Pair 6 transfers CIK `0001536185` + CRD `000156933`.

Without Adjustment 3, those identifiers would be orphaned at
the deprecated duplicate.

### Adjustment 3 (codified)

SCD transfer pattern, per identifier_type where duplicate
carries an open identifier the canonical lacks:

  Pre-flight: PK collision check on
    `(identifier_type, identifier_value, valid_from=today)`.
  ABORT pair on collision (would indicate a third entity is
  using the same `(type, value)` at today's `valid_from` —
  unexpected).

  Step 1: close at duplicate.
    UPDATE entity_identifiers SET valid_to = today
    WHERE entity_id = duplicate_eid
      AND identifier_type = T
      AND identifier_value = V
      AND valid_from = D.valid_from_existing
      AND valid_to = DATE '9999-12-31';

  Step 2: insert at canonical with `valid_from=today`.
    INSERT INTO entity_identifiers
      (entity_id, identifier_type, identifier_value,
       confidence, source, is_inferred, valid_from, valid_to,
       created_at)
    VALUES (canonical_eid, T, V, D.confidence, D.source,
            FALSE, today, '9999-12-31', NOW());

PK is `(identifier_type, identifier_value, valid_from)` —
`entity_id` is NOT in PK. Closed duplicate row's PK at
`valid_from=2000-01-01` and new canonical row's PK at
`valid_from=today` do not collide.

`is_preferred` is NOT a column on `entity_identifiers` (verified
2026-05-05); no preferred-conflict logic needed.

### Scope of canonical state

Adjustment 3 is canonical for all future MERGE work. Phase 1
of every future MERGE PR re-verifies across all identifier
types (`cik`, `crd`, `lei`, `series_id`, `isin`, etc.)
before authoring the transfer plan.

### References

- PR `cp-5-cycle-truncated-merges` (this PR; first Adjustment 3
  application — 12 transfers across 10 pairs)
- `docs/findings/cp-5-cycle-truncated-merges-results.md` §7.3

---

## MERGE op-shape extension — Adjustment 4 (Op A two-step column-independent re-point)

Authored: PR `cp-5-cycle-truncated-merges` (2026-05-05). Triggered
by Phase 3 first-attempt Guard 7 failure on Goldman Pair 1; Code
surfaced to chat per STOP-gate discipline; chat authorized
Adjustment 4.

### Problem

cp-4a precedent (PR #256, Vanguard + PIMCO brand→filer bridge)
and Adjustment 1 (PR #283, Adams 7-pair) used a one-step
OR-clause Op A:

    UPDATE fund_holdings_v2
    SET rollup_entity_id = canonical_eid,
        dm_rollup_entity_id = canonical_eid,
        dm_rollup_name = canonical_canonical_name
    WHERE rollup_entity_id = duplicate_eid
       OR dm_rollup_entity_id = duplicate_eid
      AND is_latest = TRUE;

This shape silently steals THIRD-entity attribution when
duplicate has rows where `rollup_entity_id` ≠ duplicate but
`dm_rollup_entity_id` = duplicate (or vice versa). Each rollup
column represents an independent attribution per Bundle C §7.2
(decision_maker_v1 vs economic_control_v1 semantic split);
treating them as coupled was incorrect for true-duplicate-merge
contexts.

cp-5-cycle-truncated-merges Goldman Pair 1 (canonical 22 ←
duplicate 17941) surfaced the bug: Goldman duplicate carries
28,313 rows where `dm_rollup_entity_id = 17941` and
`rollup_entity_id` legitimately points to THIRD entities
including:
  - Equitable Investment Management LLC (eid 2562; itself a
    canonical in this PR's Pair 6) — $14.20B
  - Ameriprise Financial Inc (eid 10178) — $12.96B
  - Morgan Stanley (eid 2920) — $6.57B
  - AssetMark Inc (eid 6708) — $5.18B
  - Jackson National Asset Management LLC (eid 18983) — $6.84B
  - Empower Capital Management LLC (eid 18137) — $4.52B
  - Transamerica Asset Management Inc (eid 18298) — $1.95B
  - The Variable Annuity Life Insurance Company (eid 18202) —
    $5.14B
  - Portfolio Optimization Growth Portfolio (eid 14412) —
    $31.15B
  - … and ~9 others.

One-step Op A would have stolen $91.08B from these THIRD
entities on Pair 1 alone. Cohort total stolen-AUM exposure
across Pairs 1, 2, 4, 8: $142.21B.

### Why prior cohorts were data-safe

PR #256 cp-4a was an INTENTIONAL brand→filer bridge: brand-tier
eid was the target in BOTH columns by design, so absorbing it
on both columns was correct. Paper audit (Phase 1.5 of this PR)
confirmed no THIRD entities at risk.

PR #283 Adams Pairs 2-7 had $0 dup `fund_holdings_v2` footprint
— no rows existed to misattribute. Adams Pair 1 had 20 rows /
$0.0293B; empirical proxy on current state shows attribution
remains internally consistent with Adams Asset Advisors, so
maximum unverified residual risk is bounded at $0.0293B (no
direct snapshot recovery available).

The bug was latent in the precedent shape; cohort properties
specific to cp-4a (intentional bridge) and Adams ($0 footprint)
masked it.

### Adjustment 4 (codified)

Split Op A into two single-column UPDATEs in true-duplicate-
merge contexts:

  Op A.1 — `rollup_entity_id` re-point (column-independent).
    UPDATE fund_holdings_v2 SET rollup_entity_id = canonical_eid
    WHERE rollup_entity_id = duplicate_eid AND is_latest = TRUE;

  Op A.2 — `dm_rollup_entity_id` + `dm_rollup_name` re-point
  (column-independent).
    UPDATE fund_holdings_v2
    SET dm_rollup_entity_id = canonical_eid,
        dm_rollup_name = canonical_canonical_name
    WHERE dm_rollup_entity_id = duplicate_eid AND is_latest = TRUE;

Each UPDATE touches only its own column. THIRD-entity
attribution preserved. Per-column conservation is exact:
  post_can_rollup_aum = pre_can_rollup_aum + pre_dup_rollup_aum
  post_can_dm_rollup_aum = pre_can_dm_rollup_aum + pre_dup_dm_rollup_aum

The conservation is provable by disjoint set algebra when
zero "mixed" rows exist (rollup=can ∧ dm_rollup=dup or vice
versa). Phase 1 of every future MERGE PR audits for mixed rows
to confirm disjointness.

### Scope of canonical state

Adjustment 4 is canonical for all future MERGE work in
true-duplicate-merge contexts. Supersedes the one-step
OR-clause Op A from cp-4a precedent.

The cp-4a brand→filer bridge semantic (PR #256) remains
correct as designed for that PR. PR #256 + PR #283 paper-audit
verdict: zero THIRD-entity damage occurred (brand→filer
intentional + $0/near-$0 dup footprint respectively). No
corrective PR required for prior cohorts.

### Hard guards (per pair, expanded with Adjustment 4)

Total 11 guards × 10 pairs = 110 pre-COMMIT checks per cohort
PR. Splits (1) Guard 1 into 1a/1b/1c (column-independent), and
(7) Guard 7 into 7a/7b/7c (rollup, dm_rollup, h_v2 each).

  1a. Zero rows where rollup_entity_id = duplicate.
  1b. Zero rows where dm_rollup_entity_id = duplicate.
  1c. Zero rows where holdings_v2.entity_id = duplicate.
  2.  Exactly 1 open relationship ref dup (the Op E audit).
  3.  Zero open ECH on dup.
  4.  Zero open ERH FROM-side on dup.
  5.  Zero open ERH AT-side on dup.
  6.  Zero open aliases on dup.
  6b. Zero open entity_identifiers on dup.
  7a. Per-pair AUM conservation, rollup-side (within $0.01B).
  7b. Per-pair AUM conservation, dm_rollup-side (within $0.01B).
  7c. Per-pair AUM conservation, h_v2-side (within $0.01B).

### References

- PR #256 (cp-4a Vanguard + PIMCO brand→filer bridge — semantic
  exception, Adjustment 4 does NOT supersede)
- PR #283 (Adams 7-pair — paper audit confirmed no damage)
- PR `cp-5-cycle-truncated-merges` (this PR; Adjustment 4
  codified, first application across Pairs 1, 2, 4, 8 with
  THIRD-attribution preservation; Pairs 3, 5, 6, 7, 9, 10
  trivially identical to one-step shape since no THIRDs at risk)
- `docs/findings/cp-5-cycle-truncated-merges-results.md` §0,
  §6, §7.4

## Two-relationship-layer coexistence pattern for umbrella firms

**Capital Group precedent (PR `cp-5-capital-group-umbrella`,
2026-05-05):** umbrella firms can carry TWO independent
relationship layers in `entity_relationships`, both canonical:

- **`fund_sponsor` / `advisory` / `parent_bridge`** (or
  `parent_bridge_sync`, `family_name_alias_match`) — the
  **sponsor-brand layer**. Encodes fund-sponsor / brand-issuer
  relationships, typically populated by the N-CEN /
  parent_bridge_sync loader. Consumed by sponsor-view queries
  (e.g. "which funds does this brand issue?").

- **`wholly_owned` / `control`** with the cp-4b/cp-5 author
  source signature — the **corporate ownership layer**.
  Authored deliberately by inst-eid-bridge cohorts (CP-4a,
  CP-4b carve-out, CP-5 capital-group-umbrella). Consumed by
  the `decision_maker_v1` institutional rollup queries
  (CP-5 read layer / Method A view definition).

**Both layers may coexist on the same `(parent, child)` pair**
— they answer different questions, the same way the Bundle C
§7.2 semantic split applies to two-canonical-classifications
on the rollup-type axis.

**Concrete example.** Post-cp-5-capital-group-umbrella, the
pair `(parent=12, child=7125)` carries:

| relationship_id | relationship_type | control_type | source                                                                      |
|----------------:|-------------------|--------------|-----------------------------------------------------------------------------|
|             358 | `fund_sponsor`    | `advisory`   | `parent_bridge`                                                             |
|          20,842 | `wholly_owned`    | `control`    | `CP-5-pre:cp-5-capital-group-umbrella\|arm=Capital Research Global Investors\|Path A\|coexists_with_parent_bridge_layer\|public_record_verified=cp-5-bundle-b-discovery.md_§1.3` |

Both rows are valid, both serve distinct queries, neither is
redundant.

### Implications

- **Future MERGE work on umbrella firms must preserve both layers.**
  Do NOT collapse them or treat one as redundant. A MERGE Op G
  collision detector that finds a same-`(parent, child)` row in
  the survivor with a *different* `relationship_type` should
  treat both rows as keepers, not collide.

- **Bridge-author guards must check shape-specific existence,
  not pair-level existence.** The cp-5-capital-group-umbrella
  helper checks for existing `wholly_owned`/`control` rows
  specifically (Step 1 / `existing_control_bridge_count`), not
  for any open row on the pair — otherwise authoring would
  spuriously abort whenever a sponsor-layer row exists.

- **Path A "umbrella exists" check is shape-aware.** Pre-Phase 1
  evidence that an umbrella eid exists with sponsor-brand-layer
  edges to its arms does NOT count as "Path A partially
  complete" for CP-4b-shape control bridges; the ownership
  layer is independent and may need to be authored even when
  the sponsor layer is fully wired.

### References

- PR `cp-5-capital-group-umbrella` (this pattern's first
  formal application across 3 sibling arms with explicit chat
  acknowledgment).
- `docs/findings/cp-5-capital-group-umbrella-results.md` §1.3,
  §3.1, §6.
- Bundle B §1.3 — Capital Group umbrella case study (the
  sponsor-layer 87 rows on eid=12 were not visible in the
  Bundle B snapshot; pattern formalization comes from
  reconciling that gap).
- ROADMAP P3 follow-up: `parent-bridge-mechanism-audit` —
  read-only scoping of the sponsor-brand layer across all
  firms.

---

## `is_inferred` convention on `entity_relationships`

Added by `cp-5-pipeline-contract-cleanup` (2026-05-05). Closes
Gap 7 from `docs/findings/cp-5-bundle-c-discovery.md` §7.5.

### Rule

`is_inferred = TRUE` when the relationship was derived
programmatically (loader-inferred, classifier-inferred,
name-similarity-derived). `is_inferred = FALSE` when the
relationship was authored explicitly — by an operator-written
bridge PR, by an SCD MERGE op subsuming a prior shape, or by
a registrant's filing on the public record.

### Per-source mapping (open rows, snapshot 2026-05-05)

| `relationship_type` | `control_type` | `source` | `is_inferred` | rationale |
| --- | --- | --- | --- | --- |
| `wholly_owned` | `control` | `ADV_SCHEDULE_A`/`B`/`MANUAL` | FALSE | registrant declared in ADV filing |
| `wholly_owned` | `control` | `orphan_scan` | TRUE | programmatic detection by orphan-scan loader |
| `wholly_owned` | `control` | `name_inference` | FALSE | deliberate carve-out — see `scripts/oneoff/dm14b_apply.py` docstring (corporate fact verifiable externally despite using name match as the heuristic) |
| `wholly_owned` | `control` | `CP-4b-author-*` / `CP-5-pre:*` | FALSE | explicit bridge PR |
| `wholly_owned` | `control` | `ms_eaton_vance_acquisition` | FALSE | explicit author override |
| `mutual_structure` | `mutual` | `ADV_SCHEDULE_A`/`B` | FALSE | registrant declared in ADV filing |
| `parent_brand` | `control` | `ADV_SCHEDULE_A`/`B` | FALSE | registrant declared in ADV filing |
| `parent_brand` | `control` | `name_inference` | FALSE | deliberate carve-out (same dm14b_apply.py rule) |
| `parent_brand` | `merge` | `CP-4a-merge:*` / `CP-5-pre:*` | FALSE | explicit MERGE-op audit row |
| `fund_sponsor` | `advisory` | `ncen_adviser_map` | TRUE | programmatic seed from N-CEN cross-reference |
| `fund_sponsor` | `advisory` | `family_name_alias_match` / `fund_name_alias_match` / `fund_cik_sibling` | TRUE | programmatic name/identifier match |
| `fund_sponsor` | `advisory` | `parent_bridge` | TRUE | programmatic sync |
| `fund_sponsor` | `advisory` | `nport_orphan_fix` | FALSE | one-shot operator fix (not yet re-validated under the convention; see "ambiguous" below) |
| `sub_adviser` | `advisory` | `ncen_adviser_map` | TRUE | programmatic seed from N-CEN |

### Ambiguous / write-time-only

- `fund_sponsor` / `advisory` source mix overall is fully
  populated (no NULLs as of 2026-05-05); `nport_orphan_fix`
  is the only sub-source where the convention is not enforced
  empirically. Treat at write time: programmatic batch fixes
  → TRUE; per-row operator decisions → FALSE.

### Write-time guidance (going forward)

Future MERGE / BRIDGE / loader PRs MUST populate
`is_inferred` explicitly per the rule above. Do not leave it
NULL. The column is currently fully populated (0 NULLs across
all 18,394 rows on 2026-05-05); preserve that invariant.

### Backfill record

The `cp-5-pipeline-contract-cleanup` PR flipped 140 open
rows on `(relationship_type='wholly_owned',
control_type='control', source='orphan_scan')` from
`is_inferred=FALSE` to `TRUE`. Closed historical rows on
the same (source, type) tuple (34 rows) were left
untouched per SCD immutability.
