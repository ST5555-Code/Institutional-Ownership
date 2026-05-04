# worktree-cleanup-hygiene — results

P3 ops PR. Retired 4 stale worktrees, 36 local branches, 6 orphan
remote branches accumulated through recent arcs (cp-4b carve-out,
fund-typed-ech-cleanup, backup-pruning-and-archive). No DB writes.

## 1. Phase 1 inventory snapshot

Pre-retire baseline (HEAD = `46fa3fb`):

- 6 worktrees total (1 main, 1 active session, 4 retire candidates)
- 38 local branches (1 main, 1 active session, 36 retire candidates,
  1 INVESTIGATE)
- 142 remote branches on origin (6 orphan post-merge)

Full retirement table archived at
[data/working/worktree-cleanup-inventory.csv](../../data/working/worktree-cleanup-inventory.csv).

## 2. Worktrees retired

| path | branch | category | reason |
|---|---|---|---|
| `.claude/worktrees/condescending-payne-657a73` | `claude/condescending-payne-657a73` | RETIRE_MERGED_PR | PR #264 merged 2026-05-03 |
| `.claude/worktrees/hardcore-banach-af9cc2` | `claude/hardcore-banach-af9cc2` | RETIRE_STALE | sync-audit work, behind 18, no associated PR |
| `.claude/worktrees/kind-gauss-eb0ad2` | `claude/kind-gauss-eb0ad2` | RETIRE_MERGED_PR | PR #261 merged 2026-05-03 |
| `.claude/worktrees/nostalgic-franklin-3eaf1a` | `claude/nostalgic-franklin-3eaf1a` | RETIRE_STALE | sync-audit-resolution work, behind 17, no associated PR |

Method: `git worktree remove --force <path>` followed by
`git worktree prune -v`. `--force` was required because the
directories carried uncommitted/abandoned state from interrupted
sessions; the merged-pr branches confirm relevant work landed in
main, and the stale entries had no downstream artifacts.

## 3. Branches deleted

### 3a. IN-MAIN ancestry — safe `-d` (22)

All `claude/<slug>` worktree-spawn branches whose tip SHA is an
ancestor of `main` (i.e. they fast-forward into main). These were
left behind when older worktrees were torn down without explicit
branch deletion.

`competent-mclean-b334c6`, `condescending-payne-657a73`,
`condescending-visvesvaraya-c919ce`, `cool-torvalds-4a3b12`,
`cranky-hugle-c74f17`, `determined-johnson-b98483`,
`eager-moore-74200c`, `ecstatic-mestorf-d20e8a`,
`epic-chebyshev-064eeb`, `epic-roentgen-4bdb17`,
`flamboyant-einstein-b40e83`, `gifted-black-c4d1c6`,
`goofy-grothendieck-34bff4`, `hardcore-banach-af9cc2`,
`inspiring-taussig-f883e7`, `kind-gauss-eb0ad2`,
`modest-snyder-b17577`, `nifty-mcclintock-fe137b`,
`nostalgic-franklin-3eaf1a`, `reverent-lamarr-504059`,
`strange-nobel-b666b1`, `thirsty-golick-043667`.

### 3b. Squash-merged — force `-D` (14)

User-named arc branches and 3 `claude/<slug>` branches whose
referenced PRs were squash-merged into main. The squash creates a
new SHA, so the original branch tip is not in main's history and
`-d` rejects the delete. `-D` is appropriate because the PR record
on GitHub preserves the merge artifact.

| branch | PR | title |
|---|---|---|
| `backup-pruning-and-archive` | #273 | backup-pruning-and-archive |
| `close-fund-typed-ech-rows` | #265 | 13,220-row SCD close |
| `conv-26-doc-sync` | #266 | fund-typed-ech-cleanup arc closure |
| `conv-27-doc-sync` | #272 | cp-4b carve-out arc closure |
| `cp-4b-author-first-trust` | #269 | First Trust bridge + BLOCKER 2 amendment |
| `cp-4b-author-fmr` | #270 | Fidelity/FMR brand bridge |
| `cp-4b-author-ssga` | #271 | State Street/SSGA brand bridge |
| `cp-4b-author-trowe` | #267 | T. Rowe Price bridge |
| `cp-4b-blocker2-corroboration-probe` | #268 | 4-signal LOW cohort probe |
| `cp-4b-discovery` | #260 | top-20 AUTHOR_NEW_BRIDGE manifest |
| `claude/funny-lamarr-7e7698` | #264 | migrate-fund-typed-ech-readers |
| `claude/modest-neumann-0b6b3c` | #263 | disable-fund-typed-ech-writers |
| `claude/sleepy-wright-49f441` | #261 | unknown-classification-wave-1 |
| `unknown-classification-discovery` | #259 | tiered cohort scoping |

