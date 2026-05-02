# Institution-Scoping Phase 1B + 1.5 — Findings Fragment

**Scope:** Read-only audit of fund-to-institution rollup integrity (`fund_holdings_v2`, `is_latest=TRUE`) and cross-tier consistency vs. `holdings_v2` (institution layer).
**Worktree:** `.claude/worktrees/pensive-montalcini-650089`
**Date:** 2026-05-02
**Prod DB:** `data/13f.duckdb` (read-only)
**Helpers:**
- `scripts/oneoff/institution_scoping_phase1b_rollup_integrity.py`
- `scripts/oneoff/institution_scoping_phase15_cross_tier.py`
- Raw outputs: `docs/findings/_phase1b_raw.json`, `docs/findings/_phase15_raw.json`

**Universe baseline (`fund_holdings_v2 WHERE is_latest=TRUE`):**
- Rows: **14,565,870**
- AUM: **$161,590B** ($161.59T)

---

## Phase 1B.1 — Orphan funds (no rollup target)

| Failure mode | Rows | AUM | Sample |
|---|---:|---:|---|
| `dm_rollup_entity_id IS NULL` | **84,363** | **$418.5B** | VOYA Intermediate Bond Portfolio (CIK 0000002646, S000008760), Bond Fund of America (0000013075, S000009231), Tax Exempt Bond Fund of America (0000050142), Northeast Investors Trust (0000072760), ELFUN Tax Exempt Income (0000215740), AFL CIO Housing Investment Trust (0000225030), ELFUN Income Fund (0000717854), Hawaiian Tax-Free Trust (0000750909), Colorado BondShares A Tax Exempt (0000810744), Capital World Bond Fund (0000812303) |
| `dm_rollup_entity_id` set but **no `entities` row** | 0 | — | — |

**Interpretation:** orphan-by-NULL is the only orphan failure mode in prod today; ~84K rows / $418B unattributed. All non-NULL rollups resolve to a real `entities` row (referential integrity is intact at the FK level).

---

## Phase 1B.2 — Dangling rollup (rolls up to garbage entity)

| Failure mode | Rows | AUM | Distinct entities |
|---|---:|---:|---:|
| Rollup target name in `('N/A','NA','UNKNOWN','NONE','NULL','')` or NULL | **0** | $0 | 0 |
| `dm_rollup_entity_id = 11278` (the literal Calamos N/A entity) | **0** | $0 | — |
| Rollup target has `entity_type='fund'` (rolled up to a fund, not an institution) | **221,445** | **$871.3B** | **187** |

