# ops-batch-5A-p0 — Findings

_Phase 0 + 1 combined. Branch `remediation/ops-batch-5A-p0` off main HEAD `46c2a25`.
Session date: 2026-04-20. All edits landed in this single PR._

Doc-hygiene sweep: disjoint-file subset of Batch 5-A. Fact-checks audited MINOR
items from `docs/SYSTEM_AUDIT_2026_04_17.md` §7.1 (DOC-0x) + §6.1 (R-0x).
Read-only prod DuckDB verification (no code writes, no DB writes).

## Verification queries

```sql
-- ops-07 current entity count
SELECT COUNT(*) FROM entity_current;
-- → 26,535

-- ops-10 13DG exclusion rows written by scripts/resolve_13dg_filers.py --prod-exclusions
SELECT source_type, resolution_status, COUNT(*)
FROM pending_entity_resolution
WHERE source_type = '13DG'
GROUP BY 1, 2;
-- → 13DG / excluded_individual / 921
-- → 13DG / excluded_law_firm   /   2
-- → 13DG / excluded_other      /   5
-- → 13DG / pending             /   3
-- Total: 931 (audit-corrected from 928 in commit `5efae66` and prior ROADMAP header;
-- the 3 "pending individual" rows were undercounted because the original prose
-- counted only the `excluded_*` subset.)

-- ops-11 NULL-CIK overrides in DM15 L2 range IDs 205-221
SELECT COUNT(*)
FROM entity_overrides_persistent
WHERE override_id BETWEEN 205 AND 221
  AND new_value IS NULL;
-- → 5  (IDs 205, 206, 207, 208, 220 — all Voya + Dynamic Beta replay-gap rows)
-- Audit-corrected from 4 in commit `938e435` body and prior ROADMAP header.
```

## Items — before / after

### ops-01 MINOR-6 DOC-01 — README.md retired update.py references

**Before:** README "Build Order" section instructed
`python3 scripts/update.py` as the master pipeline entry point; "Updating
for New Quarters" repeated it; "Project Structure" listed
`update.py — Master pipeline script`.

**After:** Build Order now drives off `make quarterly-update` (and
per-step `make fetch-13f`, `make fetch-nport`, `make build-entities`, …)
matching `Makefile:65-82`. "Updating for New Quarters" replaced with
`make quarterly-update`. Deprecation note added: `scripts/update.py`
is on disk but not failing-fast; open item INF32 in `ROADMAP.md`
tracks its retired-script references. The Makefile is now the single
documented entry point.

**Verification:** `grep -n "update.py" README.md` now returns only the
new deprecation-note line in Build Order (single occurrence, no
remaining positive references); `make help` enumerates
`quarterly-update` + every individual step.

### ops-02 MINOR-7 DOC-02 — README project tree refresh

**Before:** Tree listed only top-level per-script names, missed
`scripts/api_*.py` router split, `scripts/pipeline/`, `scripts/migrations/`,
`web/react-app/`, `tests/`, `docs/`, etc. Referenced `update.py` as
`Master pipeline script`.

**After:** Full rewrite. Each `api_*.py` router enumerated with the path
prefix it owns; `admin_bp.py` called out as token-authed. `scripts/pipeline/`
lists `discover.py`, `manifest.py`, `protocol.py`, `shared.py`,
`validate_schema_parity.py`, `nport_parsers.py`. `scripts/migrations/`
called out. `web/react-app/` called out with `src/`, `dist/`,
`package.json`, `vite.config.ts`, `playwright.config.ts`. `web/templates/`
noted as admin-only. `tests/` added. `docs/` added. Cross-reference
to `scripts/app.py:6-20` for the live router manifest (per the prompt's
Files-to-Read directive).

**Verification:** Cross-checked against `ls scripts/`, `ls scripts/pipeline/`,
`ls scripts/migrations/`, `ls web/react-app/`, `ls docs/`, `ls tests/` —
every directory listed exists on HEAD.

### ops-03 MINOR-8 DOC-03 — PHASE3_PROMPT.md retired fetch_nport

**Before:** PHASE3_PROMPT.md "Track C: N-PORT data refresh" section
instructed `python3 -u scripts/fetch_nport.py`. The legacy
`scripts/fetch_nport.py` was retired to `scripts/retired/` in
BLOCK-3 merge `0dc0d5d` (2026-04-18); `scripts/fetch_nport_v2.py` is the
canonical XML-path entry point (wired through `make fetch-nport`).

