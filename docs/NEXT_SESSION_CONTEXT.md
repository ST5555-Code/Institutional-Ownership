# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

- pk-enforce: migration 020 declared PRIMARY KEY on 21 L3/L4 tables in prod (CTAS rebuild + inline PK; defaults preserved verbatim). 1 dup row deleted from `cik_crd_links`; `entity_current` view dropped + recreated; total wall 138s. `other_managers` deferred (5,518 NULL `other_cik` rows; PK shape needs review). Stamp `020_pk_enforcement` at 2026-04-26 08:18 UTC.

## Up next

- See `ROADMAP.md` "Current backlog" P1 / P2 sections (P0 empty).
- Sprint guidance: P1 `ui-audit-walkthrough` first (live walkthrough, not a Code session). P2 sprint candidates: `perf-P1`, `DM13`, `DM15d`, `snapshot-retention-cadence`, `pct-rename-sweep`.

## Reminders

- `security_type_inferred` column drop is a separate migration — not yet scheduled.
- `other_managers` PK still pending — proposed (accession_number, sequence_number, other_cik) is blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely (accession_number, sequence_number) with 19-row dedupe) before scheduling.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
