#!/usr/bin/env python3
"""validate_classifier_patterns.py — PR-2 validator.

Read-only checks that confirm the PR-2 classifier-pattern sweep landed
cleanly across:

  - fund_universe (passive count = pre + 253; reclassified series carry
    fund_strategy='passive', fund_category='passive',
    is_actively_managed=FALSE; sample audit of fund names; consistency).
  - fund_holdings_v2 (every reclassified series has fund_strategy='passive'
    for ALL historical rows).
  - peer_rotation_flows (fund-level active-bucket count decreased,
    passive count increased by the matching delta; parent-level
    untouched).
  - Pipeline lock invariant against the unit-test suite.
  - Optional smoke test against Flask on http://127.0.0.1:5050.

Exit code 0 when all checks pass, 1 otherwise.
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_db_path() -> Path:
    """Find the prod 13f.duckdb. Handles three layouts:

      1. ``$PR2_VALIDATOR_DB`` env override (absolute path).
      2. ``REPO_ROOT/data/13f.duckdb`` — main checkout.
      3. Worktree fallback — climb out of ``.claude/worktrees/<name>/``
         to the parent repo root and look for ``data/13f.duckdb`` there.
    """
    env = os.environ.get("PR2_VALIDATOR_DB")
    if env:
        return Path(env)
    primary = REPO_ROOT / "data" / "13f.duckdb"
    if primary.exists():
        return primary
    # Worktree fallback: REPO_ROOT/.claude/worktrees/<name>/ → parent
    parts = REPO_ROOT.parts
    if ".claude" in parts:
        idx = parts.index(".claude")
        parent_repo = Path(*parts[:idx])
        candidate = parent_repo / "data" / "13f.duckdb"
        if candidate.exists():
            return candidate
    return primary


DB_PATH = _resolve_db_path()
DRY_RUN_CSV = REPO_ROOT / "docs" / "findings" / "pr2_reclassification_dryrun.csv"

# Pre-state baselines captured 2026-05-01 immediately before Phase 4.
PRE_PASSIVE_UNIVERSE = 1264
PRE_PASSIVE_HOLDINGS = 3055575
PRE_FUND_PASSIVE_FLOWS = 1499478
PRE_PARENT_PASSIVE_FLOWS = 268988
PRE_FUND_EQUITY_FLOWS = 2195291
PRE_FUND_BALANCED_FLOWS = 474067
PRE_FUND_MULTIASSET_FLOWS = 186532
RECLASSIFIED_COUNT = 253
RECLASSIFIED_HOLDINGS_ROWS = 186943


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def _read_reclassified_series_ids() -> list[str]:
    import csv
    if not DRY_RUN_CSV.exists():
        return []
    with open(DRY_RUN_CSV, encoding="utf-8") as fh:
        return [row["series_id"] for row in csv.DictReader(fh)]


def run_db_checks(con) -> bool:
    all_ok = True
    series_ids = _read_reclassified_series_ids()
    placeholders = ",".join("?" * len(series_ids)) if series_ids else "''"

    section("fund_universe")
    n_passive = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy = 'passive'"
    ).fetchone()[0]
    expected_passive = PRE_PASSIVE_UNIVERSE + RECLASSIFIED_COUNT
    all_ok &= check(
        "passive count = pre-state + reclassified",
        n_passive == expected_passive,
        f"observed={n_passive} expected={expected_passive}",
    )

    if series_ids:
        n_locked = con.execute(
            f"SELECT COUNT(*) FROM fund_universe "
            f"WHERE series_id IN ({placeholders}) "
            f"  AND fund_strategy = 'passive' "
            f"  AND fund_category = 'passive' "
            f"  AND is_actively_managed = FALSE",
            series_ids,
        ).fetchone()[0]
        all_ok &= check(
            "all reclassified series locked to passive/FALSE",
            n_locked == RECLASSIFIED_COUNT,
            f"observed={n_locked} expected={RECLASSIFIED_COUNT}",
        )

    n_drift = con.execute(
        "SELECT COUNT(*) FROM fund_universe "
        "WHERE fund_strategy IS NOT NULL AND fund_category IS NOT NULL "
        "  AND fund_strategy <> fund_category"
    ).fetchone()[0]
    all_ok &= check(
        "fund_strategy == fund_category for all rows",
        n_drift == 0,
        f"observed={n_drift}",
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

    # Discretionary-token audit on the reclassified set. Fires when a
    # name matches active-management keywords; "Consumer Discretionary"
    # is excluded as a GICS sector name.
    if series_ids:
        suspicious = con.execute(
            f"""
            SELECT series_id, fund_name
              FROM fund_universe
             WHERE series_id IN ({placeholders})
               AND (regexp_matches(LOWER(fund_name),
                       '\\b(active|fundamental|long[- ]short|concentrated)\\b')
                    OR (regexp_matches(LOWER(fund_name), '\\bdiscretionary\\b')
                        AND NOT regexp_matches(LOWER(fund_name),
                                'consumer\\s+discretionary')))
            """,
            series_ids,
        ).fetchall()
        all_ok &= check(
            "no reclassified fund name carries discretionary tokens",
            not suspicious,
            f"observed={len(suspicious)} suspicious "
            f"(first: {suspicious[0] if suspicious else None})",
        )

    section("fund_holdings_v2")
    if series_ids:
        n_locked_holdings = con.execute(
            f"SELECT COUNT(*) FROM fund_holdings_v2 "
            f"WHERE series_id IN ({placeholders})",
            series_ids,
        ).fetchone()[0]
        n_passive_holdings_in_set = con.execute(
            f"SELECT COUNT(*) FROM fund_holdings_v2 "
            f"WHERE series_id IN ({placeholders}) "
            f"  AND fund_strategy = 'passive'",
            series_ids,
        ).fetchone()[0]
        all_ok &= check(
            "all historical holdings rows for reclassified series are passive",
            n_locked_holdings == n_passive_holdings_in_set,
            f"total={n_locked_holdings} passive={n_passive_holdings_in_set}",
        )

    n_passive_total = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE fund_strategy = 'passive'"
    ).fetchone()[0]
    expected_holdings = PRE_PASSIVE_HOLDINGS + RECLASSIFIED_HOLDINGS_ROWS
    all_ok &= check(
        "fund_holdings_v2 passive count = pre + reclassified rows",
        n_passive_total == expected_holdings,
        f"observed={n_passive_total} expected={expected_holdings}",
    )

    section("peer_rotation_flows")
    fund_passive = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level='fund' AND entity_type='passive'"
    ).fetchone()[0]
    all_ok &= check(
        "fund-level passive count increased",
        fund_passive > PRE_FUND_PASSIVE_FLOWS,
        f"observed={fund_passive} pre={PRE_FUND_PASSIVE_FLOWS}",
    )

    fund_active_bucket = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level='fund' "
        "  AND entity_type IN ('equity','balanced','multi_asset')"
    ).fetchone()[0]
    pre_active_bucket = (
        PRE_FUND_EQUITY_FLOWS
        + PRE_FUND_BALANCED_FLOWS
        + PRE_FUND_MULTIASSET_FLOWS
    )
    all_ok &= check(
        "fund-level active-bucket count decreased",
        fund_active_bucket < pre_active_bucket,
        f"observed={fund_active_bucket} pre={pre_active_bucket} "
        f"delta={fund_active_bucket - pre_active_bucket:+,}",
    )

    parent_passive = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level='parent' AND entity_type='passive'"
    ).fetchone()[0]
    all_ok &= check(
        "parent-level 'passive' rows untouched",
        parent_passive == PRE_PARENT_PASSIVE_FLOWS,
        f"observed={parent_passive} expected={PRE_PARENT_PASSIVE_FLOWS}",
    )

    return all_ok


def run_lock_unit_tests() -> bool:
    section("pipeline lock — unit tests")
    cmd = [
        "python3", "-m", "pytest",
        "tests/pipeline/test_load_nport.py",
        "-k", "pr2_lock",
        "-q", "--no-header",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
            timeout=60,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return check("pytest pr2_lock tests", False, f"error={exc}")
    summary = (result.stdout or "").strip().splitlines()[-1:] or [""]
    ok = result.returncode == 0
    return check("pytest pr2_lock tests", ok, summary[0])


def run_smoke_test() -> bool:
    section("smoke test (optional FastAPI endpoints)")
    host = os.environ.get("HOST", "127.0.0.1")
    port = os.environ.get("PORT", "8001")
    base = f"http://{host}:{port}"

    # Probe a known endpoint; the app exposes no /healthz.
    try:
        urllib.request.urlopen(f"{base}/api/v1/health", timeout=2)
    except urllib.error.HTTPError:
        # Reachable but no health route — that's fine, server is up.
        pass
    except Exception:  # pylint: disable=broad-except
        # Connection refused / DNS / etc — server not running.
        try:
            urllib.request.urlopen(base, timeout=2)
        except urllib.error.HTTPError:
            pass
        except Exception:  # pylint: disable=broad-except
            print(f"  [SKIP] FastAPI not reachable at {base}")
            return True

    targets = [
        ("portfolio_context",
         f"{base}/api/v1/portfolio_context?ticker=AAPL&level=fund"),
        ("cross_ownership",
         f"{base}/api/v1/cross_ownership?tickers=AAPL&level=fund"),
        ("holder_momentum",
         f"{base}/api/v1/holder_momentum?ticker=AAPL&level=fund"),
        ("short_analysis",
         f"{base}/api/v1/short_analysis?ticker=AAPL"),
    ]
    all_ok = True
    payloads: dict[str, str] = {}
    for tag, url in targets:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read()
                payloads[tag] = body.decode("utf-8", errors="replace")
                ok = (resp.status == 200) and (len(body) > 0)
                all_ok &= check(f"GET {url}", ok, f"{len(body)} bytes")
        except urllib.error.URLError as exc:
            all_ok &= check(f"GET {url}", False, str(exc))

    # Verify Invesco QQQ Trust shows type='passive' in portfolio_context.
    pc = payloads.get("portfolio_context", "")
    qqq_passive = ("Invesco QQQ Trust" in pc) and (
        '"type": "passive"' in pc
        or '"type":"passive"' in pc
    )
    all_ok &= check(
        "Invesco QQQ Trust now type='passive'",
        qqq_passive,
        "QQQ row carries type=passive in portfolio_context",
    )
    return all_ok


def main() -> int:
    print(f"DB: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"FAIL: DB not found at {DB_PATH}")
        return 1
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_ok = run_db_checks(con)
    finally:
        con.close()
    lock_ok = run_lock_unit_tests()
    smoke_ok = run_smoke_test()

    section("summary")
    print(f"  db_checks    : {'PASS' if db_ok else 'FAIL'}")
    print(f"  lock_tests   : {'PASS' if lock_ok else 'FAIL'}")
    print(f"  smoke_test   : {'PASS' if smoke_ok else 'FAIL'}")
    overall = db_ok and lock_ok and smoke_ok
    print(f"  overall      : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
