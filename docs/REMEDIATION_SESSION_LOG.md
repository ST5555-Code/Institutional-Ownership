# Remediation Program — Session Log

_Every worker session appends one entry here at session close._

## Entry template

```
- **Session name:** <theme>-<seq> or <theme>-<seq>-<phase>
- **Start:** YYYY-MM-DD HH:MM
- **End:** YYYY-MM-DD HH:MM
- **Scope:** one-line description
- **Files touched:** list (absolute repo paths)
- **Result:** DONE | PARTIAL | DEFERRED
- **Commits:** list of SHAs
- **Merge status:** merged / pending review / reverted
- **Follow-ups surfaced:** list (new INF IDs or items to add to checklist)
- **Parallel-safety validation:** was this session's file-list consistent with Phase 0 prediction? YES / NO. If NO, what drifted.
```

The **Parallel-safety validation** field is a critical feedback loop. Every worker session MUST verify that the files it actually touched match the file-conflict zone predicted in `docs/REMEDIATION_PLAN.md` Appendix D. Drift is a signal that the Phase 0 dependency analysis missed something — capture it explicitly so the program can recalibrate before the next parallel batch.

---

## 2026-04-20 — Program kickoff

- **Session name:** prog-00
- **Start:** 2026-04-20 (start of program phase-0 consolidation)
- **End:** 2026-04-20 (at PR creation)
- **Scope:** program consolidation + master plan authorship; zero code changes, pure doc authorship
- **Files touched:**
  - `docs/REMEDIATION_PLAN.md` (new)
  - `docs/REMEDIATION_CHECKLIST.md` (new)
  - `docs/REMEDIATION_SESSION_LOG.md` (new)
  - `docs/SESSION_NAMING.md` (new)
  - `docs/prompts/int-01-p0.md` (new)
  - `docs/prompts/obs-03-p0.md` (new)
  - `docs/prompts/sec-01-p0.md` (new)
  - `docs/prompts/ops-batch-5A-p0.md` (new)
