# cef-residual-cleanup-adx — Phase 2 dry-run manifest

_Generated: 2026-05-02T17:35:42Z_

## Cohort re-validation (Phase 1)

- ADX (CIK `0000002230`) UNKNOWN rows with `is_latest=TRUE`: **96**
- AUM (sum of market_value_usd): **$2,988,710,095.76**
- SYN_2230 companion rows with `is_latest=TRUE`: **291**

Expected per PR #249: 96 rows / ~$2,988,710,095.76. Drift gate: ±5% on row count + AUM.

## Period coverage

| Period | UNKNOWN rows |
|---|---:|
| 2025-09-30 | 96 |

## Accession verification

- `BACKFILL_MIG015_UNKNOWN_2025-09`

## SYN-match classification

| Classification | Rows | AUM (USD) | Action |
|---|---:|---:|---|
| **byte_identical** |   96 | $2,988,710,095.76 | FLIP `is_latest=FALSE` in Phase 3 |
| **mismatch**       |    0 | $0.00 | HOLD — surfaced for chat decision |
| **orphan**         |    0 | $0.00 | HOLD — no SYN companion |

Action totals: **FLIP=96 rows / $2,988,710,095.76**, HOLD=0 rows / $0.00.

## Phase 3 entry gate

All rows are FLIP. Phase 3 may proceed with `--confirm`.
