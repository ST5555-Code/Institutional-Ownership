#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# promote_nport.py unit: one (series_id, report_month) tuple.
# Each tuple is the commit boundary — DELETE prior + INSERT new + impact
# update happen atomically per (series, month). The full run completes
# after all tuples are promoted; partial promotion is allowed (any
# completed tuple stays committed).
"""promote_nport.py — promote staged N-PORT data (staging → prod).

Runs after validate_nport.py marks a run "Promote-ready: YES". Refuses
otherwise. Group 2 entity columns (entity_id / rollup_entity_id /
dm_entity_id / dm_rollup_entity_id / dm_rollup_name) are enriched at
promote time via lookup against entity_current — the prod source of
truth for the entity MDM. Group 3 columns (ticker resolution / market
data) are NOT touched here; they are owned by enrich_holdings.py.

Steps:
  1. Verify validation report says "Promote-ready: YES".
  2. Mirror the run's manifest + impacts rows from staging → prod.
  3. For each (series_id, report_month) tuple:
       - DELETE from prod fund_holdings_v2 by (series_id, report_month)
       - INSERT staged rows enriched with Group 2 columns
       - Impact promote_status='promoted', promoted_at=NOW()
  4. UPSERT prod fund_universe rows for each series_id touched.
  5. stamp_freshness for fund_holdings_v2 + fund_universe.
  6. refresh_snapshot() copies prod → 13f_readonly.duckdb.

Amendment handling: an amended N-PORT-P with the same
(series_id, report_month) replaces the prior accession's rows. Manifest
row for the prior accession remains in place as history;
``ingestion_manifest_current`` view filters by superseded_by_manifest_id.

Usage:
  python3 scripts/promote_nport.py --run-id R
  python3 scripts/promote_nport.py --run-id R --exclude SID1,SID2
  python3 scripts/promote_nport.py --run-id R --test
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
from pipeline.shared import refresh_snapshot, stamp_freshness  # noqa: E402


REPORTS_DIR = os.path.join(BASE_DIR, "logs", "reports")


def _read_validation_report(run_id: str) -> str:
    path = os.path.join(REPORTS_DIR, f"nport_{run_id}.md")
    if not os.path.exists(path):
        raise SystemExit(
            f"No validation report at {path} — run validate_nport.py first"
        )
    with open(path) as fh:
        return fh.read()


def _assert_promote_ok(report_text: str) -> None:
    if ("Promote-ready: **YES**" not in report_text
            and "Promote-ready: YES" not in report_text):
        raise SystemExit(
            "Validation report says NOT promote-ready — aborting. "
            "Resolve BLOCKs (and entity-gate blocks) and re-validate."
        )


# ---------------------------------------------------------------------------
# Manifest / impact mirroring
# ---------------------------------------------------------------------------

def _mirror_manifest_and_impacts(prod_con, staging_con, run_id: str):
    """Copy this run's ingestion_manifest + ingestion_impacts rows to prod."""
    mf_rows = staging_con.execute(
        "SELECT * FROM ingestion_manifest "
        "WHERE run_id = ? AND source_type = 'NPORT'",
        [run_id],
    ).fetchdf()
    if mf_rows.empty:
        return [], []
    mf_ids = [int(x) for x in mf_rows["manifest_id"].tolist()]
    mf_keys = mf_rows["object_key"].tolist()

    prod_con.register("mf", mf_rows)
    prod_con.execute(
        f"DELETE FROM ingestion_manifest "
        f"WHERE manifest_id IN ({','.join('?' * len(mf_ids))})",
        mf_ids,
    )
    prod_con.execute(
        f"DELETE FROM ingestion_manifest "
        f"WHERE object_key IN ({','.join('?' * len(mf_keys))})",
        mf_keys,
    )
    prod_con.execute("INSERT INTO ingestion_manifest SELECT * FROM mf")
    prod_con.unregister("mf")

    im_rows = staging_con.execute(
        f"SELECT * FROM ingestion_impacts "
        f"WHERE manifest_id IN ({','.join('?' * len(mf_ids))})",
        mf_ids,
    ).fetchdf()
    if not im_rows.empty:
        prod_con.register("im", im_rows)
        prod_con.execute(
            f"DELETE FROM ingestion_impacts "
            f"WHERE manifest_id IN ({','.join('?' * len(mf_ids))})",
            mf_ids,
        )
        prod_con.execute("INSERT INTO ingestion_impacts SELECT * FROM im")
        prod_con.unregister("im")
    return mf_ids, im_rows


# ---------------------------------------------------------------------------
# Group 2 entity enrichment
# ---------------------------------------------------------------------------

