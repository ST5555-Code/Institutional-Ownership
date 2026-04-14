#!/usr/bin/env python3
"""fetch_market.py — DirectWritePipeline for market_data (Yahoo + SEC XBRL).

Rewritten 2026-04-13 (Batch 2A) to implement the DirectWritePipeline
protocol in scripts/pipeline/protocol.py. Proves sec_fetch / rate_limit
/ manifest writes / freshness stamping against a live canonical table.

Data sources:
  1. YahooClient (curl_cffi → query1/query2.finance.yahoo.com)
     - price, 52w high/low, avg volume, sector, industry, exchange,
       float_shares
  2. SECSharesClient (SEC XBRL company facts)
     - shares_outstanding (authoritative, from 10-K/10-Q cover)
     - public_float_usd

Staleness thresholds (match scripts/pipeline/discover._MARKET_FRESHNESS_DAYS):
  - price    : 7 days
  - metadata : 30 days
  - shares   : 90 days

Flags:
  --dry-run         Show what would be fetched. No DB writes of any kind.
  --test            10 tickers from the stale list, writes to staging.
  --staging         Write to staging DB instead of prod.
  --force           Ignore staleness, fetch all candidates in scope.
  --missing-only    Only tickers with no market_data row yet.
  --metadata-only   Only refresh Yahoo metadata for stale/missing.
  --sec-only        Only refresh SEC shares outstanding.
  --limit N         Cap total tickers fetched.

Legacy `UPDATE holdings SET market_value_live` step has been removed —
Group 3 holdings_v2 enrichment is a separate DirectWritePipeline
(`enrich_holdings.py`, Batch 2B) that runs after promote. See
docs/data_layers.md §5 "Option B split contract".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import duckdb
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import (  # noqa: E402
    set_staging_mode, is_staging_mode, get_db_path, get_read_db_path,
    crash_handler,
)
from yahoo_client import YahooClient  # noqa: E402
from sec_shares_client import SECSharesClient  # noqa: E402

from pipeline.discover import discover_market  # noqa: E402
from pipeline.manifest import (  # noqa: E402
    get_or_create_manifest_row,
    update_manifest_status,
    write_impact,
)
from pipeline.protocol import (  # noqa: E402
    DownloadTarget, FetchResult, ValidationReport,
)
from pipeline.shared import rate_limit, stamp_freshness  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRICE_STALE_DAYS = 7
META_STALE_DAYS = 30
SEC_STALE_DAYS = 90

YAHOO_DOMAIN = "query1.finance.yahoo.com"
SEC_DOMAIN = "data.sec.gov"

QUOTE_BATCH_SIZE = 150    # tickers per Yahoo /v7/quote request
CHECKPOINT_EVERY = 500    # §1 — flush WAL every 500 upserted rows

# Coverage gates applied after write_to_canonical:
COVERAGE_BLOCK_PCT = 85.0
COVERAGE_WARN_PCT = 95.0
MARKET_CAP_CEILING = 50_000_000_000_000.0  # 50T — anything above is a data error


# ---------------------------------------------------------------------------
# Schema sanity — idempotent ALTER TABLE for the columns this script owns.
# Kept from the pre-rewrite implementation so running against a pre-2026
# DB still works without out-of-band migration.
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "unfetchable":        "BOOLEAN",
    "unfetchable_reason": "VARCHAR",
    "metadata_date":      "VARCHAR",
    "sec_date":           "VARCHAR",
    "public_float_usd":   "DOUBLE",
    "shares_as_of":       "VARCHAR",
    "shares_form":        "VARCHAR",
    "shares_filed":       "VARCHAR",
    "shares_source_tag":  "VARCHAR",
    "cik":                "VARCHAR",
}


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Idempotent ALTER TABLE — add any missing columns + unique index."""
    try:
        con.execute("SELECT 1 FROM market_data LIMIT 1")
    except duckdb.CatalogException:
        return  # table doesn't exist — first run will create it
    existing = {r[0] for r in con.execute("DESCRIBE market_data").fetchall()}
    for col, typ in REQUIRED_COLUMNS.items():
        if col not in existing:
            con.execute(f"ALTER TABLE market_data ADD COLUMN {col} {typ}")
            print(f"  schema: added {col} {typ}")
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_market_ticker "
        "ON market_data(ticker)"
    )


