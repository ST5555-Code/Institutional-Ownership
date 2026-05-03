# Institution Scoping — Phases 2 + 3 (READ-ONLY investigation)

**Worktree:** `pensive-montalcini-650089`
**Date:** 2026-05-02
**Source DB:** `data/13f.duckdb` (read-only)
**Helpers (idempotent, read-only):**
- `scripts/oneoff/institution_scoping_phase2_typemerge.py`
- `scripts/oneoff/institution_scoping_phase2_market_makers.py`
- `scripts/oneoff/institution_scoping_phase2_is_passive.py`
- `scripts/oneoff/institution_scoping_phase2_swf_pension_endowment.py`
- `scripts/oneoff/institution_scoping_phase2_mixed_unknown.py`
- `scripts/oneoff/institution_scoping_phase3_migration.py`

> All AUM figures from `holdings_v2 WHERE is_latest = TRUE`.
> Identifier `entity_identifiers.identifier_type = 'cik'` (lowercase) per repo convention.
> SCD open rows use `valid_to = DATE '9999-12-31'`.

---

## Phase 2.1 — Pre-decided merge audit

### Pair A: `private_equity` + `venture_capital`

| metric | private_equity | venture_capital | combined |
|---|---:|---:|---:|
| distinct CIKs | 112 | 31 | 143 |
| holdings_v2 rows (is_latest) | 75,214 | 967 | 76,181 |
| AUM ($B) | 1,191.43 | 23.89 | 1,215.32 |

**Top 10 `private_equity` by AUM ($B):** Mariner LLC 290.8, Brookfield Corp 242.0, Barrow Hanley Mewhinney & Strauss 118.7, Thoma Bravo 48.4, Partners Value Investments 39.8, BC Partners PE 34.3, Dynasty Wealth Management 29.5, Carlyle Group 26.7, Eventide Asset Management 23.2, KKR 21.5.

**Top 10 `venture_capital` by AUM ($B):** a16z Perennial 4.8, CVC Mgmt Holdings II 2.8, Battery Mgmt 2.4, Lightspeed 2.2, ARCH Venture 1.7, Accel Leaders 4 1.3, 5AM 1.1, Redpoint 0.8, Peak XV 0.7, Pivotal bioVenture 0.7.

**Debatable (PE label, VC name OR vice versa):**
- Bain Capital Venture Investors LLC (CIK 0001309469) — labeled `private_equity` in holdings_v2; managers.strategy_type=`venture_capital`. AUM 0.69B. **Resolve before merge.**
- IDG China Venture Capital Fund IV / V Associates LP — labeled `private_equity` despite "Venture Capital" in name. AUM 1.5B / 0.5B. Likely fine post-merge but flag.
- Mariner LLC ($290.8B) is by far the largest PE-tagged manager — name resembles MFO/wealth-management; worth eyeball before lumping into PE.
- Barrow Hanley ($118.7B) — listed as PE but it's a long-only equity manager. **Misclass; not really PE.**
- Dynasty Wealth Management ($29.5B) — wealth platform, not PE. **Misclass.**

**Hybrid name scan (top examples):**
- "Bain Capital Venture Investors LLC", "Sapphire Ventures LLC", "Forerunner Ventures Mgmt" — all live in PE bucket today; would be VC if reassigned.
- Only one row in VC bucket has PE-flavored name: Accel Growth Fund V (0.44B).

**Recommendation:** PE+VC merge is structurally fine — but post-merge, the resulting bucket carries non-PE noise from the long-only/wealth misclasses (Mariner, Barrow Hanley, Dynasty). Recommend a follow-up triage pass *before* the merge so these get re-routed to `mixed`/`active`/`wealth_management` rather than absorbed into the new private-capital bucket.

---

### Pair B: `wealth_management` + `family_office`

| metric | wealth_management | family_office | combined |
|---|---:|---:|---:|
| distinct CIKs | 371 | 49 | 420 |
| holdings_v2 rows (is_latest) | 1,306,253 | 36,950 | 1,343,203 |
| AUM ($B) | 10,383.20 | 66.52 | 10,449.72 |

