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

import argparse, csv, os, re, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import duckdb
import edgar
import requests
from rapidfuzz import fuzz

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
from db import get_db_path, set_test_mode, assert_write_safe, crash_handler
os.makedirs(LOG_DIR, exist_ok=True)

edgar.set_identity("serge.tismen@gmail.com")

TEST_TICKERS = ["AR", "AM", "DVN", "WBD", "CVX"]
MAX_WORKERS_PHASE1 = 4
MAX_WORKERS_PHASE2 = 1  # Sequential — avoids SEC rate limiting entirely
_db_lock = threading.Lock()
_error_log_lock = threading.Lock()
_thread_local = threading.local()
_rate_lock = threading.Lock()
_last_request_time = [0.0]
SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_MAX_RPS = 1  # max requests/second across all workers — SEC rate limit safe
_last_completion_time = [0.0]  # watchdog: track when last filing completed
MIN_DATE = "2022-01-01"
FILING_AGENTS = {"Toppan Merrill/FA", "UNKNOWN", "Donnelley Financial Solutions",
                 "ADVISER COMPLIANCE ASSOCIATES LLC"}


def _retry_edgar(fn, label="", max_retries=5):
    """Call fn() with exponential backoff on 403/429/network errors."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            retryable = any(code in err_str for code in ["403", "429", "rate", "limit", "timeout", "connection"])
            if not retryable or attempt == max_retries - 1:
                raise
            wait = min(10 * (2 ** attempt), 120)
            time.sleep(wait)

# ---------------------------------------------------------------------------
# Filing text parser (regex extraction from filing text)
# ---------------------------------------------------------------------------

def _clean_text(raw):
    """Strip HTML tags and entities from filing text."""
    if len(raw) > 2_000_000:
        raw = raw[:2_000_000]
    text = re.sub(r"<[^>]+>", " ", raw)
    for old, new in [("&nbsp;", " "), ("&#160;", " "), ("&#xa0;", " "),
                     ("&amp;", "&"), ("&#38;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&ldquo;", '"'), ("&rdquo;", '"'), ("&lsquo;", "'"), ("&rsquo;", "'")]:
        text = text.replace(old, new)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    return re.sub(r"\s+", " ", text)


def _extract_fields(text, filing_type):
    """Extract ownership fields from cleaned filing text via regex."""
    result = {"cusip": None, "pct_owned": None, "shares_owned": None,
              "purpose_text": None, "report_date": None, "reporting_person": None}

    m = re.search(r"CUSIP\s*(?:No\.?|Number|#)?\s*[:\s]*([A-Z0-9]{6,9})", text, re.I)
    if m: result["cusip"] = m.group(1).strip()

    for pat in [r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*[\(]?9[\)]?\s+(\d+[\.,]?\d*)\s*%",
                r"Item\s*11[\s.:]+(\d+[\.,]?\d*)\s*%",
                r"Percent\s+of\s+Class[:\s]+(\d+[\.,]?\d*)\s*%",
                r"PERCENT\s+OF\s+CLASS[\s.:]*(\d+[\.,]?\d*)\s*%"]:
        m = re.search(pat, text, re.I)
        if m:
            try: result["pct_owned"] = float(m.group(1).replace(",", ""))
            except ValueError: pass
            break

    for pat in [r"(?:Item\s*9|AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED)[\s.:]*(?:BY\s+EACH\s+REPORTING\s+PERSON)?\s*([\d,]+)",
                r"Amount\s+Beneficially\s+Owned[:\s]*([\d,]+)",
                r"Item\s+9[:\s]+([\d,]+)"]:
        m = re.search(pat, text, re.I)
        if m:
            try: result["shares_owned"] = int(m.group(1).replace(",", ""))
            except ValueError: pass
            break

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

    if "13D" in filing_type:
        m4 = re.search(r"Item\s*4\.?\s*(?:Purpose\s+of\s+Transaction|Purpose)[.\s]*", text, re.I)
        if m4:
            after = text[m4.end():m4.end() + 3000]
            m5 = re.search(r"Item\s*5", after, re.I)
            purpose = after[:m5.start()] if m5 else after[:600]
            result["purpose_text"] = re.sub(r"\s+", " ", purpose).strip()[:500] or None

    for pat in [r"Item\s*1[:\s]+Reporting\s+Person\s*[-–—]\s*([\w\s.,&'/-]+?)(?=\s*(?:Item\s*2|CHECK|\n))",
                r"NAMES?\s+OF\s+REPORTING\s+PERSONS?\s+((?:[A-Z][A-Za-z.'&,\s-]+){1,5}?)(?=\s*(?:CHECK|2\.|Item\s*2))"]:
        m = re.search(pat, text[:5000], re.I)
        if m:
            name = m.group(1).strip()
            if 3 < len(name) < 100 and name[0].isalpha() and "I.R.S." not in name:
                result["reporting_person"] = name
                break

    return result

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS fetched_tickers_13dg (
        ticker VARCHAR PRIMARY KEY, fetched_at TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS listed_filings_13dg (
        accession_number VARCHAR PRIMARY KEY, ticker VARCHAR, form VARCHAR,
        filing_date VARCHAR, filer_cik VARCHAR, subject_name VARCHAR,
        subject_cik VARCHAR, listed_at TIMESTAMP)""")
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
        days_since_filing INTEGER, is_current BOOLEAN, accession_number VARCHAR,
        crossed_5pct BOOLEAN, prior_intent VARCHAR, amendment_count INTEGER)""")

def get_existing(con):
    try: return {r[0] for r in con.execute("SELECT accession_number FROM beneficial_ownership").fetchall()}
    except Exception: return set()

def batch_insert(con, records):
    assert_write_safe(con)
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
    assert_write_safe(con)
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute("""CREATE TABLE beneficial_ownership_current AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY filer_cik, subject_ticker ORDER BY filing_date DESC) as rn,
                -- Item 1: count amendments per filer+subject
                COUNT(*) OVER (PARTITION BY filer_cik, subject_ticker) as amendment_count,
                -- Item 4: previous intent (second-most-recent filing)
                LAG(intent) OVER (PARTITION BY filer_cik, subject_ticker ORDER BY filing_date DESC) as next_older_intent
            FROM beneficial_ownership WHERE subject_ticker IS NOT NULL
        ),
        -- Item 3: first 13G filing per filer+subject = first time crossing 5%
        first_13g AS (
            SELECT filer_cik, subject_ticker,
                MIN(filing_date) as first_13g_date
            FROM beneficial_ownership
            WHERE subject_ticker IS NOT NULL AND filing_type LIKE 'SC 13G%'
            GROUP BY filer_cik, subject_ticker
        )
        SELECT r.filer_cik, r.filer_name, r.subject_ticker, r.subject_cusip,
            r.filing_type AS latest_filing_type, r.filing_date AS latest_filing_date,
            r.pct_owned, r.shares_owned, r.intent, r.report_date AS crossing_date,
            CAST(CURRENT_DATE - r.filing_date AS INTEGER) AS days_since_filing,
            CASE WHEN r.filing_date >= CURRENT_DATE - INTERVAL '2 years' THEN TRUE ELSE FALSE END AS is_current,
            r.accession_number,
            -- Item 3: crossed 5% if there's any 13G filing for this pair
            g.first_13g_date IS NOT NULL AS crossed_5pct,
            -- Item 4: prior intent from the second-most-recent filing
            r.next_older_intent AS prior_intent,
            -- Item 1: amendment count (1 = original only, 2+ = has amendments)
            r.amendment_count
        FROM ranked r
        LEFT JOIN first_13g g ON r.filer_cik = g.filer_cik AND r.subject_ticker = g.subject_ticker
        WHERE r.rn = 1""")
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
            csv.writer(f).writerow(["timestamp", "ticker", "accession", "error_type", "error_message"])
    return path

def log_error(path, ticker, acc, error):
    """Thread-safe error logging with exception type."""
    if isinstance(error, Exception):
        err_type = type(error).__name__
        err_msg = str(error)
    else:
        err_type = "Error"
        err_msg = str(error)
    with _error_log_lock:
        with open(path, "a", newline="") as f:
            csv.writer(f).writerow([datetime.now().isoformat(), ticker, acc, err_type, err_msg])

# ---------------------------------------------------------------------------
# Core: list and parse filings for one ticker
# ---------------------------------------------------------------------------

def list_ticker_filings(ticker, existing, error_log):
    """List new 13D/G filings for a ticker. Returns Filing objects for Phase 2.
    Returns list of (Filing, ticker) tuples — Filing objects carry cached data
    so Phase 2 can call f.text() without an extra HTTP round-trip."""
    time.sleep(0.1)
    try:
        company = _retry_edgar(lambda: edgar.Company(ticker), f"Company({ticker})")
    except Exception as e:
        log_error(error_log, ticker, "", e)
        return []

    results = []
    for form in ["SC 13D", "SC 13G"]:
        try:
            filings = _retry_edgar(lambda f=form: company.get_filings(form=f), f"get_filings({form})")
        except Exception as e:
            log_error(error_log, ticker, "", e)
            continue
        if not filings:
            continue
        for f in filings:
            if str(f.filing_date) < MIN_DATE:
                break
            if f.accession_no in existing:
                continue
            results.append(f)
    return results


def parse_one_filing(filing, ticker, cusip_map, error_log):
    """Parse a Filing object (from Phase 1). No edgar.find() — uses the object directly."""
    acc = filing.accession_no
    form = filing.form
    filer_cik = acc.split("-")[0]

    try:
        raw_text = _retry_edgar(lambda: filing.text(), f"text({acc})")
    except Exception as e:
        log_error(error_log, ticker, acc, e)
        return None
    if not raw_text:
        log_error(error_log, ticker, acc, "empty filing text")
        return None

    text = _clean_text(raw_text)
    fields = _extract_fields(text, form)

    # Filer name from header (cached on the Filing object — no extra HTTP)
    filer_name = "UNKNOWN"
    try:
        h = filing.header
        if h.filers:
            filer_name = h.filers[0].company_information.name or "UNKNOWN"
    except Exception as e:
        log_error(error_log, ticker, acc, Exception(f"header parse: {e}"))
    if filer_name in FILING_AGENTS and fields.get("reporting_person"):
        filer_name = fields["reporting_person"]

    subject_name = str(filing.company) if hasattr(filing, "company") else ""

    return {
        "accession_number": acc,
        "filer_cik": filer_cik,
        "filer_name": filer_name,
        "subject_cusip": fields.get("cusip") or cusip_map.get(ticker),
        "subject_ticker": ticker,
        "subject_name": subject_name,
        "filing_type": form,
        "filing_date": str(filing.filing_date),
        "report_date": fields.get("report_date"),
        "pct_owned": fields.get("pct_owned"),
        "shares_owned": fields.get("shares_owned"),
        "aggregate_value": None,
        "intent": "activist" if "13D" in form else "passive",
        "is_amendment": "/A" in form,
        "prior_accession": None,
        "purpose_text": fields.get("purpose_text"),
        "group_members": None,
        "manager_cik": None,
    }

def _get_session():
    """Per-thread requests.Session for connection reuse."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(SEC_HEADERS)
        _thread_local.session = s
    return _thread_local.session


