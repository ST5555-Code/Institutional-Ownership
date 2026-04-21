# int-10-p0 — Phase 0 findings: INF26 OpenFIGI `_update_error()` permanent-pending bug

_Prepared: 2026-04-21 — branch `int-10-p0` off main HEAD `fa01c7e`._

_Tracker: [docs/REMEDIATION_PLAN.md](../REMEDIATION_PLAN.md) row `int-10` (INF26). Upstream finding: `_update_error()` in [scripts/run_openfigi_retry.py](../../scripts/run_openfigi_retry.py) never flips the retry-queue status to a terminal state when a CUSIP exhausts retries via HTTP errors._

Phase 0 is investigation only. No code writes, no DB writes. Deliverables: this document + Phase 1 scope.

**Headline.** `_update_error()` bumps `attempt_count` but never touches `status`, so rows repeatedly hitting HTTP errors land in a silent terminal state of `status='pending' AND attempt_count >= MAX_ATTEMPTS`. The retry loop's `WHERE status='pending' AND attempt_count < MAX_ATTEMPTS` filter then permanently skips them — not an infinite loop, but **permanent-pending**: they are neither retried nor marked `unmappable`, so dashboards/gates treating "pending" as work-in-progress never resolve. Staging currently holds **81 such rows** at `attempt_count=3`. Prod has 0 today (the last retry run reached all 216 remaining CUSIPs at `attempt_count=0`, so the bug has not yet manifested there). The fix is a 2–3 line change mirroring the CASE expression already used in `_update_no_match()`. A one-off sweep is needed on staging only; prod is clean.

---

## §1. `_update_error()` current behavior

[scripts/run_openfigi_retry.py:189-212](../../scripts/run_openfigi_retry.py:189):

```python
def _update_error(con, cusip: str, reason: str) -> None:
    """Hard HTTP error — bump attempts, leave status='pending'."""
    con.execute(
        """
        UPDATE cusip_classifications
        SET openfigi_status       = 'error',
            openfigi_attempts     = openfigi_attempts + 1,
            last_openfigi_attempt = NOW(),
            updated_at            = NOW()
        WHERE cusip = ?
        """,
        [cusip],
    )
    con.execute(
        """
        UPDATE cusip_retry_queue
        SET attempt_count  = attempt_count + 1,
            last_attempted = NOW(),
            last_error     = ?,
            updated_at     = NOW()
        WHERE cusip = ?
        """,
        [reason, cusip],
    )
```

The second UPDATE (on `cusip_retry_queue`) sets `attempt_count`, `last_attempted`, `last_error`, `updated_at` — but **not `status`**. The column's default is `'pending'`, so rows stay `pending` regardless of how many times they error out.

The docstring on line 190 documents this as intentional ("leave status='pending'"), but that contract is incompatible with the retry loop's selector (§2), which treats `attempt_count >= MAX_ATTEMPTS` as "stop processing." The net effect is permanent-pending.

### Contrast — `_update_no_match()` already does this correctly

[scripts/run_openfigi_retry.py:159-186](../../scripts/run_openfigi_retry.py:159):

```python
UPDATE cusip_retry_queue
SET attempt_count  = attempt_count + 1,
    last_attempted = NOW(),
    last_error     = ?,
    status         = CASE
        WHEN attempt_count + 1 >= ? THEN 'unmappable'
        ELSE 'pending'
    END,
    updated_at     = NOW()
WHERE cusip = ?
```

The CASE expression flips to `'unmappable'` at the attempt limit. `_update_error()` is missing exactly this three-line CASE.

---

## §2. MAX_ATTEMPTS and retry-loop selector

[scripts/pipeline/cusip_classifier.py:31](../../scripts/pipeline/cusip_classifier.py:31):

```python
MAX_ATTEMPTS = 3  # OpenFIGI retry limit before marking unmappable
```

Imported in [scripts/run_openfigi_retry.py:44-48](../../scripts/run_openfigi_retry.py:44). Selector in `run_retry()` at [scripts/run_openfigi_retry.py:217-224](../../scripts/run_openfigi_retry.py:217):

```sql
SELECT cusip, issuer_name, canonical_type
FROM cusip_retry_queue
WHERE status = 'pending'
  AND attempt_count < 3
ORDER BY attempt_count ASC, first_attempted ASC
```

So a row with `status='pending' AND attempt_count=3` is skipped forever — never retried, never reconciled.

---

## §3. Data state (read-only)

### §3.1 Prod — `data/13f.duckdb`

| status | rows |
|---|---|
| unmappable | 22,118 |
| resolved | 15,595 |
| pending | 216 |
| **permanent-pending (`pending AND attempt_count >= 3`)** | **0** |

All 216 `pending` rows are at `attempt_count = 0` — never attempted. Prod has not yet triggered the bug because the last retry run cleared the error path. The bug is latent, not active, in prod.

### §3.2 Staging — `data/13f_staging.duckdb`

| status | rows |
|---|---|
| unmappable | 24,379 |
| resolved | 16,285 |
| pending | 81 |
| **permanent-pending (`pending AND attempt_count >= 3`)** | **81** |

