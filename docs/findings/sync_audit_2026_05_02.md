# sync-audit — 2026-05-02 end-of-day repository and documentation state

**Audit type:** read-only repo + doc state audit (sync-and-doc-audit prompt). No code changes, no data writes. Only writes are this findings doc itself + (none required) git push.

**Pre-audit HEAD:** `24b00dd` (`inst-eid-bridge-blackrock-5-way: AUTHOR_NEW_BRIDGE for 5 BlackRock sub-brands (~$2.5T bridged) (#258)`).

---

## 1. Executive summary

| Bucket | Status | Detail |
| --- | --- | --- |
| **Pushed state** | ✅ CLEAN | `main` up to date with `origin/main` at `24b00dd`. 0 unpushed commits, 0 behind. |
| **Uncommitted state** | ⚠️ 7 untracked files in main checkout | All ephemeral / WIP / backup artifacts. None tracked. None in `.gitignore`. Surfaced for chat decision in §4. |
| **Doc integrity** | ⚠️ 5 `<TBD>` squash placeholders + 1 missing COMPLETED entry | Today's three execution PRs left `<TBD>` placeholders in ROADMAP that should now be filled with real squash SHAs; PR #253 (query4 fix) lacks a COMPLETED row entirely. Surfaced in §3.1. |
| **Worktree hygiene** | ⚠️ 1 worktree (this audit's), prunable on completion | `quirky-wozniak-7e360f` at `24b00dd` (= main HEAD), no uncommitted work. Plan in §5. |
| **Branch hygiene** | ⚠️ 14 today's local branches all squash-merged + 1 carries unmerged Op H work | 13 safe to prune; `inst-eid-bridge-fix-aliases` carries 1 substantive unmerged commit (`1aa961e` Op H AT-side ERH residual). Plan in §5. |
| **Cross-references** | ✅ CLEAN | All PR numbers and SHAs cited in ROADMAP / decisions / findings docs resolve. No broken links. |
| **Today's session arc completeness** | ✅ All commits present in git | 20 commits dated 2026-05-02 on main (12 PR-merge + 8 direct-to-main). Chat instance under-counted — see §3.5. |

**Action items requiring chat decision** are listed at the end of §4 and §5.

---

## 2. Phase 0 — repository state

### 2.1 Working tree state (main checkout)

`git status` from `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership`:

```
On branch main
Your branch is up to date with 'origin/main'.

Untracked files:
  data/.ingestion_lock
  data/13f_pre_quarter_fix.duckdb
  data/13f_staging.duckdb.pre_inf39_backup
  data/reports/dm13_bc_triage.csv
  data/reports/dm13_de_triage.csv
  docs/plans/phase-b-c-handoff-context-v2.md
  scripts/oneoff/_unknown_orphans.csv
```

`git check-ignore -v` against all 7 returned no matches — none are `.gitignore`-covered. They are true untracked files.

**Categorization:**

| Path | Category | Recommended action |
| --- | --- | --- |
| `data/.ingestion_lock` | (a) ephemeral runtime lock | DISCARD (or add to `.gitignore`) |
| `data/13f_pre_quarter_fix.duckdb` | (c) historical DB snapshot, large | DISCARD (likely supplanted by `data/backups/` snapshots) |
| `data/13f_staging.duckdb.pre_inf39_backup` | (c) backup file | DISCARD (named-backup pattern; keep in `data/backups/` only) |
| `data/reports/dm13_bc_triage.csv` | (c) old triage CSV | DISCARD (DM13 closed; see Apr 11–12 entity QC marathon memory) |
| `data/reports/dm13_de_triage.csv` | (c) old triage CSV | DISCARD |
| `docs/plans/phase-b-c-handoff-context-v2.md` | (a) WIP plan doc | KEEP — surface for chat decision: commit, refresh, or archive? |
| `scripts/oneoff/_unknown_orphans.csv` | (c) old script artifact | DISCARD (`fund-orphan-*` cohort closed via PRs #244, #245, #246, #247) |

All 7 are in main checkout, not the worktree. None block the audit. Surfaced for chat decision in §4.

### 2.2 Local vs remote state

```
git log origin/main..HEAD --oneline   →  (empty)
git log HEAD..origin/main --oneline   →  (empty)
```

`main` is up to date with `origin/main` at `24b00dd`. **0 unpushed commits, 0 behind.** No push action required.

### 2.3 Worktree state

```
git worktree list:
/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership                                          24b00dd [main]
/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/quirky-wozniak-7e360f  24b00dd [claude/quirky-wozniak-7e360f]
```

**1 active worktree** (`quirky-wozniak-7e360f`, this audit). Status:
- Branch: `claude/quirky-wozniak-7e360f` at `24b00dd` (= main HEAD)
- `git status`: clean (`nothing to commit, working tree clean`)
- No uncommitted work, no divergence from main

Cleanup plan in §5.

### 2.4 Branch state

**Local branches:** 21 (`*` = current; `+` = checked out by worktree):
```
  cef-residual-cleanup-adx
  cef-scoping
  claude/angry-hypatia-3c51a9
  claude/competent-mclean-b334c6
  claude/cool-torvalds-4a3b12
  claude/cranky-hugle-c74f17
  claude/eager-moore-74200c
  claude/ecstatic-mestorf-d20e8a
  claude/epic-chebyshev-064eeb
  claude/epic-roentgen-4bdb17
  claude/flamboyant-einstein-b40e83
  claude/goofy-grothendieck-34bff4
  claude/inspiring-taussig-f883e7
  claude/modest-snyder-b17577
  claude/nifty-mcclintock-fe137b
+ claude/quirky-wozniak-7e360f
  claude/reverent-lamarr-504059
  claude/strange-nobel-b666b1
  claude/thirsty-golick-043667
  fund-orphan-audit
  fund-orphan-backfill
  fund-stale-unknown-cleanup
  fund-universe-value-corrections
  fund-unknown-attribution
  ingestion-manifest-reconcile
  inst-eid-bridge-blackrock-5-way
  inst-eid-bridge-fix-aliases
  inst-eid-bridge-investigation
* main
  post-248-doc-sync
  query4-fix-option-a
  roadmap-cp2-mark-complete
```

**Today's named local branches (14)** — squash-merge status:

| Branch | Branch HEAD | Merged via | Squash SHA | Unmerged commits | Disposition |
| --- | --- | --- | --- | --- | --- |
| `cef-residual-cleanup-adx` | `3166bee` | PR #250 | `adb1ba9` | 2 (pre-squash WIP) | PRUNE |
| `cef-scoping` | `eaf299b` | PR #249 | `2475141` | 1 (pre-squash) | PRUNE |
| `fund-orphan-audit` | `4fa6323` | PR #244 | `65da8cc` | 1 | PRUNE |
| `fund-orphan-backfill` | `4ca6c14` | PR #245 | `9392a36` | 2 | PRUNE |
| `fund-stale-unknown-cleanup` | `af8849b` | PR #247 | `0296107` | 2 | PRUNE |
| `fund-universe-value-corrections` | `9b0056b` | PR #248 | `8253713` | 2 | PRUNE |
| `fund-unknown-attribution` | `cc8494b` | PR #246 | `1956ea8` | 1 | PRUNE |
| `ingestion-manifest-reconcile` | `cad4f5b` | PR #255 | `afd5c2f` | 2 | PRUNE |
| `inst-eid-bridge-blackrock-5-way` | `f2f435c` | PR #258 | `24b00dd` | 2 | PRUNE |
| **`inst-eid-bridge-fix-aliases`** | **`1aa961e`** | **PR #256 squash `44ed79c`** | **4 commits unmerged inc. Op H** | **HOLD — see §5** |
| `inst-eid-bridge-investigation` | `9b65e64` | PR #254 | `45bb746` | 1 | PRUNE |
| `post-248-doc-sync` | `3d57804` | direct-to-main `3d57804` | 0 | PRUNE (already on main) |
| `query4-fix-option-a` | `8c08f7b` | PR #253 | `bad48f6` | 1 | PRUNE |
| `roadmap-cp2-mark-complete` | `ef02233` | PR #257 | `d2ce6f9` | 3 (incl. shared `cad4f5b`) | PRUNE |

**`inst-eid-bridge-fix-aliases` carries unmerged work** — chat-deferred Op H supplement for AT-side `entity_rollup_history` residual (114 rows / 57 fund_eids → eid=1; 325 rows / 163 entity_ids → eid=30). The CP-4a ROADMAP entry (line 219) flagged this as: "ship corrective Op H supplement before merge OR open follow-up PR `inst-eid-bridge-aliases-rollup-residual` (P2)" — chat decision required. PR #256 merged WITHOUT Op H. Branch retains the work in commit `1aa961e`. **Do NOT prune until chat decides on follow-up PR.**

**Stale `claude/*` branches (15)** — pre-existing worktree branches (one per past worktree). Not in scope for today's audit (no PRs landed from these branches today). Surface in §5 as candidate for separate hygiene sweep.

**Remote branches:** ~120 total (`git branch -r` count). Many `remediation/*`, `conv-*`, `claude/*` branches likely already merged or stale. Not enumerated individually in this audit; surface in §5 as candidate for separate `branch-hygiene` PR sweep.

### 2.5 Stash state

```
git stash list   →  (empty)
```

**0 stashes.** Clean.

---

## 3. Phase 1 — documentation audit

### 3.1 ROADMAP.md vs actual PR state

**ROADMAP.md** is at the repo root, 442 lines, last header-stamp 2026-05-01 (`conv-24-doc-sync`). The header timestamp is **stale** — today landed 12 PRs (#247–#258) plus 8 direct-to-main commits, none reflected in the header. Recommend a `conv-25-doc-sync` (or per the new naming, `sync-audit-2026-05-02-doc-sync`) that bumps the header.

**PR reference counts in ROADMAP for today's PRs:**

| PR | ROADMAP refs | COMPLETED row? | Status |
| --- | --- | --- | --- |
| #247 fund-stale-unknown-cleanup | 8 | yes | ✅ |
| #248 fund-universe-value-corrections | 2 | yes | ✅ |
| #249 cef-scoping | 12 | yes | ✅ |
| #250 cef-residual-cleanup-adx | 3 | yes (line 222, **`<TBD>` placeholder**) | ⚠️ TBD |
| #251 cef-asa-flip-and-relabel | 2 | yes (line 221, **`<TBD>` placeholder**) + line 21 (**`<TBD>` placeholder**) | ⚠️ TBD ×2 |
| #252 institution-scoping | 5 | yes | ✅ |
| **#253 query4-fix-option-a** | **0** | **no** | ❌ MISSING |
| #254 inst-eid-bridge-investigation | 4 | yes | ✅ |
| #255 ingestion-manifest-reconcile | 3 | yes (squash `afd5c2f` filled) | ✅ |
| #256 inst-eid-bridge-fix-aliases | 3 | yes (line 219, **`<TBD>` placeholder**) | ⚠️ TBD |
| #257 roadmap CP-2 marker | 0 | bundled into #255 entry | ✅ (intentional) |
| #258 inst-eid-bridge-blackrock-5-way | 2 | yes (line 218, **`<TBD>` placeholder**) | ⚠️ TBD |

**`<TBD>` placeholders in ROADMAP that should now be filled:**

| File:line | Placeholder | Real value |
| --- | --- | --- |
| `ROADMAP.md:21` | PR-B `cef-asa-flip-and-relabel` squash `<TBD>` | `433ebe3` (PR #251) |
| `ROADMAP.md:218` | inst-eid-bridge-blackrock-5-way squash `<TBD>` | `24b00dd` (PR #258) |
| `ROADMAP.md:219` | inst-eid-bridge-fix-aliases squash `<TBD>` | `44ed79c` (PR #256) |
| `ROADMAP.md:221` | cef-asa-flip-and-relabel squash `<TBD>` ([#TBD]) | `433ebe3` ([#251](https://github.com/ST5555-Code/Institutional-Ownership/pull/251)) |
| `ROADMAP.md:222` | cef-residual-cleanup-adx squash `<TBD>` ([#TBD]) | `adb1ba9` ([#250](https://github.com/ST5555-Code/Institutional-Ownership/pull/250)) |

The `<TBD>` pattern is used because each PR is authored before its squash SHA is known; convention is to backfill in a doc-sync follow-up. Today, that doc-sync hasn't run yet.

**Missing COMPLETED entry — PR #253 (query4-fix-option-a):**
- Inline references at `ROADMAP.md:23` (open `parent-level-display-canonical-reads` entry mentions the bug it fixes) and `ROADMAP.md:24` (open `inst-eid-bridge` Wave-1 sequencing mentions CP-3 = `query4-fix-option-a`).
- No row in COMPLETED table dated 2026-05-02 for `query4-fix-option-a`.
- Squash commit message (bad48f6) cites "PR #252 Phase 4 quantified the bug at LQ: 1,543,537 rows / $23.0T (48.15% rows / 34.21% AUM)" — material enough to deserve a COMPLETED row.

**Recommendation:** add a COMPLETED row for PR #253 referencing squash `bad48f6` and the bug-quant numbers; update the open `parent-level-display-canonical-reads` and `inst-eid-bridge` Wave-1 entries to mark CP-3 shipped.

**Other `TBD` mentions** (non-blocking, pre-existing):
- `docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md:1003` — "threshold TBD" (closed-out doc)
- `docs/findings/dm-open-surface-2026-04-22.md:153` — "TBD when audit runs" (Apr 22 surface)
- `docs/findings/institution_scoping_phase_1B_15.md:93` — "TBD pending a brand-alias map" (PR #252 doc, intentional)
- `docs/findings/obs-08-p1-findings.md:223` — "PR #TBD" placeholder in remediation plan
- `docs/findings/obs-07-p0-findings.md:197` — "TBD" file path in test-plan

These are intentional or historical — out of scope for today.

### 3.2 Decisions doc audit

`docs/decisions/` contains **1 file**: `inst_eid_bridge_decisions.md`.

This was created by direct-to-main commit `6b31fe7` ("decisions: inst-eid-bridge BLOCKER resolutions + 2 new ROADMAP entries + CP-2 unblock"), referenced from ROADMAP `inst-eid-bridge` entry (line 24) and from PR #255, #256, #258 entries. Cross-references resolve. No broken links.

### 3.3 Findings doc audit

`docs/findings/` contains **127 files** total. Today's session created 14 new findings docs (or augmented existing ones):

- `cef_asa_prep_investigation.md` (PR-B scoping, commit `79350a5`)
- `cef_residual_cleanup_adx_dryrun.md` + `cef_residual_cleanup_adx_results.md` (PR #250)
- `cef_residual_cleanup_asa_dryrun.md` + `cef_residual_cleanup_asa_results.md` (PR #251)
- `cef_scoping.md` (PR #249)
- `ingestion_manifest_reconcile_dryrun.md` + `ingestion_manifest_reconcile_results.md` (PR #255)
- `inst_eid_bridge_aliases_dryrun.md` + `inst_eid_bridge_aliases_results.md` (PR #256)
- `inst_eid_bridge_blackrock_5_way_dryrun.md` + `inst_eid_bridge_blackrock_5_way_results.md` (PR #258)
- `inst_eid_bridge_investigation.md` (PR #254)
- `institution_scoping.md` + 6 partial files (`institution_scoping_partial_*`, `institution_scoping_phase_*`) (PR #252)
- `query4_fix_results.md` (PR #253)

Plus 5 supporting JSON artifacts: `_inst_eid_bridge_phase{0,1,1b,2,4}.json`.

**Orphans / cleanup candidates:**

| File | Notes | Recommendation |
| --- | --- | --- |
| `institution_scoping_partial_1a_5.md`, `institution_scoping_partial_1b_1.5.md`, `institution_scoping_partial_2_3.md`, `institution_scoping_partial_4_6.md` | 4 intermediate partial files from PR #252 phased authoring | Likely supplanted by the consolidated `institution_scoping.md` + `institution_scoping_phase_1A_5.md` + `institution_scoping_phase_1B_15.md`. Surface for chat decision: archive or delete? |
| `_inst_eid_bridge_phase*.json` (5 files) | Underscore prefix indicates intermediate machine-readable artifacts | Keep (these are the read-only inventory snapshots referenced by inst-eid-bridge results docs). |

No genuine orphans (all PR-derived findings docs map to merged PRs). All cited PRs are merged and in git log.

### 3.4 Cross-reference integrity

Spot-checked ROADMAP, decisions, and today's findings docs for inline PR-number refs (`#247`–`#258`) and SHA refs from today (`24b00dd`, `44ed79c`, `d2ce6f9`, `afd5c2f`, `6b31fe7`, `45bb746`, `bad48f6`, `c53337c`, `63fe2af`, `433ebe3`, `7aa535c`, `79350a5`, `adb1ba9`, `4ee2b97`, `2475141`, `3d57804`, `8253713`, `ab376f1`, `1cbb1d4`, `0296107`).

- All 12 PR numbers resolve to real merged PRs in git log.
- All 20 today's SHAs resolve to commits on `main`.
- Apart from the 5 `<TBD>` placeholders (§3.1), no broken refs.

### 3.5 Today's session arc completeness

Chat instance reported: 10 PRs (#249–#258) + 4 direct-to-main commits (`7aa535c`, `c53337c`, `6b31fe7`, `4ee2b97`).

**Actual git log for 2026-05-02 (20 commits):**

| Time (ET) | SHA | Type | Subject |
| --- | --- | --- | --- |
| 22:15 | `24b00dd` | PR #258 | inst-eid-bridge-blackrock-5-way |
| 20:24 | `44ed79c` | PR #256 | inst-eid-bridge-fix-aliases |
| 19:34 | `d2ce6f9` | PR #257 | roadmap CP-2 mark complete |
| 19:29 | `afd5c2f` | PR #255 | ingestion-manifest-reconcile |
| 18:50 | `6b31fe7` | direct | decisions: inst-eid-bridge BLOCKER + 2 ROADMAP + CP-2 unblock |
| 18:19 | `45bb746` | PR #254 | inst-eid-bridge-investigation |
| 18:17 | `bad48f6` | PR #253 | query4 silent-drop fix |
| 16:57 | `c53337c` | direct | roadmap: institution-scoping follow-ups |
| 16:52 | `63fe2af` | PR #252 | institution-scoping read-only |
| 15:29 | `433ebe3` | PR #251 | cef-asa-flip-and-relabel |
| 14:40 | `7aa535c` | direct | roadmap: cef-residual-cleanup PR-B reframe |
| 14:26 | `79350a5` | direct | cef-asa-prep-investigation (PR-B scoping) |
| 13:47 | `adb1ba9` | PR #250 | cef-residual-cleanup-adx |
| 11:11 | `4ee2b97` | direct | roadmap: cef-attribution-path → cef-residual-cleanup reframe |
| 09:11 | `2475141` | PR #249 | cef-scoping |
| 08:39 | `3d57804` | direct | docs: post-#248-doc-sync |
| 08:35 | `8253713` | PR #248 | fund-universe-value-corrections |
| 06:43 | `ab376f1` | direct | roadmap: cef-attribution-path + v2-loader watchpoint (close-out PR #247) |
| 06:07 | `1cbb1d4` | direct | docs: post-#247-doc-sync |
| 06:05 | `0296107` | PR #247 | fund-stale-unknown-cleanup BRANCH 1 |

**Reconciliation vs chat report:**

- Chat reported 10 PRs (#249–#258); actual is **12 PRs (#247–#258)**. Chat omitted PRs #247 and #248, both shipped early morning (06:05 and 08:35 ET).
- Chat reported 4 direct-to-main commits; actual is **8 direct-to-main commits**: chat's 4 (`7aa535c`, `c53337c`, `6b31fe7`, `4ee2b97`) + 4 more (`79350a5` PR-B scoping, `3d57804` #248-doc-sync, `ab376f1` close-out PR #247, `1cbb1d4` #247-doc-sync).
- All 20 commits present in git on main, dated 2026-05-02. **No missing commits, no unexpected content.**

This is a chat-side accounting drift, not a repo-side gap. Surface for chat instance's mental model only — no action needed.

---

## 4. Phase 2 — sync gaps

### 4.1 Sync actions taken

**None.** `main` was already at `origin/main` pre-audit; no `git push` required. No worktree had uncommitted work needing commit. No broken refs needed automatic patching (per audit constraint, all doc fixes are surfaced for chat decision).

### 4.2 Gaps requiring chat decision

**A. ROADMAP `<TBD>` placeholder cleanup (§3.1):** 5 placeholders in `ROADMAP.md:21,218,219,221,222`. Recommended: ship a doc-sync direct-to-main commit that fills each `<TBD>` with the real squash SHA + PR URL per §3.1 table.

**B. Missing COMPLETED entry for PR #253 (§3.1):** `query4-fix-option-a` shipped at 18:17 ET (`bad48f6`) but has no row in the COMPLETED table. Recommended: add a 2026-05-02 row in the same doc-sync as item A.

**C. ROADMAP header date stamp (§3.1):** still reads `Updated 2026-05-01 (conv-24-doc-sync)`. Bump in same doc-sync.

**D. Untracked working-tree artifacts (§2.1):** 7 files in main checkout (5 DISCARD candidates, 1 .gitignore candidate, 1 plan-doc). Surface for chat decision per §2.1 table.

**E. Unmerged Op H on `inst-eid-bridge-fix-aliases` (§2.4):** Substantive `entity_rollup_history` AT-side cleanup (commit `1aa961e`) deferred from PR #256 per chat decision. CP-4a ROADMAP entry asks: ship Op H supplement (new PR `inst-eid-bridge-aliases-rollup-residual`) or close out as P2 follow-up? Decision needed before pruning the branch.

**F. `institution_scoping_partial_*.md` cleanup (§3.3):** 4 partial files from PR #252 phased authoring likely supplanted by the consolidated `institution_scoping.md`. Archive or delete?

---

## 5. Phase 3 — worktree & branch cleanup plan

### 5.1 Worktree cleanup

Single active worktree: `quirky-wozniak-7e360f` (this audit's worktree).

| Worktree | Branch | HEAD | Uncommitted | Disposition |
| --- | --- | --- | --- | --- |
| `quirky-wozniak-7e360f` | `claude/quirky-wozniak-7e360f` | `24b00dd` (= main) | none | **PRUNE on audit complete** (`git worktree remove .claude/worktrees/quirky-wozniak-7e360f` + `git branch -D claude/quirky-wozniak-7e360f`). Awaiting chat authorization. |

### 5.2 Local branch cleanup

**Safe to PRUNE (13 branches)** — all PR squash-merged or already on main; pre-squash WIP commits are preserved through the squash:

```
cef-residual-cleanup-adx           (PR #250 squash adb1ba9)
cef-scoping                        (PR #249 squash 2475141)
fund-orphan-audit                  (PR #244 squash 65da8cc)
fund-orphan-backfill               (PR #245 squash 9392a36)
fund-stale-unknown-cleanup         (PR #247 squash 0296107)
fund-universe-value-corrections    (PR #248 squash 8253713)
fund-unknown-attribution           (PR #246 squash 1956ea8)
ingestion-manifest-reconcile       (PR #255 squash afd5c2f)
inst-eid-bridge-blackrock-5-way    (PR #258 squash 24b00dd)
inst-eid-bridge-investigation      (PR #254 squash 45bb746)
post-248-doc-sync                  (direct 3d57804, already on main)
query4-fix-option-a                (PR #253 squash bad48f6)
roadmap-cp2-mark-complete          (PR #257 squash d2ce6f9)
```

Pruning command (await chat authorization):
```
git branch -D cef-residual-cleanup-adx cef-scoping fund-orphan-audit fund-orphan-backfill \
              fund-stale-unknown-cleanup fund-universe-value-corrections fund-unknown-attribution \
              ingestion-manifest-reconcile inst-eid-bridge-blackrock-5-way inst-eid-bridge-investigation \
              post-248-doc-sync query4-fix-option-a roadmap-cp2-mark-complete
```

**HOLD (1 branch):**

```
inst-eid-bridge-fix-aliases        carries unmerged Op H (commit 1aa961e)
                                   chat decision required per §4.2 item E
```

**Out-of-scope (15 stale `claude/*` branches):** pre-existing artifacts of past worktrees. Recommend separate `branch-hygiene` sweep PR (`git for-each-ref --merged main 'refs/heads/claude/*'` to confirm safety first). Not pruned by this audit.

**Out-of-scope (~120 remote branches):** large remote-side cleanup needed. Recommend separate sweep PR; not in scope for today.

---

## 6. Action summary (for chat)

| # | Action | Owner | Type |
| --- | --- | --- | --- |
| 1 | Authorize `<TBD>` placeholder fill + #253 COMPLETED row + header bump (single doc-sync commit) | chat | doc-sync |
| 2 | Decide on Op H supplement (new PR `inst-eid-bridge-aliases-rollup-residual`?) before pruning `inst-eid-bridge-fix-aliases` | chat | scope |
| 3 | Decide on 7 untracked files in main checkout (DISCARD vs commit vs `.gitignore`) | chat | hygiene |
| 4 | Decide on 4 `institution_scoping_partial_*.md` files (archive or delete) | chat | hygiene |
| 5 | Authorize pruning of 13 squash-merged today branches + this audit's worktree | chat | hygiene |
| 6 | Schedule separate `branch-hygiene` sweep PR for 15 stale `claude/*` + remote cleanup | chat | scope |

---

**Audit author:** sync-and-doc-audit (read-only, executed 2026-05-02 end-of-day).
**Pre-audit HEAD / post-audit HEAD:** `24b00dd` → (this commit, direct-to-main).
**Push state at audit time:** clean (already at `origin/main`).
