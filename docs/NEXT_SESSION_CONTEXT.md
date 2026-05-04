# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## HEAD

`b24565f` — `worktree-cleanup-hygiene: retire 4 worktrees, 36 local branches, 6 orphan remotes + cef-asa diff archive (#274)`. After conv-28-doc-sync merges, HEAD advances by one doc-only commit on top.

## Active workstream pointer

**`cp-4c-manual-sourcing`** is the next substantive workstream when scheduled by chat — methodology PR for the 15 deferred LOW-cohort brands (~$10.27T residual after the cp-4b carve-out arc). Equitable IM (brand `eid=2562` → candidate filer `eid=9526` Equitable Holdings) is the **first deferred case**, gated on operating-filer verification. **No active P3 ops between now and then** — `backup-pruning-and-archive` (PR #273) and `worktree-cleanup-hygiene` (PR #274) both landed; both reframed as recurring-cadence successors (`backup-archive-cadence`, `worktree-cleanup-hygiene-cadence`) under P3 in ROADMAP.

## Architectural state (post-cp-4b-carve-out arc)

- **Two-canonical-classifications rule active** (locked 2026-05-03 via PRs #262–#265):
  - Institution → `entity_classification_history.classification` (canonical reader: `entity_current.classification`).
  - Fund → `fund_universe.fund_strategy` (canonical reader bridge: `classify_fund_strategy()` in `scripts/queries/common.py`).
  - Reads route by `entity_type`. Both classifications determined once, frozen, no revisit on refresh.
- **`entity_classification_history` carries zero open fund-typed rows.** PR #265 closed all 13,220 fund-typed open rows in a single transaction. Institution baseline unchanged at 13,930 open rows.
- **Fund-side reader bridge.** `classify_fund_strategy()` (PR #264) is the canonical helper. CP-5 (`parent-level-display-canonical-reads`) wraps it for the fund-side leg of the institution-level migration.
- **Writer paths gated.** Six fund-typed writers + a `resolve_long_tail` SQL filter were gated in PR #263; nine regression tests lock the gates.
- **BLOCKER 2 carve-out lock active** (locked 2026-05-03 via PR #269 addendum to `inst_eid_bridge_decisions.md`):
  - Strict-ADV cross-ref rule from BLOCKER 2 stays. Narrow exception: brands with 2+ orthogonal corroborating signals OR Bucket C raw-string-identical aliases (X2 alone) AND public-record verification qualify as `AUTHOR_NEW_BRIDGE`-eligible at MEDIUM confidence.
  - Carve-out applied across the cp-4b arc: 4 BRIDGE writes / ~$2,055.4B total — PR #267 (T. Rowe Price, HIGH), PR #269 (First Trust, MEDIUM Bucket B), PR #270 (FMR/Fidelity, MEDIUM Bucket C), PR #271 (SSGA/State Street, MEDIUM Bucket C).
  - 15 LOW-cohort brands / ~$10.27T residual deferred to `cp-4c-manual-sourcing`.

## Parked queue (priority order)

1. `backup-archive-cadence` (P3 recurring — re-run compress-and-prune workflow whenever `data/backups/` exceeds 3 retained directories; pre-organize `BackupToDrive/` into `full-db-exports/`/`staging-backup/`/`pipeline-snapshots/` per chat decision 2026-05-04 to make Drive upload single-folder drag-and-drop per category).
2. `worktree-cleanup-hygiene-cadence` (P3 recurring — re-run worktree-cleanup workflow whenever orphan worktrees + branches accumulate above ~5 entries; structural per PR #274 §7.5).
3. `cp-4c-manual-sourcing` (next substantive workstream — 15 LOW-cohort brands, ~$10.27T; methodology design then per-brand authoring; Equitable IM is first deferred case, gated on operating-filer verification).
4. Institution-merge pass — covers institution-side `unknown-classification-resolution` Waves 4a–4e (`unknown-classification-ncen-default-active` $4.5T lever, `unknown-classification-lp-suffix`, cleanup waves), Global X CRD backfill, then `admin-unresolved-firms-display`. Parked until CP-4 → CP-5 closes.
5. `fund-classification-by-composition` (Workstream 2) — discovery → design → execution for `fund_universe.fund_strategy` NULLs and orphan series. Parked.
6. `fund-to-parent-linkage` (Workstream 3) — re-establish fund-to-parent linkage for funds rolling up to deprecated/orphaned parent eids. Larger scope; may overlap with institution-merge. Parked.

## Recent backups (cumulative across recent arcs)

Only the 3 most recent backups remain locally per the retention rule locked in PR #273:

- `data/backups/13f_backup_20260503_082307` — pre-fund-typed-ech-audit.
- `data/backups/13f_backup_20260503_110616` — pre-PR-C (pre PR #265 SCD close); also covered the cp-4b carve-out arc.
- `data/backups/13f_backup_20260503_121103` — post-PR-C (3.2 GB EXPORT, paired with PR #265).

Older backups archived to Google Drive `ShareholderProject/13f-backups/{full-db-exports,staging-backup,pipeline-snapshots}/` (44 archives, 49.5 GB total, md5-verified). Per-archive paths and md5s in `docs/findings/backup-pruning-and-archive-results.md` and `data/working/backup-archive-manifest.csv`.

## Process rules in effect

These continue from prior session memory and apply to the next session:

- **Two-canonical-classifications rule** (above) — never write fund-typed rows to ECH; never read fund classification from ECH; route by `entity_type`.
- **BLOCKER 2 carve-out rule** (above) — strict-ADV cross-ref stays; only 2+ orthogonal signals or Bucket C identical-alias + public-record corroboration qualify for MEDIUM-confidence AUTHOR_NEW_BRIDGE writes.
- **Internal expert challenge before recommendations** — surface counter-arguments from the internal-expert lens before any recommendation is ratified.
- **No Code prompts until user confirms ready** — author Code prompts only after the user explicitly green-lights, never spec-and-ship.
- **All Code instructions in code boxes** — Code-bound instructions belong in fenced code boxes, not prose.
- **Architectural decisions paired with writer/reader audit** — every architectural decision (e.g., two-canonical-classifications, BLOCKER 2 carve-out) ships paired with a writer-side gate AND a reader-side audit.
- **Code session granularity:** one phase per session unless explicitly bundled in the prompt — `conv-*` doc-syncs are the only routine multi-phase bundle.
- **`entity_relationships` INSERT shape:** 14 columns. Confirmed across all four cp-4b PRs (#267, #269, #270, #271).
- **Direct-prod-write precedent for entity-layer one-off PRs** until a staging twin is built as its own architectural workstream.
- **Pre-flight backup before every prod-touch PR.** Confirm `mtime > DB mtime` and that the backup covers the latest commit before any `--confirm`.
- **No prompts without confirmation** when re-running an arc step; conv-* convention is direct-to-main with auto-merge after CI green.
- **`gh pr merge --delete-branch` workaround** (locked 2026-05-04 via PR #274 §7.5). The `gh pr merge --squash --delete-branch` command reliably fails to delete the local branch when the worktree using that branch is alive at merge time; the GitHub API DELETE on the branch ref succeeds silently with the worktree holding the ref, leaving the remote branch live. Empirically validated across recent arcs (PRs #265, #267, #270, #271, #272, #273, and PR #274 itself). Future arc PRs that run from a worktree should: (1) run `gh pr merge --squash` **without** `--delete-branch`; (2) `cd` to main repo; (3) run `git push origin --delete <branch>` manually; (4) defer worktree retirement to the next `worktree-cleanup-hygiene-cadence` run. Local cleanup blocked at merge time is a structural limitation of git worktree semantics, not a transient bug — cadence cleanup is the right shape.

## Gotchas surfaced this arc (not already in ROADMAP / memory)

None new. cp-4b carve-out arc executed cleanly against established gotchas (worktree-relative absolute paths; `entity_relationships` has no `notes` column — use structured `source` field; 14-column INSERT shape; `worktree-still-using-branch` warnings on `gh pr merge --delete-branch`, addressed by the new parked `worktree-cleanup-hygiene` ops PR; pytest baseline maintained post-arc).
