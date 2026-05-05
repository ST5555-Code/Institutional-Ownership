# cp-5-cycle-truncated-merges — 10-pair cycle-truncated cohort MERGE

**Status:** EXECUTED. All 10 pairs merged in a single transaction.
**Date:** 2026-05-05
**Refs:**
- `docs/findings/cp-5-comprehensive-remediation.md` §3.1
- `docs/findings/cp-5-bundle-b-discovery.md` §2.1
- `docs/findings/cp-5-cycle-truncated-merges-recon-results.md` (PR #284)
- `docs/findings/cp-5-adams-duplicates-results.md` (PR #283; Adjustment 1)
- `docs/findings/inst_eid_bridge_aliases_results.md` (PR #256; cp-4a brand→filer)
- `docs/decisions/inst_eid_bridge_decisions.md` (Adjustments 1/2/3/4 canonical)

Closes 2/5 P0 pre-execution cohorts in the CP-5 comprehensive remediation
plan. The 10-pair Category I cohort surfaced in Bundle B Phase 2.1 was
scoped in PR #284 and shipped here using the cp-4a-style MERGE op shape
plus four Adjustments. Adjustment 4 (column-independent two-step Op A) is
new in this PR and was triggered by a Phase 3 guard catch on Goldman
Pair 1; details in Section 7.4.

## Section 0 — Backfill audit on PR #256 (cp-4a) + PR #283 (Adams)

Adjustment 4 supersedes the cp-4a/Adams one-step OR-clause Op A in
true-duplicate-merge contexts. Phase 1.5 paper audit confirmed no
THIRD-entity damage occurred in either prior cohort:

**PR #256 (cp-4a Vanguard + PIMCO).** Brand→filer bridge semantic. The
one-step Op A is INTENTIONAL and CORRECT for that PR: every reference to
the brand-tier eid (in either rollup column) becomes a reference to the
filer-tier eid. Brand_eid 1 (Vanguard) and brand_eid 30 (PIMCO) were
brand-tier identifiers used by both rollup columns; merging them into
their filers absorbs them on both columns. No THIRD-entity damage
possible. Adjustment 4 does NOT supersede PR #256.

**PR #283 Pairs 2–7 (Adams funds 2961, 6471).** Per the Adams manifest
`fh_dup_rows = 0` for all six pairs, and a fresh post-merge query
confirms zero historical references to those duplicate eids in
`fund_holdings_v2`. Zero pre-merge footprint → zero damage possible.

**PR #283 Pair 1 (Adams Asset Advisors 4909 ← 19509).** 20 rows /
$0.0293B pre-merge dup footprint. Risk of THIRD-entity damage was
bounded at ≤ $0.0293B. Empirical proxy: post-merge, the 20 rows
attributed to canonical 4909 all share `fund_cik = 0001288872`,
`fund_name = 'Stock Dividend Fund, Inc.'`, `dm_rollup_name = 'Adams
Asset Advisors, LLC'`, with `rollup_entity_id = dm_rollup_entity_id =
4909`. Attribution is internally consistent with Adams Asset Advisors;
no anomalous fund families surfaced. Pre-merge snapshot was unavailable
for direct verification (earliest backup is post-merge), so the audit
is heuristic. Maximum unverified residual risk: $0.0293B.

**Verdict.** No corrective PR required for prior cohorts. Adjustment 4
codified going forward.

## Section 1 — Phase 1 cohort re-validation + Op A.3/A.4/B′ scope

All 10 pairs from PR #284's manifest re-validated against the production
DB on 2026-05-05. No drift; all 20 eids present, all `entity_type =
'institution'`. Manifest rows match the recon CSVs exactly.

**Op A.3 (holdings_v2 re-point) scope.** Only Pair 5 Financial Partners
duplicate 9722 carries 13F holdings under its `entity_id` (169 rows /
$0.5067B). Other 9 duplicates have zero h_v2 footprint — Op A.3 skip.

**Op A.4 (entity_identifiers transfer) scope.** 12 transfers planned
across 10 pairs:
- 8 pairs each transfer 1 CRD identifier from duplicate to canonical
  (canonical lacked the duplicate's CRD).
- Pair 5 transfers CIK `0001965246` and CRD `000165856` (canonical 1600
  lacked both).
- Pair 6 transfers CIK `0001536185` and CRD `000156933` (canonical 2562
  lacked both).
- All transfers are SCD: close at duplicate `valid_to=today`, insert at
  canonical `valid_from=today`. PK is `(identifier_type,
  identifier_value, valid_from)` — `valid_from` divergence prevents
  collision.

**Op B' (cycle edges) scope.** 2 cycle edges per pair, 20 total. All
`relationship_type='wholly_owned'`, `source='orphan_scan'`,
bidirectional (canonical↔duplicate).

**Pre-merge entity_relationships baseline.** 16,324 open rows;
`MAX(relationship_id) = 20830`. Op E allocated rids 20831..20840.

## Section 2 — Phase 2 dry-run manifest summary

Manifest written to
`data/working/cp-5-cycle-truncated-merges-manifest.csv` (10 pairs).

Dry-run cohort totals (matches Phase 1 audit):
- Σ `dup_rollup_aum` = $50.9452B (matches PR #284 recon's stated
  $50.95B — the rollup-column transfer)
- Σ `dup_dm_rollup_aum` = $193.1513B (the dm-column transfer; not
  separately reported in recon)
- Σ `dup_h_v2_aum` = $0.5067B (Pair 5 only)

## Section 3 — Phase 3 execute (single transaction across 10 pairs)

Single `BEGIN/COMMIT` block. All 110 hard guards (11 × 10 pairs)
passed. No rollback needed.

| Op | Effect | Rows (cohort) |
|---|---|---:|
| A.1 | `fund_holdings_v2.rollup_entity_id` re-point | 26,904 |
| A.2 | `fund_holdings_v2.dm_rollup_entity_id` + `dm_rollup_name` re-point | 63,154 |
| A.3 | `holdings_v2.entity_id` re-point (Adjustment 2; Pair 5 only) | 169 |
| A.4 | `entity_identifiers` SCD transfer (Adjustment 3) — closed | 12 |
| A.4 | `entity_identifiers` SCD transfer (Adjustment 3) — inserted | 12 |
| B (parent) | `entity_relationships` re-point parent edges | 391 |
| B (child) | `entity_relationships` re-point child edges | 0 |
| B' | close canonical↔duplicate cycle edges (D1: 2 each) | 20 |
| C | `entity_classification_history` close brand-side | 10 |
| E | INSERT audit rows (rids 20831..20840) | 10 |
| F | `entity_rollup_history` close FROM-side (2 rollup_types each) | 20 |
| G | `entity_aliases` re-point (Adjustment 1) | 10 |
| G demote | `entity_aliases` canonical preferred-of-same-type demoted | 10 |
| G close-on-collision | `entity_aliases` collision branch | 0 |
| H Branch 1 | `entity_rollup_history` AT-side re-point (close + insert) | 88 |
| H Branch 2 | canonical self-rollup recreate | 0 |
| **Total writes** | — | **~177K** |

Per-pair breakdown:

| Pair | Canonical ← Duplicate | a1 | a2 | a3 | a4 | b_par | b' | h1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 22 ← 17941 (Goldman) | 25,067 | 53,380 | 0 | (1,1) | 131 | 2 | 64 |
| 2 | 58 ← 18070 (Lazard) | 0 | 5,158 | 0 | (1,1) | 40 | 2 | 6 |
| 3 | 70 ← 18357 (Ariel) | 0 | 0 | 0 | (1,1) | 6 | 2 | 0 |
| 4 | 893 ← 17916 (Lord Abbett) | 0 | 1,832 | 0 | (1,1) | 52 | 2 | 1 |
| 5 | 1600 ← 9722 (Fin Partners) | 0 | 0 | 169 | (2,2) | 0 | 2 | 0 |
| 6 | 2562 ← 9668 (Equitable) | 0 | 0 | 0 | (2,2) | 110 | 2 | 0 |
| 7 | 2925 ← 18537 (Thornburg) | 0 | 0 | 0 | (1,1) | 26 | 2 | 0 |
| 8 | 7558 ← 18029 (Sarofim) | 795 | 1,742 | 0 | (1,1) | 16 | 2 | 9 |
| 9 | 7655 ← 18649 (Leavell) | 0 | 0 | 0 | (1,1) | 2 | 2 | 0 |
| 10 | 10501 ← 19846 (Stonebridge) | 1,042 | 1,042 | 0 | (1,1) | 8 | 2 | 8 |

## Section 4 — Phase 4 peer_rotation_flows rebuild

`scripts/pipeline/compute_peer_rotation.py` ran end-to-end:
- Wall-clock: 4:05 (245s)
- Pre-rebuild count: 17,489,564 rows
- Post-promote count: 17,489,564 rows
- Δ = **0** (rollup re-points fall within existing fund-tier coverage,
  consistent with PR #256 / PR #283 precedent)

Snapshot: `data/backups/peer_rotation_peer_rotation_empty_20260505_111826.duckdb`.

## Section 5 — Phase 5 validation

- `pytest tests/`: **416/416 passed** (1m17s).
- `cd web/react-app && npm run build`: ✓ built in 1.47s, 0 errors.

**Spot-checks (read-only post-execution):**

| Check | Result |
|---|---|
| Op E audit rows present (rids 20831..20840) | ✓ all 10, parent_brand/merge |
| All 10 duplicates: 0 open `fund_holdings_v2` refs | ✓ |
| All 10 duplicates: 0 open `holdings_v2` refs | ✓ (incl. Pair 5) |
| All 10 duplicates: exactly 1 open relationship (the Op E audit) | ✓ |
| All 10 duplicates: 0 open ECH / ERH FROM / ERH AT / aliases / identifiers | ✓ |
| Per-pair AUM conservation Δ (rollup, dm_rollup, h_v2) | $0.000000B all 30 |
| Goldman 22 preferred brand alias post-merge | "Goldman Sachs Asset Management, L.P." (re-pointed dup) |
| Goldman 22 demoted prior preferred | "Goldman Sachs Asset Management" → is_preferred=FALSE |
| Pair 5 1600 entity_identifiers count | 5 (3 original + 2 transferred at valid_from=today) |
| `entity_current` rollup_entity_id for canonicals | self (each canonical rolls to itself) |
| `entity_current` rollup_entity_id for duplicates | NULL (deprecated) |
| `peer_rotation_flows` row count delta | 0 |

**Goldman pair specific (largest cohort member):**

- Pre-merge canonical 22: rollup-side $782.69B / 124,984 rows;
  dm-side $430.21B / 112,744 rows.
- Post-merge canonical 22: rollup-side $829.19B / 150,051 rows
  (+$46.50B / +25,067 rows from dup); dm-side $567.79B / 166,124 rows
  (+$137.58B / +53,380 rows from dup).
- 64 ERH AT-side rows correctly re-pointed via Op H Branch 1
  (Goldman is 73% of cohort's 88-row AT total).
- Conservation Δ exact at $0.000000B both columns.

## Section 6 — AUM conservation gate per pair

All 10 pairs hit Δ=$0.000000B on each of the three conservation gates
(rollup, dm_rollup, h_v2) at the script's $0.01B tolerance. Per-column
exact conservation is provable by disjoint set algebra: Phase 1
confirmed zero "mixed" rows (rollup=can ∧ dm_rollup=dup or vice versa)
across the cohort, so Op A.1's pre-image (`rollup=dup`) and the canonical's
pre-existing `rollup=can` rows form disjoint sets, and likewise for
Op A.2.

| Pair | Δ rollup ($B) | Δ dm_rollup ($B) | Δ h_v2 ($B) |
|---|---:|---:|---:|
| 1 Goldman | 0.000000 | 0.000000 | 0.000000 |
| 2 Lazard | 0.000000 | 0.000000 | 0.000000 |
| 3 Ariel | 0.000000 | 0.000000 | 0.000000 |
| 4 Lord Abbett | 0.000000 | 0.000000 | 0.000000 |
| 5 Fin Partners | 0.000000 | 0.000000 | 0.000000 |
| 6 Equitable | 0.000000 | 0.000000 | 0.000000 |
| 7 Thornburg | 0.000000 | 0.000000 | 0.000000 |
| 8 Sarofim | 0.000000 | 0.000000 | 0.000000 |
| 9 Leavell | 0.000000 | 0.000000 | 0.000000 |
| 10 Stonebridge | 0.000000 | 0.000000 | 0.000000 |

## Section 7 — Adjustments 1, 2, 3, 4 (op-shape canon)

### 7.1 — Adjustment 1 (cp-4a / Adams precedent): close-on-collision in Op G

Originated in PR #256 cp-4a (PIMCO `PIMCO`/`PACIFIC INVESTMENT
MANAGEMENT CO LLC` demote case) and codified in PR #283 Adams cohort.
For each duplicate-side alias D, if canonical has an open alias matching
`(alias_name, alias_type, valid_from)`: CLOSE-ON-COLLISION at duplicate.
Else: RE-POINT, with preferred-conflict demotion of canonical's prior
preferred-of-same-type.

This PR's cohort: 0 close-on-collision branches (no PK collisions); 10
re-points; 10 demotes (all 10 duplicates carried preferred=TRUE brand
aliases, all canonicals had a competing preferred brand alias of
case/punctuation variant).

### 7.2 — Adjustment 2 (this PR): Op A.3 holdings_v2.entity_id re-point

cp-4a (PR #256) and Adams (PR #283) cohorts had no holdings on
duplicates under the `entity_id` column (they only carried brand-side
rollup attribution, not direct 13F filings). cp-5-cycle-truncated-merges
Pair 5 (Financial Partners 1600 ← 9722) has 169 rows / $0.5067B of
direct 13F holdings under duplicate's `entity_id`. Adjustment 2: standard
re-point.

```sql
UPDATE holdings_v2 SET entity_id = canonical
WHERE entity_id = duplicate AND is_latest = TRUE;
```

Adjustment 2 is canonical for all future MERGE work where duplicate has
direct 13F filings.

### 7.3 — Adjustment 3 (this PR): Op A.4 entity_identifiers SCD transfer

cp-4a + Adams cohorts had no distinct identifiers on duplicates that
needed transfer (or duplicates' identifiers were redundant with
canonical's). This cohort has 12 transfers across 10 pairs:

- Pairs 1, 2, 3, 4, 7, 8, 9, 10 each transfer 1 CRD.
- Pairs 5, 6 each transfer 1 CIK + 1 CRD.

Adjustment 3 SCD pattern:
1. Pre-flight collision check on PK `(identifier_type, identifier_value,
   valid_from=today)`. ABORT if collision.
2. UPDATE close at duplicate: `valid_to = today` WHERE `entity_id =
   duplicate AND identifier_type = T AND identifier_value = V AND
   valid_from = vf_existing AND valid_to = open`.
3. INSERT at canonical: same `(type, value)` with `valid_from = today,
   valid_to = open`, preserving `confidence` and `source`.

PK constraint is on `(identifier_type, identifier_value, valid_from)` —
`entity_id` is NOT in the PK. The closed duplicate row's PK at
`valid_from=2000-01-01` and the new canonical row's PK at
`valid_from=2026-05-05` do not collide.

Adjustment 3 is canonical for all future MERGE work. Phase 1 of every
future MERGE PR re-verifies across all identifier types before authoring
the transfer plan (CIK, CRD, LEI, series_id; this PR audited all four —
only `cik` and `crd` had transfers in the cohort).

### 7.4 — Adjustment 4 (this PR): Op A two-step column-independent re-point

**Trigger.** Phase 3 first-attempt --confirm caught Guard 7 (rollup-side
AUM conservation) failure on Pair 1 Goldman: post-merge canonical 22
rollup AUM = $920.27B, expected = $782.69 + $46.50 = $829.19B, delta =
$91.08B. The transaction rolled back cleanly (BEGIN/COMMIT discipline);
no DB damage.

**Root cause.** The cp-4a one-step OR-clause Op A inherited from PR #256
sets BOTH `rollup_entity_id` AND `dm_rollup_entity_id` to canonical for
EVERY row matching `rollup=dup OR dm_rollup=dup`. For rows where
`rollup_entity_id = THIRD ≠ dup` AND `dm_rollup_entity_id = dup`, this
silently re-points `rollup_entity_id` from THIRD to canonical, stealing
attribution from the THIRD entity.

**Cohort impact pre-fix (audit only — fix prevented actual damage).**
Goldman pair alone had 28,313 such "split" rows totalling $91.08B that
would have been stolen from THIRD entities including Equitable
Investment Management ($14.20B — itself a canonical in our Pair 6),
Ameriprise Financial ($12.96B), Morgan Stanley ($6.57B), AssetMark
($5.18B), Jackson National, Empower, Transamerica, and others. Cohort
total stolen-AUM exposure across 4 pairs (1, 2, 4, 8) was $142.21B.

**Why prior cohorts were data-safe.** PR #256 cp-4a was a brand→filer
bridge with no THIRD entities at risk (brand-tier eid was used as the
target in BOTH columns by design — see Section 0 paper audit). PR #283
Adams cohort had $0 / near-$0 dup footprint, so no THIRDs were
attribute-locked to duplicates. The bug was latent in the precedent
shape.

**Fix.** Split Op A into two single-column UPDATEs:

```sql
-- Op A.1
UPDATE fund_holdings_v2 SET rollup_entity_id = canonical
WHERE rollup_entity_id = duplicate AND is_latest = TRUE;

-- Op A.2
UPDATE fund_holdings_v2 SET dm_rollup_entity_id = canonical, dm_rollup_name = X
WHERE dm_rollup_entity_id = duplicate AND is_latest = TRUE;
```

Each UPDATE touches only its own column. THIRD-entity attribution
preserved. Per-column conservation exact (provable via disjoint set
algebra; Phase 1 zero-mixed-rows audit ensures the disjointness
precondition for this cohort).

**STOP-gate discipline credit.** The original prompt's pre-execution
checklist included:

> "STOP gate: if any pair shows unexpected complexity not surfaced in
> recon (extra edges, holdings on additional duplicates, identifier
> collisions canonical ↔ duplicate), ABORT and surface to chat."

Code surfaced this issue from a Guard 7 failure during Phase 3 first
attempt and blocked further DB writes pending chat authorization. This
prevented $142.21B of THIRD-entity attribution corruption. Chat
authorized Adjustment 4, the fix shipped in this PR, and the canonical
op-shape going forward is recorded in `inst_eid_bridge_decisions.md`.

Adjustment 4 is canonical for all future MERGE work in
true-duplicate-merge contexts. The cp-4a brand→filer bridge semantic
(PR #256) remains correct as designed for that PR.

## Section 8 — P0 pre-execution status

| # | Cohort | PR | Status |
|---|---|---|---|
| 1 | Adams duplicates (7-pair) | #283 | Shipped |
| 2 | Cycle-truncated (10-pair) | this PR | Shipped |
| 3 | Capital Group umbrella (Path A vs B) | TBD | Investigation pending |
| 4 | Pipeline contract gaps | TBD | Bundle C §7.5 read pending |
| 5 | Loader gap remediation (3 sub-PRs) | TBD | Pending |

**2/5 P0 pre-execution cohorts complete.** Next: cp-5-capital-group-
umbrella decision investigation.

## Section 9 — Out-of-scope discoveries

- **Cycle-adjacent entity audit.** Sarofim Trust Co (eid 858) was
  identified during recon as cycle-adjacent but non-member; excluded
  from this cohort per chat decision D4. Tracked as new P3 entry
  `cycle-adjacent-entity-audit` in conv-30 doc-sync.

- **THIRD-entity attribution graph.** The `dup_or > dup_rollup` gap
  exposed by Adjustment 4 reveals that some institutions (notably
  Goldman) are heavy `dm_rollup` targets across many funds whose
  `rollup_entity_id` legitimately points to other firms (insurance
  companies, asset managers, retail platforms). This is a healthy
  data shape (decision-maker rollup ≠ economic-control rollup per
  Bundle C §7.2), but it's worth documenting as a property the
  pipeline should preserve. Future MERGE work must respect column
  independence (Adjustment 4 codifies).

- **`entities.canonical_name` not updated on canonicals.** Per cp-4a /
  Adams precedent, `entities.canonical_name` is not modified by MERGE
  ops. Display name post-merge derives from preferred alias state
  (e.g. Goldman 22's `entity_current.display_name` is now "Goldman
  Sachs Asset Management, L.P." via the re-pointed alias, while
  `entities.canonical_name` still reads "Goldman Sachs Asset
  Management"). Consistent with precedent; not in scope here.
