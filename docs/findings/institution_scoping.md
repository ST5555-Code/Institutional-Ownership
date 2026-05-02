# Institution-level scoping — decision document

Read-only investigation of the institution-level consolidation workstream
(`parent-level-display-canonical-reads`) that gates the Admin Refresh System.
Snapshot date: **2026-05-02**. Prod DB: `data/13f.duckdb`. No DB writes, no
schema changes, no production module modifications.

Detailed phase findings live in five partial fragments (referenced by section).
Helper scripts for every audit are in `scripts/oneoff/institution_scoping_*.py`,
all opened with `read_only=True`. Verification: `grep -iE
'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b'` over the helpers
returns 9 hits, all docstrings/comments — no DDL/DML executes.

---

## 1. Executive summary

**Rollup integrity at the fund tier is healthy** (99.42% rows / 99.74% AUM
intact). The dangling-rollup "Calamos N/A" shape (entity_id=11278) is fully
resolved post-PR #251 — zero residual `is_latest=TRUE` rows.

**The institution tier is where the work is.** Three structural defects gate
the Admin Refresh System:

1. **Brand-vs-filer entity_id duplication** — 1,225 institutions receiving
   fund rollups have **zero** `is_latest=TRUE` rows in `holdings_v2`,
   exposing **~$27.8T of fund-side AUM** to be invisible in any
   institution-level Admin Refresh view (Vanguard, PIMCO, BlackRock Fund
   Advisors, J.P. Morgan IM, etc.). Fund-tier rolls up to brand eids;
   institution-tier keys off filer-CIK eids. The bridge is missing.
2. **Three classification dictionaries disagree on 4,043 CIKs / $64.7T**
   (`holdings_v2.entity_type`, `holdings_v2.manager_type`,
   `managers.strategy_type` — and a fourth `entity_classification_history`
   adds buckets the others lack). Every parent-level read site picks one
   without reviewing.
3. **`ingestion_manifest` schema does not match the Admin Refresh design
   doc** — every admin endpoint touches this table, and the design queries
   columns (`pipeline_name`, `status`, `completed_at`, `row_counts_json`)
   that don't exist; the live schema uses `source_type`, `fetch_status`.
   This is a structural blocker for user-triggered Admin Refresh.

**`query4` silent-drop bug is confirmed** at `scripts/queries/register.py:746-750`.
Today **1,543,537 rows / $23.0T fall into "Other/Unknown"** at LQ — 48% of
rows / 34% of AUM. Of those, **324K rows / $5.5T** explicitly carry
disagreeing `manager_type`/`entity_type` signals the CASE ignores. The fix is
a 10-line CASE rewrite (Option A) or a folding into the canonical-reads sweep
(Option B). Visible blast radius today is small (no React tab consumes
`/api/v1/query4`; only Excel export and direct API).

**Type-merge work is largely cosmetic at the data level.**
- `multi_strategy` bucket is essentially mislabeled — only 2 CIKs / $11.7B
  (Adams Diversified Equity CEF + Diversified Management Inc); recommend
  killing the bucket rather than migrating.
- PE+VC merge: 143 CIKs / $1.22T combined, but PE carries $440B+ of
  misclasses (Mariner, Barrow Hanley, Dynasty) needing triage **before**
  the merge or they pollute the new PE+VC bucket.
- WM+FO merge: 420 CIKs / $10.45T combined. FO is 0.6% of WM AUM and is
  genuinely a sub-flavor; clean merge.
- HF+multi_strategy merge: 1,019 CIKs / $8.95T combined; the multi_strategy
  side is a no-op.

**Activist universe is small** — 20 CIKs / $297B. ECH already implements the
architecturally-correct orthogonal-flag shape (`is_activist` independent of
`classification`); the read sites just don't consume it yet. Migration is
MEDIUM complexity (small data, ~7 read sites + React badge).

**Critical-path PR count to unblock Admin Refresh: 5.**
**Total estimated session count for the full institution-level sequence: ~14
sessions** (5 critical-path + 6 type-merge parallel + 3 cleanup).

---

## 2. Phase 1A — Institution-level current state

Detail: `docs/findings/institution_scoping_partial_1a_5.md` (foreground) and
`docs/findings/institution_scoping_phase_1A_5.md` (background, parallel run).

### 2.1 Distribution audit (holdings_v2, is_latest=TRUE)

`holdings_v2.entity_type` (13 buckets, 9,121 distinct CIKs):

| entity_type | rows | AUM | distinct CIKs |
|---|---:|---:|---:|
| active | 4,172,727 | $67.0T | 4,431 |
| mixed | 2,893,109 | $39.6T | 743 |
| wealth_management | 2,663,260 | $15.4T | 1,679 |
| hedge_fund | 1,160,104 | $25.0T | 1,340 |
| passive | 672,523 | $76.3T | 51 |
| pension_insurance | 327,501 | $6.9T | 149 |
| quantitative | 297,001 | $5.5T | 47 |
| strategic | 40,341 | $1.8T | 451 |
| SWF | 21,698 | $4.1T | 13 |
| endowment_foundation | 10,258 | $865.8B | 68 |
| private_equity | 6,655 | $651.6B | 89 |
| venture_capital | 4,774 | $44.7B | 46 |
| activist | 1,033 | $284.2B | 16 |

`holdings_v2.manager_type` adds two values absent from `entity_type`:
`family_office` (49 CIKs / $66.5B) and `multi_strategy` (2 CIKs / $11.7B).

