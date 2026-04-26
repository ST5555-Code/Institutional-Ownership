# mig-06-p0 — Phase 0 findings: INF40 L3 surrogate row-ID for rollback

_Prepared: 2026-04-22 — branch `mig-06-p0` off main HEAD `c2433ba`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-06` (INF40, §14.5/§14.11.4 of REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS); `docs/REMEDIATION_CHECKLIST.md` Batch 3-C. Upstream: mig-01 (atomic promotes, merged) — promote-fact-tables path already transactional. Parallel-eligible in batch with mig-09 and mig-10._

Phase 0 is investigation only. Read-only queries against prod; ALTER-TABLE benchmarks run in ephemeral tmpdir DBs, not prod. Deliverable: this document + Phase 1 migration recommendation.

---

## §1. Scope and method

**Scope.** DuckDB IDENTITY/SEQUENCE capability probe + current schemas + writer inventory + backfill runtime estimate for the three L3 canonical fact tables listed in the REMEDIATION_PLAN: `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`.

**Method.**

1. Prod DB opened `read_only=True` for schema + row counts + index + sequence inspection ([scripts/13f.duckdb](data/13f.duckdb), DuckDB **1.4.4**). No writes.
2. Ephemeral tmpdir DuckDB instances used for DDL probes: `CREATE TABLE … GENERATED ALWAYS AS IDENTITY`, `ALTER TABLE … ADD COLUMN … GENERATED ALWAYS AS IDENTITY`, `ALTER TABLE … ADD COLUMN … DEFAULT nextval('seq')`, `ALTER TABLE … ADD COLUMN … DEFAULT uuid()`.
3. Runtime benchmark: a 12,000,000-row synthetic table shaped like `holdings_v2` (34 columns, mixed types, 4 indexes matching prod) built in a tmpdir DB; then timed `ALTER TABLE ADD COLUMN BIGINT DEFAULT nextval(...)`.
4. Writer inventory: grep across `scripts/` for `INSERT INTO {table}` with regex `INSERT[[:space:]]+(OR[[:space:]]+(REPLACE|IGNORE)[[:space:]]+)?INTO[[:space:]]+(main\.)?{table}`; followed by `pipeline/registry.py` owner cross-check.

---

## §2. Current state — schemas, counts, writers, identity

### 2.1 Table sizes and column counts

| Table | rows | cols | indexes | natural-key uniqueness |
|---|---:|---:|---:|---|
| `holdings_v2` | 12,270,984 | 34 | 4 (`idx_hv2_cik_quarter`, `idx_hv2_entity_id`, `idx_hv2_rollup`, `idx_hv2_ticker_quarter`) | `(accession_number, cusip, quarter, cik)` — **NOT unique**: ~221K rows (≈1.8%) fall in intentional dup-groups per [REWRITE_PCT_OF_SO §14.5](docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md:1542) |
| `fund_holdings_v2` | 14,090,397 | 26 | 3 (`idx_fhv2_entity`, `idx_fhv2_rollup`, `idx_fhv2_series`) | `(fund_cik, report_date, cusip)` — no PK enforced; amendment semantics overwrite via DELETE+INSERT by `(series_id, report_month)` |
| `beneficial_ownership_v2` | 51,905 | 25 | 1 (`idx_bov2_entity`) | `accession_number` — no PK enforced, but promote-time DELETE+INSERT uses `accession_number` as dedup key |

**Full column list for `holdings_v2` (34):** `accession_number, cik, manager_name, crd_number, inst_parent_name, quarter, report_date, cusip, ticker, issuer_name, security_type, market_value_usd, shares, pct_of_portfolio, pct_of_so, manager_type, is_passive, is_activist, discretion, vote_sole, vote_shared, vote_none, put_call, market_value_live, security_type_inferred, fund_name, classification_source, entity_id, rollup_entity_id, rollup_name, entity_type, dm_rollup_entity_id, dm_rollup_name, pct_of_so_source`.

**`fund_holdings_v2` (26):** `fund_cik, fund_name, family_name, series_id, quarter, report_month, report_date, cusip, isin, issuer_name, ticker, asset_category, shares_or_principal, market_value_usd, pct_of_nav, fair_value_level, is_restricted, payoff_profile, loaded_at, fund_strategy, best_index, entity_id, rollup_entity_id, dm_entity_id, dm_rollup_entity_id, dm_rollup_name`.

**`beneficial_ownership_v2` (25):** `accession_number, filer_cik, filer_name, subject_cusip, subject_ticker, subject_name, filing_type, filing_date, report_date, pct_owned, shares_owned, aggregate_value, intent, is_amendment, prior_accession, purpose_text, group_members, manager_cik, loaded_at, name_resolved, entity_id, rollup_entity_id, rollup_name, dm_rollup_entity_id, dm_rollup_name`.

None of the three tables carry a surrogate row-ID or a declared PRIMARY KEY today.

### 2.2 Writer inventory

Regex-scoped grep over `scripts/` with `--include='*.py'` for `INSERT (OR REPLACE|OR IGNORE)? INTO (main.)?{table}`:

| Table | Writer(s) | Line | Insertion shape |
|---|---|---|---|
| `holdings_v2` | **no active INSERT writer** | — | One-time seeded during Phase 4 migration (the `SCHEMA_DIFF_PHASE_0_5_REBUILD_DRY_RUN.sql:50` `INSERT INTO holdings_v2 SELECT * FROM p.holdings_v2` pattern is the rebuild-from-prod path). Only UPDATEs run against it: [`enrich_holdings.py:237,356`](scripts/enrich_holdings.py:237) + [`build_managers.py:667`](scripts/build_managers.py:667). Registry owner: `"scripts/promote_13f.py (proposed)"` ([pipeline/registry.py:88](scripts/pipeline/registry.py:88)) — not yet implemented. |
| `fund_holdings_v2` | `promote_nport.py` | [301](scripts/promote_nport.py:301) | `INSERT INTO fund_holdings_v2 ({_STAGED_COLS}) SELECT {_STAGED_COLS} FROM ins_df` — explicit column list, pandas frame registered as `ins_df`. |
| `beneficial_ownership_v2` | `promote_13dg.py` | [118](scripts/promote_13dg.py:118) | `INSERT INTO beneficial_ownership_v2 (accession_number, filer_cik, …, entity_id) SELECT … FROM stage_df` — explicit 21-column list, pandas frame registered as `stage_df`. |

**One adjacent re-seed path** — [`inf39_rebuild_staging.py:71-73`](scripts/inf39_rebuild_staging.py:71) DROPs + recreates each of the three tables on staging from prod DDL (captured via `duckdb_tables().sql`) and then `INSERT INTO staging.t SELECT * FROM p.t` via ATTACH. No code change needed post-mig-06: the captured DDL will already carry the `row_id BIGINT DEFAULT nextval('row_id_seq_{table}')` column, and `SELECT * FROM p.t` passes it through.

**Zero external grep hits** outside `scripts/` — no notebook or test writes into these three tables directly.

### 2.3 Existing sequences and PK conventions

| Table | Has PK | Default-backed sequence | Central allocator |
|---|---|---|---|
| `ingestion_manifest` | PK `manifest_id` | `manifest_id_seq` (DEFAULT **dropped** by migration 010) | `scripts/pipeline/id_allocator.py::reserve_ids` |
| `ingestion_impacts` | PK `impact_id` | `impact_id_seq` (DEFAULT dropped by 010) | same allocator |
| `entities` | — | `entity_id_seq` | build_entities.py |
| `securities` | PK `cusip` | — (natural key) | — |
| `holdings_v2` | — | — | — |
| `fund_holdings_v2` | — | — | — |
| `beneficial_ownership_v2` | — | — | — |

Prod sequences already present (`SELECT sequence_name FROM duckdb_sequences()`): `entity_id_seq, identifier_staging_id_seq, impact_id_seq, manifest_id_seq, override_id_seq, relationship_id_seq, resolution_id_seq`. Three new sequences are needed for this change: `row_id_seq_holdings_v2`, `row_id_seq_fund_holdings_v2`, `row_id_seq_beneficial_ownership_v2`.

### 2.4 Why a surrogate row-ID matters — rollback-replay ambiguity

Source: [REWRITE_PCT_OF_SO §14.5](docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md:1542) and [§14.9 rollback SQL](docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md:1680). During Phase 4b of the pct-of-so migration the snapshot was captured with DuckDB `rowid`, but the post-UPDATE join returned **zero matches** — DuckDB `rowid` is not stable across full-table UPDATE + CHECKPOINT + index rebuild because physical storage rewrites shift rowids. Rollback had to fall back to a natural-key aggregate join on `(accession_number, cusip, quarter, cik)` using `MAX(pct_of_so)` per group, which is lossy where the 221K dup-group members differed in pre-apply values. Acceptable for that one-off, but it sets a precedent: **the next migration that updates `holdings_v2` cannot rely on `rowid` for point-in-time rollback, and `(accession_number, cusip, quarter, cik)` is not unique enough to replace it**.

A stable BIGINT surrogate fixes this cleanly for all three tables and, as a secondary benefit, gives promote-path crashes a row-level audit handle (who wrote this row, in what run, at what manifest_id — joinable via `ingestion_impacts` if needed).

---

## §3. DuckDB capability assessment (1.4.4, host-confirmed)

Four identity-assignment patterns probed in a tmpdir DB. Results:

| Pattern | Supported? | Evidence |
|---|---|---|
| `CREATE TABLE t (row_id BIGINT GENERATED ALWAYS AS IDENTITY, …)` | **No** | `Not implemented Error: Constraint not implemented!` |
| `ALTER TABLE t ADD COLUMN row_id BIGINT GENERATED ALWAYS AS IDENTITY` | **No** | `Parser Error: Adding generated columns after table creation is not supported yet` |
| `ALTER TABLE t ADD COLUMN row_id BIGINT DEFAULT nextval('seq')` | **Yes** | 1M row test: each existing row receives a unique sequential value (`min=1, max=1000000, 0 dupes`). Persists across reopen. Sequence `currval` advances to match. Subsequent plain `INSERT (a) VALUES (…)` without `row_id` in the column list fires the default. |
| `ALTER TABLE t ADD COLUMN row_uuid UUID DEFAULT uuid()` / `gen_random_uuid()` | **Yes** | Same — each row gets a distinct UUID; persistent across reopen. |

**Index compatibility.** `ALTER TABLE ADD COLUMN BIGINT DEFAULT nextval(...)` succeeds **with indexes already present on the table** — unlike `ALTER COLUMN DROP DEFAULT` (duckdb#17348, duckdb#15399) which the team already hit in migration 010. No DROP+RECREATE-INDEX dance is needed for mig-06.

**Durability.** After `ALTER TABLE ADD COLUMN` + `CHECKPOINT`, closing the connection and reopening the DB returns the same row_id → values are materialized, not recomputed on read.

### 3.1 Runtime benchmark at prod scale

Tmpdir DB, single-connection, single-threaded:

```
seed 12M rows (34 cols, varied types):         17.9 s
create 4 indexes (matching prod shape):         8.6 s
DB size pre-ALTER:                              993 MB
CREATE SEQUENCE row_id_seq_hv2 START 1:           ~0 s
ALTER TABLE … ADD COLUMN row_id BIGINT
    DEFAULT nextval('row_id_seq_hv2'):          0.16 s
