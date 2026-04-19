# BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE (INF39) — Phase 0 Findings

_Prepared: 2026-04-19 — branch `block/schema-diff-inf39` off main HEAD `12e172b`._

_Precedent: `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` §14.0 — pct-of-so Phase 4 prod apply aborted on `DependencyException` because staging had 0 non-PK indexes on `holdings_v2` while prod had 4. Staging-only Phase 2 validation passed silently. Tactical fix: capture-and-recreate in migration 008 amendment (commit `ea4ae99`). This block builds the pre-flight detection that would have caught the divergence before Phase 4 ever started._

Scope locked per block prompt:
- L3 canonical tables only.
- Python script, structured output + YAML accept-list.
- Read-only comparison; no auto-remediation.
- Future extensions captured as **INF45** (L4 derived) and **INF46** (L0 control plane). Explicitly in-scope as deferred items.

Phase 0 is investigation only — no code files outside this doc, no DB writes, no pipeline runs.

---

## §1. L3 table inventory

Source: `docs/data_layers.md` §1 (layer definitions) + §2 (complete inventory).
Cross-checked against live prod (`data/13f.duckdb`) and staging (`data/13f_staging.duckdb`) — every table listed is present in prod.

**30 tables** fall in the L3 comparison set:

**Core facts (3)** — `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`

**Reference / other L3 (11)** — `securities`, `market_data`, `short_interest`, `fund_universe`, `shares_outstanding_history`, `adv_managers`, `ncen_adviser_map`, `filings`, `filings_deduped`, `cusip_classifications`, `_cache_openfigi`

**Entity MDM — core tables (7)** — `entities`, `entity_identifiers`, `entity_relationships`, `entity_aliases`, `entity_classification_history`, `entity_rollup_history`, `entity_overrides_persistent`

**Entity MDM — additional L3 tables (6)** — `cik_crd_direct`, `cik_crd_links`, `lei_reference`, `other_managers`, `parent_bridge`, and the two 13D/G progress tables `fetched_tickers_13dg`, `listed_filings_13dg`

**Staging-only companions (2)** — `entity_identifiers_staging`, `entity_relationships_staging`. These are L3-staging-only per §2 but they exist on both DBs (soft-landing queues / INF1 framework). Included because their DDL also drifts.

**Ambiguity flagged:**
- `entity_current` (L4 VIEW) is not in the L3 table set for this block — it lives in prod but not in staging. Flagged for **INF45** (L4 derived extension). Recorded in §9.
- `_cache_openfigi` is labeled "L3 (reference cache)" — included despite the parenthetical; it is a canonical table, not derived.
- The 2 `*_staging` tables straddle the L3 line. Including them is worth it because they drive the MDM soft-landing queue and already show divergence (see §3).

Rollback / snapshot artifacts (`*_snapshot_*`) are **excluded** from the parity check by design — they are per-promote audit tables, not canonical.

---

## §2. Schema-dimension taxonomy

For each L3 table the parity check compares five dimensions. Introspection path, whether comparison is meaningful, and known edge cases below.

### 2.1 Columns

**Source:** `duckdb_columns()` filtered by `schema_name='main' AND table_name=?`, ordered by `column_index`.
**Fields captured:** `column_name`, `data_type`, `is_nullable`, `column_default`.
**Comparable:** yes — every field. Order matters (CTAS preserves column order; out-of-order columns signal a broken DDL pair).
**Edge cases:**
- `column_default` is a free-text SQL expression. Lexical diffs cause noise: prod stores `'cik'` while staging may store it without quoting depending on how the default was added. Normalize by parsing through DuckDB's own pretty-printer where possible, or accept a free-text mismatch that the accept-list can cover.
- `is_nullable` can differ silently from the NOT NULL constraint view in §2.3 — both are authoritative on DuckDB.
- Generated columns and IDENTITY columns are rare here but surface as `column_default = 'nextval(...)'`. See §3 for live examples on `entity_overrides_persistent.override_id` and `entity_relationships_staging.id`.

### 2.2 Indexes

