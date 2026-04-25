# Archived documentation

Point-in-time documents retained for historical reference. Not maintained. For
forward-looking work, see `ROADMAP.md` at repo root.

## Index

- `REMEDIATION_CHECKLIST.md` — Sprint-view of remediation program; retired on completion 2026-04-22 (conv-11). Moved here 2026-04-23.
- `PHASE3_PROMPT.md` — Phase 3 dispatch prompt; phase complete.
- `PHASE4_PROMPT.md` — Phase 4 dispatch prompt; phase complete.
- `PHASE4_STATE.md` — Phase 4 in-flight state snapshot; phase complete.
- `SYSTEM_ATLAS_2026_04_17.md` — 2026-04-17 architectural atlas; superseded by evolved codebase + ROADMAP narrative.
- `SYSTEM_AUDIT_2026_04_17.md` — 2026-04-17 system audit findings; all §12 remediation items closed in conv-11.
- `SYSTEM_PASS2_2026_04_17.md` — 2026-04-17 audit Pass 2 appendix; remediation complete.
- `ROLLUP_COVERAGE_REPORT.md` — One-shot rollup coverage report; no longer refreshed.
- `POST_MERGE_REGRESSIONS_DIAGNOSTIC.md` — 2026-04-17 post-merge regression diagnostic; regressions resolved.

## 2026-04-25 repo-cleanup session

- `REACT_MIGRATION.md` — React migration plan (Phase 4 cutover complete 2026-04-13); migration narrative retained for commit archaeology.
- `closed/` directory (1 file) — `DOC_UPDATE_PROPOSAL_20260418_RESOLVED.md`. `docs/closures/README.md` declares `docs/closed/` a retired convention superseded by per-session closure files; the single resolved proposal is moved here.
- `prompts/` directory (24 files) — per-task dispatch prompts for int-01/04, mig-01/04, obs-01/02/03, sec-01/02/03/04, ops-batch-5A/5B. Every item DONE per `docs/REMEDIATION_SESSION_LOG.md`; 2 live script comments (obs-03-p1 in `id_allocator.py` and `010_drop_nextval_defaults.py`) updated to the archive path.
- `proposals/` directory (1 file) — `tier-4-join-pattern-proposal.md` authored for int-09 review. int-09 CLOSED 2026-04-22 (PR #75).
- `reports/` directory (9 files) — dated session closeouts from the BLOCK/REWRITE audit wave (block3 Phase 2/4, block_sector_coverage closeout, block_securities audit Phase 2/2b, block_ticker_backfill closeout, rewrite_build_managers/shares_history/load_13f Phase 2).
- `superpowers/` directory (3 files in `plans/` + `specs/`) — early-April implementation plans: `2026-04-01-flask-web-app.md`, `2026-04-06-peer-rotation-plan.md`, `2026-04-06-sector-rotation-redesign.md`. All shipped.
- `plans/20260412_architecture_review_revision.md` — ARCHITECTURE_REVIEW.md revision pass C1–C6; all changes long-landed.
- `plans/2026-04-23-phase-b-c-execution-plan.md` — All phases + §8 shipped; B3 gets a fresh plan doc when the gate opens.

## 2026-04-25 backlog-collapse session

- `REMEDIATION_PLAN.md` — Frozen ledger of the 2026-04-20 → 2026-04-22 remediation program plus follow-up tracking through 2026-04-24. Retired during the tracker collapse so `ROADMAP.md` is the only forward-work surface; remaining live items moved to `ROADMAP.md` "Current backlog" or "Deferred". See `docs/findings/2026-04-25-backlog-collapse.md` for the closure-rationale memo.
- `DEFERRED_FOLLOWUPS.md` — Long-tail INF## index. Retired during the tracker collapse for the same reason; live items moved into `ROADMAP.md` "Deferred" with named triggers, KILL items removed, AMBIENT items routed to `MAINTENANCE.md`.