verify (MIN, MAX, dupes) — (1, 12000000, 0):    0.1  s
CHECKPOINT:                                     0.0  s
DB size post-ALTER+CHECKPOINT:                  993 MB  (Δ 0 MB)
```

The ~0 MB storage delta on a sequential BIGINT column is expected — DuckDB's column-compression of a monotonic sequence is near-free. At the 26M-row combined scale of all three tables the total ALTER runtime is well under a second, and the wall-clock is dominated by the single `CHECKPOINT` at migration end (sub-second per the host probe).

---

## §4. Design options and recommendation

### 4.1 Three candidate approaches

| Option | Column type | Default expression | Backfill semantics | Storage (12M rows) | Uniqueness | Globally unique across tables? | Writer code change? |
|---|---|---|---|---:|---|---|---|
| **A — BIGINT + SEQUENCE** | `BIGINT NOT NULL` | `DEFAULT nextval('row_id_seq_{table}')` | In-place via ALTER TABLE ADD COLUMN; backfill fires the default for every existing row | ≈0 MB (compressed) | Per-table unique (sequence-scoped) | No — three sequences, one per table | **No** — both `INSERT INTO … (explicit cols) SELECT …` sites omit `row_id`, so default fires |
| **B — UUID** | `UUID NOT NULL` | `DEFAULT gen_random_uuid()` (or `uuid()`) | In-place ALTER; same backfill semantics as A | ~200 MB at 12M rows (16 B × 12M + overhead; compresses poorly on random content) | Globally unique | Yes | No |
| **C — BIGINT + central allocator** | `BIGINT NOT NULL` | No default; writers call `allocate_id`/`reserve_ids` per row | Requires one-time backfill via `UPDATE … SET row_id = s.rn FROM (ROW_NUMBER() …) s`; then subsequent writers must be updated | ≈0 MB | Per-table | No | **Yes** — both promote scripts must route through `pipeline/id_allocator.py` |

### 4.2 Recommendation: **Option A (BIGINT + per-table SEQUENCE)**

Rationale, ordered by weight:

1. **Zero writer code change.** Both active writers ([promote_nport.py:301](scripts/promote_nport.py:301), [promote_13dg.py:118](scripts/promote_13dg.py:118)) already use explicit column lists that omit `row_id`. Adding the column with `DEFAULT nextval(...)` means the default fires on every INSERT with no caller awareness. The registry-level `promote_13f.py (proposed)` when it lands will inherit the same zero-touch property by following the same column-list idiom used everywhere else in the repo.
2. **In-place ALTER is fast.** 0.16 s at 12M rows; the full three-table migration completes in under a second of DDL time plus one `CHECKPOINT`. No shadow-table swap needed, no multi-hour backfill UPDATE, no migration rollback scenario where the writer lag causes gaps.
3. **Storage cost is effectively zero.** A monotonically increasing BIGINT compresses to near-zero bytes per row in DuckDB's native column format. UUID (Option B) adds ~200 MB at `holdings_v2` scale and ~230 MB at `fund_holdings_v2` scale — ~430 MB total — plus index-size overhead if downstream rollback replay indexes on UUID.
4. **Matches the repo's established idiom.** The pipeline control-plane already uses `manifest_id_seq` + `impact_id_seq`, the entity MDM uses `entity_id_seq`, and migration 010 explicitly chose "one sequence per identity-bearing table" over global UUIDs. The REMEDIATION_PLAN's mig-06 context inherits the mig-01 / obs-03 precedent.
5. **Rollback-replay usage pattern fits BIGINT.** The rollback use case wants an integer handle to key into a pre-apply snapshot (e.g. `pre_apply.row_id → current.row_id` join). BIGINT joins faster than UUID and produces smaller temp snapshots.
6. **Global uniqueness across tables is not needed.** Rollback happens one table at a time; a row in `holdings_v2` and a row in `fund_holdings_v2` sharing the same `row_id = 42` is semantically fine — they are identified by `(table, row_id)`.

Option C (central allocator) is rejected because it trades zero-touch writer semantics for an allocator round-trip per write, for no corresponding benefit. The allocator exists for cross-write-path PK coordination (mirror + INSERT — see [obs-03 Phase 1](docs/findings/obs-03-p0-findings.md)); the three fact-table inserts do not cross paths.

### 4.3 Uniqueness constraint — index, not PK

Phase 1 should add `CREATE UNIQUE INDEX idx_{table}_row_id ON {table}(row_id)` alongside the ALTER. DuckDB's `PRIMARY KEY` on an existing table requires a full rebuild (see migration 011 for the securities precedent) and carries the same DROP-DEFAULT-blocks-on-indexes foot-gun. A unique index is enforcement-equivalent for rollback-replay joins and avoids the PK rebuild cost. Leave `row_id` `NOT NULL` by virtue of the `DEFAULT nextval(...)` expression (no row can be inserted without a value; existing rows all receive one during ALTER).

---

## §5. Writer impact matrix — confirms zero-touch

| Writer | INSERT site | Columns specified | Impact after mig-06 |
|---|---|---|---|
| [`promote_nport.py`](scripts/promote_nport.py:301) | `INSERT INTO fund_holdings_v2 ({','.join(_STAGED_COLS)}) SELECT {','.join(_STAGED_COLS)} FROM ins_df` | Explicit 26-column list; `_STAGED_COLS` defined at module scope | **No change.** `row_id` absent → default fires; new rows get next sequence value. |
| [`promote_13dg.py`](scripts/promote_13dg.py:118) | `INSERT INTO beneficial_ownership_v2 (accession_number, …, entity_id) SELECT … FROM stage_df` | Explicit 21-column list inline | **No change.** Same reasoning. |
| `holdings_v2` — future `promote_13f.py` | Not yet implemented (registry: proposed) | Expected to follow the same idiom | **Soft constraint only** — document in the registry entry that `promote_13f.py` must use an explicit column list that omits `row_id`. Phase 1 adds a note to `pipeline/registry.py`. |
| [`inf39_rebuild_staging.py:71-73`](scripts/inf39_rebuild_staging.py:71) | DROPs staging.t, recaptures DDL from `duckdb_tables().sql` on prod, recreates, then `INSERT INTO staging.t SELECT * FROM p.t` via ATTACH | `SELECT *` (implicit match on column list) | **No change.** Captured DDL will include the new `row_id` column + `DEFAULT nextval(...)`, and `SELECT *` passes the existing prod row_ids through. The staging sequence starts with its own `nextval` state; the staging rebuild path implicitly re-aligns it via `ALTER SEQUENCE … RESTART WITH (SELECT MAX(row_id) + 1 FROM t)` — Phase 1 adds this clamp at end-of-rebuild for hygiene. |
| [`enrich_holdings.py`](scripts/enrich_holdings.py), [`build_managers.py`](scripts/build_managers.py) | UPDATE-only; no INSERT | n/a | **No change.** UPDATEs do not touch `row_id`. |

Grep coverage: `rg 'INSERT[[:space:]]+(OR[[:space:]]+(REPLACE|IGNORE)[[:space:]]+)?INTO[[:space:]]+(main\.)?{table}'` across `scripts/`, `tests/`, `notebooks/` returned the exact two writer rows above. No hidden writers.

---

## §6. Migration plan

### 6.1 Slot and file

**Slot 014** — `scripts/migrations/014_l3_surrogate_row_id.py`. Latest stamped version is `013_drop_top10_columns` (applied 2026-04-22 08:55:40), so 014 is free. Follows the template established by [`010_drop_nextval_defaults.py`](scripts/migrations/010_drop_nextval_defaults.py) and [`012_securities_is_otc.py`](scripts/migrations/012_securities_is_otc.py):

- `VERSION = "014_l3_surrogate_row_id"`
- `NOTES = "add row_id BIGINT DEFAULT nextval on holdings_v2, fund_holdings_v2, beneficial_ownership_v2 (INF40)"`
- `TARGETS = [("holdings_v2", "row_id_seq_holdings_v2"), ("fund_holdings_v2", "row_id_seq_fund_holdings_v2"), ("beneficial_ownership_v2", "row_id_seq_beneficial_ownership_v2")]`
- Idempotent: `_has_column()` probe short-circuits the ADD COLUMN; `_already_stamped()` probes `schema_versions`.
- `--dry-run`, `--prod`, `--staging`, `--path` CLI flags mirror 010/012.

### 6.2 DDL sequence (per table, in a single BEGIN/COMMIT)

```sql
-- Per target table; runs under one transaction
CREATE SEQUENCE IF NOT EXISTS row_id_seq_{table} START 1;
ALTER TABLE {table}
    ADD COLUMN row_id BIGINT DEFAULT nextval('row_id_seq_{table}');
