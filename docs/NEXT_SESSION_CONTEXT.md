# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

- eqt-classify-codefix: classifier stops reading stale `security_type_inferred` (PR #162). Two-line fix in `cusip_classifier.py` Steps 1 + 3. 8,148 CUSIPs reclassified, 662K holdings ticker changes, 342 `manual_correction` rows eliminated.
- doc-sync: moved eqt-classify-codefix from P2 to COMPLETED (this PR).

## Up next

- See `ROADMAP.md` "Current backlog" P1 / P2 sections (P0 empty).
- Sprint guidance: P1 `ui-audit-walkthrough` first (live walkthrough, not a Code session). P2 sprint candidates: `perf-P1`, `DM13`, `DM15d`, `snapshot-retention-cadence`, `pct-rename-sweep`.

## Reminders

- `security_type_inferred` column drop is a separate migration — not yet scheduled.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
