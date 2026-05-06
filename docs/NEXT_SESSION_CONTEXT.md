# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## HEAD

`d11cfba` on `main` — `cp-5-aum-subtree-callers-recon: full caller map + sequencing` (PR #307). Read-only investigation closing `cp-5-aum-subtree-redesign` as no-op. CP-5.6 confirmed independent of `compute_aum_for_subtree`.

**Active branch:** `cp-5-5b-precompute-rebuild` at `a53b8ac` (plan `a3fe7cd` + addendum `a53b8ac` committed; Phases 0+1 complete; parked before Phase 2 generator updates). Lives in worktree `.claude/worktrees/gifted-goldwasser-8fed2e`.

## Active workstream pointer

**Resume CP-5.5b at Phase 2 (generator updates)** per `docs/findings/cp-5-5b-precompute-rebuild-plan.md`.

## Resumption directives

**Read FIRST:**

- `docs/findings/cp-5-5b-precompute-rebuild-plan.md` (plan `a3fe7cd` + addendum `a53b8ac` — primary state doc).
- `docs/findings/CHAT_HANDOVER.md` conv-31a section (this commit).

**Decision locks for CP-5.5b (do not re-debate):**

- Option B for 029a `peer_rotation_flows` (generator-driven side-build via CTAS-and-swap).
- Column-drop CTAS for 029b `investor_flows` (`rollup_entity_id` already 100% populated).
- Hard cap 3% G1 row expansion (abort threshold).
- `shares_history`: in-PR if found and single read-path swap; escalate only if structural.

**6 reader sites in scope** (canonical file:line via HEAD grep, NOT recon csv which has stale line numbers):

- `market.py:316` `get_sector_flow_movers`
- `market.py:475` `get_sector_flow_mover_detail`
- `trend.py:678` `get_peer_rotation_detail`
- `flows.py:506` `flow_analysis` investor_flows read
- `flows.py:515` (subsumed)
- `register.py:633` (NAME-keyed against `investor_flows`; bundled per Q2 default)

## Architectural state (post-PR #307)

**4 op-shape extensions canonical** (cp-4a + Adjustments 1/2/3/4) — see `docs/decisions/inst_eid_bridge_decisions.md`. Adjustment 1 (close-on-collision in Op G); Adjustment 2 (Op A.3 holdings_v2 re-point); Adjustment 3 (Op A.4 entity_identifiers SCD transfer); Adjustment 4 (column-independent two-step Op A — supersedes one-step OR-clause Op A in true-duplicate-merge contexts).

**DuckDB CTAS-and-swap pattern canonical for column drops on PK-bearing tables**. Reference: migrations 025 + 026 + 029b (pending CP-5.5b).

**`unified_holdings` view live in prod** (PR #299 + #300): `inst_to_top_parent` recursive CTE + 5.17M-row R5 aggregate keyed on `(top_parent_entity_id, quarter, cusip, ticker)`.

**Method A canonical** (read-time ERH JOIN) for institutional view. Method B (denormalized `dm_rollup_*`) physically removed from fh2 (#289), holdings_v2 (#296), bo_v2 (#297).

**`cp-5-aum-subtree-redesign` closed as no-op** (PR #307 investigation). `compute_aum_for_subtree` correctly serves Entity Graph filer-grain semantics.

Existing locks remain in effect:

- **Two-canonical-classifications rule active** (PRs #262–#265): institution → ECH; fund → `fund_universe.fund_strategy`.
- **`entity_classification_history` carries zero open fund-typed rows** post PR #265.
- **Writer paths gated** for fund-typed targets (PR #263, 9 regression tests).
- **BLOCKER 2 carve-out lock active** (PR #269 addendum). 4 BRIDGE writes / ~$2,055.4B across cp-4b arc. 15 LOW-cohort brands / ~$10.27T residual deferred to post-CP-5 cp-4c.

## Parked queue (priority order)

1. **CP-5.5b** (current, in-progress at Phase 2 generator updates).
2. **CP-5.6 View 2 Tier-3 sentinel** (P1, next; 4 PENDING_CP5_6 sites — institution-hierarchy, `holder_momentum` fund children, `get_entity_descendants`, `search_entity_parents`). Independent of CP-5.5b.
3. **conv-31-doc-sync proper** (CP-5 closure; formalize standing rules #15/#16/#17; ROADMAP cleanup including `cp-5-aum-subtree-redesign` close, BlackRock brand-vs-filer reminder, Bundle C csv hygiene refresh).
4. **CP-5.2 sub-PRs:**
   - `cp-5-2a-summary-by-parent-rebuild` (P1, blocked on Bundle C Q7 chat decision).
   - `cp-5-2b-manager-type-imputation-recon` (P1, read-only).
   - `cp-5-2c-register-drill-hierarchy` (P1, blocked on `cp-5-2a`; absorbs 2 cross.py BLOCKED_DRILL sites from CP-5.3).
5. **CP-5 post-execution backlog** (P3, seqs 15–26 in execution plan): securities canonical_type loader fix, Method B disposition, bootstrap scripts disposition, operating-AM policy cleanup ($2.78T), cross-period CIK cleanup, **cp-4c brand bridges** (13 brands ~$8T), Pipelines 4/5/7, M&A event register Option C, **Workstream 3 fund-to-parent residuals**, Adams residual.
6. **`cp-5-fof-subtraction-cusip-linkage`** (P2; build CUSIP→fund-entity bridge so Bundle A §1.4 FoF subtraction can re-enter `unified_holdings`; surfaced PR #299 Phase 2).
7. **New P3 audit entries** (carried from prior arc):
   - `cycle-adjacent-entity-audit` (Sarofim Trust Co eid 858 + similar; PR #285).
   - `entity-current-inverted-rollup-audit` (canonical 4909 inverted-rollup pattern; PR #283 Op H Branch 2).
   - `parent-bridge-mechanism-audit` (sponsor-brand layer scope; PR #287).
   - `fund-cik-entity-type-audit` (N-PORT-seeded registrant CIKs typed `'institution'` not `'fund'`; PR #290).
   - `cp-5-adams-residual-cleanup` (6 fund-typed eids 20210–20215 with no open rollup rows; PR #299 Phase 0).
8. **Cadence successors:**
   - `backup-archive-cadence` (P3 recurring; first execution PR #292).
   - `worktree-cleanup-hygiene-cadence` (P3 recurring).

## Recent backups

Three retained EXPORT directories locally per cadence rule (PR #273 + #292):

- `data/backups/13f_backup_20260506_165238` (CP-5.5b pre-flight #1, 3.2GB).
- `data/backups/13f_backup_20260506_065231`.
- `data/backups/13f_backup_20260505_165855`.

Older backups archived to Google Drive `ShareholderProject/13f-backups/{full-db-exports,staging-backup,pipeline-snapshots}/` per PR #273 + PR #292 cadence runs.

## Process rules in effect

These continue from prior session memory and apply to the next session:

- **Two-canonical-classifications rule** — never write fund-typed rows to ECH; never read fund classification from ECH; route by `entity_type`.
- **BLOCKER 2 carve-out rule** — strict-ADV cross-ref stays; only 2+ orthogonal signals or Bucket C identical-alias + public-record corroboration qualify for MEDIUM-confidence AUTHOR_NEW_BRIDGE writes.
- **Audit-prompt sum-identity rule** (PR #279). Prefer sum-identity gates over ratio-bound gates across heterogeneous cohorts.
- **DuckDB DROP COLUMN with PRIMARY KEY → CTAS-and-swap** (PR #296). Reference: migrations 025 + 026.
- **Audit pipeline readers when scoping schema drops** (PR #296). Grep `scripts/pipeline/`, `scripts/compute_*`, `scripts/build_*` — not just `scripts/queries/` + `scripts/api_*.py`.
- **New entities need both rollup types at creation** (PRs #291 + #293). INSERT self-rollup rows for **both** `decision_maker_v1` AND `economic_control_v1`.
- **`entity_identifiers` schema — no `is_preferred` column** (PR #291). Uses `confidence` / `source` / `is_inferred`.
- **Internal expert challenge before recommendations**.
- **No Code prompts until user confirms ready**.
- **All Code instructions in code boxes**.
- **Architectural decisions paired with writer/reader audit**.
- **Code session granularity:** one phase per session unless explicitly bundled in the prompt — `conv-*` doc-syncs are the only routine multi-phase bundle.
- **`entity_relationships` INSERT shape:** 14 columns.
- **Direct-prod-write precedent for entity-layer one-off PRs** until a staging twin is built.
- **Pre-flight backup before every prod-touch PR.** Confirm `mtime > DB mtime` and that the backup covers the latest commit before any `--confirm`.
- **`gh pr merge --delete-branch` workaround** (PR #274 §7.5). Run `gh pr merge --squash` without `--delete-branch`, then `git push origin --delete <branch>` manually from main repo.
- **Single-file `.duckdb` default delete-direct in cadence runs** (PR #292).

**New rules locked this arc** (will formalize as standing rules #15/#16/#17 in conv-31-doc-sync proper):

- **Helper alias variant default** (PR #303 §6.4) — DuckDB binder fails ambiguity inside cross-join shape (`FROM table_a, cte_b`) when noalias variant of `top_parent_canonical_name_sql()` is used. Default to alias variant uniformly.
- **Recon schema verification at execute time** (PR #306 Phase 1) — recon recommendations claiming "one-line swap" require schema verification at execute time. Every execute Phase 1 includes schema verification step against recon's claimed migration target.
- **Helper alias self-consistency** (CV2 + S2) — helper alias use must stay self-consistent across SELECT and WHERE clauses; outer aliases need disambiguation when the helper takes 'h'.
- **Code merges + cleans up after explicit chat approval** (amended R5, locked 2026-05-06). After chat says "merge <N>", Code runs full sequence (`gh pr merge --squash`, defensive untracked-file cleanup, pull main, optional remote branch delete, report new HEAD). Standard PR creation safety convention unchanged: stop at PR creation, wait for chat review.