**Source:** `duckdb_indexes()` filtered by `schema_name='main' AND table_name=?`.
**Fields captured:** `index_name`, `is_unique`, `is_primary`, `sql`.
**Comparable:** yes. Filter `is_primary=false` if PK indexes are tracked separately via §2.3; otherwise include. The PK-auto index DuckDB creates is not surfaced here — only user-declared indexes and UNIQUE indexes appear.
**Edge cases:**
- The `sql` column is the canonical DDL. String-compare works if both DBs created the index from identical DDL. Whitespace / quoting differences will cause false-positive diffs.
- Composite index column order is significant (`(cik, quarter)` ≠ `(quarter, cik)`). Do not normalize.
- `is_unique=true` + `is_primary=false` is a UNIQUE constraint backed by an index. Example on prod: `idx_market_ticker` UNIQUE on `market_data(ticker)`.
- A PK declared on the table (`shares_outstanding_history`) surfaces as a UNIQUE index named `idx_soh_pk` in some states; the parity check must reconcile "PK in constraints" vs "UNIQUE-not-primary index" as equivalent, or the two presentations will diff.
- **This is the dimension that bit us.** Missing prod-side index ⇒ staging validation never exercises the ALTER guard path.

### 2.3 Constraints

**Source:** `duckdb_constraints()` filtered by `schema_name='main' AND table_name=?`.
**Fields captured:** `constraint_type`, `constraint_text`.
**Types seen on L3:** `PRIMARY KEY`, `NOT NULL`. **Not seen:** `UNIQUE` (declared as indexes instead), `CHECK`, `FOREIGN KEY` (codebase avoids FKs on purpose — promote is app-enforced).
**Comparable:** yes. `constraint_text` is useful for PK column list; NOT NULL rows have `constraint_text='NOT NULL'` without column identity (you pair with §2.1 `is_nullable` to identify the column).
**Edge cases:**
- Same logical NOT NULL can appear in §2.1 `is_nullable=false` AND §2.3 as a `NOT NULL` row. Treat §2.1 `is_nullable` as the authoritative per-column field; use §2.3 to surface PK / CHECK / FK only.
- PK presentation can be either a `PRIMARY KEY` constraint row here OR a UNIQUE index in §2.2. DuckDB is inconsistent depending on CTAS vs CREATE TABLE path. The parity check must dedupe.

### 2.4 Triggers

**Source:** DuckDB has **no trigger support** (confirmed empirically; no `duckdb_triggers()` system function exists; `CREATE TRIGGER` is not supported in DuckDB 0.10.x–1.x).
**Comparable:** vacuous. The dimension exists in the taxonomy for completeness but the check is a constant `no triggers on either side, confirm empty set`. If DuckDB adds trigger support this slot pre-exists.
**Recommendation:** keep the dimension in the script but make it a single-shot assertion that should always pass; fail-with-warning if a future DuckDB version surfaces one.

### 2.5 Table-level DDL / metadata

**Source:** `duckdb_tables()` column `sql` (CTAS-reconstructed DDL) + `estimated_size`.
**Fields captured:** `sql` (canonical CREATE TABLE ...), `internal`, row count (via `SELECT COUNT(*)` — separate query, for sanity only).
**Comparable:**
- `sql` **no** — DuckDB's `duckdb_tables().sql` reflects how the table was last created (CTAS, CREATE TABLE, or recreated after migration). Two tables with identical columns + types + defaults can produce different `sql` text. Use §2.1 + §2.3 as the canonical column-level comparison; treat `sql` as an advisory diff only.
- Row count **no** — explicitly out of scope for a schema-parity check (staging is a subset by design). Surface only as sanity context in the report header ("prod 12.27M rows, staging 12.27M rows — same order of magnitude").

### Dimension comparison matrix

| Dimension | Prod vs staging comparison makes sense? | Catches pct-of-so class of bug? |
|-----------|-----------------------------------------|--------------------------------|
| Columns | yes | no (pct-of-so was column-identical) |
| Indexes | yes | **yes — this is the one** |
| Constraints | yes | no |
| Triggers | vacuous on DuckDB | n/a |
| Table-level DDL / metadata | row count no; DDL text advisory | no |

---

## §3. Current divergence survey (empirical baseline)

Introspection run: 2026-04-19, read-only against `data/13f.duckdb` and `data/13f_staging.duckdb`. Raw dump pickled to `/tmp/schema_diff_raw.pkl` during Phase 0 (not committed).

### 3.1 Summary numbers