CREATE UNIQUE INDEX idx_{table}_row_id ON {table}(row_id);

-- After all three targets succeed:
INSERT INTO schema_versions (version, notes) VALUES ('014_l3_surrogate_row_id', '…');
COMMIT;
CHECKPOINT;
```

All three tables in one transaction so a mid-migration crash leaves the DB either fully stamped or fully untouched — matches the atomicity pattern from mig-01 / mig-03.

### 6.3 Prod and staging both

Per migration 010's precedent, mig-06 applies to **both** `data/13f.duckdb` (prod) and `data/13f_staging.duckdb` (staging) for schema parity — INF39 pre-flight gate (`make schema-parity-check`) would otherwise fail the next pipeline run. The `--staging` shortcut in the CLI runs it against staging with independent sequences (each DB has its own `row_id_seq_*`).

Staging + prod will therefore have **independent row_id values for the same rows** — staging row_id_seq starts from 1 and allocates on re-seed via `inf39_rebuild_staging.py`'s `SELECT *`, which carries prod's row_ids over. The sequence state on staging needs a one-line clamp after re-seed:

```sql
SELECT setval('row_id_seq_{table}', (SELECT COALESCE(MAX(row_id), 0) FROM {table}) + 1);
```

Phase 1 adds this clamp to `inf39_rebuild_staging.py` for each of the three tables.

### 6.4 Runtime estimate

Based on §3.1 benchmark at 12M-row scale, scaled linearly to the actual row totals:

| Table | Rows | Est. ALTER time | Est. UNIQUE INDEX build | Total |
|---|---:|---:|---:|---:|
| `holdings_v2` | 12,270,984 | ~0.2 s | ~3 s (BIGINT btree) | ~3 s |
| `fund_holdings_v2` | 14,090,397 | ~0.2 s | ~3 s | ~3 s |
| `beneficial_ownership_v2` | 51,905 | <0.01 s | <0.1 s | <0.1 s |
| **Sum (per DB)** | 26,413,286 | ~0.5 s | ~6 s | **~7 s + one CHECKPOINT** |

Applied to both prod and staging: total wall-clock for the full migration ≈ **15 s**, well under the mig-01 / mig-03 precedent of multi-minute transactional windows.

### 6.5 Rollback plan

Forward-only in spirit (migrations are additive), but a manual reversion path exists and is cheap:

```sql
BEGIN TRANSACTION;
DROP INDEX idx_holdings_v2_row_id;
DROP INDEX idx_fund_holdings_v2_row_id;
DROP INDEX idx_beneficial_ownership_v2_row_id;
ALTER TABLE holdings_v2 DROP COLUMN row_id;
ALTER TABLE fund_holdings_v2 DROP COLUMN row_id;
ALTER TABLE beneficial_ownership_v2 DROP COLUMN row_id;
DROP SEQUENCE row_id_seq_holdings_v2;
DROP SEQUENCE row_id_seq_fund_holdings_v2;
DROP SEQUENCE row_id_seq_beneficial_ownership_v2;
DELETE FROM schema_versions WHERE version = '014_l3_surrogate_row_id';
COMMIT;
CHECKPOINT;
```

Viable up until any downstream (registry, rollback-replay tooling, future `promote_13f.py`) starts reading `row_id`. After that, rollback is forbidden by data dependency rather than by DDL cost.

---

## §7. Phase 1 scope

### 7.1 Deliverables (one commit, Batch 3-C)

1. **New file** `scripts/migrations/014_l3_surrogate_row_id.py` — CLI mirroring 010/012: `--staging`, `--prod`, `--dry-run`. Idempotent on column presence and `schema_versions` stamp. Executes §6.2 DDL sequence under one BEGIN/COMMIT.
2. **Amendment** to [`scripts/inf39_rebuild_staging.py`](scripts/inf39_rebuild_staging.py) — append a post-rebuild `SELECT setval('row_id_seq_{table}', MAX(row_id)+1)` for each of the three fact tables so staging's sequence never allocates into prod's row_id space (harmless if it does, but a 1-line hygiene clamp is cheap).
3. **Registry note** in [`scripts/pipeline/registry.py`](scripts/pipeline/registry.py:87-111) — add a `notes=` line to all three entries: `"surrogate row_id BIGINT DEFAULT nextval(row_id_seq_{table}) since mig-06 (INF40)"`. Reminds future `promote_13f.py` author to keep explicit column lists.
4. **ROADMAP** — flip `INF40` entry row to `CLOSED`; add session log entry under `## Session April 22, 2026`.
5. **REMEDIATION_CHECKLIST** — check off `mig-06`.
6. **REMEDIATION_PLAN** — update convergence section (new PR count, theme milestones).

