# REWRITE build_managers.py — Phase 0 Findings

_Branch: `rewrite-build-managers`, off main `7e68cf9`. Phase 0 is
read-only._

## Scope

Complete the REWRITE retrofit of `scripts/build_managers.py` — the
final remaining Batch 3 target. Retrofits landed via commit `831e5b4`
(CHECKPOINT `:603`, `record_freshness(con, "managers")` `:604`,
`flush=True` on warn print `:606`). Outstanding at HEAD:

1. Legacy `holdings` ALTER+UPDATE+COUNT block (`:520-540`) operating
   against a dropped table.
2. Missing `--dry-run` flag.
3. Missing `--staging` plumbing — hard-coded prod DB path at `:26`.
4. Direct production writes of `parent_bridge` / `managers` /
   `cik_crd_links` / `cik_crd_direct`, bypassing the INF1 staging
   workflow. Flagged in `docs/pipeline_inventory.md §8` and in
   `docs/REWRITE_LOAD_13F_FINDINGS.md §9`.

Read-only throughout. Prod DB (`/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb`,
13.6 GB) opened `read_only=True`. No code edits to
`scripts/build_managers.py`. Phase 0 commits docs only.

---

## Headline

1. **The legacy `holdings` block (`:520-540`) is functionally dead and
   materially broken at HEAD.** The target `holdings` table does not
   exist in prod (dropped in Stage 5 cleanup — see `fetch_ncen.py:345`
   comment and `REWRITE_LOAD_13F_FINDINGS.md:29`). Only the `ALTER
   TABLE` loop is wrapped in `try/except pass` (`:520-525`); the
   subsequent `UPDATE holdings h ... FROM managers m` at `:527-536`
   and `SELECT COUNT(*) FROM holdings` at `:537-539` are **not**
   wrapped. A fresh run against prod today would raise at
   `build_managers_table`'s UPDATE before `CHECKPOINT` is reached. This
   is a live blocker, not a cosmetic retrofit.
2. **The ALTER+UPDATE computation is NOT dead in intent.** The four
   columns it writes (`inst_parent_name`, `manager_type`, `is_passive`,
   `is_activist`) exist on `holdings_v2` (prod DDL confirmed), are
   100% populated (12,270,984 rows, 0 NULLs in all four columns —
   carried over from the legacy `holdings`→`holdings_v2` migration),
   and are read by multiple live consumers
   (`queries.py:571,578,689,692,1444,1693,4264`,
   `compute_flows.py:319,350,361-367`,
   `build_summaries.py:174-182,260-261`, `api_register.py:307,329`,
   `admin_bp.py:380`). Retiring the block entirely stops future new
   quarters from being enriched; the existing population is a
   historical snapshot and will degrade as new rows land in
   `holdings_v2` uncoupled from `managers`. Repoint, don't delete.
3. **INF1 staging bypass — four tables, three writers on `managers`,
   empirical-PK drift.** `build_managers.py` writes four tables via
   `DROP+CTAS`: `parent_bridge`, `cik_crd_links`, `cik_crd_direct`,
   `managers`. `managers` has two additional post-hoc writers
   (`fetch_13dg.py:325-327` `ALTER ADD has_13dg` + `UPDATE has_13dg`,
   and `fetch_ncen.py:349-352,399-403` `ALTER ADD adviser_cik` +
   `UPDATE adviser_cik`). This multi-writer pattern plus
   `DROP+CTAS` semantics breaks the PK-based promote_staging path —
   any `DROP` done in staging would clobber the `has_13dg` /
   `adviser_cik` drift on the prod side if routed through the standard
   entity CANONICAL_TABLES extension (same class of footgun the
   `merge_staging.py` PK-replace fix in Apr 14 session flagged).
4. **`managers.cik` is not a valid PK.** Empirically 12,005 rows /
   11,135 distinct CIKs (≈7.3% duplication). Duplicates arise from
   `LEFT JOIN` fan-out in the `build_managers_table` CTAS at
   `:429-512` (a single CIK can match multiple `parent_bridge` rows
   when seed-based matching produces overlaps, plus non-deduped
   `cik_crd_links` fallback). This is a data-quality bug orthogonal
   to the staging routing question but it directly blocks adding
   `managers` to `PK_COLUMNS` in `promote_staging.py`. `parent_bridge.cik`
   and `cik_crd_direct.cik` are empirically unique;
   `cik_crd_links.cik` has 3 duplicate CIKs.
