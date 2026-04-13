"""Phase 0-B2 smoke test fixtures.

Sets DB_PATH_OVERRIDE before importing scripts.app so the Flask app boots
against the committed CI fixture DB instead of prod.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"


@pytest.fixture(scope="session", autouse=True)
def _configure_fixture_db():
    if not FIXTURE_DB.exists():
        pytest.fail(
            f"Fixture DB missing: {FIXTURE_DB}. Run scripts/build_fixture.py --yes first."
        )
    os.environ["DB_PATH_OVERRIDE"] = str(FIXTURE_DB)
    # scripts/ is not a package, so add it directly to sys.path and import `app`.
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


@pytest.fixture(scope="session")
def client(_configure_fixture_db):
    # Import after env var + sys.path are set.
    import app as app_module  # noqa: E402 — deferred on purpose
    return app_module.app.test_client()