## 4. INVESTIGATE entries resolved in Phase 2

### 4.1 `claude/angry-hypatia-3c51a9` — DELETE_STALE (preserved as patches)

- 2 unmerged commits, last activity 2026-05-02:
  - `2ee0c29 cef-asa-flip-and-relabel: Phase 3-5 results + ROADMAP + handoff`
  - `3a1a06d cef-asa-flip-and-relabel: Phase 2 dry-run (350 byte_identical, 0 HOLD)`
- Resolution: superseded by deferred PR-B `cef-asa-period-backfill`
  plan (run v2 loader against 3 ASA periods first, then flip).
- Action before delete: `git format-patch main..` extracted both
  commits to
  [docs/findings/_archive/cef-asa-flip-exploratory/](_archive/cef-asa-flip-exploratory/).
- Branch then force-deleted with `-D`.

## 4.5 Orphan remote branches swept

`gh pr merge --squash --delete-branch` failed to delete remote
branches for 6 PRs because the worktree was using the branch at
merge time. Verified each was still live on origin via
`git ls-remote --heads origin <name>`, then deleted in a single
push.

| remote branch | PR | ls-remote pre-delete | push result |
|---|---|---|---|
| `close-fund-typed-ech-rows` | #265 | live (`d0f121a`) | `[deleted]` |
| `cp-4b-author-trowe` | #267 | live (`8c1afa`) | `[deleted]` |
| `cp-4b-author-fmr` | #270 | live (`283fcfb`) | `[deleted]` |
| `cp-4b-author-ssga` | #271 | live (`fe693ae`) | `[deleted]` |
| `conv-27-doc-sync` | #272 | live (`ff62ced`) | `[deleted]` |
| `backup-pruning-and-archive` | #273 | live (`b1dce2e`) | `[deleted]` |

Remote branch count: **142 → 136** (-6).

## 5. Disk space

| target | before | after | delta |
|---|---|---|---|
| `.claude/worktrees/` | 415 MB | 85 MB | **-330 MB** |
| `.git/` | 3.5 GB | 3.5 GB | unchanged (see note) |
| origin remote refs | 142 | 136 | -6 |

Note on `.git/` size: branch deletion only removes refs; reachable
objects become *dangling* but stay on disk until `git gc` runs.
`git fsck --no-reflogs` post-cleanup shows the expected pool of
dangling commits/trees. They'll be reaped on the next automatic
gc (typically triggered after 50 loose objects accumulate or by
`git gc --auto` invocations during normal operations). No manual
gc invoked here — this PR retires worktrees and refs only, not
object storage.

## 6. Final state confirmation

```
$ git worktree list
/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership                                           46fa3fb [main]
/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/pedantic-lamarr-c00e78  46fa3fb [claude/pedantic-lamarr-c00e78]

$ git branch -vv
* claude/pedantic-lamarr-c00e78 46fa3fb [origin/main] backup-pruning-and-archive: compress + stage 44 old backups for Drive offload (#273)
+ main                          46fa3fb (...) [origin/main] backup-pruning-and-archive: compress + stage 44 old backups for Drive offload (#273)

$ git log -1 --oneline main
46fa3fb backup-pruning-and-archive: compress + stage 44 old backups for Drive offload (#273)
```

Local branch count: **38 → 2** (active session + main only).

## 7. Process improvement note

Future arc PRs should attempt local branch + worktree cleanup as
a Phase 8 sub-step **before** returning the merge result to chat.
Captures cleanup at the moment of merge instead of accumulating
across arcs.

## 7.5 gh pr merge --delete-branch failure pattern (extension)

The `gh pr merge --delete-branch` failure is now fully
characterized: **the flag silently no-ops on the remote when the
branch is checked out by a worktree at merge time** (the GitHub
API DELETE on the branch ref succeeds silently with the worktree
holding the ref, leaving the remote branch live). This affected
all 6 of the recent arc PRs documented above.

Recommended workflow for arc PRs that run from a worktree:

1. `gh pr merge --squash` **without** `--delete-branch`.
2. `cd` to main repo.
3. `git push origin --delete <branch>` manually.
4. Worktree retires later under a future `worktree-cleanup-hygiene`
   cadence (typically once per arc, not per-PR).

Surface this in `docs/NEXT_SESSION_CONTEXT.md` under process rules
during the next conv-NN-doc-sync (likely conv-28). Until that
codifies, reviewers should expect remote-branch leaks on
worktree-spawned PRs and add the manual delete to their PR
checklist.
