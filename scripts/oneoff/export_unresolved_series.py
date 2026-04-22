#!/usr/bin/env python3
"""export_unresolved_series.py — int-21 unresolved N-PORT series triage export.

READ-ONLY. Pulls every row in ``pending_entity_resolution`` with
``resolution_status = 'pending'`` and enriches each one with:

  - ``series_name`` / ``family_name`` / ``filer_cik`` (context_json, with
    fund_universe fallback)
  - ``filer_name`` / ``inst_parent_name`` (managers by filer_cik)
  - ``report_month_count`` / ``total_nav`` (fund_holdings_v2 by series_id)
  - ``candidate_entity_count`` — distinct entities whose
    entity_identifiers row has identifier_type='cik' and
    identifier_value = filer_cik
  - ``candidate_names`` — display_name list joined by ``|``
  - ``decision`` — empty column for offline triage by Serge.

Output: ``data/reports/unresolved_series_triage.csv``.
Usage:
    python scripts/oneoff/export_unresolved_series.py
    python scripts/oneoff/export_unresolved_series.py --db /path/to/13f.duckdb
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB  # noqa: E402

OUTPUT_REL = os.path.join("data", "reports", "unresolved_series_triage.csv")

ENRICH_SQL = """
WITH pending AS (
    SELECT
        resolution_id,
        source_type,
        identifier_type,
        identifier_value AS series_id,
        context_json,
        created_at,
    FROM pending_entity_resolution
    WHERE resolution_status = 'pending'
),
parsed AS (
    SELECT
        p.*,
        TRY_CAST(json_extract_string(context_json, '$.fund_name')    AS VARCHAR) AS ctx_fund_name,
        TRY_CAST(json_extract_string(context_json, '$.family_name')  AS VARCHAR) AS ctx_family_name,
        TRY_CAST(json_extract_string(context_json, '$.fund_cik')     AS VARCHAR) AS ctx_fund_cik,
        TRY_CAST(json_extract_string(context_json, '$.reg_cik')      AS VARCHAR) AS ctx_reg_cik,
    FROM pending p
),
holdings_agg AS (
    SELECT
        series_id,
        COUNT(DISTINCT report_month) AS report_month_count,
        SUM(market_value_usd)        AS total_nav,
    FROM fund_holdings_v2
    GROUP BY series_id
),
candidates AS (
    SELECT
        ei.identifier_value AS filer_cik,
        COUNT(DISTINCT ei.entity_id) AS candidate_entity_count,
        STRING_AGG(DISTINCT ec.display_name, ' | ')
          FILTER (WHERE ec.display_name IS NOT NULL) AS candidate_names,
    FROM entity_identifiers ei
    LEFT JOIN entity_current ec USING (entity_id)
    WHERE ei.identifier_type = 'cik'
    GROUP BY ei.identifier_value
)
SELECT
    p.resolution_id,
    p.source_type,
    p.identifier_type,
    p.series_id,
    COALESCE(fu.fund_name,    p.ctx_fund_name)    AS series_name,
    COALESCE(fu.family_name,  p.ctx_family_name)  AS family_name,
    COALESCE(fu.fund_cik,     p.ctx_fund_cik)     AS filer_cik,
    m.manager_name                                AS filer_name,
    m.parent_name                                 AS inst_parent_name,
    COALESCE(h.report_month_count, 0)             AS report_month_count,
    COALESCE(h.total_nav, 0.0)                    AS total_nav,
    COALESCE(c.candidate_entity_count, 0)         AS candidate_entity_count,
    c.candidate_names                             AS candidate_names,
    p.created_at                                  AS pending_since,
    CAST(NULL AS VARCHAR)                         AS decision,
FROM parsed p
LEFT JOIN fund_universe   fu ON fu.series_id        = p.series_id
LEFT JOIN holdings_agg    h  ON h.series_id         = p.series_id
LEFT JOIN managers        m  ON m.cik              = COALESCE(fu.fund_cik, p.ctx_fund_cik)
LEFT JOIN candidates      c  ON c.filer_cik        = COALESCE(fu.fund_cik, p.ctx_fund_cik)
ORDER BY h.total_nav DESC NULLS LAST, p.resolution_id
"""


def run(db_path: str, output_path: str) -> None:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB not found: {db_path}")

    con = duckdb.connect(db_path, read_only=True)
    try:
        rows = con.execute(ENRICH_SQL).fetchall()
        col_names = [d[0] for d in con.description]
    finally:
        con.close()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(col_names)
        for r in rows:
            w.writerow(r)

    _print_summary(rows, col_names, output_path)


def _print_summary(rows, col_names, output_path) -> None:
    idx = {n: i for i, n in enumerate(col_names)}
    total = len(rows)
    buckets = {"0": 0, "1": 0, "2+": 0}
    for r in rows:
        c = r[idx["candidate_entity_count"]] or 0
        if c == 0:
            buckets["0"] += 1
        elif c == 1:
            buckets["1"] += 1
        else:
            buckets["2+"] += 1

    print(f"Wrote {total} rows → {output_path}")
    print("Candidate entity bucket counts (match count of filer_cik in entity_identifiers):")
    for k in ("0", "1", "2+"):
        pct = (100.0 * buckets[k] / total) if total else 0.0
        print(f"  {k:>3s} candidate(s): {buckets[k]:>5d}  ({pct:5.1f}%)")

    print("\nTop 10 by total_nav (USD):")
    nav_i = idx["total_nav"]
    name_i = idx["series_name"]
    sid_i = idx["series_id"]
    cand_i = idx["candidate_entity_count"]
    cand_name_i = idx["candidate_names"]
    top = sorted(rows, key=lambda r: (r[nav_i] or 0), reverse=True)[:10]
    for r in top:
        nav = r[nav_i] or 0.0
        cand_names = r[cand_name_i] or ""
        cand_names = (cand_names[:60] + "…") if len(cand_names) > 61 else cand_names
        print(
            f"  ${nav:>16,.0f}  series={r[sid_i]:<40s}  "
            f"name={(r[name_i] or '')[:40]:<40s}  "
            f"cand={r[cand_i]} ({cand_names})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=PROD_DB,
        help=f"Path to DuckDB file (default: {PROD_DB}).",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(BASE_DIR, OUTPUT_REL),
        help=f"Output CSV path (default: <repo>/{OUTPUT_REL}).",
    )
    args = parser.parse_args()
    run(args.db, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
