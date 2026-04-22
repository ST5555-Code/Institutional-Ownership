# obs-07-p0 — Phase 0 findings: N-PORT `report_month` future-leakage gate

_Prepared: 2026-04-21 — branch `obs-07-p0` off `main` HEAD `21c6dc2`._

_Tracker: SYSTEM_AUDIT MINOR-4 (P-07). Defensive completeness gate: reject promotes whose staged `report_month` is in the future relative to the run clock, so a typo in a filing period or a fetcher bug cannot leak forward-dated rows into prod `fund_holdings_v2`._

Phase 0 is investigation only. No code writes and no DB writes were performed. Prod DB (`data/13f.duckdb`, 14.5 GB) and staging DB (`data/13f_staging.duckdb`, 4.7 GB) were read through `duckdb.connect(..., read_only=True)`.

---

## §1. TL;DR

Today there is **no future-dated `report_month` leakage in either DB** — max in both prod and staging is `'2026-03'` vs. current month `'2026-04'`. The gate is pre-emptive, not a fix for observed contamination.

Proposed Phase 1 change: add one pre-flight assertion in [scripts/promote_nport.py](scripts/promote_nport.py) that inspects staged `report_month` values for the run and aborts with a clear message if any month is strictly greater than the current calendar month. The check runs **before** `BEGIN TRANSACTION` so no rollback machinery is needed. Estimated diff: ~25 LOC + one unit test.

---

## §2. Current state of `promote_nport.py`

### §2.1 File anatomy (459 lines total)

| Section | Lines | Purpose |
|---|---|---|
| Module docstring + policy header | 1–42 | Documents checkpoint / transaction boundary, step list, amendment handling |
| Imports + constants | 43–60 | `BASE_DIR`, `REPORTS_DIR` |
| `_read_validation_report` | 63–70 | Loads `logs/reports/nport_{run_id}.md` |
| `_assert_promote_ok` | 73–79 | Rejects if report does not say `Promote-ready: YES` |
| `_bulk_enrich_run` (Group 2 entity enrichment) | 86–151 | Bulk UPDATE…FROM JOIN for entity columns |
| `_staged_tuples` | 158–170 | `SELECT DISTINCT (series_id, report_month)` for run |
| `_STAGED_COLS` constant | 177–184 | 21-col projection from `stg_nport_holdings` |
| `_promote_batch` | 187–270 | DELETE + INSERT into `fund_holdings_v2` |
| `_upsert_universe` | 273–316 | DELETE + INSERT into `fund_universe` |
| `main` | 323–454 | Entry point, transaction, CHECKPOINT, snapshot |

### §2.2 Existing validations (before any write to prod)

| Check | Location | What it guards |
|---|---|---|
| Validation report exists on disk | [promote_nport.py:63-70](scripts/promote_nport.py:63) | Refuses to promote if `validate_nport.py` has not run |
| Report body says `Promote-ready: YES` | [promote_nport.py:73-79](scripts/promote_nport.py:73) | Refuses if validation tier is `BLOCK` or entity-gate blocked |
| `ingestion_manifest` table exists in prod | [promote_nport.py:350-354](scripts/promote_nport.py:350) | Refuses if migration 001 not applied |
| At least one manifest row for run | [promote_nport.py:367-370](scripts/promote_nport.py:367) | ROLLBACK + early return if run produced no manifest rows |

**No temporal validation exists today.** A row staged with `report_month='2099-12'` would promote successfully, contaminate `fund_holdings_v2`, and survive into the `13f_readonly` snapshot.

### §2.3 Where `report_month` flows through promote

| Line | Use |
|---|---|
| [promote_nport.py:162](scripts/promote_nport.py:162) | `SELECT DISTINCT s.series_id, s.report_month FROM stg_nport_holdings` — canonical source of the promote scope |
| [promote_nport.py:179](scripts/promote_nport.py:179) | Listed in `_STAGED_COLS` (carried across verbatim) |
| [promote_nport.py:213-249](scripts/promote_nport.py:213) | `(series_id, report_month)` is the DELETE key in `fund_holdings_v2` and the JOIN key for the INSERT |
| [promote_nport.py:396-399](scripts/promote_nport.py:396) | Packed into `unit_key_json` for `ingestion_impacts.promote_status` UPDATE |

The gate should read from `stg_nport_holdings` scoped to the run's manifests — the same source `_staged_tuples` uses — so the check sees exactly the rows that are about to move.

### §2.4 DB connection pattern

```python
# promote_nport.py:346-347
staging_con = duckdb.connect(STAGING_DB, read_only=True)
prod_con    = duckdb.connect(PROD_DB)
```

