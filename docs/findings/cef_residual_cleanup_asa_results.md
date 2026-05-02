# cef-residual-cleanup-asa — Phase 3-5 results

**Date:** 2026-05-02
**PR:** cef-asa-flip-and-relabel
**Workstream closed:** cef-residual-cleanup (last residual after PR #250)
**Investigation precedent:** docs/findings/cef_asa_prep_investigation.md
(commit 79350a5)
**Dry-run manifest:** docs/findings/cef_residual_cleanup_asa_dryrun.md
(commit 3a1a06d)

---

## Headline

350 ASA Gold (CIK 0001230869) UNKNOWN rows / $1,752,484,930.87 across
3 periods (2024-11, 2025-02, 2025-08) flipped to `is_latest=FALSE`
and relabeled to `series_id='SYN_0001230869'` in a single transaction.
AUM conservation Δ = $0.00 exact. Workstream closes.

---

## Phase 3 — Execution

Single transaction:

| Operation | Rows | AUM USD | Notes |
|---|---:|---:|---|
| INSERT new SYN_0001230869 | 350 | $1,752,484,930.87 | real ASA N-PORT accessions, fresh row_ids |
| UPDATE UNKNOWN → is_latest=FALSE | 350 | $1,752,484,930.87 | source MIG015 rows preserved as history |
| **AUM conservation** |  | **Δ = $0.00** | exact, within $0.01 gate |

### Pre/post counts

| Cohort | Pre rows | Post rows | Delta |
|---|---:|---:|---:|
| ASA UNKNOWN (is_latest=TRUE) | 350 | 0 | -350 |
| ASA SYN_0001230869 (is_latest=TRUE) | 143 | 493 | +350 |

The pre-existing 143-row 2025-11 SYN_0001230869 cohort is untouched
(out of scope per asa-2025-11-syn-source-investigation roadmap entry —
its source accession `0001049169-26-000039` is from Donnelley Financial
Solutions, not from ASA's own NPORT-P filings).

### Per-period coverage

| Period | UNKNOWN-side accession (now is_latest=FALSE) | New SYN-side accession (is_latest=TRUE) | Rows | AUM USD |
|---|---|---|---:|---:|
| 2024-11 | `BACKFILL_MIG015_UNKNOWN_2024-11` | `0001752724-25-018310` | 108 | $439,912,633.43 |
| 2025-02 | `BACKFILL_MIG015_UNKNOWN_2025-02` | `0001752724-25-075250` | 112 | $521,336,911.36 |
| 2025-08 | `BACKFILL_MIG015_UNKNOWN_2025-08` | `0001230869-25-000013` | 130 | $791,235,386.08 |

---

## Fund-attribution override (deviation from literal plan)

The plan specified that new SYN rows should INSERT with "all other
column values copied from the UNKNOWN row." Inspection at execution
time showed the UNKNOWN-side carries wrong fund-level attribution that
would have been propagated by a literal copy:

| Field | UNKNOWN-side (incorrect) | New SYN rows (canonical, mirrors 2025-11 row) |
|---|---|---|
| `fund_name` | `Asa Gold & Precious Metals Ltd` | `ASA Gold and Precious Metals LTD Fund` |
| `family_name` | `Asa Gold & Precious Metals Ltd` | `ASA GOLD & PRECIOUS METALS LTD` |
| `entity_id` | `11278` (fund-typed entity literally named `N/A`) | `26793` (canonical ASA institution) |
| `rollup_entity_id` | `63` (Calamos Investments) | `26793` (ASA self-rollup) |
| `dm_entity_id` | `11278` | `26793` |
| `dm_rollup_entity_id` | `63` | `26793` |
| `dm_rollup_name` | `Calamos Investments` | `ASA Gold and Precious Metals LTD Fund` |

User confirmed the override before execution. Holding-level columns
(`cusip`, `isin`, `issuer_name`, `ticker`, `asset_category`,
`shares_or_principal`, `market_value_usd`, `pct_of_nav`,
`fair_value_level`, `is_restricted`, `payoff_profile`, `quarter`,
`report_month`, `report_date`, `fund_cik`, `fund_strategy_at_filing`)
copied verbatim from UNKNOWN. New columns: `series_id`,
`accession_number`, `is_latest=TRUE`, `loaded_at=NOW()`,
`backfill_quality='relabel_from_unknown'`, fresh `row_id`.

Per-row audit trail captured in
`data/working/asa_unknown_relabel_manifest.csv` column
`entity_id_correction='11278→26793'` on every relabeled row.

Without the override, peer_rotation_flows for SYN_0001230869 would
have inherited the Calamos rollup, which would have silently shifted
$1.75B in ASA flows into a competitor's bucket.

---

## Phase 4 — peer_rotation_flows rebuild

`scripts/pipeline/compute_peer_rotation.py` ran end-to-end:

| Metric | Value |
|---|---:|
| Pre-rebuild rows | 17,489,567 |
| Post-rebuild rows | 17,489,564 |
| Row delta | -3 (-0.000017%) |
| Run-id | `peer_rotation_empty_20260502_191309` |
| Snapshot | `data/backups/peer_rotation_peer_rotation_empty_20260502_191309.duckdb` |
| Run + promote | ~226 s |

The -3 row delta is well within the ±0.5% post-PR #250 baseline gate
and reflects routine drift from rebuilding aggregates over the just-
modified `fund_holdings_v2` rows.

---

## Phase 5 — Validation

| Gate | Result |
|---|---|
| `pytest tests/` | 373 passed, 0 failed |
| `cd web/react-app && npm run build` | 0 errors, built in 2.04 s |
| `audit_unknown_inventory.py` (PR #246) | 0 distinct series, 0 rows, $0.00 AUM (live) — workstream closed |
| `audit_orphan_inventory.py` (PR #244) | `phase1_totals_is_latest=[0, 0, None]` — 0 live orphans |
| Spot check 1: `2025-08 / CA03349X1015` (Andean Precious Metals Corp) | 1 row, $8,490,188.23 (matches expected) |
| Spot check 2: `2025-08 / AU000000AQI2` (Alicanto Minerals Ltd) | 1 row, $1,620,240.48 (matches expected) |
| Spot check 3: `2025-08 / CA11777Q2099` (B2Gold Corp) | 1 row, $8,260,000.00 (matches expected) |

The `audit_orphan_inventory` `phase1_totals_all_history` line still
reports 1 series / 3,184 rows / $10B — that is the historical UNKNOWN
cohort now carrying `is_latest=FALSE`, intentionally retained for
audit history.

---

## Files

- `scripts/oneoff/cleanup_asa_unknown_relabel.py` — flip-and-relabel oneoff
- `data/working/asa_unknown_relabel_manifest.csv` — 350-row manifest
- `docs/findings/cef_residual_cleanup_asa_dryrun.md` — Phase 2 dry-run
- `docs/findings/cef_residual_cleanup_asa_results.md` — this file

---

## Cross-references

- Investigation: `docs/findings/cef_asa_prep_investigation.md` (commit 79350a5)
- ADX precedent: `scripts/oneoff/cleanup_adx_unknown_duplicates.py` (PR #250)
- Workstream scoping: `docs/findings/cef_scoping.md` (PR #249)
- 2025-11 SYN provenance follow-up: `asa-2025-11-syn-source-investigation` (P3 ROADMAP entry, out of scope here)
