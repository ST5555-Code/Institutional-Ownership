"""Phase 0-B2 smoke test fixtures.

Sets DB_PATH_OVERRIDE before importing scripts.app so the Flask app boots
against the committed CI fixture DB instead of prod.

CP-5.2 update: copies the fixture to a tmp file and applies migrations
027 + 028 (read-time views consumed by Register / Cross / Flows readers).
The committed fixture intentionally tracks the table schema only; views
are migration-managed and re-created on each smoke run so the schema
matches the readers under test.
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

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
MIG_027 = ROOT / "scripts" / "migrations" / "027_unified_holdings_view.py"
MIG_028 = (
    ROOT / "scripts" / "migrations"
    / "028_unified_holdings_quarter_dimension.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session", autouse=True)
def _configure_fixture_db(tmp_path_factory):
    if not FIXTURE_DB.exists():
        pytest.fail(
            f"Fixture DB missing: {FIXTURE_DB}. "
            "Run scripts/build_fixture.py --yes first."
        )
    tmp_dir = tmp_path_factory.mktemp("smoke_fixture")
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

    _load(MIG_027, "mig027").run_migration(
        str(tmp_db), dry_run=False, skip_guards=True
    )
    _load(MIG_028, "mig028").run_migration(
        str(tmp_db), dry_run=False, skip_guards=True
    )

    os.environ["DB_PATH_OVERRIDE"] = str(tmp_db)
    # scripts/ is not a package, so add it directly to sys.path and import `app`.
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


@pytest.fixture(scope="session")
def client(_configure_fixture_db):
    # Import after env var + sys.path are set.
    from fastapi.testclient import TestClient  # noqa: E402
    import app as app_module  # noqa: E402 — deferred on purpose
    return TestClient(app_module.app)