def _rate_limit():
    """Global rate limiter — enforces SEC_MAX_RPS across all threads."""
    min_interval = 1.0 / SEC_MAX_RPS
    with _rate_lock:
        now = time.time()
        elapsed = now - _last_request_time[0]
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request_time[0] = time.time()


def _download_filing_text(acc, subject_cik):
    """Download filing text via direct URL. Rate-limited, Retry-After aware."""
    cik_raw = subject_cik.lstrip("0") or "0"
    acc_path = acc.replace("-", "")
    session = _get_session()
    for base_cik in [cik_raw, acc.split("-")[0].lstrip("0") or "0"]:
        url = f"https://www.sec.gov/Archives/edgar/data/{base_cik}/{acc_path}/{acc}.txt"
        for attempt in range(2):
            _rate_limit()
            try:
                resp = session.get(url, timeout=10)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = min(int(retry_after), 30)
                        except ValueError:
                            wait = 10
                    else:
                        wait = 10
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"  429 at {ts} acc={acc[:20]} attempt={attempt+1} wait={wait}s", flush=True)
                    time.sleep(wait)
                    continue
                if resp.status_code == 403:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"  403 at {ts} acc={acc[:20]} — backing off 15s", flush=True)
                    time.sleep(15)
                    continue
                break  # 404 or other — try next CIK
            except requests.RequestException as e:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"  NET ERR at {ts} acc={acc[:20]}: {e}", flush=True)
                time.sleep(2)
    return None