`managers.strategy_type` is single-row-per-CIK: 11,135 CIKs total, 1,293 NULL
(silent fall-through risk for any read site that joins managers).

`entity_classification_history.classification` (open rows): coverage of
institutions with latest holdings = **99.9%** (9,111 of 9,121). Adds
`market_maker` (~$7.1T of CIKs that hv2 calls hedge_fund — Susquehanna,
Citadel, Jane Street, IMC, Optiver) and an `unknown` bucket (3,852 entities)
that hv2 does not have.

### 2.2 Cross-tab divergence

**4,043 CIKs / $64.7T diverge** between `holdings_v2.entity_type` and
`managers.strategy_type` — 44% of the 9,121-CIK institution universe. Top
single-name divergences: Morgan Stanley ($6.3T), Norges Bank ($3.1T),
Susquehanna ($3.0T), Citadel ($2.4T), Jane Street ($2.2T), Dimensional
($1.8T). Within `holdings_v2`, the largest entity_type/manager_type
divergent pairs:

| entity_type / manager_type | CIKs | AUM |
|---|---:|---:|
| wealth_management / mixed | 845 | $3.3T |
| wealth_management / active | 467 | $1.8T |
| hedge_fund / active | 279 | $3.4T |
| hedge_fund / quantitative | 33 | **$9.8T** |
| active / mixed | 15 | $8.3T |
| hedge_fund / mixed | 7 | $3.1T |

The four-dictionary disagreement is the structural cause of the `query4`
bug and the impedance mismatch every parent-level read inherits.

### 2.3 Parent-level read site enumeration

ROADMAP tracks "18 parent-level display read sites". Reality is more
nuanced — 18 user-visible read points (when collapsing multi-line
projections to one query/function) **OR** ~25 logical Python sites + 6
Datasette views + 6 React tab components ≈ **37 total touch points** if
admin/DQ/Datasette paths are included.

The 18-site count, by file:
- `register.py` — 11 sites (queries 1, 2, 3, Top-25, query4 (silent drop),
  query5 heatmap, active-only filters, query16, coverage stats, value split,
  active/passive value)
- `cross.py` — 2 sites (level=parent, active_only filter)
- `flows.py` — 1 site (parent rollup)
- `trend.py` — 2 sites (Holder Momentum parent, Sector Flows active filter)
- `market.py` — 1 site (Market parent — though spans 5 lines)
- `api_market.py` + `api_fund.py` — 1 site (thin shim projections)

Plus shared helper `common.py:687` and `fund.py:111` reused by multiple.

**Canonical helper exists but has zero callers.** `classification_join()` at
`scripts/queries_helpers.py:171` defines the ECH-aware
`LEFT JOIN entity_classification_history ON valid_to = DATE '9999-12-31'`
pattern. No file imports it. PR-1d's fund-level analogue
(`_fund_type_label`) is widely used for fund rows but doesn't apply
parent-level. Whoever ships the migration will be re-discovering the JOIN
shape.

---

## 3. Phase 1B — Fund-to-institution rollup completeness

Detail: `docs/findings/institution_scoping_partial_1b_1.5.md` (foreground)
and `docs/findings/institution_scoping_phase_1B_15.md` (background).

Baseline: `fund_holdings_v2 is_latest=TRUE` = 14,565,870 rows / $161.59T.

### 3.1 Headline: rollup integrity 99.42% rows / 99.74% AUM (foreground)

The two parallel agents differed slightly in failure-set definition. The
**stricter foreground number** (99.42%/99.74% intact) treats only NULL-id
orphans, dangling rollup, and sponsor-shelf-mismatch as failures. The
**broader background number** (97.90%/99.20% intact, i.e. 305,808 rows /
$1.29T failing) additionally counts rows rolling up to entities with
`entity_type='fund'` (221K rows / $871B). Both find the Calamos N/A shape
fully resolved. Synthesis recommendation: lead with the strict number for
fund-tier health, then immediately pivot to Phase 1.5 (cross-tier) where
the real defect is.

| Failure mode | rows | AUM (fund-side) |
|---|---:|---:|
| Orphan (any of 4 ID columns NULL — they share the same NULL set) | 84,363 | $418.55B |
| Dangling rollup (target = N/A or 'mixed'/'unknown' entity_type) | **0** | **$0** |
| Sponsor-shelf-mismatch (SYN_<cik> ≠ rollup brand) | 110 | $3.72B |
| **Union, deduped** | **84,473** | **$422.27B** |
| % of fund universe | 0.580% | 0.261% |
| **Integrity** | **99.420%** | **99.739%** |

### 3.2 Calamos N/A shape: zero residual

Entity 11278 (literally named 'N/A') has **zero** `is_latest=TRUE` rows in
`fund_holdings_v2`. PR #251 cleared it end-to-end. Entity 11278 is the only
N/A-named entity in the `entities` table. The new shape uncovered by the
broader audit is **221,445 rows / $871.3B rolling up to entity_type='fund'**
entities (187 distinct), with names like "Growth Fund", "Mid Cap Value
Fund", "Heritage Fund". Whether this is a defect or by-design naming depends
on the institution-tier read semantics — see Phase 1.5.

### 3.3 Orphan funds — fixed-income skew

The 84,363 NULL-id rows cluster on **fixed-income / multi-asset families**:
Capital Group "American" bond funds (Bond Fund of America, Tax Exempt Bond
Fund, Intermediate Bond Fund, Limited Term Tax Exempt) account for $216B of
the $418B orphan AUM. Other heavyweight orphans: AB Global Bond, Eaton
Vance Global Macro, Voya bond portfolios, CCM Community Impact. Hypothesis:
the entity-resolution pipeline misses non-standard fixed-income shelf
naming. Captured as a follow-up to the existing P2
`fund-holdings-orphan-investigation` item.

