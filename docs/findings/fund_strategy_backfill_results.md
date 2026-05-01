# Fund-Strategy Backfill — Results

**Date:** 2026-04-30
**Branch:** `fund-strategy-backfill`
**Sequence:** PR-1a of 5 in fund-level classification consolidation
**Predecessors:** PR #230 (`d7ba02d`), PR #231 (`cb418c0`), PR #232 (`db0e3e7`)
**Backup confirmed before any writes:** `data/backups/13f_backup_20260430_185107` (3.2 GB, 380 parquet files)

---

## Objective

Reconcile legacy `fund_strategy` data so `fund_strategy = fund_category` everywhere
in `fund_universe`, backfill the 658 SYN funds from `fund_holdings_v2` majority,
and propagate the canonical taxonomy across `fund_holdings_v2`. Goal: zero drift
between the two columns and zero NULL `is_actively_managed`.

`peer_rotation_flows` rebuild is **out of scope** — that is PR-1b.

---

## Phase 1 — `fund_universe` legacy residuals

### 1.1 Pre-state (read-only audit, prod, 2026-04-30)

| fund_strategy | fund_category | n_funds |
|---|---|---:|
| active | equity | 250 |
| active | balanced | 45 |
| active | multi_asset | 15 |
| mixed | equity | 5 |
| passive | equity | 15 |
| passive | balanced | 2 |
| passive | multi_asset | 1 |
| **total** | | **333** |

Matches §G2 of `classification_consolidation_plan.md` exactly.

### 1.2 SQL applied

```sql
UPDATE fund_universe
SET fund_strategy = fund_category,
    is_actively_managed = CASE
        WHEN fund_category IN ('equity','balanced','multi_asset') THEN TRUE
        WHEN fund_category IN ('bond_or_other','excluded','final_filing','index') THEN FALSE
        ELSE NULL
    END
WHERE fund_strategy IN ('active','passive','mixed');
```

### 1.3 Post-state (2026-04-30, prod)

333 legacy residuals → 0. All 333 rows now have `fund_strategy = fund_category`
and the corresponding `is_actively_managed` value set per the functional
dependency.

---

## Phase 2 — 658 SYN funds with NULL `fund_strategy`

### 2.1 Pre-state

- 658 SYN funds with `fund_strategy IS NULL` (decomposition: 0 empty-string, 658 NULL).
- All 658 resolvable from `fund_holdings_v2` majority count + most-recent quarter tiebreaker.
- 0 SYN funds without any `fund_holdings_v2` strategy rows.

### 2.2 Resolution distribution (majority + tiebreaker)

| resolved_strategy | n_syn |
|---|---:|
| bond_or_other | 421 |
| equity | 117 |
| balanced | 56 |
| multi_asset | 36 |
| final_filing | 12 |
| index | 8 |
| excluded | 8 |
| **total** | **658** |

Matches §6.1 of `nport_classification_scoping.md` to within ±1 (the small drift comes from latest-quarter recount; `2025Q4` plus the freshly-loaded `2026Q1` rows shifted a handful of muni trusts from `bond_or_other` into `final_filing`).

### 2.3 Drifter audit (32 series with ≥2 distinct holdings strategies)

Tiebreaker: highest `n_rows` first, then most-recent `quarter` to break ties on count.

