# Refinement validation — 2026-04-23

Session: `refinement-validation-2026-04-23` (investigation-only).
Scope: verify three assumptions behind Serge's v3 refinements to the
Phase B/C plan before they bake in. **No plan edits, no code fixes,
no DB writes, no tracker edits in this session.**

Read-only evidence sources: working-tree code, prod DuckDB opened
`read_only=True`, `git log`.

---

## §1 Summary — verdicts

| # | Refinement | Verdict | One-line |
|---|---|---|---|
| V-Q1 | "V2 is ready for production cycle duty without a feature-flag fallback" | **PARTIAL** | Code path equivalent; V2 is cycle-ready *but* the Makefile still points at V1 — the swap itself is the flag, so no separate fallback is needed. Minor gaps: freshness stamps and full-reload mode. |
| V-Q3 | "V1's grep caught every reader; B3 drops are safe as a single session" | **PARTIAL** | No operational SQL reader hits `raw_*` or `fund_holdings` (v1). Three low-risk residuals must co-land with the drops: `scripts/db.py REFERENCE_TABLES`, `scripts/pipeline/registry.py` L1 entries, and `notebooks/research.ipynb` dead-branch probe. |
| V-Q4 | "`migrate_batch_3a.py` is a genuine live owner of `fund_family_patterns`" | **PARTIAL (disconfirms live-owner claim)** | It is a one-shot seeder (single commit 2026-04-13, DB rows bit-identical to the in-code seed — zero drift, zero re-runs). The registry itself already describes the ongoing owner as manual. Move-to-oneoff is the more accurate classification, provided the registry `owner` field is updated in the same PR. |

Aggregate recommendation in §5.

---

## §2 V-Q1 — V2 cycle-readiness

### V-Q1.a — Path equivalence (admin-refresh vs scheduled)

**Code path (admin refresh):**
- `scripts/admin_bp.py:1274` `_run_pipeline_background()` → `get_pipeline("13f_holdings").run(scope)` → sets status `pending_approval`.
- `scripts/admin_bp.py:1620` `/api/admin/runs/{run_id}/approve` → `get_pipeline(row['source_type']).approve_and_promote(run_id)`.
- `scripts/pipeline/pipelines.py:23` registry resolves `"13f_holdings"` → `load_13f_v2.Load13FPipeline`.

**Code path (CLI, `--auto-approve`):**
- `scripts/load_13f_v2.py:788` `pipeline.run(scope)` → `scripts/load_13f_v2.py:797` `pipeline.approve_and_promote(run_id)`.

These invoke the **same two methods on the same class**. No admin-only
hook is conditioned on request origin. No scheduled-only branch. The
only semantic difference is the gate *between* steps: admin refresh
waits for a human click on `/approve`; CLI with `--auto-approve`
chains automatically. The promote code is identical.

**Finding:** path equivalence **holds**. Admin refresh is a faithful
proxy for a scheduled V2 run.

But the scheduled path does not yet exist: `Makefile:110-111` still
invokes `scripts/load_13f.py` (V1) for the `load-13f` target that
`quarterly-update` depends on, and there is no CI or cron invocation
of `load_13f_v2.py` anywhere in the tree (searched `.sh`, `Makefile`,
`.yml/.yaml`). The V2 "scheduled cycle" is a one-line Makefile edit
away; today it is latent.

### V-Q1.b — V2 test coverage vs V1

Test files that exercise V2:
- `tests/pipeline/test_load_13f_v2.py` — 10 tests (attributes, schema
  spec, parse correctness on a fixture TSV, `run()` halts at
  `pending_approval`, `approve_and_promote()` populates prod).
- `tests/test_admin_refresh_endpoints.py` — two tests patch
  `load_13f_v2.Load13FPipeline.run` / `.reject`.

Test files that exercise V1:
- **None.** `grep -r "load_13f" tests/` returns only V2 files. V1 has
  zero dedicated test coverage.

**Finding:** there are no V1-specific test behaviors to compare
against. "V2 test coverage vs V1" trivially passes because V1 has no
test baseline. This is a weak signal — it means "no regression visible
to tests", not "no regression exists".

### V-Q1.c — Behavior parity (direct code read)

V1 (`scripts/load_13f.py`, 422 LOC) writes to **prod**:
- `raw_submissions`, `raw_infotable`, `raw_coverpage`, `other_managers`
  (DROP+CREATE full-reload; DELETE-by-quarter incremental)
- `filings`, `filings_deduped` (DROP+CTAS rebuild from raw on every run)
- `record_freshness()` stamps on 6 tables (raw_*, other_managers,
  filings, filings_deduped) — `scripts/load_13f.py:393,400`
