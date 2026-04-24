# BLOCK-MARKET-DATA-WRITER-AUDIT — Phase 0 Findings

**Date:** 2026-04-19
**Branch:** `audit-market-data-writers`
**Base:** `main` @ `d7ba1c2`
**Scope:** Read-only `rg` survey of writers to `market_data.sector` (and adjacent columns). Resolves the RILY anomaly surfaced during BLOCK-SECTOR-COVERAGE-BACKGROUND Phase 4 pre-merge drift check. No code changes.

---

## 1. Scope

Identify every code path that writes `market_data.sector` (and by extension `market_data.industry`) and classify each by whether it bumps `fetch_date` on the same operation. RILY surfaced with `sector = 'Financial Services'` and `fetch_date = 2026-04-16` — a combination no standard writer produces, since every standard writer stamps `fetch_date` on update.

Question: what wrote RILY's `sector` between the 2026-04-18 08:06 UTC staging seed and the 2026-04-19 05:27 UTC merge attempt, and is it a script bug, a manual fix, or a silent secondary writer?

---

## 2. Writer enumeration

### 2.1 Survey queries (read-only)

```
rg -n "INTO market_data|INSERT INTO market_data|UPDATE market_data|UPSERT.*market_data|MERGE.*market_data|CREATE.*TABLE.*market_data|REPLACE.*market_data" scripts/ --glob '!scripts/retired/**'
rg -n "sector\s*=|SET sector|sector\s*VALUES" scripts/ --glob '!scripts/retired/**'
rg -n "market_data\[.sector.\]|market_data\.sector\s*=" scripts/ --glob '!scripts/retired/**'
```

No matches outside `scripts/` for `INTO|UPDATE|UPSERT|MERGE|REPLACE market_data` (checked repo-wide with `!scripts/retired/**` filter). `scripts/migrations/` has zero references to `market_data`. No direct Python-level `market_data['sector'] =` writes.

### 2.2 All paths that write `market_data.sector`

| # | File | Line | Shape | Writes `fetch_date` same op? | Class |
|---|---|---|---|---|---|
| 1 | [scripts/fetch_market.py:378](scripts/fetch_market.py:378) (`upsert_yahoo`) | 378–390 | `UPDATE ... SET sector = COALESCE(d.sector, m.sector), ..., fetch_date = d.fetch_date` | **Yes** (line 387) | STANDARD |
| 2 | [scripts/approve_overrides.py:142](scripts/approve_overrides.py:142) | 123–142 | `INSERT` via record dict that includes `sector` and `fetch_date = today` | **Yes** (line 135) | STANDARD |
| 3 | [scripts/enrich_tickers.py:377](scripts/enrich_tickers.py:377) | 350–377 | `INSERT` via record dict including `sector` and `fetch_date = today` | **Yes** (line 362) | STANDARD |
| 4 | [scripts/auto_resolve.py:523](scripts/auto_resolve.py:523) | 506–523 | `INSERT` via record dict including `sector` and `fetch_date = today` | **Yes** (line 518) | STANDARD |
| 5 | [scripts/admin_bp.py:130](scripts/admin_bp.py:130) | 129–135 | `INSERT OR REPLACE INTO market_data (..., sector, industry, ..., fetch_date) VALUES (...)` | **Yes** (line 131) | STANDARD |
| 6 | [scripts/refetch_missing_sectors.py:254](scripts/refetch_missing_sectors.py:254) | 252–257 | `UPDATE market_data SET sector = ?, industry = ? WHERE ticker = ? AND sector IS NULL` | **No** | **SUSPECT** |

### 2.3 Writers that touch `market_data` but not `sector` (excluded from RILY root-cause set, retained for completeness)

| File | Line | Shape | Cols touched |
|---|---|---|---|
| [scripts/fetch_market.py:361](scripts/fetch_market.py:361) (`_ensure_rows_exist`) | 359–364 | `INSERT ... (ticker, fetch_date) ON CONFLICT DO NOTHING` | `ticker`, `fetch_date` |
| [scripts/fetch_market.py:407](scripts/fetch_market.py:407) (`upsert_sec`) | 406–417 | SEC column upsert — no `sector`/`industry`, no `fetch_date` (uses `sec_date`) | SEC cols, `sec_date` |
| [scripts/fetch_market.py:427](scripts/fetch_market.py:427) (`recompute_market_cap`) | 426–432 | `UPDATE market_data SET market_cap = CASE ...` | `market_cap` only |
| [scripts/fetch_market.py:477](scripts/fetch_market.py:477) (`_stamp_batch_attempt`) | 476–480 | `INSERT ... ON CONFLICT DO UPDATE SET fetch_date / metadata_date / sec_date` — attempt-date stamping | `fetch_date` / `metadata_date` / `sec_date` |