### 7.2 Out of scope for Phase 1

- Consumer-side rollback-replay tooling (separate item — INF40 is the schema enabler only; downstream tooling is a future concern).
- Any changes to `promote_nport.py` or `promote_13dg.py` INSERT paths — by §5, zero-touch.
- `promote_13f.py (proposed)` — out of scope of mig-06; a separate track.
- PRIMARY KEY constraint addition (UNIQUE INDEX is sufficient; PK would force a rebuild and trip the DROP-DEFAULT-blocks-on-indexes gotcha for future migrations).
- Extending `row_id` to other L3 tables (`filings`, `securities`, `adv_managers`, etc.) — those are rebuild-semantic or carry natural keys; out of scope.

### 7.3 Test plan

**Unit** (offline, no DB):

- `scripts/migrations/014_l3_surrogate_row_id.py::run_migration` — exists, has `--dry-run` flag, stamps `schema_versions` on apply.

**Integration** (against ephemeral tmpdir DBs):

1. **Happy path.** Seed a 10K-row synthetic version of each of the three tables with 1 matching index each; run the migration; assert: (a) `row_id` column exists with `column_default LIKE 'nextval%'`; (b) `SELECT COUNT(*) - COUNT(DISTINCT row_id)` = 0; (c) `SELECT MIN(row_id), MAX(row_id)` = `(1, rowcount)`; (d) unique index exists; (e) `schema_versions` has `014_l3_surrogate_row_id`; (f) `nextval('row_id_seq_{table}')` returns `rowcount + 1`.
2. **Idempotence.** Re-run the migration against the same DB; assert zero writes, zero errors, no duplicate `schema_versions` row.
3. **Insert-through-default.** After migration, insert a row via an explicit-column-list INSERT that omits `row_id`; assert the new row's `row_id` is `previous_max + 1`.
4. **Dry-run.** Run `--dry-run` against a fresh DB; assert: no columns added, no indexes created, no `schema_versions` row.
5. **Partial-state recovery.** Simulate a crash between table 2's ALTER and table 3's ALTER (monkey-patch to raise); assert: the transaction rolls back; `row_id` absent from all three tables; `schema_versions` not stamped.
6. **Staging parity.** Run the migration against both staging and prod fixture DBs; run `make schema-parity-check` (or `python3 scripts/pipeline/validate_schema_parity.py --layer l3`); assert PASS.

