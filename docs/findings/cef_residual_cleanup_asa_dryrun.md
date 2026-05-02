# cef-residual-cleanup-asa — Phase 2 dry-run manifest

_Generated: 2026-05-02T19:10:01Z_

## Cohort re-validation (Phase 1.1–1.3, 1.5)

- ASA Gold (CIK `0001230869`) UNKNOWN rows with `is_latest=TRUE`: **350**
- AUM (sum of market_value_usd): **$1,752,484,930.87**
- SYN_0001230869 companion rows with `is_latest=TRUE` for target periods: **0** (verified)
- Expected per investigation baseline (commit 79350a5): 350 rows / ~$1,752,484,930.87. Drift gate: ±5%.

### Period coverage

| Period | Accession (old → new) | UNKNOWN rows | UNKNOWN AUM (USD) |
|---|---|---:|---:|
| 2024-11 | `BACKFILL_MIG015_UNKNOWN_2024-11` → `0001752724-25-018310` | 108 | $439,912,633.43 |
| 2025-02 | `BACKFILL_MIG015_UNKNOWN_2025-02` → `0001752724-25-075250` | 112 | $521,336,911.36 |
| 2025-08 | `BACKFILL_MIG015_UNKNOWN_2025-08` → `0001230869-25-000013` | 130 | $791,235,386.08 |

## Phase 1.4 — N-PORT byte-identical re-verification

Per-period delta (UNKNOWN-side total minus N-PORT-side total):

| Period | UNKNOWN MV | N-PORT MV | Delta |
|---|---:|---:|---:|
| 2024-11 | $439,912,633.43 | $439,912,633.43 | $0.000000 |
| 2025-02 | $521,336,911.36 | $521,336,911.36 | $0.000000 |
| 2025-08 | $791,235,386.08 | $791,235,386.08 | $0.000000 |

Per-row threshold: ≤ $0.01 acceptable (rounding noise); > $0.01 surfaces as MISMATCH and HOLD.

Match anchor: `(report_date, isin)` primary, `(report_date, issuer_name)` fallback for null-ISIN rows. Multi-lot duplicates handled by rank-zip on market_value_usd (both sides sorted desc within each (period, key) group).

## Per-row classification

| Classification | Rows | UNKNOWN AUM (USD) | Action |
|---|---:|---:|---|
| **byte_identical** |  350 | $1,752,484,930.87 | FLIP_AND_RELABEL in Phase 3 |
| **mismatch**       |    0 | $0.00 | HOLD — surfaced for chat decision |
| **orphan**         |    0 | $0.00 | HOLD — no N-PORT match |

Action totals: **FLIP_AND_RELABEL=350 rows**, HOLD=0 rows.

## Fund-level attribution override

UNKNOWN-side rows carry `entity_id=11278` (fund-typed entity literally named `N/A`, rolling up to entity_id=63 = `Calamos Investments`). New SYN rows override fund-level columns to match the existing 2025-11 `SYN_0001230869` precedent: `entity_id=26793`, `rollup_entity_id=26793`, `dm_entity_id=26793`, `dm_rollup_entity_id=26793`, `dm_rollup_name='ASA Gold and Precious Metals LTD Fund'`, `fund_name='ASA Gold and Precious Metals LTD Fund'`, `family_name='ASA GOLD & PRECIOUS METALS LTD'`. Holding-level columns (cusip, isin, issuer_name, ticker, asset_category, shares_or_principal, market_value_usd, pct_of_nav, fair_value_level, is_restricted, payoff_profile, quarter, report_month, report_date, fund_cik, fund_strategy_at_filing) copied verbatim from UNKNOWN row. Per-row audit trail: manifest column `entity_id_correction='11278→26793'`.

## Phase 3 entry gate

All rows are FLIP_AND_RELABEL. Phase 3 may proceed with `--confirm`.
