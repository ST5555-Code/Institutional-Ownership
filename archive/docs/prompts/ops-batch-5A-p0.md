# ops-batch-5A-p0 — Phase 0 investigation: doc-hygiene sweep (Batch 5-A subset)

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 5; `docs/REMEDIATION_CHECKLIST.md` Batch 5-A). A cluster of audit MINOR items flagged doc drift: `README.md` promotes retired `update.py`; project tree omits current layout; `PHASE3_PROMPT.md` instructs retired `fetch_nport.py`; `ARCHITECTURE_REVIEW.md` says React Phase 4 pending while `REACT_MIGRATION.md:120` says complete; `README_deploy.md` missing React build prereq; `CLASSIFICATION_METHODOLOGY.md` cites 20,205 entities vs current prod 26,535; `ROADMAP.md` minor count drifts (928 vs 931, 4 vs 5).

This Phase 0 prompt bundles the disjoint-file subset of Batch 5-A so a single worker can land all fact-check edits in one low-risk doc commit. Items ops-10 + ops-11 share `ROADMAP.md` so they must be done serially within this batch — this prompt handles both in the correct order (ops-10 first, then ops-11).

**No code writes, no DB writes.** Read prod DuckDB for verification counts only.

## Branch

`remediation/ops-batch-5A-p0` off main HEAD.

## Files this session will touch

Read:
- `data/13f.duckdb` (read-only) — verify current entity count + 13DG exclusion count + NULL-CIK override count
- `docs/SYSTEM_AUDIT_2026_04_17.md` §7.1 + §6.1 — source of MINOR items
- `REACT_MIGRATION.md` — confirm current Phase 4 status

Write:
- `README.md` (ops-01, ops-02)
- `README_deploy.md` (ops-05)
- `PHASE3_PROMPT.md` (ops-03)
- `ARCHITECTURE_REVIEW.md` (ops-04)
- `docs/CLASSIFICATION_METHODOLOGY.md` (ops-07)
- `PHASE1_PROMPT.md`, `PHASE3_PROMPT.md`, `PHASE4_PROMPT.md` (ops-08 housekeeping — mostly status markers or retire decisions)
- `ROADMAP.md` (ops-10 then ops-11, in that order)
- `scripts/migrations/007_override_new_value_nullable.py` (ops-12 — docstring only)
- `docs/canonical_ddl.md` (ops-12 cross-ref)
- `docs/findings/ops-batch-5A-p0-findings.md` — meta-doc listing exactly what was changed and why, with verification queries

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.** This list matches Appendix D of `docs/REMEDIATION_PLAN.md`.

## Scope — per item

### ops-01 MINOR-6 DOC-01 README.md retired update.py references
- Find every mention of `scripts/update.py` as "master pipeline". Replace with current Makefile targets (`make quarterly-update`, etc.).
- Verify current Makefile entry points.

### ops-02 MINOR-7 DOC-02 README project tree refresh
- Update project tree to reflect: `scripts/api_*.py` Blueprint split, `web/react-app/`, `scripts/pipeline/`, `scripts/migrations/`.
- Reference `scripts/app.py:6-20` for current Blueprint registrations.

### ops-03 MINOR-8 DOC-03 PHASE3_PROMPT.md retired fetch_nport
- Update or mark retired references to `fetch_nport.py`. Current canonical is `fetch_nport_v2.py`.

### ops-04 MINOR-9 DOC-04 ARCHITECTURE_REVIEW vs REACT_MIGRATION Phase 4 contradiction
- Confirm React Phase 4 complete (per `REACT_MIGRATION.md:120` + commits 2026-04-13).
- Update `ARCHITECTURE_REVIEW.md:51-52` to reflect completion.

### ops-05 MINOR-10 DOC-05 README_deploy React build prereq
- Add `npm --prefix web/react-app install && npm --prefix web/react-app run build` prereq step before Python entrypoint.

### ops-07 MINOR-12 DOC-09 CLASSIFICATION_METHODOLOGY entity count
- Verify current entity count via `SELECT COUNT(*) FROM entity_current` (read-only).
- Update `docs/CLASSIFICATION_METHODOLOGY.md:11-13, :29-30` with current figure + date.

### ops-08 MINOR-13 DOC-10 prompt file housekeeping
- For each of `PHASE1_PROMPT.md`, `PHASE3_PROMPT.md`, `PHASE4_PROMPT.md`: decide retire-vs-mark-superseded per current session flow.
- Update or add a one-line header indicating status.

### ops-10 MINOR-1 R-01 ROADMAP 13DG exclusion count
- Verify via `SELECT COUNT(*) FROM entity_overrides_persistent WHERE action='exclude_13dg'` (or equivalent query — confirm exact column).
- Update `ROADMAP.md:3` from "928" to current count.

### ops-11 MINOR-2 R-02 ROADMAP NULL-CIK override count
- Verify via appropriate query.
- Update `ROADMAP.md:3` and `:393-394` from "4" to current count.

### ops-12 Pass 2 §8.2 migration 007 NULL-target doc note
- Add docstring note to `scripts/migrations/007_override_new_value_nullable.py:8-12` explaining the intentional NULL-target replay-skip semantics (prevents future auditors from re-flagging as defect).
- Add one-line cross-ref to `docs/canonical_ddl.md` if it references migration 007.

## Out of scope

- Any code changes (except ops-12 docstring-only edit).
- Any DB writes.
- ops-06 (write_path_risk_map — in Batch 5-B).
- ops-09 (new api_architecture.md — in Batch 5-B).
- ops-13, ops-14, ops-16 (DOC_UPDATE_PROPOSAL bundles — in Batch 5-C/5-D, depend on Theme 1 decisions).

## Deliverable

All edits landed in one session. `docs/findings/ops-batch-5A-p0-findings.md` summarizes each item with before/after, verification queries, and cross-refs. No further Phase 1 needed — this IS the Phase 1.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/ops-batch-5A-p0: doc hygiene sweep`. Report PR URL + CI status.
