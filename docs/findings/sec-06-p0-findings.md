# sec-06-p0 — Phase 0 findings: 5 direct-to-prod writers missing inventory

_Prepared: 2026-04-21 — branch `sec-06-p0` off main HEAD `742d504`._

_Tracker: [docs/REMEDIATION_PLAN.md](docs/REMEDIATION_PLAN.md) Theme 4-C row sec-06 (MAJOR-3 C-05, Batch 4-C). Scope: five "resolver" / "enrichment" scripts that write directly to production without being declared in [docs/pipeline_violations.md](docs/pipeline_violations.md). Disjoint file set from sec-05; see [sec-05-p0-findings §5.3](docs/findings/sec-05-p0-findings.md)._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** Five scripts:
1. [scripts/resolve_agent_names.py](scripts/resolve_agent_names.py)
2. [scripts/resolve_bo_agents.py](scripts/resolve_bo_agents.py)
3. [scripts/resolve_names.py](scripts/resolve_names.py)
4. [scripts/backfill_manager_types.py](scripts/backfill_manager_types.py)
5. [scripts/enrich_tickers.py](scripts/enrich_tickers.py)

Plus the "inline UA fix" portion of sec-06 on [scripts/fetch_adv.py](scripts/fetch_adv.py) that [REMEDIATION_PLAN.md:519](docs/REMEDIATION_PLAN.md:519) attributed to sec-06 — cross-checked against sec-08 (PR #41).

**Method.** Full-file reads of all five scripts. Targeted greps for `UPDATE`, `INSERT`, `DELETE`, `ALTER`, `DROP`, `CREATE`, `CHECKPOINT`, `get_db_path`, `set_staging_mode`, `--staging`, `--dry-run`, `--apply`, `crash_handler`, `EDGAR_IDENTITY`, `SEC_HEADERS`, `from config`. Line-number annotated. Cross-check against [docs/pipeline_violations.md](docs/pipeline_violations.md) (grep for each script name). No runtime probing.

---

## §2. Per-script inventory

### 2.1 `scripts/resolve_agent_names.py`

Re-downloads 13D/G filings where `filer_name = 'Unknown (filing agent)'` and parses the cover-page "NAME OF REPORTING PERSON" block to recover the real beneficial-owner name.

**DB connection.** [resolve_agent_names.py:133-134](scripts/resolve_agent_names.py:133) — `db_path = get_db_path(); con = duckdb.connect(db_path)`. Routes through [db.py](scripts/db.py) — `--staging` sets staging DB at [:277-278](scripts/resolve_agent_names.py:277).

**Write operations.**

| Op | Table | Columns | Line(s) | WHERE / guard |
|---|---|---|---|---|
| UPDATE | `beneficial_ownership` | `filer_name`, `name_resolved` | [:200-205](scripts/resolve_agent_names.py:200) | `accession_number = ?` AND `filer_name = 'Unknown (filing agent)'` (idempotent on replay) |
| DROP TABLE | `beneficial_ownership_current` | full table | [:212](scripts/resolve_agent_names.py:212) | unconditional — kill-window risk for seconds |
| CREATE TABLE AS SELECT | `beneficial_ownership_current` | full table | [:213-244](scripts/resolve_agent_names.py:213) | rebuilt from ranked view |
| CHECKPOINT | — | — | [:263](scripts/resolve_agent_names.py:263) | once, at end only |

**Flags.** `--apply` (default is 5-sample dry-run) [:270-271](scripts/resolve_agent_names.py:270); `--staging` [:274-275](scripts/resolve_agent_names.py:274); `--workers` (unused, sequential in practice).

**Row impact.** Targeted per-filing UPDATE keyed by `accession_number`. Current universe of unresolved filings is bounded by `filer_name = 'Unknown (filing agent)'` count (low thousands based on prior [resolve_bo_agents.py](scripts/resolve_bo_agents.py:346) audit logic).

**Frequency.** On-demand after 13D/G fetch runs when filer-agent residual exists.

**crash_handler.** Yes, [:280-282](scripts/resolve_agent_names.py:280).

**EDGAR identity.** Uses `config.EDGAR_IDENTITY` [:30, :103](scripts/resolve_agent_names.py:30). Closed by sec-08.

**Gaps.**
- CHECKPOINT only at end — crash mid-run loses nothing (restart-safe via WHERE clause), but does not progressively flush.
- `beneficial_ownership_current` rebuild is DROP-then-CREATE, not `CREATE OR REPLACE TABLE` — kill-window exists for seconds. Same pattern as `resolve_bo_agents.py` and `resolve_names.py`.

---

### 2.2 `scripts/resolve_bo_agents.py`

Resolves rows where `filer_name IN ('Toppan Merrill/FA', 'Unknown (filing agent)')` via dual-source failover (EFTS search-index API, SEC `.hdr.sgml` header).

**DB connection.** [resolve_bo_agents.py:258-259](scripts/resolve_bo_agents.py:258) — `db_path = get_db_path(); con = duckdb.connect(db_path)`. `--staging` at [:393-394](scripts/resolve_bo_agents.py:393).

**Write operations.**

| Op | Table | Columns | Line(s) | WHERE / guard |
|---|---|---|---|---|
| UPDATE | `beneficial_ownership` | `filer_name`, `filer_cik`, `name_resolved` | [:296-300](scripts/resolve_bo_agents.py:296) | `accession_number = ?` (idempotent; rows already resolved fall out of the initial SELECT) |
| DROP TABLE | `beneficial_ownership_current` | full table | [:361](scripts/resolve_bo_agents.py:361) | unconditional |
| CREATE TABLE AS SELECT | `beneficial_ownership_current` | full table | [:362](scripts/resolve_bo_agents.py:362) via `REBUILD_CURRENT_SQL` [:217-249](scripts/resolve_bo_agents.py:217) | rebuilt from ranked view |
| CHECKPOINT | — | — | [:306, :323, :380](scripts/resolve_bo_agents.py:306) | every 500 rows (§1 compliant) + post-rebuild + final |

**Flags.** `--apply` (default 10-sample dry-run) [:388-389](scripts/resolve_bo_agents.py:388); `--staging` [:390-391](scripts/resolve_bo_agents.py:390).

**Row impact.** Per-filing UPDATE keyed by `accession_number`. Restart-safe: WHERE clause filters already-resolved rows on reboot ([:266-271](scripts/resolve_bo_agents.py:266)).

**Frequency.** On-demand, typically after 13D/G quarter refresh.

**crash_handler.** Yes, [:396-398](scripts/resolve_bo_agents.py:396).

**EDGAR identity.** Uses `config.EDGAR_IDENTITY` [:38, :84, :135](scripts/resolve_bo_agents.py:38). Closed by sec-08.

**Gaps.** Same DROP→CREATE kill-window as 2.1 on the current view. Otherwise this script is the best-behaved of the five — full PROCESS_RULES compliance (§1 incremental save, §2 restart-safe, §3 multi-source failover, §4 rate limit, §9 dry-run).

---

### 2.3 `scripts/resolve_names.py`

Three-pass resolver for `filer_name` that is NULL / empty / still a raw CIK string. Pass 1 cross-references `holdings.cik`; Pass 2 hits SEC EDGAR submissions API; Pass 2b tries `company_tickers.json`; Pass 2c marks residuals as `'Unknown (filing agent)'`; Pass 3 adds `name_resolved` column.

**DB connection.** [resolve_names.py:223, :229](scripts/resolve_names.py:223) — `db_path = get_db_path(); con = duckdb.connect(db_path)`. `--staging` at [:337-338](scripts/resolve_names.py:337).

**Write operations.**

| Op | Table | Columns | Line(s) | WHERE / guard |
|---|---|---|---|---|
| UPDATE | `beneficial_ownership` | `filer_name` | [:144-149](scripts/resolve_names.py:144) (apply_resolutions — called 3× for holdings/edgar/company_tickers) | `filer_cik = ?` AND name is NULL/empty/raw-CIK |
| ALTER TABLE ADD COLUMN | `beneficial_ownership` | `name_resolved BOOLEAN DEFAULT FALSE` | [:161](scripts/resolve_names.py:161) | idempotent via DESCRIBE check at [:159-160](scripts/resolve_names.py:159) |
| UPDATE | `beneficial_ownership` | `name_resolved = TRUE` | [:165-171](scripts/resolve_names.py:165) | rows with real names |
| UPDATE | `beneficial_ownership` | `name_resolved = FALSE` | [:176-181](scripts/resolve_names.py:176) | unresolved rows |
| UPDATE | `beneficial_ownership` | `filer_name = 'Unknown (filing agent)'` | [:289-295](scripts/resolve_names.py:289) | residuals (Pass 2c) |
| DROP TABLE | `beneficial_ownership_current` | full table | [:189](scripts/resolve_names.py:189) | unconditional |
| CREATE TABLE AS SELECT | `beneficial_ownership_current` | full table | [:190-217](scripts/resolve_names.py:190) | rebuilt from ranked view |
| CHECKPOINT | — | — | [:325](scripts/resolve_names.py:325) | once, at end only |

**Reads.** `holdings` [:50-56](scripts/resolve_names.py:50) — **legacy `holdings` table**, not `holdings_v2`. Pre-[Batch 3 close](docs/pipeline_violations.md:250) artifact. Phase 1 should evaluate whether Pass 1 still lights up — if `holdings` is retired, Pass 1 is silently a no-op and should be repointed or removed.

**Flags.** `--apply` (default dry-run audit) [:333-334](scripts/resolve_names.py:333); `--staging` [:335-336](scripts/resolve_names.py:335).

**Row impact.** Potentially thousands of rows per run (all rows with NULL/empty/raw-CIK names). The WHERE filters on `filer_name IS NULL OR filer_name = '' OR regexp_matches(filer_name, '^\d{7,10}$')` make each pass idempotent.

**Frequency.** On-demand when `filer_name` residual is audited.

**crash_handler.** Yes, [:339-340](scripts/resolve_names.py:339).

**EDGAR identity.** Uses `config.EDGAR_IDENTITY` [:26, :88, :124](scripts/resolve_names.py:26). Closed by sec-08.

**Gaps.**
- **Schema mutation without staging gate.** ALTER TABLE ADD COLUMN runs against whatever `get_db_path()` returns — if invoked without `--staging`, schema change lands on prod. Idempotent (DESCRIBE check), but still a prod-side schema mutation outside the `scripts/migrations/` system.
- CHECKPOINT only at end — six UPDATEs fire before the first flush.
- Reads from legacy `holdings` table ([:50-56](scripts/resolve_names.py:50)) — suspected stale.
- Same DROP→CREATE kill-window on current view.

---

### 2.4 `scripts/backfill_manager_types.py`

Reads hand-curated `categorized_institutions_funds_v2.csv` (5,782 rows, 13 categories) and UPDATEs `holdings_v2.manager_type` + `managers.strategy_type` where current value is NULL or 'unknown'.

**DB connection.** **Different pattern from the other four.** Does NOT use `get_db_path()`. Hardcodes both prod and staging paths inside `main()` at [backfill_manager_types.py:199-204](scripts/backfill_manager_types.py:199):

```python
if args.production:
    db = base / 'data' / '13f.duckdb'
else:
    db = base / 'data' / '13f_staging.duckdb'
```

Safe in practice because the **default is staging** and `--production` is the explicit prod gate. But the deviation from `db.set_staging_mode()` / `db.get_db_path()` means this script doesn't share the same staging plumbing as the rest of the codebase (`db.seed_staging()`, `REFERENCE_TABLES` seeding, etc.).

**Write operations.**

| Op | Table | Columns | Line(s) | WHERE / guard |
|---|---|---|---|---|
| CREATE OR REPLACE TEMP TABLE | `_manager_categories` | `(name_clean, category)` | [:77-82](scripts/backfill_manager_types.py:77) | per-session temp — safe |
| INSERT | `_manager_categories` (temp) | `(name_clean, category)` | [:83-87](scripts/backfill_manager_types.py:83) | per-row loop, 5,782 iters |
| UPDATE | `holdings_v2` | `manager_type` | [:115-121](scripts/backfill_manager_types.py:115) | JOIN on lower/trim name + `manager_type IS NULL OR 'unknown'` (idempotent) |
| UPDATE | `managers` | `strategy_type` | [:125-131](scripts/backfill_manager_types.py:125) | JOIN on lower/trim name + `strategy_type IS NULL OR 'unknown'`; wrapped in try/except/pass [:124, :133-134](scripts/backfill_manager_types.py:124) |
| record_freshness | `holdings_v2` | — | [:182](scripts/backfill_manager_types.py:182) | try/except-guarded |
| CHECKPOINT | — | — | [:185](scripts/backfill_manager_types.py:185) | once, at end |

**Flags.** `--production` (default staging) [:192-193](scripts/backfill_manager_types.py:192); `--dry-run` [:194-195](scripts/backfill_manager_types.py:194). **No `--staging`** because the opposite polarity (`--production`) is the explicit flag.

**Row impact.** Bounded by the CSV. 5,782 category mappings × hit rate. Empirically: from [pipeline_violations.md:243-271](docs/pipeline_violations.md:243) (the Rewrite5 close), one run recovered ~12.3M holdings_v2 rows across 9,121 CIKs / 13 types at commit `c2c2bac`. Post-rewrite residual is ~14,368 rows / 9 entities (ongoing curation).

**Frequency.** On-demand when the CSV is updated.

**crash_handler.** **No** — uses raw `main()` at [:213-214](scripts/backfill_manager_types.py:213).

**EDGAR identity.** Not applicable — no HTTP calls.

**Gaps.**
- Bypasses `db.get_db_path()` / `db.set_staging_mode()` — diverges from codebase pattern.
- No `crash_handler` wrap.
- try/except/pass at [:124, :133-134](scripts/backfill_manager_types.py:124) swallows all errors on the `managers` UPDATE. The exception path only prints; it does not fail the run.
- `record_freshness` is also try/except-swallowed at [:181-184](scripts/backfill_manager_types.py:181) — freshness silently drops on error.
- Already cleared partially in [pipeline_violations.md:243-271](docs/pipeline_violations.md:243) as the Rewrite5 repoint (targets `holdings_v2` post-commit `7b8a2b7`), but sec-06 wants this inventoried formally — that clearance note is about the `holdings → holdings_v2` retargeting, not about the direct-to-prod classification.

---

### 2.5 `scripts/enrich_tickers.py`

**Most concerning of the five.** Cascades across four prod tables to improve CUSIP→ticker coverage, then fetches market data for newly resolved tickers.

**DB connection.** [enrich_tickers.py:419](scripts/enrich_tickers.py:419) — `con = duckdb.connect(get_db_path())`. `--staging` at [:479-480](scripts/enrich_tickers.py:479).

**Write operations.**

| Op | Table | Columns | Line(s) | WHERE / guard |
|---|---|---|---|---|
| UPDATE | `securities` | `ticker` | [:274-277](scripts/enrich_tickers.py:274) | `cusip = ?` AND `ticker IS NULL` (idempotent) |
| UPDATE | `holdings` | `ticker` | [:284-289](scripts/enrich_tickers.py:284) | JOIN on `cusip`; **legacy `holdings` table, not `holdings_v2`** |
| INSERT | `market_data` | 13 columns (ticker, price_live, market_cap, float_shares, shares_outstanding, 52w high/low, avg_volume_30d, sector, industry, exchange, fetch_date) | [:373-379](scripts/enrich_tickers.py:373) | append-only; de-duped via `existing` set at [:313-315](scripts/enrich_tickers.py:313) |
| UPDATE | `holdings` | `market_value_live` | [:388-395](scripts/enrich_tickers.py:388) | legacy `holdings` table, JOIN on `ticker` |
| UPDATE | `holdings` | `pct_of_float` | [:397-405](scripts/enrich_tickers.py:397) | legacy `holdings` table |
| CHECKPOINT | — | — | **none** | ❌ no CHECKPOINT anywhere in the script |

**Reads.** `securities` [:37-38, :147-152](scripts/enrich_tickers.py:37); `holdings` [:39-41](scripts/enrich_tickers.py:39); `market_data` [:42, :313-315](scripts/enrich_tickers.py:42).

**Flags.** `--staging` [:477-478](scripts/enrich_tickers.py:477). **No `--dry-run`.** **No `--apply`.** Invoking the script with no flags writes directly to prod.

**Row impact.** **High, uncapped.** Each full run can touch tens of thousands of rows across four tables. Per [:191-192](scripts/enrich_tickers.py:191), fuzzy-match alone operates on top 10,000 by value. `UPDATE holdings … FROM securities` at [:284-289](scripts/enrich_tickers.py:284) is a full table scan with no row limit.

**Frequency.** On-demand when ticker coverage is audited.

**crash_handler.** Yes, [:481-482](scripts/enrich_tickers.py:481).

**EDGAR identity.** Uses `config.SEC_HEADERS` [:26, :57, :103](scripts/enrich_tickers.py:26). Closed by sec-08.

**Gaps.**
- **No `--dry-run`.** Violates PROCESS_RULES §9.
- **No CHECKPOINT.** Violates PROCESS_RULES §1. Mid-run crash loses everything since connection open.
- **Writes to legacy `holdings` table**, not `holdings_v2`. Same concern as 2.3. The Batch 3 `enrich_holdings.py` ([pipeline_violations.md:54-55](docs/pipeline_violations.md:54)) was supposed to own `holdings_v2` live-value updates — the UPDATEs at [:388-405](scripts/enrich_tickers.py:388) duplicate (or contradict) that ownership.
- Cascades across four prod tables in a single run without a staging half or promote step — this is effectively a mini-builder masquerading as an enrichment script.
- `INSERT market_data` via `df.to_sql`-style [:376-377](scripts/enrich_tickers.py:376) has no transaction wrap; kill mid-append leaves a partial INSERT visible to downstream analytics.

---

## §3. pipeline_violations.md coverage check

| Script | Mentioned in pipeline_violations.md? | Line(s) | Notes |
|---|---|---|---|
| `resolve_agent_names.py` | **No** | — | Not listed. |
| `resolve_bo_agents.py` | **No** | — | Not listed. |
| `resolve_names.py` | **No** | — | Not listed. |
| `backfill_manager_types.py` | Partial | [:243-250](docs/pipeline_violations.md:243) | Referenced only inside the **`build_managers.py` CLEARED block** as the script that got retargeted from `holdings` → `holdings_v2` at commit `7b8a2b7`. No standalone entry declaring its direct-to-prod classification. |
| `enrich_tickers.py` | **No** | — | Not listed. |

**Net coverage: zero formal entries.** sec-06 needs to add one block per script (following the per-script block format used for `build_cusip.py` / `build_managers.py`) declaring them as either EXCEPTION (with PROCESS_RULES compliance note) or RETROFIT (with outstanding gaps).

---

## §4. fetch_adv.py UA status — closed by sec-08

[REMEDIATION_PLAN.md:519](docs/REMEDIATION_PLAN.md:519) lists `fetch_adv.py` under `sec-06 (inline UA fix)`. Verification per the task spec:

```
$ grep -n "EDGAR_IDENTITY\|SEC_HEADERS\|from config import" scripts/fetch_adv.py
37:from config import SEC_HEADERS
91:    r = requests.get(ADV_ZIP_URL, headers=SEC_HEADERS, timeout=120)
```

[fetch_adv.py:37](scripts/fetch_adv.py:37) imports `SEC_HEADERS` from the centralized `config.py`, and [fetch_adv.py:91](scripts/fetch_adv.py:91) uses it for the ADV ZIP fetch. This is exactly the pattern sec-08 (commit `fa01c7e`, PR #41) rolled out across 21 scripts.

**Status: CLOSED by sec-08.** The `fetch_adv.py` UA portion of sec-06 is not part of this item's Phase 1. Remaining sec-06 scope is strictly the five resolver/enrichment scripts above.

---

## §5. Classification

Per-script classification against the three options in the task brief:

| # | Script | Classification | Rationale |
|---|---|---|---|
| 2.1 | `resolve_agent_names.py` | **EXCEPTION** | Targeted per-row UPDATE keyed on `accession_number`. `--apply` defaults to 5-sample dry-run, `--staging` plumbed, `crash_handler` wrap, restart-safe via WHERE clause. Only gap: CHECKPOINT is end-only, not periodic. Declare as exception; retrofit the single CHECKPOINT gap in the same PR. |
| 2.2 | `resolve_bo_agents.py` | **EXCEPTION** | Textbook compliance: `--apply` defaults to 10-sample dry-run, `--staging`, `crash_handler`, CHECKPOINT every 500 rows, dual-source failover, WHERE-clause restart-safety, per-source rate limiting. Declare as exception with no retrofit. |
| 2.3 | `resolve_names.py` | **RETROFIT** | Targeted UPDATEs, but schema mutation (ALTER TABLE ADD COLUMN) runs against the live target and CHECKPOINT is end-only across six writes. Also reads from legacy `holdings` table (Pass 1 may be silently dead). Retrofit: (a) gate the ALTER behind `--staging`-aware migration or move to a proper `scripts/migrations/` entry; (b) CHECKPOINT after each pass; (c) repoint Pass 1 to `holdings_v2` or delete it. Then declare as exception. |
| 2.4 | `backfill_manager_types.py` | **RETROFIT** | Already partially noted in pipeline_violations.md. Retrofit: (a) switch to `db.get_db_path()` / `db.set_staging_mode()` to unify staging plumbing; (b) wrap in `crash_handler`; (c) replace silent `try/except/pass` on `managers` UPDATE with explicit error handling. Then declare as exception. Not bulk-enough to justify a staging→promote conversion. |
| 2.5 | `enrich_tickers.py` | **STAGE (or deep RETROFIT)** | Four-table cascade, no `--dry-run`, no CHECKPOINT, writes to legacy `holdings` table. This is a mini-builder, not a resolver. Two acceptable paths: **(a) STAGE** — convert to builder-style `--staging` + `--apply` + promote split, consolidate live-value UPDATEs into `enrich_holdings.py`'s territory, repoint to `holdings_v2`; **(b) deep RETROFIT** — add `--dry-run`, add CHECKPOINT every N, repoint to `holdings_v2`, keep direct-to-prod but declare with bolded PROCESS_RULES §1 and §9 violations still open. Recommend (a) for safety; (b) is a defensible short-term if scope must stay small. |

**Summary counts.** 2 EXCEPTION, 2 RETROFIT, 1 STAGE (or deep RETROFIT).

---

## §6. Proposed sec-06 Phase 1 scope

**In-scope files.**

| File | Change | Risk |
|---|---|---|
| `scripts/resolve_agent_names.py` | Add periodic CHECKPOINT (every 500 resolved rows in the apply loop). No other code change. | Low. |
| `scripts/resolve_names.py` | (a) Gate ALTER TABLE behind explicit migration path or `--staging` assertion; (b) CHECKPOINT after each of the six UPDATE passes; (c) repoint or remove legacy `holdings` read at Pass 1. | Medium — schema mutation path change. |
| `scripts/backfill_manager_types.py` | (a) Switch to `db.get_db_path()` / `db.set_staging_mode()` and accept `--staging` (replace `--production` polarity, or keep both as aliases with `--production` as explicit override); (b) wrap in `crash_handler`; (c) replace try/except/pass on managers UPDATE. | Low-Medium — flag polarity change is user-visible. |
| `scripts/enrich_tickers.py` | **Recommended (STAGE):** convert to `--staging` + `--apply` pattern, fold holdings live-value UPDATEs into `enrich_holdings.py`, repoint remaining UPDATEs to `holdings_v2`, add CHECKPOINT every 1000 rows. **Fallback (RETROFIT):** add `--dry-run`, add CHECKPOINT, repoint to `holdings_v2`. | **High** if STAGE (cross-script refactor); Medium if RETROFIT. |
| `scripts/resolve_bo_agents.py` | No code change. | — |
| `docs/pipeline_violations.md` | Add one block per script (five blocks total) declaring EXCEPTION / RETROFIT / STAGE classification with line citations. Follow the format of the existing `build_cusip.py` / `build_managers.py` blocks. | Low — docs only. |
| `docs/REMEDIATION_PLAN.md` | Close sec-06 row (Theme 4-C, line 162). Mark the `fetch_adv.py` UA note on line 519 as closed-by-sec-08. | Low — docs only. |
| `docs/REMEDIATION_CHECKLIST.md` | Flip line 117 (sec-06) to closed on Phase 1 ship. | Low — docs only. |
| `ROADMAP.md` | COMPLETED entry with commit refs. | Low — docs only. |

**Out-of-scope (explicitly deferred).**

- `fetch_adv.py` UA — already closed by sec-08.
- `validate_nport_subset.py`, `pipeline/shared.py` validator-writes-to-prod — listed separately under sec-04 per [REMEDIATION_PLAN.md:143](docs/REMEDIATION_PLAN.md:143).
- Unpinning `edgartools` / `pdfplumber` — tracked under sec-07.
- Rewriting `enrich_tickers.py` as a full builder with staging→promote → if the STAGE path is taken, scope creeps toward touching `enrich_holdings.py` ownership. Acceptable trade-off: keep (b) RETROFIT in Phase 1 and log the STAGE conversion as a separate follow-up (`sec-06b` or similar).
- Back-filling historical CHECKPOINT gaps in already-run `resolve_*` data. These scripts are idempotent on re-run; remediation is "next run is compliant" not "re-run to rebalance."

**Phase 1 file list (for the implementer).**

```
scripts/resolve_agent_names.py
scripts/resolve_names.py
scripts/backfill_manager_types.py
scripts/enrich_tickers.py
docs/pipeline_violations.md
docs/REMEDIATION_PLAN.md
docs/REMEDIATION_CHECKLIST.md
ROADMAP.md
```

`scripts/resolve_bo_agents.py` and `scripts/fetch_adv.py` do not need code changes — docs-only.

---

## §7. Risks and notes

1. **`enrich_tickers.py` legacy-table writes are the highest-risk item.** The script UPDATEs `holdings` (legacy) at [:284-289, :388-405](scripts/enrich_tickers.py:284) four times. Per [pipeline_violations.md:54-55](docs/pipeline_violations.md:54) and the Batch 3 close, `holdings` → `holdings_v2` migration already happened for most writers. If `holdings` is a view or deprecated shim, these UPDATEs may be silently dead; if `holdings` is still the write target, enrich_tickers is writing to a stale table that downstream consumers have already moved off. Phase 1 must resolve this before any further enrich_tickers run against prod.

2. **`resolve_names.py` ALTER TABLE outside migrations.** Adding `name_resolved` to `beneficial_ownership` at runtime ([:161](scripts/resolve_names.py:161)) sidesteps `scripts/migrations/`. Idempotent, but creates a drift gap: prod schema is modified by an "on-demand" resolver, not by a versioned migration. Phase 1 should either (a) move the ADD COLUMN into a real migration file and make resolve_names assert presence, or (b) at least guard the ALTER so it only fires under explicit `--init-schema` flag.

3. **`backfill_manager_types.py` `--production` polarity is non-standard.** Every other script in the codebase opts *into* staging via `--staging`. Backfill opts *out* of staging via `--production`. The default-to-staging polarity is actually safer, but the inconsistency trips up anyone pattern-matching against other scripts. If Phase 1 changes the flag, the run docs / README / ROADMAP references may need grep-and-update.

4. **`beneficial_ownership_current` DROP→CREATE kill-window.** Three of the five scripts rebuild this table with `DROP TABLE IF EXISTS` → `CREATE TABLE AS SELECT` ([resolve_agent_names.py:212-213](scripts/resolve_agent_names.py:212), [resolve_bo_agents.py:361-362](scripts/resolve_bo_agents.py:361), [resolve_names.py:189-190](scripts/resolve_names.py:189)). Kill between statements leaves the current view absent. Fix is a one-line change to `CREATE OR REPLACE TABLE beneficial_ownership_current AS …` (atomic in DuckDB). Not strictly sec-06 scope (same-pattern gap as sec-05), but trivially cheap to include in the same PR.

5. **Parallel-safety.** sec-06 Phase 1 touches only resolver/enrichment scripts + pipeline_violations.md. Disjoint from sec-05 (builders) and sec-07 (deps pinning), so parallel-safe. Overlaps with int-05/06 via `enrich_tickers.py` (int-06 also touches it per [REMEDIATION_PLAN.md:224](docs/REMEDIATION_PLAN.md:224)) — serialize the `enrich_tickers.py` edits.

6. **No runtime probing was performed.** All assertions above are from static reading of the five scripts plus `db.py`, `config.py`, `pipeline_violations.md`, and `REMEDIATION_PLAN.md`. A Phase 1 implementer should:
   - `python3 scripts/resolve_names.py` (no args) and verify it's a dry-run.
   - `python3 scripts/enrich_tickers.py --staging` and verify it routes to `13f_staging.duckdb` (known gap: no `--dry-run` means even the staging run will write).
   - `python3 scripts/backfill_manager_types.py --dry-run` to verify baseline.

---

## §8. Phase 1 acceptance criteria

1. Five blocks added to [docs/pipeline_violations.md](docs/pipeline_violations.md), one per script, classified per §5.
2. `scripts/resolve_agent_names.py` periodic CHECKPOINT landed.
3. `scripts/resolve_names.py` ALTER gated + per-pass CHECKPOINT + legacy `holdings` read resolved.
4. `scripts/backfill_manager_types.py` routes via `db.get_db_path()` / `db.set_staging_mode()`, wrapped in `crash_handler`, error-swallow removed.
5. `scripts/enrich_tickers.py` repointed to `holdings_v2`, `--dry-run` added, CHECKPOINT added. (STAGE conversion deferrable to sec-06b follow-up.)
6. `docs/REMEDIATION_PLAN.md` sec-06 row closed; `fetch_adv.py` UA note on line 519 marked closed-by-sec-08.
7. `docs/REMEDIATION_CHECKLIST.md` line 117 flipped.
8. `ROADMAP.md` COMPLETED entry.
9. CI smoke green.
