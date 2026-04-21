#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# promote_nport.py unit: one full run.
# Batch rewrite (2026-04-17) — the run's tuples are promoted as a single
# DELETE + INSERT, not per-tuple. Pre-rewrite, per-tuple CHECKPOINT at
# DERA scale (20K+ tuples) took 2+ hours; batch completes in seconds.
# mig-01 Phase 1 (2026-04-21) — the write sequence is wrapped in one
# explicit BEGIN TRANSACTION / COMMIT / ROLLBACK boundary. The DELETE
# of fund_holdings_v2 and its replacement INSERT are now atomic: a
# mid-sequence crash rolls back cleanly and leaves prod holdings
# untouched. A single CHECKPOINT runs after COMMIT (DuckDB rejects
# CHECKPOINT inside a transaction).
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
from pipeline.manifest import mirror_manifest_and_impacts  # noqa: E402
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
# Group 2 entity enrichment (bulk)
# ---------------------------------------------------------------------------

def _bulk_enrich_run(prod_con, series_touched: set[str]) -> int:
    """Single bulk UPDATE...FROM JOIN to populate Group 2 entity columns.

    Replaces the per-tuple Python loop that called `_enrich_entity()` once
    per series — at DERA-Session-2 scale (~12K series × ~3 months) the
    per-call overhead dominated promote runtime (~1h31m on the 2026-04-15
    re-promote). One JOIN against the full prod entity graph plus a
    `series_id IN (...)` scope keeps the work O(touched series) and runs
    in seconds.

    Column outputs are bit-for-bit identical to the legacy
    `_enrich_entity()` per-call SQL:
      * entity_id            ← entity_identifiers.entity_id (the fund)
      * rollup_entity_id     ← economic_control_v1 rollup
      * dm_entity_id         ← entity_identifiers.entity_id (the fund —
                               legacy aliased dm.entity_id which equals
                               ei.entity_id by JOIN constraint)
      * dm_rollup_entity_id  ← decision_maker_v1 rollup
      * dm_rollup_name       ← preferred alias of EC rollup_entity_id
                               (NOT the DM rollup; preserved to match
                               legacy behaviour)

    Returns the count of distinct series the UPDATE scoped over (one row
    per fund-holdings record receives the same enrichment values).
    """
    if not series_touched:
        return 0
    sids = sorted(series_touched)
    placeholders = ",".join("?" * len(sids))
    prod_con.execute(
        f"""
        UPDATE fund_holdings_v2 AS fh
           SET entity_id           = e.entity_id,
               rollup_entity_id    = e.ec_rollup_entity_id,
               dm_entity_id        = e.entity_id,
               dm_rollup_entity_id = e.dm_rollup_entity_id,
               dm_rollup_name      = e.dm_rollup_name
          FROM (
              SELECT ei.identifier_value      AS series_id,
                     ei.entity_id             AS entity_id,
                     ec.rollup_entity_id      AS ec_rollup_entity_id,
                     dm.rollup_entity_id      AS dm_rollup_entity_id,
                     ea.alias_name            AS dm_rollup_name
                FROM entity_identifiers ei
                LEFT JOIN entity_rollup_history ec
                       ON ec.entity_id = ei.entity_id
                      AND ec.rollup_type = 'economic_control_v1'
                      AND ec.valid_to = DATE '9999-12-31'
                LEFT JOIN entity_rollup_history dm
                       ON dm.entity_id = ei.entity_id
                      AND dm.rollup_type = 'decision_maker_v1'
                      AND dm.valid_to = DATE '9999-12-31'
                LEFT JOIN entity_aliases ea
                       ON ea.entity_id = ec.rollup_entity_id
                      AND ea.is_preferred = TRUE
                      AND ea.valid_to = DATE '9999-12-31'
               WHERE ei.identifier_type = 'series_id'
                 AND ei.valid_to = DATE '9999-12-31'
                 AND ei.identifier_value IN ({placeholders})
          ) AS e
         WHERE fh.series_id = e.series_id
           AND fh.series_id IN ({placeholders})
        """,
        sids + sids,
    )
    return len(sids)


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


