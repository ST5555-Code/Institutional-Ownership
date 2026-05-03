# Handoff Context — Phase B/C Execution

**Prepared:** 2026-04-23
**For:** New chat starting Phase B1 execution
**Project:** 13F Institutional Ownership platform (`~/ClaudeWorkspace/Projects/13f-ownership`)
**Repo:** `github.com/ST5555-Code/Institutional-Ownership`

---

## 1. Where we are

**Main HEAD:** `0264c9e`
**Plan:** `docs/plans/2026-04-23-phase-b-c-execution-plan.md` (DRAFT v4, on main)
**Today's activity:** 31 PRs merged + 2 direct plan commits (v3 + v4).

**Reference docs on main** (findings that underpin the plan):
- `docs/findings/comprehensive-audit-2026-04-23.md` — Phase A baseline audit
- `docs/findings/pre-phase-b-verification-2026-04-23.md` — V1-V10 verification
- `docs/findings/plan-review-2026-04-23.md` — v2 critique
- `docs/findings/refinement-validation-2026-04-23.md` — v3 refinement validation
- `docs/findings/plan-review-v3-2026-04-23.md` — v3 critique

**Only open PR:** #107 (ui-audit walkthrough — Serge's separate track, deferred).
**Only active worktree:** main.

---

## 2. What the plan says (one-page summary)

The plan translates audit + verification + validation findings into 6 sequential phases plus 3 one-offs.

**Phase sequence:**

```
B1 (tracker hygiene + doc archival)
  → B2 (script filesystem reorg)
    → B2.5 (V2 scheduled-path cutover, before Q1 2026 cycle ~May 15)
      → C1 (DDL fold: canonical_ddl.md → data_layers.md Appendix A) ∥ C2 (tracker consolidation + ops-18 investigation)
        → [2-cycle operational gate: Q1 + Q2 cycles clean on V2 ~Aug 2026]
          → B3 (V1 retire + 4 DDL drops + co-land cleanups)
```

**One-offs (dispatched opportunistically):**
- `fetch-finra-short-dry-run` — add `--dry-run`/`--apply` to FINRA fetch
- `audit-ticket-numbers-v10` — fix grouped-row false positive
- `snapshot-retention-policy` — define retention across 292 snapshots

**Each phase has in the plan:** scope, gating (before/after), risk, rollback, full Code session prompt.

---

## 3. Standing rules + preferences (locked in this chat)

### Working style

1. **Evenly-proportional rigor.** Don't handwave on decisions that shape long-term system state. Verify before recommending; where not verifiable directly, ask Code to verify.

2. **Long-term lens for recommendations.** When asked "is this best?" — audit against long-term system quality (resilience, speed of end-state system, future-proof), not speed of solving.

3. **Solve once, not incrementally.** Prefer solving all issues in one pass unless explicit good reason to defer.

4. **No feature flags as hedges.** If ready, commit. If not ready, don't promote. Flags that exist "just in case" are patches that live forever.

5. **No forced rollups for calendar pressure.** Sequential sessions preserved. If calendar slips, honest deferral is right (e.g., skip a cycle), not bundling work.

6. **Audit the audit.** Don't treat prior findings as authoritative without live verification. Numbers drift.

### Process

7. **Wait for explicit "go" before drafting prompts.** Confirm approach first.

8. **Show audit steps, not just conclusions.** Don't say "I audited this" without showing what was checked.

9. **Verify every file path and reference in a prompt exists with expected content before dispatching.** Filesystem connector is available for this.

10. **Fix-the-fix sessions run solo until merged. Meta-fixes serialize.**

11. **Parallel PR pairs require file-disjoint AND no-rules-collision check.**

12. **Never delete files/data without explicit confirmation.** State what will be deleted, wait for clear yes.

### Git lifecycle (plan §10)

13. **Code handles all git operations for files produced in its session.**
    - Stages, commits, pushes, opens PR, waits for CI green
    - Asks Serge: "PR #N green. Merge?" before merging
    - On yes: merges + deletes branch + cleans worktree + closes session
    - On no/adjust: addresses, re-pushes, re-asks
    - Never merges without explicit yes
    - Never uses `--no-verify` or force push

14. **Manual merge from Terminal still permitted.** If Serge merges via `gh pr merge`, Code proceeds to cleanup + close.

15. **Destructive DDL sessions (B3) have an extra layer.** Code asks before each DROP, regardless of merge state.

16. **File-producing sandbox outputs (plan docs, deliverables) flagged explicitly as "save + commit manually."** Claude doesn't try to drop these into the repo. When producing a file in `/mnt/user-data/outputs/`, state clearly whether it needs save+commit or is just reference.

### Communication

17. **Don't narrate obvious steps.** No "let me check that for you" filler.

18. **Acknowledge mistakes in one word, fix them.** No excessive apology.

19. **No recap of what the person just said** unless specifically clarifying.

20. **Challenge the person's reasoning when warranted.** Not blindly agreeing — push back when a premise is wrong.

