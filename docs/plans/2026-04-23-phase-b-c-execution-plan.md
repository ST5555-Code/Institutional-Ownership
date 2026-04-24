# Phase B / Phase C Execution Plan — 2026-04-23

**Status:** DRAFT v4 — incorporates plan-review-v3 findings + Serge Q1/Q2 decisions. Final before adoption.
**Target location on merge:** `docs/plans/2026-04-23-phase-b-c-execution-plan.md`.
**Inputs:**
- `docs/findings/comprehensive-audit-2026-04-23.md` (Phase A)
- `docs/findings/pre-phase-b-verification-2026-04-23.md` (verification)
- `docs/findings/plan-review-2026-04-23.md` (v2 critique)
- `docs/findings/refinement-validation-2026-04-23.md` (v3 refinement validation)
- `docs/findings/plan-review-v3-2026-04-23.md` (v3 critique)

**v4 changes from v3:**
- C1 (critical): C1 prompt enumerates from `DATASET_REGISTRY` + `SHOW TABLES` cross-check, not from `canonical_ddl.md` headings (Q2 decision)
- R1: Added `registry.py:175 other_managers` owner update to B2.5 scope
- R2: Added Makefile `quarterly-update` target fix (require `QUARTER=`) to B2.5 scope
- R3: `§7.2` → `§8.2` cross-references corrected in §2.1.1 and §2.6 (V10 fix location)
- R4: Named both `build_managers.py` L12 (docstring) and L228 (tuple) refs in B2.5
- R5: Tightened §5.4 grep gate to explicit allowed-files list
- M1: `scripts/update.py:75` → `scripts/update.py:74` (off-by-one)
- M2: `owner="manual"` → `owner="manual seed"` (matches `peer_groups` precedent at registry:317)
- M3: Added `queries.py` stale prose comments cleanup to B3 §7.2 co-land list
- M4: Added real `--auto-approve` smoke against fixture DB to B2.5 §5.6
- Q1 decision: Sequential (B1 → B2 → B2.5) preserved — no combining; calendar math confirmed feasible

---

## §0 — Purpose and boundaries

The comprehensive audit plus pre-Phase-B verification plus refinement validation plus plan reviews produced a set of actions, Serge decisions, and a validated execution sequence. This document translates them into discrete batches with gating, rollback, and per-batch Code session drafts.

**Hard rules this plan respects:**

- Every batch is single-session, single-PR, file-disjoint from other batches in-flight.
- Every batch has a documented gate before the next batch starts.
- Risk-ordered execution: lowest-risk first, DB drops last.
- No batch acts on any count or metric pulled from the audit without verifying it live. V6 demonstrated the audit's own numbers can be wrong.
- Plan-level meta-fixes (like this plan itself) ship solo — no parallel execution with substantive work.
- **Solve once:** every operational change co-lands its own metadata/reference cleanups in the same PR. No "we'll fix registry/references in the next phase" deferral.
- **One session, one narrow PR:** preserves reviewability, rollback granularity, and reduces coupled risk. Rollups rejected unless file-disjoint AND no added risk.

**Out of scope:**

- PR #107 ui-audit walkthrough (separate track)
- Q1 2026 13F cycle execution (Tier 1, calendar-gated)
- DM Tier 2 work, Tier 3 architectural design
- Any Tier 6 item not surfaced by the audit + verification + validation

---

## §1 — Master sequence

```
┌─────────────────────────────────────────────────┐
│ Plan adopted (v4 on main)                       │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│ Phase B1 — Tracker hygiene + doc archival      │
│ Risk: very low (doc-only)                       │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│ Phase B2 — Script filesystem reorg             │
│ Risk: medium (import-break potential)           │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│ Phase B2.5 — V2 cutover                         │
│ Risk: medium-high (scheduled path changes)      │
│ Must land BEFORE Q1 2026 cycle starts (~May 15) │
└──────────────────────────┬──────────────────────┘
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
┌──────────────────────┐   ┌──────────────────────┐
│ Phase C1 — DDL fold  │   │ Phase C2 — Tracker   │
│ Risk: low (doc-only) │   │ consolidation +      │
│ Parallel with C2.    │   │ ops-18 investigate   │
└──────────┬───────────┘   └──────────┬───────────┘
           │                          │
           └──────────────┬───────────┘
                          │
          Both C PRs merged
                          │
                          ▼
          ┌──────────────────────────────────────┐
          │ Operational gate:                     │
          │ Q1 + Q2 2026 13F cycles run clean    │
          │ on V2 scheduled path (~Aug 2026)     │
          └──────────────────┬───────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────┐
          │ Phase B3 — V1 retire + 4 DDL drops   │
          │ + co-land cleanups in same PR        │
          │ Risk: low after 2-cycle gate         │
          └──────────────────────────────────────┘

Small one-offs: dispatched opportunistically during any batch's idle time.
```

**Calendar note:** Today 2026-04-23. Q1 2026 cycle ~May 15. ~22 days. Sequential B1 (1-2d) → B2 (2-3d) → B2.5 (3-4d with real smoke) = 6-9 days best case. If calendar slips for unforeseen reasons, fallback is to run Q1 on V1 one more time and push the 2-cycle gate to Q2+Q3. No forced combining.

---

## §2 — Phase B1: Tracker hygiene + doc archival

**Session name:** `phase-b1-doc-hygiene`.
**Estimated duration:** 30-60 min Code time.
**Risk level:** Very low.

### §2.1 Scope

**Tracker fixes:**
- Flip three stale `[ ]` checkboxes in `docs/REMEDIATION_CHECKLIST.md` at L39, L98, L101 (verified V4).
- Retire `docs/REMEDIATION_CHECKLIST.md` entirely to `archive/docs/REMEDIATION_CHECKLIST.md` with a pointer stub in `docs/REMEDIATION_PLAN.md`.
- Annotate INF40 dual-closure note in ROADMAP Closed log (Option A bracketed append) + three future-proofing mitigations.

**Doc archival (to `archive/docs/`):**
- `PHASE3_PROMPT.md`, `PHASE4_PROMPT.md`, `PHASE4_STATE.md`
- `docs/SYSTEM_ATLAS_2026_04_17.md`, `docs/SYSTEM_AUDIT_2026_04_17.md`, `docs/SYSTEM_PASS2_2026_04_17.md`
- `data/reference/ROLLUP_COVERAGE_REPORT.md`
- `docs/POST_MERGE_REGRESSIONS_DIAGNOSTIC.md`

**Archive directory scaffolding:**
- `archive/docs/README.md` — index with one-line rationale per archived file

### §2.1.1 INF40 annotation — three future-proofing mitigations

**Mitigation 1 — Whitelist entry in audit_ticket_numbers.py**
Add explicit config entry marking INF40 as "dual-closure, accepted."

