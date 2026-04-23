#!/usr/bin/env bash
# scripts/bootstrap_worktree.sh
#
# Symlink gitignored DB files from the primary worktree into a secondary git
# worktree. Safe to re-run; no-op when invoked from the primary worktree.
#
# Why this exists. Fresh git worktrees do not receive gitignored files such
# as data/13f.duckdb (16 GB), data/admin.duckdb, or data/13f_staging.duckdb.
# Without them, scripts run from the worktree fail on missing paths, and the
# natural workaround — cd into the primary repo path to run scripts — has
# caused repeated file-edit leaks: Edit/Write tool calls end up using
# absolute paths rooted at the primary worktree and land on main's working
# tree instead of the session's feature branch.
#
# Running this script once per new worktree removes the incentive to cd out.
# Scripts then run correctly from the worktree and all file edits stay on
# the worktree's branch tree.
#
# Usage (from any worktree root):
#     ./scripts/bootstrap_worktree.sh
#
# Idempotent: existing symlinks are left in place; real files/dirs that
# already exist in the worktree are never overwritten.

set -euo pipefail

GIT_COMMON_DIR_RAW="$(git rev-parse --git-common-dir)"
GIT_DIR_RAW="$(git rev-parse --git-dir)"

# Absolutize. --git-common-dir can return a relative path.
if [[ "$GIT_COMMON_DIR_RAW" = /* ]]; then
    GIT_COMMON_DIR="$GIT_COMMON_DIR_RAW"
else
    GIT_COMMON_DIR="$(cd "$GIT_COMMON_DIR_RAW" && pwd)"
fi

if [[ "$GIT_DIR_RAW" = /* ]]; then
    GIT_DIR="$GIT_DIR_RAW"
else
    GIT_DIR="$(cd "$GIT_DIR_RAW" && pwd)"
fi

PRIMARY_ROOT="$(dirname "$GIT_COMMON_DIR")"
WORKTREE_ROOT="$(git rev-parse --show-toplevel)"

if [ "$GIT_DIR" = "$GIT_COMMON_DIR" ] || [ "$WORKTREE_ROOT" = "$PRIMARY_ROOT" ]; then
    echo "bootstrap_worktree: in primary worktree ($WORKTREE_ROOT) — nothing to do."
    exit 0
fi

echo "bootstrap_worktree: primary  = $PRIMARY_ROOT"
echo "bootstrap_worktree: worktree = $WORKTREE_ROOT"

linked=0
skipped=0
missing=0

link_path() {
    local rel="$1"
    local src="$PRIMARY_ROOT/$rel"
    local dst="$WORKTREE_ROOT/$rel"

    if [ ! -e "$src" ] && [ ! -L "$src" ]; then
        missing=$((missing + 1))
        return 0
    fi

    if [ -L "$dst" ]; then
        skipped=$((skipped + 1))
        return 0
    fi

    if [ -e "$dst" ]; then
        echo "  SKIP $rel (real file/dir exists in worktree; not overwriting)"
        skipped=$((skipped + 1))
        return 0
    fi

    mkdir -p "$(dirname "$dst")"
    ln -s "$src" "$dst"
    echo "  LINK $rel"
    linked=$((linked + 1))
}

# Gitignored DB files. Scope is deliberately narrow: the cd-to-main habit
# that drives the file-leak pattern is almost always "the scripts need a DB
# that is not in the worktree." Symlinking the DBs removes that incentive.
#
# We do NOT symlink data/raw, data/extracted, data/nport_raw, data/cache,
# outputs/, logs/ etc. Directory symlinks surface in `git status` because
# .gitignore's trailing-slash directory patterns do not match symlinks.
# Fetch pipelines that populate those trees run in cron contexts from the
# primary worktree, not from Code sessions in worktrees.
link_path "data/13f.duckdb"
link_path "data/13f.duckdb.wal"
link_path "data/admin.duckdb"
link_path "data/admin.duckdb.wal"
link_path "data/13f_staging.duckdb"
link_path "data/13f_readonly.duckdb"

echo "bootstrap_worktree: linked=$linked  skipped=$skipped  absent-in-primary=$missing"