Transaction boundary: [promote_nport.py:362-433](scripts/promote_nport.py:362) — `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK` wraps manifest mirror, DELETE+INSERT, bulk enrich, universe upsert, and impacts status UPDATE. `CHECKPOINT` runs **after** COMMIT ([promote_nport.py:445](scripts/promote_nport.py:445)) because DuckDB forbids CHECKPOINT inside a transaction.

---

## §3. Data reality — `report_month` today

### §3.1 Storage format

```
typeof(report_month) = VARCHAR
format               = 'YYYY-MM'  (e.g. '2026-03')
width                = 7 chars, stable → lexicographic compare is monotonic
```

### §3.2 Prod `fund_holdings_v2` distribution (read-only)

```
MIN(report_month) = '2022-06'
MAX(report_month) = '2026-03'
DISTINCT months   = 35
rows with report_month > '2026-04-21' (today) = 0
Top 10 DESC: 2026-03, 2026-02, 2026-01, 2025-12, 2025-11, 2025-10,
             2025-09, 2025-08, 2025-07, 2025-06
```

### §3.3 Staging `stg_nport_holdings` distribution (read-only)

```
MIN(report_month) = '2022-06'
MAX(report_month) = '2026-03'
staging rows with report_month >= '2026-04' = 0
total staging rows = 11,107,972
```

**Neither DB contains a future-dated `report_month` as of 2026-04-21.** The gate is preventive. It costs one aggregation query per run and, in the current baseline, will never fire — which is the point.

---

## §4. Proposed gate design

### §4.1 Where to insert

Insert as a **pre-flight check** immediately after `_assert_promote_ok` and **before** `duckdb.connect(PROD_DB)` / `BEGIN TRANSACTION` — matching the shape of the existing two assertions.

```python
# promote_nport.py — new function, called from main() after _assert_promote_ok
def _assert_no_future_report_month(staging_con, run_id: str) -> None:
    """Abort if any staged row for this run has report_month > current month.

    N-PORT-P reports period-end holdings at monthly grain. A report_month
    strictly greater than the current calendar month cannot be a legitimate
    period-end filing — it is either a typo in the filing, a date-parse bug
    in the fetcher, or corruption. Aborting the promote preserves the
    invariant that fund_holdings_v2.report_month <= today's calendar month.
    """
    # Compare VARCHAR lexicographically — YYYY-MM is fixed-width and sorts monotonically.
    offenders = staging_con.execute(
        """
        SELECT s.series_id, s.report_month, COUNT(*) AS rows
          FROM stg_nport_holdings s
          JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
         WHERE m.run_id = ?
           AND s.report_month > strftime(CURRENT_DATE, '%Y-%m')
         GROUP BY 1, 2
         ORDER BY 2 DESC, 1
         LIMIT 20
        """,
        [run_id],
    ).fetchall()
    if offenders:
        lines = [f"  {sid}  {rm}  ({n:,} rows)" for sid, rm, n in offenders]
        raise SystemExit(
            "obs-07 gate FAIL — staged report_month in the future:\n"
            + "\n".join(lines)
            + f"\n\nRun {run_id} has staged rows with report_month > "
            + "current calendar month. Investigate filings for typos "
            + "(common: YYYY swapped 2025→2052, 2026→2062) before promoting."
        )
```

Call site in `main()`:

```python
# after:  _assert_promote_ok(report_text)
# before: staging_con = duckdb.connect(STAGING_DB, read_only=True)

staging_con = duckdb.connect(STAGING_DB, read_only=True)
prod_con = duckdb.connect(PROD_DB)
try:
    _assert_no_future_report_month(staging_con, args.run_id)   # NEW
    try:
        prod_con.execute("SELECT 1 FROM ingestion_manifest LIMIT 1")
    ...
```

Placing the gate **after** the staging connection opens but **before** any prod write keeps the diff small and reuses the existing `staging_con`. The check is pure SELECT against staging — no rollback needed because no write has happened yet.

### §4.2 Threshold rationale

**Recommended: `report_month > strftime(CURRENT_DATE, '%Y-%m')`** — reject anything strictly greater than the current calendar month. Allow the current month itself.

| Threshold | Behaviour | Verdict |
|---|---|---|
| `report_month > CURRENT_DATE` | Treats VARCHAR 'YYYY-MM' against a DATE — mismatched types, DuckDB casts month to first-of-month implicitly but the semantics are muddled | Reject |
| `report_month > strftime(CURRENT_DATE, '%Y-%m')` ✅ | Lexicographic compare on two fixed-width YYYY-MM strings. Catches 2062-03 typos. Allows `'2026-04'` today. | **Recommended** |
| `report_month >= strftime(CURRENT_DATE, '%Y-%m')` | Also blocks current incomplete month. Safer, but creates false positives on mid-month amendments that legitimately report the current period. | Consider for Phase 2 |
| `report_month > strftime(CURRENT_DATE + INTERVAL '1 month', '%Y-%m')` | Very permissive — allows one month of slack. Useful if SEC ever ingests early-period filings. | Too loose for a completeness gate |

