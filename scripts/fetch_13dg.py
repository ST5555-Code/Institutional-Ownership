#!/usr/bin/env python3
"""
fetch_13dg.py — Download and parse SC 13D/G beneficial ownership filings from EDGAR.

Uses the `edgar` Python library for all EDGAR access.

Builds:
  - beneficial_ownership table: all parsed 13D/G filings
  - beneficial_ownership_current table: latest filing per filer+subject
  - Updates managers.has_13dg flag

Run: python3 scripts/fetch_13dg.py                          # Full build
     python3 scripts/fetch_13dg.py --update                 # Incremental since last filing date
     python3 scripts/fetch_13dg.py --tickers AR,DVN,CVX     # Specific tickers
     python3 scripts/fetch_13dg.py --test                   # 5 test tickers
"""

import argparse, csv, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import duckdb
import edgar
from rapidfuzz import fuzz

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

edgar.set_identity("serge.tismen@gmail.com")

TEST_TICKERS = ["AR", "AM", "DVN", "WBD", "CVX"]
MAX_WORKERS = 4
_db_lock = threading.Lock()
MIN_DATE = "2022-01-01"
FILING_AGENTS = {"Toppan Merrill/FA", "UNKNOWN", "Donnelley Financial Solutions",
                 "ADVISER COMPLIANCE ASSOCIATES LLC"}

# ---------------------------------------------------------------------------
# Filing text parser (regex extraction from filing text)
# ---------------------------------------------------------------------------