**All 81 staging `pending` rows are at `attempt_count = 3`.** These are concrete, reproducible evidence of INF26: HTTP errors during a prior staging retry run exhausted the attempt budget without transitioning to a terminal state.

Schema confirmed via `DESCRIBE cusip_retry_queue`: `status VARCHAR NOT NULL DEFAULT 'pending'`, `attempt_count INTEGER NOT NULL DEFAULT 0`. No `status='error'` rows exist in either DB (status never transitions to 'error' — the string 'error' only lives in `cusip_classifications.openfigi_status`).

---

## §4. Proposed fix (Phase 1)

### §4.1 Code change — mirror `_update_no_match()`

In [scripts/run_openfigi_retry.py:_update_error()](../../scripts/run_openfigi_retry.py:189), extend the retry-queue UPDATE with the same CASE expression and `MAX_ATTEMPTS` parameter:

```python
con.execute(
    """
    UPDATE cusip_retry_queue
    SET attempt_count  = attempt_count + 1,
        last_attempted = NOW(),
        last_error     = ?,
        status         = CASE
            WHEN attempt_count + 1 >= ? THEN 'unmappable'
            ELSE 'pending'
        END,
        updated_at     = NOW()
    WHERE cusip = ?
    """,
    [reason, MAX_ATTEMPTS, cusip],
)
```

Three-line change: add the `status = CASE ... END` clause and thread `MAX_ATTEMPTS` into the parameter tuple. Update the docstring on line 190 to reflect the new terminal-transition behavior.

### §4.2 Semantic note — HTTP errors vs no-match

Marking HTTP-exhausted rows `unmappable` conflates network/transport failure with "OpenFIGI has no record." An alternative would be a distinct terminal status (e.g. `'error_exhausted'`). Recommend sticking with `'unmappable'` for Phase 1 because:

- The retry loop already treats both classes equivalently (skip once non-pending).
- Downstream gates and dashboards only know two terminal states (`resolved`, `unmappable`).
- `last_error` preserves the HTTP cause for forensics.

Flag this for Phase 1 review; if the team prefers a distinct status, the diff is still ~3 lines but touches `cusip_classifications.openfigi_status` semantics too.

### §4.3 One-off sweep for existing stuck rows

**Prod: not needed** (0 permanent-pending rows).

**Staging: 81 rows.** Phase 2 should ship a one-shot UPDATE alongside the code fix:

```sql
UPDATE cusip_retry_queue
SET status     = 'unmappable',
    updated_at = NOW(),
    notes      = COALESCE(notes || ' | ', '') ||
                 'int-10 sweep: http-error exhausted MAX_ATTEMPTS'
WHERE status = 'pending' AND attempt_count >= 3;
```

Run against `data/13f_staging.duckdb` only. Prod path: a safety-check invocation that asserts row count = 0 before exiting cleanly (idempotent; catches any future drift).

### §4.4 Does the fix distinguish first-attempt pending from exhausted retries?

No — and it doesn't need to. The `attempt_count` column already carries that signal. Genuinely-pending-first-attempt = `attempt_count < MAX_ATTEMPTS AND status='pending'`. Exhausted = terminal (`resolved` or `unmappable`) post-fix. The retry-loop selector at line 220 already encodes the correct semantic.

---

## §5. Phase 1 file list

- `scripts/run_openfigi_retry.py` — `_update_error()` body (~3 lines + docstring).
- `docs/REMEDIATION_PLAN.md` — flip `int-10` row to "OPEN (Phase 0 done)".
- `docs/REMEDIATION_CHECKLIST.md` — tick Phase 0 box for int-10.
- (Phase 2) `scripts/sweep_int10_permanent_pending.py` — one-off SQL sweep against staging; idempotent no-op against prod.

No migration required; no schema change.

---

## §6. Risk notes

1. **Staging sweep is destructive by design** (flips 81 rows from `pending` → `unmappable`). Wrap in a dry-run flag mirroring `run_openfigi_retry.py --dry-run`. Print per-row diff before commit.
2. **No prod data loss** — prod has zero permanent-pending rows. The sweep script should still be run against prod, but it must be a no-op (assert COUNT = 0).
3. **Semantics**: calling an HTTP-error-exhausted row `unmappable` is a slight overload of the term. Mitigation: `last_error` column preserves the HTTP cause; `notes` annotation from the sweep documents the transition origin. If the team later adds a distinct `error_exhausted` state, it's a one-line enum change plus dashboard update.
4. **Future drift**: `_update_error()` and `_update_no_match()` should share a single helper or constant for the terminal-transition CASE. Not required for Phase 1, but flagged as cleanup to prevent a third `_update_*` function from repeating the divergence.
5. **Rate limiting**: unrelated to this bug, but `RATE_LIMIT_SLEEP = 2.4` + `RETRY_SLEEP_429 = 62` already provide some backpressure. The bug is not caused by aggressive retries; it's caused by missing terminal-state logic.

---

## §7. What Phase 0 did not touch

- No code edits to `scripts/run_openfigi_retry.py` or any production file.
- No DB writes; all queries run with `read_only=True`.
- No run of `run_openfigi_retry.py`.
- No changes to `REMEDIATION_PLAN.md` / `REMEDIATION_CHECKLIST.md` — deferred to Phase 1 per workflow convention.
