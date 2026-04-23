# Plan Review — 2026-04-23 Phase B/C Execution Plan

**Session:** `plan-review-2026-04-23` · **Mode:** Read-only critique. No plan edits — that is a separate session per the plan's §12 adoption flow.

**Plan under review:** [`docs/plans/2026-04-23-phase-b-c-execution-plan.md`](../plans/2026-04-23-phase-b-c-execution-plan.md), DRAFT v2.

**Inputs cross-checked:**
- [`docs/findings/comprehensive-audit-2026-04-23.md`](./comprehensive-audit-2026-04-23.md) (Phase A baseline; not yet on main).
- [`docs/findings/pre-phase-b-verification-2026-04-23.md`](./pre-phase-b-verification-2026-04-23.md) (V1–V10; not yet on main).
- Current `origin/main` HEAD `aab73d2` — repo state, prod DB read-only, scripts/, docs/.
- [`scripts/audit_ticket_numbers.py`](../../scripts/audit_ticket_numbers.py) (378 LOC, current shape).
- [`scripts/pipeline/registry.py`](../../scripts/pipeline/registry.py) (DatasetSpec `owner` fields).

**Method:** verified each §10 review checklist item against the corresponding source. Section numbering below mirrors §10 of the plan.

---

## §1 Summary

| Bucket | Count |
|---|---|
| Critical issues (must fix before adoption) | **2** |
| Recommended revisions (should fix before adoption) | **6** |
| Minor corrections (cosmetic) | **3** |
| Confirmations (correct as drafted) | **9** |
| Scope concerns formally answered | **3** (INF40 mitigations · ops-18 · B3 combined session) |
| Questions for Serge | **4** |

Plan is **mostly sound** — sequencing is right, prompts are well-scoped, Serge-rules respected throughout. Two issues block adoption (B3 gate logic, C1 stub). Six revisions should land before B1 dispatches. Everything else is polish.

---

## §2 Critical issues — must fix before plan adoption

### C1. Phase B3 gate logic is not measurable as drafted

**Where:** §1 master sequence, §6.1 step 1, §6.2 first bullet.

**The gate:** "Q1 + Q2 2026 13F cycles run clean on `load_13f_v2.py`" (§1, projected ~Aug 2026).

**Why this isn't measurable today:** V3 (verification doc) established that `load_13f.py` and `load_13f_v2.py` serve **different surfaces** — V1 is the CLI/Makefile pipeline step (called from `scripts/update.py:74` and `Makefile:111`); V2 is the admin-refresh `SourcePipeline` subclass (invoked only via `scripts/admin_bp.py`). Quarterly cycles run via the scheduled pipeline path, which calls **V1**, not V2. So "Q1+Q2 cycles run clean on V2" doesn't naturally happen unless someone first substitutes V2 into the cycle entry points.

The plan does not include this substitution step. §6.1 Step 1 says "Confirm `scripts/load_13f_v2.py` is sole loader" — but V2 only becomes sole loader as a *result* of B3, not a precondition. The current draft assumes the gate condition is observable from existing operations; it isn't.

**Two ways to repair:**
- **(a)** Add an explicit pre-B3 substitution step (call it `B2.5: cut update.py + Makefile from V1 to V2`) that lands before the Q1 2026 cycle begins. Then Q1 + Q2 cycles will naturally run on V2 and the gate becomes measurable. This is a code change with its own gating + rollback considerations.
- **(b)** Reframe the gate as shadow-validation: "V2 ran clean via admin-refresh against the same data as V1 for both Q1 and Q2 2026 cycles, with output parity checked." Then V1 stays quiescent during the gate, B3 cuts V1 over and removes it. This requires a parity-comparison harness that the plan also doesn't describe.

Either resolution is plan-level — Code can't fix this in B3's session.

### C2. §4 (Phase C1) is a stub referencing a v1 of the plan that is not in the document

**Where:** §4, line 423 — `"[Content unchanged from v1 — see §4 in draft v1 for full scope, gating, risk, rollback, and prompt draft.]"`