- **L3 tables compared:** 30
- **Tables with at least one schema divergence:** 13 / 30
- **Tables clean:** 17 / 30 (no differences across any dimension)
- **Total divergence rows:** 60
  - Index divergences: 11 tables → 30 rows (29 missing-in-staging, 1 missing-in-prod)
  - Column default / nullability diffs: 7 tables → 19 rows
  - Constraint (PK + NOT NULL) diffs: 5 tables → 11 rows
  - Trigger divergences: 0 (DuckDB has no triggers)
  - Table-DDL text divergences: not counted — advisory only

### 3.2 Index divergences (11 tables)

**Missing-in-staging (29 rows across 10 tables):**

| Table | Missing indexes | Notes |
|-------|-----------------|-------|
| `holdings_v2` | `idx_hv2_cik_quarter`, `idx_hv2_entity_id`, `idx_hv2_rollup`, `idx_hv2_ticker_quarter` | **The pct-of-so precedent.** 4 indexes. |
| `fund_holdings_v2` | `idx_fhv2_entity`, `idx_fhv2_rollup`, `idx_fhv2_series` | 3 indexes — next v2 rename would have hit the same trap. |
| `beneficial_ownership_v2` | `idx_bov2_entity` | 1 index. |
| `cusip_classifications` | `idx_cc_canonical`, `idx_cc_priceable_active`, `idx_cc_retry` | 3 indexes. |
| `market_data` | `idx_market_ticker` | 1 UNIQUE index on `ticker`. Functions as a de-facto UNIQUE constraint in prod that staging lacks. |
| `entity_aliases` | `idx_ea_active`, `idx_ea_name` | 2 indexes. |
| `entity_relationships` | `idx_er_child`, `idx_er_parent` | 2 indexes. |
| `entity_rollup_history` | `idx_rollup_parent` | 1 index. |
| `entity_identifiers_staging` | `idx_eis_entity`, `idx_eis_identifier`, `idx_eis_pending` | 3 indexes on staging-soft-landing table. |
| `entity_relationships_staging` | `idx_ers_child`, `idx_ers_status` | 2 indexes. |

**Missing-in-prod (1 row across 1 table):**

| Table | Missing index | Notes |
|-------|---------------|-------|
| `shares_outstanding_history` | `idx_soh_pk` — UNIQUE on `(ticker, as_of_date)` | Staging has explicit UNIQUE index; prod has the same uniqueness declared as a `PRIMARY KEY` constraint. Likely equivalent semantically but the parity check will flag it until the comparator normalizes PK ↔ UNIQUE-index. |

### 3.3 Column default / nullability divergences (7 tables, 19 rows)

Pattern: prod has rich defaults and NOT NULL stamps; staging has loose nullable columns with no defaults. Every diff is prod-tighter-than-staging. Zero column name or type mismatches — staging has the right shape, just without the constraints.

| Table | Columns with diff | Nature of diff |
|-------|-------------------|----------------|
| `entity_overrides_persistent` | `override_id`, `action`, `still_valid`, `applied_at`, `created_at`, `identifier_type`, `rollup_type` | 7 cols — defaults (`nextval`, `now()`, literal strings, bool cast) + NOT NULL, all dropped in staging |
| `entity_relationships_staging` | `id`, `child_entity_id`, `owner_name`, `review_status`, `created_at` | 5 cols — sequence default, NOT NULLs, `'pending'` default, `CURRENT_TIMESTAMP` |
| `entity_rollup_history` | `routing_confidence` | 1 col — `'high'` default missing in staging |
| `fund_universe` | `series_id` | 1 col — NOT NULL missing in staging |
| `lei_reference` | `lei` | 1 col — NOT NULL missing in staging |
| `securities` | `is_active` | 1 col — `CAST('t' AS BOOLEAN)` default missing in staging |
| `shares_outstanding_history` | `ticker`, `as_of_date`, `shares` | 3 cols — NOT NULLs missing in staging |

### 3.4 Constraint divergences (5 tables)

Prod has explicit PRIMARY KEY and NOT NULL declarations that staging lacks. Five tables in this bucket:

| Table | Prod constraints | Staging constraints |
|-------|------------------|----------------------|
| `entity_overrides_persistent` | 3× NOT NULL | none |
| `entity_relationships_staging` | 2× NOT NULL | none |
| `fund_universe` | 1× NOT NULL + PRIMARY KEY(`series_id`) | none |
| `lei_reference` | 1× NOT NULL + PRIMARY KEY(`lei`) | none |
| `shares_outstanding_history` | 3× NOT NULL + PRIMARY KEY(`ticker`, `as_of_date`) | none |

