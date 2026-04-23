#!/usr/bin/env python3
"""Smoke test YahooClient against a large real-world sample from holdings.

Goals:
  1. Verify no rate limiting at meaningful scale
  2. Measure batch quote coverage vs metadata coverage
  3. Profile throughput (symbols/sec) and identify per-call failure modes
  4. Categorize failures (bonds, warrants, preferreds, foreign OTC, truly delisted)

Reads from production DB read-only. Writes nothing.
"""

import os
import re
import sys
import time
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))

import duckdb
from yahoo_client import YahooClient


GARBAGE_RE = re.compile(
    r"""(
        \s                  # bonds: "MSTR 0.625 09/15/28"
        | WT$               # warrants
        | /WS$              # warrants
        | -WT$
        | \*$               # old-class marker
    )""",
    re.VERBOSE,
)


def classify_ticker(t: str) -> str:
    if " " in t:
        return "bond"
    if t.endswith(("WT", "/WS", "-WT", "W")) and len(t) >= 4:
        return "warrant"
    if "-P" in t:
        return "preferred"
    if t.endswith("*"):
        return "class_marker"
    if re.fullmatch(r"[A-Z]{4,}F", t):
        return "foreign_otc_candidate"
    return "equity"


def pick_sample(con, n: int) -> list:
    """Stratified sample: mix of prices-ok but metadata-missing + totally missing."""
    # 1) tickers in market_data missing market_cap
    missing_meta = con.execute("""
        SELECT ticker FROM market_data
        WHERE price_live IS NOT NULL AND market_cap IS NULL
        ORDER BY RANDOM()
    """).fetchdf()["ticker"].tolist()

    # 2) holdings tickers with no market_data row at all
    missing_all = con.execute("""
        SELECT DISTINCT h.ticker FROM holdings h
        LEFT JOIN market_data m ON h.ticker = m.ticker
        WHERE h.ticker IS NOT NULL AND m.ticker IS NULL
        ORDER BY RANDOM()
    """).fetchdf()["ticker"].tolist()

    # 3) random fresh tickers (sanity check — should all succeed)
    fresh = con.execute("""
        SELECT ticker FROM market_data
        WHERE market_cap IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 200
    """).fetchdf()["ticker"].tolist()

    per = n // 3
    sample = missing_meta[:per] + missing_all[:per] + fresh[: n - 2 * per]
    return sample, len(missing_meta), len(missing_all)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 800

    con = duckdb.connect(os.path.join(BASE, "data", "13f.duckdb"), read_only=True)
    sample, total_missing_meta, total_missing_all = pick_sample(con, n)
    con.close()

    print(f"Population: {total_missing_meta:,} missing metadata, {total_missing_all:,} missing entirely")
    print(f"Sample size: {len(sample):,}")

    # Pre-classify
    by_class = Counter(classify_ticker(t) for t in sample)
    print(f"Pre-classification: {dict(by_class)}")

    # Run a-priori filter for the fetch (but still fetch everything to measure)
    equities = [t for t in sample if classify_ticker(t) == "equity"]
    print(f"Equities to fetch: {len(equities):,}\n")

    client = YahooClient()

    # ----- Phase 1: batch quotes -------------------------------------------
    t0 = time.time()
    BATCH = 150
    quote_hits = {}
    for i in range(0, len(equities), BATCH):
        chunk = equities[i:i + BATCH]
        try:
            q = client.fetch_quote_batch(chunk)
            quote_hits.update(q)
        except Exception as e:
            print(f"  batch {i}-{i+len(chunk)} error: {e}")
        pct = 100 * (i + len(chunk)) / len(equities)
        print(f"  quote batch [{i+len(chunk):>4}/{len(equities)}] {pct:5.1f}%  hits={len(quote_hits):>5}", flush=True)

    t_quote = time.time() - t0
    print(f"\nQuote phase: {len(quote_hits):,}/{len(equities):,} hits ({100*len(quote_hits)/max(1,len(equities)):.1f}%) in {t_quote:.1f}s")
    print(f"  throughput: {len(equities)/t_quote:.0f} symbols/sec")

    # ----- Phase 2: per-ticker metadata for a sub-sample -------------------
    meta_sample = list(quote_hits.keys())[:100]
    print(f"\nMetadata phase: {len(meta_sample)} symbols (per-ticker quoteSummary)")
    t0 = time.time()
    meta_ok = 0
    meta_with_float = 0
    meta_with_sector = 0
    for i, sym in enumerate(meta_sample):
        m = client.fetch_metadata(sym)
        if m:
            meta_ok += 1
            if m.get("float_shares"):
                meta_with_float += 1
            if m.get("sector"):
                meta_with_sector += 1
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(meta_sample)}] ok={meta_ok} float={meta_with_float} sector={meta_with_sector}", flush=True)
    t_meta = time.time() - t0
    print(f"\nMetadata phase: {meta_ok}/{len(meta_sample)} ok ({100*meta_ok/len(meta_sample):.0f}%) in {t_meta:.1f}s")
    print(f"  float_shares populated: {meta_with_float}/{len(meta_sample)}")
    print(f"  sector populated:       {meta_with_sector}/{len(meta_sample)}")
    print(f"  throughput: {len(meta_sample)/t_meta:.1f} symbols/sec")

    # ----- Phase 3: sample a few quote misses + failures -------------------
    misses = [t for t in equities if t not in quote_hits][:20]
    print(f"\nSample quote-miss tickers: {misses}")

    # ----- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("SMOKE TEST SUMMARY")
    print("=" * 60)
    print(f"Sample:           {len(sample):,}")
    print(f"Pre-filtered:     {len(sample) - len(equities):,} garbage (bonds/warrants/preferreds)")
    print(f"Equity fetch:     {len(equities):,}")
    print(f"Quote hits:       {len(quote_hits):,} ({100*len(quote_hits)/max(1,len(equities)):.1f}%)")
    print(f"Quote time:       {t_quote:.1f}s ({len(equities)/t_quote:.0f}/s)")
    print(f"Metadata hits:    {meta_ok}/{len(meta_sample)} (float={meta_with_float})")
    print(f"Metadata time:    {t_meta:.1f}s ({len(meta_sample)/max(0.1,t_meta):.1f}/s)")
    print()
    print(f"Extrapolated full run ({total_missing_meta + total_missing_all:,} tickers):")
    est_quote = (total_missing_meta + total_missing_all) / max(1, len(equities)/t_quote)
    est_meta = (total_missing_meta + total_missing_all) / max(0.1, len(meta_sample)/t_meta)
    print(f"  quote phase est:    {est_quote/60:.1f} min")
    print(f"  metadata phase est: {est_meta/60:.1f} min")


if __name__ == "__main__":
    main()