**Regression sweep:**

- Existing `tests/pipeline/test_validate_schema_parity.py` suite (109 tests) — must pass unchanged on the rebuilt fixture.
- Existing smoke suite — must pass unchanged.

---

## §8. Risks and mitigations

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| DuckDB storage overhead higher than benchmarked under real compression mix | Low | Low | Benchmarked ≈0 MB delta on 12M rows with realistic column mix; real `holdings_v2` has no radically different distribution. If overhead materializes, it is ~96 MB worst-case (12M × 8 B) and acceptable. |
| Sequence state on staging drifts behind after `inf39_rebuild_staging.py` re-seed | Medium | Low | Phase 1 adds a `setval(…, MAX(row_id)+1)` clamp per table at end of rebuild (§7.1 item 2). Harmless drift anyway — next INSERT into staging just reserves a new value from the clamped state. |
| Future `promote_13f.py` author forgets to omit `row_id` from their INSERT column list → writes conflict with the sequence | Low | Medium | Registry note (§7.1 item 3) makes the contract explicit. INF39 schema-parity gate would also detect a missing `row_id` on a freshly-written table. |
| CI fixture `tests/fixtures/13f_fixture.duckdb` lacks `row_id` after migration until re-generated | Medium | Low | `build_fixture.py` runs against prod → after mig-06 applies to prod, the next fixture build pulls `row_id` forward. Document in the PR that CI fixture should be regenerated as part of merge. |
| UNIQUE INDEX build on 14M rows takes longer than benchmarked (single-node DuckDB btree) | Low | Low | Phase 0 estimate (~3 s per large table) is conservative; even a 5× overage is under a minute. Acceptable for a migration window. |
| Locking window during ALTER holds a write lock against concurrent readers | Low | Low | DuckDB single-writer model already serializes writers; readers get the pre-ALTER snapshot until COMMIT. Wall-clock is ~15 s total; no operator workflow runs that fast against the same DB. |
| `ALTER TABLE ADD COLUMN DEFAULT nextval(...)` does not advance the sequence across existing-row backfill (i.e. default re-evaluates to the same value on every read) | **Ruled out** | — | Probed directly: 1M-row test + reopen-and-reread confirmed values are **materialized**, not lazy. Sequence `currval` advances to `rowcount`. (§3.) |