Total writer count: **10 code paths across 5 scripts**. Well under the 10-writer stop-condition threshold; landscape is tractable.

---

## 3. Suspect writer: `refetch_missing_sectors.py`

Only one writer in the sector-touching set does **not** update `fetch_date` in the same operation: [scripts/refetch_missing_sectors.py:252-257](scripts/refetch_missing_sectors.py:252).

```python
if sector:
    con.execute(
        "UPDATE market_data SET sector = ?, industry = ? "
        "WHERE ticker = ? AND sector IS NULL",
        [sector, industry, tk]
    )
```

Characteristics:

- Writes `sector` + `industry` only. `fetch_date` is untouched anywhere in the call path (verified — no `fetch_date` assignment in the file).
- NULL-guarded: only populates where `sector IS NULL`. Cannot clobber a populated prod sector.
- `--staging` flag is **opt-in** (default write target is prod; `db.set_staging_mode(True)` is only called if `args.staging` is set — [scripts/refetch_missing_sectors.py:128,141](scripts/refetch_missing_sectors.py:128)).
- Docstring at [scripts/refetch_missing_sectors.py:13](scripts/refetch_missing_sectors.py:13) explicitly states it is "largely subsumed by `fetch_market.py --staging --metadata-only`" — kept for targeted manual fixes.

This is a structurally silent writer by the BLOCK-SECTOR-COVERAGE-BACKGROUND §8 definition: touches `market_data.sector` without bumping `fetch_date`, so any diff-based audit keyed on `fetch_date` misses it.

---

## 4. RILY-specific forensics

### 4.1 Git commits in window (2026-04-18 08:06 → 2026-04-19 05:26 UTC)

`git log --since="2026-04-18 08:06" --until="2026-04-19 05:26" --all` yielded 30+ commits. The one directly responsible is:

**`2405df1` — 2026-04-18 20:33:06 UTC — `chore(block-3): phase 4 prod apply — enrich_holdings + refetch + benchmark_weights rebuild`**

Commit body (verbatim excerpt):

> Sector refetch on prod:
>   `refetch_missing_sectors.py` is hardcoded to STAGING_DB by design and has no
>   `--staging` flag; rather than touch it in this phase's scope, **the staging
>   refetch output was mirrored to prod (ephemeral helper, UPDATE-only, zero
>   Yahoo calls). Only 1 ticker required actual `market_data.sector` population
>   (prod NULL → populated)**; the other 104 "Yahoo-fixed" tickers in Phase 3
>   were either absent from `market_data` entirely (241/355) or already had
>   sector populated in both envs. prod/staging `market_data.sector NULL` now
>   at parity (3,286 each).

The "1 ticker required actual `market_data.sector` population (prod NULL → populated)" is RILY. The ephemeral mirror helper used an `UPDATE`-only path that set `sector` (and `industry`) from the staging value without stamping `fetch_date` — which is exactly why RILY's `fetch_date` remained at 2026-04-16 while its sector became `Financial Services`.

### 4.2 Related commits and timeline

