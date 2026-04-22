"""p2-07: admin refresh endpoint tests.

Covers the 9 endpoints added in scripts/admin_bp.py:

  GET  /api/admin/status
  POST /api/admin/refresh/{pipeline}
  GET  /api/admin/run/{run_id}
  GET  /api/admin/probe/{pipeline}
  GET  /api/admin/runs/pending
  GET  /api/admin/runs/{run_id}/diff
  POST /api/admin/runs/{run_id}/approve
  POST /api/admin/runs/{run_id}/reject
  POST /api/admin/rollback/{run_id}

SourcePipeline.{run,approve_and_promote,reject,rollback} are patched so
the tests do not hit EDGAR or mutate any real DB.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[1]
ADMIN_TOKEN = "p2-07-test-token"


# ---------------------------------------------------------------------------
# minimal DB fixture
# ---------------------------------------------------------------------------


def _bootstrap_test_db(db_path: Path) -> None:
    """Create the minimal schema the admin endpoints read from."""
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_manifest (
                manifest_id              BIGINT,
                source_type              VARCHAR,
                object_type              VARCHAR,
                object_key               VARCHAR,
                source_url               VARCHAR,
                accession_number         VARCHAR,
                report_period            DATE,
                filing_date              DATE,
                accepted_at              TIMESTAMP,
                run_id                   VARCHAR,
                discovered_at            TIMESTAMP,
                fetch_started_at         TIMESTAMP,
                fetch_completed_at       TIMESTAMP,
                fetch_status             VARCHAR,
                http_code                INTEGER,
                source_bytes             BIGINT,
                source_checksum          VARCHAR,
                local_path               VARCHAR,
                retry_count              INTEGER,
                error_message            VARCHAR,
                parser_version           VARCHAR,
                schema_version           VARCHAR,
                is_amendment             BOOLEAN,
                prior_accession          VARCHAR,
                superseded_by_manifest_id BIGINT,
                created_at               TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_impacts (
                impact_id                BIGINT,
                manifest_id              BIGINT,
                target_table             VARCHAR,
                unit_type                VARCHAR,
                unit_key_json            VARCHAR,
                report_date              DATE,
                rows_staged              INTEGER,
                rows_promoted            INTEGER,
                load_status              VARCHAR,
                validation_tier          VARCHAR,
                validation_report        VARCHAR,
                promote_status           VARCHAR,
                promote_duration_ms      BIGINT,
                validate_duration_ms     BIGINT,
                promoted_at              TIMESTAMP,
                error_message            VARCHAR,
                created_at               TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS data_freshness (
                table_name        VARCHAR PRIMARY KEY,
                last_computed_at  TIMESTAMP,
                row_count         BIGINT
            )
        """)
        con.execute("CHECKPOINT")
    finally:
        con.close()


def _insert_manifest_row(
    db_path: Path, *, manifest_id: int, source_type: str,
    run_id: str, status: str, object_key: str,
) -> None:
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        con.execute(
            """
            INSERT INTO ingestion_manifest
              (manifest_id, source_type, object_type, object_key, source_url,
               run_id, fetch_status, fetch_completed_at, created_at)
            VALUES (?, ?, 'SCOPE', ?, ?, ?, ?, NOW(), NOW())
            """,
            [manifest_id, source_type, object_key,
             f"scope://{object_key}", run_id, status],
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()


@pytest.fixture(scope="module")
def test_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("p2_07") / "test.duckdb"
    _bootstrap_test_db(db_path)
    return db_path


@pytest.fixture(scope="module")
def client(test_db):
    os.environ["DB_PATH_OVERRIDE"] = str(test_db)
    os.environ["ENABLE_ADMIN"] = "1"
    os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN

    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "data").mkdir(exist_ok=True)

    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from fastapi.testclient import TestClient  # noqa: E402
    import app as app_module  # noqa: E402

    # Reset switchback state — app_db.DB_PATH was captured at import time
    # (possibly from another test module's DB_PATH_OVERRIDE). Force both
    # the module constant and the active path to our test DB.
    import app_db  # noqa: E402
    app_db.DB_PATH = str(test_db)
    app_db._active_db_path = None  # pylint: disable=protected-access
    app_db.init_db_path()

    return TestClient(app_module.app)


