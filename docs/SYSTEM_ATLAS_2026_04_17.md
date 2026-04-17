# System Atlas — 2026-04-17

**Pass 1 of 2** · Reviewer 1 (Claude Opus 4.7, ultrathink). Pass 2 is Codex (max thinking). Atlas-depth, wide scope, read-only.

## Meta

- **HEAD at audit start:** `da418a1e8cf766db8089026c2d50ef981ae41ae1` (`da418a1`, `main`). One commit past the prompt-specified `8323838`; `da418a1` is the session-close docs commit (`docs: 2026-04-17 session close — DM15 closed + 13D/G filers resolved + ncen hardening`), which cannot self-reference its own hash, so the roadmap header is pinned to the preceding code-commit. Material HEAD for this audit is `da418a1`.
- **Verification:** `git rev-parse HEAD` → `da418a1…ae41ae1`; re-verified post-audit, unchanged.
- **Primary DB:** `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb` (11.9 GB). All queries `read_only=True`.
- **Pre-audit backup:** `data/backups/13f_backup_20260417_172152` (2.6 GB, 2026-04-17 17:22). Untouched.
- **Worktree note:** audit executed from worktree `competent-meitner-ac5cdf` (@ `da418a1`). No writes. DB queries read `data/*.duckdb` in the main repo; this atlas doc written only to the worktree `docs/`.
- **Session completeness:** COMPLETE. All six categories inventoried. No section aborted.
- **Total drift findings:** 60 (26 DRIFT-CONFIRMED · 25 DRIFT-SUSPECTED · 9 CLEAN-with-note). See §7 concentration map.
- **Trigger-five verification (prompt §"Why this audit exists"):** not re-examined in Pass 1 — those are explicitly the prior-cycle findings that motivated the audit; Pass 1's job is to establish the wider baseline. Pass 2 should re-verify them against this atlas.
- **Delegation model:** six parallel Explore subagents (read-only tool surface), one per category. Top three load-bearing findings spot-verified independently by the coordinator before writing.

### Independent coordinator spot-checks (used to validate agent output)

| Claim | Agent source | Coordinator re-query | Match? |
|---|---|---|---|
| `fund_holdings_v2` entity_id coverage 40.09% overall | Agent A | `SELECT ROUND(100.0*COUNT(entity_id)/COUNT(*),2) FROM fund_holdings_v2` → `40.09` | ✅ |
| Recent-quarter collapse | Agent A | `GROUP BY report_month` → 2025-11: 0.18%, 2025-12: 0.61%, 2026-01: 5.88% | ✅ (even worse mid-2025Q4) |
| `ingestion_impacts` 13DG = 3 | Agent A/C | `GROUP BY m.source_type, i.promote_status` → `('13DG','promoted',3)` | ✅ |
| Override `new_value IS NULL` count (IDs 205-221) | Agent D | `COUNT FILTER WHERE new_value IS NULL` → `5` of 17 | ✅ (roadmap & commit-message both say 4) |
| `pending_entity_resolution` 13DG = 931 (roadmap says 928) | Agent D | `SELECT COUNT(*)` → `931` | ✅ |
| Legacy `fund_holdings` still loaded | Agent A | `SELECT COUNT(*), MAX(loaded_at)` → `(22030, 2026-04-14 21:22)` | ✅ |
| `adv_managers` has no freshness column / no `data_freshness` row | Agent C | `information_schema.columns` + `data_freshness` query | ✅ (no loaded_at, no DF row) |

Headline roadmap counters re-checked directly: `entities` 26,535 ✅, `entity_overrides_persistent` max=245 count=245 ✅, `ncen_adviser_map` 11,209 ✅, `investor_flows` 17,396,524 ✅. All MATCH.

---

## 1. Data Integrity — **DRIFT-CONFIRMED**

### 1.1 Table inventory (headline)

56 user tables + 2 views surveyed. Fact / L4 tables fresh ≤14d; MDM layer at canonical counts.

| Table | Rows | Freshness (`data_freshness` or max(stamp)) |
|---|---:|---|
| `raw_infotable` | 13,540,608 | (no stamp) |
| `holdings_v2` | 12,270,984 | 2026-04-17 04:56 (via `holdings_v2_enrichment` — no owning writer, see §3.1) |
| `fund_holdings_v2` | 14,090,397 | 2026-04-17 11:11 |
| `beneficial_ownership_v2` | 51,905 | 2026-04-14 04:05 |
| `beneficial_ownership_current` | 24,756 | 2026-04-17 12:24 |
| `fund_universe` | 12,870 | 2026-04-17 11:11 |
| `securities` | 132,618 | (no stamp) |
| `market_data` | 10,064 | 2026-04-16 23:27 |
| `ncen_adviser_map` | 11,209 | 2026-04-17 13:12 |
| `entities` | 26,535 | max(created_at) 2026-04-17 |
| `entity_identifiers` | 35,444 | max(created_at) 2026-04-17 |
| `entity_rollup_history` | 59,804 | (no stamp) |
| `entity_overrides_persistent` | 245 | (no stamp) |
| `summary_by_parent` | 63,916 | 2026-04-17 13:30 |
| `summary_by_ticker` | 47,642 | 2026-04-17 13:30 |
| `investor_flows` | 17,396,524 | 2026-04-17 13:30 |
| `ticker_flow_stats` | 80,322 | 2026-04-17 13:30 |
| `managers` | 12,005 | (no stamp) |
| `adv_managers` | 16,606 | **no stamp column, no DF row** |
| `short_interest` | 328,595 | max(loaded_at) 2026-04-16 |
| `cusip_classifications` | 132,618 | max(updated_at) 2026-04-15 |
| `cusip_retry_queue` | 37,925 | (no stamp) |
| `ingestion_manifest` | 21,339 | max(created_at) 2026-04-17 |
| `ingestion_impacts` | 29,531 | max(promoted_at) 2026-04-17 |
| `fund_holdings` (legacy) | **22,030** | max(loaded_at) **2026-04-14 21:22** |

Freshness tiers:
- **Fresh (≤14d):** 17 tables — all fact / L4 / enrichment / manifests / MDM deltas.
- **Stale (14–60d):** 0.
- **Cold (>60d):** 0.
- **No freshness column:** 33 tables — mostly reference (`lei_reference`, `parent_bridge`, `fund_name_map`, `index_proxies`, `benchmark_weights`, `peer_groups`, `fund_family_patterns`) and SCD history tables — acceptable; plus `securities` (should be stamped — see §1.6).

### 1.2 Coverage vs `docs/data_layers.md`

| Table | Doc line | Doc claim | Actual | Delta |
|---|---|---|---:|---|
| `holdings_v2` | `data_layers.md:91` | 12,270,984 | 12,270,984 | 0 |
| `fund_holdings_v2` | `data_layers.md:92` | 13,943,029 rows · **entity_id 84.47%** | 14,090,397 · **40.09%** | **+147,368 / −44.38pp** |
| `beneficial_ownership_v2` | `data_layers.md:93` | enrichment 94.52% | 94.52% | 0 |
| `fund_universe` | `data_layers.md:95` | 12,835 | 12,870 | +35 |
| `securities` | `data_layers.md:96` | 132,618 | 132,618 | 0 |
| `market_data` | `data_layers.md:97` | 10,064 | 10,064 | 0 |
| `entities` | `data_layers.md:109` | 26,535 | 26,535 | 0 |
| `entity_identifiers` | `data_layers.md:110` | 35,315 | 35,444 | +129 |
| `entity_rollup_history` | `data_layers.md:114` | 55,930 | 59,804 | +3,874 |
| `ncen_adviser_map` | `data_layers.md:101` | 11,209 | 11,209 | 0 |
| `ingestion_impacts` | `data_layers.md:134` | 21,245 | 29,531 | +8,286 (MARKET post-doc) |

### 1.3 Orphan detection