**After:** Added SUPERSEDED status banner at top of file. Updated the two
`fetch_nport.py` invocations to `fetch_nport_v2.py` with an inline note
referencing the 2026-04-18 retirement.

**Verification:** `grep -n "fetch_nport" PHASE3_PROMPT.md` now shows
`fetch_nport_v2.py` only; `ls scripts/retired/` shows the legacy file
archived.

### ops-04 MINOR-9 DOC-04 — ARCHITECTURE_REVIEW Phase 4 contradiction

**Before:** `ARCHITECTURE_REVIEW.md:51-52` said "Phase 3 complete (commit
`c836813`). Phase 4 cutover pending. Two frontends currently live —
React at port 5174, vanilla-JS at port 8001." Contradicted
`archive/docs/REACT_MIGRATION.md:120` which says Phase 4 completed 2026-04-13 at
HEAD `002fab0` with the vanilla-JS retirement done in the same session.

**After:** Replaced with: Phase 4 complete 2026-04-13 (commit `002fab0`);
single frontend; FastAPI serves `web/react-app/dist/` on port 8001;
vanilla-JS and `web/react-src/` POC retired same session; 38 public
routes rewritten to `/api/v1/*`. Cross-ref to `archive/docs/REACT_MIGRATION.md`
Status section.

**Verification:** `grep -n "Phase 4" archive/docs/REACT_MIGRATION.md` confirms the
cutover line at :120; `git log -- scripts/app.py | head` confirms the
post-cutover FastAPI swap is in main history.

### ops-05 MINOR-10 DOC-05 — README_deploy React build prereq

**Before:** Local Testing section instructed `pip install -r
requirements.txt` then `python3 scripts/app.py --port 8001`. Since
Phase 4 cutover the app serves `web/react-app/dist/`, so omitting
the React build yields 404 on `/` and every tab route. Render build
command also omitted the React build.

**After:** Added Local Testing prereq step: `npm --prefix web/react-app
install && npm --prefix web/react-app run build` with an inline
explanation of why it is required (since Phase 4 cutover). Render
build command upgraded to
`pip install -r requirements.txt && npm --prefix web/react-app install
&& npm --prefix web/react-app run build`. Updated `Updating Data`
section to drive off `make quarterly-update` instead of `update.py`.

**Verification:** `ls web/react-app/package.json` confirms the React app
exists; `grep -n "static_folder\|dist" scripts/app.py` confirms the
FastAPI app mounts `web/react-app/dist/`.

### ops-07 MINOR-12 DOC-09 — CLASSIFICATION_METHODOLOGY entity count

**Before:** `docs/CLASSIFICATION_METHODOLOGY.md` cited 20,205 entities in
two places (`:11-13`, `:29-30`), with _Last updated: April 9, 2026_.
Current prod: 26,535 (per verification query above). Drift: +6,330
entities from DM14b/DM15 sub-adviser MDM buildout + 2026-04-17 13D/G
filer resolution.

**After:** Header date advanced to April 20, 2026 with a one-line
description of what drove the delta. Resolution-order step 1 and
Classification Sources table row both updated to
`26,535 entities (2026-04-20)` with query provenance.

