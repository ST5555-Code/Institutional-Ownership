#!/usr/bin/env python3
"""
auto_resolve.py — Automatically resolve CUSIP-to-ticker gaps.

Finds CUSIPs with no ticker or non-functional ticker (no market_data),
attempts resolution via SEC JSON, EDGAR search, and Yahoo,
then routes results to auto-apply (high confidence) or pending review.

Run: python3 scripts/auto_resolve.py
"""

import os
import re
import time
from datetime import datetime

import requests
import pandas as pd
import duckdb
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import get_db_path, set_staging_mode
REF_DIR = os.path.join(BASE_DIR, "data", "reference")

OVERRIDES_PATH = os.path.join(REF_DIR, "ticker_overrides.csv")
PENDING_PATH = os.path.join(REF_DIR, "ticker_overrides_pending.csv")
LOG_PATH = os.path.join(REF_DIR, "auto_resolve_log.csv")

from config import SEC_HEADERS
SEC_DELAY = 0.5

AUTO_APPLY_THRESHOLD = 92
REVIEW_THRESHOLD = 82
MIN_FILED_VALUE = 1e9  # $1B minimum to bother resolving
MIN_MKTCAP_FOR_LARGE_POSITION = 100e6  # Reject if mktcap < $100M and filed > $500M
MAX_FILED_FOR_MICROCAP = 500e6

COMMON_SUFFIXES = [
    " INC", " CORP", " CO", " LTD", " LLC", " LP", " PLC", " SA", " NV",
    " SE", " AG", " GROUP", " HOLDINGS", " HLDGS", " INTERNATIONAL", " INTL",
    " TECHNOLOGIES", " TECHNOLOGY", " ENTERPRISES", " CLASS A", " CLASS B",
    " CL A", " CL B", " NEW", " COM", " ORD", " SHS", " ADR", " SPON",
    ",", ".", "/DE/", "/MD/", "/NY/", "/NV/", " THE",
]


def normalize_name(name):
    """Normalize company name for matching."""
    if not name or pd.isna(name):
        return ""
    s = str(name).upper().strip()
    for suffix in COMMON_SUFFIXES:
        s = s.replace(suffix, "")
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# =========================================================================
# Step 1 — Find gaps
# =========================================================================
def find_gaps(con):
    """Find CUSIPs with no live market data, excluding derivatives and money market."""
    df = con.execute(f"""
        WITH gap AS (
            SELECT
                h.cusip,
                MAX(h.issuer_name) as issuer_name,
                MAX(h.ticker) as current_ticker,
                MAX(h.security_type_inferred) as sec_type,
                SUM(h.market_value_usd) as filed_value,
                COUNT(DISTINCT h.cik) as holders
            FROM holdings h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '2025Q4'
              AND h.market_value_live IS NULL
              AND COALESCE(h.security_type_inferred, 'equity') NOT IN ('derivative', 'money_market')
            GROUP BY h.cusip
            HAVING SUM(h.market_value_usd) >= {MIN_FILED_VALUE}
        )
        SELECT * FROM gap ORDER BY filed_value DESC
    """).fetchdf()

    # Exclude CUSIPs already in overrides file
    existing = set()
    if os.path.exists(OVERRIDES_PATH):
        ov = pd.read_csv(OVERRIDES_PATH, dtype=str)
        existing = set(ov["cusip"].tolist())
    df = df[~df["cusip"].isin(existing)]

    print(f"  Gaps found: {len(df)} CUSIPs (${df['filed_value'].sum()/1e9:,.0f}B filed value)")
    return df


# =========================================================================
# Step 2 — Resolution methods
# =========================================================================
def load_sec_tickers():
    """Fetch SEC company_tickers_exchange.json and build normalized name→ticker lookup."""
    print("  Loading SEC company tickers JSON...")
    r = requests.get(
        "https://www.sec.gov/files/company_tickers_exchange.json",
        headers=SEC_HEADERS, timeout=30,
    )
    r.raise_for_status()
    time.sleep(SEC_DELAY)

    data = r.json()
    df = pd.DataFrame(data["data"], columns=data["fields"])

    lookup = {}
    for _, row in df.iterrows():
        norm = normalize_name(row["name"])
        if norm and row["ticker"]:
            lookup[norm] = str(row["ticker"]).strip()

    print(f"  SEC tickers loaded: {len(lookup):,} entries")
    return lookup


