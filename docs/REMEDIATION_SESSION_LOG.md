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
- **Commits:** `90456da` (work) → `269fec5` (PR #50 squash-merge)
- **Merge status:** merged (PR #50)
- **Follow-ups surfaced:** none blocking. Filed as informational: the 2,051 distinct-first-word CUSIPs warrant a standalone data-quality investigation if and when int-23 universe expansion forces a full re-seed.
- **Parallel-safety validation:** YES — findings-only; ran solo.

---

## 2026-04-21 — conv-03 convergence doc update

- **Session name:** conv-03
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** batch doc update reflecting work completed in PRs #35 through #48 (14 PRs merged since conv-02). Flip CHECKLIST items for mig-02, obs-04, sec-05, sec-06, sec-07, sec-08, int-05, int-10. Append session-log entries for all worker sessions + merge-wave-4/5/6. Update REMEDIATION_PLAN.md item-table statuses + changelog entry. Theme 4 security milestone marked (8/8 closed).
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** `60eda6e` (work) → `21c6dc2` (PR #49 squash-merge)
- **Merge status:** merged (PR #49)
- **Follow-ups surfaced:** remaining obs-06/07/10 + int-02 closeouts queued for next convergence (conv-04).
- **Parallel-safety validation:** YES — docs-only; no parallel worker holds these three files.

---

## 2026-04-21 — obs-07-p0 N-PORT report_month future-leakage gate (Phase 0)

- **Session name:** obs-07-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings — scope a preventive gate in `promote_nport.py` that rejects rows whose `report_month` is in the future (MINOR-4 / P-07). Confirm existing data is clean; no historical residual detected.
- **Files touched:** `docs/findings/obs-07-p0-findings.md`
- **Result:** DONE
- **Commits:** `cfd3515` (PR #51 squash-merge)
- **Merge status:** merged (PR #51)
- **Follow-ups surfaced:** obs-07-p1 scope locked — guard in promote_nport.py; emit one row per rejection with filing_id + raw report_month.
- **Parallel-safety validation:** YES — findings-only.

---

## 2026-04-21 — obs-10-p1 Makefile quarterly-update 13F + ADV wiring

- **Session name:** obs-10-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** wire `load-13f` + `promote-adv` targets into the `quarterly-update` Makefile recipe (INF32); prune retired `scripts/update.py` references from same recipe.
- **Files touched:** `Makefile`
- **Result:** DONE
- **Commits:** `b5c04aa` (PR #52 squash-merge)
- **Merge status:** merged (PR #52)
- **Follow-ups surfaced:** none — obs-10 closed. `scripts/update.py` retirement (ops-17) still Phase 2 scope; references now fully pruned from Makefile.
- **Parallel-safety validation:** YES — Makefile single-owner in this window.

---

## 2026-04-21 — obs-07-p1 report_month future-leakage gate

- **Session name:** obs-07-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** add `report_month` future-leakage gate to `promote_nport.py` — reject rows whose `report_month` > current month; per-row logging on rejection; completes MINOR-4 / P-07.
- **Files touched:** `scripts/promote_nport.py`
- **Result:** DONE
- **Commits:** `387b9c2` (PR #53 squash-merge)
- **Merge status:** merged (PR #53)
- **Follow-ups surfaced:** none — obs-07 closed.
- **Parallel-safety validation:** YES — `promote_nport.py` single-owner during obs-07 window (mig-01 already merged per prior sequencing).

---

## 2026-04-21 — obs-06-p1 13F loader freshness (NO-OP)

- **Session name:** obs-06-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** confirm MINOR-3 / P-01 13F loader freshness is already satisfied — `record_freshness(con, 'filings')` + `record_freshness(con, 'filings_deduped')` shipped in `load_13f.py` via `8e7d5cb` prior to this program window.
- **Files touched:** N/A (no code change)
- **Result:** DONE — **closed as already-satisfied / NO-OP.** No PR needed; verification only.
- **Commits:** none (no-op close)
- **Merge status:** N/A
- **Follow-ups surfaced:** none — obs-06 closed.
- **Parallel-safety validation:** N/A — no file touched.

---

## 2026-04-21 — merge-wave-7

- **Session name:** merge-wave-7
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** merge coordination — sequential squash-merge of PRs #49, #50, #51, #52, #53 (conv-03 doc sync + int-02 close + obs-07 family + obs-10).
- **Files touched:** N/A (merge operations only)
- **Result:** DONE
- **Commits:** `21c6dc2`, `269fec5`, `cfd3515`, `b5c04aa`, `387b9c2`
- **Merge status:** all merged to main
- **Follow-ups surfaced:** none — clean wave; no conflicts; no post-merge regressions. conv-04 convergence session triggered.
- **Parallel-safety validation:** YES — merge ordering respected Appendix D single-owner zones.

---

## 2026-04-21 — conv-04 convergence doc update

- **Session name:** conv-04
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** batch doc update reflecting PRs #49 through #53 merged since conv-03 (5 PRs; program-wide total 53 PRs). Flip remaining CHECKLIST items (obs-06 no-op, obs-07, obs-10). Append session-log entries for obs-07-p0/p1, obs-10-p1, obs-06-p1, merge-wave-7, conv-03, conv-04. Update REMEDIATION_PLAN.md item-table statuses (backfill of stale OPEN markers from conv-01/conv-02 window) + append conv-04 changelog entry. Narrow mig-13 residual scope note (fetch_adv closed via mig-02; build_fund_classes + build_benchmark_weights closed via sec-05).
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** (1) item-table Status column in REMEDIATION_PLAN.md for sec-01/02/03/04, obs-01/02/03, mig-01/mig-04, ops-01..ops-12, ops-06/09/15 was still showing OPEN despite being closed in conv-01/conv-02 — backfilled during this session. (2) `scripts/update.py` retirement (ops-17) now has zero Makefile references; standalone retire remains Phase 2 scope. (3) mig-13 residual scope narrowed to build_entities + merge_staging only.
- **Parallel-safety validation:** YES — docs-only; no parallel worker holds these three files.

---

## 2026-04-21 — ops-17-p1 update.py retired-script verify/close

- **Session name:** ops-17-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** verify `scripts/update.py` has zero live references (Makefile pruned by obs-10 PR #52) and close ops-17 as already-satisfied. No standalone retire needed; no code change required.
- **Files touched:** N/A (verification + doc close only)
- **Result:** DONE — **closed as already-satisfied.** Self-update doc close via PR #55.
- **Commits:** `a06729e` (PR #55 squash-merge)
- **Merge status:** merged (PR #55)
- **Follow-ups surfaced:** none — ops-17 closed.
- **Parallel-safety validation:** YES — verification-only, no file conflicts.

---

## 2026-04-21 — obs-09-p1 log-rotation script + Makefile target

- **Session name:** obs-09-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** ship log-rotation script + Makefile target to address 182-file `logs/` backlog (MINOR-18 / O-10).
- **Files touched:** `scripts/rotate_logs.py` (new), `Makefile`
- **Result:** DONE
- **Commits:** `784007a` (PR #56 squash-merge)
- **Merge status:** merged (PR #56)
- **Follow-ups surfaced:** none — obs-09 closed.
- **Parallel-safety validation:** YES — new script + Makefile single-owner in this window.

---

## 2026-04-21 — obs-12-p1 GitHub Actions Node 22+ compatibility

- **Session name:** obs-12-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** verify/upgrade GitHub Actions to Node 22+ (shipped as Node 24) to clear BLOCK-CI-ACTIONS-NODE20-DEPRECATION (INF33).
- **Files touched:** `.github/workflows/*.yml`
- **Result:** DONE
- **Commits:** `44408ba` (PR #57 squash-merge)
- **Merge status:** merged (PR #57)
- **Follow-ups surfaced:** none — obs-12 closed.
- **Parallel-safety validation:** YES — workflow files single-owner in this window.

---

## 2026-04-21 — obs-08-p1 backup-gap investigation + docs + Makefile

- **Session name:** obs-08-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** close MINOR-16 / O-05 backup-gap investigation; document backup state (no infra gap), fix MAINTENANCE.md wording (manual vs `quarterly-update`) + retention note, wire `backup-db` Makefile target. Findings captured in `docs/findings/obs-08-p1-findings.md`.
- **Files touched:** `MAINTENANCE.md`, `Makefile`, `docs/findings/obs-08-p1-findings.md`
- **Result:** DONE
- **Commits:** `c3590d0` (PR #58 squash-merge)
- **Merge status:** merged (PR #58)
- **Follow-ups surfaced:** none — obs-08 closed. PR #58 self-updated the CHECKLIST [x] marker; plan-table status still referenced "PR #TBD" and was corrected in conv-05.
- **Parallel-safety validation:** YES — MAINTENANCE.md + Makefile + findings doc single-owner in this window.

---

## 2026-04-21 — merge-wave-8

- **Session name:** merge-wave-8
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** merge coordination — sequential squash-merge of PRs #55, #56, #57, #58 (ops-17 close + obs-09 + obs-12 + obs-08).
- **Files touched:** N/A (merge operations only)
- **Result:** DONE
- **Commits:** `a06729e`, `784007a`, `44408ba`, `c3590d0`
- **Merge status:** all merged to main
- **Follow-ups surfaced:** none — clean wave; no conflicts; no post-merge regressions. conv-05 convergence session triggered.
- **Parallel-safety validation:** YES — merge ordering respected Appendix D single-owner zones.

---

## 2026-04-21 — conv-05 convergence doc update

- **Session name:** conv-05
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** batch doc update reflecting PRs #55 through #58 merged since conv-04 (4 PRs). Flip CHECKLIST items (obs-09, obs-12, ops-17; correct obs-08 row; obs-08 already self-flipped by PR #58). Append session-log entries for obs-08-p1, obs-09-p1, obs-12-p1, ops-17-p1, merge-wave-8, conv-05. Update REMEDIATION_PLAN.md item-table statuses (obs-08 PR #TBD→#58; obs-09, obs-12, ops-17 OPEN→CLOSED) + append conv-05 changelog entry.
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** (1) Theme 5 ops now 14/18 closed with ops-17 resolving as already-satisfied via obs-10 (no standalone retire needed). (2) Theme 2 observability now 10/13 closed (obs-05, obs-11, obs-13 remaining — obs-13 verify-only). (3) obs-08 row corrected from "PR #TBD" placeholder to actual "PR #58" citation.
- **Parallel-safety validation:** YES — docs-only; no parallel worker holds these three files.

---

## 2026-04-21 — mig-03-p0 migration 004 atomicity (Phase 0)

- **Session name:** mig-03-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings for mig-03 (MAJOR-15 `docs/SYSTEM_AUDIT_2026_04_17.md §11.3`). Document current RENAME → CREATE → INSERT → DROP sequence in `scripts/migrations/004_summary_by_parent_rollup_type.py` with exact line numbers; map every kill-point in the sequence to resulting on-disk state (two critical states identified: kill between RENAME and CREATE leaves canonical table missing; kill between CREATE and INSERT leaves it empty with "already applied" probe subsequently declaring success on zero rows); compare to `scripts/migrations/003_cusip_classifications.py:226-239` (only migration already using BEGIN/try/COMMIT/except/ROLLBACK scaffold); propose Phase 1 scope (single-file change).
- **Files touched:** `docs/findings/mig-03-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #60 merged as `94de1c4`
- **Merge status:** merged
- **Follow-ups surfaced:** Phase 1 locked to single file (`scripts/migrations/004_summary_by_parent_rollup_type.py`); pattern source confirmed as migration 003; no file overlap with ops-12 (migration 007), parallel-safe per REMEDIATION_PLAN.md:230.
- **Parallel-safety validation:** YES — findings doc only; no runtime writes.

---

## 2026-04-21 — mig-03-p1 migration 004 atomicity retrofit

- **Session name:** mig-03-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Wrap migration 004's RENAME→CREATE→INSERT→DROP sequence in a single BEGIN/COMMIT using build-new-and-swap shadow pattern (`summary_by_parent_new`). Move row-count parity check and `schema_versions` stamp inside the transaction — mismatch now rolls back cleanly, and "applied" is coupled with "stamped". Add pre-transaction recovery probe: if pre-fix crash left canonical table missing with `summary_by_parent_old` present, canonical name is restored via RENAME before the transaction runs.
- **Files touched:** `scripts/migrations/004_summary_by_parent_rollup_type.py`
- **Result:** DONE
- **Commits:** PR #62 merged as `1dfe466`
- **Merge status:** merged
- **Follow-ups surfaced:** retrofit only — migration has already applied cleanly on both prod and staging (mig-04-p1 confirmed stamps); Phase 1 protects future fresh-apply paths (CI fixture rebuilds, new environments); next fixture rebuild will exercise the fresh-apply path.
- **Parallel-safety validation:** YES — single file, no overlap; 97 tests passed; ruff clean.

---

## 2026-04-21 — mig-13-p0 pipeline-violations REWRITE tail scope verification (Phase 0)

- **Session name:** mig-13-p0
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Phase 0 findings verifying already-narrowed mig-13 scope at `docs/REMEDIATION_PLAN.md:132`. Confirmed 3 of 5 original scripts **already closed** (`fetch_adv.py` via mig-02 PR #37; `build_fund_classes.py` + `build_benchmark_weights.py` via sec-05 PR #45); 2 scripts **remain open** with trivial residual work: `build_entities.py` (§1 per-step CHECKPOINT — staging-only safety rail already present), `merge_staging.py` (§5 masked errors + stale `TABLE_KEYS` legacy refs — fix derives from `pipeline.registry.merge_table_keys()`, already exists). Recommendation: ship combined Phase 1 in one session.
- **Files touched:** `docs/findings/mig-13-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #61 merged as `2c779df`
- **Merge status:** merged
- **Follow-ups surfaced:** One read-only DuckDB probe confirmed `beneficial_ownership` is dropped and `fund_holdings` coexists with `fund_holdings_v2` in prod; closure commits `db1fdb8` (#37) and `742d504` (#45) verified as ancestors of HEAD `c3590d0`.
- **Parallel-safety validation:** YES — read-only inspection only; no runtime writes.

---

## 2026-04-21 — mig-13-p1 CHECKPOINT build_entities + clean merge_staging

- **Session name:** mig-13-p1
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Close the two remaining scripts from mig-13 pipeline-violations scope. (1) `scripts/build_entities.py` — add `CHECKPOINT` in `main()` after every step2..step7 call and after `replay_persistent_overrides` (10 new per-step CHECKPOINTs); closes §1 incremental save; no business logic changes. (2) `scripts/merge_staging.py` — replace hand-maintained `TABLE_KEYS` dict with `TABLE_KEYS = merge_table_keys()` from `pipeline.registry`; stale `beneficial_ownership` (dropped Stage 5) and `fund_holdings` (legacy v1 N-PORT) entries removed (registry already uses `_v2` variants); only two overrides remain for persistent caches outside the registry (`_cache_openfigi`, `_cache_yfinance`); convert per-table try/except from silent swallow to collect-and-fail (errors accumulate into a list; live runs exit non-zero with failure summary; dry-run keeps them as warnings); `--drop-staging` suppressed when any table failed so staging is retained for investigation; closes §5 error handling + legacy refs. (3) `docs/pipeline_violations.md` — mark both scripts CLEARED with fix rationale.
- **Files touched:** `scripts/build_entities.py`, `scripts/merge_staging.py`, `docs/pipeline_violations.md`
- **Result:** DONE
- **Commits:** PR #63 merged as `a410c1a`
- **Merge status:** merged
- **Follow-ups surfaced:** mig-13 CLOSED — all 5 originally-scoped scripts now resolved (3 closed upstream via mig-02/sec-05/sec-06; 2 closed by this PR). Theme 3 migration now 5/14 CLOSED.
- **Parallel-safety validation:** YES — two scripts plus doc; scope strictly limited to Phase 1 plan; 97 tests passed; ruff clean.

---

## 2026-04-21 — merge-wave-9

- **Session name:** merge-wave-9
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Coordinated merge of 4 PRs covering mig-03 (Phase 0 + Phase 1) and mig-13 (Phase 0 + Phase 1). Serial merge ordering: PR #60 (mig-03-p0 findings) → PR #61 (mig-13-p0 findings) → PR #62 (mig-03 retrofit) → PR #63 (mig-13 CHECKPOINT + merge_staging). All four landed cleanly with zero conflicts. Parallel-safety held — no file overlap across sessions (Phase 0 findings are new docs; Phase 1 scripts are disjoint).
- **Files touched:** n/a (coordination session; no code changes)
- **Result:** DONE
- **Commits:** merged `94de1c4` (#60), `2c779df` (#61), `1dfe466` (#62), `a410c1a` (#63)
- **Merge status:** merged
- **Follow-ups surfaced:** Both Batch 3-B OPEN items now CLOSED (mig-03, mig-13). Only mig-14 remains in 3-B. Theme 3 advances to 5/14 CLOSED. conv-06 convergence session triggered.
- **Parallel-safety validation:** YES — clean wave; no conflicts; no post-merge regressions.

---

## 2026-04-21 — conv-06 convergence doc update

- **Session name:** conv-06
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** batch doc update reflecting PRs #60 through #63 merged since conv-05 (4 PRs). Flip CHECKLIST items (mig-03, mig-13). Append session-log entries for mig-03-p0, mig-03-p1, mig-13-p0, mig-13-p1, merge-wave-9, conv-06. Update REMEDIATION_PLAN.md item-table statuses (mig-03 OPEN→CLOSED PRs #60/#62; mig-13 OPEN narrowed → CLOSED PRs #61/#63) + append conv-06 changelog entry. Both Theme 3 Batch 3-B items closed; Theme 3 now 5/14 CLOSED.
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** (1) Theme 3 migration now 5/14 CLOSED (mig-01, mig-02, mig-03, mig-04, mig-13); mig-14 is the last remaining Batch 3-B item; Batches 3-C/3-D untouched (mig-06/07/08/09/10/11). (2) mig-05/mig-12 remain Phase 2/Phase 3 deferrals. (3) mig-13 scope narrowing across sessions validated: original 5 scripts resolved via 4 different items (mig-02, sec-05, sec-06, mig-13 itself) — good example of cross-theme convergence.
- **Parallel-safety validation:** YES — docs-only; no parallel worker holds these three files.

---

## 2026-04-21 — obs-batch-2E data_layers.md headline + flow_intensity docstring

- **Session name:** obs-batch-2E
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Close the last two content items in Theme 2 Batch 2-E. obs-05 refreshed `docs/data_layers.md:92` `fund_holdings_v2` headline to 14,090,397 rows / 84.13% `entity_id` coverage (prod-verified 2026-04-21 via read-only SQL snapshot) and cited BLOCK-2 (2026-04-17) + CUSIP v1.4 (2026-04-15) as the stability baseline. obs-11 added a 9-line formula docstring to `scripts/compute_flows.py::_compute_ticker_stats` explaining `flow_intensity_total = SUM(price_adj_flow) / market_cap` over continuing holders, plus a new `§10 Flow metrics` section in `docs/data_layers.md` documenting `flow_intensity_{total,active,passive}` and the churn variants with cross-references to `compute_flows.py`. Doc-only + docstring-only; no behavior change, no schema change.
- **Files touched:** `scripts/compute_flows.py` (docstring only), `docs/data_layers.md` (headline + new §10)
- **Result:** DONE
- **Commits:** merged `76e8da3` (PR #66)
- **Merge status:** merged
- **Follow-ups surfaced:** Theme 2 Batch 2-E fully closed. Combined with obs-13 verification (PR #65) this closes the final 3 open items in Theme 2 → **Theme 2 observability 13/13 CLOSED**. No new items surfaced.
- **Parallel-safety validation:** YES — Batch 2-E was predicted serial (shared `docs/data_layers.md`); shipping obs-05 + obs-11 as a single PR respected the serial dependency by co-editing the file under one author. No drift from Phase 0 prediction.

---

## 2026-04-21 — obs-13-verify Register %FLOAT dist bundle verification

- **Session name:** obs-13-verify
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Verification-only pass for obs-13 DIAG-23 Register %FLOAT stale dist bundle. Confirmed that (a) React source under `web/react-app/src/` (`RegisterTab.tsx`, `api.ts`) uses `pct_so` exclusively with no `pct_of_float` remnants; (b) the main-worktree dist bundle under `web/react-app/dist/` (rebuilt 2026-04-19 15:26 EDT, after `f956096` source migration) contains zero `pct_of_float` references; (c) `ff1ff71` modified CI fixtures only and did not touch React source, so a post-ff1ff71 dist rebuild is not required; (d) `web/react-app/dist/` is gitignored, so there is no stale-bundle-in-repo condition to clear. Full evidence (grep results, file timestamps, commit trail) written to `docs/findings/obs-13-verify-findings.md`. No code changes, no DB writes, no migration.
- **Files touched:** `docs/findings/obs-13-verify-findings.md` (new)
- **Result:** DONE
- **Commits:** merged `0edb9b8` (PR #65)
- **Merge status:** merged
- **Follow-ups surfaced:** INF42 (derived-artifact hygiene — no CI check forces fixture/dist rebuilds when schema migrations land) remains a standing gap and is tracked separately under Theme 3 Batch 3-D (mig-08). Not a blocker for obs-13 closure.
- **Parallel-safety validation:** YES — verification-only session, single findings doc, no file conflicts possible.

---

## 2026-04-21 — merge-wave-10

- **Session name:** merge-wave-10
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Retroactive bookkeeping entry covering merges of PRs #64 (conv-06 doc update), #65 (obs-13 verification), #66 (obs-05 + obs-11). No dedicated coordination session was run for this window — conv-06 was merged as part of closing out the prior convergence, and PRs #65/#66 landed sequentially as individual worker PRs without requiring a wave-level merge coordinator. All three PRs landed cleanly with zero conflicts; CI green; no post-merge regressions.
- **Files touched:** n/a (coordination bookkeeping only; no code changes)
- **Result:** DONE
- **Commits:** merged `cccc604` (#64), `0edb9b8` (#65), `76e8da3` (#66)
- **Merge status:** merged
- **Follow-ups surfaced:** With PRs #65 + #66 landed, Theme 2 observability completes at **13/13 CLOSED** (program milestone). Program total advances to **66 PRs merged, 46 items closed**. conv-07 convergence session triggered.
- **Parallel-safety validation:** YES — no parallel worker activity during this window; no conflicts observed.

---

## 2026-04-21 — conv-07 convergence doc update

- **Session name:** conv-07
- **Start:** 2026-04-21
- **End:** 2026-04-21
- **Scope:** Batch doc update reflecting 3 PRs merged since conv-06 (PRs #64, #65, #66) plus retroactive closure confirmations for obs-06, int-05, int-10. Flip CHECKLIST rows for obs-05, obs-11, obs-13 to `[x]` with PR citations. Append SESSION_LOG entries for obs-batch-2E, obs-13-verify, merge-wave-10, conv-07. Update REMEDIATION_PLAN.md item-table statuses (obs-05 OPEN→CLOSED PR #66; obs-11 OPEN→CLOSED PR #66; obs-13 LIKELY-CLOSED→CLOSED PR #65) and append conv-07 changelog entry. **Theme 2 observability closes at 13/13 — program milestone.** Theme 4 security stays at 8/8 CLOSED (sustained). Program total: 66 PRs merged (#5-#66), 46 items closed, ~24 remaining across Themes 1, 3, 5.
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** (1) Theme 2 observability **13/13 CLOSED** — full theme complete; no remaining items. Combined with Theme 4 security (8/8 CLOSED), two full themes are now closed. (2) Remaining open work: Theme 1 data integrity (~13 items), Theme 3 migration (~8 items: mig-14 + Batches 3-C/3-D + mig-05/12 deferrals), Theme 5 operational (~4 items: ops-13/14/16/18). (3) **Pending data ops carried forward:** `scripts/oneoff/backfill_13dg_impacts.py --confirm` (obs-04) + int-10 staging sweep `--confirm` — both gated behind Serge approval; status unchanged from conv-06. (4) INF42 derived-artifact hygiene CI gate remains a standing gap (tracked under mig-08). (5) No new follow-ups surfaced from PRs #64-#66 review.
- **Parallel-safety validation:** YES — docs-only session; no parallel worker holds these three files.

---

## 2026-04-22 — mig-14-p0 REWRITE_BUILD_MANAGERS already-satisfied (Phase 0)

- **Session name:** mig-14-p0
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Phase 0 verification of REWRITE_BUILD_MANAGERS remaining scope (INF1 staging routing + `--dry-run` + `data_freshness`). Read `scripts/build_managers.py`, `scripts/promote_staging.py`, `scripts/db.py` end-to-end at HEAD `4484137`; cross-referenced every original deliverable against live code. Confirmed every claim satisfied: `--staging` + `db.seed_staging()` wired ([build_managers.py:728,784](scripts/build_managers.py:728)); `--dry-run` flag + per-builder projection messages ([:735](scripts/build_managers.py:735) + 4 callsites); 5 `data_freshness` stamps (parent_bridge, cik_crd_links, cik_crd_direct, managers, holdings_v2); `db.CANONICAL_TABLES` covers all 4 outputs ([db.py:130-133](scripts/db.py:130)); `promote_staging.PK_COLUMNS` includes parent_bridge + cik_crd_direct ([promote_staging.py:67-68](scripts/promote_staging.py:67)); new `rebuild` promote kind for managers + cik_crd_links ([promote_staging.py:122-126](scripts/promote_staging.py:122)); full-replace dispatch at [:310-323](scripts/promote_staging.py:310); rebuild-safe restore at [:157-191](scripts/promote_staging.py:157). Closing commits `67e81f3`, `2a71f8a`, `4e64473` verified in `git log`. Independently confirms sec-05-p0 §2/§5 conclusion. Recommendation: close mig-14 as already-satisfied, flip CHECKLIST [x] + PLAN status OPEN→CLOSED at next convergence.
- **Files touched:** `docs/findings/mig-14-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #68 merged as `0b97247`
- **Merge status:** merged
- **Follow-ups surfaced:** Two doc-hygiene items for convergence (CHECKLIST flip + PLAN status update) — handled in conv-08 below.
- **Parallel-safety validation:** YES — findings doc only; no runtime writes.

---

## 2026-04-22 — int-06-p0 forward-looking hooks already-shipped (Phase 0)

- **Session name:** int-06-p0
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Phase 0 verification of BLOCK-TICKER-BACKFILL Phase 1b — forward-looking Pass C hooks on `scripts/build_cusip.py` (end) and `scripts/normalize_securities.py` (end). Read both scripts end-to-end at HEAD; confirmed both end-of-run subprocess hooks to `enrich_holdings.py` Pass C were shipped in a prior session (pre-program window). No residual code change required.
- **Files touched:** `docs/findings/int-06-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #69 merged as `50de780`
- **Merge status:** merged
- **Follow-ups surfaced:** Unblocks int-07 gate (Phase 2 benchmark_weights coverage check) — scheduled next.
- **Parallel-safety validation:** YES — findings doc only; no runtime writes.

---

## 2026-04-22 — ops-16-p1 NEXT_SESSION_CONTEXT refresh

- **Session name:** ops-16-p1
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Close DOC_UPDATE_PROPOSAL item 6 — admin_bp.py:108 revisit flag. Refreshed `docs/NEXT_SESSION_CONTEXT.md` to current program state (PR #5-#67 coverage, Themes 2 + 4 complete, pending data ops enumerated, F1 flag embedded). Placement decision: session-context doc owns the F1 flag (not ROADMAP.md) per convention.
- **Files touched:** `docs/NEXT_SESSION_CONTEXT.md`
- **Result:** DONE
- **Commits:** PR #70 merged as `c7f5605`
- **Merge status:** merged
- **Follow-ups surfaced:** ops-16 closed. Theme 5 Batch 5-D resolved.
- **Parallel-safety validation:** YES — single doc; no code touch; no parallel worker holds this file.

---

## 2026-04-22 — int-07-p0 benchmark_weights gate PASS (Phase 0)

- **Session name:** int-07-p0
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Phase 0 verification of BLOCK-TICKER-BACKFILL Phase 2 — benchmark_weights three-part gate. Evaluated (1) coverage gate, (2) no-regression gate, (3) tier-stability gate against prod `benchmark_weights` + upstream `securities`/`holdings` state. **All 3 gates PASS.** No Phase 2b escalation required; int-08 can be formally SKIPPED as conditional-and-not-triggered.
- **Files touched:** `docs/findings/int-07-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #71 merged as `f5a0cd3`
- **Merge status:** merged
- **Follow-ups surfaced:** int-07 closed (single-phase close). int-08 SKIPPED (condition not met). Batch 1-C advances.
- **Parallel-safety validation:** YES — findings doc only; no runtime writes.

---

## 2026-04-22 — mig-09-p0 INF45 L4 schema-parity extension (Phase 0)

- **Session name:** mig-09-p0
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Phase 0 scoping of INF45 L4 schema-parity extension. Enumerated 14 L4 derived tables (post-build aggregates/summaries). Identified `entity_current` VIEW as a deferral (duckdb_tables() excludes views; tracked as micro-follow-up per §4 Option A). Proposed Phase 1 design: `L4_TABLES` constant + `--layer {l3,l4,l0,all}` CLI flag + missing-table pre-check emitting single `ddl` divergence instead of N noisy column rows. Accept-list stays empty per INF39 Option B remediate-all policy.
- **Files touched:** `docs/findings/mig-09-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #72 merged as `f79d437`
- **Merge status:** merged
- **Follow-ups surfaced:** Phase 1 cleared to ship combined with mig-10 (same constants block edit zone).
- **Parallel-safety validation:** YES — findings doc only; no runtime writes.

---

## 2026-04-22 — int-09-p0 INF25 Step 4 defer-to-Phase-2 (Phase 0)

- **Session name:** int-09-p0
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Phase 0 quantification of BLOCK-DENORM-RETIREMENT Step 4 retirement scope. Steps 1–3 confirmed done: Step 1 (backfill) `3299a9f`; Step 2 (forward hooks) `0dc0d5d`; Step 3 (write-path repoint) `d7ba1c2`/`87ee955`/`7e68cf9`/`223b4d9`. Step 4 (retire denormalized columns on `holdings_v2` + `fund_holdings_v2`) scoped: ~500 `scripts/queries.py` read sites + `rollup_entity_id` dual-graph resolution — too large for a remediation window. Forward hooks (int-06) already bound drift; no urgent correctness gap. Recommendation: **formally defer Step 4 to Phase 2** with explicit exit criteria (mig-12 load_13f_v2 + mig-07 INF41 read-site inventory + join pattern proven + dual-graph decision + drift gate ≥2 quarters + rename-sweep discipline).
- **Files touched:** `docs/findings/int-09-p0-findings.md` (new)
- **Result:** DONE
- **Commits:** PR #73 merged as `f2dfe2f`
- **Merge status:** merged
- **Follow-ups surfaced:** Phase 1 doc-only bundle cleared to ship with ops-13 + ops-14 (shared doc edit zone).
- **Parallel-safety validation:** YES — findings doc only; no runtime writes.

---

## 2026-04-22 — mig-09-10-p1 L4 + L0 schema-parity validator extension

- **Session name:** mig-09-10-p1
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Combined Phase 1 for mig-09 (INF45 L4) and mig-10 (INF46 L0). Shipped `L4_TABLES` (14 derived) + `L0_TABLES` (6 control-plane) alongside existing `L3_TABLES`; added `--layer {l3,l4,l0,all}` CLI flag (default `l3` preserves Phase 2 pre-flight behavior). Threaded active layer + table count through JSON summary (`summary.layer`, `summary.table_count`) and human report header. Added missing-table pre-check in `compare_table`: emits one clean `ddl` divergence (`detail="TABLE MISSING"`) instead of N noisy column divergences when table absent on one side. Deferrals: `entity_current` VIEW (introspect_ddl uses `duckdb_tables()` which excludes views — micro-follow-up per mig-09-p0 §4); `admin_sessions` excluded from L0 (lives in `data/admin.duckdb` per sec-01-p1-hotfix). Baseline accept-list unchanged (INF39 Option B).
- **Files touched:** `scripts/pipeline/validate_schema_parity.py` (+~150 LoC), `tests/pipeline/test_validate_schema_parity.py` (+~200 LoC)
- **Result:** DONE
- **Commits:** PR #74 merged as `8d8bd39`
- **Merge status:** merged
- **Follow-ups surfaced:** mig-11 (INF47 CI wiring) unblocked (at least one schema scope extended — both shipped). `entity_current` VIEW micro-follow-up tracked separately. First real `--layer l4 --json` + `--layer l0 --json` runs against local prod/staging DBs deferred to merge-time per findings §8 Q4.
- **Parallel-safety validation:** YES — validator + tests only; 116 tests pass (26→72 validator suite); ruff clean.

---

## 2026-04-22 — int-09-p1-ops-13-14 DENORM-RETIREMENT Phase 2 deferral formalized

- **Session name:** int-09-p1-ops-13-14
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Combined Phase 1 for int-09 + ops-13 + ops-14 (all three items share `docs/data_layers.md §7` + `ENTITY_ARCHITECTURE.md` + `ROADMAP.md` edit zone — bundled per plan-policy). **int-09 Phase 1** formalizes Phase 0 decision: defer Step 4 of Class B denormalized-column retirement sequence to Phase 2. **ops-13** refreshes `docs/data_layers.md §7` headline (Steps 1–3 marked DONE with commits; "Observed drift" rewritten to bounded-by-forward-hooks framing; post-backfill ticker row counts added; Step 4 DEFERRED TO PHASE 2 with full exit criteria embedded). **ops-14** updates `ROADMAP.md` INF25 row status "Sequenced" → "Deferred to Phase 2 (int-09 2026-04-22)"; notes cite commits for Steps 1–3 + link to `docs/findings/int-09-p0-findings.md §4`. `ENTITY_ARCHITECTURE.md` Known Limitation #6 + Design Decision Log Apr 18 entry each receive a 2026-04-22 addendum with deferral rationale + Phase 2 trigger. Doc-only; no code / schema / writer changes; 116 tests pass (sanity).
- **Files touched:** `docs/data_layers.md`, `ENTITY_ARCHITECTURE.md`, `ROADMAP.md`
- **Result:** DONE
- **Commits:** PR #75 merged as `25a0263`
- **Merge status:** merged
- **Follow-ups surfaced:** int-09, ops-13, ops-14 all CLOSED simultaneously. Theme 1 Batch 1-D advances; Theme 5 Batch 5-C closes fully. Step 4 exit criteria carried forward to Phase 2 kickoff (prog-02).
- **Parallel-safety validation:** YES — three docs, single author, serialized per shared-file policy; no parallel worker holds these docs.

---

## 2026-04-22 — merge-wave-11

- **Session name:** merge-wave-11
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** First coordination wave of conv-08 window covering Phase 0 batch: PRs #68 (mig-14-p0), #69 (int-06-p0), #70 (ops-16-p1), #71 (int-07-p0). All four landed sequentially with zero conflicts; all findings-doc or single-doc writes — file-disjoint by construction.
- **Files touched:** n/a (merge coordination only)
- **Result:** DONE
- **Commits:** merged `0b97247` (#68), `50de780` (#69), `c7f5605` (#70), `f5a0cd3` (#71)
- **Merge status:** all merged to main
- **Follow-ups surfaced:** 3 items closed outright (mig-14 already-satisfied, int-06 NO-OP, ops-16, int-07); int-08 unblocked for SKIP decision.
- **Parallel-safety validation:** YES — Phase 0 findings-only + single-doc ops-16 refresh; no parallel worker contention.

---

## 2026-04-22 — merge-wave-12

- **Session name:** merge-wave-12
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Second coordination wave of conv-08 window covering the Phase 1 batch + remaining Phase 0: PRs #72 (mig-09-p0 findings), #73 (int-09-p0 findings), #74 (mig-09-10-p1 validator extension), #75 (int-09-p1 + ops-13 + ops-14 doc bundle). All four landed sequentially with zero conflicts; schema-parity validator and doc bundle occupy disjoint file zones so serialization was conservative but not strictly required.
- **Files touched:** n/a (merge coordination only)
- **Result:** DONE
- **Commits:** merged `f79d437` (#72), `f2dfe2f` (#73), `8d8bd39` (#74), `25a0263` (#75)
- **Merge status:** all merged to main
- **Follow-ups surfaced:** 5 items closed (mig-09, mig-10, int-09, ops-13, ops-14); conv-08 convergence session triggered.
- **Parallel-safety validation:** YES — clean wave; no conflicts; no post-merge regressions.

---

## 2026-04-22 — conv-08 convergence doc update

- **Session name:** conv-08
- **Start:** 2026-04-22
- **End:** 2026-04-22
- **Scope:** Batch doc update reflecting 8 PRs merged since conv-07 (PRs #68-#75). Flip CHECKLIST rows for int-06, int-07, int-08 (SKIPPED), int-09, mig-09, mig-10, mig-14, ops-13, ops-14, ops-16 with PR citations. Append SESSION_LOG entries for mig-14-p0, int-06-p0, ops-16-p1, int-07-p0, mig-09-p0, int-09-p0, mig-09-10-p1, int-09-p1-ops-13-14, merge-wave-11, merge-wave-12, conv-08. Update REMEDIATION_PLAN.md item-table statuses (int-06 READY→CLOSED PR #69; int-07 READY→CLOSED PR #71; int-08 CONDITIONAL→SKIPPED; int-09 OPEN→CLOSED PRs #73/#75; mig-09 OPEN→CLOSED PRs #72/#74; mig-10 OPEN→CLOSED PR #74; mig-14 OPEN→CLOSED PR #68; ops-13 OPEN→CLOSED PR #75; ops-14 OPEN→CLOSED PR #75; ops-16 OPEN→CLOSED PR #70) and append conv-08 changelog entry. Program total: 75 PRs merged (#5-#75), 53 items closed, ~17 remaining.
- **Files touched:** `docs/REMEDIATION_CHECKLIST.md`, `docs/REMEDIATION_SESSION_LOG.md`, `docs/REMEDIATION_PLAN.md`
- **Result:** DONE
- **Commits:** (filled at commit step)
- **Merge status:** pending Serge review
- **Follow-ups surfaced:** (1) **Theme 5 operational advances to 17/18 CLOSED — only ops-18 BLOCKED remaining** (rotating_audit_schedule.md file not found). (2) **Theme 3 migration advances to 9/14 CLOSED** (mig-01, mig-02, mig-03, mig-04, mig-09, mig-10, mig-13, mig-14 + sec-09 via mig-02); remaining: mig-06, mig-07, mig-08, mig-11 (Batches 3-C/3-D) + mig-05/mig-12 Phase 2/3 deferrals. (3) **Theme 1 data integrity advances to 11/23 CLOSED** (add int-06 NO-OP, int-07, int-08 SKIPPED, int-09 Phase-2-deferred to earlier list of int-01/02/04/05/10); remaining: int-03, int-11..int-17, int-20..int-23 + standing int-18 + Phase 2 int-19. (4) Combined with Theme 2 (13/13) + Theme 4 (8/8) → **Themes 2 + 4 complete; Theme 5 effectively complete modulo ops-18 BLOCKED**. (5) **Pending data ops carried forward:** `scripts/oneoff/backfill_13dg_impacts.py --confirm` (obs-04) + int-10 staging sweep `--confirm` — both gated behind Serge approval; status unchanged from conv-07. (6) INF42 derived-artifact hygiene CI gate remains a standing gap (mig-08). (7) Int-09 Phase 2 exit criteria (mig-12 + mig-07 + join pattern + dual-graph + drift gate + rename-sweep) now anchored in `data_layers.md §7` for Phase 2 kickoff reference.
- **Parallel-safety validation:** YES — docs-only session; no parallel worker holds these three files.