def parse_one_filing_by_acc(acc, ticker, form, filing_date, filer_cik,
                            subject_name, subject_cik, cusip_map, error_log):
    """Parse a filing by direct URL download (resume path — no edgar.find)."""
    raw_text = _download_filing_text(acc, subject_cik)
    if not raw_text:
        log_error(error_log, ticker, acc, "could not download filing text")
        return None

    text = _clean_text(raw_text)
    fields = _extract_fields(text, form)

    filer_name = filer_cik  # fallback — no header available in direct download
    if fields.get("reporting_person"):
        filer_name = fields["reporting_person"]

    return {
        "accession_number": acc,
        "filer_cik": filer_cik,
        "filer_name": filer_name,
        "subject_cusip": fields.get("cusip") or cusip_map.get(ticker),
        "subject_ticker": ticker,
        "subject_name": subject_name,
        "filing_type": form,
        "filing_date": filing_date,
        "report_date": fields.get("report_date"),
        "pct_owned": fields.get("pct_owned"),
        "shares_owned": fields.get("shares_owned"),
        "aggregate_value": None,
        "intent": "activist" if "13D" in form else "passive",
        "is_amendment": "/A" in form,
        "prior_accession": None,
        "purpose_text": fields.get("purpose_text"),
        "group_members": None,
        "manager_cik": None,
    }


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

