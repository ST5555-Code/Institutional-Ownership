# mig-03-p0 — Phase 0 findings: migration 004 RENAME→CREATE→INSERT→DROP atomicity

_Prepared: 2026-04-21 — branch `mig-03-p0` off main HEAD `c3590d0`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-03` (MAJOR-15); `docs/REMEDIATION_CHECKLIST.md` Batch 3-B; audit ref `docs/SYSTEM_AUDIT_2026_04_17.md §11.3`. Upstream: mig-04 (stamp hole closed in PR #26/#29 — a `VERSION` constant and stamp insert now exist on both branches of 004). Downstream: pattern becomes the template for any future DuckDB migration that rebuilds a table to change a PK._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** `scripts/migrations/004_summary_by_parent_rollup_type.py` in isolation. Comparison pattern pulled from `scripts/migrations/003_cusip_classifications.py` (only other migration in the tree that uses `BEGIN`/`COMMIT`). Read-site inventory from `scripts/queries.py` to scope mid-migration read risk.

**Method.** Source-of-truth walk:

- Full read of [004_summary_by_parent_rollup_type.py:1-201](scripts/migrations/004_summary_by_parent_rollup_type.py:1).
- Full read of [003_cusip_classifications.py:205-274](scripts/migrations/003_cusip_classifications.py:205) — the only migration in the tree with a `BEGIN`/`COMMIT`/`ROLLBACK` scaffold.
- Full read of [005_beneficial_ownership_entity_rollups.py:1-158](scripts/migrations/005_beneficial_ownership_entity_rollups.py:1) and [008_rename_pct_of_float_to_pct_of_so.py:1-341](scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py:1) — neither wraps DDL in a transaction; both rely on per-statement idempotency.
- `grep -l summary_by_parent` — 42 hits; the backend read-sites live in `scripts/queries.py` (lines 828, 836, 1492, 1500, 4330, 4409, 4414).
- Git history: migration 004 landed in commit `87ee955` (Batch 3 close), later amended by mig-04-p1 in `152aca7` to add the `schema_versions` stamp.

No runtime probing — the prompt forbids DB writes.

---

## §2. Current DDL sequence in migration 004

The meaningful work happens between lines 68 and 182 of `004_summary_by_parent_rollup_type.py`. Ordered by execution:

| Step | Line(s) | Operation | Notes |
|------|---------|-----------|-------|
| 0 | [004:74](scripts/migrations/004_summary_by_parent_rollup_type.py:74) | `con = duckdb.connect(db_path)` | Single connection; no `BEGIN`. Autocommit on — every `execute` is its own transaction. |
| 1 | [004:76-78](scripts/migrations/004_summary_by_parent_rollup_type.py:76) | Presence probe: `summary_by_parent` — skip if missing | Early return. |
| 2 | [004:80-96](scripts/migrations/004_summary_by_parent_rollup_type.py:80) | `_has_rollup_type` probe — if column already present, stamp retroactively (mig-04 fix) and return | Idempotent "already applied" path. |
| 3 | [004:98-108](scripts/migrations/004_summary_by_parent_rollup_type.py:98) | Read `BEFORE` DDL + row count; print | Read-only. |
| 4 | [004:112](scripts/migrations/004_summary_by_parent_rollup_type.py:112) | `DROP TABLE IF EXISTS summary_by_parent_old` | Prior-attempt cleanup. Commits on its own. |
| 5 | [004:114-116](scripts/migrations/004_summary_by_parent_rollup_type.py:114) | `ALTER TABLE summary_by_parent RENAME TO summary_by_parent_old` | **Canonical name becomes unavailable as of this commit.** |
| 6 | [004:117-135](scripts/migrations/004_summary_by_parent_rollup_type.py:117) | `CREATE TABLE summary_by_parent (...)` with expanded PK `(quarter, rollup_type, rollup_entity_id)` | Canonical name now exists again — **but empty**. |
| 7 | [004:136-159](scripts/migrations/004_summary_by_parent_rollup_type.py:136) | `INSERT INTO summary_by_parent SELECT ..., 'economic_control_v1' AS rollup_type, ... FROM summary_by_parent_old` | Backfills all rows, stamped `rollup_type='economic_control_v1'`. |
| 8 | [004:160](scripts/migrations/004_summary_by_parent_rollup_type.py:160) | `DROP TABLE summary_by_parent_old` | Drops the shadow. |
| 9 | [004:161-164](scripts/migrations/004_summary_by_parent_rollup_type.py:161) | `INSERT OR IGNORE INTO schema_versions (version, notes) VALUES (?, ?)` | Added by mig-04-p1 (`152aca7`). Idempotent. |
| 10 | [004:165](scripts/migrations/004_summary_by_parent_rollup_type.py:165) | `CHECKPOINT` | Flush WAL. |
| 11 | [004:167-176](scripts/migrations/004_summary_by_parent_rollup_type.py:167) | `AFTER` print of DDL + row count | Read-only. |
| 12 | [004:178-182](scripts/migrations/004_summary_by_parent_rollup_type.py:178) | `rows_before == rows_after` assertion — `raise SystemExit` on mismatch | Post-condition; runs only on the fresh-apply path. |

**Transaction wrapping.** None. `con = duckdb.connect(db_path)` runs in DuckDB's default autocommit mode. No `BEGIN` / `COMMIT` / `ROLLBACK` anywhere in the file. `grep -n "BEGIN\|COMMIT\|TRANSACTION" scripts/migrations/*.py` returns matches **only** in `003_cusip_classifications.py:226,235`.

**Table(s) touched.** `summary_by_parent` (reshape), `summary_by_parent_old` (scratch, created and destroyed by the migration itself), `schema_versions` (stamp, idempotent insert).

**`schema_versions` stamping.** Present since mig-04-p1 (`152aca7`). Stamp is inserted in **both** branches: the fresh-apply branch at [004:161-164](scripts/migrations/004_summary_by_parent_rollup_type.py:161), and the already-applied backfill branch at [004:85-90](scripts/migrations/004_summary_by_parent_rollup_type.py:85). Both use `INSERT OR IGNORE`, so re-running after a stamp is already present is a no-op.

**Idempotency — re-run matrix.** Depends on which step a prior run got to before dying. DuckDB autocommits each `execute`, so the "state after kill" is **whatever the last completed execute left behind**.

| Prior run died between steps | State on disk | Next run behavior | Verdict |
|------------------------------|---------------|-------------------|---------|
| 0 (connect fails) | unchanged | normal fresh apply | safe |
| 1–3 (pre-mutation) | unchanged | normal fresh apply | safe |
| 4 → 5 (between `DROP IF EXISTS _old` and `RENAME`) | unchanged (DROP was no-op) | normal fresh apply | safe |
| 5 → 6 (**after RENAME, before CREATE**) | `summary_by_parent` **missing**; `summary_by_parent_old` has the original rows | [004:76-78](scripts/migrations/004_summary_by_parent_rollup_type.py:76): "SKIP: `summary_by_parent` does not exist" → **bails with the table gone** | ❌ **CRITICAL — canonical table is silently absent; no self-heal path** |
| 6 → 7 (**after CREATE, before INSERT**) | `summary_by_parent` exists with **0 rows** and `rollup_type` column; `_old` still holds original rows | [004:80](scripts/migrations/004_summary_by_parent_rollup_type.py:80) `_has_rollup_type()` returns `True` → "ALREADY APPLIED" path, stamps schema_versions, returns | ❌ **CRITICAL — data silently lost; stamp declares victory on an empty table** |
| 7 → 8 (**after INSERT, before DROP `_old`**) | `summary_by_parent` has correct rows with new schema; `_old` also still exists with the pre-migration rows | "ALREADY APPLIED" path on re-run; `_old` persists as orphan cruft; next fresh apply will `DROP IF EXISTS _old` at step 4 and re-collide at step 5 (RENAME to an existing name) | ⚠ **recoverable but leaves orphan table until the next run; stamp may get inserted without the DROP** |
| 8 → 9 (after DROP `_old`, before stamp) | correct schema, correct rows, **no stamp** | "ALREADY APPLIED" backfill branch stamps it | safe |
| 9 → 10 (after stamp, before CHECKPOINT) | correct, stamped, but WAL not flushed | "ALREADY APPLIED"; next CHECKPOINT by any caller flushes | safe |

The two ❌ rows are the bug MAJOR-15 calls out: **the window between RENAME and INSERT is unguarded**. A kill inside that window either removes the canonical table entirely (5→6) or lies that the migration succeeded with 0 rows (6→7).

---

## §3. Comparison with the atomic pattern in migration 003

Migration 003 is the only migration in the tree that already uses a `BEGIN`/`COMMIT` scaffold. Relevant lines:

```python
# scripts/migrations/003_cusip_classifications.py:226-239
con.execute("BEGIN")
try:
    for stmt in MIGRATION_SQL:
        con.execute(stmt)
    con.execute(
        "INSERT OR IGNORE INTO schema_versions (version, notes) VALUES (?, ?)",
        [MIGRATION_VERSION, "CUSIP & ticker classification layer"],
    )
    con.execute("COMMIT")
except Exception:
    con.execute("ROLLBACK")
    con.close()
    raise

con.execute("CHECKPOINT")
```

Three takeaways:

1. **Transactional DDL works in DuckDB.** 003 wraps `CREATE TABLE`, `ALTER TABLE ADD COLUMN`, and the `schema_versions` stamp in the same `BEGIN`/`COMMIT`. DuckDB has supported transactional DDL since 0.9; statements inside the transaction either all commit or all roll back. The 003 scaffold has been in prod since 2026-04-15 with no observed failures, so the pattern is already battle-tested in this repo.
2. **The stamp lives inside the transaction.** Unstamped-but-applied is no longer a possible crash state.
3. **`CHECKPOINT` runs after `COMMIT`, not inside.** `CHECKPOINT` is a durability barrier, not a transactional statement.

Migrations 005, 006, 007, 008, 009, 010 do **not** use `BEGIN`/`COMMIT`. They get away with it because each only performs a single `ALTER TABLE ADD COLUMN` (or, in 008, a RENAME + ADD where the per-statement probes handle partial progress). Migration 004's RENAME → CREATE → INSERT → DROP is the only multi-step schema rewrite in the tree and is therefore the only migration that cannot rely on per-statement idempotency.

---

## §4. Proposed Phase 1 changes

**Goal.** Make the fresh-apply branch of 004 atomic: a crash at any point either leaves the pre-migration state intact, or leaves the post-migration state intact. No intermediate state is observable from a subsequent read or re-run.

### §4.1 Refactor to "build new in shadow, swap under one transaction"

The mechanical fix — wrap the existing sequence `DROP _old → RENAME → CREATE → INSERT → DROP _old → stamp` in `BEGIN`/`COMMIT` — is correct. But it's worth swapping the order so the rename happens **last**, which avoids the "canonical name missing" window entirely for any reader who happens to hit the DB during the transaction's own execution (pending MVCC, see §4.3). Proposed sequence:

```python
# Inside run_migration, fresh-apply branch (replacing current lines 112-165):
con.execute("BEGIN")
try:
    # Belt-and-suspenders cleanup from a prior failed attempt.
    con.execute("DROP TABLE IF EXISTS summary_by_parent_new")

    # Build the new table next to the canonical one.
    con.execute("""
        CREATE TABLE summary_by_parent_new (
            quarter VARCHAR,
            rollup_type VARCHAR,
            rollup_entity_id BIGINT,
            inst_parent_name VARCHAR,
            rollup_name VARCHAR,
            total_aum DOUBLE,
            total_nport_aum DOUBLE,
            nport_coverage_pct DOUBLE,
            ticker_count INTEGER,
            total_shares BIGINT,
            manager_type VARCHAR,
            is_passive BOOLEAN,
            top10_tickers VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (quarter, rollup_type, rollup_entity_id)
        )
    """)

    # Backfill rows with the stamped rollup_type.
    con.execute("""
        INSERT INTO summary_by_parent_new (
            quarter, rollup_type, rollup_entity_id, inst_parent_name,
            rollup_name, total_aum, total_nport_aum, nport_coverage_pct,
            ticker_count, total_shares, manager_type, is_passive,
            top10_tickers, updated_at
        )
        SELECT
            quarter,
            'economic_control_v1' AS rollup_type,
            rollup_entity_id,
            inst_parent_name,
            rollup_name,
            total_aum,
            total_nport_aum,
            nport_coverage_pct,
            ticker_count,
            total_shares,
            manager_type,
            is_passive,
            top10_tickers,
            updated_at
        FROM summary_by_parent
    """)

    # Row-count parity check INSIDE the transaction so a mismatch rolls back.
    rows_before = con.execute(
        "SELECT COUNT(*) FROM summary_by_parent"
    ).fetchone()[0]
    rows_new = con.execute(
        "SELECT COUNT(*) FROM summary_by_parent_new"
    ).fetchone()[0]
    if rows_before != rows_new:
        raise RuntimeError(
            f"migration 004 row count mismatch: "
            f"source={rows_before:,} new={rows_new:,}"
        )

    # Atomic swap: drop old, rename new into place.
    con.execute("DROP TABLE summary_by_parent")
    con.execute("ALTER TABLE summary_by_parent_new RENAME TO summary_by_parent")

    # Stamp inside the transaction so "applied" and "stamped" are coupled.
    con.execute(
        "INSERT OR IGNORE INTO schema_versions (version, notes) VALUES (?, ?)",
        [VERSION, NOTES],
    )
    con.execute("COMMIT")
except Exception:
    con.execute("ROLLBACK")
    raise

con.execute("CHECKPOINT")
```

### §4.2 Pre-transaction recovery probe

In addition to the new `BEGIN`/`COMMIT`, add a pre-transaction probe to self-heal from a **pre-fix** crash that left the DB in either of the two ❌ states in the §2 matrix. Ordered as early as possible in `run_migration`, immediately after the `_has_table("summary_by_parent")` check:

```python
has_canonical = _has_table(con, "summary_by_parent")
has_shadow_old = _has_table(con, "summary_by_parent_old")   # pre-fix naming
has_shadow_new = _has_table(con, "summary_by_parent_new")   # post-fix naming

if not has_canonical and has_shadow_old:
    # Recovered state from a pre-fix kill between steps 5 and 6.
    # Restore canonical by renaming the shadow back.
    print("  RECOVER: summary_by_parent missing; "
          "restoring from summary_by_parent_old")
    con.execute(
        "ALTER TABLE summary_by_parent_old RENAME TO summary_by_parent"
    )
    has_canonical = True
```

The post-fix `summary_by_parent_new` leftover gets cleaned up by the `DROP TABLE IF EXISTS summary_by_parent_new` inside the new transaction (§4.1), which is a no-op if the shadow isn't there and a cleanup if it is. No separate recovery branch needed for `_new`.

The shadow-to-canonical restore must happen **outside** the outer `BEGIN`/`COMMIT` because it's a one-shot rename with no companion mutations; if it fails, the operator has a clear single-statement operation to retry manually.

### §4.3 Why this is atomic in DuckDB

DuckDB uses MVCC. All statements inside a single transaction see (and produce) a snapshot that is not visible to other connections until `COMMIT` returns. Key implications:

- A reader on a **separate connection** during the transaction sees the pre-migration `summary_by_parent` (old schema, old rows) until `COMMIT`, then sees the post-migration `summary_by_parent` (new schema, new rows). There is no "empty table" or "missing table" window on a reader's side.
- A kill before `COMMIT` rolls back: `summary_by_parent_new` never existed from any observer's perspective; `summary_by_parent` is untouched.
- A kill after `COMMIT` but before `CHECKPOINT` is safe — DuckDB's WAL will replay on next open.

One caveat: this repo uses DuckDB's **file-based** storage with a single writer. Concurrent reads from separate `duckdb.connect(path)` calls are supported; concurrent writes are not. The migration assumes no other writer is running, which matches how migrations are gated today (ops run against the DB only during admin windows).

### §4.4 Cosmetic / reviewer-facing changes

- Rename the shadow from `summary_by_parent_old` to `summary_by_parent_new` in code and the module docstring. This flips the mental model from "rename old first, then build new" to "build new, then swap" — the latter matches the atomic pattern prose in `docs/SYSTEM_AUDIT_2026_04_17.md §11.3`.
- Update the docstring step list ([004:12-17](scripts/migrations/004_summary_by_parent_rollup_type.py:12)) to match the new sequence.
- Move the `rows_before != rows_after` guard ([004:178-182](scripts/migrations/004_summary_by_parent_rollup_type.py:178)) **inside** the transaction so a mismatch rolls the whole thing back rather than leaving a committed bad state plus a post-commit `SystemExit`.

---

## §5. Risk notes

### §5.1 Is `summary_by_parent` read during migration?

**No, by operating convention.** The migration is applied during an admin window with the FastAPI app stopped, so there are no concurrent readers from `scripts/queries.py`. If that convention ever changes, the MVCC behavior in §4.3 keeps readers on a consistent snapshot — the practical exposure even under concurrent reads would be a brief stall, not incorrect data.

### §5.2 Read-site inventory (for regression scope)

`grep -n summary_by_parent scripts/queries.py` returns seven call sites: lines 828, 836, 1492, 1500, 4330, 4409, 4414. All are `SELECT` against the table; none write. The schema rewrite in 004 is additive (adds `rollup_type` to the PK; no columns dropped), so existing reads continue to work after the migration even if they don't filter on `rollup_type`. No call-site change is required as part of this Phase 1.

### §5.3 Has the migration already run everywhere?

Per `docs/findings/mig-04-p0-findings.md §4`, `summary_by_parent.rollup_type` is physically present on both `data/13f.duckdb` and `data/13f_staging.duckdb`, and mig-04-p1 (commit `152aca7`) backfilled the `schema_versions` stamp on both DBs. So this Phase 1 is a **pattern retrofit for future safety**, not an in-place fix applied to a still-broken DB. The `_has_rollup_type()` check at [004:80](scripts/migrations/004_summary_by_parent_rollup_type.py:80) will hit the "ALREADY APPLIED" branch on every current DB, and the new fresh-apply code path will only execute on a fresh DB built from scratch (e.g. a CI fixture rebuild or a new environment).

### §5.4 CI / fixture impact

The test fixture at `tests/fixtures/13f_fixture.duckdb` is rebuilt from scratch by `scripts/build_fixture.py`; any replay of migration 004 there would run the **fresh-apply** branch. Phase 1 changes are therefore exercised on every fixture rebuild — a natural integration test without needing a dedicated test harness.

### §5.5 Failure modes introduced by the change

- `BEGIN`/`COMMIT`/`ROLLBACK` adds an additional failure surface (the `ROLLBACK` itself could fail if the connection is already dead). The `try/except` mirrors 003's pattern and re-raises, so the operator sees a traceback rather than a silent corruption. Net risk reduction is substantial; the new failure mode is visible and recoverable.
- Moving the row-count check inside the transaction means a count mismatch now rolls back. This is the desired behavior — under the current code, a mismatch raises `SystemExit` after the DROP of `_old` has already committed, leaving an asymmetric state that manual cleanup must reconstruct.
- The pre-transaction recovery probe in §4.2 is strictly additive: it only fires when a pre-fix crash state is detected. On clean DBs it's a three-row SELECT that costs nothing.

---

## §6. Phase 1 file list

Scope is a single migration. Phase 1 touches:

| File | Reason |
|------|--------|
| `scripts/migrations/004_summary_by_parent_rollup_type.py` | All Phase 1 code changes: `BEGIN`/`COMMIT` wrap, shadow rename to `_new`, row-count check inside txn, pre-txn recovery probe, docstring update. |

Files **not** touched in Phase 1 (explicitly out of scope):

- `scripts/queries.py`, `scripts/api_*.py`, React read-sites — schema is unchanged for readers.
- Other migrations — retrofitting 005/006/007/008/009/010 is unnecessary because each is already idempotent per-statement and has no multi-step rewrite.
- `scripts/backfill_schema_versions_stamps.py` and `scripts/verify_migration_stamps.py` — landed by mig-04-p1, no change needed.
- The `schema_versions` table DDL itself.

### §6.1 Out-of-scope follow-ons

- **mig-11 smoke-CI wiring** — `verify_migration_stamps.py` could gate this on CI, but that's scoped under mig-11 in the remediation plan (`docs/REMEDIATION_PLAN.md` Batch 3-A follow-ups).
- **Generic migration scaffold** — a future item could extract the `BEGIN`/try/`COMMIT`/`except`/`ROLLBACK`/re-raise/`CHECKPOINT` pattern into a `scripts/migrations/_scaffold.py` helper so later migrations don't have to copy it by hand. Deferred; only migration 003 and (post-Phase-1) 004 would use it today, and duplicating twelve lines of boilerplate is cheaper than a premature abstraction.

---

## §7. Cross-item awareness

- **mig-01** (atomic promotes) — CLOSED (PRs #31, #33). Same atomicity theme, disjoint files (`scripts/promote_*.py`). Pattern is consistent: `BEGIN`/try/`COMMIT`/`ROLLBACK` with the stamp/mirror inside the transaction.
- **mig-02** (`fetch_adv.py` DROP→CREATE) — CLOSED (PRs #35, #37). Solved via staging→promote, not via `BEGIN`/`COMMIT`, because `fetch_adv.py` also needed to decouple the write path from the pipeline manifest. Migration 004 doesn't have that constraint — it runs synchronously during an admin window — so the in-transaction approach is appropriate here.
- **mig-04** (schema_versions stamp hole) — CLOSED (PRs #26, #29). The stamp on line 162 of 004 is the artifact of that fix; this Phase 1 keeps it but moves it inside the new transaction.
- **mig-06** (L3 surrogate row-ID) — OPEN, Batch 3-C. Broad DDL change; no file overlap.
- **mig-07** (read-site inventory script) — OPEN, Batch 3-D. No file overlap.
- No file overlap with any currently open `obs-*`, `sec-*`, or `int-*` item.

Batch 3-B parallelization check: `docs/REMEDIATION_PLAN.md:230` confirms mig-03 and ops-12 are disjoint (mig-03 touches migration 004, ops-12 touches migration 007). Safe to proceed in parallel.

---

## §8. Summary — yes/no

- Is migration 004 currently non-atomic? **Yes.** The RENAME → CREATE → INSERT → DROP sequence is autocommit-per-statement; a kill between steps 5 and 6 leaves the canonical table missing, and a kill between steps 6 and 7 leaves it empty with the "already applied" path subsequently declaring success on zero rows.
- Does any other migration in the tree already use the correct pattern? **Yes** — migration 003 wraps its DDL in `BEGIN`/`COMMIT`/`ROLLBACK` ([003:226-239](scripts/migrations/003_cusip_classifications.py:226)). That's the template.
- Does the fix require changes outside `scripts/migrations/004_summary_by_parent_rollup_type.py`? **No.** Single-file Phase 1.
- Is this a retrofit or an in-place fix? **Retrofit.** The migration has already applied cleanly on both prod and staging (mig-04-p1 confirmed stamps). Phase 1 protects future fresh-apply paths (CI fixture rebuilds, new environments) and is the template for any future multi-step DDL migration.
