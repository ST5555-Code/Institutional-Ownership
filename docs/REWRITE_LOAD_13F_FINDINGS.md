# REWRITE load_13f.py — Phase 0 Findings

_Branch: `rewrite-load-13f`, off main `34710d1`. Phase 0 is read-only._

## Scope

Full REWRITE audit of `scripts/load_13f.py` following Precheck2's LIVE
classification (`docs/PRECHECK_LOAD_13F_LIVENESS_20260419.md`, commit
`cdf2cae`).

**Broad audit** — not just the legacy `holdings` write retirement. All
tables owned by `load_13f.py` per `scripts/pipeline/registry.py` are
examined for drift, DDL coherence, downstream coupling, and retrofit
gaps (CHECKPOINT, `data_freshness`, `--dry-run`, fail-fast on missing
inputs, flush on prints). Precedent: BLOCK-SECURITIES-DATA-AUDIT caught
a class of corruption that would have propagated if scoped narrowly.

Read-only throughout: prod `data/13f.duckdb` opened `read_only=True`,
no code edits to `scripts/load_13f.py`, Phase 0 commits are docs only.

---

## Headline

1. `load_13f.py` at HEAD is LIVE and produces five live tables
   (`raw_submissions`, `raw_infotable`, `raw_coverpage`, `filings`,
   `filings_deduped`). DDL in prod matches the script's CREATE shapes
   on all five (no column-presence drift).
2. The legacy `holdings` DROP+CTAS at `scripts/load_13f.py:220-287`
   targets a table that **no longer exists in prod** (dropped during
   Stage 5). The DROP IF EXISTS is a no-op; the CREATE writes a dead
   copy each run. Retire confirmed — no live readers of `holdings` as
   a TABLE from the load itself. (Many scripts still reference
   `holdings` via SELECT; those are tracked in the standing `holdings`
   → `holdings_v2` repoint effort, not in this block.)
3. **Surprise finding — phantom owner for `other_managers`.** The
   registry (`scripts/pipeline/registry.py:174`) and canonical DDL
   doc (`docs/canonical_ddl.md:40,326`) name `load_13f.py` as owner of
   `other_managers`. The prod table has 15,405 rows across 2025Q1–Q4
   (steady ~3.9k/quarter) and the SEC `OTHERMANAGER.tsv` /
   `OTHERMANAGER2.tsv` source files are present under
   `data/extracted/<quarter>/`. However `load_13f.py` at HEAD contains
   **no INSERT or CREATE against `other_managers`** (grep confirmed).
   Either a prior version wrote it and the path was deleted, or it is
   populated out-of-band. This is registry/code drift beyond the
   originally scoped surface and warrants decision before Phase 1.
   See §3 and §6.
4. All five live tables lack `data_freshness` rows (retrofit gap
   confirmed) and the script contains no CHECKPOINT, no flush=True on
   prints, no `--dry-run`, and silent-continue on missing TSV.
5. `--staging` flag already exists (line 368) — Precheck2's bullet
   listing it as missing is stale. `--dry-run` is the only flag still
   missing.
6. `filings_deduped` has **zero dupes** on `(cik, quarter)` empirically
   but **no formal PK/UNIQUE** — classic INF28 empirical-unique-
   not-declared pattern. Same shape on `raw_submissions`
   (`accession_number` is empirically unique, not declared).

No corruption or value drift detected. Natural-key uniqueness holds
everywhere it should. The DROP+CTAS pattern is self-healing: every
full run rewrites all five live tables from the same raw inputs.

---

## 1. Code structure review

### 1.1 Entry points and flow

| Element | File:line | Notes |
|---|---|---|
| `main()` | `scripts/load_13f.py:311` | entry; wrapped by `crash_handler("load_13f")` at `:373` |
| `--quarter` | `:367` | incremental mode; preserves other quarters in raw tables |
| `--staging` | `:368` | already exists; calls `set_staging_mode(True)` |
| `--dry-run` | — | **missing** |
| `load_quarter(con, quarter)` | `:28-105` | loads 1 quarter of 3 TSVs |
| `create_staging_tables(con)` | `:108-158` | DROP+CREATE the 3 raw tables |
| `prepare_incremental(con, quarter)` | `:161-177` | for `--quarter` mode; DELETE rows for target quarter only |
| `build_filings(con)` | `:180-217` | DROP+CTAS `filings` and `filings_deduped` |
| `build_holdings(con)` | `:220-287` | DROP+CTAS `holdings` (dead — table absent in prod) |
| `print_summary(con)` | `:290-308` | reads all six tables including `holdings` |

### 1.2 Input sources