### 3.4 Wrong-shelf rollup — borderline only

After PR #251 ASA fix, residual is 1 group / 110 rows / $3.72B
(SYN_0002044519 Coatue Innovative Strategies Fund vs Coatue Management).
This looks correct (parent-firm rollup). Naive Jaccard on family_name
flags $63T but the top samples are all legitimate parent→subsidiary
attributions (FMR↔Fidelity, Capital Group↔American Funds, State
Street↔SPDR). A useful detector requires a brand-alias map — captured as a
follow-up.

---

## 4. Phase 1.5 — Cross-tier consistency: the real gap

Detail: same partials as Phase 1B.

### 4.1 Invisible institutions — $27.8T of fund-side AUM has no holdings_v2 anchor

`fund_holdings_v2 is_latest=TRUE` rolls up to **1,707 distinct
dm_rollup_entity_id values**. `holdings_v2 is_latest=TRUE` covers **9,121
distinct entity_id values**. Of the 1,707 fund-rollup-target institutions,
**1,225–1,326 (depending on join key tried) have zero match in holdings_v2**
across `entity_id`, `rollup_entity_id`, or `dm_rollup_entity_id`.

Fund-side AUM exposure: **$27,797.71B (~17% of fund-tier AUM)** under the
foreground methodology; **$30,113B (~18.6%)** under the background. Either
way, this dwarfs the 1B fund-tier integrity number.

Top 10 invisible institutions by fund AUM:

| eid | name | rows | fund_aum |
|---|---|---:|---:|
| 18073 | VOYA INVESTMENTS, LLC | 183,559 | $2,714.53B |
| 1 | Vanguard Group | 267,751 | $2,541.53B |
| 30 | PIMCO | 289,040 | $1,716.00B |
| 9904 | TEACHERS ADVISORS, LLC | 100,015 | $1,571.05B |
| 7586 | TRANSAMERICA CORP | 70,554 | $1,303.29B |
| 1355 | Venerable Investment Advisers, LLC | 92,179 | $1,162.81B |
| 17924 | VOYA INVESTMENTS, LLC (dup) | 66,552 | $1,105.54B |
| 9935 | Wellington Management Co LLP | 89,257 | $757.51B |
| 2400 | Fidelity Management & Research Co LLC | 160,020 | $714.59B |
| 3586 | NORTHWESTERN MUTUAL LIFE INSURANCE CO | 213,206 | $645.07B |

**Diagnosis (verified for Vanguard + PIMCO):** `eid=1` is the canonical
"Vanguard Group" institution entity. Vanguard's 13F filings live under
`eid=4375` (the registered 13F filer CIK). `eid=30` is the canonical
"PIMCO" institution; zero holdings_v2 rows. Multiple brands have duplicate
canonical entities (UBS AM at 2322 + 18062, Voya at 18073 + 17924, Mercer
at 8994 + 10538, WisdomTree at 3050 + 19555).

**This is a fundamental mapping defect: fund-tier rolls up to "brand" eids,
institution-tier keys off "filer-CIK" eids, and the bridge is broken or
never built.** It is the dominant cross-tier integrity issue and the
single biggest blocker for an institution-coverage Admin Refresh view.

### 4.2 AUM plausibility — 130 implausible institutions

Of the 1,707 fund-rollup-target institutions, 436 have at least one match
in `holdings_v2.dm_rollup_entity_id`. Of those, **130 are implausible**
(`fund_aum > 1.5x institution_aum`). Top 10 by absolute delta:

| eid | name | fund_aum | inst_aum | delta | ratio |
|---|---|---:|---:|---:|---:|
| 4375 | Vanguard Group | $38,729.80B | $25,322.97B | $13,406.82B | 1.53x |
| 10443 | Real Estate Portfolio | $20,456.60B | $7,224.11B | $13,232.49B | 2.83x |
| 12 | Capital Group / American Funds | $14,336.20B | $7,265.22B | $7,070.97B | 1.97x |
| 3616 | T. Rowe Price | $4,158.07B | $4.19B | $4,153.88B | **992.83x** |
| 17 | MFS Investment Management | $2,346.37B | $1,248.81B | $1,097.56B | 1.88x |
| 893 | LORD, ABBETT & CO. LLC | $283.90B | $0.13B | $283.78B | **2,265.07x** |
| 4636 | Western Asset Management Co | $145.50B | $0.17B | $145.33B | **859.74x** |
| 6314 | Jackson National Asset Mgmt | $131.65B | $0.05B | $131.60B | **2,460.38x** |

Ratios above 100x cannot be explained by quarter-stacking and confirm the
same eid-mismatch as 4.1. Vanguard's 1.53x is plausibly the gap between
Vanguard's mutual-fund holdings (broader N-PORT universe) vs its 13F
filings (narrower long-equity slice).

### 4.3 Deprecated / superseded rollups — 19 entities, $68.7B exposed