Note overlap with §3.3 — the NOT NULL surfaces in both §3.3 (via `is_nullable`) and §3.4 (via `duckdb_constraints`). The script must dedupe these so a single NOT NULL drift is one divergence row, not two.

### 3.5 Sequences & views (peripheral — tracked for context)

**Sequences:** identical on both DBs (7 sequences: `entity_id_seq`, `identifier_staging_id_seq`, `impact_id_seq`, `manifest_id_seq`, `override_id_seq`, `relationship_id_seq`, `resolution_id_seq`). No action.

**Views:**
- Prod: `entity_current`, `ingestion_manifest_current` (2 user views)
- Staging: `entity_identifiers_staging_review`, `ingestion_manifest_current` (2 user views)
- Divergence: `entity_current` missing in staging; `entity_identifiers_staging_review` missing in prod.

`entity_current` is an L4 VIEW (memory + §data_layers §2). Out of L3 scope — flagged for **INF45**. `entity_identifiers_staging_review` is a staging-only review helper — out of scope.

### 3.6 What §3 tells us

- pct-of-so exposed **one** table with drift. The real state is **13 L3 tables with drift** — the pct-of-so failure was not an outlier, it was the first time a v2 rename happened to land on one of the 13.
- All index drift is prod-tighter except for `shares_outstanding_history` where staging has the extra index — that one is a PK-presentation mismatch, not a real divergence.
- Column drift is purely constraint/default loss in staging, not column-shape drift. This is consistent with staging being built from CTAS patterns (`CREATE TABLE ... AS SELECT`) which do not preserve defaults or NOT NULL from the source. The root cause is structural, not accidental.
- Next v2 rename on `fund_holdings_v2`, `beneficial_ownership_v2`, `securities`, or any entity MDM table would have hit the same `DependencyException` class of bug.

---

## §4. Accept-list design

### 4.1 Format

Proposed path: `config/schema_parity_accept.yaml`. Top-level `accepted:` list; each entry is one divergence row.

```yaml
accepted:
  - table: holdings_v2
    dimension: indexes
    detail: idx_hv2_cik_quarter
    justification: |
      Staging is a row-subset and does not need the prod read-path index.
      Known-absent until staging rebuild pattern is fixed (INF40).
    expiry_date: 2026-05-31
    reviewer: serge.tismen
  - table: shares_outstanding_history
    dimension: indexes
    detail: idx_soh_pk
    justification: |
      Staging carries an explicit UNIQUE(ticker, as_of_date) index;
      prod expresses the same constraint as a PRIMARY KEY. Equivalent
      semantically. Normalize PK↔UNIQUE-index in comparator (v1.1) and
      remove this entry.
    expiry_date: 2026-04-30
    reviewer: serge.tismen
```

### 4.2 Field contract

| Field | Required | Notes |
|-------|----------|-------|
| `table` | yes | L3 table name |
| `dimension` | yes | one of `columns`, `indexes`, `constraints`, `triggers`, `ddl` |
| `detail` | yes | dimension-specific: index name, column name, constraint text, etc. |
| `justification` | yes | prose; enforced length floor (e.g., ≥30 chars) so "tbd" is rejected |
| `expiry_date` | optional | ISO date; warn 14 days before; **fail** on/after expiry with reason "accept-list entry expired — reconsider" |
| `reviewer` | yes | who accepted; email or GH handle |

### 4.3 Script behavior toward the accept-list

- **Divergence matches an accept-list entry** → log at WARN, do not fail.
- **Divergence does not match** → FAIL, exit code 1.
- **Accept-list entry has no matching divergence** (stale entry) → WARN "accept-list entry X matches no current divergence — remove"; does not fail unless `--strict-accept` set.
- **Accept-list entry expired** → FAIL, regardless of divergence. Forces re-review.
- **`--fail-on-accepted`** → treat accept-list entries as still-fail. Use in CI "drift-hardening" mode to ratchet toward zero accepted drift over time.

### 4.4 First seed entry (for v1 ship)

Draft includes one entry for `shares_outstanding_history.idx_soh_pk` (the PK↔UNIQUE-index equivalence) with a short expiry forcing the comparator normalization in v1.1. **All other divergences in §3 are `FAIL`** at v1 ship — Serge decides per-entry at block close whether to accept, remediate, or defer.

---

## §5. Script interface design

### 5.1 Invocation