**Top 10 `wealth_management` ($B):** LPL Financial 1,266.3, Raymond James 1,193.9, PNC 694.2, Jones Financial (Edward Jones) 554.4, Creative Planning 494.0, Stifel 417.6, SEI 358.3, Russell 331.2, Corient Private Wealth 306.6, Truist 279.8.

**Top 10 `family_office` ($B):** Callan FO 12.3, Stokes FO 4.0, Fusion Family Wealth 3.6, Mosaic Family Wealth Partners 3.3, CVA FO 3.0, Biltmore FO 2.6, Tarbox FO 2.6, FRG Family Wealth Advisors 2.4, Noble Family Wealth 1.7, RPg Family Wealth 1.6.

**Hybrid name scan:**
- WM bucket holds many "Trust" entities ($170B+ across 15 names — Boston Trust Walden, Greenleaf Trust, Blue Trust, GenTrust, Spinnaker Trust, etc.). These are legitimately bank-trust-style WM, not single-family offices — leave in WM.
- Many `family_office` rows have "Family Wealth" in name (FRG, Noble, Mosaic, RPg, Strategic, Morton Brown, Brady, Omnia, Family Wealth Partners). Boundary between WM and FO is blurry; merging absorbs the issue.

**Recommendation:** Clean merge. FO is only $66.5B (0.6% of WM AUM) and is genuinely a sub-flavor of WM in this dataset (almost all are RIAs serving HNW families). Merge as-is.

**MIGRATION DEPENDENCY:** `family_office` is currently a `manager_type` value; it is **not** a value in `entity_classification_history.classification`. WM+FO merge requires the family_office classification to first land in `entity_classification_history`. See Phase 3.1.

---

### Pair C: `hedge_fund` + `multi_strategy`

| metric | hedge_fund | multi_strategy | combined |
|---|---:|---:|---:|
| distinct CIKs | 1,017 | 2 | 1,019 |
| holdings_v2 rows (is_latest) | 550,373 | 553 | 550,926 |
| AUM ($B) | 8,936.23 | 11.70 | 8,947.94 |

**Top 10 `hedge_fund` ($B):** Arrowstreet 594.1, Marshall Wace 376.0, Boston Partners 366.7, GQG Partners 258.9, Adage Capital 242.6, TCI 200.4, Tudor Investment 192.9, First Manhattan 145.7, Capital Fund Management 145.1, Twin Tree Mgmt 142.3.

**`multi_strategy` (full list — only 2 firms!):**
- Adams Diversified Equity Fund (CIK 0000002230) — $11.28B. **This is a closed-end fund, NOT a multi-strategy hedge fund.**
- Diversified Management Inc (CIK 0000922372) — $0.43B. Likely also CEF / non-HF.

**Surprising finding:** the `multi_strategy` manager_type bucket in production is essentially mislabeled. Both incumbents are diversified-equity vehicles (CEFs), not multi-manager / pod-shop hedge funds (Citadel, Millennium, Point72, ExodusPoint, etc., live in `hedge_fund` already).

Hybrid name scan returned only **Brummer Multi-Strategy AB** ($0.02B) inside `hedge_fund` — i.e. Brummer correctly stays in HF post-merge.

**Recommendation:** The merge is essentially a relabel of 2 CIKs / $11.7B. It's almost a no-op from a HF perspective. **Before the merge runs**, consider whether to instead:
1. Send Adams Diversified to `closed_end_fund` / `mixed` (more accurate), and
2. Drop `multi_strategy` as a manager_type value altogether.

If pursuing the pre-decided merge as-is, do the migration to entity_classification_history first (see Phase 3.2).

---

## Phase 2.2 — `market_maker` backfill

**Total candidates matching MM-name patterns (Citadel Securities, Virtu, Susquehanna, Jane Street, IMC, GTS, Hudson River, Two Sigma Securities, Flow Traders, etc.):** 30 CIKs / **$8,240.68B AUM**.

| current `manager_type` of candidates | count |
|---|---:|
| quantitative | 9 |
| mixed | 11 |
| active | 6 |
| family_office | 1 |
| hedge_fund | 1 |
| strategic | 1 |
| wealth_management | 1 |

**Top 10 candidates ($B):**