5. **`--staging` flag is absent, not partial.** No reference to `db.
   get_db_path()`, `db.connect_write()`, `db.set_staging_mode()`, or
   `args.staging` anywhere in the file. Prod path is hard-coded at
   `:26` (confirming `pipeline_inventory.md §5`).
6. **No other downstream writers on `parent_bridge`,
   `cik_crd_links`, or `cik_crd_direct`.** `build_managers.py` is the
   sole writer for those three.

---

## 1. Code structure (0.1)

### 1.1 Entry points and flow

| Component | Location | Notes |
|---|---|---|
| Shebang + docstring | `:1-9` | Declares `fetch_adv.py` + `load_13f.py` as prerequisites |
| `BASE_DIR`, `DB_PATH` | `:25-26` | Hard-coded prod path — **INF1 / `--staging` gap** |
| `PARENT_SEEDS` constant | `:86-217` | 100+ tier-1 + tier-2 institutional seeds |
| `_BRAND_STOPWORDS` / `_brand_tokens*` | `:39-63` | INF17 Phase 3 brand-token gate |
| `_city_state_compatible` | `:66-79` | INF17 Phase 3 city/state gate |
| `build_parent_bridge(con)` | `:220-288` | Builds `parent_bridge` via seed matching + unaffiliated self-parent fallback |
| `link_cik_to_crd(con)` | `:291-421` | Two-stage CRD link: direct CIK lookup + fuzzy name match |
| `build_managers_table(con)` | `:424-542` | Composes `managers` via CTAS; then the dead `holdings` block |
| `print_summary(con)` | `:545-580` | Reports per-strategy counts, activist roster, top-15 parents |
| `main()` | `:583-608` | Four steps + CHECKPOINT/freshness retrofit |

No CLI arguments. No argparse. No `--dry-run`. No `--staging`. No
`--test`.

### 1.2 Reads

All reads are against production tables (no external I/O at read time).

| Table | Lines | Semantics |
|---|---|---|
| `filings_deduped` | `:227-229`, `:298-301`, `:494-503` | `SELECT DISTINCT cik, manager_name, crd_number WHERE manager_name IS NOT NULL`; the no-CRD variant; and a `GROUP BY cik` aggregate for `num_filings` + `total_positions` |
| `adv_managers` | `:305-309` | `SELECT crd_number, firm_name, cik AS adv_cik, city, state WHERE firm_name IS NOT NULL` |
| `parent_bridge` | `:504` | `LEFT JOIN parent_bridge p ON f.cik = p.cik` (internal — this function wrote it earlier in the same run) |
| `cik_crd_direct` | `:505` | `LEFT JOIN cik_crd_direct d ON f.cik = d.cik` |
| `cik_crd_links` (subquery) | `:506-510` | `QUALIFY ROW_NUMBER()` dedupe on `cik`, `match_score >= 85` |
| `adv_managers` (join) | `:511` | `LEFT JOIN adv_managers a ON COALESCE(f.crd_number, d.crd_number, l.crd_number) = a.crd_number` |
| `managers` | `:514` | `SELECT COUNT(*)` for reporting |
| `managers` | `:534` | `FROM managers m` in the dead `UPDATE holdings ... FROM managers` |
| `holdings` (dead) | `:527-536`, `:537-539` | UPDATE target + COUNT; table does not exist in prod |

### 1.3 Writes

| Table | Lines | Shape |
|---|---|---|
| `parent_bridge` | `:284-285` | `DROP TABLE IF EXISTS` + `CREATE TABLE AS SELECT * FROM df_bridge_full` (pandas DF) |
| `cik_crd_links` | `:406-407` | `DROP + CTAS` from `df_links` |
| `cik_crd_direct` | `:416-417` | `DROP + CTAS` from `df_direct` |
| `managers` | `:428-430` (DROP+CREATE), `:429-512` (SELECT body) | `DROP + CREATE TABLE managers AS SELECT ...` composed from `filings_deduped` GROUP BY + LEFT JOINs |
| `holdings` (dead) | `:521-524` (ALTER loop, try/except), `:527-536` (UPDATE — **unwrapped**) | Both target a dropped table; UPDATE path would raise at runtime |
| `logs/build_managers_rejected_crds.csv` | `:345-398` | External CSV with rejection log for fuzzy-match gates (INF17 Phase 3) |
| `data_freshness` (`managers`) | `:604` (via `db.record_freshness`) | Retrofit `831e5b4` |

