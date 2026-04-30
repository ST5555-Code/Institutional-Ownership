# Process Rules — Large-Data Scripts

_Updated: 2026-04-09_

These rules apply to any script that fetches, resolves, or transforms data in
batches (EDGAR downloads, name resolution, enrichment pipelines, etc.).

---

## 1. Incremental Save — Never Batch at End

- UPDATE/INSERT each row (or small batch) **immediately** after processing.
- `CHECKPOINT` every 500 rows to flush DuckDB WAL to disk.
- Never accumulate results in memory and write them all at the end.
- **Why:** If the process is killed or rate-limited after 10,000 of 15,000 rows,
  all 10,000 are already persisted. Restart picks up the remaining 5,000.

## 2. Restart-Safe by Design

- Use WHERE clauses that **naturally exclude already-processed rows**.
  Example: `WHERE filer_name IN ('Toppan Merrill/FA', 'Unknown')` — once a row
  is updated, it no longer matches. Zero restart logic needed.
- If natural exclusion isn't possible, track progress in a `_processed` flag
  column or a small checkpoint table.
- Scripts MUST be safe to run twice with identical results (idempotent).

## 3. Multi-Source with Automatic Failover

When fetching from external APIs (EDGAR, SEC, etc.):

- **Use at least two data sources** when available (e.g., EFTS + SEC .hdr.sgml).
- Track **consecutive failure count** per source. After N failures (default 10),
  switch primary to the other source automatically.
- When one source is rate-limited/blocked, the other keeps progress moving.
- **Why:** SEC blocks after ~1,500 rapid requests. EFTS has gaps for some filings.
  Neither alone covers 100%, but together they do.

## 4. Rate Limiting

- Separate rate limiters per endpoint (EFTS vs. sec.gov have independent limits).
- Default: 8 req/s for EFTS, 8 req/s for SEC.
- Use `time.monotonic()` not `time.time()` for interval tracking.
- When using threads, use a global lock per endpoint.
- After a 429 response, back off for 10+ minutes on that endpoint — don't retry
  in a tight loop.

## 5. Error Handling — Resolve Before Proceeding

After processing completes:

- **Audit unresolved rows** — print count and percentage.
- If unresolved > 5%: **STOP**. Print error. Do not rebuild derived tables.
  Investigate and fix before moving on.
- If unresolved 1-5%: **WARNING**. Log to roadmap as a follow-up item.
  Proceed but flag.
- If unresolved < 1%: acceptable. Note in final status.

Never silently accept a large failure rate.

## 5b. QC Validation — Cross-Check Parsed Values

When parsing numeric fields (shares, percentages):

- **Cross-validate** against independent sources (e.g., shares × price vs reported pct,
  or 13D/G shares vs 13F holdings for the same filer+ticker).
- **QC gates** on parsed values:
  - pct_owned: must be 0–100. Reject >100% (likely shares parsed as pct).
  - shares_owned: must be 0 or >=100. Reject 1–99 (likely row numbers or footnotes).
- **Flag suspect values** (e.g., implied pct >100% from shares/outstanding) — don't
  silently keep them. NULL and re-parse.
- **Exit filings**: pct=0% with null shares → set shares=0. These are legitimate
  below-threshold disclosures.

## 6. Progress Reporting

- Print progress every 500 rows: count, resolved, failed, rate, ETA.
- Print source breakdown (how many from each source).
- Print final summary with wall-clock time.
- Use `flush=True` on all print statements (or `python3 -u`) so background
  runs show real-time output.

## 7. Derived Table Rebuild

- Rebuild derived/materialized tables (e.g., `beneficial_ownership_current`)
  **once at the end**, not during processing.
- The rebuild is fast (seconds) and only needs to happen after all rows are
  updated.

## 8. Parser Sync — Keep All Scripts in Lockstep

When fixing parsing patterns (regex, clean_text, QC gates):

