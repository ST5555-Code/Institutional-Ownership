# System Audit — 2026-04-17

**Platform:** 13F Institutional Ownership Research Database
**Repo:** `github.com/ST5555-Code/Institutional-Ownership` · HEAD `da418a1`
**Audit window:** 2026-04-17
**Canonical source.** This document supersedes the three prior audit artifacts for decision-making. The atlas, Codex review, and Pass 2 remain in `docs/` as underlying evidence.

---

## 1. Executive Summary

The platform is structurally sound and actively maintained. The three-reviewer audit produced approximately 100 findings across six categories. The core fact tables reconcile cleanly (three PASS, two PARTIAL, zero FAIL on cross-table math), the entity MDM is internally consistent, and the six source pipelines run on a roughly-nightly cadence with only one showing silent drift.

Four findings are production-critical and block further large-scale work until resolved.

**BLOCK-1 — Entity enrichment collapsed on recent months.** `fund_holdings_v2.entity_id` coverage is 40.09% overall and 0.18% for `report_month` 2025-11. Documentation still claims 84.47%. Pass 2 determined the dominant cause is that `_bulk_enrich_run` in `promote_nport.py` is scoped to the current run only; rows from prior promotes whose `series_id` became resolvable after the fact are never revisited. 76 to 94 percent of the NULL-entity_id rows would resolve on a full-scope backfill. This is live analytical degradation, not documentation drift.

**BLOCK-2 — Prod promotes are non-atomic.** Both `promote_nport.py` and `promote_13dg.py` perform multi-statement DELETE plus INSERT sequences without enclosing transactions. A process kill between the DELETE and the INSERT leaves prod rows missing. The file-level comment at `promote_nport.py:1-8` claims atomicity that the code does not deliver.

**BLOCK-3 — Legacy `fund_holdings` table still receives writes.** The retired `fetch_nport.py` remains on the admin `/run_script` whitelist at `admin_bp.py:258-265`. The 22,030-row write on 2026-04-14 at 21:22 is consistent with a single admin click. One-line fix unblocks the cleanup sequence.

**BLOCK-4 — Admin refresh design cannot extend existing surfaces.** The draft writes against fictional `ingestion_manifest` columns (`pipeline_name`, `status`, `completed_at`, `row_counts_json`) and fictional `ingestion_impacts` columns (`run_id`, `action`, `prior_accession`). It also specifies an 11-state lifecycle that does not map to the existing 5-state `fetch_status` enum. Restart requires pre-work: one schema migration, one protocol decision, one `parse()` purity decision.

Below BLOCK, thirteen MAJOR findings sit in a fixable-but-not-blocking tier — admin TOCTOU race, `fetch_adv.py` DROP-before-CREATE window, admin token persisted in browser `localStorage`, migration 004 interruption risk, and others. Seven MINOR items are punch-list.

**Sequencing.** BLOCK items in priority order:
1. Remove `'fetch_nport.py'` from admin allowlist (1 line, immediate — stops the legacy-table bleeding)
2. Entity-enrichment backfill job (1-2 days — recovers 2025-10 and 2026-01 coverage to ≥94%)
3. Transaction-wrap promote scripts, paired with `mirror_manifest_and_impacts` extraction (2-3 days)
4. Admin refresh schema reconciliation work (3-5 days — blocks that workstream restart)

After BLOCK: security batch (admin token + TOCTOU) and observability batch (manifest coverage + direct-writer tracking + `fetch_adv.py` DROP-before-CREATE) can run in parallel.

---

## 2. Methodology

Three reviewers worked in sequence. Each produced a distinct artifact in `docs/`. All three were read-only; no DB writes, no code edits, no pipeline runs during the audit window.

**Reviewer 1 — Claude Opus 4.7 in ultrathink.** Produced `SYSTEM_ATLAS_2026_04_17.md`. Atlas-depth, wide scope across six categories (data integrity, code integrity, pipeline health, roadmap vs reality, documentation freshness, operational state). Factual baseline with DB counts, coverage percentages, cross-table checks, git and log inventory. Sixty findings labeled CLEAN, DRIFT-SUSPECTED, or DRIFT-CONFIRMED. Pass 1's explicit design choice was breadth over depth.

**Reviewer 2 — Codex in max thinking mode.** Produced `CODEX_REVIEW_2026_04_17.md`. Three surfaces read: the atlas, the docs directory, and 115 scripts across 44,650 lines in `scripts/`. Six tasks: verify the five original contradictions from the admin-refresh design cycle, cross-check atlas findings, adversarial code review (transactions, idempotency, concurrency, failure modes, hidden coupling, authorization), doc surface consistency, extensions beyond the atlas, and original contributions. Thirty-nine findings: 27 AGREE, 5 DISAGREE, 7 NEW.

