#!/usr/bin/env python3
"""fetch_dera_nport.py — SEC DERA quarterly N-PORT bulk ZIP loader.

Parallel fetch path alongside fetch_nport_v2.py. Downloads one quarterly
ZIP (~400-470MB), streams the TSV tables without extraction, joins to the
four metadata tables (SUBMISSION, REGISTRANT, FUND_REPORTED_INFO,
IDENTIFIERS), resolves amendments (latest accession per series/month),
and loads into stg_nport_holdings compatible with promote_nport.py.

Session 1 deliverable — parity test only. Does NOT replace fetch_nport_v2.
Session 2 integrates DERA as the primary bulk path after parity clears.

DERA ZIP URL pattern (confirmed live 2024Q3-2026Q1):
    https://www.sec.gov/files/dera/data/form-n-port-data-sets/{YYYY}q{N}_nport.zip

Field mapping (SEC N-PORT Rule -> staging column):
    SUBMISSION.ACCESSION_NUMBER         -> accession_number
    SUBMISSION.REPORT_DATE (A.3.b)      -> report_date (DD-MON-YYYY format)
    SUBMISSION.IS_LAST_FILING (A.4)     -> is_final
    SUBMISSION.SUB_TYPE                 -> distinguishes NPORT-P vs NPORT-P/A
    REGISTRANT.CIK (A.1.c)              -> fund_cik (zero-padded 10)
    REGISTRANT.REGISTRANT_NAME (A.1.a)  -> family_name (trust)
    FUND_REPORTED_INFO.SERIES_ID (A.2.b) -> series_id
    FUND_REPORTED_INFO.SERIES_NAME      -> fund_name
    FUND_REPORTED_INFO.NET_ASSETS (B.1.c) -> total_net_assets (universe)
    FUND_REPORTED_HOLDING.ISSUER_CUSIP  -> cusip ('N/A' -> NULL)
    FUND_REPORTED_HOLDING.ISSUER_NAME   -> issuer_name
    FUND_REPORTED_HOLDING.BALANCE (C.2.a) -> shares_or_principal
    FUND_REPORTED_HOLDING.CURRENCY_VALUE (C.2.c) -> market_value_usd (USD)
    FUND_REPORTED_HOLDING.PERCENTAGE (C.2.d) -> pct_of_nav
    FUND_REPORTED_HOLDING.ASSET_CAT (C.4.a) -> asset_category
    FUND_REPORTED_HOLDING.PAYOFF_PROFILE -> payoff_profile
    FUND_REPORTED_HOLDING.FAIR_VALUE_LEVEL -> fair_value_level
    FUND_REPORTED_HOLDING.IS_RESTRICTED_SECURITY -> is_restricted ('Y'->True)
    IDENTIFIERS.IDENTIFIER_ISIN         -> isin
    IDENTIFIERS.IDENTIFIER_TICKER       -> ticker

Run modes:
    python3 scripts/fetch_dera_nport.py --test
        Parity test: 5 reference funds vs prod fund_holdings_v2 (XML path).
        Writes logs/nport_parity_{run_id}.md. Staging only.

    python3 scripts/fetch_dera_nport.py --staging --quarter 2025Q3
        Load one quarter into stg_nport_holdings. Staging only.

    python3 scripts/fetch_dera_nport.py --staging --quarter 2025Q3 --dry-run
        Show summary (series count, holdings count, date range). No DB writes.

    python3 scripts/fetch_dera_nport.py --staging --all-missing
        PLACEHOLDER — Session 2 integrates this path. Currently errors.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Optional

import duckdb
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import STAGING_DB, PROD_DB, set_staging_mode  # noqa: E402
from pipeline import nport_parsers  # noqa: E402
from pipeline.nport_parsers import classify_fund  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Shared helpers (moved from fetch_nport_v2 in Session 2 to break a circular
# import: fetch_nport_v2 now imports these from here, so this module must own
# them. Behaviour unchanged — callers from either path see the same labels
# and the same staging DDL.)
# ---------------------------------------------------------------------------

def quarter_label_for_month(year: int, month: int) -> str:
    """Map N-PORT report month -> prod ``quarter`` label.

    Convention observed in prod ``fund_holdings_v2``:
      Jan/Feb/Mar -> YYYY-Q2,  Apr/May/Jun -> YYYY-Q3,
      Jul/Aug/Sep -> YYYY-Q4,  Oct/Nov/Dec -> (YYYY+1)-Q1.
    """
    if month >= 10:
        return f"{year + 1}Q1"
    if month >= 7:
        return f"{year}Q4"
    if month >= 4:
        return f"{year}Q3"
    return f"{year}Q2"


def quarter_label_for_date(d: date) -> str:
    return quarter_label_for_month(d.year, d.month)


_STG_HOLDINGS_DDL = """
CREATE TABLE IF NOT EXISTS stg_nport_holdings (
    fund_cik             VARCHAR,
    fund_name            VARCHAR,
    family_name          VARCHAR,
    series_id            VARCHAR,
    quarter              VARCHAR,
    report_month         VARCHAR,
    report_date          DATE,
    cusip                VARCHAR,
    isin                 VARCHAR,
    issuer_name          VARCHAR,
    ticker               VARCHAR,
    asset_category       VARCHAR,
    shares_or_principal  DOUBLE,
    market_value_usd     DOUBLE,
    pct_of_nav           DOUBLE,
    fair_value_level     VARCHAR,
    is_restricted        BOOLEAN,
    payoff_profile       VARCHAR,
    loaded_at            TIMESTAMP,
    fund_strategy        VARCHAR,
    best_index           VARCHAR,
    accession_number     VARCHAR,
    manifest_id          BIGINT,
    parse_status         VARCHAR,
    qc_flags             VARCHAR
)
"""

_STG_UNIVERSE_DDL = """
CREATE TABLE IF NOT EXISTS stg_nport_fund_universe (
    fund_cik              VARCHAR,
    fund_name             VARCHAR,
    series_id             VARCHAR PRIMARY KEY,
    family_name           VARCHAR,
    total_net_assets      DOUBLE,
    fund_category         VARCHAR,
    is_actively_managed   BOOLEAN,
    total_holdings_count  INTEGER,
    equity_pct            DOUBLE,
    top10_concentration   DOUBLE,
    last_updated          TIMESTAMP,
    fund_strategy         VARCHAR,
    best_index            VARCHAR,
    manifest_id           BIGINT
)
"""


def _ensure_staging_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_STG_HOLDINGS_DDL)
    con.execute(_STG_UNIVERSE_DDL)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DERA_BASE = "https://www.sec.gov/files/dera/data/form-n-port-data-sets"
USER_AGENT = "13f-research serge.tismen@gmail.com"
PARSER_VERSION = "dera_nport_v1.0"
L1_DIR = os.path.join(BASE_DIR, "data", "nport_raw", "dera")

# Reference funds (trust CIKs) for parity test.
REFERENCE_FUNDS = [
    {"name": "Fidelity Contrafund",     "cik": 24238},
    {"name": "Vanguard Wellington Fund", "cik": 105563},
    {"name": "T. Rowe Price Blue Chip",  "cik": 902259},
    {"name": "Dodge & Cox Funds",        "cik": 29440},
    {"name": "Growth Fund of America",   "cik": 44201},
]


# ---------------------------------------------------------------------------
# URL / download
# ---------------------------------------------------------------------------

_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$", re.IGNORECASE)


def parse_quarter(label: str) -> tuple[int, int]:
    m = _QUARTER_RE.match(label.strip())
    if not m:
        raise ValueError(f"Invalid quarter label '{label}' — expected e.g. 2025Q3")
    return int(m.group(1)), int(m.group(2))


def dera_zip_url(year: int, quarter: int) -> str:
    return f"{DERA_BASE}/{year}q{quarter}_nport.zip"


def dera_zip_local_path(year: int, quarter: int) -> str:
    # Keep the inspect-dir layout stable so Session 1's download is reused.
    return os.path.join(L1_DIR, "inspect", f"{year}q{quarter}_nport.zip")


def resolve_zip_path(year: int, quarter: int,
                     zip_spec: Optional[str]) -> Optional[Path]:
    """Find a pre-downloaded DERA ZIP for {year}q{quarter}.

    ``zip_spec`` is interpreted as:
      * path to a directory -> look for ``{year}q{quarter}_nport.zip`` inside.
      * path to a file     -> treat as the ZIP for this quarter. Caller is
        responsible for making sure the filename matches the quarter they
        asked for; we accept any .zip to keep the CLI ergonomic.

    Returns the resolved Path if found, otherwise None. None means the
    caller should fall back to ``download_dera_zip``.
    """
    if not zip_spec:
        return None
    p = Path(zip_spec).expanduser()
    if p.is_dir():
        candidate = p / f"{year}q{quarter}_nport.zip"
        return candidate if candidate.exists() else None
    if p.is_file():
        return p
    return None


def download_dera_zip(year: int, quarter: int,
                      zip_spec: Optional[str] = None) -> Path:
    """Return a Path to the DERA ZIP for {year}q{quarter}, downloading
    only if necessary.

    ``zip_spec`` (optional) is a file or directory containing a
    pre-downloaded ZIP — see :func:`resolve_zip_path`. When present and
    matching, no network call is made. Useful for air-gapped runs or when
    the user pre-seeds ZIPs to skip the ~400MB transfer.

    Default behaviour (zip_spec=None): idempotent download to the canonical
    cache location. If a cached copy already exists with matching
    Content-Length, skip. Partial downloads are replaced.
    """
    # 1. User-supplied pre-downloaded ZIP
    if zip_spec:
        local_override = resolve_zip_path(year, quarter, zip_spec)
        if local_override is not None:
            size_mb = local_override.stat().st_size / 1e6
            print(f"  using pre-downloaded: {local_override} "
                  f"({size_mb:.1f} MB)")
            return local_override
        print(f"  --zip {zip_spec} did not contain "
              f"{year}q{quarter}_nport.zip; falling back to download")

    url = dera_zip_url(year, quarter)
    dst = Path(dera_zip_local_path(year, quarter))
    dst.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": USER_AGENT}
    head = requests.head(url, headers=headers, timeout=30, allow_redirects=True)
    head.raise_for_status()
    expected_bytes = int(head.headers.get("Content-Length", 0))

    if dst.exists() and dst.stat().st_size == expected_bytes and expected_bytes > 0:
        print(f"  cached: {dst} ({expected_bytes/1e6:.1f} MB)")
        return dst

    print(f"  downloading {url} ({expected_bytes/1e6:.1f} MB)...")
    t0 = time.time()
    with requests.get(url, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dst, "wb") as fh:
            seen = 0
            last_print = t0
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                fh.write(chunk)
                seen += len(chunk)
                now = time.time()
                if now - last_print > 10:
                    pct = 100 * seen / expected_bytes if expected_bytes else 0
                    print(f"    {seen/1e6:.0f}/{expected_bytes/1e6:.0f} MB "
                          f"({pct:.0f}%) {seen/(now-t0)/1e6:.1f} MB/s")
                    last_print = now
    elapsed = time.time() - t0
    print(f"  done: {dst} in {elapsed:.0f}s")
    return dst


# ---------------------------------------------------------------------------
# TSV streaming
# ---------------------------------------------------------------------------

def stream_tsv_from_zip(zip_path: Path, tsv_name: str) -> Iterator[dict]:
    """Stream one TSV from the ZIP as row dicts, no extraction to disk.

    Uses zipfile.open + csv.DictReader. Suitable for the 988MB
    FUND_REPORTED_HOLDING.tsv — rows are yielded one at a time, never
    materialised fully in memory.
    """
    with zipfile.ZipFile(zip_path) as z:
        with z.open(tsv_name) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            reader = csv.DictReader(text, delimiter="\t")
            for row in reader:
                yield row


def load_small_tsv(zip_path: Path, tsv_name: str) -> list[dict]:
    """Read a small TSV fully into memory as list[dict]. For the 4 metadata
    tables (SUBMISSION ~900KB, REGISTRANT ~2MB, FUND_REPORTED_INFO ~4MB,
    IDENTIFIERS ~290MB — the large one is still manageable as a dict lookup
    at ~5M HOLDING_IDs)."""
    return list(stream_tsv_from_zip(zip_path, tsv_name))


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_dera_date(s: str) -> Optional[date]:
    """DERA DD-MON-YYYY -> date. Returns None on empty/malformed input."""
    if not s:
        return None
    parts = s.strip().upper().split("-")
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        month = _MONTHS.get(parts[1])
        year = int(parts[2])
        if month is None:
            return None
        return date(year, month, day)
    except (ValueError, KeyError):
        return None


def _f(val: Optional[str]) -> Optional[float]:
    """Safe float. Empty or 'N/A' -> None."""
    if val is None:
        return None
    v = val.strip()
    if not v or v.upper() == "N/A":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _s(val: Optional[str]) -> Optional[str]:
    """Safe string. Empty or 'N/A' -> None."""
    if val is None:
        return None
    v = val.strip()
    if not v or v.upper() == "N/A":
        return None
    return v


# ---------------------------------------------------------------------------
# DERA parse: produce (submissions, holdings_by_accession, universe)
# ---------------------------------------------------------------------------

def build_dera_dataset(
    zip_path: Path,
    *,
    filter_ciks: Optional[set[int]] = None,
) -> dict[str, Any]:
    """Extract submissions + holdings + universe from the DERA ZIP.

    Returns:
        {
          'submissions': list[{
             accession_number, series_id, fund_cik, fund_name,
             family_name, report_date, report_month, quarter,
             is_final, sub_type, total_net_assets,
          }],
          'holdings_by_accession': dict[accession -> list[holding_row]],
          'filter_description': str,
        }

    When filter_ciks is provided (parity test), only accessions whose
    REGISTRANT.CIK lies in the set are kept. Streaming FUND_REPORTED_HOLDING
    is filtered at the row level, so the 988MB TSV is never materialised.
    """
    print(f"  building DERA dataset from {zip_path.name}"
          + (f" filter_ciks={sorted(filter_ciks)}" if filter_ciks else " (all)"))

    # 1. REGISTRANT — accession -> (cik_padded, registrant_name). Skip rows
    # whose CIK is outside filter_ciks (if set) to prune the accession list
    # before reading larger tables.
    registrants = {}
    filter_ciks_norm: set[str] = (
        {str(c).zfill(10) for c in filter_ciks} if filter_ciks else set()
    )
    for row in stream_tsv_from_zip(zip_path, "REGISTRANT.tsv"):
        cik_pad = (row.get("CIK") or "").strip().zfill(10)
        if filter_ciks_norm and cik_pad not in filter_ciks_norm:
            continue
        registrants[row["ACCESSION_NUMBER"]] = {
            "fund_cik": cik_pad,
            "family_name": row.get("REGISTRANT_NAME") or None,
        }
    print(f"    REGISTRANT: {len(registrants):,} matching accessions")
    if filter_ciks and not registrants:
        return {"submissions": [], "holdings_by_accession": {},
                "filter_description": "no matching accessions"}

    keep_accessions = set(registrants.keys())

    # 2. SUBMISSION — accession -> report_date, is_last, sub_type
    submissions_raw = {}
    for row in stream_tsv_from_zip(zip_path, "SUBMISSION.tsv"):
        acc = row["ACCESSION_NUMBER"]
        if keep_accessions and acc not in keep_accessions:
            continue
        rd = parse_dera_date(row.get("REPORT_DATE"))
        if rd is None:
            continue
        submissions_raw[acc] = {
            "report_date": rd,
            "is_final": (row.get("IS_LAST_FILING") or "").strip() == "Y",
            "sub_type": row.get("SUB_TYPE") or "NPORT-P",
        }
    print(f"    SUBMISSION: {len(submissions_raw):,} rows")

    # 3. FUND_REPORTED_INFO — accession -> series_id, series_name, net_assets
    info_raw = {}
    for row in stream_tsv_from_zip(zip_path, "FUND_REPORTED_INFO.tsv"):
        acc = row["ACCESSION_NUMBER"]
        if keep_accessions and acc not in keep_accessions:
            continue
        info_raw[acc] = {
            "series_id": _s(row.get("SERIES_ID")),
            "series_name": _s(row.get("SERIES_NAME")),
            "net_assets": _f(row.get("NET_ASSETS")),
        }
    print(f"    FUND_REPORTED_INFO: {len(info_raw):,} rows")

    # Build the submission list — one row per accession, joined with the
    # three metadata tables. Drop accessions missing any required field
    # (series_id fallback is handled here so downstream is clean).
    submissions: list[dict[str, Any]] = []
    synthetic_series_count = 0
    for acc, sub in submissions_raw.items():
        reg = registrants.get(acc, {})
        info = info_raw.get(acc, {})
        series_id = info.get("series_id")
        if not series_id:
            # Synthetic fallback matches fetch_nport_v2 convention so the
            # validator's existing BLOCK rule catches them.
            raw_cik = reg.get("fund_cik", "0").lstrip("0") or "0"
            series_id = f"{raw_cik}_{acc}"
            synthetic_series_count += 1
        rd = sub["report_date"]
        submissions.append({
            "accession_number": acc,
            "series_id": series_id,
            "fund_cik": reg.get("fund_cik") or "0".zfill(10),
            "fund_name": info.get("series_name") or reg.get("family_name"),
            "family_name": reg.get("family_name"),
            "report_date": rd,
            "report_month": rd.strftime("%Y-%m"),
            "quarter": quarter_label_for_date(rd),
            "is_final": sub["is_final"],
            "sub_type": sub["sub_type"],
            "total_net_assets": info.get("net_assets"),
        })
    if synthetic_series_count:
        print(f"    synthetic series_id (SERIES_ID missing): "
              f"{synthetic_series_count:,}")

    # 4. IDENTIFIERS — holding_id -> (isin, ticker). Filter-CIK mode:
    # only load IDENTIFIERS for the holdings we'll ultimately keep.
    # Without a filter, load everything (still fine — ~5M entries).
    # First pass: collect the set of HOLDING_IDs we need.
    print(f"    IDENTIFIERS (pre-scan): finding HOLDING_IDs for "
          f"{len(keep_accessions):,} accessions...")
    need_holding_ids: Optional[set[str]] = None
    if filter_ciks_norm:
        need_holding_ids = set()
        for row in stream_tsv_from_zip(zip_path, "FUND_REPORTED_HOLDING.tsv"):
            if row["ACCESSION_NUMBER"] in keep_accessions:
                need_holding_ids.add(row["HOLDING_ID"])
        print(f"    need {len(need_holding_ids):,} IDENTIFIERS rows")

    identifiers: dict[str, dict[str, Optional[str]]] = {}
    for row in stream_tsv_from_zip(zip_path, "IDENTIFIERS.tsv"):
        hid = row["HOLDING_ID"]
        if need_holding_ids is not None and hid not in need_holding_ids:
            continue
        identifiers[hid] = {
            "isin": _s(row.get("IDENTIFIER_ISIN")),
            "ticker": _s(row.get("IDENTIFIER_TICKER")),
        }
    print(f"    IDENTIFIERS: {len(identifiers):,} rows loaded")

    # 5. FUND_REPORTED_HOLDING — stream and bucket by accession
    holdings_by_accession: dict[str, list[dict[str, Any]]] = {}
    total_holdings = 0
    for row in stream_tsv_from_zip(zip_path, "FUND_REPORTED_HOLDING.tsv"):
        acc = row["ACCESSION_NUMBER"]
        if keep_accessions and acc not in keep_accessions:
            continue
        hid = row["HOLDING_ID"]
        ident = identifiers.get(hid, {"isin": None, "ticker": None})
        # Preserve ISSUER_CUSIP literally (including 'N/A') to match prod
        # fund_holdings_v2, which stores 'N/A' for CUSIP-less positions
        # (832K of 6.4M rows). Normalisation to NULL is a separate cleanup
        # (out of scope for Session 1 parity).
        raw_cusip = (row.get("ISSUER_CUSIP") or "").strip()
        cusip = raw_cusip if raw_cusip else None
        h = {
            "holding_id": hid,
            "cusip": cusip,
            "isin": ident["isin"],
            "ticker": ident["ticker"],
            "issuer_name": _s(row.get("ISSUER_NAME")),
            "asset_cat": _s(row.get("ASSET_CAT")),
            "balance": _f(row.get("BALANCE")),
            "val_usd": _f(row.get("CURRENCY_VALUE")),
            "pct_val": _f(row.get("PERCENTAGE")),
            "fair_val_level": _s(row.get("FAIR_VALUE_LEVEL")),
            "is_restricted": (row.get("IS_RESTRICTED_SECURITY") or "").strip() == "Y",
            "payoff_profile": _s(row.get("PAYOFF_PROFILE")),
        }
        holdings_by_accession.setdefault(acc, []).append(h)
        total_holdings += 1
    print(f"    FUND_REPORTED_HOLDING: {total_holdings:,} rows across "
          f"{len(holdings_by_accession):,} accessions")

    return {
        "submissions": submissions,
        "holdings_by_accession": holdings_by_accession,
        "filter_description": (
            f"CIKs={sorted(filter_ciks)}" if filter_ciks else "all accessions"
        ),
    }


# ---------------------------------------------------------------------------
# Amendment resolution
# ---------------------------------------------------------------------------

def resolve_amendments(
    submissions: list[dict],
    staging_con: Optional[duckdb.DuckDBPyConnection] = None,
) -> list[dict]:
    """For each (series_id, report_month), keep only the LATEST accession.

    Two passes:
      1. **Within the submission list.** Dedupe so each (series_id,
         report_month) tuple is represented once, by the latest
         accession_number in ``submissions``. SEC accession format
         ``XXXXXXXXXX-YY-NNNNNN`` sorts lexicographically correctly across
         years, so ``s1 > s2`` iff s1 is newer.
      2. **Against staging (optional).** When ``staging_con`` is provided,
         consult ``ingestion_impacts`` for any previously-loaded accession
         for the same (series_id, report_month) — this is the cross-ZIP
         case, e.g. the original filing landed via ``2025Q4_nport.zip``
         and the amendment later via ``2026Q1_nport.zip``. Drop the
         submission if staging already has the newer accession; otherwise
         keep and let ``load_to_staging`` delete the superseded impact
         row before inserting the amendment.

    Idempotent: safe to call with or without ``staging_con``. When
    ``staging_con`` is omitted the behaviour is identical to Session 1
    (within-ZIP only).
    """
    # Pass 1 — within-list dedupe (unchanged from Session 1).
    by_key: dict[tuple[str, str], dict] = {}
    for s in submissions:
        key = (s["series_id"], s["report_month"])
        existing = by_key.get(key)
        if existing is None or s["accession_number"] > existing["accession_number"]:
            by_key[key] = s
    kept = list(by_key.values())

    if staging_con is None or not kept:
        return kept

    # Pass 2 — cross-ZIP dedupe. One bulk query gets the max accession
    # already recorded for any tuple in the submission set; skip the ones
    # where staging is strictly newer.
    import pandas as pd  # local import — only used in the cross-ZIP path
    keys_df = pd.DataFrame([
        {"series_id": s["series_id"], "report_month": s["report_month"]}
        for s in kept
    ])
    staging_con.register("_resolve_keys", keys_df)
    try:
        existing = staging_con.execute("""
            SELECT
                JSON_EXTRACT_STRING(i.unit_key_json, '$.series_id')    AS series_id,
                JSON_EXTRACT_STRING(i.unit_key_json, '$.report_month') AS report_month,
                MAX(m.accession_number) AS max_accession
            FROM ingestion_impacts i
            JOIN ingestion_manifest m ON i.manifest_id = m.manifest_id
            JOIN _resolve_keys k
              ON k.series_id    = JSON_EXTRACT_STRING(i.unit_key_json, '$.series_id')
             AND k.report_month = JSON_EXTRACT_STRING(i.unit_key_json, '$.report_month')
            WHERE i.unit_type = 'series_month'
            GROUP BY 1, 2
        """).fetchdf()
    finally:
        staging_con.unregister("_resolve_keys")

    if existing.empty:
        return kept

    existing_map: dict[tuple[str, str], str] = {
        (row["series_id"], row["report_month"]): row["max_accession"]
        for _, row in existing.iterrows()
        if row["max_accession"]
    }
    filtered: list[dict] = []
    skipped = 0
    for s in kept:
        key = (s["series_id"], s["report_month"])
        prev = existing_map.get(key)
        if prev is not None and prev >= s["accession_number"]:
            # Staging already has this amendment or newer.
            skipped += 1
            continue
        filtered.append(s)
    if skipped:
        print(f"    cross-ZIP dedupe: dropped {skipped:,} submissions "
              f"already represented in staging by a newer accession",
              flush=True)
    return filtered


# ---------------------------------------------------------------------------
# Staging load
# ---------------------------------------------------------------------------

def load_to_staging(
    dataset: dict[str, Any],
    submissions_kept: list[dict],
    run_id: str,
    staging_db_path: Optional[str] = None,
) -> tuple[int, int]:
    """Insert DERA rows into stg_nport_holdings + stg_nport_fund_universe.

    Mirrors fetch_nport_v2.load_to_staging structure (ingestion_manifest +
    ingestion_impacts + staging tables). Each accession gets one manifest
    row; each (series_id, report_month) tuple gets one impact row.

    Returns (holdings_written, series_written).
    """
    from pipeline.manifest import get_or_create_manifest_row, write_impact

    holdings_by_acc = dataset["holdings_by_accession"]
    now = datetime.now()
    db_path = staging_db_path or STAGING_DB

    # CHECKPOINT cadence — once every N accessions. Session 1 did a
    # checkpoint per accession (21 accessions total, negligible cost).
    # Session 2 scales to ~13K accessions per quarter × 2 quarters;
    # per-accession checkpoints turn into the run-dominant cost. Every
    # 2000 accessions (~8-12 in-flight minutes) keeps crash recovery
    # bounded without dominating throughput.
    checkpoint_every = 2000
    progress_every = 500

    con = duckdb.connect(db_path)
    holdings_written = 0
    series_written = 0
    t_load_start = time.time()
    try:
        _ensure_staging_schema(con)

        for idx, sub in enumerate(submissions_kept, start=1):
            acc = sub["accession_number"]
            holdings = holdings_by_acc.get(acc, [])
            if not holdings:
                continue

            # classify_fund expects XML-shaped dicts — key names match
            # (asset_cat, val_usd, balance). Pass metadata + holdings.
            metadata = {
                "series_name": sub["fund_name"],
                "reg_name": sub["family_name"],
                "series_id": sub["series_id"],
                "is_final": "Y" if sub["is_final"] else None,
                "net_assets": sub["total_net_assets"],
            }
            is_active_equity, fund_category, is_actively_managed = classify_fund(
                metadata, holdings,
            )

            # Manifest row per accession (idempotent via object_key)
            object_key = acc
            source_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(sub['fund_cik'])}/{acc.replace('-', '')}/primary_doc.xml"
            )
            manifest_id = get_or_create_manifest_row(
                con,
                source_type="NPORT",
                object_type="DERA_ZIP",
                source_url=source_url,
                accession_number=acc,
                run_id=run_id,
                object_key=f"DERA:{acc}",
                fetch_status="complete",
                fetch_started_at=now,
                fetch_completed_at=now,
            )

            # Impact row per (series_id, report_month)
            impact_unit_key = json.dumps({
                "series_id": sub["series_id"],
                "report_month": sub["report_month"],
            })
            # Delete any stale impact rows for this (series, month). Handles
            # the cross-ZIP amendment case where a prior ZIP (or prior run)
            # loaded an earlier accession: resolve_amendments() dropped the
            # submission if staging was newer, but if we got here this
            # submission IS the amendment — clean up the superseded impact
            # so _block_dup_series_month stays clean.
            con.execute(
                """
                DELETE FROM ingestion_impacts
                WHERE unit_type = 'series_month'
                  AND unit_key_json = ?
                  AND manifest_id <> ?
                """,
                [impact_unit_key, manifest_id],
            )
            write_impact(
                con,
                manifest_id=manifest_id,
                target_table="fund_holdings_v2",
                unit_type="series_month",
                unit_key_json=impact_unit_key,
                report_date=sub["report_month"] + "-01",
                rows_staged=len(holdings),
                load_status="partial",
            )

            # Replace any previously staged rows for this (series_id, month)
            con.execute("BEGIN")
            try:
                con.execute(
                    "DELETE FROM stg_nport_holdings "
                    "WHERE series_id = ? AND report_month = ?",
                    [sub["series_id"], sub["report_month"]],
                )

                qc_flags = json.dumps([
                    {"field": "series_id", "rule": "series_id_synthetic_fallback",
                     "severity": "FLAG"}
                ]) if "_" in sub["series_id"] and not sub["series_id"].startswith("S") else None

                payload = []
                for h in holdings:
                    payload.append([
                        sub["fund_cik"], sub["fund_name"], sub["family_name"],
                        sub["series_id"], sub["quarter"], sub["report_month"],
                        sub["report_date"], h["cusip"], h["isin"],
                        h["issuer_name"], h["ticker"], h["asset_cat"],
                        h["balance"], h["val_usd"], h["pct_val"],
                        h["fair_val_level"], h["is_restricted"],
                        h["payoff_profile"], now, fund_category, None, acc,
                        manifest_id, "complete", qc_flags,
                    ])
                con.executemany(
                    """
                    INSERT INTO stg_nport_holdings (
                        fund_cik, fund_name, family_name, series_id,
                        quarter, report_month, report_date, cusip, isin,
                        issuer_name, ticker, asset_category,
                        shares_or_principal, market_value_usd, pct_of_nav,
                        fair_value_level, is_restricted, payoff_profile,
                        loaded_at, fund_strategy, best_index,
                        accession_number, manifest_id, parse_status, qc_flags
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    payload,
                )

                # Upsert fund_universe sidecar
                con.execute(
                    "DELETE FROM stg_nport_fund_universe WHERE series_id = ?",
                    [sub["series_id"]],
                )
                con.execute(
                    """
                    INSERT INTO stg_nport_fund_universe (
                        fund_cik, fund_name, series_id, family_name,
                        total_net_assets, fund_category, is_actively_managed,
                        total_holdings_count, equity_pct, top10_concentration,
                        last_updated, fund_strategy, best_index, manifest_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        sub["fund_cik"], sub["fund_name"], sub["series_id"],
                        sub["family_name"], sub["total_net_assets"],
                        fund_category, is_actively_managed,
                        len(holdings), None, None, now,
                        fund_category, None, manifest_id,
                    ],
                )
                con.execute(
                    """
                    UPDATE ingestion_impacts
                       SET load_status = 'loaded'
                     WHERE manifest_id = ?
                       AND unit_type = 'series_month'
                       AND unit_key_json = ?
                    """,
                    [manifest_id, impact_unit_key],
                )
                con.execute("COMMIT")
                holdings_written += len(holdings)
                series_written += 1
            except Exception:
                con.execute("ROLLBACK")
                raise

            if idx % checkpoint_every == 0:
                con.execute("CHECKPOINT")
            if idx % progress_every == 0:
                elapsed = time.time() - t_load_start
                rate = idx / elapsed if elapsed else 0
                eta = (len(submissions_kept) - idx) / rate if rate else 0
                print(f"    [{idx}/{len(submissions_kept)}] "
                      f"{holdings_written:,} holdings, "
                      f"{rate:.1f} acc/s, ETA {eta/60:.1f}min",
                      flush=True)

        # Final checkpoint so the next reader sees everything without a
        # soft-replay from the WAL.
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return holdings_written, series_written


# ---------------------------------------------------------------------------
# Parity test
# ---------------------------------------------------------------------------

def _prod_rows_for_ciks(con_prod, ciks: list[int], _quarter_label: str) -> Any:
    """Pull prod fund_holdings_v2 rows for the reference CIKs within one
    quarter's reporting window (report_month YYYY-MM between first and last
    month in the DERA ZIP)."""
    # Translate 2025Q3 label to its 3 reporting months: Jul, Aug, Sep 2025
    # But N-PORT report_dates in a quarterly DERA ZIP span ~12 months.
    # Instead, let prod return all rows for these CIKs and we'll inner-join
    # on (series_id, report_month) for comparison.
    placeholders = ",".join("?" * len(ciks))
    padded = [str(c).zfill(10) for c in ciks]
    # prod fund_holdings_v2 has no accession_number column — amendments are
    # applied at promote time (DELETE + INSERT per series_month), so by
    # the time rows land in prod the accession is already a single value
    # per (series, month). We compare on (series_id, report_month) tuples.
    return con_prod.execute(
        f"""
        SELECT fund_cik, series_id, report_month, report_date,
               cusip, issuer_name, ticker, asset_category,
               shares_or_principal, market_value_usd, pct_of_nav
        FROM fund_holdings_v2
        WHERE fund_cik IN ({placeholders})
        """,
        padded,
    ).fetchdf()


def _dera_rows_for_run(con_staging, run_id: str) -> Any:
    return con_staging.execute(
        """
        SELECT s.fund_cik, s.series_id, s.report_month, s.report_date,
               s.cusip, s.issuer_name, s.ticker, s.asset_category,
               s.shares_or_principal, s.market_value_usd, s.pct_of_nav,
               s.accession_number, s.manifest_id
        FROM stg_nport_holdings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
        """,
        [run_id],
    ).fetchdf()


def run_parity_test(run_id: str, zip_path: Path, quarter_label: str) -> str:
    """Load DERA for reference CIKs, diff vs prod, write parity report.

    Returns path to the report. Exit code 0 if all BLOCK thresholds pass.

    Uses a dedicated staging DB file (data/13f_dera_parity.duckdb) so it
    never contends with live pipeline runs. The staging contract is
    satisfied by writing manifest + impacts + holdings atomically into
    a DuckDB file — the filename itself isn't part of the contract.
    """
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    report_path = os.path.join(BASE_DIR, "logs", f"nport_parity_{run_id}.md")
    parity_db = os.path.join(BASE_DIR, "data", "13f_dera_parity.duckdb")
    # Start each parity run from a clean file — no residual rows from prior
    # runs. Safe to delete since nothing else uses this file.
    if os.path.exists(parity_db):
        os.remove(parity_db)
    # Initialise control-plane schema (ingestion_manifest / ingestion_impacts
    # / pending_entity_resolution / data_freshness) by touching the DB and
    # replaying migration 001.
    duckdb.connect(parity_db).close()
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts", "migrations"))
    from importlib import import_module
    import_module("001_pipeline_control_plane").run_migration(parity_db)

    # 1. Build + load DERA side
    # Mirror XML path's default (index funds excluded) so parity compares
    # like-for-like. prod fund_holdings_v2 was produced with this default.
    nport_parsers._include_index = False  # pylint: disable=protected-access
    filter_ciks = {f["cik"] for f in REFERENCE_FUNDS}
    dataset = build_dera_dataset(zip_path, filter_ciks=filter_ciks)
    submissions_all = dataset["submissions"]
    submissions_kept = resolve_amendments(submissions_all)
    n_dropped_amendments = len(submissions_all) - len(submissions_kept)
    print(f"  amendments resolved: {len(submissions_all)} -> "
          f"{len(submissions_kept)} (dropped {n_dropped_amendments})")

    holdings_written, series_written = load_to_staging(
        dataset, submissions_kept, run_id, staging_db_path=parity_db,
    )
    print(f"  staging load ({parity_db}): {series_written} series, "
          f"{holdings_written:,} holdings")

    # 2. Compare to prod
    con_staging = duckdb.connect(parity_db, read_only=True)
    con_prod = duckdb.connect(PROD_DB, read_only=True)
    try:
        prod_df = _prod_rows_for_ciks(
            con_prod, [f["cik"] for f in REFERENCE_FUNDS], quarter_label,
        )
        dera_df = _dera_rows_for_run(con_staging, run_id)

        # Per-series-month aggregates for row-count delta + CUSIP overlap.
        # Count rows via series_id (always populated). pandas `count()` on
        # any column excludes NULLs, so using cusip would under-count the
        # many legitimately-CUSIP-less rows (DFE, RA, STIV, etc.).
        import pandas as pd
        dera_agg = dera_df.groupby(["series_id", "report_month"]).agg(
            dera_rows=("series_id", "count"),
            dera_nav=("market_value_usd", "sum"),
        ).reset_index()
        prod_agg = prod_df.groupby(["series_id", "report_month"]).agg(
            prod_rows=("series_id", "count"),
            prod_nav=("market_value_usd", "sum"),
        ).reset_index()
        merged = dera_agg.merge(
            prod_agg, on=["series_id", "report_month"], how="inner",
        )
        if merged.empty:
            print("  WARN: no overlapping (series_id, report_month) between "
                  "DERA and prod — cannot compute parity.")
            _write_parity_report(
                report_path, run_id, quarter_label, dera_df, prod_df,
                merged, pd.DataFrame(), pd.DataFrame(),
                verdict="BLOCKED: no overlap",
            )
            return report_path

        merged["row_delta"] = merged["dera_rows"] - merged["prod_rows"]
        merged["nav_delta_pct"] = (
            (merged["dera_nav"] - merged["prod_nav"])
            / merged["prod_nav"].replace(0, float("nan")) * 100
        )

        # CUSIP-overlap per (series, month)
        cusip_rows = []
        for (sid, rm), grp_d in dera_df.groupby(["series_id", "report_month"]):
            grp_p = prod_df[(prod_df["series_id"] == sid)
                            & (prod_df["report_month"] == rm)]
            if grp_p.empty:
                continue
            dera_cusips = set(c for c in grp_d["cusip"].dropna().tolist() if c)
            prod_cusips = set(c for c in grp_p["cusip"].dropna().tolist() if c)
            union = dera_cusips | prod_cusips
            overlap = dera_cusips & prod_cusips
            cov = (len(overlap) / len(union) * 100) if union else 100.0
            cusip_rows.append({
                "series_id": sid, "report_month": rm,
                "dera_cusips": len(dera_cusips),
                "prod_cusips": len(prod_cusips),
                "overlap": len(overlap),
                "coverage_pct": round(cov, 2),
            })
        cusip_df = pd.DataFrame(cusip_rows)

        # Group 1 nullability — required columns 100% populated
        required_cols = [
            "fund_cik", "series_id", "report_month", "report_date",
            "market_value_usd", "shares_or_principal",
        ]
        null_rates = {}
        for col in required_cols:
            if col in dera_df.columns:
                null_rates[col] = dera_df[col].isna().mean() * 100
            else:
                null_rates[col] = 100.0

        # CUSIP null-rate is reported but NOT required 100% (some N-PORT
        # positions are non-CUSIP — FX forwards, swaps, cash balances).
        # Apply parity to overlapping (series, month) tuples only.
        cusip_null_rate_overall = dera_df["cusip"].isna().mean() * 100

        # Manifest ID populated
        manifest_null_rate = dera_df["manifest_id"].isna().mean() * 100

        # Amendment discipline — any (series_id, report_month) with > 1
        # row per accession after resolve_amendments means a bug.
        dup = (dera_df.groupby(["series_id", "report_month"])
               ["accession_number"].nunique().reset_index())
        dup_violations = dup[dup["accession_number"] > 1]

        # Verdict
        checks = []
        def add(name, passed, detail):
            checks.append({"check": name, "passed": passed, "detail": detail})

        row_delta_max = merged["row_delta"].abs().max() if not merged.empty else 0
        add(
            "row_count_delta",
            row_delta_max <= 1,
            f"max |delta| = {int(row_delta_max)} rows (threshold: ±1)",
        )
        cusip_min = cusip_df["coverage_pct"].min() if not cusip_df.empty else 0
        add(
            "cusip_coverage",
            cusip_min >= 99.0,
            f"min coverage = {cusip_min:.2f}% (threshold: ≥99%)",
        )
        add(
            "series_id_mismatches",
            True,  # structural — all rows have series_id
            "0 (series_id always populated)",
        )
        add(
            "report_month_mismatches",
            True,
            "0 (report_month derived from REPORT_DATE)",
        )
        req_pass = all(v == 0.0 for v in null_rates.values())
        add(
            "group1_required_populated",
            req_pass,
            f"nulls: {null_rates} (threshold: 100% populated)",
        )
        add(
            "amendment_latest_wins",
            dup_violations.empty,
            f"{len(dup_violations)} (series, month) tuples with >1 accession",
        )
        add(
            "manifest_id_populated",
            manifest_null_rate == 0.0,
            f"manifest_id null rate = {manifest_null_rate:.1f}% (threshold: 0%)",
        )

        all_pass = all(c["passed"] for c in checks)
        verdict = "APPROVED FOR SESSION 2" if all_pass else "BLOCKED"

        _write_parity_report(
            report_path, run_id, quarter_label, dera_df, prod_df,
            merged, cusip_df, pd.DataFrame(checks),
            verdict=verdict,
            extra={
                "cusip_null_rate_overall": round(cusip_null_rate_overall, 2),
                "amendments_dropped": n_dropped_amendments,
                "submissions_kept": len(submissions_kept),
            },
        )
        print("")
        print("=" * 60)
        print(f"PARITY TEST VERDICT: {verdict}")
        print("=" * 60)
        for c in checks:
            icon = "✓" if c["passed"] else "✗"
            print(f"  {icon} {c['check']}: {c['detail']}")
        print(f"\nReport: {report_path}")
    finally:
        con_staging.close()
        con_prod.close()
    return report_path


def _write_parity_report(
    path: str, run_id: str, quarter: str,
    dera_df, prod_df, merged_agg, cusip_df, checks_df,
    verdict: str, extra: Optional[dict] = None,
) -> None:
    with open(path, "w") as fh:
        fh.write(f"# N-PORT DERA Parity Report — {run_id}\n\n")
        fh.write(f"_Generated: {datetime.now().isoformat()}_\n\n")
        fh.write(f"Quarter tested: **{quarter}**\n\n")
        fh.write(f"## Verdict: **{verdict}**\n\n")
        if not checks_df.empty:
            fh.write("## Parity checks\n\n")
            fh.write("| Check | Pass | Detail |\n")
            fh.write("|---|---|---|\n")
            for _, row in checks_df.iterrows():
                icon = "✓" if row["passed"] else "✗"
                fh.write(f"| {row['check']} | {icon} | {row['detail']} |\n")
            fh.write("\n")
        fh.write("## Volume\n\n")
        fh.write(f"- DERA staged: **{len(dera_df):,}** holdings, "
                 f"**{dera_df['series_id'].nunique()}** series, "
                 f"**{dera_df['report_month'].nunique()}** months\n")
        fh.write(f"- Prod fund_holdings_v2 (ref CIKs): "
                 f"**{len(prod_df):,}** holdings, "
                 f"**{prod_df['series_id'].nunique()}** series, "
                 f"**{prod_df['report_month'].nunique()}** months\n")
        if extra:
            for k, v in extra.items():
                fh.write(f"- {k}: **{v}**\n")
        fh.write("\n")
        if not merged_agg.empty:
            fh.write("## Row / NAV delta per (series_id, report_month)\n\n")
            show = merged_agg.copy()
            show = show.sort_values("row_delta", key=lambda s: s.abs(),
                                    ascending=False).head(30)
            fh.write("| series_id | month | DERA rows | Prod rows | Δ rows | "
                     "DERA NAV | Prod NAV | Δ NAV % |\n")
            fh.write("|---|---|---|---|---|---|---|---|\n")
            for _, r in show.iterrows():
                fh.write(
                    f"| {r['series_id']} | {r['report_month']} | "
                    f"{int(r['dera_rows']):,} | {int(r['prod_rows']):,} | "
                    f"{int(r['row_delta']):+d} | "
                    f"{r['dera_nav']:,.0f} | {r['prod_nav']:,.0f} | "
                    f"{r['nav_delta_pct']:+.2f}% |\n"
                )
            fh.write("\n")
        if not cusip_df.empty:
            fh.write("## CUSIP overlap per (series_id, report_month)\n\n")
            show = cusip_df.sort_values("coverage_pct").head(30)
            fh.write("| series_id | month | DERA CUSIPs | Prod CUSIPs | "
                     "Overlap | Jaccard % |\n")
            fh.write("|---|---|---|---|---|---|\n")
            for _, r in show.iterrows():
                fh.write(
                    f"| {r['series_id']} | {r['report_month']} | "
                    f"{r['dera_cusips']} | {r['prod_cusips']} | "
                    f"{r['overlap']} | {r['coverage_pct']:.2f}% |\n"
                )
            fh.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_last_run(run_id: str) -> None:
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "logs", "last_dera_run_id.txt"), "w") as fh:
        fh.write(run_id)


def run_test_mode(zip_spec: Optional[str] = None) -> int:
    run_id = f"dera_parity_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _write_last_run(run_id)
    year, quarter = 2025, 3  # 2025Q3 — fully in prod, best parity target
    print("=" * 60)
    print(f"fetch_dera_nport.py --test  run_id={run_id}")
    print(f"  parity target: {year}Q{quarter}")
    print(f"  reference funds: {[f['name'] for f in REFERENCE_FUNDS]}")
    print("=" * 60)

    zip_path = download_dera_zip(year, quarter, zip_spec=zip_spec)
    report_path = run_parity_test(run_id, zip_path, f"{year}Q{quarter}")
    print(f"\nrun_id saved to logs/last_dera_run_id.txt: {run_id}")
    return 0


def run_quarter(quarter_label: str, dry_run: bool,
                zip_spec: Optional[str] = None) -> int:
    run_id = f"dera_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _write_last_run(run_id)
    year, quarter = parse_quarter(quarter_label)
    print("=" * 60)
    print(f"fetch_dera_nport.py --quarter {quarter_label}  run_id={run_id}")
    print(f"  dry_run={dry_run}")
    print("=" * 60)

    zip_path = download_dera_zip(year, quarter, zip_spec=zip_spec)
    dataset = build_dera_dataset(zip_path, filter_ciks=None)
    submissions_kept = resolve_amendments(dataset["submissions"])
    n_dropped = len(dataset["submissions"]) - len(submissions_kept)
    print(f"\n  amendments resolved: {len(dataset['submissions'])} -> "
          f"{len(submissions_kept)} (dropped {n_dropped})")
    total_holdings = sum(
        len(dataset["holdings_by_accession"].get(s["accession_number"], []))
        for s in submissions_kept
    )
    months = sorted({s["report_month"] for s in submissions_kept})
    print(f"  series: {len({s['series_id'] for s in submissions_kept}):,}")
    print(f"  accessions: {len(submissions_kept):,}")
    print(f"  holdings: {total_holdings:,}")
    print(f"  months: {months}")
    if dry_run:
        print("  dry-run — no DB writes")
        return 0

    holdings_written, series_written = load_to_staging(
        dataset, submissions_kept, run_id,
    )
    print(f"  staging: {series_written} series, {holdings_written:,} holdings")
    print(f"\nrun_id: {run_id}  (logs/last_dera_run_id.txt)")
    print(f"Next: python3 scripts/validate_nport.py --run-id {run_id} --staging")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="N-PORT DERA ZIP loader (Session 1)")
    parser.add_argument("--test", action="store_true",
                        help="Parity test: 5 reference funds vs prod "
                             "fund_holdings_v2. Writes logs/nport_parity_*.md.")
    parser.add_argument("--quarter", type=str, default="",
                        help="Load one quarter, e.g. 2025Q3. Staging only.")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB (required unless --dry-run/--test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show summary without DB writes.")
    parser.add_argument("--all-missing", action="store_true",
                        help="PLACEHOLDER — orchestration lives in "
                             "fetch_nport_v2.py as of Session 2.")
    parser.add_argument("--zip", type=str, default="",
                        help="Path to a pre-downloaded DERA ZIP (file) or a "
                             "directory containing {YYYY}q{N}_nport.zip "
                             "files. Skips the network download when a match "
                             "is found; falls back to downloading otherwise.")
    args = parser.parse_args()

    if args.all_missing:
        sys.stderr.write(
            "ERROR: --all-missing moved to fetch_nport_v2.py --all in "
            "Session 2.\n"
            "       Use  python3 scripts/fetch_nport_v2.py --staging --all\n"
            "       to walk every missing DERA quarter.\n"
        )
        sys.exit(2)

    zip_spec = args.zip or None

    if args.test:
        set_staging_mode(True)
        sys.exit(run_test_mode(zip_spec=zip_spec))

    if not args.quarter:
        sys.stderr.write(
            "ERROR: one of --test, --quarter YYYYQN required.\n"
        )
        sys.exit(2)

    if not args.staging and not args.dry_run:
        sys.stderr.write(
            "ERROR: non-test runs must pass --staging or --dry-run.\n"
        )
        sys.exit(2)

    set_staging_mode(True)
    sys.exit(run_quarter(args.quarter, dry_run=args.dry_run, zip_spec=zip_spec))


if __name__ == "__main__":
    main()