def run_phase1(tickers=None, test_mode=False, max_workers=MAX_WORKERS_PHASE1):
    """Phase 1: List filings per ticker, persist to listed_filings_13dg."""
    con = duckdb.connect(get_db_path())
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

    try:
        fetched = {r[0] for r in con.execute("SELECT ticker FROM fetched_tickers_13dg").fetchall()}
    except Exception:
        fetched = set()
    to_process = [t for t in target if t not in fetched]
    if len(target) - len(to_process) > 0:
        print(f"  Skipping {len(target) - len(to_process)} already-fetched (checkpoint)")
    print(f"  Processing: {len(to_process)}, Workers: {max_workers}")

    print(f"\n--- Phase 1: Listing filings ({max_workers} workers) ---")
    phase1_new = 0
    filing_cache = {}
    done = [0]
    checkpoint_buf = []
    listing_buf = []

    def _flush_listings():
        nonlocal listing_buf
        if not listing_buf:
            return
        batch = listing_buf
        listing_buf = []
        now = datetime.now().isoformat()
        con.executemany(
            "INSERT OR IGNORE INTO listed_filings_13dg VALUES (?,?,?,?,?,?,?,?)",
            [(acc, tk, fm, fd, fc, sn, sc, now) for acc, tk, fm, fd, fc, sn, sc in batch])

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(list_ticker_filings, t, existing, error_log): t for t in to_process}
        for fut in as_completed(futures):
            ticker = futures[fut]
            done[0] += 1
            if done[0] % 200 == 0 or done[0] <= 3 or done[0] == len(to_process):
                print(f"  [{done[0]}/{len(to_process)}] {ticker}...", flush=True)
            try:
                for filing in fut.result():
                    acc = filing.accession_no
                    existing.add(acc)
                    filing_cache[acc] = filing
                    listing_buf.append((
                        acc, ticker, filing.form, str(filing.filing_date),
                        acc.split("-")[0],
                        str(filing.company) if hasattr(filing, "company") else "",
                        str(filing.cik) if hasattr(filing, "cik") else "",
                    ))
                    phase1_new += 1
            except Exception as e:
                log_error(error_log, ticker, "", e)
            checkpoint_buf.append(ticker)
            if len(checkpoint_buf) >= 50:
                now = datetime.now().isoformat()
                con.executemany("INSERT OR REPLACE INTO fetched_tickers_13dg VALUES (?,?)",
                                [(t, now) for t in checkpoint_buf])
                checkpoint_buf.clear()
                _flush_listings()

    if checkpoint_buf:
        now = datetime.now().isoformat()
        con.executemany("INSERT OR REPLACE INTO fetched_tickers_13dg VALUES (?,?)",
                        [(t, now) for t in checkpoint_buf])
    _flush_listings()
    con.execute("CHECKPOINT")

    listed = con.execute("SELECT COUNT(*) FROM listed_filings_13dg").fetchone()[0]
    print(f"  Phase 1 complete: {phase1_new} new, {listed} total listed")
    con.close()
    return filing_cache


