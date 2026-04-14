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

def discover_nport(
    con_prod: Any,
    today: Optional[date] = None,
    *,
    cik_filter: Optional[list[int]] = None,
    max_per_cik: int = 4,
) -> list[DownloadTarget]:
    """Enumerate N-PORT accessions not yet fetched.

    The SEC publishes N-PORT-P filings with a ~75-day lag. Per-CIK
    discovery (when ``cik_filter`` is provided) calls
    ``edgar.Company(cik).get_filings(form='NPORT-P')`` and returns the
    most recent ``max_per_cik`` filings since the prod floor (max
    ``report_date`` in ``fund_holdings_v2`` for that filer).

    When ``cik_filter`` is None the full-universe path uses
    ``edgar.get_filings(year=Y, quarter=Q, form='NPORT-P')`` for each
    quarter between the prod floor and ``today - 75 days``. That path
    is significantly more expensive — pull the index for each EDGAR
    quarter then anti-join the manifest.

    Anti-joins ``ingestion_manifest`` on ``accession_number`` (regardless
    of which path produced it). Returns accession-level targets;
    series-level splitting happens in parse().
    """
    from edgar import set_identity, Company, get_filings  # local import

    set_identity("13f-research serge.tismen@gmail.com")

    t = _today(today)
    cutoff = t - timedelta(days=75)

    # Manifest anti-join set
    already = set(con_prod.execute(
        "SELECT accession_number FROM ingestion_manifest "
        "WHERE source_type = 'NPORT' AND fetch_status = 'complete'"
    ).fetchdf()["accession_number"].tolist())

    targets: list[DownloadTarget] = []

    if cik_filter:
        # Per-CIK targeted discovery — used by test runs and
        # focused-vertical reruns.
        for raw_cik in cik_filter:
            try:
                company = Company(int(raw_cik))
                filings = company.get_filings(form="NPORT-P")
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  discover_nport: Company({raw_cik}) failed — {exc}",
                      flush=True)
                continue
            if not filings:
                continue
            # Floor for this filer specifically
            floor_row = con_prod.execute(
                "SELECT MAX(report_date) FROM fund_holdings_v2 "
                "WHERE fund_cik = ?",
                [str(raw_cik).zfill(10)],
            ).fetchone()
            floor = floor_row[0] if floor_row and floor_row[0] else None

            def _to_date(v):
                """Coerce edgar's date fields (str or date) to date."""
                if v is None:
                    return None
                if isinstance(v, date):
                    return v
                try:
                    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
                except ValueError:
                    return None

            count = 0
            for f in filings:
                if count >= max_per_cik:
                    break
                acc = f.accession_no
                if acc in already:
                    continue
                period = _to_date(f.period_of_report)
                filed = _to_date(f.filing_date)
                # Skip filings that pre-date our prod floor for this filer
                if floor is not None and period is not None and period < floor:
                    continue
                # Skip filings inside the SEC publication-lag window
                if filed is not None and filed > cutoff:
                    continue
                # Build the L1 artifact URL — primary_doc.xml is the
                # canonical N-PORT XML for the accession
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{int(raw_cik)}/{acc.replace('-', '')}/primary_doc.xml"
                )
                targets.append(DownloadTarget(
                    source_type="NPORT",
                    object_type="XML",
                    source_url=url,
                    accession_number=acc,
                    report_period=period,
                    filing_date=filed,
                    extras={
                        "fund_cik": str(raw_cik).zfill(10),
                        "company_name": company.name,
                    },
                ))
                count += 1
        return targets

    # Full-universe path — iterate EDGAR quarterly indexes between the
    # prod floor and `cutoff`. This loads a large index per quarter; do
    # not call from --test runs.
    floor_row = con_prod.execute(
        "SELECT MAX(filing_date) FROM fund_holdings_v2"
    ).fetchone()
    prod_floor = floor_row[0] if floor_row and floor_row[0] else (
        cutoff - timedelta(days=365)
    )

    # Walk calendar quarters from prod_floor → cutoff
    cur = date(prod_floor.year, ((prod_floor.month - 1) // 3) * 3 + 1, 1)
    end = cutoff
    while cur <= end:
        y, q = cur.year, (cur.month - 1) // 3 + 1
        try:
            q_filings = get_filings(year=y, quarter=q, form="NPORT-P")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  discover_nport: index {y}Q{q} failed — {exc}",
                  flush=True)
        else:
            df = q_filings.data.to_pandas()
            df = df[df["filing_date"] <= cutoff]
            df = df[df["filing_date"] >= prod_floor]
            for _, row in df.iterrows():
                acc = row["accession_number"]
                if acc in already:
                    continue
                cik = int(row["cik"])
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik}/{acc.replace('-', '')}/primary_doc.xml"
                )
                targets.append(DownloadTarget(
                    source_type="NPORT",
                    object_type="XML",
                    source_url=url,
                    accession_number=acc,
                    filing_date=row["filing_date"],
                    extras={"fund_cik": str(cik).zfill(10)},
                ))
        # advance one quarter
        cur = date(
            cur.year + (1 if cur.month >= 10 else 0),
            ((cur.month - 1 + 3) % 12) + 1,
            1,
        )
    return targets


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


_MARKET_MIN_POSITION_USD = 1_000_000  # per-row threshold for the active universe


def _has_table(con: Any, table_name: str) -> bool:
    """Return True when ``table_name`` is readable on ``con``.

    Used to gate the cusip_classifications filter in discover_market()
    so the function remains safe to call pre-Migration-003.
    """
    try:
        con.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
        return True
    except Exception:
        return False


