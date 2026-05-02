# fund-unknown-attribution: closing the unknown bucket end-to-end

**Date:** 2026-05-01
**Branch:** `fund-unknown-attribution`
**Mode:** read-only audit. Zero `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE` issued.
**Helpers:** `scripts/oneoff/audit_unknown_*.py` (verified write-free via grep on SQL keywords).

---

## Executive summary

**Layer 1 — `unknown` display bucket:** the entire `unknown` display bucket
collapses to a single `series_id='UNKNOWN'` literal: 3,184 rows / $10.025B /
8 distinct `(fund_cik, fund_name)` pairs. Cohorts B/C/D from the brief are
**empty** — PR #245 cleanly attributed everything else. All 8 pairs reattribute
to existing `fund_universe` series with already-set canonical strategies; no
NONE matches.

**Layer 2 — PR #245 backfill re-validation:** of 301 funds in
`strategy_source='orphan_backfill_2026Q2'`, **296 PASS_ALL** under three lenses
(name pattern, holdings shape, snapshot consistency). Of the 5 flags: 3 are
false positives (active-signal name keyword overruled by bond holdings shape
and snapshot agreement), 1 is the known intentional Blackstone override, and
**1 is a genuine reclassification candidate** (Rareview 2x Bull
Cryptocurrency & Precious Metals ETF: classifier order says `passive`, current
label is `excluded`).

**Surprises (top 3):**

1. The "unknown" bucket is much narrower than the brief assumed. Cohort B
   (Calamos / Eaton Vance Tax-Advantaged variants) and Cohort C (the ~96-row
   "N/A" entries) collapse into Cohort A: PR #245 already created
   `fund_universe` rows for these series, but the holdings rows were never
   re-stamped from the legacy `series_id='UNKNOWN'` literal.
2. 5 of the 8 (cik, fund_name) pairs in the UNKNOWN literal **coexist** with
   their proper `SYN_{cik}` companion as `is_latest=TRUE`. The Apr-3 legacy
   loader stamped `series_id='UNKNOWN'`; the Apr-15 v2 loader wrote real
   `SYN_*` companions but did not flip `is_latest` on the legacy rows. This
   is a separate data-integrity gap upstream of fund-strategy display.
3. Backfilled fund_universe rows have `total_net_assets IS NULL` for all
   301 entries — the orphan_backfill flow populated `fund_strategy` but not
   the AUM / equity-pct columns. Not a strategy-classification issue, but a
   minor data-completeness gap that surfaces here.

---

## Layer 1 — display surface map and cohort attribution

### 1.1 Code paths that emit `'unknown'` for fund_strategy display

The single source of truth is `_fund_type_label()` at
[scripts/queries/common.py:308](scripts/queries/common.py:308). It maps
canonical → display, with the implicit/None bucket falling through to
`'unknown'`:

```python
def _fund_type_label(fund_strategy):
    if fund_strategy in ACTIVE_FUND_STRATEGIES:   return 'active'
    if fund_strategy == 'passive':                return 'passive'
    if fund_strategy == 'bond_or_other':          return 'bond'
    if fund_strategy in ('excluded','final_filing'): return 'excluded'
    return 'unknown'
```

All seven query modules call this function: `fund.py`, `cross.py`, `market.py`,
`register.py`, `trend.py` (callers verified by grep). The `cross.py` 3-way
SQL CASE arms at [scripts/queries/cross.py:439](scripts/queries/cross.py:439)
and [scripts/queries/cross.py:689](scripts/queries/cross.py:689) emit literal
`NULL` (not `'unknown'`) for the same gap; the React frontend treats
`is_active === null` as the "unknown" bucket via strict-equality filtering.

Other `'unknown'` literals in the codebase (`register.py:54,127,235`, etc.)
fall back on `manager_type`, not `fund_strategy`, and are out of scope here.
The frontend `typeConfig.ts:31` fallback labels an empty `type` as `'unknown'`
but this only fires when `_fund_type_label()` already returned 'unknown'
upstream. **No surprise paths.**

### 1.2 Master inventory

`fund_universe` rows with `fund_strategy IS NULL`: **0**. The unknown bucket
comes entirely from `fund_holdings_v2 (is_latest=TRUE)` rows that have no
matching `fund_universe` series.

| metric | value |
|---|---|
| `fund_universe` rows | 13,924 |
| `fund_universe` rows with NULL strategy | 0 |
| Distinct orphan series (no fund_universe match) | 1 |
| Orphan rows (is_latest) | 3,184 |
| Orphan AUM | $10.025B |

The single orphan series is the literal `series_id='UNKNOWN'`.

### 1.3 Cohort partition

