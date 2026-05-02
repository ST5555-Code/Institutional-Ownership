"""Phase 1.1 — CEF universe enumeration via N-2 / N-2/A filings since 2020-01-01.

READ-ONLY. No DB writes.
Uses edgartools to pull form-index headers only (no body fetch).
Output: data/working/cef_scoping/cef_universe.csv with columns
  CIK, registrant_name, registration_date_proxy, most_recent_n_csr_date.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from edgar import get_filings, set_identity

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
OUT_DIR = ROOT / "data" / "working" / "cef_scoping"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "cef_universe.csv"

set_identity("serge.tismen@gmail.com")


def enumerate_n2_filers() -> pd.DataFrame:
    """Pull all N-2 and N-2/A filings since 2020-01-01, dedupe by CIK."""
    frames = []
    for form in ("N-2", "N-2/A"):
        # edgartools accepts year ranges via filings; iterate year-by-year for safety
        for year in range(2020, 2027):
            try:
                f = get_filings(form=form, year=year)
                if f is None:
                    continue
                df = f.to_pandas()
                if df is None or df.empty:
                    continue
                df = df[["cik", "company", "form", "filing_date"]].copy()
                df["form"] = form
                frames.append(df)
                print(f"  {form} {year}: {len(df):,} filings", flush=True)
            except Exception as e:
                print(f"  {form} {year}: ERROR {e}", flush=True)
    if not frames:
        return pd.DataFrame(columns=["cik", "company", "form", "filing_date"])
    all_n2 = pd.concat(frames, ignore_index=True)
    all_n2["filing_date"] = pd.to_datetime(all_n2["filing_date"])
    return all_n2


def enumerate_n_csr(ciks: set[int]) -> dict[int, str]:
    """For each CIK, find most recent N-CSR filing date (any year)."""
    result: dict[int, str] = {}
    for form in ("N-CSR", "N-CSRS"):
        for year in range(2020, 2027):
            try:
                f = get_filings(form=form, year=year)
                if f is None:
                    continue
                df = f.to_pandas()
                if df is None or df.empty:
                    continue
                df = df[df["cik"].isin(ciks)]
                if df.empty:
                    continue
                df["filing_date"] = pd.to_datetime(df["filing_date"])
                for cik, sub in df.groupby("cik"):
                    d = sub["filing_date"].max().strftime("%Y-%m-%d")
                    if cik not in result or d > result[cik]:
                        result[cik] = d
            except Exception as e:
                print(f"  {form} {year}: ERROR {e}", flush=True)
    return result


def main() -> int:
    print("Phase 1.1 — enumerating N-2 / N-2/A filings 2020-2026...", flush=True)
    n2 = enumerate_n2_filers()
    print(f"Raw N-2/N-2/A filings: {len(n2):,}", flush=True)

    if n2.empty:
        print("ERROR: no N-2 filings retrieved", flush=True)
        return 1

    # most recent N-2/N-2/A filing per CIK
    n2_sorted = n2.sort_values("filing_date", ascending=False)
    n2_dedup = n2_sorted.drop_duplicates(subset=["cik"], keep="first")
    print(f"Unique CIKs with N-2/N-2/A since 2020-01-01: {len(n2_dedup):,}", flush=True)

    ciks = set(int(c) for c in n2_dedup["cik"].tolist())
    print(f"Pulling most-recent N-CSR/N-CSRS dates for {len(ciks):,} CIKs...", flush=True)
    n_csr_map = enumerate_n_csr(ciks)
    print(f"CIKs with N-CSR/N-CSRS in window: {len(n_csr_map):,}", flush=True)

    out = pd.DataFrame({
        "CIK": [int(c) for c in n2_dedup["cik"]],
        "registrant_name": n2_dedup["company"].astype(str).values,
        "registration_date_proxy": n2_dedup["filing_date"].dt.strftime("%Y-%m-%d").values,
    })
    out["most_recent_n_csr_date"] = out["CIK"].map(n_csr_map)
    out = out.sort_values("CIK").reset_index(drop=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH} ({len(out):,} rows)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
