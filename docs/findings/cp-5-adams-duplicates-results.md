# cp-5-adams-duplicates — Phase 1-7 results

Generated 2026-05-05 by `scripts/oneoff/cp_5_adams_duplicates.py --confirm`,
followed by `compute_peer_rotation.py`, `pytest tests/`,
`cd web/react-app && npm run build`, and
`scripts/oneoff/inst_eid_bridge_phase1b_eid_level.py`.

First P0 pre-execution PR per
`docs/findings/cp-5-comprehensive-remediation.md` §3.4. Branch
`cp-5-adams-duplicates`, off `main` at `ea08681` (PR #282).

## 1. Op-shape extension — Adjustment 1 (close-on-collision in Op G)

cp-4a precedent (PR #256, Vanguard/PIMCO) established the 8-op MERGE shape
(A, B, B', C, E, F, G, H). Vanguard/PIMCO each had at most one duplicate per
canonical and alias_names were distinct, so `entity_aliases` re-point did not
hit PK collisions.

Adams duplicates (this PR, 7 pairs across 3 canonicals) hit two collision
shapes the cp-4a script didn't anticipate:

1. **Direct collision** — duplicate's alias is identical to canonical's
   existing alias (Pair 1: 4909 ← 19509, both hold
   `('Adams Asset Advisors, LLC', 'brand', 2000-01-01)` preferred=TRUE).
2. **Chained collision** — pair N's duplicate alias is identical to pair M's
   just-re-pointed alias (M < N, same canonical). Pairs 3/4 (canonical 2961)
   and pairs 6/7 (canonical 6471) hit this.

Per chat authorization 2026-05-05 (option A), Op G extended with a per-alias
collision check before re-point:

- If `(canonical, alias_name, alias_type, valid_from)` exists open: close the
  duplicate's alias (Branch CLOSE-ON-COLLISION). No demotion changes.
- Else: re-point with cp-4a-style preferred-conflict resolution scoped to
  `alias_name != D.alias_name` (Branch RE-POINT).

Adjustment 1 documented as canonical for all future MERGE work in
[docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md)
"MERGE op-shape extension — Adjustment 1" section.

Pair processing order is `(canonical_eid, pair_id)` ascending so pair M
re-points before pair N collides. Effective execution order in this run:
2, 3, 4, 1, 5, 6, 7.

## 2. Phase 1 cohort re-validation

`data/working/cp-5-bundle-b-adams-cohort.csv` (PR #278): 14 entities. All 14
still present in DB. Two Adams-named entities added since PR #278 (eid 2614
Joel Adams & Associates, eid 5114 Moss Adams Wealth Advisors) — distinct
firms, excluded from cohort.

All 6 prior CP-4 bridges intact: 20813 (Vanguard), 20814 (PIMCO), 20820
(TRowe), 20821 (First Trust), 20822 (FMR), 20823 (SSGA).

Pre-merge `MAX(relationship_id) = 20823`. Op E allocated 20824–20830.

### Pair identification (X1-normalized canonical_name grouping)

7 duplicate pairs, 3 canonicals:

| pair | canonical | duplicate | rationale |
|---|---|---|---|
| 2 | 2961 (inst, CIK 2230, $11.28B 13F) | 20213 (fund, series_id) | canonical has 376 holdings_v2 rows; duplicate has 0 |
| 3 | 2961 | 20214 (fund) | (same canonical) |
| 4 | 2961 | 20215 (fund) | (same canonical) |
| 1 | 4909 (inst, CIK 1386929, $2.98B 13F) | 19509 (inst, no CIK) | canonical has 321 h_v2 rows; duplicate has 20 fh_v2 rollup rows / $0.0293B |
| 5 | 6471 (inst, CIK 216851, $2.63B 13F) | 20210 (fund, series_id) | canonical has 216 h_v2 rows; duplicate has 0 |
| 6 | 6471 | 20211 (fund) | (same canonical) |
| 7 | 6471 | 20212 (fund) | (same canonical) |

Singletons excluded (no duplicates): 824 (Adams Street Partners), 27097
(Adams Street Private Equity Navigator Fund), 1571 (AdamsBrown Wealth
Consultants), 11012 (Adams Wealth Management).

### Phase 1 anomaly surfaced

Canonical 4909 (Adams Asset Advisors) currently rolls UP to duplicate 19509
in `entity_current.rollup_entity_id`. Op H Branch 2 inverts this — closes
the inverted rollups and inserts canonical self-rollups. Confirmed in Phase
5 spot-check: post-merge `entity_current.rollup_entity_id = 4909` (self).

## 3. Phase 2 dry-run manifest

`data/working/cp-5-adams-duplicates-manifest.csv` — 7 rows, ordered by
`(canonical_eid, pair_id)` ascending. AUM conservation expectation: $0.00B
delta for every pair (6 of 7 duplicates have $0 footprint; pair 1 has $29M
moved within fh_v2 rollup, conserved at canonical).

## 4. Phase 3 — execute MERGE (single transaction across all 7 pairs)

Single BEGIN/COMMIT block. All 7 hard guards passed for every pair. AUM
conservation tolerance ($0.01B per pair): hit **$0.000000B** for every pair.

### Per-pair op breakdown

| pair | A | B | B' | C | E rel_id | F | G repoint | G close | G demote | H b1 | H b2 | AUM Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 (2961←20213) | 0 | 0 | 1 | 0 | 20824 | 2 | **1** | 0 | 1 | 0 | 0 | $0.000000B |
| 3 (2961←20214) | 0 | 0 | 1 | 0 | 20825 | 2 | 0 | **1** | 0 | 0 | 0 | $0.000000B |
| 4 (2961←20215) | 0 | 0 | 1 | 0 | 20826 | 2 | 0 | **1** | 0 | 0 | 0 | $0.000000B |
| 1 (4909←19509) | 20 | 1 | 1 | 1 | 20827 | 2 | 0 | **1** | 0 | 2 | 2 | $0.000000B |
| 5 (6471←20210) | 0 | 0 | 1 | 0 | 20828 | 2 | **1** | 0 | 1 | 0 | 0 | $0.000000B |
| 6 (6471←20211) | 0 | 0 | 1 | 0 | 20829 | 2 | 0 | **1** | 0 | 0 | 0 | $0.000000B |
| 7 (6471←20212) | 0 | 0 | 1 | 0 | 20830 | 2 | 0 | **1** | 0 | 0 | 0 | $0.000000B |
| **Total** | **20** | **1** | **7** | **1** | — | **14** | **2** | **5** | **2** | **2** | **2** | **$0.000000B** |

Adjustment 1 verification: pair 2 / pair 5 each took the RE-POINT branch (no
collision at canonical at processing time — canonical's alias was UPPERCASE
only); pair 1 + pairs 3/4/6/7 each took CLOSE-ON-COLLISION (canonical
already held the identical alias_name, alias_type, valid_from row, either
from its own pre-existing alias or from pair 2/5's re-point earlier in the
transaction).

### Op B' subsumed-row inventory

| pair | rel_id | parent → child | type | source |
|---|---:|---|---|---|
| 2 | 16140 | 2961 → 20213 | fund_sponsor | fund_cik_sibling |
| 3 | 16141 | 2961 → 20214 | fund_sponsor | fund_cik_sibling |
| 4 | 16142 | 2961 → 20215 | fund_sponsor | fund_cik_sibling |
| 1 | 15149 | 19509 → 4909 | wholly_owned | orphan_scan |
| 5 | 16137 | 6471 → 20210 | fund_sponsor | fund_cik_sibling |
| 6 | 16138 | 6471 → 20211 | fund_sponsor | fund_cik_sibling |
| 7 | 16139 | 6471 → 20212 | fund_sponsor | fund_cik_sibling |

Op E source field encodes subsumed-row reference per the cp-4a precedent:

```
CP-5-pre:cp-5-adams-duplicates|pair=<N>|merged_duplicate_to_canonical|subsumes:<type>/<parent>-><child>/<orig_src>
```

### Op H detail (pair 1 only)

For pair 1 (4909 ← 19509), Op H closed 4 ERH rows where rollup_entity_id =
19509 (after Op F closed the 2 self-rollups). Branch 1 re-pointed 2 fund-
tier rows (entity_id=16030 × {decision_maker_v1, economic_control_v1}) to
canonical 4909. Branch 2 closed the 2 canonical-rollup-to-duplicate rows
(entity_id=4909 × {decision_maker_v1, economic_control_v1}) and inserted 2
fresh self-rollups (entity_id=4909, rollup_entity_id=4909, rule_applied=
'self', source='CP-5-pre:cp-5-adams-duplicates|pair=1').

For pairs 2-7, Op H found 0 AT-side rows referencing duplicate (canonicals
2961, 6471 already self-rolled, no fund-tier eids rolled up to fund-typed
duplicates).

## 5. Phase 4 — peer_rotation_flows rebuild

`scripts/pipeline/compute_peer_rotation.py` (no `--staging` — full prod path).

- run() complete: **48.2s**
- snapshot: `data/backups/peer_rotation_peer_rotation_empty_20260505_092052.duckdb`
- promote: **207.6s** (`rows_upserted=17,489,564`)
- pre-rebuild row count: 17,489,564
- post-rebuild row count: 17,489,564
- Δ = 0 rows (well within ±0.5% tolerance)

Total wall-clock: ~4:18. Δ=0 matches PR #256 precedent — rollup re-points
within existing fund-tier coverage produce no new (quarter, sector, entity)
tuples. Pair 1's 20-row Op A re-point shifts $29M from rollup_entity_id=
19509 to rollup_entity_id=4909; the (quarter, sector, 4909) tuples already
existed (4909 has 321 holdings_v2 rows on its own institutional 13F filing),
so the merge consolidates rather than expanding the rollup keyspace.

## 6. Phase 5 — validation

### pytest

`pytest tests/` → **416 passed, 1 warning in 55.44s**. No regression vs
main baseline (416/416).

### React build

`cd web/react-app && npm run build` → **0 errors, 1.66s, 20 chunks**.
Worktree-local symlink to parent `node_modules` to avoid a fresh
`npm install` in the worktree.

### Post-merge spot-checks

| check | result |
|---|---|
| `fund_holdings_v2` rows referencing any duplicate (rollup_entity_id or dm_rollup_entity_id) | **0** ✓ |
| `entity_relationships` open referencing duplicates (expected 7: Op E audit rows) | **7** ✓ |
| `entity_classification_history` open on each duplicate | **0** for all 7 ✓ |
| `entity_rollup_history` open on each duplicate (FROM-side) | **0** for all 7 ✓ |
| `entity_rollup_history` open with `rollup_entity_id = duplicate` (AT-side) | **0** for all 7 ✓ |
| `entity_aliases` open on each duplicate | **0** for all 7 ✓ |
| `entity_current.rollup_entity_id` for canonicals 2961, 4909, 6471 | self for all three ✓ (4909 was 19509 pre-merge) |
| `entity_current.display_name` for canonical 2961 | `'Adams Diversified Equity Fund, Inc.'` (mixed-case, from pair-2 promotion) ✓ |
| `entity_current.display_name` for canonical 4909 | `'Adams Asset Advisors, LLC'` (unchanged) ✓ |
| `entity_current.display_name` for canonical 6471 | `'Adams Natural Resources Fund, Inc.'` (mixed-case, from pair-5 promotion) ✓ |
| `entity_current` for all 7 duplicates | `rollup_entity_id=NULL`, `classification=NULL` ✓ |
| canonical 2961 brand aliases | mixed-case preferred=TRUE; UPPERCASE preferred=FALSE (demoted by pair 2 RE-POINT) ✓ |
| canonical 6471 brand aliases | mixed-case preferred=TRUE; UPPERCASE preferred=FALSE (demoted by pair 5 RE-POINT) ✓ |
| canonical 4909 brand aliases | unchanged single row preferred=TRUE (pair 1 was CLOSE-ON-COLLISION) ✓ |
| Pair 1 fund 16030 ERH rollup_entity_id | post-merge: 4909 (was 19509) ✓ |
| `entity_relationships` open count | 16,324 (unchanged — 7 closed via Op B' + 7 inserted via Op E nets to 0) ✓ |
| `MAX(relationship_id)` | 20830 (was 20823 pre-merge) ✓ |

### inst_eid_bridge phase1b helper re-run

`scripts/oneoff/inst_eid_bridge_phase1b_eid_level.py` against post-merge
state:

| metric | post-CP-4a (PR #256 baseline) | post-cp-5-adams | Δ |
|---|---:|---:|---:|
| `brand_eid_count` | 1,705 | 1,705 | 0 |
| `invisible_brand_count` | 1,223 | 1,223 | 0 |
| `invisible_brand_rows` | 6,661,809 | 6,661,809 | 0 |
| `invisible_brand_aum_usd` | $25,256,173,335,561 | $25,256,173,335,561 | 0 |
| `invisible_with_open_relationship` | 496 | 496 | 0 |
| `name_match_summary.brands_named` | 1,223 | 1,223 | 0 |

The phase1b helper measures the inst_eid_bridge cohort (synthesized brand-
typed eids that came in without CIK during pipeline ingestion). The Adams
duplicates fall outside that cohort:

- Duplicate 19509 (Adams Asset Advisors) holds a CRD identifier
  (`000120573`) which excludes it from the no-CIK brand-eid filter despite
  having no CIK.
- Duplicates 20210–20215 are entity_type='fund' (not 'institution'/brand)
  with synthesized series_ids; the phase1b helper key-filters on the brand
  shape.

The Δ=0 here is **expected** — Adams cleanup is orthogonal to the inst-
eid-bridge invisible-brand inventory. The proper "this merge worked"
evidence sits in the spot-checks table above (zero leftover refs across
all 6 SCD layers, 7 audit rows present, canonical self-rollups restored,
display names promoted).

## 7. AUM conservation gate

Every pair: **$0.000000B** delta against the per-pair $0.01B tolerance.

Pair 1 detail: pre-merge canonical 4909 fh_v2 rollup AUM = $0.0000B (4909
had no fh_v2 rollup footprint). Pre-merge duplicate 19509 fh_v2 rollup AUM
= $0.0293B (20 rows). Op A re-points 20 rows → post-merge canonical 4909
fh_v2 rollup AUM = $0.0293B. Conservation: $0.0293B = $0.0000B + $0.0293B,
delta = $0.0000B. ✓

Pairs 2–7 detail: duplicates have $0 fh_v2 rollup AUM by construction (no
footprint), so re-point or close-on-collision is value-neutral. Conservation
trivially holds.

## 8. P0 pre-execution status

| cohort | status | pairs | findings doc |
|---|---|---:|---|
| **cp-5-adams-duplicates** | **DONE** | **7** | this doc |
| cp-5-cycle-truncated-merges | next (3-PR split) | 21 | TBD |
| Capital Group umbrella | TBD | TBD | TBD |
| pipeline contract gaps | TBD | — | TBD |
| loader-gap remediation | TBD | — | TBD |

This PR validates the cp-4a MERGE op shape under chained-merge alias-
collision conditions. The Adjustment 1 extension is now canonical (per
`inst_eid_bridge_decisions.md`) and ready for inheritance into
cp-5-cycle-truncated-merges (21 pairs) and any future MERGE PR.

## 9. Out-of-scope discoveries

### A. Adams Asset Advisors rollup direction was inverted pre-merge

`entity_current.rollup_entity_id = 19509` for canonical 4909 prior to this
merge — i.e. the CIK-bearing 13F filer was rolling UP to its no-CIK
duplicate. Op H Branch 2 surfaced and corrected this (close + recreate as
self-rollup on canonical). Worth flagging for the discovery audit: how
many other inst-pair eids have the same inverted direction? Generically a
P3 audit task: scan `entity_current` for canonical eids whose
`rollup_entity_id` points at a no-CIK / synthesized eid.

### B. Brand-name casing display promotion via cp-4a preferred-conflict

Canonicals 2961 and 6471 now display in mixed-case (`'Adams Diversified
Equity Fund, Inc.'`, `'Adams Natural Resources Fund, Inc.'`) because pair 2
/ pair 5 took the RE-POINT branch and the cp-4a-style preferred-conflict
demotion fired. This matches the spirit of the cp-4a PIMCO precedent
(`PIMCO` trade name promoted over `PACIFIC INVESTMENT MANAGEMENT CO LLC`).
Display change is intended.

### C. phase1b helper scope mismatch (information only)

The phase1b helper's brand-eid filter excludes duplicate 19509 (CRD-bearing
no-CIK institution) and duplicates 20210–20215 (fund-typed). Future
cp-5-cycle-truncated-merges may also fall outside phase1b scope; results
docs should note when phase1b deltas don't reflect the merge.

## 10. Files

- `scripts/oneoff/cp_5_adams_duplicates.py` — 8-op MERGE script with
  Adjustment 1 close-on-collision in Op G; `--dry-run` and `--confirm` modes.
- `scripts/oneoff/cp_5_adams_phase1_recon.py` — Phase 1 read-only
  reconnaissance (cohort drift check, X1-normalized pairing, baselines,
  prior CP-4 bridge sanity).
- `scripts/oneoff/cp_5_adams_phase1b_relationships.py` — per-pair Op
  B/B'/F/G/H probe used during dry-run.
- `data/working/cp-5-adams-duplicates-manifest.csv` — 7-pair manifest with
  per-pair op counts and AUM conservation expectations.
- `docs/findings/cp-5-adams-duplicates-results.md` — this file.
- `docs/decisions/inst_eid_bridge_decisions.md` — Adjustment 1 op-shape
  canonical addendum appended.
- `data/backups/13f_backup_20260505_051519` — 3.2GB pre-confirm backup.

## 11. Architecture / safety

- Single BEGIN/COMMIT transaction across all 7 pairs; ROLLBACK on any
  constraint violation.
- 7 hard guards per pair (zero leftover fh_v2 refs, ≤1 open relationship
  ref, zero open ECH/ERH-FROM/ERH-AT/aliases, AUM conservation $0.01B
  tolerance). All passed first try.
- DuckDB cursor `fetchone()` for affected-row counts (no SQLite-style
  `changes()` — already a captured lesson per memory).
- `NOW()` not `CURRENT_TIMESTAMP` for `last_refreshed_at` writes (per
  memory binder-quirk lesson).
- No `--reset` anywhere; no write-path module modified
  (`load_nport.py`, `load_13f_v2.py`, `classify_fund()`, etc.).
- Fresh pre-confirm backup at `data/backups/13f_backup_20260505_051519`
  (3.2GB) per memory rule for write-path PRs.
