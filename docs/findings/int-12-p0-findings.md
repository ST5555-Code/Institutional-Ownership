# int-12 Phase 0 findings — INF28: formal PK on `securities.cusip` + validator coverage

**Branch:** `int-12-p0`
**Mode:** read-only investigation
**DB snapshot:** prod `data/13f.duckdb`, staging `data/13f_staging.duckdb` (2026-04-22)
**DuckDB runtime:** 1.4.4

## 1. Summary

The data is ready. Both prod and staging have **zero duplicate CUSIPs** and **zero NULL CUSIPs** in `securities` (430,149 rows each). Neither side has any index on the table, so DuckDB's `ALTER TABLE ... ADD PRIMARY KEY (cusip)` applies cleanly without the drop/recreate dance that migration 010 had to pay. Migration slot **009 is already occupied** (`admin_sessions.py`); slot **010 is also occupied** (`drop_nextval_defaults.py`). **Next free slot is 011**. Recommend naming it `011_securities_cusip_pk.py`.

VALIDATOR_MAP is already satisfied: `securities` is present in `L3_TABLES` at [scripts/pipeline/validate_schema_parity.py:72](scripts/pipeline/validate_schema_parity.py#L72). No code change needed in the validator registration — the migration's job is only to add the constraint to both DBs so the parity check keeps passing.

## 2. Data readiness — duplicates / NULLs

Both checks run read-only against the live DBs.

| DB | `COUNT(*)` | `COUNT(DISTINCT cusip)` | NULL cusip rows | Duplicate cusip groups |
|---|---|---|---|---|
| prod `13f.duckdb` | 430,149 | 430,149 | 0 | 0 |
| staging `13f_staging.duckdb` | 430,149 | 430,149 | 0 | 0 |

Queries:
```sql
SELECT cusip, COUNT(*) AS cnt FROM securities GROUP BY cusip HAVING cnt > 1;  -- 0 rows
SELECT COUNT(*), COUNT(DISTINCT cusip),
       SUM(CASE WHEN cusip IS NULL THEN 1 ELSE 0 END) FROM securities;         -- (430149,430149,0)
```

Interpretation: int-01 (RC1) plus the CUSIP v1.4 promotion already left the table single-source-of-truth on `cusip`. **No data cleanup is required before the PK migration**.

## 3. Existing indexes on `securities` — both DBs

```sql
SELECT index_name, is_unique, is_primary, sql
FROM duckdb_indexes()
WHERE table_name = 'securities';
-- prod:    0 rows
-- staging: 0 rows
```

Consequence: the DuckDB gotcha documented in migration 010 — `ALTER` fails with `DependencyException` when any index exists on the table — **does not apply here**. Migration 011 can issue `ALTER TABLE securities ADD PRIMARY KEY (cusip)` directly, without drop/recreate wrapping.

Reproduction (DuckDB 1.4.4 scratch DB) confirming the gotcha still exists on this version:

```
CREATE TABLE t (cusip VARCHAR, name VARCHAR);
CREATE INDEX idx_t_name ON t(name);
ALTER TABLE t ADD PRIMARY KEY (cusip);
-- Dependency Error: Cannot alter entry "t" because there are entries that depend on it.
```

We're not exposed to it because `securities` carries no indexes in either DB today — but the migration **should still inspect** `duckdb_indexes()` defensively and drop/recreate if any appear before apply time.

## 4. Migration slot availability

```
$ ls scripts/migrations/
001_pipeline_control_plane.py
002_fund_universe_strategy.py
003_cusip_classifications.py
004_summary_by_parent_rollup_type.py
005_beneficial_ownership_entity_rollups.py
006_override_id_sequence.py
007_override_new_value_nullable.py
008_rename_pct_of_float_to_pct_of_so.py
009_admin_sessions.py          ← taken
010_drop_nextval_defaults.py   ← taken
add_last_refreshed_at.py
```

The int-12 prompt reserved slot 009 but that slot shipped as `admin_sessions.py` (sec-01-p1-hotfix lineage). Recommended filename for int-12: **`011_securities_cusip_pk.py`**.

`schema_versions` sanity check:
- **prod** has `010_drop_nextval_defaults` stamped (2026-04-21 04:58).
- **staging** does NOT have `010_drop_nextval_defaults` stamped in the top-5 rows. Worth a follow-up verification outside int-12 scope, but flagging here so int-12 doesn't ship against a half-migrated staging.

## 5. VALIDATOR_MAP / L3_TABLES status

`scripts/pipeline/validate_schema_parity.py` uses a list called `L3_TABLES` rather than a map called `VALIDATOR_MAP` — I'm treating those as the same thing for the purposes of int-12.

- `securities` is already present at [scripts/pipeline/validate_schema_parity.py:72](scripts/pipeline/validate_schema_parity.py#L72), inside the "Reference / other L3 (11)" block.
- The validator compares `constraints` via `duckdb_constraints()` and normalizes PK ↔ UNIQUE-index equivalence ([scripts/pipeline/validate_schema_parity.py:326](scripts/pipeline/validate_schema_parity.py#L326)). So once the PK is applied to both DBs, the parity check continues to pass without an accept-list entry.

Conclusion: **no code change** to `validate_schema_parity.py` is required for int-12. The registration is done. The int-12 migration's only job on the validator front is to **apply symmetrically to prod AND staging** so no new constraint divergence surfaces.

## 6. DuckDB PK syntax — empirical behaviour (v1.4.4)

All three probes below were run against scratch in-memory DuckDB 1.4.4 instances.

| Probe | Result |
|---|---|
| `ALTER TABLE t ADD PRIMARY KEY (cusip)` on clean table | **OK** |
| `ALTER TABLE t ADD CONSTRAINT pk_t PRIMARY KEY (cusip)` (named form) | **FAIL** — "an index with that name already exists for this table: PRIMARY_t_cusip" (DuckDB auto-creates `PRIMARY_<table>_<col>` and the named form collides) |
| `ADD PRIMARY KEY (cusip)` on table with existing non-PK index | **FAIL** — Dependency Error (same class as duckdb#17348 / #15399) |
| `ADD PRIMARY KEY (cusip)` on table containing duplicate values | **REJECTED** — "Data contains duplicates on indexed column(s)" |
| `ADD PRIMARY KEY (cusip)` on table containing NULL values | **REJECTED** — "NOT NULL constraint failed: PRIMARY_<t>_<col>" |

Design takeaways:
1. Use the **unnamed** `ADD PRIMARY KEY (cusip)` form. DuckDB auto-names the backing index `PRIMARY_securities_cusip`.
2. DuckDB's PK enforces both uniqueness and NOT NULL at `ALTER` time — exactly the invariant INF28 wants. No pre-check query needed, but it's cheap to include anyway for a clear error message.
3. No shadow-table swap required — direct `ALTER` is supported for this case (empty index list + clean data).

## 7. Proposed migration 011 — design sketch

File: `scripts/migrations/011_securities_cusip_pk.py`

```python
VERSION = "011_securities_cusip_pk"
NOTES = "add PRIMARY KEY (cusip) to securities (INF28 — int-12)"

def _has_pk(con) -> bool:
    # DuckDB exposes PK via duckdb_constraints()
    row = con.execute(
        "SELECT 1 FROM duckdb_constraints() "
        "WHERE table_name='securities' AND constraint_type='PRIMARY KEY'"
    ).fetchone()
    return row is not None

def _already_stamped(con, version) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None

def _precheck_data(con) -> None:
    dupes = con.execute(
        "SELECT COUNT(*) FROM ("
        " SELECT cusip FROM securities GROUP BY cusip HAVING COUNT(*) > 1"
        ")"
    ).fetchone()[0]
    nulls = con.execute(
        "SELECT COUNT(*) FROM securities WHERE cusip IS NULL"
    ).fetchone()[0]
    if dupes or nulls:
        raise SystemExit(
            f"MIGRATION 011 precheck failed: {dupes} duplicate cusip(s), "
            f"{nulls} NULL cusip row(s). Clean before retry."
        )

def run_migration(db_path, dry_run):
    # skip-if-missing, open RO for dry-run
    # if _has_pk(con) and _already_stamped(con, VERSION): no-op
    # drop any index on securities (defensive — 0 today, may change)
    # _precheck_data(con)
    # ALTER TABLE securities ADD PRIMARY KEY (cusip)
    # recreate indexes
    # INSERT schema_versions ... ; CHECKPOINT
```

### 7.1 Idempotency — two-tier detection

1. **Primary**: query `duckdb_constraints()` for `constraint_type='PRIMARY KEY'` on `securities`. If present → skip ALTER.
2. **Secondary**: check `schema_versions` for `011_securities_cusip_pk`. If stamped but PK absent (e.g. someone manually dropped) → re-apply.

Both conditions together = fully-applied → full no-op. Either one alone → do the missing half only.

### 7.2 Apply order

Run against both DBs, dry-run first:

```
python3 scripts/migrations/011_securities_cusip_pk.py --staging --dry-run
python3 scripts/migrations/011_securities_cusip_pk.py --staging
python3 scripts/migrations/011_securities_cusip_pk.py --prod --dry-run
python3 scripts/migrations/011_securities_cusip_pk.py --prod
```

Parity dimension: both sides must carry the PK at the end of a migration cycle, or the schema-parity validator will throw an unaccepted `constraints :: PRIMARY KEY:...` divergence against `securities`.

### 7.3 Post-apply verification

```sql
-- Both prod and staging must return ('PRIMARY KEY', 'PRIMARY KEY(cusip)')
SELECT constraint_type, constraint_text
FROM duckdb_constraints()
WHERE table_name='securities' AND constraint_type='PRIMARY KEY';

-- schema_versions stamped
SELECT version, applied_at FROM schema_versions
WHERE version = '011_securities_cusip_pk';

-- Parity validator green
python3 scripts/pipeline/validate_schema_parity.py --layer l3
```

## 8. Risks / gotchas for Phase 1

1. **Staging schema-version drift**: staging appears to be missing the `010_drop_nextval_defaults` stamp. Before int-12 Phase 1 ships, confirm staging is on the same migration floor as prod — otherwise 011 applies to inconsistent baselines. *Out of int-12 scope to fix, but surface to the user before Phase 1.*
2. **Future-added indexes on `securities`**: today there are zero. But the migration should still inspect `duckdb_indexes()` and drop/recreate defensively — cheap insurance against someone adding an index in a parallel PR between Phase 0 and Phase 1.
3. **Writer-path side effects**: adding a PK means any existing writer that inserts duplicate CUSIPs will start failing. Known writers of `securities` should be checked for idempotent upsert patterns (`INSERT ... ON CONFLICT (cusip) DO UPDATE`) vs. naive `INSERT`. *Phase 1 should grep for `INSERT INTO securities` and `COPY ... securities` across the repo before apply.*
4. **DuckDB named-constraint quirk**: use the unnamed `ADD PRIMARY KEY (cols)` form — the named `ADD CONSTRAINT ...` form collides with the auto-generated `PRIMARY_<table>_<col>` index name on DuckDB 1.4.4.

## 9. Decision requested from operator

- [ ] Confirm slot **011** is acceptable (prompt originally said 009; 009 is taken).
- [ ] Confirm staging `010_drop_nextval_defaults` stamp state before int-12 Phase 1 starts.
- [ ] Confirm writer-path audit (INF28 Phase 1) is in scope vs. deferred to a follow-up.