- **Result:** DONE
- **Commits:** (filled by commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:**
  - `Plans/admin_refresh_system_design.md` referenced by audit BLOCK-4 **does not exist** in this branch → mig-05 BLOCKED pending doc recovery.
  - `rotating_audit_schedule.md` referenced by user prompt **does not exist** in this branch → ops-18 BLOCKED pending doc recovery.
  - `docs/UPDATE_FUNCTIONS*.md` / `docs/ADMIN_REFRESH*.md` / `docs/REFRESH_SYSTEM*.md` referenced by user prompt as "Update Functions scope artifact" — **none exist**. Phase 2 spec unrecoverable without doc-artifact location confirmed.
  - Audit BLOCK-1 (entity backfill) and BLOCK-3 (legacy-table writes) are **both CLOSED** (`5b501fc` and `12e172b`), but the repo's local commit-message numbering is inverted vs audit numbering. Cross-reference index in `REMEDIATION_PLAN.md` Appendix A captures this.
  - Audit MAJOR-4 (compute_flows.py atomicity) was doc-close-marked at `7ac96b7` via Batch 3 close `87ee955`, but atomicity specifically was not verified in Batch 3 commit log — flagged "LIKELY CLOSED, VERIFY" in Appendix A.
  - Post-merge regressions DIAG-23/24/25/26 all appear CLOSED via `d0a1e51`, `62ad0eb`, `ff1ff71`, `fcf66f2` — confirm in next sanity-check pass.
  - `scripts/update.py` references retired `fetch_nport.py` and missing `unify_positions.py` — stale script not previously tracked (ops-17 added).
  - Makefile `quarterly-update` is missing the 13F load step — already tracked as INF32 (obs-10); reaffirmed via PRECHECK.
- **Parallel-safety validation:** N/A (this session was pure authorship; no Phase 0 prediction to validate against)

---

## 2026-04-20 — Fold admin_refresh_system_design + data_sources into master plan

- **Session name:** prog-01
- **Start:** 2026-04-20 (mid-day)
- **End:** 2026-04-20 (at PR creation)
- **Scope:** fold recovered `docs/admin_refresh_system_design.md` + `docs/data_sources.md` into the master remediation plan; replace Phase 2 placeholder with real scope; reclassify mig-05 BLOCKED → SUPERSEDED-by-Phase-2; resolve migration slot collision via renumber. Zero code changes, zero DB writes.
- **Files touched:**
  - `docs/REMEDIATION_PLAN.md` (Phase 2 section rewritten; Known Risks item 6 updated; Appendix A two rows updated; Appendix D three new file entries; mig-05 row updated; Changelog appended)
  - `docs/REMEDIATION_SESSION_LOG.md` (this entry)
- **Result:** DONE
- **Commits:** (filled by commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:**
  - **Migration slot collision resolved:** Phase 2 migration renumbered from slot 008 (per design doc) → 010. Slot 009 is owned by int-12 (INF28 securities.cusip formal PK). Design doc itself recommends renumbering from 008; this plan's Appendix D drove the choice of 010 over 009.
  - **Protocol → ABC reconciliation decision** is Phase 2-native (not a foundation item). Captured as Phase 2 open design question. `scripts/pipeline/protocol.py` ships three structural `typing.Protocol`s today; design §4 calls for a single ABC with `run()` orchestrator. Deferred to Phase 2 kickoff.
  - **No new foundation-theme items added.** All Phase 2 dependencies already captured in existing theme items — validated by tracing each design-doc "gate list" entry to an existing checklist row. Conservative bias applied: did not invent new theme items for issues that map to existing ones.
  - **`web/README_deploy.md` potential duplicate** of root `README_deploy.md` — surfaced during rescan. ops-05 tracks root `README_deploy.md`. Flag for ops-05 session to decide whether `web/README_deploy.md` is a stale copy to retire or a distinct doc.
  - **mig-05 semantics change** — previously "BLOCK-4 admin refresh pre-restart rework" as a Theme 3 item; now reclassified as SUPERSEDED by the full Phase 2 workstream. Retained as cross-reference anchor in Appendix A.
  - **Appendix D added three file rows**: `scripts/migrations/010_pipeline_refresh_control_plane.py`, `scripts/pipeline/base.py`, `scripts/pipeline/cadence.py` — all attributed to Phase 2 kickoff, no foundation conflicts.
  - **Rescan of 72 repo `.md` files** found no additional scope-carrying docs. Historical / closed / report artifacts dominate the uncovered set (e.g., `docs/ci_fixture_design.md` Phase 0-B1 close-out, `docs/endpoint_classification.md` Phase 4 freeze, `docs/plans/20260412_architecture_review_revision.md` closed revision pass).
- **Parallel-safety validation:** YES — this session's file touch list (`docs/REMEDIATION_PLAN.md`, `docs/REMEDIATION_SESSION_LOG.md`) is within the plan-family scope expected for `prog` sessions (per SESSION_NAMING.md convention). No other worker owns these files during this window. No drift from Phase 0 prediction (prog-01 was anticipated as a doc-authorship-only session).

---

## 2026-04-20 — sec-01-p0 admin token server-side session (Phase 0)

- **Session name:** sec-01-p0
- **Start:** 2026-04-20
- **End:** 2026-04-20
- **Scope:** Phase 0 findings — audit localStorage token model, propose server-side session replacement (MAJOR-11 / D-11).
- **Files touched:** `docs/findings/sec-01-p0-findings.md`
- **Result:** DONE
- **Commits:** `6a98153` (work) → `efd0ee3` (PR #5 merge)
- **Merge status:** merged (PR #5)
- **Follow-ups surfaced:** sec-01-p1 design locked (server-side admin_sessions table, HttpOnly cookie, CSRF token); sec-01-p1 execution queued.
- **Parallel-safety validation:** YES — findings doc only; no code conflict with any parallel worker.

---

## 2026-04-20 — sec-01-p1 admin session implementation (Phase 1)

- **Session name:** sec-01-p1
- **Start:** 2026-04-20
- **End:** 2026-04-20
- **Scope:** replace admin token localStorage with server-side session (migration 009 admin_sessions + admin_bp.py cookie flow + admin.html login UX).
- **Files touched:** `scripts/admin_bp.py`, `scripts/migrations/009_admin_sessions.py` (new), `web/templates/admin.html`
- **Result:** DONE
- **Commits:** `e68dc94` (work) → `0b3e7d4` (PR #7 merge)
- **Merge status:** merged (PR #7)
- **Follow-ups surfaced:** post-merge DuckDB 1.4.4 catalog race on ATTACH adm (resolved by hotfix + attach-fix); concurrent-login UX glitch (resolved by ux PR).
- **Parallel-safety validation:** YES — admin_bp.py touch matches Appendix D Theme-4 Batch-A prediction; no parallel worker held admin_bp.py during this window.

---

## 2026-04-20 — sec-01-p1-hotfix admin_sessions DB isolation

- **Session name:** sec-01-p1-hotfix
- **Start:** 2026-04-20
- **End:** 2026-04-20
- **Scope:** split admin_sessions into its own DuckDB file + add UPDATE-contention guard to eliminate catalog race observed post-p1.
- **Files touched:** `scripts/admin_bp.py`, `.gitignore`
- **Result:** DONE
- **Commits:** `10f9e4e` (work) → `386ef36` (PR #9 merge)
- **Merge status:** merged (PR #9)
- **Follow-ups surfaced:** single-lock login coalesce (sec-01-p1-ux); ATTACH serialization (sec-01-p1-attach-fix).
- **Parallel-safety validation:** YES — same admin_bp.py single-owner zone as sec-01-p1.

---

## 2026-04-20 — sec-01-p1-ux login-prompt coalescing

- **Session name:** sec-01-p1-ux
- **Start:** 2026-04-20
- **End:** 2026-04-20
- **Scope:** coalesce simultaneous admin login prompts behind a single client-side lock to prevent duplicate auth dialogs on page load.
- **Files touched:** `web/templates/admin.html`
- **Result:** DONE
- **Commits:** `242fedf` (work) → `483de7f` (PR #10 merge)
- **Merge status:** merged (PR #10)
- **Follow-ups surfaced:** none — UX regression fully cleared.
- **Parallel-safety validation:** YES — admin.html single-owner during sec-01 family window.

---

## 2026-04-21 — sec-01-p1-attach-fix serialize ATTACH adm

- **Session name:** sec-01-p1-attach-fix
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** serialize ATTACH adm across Flask worker threads to eliminate DuckDB 1.4.4 catalog race (final sec-01 stabilization).
- **Files touched:** `scripts/admin_bp.py`
- **Result:** DONE
- **Commits:** `369771d` (work) → `d681bf1` (PR #21 merge)
- **Merge status:** merged (PR #21)
- **Follow-ups surfaced:** none — sec-01 is now CLOSED end-to-end.
- **Parallel-safety validation:** YES — admin_bp.py touch conflict with concurrent sec-02-p1-testfix avoided by strict serial merge order (sec-02-p1-testfix merged as PR #19 before this PR #21).

---

## 2026-04-21 — sec-02-p0 /run_script TOCTOU audit (Phase 0)

- **Session name:** sec-02-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — document TOCTOU race in admin `/run_script` allowlist validation (MAJOR-10 / C-11); recommend fcntl.flock guard.
- **Files touched:** `docs/findings/sec-02-p0-findings.md`
- **Result:** DONE
- **Commits:** `a72e1ab` (work) → `595a9da` (PR #11 merge)
- **Merge status:** merged (PR #11)
- **Follow-ups surfaced:** sec-02-p1 implementation scope locked (flock over cached script allowlist hash).
- **Parallel-safety validation:** YES — findings-only doc; no code conflict.

---

## 2026-04-21 — sec-02-p1 fcntl.flock guard for TOCTOU

- **Session name:** sec-02-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** implement fcntl.flock guard around script resolution + subprocess spawn in admin `/run_script`; add regression test suite.
- **Files touched:** `scripts/admin_bp.py`, `tests/test_admin_run_script.py` (new)
- **Result:** DONE
- **Commits:** `94dd51a` (work) → `aa400b7` (PR #14 merge)
- **Merge status:** merged (PR #14)
- **Follow-ups surfaced:** new test exposed ATTACH adm session-auth race under concurrent test fixture load (resolved in sec-02-p1-testfix).
- **Parallel-safety validation:** YES — admin_bp.py still within Theme-4 Batch-A single-owner zone; sec-01 and sec-02 were explicitly sequenced (not parallelized) per Appendix D.

---

## 2026-04-21 — sec-02-p1-testfix isolate flock test

- **Session name:** sec-02-p1-testfix
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** isolate the flock regression test from session-auth ATTACH adm race by giving it a dedicated temp DB + mocked session layer.
- **Files touched:** `tests/test_admin_run_script.py`
- **Result:** DONE
- **Commits:** `0f93859` (work) → `a865972` (PR #19 merge)
- **Merge status:** merged (PR #19)
- **Follow-ups surfaced:** race observed here motivated sec-01-p1-attach-fix ATTACH serialization.
- **Parallel-safety validation:** YES — test-only file, disjoint from any parallel worker.

---

## 2026-04-21 — sec-03-p0 admin write-surface audit (Phase 0)

- **Session name:** sec-03-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — inventory all admin_bp.py write endpoints (MAJOR-5 / C-09); identify `/add_ticker` race + `/entity_override` missing-idempotency gap.
- **Files touched:** `docs/findings/sec-03-p0-findings.md`
- **Result:** DONE
- **Commits:** `0aa442d` (work) → `6b0bc5c` (PR #16 merge)
- **Merge status:** merged (PR #16)
- **Follow-ups surfaced:** sec-03-p1 scope locked — flock guard on `/add_ticker`, input validation, 409 on `/entity_override` duplicates.
- **Parallel-safety validation:** YES — findings-only doc.

---

## 2026-04-21 — sec-03-p1 /add_ticker flock + /entity_override 409

- **Session name:** sec-03-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** add flock guard + validation on `/add_ticker`; return 409 on `/entity_override` duplicate writes; add test coverage.
- **Files touched:** `scripts/admin_bp.py`, `tests/test_admin_add_ticker.py` (new)
- **Result:** DONE
- **Commits:** `f6fe25a` (work) → `e4c0409` (PR #17 merge)
- **Merge status:** merged (PR #17)
- **Follow-ups surfaced:** none — sec-03 fully closed.
- **Parallel-safety validation:** YES — admin_bp.py still serialized with other Theme-4 items (sec-01/02/03 all share this file per Appendix D; all ran serially, no parallel conflict).

---

## 2026-04-20 — obs-03-p0 market impact_id allocation audit (Phase 0)

- **Session name:** obs-03-p0
- **Start:** 2026-04-20
- **End:** 2026-04-20
- **Scope:** Phase 0 findings — diagnose fetch_market impact_id allocation fragility (MAJOR-13 / P-04); propose centralized id_allocator + DROP DEFAULT nextval plan.
- **Files touched:** `docs/findings/obs-03-p0-findings.md`
- **Result:** DONE
- **Commits:** `57f04ff` (work) → `39abb50` (PR #8 merge)
- **Merge status:** merged (PR #8)
- **Follow-ups surfaced:** obs-03-p1 scope locked (new `pipeline/id_allocator.py` module + migration 010 dropping nextval defaults).
- **Parallel-safety validation:** YES — findings-only; ran in parallel with sec-01 family (disjoint files).

---

## 2026-04-21 — obs-03-p1 centralized id_allocator

- **Session name:** obs-03-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** implement `pipeline/id_allocator.py` as the single source of truth for manifest/impacts ID issuance; drop nextval DEFAULT columns via migration 010; repoint promote_13dg.py + promote_nport.py.
- **Files touched:** `scripts/pipeline/id_allocator.py` (new), `scripts/pipeline/manifest.py`, `scripts/pipeline/shared.py`, `scripts/promote_13dg.py`, `scripts/promote_nport.py`, `scripts/migrations/010_drop_nextval_defaults.py` (new), `tests/pipeline/test_id_allocator.py` (new)
- **Result:** DONE
- **Commits:** `18a6e2a` (work) → `cf508a8` (PR #12 merge)
- **Merge status:** merged (PR #12)
- **Follow-ups surfaced:** migration 010 slot collision with Phase 2 kickoff — resolved at plan-level (Phase 2 migration renumbered in prog-01); this obs-03 migration 010 is the live artifact.
- **Parallel-safety validation:** PARTIAL — Appendix D predicted obs-03 would touch `pipeline/manifest.py`; actual scope also touched `pipeline/shared.py` (which is owned by int-21 + sec-04). Drift acceptable here because only the nextval-DEFAULT removal was touched (no overlap with int-21/sec-04 logic zones); flagged for future runs that worked id_allocator migration widened file-touch set vs prediction.

---

## 2026-04-21 — obs-01-p0 N-CEN + ADV manifest registration (Phase 0)

- **Session name:** obs-01-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — document how to register N-CEN + ADV fetchers into ingestion_manifest (MAJOR-9 / D-07/P-05); scope Phase 1 implementation.
- **Files touched:** `docs/findings/obs-01-p0-findings.md`
- **Result:** DONE (Phase 0 only; obs-01-p1 still OPEN)
- **Commits:** `9eb230d` (work) → `8d704c1` (PR #20 merge)
- **Merge status:** merged (PR #20)
- **Follow-ups surfaced:** obs-01-p1 queued — fetch_ncen.py + fetch_adv.py manifest registration + migrations/001 ingestion_manifest row-shape alignment.
- **Parallel-safety validation:** YES — findings-only doc; ran parallel with int-04-p0 (disjoint files).

---

## 2026-04-21 — int-01-p0 OpenFIGI foreign-exchange filter audit (Phase 0)

- **Session name:** int-01-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — RC1 root cause of foreign-exchange tickers leaking through OpenFIGI filter (BLOCK-SEC-AUD-1); propose US-exchange whitelist expansion.
- **Files touched:** `docs/findings/int-01-p0-findings.md`
- **Result:** DONE
- **Commits:** `82a39e5` (work) → `460a599` (PR #13 merge)
- **Merge status:** merged (PR #13)
- **Follow-ups surfaced:** int-01-p1 scope locked (whitelist patch + re-queue one-off script for ~38K affected rows).
- **Parallel-safety validation:** YES — findings-only; ran parallel with sec-02 family.

---

## 2026-04-21 — int-01-p1 whitelist patch + CUSIP re-queue

- **Session name:** int-01-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** expand US-preferred exchange whitelist in `cusip_classifier.py`; ship `scripts/oneoff/int_01_requeue.py` to re-queue affected CUSIPs through OpenFIGI; data sweep executed.
- **Files touched:** `scripts/pipeline/cusip_classifier.py`, `scripts/oneoff/int_01_requeue.py` (new), `tests/pipeline/test_openfigi_us_preferred.py` (new)
- **Result:** DONE — data sweep complete; 216 residual CUSIPs confirmed as legitimate foreign-only (accepted).
- **Commits:** `2066682` (work) → `885c512` (PR #15 merge)
- **Merge status:** merged (PR #15)
- **Follow-ups surfaced:** 216-row foreign-only residual documented; no further action on int-01 itself.
- **Parallel-safety validation:** YES — Appendix D predicted `scripts/pipeline/cusip_classifier.py` as int-01/int-23 shared zone; no parallel int-23 worker ran during this window. Prediction held.

---

## 2026-04-21 — int-04-p0 issuer_name propagation audit (Phase 0)

- **Session name:** int-04-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — RC4 scope guard on issuer_name propagation (BLOCK-SEC-AUD-4); determine correct point of injection (build_cusip.py vs normalize_securities.py).
- **Files touched:** `docs/findings/int-04-p0-findings.md`
- **Result:** DONE — diagnosis landed on build_cusip.py as the single correct injection site.
- **Commits:** `88406d4` (work) → `c6bcd31` (PR #18 merge)
- **Merge status:** merged (PR #18)
- **Follow-ups surfaced:** int-04-p1 scope narrowed: add issuer_name to the build_cusip.py propagation step only (no normalize_securities.py edit needed).
- **Parallel-safety validation:** YES — findings-only; ran parallel with obs-01-p0.

---

## 2026-04-21 — int-04-p1 issuer_name build_cusip propagation

- **Session name:** int-04-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** add issuer_name to the build_cusip.py propagation set; add regression test.
- **Files touched:** `scripts/build_cusip.py`, `tests/pipeline/test_issuer_propagation.py` (new)
- **Result:** DONE
- **Commits:** `f2ce10d` (work) → `b14b332` (PR #22 merge)
- **Merge status:** merged (PR #22)
- **Follow-ups surfaced:** none — int-04 closed.
- **Parallel-safety validation:** YES — Appendix D predicted int-01 (RC1) and int-04 (RC4) share `scripts/build_cusip.py`. Sequencing held: int-01-p1 merged before int-04-p1; no concurrent edits.

---

## 2026-04-20 — ops-batch-5A-p0 doc hygiene sweep

- **Session name:** ops-batch-5A-p0
- **Start:** 2026-04-20
- **End:** 2026-04-20
- **Scope:** close ops-01 through ops-12 in a single batch — doc hygiene sweep across README, PHASE prompts, ARCH_REVIEW, README_deploy, CLASSIFICATION_METHODOLOGY, ROADMAP, and a docs-only migration 007 footnote.
- **Files touched:** `README.md`, `README_deploy.md`, `ARCHITECTURE_REVIEW.md`, `PHASE3_PROMPT.md`, `PHASE4_PROMPT.md`, `ROADMAP.md`, `docs/CLASSIFICATION_METHODOLOGY.md`, `docs/canonical_ddl.md`, `scripts/migrations/007_override_new_value_nullable.py`, `docs/findings/ops-batch-5A-p0-findings.md` (new)
- **Result:** DONE — ops-01, ops-02, ops-03, ops-04, ops-05, ops-07, ops-08, ops-10, ops-11, ops-12 all closed.
- **Commits:** `0bfa7fd` (work) → `4721372` (PR #6 merge)
- **Merge status:** merged (PR #6)
- **Follow-ups surfaced:** ops-06, ops-09, ops-13, ops-14, ops-15, ops-16 still OPEN (Batches 5-B/C/D); no new items surfaced.
- **Parallel-safety validation:** YES — ran fully in parallel with sec-01-p0 + obs-03-p0; all three PRs merged same window with zero file overlap (confirmed vs Appendix D).

---

## 2026-04-21 — conv-01 convergence doc update

- **Session name:** conv-01
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** batch doc update reflecting work completed in PRs #5 through #22 (18 PRs merged). Flip CHECKLIST items to [x] for sec-01, sec-02, sec-03, obs-03, int-01, int-04, ops-01..ops-12. Append one session-log entry per completed session. Update REMEDIATION_PLAN.md changelog.
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** none — pure doc reconciliation.
- **Parallel-safety validation:** YES — docs-only; no parallel worker holds these three files.
