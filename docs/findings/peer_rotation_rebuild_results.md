# Peer-Rotation Rebuild — Results

**Date:** 2026-04-30
**Branch:** `peer-rotation-rebuild`
**Sequence:** PR-1b of 5 in fund-level classification consolidation
**Predecessor:** PR #233 (`626efb1`, fund-strategy-backfill PR-1a)
**Backup confirmed before run:** `data/backups/13f_backup_20260430_185107` (3.2 GB EXPORT DATABASE PARQUET, from PR-1a)
**Rebuild snapshot (auto):** `data/backups/peer_rotation_peer_rotation_empty_20260501_013033.duckdb`

---

## Objective

Propagate the corrected `fund_strategy` values from PR-1a into
`peer_rotation_flows.entity_type` at `level='fund'`. Before PR-1a,
`peer_rotation_flows` carried legacy `{active, passive, mixed}` values at
fund level (sourced from `fund_holdings_v2.fund_strategy`); after PR-1a,
`fund_holdings_v2` carries only canonical taxonomy. PR-1b runs the
existing `compute_peer_rotation.py` pipeline so the precompute table
catches up.

`compute_peer_rotation.py` reads `fund_holdings_v2.fund_strategy` directly
(`scripts/pipeline/compute_peer_rotation.py:547`) — no code change is
required, only a full rebuild.

Out of scope (per plan):
- Extending `INDEX_PATTERNS` for named passive funds → PR-2.
- Renaming `index` → `passive` → PR-1c.
- Switching the JOIN to read canonical `fund_universe.fund_strategy` → PR-4.

---

## Pre-rebuild audit (read-only against prod, 2026-04-30 21:25 ET)

### Distinct `entity_type` at `level='fund'`

| entity_type | rows |
|---|---:|
| active | 1,439,311 |
| passive | 1,085,567 |
| equity | 777,098 |
| index | 610,033 |
| excluded | 454,718 |
| mixed | 370,557 |
| balanced | 172,092 |
| bond_or_other | 85,001 |
| multi_asset | 69,437 |
| final_filing | 1,386 |
| **fund total** | **5,065,200** |

**Legacy residual at fund level: 2,895,435 rows** (active 1,439,311 +
passive 1,085,567 + mixed 370,557).

### Distinct `entity_type` at `level='parent'`

| entity_type | rows |
|---|---:|
| active | 5,116,516 |
| wealth_management | 2,965,442 |
| mixed | 1,979,668 |
| hedge_fund | 1,254,746 |
| pension_insurance | 455,358 |
| passive | 268,988 |
| quantitative | 255,876 |
| strategic | 65,194 |
| SWF | 31,564 |
| endowment_foundation | 12,296 |
| private_equity | 10,906 |
| venture_capital | 6,658 |
| activist | 1,694 |
| **parent total** | **12,424,906** |

Parent level retains legacy `{active, passive, mixed}` from
`holdings_v2.entity_type` (institution-level). Out of PR-1b scope —
parent rollup carries institution taxonomy, not fund taxonomy.

### Total

- Total rows: **17,490,106**
- Earliest `quarter_from`: **2022Q3**
- Latest `quarter_to`: **2026Q1**
- Distinct `(quarter_from, quarter_to)` pairs: **14**

### Source state (post-PR-1a)

`fund_holdings_v2.fund_strategy` distribution (`is_latest=TRUE`):

| fund_strategy | rows |
|---|---:|
| bond_or_other | 4,264,299 |
| equity | 3,596,380 |
| index | 3,055,575 |
| excluded | 1,809,797 |
| balanced | 1,113,399 |
| multi_asset | 714,874 |
| final_filing | 14,380 |
| **total** | **14,568,704** |

Zero legacy values in `fund_holdings_v2` post-PR-1a — confirmed clean
input for the rebuild.

---

## Rebuild execution

### Invocation determination

Read `scripts/pipeline/compute_peer_rotation.py` to determine flags.
Three modes available:

| flag | semantics |
|---|---|
| `--dry-run` | Read-only row-count projection per (pair × level × sector). |
| `--staging` | Run fetch + parse + validate against staging DB; do not promote. |
| _(none)_ | Full prod run: fetch → parse → validate → snapshot → promote. |

Plan calls for full rebuild against prod → invoked **without flags**.

### Command

```bash
python3 scripts/pipeline/compute_peer_rotation.py
```

Flask app stopped before launch (PID 73589, `kill 73589`); confirmed
`lsof -ti:8001` empty.