Closed within the last few weeks: TEACHERS ADVISORS, TRANSAMERICA, PGIM,
FMR LLC, NORTHWESTERN MUTUAL — combined fund AUM > $5T (overlaps with 4.1).
Strict deprecation gate (`entity_classification_history.valid_to < CURRENT_DATE`):
**19 entities receive fund rollups despite being closed**, $68.7B exposed.
Top: Dimensional Fund Advisors LP `eid=18096` ($52.3B, closed 2026-04-17)
and BlackRock Advisors LLC `eid=17999` ($7.8B). All closed mid-April 2026
— likely fallout from the Apr 11–12 entity-merge marathon (per memory)
where successor eids were created but fund-tier rollups weren't re-pointed.
Note: `entity_relationships` does not carry
`alias_of`/`merged_into`/`superseded_by` types in this DB — the relationship
taxonomy is something else that needs re-confirming as part of the bridge
PR.

---

## 5. Phase 2 — Type-merge decisions audit

Detail: `docs/findings/institution_scoping_partial_2_3.md`.

### 5.1 PE + VC merge

143 combined CIKs / 76,181 rows / **$1,215.32B AUM**. Structurally fine
post-merge.

**Pre-merge triage required.** PE bucket carries $440B+ of misclasses:
- Mariner LLC ($290.8B) — name resembles MFO/wealth-management, not PE
- Barrow Hanley Mewhinney & Strauss ($118.7B) — long-only equity manager
- Dynasty Wealth Management ($29.5B) — wealth platform, not PE

If absorbed into PE+VC without triage, these pollute the new bucket. Also
flag: Bain Capital Venture Investors LLC (PE in hv2, VC in
managers.strategy_type) — resolve before merge.

### 5.2 WM + FO merge

420 combined CIKs / 1,343,203 rows / **$10,449.72B AUM**. Clean merge.
FO is $66.5B (0.6% of WM AUM) and is genuinely a sub-flavor of WM in this
dataset. **Migration prerequisite: Phase 3.1 family_office classification
must land first** — `family_office` is currently a `manager_type` value
not present in `entity_classification_history.classification`.

### 5.3 HF + multi_strategy merge

1,019 combined CIKs / 550,926 rows / **$8,947.94B AUM**. The
multi_strategy side is essentially a no-op — only 2 CIKs:
- Adams Diversified Equity Fund (CEF, $11.28B) — **not** a multi-strategy
  hedge fund
- Diversified Management Inc ($0.43B) — likely also CEF/non-HF

True pod-shop multi-strategy firms (Citadel, Millennium, Point72,
ExodusPoint) already live in `hedge_fund`. The merge as defined is a
2-CIK / $11.7B relabel. Recommendation in Phase 3.2 below.

### 5.4 Pre-deferred decisions

**`market_maker` backfill** — 30 CIKs / $8.24T match MM-name patterns; 23
are already classified `market_maker` in `entity_current`. Net new clean
candidates after dropping false positives (Virtus family of asset
managers): ~12 (Belvedere, Wolverine, Peak6, Akuna, Tower Research, XTX,
Headlands, Old Mission, GTS Securities, DRW Securities, Susquehanna
sub-units, Global IMC). **Recommend defer** — needs a stricter allowlist
(FINRA broker-dealer registration) than name-regex.

**`is_passive` boolean redundancy** — only 1 CIK has `is_passive=TRUE`
outside `manager_type='passive'` (Tred Avon, $0.6B, almost certainly a
bug). 8 CIKs have `manager_type='passive'` but `is_passive` not TRUE
($84B combined — Exchange Traded Concepts $38.9B, Ossiam $28.8B, Matson
Money $11.8B, Eagle Strategies, Passive Capital Management, Swmg, AFT
Forsyth & Sober, Hatteras). Read sites: `build_managers.py`,
`build_summaries.py`, `load_13f_v2.py`, `apply_series_triage.py`. All
replaceable with `manager_type='passive'` derivation. Defer column drop
until after the canonical-reads sweep.

**SWF / pension_insurance / endowment_foundation** — 13 / 136 / 67 CIKs
respectively. Distinct mandates and regulatory profiles. **Keep separate.**

**`mixed` / `unknown`** — `mixed` is the **single biggest classification
bucket by AUM** (~$55T at manager_type level, $40T at entity_type level),
dominated by wirehouses and universal banks (Morgan Stanley, JPM, BofA,
GS, UBS, RBC, BNY Mellon, Wells Fargo, Ameriprise, Franklin, Deutsche
Bank, BMO, Barclays, Citi, BNP, Sumitomo Mitsui Trust, HSBC, TD, Citi, US
Bancorp, Aberdeen, Macquarie, Toronto Dominion, Nomura, MUFG). 9 of the
top-25 `manager_type='mixed'` firms have a disagreeing `entity_type`. No
NULL/unknown rows in `holdings_v2`. 3,852 open `unknown` rows in
`entity_classification_history` await MDM. Recommended treatment: **don't
change the `mixed` definition for the type-merge phase**; address
manager_type↔entity_type harmonization separately.

---

## 6. Phase 3 — Migration prerequisites

### 6.1 family_office migration (gates WM+FO merge)

| source | distinct CIKs | rows | AUM |
|---|---:|---:|---:|
| holdings_v2 (mt='family_office', is_latest) | 49 | 36,950 | $66.52B |
| managers (strategy_type='family_office') | 51 | — | — |

All 49 holdings_v2 family_office CIKs already have `entity_id`. The
migration is a pure UPDATE of classification history, not a new-entity
bootstrap. 39 of 49 already have an open ECH row classifying them as
`wealth_management` (3 sourced `adv_strategy_inferred`, the rest legacy
seed). The fresher manager_type='family_office' assignment in holdings_v2
is more authoritative — the migration must close those WM rows
(`valid_to = today-1`) and insert new FO open rows.