| cik | manager_name | h_manager_type | current `entity_current.classification` |
|---|---|---|---|
| 0001446194 | Susquehanna International Group, LLP | mixed | **market_maker** ✓ |
| 0001595888 | Jane Street Group, LLC | quantitative | **market_maker** ✓ |
| 0001452861 | IMC-Chicago, LLC | quantitative | **market_maker** ✓ |
| 0001859606 | Optiver Holding B.V. | quantitative | **market_maker** ✓ |
| 0001632341 | Belvedere Trading LLC | quantitative | hedge_fund |
| 0000927337 | Wolverine Trading, LLC | quantitative | unknown |
| 0001389958 | Peak6 LLC | quantitative | hedge_fund |
| 0001529090 | Akuna Securities LLC | quantitative | hedge_fund |
| 0001455915 | Old Mission Capital LLC | active | active |
| 0001444949 | Susquehanna Advisors Group, Inc. | mixed | mixed |

**Other notable mismatches:**
- `Tower Research Capital LLC` ($14.8B) — h_manager_type = `wealth_management` (clearly wrong); entity_current = `wealth_management`.
- `XTX Topco Ltd` ($10.1B) — `mixed` / `mixed`.
- `Flow Traders U.S. LLC` ($0.01B) — already `market_maker` in entity_current despite tiny 13F AUM (most flow is non-13F).
- `Two Sigma Securities, LLC` ($2.9B) — `quantitative` / `market_maker`. Note: this is the *broker-dealer* arm; Two Sigma Investments (the HF) is separate and stays in HF.

**False positives surfaced by name pattern (DO NOT auto-flip):**
- "Virtus" family (Virtus Investment Advisers, Virtus Wealth Solutions, Virtus Family Office, Virtus Fixed Income, Virtus Advisers, Virtue Asset/Capital Management) — these are traditional asset managers; matched only because regex caught "virtu" prefix. **Exclude before backfill.**
- `SkyKnight Capital, L.P.` — caught by "rings" via "five rings" pattern? Actually caught via none of the obvious tokens; debug this if pattern set is reused.

Currently classified as `market_maker` in `entity_current`: **23**. Backfill candidates to add: ~**12** clean MM CIKs after dropping Virtus / SkyKnight false positives (Belvedere, Wolverine, Peak6, Akuna, Tower Research, XTX, Headlands, Old Mission, GTS Securities, DRW Securities, Susquehanna sub-units, Global IMC).

**Recommendation — defer:** This is a separate cleanup, not a prerequisite for the type merges. Treat as a P3/P4 task: build a proper allowlist (registered as broker-dealer with FINRA, principal trading > X% of revenue, etc.) before running entity_classification_history inserts. Pure name-regex backfill is too noisy.

---

## Phase 2.3 — `is_passive` boolean redundancy

### Read-site grep summary

51 hits across `scripts/`, `web/`, `app.py`. Categories:

**Schema definitions (5 hits) — `is_passive BOOLEAN` column declarations:**
- `scripts/load_13f_v2.py:135, :216`
- `scripts/build_summaries.py:139`
- `scripts/migrations/004_summary_by_parent_rollup_type.py:155`

**Read sites in production code:**
- `scripts/pipeline/shared.py:256` — pulls (manager_type, is_passive, is_activist) tuple
- `scripts/build_managers.py:587, :629, :644, :671` — coalesce-merge with managers.is_passive (`COALESCE(m.is_passive, h.is_passive)`)
- `scripts/build_summaries.py:233, :260, :281` — `BOOL_OR(h.is_passive) AS is_passive` aggregation in summary tables
- `scripts/load_13f_v2.py:494, :522` — passes `is_passive` through to holdings_v2 inserts
- `scripts/pipeline/nport_parsers.py:163-164` — `is_passive_name = INDEX_PATTERNS.search(series_name)` (writes, not reads, but flags here for completeness)
- `scripts/oneoff/apply_series_triage.py:272-306, :341` — `_classification_from_passive(is_passive_raw)` — reads worksheet column to derive classification. **This is one of the few real reads.**
- `scripts/oneoff/export_new_entity_worksheet.py:221, :240` — column passthrough on export; cosmetic.
- `scripts/retired/unify_positions.py:51, :91` — retired, ignore.