def resolve_method_a(gaps, sec_lookup):
    """Method A: SEC company tickers JSON — exact normalized name match."""
    results = {}
    for _, row in gaps.iterrows():
        cusip = row["cusip"]
        norm = normalize_name(row["issuer_name"])
        if norm in sec_lookup:
            results[cusip] = {
                "candidate": sec_lookup[norm],
                "method": "sec_json",
                "match_name": norm,
            }
    print(f"  Method A (SEC JSON): {len(results)} matches")
    return results


def resolve_method_b(gaps, already_resolved):
    """Method B: SEC EDGAR full-text search.

    Searches https://efts.sec.gov/LATEST/search-index for 10-K filings matching
    the issuer name. Extracts ticker from the display_names field, which contains
    entries like 'COMPANY NAME  (TKR)  (CIK 0000012345)'. Fuzzy-matches the
    company name portion against issuer_name to confirm the right entity.
    """
    remaining = gaps[~gaps["cusip"].isin(already_resolved)]
    results = {}

    for _, row in remaining.head(50).iterrows():  # Cap at 50 to respect rate limits
        cusip = row["cusip"]
        name = str(row["issuer_name"])
        search_terms = normalize_name(name)
        if not search_terms or len(search_terms) < 3:
            continue

        try:
            url = (
                f"https://efts.sec.gov/LATEST/search-index?"
                f"q={requests.utils.quote(search_terms[:60])}"
                f"&forms=10-K&dateRange=custom&startdt=2024-01-01"
            )
            r = requests.get(url, headers=SEC_HEADERS, timeout=15)
            time.sleep(SEC_DELAY)

            if r.status_code != 200:
                continue

            data = r.json()
            hits = data.get("hits", {}).get("hits", [])

            best_ticker = None
            best_score = 0
            best_company = ""

            # Scan display_names across first 10 hits for best fuzzy match
            for hit in hits[:10]:
                source = hit.get("_source", {})
                for display in source.get("display_names", []):
                    # Extract company name (text before first parenthesis)
                    company_part = display.split("(")[0].strip()
                    # Extract ticker from parentheses: (TKR) or (TKR, TKR-WT)
                    ticker_match = re.search(r"\(([A-Z]{1,5}(?:[-/][A-Z]{1,3})?)", display)
                    if not ticker_match:
                        continue
                    candidate_ticker = ticker_match.group(1)
                    score = fuzz.token_sort_ratio(
                        normalize_name(company_part), normalize_name(name)
                    )
                    if score > best_score:
                        best_score = score
                        best_ticker = candidate_ticker
                        best_company = company_part

            if best_ticker and best_score >= REVIEW_THRESHOLD:
                results[cusip] = {
                    "candidate": best_ticker,
                    "method": "sec_edgar",
                    "match_name": best_company,
                    "match_score": best_score,
                }
        except Exception:
            pass

    print(f"  Method B (SEC EDGAR): {len(results)} matches")
    return results


def resolve_method_c(gaps, already_resolved):
    """Method C: Yahoo name search for remaining unresolved CUSIPs."""
    from yahoo_client import YahooClient

    remaining = gaps[~gaps["cusip"].isin(already_resolved)]
    results = {}
    yc = YahooClient()

    for _, row in remaining.head(20).iterrows():  # Cap at 20 — slow
        cusip = row["cusip"]
        name = str(row["issuer_name"])
        words = normalize_name(name).split()
        if len(words) < 1:
            continue
        candidate_ticker = words[0][:5]  # First word, max 5 chars

        m = yc.fetch_metadata(candidate_ticker)
        if m and m.get("price"):
            yf_name = m.get("long_name") or m.get("short_name") or ""
            score = fuzz.token_sort_ratio(normalize_name(yf_name), normalize_name(name))
            if score >= REVIEW_THRESHOLD:
                results[cusip] = {
                    "candidate": candidate_ticker,
                    "method": "yahoo_name",
                    "match_name": yf_name,
                    "match_score": score,
                }

    print(f"  Method C (Yahoo): {len(results)} matches")
    return results


