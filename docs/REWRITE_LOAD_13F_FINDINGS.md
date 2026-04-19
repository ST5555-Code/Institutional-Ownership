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

---

## 9. Addendum — `other_managers` ghost data investigation

Follow-up read-only investigation. Hypothesis entering: an earlier
iteration of `load_13f.py` (or a sibling script) wrote `other_managers`
and the path was removed or refactored out, leaving the registry claim
stale and the data orphaned. **Result: that hypothesis is wrong.** No
committed code — retired, renamed, or otherwise — has ever written
`other_managers`. The data is real and sourced from
`OTHERMANAGER2.tsv`, but the load was performed out-of-band (REPL or
one-shot script never checked in).

### 9.1 Git history

Full-history searches (all branches, all files) for the writer signals:

| Query | Matching commits |
|---|---|
| `git log --all --oneline -S "other_managers" -- scripts/` | **1 commit:** `3816577` (pipeline-framework foundation) |
| `git log --all --oneline -S "other_managers" -- docs/` | 3 commits (all docs-only: `0ffb093`, `cdf2cae`, `3816577`) |
| `git log --all --oneline -S "INSERT INTO other_managers"` | **0 commits** |
| `git log --all --oneline -S "CREATE TABLE other_managers"` | **0 commits** |
| `git log --all --oneline -S "OTHERMANAGER.tsv"` | 0 commits (only added in `0ffb093` findings doc) |
| `git log --all --oneline -S "OTHERMANAGER2.tsv"` | 0 commits (same) |
| `git log --all --diff-filter=D --name-only -S "other_managers"` | **0 deleted files** |

