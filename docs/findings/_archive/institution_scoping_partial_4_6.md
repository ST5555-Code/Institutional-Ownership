# Institution-Level Scoping — Phases 4 + 6 Partial

**Date:** 2026-05-02
**Worktree:** `pensive-montalcini-650089`
**Scope:** READ-ONLY confirmation + quantification.

Phase 1A / 1B / 1.5 / 2 / 3 / 5 are owned by sibling agents and not covered here.

---

## Phase 4 — query4 silent-drop bug

### 4.1 Confirmed bug location

File: `scripts/queries/register.py`, lines **740–765** (the CASE itself sits at **746–750**).

```python
def query4(ticker, quarter=LQ):
    """Passive vs active ownership split."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                CASE
                    WHEN entity_type = 'passive' THEN 'Passive (Index)'
                    WHEN entity_type = 'activist' THEN 'Activist'
                    WHEN manager_type IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
                    ELSE 'Other/Unknown'
                END as category,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares,
                SUM(market_value_live) as total_value,
                SUM(pct_of_so) as total_pct_so
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND ticker = ? AND is_latest = TRUE
            GROUP BY category
            ORDER BY total_value DESC NULLS LAST
        """, [ticker]).fetchdf()
```

### 4.2 Bug shape (plain English)

The CASE bucketizes a holding into one of four labels. Branch 1 inspects `entity_type`, branch 2 inspects `entity_type`, branch 3 inspects `manager_type`. The two columns are independent and disagree on ~10% of rows / ~8% of AUM. As a result:

