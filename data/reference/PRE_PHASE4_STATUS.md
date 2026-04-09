# Pre-Phase 4 Item Status

_Updated: April 8, 2026_

## Item 1 — Validation Gates ✅ COMPLETE
- 0 FAILs, 8 PASS, 7 MANUAL (all documented)
- Thresholds updated in validate_entities.py
- Committed: 848ec04

## Item 2 — Filing Agent Names in beneficial_ownership ❌ NOT STARTED
- 8,876 rows: Toppan Merrill/FA
- 5,994 rows: Unknown (filing agent)
- Need: resolve to actual beneficial owner names

## Item 3 — International Parent Entities ❌ NOT STARTED
- Amundi, DWS, MUFG, SocGen subsidiaries
- Wire to operating AM parent (not bank holding company)

## Item 4 — Top 50 Self-Rollup Verification ❌ NOT STARTED
- Ameriprise/Columbia, MFS/Sun Life, BMO to check
- Capital Group, Jane Street, LPL, etc. to confirm independent

## Item 5 — N15: Fidelity International Sub-Adviser Dedup ❌ NOT STARTED
- N-PORT inflated to ~110% of 13F for Fidelity
- Need series-level dedup in rollup queries

## Item 6 — R1/R2/R3: 13D/G Data Quality Audit ❌ NOT STARTED
- pct_owned null rate by filing type
- Filer name to 13F parent matching
- Amendment reconciliation
- Stale filing count

## Item 7 — Item 43: app.py Lint Debt ❌ NOT STARTED
- E402 import order
- B608 SQL injection warnings

## Item 8 — N21 TODOs: Investor Type Classification ❌ NOT STARTED
- PARENT_SEEDS expansion 50→250
- Spot-validate 100 largest holders
- classification_source column

## Item 9 — Final Pre-Phase 4 Validation ❌ NOT STARTED
- Full rebuild + all gates pass
- Parity scan vs legacy
- Documentation update
