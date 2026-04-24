# Phantom `other_managers` table — decision

_Session: `phantom-other-managers-decision` (2026-04-23). Branch: `phantom-other-managers-decision`._

## TL;DR

**The phantom is already gone.** The decision called for by `2026-04-19-rewrite-load-13f.md §6.4` was effectively taken during the same rewrite block: **Option A — add writer to `load_13f.py`** — was committed at `14a5152` (2026-04-19), validated in Phase 2 (`dd1d382`), and applied to prod in Phase 4 (`a58c107`). At HEAD `f3c7183` the writer is present, active, and producing the observed 15,405 rows. The `registry.py:174` claim naming `load_13f.py` as owner is now **true**, not phantom.

This doc records the decision retroactively, cites the evidence, and cleans up the one stale tracker entry (`REMEDIATION_PLAN.md:403`) that still treats the question as open. No new code changes are required in this session.

Scope here is investigation + doc only. Read-only on prod DB.

---

## Phase 1 — Inventory

### Prod — `data/13f.duckdb` (read-only at HEAD `f3c7183`)

| Property | Value |
|---|---|
| Table exists | yes (`BASE TABLE`) |
| Row count | **15,405** |
| Columns | 8, all `VARCHAR`, all nullable |
| Indexes / constraints | none (no PK, FK, or index) |
| Timestamp column | none (no provenance column) |
| Most recent write | cannot be dated from data; see §5.3 |

Schema (prod + staging identical):

```
accession_number      VARCHAR
sequence_number       VARCHAR
other_cik             VARCHAR
form13f_file_number   VARCHAR
crd_number            VARCHAR
sec_file_number       VARCHAR
name                  VARCHAR
quarter               VARCHAR
```

Sample rows (`LIMIT 10`, prod):

```
0002001900-25-000018 | 2  | 0001802647 | 028-20154 | 000107975 | 801-57265  | Orion Portfolio Solutions, LLC | 2025Q1
0002001900-25-000018 | 11 | 0001360533 | 028-11877 | 000107975 | 801-57265  | Brinker Capital Investments, LLC | 2025Q1
0002001900-25-000018 | 7  | 0001345576 | 028-11543 | 000112266 | 801-62058  | Advisors Capital Management, LLC | 2025Q1
0002001900-25-000018 | 5  | NULL       | NULL      | 000301761 | 801-16970  | VISE AI Advisors | 2025Q1
0002001900-25-000017 | 12 | NULL       | NULL      | 000131825 | 801-69664  | Greenrock Research, Inc. | 2025Q1
0002001900-25-000017 | 2  | 0001802647 | 028-20154 | 000107975 | 801-57265  | Orion Portfolio Solutions, LLC | 2025Q1
0002001900-25-000017 | 11 | 0001360533 | 028-11877 | 000107975 | 801-57265  | Brinker Capital Investments, LLC | 2025Q1
0002001900-25-000017 | 8  | 0001703301 | 028-18017 | 000171992 | 801-80178  | SpiderRock Advisors, LLC | 2025Q1
0002001900-25-000017 | 7  | 0001345576 | 028-11543 | 000112266 | 801-62058  | Advisors Capital Management, LLC | 2025Q1
0002001900-25-000017 | 5  | NULL       | NULL      | 000301761 | 801-116970 | VISE AI Advisors | 2025Q1
```

### Staging — `data/13f_staging.duckdb`

Same schema. Same row count: **15,405**. Sample `LIMIT 10` is byte-for-byte identical to prod. Staging mirrors prod because `scripts/load_13f.py` honors `--staging` and the Phase 4 prod apply also back-populated staging from the same TSV source.

### Row-count parity vs source TSV (from `2026-04-19-rewrite-load-13f.md §9.4`)

| Quarter | `other_managers` rows | `OTHERMANAGER2.tsv` rows | Match |
|---|---:|---:|---|
| 2025Q1 | 3,811 | 3,811 | exact |
| 2025Q2 | 3,910 | 3,910 | exact |
| 2025Q3 | 3,759 | 3,759 | exact |
| 2025Q4 | 3,925 | 3,925 | exact |
| **Total** | **15,405** | **15,405** | **exact** |

