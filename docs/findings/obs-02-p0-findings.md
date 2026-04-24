# obs-02-p0 — Phase 0 findings: ADV freshness + log discipline

**Branch:** `remediation/obs-02-p0` off main HEAD (`9712a0e`).
**Audit refs:** [SYSTEM_AUDIT §P-02](../SYSTEM_AUDIT_2026_04_17.md), [SYSTEM_ATLAS §3 P-02](../SYSTEM_ATLAS_2026_04_17.md), [CODEX_REVIEW P-02](2026-04-17-codex-review.md), [REMEDIATION_PLAN obs-02](../REMEDIATION_PLAN.md), [REMEDIATION_CHECKLIST Batch 2-B](../REMEDIATION_CHECKLIST.md).
**Investigation only — no code, no DB writes.**

## TL;DR

| Gap | Status | Root cause |
|---|---|---|
| `data_freshness('adv_managers')` missing in prod | **Confirmed** | `record_freshness` hook is wired in code (commit `831e5b4`, [fetch_adv.py:278](scripts/fetch_adv.py:278)), but `fetch_adv.py` has not been re-run against prod since that commit landed. Process gap, not a code bug. |
| `fetch_adv.py` has no structured logging | **Confirmed** | Script uses `print()` only. No `import logging`, no log file, no per-run rotation. Same shape as `fetch_market.py` and `fetch_ncen.py`. |
| obs-01-p1 manifest writes | **Present, empty** | Manifest wiring from PR #24 is live in code, but `ingestion_manifest` has zero ADV rows in prod (same reason — script hasn't run). A single prod re-run closes both gaps. |

## 1. Freshness gap

### 1.1 Code state (post-`831e5b4`, post-obs-01-p1)

[scripts/fetch_adv.py:278](scripts/fetch_adv.py:278), inside `save_to_duckdb()`:

```python
con.execute("CHECKPOINT")
record_freshness(con, "adv_managers", row_count=row_count)
con.close()
```

Hook is correctly wired. `record_freshness` is imported from `db` at [scripts/fetch_adv.py:33](scripts/fetch_adv.py:33). Semantics: `INSERT OR REPLACE INTO data_freshness (table_name, last_computed_at, row_count) VALUES (?, CURRENT_TIMESTAMP, ?)` ([scripts/db.py:163-190](scripts/db.py:163)).

### 1.2 Prod DB state (read-only check, `data/13f.duckdb`, 2026-04-21)

```
-- data_freshness for adv_managers
NO ROW FOUND

-- adv_managers physical table
row_count = 16,606

-- data_freshness newest 3 rows (none are adv_managers)
holdings_v2                 2026-04-19 13:32:08  12,270,984
holdings_v2_enrichment      2026-04-19 13:32:08  10,394,757
cik_crd_links               2026-04-19 09:16:03         353

-- ingestion_manifest for source_type='ADV'
(no rows)

-- ingestion_impacts for target_table='adv_managers'
(no rows)
```

`adv_managers` is physically loaded but unfreshness-stamped and unmanifested. Both gaps close the moment `fetch_adv.py` is next executed against prod.

### 1.3 Root cause

Not a code defect. Git history confirms the freshness hook landed in `831e5b4` ("feat: Makefile + freshness hooks + validate read-only + docs") and obs-01-p1 landed in `a12b4d8`. No commit touching `fetch_adv.py` has landed since. The script simply hasn't been run since the hook + manifest wiring were merged — the 16,606 rows in `adv_managers` predate both.

### 1.4 Minor code smells (Phase 1 candidates, not blockers)

- **Unguarded `record_freshness` call.** `fetch_adv.py:278` does not wrap the call in try/except. `fetch_ncen.py:629-633` does:
  ```python
  try:
      con.execute("CHECKPOINT")
      record_freshness(con, "ncen_adviser_map")
  except Exception as e:
      print(f"  [warn] record_freshness(ncen_adviser_map) failed: {e}", flush=True)
  ```
  If `data_freshness` were ever missing, the unguarded call would bubble an exception through `save_to_duckdb()` into `main()`'s except-block, which would then mark the manifest `failed` even though the table load succeeded. Low probability (the table is present in prod), but the asymmetry is worth closing.
- **CHECKPOINT ordering.** The `CHECKPOINT` at [scripts/fetch_adv.py:277](scripts/fetch_adv.py:277) runs *before* `record_freshness`, so the freshness INSERT is not explicitly checkpointed. DuckDB persists it on `con.close()` via WAL flush, so this is safe in practice — but moving the CHECKPOINT to after the freshness write would be cleaner and matches fetch_ncen.

## 2. Logging audit

### 2.1 `fetch_adv.py`

- `grep -nE 'import logging|getLogger|logger\.' scripts/fetch_adv.py` → **zero matches.**
- All diagnostic output is `print(...)`. No `flush=True` on most print calls — stdout buffering can swallow output when redirected (see memory: "Python output buffering").
- No log file is created. The Makefile target at [Makefile:134-135](Makefile:134) shells out plain:
  ```
  fetch-adv:
      $(Q) $(PY) $(SCRIPTS)/fetch_adv.py
  ```
  No stdout redirection, no tee. Operators must redirect manually.
- `logs/` contains zero `fetch_adv*.log` files. `fetch_adv_crash.log` would be produced by `db.crash_handler("fetch_adv")` ([scripts/fetch_adv.py:387](scripts/fetch_adv.py:387)) on unhandled exception, but nothing for successful runs.

### 2.2 Comparison with the prompt's "reference implementation"

