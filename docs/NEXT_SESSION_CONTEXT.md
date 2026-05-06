# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## HEAD

`<cp-5-1b squash>` — `cp-5-1b-helper-and-view: foundation for CP-5 reader migrations` (PR #299). Sits atop `4db5b0c` (PR #297 conv-30-doc-sync + bo_v2 drop). Adds migration 027 (read-only views `inst_to_top_parent` + `unified_holdings`) plus `top_parent_holdings_join()` helper in `scripts/queries/common.py`. **Zero row mutations** — view-only catalog migration.

## Active workstream pointer

**CP-5.2 — Register tab reader migration.** CP-5.1 foundation shipped via PR #299: `inst_to_top_parent` view (recursive ownership climb with deterministic tie-break) + `unified_holdings` view (R5 cross-source aggregate, FoF subtraction deferred to P2 `cp-5-fof-subtraction-cusip-linkage`) + `top_parent_holdings_join()` helper. CP-5.2–5.6 reader migrations follow across Register, Cross-Ownership, Top Investors, Top Holders, Crowding, Conviction, Smart Money, Sector Rotation, New/Exits, AUM, Activist, View 2 Tier-3 sentinel.

**Open chat question for CP-5.2:** `unified_holdings` is multi-quarter (sums across all `is_latest=TRUE` rows per migration 015 policy). Register is single-quarter. Design call needed: (a) parameterize the view by quarter; (b) add a quarter-specific sister view; or (c) keep Register on direct source-table reads with helper supporting only the climb step.

The 26-PR execution plan is locked at `data/working/cp-5-execution-plan.csv`. The full design contract is at `docs/findings/cp-5-comprehensive-remediation.md`. Adjustments 1/2/3/4 canonical addenda at `docs/decisions/inst_eid_bridge_decisions.md`.

## Architectural state (post-CP-5 P0 pre-execution arc)

**CP-5 P0 pre-execution arc CLOSED 2026-05-05.** All 11 cohorts shipped: Adams duplicates (#283), cycle-truncated merges (#285), Capital Group umbrella (#287, Path A), fh2 dm_rollup decision + drop (#288, #289), loader-gap remediation sub-PRs 1 + 2 (#290, #291), backup cadence (#292), PR #287 ERH audit (#293), pipeline contract cleanup (#294), sister-tables sized investigation (#295), holdings_v2 dm_rollup drop (#296), and this PR (bo_v2 dm_rollup drop bundled with the doc-sync).

**4 op-shape extensions canonical** (cp-4a + Adjustments 1/2/3/4) — see `docs/decisions/inst_eid_bridge_decisions.md`. Adjustment 1 (close-on-collision in Op G); Adjustment 2 (Op A.3 holdings_v2 re-point); Adjustment 3 (Op A.4 entity_identifiers SCD transfer); Adjustment 4 (column-independent two-step Op A — supersedes one-step OR-clause Op A in true-duplicate-merge contexts). Adjustment 4 was caught via STOP-gate on PR #285 Goldman Pair 1 ($91.08B THIRD-entity attribution theft prevented; cohort exposure $142.21B).

**DuckDB CTAS-and-swap pattern canonical for column drops on PK-bearing tables** (locked 2026-05-05 via PR #296 + this PR). Reference: migrations 025 + 026.

Existing locks remain in effect (continued from prior session memory):

- **Two-canonical-classifications rule active** (locked 2026-05-03 via PRs #262–#265): institution → ECH; fund → `fund_universe.fund_strategy`.
- **`entity_classification_history` carries zero open fund-typed rows** post PR #265.
- **Writer paths gated** for fund-typed targets (PR #263, 9 regression tests).
- **BLOCKER 2 carve-out lock active** (locked 2026-05-03 via PR #269 addendum). 4 BRIDGE writes / ~$2,055.4B across cp-4b arc (#267, #269, #270, #271). 15 LOW-cohort brands / ~$10.27T residual deferred to post-CP-5 cp-4c.
- **CP-5 R5 dedup rule** + **Method A canonical** (read-time ERH JOIN; Method B `dm_rollup_entity_id` formally deprecated and now physically removed from fh2/holdings_v2/bo_v2 per PRs #289/#296/this PR) + **decision_maker_v1 canonical for institutional View 1** + **Time-versioning Option C (hybrid)** + **View 2 scope** (Tier 1 N-PORT full / Tier 2 13D/G partial / Tier 3 sentinel). See `docs/findings/cp-5-comprehensive-remediation.md` §2.

## Parked queue (priority order)

1. ~~**CP-5.1**~~ **shipped 2026-05-06 via PR #299** (`cp-5-1b-helper-and-view`). Migration 027 + helper. Resolves `classification-join-utility-resolution` decision (helper landed at `scripts/queries/common.py::top_parent_holdings_join`, not the proposed `classification_join` macro at `queries_helpers.py:171` — that dead-code decision is now reducible to a delete in the next sweep).
2. **CP-5.2 Register tab** reader migration (P1, **next up**).
3. **CP-5.3 Cross-Ownership / Top Investors / Top Holders** reader migration (P1).
4. **CP-5.4 Crowding / Conviction / Smart Money** reader migration (P1).
5. **CP-5.5 Sector Rotation / New-Exits / AUM / Activist** reader migration (P1).
6. **CP-5.6 View 2 Tier-3 sentinel** (P1).
7. **CP-5 post-execution backlog** (P3, seqs 15–26 in execution plan): securities canonical_type loader fix, Method B disposition, bootstrap scripts disposition, operating-AM policy cleanup ($2.78T), cross-period CIK cleanup, **cp-4c brand bridges** (13 brands ~$8T, #20), Pipelines 4/5/7, M&A event register Option C, **Workstream 3 fund-to-parent residuals**, Adams residual.
8. **New P3 audit entries** (surfaced during this arc):
   - `cycle-adjacent-entity-audit` (Sarofim Trust Co eid 858 + similar; surfaced PR #285).
   - `entity-current-inverted-rollup-audit` (canonical 4909 inverted-rollup pattern; surfaced PR #283 Op H Branch 2).
   - `parent-bridge-mechanism-audit` (sponsor-brand layer scope; surfaced PR #287).
   - `fund-cik-entity-type-audit` (N-PORT-seeded registrant CIKs typed `'institution'` not `'fund'`; surfaced PR #290).
   - `cp-5-adams-residual-cleanup` (6 fund-typed eids 20210–20215 with no open rollup rows; surfaced PR #299 Phase 0).
   - `cp-5-fof-subtraction-cusip-linkage` (P2; build CUSIP→fund-entity bridge so Bundle A §1.4 FoF subtraction can re-enter `unified_holdings`; surfaced PR #299 Phase 2).
9. **Cadence successors:**
   - `backup-archive-cadence` (P3 recurring; first execution PR #292).
   - `worktree-cleanup-hygiene-cadence` (P3 recurring).

## Recent backups

Pre-flight backup taken 2026-05-06 before PR #299 schema-altering migration: `data/backups/13f_pre_cp5_1b_20260506_100527.duckdb` (single-file `.duckdb`, 24GB; same-day EXPORT covers state per single-file-default delete-direct cadence rule).

Three retained EXPORT directories locally per cadence rule (PR #273):

- `data/backups/13f_backup_20260506_065231`
- `data/backups/13f_backup_20260505_165855`
- `data/backups/13f_backup_20260505_142125`

Older backups archived to Google Drive `ShareholderProject/13f-backups/{full-db-exports,staging-backup,pipeline-snapshots}/` per PR #273 + PR #292 cadence runs. Per-archive paths and md5s in `docs/findings/backup-pruning-and-archive-results.md` and `data/working/backup-archive-manifest.csv`.

## Process rules in effect

These continue from prior session memory and apply to the next session:

- **Two-canonical-classifications rule** — never write fund-typed rows to ECH; never read fund classification from ECH; route by `entity_type`.
- **BLOCKER 2 carve-out rule** — strict-ADV cross-ref stays; only 2+ orthogonal signals or Bucket C identical-alias + public-record corroboration qualify for MEDIUM-confidence AUTHOR_NEW_BRIDGE writes.
- **Audit-prompt sum-identity rule** (locked 2026-05-04 via PR #279). Prefer sum-identity gates over ratio-bound gates across heterogeneous cohorts. Cross-reference: ROADMAP `## Process rules`.
- **DuckDB DROP COLUMN with PRIMARY KEY → CTAS-and-swap** (locked 2026-05-05 via PR #296). DuckDB has no `ALTER TABLE DROP CONSTRAINT`; rebuild table with `SELECT * EXCLUDE (...)`, swap, restore PK + indexes verbatim. Reference: migrations 025 + 026.
- **Audit pipeline readers when scoping schema drops** (locked 2026-05-05 via PR #296). Grep `scripts/pipeline/`, `scripts/compute_*`, `scripts/build_*` — not just `scripts/queries/` + `scripts/api_*.py`. PR #295's user-facing audit missed 5 pipeline readers that PR #296 caught.
- **New entities need both rollup types at creation** (locked 2026-05-05 via PRs #291 + #293). INSERT self-rollup rows for **both** `decision_maker_v1` AND `economic_control_v1` — `entity_current` sources from EC; missing the EC self-rollup makes the entity invisible to that view. Inline pattern from PR #291 Op E2.
- **`entity_identifiers` schema — no `is_preferred` column** (locked 2026-05-05 via PR #291). Uses `confidence` / `source` / `is_inferred`. `is_preferred` lives on `entity_aliases` only.
- **Internal expert challenge before recommendations** — surface counter-arguments from the internal-expert lens before any recommendation is ratified.
- **No Code prompts until user confirms ready** — author Code prompts only after the user explicitly green-lights, never spec-and-ship.
- **All Code instructions in code boxes** — Code-bound instructions belong in fenced code boxes, not prose.
- **Architectural decisions paired with writer/reader audit** — every architectural decision ships paired with a writer-side gate AND a reader-side audit.
- **Code session granularity:** one phase per session unless explicitly bundled in the prompt — `conv-*` doc-syncs are the only routine multi-phase bundle.
- **`entity_relationships` INSERT shape:** 14 columns. Confirmed across all four cp-4b PRs (#267, #269, #270, #271).
- **Direct-prod-write precedent for entity-layer one-off PRs** until a staging twin is built as its own architectural workstream.
- **Pre-flight backup before every prod-touch PR.** Confirm `mtime > DB mtime` and that the backup covers the latest commit before any `--confirm`.
- **`gh pr merge --delete-branch` workaround** (locked 2026-05-04 via PR #274 §7.5). Run `gh pr merge --squash` without `--delete-branch`, then `git push origin --delete <branch>` manually from main repo; defer worktree retirement to next `worktree-cleanup-hygiene-cadence` run.
- **Single-file `.duckdb` default delete-direct in cadence runs** (locked 2026-05-05 via PR #292). Single-file `.duckdb` full-DB snapshots can be deleted directly when same-day EXPORT covers the same state — avoids the redundant compress + archive cycle.

## Gotchas surfaced this arc (not already in ROADMAP / memory)

- **Method A vs Method B drift is real and material.** SSGA cp-4b bridge (PR #271) surfaced $778.2B drift; PR #295 sister-table investigation surfaced $8.16T `holdings_v2` drift across 42 parents. Method B (`dm_rollup_entity_id`) is now formally deprecated AND physically removed from fh2 (#289), holdings_v2 (#296), and bo_v2 (this PR).
- **Pipeline-reader audit scope was incomplete in PR #295.** PR #295 scoped `scripts/queries/` + `api_*.py` only and concluded "zero readers" for both holdings_v2 + bo_v2 dm_rollup columns. PR #296 caught 5 pipeline readers (`compute_flows`, `build_summaries`, `compute_peer_rotation`, `compute_parent_fund_map`, `build_fixture`) that the user-facing audit missed. Codified as new process rule.
- **`entity_current` is a VIEW that requires economic_control_v1 self-rollup at entity creation.** PR #287 (Capital Group, Path A) reused a long-standing eid that already had both rollup types. PR #291 (loader-gap sub-PR 2) surfaced this — initial draft created entities with only `decision_maker_v1` self-rollup; entities were invisible to `entity_current` until Op E2 was added inline. PR #293 audited PR #287 to confirm. Codified as new process rule.
- **`entity_identifiers` does not have an `is_preferred` column.** Earlier prompts referenced it from the alias-table mental model. Uses `confidence` / `source` / `is_inferred`. Codified as new process rule.
- **`holdings_v2` PRIMARY KEY blocked DROP COLUMN.** PR #296 surfaced that DuckDB has no `ALTER TABLE DROP CONSTRAINT`, so the implicit PK index forced a CTAS-and-swap rebuild. Same mechanic on `beneficial_ownership_v2` in this PR. Codified as new process rule.
- **DuckDB EXPORT PARQUET writes pre-compressed** (locked 2026-05-04 via PR #273; reaffirmed PR #292). Snappy default; re-gzip yields ~10–20%. Don't lower-bound compression-ratio gates.
- **Bundle B §1.3 was wrong about eid=12 having no inst→inst edges.** Current state shows 87 such rows on eid=12 alone, all on the sponsor-brand layer (`fund_sponsor`/`advisory` with `source='parent_bridge'`). Two-relationship-layer coexistence pattern codified by PR #287. New P3 `parent-bridge-mechanism-audit` to formalize the loader's contract.