`entity_classification_history.classification` does NOT currently contain
`family_office`. Adding it requires no schema change (column is plain
VARCHAR), but downstream consumers with `CASE WHEN classification IN
(...)` clauses need an audit.

### 6.2 multi_strategy migration

Only 2 CIKs total (entity_ids 2961, 7715), both currently `hedge_fund` in
ECH. **Two paths:**

- **Option A (faithful):** Migrate to `multi_strategy` in ECH, then run
  the HF+multi_strategy merge. Net result: 2 CIKs / $11.7B re-flow into
  HF anyway.
- **Option B (recommended):** Skip the multi_strategy classification
  entirely. Re-classify Adams Diversified to `mixed` (or new
  `closed_end_fund` bucket if `fund-structure-column` work is in scope) and
  Diversified Management Inc per its actual strategy. **Drop
  `multi_strategy` from `manager_type` / `strategy_type` altogether.**

### 6.3 Sequencing

Migrations 3.1 and 3.2 are independent and can run in parallel (different
entity_ids, different classification values).

```
                ┌────────────────────────────────────────┐
                │ entity_classification_history schema   │
                │ (no change — column is VARCHAR)        │
                └───────────────┬────────────────────────┘
                                │
            ┌───────────────────┼────────────────────┐
            ▼                   ▼                    ▼
      ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
      │ MIG 3.1      │  │ MIG 3.2      │  │ (drop is_passive)│
      │ family_office│  │ multi_strat  │  │ — not blocking    │
      │ 49 / $66.5B  │  │ 2 / $11.7B   │  └──────────────────┘
      └──────┬───────┘  └──────┬───────┘
             ▼                 ▼
      ┌──────────────┐  ┌──────────────┐
      │ MERGE WM+FO  │  │ MERGE HF+MS  │
      └──────────────┘  └──────────────┘

      ┌──────────────┐
      │ MERGE PE+VC  │  (no migration prereq, but PE triage recommended)
      └──────────────┘
```

---

## 7. Phase 4 — query4 silent-drop bug

Detail: `docs/findings/institution_scoping_partial_4_6.md`.

### 7.1 Confirmed location

`scripts/queries/register.py:740-765` (the CASE itself at lines 746-750):

```python
CASE
  WHEN entity_type = 'passive' THEN 'Passive (Index)'
  WHEN entity_type = 'activist' THEN 'Activist'
  WHEN manager_type IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
  ELSE 'Other/Unknown'
END as category
```

Mixes two columns (`entity_type` for branches 1–2, `manager_type` for
branch 3). The columns disagree on ~10% of rows / ~8% of AUM, causing
silent drop.

### 7.2 Quantification at LQ (2025Q4, all tickers, is_latest=TRUE)

| Category | Rows | AUM ($B) | Share of rows | Share of AUM |
|---|---:|---:|---:|---:|
| Other/Unknown | 1,543,537 | 23,032.4 | 48.2% | 34.2% |
| Active | 1,495,424 | 23,355.3 | 46.6% | 34.7% |
| Passive (Index) | 166,424 | 20,845.5 | 5.2% | 31.0% |
| Activist | 265 | 87.9 | ~0.0% | 0.1% |
| **Total** | **3,205,650** | **67,321.2** | 100% | 100% |

Other/Unknown is the **single largest bucket** — 48% of rows / 34% of AUM
disappear into "we don't know."

Disagreement-only subset (manager_type bucket ≠ entity_type bucket, both
non-NULL): **324,194 rows / $5,496.1B**. The largest sub-cohorts:

| manager bucket | entity bucket | Rows | AUM ($B) |
|---|---|---:|---:|
| active_family | other_family | 171,233 | 590.3 |
| other_family | active_family | 127,534 | 3,328.2 |
| passive_family | active_family | 19,380 | 630.8 |
| passive_family | other_family | 2,984 | 942.9 |

Per-ticker worst case: NVDA — 4,188 of 9,042 holders ($929.8B of $3,090.2B,
~30% of book) sit in Other/Unknown.

### 7.3 Affected output surfaces

- API: `/api/v1/query4` and `/api/v1/export/query4` (Excel).
- React app: **no current consumer** — `web/react-app/src/types/api.ts`
  defines envelopes for `/api/query1` and `/api/query7` only. Visible
  blast radius today is small. Any future tab built on q4 inherits the
  bug.

### 7.4 Pattern uniqueness

Searched `cross.py`, `fund.py`, `trend.py`, `market.py`, `common.py` for
the same disagreement pattern. **No other file mixes the two columns the
way `register.py:746-750` does.** The bug is uniquely localized to
query4. Other read sites are vulnerable to the same disagreement noise but
only as filter under-/over-counts, not silent-drop categorization.

### 7.5 Fix shape

**Option A (minimal, ~10 lines):**

```python
CASE
  WHEN entity_type = 'passive' OR manager_type = 'passive' THEN 'Passive (Index)'
  WHEN entity_type = 'activist' OR manager_type = 'activist' THEN 'Activist'
  WHEN manager_type IN ('active','hedge_fund','quantitative')
    OR entity_type  IN ('active','hedge_fund','quantitative') THEN 'Active'
  WHEN manager_type IS NOT NULL OR entity_type IS NOT NULL THEN 'Other'
  ELSE 'Unknown'
END
```

Recovers ~324K rows / $5.5T (the disagreement total) into proper buckets;
shrinks Other/Unknown by that amount; splits Other from Unknown for
analyst clarity.

