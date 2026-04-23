# Pipeline Violations — Per-Script PROCESS_RULES Detail

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_
_Revised 2026-04-15: four entries CLEARED by v2 rewrites landing this
week (fetch_nport.py → v2 + DERA; fetch_13dg.py → v2; fetch_market.py
→ v2; build_cusip.py → v2). Blocks retained below for historical
reference + retirement audit._

One block per script marked REWRITE or RETROFIT in
`docs/pipeline_inventory.md`. Every violation carries a file:line so
the rewrite can clear its list without copy-pasting the same bug into
the new framework implementation.

PROCESS_RULES reference (`docs/PROCESS_RULES.md`):
§1 incremental save · §2 restart-safe · §3 multi-source failover
§4 rate limiting · §5 error handling · §5b QC validation
§6 progress reporting · §7 derived table rebuild · §8 parser sync
§9 dry-run by default

---

## CLEARED by 2026-04-14 parallel session (commit 831e5b4)

`§6` progress-reporting + `data_freshness` stamping across 8 non-v2
scripts: `fetch_adv`, `fetch_ncen`, `fetch_finra_short`, `fetch_13dg`
(phase 3), `build_entities`, `build_managers`, `build_fund_classes`,
`build_cusip`. All now call `record_freshness(con, target_table)` at
end-of-run. v2 SourcePipelines manage freshness through their promote
paths; `fetch_13f.py` is filesystem-only. `scripts/check_freshness.py`
+ `make freshness` gate advancement on missing / stale rows. Per-script
§6 violations listed below are marked `STAMPED` where applicable.

---

## CLEARED this session (2026-04-15)

- **`fetch_nport.py` (REWRITE) — CLEARED.** All 10 PROCESS_RULES
  violations resolved in `fetch_nport_v2.py` + `fetch_dera_nport.py`
  (commits 5cf3585, 44bc98e, e868772, 39d5e95). Per-accession CHECKPOINT
  every 2000 rows (§1); restart-safe via `ingestion_impacts.load_status`
  (§2); DERA bulk replaces per-XML fetch, with XML kept only for
  `--monthly-topup` (§3); `sec_fetch()` with 5xx exponential backoff +
  429 60s pause (§4); entity-gate check + synthetic-series FLAG (§5);
  parameter-bound SQL only, no f-string interpolation (§9); `--test`
  and `--staging` gates enforced. Amendment handling: latest accession
  wins, now cross-ZIP (commit 39d5e95).
- **`fetch_13dg.py` (REWRITE) — CLEARED.** Fully replaced by
  `fetch_13dg_v2.py` + `validate_13dg.py` + `promote_13dg.py` (commit
  4880467). Writes `beneficial_ownership_v2` directly; `pct_owned`
  0–100 gate + `shares_owned` 1–99 rejection shipped in the v2
  `_extract_fields()`; `--dry-run` / `--apply` gates live.
- **`fetch_market.py` (REWRITE) — CLEARED.** Rewrites in commits
  aa7603a (Batch 2B-market) + b95cb31 (Batch 2A) clear all violations.
  No more `UPDATE holdings SET market_value_live/pct_of_float` — that
  lives in Batch 3 `enrich_holdings.py` now unblocked. CUSIP-anchored
  universe via `securities.canonical_type` (CUSIP v1.4).
- **`build_cusip.py` (REWRITE) — CLEARED.** Rewritten UPSERT-only
  (commits 7081886 + c5eada8); legacy version archived at
  `scripts/retired/build_cusip_legacy.py`. OpenFIGI v3 batched (10 per
  request, 25 req/min); `_cache_openfigi` persistent; no `holdings`
  UPDATE.

---

## fetch_nport.py (REWRITE) — SUPERSEDED by `fetch_nport_v2.py`; retained for parser helpers only

- §1 (incremental save): no `CHECKPOINT` anywhere in the main loop
  `fetch_nport.py:642-679`. Per-filing inserts accumulate WAL
  without flush. Kill mid-run → un-flushed rows lost.
- §2 (restart-safe): `is_already_loaded()` at
  `fetch_nport.py:414,:420,:427` uses `COUNT(*) > 0` on
  `series_id + report_month`. Partial loads on the same month
  re-enter and double-insert because there is no uniqueness
  constraint on `fund_holdings`.
- §3 (multi-source failover): single path —
  `data.sec.gov/Archives/…/primary_doc.xml` at `:193`. The index-page
  fallback at `:204-220` is triggered only on 404, not on consecutive
  timeouts. No EFTS fallback; no consecutive-failure counter.
- §4 (rate limiting): `SEC_DELAY = 0.2` at `fetch_nport.py:38`. Uses
  `time.sleep` not `time.monotonic()`. No 429 handling in
  `download_xml()` at `:194-220`.