**Impact:** the reviewer (this session) and the eventual C1 dispatch session cannot verify:
- C1's scope (which docs are folded into canonical_ddl.md)
- C1's gating conditions
- C1's risk + rollback
- C1's session prompt

V6 of the verification doc found that the audit's own DB column counts were wrong (holdings_v2 has 38 cols, not 30 as audit reported — drift is +5, not +3). C1's scope is materially affected by V6, but the plan elides it.

§6.1 Phase B3 step 4 forward-references "data_layers.md Appendix A (from Phase C1)" — a dependency on a C1 deliverable the reviewer can't validate.

**Resolution:** inline the v1 §4 content into v2, then revise it to incorporate V6's actual delta (+5/+0/+6 vs the audit's stated +3/+0/+6). Without §4 substance, C1 cannot be reviewed and B3's appendix update has no anchor.

---

## §3 Recommended revisions — should fix before adoption

### R1. §2.1.1 Mitigation 2 conflates two different fixes

**Where:** §2.1.1, Mitigation 2 paragraph: *"Same fix closes V10's grouped-row false positive and this INF40 case."*

**Why wrong:** the two fixes touch different code paths in `scripts/audit_ticket_numbers.py`:

- **INF40 dual-closure (M2 actual scope):** detect the bracketed annotation `[INF<N> #M of K]` in the line content, mark the matching `Definition` as annotated, and skip annotated definitions from candidate-reuse output. Belongs near `extract_title()` / `group_distinct()` filtering.
- **V10 grouped-row FP:** the `**DM2 / DM3 / DM6**` lead-cell pattern is treated by `line_kind()` as a single ticket-defining table-row even though it covers three tickets in one row, and `extract_table_title()` returns the second-cell text as the title for *all three* tickets. The fix lives in `line_kind()` (multi-ticket lead-cell detection) or `extract_table_title()` (skip if lead cell holds multiple ticket tokens).

These are independent. M2 will not fix V10 by side effect. Recommend deleting the "same fix closes V10" claim from §2.1.1 and either:
- (a) split §7.2 into two distinct refinements (`audit-ticket-numbers-grouped-rows` and `audit-ticket-numbers-annotation-pattern`), keeping the latter optional if B1 already shipped M2; or
- (b) leave §7.2 covering V10 only, and rely on B1's M2 to handle the annotation pattern standalone.

### R2. `migrate_batch_3a.py` has a live metadata reference the plan does not flag

**Where:** §3.1 oneoff list, line 290 (`scripts/migrate_batch_3a.py`).

**Evidence:** [`scripts/pipeline/registry.py:295`](../../scripts/pipeline/registry.py:295) — `DatasetSpec` for `fund_family_patterns` has `owner="scripts/migrate_batch_3a.py"`.

This is a metadata reference (same pattern V2 found for `raw_*` in registry — DatasetSpec fields, not runtime imports). The Phase B2 prompt §3.6 Phase 2 rules will catch it as a hit and STOP, which is good — but the plan should pre-acknowledge it so the session knows the planned outcome:

- **Option A:** update the `owner` string to `scripts/oneoff/migrate_batch_3a.py` when moving the file (preserves the metadata signal).
- **Option B:** keep the script under `scripts/` since it's a declared dataset owner (matches V7's spirit — this is a "live owner" reference, not a true historic one-off).

V7's tighter sweep listed 6 oneoff relocates (without `migrate_batch_3a`); the plan added 5 to reach 11 (see R3). Of those 5, `migrate_batch_3a` is the only one with a code-side reference and warrants explicit handling.

### R3. §3.1 oneoff list expanded V7's set without acknowledging the expansion

**Where:** §3.1 vs verification doc V7 §7.

**V7's named oneoff candidates (6):** `backfill_pending_context`, `bootstrap_tier_c_wave2`, `dm14_layer1_apply`, `dm14b_apply`, `dm15_layer1_apply`, `inf23_apply`.