- **Does not touch `holdings_v2`.** That enrichment happens later in
  `scripts/build_managers.py:625 enrich_holdings_v2()`.

V2 (`scripts/load_13f_v2.py`, 819 LOC) writes to **staging** then
promotes to **prod**:
- `stg_13f_submissions`, `stg_13f_infotable`, `stg_13f_coverpage`,
  `stg_13f_othermanager`, `stg_13f_filings`, `stg_13f_filings_deduped`,
  `stg_13f_other_managers` (staging DB; cleaned up after promote per
  `_cleanup_staging`, `scripts/load_13f_v2.py:734`).
- `holdings_v2` (is_latest-flagged append, via base class
  `amendment_strategy='append_is_latest'`, amendment_key `(cik,
  quarter)`).
- `filings` (INSERT dedup by accession_number), `filings_deduped`
  (full DROP+CTAS rebuild from prod `filings`), `other_managers`
  (INSERT dedup on `(accession_number, sequence_number)`) — see
  `_promote_reference_tables`, `scripts/load_13f_v2.py:657`.
- `record_freshness()` stamps **`holdings_v2` only**, via base-class
  `stamp_freshness()` on `target_table` — `scripts/pipeline/base.py:958`.

**Differences classified:**

| V1 behavior | V2 equivalent | Class | Evidence |
|---|---|---|---|
| Writes `raw_submissions/infotable/coverpage` in prod | Writes `stg_13f_*` in staging DB; never in prod | **Intentional** — V2 docstring line 3–4; this is the whole point of B3. | `scripts/load_13f_v2.py:3-22` |
| `amended` flag dedup at query time via `filings_deduped` | `is_latest` flag set at load time via `append_is_latest` | **Intentional** — cleaner SCD-like semantics; mig-015 landed this | `scripts/migrations/015_amendment_semantics.py`; `scripts/load_13f_v2.py:258` |
| Full-reload mode (no `--quarter` loads all QUARTERS) | `--quarter` is required; no full-reload mode | **Unknown / potentially missed** — no docstring or PR comment explicitly retires full-reload | `scripts/load_13f.py:350` vs `scripts/load_13f_v2.py:761` |
| Freshness stamps on 6 tables (raw_*, other_managers, filings, filings_deduped) | Stamps only `holdings_v2` | **Acceptable for CI gate** — `scripts/check_freshness.py:28` only gates `holdings_v2`, `fund_holdings_v2`, etc.; per-table staleness on filings/raw is not gated anywhere. **Minor visibility loss** — individual table freshness no longer surfaces in `/api/v1/freshness`. | `scripts/check_freshness.py:28-36`; `scripts/pipeline/base.py:958-966` |
| `--dry-run` projects row counts from TSVs using in-memory DuckDB | `--dry-run` runs fetch+parse+validate, halts at `pending_approval`, staging retained | **Intentional; different semantics but both satisfy "no prod writes"** | `scripts/load_13f.py:283-330` vs `scripts/load_13f_v2.py:765,791` |

**Intentionally-dropped behaviors (with evidence):**
- `raw_*` prod writes — V2 docstring + stg_* tables
- Per-table freshness on raw_*/filings/other_managers — implied by
  `SourcePipeline.stamp_freshness()` stamping target_table only and by
  `check_freshness.THRESHOLDS` limiting gated tables to L3 facts
- Amendment dedup at query time — superseded by is_latest

**Unknowns / potentially missed:**
- Full-reload mode absence: acceptable operationally (quarterly cycle
  only adds the latest quarter), but no written evidence that this was
  a conscious drop. Flag before final swap.
- V1's `_stamp(con, [...filings, filings_deduped])` per run is gone.
  If any downstream alert depends on *stamping activity* of these
  tables (as opposed to the gated threshold), that signal goes silent.
  Audit: `grep -rn filings_deduped scripts/` shows no consumer of
  `data_freshness.last_computed_at` for these names.

### V-Q1 verdict

**PARTIAL — leaning confirmed.** V2 is cycle-ready. The "feature flag
fallback" Serge is considering dropping is unnecessary because the
current `Makefile:111` invocation of V1 **is** the flag: swapping V1
→ V2 is a single-line change, trivially reversible with a git revert.
A separate flag would just duplicate that reversibility.

**Caveats to surface in Phase B/C plan v3:**
1. The swap is a Makefile edit (plus optionally `scripts/update.py:75`
   for the legacy wrapper). Plan should name that edit explicitly.
