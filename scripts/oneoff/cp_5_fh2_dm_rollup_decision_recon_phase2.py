"""CP-5 fh2.dm_rollup decision recon — Phase 2.

Read-only investigation. Inventories every reader/writer/reference of
fund_holdings_v2.dm_rollup_entity_id and dm_rollup_name across
scripts/, web/, and tests/. Classifies each hit by role
(WRITER / READER_DIRECT / READER_FILTER / READER_GROUP / READER_JOIN
/ TEST / REFERENCE_DOC) and code-path (PRODUCTION / INVESTIGATION
/ MIGRATION / TEST).

Outputs:
  data/working/cp-5-fh2-dm-rollup-readers.csv

Refs:
  scripts/oneoff/cp_5_bundle_c_probe7_4_readers_writers.py (prior pattern)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
WORKDIR = REPO / "data" / "working"

PATTERNS = [
    "dm_rollup_entity_id",
    "dm_rollup_name",
]

# Skip categories — investigations + caches
SKIP_DIRS = ("/__pycache__/", "/retired/")


def grep(pat: str, root: Path) -> list[tuple[str, int, str]]:
    try:
        out = subprocess.check_output(
            ["grep", "-rn", "--include=*.py", "--include=*.ts",
             "--include=*.tsx", "--include=*.sql", pat, str(root)],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    rows = []
    for line in out.splitlines():
        m = re.match(r"^([^:]+):(\d+):(.*)$", line)
        if m:
            f, ln, txt = m.group(1), int(m.group(2)), m.group(3)
            if any(skip in f for skip in SKIP_DIRS):
                continue
            rows.append((f, ln, txt))
    return rows


def classify_role(text: str) -> str:
    """Categorize a hit by its SQL role."""
    t = text.upper()
    if re.search(r"\bUPDATE\s+FUND_HOLDINGS_V2\b", t) or "SET DM_ROLLUP" in t:
        return "WRITER_UPDATE"
    if re.search(r"\bINSERT\s+INTO\s+FUND_HOLDINGS_V2\b", t):
        return "WRITER_INSERT"
    if re.search(r"\bSET\s+DM_ROLLUP|DM_ROLLUP_ENTITY_ID\s*=|DM_ROLLUP_NAME\s*=", t):
        # Likely SET clause inside UPDATE
        return "WRITER_SET"
    if re.search(r"\bWHERE\b.*DM_ROLLUP|\bAND\b.*DM_ROLLUP|\bOR\b.*DM_ROLLUP", t):
        return "READER_FILTER"
    if "GROUP BY" in t and "DM_ROLLUP" in t:
        return "READER_GROUP"
    if re.search(r"\bJOIN\b.*DM_ROLLUP|\bON\b.*DM_ROLLUP", t):
        return "READER_JOIN"
    if re.search(r"DM_ROLLUP_ENTITY_ID|DM_ROLLUP_NAME", t):
        # Default — probably SELECT or column reference
        return "READER_DIRECT"
    return "OTHER"


def classify_code_path(file_path: str) -> str:
    """Categorize a file by code-path purpose."""
    if "/oneoff/" in file_path:
        return "INVESTIGATION"
    if "/migrations/" in file_path:
        return "MIGRATION"
    if "/tests/" in file_path:
        return "TEST"
    if "/web/" in file_path:
        return "PRODUCTION_FRONTEND"
    if "/queries/" in file_path or "/queries_helpers" in file_path:
        return "PRODUCTION_QUERY"
    if "/pipeline/" in file_path or "/api_" in file_path or "/app.py" in file_path:
        return "PRODUCTION_BACKEND"
    if "/scripts/" in file_path:
        return "PRODUCTION_SCRIPT"
    return "UNKNOWN"


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)

    all_hits: list[dict] = []
    for pat in PATTERNS:
        for root_dir in ("scripts", "web", "tests"):
            for f, ln, txt in grep(pat, REPO / root_dir):
                rel = f.replace(str(REPO) + "/", "")
                all_hits.append({
                    "pattern": pat,
                    "file": rel,
                    "line": ln,
                    "text": txt.strip()[:200],
                    "role": classify_role(txt),
                    "code_path": classify_code_path(f),
                })

    df = pd.DataFrame(all_hits)
    # Dedupe — both pattern matches on same line
    df = df.drop_duplicates(subset=["file", "line"]).sort_values(["file", "line"])

    out_path = WORKDIR / "cp-5-fh2-dm-rollup-readers.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path} ({len(df)} hits)")

    print()
    print("=" * 78)
    print("Hits by code_path:")
    print("=" * 78)
    print(df.groupby("code_path").size().to_string())

    print()
    print("=" * 78)
    print("Hits by role:")
    print("=" * 78)
    print(df.groupby("role").size().to_string())

    print()
    print("=" * 78)
    print("PRODUCTION readers (excluding INVESTIGATION/TEST/MIGRATION):")
    print("=" * 78)
    prod = df[df["code_path"].str.startswith("PRODUCTION")]
    print(prod.groupby(["code_path", "file"]).size().to_string())

    print()
    print("=" * 78)
    print("PRODUCTION reader hits per file (file:line text):")
    print("=" * 78)
    for _, r in prod.iterrows():
        print(f"  [{r['role']:<14} | {r['code_path']:<22}] {r['file']}:{r['line']}")
        print(f"      {r['text'][:150]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
