# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session closed a **27-PR arc (#169–#196)** ending on `p3-audit-dryrun` (PR #196 — this PR). HEAD reflects the post-merge state of #196: `make audit` runner live; `--dry-run` flag uniform across all non-pipeline write scripts (`build_entities.py` + `resolve_adv_ownership.py` were the last two holdouts and shipped here); P3 backlog cleared of every non-UI item.

Three discrete legs across the 27 PRs:

1. **DM13 + INF48/49 + perf-P1 wave (PRs #169–#181, conv-14 close).** 797 ADV_SCHEDULE_A rollup edges suppressed + 2 hard-deleted; 2 NEOS / Segall Bryant entity merges; `sector_flows_rollup` + `cohort_analysis` cache → perf-P1 closed.
2. **N-PORT pipeline / dedup / 43g (PRs #183–#187, conv-15 close) + post-conv-15 trio (#189 BL-3+INF53, #190 perf-P2 scoping, #191 perf-P2 holder_momentum).** N-PORT topup +478K rows, INF50/INF52 hardening, 68 byte-identical INF51 dupes deleted, 3 redundant v2 columns dropped (migration 022), `parent_fund_map` precompute (migration 023, 5.6× holder_momentum speedup) → perf-P2 closed.
3. **End-of-arc P3 sweep (PRs #192–#196).** DM14c Voya residual ($21.74B / 49 series DM re-route); CSV file-system relocate + DERA synthetic-series discovery & promotion to P2; Rule 9 dry-run uniformity (8 scripts) + 43e family-office taxonomy (51 managers + 36,950 holdings reclassified); G7 `scripts/queries.py` 5,455-line monolith split into 8 domain modules; **this PR** wires `scripts/run_audits.py` + `make audit` and closes the dry-run sweep on the last two deferred scripts.

**Migrations 022 + 023 applied this arc.** No migration this PR.

## This session — Tasks A/B (PR #196)

| Task | Slug | Outcome |
|---|---|---|
| A | maintenance-audit-design | New `scripts/run_audits.py` runner wraps the 5 read-only audit / validation scripts (`check_freshness`, `verify_migration_stamps`, `validate_classifications`, `validate_entities --prod`, `validate_phase4`) in subprocess invocations that preserve each script's exit codes / JSON reports / side files. PASS / FAIL / MANUAL via `_classify(returncode, stdout)`; `--quick` skips the two slow checks; `--verbose` echoes full subprocess output. Returns 0 on all-PASS-or-MANUAL, 1 on any FAIL. New Makefile targets `audit` + `audit-quick`; new "Running Audits" section in `MAINTENANCE.md` between Standing curation and Monthly maintenance. No existing audit logic touched. |
| B | dry-run sweep follow-up | Closes the rule9-43e residual on the last two scripts. **`build_entities.py`:** top-level `--dry-run` guard in `main()` opens DuckDB read-only and prints the planned table operations (refresh-reference-tables 7-table DROP+CREATE, reset 7-table DELETE + 2-sequence DROP/CREATE) plus per-step row-count estimates from cheap `COUNT(*)` probes (PARENT_SEEDS, distinct CIKs in managers, fund_universe, ncen_adviser_map, cik_crd_links, cik_crd_direct). Composes with `--reset` and `--refresh-reference-tables`. **`resolve_adv_ownership.py`:** top-level `--dry-run` guard after target fetch (read-only DB open when set); resolves which phase(s) the selected mode would invoke and prints a numbered phase plan naming each phase's side-effect targets (PDF cache dir, `adv_schedules.csv`, the four `logs/phase35_*.csv` artifacts, staging entity tables). Covers all 8 modes — `--qc`, `--manual-add`, `--refresh`, `--oversized`, `--download-only`, `--parse-only`, `--match-only`, full default. `docs/PROCESS_RULES.md §9a` compliance table updated — both flipped ⚠️ deferred → ✅. Zero behavior change when `--dry-run` is not set. |

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** `DERA-synthetic-series-resolution` (1,236 synthetic series_ids covering 2,172,757 rows / **$2.55T NAV** / 1.58% of `is_latest=TRUE` market value; multi-day resolution via `scripts/resolve_pending_series.py:830-847` `deferred_synthetic` tier extension; see `docs/findings/2026-04-28-dera-synthetic-series-discovery.md`).
- **P3 (2 items, both UI):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog for review before Q1 2026 cycle (~2026-05-15).
  - `Type-badge family_office color` — `web/react-app/src/common/typeConfig.ts` needs a `family_office` case so the 36,950 reclassified `holdings_v2` rows render with a dedicated chip.
- **All non-UI P3 items cleared this arc.** `categorized-funds-csv-relocate` (PR #193), `DERA-synthetic-series-resolution` (PR #193, promoted to P2), `Rule 9 dry-run uniformity` (PR #194 + this PR), `43e family-office taxonomy` (PR #194), `G7 queries.py monolith split` (PR #195), `maintenance-audit-design` (this PR), `dry-run sweep follow-up` (this PR).
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; this is the gate to drop their snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes (`scripts/pipeline/load_nport.py` `_cleanup_staging` hard-fail + `_enrich_staging_entities` pre-promote enrich) **and** of `compute_parent_fund_map.py` quarterly rebuild. Re-measure synthetic-series count after this drop and judge whether the P2 resolution scope changed.

## Reminders

- **DERA synthetic-series is a P2 sprint slot, not a passive defer.** Resolution scope: extend `scripts/resolve_pending_series.py:830-847` `deferred_synthetic` tier to recover series→entity via DERA registrant tables + N-CEN adviser map + fund_cik-as-entity inference, then backfill `entity_id` / `rollup_entity_id` on the affected `fund_holdings_v2` rows and re-emit `parent_fund_map`. Validator FLAG (`series_id_synthetic_fallback`, `scripts/pipeline/load_nport.py:437`) stays in place until closure.
- **`make audit` is the new front door for read-only audits.** Wraps `check_freshness` + `verify_migration_stamps` + `validate_classifications` + `validate_entities --prod` + `validate_phase4`. `make audit-quick` skips the two slow checks (`validate_entities`, `validate_phase4`). See `MAINTENANCE.md` → "Running Audits" for baseline expectations (incl. the known `validate_entities` non-structural FAIL on `wellington_sub_advisory` until INF3 lands).
- **`--dry-run` is now uniform across every non-pipeline write script.** `docs/PROCESS_RULES.md §9a` is the audited compliance table. SourcePipeline subclasses inherit `--dry-run` from `scripts/pipeline/base.py` (halts at `pending_approval`).
- **`scripts/queries.py` is now a package: `scripts/queries/`.** 8 domain modules (`common`, `register`, `fund`, `flows`, `market`, `cross`, `trend`, `entities`) plus `__init__.py` re-exporting all 91 symbols. Existing `from queries import X` imports keep working unchanged. Touch the right domain file when adding/editing a query.
- **`scripts/backfill_manager_types.py` CSV path is `data/reference/categorized_institutions_funds_v2.csv`.** Edit in place. The script reads via `Path(__file__).parent.parent / 'data' / 'reference' / ...`.
- **`managers.strategy_type='family_office'` = 51 rows; `holdings_v2.manager_type='family_office'` = 36,950 rows** (PR #194 43e backfill). React badge config still shows the default chip until the P3 follow-up lands.
- **`fund_holdings_v2` is at 14,568,775 rows** post-INF51 dedup; 5,587,231 value-divergent rows across 55,924 groups remain documented as INF53 (closed recommendation-only per PR #189 — N-PORT multi-row-per-key is by design). **Plus 2,172,757 synthetic-series rows now formally FLAG/deferred under the P2 item** — same physical table, separate metadata defect.
- **Migration 023 (`parent_fund_map`)** is live; 109,723 rows. `holder_momentum` parent path now reads from it (5.6× speedup, PR #191). Quarterly rebuild via `python3 scripts/pipeline/compute_parent_fund_map.py` (~115s end-to-end) — trigger after the new-period 13F + N-PORT promotes.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema; a `--reset` would re-seed from a column the classifier no longer reads.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172 still open** — `dm13-de-discovery` triage CSV; close after reconciling with PR #173 outcome.