Row-count parity with the source TSV bundle is preserved at HEAD — the writer is in place and the table is not drifting.

---

## Phase 2 — Writer inventory

Classification of every `other_managers` hit in the codebase (19 files). Only lines that actually mutate the table are classified as writers.

### Writers (active)

| Location | Line(s) | Role |
|---|---|---|
| [scripts/load_13f.py](scripts/load_13f.py:109) | 107–124 | **Primary writer.** `INSERT INTO other_managers SELECT … FROM read_csv_auto('OTHERMANAGER2.tsv')`, one pass per quarter. Committed at `14a5152` (2026-04-19). |
| [scripts/load_13f.py](scripts/load_13f.py:137) | 137 | `DROP TABLE IF EXISTS other_managers` inside `create_staging_tables()` — write-path preparation when rebuilding from scratch. |
| [scripts/load_13f.py](scripts/load_13f.py) | — | Also: `create_staging_tables()` CREATE; `prepare_incremental()` `DELETE … WHERE quarter=?` for `--quarter` reloads; `print_summary()` row-count line; freshness stamp. Full set landed in `14a5152`. |
| [scripts/load_13f_v2.py](scripts/load_13f_v2.py:428) | 189–195, 318–328, 428, 472–487, 715–726, 739–746 | **v2 writer (staging-pattern).** Creates `stg_13f_other_managers` in staging, populates it from `OTHERMANAGER2.tsv` in `parse()`, promotes into prod `other_managers` with NOT-EXISTS dedup on `(accession_number, sequence_number)` inside the holdings_v2 promote transaction, then drops the staging table. Will replace `load_13f.py` under `mig-12`. Committed at `37b4c9c`. |

Both writers load the same 8-column shape (`accession_number, sequence_number, other_cik, form13f_file_number, crd_number, sec_file_number, name, quarter`) from the same source file (`OTHERMANAGER2.tsv`).

### Writers (test-only)

| Location | Line(s) | Role |
|---|---|---|
| [tests/pipeline/test_load_13f_v2.py](tests/pipeline/test_load_13f_v2.py:182) | 182–197, 360–376, 467–473 | `DDL_OTHER_MANAGERS` fixture creates a scratch `other_managers` in the test DuckDB; `test_parse_emits_staging_reference_tables` asserts `parse()` populates `stg_13f_other_managers`; end-to-end test asserts `other_managers` row count after `promote()`. |

### Non-writer references (metadata / scrub lists)

| Location | Line(s) | Role |
|---|---|---|
| [scripts/pipeline/registry.py](scripts/pipeline/registry.py:174) | 174–177 | `DatasetSpec("other_managers", layer=3, owner="scripts/load_13f.py", promote_strategy="rebuild")`. Declarative ownership claim. **True at HEAD.** |
| [scripts/inf39_rebuild_staging.py](scripts/inf39_rebuild_staging.py:54) | 54 | Entry in the table-name list used to rebuild staging from prod — not an independent writer, just a reference tables re-seed. |
| [scripts/pipeline/validate_schema_parity.py](scripts/pipeline/validate_schema_parity.py:67) | 67 | Entry in the list of tables to check prod↔staging schema parity on. |

### Docs that name the table (reference-only)

`docs/findings/2026-04-19-rewrite-load-13f.md`, `docs/REMEDIATION_PLAN.md`, `docs/pipeline_violations.md`, `docs/data_layers.md`, `docs/canonical_ddl.md`, `docs/findings/mig-09-p0-findings.md`, `docs/SCHEMA_DIFF_PHASE_0_5_REBUILD_DRY_RUN.sql`, `docs/SCHEMA_DIFF_PHASE_1_REBUILD_LOG.md`, `docs/findings/2026-04-19-block-schema-diff.md`, `archive/docs/reports/rewrite_load_13f_phase2_20260419_071500.md`, `docs/findings/2026-04-19-precheck-load-13f-liveness.md`, `Makefile`. All reference-only.

### Retired scripts / migrations / SQL