### Runtime breakdown

| phase | duration | rows |
|---|---:|---:|
| fetch (DDL only) | <1s | — |
| parse (compute flows per pair × sector × rollup) | 53.1s | 17,490,106 staged |
| validate (count gates) | <1s | — |
| snapshot (auto-backup) | 2.6s | — |
| promote (DELETE-by-scope + bulk INSERT) | 175.7s | 17,490,106 upserted |
| **total wall clock** | **~3.8 min** | — |

Validate gates passed: staged > 0; row-count swing 0% vs prior
(pre 17,490,106 vs post 17,490,106). Per-rollup breakdown logged:

```
validate: level=fund   rollup=economic_control_v1 rows=5,065,200
validate: level=parent rollup=decision_maker_v1   rows=6,212,453
validate: level=parent rollup=economic_control_v1 rows=6,212,453
```

Run ID: `peer_rotation_empty_20260501_013033`
(the `empty` token is the manifest's pre-run scope tag, not a
post-state assertion — the snapshot file inherits the same name.)

---

## Post-rebuild validation

### Plan validation #1 — zero legacy at fund level

```sql
SELECT entity_type, COUNT(*) FROM peer_rotation_flows
WHERE level='fund' AND entity_type IN ('active','passive','mixed')
GROUP BY entity_type;
```

Result: **empty** (0 rows). PASS.

### Plan validation #2 — fund-level values within canonical taxonomy

| entity_type | rows |
|---|---:|
| equity | 2,195,291 |
| index | 1,499,478 |
| excluded | 614,942 |
| balanced | 474,067 |
| multi_asset | 186,532 |
| bond_or_other | 90,319 |
| final_filing | 4,571 |
| **fund total** | **5,065,200** |

All 5,065,200 fund-level rows carry one of the seven canonical fund
taxonomy values; zero rows outside the set; zero NULLs. PASS.

Distribution shift vs pre-rebuild reflects the underlying PR-1a
backfill: 1,439,311 → 0 `active` resolved to `equity` / `balanced` /
`multi_asset` per `fund_strategy = fund_category`; 1,085,567 → 0
`passive` resolved to `index`; 370,557 → 0 `mixed` resolved to
canonical fund-level strategies.

### Plan validation #3 — parent-level distribution unchanged

| entity_type | rows |
|---|---:|
| active | 5,116,516 |
| wealth_management | 2,965,442 |
| mixed | 1,979,668 |
| hedge_fund | 1,254,746 |
| pension_insurance | 455,358 |
| passive | 268,988 |
| quantitative | 255,876 |
| strategic | 65,194 |
| SWF | 31,564 |
| endowment_foundation | 12,296 |
| private_equity | 10,906 |
| venture_capital | 6,658 |
| activist | 1,694 |
| **parent total** | **12,424,906** |

Identical to pre-rebuild. Zero fund-taxonomy values
(`equity`/`balanced`/`multi_asset`/`bond_or_other`) at parent level.
PASS.

### Plan validation #4 — total row count

| | rows |
|---|---:|
| Pre-rebuild | 17,490,106 |
| Post-rebuild | 17,490,106 |
| Delta | **+0** |

Identical totals; the PR-1a backfill collapsed values within the same
groupings, not the cardinality of `(entity, ticker)` pairs per scope.
PASS.

### Plan validation #5 — quarter pair coverage

The plan's expected pattern of `(Q1→Q4, Q2→Q4, Q3→Q4)` is incorrect
(stale carry-over from an earlier session memo). The pipeline actually
derives pairs as `zip(quarters[:-1], quarters[1:])` over the
`SELECT DISTINCT quarter` ordering on each source table — i.e. all
adjacent pairs.

Post-rebuild distribution:

| quarter_from | quarter_to | level | rows |
|---|---|---|---:|
| 2022Q3 | 2022Q4 | fund | 42 |
| 2022Q4 | 2023Q1 | fund | 51 |
| 2023Q1 | 2023Q2 | fund | 56 |
| 2023Q2 | 2023Q3 | fund | 54 |
| 2023Q3 | 2023Q4 | fund | 58 |
| 2023Q4 | 2024Q1 | fund | 60 |
| 2024Q1 | 2024Q2 | fund | 52 |
| 2024Q2 | 2024Q3 | fund | 49 |
| 2024Q3 | 2024Q4 | fund | 556,668 |
| 2024Q4 | 2025Q1 | fund | 795,194 |
| 2025Q1 | 2025Q2 | fund | 825,139 |
| 2025Q1 | 2025Q2 | parent | 3,987,936 |
| 2025Q2 | 2025Q3 | fund | 877,014 |
| 2025Q2 | 2025Q3 | parent | 4,108,446 |
| 2025Q3 | 2025Q4 | fund | 1,047,442 |
| 2025Q3 | 2025Q4 | parent | 4,328,524 |
| 2025Q4 | 2026Q1 | fund | 963,321 |