**No web/app.py hits.** No SQL queries in `scripts/queries/` filter on `is_passive`.

### DB cross-validation

`is_passive=TRUE` rows (latest):

| is_passive | manager_type | CIKs | rows | AUM ($B) |
|---|---|---:|---:|---:|
| TRUE | passive | 45 | 737,851 | 81,647.4 |
| TRUE | family_office | 1 | 495 | 0.6 |
| FALSE | (every other type) | … | … | … |

**Divergence A — `is_passive=TRUE` but `manager_type<>'passive'`:** exactly 1 firm — `Tred Avon Family Wealth, LLC` (0002094435), $0.6B, manager_type='family_office'. Almost certainly a data entry error; ignore.

**Divergence B — `manager_type='passive'` but `is_passive` not TRUE:** 8 firms, $84.0B combined.
- Exchange Traded Concepts $38.9B
- Ossiam $28.8B
- Matson Money $11.8B
- Eagle Strategies $2.8B
- Passive Capital Management $1.3B (literally has "Passive" in name!)
- Swmg, AFT Forsyth & Sober, Hatteras (each <$1.3B)

These are **real divergences** — the boolean and manager_type disagree. They should converge to one source of truth.

### Recommendation

`is_passive` is **functionally redundant** with `manager_type='passive'`:
- 100% of CIKs with `manager_type='passive'` either have `is_passive=TRUE` (45 of 53) or have a divergence bug (8 of 53 — needs reconciliation).
- The boolean is set in only 4 places in live code: `build_managers.py` (coalesce merge), `build_summaries.py` (BOOL_OR aggregation), `load_13f_v2.py` (insert passthrough), and `apply_series_triage.py` (worksheet-driven classification reverse map).

**Drop plan:**
1. Reconcile the 8 divergent passive-but-not-`is_passive=TRUE` rows (manual override or recompute).
2. Replace `is_passive` reads in `build_summaries.py` and `build_managers.py` with `manager_type = 'passive'` derivations.
3. Refactor `apply_series_triage.py::_classification_from_passive` to read `manager_type` directly.
4. Drop `is_passive` column from holdings_v2 + managers + summary tables (separate migration).

Defer the column drop until after the type-merge work lands; until then, treat `is_passive` as a derived projection.

---

## Phase 2.4 — SWF / pension_insurance / endowment_foundation (keep separate)

| type | CIKs | rows | AUM ($B) |
|---|---:|---:|---:|
| SWF | 13 | 16,915 | 540.22 |
| pension_insurance | 136 | 289,545 | 6,639.46 |
| endowment_foundation | 67 | 10,430 | 693.36 |

**SWF (top 5):** Temasek 111.6, KLP Kapitalforvaltning 94.7, Public Investment Fund (Saudi PIF) 81.7, Forsta AP-Fonden 62.1, Mubadala 54.1.
**pension_insurance (top 5):** CalPERS 648.4, CPP Investment Board 511.9, National Pension Service (Korea) 483.7, State Farm Mutual Auto Insurance 469.3, Manulife 460.8.
**endowment_foundation (top 5):** Lilly Endowment 326.1, Gates Foundation Trust 161.5, Wellcome Trust 35.2, LGT Group Foundation 33.1, Japan Science & Tech Agency 23.9.

**Confirmation:** rationale holds. Each has a distinct mandate and regulatory profile:
- **SWF** — sovereign mandate, often large single positions, government-driven asset allocation.
- **pension_insurance** — long-duration liabilities, ALM-driven, mix of public/private pensions and life-insurance G/A. CalPERS/CPP/State Farm are not the same as endowments either.
- **endowment_foundation** — perpetual horizon, spending-rule driven, typically alternatives-heavy in non-13F books but the 13F slice is concentrated (Lilly Endowment alone is ~half the bucket).

Note: `pension_insurance` mixes public pensions + insurance G/A + private pensions. Future split (pension vs insurance) is a P3 nice-to-have but **not** in scope for this round.

**Keep separate. No changes.**

---

