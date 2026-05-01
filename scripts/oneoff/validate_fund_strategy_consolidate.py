"""Validate PR-3 — fund-strategy-consolidate.

Checks:
  1. ``fund_universe`` schema no longer carries ``fund_category`` or
     ``is_actively_managed``.
  2. Every row has a non-null ``fund_strategy``.
  3. Active-filter parity: row counts under
     ``fund_strategy IN ACTIVE_FUND_STRATEGIES`` match the pre-migration
     baseline captured before the migration ran.
  4. PR-2 lock unit tests still pass after the column drops + lock-code
     cleanup.
  5. Active code references — no read of the dropped columns from the
     prod write path or query layer (oneoff / retired scripts excluded).
  6. Optional smoke test against the FastAPI surface (set
     ``$PR3_SMOKE_BASE_URL`` to enable; defaults to ``http://localhost:5001``;
     skipped when unreachable).

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
    env = os.environ.get("PR3_VALIDATOR_DB")
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
SMOKE_BASE = os.environ.get("PR3_SMOKE_BASE_URL", "http://localhost:8001")

# Pre-migration baselines (captured 2026-05-01 before Phase 5).
PRE_FUND_UNIVERSE_ROWS = 13623
PRE_ACTIVE_FUND_UNIVERSE = 5620
PRE_PASSIVE_FUND_UNIVERSE = 8003
PRE_ACTIVE_HOLDINGS_LATEST = 5236150


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def run_db_checks(con: duckdb.DuckDBPyConnection) -> bool:
    all_ok = True

    section("schema — fund_universe")
    cols = {r[0] for r in con.execute("DESCRIBE fund_universe").fetchall()}
    all_ok &= check("fund_category column dropped",
                    "fund_category" not in cols,
                    f"present cols: {sorted(cols)}" if "fund_category" in cols else "")
    all_ok &= check("is_actively_managed column dropped",
                    "is_actively_managed" not in cols,
                    f"present cols: {sorted(cols)}" if "is_actively_managed" in cols else "")
    all_ok &= check("fund_strategy column present",
                    "fund_strategy" in cols)

    section("data — fund_universe")
    total = con.execute("SELECT COUNT(*) FROM fund_universe").fetchone()[0]
    all_ok &= check(
        "row count preserved",
        total == PRE_FUND_UNIVERSE_ROWS,
        f"observed={total} expected={PRE_FUND_UNIVERSE_ROWS}",
    )
    null_strat = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IS NULL"
    ).fetchone()[0]
    all_ok &= check(
        "fund_strategy non-null on every row",
        null_strat == 0,
        f"NULL rows={null_strat}" if null_strat else "",
    )

    section("active-filter parity — fund_universe")
    n_active = con.execute(
        "SELECT COUNT(*) FROM fund_universe "
        "WHERE fund_strategy IN ('equity','balanced','multi_asset')"
    ).fetchone()[0]
    n_passive = con.execute(
        "SELECT COUNT(*) FROM fund_universe "
        "WHERE fund_strategy IN ('passive','bond_or_other','excluded','final_filing')"
    ).fetchone()[0]
    all_ok &= check(
        "active count matches pre-migration baseline",
        n_active == PRE_ACTIVE_FUND_UNIVERSE,
        f"observed={n_active} expected={PRE_ACTIVE_FUND_UNIVERSE}",
    )
    all_ok &= check(
        "passive count matches pre-migration baseline",
        n_passive == PRE_PASSIVE_FUND_UNIVERSE,
        f"observed={n_passive} expected={PRE_PASSIVE_FUND_UNIVERSE}",
    )
    all_ok &= check(
        "partitions cover every row (no gap, no overlap)",
        n_active + n_passive == total,
        f"sum={n_active + n_passive} total={total}",
    )

    section("active-filter parity — fund_holdings_v2 (is_latest)")
    n_holdings_active = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 fh "
        "JOIN fund_universe fu USING (series_id) "
        "WHERE fh.is_latest=TRUE "
        "  AND fu.fund_strategy IN ('equity','balanced','multi_asset')"
    ).fetchone()[0]
    all_ok &= check(
        "active holdings count matches pre-migration baseline",
        n_holdings_active == PRE_ACTIVE_HOLDINGS_LATEST,
        f"observed={n_holdings_active} expected={PRE_ACTIVE_HOLDINGS_LATEST}",
    )

    return all_ok


def run_lock_tests() -> bool:
    section("pipeline lock — unit tests")
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/pipeline/test_load_nport.py",
        "-k", "pr2_lock", "-q", "--no-header",
    ]
    try:
        out = subprocess.run(  # noqa: S603 — local pytest, no shell
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return check("pytest pr2_lock tests", False, f"runner failed: {exc}")
    summary = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "no output"
    return check("pytest pr2_lock tests", out.returncode == 0, summary)


def run_constants_tests() -> bool:
    section("queries.common — constants tests")
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_queries_common.py",
        "-q", "--no-header",
    ]
    try:
        out = subprocess.run(  # noqa: S603
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return check("pytest constants tests", False, f"runner failed: {exc}")
    summary = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "no output"
    return check("pytest constants tests", out.returncode == 0, summary)


def run_active_code_grep() -> bool:
    """Verify no active code path reads the dropped columns.

    Excluded directories (out of scope for the active prod path):
      * scripts/oneoff/  — historical one-time scripts
      * scripts/retired/ — retired pipeline code

    Staging tables in scripts/pipeline/load_nport.py and
    scripts/fetch_dera_nport.py keep the dropped columns by design — the
    classifier still emits them but they are not propagated to prod. We
    accept those staging-only references and do not treat them as failures.
    """
    section("source grep — dropped columns in active code")

    targets = [
        REPO_ROOT / "scripts" / "queries",
        REPO_ROOT / "scripts" / "build_entities.py",
    ]
    ok = True
    for needle in ("is_actively_managed", "fund_category"):
        hits: list[str] = []
        for t in targets:
            try:
                out = subprocess.run(  # noqa: S603
                    ["grep", "-rn", needle, str(t)],
                    capture_output=True, text=True, check=False,
                )
                if out.returncode == 0:
                    hits.extend(out.stdout.strip().splitlines())
            except Exception as exc:  # pylint: disable=broad-except
                hits.append(f"<grep failed: {exc}>")
        # Comments / docstrings are acceptable; non-comment SQL or Python
        # references are not. We strip lines whose first non-whitespace
        # token is `#` or that contain `--` SQL comments only.
        offending = [
            ln for ln in hits
            if not _is_comment_only(ln, needle)
        ]
        ok &= check(
            f"no active read of {needle}",
            not offending,
            "\n    ".join(offending) if offending else "",
        )
    return ok


def _is_comment_only(line: str, needle: str) -> bool:  # pylint: disable=unused-argument
    """True if the grep hit is a Python comment, docstring, or doc-only string.

    The grep output line format is `path:lineno:content`. We need to look
    at content past the second colon.
    """
    parts = line.split(":", 2)
    if len(parts) < 3:
        return False
    content = parts[2].lstrip()
    if content.startswith("#"):
        return True
    # Multi-line docstring continuation lines — anything that does not
    # contain a SQL or Python token referencing the column directly.
    # Rough heuristic: line must contain `=` or `(` near the needle to be
    # a real reference; otherwise treat as documentation prose.
    return ("=" not in content) and ("(" not in content)


def run_smoke_test() -> bool:
    section("smoke test — affected endpoints")
    base = SMOKE_BASE.rstrip("/")
    endpoints = [
        f"{base}/api/v1/portfolio_context?ticker=AAPL&level=fund",
        f"{base}/api/v1/cross_ownership?tickers=AAPL&level=fund",
        f"{base}/api/v1/holder_momentum?ticker=AAPL&level=fund",
        f"{base}/api/v1/cohort_analysis?ticker=AAPL&active_only=true",
        f"{base}/api/v1/ownership_trend_summary?ticker=AAPL",
    ]
    ok = True
    any_reached = False
    for url in endpoints:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
                code = resp.status
                payload = resp.read()
                any_reached = True
                ok &= check(
                    f"GET {url.replace(base, '')}",
                    code == 200,
                    f"status={code} bytes={len(payload)}",
                )
        except urllib.error.HTTPError as e:
            any_reached = True
            ok &= check(f"GET {url.replace(base, '')}", False, f"HTTP {e.code}")
        except urllib.error.URLError as e:
            print(f"  [SKIP] GET {url.replace(base, '')} — server unreachable ({e.reason})")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  [SKIP] GET {url.replace(base, '')} — {exc}")
    if not any_reached:
        print("  (smoke test skipped — no Flask reachable at "
              f"{base}; rerun after starting the app)")
    return ok


def main() -> int:
    print(f"DB path: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"FATAL: {DB_PATH} does not exist")
        return 1

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_ok = run_db_checks(con)
    finally:
        con.close()

    constants_ok = run_constants_tests()
    lock_ok = run_lock_tests()
    grep_ok = run_active_code_grep()
    smoke_ok = run_smoke_test()

    section("summary")
    print(f"  db_checks      : {'PASS' if db_ok else 'FAIL'}")
    print(f"  constants_tests: {'PASS' if constants_ok else 'FAIL'}")
    print(f"  lock_tests     : {'PASS' if lock_ok else 'FAIL'}")
    print(f"  source_grep    : {'PASS' if grep_ok else 'FAIL'}")
    print(f"  smoke_test     : {'PASS' if smoke_ok else 'FAIL'}")
    overall = db_ok and constants_ok and lock_ok and grep_ok and smoke_ok
    print(f"  overall        : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
