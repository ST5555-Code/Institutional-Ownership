# cp-4b-author-fmr — results

**Date:** 2026-05-03
**Branch:** `cp-4b-author-fmr`
**Refs:** [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2 addendum landed in PR #269),
[docs/findings/cp-4b-blocker2-corroboration-probe.md](cp-4b-blocker2-corroboration-probe.md), PR #267 (cp-4b-author-trowe), PR #269 (cp-4b-author-first-trust).

Single-brand BRIDGE: brand eid 11 (Fidelity / FMR) → filer eid 10443
(FMR LLC) via `wholly_owned` / `control`. Second named brand from the
cp-4b-blocker2-corroboration-probe Outcome 4 narrow carve-out, and
the first **Bucket C** (X2-only, raw-string identical alias) bridge
authored under the carve-out predicate.

---

## 1. Pre-execution Phase 1 confirmations

Read-only against prod `data/13f.duckdb`.

| check | result |
| --- | --- |
| eid 11 canonical_name | `Fidelity / FMR` (entity_type=`institution`) |
| eid 10443 canonical_name | `FMR LLC` (entity_type=`institution`) |
| eid 10443 holdings_v2 visibility | 52,627 rows / $7,224.110B (probe matrix expected ~52,627 ✓) |
| open relationship `(parent=10443, child=11)` | 0 rows (idempotency ✓) |
| other open rels involving brand eid 11 | 103 rows, all outbound `fund_sponsor` to fund eids (`source='family_name_alias_match'` or `'fund_name_alias_match'`). No inbound `wholly_owned`. Untouched. |
| fund AUM exposure (rollup or dm_rollup = 11) | 73,539 rows / **$415.2713B** (probe expected ~$415.3B ✓) |
| `entity_relationships` baseline | 18,372 total / 16,322 open / `MAX(relationship_id)=20,821` |
| PR #267 trowe row 20820 | present ✓ (parent=3616, child=17924, type=wholly_owned) |
| PR #269 first-trust row 20821 | present ✓ (parent=136, child=8, type=wholly_owned) |

The 103 outbound `fund_sponsor` rows on brand eid 11 stay untouched.
BRIDGE is additive — the new `wholly_owned/control` parent edge to
eid 10443 sits alongside the existing fund-attribution edges without
collision.

## 2. INSERT execution

Pure new-row INSERT into `entity_relationships` in a single
`BEGIN/COMMIT` transaction via `scripts/oneoff/cp_4b_author_fmr.py --confirm`.

Helper mirrors `cp_4b_author_first_trust.py` (PR #269) verbatim with
pair-specific substitutions:

| field | value |
| --- | --- |
| `relationship_id` | **20,822** (baseline `MAX + 1`) |
| `parent_entity_id` | 10443 (filer) |
| `child_entity_id` | 11 (brand) |
| `relationship_type` | `wholly_owned` |
| `control_type` | `control` |
| `is_primary` | TRUE |
| `primary_parent_key` | 10443 |
| `confidence` | `medium` (matches first-trust; corroboration-carve-out tier) |
| `is_inferred` | FALSE |
| `valid_from` | `2026-05-03` |
| `valid_to` | `9999-12-31` |
| `source` | `CP-4b-author-fmr\|pair=1\|pairing_source=cp-4b-corroboration-probe-bucket-C\|confidence=MEDIUM\|signals=X2\|public_record_verified=cp-4b-blocker2-corroboration-probe.md_§7` |

Source string differs from PR #269 (first-trust) only in:
- `pairing_source=cp-4b-corroboration-probe-bucket-C` (Bucket C, not B)
- `signals=X2` (X2 alone, not X1+X2 concordant)

Bucket C carve-out predicate (probe §6): *"X2 alone fires with
brand-side and filer-side aliases sharing identical raw-string
content (not just normalized equality)."* This pair qualifies under
that predicate — the alias `"FIDELITY / FMR"` appears raw-string
identically on both eid 11 and eid 10443.

Hard guards (all passed before COMMIT):

- pre-execution: zero open relationships for `(10443, 11)` pair ✓
- pre-execution: prepared `relationship_id=20,822` does not exist ✓
- post-execution: exactly 1 open `(10443, 11, wholly_owned, control)` row ✓
- post-execution: open-row count delta = +1 (16,322 → 16,323) ✓
- post-execution: `MAX(relationship_id)` delta = +1 (20,821 → 20,822) ✓
- post-execution: total row count delta = +1 (18,372 → 18,373) ✓

## 3. Post-execution validation

| check | result |
| --- | --- |
| spot-check row 20,822 | full 14-column schema written; `created_at`/`last_refreshed_at` populated; `is_primary=TRUE`, `primary_parent_key=10443` |
| filer eid 10443 holdings_v2 | unchanged: 52,627 rows / $7,224.110B (matches Phase 1b) ✓ |
| brand eid 11 fund_holdings_v2 | unchanged: 73,539 rows / $415.2713B (matches Phase 1e) ✓ |
| prior CP-4b bridges (20820 trowe, 20821 first-trust) | both intact, unchanged ✓ |
| pytest tests/ | **416 passed** (baseline) |
| `cd web/react-app && npm run build` | clean (vite ✓ built in 2.25s) |

## 4. peer_rotation_flows status

No recompute triggered. Per BRIDGE-shape precedent (PR #258 cp-4b-blackrock,
PR #267 cp-4b-author-trowe, PR #269 cp-4b-author-first-trust):
`entity_relationships` row insertion does not move
`fund_holdings_v2` rollup attribution, so `peer_rotation_flows`
delta is expected = 0. Consumers traverse the new bridge at read
time via CP-5 (parent-level-display-canonical-reads).

## 5. Workstream status

Per chat decision 2026-05-03: all four cp-4b carve-out brands are
authored as BRIDGE rows (not MERGE). Updated 3-PR plan from PR #269
collapses into a 2-author plan (FMR done, SSGA next), then arc closes.

- ✅ **cp-4b-author-trowe** (PR #267) — $1.11T fund AUM bridged.
- ✅ **cp-4b-author-first-trust** (PR #269) — $232.7B bridged. Bucket B (X1+X2).
- ✅ **cp-4b-author-fmr** (this PR) — **$415.3B bridged. Bucket C
  (X2-only, raw-string identical alias).** First Bucket C BRIDGE.
- ⏭️ **cp-4b-author-ssga** — next. State Street brand eid 3 → filer
  eid 7984. Final carve-out brand. ~$301.9B per probe matrix.
  Closes the cp-4b carve-out arc.
- ⏸️ **Equitable IM** (eid 2562 → eid 9526) — DEFERRED to
  `cp-4c-manual-sourcing`. Eid 9526 is Equitable Holdings Inc.
  (public parent), which may not be the correct operating-IA
  counterparty.
- ⏸️ **Bucket D + Bucket C residual** (~$10.27T, 15 brands) →
  `cp-4c-manual-sourcing`. DEFER paragraph from PR #269 BLOCKER 2
  addendum stands.
- 📦 **backup-pruning-and-archive** — separate ops PR after the
  cp-4b carve-out arc closes (post-SSGA).

## Appendix — files

- `scripts/oneoff/cp_4b_author_fmr.py` — helper (mirrors
  cp_4b_author_first_trust.py).
- `data/working/cp-4b-author-fmr-manifest.csv` — single-row manifest
  (pair, eids, source, confidence, AUM, prepared_relationship_id=20,822).