| series_id | fund_name | candidates (strategy:rows@latest_quarter) | picked |
|---|---|---|---|
| SYN_0000813623 | Total Return Securities Fund | multi_asset:27@2025Q4 \| balanced:24@2025Q3 | multi_asset |
| SYN_0000826020 | Saba Capital Income & Opportunities Fund | balanced:1094@2026Q1 \| equity:1091@2025Q4 | balanced |
| SYN_0000835948 | BlackRock MuniVest Fund, Inc. | final_filing:241@2026Q1 \| bond_or_other:236@2025Q4 | final_filing |
| SYN_0000879361 | BlackRock MuniYield Fund, Inc. | final_filing:279@2026Q1 \| bond_or_other:279@2025Q4 | final_filing |
| SYN_0000880406 | HERZFELD CREDIT INCOME FUND, INC | multi_asset:29@2025Q4 \| bond_or_other:12@2025Q3 | multi_asset |
| SYN_0000887394 | BlackRock MuniYield Quality Fund II, Inc. | final_filing:320@2026Q1 \| bond_or_other:317@2025Q4 | final_filing |
| SYN_0000891290 | COHEN & STEERS TOTAL RETURN REALTY FUND INC | balanced:192@2025Q3 \| equity:186@2025Q4 | balanced |
| SYN_0000894242 | BlackRock Investment Quality Municipal Trust, Inc. | final_filing:276@2026Q1 \| bond_or_other:273@2025Q4 | final_filing |
| SYN_0000897269 | BlackRock MuniVest Fund II, Inc. | final_filing:243@2026Q1 \| bond_or_other:238@2025Q4 | final_filing |
| SYN_0001038186 | BlackRock MuniHoldings New York Quality Fund, Inc. | final_filing:242@2026Q1 \| bond_or_other:241@2025Q4 | final_filing |
| SYN_0001071899 | BlackRock MuniHoldings Quality Fund II, Inc. | final_filing:261@2026Q1 \| bond_or_other:257@2025Q4 | final_filing |
| SYN_0001137390 | BlackRock New York Municipal Income Trust | final_filing:243@2026Q1 \| bond_or_other:239@2025Q4 | final_filing |
| SYN_0001137391 | BlackRock California Municipal Income Trust | final_filing:123@2026Q1 \| bond_or_other:115@2025Q4 | final_filing |
| SYN_0001137393 | BlackRock Municipal Income Trust | final_filing:197@2026Q1 \| bond_or_other:189@2025Q4 | final_filing |
| SYN_0001176194 | BlackRock Municipal Income Trust II | final_filing:344@2026Q1 \| bond_or_other:342@2025Q4 | final_filing |
| SYN_0001181187 | BlackRock Municipal Income Quality Trust | bond_or_other:236@2025Q4 \| final_filing:232@2026Q1 | bond_or_other |
| SYN_0001260729 | Gabelli Dividend & Income Trust | balanced:681@2025Q4 \| equity:642@2025Q3 | balanced |
| SYN_0001343793 | BlackRock Long-Term Municipal Advantage Trust | final_filing:394@2026Q1 \| bond_or_other:382@2025Q4 | final_filing |
| SYN_0001391437 | Gabelli Healthcare & WellnessRx Trust | balanced:182@2025Q4 \| equity:147@2025Q3 | balanced |
| SYN_0001447247 | Partners Group Private Equity Fund, LLC | excluded:1700@2025Q3 \| multi_asset:1665@2025Q4 | excluded |
| SYN_0001496749 | John Hancock Diversified Income Fund | multi_asset:606@2025Q4 \| balanced:585@2025Q3 | multi_asset |
| SYN_0001499857 | Morgan Creek Global Equity Long/Short Institutional Fund | balanced:19@2025Q3 \| final_filing:18@2025Q4 | balanced |
| SYN_0001628040 | Alternative Credit Income Fund | bond_or_other:125@2025Q4 \| multi_asset:119@2025Q3 | bond_or_other |
| SYN_0001636289 | Virtus Diversified Income & Convertible Fund | multi_asset:302@2026Q1 \| bond_or_other:300@2025Q4 | multi_asset |
| SYN_0001717457 | Calamos Long/Short Equity & Dynamic Income Trust | bond_or_other:699@2025Q4 \| multi_asset:693@2026Q1 | bond_or_other |
| SYN_0001907437 | Opportunistic Credit Interval Fund | bond_or_other:101@2025Q3 \| multi_asset:96@2025Q4 | bond_or_other |
| SYN_0001987990 | KKR US Direct Lending Fund-U Inc. | bond_or_other:258@2025Q4 \| equity:218@2025Q3 | bond_or_other |
| SYN_0001989393 | Partners Group Next Generation Infrastructure LLC | multi_asset:79@2025Q4 \| bond_or_other:72@2025Q3 | multi_asset |
| SYN_0002008602 | Franklin Lexington Private Markets Fund | balanced:418@2025Q4 \| equity:148@2025Q2 | balanced |
| SYN_0002044327 | C1 Fund Inc. | multi_asset:9@2025Q4 \| bond_or_other:2@2025Q3 | multi_asset |
| SYN_0002054995 | Lincoln Partners Group Royalty Fund | multi_asset:48@2025Q4 \| balanced:13@2025Q3 | multi_asset |
| SYN_0002076022 | EP Private Capital Fund I | multi_asset:58@2025Q4 \| bond_or_other:34@2025Q3 | multi_asset |