@pytest.fixture
def logged_in(client):
    resp = client.post("/api/admin/login", json={"token": ADMIN_TOKEN})
    assert resp.status_code == 200, resp.text
    yield client
    client.post("/api/admin/logout")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_status_returns_all_pipelines(logged_in):
    """/status includes an entry per PIPELINE_CADENCE pipeline (6 today)."""
    from pipeline.cadence import PIPELINE_CADENCE  # noqa: E402

    resp = logged_in.get("/api/admin/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "pipelines" in body
    assert "pending_runs" in body
    names = {p["name"] for p in body["pipelines"]}
    assert names == set(PIPELINE_CADENCE.keys())
    # Pipelines migrated to SourcePipeline so far:
    # 13f_holdings (p2-05), 13dg_ownership (w2-01), market_data (w2-02).
    registered = {p["name"] for p in body["pipelines"] if p["registered"]}
    assert registered == {"13f_holdings", "13dg_ownership", "market_data"}


def test_refresh_unknown_pipeline_404(logged_in):
    resp = logged_in.post("/api/admin/refresh/nonexistent", json={})
    assert resp.status_code == 404, resp.text
    assert "Unknown pipeline" in resp.json()["detail"]["error"]


def test_refresh_returns_run_id(logged_in):
    """A successful refresh spawns a background thread and returns 200.

    We patch SourcePipeline.run() so no real work happens — a quick
    sleep lets the lock release before the next test case runs.
    """
    from admin_bp import _release_pipeline  # noqa: E402

    def fake_run(_self, _scope):
        time.sleep(0.05)
        return "fake_run_id_13f_holdings_abc"

    with patch("load_13f_v2.Load13FPipeline.run", new=fake_run):
        resp = logged_in.post(
            "/api/admin/refresh/13f_holdings",
            json={"quarter": "2026Q1"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "started"
        assert body["pipeline"] == "13f_holdings"
        assert body["scope"] == {"quarter": "2026Q1"}
        assert "run_id_placeholder" in body

    # Wait briefly for the daemon thread to release the lock.
    deadline = time.time() + 2.0
    from admin_bp import _running_pipelines  # noqa: E402
    while time.time() < deadline and _running_pipelines.get("13f_holdings"):
        time.sleep(0.02)
    _release_pipeline("13f_holdings")  # belt-and-braces


def test_concurrent_refresh_409(logged_in):
    """A second refresh for the same pipeline returns 409 while the first runs."""
    from admin_bp import _acquire_pipeline, _release_pipeline  # noqa: E402

    # Simulate a run in flight by grabbing the lock ourselves.
    assert _acquire_pipeline("13f_holdings", "held_run_id")
    try:
        resp = logged_in.post(
            "/api/admin/refresh/13f_holdings", json={"quarter": "2026Q1"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["run_id"] == "held_run_id"
    finally:
        _release_pipeline("13f_holdings")


def test_run_status_not_found(logged_in):
    resp = logged_in.get("/api/admin/run/does_not_exist")
    assert resp.status_code == 404, resp.text


def test_run_status_returns_manifest_fields(logged_in, test_db):
    _insert_manifest_row(
        test_db, manifest_id=1001, source_type="13f_holdings",
        run_id="test_run_complete", status="complete",
        object_key="13f_holdings:quarter=2026Q1",
    )
    resp = logged_in.get("/api/admin/run/test_run_complete")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == "test_run_complete"
    assert body["status"] == "complete"
    assert body["scope"] == {"quarter": "2026Q1"}


def test_approve_wrong_state_400(logged_in, test_db):
    _insert_manifest_row(
        test_db, manifest_id=1002, source_type="13f_holdings",
        run_id="test_run_complete_not_pending", status="complete",
        object_key="13f_holdings:quarter=2026Q1",
    )
    resp = logged_in.post(
        "/api/admin/runs/test_run_complete_not_pending/approve",
    )
    assert resp.status_code == 400, resp.text
    assert "pending_approval" in resp.json()["detail"]["error"]


def test_reject_wrong_state_400(logged_in, test_db):
    _insert_manifest_row(
        test_db, manifest_id=1003, source_type="13f_holdings",
        run_id="test_run_cant_reject", status="complete",
        object_key="13f_holdings:quarter=2026Q1",
    )
    resp = logged_in.post(
        "/api/admin/runs/test_run_cant_reject/reject", json={"reason": "nope"},
    )
    assert resp.status_code == 400, resp.text


def test_reject_transitions_to_rejected(logged_in, test_db):
    _insert_manifest_row(
        test_db, manifest_id=1004, source_type="13f_holdings",
        run_id="test_run_pending_reject", status="pending_approval",
        object_key="13f_holdings:quarter=2026Q1",
    )

    def fake_reject(_self, run_id, reason):  # noqa: D401
        return None

    with patch("load_13f_v2.Load13FPipeline.reject", new=fake_reject):
        resp = logged_in.post(
            "/api/admin/runs/test_run_pending_reject/reject",
            json={"reason": "bad data"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["reason"] == "bad data"


def test_probe_caches(logged_in):
    """Second probe call within 15 minutes hits the cache."""
    call_count = {"n": 0}

    def fake_probe(_con):
        call_count["n"] += 1
        from datetime import datetime
        return {
            "new_count": 3, "latest_accession": "0001234567-26-000001",
            "probed_at": datetime.utcnow(),
        }

    with patch("pipeline.cadence.probe_13f_accessions", new=fake_probe), \
            patch.dict(
                "pipeline.cadence.PIPELINE_CADENCE",
                {
                    "13f_holdings": dict(
                        __import__(
                            "pipeline.cadence", fromlist=["PIPELINE_CADENCE"],
                        ).PIPELINE_CADENCE["13f_holdings"],
                        probe_fn=fake_probe,
                    ),
                },
            ):
        # Clear cache between tests.
        from admin_bp import _probe_cache  # noqa: E402
        _probe_cache.pop("13f_holdings", None)

        r1 = logged_in.get("/api/admin/probe/13f_holdings")
        assert r1.status_code == 200, r1.text
        assert r1.json().get("cached") is False
        assert call_count["n"] == 1

        r2 = logged_in.get("/api/admin/probe/13f_holdings")
        assert r2.status_code == 200, r2.text
        assert r2.json().get("cached") is True
        assert call_count["n"] == 1  # no new probe call


def test_probe_unknown_pipeline_404(logged_in):
    resp = logged_in.get("/api/admin/probe/not_a_pipeline")
    assert resp.status_code == 404, resp.text


def test_rollback_wrong_state_400(logged_in, test_db):
    _insert_manifest_row(
        test_db, manifest_id=1005, source_type="13f_holdings",
        run_id="test_run_cant_rollback", status="pending_approval",
        object_key="13f_holdings:quarter=2026Q1",
    )
    resp = logged_in.post("/api/admin/rollback/test_run_cant_rollback")
    assert resp.status_code == 400, resp.text


def test_runs_pending_lists_pending(logged_in, test_db):
    _insert_manifest_row(
        test_db, manifest_id=1006, source_type="13f_holdings",
        run_id="test_run_pending_list", status="pending_approval",
        object_key="13f_holdings:quarter=2026Q1",
    )
    resp = logged_in.get("/api/admin/runs/pending")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    run_ids = {r["run_id"] for r in body["pending"]}
    assert "test_run_pending_list" in run_ids