| # | Check | Orphan | Total | % | Label |
|---|---|---:|---:|---:|---|
| O1 | `holdings_v2.entity_id` ∉ `entities` | 0 | 12,270,984 | 0.00 | CLEAN |
| O2 | `fund_holdings_v2.entity_id` ∉ `entities` | 0 ref; **8,441,797 NULL** of 14,090,397 | — | **59.91% NULL** | **DRIFT-CONFIRMED** |
| O3 | `fund_holdings_v2.cusip` ∉ `securities` | 4,435,383 rows / 297,532 distinct | 14,090,387 | **31.48** | **DRIFT-CONFIRMED** |
| O4 | `holdings_v2.cusip` ∉ `securities` | 0 | 12,270,984 | 0.00 | CLEAN |
| O5 | `fund_holdings_v2.fund_cik` ∉ `entity_identifiers(cik)` | 1,961 / 1,995 distinct | 12.4M rows | 88.07% distinct | **DRIFT-SUSPECTED** (funds keyed by series_id, not CIK — but gap too wide to pass) |
| O6 | `fund_holdings_v2.series_id` ∉ `entity_identifiers(series_id)` | 1,265 / 14,379 distinct; 2,235,821 rows | — | 15.87% rows | **DRIFT-CONFIRMED** |
| O7 | `beneficial_ownership_v2.filer_cik` ∉ active CIK identifiers | 928 distinct, 2,846 rows | 3,522 / 51,905 | 5.48% rows | CLEAN (documented as `pending_entity_resolution` exclusions; see §4 for 931 vs 928 discrepancy) |

### 1.4 Coverage collapse by `report_month` (independently spot-verified)

```
report_month | total       | with_eid | pct_entity_id
2026-02      |       1,113 |   1,113  | 100.00
2026-01      |   1,321,332 |  77,701  |   5.88
2025-12      |   2,514,494 |  15,217  |   0.61
2025-11      |   2,001,782 |   3,556  |   0.18
2025-10      |   1,306,425 |  71,873  |   5.50
2025-09      |   1,419,322 | 487,158  |  34.32
2025-08      |     604,021 | 197,857  |  32.76
```

Enrichment is effectively broken for N-PORT reports filed against CY25Q4 and CY26Q1 `report_month`s. No other DB surface shows this pattern — `holdings_v2.entity_id` remains at 0 orphan rate.

### 1.5 Cross-table reconciliation (spot checks)

- `investor_flows` vs `holdings_v2` quarter-pair cardinality (1Q worldview): 2,083,116 actual vs 2,085,008 expected, Δ = −1,892 (0.09%). **CLEAN.**
- `summary_by_ticker` share totals match `holdings_v2` exactly for AAPL / MSFT × 4 quarters. Value totals differ in expected direction (`build_summaries.py` uses live market values) — MSFT 2025Q4 summary $2.689T vs infotable $2.581T (+4.2%). **CLEAN (expected).**
- EC vs DM worldview parity: row counts identical per period. **CLEAN.**

### 1.6 Amendment / `ingestion_impacts`

| source_type | promote_status | count |
|---|---|---:|
| 13DG | promoted | **3** |
| MARKET | pending | 90 |
| MARKET | promoted | 8,194 |
| NPORT | pending | 22 |
| NPORT | promoted | 21,222 |

- Zero rows with `promoted_at IS NULL AND created_at < 2026-04-10` — promote queue is current.
- **13DG manifest has only 3 impact rows, yet `beneficial_ownership_v2` has 51,905 rows.** ZIP-level grain rather than accession-level — pre-v2 history not mirrored into the unified impacts framework. **DRIFT-CONFIRMED.**
- `ingestion_manifest` covers only `{MARKET, NPORT, 13DG}` — **N-CEN and ADV run outside the manifest/impacts system** despite both calling `record_freshness`. Reconciliation/incident-review gap. **DRIFT-CONFIRMED.**

### 1.7 Staging vs prod

Staging at `data/13f_staging.duckdb` (1.3 GB). Entity MDM tables match prod exactly (`entities` 26,535, `entity_identifiers` 35,444, `entity_rollup_history` 59,804, `entity_overrides_persistent` 245). Prod fact tables (`holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`, `investor_flows`, `ticker_flow_stats`, `summary_by_ticker`) intentionally absent from staging — staging holds `stg_nport_holdings`, `stg_nport_fund_universe`, `stg_13dg_filings` per `data_layers.md:54` sync→diff→promote. **CLEAN.**

### 1.8 Drift summary — Data Integrity

| # | Finding | Evidence | Label |
|---|---|---|---|
| D-01 | `fund_holdings_v2.entity_id` 59.91% NULL (8.44M of 14.09M rows); doc claim 84.47% | `data_layers.md:92`; `SELECT COUNT(entity_id)/COUNT(*) FROM fund_holdings_v2` = 40.09% | **DRIFT-CONFIRMED** |
| D-02 | Coverage collapses by `report_month`: 2025-11 at 0.18%, 2025-12 at 0.61%, 2026-01 at 5.88% | Spot-verified SQL §1.4 | **DRIFT-CONFIRMED** |
| D-03 | 31.48% (4.44M rows, 297K distinct CUSIPs) of `fund_holdings_v2` reference a CUSIP not in `securities` | `LEFT JOIN securities USING(cusip)` count | **DRIFT-CONFIRMED** |
| D-04 | 15.87% of `fund_holdings_v2` rows have `series_id` not in `entity_identifiers(series_id)` | Join count | **DRIFT-CONFIRMED** |
| D-05 | Legacy `fund_holdings` table still populated (22,030 rows, `loaded_at` 2026-04-14 21:22) despite documented Stage-5 drop | `SELECT COUNT(*), MAX(loaded_at) FROM fund_holdings` | **DRIFT-CONFIRMED** |
| D-06 | `ingestion_impacts` has 3 rows for 13DG vs 51,905 BO rows — grain mismatch or un-mirrored backfill | Join count §1.6 | **DRIFT-SUSPECTED** |
| D-07 | `ingestion_manifest` covers only MARKET/NPORT/13DG; N-CEN + ADV absent | `SELECT DISTINCT source_type` | **DRIFT-CONFIRMED** |
| D-08 | `data_freshness` has 13 rows; `securities`, `adv_managers`, `managers`, all SCD tables, all reference tables unstamped | `data_freshness` enumeration + `information_schema` | **DRIFT-SUSPECTED** (partial coverage) |
| D-09 | `fund_holdings_v2.fund_cik` 88% of distinct values unresolved to entity CIK identifiers | `LEFT JOIN` count | **DRIFT-SUSPECTED** (funds indexed by series_id, but gap still large) |
| D-10 | `ingestion_impacts` total 29,531 vs doc claim 21,245 (+8,286 MARKET) | `data_layers.md:134` vs count | **DRIFT-SUSPECTED** (stale doc) |
| D-11 | 32 snapshots × 9 entity tables accumulating (D7 retention decision open) | `information_schema.tables` prefix scan | CLEAN (documented open) |

### 1.9 Section verdict

**DRIFT-CONFIRMED.** `fund_holdings_v2` entity enrichment has regressed materially from the documented 84.47% baseline to 40.09% overall, collapsing to near-zero in the three most recent N-PORT `report_month`s. CUSIP reference integrity also broken at 31.48% orphan rate. No signs of active corruption — facts are internally consistent and entity MDM is synced — but post-promote enrichment is silently degraded.

### 1.10 Pass 2 deep-dive flags (Data)

1. Why does `fund_holdings_v2.entity_id` collapse from ~99% (2025Q1) to 0.18% (2025-11). Is `promote_nport.py` Group-2 enrichment (`data_layers.md:279`) skipping recent months, or is the entity gate letting promotes through without resolution?
2. 297,532 distinct CUSIPs in `fund_holdings_v2` not in `securities` — is `build_cusip.py` / `build_classifications.py` running against the full N-PORT universe or only 13F?
3. `ingestion_impacts` 13DG grain (3 rows vs 51,905 filings) — confirm whether `_mirror_manifest_and_impacts` needs backfill for pre-v2 data.
4. `fund_holdings` legacy writer still landing rows — trace which script writes (legacy `fetch_nport.py` or some amendment path).
5. 1,265 unresolved `series_id` values — overlap with `pending_entity_resolution` source_type='NPORT'?
6. Snapshot growth policy (D7) — 32 × 9 = 288 snapshot tables. At what size does this become a retention blocker?

---

## 2. Code Integrity — **DRIFT-CONFIRMED (tail)**

~94 Python scripts in `scripts/`. Writer universe scoped to the ~50 that write DB. Core v2 pipelines (fetch_nport_v2, fetch_13dg_v2, promote_*, build_cusip v2, enrich_*, compute_flows, build_summaries) comply with `PROCESS_RULES.md` §1/§2/§7 and `pipeline_violations.md` CLEARED labels hold at HEAD. Drift concentrates in a long tail of direct-to-prod helpers.