**Plan §3.1 oneoff list (11):** V7's six **plus** `dm14c_voya_amundi_apply`, `dm15_layer2_apply`, `dm15c_amundi_sa_apply`, `inf39_rebuild_staging`, `migrate_batch_3a`.

I re-grepped each of the 5 added scripts on current `origin/main`. All exist; none have code callers (only doc / ROADMAP / findings refs) **except** `migrate_batch_3a` (R2 above). The expansion is therefore defensible — V7 was an illustrative sample, and these five fit the same pattern.

But §3.1 frames the list as "per V7, unchanged per Q2." That's misleading — V7 listed six, not eleven. Recommend rewording §3.1 to: "Per V7's classification rules, applied to the full Pass-2 candidate set: 11 historic one-offs identified (6 named in V7 + 5 found by the same rules)." This avoids future confusion about which list is authoritative.

### R4. Phase B3 should split into B3a (retire) + B3b (drops)

**Where:** §6.1 — six listed actions in one session: load_13f.py retirement (5 caller-file edits + git mv), 4 DROP TABLE operations on tables totaling ~13.65M rows, plus 4 doc updates.

**Concerns:**
- Blast radius: combining a code change (V1 retire) with 4 irreversible DDLs in one PR means a problem with the drops contaminates the retire (and vice versa). Revert is messier.
- The 90–180 min estimate is tight for 4 pre-drop snapshots + 4 drops + 5-file code change + 4 doc updates + smoke verification.
- The 2-cycle gate validates V2's correctness as a *loader*. It does not directly validate that no forgotten reader exists for `raw_*` or `fund_holdings`. Those concerns are discrete; bundling them into one PR removes the option to land them independently.

**Recommended split:**
- **B3a** (immediately after gate): cut update.py + Makefile + benchmark + registry + build_managers from V1 to V2; `git mv scripts/load_13f.py scripts/retired/`. PR-revertible if a regression appears.
- **B3b** (after B3a soaks for ~1–2 weeks): pre-snapshot + drop `raw_infotable`, `raw_coverpage`, `raw_submissions`, `fund_holdings`. Doc updates in this same PR (data_layers.md Appendix A, ROADMAP, etc.).

Splitting makes each PR's blast radius narrower and gives a real-world soak window between V1 retirement and the data drops.

### R5. ops-18 prompt should reflect prior knowledge of the missing-file context

**Where:** §5.6 Phase 5 (ops-18 investigation), step 3 (`git log --grep="rotating"` / `git log --grep="ops-18"`).

**Why:** [`docs/REMEDIATION_PLAN.md`](../REMEDIATION_PLAN.md) L208/L253/L446/L595/L606 already establishes the historical context — `rotating_audit_schedule.md` was a *file* that didn't exist in the branch as of the 2026-04-20 initial remediation consolidation, and ops-18 has been BLOCKED on "upstream doc recovery" since. The git log greps proposed in §5.6 will find only the consolidation entries acknowledging the file was missing — not its contents.

The investigation has higher yield if it reframes around: "was the rotating-audit *concept* ever written down anywhere — design notes, prompts, pre-program scratch, Linear/issues elsewhere?" The current prompt invites the session to spend cycles on dead-end greps before reaching the same conclusion the remediation plan reached six months ago.

Recommend §5.6 Phase 5 add a step 0: "Read REMEDIATION_PLAN.md L208, L253, L446, L606 first — confirm they describe a missing FILE, not an unsolved concept. Frame investigation accordingly: search for the original concept source, not the file."

### R6. §2.6 Phase 5 retirement-pointer text embeds a date that may drift

**Where:** §2.6 Phase 5 step 3, the pointer text dropped at the top of `docs/REMEDIATION_PLAN.md`:
> "Remediation Program COMPLETE 2026-04-22 (conv-11). The historical checklist was retired to `archive/docs/REMEDIATION_CHECKLIST.md` on 2026-04-23 ..."