- `SUBMISSION.tsv`, `INFOTABLE.tsv`, `COVERPAGE.tsv` under
  `data/extracted/<quarter>/` (`:30-33`).
- `OTHERMANAGER.tsv`, `OTHERMANAGER2.tsv`, `SIGNATURE.tsv`,
  `SUMMARYPAGE.tsv` also present in those directories but **never
  read** by `load_13f.py`.
- Missing-file handling: `:35-38` logs `WARNING: Missing {p}` and
  returns `(0, 0)` — no raise, no non-zero exit. §5 violation.

### 1.3 Write operations per table

| Table | CREATE shape | File:line | Source |
|---|---|---|---|
| `raw_submissions` | `DROP` + `CREATE TABLE` (full mode) | `:110,114-123` | `read_csv_auto(SUBMISSION.tsv)` then `INSERT` at `:41` |
| `raw_infotable` | `DROP` + `CREATE TABLE` | `:111,125-143` | `read_csv_auto(INFOTABLE.tsv)` then `INSERT` at `:58` |
| `raw_coverpage` | `DROP` + `CREATE TABLE` | `:112,145-158` | `read_csv_auto(COVERPAGE.tsv)` then `INSERT` at `:84` |
| `filings` | `DROP` + `CREATE TABLE AS` | `:182-197` | raw_submissions LEFT JOIN raw_coverpage on accession_number |
| `filings_deduped` | `DROP` + `CREATE TABLE AS` | `:200-212` | `filings` ranked by `(amended DESC, filed_date DESC)` per `(cik, quarter)`, kept rn=1 |
| `holdings` (DEAD) | `DROP` + `CREATE TABLE AS` | `:222-284` | `raw_infotable` JOIN `filings_deduped` — table does not exist in prod |

No CHECKPOINT calls anywhere (grep confirmed). No `register_dataset` or
`data_freshness` writes. No `flush=True` on any `print()`.

### 1.4 Read operations (internal only)

Grep inside `load_13f.py`: reads exist only for COUNT(*) progress
output (`:54,80,101,214,215,286,297,304`). No external-table reads for
joins or lookups.

### 1.5 Error handling

Only one silent-continue site: `:37` missing-TSV warning (§5
violation). The crash_handler wrapper at `:373` covers the rest.

### 1.6 Flags

| Flag | Present? |
|---|---|
| `--quarter` | yes (`:367`) |
| `--staging` | yes (`:368`) |
| `--dry-run` / `--apply` | **no** (§9 violation) |

---

## 2. DDL coherence check per table

Queried prod `DESCRIBE`. For each of the five live tables, compared the
column list against the script's `CREATE TABLE` / `CREATE TABLE AS`.

| Table | Script columns | Prod columns | Drift |
|---|---:|---:|---|
| `raw_submissions` | 6 | 6 | **aligned** |
| `raw_infotable` | 15 | 15 | **aligned** |
| `raw_coverpage` | 10 | 10 | **aligned** |
| `filings` | 9 | 9 | **aligned** |
| `filings_deduped` | 9 | 9 | **aligned** |
| `holdings` | (script: 23 cols) | **absent** | DROP IF EXISTS no-op, CREATE writes dead table |

No PK, UNIQUE, NOT NULL, or FK constraints declared on any of the six
tables — standard INF28 laxness. Natural keys:

- `raw_submissions.accession_number` — 0 dupes empirically. Not declared.
- `raw_coverpage.accession_number` — 1:1 with raw_submissions. Not declared.
- `raw_infotable` — natural key `(accession_number, <row_seq>)` unclear;
  there is no row-sequence column carried through; dedup relies on
  downstream quirks.
- `filings.accession_number` — 1:1 with raw_submissions (43,358 each).
  Not declared.
- `filings_deduped.(cik, quarter)` — 0 dupes empirically. Not declared.
  This is the dedup target; PK/UNIQUE would be a clean retrofit.

---

## 3. Downstream readers survey

Scanned `scripts/` (excluding `scripts/retired/**`) for
`FROM|JOIN <table>`:

| Table | Live readers | Dead readers | Notes |
|---|---:|---:|---|
| `raw_submissions` | 0 | 0 | read only inside `load_13f.py` |
| `raw_infotable` | 0 | 0 | read only inside `load_13f.py` |
| `raw_coverpage` | 0 | 0 | read only inside `load_13f.py` |
| `filings` | 2 | 0 | `api_register.py:252,258` (Register tab) |
| `filings_deduped` | 4 | 0 | `build_managers.py:227,298,501`; `fetch_13dg_v2.py:113` |
| `holdings` | many | | table is absent in prod; every reader errors. Tracked under the standing `holdings` → `holdings_v2` repoint effort (OUT OF SCOPE for this block). Representative: `validate_phase4.py`, `fetch_13dg.py`, `auto_resolve.py`, `backfill_manager_types.py`, `resolve_names.py`, `enrich_tickers.py`, `approve_overrides.py`, `queries.py`. |
| `other_managers` | 0 | 0 | no external reader found |

