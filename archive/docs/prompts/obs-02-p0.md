# obs-02-p0 — Phase 0 investigation: ADV freshness + log discipline

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 2; `docs/REMEDIATION_CHECKLIST.md` Batch 2-B). Audit item MAJOR-12 (P-02): `fetch_adv.py` has no structured logging and its `data_freshness` stamp for `adv_managers` is not landing in prod (the hook was added in `831e5b4` but the script has not been re-run against prod since).

obs-01-p1 (manifest registration for ADV) is merged — `fetch_adv.py` now writes `ingestion_manifest` + `ingestion_impacts`. This investigation assesses what remains for the freshness + logging gaps.

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/obs-02-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/fetch_adv.py` — current freshness stamp, logging, the obs-01-p1 manifest additions
- `scripts/pipeline/shared.py` — `stamp_freshness` wrapper
- `scripts/db.py` — `record_freshness` function
- `data/13f.duckdb` (read-only) — check `data_freshness` for `adv_managers` row
- `scripts/fetch_market.py` — reference implementation for structured logging + freshness
- `scripts/fetch_ncen.py` — reference for obs-01-p1 pattern

Write:
- `docs/findings/obs-02-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Freshness gap:** Is `data_freshness` for `adv_managers` present in prod? If not, why not (script not re-run? stamp call missing? wrong table name)?

2. **Logging audit:** Does `fetch_adv.py` use structured logging (Python `logging` module) or just `print()`? What log file does it write to? Is there a per-run log rotation?

3. **obs-01-p1 interaction:** Review the manifest additions from obs-01-p1. Does the `record_freshness` call now fire correctly after manifest registration? Any ordering issue?

4. **Cross-item awareness:**
   - mig-02 (fetch_adv.py DROP+CREATE atomicity) — serial with obs-02 on same file.
   - obs-01 (merged) — manifest wiring is done.

5. **Phase 1 scope:** What changes to close the freshness + logging gaps?

## Out of scope

- Code writes. DB writes. mig-02 (separate item, serial).

## Deliverable

`docs/findings/obs-02-p0-findings.md` with freshness status, logging audit, Phase 1 scope.

## Hard stop

Do NOT merge. Open PR with title `remediation/obs-02-p0: Phase 0 findings — ADV freshness + log discipline`. Report PR URL + CI status.