### 2.1 Writer inventory (abbreviated)

The full inventory is ~50 scripts. Highlights (load-bearing):

| Script | Target | Table(s) | Write style |
|---|---|---|---|
| `fetch_nport_v2.py:258,484,522,701,750,769` | staging (+prod manifests) | stg_nport_*, ingestion_* | Per-accession INSERT + CHECKPOINT every 2000 |
| `promote_nport.py:412,436,490,494` | prod | `fund_holdings_v2`, `fund_universe`, manifests | Scoped DELETE+INSERT (no explicit BEGIN/COMMIT) |
| `fetch_13dg_v2.py:333,370,490` | both | BO v2, listed_filings_13dg, manifests | Batch INSERT + shared CHECKPOINT |
| `promote_13dg.py:184-185,273,282,287` | prod | BO v2, BO current | DELETE+INSERT keyed by accession; CHECKPOINT |
| `build_cusip.py:409,425` | prod / staging | `securities`, `cusip_classifications`, `cusip_retry_queue`, `_cache_openfigi` | UPSERT + ROLLBACK + final CHECKPOINT |
| `enrich_holdings.py:446,460,475,512` | both | holdings_v2_enrichment + columns | Per-batch UPDATE + CHECKPOINT |
| `compute_flows.py:87,117,149,…` | prod (+`--staging`) | `investor_flows`, `ticker_flow_stats` | DROP+CTAS per period (destructive but idempotent) |
| `build_summaries.py:166,230,333,344` | both | summaries | INSERT + CHECKPOINT |
| `build_managers.py:22,:588` | **prod hardcoded** | `managers`, `parent_bridge` | DROP+CTAS |
| `build_fund_classes.py:19,:85` | **prod hardcoded** | fund_classes + 5 tables + ALTER `fund_holdings` | DROP+CTAS |
| `fetch_adv.py:247,267` | prod | `adv_managers`, `cik_crd_direct`, `lei_reference` | DROP+CTAS from pandas |
| `load_13f.py:317` | prod | raw_*, filings, filings_deduped, holdings (dropped) | DROP+CTAS |
| `fetch_ncen.py:424,474` | prod | `ncen_adviser_map`, `managers.adviser_cik` | INSERT + CHECKPOINT per 25 |
| `fetch_market.py:609,707,948` | prod | `market_data`, manifests, DF | Chunked upsert + CHECKPOINT every 500 |
| `promote_staging.py:320,374,384-447,462-469` | prod | entity MDM | BEGIN + ROLLBACK + CHECKPOINT |
| `*_apply.py` (dm14 L1, dm14b, dm14c, dm15 L1, dm15 L2, dm15c, inf23) | staging | entity MDM | BEGIN/ROLLBACK |
| `validate_nport_subset.py:67` | **prod RW (validator)** | — | `read_only=False` |
| `validate_classifications.py:152` | prod RW (conditional) | — | conditional |
| `admin_bp.py:127,639,659-739` | prod RW via Flask | — | live-request writes |
| `resolve_agent_names.py:135,264`, `resolve_bo_agents.py:260`, `resolve_names.py:229`, `backfill_manager_types.py:40`, `enrich_tickers.py:419` | **prod RW (unlisted)** | MDM-adjacent | UPDATE + (some) CHECKPOINT |
| `fix_fund_classification.py:54,87` | staging/prod | `fund_universe.classification` | `executemany`, no CHECKPOINT |
| `refetch_missing_sectors.py:46` | staging | `market_data.sector/industry` | UPDATE loop, no CHECKPOINT |

### 2.2 `PROCESS_RULES.md` compliance re-audit

- **§1 incremental save + CHECKPOINT every 500** — violators at HEAD: `fetch_adv.py`, `load_13f.py`, `build_managers.py`, `build_fund_classes.py`, `build_benchmark_weights.py:57`, `build_shares_history.py`, `build_entities.py` (per-step missing, final only), `refetch_missing_sectors.py`, `resolve_long_tail.py`, `fix_fund_classification.py`, `resolve_adv_ownership.py`. All listed in `pipeline_violations.md` — **still apply at HEAD** (verified).
- **§2 restart-safe** — compliant: `fetch_nport_v2.py` (via `ingestion_impacts.load_status`), `fetch_13dg_v2.py` (via `fetched_tickers_13dg`), `reparse_*`. Non-compliant but SUPERSEDED: `fetch_nport.py`.
- **§3 multi-source failover** — handled by `pipeline/shared.sec_fetch()`; legacy single-source scripts acknowledged.
- **§4 rate limiting (`time.monotonic`)** — `fetch_ncen.py` still uses `time.sleep(SEC_DELAY)`; `fetch_adv.py` no rate limiter.
- **§5b QC gates** — live in `fetch_13dg_v2._extract_fields` (verified `pipeline_violations.md:50`).
- **§7 derived-table rebuild at end** — compliant for `promote_13dg.py`, `build_summaries.py`.
- **§9 `--dry-run`** — violators: `fetch_adv.py`, `load_13f.py`, `refetch_missing_sectors.py`, `build_cusip.py`, `build_managers.py`, `build_fund_classes.py`, `build_benchmark_weights.py`, `build_shares_history.py`, `compute_flows.py`, `build_summaries.py`, `fix_fund_classification.py`.

**No stale entries found in `pipeline_violations.md`.** `build_cusip.py` and `fetch_market.py` blocks header-marked CLEARED and verified. `fetch_nport.py` and `fetch_13dg.py` (legacy) correctly labeled SUPERSEDED.

### 2.3 Transaction safety

- `fetch_nport_v2.py`, `promote_nport.py`, `promote_13dg.py`, `build_summaries.py`, `enrich_holdings.py` — **no explicit BEGIN/COMMIT**, rely on DuckDB auto-commit + periodic CHECKPOINT. Idempotent on re-run.
- `compute_flows.py` — DROP+CTAS (destructive, idempotent). No BEGIN/COMMIT.
- `*_apply.py`, `build_entities.py`, `promote_staging.py` — **proper BEGIN + ROLLBACK + CHECKPOINT.** Best-in-repo pattern.

Promote scripts (`promote_nport.py`, `promote_13dg.py`) are load-bearing but **lack explicit transaction wrap** around DELETE+INSERT. DuckDB auto-commits per statement — a crash between the two leaves prod with scope rows missing until rerun.

### 2.4 Staging-first discipline

Direct-to-prod writers that arguably should go through staging:

- `build_managers.py:22,:588` — prod hardcoded (flagged in `pipeline_inventory.md:195`).
- `build_fund_classes.py:19,:85` — prod hardcoded.
- `fetch_adv.py:247` — prod DROP+CTAS.
- `load_13f.py:317` — prod raw tables direct.
- `resolve_agent_names.py:135,264`, `resolve_bo_agents.py:260`, `resolve_names.py:229`, `backfill_manager_types.py:40`, `enrich_tickers.py:419` — **write prod directly, not listed in `pipeline_violations.md`.**
- `resolve_13dg_filers.py` `--prod-exclusions` path — deliberate exception (`pending_entity_resolution` not in `db.ENTITY_TABLES`).

### 2.5 Read-only discipline

- `validate_nport_subset.py:67` — opens prod in **write mode** for a validator, with the comment "write lock — promote will need it too." **DRIFT-CONFIRMED**; validators should not hold prod write locks.
- `validate_classifications.py:152` — conditional prod RW path.
- `admin_bp.py:127,639,659-739` — Flask blueprint writes at request time; admin requests block CHECKPOINT cadence during promotes.

### 2.6 Drift summary — Code Integrity

