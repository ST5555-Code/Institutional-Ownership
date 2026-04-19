# Precheck2 — `load_13f.py` liveness audit

Date: 2026-04-19
Scope: determine whether `scripts/load_13f.py` is dead code (retire) or
live code (scope rewrite block). Read-only audit at `main` (bc43d25).

## Classification

**LIVE** — invoked by an orchestrator and its output tables are read by
live application code. Not dead. No replacement script exists. Pipeline
coverage gap separately identified (see §4).

## 1. Invocations (subprocess / shell callers)

| # | Caller | Line | Form |
|---|--------|-----:|------|
| 1 | `scripts/update.py` | 47 | `steps = [..., "load_13f.py", ...]` — subprocess runner invokes it in the master update sequence |
| 2 | `scripts/benchmark.py` | 20 | `("load_13f.py", "Load TSVs into DuckDB")` — listed in benchmark script registry |

Caveat on #1: `update.py` is itself partially stale — it still references
retired `fetch_nport.py` and missing `unify_positions.py` (verified: neither
file exists at HEAD). The canonical orchestrator is the Makefile
(`quarterly-update`), not `update.py`. But `update.py` remains a runnable
entrypoint and has not been retired.

## 2. Module imports

None. Grep for `import load_13f|from load_13f` returned zero hits under
`scripts/`.

## 3. Downstream consumers of `load_13f.py` output tables

`load_13f.py` owns writes to six tables (per `scripts/pipeline/registry.py`
lines 69, 74, 79, 113, 118, 175): `raw_submissions`, `raw_infotable`,
`raw_coverpage`, `filings`, `filings_deduped`, `other_managers`.

Live readers at HEAD (excluding `load_13f.py` itself and `scripts/retired/**`):

| Table | Reader | Line | Context |
|-------|--------|-----:|---------|
| `filings` | `scripts/api_register.py` | 252, 258 | app UI (Register tab) — live |
| `filings_deduped` | `scripts/build_managers.py` | 227, 298, 501 | managers build — live |
| `filings_deduped` | `scripts/fetch_13dg_v2.py` | 113 | 13D/G v2 fetcher — live |
| `raw_submissions` / `raw_infotable` / `raw_coverpage` | (no external readers) | — | read only inside `load_13f.py` |
| `other_managers` | (no external readers found) | — | — |

At least one live app path (`api_register.py` → `filings`) reads data that
only `load_13f.py` produces. This alone is sufficient to classify LIVE.

## 4. Makefile / scheduler / cron coverage

- `Makefile` — `quarterly-update` target calls `fetch-13f` (download
  only), `fetch-nport`, `build-entities`, `compute-flows`, `fetch-market`,
  `build-summaries`, `build-classifications`, `backup-db`, `validate`.
  **Does NOT invoke `load_13f.py`.** This is a pipeline coverage gap:
  running `make quarterly-update` on a fresh DB would not populate
  `filings` / `filings_deduped` / raw tables.
- `scripts/run_pipeline.sh` — no references to `load_13f`.
- `scripts/scheduler.py` — no references.
- `data/schedule.json` — file does not exist.
- `scripts/benchmark.py` — references `load_13f.py` (item #2 above) but
  is a benchmark tool, not a scheduler.

Inference: the current quarterly refresh depends on either (a) an
operator running `python3 scripts/update.py` manually, or (b) running
`python3 scripts/load_13f.py` directly between `fetch_13f.py` and the
Makefile sequence. The Makefile docstring claims "Single entry point for
the quarterly refresh sequence" — this is aspirational given the gap.

## 5. Replacement scripts

- `scripts/load_13f_v2.py` — does not exist.
- `scripts/promote_13f.py` — does not exist, though `registry.py:88`
  declares `holdings_v2` owner as `scripts/promote_13f.py (proposed)`.

No replacement is in-flight at HEAD. `load_13f.py` is the only writer
for its six owned tables.

## 6. Git history

```
88d01d2  Major data quality fixes: market_value_usd, manager_type, FLOW_PERIODS, pct_of_float
5bff348  Name resolution pipeline, short squeeze signals, incremental load, quarter centralization
fc9c98a  Bug fixes 6-7, pyflakes cleanup, performance improvements, architecture refactor
```

Last touch on `scripts/load_13f.py` was `88d01d2`, pre-CUSIP-v1.4 cutover.
No recent maintenance, consistent with its REWRITE flag across the docs
(`pipeline_inventory.md:59`, `pipeline_violations.md:179`,
`canonical_ddl.md:23,28,29,40,79,99,262,328,396`,
`SYSTEM_ATLAS_2026_04_17.md:192,206,212,231,279,293,313,383,642`,
`SYSTEM_AUDIT_2026_04_17.md:137`).

## 7. Notes on legacy artifacts

`load_13f.py:222-284` creates the pre-Stage-5 `holdings` table (dropped
since 2026-04-13). That DROP+CTAS path writes to a dropped table — dead
output. But the same script still produces `filings`, `filings_deduped`,
and the three raw tables, which are not dropped and whose writes remain
functional.

The legacy `holdings` CTAS is dead output within a live script. Rewriting
the script should drop that path while preserving the filings and raw
writers (or replace them with a new promoter).

## 8. Recommendation

**Full REWRITE block, scoped separately.** Do not retire.

Rewrite surface (estimate — to be refined in the rewrite's own precheck):

- ~380 LOC in `scripts/load_13f.py` (full file rewrite likely — multiple
  pipeline-rules violations: §1 DROP+CTAS, §5 silent continue on missing
  TSV at `:37`, §9 no `--dry-run`, no CHECKPOINT, no `data_freshness`
  stamp; per `pipeline_violations.md:179-190`).
- Target naming: `load_13f_v2.py` or split into fetch (already exists as
  `fetch_13f.py`) + `promote_13f.py` matching the registry's proposed
  shape at `registry.py:88`.
- Retrofits needed: incremental save + CHECKPOINT, `data_freshness`
  writer (P-01 open per `SYSTEM_ATLAS:313`), `--dry-run`, fail-fast on
  missing TSV, drop the legacy `holdings` CTAS.
- Upstream: `fetch_13f.py` (download + extract — no schema coupling).
- Downstream: `filings` (→ `api_register.py`), `filings_deduped`
  (→ `build_managers.py`, `fetch_13dg_v2.py`). Column shapes must be
  preserved or consumers updated in the same block.
- Side concern: fix the Makefile gap — either add `load-13f` target
  between `fetch-13f` and `build-entities`, or fold the load into the
  `fetch-13f` recipe. Retire `scripts/update.py` once the Makefile is
  complete (it's the only other invocation path).

## 9. Summary

- **Classification:** LIVE
- **Recommendation:** full REWRITE block, scoped separately
- **Do not retire in a follow-up block.**
- **Secondary finding (not blocking):** Makefile `quarterly-update`
  omits the 13F load step — pipeline coverage gap. Track separately.
- **Tertiary finding:** `scripts/update.py` references retired
  `fetch_nport.py` and missing `unify_positions.py`. It is stale and
  should itself be retired or repaired — track separately.