### 1.4 Error handling

Silent-swallow patterns:

- `:520-525` — `try/except Exception: pass  # nosec B110` around the
  dead `ALTER TABLE holdings` block. Masks the real failure (dropped
  table).
- `:605-606` — warn-print around `CHECKPOINT` + `record_freshness`.
  Acceptable (retrofit).

No `continue` / `pass` in the fuzzy-match loop hides data errors; the
loop writes every near-miss to the rejection CSV.

### 1.5 Flag semantics

Post-`831e5b4` state:

| Flag | Status |
|---|---|
| CHECKPOINT at end | PRESENT `:603` |
| `record_freshness("managers")` | PRESENT `:604` |
| `flush=True` on warns | PRESENT `:606` |
| `--dry-run` | **MISSING** |
| `--staging` | **MISSING** |
| `--test` | **MISSING** |
| Fail-fast on missing inputs | **MISSING** — e.g., no check that `filings_deduped` / `adv_managers` are present before first SELECT |
| Per-table `data_freshness` | PARTIAL — only `managers` is stamped; `parent_bridge`, `cik_crd_links`, `cik_crd_direct` are not |

---

## 2. INF1 staging routing design (0.2)

### 2.1 Current entity-table staging mechanism

Pattern: `sync_staging.py` → editor → `diff_staging.py` → human review
→ `promote_staging.py --approved`.

- `sync_staging.py` (`:86-224`) CTAS-clones `db.ENTITY_TABLES` from
  prod → staging at session start.
- `promote_staging.py` (`:456-556`) snapshots every promotable table,
  does diff-based `DELETE-then-INSERT` per `PK_COLUMNS`, resets
  sequences, runs per-table validators per `VALIDATOR_MAP`,
  auto-rolls-back on structural failure.
- `db.PROMOTABLE_TABLES = ENTITY_TABLES + CANONICAL_TABLES` (`db.py:122`).
- `db.REFERENCE_TABLES` (`db.py:82-85`) is the *staging seed* list —
  read-only mirror of prod for reference lookups during an edit
  session. **`parent_bridge` is already in `REFERENCE_TABLES`** for
  seed-read purposes.

### 2.2 BLOCK-SECURITIES-DATA-AUDIT precedent (commit `04cf833`, 2026-04-18)

Extension shape:

1. Add canonical tables to `db.CANONICAL_TABLES` (`db.py:111-118`).
2. Declare PKs in `promote_staging.PK_COLUMNS` (`promote_staging.py:49-63`) — empirically unique natural key.
3. Register `None` in `VALIDATOR_MAP` (`promote_staging.py:74-88`) with explicit load-bearing warn (`_run_validators:573-579`, `dry_run:447-452`).
4. No new per-table logic required in `_apply_table` or the snapshot/restore path.

This worked for `cusip_classifications` and `securities` because
(a) their natural keys are true empirical PKs (0 dupes, 0 NULLs),
(b) they have no post-hoc column-adders or UPDATE tails (build scripts
own them end-to-end), and (c) they are the sole writer.

### 2.3 Per-table characteristics (prod snapshot, `7e68cf9`)

| Table | Rows | Cols | PK candidate | Empirically unique? | Additional writers | Write shape |
|---|---:|---:|---|---|---|---|
| `parent_bridge` | 11,135 | 7 | `cik` | **YES** (11,135/11,135, 0 NULLs) | None | DROP+CTAS |
| `cik_crd_direct` | 4,059 | 3 | `cik` | **YES** (4,059/4,059, 0 NULLs) | None | DROP+CTAS |
| `cik_crd_links` | 448 | 5 | `cik` | **NO** — 445/448 distinct (3 dupes) | None | DROP+CTAS |
| `managers` | 12,005 | 16 | `cik` | **NO** — 11,135/12,005 distinct (~7.3% dupe rate) | `fetch_13dg.py` (ALTER+UPDATE `has_13dg`), `fetch_ncen.py` (ALTER+UPDATE `adviser_cik`) | DROP+CTAS, then downstream UPDATEs add columns |