| # | Finding | Evidence | Label |
|---|---|---|---|
| C-01 | Promote scripts have no explicit BEGIN/COMMIT around DELETE+INSERT | `promote_nport.py:275-334`; `promote_13dg.py:105-150,273-287` | **DRIFT-SUSPECTED** |
| C-02 | `validate_nport_subset.py:67` opens prod in write mode | same | **DRIFT-CONFIRMED** |
| C-03 | `validate_classifications.py:152` conditional prod RW | same | **DRIFT-SUSPECTED** |
| C-04 | `build_managers.py`, `build_fund_classes.py`, `build_benchmark_weights.py` hardcode prod | `build_managers.py:22,:588`; `build_fund_classes.py:19,:85`; `build_benchmark_weights.py:57` | **DRIFT-CONFIRMED** (documented) |
| C-05 | `resolve_agent_names.py`, `resolve_bo_agents.py`, `resolve_names.py`, `backfill_manager_types.py`, `enrich_tickers.py` write prod directly, **not listed in `pipeline_violations.md`** | file:line as above | **DRIFT-CONFIRMED** |
| C-06 | `fix_fund_classification.py` `executemany` with no CHECKPOINT | `:54,:87` | **DRIFT-CONFIRMED** (documented) |
| C-07 | `refetch_missing_sectors.py` hardcoded `/tmp/refetch_tickers.txt`, no CHECKPOINT | `:46-50` | **DRIFT-CONFIRMED** |
| C-08 | `compute_flows.py` DROP+CTAS (destructive) for derived tables | `:87,:117` | **DRIFT-SUSPECTED** |
| C-09 | `admin_bp.py` opens prod RW from Flask | `:127,:639,:659-739` | **DRIFT-SUSPECTED** |
| C-10 | `fetch_nport.py` (legacy) still on disk; accidental-run risk | `scripts/fetch_nport.py:842` | **DRIFT-SUSPECTED** (retention policy) |
| C-11 | Multiple scripts call `duckdb.connect()` without context-manager close | `migrate_batch_3a.py:73`, `fix_fund_classification.py:54` | **DRIFT-SUSPECTED** |

### 2.7 Section verdict

**AMBER / DRIFT-CONFIRMED in tail.** Core v2 pipelines clean; drift is the five unlisted direct-to-prod helpers (Finding C-05) plus two validators opening prod RW (C-02/03). None currently block pipelines; each is a small staging-discipline hole.

### 2.8 Pass 2 deep-dive flags (Code)

1. Atomicity of `promote_nport.py` / `promote_13dg.py` DELETE+INSERT without explicit BEGIN — confirm DuckDB crash-recovery semantics.
2. Why validators (`validate_nport_subset.py`, `validate_classifications.py`) hold prod write locks.
3. Scope `pipeline_violations.md` to include the five unlisted direct-writers (C-05).
4. `admin_bp.py` Flask-time writes — interaction with promote locks and CHECKPOINT cadence.
5. `build_managers.py` / `build_fund_classes.py` staging-bypass resolution priority.
6. `compute_flows.py` DROP+CTAS → incremental upsert migration (now that `holdings_v2` carries worldview columns).
7. `fetch_nport.py` legacy retention — safe-to-retire decision.

---

## 3. Pipeline Health — **DRIFT-CONFIRMED**

### 3.1 Per-pipeline state

| Pipeline | Evidence | Last run | Rows | Blockers | Status |
|---|---|---|---|---|---|
| **13F** (`load_13f.py`) | **no `load_13f_*.log` in `/logs/`**; `filings` max quarter 2025Q4 (11,372); `holdings_v2` 12,270,984; no owning freshness writer (`pipeline_inventory.md:10`) | Undatable; proxy is `holdings_v2_enrichment` at 2026-04-17 04:56 | 12.27M total | `docs/pipeline_inventory.md:59` REWRITE | **STALE / UNKNOWN** |
| **N-PORT** (`fetch_nport_v2.py` + `promote_nport.py`) | `nport_topup_20260415_095148.log`; `promote_nport_060422_scoped.log` 2026-04-16 13:19; DF `fund_holdings_v2` 2026-04-17 11:11; impacts MAX(promoted_at) 2026-04-17 11:11 | 2026-04-17 11:11 | 14.09M | None | **HEALTHY** |
| **13D/G** (`fetch_13dg_v2.py` + `promote_13dg.py`) | `ingestion_manifest` MAX(fetch_completed_at) 2026-04-14 04:02; DF `beneficial_ownership_v2` 2026-04-14 04:05; enrichment 2026-04-17 12:24 | 2026-04-14 04:05 (fetch); 2026-04-17 12:24 (enrich) | 51,905 BO rows | Fetch cadence 3d | **HEALTHY** (borderline — see D-03 below) |
| **N-CEN** (`fetch_ncen.py`) | `fetch_ncen_output.log`; `ncen_routing_drift.log` 2026-04-17 13:12; DF 2026-04-17 13:12 | 2026-04-17 13:12 | 11,209 | `pipeline_inventory.md:58` RETROFIT | **HEALTHY** (with RETROFIT tag) |
| **Market** (`fetch_market.py`) | `fetch_market_20260416c.log` 2026-04-16 23:27; DF 2026-04-16 23:27 | 2026-04-16 23:27 | 10,064 | `impact_id` race (see below) | **HEALTHY (with recurring crash risk)** |
| **ADV** (`fetch_adv.py`) | **no `fetch_adv_*.log` anywhere; no `loaded_at` column; no DF row**. Best proxy: `logs/phase35_full_run.log` 2026-04-07 | **UNKNOWN** | 16,606 | `pipeline_inventory.md:55` REWRITE | **STALE / UNKNOWN** |
| **Derived** (`enrich_holdings.py`, `compute_flows.py`, `build_summaries.py`) | `enrich_holdings_20260417_084223.log`; `compute_flows_20260417_173023.log`; `build_summaries_20260417_173045.log`; all DF rows 2026-04-17 13:30 | 2026-04-17 13:30 | — | None | **HEALTHY** |

### 3.2 Derived pipeline freshness

All derived tables newer than sources: `holdings_v2_enrichment` / `holdings_v2` same stamp 2026-04-17 04:56; `investor_flows` and `ticker_flow_stats` 8.6 h ahead of sources; `summary_by_*` 2.3 h ahead. `beneficial_ownership_current` 3d rebuild-ahead of `beneficial_ownership_v2` (standalone `enrich_13dg.py` refresh pattern, documented). **CLEAN.**

### 3.3 PROCESS_RULES compliance per pipeline

- **13F** — non-compliant per `load_13f.py:182,:200,:222` DROP+CTAS; matches REWRITE tag.
- **N-PORT** — compliant (§1/§2/§3/§4/§5/§9 all present in v2).
- **13D/G** — compliant (QC gates + accession dedupe + shared `rebuild_beneficial_ownership_current`).
- **N-CEN** — mostly compliant; `§6 flush=True` missing (relies on `-u`); `§9 --dry-run` missing. RETROFIT tag correct.
- **Market** — mostly compliant; `§3` is **complementary-source** (Yahoo+SEC), not strict failover; `§9` has `--limit N` but no true `--dry-run`.
- **ADV** — non-compliant (DROP+CTAS, no §2 restart, silent-continue on missing cols, no `--dry-run`).
- **Derived trio** — compliant (per-pass CHECKPOINT verified in log files).

### 3.4 Recent pipeline failures (last 14 days)

- `logs/fetch_market_crash.log` 2026-04-16 15:28:59 — `ConstraintException: Duplicate key "impact_id: 191"` at `scripts/pipeline/manifest.py:134`. Post-CUSIP-v2, indicates `manifest._next_id` helper MAX+1 allocation is **not transactionally coupled to the INSERT**. Earlier crashes 2026-04-13 (pandas NA boolean) and 2026-04-03 (legacy holdings). **DRIFT-CONFIRMED** (recurring after nominal fix).
- `logs/fetch_nport_v2_crash.log` 2026-04-14 13:04:43 — `IOException: Could not set lock on ... 13f_staging.duckdb (Conflicting lock, PID 49378)`. Concurrent process contention, not data defect.
- `logs/fetch_nport_v2_crash.log` 2026-04-14 05:28 — `TypeError: '<' not supported between 'str' and 'datetime.date'` at `pipeline/discover.py:214`; partial fix evident from 13:04 re-run clearing this trace.
- Legacy crash logs (`fetch_13dg_crash.log`, `fetch_nport_crash.log`, `compute_flows_crash.log`, `resolve_agent_names_crash.log`) — all from 2026-04-03 or earlier.
- No tracebacks in 2026-04-17 derived runs.

### 3.5 Drift summary — Pipeline Health