---

## §9. Cross-item awareness

- **mig-01 (merged, PR #32).** promote-fact-tables atomic transactions — provides the per-table transaction boundary; mig-06 ADD COLUMN sits outside promote. No interaction.
- **mig-09/10 (merged).** schema-parity validator extended to L4 + L0. mig-06's new row_id column lives in L3 canonical — validator already covers it; just re-run schema-parity-check after merge to regenerate the accept file if needed.
- **mig-11 (merged).** CI wiring for `tests/pipeline/` — will exercise mig-06's post-migration fixture state automatically once CI fixture is regenerated (§8 Risk 4).
- **int-12 (open).** Share touches `docs/canonical_ddl.md`; mig-06 adds one row per fact-table noting the new `row_id` column. File-level coordination only, not semantic.
- **INF41 (OPEN, process hardening).** Pre-migration exhaustive grep for old names. Not a dependency for mig-06 (no rename involved), but mig-06 should include the INF41-style sweep in its PR description as a good-hygiene example.
- **obs-04 (OPEN, ADV impacts).** Adds ADV as a source_type. Unrelated to row_id on fact tables.
- **`promote_13f.py (proposed)`.** Not yet implemented; registry update in §7.1 item 3 makes the `row_id` contract explicit for whoever writes it.

---

## §10. Summary

| Finding | Evidence | Phase 1 action |
|---|---|---|
| Three L3 fact tables lack a stable surrogate row-ID | §2.1 schemas, §2.4 rowid instability precedent | Add `row_id BIGINT DEFAULT nextval('row_id_seq_{table}')` via migration 014 |
| DuckDB `GENERATED ALWAYS AS IDENTITY` not supported on existing tables | §3 probe | Use SEQUENCE + DEFAULT (Option A) — only supported in-place path |
| Only two active writers, both use explicit column lists | §2.2, §5 | Zero writer code change; new column is backfilled by ALTER default |
| Storage cost at 26M-row total scale is negligible | §3.1 benchmark (Δ 0 MB at 12M rows) | — |
| Runtime at prod scale is ~15 s end-to-end across prod + staging | §3.1, §6.4 | — |
| Rollback is cheap up until consumer adoption | §6.5 | — |
| Staging rebuild path (`inf39_rebuild_staging.py`) carries through transparently | §5 table | Add one-line `setval(…)` clamp per table at end of rebuild |
| UNIQUE INDEX > PRIMARY KEY for this use case | §4.3 | Create unique index per table |

Phase 1 ships as one commit on branch `mig-06-p1` covering §7.1 items 1-6, with the integration tests in §7.3.