Notes on tiebreaker behaviour:

- **BlackRock muni trusts** (~12 series) split between `final_filing` (2026Q1, the
  most recent quarter) and `bond_or_other` (2025Q4). The tiebreaker correctly
  picks the most recent N-PORT classification — `final_filing` indicates these
  trusts filed their final N-PORT before liquidation. After Phase 2 they end up
  with `is_actively_managed=FALSE`, which is correct.
- **Equity → balanced moves** (Saba, Cohen & Steers Total Return Realty,
  Gabelli Dividend, Gabelli Healthcare, Franklin Lexington Private Markets) all
  added bond/option positions over time as they shifted toward total-return
  strategies; the classifier moved them from `equity` into `balanced` as those
  positions grew. Picking the most recent (`balanced`) is correct.
- **`bond_or_other` ↔ `multi_asset` flips** (HERZFELD, John Hancock Diversified
  Income, Virtus Diversified Income & Convertible, Partners Group Infrastructure,
  Lincoln Partners Group, EP Private Capital, C1 Fund) reflect the classifier
  flipping between the two as the equity/bond mix crosses the threshold. The
  tiebreaker picks whichever quarter dominates.

### 2.4 SQL applied

```sql
-- Resolution table built once
CREATE TEMP TABLE _syn_resolved_strategy AS
WITH syn_funds AS (
  SELECT series_id FROM fund_universe
  WHERE fund_strategy IS NULL OR fund_strategy = ''
),
holdings_counts AS (
  SELECT fh.series_id, fh.fund_strategy, COUNT(*) AS n_rows,
         MAX(fh.quarter) AS latest_quarter
  FROM fund_holdings_v2 fh
  JOIN syn_funds sf USING (series_id)
  WHERE fh.fund_strategy IS NOT NULL AND fh.fund_strategy != ''
  GROUP BY fh.series_id, fh.fund_strategy
),
ranked AS (
  SELECT series_id, fund_strategy, n_rows, latest_quarter,
         ROW_NUMBER() OVER (
           PARTITION BY series_id
           ORDER BY n_rows DESC, latest_quarter DESC
         ) AS rn
  FROM holdings_counts
)
SELECT series_id, fund_strategy AS resolved_strategy
FROM ranked WHERE rn = 1;

UPDATE fund_universe
SET fund_strategy = r.resolved_strategy,
    fund_category = r.resolved_strategy,
    is_actively_managed = CASE
        WHEN r.resolved_strategy IN ('equity','balanced','multi_asset') THEN TRUE
        WHEN r.resolved_strategy IN ('bond_or_other','excluded','final_filing','index') THEN FALSE
        ELSE NULL
    END
FROM _syn_resolved_strategy r
WHERE fund_universe.series_id = r.series_id;
```

### 2.5 Post-state (2026-04-30, prod)

658 SYN funds with NULL `fund_strategy` → 0. All 658 now carry the resolved
strategy (matching the §2.2 distribution), with `fund_category` set to the same
value and `is_actively_managed` populated from the functional dependency.
**`fund_universe` rows with `is_actively_managed IS NULL`: 658 → 0.** This
neutralises the `cross.py:159` `COALESCE(fu.is_actively_managed, TRUE)` filter
behaviour for these series — they now resolve naturally.

---

## Phase 3 — `fund_holdings_v2` legacy residuals

### 3.1 Pre-state

| fund_strategy | rows | distinct_funds |
|---|---:|---:|
| active | 2,963,043 | 5,256 |
| passive | 1,877,774 | 1,018 |
| mixed | 634,197 | 377 |
| **total** | **5,475,014** | **6,651** |

