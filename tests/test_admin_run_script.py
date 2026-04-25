"""sec-02-p1: /api/admin/run_script TOCTOU concurrency tests.

Covers the fcntl.flock guard added in scripts/admin_bp.py. The real
subprocess.Popen is shimmed to spawn `sleep` instead of the actual
pipeline script — this keeps pass_fds live (so the flock behavior is
exercised end-to-end against a real child process) but avoids running
any ingest code or touching the DB.

Tests:
  1. test_concurrent_same_script_one_wins — two parallel requests for
     the same script resolve to exactly one 200 and one 409.
  2. test_lock_released_on_child_exit     — after the winner's child
     dies, a subsequent request for the same script succeeds.
  3. test_different_scripts_both_allowed  — per-script locks let
     distinct scripts run in parallel.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
ADMIN_TOKEN = "sec-02-p1-test-token"


@pytest.fixture(scope="module")
def client():
    if not FIXTURE_DB.exists():
        pytest.skip(f"Fixture DB missing: {FIXTURE_DB}")
    os.environ["DB_PATH_OVERRIDE"] = str(FIXTURE_DB)
    os.environ["ENABLE_ADMIN"] = "1"
    os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN

    # logs/ and data/ are gitignored; worktrees spun up fresh may lack them.
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "data").mkdir(exist_ok=True)

    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from fastapi.testclient import TestClient  # noqa: E402
    import app as app_module  # noqa: E402

    return TestClient(app_module.app)


@pytest.fixture
def logged_in(client):
    # These tests exercise the /run_script flock — not session auth. The real
    # auth dependency (require_admin_session) lazily ATTACHes admin.duckdb per
    # thread; two worker threads racing that ATTACH hit a DuckDB 1.4.4
    # catalog-visibility race that surfaces here as a CatalogException, turning
    # this test flaky for reasons unrelated to the lock being tested. Bypass
    # the dependency with FastAPI's dependency_overrides so the test isolates
    # the flock behavior it exists to verify.
    import app as app_module  # noqa: E402
    import admin_bp  # noqa: E402

    app_module.app.dependency_overrides[admin_bp.require_admin_session] = lambda: None
    try:
        yield client
    finally:
        app_module.app.dependency_overrides.pop(admin_bp.require_admin_session, None)


@pytest.fixture
def popen_sleep():
    """Replace admin_bp.subprocess.Popen with a shim that spawns `sleep`.

    Preserves pass_fds (so the lock fd reaches the child) and all other
    kwargs (stdout/stderr redirection, cwd, close_fds). Returns the list
    of spawned Popen handles so individual tests can kill them.
    """
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen] = []

    def shim(_cmd, **kwargs):
        proc = real_popen(["sleep", "30"], **kwargs)
        spawned.append(proc)
        return proc

    with patch("admin_bp.subprocess.Popen", side_effect=shim):
        yield spawned

    for proc in spawned:
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for proc in spawned:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    # Clear any cookies between tests so the next fixture's login is fresh.
    # (Module-scoped client fixture shares cookies across tests.)


def _fire(client, results, idx, script):
    resp = client.post(
        "/api/admin/run_script",
        json={"script": script, "flags": []},
    )
    results[idx] = (resp.status_code, resp.json())


def test_concurrent_same_script_one_wins(logged_in, popen_sleep):
    """Two parallel POSTs for the same script: exactly one 200 and one 409."""
    results: list = [None, None]
    barrier = threading.Barrier(2)

    def fire_synced(idx, script):
        barrier.wait()
        _fire(logged_in, results, idx, script)

    t1 = threading.Thread(target=fire_synced, args=(0, "compute_flows.py"))
    t2 = threading.Thread(target=fire_synced, args=(1, "compute_flows.py"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not t1.is_alive() and not t2.is_alive(), "request threads hung"

    statuses = sorted(r[0] for r in results)
    assert statuses == [200, 409], f"Unexpected outcomes: {results}"

    winner_body = next(r[1] for r in results if r[0] == 200)
    loser_body = next(r[1] for r in results if r[0] == 409)
    assert winner_body["status"] == "started"
    assert winner_body["script"] == "compute_flows.py"
    assert isinstance(winner_body["pid"], int)
    assert "already running" in loser_body["error"]

    # The loser must NOT have spawned a child. Exactly one sleep process.
    assert len(popen_sleep) == 1, f"Expected 1 child, got {len(popen_sleep)}"


def test_lock_released_on_child_exit(logged_in, popen_sleep):
    """After the winner's child dies, a fresh request for the same script succeeds."""
    resp1 = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": []},
    )
    assert resp1.status_code == 200, resp1.text

    # Second request while the first child is alive must 409.
    resp2 = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": []},
    )
    assert resp2.status_code == 409, resp2.text

    # Kill the first child and wait for the kernel to release the OFD lock.
    os.kill(resp1.json()["pid"], signal.SIGKILL)
    popen_sleep[0].wait(timeout=5)

    # Small beat for the kernel to finalize fd teardown after wait().
    time.sleep(0.2)

    resp3 = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": []},
    )
    assert resp3.status_code == 200, resp3.text
    assert len(popen_sleep) == 2


def test_different_scripts_both_allowed(logged_in, popen_sleep):
    """Per-script locks: two different scripts may run concurrently."""
    resp_a = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": []},
    )
    resp_b = logged_in.post(
        "/api/admin/run_script",
        json={"script": "fetch_market.py", "flags": []},
    )
    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    assert resp_a.json()["pid"] != resp_b.json()["pid"]
    assert len(popen_sleep) == 2


def test_unknown_flag_rejected(logged_in, popen_sleep):
    """ALLOWED_FLAGS gate: unknown flags 400 before subprocess.Popen."""
    resp = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": ["--evil"]},
    )
    assert resp.status_code == 400, resp.text
    assert "not allowed" in resp.json()["error"].lower()
    assert popen_sleep == []


def test_value_flag_requires_value(logged_in, popen_sleep):
    """--quarter without a following value is rejected."""
    resp = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": ["--quarter"]},
    )
    assert resp.status_code == 400, resp.text
    assert popen_sleep == []


def test_value_flag_value_cannot_be_flag(logged_in, popen_sleep):
    """--quarter --all is rejected: value must not start with --."""
    resp = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": ["--quarter", "--all"]},
    )
    assert resp.status_code == 400, resp.text
    assert popen_sleep == []


def test_allowed_flags_accepted(logged_in, popen_sleep):
    """Documented flag set is accepted end-to-end."""
    resp = logged_in.post(
        "/api/admin/run_script",
        json={"script": "compute_flows.py", "flags": ["--dry-run", "--quarter", "2024Q1"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "started"
    assert len(popen_sleep) == 1
