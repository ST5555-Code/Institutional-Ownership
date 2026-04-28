# DERA synthetic-series resolution — scoping (read-only) — 2026-04-28

Follow-up to [docs/findings/2026-04-28-dera-synthetic-series-discovery.md](2026-04-28-dera-synthetic-series-discovery.md)
which closed the original P3 cleanup as **FLAG**. This pass scopes what a future
*resolve* pass would actually entail. Prod `data/13f_readonly.duckdb` (no writes).

## TL;DR

The framing of the original task — "find the missing real `Sxxxxxxxxx` series_id
and swap it in" — does not match what the data actually is. **All 714 registrant
CIKs behind the 1,236 synthetic series carry exactly one fund per CIK and have
zero real `Sxxxxxxxxx` series anywhere in fund_universe, ncen_adviser_map, or
the rest of fund_holdings_v2.** They are stand-alone investment companies
(ETFs, BDCs, interval funds, CEFs, muni closed-end funds) whose N-PORT filings
structurally lack `SERIES_ID` because they are not series trusts. The synthetic
key is the only stable identifier that exists for them.

The actionable bug isn't a missing real series — it's that the synthetic key is
keyed on `accession_number`, so the same fund gets a *different* synthetic key
each quarter (2 distinct synthetic series per fund × 714 funds ≈ 1,236 series).
Resolution = collapse to a stable per-fund key + link to entity, not recover
real series_ids.

## STEP 1 — Inventory

### 1a–b. Synthetic series by registrant CIK

| Metric | Value |
|---|---|
| Distinct synthetic series in `fund_holdings_v2` (is_latest) | 1,236 |
| Distinct registrant CIKs (prefix-stripped, padded) | 714 |
| Distinct fund_ciks per registrant | **1.0** (every registrant is single-fund) |
| Synthetic rows | 2,172,757 |
| Synthetic NAV exposure | $2,553.4B |
| Format `{cik}_{accession}` (real synthetic) | 1,235 series / 2,169,573 rows |
| Format literal `'UNKNOWN'` (legacy fallback, ~8 fund_ciks) | 1 series / 3,184 rows |

The literal `'UNKNOWN'` row covers 8 distinct fund_ciks under a single shared
key (Calamos Global Total Return, NXG Cushing Midstream, AMG Pantheon Credit
Solutions, Eaton Vance Tax-Advantaged Dividend, Saba Capital Income & Opp,
"N/A" cik=0000002230, AIP Alternative Lending Fund P, Asa Gold & Precious
Metals). This is older than the `{cik}_{acc}` synthetic and originates from
a pre-`fetch_dera_nport.py` loader.

### 1c. Resolution sources by registrant CIK

CIK normalization: all sources padded to 10 digits before joining.

| Source | Registrant CIKs with REAL `Sxxx` series |
|---|---|
| `fund_universe` | 0 |
| `ncen_adviser_map` | 0 |
| `fund_holdings_v2` (other-quarter) | 1 |
| Total CIKs with any real series anywhere | **1 / 714** |

| Other linkage | Registrant CIKs hit |
|---|---|
| Any row in `fund_universe` (with or without series) | 55 |
| Any row in `ncen_adviser_map` (with or without series) | 1 |
| `entity_identifiers` (cik → entity_id) | 55 |

The 55 entity-mapped CIKs were created in INF51-era residual-adviser bootstraps
(see `entities_snapshot_20260427_*`), which is why they have `entity_type =
'institution'` rows but no series fan-out.

### 1d. Tier classification (per task definitions)

| Tier | Criterion | Registrants | Synth series | Rows | NAV ($B) |
|---|---|---:|---:|---:|---:|
| **TIER 1** | Real series in fund_universe OR DERA other-quarter | 1 | 1 | 72 | 0.0 |
| **TIER 2** | Real series in ncen_adviser_map | 0 | 0 | 0 | 0.0 |
| **TIER 3** | Entity exists, no series anywhere | 55 | 108 | 1,285,842 | 1,982.6 |
| **TIER 4** | CIK does not resolve at all | 658 | 1,134 | 886,843 | 570.8 |
| **TOTAL** | | 714 | 1,243* | 2,172,757 | 2,553.4 |

\* Sum across CIK groups is 1,243; the actual distinct-series count is 1,236.
The 7-row gap is the literal `'UNKNOWN'` series being counted once per CIK it
spans (8 CIKs × 1 series, double-counted in 7 of the 8 buckets).

#### Composition by fund-name keyword

| Bucket | CIKs | Series | Rows | NAV ($B) |
|---|---:|---:|---:|---:|
| ETF (SPDR family) | 3 | 6 | 1,868 | 1,517.7 |
| Interval / Private credit | 108 | 212 | 1,866,226 | 317.9 |
| Muni (closed-end) | 107 | 185 | 57,443 | 141.3 |
| Trust (likely CEF) | 65 | 111 | 57,338 | 76.3 |
| Other | 431 | 729 | 189,882 | 500.2 |

