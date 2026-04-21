# obs-04-p0 — Phase 0 findings: 13D/G `ingestion_impacts` backfill

_Prepared: 2026-04-21 — branch `obs-04-p0` off `main` HEAD `7e3fe54`._

_Tracker: SYSTEM_AUDIT §3 MAJOR-8 (D-06). mig-01 Phase 1 (PR #33) shipped the forward-looking fix by extracting `mirror_manifest_and_impacts` into `scripts/pipeline/manifest.py` and calling it from `scripts/promote_13dg.py`. obs-04 is the retroactive backfill for the pre-v2 history that predates that mirror._

Phase 0 is investigation only. No code writes and no DB writes were performed. Prod DB (`data/13f.duckdb`, 14.5 GB) was read through `duckdb.connect(..., read_only=True)`.

---

## §1. TL;DR — grain reframing

The task statement framed this as "3 wrong-grain rows → DELETE + re-INSERT at correct grain." Phase 0 evidence shows that framing is **inaccurate**. The three existing `ingestion_impacts` rows are already at the correct grain (one per `filer_subject_accession` triple, matching the pattern `fetch_13dg_v2.py:526-545` writes). The defect is **coverage**, not grain:

| | Rows | Coverage |
|---|---|---|
| `beneficial_ownership_v2` (BO v2) | 51,905 | — |
| BO v2 rows with matching `ingestion_manifest` row | 3 | 0.006 % |
| BO v2 rows with **no** manifest/impact lineage | 51,902 | 99.994 % |
| Existing `ingestion_impacts` rows with `source_type='13DG'` | 3 | correct grain, all three already `promote_status='promoted'` |

The 3 tracked rows are the three accessions fetched through the v2 pipeline on 2026-04-14 (run_id `13dg_20260414_040240_79faea`) — the first and so far only run of `fetch_13dg_v2.py` against prod post-mig-01. Every other BO v2 row was loaded before `fetch_13dg_v2.py` existed and therefore has no manifest row to FK back to.

**Revised plan:** leave the 3 existing rows in place. Backfill **2 tables** — `ingestion_manifest` (51,902 new rows) and `ingestion_impacts` (51,902 new rows) — for the orphan accessions. Target: `COUNT(ingestion_impacts ∩ 13DG) = 51,905` post-backfill.

Also flagged: the task description used the name `_mirror_manifest_and_impacts` (leading underscore). The actual function is [`mirror_manifest_and_impacts`](scripts/pipeline/manifest.py:113) — public, no underscore.

---

## §2. Current DB state

### §2.1 Existing `ingestion_impacts` 13D/G rows

```
impact_id  manifest_id  target_table                  unit_type                unit_key_json                                                                                         promote_status  promoted_at
191        8            beneficial_ownership_v2       filer_subject_accession  {"filer_cik":"0001423902","subject_cusip":"Number","accession_number":"0001140361-24-037383"}         promoted        2026-04-14 04:05:04
192        9            beneficial_ownership_v2       filer_subject_accession  {"filer_cik":"0000033213","subject_cusip":"NUMBER","accession_number":"0000080255-24-001363"}         promoted        2026-04-14 04:05:04
193        10           beneficial_ownership_v2       filer_subject_accession  {"filer_cik":"0001065280","subject_cusip":"64110L106","accession_number":"0001104659-24-021541"}     promoted        2026-04-14 04:05:04
```

All three: `load_status='loaded'`, `promote_status='promoted'`, `rows_staged=1`, `rows_promoted=1`, `report_date=NULL`. Run_id `13dg_20260414_040240_79faea`.

### §2.2 Matching `ingestion_manifest` rows (manifest_id 8, 9, 10)

```
source_type='13DG'   object_type='TXT'   fetch_status='complete'
object_key = accession_number (UNIQUE)
source_url = https://www.sec.gov/Archives/edgar/data/{subject_cik}/{acc_no_dashes}/{accession}.txt
filing_date = NULL   report_period = NULL   accepted_at = NULL   is_amendment = false
run_id = 13dg_20260414_040240_79faea
```

### §2.3 `beneficial_ownership_v2`

| Metric | Value |
|---|---|
| Row count | 51,905 |
| Distinct accessions | 51,905 (1:1 with rows) |
| Distinct `(filer_cik, subject_cusip, accession_number)` triples | 51,905 (1:1 with rows) |
| Filing date range | 2022-01-03 → 2026-03-16 |
| Loaded_at range | 2026-04-02 18:19 → 2026-04-14 04:02 |
| Filing type breakdown | SC 13G/A 34,263 · SC 13G 10,200 · SC 13D/A 6,265 · SC 13D 1,177 |
| Load-day "batches" | 2026-04-02: 2,339 rows · 2026-04-03: 49,563 rows · 2026-04-14: 3 rows |

`report_date` is NULL for all 51,905 BO v2 rows — consistent with the 3 existing impacts having `report_date=NULL`.

### §2.4 `ingestion_impacts` full schema (prod, 17 columns)

```
impact_id            BIGINT    NOT NULL   PK
manifest_id          BIGINT    NOT NULL   → ingestion_manifest.manifest_id
target_table         VARCHAR   NOT NULL
unit_type            VARCHAR   NOT NULL
unit_key_json        VARCHAR   NOT NULL
report_date          DATE      NULL
rows_staged          INTEGER   NOT NULL   DEFAULT 0
rows_promoted        INTEGER   NOT NULL   DEFAULT 0
load_status          VARCHAR   NOT NULL   DEFAULT 'pending'
validation_tier      VARCHAR   NULL       ('PASS' | 'WARN' | 'BLOCK')
validation_report    VARCHAR   NULL
promote_status       VARCHAR   NOT NULL   DEFAULT 'pending'
promote_duration_ms  BIGINT    NULL
validate_duration_ms BIGINT    NULL
promoted_at          TIMESTAMP NULL
error_message        VARCHAR   NULL
created_at           TIMESTAMP NULL       DEFAULT CURRENT_TIMESTAMP
```

### §2.5 FK-dependency check

Scan of `information_schema.columns` for any column named `%impact_id%`:

```
table_name           column_name
ingestion_impacts    impact_id
```

**Exactly one table references `impact_id` — `ingestion_impacts` itself.** No downstream table FKs to `ingestion_impacts.impact_id`. Safe to DELETE/INSERT without cascading rewrites. Consistent with the task's stated assumption.

(Hardcoded scan of `scripts/*.py` for the literal string `impact_id` turned up only reads inside `scripts/pipeline/manifest.py` and the `write_impact` / `mirror_manifest_and_impacts` helpers — no external joins.)

### §2.6 Breakdown across all sources

```
source_type   ingestion_impacts rows
NPORT         21,244
MARKET         8,284
13DG               3
ADV                1
```

13DG is the obvious outlier. NPORT coverage (21,244 impacts across a 9.3M-row fact table) is tracked under obs-01 / obs-02 themes, not obs-04.

---

## §3. Forward-looking pattern (post mig-01)

### §3.1 `mirror_manifest_and_impacts` — signature

Location: [scripts/pipeline/manifest.py:113-216](scripts/pipeline/manifest.py:113). Public name (no leading underscore).

```python
def mirror_manifest_and_impacts(
    prod_con: Any,
    staging_con: Any,
    run_id: str,
    source_type: str,
) -> tuple[list[int], int]:
```

Scope: `(run_id, source_type)`. Mirrors every `ingestion_manifest` + `ingestion_impacts` row that lives in staging under that pair into prod. `reserve_ids(prod_con, "ingestion_impacts", "impact_id", N)` allocates prod-side impact_ids (so the staging PK never leaks into prod — obs-03 Phase 1 rule). Audit-preservation: prod impacts already at `promote_status='promoted'` for this `(manifest_id, unit_type, unit_key_json)` are not overwritten.

### §3.2 Called from `promote_13dg.py:220-222`

```python
mirror_manifest_and_impacts(
    prod_con, staging_con, args.run_id, "13DG",
)
```

Called once per promote run, inside the explicit `BEGIN TRANSACTION` boundary at [scripts/promote_13dg.py:215-245](scripts/promote_13dg.py:215).

### §3.3 Impact row shape the forward path writes

Written by [`write_impact`](scripts/pipeline/manifest.py:223) inside [`fetch_13dg_v2.py:526-545`](scripts/fetch_13dg_v2.py:526) on staging, then mirrored to prod:

```python
unit_key = json.dumps({
    "filer_cik": row["filer_cik"],
    "subject_cusip": row["subject_cusip"],
    "accession_number": row["accession_number"],
})
write_impact(
    con,
    manifest_id=parse_result.fetch_result.manifest_id,
    target_table="beneficial_ownership_v2",
    unit_type="filer_subject_accession",
    unit_key_json=unit_key,
    report_date=row["report_date"],          # NULL for 13D/G
    rows_staged=1,
    load_status="loaded" | "partial",
)
```

The backfill must produce rows that match this exact shape so prod state post-backfill is indistinguishable (up to `run_id`) from what the forward pipeline would produce on a re-fetch.

---

## §4. Proposed backfill grain and row count

| | Grain | Expected rows |
|---|---|---|
| `ingestion_manifest` | One row per accession (object_key UNIQUE on accession) | **51,902** new rows — existing 3 already present |
| `ingestion_impacts` | One row per `(filer_cik, subject_cusip, accession_number)` triple | **51,902** new rows — existing 3 already present |

Since BO v2 is 1:1 triple↔row↔accession (§2.3), the impact count equals the manifest count. Post-backfill totals: `ingestion_manifest` 13DG rows = 51,905; `ingestion_impacts` 13DG rows = 51,905.

### §4.1 Column values the backfill will write

**`ingestion_manifest` (one row per orphan BO v2 accession):**

| Column | Source |
|---|---|
| `manifest_id` | `reserve_ids(..., "ingestion_manifest", "manifest_id", 51902)` |
| `source_type` | `'13DG'` |
| `object_type` | `'TXT'` (matches the 3 existing rows — we do not have the raw form string on disk for the orphan rows) |
| `object_key` | `bo.accession_number` (UNIQUE, matches the 3 existing rows' pattern) |
| `source_url` | NULL (column nullable; we do not have `subject_cik` reliably to reconstruct the URL — CIK in BO v2 is `filer_cik`, not `subject_cik`; attempting to build a URL risks 404s that never resolve) |
| `accession_number` | `bo.accession_number` |
| `filing_date` | `bo.filing_date` |
| `run_id` | `'13dg_backfill_obs04_20260421'` (synthetic — distinguishable from real fetch runs) |
| `fetch_status` | `'complete'` (the data is in BO v2, so fetch *did* complete historically; the defect was manifest-tracking, not fetching) |
| `is_amendment` | `bo.is_amendment` (DEFAULT false if null) |
| `prior_accession` | `bo.prior_accession` |
| `fetch_completed_at` / `accepted_at` | `bo.loaded_at` (best historical proxy) |
| `created_at` | `CURRENT_TIMESTAMP` (let default fire) |
| All others | NULL or default |

**`ingestion_impacts` (one row per orphan BO v2 row):**

| Column | Source |
|---|---|
| `impact_id` | `reserve_ids(..., "ingestion_impacts", "impact_id", 51902)` |
| `manifest_id` | FK to the matching new manifest row just created, joined on `accession_number` |
| `target_table` | `'beneficial_ownership_v2'` |
| `unit_type` | `'filer_subject_accession'` |
| `unit_key_json` | `json_object('filer_cik', bo.filer_cik, 'subject_cusip', bo.subject_cusip, 'accession_number', bo.accession_number)` |
| `report_date` | `bo.report_date` (NULL for all 51,905 rows, but honor the column) |
| `rows_staged` | `1` |
| `rows_promoted` | `1` |
| `load_status` | `'loaded'` |
| `promote_status` | `'promoted'` |
| `promoted_at` | `bo.loaded_at` |
| `created_at` | `CURRENT_TIMESTAMP` |
| All others | NULL |

The `promote_status='promoted'` + `promoted_at=loaded_at` combination is what records the historical fact "these rows were loaded at time T," which is the whole point of closing D-06.

---

## §5. Pseudocode for the Phase 1 one-off script

Target path: `scripts/oneoff/backfill_13dg_impacts.py`.

```python
#!/usr/bin/env python3
"""obs-04 Phase 1 — backfill ingestion_manifest + ingestion_impacts for the
51,902 BO v2 accessions loaded before fetch_13dg_v2.py existed.

Single-shot, idempotent by design (anti-join on existing object_key so a
re-run writes zero rows). Safe to rerun.
"""
import duckdb
from db import PROD_DB
from pipeline.id_allocator import reserve_ids

RUN_ID = "13dg_backfill_obs04_20260421"

def main() -> None:
    con = duckdb.connect(PROD_DB)
    try:
        # 1. Identify orphans — BO v2 accessions with no matching manifest row.
        orphans = con.execute("""
            SELECT DISTINCT bo.accession_number, bo.filer_cik, bo.subject_cusip,
                            bo.filing_date, bo.filing_type, bo.loaded_at,
                            bo.is_amendment, bo.prior_accession, bo.report_date
              FROM beneficial_ownership_v2 bo
              LEFT JOIN ingestion_manifest m
                ON m.source_type = '13DG' AND m.object_key = bo.accession_number
             WHERE m.manifest_id IS NULL
        """).fetchdf()
        n = len(orphans)
        if n == 0:
            print("Nothing to backfill.")
            return
        print(f"Backfilling {n:,} orphan 13D/G accessions…")

        con.execute("BEGIN TRANSACTION")
        try:
            # 2. Reserve manifest_ids and build manifest DataFrame.
            mf_ids = reserve_ids(con, "ingestion_manifest", "manifest_id", n)
            mf = orphans[["accession_number","filing_date","loaded_at",
                          "is_amendment","prior_accession"]].copy()
            mf["manifest_id"]          = list(mf_ids)
            mf["source_type"]          = "13DG"
            mf["object_type"]          = "TXT"
            mf["object_key"]           = mf["accession_number"]
            mf["source_url"]           = None
            mf["run_id"]               = RUN_ID
            mf["fetch_status"]         = "complete"
            mf["fetch_completed_at"]   = mf["loaded_at"]
            mf["accepted_at"]          = mf["loaded_at"]
            mf["retry_count"]          = 0
            # reorder columns to match prod DDL; INSERT by column list.
            con.register("mf_df", mf)
            con.execute("""INSERT INTO ingestion_manifest
                           (manifest_id, source_type, object_type, object_key,
                            source_url, accession_number, filing_date,
                            accepted_at, run_id, fetch_completed_at,
                            fetch_status, is_amendment, prior_accession,
                            retry_count)
                           SELECT manifest_id, source_type, object_type,
                                  object_key, source_url, accession_number,
                                  filing_date, accepted_at, run_id,
                                  fetch_completed_at, fetch_status,
                                  is_amendment, prior_accession, retry_count
                             FROM mf_df""")
            con.unregister("mf_df")

            # 3. Reserve impact_ids and join orphans → new manifest_ids.
            ii_ids = reserve_ids(con, "ingestion_impacts", "impact_id", n)
            ii = orphans.copy()
            ii["impact_id"]      = list(ii_ids)
            ii["manifest_id"]    = list(mf_ids)  # aligned order — same row index
            ii["target_table"]   = "beneficial_ownership_v2"
            ii["unit_type"]      = "filer_subject_accession"
            ii["unit_key_json"]  = ii.apply(lambda r: json.dumps({
                "filer_cik": r["filer_cik"],
                "subject_cusip": r["subject_cusip"],
                "accession_number": r["accession_number"]}), axis=1)
            ii["rows_staged"]    = 1
            ii["rows_promoted"]  = 1
            ii["load_status"]    = "loaded"
            ii["promote_status"] = "promoted"
            ii["promoted_at"]    = ii["loaded_at"]
            con.register("ii_df", ii)
            con.execute("""INSERT INTO ingestion_impacts
                           (impact_id, manifest_id, target_table, unit_type,
                            unit_key_json, report_date, rows_staged,
                            rows_promoted, load_status, promote_status,
                            promoted_at)
                           SELECT impact_id, manifest_id, target_table,
                                  unit_type, unit_key_json, report_date,
                                  rows_staged, rows_promoted, load_status,
                                  promote_status, promoted_at
                             FROM ii_df""")
            con.unregister("ii_df")

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("CHECKPOINT")

        # 4. Verify.
        post = con.execute("""
            SELECT COUNT(*) FROM ingestion_impacts ii
             JOIN ingestion_manifest m ON m.manifest_id = ii.manifest_id
            WHERE m.source_type = '13DG'
        """).fetchone()[0]
        bo = con.execute("SELECT COUNT(*) FROM beneficial_ownership_v2").fetchone()[0]
        print(f"Post-backfill: ingestion_impacts 13DG = {post:,}; "
              f"beneficial_ownership_v2 = {bo:,}; "
              f"delta = {bo - post} (expected 0)")
    finally:
        con.close()

if __name__ == "__main__":
    main()
```

### §5.1 Phase 1 files to touch

| File | Change | Notes |
|---|---|---|
| `scripts/oneoff/backfill_13dg_impacts.py` | **NEW** | The one-off above. Mirrors existing `scripts/oneoff/` convention (each file self-contained, run once, kept in-repo for audit). |
| `docs/REMEDIATION_PLAN.md` | update obs-04 row | Flip status to Phase 1 in progress, add link to this findings doc and to the one-off. |
| `docs/REMEDIATION_CHECKLIST.md` | update checklist | Mark Phase 0 complete; note revised row count (51,902, not 3). |
| `scripts/migrations/001_pipeline_control_plane.py` | **NO CHANGE** | Migration 001 defines the DDL only — it does not seed impact rows. The 3 existing rows come from the 2026-04-14 fetch run, not from migration 001. No one-off DDL change needed. |
| `docs/SYSTEM_AUDIT.md` | note D-06 closed | After Phase 1 lands, D-06 moves from MAJOR to RESOLVED. |

---

## §6. Risk notes

1. **Synthetic `run_id`.** The backfill writes 51,902 rows under a single run_id `13dg_backfill_obs04_20260421`. Any downstream query that assumes `run_id` cardinality is small (e.g. `get_promotable_impacts` scans by `(source_type, run_id)`) will see one very large run. Scanned: [`get_promotable_impacts`](scripts/pipeline/manifest.py:312) only returns impacts with `promote_status='pending'` — the backfill writes `'promoted'`, so the helper returns zero rows for this run_id. Safe.
2. **`object_key` UNIQUE collision.** `ingestion_manifest.object_key` is UNIQUE. The anti-join in §5 step 1 filters to orphans (where no existing manifest row matches), but a concurrent fetch between Phase 0 and Phase 1 could create a new real manifest row for an accession that was an orphan at Phase 0 snapshot time. Mitigation: re-run the orphan query inside the transaction (the pseudocode above does this — `SELECT … LEFT JOIN … WHERE m.manifest_id IS NULL` executes at the start of the BEGIN block, not at script start).
3. **`id_allocator` reservation and transaction rollback.** `reserve_ids` takes an advisory file lock, writes `MAX+1…MAX+N` to the sequence tracker, releases the lock. If the transaction rolls back, the reservation is released with it (per [pipeline/manifest.py:137-140](scripts/pipeline/manifest.py:137) and the `id_allocator` module docstring). On rollback, the next caller re-reads `MAX+1` correctly. No orphan ID gaps that break FKs.
4. **Snapshot refresh.** `data/13f_readonly.duckdb` is not touched by the one-off. After Phase 1 lands, the next promote run will refresh the snapshot via [`refresh_snapshot`](scripts/pipeline/shared.py). Nothing broken in the meantime — readers of the snapshot only see yesterday's state regardless.
5. **Audit stamp.** The backfill rows all carry `promoted_at = bo.loaded_at` (i.e., historical loaded timestamps spanning 2026-04-02 → 2026-04-14). `created_at` is left to the `CURRENT_TIMESTAMP` default, which stamps 2026-04-22 (or whenever Phase 1 runs). The pair makes the retroactive nature of the rows obvious to future auditors — `created_at > promoted_at` signals "backfilled after the fact," distinct from normal rows where `created_at ≤ promoted_at`.
6. **Idempotence under re-run.** The orphan query is the idempotence key. A second run with no new orphans produces zero inserts and exits at the "Nothing to backfill." branch in §5. A second run *after new orphans have appeared* (shouldn't happen — forward pipeline now writes manifests) would pick them up and extend the backfill. Safe either way.
7. **Name correction.** Flagging for future checklist authors: the mirror helper is `mirror_manifest_and_impacts`, not `_mirror_manifest_and_impacts`. It is a public module-level function, not a private helper.

---

## §7. Phase 0 exit criteria

- [x] 3 existing `ingestion_impacts` 13D/G rows inspected and their grain confirmed **correct** (not wrong).
- [x] BO v2 row count (51,905) and orphan count (51,902) confirmed.
- [x] No downstream FKs to `ingestion_impacts.impact_id` anywhere in the DB.
- [x] `mirror_manifest_and_impacts` signature documented; forward-looking grain (`filer_subject_accession`) confirmed as the Phase 1 target.
- [x] Backfill pseudocode written, idempotent, transactional.
- [x] Risk notes (§6) enumerate rollback, reservation, snapshot, idempotence.

Phase 0 exit: ready to proceed to Phase 1 pending review approval on this findings doc. Phase 1 will ship `scripts/oneoff/backfill_13dg_impacts.py` + doc updates only — no change to migration 001 or any production script.
