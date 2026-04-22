#!/usr/bin/env python3
"""
export_ticker_override_triage.py — enrich data/reference/ticker_overrides.csv
with current database state so Serge can triage the ~568 manual overrides
offline.

Read-only. Writes a single CSV to data/reports/ticker_override_triage.csv.

For each override row, the output adds:
  * current_securities_ticker           — securities.ticker (NULL if missing)
  * openfigi_ticker                     — _cache_openfigi.ticker (NULL if missing)
  * canonical_type                      — cusip_classifications.canonical_type
  * issuer_name_db                      — securities.issuer_name (fallback: cusip_classifications)
  * is_priceable, is_equity, is_active  — securities flags
  * override_matches_openfigi           — override.correct_ticker == openfigi_ticker
  * override_matches_securities         — override.correct_ticker == securities.ticker
  * cusip_in_securities                 — CUSIP present in securities
  * suspect_reason                      — one of:
        duplicate_cusip, cusip_not_in_securities, stale_delisted,
        ticker_mismatch, or NULL when the row looks clean
  * decision                            — empty column for Serge to fill
                                          (KEEP / FIX / REMOVE)

Usage:
    python scripts/oneoff/export_ticker_override_triage.py
"""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB  # noqa: E402

INPUT_CSV = os.path.join(BASE_DIR, "data", "reference", "ticker_overrides.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "reports")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "ticker_override_triage.csv")

INPUT_COLS = [
    "cusip", "wrong_ticker", "correct_ticker", "company_name",
    "note", "security_type_override", "method", "auto_applied",
]

ENRICH_COLS = [
    "current_securities_ticker",
    "openfigi_ticker",
    "canonical_type",
    "issuer_name_db",
    "is_priceable",
    "is_equity",
    "is_active",
    "cusip_in_securities",
    "override_matches_securities",
    "override_matches_openfigi",
    "suspect_reason",
    "decision",
]


def load_overrides(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fetch_enrichment(con: duckdb.DuckDBPyConnection, cusips: list[str]) -> dict[str, dict]:
    """Return {cusip: {...enrichment fields}} for every CUSIP in the input."""
    if not cusips:
        return {}
    ph = ",".join("?" * len(cusips))

    sec = {
        row[0]: row
        for row in con.execute(
            f"""
            SELECT cusip, ticker, issuer_name, is_priceable, is_equity, is_active
            FROM securities
            WHERE cusip IN ({ph})
            """,
            cusips,
        ).fetchall()
    }

    ofg = {
        row[0]: row[1]
        for row in con.execute(
            f"""
            SELECT cusip, ticker
            FROM _cache_openfigi
            WHERE cusip IN ({ph})
            """,
            cusips,
        ).fetchall()
    }

    cls = {
        row[0]: row
        for row in con.execute(
            f"""
            SELECT cusip, canonical_type, issuer_name
            FROM cusip_classifications
            WHERE cusip IN ({ph})
            """,
            cusips,
        ).fetchall()
    }

    out: dict[str, dict] = {}
    for cusip in cusips:
        s = sec.get(cusip)
        c = cls.get(cusip)
        out[cusip] = {
            "sec_ticker": s[1] if s else None,
            "sec_issuer": s[2] if s else None,
            "is_priceable": s[3] if s else None,
            "is_equity": s[4] if s else None,
            "is_active": s[5] if s else None,
            "in_securities": s is not None,
            "openfigi_ticker": ofg.get(cusip),
            "canonical_type": c[1] if c else None,
            "cls_issuer": c[2] if c else None,
        }
    return out


DELISTED_TYPES = {
    "NONE", "DELISTED", "INACTIVE", "EXPIRED", "WARRANT_EXPIRED",
}


def compute_suspect_reason(
    override_ticker: str,
    enrich: dict,
    dup_cusips: set[str],
    cusip: str,
) -> str | None:
    if cusip in dup_cusips:
        return "duplicate_cusip"
    if not enrich["in_securities"]:
        return "cusip_not_in_securities"
    ct = (enrich["canonical_type"] or "").upper()
    if enrich["is_active"] is False or ct in DELISTED_TYPES:
        return "stale_delisted"
    sec_t = enrich["sec_ticker"]
    ofg_t = enrich["openfigi_ticker"]
    ov = (override_ticker or "").strip()
    if not ov:
        return None
    matches_sec = sec_t is not None and sec_t == ov
    matches_ofg = ofg_t is not None and ofg_t == ov
    if matches_sec or matches_ofg:
        return None
    # Neither source confirms the override.
    return "ticker_mismatch"


def build_rows(overrides: list[dict], enrichment: dict[str, dict]) -> list[dict]:
    cusip_counts = Counter(r["cusip"] for r in overrides)
    dup_cusips = {k for k, v in cusip_counts.items() if v > 1}

    out = []
    for r in overrides:
        cusip = r["cusip"]
        e = enrichment.get(cusip, {
            "sec_ticker": None, "sec_issuer": None, "is_priceable": None,
            "is_equity": None, "is_active": None, "in_securities": False,
            "openfigi_ticker": None, "canonical_type": None, "cls_issuer": None,
        })
        ov = (r.get("correct_ticker") or "").strip()
        row = dict(r)
        row["current_securities_ticker"] = e["sec_ticker"] or ""
        row["openfigi_ticker"] = e["openfigi_ticker"] or ""
        row["canonical_type"] = e["canonical_type"] or ""
        row["issuer_name_db"] = e["sec_issuer"] or e["cls_issuer"] or ""
        row["is_priceable"] = "" if e["is_priceable"] is None else str(e["is_priceable"])
        row["is_equity"] = "" if e["is_equity"] is None else str(e["is_equity"])
        row["is_active"] = "" if e["is_active"] is None else str(e["is_active"])
        row["cusip_in_securities"] = str(e["in_securities"])
        row["override_matches_securities"] = str(
            e["sec_ticker"] is not None and e["sec_ticker"] == ov
        )
        row["override_matches_openfigi"] = str(
            e["openfigi_ticker"] is not None and e["openfigi_ticker"] == ov
        )
        row["suspect_reason"] = compute_suspect_reason(ov, e, dup_cusips, cusip) or ""
        row["decision"] = ""
        out.append(row)
    return out


def write_output(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = INPUT_COLS + ENRICH_COLS
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def print_summary(rows: list[dict]) -> None:
    reasons = Counter(r["suspect_reason"] or "CLEAN" for r in rows)
    total = len(rows)
    clean = reasons.get("CLEAN", 0)
    suspect = total - clean
    print(f"Total rows:   {total}")
    print(f"Clean rows:   {clean}")
    print(f"Suspect rows: {suspect}")
    print("By reason:")
    for reason, count in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):
        if reason == "CLEAN":
            continue
        print(f"  {reason:30s} {count}")


def main() -> None:
    print("export_ticker_override_triage.py")
    print("=" * 60)
    print(f"  input:  {INPUT_CSV}")
    print(f"  db:     {PROD_DB} (read-only)")
    print(f"  output: {OUTPUT_CSV}")
    print()

    overrides = load_overrides(INPUT_CSV)
    cusips = [r["cusip"] for r in overrides]
    print(f"  loaded {len(overrides)} override rows")

    con = duckdb.connect(PROD_DB, read_only=True)
    try:
        enrichment = fetch_enrichment(con, cusips)
    finally:
        con.close()
    print(f"  enriched {len(enrichment)} CUSIPs from database")
    print()

    rows = build_rows(overrides, enrichment)
    write_output(rows, OUTPUT_CSV)
    print_summary(rows)
    print()
    print(f"Wrote {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
