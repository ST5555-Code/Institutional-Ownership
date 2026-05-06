# cp-5-aum-subtree-callers-recon — full caller map + sequencing recommendation

**Branch:** `cp-5-aum-subtree-callers-recon` (off `main` @ `945b173` PR #306)
**Date:** 2026-05-06
**Scope:** Read-only investigation. No DB writes. No production code edits.
**Goal:** Map every caller of `compute_aum_for_subtree` ([scripts/queries/entities.py:119](scripts/queries/entities.py:119)), classify caller intent, decide whether `cp-5-aum-subtree-redesign` blocks CP-5.5b or CP-5.6.

---

## TL;DR

- **2 production call sites only** — both inside `scripts/queries/entities.py`. Both terminate at the same React surface: the **Entity Graph tab** via [api_entities.py:136](scripts/api_entities.py:136) `/api/v1/entity_graph`.
- **No CP-5.5b precompute dependency.** `scripts/pipeline/compute_peer_rotation.py` never imports or calls `compute_aum_for_subtree`. CP-5.5b ships independently.
- **CP-5.6 cohort overlaps the redesign.** The "PENDING_CP5_6" cohort in [data/working/cp-5-bundle-c-readers-extended.csv](data/working/cp-5-bundle-c-readers-extended.csv) lists two `entities.py` sites (line ranges `120-170` and `360-400`) whose **current** code at those ranges is exactly `compute_aum_for_subtree` (def) and `get_entity_sub_advisers` (direct caller). The labels in the CSV are stale; the line ranges are the redesign target.
- **Recommendation: Option A — strict serial.** Ship `cp-5-aum-subtree-redesign-execute` before CP-5.6. CP-5.5b can ship in parallel (Option B-style for the precompute side, but that's not what this PR is asking).
- **Parity gap is real but small.** Top-parent grain SUM differs from filer-grain SUM by **−0.15% Vanguard / −1.39% Capital Group / 0% BlackRock** on 2025Q4. Direction (filer > top-parent) suggests the recursive ER walk picks up cross-attribution between umbrella siblings that the canonical climb attributes once.

---

## 1. Callers inventory (Phase 1)

### 1.1 Direct callers — full codebase grep

`grep -rn "compute_aum_for_subtree" scripts/ tests/ web/ docs/`

| File:Line | Class | Note |
|---|---|---|
| [scripts/queries/entities.py:119](scripts/queries/entities.py:119) | DEFINITION | Recursive ER walk (`depth<4`, excludes `sub_adviser`) → distinct CIK set → SUM(`holdings_v2.market_value_usd`) WHERE quarter AND `is_latest=TRUE`. |
| [scripts/queries/entities.py:382](scripts/queries/entities.py:382) | **PRODUCTION_CALLER** | `get_entity_sub_advisers` — per-sub-adviser AUM in the Entity Graph sub-adviser ring. |
| [scripts/queries/entities.py:422](scripts/queries/entities.py:422) | **PRODUCTION_CALLER** | `build_entity_graph` — institution root node (level 0) headline AUM. |
| [scripts/queries/__init__.py:133](scripts/queries/__init__.py:133) | DOC_REFERENCE | Re-export. No live invocation. |
| `scripts/oneoff/cp_5_bundle_c_probe7_4_readers_writers.py:101` | DOC_REFERENCE | PR #281 inventory row. |
| `scripts/oneoff/cp_5_discovery_phase3_readers.py:117` | DOC_REFERENCE | PR #276 discovery row. |
| `tests/test_cp5_5_sector_rotation_new_exits_aum.py:15` | DOC_REFERENCE | S8 deferral docstring. No active test (no other `compute_aum_for_subtree` mention in `tests/`). |
| `docs/findings/cp-5-5-execute-results.md:34,113` | DOC_REFERENCE | PR #306 deferral note + recon-doc correction. |
| `docs/findings/cp-5-5-recon-results.md:83,117,166,193,278` | DOC_REFERENCE | PR #305 recon prose. |

**Inventory:** 2 PRODUCTION_CALLER, 1 DEFINITION, 1 module-level export, 9 docs/probe references. Full table at [data/working/cp-5-aum-subtree-callers.csv](data/working/cp-5-aum-subtree-callers.csv).

### 1.2 Indirect callers (2-hop trace)

| Leaf call site | Hop 1 | Hop 2 | API endpoint | Frontend consumer |
|---|---|---|---|---|
| entities.py:382 (`get_entity_sub_advisers`) | entities.py:453 (`build_entity_graph` per-fund sub-adviser walk) | api_entities.py:136 (`/api/v1/entity_graph`) | `/api/v1/entity_graph` | `web/react-app` EntityGraphTab — vis.js sub-adviser node label |
| entities.py:422 (`build_entity_graph` institution root) | (direct) | api_entities.py:136 | `/api/v1/entity_graph` | EntityGraphTab — institution node label (level 0) |

**Both call sites flow through the same single API endpoint and the same single React component.** The blast radius of a redesign is `EntityGraphTab` only.

### 1.3 Sibling helpers worth comparing

- **`compute_aum_by_cik`** ([scripts/queries/entities.py:107](scripts/queries/entities.py:107)) — single-CIK SUM path used by `get_entity_filer_children` (line 220) and `get_institution_hierarchy` (line 311). Returns AUM for one filer-CIK. Already filer-CIK grain at the leaf. **Not a redesign target.**
- **`top_parent_holdings_join` / `top_parent_canonical_name_sql`** ([scripts/queries/common.py:77,112](scripts/queries/common.py:77)) — CP-5.1 foundation helpers. Map a row to its canonical top-parent via the `inst_to_top_parent` view (migration 027). For 13F (`holdings_v2`) callers, `JOIN inst_to_top_parent ittp ON ittp.entity_id = h.entity_id` is the canonical climb. **Path A/B candidate building block.**

---

## 2. Caller intent classification (Phase 2)

### 2.1 Per-caller intent

| Caller | Intent | Confidence |
|---|---|---|
| entities.py:382 `get_entity_sub_advisers` | **INTENT_FILER_GRAIN** | High. Function name `_for_subtree` is explicit. A sub-adviser firm can itself parent multiple filer-CIKs; the meaningful UI number is "all 13F books filed by this sub-adviser." |
| entities.py:422 `build_entity_graph` (root) | **INTENT_AMBIGUOUS** | UI shows it as "this institution's 13F AUM" — could legitimately mean filer-grain SUM (legacy "sum the children" shape) or top-parent grain (canonical-attribution shape). Direction of the parity gap (filer > top-parent) suggests the current shape over-counts when the same holding sits in two filer-CIKs under the umbrella. |

### 2.2 Parity gap — three known umbrellas, 2025Q4

Probe: [scripts/oneoff/cp_5_aum_subtree_parity_probe.py](scripts/oneoff/cp_5_aum_subtree_parity_probe.py) — read-only on `data/13f.duckdb` (CP-5.1 foundation present; `inst_to_top_parent` view exists).

| eid | name | filer-grain SUM | top-parent SUM | delta | pct | filer-CIK count |
|---:|---|---:|---:|---:|---:|---:|
| 4375 | Vanguard family | $6,908,051,583,469 | $6,897,676,080,637 | −$10,375,502,832 | −0.15% | 3 |
| 3241 | BlackRock | $5,916,347,916,984 | $5,916,347,916,984 | 0 | 0.00% | 1 |
| 12 | Capital Group umbrella | $1,941,966,341,613 | $1,915,006,840,171 | −$26,959,501,442 | −1.39% | 40 |

CSV: [data/working/cp-5-aum-subtree-parity-probe.csv](data/working/cp-5-aum-subtree-parity-probe.csv).

**Reading.** The filer-grain walk is consistently ≥ the top-parent climb. BlackRock's subtree resolves to a single CIK in the CP-5.1 inst_to_top_parent view, so both paths agree exactly. Vanguard and Capital Group expose the over-count: holdings whose live `entity_id` climbs to a *different* canonical top-parent than the one whose subtree-CIK walk would otherwise pick them up. Magnitude is **<1.5% in the worst case**, not a five-sigma display problem, but it does mean **the two intents materially disagree on Capital Group's 2025Q4 number to the tune of $27B**.

### 2.3 Call-site signals

- `compute_aum_for_subtree` docstring says "AUM across all CIKs in an entity's subtree (non-sub_adviser descendants). Used for institution and sub_adviser node totals where the entity is a logical parent aggregating multiple filer CIKs." — explicit filer-grain framing.
- The Entity Graph node label rendering in [web/react-app/src/types/api-generated.ts:725](web/react-app/src/types/api-generated.ts:725) treats the value as opaque AUM; no UI-level distinction between filer- and top-parent grain.

---

## 3. CP-5.6 dependency check (Phase 3)

### 3.1 Per-site DEPENDS / INDEPENDENT

The PENDING_CP5_6 cohort from [data/working/cp-5-bundle-c-readers-extended.csv](data/working/cp-5-bundle-c-readers-extended.csv):

| CSV row | Current code at that line range | DEPENDS? | Note |
|---|---|---|---|
| `scripts/queries/market.py,1040-1130,institution-hierarchy` | (unrelated `holdings_v2 + ER` view-swap site) | **INDEPENDENT** | No `compute_aum_for_subtree` call. |
| `scripts/queries/trend.py,170-205,holder_momentum (fund)` | (unrelated `fund_holdings_v2` view-swap site) | **INDEPENDENT** | No `compute_aum_for_subtree` call. |
| `scripts/queries/entities.py,120-170,get_entity_descendants` | **`compute_aum_for_subtree` def + `get_entity_filer_children`** at current line numbers | **DEPENDS** | The CSV label `get_entity_descendants` is stale (no such function exists in the current tree). The line range *is* the redesign target. |
| `scripts/queries/entities.py,360-400,search_entity_parents` | **`get_entity_sub_advisers`** (lines 359-384) — direct caller at line 382 | **DEPENDS** | The CSV label `search_entity_parents` is stale (that function moved to line 33). Current code at the listed range calls `compute_aum_for_subtree`. |

### 3.2 Stale label / live range gotcha

The two `entities.py` rows in the PENDING_CP5_6 cohort were authored against a pre-CP-5.5 numbering and the **function names are wrong**, but the **line ranges remain correct** for what's at those lines today. CP-5.6 will encounter `compute_aum_for_subtree` (and its caller) directly when it works that file. Anyone consuming the CSV at face value will be confused; suggest a Phase-7 refresh before CP-5.6 starts.

### 3.3 Sequencing recommendation

**Option A — strict serial (RECOMMENDED).** Ship `cp-5-aum-subtree-redesign-execute` before CP-5.6.

Reasons:
1. Two CP-5.6 cohort line ranges land squarely on the redesign target. CP-5.6 cannot apply its standard "view-swap to `unified_holdings`" template here without first deciding the grain question.
2. The grain question (filer vs top-parent) has UI implications for the Entity Graph headline — needs an explicit chat-side decision, not absorbed into a CP-5.6 omnibus PR.
3. Risk of bundling: CP-5.6 PR-size + grain-decision blast radius compound poorly. Splitting keeps the redesign reviewable in isolation.

The 2-hop dependency check found **no** transitive callers beyond the two leaf sites; no need to look deeper than 2 hops.

---

## 4. CP-5.5b precompute dependency check (Phase 4)

`grep -n "compute_aum_for_subtree\|compute_aum_by_cik\|from queries\|import.*entities" scripts/pipeline/compute_peer_rotation.py` returned **zero matches**.

`scripts/pipeline/compute_peer_rotation.py` (799 lines) does not import or invoke `compute_aum_for_subtree`. The CP-5.5b precompute rebuild keys `peer_rotation_flows` by `tp_eid` directly from `holdings_v2 + inst_to_top_parent`, never touching the subtree helper.

**CP-5.5b is independent.** It can ship in parallel with `cp-5-aum-subtree-redesign-execute`, no sequencing constraint between them.

---

## 5. Redesign path candidates (Phase 5)

### 5.1 Path A — keep filer-CIK grain, swap source

Replace the inner `holdings_v2 + is_latest` SUM with a `unified_holdings`-style read while preserving the filer-CIK semantics. Smallest refactor; no UI behavior change beyond what `unified_holdings` already corrects (latest-quarter dedup etc.). Estimated 30 LOC; both call sites unchanged.

- Pros: Minimal blast radius; preserves both callers' current intent.
- Cons: Doesn't address the grain question. Capital Group's $27B over-count remains.

### 5.2 Path B — sister view `filer_unified_holdings`

Build a CP-5.1-style view keyed at filer-CIK grain (mirrors `unified_holdings` but climbs to the filer-CIK rollup, not top-parent). Migrate `compute_aum_for_subtree` to consume it.

- Pros: Reusable foundation for any future filer-grain reader.
- Cons: New view to maintain; second-grain abstraction in the schema. Premature unless other callers need it (none do today).

### 5.3 Path C — caller-by-caller redesign

Split `compute_aum_for_subtree` into two helpers:
1. `compute_aum_for_subtree_filer_grain` — current behavior, retained for `get_entity_sub_advisers` (INTENT_FILER_GRAIN, high confidence).
2. `compute_aum_top_parent` — top-parent climb via `inst_to_top_parent`, used for `build_entity_graph` institution root (resolves the AMBIGUOUS site to top-parent grain — matches CP-5.1 canonical attribution everywhere else in the app).

- Pros: Fixes the grain question; aligns institution headline with the rest of the post-CP-5.1 app; the ambiguous site is the one that matters most (it's what users see as "this firm's AUM").
- Cons: Two helpers + two test surfaces. Requires UI confirmation that the headline number changing by ≤1.5% on umbrellas is acceptable (it is — every other top-parent number in the app has already moved by that magnitude post-CP-5.1).

### 5.4 Path D — deprecate

Not viable. `get_entity_sub_advisers` has a real filer-grain need (sub-adviser shells with multiple filer-CIKs). No equivalent helper exists.

### 5.5 Recommended path — **Path C**

Path C is the only candidate that resolves the grain question instead of papering over it. Path A is a viable fallback if chat decides the parity gap is too small to act on; in that case downgrade `cp-5-aum-subtree-redesign` from P1 to P2 and let CP-5.6 absorb the simple view-swap.

---

## 6. Open questions for chat

1. **Grain decision for `build_entity_graph` root node.** Filer-grain (current) or top-parent grain (Path C)? Material on Capital Group ($27B / −1.39%); immaterial on BlackRock; mild on Vanguard ($10B / −0.15%).
2. **Path A vs Path C.** If chat declines the grain change, Path A is essentially a CP-5.6 line item — should we just fold it into CP-5.6 and close `cp-5-aum-subtree-redesign` as superseded?
3. **CSV label refresh.** Should this PR also fix the stale function names in `cp-5-bundle-c-readers-extended.csv` rows 26 and 28, or leave that for the CP-5.6 author?
4. **Tests.** S8 deferral test ([tests/test_cp5_5_sector_rotation_new_exits_aum.py:15](tests/test_cp5_5_sector_rotation_new_exits_aum.py:15)) — keep as-is until redesign ships, then convert into the actual parity test.

---

## 7. Out-of-scope discoveries / surprises

- **Stale labels in PR #304's PENDING_CP5_6 cohort.** Two of the four entries point at function names that no longer exist at those line numbers. Surface to the CP-5.6 author. Not blocking but a sharp edge.
- **Single API endpoint, single React tab** for both call sites. The Entity Graph tab is the entire blast radius — no other downstream consumer exists. Frees the redesign from cross-tab coordination.
- **`unified_holdings` view does not exist on `data/13f_readonly.duckdb`** (it does on `data/13f.duckdb`). The read-only mirror is behind the writable prod for CP-5.1 artifacts. Worth surfacing before any post-CP-5 cron schedules a reader against the read-only mirror that assumes the view is present.