```
python3 scripts/validate_schema_parity.py [options]
```

Default behavior: L3 tables, full dimension check, compare `data/13f.duckdb` vs `data/13f_staging.duckdb`.

### 5.2 Flags

| Flag | Meaning | Default |
|------|---------|---------|
| `--prod PATH` | prod DB path | `data/13f.duckdb` |
| `--staging PATH` | staging DB path | `data/13f_staging.duckdb` |
| `--tables t1,t2,...` | subset of L3 tables | all 30 |
| `--dimensions d1,d2` | subset of `columns,indexes,constraints,triggers,ddl` | all 5 |
| `--accept-list PATH` | accept-list path override | `config/schema_parity_accept.yaml` |
| `--fail-on-accepted` | treat accept-list entries as still-fail | false |
| `--json` | emit JSON to stdout | false (default: human table) |
| `--verbose` | per-table trace to stderr | false |

### 5.3 Exit codes

| Code | Meaning |
|------|---------|
| 0 | parity — no unaccepted divergence |
| 1 | unaccepted divergence OR expired accept-list entry |
| 2 | invocation error (missing file, bad YAML, etc.) |

### 5.4 Output contract

- **Default (human):** markdown-esque table per dimension with table count header; colored FAIL / WARN / OK if stdout is a tty.
- **`--json`:** structured payload `{ "divergences": [ ... ], "accepted": [ ... ], "summary": { "total": N, "accepted": M, "unaccepted": K } }`. One object per divergence row so CI can count and diff between runs.
- stderr: logging / warnings only. stdout: the authoritative result.

### 5.5 Integration shape

- Invoke from `make schema-parity` target (add to Makefile in Phase 1).
- Invoke from `scripts/pipeline/phase2_preflight.py` (new wrapper added Phase 1; sequences schema-parity + entity-gate + freshness into one pre-Phase-2 gate).
- Invoke standalone from ad hoc investigation ("did my migration drift anything?").

---

## §6. Integration into block shape — proposed patch

### 6.1 Current Rewrite block shape

From `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md`:

```
Phase 0 — investigation / findings doc
Phase 1 — implementation (staging DB only)
Phase 2 — staging validation (all gates must pass)
HARD STOP — await Serge's explicit Phase 4 sign-off
Phase 4 — prod apply
```

Phase 2's implicit assumption was that staging schema equals prod schema up to row content. That assumption failed quietly on pct-of-so.

### 6.2 Proposed post-INF39 shape

```
Phase 0 — investigation / findings doc
Phase 1 — implementation (staging DB only)
Phase 2 — staging validation
  § Phase 2 pre-flight (NEW):
    - validate_schema_parity.py MUST pass before any validation workload runs.
    - Any unaccepted divergence halts Phase 2 with a structured report.
    - Remediation: either resync staging to prod, or add an accept-list entry
      with justification + expiry + reviewer. Re-run Phase 2.
  § Phase 2 validation proper
HARD STOP — await Serge's explicit Phase 4 sign-off
Phase 4 — prod apply
```

### 6.3 Draft addendum patch (to be applied in Phase 1, not Phase 0)

Append to `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` as §14.11 or to the generic Rewrite-block template doc (if one exists; if not, create `docs/BLOCK_TEMPLATE.md`):

> ### Phase 2 schema-parity pre-flight (INF39)
>
> Before any Phase 2 staging validation workload begins, run
> `python3 scripts/validate_schema_parity.py`. Expected exit 0 with
> no unaccepted divergences. Any divergence surfaces as one of:
>
> 1. **Drift to remediate** — apply migration/DDL to staging so it
>    matches prod. Re-run pre-flight.
> 2. **Drift to accept** — add accept-list entry with prose
>    justification, expiry date, and reviewer. Re-run pre-flight.
>
> Pre-flight failure halts Phase 2. Do not bypass.
>
> Precedent: pct-of-so Phase 4 `DependencyException` on
> `holdings_v2` RENAME (`§14.0`). Staging had zero indexes; prod
> had four; the ALTER guard only fires with indexes present.

**Do not apply the patch in Phase 0** — drafted here, applied at Phase 1 close once the script lands.

---

## §7. Phase 1 implementation plan

Ordered tasks. Phase 1 = build the script. No schema changes to either DB.