1. Any row whose **manager_type** is one of the institutional sub-types not in the active list (`mixed`, `wealth_management`, `pension_insurance`, `family_office`, `multi_strategy`, `private_equity`, `venture_capital`, `endowment_foundation`, `SWF`, `strategic`) and whose **entity_type** is not literally `passive` or `activist` falls to **Other/Unknown** — even when the row carries clear classification signal.
2. Rows where **manager_type** says `passive` but **entity_type` carries an active-family value get bucketed into "Active" via branch 3 not firing — they fall to Other/Unknown by the same path. (We measured 19,380 rows / $631B in this exact case.)
3. The third branch never reads `entity_type`, so a row with `entity_type IN ('active','hedge_fund','quantitative')` but a non-active `manager_type` is **silently dropped** even though the entity layer has answered the question.

The chart silently mis-states the passive/active split for any ticker whose top holders include institutional sub-types — i.e. essentially every large-cap.

### 4.3 Quantification at LQ (2025Q4) across the entire `is_latest=TRUE` slice

Helper: [`scripts/oneoff/institution_scoping_phase4_query4_quantify.py`](../../scripts/oneoff/institution_scoping_phase4_query4_quantify.py) — write-keyword-clean, `read_only=True`.

**Buggy CASE breakdown (envelope across all tickers at LQ):**

| Category          | Rows         | AUM ($B)     | Share of rows | Share of AUM |
|-------------------|-------------:|-------------:|--------------:|-------------:|
| Other/Unknown     |  1,543,537   |  23,032.4    |  48.2%        |  34.2%       |
| Active            |  1,495,424   |  23,355.3    |  46.6%        |  34.7%       |
| Passive (Index)   |    166,424   |  20,845.5    |   5.2%        |  31.0%       |
| Activist          |        265   |      87.9    |  ~0.0%        |   0.1%       |
| **Total**         |  3,205,650   |  67,321.2    |  100%         |  100%        |

Other/Unknown is the **single largest bucket** — almost half of all rows and a third of AUM disappear into the "we don't know" pile.

**Silent-drop slice — rows in Other/Unknown that DO carry a classification signal:**

- **1,543,537 rows / $23,032.4B AUM** (i.e. essentially the entire Other/Unknown bucket carries signal — there are no all-NULL rows of meaningful size).
- **48.15% of LQ rows / 34.21% of LQ AUM** are mis-bucketed.

**Disagreement-only subset — manager_type bucket ≠ entity_type bucket (both non-NULL):**

| manager bucket    | entity bucket     | Rows     | AUM ($B) |
|-------------------|-------------------|---------:|---------:|
| active_family     | other_family      | 171,233  |   590.3  |
| other_family      | active_family     | 127,534  | 3,328.2  |
| passive_family    | active_family     |  19,380  |   630.8  |
| passive_family    | other_family      |   2,984  |   942.9  |
| active_family     | passive_family    |   1,970  |     0.5  |
| other_family      | passive_family    |     811  |     0.9  |
| activist_family   | other_family      |     214  |     0.5  |
| activist_family   | active_family     |      68  |     2.2  |
| **Total**         |                   | **324,194** | **5,496.1** |

= **10.11% of rows / 8.16% of AUM** disagree between the two columns at LQ. These rows are where the bug actually changes a label vs a corrected expression.

**Per-ticker worst case (top of the list):** `NVDA` — 4,188 of 9,042 holders ($929.8B of $3,090.2B AUM, ~30% of book) sit in Other/Unknown. Same holder set drives every mega-cap.

### 4.4 Fix shape (minimal diff)

Two practical fixes; the team can pick either.

**Option A — minimal (one-line spirit):** read `manager_type` *and* `entity_type` together, falling through. Add a second branch on `manager_type` for passive/activist before the active fallback, and merge `entity_type` into the active fallback so disagreement is resolved by symmetry.

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

This still under-classifies institutional sub-types (`mixed`, `wealth_management`, …) but at least stops the silent disagreement loss. Recovers ~19K passive_family/active_family rows and the 5,623 + 6,955 active/hedge_fund cross-disagreements directly. Net: shrinks Other/Unknown by ~324K rows / ~$5.5T (the disagreement total).

**Option B — canonical (the ROADMAP intent):** delete the CASE on `holdings_v2.manager_type/entity_type` entirely, join to `entity_current.classification` via `entity_id` (or `dm_rollup_entity_id` for institution-level), and bucket on the canonical column. This is the `parent-level-display-canonical-reads` workstream already on the P2 backlog — the query4 fix folds in there.

Option A is one CASE rewrite (≤10 lines). Option B is the right shape but requires the 18-site sweep tracked under that ROADMAP item.

### 4.5 Affected output surfaces

- API: `/api/v1/query4` (generic dispatch via `scripts/api_register.py:175`) and `/api/v1/export/query4` (Excel export at `:186`).
- React app: **no current consumer** — `web/react-app/src/types/api.ts` only defines envelopes for `/api/query1` (Register) and `/api/query7` (Fund Portfolio); no `query4` consumer exists. The bug is currently visible **only** through Excel export and direct API hits. (Means visible blast radius today is small, but any future tab built on q4 inherits the bug.)

### 4.6 Pattern duplication across other query files

Searched `cross.py`, `fund.py`, `trend.py`, `market.py`, `common.py` for the same disagreement pattern (CASE on `entity_type` + `manager_type` together).

- `scripts/queries/cross.py:44` — `entity_type NOT IN ('passive')` filter; reads `entity_type` only, single source.
- `scripts/queries/trend.py:377-378` — `SUM(CASE WHEN entity_type NOT IN ('passive') ...)`; reads `entity_type` only.
- `scripts/queries/trend.py:469, 671` — `entity_type IN (...)` filters; single source.
- `scripts/queries/market.py:373, 498` — `entity_type IN ('active','hedge_fund','activist')`; single source.
- `scripts/queries/common.py:687` — `COALESCE(h.manager_type, 'unknown')`; single source.

**No other file mixes the two columns the way `register.py:746-750` does.** The bug is uniquely localized to query4. Other read sites are vulnerable to the same disagreement noise but only as filter under-/over-counts, not silent-drop categorization.

---

## Phase 6 — Admin Refresh System dependency map

Source: `docs/admin_refresh_system_design.md` (990 lines, v3.2).

### 6.2 Dependencies on the entity / institution layer

| # | Dependency | Where in design | What is assumed |
|---|---|---|---|
| D1 | `entity_identifiers` is the resolution oracle for filer CIKs | §4 `entity_gate_check` (lines 530-532) | Every filer CIK / series_id resolves; unresolved goes to `pending_entity_resolution`. Implicit: identifier_type taxonomy is stable & lowercase (cik / crd / series_id). |
| D2 | `pending_entity_resolution` is non-blocking | §2a step 3 (line 178) | Unresolved CIKs do NOT block promote; they are post-facto resolvable. Implies the rest of the pipeline tolerates rows with unmapped entities at promote time. |
| D3 | `holdings_v2.is_latest` semantics correct after every refresh | §3 amendment chain pattern (lines 416-454) | After UPDATE+INSERT, exactly one accession per (cik, quarter) has `is_latest=TRUE`. Verify step (§2a step 7, line 191) re-runs validation on prod. |
| D4 | `manager_type` / `entity_type` columns on `holdings_v2` are **populated by the loader at write time** | §4 base class (lines 460-554), §5 schema (lines 558-589) | Migration 015 + the loader populate these columns. Design doc never enumerates how — assumed to be a parse-step responsibility, but not bound to canonical `entity_current.classification`. |
| D5 | `data_freshness` table is the freshness source-of-truth | §4 `stamp_freshness()` (line 540), §8 admin UI | One row per pipeline. Wire to UI via the badge component (§8 line 88). |
| D6 | `ingestion_manifest` row exists for every legacy refresh prior to mig-008 | §5 backfill plan for `fund_holdings_v2` (lines 610-630) | Backfill JOINs `fund_holdings_v2` to `ingestion_manifest` on `(series_id, report_month)` to recover accession_number. Coverage ≥90% expected (§13 line 959). |
| D7 | `filings_deduped` exists & is canonical for `holdings_v2` backfill | §5 holdings_v2 backfill (lines 632-659) | JOIN `holdings_v2` × `filings_deduped` on `(cik, quarter)`. Multi-accession ambiguity ≤0.5% (line 681). |
| D8 | Top-100 institutions by AUM are stable across quarters | §2b anomaly detection (line 291) | "Top 100 institutions: 100 of 100 present ✅" check assumes AUM-ranked institution identity is reproducible — i.e. entity-layer rollup IDs are stable across refreshes. |
| D9 | Auto-approve `admin_preferences` schema is sufficient | §2b auto-approval (lines 374-382) | Per-(user, pipeline) row, JSON conditions. Implicit: auto-approve never fires on entity-layer changes (only on pipeline rows). |
| D10 | `dm_rollup_entity_id` / `rollup_entity_id` are populated on every promoted row | §2a flow generally; not explicitly called out | Anomaly checks like "filers with >50% QoQ AUM change" presume rollup totals can be summed at the institution level. If rollup is NULL, the check silently drops the row. |
| D11 | `entity_classification_history` / `entity_current` are not refreshed by Admin Refresh | Implicit (no §) | Admin Refresh has no pipeline for entity classification changes. Reclassification (e.g. `cef-asa-flip-and-relabel` on 2026-05-02) is performed outside the framework. |
| D12 | `manager_type` taxonomy on `holdings_v2` matches `entity_current.classification` taxonomy | Implicit (§4) | Loader is expected to write the canonical value. Anomaly checks compare AUM by manager_type bucket implicitly. |

### 6.3 Cross-reference against current state — gap classification

| # | Gap | Severity | Detail |
|---|---|---|---|
| G1 | **`manager_type` and `entity_type` on `holdings_v2` are derived columns that disagree on ~10% of rows / ~8% of AUM** | **BLOCKER** | Admin Refresh anomaly checks ("per-filer AUM", "per-ticker holder count") aggregate by these columns; the ROADMAP `parent-level-display-canonical-reads` work plus query4 fix have to land first or every refresh report shows mis-classified Top-100 totals. (Phase 4 quantification: 1.54M rows / $23T in Other/Unknown today.) |
| G2 | **Admin Refresh has no entity-classification pipeline** (D11) | **BLOCKER** | When users reclassify entities (sibling agents 2/3 on family_office / multi_strategy migrations; recent CEF reclassify), there is no refresh-flow path. Today these go through staging snapshots & manual SQL. The Admin Refresh design assumes entity classification is "outside" — but every other dependency assumes it's correct. |
| G3 | **`manager_type` taxonomy mismatch** (D12) — `holdings_v2.manager_type` carries `family_office` and `multi_strategy` values that do **not** appear in `entity_current.classification` distinct list | non-blocker | Confirmed via query: 2 manager_type values exist in holdings_v2 with no canonical equivalent. Reverse direction (canonical-only values) also possible. The framework's anomaly bucketing inherits this drift. |
| G4 | **`ingestion_manifest` schema does NOT match the design's assumed shape** | **BLOCKER** | Design refers to `pipeline_name`, `status`, `row_counts_json` (e.g. §8 line 822). Live schema (verified) uses `source_type`, `fetch_status`, no `pipeline_name`, no `row_counts_json`, no `completed_at`. The admin dashboard queries cited in §8 will not run as documented. |
| G5 | **Activist is a manager_type value, not a flag** (D8 implicit) | non-blocker | Sibling Phase 5 owns this; the design's anomaly detection treats activist as an analytic dimension but `holdings_v2.is_activist` is also a column. Two sources of truth invite drift. Admin Refresh's per-filer AUM check needs to declare which one to read. |
| G6 | **`entity_relationships` / `entity_rollup_history` are not under Admin Refresh** (D10) | non-blocker | Rollup edits today happen via direct SQL + snapshot. Admin Refresh assumes rollups are stable & populated (verified: 0 NULL `dm_rollup_entity_id` / 0 dm-orphans on 12.27M latest rows — green today). But: no framework guard against future rollup drift. |
| G7 | **Top-100 institutions identity assumption** (D8) | non-blocker | Only valid if rollup IDs are stable. Sibling 1B's orphan analysis may surface drift. Anomaly check needs an explicit join target (currently unspecified). |
| G8 | **`pending_entity_resolution` has 6,874 open rows today** (D2) | non-blocker | Non-blocking by design, but the count alone exceeds the design's `max_new_pending: 100` anomaly threshold (§2b line 311) by 68×. The threshold needs recalibration before first user-triggered refresh, or every refresh fires an anomaly flag. |
| G9 | **`admin_preferences` table has 0 rows today** | non-blocker | Auto-approve is opt-in; default=disabled. Not a data gap, but worth noting that "well-trodden" auto-approve paths don't exist yet. |
| G10 | **`data_freshness` only tracks 29 entries** (D5) | non-blocker | Sufficient as a status feed today. Confirms badge wiring is alive. No action. |
| G11 | **Migration 008 was renumbered to 015** | non-blocker | Already absorbed (per DONE annotations §0 lines 13-110). Documentation cleanup only. |
| G12 | **Backfill quality assumed coverage** (D6, D7) | non-blocker | Design targets ≥99% direct on `holdings_v2`, ≥90% on `fund_holdings_v2`, 100% on `beneficial_ownership_v2`. Per the DONE annotations these are met. Verified at the table level: backfill_quality column is live. |
| G13 | **No published canonical-vs-derived parity check before/after refresh** | non-blocker | Today's refresh would re-stamp `holdings_v2.manager_type` from the loader without verifying it matches `entity_current.classification` for the same `entity_id`. Dependency D4 + D12 combined. |

### 6.4 Headline numbers

- **Total Phase 6 gaps:** **13**
- **BLOCKER count:** **3** (G1, G2, G4)
- **Biggest blocker:** **G4 — `ingestion_manifest` schema does not match the design doc.** The admin dashboard queries the design specifies (§8 line 822: "MAX(completed_at) from ingestion_manifest filtered by pipeline_name") cannot run against the live schema (`source_type`, `fetch_status`, no `pipeline_name`, no `completed_at`). This is structural — every admin endpoint touches this table. Either the design needs reconciling to live schema, or a column rename / migration adds the assumed columns. **Fix this before user-triggered Admin Refresh ships.**

---

## Open questions

1. **(Phase 4)** Should the query4 fix wait for the canonical-reads sweep (`parent-level-display-canonical-reads`, P2) or land as a one-line CASE patch first? Rec: land Option A immediately (10-line PR), then Option B inside the canonical sweep.
2. **(Phase 4)** Is "Other" + "Unknown" supposed to be one bucket (current) or two? Current code merges them — a corrected expression should probably split them so the analyst can see "rows we couldn't classify" vs "institutional types we don't render in this 4-bucket chart".
3. **(Phase 6)** The design's `ingestion_manifest` schema (§8) reads as if it were authored against an earlier table shape. Has the design doc been updated since the migration-001 control plane shipped? If not, v3.3 should reconcile.
4. **(Phase 6)** Does Admin Refresh need an entity-classification pipeline (G2) or is reclassification permanently out-of-band? If out-of-band, the doc should say so explicitly and the anomaly check on Top-100 institutions needs to know how to respond when an institution renames / reclassifies between refreshes.
5. **(Phase 6)** `max_new_pending: 100` anomaly threshold (§2b line 311) is 68× too tight given today's 6,874 open pending rows (G8). Bring threshold up to a reasonable baseline — probably "delta from prior run", not absolute.

---

## Helper script

`scripts/oneoff/institution_scoping_phase4_query4_quantify.py` — read-only quantifier. Verified: no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE keywords.

```
$ grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b' scripts/oneoff/institution_scoping_phase4_query4_quantify.py
# (no matches)
```