# Stable column lists. Group 2 entity columns are filled by
# `_bulk_enrich_run` after all per-tuple inserts complete; the per-tuple
# INSERT leaves them NULL, then a single UPDATE...FROM JOIN populates
# them once for every series in series_touched.
_STAGED_COLS = [
    "fund_cik", "fund_name", "family_name", "series_id",
    "quarter", "report_month", "report_date", "cusip", "isin",
    "issuer_name", "ticker", "asset_category",
    "shares_or_principal", "market_value_usd", "pct_of_nav",
    "fair_value_level", "is_restricted", "payoff_profile",
    "loaded_at", "fund_strategy", "best_index",
]


def _promote_batch(prod_con, staging_con, manifest_ids,
                   tuples: list[tuple[str, str]]) -> tuple[int, int]:
    """Replace prod rows for every (series_id, report_month) in `tuples`
    with their staged equivalents.

    Executes as a single DELETE + INSERT, not per-tuple — pre-rewrite
    per-tuple CHECKPOINTs took 2+ hours on DERA-scale runs. The caller
    wraps this call in an explicit transaction (mig-01 Phase 1); the
    single CHECKPOINT runs after COMMIT.

    Group 2 entity columns are inserted NULL; `_bulk_enrich_run` fills
    them in one UPDATE after this returns.

    Returns (total_deleted, total_inserted).
    """
    if not tuples:
        return 0, 0

    # Build a two-column TEMP table of the tuples to promote — DuckDB
    # doesn't accept tuple-IN-tuple list bindings directly, and a very
    # large (series, month) IN (...) expression would blow argv/parse
    # limits. A TEMP table with an index on (series_id, report_month)
    # is the clean path and cheap at these sizes.
    prod_con.execute("DROP TABLE IF EXISTS _promote_scope")
    prod_con.execute(
        "CREATE TEMP TABLE _promote_scope "
        "(series_id VARCHAR, report_month VARCHAR)"
    )
    import pandas as pd
    scope_df = pd.DataFrame(tuples, columns=["series_id", "report_month"])
    prod_con.register("_scope_df", scope_df)
    prod_con.execute(
        "INSERT INTO _promote_scope SELECT * FROM _scope_df"
    )
    prod_con.unregister("_scope_df")

    deleted = prod_con.execute(
        """
        SELECT COUNT(*) FROM fund_holdings_v2 fh
        WHERE (fh.series_id, fh.report_month) IN (
            SELECT series_id, report_month FROM _promote_scope
        )
        """
    ).fetchone()[0]
    prod_con.execute(
        """
        DELETE FROM fund_holdings_v2
        WHERE (series_id, report_month) IN (
            SELECT series_id, report_month FROM _promote_scope
        )
        """
    )

    # Pull the whole scoped staged slice in one shot.
    m_placeholders = ",".join("?" * len(manifest_ids))
    df = staging_con.execute(
        f"""
        SELECT {','.join(_STAGED_COLS)}
        FROM stg_nport_holdings s
        WHERE s.manifest_id IN ({m_placeholders})
          AND (s.series_id, s.report_month) IN (
              SELECT series_id, report_month FROM (
                  SELECT UNNEST(?) AS series_id, UNNEST(?) AS report_month
              )
          )
        """,
        list(manifest_ids) + [
            [t[0] for t in tuples],
            [t[1] for t in tuples],
        ],
    ).fetchdf()

    inserted = 0
    if not df.empty:
        prod_con.register("ins_df", df)
        prod_con.execute(
            f"INSERT INTO fund_holdings_v2 ({','.join(_STAGED_COLS)}) "
            f"SELECT {','.join(_STAGED_COLS)} FROM ins_df"
        )
        prod_con.unregister("ins_df")
        inserted = len(df)

    prod_con.execute("DROP TABLE IF EXISTS _promote_scope")
    return int(deleted), inserted


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
    parser.add_argument("--exclude-file", default=None,
                        help="File with one series_id per line to hold out. "
                             "Merged with --exclude (union). Useful when the "
                             "exclude list is too large for argv.")
    parser.add_argument("--test", action="store_true",
                        help="Promote whatever the run staged — no extra "
                             "behaviour; flag exists for parity with "
                             "fetch_nport_v2.py --test.")
    args = parser.parse_args()

    exclude = {s.strip() for s in args.exclude.split(",") if s.strip()}
    if args.exclude_file:
        with open(args.exclude_file, encoding="utf-8") as fh:
            exclude |= {line.strip() for line in fh if line.strip()}
        print(f"  --exclude-file: loaded {len(exclude):,} series to skip")
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

        # mig-01 Phase 1: wrap the whole write sequence in one explicit
        # transaction. DELETE+INSERT of fund_holdings_v2 + manifest mirror
        # + impacts UPDATE all roll back together on any failure.
        # CHECKPOINT cannot run inside a DuckDB transaction — the single
        # post-COMMIT CHECKPOINT below replaces the three former
        # intermediate ones.
        prod_con.execute("BEGIN TRANSACTION")
        try:
            manifest_ids, _impacts_inserted = mirror_manifest_and_impacts(
                prod_con, staging_con, args.run_id, "NPORT",
            )
            if not manifest_ids:
                prod_con.execute("ROLLBACK")
                print(f"No manifest rows for run_id={args.run_id}")
                return

            tuples = _staged_tuples(staging_con, args.run_id, exclude)
            print(f"Promoting run_id={args.run_id}  test={args.test}")
            print(f"  tuples to promote: {len(tuples)}")

            total_deleted, total_inserted = _promote_batch(
                prod_con, staging_con, manifest_ids, tuples,
            )
            series_touched: set[str] = {s for s, _m in tuples}
            print(f"  batch promote: -{total_deleted} +{total_inserted} holdings")

            # Single bulk enrichment pass — fills Group 2 entity columns for
            # every row inserted above.
            enriched_series = _bulk_enrich_run(prod_con, series_touched)
            print(f"  bulk enrichment: {enriched_series} series")

            u = _upsert_universe(
                prod_con, staging_con, manifest_ids, series_touched,
            )
            print(f"  fund_universe upserts: {u}")

            # Batch UPDATE: mark every promoted tuple as `promoted`. The
            # unit_key_json is a JSON object — build the string with the same
            # formatting DuckDB produces to ensure IN-match works.
            if tuples:
                unit_keys = [
                    json.dumps({"series_id": s, "report_month": m})
                    for s, m in tuples
                ]
                prod_con.register(
                    "_tuple_keys",
                    __import__("pandas").DataFrame(
                        {"unit_key_json": unit_keys}
                    ),
                )
                prod_con.execute(
                    """
                    UPDATE ingestion_impacts
                       SET promote_status = 'promoted',
                           rows_promoted  = rows_staged,
                           promoted_at    = CURRENT_TIMESTAMP
                     WHERE manifest_id IN (SELECT manifest_id FROM ingestion_manifest
                                            WHERE run_id = ? AND source_type = 'NPORT')
                       AND unit_type = 'series_month'
                       AND unit_key_json IN (SELECT unit_key_json FROM _tuple_keys)
                    """,
                    [args.run_id],
                )
                prod_con.unregister("_tuple_keys")
            else:
                prod_con.execute(
                    """
                    UPDATE ingestion_impacts
                       SET promote_status = 'promoted',
                           rows_promoted  = rows_staged,
                           promoted_at    = CURRENT_TIMESTAMP
                     WHERE manifest_id IN (SELECT manifest_id FROM ingestion_manifest
                                            WHERE run_id = ? AND source_type = 'NPORT')
                       AND unit_type = 'series_month'
                    """,
                    [args.run_id],
                )
            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        # Freshness stamps + CHECKPOINT run outside the transaction.
        # stamp_freshness is metadata — a crash between COMMIT and the
        # stamp is recoverable by re-running (the stamp converges).
        # CHECKPOINT cannot run inside a transaction, so it lives here
        # exactly once per successful promote.
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
