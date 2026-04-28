# INF53 — BACKFILL_MIG015 multi-row groups in fund_holdings_v2

_Session: `bl3-inf53` (2026-04-28). Branch: `bl3-inf53`._

## Question

INF51 discovery found 55,988 groups in `fund_holdings_v2` with
value-divergent rows sharing the same
`(series_id, report_month, accession_number, cusip)` key. 54,437 of
these come from `BACKFILL_MIG015_*` synthetic accessions; 1,551 come
from real N-PORT accession numbers. Is this by design or a bug, and
what is the correct fix scope?

## TL;DR

**By design.** The `(series_id, report_month, accession_number, cusip)`
tuple is **not** a natural key for `fund_holdings_v2`, and never was.
N-PORT lets a fund report multiple `<invstOrSec>` line items for the
same security inside a single filing — distinct lots, Long/Short
pairs, sub-portfolios, repo positions across counterparties, and
private holdings without CUSIPs. Migration 015 did not create the
multi-row pattern; it only made it visible by stamping a synthetic
`accession_number` derived from `(series_id, report_month)`.

The real PK is the surrogate `row_id` (already enforced via
`fund_holdings_v2_row_id_pkey`, migration `020_pk_enforcement.py`).
No fix in this PR. Documentation update only.

## Evidence

### 1. Migration 015 logic

`scripts/migrations/015_amendment_semantics.py:181-202` — the
`fund_holdings_v2` migrator is a bulk UPDATE that adds three columns
and stamps every existing row:

```sql
UPDATE fund_holdings_v2
SET accession_number = 'BACKFILL_MIG015_' || series_id || '_' || report_month,
    backfill_quality = 'inferred'
```

The header comment (lines 30–36) explicitly calls this a sentinel:

> No per-series accession is recoverable from `ingestion_manifest`
> (NPORT manifest is per-DERA-ZIP, one accession covers thousands
> of fund-month pairs). Every row gets
> `accession_number='BACKFILL_MIG015_' || series_id || '_' ||
> report_month` and `backfill_quality='inferred'`.

The migration does **not** dedupe rows. It does not COUNT(*) GROUP BY
`(series_id, report_month, cusip)`. It is purely an additive UPDATE
on existing rows. Whatever multi-row pattern existed in
`fund_holdings_v2` before MIG015 still exists after.

### 2. Distribution

```
fund_holdings_v2 total rows:    14,568,775
BACKFILL_MIG015 rows:           14,090,329 (96.7%)
NPORT_NORMAL rows (real accn):     478,446 (3.3%)
Value-divergent groups:             55,924
  ├─ BACKFILL_MIG015:               54,373
  └─ NPORT_NORMAL:                   1,551
```

Both populations exhibit the same pattern. The 96.7%/3.3% skew toward
BACKFILL_MIG015 just reflects that 96.7% of the table predates the
control-plane and got the synthetic accession.

### 3. Sample groups (BACKFILL_MIG015, real CUSIPs)

`(series_id, report_month, cusip)` → distinct positions:

| Series | Month | CUSIP | n | Pattern |
|---|---|---|---|---|
| S000038670 (DFA World ex U.S. Targeted Value) | 2026-01 | 496902404 (KGC) | 2 | shares 124,582 vs 100; mv $3.93M vs $3.1K — two lots |
| S000000994 (DFA International Value) | 2025-04 | 867224107 | 2 | shares 840,913 vs 2,343,254 — two lots |
| S000055522 (Multi-Asset Strategy) | 2025-07 | 811916105 (SA) | 2 | 15,257 sh vs 24,534 sh — two lots |
| S000000697 (Clearwater Core Equity) | 2025-09 | G29183103 (WHR-PA) | 2 | 3,520 sh vs 6,307 sh — two lots |
| S000008301 (International Small Co Trust) | 2025-12 | 450913108 (IAG) | 2 | 4,400 sh vs 22,927 sh — two lots |

All five samples: same fund, same security, same `payoff_profile=Long`,
same `asset_category`, same `loaded_at` — different share counts and
market values. These are legitimate multi-lot positions reported as
separate `<invstOrSec>` items in N-PORT.

### 4. Sample groups (BACKFILL_MIG015, placeholder CUSIPs)

The largest groups are dominated by funds holding **non-CUSIP
securities** (private loans, derivatives) that all collapse into
`cusip='N/A'` or `cusip='000000000'`:

