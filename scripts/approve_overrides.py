#!/usr/bin/env python3
"""
approve_overrides.py — Interactive CLI to review and approve pending ticker overrides.

Run: python3 scripts/approve_overrides.py
"""

import os
from datetime import datetime

import pandas as pd
import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")
REF_DIR = os.path.join(BASE_DIR, "data", "reference")

OVERRIDES_PATH = os.path.join(REF_DIR, "ticker_overrides.csv")
PENDING_PATH = os.path.join(REF_DIR, "ticker_overrides_pending.csv")
LOG_PATH = os.path.join(REF_DIR, "auto_resolve_log.csv")


def fmt_dollars(val):
    try:
        val = float(val)
    except (ValueError, TypeError):
        return "$?"
    if val >= 1e12:
        return f"${val/1e12:.1f}T"
    if val >= 1e9:
        return f"${val/1e9:.0f}B"
    if val >= 1e6:
        return f"${val/1e6:.0f}M"
    return f"${val:,.0f}"


def apply_override(row, con):
    """Apply a single override to the database."""
    cusip = row["cusip"]
    ticker = row["candidate_ticker"]
    wrong = row.get("wrong_ticker", "")

    # Update securities
    if wrong and str(wrong).strip():
        con.execute(f"UPDATE securities SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND ticker = '{wrong}'")
        con.execute(f"UPDATE holdings SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND ticker = '{wrong}'")
    else:
        con.execute(f"UPDATE securities SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND (ticker IS NULL OR ticker = '')")
        con.execute(f"UPDATE holdings SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND ticker IS NULL")

    # Add to overrides file
    overrides = pd.read_csv(OVERRIDES_PATH, dtype=str) if os.path.exists(OVERRIDES_PATH) else pd.DataFrame()
    new_row = pd.DataFrame([{
        "cusip": cusip,
        "wrong_ticker": wrong,
        "correct_ticker": ticker,
        "company_name": row.get("issuer_name", ""),
        "note": f"Approved from pending ({row.get('method', 'unknown')})",
        "security_type_override": "equity",
        "method": row.get("method", "unknown"),
        "auto_applied": "True",
    }])
    combined = pd.concat([overrides, new_row], ignore_index=True)
    combined.to_csv(OVERRIDES_PATH, index=False)

    # Log
    log_row = pd.DataFrame([{
        "cusip": cusip,
        "issuer_name": row.get("issuer_name", ""),
        "wrong_ticker": wrong,
        "correct_ticker": ticker,
        "method": row.get("method", ""),
        "confidence_score": row.get("confidence_score", ""),
        "resolved_at": datetime.now().isoformat(),
        "auto_applied": True,
    }])
    if os.path.exists(LOG_PATH):
        existing_log = pd.read_csv(LOG_PATH, dtype=str)
        log_row = pd.concat([existing_log, log_row], ignore_index=True)
    log_row.to_csv(LOG_PATH, index=False)

    return ticker


def fetch_market_for_tickers(tickers, con):
    """Fetch market data for approved tickers via YahooClient + SEC XBRL.

    Uses the canonical sources for this project:
      - Prices, sector, industry, 52w, volume: YahooClient (/v10/quoteSummary)
      - shares_outstanding: SEC XBRL (authoritative, from 10-K/10-Q cover)
      - market_cap: computed as shares_outstanding × price_live (SEC × Yahoo)
    """
    from yahoo_client import YahooClient
    from sec_shares_client import SECSharesClient

    if not tickers:
        return

    yc = YahooClient()
    sc = SECSharesClient()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"\nFetching market data for {len(tickers)} approved tickers...")
    for tkr_str in tickers:
        existing = con.execute(
            "SELECT COUNT(*) FROM market_data WHERE ticker = ?", [tkr_str]
        ).fetchone()[0]
        if existing > 0:
            continue
        try:
            m = yc.fetch_metadata(tkr_str)
            if not m or not m.get("price"):
                print(f"  {tkr_str}: no Yahoo price")
                continue
            sec = sc.fetch(tkr_str) or {}
            shares_out = sec.get("shares_outstanding")
            price = m.get("price")
            market_cap = (shares_out * price) if (shares_out and price) else None

            rec = {
                "ticker":              tkr_str,
                "price_live":          price,
                "market_cap":          market_cap,
                "float_shares":        m.get("float_shares"),
                "shares_outstanding":  shares_out,
                "fifty_two_week_high": m.get("fifty_two_week_high"),
                "fifty_two_week_low":  m.get("fifty_two_week_low"),
                "avg_volume_30d":      m.get("avg_volume_30d"),
                "sector":              m.get("sector"),
                "industry":            m.get("industry"),
                "exchange":            m.get("exchange"),
                "fetch_date":          today,
            }
            df = pd.DataFrame([rec])
            con.register("df_new", df)
            # Upsert: delete any existing row, then insert only matching columns
            con.execute("DELETE FROM market_data WHERE ticker = ?", [tkr_str])
            cols = ",".join(rec.keys())
            con.execute(f"INSERT INTO market_data ({cols}) SELECT {cols} FROM df_new")
            con.unregister("df_new")

            mc = fmt_dollars(market_cap) if market_cap else "N/A"
            print(f"  {tkr_str}: ${price:.2f}, mktcap {mc} (shares src: {'SEC' if shares_out else 'none'})")
        except Exception as e:
            print(f"  {tkr_str}: FAILED ({e})")

    # Update holdings — use shares_outstanding (SEC) with float_shares fallback
    placeholders = ",".join(["?"] * len(tickers))
    con.execute(f"""
        UPDATE holdings h SET market_value_live = h.shares * m.price_live
        FROM market_data m WHERE h.ticker = m.ticker
          AND h.ticker IN ({placeholders})
          AND h.market_value_live IS NULL
    """, tickers)
    con.execute(f"""
        UPDATE holdings h SET pct_of_so = ROUND(
            h.shares * 100.0 / COALESCE(m.shares_outstanding, m.float_shares), 4)
        FROM market_data m WHERE h.ticker = m.ticker
          AND COALESCE(m.shares_outstanding, m.float_shares) > 0
          AND h.ticker IN ({placeholders})
          AND h.pct_of_so IS NULL
    """, tickers)