1. **Scaffold** `scripts/validate_schema_parity.py` with CLI (argparse), DB path discovery (default paths from `scripts/pipeline/shared.py` if it defines them, else hardcoded), and logging setup.
2. **L3 table list** as a module-level constant sourced from §1 of this doc. Option to read from `docs/data_layers.md` at runtime is out of scope — keep the list in code for v1.
3. **Introspection layer** — one function per dimension (`compare_columns`, `compare_indexes`, `compare_constraints`, `compare_triggers`, `compare_ddl`). Each returns `list[Divergence]`. `Divergence` dataclass: `(table, dimension, detail, prod_value, staging_value)`.
4. **Comparator normalizer** for known-equivalent shapes:
   - PK constraint ↔ UNIQUE index with `is_primary=False` + same columns (drop the `idx_soh_pk` false-positive).
   - `is_nullable=False` in columns ↔ `NOT NULL` row in constraints (dedupe — surface once, not twice).
   - Whitespace in `sql` text normalized before comparison.
5. **Accept-list parser** — YAML → `list[AcceptEntry]`; schema-validate with `jsonschema` or a small hand-rolled validator; reject missing-required-field entries with exit 2.
6. **Matcher** — one divergence vs accept-list entries; match requires `(table, dimension, detail)` exact; expiry check inline.
7. **Reporter** — human table, JSON mode, colored tty output, summary header.
8. **Exit code logic** per §5.3.
9. **Unit tests** — `tests/test_schema_parity.py` with fixtures for each normalization case (PK↔index, nullable-dedupe, stale accept entry, expired entry, `--fail-on-accepted` mode). Target ≥90% branch coverage of the matcher.
10. **Integration wiring** — add `make schema-parity` target; optionally wire a Phase 2 pre-flight wrapper (decide with Serge whether to ship that in Phase 1 or a follow-up block).
11. **Seed `config/schema_parity_accept.yaml`** with the single v1 seed entry from §4.4, committed alongside the script.
12. **Run once against current DBs** — expect the §3 baseline: ~60 divergence rows. Accept-list is empty at seed time; script exits 1 with the full list. That list becomes the Phase 2 test input.

Commit shape: one commit for script + tests + accept-list stub + Makefile target.
Message: `INF39 Phase 1: validate_schema_parity.py + L3 schema parity check`.

---

## §8. Phase 2 staging validation plan

Phase 2 validates the script itself against current DB state (not a pipeline workload; the script has no data dependency).

### 8.1 Test cases — expected outcomes

| # | Scenario | Expected exit | Expected report |
|---|----------|---------------|-----------------|
| 1 | Baseline run, empty accept-list | 1 | ~60 divergence rows across 13 tables per §3 |
| 2 | Baseline run, all §3 divergences accepted | 0 | WARN rows only |
| 3 | `--tables holdings_v2` with empty accept-list | 1 | 4 index rows |
| 4 | `--dimensions columns` with empty accept-list | 1 | 19 column rows (§3.3) |
| 5 | Accept-list entry with expired date | 1 | expired entry reason surfaced |
| 6 | Stale accept-list entry (matches no divergence) | 0 with WARN | "remove stale entry" warning |
| 7 | `--fail-on-accepted` with any accept-list matches | 1 | accepted entries also counted as fail |
| 8 | Same DB vs itself (`--prod X --staging X`) | 0 | zero divergences |
| 9 | Missing staging file | 2 | invocation error |
| 10 | Malformed YAML | 2 | YAML error surfaced |

### 8.2 Hard gate for Phase 2 close

Test 1 must produce the exact §3 row count (60). Deviation indicates either (a) DBs changed since 2026-04-19 — re-baseline; or (b) comparator logic is wrong — fix.

### 8.3 Staging / prod state at Phase 2 close

Unchanged. No DDL applied to either DB during Phase 2 (the script is read-only). Remediation of the actual §3 divergences is a separate decision taken at block close (§10 open question Q1).

---

## §9. Future extensions — INF45, INF46

Recorded now so they don't get lost at block close.

### INF45 — extend schema-parity to L4 derived tables

**Scope:** add L4 tables (`summary_by_parent`, `summary_by_ticker`, `investor_flows`, `ticker_flow_stats`, `managers`, `benchmark_weights`, `fund_classes`, `fund_best_index`, `fund_index_scores`, `fund_name_map`, `index_proxies`, `peer_groups`, `fund_family_patterns`, `beneficial_ownership_current`) and the L4 VIEW `entity_current` to the parity comparator.

