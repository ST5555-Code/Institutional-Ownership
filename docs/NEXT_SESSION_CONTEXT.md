# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## HEAD

`b5e1c76` — `cp-5-comprehensive-discovery-bundle-d: synthesis (#281)`. After conv-29-doc-sync merges, HEAD advances by one doc-only commit on top.

## Active workstream pointer

**CP-5 pre-execution work** starts next. The first substantive PR is one of the five P0 pre-execution items locked at PR [#281](https://github.com/ST5555-Code/Institutional-Ownership/pull/281). Chat-side decision on which order. Cycle-truncated merges and Adams duplicates are independent of each other (and of the rest), so could ship in parallel; loader-gap remediation has internal dependencies (entity creation before rollup rebuild — 3 sub-PRs); Capital Group umbrella is a one-off (Path A vs Path B decision-gated); pipeline contract gaps sized individually based on Bundle C §7.5 specifics.

The 26-PR execution plan is locked at `data/working/cp-5-execution-plan.csv`. The full design contract is at `docs/findings/cp-5-comprehensive-remediation.md`.

## Architectural state (post-CP-5 comprehensive discovery arc)

Existing locks remain in effect:

- **Two-canonical-classifications rule active** (locked 2026-05-03 via PRs #262–#265):
  - Institution → `entity_classification_history.classification` (canonical reader: `entity_current.classification`).
  - Fund → `fund_universe.fund_strategy` (canonical reader bridge: `classify_fund_strategy()` in `scripts/queries/common.py`).
  - Reads route by `entity_type`. Both classifications determined once, frozen, no revisit on refresh. Reaffirmed by Bundle A §2.4 (zero NULL `fund_strategy` in `fund_universe`).
- **`entity_classification_history` carries zero open fund-typed rows.** PR #265 closed all 13,220 fund-typed open rows in a single transaction. Institution baseline unchanged at 13,930 open rows.
- **Writer paths gated.** Six fund-typed writers + a `resolve_long_tail` SQL filter were gated in PR #263; nine regression tests lock the gates.
- **BLOCKER 2 carve-out lock active** (locked 2026-05-03 via PR #269 addendum to `inst_eid_bridge_decisions.md`):
  - Strict-ADV cross-ref rule from BLOCKER 2 stays. Narrow exception: brands with 2+ orthogonal corroborating signals OR Bucket C raw-string-identical aliases (X2 alone) AND public-record verification qualify as `AUTHOR_NEW_BRIDGE`-eligible at MEDIUM confidence.
  - Carve-out applied across the cp-4b arc: 4 BRIDGE writes / ~$2,055.4B total — PR #267 (T. Rowe Price, HIGH), PR #269 (First Trust, MEDIUM Bucket B), PR #270 (FMR/Fidelity, MEDIUM Bucket C), PR #271 (SSGA/State Street, MEDIUM Bucket C).
  - 15 LOW-cohort brands / ~$10.27T residual moved from `cp-4c-manual-sourcing` (closed as a standalone workstream) to the post-CP-5 cp-4c brand-bridges backlog (#20 in `data/working/cp-5-execution-plan.csv`).

New locks added by the CP-5 comprehensive discovery arc (locked 2026-05-04 via PRs #277–#281):

- **CP-5 R5 dedup rule** — for `(top_parent, ticker, cusip)` triples in 2025Q4: `result = MAX(thirteen_f, fund_tier_adjusted)` with intra-family FoF subtraction (~$2,207B) and non-valid-CUSIP filter on EC asset_category (~$5,172B); `13F_only` and `fund_only` top-parents handled explicitly. See cp-5-comprehensive-remediation.md §2.1.
- **Method A canonical** for fund→top-parent climb (read-time `entity_rollup_history` JOIN on `decision_maker_v1` + `valid_to='9999-12-31'`). Method B (`fund_holdings_v2.dm_rollup_entity_id`) is **not** canonical — goes stale after every ERH rebuild; retained as a cache-invalidation signal. See §2.2.
- **decision_maker_v1 canonical for institutional view (View 1)** — `economic_control_v1` retained for parallel sponsor-view queries. See §2.3.
- **Time-versioning Option C (hybrid)** — time-invariant default + override for known M&A events when historical data loads. SCD schema already supports it. M&A event register deferred to Pipeline 4+ scope. See §2.4.
- **View 2 scope** — Tier 1 N-PORT funds full PM-level decomposition; Tier 2 13D/G partial as "PM partial" with caveat; Tier 3 ($4.9T across 1,367 hedge fund / SMA / pension / family / SWF / VC / activist / endowment filers) as institutional-tier with explicit "no fund decomposition available" sentinel. See §2.7.

## Parked queue (priority order)

1. **CP-5 pre-execution P0 cohorts** (5 cohorts blocking CP-5.1; see ROADMAP P0):
   - `cp-5-cycle-truncated-merges` (21 entities / ~10–11 pairs; 2–3 batched merge PRs).
   - `cp-5-loader-gap-remediation` (84,363 rows / $418.5B; 1–3 sub-PRs — link existing CIKs, create new fund-typed entities, rollup rebuild).
   - `cp-5-capital-group-umbrella` (one-off; Path A vs Path B decided at execution time).
   - `cp-5-adams-duplicates` (120-row entity merge; 1 small PR).
   - `cp-5-pipeline-contract-gaps` (writer-gate hardening per Bundle C §7.5; sized individually).
2. **CP-5 execution P1** (6 stages, seqs 9–14 in `data/working/cp-5-execution-plan.csv`): CP-5.1 helper + Method A view → CP-5.2 Register tab → CP-5.3 Cross-Ownership/Top Investors/Top Holders → CP-5.4 Crowding/Conviction/Smart Money → CP-5.5 Sector Rotation/New-Exits/AUM/Activist → CP-5.6 View 2 Tier-3 sentinel.
3. **CP-5 post-execution backlog** (12 items, seqs 15–26): securities canonical_type loader fix, Method B disposition, bootstrap scripts disposition, operating-AM policy cleanup ($2.78T), cross-period CIK cleanup, cp-4c brand bridges (13 brands ~$8T), Pipelines 4/5/7, M&A event register Option C, Workstream 3 fund-to-parent residuals, Adams residual.
4. `fund-classification-by-composition` Workstream 2 — **CLOSED** (per Bundle A §2.4: 0 NULL `fund_strategy` in `fund_universe`). The orphan-fund classification residual reframed as part of `cp-5-loader-gap-remediation` per Bundle B §2.4.
5. `backup-archive-cadence` (P3 recurring — re-run compress-and-prune workflow whenever `data/backups/` exceeds 3 retained directories).
6. `worktree-cleanup-hygiene-cadence` (P3 recurring — re-run worktree-cleanup workflow whenever orphan worktrees + branches accumulate above ~5 entries).

## Recent backups

Only the 3 most recent backups remain locally per the retention rule locked in PR #273:

- `data/backups/13f_backup_20260503_082307` — pre-fund-typed-ech-audit.
- `data/backups/13f_backup_20260503_110616` — pre-PR-C (pre PR #265 SCD close); also covered the cp-4b carve-out arc.
- `data/backups/13f_backup_20260503_121103` — post-PR-C (3.2 GB EXPORT, paired with PR #265).

Older backups archived to Google Drive `ShareholderProject/13f-backups/{full-db-exports,staging-backup,pipeline-snapshots}/` (44 archives, 49.5 GB total, md5-verified). Per-archive paths and md5s in `docs/findings/backup-pruning-and-archive-results.md` and `data/working/backup-archive-manifest.csv`.

## Process rules in effect

These continue from prior session memory and apply to the next session:

- **Two-canonical-classifications rule** (above) — never write fund-typed rows to ECH; never read fund classification from ECH; route by `entity_type`.
- **BLOCKER 2 carve-out rule** (above) — strict-ADV cross-ref stays; only 2+ orthogonal signals or Bucket C identical-alias + public-record corroboration qualify for MEDIUM-confidence AUTHOR_NEW_BRIDGE writes.
- **Audit-prompt sum-identity rule** (locked 2026-05-04 via PR [#279](https://github.com/ST5555-Code/Institutional-Ownership/pull/279) `cp-5-coverage-matrix-revalidation`). When computing pre/post numerical deltas across a cohort with non-uniform per-row inflation factors, prefer sum-identity gates (`|orig − sum(parts)| ≤ ε`) over ratio-bound gates. Sum-identity holds exactly across heterogeneous data; ratio bounds trip on legitimate per-entity variance. Cross-reference: ROADMAP `## Process rules` section (full statement + PR #279 evidence).
- **Internal expert challenge before recommendations** — surface counter-arguments from the internal-expert lens before any recommendation is ratified.
- **No Code prompts until user confirms ready** — author Code prompts only after the user explicitly green-lights, never spec-and-ship.
- **All Code instructions in code boxes** — Code-bound instructions belong in fenced code boxes, not prose.
- **Architectural decisions paired with writer/reader audit** — every architectural decision (e.g., two-canonical-classifications, BLOCKER 2 carve-out, the new CP-5 contract) ships paired with a writer-side gate AND a reader-side audit.
- **Code session granularity:** one phase per session unless explicitly bundled in the prompt — `conv-*` doc-syncs are the only routine multi-phase bundle.
- **`entity_relationships` INSERT shape:** 14 columns. Confirmed across all four cp-4b PRs (#267, #269, #270, #271).
- **Direct-prod-write precedent for entity-layer one-off PRs** until a staging twin is built as its own architectural workstream.
- **Pre-flight backup before every prod-touch PR.** Confirm `mtime > DB mtime` and that the backup covers the latest commit before any `--confirm`.
- **No prompts without confirmation** when re-running an arc step; conv-* convention is direct-to-main with auto-merge after CI green.
- **`gh pr merge --delete-branch` workaround** (locked 2026-05-04 via PR #274 §7.5). The `gh pr merge --squash --delete-branch` command reliably fails to delete the local branch when the worktree using that branch is alive at merge time; the GitHub API DELETE on the branch ref succeeds silently with the worktree holding the ref, leaving the remote branch live. Empirically validated across recent arcs (PRs #265, #267, #270, #271, #272, #273, and PR #274 itself). Future arc PRs that run from a worktree should: (1) run `gh pr merge --squash` **without** `--delete-branch`; (2) `cd` to main repo; (3) run `git push origin --delete <branch>` manually; (4) defer worktree retirement to the next `worktree-cleanup-hygiene-cadence` run. Local cleanup blocked at merge time is a structural limitation of git worktree semantics, not a transient bug — cadence cleanup is the right shape.

## Gotchas surfaced this arc (not already in ROADMAP / memory)

- **Method A vs Method B drift is real and material.** SSGA cp-4b bridge (PR #271) surfaced $778.2B drift between the live ERH JOIN (Method A) and the denormalized `fund_holdings_v2.dm_rollup_entity_id` (Method B). Method B is now formally deprecated as canonical; CP-5.1 builds on Method A. Method B's residual role is as a cache-invalidation signal: rows where `dm_rollup_entity_id ≠ Method A` flag the loader denormalization for backfill.
- **Coverage matrix double-count via missing rollup_type filter.** PR #276's coverage matrix double-counted FoF positions because the rollup query did not filter by `entity_rollup_history.rollup_type='decision_maker_v1'` — fund-tier positions appeared once per rollup_type row. PR #279 hotfixed; combined AUM corrected $102.0T → $75.2T (−26%). Any future ERH-aware aggregation must include the `rollup_type` filter.
- **Ratio-bound STOP gates are unsafe across heterogeneous cohorts.** PR #279 STOP gate originally tripped on BlackRock (1.73×) and Fidelity (2.04×) under a ratio-bound gate that turned out to encode legitimate per-entity variance, not error. Lifted into a permanent process rule (above).
