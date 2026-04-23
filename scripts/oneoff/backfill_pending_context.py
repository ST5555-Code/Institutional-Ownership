#!/usr/bin/env python3
"""backfill_pending_context.py — populate pending_entity_resolution.context_json.

`pending_entity_resolution` is a queue table (NOT part of entity SCD), so
this runs directly against prod — no staging workflow required. The
`context_json` column is NULL for every series_id row inserted by
`validate_nport.py` / `validate_nport_subset.py`. This script joins each
NULL row to:
  * `data/13f_staging.duckdb`.`stg_nport_holdings` (staging) — fund_cik,
    fund_name, family_name (most recent loaded_at wins per series_id)
  * `fund_universe` (prod) — same fields, fallback for series already
    promoted whose staging rows were aged out
  * `ncen_adviser_map` (prod) — registrant_cik via series_id when
    available

…and UPSERTs `context_json` with the JSON object:
  {"fund_name": ..., "family_name": ..., "fund_cik": ..., "reg_cik": ...}

One-off; safe to re-run (only touches rows where context_json IS NULL).
Prints before/after NULL counts.

Usage:
    python3 scripts/backfill_pending_context.py
    python3 scripts/backfill_pending_context.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402


def _build_context_map(prod_con, stg_con) -> dict[str, dict]:
    """Return {series_id -> dict(fund_name, family_name, fund_cik, reg_cik)}.

    Source priority per series_id:
      1. Staging stg_nport_holdings — most-recent loaded_at row
      2. Prod fund_universe — fallback for promoted series
    `reg_cik` is the LPAD'd 10-digit form of fund_cik (matches
    `ncen_adviser_map.registrant_cik` convention) so cross-source
    lookups stay consistent.
    """
    pending = prod_con.execute(
        """
        SELECT identifier_value AS series_id
          FROM pending_entity_resolution
         WHERE identifier_type = 'series_id'
           AND context_json IS NULL
        """
    ).fetchdf()
    if pending.empty:
        return {}
    stg_con.register("pending", pending)

    stg_rows = stg_con.execute(
        """
        SELECT series_id,
               ANY_VALUE(fund_cik    ORDER BY loaded_at DESC) AS fund_cik,
               ANY_VALUE(fund_name   ORDER BY loaded_at DESC) AS fund_name,
               ANY_VALUE(family_name ORDER BY loaded_at DESC) AS family_name
          FROM stg_nport_holdings
         WHERE series_id IN (SELECT series_id FROM pending)
         GROUP BY series_id
        """
    ).fetchdf()
    stg_con.unregister("pending")

    ctx: dict[str, dict] = {}
    for _, row in stg_rows.iterrows():
        sid = row["series_id"]
        cik = row["fund_cik"]
        ctx[sid] = {
            "fund_name":   None if row["fund_name"]   is None else str(row["fund_name"]),
            "family_name": None if row["family_name"] is None else str(row["family_name"]),
            "fund_cik":    None if cik is None else str(cik),
            "reg_cik":     None if cik is None else str(cik).zfill(10),
        }

    # Fallback — prod.fund_universe for any series we couldn't find in stg.
    missing = pending[~pending["series_id"].isin(stg_rows["series_id"])]
    if not missing.empty:
        prod_con.register("missing", missing)
        fu_rows = prod_con.execute(
            """
            SELECT fu.series_id, fu.fund_cik, fu.fund_name, fu.family_name
              FROM fund_universe fu
              JOIN missing m ON m.series_id = fu.series_id
            """
        ).fetchdf()
        prod_con.unregister("missing")
        for _, row in fu_rows.iterrows():
            sid = row["series_id"]
            cik = row["fund_cik"]
            ctx[sid] = {
                "fund_name":   None if row["fund_name"]   is None else str(row["fund_name"]),
                "family_name": None if row["family_name"] is None else str(row["family_name"]),
                "fund_cik":    None if cik is None else str(cik),
                "reg_cik":     None if cik is None else str(cik).zfill(10),
            }
    return ctx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build context map + report counts only; "
                             "no writes.")
    args = parser.parse_args()

    prod_con = duckdb.connect(PROD_DB)
    stg_con = duckdb.connect(STAGING_DB, read_only=True)

    try:
        before = prod_con.execute(
            "SELECT COUNT(*) FROM pending_entity_resolution "
            "WHERE identifier_type = 'series_id' AND context_json IS NULL"
        ).fetchone()[0]
        print(f"NULL context_json (series_id) before: {before:,}")

        ctx_map = _build_context_map(prod_con, stg_con)
        print(f"context resolved for {len(ctx_map):,} series "
              f"({before - len(ctx_map):,} unresolvable)")

        if args.dry_run:
            print("[dry-run] no writes")
            return

        # Build a DataFrame and UPDATE via JOIN (one statement, batched).
        import pandas as pd
        rows = [{"series_id": sid, "context_json": json.dumps(ctx)}
                for sid, ctx in ctx_map.items()]
        if not rows:
            print("nothing to update")
            return
        df = pd.DataFrame(rows)
        prod_con.register("ctx_df", df)
        prod_con.execute(
            """
            UPDATE pending_entity_resolution AS p
               SET context_json = c.context_json
              FROM ctx_df AS c
             WHERE p.identifier_type = 'series_id'
               AND p.identifier_value = c.series_id
               AND p.context_json IS NULL
            """
        )
        prod_con.unregister("ctx_df")
        prod_con.execute("CHECKPOINT")

        after = prod_con.execute(
            "SELECT COUNT(*) FROM pending_entity_resolution "
            "WHERE identifier_type = 'series_id' AND context_json IS NULL"
        ).fetchone()[0]
        print(f"NULL context_json (series_id) after:  {after:,}")
        print(f"backfilled: {before - after:,}")

    finally:
        stg_con.close()
        prod_con.close()


if __name__ == "__main__":
    main()
