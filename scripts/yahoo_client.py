#!/usr/bin/env python3
"""
yahoo_client.py — Direct Yahoo Finance API client via curl_cffi.

Bypasses yfinance entirely — yfinance 1.2.0 ignores passed sessions and its
internal requests get rate-limited. Raw curl_cffi with browser impersonation
hits the same Yahoo endpoints without rate limits.

Endpoints used:
  /v7/finance/quote          — batch quote (price + market_cap, ~200 symbols/call)
  /v10/finance/quoteSummary  — full metadata per symbol (float, sector, 52w, ...)
  /v8/finance/chart          — historical prices for a single symbol

Public API:
  client = YahooClient()
  client.fetch_quote_batch(["AAPL","MSFT",...]) -> dict[sym, quote_dict]
  client.fetch_metadata(symbol)                 -> metadata_dict | None
  client.fetch_history(symbol, start, end)      -> list[(date, close)]
"""

import time
from typing import Iterable, Optional

from curl_cffi import requests as cr


_QUOTE_URL   = "https://query1.finance.yahoo.com/v7/finance/quote"
_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_CHART_URL   = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_CRUMB_URL   = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_COOKIE_SEED = "https://fc.yahoo.com"

_SUMMARY_MODULES = "price,summaryDetail,defaultKeyStatistics,assetProfile"


class YahooClient:
    """Thin Yahoo Finance client. One instance per run — holds session + crumb."""

    def __init__(self, impersonate: str = "chrome", timeout: int = 15):
        self.session = cr.Session(impersonate=impersonate)
        self.timeout = timeout
        self._crumb: Optional[str] = None
        self._refresh_crumb()

    # ----- internals --------------------------------------------------------

    def _refresh_crumb(self) -> None:
        self.session.get(_COOKIE_SEED, timeout=self.timeout)  # seed cookie
        r = self.session.get(_CRUMB_URL, timeout=self.timeout)
        r.raise_for_status()
        crumb = r.text.strip()
        if not crumb or "<html" in crumb.lower():
            raise RuntimeError(f"Failed to obtain Yahoo crumb: {crumb[:100]}")
        self._crumb = crumb

    class NotFound(Exception):
        """Symbol not found (Yahoo returns 404 or empty result)."""

    def _get_json(self, url: str, params: dict, retries: int = 2) -> dict:
        """GET with retry on transient errors. Raises NotFound on 404 (no retry)."""
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 404:
                    raise YahooClient.NotFound(url)
                if r.status_code == 401:
                    # Crumb expired — refresh once and retry
                    self._refresh_crumb()
                    params = {**params, "crumb": self._crumb} if "crumb" in params else params
                    continue
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except YahooClient.NotFound:
                raise
            except Exception as e:
                last_err = e
                time.sleep(0.3 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed after {retries + 1} attempts: {last_err}")

    # ----- public API -------------------------------------------------------

    def fetch_quote_batch(self, symbols: Iterable[str]) -> dict:
        """Batch quote lookup. Up to ~200 symbols per call.

        Returns dict[symbol] -> {
            price, market_cap, shares_outstanding, currency, exchange,
            fifty_two_week_high, fifty_two_week_low, avg_volume_30d,
        }. Missing symbols are simply absent from the result dict.
        """
        symbols = list(symbols)
        if not symbols:
            return {}
        params = {"symbols": ",".join(symbols), "crumb": self._crumb}
        data = self._get_json(_QUOTE_URL, params)
        out = {}
        for row in (data.get("quoteResponse", {}).get("result") or []):
            sym = row.get("symbol")
            if not sym:
                continue
            out[sym] = {
                "price":                row.get("regularMarketPrice"),
                "market_cap":           row.get("marketCap"),
                "shares_outstanding":   row.get("sharesOutstanding"),
                "currency":             row.get("currency"),
                "exchange":             row.get("fullExchangeName") or row.get("exchange"),
                "fifty_two_week_high":  row.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low":   row.get("fiftyTwoWeekLow"),
                "avg_volume_30d":       row.get("averageDailyVolume3Month"),
                "short_name":           row.get("shortName"),
                "long_name":            row.get("longName"),
                "quote_type":           row.get("quoteType"),
            }
        return out

    def fetch_metadata(self, symbol: str) -> Optional[dict]:
        """Full metadata for a single symbol via quoteSummary.

        Returns None if the symbol is not found. Includes float_shares, sector,
        industry — fields not available from the batch /v7/quote endpoint.
        """
        url = _SUMMARY_URL.format(symbol=symbol)
        params = {"modules": _SUMMARY_MODULES, "crumb": self._crumb}
        try:
            data = self._get_json(url, params)
        except YahooClient.NotFound:
            return None
        except Exception:
            return None
        results = data.get("quoteSummary", {}).get("result") or []
        if not results:
            return None
        r = results[0]
        price = r.get("price") or {}
        stats = r.get("defaultKeyStatistics") or {}
        summary = r.get("summaryDetail") or {}
        profile = r.get("assetProfile") or {}

        def raw(d, key):
            v = d.get(key)
            if isinstance(v, dict):
                return v.get("raw")
            return v

        return {
            "symbol":               symbol,
            "price":                raw(price, "regularMarketPrice"),
            "market_cap":           raw(price, "marketCap"),
            "float_shares":         raw(stats, "floatShares"),
            "shares_outstanding":   raw(stats, "sharesOutstanding"),
            "fifty_two_week_high":  raw(summary, "fiftyTwoWeekHigh"),
            "fifty_two_week_low":   raw(summary, "fiftyTwoWeekLow"),
            "avg_volume_30d":       raw(summary, "averageVolume"),
            "sector":               profile.get("sector"),
            "industry":             profile.get("industry"),
            "exchange":             price.get("exchangeName") or price.get("exchange"),
            "currency":             price.get("currency"),
            "quote_type":           price.get("quoteType"),
            "short_name":           price.get("shortName"),
            "long_name":            price.get("longName"),
        }

    def fetch_history(self, symbol: str, start: int, end: int, interval: str = "1d") -> list:
        """Historical closes for one symbol. start/end are unix timestamps."""
        url = _CHART_URL.format(symbol=symbol)
        params = {"period1": start, "period2": end, "interval": interval}
        try:
            data = self._get_json(url, params)
        except Exception:
            return []
        results = data.get("chart", {}).get("result") or []
        if not results:
            return []
        r = results[0]
        timestamps = r.get("timestamp") or []
        closes = (r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        return [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]


if __name__ == "__main__":
    # Smoke test
    import sys
    c = YahooClient()
    syms = sys.argv[1:] or ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "TSLA", "AMZN"]
    print(f"quote batch: {len(syms)} symbols")
    q = c.fetch_quote_batch(syms)
    for s in syms:
        quote = q.get(s, {})
        print(f"  {s:8} {quote.get('price')!s:>10}  cap={quote.get('market_cap')}")
    print("\nmetadata AAPL:")
    m = c.fetch_metadata("AAPL")
    if m:
        for k, val in m.items():
            print(f"  {k}: {val}")
