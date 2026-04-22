"""Pipeline cadence metadata + EDGAR probe functions (p2-06).

Single source of truth for the admin refresh dashboard. Drives:

  * Stale badge colour (green/yellow/red) on each pipeline card.
  * "Next expected" date shown on each card.
  * "New data available" blue dot via the EDGAR probe functions.
  * Anomaly flags in the diff-review flow (expected_delta ranges).

Design doc §6 and §7 in docs/admin_refresh_system_design.md.

Probes are read-only. They hit EDGAR through sec_fetch() so the shared
rate limiter applies. They do NOT write to the DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from .shared import sec_fetch


# ---------------------------------------------------------------------------
# Staleness tri-state
# ---------------------------------------------------------------------------

def get_staleness(pipeline_name: str, last_refreshed: datetime) -> str:
    """Return 'green', 'yellow', or 'red' based on stale_threshold_days.

    Green:  age < 50% of threshold
    Yellow: age 50% to < 100%
    Red:    age >= threshold
    """
    cfg = PIPELINE_CADENCE[pipeline_name]
    threshold = cfg["stale_threshold_days"]
    now = datetime.utcnow()
    age_days = (now - last_refreshed).total_seconds() / 86400.0
    if age_days < 0.5 * threshold:
        return "green"
    if age_days < threshold:
        return "yellow"
    return "red"


def get_all_staleness(con: Any) -> dict:
    """Read data_freshness for each pipeline's target table.

    Returns {pipeline_name: {"status": "green"|"yellow"|"red"|"missing",
                             "age_days": int|None,
                             "last_refreshed": datetime|None}}
    """
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in PIPELINE_CADENCE.items():
        row = con.execute(
            "SELECT last_computed_at FROM data_freshness WHERE table_name = ?",
            [cfg["target_table"]],
        ).fetchone()
        if not row or row[0] is None:
            out[name] = {
                "status": "missing",
                "age_days": None,
                "last_refreshed": None,
            }
            continue
        last = row[0]
        age_days = int((datetime.utcnow() - last).total_seconds() // 86400)
        out[name] = {
            "status": get_staleness(name, last),
            "age_days": age_days,
            "last_refreshed": last,
        }
    return out


# ---------------------------------------------------------------------------
# Next-expected date calculators
# ---------------------------------------------------------------------------

def _quarter_end(d: date) -> date:
    """Return the last day of the calendar quarter containing `d`."""
    q = (d.month - 1) // 3 + 1
    end_month = q * 3
    if end_month == 3:
        return date(d.year, 3, 31)
    if end_month == 6:
        return date(d.year, 6, 30)
    if end_month == 9:
        return date(d.year, 9, 30)
    return date(d.year, 12, 31)


def _most_recent_quarter_end(today: Optional[date] = None) -> date:
    """Return the most recent calendar quarter end on or before `today`."""
    t = today or date.today()
    qe = _quarter_end(t)
    if qe <= t:
        return qe
    # Roll back one quarter
    month = qe.month - 3
    year = qe.year
    if month < 1:
        month += 12
        year -= 1
    return _quarter_end(date(year, month, 1))


def _month_end(d: date) -> date:
    """Return the last day of the month containing `d`."""
    if d.month == 12:
        return date(d.year, 12, 31)
    first_of_next = date(d.year, d.month + 1, 1)
    return first_of_next - timedelta(days=1)


def _most_recent_month_end(today: Optional[date] = None) -> date:
    t = today or date.today()
    me = _month_end(t)
    if me <= t:
        return me
    if t.month == 1:
        return date(t.year - 1, 12, 31)
    return _month_end(date(t.year, t.month - 1, 1))


def next_13f_deadline(today: Optional[date] = None) -> date:
    """Next 13F filing deadline — 45 days after the most recent quarter end.

    If that deadline has already passed, roll forward to the deadline for
    the current quarter.
    """
    t = today or date.today()
    qe = _most_recent_quarter_end(t)
    deadline = qe + timedelta(days=45)
    if deadline < t:
        # Move to the upcoming quarter end
        month = qe.month + 3
        year = qe.year
        if month > 12:
            month -= 12
            year += 1
        next_qe = _quarter_end(date(year, month, 1))
        return next_qe + timedelta(days=45)
    return deadline


def next_nport_public_date(today: Optional[date] = None) -> date:
    """Next N-PORT public-availability date — 60-day lag from month end."""
    t = today or date.today()
    me = _most_recent_month_end(t)
    pub = me + timedelta(days=60)
    if pub < t:
        # Advance to the upcoming month end + 60
        if me.month == 12:
            next_me = date(me.year + 1, 1, 31)
        else:
            next_month_first = date(me.year, me.month + 1, 1)
            next_me = _month_end(next_month_first)
        return next_me + timedelta(days=60)
    return pub


def next_ncen_batch_date(today: Optional[date] = None) -> date:
    """Approximate N-CEN batch date — rolls in all year.

    Returns today + 90 days as a rough "next sweep" hint.
    """
    t = today or date.today()
    return t + timedelta(days=90)


def next_adv_deadline(today: Optional[date] = None) -> date:
    """ADV annual amendment deadline — 90 days after Dec 31 FYE (March 31).

    Most advisers have a December fiscal year end, so the typical deadline
    is March 31 of each year.
    """
    t = today or date.today()
    march_31 = date(t.year, 3, 31)
    if march_31 < t:
        return date(t.year + 1, 3, 31)
    return march_31


# US federal market holidays that always fall on fixed calendar dates.
_US_FIXED_HOLIDAYS = {(1, 1), (7, 4), (12, 25)}


def next_trading_day(today: Optional[date] = None) -> date:
    """Next US trading day after `today`.

    Skips weekends and a small set of fixed-date federal holidays
    (New Year's Day, Independence Day, Christmas). Floating holidays
    (MLK Day, Memorial Day, Thanksgiving, etc.) are not enumerated — the
    rough estimate is good enough for the admin UI's "next expected" hint.
    """
    t = today or date.today()
    candidate = t + timedelta(days=1)
    for _ in range(10):
        if candidate.weekday() < 5 and (candidate.month, candidate.day) not in _US_FIXED_HOLIDAYS:
            return candidate
        candidate = candidate + timedelta(days=1)
    return candidate


# ---------------------------------------------------------------------------
# EDGAR probes
# ---------------------------------------------------------------------------

_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_PROBE_LOOKBACK_DAYS = 30


def _efts_search(
    forms: list[str] | str,
    since: date,
    until: date,
) -> tuple[int, Optional[str]]:
    """Hit EDGAR full-text search for filings of `forms` between the dates.

    Returns (total_hits, latest_accession_or_none). Raises on HTTP error
    so the probe wrappers can turn it into an error envelope.
    """
    if isinstance(forms, list):
        form_param = ",".join(forms)
    else:
        form_param = forms
    url = (
        f"{_EFTS_SEARCH_URL}?q=&forms={form_param}"
        f"&dateRange=custom&startdt={since:%Y-%m-%d}&enddt={until:%Y-%m-%d}"
    )
    resp, _ = sec_fetch(url)
    data = resp.json()
    total = data.get("hits", {}).get("total", {}).get("value", 0)
    hits = data.get("hits", {}).get("hits", [])
    latest = None
    if hits:
        latest = hits[0].get("_source", {}).get("adsh")
    return int(total), latest


def _manifest_max_filing_date(
    con: Any, source_type: str,
) -> Optional[date]:
    """Return MAX(filing_date) from ingestion_manifest for this source_type,
    or None if the manifest has no rows for it."""
    try:
        row = con.execute(
            "SELECT MAX(filing_date) FROM ingestion_manifest "
            "WHERE source_type = ?",
            [source_type],
        ).fetchone()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    val = row[0]
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _probe_forms(
    con: Any,
    *,
    source_type: str,
    forms: list[str] | str,
) -> dict:
    """Core probe routine shared by every form-based probe_*() function.

    Looks at manifest MAX(filing_date) for this source_type (fallback:
    _PROBE_LOOKBACK_DAYS ago), then hits EDGAR full-text search for any
    filings newer than that. Returns the probe envelope.
    """
    floor = _manifest_max_filing_date(con, source_type)
    today = date.today()
    if floor is None:
        since = today - timedelta(days=_PROBE_LOOKBACK_DAYS)
    else:
        since = floor + timedelta(days=1)
    if since > today:
        return {
            "new_count": 0,
            "latest_accession": None,
            "probed_at": datetime.utcnow(),
        }
    try:
        total, latest = _efts_search(forms, since, today)
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "new_count": -1,
            "latest_accession": None,
            "probed_at": datetime.utcnow(),
            "error": str(exc),
        }
    return {
        "new_count": total,
        "latest_accession": latest,
        "probed_at": datetime.utcnow(),
    }


def probe_13f_accessions(con: Any) -> dict:
    """EDGAR probe for 13F-HR filings newer than our latest."""
    return _probe_forms(con, source_type="13F", forms="13F-HR")


def probe_nport_accessions(con: Any) -> dict:
    """EDGAR probe for NPORT-P filings newer than our latest."""
    return _probe_forms(con, source_type="NPORT", forms="NPORT-P")


def probe_13dg_accessions(con: Any) -> dict:
    """EDGAR probe for 13D/G/A filings newer than our latest."""
    return _probe_forms(
        con,
        source_type="13DG",
        forms=["SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"],
    )


def probe_ncen_accessions(con: Any) -> dict:
    """EDGAR probe for N-CEN filings newer than our latest."""
    return _probe_forms(con, source_type="NCEN", forms="N-CEN")


def probe_adv_filings(con: Any) -> dict:
    """EDGAR probe for Form ADV filings newer than our latest."""
    return _probe_forms(con, source_type="ADV", forms="ADV")


# ---------------------------------------------------------------------------
# Pipeline config
# ---------------------------------------------------------------------------

PIPELINE_CADENCE: dict[str, dict[str, Any]] = {
    "13f_holdings": {
        "display_name": "13F Holdings",
        "filing_form": "13F-HR",
        "cadence": "quarterly",
        "deadline_rule_days": 45,
        "amendment_window_days": 90,
        "stale_threshold_days": 135,
        "target_table": "holdings_v2",
        "next_expected_fn": next_13f_deadline,
        "probe_fn": probe_13f_accessions,
        "expected_delta": {
            "row_delta_vs_prior": (-0.20, 0.20),
            "filer_delta_vs_prior": (-0.10, 0.10),
            "min_rows": 2_000_000,
            "max_rows": 4_000_000,
            "max_new_pending": 100,
        },
    },
    "nport_holdings": {
        "display_name": "N-PORT Holdings",
        "filing_form": "NPORT-P",
        "cadence": "monthly",
        "public_lag_days": 60,
        "stale_threshold_days": 75,
        "target_table": "fund_holdings_v2",
        "next_expected_fn": next_nport_public_date,
        "probe_fn": probe_nport_accessions,
        "expected_delta": {
            "row_delta_vs_prior_month": (-0.15, 0.15),
            "min_rows": 800_000,
            "max_rows": 1_500_000,
        },
    },
    "13dg_ownership": {
        "display_name": "13D/G Ownership",
        "filing_form": ["SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"],
        "cadence": "event_driven",
        "stale_threshold_days": 14,
        "target_table": "beneficial_ownership_v2",
        "next_expected_fn": None,
        "probe_fn": probe_13dg_accessions,
        "expected_delta": {
            "min_rows": 1,
            "max_rows": 5_000,
        },
    },
    "ncen_advisers": {
        "display_name": "N-CEN Advisers",
        "filing_form": "N-CEN",
        "cadence": "annual_rolling",
        "stale_threshold_days": 400,
        "target_table": "ncen_adviser_map",
        "next_expected_fn": next_ncen_batch_date,
        "probe_fn": probe_ncen_accessions,
        "expected_delta": {},
    },
    "adv_registrants": {
        "display_name": "ADV Registrants",
        "filing_form": "Form ADV",
        "cadence": "annual",
        "stale_threshold_days": 400,
        "target_table": "adv_managers",
        "next_expected_fn": next_adv_deadline,
        "probe_fn": probe_adv_filings,
        "expected_delta": {},
    },
    "market_data": {
        "display_name": "Market Data",
        "filing_form": None,
        "cadence": "daily",
        "stale_threshold_days": 3,
        "target_table": "market_data",
        "next_expected_fn": next_trading_day,
        "probe_fn": None,
        "expected_delta": {
            "row_delta_vs_prior_day": (-0.05, 0.05),
            "min_rows": 5_000,
            "max_rows": 7_000,
        },
    },
}


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

_DELTA_KEY_TO_BASELINE = {
    "row_delta_vs_prior": ("row_count", "prior_row_count"),
    "row_delta_vs_prior_month": ("row_count", "prior_row_count"),
    "row_delta_vs_prior_day": ("row_count", "prior_row_count"),
    "filer_delta_vs_prior": ("filer_count", "prior_filer_count"),
}


def _relative_delta(cur: Optional[float], prior: Optional[float]) -> Optional[float]:
    if cur is None or prior in (None, 0):
        return None
    return (cur - prior) / prior


def check_expected_delta(
    pipeline_name: str, diff_summary: dict,
) -> list[str]:
    """Compare a diff_summary against expected_delta for this pipeline.

    diff_summary keys (all optional):
      * row_count, prior_row_count
      * filer_count, prior_filer_count
      * new_pending_count

    Returns a list of anomaly strings. Empty list = all checks pass.
    """
    anomalies: list[str] = []
    ranges = PIPELINE_CADENCE[pipeline_name].get("expected_delta", {})
    if not ranges:
        return anomalies

    row_count = diff_summary.get("row_count")

    min_rows = ranges.get("min_rows")
    if min_rows is not None and row_count is not None and row_count < min_rows:
        anomalies.append(
            f"row_count={row_count:,} below min_rows={min_rows:,}"
        )

    max_rows = ranges.get("max_rows")
    if max_rows is not None and row_count is not None and row_count > max_rows:
        anomalies.append(
            f"row_count={row_count:,} above max_rows={max_rows:,}"
        )

    for range_key, (cur_key, prior_key) in _DELTA_KEY_TO_BASELINE.items():
        bounds = ranges.get(range_key)
        if bounds is None:
            continue
        delta = _relative_delta(
            diff_summary.get(cur_key),
            diff_summary.get(prior_key),
        )
        if delta is None:
            continue
        lo, hi = bounds
        if delta < lo or delta > hi:
            anomalies.append(
                f"{range_key}={delta:+.1%} outside [{lo:+.1%}, {hi:+.1%}]"
            )

    max_new_pending = ranges.get("max_new_pending")
    new_pending = diff_summary.get("new_pending_count")
    if (
        max_new_pending is not None
        and new_pending is not None
        and new_pending > max_new_pending
    ):
        anomalies.append(
            f"new_pending_count={new_pending} above max_new_pending={max_new_pending}"
        )

    return anomalies