**Reviewer 3 — Claude Opus 4.7 1M in ultrathink (Pass 2).** Produced `SYSTEM_PASS2_2026_04_17.md`. Surgical, not wide. Six targeted tasks: trace the entity-enrichment collapse to its pipeline boundary, identify the legacy `fund_holdings` writer, structurally fix the `_mirror_manifest_and_impacts` duplication, schema-reconcile the admin refresh design against live control-plane, deep-audit the migration surface, and reconcile cross-table math. Plus independent verification of the four Codex claims driving BLOCK decisions. Two production-critical surprises surfaced beyond the six tasks.

**Reviewer disagreements resolved for this document.** Five atlas findings were corrected by Codex (Flask vs FastAPI, PROCESS_RULES parser-helper naming, REACT_MIGRATION line reading, validator staging vs prod scope, 13D/G fetch scope). Two Codex framings were corrected by Pass 2 (entity-enrichment primary driver, DM override NULL-target severity). This document adopts the corrected positions without re-litigation.

---

## 3. Data Integrity

Verdict: **DRIFT-CONFIRMED (live degradation).**

Fifty-six user tables surveyed. Seventeen fresh (within 14 days), zero stale. Cross-table reconciliation math passes on three of five pairs and produces no FAIL results. Entity MDM is synced across prod and staging.

The concentration of drift is in one place: `fund_holdings_v2` enrichment and CUSIP reference integrity.

### 3.1 Confirmed findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| D-01 | `fund_holdings_v2.entity_id` 40.09% coverage overall (8.44M NULL of 14.09M rows); `data_layers.md:92` claims 84.47% | Atlas §1.2, Codex §2a, Pass 2 §1 | **BLOCK-1** |
| D-02 | Coverage collapses by `report_month`: 2025-11 at 0.18%, 2025-12 at 0.61%, 2026-01 at 5.88% | Atlas §1.4 | **BLOCK-1** |
| D-03 | 31.48% of `fund_holdings_v2` rows (4.44M rows, 297K distinct CUSIPs) reference a CUSIP not in `securities` | Atlas §1.3 | MAJOR |
| D-04 | 15.87% of `fund_holdings_v2` rows have `series_id` not in `entity_identifiers` | Atlas §1.3 | MAJOR |
| D-05 | Legacy `fund_holdings` table still populated — 22,030 rows, max `loaded_at` 2026-04-14 21:22 | Atlas §1.8, Codex §2a, Pass 2 §2 | **BLOCK-3** |
| D-06 | `ingestion_impacts` has 3 rows for 13DG vs 51,905 BO rows — grain mismatch or un-mirrored backfill | Atlas §1.6, Codex §2b PROMOTE | MAJOR |
| D-07 | `ingestion_manifest` covers only MARKET / NPORT / 13DG — N-CEN and ADV are absent | Atlas §1.6 | MAJOR |

### 3.2 Pass 2 root cause on D-01/D-02

Pass 2 split the NULL-entity_id population per `report_month` into "series_id currently resolvable in `entity_identifiers`" versus "still unresolvable." Results:

| report_month | NULL rows | resolvable-but-not-backfilled | truly unresolvable | resolvable share |
|---|---:|---:|---:|---:|
| 2025-09 | 932,164 | 809,291 | 122,873 | 86.8% |
| 2025-10 | 1,234,552 | 1,164,448 | 70,104 | 94.3% |
| 2025-11 | 1,998,226 | 955,273 | 1,042,953 | 47.8% |
| 2025-12 | 2,499,277 | 1,912,229 | 587,048 | 76.5% |
| 2026-01 | 1,243,631 | 1,173,382 | 70,249 | 94.4% |

