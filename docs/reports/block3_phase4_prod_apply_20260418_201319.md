# BLOCK-3 Phase 4 Prod Apply — Report

**Run ID:** 20260418_201319
**Branch:** block-3-fund-holdings-retirement
**Sign-off:** Phase 3 gates signed off by Serge; Phase 4 executed 2026-04-18.
**Outcome:** All three gates PASS on prod. Exact parity with Phase 3 staging.

## Snapshot

- Path: `data/backups/13f_backup_pre_block3_phase4_20260418_201319/`
- Format: DuckDB EXPORT DATABASE (parquet)
- Size: 2.6 GB, 320 files
- Duration: 8.7s

## Step 1 — `enrich_holdings.py --fund-holdings` on prod

| metric | prod | Phase 3 staging | delta |
|---|---:|---:|---:|
| Pass C rows populated (NULL → ticker) | 1,218,264 | 1,218,264 | 0 |
| Pass C rows refreshed (X → Y) | 159,145 | 159,145 | 0 |
| fund_holdings_v2 ticker populated (pre → post) | 3,935,959 → 5,154,223 | 3,935,959 → 5,154,223 | 0 |
| VTSM 2025-09 NULL (pre → post) | 3,556 → 555 | 3,556 → 555 | 0 |
| Residual prod fund_holdings_v2 NULL | 8,936,174 | 8,936,174 | 0 |
| Pass B apply duration | 849.2s | 0.9s (already warm) | — |
| Pass C apply duration | 0.8s | 0.5s | — |
| Total runtime | ~14min | ~1s | — |

Prod enrich numbers match Phase 3 staging exactly; 0% delta.

## Step 2 — Sector refetch on prod

`scripts/refetch_missing_sectors.py` hardcodes `STAGING_DB = 'data/13f_staging.duckdb'`
and has no `--staging` flag to flip it — the script is staging-only by design
(per the docstring note that it's "largely subsumed by `fetch_market.py --staging
--metadata-only`" for the end-to-end case). Rather than edit the script outside
this phase's scope, the Phase 3 sector refetch output was mirrored from staging
to prod via `scripts/_block3_phase4_refetch_prod.py` — same UPDATE-only semantics
as the original refetch (sector+industry only, never INSERT), zero additional
Yahoo calls, deterministic since the Phase 3 staging run already resolved the
Yahoo metadata for the identical 355-ticker list.

Result:
- Candidate rows (staging.sector NOT NULL AND prod.sector NULL): **1**
- Rows updated on prod: **1**
- prod market_data.sector NULL post-run: 3,286 (matches staging 3,286)

Analysis of the "only 1 change" result: of the 355 Phase-3 refetch tickers,
only 114 exist in `market_data` at all; of those 114, 113 had sector already
populated in both prod and staging prior to Phase 3. Only 1 ticker had sector
NULL in both and was resolved via the Phase 3 Yahoo run — now mirrored to
prod. The remaining 241 tickers are absent from `market_data` entirely and
flow through `_map_to_gics` as "Unknown" / skipped by the builder (expected
behaviour — the gate is designed to pass despite residual Unknown).

No Yahoo rate-limit encounters (zero API calls on prod path).

## Step 3 — `build_benchmark_weights.py` on prod

Builder wrote 44 rows to `benchmark_weights` on prod. Per-quarter weights
identical to staging Phase 3 output — full sector list per quarter (11 sectors
× 4 quarters = 44 rows).

**2025Q1 (2025-03-31):** TEC 31.17, FIN 13.02, CND 11.77, HCR 10.69, COM 8.99, IND 8.64, CNS 5.22, ENE 3.35, REA 3.05, UTL 2.28, MAT 1.82 → 100.00
**2025Q2 (2025-06-30):** TEC 28.71, FIN 13.97, HCR 11.73, CND 10.86, COM 8.80, IND 8.76, CNS 5.71, ENE 3.78, REA 3.24, UTL 2.51, MAT 1.94 → 100.01
**2025Q3 (2025-09-30):** TEC 31.91, FIN 13.47, CND 10.88, HCR 9.94, COM 9.38, IND 9.04, CNS 5.18, ENE 3.16, REA 2.88, UTL 2.36, MAT 1.81 → 100.01
**2025Q4 (2025-12-31):** TEC 35.19, FIN 11.99, CND 10.96, COM 10.35, HCR 9.27, IND 8.55, CNS 4.18, ENE 3.25, REA 2.35, UTL 2.10, MAT 1.80 → 99.99

## Step 4 — Gate validation on prod

| Gate | Target | Actual | Result |
|---|---|---|---|
| 1. Row count (US_MKT) | 44 | 44 | **PASS** |
| 2. Weight sums per quarter | ∈ [99.0, 100.01] | 100.00 / 100.01 / 100.01 / 99.99 | **PASS** |
| 3. Drift vs 2026-04-17 backup | ≤ 2.0pp | max 1.66pp @ IT/2025Q4 (33.53 → 35.19), 0 breaches | **PASS** |
| Cross-check VTSM 2025-09 NULL | 555 | 555 | **PASS** |
| Staging parity (row-level diff) | 0 | 0 | **PASS** |

IT/2025Q4 drift of +1.66pp is the expected restoration of IT weight that the
pre-Audit backup understated (pre-Audit run had a truncated Q4 universe with
3,556 VTSM NULL tickers that the is_priceable-gated enrich now resolves).

No gate failures. No restore executed.

## Step 5 — `fetch_nport.py` retired

`git mv scripts/fetch_nport.py scripts/retired/fetch_nport.py`

Post-move live-reference grep (`rg -n "scripts/fetch_nport\.py|from fetch_nport |import fetch_nport"
--glob '!scripts/retired/**' --glob '!docs/**' --glob '!*.md'`):

Two non-breaking hits, both metadata/docstrings, no import/function references:
1. `scripts/pipeline/nport_parsers.py:22` — docstring provenance note
   ("Extracted from `scripts/fetch_nport.py`…"); kept as historical reference.
2. `scripts/pipeline/registry.py:142` — `owner="scripts/fetch_nport.py"`
   metadata string in `DatasetSpec("fund_universe")`; `.owner` is not read by
   any runtime code (pure inventory field); updated to
   `scripts/retired/fetch_nport.py` as part of Step 6 inventory maintenance.

Zero import hits. No Python module depends on the old path.

## Guardrail compliance

- [x] Snapshot succeeded before any prod write (2.6GB, path recorded)
- [x] No gate failures — no restore executed
- [x] Enrich numbers match Phase 3 staging within 0%
- [x] Zero Yahoo rate-limit encounters (staging-to-prod mirror, no API calls)
- [x] Step 5 move only after Steps 1-4 succeeded on prod
- [x] Grep confirms no live-code import references
- [x] No DROP TABLE anywhere
- [x] No downstream v2 rebuilds beyond Pass C

## Artifacts

- `logs/reports/_block3_phase4_enrich_prod.log`
- `logs/reports/_block3_phase4_refetch_prod.log`
- `logs/reports/_block3_phase4_build_prod.log`
- `logs/reports/_block3_phase4_gates_prod.log`
- Ephemeral helpers (not committed):
  `scripts/_block3_phase4_refetch_prod.py`,
  `scripts/_block3_phase4_gates_prod.py`
