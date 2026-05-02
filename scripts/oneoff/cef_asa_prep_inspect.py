"""cef_asa_prep_inspect.py — READ-ONLY ASA Gold (CIK 0001230869) prep probes.

Backs the cef-asa-prep-investigation finding doc. Re-running this script
produces the same numbers used in
``docs/findings/cef_asa_prep_investigation.md``.

NO writes to any DB. NO mutation. Output goes to stdout + JSON files
under ``data/working/``.

Three probes:
  1. Enumerate ASA UNKNOWN cohort (rows / AUM / period coverage) from
     prod, plus any existing SYN_0001230869 companion rows.
  2. List ASA's NPORT-P filings via edgartools (read-only EDGAR fetch);
     cross-reference filing report_period vs UNKNOWN-cohort periods.
  3. Fetch primary_doc.xml for each accession matching an UNKNOWN
     period, run the canonical ``parse_nport_xml`` parser, sum
     ``val_usd`` to compare against UNKNOWN-side market_value_usd.

Caps EDGAR fetches at the 3 ASA accessions covering the UNKNOWN
periods (2024-11, 2025-02, 2025-08). The full 24-filing NPORT-P
listing is metadata-only via edgartools (no per-filing fetch).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time

import duckdb
import requests

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(HERE, "scripts"))
sys.path.insert(0, os.path.join(HERE, "scripts/pipeline"))

# Path-based local imports — same pattern as scripts/oneoff/cef_scoping_*.py.
from config import EDGAR_IDENTITY  # noqa: E402
from nport_parsers import parse_nport_xml  # noqa: E402

ASA_CIK = "0001230869"
UNKNOWN_PERIODS = ("2024-11", "2025-02", "2025-08")

# ASA accessions matching the UNKNOWN periods, confirmed via edgartools
# Company("0001230869").get_filings(form=["NPORT-P"]) on 2026-05-02.
ASA_ACCESSIONS = [
    ("0001752724-25-018310", "2024-11"),
    ("0001752724-25-075250", "2025-02"),
    ("0001230869-25-000013", "2025-08"),
]

PROD_DB = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f_readonly.duckdb"
OUT_DIR = os.path.join(HERE, "data/working")
HEADERS = {"User-Agent": EDGAR_IDENTITY}


def probe_unknown_cohort(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute(
        """
        SELECT report_month, COUNT(*) AS rows, SUM(market_value_usd) AS aum,
               COUNT(DISTINCT cusip) AS distinct_cusip,
               COUNT(DISTINCT isin) AS distinct_isin
        FROM fund_holdings_v2
        WHERE fund_cik = ? AND series_id = 'UNKNOWN' AND is_latest = TRUE
        GROUP BY report_month
        ORDER BY report_month
        """,
        [ASA_CIK],
    ).fetchall()
    syn = con.execute(
        """
        SELECT report_month, accession_number, COUNT(*), SUM(market_value_usd)
        FROM fund_holdings_v2
        WHERE fund_cik = ? AND series_id = 'SYN_0001230869' AND is_latest = TRUE
        GROUP BY report_month, accession_number
        ORDER BY report_month
        """,
        [ASA_CIK],
    ).fetchall()
    return {
        "unknown_periods": [
            {"period": r[0], "rows": r[1], "aum_usd": r[2],
             "distinct_cusip": r[3], "distinct_isin": r[4]}
            for r in rows
        ],
        "syn_companion_rows": [
            {"period": r[0], "accession": r[1], "rows": r[2], "aum_usd": r[3]}
            for r in syn
        ],
    }


def probe_edgar_filings() -> list[dict]:
    """List ASA NPORT-P filings via edgartools (metadata only)."""
    from config import configure_edgar_identity
    from edgar import Company

    configure_edgar_identity()
    asa = Company(ASA_CIK)
    filings = asa.get_filings(form=["NPORT-P"])
    out: list[dict] = []
    for f in filings:
        rd = getattr(f, "report_date", None) or getattr(f, "period_of_report", None)
        out.append({
            "filing_date": str(getattr(f, "filing_date", "")),
            "accession": str(getattr(f, "accession_number",
                                     getattr(f, "accession_no", ""))),
            "form": str(getattr(f, "form", "")),
            "report_period": str(rd) if rd else "",
        })
    return out


def probe_nport_holdings() -> dict:
    """Fetch primary_doc.xml for the 3 UNKNOWN-period accessions."""
    out: dict = {}
    cik_int = ASA_CIK.lstrip("0") or "0"
    for acc, period in ASA_ACCESSIONS:
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_int}/{acc.replace('-', '')}/primary_doc.xml"
        )
        time.sleep(0.2)
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        metadata, holdings = parse_nport_xml(resp.content)
        nav = float(metadata.get("net_assets") or 0)
        total_mv = sum(float(h.get("val_usd") or 0) for h in holdings)
        top10 = sorted(holdings, key=lambda x: float(x.get("val_usd") or 0),
                       reverse=True)[:10]
        out[period] = {
            "accession": acc,
            "url": url,
            "report_period": metadata.get("rep_pd_date") or metadata.get("rep_pd_end"),
            "series_id_in_filing": metadata.get("series_id"),
            "net_assets": nav,
            "holdings_count": len(holdings),
            "total_mv_sum": total_mv,
            "top10": [
                {
                    "cusip": h.get("cusip"),
                    "isin": h.get("isin"),
                    "name": h.get("name"),
                    "ticker": h.get("ticker"),
                    "val_usd": h.get("val_usd"),
                    "pct_of_nav": h.get("pct_of_nav"),
                }
                for h in top10
            ],
        }
    return out


def write_unknown_baseline_csv(con: duckdb.DuckDBPyConnection) -> str:
    out_path = os.path.join(OUT_DIR, "asa_unknown_baseline.csv")
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "period", "rank", "cusip", "isin", "issuer_name", "ticker",
            "market_value_usd", "pct_of_nav", "shares_or_principal",
            "accession_number", "backfill_quality",
        ])
        for period in UNKNOWN_PERIODS:
            rows = con.execute(
                """
                SELECT cusip, isin, issuer_name, ticker,
                       market_value_usd, pct_of_nav, shares_or_principal,
                       accession_number, backfill_quality
                FROM fund_holdings_v2
                WHERE fund_cik = ? AND series_id = 'UNKNOWN'
                  AND report_month = ? AND is_latest = TRUE
                ORDER BY market_value_usd DESC
                """,
                [ASA_CIK, period],
            ).fetchall()
            for i, r in enumerate(rows, 1):
                w.writerow([period, i, *r])
    return out_path


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    con = duckdb.connect(PROD_DB, read_only=True)
    try:
        print("=== Probe 1: ASA UNKNOWN cohort + SYN companion ===")
        cohort = probe_unknown_cohort(con)
        print(json.dumps(cohort, indent=2, default=str))

        baseline_csv = write_unknown_baseline_csv(con)
        print(f"\nWROTE {baseline_csv}")
    finally:
        con.close()

    print("\n=== Probe 2: EDGAR NPORT-P filings (metadata-only) ===")
    filings = probe_edgar_filings()
    print(f"Total NPORT-P filings: {len(filings)}")
    matched = [f for f in filings if f["report_period"][:7] in UNKNOWN_PERIODS]
    print(f"Matching UNKNOWN-period filings: {len(matched)}")
    for f in matched:
        print(f"  {f}")

    print("\n=== Probe 3: N-PORT XML fetch + parse ===")
    nport = probe_nport_holdings()
    summary = {
        period: {
            "accession": d["accession"],
            "net_assets": d["net_assets"],
            "holdings_count": d["holdings_count"],
            "total_mv_sum": d["total_mv_sum"],
            "series_id_in_filing": d["series_id_in_filing"],
        }
        for period, d in nport.items()
    }
    print(json.dumps(summary, indent=2, default=str))

    nport_path = os.path.join(OUT_DIR, "asa_nport_baseline.json")
    with open(nport_path, "w") as fh:
        json.dump(nport, fh, indent=2, default=str)
    print(f"\nWROTE {nport_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