**Verification:** `SELECT COUNT(*) FROM entity_current` returns 26,535
(matches ROADMAP 2026-04-17 session #11 close "entities 26,535 (+1,640)").

### ops-08 MINOR-13 DOC-10 — prompt file housekeeping

**Before:** `PHASE3_PROMPT.md` and `PHASE4_PROMPT.md` tracked in-repo but
orphaned: session flow has long moved to `docs/NEXT_SESSION_CONTEXT.md`;
neither prompt is loaded at session start anymore, and both reference
work-items that have shipped. `PHASE1_PROMPT.md` was noted as untracked
in the audit — confirmed: no such file on HEAD or in `git log -- PHASE1_PROMPT.md`,
so no action.

**After:** Added a SUPERSEDED status banner at the top of each existing
prompt file noting the retention-for-history stance, pointing users to
`docs/NEXT_SESSION_CONTEXT.md`, and flagging specific facts (canonical
entity IDs, script names) that are stale snapshots. Files retained
rather than deleted — they remain useful as historical context for
session #2/#3 Entity MDM Phase 4 work and the first React migration
tranche.

**Verification:** `head -5 PHASE3_PROMPT.md` and `head -5 PHASE4_PROMPT.md`
both show the STATUS banner.

### ops-10 MINOR-1 R-01 — ROADMAP 13DG exclusion count

**Before:** ROADMAP prior header (session #11 close) stated:
`prod-direct pass writes 928 exclusions to pending_entity_resolution
(921 individual / 2 law_firm / 5 other)`. Audit finding R-01: prod
has 931.

**After:** Updated the header in-place to
`writes 931 rows to pending_entity_resolution (921 excluded_individual
/ 2 excluded_law_firm / 5 excluded_other / 3 remained pending — audit
correction; commit 5efae66 body and prior ROADMAP header both stated
928, which undercounted the 3 still-pending rows by treating only the
excluded_* subset)`, with a cross-reference to
`docs/SYSTEM_AUDIT_2026_04_17.md §6.1 R-01`.

**Verification:** query above returned 921+5+2+3=931 rows in
`pending_entity_resolution` with `source_type='13DG'`.

### ops-11 MINOR-2 R-02 — ROADMAP NULL-CIK override count

**Before:** Both the session #11 prior header and the DM15 Layer 2 row
in the Done-2026-04-17 table stated
`Override IDs 205-221 (4 NULL-CIK per INF9d/DM15 L1 precedent)`. Audit
finding R-02: prod has 5 NULL-CIK rows in that range (commit `938e435`
body itself under-counted).

**After:** Both occurrences updated to `5 NULL-CIK` with an inline
audit-correction note and cross-reference to
`docs/SYSTEM_AUDIT_2026_04_17.md §6.1 R-02`. Preserved the DM15 L1
precedent reference and (on the second occurrence) the
`migration 007 handles` clause.

**Verification:** `SELECT COUNT(*) FROM entity_overrides_persistent
WHERE override_id BETWEEN 205 AND 221 AND new_value IS NULL` returns 5
(IDs 205-208 Voya + 220 Dynamic Beta).

### ops-12 Pass 2 §8.2 — migration 007 NULL-target doc note

**Before:** `scripts/migrations/007_override_new_value_nullable.py:8-12`
docstring explained the history of DM15 L1 staging the NULL-target
rows, but did not explicitly name the replay-skip semantics as
intentional. Future auditors running a
row-count-vs-replay-apply-count comparison could reasonably flag
the divergence as a defect. `docs/canonical_ddl.md` §17 mentioned
`entity_overrides_persistent` without cross-referencing migration 007.

**After:** Migration 007 docstring expanded with a dedicated section
`INTENTIONAL NULL-TARGET REPLAY-SKIP SEMANTICS (do not re-flag as defect)`
that names the three invariants: (1) override effect applied at write
time, not replay time; (2) replay skip of NULL-target rows is correct
because the pre-rebuild state already reflects the effect; (3) the
row's replay role is purely documentary. Explicit monitoring guidance:
gates must filter `WHERE new_value IS NOT NULL` before comparing
row-count to apply-count. `docs/canonical_ddl.md` §17 gained a
"Migration 007 note" paragraph with the same invariant in abbreviated
form + pointer to the migration docstring.

**Verification:** `sed -n '3,60p' scripts/migrations/007_override_new_value_nullable.py`
shows the new section in the docstring; `grep -n "Migration 007"
docs/canonical_ddl.md` returns the new §17 note.

## Files written (full list — matches prompt Appendix D scope)

- `README.md` — ops-01, ops-02
- `docs/deployment.md` — ops-05
- `PHASE3_PROMPT.md` — ops-03 + ops-08
- `PHASE4_PROMPT.md` — ops-08
- `ARCHITECTURE_REVIEW.md` — ops-04
- `docs/CLASSIFICATION_METHODOLOGY.md` — ops-07
- `ROADMAP.md` — ops-10, ops-11
- `scripts/migrations/007_override_new_value_nullable.py` — ops-12 (docstring only)
- `docs/canonical_ddl.md` — ops-12 cross-ref
- `docs/findings/ops-batch-5A-p0-findings.md` — this document

No other files touched. `PHASE1_PROMPT.md` does not exist on HEAD or in
`git log`, so the ops-08 housekeeping reduced to two files rather than
three.

## Out-of-scope items explicitly deferred

- ops-06 (`docs/write_path_risk_map.md` T2 list) — Batch 5-B.
- ops-09 (new `docs/api_architecture.md`) — Batch 5-B.
- ops-13 / ops-14 / ops-16 (`DOC_UPDATE_PROPOSAL` bundles) — Batch 5-C / 5-D,
  depend on Theme 1 decisions.

## CI expectations

No code paths changed. Pre-commit (ruff + pylint + bandit) runs on the
migration 007 docstring edit (docstring-only, no logic change);
expected green. Smoke CI not exercised by doc edits.
