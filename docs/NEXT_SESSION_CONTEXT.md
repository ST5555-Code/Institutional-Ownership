# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## HEAD

`9cfe339` — `cp-4b-author-ssga: State Street/SSGA brand bridge to State Street Corp (#271)`. After conv-27-doc-sync merges, HEAD advances by one doc-only commit on top.

## Active workstream pointer

**`backup-pruning-and-archive`** is next (P3 ops). Local prune of ~63 GB across 20 backup directories under `data/backups/` plus Google Drive cold-storage offload of pruned backups (compress to `.tar.gz`, ~3 GB → ~600 MB each). Decisions deferred to execution time: target Google Drive folder, retention policy on cold storage, manual vs scripted upload (`gdrive` CLI / `rclone`). Single S ops PR. **Next substantive workstream after that:** `cp-4c-manual-sourcing` — methodology PR for the 15 deferred LOW-cohort brands (~$10.27T residual after the cp-4b carve-out arc).

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

1. `backup-pruning-and-archive` (next active, P3 ops — local prune + Google Drive offload).
2. `worktree-cleanup-hygiene` (P3 ops, ~10 min — retire cp-4b arc worktrees + earlier arc worktrees; cleans up `worktree-still-using-branch` warnings).
3. `cp-4c-manual-sourcing` (next substantive workstream — 15 LOW-cohort brands, ~$10.27T; methodology design then per-brand authoring; Equitable IM is first deferred case, gated on operating-filer verification).
4. Institution-merge pass — covers institution-side `unknown-classification-resolution` Waves 4a–4e (`unknown-classification-ncen-default-active` $4.5T lever, `unknown-classification-lp-suffix`, cleanup waves), Global X CRD backfill, then `admin-unresolved-firms-display`. Parked until CP-4 → CP-5 closes.
5. `fund-classification-by-composition` (Workstream 2) — discovery → design → execution for `fund_universe.fund_strategy` NULLs and orphan series. Parked.
6. `fund-to-parent-linkage` (Workstream 3) — re-establish fund-to-parent linkage for funds rolling up to deprecated/orphaned parent eids. Larger scope; may overlap with institution-merge. Parked.

## Recent backups (cumulative across recent arcs)

- `data/backups/13f_backup_20260503_072956` — pre-Wave-1 (unknown-classification cohort discovery / Tier A auto-resolutions).
- `data/backups/13f_backup_20260503_082307` — pre-fund-typed-ech-audit.
- `data/backups/13f_backup_20260503_110616` — pre-PR-C (pre PR #265 SCD close); also covered the cp-4b carve-out arc.
- `data/backups/13f_backup_20260503_121103` — post-PR-C (3.2 GB EXPORT, paired with PR #265).

`backup-pruning-and-archive` will offload most of these to Google Drive before local deletion.

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

## Gotchas surfaced this arc (not already in ROADMAP / memory)

None new. cp-4b carve-out arc executed cleanly against established gotchas (worktree-relative absolute paths; `entity_relationships` has no `notes` column — use structured `source` field; 14-column INSERT shape; `worktree-still-using-branch` warnings on `gh pr merge --delete-branch`, addressed by the new parked `worktree-cleanup-hygiene` ops PR; pytest baseline maintained post-arc).
