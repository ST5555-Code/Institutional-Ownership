# branch-cleanup — local branch audit & bulk prune

**Date:** 2026-05-01
**Working tree:** main checkout at `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership`
**HEAD pre-cleanup:** `5af96e1` (fund-cleanup-batch — 4 fund-level follow-ups + 2 credit reclassifications, [#242](https://github.com/sergetismen/13f-ownership/pull/242))

## Summary

| Metric | Pre | Post | Δ |
|---|---|---|---|
| Local branches | 80 | 4 | -76 |
| Remote refs | 128 | 128 | 0 (already pruned by `git fetch --prune`) |
| Worktrees | 2 | 2 | 0 (both active, neither stale) |

76 branches deleted. 4 retained: `main`, the active session worktree branch (`claude/competent-mclean-b334c6`), and 2 closed-PR audit branches awaiting chat decision.

## Phase 1 — Pre-cleanup inventory

Categorisation rules (per the executing plan):

- **MERGED** — `git log <branch> --not main` returns 0 commits
- **SQUASH-MERGED** — has commits not in main, but its head PR (`gh pr list`) is in `MERGED` state (squash-merge produced a different SHA in main)
- **WORKTREE-LOCKED** — branch is the HEAD of an active worktree
- **UNMERGED** — has commits not in main, and either no PR record or the PR is `CLOSED` without merge

`gh pr list --state all` returned 242 PRs (239 MERGED, 3 CLOSED, 0 OPEN), giving an authoritative signal for every branch with a PR record.

| Category | Count |
|---|---|
| MERGED | 5 |
| SQUASH-MERGED | 71 |
| UNMERGED | 2 |
| WORKTREE-LOCKED | 1 |
| (`main`) | 1 |
| **Total** | **80** |

UNMERGED count (2) was well below the 50-branch STOP threshold; categorisation accepted.

### MERGED branches (5)

Traditional merge commits already reachable from `main`. Deleted with `git branch -d` (safe delete).

| branch | last sha | last date | last commit message |
|---|---|---|---|
| `claude/hopeful-almeida-3e1fd3` | db0e3e7 | 2026-04-30 | docs: nport-classify-scope — fund-level classification scoping (#232) |
| `claude/jovial-kirch-bb0cc5` | 414b824 | 2026-05-01 | fix: fund-strategy-rename — value rename + column rename + peer_rotation JOIN |
| `claude/objective-cori-66eb3d` | 928e7ab | 2026-05-01 | fix: fund-strategy-consolidate — drop fund_category + is_actively_managed |
| `claude/optimistic-ardinghelli-befa15` | db0e3e7 | 2026-04-30 | docs: nport-classify-scope — fund-level classification scoping (#232) |
| `conv-23-doc-sync` | 7fa92ff | 2026-05-01 | docs: conv-23-doc-sync — fund-level consolidation closed, 8 PRs merged |

### SQUASH-MERGED branches (71)

PR merged via squash; local SHA differs from the squash commit in main. All 71 carry `state=MERGED` in `gh pr list`. Deleted with `git branch -D` (force).

| branch | PR | last sha | last date | on origin? |
|---|---|---|---|---|
| `bl3-inf53` | #189 | a0557d1 | 2026-04-28 | no |
| `bug-close-doc` | #153 | 9e0558d | 2026-04-25 | no |
| `classify-consolidate-plan` | #231 | 83af04f | 2026-04-30 | no |
| `classify-scope` | #230 | ece1b50 | 2026-04-30 | no |
| `claude/admiring-mahavira-ad38a9` | #173 | 7f231ea | 2026-04-27 | no |
| `claude/beautiful-shaw-b808a4` | #192 | eac8c02 | 2026-04-28 | yes |
| `claude/elegant-cori-8c40e3` | #191 | b5afaad | 2026-04-28 | no |
| `claude/eloquent-goldwasser-e65e97` | #170 | b9463ed | 2026-04-26 | no |
| `claude/friendly-lamarr-eaf0bb` | #179 | 08fac8c | 2026-04-27 | no |
| `claude/funny-newton-fe14c8` | #196 | 5a888e1 | 2026-04-28 | no |
| `claude/gifted-joliot-dc6ce8` | #188 | e9de258 | 2026-04-27 | no |
| `claude/goofy-feynman-10f625` | #174 | 2f1bccd | 2026-04-27 | no |
| `claude/gracious-merkle-2d7394` | #152 | 4ea791f | 2026-04-24 | no |
| `claude/jovial-wilson-3074d4` | #237 | 9e9697f | 2026-05-01 | yes |
| `claude/laughing-euclid-50647c` | #185 | bfe7b7a | 2026-04-27 | no |
| `claude/naughty-nash-652d51` | #200 | 4cc790b | 2026-04-28 | no |
| `claude/nice-vaughan-8da17c` | #198 | deacd0c | 2026-04-28 | no |
| `claude/optimistic-lamport-78dc7e` | #199 | 85ff1e8 | 2026-04-28 | no |
| `claude/pedantic-zhukovsky-75af97` | #187 | 9a973f2 | 2026-04-27 | yes |
| `claude/quizzical-saha-ee5658` | #190 | b94e3f4 | 2026-04-28 | no |
| `claude/sharp-hopper-a901c0` | #197 | c466ebd | 2026-04-28 | yes |
| `claude/sleepy-pasteur-21634a` | #195 | 4c6f82d | 2026-04-28 | no |
| `claude/stoic-nash-325d62` | #193 | 392f11f | 2026-04-28 | yes |
| `claude/trusting-jones-fbbe88` | #175 | d14ae47 | 2026-04-27 | no |
| `claude/zealous-lalande-bcbf7b` | #184 | c3d6de5 | 2026-04-27 | no |
| `claude/zen-sammet-50dea7` | #178 | 92ec615 | 2026-04-27 | no |
| `compact-density` | #212 | 0aadb78 | 2026-04-29 | no |
| `controls-panel-border` | #222 | fef748c | 2026-04-30 | yes |
| `conv-14-doc-sync` | #182 | 03befd9 | 2026-04-27 | yes |
| `conv-16-doc-sync` | #201 | 613df8a | 2026-04-28 | no |
| `cross-ownership-fix` | #229 | 90a705a | 2026-04-30 | yes |
| `cross-ownership-polish` | #228 | a52fac6 | 2026-04-30 | yes |
| `dark-ui-restyle` | #202 | 8779ed8 | 2026-04-29 | yes |
| `dm13-bc-suppress` | #169 | 3d9a567 | 2026-04-26 | no |
| `doc-sync` | #157 | 56d9a04 | 2026-04-25 | no |
| `doc-sync-2` | #160 | 463ed18 | 2026-04-25 | no |
| `doc-sync-4` | #163 | e0c8c3a | 2026-04-26 | no |
| `doc-sync-5` | #167 | 6f0d29c | 2026-04-26 | no |
| `eqt-classify-fix` | #162 | c9f702c | 2026-04-26 | no |
| `export-bar-align` | #221 | 78167fb | 2026-04-30 | yes |
| `fund-strategy-backfill` | #233 | b687c02 | 2026-04-30 | yes |
| `inf48-49-entity-dedup` | #176 | f3d287d | 2026-04-27 | no |
| `inf51-prod-dedup` | #186 | 56e7811 | 2026-04-27 | no |
| `investor-detail-dedup` | #211 | c644150 | 2026-04-29 | no |
| `investor-detail-redesign` | #210 | 92196ce | 2026-04-29 | yes |
| `layout-header-fullwidth` | #204 | 76a7433 | 2026-04-29 | yes |
| `nport-quarter-fix` | #213 | 6f59536 | 2026-04-30 | yes |
| `overlap-column-stats` | #225 | e1e1888 | 2026-04-30 | yes |
| `overlap-tab-redesign` | #224 | b1c8e5e | 2026-04-30 | yes |
| `pct-rename-sweep` | #171 | f381786 | 2026-04-26 | yes |
| `perf-p0-s1` | #158 | 66695ad | 2026-04-25 | no |
| `perf-p0-s2` | #159 | 662677d | 2026-04-25 | no |
| `perf-p1-cohort-cache` | #181 | 318b39b | 2026-04-27 | no |
| `perf-p1-sector` | #180 | e50d109 | 2026-04-27 | no |
| `pk-enforce` | #165 | f294f0b | 2026-04-26 | no |
| `quarter-label-global` | #226 | 395e23a | 2026-04-30 | yes |
| `react-cleanup-inf28` | #177 | dab90f3 | 2026-04-27 | no |
| `roadmap-priority-moves` | #183 | 3eec6a3 | 2026-04-27 | yes |
| `roadmap-quarter-label-global` | #227 | 96df19b | 2026-04-30 | yes |
| `rule9-43e` | #194 | 0414977 | 2026-04-28 | no |
| `sector-rotation-redesign` | #205 | 38dae5d | 2026-04-29 | yes |
| `si-chart-table-align` | #220 | 8819c82 | 2026-04-30 | yes |
| `si-layout-fix` | #219 | 1d2e743 | 2026-04-30 | yes |
| `si-tab-redesign` | #216 | 0572901 | 2026-04-30 | no |
| `si-table-quarter-polish` | #223 | 38d9424 | 2026-04-30 | yes |
| `snapshot-cadence` | #164 | 4e74894 | 2026-04-26 | yes |
| `sr-chart-movers-fix` | #208 | 3045b36 | 2026-04-29 | yes |
| `sr-fund-quarter-filter` | #215 | 330f605 | 2026-04-30 | yes |
| `sr-layout-polish` | #206 | 8d6055e | 2026-04-29 | yes |
| `sr-polish-v2` | #218 | 18a4266 | 2026-04-30 | yes |
| `tab-page-headers` | #214 | 8c19def | 2026-04-30 | no |

41 of 71 had `origin=no` (remote ref already pruned by `git fetch --prune` at session start, indicating GitHub auto-deleted the head branch on merge). The other 30 still carry a remote ref but the corresponding PR is in `MERGED` state — local can be pruned safely.

### WORKTREE-LOCKED (1)

| branch | last sha | path |
|---|---|---|
| `claude/competent-mclean-b334c6` | 5af96e1 | `.claude/worktrees/competent-mclean-b334c6` (this session) |

Not deleted — referenced by an active worktree.

## Phase 2 — Bulk delete

```bash
# 2a — MERGED (safe delete)
git branch -d claude/hopeful-almeida-3e1fd3 claude/jovial-kirch-bb0cc5 \
              claude/objective-cori-66eb3d claude/optimistic-ardinghelli-befa15 \
              conv-23-doc-sync
# Result: 5/5 deleted.

# 2b — SQUASH-MERGED (force)
xargs git branch -D < /tmp/squash_list.txt
# Result: 71/71 deleted.

# 2c — STALE worktrees: none.
git worktree list
#   /…/13f-ownership                                           5af96e1 [main]
#   /…/13f-ownership/.claude/worktrees/competent-mclean-b334c6 5af96e1 [claude/competent-mclean-b334c6]
# Both worktrees exist on disk and are active; nothing to remove.

# 2d — Post-cleanup count
git branch | wc -l
#   4
```

Final state:

```
+ claude/competent-mclean-b334c6
  claude/reverent-kirch-c1fcdf
* main
  ui-audit-01
```

## Phase 3 — UNMERGED branches (chat decision required)

Both branches have a `CLOSED` PR (closed without merging). Branches were intentionally not merged at the time the PRs were closed; whether to retain them locally depends on whether the work is captured elsewhere.

| branch | last sha | last date | last commit message | on origin? | PR | recommendation |
|---|---|---|---|---|---|---|
| `claude/reverent-kirch-c1fcdf` | 7adb4e5 | 2026-04-26 | DM13-D/E discovery: triage CSV for residual ADV_SCHEDULE_A edges | yes | [#172](https://github.com/sergetismen/13f-ownership/pull/172) (CLOSED) | DELETE-WITH-APPROVAL — discovery-only PR; the actual fix shipped under [#173](https://github.com/sergetismen/13f-ownership/pull/173) (`DM13-D/E`) |
| `ui-audit-01` | 8a50a51 | 2026-04-22 | ui-audit-01: UI audit + query triage (discovery only) | yes | [#107](https://github.com/sergetismen/13f-ownership/pull/107) (CLOSED) | KEEP — referenced by ROADMAP P1 `ui-audit-walkthrough` (`docs/ui-audit-01-triage.md` is the deliverable; the branch may carry the underlying triage notes) |

**Action items:**
1. Confirm `claude/reverent-kirch-c1fcdf` discovery work is fully captured in the merged PR-#173 findings; if so, `git branch -D claude/reverent-kirch-c1fcdf`.
2. Confirm `ui-audit-01`'s working notes are committed to main (or no longer needed) before deletion. If main has `docs/ui-audit-01-triage.md` and the ui-audit-walkthrough P1 work doesn't depend on the branch tip, `git branch -D ui-audit-01`.

Both decisions are out of scope for this housekeeping commit. Tracked as P3 `unmerged-branch-decisions` in ROADMAP.

## Out of scope (per plan)

- Remote-side branch cleanup beyond what `git fetch --prune` did automatically (origin still carries 30 remote refs whose PRs are merged; user manages via `gh` when needed).
- Reflog cleanup, tag pruning.
- Removing the `.claude/worktrees/` parent directory if it ends up empty.