| cohort | description | rows | AUM | (cik, fund_name) pairs |
|---|---|---:|---:|---:|
| A | `series_id='UNKNOWN'` literal | 3,184 | $10.025B | 8 |
| B | named SKIP-list (Calamos, Eaton Vance Tax-Adv, etc.) | 0 | $0 | 0 |
| C | "N/A" cohort | 0 | $0 | 0 (folded into A) |
| D | anything else | 0 | $0 | 0 |

**Note on Cohort B/C dissolution.** The brief expected Calamos and Eaton Vance
Tax-Advantaged variants to surface as separate orphan series. They do not.
PR #245 inserted `fund_universe` rows for the SYN_-keyed equivalents
(`SYN_0001285650` Calamos, `SYN_0001253327` Eaton Vance Tax-Advantaged
Dividend Income), so the **fund_universe layer is complete for these names**.
The legacy holdings rows still tagged `series_id='UNKNOWN'` are the only
remaining attribution gap, and they fall under Cohort A. Cohort C "N/A" rows
also collapse into A as the single `(cik=0000002230, fund_name='N/A')` pair.

### 1.4 Cohort A reattribution

Per `audit_unknown_cohortA.py`, all 8 (cik, fund_name) pairs map cleanly:

| confidence | pairs | rows | AUM |
|---|---:|---:|---:|
| HIGH (exact name+CIK in fund_universe) | 6 | 2,738 | $5.283B |
| MEDIUM (token-set fuzzy >= 0.6 + CIK) | 1 | 350 | $1.752B |
| LOW (single real series under CIK) | 1 | 96 | $2.989B |
| NONE | 0 | 0 | $0 |

Per-pair detail:

| cik | fund_name | rows | AUM | conf | target series_id | target strategy |
|---|---|---:|---:|---|---|---|
| 0000002230 | N/A | 96 | $2.989B | LOW | `SYN_0000002230` (Adams Diversified Equity Fund, Inc.) | active |
| 0001253327 | Eaton Vance Tax-Advantaged Dividend Income Fund | 157 | $2.864B | HIGH | `SYN_0001253327` | balanced |
| 0001230869 | Asa Gold & Precious Metals Ltd | 350 | $1.752B | MEDIUM | `SYN_0001230869` (ASA Gold and Precious Metals LTD Fund) | active |
| 0001709406 | AIP Alternative Lending Fund P | 2 | $1.018B | HIGH | `SYN_0001709406` | bond_or_other |
| 0001995940 | AMG Pantheon Credit Solutions Fund | 33 | $0.689B | HIGH | `SYN_0001995940` | bond_or_other |
| 0001285650 | Calamos Global Total Return Fund | 1,412 | $0.325B | HIGH (case-different) | `SYN_0001285650` | balanced |
| 0001400897 | NXG Cushing Midstream Energy Fund | 43 | $0.258B | HIGH | `SYN_0001400897` | active |
| 0000826020 | Saba Capital Income & Opportunities Fund | 1,091 | $0.129B | HIGH | `SYN_0000826020` | balanced |

### 1.4a Stale-loader root cause

| pair | stale UNKNOWN rows (loaded ~2026-04-03) | live SYN_ rows (loaded ~2026-04-15) | both is_latest=TRUE? |
|---|---:|---:|---|
| Adams Diversified (cik=2230, name='N/A') | 96 | 0 | only stale |
| Eaton Vance Tax-Advantaged Div Income | 157 | 311 | **yes** |
| Asa Gold & Precious Metals Ltd | 350 | 0 | only stale |
| AIP Alternative Lending Fund P | 2 | 1 | **yes** |
| AMG Pantheon Credit Solutions Fund | 33 | 77 | **yes** |
| Calamos Global Total Return Fund | 1,412 | 0 | only stale |
| NXG Cushing Midstream Energy Fund | 43 | 46 | **yes** |
| Saba Capital Income & Opportunities Fund | 1,091 | 2,185 | **yes** |

**Mechanism.** The legacy loader (Apr 3, 2026) wrote rows with
`series_id='UNKNOWN'` whenever the `<seriesId>` element was missing or the
fund parse fell into the fallback path. The DERA Session-2 / `fetch_nport_v2`
loader (Apr 15, 2026, see commit `e868772`) wrote authoritative rows with
real `SYN_{cik}` series ids but did **not** flip `is_latest=FALSE` on the
legacy rows for the same `(cik, accession_number)`. Result: 5 of 8 pairs have
both versions live; 3 of 8 have only the stale UNKNOWN version (the v2 loader
either skipped or did not yet cover those fund/quarter combinations).

### 1.5 / 1.6 — Cohort B/C/D classification (no-op)

