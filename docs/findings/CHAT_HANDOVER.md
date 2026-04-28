# Chat Handover — 2026-04-27 (conv-15 close)

## State

HEAD: `2ca71f7` (post-PR #187, 43g — 3 redundant write-only v2 columns dropped, migration 022)
Migrations: 001–022 applied (022 = `drop_redundant_v2_columns`, this leg)
Open PRs:
- **#172** — `dm13-de-discovery: triage CSV for residual ADV_SCHEDULE_A edges` (intentional, paired with #173 apply; close after reconciling)
- **#107** — `ui-audit-walkthrough` (intentional; needs live Serge+Claude session, not a Code session)
- **(this PR)** — `conv-15-doc-sync`
P0: empty.
P1: `ui-audit-walkthrough` only (live walkthrough).
P2: `ui-audit-01 perf-P2` (`flow_analysis` + `market_summary` + `holder_momentum` precompute) — moved Deferred → P2 by PR #183.
P3: `BL-3 Write-path consistency (non-entity)` (PR #183), `D10 Admin UI for entity_identifiers_staging` (PR #183), `INF53 BACKFILL_MIG015 multi-row investigation` (PR #186 follow-up).
Worktrees: this branch (`conv-15-doc-sync` / worktree `gifted-joliot-dc6ce8`) only.

## Session arc 2026-04-26/27 — 19 PRs (#169–#187)

The arc spans two consecutive sessions stitched together by `conv-14-doc-sync` (PR #182). conv-14 closed the DM13 sweep + the perf-P1 wave (#169–#181, 12 merged + 1 still-open) and was summarised by PR #182. **conv-15** (this leg) covers **#183–#187 — 5 merged**, the focus shifting from entity / perf work to N-PORT pipeline hardening, prod-dedup hygiene, schema drop, and roadmap re-prioritization.

### Full 19-PR table

| PR | Slug | Notes |
|---|---|---|
| #169 | DM13-B/C apply | 107 non-operating / redundant `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 389–495. Promote `20260426_171207`. |
| #170 | DM15f / DM15g hard-delete | StoneX→StepStone (rel 14408) + Pacer→Mercer (rel 12022) `wholly_owned` edges hard-`DELETE`d along with their B/C suppression overrides (425, 488). |
| #171 | pct-rename-sweep | Doc/naming-only. 283 substitutions across 32 files retiring `pct_of_float` / `pct-of-float` / `PCT-OF-FLOAT` references. Migration 008 filename + 39 rename-narrative lines preserved. |
| #172 | dm13-de-discovery | **OPEN.** Triage CSV for residual ADV_SCHEDULE_A edges (consumed by #173 apply). |
| #173 | DM13-D/E apply | 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 496–1054. Promote `20260427_045843`. **DM13 sweep fully closed.** |
| #174 | DM15d no-op | 0 re-routes. The 3 N-CEN-coverable trusts (Sterling Capital / NEOS / Segall Bryant) are all single-adviser (52 rows all `role='adviser'`, zero `role='subadviser'`); DM rollup already correct. |
| #175 | conv-13 doc sync | Refreshed `NEXT_SESSION_CONTEXT.md` / `ENTITY_ARCHITECTURE.md` header / `MAINTENANCE.md` / `CHAT_HANDOVER.md` post-DM13 wave. |
| #176 | INF48 / INF49 | NEOS dup eid=10825 → canonical eid=20105; SBH dup eid=254 → canonical eid=18157. Suspect CRD `001006378` excluded from transfer (numerically identical to its CIK). Override IDs 1055 + 1056. Promote `20260427_064049`. |
| #177 | react-cleanup-inf28 | React-1: shared `useTickers.ts` module-cached hook (3 fetches → 1). React-2: extracted `fetchEntitySearch(q)` helper at module scope in `EntityGraphTab.tsx`. INF28: `promote_staging.VALIDATOR_MAP['securities']` → `schema_pk`. No DB writes. |
| #178 | dead-endpoints | 11 of 15 router-defined uncalled `/api/v1/*` routes deleted; 4 kept (`export/query{qnum}`, `crowding`, `smart_money`, `peer_groups/{group_id}`). 2 query helpers deleted (`get_sector_flow_detail`, `get_short_long_comparison`). |
| #179 | perf-p1-discovery | Scoping doc `docs/findings/perf-p1-scoping.md` (sector flows / movers / cohort precompute analysis). |
| #180 | perf-P1 part 1 | New `sector_flows_rollup` precompute (321 rows, migration 021). New `compute_sector_flows.py` `SourcePipeline` subclass (~2.1s rebuild). `queries.get_sector_flows` rewritten to read precomputed; `get_sector_flow_movers` `level='parent'` rewritten to read `peer_rotation_flows`. Latency: parent 1242ms → 4ms (310×); fund 1119ms → 5ms (224×); movers parent 335-405ms → 22-36ms (~12×). |
| #181 | perf-P1 part 2 | `cohort_analysis` 60s TTL cache. New `CACHE_KEY_COHORT` + `CACHE_TTL_COHORT=60`; `cached()` extended with optional `ttl=`. Cold 777-934ms → warm 0.01-0.05ms (>10,000× on a hit). **Closes perf-P1.** |
| #182 | conv-14-doc-sync | End-of-leg doc sync. Full rewrite of `NEXT_SESSION_CONTEXT.md` + `CHAT_HANDOVER.md`; ENTITY_ARCHITECTURE.md header refresh; MAINTENANCE.md "Precompute / rollup pipelines" subsection. ROADMAP verification date `2026-04-25 → 2026-04-27`; **43g moved Deferred → P3** by audit. |
| #183 | roadmap-priority-moves | Three Deferred items activated ahead of VPS hosting / Q1 2026 cycle: `perf-P2` → P2; `BL-3` write-path consistency + `D10` admin UI for `entity_identifiers_staging` → P3. Pure roadmap re-prioritization. |
| #184 | nport-refresh-catchup | N-PORT monthly-topup +478,446 rows / 1,164 NPORT-P accessions; 71 `is_latest` flips. Two pipeline blockers worked around in-session and logged: stale `stg_nport_holdings` (11.1M from Apr 15 silent-failed cleanup, manually purged); **INF52** int-23 vs entity-enrich ordering. Pre-promote backup `data/backups/13f_backup_20260427_131151` (3.1 GB). |
| #185 | inf50-52-nport-pipeline-fixes | Code-only N-PORT pipeline hardening. INF50: `_cleanup_staging` rewritten to drop all 3 staging tables on one connection with post-cleanup `CatalogException` assertion + `_purge_stale_raw_staging` at start of `fetch()`. INF52: new `_enrich_staging_entities` mirrors `_bulk_enrich_run`'s JOIN and runs in `LoadNPortPipeline.promote()` BEFORE `super().promote()`. 6 new unit tests; 230/230 smoke + pipeline pass. **Not yet exercised against prod.** |
| #186 | INF51 prod-dedup | Investigation reframed prompt's premise. 5.53M apparent dupes → only **68 rows / 64 groups** are byte-identical (deleted); 5.59M / 55,924 are value-divergent (kept under spec carve-out). `fund_holdings_v2` 14,568,843 → 14,568,775. **INF53** logged as P3 follow-up (BACKFILL_MIG015 multi-row pattern, 54,437 of 55,924 affected groups originate from `BACKFILL_MIG015_*` accessions). Pre-DELETE backup `data/backups/13f_backup_20260427_191936` (3.2 GB). |
| #187 | 43g-drop-redundant-columns | Migration 022 stamped. 3 write-only columns dropped: `holdings_v2.crd_number`, `holdings_v2.security_type`, `fund_holdings_v2.best_index`. Rebuild path (DuckDB 1.4 limitation). 38s wall on 25 GB prod DB. 12.27M holdings_v2 + 14.57M fund_holdings_v2 rows preserved. Writer-side cleanups co-shipped. AAPL + EQT smoke-tested across 8 endpoints; pytest 364 passed; `total_aum` PASS at 0.0% diff. **Closes P3 43g.** |

## DM13 grand total (closed in conv-14, recap)

**797 relationships suppressed + 2 hard-deleted across 4 PRs:**

| PR | Category | Count | Override IDs |
|---|---|---|---|
| #168 | A — self-referential edges | 131 | 258–388 |
| #169 | B+C — non-operating / redundant | 107 (now 105 in DB after #170 deletes) | 389–495 |
| #170 | DM15f/g — hard-DELETE (subset of B/C false-positives) | 2 | (425, 488 deleted) |
| #173 | D+E — dormant / residual | 559 | 496–1054 |
| **Total** | | **797 suppressed + 2 deleted** | |

## INF48 + INF49 (conv-14 wave, recap)

| PR | Item | Dup eid → Survivor eid | New override_id |
|---|---|---|---|
| #176 | INF48 NEOS Investment Management | 10825 → 20105 | **1055** |
| #176 | INF49 Segall Bryant & Hamill | 254 → 18157 | **1056** |

## Prod entity-layer state (read-only `data/13f.duckdb`, HEAD `2ca71f7`)

| Metric | Value | Δ vs conv-14 close |
|---|---|---|
| `entities` | **26,602** | unchanged |
| `entity_overrides_persistent` rows | **1,054** | unchanged |
| `MAX(override_id)` | **1,056** (gaps at 425, 488 from #170 hard-deletes) | unchanged |
| `entity_rollup_history` open `economic_control_v1` | 26,602 | unchanged |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 (DM1 parity holds) | unchanged |
| `entity_relationships` total / active | **18,363 / 16,316** | unchanged |
| `entity_aliases` | 26,943 | unchanged |
| `entity_identifiers` | 35,516 | unchanged |
| `ncen_adviser_map` | 11,209 | unchanged |
| `sector_flows_rollup` (migration 021) | 321 | unchanged |
| `holdings_v2` rows / cols | 12,270,984 / **36** | cols −2 (PR #187: dropped `crd_number` + `security_type`) |
| `fund_holdings_v2` rows / cols | **14,568,775** / **29** | rows −68 (PR #186 INF51) + 478,446 (PR #184 topup); cols −1 (PR #187: dropped `best_index`) |

Validate baseline preserved through every promote in the leg: **8 PASS / 1 FAIL (`wellington_sub_advisory`) / 7 MANUAL** (long-standing non-structural baseline; no auto-rollback fired).

## P0 / P1 / P2 / P3 status

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (live walkthrough — not a Code session).
- **P2:** `ui-audit-01 perf-P2` (`flow_analysis` + `market_summary` + `holder_momentum` precompute) — activated by PR #183 ahead of VPS hosting.
- **P3:** `BL-3 Write-path consistency (non-entity)` (PR #183), `D10 Admin UI for entity_identifiers_staging` (PR #183), `INF53 BACKFILL_MIG015 multi-row investigation` (PR #186 follow-up). **43g closed** by PR #187.

## INF50 + INF52 — pending live verification

Both fixes are **code-only and have not been exercised against prod yet.** Live test triggers, in order:

1. **Next monthly N-PORT topup that touches amendments** — exercises both `_purge_stale_raw_staging` (INF50) and `_enrich_staging_entities` (INF52).
2. **Q1 2026 N-PORT DERA bulk, ~late May 2026** — full integration test.

If the post-cleanup `CatalogException` assertion ever fires, capture the full `RuntimeError("...staging is contaminated...")` — that is the actual root cause of the prior silent failure, finally visible.

## INF53 — new P3 follow-up

Surfaced 2026-04-27 during INF51 dedup discovery (PR #186). `fund_holdings_v2` has 55,924 groups (5,587,231 rows) with the same `(series_id, report_month, accession_number, cusip)` key but different `shares_or_principal` / `market_value_usd` / `pct_of_nav` values. **54,437 of those groups originate from `BACKFILL_MIG015_*` accessions** (5,516,217 rows); the remaining 1,551 groups (71,146 rows) are from real N-PORT filings, dominated by placeholder CUSIPs (`000000000` / `N/A`) representing many distinct unidentified positions. Determine whether multi-row-per-key is by design (multiple lots / placeholder CUSIPs aggregating distinct positions) or a migration bug. Inventory at `data/reports/inf51/value_divergent_groups_20260427_192000.csv`.

## N-PORT data status

| Report month | Rows | Notes |
|---|---|---|
| 2026-03 | 3,379 | Partial. 60-day SEC public-release lag — Q1 2026 DERA bulk lands ~late May 2026. |
| 2026-02 | 476,173 | Mostly complete. Filings closing toward Apr 30 deadline; final stragglers may land in next monthly topup. |
| 2026-01 | 1,321,367 | Full. |
| 2025-12 | 2,514,497 | Full. |
| 2025-11 | 2,001,775 | Full. |

## Schema migrations applied this leg

- **022_drop_redundant_v2_columns** (PR #187, 2026-04-27) — drops `holdings_v2.crd_number`, `holdings_v2.security_type`, `fund_holdings_v2.best_index` via per-table rebuild. 38s on 25 GB prod DB.

## Deferred-item audit (PRs #183–#187)

| Item | Trigger | Trigger met (Y/N) | Evidence |
|---|---|---|---|
| **P2-FU-01** (`run_script` allowlist prune) | Q1 2026 cycle runs clean on V2 | **N** | Q1 2026 13F cycle is ~2026-05-15; not yet run. |
| **DM14c Voya residual** | DM14b edge-completion (Voya edge missing) | **N** | No PR in the leg touched DM14b or added a Voya edge. |
| **categorized-funds-csv-relocate** | Next session touching `scripts/backfill_manager_types.py:39` | **N** | No PR in the leg touched `scripts/backfill_manager_types.py`. |
| **Auto-refresh scheduler (cron)** | First time auto-refresh would have prevented an issue | **N** | Apr 27 nport-refresh-catchup was a manual decision, not a missed-cycle incident. |

## Rules carried forward

- **Do NOT run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed; `security_type_inferred` column still exists in schema (not dropped — only the `holdings_v2.security_type` mirror was dropped by 43g). A `--reset` would re-seed from a column the classifier no longer reads.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP gate for `holdings` / `fund_holdings` / `beneficial_ownership` snapshots) authorized **on or after 2026-05-09**. Tables themselves were dropped 2026-04-13; this gate is for the residual snapshot cleanup pass.
- **Approach first, prompt second** — present approach and wait for confirmation before writing code.
- **Git ops:** Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- **Staging workflow mandatory** for all entity changes (`sync_staging.py` → `diff_staging.py` → `promote_staging.py --approved`).
- **`ROADMAP.md` is the single source of truth** for all items.
- **Ticket numbers retired forever** once assigned (codified in `REVIEW_CHECKLIST.md` / `audit_ticket_numbers.py` per PR #149 hygiene-ticket-numbering session).

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 DROP window opens (legacy-table snapshot cleanup gate). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Recommended next actions (priority order)

A. **PR #172 close** — reconcile `dm13-de-discovery` doc with #173 apply outcome and close the PR. Carried over from conv-14.
B. **`other_managers` PK shape decision** — 5,518 NULL `other_cik` rows + 19-row dedupe; finalize the PK shape (likely `(accession_number, sequence_number)`) before stamping a PK enforcement migration. Carried over from PR #165 deferred decision.
C. **INF50 + INF52 live verification** — wait for next N-PORT topup or Q1 2026 DERA bulk; capture the full `RuntimeError` if the contamination assertion fires.
D. **D10 Admin UI** — surface the 280-row `entity_identifiers_staging` backlog before Q1 2026 cycle (~2026-05-15).
E. **perf-P2** — `flow_analysis` + `market_summary` + `holder_momentum` precompute. Activated proactively by PR #183.
F. **DM15e** — still deferred behind DM6 / DM3 parser work. Do not slot until parsers ship.