Inspection of `3816577` (Apr 13, 2026 — "feat: pipeline framework
foundation"): the only script-side addition was the new
`DatasetSpec("other_managers", ..., owner="scripts/load_13f.py", ...)`
entry in `scripts/pipeline/registry.py:174` (line 1342 of that commit's
diff). The registry entry was a **declarative owner claim based on
context (13F-shaped data, load_13f looked like the closest fit)**, not
a refactor of an existing writer. No CREATE or INSERT statement was
added or removed in that commit or anywhere else in history.

Commit `4105689` ("N-PORT pipeline built and tested") mentions
`OTHERMANAGER` only as the uppercase column name inside the
`INSERT INTO raw_infotable` projection (the `OTHERMANAGER` source
column at `scripts/load_13f.py:71`), which is an unrelated scalar
field on `INFOTABLE.tsv`, not the `other_managers` table.

Non-commit references in the working tree:

| Path | Line | Nature |
|---|---|---|
| `scripts/pipeline/registry.py` | 174 | declarative owner claim (from `3816577`) |
| `docs/data_layers.md` | 105 | documentation claim (from `3816577`) |
| `docs/canonical_ddl.md` | 40, 326 | documentation claim (from `3816577`) |
| `notebooks/research.ipynb` | 21 | non-writer — listed in a static `DESCRIBE` enumeration of available tables |
| `docs/REWRITE_LOAD_13F_FINDINGS.md` | multiple | this finding |
| `scripts/load_13f.py` | 71 | `OTHERMANAGER` scalar column on `INFOTABLE.tsv`, unrelated to the `other_managers` table |

### 9.2 Retired scripts

`scripts/retired/` contents: `build_cusip_legacy.py`, `fetch_nport.py`,
`unify_positions.py`. Grep for `other_managers` across all three:
**no hits.** None of the retired scripts ever referenced the table.

### 9.3 SQL / migration files

No `*.sql` files in the repo (`rg --glob '*.sql' OTHERMANAGER` → zero).
Migration scripts under `scripts/migrations/` (001–007 plus
`add_last_refreshed_at.py`) do not create or populate
`other_managers`. No CREATE TABLE DDL for it exists anywhere.

### 9.4 Prod data forensics

Row-count parity against the source TSV:

| Quarter | `other_managers` rows | `OTHERMANAGER2.tsv` rows | Match |
|---|---:|---:|---|
| 2025Q1 | 3,811 | 3,811 | **exact** |
| 2025Q2 | 3,910 | 3,910 | **exact** |
| 2025Q3 | 3,759 | 3,759 | **exact** |
| 2025Q4 | 3,925 | 3,925 | **exact** |

Exact per-quarter match across all four quarters. The prod table is a
direct 1:1 copy of `OTHERMANAGER2.tsv` (not `OTHERMANAGER.tsv`, which
has ~25% more rows: Q4 = 4,751).

Accession-level sanity:

- `COUNT(DISTINCT accession_number)` = 4,817 (vs 43,358 filings) —
  only ~11% of filings disclose co-filed other managers, consistent
  with real-world 13F co-filing patterns.
- All 15,405 rows have a matching accession in `filings` (EXISTS
  check returns 15,405/15,405).
- Per-accession row count averages ~3.2, with max observed sequence
  numbers in the single digits — consistent with a small number of
  co-filers per filing.

Sample rows (heads of 2025Q4):

```
0002056656-26-000004 | 1 | NULL | NULL | 000316475 | 801-122390 | Brooklyn Investment Group
0002056656-26-000004 | 3 | NULL | NULL | 000107038 | 801-21011  | JP Morgan Asset Management
0000919574-26-001412 | 1 | 0001946122 | 028-22661 | NULL | NULL | Kosmin Fund Ltd
```

No timestamp column exists (`DESCRIBE other_managers` returns 8
columns, all VARCHAR, no ingestion timestamp). No way to directly
date the writes from the data, but row-count parity with the static
quarterly TSV rules out any recent incremental writer — whoever ran
the load did so quarterly with the complete TSV bundle.

### 9.5 Schema lineage

`OTHERMANAGER2.tsv` header:

```
ACCESSION_NUMBER  SEQUENCENUMBER  CIK  FORM13FFILENUMBER  CRDNUMBER  SECFILENUMBER  NAME
```

Prod `other_managers` schema:

```
accession_number  sequence_number  other_cik  form13f_file_number  crd_number  sec_file_number  name  quarter
```

1:1 column mapping with `CIK` → `other_cik` (renamed to disambiguate
from the filer's CIK) and a `quarter` tag appended. Identical to the
style used by `load_13f.py`'s existing `INSERT INTO raw_submissions`
projection at `:41-52`. The missing write path would fit naturally as
a fourth SEC-TSV loader inside `load_quarter()`.

Contrast with `OTHERMANAGER.tsv`: 7 columns headed
`ACCESSION_NUMBER OTHERMANAGER_SK CIK FORM13FFILENUMBER CRDNUMBER SECFILENUMBER NAME` —
different second column (`OTHERMANAGER_SK` vs `SEQUENCENUMBER`) and
25% higher row counts. The table does **not** derive from this TSV.

### 9.6 Classification

**Scenario A (with qualifier): historical writer identifiable but
never checked in.** The original logic is trivially recoverable — it
is a column-rename projection over `OTHERMANAGER2.tsv` with the
same `quarter` tag used elsewhere in `load_13f.py`. But there is no
retired script, no git commit, and no notebook that performed the
load. The writer was ad-hoc (REPL or uncommitted local script) and
the table has been sitting in prod unmaintained since at least
2025Q1 (earliest quarter with data).

Neither Scenario B (logic unclear) nor Scenario C (no trace) nor
Scenario D (derivable from a live table) fit. The data has a clear
TSV lineage; it just was never captured as code.

### 9.7 Recommendation

**Option (A) — add write path to `load_13f.py`.** Scope in Phase 1:

1. Extend `load_quarter(con, quarter)` to load a fourth TSV
   (`OTHERMANAGER2.tsv`) into `other_managers` using the same
   pattern as `raw_submissions` / `raw_infotable` / `raw_coverpage`
   (column-rename projection + `quarter` tag). Est. ~25 LOC mirroring
   the existing INSERT blocks.
2. Add `other_managers` to `create_staging_tables(con)` (`:108-158`)
   with the observed 8-column schema.
3. Add `other_managers` to `prepare_incremental(con, quarter)`
   (`:164-177`) so `--quarter` reload works.
4. Add `other_managers` to `print_summary(con)` (`:293`).
5. Add `other_managers` to the `data_freshness` retrofit (R2) along
   with the other five tables.
6. Leave `OTHERMANAGER.tsv` (the `_SK`-keyed variant) unloaded —
   prod does not use it and it would be a new surface.

Validation in Phase 1:

- Dry run: row counts per quarter match prior table exactly
  (3,811 / 3,910 / 3,759 / 3,925).
- Staging full load: `other_managers` row count in staging DB
  matches prod (15,405) after loading all four quarters.
- Downstream: zero live readers (§3), so no consumer regression
  check required. Just row-count + schema match.

Not recommended:

- **Option (B) reassign owner:** no other script is a better
  owner. The TSV is part of the 13F EDGAR bundle and the only
  existing TSV-to-DB loader for that bundle is `load_13f.py`.
- **Option (C) retire the table:** no evidence the data is unused
  in downstream analysis (zero code readers does not prove zero
  analytical / notebook readers). Cheaper to make it maintained
  than to retire and risk a future need.

### 9.8 Guardrail check

- Git log volume: 4 commits total touching `other_managers`, all
  identifiable as registry/docs additions or this audit. Not the
  ">20 commits" ghost-with-complex-history trigger.
- Recent writes check: no timestamp column, but row-count parity
  with the static TSV bundle means the writes are quarterly
  snapshots, not active. 2025Q4 was populated from the 2025Q4 TSV
  at some point between EDGAR publication (late Oct 2025) and now.
  No evidence of an active unknown writer.

### 9.9 Phase 1 scope impact

Net addition to Phase 1 scope (small):

- `+other_managers` CREATE, INSERT, DELETE, summary line, and
  freshness stamp in `load_13f.py`.
- `+other_managers` staging validation in the test plan.
- No change to registry (`scripts/pipeline/registry.py:174`
  already correctly names `load_13f.py` as owner — the claim simply
  becomes true in Phase 1).
- No change to `docs/canonical_ddl.md` or `docs/data_layers.md`.