- §5 (error handling): `log_error()` writes to CSV (`:472-482`) and
  silently `pass`es bad rows. No final unresolved-% gate at run end.
- §5b (QC): `val_usd` and `balance` cast to float with no range gate
  (`fetch_nport.py:457-458`). No cross-validation against reported
  NAV.
- §6 (progress): `:676` progress line uses default `print`, not
  `flush=True` — only works under `python3 -u`.
- §9 (dry-run): no `--dry-run` or `--apply`. `--test` at `:817` limits
  to 5 funds but still writes to prod DB.

---

## fetch_13dg.py (REWRITE) — SUPERSEDED by `fetch_13dg_v2.py`; retained for parser helpers only

- §1 (incremental save): OK — `FLUSH_SIZE = 200` at
  `fetch_13dg.py:676`, `batch_insert + CHECKPOINT` at `:718-730`.
- §2 (restart-safe): OK — `fetched_tickers_13dg` checkpoint at `:561`,
  `get_existing()` dedupes by accession at `:245`, `WHERE accession_number
  NOT IN (...)` at `:647`.
- §3 (multi-source failover): partial — edgar library primary, curl
  fallback for filing body at `:449-470` (`_download_filing_text`).
  No consecutive-failure counter to switch primaries; no EFTS.
- §4 (rate limiting): hardcoded `time.sleep(0.1)` at
  `fetch_13dg.py:369,:847` and `time.sleep(0.2)` at `:458`. No
  monotonic timer, no 429 back-off (generic retry at `:59-69`).
- §5b (QC): **VIOLATION** — `_extract_fields()` parses `pct_owned` and
  `shares_owned` without the 0-100 range gate and 1-99 shares-rejection
  described in PROCESS_RULES §5b. Known-good parser discipline
  documented in the memory system under "§5b QC gates" is not
  implemented here.
- §9 (dry-run): **VIOLATION** — no `--dry-run`/`--apply`. `--test` at
  `:887` seeds a test DB but full run writes prod by default.
- Legacy refs: `fetch_13dg.py:230` CREATE `beneficial_ownership`
  (dropped); `:245,:259,:276,:306,:312,:320,:327,:527,:528,:536,:647,:735,:768`
  read/write the dropped table; `:332-333` read dropped `holdings`;
  `:872-873` `_seed_test_db` copies dropped `holdings`, `fund_holdings`
  from prod.

---

## fetch_adv.py (REWRITE) — SUPERSEDED by `scripts/pipeline/load_adv.py` (Wave 2 w2-05, 2026-04-22). Retained for historical reference only.

- §1 (incremental save): **VIOLATION** — whole CSV loaded into pandas
  at `fetch_adv.py:110`, processed in memory, `DROP TABLE; CREATE TABLE
  AS SELECT * FROM df_out` at `:248-249`. No row-level save; no
  CHECKPOINT. A mid-run kill leaves prod `adv_managers` empty.
- §2 (restart-safe): partial — DROP+CTAS is idempotent for completed
  runs; no progress persistence if the pandas step fails.
- §5 (error handling): silent — `fetch_adv.py:134-141` prints
  `WARNING: Missing columns` but continues. No final unresolved-% gate.
- §9 (dry-run): **VIOLATION** — no `--dry-run`/`--apply`. Running the
  script rewrites prod `adv_managers` immediately.

---

## fetch_market.py (REWRITE) — CLEARED 2026-04-13 (Batch 2A/2B)

- §1 (incremental save): **VIOLATION** — Yahoo and SEC upserts flush
  only at `fetch_market.py:527` (single end-of-run CHECKPOINT). 500-
  ticker progress at `:322` is print-only, not committed.
- §3 (multi-source failover): partial — Yahoo + SEC are
  complementary, not failover. No consecutive-failure counter. If
  Yahoo 429s, the script keeps retrying without backoff.
- §4 (rate limiting): `META_SLEEP_SEC = 0.05` at `:61`. No 429 handling
  per-call in YahooClient.
- §5 (error handling): silent — `fetch_yahoo` at `:232-233` logs and
  continues. No final unresolved-% gate.
- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--limit N` at `:559`
  exists for scale-testing but still writes to prod.
- Legacy refs: `fetch_market.py:150` `FROM holdings`; `:422-433`
  `UPDATE holdings SET market_value_live`, `SET pct_of_float`;
  `:434-438` COUNTs on `holdings`. All against a dropped table.

---

## fetch_finra_short.py (RETROFIT)

- §9 (dry-run): minor — `--test` at `:257` limits to 5 days but still
  writes. No `--dry-run` observation-only mode.
- Otherwise clean: CHECKPOINT per 50k chunk at `:160`/`:219-221`,
  restart-safe via `loaded_dates` check at `:171`/`:193`, 429 backoff
  at `:77-79`, 3× retry at `:83`, tqdm progress at `:203`.

---

## fetch_ncen.py (RETROFIT) — SUPERSEDED by `scripts/pipeline/load_ncen.py` (Wave 2 w2-04, 2026-04-22). Retained for historical reference only.

- §6 (progress): 50-filing progress at `fetch_ncen.py:435` lacks
  explicit `flush=True` — relies on `python3 -u` at call sites.
- §9 (dry-run): **VIOLATION** — `--test` at `:` exists but writes; no
  `--dry-run`/`--apply`.
- Otherwise clean: CHECKPOINT every 25 filings at `:474` + final `:476`,
  restart-safe via `get_processed_ciks` + WHERE filter at `:422,:426`,
  429 retry at `:78`, `SEC_DELAY = 0.5` at `:60`.

---

## load_13f.py (REWRITE) — CLEARED 2026-04-19 (Rewrite4, 7e68cf9 / prod apply a58c107)

**CLEARED 2026-04-19** — Full rewrite landed at commit `7e68cf9`, Phase 4
prod apply at `a58c107`. Rewrite4 Findings at
`docs/REWRITE_LOAD_13F_FINDINGS.md`:

- Dead `holdings` DROP+CTAS at `:222-284` retired — script no longer
  writes the legacy table. `holdings_v2` is the canonical fact table
  and is produced by the downstream enrichment chain.
- `--dry-run` and `--staging` plumbed through `main()` end-to-end;
  no more hardcoded prod writes.
- `OTHERMANAGER2` loader added (Phase 0 addendum, commit `0a7ae35`):
  materialized 15,405 `other_managers` rows from ghost data that the
  legacy script silently dropped on the floor. Fix shipped in the
  same rewrite at commit `14a5152`.
- `--quarter` gate retained; CHECKPOINT per filing batch, error-log
  on missing `filings_txt` / `filings_xml` halts the quarter rather
  than silently loading a 0-row partition.
- `data_freshness` hook live on both `filings` and `filings_deduped`.

Original violations retained below for historical reference.

- §1 (incremental save): **VIOLATION** — full `DROP+CREATE` on
  `filings` at `load_13f.py:182`, `filings_deduped` at `:200`,
  `holdings` at `:222`. No per-quarter persistence if the build step
  fails mid-run.
- §5 (error handling): `load_13f.py:37` prints `WARNING: Missing {p}`
  and returns `(0, 0)` without aborting. Loss of data for that quarter
  is silent.
- §9 (dry-run): **VIOLATION** — no `--dry-run`/`--apply`. `--quarter`
  at `:` limits scope but still writes.
- Legacy refs: `load_13f.py:222-284` CREATE `holdings` (dropped);
  `:286,:294,:304-305` reads.

---

## refetch_missing_sectors.py (RETROFIT)

- §1 (incremental save): **VIOLATION** — no CHECKPOINT anywhere.
- §4 (rate limiting): no sleep between Yahoo calls in the loop at
  `refetch_missing_sectors.py:50`.
- §9 (dry-run): **VIOLATION** — no flag, hardcoded
  `/tmp/refetch_tickers.txt` input path. Writes to staging only, which
  is the safety rail.

---

## build_cusip.py (REWRITE) — CLEARED 2026-04-14 (CUSIP v1.4)

- §1 (incremental save): **VIOLATION** — cache writes per-batch
  (`save_figi_cache` at `build_cusip.py:87`) but the `securities`
  rebuild is `DROP+CREATE` all-at-end at `:318-319`. No CHECKPOINT
  anywhere.
- §5 (error handling): silent on OpenFIGI per-batch failures at
  `build_cusip.py:145`.
- §9 (dry-run): **VIOLATION** — no `--dry-run`/`--apply`. `--staging`
  at `:389` exists but still writes.
- Legacy refs: `build_cusip.py:31,:123,:248,:336-338` reads
  `holdings`; `:322-332` ALTER `holdings` + UPDATE.

---

## build_managers.py (REWRITE) — CLEARED 2026-04-19 (Rewrite5, 223b4d9 / prod apply 7747af2)

**CLEARED 2026-04-19** — Full rewrite + `backfill_manager_types.py`
repoint landed at merge commit `223b4d9`, Phase 4 prod apply at
`7747af2`. Rewrite5 Findings at
`docs/REWRITE_BUILD_MANAGERS_FINDINGS.md`:

- `holdings` ALTER+UPDATE at `:513-532` retired — manager enrichment
  now writes `holdings_v2` (repoint commit `1719320`) and
  `backfill_manager_types.py` retargeted to `holdings_v2` (commit
  `7b8a2b7`).
- COALESCE preservation applied across all four enrichment columns
  (`manager_type`, `inst_parent_name`, `is_passive`, `is_activist`) so
  legacy 14-category taxonomy survives the repoint even though
  `managers.strategy_type` from `fetch_adv.py` covers only ~60% of
  CIKs (structural ADV filing gap — ~$25T+ AUM of non-ADV filers).
- Pre-rewrite audit artifact: `holdings_v2_manager_type_legacy_snapshot_20260419`
  created at commit `c2c2bac` (12,270,984 rows, 9,121 CIKs, 13 types) —
  full point-in-time reference for rollback or diff validation.
- Entity staging workflow (INF1) respected — `parent_bridge` and
  `cik_crd_direct` promote as `pk_diff`; `managers` and
  `cik_crd_links` promote as `rebuild` via the new `PROMOTE_KIND`
  machinery in `promote_staging.py` (commit `6079220`).
- `--dry-run` and `--staging` plumbed; try/except/pass at
  `:515-521` replaced with explicit error handling.
- `data_freshness` hook live on all rebuilt tables.

Residual: 14,368 rows / 9 entities have `manager_type` NULL after
backfill (not in `categorized_institutions_funds_v2.csv`, not
ADV-covered) — logged as ongoing curation, not a regression.

Original violations retained below for historical reference.

- §1 (incremental save): **VIOLATION** — every target table is
  DROP+CREATE AS SELECT. No CHECKPOINT.
- §5 (error handling): silent — `build_managers.py:515-521` uses
  `try/except pass` (nosec'd) that hides schema failures.
- §9 (dry-run): **VIOLATION** — `DB_PATH` hardcoded to prod at
  `build_managers.py:22`. `main()` at `:584` does `duckdb.connect(DB_PATH)`
  with no `--staging` plumbing.
- Legacy refs: `build_managers.py:513-532` ALTER + UPDATE on
  `holdings`; `:534` COUNT on `holdings`.
- Additional: bypasses entity staging workflow (INF1) — writes
  `parent_bridge` / `managers` directly to prod.

---

## build_summaries.py (REWRITE) — CLEARED 2026-04-19 (Batch 3 close, 87ee955)

**CLEARED 2026-04-19** — Work landed at commit `87ee955` on
2026-04-16 ("feat: Batch 3 close — compute_flows + build_summaries
rewrites + migration 004"), an ancestor of HEAD `d7ba1c2`. Phase 0
audit (`docs/REWRITE_BUILD_SUMMARIES_FINDINGS.md`) confirmed:

- Legacy `holdings` reads retired — script now reads `holdings_v2`
  and `fund_holdings_v2` throughout (0 refs to legacy `holdings`).
- `--dry-run` flag live at `build_summaries.py:374` alongside
  existing `--staging` / `--rebuild`.
- Per-(quarter × worldview) `CHECKPOINT` at `:333` and `:344`.
- `db.record_freshness` hook at `:355–356` for both output tables.
- Line-buffered logging with explicit `sys.stdout.flush()` (`:94`),
  equivalent to `flush=True` per write.
- Error propagation via `try/finally` at `:411–420`; no silent
  `except` clauses anywhere in the file.
- DDL drift: **absent**. `CREATE TABLE IF NOT EXISTS` at `:110–145`
  matches prod column-for-column for both tables; PK on
  `summary_by_parent` is `(quarter, rollup_type, rollup_entity_id)`
  per migration 004 shipped in the same commit. `docs/data_layers.md`
  Appendix A entries already mark both tables ALIGNED (formerly
  `canonical_ddl.md` §4 and §5).
- Downstream readers surveyed: 14 files, 90 hits, no breakage.

No Phase 1–4 rewrite work required. Original violations retained
below for historical reference.

- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--staging` at `:130`
  and `--rebuild` at `:129` exist.
