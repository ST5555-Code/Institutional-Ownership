#!/usr/bin/env python3
"""
fetch_market.py — Pull market data for all unique tickers in holdings.

Data sources (in order of preference for each field):
  1. YahooClient (curl_cffi direct to query1/query2.finance.yahoo.com)
     - price, market_cap, 52w high/low, avg volume, sector, industry, exchange
  2. SECSharesClient (SEC XBRL company facts)
     - shares_outstanding (authoritative, from 10-K/10-Q cover page)
     - public_float_usd (from 10-K cover)

Incremental update protocol (default behavior):
  - Prices:     refetch if fetch_date > 7 days old
  - Metadata:   refetch if metadata_date > 30 days old OR market_cap is NULL
  - SEC shares: refetch if sec_date > 90 days old (quarterly filing cadence)
  - Unfetchable tickers are flagged and skipped on future runs

Pre-filter: bonds (" " in ticker), warrants (WT/-WT/-W suffix), preferreds
(-P*), class markers (trailing *) are flagged as unfetchable before any HTTP
call.

Flags:
  --staging         Write to staging DB instead of production
  --force           Ignore freshness, refetch everything in scope
  --missing-only    Only fetch tickers with no market_data row at all
  --sec-only        Only refresh SEC shares outstanding (no Yahoo calls)
  --metadata-only   Only refresh Yahoo metadata for tickers with stale/missing
  --limit N         Cap number of tickers fetched (for testing)

Run: python3 scripts/fetch_market.py [--staging]
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from typing import List, Optional

import duckdb
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import set_staging_mode, is_staging_mode, get_db_path, connect_read, crash_handler
# from config import QUARTER_SNAPSHOT_DATES as SNAPSHOT_DATES

from yahoo_client import YahooClient
from sec_shares_client import SECSharesClient


# ---------- Staleness thresholds (days) ----------
PRICE_STALE_DAYS = 7
META_STALE_DAYS = 30
SEC_STALE_DAYS = 90

# ---------- Batching ----------
QUOTE_BATCH_SIZE = 150  # tickers per /v7/quote call
META_SLEEP_SEC = 0.05   # between per-ticker metadata calls


# =====================================================================
# Schema: ensure market_data has the columns we need (idempotent)
# =====================================================================

REQUIRED_COLUMNS = {
    "unfetchable":       "BOOLEAN",
    "unfetchable_reason": "VARCHAR",
    "metadata_date":     "VARCHAR",
    "sec_date":          "VARCHAR",
    "public_float_usd":  "DOUBLE",
    "shares_as_of":      "VARCHAR",
    "shares_form":       "VARCHAR",
    "shares_filed":      "VARCHAR",
    "shares_source_tag": "VARCHAR",
    "cik":               "VARCHAR",
}


def ensure_schema(con):
    """Idempotent ALTER TABLE — add any missing columns."""
    try:
        con.execute("SELECT 1 FROM market_data LIMIT 1")
    except Exception:
        return  # table doesn't exist yet; will be created by save_market_data
    existing = {r[0] for r in con.execute("DESCRIBE market_data").fetchall()}
    for col, typ in REQUIRED_COLUMNS.items():
        if col not in existing:
            con.execute(f"ALTER TABLE market_data ADD COLUMN {col} {typ}")
            print(f"  schema: added {col} {typ}")


# =====================================================================
# Pre-filter: classify unfetchable tickers before any HTTP call
# =====================================================================

# Patterns that Yahoo cannot price (bonds, warrants, preferreds, class markers)
_BOND_RE     = re.compile(r"\s")              # "MSTR 0.625 09/15/28"
_WARRANT_RE  = re.compile(r"(?:^|[^A-Z])(WT|WTS|WS|/WS|-WT|-W)$")
_PREF_RE     = re.compile(r"-P[A-Z]?$|^.*-P$") # "MER-PK", "BAC-PL"
_CLASS_MARK  = re.compile(r"\*$")              # "MRO*"
_FX_SUFFIX   = re.compile(r"(?:USD|EUR|GBP|JPY|CAD|CHF|AUD)$")


def classify_unfetchable(ticker: str) -> Optional[str]:
    """Return reason string if unfetchable, else None."""
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


def flag_unfetchable(con, tickers: List[str]) -> int:
    """Insert/update unfetchable rows in market_data. Returns count flagged."""
    rows = []
    today = datetime.now().strftime("%Y-%m-%d")
    for t in tickers:
        reason = classify_unfetchable(t)
        if reason:
            rows.append((t, True, reason, today))
    if not rows:
        return 0
    con.executemany("""
        INSERT INTO market_data (ticker, unfetchable, unfetchable_reason, fetch_date)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (ticker) DO UPDATE SET
            unfetchable = excluded.unfetchable,
            unfetchable_reason = excluded.unfetchable_reason
    """, rows)
    return len(rows)


# =====================================================================
# Ticker selection: incremental / missing-only / force
# =====================================================================

def get_all_holdings_tickers(read_con) -> list:
    return read_con.execute("""
        SELECT DISTINCT ticker FROM holdings
        WHERE ticker IS NOT NULL AND ticker != ''
        ORDER BY ticker
    """).fetchdf()["ticker"].tolist()


def select_tickers_to_fetch(con, read_con, mode: str, force: bool, limit: Optional[int]) -> List[str]:
    """Choose which tickers need a Yahoo fetch.

    mode: 'all' | 'missing' | 'metadata'
    """
    all_tickers = get_all_holdings_tickers(read_con)

    # Exclude anything already flagged unfetchable
    unfetchable = set(con.execute("""
        SELECT ticker FROM market_data WHERE unfetchable = TRUE
    """).fetchdf()["ticker"].tolist()) if table_has_column(con, "unfetchable") else set()

    candidates = [t for t in all_tickers if t not in unfetchable]
    # Also apply the static classifier to catch anything not yet flagged
    candidates = [t for t in candidates if classify_unfetchable(t) is None]

    if force:
        selected = candidates
    elif mode == "missing":
        existing = set(con.execute(
            "SELECT ticker FROM market_data WHERE price_live IS NOT NULL"
        ).fetchdf()["ticker"].tolist())
        selected = [t for t in candidates if t not in existing]
    elif mode == "metadata":
        # Tickers with a row but stale/missing metadata
        rows = con.execute(f"""
            SELECT ticker FROM market_data
            WHERE (market_cap IS NULL
                   OR metadata_date IS NULL
                   OR CAST(metadata_date AS DATE) < CURRENT_DATE - INTERVAL '{META_STALE_DAYS}' DAY)
                  AND (unfetchable IS NULL OR unfetchable = FALSE)
        """).fetchdf()["ticker"].tolist()
        selected = [t for t in rows if t in set(candidates)]
    else:  # 'all' → incremental: stale prices OR missing
        existing = con.execute(f"""
            SELECT ticker FROM market_data
            WHERE price_live IS NOT NULL
              AND CAST(fetch_date AS DATE) >= CURRENT_DATE - INTERVAL '{PRICE_STALE_DAYS}' DAY
        """).fetchdf()["ticker"].tolist()
        fresh = set(existing)
        selected = [t for t in candidates if t not in fresh]

    if limit:
        selected = selected[:limit]
    return selected


def table_has_column(con, col: str) -> bool:
    try:
        cols = {r[0] for r in con.execute("DESCRIBE market_data").fetchall()}
        return col in cols
    except Exception:
        return False


# =====================================================================
# Yahoo fetch via curl_cffi client
# =====================================================================

def fetch_yahoo(tickers: list) -> pd.DataFrame:
    """Two-pass Yahoo fetch: batch quote (price + market_cap) then per-symbol
    metadata (sector/industry/float). Returns merged DataFrame keyed on ticker."""
    if not tickers:
        return pd.DataFrame()

    client = YahooClient()
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- Pass 1: batch quotes ----
    print(f"  Yahoo pass 1 — batch quote ({QUOTE_BATCH_SIZE}/call): {len(tickers):,} symbols")
    quotes = {}
    t0 = time.time()
    for i in range(0, len(tickers), QUOTE_BATCH_SIZE):
        chunk = tickers[i:i + QUOTE_BATCH_SIZE]
        try:
            quotes.update(client.fetch_quote_batch(chunk))
        except Exception as e:
            print(f"    batch {i} err: {e}")
        if (i // QUOTE_BATCH_SIZE) % 5 == 4:
            done = min(i + QUOTE_BATCH_SIZE, len(tickers))
            print(f"    [{done:,}/{len(tickers):,}] hits={len(quotes):,}", flush=True)
    dt1 = time.time() - t0
    print(f"  Pass 1 done: {len(quotes):,}/{len(tickers):,} hits in {dt1:.1f}s")

    # ---- Pass 2: per-symbol metadata for everything (fills sector/industry/float) ----
    # Run metadata for all quote hits PLUS the misses (quoteSummary is more forgiving).
    # Skip no-one — the per-symbol endpoint is our only path to sector/industry/float.
    all_syms = list(set(tickers))
    print(f"  Yahoo pass 2 — per-symbol metadata: {len(all_syms):,} symbols")
    metadata = {}
    t0 = time.time()
    for i, sym in enumerate(all_syms):
        m = client.fetch_metadata(sym)
        if m:
            metadata[sym] = m
        if (i + 1) % 200 == 0:
            print(f"    [{i+1:,}/{len(all_syms):,}] hits={len(metadata):,}", flush=True)
        time.sleep(META_SLEEP_SEC)
    dt2 = time.time() - t0
    print(f"  Pass 2 done: {len(metadata):,}/{len(all_syms):,} hits in {dt2:.1f}s")

    # ---- Merge ----
    records = []
    for sym in all_syms:
        q = quotes.get(sym, {})
        m = metadata.get(sym, {})
        price = q.get("price") or m.get("price")
        if price is None:
            continue  # skip rows with no price at all
        # NOTE: market_cap is NOT written from Yahoo. It is computed downstream
        # as shares_outstanding (SEC, authoritative) × price_live (Yahoo). See
        # recompute_market_cap() at end of main(). shares_outstanding is also
        # left blank here — SEC is the sole source.
        records.append({
            "ticker":             sym,
            "price_live":         price,
            "float_shares":       m.get("float_shares"),
            "fifty_two_week_high": q.get("fifty_two_week_high") or m.get("fifty_two_week_high"),
            "fifty_two_week_low":  q.get("fifty_two_week_low")  or m.get("fifty_two_week_low"),
            "avg_volume_30d":     q.get("avg_volume_30d") or m.get("avg_volume_30d"),
            "sector":             m.get("sector"),
            "industry":           m.get("industry"),
            "exchange":           m.get("exchange") or q.get("exchange"),
            "fetch_date":         today,
            "metadata_date":      today if m else None,
        })
    return pd.DataFrame(records)


# =====================================================================
# SEC fetch — authoritative shares outstanding
# =====================================================================

def fetch_sec(tickers: list) -> pd.DataFrame:
    """Pull shares_outstanding + public_float from SEC XBRL for all tickers that
    have a CIK mapping. Returns DataFrame; tickers not in SEC mapping are absent."""
    if not tickers:
        return pd.DataFrame()

    client = SECSharesClient()
    print(f"  SEC XBRL: {len(tickers):,} tickers (cached, ~90d ttl)")
    today = datetime.now().strftime("%Y-%m-%d")

    records = []
    hits = 0
    no_cik = 0
    t0 = time.time()
    for i, t in enumerate(tickers):
        r = client.fetch(t)
        if r is None:
            no_cik += 1
            continue
        if r.get("shares_outstanding") is None:
            continue
        hits += 1
        records.append({
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
        if (i + 1) % 500 == 0:
            print(f"    [{i+1:,}/{len(tickers):,}] sec_hits={hits:,} no_cik={no_cik:,}", flush=True)
    dt = time.time() - t0
    print(f"  SEC done: {hits:,}/{len(tickers):,} hits, {no_cik:,} no CIK in {dt:.1f}s")
    return pd.DataFrame(records)


# =====================================================================
# Save / upsert
# =====================================================================

def upsert_yahoo(con, df: pd.DataFrame):
    """Upsert Yahoo-sourced columns into market_data. Preserves SEC fields."""
    if df.empty:
        print("  No Yahoo rows to save.")
        return
    print(f"\nSaving Yahoo data: {len(df):,} rows")
    con.register("df_y", df)
    # Ensure rows exist
    con.execute("""
        INSERT INTO market_data (ticker, fetch_date)
        SELECT ticker, fetch_date FROM df_y
        ON CONFLICT (ticker) DO NOTHING
    """)
    # Update only Yahoo-owned fields. market_cap and shares_outstanding are
    # intentionally NOT touched here — they come from SEC XBRL and market_cap
    # is computed downstream as shares_outstanding × price_live.
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


def upsert_sec(con, df: pd.DataFrame):
    """Upsert SEC-sourced columns. SEC shares_outstanding is authoritative and
    overwrites whatever Yahoo provided."""
    if df.empty:
        print("  No SEC rows to save.")
        return
    print(f"\nSaving SEC data: {len(df):,} rows")
    con.register("df_s", df)
    con.execute("""
        INSERT INTO market_data (ticker, fetch_date)
        SELECT ticker, sec_date FROM df_s
        ON CONFLICT (ticker) DO NOTHING
    """)
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


def recompute_market_cap(con):
    """Recompute market_cap = shares_outstanding (SEC) × price_live (Yahoo).

    Strict: market_cap is set to NULL where either input is missing. We never
    fall back to Yahoo's marketCap field because it is not auditable against a
    specific filing date.
    """
    print("\nRecomputing market_cap = SEC shares_outstanding × Yahoo price_live...")
    con.execute("""
        UPDATE market_data
        SET market_cap = CASE
            WHEN shares_outstanding IS NOT NULL AND price_live IS NOT NULL
                THEN shares_outstanding * price_live
            ELSE NULL
        END
    """)
    total = con.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
    with_cap = con.execute("SELECT COUNT(*) FROM market_data WHERE market_cap IS NOT NULL").fetchone()[0]
    print(f"  market_cap populated: {with_cap:,}/{total:,} ({100*with_cap/max(1,total):.1f}%)")


def update_holdings(con):
    """Update holdings with pct_of_float and market_value_live.

    pct_of_float uses SEC shares_outstanding when available (authoritative from
    10-K/10-Q cover); falls back to Yahoo float_shares otherwise.
    """
    print("\nUpdating holdings with market data...")
    con.execute("""
        UPDATE holdings h SET market_value_live = h.shares * m.price_live
        FROM market_data m WHERE h.ticker = m.ticker AND m.price_live IS NOT NULL
    """)
    con.execute("""
        UPDATE holdings h SET pct_of_float = ROUND(
            h.shares * 100.0 / COALESCE(m.shares_outstanding, m.float_shares), 4)
        FROM market_data m
        WHERE h.ticker = m.ticker
          AND COALESCE(m.shares_outstanding, m.float_shares) IS NOT NULL
          AND COALESCE(m.shares_outstanding, m.float_shares) > 0
    """)
    total = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    live = con.execute("SELECT COUNT(*) FROM holdings WHERE market_value_live IS NOT NULL").fetchone()[0]
    pct = con.execute("SELECT COUNT(*) FROM holdings WHERE pct_of_float IS NOT NULL").fetchone()[0]
    print(f"  Holdings with live value: {live:,}/{total:,} ({100*live/total:.1f}%)")
    print(f"  Holdings with pct_of_float: {pct:,}/{total:,} ({100*pct/total:.1f}%)")


# =====================================================================
# Main
# =====================================================================

def main(args):
    print("=" * 60)
    print("fetch_market.py — Market Data (Yahoo + SEC)")
    print(f"  mode: staging={is_staging_mode()} | force={args.force} | "
          f"missing-only={args.missing_only} | sec-only={args.sec_only} | "
          f"metadata-only={args.metadata_only}")
    print("=" * 60)

    con = duckdb.connect(get_db_path())
    ensure_schema(con)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_ticker ON market_data(ticker)")

    # Read holdings from production DB (source of truth)
    read_con = connect_read() if is_staging_mode() else con
    all_tickers = get_all_holdings_tickers(read_con)
    print(f"  Total holdings tickers: {len(all_tickers):,}")

    # Flag unfetchable via static classifier (idempotent)
    flagged = flag_unfetchable(con, all_tickers)
    if flagged:
        print(f"  Flagged unfetchable: {flagged:,}")

    # Determine which tickers to fetch
    if args.sec_only:
        # All candidates — SEC client handles "not in CIK map" internally
        unfetchable_set = set(con.execute(
            "SELECT ticker FROM market_data WHERE unfetchable = TRUE"
        ).fetchdf()["ticker"].tolist())
        candidates = [t for t in all_tickers if t not in unfetchable_set]
        if not args.force:
            stale_cutoff = con.execute(f"""
                SELECT ticker FROM market_data
                WHERE sec_date IS NULL
                   OR CAST(sec_date AS DATE) < CURRENT_DATE - INTERVAL '{SEC_STALE_DAYS}' DAY
            """).fetchdf()["ticker"].tolist()
            candidates = [t for t in candidates if t in set(stale_cutoff) or t not in set(
                con.execute("SELECT ticker FROM market_data WHERE sec_date IS NOT NULL")
                   .fetchdf()["ticker"].tolist())]
        if args.limit:
            candidates = candidates[: args.limit]
        yahoo_targets = []
        sec_targets = candidates
    else:
        mode = "missing" if args.missing_only else ("metadata" if args.metadata_only else "all")
        yahoo_targets = select_tickers_to_fetch(con, read_con, mode, args.force, args.limit)
        # SEC: always refresh stale ones on full/missing runs (unless metadata-only)
        sec_targets = []
        if not args.metadata_only:
            stale_sec = con.execute(f"""
                SELECT ticker FROM market_data
                WHERE (unfetchable IS NULL OR unfetchable = FALSE)
                  AND (sec_date IS NULL
                       OR CAST(sec_date AS DATE) < CURRENT_DATE - INTERVAL '{SEC_STALE_DAYS}' DAY)
            """).fetchdf()["ticker"].tolist()
            # Plus any ticker we're about to add via Yahoo
            sec_targets = sorted(set(stale_sec) | set(yahoo_targets))
            if args.limit:
                sec_targets = sec_targets[: args.limit]

    print(f"\n  Yahoo fetch targets: {len(yahoo_targets):,}")
    print(f"  SEC  fetch targets: {len(sec_targets):,}")

    if not yahoo_targets and not sec_targets:
        print("\nAll data fresh. Nothing to fetch.")
        con.close()
        if is_staging_mode():
            read_con.close()
        return

    # ---- Fetch ----
    if yahoo_targets:
        df_y = fetch_yahoo(yahoo_targets)
        if not df_y.empty:
            upsert_yahoo(con, df_y)

    if sec_targets:
        df_s = fetch_sec(sec_targets)
        if not df_s.empty:
            upsert_sec(con, df_s)

    # Always recompute market_cap from SEC shares × Yahoo price — single source of truth
    recompute_market_cap(con)
    con.execute("CHECKPOINT")

    # ---- Holdings update (production only) ----
    if not is_staging_mode():
        update_holdings(con)
    else:
        print("\n  Staging mode: skipping holdings update (run after merge)")

    # ---- Summary ----
    total = con.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
    with_price = con.execute("SELECT COUNT(*) FROM market_data WHERE price_live IS NOT NULL").fetchone()[0]
    with_cap = con.execute("SELECT COUNT(*) FROM market_data WHERE market_cap IS NOT NULL").fetchone()[0]
    with_sec = con.execute("SELECT COUNT(*) FROM market_data WHERE shares_as_of IS NOT NULL").fetchone()[0]
    unfetch = con.execute("SELECT COUNT(*) FROM market_data WHERE unfetchable = TRUE").fetchone()[0]
    print(f"\n  market_data: {total:,} rows  price={with_price:,} cap={with_cap:,} sec_shares={with_sec:,} unfetchable={unfetch:,}")

    con.close()
    if is_staging_mode() and read_con is not con:
        read_con.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch market data (Yahoo + SEC)")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    parser.add_argument("--force", action="store_true", help="Ignore staleness, refetch all in scope")
    parser.add_argument("--missing-only", action="store_true",
                        help="Only tickers with no market_data row yet")
    parser.add_argument("--metadata-only", action="store_true",
                        help="Only refresh Yahoo metadata for stale/missing")
    parser.add_argument("--sec-only", action="store_true",
                        help="Only refresh SEC shares outstanding (no Yahoo)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of tickers fetched (testing)")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    crash_handler("fetch_market")(lambda: main(args))