The "equal to current month" case is rare but not impossible — a fund could file an N-PORT-P amendment that lists the current month as period end on the last day of that month. The stricter `>=` variant would block it. Recommend starting with strict-greater-than (`>`); tighten later if we want even more defence.

### §4.3 Failure mode

**Hard abort via `SystemExit`** — consistent with `_assert_promote_ok` ([promote_nport.py:73-79](scripts/promote_nport.py:73)). The message lists up to 20 offending `(series_id, report_month, row_count)` triples so the operator can grep the staging table and find the root cause filing.

No `--allow-future-report-month` escape hatch in Phase 1. If legitimate future-dated filings ever need to pass through (unlikely given N-PORT semantics), add the flag in a later ticket. A hard gate is the right default for a preventive completeness check.

### §4.4 Staging-only vs post-promote assertion

**Staging-only.** If the gate passes on staging and `_promote_batch` is a faithful INSERT from staging (it is — see [promote_nport.py:240-266](scripts/promote_nport.py:240)), prod cannot end up with a future `report_month`. A post-promote SELECT would add a round-trip for no information gain unless we mistrust `_promote_batch`.

A minimal post-COMMIT assertion (`SELECT COUNT(*) FROM fund_holdings_v2 WHERE report_month > strftime(CURRENT_DATE, '%Y-%m')` for the run's series scope) could be added as belt-and-braces, but out of scope for P0 — flagging as an optional Phase 2 enhancement.

---

## §5. Phase 1 scope and file list

### §5.1 Files to touch

| File | Change | LOC (est.) |
|---|---|---|
| [scripts/promote_nport.py](scripts/promote_nport.py) | Add `_assert_no_future_report_month(staging_con, run_id)`. Call from `main()` after `_assert_promote_ok`. Update module docstring step list. | +25 / -0 |
| [tests/test_promote_nport.py](tests/test_promote_nport.py) (new or existing — TBD) | Unit test: stage a row with `report_month='2099-01'`, assert `SystemExit` with "obs-07 gate FAIL" substring; a control test with valid months passes cleanly. | +40 / -0 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Move obs-07 from active → COMPLETED with 2026-04-21 and PR link. | +1 / -1 |

Migration files, CI config, and other pipelines are untouched. No DB schema change.

### §5.2 Out of scope for Phase 1

- Adding the same gate to `validate_nport.py` (earlier surfacing in the report). Candidate for Phase 2 if operators want the signal before promote-time.
- Adding the gate to `fetch_nport_v2.py` (catch at ingest). Candidate for Phase 2.
- Belt-and-braces post-COMMIT assertion (see §4.4).
- A `--allow-future-report-month` override flag.
- Retroactive scrub of prod for future months — not needed, current max is `'2026-03'` ≤ current month.

---

## §6. Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Clock skew on the host running promote causes the gate to fire on a legitimate filing at month rollover | Low — staging runs are operator-driven, not wall-clock-triggered | Operator re-runs once clock is correct; error message names the threshold so the cause is obvious |
| R2 | VARCHAR lexicographic compare breaks if `report_month` ever widens beyond `YYYY-MM` | Very low — format is enforced upstream in `fetch_nport_v2.py` | Unit test asserts format at the gate; Phase 2 could tighten to explicit DATE cast if format changes |
| R3 | Gate aborts a genuine same-month amendment filed on the last day of the period | Low — strict `>` allows current month; only blocks strictly future | If observed in practice, tighten or relax per §4.2 table |
| R4 | Gate runs after `_assert_promote_ok` but before staging connection opens — if the check is placed wrong, staging_con is None | N/A — design §4.1 puts the call **after** the connect, before any prod write | Covered by code review in Phase 1 |

---

## §7. Source citations

- Prod and staging values queried live on 2026-04-21 via `duckdb.connect(..., read_only=True)`. Exact queries in §3.2 and §3.3.
- Line references to `promote_nport.py` are against worktree HEAD `21c6dc2` (same as `main`).
- Current-month semantics: Python `datetime.date.today().strftime('%Y-%m')` on 2026-04-21 = `'2026-04'`; DuckDB `strftime(CURRENT_DATE, '%Y-%m')` returns the same string.

_End of obs-07-p0 Phase 0 findings._