**Calamos N/A shape (PR #251 ASA fix):** zero residual `is_latest=TRUE` exposure to entity 11278 *or* any other suspiciously-named entity. **Entity 11278 is the only N/A-named entity in `entities`** and it has been fully purged from the live fund layer. PR #251's flip-and-relabel work has cleared this shape end-to-end.

**New shape uncovered — fund-as-rollup-target:** 221,445 rows / $871.3B roll up to entities whose `entity_type='fund'` instead of `'institution'`. These will not appear correctly in any institution-level Admin Refresh view because their rollup target is a fund, not an asset manager. Top targets by AUM:

| `dm_rollup_entity_id` | `canonical_name` | `entity_type` | Rows | AUM |
|---:|---|---|---:|---:|
| 12709 | Growth Fund | fund | 501 | $77.0B |
| 15611 | Mid Cap Value Fund | fund | 588 | $34.9B |
| 15609 | Equity Income Fund | fund | 624 | $33.8B |
| 12713 | Select Fund | fund | 296 | $30.7B |
| 12712 | Heritage Fund | fund | 452 | $30.2B |
| 14428 | Equity Index Portfolio | fund | 2,529 | $26.9B |
| 12714 | Small Cap Growth Fund | fund | 757 | $23.3B |
| 15614 | Small Cap Value Fund | fund | 562 | $22.8B |
| 20019 | S000066459 (raw series ID) | fund | 786 | $19.6B |
| 12715 | Large Cap Equity Fund | fund | 617 | $18.7B |
| 20015 | S000066454 (raw series ID) | fund | 3,863 | $15.3B |

These names are also generic (e.g. "Growth Fund", "Heritage Fund") — they look like they may be shared across families and merit a separate entity-cleanup pass.

---

## Phase 1B.3 — Wrong-shelf rollup

**Inconclusive at this resolution.** A naive Jaccard between `entities.canonical_name` (rollup target) and `fund_universe.family_name` flags 5,636,556 rows / $63.2T as wrong-shelf, but inspection of the top-AUM samples shows **all top hits are legitimate parent → subsidiary attributions**:

| Fund family (`fund_universe.family_name`) | Rolled up to | Verdict |
|---|---|---|
| Fidelity Concord Street Trust | FMR LLC | correct (FMR is Fidelity parent) |
| Growth Fund of America | Capital Group / American Funds | correct |
| SPDR S&P 500 ETF Trust | State Street Corp | correct |
| Washington Mutual Investors Fund | Capital Group / American Funds | correct |
| Investment Co of America | Capital Group / American Funds | correct |
| College Retirement Equities Fund | Nuveen / TIAA | correct |
| JPMorgan Trust II | J.P. Morgan Investment Management Inc. | correct |

Detection requires a parent-brand alias map (FMR ↔ Fidelity, Capital Group ↔ American Funds, State Street ↔ SPDR, etc.) which we do not have a clean source for in this read-only pass. **Recommendation:** defer wrong-shelf detection to a follow-up sub-phase that materializes a brand-alias dictionary from `entity_relationships` (`parent_brand`, `fund_sponsor`) and re-runs the Jaccard with brand-equivalence.

---

## Phase 1B.4 — Headline rollup-integrity number

Union of 1B.1 + 1B.2 (deduped at `row_id`):

> **305,808 rows / $1,289.8B (~$1.29T) of fund-side AUM has rollup-integrity issues.**
> **= 2.10% of fund universe by row count, 0.80% of fund AUM by dollars.**

Breakdown of the union:

| Component | Rows | AUM |
|---|---:|---:|
| `dm_rollup_entity_id` NULL | 84,363 | $418.5B |
| Rolls up to `entity_type='fund'` (not institution) | 221,445 | $871.3B |
| Rolls up to N/A-named entity | 0 | $0 |
| **Union (deduped)** | **305,808** | **$1,289.8B** |

1B.3 (wrong-shelf) is excluded from the headline because the current detection method has too high a false-positive rate; treat 1B.3 as **TBD pending a brand-alias map**.

---

## Phase 1.5.1 — Institution presence gap

**1,326 distinct `entity_id`s** receive fund rollups but have **zero `is_latest=TRUE` rows in `holdings_v2`** (institution layer). These institutions are invisible in any Admin Refresh view that joins the institution tier.

- Fund-side rows exposed: **7,390,242**
- Fund-side AUM exposed: **$30,119B (~$30.1T)**

Top 20 missing institutions by fund-side AUM exposure:

| `entity_id` | `canonical_name` | Fund rows | Fund AUM |
|---:|---|---:|---:|
| 18073 | J.P. Morgan Investment Management Inc. | 184,046 | $2,762.9B |
| 1 | Vanguard Group | 267,751 | $2,541.5B |
| 30 | PIMCO | 289,132 | $1,717.0B |
| 9904 | TEACHERS ADVISORS, LLC | 100,015 | $1,571.1B |
| 7586 | BlackRock Fund Advisors | 70,554 | $1,303.3B |
| 18983 | Jackson National Asset Management, LLC | 162,191 | $1,201.5B |
| 1355 | FRANKLIN ADVISERS INC | 125,090 | $1,184.3B |
| 17924 | T. Rowe Price Associates, Inc. | 66,552 | $1,105.5B |
| 9935 | Wellington Management Co LLP | 89,257 | $757.5B |
| 2400 | Fidelity Management & Research Co LLC | 160,020 | $714.6B |
| 3586 | BLACKROCK ADVISORS LLC | 213,206 | $645.1B |
| 19924 | Olive Street Investment Advisers LLC | 57,893 | $622.7B |
| 18177 | Brighthouse Investment Advisers, LLC | 114,169 | $581.8B |
| 2562 | Equitable Investment Management, LLC | 231,561 | $564.6B |
| 7 | Dimensional Fund Advisors | 167,803 | $510.8B |
| 18869 | Lincoln Financial Investments Corporation | 138,745 | $465.2B |
| 17970 | BlackRock Investment Management, LLC | 95,262 | $426.5B |
| 8501 | J.P. Morgan Private Investments Inc. | 32,452 | $424.2B |
| 11 | Fidelity / FMR | 73,539 | $415.3B |
| 8994 | MANULIFE FINANCIAL CORP | 111,223 | $395.7B |

**Interpretation:** Fund-tier entities point to *adviser/sub-adviser* entities (e.g. `Vanguard Group eid=1`, `J.P. Morgan Investment Management Inc. eid=18073`) that are not themselves 13F filers. The 13F-filer CIKs sit on different `entity_id`s. Admin Refresh institution view will silently drop these unless the institution tier is back-filled with a synthetic record per fund-rollup target, **or** the fund tier rollups are re-pointed at the matching 13F-filer entity. This is the **#1 blocker** for Admin Refresh institution-level coverage.

---

## Phase 1.5.2 — AUM plausibility

**1,439 of 1,707** (84%) institutions that receive any fund rollup have `fund_aum_at_inst > inst_13f_aum × 1.10` (or `inst_13f_aum = 0`). Most are explained by 1.5.1 (institution missing entirely from `holdings_v2`), but several have 13F presence yet still understate. Top 25 mismatches by absolute delta:

| `entity_id` | Name | Fund AUM | Inst 13F AUM | Δ | Ratio |
|---:|---|---:|---:|---:|---:|
| 4375 | VANGUARD GROUP INC | $38,729.8B | $25,323.0B | $13,406.8B | 1.53× |
| 10443 | FMR LLC | $20,456.6B | $7,224.1B | $13,232.5B | 2.83× |
| 12 | Capital Group / American Funds | $14,336.2B | $7,265.2B | $7,071.0B | 1.97× |
| 3616 | PRICE T ROWE ASSOCIATES INC /MD/ | $4,158.1B | $4.2B | $4,153.9B | **993×** |
| 18073 | J.P. Morgan Investment Management Inc. | $2,714.5B | $0 | $2,714.5B | n/a |
| 1 | Vanguard Group | $2,541.5B | $0 | $2,541.5B | n/a |
| 30 | PIMCO | $1,716.0B | $0 | $1,716.0B | n/a |
| 9904 | TEACHERS ADVISORS, LLC | $1,571.1B | $0 | $1,571.1B | n/a |
| 7586 | BlackRock Fund Advisors | $1,303.3B | $0 | $1,303.3B | n/a |
| 1355 | FRANKLIN ADVISERS INC | $1,162.8B | $0 | $1,162.8B | n/a |
| 17924 | T. Rowe Price Associates, Inc. | $1,105.5B | $0 | $1,105.5B | n/a |
| 17 | MFS Investment Management | $2,346.4B | $1,248.8B | $1,097.6B | 1.88× |
| 5026 | DIMENSIONAL FUND ADVISORS LP | $2,643.2B | $1,777.0B | $866.3B | 1.49× |
| 9935 | Wellington Management Co LLP | $757.5B | $0 | $757.5B | n/a |
| 2400 | Fidelity Management & Research Co LLC | $714.6B | $0 | $714.6B | n/a |
| 9130 | VICTORY CAPITAL MANAGEMENT INC | $698.7B | $0 | $698.7B | n/a |
| 3586 | BLACKROCK ADVISORS LLC | $645.1B | $0 | $645.1B | n/a |
| 7 | Dimensional Fund Advisors | $510.8B | $0 | $510.8B | n/a |
| 15 | Dodge & Cox | $1,203.6B | $724.0B | $479.6B | 1.66× |
| 8497 | ALLIANCEBERNSTEIN L.P. | $473.5B | $0 | $473.5B | n/a |
| 17970 | BlackRock Investment Management, LLC | $426.5B | $0 | $426.5B | n/a |
| 11 | Fidelity / FMR | $415.3B | $0 | $415.3B | n/a |
| 17956 | Pzena Investment Management, LLC | $480.1B | $123.7B | $356.4B | 3.88× |
| 2322 | PACIFIC INVESTMENT MANAGEMENT CO LLC | $327.2B | $0 | $327.2B | n/a |
| 18062 | GQG Partners LLC | $325.9B | $0 | $325.9B | n/a |

**Top mismatch (institution with 13F presence): VANGUARD GROUP INC eid=4375, fund-side $38.7T vs institution-side $25.3T, Δ=$13.4T (1.53× over).** This is impossible if fund holdings are a subset of institution holdings — the most likely explanation is that fund holdings are being attributed to a brand-level entity (Vanguard Group Inc) while institution-level 13F is filed under a different but related entity. T. Rowe Price `eid=3616` showing 993× is the most extreme — fund tier shows $4.2T, institution tier shows $4.2B; clearly a fragmented mapping.

---

## Phase 1.5.3 — Merged / superseded entities (deprecated rollups)

`entity_relationships` does not carry `alias_of`/`merged_into`/`superseded_by` types in this DB (only `mutual_structure`, `wholly_owned`, `parent_brand`, `fund_sponsor`, `sub_adviser`). Fallback: any entity whose **all** rows in `entity_classification_history` have `valid_to < CURRENT_DATE` (none open via the 9999-12-31 sentinel) is treated as deprecated.

- **19 deprecated entities** receive fund rollups (`is_latest=TRUE`)
- **71,715 rows / $68.7B exposed**

| `entity_id` | `canonical_name` | `last_valid_to` | Rows | AUM |
|---:|---|---|---:|---:|
| 18096 | Dimensional Fund Advisors LP | 2026-04-17 | 54,203 | $52.3B |
| 17999 | BlackRock Advisors, LLC | 2026-04-12 | 3,694 | $7.8B |
| 17917 | AllianceBernstein L.P. | 2026-04-12 | 3,779 | $2.0B |
| 19801 | Muhlenkamp and Company Inc. | 2026-04-12 | 128 | $1.7B |
| 18325 | BlackRock Fund Advisors | 2026-04-12 | 390 | $1.0B |
| 19596 | Morningstar Investment Management LLC | 2026-04-17 | 494 | $1.0B |
| 18087 | Victory Capital Management Inc | 2026-04-12 | 923 | $0.8B |
| 18033 | Calvert Research and Management | 2026-04-12 | 185 | $0.7B |
| 18691 | UBS Asset Management (Americas) LLC | 2026-04-12 | 260 | $0.3B |
| 18963 | Baring International Investment Limited | 2026-04-12 | 491 | $0.3B |
| 18031 | BlackRock (Singapore) Limited | 2026-04-12 | 549 | $0.2B |
| 17973 | Loomis, Sayles & Company, L.P. | 2026-04-11 | 5,859 | $0.2B |
| 19594 | Oaktree Capital Management, L.P. | 2026-04-12 | 127 | $0.1B |
| 18354 | HSBC Global Asset Management (USA) Inc. | 2026-04-12 | 90 | $0.1B |
| 18149 | RBC Global Asset Management (uk) Limited | 2026-04-12 | 218 | $0.06B |
| 18636 | JOHCM (USA) Inc. | 2026-04-12 | 118 | $0.06B |
| 17958 | Hartford Funds Management Company, LLC | 2026-04-12 | 122 | $0.03B |
| 19853 | Dakota Wealth, LLC. | 2026-04-12 | 7 | $0.02B |
| 19528 | Robinson Capital Management, LLC | 2026-04-12 | 78 | $0.01B |

These are all merged/superseded entities (closed in mid-April 2026 — likely from the Apr 11–12 entity-merge marathon per project memory) whose successor entity_ids are receiving the institution-tier rows but whose fund-tier rollups still point at the closed predecessor. Replacement mapping is not stored in `entity_relationships` directly; would need to be derived from `entity_rollup_history` valid_from windowing (out of scope for read-only Phase 1B/1.5 — flagged for synthesis).

---

## Open questions

1. **Cross-tier entity-id alignment.** Why do major asset managers (Vanguard, FMR, J.P. Morgan, PIMCO, T. Rowe) appear under different `entity_id`s on the fund tier vs the institution tier? Is this intentional (brand entity vs. 13F-filer entity), or a join that's never been built? This is the gating question for Admin Refresh institution coverage.
2. **fund_holdings_v2 entity_type='fund' rollups (221k rows / $871B).** Is rolling a fund up to another fund ever correct (e.g. fund-of-funds), or is this universally a misclassification?
3. **Deprecated-rollup successor mapping.** Is there a canonical place to look up "entity X was merged into entity Y" beyond walking `entity_rollup_history` valid_from windows? `entity_relationships` does not carry merge edges.
4. **Wrong-shelf detection.** What's the right reference source for "this fund_cik should roll up to institution X"? Candidates: `entity_relationships(parent_brand|fund_sponsor)`, `fund_universe.family_name` joined to a brand-alias map, or a curated golden table.
5. **84K NULL-rollup rows.** Are these in-flight (haven't been resolved yet) or terminal (no candidate institution exists)? Sample CIKs are mostly bond/tax-exempt funds — possibly a strategy-class gap in the resolver.