Compound key tests (`managers`): `(cik, crd_number)` gives
`11,135 / 12,005` distinct — same as `cik` alone — proving duplicates
have identical `(cik, crd_number)` and differ only in `parent_name` /
`strategy_type` columns. Verified: CIK `0001802635` has 3 rows, all
same `manager_name`/`crd_number`, with `parent_name` values
{`"H&H Retirement Design & Management INC"`, `"One Wealth Map LLC"`,
`"One Wealth Map LLC"`} — LEFT JOIN fan-out in the
`build_managers_table` CTAS at `:429-512`. No composite column in
`managers` as-shipped produces uniqueness.

### 2.4 Routing decision

**Option (i): standard CANONICAL_TABLES extension.** Works cleanly for
`parent_bridge` and `cik_crd_direct`. Blocked for `managers` and
`cik_crd_links` by empirical PK failure.

**Option (ii): new routing path.** Too much scope for the last Batch 3
block — per BLOCK-SECURITIES-DATA-AUDIT Phase 3 we want the
CANONICAL_TABLES extension to stay the one precedent shape.

**Option (iii): skip staging.** Unacceptable — violates INF1 (see
`pipeline_inventory.md §8`).

**Recommended hybrid (option i+):**

1. Phase 1 routes `parent_bridge` and `cik_crd_direct` through
   CANONICAL_TABLES (diff-based DELETE/INSERT, empirical PK = `cik`).
2. Phase 1 routes `managers` and `cik_crd_links` through a
   **full-replace** promotion path (snapshot + `DELETE FROM prod.tbl`
   + `INSERT SELECT * FROM stg.tbl`) — not diff-based. Justification:
   both tables are DROP+CTAS rebuilds with no meaningful identity
   semantics below the table grain. This can be implemented as a new
   `"rebuild"` kind in `promote_staging.VALIDATOR_MAP`-adjacent state
   (`PROMOTE_STRATEGY` dict alongside `PK_COLUMNS`, keyed at
   `_apply_table`), or as a light extension in `promote_staging.py`
   with one new branch at `_apply_table`. This avoids the footgun
   where `DROP` in staging orphans `has_13dg` / `adviser_cik` drift
   on the prod side: because the `managers` DROP+CTAS is the
   upstream-of-`fetch_13dg`/`fetch_ncen` step, staging's `managers`
   never has those columns; a full replace is the semantically
   correct operation.
3. Explicit PK-dedupe bug-fix on `managers` is **scope-deferred** —
   it's a data-quality issue in `build_managers_table` LEFT JOIN
   fan-out that predates the rewrite. Add as a separate ROADMAP item;
   full-replace routing lets Phase 1 land without fixing it first.
4. `VALIDATOR_MAP[parent_bridge|managers|cik_crd_links|cik_crd_direct] = None`
   with the standard load-bearing warn.

Sequencing implication: `fetch_13dg.py` and `fetch_ncen.py` must
continue to run *after* `build_managers.py` (unchanged pipeline
order). Staging doesn't affect this since post-promotion the prod
`managers` is the CTAS output, ready for ADD COLUMN / UPDATE.

---

## 3. Downstream readers survey (0.3)

Live readers (excluding `scripts/retired/**`):

### `parent_bridge`
| File:line | Kind |
|---|---|
| `scripts/build_entities.py:11,358,372,388,945` | READ (entity rollup seed) + evidence comment |
| `scripts/build_managers.py:504` | READ (internal join) |
| `scripts/normalize_names.py:219-220` | SCHEMA (name normalization) |
| `scripts/validate_entities.py:497` | DOC (comment only) |
| `scripts/dm15c_amundi_sa_apply.py:4,278`, `dm14c_voya_amundi_apply.py:24,262` | DOC (references to past `parent_bridge_sync` artifacts) |
| `scripts/pipeline/registry.py:178` | SCHEMA (dataset spec — legacy owner note) |
| `scripts/migrations/add_last_refreshed_at.py:9` | DOC |
| `scripts/merge_staging.py:12` | DOC |
| `scripts/run_pipeline.sh:55` | DOC |
| `scripts/entity_sync.py:171,213` | SCHEMA (legacy source enum) |

**Live SELECT consumers:** `build_entities.py`. `validate_entities`
doesn't read the table — it's a docstring hit. Single non-self reader.