def discover_market(
    con_prod: Any,
    today: Optional[date] = None,
    *,
    print_reduction: bool = True,
    con_write: Optional[Any] = None,
) -> list[DownloadTarget]:
    """Enumerate stale tickers in the CUSIP-anchored active equity universe.

    Filter logic (fixes the 43K-ticker over-broad set from the pre-Batch-2B
    implementation):

      1. Anchor on ``securities.cusip`` — the stable identifier. Ticker
         reuse and renames are tolerated because CUSIPs don't recycle.
      2. Latest quarter of ``holdings_v2`` + latest ``report_month`` of
         ``fund_holdings_v2`` — no stale history.
      3. Equity only — ``holdings_v2`` rows with ``put_call IS NULL/''``
         (excludes options), ``fund_holdings_v2.asset_category IN
         ('EC','EP')`` (common + preferred).
      4. At least one position with ``market_value_usd >= $1M``.
      5. ``securities.ticker`` not null / blank.
      6. Anti-join ``market_data`` on the per-bucket freshness thresholds
         in ``_MARKET_FRESHNESS_DAYS``. When ``con_write`` is provided the
         freshness check uses its ``market_data`` — this is the crash-
         recovery path: writes go to staging, so a restart must see staging
         rows as fresh (otherwise we'd refetch on every restart).

    Returns one DownloadTarget per 100-ticker batch; ``object_key`` is a
    sha256 of the sorted ticker list so the same batch submitted twice
    hits the same manifest row (``get_or_create_manifest_row``).
    """
    t = _today(today)
    cutoffs = {
        kind: t - timedelta(days=n)
        for kind, n in _MARKET_FRESHNESS_DAYS.items()
    }

    # --- Raw universe (pre-filter) --- kept for the logging line
    raw_count = con_prod.execute(
        """
        SELECT COUNT(DISTINCT ticker) FROM (
            SELECT ticker FROM holdings_v2 WHERE ticker IS NOT NULL AND ticker <> ''
            UNION
            SELECT ticker FROM fund_holdings_v2 WHERE ticker IS NOT NULL AND ticker <> ''
        )
        """
    ).fetchone()[0]

    # --- CUSIP-anchored active universe ---
    latest_q = con_prod.execute(
        "SELECT MAX(quarter) FROM holdings_v2"
    ).fetchone()[0]
    latest_m = con_prod.execute(
        "SELECT MAX(report_month) FROM fund_holdings_v2"
    ).fetchone()[0]

    # Additive classification filter — active only when the table exists
    # (pre-Migration-003 DB runs this query unchanged). The LEFT JOIN +
    # WHERE condition keeps unclassified CUSIPs in the universe (safe
    # default) while excluding any CUSIP that has been explicitly marked
    # non-priceable or inactive.
    has_cc = _has_table(con_prod, 'cusip_classifications')
    if has_cc:
        cc_join = "LEFT JOIN cusip_classifications cc ON s.cusip = cc.cusip"
        cc_where = (
            "AND (cc.cusip IS NULL "
            "     OR (cc.is_priceable = TRUE AND cc.is_active = TRUE))"
        )
    else:
        cc_join = ""
        cc_where = ""

    universe = con_prod.execute(
        f"""
        SELECT DISTINCT s.ticker AS ticker FROM (
            SELECT s.ticker, s.cusip
            FROM holdings_v2 h
            JOIN securities s ON h.cusip = s.cusip
            {cc_join}
            WHERE h.quarter = ?
              AND (h.put_call IS NULL OR h.put_call = '')
              AND h.market_value_usd >= ?
              AND s.ticker IS NOT NULL AND s.ticker <> ''
              {cc_where}
            UNION
            SELECT s.ticker, s.cusip
            FROM fund_holdings_v2 fh
            JOIN securities s ON fh.cusip = s.cusip
            {cc_join}
            WHERE fh.report_month = ?
              AND fh.asset_category IN ('EC','EP')
              AND fh.market_value_usd >= ?
              AND s.ticker IS NOT NULL AND s.ticker <> ''
              {cc_where}
        ) s
        """,
        [latest_q, _MARKET_MIN_POSITION_USD, latest_m, _MARKET_MIN_POSITION_USD],
    ).fetchdf()

    filtered_count = len(universe)

    md_source = con_write if con_write is not None else con_prod
    md = md_source.execute(
        "SELECT ticker, fetch_date, metadata_date, sec_date, unfetchable "
        "FROM market_data"
    ).fetchdf()

    merged = universe.merge(md, on="ticker", how="left")

    def _stale(d: Any, cutoff: date) -> bool:
        if d is None or (isinstance(d, float) and pd.isna(d)):
            return True
        try:
            return pd.to_datetime(d).date() < cutoff
        except Exception:  # pylint: disable=broad-except
            return True

    stale_tickers: list[str] = []
    for _, row in merged.iterrows():
        # pandas coerces missing BOOLEAN columns to pd.NA which raises
        # TypeError when truth-tested; compare with `is True` explicitly.
        if row.get("unfetchable") is True:
            continue
        if (
            _stale(row.get("fetch_date"), cutoffs["price"])
            or _stale(row.get("metadata_date"), cutoffs["metadata"])
            or _stale(row.get("sec_date"), cutoffs["shares"])
        ):
            stale_tickers.append(row["ticker"])

    if print_reduction:
        print(
            f"  discover_market: raw_universe={raw_count:,} "
            f"cusip_anchored_active={filtered_count:,} "
            f"stale={len(stale_tickers):,} "
            f"(latest_q={latest_q}, latest_m={latest_m}, "
            f"min_position=${_MARKET_MIN_POSITION_USD:,})",
            flush=True,
        )

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
