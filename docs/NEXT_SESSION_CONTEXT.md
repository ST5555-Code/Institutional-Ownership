# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `p3-quick-wins` (worktree `stoic-nash-325d62`, branch `claude/stoic-nash-325d62`):

- **Two P3 items, one PR.** (A) `categorized-funds-csv-relocate` — actioned. (B) `DERA 1,187 NULL-series synthetics cleanup` — discovery + FLAG/defer with documented reactivation triggers.
- **HEAD at session start:** `8bfbeca` (dm14c-voya, PR #192). No new schema migrations, no DB writes, no staging promote — entity layer state unchanged from dm14c-voya close.

## This session — Tasks A/B

| Task | Slug | Outcome |
|---|---|---|
| A | categorized-funds-csv-relocate | `categorized_institutions_funds_v2.csv` (5,790 rows) `git mv`d to `data/reference/`. `scripts/backfill_manager_types.py:39` `CSV_PATH` updated. Verified via `--dry-run` (CSV loads, 13 categories, 0 rows projected to update — already-applied idempotent state). Repo-wide grep: no other live code references; archive/docs/findings narrative refs left intact (historical record); `docs/data_layers.md` already documents the target path. |
| B | dera-synthetic-series — FLAG | Discovery only, no DB writes. `fund_holdings_v2` has 0 rows with `series_id IS NULL`; the "1,187" figure refers to synthetic-fallback series_ids of form `{cik}_{accession}` minted at DERA load when `FUND_REPORTED_INFO.SERIES_ID` is missing. Current count: 2,172,757 rows / 1,236 distinct synthetic series / $2,553B AUM (1.58% of total `is_latest=TRUE` MV). Decision: defer — real holdings, no downstream regression (`parent_fund_map` already excludes 68% of synthetic series that have no entity rollup), proper resolution requires multi-day work on `resolve_pending_series.py` tiers. Findings doc `docs/findings/2026-04-28-dera-synthetic-series-discovery.md`. |

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** _empty_.
- **P3:** `D10 Admin UI for entity_identifiers_staging`, `INF53 BACKFILL_MIG015 multi-row investigation`, `43e family-office taxonomy`, `PROCESS_RULES Rule 9 dry-run uniformity`, `G7 queries.py monolith split`, `maintenance-audit-design`. (Two of the eight items activated by `roadmap-priority-moves` / `dm14c-voya` are now closed in this PR.)
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; this is the gate to drop their snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes (`scripts/pipeline/load_nport.py` `_cleanup_staging` hard-fail + `_enrich_staging_entities` pre-promote enrich). Re-measure synthetic-series count after this drop and decide whether to reactivate the cleanup item.

## Reminders

- **DERA synthetic-series stays FLAGGED.** Reactivate only when (a) `resolve_pending_series.py` tier work is being done for unrelated reasons, (b) Q1 2026 DERA bulk lands and percentage of synthetic NAV materially changes, or (c) a specific analytical workflow surfaces user-visible friction from a fund stuck behind a synthetic series_id. Validator FLAG already in place; aggregates already exclude.
- **`scripts/backfill_manager_types.py` CSV path now lives at `data/reference/`.** Same applies if the curation is ever re-extended — edit the CSV in place; the script reads via `Path(__file__).parent.parent / 'data' / 'reference' / 'categorized_institutions_funds_v2.csv'`.
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
