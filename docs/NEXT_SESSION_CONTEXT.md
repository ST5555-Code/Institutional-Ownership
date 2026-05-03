# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## HEAD

`9e58e8f` — `close-fund-typed-ech-rows: 13,220-row SCD close (#265)`. After conv-26-doc-sync merges, HEAD advances by one doc-only commit on top.

## Active workstream pointer

**`cp-4b-author-trowe`** is next. Single-brand BRIDGE write for T. Rowe Price (~$1.11T fund-side AUM). Same `wholly_owned` + `control_type='control'` shape as PR #258 (BlackRock 5-way). Pre-cycle eligible. See ROADMAP P2 entry; manifest derives from CP-4b-discovery (PR #260).

## Architectural state (post-fund-typed-ech-cleanup arc)

- **Two-canonical-classifications rule active** (locked 2026-05-03 via PRs #262–#265):
  - Institution → `entity_classification_history.classification` (canonical reader: `entity_current.classification`).
  - Fund → `fund_universe.fund_strategy` (canonical reader bridge: `classify_fund_strategy()` in `scripts/queries/common.py`).
  - Reads route by `entity_type`. Both classifications determined once, frozen, no revisit on refresh.
- **`entity_classification_history` carries zero open fund-typed rows.** PR #265 closed all 13,220 fund-typed open rows in a single transaction. Institution baseline unchanged at 13,930 open rows.
- **Fund-side reader bridge.** `classify_fund_strategy()` (PR #264) is the canonical helper. CP-5 (`parent-level-display-canonical-reads`) wraps it for the fund-side leg of the institution-level migration.
- **Writer paths gated.** Six fund-typed writers + a `resolve_long_tail` SQL filter were gated in PR #263; nine regression tests lock the gates.

## Parked queue (priority order)

1. `cp-4b-author-trowe` (next active, P2, S, pre-cycle eligible)
2. `cp-4b-blocker2-corroboration-probe` (read-only, P2, pre-cycle eligible)
3. `backup-pruning` (P3 ops, ~60 GB / 19 directories — Apr 22–28 + May 1–3 backup window)
4. Institution-side unknown-classification waves — Wave 4a `unknown-classification-ncen-default-active` ($4.5T lever), Wave 4b `unknown-classification-lp-suffix`, Waves 4c–4e cleanup, Global X CRD backfill, then `admin-unresolved-firms-display`. Parked until institution-merge pass (CP-4 → CP-5) starts.
5. `fund-classification-by-composition` (Workstream 2) — discovery → design → execution for `fund_universe.fund_strategy` NULLs and orphan series. Parked.
6. `fund-to-parent-linkage` (Workstream 3) — re-establish fund-to-parent linkage for funds rolling up to deprecated/orphaned parent eids. Larger scope; may overlap with institution-merge. Parked.

## Recent backups (this arc)

- `data/backups/13f_backup_20260503_110616` — pre-PR-C (pre PR #265 SCD close).
- `data/backups/13f_backup_20260503_121103` — post-PR-C (3.2 GB EXPORT, paired with PR #265).

Pre-arc backup paths from prior PRs continue to live under `data/backups/` and are candidates for the parked `backup-pruning` ops PR.

## Process rules in effect

These continue from prior session memory and apply to the next session:

- **Two-canonical-classifications rule** (above) — never write fund-typed rows to ECH; never read fund classification from ECH; route by `entity_type`.
- **Direct-prod-write precedent for entity-layer one-off PRs** until a staging twin is built as its own architectural workstream (see ROADMAP — staging-workflow note under `inst-eid-bridge`).
- **Pre-flight backup before every prod-touch PR.** Confirm `mtime > DB mtime` and that the backup covers the latest commit before any `--confirm`.
- **No prompts without confirmation** when re-running an arc step; conv-* convention is direct-to-main with auto-merge after CI green.
- **Code session granularity:** one phase per session unless explicitly bundled in the prompt.

## Gotchas surfaced this arc (not already in ROADMAP / memory)

None new. Arc executed cleanly against established gotchas (worktree-relative absolute paths; `entity_relationships` has no `notes` column — use structured `source` field; SCD open sentinel is `valid_to = DATE '9999-12-31'`; pytest 416/416 baseline post-arc).
