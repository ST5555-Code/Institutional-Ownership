# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

- backlog-collapse: tracker consolidation per `docs/findings/2026-04-25-backlog-collapse.md`

## Up next

- See `ROADMAP.md` "Current backlog" P0 / P1 sections.
- Sprint guidance: P0 first (bug-1 verification → bug-2 fix → audit-tracker-staleness-ci), then P1 perf-P0 + 43b SECURITY hardening + walkthrough scheduling.

## Reminders

- Snapshot policy first real fire: 2026-04-25. Run `python scripts/hygiene/snapshot_retention.py --dry-run` then `--apply` to clear oldest cohort.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