**Option B (canonical, the ROADMAP intent):** delete the CASE on
`holdings_v2.manager_type/entity_type` entirely; join to
`entity_current.classification` via `entity_id` and bucket on the
canonical column. Folds into the `parent-level-display-canonical-reads`
sweep.

---

## 8. Phase 5 — Activist-as-flag architecture

### 8.1 Current state — small data, four sources of truth

| dictionary / column | rows | AUM | distinct CIKs |
|---|---:|---:|---:|
| `holdings_v2.manager_type='activist'` | 2,143 | $297.05B | 20 |
| `holdings_v2.entity_type='activist'` | 1,033 | $284.24B | 16 |
| `holdings_v2.is_activist=TRUE` | 1,847 | $276.70B | 16 |
| `managers.is_activist=TRUE` | 23 | $26.98B | 23 |
| `managers.strategy_type='activist'` | 26 | $26.98B | 26 |
| `entity_classification_history.classification='activist'` (open) | 34 | — | 34 |
| `entity_classification_history.is_activist=TRUE` (open) | 150 | — | 150 |

Top-AUM activists where all three holdings_v2 signals agree: Elliott
($57.4B), Pershing Square ($43.9B), Icahn ($33.0B), Third Point ($30.4B),
ValueAct ($23.1B), Starboard ($21.9B), Trian ($15.6B). Pure activist
names; **no crossover ambiguity** with hedge_fund / multi_strategy. Four
CIKs have `manager_type='activist'` but `is_activist=FALSE` (Mantle Ridge,
Impactive Capital, Engaged Capital, Cannell Capital, ~$20B combined) —
under-population of the flag, not crossover.

### 8.2 ECH already implements the target shape

`entity_classification_history.is_activist` is already orthogonal to
`classification`: 150 entities have it set, of which only 34 have
`classification='activist'`. The other 116 have classifications `active`
(70), `strategic` (42), and one each of `hedge_fund`, `private_equity`,
`venture_capital`. **This is the architecturally-correct shape Phase 5 is
asking about — half-shipped at the source-of-truth layer.** The read
sites just don't consume it.

### 8.3 Migration shape

Promote ECH `is_activist` to canonical truth source. Re-typing 20 CIKs to
ECH classifications would yield:
- 15 → `activist` kept as label
- 3 → `hedge_fund`
- 1 → `wealth_management`
- 1 → review

Read sites filtering on `manager_type='activist'` or `entity_type='activist'`
(7 total): `register.py:472`, `register.py:748` (the CASE), `register.py:1018`,
`register.py:1354`, `market.py:373`, `market.py:498`, `build_summaries.py:173,181`.

**Latent bug surfaced:** `register.py:1018` excludes activist where `:472`,
`:1354`, `market.py:373/498` include it. Inconsistent active-universe
definition across the same Register tab. Likely a copy-paste at the time
activist was added; needs a one-line decision before the canonical
migration.

The React app has **no dedicated Activist tab**, no SQL pattern outside
the badge color in `web/react-app/src/components/common/typeConfig.ts:20`.
`getTypeStyle()` does not yet accept `is_activist` as input.

Migration complexity: **MEDIUM**. Small data footprint (20 CIKs / $297B),
~7 code touch points, ECH already proves the pattern.

---

## 9. Phase 6 — Admin Refresh System dependency map

Detail: `docs/findings/institution_scoping_partial_4_6.md` §Phase 6.

13 dependencies extracted from `docs/admin_refresh_system_design.md`
(990 lines). 13 gaps identified. **3 BLOCKERS** (G1, G2, G4):

| # | Gap | Severity | Notes |
|---|---|---|---|
| **G1** | `manager_type`/`entity_type` disagree on ~10% rows / ~8% AUM (1.54M rows / $23T in Other/Unknown) | **BLOCKER** | Anomaly checks like "per-filer AUM by manager_type bucket" inherit the disagreement. Closes via Phase 4 fix + the canonical-reads sweep. |
| **G2** | Admin Refresh has no entity-classification pipeline | **BLOCKER** | Reclassification (recent CEF reclassify, family_office migration) is out-of-band today. Design doesn't say so. Two reasonable closes: (a) declare it permanently out-of-band in design v3.3; (b) add an entity-classification pipeline to the framework. |
| **G3** | `manager_type` taxonomy mismatch — `family_office` and `multi_strategy` exist in hv2 but not in `entity_current.classification` | non-blocker | Closes via Phase 3 migrations. |
| **G4** | `ingestion_manifest` schema does NOT match design's assumed shape | **BLOCKER** | Design refers to `pipeline_name`, `status`, `row_counts_json`, `completed_at`. Live schema uses `source_type`, `fetch_status`. Every admin endpoint touches this table. **Reconcile before user-triggered Admin Refresh ships.** Two paths: rename live columns, or rewrite design doc + admin queries to match live. |
| G5 | Activist is a manager_type value, not a flag | non-blocker | Closes via Phase 5 migration. |
| G6 | `entity_relationships` / `entity_rollup_history` not under Admin Refresh | non-blocker | 0 NULL `dm_rollup_entity_id` today; green now, no framework guard for future drift. |
| G7 | Top-100 institutions identity assumption | non-blocker | Valid only if rollup IDs are stable; the 1.5.1 brand-vs-filer eid issue affects this. Anomaly check needs an explicit join target. |
| G8 | `pending_entity_resolution` has 6,874 open rows; design's `max_new_pending: 100` threshold is **68× too tight** | non-blocker | Recalibrate threshold to delta-from-prior-run, not absolute. |
| G9 | `admin_preferences` has 0 rows today | non-blocker | Auto-approve is opt-in, default disabled. |
| G10 | `data_freshness` only tracks 29 entries | non-blocker | Sufficient for status feed today. |
| G11 | Migration 008 was renumbered to 015 | non-blocker | Documentation cleanup. |
| G12 | Backfill quality coverage | non-blocker | All targets met per DONE annotations. |
| G13 | No published canonical-vs-derived parity check before/after refresh | non-blocker | Today's refresh re-stamps `holdings_v2.manager_type` from the loader without verifying it matches `entity_current.classification`. |