def _enrich_entity(prod_con, series_id: str) -> dict:
    """Return Group 2 entity columns for one series_id from entity_current.

    Looks up entity_id via entity_identifiers (identifier_type='series_id',
    valid_to='9999-12-31'), then resolves both rollup worldviews via
    entity_rollup_history and the EC rollup_name via entity_aliases
    preferred lookup. Returns a dict with keys matching the Group 2
    columns in fund_holdings_v2; NULLs for any column that can't be
    resolved (validate_nport should have caught BLOCK-level gaps but
    we don't trust the gate to be perfect — defensive NULL).
    """
    row = prod_con.execute(
        """
        SELECT ec.rollup_entity_id   AS rollup_entity_id,
               dm.rollup_entity_id   AS dm_rollup_entity_id,
               ec.entity_id          AS entity_id,
               dm.entity_id          AS dm_entity_id,
               (SELECT alias_name FROM entity_aliases
                  WHERE entity_id = ec.rollup_entity_id
                    AND is_preferred = TRUE
                    AND valid_to = DATE '9999-12-31'
                  LIMIT 1)           AS dm_rollup_name
        FROM entity_identifiers ei
        LEFT JOIN entity_rollup_history ec
               ON ec.entity_id = ei.entity_id
              AND ec.rollup_type = 'economic_control_v1'
              AND ec.valid_to = DATE '9999-12-31'
        LEFT JOIN entity_rollup_history dm
               ON dm.entity_id = ei.entity_id
              AND dm.rollup_type = 'decision_maker_v1'
              AND dm.valid_to = DATE '9999-12-31'
        WHERE ei.identifier_type = 'series_id'
          AND ei.identifier_value = ?
          AND ei.valid_to = DATE '9999-12-31'
        LIMIT 1
        """,
        [series_id],
    ).fetchone()
    if row is None:
        return {
            "entity_id": None, "rollup_entity_id": None,
            "dm_entity_id": None, "dm_rollup_entity_id": None,
            "dm_rollup_name": None,
        }
    rollup_id, dm_rollup_id, entity_id, dm_entity_id, dm_name = row
    return {
        "entity_id":            entity_id,
        "rollup_entity_id":     rollup_id,
        "dm_entity_id":         dm_entity_id,
        "dm_rollup_entity_id":  dm_rollup_id,
        "dm_rollup_name":       dm_name,
    }


# ---------------------------------------------------------------------------
# Promote
# ---------------------------------------------------------------------------

def _staged_tuples(staging_con, run_id: str, exclude: set[str]):
    """Return distinct (series_id, report_month) tuples for this run."""
    rows = staging_con.execute(
        """
        SELECT DISTINCT s.series_id, s.report_month
        FROM stg_nport_holdings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
        ORDER BY s.series_id, s.report_month
        """,
        [run_id],
    ).fetchall()
    return [(s, m) for (s, m) in rows if s not in exclude]


def _promote_tuple(prod_con, staging_con, manifest_ids,
                   series_id: str, report_month: str) -> tuple[int, int]:
    """Replace prod rows for (series_id, report_month) with staged rows.

    Returns (deleted, inserted).
    """
    deleted = prod_con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE series_id = ? AND report_month = ?",
        [series_id, report_month],
    ).fetchone()[0]
    prod_con.execute(
        "DELETE FROM fund_holdings_v2 "
        "WHERE series_id = ? AND report_month = ?",
        [series_id, report_month],
    )

    enrich = _enrich_entity(prod_con, series_id)

    # Pull staged rows for this tuple
    placeholders = ",".join("?" * len(manifest_ids))
    df = staging_con.execute(
        f"""
        SELECT fund_cik, fund_name, family_name, series_id,
               quarter, report_month, report_date,
               cusip, isin, issuer_name, ticker, asset_category,
               shares_or_principal, market_value_usd, pct_of_nav,
               fair_value_level, is_restricted, payoff_profile,
               loaded_at, fund_strategy, best_index
        FROM stg_nport_holdings
        WHERE series_id = ?
          AND report_month = ?
          AND manifest_id IN ({placeholders})
        """,
        [series_id, report_month] + list(manifest_ids),
    ).fetchdf()
    if df.empty:
        return int(deleted), 0

    # Add Group 2 columns
    df["entity_id"] = enrich["entity_id"]
    df["rollup_entity_id"] = enrich["rollup_entity_id"]
    df["dm_entity_id"] = enrich["dm_entity_id"]
    df["dm_rollup_entity_id"] = enrich["dm_rollup_entity_id"]
    df["dm_rollup_name"] = enrich["dm_rollup_name"]

    # Match prod fund_holdings_v2 column order
    prod_cols = [
        "fund_cik", "fund_name", "family_name", "series_id",
        "quarter", "report_month", "report_date", "cusip", "isin",
        "issuer_name", "ticker", "asset_category",
        "shares_or_principal", "market_value_usd", "pct_of_nav",
        "fair_value_level", "is_restricted", "payoff_profile",
        "loaded_at", "fund_strategy", "best_index",
        "entity_id", "rollup_entity_id", "dm_entity_id",
        "dm_rollup_entity_id", "dm_rollup_name",
    ]
    df = df[prod_cols]

    prod_con.register("ins_df", df)
    prod_con.execute(
        f"INSERT INTO fund_holdings_v2 ({','.join(prod_cols)}) "
        f"SELECT {','.join(prod_cols)} FROM ins_df"
    )
    prod_con.unregister("ins_df")
    return int(deleted), len(df)


