"""Unit tests for scripts/pipeline/cadence.py (p2-06).

Probes are NOT exercised here — they hit live EDGAR and belong in a
manual integration sweep. These tests cover config completeness, the
staleness tri-state, the next-expected date helpers, and the
expected-delta anomaly detector.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.cadence import (  # noqa: E402
    PIPELINE_CADENCE,
    check_expected_delta,
    get_staleness,
    next_13f_deadline,
    next_adv_deadline,
    next_ncen_batch_date,
    next_nport_public_date,
    next_trading_day,
)


# ---------------------------------------------------------------------------
# Config completeness
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "display_name",
    "stale_threshold_days",
    "target_table",
    "expected_delta",
    "next_expected_fn",
    "probe_fn",
    "cadence",
    "filing_form",
}


def test_all_pipelines_have_required_keys():
    assert PIPELINE_CADENCE, "PIPELINE_CADENCE must not be empty"
    for name, cfg in PIPELINE_CADENCE.items():
        missing = REQUIRED_KEYS - set(cfg.keys())
        assert not missing, f"{name} missing keys: {missing}"
        assert isinstance(cfg["display_name"], str) and cfg["display_name"]
        assert isinstance(cfg["stale_threshold_days"], int)
        assert cfg["stale_threshold_days"] > 0
        assert isinstance(cfg["target_table"], str) and cfg["target_table"]
        assert isinstance(cfg["expected_delta"], dict)


# ---------------------------------------------------------------------------
# Staleness tri-state
# ---------------------------------------------------------------------------

def test_staleness_green():
    # Age ≈ 0 → well under 50% of any threshold → green.
    assert get_staleness("13f_holdings", datetime.utcnow()) == "green"


def test_staleness_yellow():
    threshold = PIPELINE_CADENCE["13f_holdings"]["stale_threshold_days"]
    # 60% of threshold → yellow band.
    age = int(0.6 * threshold)
    last = datetime.utcnow() - timedelta(days=age)
    assert get_staleness("13f_holdings", last) == "yellow"


def test_staleness_red():
    threshold = PIPELINE_CADENCE["13f_holdings"]["stale_threshold_days"]
    # Exactly at threshold → red (boundary is inclusive).
    last = datetime.utcnow() - timedelta(days=threshold + 1)
    assert get_staleness("13f_holdings", last) == "red"


# ---------------------------------------------------------------------------
# Next-expected date helpers
# ---------------------------------------------------------------------------

def test_next_13f_deadline_returns_future_date():
    today = date.today()
    result = next_13f_deadline(today)
    assert isinstance(result, date)
    assert result >= today


def test_next_13f_deadline_45_days_after_quarter_end():
    # 2026-04-22 → most recent quarter end is 2026-03-31 → deadline 2026-05-15.
    result = next_13f_deadline(date(2026, 4, 22))
    assert result == date(2026, 5, 15)


def test_next_nport_public_date_60_day_lag():
    # 2026-04-22 → last month end 2026-03-31 → 60 days later 2026-05-30.
    result = next_nport_public_date(date(2026, 4, 22))
    assert result == date(2026, 5, 30)


def test_next_trading_day_skips_weekends():
    # Friday 2026-04-24 → next is Monday 2026-04-27.
    friday = date(2026, 4, 24)
    assert friday.weekday() == 4
    nxt = next_trading_day(friday)
    assert nxt.weekday() == 0
    assert nxt == date(2026, 4, 27)


def test_next_trading_day_skips_new_years():
    # 2025-12-31 → skip Jan 1 (holiday) → Jan 2, 2026 (Friday).
    assert next_trading_day(date(2025, 12, 31)) == date(2026, 1, 2)


def test_next_adv_deadline_rolls_over():
    # After March 31 → rolls to next year.
    assert next_adv_deadline(date(2026, 4, 1)) == date(2027, 3, 31)
    # Before March 31 → current year.
    assert next_adv_deadline(date(2026, 2, 15)) == date(2026, 3, 31)


def test_next_ncen_batch_date_roughly_90_days():
    today = date(2026, 4, 22)
    result = next_ncen_batch_date(today)
    assert result == today + timedelta(days=90)


# ---------------------------------------------------------------------------
# Expected-delta anomaly detection
# ---------------------------------------------------------------------------

def test_check_expected_delta_no_anomalies():
    summary = {
        "row_count": 3_000_000,
        "prior_row_count": 2_900_000,
        "filer_count": 5_200,
        "prior_filer_count": 5_100,
        "new_pending_count": 10,
    }
    assert check_expected_delta("13f_holdings", summary) == []


def test_check_expected_delta_flags_outlier_row_count():
    # 10M is well above max_rows=4M for 13F — must be flagged.
    summary = {
        "row_count": 10_000_000,
        "prior_row_count": 3_000_000,
    }
    out = check_expected_delta("13f_holdings", summary)
    assert out, "expected at least one anomaly"
    assert any("max_rows" in a for a in out)


def test_check_expected_delta_flags_row_delta_outside_range():
    # +50% vs prior quarter — outside ±20% band.
    summary = {
        "row_count": 3_000_000,
        "prior_row_count": 2_000_000,
    }
    out = check_expected_delta("13f_holdings", summary)
    assert any("row_delta_vs_prior" in a for a in out)


def test_check_expected_delta_empty_for_pipelines_without_ranges():
    # ncen_advisers has expected_delta={} → never flags.
    assert check_expected_delta("ncen_advisers", {"row_count": 999}) == []


def test_check_expected_delta_flags_new_pending():
    summary = {
        "row_count": 3_000_000,
        "prior_row_count": 2_900_000,
        "new_pending_count": 250,
    }
    out = check_expected_delta("13f_holdings", summary)
    assert any("new_pending_count" in a for a in out)
