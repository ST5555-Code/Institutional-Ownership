# Chat Handover

## conv-18-doc-sync (2026-04-29)

HEAD: **`922ef6a`** on `main` after 9 squash-merges this session (#204–#212), on top of the conv-17 base (#202–#203).

### PRs landed (#204–#212)

10 PRs merged across the dark-UI continuation arc:

- **PR #204 `layout-header-fullwidth`** — full-width header above sidebar + content; two-line "SHAREHOLDER INTELLIGENCE" wordmark. Squash `d460526`.
- **PR #205 `sector-rotation-redesign`** — new `/api/v1/sector_summary` endpoint, KPI cards row, grouped bar chart, ranked heatmap table, auto-select for top movers. Squash `7ef4cde`.
- **PR #206 `sr-layout-polish`** — compact KPI tiles, outlier toggle, table restructure (4 quarter columns + boxed Total Net), movers panel gains dollar signs and footnote. Squash `ec72e5b`.
- **PR #207 `sr-chart-movers-fix`** — broken-axis charts, new `type_breakdown` endpoint, mover-detail drill-down popup, fund-view movers fix. Squash `975c17c`.
- **PR #208 `sr-chart-movers-fix v2`** — heatmap replaces bar chart, two-line wordmark, net flows redesign, KPI tiles for all categories. Squash `5e421d5`.
- **PR #209 `sr-polish-v2`** — net-flows heatmap table replaces bar chart, sector totals row, movers panel beside heatmap, shorter KPI labels. Squash `48bd894`.
- **PR #210 `investor-detail-redesign`** — Entity Graph renamed to Investor Detail; new 3-level hierarchy (institution → filer → fund); new `/api/v1/institution_hierarchy` endpoint; quarter selector + market-wide static view. Squash `f480e3e`.
- **PR #211 `investor-detail-dedup`** — `GROUP BY` dedup on filer-level and fund-level hierarchy queries. Squash `c04bca4`.
- **PR #212 `compact-density`** — tighter padding across all 12 tabs, expand triangle in dedicated first column, gold left border on leftmost edge only, child-row connectors. Squash `922ef6a`.

### New endpoints

- `/api/v1/sector_summary` — backs the redesigned Sector Rotation tab (KPI tiles + ranked heatmap).
- `/api/v1/sector_flow_mover_detail` — backs the mover drill-down popup.
- `/api/v1/institution_hierarchy` — backs the 3-level Investor Detail drill-down (institution → filer → fund).

### Known issue discovered

- **N-PORT quarter bucketing off by one.** Pipeline assigns `Q+1` instead of the calendar quarter for N-PORT periods. Manifests as `2026Q1` containing Oct–Dec 2025 and `2026Q2` containing Jan–Mar 2026 in the new Sector Rotation quarter columns and the Investor Detail hierarchy. Logged in `ROADMAP.md` "Known issues"; pipeline fix needed.

### Process notes

- **Git ops rule change.** Code now pushes the branch, opens the PR, waits for CI green, then merges via `gh pr merge --squash --delete-branch` and pulls `main`. Previously the operator merged manually from Terminal. Captured in `docs/PROCESS_RULES.md`.
- **Session/branch naming rule added.** Always use short descriptive slugs (e.g. `sector-rotation-redesign`, `dark-ui-restyle`, `investor-detail-redesign`, `compact-density`). Claude must propose the short slug before writing any prompt for Code. Captured in `docs/SESSION_NAMING.md`.

### Backlog state

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only.
- **P2:** empty.
- **P3 (2 items):** `D10 Admin UI for entity_identifiers_staging`; `Tier 4 unmatched classifications (427)`.
- **Known issues:** N-PORT quarter bucketing off by one (pipeline).

---

## conv-17-doc-sync (2026-04-29)

HEAD: **`5f7781f`** on `main` after two squash-merges this session.

### PRs landed

- **PR #202 `dark-ui-restyle`** (squash commit `5f7781f`) — full dark/cinematic UI restyle per `docs/plans/DarkStyle.md`. **33 files, 3 commits on the branch.** Touched `web/react-app/src/styles/globals.css` (new token palette: `--bg #0c0c0e`, `--panel #131316`, `--header #000000`, `--gold #c5a254`, semantic `--pos`/`--neg`, plus 3 Google Fonts via `@import`: Hanken Grotesk / Inter / JetBrains Mono), 5 shell components (Header / Sidebar / SidebarSection / SidebarItem / AppShell), 9 common components (typeConfig, QuarterSelector, RollupToggle, FundViewToggle, ActiveOnlyToggle, InvestorTypeFilter, FreshnessBadge, ExportBar, ColumnGroupHeader, TableFooter, plus InvestorSearch + ErrorBoundary as collateral), 12 tab files, and `web/templates/admin.html`. **Branch commit sequence:** `c384b4c` initial restyle (33 files +869/−738) → `14ae269` audit pass (10 files +59/−47, fixing residual white parent rows in Register/Conviction, inactive segmented buttons in CrossOwnership/FlowAnalysis/SectorRotation, DataSourceTab markdown headings rendering invisible black, dropdown row hover unification, input/select backgrounds moved to `var(--bg)`) → `8779ed8` final sweep (2 files +4/−4, fixing 4 missed `var(--white)` backgroundColor leaks in PeerRotationTab + OwnershipTrendTab). **Also resolves prior P3 item "Type-badge `family_office` color"** — `family_office` now in `common/typeConfig.ts` mapped to the gold category palette (translucent fills + colored text). Visual-only — no API, data-logic, or component-contract changes; all collapsibles, tooltips, sorting, filtering, ExcelExport, and Print preserved. Build clean (`cd web/react-app && npm run build` ✓ 1.62s, 0 TS errors). Style guide: [docs/plans/DarkStyle.md](docs/plans/DarkStyle.md). Implementation spec: [docs/plans/dark-ui-restyle-prompt.md](docs/plans/dark-ui-restyle-prompt.md).
- **PR #203 `ci-fix-stale-test`** (squash commit `03914f2`) — replaced three hardcoded `fetch_date` strings in `tests/pipeline/test_load_market.py::test_scope_stale_days_queries_prod` with `dt.date.today()`-relative offsets (`FRESH = today − 1d`, `STALE = today − 30d`, `UNFETCHABLE = today − 120d`) so the test cannot drift stale as calendar time passes. The hardcoded `FRESH = '2026-04-21'` had crossed the 7-day staleness boundary on 2026-04-28 and was failing CI for every open PR (notably PR #202, which is frontend-only and unrelated). Test intent unchanged. 1 file, +12/−3.

### Process notes

- Workflow: opened #202 first (dark UI). CI failed on the smoke check in `test_load_market.py` — root cause was the time-bomb test, not the PR. Cut #203 as a dedicated test fix off `origin/main`, merged it, then `gh pr update-branch 202` to pull main into #202's branch so CI re-ran against post-fix main; both checks went green; squash-merged #202.
- Local main worktree had the three #202 branch commits replayed onto local main as fast-forward (a state divergence from `origin/main`). Reset to `origin/main` before the squash-merge to keep history matching the project's `(#NNN)` squash-per-PR pattern. No work lost — all commits were on the PR branch.
- Doc-sync (this commit, `conv-17-doc-sync`) is direct to main per session brief.

### Backlog state

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only.
- **P2:** empty.
- **P3 (2 items, was 3):** `D10 Admin UI for entity_identifiers_staging`; `Tier 4 unmatched classifications (427)`. The third (`Type-badge family_office color`) closed by PR #202.

---

# Chat Handover — 2026-04-28 (conv-16-doc-sync, 31-PR arc close)

## State

HEAD: `5a77c5c` (PR #200 `calamos-merge-tier4-classify`).
Migrations: 001–023 applied (022 = drop redundant v2 columns, PR #187; 023 = `parent_fund_map`, PR #191). No migration in this PR.

Open PRs:
- **#172** — `dm13-de-discovery: triage CSV for residual ADV_SCHEDULE_A edges` (intentional, paired with #173 apply; close after reconciling).
- **#107** — `ui-audit-walkthrough` (intentional; needs live Serge+Claude session).
- **conv-16-doc-sync (this PR)** — to be opened, not merged.

P0: empty.
P1: `ui-audit-walkthrough` (#107) only.
P2: empty (DERA umbrella initiative closed Tier 1+3+4 in PRs #198/#199; Calamos merge follow-up closed in PR #200).
P3 (3 items): `D10 Admin UI for entity_identifiers_staging`; `Type-badge family_office color`; `Tier 4 unmatched classifications (427)` — new this PR.

## 31-PR arc 2026-04-26/28 — full table (#169–#200)

The arc spans four legs stitched together by **two end-of-leg doc-syncs** (`conv-14-doc-sync` PR #182, `conv-15-doc-sync` PR #188), **one end-of-arc doc-sync** (`dm14c-voya` PR #192), and **this final-session sync** (`conv-16-doc-sync`).

- **Leg 1 — DM13 + INF48/49 + perf-P1** (PRs #169–#181, conv-14 close): 797 ADV_SCHEDULE_A rollup edges suppressed + 2 hard-deleted; 2 NEOS / Segall Bryant entity merges; `sector_flows_rollup` precompute (migration 021) + `cohort_analysis` 60s TTL cache.
- **Leg 2 — N-PORT pipeline / dedup / 43g** (PRs #183–#187, conv-15 close): N-PORT topup +478K rows, INF50/INF52 hardening, INF51 prod-dedup (68 byte-identical rows deleted, 5.59M value-divergent retained), 3 redundant v2 columns dropped (migration 022).
- **Leg 3 — perf-P2 + BL-3 close** (PRs #189–#191): app-side write-path audit (no DML found), INF53 closed as by-design, `parent_fund_map` precompute (migration 023, 5.6× holder_momentum speedup).
- **Leg 4 — end-of-arc P3 sweep** (PRs #192–#196): DM14c Voya residual, CSV relocate + DERA synthetic-series discovery, Rule 9 dry-run uniformity + 43e family-office, G7 `queries.py` split, `make audit` runner + last two `--dry-run` holdouts.
- **Leg 5 — DERA close + Calamos merge** (PRs #197–#200, this leg): DERA Tier 1+3+4 stabilization umbrella close ($2.55T NAV resolved across 714 registrants); Calamos eid 20206/20207 entity-merge follow-up; Tier 4 keyword classification sweep.

| PR | Slug | Notes |
|---|---|---|
| #169 | DM13-B/C apply | 107 non-operating / redundant `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 389–495. Promote `20260426_171207`. |
| #170 | DM15f / DM15g hard-delete | StoneX→StepStone (rel 14408) + Pacer→Mercer (rel 12022) `wholly_owned` edges hard-DELETEd; B/C suppression overrides 425, 488 deleted. |
| #171 | pct-rename-sweep | Doc/naming-only. 283 substitutions across 32 files retiring `pct_of_float` references. |
| #172 | dm13-de-discovery | **OPEN.** Triage CSV for residual ADV_SCHEDULE_A edges (consumed by #173). |
| #173 | DM13-D/E apply | 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 496–1054. Promote `20260427_045843`. **DM13 sweep fully closed.** |
| #174 | DM15d no-op | 0 re-routes. The 3 N-CEN-coverable trusts are all single-adviser; DM rollup already correct. |
| #175 | conv-13 doc sync | Refreshed `NEXT_SESSION_CONTEXT.md` / `ENTITY_ARCHITECTURE.md` / `MAINTENANCE.md` / `CHAT_HANDOVER.md` post-DM13 wave. |
| #176 | INF48 / INF49 | NEOS dup eid=10825 → canonical eid=20105; Segall Bryant dup eid=254 → canonical eid=18157. Override IDs 1055 + 1056. Promote `20260427_064049`. |
| #177 | react-cleanup-inf28 | React: shared `useTickers.ts` module-cached hook (3 fetches → 1) + module-scope `fetchEntitySearch(q)`. INF28: `promote_staging.VALIDATOR_MAP['securities']` → `schema_pk`. No DB writes. |
| #178 | dead-endpoints | 11 of 15 router-defined uncalled `/api/v1/*` routes deleted; 4 kept. 2 query helpers deleted. |
| #179 | perf-p1-discovery | Scoping doc `docs/findings/perf-p1-scoping.md`. |
| #180 | perf-P1 part 1 | New `sector_flows_rollup` precompute (321 rows, migration 021). 310× / 224× speedups on parent / fund paths. |
| #181 | perf-P1 part 2 | `cohort_analysis` 60s TTL cache. >10,000× warm-hit speedup. **Closes perf-P1.** |
| #182 | conv-14-doc-sync | End-of-leg doc sync after #169–#181. |
| #183 | roadmap-priority-moves | 3 Deferred → active: `perf-P2` → P2; `BL-3` + `D10` → P3. |
| #184 | nport-refresh-catchup | N-PORT monthly-topup +478,446 rows / 1,164 NPORT-P accessions; 71 `is_latest` flips. INF50 + INF52 surfaced. |
| #185 | inf50-52-nport-pipeline-fixes | Code-only N-PORT pipeline hardening. INF50 hard-fail cleanup; INF52 pre-promote `_enrich_staging_entities`. 6 new tests; 230/230 pipeline + smoke pass. |
| #186 | INF51 prod-dedup | 5.53M apparent dupes → only **68 byte-identical rows** deleted; 5.59M value-divergent kept. `fund_holdings_v2` 14,568,843 → 14,568,775. **INF53** logged. |
| #187 | 43g-drop-redundant-columns | Migration 022. Dropped `holdings_v2.crd_number`, `holdings_v2.security_type`, `fund_holdings_v2.best_index` via rebuild path. 38s on 25 GB prod DB. |
| #188 | conv-15-doc-sync | End-of-leg doc sync after #183–#187. |
| #189 | bl3-inf53 | (A) BL-3 app-side audit of `scripts/api_*.py` + `scripts/queries.py` — zero DML found. (B) INF53 root cause — N-PORT multi-row-per-key is by design (Long+Short pairs, multiple lots, placeholder CUSIPs); MIG015 not the bug. **Closes BL-3 + INF53 as recommendation-only.** |
| #190 | perf-p2-discovery | Scoping doc `docs/findings/perf-p2-scoping.md` for `flow_analysis` + `market_summary` + `holder_momentum`. First two deferred (already fast); `holder_momentum` parent 800ms targeted. |
| #191 | perf-P2 holder_momentum | New `parent_fund_map` precompute (109,723 rows, migration 023). One batched JOIN replaces 25 sequential `_get_fund_children` ILIKE calls. AAPL parent EC 800ms → 142ms (5.6×). **Closes perf-P2.** |
| #192 | dm14c-voya | (0) End-of-arc doc sync covering #169–#191. (1) 7 Deferred → active backlog. (2) **DM14c Voya residual.** 49 actively-managed Voya-Voya intra-firm series ($21.74B) DM-retargeted from holding co eid=2489 → operating sub-adviser eid=17915. Override IDs 1057–1105. Promote `20260428_081209`. EC untouched. |
| #193 | p3-quick-wins | (A) categorized-funds-csv-relocate. (B) DERA synthetic-series FLAG / discovery — **2,172,757 rows / 1,236 distinct synthetic series / $2.55T NAV / 1.58% of `is_latest=TRUE` market value**. Promoted to P2 per Serge sign-off. |
| #194 | rule9-43e | (A) `--dry-run` flag added to 8 high-risk write scripts. Compliance table in `docs/PROCESS_RULES.md §9a`. (B) **43e family-office.** 41 wealth_management → family_office reclassified + 16 new in CSV. **Prod backfill: 51 managers + 36,950 holdings_v2 rows** (was 0). |
| #195 | csv-cleanup-g7-split | (A) 5 carry-over `family_office` dupes removed from CSV (5,807→5,802). (B) **G7 `queries.py` monolith split.** 5,455 L → 8 domain modules + `__init__.py` re-exporting all 91 symbols. |
| #196 | p3-audit-dryrun | (A) `scripts/run_audits.py` runner + `make audit` / `make audit-quick` + `MAINTENANCE.md` "Running Audits" section. (B) `--dry-run` added to last two holdouts (`build_entities.py`, `resolve_adv_ownership.py`). **All non-UI P3 items cleared.** |
| #197 | dera-synthetic-series-discovery | Read-only resolution scoping. Tier classification (Tier 1: 1 reg / 0 NAV; Tier 2: 0; Tier 3: 55 / $1.98T; Tier 4: 658 / $570.8B). Findings doc `docs/findings/dera-synthetic-resolution-scoping.md`. No DB writes. |
| #198 | dera-synthetic-phase1-2 | New `scripts/oneoff/dera_synthetic_stabilize.py`. Phase 1 (Tier 1, 1 reg / 72 rows). Phase 2 (Tier 3, 55 regs / 1.29M rows / $1.98T NAV) `SYN_{cik_padded}` stable-key migration. 8/8 verifications PASS. |
| #199 | dera-synthetic-tier4 | Phase 3 (Tier 4, 658 regs / 884K rows / $566.7B NAV). **657 institution entities bootstrapped** (`classification='unknown'`, `created_source='bootstrap_tier4'`); 1 attach (Calamos eid 20206). 10/10 hard verifications PASS. **Closes umbrella DERA initiative across all 4 tiers.** |
| **#200** | **calamos-merge-tier4-classify (this PR)** | **(A) Calamos eid 20207 → 20206 merge** — closes the Tier-4 entity-merge follow-up. Identifier transfer no-op (dup had 0 open identifiers post-Tier-4); parallel sponsor edge `rel_id=16134` closed as redundant with survivor's twin `rel_id=16133`; legal_name alias added on survivor; `merged_into` rollups inserted on dup for EC + DM; override `id=1106` written. **(B) Tier 4 keyword classification sweep.** Spec: PASSIVE = SPDR / iShares / Vanguard / ETF / Index; ACTIVE = CEF / Closed-End / Interval / Municipal / BDC / Business Development / Income Fund. **230 of 657 reclassified** (1 passive `Index`; 229 active across `Income Fund=175`, `Municipal=76`, `Interval=4`, `Closed-End=1`); **427 unmatched** (all visibly CEFs/interval/private credit but kept `unknown` per conservative spec). Snapshot deltas: relationships_active -1; classifications_active -1; tier4_unknown_active 657→427; tier4_sweep_active 0→230; overrides_total 1,103→1,104. **No recompute pipelines** (eid 20207 had 0 holdings; classifications not joined into rollups). **427 unmatched Tier 4 classifications logged as new P3.** |

## End-of-arc P3 sweep — closure detail

The end-of-arc legs cleared every non-UI P3 item activated by #192's deferred-item audit. Mapping:

| Activated in #192 | Closed in | How |
|---|---|---|
| DM14c Voya residual (P2) | #192 | DM re-route shipped same PR; 49 series, $21.74B, override IDs 1057–1105. |
| categorized-funds-csv-relocate (P3) | #193 | `git mv` to `data/reference/`; one read site updated. |
| DERA NULL-series synthetics (P3 → P2) | #193 → #197/#198/#199 | Discovery promoted to P2 sprint slot; closed across the three DERA PRs (umbrella initiative). |
| 43e family-office taxonomy (P3) | #194 | 41 rows reclassified + 16 appended in CSV; prod backfill 51 managers + 36,950 holdings_v2. |
| Rule 9 dry-run uniformity (P3) | #194 + #196 | 8 scripts in #194; 2 last holdouts (`build_entities.py`, `resolve_adv_ownership.py`) in #196. |
| G7 `queries.py` monolith split (P3) | #195 | 5,455 L → 8 domain modules + `__init__.py` re-export. |
| maintenance-audit-design (P3) | #196 | `scripts/run_audits.py` + `make audit` + `make audit-quick`. |
| Calamos eid 20206/20207 entity-merge (P3, surfaced #199) | #200 | Identifier no-op + redundant edge close + legal_name alias + `merged_into` rollups + override 1106. |

## DM13 grand total (closed in conv-14)

**797 relationships suppressed + 2 hard-deleted across 4 PRs:**

| PR | Category | Count | Override IDs |
|---|---|---|---|
| #168 | A — self-referential edges | 131 | 258–388 |
| #169 | B+C — non-operating / redundant | 107 (105 in DB after #170 deletes) | 389–495 |
| #170 | DM15f/g — hard-DELETE (subset of B/C false-positives) | 2 | 425, 488 deleted |
| #173 | D+E — dormant / residual | 559 | 496–1054 |
| **Total** | | **797 suppressed + 2 deleted** | |

## Override-ID timeline (state at HEAD `5a77c5c`)

| Wave | PRs | Override IDs |
|---|---|---|
| DM13-A self-referential | #168 | 258–388 |
| DM13-B/C non-operating | #169 | 389–495 (425, 488 deleted in #170) |
| DM13-D/E dormant | #173 | 496–1054 |
| INF48 NEOS / INF49 Segall Bryant | #176 | 1055, 1056 |
| DM14c Voya residual | #192 | 1057–1105 |
| Calamos eid 20207 merge | #200 | 1106 |
| **MAX(override_id)** | | **1106** |
| **Active count** | | **1,104** (gaps at 425, 488 from #170) |

## Prod entity-layer state (read-only `data/13f.duckdb`, post #200)

| Metric | Value | Δ vs prior handover (dm14c-voya close) |
|---|---|---|
| `entities` | **27,259** | +657 (Tier 4 institution bootstraps in #199; eid 20207 SCD-closed not deleted in #200) |
| `entity_overrides_persistent` rows | **1,104** | +1 (Calamos override id=1106 in #200) |
| `MAX(override_id)` | **1,106** | +1 |
| `entity_rollup_history` open `economic_control_v1` | **27,259** | +657 (Tier 4 self-rooted EC; +2 merged_into / -2 dup closed in #200, net 0) |
| `entity_rollup_history` open `decision_maker_v1` | **27,259** | +657 (Tier 4 self-rooted DM; +2 merged_into / -2 dup closed in #200, net 0) |
| `entity_relationships` total / active | **18,363 / 16,315** | total unchanged; active -1 (parallel sponsor edge `rel_id=16134` closed in #200) |
| `entity_aliases` (total, all states) | **27,601** | +657 Tier-4 brand aliases in #199; +1 legal_name alias on eid 20206 in #200; -1 dup alias closed on eid 20207 in #200 |
| `entity_identifiers` | **36,174** | +658 (#199: 657 Tier-4 CIK identifiers + 1 Calamos attach) |
| `entity_classification_history` open | **27,152** | +657 Tier-4 unknown opens in #199; -1 dup closed on eid 20207 in #200 |
| `parent_fund_map` (migration 023) | **111,941** | +2,220 organic vs prior 109,721 snapshot |
| `sector_flows_rollup` (migration 021) | **321** | unchanged |
| `holdings_v2` rows | **12,270,984** | unchanged |
| `fund_holdings_v2` rows / `is_latest` | **14,568,775 / 14,568,704** | unchanged total (rekey-only in DERA Tier 4) |
| `fund_holdings_v2` distinct `series_id` (`is_latest`) | **13,919** | -470 (1,128 Tier-4 synth series collapsed to 658 SYN_*) |
| Distinct SYN_* keys (`is_latest`) | **713** | +658 (= 55 Phase 2 + 658 Phase 3) |
| `fund_universe` | **13,623** | +609 (= -49 Tier-4 fund_universe rows / +658 canonical SYN_* rows) |
| `managers.strategy_type='family_office'` | **51** | unchanged (PR #194 43e backfill) |
| `holdings_v2.manager_type='family_office'` | **36,950** | unchanged (PR #194 43e backfill) |

NAV `is_latest` $161,598,742,805,818.09. `validate_entities --prod` baseline preserved post-Tier-4 + Calamos: **7 PASS / 1 FAIL (`wellington_sub_advisory`, long-standing) / 8 MANUAL**.

## Active classification distribution (open rows on `entity_classification_history`)

| Value | Count |
|---|---:|
| active | 11,470 |
| passive | 5,846 |
| unknown | 3,852 |
| wealth_management | 1,678 |
| hedge_fund | 1,484 |
| strategic | 1,163 |
| mixed | 1,032 |
| pension_insurance | 152 |
| private_equity | 137 |
| venture_capital | 128 |
| quantitative | 73 |
| endowment_foundation | 65 |
| activist | 34 |
| market_maker | 23 |
| SWF | 15 |
| **Total** | **27,152** |

The 3,852 `unknown` total includes the 427 Tier-4 unmatched logged as new P3 in PR #200.

## DERA synthetic-series — closed across Tiers 1+3+4

`scripts/fetch_dera_nport.py:460` mints synthetic series_ids of form `{cik_no_leading_zeros}_{accession_number}` when DERA `FUND_REPORTED_INFO.SERIES_ID` is missing in the source XML. Closure path: `scripts/oneoff/dera_synthetic_stabilize.py` (`--phase 1|2|3|all`).

| Tier | Approach | Registrants | Rows | NAV |
|---|---|---:|---:|---:|
| Tier 1 (PR #198) | Real-series swap (synthetic → existing `Sxxxxxxxxx`) | 1 | 72 | <$0.1B |
| Tier 2 | n/a (N-CEN does not cover any) | 0 | 0 | 0 |
| Tier 3 (PR #198) | `SYN_{cik_padded}` stable-key migration; entity already mapped | 55 | 1,285,589 | $1,977.6B |
| Tier 4 (PR #199) | Bootstrap institution entity + same SYN migration | 658 | 883,912 | $566.7B |
| **Cumulative** | | **714** | **2,169,573** | **$2,544.3B** |

The 8-CIK literal `'UNKNOWN'` legacy fallback (3,184 rows / pre-`fetch_dera_nport.py` loader) is intentionally excluded — pre-DERA-Session-2 data with no per-row registrant CIK.

**Validator FLAG `series_id_synthetic_fallback` (`scripts/pipeline/load_nport.py:437`) can be retired** — no remaining Tier 1/3/4 candidates as of #200. Future N-PORT filings without SERIES_ID will mint net-new `{raw_cik}_{accession}` keys; re-running `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period absorbs them.

Findings: `docs/findings/dera-synthetic-resolution-scoping.md` (PR #197), `docs/findings/2026-04-28-dera-synthetic-series-discovery.md` (PR #193).

## Tier 4 classification sweep (PR #200) — by-the-numbers

Cohort: 657 entities with `created_source='bootstrap_tier4'` and an open `classification='unknown'` row.

| Outcome | Count | Notes |
|---|---:|---|
| Active (Income Fund) | 175 | |
| Active (Municipal) | 76 | |
| Active (Interval) | 4 | |
| Active (Closed-End) | 1 | |
| Passive (Index) | 1 | `Accordant ODCE Index Fund` eid 27027 — debatable (real-estate fund-of-funds) but follows spec keyword literally |
| Unmatched (still `unknown`) | 427 | All visibly CEFs/interval/private credit (sample: John Hancock Income Securities Trust, Western Asset High Income Opportunity Fund, BlackRock MuniYield NY, Eagle Point Defensive Income Trust, NB Crossroads Private Markets); kept conservative |
| **Total** | **657** | |

NAV exposure of the 427 unmatched: bounded at ~$370B (427 / 657 × $566.7B Tier-4 cohort).

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
- **023_parent_fund_map** (PR #191) — new `parent_fund_map` precompute table, PK `(rollup_entity_id, rollup_type, series_id, quarter)`, current row count 111,941.

PRs #192–#200 add **no schema migrations** — all data, file-system, or code-only.

## Rules carried forward

- **Do NOT run `build_classifications.py --reset`.** PR #162 eqt-classify-codefix changed what the classifier reads; `--reset` would re-seed from a column the classifier no longer reads.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP gate) authorized **on or after 2026-05-09**.
- **Approach first, prompt second** — present approach and wait for confirmation before writing code.
- **Git ops:** Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- **Staging workflow mandatory** for all entity changes (`sync_staging.py` → `diff_staging.py` → `promote_staging.py --approved`); PR #200 was a documented exception (orphan dedup of an already-isolated entity, prod-direct).
- **`ROADMAP.md` is the single source of truth** for all forward items.
- **Ticket numbers retired forever** once assigned (codified in `REVIEW_CHECKLIST.md` / `audit_ticket_numbers.py`).
- **`make audit` is the front door for read-only audits.** `make audit-quick` skips the two slow checks.
- **`--dry-run` is uniform** across all non-pipeline write scripts (compliance table in `docs/PROCESS_RULES.md §9a`); SourcePipeline subclasses inherit `--dry-run` from `scripts/pipeline/base.py`.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 DROP window opens (legacy-table snapshot cleanup gate). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Recommended next actions (priority order)

A. **Type-badge `family_office` color (P3, UI)** — `web/react-app/src/common/typeConfig.ts` needs a `family_office` case for the 36,950 reclassified `holdings_v2` rows.
B. **D10 Admin UI for `entity_identifiers_staging` (P3, UI)** — surface the 280-row staging backlog before Q1 2026 cycle.
C. **Tier 4 unmatched classifications (P3, surfaced #200)** — 427 `bootstrap_tier4` entities still `unknown`; expand keyword set or do per-entity manual sign-off.
D. **PR #172 close** — reconcile `dm13-de-discovery` doc with #173 apply outcome.
E. **`load_nport.py:437` `series_id_synthetic_fallback` validator FLAG retire** — no remaining Tier 1/3/4 candidates after #200.
F. **Passive Voya-Voya cleanup (DM14c follow-up, optional)** — 32 passive series at eid=2489 that should mirror EC. Not blocking.
G. **`other_managers` PK shape decision** — 5,518 NULL `other_cik` rows + 19-row dedupe.
H. **INF50 + INF52 live verification** — wait for next N-PORT topup or Q1 2026 DERA bulk; capture full `RuntimeError` if contamination assertion fires.
I. **DM15e** — still deferred behind DM6 / DM3.