- **Update ALL scripts** that share the same parsing logic. For 13D/G:
  - `fetch_13dg.py` — main pipeline parser (`_extract_fields`, `_clean_text`)
  - `reparse_13d.py` — re-parse script for 13D
  - `reparse_all_nulls.py` — re-parse script for all types
- Same `clean_text()` function, same pattern lists, same QC thresholds.
- **Why:** A pattern fix in the re-parse script that isn't synced to
  `fetch_13dg.py` means new filings will hit the same bug.

## 9. Dry-Run by Default

- Default mode: process 10 samples, print results, exit.
- `--apply` flag required for real writes.
- Never auto-apply on first run.
- **Every script with a CLI write path MUST accept `--dry-run`.** When set, the
  script performs no DB mutations, no CSV/file writes, and no network POSTs.
- For scripts whose existing safe-default flag is `--apply` / `--production`,
  `--dry-run` is the explicit form of the default safe mode and overrides
  `--apply` if both are passed.

### 9a. Compliance Table (audited 2026-04-28, refreshed p3-audit-dryrun)

Pipeline scripts (`scripts/pipeline/*.py`) — SourcePipeline subclasses inherit
`--dry-run` semantics from `scripts/pipeline/base.py`. The base class halts at
the `pending_approval` step (after fetch / parse / validate / diff into the
staging DB) and only writes to prod when `approve_and_promote(run_id)` is
called explicitly. `--dry-run` on a SourcePipeline subclass therefore always
exits before prod is touched.

| Script | Has --dry-run | Notes |
|---|---|---|
| `pipeline/load_13dg.py` | ✅ | SourcePipeline; halts at pending_approval |
| `pipeline/load_adv.py` | ✅ | SourcePipeline; halts at pending_approval |
| `pipeline/load_market.py` | ✅ | SourcePipeline; halts at pending_approval |
| `pipeline/load_ncen.py` | ✅ | SourcePipeline; halts at pending_approval |
| `pipeline/load_nport.py` | ✅ | SourcePipeline; halts at pending_approval |
| `pipeline/compute_parent_fund_map.py` | ✅ | SourcePipeline; preview-only when set |
| `pipeline/compute_peer_rotation.py` | ✅ | SourcePipeline; preview-only when set |
| `pipeline/compute_sector_flows.py` | ✅ | SourcePipeline; preview-only when set |
| `pipeline/validate_schema_parity.py` | n/a | Read-only validator |

Non-pipeline scripts (`scripts/*.py`) with CLI write paths:

| Script | --dry-run | Other write-gating flag(s) |
|---|---|---|
| `auto_resolve.py` | ✅ (rule9-43e) | `--staging` (DB target) |
| `backfill_manager_types.py` | ✅ | `--production` (prod vs staging) |
| `build_classifications.py` | ✅ | `--staging` |
| `build_cusip.py` | ✅ | — |
| `build_fixture.py` | ✅ | — |
| `build_fund_classes.py` | ✅ | — |
| `build_managers.py` | ✅ | — |
| `build_shares_history.py` | ✅ | — |
| `build_summaries.py` | ✅ | — |
| `build_benchmark_weights.py` | ✅ (rule9-43e) | `--staging` |
| `compute_flows.py` | ✅ | — |
| `enrich_13dg.py` | ✅ | — |
| `enrich_fund_holdings_v2.py` | ✅ (rule9-43e) | `--apply` (alias) |
| `enrich_holdings.py` | ✅ | — |
| `enrich_tickers.py` | ✅ | — |
| `fetch_dera_nport.py` | ✅ | — |
| `fetch_finra_short.py` | ✅ | — |
| `fix_fund_classification.py` | ✅ (rule9-43e) | `--production` |
| `load_13f.py` | ✅ | — |
| `load_13f_v2.py` | ✅ | `--staging` (SourcePipeline halt) |
| `merge_staging.py` | ✅ | — |
| `normalize_names.py` | ✅ (rule9-43e) | `--apply` (alias) |
| `normalize_securities.py` | ✅ (rule9-43e) | `--staging` |
| `promote_staging.py` | ✅ | `--approved` |
| `queue_nport_excluded.py` | ✅ | — |
| `reparse_13d.py` | ✅ (rule9-43e) | `--apply` (alias) |
| `reparse_all_nulls.py` | ✅ (rule9-43e) | `--apply` (alias) |
| `resolve_13dg_filers.py` | ✅ | — |
| `resolve_long_tail.py` | ✅ | — |
| `resolve_pending_series.py` | ✅ | — |
| `run_openfigi_retry.py` | ✅ | — |
| `sync_staging.py` | ✅ | — |
| `build_entities.py` | ✅ (p3-audit-dryrun) | Top-level guard: opens read-only DuckDB, prints planned step ops + estimated row counts (PARENT_SEEDS, distinct CIKs, fund_universe rows, ncen rows, cik_crd_links, cik_crd_direct), exits before any step. Composes with `--reset` and `--refresh-reference-tables` (both reported in plan, neither executed). |
| `resolve_adv_ownership.py` | ✅ (p3-audit-dryrun) | Top-level guard: prints which phase(s) would run for the selected mode (`--download-only` / `--parse-only` / `--match-only` / `--refresh` / `--oversized` / `--qc` / `--manual-add` / full), names the side-effect targets (PDF cache dir, `adv_schedules.csv`, results/JV/unmatched CSVs, staging entity tables), exits before downloads or DB writes. |