2. Full-reload mode is lost — if a reseed of multiple quarters ever
   becomes necessary, operator must iterate quarters in a shell loop.
3. Per-table freshness stamps on filings/filings_deduped/other_managers
   will stop landing in `data_freshness` once V2 owns the cycle. No
   current consumer depends on them, but the registry entries at
   `scripts/pipeline/registry.py:112-121` (filings, filings_deduped)
   list `owner="scripts/load_13f.py"` and will be stale until updated.

---

## §3 V-Q3 — raw_* + fund_holdings exhaustive reader check

### V-Q3.a — grep across all formats

Command run:
```
grep -rn --include="*.py" --include="*.sh" --include="*.sql" \
  --include="*.ipynb" --include="*.md" --include="*.yml" \
  --include="*.yaml" --include="*.toml" --include="*.cfg" \
  --include="*.mk" --include="*.txt" \
  -E "raw_infotable|raw_coverpage|raw_submissions|\bfund_holdings\b" .
```
Filtered: `.git/`, `__pycache__`, `node_modules/`, `data/`, `.md` docs
(non-executable references). Raw count: **203 total hits**;
code/config-only (excluding docs): **~60 hits across ~12 files**.

Classification of non-trivial hits:

| File:line | Table | Class | Notes |
|---|---|---|---|
| `scripts/load_13f.py:*` (many) | `raw_*` | WRITER | Expected; V1 writes these. Dies when Makefile repoints. |
| `scripts/pipeline/registry.py:68-82` | `raw_submissions/infotable/coverpage` | REFERENCE (stale metadata) | `DatasetSpec` entries with `owner="scripts/load_13f.py"`. Must co-update when B3 drops tables. |
| `scripts/pipeline/registry.py:346` | `fund_holdings` | REFERENCE (comment) | Docstring notes `fund_holdings` was "dropped Stage 5" — already flagged stale. |
| `scripts/db.py:84` | `fund_holdings` | READER (defensive, swallows errors) | Listed in `REFERENCE_TABLES`; used by `seed_staging()` (`scripts/db.py:144`) which wraps each copy in `try/except` and silently continues on failure. Called only from `scripts/run_pipeline.sh:35` + a few `resolve_*.py` one-offs. `run_pipeline.sh` is explicitly blocked from web-triggered execution (`scripts/admin_bp.py:579`). **Not operational; still needs registry cleanup.** |
| `scripts/admin_bp.py:508` | `fund_holdings` | REFERENCE (dashboard key alias) | Tuple `('fund_holdings_v2', 'fund_holdings')` — table is `_v2`, the string `'fund_holdings'` is only the JSON key name in the stats response. Not a reader. |
| `scripts/admin_bp.py:581` | `fund_holdings` | REFERENCE (comment) | "prevent resurrection of legacy `fund_holdings`". Not a reader. |
| `scripts/queries.py:264,356,571,2092,2355,2691,2940,3034` | `fund_holdings` | REFERENCE (docstrings/comments) | All actual `FROM fund_holdings*` SQL in `queries.py` is against `fund_holdings_v2` (verified by `grep "FROM fund_holdings" scripts/queries.py` — 34 hits, all `_v2`). The `fund_holdings` in docstrings is stale terminology. |
| `scripts/build_fixture.py:224` | `fund_holdings` | REFERENCE (comment) | Line 193-230 uses `prod.fund_holdings_v2` in all DDL; line 224 is a stale docstring. |
| `scripts/enrich_holdings.py:685,696,706` | `args.fund_holdings` / `--fund-holdings` | NOT A TABLE REFERENCE | CLI flag name. The actual SQL target is `fund_holdings_v2`. |
| `notebooks/research.ipynb:21` | `raw_*` | REFERENCE (embedded output) | Output of `.fetchall()` printed into a prior run's notebook cell, listing tables. No runtime SQL. |
| `notebooks/research.ipynb:586-589` | `fund_holdings` | READER (defensive probe) | `SELECT 1 FROM fund_holdings LIMIT 1` inside `try/except: pass`. Sets `has_fund_holdings = False` gracefully when table is absent; dead branch thereafter. Not operational code. |
| `scripts/retired/fetch_nport.py` (many) | `fund_holdings` | RETIRED | Archived under `scripts/retired/`; allowlist in `admin_bp.py:582-587` excludes it (`BLOCK-1 2026-04-17 audit`). Dead. |
| `scripts/retired/fetch_13dg.py:878` | `fund_holdings` | RETIRED | Same. |
| `scripts/retired/unify_positions.py:3,7,97` | `fund_holdings` | RETIRED | Same. |
| `scripts/run_pipeline.sh:54` | `fund_holdings` | REFERENCE (comment) | Documents legacy pipeline steps; not executable SQL. |

