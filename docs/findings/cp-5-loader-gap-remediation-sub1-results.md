# cp-5-loader-gap-remediation-sub1 — results

**Date:** 2026-05-05
**Branch:** `cp-5-loader-gap-remediation-sub1`
**Predecessor:** PR [#289](https://github.com/ST5555-Code/Institutional-Ownership/pull/289) `cp-5-fh2-dm-rollup-drop` (squash `d8a64bd`)
**Successors:** `cp-5-loader-gap-remediation-sub2` (UNMATCHED + carve-out audit), `cp-5-loader-gap-remediation-sub3` (ERH rebuild for affected entities)

Closes the LINKABLE portion of the 84,363-row `entity_id IS NULL` cohort in
`fund_holdings_v2` surfaced in Bundle B §2.4 / Bundle C §7.5 Gap 1. 23 fund_ciks
where `entity_identifiers` already carries the CIK linked to an existing entity
were propagated to `fund_holdings_v2.entity_id` under 6 hard guards in a single
transaction.

---

## 1. Phase 1 cohort revalidation

### 1.1 84K cohort total reconfirmed

| Metric | Bundle B baseline | Phase 1 actual | Drift |
|---|---:|---:|---:|
| Rows | 84,363 | 84,363 | 0% |
| AUM | $418.5B | $418.55B | +0.01% |
| Distinct fund_ciks | ~50 | 76 | +52% |

Row count and AUM match Bundle B exactly. Distinct CIK count is materially
higher — see §1.3 / §6.

### 1.2 CIK breakdown (top concentrations)

Top 10 by AUM (full breakdown in
`data/working/cp-5-loader-gap-cik-breakdown.csv`):

| fund_cik | sample_fund_name | n_rows | aum_b |
|---|---|---:|---:|
| 0000013075 | Bond Fund of America | 5,801 | 101.15 |
| 0000050142 | Tax Exempt Bond Fund of America | 10,606 | 48.16 |
| 0000826813 | Intermediate Bond Fund of America | 2,849 | 28.54 |
| 0000925950 | American High-Income Municipal Bond Fund | 7,418 | 26.59 |
| 0000823620 | American High Income Trust | 1,027 | 26.30 |
| 0001475712 | Global Opportunities Portfolio | 2,964 | 24.59 |
| 0001484750 | Cohen & Steers Preferred Securities & Income Fund, Inc. | 581 | 14.83 |
| 0000933188 | Senior Debt Portfolio | 1,349 | 13.75 |
| 0001368040 | Short-Term Bond Fund of America | 1,432 | 12.60 |
| 0000909427 | Limited Term Tax Exempt Bond Fund of America | 3,843 | 11.89 |

Cohort is dominated by American Funds (Capital Group brand) bond funds — top 9
of the top 10 are Capital Group-managed. Long tail of 60+ smaller-AUM CIKs.

### 1.3 Classification (LINKABLE / UNMATCHED / CARVED_OUT)

Each distinct CIK was checked against `entity_identifiers` for open
`identifier_type='cik'` rows (`valid_to = DATE '9999-12-31'`):

| Bucket | n_ciks | n_rows | aum_b |
|---|---:|---:|---:|
| LINKABLE (1 open match) | 23 | 58,355 | 386.38 |
| CARVED_OUT (see §1.5) | 1 | 20 | 0.028 |
| UNMATCHED (0 open matches) | 52 | 25,988 | 32.14 |
| LINKABLE_MULTI (>1 open match) | 0 | 0 | 0.00 |
| EXISTS_BUT_CLOSED | 0 | 0 | 0.00 |
| **Total** | **76** | **84,363** | **418.55** |

Full table in `data/working/cp-5-loader-gap-classification.csv`.

### 1.4 Target entity sanity check (relaxed shape)

Per chat decision 2026-05-05, the canonical-shape check was relaxed to
`entity_type IN ('fund', 'institution') AND open CIK count = 1`. Under the
relaxed rule, all 23 LINKABLE targets PASS:

- `entity_type` distribution across the 23 targets: **`{'institution': 23}`**
- Open CIK count per target: **1 for all 23** (1:1 fund-cik shape)
- `entity_classification_history` open row present: **23/23** (all `'active'`)
- Rejected by relaxed rule: 1 (the carved-out `0000945908` — see §1.5)

### 1.5 Carve-out: 0000945908 (Fidelity CLO ETF → FMR LLC)

`fund_cik = 0000945908` is pre-linked to `entity_id = 10443` (FMR LLC, the
parent adviser entity from `cp-4b-author-fmr` PR
[#270](https://github.com/ST5555-Code/Institutional-Ownership/pull/270)). FMR
LLC carries 2 open CIK identifiers (its own filer CIK `0000315066` plus this
fund-side CIK), violating the 1:1 shape that holds for the other 23 LINKABLE
targets.

**Cohort impact at sub-PR 1 closure:** 20 rows / $0.028B remaining
unattributed (~0.007% of $418.55B). Routed to sub-PR 2 for audit.

**Possible resolutions in sub-PR 2:**
1. Create a new fund-typed entity for the Fidelity CLO ETF and re-point the
   `entity_identifier` row from FMR LLC to the new entity.
2. Confirm the FMR LLC linkage was intentional (e.g., umbrella attribution
   pattern for a small loader-bug residual) and propagate with explicit
   documentation; the canonical shape would then need an explicit exception.

### 1.6 Empirical finding — entity_type='institution' for all 23 LINKABLE targets

All 23 LINKABLE targets carry `entity_type='institution'`, not `'fund'`. Per-fund
registrant CIKs in `fund_holdings_v2` are linked to institution-typed entities
in this codebase, not fund-typed entities. This is consistent with the dominant
pattern in the cohort but raises the question whether N-PORT-seeded
registrant-CIK entities should carry `entity_type='fund'` instead.

**Two possible explanations:**
1. **Intentional convention** — the N-PORT loader treats registrant-CIK
   entities as institutions, with fund-tier identity carried in `fund_universe`
   rows; the entity is the issuer/registrant, not the fund product.
2. **Loader bug** — the entities should be `'fund'` and have been mis-typed at
   seed time.

**Why sub-PR 1 ships correctly under either explanation:** Method A JOIN does
not filter by `entity_type`. The retyping question is routed to a follow-up
audit added to ROADMAP P3 as `fund-cik-entity-type-audit` (don't act on this
in `conv-30-doc-sync` — defer to chat-side decision after CP-5.1 ships).

---

## 2. Phase 2 dry-run manifest

`data/working/cp-5-loader-gap-remediation-sub1-manifest.csv` was authored
covering 23 LINKABLE CIKs (FMR LLC carve-out applied):

- Total rows to update: **58,355**
- Total AUM linked: **$386.38B**
- All 23 target_entity_ids verified to exist in `entities` table.

Phase 3 entry-gate checks all printed and passed prior to `--confirm`.

---

## 3. Phase 3 execute

### 3.1 Per-CIK update counts

Single `BEGIN ... COMMIT` block. For each of the 23 LINKABLE CIKs:

```sql
UPDATE fund_holdings_v2
   SET entity_id = <target_entity_id>
 WHERE fund_cik = <cik>
   AND entity_id IS NULL
   AND is_latest = TRUE;
```

All 23 per-CIK post-update counts matched manifest expectations exactly.

### 3.2 All 6 hard guards passed

| # | Guard | Result |
|---|---|---|
| 1 | per-CIK update counts ≥ manifest expectations | OK — 23/23 |
| 2 | zero leftover NULL `entity_id` for LINKABLE CIKs | OK — 0 leftover |
| 3 | UNMATCHED rows reduced exactly by 58,355 | OK (84,363 → 26,008) |
| 4 | attributed rows increased exactly by 58,355 | OK (14,481,507 → 14,539,862) |
| 5 | total `is_latest` AUM unchanged within $0.01B tolerance | OK |
| 6 | every fh2 `entity_id` links to `entities` | OK |

`COMMIT OK`.

Post-PR residual unattributed: **26,008 rows / $32.16B** (= 25,988 UNMATCHED +
20 carved-out FMR-linked rows; matches Phase 1 expectation exactly).

---

## 4. Phase 4 ERH coverage spot-check

Sample of 5 LINKABLE CIKs queried against `entity_rollup_history` filtered to
`rollup_type = 'decision_maker_v1'` open rows:

| fund_cik | target_eid | rollup_present |
|---|---|---|
| 0000013075 | 26537 (Bond Fund of America) | 5/5 |
| 0000050142 | 26538 (Tax Exempt Bond Fund of America) | 5/5 |
| 0000826813 | 26542 (Intermediate Bond Fund of America) | 5/5 |
| 0000925950 | 26543 (American High-Income Municipal Bond Fund) | 5/5 |
| 0000823620 | 26544 (American High Income Trust) | 5/5 |

### 4.1 Which LINKABLE CIKs already have ERH coverage

All 5 sampled CIKs (top of manifest by AUM) have ERH coverage on the linked
entity. This is a stronger result than the prompt anticipated: the targets are
not just present in `entities` but also already carry `decision_maker_v1` ERH
rows — meaning Method A reads will pick up rollup attribution immediately,
without waiting on sub-PR 3.

### 4.2 Which need sub-PR 3 ERH rebuild

To be enumerated in sub-PR 3's Phase 1 audit. The sample suggests sub-PR 3's
scope may be materially smaller than the original framing (which assumed all
23 LINKABLE targets needed ERH rebuild). Plausibly sub-PR 3's load is limited
to whatever long-tail entities lack the rollup row.

---

## 5. Phase 5 validation

| Check | Result |
|---|---|
| pytest tests/ | **416 passed** in 81.92s |
| npm run build (web/react-app) | **0 errors**, vite ✓ built in 1.60s |
| App smoke (port 8001) | HTTP 200 |

---

## 6. P0 pre-execution status + UNMATCHED expansion note

### 6.1 P0 pre-execution status

Sub-PR 1 closes part of one of the 5 P0 pre-execution PRs (~0.33 of 1).

After this PR: **4.33 / 9** P0 pre-execution items shipped:
1. ~~`cp-5-adams-duplicates`~~ (PR [#283](https://github.com/ST5555-Code/Institutional-Ownership/pull/283))
2. ~~`cp-5-cycle-truncated-merges`~~ (PRs [#285](https://github.com/ST5555-Code/Institutional-Ownership/pull/285), [#286](https://github.com/ST5555-Code/Institutional-Ownership/pull/286))
3. ~~`cp-5-capital-group-umbrella`~~ (PR [#287](https://github.com/ST5555-Code/Institutional-Ownership/pull/287))
4. ~~`cp-5-fh2-dm-rollup-drop`~~ (PR [#289](https://github.com/ST5555-Code/Institutional-Ownership/pull/289))
5. **`cp-5-loader-gap-remediation-sub1`** (this PR)
6. `cp-5-loader-gap-remediation-sub2` — next
7. `cp-5-loader-gap-remediation-sub3` — after sub-PR 2
8. `cp-5-pipeline-contract-cleanup` (Gaps 4 + 7)
9. Sister-tables sized investigation → conditional `cp-5-holdings-v2-dm-rollup-drop` + `cp-5-bo-v2-dm-rollup-drop`

### 6.2 AUM coverage gap reduction

| State | Rows | AUM | % of original gap |
|---|---:|---:|---:|
| Pre-PR (Bundle B baseline) | 84,363 | $418.55B | 100% |
| Post-PR (sub-PR 1 closure) | 26,008 | $32.16B | 7.7% |
| **Reduction this PR** | **58,355** | **$386.38B** | **92.3%** |

Sub-PR 1 closes the largest tranche of the loader-gap by AUM. Sub-PRs 2 + 3
clear the residual $32.16B (52 UNMATCHED CIKs + 1 carved-out CIK) plus any ERH
rebuilds needed for affected entities.

### 6.3 UNMATCHED expansion note

Bundle B Phase 2.4 estimated UNMATCHED at ~27 CIKs. Phase 1 revalidation
surfaced **52 UNMATCHED CIKs — nearly 2× the estimate**. Cohort total
(84,363 rows / $418.55B) matches Bundle B exactly, but distribution across
CIKs skewed: 76 distinct CIKs total vs ~50 expected.

**Sub-PR 2 scope expands accordingly.** Chat will decide sub-PR 2 batching
(single PR vs split by sector/size) after sub-PR 1 ships. Per-CIK AUM in the
UNMATCHED tail is small (avg $0.62B per CIK), so a single PR with a clear
batched cohort table is plausible, but the $32.14B total could also be split
into a "Capital Group-style umbrella" cohort and a long-tail CEF/ETF cohort.

---

## 7. Hard guards: why each one matters

| # | Guard | Failure mode it prevents |
|---|---|---|
| 1 | per-CIK count ≥ manifest | partial UPDATE due to mid-tx race or filter bug |
| 2 | zero leftover NULL for LINKABLE | residual unattributed rows on a CIK we promised to close |
| 3 | UNMATCHED untouched | over-reaching UPDATE on rows belonging to sub-PR 2 |
| 4 | attributed delta = expected | spurious rows dragged into `is_latest=TRUE` or off |
| 5 | AUM unchanged | a row was deleted/replaced rather than updated |
| 6 | referential integrity | UPDATE pointed to a non-existent entity |

All 6 must pass before COMMIT; ROLLBACK on any failure with the same single tx.

---

## 8. Out-of-scope discoveries

1. **§1.6 entity_type='institution'** — see ROADMAP P3 entry
   `fund-cik-entity-type-audit` (added in this PR's commit).
2. **§6.3 UNMATCHED expansion** — sub-PR 2 sizing chat decision pending.
3. **§4 ERH coverage of LINKABLE targets** — sub-PR 3 may have smaller scope
   than originally framed.
4. **§1.5 FMR LLC carve-out** — sub-PR 2 to decide between (a) creating a
   per-fund entity for Fidelity CLO ETF and re-pointing the identifier, or
   (b) confirming the FMR LLC linkage as intentional umbrella attribution.

---

## 9. Files

- `scripts/oneoff/cp_5_loader_gap_remediation_sub1.py` — phase 1/2/3 orchestrator
- `data/working/cp-5-loader-gap-cik-breakdown.csv` — per-CIK row+AUM breakdown
- `data/working/cp-5-loader-gap-classification.csv` — per-CIK classification
- `data/working/cp-5-loader-gap-remediation-sub1-manifest.csv` — execution manifest
- `docs/findings/cp-5-loader-gap-remediation-sub1-results.md` — this doc
- `ROADMAP.md` — P0 sub-PR 1 closure note + new P3 `fund-cik-entity-type-audit`

---

## 10. Next

1. Chat receives PR results.
2. `cp-5-loader-gap-remediation-sub2` — 52 UNMATCHED CIKs + FMR LLC carve-out audit (single PR vs split TBD).
3. `cp-5-loader-gap-remediation-sub3` — ERH rollup rebuild for affected entities (likely smaller than originally framed per §4).
4. `cp-5-pipeline-contract-cleanup` (Gaps 4 + 7).
5. Sister-tables sized investigation.
6. Conditional: `cp-5-holdings-v2-dm-rollup-drop` + `cp-5-bo-v2-dm-rollup-drop`.
7. `conv-30-doc-sync`.
8. CP-5.1.