- Legacy refs: `build_summaries.py:73` `FROM holdings h`; `:118`
  `FROM holdings h`. DDL drift documented in `docs/data_layers.md` Appendix A
  (prod has `rollup_entity_id`, `rollup_name`, `total_nport_aum`,
  `nport_coverage_pct`; script has none of these and wrong PK).

---

## build_fund_classes.py (REWRITE) — CLEARED 2026-04-23 (retrofit bar)

**CLEARED 2026-04-23** — Retrofit landed on branch
`build-fund-classes-rewrite` alongside the Batch 3 bar
(`compute_flows` / `build_summaries` / `build_shares_history`).
Legacy-ref + `DB_PATH` + `--staging` items had already been cleared
in earlier sessions (sec-05 PR #45 for `--staging` / `seed_staging` /
`--enrichment-only`; BLOCK-3 `0dc0d5d` repointed `fund_holdings` →
`fund_holdings_v2`); this PR closes the remaining §1 / §5 / §9 gaps:

- §1 (incremental save): **CLEARED** — CHECKPOINT cadence tightened
  to every 2,000 XMLs (prev. 5,000) via `CHECKPOINT_EVERY` constant,
  final flush preserved before enrichment + before close. Matches
  the `fetch_nport_v2.py` per-2,000-rows bar.