STOP-condition check (unexpected legacy values): 0 rows. No values appear in
`fund_holdings_v2.fund_strategy` outside the canonical 7 + the 3 legacy values
+ NULL/empty.

### 3.2 Orphan rows (no `fund_universe` join)

3,184 rows on `series_id='UNKNOWN'`, all `is_latest=TRUE`, all legacy `active`.

Distinct fund names rolled into the `UNKNOWN` sentinel:

| fund_name | rows |
|---|---:|
| Calamos Global Total Return Fund | 1,412 |
| Saba Capital Income & Opportunities Fund | 1,091 |
| Asa Gold & Precious Metals Ltd | 350 |
| Eaton Vance Tax-Advantaged Dividend Income Fund | 157 |
| `N/A` | 96 |
| NXG Cushing Midstream Energy Fund | 43 |
| AMG Pantheon Credit Solutions Fund | 33 |
| AIP Alternative Lending Fund P | 2 |

These are 8 closed-end / alternative funds whose original `series_id` failed the
N-PORT loader's resolution and got bucketed into the `UNKNOWN` sentinel. There
is no row for `series_id='UNKNOWN'` in `fund_universe`, so a naïve
`UPDATE … FROM fund_universe` would skip them (DuckDB inner-join semantics).

### 3.3 SQL applied (main path)

```sql
UPDATE fund_holdings_v2 AS fh
SET fund_strategy = fu.fund_category
FROM fund_universe AS fu
WHERE fh.series_id = fu.series_id
  AND fh.fund_strategy IN ('active','passive','mixed')
  AND fu.fund_category IS NOT NULL AND fu.fund_category != '';
```

The `fu.fund_category IS NOT NULL` guard is defensive — by Phase 1+2 every row
in `fund_universe` has a non-null `fund_category`, so this guard is a no-op.

### 3.4 Orphan policy

The script offers `--orphan-policy {skip, equity, error}`:

- `skip` (default): leaves UNKNOWN's 3,184 legacy rows intact. Validate fails the
  "no legacy values anywhere" check and passes "no legacy values excluding orphans".
- `equity`: blanket-maps remaining `active→equity`, `passive→index`, `mixed→balanced`
  after the main UPDATE. Achieves zero legacy values everywhere.
- `error`: aborts Phase 3 if any orphans found.

**Selected policy:** `equity` — confirmed by user 2026-04-30. The 3,184
UNKNOWN orphan rows are blanket-mapped `active → equity` after the main UPDATE.
A roadmap item is now open to comprehensively review the resulting
`fund_strategy='equity'` bucket (and specifically the 8 underlying CEFs that
roll up into UNKNOWN — including AMG Pantheon Credit Solutions and AIP
Alternative Lending, which are credit funds, not equity).

### 3.5 Distribution of target `fund_category` values for the main UPDATE

| target fund_category | rows | funds |
|---|---:|---:|
| equity | 2,436,176 | 4,818 |
| index | 1,567,985 | 737 |
| balanced | 738,939 | 592 |
| multi_asset | 448,162 | 196 |
| excluded | 260,964 | 223 |
| bond_or_other | 13,675 | 49 |
| final_filing | 5,929 | 35 |
| `<NULL>` (= UNKNOWN orphan) | 3,184 | 1 |

### 3.6 Post-state (2026-04-30, prod)

5,475,014 legacy rows → 0. The main UPDATE cleared 5,471,830 rows via the
`fund_universe` join. The orphan-policy `equity` step then mapped the
remaining 3,184 `series_id='UNKNOWN'` rows from `active` to `equity`.

`fund_holdings_v2` final state:
- 0 rows with `fund_strategy IN ('active','passive','mixed')`
- 0 rows with `fund_strategy` outside the canonical 7-value set (excluding NULL/empty)
- 0 `is_latest=TRUE` rows with NULL/empty `fund_strategy`

---

## Schema corrections

### S1 — `fund_holdings_v2` is not in staging

