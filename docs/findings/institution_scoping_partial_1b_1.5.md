# Institution Scoping — Partial Findings (Phases 1B + 1.5)

Date: 2026-05-02
Scope: Read-only audit of fund-to-institution rollup integrity (1B) and cross-tier
consistency between fund_holdings_v2 and holdings_v2 (1.5).
DB: `data/13f.duckdb` (read_only=True)
Helpers (worktree-absolute):
- `scripts/oneoff/institution_scoping_phase1b_orphans.py`
- `scripts/oneoff/institution_scoping_phase1b_dangling.py`
- `scripts/oneoff/institution_scoping_phase1b_wrong_shelf.py`
- `scripts/oneoff/institution_scoping_phase15_crosstier.py`

Baseline universe: `fund_holdings_v2` `is_latest=TRUE` → 14,565,870 rows / $161,590.47B fund-side market_value_usd.

---

## Headline (1B.4): rollup integrity 99.42% rows / 99.74% AUM

Deduped union of (orphan rows + dangling-rollup rows + sponsor-shelf-mismatch rows):

| Failure mode | rows | AUM (fund-side market_value_usd) |
|--|--|--|
| Orphan (any of entity_id / rollup_entity_id / dm_entity_id / dm_rollup_entity_id IS NULL) | 84,363 | $418.55B |
| Dangling rollup (target = N/A or null/mixed/unknown entity_type) | 0 | $0.00B |
| Sponsor-shelf-mismatch (SYN_<cik> registered manager name diverges from rollup) | 110 | $3.72B |
| **Union, deduped** | **84,473** | **$422.27B** |
| % of universe | **0.580%** | **0.261%** |
| **Integrity** | **99.420%** | **99.739%** |