# =========================================================================
# Step 3 — Validate candidates
# =========================================================================
def validate_candidates(all_candidates, gaps):
    """Validate every candidate ticker via YahooClient. Return scored results.

    Validation signals (not persisted — transient sanity check):
      - price must be > 0
      - market_cap: used ONLY to reject micro-cap candidates for large positions.
        Uses Yahoo's quote market_cap here because this is a fast sanity filter,
        not a persisted value. The authoritative DB market_cap is computed
        elsewhere as SEC shares × Yahoo price.
      - name: fuzzy-match Yahoo longName against issuer_name.
    """
    from yahoo_client import YahooClient

    yc = YahooClient()
    validated = []

    # Batch-fetch quotes (price + market_cap) for all candidates in one pass
    candidate_list = [info["candidate"] for info in all_candidates.values()]
    quote_map = {}
    for i in range(0, len(candidate_list), 150):
        chunk = candidate_list[i:i + 150]
        try:
            quote_map.update(yc.fetch_quote_batch(chunk))
        except Exception:
            pass

    for cusip, info in all_candidates.items():
        candidate = info["candidate"]
        method = info["method"]
        gap_row = gaps[gaps["cusip"] == cusip].iloc[0]
        issuer_name = gap_row["issuer_name"]
        current_ticker = gap_row.get("current_ticker", "")
        filed_value = gap_row["filed_value"]

        confidence = "LOW"
        score = info.get("match_score", 0)
        reason = ""

        q = quote_map.get(candidate, {})
        price = q.get("price")
        mktcap = q.get("market_cap")

        try:
            if price and price > 0 and mktcap and mktcap > 0:
                # Hard rejection: micro-cap candidate for large institutional position
                if mktcap < MIN_MKTCAP_FOR_LARGE_POSITION and filed_value > MAX_FILED_FOR_MICROCAP:
                    confidence = "REJECT"
                    reason = f"Market cap ${mktcap/1e6:.0f}M too small for ${filed_value/1e9:.0f}B filed position"
                    validated.append({
                        "cusip": cusip, "issuer_name": issuer_name,
                        "wrong_ticker": current_ticker if pd.notna(current_ticker) else "",
                        "candidate_ticker": candidate, "method": method,
                        "confidence": confidence, "confidence_score": 0,
                        "filed_value": filed_value, "reason": reason,
                    })
                    continue

                # Fuzzy name match via long/short name from batch quote
                yf_name = q.get("long_name") or q.get("short_name") or ""
                if not yf_name:
                    # Fall back to per-symbol metadata if batch didn't include names
                    m = yc.fetch_metadata(candidate) or {}
                    yf_name = m.get("long_name") or m.get("short_name") or ""
                name_score = fuzz.token_sort_ratio(
                    normalize_name(yf_name), normalize_name(issuer_name)
                )
                score = max(score, name_score)

                if score >= AUTO_APPLY_THRESHOLD:
                    confidence = "HIGH"
                elif score >= REVIEW_THRESHOLD:
                    confidence = "LOW"
                    reason = f"Fuzzy score {score} below auto-apply threshold ({AUTO_APPLY_THRESHOLD})"
                else:
                    confidence = "REJECT"
                    reason = f"Fuzzy score {score} below review threshold ({REVIEW_THRESHOLD})"
            else:
                confidence = "REJECT"
                reason = "Yahoo validation failed: no price or market cap"
        except Exception as e:
            confidence = "REJECT"
            reason = f"Yahoo error: {e}"

        validated.append({
            "cusip": cusip,
            "issuer_name": issuer_name,
            "wrong_ticker": current_ticker if pd.notna(current_ticker) else "",
            "candidate_ticker": candidate,
            "method": method,
            "confidence": confidence,
            "confidence_score": score,
            "filed_value": filed_value,
            "reason": reason,
        })

    print(f"  Validated: {len(validated)} candidates")
    high = sum(1 for v in validated if v["confidence"] == "HIGH")
    low = sum(1 for v in validated if v["confidence"] == "LOW")
    reject = sum(1 for v in validated if v["confidence"] == "REJECT")
    print(f"    HIGH: {high}, LOW: {low}, REJECT: {reject}")
    return validated