# ---------------------------------------------------------------------------
# Unfetchable classifier — pre-HTTP filter for things Yahoo cannot price.
# ---------------------------------------------------------------------------

_BOND_RE = re.compile(r"\s")
_WARRANT_RE = re.compile(r"(?:^|[^A-Z])(WT|WTS|WS|/WS|-WT|-W)$")
_PREF_RE = re.compile(r"-P[A-Z]?$|^.*-P$")
_CLASS_MARK = re.compile(r"\*$")
_FX_SUFFIX = re.compile(r"(?:USD|EUR|GBP|JPY|CAD|CHF|AUD)$")


def classify_unfetchable(ticker: str) -> Optional[str]:
    """Return reason string if the ticker is unfetchable, else None."""
    if not ticker:
        return "empty"
    if _BOND_RE.search(ticker):
        return "bond"
    if _WARRANT_RE.search(ticker):
        return "warrant"
    if _PREF_RE.search(ticker):
        return "preferred"
    if _CLASS_MARK.search(ticker):
        return "class_marker"
    if _FX_SUFFIX.search(ticker) and len(ticker) >= 6:
        return "fx_suffix"
    return None


# ---------------------------------------------------------------------------
# Batch fetchers — Yahoo + SEC. Rate-limited per-domain.
# ---------------------------------------------------------------------------

def fetch_yahoo_batch(
    client: YahooClient,
    tickers: list[str],
) -> tuple[pd.DataFrame, int, list[dict[str, Any]]]:
    """Fetch Yahoo quote+metadata for one batch. Returns (df, bytes, errors).

    Calls pipeline.shared.rate_limit(YAHOO_DOMAIN) before each HTTP call.
    """
    if not tickers:
        return pd.DataFrame(), 0, []
    today = datetime.now().strftime("%Y-%m-%d")
    bytes_total = 0
    errors: list[dict[str, Any]] = []

    # Pass 1: batch quote
    quotes: dict[str, dict[str, Any]] = {}
    for i in range(0, len(tickers), QUOTE_BATCH_SIZE):
        chunk = tickers[i:i + QUOTE_BATCH_SIZE]
        rate_limit(YAHOO_DOMAIN)
        try:
            batch_quotes = client.fetch_quote_batch(chunk)
        except Exception as exc:  # pylint: disable=broad-except
            errors.append({"stage": "quote_batch", "chunk_start": i, "error": str(exc)})
            continue
        quotes.update(batch_quotes)
        # curl_cffi responses don't expose byte count cheaply; approximate
        # from quote count (≈200 bytes/symbol for the serialised subset).
        bytes_total += len(batch_quotes) * 200

    # Pass 2: per-symbol metadata
    metadata: dict[str, dict[str, Any]] = {}
    for sym in tickers:
        rate_limit(YAHOO_DOMAIN)
        try:
            m = client.fetch_metadata(sym)
        except Exception as exc:  # pylint: disable=broad-except
            errors.append({"stage": "metadata", "ticker": sym, "error": str(exc)})
            continue
        if m:
            metadata[sym] = m
            bytes_total += 1500  # quoteSummary is ~1-2 KB / symbol

    # Merge quote + metadata → canonical-shape rows.
    # market_cap and shares_outstanding intentionally NOT written here —
    # market_cap is recomputed downstream as SEC shares × Yahoo price.
    rows: list[dict[str, Any]] = []
    for sym in tickers:
        q = quotes.get(sym, {})
        m = metadata.get(sym, {})
        price = q.get("price") or m.get("price")
        if price is None:
            continue
        rows.append({
            "ticker":              sym,
            "price_live":          price,
            "float_shares":        m.get("float_shares"),
            "fifty_two_week_high": q.get("fifty_two_week_high") or m.get("fifty_two_week_high"),
            "fifty_two_week_low":  q.get("fifty_two_week_low")  or m.get("fifty_two_week_low"),
            "avg_volume_30d":      q.get("avg_volume_30d")      or m.get("avg_volume_30d"),
            "sector":              m.get("sector"),
            "industry":            m.get("industry"),
            "exchange":            m.get("exchange") or q.get("exchange"),
            "fetch_date":          today,
            "metadata_date":       today if m else None,
        })
    return pd.DataFrame(rows), bytes_total, errors