Read-only scripts that do not need `--dry-run`: `backup_db.py`, `benchmark.py`,
`check_freshness.py`, `diff_staging.py`, `rollback_promotion.py` (gated by
`--confirm`/`--restore`), `rollback_run.py` (gated by
`--confirm`/`--i-understand-this-writes`), `scheduler.py`,
`validate_classifications.py`, `validate_entities.py`,
`verify_migration_stamps.py`, `yahoo_client.py`, `db.py`.

## 10. Script Structure Template

```
1. Connect to DB
2. SELECT unprocessed rows (WHERE clause excludes done rows)
3. If count == 0: print "nothing to do", exit
4. For each row:
   a. Try primary source
   b. If fail: try secondary source
   c. If resolved: UPDATE immediately (with QC validation)
   d. If fail: increment error counter
   e. Every 500: CHECKPOINT + progress line
5. Final CHECKPOINT
6. Audit unresolved — enforce thresholds (Rule 5)
7. Cross-validate parsed values (Rule 5b)
8. Rebuild derived tables
9. Print final status
```

## 11. Git Ops — PR/Merge Workflow (Code sessions)

Set 2026-04-29 (conv-18-doc-sync). Replaces the prior split where the operator did the merge step from Terminal.

- **Code pushes the branch, opens the PR, waits for CI green, then merges** via:

  ```
  gh pr merge --squash --delete-branch
  git checkout main && git pull --ff-only
  ```

  Then runs `./scripts/hygiene/cleanup_merged_worktree.sh <pr-number>` if a worktree was used.

- **Session/branch naming.** Always use a short descriptive slug, not the legacy `<theme>-<seq>` pattern, for UI/feature/doc-sync work. Examples that landed in conv-18: `dark-ui-restyle`, `layout-header-fullwidth`, `sector-rotation-redesign`, `sr-layout-polish`, `sr-chart-movers-fix`, `investor-detail-redesign`, `investor-detail-dedup`, `compact-density`.

  **Claude must propose the short slug before writing any prompt for Code.** Code does not invent the branch name.

- **Doc-sync PRs are an exception** — they commit directly to main per session brief, not via PR.

- **Never `--no-verify` / `--no-gpg-sign`** unless the user explicitly asks.

- The `<theme>-<seq>` convention in `docs/SESSION_NAMING.md` (`int-NN`, `obs-NN`, `mig-NN`, `sec-NN`, `ops-NN`, `conv-NN`, `prog-NN`) still applies to remediation-program work that maps to a numbered item in that program. Feature/UI work uses short slugs.
