# Session Naming Convention

Format: `<theme>-<seq>` or `<theme>-<seq>-<phase>` for multi-phase sessions.

## Theme prefixes

- `int` — Theme 1, data integrity foundation
- `obs` — Theme 2, observability + audit trail
- `mig` — Theme 3, migration + schema discipline
- `sec` — Theme 4, security hardening
- `ops` — Theme 5, operational surface
- `conv` — convergence sessions (cross-theme reconciliation, post-batch merges)
- `prog` — program-level sessions (phase-0 consolidation, mid-program status, post-foundation close)

## Sequence number

Two digits, zero-padded. Resets per theme. Numbering in this program matches item IDs in `docs/REMEDIATION_PLAN.md` (historical checklist retired to `archive/docs/REMEDIATION_CHECKLIST.md` 2026-04-23).

## Multi-phase

Append a phase suffix for sessions that split investigation, implementation, and post-merge review:

- `-p0` — Phase 0 investigation (read code, produce findings doc, no writes)
- `-p1` — Phase 1 implementation (land code or doc change)
- `-p2` — Phase 2 post-merge (address follow-up, verify in prod, close tracking docs)

Single-session items omit the phase suffix.

## Examples

- `int-01` — first data-integrity item (RC1 OpenFIGI fix); single session
- `int-01-p0` — if the worker decides to split RC1 into investigation-first, the Phase 0 session
- `obs-03-p0` — third observability item (market impact_id hardening), Phase 0
- `mig-02-p1` — second migration item (fetch_adv.py atomic fix), Phase 1
- `conv-01` — first convergence checkpoint (post-Batch 1 reconciliation)
- `prog-00` — program kickoff (this session, 2026-04-20)

## Branch naming

Session branches should mirror the session name: `remediation/<session-name>`.

- `remediation/int-01-p0`
- `remediation/mig-02-p1`
- `remediation/conv-01`

## Commit-message convention

Each session's commits must include the session name in the first line for traceability:

- `feat(int-01): RC1 OpenFIGI US-preferred sweep + fallback`
- `docs(ops-13): data_layers.md §7 denorm drift retirement sequence`
- `chore(conv-01): Batch 1 post-batch convergence checklist update`

This lets `git log --grep="int-01"` surface every commit associated with that item.

## Closing tracked items

When a session closes a tracked item (from `ROADMAP.md § Open items`
or equivalent), do **not** append the closure row to
`ROADMAP.md § Closed items (log)`. That table is frozen as of
2026-04-23. Parallel sessions that both appended to its tail
conflicted mechanically on every collision.

Instead, the session writes a per-session file:

```
docs/closures/YYYY-MM-DD-<session-name>.md
```

containing one Markdown table row per closed item, in the same
four-column shape as the archived log. Multiple closures from one
session stack as multiple rows in the same file. Full format spec
and rationale: `docs/closures/README.md`.

Because each session writes its own file, two parallel sessions
never touch the same file and git merge has no grounds to flag a
conflict. A flat view is generated on demand by
`python3 scripts/concat_closed_log.py` → `docs/closed-items-log.md`
(git-ignored).

## Post-merge cleanup

`gh pr merge --squash --delete-branch` deletes the remote branch but cannot delete the local branch when a worktree still holds it, so the local copy and its worktree both leak. After merging a PR to `main`, run:

```
./scripts/cleanup_merged_worktree.sh <pr-number>
# or
./scripts/cleanup_merged_worktree.sh <branch-name>
```

The script resolves the PR to its head branch, removes the worktree (`git worktree remove --force`), and deletes the local branch (`git branch -D`). It refuses to touch `main` or `master`, and it is a no-op if either the worktree or branch is already gone.

Optional one-shot alias:

```
git config alias.merge-and-clean '!f() { gh pr merge "$1" --squash --delete-branch && git checkout main && git pull --ff-only && ./scripts/cleanup_merged_worktree.sh "$1"; }; f'
# then: git merge-and-clean 127
```

