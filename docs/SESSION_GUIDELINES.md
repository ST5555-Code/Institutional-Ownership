# Session Guidelines — Worktree Hygiene

_Generated: 2026-04-23 (hygiene-file-leak-fix). Companion to `docs/SESSION_NAMING.md`._

Covers rules that span sessions and that the harness cannot enforce on its own. Read this at the start of any session that runs in a git worktree.

---

## 1. File-leak-to-main mitigation

### Symptom

A worker session running on a feature branch inside a worktree finishes its work, but `git status` on the worktree shows a clean tree — while `git status` on the primary repo path (`~/ClaudeWorkspace/Projects/13f-ownership`) shows uncommitted edits that were supposed to live on the feature branch. The work landed on `main`'s working tree, not the branch.

This recurred at least three times in the Group A sessions batch (2026-04-23): `entity-curation-w1`, `build-fund-classes-rewrite`, and `bl7-ticker-validation`.

### Root cause

Gitignored data paths (`data/13f.duckdb` at 16 GB, `data/admin.duckdb`, `data/13f_staging.duckdb`, etc.) exist only in the primary worktree. Fresh git worktrees have none of them.

When a worker script needs a DB, the natural workaround is to `cd ~/ClaudeWorkspace/Projects/13f-ownership` and run the script there. Once the session's shell headspace has shifted to the primary path, subsequent `Edit` / `Write` tool calls that use absolute paths `/Users/.../Projects/13f-ownership/<file>` land on main's tree rather than the worktree's tree. The branch sees no change; main sees an uncommitted diff.

### Mitigation — run the bootstrap script

```
./scripts/hygiene/bootstrap_worktree.sh
```

Idempotent. In the primary worktree it no-ops. In a secondary worktree it creates symlinks:

- `data/13f.duckdb` → primary worktree's DB
- `data/13f.duckdb.wal`
- `data/admin.duckdb` + `.wal`
- `data/13f_staging.duckdb`
- `data/13f_readonly.duckdb` (if present)

After running, scripts that resolve the DB path via `BASE_DIR = dirname(__file__)` + `data/13f.duckdb` work directly from the worktree — no `cd` required, no incentive to leak.

**Run this once at the start of every worktree session** before touching any script that needs a DB.

### Belt-and-braces rule for absolute paths

Even with bootstrap in place, never pass an absolute path under the primary worktree to `Edit` / `Write` / `Read` when the intent is to modify branch-tree files. Two rules:

1. **For branch-tree edits, always use a path under the current worktree root** (`/Users/.../.claude/worktrees/<name>/...`), or prefer relative paths that resolve under `pwd`.
2. **If a path contains `/13f-ownership/<file>` without the `.claude/worktrees/<name>/` segment, it is a main-tree path.** Do not use it for feature work.

Verify at any time:

```
git rev-parse --show-toplevel   # must match the worktree you expect
```

### Recovery if the leak happens anyway

From the primary worktree:

```
cd ~/ClaudeWorkspace/Projects/13f-ownership
git diff <leaked-files> > /tmp/patch
git checkout -- <leaked-files>
```

Then re-apply `/tmp/patch` from the worker session on its own branch.

---

## 2. Standing hygiene checklist at session start

For a session that runs in a secondary worktree:

1. `pwd` — confirm you are under `.claude/worktrees/<name>/`, not `~/ClaudeWorkspace/Projects/13f-ownership/`.
2. `git branch --show-current` — confirm the feature branch.
3. `./scripts/hygiene/bootstrap_worktree.sh` — install DB symlinks.
4. Run work from the worktree. Never `cd` to the primary path.
5. `git status` at end of session — confirm expected files are staged; cross-check `git -C ~/ClaudeWorkspace/Projects/13f-ownership status` shows no stray changes.

---

## 3. Cross-tracker update rule

**Closing a tracked item requires updating every tracker that references it, in the same PR.**

After backlog-collapse (2026-04-25), the active tracker surface is intentionally narrow:

- `ROADMAP.md` — single source of truth for forward work (see §5).
- `MAINTENANCE.md` — recurring/standing maintenance.
- `docs/NEXT_SESSION_CONTEXT.md` — single-session handoff (overwritten per session; never accumulates multi-session state).

`docs/REMEDIATION_PLAN.md` and `docs/DEFERRED_FOLLOWUPS.md` were archived to `archive/docs/` on 2026-04-25; do not update them and do not add new entries. Findings files in `docs/findings/` are point-in-time reference material — leave historical references intact.