def fetch_sec_batch(
    client: SECSharesClient,
    tickers: list[str],
) -> tuple[pd.DataFrame, int, list[dict[str, Any]]]:
    """Fetch SEC XBRL shares_outstanding + public_float for one batch."""
    if not tickers:
        return pd.DataFrame(), 0, []
    today = datetime.now().strftime("%Y-%m-%d")
    bytes_total = 0
    errors: list[dict[str, Any]] = []

    rows: list[dict[str, Any]] = []
    for t in tickers:
        rate_limit(SEC_DOMAIN)
        try:
            r = client.fetch(t)
        except Exception as exc:  # pylint: disable=broad-except
            errors.append({"stage": "sec_xbrl", "ticker": t, "error": str(exc)})
            continue
        if r is None or r.get("shares_outstanding") is None:
            continue
        bytes_total += 2000  # companyfacts payloads are ~1-5 KB cached
        rows.append({
            "ticker":             t,
            "cik":                r["cik"],
            "shares_outstanding": r["shares_outstanding"],
            "shares_as_of":       r.get("shares_as_of"),
            "shares_form":        r.get("shares_form"),
            "shares_filed":       r.get("shares_filed"),
            "shares_source_tag":  r.get("shares_source_tag"),
            "public_float_usd":   r.get("public_float_usd"),
            "sec_date":           today,
        })
    return pd.DataFrame(rows), bytes_total, errors


# ---------------------------------------------------------------------------
# Upsert helpers — preserve Yahoo/SEC field ownership semantics.
# §1 CHECKPOINT every CHECKPOINT_EVERY rows via chunked write.
# ---------------------------------------------------------------------------

def _ensure_rows_exist(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                       date_col: str) -> None:
    """Insert empty rows for any new tickers so UPDATE can target them."""
    con.register("df_new", df[["ticker", date_col]].rename(columns={date_col: "fetch_date"}))
    con.execute(
        "INSERT INTO market_data (ticker, fetch_date) "
        "SELECT ticker, fetch_date FROM df_new "
        "ON CONFLICT (ticker) DO NOTHING"
    )
    con.unregister("df_new")