### V-Q3.b — notebook check

`find notebooks/ -name "*.ipynb"` → only `notebooks/research.ipynb`.
Inspected: one dead-branch existence probe at line 586-589 (above),
one printed table listing at line 21. No other active references.

### V-Q3.c — fixture / test data check

`grep -rn raw_infotable\|raw_coverpage\|raw_submissions\|fund_holdings tests/`
returns **only** the binary `tests/fixtures/13f_fixture.duckdb`.
Queried the fixture DB: the four candidate-drop tables are **not
present** in the fixture (`information_schema.tables` returns empty).
Fixture already tracks the post-drop world.

### V-Q3.d — DB constraint check (read-only)

```sql
SELECT table_name, constraint_type, constraint_name
FROM information_schema.table_constraints
WHERE table_name IN ('raw_infotable','raw_coverpage','raw_submissions','fund_holdings')
   OR constraint_name LIKE '%raw_%' OR constraint_name LIKE '%fund_holdings%';
```
Result: **`[]`** (no rows). No FK or CHECK constraint references any
drop-target table. Safe from a constraint perspective.

### V-Q3.e — view dependency check

```sql
SELECT view_name, sql FROM duckdb_views()
WHERE sql ILIKE '%raw_infotable%' OR sql ILIKE '%raw_coverpage%'
   OR sql ILIKE '%raw_submissions%' OR sql ILIKE '%fund_holdings%';
```
Result: **`[]`**. Only two user views exist (`entity_current`,
`ingestion_manifest_current`); neither references drop targets.

### V-Q3 verdict

**PARTIAL.** The core claim "no hidden *operational* SQL reader exists"
is **confirmed**: zero FK/CHECK, zero views, zero tests, zero active
SQL queries hit `raw_*` or `fund_holdings` (v1).

Three **co-land cleanups** are required for a safe single-session B3:
1. `scripts/db.py:82-86 REFERENCE_TABLES` — remove `fund_holdings`.
2. `scripts/pipeline/registry.py:68-82` — remove three raw_* L1
   `DatasetSpec` entries. Also update line 113 (`filings` owner) and
   line 118 (`filings_deduped` owner) to `load_13f_v2.py` when Makefile
   repoints.
3. `notebooks/research.ipynb:586-589` — either update probe to
   `fund_holdings_v2` or delete the dead branch. (Manual; cosmetic.)

The two `admin_bp.py` references (`:508` tuple, `:581` comment) and the
`queries.py` stale docstrings are cosmetic — no correctness impact.

"B3 drops safe in a single session" is achievable **only** if items 1
and 2 above are part of the same diff. If they are not, the drops
succeed silently but the registry becomes a lying source-of-truth.

---

## §4 V-Q4 — `migrate_batch_3a.py` live-owner check

### V-Q4.a — Git history

```
git log --follow --all --format="%h %ad %s" --date=short -- scripts/migrate_batch_3a.py
```
**Single commit:** `731f4a0  2026-04-13  feat: Batch 3-A —
fund_family_patterns + data_freshness tables`.

The script has **never been edited since creation** (10 days ago).
No re-runs documented in ROADMAP (which logs this as a one-shot at
line 889).

### V-Q4.b — `fund_family_patterns` table state

```sql
DESCRIBE fund_family_patterns;
-- pattern           VARCHAR NOT NULL PRI
-- inst_parent_name  VARCHAR NOT NULL PRI
-- (no created_at / updated_at columns)

SELECT COUNT(*) FROM fund_family_patterns;  -- 83
```

**Drift test** — compare DB rows to the in-code
`_FAMILY_PATTERNS_FALLBACK` dict (which is the script's seed source via
`get_nport_family_patterns()`):

```
DB rows: 83
In-code fallback rows: 83
In DB but not in-code (manual adds): 0
In-code but not in DB (drift):       0
```

Bit-identical. Zero rows have been added, removed, or modified since
the 2026-04-13 seed. The table is **frozen** at its seed state.

### V-Q4.c — Reader grep

```
grep -rn "fund_family_patterns" scripts/ tests/ web/ docs/
```
Readers (active):
- `scripts/queries.py:282 get_nport_family_patterns()` — SELECTs
  patterns into a module-level memoized dict. The only operational
  SQL reader.
- `scripts/build_fixture.py:165` — copies prod table into fixture.
- `scripts/pipeline/validate_schema_parity.py:106` — lists table in
  parity-check set.
