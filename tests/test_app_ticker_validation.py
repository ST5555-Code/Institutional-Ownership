"""BL-7: route-layer ticker validation against the DB-universe tables.

Two validators live in scripts/api_common.py:

  validate_ticker_current    — LQ + is_latest=TRUE in holdings_v2
                               (matches /api/v1/tickers autocomplete)
  validate_ticker_historical — EXISTS in summary_by_ticker (any quarter)

This file verifies:

  1. Valid ticker (AAPL) — current-family + historical-family routes 200.
  2. Invalid but shape-valid ticker (ZZZZZ) — current routes 404,
     historical routes 404, and the error body names the ticker.
  3. Missing ticker — 400 "Missing ticker parameter"
     (existing guard, preserved).
  4. Lowercase ticker (aapl) — normalized to AAPL and passes through.
  5. /api/v1/tickers — reference endpoint, no self-rejection.
  6. /api/v1/query{N} ?quarter= override — current-family query with
     ?quarter=<non-LQ> switches to historical validator.
  7. Multi-ticker routes — a mix of valid + invalid tickers 404s on the
     invalid one (no silent empty-result).

Fixture: tests/fixtures/13f_fixture.duckdb (AAPL present in LQ=2025Q4
with is_latest=TRUE, and in summary_by_ticker across multiple quarters).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
MIG_027 = ROOT / "scripts" / "migrations" / "027_unified_holdings_view.py"
MIG_028 = (
    ROOT / "scripts" / "migrations"
    / "028_unified_holdings_quarter_dimension.py"
)


def _load_migration(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if not FIXTURE_DB.exists():
        pytest.skip(f"Fixture DB missing: {FIXTURE_DB}")

    # CP-5.3: cross-ownership readers now consume inst_to_top_parent /
    # unified_holdings (migrations 027 + 028). The committed fixture
    # carries tables only — views are migration-managed and must be
    # applied to a tmp copy before booting the FastAPI test client.
    # Mirrors tests/smoke/conftest.py wiring added in PR #300.
    tmp_dir = tmp_path_factory.mktemp("bl7_fixture")
    tmp_db = tmp_dir / "13f_fixture_with_views.duckdb"
    shutil.copy(FIXTURE_DB, tmp_db)

    boot = duckdb.connect(str(tmp_db))
    boot.execute(
        "CREATE TABLE IF NOT EXISTS schema_versions ("
        "  version VARCHAR PRIMARY KEY, "
        "  notes VARCHAR, "
        "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    boot.close()
    _load_migration(MIG_027, "mig027").run_migration(
        str(tmp_db), dry_run=False, skip_guards=True
    )
    _load_migration(MIG_028, "mig028").run_migration(
        str(tmp_db), dry_run=False, skip_guards=True
    )

    os.environ["DB_PATH_OVERRIDE"] = str(tmp_db)

    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from fastapi.testclient import TestClient  # noqa: E402
    import app as app_module  # noqa: E402

    # app_db.DB_PATH + _active_db_path may have been captured at import time
    # by earlier test modules with their own scratch DB. Force both back to
    # the BL-7 fixture DB. Same pattern as test_admin_refresh_endpoints.py.
    import app_db  # noqa: E402
    app_db.DB_PATH = str(tmp_db)
    app_db._active_db_path = None  # pylint: disable=protected-access
    app_db.init_db_path()

    return TestClient(app_module.app)


# Shape-valid unknown ticker. "ZZZZZ" matches TICKER_RE ^[A-Z]{1,6}(\.[A-Z])?$
# and is absent from both holdings_v2 and summary_by_ticker in the fixture.
UNKNOWN = "ZZZZZ"


# ── Reference endpoint — must NOT self-reject ─────────────────────────────


def test_tickers_endpoint_no_validation(client):
    """The autocomplete reference endpoint takes no ticker — it IS the universe."""
    resp = client.get("/api/v1/tickers")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict) and isinstance(body.get("data"), list)


# ── Current-family routes (LQ + is_latest=TRUE universe) ──────────────────

CURRENT_ROUTES = [
    "/api/v1/query1?ticker={t}",
    "/api/v1/portfolio_context?ticker={t}",
    "/api/v1/short_analysis?ticker={t}",
    "/api/v1/crowding?ticker={t}",
    "/api/v1/smart_money?ticker={t}",
    "/api/v1/fund_portfolio_managers?ticker={t}",
]


@pytest.mark.parametrize("route_tpl", CURRENT_ROUTES)
def test_current_valid_ticker_not_rejected_by_validator(client, route_tpl):
    """AAPL exists in LQ — validator must not 404 it. Pre-existing route 404s
    are fine; we assert only that the validator's own message is absent from
    the response body."""
    resp = client.get(route_tpl.format(t="AAPL"))
    assert "not found in current holdings" not in resp.text, (
        f"{route_tpl}: validator rejected valid AAPL — {resp.text[:200]}"
    )


@pytest.mark.parametrize("route_tpl", CURRENT_ROUTES)
def test_current_unknown_ticker_404(client, route_tpl):
    """Shape-valid unknown ticker → 404 with the ticker named in the body."""
    resp = client.get(route_tpl.format(t=UNKNOWN))
    assert resp.status_code == 404, f"{route_tpl}: expected 404, got {resp.status_code} — {resp.text[:200]}"
    assert UNKNOWN in resp.text, f"{route_tpl}: 404 body does not name the ticker"


# ── Historical-family routes (summary_by_ticker universe) ─────────────────

HISTORICAL_ROUTES = [
    "/api/v1/summary?ticker={t}",
    "/api/v1/flow_analysis?ticker={t}",
    "/api/v1/ownership_trend_summary?ticker={t}",
    "/api/v1/cohort_analysis?ticker={t}",
    "/api/v1/holder_momentum?ticker={t}",
    "/api/v1/peer_rotation?ticker={t}",
]


@pytest.mark.parametrize("route_tpl", HISTORICAL_ROUTES)
def test_historical_valid_ticker_not_rejected_by_validator(client, route_tpl):
    resp = client.get(route_tpl.format(t="AAPL"))
    assert "has no historical data" not in resp.text, (
        f"{route_tpl}: validator rejected valid AAPL — {resp.text[:200]}"
    )


@pytest.mark.parametrize("route_tpl", HISTORICAL_ROUTES)
def test_historical_unknown_ticker_404(client, route_tpl):
    resp = client.get(route_tpl.format(t=UNKNOWN))
    assert resp.status_code == 404, f"{route_tpl}: expected 404, got {resp.status_code} — {resp.text[:200]}"
    assert UNKNOWN in resp.text


# ── Missing-parameter handling (existing guard, preserved) ────────────────


def test_missing_ticker_returns_400(client):
    """Routes with `ticker: str = ''` default return 400 on empty, not 422."""
    resp = client.get("/api/v1/summary")
    assert resp.status_code == 400, resp.text
    assert "Missing ticker" in resp.text


def test_missing_ticker_on_query1_returns_400(client):
    resp = client.get("/api/v1/query1")
    assert resp.status_code == 400, resp.text


# ── Lowercase input — current behavior preserved (normalized upstream) ────


def test_lowercase_ticker_normalized(client):
    """Route handlers upper()/strip() before validation. 'aapl' → AAPL passes."""
    resp = client.get("/api/v1/query1?ticker=aapl")
    assert resp.status_code != 404, resp.text


def test_lowercase_unknown_ticker_still_404(client):
    resp = client.get(f"/api/v1/query1?ticker={UNKNOWN.lower()}")
    assert resp.status_code == 404, resp.text


# ── ?quarter= override on /query{N} dispatch ──────────────────────────────


def test_query1_current_quarter_uses_current_validator(client):
    """q1 without ?quarter= — current validator."""
    # ZZZZZ not in LQ → 404.
    resp = client.get(f"/api/v1/query1?ticker={UNKNOWN}")
    assert resp.status_code == 404


def test_query1_explicit_current_quarter_stays_current(client):
    """?quarter=<LQ> should NOT override to historical."""
    from config import LATEST_QUARTER
    resp = client.get(f"/api/v1/query1?ticker={UNKNOWN}&quarter={LATEST_QUARTER}")
    assert resp.status_code == 404, resp.text


def test_query1_historical_quarter_override_unknown_still_404(client):
    """q1 with ?quarter=<non-LQ> — historical validator kicks in.
    ZZZZZ is absent from summary_by_ticker too, so still 404."""
    resp = client.get(f"/api/v1/query1?ticker={UNKNOWN}&quarter=2025Q1")
    assert resp.status_code == 404, resp.text


# ── Multi-ticker routes: first invalid ticker 404s the whole request ──────


def test_cross_ownership_all_valid(client):
    resp = client.get("/api/v1/cross_ownership?tickers=AAPL")
    assert resp.status_code != 404, resp.text


def test_cross_ownership_mixed_invalid_404s(client):
    resp = client.get(f"/api/v1/cross_ownership?tickers=AAPL,{UNKNOWN}")
    assert resp.status_code == 404, resp.text
    assert UNKNOWN in resp.text


def test_cross_ownership_top_mixed_invalid_404s(client):
    resp = client.get(f"/api/v1/cross_ownership_top?tickers={UNKNOWN},AAPL")
    assert resp.status_code == 404, resp.text
    assert UNKNOWN in resp.text


def test_two_company_overlap_second_invalid_404s(client):
    resp = client.get(f"/api/v1/two_company_overlap?subject=AAPL&second={UNKNOWN}")
    assert resp.status_code == 404, resp.text
    assert UNKNOWN in resp.text


def test_two_company_subject_invalid_404s(client):
    resp = client.get(f"/api/v1/two_company_subject?subject={UNKNOWN}")
    assert resp.status_code == 404, resp.text
    assert UNKNOWN in resp.text


# ── q7 (Fund Portfolio) skips ticker validation ───────────────────────────


def test_query7_skips_ticker_validation(client):
    """q7 keys on cik/fund_name; pre-existing 'No holdings found for CIK'
    404 handles bad inputs. Validator must not add a second ticker-404 path.
    Exact response varies (200/400/404 on empty) but the validator layer
    itself must not reject a known-unknown ticker before dispatch."""
    # With a known-unknown ticker and no cik — the handler proceeds to the
    # query7 call, which returns the 'not_found' envelope for the CIK.
    # The important assertion: error body does NOT mention the BL-7
    # current/historical validator strings.
    resp = client.get(f"/api/v1/query7?ticker={UNKNOWN}")
    body = resp.text
    assert "not found in current holdings" not in body
    assert "has no historical data" not in body