**Biggest blocker: G4 (`ingestion_manifest` schema mismatch).** Structural —
every admin endpoint touches this table.

**Cross-tier eid bridge defect (Phase 1.5) is implicitly G14** — not on
the design's dependency list at all, but it makes Admin Refresh's
institution-coverage view incoherent for $27.8T of fund-side AUM.
**Promote to BLOCKER** as part of the synthesis.

**Total BLOCKER count, including the synthesis-promoted G14: 4.**

---

## 10. Phase 7 — Sequenced PR plan

Branch slugs are proposals; sizes are estimates (S = 1 session, M = 1.5–2,
L = 3+).

### 10.1 Critical-path PRs (gate Admin Refresh System)

| # | Branch slug | Size | Pre-flight | Depends on | Q1 cycle |
|---|---|---|---|---|---|
| **CP-1** | `inst-eid-bridge-investigation` | S | backup, app-off | none | pre-cycle |
| **CP-2** | `ingestion-manifest-reconcile` | M | backup, app-off, staging-twin | none | pre-cycle |
| **CP-3** | `query4-fix-option-a` | S | app-off | none | pre-cycle |
| **CP-4** | `inst-eid-bridge-fix` | L | backup, app-off, staging-twin | CP-1 | post-cycle |
| **CP-5** | `parent-level-display-canonical-reads` | L | app-off | CP-3 ideally lands first | post-cycle |

CP-1 is the read-only investigation PR that maps the brand-vs-filer eid
duplication and produces a manifest of the 1,225 invisible institutions
with their proposed bridge mappings. CP-2 reconciles the
`ingestion_manifest` schema (likely add columns + view to satisfy design).
CP-3 is the 10-line CASE rewrite at register.py:746-750. CP-4 actually
lands the bridge mappings (entity_relationships population pass + fund_holdings_v2
rollup re-pointing). CP-5 is the 18-site (37 touch-point) sweep.

### 10.2 Type-merge parallel track

Can ship in parallel with CP-* once CP-2 + CP-3 land.

| # | Branch slug | Size | Depends on | Q1 cycle |
|---|---|---|---|---|
| TM-1 | `family-office-classification-migration` | S | none | cycle-neutral |
| TM-2 | `multi-strategy-decision` (Option B: drop) | S | none | cycle-neutral |
| TM-3 | `wm-fo-merge` | M | TM-1 | post-cycle |
| TM-4 | `hf-multi-strategy-merge` (Option B = no-op) | S | TM-2 | post-cycle |
| TM-5 | `pe-bucket-triage` (Mariner/Barrow/Dynasty) | S | none | cycle-neutral |
| TM-6 | `pe-vc-merge` | M | TM-5 | post-cycle |

### 10.3 Cleanup track (defer past Admin Refresh launch)

| # | Branch slug | Size | Depends on | Q1 cycle |
|---|---|---|---|---|
| CL-1 | `activist-as-flag` | M | CP-5 | post-cycle |
| CL-2 | `register.py:1018-active-universe-fix` | S | none (one-line) | cycle-neutral |
| CL-3 | `drop-is-passive-column` | S | CP-5 | post-cycle |
| CL-4 | `admin-refresh-anomaly-thresholds` | S | none | post-cycle |
| CL-5 | `mixed-bucket-harmonization` | M | CP-5 | post-cycle |
| CL-6 | `market-maker-backfill` (with FINRA allowlist) | M | none | cycle-neutral |
| CL-7 | `entity-relationships-deprecated-rollup-cleanup` | S | none | cycle-neutral |

### 10.4 Critical-path session count

5 critical-path PRs × ~2 sessions average (CP-2/4/5 are L/M; CP-1/3 are S)
= **~7 sessions on critical path**. With type-merge in parallel (~5
sessions if pipelined) and cleanup (~3 sessions): **~14 sessions total**
for the institution-level sequence end-to-end.

If type-merge and cleanup ship after Admin Refresh exits Q1, the
critical-path-only run (CP-1 → CP-5) is **5 PRs / ~7 sessions**.

### 10.5 Minimum-viable PR set for Admin Refresh

CP-2 + CP-3 + CP-1 + CP-4 + CP-5. Plus a one-line G8 threshold
recalibration (CL-4 promoted to critical) so the first user-triggered
refresh doesn't immediately fire an anomaly. So **6 PRs minimum** if
CL-4 promotes.

---

## 11. Phase 8 — Q1 2026 cycle interaction

Q1 cycle = **~2026-05-15** (about 13 days from snapshot date).

### 11.1 Pre-cycle (must land before May 15)

- **CP-2** `ingestion-manifest-reconcile` — admin dashboard breaks
  otherwise; first cycle will exercise it.
- **CP-3** `query4-fix-option-a` — independent and small; ship anytime.
- **CL-4** `admin-refresh-anomaly-thresholds` — first user-triggered
  refresh would fire `max_new_pending` 68× over today.

### 11.2 Cycle-data-required