`scripts/retired/` (build_cusip_legacy.py, fetch_nport.py, unify_positions.py): **zero hits.** `scripts/migrations/` (001–007 plus add_last_refreshed_at.py): **zero hits** — the table has no CREATE-TABLE migration; it is created on first run by `create_staging_tables()` in `load_13f.py`. No standalone SQL files in repo reference it.

---

## Phase 3 — Reader inventory

Hunt performed with the same grep across `scripts/`, `tests/`, `web/` plus the docs tree. Classification of every non-writer hit:

| Location | Line(s) | Kind | Active / Legacy | Handling of empty result |
|---|---|---|---|---|
| [notebooks/research.ipynb](notebooks/research.ipynb) | 21 | Static `DESCRIBE` enumeration of available tables | Legacy / ad hoc — not part of a pipeline | N/A (explorer notebook) |
| [scripts/pipeline/validate_schema_parity.py](scripts/pipeline/validate_schema_parity.py) | 67 | Infrastructure — schema & row-count parity check between prod and staging | Active (ops tooling) | Fails loudly on schema or row-count drift; would not tolerate empty |

**`web/`: zero hits.** No API endpoint, no React component, no `queries.py` function, no build script (`build_managers.py`, `build_entities.py`, `build_shares_history.py`, `build_summaries.py`, `fetch_13dg*.py`, `fetch_adv.py`, `resolve_names.py`, `enrich_tickers.py`, `auto_resolve.py`, `backfill_manager_types.py`, `approve_overrides.py`, `queries.py`) references `other_managers`.

**Reader surface: effectively none.** The only "active" reader is ops-infrastructure parity validation — a reader of shape, not of content.

---

## Phase 4 — Cross-reference with REWRITE_LOAD_13F §6.4 + §9

`docs/findings/2026-04-19-rewrite-load-13f.md` covered this territory exhaustively:

- **§0 (Phase 0 executive summary, finding 3)** flagged the phantom-owner drift: registry (`registry.py:174`) and canonical DDL claimed `load_13f.py` owned the table, but the script had no INSERT/CREATE.
- **§6.4** posed the decision: (A) add write path, (B) reassign ownership, or (C) retire.
- **§9** (Phase 0 addendum, commit `0a7ae35`) ran a ghost-data investigation: full git history (all branches) showed **no committed writer ever existed** — data was materialized by an out-of-band REPL/one-shot load. Row-count parity with the TSV was exact. Zero live readers. Recommendation: **Option A.**
- **§9.9** sized Phase 1 scope impact at ~25 LOC.

Implementation landed in the same block:

| Commit | Date | What |
|---|---|---|
| `46f0ca8` | 2026-04-19 | docs — phase 0 broad audit findings |
| `0a7ae35` | 2026-04-19 | docs — phase 0 addendum (§9 ghost investigation) |
| `05427c7` | 2026-04-19 | refactor — retire dead holdings DROP+CTAS |
| `8e7d5cb` | 2026-04-19 | feat — CHECKPOINT / data_freshness / --dry-run / fail-fast / flush |
| **`14a5152`** | **2026-04-19** | **feat(load_13f): add OTHERMANAGER2 loader, materialize `other_managers`** — 48 insertions, 9 deletions in `scripts/load_13f.py` |
| `dd1d382` | 2026-04-19 | chore — phase 2 staging validation, gates PASS |
| `a58c107` | 2026-04-19 | chore — **phase 4 prod apply: 43,358 / 13,540,608 / 43,358 / 43,358 / 40,140 / 15,405** (last figure = `other_managers` row count, matches current prod exactly) |
| `37b4c9c` | 2026-04-20+ | p2-05 — `load_13f_v2.py` first SourcePipeline subclass, carries the writer forward to the rewrite |
| `499e120` | — | docs(pipeline_violations) — mark Batch 3 REWRITE queue CLEARED (build_shares_history, load_13f, build_managers) |

`docs/pipeline_violations.md:189–193` already records the fix:

> `OTHERMANAGER2` loader added (Phase 0 addendum, commit `0a7ae35`): materialized 15,405 `other_managers` rows from ghost data that the legacy script silently dropped on the floor. Fix shipped in the same rewrite at commit `14a5152`.

**The decision is closed in code and partially closed in docs.**

---

## Phase 5 — Recommendation