- §5 (error handling): **CLEARED** — three silent `pass` blocks
  replaced:
  (a) `parse_xml_for_classes()` catches only `etree.XMLSyntaxError` /
      `OSError` and prints a `[parse_error]` line with the filename +
      exception; a per-run counter is surfaced in the SUMMARY and
      drives a `>1%` WARN gate.
  (b) `_get_existing_classes()` catches only
      `duckdb.CatalogException` (table-missing first-run case); any
      other DuckDB error propagates.
  (c) `enrich_fund_holdings_v2()` no longer speculatively ALTERs
      inside a try/except — probes `information_schema.columns`
      first; idempotent by detection, not by swallowing errors.
  (d) LEI `INSERT OR REPLACE` wraps only `duckdb.Error` and
      increments a `lei_errors` counter reported in SUMMARY.
- §9 (dry-run): **CLEARED** — `--dry-run` flag added; opens a
  read-only DuckDB connection, parses the full XML cache, counts
  candidate inserts against an in-memory `existing` set, and
  projects the enrichment UPDATE via COUNT-join. Zero DB mutations
  in dry-run. Skips `record_freshness` and all CHECKPOINT calls.
- Legacy refs: **CLEARED prior session** (BLOCK-3 `0dc0d5d`) — script
  targets `fund_holdings_v2` only; `rg "fund_holdings(?!_v2)"` on
  `scripts/build_fund_classes.py` returns 0 matches.

Test: `python3 scripts/build_fund_classes.py --dry-run` against prod
— 53,131 XMLs scanned, 1 parse error surfaced (previously silent),
31,067 candidate classes + 13,154 candidate LEIs projected,
11,855,837-row enrichment projection, zero writes. `pytest tests/`
282/282 PASS, `pytest tests/smoke/` 8/8 PASS.

---

## build_entities.py (RETROFIT) — CLEARED 2026-04-21 (mig-13-p1)

- §1 (incremental save): **CLEARED** — `CHECKPOINT` now fires in
  `main()` after every build step (`step2_seed_parents`,
  `step2_create_manager_entities`, `step2_create_fund_entities`,
  `step3_populate_identifiers`, `step4_populate_relationships`,
  `step5_populate_aliases`, `step6_populate_classifications`,
  `step7_compute_rollups`, plus `replay_persistent_overrides`). Mid-run
  kill no longer loses a completed step.
- §9 (dry-run): partial — staging-only via `db.set_staging_mode(True)`
  at `build_entities.py:971`. No explicit `--dry-run` but the
  staging-only gate is the safety rail. Promotion to prod always
  goes through `promote_staging.py` which IS gated.
- Otherwise clean: per-step try/except to CONFLICT_LOG,
  idempotent `--reset`.

---

## build_benchmark_weights.py (REWRITE)

- **BROKEN IMPORT** — `build_benchmark_weights.py:16`
  `from db import get_connection` — `get_connection` did not exist in
  `db.py`. Fixed this session (D11) by adding a local `get_connection()`
  that wraps `duckdb.connect(get_db_path())`.
- §1 (incremental save): **VIOLATION** — no CHECKPOINT anywhere.
- §5 (error handling): minimal — prints "no benchmark fund data" and
  returns.
- §9 (dry-run): **VIOLATION** — no flag.
- Legacy refs: `build_benchmark_weights.py:79,:90` `FROM fund_holdings`
  (dropped).

---

## build_shares_history.py (REWRITE) — CLEARED 2026-04-19 (Rewrite1, d7ba1c2 / prod apply 443e37a)

**CLEARED 2026-04-19** — Full rewrite + PROCESS_RULES retrofits landed
at commit `d7ba1c2`, Phase 4 prod apply at `443e37a`. Rewrite1 Findings
at `docs/REWRITE_BUILD_SHARES_HISTORY_FINDINGS.md`:

- Legacy `holdings` reads at `:161-164,:201-203` and
  `holdings.pct_of_float` UPDATEs at `:177-184,:190-199` retired —
  script no longer touches the dropped table. `--update-holdings`
  gate removed.
- `--dry-run` flag live alongside `--staging`; dry-run opens a
  read-only connection and projects per-slice counts without writes.