### `managers`
| File:line | Kind |
|---|---|
| `scripts/fetch_adv.py:262` | READ |
| `scripts/fetch_13dg.py:307,328` | READ (+ ALTER+UPDATE writer) |
| `scripts/fetch_ncen.py:362,400` | READ (+ ALTER+UPDATE writer) |
| `scripts/build_entities.py:172` | READ |
| `scripts/validate_entities.py:127,140,273,398,403,451,455,478` | READ (multiple gates) |
| `scripts/build_managers.py:514,534,553,564,574` | READ (self) |
| `scripts/queries.py:722,2360,2382` | READ (live app path) |
| `web/datasette_config.yaml:123` | READ (dashboard) |
| `notebooks/research.ipynb:1565,1636` | READ (notebook) |

**Live SELECT consumers:** at least 5 scripts + live API + dashboard.
Heavy coupling.

### `cik_crd_links`
| File:line | Kind |
|---|---|
| `scripts/build_entities.py:326` | READ |
| `scripts/build_managers.py:507` | READ (self) |
| `scripts/pipeline/registry.py:166-169` | SCHEMA |

### `cik_crd_direct`
| File:line | Kind |
|---|---|
| `scripts/build_entities.py:333` | READ |
| `scripts/build_managers.py:505` | READ (self) |
| `scripts/pipeline/registry.py:162-165` | SCHEMA |

**All four tables have exactly one external writer — this file.** The
multi-writer issue is confined to `managers` (via ALTER+UPDATE in
`fetch_13dg` / `fetch_ncen`).

---

## 4. `holdings` ALTER+UPDATE disposition (0.4)

### 4.1 What the block computes

`scripts/build_managers.py:517-540`:

1. `ALTER TABLE holdings ALTER COLUMN` × 4 → cast types to VARCHAR /
   BOOLEAN. Wrapped in `try/except pass` (`:525`) — assumes columns
   may already be correct shape.
2. `UPDATE holdings h SET inst_parent_name, manager_type, is_passive,
   is_activist FROM managers m WHERE h.cik = m.cik` — per-holding
   denormalization of manager metadata for fast aggregate reads.
3. `SELECT COUNT(*) FROM holdings WHERE manager_type IS NOT NULL` —
   progress reporting.

### 4.2 Why it matters

`holdings_v2` DDL already has these four columns
(`inst_parent_name VARCHAR`, `manager_type VARCHAR`, `is_passive BOOLEAN`,
`is_activist BOOLEAN` — positions 5, 16, 17, 18). Prod has **12,270,984
rows with 100% population on all four columns** (verified).

Who populates them? Git / grep survey:

- `scripts/build_managers.py:527-536` — operates on the **dropped**
  `holdings` table, not `holdings_v2`. Dead.
- `scripts/backfill_manager_types.py:77-91` — operates on the
  **dropped** `holdings` table too (hard-coded `holdings.manager_type`
  reference at `:82-83,88-91`). Dead.
- `scripts/load_13f.py` — does not write `holdings_v2`; the pipeline
  framework `promote_13f.py` is still *proposed*
  (`registry.py:88 "scripts/promote_13f.py (proposed)"`).
- `scripts/enrich_holdings.py:147,228` — writes Group 3 columns
  (`ticker`, `security_type_inferred`, `market_value_live`,
  `pct_of_float`). **Does not touch any of the four manager columns.**
- No other writer found via `grep -rn "SET inst_parent_name\|
  inst_parent_name =\|UPDATE holdings_v2" scripts/`.