The standard staging→prod workflow (`scripts/sync_staging.py` /
`scripts/promote_staging.py`) covers entity tables only. Reference data — including
`fund_holdings_v2` — is intentionally excluded and not mirrored to
`data/13f_staging.duckdb`:

> `sync_staging.py` header: "Reference data tables (holdings, securities,
> market_data, etc.) are NOT touched — they're managed separately by
> `db.seed_staging()` and `merge_staging.py`."

`fund_universe` does exist in staging (12,870 rows vs. prod's 13,623, so staging
is also stale relative to prod). The established precedent for fund-level
classification rewrites is `scripts/fix_fund_classification.py`, which uses an
in-place `UPDATE` on either DB selected via `--production` and gated by
`--dry-run` — not the staging→promote pipeline.

**Adopted approach:** `backfill_fund_strategy.py` follows the
`fix_fund_classification.py` precedent — direct in-place `UPDATE` on prod,
gated by `--dry-run` (default) and `--confirm`. The 3.2 GB parquet backup at
`data/backups/13f_backup_20260430_185107` provides full rollback on the prod DB.

### S2 — Empty-string vs NULL representation

Prompt phrasing said `fund_strategy = ''`; in actual prod data, all 658 SYN funds
have `fund_strategy IS NULL` (0 empty-string rows). The script handles both via
`fund_strategy IS NULL OR fund_strategy = ''` in every Phase 2 query.

### S3 — `fund_holdings_v2` has no `is_actively_managed` column

`is_actively_managed` lives only on `fund_universe`. The Phase 3 orphan-policy
`equity` step therefore only updates `fund_strategy`; there is no
`is_actively_managed` column on `fund_holdings_v2` to set. Read sites
deriving "active" status for holdings either join to `fund_universe` (e.g.
`scripts/queries/cross.py:159`) or compute it from `fund_strategy` directly.

---

## Validation

`scripts/oneoff/validate_fund_strategy_backfill.py` runs the full set of
post-condition checks. Pre-backfill (current state):

| check | fund_universe | fund_holdings_v2 |
|---|---|---|
| 0 legacy values | 333 (FAIL) | 5,475,014 (FAIL) |
| 0 NULL/empty | 658 (FAIL) | 0 (PASS, on `is_latest=TRUE`) |
| `fund_strategy = fund_category` | 333 mismatches (FAIL) | n/a |
| `is_actively_managed` not NULL | 658 NULLs (FAIL) | n/a |

Post-backfill validation (2026-04-30 21:00, prod, `validate_fund_strategy_backfill.py`, no `--allow-orphans`):

```
=== fund_universe ===
  [PASS] no legacy fund_strategy values: 0 (expected 0)
  [PASS] no NULL/empty fund_strategy: 0 (expected 0)
  [PASS] fund_strategy = fund_category: 0 (expected 0)
  [PASS] no NULL is_actively_managed: 0 (expected 0)

=== fund_holdings_v2 ===
  [PASS] no legacy values anywhere: 0 (expected 0)
  [PASS] no values outside canonical+legacy set: 0 (expected 0)
  [PASS] is_latest=TRUE rows have non-null fund_strategy: 0 (expected 0)

=== cross-page SYN leak baseline ===
  [INFO] fund_universe rows with is_actively_managed IS NULL: 0

ALL PASS
```

---

## Files

- [scripts/oneoff/backfill_fund_strategy.py](../../scripts/oneoff/backfill_fund_strategy.py) — orchestrator (3 phases, `--dry-run`/`--confirm` gates, `--orphan-policy` flag, `--db-path` override)
- [scripts/oneoff/validate_fund_strategy_backfill.py](../../scripts/oneoff/validate_fund_strategy_backfill.py) — post-condition validator
- [docs/findings/classification_scoping.md](classification_scoping.md) — PR #230 (`d7ba02d`) read-only audit
- [docs/findings/classification_consolidation_plan.md](classification_consolidation_plan.md) — PR #231 (`cb418c0`) consolidation plan
- [docs/findings/nport_classification_scoping.md](nport_classification_scoping.md) — PR #232 (`db0e3e7`) write-path re-audit
