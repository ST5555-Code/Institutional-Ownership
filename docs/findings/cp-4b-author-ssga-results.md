# cp-4b-author-ssga — results

**Date:** 2026-05-03
**Branch:** `cp-4b-author-ssga`
**Refs:** [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2 addendum landed in PR #269),
[docs/findings/cp-4b-blocker2-corroboration-probe.md](cp-4b-blocker2-corroboration-probe.md), PR #267 (cp-4b-author-trowe), PR #269 (cp-4b-author-first-trust), PR #270 (cp-4b-author-fmr).

Single-brand BRIDGE: brand eid 3 (State Street / SSGA) → filer eid 7984
(STATE STREET CORP) via `wholly_owned` / `control`. Final named brand
from the cp-4b-blocker2-corroboration-probe Outcome 4 narrow carve-out,
and the second **Bucket C** (X2-only, raw-string identical alias)
bridge authored under the carve-out predicate. **Closes the cp-4b
carve-out arc.**

---

## 1. Pre-execution Phase 1 confirmations

Read-only against prod `data/13f.duckdb`.

| check | result |
| --- | --- |
| eid 3 canonical_name | `State Street / SSGA` (entity_type=`institution`) |
| eid 7984 canonical_name | `STATE STREET CORP` (entity_type=`institution`) |
| eid 7984 holdings_v2 visibility | 17,111 rows / $10,959.488B (probe matrix expected ~17,111 ✓) |
| open relationship `(parent=7984, child=3)` | 0 rows (idempotency ✓) |
| other open rels involving brand eid 3 | 68 rows, all outbound `fund_sponsor` to fund eids (60 `source='family_name_alias_match'`, 8 `'fund_name_alias_match'`). No inbound `wholly_owned`. Untouched. |
| fund AUM exposure (rollup or dm_rollup = 3) | 60,157 rows / **$301.8957B** (probe expected ~$301.9B ✓) |
| `entity_relationships` baseline | 18,373 total / 16,323 open / `MAX(relationship_id)=20,822` |
| PR #267 trowe row 20820 | present ✓ (parent=3616, child=17924, type=wholly_owned) |
| PR #269 first-trust row 20821 | present ✓ (parent=136, child=8, type=wholly_owned) |
| PR #270 fmr row 20822 | present ✓ (parent=10443, child=11, type=wholly_owned) |

The 68 outbound `fund_sponsor` rows on brand eid 3 stay untouched.
BRIDGE is additive — the new `wholly_owned/control` parent edge from
eid 7984 sits alongside the existing fund-attribution edges without
collision. State Street being a major operating filer means the brand
has a richer existing relationship graph than other carve-out brands;
the count is informational only.

## 2. INSERT execution

Pure new-row INSERT into `entity_relationships` in a single
`BEGIN/COMMIT` transaction via `scripts/oneoff/cp_4b_author_ssga.py --confirm`.

Helper mirrors `cp_4b_author_fmr.py` (PR #270) verbatim with
pair-specific substitutions (filer/brand eids, brand label, source
prefix `CP-4b-author-ssga`).

| field | value |
| --- | --- |
| `relationship_id` | **20,823** (baseline `MAX + 1`) |
| `parent_entity_id` | 7984 (filer) |
| `child_entity_id` | 3 (brand) |
| `relationship_type` | `wholly_owned` |
| `control_type` | `control` |
| `is_primary` | TRUE |
| `primary_parent_key` | 7984 |
| `confidence` | `medium` (matches fmr/first-trust; corroboration-carve-out tier) |
| `is_inferred` | FALSE |
| `valid_from` | `2026-05-03` |
| `valid_to` | `9999-12-31` |
| `source` | `CP-4b-author-ssga\|pair=1\|pairing_source=cp-4b-corroboration-probe-bucket-C\|confidence=MEDIUM\|signals=X2\|public_record_verified=cp-4b-blocker2-corroboration-probe.md_§7` |

Source string differs from PR #270 (fmr) only in the leading
`CP-4b-author-ssga` token. Bucket and signals identical: `bucket-C`
+ `signals=X2`. Bucket C carve-out predicate (probe §6): *"X2 alone
fires with brand-side and filer-side aliases sharing identical
raw-string content (not just normalized equality)."* This pair
qualifies under that predicate per the probe matrix.

Hard guards (all passed before COMMIT):

- pre-execution: zero open relationships for `(7984, 3)` pair ✓
- pre-execution: prepared `relationship_id=20,823` does not exist ✓
- post-execution: exactly 1 open `(7984, 3, wholly_owned, control)` row ✓
- post-execution: open-row count delta = +1 (16,323 → 16,324) ✓
- post-execution: `MAX(relationship_id)` delta = +1 (20,822 → 20,823) ✓
- post-execution: total row count delta = +1 (18,373 → 18,374) ✓

## 3. Post-execution validation

| check | result |
| --- | --- |
| spot-check row 20,823 | full 14-column schema written; `created_at`/`last_refreshed_at` populated (2026-05-03 21:49:41 UTC); `is_primary=TRUE`, `primary_parent_key=7984` |
| filer eid 7984 holdings_v2 | unchanged: 17,111 rows / $10,959.488B (matches Phase 1b) ✓ |
| brand eid 3 fund_holdings_v2 | unchanged: 60,157 rows / $301.8957B (matches Phase 1e) ✓ |
| prior CP-4b bridges (20820 trowe, 20821 first-trust, 20822 fmr) | all intact, unchanged ✓ |
| pytest tests/ | **416 passed** (baseline) |
| `tsc -b && vite build` (web/react-app) | clean (vite ✓ built in 1.50s) |

## 4. peer_rotation_flows status

No recompute triggered. Per BRIDGE-shape precedent (PR #258
cp-4b-blackrock, PR #267 cp-4b-author-trowe, PR #269
cp-4b-author-first-trust, PR #270 cp-4b-author-fmr):
`entity_relationships` row insertion does not move
`fund_holdings_v2` rollup attribution, so `peer_rotation_flows`
delta is expected = 0. Consumers traverse the new bridge at read
time via CP-5 (parent-level-display-canonical-reads).

## 5. cp-4b carve-out arc — CLOSED

Per chat decision 2026-05-03, all four named cp-4b carve-out brands
are now authored as BRIDGE rows. With this PR the arc closes:

| PR | brand → filer | bucket / signals | confidence | fund AUM |
| --- | --- | --- | --- | --- |
| #267 cp-4b-author-trowe | T. Rowe Price (eid 17924) → filer 3616 | A — single CRD chain | HIGH | $1,105.5B |
| #269 cp-4b-author-first-trust | First Trust (eid 8) → filer 136 | B — X1+X2 concordant | MEDIUM | $232.7B |
| #270 cp-4b-author-fmr | Fidelity / FMR (eid 11) → filer 10443 | C — X2 raw-string identical alias | MEDIUM | $415.3B |
| **this PR** cp-4b-author-ssga | State Street / SSGA (eid 3) → filer 7984 | **C — X2 raw-string identical alias** | MEDIUM | **$301.9B** |
| | | | **Total bridged via cp-4b** | **~$2,055.4B** |

### Deferred to cp-4c-manual-sourcing

- **Equitable IM** (eid 2562 → eid 9526) — eid 9526 is Equitable
  Holdings Inc. (public parent). Operating-IA counterparty needs
  verification before authoring. Original Bucket A candidate;
  reclassified DEFER pending sourcing.
- **Bucket D + Bucket C residual (~$10.27T, 15 brands)** — DEFER
  paragraph from PR #269 BLOCKER 2 addendum stands. Normalization-
  collapse FP mode documented in
  [cp-4b-blocker2-corroboration-probe.md](cp-4b-blocker2-corroboration-probe.md).

### Workstream next

- 📦 **conv-27-doc-sync** — ROADMAP + NEXT_SESSION_CONTEXT update
  covering PRs #267/#269/#270 + this PR plus the BLOCKER 2 addendum
  and Equitable cp-4c deferral.
- 📦 **backup-pruning-and-archive** — separate ops PR (local prune +
  Google Drive offload).

## Appendix — files

- `scripts/oneoff/cp_4b_author_ssga.py` — helper (mirrors
  cp_4b_author_fmr.py).
- `data/working/cp-4b-author-ssga-manifest.csv` — single-row manifest
  (pair, eids, source, confidence, AUM, prepared_relationship_id=20,823).
