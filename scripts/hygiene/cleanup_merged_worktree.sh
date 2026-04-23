#!/usr/bin/env bash
# Clean up a merged PR's local branch and its worktree.
#
# Usage:
#   scripts/cleanup_merged_worktree.sh <pr-number>
#   scripts/cleanup_merged_worktree.sh <branch-name>
#
# Behavior:
#   1. Resolve argument to a branch name (if numeric, look up via gh).
#   2. Locate any worktree that has that branch checked out.
#   3. `git worktree remove --force` the worktree.
#   4. `git branch -D` the local branch.
#   5. Refuses to touch main/master.
#
# Idempotent: if the worktree or branch is already gone, that step is skipped.

set -euo pipefail

arg=${1:-}
if [[ -z "$arg" ]]; then
  echo "usage: $0 <pr-number|branch-name>" >&2
  exit 2
fi

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# --- Resolve arg -> branch name ---------------------------------------------
if [[ "$arg" =~ ^[0-9]+$ ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "error: arg '$arg' looks like a PR number but 'gh' is not installed" >&2
    exit 2
  fi
  echo "==> Resolving PR #$arg to head branch"
  branch=$(gh pr view "$arg" --json headRefName --jq .headRefName)
  if [[ -z "$branch" ]]; then
    echo "error: could not resolve PR #$arg to a branch" >&2
    exit 1
  fi
  echo "    PR #$arg head = $branch"
else
  branch="$arg"
fi

# --- Guard against protected branches ---------------------------------------
case "$branch" in
  main|master|HEAD|"")
    echo "error: refusing to delete protected branch '$branch'" >&2
    exit 2
    ;;
esac

# --- Locate worktree for this branch (porcelain parser) ---------------------
worktree_path=""
current_path=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*)
      current_path="${line#worktree }"
      ;;
    "branch refs/heads/$branch")
      worktree_path="$current_path"
      ;;
    "")
      current_path=""
      ;;
  esac
done < <(git worktree list --porcelain)

# --- Remove worktree --------------------------------------------------------
if [[ -n "$worktree_path" ]]; then
  # Never remove the primary worktree (the repo root itself).
  if [[ "$worktree_path" == "$repo_root" ]]; then
    echo "error: branch '$branch' is checked out in the primary worktree at $repo_root" >&2
    echo "       switch that worktree to main before running this script" >&2
    exit 2
  fi
  echo "==> Removing worktree at $worktree_path"
  git worktree remove --force "$worktree_path"
else
  echo "==> No worktree holds branch '$branch' (skipping worktree remove)"
  # Prune any stale administrative entries (worktree dir deleted manually, etc.)
  git worktree prune
fi

# --- Delete local branch ----------------------------------------------------
if git show-ref --verify --quiet "refs/heads/$branch"; then
  echo "==> Deleting local branch '$branch'"
  git branch -D "$branch"
else
  echo "==> No local branch '$branch' (skipping branch delete)"
fi

# --- Verify -----------------------------------------------------------------
if git show-ref --verify --quiet "refs/heads/$branch"; then
  echo "error: branch '$branch' still exists after delete" >&2
  exit 1
fi
if [[ -n "$worktree_path" && -e "$worktree_path" ]]; then
  echo "error: worktree path '$worktree_path' still exists after remove" >&2
  exit 1
fi

echo "==> Clean. branch='$branch'${worktree_path:+, worktree='$worktree_path'}"