def run_phase2(max_workers=MAX_WORKERS_PHASE2, filing_cache=None, test_mode=False):
    """Phase 2: Parse all unparsed filings from listed_filings_13dg."""
    con = duckdb.connect(get_db_path())
    create_tables(con)
    error_log = init_error_log()
    filing_cache = filing_cache or {}

    cusip_map = {r[0]: r[1] for r in con.execute("SELECT ticker, cusip FROM securities WHERE ticker IS NOT NULL").fetchall()}

    unparsed = con.execute("""
        SELECT l.accession_number, l.ticker, l.form, l.filing_date, l.filer_cik,
               l.subject_name, l.subject_cik
        FROM listed_filings_13dg l
        WHERE l.accession_number NOT IN (SELECT accession_number FROM beneficial_ownership)
    """).fetchall()

    if not unparsed:
        print("  No unparsed filings — all up to date.")
        con.close()
        return

    cached = [(acc, tk) for acc, tk, *_ in unparsed if acc in filing_cache]
    uncached = [(acc, tk, fm, fd, fc, sn, sc) for acc, tk, fm, fd, fc, sn, sc in unparsed if acc not in filing_cache]
    if cached:
        print(f"    {len(cached)} from this session (cached), {len(uncached)} from prior session (will re-fetch)")
    else:
        print(f"    {len(uncached)} from prior session (will re-fetch)")

    total = len(unparsed)
    print(f"\n--- Phase 2: Parsing {total} filings (sequential, {SEC_MAX_RPS} req/s) ---", flush=True)
    all_records = []
    errors = 0
    done_count = 0
    t_start = time.time()

    # Process sequentially — avoids thread contention and SEC rate limiting
    work_items = [(acc, tk, fm, fd, fc, sn, sc) for acc, tk, fm, fd, fc, sn, sc in uncached]
    # Prepend cached items
    for acc, tk in cached:
        work_items.insert(0, (acc, tk, None, None, None, None, None))

    for item in work_items:
        acc, tk = item[0], item[1]
        done_count += 1
        try:
            if acc in filing_cache:
                rec = parse_one_filing(filing_cache[acc], tk, cusip_map, error_log)
            else:
                _, _, fm, fd, fc, sn, sc = item
                rec = parse_one_filing_by_acc(acc, tk, fm, fd, fc, sn, sc, cusip_map, error_log)
            if rec:
                all_records.append(rec)
            else:
                errors += 1
        except Exception as e:
            log_error(error_log, tk, acc, e)
            errors += 1

        if done_count % 50 == 0 or done_count == total:
            elapsed = time.time() - t_start
            rate = done_count / elapsed * 60 if elapsed > 0 else 0
            print(f"  [{done_count}/{total}] ok={done_count-errors} err={errors} {rate:.0f}/min", flush=True)

        if len(all_records) >= 200:
            batch_insert(con, all_records)
            con.execute("CHECKPOINT")
            all_records.clear()

    if all_records:
        batch_insert(con, all_records)
    con.execute("CHECKPOINT")

    total = con.execute("SELECT COUNT(*) FROM beneficial_ownership").fetchone()[0]
    print(f"  Phase 2 complete: {total} total filings in DB")
    con.close()


def run_phase3(test_mode=False, tickers=None):
    """Phase 3: Post-processing — rebuild current view, fuzzy match, update flags."""
    con = duckdb.connect(get_db_path())
    create_tables(con)
    post_process(con, True, TEST_TICKERS if test_mode else tickers)
    con.close()
    print("\nPhase 3 complete.")


def run(tickers=None, test_mode=False, max_workers=MAX_WORKERS_PHASE1):
    """Full pipeline: Phase 1 → Phase 2 → Phase 3."""
    filing_cache = run_phase1(tickers=tickers, test_mode=test_mode, max_workers=max_workers)
    run_phase2(max_workers=max_workers, filing_cache=filing_cache, test_mode=test_mode)
    run_phase3(test_mode=test_mode, tickers=tickers)
    print("\nDone.")

# ---------------------------------------------------------------------------
# run_update() — incremental via EDGAR full-index
# ---------------------------------------------------------------------------

