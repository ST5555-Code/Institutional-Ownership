"""Unit tests for scripts/promote_nport.py — obs-07 report_month gate.

Verifies _assert_no_future_report_month():
  * passes when all staged report_months are in the current or past month
  * raises SystemExit with "obs-07 gate FAIL" when any staged report_month
    is strictly greater than the current calendar month
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import promote_nport  # noqa: E402


def _build_staging_con(rows: list[tuple[str, str, str]]) -> duckdb.DuckDBPyConnection:
    """Return an in-memory DuckDB connection seeded with minimal staging
    tables sufficient for the gate's JOIN.

    rows: list of (manifest_id, series_id, report_month).
    """
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE ingestion_manifest (
            manifest_id VARCHAR,
            run_id VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE stg_nport_holdings (
            manifest_id VARCHAR,
            series_id VARCHAR,
            report_month VARCHAR
        )
        """
    )
    manifests = {mid for (mid, _s, _m) in rows}
    for mid in manifests:
        con.execute(
            "INSERT INTO ingestion_manifest VALUES (?, ?)",
            [mid, "RUN_TEST"],
        )
    for mid, sid, rm in rows:
        con.execute(
            "INSERT INTO stg_nport_holdings VALUES (?, ?, ?)",
            [mid, sid, rm],
        )
    return con


class TestReportMonthGate:
    def test_passes_when_all_months_in_past(self, capsys):
        con = _build_staging_con([
            ("M1", "S000001", "2024-06"),
            ("M1", "S000002", "2025-12"),
            ("M1", "S000003", "2026-01"),
        ])
        promote_nport._assert_no_future_report_month(con, "RUN_TEST")
        out = capsys.readouterr().out
        assert "report_month gate: PASS" in out

    def test_passes_when_month_is_current_month(self, capsys):
        current_month = date.today().strftime("%Y-%m")
        con = _build_staging_con([("M1", "S000001", current_month)])
        promote_nport._assert_no_future_report_month(con, "RUN_TEST")
        out = capsys.readouterr().out
        assert "report_month gate: PASS" in out

    def test_raises_when_future_month_present(self):
        con = _build_staging_con([
            ("M1", "S000001", "2025-06"),
            ("M1", "S000999", "2099-01"),
        ])
        with pytest.raises(SystemExit) as excinfo:
            promote_nport._assert_no_future_report_month(con, "RUN_TEST")
        msg = str(excinfo.value)
        assert "obs-07 gate FAIL" in msg
        assert "2099-01" in msg
        assert "S000999" in msg

    def test_only_flags_current_run(self, capsys):
        """Offenders tied to a different run_id must not trigger the gate."""
        con = _build_staging_con([
            ("M1", "S000001", "2025-06"),
        ])
        con.execute(
            "INSERT INTO ingestion_manifest VALUES (?, ?)",
            ["M2", "RUN_OTHER"],
        )
        con.execute(
            "INSERT INTO stg_nport_holdings VALUES (?, ?, ?)",
            ["M2", "S000777", "2099-12"],
        )
        promote_nport._assert_no_future_report_month(con, "RUN_TEST")
        out = capsys.readouterr().out
        assert "report_month gate: PASS" in out
