#!/usr/bin/env python3
"""validate_index_to_passive_rename.py — PR-1e validator.

Read-only checks that confirm the `index → passive` fund_strategy rename
landed cleanly across:

  - fund_universe (no 'index' rows; passive rows = pre-state index count;
    fund_strategy == fund_category; passive never flagged active)
  - fund_holdings_v2 (no 'index' rows; passive count matches pre-state)
  - peer_rotation_flows (no fund-level 'index' rows; passive rows > 0;
    parent-level 'passive' rows untouched)
  - scripts/queries + scripts/pipeline (no remaining `'index'` literal as
    a fund_strategy value, allowing INDEX_PATTERNS, comments, tests)

Optional smoke test against a running Flask app on http://127.0.0.1:5050
(set HOST/PORT via env). Smoke test is skipped if the host is not reachable.

Exit code 0 when all checks pass, 1 otherwise.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "13f.duckdb"

# Pre-rename baseline counts captured during PR-1e Phase 1.
PRE_INDEX_FUND_UNIVERSE = 1264
PRE_INDEX_FUND_HOLDINGS = 3055575
PRE_PARENT_PASSIVE = 268988
PRE_FUND_INDEX_FLOWS = 1499478


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def run_db_checks(con) -> bool:
    all_ok = True

    section("fund_universe")
    n_index = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy = 'index'"
    ).fetchone()[0]
    all_ok &= check("no 'index' rows", n_index == 0, f"observed={n_index}")

    n_passive = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy = 'passive'"
    ).fetchone()[0]
    all_ok &= check(
        "passive count matches pre-state index count",
        n_passive == PRE_INDEX_FUND_UNIVERSE,
        f"observed={n_passive} expected={PRE_INDEX_FUND_UNIVERSE}",
    )

    n_passive_active = con.execute(
        "SELECT COUNT(*) FROM fund_universe "
        "WHERE fund_strategy = 'passive' AND is_actively_managed = TRUE"
    ).fetchone()[0]
    all_ok &= check(
        "passive funds never flagged actively managed",
        n_passive_active == 0,
        f"observed={n_passive_active}",
    )

    n_strat_cat_drift = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy != fund_category"
    ).fetchone()[0]
    all_ok &= check(
        "fund_strategy == fund_category for all rows",
        n_strat_cat_drift == 0,
        f"observed={n_strat_cat_drift}",
    )

    section("fund_holdings_v2")
    n_index = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE fund_strategy = 'index'"
    ).fetchone()[0]
    all_ok &= check("no 'index' rows", n_index == 0, f"observed={n_index}")

    n_passive = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE fund_strategy = 'passive'"
    ).fetchone()[0]
    all_ok &= check(
        "passive count matches pre-state index count",
        n_passive == PRE_INDEX_FUND_HOLDINGS,
        f"observed={n_passive} expected={PRE_INDEX_FUND_HOLDINGS}",
    )

    section("peer_rotation_flows")
    n_fund_index = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level = 'fund' AND entity_type = 'index'"
    ).fetchone()[0]
    all_ok &= check(
        "no fund-level 'index' rows", n_fund_index == 0, f"observed={n_fund_index}"
    )

    n_fund_passive = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level = 'fund' AND entity_type = 'passive'"
    ).fetchone()[0]
    all_ok &= check(
        "fund-level 'passive' rows > 0", n_fund_passive > 0, f"observed={n_fund_passive}"
    )

    n_parent_passive = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level = 'parent' AND entity_type = 'passive'"
    ).fetchone()[0]
    all_ok &= check(
        "parent-level 'passive' rows untouched",
        n_parent_passive == PRE_PARENT_PASSIVE,
        f"observed={n_parent_passive} expected={PRE_PARENT_PASSIVE}",
    )

    return all_ok


def run_code_checks() -> bool:
    section("source — no 'index' fund_strategy literal in queries/pipeline")
    targets = [REPO_ROOT / "scripts" / "queries", REPO_ROOT / "scripts" / "pipeline"]
    pattern = re.compile(r"['\"]index['\"]")
    suspicious: list[str] = []
    for root in targets:
        for path in root.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                # Allow well-known non-value usages.
                if "INDEX_PATTERNS" in line:
                    continue
                if "index_score" in line:
                    continue
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "isin" in line.lower():
                    continue
                suspicious.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{line.strip()}")

    ok = not suspicious
    detail = ""
    if suspicious:
        detail = "first hits: " + " | ".join(suspicious[:3])
    return check(
        "no fund_strategy='index' literal in scripts/queries or scripts/pipeline",
        ok,
        detail,
    )


def run_smoke_test() -> bool | None:
    """Optional Flask smoke test. Returns None if Flask is not reachable."""
    section("smoke test (optional Flask endpoints)")
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = os.environ.get("FLASK_PORT", "5050")
    base = f"http://{host}:{port}"

    endpoints = [
        ("/api/v1/portfolio_context?ticker=AAPL&level=fund", "fund"),
        ("/api/v1/cross_ownership?tickers=AAPL&level=fund", "fund"),
        ("/api/v1/holder_momentum?ticker=AAPL&level=parent", "parent"),
    ]

    # Probe first
    try:
        urllib.request.urlopen(f"{base}/api/v1/portfolio_context?ticker=AAPL&level=fund", timeout=2)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  [SKIP] Flask not reachable at {base} ({e}); smoke test skipped")
        return None

    all_ok = True
    saw_passive_label = False
    for path, level in endpoints:
        url = f"{base}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                body = r.read().decode("utf-8", errors="replace")
        except Exception as e:
            all_ok &= check(f"GET {path}", False, str(e))
            continue
        all_ok &= check(f"GET {path}", True, f"{len(body)} bytes")
        if level == "fund" and ('"type":"passive"' in body or '"type": "passive"' in body):
            saw_passive_label = True

    all_ok &= check(
        "fund-level response carries type='passive'",
        saw_passive_label,
        "" if saw_passive_label else "no 'passive' type label observed across fund endpoints",
    )
    return all_ok


def main() -> int:
    print(f"DB: {DB_PATH}")
    if not DB_PATH.exists():
        print("ERROR: database file missing", file=sys.stderr)
        return 1

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_ok = run_db_checks(con)
    finally:
        con.close()

    code_ok = run_code_checks()
    smoke = run_smoke_test()

    section("summary")
    overall = db_ok and code_ok and (smoke is not False)
    print(f"  db_checks    : {'PASS' if db_ok else 'FAIL'}")
    print(f"  code_checks  : {'PASS' if code_ok else 'FAIL'}")
    if smoke is None:
        print("  smoke_test   : SKIPPED (Flask not running)")
    else:
        print(f"  smoke_test   : {'PASS' if smoke else 'FAIL'}")
    print(f"  overall      : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