| # | Finding | Evidence | Label |
|---|---|---|---|
| P-01 | 13F loader has no owning freshness writer; last datable run unknown | missing `load_13f_*.log`; `pipeline_inventory.md:10` | **DRIFT-CONFIRMED** (documented) |
| P-02 | ADV pipeline undatable — no log, no `loaded_at`, no `data_freshness` row | `DESCRIBE adv_managers`; missing log | **DRIFT-SUSPECTED** (may be intentional for reference-data pipeline, but silent) |
| P-03 | 13D/G fetch cadence 3d; `ingestion_manifest` has only 1 run / 3 impacts in its whole history for 13DG | manifest+impacts counts | **DRIFT-SUSPECTED** |
| P-04 | Market `impact_id` duplicate-PK crash recurred 2026-04-16 after nominal `manifest._next_id` fix | `fetch_market_crash.log:37-49` | **DRIFT-CONFIRMED** |
| P-05 | N-CEN + ADV not in `ingestion_manifest` despite both calling `record_freshness` | `SELECT DISTINCT source_type` | **DRIFT-CONFIRMED** |
| P-06 | N-PORT DF stamp at 2026-04-17 11:11 but no corresponding log file in `/logs/` — promote-only re-run with output routed to stdout | DF vs ls /logs 2026-04-17 | **DRIFT-SUSPECTED** |
| P-07 | N-PORT `report_month` leakage: 64 rows @ 2026-03, 1,113 @ 2026-02 — partial filings post-period; no completeness gate | GROUP BY query | WATCH |

### 3.6 Section verdict

**PARTIAL / DEGRADED.** Core fetch+promote (N-PORT, Market, 13D/G) and derived trio are fresh on 2026-04-17 and PROCESS_RULES-compliant, but three silent-drift surfaces: 13F has no freshness writer, ADV has no log/stamp, and Market has a recurring impact_id race post-fix.

### 3.7 Pass 2 deep-dive flags (Pipeline)

1. ADV end-to-end trace — confirm whether `fetch_adv.py` has actually run in the last 30d or `adv_managers` is frozen since Phase 3.5 (2026-04-07).
2. 13F loader replacement — quantify rows being masked by `enrich_holdings` stamp (is 2025Q4 `holdings_v2` complete vs `filings_deduped` 2025Q4 = 10,535?).
3. `manifest._next_id` read-vs-INSERT transaction coupling — reproduce with concurrent `fetch_market.py --limit`.
4. 13D/G manifest cadence — 1 run total in history is anomalous; verify whether runs are discarded pre-manifest or genuinely first-run.
5. N-CEN + ADV retrofit into `ingestion_manifest` for uniform incident forensics.
6. Locate log for N-PORT promote at 2026-04-17 11:11 (missing).

---

## 4. Roadmap vs Reality — **CLEAN-WITH-MINOR-DRIFT**

### 4.1 Structure snapshot

- `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/ROADMAP.md` — 305,536 bytes / 1,095 lines.
- Top three `##`-level session headers:
  - Line 23: `2026-04-16 part 2` (Batch 3 beyond — 13D/G linkage, add_last_refreshed_at, top-up, ETF Tier A+B, recovery).
  - Line 90: `2026-04-16` (Batch 3 close — compute_flows + build_summaries + migration 004).
  - Line 111: `2026-04-16` (Batch 3 — enrich_holdings shipped).
- **Session #11 close is encoded in italicized top-of-file paragraphs at lines 3–21**, not as its own `##` section. Pins itself to HEAD `8323838` — which cannot include the docs-close commit that carries the pin.

### 4.2 Claim-by-claim (23 claims verified)

| # | Claim | Evidence | Result |
|---|---|---|---|
| 1 | 2,591 unmatched BO v2 filer CIKs | `13dg_filer_research_v2.csv` distinct `filer_cik` = 2,591 | MATCH |
| 2 | 23 MERGE + 1,640 NEW_ENTITY | Commit `5efae66`; `entities` 24,895→26,535 (+1,640) | MATCH |
| 3 | 928 exclusions to `pending_entity_resolution` | Actual **931** | **DRIFT-CONFIRMED** (Δ=3) |
| 4 | BO v2 coverage 77.08% → 94.52% | 49,059 / 51,905 = 94.52% | MATCH |
| 5 | BO current 73.64% → 94.51% | 23,398 / 24,756 = 94.51% | MATCH |
| 6 | DM15b +103 ncen rows; `ncen_adviser_map` 11,106→11,209 | Commit `9ce5b17` stats; DB = 11,209 | MATCH |
| 7 | 81/84 fund_universe series covered | Not spot-checked at series grain | UNVERIFIABLE |
| 8 | DM15 Layer 2: 17 sub-adviser DM retargets / $8.95B | 17 override rows in 205-221; AUM not re-summed | MATCH (count) |
| 9 | Override IDs 205-221, **4 NULL-CIK** | Actual 5 NULLs (IDs 205, 206, 207, 208, 220) | **DRIFT-CONFIRMED** |
| 10 | CBRE IM (eid 11166) chosen over shell 18645 | Override 217 new_value = CIK 0000900973 | MATCH |
| 11 | DM15c: eid 2214 renamed Amundi→Amundi SA, passive→active | Rename MATCH; classification SCD valid_to semantics blocked independent check | PARTIAL |
| 12 | 12 Amundi geographic entities rerouted (listed eids 1318, 1414, 3217, 3975, 4248, 4667, 5403, 6006, 7079, 8338, 10266, 752) | All 12 confirmed | MATCH |
| 13 | 24 override rows IDs 222-245 | DB count 24, max 245 | MATCH |
| 14 | fetch_ncen hardening (`ef7fb13`+`8323838`) | Commit stats match claim | MATCH |
| 15 | `entities` 26,535 (+1,640) | 26,535 | MATCH |
| 16 | `entity_overrides_persistent` 245 | 245 | MATCH |
| 17 | `ncen_adviser_map` 11,209 (+103) | 11,209 | MATCH |
| 18 | `investor_flows` 17,396,524 | 17,396,524 | MATCH |
| 19 | `summary_by_parent` 63,916 | 63,916 | MATCH |
| 20 | Snapshot 11,361.5 MB | `stat` → 11,913,408,512 B / 1024² = 11,361.5 MiB | MATCH |
| 21 | Validate 8 PASS / 1 FAIL / 7 MANUAL preserved | Not re-run (would require validate_entities.py invocation) | UNVERIFIABLE |
| 22 | 5 Securian SFT series ($1.26B) residual | Not spot-checked | UNVERIFIABLE |
| 23 | Header declares HEAD `8323838` | Actual HEAD `da418a1` — docs-close commit, cannot self-reference; prompt acknowledges | CLEAN (convention) |

### 4.3 Prior-session spot checks (session #10)

- "108-series Voya DM14c retarget" — commit `8136434` title matches; count not recomputed in DB. PARTIAL.
- "entities 24,895 (+34), fund_holdings_v2 14,090,397" — current `entities` 26,535 confirms session #10 baseline; `fund_holdings_v2` unchanged at 14.09M. MATCH.
- "Amundi US → Victory Capital re-route (eid 4294+830 → 24864)" — not spot-checked in this pass. UNVERIFIABLE.

### 4.4 Open / pending items

- Next-priority **`load_13f_v2.py`** (Q1 2026 13F fetch, May 16 window) — no commit yet; open. Directly intersects §1.4 coverage collapse and §3.5 P-01.
- Admin Refresh System — no commit yet; open. Prompt §"Why this audit exists" acknowledges this workstream is paused.
- Accepted gaps: 5 Securian SFT series ($1.26B); DM15 umbrella-trust audit (~132 series / $105B).
- LEI coverage = 0; `entity_identifiers_staging_review` backlog ~280 items — still open.
- No items found that are complete per git/DB but still flagged open.

### 4.5 Drift summary — Roadmap

| # | Finding | Evidence | Label |
|---|---|---|---|
| R-01 | Roadmap claims 928 13DG exclusions; DB has 931 | `SELECT COUNT(*) FROM pending_entity_resolution WHERE source_type='13DG'` = 931 | **DRIFT-SUSPECTED** (small; possibly post-commit adds) |
| R-02 | Roadmap + commit `938e435` both claim "4 NULL-CIK" overrides in 205-221; DB has 5 NULLs | `COUNT FILTER (WHERE new_value IS NULL) WHERE override_id BETWEEN 205 AND 221` = 5 | **DRIFT-CONFIRMED** |
| R-03 | Session #11 encoded as italicized top-of-file paragraphs instead of `## Session Summary` H2 | Line 3 vs lines 23/90/111 | CLEAN (stylistic) |
| R-04 | Roadmap pins to HEAD `8323838`; actual HEAD `da418a1` is docs-close commit | `git log --oneline -1` | CLEAN (convention — docs commit cannot self-pin) |