## Phase 2.5 — `mixed` and `unknown` buckets

### Distribution

| field | value | CIKs | rows | AUM ($B) |
|---|---|---:|---:|---:|
| holdings_v2.manager_type | `mixed` | 1,607 | 4,031,814 | **55,011.8** |
| holdings_v2.manager_type | NULL | 0 | 0 | 0 |
| holdings_v2.manager_type | `unknown` | 0 | 0 | 0 |
| holdings_v2.entity_type | `mixed` | 743 | 2,893,109 | **39,618.6** |
| holdings_v2.entity_type | NULL | 0 | 0 | 0 |
| entity_classification_history.classification | `unknown` (open rows) | 3,852 | — | — |

`mixed` is the **single biggest classification bucket by AUM** (~$55T at manager_type level, $40T at entity_type level). No NULL or 'unknown' rows in holdings_v2 itself — those have been backfilled. The 3,852 open `unknown` rows in `entity_classification_history` are the residual cohort awaiting MDM.

### What's in `mixed`?

Top-25 by AUM are dominated by **wirehouses, universal banks, and global custodians**:
- Morgan Stanley, JPMorgan, Bank of America, Goldman Sachs, UBS, RBC, BNY Mellon, Wells Fargo, Ameriprise, Franklin Resources, Deutsche Bank, BMO, Barclays, Citi, BNP, Sumitomo Mitsui Trust, HSBC, TD Asset Management, Citigroup, US Bancorp, Aberdeen, Macquarie, Toronto Dominion, Nomura, MUFG.
- One SWF in the bucket (Swiss National Bank — $649B; obviously belongs in SWF, currently entity_type='SWF' but manager_type='mixed' → **manager_type ≠ entity_type for top mixed firms**, see below).
- One MM-flavored firm (Susquehanna International — manager_type='mixed', entity_type='hedge_fund'; really a market_maker).

### The manager_type / entity_type divergence

The mixed bucket has a structural quirk: of the top-25 `manager_type='mixed'` firms, **9 have `entity_type` that disagrees** (active, hedge_fund, SWF, wealth_management). This means downstream consumers of these two columns can land at different classifications for the same firm.

### Recommended treatments for `mixed`

Treat `mixed` as **three sub-cohorts**:

