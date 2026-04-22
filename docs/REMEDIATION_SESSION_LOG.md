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

---

## 2026-04-21 — sec-04-p0 validators writing to prod (Phase 0)

- **Session name:** sec-04-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — audit validator scripts that mutate prod as a side effect of validation (MAJOR-1 / C-02); scope read-only default + separate validate-vs-queue split.
- **Files touched:** `docs/findings/sec-04-p0-findings.md`
- **Result:** DONE
- **Commits:** `88341fb` (work) → `a38f3aa` (PR #24 merge)
- **Merge status:** merged (PR #24)
- **Follow-ups surfaced:** sec-04-p1 scope locked — default validators to RO; extract queue_nport_excluded.py as the single write-bearing script.
- **Parallel-safety validation:** YES — findings-only doc; ran parallel with obs-01-p1.

---

## 2026-04-21 — sec-04-p1 validators RO default + split validate/queue

- **Session name:** sec-04-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** default `validate_nport_subset.py` + `validate_entities.py` to read-only; extract write-side into new `queue_nport_excluded.py`; repoint `fetch_dera_nport.py` + `fetch_nport_v2.py` call sites.
- **Files touched:** `scripts/validate_nport_subset.py`, `scripts/validate_entities.py`, `scripts/queue_nport_excluded.py` (new), `scripts/fetch_dera_nport.py`, `scripts/fetch_nport_v2.py`
- **Result:** DONE
- **Commits:** `af66013` (work) → `aa7f6a8` (PR #27 merge)
- **Merge status:** merged (PR #27)
- **Follow-ups surfaced:** none — sec-04 closed.
- **Parallel-safety validation:** PARTIAL — Appendix D predicted sec-04 zone as `validate_nport_subset.py` + `pipeline/shared.py`; actual scope expanded to include `validate_entities.py` + two fetch_* call-site repoints + new `queue_nport_excluded.py`. `pipeline/shared.py` was NOT touched (the write path was extracted to a new module instead). Drift acceptable — no overlap with int-21 (which owns `pipeline/shared.py` series_id logic); flagged so future RO-default refactors anticipate new-module extraction.

---

## 2026-04-21 — obs-01-p1 N-CEN + ADV manifest registration (Phase 1)

- **Session name:** obs-01-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** register `fetch_ncen.py` + `fetch_adv.py` in `ingestion_manifest` + `ingestion_impacts`; complete MAJOR-9 / D-07/P-05.
- **Files touched:** `scripts/fetch_adv.py`, `scripts/fetch_ncen.py`
- **Result:** DONE
- **Commits:** `a12b4d8` (work) → `64c7d41` (PR #25 merge)
- **Merge status:** merged (PR #25)
- **Follow-ups surfaced:** obs-02 (ADV freshness discipline) enters scope with fetch_adv.py now manifest-aware; sequenced next.
- **Parallel-safety validation:** YES — fetch_adv.py + fetch_ncen.py are Batch 2-A zone; obs-02 was explicitly sequenced after obs-01 to avoid fetch_adv.py write conflict.

---

## 2026-04-21 — obs-02-p0 ADV freshness + log discipline (Phase 0)

- **Session name:** obs-02-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — diagnose missing `record_freshness` call + CHECKPOINT ordering in `fetch_adv.py` (MAJOR-12 / P-02); scope Phase 1 guard + reorder.
- **Files touched:** `docs/findings/obs-02-p0-findings.md`
- **Result:** DONE
- **Commits:** `c8320e1` (work) → `0e7b59f` (PR #28 merge)
- **Merge status:** merged (PR #28)
- **Follow-ups surfaced:** obs-02-p1 scope locked — wrap `record_freshness` in try/except and CHECKPOINT after freshness write, not before.
- **Parallel-safety validation:** YES — findings-only; ran parallel with mig-04-p1.

---

## 2026-04-21 — obs-02-p1 guard record_freshness + CHECKPOINT reorder

- **Session name:** obs-02-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** add freshness-write guard + reorder CHECKPOINT after freshness stamp in `fetch_adv.py`.
- **Files touched:** `scripts/fetch_adv.py`
- **Result:** DONE
- **Commits:** `b86096b` (work) → `b690a1f` (PR #30 merge)
- **Merge status:** merged (PR #30)
- **Follow-ups surfaced:** none — obs-02 closed.
- **Parallel-safety validation:** YES — fetch_adv.py single-owner during obs-02 window; no parallel worker held it (obs-01-p1 merged first per sequencing plan).

---

## 2026-04-21 — mig-04-p0 schema_versions stamp hole (Phase 0)

- **Session name:** mig-04-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — audit which migrations shipped without schema_versions stamps (MAJOR-16 / S-02); scope one-off backfill + verify tool.
- **Files touched:** `docs/findings/mig-04-p0-findings.md`
- **Result:** DONE
- **Commits:** `5997345` (work) → `60ed6a1` (PR #26 merge)
- **Merge status:** merged (PR #26)
- **Follow-ups surfaced:** mig-04-p1 scope locked — backfill missing stamps + ship `verify_migration_stamps.py` as permanent CI gate candidate.
- **Parallel-safety validation:** YES — findings-only; ran parallel with sec-04-p1.

---

## 2026-04-21 — mig-04-p1 schema_versions stamp backfill + verify

- **Session name:** mig-04-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** backfill schema_versions stamps for migrations 004 + add_last_refreshed_at; ship `scripts/oneoff/backfill_schema_versions_stamps.py` + `scripts/verify_migration_stamps.py`.
- **Files touched:** `scripts/migrations/004_summary_by_parent_rollup_type.py`, `scripts/migrations/add_last_refreshed_at.py`, `scripts/oneoff/backfill_schema_versions_stamps.py` (new), `scripts/verify_migration_stamps.py` (new)
- **Result:** DONE
- **Commits:** `152aca7` (work) → `caa1de0` (PR #29 merge)
- **Merge status:** merged (PR #29)
- **Follow-ups surfaced:** consider wiring `verify_migration_stamps.py` into smoke CI (candidate for a future mig-11 bundle).
- **Parallel-safety validation:** YES — migrations touched were owned by mig-04 alone; no overlap with other migration-family work.

---

## 2026-04-21 — mig-01-p0 atomic promotes + manifest mirror (Phase 0)

- **Session name:** mig-01-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — diagnose non-atomic promote sequences in `promote_nport.py` + `promote_13dg.py` (BLOCK-2); design `_mirror_manifest_and_impacts` helper extraction.
- **Files touched:** `docs/findings/mig-01-p0-findings.md`
- **Result:** DONE
- **Commits:** `dd03780` (work) → `fab82b2` (PR #31 merge)
- **Merge status:** merged (PR #31)
- **Follow-ups surfaced:** mig-01-p1 scope locked — single BEGIN/COMMIT around manifest + impacts + data inserts; helper lifted to `pipeline/manifest.py`.
- **Parallel-safety validation:** YES — findings-only.

---

## 2026-04-21 — mig-01-p1 atomic promotes + manifest mirror extraction

- **Session name:** mig-01-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** wrap promote_nport.py + promote_13dg.py in atomic transactions; extract `_mirror_manifest_and_impacts` helper into `pipeline/manifest.py` as the shared call site.
- **Files touched:** `scripts/pipeline/manifest.py`, `scripts/promote_13dg.py`, `scripts/promote_nport.py`
- **Result:** DONE
- **Commits:** `56dcfcb` (work) → `b2765b4` (PR #33 merge)
- **Merge status:** merged (PR #33)
- **Follow-ups surfaced:** none — mig-01 (BLOCK-2) closed. Theme-3 migration work formally begun.
- **Parallel-safety validation:** YES — `pipeline/manifest.py` was touched earlier by obs-03-p1 (id_allocator integration); mig-01-p1 appended new helper without colliding with id_allocator zones. Sequential merge ordering held.

---

## 2026-04-21 — ops-batch-5B doc updates

- **Session name:** ops-batch-5B
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** close ops-06 + ops-09 + ops-15 in one batch — refresh `docs/write_path_risk_map.md`, ship new `docs/api_architecture.md` (Blueprint split), and add §Refetch Pattern to `MAINTENANCE.md`.
- **Files touched:** `docs/write_path_risk_map.md`, `docs/api_architecture.md` (new), `MAINTENANCE.md`, `docs/findings/ops-batch-5B-findings.md` (new)
- **Result:** DONE — ops-06, ops-09, ops-15 all closed.
- **Commits:** `1a47a0e` (work) → `b45893f` (PR #32 merge)
- **Merge status:** merged (PR #32)
- **Follow-ups surfaced:** ops-13, ops-14, ops-16 still OPEN (Batches 5-C/D).
- **Parallel-safety validation:** YES — docs-only; ran parallel with mig-01-p1 with zero file overlap.

---

## 2026-04-21 — conv-02 convergence doc update

- **Session name:** conv-02
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** batch doc update reflecting work completed in PRs #24 through #33 (10 PRs merged since conv-01; 29 PRs total across the program). Flip CHECKLIST items to [x] for sec-04, obs-01, obs-02, mig-01, mig-04, ops-06, ops-09, ops-15. Append one session-log entry per completed session. Update REMEDIATION_PLAN.md changelog.
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** Theme 4 security now substantially complete (sec-01/02/03/04 all closed; sec-05/06/07/08 remain). Theme 3 migration formally begun (mig-01 + mig-04 closed; mig-02/03/13/14 and Batches 3-C/D remain). Theme 2 observability mostly closed (obs-01/02/03 done; obs-04/06/07/10 and doc items remain).
- **Parallel-safety validation:** YES — docs-only; no parallel worker holds these three files.

---

## 2026-04-21 — mig-02-p0 fetch_adv.py staging split (Phase 0)

- **Session name:** mig-02-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — diagnose DROP-before-CREATE window in `fetch_adv.py:247-249` (MAJOR-14); scope staging→promote split as the atomic fix (supersedes naive `CREATE OR REPLACE TABLE`).
- **Files touched:** `docs/findings/mig-02-p0-findings.md`
- **Result:** DONE
- **Commits:** `9b48635` (PR #35 squash-merge)
- **Merge status:** merged (PR #35)
- **Follow-ups surfaced:** mig-02-p1 scope locked — route fetch_adv.py through staging DB + promote step; eliminates DROP window entirely. Also closes fetch_adv portion of mig-13.
- **Parallel-safety validation:** YES — findings-only doc; ran parallel with obs-04-p0.

---

## 2026-04-21 — obs-04-p0 13D/G ingestion_impacts backfill (Phase 0)

- **Session name:** obs-04-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — diagnose 3-row vs 51,905-BO-row grain mismatch in `ingestion_impacts` (MAJOR-8 / D-06); scope one-off backfill script for pre-v2 13D/G history.
- **Files touched:** `docs/findings/obs-04-p0-findings.md`
- **Result:** DONE
- **Commits:** `cb91ef2` (PR #36 squash-merge)
- **Merge status:** merged (PR #36)
- **Follow-ups surfaced:** obs-04-p1 scope locked — one-off backfill script gated behind `--confirm`; data op deferred.
- **Parallel-safety validation:** YES — findings-only; ran parallel with mig-02-p0.

---

## 2026-04-21 — mig-02-p1 fetch_adv.py staging→promote conversion

- **Session name:** mig-02-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** convert `fetch_adv.py` to the staging→promote pattern — fetch writes to staging DB, promote step moves rows to prod under a single atomic swap.
- **Files touched:** `scripts/fetch_adv.py`, `scripts/promote_staging.py` (promote entry wired)
- **Result:** DONE
- **Commits:** `db1fdb8` (PR #37 squash-merge)
- **Merge status:** merged (PR #37)
- **Follow-ups surfaced:** mig-02 closed; also closes fetch_adv portion of mig-13 (pipeline-violations REWRITE tail).
- **Parallel-safety validation:** YES — fetch_adv.py single-owner in this window (obs-02 family already merged per prior sequencing).

---

## 2026-04-21 — obs-04-p1 one-off ingestion_impacts backfill script

- **Session name:** obs-04-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** ship `scripts/oneoff/backfill_13dg_impacts.py` as the retro-mirror tool for pre-v2 13D/G history; script gated behind `--confirm`. Data op deferred.
- **Files touched:** `scripts/oneoff/backfill_13dg_impacts.py` (new)
- **Result:** DONE (code only; data op pending `--confirm`)
- **Commits:** `659f5c4` (PR #38 squash-merge)
- **Merge status:** merged (PR #38)
- **Follow-ups surfaced:** backfill data op pending Serge approval + `--confirm` execution window.
- **Parallel-safety validation:** YES — new-file scope; no parallel worker conflict.

---

## 2026-04-21 — sec-07-p1 pin edgartools + pdfplumber

- **Session name:** sec-07-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** pin `edgartools` and `pdfplumber` in `requirements.txt` (MINOR-15 / O-02). Single session — no Phase 0 required given trivial scope.
- **Files touched:** `requirements.txt`
- **Result:** DONE
- **Commits:** `1f888c3` (PR #39 squash-merge)
- **Merge status:** merged (PR #39)
- **Follow-ups surfaced:** none — sec-07 closed.
- **Parallel-safety validation:** YES — requirements.txt single-owner in Batch 4-D window.

---

## 2026-04-21 — sec-08-p0 central EDGAR identity config (Phase 0)

- **Session name:** sec-08-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — inventory all `User-Agent` + EDGAR identity strings across fetcher scripts (MINOR-17 / O-08); scope central config extraction.
- **Files touched:** `docs/findings/sec-08-p0-findings.md`
- **Result:** DONE — 21 scripts targeted (not 22 as originally scoped).
- **Commits:** `47266ad` (PR #40 squash-merge)
- **Merge status:** merged (PR #40)
- **Follow-ups surfaced:** sec-08-p1 scope locked — add `EDGAR_IDENTITY` helper to `scripts/config.py` and normalize 21 call sites.
- **Parallel-safety validation:** YES — findings-only; ran parallel with sec-07-p1.

---

## 2026-04-21 — sec-08-p1 centralize EDGAR identity

- **Session name:** sec-08-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** add `EDGAR_IDENTITY` helper to `scripts/config.py`; normalize 21 fetcher scripts to consume it.
- **Files touched:** `scripts/config.py`, 21 fetcher scripts (call-site normalization)
- **Result:** DONE
- **Commits:** `fa01c7e` (PR #41 squash-merge)
- **Merge status:** merged (PR #41)
- **Follow-ups surfaced:** none — sec-08 closed.
- **Parallel-safety validation:** PARTIAL — Appendix D predicted ~22 scripts; actual touch count was 21 (one script already used a different UA convention and was out-of-scope). Drift minor; direction consistent with prediction.

---

## 2026-04-21 — merge-wave-4

- **Session name:** merge-wave-4
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** merge coordination — sequential squash-merge of PRs #35, #36, #37, #38, #39, #40, #41 (mig-02 + obs-04 + sec-07 + sec-08 families).
- **Files touched:** N/A (merge operations only)
- **Result:** DONE
- **Commits:** `9b48635`, `cb91ef2`, `db1fdb8`, `659f5c4`, `1f888c3`, `47266ad`, `fa01c7e`
- **Merge status:** all merged to main
- **Follow-ups surfaced:** none — clean wave; no conflicts; no post-merge regressions.
- **Parallel-safety validation:** YES — merge ordering respected Appendix D single-owner zones.

---

## 2026-04-21 — int-10-p0 OpenFIGI _update_error() bug (Phase 0)

- **Session name:** int-10-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — diagnose INF26 permanent-pending bug in `run_openfigi_retry.py:_update_error()` (never flips `status='unmappable'` at MAX_ATTEMPTS).
- **Files touched:** `docs/findings/int-10-p0-findings.md`
- **Result:** DONE
- **Commits:** `4072d9e` (PR #42 squash-merge)
- **Merge status:** merged (PR #42)
- **Follow-ups surfaced:** int-10-p1 scope locked — flip to `'unmappable'` at MAX_ATTEMPTS + one-off sweep for historical permanent-pending residue (`--confirm`-gated).
- **Parallel-safety validation:** YES — findings-only.

---

## 2026-04-21 — sec-05-p0 hardcoded-prod builders audit (Phase 0)

- **Session name:** sec-05-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — audit `build_managers.py`, `build_fund_classes.py`, `build_benchmark_weights.py` for hardcoded prod routing (MAJOR-2 / C-04).
- **Files touched:** `docs/findings/sec-05-p0-findings.md`
- **Result:** DONE — key finding: `build_managers.py` is already fully staged (plan claim "routing pending" is stale); only `build_fund_classes.py` + `build_benchmark_weights.py` need the `--staging` path fix.
- **Commits:** `8951117` (PR #43 squash-merge)
- **Merge status:** merged (PR #43)
- **Follow-ups surfaced:** sec-05-p1 scope narrowed to two scripts; plan row sec-05 needs the "routing pending" note updated to reflect already-staged reality.
- **Parallel-safety validation:** YES — findings-only.

---

## 2026-04-21 — int-10-p1 _update_error fix + one-off sweep

- **Session name:** int-10-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** patch `_update_error()` to flip `status='unmappable'` at MAX_ATTEMPTS; ship `scripts/oneoff/int_10_sweep.py` for historical permanent-pending residue (`--confirm`-gated).
- **Files touched:** `scripts/run_openfigi_retry.py`, `scripts/oneoff/int_10_sweep.py` (new)
- **Result:** DONE (code only; staging sweep pending `--confirm`)
- **Commits:** `95f74f2` (PR #44 squash-merge)
- **Merge status:** merged (PR #44)
- **Follow-ups surfaced:** staging sweep pending Serge approval + `--confirm` execution.
- **Parallel-safety validation:** YES — `run_openfigi_retry.py` single-owner in this window.

---

## 2026-04-21 — sec-05-p1 --staging path fix

- **Session name:** sec-05-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** fix `--staging` path for `build_fund_classes.py` + `build_benchmark_weights.py`; eliminates hardcoded prod routing in both.
- **Files touched:** `scripts/build_fund_classes.py`, `scripts/build_benchmark_weights.py`
- **Result:** DONE
- **Commits:** `742d504` (PR #45 squash-merge)
- **Merge status:** merged (PR #45)
- **Follow-ups surfaced:** none — sec-05 closed end-to-end (build_managers already staged; fund_classes + benchmark_weights now also staged).
- **Parallel-safety validation:** YES — two disjoint scripts; no overlap with int-10-p1 or merge-wave-5.

---

## 2026-04-21 — merge-wave-5

- **Session name:** merge-wave-5
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** merge coordination — sequential squash-merge of PRs #42, #43, #44, #45 (int-10 + sec-05 families).
- **Files touched:** N/A (merge operations only)
- **Result:** DONE
- **Commits:** `4072d9e`, `8951117`, `95f74f2`, `742d504`
- **Merge status:** all merged to main
- **Follow-ups surfaced:** none — clean wave.
- **Parallel-safety validation:** YES.

---

## 2026-04-21 — int-05-p0 retroactive Pass C sweep (Phase 0, NO-OP)

- **Session name:** int-05-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — investigate BLOCK-TICKER-BACKFILL Phase 1a retroactive Pass C sweep; determine whether any residual work remains.
- **Files touched:** `docs/findings/int-05-p0-findings.md`
- **Result:** DONE — **CLOSED AS NO-OP.** Retroactive Pass C sweep was already executed in an earlier session; no residual rows remain. int-05 closes without a p1.
- **Commits:** `98dc28e` (PR #46 squash-merge)
- **Merge status:** merged (PR #46)
- **Follow-ups surfaced:** none — int-05 closed as NO-OP. int-06 (forward-looking hooks) remains open per normal sequencing.
- **Parallel-safety validation:** YES — findings-only.

---

## 2026-04-21 — sec-06-p0 direct-to-prod writers inventory (Phase 0)

- **Session name:** sec-06-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — inventory 5 direct-to-prod writers (MAJOR-3 / C-05): `resolve_agent_names.py`, `resolve_bo_agents.py`, `resolve_names.py`, `backfill_manager_types.py`, `enrich_tickers.py`. Decide stage-vs-retire per script.
- **Files touched:** `docs/findings/sec-06-p0-findings.md`
- **Result:** DONE — 3 scripts confirmed dead (retire); 2 scripts are live writers (harden).
- **Commits:** `507f30c` (PR #47 squash-merge)
- **Merge status:** merged (PR #47)
- **Follow-ups surfaced:** sec-06-p1 scope locked — retire `resolve_agent_names.py` + `resolve_bo_agents.py` + `resolve_names.py` to `scripts/retired/`; harden `backfill_manager_types.py` + `enrich_tickers.py`.
- **Parallel-safety validation:** YES — findings-only.

---

## 2026-04-21 — sec-06-p1 retire + harden direct-to-prod writers

- **Session name:** sec-06-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** move 3 dead resolver scripts to `scripts/retired/`; harden `backfill_manager_types.py` + `enrich_tickers.py`; update `docs/pipeline_violations.md` with 6 RETIRED + 11 RETROFIT markers.
- **Files touched:** `scripts/retired/resolve_agent_names.py` (moved), `scripts/retired/resolve_bo_agents.py` (moved), `scripts/retired/resolve_names.py` (moved), `scripts/backfill_manager_types.py`, `scripts/enrich_tickers.py`, `docs/pipeline_violations.md`
- **Result:** DONE
- **Commits:** `b716cf4` (PR #48 squash-merge)
- **Merge status:** merged (PR #48)
- **Follow-ups surfaced:** none — sec-06 closed. Theme 4 security now fully closed (8/8 items).
- **Parallel-safety validation:** YES — 5-script touch set matches Appendix D prediction exactly.

---

## 2026-04-21 — merge-wave-6

- **Session name:** merge-wave-6
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** merge coordination — sequential squash-merge of PRs #46, #47, #48 (int-05 NO-OP + sec-06 family). Included stale-worktree cleanup (4 worktrees removed) and local branch deletion for int-05/int-10/sec-05/sec-06.
- **Files touched:** N/A (merge operations only)
- **Result:** DONE
- **Commits:** `98dc28e`, `507f30c`, `b716cf4`
- **Merge status:** all merged to main
- **Follow-ups surfaced:** Theme 4 fully closed; int-05 closed as NO-OP; conv-03 convergence session triggered.
- **Parallel-safety validation:** YES.

---

## 2026-04-21 — int-02-p0 RC2 mode aggregator status + re-seed gap (Phase 0, CLOSE)

- **Session name:** int-02-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — confirm RC2 code status (commit `fc2bbbc`), quantify the MAX→MODE residual gap in prod `cusip_classifications`, and decide on re-seed path.
- **Files touched:** `docs/findings/int-02-p0-findings.md`, `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/NEXT_SESSION_CONTEXT.md`, `ROADMAP.md`
- **Result:** DONE — **CLOSED AS CODE-COMPLETE.** `fc2bbbc` (2026-04-18) already shipped the mode+length+alpha aggregator in `cusip_classifier.get_cusip_universe()`; HEAD reflects it. Prod `cusip_classifications` (seeded 2026-04-14, four days before the fix) carries an 8,178-row (6.17%) residual MAX-era gap: 2,600 cosmetic, 248 classic RC2 first-letter-clip rescues, 618 superstring improvements, 771 superstring shortenings, 2,051 distinct-first-word flips (upstream CUSIP contamination, fc2bbbc's "known limitation"), 1,890 other. **Option A (no re-seed now) selected** — organic convergence via future universe expansion (int-23) or routine `--reset` runs is acceptable; the 2,051-row distinct-first-word bucket is a data-quality investigation out of remediation scope. int-02 closes without a p1.
- **Commits:** PR #50 (pending merge at log-write time)
- **Merge status:** PR #50 open; both CI checks (pre-commit + smoke) passing; awaiting merge-wave
- **Follow-ups surfaced:** none blocking. Filed as informational: the 2,051 distinct-first-word CUSIPs warrant a standalone data-quality investigation if and when int-23 universe expansion forces a full re-seed.
- **Parallel-safety validation:** YES — findings-only; ran solo.