# =========================================================================
# Step 4 — Route results
# =========================================================================
def route_results(validated, unresolved_cusips, gaps, con):
    """Route validated results to auto-apply, pending, or log-only."""
    auto_applied = []
    pending = []
    logged_unresolved = []

    now = datetime.now().isoformat()

    # --- HIGH confidence → auto-apply ---
    for v in validated:
        if v["confidence"] == "HIGH":
            auto_applied.append(v)
        elif v["confidence"] == "LOW":
            pending.append(v)
        # REJECT: log only

    # --- Apply HIGH confidence to overrides file ---
    if auto_applied:
        existing = pd.read_csv(OVERRIDES_PATH, dtype=str) if os.path.exists(OVERRIDES_PATH) else pd.DataFrame()
        new_rows = []
        for v in auto_applied:
            new_rows.append({
                "cusip": v["cusip"],
                "wrong_ticker": v["wrong_ticker"],
                "correct_ticker": v["candidate_ticker"],
                "company_name": v["issuer_name"],
                "note": f"Auto-resolved via {v['method']} (score {v['confidence_score']})",
                "security_type_override": "equity",
                "method": v["method"],
                "auto_applied": "True",
            })

        df_new = pd.DataFrame(new_rows)
        combined = pd.concat([existing, df_new], ignore_index=True)
        combined.to_csv(OVERRIDES_PATH, index=False)

        # Apply to database
        for v in auto_applied:
            cusip = v["cusip"]
            ticker = v["candidate_ticker"]
            wrong = v["wrong_ticker"]
            if wrong:
                con.execute(f"UPDATE securities SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND ticker = '{wrong}'")
                con.execute(f"UPDATE holdings SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND ticker = '{wrong}'")
            else:
                con.execute(f"UPDATE securities SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND (ticker IS NULL OR ticker = '')")
                con.execute(f"UPDATE holdings SET ticker = '{ticker}' WHERE cusip = '{cusip}' AND ticker IS NULL")

    # --- LOW confidence → pending file ---
    if pending:
        df_pending = pd.DataFrame([{
            "cusip": v["cusip"],
            "issuer_name": v["issuer_name"],
            "wrong_ticker": v["wrong_ticker"],
            "candidate_ticker": v["candidate_ticker"],
            "method": v["method"],
            "confidence_score": v["confidence_score"],
            "filed_value": v["filed_value"],
            "reason_flagged": v["reason"],
        } for v in pending])

        # Append to existing pending if any
        if os.path.exists(PENDING_PATH):
            existing_pending = pd.read_csv(PENDING_PATH, dtype=str)
            existing_cusips = set(existing_pending["cusip"].tolist())
            df_pending = df_pending[~df_pending["cusip"].isin(existing_cusips)]
            df_pending = pd.concat([existing_pending, df_pending], ignore_index=True)

        df_pending.to_csv(PENDING_PATH, index=False)

    # --- Unresolved CUSIPs ---
    for cusip in unresolved_cusips:
        gap_row = gaps[gaps["cusip"] == cusip]
        if len(gap_row) == 0:
            continue
        gap_row = gap_row.iloc[0]
        sec_type = "unresolved_foreign" if cusip[0] in "GHLNV" else "unresolved"
        logged_unresolved.append({
            "cusip": cusip,
            "issuer_name": gap_row["issuer_name"],
            "filed_value": gap_row["filed_value"],
            "security_type": sec_type,
        })

    # --- Write log ---
    log_rows = []
    for v in validated:
        log_rows.append({
            "cusip": v["cusip"],
            "issuer_name": v["issuer_name"],
            "wrong_ticker": v["wrong_ticker"],
            "correct_ticker": v["candidate_ticker"],
            "method": v["method"],
            "confidence_score": v["confidence_score"],
            "resolved_at": now,
            "auto_applied": v["confidence"] == "HIGH",
        })
    for u in logged_unresolved:
        log_rows.append({
            "cusip": u["cusip"],
            "issuer_name": u["issuer_name"],
            "wrong_ticker": "",
            "correct_ticker": "",
            "method": "",
            "confidence_score": 0,
            "resolved_at": now,
            "auto_applied": False,
        })

    if log_rows:
        df_log = pd.DataFrame(log_rows)
        if os.path.exists(LOG_PATH):
            existing_log = pd.read_csv(LOG_PATH, dtype=str)
            df_log = pd.concat([existing_log, df_log], ignore_index=True)
        df_log.to_csv(LOG_PATH, index=False)

    return auto_applied, pending, logged_unresolved


