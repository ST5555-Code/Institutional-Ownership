# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`dera-synthetic-phase1-2` (this session, branch `claude/nice-vaughan-8da17c`,
not yet merged). Phase 1 (Tier 1, 1 reg / 72 rows) + Phase 2 (Tier 3, 55 regs
/ ~$1.98T NAV / 1,285,589 rows) of the DERA synthetic-series resolution are
done. Tier 4 (658 unmapped CIKs / $570.8B NAV) remains as the P2 sprint slot
under a renamed item.

## This session

| Phase | Slug | Outcome |
|---|---|---|
| Pre-flight | backup + baselines | Backup `data/backups/13f_backup_20260428_124210/` (3.2 GB EXPORT DATABASE PARQUET). Pre-state baselines: fund_holdings_v2 14,568,775 (all) / 14,568,704 (`is_latest`); 14,441 distinct series_id (`is_latest`); $161,598.7428058227B NAV (`is_latest`); fund_universe 12,971; synth `{cik}_{accession}` inventory 2,169,573 rows / 1,235 series / $2,543.4B NAV. App not running — no stop needed. |
| Phase 1 | dera-synthetic-phase1 | New `scripts/oneoff/dera_synthetic_stabilize.py` (`--phase 1\|2\|all`, default `--dry-run`, `--confirm` to write). Tier 1 case: synthetic `2060415_0002071691-26-007379` → real `S000093420` for First Eagle High Yield Municipal Completion Fund (CIK 0002060415); the real S-number already existed in the same fund's prior-quarter row (Q1'26 DERA bulk dropped SERIES_ID for the new filing, Q4'25 carried it). Pure key rename (72 rows), no row delta, no entity backfill (Tier 1 CIK has no `entity_identifier` row), 0 fund_universe rows touched. Commit `3043b34`. |
| Phase 2 | dera-synthetic-phase2 | Tier 3 stable-key migration: collapsed per-quarter `{cik}_{accession}` synth keys to `SYN_{cik_padded}` for 55 entity-mapped single-fund stand-alone registrants (ETFs, BDCs, interval funds, CEFs). Per CIK in one tx: rekeyed fund_holdings_v2 (1,285,589 rows total); deleted prior fund_universe rows by `fund_cik` (always 10-padded; -12 across 7 of 55); inserted one canonical SYN_* fund_universe row (+55 — 7 sourced from existing fund_universe attrs, 48 fall back to fund_holdings_v2 metadata since those CIKs had no fund_universe row); backfilled `entity_id` + EC `rollup_entity_id` + DM `dm_entity_id` + `dm_rollup_entity_id` + `dm_rollup_name` from `entity_identifiers` + `entity_rollup_history` (SCD open at `9999-12-31`) — 1,285,589 rows backfilled, 0 NULL `entity_id` remaining. Commit `7b84637`. |
| Recompute | downstream pipelines | `compute_parent_fund_map` (109,723 upserted, 95s); `compute_sector_flows` (321 upserted, 2s); `compute_flows` (19,224,688 investor_flows / 69,142 ticker_flow_stats, 20s); `build_summaries` (10,969 / 8,438 / 8,438 rows, 1.7s); `refresh_snapshot.sh` (7.7 GB / 378 tables). |
| Verify | post-state assertions | All 8 PASS: 0 residual `{cik}_{accession}` synth rows for entity-mapped CIKs; 55 distinct `SYN_*` keys; 0 `SYN_*` rows with NULL `entity_id`; 55 `SYN_*` fund_universe rows; Tier 1 final state real=140 (72+68) synth=0; fund_holdings_v2 totals **unchanged** at 14,568,775 / 14,568,704; NAV `is_latest` $161,598.7428058224B (delta vs pre 1.62e-13%, float aggregation); fund_universe 13,014 (delta +43); distinct series_id `is_latest` 14,389 (delta -52). `validate_entities --prod --read-only` 7 PASS / 1 FAIL (`wellington_sub_advisory` baseline) / 8 MANUAL — same as the `dm14c-voya` close. |

**Implementation refinements vs original plan:**

- fund_universe matches CIKs by `fund_cik` (always 10-padded) rather than
  `SPLIT_PART(series_id,'_',1)` — synth series_id prefixes are
  inconsistently padded (some `'1285650_…'`, some `'0002007649_…'`); a
  series_id-prefix match would miss rows.
- Falls back to fund_holdings_v2 `(fund_cik, fund_name, family_name)` when
  fund_universe has no row for the CIK (48 of 55 cases).
- Uses pre-DML `SELECT COUNT(*)` for rowcount tracking — DuckDB has no
  SQLite-style `SELECT changes()`.

**Ran from main checkout** (`/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership`)
with explicit `--prod-db` override. The `claude/nice-vaughan-8da17c`
worktree under `.claude/worktrees/` has no `data/` subdir, so all pipeline /
oneoff invocations need either main-checkout `cwd` + script path into the
worktree, or `--prod-db <abs>` override.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** `DERA-synthetic-series-resolution Tier 4` — 658 registrant CIKs / 1,134 synth series / ~886K rows / $570.8B NAV that don't yet exist in `entity_identifiers`. Bootstrap entity rows by `fund_cik` (re-use `scripts/bootstrap_residual_advisers.py` pattern), then apply the same `SYN_{cik_padded}` migration. Multi-day. Medium confidence — entity-naming dedup risk: some Tier 4 CIKs may already be entities under different identifiers (CRD, ADV file number). Scoping: `docs/findings/dera-synthetic-resolution-scoping.md` Tier 4 row.
- **P3 (2 items, both UI):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Type-badge family_office color` — `web/react-app/src/common/typeConfig.ts` needs a `family_office` case so the 36,950 reclassified `holdings_v2` rows render with a dedicated chip.
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; gate to drop snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes and of `compute_parent_fund_map.py` quarterly rebuild. **Re-measure Tier 1/3 residuals** after this drop — new filings can re-seed synth keys for the 56 already-resolved CIKs (Phase 1+2 are idempotent: re-run `--phase all --confirm` against the new period).

## Reminders

- **PR for this session is open but NOT merged.** Per session brief: "do not merge". Three commits on `claude/nice-vaughan-8da17c`: `3043b34` (Phase 1), `7b84637` (Phase 2), and the docs commit landing this file.
- **App is started from `data/13f_readonly.duckdb`** (refreshed in this session). If the user starts it with the standard incantation it will pick up the new SYN_* keys + entity backfill automatically.
- **`SYN_{cik_padded}` is the new stable per-fund synthetic key pattern.** Do not introduce another fallback — load_nport's `series_id_synthetic_fallback` should follow the same `SYN_{cik_padded}` shape if it ever has a CIK with no SERIES_ID at promote time. (`scripts/fetch_dera_nport.py:460` still mints `{raw_cik}_{accession}` per filing; that's the upstream bug. Fix is out of scope for this PR — track via the Tier 4 work.)
- **`make audit` baseline preserved post-Phase-2.** `validate_entities --prod` 7 PASS / 1 FAIL (`wellington_sub_advisory`) / 8 MANUAL.
- **Validator FLAG `series_id_synthetic_fallback` (`scripts/pipeline/load_nport.py:437`) stays in place** until Tier 4 closes — Phase 1+2 closed the entity-mapped subset, but new filings still mint `{raw_cik}_{accession}` keys for the unmapped 658 registrants.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** Same as previous sessions.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172 still open** — `dm13-de-discovery` triage CSV; close after reconciling with PR #173 outcome.