### Recommendation: **Option A (add writer) — confirmed retroactively. No new implementation work.**

Evidence (restated, tight):

1. **Writer is live in code.** `scripts/load_13f.py:107–124` inserts `OTHERMANAGER2.tsv` into `other_managers` one quarter at a time. Invoked by `Makefile:111` (`make load_13f …`).
2. **Writer is carried into the rewrite.** `scripts/load_13f_v2.py` populates `stg_13f_other_managers` in `parse()` and promotes into `other_managers` inside the holdings_v2 promote transaction, with `(accession_number, sequence_number)` NOT-EXISTS dedup.
3. **Data is exact.** Prod = staging = 15,405 rows; per-quarter row counts match `OTHERMANAGER2.tsv` byte-for-byte.
4. **Registry claim is true.** `registry.py:174` names `load_13f.py` as owner, which matches reality at HEAD.
5. **Readers are effectively zero.** Only ops parity infra touches it. No consumer regression surface.
6. **Prior session already reached and implemented this decision** (Phase 0 addendum → Phase 2 staging gates → Phase 4 prod apply).

Options B and C are rejected for reasons that already hold:

- **Option B (reassign ownership) is unnecessary.** There is no competing script writing it; `load_13f.py` is the only committed writer, and `load_13f_v2.py` is its rewrite successor on the same ownership line.
- **Option C (retire the table) is rejected.** The original §9.7 rationale still holds: the data is a legitimate SEC filing artifact (co-filing manager cross-reference, part of the 13F schema bundle), row-count parity with the TSV is exact, cost of maintenance is tiny (single INSERT inside an existing loader), and retirement now would require coordinated retirement of the registry spec, the schema-parity list, the v2 rewrite path, and the test fixture. Dropping a populated reference table to then possibly need it for analytical/notebook readers (the kind of reader that wouldn't show up in a grep) is the wrong trade.

### Residual action (tracker-only, not code)

One stale entry:

- `docs/REMEDIATION_PLAN.md:403` still reads "Phantom `other_managers` table decision (REWRITE_LOAD_13F §6.4): add write path, reassign ownership, or retire." This bullet should be removed or moved to a "completed" section. Implemented in this PR.

Optionally link this decision doc from `2026-04-19-rewrite-load-13f.md §6.4` so a future reader pulling on that thread lands here directly. Not strictly required — the §9 addendum already closes the loop — so held for the follow-on session to batch with any other REWRITE cross-refs.

---

## Phase 6 — Follow-on scope stub

Pick up in a separate session if needed:

- **Docs cleanup (tracker hygiene).** Remove or re-file `REMEDIATION_PLAN.md:403`. Covered in this PR; listed here for completeness.
- **Cross-link (optional, low-priority).** Add a one-line pointer from `2026-04-19-rewrite-load-13f.md §6.4` / §9.9 to `docs/findings/phantom-other-managers-decision.md`.
- **`mig-12` carry-forward (tracked elsewhere).** The `load_13f_v2` rewrite (REMEDIATION_PLAN.md:401) will become the long-term owner of `other_managers` when it retires `load_13f.py`. The v2 writer is already written and tested (`tests/pipeline/test_load_13f_v2.py`). No incremental work needed here; verify `other_managers` is covered in the `mig-12` cutover checklist when that session runs.
- **Schema hardening (deferred, optional).** Table has no PK, no index, no provenance column. If a reader ever materializes that filters by `(accession_number, sequence_number)` hot, revisit. Until a reader shows up, leave it as-is.

No further investigation required. No prod data change required. No writer change required.

---

## Appendix — session log

- Read-only DuckDB queries against `data/13f.duckdb` and `data/13f_staging.duckdb` for schema, row counts, and samples.
- `Grep` across `scripts/`, `tests/`, `web/`, `docs/`, `notebooks/`, `Makefile`, `scripts/retired/`, `scripts/migrations/`.
- `git log --all -S` and `--grep` on `other_managers`, `OTHERMANAGER2`, `INSERT INTO other_managers`, `CREATE TABLE other_managers`.
- No mutations, no merges, branch `phantom-other-managers-decision` pushed for review only.
