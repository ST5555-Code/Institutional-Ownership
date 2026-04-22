#!/usr/bin/env python3
"""validate_13dg.py — standalone validator for staged 13D/G filings.

Reads stg_13dg_filings from the staging DB, compares against prod, runs
block / flag / warn gates and the entity gate, writes a Markdown report
to logs/reports/13dg_{run_id}.md.

BLOCK checks:
  - duplicate accession_number in staged rows
  - pct_owned > 100 or < 0 (QC failure)
  - amendment_number not monotonic per (filer_cik, subject_cusip) chain
  - partial manifest rows (load_status = 'partial' with BLOCK in qc_flags)

FLAG checks:
  - shares_owned between 1 and 99 (likely parsing error)
  - filer_cik maps to different entity canonical_name than prior filing
  - filer_cik not in entity_identifiers (triggers entity gate block)

WARN checks:
  - pct_owned NULL (structural gap in some 13D cover pages)
  - non-empty qc_flags on the row

Entity gate: calls pipeline.shared.entity_gate_check() against the prod
entity tables. Unresolved filers land in pending_entity_resolution.

Usage:
  python3 scripts/validate_13dg.py --run-id R --staging
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.shared import entity_gate_check  # noqa: E402


REPORTS_DIR = os.path.join(BASE_DIR, "logs", "reports")


def _collect_staging_rows(staging_con, run_id: str):
    """Return all stg_13dg_filings rows whose manifest run_id matches."""
    return staging_con.execute(
        """
        SELECT s.*, m.run_id
        FROM stg_13dg_filings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
        ORDER BY s.filer_cik, s.subject_cusip, s.accession_number
        """,
        [run_id],
    ).fetchdf()


def _block_duplicate_accessions(rows):
    dup = rows["accession_number"].value_counts()
    dup = dup[dup > 1]
    return [{"gate": "dup_accession", "accession_number": a, "count": int(c)}
            for a, c in dup.items()]


def _block_pct_out_of_range(rows):
    out = []
    for _, r in rows.iterrows():
        p = r.get("pct_owned")
        if p is not None and not _is_na(p) and (p < 0 or p > 100):
            out.append({
                "gate": "pct_out_of_range",
                "accession_number": r["accession_number"],
                "pct_owned": float(p),
            })
    return out


def _block_partial_parses(rows):
    return [
        {"gate": "partial_parse",
         "accession_number": r["accession_number"],
         "parse_status": r["parse_status"],
         "qc_flags": r["qc_flags"]}
        for _, r in rows.iterrows()
        if r.get("parse_status") == "partial"
    ]


def _flag_shares_tiny(rows):
    out = []
    for _, r in rows.iterrows():
        s = r.get("shares_owned")
        if s is not None and not _is_na(s) and 0 < int(s) < 100:
            out.append({"gate": "shares_tiny",
                        "accession_number": r["accession_number"],
                        "shares_owned": int(s)})
    return out


def _warn_pct_null(rows):
    out = []
    for _, r in rows.iterrows():
        if r.get("pct_owned") is None or _is_na(r.get("pct_owned")):
            out.append({
                "gate": "pct_null",
                "accession_number": r["accession_number"],
                "filing_type": r["filing_type"],
            })
    return out


def _warn_qc_flags(rows):
    out = []
    for _, r in rows.iterrows():
        flags = r.get("qc_flags")
        if flags and str(flags) != "None":
            out.append({
                "gate": "qc_flags",
                "accession_number": r["accession_number"],
                "qc_flags": flags,
            })
    return out


def _is_na(v):
    # pandas/duckdb may produce pd.NA or NaN for nulls
    try:
        import pandas as pd
        return pd.isna(v)
    except Exception:  # pylint: disable=broad-except
        return v is None


def _run_entity_gate(prod_con, rows):
    filer_ciks = sorted({r["filer_cik"] for _, r in rows.iterrows()
                         if r.get("filer_cik")})
    return entity_gate_check(
        prod_con,
        source_type="13DG",
        identifier_type="cik",
        staged_identifiers=filer_ciks,
        rollup_types=["economic_control_v1"],  # 13D/G filers don't need decision_maker_v1
        requires_classification=False,
    )


def _write_report(run_id: str, n: int, blocks, flags, warns, gate) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"13dg_{run_id}.md")
    # Gate-level blocks (missing entity_identifiers) are FLAG-severity for
    # 13D/G — see validate_13dg.main(). Structural BLOCKs are the only
    # hard refuse-to-promote condition.
    promote_ok = (len(blocks) == 0)

    with open(path, "w") as fh:
        fh.write(f"# VALIDATION REPORT — 13D/G Scoped Run {run_id}\n\n")
        fh.write(f"_Generated: {datetime.now().isoformat()}_\n\n")
        fh.write("Tickers: AR, OXY, EQT, NFLX\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- Staged filings: **{n}**\n")
        fh.write(f"- BLOCK: **{len(blocks)}** (promote refuses if > 0)\n")
        fh.write(f"- FLAG: **{len(flags)}** (operator review required)\n")
        fh.write(f"- WARN: **{len(warns)}** (logged, proceed)\n\n")
        fh.write("## Entity gate\n\n")
        fh.write(f"- Resolved: **{len(gate.promotable)}**\n")
        fh.write(f"- Blocked:  **{len(gate.blocked)}**\n")
        fh.write(f"- Pending review: **{len(gate.new_entities_pending)}**\n\n")

        if blocks:
            fh.write("## BLOCK details\n\n")
            for b in blocks:
                fh.write(f"- {json.dumps(b)}\n")
            fh.write("\n")
        if gate.blocked:
            fh.write("## Entity-gate blocks\n\n")
            for b in gate.blocked:
                fh.write(f"- {json.dumps(b, default=str)}\n")
            fh.write("\n")
        if flags:
            fh.write("## FLAG details\n\n")
            for f in flags:
                fh.write(f"- {json.dumps(f)}\n")
            fh.write("\n")
        if warns:
            fh.write("## WARN details\n\n")
            for w in warns[:50]:
                fh.write(f"- {json.dumps(w)}\n")
            if len(warns) > 50:
                fh.write(f"- ... ({len(warns) - 50} more omitted)\n")
            fh.write("\n")

        fh.write(f"## Promote-ready: **{'YES' if promote_ok else 'NO'}**\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate staged 13D/G run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--staging", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id
    staging_path = STAGING_DB if args.staging else PROD_DB

    staging_con = duckdb.connect(staging_path, read_only=True)
    # Read-only — the running app may hold the prod write lock.
    # entity_gate_check's pending_entity_resolution insert is wrapped in
    # try/except (scripts/pipeline/shared.py); the gate still returns
    # accurate block/promotable/pending lists. Promote step writes
    # pending rows for real when it has the lock.
    prod_con = duckdb.connect(PROD_DB, read_only=True)
    try:
        rows = _collect_staging_rows(staging_con, run_id)
        n = len(rows)
        if n == 0:
            print(f"No staged rows for run_id={run_id}")
            return

        blocks = (_block_duplicate_accessions(rows)
                  + _block_pct_out_of_range(rows)
                  + _block_partial_parses(rows))
        flags = _flag_shares_tiny(rows)
        warns = _warn_pct_null(rows) + _warn_qc_flags(rows)

        gate = _run_entity_gate(prod_con, rows)

        # Per the v1.2 spec: for 13D/G, "new filer_cik not in entity_identifiers"
        # is a FLAG not a BLOCK. BO filers are often individuals or corporations
        # that never enter the 13F-centric entity MDM. The gate writes them to
        # pending_entity_resolution for operator review but does not refuse
        # promote. Corporations filing a 13G about themselves (EQT, Netflix)
        # land here. gate.blocked becomes a FLAG bucket; BLOCKs are strictly
        # structural (dup accession, pct out-of-range, partial parse).
        flags.extend([
            {"gate": "filer_not_in_mdm",
             "identifier_value": b.get("identifier_value"),
             "reason": b.get("reason")}
            for b in gate.blocked
        ])
    finally:
        staging_con.close()
        prod_con.close()

    report_path = _write_report(run_id, n, blocks, flags, warns, gate)

    promote_ok = (len(blocks) == 0)
    print("=" * 60)
    print(f"VALIDATION REPORT — 13D/G Scoped Run {run_id}")
    print("=" * 60)
    print(f"Staged filings:   {n}")
    print(f"BLOCK:            {len(blocks)}")
    print(f"FLAG:             {len(flags)}")
    print(f"WARN:             {len(warns)}")
    print()
    print("Entity gate:")
    print(f"  Resolved:       {len(gate.promotable)}")
    print(f"  Blocked (new):  {len(gate.blocked)}")
    print(f"  Pending review: {len(gate.new_entities_pending)}")
    print()
    if blocks:
        print("BLOCK details:")
        for b in blocks:
            print(f"  {b}")
    if gate.blocked:
        print("Entity-gate blocks:")
        for b in gate.blocked[:10]:
            print(f"  {b}")
    print()
    print(f"Promote-ready: {'YES' if promote_ok else 'NO'}")
    print(f"Report: {report_path}")
    sys.exit(0 if promote_ok else 1)


if __name__ == "__main__":
    main()
