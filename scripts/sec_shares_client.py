#!/usr/bin/env python3
"""
sec_shares_client.py — Authoritative shares outstanding + public float from SEC XBRL.

Data source: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
Facts used:
  - dei:EntityCommonStockSharesOutstanding  → shares outstanding (from 10-K/10-Q cover)
  - dei:EntityPublicFloat                   → public float in USD (from 10-K cover)

Both are pulled from the registrant's periodic report cover pages and are the
authoritative source. Yahoo's floatShares is sparse and unreliable for small-
caps; this client fills that gap with no rate limits and no API key.

SEC EDGAR requires a descriptive User-Agent with contact email. Max ~10 req/sec.

Public API:
  client = SECSharesClient()
  client.fetch("AAPL") -> {
      "cik": "0000320193",
      "shares_outstanding": 14681140000,
      "shares_as_of": "2026-01-16",
      "shares_form": "10-Q",
      "shares_filed": "2026-01-30",
      "public_float_usd": 2600000000000.0 | None,
      "public_float_as_of": "2024-03-29" | None,
  }
  # or None if ticker not in SEC mapping

Ticker → CIK mapping read from data/reference/sec_company_tickers.csv
(refreshable via scripts/enrich_tickers.py).
"""

import csv
import json
import os
import time
from typing import Optional

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKER_CIK_CSV = os.path.join(BASE_DIR, "data", "reference", "sec_company_tickers.csv")
OVERRIDES_CSV = os.path.join(BASE_DIR, "data", "reference", "shares_overrides.csv")
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache", "sec_companyfacts")

USER_AGENT = "13f-ownership-research serge.tismen@gmail.com"
RATE_LIMIT_SLEEP = 0.11  # ~9 req/sec, under SEC's 10/sec cap
CACHE_MAX_AGE_DAYS = 90  # SEC files update at filing cadence (quarterly)


