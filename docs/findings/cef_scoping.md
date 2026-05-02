# cef-scoping — Closed-End Fund Attribution Decision Doc

**Date:** 2026-05-02
**Branch:** `cef-scoping`
**Scope:** Read-only investigation answering the five scoping questions in [ROADMAP.md `cef-attribution-path`](../../ROADMAP.md#cef-attribution-path). No DB writes, no production module changes.
**Per-phase detail:** [phase_1](../../data/working/cef_scoping/phase_1_findings.md) · [phase_2](../../data/working/cef_scoping/phase_2_findings.md) · [phase_4](../../data/working/cef_scoping/phase_4_findings.md) · [phase_5](../../data/working/cef_scoping/phase_5_findings.md)

---

## Executive Summary

**The original 5-PR `cef-attribution-path` workstream is dramatically descoped.** Two facts reframe everything:

1. **CEFs DO file N-PORT.** Rule 30b1-9 covers all registered management investment companies. The SEC explicitly rejected a CEF carve-out in the 2016 Reporting Modernization release. The original ROADMAP framing ("CEFs file NSAR / N-CSR not N-PORT") was wrong — and NSAR was an operational/census form, not a holdings form, so the NSAR mention is doubly incorrect.
2. **The existing SYN_ namespace already handles 436 CEFs / $625.94B correctly** via `load_13f_v2.py`. The 446-row UNKNOWN residual is **not** an architecture gap; it's stale data from the retired Apr-3 loader (`scripts/retired/fetch_nport.py`, the only literal-`UNKNOWN` write site in the entire repo).

| Question | Original framing | Actual finding |
|---|---|---|
| Q1: full CEF inventory | unknown | **757 N-2 filers since 2020; 458 active N-CSR core; Tier B (already loaded fine via SYN_): 436 / $625.94B; Tier A (UNKNOWN-bearing): exactly the 2 known seeds, no others** |
| Q2: by design or by accident | unknown | **Legacy-loader residue. Active loaders never write `series_id='UNKNOWN'`. v2 path is correct architecture.** |
| Q3: canonical CEF identifier | CIK / `CEF_<cik>` / separate table | **Moot. SYN_<cik> namespace already in use across 436 CEFs. No new namespace needed.** |
| Q4: schema fit (NSAR/N-CSR vs N-PORT) | major schema delta | **`fund_universe` and `fund_holdings_v2` are fully reusable for CEFs from N-PORT. Zero schema changes required.** |
| Q5: holdings parsing pre-2020 | PDF/OCR risk | **Skip — net new modern data = 0; historical depth has weak ROI; ~3–5 weeks effort if ever pursued.** |

**Workstream collapse:**

- ❌ DROP: PR-2 `cef-fetch-pipeline`, PR-3 `cef-parser`, PR-5 display integration
- ✅ KEEP (rescoped): PR-4 → split into 2 small cleanup PRs, see [§ 7](#7-sequenced-pr-plan-rescoped)

**Total estimated effort for the rescoped follow-on arc: ~1–2 sessions (S+S), not 4–6 weeks.**

---

## 1. Phase 1 — Full CEF Inventory

**Universe:** 757 unique CIKs filed Form N-2 / N-2/A since 2020-01-01. 458 (60.5%) also have N-CSR/N-CSRS in the same window (active operating core). Universe size is within the spec window of ~500–800. Validation spot-check: 5/5 sampled CIKs verified as bona fide CEF / interval-fund registrants (PGIM PRE Fund, India Fund IFN, Felicitas, Angel Oak DYFN, DoubleLine DSL).

**Cross-reference vs `fund_holdings_v2 is_latest=TRUE`:**

| Tier | Definition | n CIKs | Rows | AUM |
|---|---|---:|---:|---:|
| **A** | UNKNOWN-bearing | **2** (direct prod query; absent from N-2 universe — see ⚠ below) | 446 | $4.741B |
| **B** | SYN_-only (no UNKNOWN) | **436** | 815,183 | **$625.94B** |
| **C** | Canonical series_id only | **0** | 0 | $0 |
| **D** | In universe, not in `fund_holdings_v2` | 321 | 0 | $0 |

⚠ **Tier A gap reason:** Both UNKNOWN-bearing CIKs (Adams ADX since 1929, ASA Gold since 1958) registered pre-2020 and have not amended via N-2/A in our window. The N-2 universe captures registrants but misses old CEFs that are still active under their original registration. A defensive guard against future migration-residue would monitor "any `is_latest=TRUE` row with `BACKFILL_MIG015_UNKNOWN_*` accession" — zero rows is the green target.

**Tier A subtable:**

| fund_cik | fund_name | unknown_rows | unknown_AUM | mig015_UNKNOWN prefix | has_SYN_companion |
|---|---|---:|---:|---:|---|
| 0000002230 | Adams Diversified Equity Fund (ADX) | 96 | $2.989B | 96 (100%) | **YES** (291 rows / $8.826B) |
| 0001230869 | ASA Gold & Precious Metals Ltd | 350 | $1.752B | 350 (100%) | **YES** (143 rows / $1.094B) |
| **TOTAL** | | **446** | **$4.741B** | **446 (100%)** | |

Output files: [`data/working/cef_scoping/cef_universe.csv`](../../data/working/cef_scoping/cef_universe.csv) (757 rows), [`tier_a_cohort.csv`](../../data/working/cef_scoping/tier_a_cohort.csv), [`tiers_summary.csv`](../../data/working/cef_scoping/tiers_summary.csv).

---

## 2. Phase 2 — Load-Path Trace

**Verdict: MIXED, lean BY_DESIGN. Confidence: HIGH.**

### Loader-of-origin

| Bucket | Source | Evidence |
|---|---|---|
| UNKNOWN (446) | [`scripts/retired/fetch_nport.py`](../../scripts/retired/fetch_nport.py) lines 311/367/484: `series_id = metadata.get("series_id") or "UNKNOWN"` | **Single literal-`UNKNOWN` write site in the entire repo.** Legacy loader, retired. `loaded_at` clusters Apr 3. |
| SYN_ (434) | `scripts/load_13f_v2.py` (Apr 15 v2 cutover) + `scripts/oneoff/dera_synthetic_stabilize.py` Tier 3 | `loaded_at` clusters Apr 15 06:04–06:21. Aligns with memory `project_session_apr15_dera_promote.md` (`e868772`). |

Migration 015 only stamped synthetic accessions onto pre-existing rows; it did **not** write the rows. The current pipeline (`scripts/pipeline/load_nport.py:619`) emits `{cik}_{accession}` synthetic series_ids — never literal `'UNKNOWN'`. **Zero hits** for `'UNKNOWN'` series_id writes in any active loader script.

### SEC form-type lookup (Phase 4 hypothesis check)

| CIK | Accession | Form | Filed | Period |
|---|---|---|---|---|
| ADX | 0001104659-25-124101 | NPORT-P/A | 2025-12-23 | 2025-06-30 |
| ADX | 0001104659-25-124108 | NPORT-P/A | 2025-12-23 | 2025-09-30 |
| ADX | 0001104659-26-019620 | NPORT-P | 2026-02-25 | 2025-12-31 |
| ASA | 0001049169-26-000039 | NPORT-P | 2026-01-27 | 2025-11-30 |

All four real EDGAR accessions are N-PORT. Confirms: CEFs file N-PORT.

### Per-CIK reality

- **ADX 2025-09:** 96 UNKNOWN rows are **byte-identical duplicates** of 96 SYN_ rows (same accession family, same CUSIPs, same shares/MV). Pure dedup case — drop the UNKNOWN side.
- **ASA 2024-11 / 2025-02 / 2025-08:** UNKNOWN rows have **NO SYN_ companion**. Dropping without a parallel v2 backfill loses three filing periods. Real fix requires re-running v2 loader against older periods.

### Spot-check (BY_DESIGN side)

ADX (CUSIP `006212104`) and ASA (CUSIP `G3156P103`) both appear as 13F portfolio positions held by other managers, attributed to the **holder's** manager_id (Saba Capital, Morgan Stanley, etc.). ADX itself files its own 13F-HR ($11.3B). Third-party 13F attribution is working correctly — independent of the N-PORT data path.

### Database-wide blast radius

The literal-`UNKNOWN` series_id pattern in `fund_holdings_v2` is **strictly limited to ADX (96) + ASA (350)**. No other Tier A CIK affected. The retired loader's CEF blast radius was 2 issuers — likely because those were the only CEFs queued in its input list at the time, not a systemic bug.

---

## 3. Phase 3 — Canonical CEF Series Identifier (Decision Matrix)

**Question moot — recommendation: `SYN_<cik>` (Option B, status quo).**

The original prompt asked us to weigh three options (Option A: CIK as canonical key; Option B: mint `CEF_<cik>` namespace; Option C: separate `cef_holdings` table). Phase 1's Tier B finding settles it: **the existing `SYN_<cik>` namespace already handles 436 CEFs across $625.94B AUM correctly** via `load_13f_v2.py` and `dera_synthetic_stabilize.py`. CEFs slot cleanly into the same namespace open-end funds use when EDGAR doesn't emit a real series_id.

| Option | Status | Notes |
|---|---|---|
| A — CIK as canonical | rejected | Would require a parallel attribution path. SYN_ namespace already provides clean fallback. |
| B — `CEF_<cik>` namespace | rejected | Same rationale as A — adds a third namespace where two suffice. SYN_<cik> is structure-agnostic; that's a feature. |
| **C — `SYN_<cik>` (existing namespace)** | **recommended (= status quo)** | Used by 436 of 438 CEFs in `fund_holdings_v2`. Zero schema change. Zero new query branches. Zero display-layer cost. |
| D — separate `cef_holdings` table | rejected | Highest migration cost, highest long-term clarity cost; UNION/duplicated logic across every cross-fund query. Not justified by 446-row residual. |

**fund_strategy taxonomy:** existing values fit CEFs without modification. Cross-reference [`fund-strategy-taxonomy-finalization`](../../ROADMAP.md) (open P2) for a CEF sample inclusion when that audit happens. **Do not** introduce CEF-specific strategy values (avoid balkanizing the taxonomy).

**`total_net_assets` source:** N-PORT Item B.1 NAV. Never market cap — CEFs trade at premium/discount, sometimes 10%+. (Optional P3 add: `nav_per_share` to `fund_universe` if any analytic depends on premium/discount.)

**Optional orthogonal column (P3, deferred):** `fund_structure` on `fund_universe` (`open_end` / `closed_end` / `etf` / `uit`) — separate dimension from `fund_strategy`. Out of scope for cef-scoping; surface only if a CEF-specific analytic emerges.

---

## 4. Phase 4 — Schema Fit Delta

### Filing cadence

| Form | Frequency | Disclosure lag | Applies to CEFs |
|---|---|---|---|
| **N-PORT** | Monthly file (3 reports/quarter) | 60 days quarter-end (third month public; months 1+2 non-public until 2024 amendments compliance: Nov 2027 large / May 2028 small) | **YES** (Rule 30b1-9) |
| N-CSR | Semiannual | ~70 days post period-end (60-day shareholder + 10-day filing) | YES (historical primary pre-2019; supplemental now) |
| N-CEN | Annual | 75 days post fiscal-year-end | YES (operational/census, not holdings) |
| NSAR-A / NSAR-B | RETIRED 2018-06-01 | n/a | **n/a — was operational/census, NOT holdings.** ROADMAP wording naming NSAR as a CEF holdings source is wrong. |

### Quarterly-aggregation impact

- **2019-Q3 onward (N-PORT era):** identical to open-end funds. Quarterly groupby on `report_date` works as-is. No carry-forward.
- **Pre-2019 (if N-CSR ever backfilled):** semiannual cadence → 2 points/year per CEF. Q1/Q3 empty unless flagged with `is_carryforward`.

### Field-level delta

`fund_universe` and `fund_holdings_v2` are **fully reusable for CEFs from N-PORT**. Zero new columns required. Two soft issues:
- `series_id` will frequently be null for CEFs — already handled by SYN_<cik> fallback.
- Pre-2019 N-CSR backfill (if pursued) would null `fair_value_level` / `is_restricted` / `payoff_profile` and tag `backfill_quality = 'ncsr_html'`.

### CEF-specific fields NOT captured (all P3 / deferred)

NAV per share, market price per share, premium/discount, leverage ratio, distribution rate, board composition, expense ratio detail. None blocking. Add on demand if analytics surface them.

---

## 5. Phase 5 — N-CSR Parser Feasibility

**Recommendation: D — Skip historical N-CSR backfill entirely.**

5/5 N-CSR samples fetched successfully across vintages (ADX 2026, ASA 2026, FT Private Assets 2025, Pioneer HI 2023, HISF 2019). Coverage matrix:

| CIK | Vintage | edgartools structured? | HTML-table parseable? | Effort |
|---|---|---|---|---|
| ADX | 2024+ | No (`obj()`=None) | Yes (~41 rows) | MEDIUM |
| ASA | 2024+ | Partial (XBRL cover only) | Yes (~59 rows) | MEDIUM |
| FT Private Assets | 2024+ | No | Yes (~42 rows) | MEDIUM |
| Pioneer HI | 2023 | Partial (XBRL cover only) | Yes, 304 tables noisy (~45 rows) | MEDIUM-HARD |
| HISF | 2019 | No | Yes (~51 rows) | MEDIUM |

**Tier breakdown:** TRIVIAL=0, MEDIUM=4, MEDIUM-HARD=1, HARD=0, UNPARSEABLE=0. Zero PDF/OCR exposure across the sample.

**Key empirical findings:**
- `edgartools` does **not** expose a `holdings()` accessor for N-CSR. `Filing.obj()` returns either `None` or an `XBRL` cover-page object — never a Schedule of Investments DataFrame.
- IXBRL wrapping (post-2024 tailored shareholder report rule) tags **financial statement** facts, not SoI line items. It does not help holdings extraction.
- All 5 samples have HTML SoI tables with reasonable row counts (~40–60). Custom BeautifulSoup + table classification scrape is feasible.

**Why D over B:**
1. Net new modern data = 0 (N-PORT covers 2019+ at monthly granularity, vs N-CSR semiannual).
2. Historical depth value is low for flow-analysis / conviction tabs (most use-cases run on 4–12 quarter lookbacks).
3. Effort is real: ~3–5 weeks one-time build (parser core + per-filer overrides + MDM reconciliation across 458 CEFs × ~20 filings each = ~9,160 filings).

**If ever authorized, fallback path:** B — edgartools + BeautifulSoup HTML-table classification. Path C (OCR) is not warranted based on the sample.

---

## 6. Schema-Fit Quick Reference (for Phase 4 cross-walk)

| Column | N-PORT source | Mappable for CEFs? |
|---|---|---|
| `fund_holdings_v2.series_id` | Item A.1 (often null for CEFs) | PARTIAL — SYN_<cik> fallback covers it |
| `fund_holdings_v2.cusip` / `issuer_name` / `shares_or_principal` / `market_value_usd` / `pct_of_nav` | Part C Items C.1 / C.5 / C.6 / C.7 | YES |
| `fund_holdings_v2.fair_value_level` / `is_restricted` / `payoff_profile` | Part C Items C.8 / C.9 / C.10 | YES post-2019; null pre-2019 |
| `fund_universe.total_net_assets` | Item B.1 (NAV) | YES — use NAV, not market cap |
| `fund_universe.fund_strategy` | external classifier | YES (existing taxonomy fits; revisit in `fund-strategy-taxonomy-finalization` audit) |

Full per-column mapping in [phase_4_findings.md § 3 + § 4](../../data/working/cef_scoping/phase_4_findings.md).

---

## 7. Sequenced PR Plan (Rescoped)

### Original 5-PR sequence vs actual

| Original | Status | Actual |
|---|---|---|
| PR-1 `cef-scoping` (this) | ✅ Delivered | (this PR) |
| PR-2 `cef-fetch-pipeline` (NSAR/N-CSR fetcher) | ❌ DROP | Existing N-PORT loader covers everything; no NSAR/N-CSR fetcher needed |
| PR-3 `cef-parser` | ❌ DROP | Phase 5 D recommendation |
| PR-4 `cef-holdings-load` | 🔄 RESCOPE | Splits into PR-2 + PR-3 below (small cleanup) |
| PR-5 `cross.py` + display integration | ❌ DROP | No schema change → no integration work; CEFs already render via SYN_ namespace |

### Rescoped follow-on arc (2 PRs + 1 optional)

#### PR-2 `cef-residual-cleanup-adx` — flip ADX 96 byte-identical duplicates

**Scope:** S
**Dependencies:** none
**Open decisions:** none

Mirror the BRANCH 1 operation from PR [#247](https://github.com/ST5555-Code/Institutional-Ownership/pull/247) (`cleanup_stale_unknown.py`). Flip `is_latest=FALSE` on the 96 ADX UNKNOWN rows (CIK 0000002230, accession `BACKFILL_MIG015_UNKNOWN_2025-09`). Their SYN_0000002230 companion already carries identical data ($2.989B / 96 holdings) for the same period. Pure dedup. Same safety gates as #247.

Net: 446 → 350 residual UNKNOWN rows; $4.741B → $1.752B exposure.

#### PR-3 `cef-asa-period-backfill` — extend SYN_ coverage + flip ASA 350

**Scope:** M
**Dependencies:** PR-2 merged (clean residual scope to ASA-only first)
**Open decisions:**
- Loader entry point: re-run `fetch_nport_v2.py` against ASA's three older periods (2024-11, 2025-02, 2025-08) directly, vs back-fill via the v2 promotion script as in `project_session_apr15_dera_promote.md` (`e868772`)? Both work; the direct approach is smaller-blast-radius.
- Should the same SCD flip helper from PR-2 / #247 be generalized into `scripts/oneoff/cleanup_stale_unknown.py` (already exists) with a `--cik 0001230869` arg, or a fresh oneoff?

Re-run v2 N-PORT loader against ASA periods 2024-11 / 2025-02 / 2025-08 to create SYN_0001230869 companion rows. Then SCD-flip the 350 UNKNOWN rows to `is_latest=FALSE`.

Net: 350 → 0 residual UNKNOWN rows; $1.752B → $0 exposure. Closes the cef-attribution-path workstream.

#### PR-4 (optional, P3) `retired-loader-residue-monitor`

**Scope:** XS
**Dependencies:** PR-3 merged
**Open decisions:** include in default gates vs run on-demand

Defensive watchpoint: assert zero `fund_holdings_v2` rows with `is_latest=TRUE AND accession_number LIKE 'BACKFILL_MIG015_UNKNOWN_%'`. Detects regression if the retired loader is ever re-armed accidentally. One-line gate addition. Optional — only worth doing if the existing CI gates don't already cover this shape.

### Total estimated effort

**~1–2 sessions** (S + M, sequential). Compare to original 5-PR ROADMAP estimate of 4–6 weeks.

---

## 8. Open Questions for Chat Decision

1. **Drop the 3 unused PRs from the ROADMAP entry?** `cef-fetch-pipeline`, `cef-parser`, display integration are no longer needed. Update the ROADMAP `cef-attribution-path` entry to reflect the rescoped 2-PR plan, and correct the NSAR-as-holdings-source wording to N-PORT-as-primary / N-CSR-as-supplemental.

2. **PR-2 / PR-3 sequence vs single combined PR?** Two PRs preserve the BRANCH 1 / BRANCH 2 pattern from #247 (clean test for each shape: dedup vs period-backfill). One combined PR is fewer cycles but mixes two shapes. Recommend two PRs for review clarity; happy to combine on request.

3. **Defensive monitor (PR-4) — yes or no?** Low-cost insurance against migration-residue regressions. The retired loader is unlikely to be re-armed, but the gate is one assertion. Default position: skip unless a similar incident makes it worth the addition.

4. **`fund_structure` orthogonal column (P3)?** Surface as a separate ROADMAP item, not part of cef-attribution-path. Trigger: first analytic that needs to filter by fund structure (CEF-only premium/discount, etc.).

5. **`nav_per_share` enrichment (P3)?** Same — defer until premium/discount analytic surfaces a need.

6. **Wording fix for ROADMAP NSAR mention.** Phase 4 confirmed NSAR was operational/census, not holdings. The cef-attribution-path entry says "CEFs report on NSAR-A / NSAR-B (semiannual) and N-CSR" — should be corrected to "CEFs report on N-PORT (monthly), with N-CSR semiannual shareholder reports as supplemental disclosure." Suggest folding into the close-out doc-sync after PR-3.

> **Resolution (2026-05-02 cef-roadmap-correction commit):** all open questions surfaced here landed as three new ROADMAP entries — [`cef-residual-cleanup`](../../ROADMAP.md#cef-residual-cleanup) (renamed from `cef-attribution-path`, rescoped to 2 cleanup PRs), [`retired-loader-residue-watchpoint`](../../ROADMAP.md#retired-loader-residue-watchpoint) (P3, defensive monitor for the literal-`UNKNOWN` write pattern), and [`fund-structure-column`](../../ROADMAP.md#fund-structure-column) (P2, orthogonal `fund_universe.fund_structure` enum).

---

## 9. Helper Scripts (read-only, verified zero writes)

- [`scripts/oneoff/cef_scoping_phase_1_1_universe.py`](../../scripts/oneoff/cef_scoping_phase_1_1_universe.py) — builds `cef_universe.csv` (757 rows)
- [`scripts/oneoff/cef_scoping_phase_1_2_crossref.py`](../../scripts/oneoff/cef_scoping_phase_1_2_crossref.py) — builds `tiers_summary.csv` and Tier A worksheet
- [`scripts/oneoff/cef_scoping_phase_5_ncsr_sample.py`](../../scripts/oneoff/cef_scoping_phase_5_ncsr_sample.py) — fetches 5 N-CSR samples, runs structured-extraction probe

Phase 2 (loader trace) and Phase 4 (schema fit) used direct grep + DB read + WebFetch only — no helper scripts needed.

All scripts pass: `grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b'` returns only false-positives (pandas `.drop()`, `.sort_values()`, comments).