Dominant mechanism is missed backfill, not unresolvable input. The code boundary is `promote_nport.py:153-218` — `_bulk_enrich_run` filters on `series_touched` (the current run's staged tuples), so rows from prior promotes that became resolvable later are never revisited.

### 3.3 Cross-table reconciliation (Pass 2 §6)

| Pair | Grain | Result |
|---|---|---|
| `investor_flows` (EC, 2025Q3→Q4) vs `holdings_v2` ticker × rollup union | ticker × rollup | PARTIAL — 10,109 row under-count (0.48%) explained by NULL `rollup_entity_id` rows downstream of D-01 |
| `summary_by_ticker` 2025Q4 vs `holdings_v2` aggregation (AAPL/MSFT/NVDA/TSLA) | ticker × quarter | PASS — exact match on shares and holders |
| `summary_by_parent` 2025Q4 EC AUM vs `holdings_v2.market_value_usd` sum | quarter | PASS — 67,321,197,046,577 exact |
| `ticker_flow_stats.flow_intensity_total` vs naive derivation | ticker × quarter pair | PARTIAL — stored values 8-40× smaller than naive; formula undocumented, not wrong |
| `beneficial_ownership_current` vs `beneficial_ownership_v2` latest-accession | (filer_cik, subject_ticker) | PASS — 24,756 exact |

Key observation from the final pair: `bo_current` is keyed on `(filer_cik, subject_ticker)`, not CUSIP. A CUSIP-keyed rollup produces 7,390 rows because one CUSIP can carry multiple tickers.

---

## 4. Code Integrity

Verdict: **DRIFT-CONFIRMED (tail).**

Approximately fifty DB-writing scripts inventoried. Core v2 pipelines (`fetch_nport_v2`, `fetch_13dg_v2`, `promote_*`, `build_cusip` v2, `enrich_*`, `compute_flows`, `build_summaries`) comply with `PROCESS_RULES.md` §1 / §2 / §7. Drift concentrates in a long tail of direct-to-prod helpers and in one class of cross-cutting logic.

### 4.1 Confirmed findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| C-01 | Non-atomic prod promotes: `promote_nport.py:421-494` and `promote_13dg.py:273-305` run multi-statement DELETE+INSERT without enclosing transaction | Atlas §2.2, Codex §3a, Pass 2 §7.1 (verified) | **BLOCK-2** |
| C-02 | Validators open prod RW and write to `pending_entity_resolution` — `validate_nport_subset.py:67`, `:182-197` and `pipeline/shared.py:364-379` | Atlas §2.2, Codex §2a | MAJOR |
| C-04 | Hardcoded-prod builders: `build_managers.py`, `build_fund_classes.py`, `build_benchmark_weights.py` bypass staging | Atlas §2.2, Codex §2a | MAJOR |
| C-05 | Five unlisted direct-to-prod writers missing from `pipeline_violations.md`: `resolve_agent_names.py`, `resolve_bo_agents.py`, `resolve_names.py`, `backfill_manager_types.py`, `enrich_tickers.py` | Atlas §2.2, Codex §2a | MAJOR |
| C-06 | `fix_fund_classification.py` is a direct writer with no CHECKPOINT | Atlas §2.2, Codex §2a | MINOR |
| C-08 | `compute_flows.py` is destructive non-atomic — DROPs `investor_flows` and `ticker_flow_stats` before repopulating | Codex §2b PROMOTE, §3a | MAJOR |
| C-09 | `admin_bp.py` is a live write surface: mutates quarter config, launches scripts, writes entity overrides | Codex §2b PROMOTE | MAJOR |
| C-10 | Legacy `fetch_nport.py` is still runnable and is the writer behind D-05 | Atlas §2.2, Pass 2 §2 | **BLOCK-3** |

### 4.2 Pass 2 on non-atomic promotes

Pass 2 read both cited line ranges independently. The sequence in `promote_nport.py` is: `_mirror_manifest_and_impacts` (multi DELETE+INSERT) → `_promote_batch` (DELETE+INSERT on `fund_holdings_v2`) → CHECKPOINT → `_bulk_enrich_run` UPDATE → `_upsert_universe` (DELETE+INSERT) → UPDATE `ingestion_impacts` → CHECKPOINT → `stamp_freshness` × 2 → CHECKPOINT. Every statement auto-commits. A process kill between the DELETE at line 298-302 and the INSERT at line 328 leaves prod rows missing for the scope tuples.

The comment block at `promote_nport.py:1-8` claims "either the whole run commits or nothing does." The code does not deliver that invariant.

`promote_13dg.py:272-306` exhibits the same pattern.

---

## 5. Pipeline Health

Verdict: **PARTIAL / DEGRADED.**

Four of six source pipelines plus the derived trio are healthy. N-PORT, 13D/G, N-CEN, Market, and derived all fresh on 2026-04-17 and PROCESS_RULES-compliant. Two pipelines show silent drift.

### 5.1 Per-pipeline state

| Pipeline | Last run | Status | Notes |
|---|---|---|---|
| 13F (`load_13f.py`) | Undatable | STALE | No owning freshness writer; proxy via `holdings_v2_enrichment` 2026-04-17 04:56; DROP+CTAS pattern flagged REWRITE in `pipeline_inventory.md` |
| N-PORT (`fetch_nport_v2` + `promote_nport`) | 2026-04-17 11:11 | HEALTHY | Core source; no blockers beyond the promote-atomicity gap |
| 13D/G (`fetch_13dg_v2` + `promote_13dg`) | 2026-04-14 04:05 fetch, 2026-04-17 12:24 enrich | HEALTHY | Scoped vertical; pre-v2 history not mirrored into manifest |
| N-CEN (`fetch_ncen.py`) | 2026-04-17 13:12 | HEALTHY | RETROFIT tag; `flush=True` missing, no `--dry-run` |
| Market (`fetch_market.py`) | 2026-04-16 23:27 | HEALTHY (recurring crash risk) | `impact_id` duplicate-PK crash recurred 2026-04-16 after nominal `_next_id` fix |
| ADV (`fetch_adv.py`) | UNKNOWN | STALE | No log, no `loaded_at` column, no `data_freshness` row; best proxy 2026-04-07 |
| Derived (`enrich_holdings`, `compute_flows`, `build_summaries`) | 2026-04-17 13:30 | HEALTHY | — |

### 5.2 Confirmed findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| P-01 | 13F loader has no owning freshness writer; last datable run unknown | Atlas §3.1 | MINOR |
| P-02 | ADV pipeline undatable — no log, no `loaded_at`, no `data_freshness` row | Atlas §3.1, Codex §2b PROMOTE | MAJOR |
| P-04 | Market `impact_id` duplicate-PK crash recurred 2026-04-16 post-fix; indicates `_next_id` is only safe under true one-writer invariant | Atlas §3.4, Codex §2a | MAJOR |
| P-05 | N-CEN and ADV outside `ingestion_manifest` despite control-plane rhetoric | Atlas §3.5, Codex §2a | MAJOR |
| P-07 | N-PORT `report_month` leakage — 1,113 rows at 2026-02, 64 at 2026-03; no completeness gate | Atlas §3.5 | MINOR (WATCH) |

---

## 6. Roadmap vs Reality

Verdict: **CLEAN-WITH-MINOR-DRIFT.**

Twenty-three claims verified from the session #11 close header. Sixteen MATCH, three PARTIAL, two DRIFT-CONFIRMED, two UNVERIFIABLE. All headline prod counters reconcile exactly (`entities` 26,535, `entity_overrides_persistent` 245, `ncen_adviser_map` 11,209, `investor_flows` 17,396,524, `summary_by_parent` 63,916, snapshot 11,361.5 MB).

### 6.1 Confirmed findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| R-01 | Roadmap claims 928 13DG exclusions; prod has 931 | Atlas §4.2, Codex §2b PROMOTE | MINOR |
| R-02 | Roadmap + commit `938e435` body both claim "4 NULL-CIK" overrides in IDs 205-221; prod has 5 | Atlas §4.2, Codex §2a | MINOR |

R-02's commit prose itself under-counted, so the roadmap is faithful to the commit — it is the commit that is wrong. Low severity.

---

## 7. Documentation Freshness

Verdict: **DRIFT-CONFIRMED (root-level concentrated).**

Docs in `docs/` are actively maintained — six are within five days of HEAD. Drift lives in root-level README, deploy docs, PHASE prompts, and old architecture narratives that predate the FastAPI and React cutovers.

### 7.1 Confirmed findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| DOC-01 | `README.md` promotes retired `update.py` master pipeline | Atlas §5.2.1, Codex §2a | MINOR |
| DOC-02 | `README.md` project tree omits Blueprint, React, pipeline, migrations layouts | Atlas §5.2.1, Codex §2a | MINOR |
| DOC-03 | `PHASE3_PROMPT.md` instructs use of retired `fetch_nport.py` | Atlas §5.2.2, Codex §2a | MINOR |
| DOC-04 | `ARCHITECTURE_REVIEW.md:51-52` says React Phase 4 pending; `REACT_MIGRATION.md:120` says complete 2026-04-13 | Atlas §5.4, Codex §2a | MINOR |
| DOC-05 | `README_deploy.md` missing React `npm run build` prerequisite | Atlas §5.2.4, Codex §2a | MINOR |
| DOC-06 | `docs/write_path_risk_map.md` T2 list references retired / rewritten scripts | Atlas §5.2.5 | MINOR |
| DOC-09 | `docs/CLASSIFICATION_METHODOLOGY.md` cites 20,205 entities vs current 26,535 | Atlas §5.5, Codex §2b PROMOTE | MINOR |
| DOC-10 | `PHASE1_PROMPT.md` untracked; `PHASE3/PHASE4_PROMPT.md` tracked but orphaned | Atlas §5.5 | MINOR |
| DOC-11 | `docs/data_layers.md:92` headline claim 84.47% entity coverage is now 40.09% | Atlas §5.5, Codex §2a | MAJOR (auto-resolves with BLOCK-1 fix) |
| DOC-12 | No architecture doc for `scripts/api_*.py` Blueprint split | Atlas §5.5, Codex §2b PROMOTE | MINOR |

### 7.2 Codex corrections to atlas doc findings (adopted)

Atlas DOC-07 overstated drift: `PROCESS_RULES.md:94` names `fetch_13dg.py` for parser-sync, which is functionally correct because `fetch_13dg_v2.py:60, :214-215` still imports its helpers. Form is stale; content remains accurate.

Atlas DOC-08 misread the line: `REACT_MIGRATION.md:121` accurately states `web/templates/index.html` was deleted; surviving `admin.html` is not a contradiction on that line.

---

## 8. Operational State

Verdict: **AMBER.**

Stable tip, reliable backup, healthy disk (136 G free), consistent EDGAR email, green logs. Housekeeping drift is real but non-blocking.

### 8.1 Confirmed findings

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| O-02 | `edgartools` and `pdfplumber` unpinned in `requirements.txt` (Flask no longer runtime-relevant per Codex correction) | Atlas §6.6, Codex §2b DOWNGRADE | MINOR |
| O-05 | Backup gap 3d 12h; 2026-04-14 backups 1.6 G vs surrounding 2.6-2.7 G — partial-state risk worth investigating | Atlas §6.2, Codex §2b PROMOTE | MINOR |
| O-08 | Divergent UA strings and bare-email-only scripts; no central identity config | Atlas §6.5, Codex §2b PROMOTE | MINOR |
| O-10 | No log-rotation policy; 182 log files back to 2026-04-01 | Atlas §6.3, Codex §2a | MINOR |

Accepted without action: 32 entity snapshot tables accumulating per D7 retention decision, two stale worktrees (`confident-rhodes`, `charming-haibt`), orphan branches, Datasette port 8002 guidance, untracked `Plans/` directory.

---

## 9. Contradictions

### 9.1 Five original contradictions from admin-refresh design cycle

All five verified against code by Codex. Results:

| # | Contradiction | Status | Mechanism |
|---|---|---|---|
| 1 | Snapshot mechanism conflict | CONFIRMED | Design proposes `data/backups/{pipeline}_{run_id}.duckdb` as new. Repo already has two live snapshot meanings: entity rollback snapshots inside prod DB (`promote_staging.py:67-101`) and app read-replica refresh (`promote_nport.py:502`, `promote_13dg.py:311`, `app_db.py:41-57`). Third meaning proposed without reconciling the two existing ones. |
| 2 | Validate-writes-prod carveout | CONFIRMED | Design claims validators are read-only while queueing unresolved identifiers to prod. Implementation already writes to prod (`validate_nport_subset.py:67`, `:182-197`; `pipeline/shared.py:364-379`). Carveout is real and already live. |
| 3 | Already-populated columns proposed as new | PARTIAL — worse than stated | Not a literal duplicate. Instead: design writes against **fictional** `ingestion_manifest` columns (`pipeline_name`, `status`, `completed_at`, `row_counts_json`) and **fictional** `ingestion_impacts` columns (`run_id`, `action`, `rowkey`, `prior_accession`) while ignoring the real schema at `migrations/001_pipeline_control_plane.py:53-109`. This is schema fiction, not column overlap. |
| 4 | Framework replacing existing protocol | CONFIRMED | Design presents `SourcePipeline` base class as new. Existing `scripts/pipeline/protocol.py:117-276` already defines `SourcePipeline`, `DirectWritePipeline`, `DerivedPipeline` protocols with manifest/impact/freshness contracts. Design replaces terminology instead of extending. |
| 5 | Concurrency check TOCTOU | CONFIRMED | Design specifies "409 Conflict when same pipeline running." Implementation at `admin_bp.py:267-283` runs `pgrep` and then `subprocess.Popen` as independent OS calls with no serialization. Two requests can pass the check before either child appears in the process table. |

Taken together, these five (plus the two Pass 2 surprises below) motivated the audit and justify the current pause on admin-refresh work.

### 9.2 Cross-doc contradictions

| # | Contradiction | Severity |
|---|---|---|
| 1 | `ENTITY_ARCHITECTURE.md:287-293` says Stage 5 dropped legacy tables on 2026-04-13; `MAINTENANCE.md:120-123` authorizes drop on/after 2026-05-09; prod still contains `fund_holdings` with fresh rows | BLOCK (auto-resolves with BLOCK-3 fix) |
| 2 | `ARCHITECTURE_REVIEW.md` describes Flask monolith with Phase 4 pending; live app is FastAPI with split routers per `REACT_MIGRATION.md:120-121` | MINOR |
| 3 | `docs/data_layers.md:92` reports 84.47% `fund_holdings_v2` entity coverage and 9 `data_freshness` rows; prod is 40.09% and 13 rows | MAJOR (auto-resolves with BLOCK-1 fix) |
| 4 | `Plans/admin_refresh_system_design.md` references `docs/data_sources.md`; file lives at `Plans/data_sources.md`, not under `docs/` | MINOR |
| 5 | `README_deploy.md` describes pure-Python deploy; `REACT_MIGRATION.md` makes React build a prerequisite | MINOR |
| 6 | `CLASSIFICATION_METHODOLOGY.md` frames coverage around 20,205 entities; prod MDM is 26,535 | MINOR |

### 9.3 Pass 2 production-critical surprises

Two findings surfaced beyond the six Pass 2 tasks:

**S-01 — Retired `fetch_nport.py` on admin allowlist.** `admin_bp.py:258-265` whitelists `'fetch_nport.py'` as user-runnable. The write batch that repopulated legacy `fund_holdings` on 2026-04-14 21:22 (22,030 rows across 13 funds, 6-second window) is consistent with a single admin click. Rolls up to BLOCK-3.

**S-02 — `add_last_refreshed_at.py` is a migration-tracking lie.** The migration ran on prod — 14,181 of 18,500 `entity_relationships` rows carry the column populated (76.8%) — but `schema_versions` was never stamped. Any audit or gate logic that reads `schema_versions` to decide "was this applied?" gets the wrong answer. Either the script is incomplete or the `INSERT INTO schema_versions` line was omitted. Rolls up to MAJOR-9.

---

## 10. Structural Fix Proposals

Three structural fixes were developed in Pass 2. Each remains a proposal, not an applied change. They are included in this synthesis document because they are ready to scope as engineering work and represent the non-obvious architectural moves this audit surfaced.

### 10.1 Decouple entity enrichment from promote (BLOCK-1 fix)

**Problem.** `_bulk_enrich_run` in `promote_nport.py:153-218` is run-scoped via `series_touched`. Rows from prior promotes whose `series_id` became resolvable later are never revisited.

**Proposal.**

1. Add `scripts/enrich_fund_holdings_v2.py` or extend `enrich_holdings.py` with a `fund_holdings_v2` branch. Standalone, idempotent job that runs the `_bulk_enrich_run` UPDATE over the entire set of NULL-entity_id series (not `series_touched`). Run after every entity MDM change (`promote_staging` completion hook) and as a nightly sweep.
2. Leave the existing `_bulk_enrich_run` in place as the per-run fast path; it is no longer the only enrichment surface.
3. The entity gate at `pipeline/shared.py:237-385` already routes unresolvable series to `pending_entity_resolution`; no change there. Add a visibility surface (admin panel) for series queued more than N days.

**Expected recovery.** 2025-10 and 2026-01 to ≥94% coverage on first run. 2025-11 / 2025-12 to ≥48% / 76% pending further MDM work on the unresolvable tail (587K to 1M rows of genuinely-pending series).

### 10.2 Extract canonical `mirror_manifest_and_impacts` + wrap promotes in transactions (BLOCK-2 fix)

**Problem.** Two independent implementations exist — one in `promote_nport.py:81-146`, one inline in `promote_13dg.py:203-269`. They have already drifted. The admin refresh design will produce a third. Neither site is wrapped in an enclosing transaction.

**Proposal.** Add one function to `scripts/pipeline/manifest.py`:

```python
def mirror_manifest_and_impacts(
    *,
    prod_con,
    staging_con,
    run_id,
    source_type,
    preserve_promoted=True,
):
    """Canonical staging→prod mirror of ingestion_manifest + ingestion_impacts
    for one (source_type, run_id). Returns (manifest_ids, impact_rows_copied)."""
```

Collapse both existing implementations to delegate to the helper. Land the extraction paired with an enclosing `BEGIN TRANSACTION` / `COMMIT` wrap on the full promote sequence in each script — the atomicity gap closes at the same moment the duplication closes. Extract-without-wrap would be a lift-and-shift that preserves the non-atomic semantics.

Regression surface: once landed, the admin refresh `SourcePipeline.run()` delegates here as a fourth use of the same helper, not a fourth reimplementation.

### 10.3 Admin refresh pre-restart rework (BLOCK-4 fix)

**Problem.** The design diverges from reality in four places simultaneously: schema fiction (four fictional columns, three renamed), 11-state lifecycle incompatible with 5-state `fetch_status` enum, Protocol-vs-ABC tension, and `parse()` purity inversion.

**Proposal.** Before the workstream restarts, produce:

1. One schema migration (008) — either add the fictional columns with the names the design uses, or edit the design to adopt the current names. Column-by-column delta table lives in Pass 2 §4a / §4b.
2. One decision doc — either expand `fetch_status` / `promote_status` enums to the 11-state model, or add a separate `run_status` column. The existing enums are load-bearing for the v2 promote scripts; changing them has knock-on effects.
3. One decision doc — `Protocol` vs `ABC`. Existing `pipeline/protocol.py:117-276` uses `typing.Protocol` with `@runtime_checkable`. Design uses `abc.ABC`. Test-double strategy, duck-typed dispatch, and existing registry usage all depend on the choice.
4. One decision doc — `parse()` purity. Current `parse()` is pure (no DB side effects); design's `parse()` writes staging. Six existing pipelines would need `parse()` refactored if the design wins. If purity wins, the design must move staging writes into a separate step.

Estimate: one focused session of refactor and decision-making before the base class can be written against reality.

---

## 11. Technical Debt Inventory

Findings below BLOCK that did not surface a structural fix proposal. This is the running punch-list. Items are grouped for batching.

### 11.1 Security batch

- **D-11 (MAJOR)** Admin token stored in browser `localStorage` (`admin.html:180-202`). Fix: HttpOnly session cookie, server-side session table, rotation endpoint.
- **C-11 (MAJOR)** Admin `/run_script` TOCTOU race (`admin_bp.py:267-283`). Fix: `fcntl.flock` on log file, or manifest-backed `fetch_status='fetching'` check-and-set inside a transaction.
- Secrets centralization: EDGAR identity inlined in 22+ scripts. Move to `scripts/config.py` single constant.

### 11.2 Observability batch

- **C-05 (MAJOR)** Five unlisted direct-to-prod writers — list in `pipeline_violations.md`, decide staging-or-exception per script.
- **P-05 / D-07 (MAJOR)** N-CEN and ADV outside `ingestion_manifest`. Add source_type rows plus per-run manifest inserts in `fetch_ncen.py` and `fetch_adv.py`.
- **P-04 (MAJOR)** Market `impact_id` race — audit every direct `INSERT INTO ingestion_impacts` that bypasses `manifest._next_id`.
- **P-02 (MAJOR)** ADV pipeline silent — no log, no freshness row. Add logging, stamp `data_freshness`.

### 11.3 Atomicity batch (follow-ons to BLOCK-2)

- **C-08 (MAJOR)** `compute_flows.py` destructive DROP+CTAS on `investor_flows` and `ticker_flow_stats`. Fix: stage-then-rename, or `CREATE OR REPLACE TABLE ... AS SELECT` single-statement.
- **MAJOR** `fetch_adv.py:247-249` DROP-before-CREATE on `adv_managers`. Fix: single `CREATE OR REPLACE TABLE` statement.
- **MAJOR** Migration 004 (`004_summary_by_parent_rollup_type.py:82-145`) RENAME → CREATE → INSERT → DROP without transaction. Kill mid-run leaves canonical table name absent. Fix: `BEGIN TRANSACTION` / `COMMIT` wrap.

### 11.4 Schema and migration hygiene

- **MAJOR** S-02 — `add_last_refreshed_at.py` ran but never stamped `schema_versions`. Fix: insert the row retroactively, or fix the migration to match docstring.
- **MINOR** Rollback paths are universally weak — none of the 8 migrations have scripted down-paths. Recovery is "restore backup," not "run down()."
- **MINOR** DM override replay skips NULL-target rows (migration 007 intentional). Worth a doc note for future readers.

### 11.5 Doc refresh batch (one pass covers all)

- DOC-01 through DOC-12 (minus DOC-07 and DOC-08 corrected by Codex). README, PHASE prompts, `README_deploy.md`, `write_path_risk_map.md`, `CLASSIFICATION_METHODOLOGY.md`, and the `scripts/api_*.py` architecture gap.
- DOC-11 auto-resolves with BLOCK-1 fix (refresh `data_layers.md:92` after backfill).
- Cross-doc contradiction 1 auto-resolves with BLOCK-3 fix (legacy table actually dropped).

### 11.6 Housekeeping

- R-01, R-02 — roadmap numeric drift (931 vs 928 exclusions, 5 vs 4 NULL-CIK overrides).
- O-02 — pin `edgartools` and `pdfplumber`.
- O-05 — investigate 2026-04-14 backup size shrinkage.
- O-08 — centralize UA strings.
- O-10 — log rotation policy.
- Stale worktrees and orphan branches cleanup.
- Untracked `Plans/` directory — commit to `docs/plans/` or gitignore.

---

## 12. Ordered Recommendations

Twenty items total. Severity reflects production impact. Sequence reflects dependency order and operational risk.

### 12.1 BLOCK — fix before next large promote or design restart

| # | Item | Fix summary | Effort |
|---|---|---|---|
| 1 | Remove `'fetch_nport.py'` from admin allowlist at `admin_bp.py:258-265` | One-line stop-the-bleeding. Legacy `fund_holdings` stops receiving writes immediately. Follow-on removal sequence in Pass 2 §2. | <1 hour |
| 2 | Entity-enrichment backfill job (§10.1) | Add standalone idempotent job; hook to `promote_staging` completion; schedule nightly. Expected 2025-10 and 2026-01 recover to ≥94%. | 1-2 days |
| 3 | Extract `mirror_manifest_and_impacts` helper + wrap promotes in transactions (§10.2) | One helper in `pipeline/manifest.py`; both promote scripts delegate; both wrap in `BEGIN`/`COMMIT` in the same commit. | 2-3 days |
| 4 | Admin refresh pre-restart rework (§10.3) | Migration 008 or design edits; enum decision; Protocol-vs-ABC decision; `parse()` purity decision. | 3-5 days |

### 12.2 MAJOR — fix before next session-close

| # | Item | Fix summary | Batch |
|---|---|---|---|
| 5 | Admin `/run_script` TOCTOU race | File lock or manifest-backed check-and-set | Security |
| 6 | Admin token in `localStorage` | HttpOnly cookie + session table + rotation endpoint | Security |
| 7 | `fetch_adv.py` DROP-before-CREATE | Single `CREATE OR REPLACE TABLE` statement | Atomicity |
| 8 | Migration 004 interruption risk | Wrap `004_summary_by_parent_rollup_type.py:82-145` in transaction | Atomicity |
| 9 | S-02 — `add_last_refreshed_at` not stamped | Insert `schema_versions` row; decide authoritative form | Schema |
| 10 | Five unlisted direct-to-prod writers | List in `pipeline_violations.md`; decide staging/exception per script | Observability |
| 11 | N-CEN and ADV outside `ingestion_manifest` | Add `source_type` rows; instrument both fetchers | Observability |
| 12 | Market `impact_id` race | Audit every direct `INSERT INTO ingestion_impacts` that bypasses `_next_id` | Observability |
| 13 | Stage 5 cross-doc contradiction (auto-resolves with #1) | Align `ENTITY_ARCHITECTURE.md` and `MAINTENANCE.md` on one drop date | Docs |

### 12.3 MINOR — punch-list

| # | Item | Fix summary |
|---|---|---|
| 14 | R-01 / R-02 | Reconcile 931 vs 928 exclusions and 5 vs 4 NULL-CIK overrides in roadmap |
| 15 | O-02 | Pin `edgartools` and `pdfplumber` in `requirements.txt` (Flask correctly removed) |
| 16 | DOC-01 through DOC-12 minus DOC-07/08 | One docs pass covers README, PHASE prompts, deploy, write-path risk map, classification methodology, Blueprint architecture |
| 17 | DOC-11 | Auto-resolves with BLOCK-1 — refresh `data_layers.md:92` after backfill |
| 18 | O-08 | Centralize UA strings in `scripts/config.py` |
| 19 | `flow_intensity_total` formula | Docstring in `compute_flows.py` plus mention in `docs/data_layers.md` |
| 20 | Migration 007 NULL-target replay handling | Doc note that this is intentional |

### 12.4 Sequencing guidance

**Today:** Item 1. One-line change, stops legacy-table regression.

**This week:** Items 2, 3. Entity-enrichment backfill and promote atomicity are load-bearing for all subsequent N-PORT work. Both block further large-scale promotes.

**Next 1-2 weeks:** Item 4 as a single focused session, then items 5-13 as two parallel tracks (security + observability) plus the atomicity batch as one push.

**Ongoing:** Items 14-20 as engineering bandwidth allows. None blocks other work.

**Before the next wide audit (2026-10):** All BLOCK plus all MAJOR items resolved. MINOR items form the running punch-list. The rotating audits (May through October, per the separate schedule) cover surfaces not reached here — frontend, MDM correctness depth, data math, amendment logic, security/DR, performance.

---

*End of audit. Evidence artifacts remain in `docs/`: `SYSTEM_ATLAS_2026_04_17.md` (Pass 1), `CODEX_REVIEW_2026_04_17.md` (Reviewer 2), `SYSTEM_PASS2_2026_04_17.md` (Pass 2). This document supersedes them for decision-making.*