Cohorts B, C, D are empty. No additional per-fund classification work needed
under Layer 1 beyond Cohort A. The named items the brief flagged for
per-fund classification (Calamos Global Total Return → 'balanced',
Eaton Vance Tax-Adv Div Income → 'balanced', NXG Cushing Midstream → 'active',
Saba Capital Income & Opportunities → 'balanced') already have correct
canonical strategies in `fund_universe`; the only outstanding work is to
re-stamp the holdings rows from legacy `'UNKNOWN'` to the SYN_ keys.

---

## Layer 2 — PR #245 backfill re-validation

### 2.1 Inventory

301 funds total, $0 AUM (none of these rows have `total_net_assets`
populated — separate data-completeness gap). All `last_updated` and
`strategy_fetched_at` set to 2026-05-01 23:58:12 (PR #245 landed today).

| canonical strategy | n |
|---|---:|
| excluded | 136 |
| bond_or_other | 133 |
| passive | 25 |
| active | 6 |
| multi_asset | 1 (Blackstone override) |
| balanced | 0 |
| final_filing | 0 |

### 2.2 Three-lens verdict

Lens contracts (mirroring `classify_fund()` at `nport_parsers.py:153`):

- **Lens A — name pattern.** `INDEX_PATTERNS` match → expect `passive`.
  Else `EXCLUDE_PATTERNS` match → expect `excluded`. Else `ACTIVE_SIGNAL`
  match (income/municipal/closed-end/interval/BDC/CEF/opportunities/hedge/
  alpha/long-short/dividend-growth) → expect a member of
  `ACTIVE_FUND_STRATEGIES`, with a bond carve-out for fixed-income tokens.
- **Lens B — holdings shape.** `>=90% equity → active`; `60–90% → balanced`;
  `30–60% → multi_asset`; `<30% → bond_or_other`. ±10pp slack at boundaries.
  Skipped when strategy is name-driven (`passive`/`excluded`) — those
  short-circuit before the shape check in the classifier.
- **Lens C — snapshot.** Value-weighted `fund_strategy_at_filing` distribution
  must agree with canonical strategy at ≥ 99.5% support.

| verdict | n | note |
|---|---:|---|
| PASS_ALL (no flag in any lens) | 296 |  |
| FLAG_ACTIVE_NAME (Lens A only) | 3 | name has active keyword but holdings + snapshot agree on bond_or_other → false positive |
| FLAG_PASSIVE_NAME (Lens A only) | 1 | Rareview 2x — real reclass candidate |
| FLAG_SHAPE + FLAG_SNAPSHOT_DIVERGE (Lens B + C) | 1 | Blackstone — known intentional override |

### 2.3 Per-fund recommendations

| series_id | fund_name | current | recommendation | confidence | rationale |
|---|---|---|---|---|---|
| `S000045538` | Blackstone Alternative Multi-Strategy Fund | multi_asset | KEEP_BACKFILL_OVERRIDE | HIGH | Documented PR #245 override. Snapshot says `bond_or_other` (100%) and shape (eq=19.8%, bd=12.7%) supports `bond_or_other`, but the canonical override to `multi_asset` is intentional given the fund's hedge-style multi-strategy mandate. |
| `S000090077` | Rareview 2x Bull Cryptocurrency & Precious Metals ETF | excluded | **RECLASSIFY_TO_PASSIVE** | MEDIUM | Name matches `INDEX_PATTERNS` (`\d+x` leveraged-ETF token from PR-2 additions). Per `classify_fund()` order, INDEX precedes EXCLUDE — should be `passive`. Snapshot has only 4 holdings rows with effectively zero net AUM ($-281); fund is launch-quarter-only. Stale snapshot was generated under pre-PR-2 classifier. Reclass aligns with the rest of the leveraged-ETF universe (most of which already shows `passive` post-PR-2). Material impact: minimal (no AUM). |
| `S000029761` | Global Macro Absolute Return Advantage Portfolio | bond_or_other | KEEP_BACKFILL | HIGH | Lens A flag is false positive: shape and snapshot both confirm `bond_or_other`. Eaton Vance global-macro absolute-return funds are predominantly fixed-income. |
| `S000027417` | Global Opportunities Portfolio | bond_or_other | KEEP_BACKFILL | HIGH | Lens A flag is false positive: shape (bond-dominated) and snapshot both agree. Eaton Vance Global Opportunities Portfolio is a global high-yield bond fund. |
| `S000005235` | HIGH INCOME OPPORTUNITIES PORTFOLIO | bond_or_other | KEEP_BACKFILL | HIGH | Lens A flag is false positive: "high income" carve-out should suppress active-signal; shape and snapshot agree on bond_or_other. |

The remaining 296 funds carry **KEEP_BACKFILL** at HIGH confidence.

---

## Decision matrix

| action | scope | execution path | risk | est. impact |
|---|---|---|---|---|
| **A1.** Re-stamp 3 stale-only UNKNOWN pairs (Adams "N/A" 96 rows, Asa Gold 350 rows, Calamos 1,412 rows) onto their SYN_ series. | 1,858 rows / $5.07B | one-shot UPDATE on `fund_holdings_v2` keyed by `(fund_cik, fund_name, series_id='UNKNOWN')`, setting `series_id := SYN_{cik}` and `fund_name := canonical fund_universe name`. Wrap as a staging-workflow apply per the staging convention. | LOW — `fund_universe` rows already exist; no new entities. | Removes $5.07B from "unknown" display bucket. |
| **A2.** Flip `is_latest=FALSE` on 5 stale-redundant UNKNOWN pairs (Eaton Vance, AIP, AMG, NXG, Saba) — totals 1,326 rows / $4.96B. | 1,326 rows | UPDATE setting `is_latest=FALSE` for `series_id='UNKNOWN'` AND a SYN_ companion exists for the same `(fund_cik, fund_name, accession_number)`. | LOW — companions already authoritative under the v2 loader. | Removes $4.96B from "unknown" display bucket; restores expected single-row-per-filing invariant. |
| **A3.** Investigate why the v2 loader did not write SYN_ companions for Adams "N/A", Asa Gold, and Calamos. | 3 funds | Inspect `scripts/pipeline/load_nport.py` and `fetch_nport_v2.py` traces for the relevant accession numbers. Likely the legacy loader tagged a degenerate case the v2 path skipped. | LOW (read-only investigation). | Confirms whether the data is actually present in raw filings or the funds themselves dropped 13F/N-PORT. |
| **B1.** Reclassify `S000090077` (Rareview 2x Bull) from `excluded` → `passive`. | 1 fund | One-row UPDATE on `fund_universe.fund_strategy`. | NIL — fund has effectively zero AUM. | Aligns with classifier order and rest of leveraged-ETF universe. Sets up cleaner re-derivation when next N-PORT lands. |
| **B2.** Backfill `total_net_assets`, `total_holdings_count`, `equity_pct`, `top10_concentration` for the 301 orphan_backfill funds from the latest holdings. | 301 funds | Recompute and UPDATE from `fund_holdings_v2 (is_latest=TRUE)`. | LOW — purely derived columns. | Removes the AUM-NULL gap noted in 2.1. |

All five actions are read-write (out of scope for this audit). They should be
queued as separate staging-workflow applies in subsequent PRs.

---

## Open questions (chat decision)

1. **Action A3 — the 3 stale-only pairs.** Adams Diversified Equity Fund, Asa
   Gold & Precious Metals, and Calamos Global Total Return have only the
   legacy UNKNOWN rows live. Should we (a) rebackfill via the v2 loader from
   the original raw filings, or (b) do an in-place series_id rewrite (A1)?
   Option (b) is faster and already validated by the existing fund_universe
   rows; option (a) gives end-to-end provenance through the v2 path.
2. **Action B1 — Rareview 2x.** Strict reading of the classifier says
   `passive`, but the fund is functionally inactive (4 holdings, ~$0 net).
   Worth the one-row rewrite, or wait for the next non-empty filing and let
   the snapshot pipeline fix it organically?
3. **Action B2 — AUM backfill.** Should this happen in this thread, or is it
   already covered by an existing scheduled flow that hasn't yet recomputed
   for 2026-05-01-stamped rows?
4. **Larger fix — should the legacy `series_id='UNKNOWN'` literal be
   forbidden** by a CHECK constraint or a load-time guard once A1+A2 land?
   Right now the loader can still emit `'UNKNOWN'` if a `<seriesId>` element
   is missing. A guard at write time prevents this class of orphan from ever
   reappearing.

---

## Appendix — reproducibility

Helpers (all read-only; no SQL writes):

- [scripts/oneoff/audit_unknown_inventory.py](scripts/oneoff/audit_unknown_inventory.py) — Phase 1.2 master inventory, writes `_unknown_orphans.csv`.
- [scripts/oneoff/audit_unknown_cohortA.py](scripts/oneoff/audit_unknown_cohortA.py) — Phase 1.4 reattribution, writes `_unknown_cohortA_attribution.csv`.
- [scripts/oneoff/audit_unknown_backfill_validation.py](scripts/oneoff/audit_unknown_backfill_validation.py) — Phase 2.1–2.3 three-lens validation, writes `_unknown_backfill_validation.csv`.

DB: `data/13f.duckdb` (prod), opened `read_only=True`. No app-lock contention
encountered during the run.