### Tool usage

21. **Use filesystem connector to verify before claiming.** Don't assume file content or paths.

22. **When Serge pastes Code session output: read the full report via filesystem connector, don't just summarize from the paste.**

### Session management

23. **New chat when context is heavy or phase shifts.** Not mid-planning.

24. **Session handoff document when transitioning chats on complex work.**

25. **Code prompts always delimited in copy-paste-friendly boxes.** Using `------` delimiter lines top and bottom. Clear boundaries so Serge can select the whole prompt cleanly without picking up surrounding commentary.

26. **Session names kept short (~25 characters max).** Descriptive but not verbose. Examples:
    - Good: `phase-b1-doc-hygiene`, `plan-review-v3`, `audit-ticket-numbers-v10`
    - Avoid: `phase-b2-5-v2-cutover-with-registry-updates-2026-04-23` (too long), `sess-001` (not descriptive).

---

## 4. What to do first in the new chat

**Dispatch Phase B1.** The plan contains a full prompt draft in §2.6.

**Plan citation:** `docs/plans/2026-04-23-phase-b-c-execution-plan.md` §2 (scope, gating, risk) and §2.6 (prompt).

**Phase B1 summary:**
- Flip 3 stale checkboxes in `REMEDIATION_CHECKLIST.md` (L39/L98/L101)
- Annotate INF40 dual-closure in ROADMAP with 3 future-proofing mitigations
- Retire `REMEDIATION_CHECKLIST.md` to `archive/docs/`
- Archive 8 legacy docs to `archive/docs/`
- Risk: very low, doc-only

**After B1 merges, dispatch B2.** Plan §3 + §3.6. Sequential through B2.5, then C1 ∥ C2. Then the Q1+Q2 cycle gate. Then B3.

---

## 5. Key project context

**Stack:** DuckDB, Flask, Python, Chart.js, vis.js.
**EDGAR identity:** `serge.tismen@gmail.com`.
**Serge's working style (userPreferences):** Plain, direct, no preamble. Challenge flawed logic. Confirm end-use before complex tasks. Never delete without explicit confirmation. Flag thin data. Always produce downloadable files for deliverables. No contractions, no exclamations, no consultant-speak. Presentations: banker-ppt template only.
**User location:** New York.

**V2 loader status (critical for B2.5):**
- `scripts/load_13f.py` = V1, still on scheduled cycle path via `Makefile:111`
- `scripts/load_13f_v2.py` = V2, on admin-refresh path via `scripts/pipeline/pipelines.py` → `Load13FPipeline`
- B2.5 swaps V1 → V2 on scheduled path
- B3 retires V1 after 2 clean cycles on V2 (Aug 2026)

**Canonical entity IDs:** Vanguard 4375, Morgan Stanley 2920, Fidelity 10443, State Street 7984, Northern Trust 4435, Wellington 11220, Dimensional 5026, Franklin 4805, PGIM 1589, First Trust 136.

**Architectural invariants:**
- `entity_current` VIEW hardcodes `rollup_type='economic_control_v1'`
- SCD open-row sentinel: `DATE '9999-12-31'`, not NULL
- B608 nosec on closing `"""` line of SQL string
- `git pull --ff-only` for worktree recovery
- v2 fact tables have `row_id BIGINT PK` (migration 014)

---

## 6. Out of scope for Phase B/C

- Forward feature work (Tier 1-3)
- DM Tier 2 completion (int-09 Step 4, INF25, INF38, 43g, 43b, 48, 56)
- PR #107 ui-audit walkthrough
- Q1 2026 13F cycle execution (calendar-gated)
- Tier 3 architectural design sessions

Tracked in plan §9.

---

## 7. If something breaks

- CI red: pause, investigate, fix before merge.
- Plan assumption wrong: escalate to Serge before acting.
- V2 fails post-B2.5: `git revert` of B2.5 PR restores V1 in one commit.
- Worktree stuck: `git worktree remove .claude/worktrees/<n>` + `git branch -D claude/<branch>`.
- DuckDB lock held: stop Flask app, retry.

---

## 8. Opening message for the new chat

Paste in the new chat:

```
Phase B/C execution. Plan on main at docs/plans/2026-04-23-phase-b-c-execution-plan.md.
Main HEAD 0264c9e. Ready to dispatch Phase B1.

Read the plan, confirm you have context, then produce the Phase B1 prompt per §2.6
(with <TODAY> resolved to actual session date). I'll dispatch it from a Code session.
```

---

## 9. Session naming reference

Phase session names (from plan):
- `phase-b1-doc-hygiene`
- `phase-b2-script-reorg`
- `phase-b2-5-v2-cutover`
- `phase-c1-ddl-fold`
- `phase-c2-tracker-consolidate`
- `phase-b3-db-cleanup` (drafted at gate approach, ~Aug 2026)

One-offs:
- `fetch-finra-short-dry-run`
- `audit-ticket-numbers-v10`
- `snapshot-retention-policy`

All follow §10 standing git lifecycle rule.