The `holdings` hits are pre-existing debt, not caused by this block.
Confirmed: the legacy CTAS has **no reader dependency** (there is no
reader relying on `load_13f.py` producing that table specifically — all
those readers assume a table that no longer exists, period). Safe to
retire the write without further cleanup in this block.

---

## 4. Data quantification against prod

`data/13f.duckdb` opened read-only.

| Table | Rows | Quarters | Natural-key dupes | Notes |
|---|---:|---|---:|---|
| `raw_submissions` | 43,358 | 2025Q1–Q4 (10,765 / 10,799 / 10,422 / 11,372) | 0 on `accession_number` | |
| `raw_infotable` | 13,540,608 | same 4 | — | large fact table |
| `raw_coverpage` | 43,358 | same 4 | 0 on `accession_number` | 1:1 with raw_submissions |
| `filings` | 43,358 | same 4 | **1,277 on (cik,quarter)** | expected pre-dedup; 2.9% amended-filing overlap |
| `filings_deduped` | 40,140 | same 4 | **0 on (cik,quarter)** | dedup target |
| `holdings` | **ABSENT** | — | — | dropped Stage 5 |
| `other_managers` | 15,405 | 2025Q1 3,811 / Q2 3,910 / Q3 3,759 / Q4 3,925 | — | populated but not by this script |

Dedup ratio: `filings_deduped / filings = 40,140 / 43,358 = 92.6%` —
consistent with ~7.4% amended-filing shrinkage. Stable across quarters.

Max `filing_date` / `filed_date` = `31-OCT-2025`. Freshness inferred
from data only — no `data_freshness` row exists for any load_13f table
(verified by `SELECT table_name FROM data_freshness`).

---

## 5. DROP+CTAS pattern implications

1. **No incremental load for L3**. `--quarter` preserves other quarters'
   rows in the three raw tables (via `prepare_incremental` at `:161`),
   but `build_filings` and `build_holdings` always DROP+CTAS. Run is
   idempotent only at the whole-L3-rebuild granularity.
2. **No FK references to these tables** (audit: no `REFERENCES` to
   `filings`, `filings_deduped`, or raw_* anywhere under `scripts/`).
   Row-position identity not cached by downstream readers (all downstream
   joins use `accession_number` or `cik`+`quarter`, stable values).
3. **Stale window**: seconds. On a warm DuckDB, DROP+CTAS of
   `filings` (43k rows) and `filings_deduped` (40k rows) is sub-second.
   `holdings` (formerly ~13M rows) was minutes but is now absent.
4. **Staging compatibility**: `--staging` already exists. DROP+CTAS is
   the standard L3 rebuild shape per `pipeline/registry.py`
   (`promote_strategy="rebuild"` for all five live tables). Compatible
   with the INF1 staging workflow: sync → diff → promote.
5. **CHECKPOINT absence**: crash mid-run between raw load and filings
   build (or between two quarters in full mode) leaves the DB with raw
   data persisted only if DuckDB's WAL has auto-checkpointed. Retrofit:
   explicit `CHECKPOINT` after each of (a) each quarter's raw load,
   (b) `build_filings`, (c) end of main.

---

## 6. Proposed rewrite surface

### 6.1 Retire dead holdings write

Delete `build_holdings()` (`:220-287`), delete `holdings` mentions in
`print_summary` (`:293,303-307`), delete the `holdings_count` print at
`:354-356`. No reader impact (table absent in prod; existing readers
error today, independently of this change).

### 6.2 DROP+CTAS: keep for five live tables

Full reload semantics are intentional (TSVs are complete quarterly
snapshots from EDGAR, not deltas) and downstream assumptions are key-
based, not row-position. Keep DROP+CTAS for `filings` and
`filings_deduped`. Raw tables already support `--quarter` incremental.

Alternative considered (UPSERT on natural key): adds machinery without
a correctness or perf win at current scale (43k filings, 13M infotable
rows — sub-second rebuild). Defer unless pipeline scale changes.

### 6.3 Retrofits

