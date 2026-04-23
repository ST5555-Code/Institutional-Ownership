# Phase B / Phase C Execution Plan — 2026-04-23

**Status:** DRAFT v3 — incorporates validation findings + plan review + Serge refinements. Awaiting final Code review before adoption.
**Target location on merge:** `docs/plans/2026-04-23-phase-b-c-execution-plan.md`.
**Inputs:**
- `docs/findings/comprehensive-audit-2026-04-23.md` (Phase A)
- `docs/findings/pre-phase-b-verification-2026-04-23.md` (verification)
- `docs/findings/plan-review-2026-04-23.md` (v2 critique)
- `docs/findings/refinement-validation-2026-04-23.md` (v3 refinement validation)

**v3 changes from v2:**
- Added Phase B2.5 (V2 cutover) — addresses C1 from plan review
- Rewrote §4 (Phase C1) fresh from primary sources — addresses C2 from plan review
- Q4 reverted per validation — migrate_batch_3a.py moves to oneoff/, registry owner → "manual"
- Co-landing requirements named explicitly in Phase B2.5 and Phase B3 (per validation)
- INF40 mitigation 2 decoupled from V10 fix (R1)
- Oneoff list framing clarified: V7 rules applied to full set, not V7's 6-name sample (R3)
- B3 stays combined; split rejected — rationale documented (R4 response)
- ops-18 prompt reframed around missing-file context (R5)
- Dynamic session date throughout prompts (R6 + M1)
- §0 "count or metric" replaces ambiguous "number" (M3)
- B2 risk mitigation names `registry.py owner=` as checked location (M2)

---

## §0 — Purpose and boundaries

The comprehensive audit plus pre-Phase-B verification plus refinement validation produced a set of actions, Serge decisions, and a validated execution sequence. This document translates them into discrete batches with gating, rollback, and per-batch Code session drafts.

**Hard rules this plan respects:**

- Every batch is single-session, single-PR, file-disjoint from other batches in-flight.
- Every batch has a documented gate before the next batch starts.
- Risk-ordered execution: lowest-risk first, DB drops last.
- No batch acts on any count or metric pulled from the audit without verifying it live. V6 demonstrated the audit's own numbers can be wrong.
- Plan-level meta-fixes (like this plan itself) ship solo — no parallel execution with substantive work.
- **Solve once:** every operational change co-lands its own metadata/reference cleanups in the same PR. No "we'll fix registry/references in the next phase" deferral.

**Out of scope:**

- PR #107 ui-audit walkthrough (separate track)
- Q1 2026 13F cycle execution (Tier 1, calendar-gated)
- DM Tier 2 work, Tier 3 architectural design
- Any Tier 6 item not surfaced by the audit + verification + validation

---

## §1 — Master sequence