Net: rollup integrity on the fund tier is in good shape. The dangling-rollup mode (the
PR #251 / Calamos / ASA shape) is **fully resolved post-merge** — zero residual rows in
`fund_holdings_v2 is_latest=TRUE`. The remaining 0.6% is a single class of missing-id
"orphan" funds (see 1B.1).

The cross-tier (Phase 1.5) gap is much larger and not captured in the 1B headline.

---

## 1B.1 Orphan funds

All four ID columns share the **same** 84,363-row NULL set (i.e. when one is NULL, all are).
"NOT in entities" returns zero — every non-null ID resolves cleanly.

| Column | NULL rows | NULL AUM | Not in entities |
|--|--|--|--|
| entity_id | 84,363 | $418.55B | 0 / $0 |
| rollup_entity_id | 84,363 | $418.55B | 0 / $0 |
| dm_entity_id | 84,363 | $418.55B | 0 / $0 |
| dm_rollup_entity_id | 84,363 | $418.55B | 0 / $0 |

Top 10 orphan fund groups (rows × AUM, biggest first):

| fund_cik | fund_name | series_id | rows | aum |
|--|--|--|--|--|
| 0000013075 | Bond Fund of America | S000009231 | 5,801 | $101.15B |
| 0000050142 | Tax Exempt Bond Fund of America | S000009238 | 10,606 | $48.16B |
| 0000826813 | Intermediate Bond Fund of America | S000009236 | 2,849 | $28.54B |
| 0000925950 | American High-Income Municipal Bond Fund | S000009229 | 7,418 | $26.59B |
| 0001475712 | Global Opportunities Portfolio | S000027417 | 2,964 | $24.59B |
| 0000909427 | Limited Term Tax Exempt Bond Fund of America | S000009237 | 3,843 | $11.89B |
| 0001493214 | Global Macro Absolute Return Advantage Portfolio | S000029761 | 2,484 | $11.64B |
| 0000812303 | Capital World Bond Fund | S000009240 | 2,574 | $9.86B |
| 0000883676 | AB GLOBAL BOND FUND, INC. | S000010128 | 1,788 | $7.41B |
| 0001078195 | CCM Community Impact Bond Fund | S000001913 | 2,574 | $3.84B |

Pattern: heavily skewed toward fixed-income / multi-asset funds (Capital Group "American"
fixed-income family, AB Global Bond, Eaton Vance Global Macro). Hypothesis worth flagging
to other agents: these are funds the entity-resolution pipeline never assigned an entity_id
to — likely an issue in the family/sponsor matcher for fixed-income shelves.

`fund_universe`: 13,924 rows; 6 rows (TNA = $0) have no `is_latest=TRUE` match in
`fund_holdings_v2`. 664 rows have NULL `total_net_assets`.

## 1B.2 Dangling rollup ("Calamos shape")

**Zero rows** in `fund_holdings_v2 is_latest=TRUE` whose `dm_rollup_entity_id` resolves to
an entity with `canonical_name = 'N/A'` or `entity_type` in `('n/a','mixed','unknown',NULL)`.

Specifically: zero rows now reference `entity_id=11278` (the literal "N/A" entity) on
either `entity_id` or `dm_rollup_entity_id`. PR #251 + the upstream Calamos cleanup have
fully eliminated this failure mode.

## 1B.3 Wrong-shelf rollup

Comparison: SYN_<cik> series in `fund_holdings_v2 is_latest=TRUE`. Two flavours:

(a) **Loose name-mismatch** (informational): fund_name vs rollup_name token-similarity < 0.4.
22 groups flagged. **All inspected look correct** (e.g. "SPDR S&P 500 ETF TRUST" rolls up to
"STATE STREET CORP" — fund vs sponsor names always differ). Use case: prove the heuristic is
too noisy to be a defect signal on its own.

(b) **Sponsor-shelf-mismatch** (the actual ASA shape): `fund_cik` is itself a registered 13F
filer in `managers`, AND `managers.manager_name` token-sim < 0.4 vs `dm_rollup_name`, AND the
entity_id linked to that CIK ≠ `dm_rollup_entity_id`. Only **1 group, 110 rows, $3.72B**:

| series_id | cik | manager_name | rollup_name | sim | rows | aum |
|--|--|--|--|--|--|--|
| SYN_0002044519 | 0002044519 | Coatue Innovative Strategies Fund | Coatue Management | 0.35 | 110 | $3.72B |

This single case looks borderline-correct (the fund vehicle's CIK is registered as a manager,
but the brand-level rollup is the parent firm "Coatue Management"). Probably not a defect.

Net: **post-ASA, residual wrong-shelf is essentially zero.**

---

## 1.5 Cross-tier consistency — the actual gap

`fund_holdings_v2 is_latest=TRUE` rolls up to **1,707 distinct dm_rollup_entity_id values**.
`holdings_v2 is_latest=TRUE` covers **9,121 distinct entity_id values** (institution side).

### 1.5.1 Invisible institutions — **1,225 institutions / $27,797.71B fund AUM**

Receiving institutions (distinct `dm_rollup_entity_id` from fund-side) with **zero** match
in `holdings_v2` against `entity_id`, `rollup_entity_id`, *or* `dm_rollup_entity_id`:
- count: **1,225**
- fund-side AUM: **$27,797.71B** (~17% of fund-tier baseline AUM)

This is the headline cross-tier defect. These institutions appear as fund rollup targets
but will be **invisible in any institution-level Admin Refresh / dashboard view**.

Of the 1,339 invisible eids in the joint set, only **113 are resolvable** via at least one
child entity in `entity_relationships` that does appear in holdings_v2; the remaining **1,226
are genuinely orphan** in the cross-tier mapping.

Top 25 invisible institutions by fund AUM:

| eid | name | rows | fund_aum |
|--|--|--|--|
| 18073 | VOYA INVESTMENTS, LLC | 183,559 | $2,714.53B |
| 1 | Vanguard Group | 267,751 | $2,541.53B |
| 30 | PIMCO | 289,040 | $1,716.00B |
| 9904 | TEACHERS ADVISORS, LLC | 100,015 | $1,571.05B |
| 7586 | TRANSAMERICA CORP | 70,554 | $1,303.29B |
| 1355 | Venerable Investment Advisers, LLC | 92,179 | $1,162.81B |
| 17924 | VOYA INVESTMENTS, LLC | 66,552 | $1,105.54B |
| 9935 | Wellington Management Co LLP | 89,257 | $757.51B |
| 2400 | Fidelity Management & Research Co LLC | 160,020 | $714.59B |
| 3586 | NORTHWESTERN MUTUAL LIFE INSURANCE CO | 213,206 | $645.07B |
| 7 | Dimensional Fund Advisors | 167,803 | $510.78B |
| 17970 | Transamerica Asset Management, Inc. | 95,262 | $426.48B |
| 11 | Fidelity / FMR | 73,539 | $415.27B |
| 2322 | UBS AM, a distinct business unit of UBS ASSET MANAGEMENT AMERICAS LLC | 34,561 | $327.20B |
| 18062 | UBS AM (same brand, different eid) | 1,813 | $325.91B |
| 3050 | WisdomTree Digital Management, Inc. | 59,835 | $319.03B |
| 3 | State Street / SSGA | 60,157 | $301.90B |
| 18983 | Jackson National Asset Management, LLC | 57,650 | $300.79B |
| 17930 | Federated Advisory Services Company | 28,716 | $275.34B |
| 77 | PGIM | 37,321 | $269.40B |
| 8994 | Mercer Investments LLC | 89,362 | $265.71B |
| 19555 | WisdomTree Asset Management, Inc. | 93,317 | $262.24B |
| 10538 | Mercer Investments LLC | 24,328 | $257.96B |
| 8 | First Trust | 24,098 | $232.68B |
| 2232 | The Variable Annuity Life Insurance Company | 89,117 | $222.17B |

Diagnosis (verified for Vanguard + PIMCO):
- `eid=1` is the canonical "Vanguard Group" institution entity. Holdings_v2 stores Vanguard
  filings under `eid=4375` ("Vanguard Group Inc" — the registered 13F filer CIK).
- `eid=30` is the canonical "PIMCO" institution. Holdings_v2 has zero rows for eid=30; PIMCO's
  13F filings are coded under a separate filer-CIK eid.
- Several brands appear at multiple eids (UBS AM at 2322 and 18062, Voya at 18073 and 17924,
  Mercer at 8994 and 10538, WisdomTree at 3050 and 19555, etc.) — duplicate canonical entities
  per institution, both used as fund rollup targets, neither lining up with holdings_v2's
  filer-CIK eid.

This is a fundamental mapping defect: **fund-tier rolls up to "brand" eids, institution-tier
keys off "filer-CIK" eids, and the bridge is broken/incomplete.** It is the dominant
cross-tier integrity issue in the database.

### 1.5.2 AUM plausibility — 130 implausible institutions

Join key chosen: `holdings_v2.dm_rollup_entity_id` (matches 436 of 1,707 — best of the three).
- 1,271 of the 1,707 fund-rollup-target institutions had no match in `holdings_v2.dm_rollup_entity_id`
  at all (overlaps with 1.5.1 invisibles).
- Of the 436 that did match: **130 are implausible** (`fund_aum > 1.5x institution_aum`).
- Soft flag (`fund_aum > institution_aum` at all): **183 institutions**.

Top 25 mismatches by absolute delta:

| eid | name | fund_aum | inst_aum | delta | ratio |
|--|--|--|--|--|--|
| 4375 | Vanguard Group | $38,729.80B | $25,322.97B | $13,406.82B | 1.53x |
| 10443 | Real Estate Portfolio | $20,456.60B | $7,224.11B | $13,232.49B | 2.83x |
| 12 | Capital Group / American Funds | $14,336.20B | $7,265.22B | $7,070.97B | 1.97x |
| 3616 | T. Rowe Price | $4,158.07B | $4.19B | $4,153.88B | 992.83x |
| 17 | MFS Investment Management | $2,346.37B | $1,248.81B | $1,097.56B | 1.88x |
| 15 | Dodge & Cox | $1,203.61B | $724.02B | $479.59B | 1.66x |
| 17956 | U.S. Small Cap Equity Fund | $480.14B | $123.74B | $356.40B | 3.88x |
| 893 | LORD, ABBETT & CO. LLC | $283.90B | $0.13B | $283.78B | 2,265.07x |
| 901 | First Eagle Investment Management, LLC | $462.54B | $210.61B | $251.93B | 2.20x |
| 5022 | ProShare Advisors LLC | $368.92B | $210.31B | $158.62B | 1.75x |
| 18051 | Nationwide Fund Advisors | $164.79B | $7.11B | $157.68B | 23.19x |
| 4636 | Western Asset Management Company, LLC | $145.50B | $0.17B | $145.33B | 859.74x |
| 1699 | Thrivent Financial for Lutherans | $142.57B | $0.18B | $142.39B | 786.11x |
| 6314 | Jackson National Asset Management, LLC | $131.65B | $0.05B | $131.60B | 2,460.38x |
| 6829 | Rafferty Asset Management, LLC | $244.33B | $113.55B | $130.79B | 2.15x |
| 18814 | SEI INVESTMENTS MANAGEMENT CORP | $141.86B | $25.94B | $115.92B | 5.47x |
| 8646 | Vident Advisory, LLC | $147.68B | $37.20B | $110.48B | 110.48x |
| 7864 | Cliffwater LLC | $99.29B | $1.82B | $97.47B | 54.56x |
| 8876 | MAIRS & POWER INC | $121.50B | $40.77B | $80.73B | 2.98x |
| 5099 | MUTUAL OF AMERICA LIFE INSURANCE CO | $109.64B | $36.96B | $72.68B | 2.97x |
| 70 | Ariel Investments | $102.90B | $35.94B | $66.96B | 2.86x |
| 4367 | Sterling Capital Management LLC | $92.54B | $26.47B | $66.07B | 3.50x |
| 4342 | Innovator Capital Management, LLC | $60.86B | $0.02B | $60.84B | 3,150.85x |
| 564 | NORTHWESTERN MUTUAL LIFE INSURANCE CO | $62.05B | $3.62B | $58.43B | 17.13x |
| 2925 | THORNBURG INVESTMENT MANAGEMENT INC | $152.41B | $94.91B | $57.50B | 1.61x |

Caveats:
- Fund-side AUM is summed across all `is_latest=TRUE` periods/holdings rows, not a single
  point-in-time snapshot. Some of the "fund_aum > inst_aum" gap may be stacked-quarter
  duplication if `is_latest=TRUE` covers multiple periods.
- Institution-side `holdings_v2.market_value_usd` is single-period 13F. So the ratios
  here are noisy. But ratios > 100x (T. Rowe Price 992x, Lord Abbett 2265x, Western Asset 860x,
  Innovator 3150x, Jackson 2460x) cannot be explained by stacking — they confirm the same
  cross-tier eid-mismatch as 1.5.1.

### 1.5.3 Deprecated / superseded receiving institutions

**Closed in `entity_classification_history`** (latest row valid_to ≠ 9999-12-31): **19
receiving targets, $68.69B fund AUM**.

| eid | valid_to | name | rows | fund_aum |
|--|--|--|--|--|
| 18096 | 2026-04-17 | Symmetry Partners, LLC | 54,203 | $52.29B |
| 17999 | 2026-04-12 | BlackRock Advisors, LLC | 3,694 | $7.77B |
| 17917 | 2026-04-12 | AllianceBernstein L.P. | 3,779 | $2.03B |
| 19801 | 2026-04-12 | Muhlenkamp and Company Inc. | 128 | $1.67B |
| 18325 | 2026-04-12 | BlackRock Fund Advisors | 390 | $1.04B |
| 19596 | 2026-04-17 | Universal Financial Services, Inc. | 494 | $1.03B |
| 18087 | 2026-04-12 | Victory Capital Management Inc | 923 | $0.77B |
| 18033 | 2026-04-12 | Calvert Research and Management | 185 | $0.65B |
| 18691 | 2026-04-12 | UBS Asset Management (Americas) LLC | 260 | $0.34B |
| 18963 | 2026-04-12 | Baring International Investment Limited | 491 | $0.31B |
| 18031 | 2026-04-12 | BlackRock (Singapore) Limited | 549 | $0.23B |
| 17973 | 2026-04-11 | Loomis, Sayles & Company, L.P. | 5,859 | $0.17B |
| 19594 | 2026-04-12 | Oaktree Capital Management, L.P. | 127 | $0.12B |
| 18354 | 2026-04-12 | HSBC Global Asset Management (USA) Inc. | 90 | $0.10B |
| 18149 | 2026-04-12 | RBC Global Asset Management (uk) Limited | 218 | $0.06B |
| 18636 | 2026-04-12 | JOHCM (USA) Inc. | 118 | $0.06B |
| 17958 | 2026-04-12 | Hartford Funds Management Company, LLC | 122 | $0.03B |
| 19853 | 2026-04-12 | Dakota Wealth, LLC. | 7 | $0.02B |
| 19528 | 2026-04-12 | Robinson Capital Management, LLC | 78 | $0.01B |

These eids have a closed classification row but `dm_rollup_entity_id` still points at them
in `fund_holdings_v2 is_latest=TRUE` — i.e. fund-side rollup mapping was not updated when
the entity was closed/merged.

**Superseded via `entity_relationships`** (closed parent/child rel): **109 receiving
targets**. Top examples (fund AUM):
- eid=9904 TEACHERS ADVISORS, LLC → wholly_owned by 9554 (closed 2026-04-27) — $1,571.05B
- eid=7586 TRANSAMERICA CORP → wholly_owned by 3241 (closed 2026-04-26) — $1,303.29B
- eid=1589 PGIM, Inc. → wholly_owned by 10914 (closed 2026-04-27) — $772.92B
- eid=2400 Fidelity Management & Research Co LLC → wholly_owned by 10443 (closed 2026-04-27) — $714.59B
- eid=3586 NORTHWESTERN MUTUAL LIFE INSURANCE CO → wholly_owned by 18699 (closed 2026-04-12) — $645.07B
- eid=8497 The Variable Annuity Life Insurance Company → fund_sponsor by 57 (closed 2026-04-08) — $473.48B

These are recent (last few weeks) supersessions. Fund-side rollups have not been refreshed
to follow the new parents.

---

## Open questions

1. **Cross-tier eid duplication is the dominant integrity defect, not 1B.** The 1B headline
   (99.7% AUM integrity) is good news but it's measured in a single tier. Phase 1.5 reveals
   that ~17% of fund AUM ($27.8T) rolls up to brand-level institution eids that have no
   parallel in holdings_v2 (institution-tier 13F). Recommend the consolidated investigation
   call this out as the headline finding rather than 1B.

2. **Why do the canonical institution eids (eid=1 Vanguard, eid=3 SSGA, eid=7 DFA, eid=8
   First Trust, eid=11 Fidelity, eid=12 Capital Group, eid=30 PIMCO, eid=77 PGIM, etc.)
   not also serve as the holdings_v2 keys?** These look like a separate "brand" naming layer
   (low-numbered eids) that was never bidirectionally bridged to the filer-CIK eids
   (high-numbered: 4375 Vanguard, etc.). If the canonical layer is the intended source of
   truth, holdings_v2 needs a remap; if the filer-CIK layer is the source of truth,
   fund_holdings_v2 dm_rollup mapping needs a remap. Either way, ~17% of fund AUM is
   currently un-joinable across tiers without a manual bridge.

3. **The 19 deprecated receiving targets ($68.69B) are a bug.** Closing an entity in
   `entity_classification_history` should propagate to fund_holdings_v2 dm_rollup updates
   (or vice-versa). These are easy fixes once a backfill loader is wired up.

4. **84,363 NULL-id orphan rows ($418.55B)** are concentrated in fixed-income / multi-asset
   fund families (Capital Group "American" bond funds, Eaton Vance global macro, AB Global
   Bond, Voya, CCM impact). Hypothesis: the entity-resolution path that assigns
   `entity_id`/`dm_rollup_entity_id` skips funds with non-standard family naming or shelf
   structure. Worth a separate scoping ticket if not already in scope of 1A/2/3.

5. **Should we run with `is_latest=TRUE` or single-period?** `is_latest=TRUE` includes
   multiple historical periods that are still flagged latest under multi-quarter coverage —
   the 14.5M baseline and the $161T AUM are partially stacked. If the consolidated
   institution scoping wants per-period numbers, re-run with a `report_date` filter.
