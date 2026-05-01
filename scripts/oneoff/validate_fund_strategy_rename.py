"""Validate PR-4 — fund-strategy-rename.

Checks:
  1. Value rename — `equity` is gone from `fund_universe`, `fund_holdings_v2`,
     and `peer_rotation_flows` (level='fund'); `active` is present.
  2. Column rename — `fund_holdings_v2.fund_strategy` no longer exists;
     `fund_holdings_v2.fund_strategy_at_filing` does. Row count preserved.
  3. Constants — ``ACTIVE_FUND_STRATEGIES == ('active','balanced','multi_asset')``.
  4. Pipeline lock — pytest tests still pass.
  5. JOIN architectural fix — `compute_peer_rotation.py` no longer reads
     fund_strategy from fund_holdings_v2 directly; reads from fund_universe.
  6. Source-code grep — no active read of legacy `'equity'` value or
     `fund_holdings_v2.fund_strategy[^_]` column reference.
  7. Optional smoke test against the FastAPI surface (set
     ``$PR4_SMOKE_BASE_URL`` to enable; defaults to ``http://localhost:8001``;
     skipped when unreachable).

Exit code 0 when all checks pass, 1 otherwise.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_db_path() -> Path:
    env = os.environ.get("PR4_VALIDATOR_DB")
    if env:
        return Path(env)
    primary = REPO_ROOT / "data" / "13f.duckdb"
    if primary.exists():
        return primary
    parts = REPO_ROOT.parts
    if ".claude" in parts:
        idx = parts.index(".claude")
        parent_repo = Path(*parts[:idx])
        candidate = parent_repo / "data" / "13f.duckdb"
        if candidate.exists():
            return candidate
    return primary


DB_PATH = _resolve_db_path()
SMOKE_BASE = os.environ.get("PR4_SMOKE_BASE_URL", "http://localhost:8001")

# Pre-rename baselines (captured 2026-05-01 just before Phase 2/Phase 10).
PRE_FUND_HOLDINGS_V2_ROWS = 14_568_775
PRE_PEER_ROTATION_FUND_ROWS = 5_065_200
PRE_PEER_ROTATION_TOTAL_ROWS = 17_490_106


def _print_section(title: str) -> None:
    print()
    print(f"=== {title} ===")


def check_value_rename(con: duckdb.DuckDBPyConnection) -> list[str]:
    fails = []
    _print_section("value rename — equity → active")
    fu_eq = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy = 'equity'"
    ).fetchone()[0]
    fu_act = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy = 'active'"
    ).fetchone()[0]
    fh_eq = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE fund_strategy_at_filing = 'equity'"
    ).fetchone()[0]
    fh_act = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE fund_strategy_at_filing = 'active'"
    ).fetchone()[0]
    pr_eq = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level='fund' AND entity_type='equity'"
    ).fetchone()[0]
    pr_act = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level='fund' AND entity_type='active'"
    ).fetchone()[0]

    for label, expect, observed in [
        ("fund_universe.fund_strategy='equity'", 0, fu_eq),
        ("fund_universe.fund_strategy='active' (>0)", "positive", fu_act),
        ("fund_holdings_v2.fund_strategy_at_filing='equity'", 0, fh_eq),
        ("fund_holdings_v2.fund_strategy_at_filing='active' (>0)", "positive", fh_act),
        ("peer_rotation_flows fund equity", 0, pr_eq),
        ("peer_rotation_flows fund active (>0)", "positive", pr_act),
    ]:
        ok = (
            (expect == 0 and observed == 0)
            or (expect == "positive" and observed > 0)
        )
        status = "PASS" if ok else "FAIL"
        if not ok:
            fails.append(label)
        print(f"  [{status}] {label} — observed={observed}")
    return fails


def check_column_rename(con: duckdb.DuckDBPyConnection) -> list[str]:
    fails = []
    _print_section("column rename — fund_strategy → fund_strategy_at_filing")
    cols = {
        c[1]
        for c in con.execute(
            "PRAGMA table_info(fund_holdings_v2)"
        ).fetchall()
    }
    if "fund_strategy" in cols:
        fails.append("old column fund_strategy still present")
        print(f"  [FAIL] fund_strategy column should be gone")
    else:
        print(f"  [PASS] fund_strategy column dropped")
    if "fund_strategy_at_filing" not in cols:
        fails.append("new column fund_strategy_at_filing missing")
        print(f"  [FAIL] fund_strategy_at_filing column missing")
    else:
        print(f"  [PASS] fund_strategy_at_filing column present")

    rows = con.execute("SELECT COUNT(*) FROM fund_holdings_v2").fetchone()[0]
    if rows != PRE_FUND_HOLDINGS_V2_ROWS:
        fails.append(
            f"row count drift: expected={PRE_FUND_HOLDINGS_V2_ROWS:,} "
            f"observed={rows:,}"
        )
        print(
            f"  [FAIL] row count expected={PRE_FUND_HOLDINGS_V2_ROWS:,} "
            f"observed={rows:,}"
        )
    else:
        print(f"  [PASS] row count preserved — {rows:,}")

    pr_total = con.execute("SELECT COUNT(*) FROM peer_rotation_flows").fetchone()[0]
    if pr_total != PRE_PEER_ROTATION_TOTAL_ROWS:
        fails.append(
            f"peer_rotation_flows total drift: expected="
            f"{PRE_PEER_ROTATION_TOTAL_ROWS:,} observed={pr_total:,}"
        )
        print(
            f"  [FAIL] peer_rotation_flows total expected="
            f"{PRE_PEER_ROTATION_TOTAL_ROWS:,} observed={pr_total:,}"
        )
    else:
        print(f"  [PASS] peer_rotation_flows total preserved — {pr_total:,}")
    return fails


def check_constants() -> list[str]:
    fails = []
    _print_section("constants — ACTIVE_FUND_STRATEGIES")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from queries.common import (  # noqa: E402  pylint: disable=import-outside-toplevel
        ACTIVE_FUND_STRATEGIES,
        PASSIVE_FUND_STRATEGIES,
    )

    expected = ("active", "balanced", "multi_asset")
    if ACTIVE_FUND_STRATEGIES == expected:
        print(f"  [PASS] ACTIVE_FUND_STRATEGIES == {expected}")
    else:
        fails.append(f"ACTIVE_FUND_STRATEGIES != {expected}")
        print(
            f"  [FAIL] ACTIVE_FUND_STRATEGIES expected={expected} "
            f"observed={ACTIVE_FUND_STRATEGIES}"
        )

    canonical = {
        "active",
        "balanced",
        "multi_asset",
        "passive",
        "bond_or_other",
        "excluded",
        "final_filing",
    }
    if set(ACTIVE_FUND_STRATEGIES).union(set(PASSIVE_FUND_STRATEGIES)) == canonical:
        print("  [PASS] active ∪ passive covers all 7 canonical values")
    else:
        fails.append("partition does not cover canonical 7-value set")
        print("  [FAIL] partition gap or extra value")
    return fails


def check_lock_tests() -> list[str]:
    fails = []
    _print_section("pipeline lock — unit tests")
    res = subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "tests/test_queries_common.py",
            "tests/pipeline/test_load_nport.py",
            "-q",
            "--no-header",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (res.stdout + res.stderr).strip().splitlines()
    summary = next((line for line in reversed(out) if "passed" in line or "failed" in line), "")
    if res.returncode == 0:
        print(f"  [PASS] {summary}")
    else:
        fails.append("pytest lock tests failed")
        print(f"  [FAIL] {summary}")
        print("\n".join(out[-15:]))
    return fails


def check_join_fix() -> list[str]:
    fails = []
    _print_section("JOIN architectural fix — compute_peer_rotation.py")
    src = (REPO_ROOT / "scripts/pipeline/compute_peer_rotation.py").read_text()
    if "JOIN " not in src.split("CREATE TEMP TABLE f_agg_pair", 1)[1].split(")", 1)[0]:
        # The CTAS body should contain the JOIN
        pass
    # Check the f_agg_pair body explicitly references fund_universe.
    fund_agg_block = src.split("def _materialize_fund_agg", 1)[1].split("def _insert_parent_flows", 1)[0]
    if "fund_universe" not in fund_agg_block:
        fails.append("compute_peer_rotation.py f_agg_pair does not JOIN fund_universe")
        print("  [FAIL] _materialize_fund_agg does not reference fund_universe")
    else:
        print("  [PASS] _materialize_fund_agg JOINs fund_universe")
    if "MAX(fund_strategy)" in fund_agg_block:
        fails.append(
            "compute_peer_rotation.py still aggregates fund_strategy from holdings"
        )
        print("  [FAIL] still uses MAX(fund_strategy) from holdings layer")
    else:
        print("  [PASS] no MAX(fund_strategy) read from holdings layer")
    return fails


def check_source_grep() -> list[str]:
    fails = []
    _print_section("source grep — legacy strings")
    scripts = REPO_ROOT / "scripts"
    excludes = ("oneoff", "retired")

    # 1) literal value 'equity' as fund_strategy in active code
    for path in scripts.rglob("*.py"):
        if any(part in path.parts for part in excludes):
            continue
        text = path.read_text()
        for m in re.finditer(r"fund_strategy\s*[=!]?=\s*'equity'", text):
            fails.append(f"{path}: literal fund_strategy = 'equity' at offset {m.start()}")
            print(f"  [FAIL] {path}: {m.group(0)!r}")
    # 2) literal column reference fund_holdings_v2.fund_strategy without _at_filing
    for path in scripts.rglob("*.py"):
        if any(part in path.parts for part in excludes):
            continue
        text = path.read_text()
        for m in re.finditer(r"fund_holdings_v2\.fund_strategy(?!_at_filing|`)", text):
            fails.append(
                f"{path}: literal fund_holdings_v2.fund_strategy at offset {m.start()}"
            )
            print(f"  [FAIL] {path}: literal fund_holdings_v2.fund_strategy")

    if not fails:
        print("  [PASS] no active code references to legacy 'equity' value")
        print("  [PASS] no active code references to fund_holdings_v2.fund_strategy")
    return fails


SMOKE_ENDPOINTS = [
    "/api/v1/portfolio_context?ticker=AAPL&level=fund",
    "/api/v1/cross_ownership?tickers=AAPL&level=fund",
    "/api/v1/holder_momentum?ticker=AAPL&level=fund",
    "/api/v1/cohort_analysis?ticker=AAPL&active_only=true",
    "/api/v1/ownership_trend_summary?ticker=AAPL",
    "/api/v1/peer_rotation?ticker=AAPL&level=fund",
    "/api/v1/short_analysis?ticker=AAPL",
]


def check_smoke() -> list[str]:
    fails = []
    _print_section("smoke test — affected endpoints")
    try:
        # Reachability probe via the trend-summary endpoint.
        urllib.request.urlopen(
            SMOKE_BASE + "/api/v1/ownership_trend_summary?ticker=AAPL",
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [SKIP] {SMOKE_BASE} unreachable ({exc})")
        return fails
    for ep in SMOKE_ENDPOINTS:
        url = SMOKE_BASE + ep
        try:
            with urllib.request.urlopen(url, timeout=15.0) as resp:
                body = resp.read()
                status = resp.status
            if status == 200:
                print(f"  [PASS] {ep} status={status} bytes={len(body)}")
            else:
                fails.append(f"{ep} status={status}")
                print(f"  [FAIL] {ep} status={status}")
        except urllib.error.HTTPError as exc:
            fails.append(f"{ep} {exc}")
            print(f"  [FAIL] {ep} {exc}")
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{ep} {exc}")
            print(f"  [FAIL] {ep} {exc}")
    return fails


def main() -> int:
    print(f"DB path: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"FATAL: {DB_PATH} does not exist")
        return 1
    con = duckdb.connect(str(DB_PATH), read_only=True)
    fails: list[str] = []
    fails += check_value_rename(con)
    fails += check_column_rename(con)
    fails += check_constants()
    fails += check_lock_tests()
    fails += check_join_fix()
    fails += check_source_grep()
    fails += check_smoke()
    _print_section("summary")
    if fails:
        for f in fails:
            print(f"  [FAIL] {f}")
        print("  overall        : FAIL")
        return 1
    print("  overall        : PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