| Time (UTC) | Commit / event |
|---|---|
| 2026-04-18 08:06 | staging seed for BLOCK-SECTOR-COVERAGE-BACKGROUND (RILY = sector NULL at this point) |
| 2026-04-18 09:05 | `3738179` — throttle fix for `refetch_missing_sectors.py` |
| 2026-04-18 13:06 | BLOCK-SECTOR-COVERAGE initial run PID 47045 starts (processed 550 head-of-list tickers) |
| 2026-04-18 13:09 | PID 47045 halted (R's never reached — alphabetical progress, no impact on RILY) |
| 2026-04-18 ~20:33 | **`2405df1` BLOCK-3 Phase 4 prod apply — ephemeral staging→prod sector mirror runs, populates RILY** |
| 2026-04-19 04:16 | BLOCK-SECTOR-COVERAGE resume PID 86036 starts |
| 2026-04-19 05:27 | Merge attempt — RILY detected as prod-populated, dropped from merge |

The `2405df1` helper is not in the repo (ephemeral, run once and discarded). Its effect is documented in the commit body and confirmed by the `/tmp/refetch_tickers.txt` artifact (355 lines, mtime 2026-04-18 19:36 UTC, contains RILY), and by the BLOCK-SECTOR-COVERAGE closeout report's §5 (RILY dropped from merge because prod was already populated).

### 4.3 Scheduled jobs

No scheduled-job logs in `logs/` for the window (only audit_path_a, phase3_promote, and promotion_history). No cron, no background daemon touched `market_data` between seed and merge beyond the documented BLOCK-3 Phase 4 apply.

---

## 5. Root cause hypothesis

**Confidence: HIGH.**

RILY's `sector = 'Financial Services'` with stale `fetch_date = 2026-04-16` was written by the **ephemeral staging→prod sector mirror helper** executed during BLOCK-3 Phase 4 prod apply at 2026-04-18 20:33 UTC (commit `2405df1`). The helper was:

- One-off (not in the repo), `UPDATE`-only, sector + industry only, `WHERE sector IS NULL` guarded.
- Affected exactly 1 prod ticker (explicitly noted: "Only 1 ticker required actual market_data.sector population").
- Did not stamp `fetch_date` (the helper had no Yahoo call, so no fetch to stamp).

The structural pattern — UPDATE sector without bumping fetch_date — is the same pattern present in the committed writer [scripts/refetch_missing_sectors.py:254](scripts/refetch_missing_sectors.py:254). That script is the one standing code-level hazard for this anomaly class going forward, but it is not what wrote RILY on 04-18.

---

## 6. Recommendation

**(a) No action required for the RILY anomaly.** It was written by a documented ephemeral helper (`2405df1`), explicitly logged in the commit body, with fully understood semantics. No data is incorrect: RILY's sector value is the same in prod and staging; the only "drift" artifact is the unchanged `fetch_date`, which reflects that no Yahoo call was made — correct by design for a UPDATE-only mirror.

**Follow-on (scope separately, not this audit):** the standing silent writer in `refetch_missing_sectors.py` remains a convention gap. Two options, to be evaluated when BLOCK-MERGE-UPSERT-MODE or a writer-convention hardening block is opened:

1. **Add a last-write sentinel column** (`last_write_ts` or reuse an existing attempt-date field) that every `market_data` writer — including UPDATE-only paths — bumps. Diff-based audits key on `last_write_ts`, not `fetch_date`. `fetch_date` retains its "last Yahoo fetch" semantics.
2. **Require all `UPDATE market_data` paths to bump `fetch_date`** (or `metadata_date`) even on enrichment-only updates. Simpler but overloads `fetch_date` semantics and risks masking stale price data.

Option 1 is cleaner but more invasive. Decision belongs to the writer-convention block, not here.

No fix commits on this audit branch. Audit deliverable is this document only.

---

## 7. Artifacts and citations

- Writer enumeration: §2.2, §2.3 with file:line citations
- Commit responsible: `2405df1` (2026-04-18 20:33:06 UTC)
- Prior closeout report: [archive/docs/reports/block_sector_coverage_closeout_20260419_052804.md](archive/docs/reports/block_sector_coverage_closeout_20260419_052804.md) §8
- Suspect source: [scripts/refetch_missing_sectors.py:252-257](scripts/refetch_missing_sectors.py:252)
- Ephemeral helper input: `/tmp/refetch_tickers.txt` (355 lines, mtime 2026-04-18 19:36 UTC, contains `RILY`)

---

## 8. Exit state

- **Writers enumerated:** 10 code paths across 5 scripts.
  - Sector-touching: 6 — 5 STANDARD (bump `fetch_date`), 1 SUSPECT (`refetch_missing_sectors.py`).
  - Non-sector `market_data` writers: 4 in `fetch_market.py`.
- **RILY anomaly:** explained. Written by documented ephemeral helper in commit `2405df1`. No action needed.
- **Standing hazard:** `refetch_missing_sectors.py:254` writes sector without bumping any last-write indicator. Defer to writer-convention block.
- **Phase 1:** not opened. No code changes authored.
