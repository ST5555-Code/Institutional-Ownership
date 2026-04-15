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

## fetch_adv.py (REWRITE)

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

## fetch_ncen.py (RETROFIT)

- §6 (progress): 50-filing progress at `fetch_ncen.py:435` lacks
  explicit `flush=True` — relies on `python3 -u` at call sites.
- §9 (dry-run): **VIOLATION** — `--test` at `:` exists but writes; no
  `--dry-run`/`--apply`.
- Otherwise clean: CHECKPOINT every 25 filings at `:474` + final `:476`,
  restart-safe via `get_processed_ciks` + WHERE filter at `:422,:426`,
  429 retry at `:78`, `SEC_DELAY = 0.5` at `:60`.

---

## load_13f.py (REWRITE)

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

## build_managers.py (REWRITE)

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

## build_summaries.py (REWRITE)

- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--staging` at `:130`
  and `--rebuild` at `:129` exist.
- Legacy refs: `build_summaries.py:73` `FROM holdings h`; `:118`
  `FROM holdings h`. DDL drift documented in `docs/canonical_ddl.md`
  (prod has `rollup_entity_id`, `rollup_name`, `total_nport_aum`,
  `nport_coverage_pct`; script has none of these and wrong PK).

---

## build_fund_classes.py (REWRITE)

- §1 (incremental save): weak — CHECKPOINT every 5000 XMLs at
  `build_fund_classes.py:104`, final at `:135`. Adequate but sparse
  for the N-PORT XML volume.
- §5 (error handling): silent — `pass` at `:53` and `:133` hide parse
  failures.
- §9 (dry-run): **VIOLATION** — no flag; `DB_PATH` hardcoded to prod at
  `build_fund_classes.py:19`. No `--staging` plumbing.
- Legacy refs: `build_fund_classes.py:139` ALTER `fund_holdings`;
  `:146-151` UPDATE; `:152` COUNT.

---

## build_entities.py (RETROFIT)

- §1 (incremental save): **VIOLATION** — no CHECKPOINT inside any of
  the 7 build steps. Large INSERT chains flush only at close.
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

## build_shares_history.py (REWRITE)

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

## compute_flows.py (REWRITE)

- §9 (dry-run): **VIOLATION** — no `--dry-run`. `--staging` at `:256`
  exists.
- Legacy refs: `compute_flows.py:69,:78` `FROM holdings WHERE
  quarter = '{q_from/to}'`. Uses dropped `holdings` for flow math.
- Otherwise close to OK: DROP+CREATE idempotent (`:25-36,:37-45`),
  per-period INSERT with end-CHECKPOINT at `:229`, flushed prints at
  `:50,:131,:136,:176,:207`.

---

## merge_staging.py (RETROFIT)

- §5 (error handling): per-table try/except at `merge_staging.py:289`
  prints error but continues — can mask real failures.
- Legacy refs: `:45` `"beneficial_ownership": ["accession_number"]`,
  `:51` `"fund_holdings": None` (both dropped Stage 5). Comments at
  `:154-160,:204-205,:273` reference legacy names.
- Otherwise clean: `--dry-run` at `:195`, `--all --i-really-mean-all`
  gate at `:209`, CHECKPOINT at `:293`.
- Fix: derive `TABLE_KEYS` from
  `scripts/pipeline/registry.merge_table_keys()` to keep drift from
  reappearing.

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
