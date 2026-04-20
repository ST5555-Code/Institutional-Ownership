# int-01-p0 — Phase 0 investigation: RC1 OpenFIGI foreign-exchange ticker filter

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 1; `docs/REMEDIATION_CHECKLIST.md` Batch 1-A). Item int-01 is the first root-cause fix from BLOCK-SECURITIES-DATA-AUDIT: the OpenFIGI lookup path currently selects `data[0]` without preferring a US-priceable exchange, producing ~382 wrong-exchange rows in `cusip_classifications` and ~442 in `securities`.

Phase 0 of this prompt is investigation only: confirm the ~442-row impact is current, inventory the two call sites in depth, draft the US-preferred sweep + fallback logic, and write a findings doc that Phase 1 will execute. **No code writes, no DB writes.**

## Branch

`remediation/int-01-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/build_cusip.py` — RC1 call-site #1 at `:207`
- `scripts/run_openfigi_retry.py` — RC1 call-site #2 at `:254`
- `scripts/pipeline/cusip_classifier.py` — upstream consumer; check MAX(issuer_name_sample) interaction for cross-item awareness (item int-02)
- `data/13f.duckdb` (read-only) — confirm row impact
- `docs/BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md` — existing Phase 0 finding to extend

Write:
- `docs/findings/int-01-p0-findings.md` — new findings doc (this session's deliverable)

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.** This list matches Appendix D of `docs/REMEDIATION_PLAN.md`.

## Scope

1. Reproduce the 382 / 442 row counts from `BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md §4.1` against current prod state. If numbers have drifted (Phase 3 promote landed post-finding), capture the current state.

2. For both RC1 call sites, record:
   - Exact line numbers of the `data[0]` selection.
   - Call graph: who invokes this function; how many rows feed each site per run.
   - Pure-foreign-CUSIP fallback rate (rows where no US exchange is available).

3. Confirm the proposed fix shape (from `BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md §4.1` code snippet):
   - US-priceable exchange whitelist (CL, US composite, etc.)
   - Sweep: prefer first match in whitelist; fallback to `data[0]` only if no US match.
   - Verify the whitelist is accurate against 10 sample OpenFIGI responses.

4. List any cross-item dependencies:
   - int-02 (RC2) needs RC1-fixed data to measure true RC2 impact.
   - int-03 (RC3) uses OpenFIGI US-preferred as gold-standard — depends on int-01.
   - int-06 (ticker Pass C forward-hook) runs `build_cusip.py` at end; must not regress on RC1 fix.

5. Scope the Phase 1 implementation:
   - Exact code diff (two call sites).
   - Test plan — regression fixtures with known foreign-exchange rows.
   - Acceptance criteria — post-fix row counts.

## Out of scope

- Any code writes.
- Any DB writes.
- RC2 (int-02) or RC3 (int-03) fixes.
- Pass C forward-hook implementation (int-06).

## Deliverable

`docs/findings/int-01-p0-findings.md` following the structure of existing Phase 0 findings docs (see `docs/BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md` §4 for shape). Cite file:line for every claim.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/int-01-p0: Phase 0 findings — RC1 OpenFIGI foreign-exchange filter`. Report PR URL and CI status. Wait for Serge review before any Phase 1 work.