| Series | Month | CUSIP | n | Fund |
|---|---|---|---|---|
| 1658645_0001193125-25-257940 | 2025-08 | N/A | 210,535 | Stone Ridge Alternative Lending Risk Premium Fund |
| 1709447_0001193125-26-076584 | 2025-12 | N/A | 155,322 | (private-credit fund) |
| 2059436_0001410368-26-021130 | 2025-12 | 000000000 | 16,863 | (loan fund) |

For Stone Ridge: 210,484 of 210,535 rows are `asset_category='LON'`
(loans) with internal IDs as `issuer_name` (e.g., `L1379095.UP`,
`CBM4221649.UP`). Each loan is a distinct holding; they share `cusip='N/A'`
because loans don't have CUSIPs. This is correct N-PORT modelling.

### 5. Sample groups (NPORT_NORMAL, real accessions)

Same pattern with **real** accession numbers — confirms the multi-row
shape is intrinsic to N-PORT, not an artifact of the synthetic
accession:

| Series | Accession | CUSIP | n | Pattern |
|---|---|---|---|---|
| S000042023 (Franklin Alt Strategies) | 0000940400-26-014752 | 31935HAD9 | 3 | Long + **Short** + Long, distinct shares — hedged book |
| S000004362 (iShares Core US Agg Bond) | 0001410368-26-039534 | 066922477 | 3 | three Long STIV positions, $100K + $735M + $4.5B — repo/cash sleeves |
| S000012002 (NC Tax-Free Income) | 0001193125-26-163213 | 479357CG8 | 3 | three Long DBT positions, three different lot sizes |

Distinguishing-axis breakdown for the 1,551 NPORT_NORMAL groups:

```
Distinguished by payoff_profile alone:    397 (25.6%)
Multi-row even within same payoff:      1,154 (74.4%)
```

So `payoff_profile` is a partial discriminator (Long/Short pairs) but
74% of multi-row groups have **multiple positions on the same side**
of the same security — these are lot-level / sub-portfolio splits with
no business-axis tie-breaker except the surrogate `row_id`.

## Root cause

1. **N-PORT semantics** allow multiple `<invstOrSec>` entries per
   security per filing. Funds use this for:
   - Long/Short positions on the same CUSIP (hedged books).
   - Multiple lots, sub-portfolios, or sleeve allocations.
   - Repo/cash positions across counterparties.
   - Private holdings without CUSIPs (collapsed into `cusip='N/A'` or
     `'000000000'` placeholders).

2. **Schema design** treats `row_id` (BIGINT, surrogate) as the PK —
   confirmed via `duckdb_constraints()`:
   ```
   PRIMARY KEY(row_id)
   NOT NULL row_id
   ```
   No unique constraint exists or has ever existed on
   `(series_id, report_month, accession_number, cusip)`. The
   "PK assumption" called out in INF51 was a downstream analytic
   assumption, not a schema constraint.

3. **MIG015 sentinel accession** is a function of
   `(series_id, report_month)`. For amendments and "fake series" rows
   (where `series_id` got loaded as `CIK_accession`), the synthetic
   accession is unique per amendment, but for properly-keyed rows
   it collapses all amendments into a single bucket — which is
   exactly the design intent (sentinel = "we don't know the accession,
   group by series-month").

## Recommendation

**No code fix.** Update PK assumption documentation:

1. Note in `docs/admin_refresh_system_design.md` (or wherever the
   `(series, month, accession, cusip)` shorthand appears) that this
   tuple is **not unique** in `fund_holdings_v2`. Reference
   N-PORT semantics.

2. For analytic dedup/aggregation in `scripts/queries.py` and v2
   API routes that need a single value per (fund, security, month):
   `SUM(shares_or_principal)` and `SUM(market_value_usd)` across the
   group. Filter by `payoff_profile='Long'` if a long-only view is
   required. Already the convention in current rollup queries — no
   change needed.

3. The 1,551 NPORT_NORMAL groups are **not** loader bugs and do not
   warrant a `load_13f_v2.py` fix.

4. Future control-plane improvements could add an N-PORT line-item
   ordinal column (e.g., `nport_lot_index INT`) to make multi-row
   groups self-explanatory in raw inspection — non-blocking, not
   needed for correctness.

## Status

Closed as "by design." No follow-up item needed. ROADMAP entry moves
to COMPLETED.
