"""sec-03-p1: /api/admin/add_ticker concurrency + input-validation tests.

Covers the changes in scripts/admin_bp.py:
  - P0-1: fcntl.flock guard on data/.add_ticker.lock (409 on contention)
  - P0-2: TICKER_RE input regex (400 on invalid format)

External clients (OpenFIGI requests.post, YahooClient, SECSharesClient)
are patched so no network traffic is generated. `edgar` is not patched
because the handler already wraps that step in its own try/except.

The flock guard is exercised by holding the kernel lock from the test
process itself (rather than by racing two TestClient threads — the
admin-session dependency uses a thread-local DuckDB connection with an
ATTACH that does not play nicely with simultaneous auth checks in
pytest's TestClient). This still fully exercises the production code
path: the handler attempts fcntl.flock(LOCK_EX | LOCK_NB) and must
return 409 when another holder exists, regardless of who that holder is.

Tests:
  1. test_invalid_ticker_format_rejected — regex short-circuit to 400
  2. test_valid_ticker_formats_pass_regex — BRK.B, BF-A pass validation
  3. test_add_ticker_returns_409_when_lock_held — flock contention → 409
  4. test_lock_released_after_request — subsequent request succeeds
"""
from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
ADMIN_TOKEN = "sec-03-p1-test-token"


@pytest.fixture(scope="module")
def client():
    if not FIXTURE_DB.exists():
        pytest.skip(f"Fixture DB missing: {FIXTURE_DB}")
    os.environ["DB_PATH_OVERRIDE"] = str(FIXTURE_DB)
    os.environ["ENABLE_ADMIN"] = "1"
    os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN

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
    resp = client.post("/api/admin/login", json={"token": ADMIN_TOKEN})
    assert resp.status_code == 200, resp.text
    yield client
    client.post("/api/admin/logout")


@pytest.fixture
def mock_externals():
    """Stub every external call /add_ticker makes.

    OpenFIGI returns no match; YahooClient returns no price, so the
    handler skips the PROD_DB write path entirely — keeps the test
    hermetic without needing a writable fixture. `edgar` is allowed to
    fail naturally (its step is wrapped in its own try/except in the
    handler).
    """
    def fast_openfigi_post(*_args, **_kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = []
        return r

    yc_instance = MagicMock()
    yc_instance.fetch_metadata.return_value = {}

    sc_instance = MagicMock()
    sc_instance.fetch.return_value = {}

    with patch("requests.post", side_effect=fast_openfigi_post), \
         patch("yahoo_client.YahooClient", return_value=yc_instance), \
         patch("sec_shares_client.SECSharesClient", return_value=sc_instance):
        yield


@pytest.fixture
def lock_held():
    """Acquire the add_ticker flock from the test process itself.

    The handler uses a non-blocking LOCK_EX on data/.add_ticker.lock;
    if any other fd in the system already holds the lock, the handler's
    fcntl.flock call raises BlockingIOError and the 409 branch fires.
    This fixture drives that path deterministically without depending
    on request-thread interleaving.
    """
    lock_path = ROOT / "data" / ".add_ticker.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_invalid_ticker_format_rejected(logged_in):
    """Path-traversal, empty string, and overlong tickers all return 400."""
    for bad in ["../../etc/passwd", "", "AAAAAAAAAAA", "AAPL;DROP", "A B"]:
        resp = logged_in.post("/api/admin/add_ticker", json={"ticker": bad})
        assert resp.status_code == 400, f"ticker={bad!r} → {resp.status_code} {resp.text}"
        assert "invalid ticker format" in resp.json().get("error", "")


def test_valid_ticker_formats_pass_regex(logged_in, mock_externals):
    """BRK.B (dot) and BF-A (hyphen) pass the regex and reach the handler body."""
    for good in ["BRK.B", "BF-A", "AAPL", "A"]:
        resp = logged_in.post("/api/admin/add_ticker", json={"ticker": good})
        assert resp.status_code == 200, f"ticker={good!r} → {resp.status_code} {resp.text}"
        body = resp.json()
        assert body.get("ticker") == good.upper()
        assert body.get("status") == "ok"


def test_add_ticker_returns_409_when_lock_held(logged_in, mock_externals, lock_held):
    """With another process already holding data/.add_ticker.lock, /add_ticker 409s."""
    resp = logged_in.post("/api/admin/add_ticker", json={"ticker": "AAPL"})
    assert resp.status_code == 409, resp.text
    assert "another add_ticker is in flight" in resp.json().get("error", "")


def test_lock_released_after_request(logged_in, mock_externals):
    """After a request completes, the next /add_ticker succeeds (lock was released)."""
    resp1 = logged_in.post("/api/admin/add_ticker", json={"ticker": "AAPL"})
    assert resp1.status_code == 200, resp1.text

    resp2 = logged_in.post("/api/admin/add_ticker", json={"ticker": "MSFT"})
    assert resp2.status_code == 200, resp2.text