Three SPDR ETFs alone are $1.52T — SPY (CIK 884394) is $1.38T of that. SPY is
a unit investment trust and reports N-PORT without a series structure.

## STEP 2 — Effort per tier

| Tier | NAV ($B) | Approach | Confidence | Time |
|---|---:|---|---|---|
| TIER 1 (1 CIK) | 0.0 | One-row UPDATE: rewrite synthetic→`S000093420` matched on (fund_cik, fund_name); also extend `resolve_pending_series.py` tier-S1 with a "real_series_in_other_quarter" probe | High | 30 min |
| TIER 2 (0 CIKs) | 0.0 | n/a — N-CEN does not cover any of these registrants | n/a | 0 |
| TIER 3 (55 CIKs) | 1,982.6 | Mint stable per-fund synthetic key (e.g. `SYN_<cik>`), collapse per-quarter accession variants, backfill `entity_id` + `rollup_entity_id` from `entity_identifiers`, re-emit `parent_fund_map` for the affected fund_ciks | High | 1–2 days (script + staging diff + promote) |
| TIER 4 (658 CIKs) | 570.8 | Bootstrap entity rows by fund_cik (re-use `bootstrap_residual_advisers.py` pattern), then apply Tier 3 stable-key migration | Medium (entity-naming dedup risk) | 2–3 days |
| Cross-quarter validation | — | After re-key, verify `parent_fund_map` and `compute_parent_fund_map.py` aggregates match a pre-change baseline within tolerance | High | 1 day |

**Total resolve effort: ~5 days**, gated on (i) deciding the stable-key naming
convention (`SYN_<cik>` vs reusing `S` prefix vs `fund_cik`-as-series), (ii)
acceptance of entity-bootstrap dedup risk for the 658 unmapped CIKs (some are
likely already entities under different identifiers — CRD, ADV file number).

## STEP 3 — Sample resolution test

### TIER 1 (only case)

CIK `0002060415` — First Eagle High Yield Municipal Completion Fund:

| Type | series_id | fund_name | report_month | rows | NAV |
|---|---|---|---|---:|---:|
| Synthetic | `2060415_0002071691-26-007379` | First Eagle High Yield Municipal Completion Fund | 2026-01 | 72 | $15.9M |
| Real | `S000093420` | First Eagle High Yield Municipal Completion Fund | 2025-10 | 68 | $16.4M |

**Match criteria:** identical `fund_cik`, identical `fund_name`, adjacent
`report_month`. **Match correct: yes.** The Q1'26 DERA bulk dropped SERIES_ID
for this filing; Q4'25 carried it. Cross-quarter probe in
`resolve_pending_series.py` would catch this without manual review.

### TIER 3 diagnostic (top 3 by NAV — *not* resolvable to real series)

These three are presented to make the structural point: there is no real
`Sxxxxxxxxx` to swap in. They are single-fund stand-alone filers.

| CIK | Fund | Synthetic series (per quarter) | fund_universe | ncen |
|---|---|---|---|---|
| 0000884394 | SPDR S&P 500 ETF TRUST | `884394_0001410368-25-031962` (2025-09) + `884394_0001410368-26-020131` (2025-12) | empty | empty |
| 0001735964 | Cliffwater Corporate Lending Fund | `1735964_0001735964-26-000006` (2025-09) + `1735964_0001735964-26-000003` (2025-12) | empty | empty |
| 0001041130 | SPDR DOW JONES INDUSTRIAL AVERAGE | `1041130_0001410368-25-041185` (2025-10) + `1041130_0001410368-26-034110` (2026-01) | empty | empty |

Same fund, two synthetic series, because the synthetic key includes
`accession_number`. Stable key = `SYN_<cik>` would collapse the pair and unlock
clean per-fund aggregation; entity_id is already populated for these (eid 26536,
26539, 26540 respectively).

## Summary table

| Tier | Registrants | Synthetic series | Rows | NAV ($B) | Approach | Time |
|---|---:|---:|---:|---:|---|---|
| TIER 1 | 1 | 1 | 72 | 0.0 | (fund_cik, fund_name) → real S* swap | 30 min |
| TIER 2 | 0 | 0 | 0 | 0.0 | n/a | 0 |
| TIER 3 | 55 | 108 | 1,285,842 | 1,982.6 | Stable-key mint + entity backfill + parent_fund_map re-emit | 1–2 days |
| TIER 4 | 658 | 1,134 | 886,843 | 570.8 | Bootstrap entity then TIER 3 | 2–3 days |
| **TOTAL** | **714** | **1,243** | **2,172,757** | **2,553.4** | | **~5 days** |

## Recommendation

The original FLAG decision (defer) still stands. This scoping confirms the
deferred work is **not** a metadata-recovery exercise — it's a small
identifier-design decision (stable per-fund synthetic key) plus a routine
entity-bootstrap pass for 658 unmapped registrant CIKs. Pick this up alongside
the next `resolve_pending_series.py` tier refresh (per the discovery doc's
recommended trigger #1), and only if a downstream workflow surfaces the gap.

No DB writes were performed. No staging diffs. No promotes.