- Per-batch CHECKPOINT retrofit: every `_upsert_batch` call flushes
  WAL, not just the two end-of-phase CHECKPOINTs.
- `db.record_freshness` hook stamps `shares_history` at end-of-run.
- Silent-continue on empty history replaced with explicit log +
  propagated exit status.

Deferred: period-accurate denominator via ASOF JOIN in
`enrich_holdings.py` Pass B — **CLOSED 2026-04-19** as the pct-of-so
workstream. Ships as `pct_of_so` (renamed from `pct_of_float` in
migration 008, `ea4ae99` amended) with three-tier SOH-ASOF fallback
(`soh_period_accurate` → `market_data_so_latest` → `market_data_float_latest`)
and `pct_of_so_source` audit column. Commit citations: Phase 1b read-site
migration + Phase 1c audit-column split + Phase 4b amended migration +
Phase 4c rename sweep; merge `8925347` + follow-on `12e172b`. See
`docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md`. Original
BLOCK-PCT-OF-FLOAT-PERIOD-ACCURACY row also closed in ROADMAP Open Items.
True float-adjusted denominator (public-float-based, distinct from
shares-outstanding) tracked separately as **INF38 / BLOCK-FLOAT-HISTORY**.

Original violations retained below for historical reference.

- §1 (incremental save): weak — `BATCH=1000` at
  `build_shares_history.py:74`, `_upsert_batch` commits, but only two
  CHECKPOINTs total (`:117`, `:206`). No per-batch CHECKPOINT.
- §5 (error handling): silent — empty `history` → continue.
- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--staging` at `:211`
  and `--update-holdings` gate at `:212` (writes the dropped
  `holdings` table when enabled).
- Legacy refs: `build_shares_history.py:161-164,:201-203` reads
  `holdings`; `:177-184,:190-199` UPDATE `holdings.pct_of_float`.

---

## compute_flows.py (REWRITE) — CLEARED 2026-04-19 (Batch 3 close, 87ee955)

**CLEARED 2026-04-19** — Work landed at commit `87ee955` on
2026-04-16 ("feat: Batch 3 close — compute_flows + build_summaries
rewrites + migration 004"), an ancestor of HEAD `bc43d25`. Precheck
audit (main=`bc43d25`) confirmed:

- Legacy `holdings` reads retired — script now reads `holdings_v2`
  at `compute_flows.py:166,:178` (write path) and `:261,:268`
  (dry-run projection). Docstring/help at `:388` also references
  `holdings_v2`. `rg "FROM holdings\b" scripts/compute_flows.py`
  returns 0 matches.
- `--dry-run` flag live at `compute_flows.py:392` alongside existing
  `--staging`; dry-run opens a read-only connection at `:402` and
  projects per-slice row counts via `_project_period_flows()` with
  no writes.
- Per-(period × worldview) `CHECKPOINT` at `:435`, per-worldview
  momentum `CHECKPOINT` at `:445`, per-worldview ticker-stats
  `CHECKPOINT` at `:453`.
- `db.record_freshness` hook at `:460–461` for both output tables
  (`investor_flows`, `ticker_flow_stats`).
- Line-buffered logging: `_Tee.line` at `:73–78` calls
  `sys.stdout.flush()` after every write; log file opened with
  `buffering=1` (line-buffered) at `:66`. Equivalent to `flush=True`
  per write — no retrofit needed.
- Error propagation via `try/finally` at `:487–496`; no silent
  `except` clauses anywhere in the file.

No Phase 1–4 rewrite work required. Original violations retained
below for historical reference.

- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--staging` at `:256`
  exists.
- Legacy refs: `compute_flows.py:69,:78` `FROM holdings WHERE
  quarter = '{q_from/to}'`. Uses dropped `holdings` for flow math.
- Otherwise close to OK: DROP+CREATE idempotent (`:25-36,:37-45`),
  per-period INSERT with end-CHECKPOINT at `:229`, flushed prints at
  `:50,:131,:136,:176,:207`.

---

## merge_staging.py (RETROFIT) — CLEARED 2026-04-21 (mig-13-p1)

- §5 (error handling): **CLEARED** — per-table errors are now collected
  into an `errors` list; on live runs the script exits non-zero with a
  failure summary. Dry-run keeps errors as warnings to preserve the
  inspection contract. `--drop-staging` is suppressed when any table
  failed so the staging DB is retained for investigation.
- Legacy refs: **CLEARED** — hand-maintained `TABLE_KEYS` dict replaced
  by `TABLE_KEYS = merge_table_keys()` import from
  `scripts/pipeline/registry.py:355`. Stale `beneficial_ownership` and
  `fund_holdings` entries are gone because neither is in the registry
  (only `beneficial_ownership_v2` and `fund_holdings_v2` are). Only two
  explicit overrides remain (`_cache_openfigi`, `_cache_yfinance`) —
  infrastructure caches that live outside the dataset registry.
