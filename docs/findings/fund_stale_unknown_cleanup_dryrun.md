# fund-stale-unknown-cleanup — Phase 2 dry-run manifest

_Generated: 2026-05-02T09:40:39Z_

## Cohort re-validation

- (fund_cik, fund_name) pairs where `series_id='UNKNOWN'` AND `is_latest=TRUE`: **8**
- Rows: **3,184**
- AUM (sum of market_value_usd): **$10,024,654,105.56**

Expected per PR #246 audit: 8 / 3,184 / ~$10,025,000,000.00. Drift gate: ±5% on pair + row counts.

## Branch breakdown

| Branch | Pairs | UNKNOWN rows | UNKNOWN AUM (USD) | Action |
|---|---:|---:|---:|---|
| **BRANCH 1 — FLIP**              |   6 | 2,738 | $5,283,459,078.93 | `UPDATE ... SET is_latest=FALSE` in Phase 3 |
| **BRANCH 2 — HOLD_NO_MATCH**     |   2 |   446 | $4,741,195,026.63 | HOLD — no SYN_ companion; would orphan rows. Surfaced for chat. |
| **BRANCH 3 — HOLD_SYN_INACTIVE** |   0 |     0 | $0.00 | HOLD — SYN_ side also stale; different problem. Surfaced separately. |

## Per-pair manifest (sorted by UNKNOWN AUM DESC)

| branch | fund_cik | fund_name | UNKNOWN rows | UNKNOWN AUM (USD) | SYN series_id | SYN strategy | SYN is_latest=TRUE rows | SYN is_latest=FALSE rows |
|---|---|---|---:|---:|---|---|---:|---:|
| HOLD_NO_MATCH | 0000002230 | N/A | 96 | $2,988,710,095.76 | `—` | — | 0 | 0 |
| FLIP | 0001253327 | Eaton Vance Tax-Advantaged Dividend Income Fund | 157 | $2,864,088,426.62 | `SYN_0001253327` | balanced | 311 | 0 |
| HOLD_NO_MATCH | 0001230869 | Asa Gold & Precious Metals Ltd | 350 | $1,752,484,930.87 | `—` | — | 0 | 0 |
| FLIP | 0001709406 | AIP Alternative Lending Fund P | 2 | $1,018,135,937.25 | `SYN_0001709406` | bond_or_other | 1 | 0 |
| FLIP | 0001995940 | AMG Pantheon Credit Solutions Fund | 33 | $688,770,581.69 | `SYN_0001995940` | bond_or_other | 77 | 0 |
| FLIP | 0001285650 | Calamos Global Total Return Fund | 1,412 | $325,262,413.29 | `SYN_0001285650` | balanced | 1459 | 0 |
| FLIP | 0001400897 | NXG Cushing Midstream Energy Fund | 43 | $257,780,523.36 | `SYN_0001400897` | active | 46 | 0 |
| FLIP | 0000826020 | Saba Capital Income & Opportunities Fund | 1,091 | $129,421,196.72 | `SYN_0000826020` | balanced | 2185 | 0 |

## Phase 3 entry gate

**STOP.** 2 BRANCH 2 + 0 BRANCH 3 pair(s) require chat decision before --confirm can run. Per brief: do not synthesize or rewrite series_id; surface findings instead.