def _upsert_universe(prod_con, staging_con, manifest_ids,
                     series_ids: set[str]) -> int:
    if not series_ids:
        return 0
    placeholders_m = ",".join("?" * len(manifest_ids))
    placeholders_s = ",".join("?" * len(series_ids))
    df = staging_con.execute(
        f"""
        SELECT fund_cik, fund_name, series_id, family_name,
               total_net_assets, fund_category, is_actively_managed,
               total_holdings_count, equity_pct, top10_concentration,
               last_updated, fund_strategy, best_index
        FROM stg_nport_fund_universe
        WHERE manifest_id IN ({placeholders_m})
          AND series_id IN ({placeholders_s})
        """,
        list(manifest_ids) + list(series_ids),
    ).fetchdf()
    if df.empty:
        return 0
    sids = df["series_id"].tolist()
    prod_con.execute(
        f"DELETE FROM fund_universe WHERE series_id IN "
        f"({','.join('?' * len(sids))})",
        sids,
    )
    prod_con.register("u_df", df)
    prod_con.execute(
        """
        INSERT INTO fund_universe (
            fund_cik, fund_name, series_id, family_name,
            total_net_assets, fund_category, is_actively_managed,
            total_holdings_count, equity_pct, top10_concentration,
            last_updated, fund_strategy, best_index
        )
        SELECT fund_cik, fund_name, series_id, family_name,
               total_net_assets, fund_category, is_actively_managed,
               total_holdings_count, equity_pct, top10_concentration,
               last_updated, fund_strategy, best_index
        FROM u_df
        """
    )
    prod_con.unregister("u_df")
    return len(df)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Promote N-PORT staging → prod")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--exclude", default="",
                        help="Comma-separated series_ids to hold out")
    parser.add_argument("--test", action="store_true",
                        help="Promote whatever the run staged — no extra "
                             "behaviour; flag exists for parity with "
                             "fetch_nport_v2.py --test.")
    args = parser.parse_args()

    exclude = {s.strip() for s in args.exclude.split(",") if s.strip()}
    report_text = _read_validation_report(args.run_id)
    _assert_promote_ok(report_text)

    staging_con = duckdb.connect(STAGING_DB, read_only=True)
    prod_con = duckdb.connect(PROD_DB)
    try:
        try:
            prod_con.execute("SELECT 1 FROM ingestion_manifest LIMIT 1")
        except duckdb.CatalogException as exc:
            raise SystemExit(
                "ingestion_manifest not present in prod — run migration 001 first"
            ) from exc

        manifest_ids, _impact_rows = _mirror_manifest_and_impacts(
            prod_con, staging_con, args.run_id,
        )
        if not manifest_ids:
            print(f"No manifest rows for run_id={args.run_id}")
            return

        tuples = _staged_tuples(staging_con, args.run_id, exclude)
        print(f"Promoting run_id={args.run_id}  test={args.test}")
        print(f"  tuples to promote: {len(tuples)}")

        total_deleted = total_inserted = 0
        series_touched: set[str] = set()
        for sid, rm in tuples:
            d, i = _promote_tuple(
                prod_con, staging_con, manifest_ids, sid, rm,
            )
            total_deleted += d
            total_inserted += i
            series_touched.add(sid)
            prod_con.execute("CHECKPOINT")
            print(f"    {sid} {rm}: -{d} +{i}")

        u = _upsert_universe(
            prod_con, staging_con, manifest_ids, series_touched,
        )
        print(f"  fund_universe upserts: {u}")

        # Update impacts → promoted in prod copy
        prod_con.execute(
            """
            UPDATE ingestion_impacts
               SET promote_status = 'promoted',
                   rows_promoted = rows_staged,
                   promoted_at = CURRENT_TIMESTAMP
             WHERE manifest_id IN (SELECT manifest_id FROM ingestion_manifest
                                    WHERE run_id = ? AND source_type = 'NPORT')
               AND unit_type = 'series_month'
               AND unit_key_json IN ({})
            """.format(",".join("?" * len(tuples))) if tuples else
            """
            UPDATE ingestion_impacts SET promote_status = 'promoted',
                rows_promoted = rows_staged, promoted_at = CURRENT_TIMESTAMP
             WHERE manifest_id IN (SELECT manifest_id FROM ingestion_manifest
                                    WHERE run_id = ? AND source_type = 'NPORT')
               AND unit_type = 'series_month'
            """,
            [args.run_id] + (
                [json.dumps({"series_id": s, "report_month": m})
                 for s, m in tuples]
                if tuples else []
            ),
        )
        prod_con.execute("CHECKPOINT")

        stamp_freshness(prod_con, "fund_holdings_v2")
        stamp_freshness(prod_con, "fund_universe")
        prod_con.execute("CHECKPOINT")

        print(f"\nDONE  -{total_deleted} +{total_inserted} holdings  "
              f"u={u} universe rows  series={len(series_touched)}")
    finally:
        staging_con.close()
        prod_con.close()

    refresh_snapshot()
    print("DONE  promote_nport")


if __name__ == "__main__":
    main()