The prompt cites `fetch_market.py` as a reference for structured logging. **It isn't.** `grep -nE 'import logging|getLogger|logger\.' scripts/fetch_market.py` → zero matches. `fetch_market.py` uses `print()` as well, and existing `logs/fetch_market_*.log` files in `logs/` are produced by manual shell redirection (`python3 scripts/fetch_market.py > logs/fetch_market_<date>.log`), not by the script itself.

No fetcher in `scripts/` currently uses Python `logging`. obs-02 is the first item to introduce structured logging to a fetcher.

### 2.3 Operational impact

Without a log file per run:
- Crash diagnostics depend on `logs/fetch_adv_crash.log`, which captures only the final traceback — not the run context (URL, row counts, elapsed time).
- Post-hoc freshness reconstruction is impossible — if the DB is rolled back, there's no record of when the last successful parse ran.
- The admin-dashboard "Last run / Age / Status" fields for ADV (per [REMEDIATION_PLAN.md:317](../REMEDIATION_PLAN.md:317)) have no underlying data to surface.

## 3. obs-01-p1 interaction

Sequence inside `main()` ([scripts/fetch_adv.py:283-381](scripts/fetch_adv.py:283)):

1. Connection A: `get_or_create_manifest_row(... fetch_status='fetching')`, `update_manifest_status(...)`, `CHECKPOINT`, close.
2. Download + parse in-memory.
3. Connection B (inside `save_to_duckdb`): DROP+CREATE `adv_managers`, `CHECKPOINT`, `record_freshness`, close.
4. Connection C: DELETE prior `ingestion_impacts` row, `write_impact(... promote_status='promoted')`, `update_manifest_status(... 'complete')`, `CHECKPOINT`, close.

Three serial connections to the same PROD_DB file. No ordering hazard — each connection commits before the next opens. On failure (anywhere in steps 2-3), the except-block on [scripts/fetch_adv.py:338-349](scripts/fetch_adv.py:338) flips the manifest to `failed` on a fresh connection. That includes the case where an unguarded `record_freshness` inside `save_to_duckdb` raises (see §1.4).

**Verdict:** obs-01-p1 and the freshness hook do not conflict. One re-run of `fetch_adv.py` will populate `ingestion_manifest` + `ingestion_impacts` + `data_freshness` atomically from the operator's perspective.

## 4. Cross-item awareness

- **mig-02** (fetch_adv.py DROP+CREATE atomicity): same file; must run serially. `save_to_duckdb` currently does `DROP TABLE IF EXISTS adv_managers; CREATE TABLE adv_managers AS SELECT * FROM df_out` — a failure between those statements leaves prod with no `adv_managers`. obs-02 logging changes should not mask that gap or make it harder to diagnose.
- **obs-01** (merged): already done. This investigation inherits its wiring.
- **sec-06** (inline UA fix, per REMEDIATION_PLAN.md:519): `SEC_HEADERS` at [scripts/fetch_adv.py:36](scripts/fetch_adv.py:36) hardcodes `serge.tismen@gmail.com`. Out of scope here, flagged for that item.

## 5. Phase 1 scope proposal

**Minimum to close P-02:**

1. **Re-run `fetch_adv.py` against prod.** This alone writes the `data_freshness('adv_managers')` row, the `ingestion_manifest` row, and the `ingestion_impacts` row. Confirms obs-01-p1 wiring end-to-end. *Must be explicitly authorized by user per feedback-memory `feedback_no_unauthorized_runs.md`.*
2. **Wrap `record_freshness` in try/except** in `save_to_duckdb` ([scripts/fetch_adv.py:278](scripts/fetch_adv.py:278)) matching `fetch_ncen.py:629-633` — freshness failures must not fail the run.
3. **Move `CHECKPOINT`** to after `record_freshness` so both the DROP+CREATE and the freshness stamp commit together.

**Structured logging (the "log discipline" half of P-02):**

4. Add a small `pipeline/logging_setup.py` helper: builds a `logging.Logger` with `FileHandler(logs/fetch_adv_<run_id>.log)` + `StreamHandler(sys.stdout)`, INFO-level by default, format `%(asctime)s %(levelname)s %(message)s`. Keep StreamHandler so operators still see live output at the terminal.
5. Replace `print(...)` in `fetch_adv.py` with `logger.info(...) / logger.warning(...) / logger.error(...)`. Preserve existing message strings so external log-scrapers don't break.
6. Write `run_id` + `ADV_ZIP_URL` + row counts + elapsed seconds as structured fields at the start and end of `main()`.

**Deferred / out of scope:**

- Same logging helper applied to `fetch_ncen.py` + `fetch_market.py` — consistent pattern, but not required by P-02. Flag as a follow-up (possibly obs-10 or a dedicated logging-rollout item).
- Log rotation policy (retain N days of `fetch_adv_*.log`). Not in original audit scope.
- `parser_version` / `schema_version` population — deferred to obs-09 per [obs-01-p1 decision table](../prompts/obs-01-p1.md).

## 6. Acceptance criteria for Phase 1

- Post-run, `SELECT * FROM data_freshness WHERE table_name = 'adv_managers'` returns one row with `last_computed_at` within seconds of the run.
- `logs/fetch_adv_<run_id>.log` exists and contains the URL, row counts, elapsed time, and final `data_freshness` stamp line.
- `ingestion_manifest` contains one ADV row with `fetch_status='complete'`; `ingestion_impacts` contains one row with `target_table='adv_managers'`, `promote_status='promoted'`, matching `rows_promoted`.
- No regression in `adv_managers` row count (16,606 → N where N is the new download; expected drift < 5%).

## 7. Hard stop

No code or DB writes were made in this session. Phase 1 implementation is a separate item (`remediation/obs-02-p1`) and requires user authorization before any prod run.
