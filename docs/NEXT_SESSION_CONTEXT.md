# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

- bug-close-doc: moved stale bug-1 + bug-2 from P0 to COMPLETED (PR #153, `cfbbb1b`). P0 is now empty.
- backlog-collapse: tracker consolidation per `docs/findings/2026-04-25-backlog-collapse.md`

## Up next

- See `ROADMAP.md` "Current backlog" P1 / P2 sections (P0 empty).
- Sprint guidance: P1 first — `audit-tracker-staleness-ci` (discipline anchor for ROADMAP-only model), then perf-P0 + 43b SECURITY hardening + ui-audit walkthrough scheduling.

## Reminders

- Snapshot policy first real fire: 2026-04-25. Run `python scripts/hygiene/snapshot_retention.py --dry-run` then `--apply` to clear oldest cohort.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