# =========================================================================
# Step 5 — Fetch market data for auto-applied tickers
# =========================================================================
def fetch_market_data(auto_applied, con):
    """Fetch market data for newly applied tickers via YahooClient + SEC XBRL.

    market_cap is computed as SEC shares_outstanding × Yahoo price_live.
    """
    from yahoo_client import YahooClient
    from sec_shares_client import SECSharesClient

    new_tickers = [v["candidate_ticker"] for v in auto_applied]
    if not new_tickers:
        return

    yc = YahooClient()
    sc = SECSharesClient()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"\n  Fetching market data for {len(new_tickers)} auto-applied tickers...")
    for tkr_str in new_tickers:
        existing = con.execute(
            "SELECT COUNT(*) FROM market_data WHERE ticker = ?", [tkr_str]
        ).fetchone()[0]
        if existing > 0:
            continue
        try:
            m = yc.fetch_metadata(tkr_str)
            if not m or not m.get("price"):
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
            cols = ",".join(rec.keys())
            con.execute(f"INSERT INTO market_data ({cols}) SELECT {cols} FROM df_new")
            con.unregister("df_new")
        except Exception:
            pass

    # Update holdings
    placeholders = ",".join(["?"] * len(new_tickers))
    con.execute(f"""
        UPDATE holdings h SET market_value_live = h.shares * m.price_live
        FROM market_data m WHERE h.ticker = m.ticker
          AND h.ticker IN ({placeholders}) AND h.market_value_live IS NULL
    """, new_tickers)
    con.execute(f"""
        UPDATE holdings h SET pct_of_float = ROUND(
            h.shares * 100.0 / COALESCE(m.shares_outstanding, m.float_shares), 4)
        FROM market_data m WHERE h.ticker = m.ticker
          AND COALESCE(m.shares_outstanding, m.float_shares) > 0
          AND h.ticker IN ({placeholders}) AND h.pct_of_float IS NULL
    """, new_tickers)


# =========================================================================
# Main
# =========================================================================
def main():
    print("=" * 60)
    print("AUTO-RESOLVE — Ticker gap resolution")
    print("=" * 60)

    con = duckdb.connect(get_db_path())

    # Step 1
    print("\nStep 1 — Finding gaps...")
    gaps = find_gaps(con)
    if len(gaps) == 0:
        print("  No gaps to resolve.")
        con.close()
        return

    # Step 2
    print("\nStep 2 — Attempting resolution...")
    sec_lookup = load_sec_tickers()
    results_a = resolve_method_a(gaps, sec_lookup)

    resolved_so_far = set(results_a.keys())
    results_b = resolve_method_b(gaps, resolved_so_far)
    resolved_so_far.update(results_b.keys())

    results_c = resolve_method_c(gaps, resolved_so_far)
    resolved_so_far.update(results_c.keys())

    # Merge all candidates
    all_candidates = {}
    all_candidates.update(results_a)
    all_candidates.update(results_b)
    all_candidates.update(results_c)

    unresolved = set(gaps["cusip"].tolist()) - resolved_so_far

    # Step 3
    print("\nStep 3 — Validating candidates...")
    validated = validate_candidates(all_candidates, gaps)

    # Step 4
    print("\nStep 4 — Routing results...")
    auto_applied, pending, logged_unresolved = route_results(validated, unresolved, gaps, con)

    # Fetch market data
    fetch_market_data(auto_applied, con)

    # Step 5 — Summary
    total = con.execute("SELECT SUM(market_value_usd) FROM holdings WHERE quarter='2025Q4'").fetchone()[0]
    covered = con.execute("SELECT SUM(market_value_usd) FROM holdings WHERE quarter='2025Q4' AND market_value_live IS NOT NULL").fetchone()[0]
    pct = covered / total * 100

    auto_val = sum(v["filed_value"] for v in auto_applied)
    pending_val = sum(v["filed_value"] for v in pending)
    unresolved_val = sum(u["filed_value"] for u in logged_unresolved)

    print("\n")
    print("Auto-resolution complete")
    print("-" * 45)
    print(f"  Gaps found:        {len(gaps):>4} CUSIPs  (${gaps['filed_value'].sum()/1e9:,.0f}B filed value)")
    print(f"  Auto-applied:      {len(auto_applied):>4} CUSIPs  (${auto_val/1e9:,.0f}B)")
    print(f"  Pending review:    {len(pending):>4} CUSIPs  (${pending_val/1e9:,.0f}B)")
    print(f"  Unresolved:        {len(logged_unresolved):>4} CUSIPs  (${unresolved_val/1e9:,.0f}B)")
    print(f"  Coverage after:    {pct:.1f}%")
    print("-" * 45)

    if pending:
        print(f"  Pending file: {PENDING_PATH}")

    con.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Auto-resolve ticker gaps")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("auto_resolve")(main)