class SECSharesClient:
    """Fetch shares outstanding and public float from SEC XBRL company facts."""

    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._ticker_to_cik = self._load_ticker_map()
        self._overrides = self._load_overrides()
        self._last_request_ts = 0.0

    def _load_overrides(self) -> dict:
        """Load ticker-level shares_outstanding overrides (for filers with
        broken XBRL tagging like Visa, BRK-A/B). Keyed by ticker."""
        if not os.path.exists(OVERRIDES_CSV):
            return {}
        out = {}
        with open(OVERRIDES_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = (row.get("ticker") or "").strip().upper()
                try:
                    shares = int(float(row.get("shares_outstanding") or 0))
                except ValueError:
                    continue
                if not t or shares <= 0:
                    continue
                out[t] = {
                    "shares_outstanding": shares,
                    "shares_as_of": row.get("as_of") or None,
                    "shares_form":  row.get("form") or None,
                    "shares_source_tag": f"manual_override:{row.get('source') or 'csv'}",
                }
        return out

    # ----- ticker -> cik ----------------------------------------------------

    def _load_ticker_map(self) -> dict:
        if not os.path.exists(TICKER_CIK_CSV):
            raise FileNotFoundError(
                f"{TICKER_CIK_CSV} not found. Run scripts/enrich_tickers.py to refresh."
            )
        m = {}
        with open(TICKER_CIK_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                tkr = (row.get("ticker") or "").strip().upper()
                cik_raw = (row.get("cik") or "").strip()
                if not tkr or not cik_raw:
                    continue
                # SEC expects zero-padded 10-digit CIK
                m[tkr] = f"{int(cik_raw):010d}"
        return m

    def get_cik(self, ticker: str) -> Optional[str]:
        return self._ticker_to_cik.get(ticker.upper())

    # ----- SEC API ---------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_ts
        if elapsed < RATE_LIMIT_SLEEP:
            time.sleep(RATE_LIMIT_SLEEP - elapsed)
        self._last_request_ts = time.time()

    def _cache_path(self, cik: str) -> str:
        return os.path.join(CACHE_DIR, f"CIK{cik}.json")

    def _load_facts(self, cik: str) -> Optional[dict]:
        """Load company facts from cache (if fresh) or SEC API."""
        cache = self._cache_path(cik)
        if os.path.exists(cache):
            age_days = (time.time() - os.path.getmtime(cache)) / 86400
            if age_days < CACHE_MAX_AGE_DAYS:
                try:
                    with open(cache) as f:
                        return json.load(f)
                except Exception:
                    pass  # corrupted → refetch

        self._throttle()
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code == 404:
                # Persist a negative marker so we don't re-hit
                with open(cache, "w") as f:
                    json.dump({"_not_found": True}, f)
                return None
            r.raise_for_status()
            data = r.json()
            with open(cache, "w") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            print(f"  SEC fetch error CIK{cik}: {e}")
            return None

    # ----- extraction ------------------------------------------------------

    @staticmethod
    def _latest_fact(facts: list, max_age_years: int = 2) -> Optional[dict]:
        """Return the most recent XBRL fact by 'end' then 'filed'. Reject facts
        older than max_age_years to avoid stale legacy tags (e.g. BRK's 2011
        single-class fact still present in the feed)."""
        if not facts:
            return None
        latest = sorted(facts, key=lambda x: (x.get("end", ""), x.get("filed", "")))[-1]
        end = latest.get("end") or ""
        if end:
            from datetime import datetime as _dt
            try:
                end_dt = _dt.strptime(end, "%Y-%m-%d")
                age_years = (_dt.now() - end_dt).days / 365.25
                if age_years > max_age_years:
                    return None
            except ValueError:
                pass
        return latest

    def _extract_shares(self, facts_json: dict) -> dict:
        facts = facts_json.get("facts") or {}
        dei = facts.get("dei") or {}
        usgaap = facts.get("us-gaap") or {}
        out = {
            "shares_outstanding": None,
            "shares_as_of": None,
            "shares_form": None,
            "shares_filed": None,
            "shares_source_tag": None,
            "public_float_usd": None,
            "public_float_as_of": None,
        }

        # Preferred: dei:EntityCommonStockSharesOutstanding (single-class filers)
        # Fallback: us-gaap:CommonStockSharesOutstanding (multi-class filers like
        # Alphabet, Meta — the DEI tag is absent, us-gaap holds the total).
        # Some filers only have us-gaap:EntityCommonStockSharesOutstanding. We try
        # all three in order of preference.
        candidates = [
            ("dei:EntityCommonStockSharesOutstanding",
             (dei.get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []),
            ("us-gaap:CommonStockSharesOutstanding",
             (usgaap.get("CommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []),
            ("us-gaap:EntityCommonStockSharesOutstanding",
             (usgaap.get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []),
            # Last-resort fallback: weighted-average basic (period-average, not
            # point-in-time). Used when filers like META don't tag point-in-time
            # share counts. Off by ~1-2% vs. true end-of-period outstanding but
            # acceptable for market cap calculation.
            ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
             (usgaap.get("WeightedAverageNumberOfSharesOutstandingBasic") or {}).get("units", {}).get("shares") or []),
        ]
        for tag, facts_list in candidates:
            latest = self._latest_fact(facts_list)
            if latest and latest.get("val"):
                out["shares_outstanding"] = latest.get("val")
                out["shares_as_of"] = latest.get("end")
                out["shares_form"] = latest.get("form")
                out["shares_filed"] = latest.get("filed")
                out["shares_source_tag"] = tag
                break

        # EntityPublicFloat — in USD units
        pf = (dei.get("EntityPublicFloat") or {}).get("units") or {}
        pf_facts = pf.get("USD") or []
        latest_pf = self._latest_fact(pf_facts)
        if latest_pf:
            out["public_float_usd"] = latest_pf.get("val")
            out["public_float_as_of"] = latest_pf.get("end")

        return out

    # ----- public API ------------------------------------------------------

    def fetch_history(self, ticker: str) -> list:
        """Return ALL historical shares_outstanding facts for a ticker, not just
        the latest. Used to populate period-accurate share counts for 13F
        holdings at their original report dates.

        Returns a list of dicts sorted by as_of_date ascending:
            [{"as_of_date","shares","form","filed","source_tag","cik","ticker"}, ...]

        Deduplicates by end date — if multiple XBRL tags have a fact for the
        same date, the one with the highest-priority tag wins (dei:ESO first).
        """
        ticker_u = ticker.upper()
        cik = self.get_cik(ticker_u)
        if not cik:
            return []
        facts_json = self._load_facts(cik)
        if not facts_json or facts_json.get("_not_found"):
            return []

        facts = facts_json.get("facts") or {}
        dei = facts.get("dei") or {}
        usgaap = facts.get("us-gaap") or {}

        # Same preference order as _extract_shares
        tag_sources = [
            ("dei:EntityCommonStockSharesOutstanding",
             (dei.get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []),
            ("us-gaap:CommonStockSharesOutstanding",
             (usgaap.get("CommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []),
            ("us-gaap:EntityCommonStockSharesOutstanding",
             (usgaap.get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []),
            ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
             (usgaap.get("WeightedAverageNumberOfSharesOutstandingBasic") or {}).get("units", {}).get("shares") or []),
        ]

        # Collect by end date, highest-priority tag wins
        by_date: dict = {}
        for tag, fact_list in tag_sources:
            for f in fact_list:
                end = f.get("end")
                val = f.get("val")
                if not end or not val:
                    continue
                if end in by_date:
                    continue  # already have higher-priority tag for this date
                by_date[end] = {
                    "ticker":     ticker_u,
                    "cik":        cik,
                    "as_of_date": end,
                    "shares":     int(val),
                    "form":       f.get("form"),
                    "filed":      f.get("filed"),
                    "source_tag": tag,
                }

        return sorted(by_date.values(), key=lambda r: r["as_of_date"])

    def fetch(self, ticker: str) -> Optional[dict]:
        ticker_u = ticker.upper()

        # Step 1: Try SEC XBRL first (authoritative when tagged)
        cik = self.get_cik(ticker_u)
        result = None
        if cik:
            facts = self._load_facts(cik)
            if facts and not facts.get("_not_found"):
                result = self._extract_shares(facts)
                result["cik"] = cik
                result["ticker"] = ticker_u

        # Step 2: Apply manual override if XBRL returned no shares
        # (filers like Visa don't tag shares in XBRL — override CSV fills the gap)
        override = self._overrides.get(ticker_u)
        if override and (result is None or not result.get("shares_outstanding")):
            if result is None:
                result = {
                    "shares_outstanding": None, "shares_as_of": None,
                    "shares_form": None, "shares_filed": None,
                    "shares_source_tag": None,
                    "public_float_usd": None, "public_float_as_of": None,
                    "cik": cik, "ticker": ticker_u,
                }
            result["shares_outstanding"] = override["shares_outstanding"]
            result["shares_as_of"]       = override["shares_as_of"]
            result["shares_form"]        = override["shares_form"]
            result["shares_source_tag"]  = override["shares_source_tag"]

        return result


if __name__ == "__main__":
    import sys
    c = SECSharesClient()
    print(f"Loaded {len(c._ticker_to_cik):,} ticker→CIK mappings")
    tickers = sys.argv[1:] or ["AAPL", "MSFT", "NVDA", "SMLR", "CIVI", "ZZZZ_NOTREAL"]
    for sym in tickers:
        sh = c.fetch(sym)
        if sh is None:
            print(f"  {sym}: not found")
            continue
        print(f"  {sym} (CIK {sh['cik']}): "
              f"shares={sh['shares_outstanding']:,} as of {sh['shares_as_of']} "
              f"({sh['shares_form']} filed {sh['shares_filed']}) | "
              f"float=${sh['public_float_usd']:,.0f}" if sh.get("public_float_usd") else
              f"  {sym} (CIK {sh['cik']}): shares={sh['shares_outstanding']:,} as of {sh['shares_as_of']} "
              f"({sh['shares_form']} filed {sh['shares_filed']}) | float=n/a")