def upsert_yahoo(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Upsert Yahoo-owned columns. Preserves SEC fields. CHECKPOINT per batch."""
    if df.empty:
        return 0
    written = 0
    for start in range(0, len(df), CHECKPOINT_EVERY):
        chunk = df.iloc[start:start + CHECKPOINT_EVERY]
        _ensure_rows_exist(con, chunk, "fetch_date")
        con.register("df_y", chunk)
        con.execute("""
            UPDATE market_data m SET
                price_live          = d.price_live,
                float_shares        = COALESCE(d.float_shares, m.float_shares),
                fifty_two_week_high = d.fifty_two_week_high,
                fifty_two_week_low  = d.fifty_two_week_low,
                avg_volume_30d      = d.avg_volume_30d,
                sector              = COALESCE(d.sector, m.sector),
                industry            = COALESCE(d.industry, m.industry),
                exchange            = COALESCE(d.exchange, m.exchange),
                fetch_date          = d.fetch_date,
                metadata_date       = COALESCE(d.metadata_date, m.metadata_date)
            FROM df_y d WHERE m.ticker = d.ticker
        """)
        con.unregister("df_y")
        con.execute("CHECKPOINT")
        written += len(chunk)
    return written


def upsert_sec(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Upsert SEC-owned columns. SEC shares_outstanding is authoritative."""
    if df.empty:
        return 0
    written = 0
    for start in range(0, len(df), CHECKPOINT_EVERY):
        chunk = df.iloc[start:start + CHECKPOINT_EVERY]
        _ensure_rows_exist(con, chunk, "sec_date")
        con.register("df_s", chunk)
        con.execute("""
            UPDATE market_data m SET
                shares_outstanding = d.shares_outstanding,
                shares_as_of       = d.shares_as_of,
                shares_form        = d.shares_form,
                shares_filed       = d.shares_filed,
                shares_source_tag  = d.shares_source_tag,
                public_float_usd   = COALESCE(d.public_float_usd, m.public_float_usd),
                cik                = d.cik,
                sec_date           = d.sec_date
            FROM df_s d WHERE m.ticker = d.ticker
        """)
        con.unregister("df_s")
        con.execute("CHECKPOINT")
        written += len(chunk)
    return written


def recompute_market_cap(con: duckdb.DuckDBPyConnection) -> None:
    """market_cap = SEC shares_outstanding × Yahoo price_live. NULL if either missing."""
    con.execute("""
        UPDATE market_data SET market_cap = CASE
            WHEN shares_outstanding IS NOT NULL AND price_live IS NOT NULL
                THEN shares_outstanding * price_live
            ELSE NULL
        END
    """)


# ---------------------------------------------------------------------------
# DirectWritePipeline implementation
# ---------------------------------------------------------------------------

class MarketDataPipeline:
    """DirectWritePipeline for market_data.

    Conforms to scripts.pipeline.protocol.DirectWritePipeline structurally.
    Fetch results are stashed in self._batch_data keyed by manifest_id
    because the FetchResult dataclass does not carry parsed rows; the
    write_to_canonical() step reads from the stash. This is a pragmatic
    split of the fetch / write boundary for a pipeline where the two
    always run in the same process.
    """

    source_type = "MARKET"

    def __init__(self, *, run_id: str, test_mode: bool = False,
                 limit: Optional[int] = None,
                 missing_only: bool = False,
                 metadata_only: bool = False,
                 sec_only: bool = False,
                 force: bool = False) -> None:
        self.run_id = run_id
        self.test_mode = test_mode
        self.limit = limit
        self.missing_only = missing_only
        self.metadata_only = metadata_only
        self.sec_only = sec_only
        self.force = force
        self._batch_data: dict[int, tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]] = {}
        self._yahoo_client: Optional[YahooClient] = None
        self._sec_client: Optional[SECSharesClient] = None

    # --- discover ---------------------------------------------------------

    def discover(self, run_id: str) -> list[DownloadTarget]:
        """Enumerate stale-ticker batches via pipeline.discover.discover_market.

        Applies --test / --limit truncation. Returns [] when nothing is stale.
        Upstream reads (holdings_v2, fund_holdings_v2, market_data) always
        come from prod via get_read_db_path() — staging mode only affects
        where we WRITE, not where we read reference data.
        """
        con = duckdb.connect(get_read_db_path(), read_only=True)
        try:
            targets = discover_market(con)
        finally:
            con.close()

        if not targets:
            return []

        # --test: take first batch and clip to 10 tickers
        if self.test_mode:
            first = targets[0]
            tickers = list(first.extras["tickers"])[:10]
            object_key = f"market_{run_id}_test_{len(tickers)}t"
            return [DownloadTarget(
                source_type="MARKET",
                object_type="price_batch",
                source_url=first.source_url,
                accession_number=None,
                report_period=None,
                filing_date=None,
                extras={"tickers": tickers, "object_key": object_key},
            )]

        # --limit: truncate across batches
        if self.limit:
            running = 0
            trimmed: list[DownloadTarget] = []
            for t in targets:
                if running >= self.limit:
                    break
                remaining = self.limit - running
                batch_tickers = list(t.extras["tickers"])[:remaining]
                trimmed.append(DownloadTarget(
                    source_type=t.source_type,
                    object_type=t.object_type,
                    source_url=t.source_url,
                    accession_number=t.accession_number,
                    report_period=t.report_period,
                    filing_date=t.filing_date,
                    extras={"tickers": batch_tickers,
                            "object_key": t.extras.get("object_key")},
                ))
                running += len(batch_tickers)
            return trimmed
        return targets

    # --- fetch ------------------------------------------------------------

    def fetch(self, target: DownloadTarget, run_id: str) -> FetchResult:
        """Fetch Yahoo + SEC data for one batch. Writes one manifest row."""
        tickers = list(target.extras["tickers"])
        object_key = target.extras.get("object_key") or f"market_{run_id}_{uuid.uuid4().hex[:12]}"

        # Open a connection once per fetch() for the manifest bookkeeping.
        con = duckdb.connect(get_db_path())
        try:
            manifest_id = get_or_create_manifest_row(
                con,
                source_type=self.source_type,
                object_type="price_batch",
                source_url=target.source_url,
                accession_number=None,
                run_id=run_id,
                object_key=object_key,
                fetch_status="fetching",
                fetch_started_at=datetime.now(),
            )
            update_manifest_status(con, manifest_id, "fetching",
                                   fetch_started_at=datetime.now())
            con.execute("CHECKPOINT")

            # Lazy-init HTTP clients
            if self._yahoo_client is None and not self.sec_only:
                self._yahoo_client = YahooClient()
            if self._sec_client is None and not self.metadata_only:
                self._sec_client = SECSharesClient()

            df_y = pd.DataFrame()
            df_s = pd.DataFrame()
            bytes_total = 0
            errors: list[dict[str, Any]] = []

            if not self.sec_only and self._yahoo_client is not None:
                df_y, b_y, e_y = fetch_yahoo_batch(self._yahoo_client, tickers)
                bytes_total += b_y
                errors.extend(e_y)

            if not self.metadata_only and self._sec_client is not None:
                df_s, b_s, e_s = fetch_sec_batch(self._sec_client, tickers)
                bytes_total += b_s
                errors.extend(e_s)

            self._batch_data[manifest_id] = (df_y, df_s, errors)

            update_manifest_status(
                con, manifest_id, "complete",
                fetch_completed_at=datetime.now(),
                source_bytes=bytes_total,
                http_code=200,
                error_message=(json.dumps(errors)[:500] if errors else None),
            )
            con.execute("CHECKPOINT")
        except Exception as exc:
            with contextlib_suppress_then_raise(exc):
                update_manifest_status(
                    con, manifest_id, "failed",
                    fetch_completed_at=datetime.now(),
                    error_message=str(exc)[:500],
                )
                con.execute("CHECKPOINT")
        finally:
            con.close()

        return FetchResult(
            target=target,
            manifest_id=manifest_id,
            local_path=None,
            http_code=200,
            source_bytes=bytes_total,
            source_checksum=None,
            success=True,
            error_message=(json.dumps(errors)[:500] if errors else None),
        )

    # --- write_to_canonical ----------------------------------------------

    def write_to_canonical(self, fetch_result: FetchResult,
                           prod_db_path: str, run_id: str) -> int:
        """Upsert one batch into market_data + write one impact row per ticker."""
        df_y, df_s, errors = self._batch_data.pop(fetch_result.manifest_id)
        tickers = list(fetch_result.target.extras["tickers"])
        error_tickers = {e.get("ticker") for e in errors if e.get("ticker")}

        con = duckdb.connect(prod_db_path)
        try:
            ensure_schema(con)
            written_y = upsert_yahoo(con, df_y)
            written_s = upsert_sec(con, df_s)
            recompute_market_cap(con)
            con.execute("CHECKPOINT")

            # One impact row per ticker. DuckDB's unit_key_json is VARCHAR.
            today = datetime.now().strftime("%Y-%m-%d")
            hit_yahoo = set(df_y["ticker"].tolist()) if not df_y.empty else set()
            hit_sec = set(df_s["ticker"].tolist()) if not df_s.empty else set()
            for t in tickers:
                ok = (t in hit_yahoo) or (t in hit_sec)
                write_impact(
                    con,
                    manifest_id=fetch_result.manifest_id,
                    target_table="market_data",
                    unit_type="ticker_date",
                    unit_key_json=json.dumps({"ticker": t, "as_of_date": today}),
                    report_date=today,
                    rows_staged=1 if ok else 0,
                    load_status="loaded" if ok else "failed",
                    error_message=("no_source_hit" if not ok and t in error_tickers
                                   else None),
                )
            # One extra impact row per ticker for promote accounting
            # (DirectWrite = promote at write time).
            con.execute(
                "UPDATE ingestion_impacts SET promote_status = 'promoted', "
                "rows_promoted = rows_staged, promoted_at = CURRENT_TIMESTAMP "
                "WHERE manifest_id = ?",
                [fetch_result.manifest_id],
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()

        return written_y + written_s

    # --- validate_post_write ---------------------------------------------

    def validate_post_write(self, run_id: str, prod_db_path: str) -> ValidationReport:
        """Coverage + sentinel gates. Logs, never raises.

        Coverage gate only runs in prod mode. In staging / --test mode the
        market_data universe is subset-only; comparing it against prod's
        holdings_v2 ∪ fund_holdings_v2 would always fail the 85% gate
        spuriously. Sentinel gates (bad price / float / cap / stale) run
        against whichever DB we wrote to (prod_db_path).
        """
        con = duckdb.connect(prod_db_path, read_only=True)
        try:
            coverage_pct: Optional[float] = None
            if not is_staging_mode():
                universe = con.execute("""
                    WITH u AS (
                        SELECT DISTINCT ticker FROM holdings_v2 WHERE ticker IS NOT NULL
                        UNION
                        SELECT DISTINCT ticker FROM fund_holdings_v2 WHERE ticker IS NOT NULL
                    )
                    SELECT COUNT(*) FROM u
                """).fetchone()[0]
                covered = con.execute(f"""
                    WITH u AS (
                        SELECT DISTINCT ticker FROM holdings_v2 WHERE ticker IS NOT NULL
                        UNION
                        SELECT DISTINCT ticker FROM fund_holdings_v2 WHERE ticker IS NOT NULL
                    )
                    SELECT COUNT(*) FROM u
                    JOIN market_data md ON md.ticker = u.ticker
                    WHERE md.unfetchable IS NOT TRUE
                      AND md.price_live IS NOT NULL
                      AND CAST(md.fetch_date AS DATE)
                            >= CURRENT_DATE - INTERVAL '{PRICE_STALE_DAYS}' DAY
                """).fetchone()[0]
                coverage_pct = (100.0 * covered / universe) if universe else 0.0

            # Sentinel gates — always run
            bad_price = con.execute(
                "SELECT COUNT(*) FROM market_data "
                "WHERE price_live IS NOT NULL AND price_live <= 0"
            ).fetchone()[0]
            bad_float = con.execute(
                "SELECT COUNT(*) FROM market_data "
                "WHERE float_shares IS NOT NULL AND float_shares <= 0"
            ).fetchone()[0]
            bad_cap = con.execute(
                "SELECT COUNT(*) FROM market_data "
                "WHERE market_cap IS NOT NULL AND market_cap > ?",
                [MARKET_CAP_CEILING],
            ).fetchone()[0]
            stale_price = con.execute(f"""
                SELECT COUNT(*) FROM market_data
                WHERE unfetchable IS NOT TRUE
                  AND (fetch_date IS NULL
                       OR CAST(fetch_date AS DATE)
                           < CURRENT_DATE - INTERVAL '{PRICE_STALE_DAYS}' DAY)
            """).fetchone()[0]
        finally:
            con.close()

        blocks: list[dict[str, Any]] = []
        flags: list[dict[str, Any]] = []
        warns: list[dict[str, Any]] = []

        if coverage_pct is None:
            warns.append({
                "gate": "coverage",
                "message": "skipped (staging/test mode — universe lives in prod, market_data in staging)",
            })
        elif coverage_pct < COVERAGE_BLOCK_PCT:
            blocks.append({
                "gate": "coverage",
                "coverage_pct": round(coverage_pct, 2),
                "threshold": COVERAGE_BLOCK_PCT,
                "message": (f"market_data covers {coverage_pct:.1f}% of holdings_v2 "
                            f"∪ fund_holdings_v2 universe — below {COVERAGE_BLOCK_PCT}% block threshold"),
            })
        elif coverage_pct < COVERAGE_WARN_PCT:
            warns.append({
                "gate": "coverage",
                "coverage_pct": round(coverage_pct, 2),
                "threshold": COVERAGE_WARN_PCT,
            })
        if bad_price:
            flags.append({"gate": "price_nonpositive", "count": bad_price})
        if bad_float:
            flags.append({"gate": "float_nonpositive", "count": bad_float})
        if bad_cap:
            flags.append({"gate": "market_cap_over_50T", "count": bad_cap})
        if stale_price:
            warns.append({"gate": "stale_price_rows", "count": stale_price})

        pass_count = 1 if (coverage_pct is not None and coverage_pct >= COVERAGE_WARN_PCT) else 0

        return ValidationReport(
            run_id=run_id,
            source_type=self.source_type,
            block_count=len(blocks),
            flag_count=len(flags),
            warn_count=len(warns),
            pass_count=pass_count,
            report_path=None,
            blocks=blocks,
            flags=flags,
            warns=warns,
        )

    # --- stamp_freshness --------------------------------------------------

    def stamp_freshness(self, run_id: str, prod_db_path: str) -> None:
        """Upsert data_freshness row for market_data."""
        con = duckdb.connect(prod_db_path)
        try:
            stamp_freshness(con, "market_data")
        finally:
            con.close()


def contextlib_suppress_then_raise(exc: BaseException):
    """Context manager helper: run block, swallow any exception raised inside,
    then re-raise the original exc. Used to record a failed manifest status
    without masking the underlying error that caused the failure."""
    class _Ctx:
        def __enter__(self):
            return self
        def __exit__(self, et, ev, tb):
            # Swallow whatever the cleanup block raised; re-raise original.
            raise exc
    return _Ctx()


# ---------------------------------------------------------------------------
# Top-level orchestration — dry-run, test, full
# ---------------------------------------------------------------------------

def run_dry_run() -> int:
    """Print what discover_market would fetch, without writing anything."""
    print("=" * 60)
    print("fetch_market.py --dry-run — no DB writes")
    print("=" * 60)

    con = duckdb.connect(get_read_db_path(), read_only=True)
    try:
        targets = discover_market(con)
        universe = con.execute("""
            SELECT COUNT(DISTINCT ticker) FROM (
                SELECT ticker FROM holdings_v2 WHERE ticker IS NOT NULL
                UNION
                SELECT ticker FROM fund_holdings_v2 WHERE ticker IS NOT NULL
            )
        """).fetchone()[0]
        staleness = con.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE fetch_date IS NULL
                                      OR CAST(fetch_date AS DATE)
                                           < CURRENT_DATE - INTERVAL '{PRICE_STALE_DAYS}' DAY) AS stale_price,
                COUNT(*) FILTER (WHERE metadata_date IS NULL
                                      OR CAST(metadata_date AS DATE)
                                           < CURRENT_DATE - INTERVAL '{META_STALE_DAYS}' DAY) AS stale_meta,
                COUNT(*) FILTER (WHERE sec_date IS NULL
                                      OR CAST(sec_date AS DATE)
                                           < CURRENT_DATE - INTERVAL '{SEC_STALE_DAYS}' DAY) AS stale_sec,
                COUNT(*) AS total
            FROM market_data
        """).fetchdf()
    finally:
        con.close()

    total_tickers = sum(len(t.extras["tickers"]) for t in targets)
    batches = len(targets)

    print(f"  universe (holdings_v2 ∪ fund_holdings_v2): {universe:,} tickers")
    print()
    print("  staleness in market_data:")
    print(staleness.to_string(index=False))
    print()
    print(f"  discover_market returned {batches:,} batches "
          f"({total_tickers:,} tickers)")
    # At Yahoo 2 req/s with ~2 calls/ticker (quote+metadata), plus SEC at
    # 8 req/s rate-limited:
    yahoo_budget = total_tickers * 2 / 2.0  # seconds
    sec_budget = total_tickers / 8.0
    est_seconds = max(yahoo_budget, sec_budget)
    print(f"  est. fetch time (rate-limited): ~{est_seconds / 60.0:.1f} minutes")
    print()
    print("  (no DB writes performed)")
    return 0


def run_pipeline(*, test_mode: bool, force: bool, missing_only: bool,
                 metadata_only: bool, sec_only: bool,
                 limit: Optional[int]) -> int:
    """Execute discover → fetch → write_to_canonical → validate → stamp."""
    run_id = f"market_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    print("=" * 60)
    print(f"fetch_market.py — DirectWritePipeline  run_id={run_id}")
    print(f"  staging={is_staging_mode()}  test={test_mode}  force={force}")
    print(f"  limit={limit}  missing_only={missing_only}  "
          f"metadata_only={metadata_only}  sec_only={sec_only}")
    print("=" * 60)

    if test_mode:
        # --test implies staging per the Batch 2A spec
        if not is_staging_mode():
            print("  --test forces staging mode (writing to data/13f_staging.duckdb)")
            set_staging_mode(True)
        print("  TEST MODE — clipping to 10 tickers")

    pipeline = MarketDataPipeline(
        run_id=run_id,
        test_mode=test_mode,
        limit=limit,
        missing_only=missing_only,
        metadata_only=metadata_only,
        sec_only=sec_only,
        force=force,
    )

    # 1. Discover
    targets = pipeline.discover(run_id)
    total_tickers = sum(len(t.extras["tickers"]) for t in targets)
    print(f"\n  discovered: {len(targets):,} batch(es), {total_tickers:,} tickers")
    if not targets:
        print("  nothing to fetch — market_data is already fresh.")
        return 0

    # 2. Fetch + write per batch, progress every 100 tickers
    t0 = time.time()
    seen = 0
    total_written = 0
    db_path = get_db_path()
    for i, target in enumerate(targets, start=1):
        batch_tickers = list(target.extras["tickers"])
        print(f"  batch {i}/{len(targets)}: {len(batch_tickers)} tickers "
              f"(first={batch_tickers[0]!r}...) fetching...", flush=True)
        fetch_result = pipeline.fetch(target, run_id)
        rows = pipeline.write_to_canonical(fetch_result, db_path, run_id)
        total_written += rows
        seen += len(batch_tickers)
        elapsed = time.time() - t0
        rate = seen / elapsed if elapsed > 0 else 0
        remaining = max(0, total_tickers - seen)
        eta = remaining / rate if rate > 0 else 0
        if seen % 100 == 0 or i == len(targets):
            print(f"    progress: {seen:,}/{total_tickers:,}  "
                  f"rows_written={total_written:,}  "
                  f"rate={rate:.1f}/s  eta={eta/60.0:.1f}min",
                  flush=True)

    # 3. Validate
    print("\n  validating post-write coverage + sentinels...")
    report = pipeline.validate_post_write(run_id, db_path)
    print(f"    BLOCKS={report.block_count} "
          f"FLAGS={report.flag_count} WARNS={report.warn_count}")
    for b in report.blocks:
        print(f"    BLOCK: {b}")
    for f in report.flags:
        print(f"    FLAG:  {f}")
    for w in report.warns:
        print(f"    WARN:  {w}")

    # 4. Freshness
    pipeline.stamp_freshness(run_id, db_path)

    print(f"\nDone in {(time.time() - t0):.1f}s")
    return 0 if report.block_count == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Market data pipeline (DirectWrite)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched, write nothing.")
    parser.add_argument("--test", action="store_true",
                        help="10 stale tickers, writes to staging DB.")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB instead of prod.")
    parser.add_argument("--force", action="store_true",
                        help="Ignore staleness, fetch all in scope.")
    parser.add_argument("--missing-only", action="store_true",
                        help="Only tickers with no market_data row yet.")
    parser.add_argument("--metadata-only", action="store_true",
                        help="Only refresh Yahoo metadata.")
    parser.add_argument("--sec-only", action="store_true",
                        help="Only refresh SEC shares outstanding.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total tickers fetched.")
    args = parser.parse_args()

    if args.staging:
        set_staging_mode(True)

    if args.dry_run:
        sys.exit(run_dry_run())

    sys.exit(run_pipeline(
        test_mode=args.test,
        force=args.force,
        missing_only=args.missing_only,
        metadata_only=args.metadata_only,
        sec_only=args.sec_only,
        limit=args.limit,
    ))


if __name__ == "__main__":
    crash_handler("fetch_market")(main)
