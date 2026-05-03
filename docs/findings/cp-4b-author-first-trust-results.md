# cp-4b-author-first-trust — results

**Date:** 2026-05-03
**Branch:** `cp-4b-author-first-trust`
**Refs:** [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2),
[docs/findings/cp-4b-blocker2-corroboration-probe.md](cp-4b-blocker2-corroboration-probe.md), PR #267 (cp-4b-author-trowe), PR #258 (cp-4b-blackrock).

Single-brand BRIDGE: brand eid 8 (First Trust) → filer eid 136
(FIRST TRUST ADVISORS LP) via `wholly_owned` / `control`. First named
brand from the cp-4b-blocker2-corroboration-probe Outcome 4 narrow
carve-out.

---

## 1. Pre-execution Phase 1 confirmations

Read-only against prod `data/13f.duckdb`.

| check | result |
| --- | --- |
| eid 8 canonical_name | `First Trust` (entity_type=`institution`) |
| eid 136 canonical_name | `FIRST TRUST ADVISORS LP` (entity_type=`institution`) |
| eid 136 holdings_v2 visibility | 11,367 rows (probe matrix expected ~11,367 ✓) |
| open relationship `(parent=136, child=8)` | 0 rows (idempotency ✓) |
| other open rels involving brand eid 8 | 227 rows: 1 inbound `wholly_owned` from eid 19601 (`source='orphan_scan'`, untouched) + 226 outbound `fund_sponsor` to fund eids (`source='family_name_alias_match'`) |
| fund AUM exposure (rollup or dm_rollup = 8) | 24,098 rows / **$232.6826B** (probe expected ~$232.7B ✓) |
| `entity_relationships` baseline | 18,371 total / 16,321 open / `MAX(relationship_id)=20,820` |
| PR #267 trowe row 20820 | present ✓ (parent=3616, child=17924, type=wholly_owned) |

The pre-existing `(eid 19601 → eid 8) wholly_owned/orphan_scan` row
stays untouched. Adding eid 136 as a parallel `wholly_owned/control`
parent is the correct fix because eid 136 is the operating, hv2-visible
filer; eid 19601 is invisible.

## 2. INSERT execution

Pure new-row INSERT into `entity_relationships` in a single
`BEGIN/COMMIT` transaction via `scripts/oneoff/cp_4b_author_first_trust.py --confirm`.

Helper mirrors `cp_4b_author_trowe.py` (PR #267) verbatim with the
following pair-specific substitutions:

| field | value |
| --- | --- |
| `relationship_id` | **20,821** (baseline `MAX + 1`) |
| `parent_entity_id` | 136 (filer) |
| `child_entity_id` | 8 (brand) |
| `relationship_type` | `wholly_owned` |
| `control_type` | `control` |
| `is_primary` | TRUE |
| `primary_parent_key` | 136 |
| `confidence` | `medium` (vs. `high` for trowe — distinguishes corroboration-carve-out from single-CRD-chain) |
| `is_inferred` | FALSE |
| `valid_from` | `2026-05-03` |
| `valid_to` | `9999-12-31` |
| `source` | `CP-4b-author-first-trust\|pair=1\|pairing_source=cp-4b-corroboration-probe-bucket-B\|confidence=MEDIUM\|signals=X1+X2\|public_record_verified=cp-4b-blocker2-corroboration-probe.md_§7` |

Hard guards (all passed before COMMIT):

- pre-execution: zero open relationships for `(136, 8)` pair ✓
- pre-execution: prepared `relationship_id=20,821` does not exist ✓
- post-execution: exactly 1 open `(136, 8, wholly_owned, control)` row ✓
- post-execution: open-row count delta = +1 (16,321 → 16,322) ✓
- post-execution: `MAX(relationship_id)` delta = +1 (20,820 → 20,821) ✓
- post-execution: total row count delta = +1 (18,371 → 18,372) ✓

## 3. Post-execution validation

| check | result |
| --- | --- |
| spot-check row 20,821 | full schema written; `created_at`/`last_refreshed_at` populated |
| open `wholly_owned/control` parents of eid 8 | 2 rows (`19601` orphan_scan + `136` new bridge) — `TRUE_BRIDGE_ENCODED` count Δ +1 |
| filer eid 136 holdings_v2 | unchanged: 11,367 rows / $509.1698B |
| trowe row 20820 | unchanged ✓ |
| pytest tests/ | **416 passed** (baseline) |
| `cd web/react-app && npm run build` | clean (vite ✓ built in 1.50s) |

## 4. peer_rotation_flows status

No recompute triggered. Per BRIDGE-shape precedent (PR #258 cp-4b-blackrock,
PR #267 cp-4b-author-trowe): `entity_relationships` row insertion does
not move `fund_holdings_v2` rollup attribution, so
`peer_rotation_flows` delta is expected = 0. Consumers traverse the
new bridge at read time via CP-5 (parent-level-display-canonical-reads).

## 5. BLOCKER 2 amendment

`docs/decisions/inst_eid_bridge_decisions.md` updated in the same PR.
A new `### BLOCKER 2 — addendum (2026-05-03)` subsection ships the
4-signal probe Outcome 4 verbatim from the probe findings §6, with
the CARVE-OUT paragraph adapted for the **3-PR split** confirmed in
chat 2026-05-03:

  1. `cp-4b-author-first-trust` (this PR) — single BRIDGE row, $232.7B.
  2. `cp-4b-merge-fmr-ssga` (next) — two-pair MERGE following PR #256
     (CP-4a Vanguard/PIMCO) precedent (Op F + Op H). ~$717.2B combined.
  3. **Equitable IM** (eid 2562 → eid 9526) — DEFERRED to
     `cp-4c-manual-sourcing`. Eid 9526 is Equitable Holdings Inc.
     (public parent), which may not be the correct operating-IA
     counterparty.

DEFER paragraph: 15 remaining brands (Bucket C residual + Bucket D,
~$10.27T) → `cp-4c-manual-sourcing`. Failure-mode list shipped verbatim.

## 6. Workstream status

- ✅ **cp-4b-author-first-trust** — shipped (this PR). $232.7B fund AUM
  bridged. BLOCKER 2 strict rule remains; carve-out amendment landed.
- ⏭️ **cp-4b-merge-fmr-ssga** — next. MERGE shape; needs fresh
  prompt-side op design per PR #256 5-correction note + Op F + Op H
  hygiene.
- ⏸️ **Equitable IM** — held for `cp-4c-manual-sourcing`.
- 📦 **backup-pruning-and-archive** — separate ops PR after FMR/SSGA
  ships.

## Appendix — files

- `scripts/oneoff/cp_4b_author_first_trust.py` — helper (mirrors
  cp_4b_author_trowe.py).
- `data/working/cp-4b-author-first-trust-manifest.csv` — single-row
  manifest (pair, eids, source, confidence, AUM, prepared_relationship_id).
- `docs/decisions/inst_eid_bridge_decisions.md` — BLOCKER 2 addendum.
