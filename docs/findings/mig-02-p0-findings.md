# mig-02-p0 — Phase 0 findings: fetch_adv.py staging → promote_adv.py conversion

_Prepared: 2026-04-21 — branch `mig-02-p0` off main HEAD `7e3fe54`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-02` (MAJOR-14, Batch 3-A). Also closes the `fetch_adv` portion of `mig-13` (pipeline-violations REWRITE tail). Duplicate tracker `sec-09` is retired by this item. Upstream: `obs-01` (PR #25, manifest rows) and `obs-02` (PR #30, freshness try/except + CHECKPOINT reorder) are both merged and must be preserved. `mig-01` (PR #33) ships `mirror_manifest_and_impacts` in `pipeline/manifest.py` — this item calls it._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** `scripts/fetch_adv.py`, `scripts/promote_nport.py`, `scripts/promote_13dg.py`, `scripts/pipeline/manifest.py`, `scripts/pipeline/id_allocator.py`, `scripts/db.py`. Read-only inspection only.

**Method.** Full-file reads of all six scripts above, plus targeted greps for `STAGING_DB`, `PROD_DB`, `mirror_manifest_and_impacts`, and the `fetch_adv` entries in `docs/REMEDIATION_PLAN.md`. The Phase 0 task decision — standalone `promote_adv.py` rather than a branch inside `promote_staging.py` — is taken at face value from the prompt to avoid int-14/mig-14 conflict zone; no alternative was evaluated.

No runtime probing.

---

## §2. Current state — `fetch_adv.py` is a direct-write DROP→CREATE against prod

### 2.1 DDL sequence (what runs today)

All writes happen on a single connection opened at [scripts/fetch_adv.py:257](scripts/fetch_adv.py:257) against `DB_PATH = get_db_path()` — which resolves to `data/13f.duckdb` (prod) unless `set_staging_mode(True)` has been called by the caller (never, in fetch_adv.py). The execution order inside `save_to_duckdb` is:

1. **[fetch_adv.py:257](scripts/fetch_adv.py:257)** — `con = duckdb.connect(DB_PATH)` → opens prod.
2. **[fetch_adv.py:258](scripts/fetch_adv.py:258)** — `DROP TABLE IF EXISTS adv_managers`. **This is the kill-window.** A SIGKILL or process crash between this line and line 259 leaves prod with the table gone until the script is re-run.
3. **[fetch_adv.py:259](scripts/fetch_adv.py:259)** — `CREATE TABLE adv_managers AS SELECT * FROM df_out` (pandas DataFrame registered in the local scope).
4. **[fetch_adv.py:260](scripts/fetch_adv.py:260)** — `SELECT COUNT(*) FROM adv_managers` for logging.
5. **[fetch_adv.py:266-275](scripts/fetch_adv.py:266)** — two read-only summary queries for stdout.
6. **[fetch_adv.py:277-280](scripts/fetch_adv.py:277)** — `try: record_freshness(con, "adv_managers", row_count=row_count) except Exception …` — stamps `data_freshness`. Guarded try/except shipped in obs-02 (PR #30).
7. **[fetch_adv.py:281](scripts/fetch_adv.py:281)** — `con.execute("CHECKPOINT")`. Ordered after the freshness stamp — obs-02 reorder.
8. **[fetch_adv.py:282](scripts/fetch_adv.py:282)** — `con.close()`.

Separately, `main()` opens **three more** short-lived prod connections for manifest/impacts control-plane writes:

- **[fetch_adv.py:296-319](scripts/fetch_adv.py:296)** (connection A) — `get_or_create_manifest_row(... source_type="ADV", object_type="ZIP", object_key=f"ADV_BULK:{zip_filename}", fetch_status="fetching")` then `update_manifest_status(... "fetching", …)` then `CHECKPOINT` + `close`. Added in obs-01 (PR #25).
- **[fetch_adv.py:342-351](scripts/fetch_adv.py:342)** (connection B, failure path) — `update_manifest_status(... "failed", error_message=…)` + `CHECKPOINT` + `close`.
- **[fetch_adv.py:356-384](scripts/fetch_adv.py:356)** (connection C, success path) — `DELETE FROM ingestion_impacts WHERE manifest_id = ?` (re-run de-dupe), `write_impact(... target_table="adv_managers", unit_type="bulk_load", load_status="loaded", promote_status="promoted", rows_promoted=row_count, promoted_at=NOW())`, `update_manifest_status(... "complete", …)`, `CHECKPOINT`, `close`.

**The `promote_status='promoted'` at write_impact time is the direct-write signal.** In the staging pattern we are adopting, the fetch script must write the impact row with `promote_status='pending'` and the promote script must flip it to `'promoted'` after the atomic swap lands in prod.

### 2.2 Manifest registration — present (obs-01 PR #25)

Confirmed. `fetch_adv.py` registers against `ingestion_manifest` with:

- `source_type="ADV"`, `object_type="ZIP"`
- `object_key=f"ADV_BULK:{zip_filename}"` where `zip_filename = os.path.basename(ADV_ZIP_URL)` (e.g. `ADV_BULK:ia030226.zip`)
- `source_url=ADV_ZIP_URL`
- `run_id=f"adv_{YYYYmmdd_HHMMSS}_{uuid6}"`

Target tables declared via `write_impact`: `adv_managers` only (`unit_type="bulk_load"`, `unit_key_json={"filename": zip_filename}`, `report_date = today`).

### 2.3 Freshness — present (obs-02 PR #30)

Confirmed. `record_freshness(con, "adv_managers", row_count=row_count)` lands in `data_freshness` with `last_computed_at=CURRENT_TIMESTAMP`. Guarded by try/except; CHECKPOINT now trails the stamp, not precedes it.

### 2.4 Pipeline-violations status (`mig-13`)

`fetch_adv.py` is listed in `docs/REMEDIATION_PLAN.md` as a `mig-13` REWRITE target precisely because the DROP→CREATE pattern violates the staging-first rule. Shipping the fetch/promote split under `mig-02` closes that line-item too; no separate fix needed.

---

## §3. Reference pattern — how the converted scripts work

### 3.1 Fetch-writes-staging half

No fetch script currently needs to be converted in isolation for 13DG/NPORT (they were designed staging-native from day one). The closest analogue for fetch→staging ownership is:

- **Connection target**: `duckdb.connect(STAGING_DB)` (not `get_db_path()` — fetch_adv's staging conversion should be unconditional; there is no prod-mode for a staging-owning fetch).
- **Manifest/impacts rows**: written to staging `ingestion_manifest` / `ingestion_impacts` with `promote_status='pending'`, `rows_promoted` unset (NULL) at staging time.
- **Fact table write**: `CREATE OR REPLACE TABLE adv_managers AS SELECT * FROM df_out` against staging. `CREATE OR REPLACE` is a single DuckDB statement — atomic on its own connection — so the kill-window from §2.1 closes inside staging even before the promote lands.
- **Freshness**: **not stamped in staging.** `data_freshness` is a prod-facing surface; it should only reflect the last successful prod promote. Move the `record_freshness` call out of `fetch_adv.py` and into `promote_adv.py` after the prod INSERT.
- **CHECKPOINT**: on staging only. Prod is untouched by fetch_adv.

### 3.2 Promote-staging-to-prod half

Both `promote_nport.py` and `promote_13dg.py` follow the same four-step pattern, wrapped in a single explicit transaction on prod (mig-01 Phase 1):

1. Open two connections: `staging_con = duckdb.connect(STAGING_DB, read_only=True)` and `prod_con = duckdb.connect(PROD_DB)`.
2. Assert `ingestion_manifest` exists in prod (migration 001 must have run).
3. `prod_con.execute("BEGIN TRANSACTION")` then:
   - `mirror_manifest_and_impacts(prod_con, staging_con, run_id, source_type)` — mirrors this run's manifest + impacts rows staging → prod with audit-preserving anti-join on `(manifest_id, unit_type, unit_key_json)` for rows already `promoted`. Returns `(manifest_ids, impacts_inserted)`. `impact_id`s on newly inserted rows are reserved via `reserve_ids(prod_con, "ingestion_impacts", "impact_id", n)` inside the helper.
   - Fact-table DELETE+INSERT scoped by the run's grain. For NPORT: `(series_id, report_month)` tuples; for 13DG: `accession_number`. For ADV: **whole-table replace** — there is only one grain (`bulk_load`) and no incremental path, so the promote is a straight `DELETE FROM adv_managers` + `INSERT INTO adv_managers SELECT * FROM staging.adv_managers`.
   - `UPDATE ingestion_impacts SET promote_status='promoted', rows_promoted=rows_staged, promoted_at=CURRENT_TIMESTAMP WHERE manifest_id IN (SELECT manifest_id FROM ingestion_manifest WHERE run_id=? AND source_type=?)`.
4. `prod_con.execute("COMMIT")`. On any exception inside the block: `ROLLBACK` + re-raise.
5. Post-COMMIT, outside the transaction: `stamp_freshness(prod_con, "adv_managers")` (or `record_freshness` — see §5 risk note on the two helpers), then `CHECKPOINT`. DuckDB rejects CHECKPOINT inside a transaction, so it lives exactly once per successful promote.
6. `refresh_snapshot()` copies prod → `data/13f_readonly.duckdb`. Called from `promote_nport.py` and `promote_13dg.py`; should be called from `promote_adv.py` too.
7. `staging_con.close()` + `prod_con.close()`.

### 3.3 `mirror_manifest_and_impacts` contract

Signature ([scripts/pipeline/manifest.py:113-216](scripts/pipeline/manifest.py:113)):

```python
def mirror_manifest_and_impacts(
    prod_con: Any,
    staging_con: Any,
    run_id: str,
    source_type: str,
) -> tuple[list[int], int]:
    """Returns (manifest_ids, impacts_inserted)."""