```
┌─────────────────────────────────────────────────┐
│ Plan final review (this v3)                     │
│ → Plan PR merged                                │
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
│ Must land BEFORE Q1 2026 cycle starts           │
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
`audit_ticket_numbers.py` detects bracketed-annotation pattern `[INF<N> #M of K]` as canonical disambiguation. **This is independent from V10 grouped-row fix** (which lives in `line_kind()` / `extract_table_title()` — §7.2 scope).

**Mitigation 3 — REVIEW_CHECKLIST.md explicit note**
Add section documenting INF40 exception + prohibition against re-issuing it.

### §2.2 Gating condition (before starting)

- Main clean.
- No Code sessions in flight on these files.
- Phase A (PR #134), verification (PR #135), plan review (PR #136), validation (PR #137) all merged to main OR known-stable reference PRs.
- This plan PR merged.

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
| INF40 classifier refactor larger than expected | Low | Low | Prompt escape hatch — if >35 LOC needed, STOP and defer to §7.2 |

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
2. HEAD includes plan PR
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
- Note: this is INDEPENDENT of V10 grouped-row fix (§7.2). Do not try to fix V10 here.

If combined M1+M2 exceed 35 LOC OR require structural refactor beyond additions, STOP and surface. Defer M2 to §7.2.

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

Phase 10 — PR
Title: `phase-b1-doc-hygiene`
Body: describe changes, cite audit + verification + validation.

Output: PR pushed, CI green, not merged. Summary of files moved, refs updated, checkboxes flipped, INF40 status.

Out of scope: anything beyond the 3 flips + ROADMAP INF40 + REVIEW_CHECKLIST note + audit_ticket_numbers.py (mitigations 1+2 only) + 8 archivals.

DO NOT use --no-verify. DO NOT force push.
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

**For `migrate_batch_3a.py`:** co-land registry owner update. `scripts/pipeline/registry.py:295` — change `owner="scripts/migrate_batch_3a.py"` → `owner="manual"`. Matches the script's actual nature (one-shot seeder, never re-run, DB rows bit-identical to in-code seed). This eliminates a false "live owner" signal that could tempt a future re-run to silently wipe manual edits.

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
- Change owner="scripts/migrate_batch_3a.py" → owner="manual"
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

Phase 7 — PR
Title: `phase-b2-script-reorg: 11 oneoffs + 6 hygiene + 2 retire + registry owner update`
Body: per-script table, diff, test output, rationale for oneoff expansion (V7 rules applied to full set).

Output: PR pushed, CI green, not merged.

Out of scope: script logic, load_13f.*, new scripts/tests, DB operations, merge.

DO NOT use --no-verify. DO NOT force push.
```

---

## §4 — Phase C1: Canonical DDL fold

**Session name:** `phase-c1-ddl-fold`.
**Estimated duration:** 60-120 min.
**Risk level:** Low (doc-only, but scope-up per V6).

### §4.1 Scope

**Rationale (per V6):** canonical_ddl.md's column counts are stale — doc claims holdings_v2=33, actual prod is 38. Drift is +5 on holdings_v2, +4 on fund_holdings_v2, +6 on beneficial_ownership_v2. A regen from doc content forward would inherit the staleness. Correct approach: regenerate DDL from prod `information_schema` fresh, then fold into data_layers.md.

**Generate fresh DDL from prod for every table canonical_ddl.md covers.** Approach:

1. Enumerate tables in canonical_ddl.md's scope (cross-reference against prod `SHOW TABLES`)
2. For each: query `information_schema.columns` for column list + types + nullability
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

**Update all inbound references** (scope: whatever grep surfaces — audit found 20, may be more or fewer after B1+B2 archivals):
- Replace paths to `docs/canonical_ddl.md` with paths to `docs/data_layers.md#appendix-a-canonical-ddl` or equivalent section reference
- Leave references inside archived docs untouched (those are historical)

### §4.2 Gating condition (before starting)

- Phase B2 PR merged.
- CI green.
- Can run parallel with Phase C2 (different file sets).

### §4.3 Gating condition (after completing)

- PR merged.
- CI green.
- `data_layers.md` Appendix A contains every table canonical_ddl.md covered (100% overlap, verified via comparison).
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
| Audit's stale +3/+0/+6 counts propagate into v3 | Low | Low | Regen is from prod, not from audit — audit counts are never inputs |

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

Phase 2 — Enumerate canonical_ddl.md's table scope
> grep "^### " docs/canonical_ddl.md
Extract the list of tables documented. Cross-check against:
> duckdb data/13f.duckdb --readonly -c "SHOW TABLES" | grep -v snapshot_

Note any table in canonical_ddl.md not in prod (likely dropped; document that)
Note any table in prod not in canonical_ddl.md (gap; include in Appendix A)

Phase 3 — Generate DDL per table from prod
For each in-scope table:
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

Phase 5 — Compose Appendix A
Insert `## Appendix A: Canonical DDL` at end of docs/data_layers.md:
- Lead paragraph: "This appendix was folded in from docs/canonical_ddl.md on <SESSION_DATE>. DDL regenerated from prod information_schema at the time of the fold. For updates, regenerate via Phase C1's queries against live prod."
- Per table: section `### <table_name>` with row count, CREATE TABLE DDL block
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
1. data_layers.md Appendix A covers all canonical_ddl.md tables (100% overlap)
2. No broken inbound refs from active docs
3. archive/docs/canonical_ddl.md has original content
4. Pointer stub at old path
5. Column count deltas recorded vs audit claims (V6 said doc=33 for holdings_v2; fresh prod regen is 38)

Phase 9 — PR
Title: `phase-c1-ddl-fold: regen canonical DDL from prod into data_layers.md Appendix A`
Body: tables covered, column-count deltas vs prior doc, inbound ref count updated.

Output: PR pushed, CI green, not merged.

Out of scope: table redesign, data_layers.md body changes, DB writes, script changes, merge.

DO NOT use --no-verify. DO NOT force push.
```

---

## §5 — Phase B2.5: V2 cutover (new in v3)

**Session name:** `phase-b2-5-v2-cutover`.
**Estimated duration:** 60-120 min.
**Risk level:** Medium-high (changes scheduled production path).
**Must land:** before Q1 2026 13F cycle begins.

### §5.1 Rationale

Validation V-Q1 confirmed V2's code path is equivalent to admin-refresh path (which has been running V2 on live data for months). But V2 is **not yet wired into the scheduled cycle** — `Makefile:111` still invokes V1. To make the B3 2-cycle gate observable (Q1+Q2 cycles run clean on V2), V2 must be the scheduled path before Q1 cycle starts.

This session performs that cutover + co-lands registry/reference cleanups in the same PR. No feature flag — the Makefile edit itself is the switch, and it's one-line-revertible via `git revert`.

### §5.2 Scope

**Cutover edits:**

1. `Makefile:111` — swap V1 to V2:
   - Current: `$(PY) $(SCRIPTS)/load_13f.py $(if $(QUARTER),--quarter $(QUARTER),)`
   - Replace with V2 equivalent (note: V2 requires `--quarter`; confirm Makefile always passes one in cycle context)

2. `scripts/update.py:75` — remove or replace `load_13f.py` step:
   - V2 has different invocation pattern (auto-approve flag for cycle context vs admin-refresh's approval gate)
   - Confirm proper invocation

3. `scripts/benchmark.py:20` — update benchmark matrix entry from V1 to V2.

4. `scripts/build_managers.py` upstream-producer comment — update to reference `load_13f_v2.py` (near line 228 per V3, but use semantic match not line number — build_managers may shift by B2.5 time).

**Co-land registry owner updates (solve-once principle):**

5. `scripts/pipeline/registry.py:113` — `filings` spec:
   - Current: `owner="scripts/load_13f.py"`
   - Update to: `owner="scripts/load_13f_v2.py"`

6. `scripts/pipeline/registry.py:118` — `filings_deduped` spec:
   - Current: `owner="scripts/load_13f.py"`
   - Update to: `owner="scripts/load_13f_v2.py"`

**Documentation updates:**

7. `docs/data_layers.md` Appendix A: note V2 as the active loader for 13F path (if Phase C1 has shipped; otherwise this update rides in C1's regen).

8. `docs/data_sources.md` or `docs/pipeline_inventory.md`: any reference to load_13f.py as the active loader.

9. `NEXT_SESSION_CONTEXT.md`: document cutover date + what to watch during Q1 cycle.

**Full-reload caveat:** V2 has no full-reload mode (requires `--quarter` per invocation). Document in MAINTENANCE.md:
- Under "Quarterly Cycle" section
- "To reload historical quarters, operator must loop `make load-13f QUARTER=<q>` per quarter; no single-command full reload."

### §5.3 Gating condition (before starting)

- Phase B2 PR merged (so script locations are stable).
- CI green.
- No 13F cycle in flight (would conflict with cutover).
- **Calendar gate:** session must complete + CI verify before Q1 2026 cycle starts (which would be next regularly-scheduled cycle).

### §5.4 Gating condition (after completing)

- PR merged.
- CI green.
- `grep -rn "load_13f.py" Makefile scripts/` returns only:
  - Reference in `scripts/load_13f.py` itself
  - Reference in `scripts/load_13f_v2.py` docstring/comments
  - Reference in documentation/comments
- No live invocation of V1 in Makefile, scheduler, update, benchmark, or registry owner fields.
- Smoke test: `make load-13f QUARTER=<test-quarter>` runs V2, writes to staging, halts at pending_approval.
- Approve path tested: `make approve-13f` (or equivalent) completes promotion.
- Worktree cleanup run.

### §5.5 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| V2 fails on live Q1 data (edge case not seen in admin refresh) | Low | HIGH | git revert restores V1 in Makefile; single-line change |
| Makefile syntax error breaks entire Make target surface | Low | HIGH | Test Make target before PR push |
| update.py:75 replacement has wrong invocation pattern | Medium | Medium | Diff V1 and V2 invocations in prompt; pick pattern with evidence |
| registry.py owner updates break downstream consumer | Very low | Low | owner field is advisory text; not hard-parsed as module path (verified via filesystem connector earlier) |
| Full-reload mode needed post-cutover | Low | Medium | Documented manual loop; operator has tool |

### §5.6 Rollback plan

- `git revert` on PR restores V1 in Makefile + scripts/update.py + registry owners in one revert.
- V1 script physically remains at `scripts/load_13f.py` until B3 (per gate) — so revert is complete restoration.
- If issue surfaces mid-cycle, revert + re-run cycle on V1 + open investigation.

### §5.7 Code session prompt draft

```
Session: phase-b2-5-v2-cutover

Mode: V2 cutover — Makefile + update.py + benchmark + registry owner fields. Single PR. Critical path change.

Working dir: ~/ClaudeWorkspace/Projects/13f-ownership
Base: main (post phase-b2)
Branch: phase-b2-5-v2-cutover

Hard scope:
- DO NOT retire scripts/load_13f.py in this session (that's B3)
- DO NOT drop any table (that's B3)
- DO NOT modify V2 or V1 script content
- DO NOT merge

Phase 1 — Verify start
1. git status clean
2. HEAD post-B2
3. scripts/load_13f.py exists at scripts/ (not retired yet)
4. scripts/load_13f_v2.py exists
5. No 13F cycle in flight: check scripts/logs/ for recent pipeline activity; if a cycle is active, STOP and wait

Phase 2 — Pre-cutover verification
2.1 — Verify V2's admin refresh equivalence on real invocation:
> python -c "from scripts.pipeline.pipelines import get_pipeline; p = get_pipeline('13f_holdings'); print(p, p.__class__, p.__module__)"
Expect: Load13FPipeline from load_13f_v2

2.2 — Identify every invocation of V1 in scheduled paths:
> grep -rn "load_13f.py\|load_13f\b" Makefile scripts/update.py scripts/benchmark.py scripts/scheduler.py .github/
Document each hit with context.

2.3 — Review V2's __main__ / CLI surface to understand invocation:
> tail -100 scripts/load_13f_v2.py
Note: --quarter required, --auto-approve flag chains run → approve_and_promote.

Phase 3 — Execute cutover

3.1 — Makefile:111 (or whichever line now has the V1 invocation):
Find the current line. Replace V1 invocation with V2 equivalent. V2 invocation pattern (verify against scripts/load_13f_v2.py __main__):
`$(PY) $(SCRIPTS)/load_13f_v2.py --quarter $(QUARTER) --auto-approve`

If Makefile flow varies (e.g., has a non-cycle target calling V1 without --quarter), handle each occurrence appropriately. Document decisions.

3.2 — scripts/update.py:75 (or semantically equivalent line):
Find the load_13f.py step in the pipeline_steps list or dispatch. Replace with load_13f_v2 equivalent, matching V2's invocation requirements (--quarter, --auto-approve).

3.3 — scripts/benchmark.py:20 (or semantic match):
Update the benchmark matrix entry from load_13f to load_13f_v2.

3.4 — scripts/build_managers.py upstream comment:
Find reference to load_13f.py as upstream producer. Replace with load_13f_v2.py. Use semantic search (comment about filings_deduped or upstream producer), not line number.

3.5 — scripts/pipeline/registry.py:
Line 113 (filings spec): owner="scripts/load_13f.py" → owner="scripts/load_13f_v2.py"
Line 118 (filings_deduped spec): same update
Leave raw_* L1 specs alone (B3 handles those).

Phase 4 — Documentation updates

4.1 — MAINTENANCE.md: add "Full reload" subsection under Quarterly Cycle:
"V2 requires --quarter per invocation; no full-reload mode. To reload historical quarters, loop:
  for q in 2025Q1 2025Q2 2025Q3 2025Q4; do
    make load-13f QUARTER=$q
  done"

4.2 — NEXT_SESSION_CONTEXT.md: append cutover record:
"[<SESSION_DATE>] V2 cutover complete. Scheduled cycle now runs load_13f_v2.py. V1 script remains at scripts/load_13f.py as break-glass until B3 (2-cycle gate Aug 2026). Watch Q1 cycle for any novel filing patterns V1 handled silently that V2 doesn't."

4.3 — docs/data_sources.md / docs/pipeline_inventory.md: update load_13f refs to load_13f_v2.

4.4 — If Phase C1 has shipped: update data_layers.md Appendix A 13F provenance note. If C1 has NOT shipped, note in PR body that C1's regen will pick this up.

Phase 5 — Smoke test
5.1 — Test Make target (DRY RUN — do not actually run full cycle):
> make -n load-13f QUARTER=2025Q4
Confirm expansion uses load_13f_v2.py.

5.2 — Fixture-DB smoke test if test fixture supports it:
> pytest tests/pipeline/test_load_13f_v2.py -v
All green.

5.3 — Verify no V1 references remain in scheduled paths:
> grep -rn "load_13f.py\|load_13f\b" Makefile scripts/update.py scripts/benchmark.py scripts/scheduler.py .github/ | grep -v "load_13f_v2"
Expected: only refs are in comments, docstrings, or V1 file itself.

Phase 6 — PR
Title: `phase-b2-5-v2-cutover: swap scheduled path V1→V2 + co-land registry owner updates`
Body:
- Every file edited with diff context
- Makefile test output
- V1 remaining references (should be: V1 script itself, comments, docs)
- Rollback plan: single git revert

Output: PR pushed, CI green, not merged. Summary of cutover state.

Out of scope:
- Retiring scripts/load_13f.py (B3)
- Dropping any table (B3)
- Modifying V1 or V2 script content
- Changing raw_* registry entries (B3)
- Merge

DO NOT use --no-verify. DO NOT force push.
```

---

## §6 — Phase C2: Tracker consolidation + ops-18 investigation

**Session name:** `phase-c2-tracker-consolidate`.
**Estimated duration:** 90-150 min.
**Risk level:** Low-medium.

### §6.1 Scope

[Content from v2 §5 — preserved]

**Post-B1 state:** REMEDIATION_CHECKLIST.md archived. Active trackers:
- ROADMAP.md
- REMEDIATION_PLAN.md
- DEFERRED_FOLLOWUPS.md
- NEXT_SESSION_CONTEXT.md

**Decisions:**

1. **Keep DEFERRED_FOLLOWUPS.md and NEXT_SESSION_CONTEXT.md separate** (Option B). Document source-of-truth rule.
2. **Add 4 undocumented pipeline modules** to pipeline_inventory.md (V9).
3. **Consolidated backlog view** in ROADMAP.md.
4. **Document source-of-truth rules** for every tracker category.
5. **ops-18 investigation (per Q4)** — investigate with prior-knowledge framing from REMEDIATION_PLAN.md.

### §6.2 ops-18 investigation — prior-knowledge framing (R5 adjustment)

Plan review R5 established that REMEDIATION_PLAN.md L208/253/446/595/603/606 already documents ops-18 as a missing-file problem, not an unsolved concept. Rediscovering this via git log + grep would duplicate existing documentation.

**Revised investigation approach:**

Step 0 (new): Read REMEDIATION_PLAN.md at the cited line numbers. Confirm ops-18 has been tracked as a missing FILE (`rotating_audit_schedule.md`) since 2026-04-20 initial remediation consolidation.

Step 1: Frame investigation around: "was the rotating-audit *concept* ever written down elsewhere — design notes, prompts, pre-program scratch files, archived docs, git history predating remediation?"

Step 2: Search archived docs (Phase B1 archives may have context):
> grep -rn "rotating" archive/docs/ docs/ --include="*.md"

Step 3: Git log (deep):
> git log --all --grep="rotating" -p
> git log --all --grep="ops-18" -p

Step 4: Specifically check pre-remediation-consolidation files:
> git log --all --before="2026-04-20" -- "*.md" | grep -i rotating

Step 5: If concept recoverable: summarize in investigation report, add to backlog with recovered context. If not: close as ambiguous.

### §6.3 Scope (rest unchanged from v2)

[Rest of §5 from v2 — pipeline_inventory additions, Current Backlog section, source-of-truth rules]

### §6.4 Gating + risk + rollback + prompt

[Per v2 §5, with ops-18 Phase 5 updated per §6.2 above]

---

## §7 — Phase B3: DB cleanup + legacy retire (single combined session)

**Session name:** `phase-b3-db-cleanup`.
**Estimated duration:** 120-180 min.
**Risk level:** Low after 2-cycle gate (high without).
**Gate:** Q1 + Q2 2026 13F cycles both run clean on V2 scheduled path (~Aug 2026).

### §7.1 Rationale for combined session (R4 response)

Plan review R4 recommended splitting B3 into B3a (retire) + B3b (drops). Considered and rejected because:

1. **No new safety from the split.** V1 has been validated as having no readers outside itself (V1 + V2 of verification). 2 clean cycles on V2 validate V2's correctness as a loader. Waiting additional time between retire and drops doesn't surface new readers — they'd already surface during cycles.

2. **Pre-drop snapshots provide the real safety net.** Irreversibility of DDL drops is mitigated by mandatory snapshot-before-drop, not by calendar delay.

3. **Split creates a window of drift.** Between B3a and B3b, V1 is retired but `raw_*` tables remain. Registry would still list them as owned by V1 (now at `scripts/retired/`), creating an actively misleading state.

4. **Combined PR is also one revert.** If any issue surfaces post-merge, `git revert` of B3 restores V1 to `scripts/` and recreates tables from snapshots. Same recoverability as split.

The 2-cycle gate itself is the delay that matters — it's what validates V2 in production conditions.

### §7.2 Scope (co-land everything per solve-once principle)

**Code retirement:**
1. Remove `scripts/load_13f.py` references from:
   - `scripts/update.py` (B2.5 already did this; verify)
   - `Makefile` (B2.5 already did this; verify)
   - `scripts/benchmark.py` (B2.5 already did this; verify)
   - `scripts/build_managers.py` upstream comment (B2.5 already did this; verify)
2. Remove `scripts/load_13f.py` from `scripts/pipeline/registry.py` raw_* owner fields (B3 does this because B3 also drops the raw_* entries)
3. `git mv scripts/load_13f.py scripts/retired/`

**DB drops with pre-drop snapshots:**
4. `CREATE TABLE raw_submissions_snapshot_<TIMESTAMP> AS SELECT * FROM raw_submissions; DROP TABLE raw_submissions;`
5. Same for `raw_infotable`, `raw_coverpage`.
6. `CREATE TABLE fund_holdings_snapshot_<TIMESTAMP> AS SELECT * FROM fund_holdings; DROP TABLE fund_holdings;`

**Co-land cleanups (solve-once per validation V-Q3):**
7. `scripts/db.py:82-86 REFERENCE_TABLES` — remove `fund_holdings` entry
8. `scripts/pipeline/registry.py` — remove 3 raw_* L1 DatasetSpec entries (L68-82)
9. `scripts/pipeline/registry.py:346` — update `fund_holdings` docstring comment (already notes dropped Stage 5; refresh)
10. `notebooks/research.ipynb:586-589` — update dead-branch probe to `fund_holdings_v2` OR delete the probe entirely

**Doc updates:**
11. `docs/data_layers.md` Appendix A — remove dropped tables from DDL listing; note their drop date
12. `ROADMAP.md` Closed log — add B3 entry
13. `REMEDIATION_PLAN.md` — if raw_* or fund_holdings mentioned, add drop note
14. `NEXT_SESSION_CONTEXT.md` — document drop + removed artifacts
15. `MAINTENANCE.md` — remove any reference to dropped tables in ops procedures

### §7.3 Gating condition (before starting)

- Q1 2026 AND Q2 2026 13F cycles both ran cleanly on V2 scheduled path (verified via pipeline logs + freshness records).
- Phase B1, B2, B2.5, C1, C2 all merged.
- Backup DB snapshot taken within 24 hours (`scripts/backup_db.py --confirm`).
- Prod DB is NOT in active use (no Flask app running, no other session writing).

### §7.4 Gating condition (after completing)

- PR merged.
- CI green.
- All 4 tables have confirmed snapshots (timestamped, verified non-empty).
- `grep -rn "load_13f.py\|raw_infotable\|raw_coverpage\|raw_submissions" scripts/ Makefile .github/` returns only archived references + retired file.
- Smoke test: app starts, loads register tab, no errors.
- `duckdb data/13f.duckdb --readonly -c "SHOW TABLES;" | grep -E "^raw_|^fund_holdings$"` — returns only snapshot tables (if any), no live drop-targets.
- Worktree cleanup run.

### §7.5 Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| V2 had a silent issue during Q1+Q2 cycles not caught | Very low (gate validates) | HIGH | 2-cycle gate; if issue surfaces pre-B3, halt and fix |
| Dropped table had a forgotten reader | Very low | HIGH | Pre-drop snapshot; validation V-Q3 cleared all readers |
| Snapshot creation fails silently | Low | CRITICAL | Script checks snapshot row count matches source before proceeding to DROP |
| Concurrent app or session writing during drop | Medium | HIGH | Explicit pre-check: no app running, no other session in DB |
| notebook probe update changes notebook's git-tracked state unexpectedly | Low | Low | Confirm notebook diff is surgical; only the 4-line probe changes |

### §7.6 Rollback plan

- Snapshots restore all dropped tables via `CREATE TABLE ... AS SELECT * FROM snapshot_table`.
- `git revert` restores V1 to `scripts/` and all caller references.
- Combined rollback is one `git revert` + 4 SQL restore statements.

### §7.7 Code session prompt draft

Deferred — drafted when gate approaches (est. Aug 2026). Current draft is structural only; concrete prompt needs real post-cycle state before dispatching.

---

## §8 — Small one-offs (tracked, not phased)

### §8.1 `fetch-finra-short-dry-run`

Add `--dry-run` / `--apply` pattern to `scripts/fetch_finra_short.py`. Verified gap per V5. Very low risk.

### §8.2 `audit-ticket-numbers-refinement-v10`

Refine `scripts/hygiene/audit_ticket_numbers.py` grouped-row handling for V10's `| DM2 / DM3 / DM6 |` false positive. Fix lives in `line_kind()` or `extract_table_title()` — detect multi-ticket lead cells, skip them from title extraction.

**Independent from B1's INF40 mitigations.** Plan review R1 corrected the v2 claim that M2 fixes V10 — they're different code paths.

Very low risk.

### §8.3 `snapshot-retention-policy`

Define retention for 292 historic snapshots across 15 tables (V8). Requires Serge policy decision. Low risk once policy agreed.

---

## §9 — Still-open real backlog

[Unchanged from v2 §8. Listed for completeness.]

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

## §10 — Final Code review session (narrower scope)

**Session:** `plan-review-v3-2026-04-23`
**Duration:** 45-75 min (narrower than v2 review since much was confirmed).
**Scope:** Review v3's CHANGES from v2 only. Don't re-review confirmed sections.

**Focus areas (new or substantially changed since v2 review):**

1. **Phase B2.5 (entirely new)** — V2 cutover scope, co-landing specifics, rollback plan, session prompt. Does B2.5 cover everything needed to make Q1+Q2 gate measurable? Does the prompt correctly handle V1/V2 invocation differences?

2. **§4 Phase C1 (written fresh from primary sources)** — does the regenerate-from-prod approach cover all tables canonical_ddl.md covered? Does the prompt correctly identify inbound references?

3. **Q4 revert (migrate_batch_3a to oneoff/ + registry owner update)** — does B2 prompt correctly identify the owner update? Is "manual" the right owner string, or should it be more specific?

4. **B3 co-landing additions (V-Q3 per validation)** — db.py REFERENCE_TABLES, registry.py raw_* entries, notebook probe. Does §7.2 cover each correctly?

5. **INF40 mitigation 2 decoupling from V10 (R1)** — does §2.1.1 correctly describe M2 as independent from V10's grouped-row fix?

6. **Oneoff list framing (R3)** — does §3.1 correctly describe the V7 extension?

7. **ops-18 prior-knowledge framing (R5)** — does §6.2 Step 0 correctly establish the missing-file prior?

8. **Session-date dynamics (R6 + M1)** — are all prompts using `<SESSION_DATE>` or `date +%Y-%m-%d` rather than hardcoded dates? Any line numbers that should be semantic searches?

**Not in scope (already confirmed in v2 review):**

- B1 tracker flips (L39/L98/L101) — verbatim-confirmed
- Archive file existence (8 files) — confirmed
- Pipeline module existence (4 files) — confirmed
- Hygiene script existence (6 files) — confirmed
- Retire candidate existence (2 files) — confirmed
- INF40 chronology #1/#2 assignment — confirmed
- No `--no-verify` in prompts — confirmed
- Sequence dependencies (B1→B2→C etc.) — confirmed

**Output:** `docs/findings/plan-review-v3-2026-04-23.md` with only critical/recommended/minor findings on the review scope. Confirmations optional.

---

## §11 — Plan change log

- 2026-04-23 v1 — initial draft post-verification
- 2026-04-23 v2 — incorporates Serge's Q1-Q5 answers
- 2026-04-23 v3 — incorporates validation results + plan review + Q4 revert + Phase B2.5 added + §4 C1 written fresh

---

## §12 — Plan adoption criteria

This plan is adopted when:

1. v3 Code review session ships a review report on the scope in §10.
2. Serge reviews the report.
3. Plan revised if any critical issue found.
4. Plan PR merged to main.

Then Phase B1 starts.
