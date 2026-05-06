# Retired Scripts

This directory holds scripts that have been retired from the active code path.
They remain checked-in for historical reference and reproducibility but are
not invoked by any pipeline, Makefile, scheduler, or test.

## Bootstrap advisers cohort (cp-5-pipeline-contract-cleanup, 2026-05-05)

One-shot ETF/Tier-A/B/C adviser bootstraps. Each script seeded a small,
named cohort of `entity_type='institution'` rows + the standard SCD row
set (entities, entity_identifiers, entity_aliases,
entity_classification_history, entity_rollup_history × 2). Idempotent
check-or-create by CRD/CIK/canonical_name. After the cohort was merged
to prod the script had no remaining purpose.

| Script | Original commit | Cohort | Eids minted |
| --- | --- | --- | --- |
| `bootstrap_etf_advisers.py` | `08e2400` (2026-04-15) | Van Eck, Aptus, BondBloxx | 3 |
| `bootstrap_residual_advisers.py` | `d330d8f` (2026-04-16) | Stone Ridge, Bitwise, Volatility Shares, Dupree, Baron, Grayscale (+1 reuse Abacus FCF) | 6 + 1 reuse |
| `bootstrap_tier_c_advisers.py` | `9463b6d` (2026-04-17) | Collaborative, Spinnaker, Yorkville, FundX, Procure AM, Community Development | 6 |

References to these scripts in docstrings of newer code (e.g.
`scripts/oneoff/dera_synthetic_stabilize.py`,
`scripts/resolve_pending_series.py`) are explanatory only — no runtime
import depends on them.

Closes Gap 4 from `docs/findings/cp-5-bundle-c-discovery.md` §7.5.