def run_update():
    con = duckdb.connect(get_db_path())
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
                    filings = _retry_edgar(
                        lambda y=yr, q=qtr, fm=form: edgar.get_filings(year=y, quarter=q, form=fm))
                except Exception as e:
                    log_error(error_log, "", f"{yr}Q{qtr}", e)
                    continue
                if not filings:
                    continue
                count = 0
                for f in filings:
                    if str(f.filing_date) < last_date:
                        continue
                    if f.accession_no in existing:
                        continue
                    acc = f.accession_no
                    filer_cik = acc.split("-")[0]
                    try:
                        raw_text = _retry_edgar(lambda: f.text(), f"text({acc})")
                        if not raw_text:
                            log_error(error_log, "", acc, "empty filing text")
                            continue
                        text = _clean_text(raw_text)
                        fields = _extract_fields(text, f.form)
                    except Exception as e:
                        log_error(error_log, "", acc, e)
                        continue
                    filer_name = "UNKNOWN"
                    subject_name = ""
                    try:
                        h = f.header
                        if h.filers:
                            filer_name = h.filers[0].company_information.name or "UNKNOWN"
                        if h.subject_companies:
                            subject_name = h.subject_companies[0].company_information.name or ""
                    except Exception as e:
                        log_error(error_log, "", acc, Exception(f"header parse: {e}"))
                    if filer_name in FILING_AGENTS and fields.get("reporting_person"):
                        filer_name = fields["reporting_person"]
                    rec = {
                        "accession_number": acc, "filer_cik": filer_cik,
                        "filer_name": filer_name,
                        "subject_cusip": fields.get("cusip"),
                        "subject_ticker": None, "subject_name": subject_name,
                        "filing_type": f.form, "filing_date": str(f.filing_date),
                        "report_date": fields.get("report_date"),
                        "pct_owned": fields.get("pct_owned"),
                        "shares_owned": fields.get("shares_owned"),
                        "aggregate_value": None,
                        "intent": "activist" if "13D" in f.form else "passive",
                        "is_amendment": "/A" in f.form, "prior_accession": None,
                        "purpose_text": fields.get("purpose_text"),
                        "group_members": None, "manager_cik": None,
                    }
                    all_records.append(rec)
                    existing.add(acc)
                    count += 1
                    time.sleep(0.1)
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

def _seed_test_db():
    """Copy read-only reference tables from production to test DB."""
    from db import PROD_DB, TEST_DB
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    # Create test DB and copy reference tables from production
    prod = duckdb.connect(PROD_DB, read_only=True)
    test = duckdb.connect(TEST_DB)
    for table in ["holdings", "securities", "managers", "market_data", "filings",
                   "fund_holdings", "fund_universe"]:
        try:
            df = prod.execute(f"SELECT * FROM {table}").fetchdf()
            test.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
        except Exception:
            pass
    prod.close()
    test.close()
    print(f"  Test DB seeded: {TEST_DB}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch 13D/G beneficial ownership filings")
    parser.add_argument("--tickers", type=str, help="Comma-separated tickers")
    parser.add_argument("--test", action="store_true", help="Test mode (5 tickers, separate DB)")
    parser.add_argument("--update", action="store_true", help="Incremental since last filing date")
    parser.add_argument("--workers", type=int, default=None,
                        help="Override thread count (default: 4 phase1, 2 phase2)")
    parser.add_argument("--phase1-only", action="store_true", help="Run Phase 1 only (list filings)")
    parser.add_argument("--phase2-only", action="store_true", help="Run Phase 2 only (parse filings)")
    parser.add_argument("--phase3-only", action="store_true", help="Run Phase 3 only (post-process)")
    args = parser.parse_args()

    if args.test:
        set_test_mode(True)
        # Only seed test DB on Phase 1 or full run (not Phase 2/3 which read prior state)
        if not args.phase2_only and not args.phase3_only:
            _seed_test_db()

    def _main():
        t = args.tickers.split(",") if args.tickers else None
        w1 = args.workers or MAX_WORKERS_PHASE1
        w2 = args.workers or MAX_WORKERS_PHASE2
        if args.update:
            run_update()
        elif args.phase1_only:
            run_phase1(tickers=t, test_mode=args.test, max_workers=w1)
        elif args.phase2_only:
            run_phase2(max_workers=w2, test_mode=args.test)
        elif args.phase3_only:
            run_phase3(test_mode=args.test, tickers=t)
        else:
            run(tickers=t, test_mode=args.test, max_workers=w1)

    crash_handler("fetch_13dg")(_main)
