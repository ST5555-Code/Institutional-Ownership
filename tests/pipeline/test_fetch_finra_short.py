"""Regression tests for scripts/fetch_finra_short.py --dry-run / --apply.

Exercises the CLI surface via subprocess so argparse wiring — mutex
group, deprecation warning on no flag, and the dry-run write guard — is
verified end-to-end rather than at the function boundary. Same lesson
as the load_13f_v2 B2.5 cutover: CLI contracts are a separate surface
from the functions they call.

FINRA fetches are neutralised by pointing FINRA_BASE_URL_OVERRIDE at an
in-process HTTP server that 404s every path. fetch_day treats 404 as a
holiday/weekend miss and returns None, so all_rows is empty and writes
collapse onto the data_freshness row only — which is enough to
distinguish dry-run from apply via the last_computed_at timestamp.

DB isolation: --test routes writes to data/13f_test.duckdb. The
seeded_test_db fixture rewrites that file with a known seed before
each test and removes it afterwards.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fetch_finra_short.py"
TEST_DB = ROOT / "data" / "13f_test.duckdb"


# ---------------------------------------------------------------------------
# Local HTTP 404 fixture
# ---------------------------------------------------------------------------

class _Always404(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args, **kwargs):  # silence default stderr logging
        return


@pytest.fixture(scope="module")
def finra_stub_url():
    server = HTTPServer(("127.0.0.1", 0), _Always404)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# DB seed fixture
# ---------------------------------------------------------------------------

SEED_TS = "2000-01-01 00:00:00"


@pytest.fixture
def seeded_test_db():
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB.exists():
        TEST_DB.unlink()

    con = duckdb.connect(str(TEST_DB))
    try:
        con.execute("""
            CREATE TABLE short_interest (
                ticker VARCHAR,
                short_volume BIGINT,
                short_exempt_volume BIGINT,
                total_volume BIGINT,
                report_date DATE,
                report_month VARCHAR,
                short_pct DOUBLE,
                loaded_at TIMESTAMP,
                PRIMARY KEY (ticker, report_date)
            )
        """)
        con.execute(
            "INSERT INTO short_interest VALUES "
            "('SEED', 1, 0, 10, DATE '1990-01-01', '1990-01', 10.0, CURRENT_TIMESTAMP)"
        )
        con.execute("""
            CREATE TABLE data_freshness (
                table_name VARCHAR PRIMARY KEY,
                last_computed_at TIMESTAMP,
                row_count BIGINT
            )
        """)
        con.execute(
            f"INSERT INTO data_freshness VALUES "
            f"('short_interest', TIMESTAMP '{SEED_TS}', 1)"
        )
    finally:
        con.close()

    yield TEST_DB

    if TEST_DB.exists():
        TEST_DB.unlink()


def _snapshot(path):
    """Return (short_interest_rowcount, freshness_timestamp_str_or_None)."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        try:
            rc = con.execute("SELECT COUNT(*) FROM short_interest").fetchone()[0]
        except duckdb.CatalogException:
            rc = None
        try:
            row = con.execute(
                "SELECT last_computed_at FROM data_freshness WHERE table_name = 'short_interest'"
            ).fetchone()
            ts = str(row[0]) if row else None
        except duckdb.CatalogException:
            ts = None
    finally:
        con.close()
    return rc, ts


def _run(args, finra_stub_url, timeout=60):
    env = {**os.environ, "FINRA_BASE_URL_OVERRIDE": finra_stub_url}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, timeout=timeout, env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_help_advertises_modes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "--dry-run" in result.stdout
    assert "--apply" in result.stdout


def test_dry_run_and_apply_are_mutually_exclusive(finra_stub_url):
    result = _run(["--dry-run", "--apply", "--test"], finra_stub_url)
    assert result.returncode != 0
    assert "not allowed with" in result.stderr


def test_dry_run_makes_no_writes(seeded_test_db, finra_stub_url):
    pre_rc, pre_ts = _snapshot(seeded_test_db)
    assert pre_rc == 1
    assert pre_ts == SEED_TS

    result = _run(["--dry-run", "--test"], finra_stub_url)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "[DRY-RUN]" in result.stdout

    post_rc, post_ts = _snapshot(seeded_test_db)
    assert post_rc == pre_rc, "dry-run must not touch short_interest"
    assert post_ts == pre_ts, "dry-run must not update data_freshness"


def test_apply_updates_freshness_stamp(seeded_test_db, finra_stub_url):
    _, pre_ts = _snapshot(seeded_test_db)
    result = _run(["--apply", "--test"], finra_stub_url)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    _, post_ts = _snapshot(seeded_test_db)
    assert post_ts != pre_ts, "apply must update data_freshness.last_computed_at"


def test_no_flag_warns_and_applies(seeded_test_db, finra_stub_url):
    _, pre_ts = _snapshot(seeded_test_db)
    result = _run(["--test"], finra_stub_url)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "[deprecation]" in result.stderr
    _, post_ts = _snapshot(seeded_test_db)
    assert post_ts != pre_ts, "no-flag default must apply (match current behaviour)"


def test_apply_is_idempotent(seeded_test_db, finra_stub_url):
    """INSERT OR IGNORE on (ticker, report_date) survives a double-apply."""
    _run(["--apply", "--test"], finra_stub_url)
    rc_after_first, _ = _snapshot(seeded_test_db)
    _run(["--apply", "--test"], finra_stub_url)
    rc_after_second, _ = _snapshot(seeded_test_db)
    assert rc_after_first == rc_after_second, \
        "second --apply must not produce duplicates under PK guard"
