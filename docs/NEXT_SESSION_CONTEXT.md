# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `csv-cleanup-g7-split` (worktree `sleepy-pasteur-21634a`, branch `claude/sleepy-pasteur-21634a`, PR #195):

- **Two refactor tasks, one PR.** (A) `categorized CSV duplicate cleanup` — 5 carry-over `family_office` dupes removed. (B) `G7 queries.py monolith split` — 5,455-line `scripts/queries.py` split into a `scripts/queries/` package with 8 domain modules. Pure refactor — no logic, signature, SQL, or return-value changes. `__init__.py` re-exports all 91 symbols so `from queries import X` keeps working unchanged.
- **HEAD at session start:** `a95c0f0` (rule9-43e, PR #194). No schema migrations, no DB writes, no staging promote.

## This session — Tasks A/B

| Task | Slug | Outcome |
|---|---|---|
| A | csv-dupe-cleanup | Removed 5 carry-over duplicate `family_office` rows from `data/reference/categorized_institutions_funds_v2.csv` (`Custos`, `Forthright`, `Fusion`, `QTR`, `RPg`). CSV row count 5,807 → 5,802; `family_office` distinct names 57 → 52. Verified via pandas (`5,801 data rows / 4 cols / 15 categories`) and `backfill_manager_types.py --dry-run` (CSV load is upstream and clean). The 52nd un-matched `managers` name flagged in rule9-43e left for next curator pass — out of scope for a pure dupe cleanup. |
| B | g7-queries-split | `scripts/queries.py` (5,455 L) split into `scripts/queries/` package — `common.py` (798 L), `register.py` (1,436 L), `fund.py` (455 L), `flows.py` (695 L), `market.py` (693 L), `cross.py` (452 L), `trend.py` (744 L), `entities.py` (551 L), `__init__.py` (re-exports all 91 names). Each domain module imports only what it actually uses (per-module audited; ruff F401 + pylint W0611 clean). Original `queries.py` deleted. **Verification:** `pytest tests/` 364 passed; `pytest tests/smoke/` 8 passed; `pre-commit run --all-files` PASS; all 91 expected symbols accessible via `import queries`; `_setup` correctly wires shared `common._get_db` / `_has_table` state; `api_*.py`, `admin_bp.py`, `serializers.py`, `oneoff/migrate_batch_3a.py` all `import` cleanly. |

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** `DERA-synthetic-series-resolution` (1,236 synthetic series_ids covering 2,172,757 rows / $2.55T NAV / 1.58% of `is_latest=TRUE` market value; multi-day resolution via `scripts/resolve_pending_series.py` tier extension; see `docs/findings/2026-04-28-dera-synthetic-series-discovery.md`).
- **P3 (4 items remaining):** `D10 Admin UI for entity_identifiers_staging` (UI), `Type-badge family_office color` (UI), `dry-run sweep follow-up` (~1 hr — `build_entities.py` + `resolve_adv_ownership.py` only), `maintenance-audit-design` (~2 hrs). **Non-UI quick wins remaining:** `dry-run sweep follow-up` (~1 hr) and `maintenance-audit-design` (~2 hrs). Both `categorized CSV dupe cleanup` and `G7 queries.py monolith split` closed in this PR.
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; this is the gate to drop their snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes (`scripts/pipeline/load_nport.py` `_cleanup_staging` hard-fail + `_enrich_staging_entities` pre-promote enrich). Re-measure synthetic-series count after this drop and decide whether to reactivate the cleanup item.

## Reminders

- **DERA synthetic-series promoted to P2 sprint slot.** Resolution scope: extend `scripts/resolve_pending_series.py:830-847` `deferred_synthetic` tier to recover series→entity via DERA registrant tables + N-CEN adviser map + fund_cik-as-entity inference, then backfill `entity_id` / `rollup_entity_id` on the affected `fund_holdings_v2` rows and re-emit `parent_fund_map`. Validator FLAG (`series_id_synthetic_fallback`) stays in place until closure. See `docs/findings/2026-04-28-dera-synthetic-series-discovery.md`.
- **`scripts/backfill_manager_types.py` CSV path now lives at `data/reference/`.** Same applies if the curation is ever re-extended — edit the CSV in place; the script reads via `Path(__file__).parent.parent / 'data' / 'reference' / 'categorized_institutions_funds_v2.csv'`.
- **`scripts/queries.py` is now a package: `scripts/queries/`.** 8 domain modules (`common`, `register`, `fund`, `flows`, `market`, `cross`, `trend`, `entities`) plus `__init__.py` that re-exports the full 91-symbol public surface. **All existing `from queries import X` imports continue to work unchanged** — touch the right domain file (not a single 5,500-line monolith) when adding/editing a query. Shared helpers (`get_db`, `has_table`, `_setup`, `get_cusip`, NPORT family-pattern + children fetchers, `_resolve_pct_of_so_denom`, `_quarter_to_date`, rollup helpers) live in `common.py`. Domain modules import only what they use from `.common` / `cache` / `config` / `serializers`; pylint/ruff are clean.
- **`data/*.lock` and `data/*.wal` now in `.gitignore`** — DuckDB WAL + per-pipeline runtime locks are no longer tracked. If they appear in `git status` after a session restart, ignore them (already gitignored as of this PR).
- **`fund_holdings_v2` is at 14,568,775 rows** post-INF51 dedup; 5,587,231 value-divergent rows across 55,924 groups remain as **INF53** P3 follow-up. **Plus 2,172,757 synthetic-series rows now formally FLAG/deferred** (this session) — same physical table, separate metadata defect.
- **Migration 023 (`parent_fund_map`)** is live; 109,723 rows. `holder_momentum` parent path now reads from it (5.6× speedup; PR #191). Quarterly rebuild via `python3 scripts/pipeline/compute_parent_fund_map.py` (~115s end-to-end) — trigger after the new-period 13F + N-PORT promotes.
- **`fund_holdings_v2_enrichment` not rebuilt this session** — last computed 2026-04-17. Separate cadence; next refresh is on a different trigger.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- **No `--reset` runs anywhere** without explicit user authorization.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172 still open** — dm13-de-discovery triage CSV; close after reconciling with PR #173 outcome.
