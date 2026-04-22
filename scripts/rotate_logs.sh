#!/usr/bin/env bash
# rotate_logs.sh — apply the standard log-retention policy to logs/.
#
# Policy:
#   - Files older than  7 days  : compressed with gzip (unless already .gz).
#   - Files older than 90 days  : deleted (whether or not compressed).
#
# Usage:
#   scripts/rotate_logs.sh              # apply
#   scripts/rotate_logs.sh --dry-run    # print actions without executing
#
# The script is idempotent and restart-safe. All paths are resolved
# relative to the repository root (the directory containing this script's
# parent). Non-regular files and symlinks are ignored.

set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY_RUN=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${REPO_ROOT}/logs"

COMPRESS_AGE_DAYS=7
DELETE_AGE_DAYS=90

if [[ ! -d "${LOG_DIR}" ]]; then
  echo "rotate_logs: no logs directory at ${LOG_DIR} — nothing to do."
  exit 0
fi

prefix() {
  if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "[DRY RUN]"
  else
    echo "[ROTATE]"
  fi
}

echo "=== rotate_logs: ${LOG_DIR} ==="
echo "Policy: compress >${COMPRESS_AGE_DAYS}d, delete >${DELETE_AGE_DAYS}d. Dry-run: ${DRY_RUN}."

# Step 1: delete anything older than DELETE_AGE_DAYS (runs first so we
# never waste cycles compressing a file we're about to delete).
deleted=0
while IFS= read -r -d '' f; do
  echo "$(prefix) delete ${f}"
  if [[ ${DRY_RUN} -eq 0 ]]; then
    rm -f "${f}"
  fi
  deleted=$((deleted + 1))
done < <(find "${LOG_DIR}" -maxdepth 1 -type f -mtime +${DELETE_AGE_DAYS} -print0)

# Step 2: compress uncompressed files older than COMPRESS_AGE_DAYS.
# Skip .gz files and zero-byte files (gzip'ing empties is pointless).
compressed=0
while IFS= read -r -d '' f; do
  case "${f}" in
    *.gz) continue ;;
  esac
  if [[ ! -s "${f}" ]]; then
    continue
  fi
  echo "$(prefix) gzip ${f}"
  if [[ ${DRY_RUN} -eq 0 ]]; then
    gzip -q "${f}"
  fi
  compressed=$((compressed + 1))
done < <(find "${LOG_DIR}" -maxdepth 1 -type f -mtime +${COMPRESS_AGE_DAYS} -print0)

total_files=$(find "${LOG_DIR}" -maxdepth 1 -type f | wc -l | tr -d ' ')
dir_size=$(du -sh "${LOG_DIR}" | cut -f1)

echo "=== rotate_logs summary ==="
echo "  deleted    : ${deleted} file(s)"
echo "  compressed : ${compressed} file(s)"
echo "  remaining  : ${total_files} file(s), ${dir_size} total"
