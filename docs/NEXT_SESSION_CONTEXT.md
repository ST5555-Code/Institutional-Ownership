# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `conv-15-doc-sync` (worktree `gifted-joliot-dc6ce8`, branch `claude/gifted-joliot-dc6ce8`):

- **End-of-session doc sync.** Pure documentation; no DB writes, no schema changes, no code touched. Refreshes `docs/NEXT_SESSION_CONTEXT.md` (full rewrite), `docs/findings/CHAT_HANDOVER.md` (full rewrite), `MAINTENANCE.md` (date stamp), and verifies `ROADMAP.md` COMPLETED table.
- **HEAD at sync:** `2ca71f7` (43g-drop-redundant-columns, PR #187).
- **19-PR session arc (#169–#187).** This sync closes the second leg (`#183–#187`) of the longer arc that began with the DM13 sweep at PR #168 and was previously partially summarised by `conv-14-doc-sync` (PR #182, covered #169–#181). Total active landings since #168: 18 merged + 1 still-open (#172).

## This leg — PRs #183–#187

| PR | Slug | Notes |
|---|---|---|
| #183 | roadmap-priority-moves | Three Deferred items activated: `perf-P2` → P2; `BL-3` write-path consistency + `D10` admin UI for `entity_identifiers_staging` → P3. Pure ROADMAP / `NEXT_SESSION_CONTEXT.md` re-prioritization; no DB writes, no code. Activated proactively ahead of VPS hosting / Q1 2026 cycle, not in response to a fired trigger. |
| #184 | nport-refresh-catchup | N-PORT monthly-topup landed **1,164 NPORT-P accessions / 478,446 holdings rows** filed since 2026-04-16. `fund_holdings_v2` 14.09M → 14.57M; 71 prior `is_latest=TRUE` rows flipped on amendments. 2026-02 reports near Apr 30 deadline; 2026-03 stays partial (60-day SEC public-release lag — Q1 2026 DERA bulk lands ~late May 2026). Two pipeline blockers worked around in-session and logged: stale `stg_nport_holdings` from Apr 15 DERA Session 2 silent-failed cleanup (manually purged), and **INF52** int-23 downgrade-refusal vs entity-enrichment-ordering (workaround: pre-enriched `staging.fund_holdings_v2` from prod entity tables + force-reset failed manifest). Pre-promote backup `data/backups/13f_backup_20260427_131151` (3.1 GB). |
| #185 | inf50-52-nport-pipeline-fixes | **Code-only N-PORT pipeline hardening.** `_cleanup_staging` rewritten to drop all 3 staging tables on one connection with a post-cleanup `CatalogException` assertion (`raise RuntimeError("...staging is contaminated...")` on any leak); broad `except Exception → warning` removed. New `_purge_stale_raw_staging` at start of `fetch()` clears leftover rows. New `_enrich_staging_entities(prod_con, series_touched)` mirrors `_bulk_enrich_run`'s JOIN against `entity_identifiers` + `entity_rollup_history` (EC + DM) + `entity_aliases` and runs UPDATE on `staging.fund_holdings_v2` BEFORE `super().promote()`. Step ordering documented in the docstring as `enrich → promote → re-enrich (safety net)`. 6 new unit tests; 22/22 nport tests pass; 230/230 smoke + pipeline pass. **Not yet exercised against prod** — first live test is the next pipeline run that touches amendments (next monthly topup or Q1 2026 DERA bulk). |
| #186 | INF51 prod-dedup | Investigation reframed the prompt's premise (1.36M trivial dupes) — of 5.53M apparent `(series_id, report_month, accession_number, cusip)` duplicates, **only 68 rows / 64 groups are true byte-identical duplicates** (deleted via single targeted `DELETE`); the other 5.59M rows / 55,924 groups are value-divergent (different shares/value/pct on the same key) and fall under the spec's "keep both, flag for manual review" carve-out. `fund_holdings_v2` 14,568,843 → **14,568,775** rows; aggregates unchanged (each removed row was byte-identical to its kept sibling). Logged **INF53** (BACKFILL_MIG015 multi-row pattern, 54,437 of 55,924 affected groups originate from `BACKFILL_MIG015_*` accessions) as P3 follow-up. Pre-DELETE backup `data/backups/13f_backup_20260427_191936` (3.2 GB). 5-ticker `/api/v1/summary` spot check post-snapshot-rebuild all 200 in <300ms. |
| #187 | 43g-drop-redundant-columns | **Migration 022 stamped.** Three write-only columns dropped from v2 holdings tables: `holdings_v2.crd_number`, `holdings_v2.security_type`, `fund_holdings_v2.best_index`. Reference scan across `scripts/`, `web/`, `tests/` (excluding `scripts/migrations/` and `scripts/retired/`) found zero live READs. Rebuild path used because DuckDB 1.4 refuses `DROP COLUMN` when any index/PK references a later column ordinal and `ALTER TABLE … DROP CONSTRAINT` is unsupported — both v2 tables carry a `row_id` PK + 6 user indexes downstream of the drops. Per-table flow: drop user indexes; `CREATE TABLE …_new` with surviving columns + original `nextval('<table>_row_id_seq')` default + `PRIMARY KEY (row_id)`; `INSERT INTO …_new SELECT …`; `DROP TABLE`; `RENAME`; recreate all 12 indexes. End-to-end on prod 25 GB DB: **38s wall** (372% CPU). Row counts preserved: 12,270,984 holdings_v2 + 14,568,775 fund_holdings_v2. Writer-side cleanups co-shipped in `scripts/load_13f_v2.py`, `scripts/pipeline/load_nport.py`, `tests/pipeline/test_load_13f_v2.py`. Int-23 protected columns (`ticker`, `entity_id`, `rollup_entity_id`, `is_latest`) untouched. AAPL + EQT smoke-tested across 8 endpoints; `npm run build` clean; `pytest tests/` 364 passed; `validate_entities.py --prod` `total_aum` PASS at 0.0% diff. |

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** `ui-audit-01 perf-P2` (precompute `flow_analysis` + `market_summary` + `holder_momentum`).
- **P3:** `BL-3 Write-path consistency (non-entity)`, `D10 Admin UI for entity_identifiers_staging`, `INF53 BACKFILL_MIG015 multi-row investigation`.
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; this is the gate to drop their snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes.

## Reminders

- **INF50 + INF52 fixes are code-only and have not been exercised against prod yet.** Next monthly topup that touches amendments (or the Q1 2026 DERA bulk) is the live test. If the post-cleanup `CatalogException` assertion ever fires, capture the full `RuntimeError` — that is the actual root cause of the prior silent failure, finally visible.
- **The 11M-row staging contamination from Apr 15 DERA Session 2 is already cleaned** (manually purged during 2026-04-27 `nport-refresh-catchup`). Pre-fetch purge will catch any future recurrence.
- **`fund_holdings_v2` is now at 14,568,775 rows** post-INF51 dedup (delta -68 from 14,568,843). 5,587,231 value-divergent rows across 55,924 groups remain pending **INF53** investigation (by-design vs migration bug).
- **Migration 022 landed on prod.** `holdings_v2.crd_number`, `holdings_v2.security_type`, and `fund_holdings_v2.best_index` are gone. Any lingering writers will fail loudly; smoke-test any writer touched in the next session before promote.
- **`fund_holdings_v2_enrichment` not rebuilt this session** — last computed 2026-04-17. Separate cadence; next refresh is on a different trigger.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows) closing toward the Apr 30 filing deadline. Latest full month is 2026-01 (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- **No `--reset` runs anywhere** without explicit user authorization.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **DM14c Voya residual** still deferred — DM14b edge-completion has not landed.
- **PR #172 still open** — dm13-de-discovery triage CSV; close after reconciling with PR #173 outcome.