### 4.6 Section verdict

**CLEAN-WITH-MINOR-DRIFT.** Of 23 claims, 16 MATCH / 3 PARTIAL / 2 DRIFT-CONFIRMED / 2 UNVERIFIABLE. All headline prod counters hit exactly. Two numeric discrepancies (931 vs 928 exclusions, 5 vs 4 NULL-CIK overrides); the second originates in commit-message prose, so roadmap faithfully mirrors the commit's self-miscount.

### 4.7 Pass 2 deep-dive flags (Roadmap)

1. Override 220 (`S000093461`, NULL new_value) — narrative vs count reconciliation (5 NULLs listed per commit body but prose says 4).
2. 3-row gap in `pending_entity_resolution` 13DG — were rows added post-`5efae66`?
3. `entity_classification_history` SCD semantics for eid=2214 — sentinel for "active" state.
4. Session #11 stylistic inconsistency — retrospective H2 for backward-accounting grep-ability?
5. "81/84 fund_universe series covered" — confirm via `ncen_adviser_map × fund_universe` join.
6. "108-series Voya DM14c retarget" — recount `entity_rollup_history` children of eid 2489 at `rollup_type='decision_maker_v1'`.

---

## 5. Documentation Freshness — **DRIFT-CONFIRMED (root-level concentrated)**

Core data/pipeline docs in `docs/` maintained and fresh as of HEAD. Drift concentrates in root-level README + PHASE prompts.

### 5.1 Per-doc inventory

| Doc path | Last-modified | Size (B) | Staleness | Note |
|---|---|---:|---|---|
| `README.md` | 2026-04-13 | 5,550 | **STALE** | Lists retired `update.py` master + missing Blueprint/React tree — §5.2.1 |
| `ARCHITECTURE_REVIEW.md` | 2026-04-15 | 39,802 | FRESH | Has §0 delta refresh 2026-04-15 — but §1 internal contradiction (§5.4.4) |
| `ENTITY_ARCHITECTURE.md` | 2026-04-17 | 64,280 | FRESH | Session #11 aligned; `entity_current` still a view (`entity_schema.sql:296`) |
| `MAINTENANCE.md` | 2026-04-10 | 4,069 | FRESH | Referenced scripts exist |
| `REACT_MIGRATION.md` | 2026-04-13 | 6,232 | STALE | Line 121 overstates `web/templates/` deletion — `admin.html` still on disk |
| `PHASE1_PROMPT.md` | n/a (untracked) | 9,826 | **ORPHANED** | `.gitignore:49`; historical artifact |
| `PHASE3_PROMPT.md` | 2026-04-12 | 2,825 | **ORPHANED** | Track C runs retired `fetch_nport.py` |
| `PHASE4_PROMPT.md` | 2026-04-09 | 17,023 | **ORPHANED** | Describes completed cutover |
| `PHASE4_STATE.md` | 2026-04-10 | 4,210 | FRESH | Self-dated 2026-04-09 |
| `README_deploy.md` | 2026-04-01 | 1,887 | STALE | Missing React `npm run build` step |
| `docs/PROCESS_RULES.md` | 2026-04-09 | 4,918 | FRESH | §8 still cites retired `fetch_13dg.py` — §5.4.1 |
| `docs/CLASSIFICATION_METHODOLOGY.md` | 2026-04-09 | 3,583 | FRESH | 20,205 entities cited vs current 26,535 |
| `docs/ci_fixture_design.md` | 2026-04-13 | 9,813 | FRESH | |
| `docs/endpoint_classification.md` | 2026-04-13 | 5,904 | FRESH | |
| `docs/write_path_risk_map.md` | 2026-04-13 | 7,895 | **STALE** | T2 list names retired / rewritten scripts |
| `docs/canonical_ddl.md` | 2026-04-15 | 18,646 | FRESH | |
| `docs/pipeline_violations.md` | 2026-04-15 | 17,050 | FRESH | CLEARED labels hold at HEAD (§2.2 verified) |
| `docs/13DG_ENTITY_LINKAGE.md` | 2026-04-16 | 7,619 | FRESH | Migration 005 present |
| `docs/NEXT_SESSION_CONTEXT.md` | 2026-04-17 | 164,476 | FRESH | 164 KB monolith |
| `docs/data_layers.md` | 2026-04-17 | 37,208 | FRESH | Headline claim (84.47% fund_holdings_v2 entity coverage) now materially wrong — see §1.2 |
| `docs/pipeline_inventory.md` | 2026-04-17 | 33,134 | FRESH | SUPERSEDED labels accurate |

### 5.2 Orphaned-reference spot checks

**5.2.1 `README.md` — orphaned entry points.**
- Line 35–38 names `python3 scripts/update.py` → `auto_resolve.py` as master pipeline. Both listed under backlog-to-retire in `pipeline_inventory.md:107`.
- Line 95 Datasette instructions on port 8002 — works, but legacy guidance post-React cutover.
- Line 119 project tree omits `web/react-app/`, `scripts/pipeline/`, `scripts/migrations/`, `scripts/api_*.py`.

**5.2.2 `PHASE3_PROMPT.md:47-48` — broken script reference.** Commands `python3 -u scripts/fetch_nport.py --test`; `pipeline_inventory.md:52` marks the script SUPERSEDED.

**5.2.3 `REACT_MIGRATION.md:121`** — claims `web/templates/` retired wholesale; `admin.html` remains on disk.

**5.2.4 `README_deploy.md:47`** — start command `python scripts/app.py --port $PORT`; missing prerequisite `cd web/react-app && npm run build` per `REACT_MIGRATION.md:120`.

**5.2.5 `docs/write_path_risk_map.md:55-59`** — T2 list includes `unify_positions.py` (retired to `scripts/retired/`), `build_cusip.py` (rewrite shipped), `compute_flows.py` (rewrite shipped).

### 5.3 Missing-doc coverage

1. `scripts/api_*.py` Blueprint package — 8 files, only a routing table in `endpoint_classification.md:67-75`; no architecture doc.
2. `scripts/pipeline/` package — `cusip_classifier.py`, `discover.py`, `manifest.py`, `protocol.py`, `registry.py`, `shared.py` — no doc of SourcePipeline / DirectWritePipeline protocols.
3. `resolve_13dg_filers.py` + `data/reference/13dg_filer_research_v2.csv` — only mentioned in `NEXT_SESSION_CONTEXT.md:3`.
4. `scripts/migrations/` — 8 migrations on disk, only migration 005 has a dedicated doc; no chronology.
5. `scripts/admin_bp.py` admin routes — no inventory of `/api/admin/*`.

### 5.4 Contradictions between docs

1. `docs/PROCESS_RULES.md:94` says `fetch_13dg.py` is the canonical parser; `docs/pipeline_violations.md:47` marks it SUPERSEDED.
2. `PHASE3_PROMPT.md:44` Track C: "`fund_holdings_v2` stale — last fetch Oct 2025"; `data_layers.md:92` shows newest `report_date` 2026-02-28 (now partial through 2026-03).
3. `README.md:38` ↔ `pipeline_inventory.md:107-120` — `update.py` promoted as master vs backlog-to-retire.
4. `REACT_MIGRATION.md:121` ↔ `ARCHITECTURE_REVIEW.md:51` — Phase 4 cutover complete vs Phase 4 pending (internal contradiction within ARCHITECTURE_REVIEW: §0 delta says complete, §1 still reads pending).
5. `docs/write_path_risk_map.md:55-59` ↔ `docs/pipeline_violations.md:36-57` + `scripts/retired/` — T2 list names scripts that are either rewritten or retired.

### 5.5 Drift summary — Docs

