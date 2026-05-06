# Chat Handover

## conv-31a-mid-arc-doc-sync (2026-05-06)

### State summary

- HEAD on main: `d11cfba` (PR #307 `cp-5-aum-subtree-callers-recon` merged).
- Active branch: `cp-5-5b-precompute-rebuild` at `a53b8ac` (plan `a3fe7cd` + addendum `a53b8ac`, parked at end of Phase 1).
- CP-5 progress: 5 of 6 main reader-migration PRs shipped (CP-5.1 #299, CP-5.2 #300, CP-5.3 #301, CP-5.4 #303, CP-5.5 #306) plus 1 in-progress (CP-5.5b parked at scaffolding).
- pytest baseline: 447 passing on main; 447 on `cp-5-5b-precompute-rebuild` (no test changes yet on branch).

### CP-5 arc PRs landed since conv-30 (8 PRs)

| PR | Slug | Squash | One-line scope |
| --- | --- | --- | --- |
| #299 | cp-5-1b-helper-and-view (CP-5.1) | — | Migration 027 `inst_to_top_parent` + `unified_holdings` views; `top_parent_holdings_join` helper; FoF subtraction deferred to P2 (`cp-5-fof-subtraction-cusip-linkage`); 6 missing dm_v1 self-rollups null-result (already backfilled). 416→426 tests. |
| #300 | cp-5-2-register-partial-and-unified-quarter-fix (CP-5.2) | — | Migration 028 quarter dimension on `unified_holdings`; 4 of 7 Register sites migrated (queries 1, 2, 12, 16); 3 deferred to P1 sub-PRs (`cp-5-2a` summary_by_parent rebuild blocked Q7; `cp-5-2b` manager_type imputation recon; `cp-5-2c` register-drill-hierarchy). 426→434 tests. |
| #301 | cp-5-3-cross-ownership-readers (CP-5.3) | — | 3 CLEAN sites / 6 sub-sites in `scripts/queries/cross.py` migrated (C1, C4, C6); 2 BLOCKED_DRILL deferred to `cp-5-2c`. 434→438 tests. |
| #302 | cp-5-4-recon | — | Read-only investigation; zero BLOCKED sites; Conviction L-size hypotheses (manager_aum, portfolio_context, Direction/Since/Held) all false premises; recommended Option A bundled. 438 unchanged. |
| #303 | cp-5-4-execute (CP-5.4) | — | 5 CLEAN sub-sites: C1 `market.py:135`, C2 `api_market.py:199`, CV1 `fund.py:110`, CV2 `fund.py:179+:188`, FPM1 `api_fund.py:42`; alias='h' variant uniform; §6.4 binder-ambiguity surfaced as standing rule. 438→444 tests. |
| #304 | cp-5-bundle-c-api-files-extension | `1c98658` | Read-only hygiene; `api_*.py` reader layer enumerated (37 rows added, 27→64); per-feature breakdown: 10 MIGRATED, 2 NO_OP, 3 PENDING_CP5_2C, 9 PENDING_CP5_5, 4 PENDING_CP5_6, 4 PENDING_CP5_BUNDLE_C, 6 N/A, 26 DELEGATING_WRAPPER, 3 DISPATCH_UTILITY. 444 unchanged. |
| #305 | cp-5-5-recon | `1288507` | 9 PENDING_CP5_5 sites scoped; 4-5 CLEAN main bundle; 3 BLOCKED_FLOWS_PRECOMPUTE deferred to CP-5.5b; S9 helper deferred; Activist closes implicitly via `entity_type` column. 444 unchanged. |
| #306 | cp-5-5-execute (CP-5.5 main) | `945b173` | 4 sites migrated (S1 cohort_analysis, S2 holder_momentum, S3 ownership_trend_summary, S4 flow_analysis live); S8 (compute_aum_for_subtree) deferred to ROADMAP P1 `cp-5-aum-subtree-redesign` after Phase 1 schema check caught `unified_holdings` mismatch. 444→447 tests (3 pass + 2 skip on fixture single-quarter). |
| #307 | cp-5-aum-subtree-callers-recon | `d11cfba` | Investigated `compute_aum_for_subtree` callers (2 production callers, both Entity Graph tab); CLOSED as no-op — function correctly serves filer-grain semantics; CP-5.6 independent. 447 unchanged. |

### Process rules locked / amended this arc

- **PR #303 §6.4 — Helper alias variant default for binder safety.** DuckDB binder fails ambiguity inside cross-join shape (`FROM table_a, cte_b`) when noalias variant of `top_parent_canonical_name_sql()` is used. All sites default to alias variant uniformly. Will formalize as standing rule #15 in conv-31-doc-sync proper.
- **PR #306 Phase 1 schema check — Recon recommendations claiming "one-line swap" require schema verification at execute time.** Recon may inspect call sites without verifying the target view/table actually carries equivalent columns. Every execute Phase 1 includes schema verification step against recon's claimed migration target. Will formalize as standing rule #16.
- **CP-5.4/5.5 helper-alias self-consistency.** CV2 and S2 surfaced that helper alias use must stay self-consistent across SELECT and WHERE clauses; outer aliases need disambiguation when the helper takes 'h'. Bake into future migration prompts. Will formalize as standing rule #17.
- **Code merges + cleans up after explicit chat approval** (amended R5, locked 2026-05-06). After chat says "merge <N>", Code runs full sequence (`gh pr merge --squash`, defensive untracked-file cleanup, pull main, optional remote branch delete, report new HEAD). Standard PR creation safety convention unchanged: stop at PR creation, wait for chat review.

### Open ROADMAP items added this arc

- `cp-5-2a-summary-by-parent-rebuild` (P1, blocked on Bundle C Q7 chat decision) — required for `register.py:104-115` (N-PORT cov) + `register.py:560-660` (query14 drill).
- `cp-5-2b-manager-type-imputation-recon` (P1, read-only investigation) — determine whether ECH institution taxonomy already provides what active/passive Register queries need.
- `cp-5-2c-register-drill-hierarchy` (P1, blocked on `cp-5-2a`) — drill hierarchy + `tp_to_filer` + 2 cross.py BLOCKED_DRILL sites.
- `cp-5-fof-subtraction-cusip-linkage` (P2) — build CUSIP→fund-entity bridge so Bundle A §1.4 FoF subtraction can re-enter `unified_holdings`.
- `cp-5-aum-subtree-redesign` — CLOSED as no-op per PR #307. Function correctly serves Entity Graph filer-grain. Cross-tab AUM inconsistency vs top-parent-grain tabs is acceptable design.

### CP-5.5b state (CURRENT, parked)

- Branch: `cp-5-5b-precompute-rebuild`.
- HEAD: `a53b8ac` (addendum) → `a3fe7cd` (plan) → `d11cfba` (main).
- Plan doc: `docs/findings/cp-5-5b-precompute-rebuild-plan.md`.
- **Decision locks:**
  - Option B: generator-driven side-build for 029a `peer_rotation_flows` (CTAS-and-swap pattern via `compute_peer_rotation.py` rebuild).
  - Column-drop CTAS for 029b `investor_flows` (`rollup_entity_id` already 100% populated).
  - Hard cap on G1 row expansion: 3% (abort if exceeded).
  - `shares_history` derivative: in-PR if found and single read-path swap; escalate only if structural.
- **6 reader sites in scope** (was 5; `register.py:633-640` added in Phase 1):
  - `market.py:316` `get_sector_flow_movers`
  - `market.py:475` `get_sector_flow_mover_detail`
  - `trend.py:678` `get_peer_rotation_detail`
  - `flows.py:506` `flow_analysis` investor_flows read
  - `flows.py:515` (subsumed)
  - `register.py:633` (NAME-keyed against `investor_flows`; bundled per Q2 default)
- Pre-flight backup #1 captured: `data/backups/13f_backup_20260506_165238` (3.2GB).
- **Phase 1 audit findings:**
  - `shares_history`: XBRL-derived, not flows-derived; no consumer of dropped columns.
  - `ticker_flow_stats`: doesn't carry `inst_parent_name`.
  - `validate_schema_parity` / `canonical_ddl` audit clean.
  - Activist closure: ECH classification 'activist' populates `entity_type` at rebuild time.
- **Path forward (3-4 sessions):**
  1. Generator updates (`compute_peer_rotation.py` + `compute_flows.py`) → commit.
  2. Migration 029 script (029a generator-driven, 029b column-drop CTAS) → commit, run side-build (hours-scale background).
  3. Atomic swap + 6 reader migrations + tests → commit.
  4. Findings doc + PR.

### Forward sequence

1. Resume CP-5.5b at Phase 2 (generator updates).
2. CP-5.6 — 4 PENDING_CP5_6 sites (institution-hierarchy, `holder_momentum` fund children, `get_entity_descendants`, `search_entity_parents`) — independent of CP-5.5b.
3. conv-31-doc-sync proper — CP-5 closure + standing rules #15/#16/#17 formalized + ROADMAP cleanup (close `cp-5-aum-subtree-redesign` as investigated-no-op, BlackRock brand-vs-filer reminder, Bundle C csv hygiene refresh).

### Backups archived this arc

Three retained EXPORT directories per cadence rule (PR #273 + #292):

- `data/backups/13f_backup_20260506_165238` (CP-5.5b pre-flight #1, 3.2GB).
- `data/backups/13f_backup_20260506_065231`.
- `data/backups/13f_backup_20260505_165855`.

---

## conv-25 — institution-consolidation arc (2026-05-02)

**HEAD on main:** b65363a

**Today's arc:** 12 PRs landed (#247–#258) closing orphan/unknown remediation end-to-end and advancing institution-level critical path through CP-1 + CP-2 + CP-3 + CP-4a + CP-4b-blackrock. Plus 4 in-arc direct-to-main commits (7aa535c, c53337c, 6b31fe7, 4ee2b97) and 2 close-out commits (sync-audit 7f21574, sync-audit-resolution b65363a).

**Critical-path state:** 4 of 5 PRs landed. invisible_brand_aum reduced from $27.80T to $22.72T at relationship layer; CP-5 is what makes the reduction visible at user-facing display. AUM conservation exact across PR #251 ($1.752B), PR #256 ($4.26T), PR #258 ($2.54T). pytest 373/373 throughout. End-of-day sync-audit confirmed 0 broken refs, 0 unpushed commits.

**BLOCKER state:** 2 of 4 fully closed (G1 query4 fix, G4 ingestion_manifest schema). 1 partially closed (G14 cross-tier eid bridge — finishes with CP-4b-author-top20 + CP-5). 1 open pending D4 chat decision (G2 entity-classification pipeline precedence rule).

**Op F + Op H pattern locked** for any future BRAND_TO_FILER merge: FROM-side closure (Op F on `entity_rollup_history` `WHERE entity_id=brand`) plus AT-side closure (Op H `WHERE rollup_entity_id=brand`). Captured in `docs/decisions/inst_eid_bridge_decisions.md`.

### Three forward threads available — user will choose

1. **Critical path next step:** `CP-4b-discovery`. Read-only investigation enumerating top-20 AUTHOR_NEW_BRIDGE candidates by AUM. Per-brand filer pairing via `adv_managers` ADV cross-ref + parent-corp lookup. Manifest deliverable with HIGH / MEDIUM / LOW confidence per pair. Must derive from current state, NOT `eid_inventory.csv` snapshot from PR #254 — numbers drifted (1,225 → 1,337 invisible brands at CP-4b execution time). Output: per-pair pairings for chat review, then `CP-4b-author-top20` execution PR follows. Pattern matches PR #249 (`cef-scoping`) → PR #251 (`cef-asa-flip-and-relabel`) precedent.
2. **Major BLOCKER decision:** D4 from `institution_scoping.md` §9 G2. Precedence rule for institutions without an `entity_classification_history` row. ECH coverage 99.9% (10 of 9,121 uncovered). Design-blocked without chat decision: out-of-band classification pipeline vs in-pipeline backfill on first-write. Closes G2 — last open BLOCKER for Admin Refresh System launch.
3. **Architectural P2 surfaced today:** `register-active-universe-consistency`. Register tab uses 4 different definitions of "active" across read sites (`register.py:1018` excludes activists; `register.py:472`, `1354`, `market.py:373/498` include them). Same tab, four predicates. Pre-requisite for activist-as-flag refactor and gates internal consistency in CP-5 read sweep.

### Smaller deferred items (not urgent)

- `pimco-13f-ingestion-gap` (P2) — PIMCO's $1.72T 13F invisibility persists post-CP-4a. Separate workstream from CP-4b/CP-5. CIK `0001163368` absent from `holdings_v2.cik` entirely.
- `inst-eid-bridge-orphan-triage` (P3) — 723 BRAND_ORPHAN brands / $943B long tail. Defer unless triggering display gap surfaces post-CP-5.
- `source-type-value-canonicalization` (P3) — `'NPORT'` vs `'nport_holdings'` inconsistency in `ingestion_manifest`. Affects `admin_bp.py:1346`.
- `drop-multi-strategy-bucket` (P3) — 2 CIKs / $11.7B (Adams + Diversified Mgmt Inc), neither is multi-strategy. Reclassify Adams to `closed_end` pending `fund-structure-column` workstream.
- `classification-join-utility-resolution` (P3) — utility at `scripts/queries_helpers.py:171` with zero callers. Decision rides on CP-5: adopt or delete.
- `deprecated-fund-rollup-targets-cleanup` (P3) — 19 deprecated entities, $68.7B exposed. Bundled into CP-4 per `institution_scoping.md` §10.
- `fund-structure-column` (P2) — orthogonal column on `fund_universe` (`open_end` / `closed_end` / `etf` / `bdc` / `interval`). Surfaced by PR #249 `cef-scoping`.
- `repo-branch-hygiene` (P3) — 15 stale `claude/*` local + ~120 remote branches. Defer unless impeding workflow.
- `v2-loader-is-latest-watchpoint` (P3) — fires after Q1 2026 cycle (~May 15). Run `audit_unknown_inventory.py`.
- `retired-loader-residue-watchpoint` (P3) — same window, same audit, different signal.
- Migration 008/015 join-key — surfaced PR #255 §A.5 as candidate P3, awaits chat decision on whether to fold into existing tracker or stand alone.

### Process rules in force

- Code is the executor; chat does planning + decisions + prompt generation.
- Self-contained prompts — single paste per Code session.
- Every prompt starts with `CODE PROMPT — <branch-slug>` on first line; chat marks `CODE SESSION OPEN — <branch-slug>` and `CODE SESSION CLOSED — <branch-slug>` boundaries.
- Re-validation discipline: every write-path prompt includes Phase 1 re-validation confirming current state vs preconditions. ABORT on >5% drift.
- Discovery-phase hard rule: Claude does not extrapolate or assume facts about repo state, schema, data shape, or prior PR contents. Every state claim comes from Code — investigation, dry-run, or direct read.
- Recommendation discipline: internal expert challenge (performance, data integrity, architecture, ops/resilience) before delivering any technical recommendation. Final only; not the debate.
- Code prompt hygiene: enumerate columns by category for write ops (no "copy all other columns"); specify worktree-relative absolute paths for Write tool calls.
- Worktree merge hygiene: when worktree is alive while parent holds main, `gh pr merge --squash --delete-branch` fails on local cleanup. Code does manual `git pull` + remote branch delete up front.
- Backup before destructive PRs: `backup_db.py` is run manually by user, never auto-run. Use `ulimit -n 65536` first to avoid macOS file descriptor limit.
- App must be off (`lsof -ti:8001` empty) for write PRs and most read-only audits that touch prod DB.
- Direct-to-main commit pattern for doc-only / decision-locking / sync-audit work — no PR.
- `staging_workflow_live.md` does not exist as a file. Entity writes follow direct-prod-write precedent until a staging twin is built as its own workstream.
- All remediation tracking in `ROADMAP.md` at repo root.

### Cycle timing

- Stage 5 DROP: on/after May 9.
- Q1 2026 13F cycle: expected ~May 15.
- Pre-cycle eligible: `CP-4b-discovery`, `CP-4b-author-top20`.
- Post-cycle: CP-5 (per `institution_scoping.md` §11.3 — defer past Q1 to avoid scope creep during cycle).

---

## conv-24-doc-sync (2026-05-01)

> **Status: superseded by conv-25 (2026-05-02). Retained for historical reference. See conv-25 above for current state.**

HEAD: **`f256e5e`** on `main` after the fund-level cleanup arc closed (PR #242 + branch-cleanup chore + PR #243). 11 PRs total in the consolidation+cleanup arc.

### What landed since `conv-23-doc-sync`

Three commits on top of the 8-PR consolidation arc (`#233`–`#241`):

- **PR [#242](https://github.com/sergetismen/13f-ownership/pull/242) `fund-cleanup-batch` (`5af96e1`)** — Combined cleanup session covering 4 fund-level follow-ups surfaced during PR-1a → PR-4: `canonical-value-coverage-audit` (3 read-only audits, 8 SQL queries against prod) + `verify-blackrock-muni-trust-status` (12-fund EDGAR check) + `verify-proshares-short-classification` (51-fund mechanics review) + `review-active-bucket` (3,184 UNKNOWN orphans + 8 named CEFs + 2 reclassifications). 2 reclassifications applied: AMG Pantheon Credit Solutions (`balanced` → `bond_or_other`) + AIP Alternative Lending Fund P (`active` → `bond_or_other`). New scripts: `scripts/oneoff/audit_canonical_coverage.py`, `scripts/oneoff/audit_active_bucket.py`, `scripts/oneoff/reclassify_credit_funds.py`. Findings: `docs/findings/fund_cleanup_batch_results.md`. Closes 4 P2 items; surfaces 2 new P2/P3 items.
- **branch-cleanup chore (`594a273`)** — Bulk prune of local branch sprawl after the consolidation arc closed. Pre-state: 80 local branches + 128 remote refs + 2 worktrees. Phase 1 audit categorised every branch using `git log <branch> --not main` + `gh pr list --state all` (242 PRs total: 239 MERGED, 3 CLOSED, 0 OPEN). Final categorisation: 5 MERGED / 71 SQUASH-MERGED / 2 UNMERGED / 1 WORKTREE-LOCKED / 1 main. Phase 2 deleted 5 MERGED via `git branch -d` and 71 SQUASH-MERGED via `git branch -D`. Post-state: 4 local branches (main + 1 active worktree + 2 closed-PR branches awaiting chat decision). Net delta: -76. Findings: `docs/findings/branch_cleanup_audit.md`.
- **PR [#243](https://github.com/sergetismen/13f-ownership/pull/243) `saba-proshares-reclassify` (`f256e5e`)** — Two whitelisted reclassifications, single PR. **Phase 1 — audit (read-only):** Saba inventory in `fund_universe`: exactly 2 funds (sibling pair). ProShares short/inverse/bear inventory: 52 funds (within plan range 45–55, STOP gate PASS); split 29 `bond_or_other` / 10 `excluded` / 13 `passive`. Whitelist for Phase 2 = 1 series_id (Saba Fund II). Whitelist for Phase 3 = 39 series_ids (the 29 + 10 currently non-`passive`). **Phase 2 — Saba reclassification:** Single transaction; 1 row in `fund_universe`, 1,603 rows in `fund_holdings_v2`. Saba sibling pair now both `balanced`. **Phase 3 — ProShares reclassification:** Single transaction; 39 rows in `fund_universe`, 1,342 rows in `fund_holdings_v2`. All 52 ProShares short/inverse/bear funds now `passive` (39 reclassified + 13 already `passive`). **Phase 4 — validation:** `pytest tests/` 373/373 PASS; PR-3 + PR-4 validators `overall: PASS` against all 7 affected endpoints. New scripts: `scripts/oneoff/reclassify_saba_proshares.py`. Findings: `docs/findings/saba_proshares_reclassify_results.md`. Closes P2 `proshares-short-reclassify-execute`.

### Reclassifications applied

| Fund | From → To | Source PR |
| --- | --- | --- |
| AMG Pantheon Credit Solutions | `balanced` → `bond_or_other` | #242 |
| AIP Alternative Lending Fund P | `active` → `bond_or_other` | #242 |
| Saba Capital Income & Opportunities Fund II | `multi_asset` → `balanced` | #243 |
| 39 ProShares short / inverse / leveraged-short funds | `bond_or_other` / `excluded` → `passive` | #243 |

### Verifications confirmed (no UPDATE)

- **12 BlackRock muni trusts on `final_filing`** — all confirmed terminated via merger Feb 2026: wave 1 (2026-02-09) Form 25-NSE delistings BFZ→MUC, MHN→MYN, BNY→MYN; wave 2 (2026-02-23) BusinessWire merger-completion press releases BKN→MQY, BTA→MUA, MUE→MHD, MVT→MYI, MVF→MYI, MYD→MQY, MQT→MQY, BFK→MHD, BLE→MHD. Post-merger NPORT-P (2026-03-26) and N-CSRS (2026-04-07) are residual administrative filings.
- **51 ProShares short / inverse / bear funds** — verified `passive` end-to-end (39 reclassified by #243 + 12 already `passive`). N-PORT holdings shape is uniformly swap notionals + cash/T-bill collateral; Morningstar classifies as "passively managed Trading-Inverse" ETFs.

### Branch cleanup detail

- Pre-cleanup: 80 local branches + 128 remote refs + 2 worktrees + 242 PRs (239 MERGED / 3 CLOSED / 0 OPEN).
- Post-cleanup: 4 local branches (`main`, `claude/competent-mclean-b334c6`, `claude/reverent-kirch-c1fcdf`, `ui-audit-01`).
- Net delta: -76 local branches.
- Remote refs unchanged at 128 — origin-side cleanup deferred to user `gh` workflow.
- 2 unmerged branches (PR CLOSED, not MERGED): both flagged DELETE in `conv-24-doc-sync` chat decision.

### Open follow-up status (8 items)

- **fund-holdings-orphan-investigation (P2, NEW)** — *highest data-integrity impact.* 302 series / 160K holdings rows on the NULL arm of `cross.py` 3-way CASE.
- **canonical-value-coverage-audit (P2, partially done in #242)** — Phase 1 (data-pull) covered; structured per-bucket count + AUM exposure + recommended treatment table is the still-open deliverable.
- **fund-strategy-taxonomy-finalization (P2, architectural)** — `balanced` / `multi_asset` / `bond_or_other` / `excluded` / `final_filing` review.
- **parent-level-display-canonical-reads (P2, institution-level)** — 18 read sites on `manager_type` / `entity_type` need migration.
- **per-fund-deferred-decisions (P3, NEW)** — Eaton Vance Tax-Advantaged variants × 3, Calamos Global Total Return Fund (loader gap), N/A-cohort 96 holdings rows (loader gap).
- **historical-fund-holdings-drift-audit (P3)** — 31,400 non-SYN drift rows.
- **stage-b-turnover-deferred-funds (P3, demoted from P2)** — Vanguard Primecap / Windsor II / Equity Income (~$203B) + Bridgeway Ultra-Small. Trigger is itself a separate larger initiative.
- **unmerged-branch-decisions (P3, both DELETE per chat)** — `claude/reverent-kirch-c1fcdf` + `ui-audit-01`.

### Architectural state (unchanged from conv-23)

- Single canonical column `fund_universe.fund_strategy`; pipeline lock + COALESCE in `load_nport.py`.
- `compute_peer_rotation._materialize_fund_agg` JOINs `fund_universe` (PR-4); per-quarter drift class structurally impossible.
- Display layer reads canonical via `_fund_type_label()` in `scripts/queries/common.py`.
- Snapshot semantics intentional: `fund_holdings_v2.fund_strategy_at_filing` frozen at filing moment; `fund_universe.fund_strategy` is the single source of truth for filters.
- Saba Fund I retains pre-existing snapshot drift (1,091 `active` + 1,094 `balanced` in `fund_holdings_v2`); intentionally preserved per `historical-fund-holdings-drift-audit`.

### Git ops

- **Doc-only commits (`conv-*` naming) push directly to `main`** — no PR.
- **Code merges PRs autonomously after CI passes** (rule from conv-18, reaffirmed each session).
- **Every Code prompt must start with the session/branch name on the first line.**

---

## conv-23-doc-sync (2026-05-01)

HEAD: **`414b824`** on `main` after the 8-PR fund-level classification consolidation arc closed (`#233`, `#235`, `#236`, `#237`, `#238`, `#239`, `#240`, `#241`).

### PRs landed (#233–#241; 8 PRs)

The fund-level classification consolidation arc closed end-to-end across 8 PRs in `2026-04-30 → 2026-05-01`:

- **PR #233 `fund-strategy-backfill` (PR-1a)** — Reconciled all legacy `fund_strategy` data so `fund_strategy = fund_category` everywhere and `is_actively_managed` is never NULL. Three phases: 333 legacy `{active,passive,mixed}` residuals in `fund_universe` → 0; 658 SYN funds with NULL `fund_strategy` → 0 (resolved via majority + most-recent quarter tiebreaker); 5,475,014 legacy holdings rows → 0 (orphan policy `equity` for 3,184 `series_id='UNKNOWN'` rows). Findings: `docs/findings/fund_strategy_backfill_results.md`.
- **PR #235 `peer-rotation-rebuild` (PR-1b)** — Rebuilt `peer_rotation_flows` against post-PR-1a `fund_holdings_v2`. 17,490,106 rows upserted; fund-level fully canonical (5,065,200 rows); parent-level untouched (12,424,906 rows). Findings: `docs/findings/peer_rotation_rebuild_results.md`.
- **PR #236 `classification-display-audit` (PR-1c)** — Read-only audit of every API endpoint and query module emitting a classification field. 27 of 40 user-facing FastAPI routes audited. Headline: display layer never read canonical source. Surfaced 6 confirmed display bugs + Decisions D1-D8 for PR-1d. Findings: `docs/findings/classification_display_audit.md`.
- **PR #237 `classification-display-fix` (PR-1d)** — Wired API/queries display layer to canonical fund-level classification. New utility `_fund_type_label(fund_strategy)` in `scripts/queries/common.py`; canonical 5-value display map. 12 fund-level read sites migrated across 5 files (`register.py`, `cross.py`, `fund.py`, `trend.py`, `market.py`). New validator: `scripts/oneoff/validate_classification_display_fix.py` (24/24 PASS). Findings: `docs/findings/classification_display_fix_results.md`.
- **PR #238 `index-to-passive` (PR-1e)** — Renamed `fund_strategy` value `'index'` → `'passive'` end-to-end (1,264 series + 3,055,575 holdings rows + classifier write path + display label utility). Findings: `docs/findings/index_to_passive_rename_results.md`.
- **PR #239 `classifier-name-patterns` (PR-2)** — Extended `INDEX_PATTERNS` in `scripts/pipeline/nport_parsers.py` with 8 new alternations (`qqq`, `target_date`, `target_retirement`, `\d+x` leveraged, `proshares`, `profund`, `direxion`, `daily inverse`, `inverse`). Added pipeline write-path lock (`_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE in `load_nport.py`). Reclassified 253 series + 186,943 holdings rows. Findings: `docs/findings/classifier_patterns_results.md`.
- **PR #240 `fund-strategy-consolidate` (PR-3)** — Dropped redundant `fund_universe.fund_category` and `fund_universe.is_actively_managed` columns end-to-end. New canonical constants `ACTIVE_FUND_STRATEGIES` / `PASSIVE_FUND_STRATEGIES` in `scripts/queries/common.py`; 9 sites migrated to derive `is_active` from these constants. Findings: `docs/findings/fund_strategy_consolidate_results.md`.
- **PR #241 `fund-strategy-rename` (PR-4)** — Three changes bundled in 11 phases: (1) value rename `'equity'` → `'active'` (4,832 + 3,555,766 rows); (2) column rename `fund_holdings_v2.fund_strategy` → `fund_strategy_at_filing` via DuckDB CTAS+DROP+RENAME (14,568,775 rows preserved, all 6 indexes restored); (3) architectural fix in `compute_peer_rotation._materialize_fund_agg` — `LEFT JOIN fund_universe.fund_strategy` replaces the per-row, per-quarter `MAX(fh.fund_strategy)` aggregate, eliminating the original drift class permanently. peer_rotation_flows rebuild: 17,490,106 rows preserved; 3,108 fund-level rows reclassified `active → balanced` (canonical now wins over snapshot). Findings: `docs/findings/fund_strategy_rename_results.md`.

### Key architectural changes

- **Canonical reads.** Display layer reads `fund_universe.fund_strategy` (canonical, locked) via `_fund_type_label()`. Filters JOIN `fund_universe`. Snapshot value at filing moment lives in `fund_holdings_v2.fund_strategy_at_filing` (intentional snapshot semantics; not used for filters).
- **Pipeline lock.** `_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE in `scripts/pipeline/load_nport.py` together prevent `fund_universe.fund_strategy` overwrite once a series carries a non-NULL value. Three-branch semantics covered by 5 unit tests in `tests/pipeline/test_load_nport.py`.
- **JOIN fix.** `compute_peer_rotation.py:_materialize_fund_agg` switched from per-row, per-quarter `MAX(fh.fund_strategy)` aggregate to `LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id`; emits `MAX(fu.fund_strategy)`. The per-quarter drift class is now structurally impossible.
- **Constants module.** `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` and `PASSIVE_FUND_STRATEGIES = ('passive','bond_or_other','excluded','final_filing')` adjacent to `_fund_type_label` in `scripts/queries/common.py`.
- **Schema cleanup.** `fund_universe.fund_category` and `fund_universe.is_actively_managed` columns dropped (PR-3). `fund_holdings_v2.fund_strategy` renamed to `fund_strategy_at_filing` (PR-4). Staging schemas (`stg_nport_holdings`, `stg_nport_fund_universe`) intentionally retain old names — prod write path renames at INSERT time; staging cleanup is a deferred PR.

### Findings docs produced

- `docs/findings/classification_consolidation_plan.md`
- `docs/findings/fund_strategy_backfill_results.md` (PR-1a)
- `docs/findings/peer_rotation_rebuild_results.md` (PR-1b)
- `docs/findings/classification_display_audit.md` (PR-1c)
- `docs/findings/classification_display_fix_results.md` (PR-1d)
- `docs/findings/index_to_passive_rename_results.md` (PR-1e)
- `docs/findings/classifier_patterns_results.md` (PR-2)
- `docs/findings/fund_strategy_consolidate_results.md` (PR-3)
- `docs/findings/fund_strategy_rename_results.md` (PR-4)

### Roadmap follow-ups added (P2 unless otherwise noted)

- **review-active-bucket** (renamed from `review-equity-bucket` per PR-4) — review the renamed `'active'` bucket for entries that need `bond_or_other` / `balanced` reclassification (AMG Pantheon Credit Solutions, AIP Alternative Lending, ASA Gold, NXG Cushing Midstream).
- **parent-level-display-canonical-reads** — institution-level half of the consolidation sequence; 18 parent-level read sites currently on `manager_type` / `entity_type` need migration to `entity_classification_history.classification` / `entity_current.classification`. Includes fix for `query4` silent-drop bug at [register.py:746-750](scripts/queries/register.py:746).
- **verify-blackrock-muni-trust-status** — verify whether 12 BlackRock muni trusts are actually liquidating (correct `final_filing`) or still trading (needs reclassification).
- **verify-proshares-short-classification** — ProShares short funds may belong in a new `inverse_or_short` bucket or be flipped to `passive`.
- **canonical-value-coverage-audit** — comprehensive audit of NULL `fund_strategy`, orphan series, edge cohorts, 3-way `CASE` NULL semantics in `cross.py`, and rows where `fund_holdings_v2.fund_strategy_at_filing` differs from `fund_universe.fund_strategy` (quantify the historical drift the PR-4 JOIN fix now papers over).
- **fund-strategy-taxonomy-finalization** — review and finalize the five edge categories (`balanced` / `multi_asset` / `bond_or_other` / `excluded` / `final_filing`) in the canonical taxonomy.
- **stage-b-turnover-deferred-funds** (position-turnover detection design) — Vanguard Primecap / Windsor II / Equity Income (~$203B AUM) and Bridgeway Ultra-Small Company Market are passive in behavior but won't match systemic INDEX_PATTERNS rules.

### Canonical taxonomy (post-PR-4)

`fund_universe.fund_strategy` ∈ `{active, balanced, multi_asset, passive, bond_or_other, excluded, final_filing}`. The display label utility collapses to 5 values: `{active, passive, bond, excluded, unknown}`.

### Where institution-level work picks up

The fund-level arc established the four-stage pattern: (1) backfill / reconcile data; (2) rebuild downstream tables; (3) audit display layer; (4) fix display + rename + lock. Institution-level needs the same shape but with different surface area:

- **Taxonomy decisions partially captured (prior chat session, not yet executed):** `pension`, `endowment`, `sovereign_wealth_fund` kept separate; `private_equity` + `venture_capital` → `pe_vc`; `wealth_management` + `family_office` → `wealth_mgmt`; `hedge_fund` + `multi_strategy` → `hedge_fund`. `mixed` and `unknown` still need review.
- **Data state to confront:** 1.4M+ parent-level rows in `holdings_v2.entity_type` carry legacy values.
- **Prerequisites:** `family_office` and `multi_strategy` migration from `manager_type` to `entity_classification_history` is a precondition for some merges.

### Known Issue closed

- **fund_strategy classification drift** — RESOLVED 2026-05-01 by the PR-2 + PR-4 sequence. Pipeline lock prevents `fund_universe` overwrite (PR-2); `compute_peer_rotation._materialize_fund_agg` JOINs canonical instead of reading per-quarter snapshot (PR-4). Drift class structurally impossible.

### Git ops

- **Code merges PRs autonomously after CI passes** (rule from conv-18, reaffirmed each session).
- **Doc-only commits (`conv-*` naming) push directly to `main`** — no PR.
- **Every Code prompt must start with the session/branch name on the first line.**

---

## conv-22-doc-sync (2026-04-30)

HEAD: **`7203539`** on `main` after PRs `#228`–`#229` merged.

### PRs landed (#228–#229)

Two PRs merged across the Cross-Ownership tab redesign + fix-up arc:

- **PR #228 `cross-ownership-polish`** — Cross-Ownership tab polish. (1) Peer Group dropdown driven by the loaded ticker's classification — new `GET /api/v1/peer_tickers?ticker=X` returns `{sector, industry, sector_peers, industry_peers}` from `market_data`; "Industry Peers" / "Sector Peers" auto-fill, "Custom" preserves manual editing (replaces the old `peer_groups` table-driven dropdown). (2) Inline ticker input always visible in the controls panel (Add button removed); commits on Enter or autocomplete. (3) Expandable institution rows match RegisterTab / OverlapAnalysisTab pattern (24px gold ▶ column + `└` connector child rows + gold left rail); expand fetches new `GET /api/v1/cross_ownership_fund_detail?tickers=…&institution=…&anchor=…&quarter=…` (top 5 N-PORT funds under that institution holding the active anchor by value). (4) Fund-level toggle now actually changes data: `_cross_ownership_query(level='fund')` pulls from `fund_holdings_v2`; both `/cross_ownership` and `/cross_ownership_top` accept `level=parent|fund`. (5) Group Total footer restyled gold per DarkStyle. (6) Page title appends current quarter via shared `fmtQuarter`. Squash `f46c88c`.
- **PR #229 `cross-ownership-fix`** — Cross-Ownership tab fix-ups on top of #228. (1) **Fund-level 500 fixed** — `_cross_ownership_fund_query` pivot was emitting `SUM(CASE WHEN fh.ticker = …)` against the outer `FROM fund_pos fp` aggregation (`BinderException`); pivot now references `fp.ticker` / `fp.holding_value`. (2) **`has_fund_detail` flag** added to `/cross_ownership` parent rollup — new `fund_parents` CTE collects DISTINCT `dm_rollup_name` ∪ `family_name` from `fund_holdings_v2` for the active quarter; LEFT JOIN exposes a per-investor boolean, frontend renders the `▶` only when true. (3) **`/cross_ownership_fund_detail` rewritten** for per-peer-ticker positions — accepts the full `tickers=…` list, returns `{fund_name, series_id, type, positions: {ticker → {value, shares}}}` for top 5 funds by total value across the peer group. (4) **Sticky summary block** — Group Total + % of Portfolio rows moved out of `<tfoot>` into `<thead>` with `position: sticky` (top 60 / 88), solid `var(--header)` bg, `var(--gold)` text + 700 weight, 2px gold borders top + bottom. (5) **Expanded child rows** mirror parent column structure — one row per fund, per-ticker columns from `positions[ticker].value`, missing tickers render `—`, Group Total column carries per-fund cross-peer total. Squash `f2194b8`.

### New / updated endpoints

- **NEW** `/api/v1/peer_tickers?ticker=X` — returns `{sector, industry, sector_peers, industry_peers}` for the loaded ticker (PR #228). Drives the peer-group dropdown.
- **NEW** `/api/v1/cross_ownership_fund_detail?tickers=…&institution=…&anchor=…&quarter=…` — top 5 N-PORT funds under an institution holding the active anchor by value (PR #228). Rewritten in PR #229 to return per-peer-ticker positions across the full `tickers=…` list.
- **UPDATED** `/api/v1/cross_ownership` and `/api/v1/cross_ownership_top` — accept `level=parent|fund` (PR #228); parent response gains `has_fund_detail` boolean (PR #229).

### fund_strategy classification drift (new Known Issue)

Surfaced this session and logged on `ROADMAP.md` "Known issues":

- **What:** `classify_fund()` recomputes the active/passive label per quarter, so the same series_id can flip values across periods. **6,195 of ~14,000 funds** in `fund_holdings_v2` currently carry 2+ distinct `fund_strategy` values across their history.
- **Pipeline fix:** lock `fund_universe.fund_strategy` on first classification — once a series_id has a non-null value, do not overwrite on later quarters unless an analyst forces a reclassification.
- **Query fix:** for `active_only` / passive filters, JOIN `fund_universe` to read the locked strategy instead of reading `fund_holdings_v2.fund_strategy` (per-row, drifts per quarter).
- **Scope rule:** both legs land in the same PR so the lock and the join cut over together.

### Git ops

- **Code merges PRs autonomously after CI passes** (rule from conv-18, reaffirmed in conv-21–22). Workflow: push branch → open PR → wait for CI green → `gh pr merge --squash --delete-branch` → `git pull` on main. Reflected in `docs/PROCESS_RULES.md` §11.
- **Every Code prompt must start with the session/branch name on the first line.**

---

## conv-21-doc-sync (2026-04-30)

HEAD: **`5c06e32`** on `main` after PRs `#223`–`#227` merged.

### PRs landed (#223–#227)

Five PRs merged across the SI table polish + Overlap Analysis tab redesign + global quarter label standardization arc:

- **PR #223 `si-table-quarter-polish`** — Fixed-width `colgroup` definitions across the 4 SI tables (CrossRef, ShortOnly, NportByFund, per-ticker detail) for consistent Type column alignment; quarter labels formatted to `Q4 '25` style ahead of the global `quarter-label-global` work in #226. Squash `a49bac5`.
- **PR #224 `overlap-tab-redesign`** — Overlap Analysis tab redesigned from a single side-by-side comparison to a vertical stack of two tables (institutional + fund). Each row expands to per-fund detail backed by the new `GET /api/v1/overlap_institution_detail` endpoint. Cross-ownership stat boxes summarize overlap counts and dollar value. Per-table "Active Only" toggles filter independently. Squash `0a6d759`.
- **PR #225 `overlap-column-stats`** — Overlap Analysis polish: spanning-header column groups (`% of Outstanding` / `Value ($MM)`), 8 KPI stat tiles above tables (institutional + fund × all-holders + active-only), 3-section row-expand (Overlapping / `{TICKER_A}` Only / `{TICKER_B}` Only — each capped at top 5 by value), totals footer rows. `/api/v1/overlap_institution_detail` updated to return `{overlapping, ticker_a_only, ticker_b_only}`. Squash `ebdc8f5`.
- **PR #226 `quarter-label-global`** — Shared `fmtQuarter` in `web/react-app/src/components/common/formatters.ts` (`"2025Q3" → "Q3 '25"`). `QuarterSelector` defaults `formatLabel` to it. Removed 7 tab-local copies (RegisterTab, OverlapAnalysisTab, InvestorDetailTab, OwnershipTrendTab cohort, SectorRotationTab, ShortInterestTab, FlowAnalysisTab). Quarter button arrays reordered oldest-left → newest-right. Squash `3248162`.
- **PR #227 `conv-21-doc-sync`** — This sync (direct to main).

### New / updated endpoints

- **NEW** `/api/v1/overlap_institution_detail` — per-institution overlap drill-down for the Overlap Analysis tab (PR #224). Updated in PR #225 to return `{overlapping, ticker_a_only, ticker_b_only}` (replacing earlier `non_overlapping`).

### Index benchmark coverage analysis

- New findings doc: `docs/findings/index_benchmark_coverage.md` — 27 benchmarks identified from `fund_universe` naming (S&P 500: 227 funds / $4.0T; Total Stock Market: 14 / $2.7T; Nasdaq 100: 98 / $579B; plus sector + international). 3,599 funds with "Index"/"ETF" in name ($4.6T) remain unmatched to a specific benchmark. 11 GICS sector benchmarks identified.
- New roadmap entry under **P2 — `index-benchmark-validation`**: 4-phase plan to systematize fund-to-index classification using N-PORT holdings data (reference table → correlation scoring → unmatched fund classification → sector fund integration).

### Session totals — conv-15 through conv-21

26 PRs merged (`#202`–`#227`) across:

- Dark UI restyle + page-level framing (PageHeader, ExportBar/FreshnessBadge alignment, controls panel borders).
- Sector Rotation tab redesign + polish + fund-view enhancements (heatmap, totals row, monthly tooltip, partial-quarter filter).
- Investor Detail tab introduction + 3-level hierarchy drill-down.
- N-PORT calendar-quarter fix (PR #213 — Jan-Mar→Q1, etc.) + derived-table rebuild.
- Short Interest tab full redesign + restored reference tables + chart polish + column alignment.
- Overlap Analysis tab full redesign (vertical stack, expandable rows, KPI tiles, 3-section expand, totals).
- Global UI consistency: page headers, export bar / freshness badge alignment, controls panel borders, compact density, quarter label standardization.

### Git ops

- **Code merges PRs autonomously after CI passes** (rule from conv-18, reaffirmed in conv-21). Workflow: push branch → open PR → wait for CI green → `gh pr merge --squash --delete-branch` → `git pull` on main. Reflected in `docs/PROCESS_RULES.md` §11.
- **Every Code prompt must start with the session/branch name on the first line.**

---

## conv-20-doc-sync (2026-04-30)

HEAD: **`3a5e2a1`** on `main` after PRs `#215`–`#222` merged.

### PRs landed (#215–#222)

Eight PRs merged across the Sector Rotation fund view + Short Interest redesign + UI alignment arc:

- **PR #215 `sr-fund-quarter-filter`** — Sector Rotation Fund-view enhancements: partial-quarter filter (drop incomplete destination quarters from the sector heatmap when `level='fund'`) + monthly hover tooltip. New `GET /api/v1/fund_quarter_completeness` and `GET /api/v1/sector_monthly_flows`. Squash `2a296ce`.
- **PR #216 `si-tab-redesign`** — Short Interest tab fully redesigned with sector/industry overlays. Two new endpoints: `GET /api/v1/short_position_pct` and `GET /api/v1/short_volume_comparison`. 5 KPI tiles. Squash `e9b09aa`.
- **PR #217 `si-restore-tables`** — Restored 3 tables dropped during the #216 redesign: CrossRef, ShortOnly, NportByFund. Squash `26b7553`.
- **PR #218 `sr-polish-v2` (on-main rebuild)** — Net flows heatmap table, totals row, movers panel beside heatmap, compact KPI labels. Same scope as #209; #218 is the on-`main` rebuild after subsequent SR work. Squash `89f2ac4`.
- **PR #219 `si-layout-fix`** — Short Interest layout polish: full-width stacked tables, axis-line removal, named legends (Ticker / Sector / Industry), FINRA-attribution footnote. Squash `f2b3e76`.
- **PR #220 `si-chart-table-align`** — Ticker series converted from bar chart to line-with-dots; column widths normalized across the 4 SI tables. Squash `ce54d6f`.
- **PR #221 `export-bar-align`** — `ExportBar` + `FreshnessBadge` moved into the top-right header row on every one of the 12 tabs. Squash `370619f`.
- **PR #222 `controls-panel-border`** — Bordered control panel applied to the 10 tabs that have controls bars (Overview, Holdings, Investors, Performers, Sector Rotation, Short Interest, Investor Detail, Network Map, Activity, Filings). Squash `3a5e2a1`.

### New endpoints

- `/api/v1/fund_quarter_completeness` — per-quarter `months_available` + `complete` flag (true iff 3 monthly N-PORT report-months filed) from `fund_holdings_v2`. Backs the SR Fund-view partial-quarter filter (PR #215).
- `/api/v1/sector_monthly_flows?sector=&quarter=` — per-month net flows for a given (sector, quarter) pair, computed from paired filers (funds present in both current and prior month). Backs the SR Fund-view monthly hover tooltip (PR #215).
- `/api/v1/short_position_pct` — per-ticker short-position percent of shares outstanding, time-series. Backs the redesigned Short Interest tab (PR #216).
- `/api/v1/short_volume_comparison` — per-ticker short-volume vs total-volume, time-series. Backs the redesigned Short Interest tab (PR #216).

### Git ops

- **Code now merges PRs autonomously after CI passes** (rule change from conv-18, reaffirmed in conv-20). Workflow: push branch → open PR → wait for CI green → `gh pr merge --squash --delete-branch` → `git pull` on main. Reflected in `docs/PROCESS_RULES.md`.

### Known issues

- **N-PORT quarter bucketing:** **CLOSED** by PR #213 (closed in conv-19).
- **No new known issues opened in conv-20.**

---

## conv-19-doc-sync (2026-04-30)

HEAD: **`e090ab7`** on `main` after PR #214 squash-merge, on top of PR #213.

### PRs landed (#213, #214)

- **PR #213 `nport-quarter-fix`** — N-PORT quarter bucketing fixed. `quarter_label_for_month()` rewritten to calendar convention (Jan–Mar→Q1, Apr–Jun→Q2, Jul–Sep→Q3, Oct–Dec→Q4); previously assigned `Q+1`. Migrated 14.6M `fund_holdings_v2` + 31K `fund_classes` + 22K `fund_holdings` rows. Rebuilt `parent_fund_map` (109K), `sector_flows_rollup` (321), `peer_rotation_flows` (17.5M, pruned 960K stale shifted rows). Cleared 3 stale `peer_rotation` manifest entries. Backup at `data/13f_pre_quarter_fix.duckdb`. Squash `19a7b15`.
- **PR #214 `tab-page-headers`** — Shared `PageHeader` component (gold section kicker, 24px light title, dim description) added to all 12 tabs for consistent page-level framing. UI-only, no data-logic or contract changes. Squash `e090ab7`.

### Known issues

- **N-PORT quarter bucketing:** **CLOSED** by PR #213.

---

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
