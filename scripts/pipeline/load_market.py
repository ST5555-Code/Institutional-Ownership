"""LoadMarketPipeline — SourcePipeline subclass for market_data.

Migrated w2-02 from scripts/fetch_market.py. Daily UPSERT of prices,
market cap, and float from Yahoo Finance + SEC XBRL companyfacts.
Uses the ``direct_write`` amendment strategy — no is_latest flag, no
amendment history. One row per ticker; the promote step DELETEs the
prior row and INSERTs the fresh one.

Scope options:
  {}                        — refresh all stale tickers via
                              scripts.pipeline.discover.discover_market
  {"tickers": ["AAPL",...]} — refresh the listed tickers
  {"stale_days": 7}         — refresh tickers whose fetch_date is older
                              than N days in prod

Untouched prod columns (e.g., legacy ``price_2025Q1`` cached
quarterly fields, ``unfetchable``/``unfetchable_reason``) are
preserved through a LEFT JOIN against attached prod on ``ticker``
inside ``parse()``. Without that COALESCE, direct_write would NULL
them on every refresh.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Optional

import duckdb
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from pipeline.base import (  # noqa: E402
    FetchResult, ParseResult, SourcePipeline,
)
from pipeline.shared import rate_limit  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

YAHOO_DOMAIN = "query1.finance.yahoo.com"
SEC_DOMAIN = "data.sec.gov"

QUOTE_BATCH_SIZE = 150    # Yahoo /v7/quote chunk size
FETCH_BATCH_SIZE = 100    # ticker group per fetch() loop iteration

DEFAULT_STALE_DAYS = 7

# Ordered column list of market_data (prod schema). Must match the
# staging DDL below and the INSERT column list in parse().
_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("ticker",              "VARCHAR"),
    ("price_live",          "DOUBLE"),
    ("market_cap",          "DOUBLE"),
    ("float_shares",        "DOUBLE"),
    ("shares_outstanding",  "DOUBLE"),
    ("fifty_two_week_high", "DOUBLE"),
    ("fifty_two_week_low",  "DOUBLE"),
    ("avg_volume_30d",      "DOUBLE"),
    ("sector",              "VARCHAR"),
    ("industry",            "VARCHAR"),
    ("exchange",            "VARCHAR"),
    ("fetch_date",          "VARCHAR"),
    ("price_2025Q1",        "INTEGER"),
    ("price_2025Q2",        "INTEGER"),
    ("price_2025Q3",        "INTEGER"),
    ("price_2025Q4",        "INTEGER"),
    ("unfetchable",         "BOOLEAN"),
    ("unfetchable_reason",  "VARCHAR"),
    ("metadata_date",       "VARCHAR"),
    ("sec_date",            "VARCHAR"),
    ("public_float_usd",    "DOUBLE"),
    ("shares_as_of",        "VARCHAR"),
    ("shares_form",         "VARCHAR"),
    ("shares_filed",        "VARCHAR"),
    ("shares_source_tag",   "VARCHAR"),
    ("cik",                 "VARCHAR"),
]

_MARKET_DATA_STAGING_DDL = (
    "CREATE TABLE market_data (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)

_STG_YAHOO_RAW_DDL = """
CREATE TABLE stg_market_yahoo_raw (
    ticker              VARCHAR,
    price_live          DOUBLE,
    float_shares        DOUBLE,
    fifty_two_week_high DOUBLE,
    fifty_two_week_low  DOUBLE,
    avg_volume_30d      DOUBLE,
    sector              VARCHAR,
    industry            VARCHAR,
    exchange            VARCHAR,
    fetch_date          VARCHAR,
    metadata_date       VARCHAR
)
"""

_STG_SEC_RAW_DDL = """
CREATE TABLE stg_market_sec_raw (
    ticker             VARCHAR,
    cik                VARCHAR,
    shares_outstanding DOUBLE,
    shares_as_of       VARCHAR,
    shares_form        VARCHAR,
    shares_filed       VARCHAR,
    shares_source_tag  VARCHAR,
    public_float_usd   DOUBLE,
    sec_date           VARCHAR
)
"""


# ---------------------------------------------------------------------------
# Unfetchable classifier — pre-HTTP filter for tickers Yahoo cannot price.
# ---------------------------------------------------------------------------

_BOND_RE = re.compile(r"\s")
_WARRANT_RE = re.compile(r"(?:^|[^A-Z])(WT|WTS|WS|/WS|-WT|-W)$")
_PREF_RE = re.compile(r"-P[A-Z]?$|^.*-P$")
_CLASS_MARK = re.compile(r"\*$")
_FX_SUFFIX = re.compile(r"(?:USD|EUR|GBP|JPY|CAD|CHF|AUD)$")


def classify_unfetchable(ticker: str) -> Optional[str]:
    """Return a short reason string if the ticker is unfetchable, else None."""
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

def fetch_yahoo_batch(client: Any, tickers: list[str]) -> pd.DataFrame:
    """Fetch Yahoo quote + metadata for a batch. Returns a DataFrame keyed
    by ticker with the Yahoo-owned fields. Validation-only columns
    (``_long_name`` etc.) from the legacy fetch_market.py are omitted.
    """
    if not tickers:
        return pd.DataFrame()
    today = datetime.now().strftime("%Y-%m-%d")

    quotes: dict[str, dict[str, Any]] = {}
    for i in range(0, len(tickers), QUOTE_BATCH_SIZE):
        chunk = tickers[i:i + QUOTE_BATCH_SIZE]
        rate_limit(YAHOO_DOMAIN)
        try:
            quotes.update(client.fetch_quote_batch(chunk))
        except Exception:  # noqa: BLE001  # nosec B112  # one bad batch must not kill the whole run
            continue

    metadata: dict[str, dict[str, Any]] = {}
    for sym in tickers:
        rate_limit(YAHOO_DOMAIN)
        try:
            m = client.fetch_metadata(sym)
        except Exception:  # noqa: BLE001  # nosec B112  # one bad ticker must not kill the whole batch
            continue
        if m:
            metadata[sym] = m

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
            "fifty_two_week_low":  q.get("fifty_two_week_low") or m.get("fifty_two_week_low"),
            "avg_volume_30d":      q.get("avg_volume_30d") or m.get("avg_volume_30d"),
            "sector":              m.get("sector"),
            "industry":            m.get("industry"),
            "exchange":            m.get("exchange") or q.get("exchange"),
            "fetch_date":          today,
            "metadata_date":       today if m else None,
        })
    return pd.DataFrame(rows)


def fetch_sec_batch(client: Any, tickers: list[str]) -> pd.DataFrame:
    """Fetch SEC XBRL shares_outstanding + public_float for one batch."""
    if not tickers:
        return pd.DataFrame()
    today = datetime.now().strftime("%Y-%m-%d")

    rows: list[dict[str, Any]] = []
    for t in tickers:
        rate_limit(SEC_DOMAIN)
        try:
            r = client.fetch(t)
        except Exception:  # noqa: BLE001  # nosec B112  # one bad ticker must not kill the whole batch
            continue
        if r is None or r.get("shares_outstanding") is None:
            continue
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
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# LoadMarketPipeline
# ---------------------------------------------------------------------------

class LoadMarketPipeline(SourcePipeline):
    """SourcePipeline for market_data (Yahoo + SEC XBRL daily UPSERT)."""

    name = "market_data"
    target_table = "market_data"
    amendment_strategy = "direct_write"
    amendment_key = ("ticker",)

    def __init__(
        self,
        *,
        yahoo_client: Any = None,
        sec_client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Clients are injectable so tests can mock without a network call.
        self._yahoo_client = yahoo_client
        self._sec_client = sec_client

    # ---- target_table_spec ---------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": ["ticker"],
            "indexes": [["ticker"]],
        }

    # ---- scope resolution ----------------------------------------------

    def resolve_scope_tickers(self, scope: dict) -> list[str]:
        """Turn a scope dict into a deduped list of uppercase tickers."""
        if "tickers" in scope:
            seen: dict[str, None] = {}
            for t in scope["tickers"]:
                if t:
                    seen.setdefault(t.upper(), None)
            return list(seen)

        prod_ro = duckdb.connect(self._prod_db_path, read_only=True)
        try:
            if "stale_days" in scope:
                n = int(scope["stale_days"])
                rows = prod_ro.execute(
                    "SELECT ticker FROM market_data "
                    "WHERE ticker IS NOT NULL "
                    "  AND unfetchable IS NOT TRUE "
                    "  AND (fetch_date IS NULL "
                    "       OR CAST(fetch_date AS DATE) "
                    f"           < CURRENT_DATE - INTERVAL '{n}' DAY)"
                ).fetchall()
                return [r[0] for r in rows if r[0]]

            # Default: delegate to discover_market for the full stale set
            from pipeline.discover import discover_market  # noqa: WPS433
            targets = discover_market(prod_ro, print_reduction=False)
        finally:
            prod_ro.close()

        seen = {}  # type: ignore[assignment]
        for t in targets:
            for sym in t.extras.get("tickers", []):
                if sym:
                    seen.setdefault(sym.upper(), None)
        return list(seen)

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        t0 = time.monotonic()
        tickers = self.resolve_scope_tickers(scope)

        # Lazy-init HTTP clients unless the caller injected mocks.
        if self._yahoo_client is None:
            from yahoo_client import YahooClient  # noqa: WPS433
            self._yahoo_client = YahooClient()
        if self._sec_client is None:
            from sec_shares_client import SECSharesClient  # noqa: WPS433
            self._sec_client = SECSharesClient()

        # Fresh raw staging tables each fetch — typed DDL so COALESCE in
        # parse() doesn't hit a VARCHAR/DOUBLE mismatch when a batch
        # returned no rows (empty DataFrames register as object/VARCHAR).
        staging_con.execute("DROP TABLE IF EXISTS stg_market_yahoo_raw")
        staging_con.execute("DROP TABLE IF EXISTS stg_market_sec_raw")
        staging_con.execute("DROP TABLE IF EXISTS stg_market_tickers")
        staging_con.execute(_STG_YAHOO_RAW_DDL)
        staging_con.execute(_STG_SEC_RAW_DDL)
        staging_con.execute(
            "CREATE TABLE stg_market_tickers (ticker VARCHAR)"
        )

        # Record every ticker in scope so parse() can emit a row per ticker
        # even when a fetch returns no data (COALESCE against prod).
        if tickers:
            staging_con.executemany(
                "INSERT INTO stg_market_tickers (ticker) VALUES (?)",
                [[t] for t in tickers],
            )

        df_y_all: list[pd.DataFrame] = []
        df_s_all: list[pd.DataFrame] = []
        for i in range(0, len(tickers), FETCH_BATCH_SIZE):
            chunk = tickers[i:i + FETCH_BATCH_SIZE]
            df_y = fetch_yahoo_batch(self._yahoo_client, chunk)
            df_s = fetch_sec_batch(self._sec_client, chunk)
            if not df_y.empty:
                df_y_all.append(df_y)
            if not df_s.empty:
                df_s_all.append(df_s)

        if df_y_all:
            yahoo_df = pd.concat(df_y_all, ignore_index=True)
            staging_con.register("yahoo_df", yahoo_df)
            cols = ", ".join(yahoo_df.columns)
            staging_con.execute(
                f"INSERT INTO stg_market_yahoo_raw ({cols}) "
                f"SELECT {cols} FROM yahoo_df"
            )
            staging_con.unregister("yahoo_df")

        if df_s_all:
            sec_df = pd.concat(df_s_all, ignore_index=True)
            staging_con.register("sec_df", sec_df)
            cols = ", ".join(sec_df.columns)
            staging_con.execute(
                f"INSERT INTO stg_market_sec_raw ({cols}) "
                f"SELECT {cols} FROM sec_df"
            )
            staging_con.unregister("sec_df")

        staging_con.execute("CHECKPOINT")

        return FetchResult(
            run_id="",
            rows_staged=len(tickers),
            raw_tables=[
                "stg_market_tickers",
                "stg_market_yahoo_raw",
                "stg_market_sec_raw",
            ],
            duration_seconds=time.monotonic() - t0,
        )

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        t0 = time.monotonic()

        staging_con.execute("DROP TABLE IF EXISTS market_data")
        staging_con.execute(_MARKET_DATA_STAGING_DDL)

        # Attach prod RO so COALESCE can preserve columns the fetch did
        # not touch (legacy quarterly price caches, unfetchable flags,
        # untouched SEC/Yahoo fields when a batch fails partially).
        staging_con.execute(
            f"ATTACH '{self._prod_db_path}' AS prod_ro (READ_ONLY)"
        )
        try:
            staging_con.execute(
                """
                INSERT INTO market_data (
                    ticker, price_live, market_cap, float_shares,
                    shares_outstanding, fifty_two_week_high, fifty_two_week_low,
                    avg_volume_30d, sector, industry, exchange, fetch_date,
                    price_2025Q1, price_2025Q2, price_2025Q3, price_2025Q4,
                    unfetchable, unfetchable_reason, metadata_date, sec_date,
                    public_float_usd, shares_as_of, shares_form, shares_filed,
                    shares_source_tag, cik
                )
                SELECT
                    t.ticker,
                    COALESCE(y.price_live, p.price_live) AS price_live,
                    CASE
                        WHEN COALESCE(s.shares_outstanding, p.shares_outstanding) IS NOT NULL
                         AND COALESCE(y.price_live, p.price_live) IS NOT NULL
                        THEN COALESCE(s.shares_outstanding, p.shares_outstanding)
                             * COALESCE(y.price_live, p.price_live)
                        ELSE p.market_cap
                    END AS market_cap,
                    COALESCE(y.float_shares, p.float_shares),
                    COALESCE(s.shares_outstanding, p.shares_outstanding),
                    COALESCE(y.fifty_two_week_high, p.fifty_two_week_high),
                    COALESCE(y.fifty_two_week_low, p.fifty_two_week_low),
                    COALESCE(y.avg_volume_30d, p.avg_volume_30d),
                    COALESCE(y.sector, p.sector),
                    COALESCE(y.industry, p.industry),
                    COALESCE(y.exchange, p.exchange),
                    COALESCE(y.fetch_date, p.fetch_date),
                    p.price_2025Q1,
                    p.price_2025Q2,
                    p.price_2025Q3,
                    p.price_2025Q4,
                    p.unfetchable,
                    p.unfetchable_reason,
                    COALESCE(y.metadata_date, p.metadata_date),
                    COALESCE(s.sec_date, p.sec_date),
                    COALESCE(s.public_float_usd, p.public_float_usd),
                    COALESCE(s.shares_as_of, p.shares_as_of),
                    COALESCE(s.shares_form, p.shares_form),
                    COALESCE(s.shares_filed, p.shares_filed),
                    COALESCE(s.shares_source_tag, p.shares_source_tag),
                    COALESCE(s.cik, p.cik)
                FROM stg_market_tickers t
                LEFT JOIN stg_market_yahoo_raw y ON y.ticker = t.ticker
                LEFT JOIN stg_market_sec_raw s ON s.ticker = t.ticker
                LEFT JOIN prod_ro.market_data p ON p.ticker = t.ticker
                """
            )
        finally:
            staging_con.execute("DETACH prod_ro")

        staging_con.execute("CHECKPOINT")

        rows_parsed = staging_con.execute(
            "SELECT COUNT(*) FROM market_data"
        ).fetchone()[0]

        qc_failures: list[dict[str, Any]] = []

        no_data = staging_con.execute(
            "SELECT COUNT(*) FROM market_data WHERE price_live IS NULL"
        ).fetchone()[0]
        if rows_parsed and no_data == rows_parsed:
            qc_failures.append({
                "field": "price_live",
                "rule": "every_ticker_has_null_price",
                "severity": "WARN",
            })

        bad_price = staging_con.execute(
            "SELECT COUNT(*) FROM market_data "
            "WHERE price_live IS NOT NULL AND price_live <= 0"
        ).fetchone()[0]
        if bad_price:
            qc_failures.append({
                "field": "price_live",
                "rule": f"{bad_price}_nonpositive_prices",
                "severity": "FLAG",
            })

        bad_cap = staging_con.execute(
            "SELECT COUNT(*) FROM market_data "
            "WHERE market_cap IS NOT NULL AND market_cap < 0"
        ).fetchone()[0]
        if bad_cap:
            qc_failures.append({
                "field": "market_cap",
                "rule": f"{bad_cap}_negative_market_cap",
                "severity": "FLAG",
            })

        return ParseResult(
            run_id="",
            rows_parsed=int(rows_parsed),
            target_staging_table=self.target_table,
            qc_failures=qc_failures,
            duration_seconds=time.monotonic() - t0,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="market_data pipeline (SourcePipeline / direct_write)",
    )
    parser.add_argument("--tickers", nargs="+",
                        help="Refresh the listed tickers (uppercase).")
    parser.add_argument("--stale-days", type=int, default=None,
                        help="Refresh tickers whose fetch_date is older "
                             "than N days.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print resolved ticker count and exit.")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Skip the approval gate and promote immediately.")
    args = parser.parse_args()

    pipeline = LoadMarketPipeline()

    scope: dict[str, Any] = {}
    if args.tickers:
        scope["tickers"] = args.tickers
    if args.stale_days is not None:
        scope["stale_days"] = args.stale_days

    if args.dry_run:
        tickers = pipeline.resolve_scope_tickers(scope)
        print(f"dry-run: {len(tickers)} tickers in scope (scope={scope})")
        return 0

    run_id = pipeline.run(scope)
    print(f"run_id={run_id} → pending_approval")

    if args.auto_approve:
        result = pipeline.approve_and_promote(run_id)
        print(f"promoted: {result.rows_upserted} rows "
              f"in {result.duration_seconds:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