| # | Finding | Evidence | Label |
|---|---|---|---|
| DOC-01 | README.md lists retired `update.py` master | `README.md:23-38,107-122` | **DRIFT-CONFIRMED** |
| DOC-02 | README project tree omits Blueprint, React, pipeline, migrations | `README.md:109-140` | **DRIFT-CONFIRMED** |
| DOC-03 | PHASE3 Track C runs retired `fetch_nport.py` | `PHASE3_PROMPT.md:47-48` | **DRIFT-CONFIRMED** |
| DOC-04 | ARCHITECTURE_REVIEW §1 says Phase 4 pending; Phase 4 shipped | `:51` vs `REACT_MIGRATION.md:120` | **DRIFT-CONFIRMED** |
| DOC-05 | README_deploy omits React build step | `README_deploy.md:47` | **DRIFT-CONFIRMED** |
| DOC-06 | write_path_risk_map T2 list includes retired/rewritten scripts | `:55-59` | **DRIFT-CONFIRMED** |
| DOC-07 | PROCESS_RULES §8 parser-sync mandate names retired `fetch_13dg.py` | `:89-99` | **DRIFT-CONFIRMED** |
| DOC-08 | REACT_MIGRATION overstates `web/templates/` deletion | `:121` vs `ls web/templates/` | **DRIFT-SUSPECTED** |
| DOC-09 | CLASSIFICATION_METHODOLOGY cites 20,205 entities vs 26,535 | `:11` | **DRIFT-SUSPECTED** |
| DOC-10 | PHASE1_PROMPT.md untracked; PHASE3/PHASE4_PROMPT.md tracked but orphaned | file + `.gitignore:49` | **DRIFT-CONFIRMED** |
| DOC-11 | `data_layers.md:92` headline coverage claim 84.47% now wrong (actual 40.09%) | §1.2 | **DRIFT-CONFIRMED** (caused by §1 DRIFT, not doc neglect) |
| DOC-12 | No architectural doc for `scripts/api_*.py` Blueprint split | — | **DRIFT-SUSPECTED** (gap) |

### 5.6 Section verdict

**DRIFT-CONFIRMED (YELLOW).** `docs/*` is actively maintained — six docs have git-dates within the last 5 days. Root-level ring is where the drift lives — README + PHASE prompts + README_deploy predate the Blueprint/React/retired-script cleanup.

### 5.7 Pass 2 deep-dive flags (Docs)

1. ARCHITECTURE_REVIEW §1–§9 vs §0 delta — likely more internal contradictions than just finding DOC-04.
2. Full inventory of `docs/NEXT_SESSION_CONTEXT.md` (164 KB) for superseded state.
3. Import-graph scan — any `pipeline_inventory.md:107-120` retired scripts still imported?
4. PHASE1/3/4 retention policy — retire vs move to `docs/history/`?
5. Grep `docs/` for non-v2 ghost-table names (`holdings`, `beneficial_ownership`, `fund_holdings`).
6. Refresh `data_layers.md:92` coverage number (or treat §1 DRIFT as the forcing fix, not the doc).

---

## 6. Operational State — **AMBER**

### 6.1 Git

- `main` @ `da418a1`, 0 ahead / 0 behind origin.
- `git status --short` → `?? Plans/` (untracked dir; contains `admin_refresh_system_design.md` 47 KB + `data_sources.md` 12 KB, both 2026-04-17).
- Stashes: none.
- Worktrees: 8 total. Stale HEADs: `confident-rhodes` @ `53d6e7b`, `charming-haibt` @ `7c51a21`, `distracted-borg` @ `7c51a21`, `sleepy-shtern` @ `a221202`. Current: `jovial-mestorf` and `competent-meitner-ac5cdf` @ `da418a1`. `intelligent-ellis` @ `8323838` is the prompt-referenced HEAD (one behind).
- Orphan branches (no worktree): `claude/elegant-ptolemy`, `claude/mystifying-bouman`, `claude/nostalgic-goldberg`.
- No `--no-verify` bypass in recent commit log (grep hits are INF14 tech-debt doc commits).

### 6.2 Backups

| Backup | Size | mtime |
|---|---|---|
| 13f_backup_20260410_122411 | 2.7 G | Apr 10 13:24 |
| 13f_backup_20260413_184518 | 2.7 G | Apr 13 18:45 |
| 13f_backup_20260413_222950 | 2.1 G | Apr 13 22:29 |
| 13f_backup_20260414_040227 | 1.6 G | Apr 14 04:02 |
| 13f_backup_20260414_053433 | 1.6 G | Apr 14 05:34 |
| **13f_backup_20260417_172152** | **2.6 G** | Apr 17 17:22 |

- Pre-audit backup confirmed.
- 3d 12h gap between most-recent and second-most-recent. Apr 14 backups notably smaller (1.6 G vs 2.6–2.7 G surrounding) — partial-state risk.

### 6.3 Logs

- 182 entries total; oldest `nport_build.log` 2026-04-01 (rotation candidate).
- 47 `Traceback|ERROR|FAILED` hits across 16 files in last 24 h; spot samples:
  - `staging_sync.log` — 9 hits, all historical Apr 10 binder/constraint errors retained in rolling log.
  - `promotion_history.log` — `validation FAILED (rc=1) — auto-restoring snapshot` 2026-04-10; auto-restore behaved correctly.
  - Crash breadcrumbs: `fetch_13dg_crash.log` (4), `fetch_market_crash.log` (3), `fetch_nport_crash.log` (2), `fetch_nport_v2_crash.log` (2).
- `ncen_routing_drift.log` Apr 17 13:12 — clean.

### 6.4 Disk

- `df -h /System/Volumes/Data` — 460 G total, 290 G used (69%), **136 G free**. Healthy.
- Top consumers:
  - `data/13f.duckdb` — 11 G
  - `data/13f_readonly.duckdb` — 11 G (duplicate mirror — worth confirming policy)
  - `data/backups/` — 13 G total
  - `data/13f_staging.duckdb` — 1.3 G
  - `logs/` — 31 M

### 6.5 EDGAR identity

- `serge.tismen@gmail.com` consistent across 22+ scripts.
- Two UA string conventions: `"13f-research serge.tismen@gmail.com"` (majority) vs `"13f-ownership-research serge.tismen@gmail.com"` (`sec_shares_client.py:46`). Some scripts (`reparse_*`, `resolve_*`, `resolve_bo_agents.py`) use bare email.
- **No central UA config.** `scripts/config.py` only holds quarter/URL data; identity inlined per-script.
- No `.env` files present (verified).
- `edgartools.set_identity` called in `fetch_13dg.py:44`, `fetch_nport.py:105`, `fetch_nport_v2.py:424`, `admin_bp.py:150`, `pipeline/discover.py:172` — all pass the correct email.

### 6.6 Dependencies

`requirements.txt` — 14 packages, all pinned: datasette, duckdb 1.4.4, fastapi, httpx, jinja2, openpyxl, pandas 2.3.3, pydantic, rapidfuzz, requests, tabulate, tqdm, uvicorn, yfinance 1.2.0.

**Runtime-critical packages NOT in requirements.txt:**
- Flask 3.1.3 (imported by `app.py`, `admin_bp.py`).
- edgartools 4.6.3.
- pdfplumber 0.11.8.

`smoke.yml` workflow does **not install Flask** — smoke tests can pass while runtime boot fails.

### 6.7 CI / pre-commit

- `.pre-commit-config.yaml` — ruff v0.15.9, pylint v3.3.6, bandit 1.8.3. Wide pylint/bandit rule set disabled as "Phase 0-A baseline cruft" with ROADMAP INF14 tracking. Semgrep intentionally omitted (Py3.9/macOS incompatibility).
- `.bandit` — `skips: B608`.
- `.github/workflows/lint.yml` — `pre-commit run --all-files` on push-main / PR (Python 3.11).
- `.github/workflows/smoke.yml` — pytest against committed fixture DB; does not install Flask or edgartools.
- No `--no-verify` bypass in recent commit history.

### 6.8 Flask app state

- Port 8001: **not bound** (`lsof -i :8001` empty).
- No `flask|uvicorn|app.py` process running.
- Port 5000 bound by macOS `ControlCenter` (AirPlay Receiver), unrelated.

### 6.9 Drift summary — Operational

