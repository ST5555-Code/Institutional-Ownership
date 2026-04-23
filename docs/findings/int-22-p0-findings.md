# int-22 Phase 0 Findings — prod `is_latest` inversion

_Generated: 2026-04-22. Diagnosis + staging proof. Prod fix is a Terminal-only follow-up._

## 1. Problem statement

From [ui-audit-01-triage.md §Technical anomalies item 1](https://github.com/stismen/13f-ownership/pull/107/files#diff-ui-audit-01-triage):

> **`is_latest=TRUE` inversion on prod DB for `quarter='2025Q4'`.** Every `is_latest=TRUE` row has `ticker IS NULL`; every row with a ticker has `is_latest=FALSE`. Previous quarters (2025Q2, Q3) store only `is_latest=TRUE`. Recent commits 9d26eb1 and a7abb79 backfill the CI fixture but did not touch `data/13f.duckdb`. Affected endpoints (all filter `WHERE is_latest=TRUE AND quarter=LQ`): `/api/v1/tickers` returns 0 rows; `/api/v1/fund_portfolio_managers` 0 rows on AAPL; `/api/v1/portfolio_context` 0 rows on AAPL; most 2025Q4-filtering queries inside `queries.py` return empty.

Plain English: a 13F loader re-run earlier today re-ingested every 2025Q4 13F filing as a fresh insert with `ticker=NULL` (ticker is populated downstream, not in the load). The loader's amendment-handling logic correctly flagged the new inserts `is_latest=TRUE` and flipped the old (ticker-enriched) rows to `is_latest=FALSE`. Ticker enrichment was not re-run. Every query that filters `is_latest=TRUE AND quarter='2025Q4'` now sees only the tickerless population.

## 2. Root cause

Confirmed from prod read-only inspection of `data/13f.duckdb`:

1. Migration 015 stamped prod at **2026-04-22 11:46:54** ([015_amendment_semantics.py](scripts/migrations/015_amendment_semantics.py)) — set `is_latest=TRUE` on the existing enriched population (3.2M rows with tickers).
2. A 13F-v2 load was triggered twice on 2025Q4 that afternoon:
   - `13f_holdings_quarter=2025Q4_20260422_191810` (manifest_id=78901) — **failed** with 0 impacts. No effect.
   - `13f_holdings_quarter=2025Q4_20260422_200854` (manifest_id=78902) — **complete** at **16:08:54**. Wrote **8,636 `flip_is_latest` + 8,636 `insert` impact rows** (one of each per `(cik, quarter=2025Q4)` key).
3. [load_13f_v2.py:515](scripts/load_13f_v2.py:515) inserts every row as `NULL AS ticker`. The SEC bulk ZIP TSV does not carry a ticker column; ticker is a separate enrichment join from `securities` that runs downstream.
4. [pipeline/base.py:462-469](scripts/pipeline/base.py:462) — the `append_is_latest` promote path — ran its standard logic: for each `(cik, quarter)` amendment key, UPDATE prior `is_latest=TRUE` rows to FALSE, then INSERT the new rows as TRUE. Correct by strategy contract; wrong outcome because the new rows were missing a column the displaced rows had populated.
5. Ticker enrichment was not rerun against the new `is_latest=TRUE` population.

**The bug is not in the `append_is_latest` strategy. The bug is a load-idempotency / enrichment-sequencing gap.** See §10 and the `int-23` follow-up.

## 3. Scope on prod

Diagnostic queries run read-only against `data/13f.duckdb` at 2026-04-22 ~21:00:

### `holdings_v2` — per-quarter `is_latest` × `ticker` matrix

| quarter | `is_latest=TRUE` | ...AND `ticker IS NULL` | ...AND `ticker NOT NULL` | `is_latest=FALSE` | ...AND `ticker NOT NULL` | total |
|---|--:|--:|--:|--:|--:|--:|
| **2025Q4** | **3,205,868** | **3,205,868** (100%) | **0** | **3,205,650** | **2,722,570** (84.9%) | **6,411,518** |
| 2025Q3 | 3,024,698 | 459,221 (15.2%) | 2,565,477 | 0 | — | 3,024,698 |
| 2025Q2 | 3,047,474 | 470,462 (15.4%) | 2,577,012 | 0 | — | 3,047,474 |
| 2025Q1 | 2,993,162 | 463,464 (15.5%) | 2,529,698 | 0 | — | 2,993,162 |

2025Q4 total row count (~6.4M) is roughly double the other quarters (~3M each). Per-`(accession_number)` check: 8,586 of 8,636 accessions appear on both the TRUE and FALSE side — the same filings were loaded twice. The 50 accessions unique to the TRUE side are filings first ingested by this re-run; the 50 unique to the FALSE side are filings that missed the re-run.

### `fund_holdings_v2` and `beneficial_ownership_v2` — **NOT AFFECTED**

- `fund_holdings_v2` has 0 `is_latest=FALSE` rows across all quarters. N-PORT tickerless rates (30–80%) are higher than 13F because funds hold non-ticker assets (bonds, private issues, options), and do not indicate inversion.
- `beneficial_ownership_v2` has 0 `is_latest=TRUE AND subject_ticker IS NULL` rows — partition-based amendment semantics from Migration 015 work correctly.

**Conclusion: inversion is scoped to `holdings_v2` for `quarter='2025Q4'` only.**

## 4. Why the fixture backfill SQL does NOT apply to prod

Commits `9d26eb1` and `a7abb79` added this to [build_fixture.py:213-220](scripts/build_fixture.py:213):

```sql
UPDATE holdings_v2 SET is_latest = TRUE WHERE is_latest IS NOT TRUE;
UPDATE fund_holdings_v2 SET is_latest = TRUE WHERE is_latest IS NOT TRUE;
```

That logic is correct for the fixture: the fixture filters amendments out of scope, so any row that survives the filter should be treated as current, and an unconditional flip-to-TRUE is safe.

**It is NOT safe on prod.** Applying it would leave *both* populations on 2025Q4 `holdings_v2` (tickerless duplicates + ticker-enriched originals) as `is_latest=TRUE`. Every query filtering `is_latest=TRUE AND quarter='2025Q4'` would return duplicated rows, doubling market-value totals, holding counts, and institution counts. `/api/v1/tickers` would still return tickerless rows on top of real ones. The fixture-backfill template was explicitly rejected for prod for this reason.

## 5. Backfill approach — Option C (rollback), not a new backfill

The 2026-04-22 16:08 run recorded full `ingestion_impacts` (8,636 `flip_is_latest` + 8,636 `insert` rows, manifest_id=78902). [pipeline/base.py:614-656](scripts/pipeline/base.py:614) implements an LIFO rollback that handles this strategy end-to-end. Three checks passed:

1. **DELETE inserted rows.** [`_rollback_insert`](scripts/pipeline/base.py:658) for `append_is_latest` runs `DELETE FROM holdings_v2 WHERE cik=? AND quarter=? AND is_latest=TRUE` per insert impact. Applied to 8,636 keys, this removes the 3.2M tickerless rows from 2025Q4.
2. **Flip prior FALSE rows back to TRUE.** [`_rollback_flip`](scripts/pipeline/base.py:676) runs `UPDATE holdings_v2 SET is_latest=TRUE WHERE cik=? AND quarter=? AND is_latest=FALSE` per flip impact. LIFO ordering (inserts have higher `impact_id` than flips, processed first) ensures the 3.2M tickerless rows are deleted before the 3.2M enriched rows are restored — no ambiguity.
3. **Manifest status record.** [`rollback()`](scripts/pipeline/base.py:614) transitions `ingestion_manifest.fetch_status` from `'complete'` → `'rolled_back'` via the standard valid-transition table ([base.py:123](scripts/pipeline/base.py:123)). No separate manifest row is written; the status transition is the audit record.

No new backfill script is needed. A thin CLI wrapper exposes the rollback with safety flags matching repo conventions.

### Wrapper script — `scripts/rollback_run.py`

- Args: `--run-id` (required), `--db PATH` (default `data/13f.duckdb`), `--dry-run` (default), `--confirm`, `--i-understand-this-writes`, `--allow-prod`.
- `--dry-run`: opens read-only, prints manifest status, impact counts, and the pre-state `is_latest × ticker` matrix for the quarter. Never writes.
- `--confirm` without `--i-understand-this-writes` → ABORT.
- `--confirm --i-understand-this-writes` targeting a file named `13f.duckdb` without `--allow-prod` → ABORT.
- Idempotent: running against a manifest already in `'rolled_back'` status → clean NOOP, exit 0.

## 6. Staging proof

Staging at `data/13f_staging.duckdb` did not contain `holdings_v2` at session start (`sync_staging.py` only copies entity tables). Seeded the minimal slice needed to reproduce the prod state:

```python
# ATTACH prod read-only → copy into staging
CREATE TABLE holdings_v2 AS SELECT * FROM prod.holdings_v2
  WHERE quarter IN ('2025Q2','2025Q3','2025Q4');  # 12,483,690 rows
INSERT INTO ingestion_manifest
  SELECT * FROM prod.ingestion_manifest WHERE manifest_id IN (78901, 78902);
INSERT INTO ingestion_impacts
  SELECT * FROM prod.ingestion_impacts WHERE manifest_id = 78902;
CHECKPOINT;
```

Seed completed in 6.6s. 12,483,690 rows copied, 2 manifest rows, 17,272 impact rows.

### Dry-run on staging

```
$ python3 scripts/rollback_run.py \
    --run-id 13f_holdings_quarter=2025Q4_20260422_200854 \
    --db data/13f_staging.duckdb

  DB           : data/13f_staging.duckdb
  run_id       : 13f_holdings_quarter=2025Q4_20260422_200854
  source_type  : 13f_holdings
  manifest_id  : 78902
  fetch_status : complete
  mode         : dry-run
  impact summary:
    flip_is_latest            8,636
    insert                    8,636
  pre-state holdings_v2 quarter=2025Q4:
    is_latest=TRUE              :    3,205,868
    is_latest=TRUE & ticker NULL:    3,205,868
    is_latest=TRUE & ticker set :            0
    is_latest=FALSE             :    3,205,650
    total rows                  :    6,411,518
  DRY-RUN: no writes performed. Pass --confirm to execute.
```

### Confirm on staging

```
$ python3 scripts/rollback_run.py \
    --run-id 13f_holdings_quarter=2025Q4_20260422_200854 \
    --db data/13f_staging.duckdb \
    --confirm --i-understand-this-writes

  [... pre-state ...]
  executing pipeline.rollback('13f_holdings_quarter=2025Q4_20260422_200854') ...
  rollback complete.
  post status  : rolled_back
  post-state holdings_v2 quarter=2025Q4:
    is_latest=TRUE              :    3,205,650
    is_latest=TRUE & ticker NULL:      483,080
    is_latest=TRUE & ticker set :    2,722,570
    is_latest=FALSE             :            0
    total rows                  :    3,205,650
```

The post-state matches the Q3 pattern: zero `is_latest=FALSE` rows, ~15% legitimate `ticker IS NULL` (private issues / untickered CUSIPs), 84.9% ticker-populated. The 3.2M tickerless duplicates are gone.

### Safety-flag verification

```
$ python3 scripts/rollback_run.py --run-id ... --db data/13f.duckdb --confirm
  ABORT: --confirm without --i-understand-this-writes. ...

$ python3 scripts/rollback_run.py --run-id ... --db data/13f.duckdb --confirm --i-understand-this-writes
  ABORT: data/13f.duckdb resolves to the prod DB (13f.duckdb) but --allow-prod was not passed. ...
```

### Idempotency check

Re-running `--confirm --i-understand-this-writes` against the already-rolled-back staging manifest:

```
  fetch_status : rolled_back
  NOOP: run is already in 'rolled_back' status. Nothing to do.
```

## 7. Finding #2 resolution status

Plan hypothesis: Finding #2 (query1 crash at [queries.py:933](scripts/queries.py:933)) is a downstream symptom of Finding #1 — the tickerless 2025Q4 rows surface as N-PORT children with `institution=NULL` through the parent-rollup merge, and the `.lower()` call has no null guard.

**Confirmed.** Tested `queries.query1()` directly against post-rollback staging (worktree's queries.py does NOT have the null-guard fix applied — same code that crashed on prod):

```
[verify] app_db path in use: data/13f_staging.duckdb
[verify] query1('AAPL') -> OK (keys=['rows', 'all_totals', 'type_totals'])
    sizes: {'rows': 104, 'all_totals': 4, 'type_totals': 15}
[verify] query1('MSFT') -> OK (keys=['rows', 'all_totals', 'type_totals'])
    sizes: {'rows': 111, 'all_totals': 4, 'type_totals': 15}
```

No crash. Finding #2 is fully unblocked by the rollback. The defensive null-guard at queries.py:933 is independent hygiene; out of scope for this session per the plan's explicit scope lock.

### Auxiliary verification (raw SQL, post-rollback staging)

| Query | Rows |
|---|--:|
| `SELECT COUNT(DISTINCT ticker) FROM holdings_v2 WHERE is_latest=TRUE AND quarter='2025Q4' AND ticker IS NOT NULL` | 12,598 |
| `SELECT COUNT(*) FROM holdings_v2 WHERE ticker='AAPL' AND quarter='2025Q4' AND is_latest=TRUE` | 8,981 |
| `SELECT COUNT(*) FROM holdings_v2 WHERE ticker='MSFT' AND quarter='2025Q4' AND is_latest=TRUE` | 9,282 |

All three previously returned 0 on the broken prod state.

### pytest

```
$ pytest tests/ -x -q
267 passed, 1 warning in 45.40s
```

## 8. Prod execution plan — Terminal-only

After the PR is reviewed and merged by Serge, run from Terminal in the project root:

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership

# 1. Snapshot before touching prod (belt-and-braces; prod is already in backups/)
ls -lh data/13f.duckdb

# 2. Dry-run one last time against prod (read-only)
python3 scripts/rollback_run.py \
    --run-id 13f_holdings_quarter=2025Q4_20260422_200854

# 3. Execute. Three flags required: --confirm, --i-understand-this-writes, --allow-prod.
python3 scripts/rollback_run.py \
    --run-id 13f_holdings_quarter=2025Q4_20260422_200854 \
    --confirm --i-understand-this-writes --allow-prod

# 4. Verify the prod post-state matches the staging post-state from §6.
python3 -c "
import duckdb
con = duckdb.connect('data/13f.duckdb', read_only=True)
print(con.execute('''
    SELECT SUM(CASE WHEN is_latest THEN 1 ELSE 0 END),
           SUM(CASE WHEN is_latest AND ticker IS NULL THEN 1 ELSE 0 END),
           SUM(CASE WHEN NOT is_latest THEN 1 ELSE 0 END),
           COUNT(*)
    FROM holdings_v2 WHERE quarter = '2025Q4'
''').fetchone())
"
# Expect roughly: (3205650, 483080, 0, 3205650)
```

**Do not merge this PR or run step 3 in a Claude Code session.** Prod writes are Terminal-only.

## 9. Rollback plan — if the prod run goes wrong

The wrapper runs `pipeline.rollback(run_id)` which wraps DELETEs and UPDATEs across many rows outside a single transaction (the base class CHECKPOINTs at the end, not around the loop). If the run errors partway:

1. **Don't re-run the wrapper blindly.** The manifest status will still be `'complete'` (not yet flipped), but some impacts may already be reversed. Re-run would try to reverse them twice.
2. **Restore from snapshot.** `data/13f_readonly.duckdb` (2026-04-17 snapshot) pre-dates the problematic 2026-04-22 run and pre-dates Migration 015. It is a complete restore point but loses the Apr 17–21 ingestion. `data/backups/` contains more recent snapshots; pick the one closest before 2026-04-22 11:46 to preserve Migration 015 without the bad re-load.
3. Restore procedure:
   ```bash
   # Identify the best snapshot
   ls -lht data/backups/ | head -10
   # Copy it into place (DESTRUCTIVE — confirm first)
   cp data/backups/<snapshot> data/13f.duckdb
   ```
4. Open an incident note in `docs/INCIDENT_NOTES.md`, capture the partial-rollback state, and file a follow-up to rebuild the base-class rollback inside a single transaction (new followup, not yet filed).

If the run completes cleanly, no rollback of the rollback is required — the prod state will match the staging post-state.

## 10. Follow-ups filed

Two rows added to `docs/DEFERRED_FOLLOWUPS.md`:

- **int-23: load_13f_v2.py idempotency + enrichment sequencing.** Re-running the loader against an already-loaded quarter corrupts `is_latest` because ticker is populated by a separate downstream enrichment step the loader does not coordinate with. Two possible fixes to flag, not choose here: (a) promote refuses the flip when the new population has NULL on a column the displaced population had populated; (b) enrichment becomes atomic with load (part of the same `SourcePipeline` promote step). Priority: Medium. Not fixed in this PR.
- *(int-24 not filed — all three rollback checks passed; no base-class gap to capture.)*