- **CP-1** `inst-eid-bridge-investigation` — Q1 data may surface new
  brand/filer eid duplicates (new mutual-fund families filing for the
  first time). Investigation PR could ship pre-cycle but the manifest
  should be re-validated against Q1 data before CP-4 lands.
- **TM-5** `pe-bucket-triage` — Q1 cycle may surface new PE-tagged firms;
  decide cohort post-cycle.

### 11.3 Post-cycle ship

- **CP-4** `inst-eid-bridge-fix` — wait for Q1 data so the bridge
  mappings cover new filers in one pass.
- **CP-5** `parent-level-display-canonical-reads` — large sweep; better
  to defer past Q1 to avoid scope creep during cycle.
- All type-merge PRs (TM-3/4/6) — need entity layer settled.

### 11.4 Cycle-neutral

CL-2, CL-6, CL-7, TM-1, TM-2, TM-5 can ship independent of cycle timing.

### 11.5 Cycle-altering scope

No PR currently scoped is expected to materially change scope based on Q1
data, except potentially CP-1 (new eid duplicates) and TM-5 (new PE-tagged
firms). Both are bounded — additions to existing manifests, not
re-architectures.

---

## 12. Open questions for chat decision (ranked by blocking impact)

1. **(BLOCKER)** Reconcile `ingestion_manifest` schema (G4): rename live
   columns to match design, or rewrite design + admin queries to match
   live. Pure design call, but every admin endpoint depends on it.
2. **(BLOCKER)** Bridge brand-vs-filer eid duplication: how to populate
   the bridge — by eid-match on canonical name (fragile), by
   entity_relationships parent/child (preferred but requires populating
   that table), or by fund-side re-pointing? Affects CP-1 manifest shape.
3. **(BLOCKER)** Admin Refresh entity-classification pipeline (G2): treat
   reclassification as permanently out-of-band and document it explicitly,
   or add a pipeline. If out-of-band, the Top-100 anomaly check needs to
   know how to respond when an institution renames between refreshes.
4. **(BLOCKER)** Decision D4 from PR-1c — precedence rule for institutions
   without an `entity_classification_history` row. ECH coverage is 99.9%
   (10 of 9,121 uncovered) but the migration is design-blocked without
   the rule. Default to `holdings_v2.manager_type` fallback?
5. **(non-blocker)** Multi_strategy classification — Option A (faithful
   migration of 2 CEFs) or Option B (drop the bucket entirely, re-route
   the 2 CIKs to `mixed`)? Recommended Option B.
6. **(non-blocker)** PE bucket triage scope before PE+VC merge:
   triage Mariner ($291B), Barrow Hanley ($119B), Dynasty Wealth ($30B)
   first, or absorb into PE+VC and triage post-merge? Recommended:
   triage first.
7. **(non-blocker)** `register.py:1018` excludes activist where `:472` /
   `:1354` / `market.py:373/498` include it. Fix as part of canonical
   sweep, or as a one-line standalone PR (CL-2)?
8. **(non-blocker)** ECH adds value buckets that hv2 doesn't have
   (`market_maker` covers ~$7T of `hedge_fund`-classified hv2 AUM via 5
   CIKs; `unknown` covers 3,852 entities). When the canonical sweep ships,
   the React UI will see new badge values it doesn't render today —
   `getTypeStyle()` needs an `unknown` entry and a `market_maker` entry.
9. **(non-blocker)** Mixed-bucket sub-flagging — introduce
   `is_universal_bank` (or similar) for the ~30 wirehouses dominating
   `mixed`? Or keep the bucket monolithic?
10. **(non-blocker)** 19 deprecated entities (closed 2026-04-17) still
    receive fund rollups ($68.7B). Cleanup PR (CL-7), or fold into the
    bridge fix (CP-4)?
11. **(non-blocker)** ROADMAP "18 read sites" reconciliation — true count
    is 18 user-visible read points OR ~25 logical Python sites OR ~37
    total touch points if Datasette + React are included. Update
    ROADMAP to the chosen number once CP-5 scope locks.

---

## 13. Verification

```bash
# Read-only constraint on every helper:
grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b' \
    scripts/oneoff/institution_scoping_*.py
# 9 matches — all docstrings/comments. No DDL/DML executes.

# Helpers (worktree-relative):
ls scripts/oneoff/institution_scoping_*.py
# 16 helpers, all idempotent and read_only=True.
```

## 14. Cross-references

Phase partials (each agent's full data tables + samples):
- `docs/findings/institution_scoping_partial_1a_5.md` — Phase 1A + 5 (foreground agent)
- `docs/findings/institution_scoping_phase_1A_5.md` — Phase 1A + 5 (parallel background agent — duplicate run, retained for triangulation)
- `docs/findings/institution_scoping_partial_1b_1.5.md` — Phase 1B + 1.5 (foreground agent)
- `docs/findings/institution_scoping_phase_1B_15.md` — Phase 1B + 1.5 (parallel background agent — duplicate run)
- `docs/findings/institution_scoping_partial_2_3.md` — Phase 2 + 3
- `docs/findings/institution_scoping_partial_4_6.md` — Phase 4 + 6

ROADMAP item: `parent-level-display-canonical-reads` (P2, surfaced
2026-05-01 PR-1d follow-up). This investigation produces the manifest +
PR plan that item refers to. The ROADMAP item itself stays as the
tracking anchor; PR drafting can begin from §10 above.

Decision D4 (PR-1c precedence rule for managers without ECH row) remains
open. See open question #4.