Before opening a PR that closes an item, grep for the item ID / name across the active trackers. If more than one mentions it, update them all in this PR — do not leave stale mentions for a future doc-sync session. The historical cost of a stale tracker is a full investigation session to reconstruct state that was already known (see `phantom-other-managers-decision`, PR #125 — the phantom `other_managers` item flagged open in `REMEDIATION_PLAN.md` had already been resolved four days earlier, but that was only confirmed after a full session re-reading the code).

**Why:** trackers drift independently. A session that ships a fix naturally updates whichever tracker the author was looking at, not the others. The next session investigating the item reads a stale tracker, treats it as authoritative, and wastes a session rediscovering what already shipped. The narrower surface after backlog-collapse exists to keep the cross-tracker audit cheap.

**How to apply:**

1. When preparing a PR that closes an item, run `python3 scripts/hygiene/audit_tracker_staleness.py` against your branch. The script prints any ID whose status disagrees across docs and exits non-zero if drift exists.
2. If the audit flags your item, update every tracker it names before pushing. Use the same closure note (commit SHA, PR number, date) in each.
3. For items whose closure is partial (`Steps 1-3 done; Step 4 deferred`), spell out the partial state in every tracker — do not rely on one tracker to carry the nuance.
4. Reviewers check tracker consistency per the `docs/REVIEW_CHECKLIST.md` tracker-consistency gate.

**Scope exemption.** A PR that deliberately only touches one tracker (a typo fix, a link repair, a header refresh) does not need to update the others. The rule kicks in when the PR changes the **status** of an item, not when it changes prose around the item.

---

## 4. Scripts directory taxonomy

The `scripts/` tree is partitioned by lifecycle. Place new scripts in the directory matching their intended use:

- **`scripts/`** — active pipelines + core utilities (run regularly by Makefile, scheduler, or operators).
- **`scripts/pipeline/`** — `SourcePipeline` framework (registry, sync/diff/promote, base classes).
- **`scripts/hygiene/`** — audit + cleanup tools (e.g. `audit_ticket_numbers.py`, `audit_tracker_staleness.py`, `audit_read_sites.py`, `bootstrap_worktree.sh`, `cleanup_merged_worktree.sh`, `concat_closed_log.py`). Run on demand by reviewers / session start.
- **`scripts/oneoff/`** — historical apply / bootstrap / seed scripts (audit trail; **do not re-run**). Examples: `dm14_layer1_apply.py`, `inf23_apply.py`, `migrate_batch_3a.py`.
- **`scripts/retired/`** — superseded by current code paths; **do not call**. Kept only for archaeology.

**Rule of thumb:** if a script is one-shot (data fix, schema migration apply, bootstrap seed), land it in `scripts/oneoff/` from the start. If it's a recurring on-demand tool (audit, cleanup), land it in `scripts/hygiene/`. Reserve top-level `scripts/` for things that get called by Makefile / scheduler / update.py / admin_bp.py.

---

## 5. Tracker source-of-truth

`ROADMAP.md` is the single source of truth for forward work. Every session updates ROADMAP at close — items live here or do not exist.

Document roles:

- `ROADMAP.md` — all forward work. Current backlog (P0–P3) + Scheduled + Deferred (with triggers) + Ambient pointers.
- `MAINTENANCE.md` — recurring/standing maintenance and operational runbook. NOT a backlog.
- `docs/NEXT_SESSION_CONTEXT.md` — single-session handoff only. Overwritten per session. NEVER accumulates multi-session items.
- `docs/plans/<slug>.md` — workstream-specific plan for active work. Archives to `archive/docs/plans/` on workstream close.
- `docs/findings/` — per-session investigation outputs. Reference material; not a backlog.
- `archive/docs/` — historical artifacts. Reference only.

Rules:

1. Closing an item requires updating ROADMAP. No exceptions.
2. Deferring an item requires a named trigger documented in ROADMAP "Deferred". "I'll come back to it" is not a trigger.
3. Recurring/standing maintenance lives in `MAINTENANCE.md`, not the ROADMAP backlog.
4. Workstream plan docs are temporary by design. Active workstream gets one doc; archive on close.
5. Drift between trackers is caught by `scripts/hygiene/audit_tracker_staleness.py` running in pre-commit + CI (`audit-tracker-staleness-ci` on ROADMAP P1).

If a session would naturally produce content for a tracker that no longer exists (`REMEDIATION_PLAN`, `DEFERRED_FOLLOWUPS`), redirect to ROADMAP. Those trackers are archived as historical record only.

---

## Related

- `docs/SESSION_NAMING.md` — session / branch naming convention.
- `docs/REVIEW_CHECKLIST.md` — PR-review gates applied at merge time.
- `docs/PROCESS_RULES.md` — rules for large-data pipeline scripts.