- `scripts/resolve_pending_series.py:438,466,542` — comments/docstrings,
  not SQL reads.

All readers target the **table**, not the script. None depends on the
script being re-run.

### V-Q4.d — Is the live-owner claim accurate?

`migrate_batch_3a.py:64-88 apply()` is the only mutator: `DELETE FROM
fund_family_patterns` then `INSERT` the in-code seed. Re-running it
would **overwrite any manual edit** made since 2026-04-13. Because no
manual edit has happened, the idempotency is harmless today — but that
is accidental, not designed. If the operator ever added a new pattern
directly in prod, the next `migrate_batch_3a.py --prod` run would
silently delete it.

The registry confirms the ambiguity in its own notes:

```
# scripts/pipeline/registry.py:294-299
"fund_family_patterns": DatasetSpec(
    layer=4, owner="scripts/migrate_batch_3a.py",
    promote_strategy="upsert", promote_key=("pattern",),
    notes="seeded once, manually edited thereafter",
),
```

Owner field says "scripts/migrate_batch_3a.py". Notes field says
"seeded once, manually edited thereafter". Those two statements are
mutually contradictory. The notes match observed reality; the owner
field does not.

### V-Q4 verdict

**PARTIAL — disconfirms the live-owner claim.**

`migrate_batch_3a.py` is a **one-shot seeder that has run exactly
once**. It is not a live mutator of `fund_family_patterns`. Keeping it
under `scripts/` implies ongoing operational relevance, which the git
history, DB drift test, and registry notes field all contradict.

Correct classification and suggested move:
- **Move to `scripts/oneoff/`** (matches precedent:
  `scripts/oneoff/apply_series_triage.py`,
  `scripts/oneoff/backfill_schema_versions_stamps.py`).
- **Update `registry.py:294-299`** `owner` to `"manual"` (or
  `"manual (seeded once by scripts/oneoff/migrate_batch_3a.py)"` for
  audit trail).
- The DDL+seed are preserved under `oneoff/` for rebuild-from-scratch
  purposes; they're not lost.

Keeping the script at `scripts/` with a live-owner designation
perpetuates a false signal that quarterly operators might interpret as
"safe to re-run" — when in fact a re-run would destroy any future
manual edit.

---

## §5 Aggregate recommendation

Adoption status of the three Phase B/C v3 refinements:

### Refinement 1 — "Drop the V1→V2 feature flag"
**Proceed as drafted.** The Makefile line that selects V1 today *is*
the flag; a second layer of gating duplicates reversibility for no
benefit. Admin refresh has been proving V2 cycle-viable on the same
code path as a scheduled run would.

**Condition for safety:** the Makefile swap PR must also fix two
small referential items in the same commit to avoid lying docs:
1. `scripts/pipeline/registry.py:113,118` — `filings` /
   `filings_deduped` owner: `scripts/load_13f.py` → `scripts/load_13f_v2.py`.
2. `scripts/update.py:75` — remove or update the `load_13f.py` step
   (docstring already calls this script "legacy", but the runtime
   step is still active).

### Refinement 2 — "B3 drops in a single session"
**Proceed, with the three cleanup items from V-Q3 bundled into the
same PR** (not a follow-up):
- Remove `fund_holdings` from `scripts/db.py:82-86 REFERENCE_TABLES`
- Remove raw_* L1 entries from `scripts/pipeline/registry.py:68-82`
- Update / delete `notebooks/research.ipynb:586-589` probe

Without those co-landings, the drops succeed but leave
contradictory registry/ref-table declarations pointing at non-existent
tables. Single-session B3 is fine; it is not safe if the cleanups
are "we'll get to them in C" — that's the same trap as Refinement 1's
proof-by-Makefile.

### Refinement 3 — "Keep `migrate_batch_3a.py` at `scripts/` as a live owner"
**Revise.** The live-owner premise is wrong. Recommend moving to
`scripts/oneoff/` and updating `registry.py:294-299 owner` to
"manual". This matches what the table actually is (a once-seeded
reference that is thereafter maintained by hand) and prevents a
future operator from re-running the script and silently wiping any
manual edit that accumulates over time.

---

## Most impactful finding (one-liner)

The V2 cycle-readiness claim has a concrete latent gap that
Serge's draft doesn't address: **the Makefile still runs V1
(`Makefile:111`)**. Admin-refresh parity is real, but
"cycle-ready" remains a one-line edit away. Phase B/C v3 should
name that edit and bundle the registry cleanups with it, or the
feature-flag removal leaves the system in a state where "the
cycle" and "admin refresh" write to different tables via different
scripts.
