"""Unit tests for the N-PORT obs-07 report_month gate (w2-03).

The gate originally lived in ``scripts/promote_nport.py``; after the
w2-03 migration it is part of ``LoadNPortPipeline.validate()`` via the
module-level ``_assert_no_future_report_month`` helper in
``scripts/pipeline/load_nport.py``. The helper now reads from the
typed staging table ``fund_holdings_v2`` (populated by ``parse()``)
rather than the raw ``stg_nport_holdings`` table, and returns a list of
BLOCK strings instead of raising SystemExit.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.load_nport import _assert_no_future_report_month  # noqa: E402


def _build_staging_con(rows: list[tuple[str, str]]) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection seeded with typed staging rows.

    rows: list of (series_id, report_month).
    """
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE fund_holdings_v2 (
            series_id    VARCHAR,
            report_month VARCHAR
        )
        """
    )
    for sid, rm in rows:
        con.execute(
            "INSERT INTO fund_holdings_v2 VALUES (?, ?)", [sid, rm],
        )
    return con


class TestReportMonthGate:
    def test_passes_when_all_months_in_past(self):
        con = _build_staging_con([
            ("S000001", "2024-06"),
            ("S000002", "2025-12"),
            ("S000003", "2026-01"),
        ])
        assert _assert_no_future_report_month(con) == []

    def test_passes_when_month_is_current_month(self):
        current_month = date.today().strftime("%Y-%m")
        con = _build_staging_con([("S000001", current_month)])
        assert _assert_no_future_report_month(con) == []

    def test_returns_block_when_future_month_present(self):
        con = _build_staging_con([
            ("S000001", "2025-06"),
            ("S000999", "2099-01"),
        ])
        blocks = _assert_no_future_report_month(con)
        assert len(blocks) == 1
        assert "report_month_in_future" in blocks[0]
        assert "2099-01" in blocks[0]
        assert "S000999" in blocks[0]

    def test_returns_empty_when_staging_table_missing(self):
        """A staging DB without fund_holdings_v2 short-circuits to []."""
        con = duckdb.connect(":memory:")
        assert _assert_no_future_report_month(con) == []