**Trigger:** concrete incident — an L4 build fails on prod where it passed on staging due to schema drift. Until that happens, L4 is rebuilt from L3 every cycle so drift self-corrects.

**Why deferred:** L4 tables are `DROP+CREATE-AS-SELECT` regenerated (mostly). Index and constraint drift there is lower-impact because each rebuild reshapes the table anyway. Adding L4 to the parity set now would be noisy without being informative.

**Priority:** low.

### INF46 — extend schema-parity to L0 control-plane tables

**Scope:** add L0 tables (`ingestion_manifest`, `ingestion_impacts`, `pending_entity_resolution`, `data_freshness`, `cusip_retry_queue`, `schema_versions`) to the parity comparator.

**Trigger:** when a control-plane migration produces a silent staging/prod drift (pattern seen once historically on `data_freshness` when v2 vs non-v2 scripts wrote different schemas).

**Why deferred:** L0 is owned by `scripts/pipeline/manifest.py` + migration scripts. Drift is rare because there is a single writer per table and migrations stamp `schema_versions`. Adding L0 is process-tidiness; not prompted by incident.

**Priority:** low.

---

## §10. Open questions for Phase 1 sign-off

### Q1. Remediation of the §3 baseline — policy decision

The script will ship and immediately report ~60 divergence rows. Three options:

- **A. Accept all 60 at v1 seed.** Accept-list has 60 entries on day 1; script exits 0; real work = remediate over weeks, burning down the accept-list toward zero.
- **B. Fix all 60 at v1 seed.** Resync staging schema to prod before the script ships; accept-list is empty; script exits 0 because no divergence exists. Requires a staging DDL pass (~1 hour of work; §3 lists every change needed).
- **C. Hybrid — fix the index/constraint cluster, accept the PK-vs-index normalization, leave the defaults drift.** Cleanest operationally.

Recommendation: **B**. The §3 drift is mechanical and recovery is a single targeted staging rebuild. Starting the script at exit 0 makes "parity" the baseline state; anything new shows up as new drift. Option A poisons the well — every future run carries 60 background rows that humans stop reading.

Serge: A/B/C decision needed before Phase 1 ship.

### Q2. Script location — `scripts/` vs `scripts/pipeline/` vs `tools/`

`scripts/` is the bulk folder; `scripts/pipeline/` holds pipeline-coupled modules (`shared.py`, `manifest.py`, `registry.py`). Schema parity is a pipeline gate, so `scripts/pipeline/validate_schema_parity.py` fits. But it is also invoked ad hoc from the CLI, so top-level `scripts/validate_schema_parity.py` fits too. Convention check needed.

### Q3. `entity_current` (L4 VIEW) — include in this block or defer to INF45?

Memory note (2026-04-13): "entity_current is a VIEW — only user-defined view in prod; fixture/snapshot rebuilds must recreate it after tables land." Staging is missing the view. Including it in v1 makes sense; deferring to INF45 is consistent with scope lock. Serge's call.

### Q4. Phase 2 pre-flight wrapper — Phase 1 scope or follow-up?

The script runs standalone fine. Wiring it into a `scripts/pipeline/phase2_preflight.py` wrapper that sequences schema-parity + entity-gate + freshness is convenient but not strictly required for INF39. Include in Phase 1 scope or defer to a follow-up block?

### Q5. CI integration — in scope for this block?

Adding `validate_schema_parity.py --json` to the existing smoke CI job is one line. But CI runs against a fixture DB, not prod/staging paths. Does the fixture reproduce the drift? (Likely not — fixture is built fresh every run.) Decision: probably ship Phase 1 without CI integration; revisit once the §3 drift is remediated and parity is the baseline.

### Q6. Comparator normalization — how aggressive?

The §2 edge cases (PK↔UNIQUE-index, nullable-dedupe, whitespace in SQL text) are the known-safe normalizations. Are there others Serge wants normalized away by default (e.g., `CAST('t' AS BOOLEAN)` vs `TRUE`; `now()` vs `CURRENT_TIMESTAMP`)? Each normalization is a lossy simplification — easier to read, harder to audit.

Recommendation: start narrow (only the three in §7.4); expand only when Phase 2 test 1 surfaces a noise pattern that obscures real drift.

---

_End of Phase 0 findings. No code changes, no DB writes, no migrations. Findings doc is the only artifact._