| sub-cohort | description | size (rough) | treatment |
|---|---|---|---|
| **MEGA-BANKS** | Universal banks / wirehouses with multi-strategy 13F books | ~30 firms, $40T | Keep in `mixed` — accurate label; the 13F is genuinely a blended multi-strategy filing. Add a sub-flag `is_universal_bank` if downstream needs to peel them out. |
| **CONSERVATIVE-MIXED** | RIAs/banks where N-PORT coverage < 50% + active/passive split is genuinely unclear | ~1,400 firms, $14T | Keep in `mixed` per existing LOW_COV rule (per memory). |
| **MISCLASSED** | Single-strategy firms accidentally tagged mixed (e.g. Susquehanna Int'l / market_maker, Swiss National Bank / SWF) | ~10–30 firms, $0.5–1T | Triage into correct buckets. Many already correct in `entity_type` — the fix is to harmonize manager_type to entity_type. |

**Recommendation:** Don't change the `mixed` definition for the type-merge phase. Address the manager_type vs entity_type divergence separately as a "harmonize labels" task.

`unknown` cohort handling is the parallel agent's territory (per task assignment; they own Phases 4/5). Reference only.

---

## Phase 3 — Migration prerequisites

### 3.1 `family_office` migration

**Population in source tables:**

| source | distinct CIKs | rows | AUM ($B) |
|---|---:|---:|---:|
| holdings_v2 (manager_type='family_office', is_latest) | 49 | 36,950 | 66.52 |
| managers (strategy_type='family_office') | 51 | — | — |

**Cross-check vs `entity_classification_history` (open rows):**

| current entity_classification_history.classification | CIKs |
|---|---:|
| wealth_management | 39 |
| mixed | 7 |
| unknown | 2 |
| passive | 1 |

**All 49 holdings_v2 family_office CIKs already have `entity_id`.** None are unmapped. So the migration is purely an *update* of classification history, not a new-entity bootstrapping task.

**Conflict shape:** every family_office CIK has a pre-existing OPEN row in entity_classification_history with a non-`family_office` classification. The migration must close those rows (`valid_to = today-1`) and insert new `family_office` open rows.

**Source-of-truth note:** 3 conflicting rows already use `source='adv_strategy_inferred'` (newer ADV-derived classification, dated 2026-04-08). The other ~46 use `source='managers'` with `valid_from='2000-01-01'` (legacy seed). The newer source is more authoritative — but the manager_type='family_office' assignment in holdings_v2 is even fresher (presumably from the recent FO triage round).

**`entity_classification_history.classification` value space currently does NOT contain `family_office`.** Adding it does not require a schema change (column is plain VARCHAR), but downstream consumers (any CASE WHEN classification IN (…) clauses) need to be audited.

**Migration shape — pseudo-SQL (NOT YET EXECUTED):**

```sql
-- WOULD-RUN ONLY. Read-only investigation.
-- Step A: close existing open rows for family_office CIKs.
WITH fo_ents AS (
  SELECT DISTINCT ei.entity_id
  FROM entity_identifiers ei
  JOIN holdings_v2 h
    ON h.cik = ei.identifier_value
   AND h.is_latest = TRUE
   AND h.manager_type = 'family_office'
  WHERE ei.identifier_type = 'cik'
)
-- WOULD-RUN: UPDATE entity_classification_history
--   SET valid_to = CURRENT_DATE - INTERVAL 1 DAY
--   WHERE entity_id IN (SELECT entity_id FROM fo_ents)
--     AND valid_to = DATE '9999-12-31';

-- Step B: insert new family_office open rows.
-- WOULD-RUN: INSERT INTO entity_classification_history
--   (entity_id, classification, is_activist, confidence, source, is_inferred,
--    valid_from, valid_to, created_at)
--   SELECT entity_id, 'family_office', FALSE, 'high',
--          'migration_family_office_2026', FALSE,
--          CURRENT_DATE, DATE '9999-12-31', NOW()
--   FROM fo_ents;

-- Step C (optional): update managers.strategy_type to 'family_office'
--   for any of these 51 CIKs where it disagrees. 49 of 49 already match;
--   the 2 extra in managers (51-49) need a separate audit.
```

**Validation queries (run before promote):**
- All 49 holdings_v2 CIKs have entity_id (confirmed: yes, 0 unmapped).
- entities table has entity_type compatible with family_office (presumably 'institution'; verify).
- `entity_current` view recomputes after migration (recall: entity_current is a view per memory).

---

### 3.2 `multi_strategy` migration

**Population in source tables:**

| source | distinct CIKs | rows | AUM ($B) |
|---|---:|---:|---:|
| holdings_v2 (manager_type='multi_strategy', is_latest) | 2 | 553 | 11.70 |
| managers (strategy_type='multi_strategy') | 2 | — | — |

**The full universe is just 2 CIKs:**
- 0000002230 — Adams Diversified Equity Fund (CEF, $11.28B)
- 0000922372 — Diversified Management Inc ($0.43B)

**Cross-check vs `entity_classification_history`:**

| current open classification | CIKs |
|---|---:|
| hedge_fund | 2 |

Both are currently classified as `hedge_fund` in entity_classification_history.

**`entity_classification_history.classification` value space currently does NOT contain `multi_strategy`.**

**Critical observation:** the holdings_v2 manager_type='multi_strategy' bucket is *almost certainly mislabeled*. Adams Diversified is a CEF, not a multi-strategy hedge fund (Citadel/Millennium-style pod shop). Before the migration runs, decide whether to:

**Option A (faithful migration):** Move the 2 CIKs to `entity_classification_history.classification = 'multi_strategy'`, then run the HF+multi_strategy merge. Net result: 2 CIKs / $11.7B re-flow back into HF.

**Option B (recommended):** Skip the multi_strategy classification entirely. Re-classify Adams Diversified to `mixed` (or a new `closed_end_fund` bucket if scoped) and Diversified Management Inc per its actual strategy. Drop `multi_strategy` from manager_type / strategy_type altogether.

If Option A is chosen, migration shape is:

```sql
-- WOULD-RUN ONLY. Read-only investigation.
-- Step A: close existing open hedge_fund rows for these 2 entity_ids (2961, 7715).
-- WOULD-RUN: UPDATE entity_classification_history
--   SET valid_to = CURRENT_DATE - INTERVAL 1 DAY
--   WHERE entity_id IN (2961, 7715)
--     AND valid_to = DATE '9999-12-31';

-- Step B: insert multi_strategy rows.
-- WOULD-RUN: INSERT INTO entity_classification_history (...)
--   VALUES (2961, 'multi_strategy', FALSE, 'high',
--           'migration_multi_strategy_2026', FALSE,
--           CURRENT_DATE, DATE '9999-12-31', NOW()),
--          (7715, 'multi_strategy', FALSE, 'high',
--           'migration_multi_strategy_2026', FALSE,
--           CURRENT_DATE, DATE '9999-12-31', NOW());
```

### 3.3 Sequencing graph

```
                   ┌─────────────────────────────────────────────┐
                   │ existing entity_classification_history      │
                   │ schema (no change required — VARCHAR)       │
                   └───────────────┬─────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
    │ MIGRATION 3.1    │  │ MIGRATION 3.2    │  │ (Phase 5: drop   │
    │ family_office    │  │ multi_strategy   │  │  is_passive col) │
    │ (49 CIKs, $66B)  │  │ (2 CIKs, $12B)   │  │  — not blocking  │
    └────────┬─────────┘  └────────┬─────────┘  └──────────────────┘
             │                     │
             ▼                     ▼
    ┌──────────────────┐  ┌──────────────────┐
    │ MERGE B          │  │ MERGE C          │
    │ WM + family_off  │  │ HF + multi_strat │
    └──────────────────┘  └──────────────────┘

    ┌──────────────────┐
    │ MERGE A          │  (no migration prerequisite — both PE and
    │ PE + VC          │   VC already first-class manager_types)
    └──────────────────┘
```

**Sequencing rules:**
- Migrations 3.1 and 3.2 are **independent** and can run in parallel (different entity_ids, different classification values).
- Merge A (PE+VC) has **no migration prerequisite** — but recommend a triage pass first (see Phase 2.1 PE recommendation re: misclassed Mariner / Barrow Hanley / Dynasty before lumping into PE+VC).
- Merge B requires Migration 3.1.
- Merge C requires Migration 3.2 (or pivot to Option B per 3.2).
- Validation gate after each migration: `entity_current` view recomputes; row counts in `entity_classification_history` for the new classification value match the source `holdings_v2` CIK count.

---

## Open questions for product / Serge

1. **PE bucket cleanup before PE+VC merge?** Mariner LLC ($291B), Barrow Hanley ($119B), Dynasty Wealth ($30B) are misclassed as PE today. Do we triage them first or absorb them into PE+VC?
2. **HF + multi_strategy merge — Option A vs Option B?** Faithfully migrate 2 CEFs through `multi_strategy`, or kill the bucket entirely and re-route the 2 CIKs to `mixed` / `closed_end_fund`?
3. **`is_passive` drop — when?** Confirm sequencing relative to the type-merge work. Recommend: after merges land, since `build_summaries.py` and `build_managers.py` need refactor.
4. **Mega-bank `mixed` sub-flag?** Worth introducing `is_universal_bank` (or similar) for the ~30 wirehouses dominating the `mixed` bucket?
5. **Market-maker backfill scope.** Defer to a separate cleanup pass with a stricter allowlist (FINRA broker-dealer registration), not name-regex.
6. **manager_type ↔ entity_type harmonization.** Several top-25 firms have disagreeing values (Susquehanna Int'l, Swiss National Bank, Northwestern Mutual, etc.). Separate task or in scope?

---

## Verification

```bash
# All helpers READ-ONLY (verified via grep):
grep -niE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b' \
  scripts/oneoff/institution_scoping_phase2_*.py \
  scripts/oneoff/institution_scoping_phase3_*.py
# All hits: comments / heuristic-string-literals inside is_passive grep classifier.
# No real SQL writes. Connection opened with read_only=True.
```
