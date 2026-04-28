# Chat Handover — 2026-04-28 (dera-synthetic-tier4 close, 30-PR arc)

## State

HEAD (post this PR): `dera-synthetic-tier4` (PR-pending; do not merge per session brief).
Migrations: 001–023 applied (022 = drop redundant v2 columns, PR #187; 023 = `parent_fund_map`, PR #191). No migration in this PR.
Open PRs:
- **#172** — `dm13-de-discovery: triage CSV for residual ADV_SCHEDULE_A edges` (intentional, paired with #173 apply; close after reconciling).
- **#107** — `ui-audit-walkthrough` (intentional; needs live Serge+Claude session, not a Code session).

P0: empty.
P1: `ui-audit-walkthrough` only (live walkthrough).
P2: **empty** — `DERA-synthetic-series-resolution Tier 4` closed in this session (713 distinct SYN_* keys, $2.55T NAV resolved across 714 registrants).
P3 (3 items): `D10 Admin UI for entity_identifiers_staging`, `Type-badge family_office color`, `Calamos eid 20206 / 20207 entity-merge` (new this session).

Worktrees: this branch (`claude/optimistic-lamport-78dc7e` / worktree `optimistic-lamport-78dc7e`) only.

## Post-arc additions

The 27-PR arc closed at `p3-audit-dryrun` (PR #196). Three further PRs this same day:

| PR | Slug | Notes |
|---|---|---|
| #197 | dera-synthetic-series-discovery | Read-only resolution scoping for the $2.55T DERA synthetic backlog. Tier classification (Tier 1: 1 reg / 0 NAV; Tier 2: 0; Tier 3: 55 / $1.98T; Tier 4: 658 / $570.8B). Findings doc `docs/findings/dera-synthetic-resolution-scoping.md`. No DB writes. |
| #198 | dera-synthetic-phase1-2 | New `scripts/oneoff/dera_synthetic_stabilize.py`. Phase 1 (Tier 1, 1 reg / 72 rows) Tier-1-style swap. Phase 2 (Tier 3, 55 regs / 1.29M rows / $1.98T NAV) `SYN_{cik_padded}` stable-key migration. 8/8 verifications PASS; recompute pipelines clean; validate baseline 7 PASS / 1 FAIL / 8 MANUAL. |
| **(this PR)** | **dera-synthetic-tier4** | **Phase 3 (Tier 4, 658 regs / 884K rows / $566.7B NAV).** Extended script with `--phase 3`. **657 institution entities bootstrapped** (`classification='unknown'`, `created_source='bootstrap_tier4'`, self-rooted EC + DM rollups). **1 attach (Calamos CIK 0001285650 → eid 20206)**, with stale synth-series identifiers closed on both 20206 + 20207. **Dedup gate: 3 name hits, threshold 50 → PROCEED** — but cross-checking matched eids' `fund_holdings_v2.fund_cik` flagged 2 of 3 as name collisions across different registrants (Nuveen FRI eid 20950 = Nuveen Investment Trust III; Alt Strats eid 16596 = Morgan Stanley Pathway Funds). 10/10 hard verifications PASS; row count + NAV unchanged; entities +657 / entity_identifiers +658 / fund_universe +609 / distinct series_id `is_latest` -470. **Closes the umbrella DERA initiative across all 4 tiers.** Calamos eid 20207 logged as P3 follow-up entity-merge (orphan: 0 holdings / 0 open identifiers, not deleted in this PR). |

## Session arc 2026-04-26/28 — 27 PRs (#169–#196)

The arc spans four consecutive sessions stitched together by **two end-of-leg doc-syncs** (`conv-14-doc-sync` PR #182, `conv-15-doc-sync` PR #188) and **two end-of-arc doc-syncs** (`dm14c-voya` PR #192, this PR's NEXT_SESSION + CHAT_HANDOVER refresh).

- **Leg 1 — DM13 + INF48/49 + perf-P1** (PRs #168→#181, conv-14 close): 797 ADV_SCHEDULE_A rollup edges suppressed + 2 hard-deleted; 2 NEOS / Segall Bryant entity merges; `sector_flows_rollup` precompute (migration 021) + `cohort_analysis` 60s TTL cache.
- **Leg 2 — N-PORT pipeline / dedup / 43g** (PRs #183→#187, conv-15 close): N-PORT topup +478K rows, INF50/INF52 hardening, INF51 prod-dedup (68 byte-identical rows deleted, 5.59M value-divergent retained), 3 redundant v2 columns dropped (migration 022).
- **Leg 3 — perf-P2 + BL-3 close** (PRs #189–#191): app-side write-path audit (no DML found), INF53 closed as by-design, `parent_fund_map` precompute (migration 023, 5.6× holder_momentum speedup).
- **Leg 4 — end-of-arc P3 sweep** (PRs #192–#196, this session): DM14c Voya residual, CSV relocate + DERA synthetic-series discovery, Rule 9 dry-run uniformity + 43e family-office, G7 `queries.py` split, `make audit` runner + last two `--dry-run` holdouts.

### Full 27-PR table

| PR | Slug | Notes |
|---|---|---|
| #169 | DM13-B/C apply | 107 non-operating / redundant `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 389–495. Promote `20260426_171207`. |
| #170 | DM15f / DM15g hard-delete | StoneX→StepStone (rel 14408) + Pacer→Mercer (rel 12022) `wholly_owned` edges hard-DELETEd along with B/C suppression overrides 425, 488. |
| #171 | pct-rename-sweep | Doc/naming-only. 283 substitutions across 32 files retiring `pct_of_float` references. |
| #172 | dm13-de-discovery | **OPEN.** Triage CSV for residual ADV_SCHEDULE_A edges (consumed by #173 apply). |
| #173 | DM13-D/E apply | 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 496–1054. Promote `20260427_045843`. **DM13 sweep fully closed.** |
| #174 | DM15d no-op | 0 re-routes. The 3 N-CEN-coverable trusts are all single-adviser; DM rollup already correct. |
| #175 | conv-13 doc sync | Refreshed `NEXT_SESSION_CONTEXT.md` / `ENTITY_ARCHITECTURE.md` / `MAINTENANCE.md` / `CHAT_HANDOVER.md` post-DM13 wave. |
| #176 | INF48 / INF49 | NEOS dup eid=10825 → canonical eid=20105; Segall Bryant dup eid=254 → canonical eid=18157. Override IDs 1055 + 1056. Promote `20260427_064049`. |
| #177 | react-cleanup-inf28 | React: shared `useTickers.ts` module-cached hook (3 fetches → 1) + module-scope `fetchEntitySearch(q)`. INF28: `promote_staging.VALIDATOR_MAP['securities']` → `schema_pk`. No DB writes. |
| #178 | dead-endpoints | 11 of 15 router-defined uncalled `/api/v1/*` routes deleted; 4 kept. 2 query helpers deleted. |
| #179 | perf-p1-discovery | Scoping doc `docs/findings/perf-p1-scoping.md`. |
| #180 | perf-P1 part 1 | New `sector_flows_rollup` precompute (321 rows, migration 021). 310× / 224× speedups on parent / fund paths. |
| #181 | perf-P1 part 2 | `cohort_analysis` 60s TTL cache. >10,000× warm-hit speedup. **Closes perf-P1.** |
| #182 | conv-14-doc-sync | End-of-leg doc sync. ROADMAP date `2026-04-25 → 2026-04-27`; 43g moved Deferred → P3 by audit. |
| #183 | roadmap-priority-moves | 3 Deferred → active: `perf-P2` → P2; `BL-3` + `D10` → P3. |
| #184 | nport-refresh-catchup | N-PORT monthly-topup +478,446 rows / 1,164 NPORT-P accessions; 71 `is_latest` flips. INF50 + INF52 surfaced. |
| #185 | inf50-52-nport-pipeline-fixes | Code-only N-PORT pipeline hardening. INF50 hard-fail cleanup; INF52 pre-promote `_enrich_staging_entities`. 6 new tests; 230/230 pipeline + smoke pass. **Not yet exercised against prod.** |
| #186 | INF51 prod-dedup | 5.53M apparent dupes → only **68 byte-identical rows** deleted; 5.59M value-divergent kept. `fund_holdings_v2` 14,568,843 → 14,568,775. **INF53** logged. |
| #187 | 43g-drop-redundant-columns | Migration 022. Dropped `holdings_v2.crd_number`, `holdings_v2.security_type`, `fund_holdings_v2.best_index` via rebuild path. 38s on 25 GB prod DB. |
| #188 | conv-15-doc-sync | End-of-leg doc sync after PRs #183–#187. |
| #189 | bl3-inf53 | (A) BL-3 app-side audit of `scripts/api_*.py` + `scripts/queries.py` — zero DML found. (B) INF53 root cause — N-PORT multi-row-per-key is by design (Long+Short pairs, multiple lots, placeholder CUSIPs); MIG015 is not the bug. Recommendation-only. **Closes BL-3 + INF53 as recommendation-only.** |
| #190 | perf-p2-discovery | Scoping doc `docs/findings/perf-p2-scoping.md` for `flow_analysis` + `market_summary` + `holder_momentum`. First two deferred (already fast); `holder_momentum` parent 800ms targeted for rewrite. |
| #191 | perf-P2 holder_momentum | New `parent_fund_map` precompute (109,723 rows, migration 023). One batched JOIN replaces 25 sequential `_get_fund_children` ILIKE calls. **Latency:** AAPL parent EC 800ms → 142ms (5.6×); EQT parent EC 745ms → 127ms (5.9×). **Closes perf-P2.** |
| #192 | dm14c-voya | Three-task end-of-leg session. (0) Doc sync — full rewrites of `NEXT_SESSION_CONTEXT.md` + `CHAT_HANDOVER.md` covering the 22-PR arc; `MAINTENANCE.md` + `ENTITY_ARCHITECTURE.md` headers updated. (1) **7 Deferred → active backlog moves** (DM14c Voya residual → P2; 6 → P3). (2) **DM14c Voya residual.** 49 actively-managed Voya-Voya intra-firm series ($21.74B) DM-retargeted from holding co eid=2489 → operating sub-adviser eid=17915. Override IDs 1057–1105 (+49). Promote `20260428_081209`. EC untouched. |
| #193 | p3-quick-wins | **(A) categorized-funds-csv-relocate.** `git mv` `categorized_institutions_funds_v2.csv` from repo root to `data/reference/`; `scripts/backfill_manager_types.py:39` `CSV_PATH` updated. **(B) DERA synthetic-series FLAG / discovery.** Real number is **2,172,757 rows / 1,236 distinct synthetic series / $2.55T NAV / 1.58% of `is_latest=TRUE` market value** (not the 1,187 figure that was carried in docs). Findings doc `docs/findings/2026-04-28-dera-synthetic-series-discovery.md`. **Promoted to P2** (`DERA-synthetic-series-resolution`) per Serge sign-off. No DB writes; FLAG stays in place. |
| #194 | rule9-43e | **(A) Rule 9 dry-run uniformity.** `--dry-run` flag added to 8 high-risk write scripts: `auto_resolve.py`, `build_benchmark_weights.py`, `enrich_fund_holdings_v2.py`, `fix_fund_classification.py`, `normalize_names.py`, `normalize_securities.py`, `reparse_13d.py`, `reparse_all_nulls.py`. Compliance table written to `docs/PROCESS_RULES.md §9a`. **(B) 43e family-office taxonomy.** CSV: 41 `wealth_management` rows reclassified to `family_office`, 16 new rows appended (5,806 total). **Backfill applied to prod via `scripts/oneoff/43e_family_office_apply.py`** — `managers.strategy_type='family_office'` = **51 rows** (was 0); `holdings_v2.manager_type='family_office'` = **36,950 rows** (was 0). Snapshot rebuilt. `validate_entities` baseline preserved (7 PASS / 1 FAIL / 8 MANUAL). |
| #195 | csv-cleanup-g7-split | **(A) categorized CSV duplicate cleanup.** 5 carry-over `family_office` dupes removed (CSV 5,807 → 5,802; distinct names 57 → 52). **(B) G7 `scripts/queries.py` monolith split.** **5,455-line `scripts/queries.py` split into a `scripts/queries/` package with 8 domain modules** — `common.py` (798 L), `register.py` (1,436 L), `fund.py` (455 L), `flows.py` (695 L), `market.py` (693 L), `cross.py` (452 L), `trend.py` (744 L), `entities.py` (551 L), plus `__init__.py` re-exporting all 91 symbols. Pure refactor — no logic, signature, SQL, or return-value changes. `pytest tests/` 364 passed; `pytest tests/smoke/` 8 passed; pre-commit clean. Original `queries.py` deleted. |
| **#196** | **p3-audit-dryrun (this PR)** | **(A) maintenance-audit-design.** New `scripts/run_audits.py` runner wraps the 5 read-only audit / validation scripts (`check_freshness`, `verify_migration_stamps`, `validate_classifications`, `validate_entities --prod`, `validate_phase4`) as subprocesses; PASS / FAIL / MANUAL status mapping; `--quick` skips the two slow checks; `--verbose` echoes full output. New Makefile targets `audit` + `audit-quick`. New "Running Audits" section in `MAINTENANCE.md`. **(B) dry-run sweep follow-up.** Closes the rule9-43e residual. `--dry-run` flag added to `build_entities.py` (top-level guard, opens DuckDB read-only, prints planned step ops + per-step row-count estimates) and `resolve_adv_ownership.py` (top-level guard, prints numbered phase plan with side-effect targets for all 8 invocation modes). `docs/PROCESS_RULES.md §9a` — both flipped ⚠️ deferred → ✅. **All non-UI P3 items now cleared.** No DB writes, no schema migrations. |

## End-of-arc P3 sweep — detail (PRs #193–#196)

The end-of-arc leg cleared every non-UI P3 item activated in #192's deferred-item audit. Mapping:

| Activated in #192 | Closed in | How |
|---|---|---|
| DM14c Voya residual (P2) | #192 itself | DM re-route shipped same PR; 49 series, $21.74B, override IDs 1057–1105. |
| categorized-funds-csv-relocate (P3) | #193 | `git mv` to `data/reference/`; one read site updated. |
| DERA NULL-series synthetics (P3 → P2) | #193 | Discovery surfaced $2.55T scale → promoted to P2 sprint slot, not closed. |
| 43e family-office taxonomy (P3) | #194 | 41 rows reclassified + 16 appended in CSV; prod backfill 51 managers + 36,950 holdings. |
| Rule 9 dry-run uniformity (P3) | #194 + **#196** | 8 scripts in #194 + 2 last holdouts (`build_entities.py`, `resolve_adv_ownership.py`) in #196. |
| G7 `queries.py` monolith split (P3) | #195 | 5,455 L → 8 domain modules + `__init__.py` re-export. |
| maintenance-audit-design (P3) | **#196** | `scripts/run_audits.py` + `make audit` + `make audit-quick` + `MAINTENANCE.md` "Running Audits" section. |

## DM13 grand total (closed in conv-14, recap)

**797 relationships suppressed + 2 hard-deleted across 4 PRs:**

| PR | Category | Count | Override IDs |
|---|---|---|---|
| #168 | A — self-referential edges | 131 | 258–388 |
| #169 | B+C — non-operating / redundant | 107 (105 in DB after #170 deletes) | 389–495 |
| #170 | DM15f/g — hard-DELETE (subset of B/C false-positives) | 2 | 425, 488 deleted |
| #173 | D+E — dormant / residual | 559 | 496–1054 |
| **Total** | | **797 suppressed + 2 deleted** | |

## Override-ID timeline (state at this PR)

| Wave | PRs | Override IDs |
|---|---|---|
| DM13-A self-referential | #168 | 258–388 |
| DM13-B/C non-operating | #169 | 389–495 (425, 488 deleted in #170) |
| DM13-D/E dormant | #173 | 496–1054 |
| INF48 NEOS / INF49 Segall Bryant | #176 | 1055, 1056 |
| DM14c Voya residual | #192 | 1057–1105 |
| **MAX(override_id)** | | **1105** |
| **Active count** | | **1103** (gaps at 425, 488 from #170) |

## Prod entity-layer state (read-only `data/13f.duckdb`, post-tier4 close)

| Metric | Value | Δ vs prior handover (dm14c-voya close) |
|---|---|---|
| `entities` | **27,259** | **+657** (Tier 4 institution bootstraps; PR-pending) |
| `entity_overrides_persistent` rows | 1,103 | unchanged |
| `MAX(override_id)` | 1,105 | unchanged |
| `entity_rollup_history` open `economic_control_v1` | **27,259** | **+657** (Tier 4 self-rooted EC) |
| `entity_rollup_history` open `decision_maker_v1` | **27,259** | **+657** (Tier 4 self-rooted DM) |
| `entity_relationships` total / active | 18,363 / 16,316 | unchanged |
| `entity_aliases` | **27,600** | **+657** (Tier 4 brand aliases, preferred=TRUE) |
| `entity_identifiers` | **36,174** | **+658** (657 Tier 4 CIK identifiers + 1 Calamos attach) |
| `parent_fund_map` (migration 023) | **109,721** | -2 (re-emit post Tier 4 rekey) |
| `sector_flows_rollup` (migration 021) | 321 | unchanged |
| `holdings_v2` rows / cols | 12,270,984 / 36 | unchanged |
| `fund_holdings_v2` rows / cols | **14,568,775 / 29** | unchanged total (rekey only) |
| `fund_holdings_v2` distinct `series_id` (`is_latest`) | **13,919** | **-470** (1,128 Tier 4 synth series collapsed to 658 SYN_*) |
| `fund_holdings_v2` SYN_* `is_latest` rows | **2,169,501** | **+883,912** (Tier 4 rekey; Phase 2 was 1,285,589) |
| Distinct SYN_* keys | **713** | **+658** (= 55 Phase 2 + 658 Phase 3) |
| `fund_universe` | **13,623** | **+609** (= -49 Tier 4 fund_universe rows / +658 canonical SYN_* rows) |
| `managers.strategy_type='family_office'` | 51 | unchanged (PR #194 43e backfill) |
| `holdings_v2.manager_type='family_office'` | 36,950 | unchanged (PR #194 43e backfill) |

NAV `is_latest` $161,598,742,805,818.09 (pre $161,598,742,805,816.56; delta +9.48e-13% — float aggregation order, not data change). `validate_entities` baseline preserved post-Tier-4: **7 PASS / 1 FAIL (`wellington_sub_advisory`, long-standing) / 8 MANUAL**.

## P0 / P1 / P2 / P3 status (post Tier 4 close)

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live walkthrough — not a Code session).
- **P2:** **empty.** DERA umbrella initiative closed (Tier 1 + Tier 3 + Tier 4); $2.55T NAV / 2.17M synth rows resolved.
- **P3 (3 items):** `D10 Admin UI for entity_identifiers_staging`, `Type-badge family_office color`, `Calamos eid 20206 / 20207 entity-merge` (new this session — orphan eid 20207 with 0 holdings / 0 open identifiers needs merge into 20206 in next entity-curation pass).

## INF50 + INF52 — pending live verification

Both fixes are **code-only and have not been exercised against prod yet.** Live test triggers, in order:

1. **Next monthly N-PORT topup that touches amendments** — exercises both `_purge_stale_raw_staging` (INF50) and `_enrich_staging_entities` (INF52).
2. **Q1 2026 N-PORT DERA bulk, ~late May 2026** — full integration test, also first live exercise of `compute_parent_fund_map.py` quarterly rebuild.

If the post-cleanup `CatalogException` assertion ever fires, capture the full `RuntimeError("...staging is contaminated...")` — that is the actual root cause of the prior silent failure.

## INF53 — closed as by-design (PR #189, recommendation-only, recap)

55,924 groups (5,587,231 rows) with same `(series_id, report_month, accession_number, cusip)` key but different shares/value/pct. **By design** — N-PORT lets a fund report multiple `<invstOrSec>` line items per security (Long+Short hedged pairs, multiple lots / sub-portfolios, placeholder-CUSIP buckets). The actual PK is `row_id BIGINT` (migration `020_pk_enforcement.py`); `(series_id, report_month, accession_number, cusip)` was never a natural key. **No fix.** Findings doc `docs/findings/inf53-backfill-mig015-multirow.md`.

## DERA synthetic-series — closed (Tier 1 + Tier 3 + Tier 4)

`scripts/fetch_dera_nport.py:460` mints synthetic series_ids of form `{cik_no_leading_zeros}_{accession_number}` when DERA `FUND_REPORTED_INFO.SERIES_ID` is missing in the source XML. Closure path: `scripts/oneoff/dera_synthetic_stabilize.py` (`--phase 1|2|3|all`).

| Tier | Approach | Registrants | Rows | NAV |
|---|---|---:|---:|---:|
| Tier 1 (PR #198) | Real-series swap (synthetic → existing `Sxxxxxxxxx`) | 1 | 72 | <$0.1B |
| Tier 2 | n/a (N-CEN does not cover any) | 0 | 0 | 0 |
| Tier 3 (PR #198) | `SYN_{cik_padded}` stable-key migration; entity already mapped | 55 | 1,285,589 | $1,977.6B |
| **Tier 4 (this PR)** | **Bootstrap institution entity + same SYN migration** | **658** | **883,912** | **$566.7B** |
| **Cumulative** | | **714** | **2,169,573** | **$2,544.3B** |

The 8-CIK literal `'UNKNOWN'` legacy fallback (3,184 rows / pre-`fetch_dera_nport.py` loader) is intentionally excluded — those are pre-DERA-Session-2 data with no per-row registrant CIK to bootstrap from. Tracked separately if it ever becomes load-bearing.

**Validator FLAG `series_id_synthetic_fallback` (`scripts/pipeline/load_nport.py:437`) can be retired** in the next `load_nport.py` audit pass — there are no remaining Tier 1/3/4 candidates as of this PR. Future N-PORT filings without SERIES_ID will mint net-new `{raw_cik}_{accession}` keys; re-running `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period absorbs them (the script is idempotent).

Findings: `docs/findings/dera-synthetic-resolution-scoping.md` (scoping, PR #197), `docs/findings/2026-04-28-dera-synthetic-series-discovery.md` (initial FLAG/discovery, PR #193).

## N-PORT data status

| Report month | Rows | Notes |
|---|---|---|
| 2026-03 | 3,379 | Partial. 60-day SEC public-release lag — Q1 2026 DERA bulk lands ~late May 2026. |
| 2026-02 | 476,173 | Mostly complete. Filings closing toward Apr 30 deadline. |
| 2026-01 | 1,321,367 | Full. |
| 2025-12 | 2,514,497 | Full. |
| 2025-11 | 2,001,775 | Full. |

## Schema migrations applied this arc

- **022_drop_redundant_v2_columns** (PR #187) — 3 write-only columns dropped from v2 holdings tables via per-table rebuild.
- **023_parent_fund_map** (PR #191) — new `parent_fund_map` precompute table, PK `(rollup_entity_id, rollup_type, series_id, quarter)`, 109,723 rows.

PRs #192–#196 add **no schema migrations** — all data, file-system, or code-only.

## Rules carried forward

- **Do NOT run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed; `security_type_inferred` column still in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP gate) authorized **on or after 2026-05-09**.
- **Approach first, prompt second** — present approach and wait for confirmation before writing code.
- **Git ops:** Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- **Staging workflow mandatory** for all entity changes (`sync_staging.py` → `diff_staging.py` → `promote_staging.py --approved`).
- **`ROADMAP.md` is the single source of truth** for all items.
- **Ticket numbers retired forever** once assigned (codified in `REVIEW_CHECKLIST.md` / `audit_ticket_numbers.py` per PR #149).
- **`make audit` is the new front door for read-only audits.** `make audit-quick` skips the two slow checks (`validate_entities`, `validate_phase4`).
- **`--dry-run` is now uniform** across all non-pipeline write scripts (compliance table in `docs/PROCESS_RULES.md §9a`); SourcePipeline subclasses inherit `--dry-run` from `scripts/pipeline/base.py`.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 DROP window opens (legacy-table snapshot cleanup gate). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes; first live exercise of `compute_parent_fund_map.py` quarterly rebuild; re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Recommended next actions (priority order)

A. **Type-badge `family_office` color (P3, UI)** — `web/react-app/src/common/typeConfig.ts` needs a `family_office` case. The 36,950 reclassified `holdings_v2` rows currently render with the default chip. Trivial; first session touching the badge config closes it.
B. **D10 Admin UI for `entity_identifiers_staging` (P3, UI)** — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
C. **Calamos eid 20207 entity-merge (P3, this-session follow-up)** — orphan: 0 holdings, 0 open identifiers (closed in Tier 4 close), but `entities` row + classification + rollup history still in place. Merge into 20206 in next entity-curation pass: re-point `entity_relationships` / `entity_overrides_persistent` / aliases on 20207 to 20206; close the entities row.
D. **`load_nport.py:437` `series_id_synthetic_fallback` validator FLAG retire** — no remaining Tier 1/3/4 candidates after this PR. Audit-pass cleanup; flip the FLAG semantics from "block legacy backlog" to "warn on new mints" if any.
E. **PR #172 close** — reconcile `dm13-de-discovery` doc with #173 apply outcome and close the PR. Carried over.
F. **Passive Voya-Voya cleanup (DM14c follow-up, optional)** — 32 passive series at eid=2489 that should mirror EC (eid=4071). Not blocking; ship if a session already touches DM rollups.
G. **`other_managers` PK shape decision** — 5,518 NULL `other_cik` rows + 19-row dedupe; finalize PK shape before stamping a PK enforcement migration.
H. **INF50 + INF52 live verification** — wait for next N-PORT topup or Q1 2026 DERA bulk; capture the full `RuntimeError` if the contamination assertion fires.
I. **Tier 4 classification sweep** — 657 new institution entities are `classification='unknown'`. Next `build_classifications.py` non-`--reset` sweep will assign them based on fund_strategy / SIC / N-PORT signals. No manual action needed unless the run shows >5% staying unknown.
J. **DM15e** — still deferred behind DM6 / DM3. Do not slot until parsers ship.