- Otherwise clean: `--dry-run`, `--all --i-really-mean-all` gate, and
  end-of-merge `CHECKPOINT` retained.

---

## resolve_long_tail.py (RETROFIT)

- §1 (incremental save): **VIOLATION** — no CHECKPOINT inside the
  resolution loop at `resolve_long_tail.py:147-229`. Progress CSV
  written at end at `:234-239`.
- Otherwise clean: restart-safe via `get_already_resolved()` at `:78`,
  `SEC_RATE_LIMIT = 0.2` at `:53`, `--dry-run` at `:102`, staging-only
  via `--staging required=True` at `:99`.

---

## resolve_adv_ownership.py (RETROFIT)

- §1 (incremental save): file-level checkpoint at
  `data/cache/adv_parsed.txt` (append-only) — DB writes in `run_match`
  at `resolve_adv_ownership.py:664` lack an explicit DB CHECKPOINT.
- Otherwise clean: pymupdf primary → pdfplumber fallback at
  `:954-984`, `RATE_LIMIT = 0.2` at `:53`, staging-only gate at
  `:1024`, `--qc` report path compliant with §5b intent.

---

## fix_fund_classification.py (RETROFIT)

- §1 (incremental save): **VIOLATION** — `executemany` on all rows at
  once at `fix_fund_classification.py:87`, no CHECKPOINT.
- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--production` at
  `:132` is the destructive gate (default = staging).
- Otherwise acceptable as a one-shot fix: rewrites every row
  idempotently from fund_name keywords; spot-check prints known funds
  at `:104-124` (weak §5b).

---

## sec-06 (2026-04-21) — 5 direct-to-prod writers inventoried

Phase 0 findings in [docs/findings/sec-06-p0-findings.md](docs/findings/sec-06-p0-findings.md). Three of the five scripts wrote to the `beneficial_ownership` legacy table (dropped Stage 5) — **retired**, not retrofitted. Two scripts target live tables — **hardened** (--dry-run + CHECKPOINT, dead legacy writes removed).

---

## resolve_agent_names.py (RETIRED)

- **Status:** RETIRED — moved to `scripts/retired/resolve_agent_names.py` (sec-06, 2026-04-21).
- **Reason:** All write operations target `beneficial_ownership` (legacy table dropped Stage 5). Every UPDATE / DROP / CREATE TABLE / CHECKPOINT in the script fires against a table that does not exist in prod — READ-ONLY `information_schema.tables` probe 2026-04-21 confirmed only `beneficial_ownership_current` and `beneficial_ownership_v2` exist.
- **Tables targeted (all dropped):** `beneficial_ownership`, `beneficial_ownership_current` (the script's `DROP TABLE IF EXISTS` + `CREATE TABLE AS SELECT` rebuild references the dropped source).
- **Historical reads/writes:** UPDATE `beneficial_ownership` SET `filer_name`, `name_resolved` at `:200-205`; DROP + CREATE `beneficial_ownership_current` at `:212-244`; CHECKPOINT at `:263`.
- **Future:** If "extract reporting person from filing text" functionality is needed against `beneficial_ownership_v2`, rebuild from scratch against the v2 schema + `entity_id` resolution path.

---

## resolve_bo_agents.py (RETIRED)

- **Status:** RETIRED — moved to `scripts/retired/resolve_bo_agents.py` (sec-06, 2026-04-21).
- **Reason:** All write operations target `beneficial_ownership` (legacy table dropped Stage 5). Script was the best-behaved of the five by PROCESS_RULES (§1 CHECKPOINT every 500 rows, §2 WHERE-clause restart-safety, §3 EFTS + .hdr.sgml failover, §4 monotonic rate limit, §9 `--apply` dry-run), but every fire path hits a dropped table.
- **Tables targeted (all dropped):** `beneficial_ownership`, `beneficial_ownership_current`.
- **Historical reads/writes:** UPDATE `beneficial_ownership` SET `filer_name`, `filer_cik`, `name_resolved` at `:296-300`; DROP + CREATE `beneficial_ownership_current` at `:361-362`; CHECKPOINT at `:306, :323, :380`.
- **Future:** If agent-name resolution is needed against `beneficial_ownership_v2`, rebuild from scratch — the dual-source EFTS/.hdr.sgml pattern is worth preserving.

---

## resolve_names.py (RETIRED)

- **Status:** RETIRED — moved to `scripts/retired/resolve_names.py` (sec-06, 2026-04-21).
- **Reason:** All write operations target `beneficial_ownership` (legacy table dropped Stage 5). Script also ran `ALTER TABLE beneficial_ownership ADD COLUMN name_resolved` at `:161` — dead code; the `name_resolved` column already exists on `beneficial_ownership_v2` (READ-ONLY probe 2026-04-21). Pass 1 also reads dropped `holdings` at `:50-56`.
- **Tables targeted (all dropped):** `beneficial_ownership`, `beneficial_ownership_current`, `holdings`.
- **Historical reads/writes:** six UPDATEs on `beneficial_ownership` at `:144-149, :165-171, :176-181, :289-295`; ALTER + ADD COLUMN at `:161`; DROP + CREATE `beneficial_ownership_current` at `:189-217`; CHECKPOINT at `:325`.
- **Future:** If three-pass filer-name resolution is needed against `beneficial_ownership_v2`, rebuild from scratch — Pass 2 (EDGAR submissions API) and Pass 2b (company_tickers.json) logic is worth preserving against the v2 schema.

---

## backfill_manager_types.py (RETROFIT)

- **Status:** HARDENED — `--dry-run` verified + CHECKPOINT verified + entry added (sec-06, 2026-04-21).
- **Classification:** EXCEPTION — targeted enrichment updater keyed on CSV-curated category mappings, acceptable as direct-to-prod.
- **Tables written:** `holdings_v2` (UPDATE `manager_type` where NULL or `'unknown'`), `managers` (UPDATE `strategy_type`).
- **Hardening already in file:** `--dry-run` at `:194-195` previews projected row counts across `holdings_v2` and `managers` without executing any prod UPDATE (temp table `_manager_categories` is session-scoped); CHECKPOINT at `:185` after writes; `record_freshness("holdings_v2")` at `:182`.
- **Deviations from codebase pattern (tracked, not blocking EXCEPTION):** uses hardcoded prod/staging paths at `:199-204` instead of `db.get_db_path()` / `db.set_staging_mode()`; `--production` polarity (default staging) instead of `--staging`; no `crash_handler` wrap; `try/except/pass` on `managers` UPDATE at `:124, :133-134`. Not a regression — script is safe by default and the CSV mapping is hand-curated.

---

## enrich_tickers.py (RETROFIT)

- **Status:** HARDENED — dead `holdings` (legacy) writes removed, `--dry-run` + CHECKPOINT added (sec-06, 2026-04-21).
- **Classification:** EXCEPTION — CUSIP→ticker enrichment updater, acceptable as direct-to-prod now that dead-table writes are gone.
- **Tables written (live):** `securities` (UPDATE `ticker` WHERE `cusip = ?` AND `ticker IS NULL`), `market_data` (INSERT 13 columns, append-only, de-duped via `existing` set).
- **Dead writes removed (sec-06, 2026-04-21):** UPDATE `holdings` SET `ticker` (propagate from securities); UPDATE `holdings` SET `market_value_live`; UPDATE `holdings` SET `pct_of_float`; SELECT COUNT on `holdings`. `holdings` was dropped Stage 5; `holdings_v2` enrichment lives in `enrich_holdings.py` (Batch 3).
- **Hardening added:** `--dry-run` projects new-ticker-match count + market_data delta without writing; CHECKPOINT after write operations complete.
- **Reads that remain:** `securities` (for CUSIPs without ticker), `market_data` (for de-dupe). Both are live.

---

## Cross-cutting violation patterns

The violation list above clusters into five systemic patterns that the
framework rewrites must solve once, not per-script:

1. **§1 CHECKPOINT discipline.** The framework
   `SourcePipeline.load_to_staging()` contract must CHECKPOINT per-object
   after every manifest/impact write — not batch at end.

2. **§9 dry-run gate.** Every `SourcePipeline.promote()` starts from
   `manifest.validation_tier` — no dry-run flag needed at the script
   level because the control plane manages the gate.

3. **§3 multi-source failover.** `scripts/pipeline/shared.sec_fetch()`
   must support an optional fallback URL with consecutive-failure
   switch. Current single-source implementations are the default; the
   rewrite supplies a failover wrapper.

4. **§4 rate limiting.** `scripts/pipeline/shared.rate_limit()` uses
   `time.monotonic()` per-domain locks. Every script migrating to the
   framework drops its hardcoded `time.sleep(SEC_DELAY)`.

5. **§5b QC gates.** `ParseResult.qc_failures` carries BLOCK/FLAG/WARN
   severities. `SourcePipeline.validate()` dispatches on severity —
   BLOCKs refuse promote, FLAGs/WARNs record but proceed.

Each script's violation list must be reduced to zero before its rewrite
PR merges. The list is the acceptance criteria.
