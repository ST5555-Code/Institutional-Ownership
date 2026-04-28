# Chat Handover — 2026-04-28 (dm14c-voya close)

## State

HEAD (pre-session): `771e79f` (perf-P2 holder_momentum parent rewrite, PR #191)
Migrations: 001–023 applied (023 = `parent_fund_map`, perf-P2)
Open PRs:
- **#172** — `dm13-de-discovery: triage CSV for residual ADV_SCHEDULE_A edges` (intentional, paired with #173 apply; close after reconciling)
- **#107** — `ui-audit-walkthrough` (intentional; needs live Serge+Claude session, not a Code session)
- **(this PR)** — `dm14c-voya: doc sync + 7 ROADMAP moves + DM14c Voya residual (49 series, $21.74B)`
P0: empty.
P1: `ui-audit-walkthrough` only (live walkthrough).
P2: _empty after this session_ (DM14c Voya residual ships to COMPLETED on merge).
P3: `D10 Admin UI for entity_identifiers_staging` (PR #183), `INF53 BACKFILL_MIG015 multi-row investigation` (PR #186 follow-up, recommendation-only per PR #189), and 6 freshly activated items from this session's Task 1 (categorized-funds-csv-relocate, DERA NULL synthetics, 43e family-office taxonomy, PROCESS_RULES Rule 9 dry-run uniformity, G7 queries.py monolith split, maintenance-audit-design).
Worktrees: this branch (`dm14c-voya` / worktree `beautiful-shaw-b808a4`) only.

## Session arc 2026-04-26/28 — 22 PRs (#169–#191) + dm14c-voya

The arc spans three consecutive sessions stitched together by `conv-14-doc-sync` (PR #182) and `conv-15-doc-sync` (PR #188). conv-14 closed the DM13 sweep + perf-P1 wave (#169–#181, 12 merged + 1 still-open). conv-15 closed the N-PORT pipeline / dedup / 43g leg (#183–#187). The post-conv-15 trio (#189 BL-3+INF53, #190 perf-P2 scoping, #191 perf-P2 holder_momentum) closed perf-P2 and BL-3. **This session** layers on top: end-of-leg doc sync, 7 ROADMAP priority moves, and DM14c Voya residual.

### Full 22-PR table (pre-session) + this session

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
| #177 | react-cleanup-inf28 | React-1: shared `useTickers.ts` module-cached hook (3 fetches → 1). React-2: extracted `fetchEntitySearch(q)` helper at module scope. INF28: `promote_staging.VALIDATOR_MAP['securities']` → `schema_pk`. No DB writes. |
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
| #189 | bl3-inf53 | **(A) BL-3 app-side audit** of `scripts/api_*.py` + `scripts/queries.py` — zero DML found, request-serving code is read-only by construction. **(B) INF53 root cause** — N-PORT multi-row-per-key is by design (Long+Short pairs, multiple lots, placeholder CUSIPs); MIG015 is not the bug. Recommendation-only, no schema change. Findings `docs/findings/inf53-backfill-mig015-multirow.md`. **Closes BL-3 + INF53 as recommendation-only.** |
| #190 | perf-p2-discovery | Scoping doc `docs/findings/perf-p2-scoping.md` for `flow_analysis` + `market_summary` + `holder_momentum`. `flow_analysis` (<300ms) and `market_summary` (<170ms) deferred — already fast. `holder_momentum` parent 800ms targeted for rewrite. |
| #191 | perf-P2 holder_momentum | New `parent_fund_map` precompute (109,723 rows, migration 023). `queries.holder_momentum` parent path issues ONE batched JOIN against `parent_fund_map` covering all 25 parents at once, replacing 25 sequential `_get_fund_children` ILIKE calls. **Latency 5-run median:** AAPL parent EC 800ms → 142ms (5.6×), EQT parent EC 745ms → 127ms (5.9×). **Closes perf-P2.** |
| **(this PR)** | dm14c-voya | **Three-task session.** (0) End-of-leg doc sync — full rewrites of `NEXT_SESSION_CONTEXT.md` + `CHAT_HANDOVER.md` covering the 22-PR arc + this session; `MAINTENANCE.md` last-updated date refresh + `compute_parent_fund_map.py` added to L4 precompute table; `ENTITY_ARCHITECTURE.md` header updated for the +49 override delta. (1) **7 Deferred → active backlog moves:** DM14c Voya residual → P2; categorized-funds-csv-relocate / DERA NULL synthetics / 43e family-office / PROCESS_RULES Rule 9 / G7 queries.py monolith / maintenance-audit-design → P3. All 7 had self-referential triggers; activated for visibility. (2) **DM14c Voya residual.** 49 actively-managed Voya-Voya intra-firm series ($21.74B) DM-retargeted from holding co eid=2489 (Voya Financial, Inc.) to operating sub-adviser eid=17915 (Voya Investment Management Co. LLC, CRD 106494). Override IDs 1057–1105 (+49). Promote `20260428_081209`. EC untouched. Script `scripts/oneoff/dm14c_voya_apply.py`. |

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

## DM14c (this session)

| Item | Scope | Detail |
|---|---|---|
| DM14c Voya residual — DM re-route | 49 series, $21.74B AUM | adviser_crd=`000111091` (Voya Investments LLC) AND subadviser_crd=`000106494` (Voya IM Co LLC) AND `is_actively_managed=TRUE`. SCD-close on eid=2489 + SCD-open on eid=17915, `rule_applied='manual_override'`. Override IDs 1057–1105. Promote snapshot `20260428_081209`. EC untouched. |

## Prod entity-layer state (read-only `data/13f.duckdb`, post-promote `20260428_081209`)

| Metric | Value | Δ vs conv-15 close |
|---|---|---|
| `entities` | **26,602** | unchanged |
| `entity_overrides_persistent` rows | **1,103** | **+49** (DM14c Voya, IDs 1057–1105) |
| `MAX(override_id)` | **1,105** | **+49** (gaps at 425, 488 from #170 hard-deletes preserved) |
| `entity_rollup_history` open `economic_control_v1` | 26,602 | unchanged |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 (DM1 parity holds) | unchanged (49 SCD-close + 49 SCD-open, net 0) |
| `entity_relationships` total / active | **18,363 / 16,316** | unchanged |
| `entity_aliases` | 26,943 | unchanged |
| `entity_identifiers` | 35,516 | unchanged |
| `ncen_adviser_map` | 11,209 | unchanged |
| `parent_fund_map` (migration 023) | **109,723** | **NEW** (perf-P2, PR #191) |
| `sector_flows_rollup` (migration 021) | 321 | unchanged |
| `holdings_v2` rows / cols | 12,270,984 / 36 | unchanged |
| `fund_holdings_v2` rows / cols | 14,568,775 / 29 | unchanged |

Validate baseline preserved through promote: **7 PASS / 1 FAIL (`wellington_sub_advisory`) / 8 MANUAL** (long-standing non-structural baseline; no auto-rollback fired).

## P0 / P1 / P2 / P3 status

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (live walkthrough — not a Code session).
- **P2:** _empty after this PR merges_ (DM14c Voya residual moves to COMPLETED).
- **P3:** `D10 Admin UI for entity_identifiers_staging` (PR #183), `INF53` (PR #186 → recommendation-only per PR #189), plus 6 freshly activated items from this session's Task 1 (categorized-funds-csv-relocate, DERA 1,187 NULL-series synthetics, 43e family-office taxonomy, PROCESS_RULES Rule 9 dry-run uniformity, G7 queries.py monolith split, maintenance-audit-design).

## INF50 + INF52 — pending live verification

Both fixes are **code-only and have not been exercised against prod yet.** Live test triggers, in order:

1. **Next monthly N-PORT topup that touches amendments** — exercises both `_purge_stale_raw_staging` (INF50) and `_enrich_staging_entities` (INF52).
2. **Q1 2026 N-PORT DERA bulk, ~late May 2026** — full integration test.

If the post-cleanup `CatalogException` assertion ever fires, capture the full `RuntimeError("...staging is contaminated...")` — that is the actual root cause of the prior silent failure, finally visible.

## INF53 — closed as by-design (PR #189, recommendation-only)

55,924 groups (5,587,231 rows) with same `(series_id, report_month, accession_number, cusip)` key but different shares/value/pct. Of those: 54,437 originate from `BACKFILL_MIG015_*` accessions (5,516,217 rows); 1,551 from real N-PORT filings (71,146 rows, dominated by placeholder CUSIPs). PR #189 read `scripts/migrations/015_amendment_semantics.py:181-202` and sampled 9 groups across BACKFILL + NPORT_NORMAL + fake-CUSIP placeholder. **Conclusion:** by design — N-PORT lets a fund report multiple `<invstOrSec>` line items per security (Long+Short hedged pairs, multiple lots / sub-portfolios, placeholder-CUSIP buckets aggregating distinct holdings). The actual PK is `row_id BIGINT` (migration `020_pk_enforcement.py`); `(series_id, report_month, accession_number, cusip)` was never a natural key. **No fix.** Findings doc `docs/findings/inf53-backfill-mig015-multirow.md`.

## DM14c Voya residual — verification

Post-promote spot checks against prod (read-only `data/13f.duckdb`):

| Check | Expected | Actual |
|---|---|---|
| Active Voya-Voya series at eid=17915 (DM, manual_override) | 49 | **49** ✓ |
| Active Voya-Voya residual at eid=2489 (DM) | 0 | **0** ✓ |
| EC for the 49 series | all eid=4071 (`fund_sponsor`) | **49 at eid=4071** ✓ (untouched) |
| Override count | 1054 → 1103 (+49) | **1103** ✓ |
| MAX(override_id) | 1056 → 1105 | **1105** ✓ |
| New override IDs | 1057–1105 | **1057–1105** ✓ |
| `entity_relationships` active | 16,316 (unchanged) | **16,316** ✓ |
| validate_entities | 7 PASS / 1 FAIL (wellington baseline) / 8 MANUAL | **matched** ✓ |

## N-PORT data status

| Report month | Rows | Notes |
|---|---|---|
| 2026-03 | 3,379 | Partial. 60-day SEC public-release lag — Q1 2026 DERA bulk lands ~late May 2026. |
| 2026-02 | 476,173 | Mostly complete. Filings closing toward Apr 30 deadline. |
| 2026-01 | 1,321,367 | Full. |
| 2025-12 | 2,514,497 | Full. |
| 2025-11 | 2,001,775 | Full. |

## Schema migrations applied (state at this PR)

- **022_drop_redundant_v2_columns** (PR #187, 2026-04-27) — 3 write-only columns dropped from v2 holdings tables via per-table rebuild.
- **023_parent_fund_map** (PR #191, 2026-04-28) — new `parent_fund_map` precompute table, PK `(rollup_entity_id, rollup_type, series_id, quarter)`, 109,723 rows, populated by `scripts/pipeline/compute_parent_fund_map.py`.

This PR adds **no schema migrations** (DM14c is data-only).

## Deferred-item audit (this session)

| Item | Trigger as written | Rationale to activate |
|---|---|---|
| DM14c Voya residual | "DM14b edge-completion (Voya edge missing)" | Self-referential — DM14b shipped Apr 17 and entity-seed creation IS the work, not a trigger. |
| categorized-funds-csv-relocate | "Next session touching `scripts/backfill_manager_types.py:39`" | Self-referential. Trivial file move. |
| DERA 1,187 NULL-series synthetics | "Next N-PORT data quality sweep" | Self-referential. Real cleanup work; no upstream gate. |
| 43e family-office taxonomy | "Next classification taxonomy work" | Self-referential. Bundled with type-badge `family_office` color (still deferred). |
| PROCESS_RULES Rule 9 dry-run uniformity | "Next session touching a non-finra pipeline script's CLI" | Self-referential. CLI standardization sweep. |
| G7 `scripts/queries.py` monolith split | "`queries.py` touches become painful" | Trigger fires every session; surface as actionable. |
| maintenance-audit-design | "Audit surfaces ready to be implemented as runnable programs" | Self-referential. Wire-up work. |

## Rules carried forward

- **Do NOT run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed; `security_type_inferred` column still exists in schema (not dropped — only the `holdings_v2.security_type` mirror was dropped by 43g). A `--reset` would re-seed from a column the classifier no longer reads.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP gate for `holdings` / `fund_holdings` / `beneficial_ownership` snapshots) authorized **on or after 2026-05-09**.
- **Approach first, prompt second** — present approach and wait for confirmation before writing code.
- **Git ops:** Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- **Staging workflow mandatory** for all entity changes (`sync_staging.py` → `diff_staging.py` → `promote_staging.py --approved`).
- **`ROADMAP.md` is the single source of truth** for all items.
- **Ticket numbers retired forever** once assigned (codified in `REVIEW_CHECKLIST.md` / `audit_ticket_numbers.py` per PR #149).

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 DROP window opens (legacy-table snapshot cleanup gate). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes; also first live exercise of `compute_parent_fund_map.py` quarterly rebuild. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Recommended next actions (priority order)

A. **PR #172 close** — reconcile `dm13-de-discovery` doc with #173 apply outcome and close the PR. Carried over from conv-14/15.
B. **Passive Voya-Voya cleanup (DM14c follow-up)** — 32 passive series at eid=2489 that should mirror EC (eid=4071). Separate scoping decision; not blocking.
C. **`other_managers` PK shape decision** — 5,518 NULL `other_cik` rows + 19-row dedupe; finalize the PK shape before stamping a PK enforcement migration. Carried over from PR #165.
D. **INF50 + INF52 live verification** — wait for next N-PORT topup or Q1 2026 DERA bulk; capture the full `RuntimeError` if the contamination assertion fires.
E. **D10 Admin UI** — surface the 280-row `entity_identifiers_staging` backlog before Q1 2026 cycle (~2026-05-15).
F. **DM15e** — still deferred behind DM6 / DM3. Do not slot until parsers ship.