The session may dispatch later than 2026-04-23. The closure date (`2026-04-22 conv-11`) is correct — that's the program-complete commit `7c49471` per ROADMAP — but the *retirement* date `2026-04-23` is hardcoded.

Recommend rewriting the prompt to: "use the actual session date for the retirement date (today)." The conv-11 / 2026-04-22 closure date stays verbatim.

---

## §4 Minor corrections — cosmetic

### M1. §6.1 step 1 "Remove from `scripts/build_managers.py:228`"

The exact line number is brittle. V3 cited `:228` but build_managers.py may have shifted by the time B3 dispatches (~Aug 2026). Recommend rephrasing to "Remove the `scripts/load_13f.py` reference at the upstream-producer comment in `scripts/build_managers.py`" so the prompt doesn't depend on a stale line number.

### M2. §3.4 risk table entry "Misclassified script (actually live)"

Mitigation column says "Verify V7 categorization per script before moving; Code review flags any missed callers." Recommend adding the explicit pattern: "Check `scripts/pipeline/registry.py` `owner=` and `downstream=` fields per script — these are the easy-to-miss metadata references." (Direct response to R2.)

### M3. §0 Hard rules bullet 4 typo

"No batch acts on any number pulled from the audit without verifying it live" — clear in intent but the word "number" is ambiguous (could read as "ticket number"). Suggest "No batch acts on any **count or metric** pulled from the audit without verifying it live."

---

## §5 Confirmations — correct as drafted

| # | Item | Verified against | Status |
|---|---|---|---|
| F1 | L39 / L98 / L101 verbatim text matches V4 claims | `sed -n '39p;98p;101p' docs/REMEDIATION_CHECKLIST.md` on `origin/main` | ✓ exact match |
| F2 | All 8 archival source files exist | `test -f` per file from §2.1 | ✓ all present |
| F3 | All 4 V9 pipeline modules exist | `ls scripts/pipeline/{protocol,discover,id_allocator,cusip_classifier}.py` | ✓ all present |
| F4 | All 6 hygiene-target scripts exist | `ls scripts/{audit_ticket_numbers,audit_tracker_staleness,audit_read_sites}.py scripts/{cleanup_merged_worktree,bootstrap_worktree}.sh scripts/concat_closed_log.py` | ✓ all present |
| F5 | Both retire candidates exist | `ls scripts/{smoke_yahoo_client,snapshot_manager_type_legacy}.py` | ✓ both present |
| F6 | `scripts/oneoff/` and `scripts/retired/` exist; `scripts/hygiene/` does not | direct `ls` | ✓ matches "new directory" claim |
| F7 | INF40 chronology + #1/#2 assignment matches ROADMAP L600/L613 | grep `INF40` ROADMAP.md | ✓ #1=L613 (mig-06, 2026-04-22) · #2=L600 (inf40-fix, 2026-04-23) |
| F8 | ops-18 BLOCKED status + missing-file framing matches REMEDIATION_PLAN.md | grep `ops-18` REMEDIATION_PLAN.md | ✓ confirmed at L208/L253/L446/L595/L603/L606 |
| F9 | No prompt uses `--no-verify` or `--force` | grep `--no-verify\|force` plan | ✓ all prompts end with "DO NOT use --no-verify. DO NOT force push." |

