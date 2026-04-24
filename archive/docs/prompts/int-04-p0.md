# int-04-p0 — Phase 0 investigation: RC4 issuer_name propagation scope guard

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 1; `docs/REMEDIATION_CHECKLIST.md` Batch 1-A). Item int-04 is BLOCK-SEC-AUD-4 (RC4): `normalize_securities.py` propagates `issuer_name` from `cusip_classifications` to `securities`, but the scope guard (which rows to update, which to skip) has not been audited since the universe expansion from 132K → 430K rows.

int-01 (RC1 whitelist expansion) is merged. int-02 (RC2 mode aggregator) code already shipped in `fc2bbbc` per int-01-p0 findings §4. This investigation determines whether `normalize_securities.py` has any remaining scope issues or whether RC4 is already clean.

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/int-04-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/normalize_securities.py` — the propagation script: `update_securities_from_classifications` function, scope filters, column mapping
- `scripts/pipeline/cusip_classifier.py` — upstream source of `issuer_name` in `cusip_classifications`
- `scripts/build_cusip.py` — calls `normalize_securities` at end; check invocation pattern
- `docs/BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md` — RC4 original finding
- `data/13f.duckdb` (read-only) — measure current `securities.issuer_name` vs `cusip_classifications.issuer_name` divergence

Write:
- `docs/findings/int-04-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Trace the propagation flow:**
   - What does `normalize_securities.py` do? Which columns does it propagate from `cusip_classifications` to `securities`?
   - What is the scope guard (WHERE clause)? Does it update all rows, only NULLs, only changed values?
   - How is it invoked? (standalone script, called from `build_cusip.py` end-of-run, admin UI?)

2. **Measure current divergence:**
   - `SELECT COUNT(*) FROM securities s JOIN cusip_classifications cc ON s.cusip = cc.cusip WHERE s.issuer_name != cc.issuer_name` — how many rows diverge?
   - Breakdown by cause: NULL vs non-NULL, pre-expansion vs post-expansion CUSIPs.
   - Is the divergence growing or stable?

3. **Assess whether RC4 is already fixed:**
   - Check git history for any recent fixes to `normalize_securities.py`.
   - If the fix already shipped (like RC1/RC2), document what remains (data sweep? acceptance test?).

4. **Cross-item awareness:**
   - int-01 (RC1) — merged. Whitelist expansion may change which CUSIPs have tickers, affecting the propagation scope.
   - int-02 (RC2) — code shipped. Mode aggregator may have changed `issuer_name` values in `cusip_classifications`.
   - int-05 (Pass C sweep) — depends on int-04 scope guard being correct before triggering a mass propagation.
   - int-06 (forward hooks) — adds auto-trigger of normalize_securities at end of `build_cusip.py`. Depends on int-04.

5. **Phase 1 scope:**
   - If code changes needed: what and where.
   - If only a data sweep: document the steps.
   - Test plan and acceptance criteria.

## Out of scope

- Code writes.
- DB writes.
- int-05 (Pass C sweep).
- int-06 (forward hooks).
- int-02 (RC2 — already shipped).

## Deliverable

`docs/findings/int-04-p0-findings.md` structured like prior findings docs. Cite file:line.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/int-04-p0: Phase 0 findings — RC4 issuer_name propagation scope guard`. Report PR URL + CI status.
