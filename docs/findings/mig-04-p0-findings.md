# mig-04-p0 — Phase 0 findings: schema_versions stamp hole

_Prepared: 2026-04-21 — branch `remediation/mig-04-p0` off main HEAD `79aba16`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-04` (MAJOR-16, S-02); `docs/REMEDIATION_CHECKLIST.md` Batch 3-A. Upstream: obs-03-p1 (migration 010, merged). Downstream: Phase 2 migration 010 and any future `verify_migration_applied()` consumer rely on stamp integrity._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** Every script under `scripts/migrations/`, the `schema_versions` table itself, and current stamp state in both DuckDBs.

**Method.** Source-of-truth walk:

- `scripts/migrations/001_pipeline_control_plane.py` through `010_drop_nextval_defaults.py` — full files.
- `scripts/migrations/add_last_refreshed_at.py` — full file.
- `scripts/db.py` — searched for `verify_migration_applied` / `schema_versions`.
- `data/13f.duckdb` and `data/13f_staging.duckdb` — read-only `SELECT version, applied_at, notes FROM schema_versions`; read-only DDL presence probes against `information_schema.columns` / `duckdb_tables()`.

No runtime probing beyond read-only SELECTs — the prompt forbids any write.

**Discovered migration set** (`ls scripts/migrations/`):

1. `001_pipeline_control_plane.py`
2. `002_fund_universe_strategy.py`
3. `003_cusip_classifications.py`
4. `004_summary_by_parent_rollup_type.py`
5. `005_beneficial_ownership_entity_rollups.py`
6. `006_override_id_sequence.py`
7. `007_override_new_value_nullable.py`
8. `008_rename_pct_of_float_to_pct_of_so.py`
9. `009_admin_sessions.py`
10. `010_drop_nextval_defaults.py`
11. `add_last_refreshed_at.py` (named, not numbered)

---

## §2. `verify_migration_applied()` — not a function, a convention

Grep across the repo returns **no definition** of `verify_migration_applied()` anywhere in `scripts/` or elsewhere — only prose references in `docs/REMEDIATION_PLAN.md:111,324` and in this prompt (`docs/prompts/mig-04-p0.md:5,18,38`). `scripts/db.py` does not reference `schema_versions` or `verify_migration`.

The invariant is enforced inline. Each well-formed migration defines an `_already_stamped(con, version)` helper that runs:

```sql
SELECT 1 FROM schema_versions WHERE version = ?
```

Instances: [005_beneficial_ownership_entity_rollups.py:65-69](scripts/migrations/005_beneficial_ownership_entity_rollups.py:65), [006_override_id_sequence.py:73](scripts/migrations/006_override_id_sequence.py:73), [007_override_new_value_nullable.py:101](scripts/migrations/007_override_new_value_nullable.py:101), [008_rename_pct_of_float_to_pct_of_so.py:94](scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py:94), [009_admin_sessions.py:99](scripts/migrations/009_admin_sessions.py:99), [010_drop_nextval_defaults.py:102-106](scripts/migrations/010_drop_nextval_defaults.py:102).

**What breaks if a migration is unstamped.** The SELECT returns no row, so any audit that relies on it (or a future `verify_migration_applied()` helper) will declare the migration **not applied** even though the DDL is physically present. Consequences:

- Re-running the migration is a no-op in practice (every statement is idempotent with `IF NOT EXISTS` / column probes), but the audit report lies.
- Downstream migrations that `_already_stamped()`-check a predecessor as a precondition will refuse to proceed, or will re-enter an already-applied branch.
- Phase 2 `migration 010` (per REMEDIATION_PLAN.md:324) expects `verify_migration_applied()` to give the right answer — an unstamped row silently poisons any future automation.

The `schema_versions` table itself was created fresh by migration 003 ([003_cusip_classifications.py:51-58](scripts/migrations/003_cusip_classifications.py:51)), with a self-aware comment: `"schema_versions (created fresh; prior migrations did not stamp)"`. So 001 and 002 running before 003 could not have stamped. Everything after 003 should stamp.

---

## §3. Migration inventory — DDL vs. stamp

Legend: **YES** = stamps via `INSERT INTO schema_versions`; **NO** = migration performs DDL but never writes to `schema_versions`; **N/A-pre-003** = ran before the `schema_versions` table existed.

| # | Script | DDL applied | Stamps? | Stamp site (file:line) | Status |
|---|--------|-------------|---------|------------------------|--------|
| 001 | `001_pipeline_control_plane.py` | creates sequences, `ingestion_manifest`, `ingestion_impacts`, `pending_entity_resolution`, `data_freshness`, `ingestion_manifest_current` view | **NO** | — ([scripts/migrations/001_pipeline_control_plane.py:40-166](scripts/migrations/001_pipeline_control_plane.py:40); no `schema_versions` reference) | N/A-pre-003 |
| 002 | `002_fund_universe_strategy.py` | `ALTER TABLE fund_universe ADD COLUMN` × 3 (`strategy_narrative`, `strategy_source`, `strategy_fetched_at`) | **NO** | — ([scripts/migrations/002_fund_universe_strategy.py:27-33](scripts/migrations/002_fund_universe_strategy.py:27); no `schema_versions` reference) | N/A-pre-003 |
| 003 | `003_cusip_classifications.py` | creates `schema_versions`, `cusip_classifications`, helpers | **YES** (`INSERT OR IGNORE`) | [scripts/migrations/003_cusip_classifications.py:230-233](scripts/migrations/003_cusip_classifications.py:230) | OK |
| 004 | `004_summary_by_parent_rollup_type.py` | rebuilds `summary_by_parent` with expanded PK + `rollup_type` column | **NO** | — ([scripts/migrations/004_summary_by_parent_rollup_type.py:1-60+](scripts/migrations/004_summary_by_parent_rollup_type.py:1); no `schema_versions` reference in file) | **HOLE** — ran after 003, should stamp |
| 005 | `005_beneficial_ownership_entity_rollups.py` | `ALTER TABLE beneficial_ownership_v2 ADD COLUMN` × 4 rollup columns | **YES** (both branches: already-applied and fresh-apply) | [scripts/migrations/005_beneficial_ownership_entity_rollups.py:96-102,113-118](scripts/migrations/005_beneficial_ownership_entity_rollups.py:96) | OK |
| 006 | `006_override_id_sequence.py` | creates `override_id_seq`; alters `entity_overrides_persistent` default + NOT NULL | **YES** | [scripts/migrations/006_override_id_sequence.py:148-153](scripts/migrations/006_override_id_sequence.py:148) | OK |
| 007 | `007_override_new_value_nullable.py` | drops NOT NULL on `entity_overrides_persistent.new_value` | **YES** | [scripts/migrations/007_override_new_value_nullable.py:140-145](scripts/migrations/007_override_new_value_nullable.py:140) | OK |
| 008 | `008_rename_pct_of_float_to_pct_of_so.py` | renames `holdings_v2.pct_of_float` → `pct_of_so`; adds `pct_of_so_source` audit | **YES** | [scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py:266-271](scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py:266) | OK |
| 009 | `009_admin_sessions.py` | creates `admin_sessions` | **YES** | [scripts/migrations/009_admin_sessions.py:160-165](scripts/migrations/009_admin_sessions.py:160) | OK |
| 010 | `010_drop_nextval_defaults.py` | drops `DEFAULT nextval` on `ingestion_impacts.impact_id` + `ingestion_manifest.manifest_id` | **YES** | [scripts/migrations/010_drop_nextval_defaults.py:176-181](scripts/migrations/010_drop_nextval_defaults.py:176) | OK — obs-03-p1 verified |
| — | `add_last_refreshed_at.py` | `ALTER TABLE entity_relationships ADD COLUMN last_refreshed_at TIMESTAMP`; backfills from `created_at` | **NO** | — ([scripts/migrations/add_last_refreshed_at.py:1-143](scripts/migrations/add_last_refreshed_at.py:1); no `schema_versions` reference anywhere) | **HOLE** — audit target (MAJOR-16 / S-02) |

**Stamp-missing count: 4 migrations** — `001`, `002`, `004`, `add_last_refreshed_at`.

Of these:
- `001` and `002` are **excused** by timing (the stamp table did not yet exist).
- `004` and `add_last_refreshed_at` are **bugs**: both were added after 003 created `schema_versions`, and both perform real DDL without stamping.

---

## §4. DB state — `schema_versions` current rows

Read-only query against both DBs at `2026-04-21`:

```sql
SELECT version, applied_at, notes FROM schema_versions ORDER BY applied_at, version;
```

### Prod (`data/13f.duckdb`) — 7 rows

| version | applied_at | notes |
|---|---|---|
| `003_cusip_classifications` | 2026-04-15 09:17:46 | CUSIP & ticker classification layer |
| `005_beneficial_ownership_entity_rollups` | 2026-04-16 07:56:14 | 13D/G entity rollup columns on beneficial_ownership_v2 |
| `006_override_id_sequence` | 2026-04-17 05:00:39 | override_id sequence + DEFAULT nextval + NOT NULL constraint |
| `007_override_new_value_nullable` | 2026-04-17 05:55:16 | drop NOT NULL on entity_overrides_persistent.new_value |
| `008_rename_pct_of_float_to_pct_of_so` | 2026-04-19 13:17:12 | holdings_v2 pct_of_float → pct_of_so rename + pct_of_so_source audit column |
| `009_admin_sessions` | 2026-04-20 12:39:01 | admin_sessions table (sec-01 Phase 1 server-side session storage) |
| `010_drop_nextval_defaults` | 2026-04-21 04:58:38 | drop DEFAULT nextval on ingestion_impacts.impact_id and ingestion_manifest.manifest_id (obs-03 Phase 1) |

### Staging (`data/13f_staging.duckdb`) — 6 rows

| version | applied_at | notes |
|---|---|---|
| `003_cusip_classifications` | 2026-04-14 09:17:51 | CUSIP & ticker classification layer |
| `006_override_id_sequence` | 2026-04-16 22:37:13 | override_id sequence + DEFAULT nextval + NOT NULL constraint |
| `007_override_new_value_nullable` | 2026-04-17 05:55:15 | drop NOT NULL on entity_overrides_persistent.new_value |
| `008_rename_pct_of_float_to_pct_of_so` | 2026-04-19 12:51:51 | holdings_v2 pct_of_float → pct_of_so rename + pct_of_so_source audit column |
| `009_admin_sessions` | 2026-04-20 12:39:01 | admin_sessions table (sec-01 Phase 1 server-side session storage) |
| `010_drop_nextval_defaults` | 2026-04-20 18:05:45 | drop DEFAULT nextval on ingestion_impacts.impact_id and ingestion_manifest.manifest_id (obs-03 Phase 1) |

### Parity gap

| version | prod stamp | staging stamp | DDL present on prod | DDL present on staging |
|---|---|---|---|---|
| `001` (pipeline control plane tables) | missing | missing | yes (`ingestion_manifest`, `ingestion_impacts`, `pending_entity_resolution`, `data_freshness`) | yes |
| `002` (fund_universe strategy cols) | missing | missing | yes (`strategy_narrative`, `strategy_source`, `strategy_fetched_at` on `fund_universe`) | yes |
| `003` | ✅ | ✅ | yes (table `cusip_classifications`) | yes |
| `004` (summary_by_parent.rollup_type) | missing | missing | yes (`rollup_type` column present) | yes |
| `005` (bo_v2 rollup columns) | ✅ | **missing** | yes (`rollup_entity_id`, `rollup_name` present) | yes |
| `006`–`010` | ✅ | ✅ | yes | yes |
| `add_last_refreshed_at` (`entity_relationships.last_refreshed_at`) | missing | missing | yes (column present) | yes |

**Two independent issues**:

1. **Stamp-omitting migrations** — 001, 002, 004, `add_last_refreshed_at` never stamp anywhere. (001/002 expected; 004 and `add_last_refreshed_at` are bugs.)
2. **Cross-DB stamp drift — `005`** — stamp exists on prod (2026-04-16) but not on staging, even though the four rollup columns are physically present on the staging `beneficial_ownership_v2` table. Hypothesis: an older copy of 005 ran against staging before the `_already_stamped`/stamp-in-already-applied-branch logic landed (lines 96-102 specifically). Re-running the current 005 with `--staging` (not `--dry-run`) would backfill the stamp via the "no pending columns + not stamped" branch without re-executing any DDL.

---

## §5. Cross-item awareness

- **mig-01 (atomic promotes)** — Batch 3-A parallel-eligible with mig-04 per `docs/REMEDIATION_CHECKLIST.md` Batch 3-A. No overlap in files touched: mig-01 operates on `scripts/promote_*.py`, mig-04 on `scripts/migrations/*.py`. Proceed in parallel.
- **mig-02** — listed out-of-scope by the prompt.
- **Phase 2 migration 010 (`010_drop_nextval_defaults.py`)** — confirmed stamps correctly ([010:176-181](scripts/migrations/010_drop_nextval_defaults.py:176)); obs-03-p1 merged 2026-04-21. Stamp is present on both prod and staging.
- **obs-03-p1** — landed 010 cleanly. No regression to undo.
- **sec-03-p1** / **sec-04-p0** / **obs-01-p1** — orthogonal; no file overlap with `scripts/migrations/`.

---

## §6. Recommended Phase 1 scope

**Branch**: `remediation/mig-04-p1` off `remediation/mig-04-p0` (or main after this PR merges).

### Code fixes

1. **`scripts/migrations/add_last_refreshed_at.py`** — add the full `_already_stamped` + `INSERT INTO schema_versions` pattern matching [010:102-106,176-181](scripts/migrations/010_drop_nextval_defaults.py:102). Define `VERSION = "add_last_refreshed_at"` (keep the non-numeric naming for traceability; future numbered migrations keep their NNN prefix). Stamp on both the "already applied" branch (column exists) and the fresh-apply branch. Include in both dry-run printout and real-run CHECKPOINT.

2. **`scripts/migrations/004_summary_by_parent_rollup_type.py`** — same treatment. `VERSION = "004_summary_by_parent_rollup_type"`, `NOTES = "summary_by_parent rollup_type column + compound PK"`. Stamp in both the already-applied and fresh-apply branches.

3. **`scripts/migrations/001_pipeline_control_plane.py`** and **`scripts/migrations/002_fund_universe_strategy.py`** — add stamp after the DDL. These ran before `schema_versions` existed, so the stamp call must be `INSERT OR IGNORE` (matching 003's style) and guarded by `if _has_table('schema_versions')` — otherwise running 001 on a fresh DB pre-003 will crash. Treating the stamp as opportunistic (no-op if the table is missing) is the right semantic: "if the audit table is live, record this."

### Backfill — DB writes (Phase 1, not Phase 0)

Apply `scripts/backfill_schema_versions_stamps.py` (new) that, for each DB (`--prod`, `--staging`, `--both`), probes for each migration's DDL signature and inserts the stamp if it is absent:

| version | DDL probe | Notes to insert |
|---|---|---|
| `001_pipeline_control_plane` | `ingestion_manifest` exists AND `ingestion_impacts` exists | `"L0 pipeline control plane (backfill)"` |
| `002_fund_universe_strategy` | `fund_universe.strategy_narrative` exists | `"fund_universe strategy narrative columns (backfill)"` |
| `004_summary_by_parent_rollup_type` | `summary_by_parent.rollup_type` exists | `"summary_by_parent rollup_type column + compound PK (backfill)"` |
| `005_beneficial_ownership_entity_rollups` | `beneficial_ownership_v2.rollup_entity_id` exists AND stamp absent | staging-only backfill; prod already stamped |
| `add_last_refreshed_at` | `entity_relationships.last_refreshed_at` exists | `"entity_relationships.last_refreshed_at column + backfill (backfill)"` |

All inserts use `INSERT OR IGNORE` keyed on `version` (PK).

### Test plan

1. **Code-level**: rerun the fixed `004_summary_by_parent_rollup_type.py` and `add_last_refreshed_at.py` against staging with `--dry-run` first; confirm output shows `INSERT schema_versions: <VERSION>` in the will-do list and that `schema_versions stamped: False` flips to `True` in the live-apply output.
2. **Backfill**: run the new `backfill_schema_versions_stamps.py --both --dry-run`, inspect. Then `--both` live. Re-query `schema_versions` on both DBs; assert row counts 11 on prod, 11 on staging (7 → 11 prod, 6 → 11 staging), and that the `(version, notes)` set is equal between the two DBs modulo `applied_at` timestamps.
3. **Invariant check**: write a simple `scripts/verify_migration_stamps.py` that reads `scripts/migrations/*.py`, extracts each file's `VERSION` constant (or falls back to the filename stem), and asserts one `schema_versions` row per migration. This formalizes the `verify_migration_applied()` invariant that the prompt references.
4. **CI gate (optional Phase 2)**: wire `verify_migration_stamps.py` into pre-push / Makefile so a new migration without a stamp fails CI.

### Out of scope for Phase 1

- mig-01 atomic promotes (separate item).
- mig-02 (separate item).
- Any DDL change to the `schema_versions` table itself.
- Any rename of `add_last_refreshed_at.py` to a numbered form (would be cosmetic and introduce a migration-rename ceremony with no stamp-integrity benefit).

---

## §7. Summary — yes/no

- Is `scripts/migrations/add_last_refreshed_at.py` missing the `schema_versions` stamp? **Yes** — no reference in the file at all ([add_last_refreshed_at.py:1-143](scripts/migrations/add_last_refreshed_at.py:1)).
- Is it the only one? **No.** `001`, `002`, and `004` are also missing. `001` and `002` are excused by timing (pre-`schema_versions`); `004` is a matching bug and should be fixed in the same Phase 1 patch.
- Is there a prod-vs-staging drift? **Yes** — `005` is stamped on prod but not staging despite DDL parity.
- Does `verify_migration_applied()` exist as a function? **No** — it is a convention realized as inline `_already_stamped()` helpers. Phase 1 should introduce a single `scripts/verify_migration_stamps.py` so the invariant is mechanized, not just referenced in prose.
