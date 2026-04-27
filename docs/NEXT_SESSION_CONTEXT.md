# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `roadmap-priority-moves` (branch `roadmap-priority-moves`, no DB writes, no schema changes, no code touched):

- Three items moved from Deferred to active backlog in `ROADMAP.md`:
  - **`ui-audit-01 perf-P2`** (`flow_analysis` + `market_summary` + `holder_momentum` precompute) → **P2**. Trigger ("perf-P0 + perf-P1 shipped AND latency complaints persist") partially met — perf-P0 (PRs #158 / #159) and perf-P1 (PRs #180 / #181) both shipped. Activated proactively ahead of VPS hosting rather than waiting for in-prod latency complaints.
  - **`BL-3 Write-path consistency (non-entity)`** → **P3**. Trigger ("non-entity write-path bug surfaces in prod") not yet fired; activated as preventive hardening before production traffic. Target scope per `docs/write_path_risk_map.md` is the T2 tier — `build_cusip` / `build_managers` / `load_13f` / `unify_positions` / `compute_flows` / `fetch_adv` / `fetch_13dg` (drop+recreate without explicit BEGIN/COMMIT/ROLLBACK).
  - **`D10 Admin UI for entity_identifiers_staging`** → **P3**. Trigger ("next admin UI iteration") not yet fired; activated to surface the 280-row staging backlog for review before the Q1 2026 cycle (~2026-05-15).
- Three rows removed from the Deferred table; new entries added under P2 (perf-P2) and P3 (BL-3 + D10, after `43g`). New `roadmap-priority-moves` row added at the top of the COMPLETED table.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude walkthrough — not a Code session).
- **P2:** `ui-audit-01 perf-P2` — precompute `flow_analysis` + `market_summary` + `holder_momentum`.
- **P3:** `43g drop redundant type columns`, `BL-3 Write-path consistency (non-entity)`, `D10 Admin UI for entity_identifiers_staging`.
- Next external event: **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).

## Reminders

- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09** per `MAINTENANCE.md`. Do not drop earlier.
- **No `--reset` runs anywhere** without explicit user authorization.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely `(accession_number, sequence_number)` with 19-row dedupe) before scheduling.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts: Gotham / Mairs & Power / Brandes / Crawford / Bridges / Champlain / FPA) remains deferred behind DM6 (N-1A parser) or DM3 (N-PORT metadata extension).
- **DM14c Voya residual** still deferred — DM14b edge-completion has not landed.
- **PR #172 still open** — dm13-de-discovery triage CSV; close after reconciling with PR #173 outcome.
