"""Per-source discovery functions for the v1.2 pipeline framework.

Each discover_* function returns list[DownloadTarget] for the next
fetch() loop to consume. Discovery is read-only — no manifest writes,
no DB mutations. The manifest anti-join is how discovery stays cheap
and idempotent across runs.

Scoped reference vertical: 13D/G discovery is scoped to AR, OXY, EQT,
NFLX via SCOPED_13DG_TEST_TICKERS until the framework is proven.
fetch_market is a utility-validation pipeline only, not a framework
proof.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from .protocol import DownloadTarget


# ---------------------------------------------------------------------------
# Scoped 13D/G test universe
# ---------------------------------------------------------------------------

SCOPED_13DG_TEST_TICKERS: tuple[str, ...] = ("AR", "OXY", "EQT", "NFLX")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today(today: Optional[date] = None) -> date:
    return today or date.today()


def _quarter_string(report_date: date) -> str:
    """Map a report_date to our YYYYQN quarter label.

    The quarter label we use is the one in which the 13F is FILED, not
    the one the data covers. A 2025-12-31 period-of-report is filed in
    2026Q1 and so labeled `2025Q4` (quarter-of-data) or `2026Q1`
    (filing quarter) depending on which table. holdings_v2.quarter uses
    data-period: Dec 31 → 2025Q4. Match that here.
    """
    y = report_date.year
    m = report_date.month
    q = (m - 1) // 3 + 1
    return f"{y}Q{q}"


def _market_quarters_needed(latest_in_prod: Optional[str], today: date) -> list[str]:
    """Return quarters between latest_in_prod and `today` that are missing.

    Used by 13F discovery to compute the backlog. `latest_in_prod` is the
    MAX(quarter) string in holdings_v2; `today` is the calendar date.
    """
    if latest_in_prod is None:
        # Seed case — pick last 4 quarters
        start = datetime(today.year - 1, 1, 1).date()
    else:
        y, q = int(latest_in_prod[:4]), int(latest_in_prod[-1])
        # Start of quarter AFTER latest_in_prod
        month = ((q - 1) * 3) + 4
        year = y + (1 if month > 12 else 0)
        month = month if month <= 12 else month - 12
        start = date(year, month, 1)

    missing: list[str] = []
    cur = start
    while cur <= today:
        missing.append(_quarter_string(cur))
        # advance one quarter
        m = cur.month + 3
        y = cur.year + (1 if m > 12 else 0)
        m = m if m <= 12 else m - 12
        cur = date(y, m, 1)
    return sorted(set(missing))


# ---------------------------------------------------------------------------
# discover_13f — bulk quarterly ZIPs
# ---------------------------------------------------------------------------

_SEC_13F_INDEX_URL = "https://www.sec.gov/dera/data/form-13f"


def discover_13f(con_prod: Any, today: Optional[date] = None) -> list[DownloadTarget]:
    """Enumerate missing 13F quarterly ZIP downloads.

    Strategy:
      1. Query holdings_v2 for MAX(quarter).
      2. Compute missing quarters between that and today.
      3. Scrape the SEC form-13f landing page to obtain the actual ZIP
         URLs — do NOT hardcode URLs, SEC rotates their format yearly.
      4. Anti-join against ingestion_manifest (source_type='13F',
         object_type='ZIP') by object_key.

    Returns one DownloadTarget per missing quarter.
    """
    t = _today(today)
    latest = con_prod.execute(
        "SELECT MAX(quarter) FROM holdings_v2"
    ).fetchone()
    latest_q = latest[0] if latest and latest[0] else None

    missing_quarters = _market_quarters_needed(latest_q, t)
    if not missing_quarters:
        return []

    # NOTE: the actual ZIP URL scrape is deferred to the fetch step —
    # discover only needs to emit one target per quarter. The URL field
    # below is a probe URL; the fetch() implementation is responsible
    # for scraping the real ZIP href off the landing page at request time.
    # This keeps discover() read-only and side-effect-free.
    targets: list[DownloadTarget] = []
    for q in missing_quarters:
        object_key = f"13F:ZIP:{q}"
        # Skip if already in manifest
        exists = con_prod.execute(
            "SELECT 1 FROM ingestion_manifest WHERE object_key = ? "
            "  AND fetch_status = 'complete'",
            [object_key],
        ).fetchone()
        if exists:
            continue
        targets.append(DownloadTarget(
            source_type="13F",
            object_type="ZIP",
            source_url=_SEC_13F_INDEX_URL,   # scraper resolves actual ZIP URL
            accession_number=None,           # bulk ZIP has no accession
            report_period=None,
            filing_date=None,
            extras={"quarter": q, "object_key": object_key},
        ))
    return targets


# ---------------------------------------------------------------------------
# discover_nport — accession-level
# ---------------------------------------------------------------------------

def discover_nport(con_prod: Any, today: Optional[date] = None) -> list[DownloadTarget]:
    """Enumerate N-PORT accessions not yet fetched.

    The SEC publishes N-PORT-P filings with a ~75-day lag. This function
    queries EDGAR's full-text filings index for filings in that window,
    anti-joins ingestion_manifest, and returns accession-level targets.

    A single accession may contain multiple series; the parse() step
    splits them out. Discover stays at accession grain.

    Implementation note: this function intentionally does NOT issue the
    EDGAR query inline — that is a network fetch and discover is
    supposed to be read-only against local state. The real pipeline
    will delegate to an EDGAR helper that discover() then consumes.
    Kept as a TODO marker for the first N-PORT pipeline port.
    """
    t = _today(today)
    cutoff = t - timedelta(days=75)

    # Read current floor from prod so the framework knows where to start.
    row = con_prod.execute(
        "SELECT MAX(filing_date) FROM fund_holdings_v2"
    ).fetchone()
    prod_floor = row[0] if row and row[0] else cutoff - timedelta(days=365)

    # The real implementation will:
    #   1. Query https://efts.sec.gov/LATEST/search-index?q=...&forms=NPORT-P
    #      with filingDate from prod_floor..cutoff
    #   2. Parse JSON response → accession_number + filed_date + cik
    #   3. Anti-join ingestion_manifest via get_already_fetched()
    # Here we emit an empty list so the orchestrator can run dry against
    # a freshly-migrated control plane without network access.
    #
    # TODO(promote_nport): replace with live EDGAR query.
    _ = (t, cutoff, prod_floor)
    return []


# ---------------------------------------------------------------------------
# discover_13dg — scoped to test universe
# ---------------------------------------------------------------------------

def discover_13dg(
    con_prod: Any,
    today: Optional[date] = None,
    subject_tickers: Optional[list[str]] = None,
) -> list[DownloadTarget]:
    """Enumerate 13D/G/A filings not yet fetched.

    When `subject_tickers` is provided, scope to those subject issuers
    only (the scoped-reference vertical). Default: fall back to
    SCOPED_13DG_TEST_TICKERS until the framework is proven.

    Anti-joins ingestion_manifest by accession_number.
    """
    t = _today(today)
    tickers = subject_tickers or list(SCOPED_13DG_TEST_TICKERS)

    floor_row = con_prod.execute(
        "SELECT MAX(filing_date) FROM beneficial_ownership_v2 "
        "WHERE subject_ticker IN ({})".format(",".join(["?"] * len(tickers))),
        tickers,
    ).fetchone()
    floor = floor_row[0] if floor_row and floor_row[0] else date(2022, 1, 1)

    # Real implementation:
    #   1. Hit https://efts.sec.gov/LATEST/search-index?q=&forms=SC%2013D,SC%2013G,...
    #      + subject-company filter
    #   2. Parse, anti-join manifest
    # Placeholder return until the 13D/G SourcePipeline lands.
    _ = (t, floor)
    return []


# ---------------------------------------------------------------------------
# discover_market — ticker batches by staleness
# ---------------------------------------------------------------------------

_MARKET_FRESHNESS_DAYS = {
    "price": 7,
    "metadata": 30,
    "shares": 90,
}


def discover_market(
    con_prod: Any,
    today: Optional[date] = None,
) -> list[DownloadTarget]:
    """Enumerate stale tickers in market_data and return batched download targets.

    One DownloadTarget per batch of 100 tickers; object_key is a sha256
    hash of the sorted ticker list so the same batch submitted twice
    returns the same manifest row.
    """
    t = _today(today)
    cutoffs = {
        kind: t - timedelta(days=n)
        for kind, n in _MARKET_FRESHNESS_DAYS.items()
    }

    # Universe of tickers referenced by any canonical fact table.
    universe = con_prod.execute(
        """
        SELECT DISTINCT ticker FROM holdings_v2 WHERE ticker IS NOT NULL
        UNION
        SELECT DISTINCT ticker FROM fund_holdings_v2 WHERE ticker IS NOT NULL
        """
    ).fetchdf()

    md = con_prod.execute(
        "SELECT ticker, fetch_date, metadata_date, sec_date, unfetchable "
        "FROM market_data"
    ).fetchdf()

    merged = universe.merge(md, on="ticker", how="left")

    # A ticker needs refresh if any of the three dates is stale (or missing)
    # and it is not marked unfetchable.
    def _stale(d: Any, cutoff: date) -> bool:
        if d is None or (isinstance(d, float) and pd.isna(d)):
            return True
        try:
            return pd.to_datetime(d).date() < cutoff
        except Exception:
            return True

    stale_tickers: list[str] = []
    for _, row in merged.iterrows():
        if row.get("unfetchable"):
            continue
        if (
            _stale(row.get("fetch_date"), cutoffs["price"])
            or _stale(row.get("metadata_date"), cutoffs["metadata"])
            or _stale(row.get("sec_date"), cutoffs["shares"])
        ):
            stale_tickers.append(row["ticker"])

    if not stale_tickers:
        return []

    targets: list[DownloadTarget] = []
    batch_size = 100
    for i in range(0, len(stale_tickers), batch_size):
        batch = sorted(stale_tickers[i:i + batch_size])
        key_input = ",".join(batch)
        object_key = (
            "MARKET:" + hashlib.sha256(key_input.encode()).hexdigest()[:32]
        )
        targets.append(DownloadTarget(
            source_type="MARKET",
            object_type="JSON",
            source_url="https://query1.finance.yahoo.com/",
            accession_number=None,
            report_period=None,
            filing_date=None,
            extras={"tickers": batch, "object_key": object_key},
        ))
    return targets