**Conclusion.** The 100% population is legacy — carried over from the
prior `holdings` → `holdings_v2` migration. **No live code path
re-populates these columns after new data lands.** When
`load_13f.py` / `promote_13f.py` begin writing new quarters to
`holdings_v2` (already partially live — the most recent quarter was
added by load_13f's rewrite per commit `a58c107`), the new rows land
with `NULL` in all four columns until a refresh step runs.

**Disposition.** Option (b) migrate, not (a) retire. Specifically:

- **Retire** the ALTER loop (holdings_v2 has these columns typed
  correctly already).
- **Retire** the COUNT reporting line (holdings_v2's population is
  monitored elsewhere).
- **Repoint** the UPDATE from `holdings` to `holdings_v2` — same
  `JOIN managers m ON h.cik = m.cik` / `SET ...` shape.
- Flag `backfill_manager_types.py:77-91` as a parallel block broken
  against the dropped `holdings` table; out of scope for this REWRITE
  but file a follow-up.

**Verification of disposition.** After Phase 1, a one-quarter
spot-check: pick the most recent quarter from `holdings_v2`, verify
all four columns are populated for >95% of rows (remaining NULLs =
CIKs with no `managers` row, same tail the current data has).

---

## 5. Retrofit gap analysis (0.5)

Beyond the Precheck list:

| Gap | Line | Notes |
|---|---|---|
| `--dry-run` | — | Standard retrofit |
| `--staging` (+ `db.get_db_path()`, `db.connect_write()`) | `:26`, `:588` | Script connects via `duckdb.connect(DB_PATH)` at `:588` — wire through `db.connect_write()` |
| `--test` | — | Comes with `--staging` plumbing via `db.set_test_mode` |
| Fail-fast on missing inputs | `:227`, `:305` | No guard that `filings_deduped` / `adv_managers` exist before first SELECT. Pattern from `load_13f.py` REWRITE §5: raise with actionable message |
| Per-table `data_freshness` | `:603-606` | Currently only `managers` stamped. Add `parent_bridge`, `cik_crd_links`, `cik_crd_direct` |
| `UPDATE holdings` lacks try/except | `:527-536` | Will raise on prod today; but retire the block (see §4) |
| Fuzzy-match loop checkpoint | `:358-398` | Long-running loop (~30 min on 40k filers) — add progress checkpoint every 5k rows with `flush=True` (have `flush`-less `print` at `:394-398` already; retrofit to `flush=True`) |
| `seed_staging()` invocation | `:588` | When `--staging`, must call `db.seed_staging()` before first read so reference tables (`filings_deduped`, `adv_managers`) are available in staging DB |

No additional surprise retrofits surfaced.

---

## 6. Proposed rewrite surface (0.6)

### 6.1 `holdings` block retirement + repoint

- Delete `:520-525` ALTER loop.
- Delete `:537-540` COUNT reporting.
- Repoint `:527-536` UPDATE: `UPDATE holdings h` → `UPDATE holdings_v2 h`.
  Keep the `FROM managers m WHERE h.cik = m.cik` and `SET` clause as
  today.
- Wrap the UPDATE in `if not dry_run:` and print a dry-run projection
  of affected row count instead.

### 6.2 INF1 staging routing

- Add `parent_bridge` and `cik_crd_direct` to `db.CANONICAL_TABLES`
  (`db.py:115-118`).
- Declare in `promote_staging.PK_COLUMNS` (`promote_staging.py:49-63`):
  - `"parent_bridge": ["cik"]`
  - `"cik_crd_direct": ["cik"]`
- `VALIDATOR_MAP[parent_bridge|cik_crd_direct] = None` with warn.

### 6.3 New `"rebuild"` promote kind for `managers` and `cik_crd_links`

- Add a `PROMOTE_STRATEGY` dict (or equivalent) in `promote_staging.py`
  alongside `PK_COLUMNS`, default `"diff"`, override
  `{"managers": "rebuild", "cik_crd_links": "rebuild"}`.
- Extend `_apply_table` with a branch on `"rebuild"`:
  `DELETE FROM prod.tbl; INSERT INTO prod.tbl SELECT * FROM stg.tbl`
  inside the existing transaction. Snapshot and rollback paths are
  unchanged (snapshots are full-table CTAS already).
- Add both tables to `db.CANONICAL_TABLES`.
- `VALIDATOR_MAP[managers|cik_crd_links] = None` with warn.
- Alternative under consideration: skip `managers` from staging
  routing entirely given the three-writer / data-quality /
  fan-out cluster; instead leave `build_managers.py --staging`
  writing to `13f_staging.duckdb:managers` for dry-run verification,
  but run the final promote in-place against prod. This weakens INF1
  for `managers` specifically — not recommended, but documented as a
  fallback if the `"rebuild"` kind reveals unexpected scope.

### 6.4 `--dry-run` flag

Standard shape per `load_13f.py` REWRITE:

- Opens read-only prod connection for reads; suppresses all DROP/
  CREATE/INSERT/UPDATE against staging or prod; prints projected
  row counts for each target table.
- For the `holdings_v2` UPDATE: report projected `rows_affected =
  SELECT COUNT(*) FROM holdings_v2 h JOIN managers m ON h.cik = m.cik
  WHERE h.<col> IS DISTINCT FROM m.<col>` per column.

### 6.5 `--staging` plumbing

- Replace `duckdb.connect(DB_PATH)` at `:588` with
  `db.connect_write()`.
- Add argparse `--staging` / `--test` flags and call
  `db.set_staging_mode` / `db.set_test_mode` before `connect_write`.
- Call `db.seed_staging()` immediately after `db.set_staging_mode` so
  `filings_deduped` and `adv_managers` are available in staging.
  (Already in `db.REFERENCE_TABLES`; `parent_bridge` also already
  there.)
- Remove hard-coded `DB_PATH` at `:26`.

### 6.6 Per-table freshness

Add `record_freshness(con, t)` for `parent_bridge`, `cik_crd_links`,
`cik_crd_direct` alongside the existing `managers` call at `:604`.
Add `holdings_v2` freshness stamp after the repointed UPDATE
succeeds.

### 6.7 Fail-fast inputs

Before first SELECT: raise with actionable message if
`filings_deduped` or `adv_managers` is missing or has 0 rows.

### 6.8 Test plan

1. **Dry-run clean.** `python3 scripts/build_managers.py --dry-run`
   against prod: prints projected counts, zero writes observed (verify
   `MAX(last_computed_at)` on `data_freshness` is unchanged and no
   new snapshots appear in prod).
2. **Staging real run.**
   - `python3 scripts/sync_staging.py --tables parent_bridge,cik_crd_direct,cik_crd_links,managers`
     (extend `sync_staging.py` or use `db.seed_staging()` precedent —
     these are canonical, not entity tables; may require a parallel
     `sync_canonical_staging.py` or extension of existing sync path).
   - `python3 scripts/build_managers.py --staging` — writes four
     tables to `13f_staging.duckdb`.
   - Row-count parity vs prod within natural drift: `parent_bridge`
     within ±50 rows (seed matching is deterministic; drift comes
     from new quarters in `filings_deduped`); `managers` within
     ±100 rows; `cik_crd_links` / `cik_crd_direct` within ±20.
3. **promote_staging dry-run.**
   `python3 scripts/promote_staging.py --dry-run --tables parent_bridge,cik_crd_direct,cik_crd_links,managers`
   — verify the new `rebuild` path reports `would_delete` + `would_add`
   as full-table counts, standard diff path reports line-level deltas
   for the two entity-style canonical tables.
4. **`holdings_v2` enrichment parity.** After the repointed UPDATE
   runs against staging, verify that the four columns populate for
   >95% of rows in the latest quarter, matching prod's current 100%
   legacy population on older quarters.
5. **Downstream reader sanity.** Spot-check three live consumers:
   - `python3 scripts/validate_entities.py --prod` — passes
     (`managers` count + AUM gates).
   - `python3 scripts/compute_flows.py --staging --dry-run` — no
     new NULL `inst_parent_name` / `manager_type` warnings.
   - `web/datasette_config.yaml` count query returns same
     `managers` row count.
6. **Full promotion against staging.**
   `python3 scripts/promote_staging.py --approved --tables
   parent_bridge,cik_crd_direct,cik_crd_links,managers` — snapshot
   taken, changes applied, validators emit warn, no auto-rollback.

### 6.9 Sequencing

No external dependencies remain. Batch 3 closes with this block after
Phase 1 + 2 + 4 land. Post-completion, all five Batch 3 REWRITE
targets are done.

---

## 7. Out of scope

- Fixing `managers` CIK duplication from LEFT JOIN fan-out at
  `build_managers_table` `:429-512`. Data-quality bug, not retrofit.
  Separate ROADMAP item.
- Fixing `backfill_manager_types.py:77-91` against the dropped
  `holdings` table. Parallel broken block, separate fix.
- Promotion-strategy-per-table refactor in `promote_staging.py`
  beyond the single `"rebuild"` branch added here — if future Batch
  tables need bespoke strategies, handle at that time.
- INF17 Phase 3 gate tuning (`_BRAND_STOPWORDS` expansion,
  city/state compatibility edge cases) — separate INF17 Phase 4.
- Retiring `scripts/pipeline/registry.py:178-182`'s claim that
  `parent_bridge` is owned by `build_entities.py` — inconsistent with
  reality (this file writes it). Minor docs-only cleanup; can land
  with Phase 1 commit.
- Adding a formal PK/UNIQUE constraint to any of the four tables at
  the DDL level. Prod has degraded schema by policy
  (`ENTITY_ARCHITECTURE.md`); matching it keeps staging and prod
  lossless. Use `PK_COLUMNS` logical keys instead.