| # | Retrofit | Site | Detail |
|---|---|---|---|
| R1 | `CHECKPOINT` after each phase | end of `load_quarter`, end of `build_filings`, end of `main` | per `docs/PROCESS_RULES.md` §1 |
| R2 | `data_freshness` rows for all five live tables | after each write completes | use `scripts/pipeline/freshness.py` helper |
| R3 | `--dry-run` flag | `argparse` block + early return before any write | §9 |
| R4 | Fail-fast on missing TSV | replace `:37` WARN+return with `raise FileNotFoundError` | §5 |
| R5 | `flush=True` on every `print()` | all 20+ print sites | matches pipeline rules |
| R6 | Parameterize quarter in f-string INSERTs | `:41-52`, `:58-78`, `:84-99` | current f-string is safe (values from config), but prepared statements are cleaner |

### 6.4 Phantom `other_managers` owner — decision required

Prod has 15,405 rows across 2025Q1–Q4; source TSVs
(`OTHERMANAGER.tsv`, `OTHERMANAGER2.tsv`) exist; schema matches;
registry and canonical DDL claim `load_13f.py` owns it — but the
script has no write path for it. Three options:

- **(A) Add write path.** Extend `load_quarter` to also load
  `OTHERMANAGER.tsv` / `OTHERMANAGER2.tsv` into `other_managers`
  (matching the 8-column prod schema). Preserves registry claim;
  closes silent write gap.
- **(B) Reassign ownership.** If an out-of-band script is the real
  writer, identify it (git history shows `load_13f.py` was last
  touched at `88d01d2`, pre-registry), update `registry.py:174` and
  `canonical_ddl.md`, leave `load_13f.py` as-is.
- **(C) Retire the table.** No live readers found. If the 15,405 rows
  are not used downstream, drop the table.

Recommended: (A) during Phase 1 if the OTHERMANAGER source is
authoritative (SEC publishes both TSVs in the 13F bundle). Smallest
scope change; closes the registry claim cleanly. Verify no external
out-of-band writer first.

### 6.5 Sequencing and dependencies

- **Blocks** `build_managers.py` REWRITE completion — that script reads
  `filings_deduped` three times (`:227,298,501`). No code-level change
  expected (column shape preserved), but the rewrite block's CHECKPOINT
  + data_freshness retrofits make the upstream deterministic.
- **Does not block** `api_register.py` (read-only against `filings`,
  stable columns).
- Suggest ordering: `load_13f` REWRITE → `build_managers` REWRITE →
  any `holdings` → `holdings_v2` consumer repoint.

### 6.6 Test plan

Phase 1 validation, in order:

1. `--dry-run` smoke: no DB writes, prints plan.
2. Staging run against `data/13f_staging.duckdb` — full `QUARTERS`
   load. Compare row counts vs prod within ±0.1%:
   - `raw_submissions` 43,358, `raw_coverpage` 43,358,
     `raw_infotable` 13,540,608, `filings` 43,358,
     `filings_deduped` 40,140.
3. Spot-check 10 filings (random sample of accession numbers) against
   SEC EDGAR — CIK, filing_date, amendment flag, manager name.
4. Natural-key sanity: `filings_deduped.(cik, quarter)` 0 dupes;
   `raw_submissions.accession_number` 0 dupes.
5. Downstream smoke:
   - `api_register.py` Register tab loads (filings read).
   - `build_managers.py --dry-run` completes (filings_deduped read).
   - `fetch_13dg_v2.py` can list filings_deduped CIKs.
6. If option (A) is chosen for `other_managers`: row count vs prod
   ±1%; schema match; no regression in 15,405-row baseline.
7. `data_freshness` rows present for all five (or six, if A) tables
   post-run.

---

## 7. Out of scope (flagged)

- **Makefile `quarterly-update` coverage gap.** `make quarterly-update`
  omits `load_13f.py` entirely — coverage gap flagged by Precheck2 §4.
  Track as `BLOCK-QUARTELY-UPDATE-INTEGRITY`.
- **`scripts/update.py` stale references.** Calls retired
  `fetch_nport.py` and missing `unify_positions.py`. Track separately.
- **Repoint of `holdings` readers to `holdings_v2`.** Pre-existing debt
  (~18 reader sites). Tracked under the standing `holdings` →
  `holdings_v2` effort.

---

## 8. Guardrail assessment

Phase 0 prompt lists stop conditions. None triggered:

- No corruption of live tables. Row counts, natural-key uniqueness,
  and dedup ratio all within expectation.
- `filings` 1,277 dupes on `(cik,quarter)` is expected pre-dedup
  (amendments); `filings_deduped` is 0 dupes (dedup works).
- `holdings` absent in prod confirms Stage 5 drop; write retirement is
  a no-op from prod's perspective.

The `other_managers` phantom-owner finding is drift beyond original
scope but is a **missing write**, not corruption — prod values stand;
they just have an unknown provenance. Decision required in Phase 1
(§6.4), not a stop condition.

Proceeding to Phase 1 on sign-off.