Identical pair set + counts vs pre-rebuild.

Note on the `(2022Q2, 2022Q3)` "missing" pair flagged by the validator:
`fund_holdings_v2` carries 11 sentinel rows at `quarter='2022Q2'`
(1 with a ticker, 0 overlap with `market_data` sectors), so the
pipeline correctly produces 0 rows for that pair. The validator now
reports this as INFO rather than FAIL.

### Validator output

```
$ python3 scripts/oneoff/validate_peer_rotation_rebuild.py

=== peer_rotation_flows (level='fund') ===
  [PASS] no legacy active/passive/mixed: 0 (expected 0)
  [PASS] values are subset of canonical fund taxonomy (NULLs ignored): 0 (expected 0)
  [PASS] fund-level row count is non-zero: 5,065,200

=== peer_rotation_flows (level='parent') ===
  [PASS] no fund-taxonomy values bleeding into parent: 0 (expected 0)
  [PASS] parent-level row count is non-zero: 12,424,906

=== peer_rotation_flows (whole table) ===
  [INFO] total rows: 17,490,106
  [PASS] no unexpected (non-consecutive) quarter pairs
         parent expected=3 actual=3 unexpected=[]
         fund   expected=15 actual=14 unexpected=[]
  [INFO] missing pairs (legitimate when source has no ticker/sector-overlapping holdings):
         fund   missing=[('2022Q2', '2022Q3')]

ALL PASS
```

---

## Sector Rotation tab spot-check

Restarted Flask (`python3 scripts/app.py --port 8001`) and exercised
the four endpoints the React `SectorRotationTab` calls:

| endpoint | HTTP | time | size |
|---|---:|---:|---:|
| `/api/v1/sector_summary` | 200 | 52 ms | 1.2 KB |
| `/api/v1/sector_flows?level=fund&active_only=0` | 200 | 15 ms | 23.6 KB |
| `/api/v1/sector_flow_movers?from=2025Q3&to=2025Q4&sector=Technology&level=fund&rollup_type=economic_control_v1&active_only=0` | 200 | 167 ms | 1.6 KB |
| `/api/v1/peer_rotation?ticker=AAPL&level=fund` _(adjacent tab)_ | 200 | 1.5 s | 13.2 KB |

Top fund-level rows in `peer_rotation_flows` for the most recent pair
(2025Q4→2026Q1), sorted by `|active_flow|` descending:

| entity | entity_type | ticker | sector |
|---|---|---|---|
| VANGUARD TOTAL STOCK MARKET INDEX FUND | **index** | NVDA | Technology |
| VANGUARD TOTAL STOCK MARKET INDEX FUND | **index** | AAPL | Technology |
| VANGUARD 500 INDEX FUND | **index** | NVDA | Technology |
| VANGUARD TOTAL STOCK MARKET INDEX FUND | **index** | MSFT | Technology |
| VANGUARD 500 INDEX FUND | **index** | AAPL | Technology |

All five carry the canonical `index` value, not legacy `passive`. Tab
is healthy.

---

## Files changed

| file | type | purpose |
|---|---|---|
| `scripts/oneoff/validate_peer_rotation_rebuild.py` | new | Idempotent post-rebuild validator (5 checks). |
| `docs/findings/peer_rotation_rebuild_results.md` | new | This document. |
| `ROADMAP.md` | edit | Move PR-1b from queued to COMPLETED. |

No code changes to the pipeline or query layer — PR-1b is purely a
data-state advancement.

---

## Rules observed

- All `compute_peer_rotation.py` runs explicitly authorized for this PR
  (per plan).
- Flask stopped before rebuild, restarted only after validation passed.
- No `--reset` of any other table; no destructive UPDATE/DELETE outside
  the pipeline's own DELETE-by-scope inside `promote()`.
- Backup confirmed before any writes.
- Branch name `peer-rotation-rebuild`; PR opened autonomously,
  user retains merge gate.
