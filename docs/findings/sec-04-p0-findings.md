# sec-04-p0 — Phase 0 findings: validators writing to prod

_Prepared: 2026-04-21 — branch `remediation/sec-04-p0` off main HEAD `d0fba1c`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 4 row `sec-04` (MAJOR-1, C-02); `docs/REMEDIATION_CHECKLIST.md` Batch 4-B. Audit refs: `docs/SYSTEM_AUDIT_2026_04_17.md` §4.1 (MAJOR-1 / C-02). Upstream: sec-03-p1 (admin write-surface audit, merged PR #16, #17)._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** Every `scripts/validate_*.py` script, their DB connection modes, their write targets, and the invocation points that call them. `db.py` and `pipeline/shared.py` are in scope because every validator routes through one of them.

**Method.** Source-of-truth walk:

- `scripts/db.py` — full file ([scripts/db.py](scripts/db.py)).
- `scripts/pipeline/shared.py` — full file ([scripts/pipeline/shared.py](scripts/pipeline/shared.py)).
- Each `scripts/validate_*.py` — full file.
- `Makefile`, `scripts/promote_*.py`, `scripts/fetch_*.py` — invocation callers.
- `scripts/api_*.py`, `scripts/admin_bp.py` — confirmed **no admin/API route invokes any validator** (checked `grep -l 'validate_'` across `api*.py`; admin routes do not shell out to validators).

No runtime probing — the prompt forbids it.

**Discovered validator set** (`glob scripts/validate_*.py`):

1. `scripts/validate_13dg.py`
2. `scripts/validate_classifications.py`
3. `scripts/validate_entities.py`
4. `scripts/validate_nport.py`
5. `scripts/validate_nport_subset.py`
6. `scripts/validate_phase4.py`

The prompt's file list named three (`validate_nport_subset.py`, `validate_entities.py`, `validate_13dg.py`); the other three were discovered in inventory and are tabulated alongside for completeness, but only read-only observations are reported for them.

---

## §2. Connection-path helpers in `db.py` and `pipeline/shared.py`

**`scripts/db.py`** provides no `get_db()` helper (the prompt name). The surface is ([scripts/db.py:40-67](scripts/db.py:40)):

| Helper | Returns | Notes |
|---|---|---|
| `get_db_path()` | test DB if `_test_mode` else staging DB if `_staging_mode` else prod DB | Path only — caller decides open mode. |
| `get_read_db_path()` | test DB if `_test_mode` else always prod | Reference reads in staging mode still hit prod. |
| `connect_read()` | `duckdb.connect(get_read_db_path(), read_only=True)` | Safe by construction. |
| `connect_write()` | `duckdb.connect(get_db_path())` | RW — returns prod in default mode. |
| `assert_write_safe(con)` | raises if test mode and path isn't the test DB | Only guards the test→prod misroute, not prod RW opens from validators. |

There is **no default**. Every validator opens a connection explicitly. Some call `db.connect_write()` (RW prod by default), some go straight to `duckdb.connect(PROD_DB)` or `duckdb.connect(PROD_DB, read_only=True)`, bypassing `db.py` entirely.

**`scripts/pipeline/shared.py` `entity_gate_check`** ([scripts/pipeline/shared.py:237-385](scripts/pipeline/shared.py:237)) is the canonical side-effect vector. The module docstring at [scripts/pipeline/shared.py:15-17](scripts/pipeline/shared.py:15) asserts the function is "read-only" and "never writes to any entity table" — then acknowledges it "writes rows to pending_entity_resolution for later human review." The actual write is at [scripts/pipeline/shared.py:364-379](scripts/pipeline/shared.py:364):

```python
for raw_value in new_pending:
    ...
    try:
        con_prod.execute(
            "INSERT INTO pending_entity_resolution "
            ...
            "ON CONFLICT (pending_key) DO NOTHING",
            ...
        )
    except Exception as e:
        print(f"  [entity_gate_check] pending insert failed: {e}", flush=True)
```

The bare `except Exception` is **the load-bearing invariant** for read-only callers: when `con_prod` is opened with `read_only=True`, DuckDB raises on INSERT, the caller sees a warning on stdout, and the gate still returns correct `GateResult` tuples (the reads before the INSERT already happened). Callers that want pending rows persisted must either open RW themselves or rely on a downstream promote step.

This design is brittle but currently non-breaking. The Phase 1 recommendation in §5 replaces the `try/except` with an explicit `write_pending: bool = False` kwarg so behavior becomes intentional at every call site.

**No validator** calls `pipeline.shared.write_manifest_row`, `bulk_enrich_bo_filers`, `rebuild_beneficial_ownership_current`, `stamp_freshness`, or `refresh_snapshot` (verified by grep). `write_impact_row` was removed by obs-03 (PRs #8, #12) and is not referenced in any `.py` file.

---

## §3. Per-validator write classification

| # | Validator | Opens prod | Line | Writes prod? | Classification | Notes |
|---|---|---|---|---|---|---|
| 1 | `validate_nport_subset.py` | **RW** (direct `duckdb.connect`) | [validate_nport_subset.py:67](scripts/validate_nport_subset.py:67) | Yes — `INSERT INTO pending_entity_resolution` ([:188-196](scripts/validate_nport_subset.py:188)) + `CHECKPOINT` ([:268](scripts/validate_nport_subset.py:268)) | **INTENTIONAL** | Queues excluded series as pending rows. Writes are by design. Named "validator" but performs promote-prep writes. |
| 2 | `validate_nport.py` | RO | [validate_nport.py:650](scripts/validate_nport.py:650) (also RO changes-only [:629](scripts/validate_nport.py:629)) | Side-effect (swallowed) | **SIDE-EFFECT (mitigated)** | Passes RO prod conn to `entity_gate_check`; the INSERT at `shared.py:369-377` raises on RO and the `except` prints a warning. Relies on the downstream promote step to persist pending rows. Comment at [:644-649](scripts/validate_nport.py:644) documents the contract. |
| 3 | `validate_13dg.py` | RO | [validate_13dg.py:216](scripts/validate_13dg.py:216) | Side-effect (swallowed) | **SIDE-EFFECT (mitigated)** | Same pattern as validate_nport.py. Comment at [:211-215](scripts/validate_13dg.py:211) documents the contract. |
| 4 | `validate_entities.py` | **RW** by default; RO opt-in via `--read-only` ([:832-848](scripts/validate_entities.py:832)) | [:848](scripts/validate_entities.py:848) via `db.connect_write()` | No — every `GATES` entry is SELECT-only (grep-verified; no `INSERT`/`UPDATE`/`DELETE`/`ALTER` in the file) | **ACCIDENTAL** | Opens prod RW although all 16 gates are pure reads. `--read-only` flag exists ([:832-835](scripts/validate_entities.py:832)) but is off by default. Makefile Step 9 ([Makefile:126](Makefile:126)) and `promote_staging.py` ([promote_staging.py:668](scripts/promote_staging.py:668)) both invoke without `--read-only`. |
| 5 | `validate_classifications.py` | RO prod (default); RW staging when `--staging` ([:150-154](scripts/validate_classifications.py:150)) | [:145](scripts/validate_classifications.py:145), [:152](scripts/validate_classifications.py:152) | No prod writes. Staging opened RW so DuckDB can `ATTACH '{PROD_DB}' AS prod_src (READ_ONLY)` ([:153](scripts/validate_classifications.py:153)) | **SAFE (prod)** — staging RW is acceptable per staging workflow | Prod is always RO; staging RW is the staging discipline, not a violation. Phase 1 may still prefer a RO main with RW ATTACH (supported on DuckDB ≥ 0.9 when the staging file isn't write-locked elsewhere). |
| 6 | `validate_phase4.py` | RO | [validate_phase4.py:32](scripts/validate_phase4.py:32) | No | **SAFE** | Hardcodes `DB_PATH = data/13f.duckdb` ([:13](scripts/validate_phase4.py:13)) instead of `db.get_read_db_path()`. Not a sec-04 concern — this is a sec-05 "hardcoded prod path" issue and is noted there. |

**Only two validators actually write to prod:**

1. `validate_nport_subset.py` — INTENTIONAL (does its own INSERT + CHECKPOINT).
2. `validate_entities.py` — ACCIDENTAL (opens RW, never writes).

Two more (`validate_nport.py`, `validate_13dg.py`) attempt side-effect writes that fail silently on RO. That pattern is fragile but does not breach the RO contract in practice.

---

## §4. Invocation inventory

Source: `grep -rn 'validate_[a-z0-9_]*\.py' scripts Makefile *.md`.

| Validator | Caller | Mode flag | Prod open mode |
|---|---|---|---|
| `validate_entities.py` | [Makefile:126](Makefile:126) (`make validate`) | `--prod` | **RW** — `--read-only` not passed |
| `validate_entities.py` | [scripts/promote_staging.py:668](scripts/promote_staging.py:668) (subprocess during every entity-table promote) | `--prod` | **RW** — `--read-only` not passed |
| `validate_nport.py` | No automated invoker. [fetch_nport_v2.py:388-389](scripts/fetch_nport_v2.py:388) and [fetch_dera_nport.py:1216](scripts/fetch_dera_nport.py:1216) print a "next:" hint; operator runs it manually. | `--run-id … --staging` | RO |
| `validate_13dg.py` | No automated invoker. `promote_13dg.py` reads the validation report file ([promote_13dg.py:54](scripts/promote_13dg.py:54)) but does not run the validator. | manual | RO |
| `validate_nport_subset.py` | No automated invoker. Operator runs per the docstring recipe ([validate_nport_subset.py:18-23](scripts/validate_nport_subset.py:18)). | manual | **RW** |
| `validate_classifications.py` | No automated invoker | manual | RO prod / RW staging |
| `validate_phase4.py` | No automated invoker | manual | RO |

**No admin/API route runs any validator.** `grep -l 'validate_' scripts/api_*.py scripts/admin_bp.py` returns zero script-invocation hits — matches from `api_register.py` et al. are comments about data validation, not subprocess calls. Every validator is either manually invoked by an operator or (for `validate_entities.py`) invoked automatically from `promote_staging.py` / `make validate`.

---

## §5. Phase 1 scope

Two violations require code change; two require only a documentation clarification.

### 5.1 `validate_entities.py` — flip default to read-only (ACCIDENTAL)

- Change: flip the `--read-only` default so validators default **RO**, with an explicit `--write` / `--rw` escape hatch if any gate ever needs to write (none currently does).
- Touches: `scripts/validate_entities.py` (arg handling), `scripts/promote_staging.py:668` (pass new flag if needed — likely a no-op since `--read-only` becomes the default), `Makefile:126` (likewise).
- Blast radius: zero functional change — `run_checks` is 100 % SELECT — only closes the prod-RW window during `make validate` and every entity promote.
- Test plan:
  1. `python scripts/validate_entities.py --prod` — confirm exit 0 and matching `logs/entity_validation_report.json` vs. current output.
  2. `python scripts/validate_entities.py --prod --write` — confirm RW path still works (compat).
  3. `scripts/promote_staging.py` dry-run on a small staging diff — confirm the subprocess wrapper still reports `validate_returncode == 0`.

### 5.2 `validate_nport_subset.py` — split validate from queue (INTENTIONAL, but misplaced)

- Change: extract the `pending_entity_resolution` INSERT block into `scripts/queue_nport_excluded.py` (or fold into `promote_nport.py`'s pending-row pre-step). `validate_nport_subset.py` then opens prod **RO**, reports the excluded series, and exits — it stops writing.
- Why: "validate" implies read. The current script reads as a validator but writes as a promote prep step. Either rename it (e.g. `prepare_nport_promote.py`) or split the write out. Splitting is lower risk because callers can be migrated one at a time.
- Touches: `scripts/validate_nport_subset.py` (remove INSERT + CHECKPOINT); new `scripts/queue_nport_excluded.py` (or new function in `promote_nport.py`); docstring callers in `fetch_nport_v2.py:388-389`, `fetch_dera_nport.py:1216`.
- Blast radius: any operator running the existing two-liner recipe must add a second command (`queue_nport_excluded.py --excluded-file ...`). Low — there's a single recipe in the docstring and both `fetch_*.py` scripts print an updatable hint.
- Test plan:
  1. On staging: run validator-only path — confirm report produced identical to today's minus the "queued X" note.
  2. Run the new queue script — confirm the same `pending_entity_resolution` rows land as before (compare on `pending_key`).
  3. Re-run both idempotent — confirm `ON CONFLICT DO NOTHING` still prevents dups.

### 5.3 `pipeline/shared.py entity_gate_check` — explicit `write_pending` kwarg (SIDE-EFFECT)

- Change: replace the bare `try/except` at [shared.py:368-379](scripts/pipeline/shared.py:368) with an explicit `write_pending: bool = False` parameter. Callers that pass a RO connection set `write_pending=False` (default) and the block is skipped entirely. Callers that want persistence pass RW conn + `write_pending=True`.
- Why: removes the "swallow IOError on RO" pattern. Today's behavior is correct by accident; tomorrow a DuckDB version bump or a partial-write bug could silently drop pending rows. Making the write opt-in makes the contract visible.
- Touches: `scripts/pipeline/shared.py` (signature + docstring), `scripts/validate_nport.py:158` (pass nothing — defaults to RO-safe), `scripts/validate_13dg.py:142` (same), plus any promote callers that actually want the INSERT (audit grep below).
- **Cross-item serialization required.** REMEDIATION_PLAN.md §Theme 1 × Theme 4 flags int-21 on the same file. Per the plan "int-21 ∥ sec-04 → share shared.py → serial." Phase 1 must land **after** int-21 or be sequenced by the planner.
- Blast radius: behavior-preserving for all RO callers; RW callers (promote scripts) add an explicit `write_pending=True`. Log line disappears because the exception path no longer fires.
- Test plan:
  1. Audit grep for callers of `entity_gate_check` and classify each RO vs RW.
  2. Run `validate_nport.py` + `validate_13dg.py` against a staging fixture — confirm no `pending_entity_resolution` delta vs. today (both are RO callers, write_pending stays False).
  3. Run `promote_nport.py` or equivalent RW caller with `write_pending=True` — confirm pending rows still land.

### 5.4 Docstring cleanup (no code change)

- `pipeline/shared.py:15-17` claims `entity_gate_check` is "read-only" then admits it writes. Rewrite after 5.3 to match the new explicit contract.
- `validate_nport_subset.py:14-17` describes itself as a validator but performs promote writes. Rename + re-docstring after 5.2.

---

## §6. Cross-item flags

- **sec-03 (merged, PRs #16, #17).** Confirmed no admin endpoint shells out to a validator — sec-03's admin write surface and sec-04's script write surface are fully disjoint.
- **sec-05 / sec-06.** `validate_phase4.py` hardcodes `DB_PATH = data/13f.duckdb` ([validate_phase4.py:13](scripts/validate_phase4.py:13)) — correctly flagged as sec-05-scope (hardcoded-prod path), not sec-04. No action here; noted for sec-05.
- **int-21 (MAJOR-7 unresolved series_id).** Both sec-04 §5.3 and int-21 touch `pipeline/shared.py`. Plan calls for **serial** execution; Phase 1 for §5.3 must be sequenced after int-21 (or vice versa), per REMEDIATION_PLAN §Theme 1 × Theme 4.
- **obs-03 (merged, PRs #8, #12).** `write_impact_row` was removed from `pipeline/shared.py`. Grep confirms no validator referenced it. No carry-over cleanup.
- **obs-01 (pending).** N-CEN + ADV manifest registration is orthogonal — none of the validators register manifests.

---

## §7. Summary

- **Six validators** inventoried; **two** open prod **RW**.
  - `validate_nport_subset.py` — **INTENTIONAL** write (split validate from queue).
  - `validate_entities.py` — **ACCIDENTAL** RW open (flip default to RO).
- **Two more** (`validate_nport.py`, `validate_13dg.py`) rely on `entity_gate_check`'s `try/except` to swallow INSERT failures on RO connections. Fragile, currently non-breaking — formalize with `write_pending: bool` kwarg.
- **No admin UI or API route** triggers any validator. All invocations are Makefile, `promote_staging.py`, or manual operator commands.
- `validate_classifications.py` opens staging RW for ATTACH reasons (not a prod violation). `validate_phase4.py` is RO but hardcodes prod path (sec-05 concern, not sec-04).
- Phase 1 sequencing: §5.1 + §5.2 are independent of int-21. §5.3 must serialize with int-21 per the remediation plan.