Sequence dependencies (§10.2) all check out:
- B1 → B2 (B2 needs `scripts/hygiene/` from B1's M1+M2 to land there).
- B2 → C1 ∥ C2 (filesystem reorg must precede doc updates that cite new paths).
- (C1 ∥ C2) → B3 (data_layers.md Appendix A from C1; ROADMAP backlog from C2).
- B3 gate → B3 (operationally gated, not just sequenced).

Gating conditions (§10.3) are measurable everywhere **except B3** (see C1).

---

## §6 Scope concerns — §10.9 / §10.10 / §10.11

### §6.1 INF40 mitigations 1+2 in B1 (§10.9) — **feasible in B1, with prompt's escape hatch retained**

`scripts/audit_ticket_numbers.py` is 378 LOC with clean structure (`scan` → `group_distinct` → `main` reuse-detection loop). Both mitigations are localized:

- **M1 (whitelist):** add `DUAL_CLOSURE_EXCEPTIONS = {"INF40"}` const + filter in `main()` reuse loop. ~5–10 LOC.
- **M2 (annotation pattern):** detect `[INF<N> #M of K]` in line content during `scan()`, mark `Definition` as annotated, exclude annotated defs from `group_distinct()` output. ~15–25 LOC.

Combined ≤35 LOC, single file, no new dependencies. The plan's "STOP and surface — a larger refactor belongs in §7.2" escape hatch is well-placed and should be preserved.

**One revision (R1):** the §2.1.1 claim that M2 "closes V10's grouped-row false positive" is wrong. M2 and V10's fix are independent code paths.

### §6.2 ops-18 in C2 (§10.10) — **feasible in single C2 session**

Investigation scope is bounded: 4 grep variants + git log + outcome decision (RECOVERABLE / INCONCLUSIVE / PARTIAL). Combined with C2's existing scope (4 pipeline_inventory rows + ROADMAP backlog section + SESSION_GUIDELINES rule + source-of-truth docs), the 90–150 min estimate holds.

**One revision (R5):** the prompt should reflect prior knowledge from REMEDIATION_PLAN.md that this is a missing-FILE problem from day one, not an unresolved concept. Otherwise the session will rediscover what the remediation plan already documented.

### §6.3 Phase B3 single-session combined retire+drops (§10.11) — **should split (R4)**

See R4 above. Bundling V1 retirement with 4 irreversible DDL drops concentrates blast radius unnecessarily. Splitting into B3a (retire, reversible via revert) and B3b (drops, post-soak) preserves rollback options.

---

## §7 Questions for Serge

### Q1. How does load_13f_v2 actually run during the Q1+Q2 2026 gate period?

(C1 above.) Three plausible models — pick one before B3 can be reviewed:

- **(a)** Manual admin-refresh triggers per cycle, V1 stays as the scheduled path for production loads (V2 is shadow-validated only). B3 then has to do both the substitution *and* the drops.
- **(b)** Substitute V2 into update.py + Makefile *before* Q1 2026 starts (new pre-B3 step). Then the gate is naturally measurable.
- **(c)** Parity-compare V1 vs V2 outputs on every cycle (requires a parity harness that doesn't exist). Then B3 retires V1 once parity is confirmed.

### Q2. Is §4 (Phase C1) meant to inherit content from a v1 of the plan that lives elsewhere?

(C2 above.) The stub references "draft v1 §4." If v1 is in another doc / chat / scratch, please surface the path so it can be folded into v2. If it's lost, C1 needs to be re-scoped from the audit + verification docs directly — and that re-scoping should land in v3 of the plan, not in C1's session.

### Q3. B3 single-session vs B3a + B3b split — your call?

(R4 above.) Splitting is safer; combined is faster. Either is defensible. I'd recommend split, but you've made other Code-suggested splits unsplit before for ceremony cost. Worth your 30 seconds.

### Q4. For `migrate_batch_3a.py`, do you want B2 to update the `registry.py` `owner=` string, or leave the script in place as a declared dataset owner?

(R2 above.) The script is the declared `owner` of `fund_family_patterns` in `scripts/pipeline/registry.py:295`. Two answers, both fine — pick one so B2's prompt knows which to take:

- **Update `owner=` string** when moving the file → `scripts/oneoff/migrate_batch_3a.py`. Metadata stays accurate; relocate as planned.
- **Keep the file at `scripts/migrate_batch_3a.py`** since it's an active dataset owner; remove from §3.1 oneoff list. Treat the seeded-once-then-manually-edited pattern as "active rare", not "historic one-off."

---

## §8 Bottom line

Adopt v2 → v3 with C1 + C2 (critical) and R1–R6 (recommended) folded in. Then B1 dispatches.

The rest is right.