**Mitigation 2 — Classifier recognizes annotation pattern**
`audit_ticket_numbers.py` detects bracketed-annotation pattern `[INF<N> #M of K]` as canonical disambiguation. **This is independent from V10 grouped-row fix** (which lives in `line_kind()` / `extract_table_title()` — §8.2 scope).

**Mitigation 3 — REVIEW_CHECKLIST.md explicit note**
Add section documenting INF40 exception + prohibition against re-issuing it.

### §2.2 Gating condition (before starting)

- Main clean.
- No Code sessions in flight on these files.
- Phase A (PR #134), verification (PR #135), plan review (PR #136), validation (PR #137) all merged to main.
- This plan (v4) on main.

### §2.3 Gating condition (after completing)

- PR merged to main.
- CI green.
- `grep -rn "REMEDIATION_CHECKLIST" docs/ ROADMAP.md README.md` returns only archive pointer references.
- `archive/docs/` exists with expected files + README.md index.
- `docs/REVIEW_CHECKLIST.md` has dual-closure note.
- audit_ticket_numbers.py runs clean on INF40 (no VIOLATION).
- Worktree cleanup run.

### §2.4 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Broken inbound reference | Medium | Low | Grep-verify every inbound ref updated |
| INF40 classifier refactor larger than expected | Low | Low | Prompt escape hatch — if >35 LOC needed, STOP and defer to §8.2 |

### §2.5 Rollback plan

PR revert on main if any issue surfaces. No DB impact, no code impact.

### §2.6 Code session prompt draft

```
Session: phase-b1-doc-hygiene

Mode: Doc hygiene. Single PR.

Working dir: ~/ClaudeWorkspace/Projects/13f-ownership
Base: main
Branch: phase-b1-doc-hygiene

Hard scope:
- DO NOT modify any file not in plan §2.1.
- DO NOT move any script. DO NOT touch DB.
- If inbound refs exceed expectation, STOP and report before proceeding.

Phase 1 — Verify start
1. git status clean
2. HEAD includes v4 plan commit
3. sed -n '39p;98p;101p' docs/REMEDIATION_CHECKLIST.md — confirm match audit claims
4. archive/ directory does not yet exist

Phase 2 — Tracker flips
Apply 3 checkbox flips in docs/REMEDIATION_CHECKLIST.md before archiving it:
- L39: `[ ]` → `[x]` with note ` — CLEARED <TODAY> (entity-curation-w1)`
- L98: `[ ]` → `[x]` with note ` — SUPERSEDED by Phase 2 (prog-01)`
- L101: `[ ]` → `[x]` with note ` — absorbed by p2-05 load_13f_v2.py`

Where <TODAY> is the actual session date (use `date +%Y-%m-%d`).

Phase 3 — INF40 annotation
Edit ROADMAP.md Closed log. Append bracketed annotations:
- First INF40 (L3 surrogate row-ID, 2026-04-22): in Notes cell, append ` [INF40 #1 of 2 — distinct from INF40 (entity-CTAS) closed 2026-04-23; retained per 2026-04-23 decision, not re-issued]`
- Second INF40 (entity-CTAS, 2026-04-23): append ` [INF40 #2 of 2 — distinct from INF40 (L3 surrogate row-ID) closed 2026-04-22]`

Phase 4 — INF40 future-proofing (3 mitigations)

Mitigation 1: Add whitelist entry to scripts/audit_ticket_numbers.py:
- Add DUAL_CLOSURE_EXCEPTIONS = {"INF40"} at module level
- Filter in main() reuse detection loop: skip tickets in DUAL_CLOSURE_EXCEPTIONS
- ~5-10 LOC

Mitigation 2: Add annotation-pattern recognition:
- Detect `[INF<N> #M of K]` pattern in line content during scan()
- Mark matching Definition as annotated
- Exclude annotated definitions from group_distinct() candidate-reuse output
- ~15-25 LOC
- Note: this is INDEPENDENT of V10 grouped-row fix (§8.2). Do not try to fix V10 here.

If combined M1+M2 exceed 35 LOC OR require structural refactor beyond additions, STOP and surface. Defer M2 to §8.2.

Mitigation 3: Add to docs/REVIEW_CHECKLIST.md under "Ticket Number Discipline":
```
> **Prior dual-closure items (INF40):**
> INF40 has two annotated closures using pattern `[INF<N> #M of K]`. Do NOT file new INF40. Next available number is current monotonic increment. Run `scripts/hygiene/audit_ticket_numbers.py` if unsure. (Script relocates to scripts/hygiene/ in Phase B2.)
```

Phase 5 — Retire REMEDIATION_CHECKLIST.md
1. mkdir -p archive/docs
2. git mv docs/REMEDIATION_CHECKLIST.md archive/docs/REMEDIATION_CHECKLIST.md
3. Add pointer at docs/REMEDIATION_PLAN.md top:
> "Remediation Program COMPLETE 2026-04-22 (conv-11). Historical checklist retired to archive/docs/REMEDIATION_CHECKLIST.md on <TODAY>. Sprint-view no longer useful post-program. Forward work → ROADMAP.md."

Phase 6 — Archive 8 legacy docs
git mv each to archive/docs/:
- PHASE3_PROMPT.md, PHASE4_PROMPT.md, PHASE4_STATE.md
- docs/SYSTEM_ATLAS_2026_04_17.md, docs/SYSTEM_AUDIT_2026_04_17.md, docs/SYSTEM_PASS2_2026_04_17.md
- data/reference/ROLLUP_COVERAGE_REPORT.md
- docs/POST_MERGE_REGRESSIONS_DIAGNOSTIC.md

Phase 7 — Inbound ref cleanup
For each archived file:
> grep -rn "<filename>" docs/ scripts/ tests/ web/ *.md
Update active refs to archive/docs/ paths. Flag script refs for review.

Phase 8 — Write archive/docs/README.md with index + one-line rationale per file.

Phase 9 — Final verification
1. git status — only expected changes
2. CI pre-commit clean
3. Inbound refs resolved
4. audit_ticket_numbers.py run: no VIOLATION on INF40

Phase 10 — PR + merge confirmation
Title: `phase-b1-doc-hygiene`
Body: describe changes, cite audit + verification + validation.

Git lifecycle:
1. Commit, push, open PR, wait for CI green.
2. When CI green, Code pauses and asks Serge: "PR #N green. Merge?"
3. On yes: merge, delete branch, clean up worktree, close session.
4. On no or adjust: address per Serge's instruction, re-push, re-ask.
5. Do NOT merge without explicit yes.
6. Do NOT use --no-verify. DO NOT force push.

Output: Summary of files moved, refs updated, checkboxes flipped, INF40 status.

Out of scope: anything beyond the 3 flips + ROADMAP INF40 + REVIEW_CHECKLIST note + audit_ticket_numbers.py (mitigations 1+2 only) + 8 archivals.
```

---

## §3 — Phase B2: Script filesystem reorg

**Session name:** `phase-b2-script-reorg`.
**Estimated duration:** 60-120 min.
**Risk level:** Medium.

### §3.1 Scope

**Rationale:** V7's tighter sweep produced 6 named oneoff candidates. Applying V7's classification rules to the full Pass-2 candidate set yields 11 historic one-offs — V7's 6 plus 5 additional scripts that fit the same rules.

**Relocations to `scripts/oneoff/`** (11 scripts):
- From V7's named set: `backfill_pending_context.py`, `bootstrap_tier_c_wave2.py`, `dm14_layer1_apply.py`, `dm14b_apply.py`, `dm15_layer1_apply.py`, `inf23_apply.py`
- Applying V7 rules to remainder: `dm14c_voya_amundi_apply.py`, `dm15_layer2_apply.py`, `dm15c_amundi_sa_apply.py`, `inf39_rebuild_staging.py`, `migrate_batch_3a.py`

**For `migrate_batch_3a.py`:** co-land registry owner update. `scripts/pipeline/registry.py:295` — change `owner="scripts/migrate_batch_3a.py"` → `owner="manual seed"`. This matches precedent at `registry.py:317` (`peer_groups` uses `"manual seed"`). The script's actual nature: one-shot seeder, never re-run since 2026-04-13, DB rows bit-identical to in-code seed. Eliminates a false "live owner" signal.

**New `scripts/hygiene/` directory:**
- `scripts/audit_ticket_numbers.py` (with B1's mitigations 1+2 intact)
- `scripts/audit_tracker_staleness.py`
- `scripts/audit_read_sites.py`
- `scripts/cleanup_merged_worktree.sh`
- `scripts/bootstrap_worktree.sh`
- `scripts/concat_closed_log.py`

**Retirements to `scripts/retired/`:**
- `scripts/smoke_yahoo_client.py`
- `scripts/snapshot_manager_type_legacy.py`

**Explicitly NOT moving:**
- `scripts/load_13f.py`, `scripts/load_13f_v2.py` (both verified live in V3; B2.5 handles cutover; B3 retires V1)

### §3.2 Gating condition (before starting)

- Phase B1 PR merged.
- CI green on main.

### §3.3 Gating condition (after completing)

- PR merged.
- CI green.
- Full `pytest tests/ -v` green.
- No import errors from relocated scripts.
- Worktree cleanup run.

### §3.4 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Broken import path | Medium | Medium | Smoke test mandatory; probe imports per move |
| Shell script path in Makefile/sh | Medium | Low | Grep-verify all caller files |
| Misclassified script (actually live) | Low-medium | Medium | Verify V7 categorization + check `scripts/pipeline/registry.py` `owner=` / `downstream=` fields per script (easy-to-miss metadata references) |

### §3.5 Rollback plan

`git revert` on PR if issues. Before merge: if tests fail, revert session and narrow scope.

### §3.6 Code session prompt draft

```
Session: phase-b2-script-reorg

Mode: Filesystem reorg. git mv + update callers + verify tests. Single PR.

Working dir: ~/ClaudeWorkspace/Projects/13f-ownership
Base: main (post phase-b1)
Branch: phase-b2-script-reorg

Hard scope:
- DO NOT modify script logic — only location + caller references + registry.py owner updates
- DO NOT touch load_13f.py or load_13f_v2.py (both live per V3)
- DO NOT touch DB
- If a relocation has live callers not anticipated, STOP and surface

Phase 1 — Verify start
1. git status clean
2. HEAD includes Phase B1 merge
3. ls scripts/oneoff/ scripts/retired/ — exist
4. mkdir -p scripts/hygiene

Phase 2 — Per-script verification
For each of the 11 oneoff candidates + 6 hygiene + 2 retire (19 total):
> grep -rn "<script_stem>" Makefile scripts/ tests/ web/ docs/ .github/ *.sh
Classify: WRITER / CALLER / REFERENCE.

Special checks per script:
> grep -n "<script_stem>" scripts/pipeline/registry.py
If hit in registry owner/downstream field: note for co-land update.

If any CALLER in Makefile / scheduler.py / update.py / admin_bp.py / CI workflow: STOP and flag.

Output per-script table: path | CALLERS | REGISTRY REF | VERDICT.

Phase 3 — Execute moves (if Phase 2 clear)
Relocations to scripts/oneoff/:
[list of 11 git mv commands]

Co-land: migrate_batch_3a owner update
Edit scripts/pipeline/registry.py:
- Line ~295, fund_family_patterns spec
- Change owner="scripts/migrate_batch_3a.py" → owner="manual seed"
- Keep notes field as-is ("seeded once, manually edited thereafter")

New scripts/hygiene/:
[6 git mv commands]

Retirements:
[2 git mv commands]

Phase 4 — Caller updates
For each caller identified in Phase 2, update reference to new path.

Phase 5 — Documentation
Update docs/SESSION_GUIDELINES.md with new structure:
- scripts/ = active pipelines + core utilities
- scripts/hygiene/ = audit + cleanup tools
- scripts/oneoff/ = historical apply/bootstrap/seed (audit trail)
- scripts/retired/ = superseded, do not call
- scripts/pipeline/ = SourcePipeline framework

Update docs/REVIEW_CHECKLIST.md INF40 note: `scripts/hygiene/audit_ticket_numbers.py` path.
Update MAINTENANCE.md references to moved scripts.

Phase 6 — Test suite
> pytest tests/ -v
> pytest tests/smoke/ -v
Both green. Capture output.

Phase 7 — PR + merge confirmation
Title: `phase-b2-script-reorg: 11 oneoffs + 6 hygiene + 2 retire + registry owner update`
Body: per-script table, diff, test output, rationale for oneoff expansion (V7 rules applied to full set).

Git lifecycle: same as B1 (ask Serge before merge).

Output: Summary with per-directory counts and any surprises.

Out of scope: script logic, load_13f.*, new scripts/tests, DB operations.
DO NOT use --no-verify. DO NOT force push.
```

---

## §4 — Phase C1: Canonical DDL fold

**Session name:** `phase-c1-ddl-fold`.
**Estimated duration:** 60-120 min.
**Risk level:** Low (doc-only, but scope-up per V6).

### §4.1 Scope

**Rationale (per V6):** canonical_ddl.md's column counts are stale — doc claims holdings_v2=33, actual prod is 38. Drift is +5 on holdings_v2, +4 on fund_holdings_v2, +6 on beneficial_ownership_v2. A regen from doc content forward would inherit the staleness. Correct approach: regenerate DDL from prod `information_schema` fresh, then fold into data_layers.md.

**Generate fresh DDL from prod.** Approach:

1. **Enumerate tables from `DATASET_REGISTRY` cross-checked against `SHOW TABLES`** — not from `canonical_ddl.md` (which is a drift report, not a per-table catalog). Plan-review-v3 C1 finding: canonical_ddl.md uses `##` headings and groups multiple tables per heading. DATASET_REGISTRY is authoritative and persists past this fold.
2. For each table in the enumeration: query `information_schema.columns` for column list + types + nullability
3. For each: query `information_schema.table_constraints` for PK/unique
4. Compose `CREATE TABLE` DDL from live schema
5. Generate migration-history appendix from `schema_versions` table + `scripts/migrations/` directory

**Fold approach:**
1. Create new section in `docs/data_layers.md` titled `## Appendix A: Canonical DDL` (at end of file)
2. Include regenerated DDL per table, with row counts at regen time
3. Include migration-history as `## Appendix A.2: Migration History`
4. Add lead paragraph noting the appendix is generated from prod, with regeneration date

**Retire canonical_ddl.md:**
1. `git mv docs/canonical_ddl.md archive/docs/canonical_ddl.md`
2. Create minimal pointer stub at `docs/canonical_ddl.md`:
```
# Canonical DDL — Moved
This file was folded into `docs/data_layers.md` (Appendix A) on <session_date>.
Archived original: `archive/docs/canonical_ddl.md`.
Current prod DDL is generated from `information_schema`; see Appendix A.
```

**Update all inbound references** — replace paths to `docs/canonical_ddl.md` with `docs/data_layers.md#appendix-a-canonical-ddl`. Leave references inside archived docs untouched (those are historical).

### §4.2 Gating condition (before starting)

- Phase B2 PR merged.
- CI green.
- Can run parallel with Phase C2 (different file sets).

### §4.3 Gating condition (after completing)

- PR merged.
- CI green.
- `data_layers.md` Appendix A covers every table in `DATASET_REGISTRY` that exists in prod (100% overlap).
- Any table in `DATASET_REGISTRY` but not in prod: flagged in Appendix A with status (retire candidate, or not-yet-created).
- Any table in prod but not in `DATASET_REGISTRY`: flagged as registry gap (pre-existing issue; not fixed in C1 but surfaced).
- All inbound references updated (zero stale links from active docs to old path).
- `archive/docs/canonical_ddl.md` exists with original content.
- Pointer stub at `docs/canonical_ddl.md` exists.
- Worktree cleanup run.

### §4.4 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Column regen misses dropped-then-re-added columns | Low | Low | `information_schema` is authoritative for current state |
| Inbound ref updates broken | Medium | Low | Grep-verify every reference post-update |
| Migration-history appendix lossy | Low | Medium | Read both schema_versions + scripts/migrations/ directory |
| DATASET_REGISTRY has gaps missed in enumeration | Low | Medium | Cross-check against SHOW TABLES; surface any prod tables not registered |

### §4.5 Rollback plan

- Revert PR if Appendix A wrong.
- Original canonical_ddl.md recoverable from `archive/docs/`.

### §4.6 Code session prompt draft

```
Session: phase-c1-ddl-fold

Mode: Doc regen + fold + archive. Single PR.

Working dir: ~/ClaudeWorkspace/Projects/13f-ownership
Base: main (post phase-b2; can run parallel with C2)
Branch: phase-c1-ddl-fold

Hard scope:
- DO NOT modify any script. DO NOT write to DB.
- DO NOT change data_layers.md body content (only append Appendix A).
- DO NOT modify any tracker doc.

Phase 1 — Verify start
1. git status clean
2. HEAD post-B2
3. duckdb data/13f.duckdb read-only accessible

Phase 2 — Enumerate tables (from DATASET_REGISTRY + SHOW TABLES cross-check)

2.1 — Read DATASET_REGISTRY as authoritative source:
> python -c "from scripts.pipeline.registry import DATASET_REGISTRY; print(sorted(DATASET_REGISTRY.keys()))"

This gives the canonical table list. DATASET_REGISTRY is the single source of truth (used by reference_tables(), merge_table_keys(), unclassified_tables()).

2.2 — Cross-check against prod:
> duckdb data/13f.duckdb --readonly -c "SHOW TABLES" | grep -v "_snapshot_" | sort

2.3 — Reconcile the two lists:
- In REGISTRY AND in prod → generate Appendix A entry (primary scope)
- In REGISTRY NOT in prod → flag as retire-candidate or not-yet-created; include in Appendix A with status note
- In prod NOT in REGISTRY → flag as registry gap (pre-existing issue; note in Appendix A for later resolution)

2.4 — Read canonical_ddl.md for migration-history color only (not for table enumeration):
> cat docs/canonical_ddl.md
Extract any migration-history narrative / commentary worth preserving in Appendix A.2.

Phase 3 — Generate DDL per table from prod
For each table in the reconciled enumeration (Phase 2):
> duckdb data/13f.duckdb --readonly -c "
  SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
  WHERE table_name = '<table>'
  ORDER BY ordinal_position;
"

> duckdb data/13f.duckdb --readonly -c "
  SELECT constraint_name, constraint_type
  FROM information_schema.table_constraints
  WHERE table_name = '<table>';
"

> duckdb data/13f.duckdb --readonly -c "SELECT COUNT(*) FROM <table>;"

Compose CREATE TABLE statement from prod.

Record per table: name, col count, row count, PK.

Phase 4 — Generate migration history
> duckdb data/13f.duckdb --readonly -c "SELECT * FROM schema_versions ORDER BY version;"
> ls scripts/migrations/

Cross-reference: version → file → description. Flag any gap.

Phase 5 — Compose Appendix A in data_layers.md
Insert `## Appendix A: Canonical DDL` at end of docs/data_layers.md:
- Lead paragraph: "This appendix was folded in from docs/canonical_ddl.md on <SESSION_DATE>. DDL regenerated from prod information_schema at time of fold. Table enumeration from DATASET_REGISTRY cross-checked against SHOW TABLES. For updates, regenerate via Phase C1's queries against live prod."
- Per table: section `### <table_name>` with row count, CREATE TABLE DDL block
- If table is REGISTRY-only or prod-only: flag with status annotation in section header
- `## Appendix A.2: Migration History`: table of version | applied_at | description | file

Phase 6 — Archive canonical_ddl.md
> git mv docs/canonical_ddl.md archive/docs/canonical_ddl.md

Create pointer stub at docs/canonical_ddl.md:
```
# Canonical DDL — Moved
This file was folded into `docs/data_layers.md` (Appendix A) on <SESSION_DATE>.
Archived original: `archive/docs/canonical_ddl.md`.
Current prod DDL is generated from `information_schema`; see Appendix A.
```

Phase 7 — Update inbound refs
> grep -rn "canonical_ddl" docs/ scripts/ tests/ *.md --include="*.md" --include="*.py"
Exclude archive/docs/ (historical; leave alone).
For each active hit:
- General concept → "data_layers.md Appendix A"
- Specific section → map to data_layers.md Appendix A equivalent

Phase 8 — Verify
1. data_layers.md Appendix A covers all DATASET_REGISTRY entries + all prod tables (or flags their status)
2. No broken inbound refs from active docs
3. archive/docs/canonical_ddl.md has original content
4. Pointer stub at old path
5. Column count deltas recorded vs audit claims (V6 said doc=33 for holdings_v2; fresh prod regen is 38)

Phase 9 — PR + merge confirmation
Title: `phase-c1-ddl-fold: regen canonical DDL from prod (DATASET_REGISTRY-driven) into data_layers.md Appendix A`
Body:
- Tables covered (by source: REGISTRY ∩ prod, REGISTRY only, prod only)
- Column-count deltas vs prior doc
- Inbound ref count updated

Git lifecycle: same as B1 (ask Serge before merge).

Output: Summary per category.

Out of scope: table redesign, data_layers.md body changes, DB writes, script changes.
DO NOT use --no-verify. DO NOT force push.
```

---

## §5 — Phase B2.5: V2 cutover

**Session name:** `phase-b2-5-v2-cutover`.
**Estimated duration:** 90-150 min (includes real fixture smoke per plan-review-v3 M4).
**Risk level:** Medium-high (changes scheduled production path).
**Must land:** before Q1 2026 13F cycle begins (~May 15).

### §5.1 Rationale

Validation V-Q1 confirmed V2's code path is equivalent to admin-refresh path (which has been running V2 on live data for months). But V2 is **not yet wired into the scheduled cycle** — `Makefile:111` still invokes V1, and `Makefile:80-100` `quarterly-update` target calls `$(MAKE) load-13f` without passing `QUARTER=`. To make the B3 2-cycle gate observable (Q1+Q2 cycles run clean on V2), V2 must be the scheduled path before Q1 cycle starts, AND the `quarterly-update` orchestration must pass `QUARTER=` through.

This session performs cutover + orchestration fix + co-lands registry cleanups in one PR.

### §5.2 Scope

**Cutover edits:**

1. `Makefile:111` (V1 invocation) — swap to V2:
   - Current: `$(PY) $(SCRIPTS)/load_13f.py $(if $(QUARTER),--quarter $(QUARTER),)`
   - Replace with: `$(PY) $(SCRIPTS)/load_13f_v2.py --quarter $(QUARTER) --auto-approve`

2. `Makefile:80-100` (`quarterly-update` target orchestration) — ensure `QUARTER=` passes through to `load-13f`:
   - Currently `quarterly-update` calls `$(MAKE) load-13f` without `QUARTER=`
   - V2 requires `--quarter`, so this would crash post-cutover
   - Fix: require `QUARTER=` at `quarterly-update` invocation, pass through to `load-13f`
   - Update `make help` text (currently says "QUARTER=YYYYQn optional") to reflect new requirement

3. `scripts/update.py:74` (load_13f.py entry in steps list) — replace V1 reference:
   - V2 invocation pattern (with --quarter and --auto-approve)

4. `scripts/benchmark.py:20` (benchmark matrix) — swap V1 entry to V2.

5. `scripts/build_managers.py` — TWO references to `load_13f.py` per plan-review-v3 R4:
   - L12: module docstring "(Requires pipeline/load_adv.py and load_13f.py to have run first)" — update to `load_13f_v2.py`
   - L228: upstream tuple `("filings_deduped", "load_13f.py")` — update to `load_13f_v2.py`

**Co-land registry owner updates (solve-once principle):**

6. `scripts/pipeline/registry.py:113` (`filings` spec): `owner="scripts/load_13f.py"` → `owner="scripts/load_13f_v2.py"`

7. `scripts/pipeline/registry.py:118` (`filings_deduped` spec): `owner="scripts/load_13f.py"` → `owner="scripts/load_13f_v2.py"`

8. `scripts/pipeline/registry.py:175` (`other_managers` spec) — **new in v4 per plan-review-v3 R1**: `owner="scripts/load_13f.py"` → `owner="scripts/load_13f_v2.py"` (V2 writes this table at load_13f_v2.py:719)

**Leave raw_* registry specs alone** — they're dropped entirely in B3, not re-owned.

**Documentation updates:**

9. `docs/data_layers.md` Appendix A: note V2 as the active loader (if C1 has shipped; otherwise C1 regen picks this up).

10. `docs/data_sources.md` / `docs/pipeline_inventory.md`: update load_13f refs to load_13f_v2.

11. `NEXT_SESSION_CONTEXT.md`: document cutover date + watch items for Q1 cycle.

**Full-reload caveat:** V2 requires `--quarter` per invocation. Document in MAINTENANCE.md:
- Under "Quarterly Cycle": "V2 requires --quarter per invocation; no full-reload mode. To reload multiple quarters, loop: `for q in 2025Q1 2025Q2 2025Q3 2025Q4; do make load-13f QUARTER=$q; done`"

### §5.3 Gating condition (before starting)

- Phase B2 PR merged.
- CI green.
- No 13F cycle in flight.
- Calendar: session complete + CI verify before Q1 2026 cycle starts.

### §5.4 Gating condition (after completing)

Tightened per plan-review-v3 R5 — explicit allowed-files list:

- PR merged.
- CI green.
- `grep -rn "\bload_13f\.py\b" Makefile scripts/ .github/` returns ONLY these specific files/lines:
  - `scripts/load_13f.py` itself (the file that owns the name)
  - `scripts/load_13f_v2.py` (may mention V1 in docstrings/comments documenting the transition)
  - `MAINTENANCE.md` (full-reload caveat section may reference historical V1)
  - `NEXT_SESSION_CONTEXT.md` (cutover record references V1)
  - `archive/docs/` (historical; not an issue)
  - Any other match = regression. STOP and investigate.
- `grep -rn "\bload_13f\b" Makefile scripts/update.py scripts/benchmark.py scripts/scheduler.py .github/ | grep -v "load_13f_v2"` returns ZERO hits.
- Makefile dry-run test: `make -n quarterly-update QUARTER=2025Q4` expands to V2 invocation.
- Fixture smoke test: actual `python scripts/load_13f_v2.py --quarter 2025Q4 --auto-approve` run against `tests/fixtures/13f_fixture.duckdb` (or equivalent fixture) — completes without error, writes to staging, promotes to prod tables on approve.
- `pytest tests/pipeline/test_load_13f_v2.py -v` green.
- `pytest tests/test_admin_refresh_endpoints.py -v` green (covers admin path unchanged).
- Worktree cleanup run.

### §5.5 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| V2 fails on live Q1 data (edge case not in admin refresh) | Low | HIGH | git revert restores V1 in Makefile; single-line change |
| Makefile syntax error breaks Make target surface | Low | HIGH | `make -n` dry-run test before PR push |
| quarterly-update orchestration wrong (QUARTER not passed) | Medium (currently broken) | HIGH | Explicit fix + dry-run verification |
| update.py invocation pattern wrong | Medium | Medium | Diff V1 and V2 invocations; pick pattern with evidence |
| registry.py owner updates break downstream consumer | Very low | Low | owner field is advisory text; not hard-parsed as module path |
| Full-reload mode needed post-cutover | Low | Medium | Documented manual loop; operator has tool |
| Fixture smoke doesn't catch a real-data edge case | Medium | Medium | Q1 cycle is the real test; fallback is git revert |

### §5.6 Rollback plan

- `git revert` on PR restores V1 in Makefile + update.py + benchmark + build_managers + registry owners (filings, filings_deduped, other_managers) in one revert.
- V1 script physically remains at `scripts/load_13f.py` until B3 — revert is complete restoration.
- If issue surfaces mid-Q1 cycle: revert + re-run cycle on V1 + open investigation.

### §5.7 Code session prompt draft

```
Session: phase-b2-5-v2-cutover

Mode: V2 cutover — Makefile orchestration fix + cycle-path script updates + registry owner updates. Single PR. Critical path change.

Working dir: ~/ClaudeWorkspace/Projects/13f-ownership
Base: main (post phase-b2)
Branch: phase-b2-5-v2-cutover

Hard scope:
- DO NOT retire scripts/load_13f.py (that's B3)
- DO NOT drop any table (B3)
- DO NOT modify V1 or V2 script content
- DO NOT merge without Serge confirmation

Phase 1 — Verify start
1. git status clean
2. HEAD post-B2
3. scripts/load_13f.py exists at scripts/ (not retired yet)
4. scripts/load_13f_v2.py exists
5. No 13F cycle in flight: check scripts/logs/ for recent pipeline activity; if cycle active, STOP and wait

Phase 2 — Pre-cutover verification

2.1 — Verify V2's admin refresh equivalence on real invocation:
> python -c "from scripts.pipeline.pipelines import get_pipeline; p = get_pipeline('13f_holdings'); print(p, p.__class__, p.__module__)"
Expect: Load13FPipeline from load_13f_v2

2.2 — Enumerate every V1 reference in scheduled paths + metadata:
> grep -rn "\bload_13f\.py\b\|\bload_13f\b" Makefile scripts/update.py scripts/benchmark.py scripts/scheduler.py scripts/build_managers.py scripts/pipeline/registry.py .github/
Document each hit with context + classification (cutover / co-land / leave-alone).

2.3 — Review V2's __main__ / CLI surface:
> tail -100 scripts/load_13f_v2.py
Confirm: --quarter required, --auto-approve flag chains run → approve_and_promote.

Phase 3 — Execute cutover edits

3.1 — Makefile:111 (load-13f target):
Current V1 line: `$(PY) $(SCRIPTS)/load_13f.py $(if $(QUARTER),--quarter $(QUARTER),)`
Replace with: `$(PY) $(SCRIPTS)/load_13f_v2.py --quarter $(QUARTER) --auto-approve`

3.2 — Makefile quarterly-update target (L80-100, verify exact line):
Currently calls $(MAKE) load-13f without QUARTER=.
Fix: require QUARTER= at quarterly-update invocation, pass through.
Example pattern:
```
quarterly-update:
ifndef QUARTER
	$(error QUARTER is required. Usage: make quarterly-update QUARTER=2025Q4)
endif
	$(MAKE) load-13f QUARTER=$(QUARTER)
	[... other pipeline steps ...]
```
Update `make help` text: remove "(optional)" from QUARTER description for quarterly-update + load-13f.

3.3 — scripts/update.py:74 (load_13f.py entry in steps list):
Replace V1 entry with V2 equivalent. Match V2's invocation requirements.

3.4 — scripts/benchmark.py:20 (benchmark matrix):
Replace V1 entry with V2 equivalent.

3.5 — scripts/build_managers.py — TWO refs:
L12 (module docstring): "(Requires pipeline/load_adv.py and load_13f.py to have run first)" → replace load_13f.py with load_13f_v2.py
L228 (upstream tuple): `("filings_deduped", "load_13f.py"),` → `("filings_deduped", "load_13f_v2.py"),`

3.6 — scripts/pipeline/registry.py — THREE owner updates:
Line 113 (filings spec): owner="scripts/load_13f.py" → owner="scripts/load_13f_v2.py"
Line 118 (filings_deduped spec): same update
Line 175 (other_managers spec): same update (V2 writes this table at load_13f_v2.py:719)
Leave raw_* L1 specs (L68-82) alone — B3 handles those.

Phase 4 — Documentation updates

4.1 — MAINTENANCE.md: add "Full reload" subsection under Quarterly Cycle:
"V2 requires --quarter per invocation; no full-reload mode. To reload historical quarters, loop:
  for q in 2025Q1 2025Q2 2025Q3 2025Q4; do
    make load-13f QUARTER=$q
  done"

4.2 — NEXT_SESSION_CONTEXT.md: append cutover record:
"[<SESSION_DATE>] V2 cutover complete. Scheduled cycle runs load_13f_v2.py. V1 remains at scripts/load_13f.py as break-glass until B3 (2-cycle gate Aug 2026). Watch Q1 cycle for any novel filing patterns V1 handled silently that V2 doesn't."

4.3 — docs/data_sources.md / docs/pipeline_inventory.md: update load_13f refs.

4.4 — If C1 shipped: update data_layers.md Appendix A 13F provenance. If not: note in PR body.

Phase 5 — Smoke tests (dry-run + fixture)

5.1 — Makefile dry-run:
> make -n quarterly-update QUARTER=2025Q4
Verify expansion uses load_13f_v2.py.

> make -n load-13f QUARTER=2025Q4
Verify expansion uses load_13f_v2.py with --auto-approve.

5.2 — Fixture smoke (REAL execution, not dry-run):
> python scripts/load_13f_v2.py --quarter 2025Q4 --auto-approve
Against test fixture DB (tests/fixtures/13f_fixture.duckdb or equivalent).
Verify: writes to staging, promotes to prod tables, no errors, exit code 0.

5.3 — Test suite:
> pytest tests/pipeline/test_load_13f_v2.py -v
> pytest tests/test_admin_refresh_endpoints.py -v
All green.

5.4 — Grep gate (tightened per plan-review-v3 R5):
> grep -rn "\bload_13f\.py\b" Makefile scripts/ .github/ | grep -v "load_13f_v2"
Expected matches ONLY in:
- scripts/load_13f.py itself
- scripts/load_13f_v2.py (docstrings/comments documenting transition)
- MAINTENANCE.md (full-reload caveat)
- NEXT_SESSION_CONTEXT.md (cutover record)
Any other match = regression. STOP, investigate, fix.

> grep -rn "\bload_13f\b" Makefile scripts/update.py scripts/benchmark.py scripts/scheduler.py .github/ | grep -v "load_13f_v2"
Expected: ZERO hits.

Phase 6 — PR + merge confirmation
Title: `phase-b2-5-v2-cutover: swap scheduled path V1→V2 + quarterly-update fix + 3 registry owner updates`
Body:
- Every file edited with diff context
- Makefile dry-run output
- Fixture smoke output (real run, not dry)
- V1 remaining references (should be: V1 script itself, transition docstrings, caveat docs, session-context record)
- Rollback plan: single git revert

Git lifecycle: same as B1 (ask Serge before merge).

Output: Summary of cutover state.

Out of scope:
- Retiring scripts/load_13f.py (B3)
- Dropping any table (B3)
- Modifying V1 or V2 script content
- Changing raw_* registry entries (B3)

DO NOT use --no-verify. DO NOT force push.
```

---

## §6 — Phase C2: Tracker consolidation + ops-18 investigation

**Session name:** `phase-c2-tracker-consolidate`.
**Estimated duration:** 90-150 min.
**Risk level:** Low-medium.

### §6.1 Scope

**Post-B1 state:** REMEDIATION_CHECKLIST.md archived. Active trackers:
- ROADMAP.md
- REMEDIATION_PLAN.md
- DEFERRED_FOLLOWUPS.md
- NEXT_SESSION_CONTEXT.md

**Decisions:**

1. Keep DEFERRED_FOLLOWUPS.md and NEXT_SESSION_CONTEXT.md separate (Option B). Document source-of-truth rule.
2. Add 4 undocumented pipeline modules to pipeline_inventory.md (V9).
3. Consolidated backlog view in ROADMAP.md.
4. Document source-of-truth rules for every tracker category.
5. ops-18 investigation — investigate with prior-knowledge framing from REMEDIATION_PLAN.md.

### §6.2 ops-18 investigation — prior-knowledge framing

Plan-review-v2 R5: REMEDIATION_PLAN.md L208/253/446/595/603/606 already documents ops-18 as a missing-file problem. Investigation should not re-discover this via grep; it should start from the known prior.

**Revised investigation approach:**

Step 0: Read REMEDIATION_PLAN.md at the cited line numbers. Confirm ops-18 has been tracked as a missing FILE (`rotating_audit_schedule.md`) since 2026-04-20 initial consolidation.

Step 1: Frame investigation around: "was the rotating-audit *concept* written down elsewhere — design notes, prompts, pre-program scratch files, archived docs, git history predating remediation?"

Step 2: Search archived docs + current docs:
> grep -rn "rotating" archive/docs/ docs/ --include="*.md"

Step 3: Git log (deep):
> git log --all --grep="rotating" -p
> git log --all --grep="ops-18" -p

Step 4: Check pre-consolidation files:
> git log --all --before="2026-04-20" -- "*.md" | grep -i rotating

Step 5: Outcome classification:
- RECOVERABLE: concept found. Summarize + add to backlog with recovered context.
- PARTIAL: some intent known, details missing. Document what's known + flag gaps.
- INCONCLUSIVE: close as ambiguous with closure note. Serge may re-open.

In no case close silently. Always cite investigation findings in PR body.

### §6.3 Additional scope

**Pipeline inventory (V9):**
Add 4 missing modules to `docs/pipeline_inventory.md`:
- scripts/pipeline/protocol.py — ABC for SourcePipeline
- scripts/pipeline/discover.py — PIPELINE_CADENCE probes
- scripts/pipeline/id_allocator.py — centralized impact_id allocator
- scripts/pipeline/cusip_classifier.py — cusip-classifier rules

**Current Backlog section in ROADMAP.md:**
Add `### Current backlog (verified <SESSION_DATE>)` subsection listing 12 confirmed-open items (per v2 §5.6 Phase 3, see §9 of this plan for canonical list).

**Source-of-truth rules in SESSION_GUIDELINES.md:**
Append section documenting which tracker owns which category:
- Forward work → ROADMAP.md Current backlog + DEFERRED_FOLLOWUPS.md (multi-session)
- Single-session handoff → NEXT_SESSION_CONTEXT.md
- Remediation narrative → REMEDIATION_PLAN.md
- Per-session closures → docs/closures/*.md (Pattern B)
- Frozen closure log → ROADMAP.md §Closed items (log)
- Per-session findings → docs/findings/
- Rule: closing an item requires updating every tracker that references it. Run `scripts/hygiene/audit_tracker_staleness.py` if in doubt.

### §6.4 Gating + risk + rollback + prompt

[Structure per v3; ops-18 Phase 5 updated per §6.2 above. Prompt follows same git lifecycle rule — ask Serge before merge.]

---

## §7 — Phase B3: DB cleanup + legacy retire (single combined session)

**Session name:** `phase-b3-db-cleanup`.
**Estimated duration:** 120-180 min.
**Risk level:** Low after 2-cycle gate (high without).
**Gate:** Q1 + Q2 2026 13F cycles both run clean on V2 scheduled path (~Aug 2026).

### §7.1 Rationale for combined session

Plan review R4 recommended split. Rejected because:

1. No new safety from split. V1 validated as having no readers (V1 + V2 of verification). 2 clean cycles validate V2 correctness. Split adds calendar delay without finding new readers.

2. Pre-drop snapshots are the real safety net. Calendar delay doesn't improve snapshot coverage.

3. Split creates window of drift. Between B3a and B3b, V1 retired but raw_* still exist. Registry would be actively misleading.

4. Combined PR is also one revert. Same recoverability as split.

The 2-cycle gate is the delay that matters.

### §7.2 Scope (co-land everything)

**Code retirement:**
1. Verify B2.5 cleanups held (update.py, Makefile, benchmark.py, build_managers.py L12+L228, registry filings/filings_deduped/other_managers owners).
2. Remove `scripts/load_13f.py` references from `scripts/pipeline/registry.py` raw_* owner fields (being dropped in same PR).
3. `git mv scripts/load_13f.py scripts/retired/`

**DB drops with pre-drop snapshots:**
4. `CREATE TABLE raw_submissions_snapshot_<TIMESTAMP> AS SELECT * FROM raw_submissions; DROP TABLE raw_submissions;`
5. Same for `raw_infotable`, `raw_coverpage`.
6. `CREATE TABLE fund_holdings_snapshot_<TIMESTAMP> AS SELECT * FROM fund_holdings; DROP TABLE fund_holdings;`

**Co-land cleanups (per validation V-Q3):**
7. `scripts/db.py:82-86 REFERENCE_TABLES` — remove `fund_holdings` entry.
8. `scripts/pipeline/registry.py` — remove 3 raw_* L1 DatasetSpec entries (L68-82).
9. `scripts/pipeline/registry.py:346` — refresh `fund_holdings` docstring comment.
10. `notebooks/research.ipynb:586-589` — update dead-branch probe to `fund_holdings_v2` OR delete.

**Co-land cosmetic cleanups (per plan-review-v3 M3):**
11. `scripts/queries.py` — update stale `fund_holdings` prose comments at L264/L356/L571/L2092/L2355/L2691/L2940/L3034 to reference `fund_holdings_v2` (verified by plan-review-v3: all SQL already targets `_v2`; comments are stale terminology only).

**Doc updates:**
12. `docs/data_layers.md` Appendix A — remove dropped tables; note drop date.
13. `ROADMAP.md` Closed log — add B3 entry.
14. `REMEDIATION_PLAN.md` — add drop note where raw_* or fund_holdings referenced.
15. `NEXT_SESSION_CONTEXT.md` — document drop + removed artifacts.
16. `MAINTENANCE.md` — remove any reference to dropped tables.

### §7.3 Gating condition (before starting)

- Q1 2026 AND Q2 2026 cycles both ran cleanly on V2 (verified via pipeline logs + freshness records).
- Phase B1, B2, B2.5, C1, C2 all merged.
- Backup taken within 24 hours (`scripts/backup_db.py --confirm`).
- Prod DB not in active use.

### §7.4 Gating condition (after completing)

- PR merged.
- CI green.
- All 4 tables have confirmed snapshots (timestamped, non-empty).
- `grep -rn "load_13f.py\|raw_infotable\|raw_coverpage\|raw_submissions" scripts/ Makefile .github/` returns only archived/retired references.
- Smoke: app starts, loads register tab, no errors.
- `duckdb data/13f.duckdb --readonly -c "SHOW TABLES;" | grep -E "^raw_|^fund_holdings$"` returns only snapshot tables (if any).
- Worktree cleanup run.

### §7.5 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| V2 had silent issue in Q1+Q2 not caught | Very low (gate validates) | HIGH | 2-cycle gate; halt + fix if issue surfaces |
| Dropped table had forgotten reader | Very low | HIGH | Pre-drop snapshot; V-Q3 cleared all readers |
| Snapshot creation fails silently | Low | CRITICAL | Script checks row count matches source before DROP |
| Concurrent app/session writing during drop | Medium | HIGH | Explicit pre-check: no app, no other session |
| Notebook probe update changes git-tracked state unexpectedly | Low | Low | Surgical diff confirmation |

### §7.6 Rollback plan

- Snapshots restore all dropped tables.
- `git revert` restores V1 + all caller references.
- Combined rollback: one `git revert` + 4 SQL restore statements.

### §7.7 Code session prompt draft

Deferred — drafted when gate approaches (Aug 2026). Current draft structural only; concrete prompt needs post-cycle state.

---

## §8 — Small one-offs (tracked, not phased)

### §8.1 `fetch-finra-short-dry-run`

Add `--dry-run` / `--apply` to `scripts/fetch_finra_short.py`. V5 gap. Very low risk.

### §8.2 `audit-ticket-numbers-refinement-v10`

Refine `scripts/hygiene/audit_ticket_numbers.py` grouped-row handling for V10's `| DM2 / DM3 / DM6 |` false positive. Fix in `line_kind()` or `extract_table_title()` — detect multi-ticket lead cells.

**Independent from B1's INF40 mitigations** (R1 correction; different code paths).

Very low risk.

### §8.3 `snapshot-retention-policy`

Define retention for 292 snapshots across 15 tables (V8). Requires Serge policy decision.

### §8.4 `registry-gap-sweep`

Add DATASET_REGISTRY entries for 4 active tables surfaced by C1 registry-gap triage:

- `_cache_openfigi` (CUSIP v1.4 OpenFIGI cache; writers: `build_cusip.py`, `run_openfigi_retry.py`; readers: `build_cusip.py` and one-offs)
- `admin_sessions` (admin app session store; writers/readers: `admin_bp.py`)
- `cusip_classifications` (CUSIP/ticker classification pipeline output; readers include `enrich_holdings.py`)
- `cusip_retry_queue` (OpenFIGI retry pipeline queue state)

Each entry requires a small design call: layer tag (L0/L1/L2), lifecycle classification (cache vs pipeline output vs queue vs app state), owner, downstream, notes. Scope-boundary question for REGISTRY is in play — app-state tables like `admin_sessions` may or may not belong.

Session scope: design decision per table, then add `DatasetSpec` entries in one PR. Not gating B3. Dispatched as a dedicated session after C2.

Low-medium risk. ~45-60 min.

---

## §9 — Still-open real backlog

| ID | Description | Status | Priority | Gate |
|---|---|---|---|---|
| int-09 Step 4 / INF25 | BLOCK-DENORM-RETIREMENT | Unblocked | Medium | Architectural design Q2 2026 |
| INF38 / int-19 | BLOCK-FLOAT-HISTORY | Deferred | Low | Float-history data source |
| ops-18 | restore rotating_audit_schedule.md | Phase C2 investigation | Unclear | Per C2 outcome |
| INF27 | CUSIP residual-coverage | Standing | N/A | Auto-handled |
| INF2 | monthly maintenance | Recurring | Ops | Monthly |
| INF16 | recompute managers.aum_total | Open | Low | None |
| 43g | drop redundant type columns | Open | Medium | None |
| 43b | app.py remaining hardening | Open | Low | None |
| 48 | Phase 3.5 deferred items | Partial | Medium | Per-D decisions |
| 56 | DM worldviews | Not started | Medium | DM Tier 2 |
| P2-FU-01 | run_script allowlist prune | Open | Ops | 2 clean cycles |
| P2-FU-03 | ADV SCD Type 2 | Deferred | Low | Design decision |

---

## §10 — Standing git lifecycle rule

All Phase sessions (B1, B2, B2.5, C1, C2, B3) follow this git lifecycle:

1. Code stages, commits, pushes to branch, opens PR.
2. Code waits for CI green.
3. Code asks Serge: "PR #N CI green. Merge?"
4. Serge replies yes / no / adjust.
5. On yes: Code merges, deletes branch, cleans worktree, closes session.
6. On no or adjust: Code addresses per Serge's instruction, re-pushes, re-asks.
7. Code NEVER merges without explicit Serge confirmation.
8. Code NEVER uses `--no-verify` or force push.

Manual merge from Terminal still permitted — if Serge merges via `gh pr merge` from Terminal, Code proceeds to cleanup + close.

**Exception — destructive DDL sessions (B3):** Code always asks before executing any DROP statement, regardless of merge state. Each DROP is confirmed independently.

---

## §11 — Plan change log

- 2026-04-23 v1 — initial draft post-verification
- 2026-04-23 v2 — Serge Q1-Q5 answers
- 2026-04-23 v3 — validation + plan review + Q4 revert + Phase B2.5 + §4 C1 fresh
- 2026-04-23 v4 — plan-review-v3 findings (C1 critical, R1-R5, M1-M4) + Q1/Q2 decisions (sequential + DATASET_REGISTRY)

---

## §12 — Plan adoption

This plan (v4) is adopted when committed to main. No further review sessions scheduled — v3 review findings are fully incorporated; v4 is the final plan before execution.

Phase B1 starts after v4 on main + new chat opened.
