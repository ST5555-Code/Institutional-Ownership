# cp-5-loader-gap-remediation-sub2 — results

**Date:** 2026-05-05
**Branch:** `cp-5-loader-gap-remediation-sub2`
**Predecessor:** PR [#290](https://github.com/ST5555-Code/Institutional-Ownership/pull/290) `cp-5-loader-gap-remediation-sub1` (squash `07cceb5`)
**Successors:** `cp-5-pipeline-contract-cleanup` (Bundle C §7.5 Gaps 4 + 7), then `cp-5-sister-tables-sized-investigation`

Closes the loader-gap workstream. Creates 53 new institution-typed entities
(52 UNMATCHED `fund_cik` registrants from Bundle B §2.4 + 1 Fidelity CLO ETF
carve-out from sub-PR 1), populates `fund_holdings_v2.entity_id` for the
final 26,008 NULL-attribution rows, and writes self-rollup rows in
`entity_rollup_history` for both `decision_maker_v1` and
`economic_control_v1` (the latter added in-flight per §3.2).

After this PR, all 84,363 originally-gap rows / $418.55B are linked.
Method A reads cover the full cohort. Sub-PR 3 (separate ERH rebuild)
eliminated as planned.

---

## 1. Phase 1 cohort re-validation

### 1.1 53-CIK manifest

| Metric | Bundle B §2.4 routed-to-sub2 | Phase 1 actual | Drift |
|---|---:|---:|---:|
| Rows | 26,008 | 26,008 | 0% |
| AUM | $32.17B | $32.16B | −0.03% |
| Distinct fund_ciks | 53 | 53 | 0% |

Source split: 52 UNMATCHED + 1 FMR_CARVE_OUT. No ANOMALY rows.

### 1.2 Name-variant resolution

18 of 53 CIKs carry > 1 distinct `fund_name` across N-PORT periods
(registrants reorganized series, renamed, or rotated wrappers). The
helper picks the most-common variant as canonical (ties → lexicographic
min for determinism). Notable:

- **CIK 0002025968 (BNY Mellon)** — 6 sub-fund names under one CIK;
  canonical = `BNY Mellon Municipal Opportunities ETF` (most-common, 687
  rows). Master-trust wrapper; the entity represents the registrant, not
  any single sub-fund.
- **CIK 0001852344 (Variable Insurance Products / "Portfolio I")** —
  6 sub-portfolios; canonical = `International Portfolio I` (46 rows).
- **CIK 0001924868 / 0001771146** — name churn around crypto/leveraged
  ETF rebrands; canonical chosen by recency of dominance.

Full per-CIK manifest: `data/working/cp-5-loader-gap-sub2-manifest.csv`.

### 1.3 FMR carve-out pre-state

CIK `0000945908` (Fidelity CLO ETF) confirmed pre-linked to FMR LLC eid
10443. FMR LLC held exactly 2 open CIKs pre-execution (its own filer CIK
`0000315066` + the carve-out). Matches PR #290 §1.5 expectation.

### 1.4 Prior bridges intact

All 9 prior `entity_relationships` rows present (cp-4a × 2, cp-4b × 4,
Adams × 1, cycle-truncated end × 1, Capital Group umbrella × 1).
Relationship IDs: `{20813, 20814, 20820, 20821, 20822, 20823, 20830,
20840, 20843}`.

### 1.5 Pre-write baseline

`max(entity_id) = 27259` → new entities allocated `27260..27312`.
`max(relationship_id) = 20843` (no new relationships in this PR).

---

## 2. Phase 2 dry-run manifest

`data/working/cp-5-loader-gap-sub2-manifest.csv` (53 rows). Phase 3
entry gate:

- Manifest rows: **53** ✓
- FMR_CARVE_OUT (transfer): **1** ✓
- UNMATCHED (insert): **52** ✓
- New `entity_id` range: `27260..27312` (sequential, contiguous) ✓
- Total fh2 rows: **26,008** ✓
- Total AUM: **$32.16B** ✓

---

## 3. Phase 3 execute

### 3.1 Per-op counts (single transaction)

| Op | Action | Count |
|---|---|---:|
| A | INSERT `entities` (institution, is_inferred=TRUE) | 53 |
| B.1 | UPDATE `entity_identifiers` close-on-collision (FMR carve-out) | 1 |
| B.2 | INSERT `entity_identifiers` open `cik` row | 53 |
| C | INSERT `entity_aliases` (brand, is_preferred=TRUE) | 53 |
| D | INSERT `entity_classification_history` (`mixed`, inferred) | 53 |
| E | INSERT `entity_rollup_history` (`decision_maker_v1` self) | 53 |
| F | UPDATE `fund_holdings_v2.entity_id` | 26,008 |

All seven operations executed inside a single `BEGIN/COMMIT`.

### 3.2 In-flight discovery — Op E2 added (economic_control_v1)

Spot check after the original 7-op COMMIT showed
`entity_current.rollup_entity_id IS NULL` for all 53 new entities —
the `entity_current` view sources `rollup_entity_id` from
`entity_rollup_history WHERE rollup_type = 'economic_control_v1'`.
The plan only specified `decision_maker_v1`. bootstrap_tier4 precedent
(eid 27200..27259 inspected) populates **both** rollup types. Without
the `economic_control_v1` self-row, `entity_current` would yield
`NULL` rollup for these 53 entities, breaking parent-level joins
downstream.

**Patch:** 53 `economic_control_v1` self-rollup rows inserted in a
separate transaction, with assertion that `entity_current.entity_id =
rollup_entity_id` for the new range. Helper script updated to include
**Op E2** so the script reflects the complete remediation (and re-runs
cleanly against a hypothetical clean DB). Guard 5 extended to assert
both rollup types.

This is a documentation/rollup gap in the plan; the underlying data
shape now matches bootstrap_tier4 precedent exactly.

### 3.3 Hard-guard results (all passing post-E2 patch)

| # | Guard | Result |
|---|---|---|
| 1 | 53 new entities in range | OK |
| 2 | 1 open CIK per new eid; FMR LLC 2 → 1 open CIK | OK |
| 3 | 53 open aliases | OK |
| 4 | 53 open ECH rows (`mixed` / `medium` / inferred) | OK |
| 5 | 53 open ERH self-rollups for both rollup types | OK |
| 6 | fh2 NULL `entity_id` count: 26,008 → 0 | OK |
| 7 | fh2 row count unchanged (14,565,870) | OK |
| 8 | fh2 AUM unchanged: $161,590.4706B (within $0.01B tolerance) | OK |
| 9 | Method A JOIN matches manifest for 10 samples | OK |

#### Guard 9 logic refinement (in-flight)

First `--confirm` run (with Op B's planned `is_preferred` column)
ROLLBACK'd cleanly on `entity_identifiers` schema mismatch
(`is_preferred` does not exist; `entity_aliases` carries it instead).
The plan template predated the actual schema. Op B was rewritten to
match precedent: `(entity_id, identifier_type, identifier_value,
confidence='exact', source='CP-5-pre:...', is_inferred=TRUE,
valid_from=CURRENT_DATE, valid_to='9999-12-31')`.

Second run ROLLBACK'd cleanly on Guard 9 over-broad filter:
`WHERE fh.fund_cik = ?` matched ALL fh2 rows for that CIK regardless of
`entity_id`. fh2.fund_cik is many-to-many with entities (pre-existing
rows for the same CIK link to multiple entities via different mapping
paths). Guard 9 tightened to `WHERE fh.fund_cik = ? AND fh.entity_id =
<new_eid>`. Third run COMMIT'd cleanly.

Both rollbacks left the DB unchanged — single-transaction discipline
held. No partial state.

---

## 4. Phase 4 — peer_rotation_flows recompute

```
pre rows : 17,489,564
post rows: 17,489,564
Δ        : 0 rows
runtime  : 6 min 34 s
```

Δ=0 as expected per plan. The 53 new entities are decision-maker
self-rollups with no holdings_v2 (parent-level) data — they appear as
fund_cik registrants in `fund_holdings_v2` only. Fund-tier rotation is
computed off `fund_holdings_v2 + economic_control_v1` rollup, but
peer_rotation specifically aggregates by `(rollup_entity_id, ticker)`,
and for these new entities `rollup_entity_id == entity_id`, so they
contribute 0 cross-quarter flow rows (no prior period).

Snapshot: `data/backups/peer_rotation_peer_rotation_empty_20260505_210801.duckdb`.

---

## 5. Phase 5 validation

- **pytest:** 416/416 passed (75.7s baseline, 99.3s post; matches PR #290 baseline).
- **npm run build:** OK, 0 errors, all bundles emitted.
- **Spot checks:**
  - 10 sample new eids: `entity_current.display_name` matches `canonical_fund_name` ✓
  - 10 sample new eids: `entity_current.rollup_entity_id == entity_id` (post Op E2 patch) ✓
  - FMR LLC eid 10443: 1 open CIK = `0000315066` (own filer only) ✓
  - Fidelity CLO ETF eid 27260: 1 open CIK = `0000945908`, canonical = `Fidelity CLO ETF` ✓
  - `fund_holdings_v2 WHERE entity_id IS NULL AND is_latest = TRUE`: **0** ✓
- **App smoke test:** `python3 scripts/app.py --port 8001` → HTTP 200 on `/`. Clean startup, no errors. App stopped cleanly.

---

## 6. Sub-PR 3 elimination

Per chat decision 2026-05-05, Op E (decision_maker_v1 self-rollup) was
inlined at entity-creation time, eliminating the originally-planned
sub-PR 3 (separate ERH rebuild). PR #290's Phase 4 spot check
confirmed sub-PR 1's 23 LINKABLE entities already had
`decision_maker_v1` ERH coverage from prior loader runs — only the 53
new entities created here needed the inserts.

The in-flight Op E2 patch (§3.2) extends this contract to
`economic_control_v1` for the 53 new entities. Both rollup tables are
now populated for the entire 53-entity cohort, matching the
bootstrap_tier4 precedent observed at eid 27200..27259.

---

## 7. Loader-gap AUM coverage closure

| Stage | Unattributed rows | Unattributed AUM |
|---|---:|---:|
| Pre-sub-PR 1 (Bundle B §2.4) | 84,363 | $418.55B |
| Post-sub-PR 1 (linked 23 LINKABLE) | 26,008 | $32.16B |
| Post-this-PR (linked 53 new + carve-out) | **0** | **$0.00B** |

Loader-gap workstream **CLOSED**. Method A reads cover the full
$418.55B that was previously invisible in fund-tier rollups.

---

## 8. P0 pre-execution status

| # | PR | Status |
|---|---|---|
| 1 | cp-5-adams-duplicates (PR #283) | shipped |
| 2 | cp-5-cycle-truncated-merges (PR #285) | shipped |
| 3 | cp-5-capital-group-umbrella (PR #287) | shipped |
| 4 | cp-5-fh2-dm-rollup-drop (PR #289) | shipped |
| 5 | cp-5-loader-gap-remediation-sub1 (PR #290) | shipped |
| 6 | cp-5-loader-gap-remediation-sub2 (this PR) | **shipped** |
| 7 | cp-5-pipeline-contract-cleanup | next |
| 8 | cp-5-sister-tables-sized-investigation | pending |
| 9 | cp-5-sister-tables-drop (conditional) | pending |

6/9 P0 PRs shipped. Next: `cp-5-pipeline-contract-cleanup` (Bundle C
§7.5 Gaps 4 + 7 — `bootstrap_*_advisers.py` retire/gate +
`entity_relationships.is_inferred` populate convention).

---

## 9. Out-of-scope discoveries / surprises

1. **Plan ↔ schema drift on `entity_identifiers.is_preferred`** — the
   `is_preferred` column lives on `entity_aliases`, not
   `entity_identifiers`. Plan template predated the actual schema. Helper
   rewritten to use `confidence` / `source` / `is_inferred` (the columns
   that *do* exist). Worth refreshing the canonical CP-5 op-shape doc.

2. **`entity_current` view requires `economic_control_v1` self-rollup**
   — see §3.2. Any future entity-creation PR must populate **both**
   rollup types or downstream parent-level reads will return NULL
   rollup. Recommend adding this contract to the cp-5 design notes for
   subsequent PRs.

3. **fh2.fund_cik is many-to-many with entities** — not a 1:1 mapping.
   Pre-existing fh2 rows for the same `fund_cik` link to multiple
   entities via different mapping paths (e.g., name-based vs CIK-based).
   Phase 1's "UNMATCHED" classification correctly identified the rows
   where the CIK had **no** open `entity_identifiers` row, but said
   nothing about how the same CIK might already point to other entities
   via fh2.entity_id directly. This shape is fine for Method A reads
   (each row's `entity_id` is independent) but is worth noting for any
   future audit that assumes fund_cik uniqueness.

4. **53 fund-CIK registrants imply 53 institutional-typed entities,
   not 53 fund-typed.** Per chat decision D2, all 53 are
   `entity_type='institution'` to match dominant precedent in PR #290's
   LINKABLE cohort. The `mixed` / `inferred=TRUE` / `confidence=medium`
   ECH classification flags these for future review when sub-fund
   typing becomes a workstream (CP-5.x bucket).

5. **Two of the new entities are crypto / leveraged-rebrand registrants
   with rapid name churn** (CIK 0001924868, 0001771146). The canonical
   name picked is the dominant variant by row count, but follow-on
   registrants may rebrand again. Worth surfacing if a generic
   "stale-name" sweep runs later.