def parse_filing(f, filing_type):
    """Parse an edgar Filing object. Returns a record dict or None."""
    try:
        raw_text = f.text() or ""
    except Exception:
        return None
    if not raw_text:
        return None
    if len(raw_text) > 2_000_000:
        raw_text = raw_text[:2_000_000]

    # Strip HTML entities
    text = re.sub(r"<[^>]+>", " ", raw_text)
    for old, new in [("&nbsp;", " "), ("&#160;", " "), ("&#xa0;", " "),
                     ("&amp;", "&"), ("&#38;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&ldquo;", '"'), ("&rdquo;", '"'), ("&lsquo;", "'"), ("&rsquo;", "'")]:
        text = text.replace(old, new)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\s+", " ", text)

    # Extract filer info from header
    h = f.header
    filer_name, filer_cik = "UNKNOWN", ""
    if h.filers:
        ci = h.filers[0].company_information
        filer_name = ci.name or "UNKNOWN"
        filer_cik = (ci.cik or "").zfill(10)
    subject_name, subject_cik = "", ""
    if h.subject_companies:
        sci = h.subject_companies[0].company_information
        subject_name = sci.name or ""
        subject_cik = (sci.cik or "").zfill(10)

    result = {"cusip": None, "pct_owned": None, "shares_owned": None,
              "purpose_text": None, "group_members": None, "report_date": None}

    # CUSIP
    m = re.search(r"CUSIP\s*(?:No\.?|Number|#)?\s*[:\s]*([A-Z0-9]{6,9})", text, re.I)
    if m:
        result["cusip"] = m.group(1).strip()

    # Percentage (Item 11 / cover page)
    for pat in [r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*[\(]?9[\)]?\s+(\d+[\.,]?\d*)\s*%",
                r"Item\s*11[\s.:]+(\d+[\.,]?\d*)\s*%",
                r"Percent\s+of\s+Class[:\s]+(\d+[\.,]?\d*)\s*%",
                r"PERCENT\s+OF\s+CLASS[\s.:]*(\d+[\.,]?\d*)\s*%"]:
        m = re.search(pat, text, re.I)
        if m:
            try: result["pct_owned"] = float(m.group(1).replace(",", ""))
            except ValueError: pass
            break

    # Shares (Item 9)
    for pat in [r"(?:Item\s*9|AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED)[\s.:]*(?:BY\s+EACH\s+REPORTING\s+PERSON)?\s*([\d,]+)",
                r"Amount\s+Beneficially\s+Owned[:\s]*([\d,]+)",
                r"Item\s+9[:\s]+([\d,]+)"]:
        m = re.search(pat, text, re.I)
        if m:
            try: result["shares_owned"] = int(m.group(1).replace(",", ""))
            except ValueError: pass
            break

    # Report date
    for pat in [r"Date\s+of\s+Event\s+Which\s+Requires\s+Filing[^)]*\)\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
                r"Date\s+of\s+Event[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
                r"Date\s+of\s+Event[:\s]*(\d{4}-\d{2}-\d{2})"]:
        m = re.search(pat, text, re.I)
        if m:
            ds = m.group(1).strip()
            for fmt in ["%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"]:
                try: result["report_date"] = datetime.strptime(ds, fmt).strftime("%Y-%m-%d"); break
                except ValueError: pass
            break

    # Purpose (Item 4, 13D only)
    if "13D" in filing_type:
        m4 = re.search(r"Item\s*4\.?\s*(?:Purpose\s+of\s+Transaction|Purpose)[.\s]*", text, re.I)
        if m4:
            after = text[m4.end():m4.end() + 3000]
            m5 = re.search(r"Item\s*5", after, re.I)
            purpose = after[:m5.start()] if m5 else after[:600]
            result["purpose_text"] = re.sub(r"\s+", " ", purpose).strip()[:500] or None

    # Reporting person fallback for filing agents
    if filer_name in FILING_AGENTS:
        for pat in [r"Item\s*1[:\s]+Reporting\s+Person\s*[-–—]\s*([\w\s.,&'/-]+?)(?=\s*(?:Item\s*2|CHECK|\n))",
                    r"NAMES?\s+OF\s+REPORTING\s+PERSONS?\s+((?:[A-Z][A-Za-z.'&,\s-]+){1,5}?)(?=\s*(?:CHECK|2\.|Item\s*2))"]:
            m = re.search(pat, text[:5000], re.I)
            if m:
                name = m.group(1).strip()
                if 3 < len(name) < 100 and name[0].isalpha() and "I.R.S." not in name:
                    filer_name = name
                    break

    intent = "activist" if "13D" in filing_type else "passive"
    return {
        "accession_number": f.accession_no,
        "filer_cik": filer_cik,
        "filer_name": filer_name,
        "subject_cusip": result["cusip"],
        "subject_ticker": None,  # filled by caller
        "subject_name": subject_name,
        "filing_type": filing_type,
        "filing_date": str(f.filing_date),
        "report_date": result["report_date"],
        "pct_owned": result["pct_owned"],
        "shares_owned": result["shares_owned"],
        "aggregate_value": None,
        "intent": intent,
        "is_amendment": "/A" in filing_type,
        "prior_accession": None,
        "purpose_text": result["purpose_text"],
        "group_members": None,
        "manager_cik": None,
    }

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS fetched_tickers_13dg (
        ticker VARCHAR PRIMARY KEY, fetched_at TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS beneficial_ownership (
        accession_number VARCHAR PRIMARY KEY, filer_cik VARCHAR, filer_name VARCHAR,
        subject_cusip VARCHAR, subject_ticker VARCHAR, subject_name VARCHAR,
        filing_type VARCHAR, filing_date DATE, report_date DATE, pct_owned DOUBLE,
        shares_owned BIGINT, aggregate_value DOUBLE, intent VARCHAR,
        is_amendment BOOLEAN, prior_accession VARCHAR, purpose_text VARCHAR,
        group_members VARCHAR, manager_cik VARCHAR, loaded_at TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS beneficial_ownership_current (
        filer_cik VARCHAR, filer_name VARCHAR, subject_ticker VARCHAR,
        subject_cusip VARCHAR, latest_filing_type VARCHAR, latest_filing_date DATE,
        pct_owned DOUBLE, shares_owned BIGINT, intent VARCHAR, crossing_date DATE,
        days_since_filing INTEGER, is_current BOOLEAN, accession_number VARCHAR)""")

def get_existing(con):
    try: return {r[0] for r in con.execute("SELECT accession_number FROM beneficial_ownership").fetchall()}
    except Exception: return set()

def batch_insert(con, records):
    now = datetime.now().isoformat()
    rows = [[r["accession_number"], r["filer_cik"], r["filer_name"],
             r.get("subject_cusip"), r.get("subject_ticker"), r.get("subject_name"),
             r["filing_type"], r["filing_date"], r.get("report_date"),
             r.get("pct_owned"), r.get("shares_owned"), r.get("aggregate_value"),
             r["intent"], r["is_amendment"], r.get("prior_accession"),
             r.get("purpose_text"), r.get("group_members"), r.get("manager_cik"), now]
            for r in records]
    if rows:
        con.executemany("""INSERT OR REPLACE INTO beneficial_ownership
            (accession_number,filer_cik,filer_name,subject_cusip,subject_ticker,
             subject_name,filing_type,filing_date,report_date,pct_owned,shares_owned,
             aggregate_value,intent,is_amendment,prior_accession,purpose_text,
             group_members,manager_cik,loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)

def rebuild_current(con):
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute("""CREATE TABLE beneficial_ownership_current AS
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY filer_cik, subject_ticker ORDER BY filing_date DESC) as rn
            FROM beneficial_ownership WHERE subject_ticker IS NOT NULL)
        SELECT filer_cik, filer_name, subject_ticker, subject_cusip,
            filing_type AS latest_filing_type, filing_date AS latest_filing_date,
            pct_owned, shares_owned, intent, report_date AS crossing_date,
            CAST(CURRENT_DATE - filing_date AS INTEGER) AS days_since_filing,
            CASE WHEN filing_date >= CURRENT_DATE - INTERVAL '2 years' THEN TRUE ELSE FALSE END AS is_current,
            accession_number
        FROM ranked WHERE rn = 1""")
    cnt = con.execute("SELECT COUNT(*) FROM beneficial_ownership_current").fetchone()[0]
    print(f"\n  beneficial_ownership_current rebuilt: {cnt} rows")

def fuzzy_match_managers(con):
    print("\nFuzzy-matching filers to managers table...")
    filers = con.execute("SELECT DISTINCT filer_cik, filer_name FROM beneficial_ownership WHERE filer_name IS NOT NULL AND filer_name != 'UNKNOWN'").fetchall()
    managers = con.execute("SELECT cik, manager_name FROM managers").fetchall()
    mgr_map = {m[0]: m[1] for m in managers}
    matched = fuzzy = 0
    for fc, fn in filers:
        if fc in mgr_map:
            con.execute("UPDATE beneficial_ownership SET manager_cik=? WHERE filer_cik=? AND manager_cik IS NULL", [fc, fc])
            matched += 1
        else:
            best, best_cik = 0, None
            for mc, mn in managers:
                s = fuzz.token_sort_ratio(fn.upper(), mn.upper())
                if s > best: best, best_cik = s, mc
            if best >= 85:
                con.execute("UPDATE beneficial_ownership SET manager_cik=? WHERE filer_cik=? AND manager_cik IS NULL", [best_cik, fc])
                fuzzy += 1
    print(f"  Direct: {matched}, Fuzzy: {fuzzy}, Unmatched: {len(filers)-matched-fuzzy}")

def update_has_13dg(con):
    try: con.execute("ALTER TABLE managers ADD COLUMN has_13dg BOOLEAN DEFAULT FALSE")
    except Exception: pass
    con.execute("UPDATE managers SET has_13dg=TRUE WHERE cik IN (SELECT DISTINCT filer_cik FROM beneficial_ownership)")
    cnt = con.execute("SELECT COUNT(*) FROM managers WHERE has_13dg=TRUE").fetchone()[0]
    print(f"  managers.has_13dg set for {cnt}")

def get_target_tickers(con):
    return [r[0] for r in con.execute("""SELECT ticker FROM holdings
        WHERE quarter=(SELECT MAX(quarter) FROM holdings) AND ticker IS NOT NULL AND ticker!=''
        GROUP BY ticker HAVING SUM(market_value_usd)>500000000
        ORDER BY SUM(market_value_usd) DESC""").fetchall()]

# ---------------------------------------------------------------------------
# Error log
# ---------------------------------------------------------------------------

def init_error_log():
    path = os.path.join(LOG_DIR, "fetch_13dg_errors.csv")
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(["timestamp", "ticker", "accession", "error"])
    return path

def log_error(path, ticker, acc, err):
    with open(path, "a", newline="") as f:
        csv.writer(f).writerow([datetime.now().isoformat(), ticker, acc, str(err)])

# ---------------------------------------------------------------------------
# Core: list and parse filings for one ticker
# ---------------------------------------------------------------------------

def process_ticker(ticker, existing, cusip_map, error_log):
    """List all 13D/G filings for a ticker via edgar library, parse new ones.
    Returns list of record dicts."""
    records = []
    try:
        company = edgar.Company(ticker)
    except Exception as e:
        log_error(error_log, ticker, "", str(e))
        return records

    for form in ["SC 13D", "SC 13G"]:
        try:
            filings = company.get_filings(form=form)
        except Exception:
            continue
        if not filings:
            continue
        for f in filings:
            if str(f.filing_date) < MIN_DATE:
                break  # filings are sorted desc by date
            if f.accession_no in existing:
                continue
            try:
                rec = parse_filing(f, f.form)
                if rec:
                    rec["subject_ticker"] = ticker
                    rec["subject_cusip"] = cusip_map.get(ticker)
                    records.append(rec)
            except Exception as e:
                log_error(error_log, ticker, f.accession_no, str(e))
    return records

# ---------------------------------------------------------------------------
# Post-processing and summary (shared by run/run_update)
# ---------------------------------------------------------------------------

def post_process(con, new_count, check_tickers=None):
    if new_count > 0:
        fuzzy_match_managers(con)
        update_has_13dg(con)
    rebuild_current(con)

    total = con.execute("SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    by_type = con.execute("SELECT filing_type, COUNT(*) FROM beneficial_ownership GROUP BY filing_type ORDER BY COUNT(*) DESC").fetchall()
    print(f"\n{'='*50}\nSUMMARY\n{'='*50}")
    print(f"Total: {total}")
    for ft, cnt in by_type:
        print(f"  {ft}: {cnt}")
    if check_tickers:
        print("\nPer-ticker:")
        for t in check_tickers:
            r = con.execute("SELECT COUNT(*) FILTER (WHERE intent='activist'), COUNT(*) FILTER (WHERE intent='passive') FROM beneficial_ownership WHERE subject_ticker=?", [t]).fetchone()
            print(f"  {t}: 13D={r[0]}, 13G={r[1]}")

# ---------------------------------------------------------------------------
# run() — full build, ticker by ticker
# ---------------------------------------------------------------------------

def run(tickers=None, test_mode=False, max_workers=MAX_WORKERS):
    con = duckdb.connect(DB_PATH)
    create_tables(con)
    error_log = init_error_log()
    existing = get_existing(con)
    print(f"Already loaded: {len(existing)} filings")

    if test_mode:
        target = TEST_TICKERS
    elif tickers:
        target = [t.strip().upper() for t in tickers]
    else:
        target = get_target_tickers(con)
    print(f"Target tickers: {len(target)}")

    # Checkpoint: skip already-fetched tickers
    try:
        fetched = {r[0] for r in con.execute("SELECT ticker FROM fetched_tickers_13dg").fetchall()}
    except Exception:
        fetched = set()
    to_process = [t for t in target if t not in fetched]
    if len(target) - len(to_process) > 0:
        print(f"  Skipping {len(target) - len(to_process)} already-fetched (checkpoint)")
    print(f"  Processing: {len(to_process)}, Workers: {max_workers}")

    cusip_map = {r[0]: r[1] for r in con.execute("SELECT ticker, cusip FROM securities WHERE ticker IS NOT NULL").fetchall()}

    # Workers call edgar (pure I/O, no DB). Main thread collects and writes.
    all_records = []
    checkpoint_buf = []
    done = [0]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_ticker, t, existing, cusip_map, error_log): t
                   for t in to_process}
        for fut in as_completed(futures):
            ticker = futures[fut]
            done[0] += 1
            if done[0] % 200 == 0 or done[0] <= 3 or done[0] == len(to_process):
                print(f"  [{done[0]}/{len(to_process)}] {ticker}...", flush=True)

            try:
                records = fut.result()
            except Exception as e:
                log_error(error_log, ticker, "", str(e))
                records = []

            all_records.extend(records)
            for r in records:
                existing.add(r["accession_number"])
            checkpoint_buf.append(ticker)

            # Periodic DB flush from main thread only
            if len(checkpoint_buf) >= 50:
                now = datetime.now().isoformat()
                with _db_lock:
                    con.executemany("INSERT OR REPLACE INTO fetched_tickers_13dg VALUES (?,?)",
                                    [(t, now) for t in checkpoint_buf])
                checkpoint_buf.clear()
            if len(all_records) >= 500:
                with _db_lock:
                    batch_insert(con, all_records)
                    con.execute("CHECKPOINT")
                all_records.clear()

    # Flush remaining
    if checkpoint_buf:
        now = datetime.now().isoformat()
        con.executemany("INSERT OR REPLACE INTO fetched_tickers_13dg VALUES (?,?)",
                        [(t, now) for t in checkpoint_buf])
    if all_records:
        batch_insert(con, all_records)
    con.execute("CHECKPOINT")

    total_now = con.execute("SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    post_process(con, total_now > 0, TEST_TICKERS if test_mode else tickers)
    con.close()
    print("\nDone.")

# ---------------------------------------------------------------------------
# run_update() — incremental via EDGAR full-index
# ---------------------------------------------------------------------------

def run_update():
    con = duckdb.connect(DB_PATH)
    create_tables(con)
    error_log = init_error_log()
    existing = get_existing(con)
    print(f"Already loaded: {len(existing)} filings")

    row = con.execute("SELECT MAX(filing_date) FROM beneficial_ownership").fetchone()
    last_date = str(row[0]) if row and row[0] else None
    if not last_date:
        print("No existing data — run full build first.")
        con.close()
        return
    print(f"Latest filing: {last_date}")

    # Get tickers we care about
    target_set = set(get_target_tickers(con))
    cusip_map = {r[0]: r[1] for r in con.execute("SELECT ticker, cusip FROM securities WHERE ticker IS NOT NULL").fetchall()}

    # Use edgar.get_filings to scan recent filings globally
    from datetime import date
    last = datetime.strptime(last_date[:10], "%Y-%m-%d").date()
    today = date.today()
    years = list(range(last.year, today.year + 1))

    all_records = []
    for form in ["SC 13D", "SC 13G"]:
        print(f"\n  Scanning {form}...")
        for yr in years:
            for qtr in range(1, 5):
                try:
                    filings = edgar.get_filings(year=yr, quarter=qtr, form=form)
                except Exception:
                    continue
                if not filings:
                    continue
                count = 0
                for f in filings:
                    if str(f.filing_date) < last_date:
                        continue
                    if f.accession_no in existing:
                        continue
                    # Check if this is about one of our target tickers
                    try:
                        h = f.header
                        if h.subject_companies:
                            subj_name = h.subject_companies[0].company_information.name or ""
                        else:
                            continue
                    except Exception:
                        continue
                    # Parse it
                    try:
                        rec = parse_filing(f, f.form)
                        if rec:
                            all_records.append(rec)
                            existing.add(f.accession_no)
                            count += 1
                    except Exception as e:
                        log_error(error_log, "", f.accession_no, str(e))
                if count:
                    print(f"    {yr}Q{qtr} {form}: {count} new", flush=True)

    print(f"\n  Total new filings: {len(all_records)}")
    if all_records:
        batch_insert(con, all_records)
        con.execute("CHECKPOINT")

    post_process(con, len(all_records), None)
    con.close()
    print("\nDone.")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch 13D/G beneficial ownership filings")
    parser.add_argument("--tickers", type=str, help="Comma-separated tickers")
    parser.add_argument("--test", action="store_true", help="Test mode (5 tickers)")
    parser.add_argument("--update", action="store_true", help="Incremental since last filing date")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"Parallel threads (default {MAX_WORKERS})")
    args = parser.parse_args()

    if args.update:
        run_update()
    else:
        t = args.tickers.split(",") if args.tickers else None
        run(tickers=t, test_mode=args.test, max_workers=args.workers)
