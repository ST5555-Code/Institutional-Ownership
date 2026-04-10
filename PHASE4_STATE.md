# Phase 4 State — Facts Only

_Snapshot: 2026-04-09_

## Entity Counts (staging DB)

| Table | Rows |
|-------|------|
| entities | 20,205 |
| entity_identifiers | 29,023 |
| entity_relationships | 13,715 |
| entity_aliases | 20,439 |
| entity_classification_history | 20,212 |
| entity_rollup_history | 24,818 |

## Validation Gates

Item 1 result: **0 FAILs, 8 PASS, 7 MANUAL**

| Gate | Result |
|------|--------|
| Orphan relationships | PASS |
| Circular rollup chains | PASS |
| Multi-primary parents | PASS |
| SCD integrity | PASS |
| Duplicate entity IDs | PASS |
| Pending staging records | PASS |
| Rollup chain depth | PASS |
| Self-rollup consistency | PASS |
| ADV match rate | MANUAL |
| Classification coverage | MANUAL |
| Alias uniqueness | MANUAL |
| N-CEN adviser coverage | MANUAL |
| Long-tail resolution rate | MANUAL |
| International parent wiring | MANUAL |
| Rollup AUM reasonableness | MANUAL |

## Pre-Phase 4 Items

| Item | Status |
|------|--------|
| 1. Validation gates | ✅ |
| 2. Filing agent names | ✅ |
| 3. International parents | ✅ |
| 4. Top 50 self-rollup | ✅ |
| 5. Fidelity sub-adviser dedup | ✅ |
| 6. 13D/G data quality | ✅ |
| 7. app.py lint | ✅ |
| 8. Investor type classification | ✅ |
| 9. Final validation | ✅ |

**All 9 items complete.**

## Canonical Entity IDs — Top 15 Parents

| entity_id | Name | Rollup Children |
|-----------|------|-----------------|
| 10443 | Fidelity / FMR | 493 |
| 2 | BlackRock / iShares | 329 |
| 7984 | State Street / SSGA | 161 |
| 12 | Capital Group / American Funds | 145 |
| 30 | PIMCO | 138 |
| 4 | Invesco | 137 |
| 5022 | ProShare Advisors | 136 |
| 18983 | Jackson National AM | 133 |
| 5026 | Dimensional Fund Advisors | 131 |
| 6829 | Rafferty Asset Management | 131 |
| 2920 | Morgan Stanley | 128 |
| 17924 | T. Rowe Price | 126 |
| 4375 | Vanguard Group | 125 |
| 10178 | Ameriprise Financial | 123 |
| 2562 | Equitable Investment Management | 120 |

## Coverage Stats

| Metric | Entity DB | Production DB | Coverage |
|--------|-----------|---------------|----------|
| CIK (13F filers) | 11,135 | 9,121 | 100.0% |
| Series ID (N-PORT funds) | 8,547 | 6,671 | 100.0% |
| CRD (ADV advisers) | 9,341 | — | — |

## Last Commit

```
18d88dd Update ENTITY_ARCHITECTURE.md: validation gates 0 FAILs noted in pre-conditions
```

## Database Paths

- Production: `data/13f.duckdb`
- Staging (entity tables): `data/13f_staging.duckdb`
- Test: `data/13f_test.duckdb`

## Migration Approach

New data primary, old data shadow. App switches to entity-backed tables after pre-cutover scan passes. Legacy tables retained 30 days post-cutover, no fixed validation window — cutover authorized when background log is clean.

## AUM Parity Check (2026-04-09)

Entity rollup vs parent_bridge string matching — top 50 tickers by AUM:
- **50/50 match at 0.00% difference**
- Total AUM checked: ~$27T across top 50 tickers
- Entity system consolidates to fewer parents (merges subsidiaries) but dollar totals identical
- Example: NVDA — PB 5,585 parents $3,090B → Entity 5,483 parents $3,090B

## Entity Rollup Sync (2026-04-09)

- 87 self-rollup → parent wires synced from parent_bridge (Items 3+4 international/top-50 work)
- Entity child→parent: 9,348 (was 9,261)
- 15 remaining "gap" are correctly self-rolling parent entities