| # | Finding | Evidence | Label |
|---|---|---|---|
| O-01 | Untracked `Plans/` in repo root (2 design docs, 59 KB) | `git status --short` | **DRIFT-SUSPECTED** |
| O-02 | Flask, edgartools, pdfplumber installed but not in `requirements.txt` | `pip list` vs `requirements.txt` | **DRIFT-CONFIRMED** |
| O-03 | `smoke.yml` does not install Flask | `.github/workflows/smoke.yml` | **DRIFT-CONFIRMED** |
| O-04 | `13f_readonly.duckdb` duplicates `13f.duckdb` at 11 G each | `du -sh` | **DRIFT-SUSPECTED** |
| O-05 | Backup gap 3d12h; Apr 14 snapshots 1.6 G (partial?) vs surrounding 2.6–2.7 G | `ls -la data/backups/` | **DRIFT-SUSPECTED** |
| O-06 | 3 stale worktrees (`confident-rhodes`, `charming-haibt`/`distracted-borg`, `sleepy-shtern`) | `git worktree list` | **DRIFT-SUSPECTED** |
| O-07 | 3 orphan branches with no worktree | `git branch -a` | **DRIFT-SUSPECTED** |
| O-08 | Divergent UA strings + bare-email-only scripts; no central config | grep across `scripts/` | **DRIFT-SUSPECTED** |
| O-09 | Flask app not running (expected snapshot, not a defect) | `lsof` empty | CLEAN |
| O-10 | Log rotation policy missing (182 files back to Apr 1) | `ls -la logs/` | **DRIFT-SUSPECTED** |
| O-11 | Pre-commit disables wide pylint/bandit set as Phase 0-A debt | `.pre-commit-config.yaml` | CLEAN (documented INF14) |

### 6.10 Section verdict

**AMBER.** Stable tip, reliable backup, healthy disk, consistent EDGAR email, green logs. Housekeeping drift is real but non-blocking: unpinned runtime deps + smoke CI gap (highest priority), stale worktrees/branches, untracked `Plans/`, divergent UA strings.

### 6.11 Pass 2 deep-dive flags (Ops)

1. **Deps drift (P1)** — `import` graph audit; pin Flask/edgartools/pdfplumber; smoke CI boots `app.py` end-to-end.
2. **`13f_readonly.duckdb` policy (P2)** — hot-swappable replica, stale artifact, or refresh leftover?
3. **Worktree + orphan-branch GC (P3)**.
4. **`Plans/` directory (P2)** — commit to `docs/history/` or add to `.gitignore`?
5. **UA centralization (P3)** — single `scripts/config.py` constant.
6. **Backup cadence (P2)** — investigate Apr 14 1.6 G shrinkage and 3.5d gap; nightly cron status.
7. **Log rotation (P3)**.
8. **Pre-commit disabled-rules backlog (P3)** — quantify INF14.

---

## 7. Drift Concentration Map

Drift ranked by DRIFT-CONFIRMED density. Drives Pass 2 scoping.

| Rank | Category | Confirmed | Suspected | Dominant theme |
|---|---|---:|---:|---|
| 1 | **Data Integrity** (§1) | 5 | 5 | N-PORT post-promote enrichment collapsed (entity_id 40.09% overall → 0.18% in 2025-11); CUSIP-in-`securities` 31.48% orphan rate; `ingestion_impacts` grain gaps for 13DG/NCEN/ADV. |
| 2 | **Documentation Freshness** (§5) | 8 | 3 | Root-level README + PHASE prompts + `README_deploy.md` + `write_path_risk_map.md` + `PROCESS_RULES.md:§8` all predate Blueprint/React/retired-script cleanups. `data_layers.md:92` headline is now wrong but that's downstream of §1. |
| 3 | **Code Integrity** (§2) | 5 | 6 | Five unlisted direct-to-prod writers (`resolve_agent_names.py`, `resolve_bo_agents.py`, `resolve_names.py`, `backfill_manager_types.py`, `enrich_tickers.py`); two validators opening prod RW; hardcoded-prod builders (`build_managers.py`, `build_fund_classes.py`, `build_benchmark_weights.py`). |
| 4 | **Pipeline Health** (§3) | 3 | 3 | ADV silent (no log, no stamp); 13F has no freshness writer; Market `impact_id` race recurred post-fix. |
| 5 | **Operational State** (§6) | 2 | 7 | Unpinned runtime deps (Flask/edgartools/pdfplumber) + smoke CI gap; plus housekeeping drift (worktrees, branches, UA strings, backup cadence, log rotation). |
| 6 | **Roadmap vs Reality** (§4) | 1 | 1 | Mostly clean — roadmap counters reconcile to DB. Only numeric drift: `pending_entity_resolution` 13DG 931 vs 928, and override NULL-CIK count 5 vs 4 (commit-message mirrored). |

**Pass 2 scope recommendation:** unpack §1 and §5 deeply. §2 and §3 deserve targeted spot-fixes (Finding C-05 and P-04 specifically). §4 and §6 can be skipped in deep form; handle as punch-list.

---

## 8. Flags for Pass 2 Deep Dive (consolidated)

**Critical (merge-blocking candidates):**
- §1 D-01 + D-02 — fund_holdings_v2 entity_id collapse; root-cause in `promote_nport.py` Group-2 enrichment or gate logic.
- §1 D-03 — 297K distinct CUSIPs in `fund_holdings_v2` not in `securities`; `build_cusip.py` universe coverage.
- §3 P-04 — Market `impact_id` duplicate-PK race; `manifest._next_id` transaction coupling.

**High (silent-drift, affects trust in freshness signals):**
- §1 D-05 — legacy `fund_holdings` still receiving writes (trace writer).
- §3 P-01 — 13F TSV loader freshness writer (load_13f_v2 build).
- §3 P-02 — ADV pipeline last-run observability.
- §1 D-06 + §1 D-07 — `ingestion_manifest/impacts` grain + missing sources (NCEN/ADV).

**Medium (staging-discipline + doc-reality alignment):**
- §2 C-05 — five unlisted direct-to-prod writers; add to `pipeline_violations.md`.
- §2 C-02/C-03 — validators holding prod write locks.
- §5 DOC-01 + DOC-02 + DOC-04 + DOC-07 — README + ARCHITECTURE_REVIEW §1 + PROCESS_RULES §8 refresh.

**Low (housekeeping):**
- §4 R-01 + R-02 — reconcile roadmap numeric drift.
- §6 O-02 + O-03 — pin Flask/edgartools/pdfplumber; smoke CI with Flask.
- §6 worktree/branch/logs/backup housekeeping.

---

## 9. Flags for Codex (Reviewer 2)

Contradictions Pass 1 found between documented behavior and code/DB state that Codex should cross-check against any remaining undocumented surface:

1. **Doc promise vs DB reality on `fund_holdings_v2` entity_id coverage** (`data_layers.md:92` 84.47% vs actual 40.09%). Pass 2 should trace the enrichment call path and confirm whether the doc number was ever true or always aspirational.
2. **`ingestion_impacts` grain inconsistency** — NPORT has 21k rows per accession; 13DG has 3 rows ZIP-level; MARKET has 8k rows per-symbol batch. Is the grain contract documented anywhere?
3. **`fetch_adv.py` freshness path** — script ostensibly calls `record_freshness` (per `pipeline_inventory.md:21`) but no `data_freshness` row for `adv_managers` exists. Either the call is dead or the hook was never wired.
4. **Session #11 header pin** — roadmap pins `HEAD: 8323838` but actual HEAD at audit was `da418a1` (the docs commit that includes the pin). Not a defect, but the convention choice should be explicit in a docs process doc.
5. **Override NULL-CIK miscount** — commit message `938e435` and ROADMAP both say "4 NULL-CIK"; DB has 5. Commit prose under-counted. Worth tracing which series was added without being called out in the prose.
6. **Legacy `fund_holdings` writer** — table is documented dropped, yet `loaded_at` 2026-04-14 21:22. Codex should trace the writer; Pass 1 did not identify which script lands these rows.
7. **ARCHITECTURE_REVIEW internal contradiction** — §0 delta says Phase 4 done, §1 still reads Phase 4 pending. Whichever Pass 2 inspects first will be inconsistent with the other.
8. **Five originally-cited contradictions** (prompt §"Why this audit exists"): Pass 1 did not re-verify these specifically — Pass 2 should map them onto this atlas and confirm each is still live.
9. **`PHASE1_PROMPT.md` untracked, `PHASE3/PHASE4_PROMPT.md` tracked** — retention asymmetry. Either all PHASE prompts are historical artifacts (and should consistently be archived or gitignored) or they serve a live purpose (in which case PHASE1 should be tracked).
10. **`Plans/` directory** — 59 KB of design notes untracked. Is this deliberate scratch space, or should it live in `docs/` (perhaps under a `docs/plans/` that already exists per the worktree `ls docs/`)?

---

*End of atlas. Pass 2 reviewer: continue with deep-dives on §1 and §5. Do not modify this doc — extend or produce a companion review.*
