# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `nport-refresh-catchup` (worktree `zealous-lalande-bcbf7b`, branch `claude/zealous-lalande-bcbf7b`):

- **N-PORT monthly-topup catch-up landed.** `python3 scripts/pipeline/load_nport.py --monthly-topup` ingested **1,164 NPORT-P accessions / 478,446 holdings rows** filed at SEC since the prior topup on 2026-04-16. Distribution: 2026-02 = 475,060 rows / 1,140 accessions (bulk — funds racing the Apr 30 filing deadline), 2026-03 = 3,315 / 19, 2026-01 = 40 / 1, 2025-12 = 31 / 4 (amendments). `fund_holdings_v2` row count **14,090,397 → 14,568,843**; 71 prior `is_latest=TRUE` rows flipped on (series, month) amendments.
- **MAX(report_month) is_latest=TRUE = 2026-03** (3,379 rows / 20 series — early-reporters only). Substantive coverage through 2026-02 (476,173 rows / 1,155 series). This is current relative to the SEC's 60-day public-release lag — Q1 2026 DERA bulk lands ~late May 2026, fills out 2026-03 fully.
- **INF52 logged in ROADMAP under P2** — first encounter of a real N-PORT pipeline ↔ int-23 guard conflict. `LoadNPortPipeline.parse` (load_nport.py:731-734) deliberately NULLs `entity_id`/`rollup_entity_id`/`dm_entity_id`/`dm_rollup_entity_id`/`dm_rollup_name` and relies on post-promote `_bulk_enrich_run` to populate them. The int-23 downgrade-refusal guard (base.py:631, `_DOWNGRADE_SENSITIVE_COLUMNS = ('ticker','entity_id','rollup_entity_id')`) fires inside `_promote_append_is_latest` BEFORE the post-promote enrich and refuses if prod has non-NULL values for those keys. Today's failure: 5 (series, month) keys in 2025-12 amendments (Bretton Capital Management funds S000068707-068711) with prod entity_id set. **Why it didn't fire on Apr 15 DERA Session 2 / Apr 16 topup:** those touched mostly NEW (series, month) keys with no prior prod rows to displace. Will re-fire on every amendment-heavy topup. Two correct fixes (own PR): (a) populate entity columns inside `parse()` via the same JOIN `_bulk_enrich_run` uses, or (b) move `_bulk_enrich_run` to between parse and promote. **Workaround used today:** Python one-shot `UPDATE staging.fund_holdings_v2 SET entity_id, rollup_entity_id, dm_entity_id, dm_rollup_entity_id, dm_rollup_name FROM (JOIN against prod entity_identifiers + entity_rollup_history + entity_aliases on series_id)`, then `UPDATE ingestion_manifest SET fetch_status='pending_approval', error_message=NULL WHERE run_id=...`, then `LoadNPortPipeline().approve_and_promote(run_id)` driven from a Python REPL — bypasses the failed→pending_approval state-machine block. 462,595 of 478,446 rows enriched (96.7%); 65 series unmatched but zero overlapped with prod's non-NULL entity_id rows (no guard-trigger).
- **Staging cleanup also required pre-promote.** stg_nport_holdings had 11.1M leftover rows from the Apr 15 DERA Session 2 promote that never got cleaned up by `_cleanup_staging` (silent failure pattern flagged but **not fixed in this PR**). Cleaned via `DELETE FROM stg_nport_holdings WHERE DATE(loaded_at) < '2026-04-27'` + same on `stg_nport_fund_universe` + `DROP TABLE staging.fund_holdings_v2`. After cleanup, staging held only today's 478K rows / 1,164 accessions across 4 report_months — exactly the topup payload.
- **Pre-promote backup taken** — `data/backups/13f_backup_20260427_131151` (3.1 GB, EXPORT DATABASE PARQUET). Per MAINTENANCE.md ad-hoc backup protocol.
- **Downstream precomputes rebuilt against fresh data:**
  - `compute_sector_flows.py` — `sector_flows_rollup` 321 rows, 2.1s. (CLI changed: no longer accepts `--auto-approve`; no-flag = full promote. MAINTENANCE.md updated.)
  - `compute_flows.py` — `investor_flows` 19,224,688 rows / `ticker_flow_stats` 69,142 rows across 4Q/3Q/2Q/1Q × economic_control_v1/decision_maker_v1, 22.3s.
  - `build_summaries.py` — `summary_by_ticker` 42,593 / `summary_by_parent` 63,916, 2.0s.
- **Snapshot refreshed twice** — once auto by N-PORT promote, once manually post-downstream. Final `data/13f_readonly.duckdb` mtime 2026-04-27 14:57:32, 7.7 GB, 368 tables.
- **`scripts/validate_entities.py` run on prod** — Summary `{'PASS': 7, 'FAIL': 1, 'MANUAL': 8}`. Sole FAIL is the pre-existing `wellington_sub_advisory` (unchanged, non-structural). `total_aum` PASS confirms the topup didn't disturb the ~$166B INF4c gate.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only.
- **P2:** `ui-audit-01 perf-P2` (precompute `flow_analysis` + `market_summary` + `holder_momentum`); **INF52** (N-PORT × int-23 guard fix — recommend Option (a): populate entity columns inside `parse()`).
- **P3:** `43g drop redundant type columns`, `BL-3 Write-path consistency (non-entity)`, `D10 Admin UI for entity_identifiers_staging`.
- **Next external event:** Q1 2026 13F cycle, ~2026-05-15 (filings for period ending 2026-03-31, 45-day reporting window).

## Reminders

- **`fund_holdings_v2_enrichment` not rebuilt this session** — last computed 2026-04-17. Separate cadence; next refresh is on a different trigger. Stale relative to today's N-PORT topup but not in user's standard rebuild list.
- **`_cleanup_staging` failure pattern observed but not fixed.** stg_nport_holdings retained Apr 15 DERA Session 2 rows; today's session cleaned manually. Worth investigating in a separate PR — likely the `_cleanup_staging` exception handler is too permissive (catches and warns but leaves data behind). Not assigned an INF number yet.
- **1.36M duplicate (series, month, accession, cusip) rows in prod since 2025-12** observed during state inspection. Not from today's promote (which was clean). Pre-existing artifact of prior promotes. Idempotency cleanup is a separate exercise. Not assigned an INF number yet.
- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09** per `MAINTENANCE.md`. Do not drop earlier.
- **No `--reset` runs anywhere** without explicit user authorization.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **DM14c Voya residual** still deferred — DM14b edge-completion has not landed.
- **PR #172 still open** — dm13-de-discovery triage CSV; close after reconciling with PR #173 outcome.
- **App on port 8001** (pid 15724 at session-start, started 9:43 AM 2026-04-27, `python scripts/app.py --port 8001`) ran throughout — uses readonly snapshot, doesn't lock prod, picks up snapshot refreshes per request. The `start_app.sh stop` early in this session only killed an unrelated uvicorn on port 8000 (which was the CIC project's app, not 13f).