def main():
    if not os.path.exists(PENDING_PATH):
        print("No pending overrides.")
        return

    df = pd.read_csv(PENDING_PATH, dtype=str)
    if len(df) == 0:
        print("No pending overrides.")
        return

    # Filter: drop candidates below review threshold (82)
    REVIEW_THRESHOLD = 82
    MIN_MKTCAP = 100e6
    MAX_FILED_FOR_MICROCAP = 500e6

    df['confidence_score'] = pd.to_numeric(df['confidence_score'], errors='coerce').fillna(0)
    below_threshold = df[df['confidence_score'] < REVIEW_THRESHOLD]
    df = df[df['confidence_score'] >= REVIEW_THRESHOLD]

    if len(below_threshold) > 0:
        print(f"  Filtered out {len(below_threshold)} candidates below confidence threshold ({REVIEW_THRESHOLD})")

    print(f"\n{len(df)} pending overrides to review.\n")

    if len(df) == 0:
        print("No overrides above threshold.")
        pd.DataFrame(columns=['cusip']).to_csv(PENDING_PATH, index=False)
        return

    con = duckdb.connect(DB_PATH)
    approved_tickers = []
    remaining = []

    for i, (_, row) in enumerate(df.iterrows()):
        # Check market cap of candidate
        candidate = row.get('candidate_ticker', '')
        mkt = con.execute(f"SELECT market_cap FROM market_data WHERE ticker = '{candidate}'").fetchone()
        mktcap = float(mkt[0]) if mkt and mkt[0] else 0
        filed = float(row.get('filed_value', 0))

        warning = ""
        if mktcap < MIN_MKTCAP and filed > MAX_FILED_FOR_MICROCAP:
            warning = "  *** WARNING: Micro-cap candidate for large position — likely wrong match ***"

        print("-" * 45)
        print(f"  CUSIP:        {row['cusip']}")
        print(f"  Company:      {row.get('issuer_name', '?')}")
        print(f"  Filed value:  {fmt_dollars(row.get('filed_value', 0))}")
        print(f"  Candidate:    {candidate}  (mktcap: {fmt_dollars(mktcap)})")
        print(f"  Method:       {row.get('method', '?')}")
        print(f"  Confidence:   {row.get('confidence_score', '?'):.0f}")
        print(f"  Reason:       {row.get('reason_flagged', '?')}")
        if warning:
            print(warning)
        print("-" * 45)

        choice = input("  Apply this override? [y/n/s(kip all remaining)]: ").strip().lower()

        if choice == "y":
            ticker = apply_override(row, con)
            approved_tickers.append(ticker)
            print(f"  → Applied: {row['cusip']} → {ticker}\n")
        elif choice == "s":
            remaining.append(row)
            # Add all remaining rows
            for j in range(i + 1, len(df)):
                remaining.append(df.iloc[j])
            break
        else:
            # Log as rejected
            log_row = pd.DataFrame([{
                "cusip": row["cusip"],
                "issuer_name": row.get("issuer_name", ""),
                "wrong_ticker": row.get("wrong_ticker", ""),
                "correct_ticker": row.get("candidate_ticker", ""),
                "method": row.get("method", ""),
                "confidence_score": row.get("confidence_score", ""),
                "resolved_at": datetime.now().isoformat(),
                "auto_applied": False,
            }])
            if os.path.exists(LOG_PATH):
                existing_log = pd.read_csv(LOG_PATH, dtype=str)
                log_row = pd.concat([existing_log, log_row], ignore_index=True)
            log_row.to_csv(LOG_PATH, index=False)
            print("  → Rejected\n")

    # Save remaining to pending file
    if remaining:
        pd.DataFrame(remaining).to_csv(PENDING_PATH, index=False)
        print(f"\n{len(remaining)} overrides remaining in pending file.")
    else:
        # Clear pending file
        pd.DataFrame(columns=df.columns).to_csv(PENDING_PATH, index=False)
        print("\nAll pending overrides processed.")

    # Fetch market data for approved tickers
    fetch_market_for_tickers(approved_tickers, con)

    # Final coverage
    total = con.execute("SELECT SUM(market_value_usd) FROM holdings WHERE quarter='2025Q4'").fetchone()[0]
    covered = con.execute("SELECT SUM(market_value_usd) FROM holdings WHERE quarter='2025Q4' AND market_value_live IS NOT NULL").fetchone()[0]
    print(f"\nCoverage: {covered/total*100:.1f}%")

    con.close()


if __name__ == "__main__":
    main()
