# int-01-p1 — Phase 1 implementation: RC1 whitelist patch + residual CUSIP re-queue

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 1; `docs/REMEDIATION_CHECKLIST.md` Batch 1-A). The RC1 code fix (US-preferred OpenFIGI selector) already shipped in `bcc5867`. Phase 0 (`docs/findings/int-01-p0-findings.md`, PR #13) found: 4 missing US exchCodes in the whitelist + 216 `cusip_classifications` rows still carry pre-fix foreign-exchange selections because they have not been re-queried since the fix landed.

Phase 1 scope: patch the whitelist, re-queue the 216 affected CUSIPs, and add a regression test. The data sweep (re-run retry script + promote) requires explicit authorization and is documented below but NOT executed by this session.

## Branch

`remediation/int-01-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/pipeline/cusip_classifier.py` — expand `US_PRICEABLE_EXCHCODES` from 11 → 15 codes (add UB, UC, UM, UT)
- `scripts/oneoff/int_01_requeue.py` (new) — one-shot script to re-queue 216 affected CUSIPs in `cusip_retry_queue`
- `tests/pipeline/test_openfigi_us_preferred.py` (new) — regression test for US-preferred selector

Read (verification only):
- `docs/findings/int-01-p0-findings.md` — the design spec
- `scripts/build_cusip.py` — confirm selector uses imported whitelist (no changes needed)
- `scripts/run_openfigi_retry.py` — confirm selector uses imported whitelist (no changes needed)
- `data/13f.duckdb` (read-only) — verify current affected row count

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. Whitelist expansion — `cusip_classifier.py:46-48`

Replace:
```python
US_PRICEABLE_EXCHCODES = frozenset({
    'US', 'UN', 'UW', 'UQ', 'UR', 'UA', 'UF', 'UP', 'UV', 'UD', 'UX',
})
```

With:
```python
US_PRICEABLE_EXCHCODES = frozenset({
    'US',                                              # composite
    'UA', 'UB', 'UC', 'UD', 'UF', 'UM', 'UN',
    'UP', 'UQ', 'UR', 'UT', 'UV', 'UW', 'UX',
})
```

4 new codes: UB (NASDAQ BX), UC (NYSE National/NSX), UM (NYSE Chicago/CHX), UT (Cboe EDGA). All US equity venues confirmed in findings §3.

### 2. Re-queue script — `scripts/oneoff/int_01_requeue.py`

One-shot script that:

1. Connects to the database (accept `--staging` flag; default prod read-write).
2. Identifies affected CUSIPs:
   ```sql
   SELECT cusip FROM cusip_classifications
   WHERE ticker IS NOT NULL
     AND canonical_type IN ('COM','ETF','PFD','ADR')
     AND ticker_source = 'openfigi'
     AND exchange IN ('GR','GF','GM','FF','GA','EU','EO','GY','GS')
   ```
3. For CUSIPs already in `cusip_retry_queue`: `UPDATE cusip_retry_queue SET status='pending', attempt_count=0, last_error=NULL WHERE cusip IN (...)`.
4. For CUSIPs not in the queue: `INSERT INTO cusip_retry_queue (cusip, status, attempt_count) VALUES (?, 'pending', 0)`.
5. Print summary: `Re-queued N CUSIPs (M updated, K inserted)`.
6. Support `--dry-run` flag that prints the count without writing.

This script is run once manually after merge. It does NOT run the retry — that is a separate step requiring authorization.

### 3. Regression test — `tests/pipeline/test_openfigi_us_preferred.py`

```python
from scripts.pipeline.cusip_classifier import US_PRICEABLE_EXCHCODES

def test_whitelist_contains_all_known_us_codes():
    """All 15 US exchCodes are in the whitelist."""
    expected = {'US','UA','UB','UC','UD','UF','UM','UN','UP','UQ','UR','UT','UV','UW','UX'}
    assert US_PRICEABLE_EXCHCODES == expected

def test_us_preferred_picks_uc_over_gr():
    data = [
        {'exchCode': 'GR', 'ticker': 'FOO1', 'compositeFIGI': 'BBG000A'},
        {'exchCode': 'UC', 'ticker': 'FOO',  'compositeFIGI': 'BBG000B'},
    ]
    preferred = next(
        (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
        None,
    )
    item = preferred or data[0]
    assert item['ticker'] == 'FOO'

def test_us_preferred_picks_ub_over_eo():
    data = [
        {'exchCode': 'EO', 'ticker': 'BAR1', 'compositeFIGI': 'BBG000C'},
        {'exchCode': 'UB', 'ticker': 'BAR',  'compositeFIGI': 'BBG000D'},
    ]
    preferred = next(
        (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
        None,
    )
    item = preferred or data[0]
    assert item['ticker'] == 'BAR'

def test_pure_foreign_falls_back_to_data0():
    data = [
        {'exchCode': 'GR', 'ticker': 'XFOO', 'compositeFIGI': 'BBG000E'},
        {'exchCode': 'GF', 'ticker': 'XFOO1', 'compositeFIGI': 'BBG000F'},
    ]
    preferred = next(
        (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
        None,
    )
    item = preferred or data[0]
    assert item['exchCode'] == 'GR'  # data[0] fallback

def test_empty_data_returns_none():
    data = []
    preferred = next(
        (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
        None,
    ) if data else None
    assert preferred is None
```

### 4. Verification

- Pre-commit (ruff + pylint + bandit) clean on all modified files.
- All existing tests pass (`pytest tests/`).
- New tests pass.
- `make smoke` or equivalent passes.
- Read-only verification: confirm affected CUSIP count matches findings (expect ~216 in cc).

### 5. Post-merge data sweep (NOT executed by this session)

After merge, the operator runs these steps manually with authorization:

```bash
# Step 1: Re-queue affected CUSIPs
python3 scripts/oneoff/int_01_requeue.py --dry-run   # verify count
python3 scripts/oneoff/int_01_requeue.py              # execute

# Step 2: Run retry against staging (REQUIRES AUTHORIZATION)
python3 scripts/run_openfigi_retry.py --staging

# Step 3: Propagate cc → securities
python3 scripts/build_cusip.py --staging --skip-openfigi

# Step 4: Verify acceptance criteria
# cc foreign-exchange count < 50
# securities foreign-exchange count < 50
# Zero new openfigi_status='error' rows

# Step 5: Promote staging → prod (REQUIRES AUTHORIZATION)
```

## Out of scope

- Running the retry script (requires explicit authorization per fetch protocol).
- Promoting staging → prod.
- int-02 (RC2 mode aggregator) — separate item.
- int-03 (RC3 override triage) — separate item.
- int-06 (Pass C forward-hook) — separate item.
- Doc updates to REMEDIATION_CHECKLIST / ROADMAP / SESSION_LOG (batched per doc discipline).

## Rollback

Revert the commit. The whitelist reverts to 11 codes. The re-queue script under `oneoff/` is inert (no callers). Tests removed. No schema change, no migration.

## Hard stop

Do NOT merge. Push to `origin/remediation/int-01-p1` after each logical commit. Open a PR via `gh pr create` with title `remediation/int-01-p1: RC1 whitelist expansion + CUSIP re-queue script`. Wait for CI green. Report PR URL + CI status. Do NOT merge.