```

Behaviour relevant to ADV:

- Scoped to `(run_id, source_type)` — for ADV this is `(f"adv_{…}", "ADV")`.
- Empty manifest rows → `([], 0)`, no writes. Caller should early-return in that case (both existing promoters do).
- Mirrors `ingestion_manifest` by DELETE-then-INSERT on both `manifest_id` and `object_key` (DuckDB rejects a bare `ON CONFLICT DO UPDATE` because both are unique keys).
- Mirrors `ingestion_impacts` with an audit-preserving anti-join: prod rows already `promote_status='promoted'` are not overwritten. New rows get fresh `impact_id`s from `reserve_ids`.
- The helper does **not** open or commit a transaction. Caller must provide the transactional boundary — which is exactly what `promote_nport.py` / `promote_13dg.py` already do.

### 3.4 `id_allocator` surface the promoter should NOT touch directly

`promote_adv.py` should not call `allocate_id` or `reserve_ids` itself — the helpers are invoked inside `mirror_manifest_and_impacts` for impact rows, and the fact-table (`adv_managers`) has no managed integer PK that the pipeline owns. CRD numbers are VARCHAR and are not issued by the allocator.

---

## §4. Proposed changes — Phase 1 shape

### 4.1 `scripts/fetch_adv.py` — itemized diff (text only; Phase 0 deliverable)

Goal: make `fetch_adv.py` write to staging exclusively. Preserve obs-01 (manifest) and obs-02 (guarded freshness + CHECKPOINT order) work but move the freshness stamp out.

1. **Swap connection target.** Replace the three-site usage of `DB_PATH = get_db_path()` with `STAGING_DB` imported from `db`. Remove the `get_db_path` import; keep `record_freshness` and `crash_handler`. Specifically:
   - [fetch_adv.py:33](scripts/fetch_adv.py:33) — change `from db import get_db_path, crash_handler, record_freshness` to `from db import STAGING_DB, crash_handler` (drop `record_freshness`; it's called only from the promote now).
   - [fetch_adv.py:34](scripts/fetch_adv.py:34) — delete `DB_PATH = get_db_path()`; replace all three `duckdb.connect(DB_PATH)` sites with `duckdb.connect(STAGING_DB)`.

2. **Replace DROP → CREATE with single-statement CREATE OR REPLACE.**
   - [fetch_adv.py:258-259](scripts/fetch_adv.py:258) — replace:
     ```python
     con.execute("DROP TABLE IF EXISTS adv_managers")
     con.execute("CREATE TABLE adv_managers AS SELECT * FROM df_out")
     ```
     with:
     ```python
     con.execute("CREATE OR REPLACE TABLE adv_managers AS SELECT * FROM df_out")
     ```
   This closes the kill-window inside staging. Prod is untouched by this script after the conversion.

3. **Remove `record_freshness` from `save_to_duckdb`.**
   - [fetch_adv.py:277-280](scripts/fetch_adv.py:277) — delete the try/except + `record_freshness` call. The `CHECKPOINT` at line 281 stays (checkpoints the staging write). The freshness stamp moves to `promote_adv.py` and fires on prod after the atomic swap.

4. **Flip the direct-write `promote_status='promoted'` signal to `pending`.**
   - [fetch_adv.py:363-375](scripts/fetch_adv.py:363) — change the `write_impact(...)` kwargs to `load_status="loaded"`, `promote_status="pending"`, and drop `rows_promoted=row_count` and `promoted_at=datetime.now()`. Those two fields get set by `promote_adv.py`'s `UPDATE ingestion_impacts` after promote.

5. **Keep everything else.** Manifest registration (lines 296-319), failure-path manifest flip (342-351), success-path manifest flip to `complete` (376-381), summary prints, ACTIVIST_NAMES loop — all untouched. `main()` structure + `crash_handler` wrapper unchanged.

6. **Module docstring.** Update the one-liner at the top to note the staging target and that promote is handled by `scripts/promote_adv.py`. Existing lint rules require no trailing-whitespace changes; keep the edit small.

Expected net diff: ~15 lines changed in `fetch_adv.py`, all confined to the sections above.

### 4.2 `scripts/promote_adv.py` — new file, pseudocode

Parallel shape to `promote_13dg.py` (simpler grain — no amendment handling, no enrichment, no derived-table rebuild). ADV is effectively a single-table whole-refresh promote.

```python
#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# promote_adv.py unit: one run_id (one ADV bulk ZIP parse).
# The whole write sequence is wrapped in one explicit BEGIN TRANSACTION /
# COMMIT / ROLLBACK. A single CHECKPOINT runs after COMMIT.
"""promote_adv.py — promote staged ADV data (staging → prod).

Runs after fetch_adv.py writes to data/13f_staging.duckdb. Replaces all
rows in prod adv_managers with the staged set (ADV is a whole-table
refresh — there is no incremental path).

Usage:
  python3 scripts/promote_adv.py --run-id <adv_YYYYmmdd_HHMMSS_xxxxxx>
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB, record_freshness  # noqa: E402
from pipeline.manifest import mirror_manifest_and_impacts  # noqa: E402
from pipeline.shared import refresh_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote ADV staging → prod")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    staging_con = duckdb.connect(STAGING_DB, read_only=True)
    prod_con = duckdb.connect(PROD_DB)
    try:
        # Migration 001 guard (same as 13dg/nport).
        try:
            prod_con.execute("SELECT 1 FROM ingestion_manifest LIMIT 1")
        except duckdb.CatalogException as exc:
            raise SystemExit(
                "ingestion_manifest not present in prod — run migration 001 first"
            ) from exc

        # Verify staging actually has rows for this run_id before touching prod.
        staged_count = staging_con.execute(
            "SELECT COUNT(*) FROM adv_managers"
        ).fetchone()[0]
        if staged_count == 0:
            raise SystemExit(
                f"staging adv_managers is empty — aborting promote for {args.run_id}"
            )

        prod_con.execute("BEGIN TRANSACTION")
        try:
            manifest_ids, _impacts = mirror_manifest_and_impacts(
                prod_con, staging_con, args.run_id, "ADV",
            )
            if not manifest_ids:
                prod_con.execute("ROLLBACK")
                print(f"No manifest rows for run_id={args.run_id}")
                return

            # Whole-table replace. ADV has no partitioning grain — one run
            # re-parses the full SEC bulk ZIP, so the correct semantics is
            # "replace the prior universe". Pulling via ATTACH gives a
            # single-statement INSERT without a pandas round-trip.
            prod_con.execute(f"ATTACH '{STAGING_DB}' AS stg (READ_ONLY)")
            try:
                deleted = prod_con.execute(
                    "SELECT COUNT(*) FROM adv_managers"
                ).fetchone()[0]
                prod_con.execute("DELETE FROM adv_managers")
                prod_con.execute(
                    "INSERT INTO adv_managers SELECT * FROM stg.adv_managers"
                )
                inserted = prod_con.execute(
                    "SELECT COUNT(*) FROM adv_managers"
                ).fetchone()[0]
            finally:
                prod_con.execute("DETACH stg")

            print(f"  adv_managers: -{deleted} +{inserted}")

            # Flip impacts pending → promoted for this run.
            prod_con.execute(
                """
                UPDATE ingestion_impacts
                   SET promote_status = 'promoted',
                       rows_promoted  = rows_staged,
                       promoted_at    = CURRENT_TIMESTAMP
                 WHERE manifest_id IN (
                     SELECT manifest_id FROM ingestion_manifest
                      WHERE run_id = ? AND source_type = 'ADV'
                 )
                   AND promote_status = 'pending'
                """,
                [args.run_id],
            )

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        # Freshness + CHECKPOINT outside the transaction (DuckDB rejects
        # CHECKPOINT inside one; stamp_freshness is recoverable metadata).
        try:
            record_freshness(prod_con, "adv_managers", row_count=inserted)
        except Exception as e:
            print(f"  [warn] record_freshness(adv_managers) failed: {e}", flush=True)
        prod_con.execute("CHECKPOINT")

        print(f"DONE  adv_managers -{deleted} +{inserted}")
    finally:
        staging_con.close()
        prod_con.close()

    refresh_snapshot()
    print("DONE  promote_adv")


if __name__ == "__main__":
    main()
```

Notes on the above:

- **No validation-report gate.** Unlike `promote_nport.py` / `promote_13dg.py`, ADV has no `validate_adv.py` today. The existing Phase 1 scope does **not** include building one — the staging-first restructure is the contract that mig-02 ships. Adding a validator is a follow-up (likely `obs-04` or a new item) and should not block this PR. The inline `staged_count == 0` guard is the minimal safety net for the zero-rows case.
- **`ATTACH … READ_ONLY`** instead of the pandas round-trip used by `promote_13dg.py._promote()`. ADV is ~16.6K rows × ~18 columns — small enough that either path is fine, but `ATTACH` avoids an unnecessary DataFrame materialization and is closer to the intent (whole-table copy). This mirrors the pattern already used in `scripts/db.py:141-143` for snapshot restore.
- **`record_freshness` vs `stamp_freshness`.** `promote_nport.py` / `promote_13dg.py` use `stamp_freshness` from `pipeline.shared`. That helper is defined once there and wraps `db.record_freshness` with slightly different arg handling. For ADV, `record_freshness` (imported directly from `db`) is what the pre-conversion fetch_adv.py used and matches the exact call shape obs-02 shipped. Either works; the pseudocode uses `record_freshness` to keep the call identical to pre-conversion semantics. Phase 1 should pick one deliberately — no hidden behaviour difference, just call-site consistency.
- **`refresh_snapshot()`** is called from both existing promoters; ADV should participate in the same read-only snapshot refresh so downstream readers see the new universe.

### 4.3 Files to touch in Phase 1

| File | Change | Approx LOC |
|---|---|---|
| `scripts/fetch_adv.py` | Modify — staging target + CREATE OR REPLACE + remove freshness + flip impact promote_status to pending | ~15 lines changed |
| `scripts/promote_adv.py` | **New** — full promoter per §4.2 pseudocode | ~110 lines (new file) |

No other files need touching for Phase 1. `pipeline/manifest.py` is not modified (the helper is already general enough). `db.py` is not modified (`STAGING_DB` / `PROD_DB` / `record_freshness` are already exported). `migrations/` is not touched (the `adv_managers` table schema is already in prod; the conversion only changes who writes what when).

---

## §5. Risk notes

1. **Staging DB must have `adv_managers` table + `ingestion_manifest` + `ingestion_impacts` schema before the first converted run.** The first execution of the new `fetch_adv.py` against staging will `CREATE OR REPLACE TABLE adv_managers AS SELECT ...` — which handles the table creation itself. But `ingestion_manifest` and `ingestion_impacts` need to already exist in staging so `get_or_create_manifest_row` / `write_impact` resolve. Confirm before Phase 1 lands: migration 001 (pipeline control plane) has been applied to `data/13f_staging.duckdb`. Staging-native fetches (NPORT, 13DG) already rely on this, so in practice it's true today — but a one-line pre-flight check or explicit `scripts/migrations/apply.py --db staging` run should be documented.

2. **Orchestration change.** Any caller that currently runs `python3 scripts/fetch_adv.py` expecting prod `adv_managers` to be fresh afterwards will stop getting that. The Makefile target `quarterly-update` (and any ad-hoc scripts referencing `fetch_adv.py`) must be updated to run `fetch_adv.py` followed by `promote_adv.py --run-id <id>`. `fetch_adv.py` should print the generated `run_id` prominently at exit so the next step is scriptable. This is a Phase 1 task — flag in the PR description.

3. **`refresh_snapshot()` timing.** ADV data is used by downstream readers (register tab, manager classifications). Calling `refresh_snapshot()` from `promote_adv.py` ensures the read-only snapshot picks up the new universe, matching nport/13dg. If another pipeline (e.g. an enrichment run) is expected to produce the snapshot later in the same orchestration window, `promote_adv.py` will produce an extra snapshot refresh — small cost (one-file copy), harmless.

4. **Audit preservation interaction.** The staging fetch writes the impact row as `promote_status='pending'`. If `promote_adv.py` runs, flips it to `'promoted'`, and then `fetch_adv.py` runs again with a **new** `run_id` (common: a fresh monthly re-parse), the new run will `DELETE FROM ingestion_impacts WHERE manifest_id = ?` on its own manifest_id at [fetch_adv.py:359-362](scripts/fetch_adv.py:359), but the **prior** promoted run's impact row is on a different `manifest_id` and is correctly preserved by `mirror_manifest_and_impacts`'s anti-join. No behaviour change required. If the same `run_id` is re-run (failure recovery), the same object_key resolves to the same manifest_id, the impact DELETE clears the pending row, and promote runs cleanly — matches the existing re-entrant behaviour.

5. **Migration ordering with `mig-14` and `int-14`.** The REMEDIATION_PLAN notes mig-02 and mig-14 live in Batch 3-A; mig-14 is the migration-004 retrofit. Both items are disjoint (different files) — safe to execute independently. The decision in the prompt to write `promote_adv.py` as a standalone script (not a branch inside `promote_staging.py`) keeps this item out of the int-14 / mig-14 conflict zone as intended.

6. **No rollback data migration needed.** Prod `adv_managers` already has the expected schema. The first converted run simply re-parses the SEC ZIP, stages it, promotes via the new path, and the prod table ends up with the same shape it has today (16.6K rows ±). No backfill, no retro-mirror of history.

---

## §6. Phase 1 acceptance criteria (proposed)

To keep the Phase 1 PR scope explicit:

- `scripts/fetch_adv.py` connects to `STAGING_DB` in all three write-site connections. `DB_PATH` reference removed.
- `scripts/fetch_adv.py` contains no `DROP TABLE IF EXISTS adv_managers` — replaced with `CREATE OR REPLACE TABLE`.
- `scripts/fetch_adv.py` no longer calls `record_freshness`.
- `scripts/fetch_adv.py` `write_impact` call uses `promote_status='pending'`, drops `rows_promoted` + `promoted_at`.
- `scripts/promote_adv.py` exists, matches §4.2 shape, wraps writes in explicit transaction with ROLLBACK on failure, CHECKPOINT once after COMMIT, calls `refresh_snapshot()`.
- `scripts/promote_adv.py` calls `mirror_manifest_and_impacts` for `source_type='ADV'`.
- `scripts/promote_adv.py` flips `ingestion_impacts.promote_status` pending → promoted for the run's manifest rows.
- `scripts/promote_adv.py` stamps `data_freshness('adv_managers')` after COMMIT, guarded by try/except matching obs-02's pattern.
- Manual smoke test in a worktree: run `fetch_adv.py` against staging, note `run_id`, run `promote_adv.py --run-id <id>`, verify `SELECT COUNT(*) FROM adv_managers` in prod matches staged, and `ingestion_impacts` row is `promoted`.

No new test harness is introduced in Phase 1 — fetch_adv is external-network-dependent and the existing project convention is to smoke-test pipeline changes manually in a worktree. A dedicated unit test is out of scope for mig-02 and not required by the plan.
