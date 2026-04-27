"""ComputeSectorFlowsPipeline — precompute for ``sector_flows_rollup``.

perf-P1 part 1. Materializes the per-(quarter pair × level × rollup_type ×
active_only × sector) flow aggregate that ``queries.get_sector_flows``
previously computed at request time. The aggregate is small (~351 rows on
the current corpus) — the perf win is moving an ~1.2s scan of
``holdings_v2`` / ``fund_holdings_v2`` out of the request path. Target
post-rewrite latency for ``get_sector_flows``: <50ms.

Source tables:
  * ``holdings_v2`` (level='parent') — both ``economic_control_v1`` and
    ``decision_maker_v1`` rollup_type rows. The aggregate values are
    rollup-agnostic (managers / new_positions / exits count distinct
    CIKs, not rollup entities), so EC and DM rows carry identical
    metrics today. Both rollup_types are stored to keep the schema
    forward-compatible with rollup-aware aggregations.
  * ``fund_holdings_v2`` (level='fund') — ``economic_control_v1`` only.
    fund_holdings has no DM rollup. ``active_only`` is ignored on the
    fund path (matches the original CTE behavior); we always store
    ``active_only=FALSE`` rows for fund and the read query always
    selects FALSE for level='fund'.
  * ``market_data`` for sector mapping (TRIM-aware match; whitespace-
    only sectors are dropped via ``TRIM(sector) <> ''``). Note:
    'Derivative' / 'ETF' sectors are *included* in the rollup table;
    ``get_sector_flows`` filters them at read time so the precompute
    stays a faithful materialization of the source data.

Quarter pairs are derived from ``SELECT DISTINCT quarter`` on each
source table — consecutive pairs only.

Per pair the pipeline materializes ONE typed temp ``flows`` table
covering all sectors and entity rows, then runs aggregate INSERTs
keyed by (rollup_type, active_only) into the staging target. For the
parent path this is 4 INSERTs per pair (2 rollup_types × 2
active_only states); for the fund path 1 INSERT per pair. The
``flows`` temp is dropped between pairs.

int-22 fix note — the original ``get_sector_flows`` SQL had a latent
bug: when ``active_only=True`` the query referenced ``c.entity_type``
on a CTE that did not project the column, raising
``BinderException`` at runtime. The original code path was only
exercised with ``active_only=False`` so prod never noticed. This
precompute restores correctness by including ``entity_type`` in the
per-pair temp; ``active_only=True`` rows are now legitimately
populated.

Promote semantics: ``direct_write`` with the base ABC's per-PK-row
DELETE-then-INSERT. Row count is small (~hundreds), so the
fine-grained delete is not a perf concern here.

Usage::

    python3 scripts/pipeline/compute_sector_flows.py --dry-run
    python3 scripts/pipeline/compute_sector_flows.py --staging
    python3 scripts/pipeline/compute_sector_flows.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any, Optional

import duckdb

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from pipeline.base import (  # noqa: E402  pylint: disable=wrong-import-position
    FetchResult, ParseResult, SourcePipeline, ValidationResult,
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("quarter_from",  "VARCHAR"),
    ("quarter_to",    "VARCHAR"),
    ("level",         "VARCHAR"),
    ("rollup_type",   "VARCHAR"),
    ("active_only",   "BOOLEAN"),
    ("gics_sector",   "VARCHAR"),
    ("net",           "DOUBLE"),
    ("inflow",        "DOUBLE"),
    ("outflow",       "DOUBLE"),
    ("new_positions", "BIGINT"),
    ("exits",         "BIGINT"),
    ("managers",      "BIGINT"),
    ("loaded_at",     "TIMESTAMP"),
]

_STG_TARGET_DDL = (
    "CREATE TABLE sector_flows_rollup (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)

# Parent rollup_types stored in the table. Aggregate values are
# rollup-agnostic today — both rows carry identical metrics. Keeping
# both lets a future rollup-aware query select by rollup_type without a
# schema migration.
_PARENT_ROLLUP_TYPES: tuple[str, ...] = (
    "economic_control_v1",
    "decision_maker_v1",
)

_ACTIVE_ENTITY_TYPES: tuple[str, ...] = ("active", "hedge_fund", "activist")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ComputeSectorFlowsPipeline(SourcePipeline):
    """SourcePipeline for the ``sector_flows_rollup`` precompute table."""

    name = "sector_flows"
    target_table = "sector_flows_rollup"
    amendment_strategy = "direct_write"
    amendment_key = (
        "quarter_from", "quarter_to", "level",
        "rollup_type", "active_only", "gics_sector",
    )

    # ---- target_table_spec ---------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": list(self.amendment_key),
            "indexes": [],
        }

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        """No external fetch — sources are internal prod tables. Recreates
        the staging target table so ``parse()`` writes fresh."""
        # pylint: disable=unused-argument
        t0 = time.monotonic()
        staging_con.execute(f"DROP TABLE IF EXISTS {self.target_table}")
        staging_con.execute(_STG_TARGET_DDL)
        return FetchResult(
            run_id="",
            rows_staged=0,
            raw_tables=[],
            duration_seconds=time.monotonic() - t0,
        )

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        """Materialize per-pair temp aggregates, then aggregate by sector
        for each (rollup_type, active_only) combination."""
        t0 = time.monotonic()
        alias = self._attach_prod(staging_con)
        try:
            parent_quarters = self._fetch_quarters(
                staging_con, alias, "holdings_v2",
            )
            fund_quarters = self._fetch_quarters(
                staging_con, alias, "fund_holdings_v2",
            )
            parent_pairs = list(
                zip(parent_quarters[:-1], parent_quarters[1:])
            )
            fund_pairs = list(
                zip(fund_quarters[:-1], fund_quarters[1:])
            )

            self._logger.info(
                "parse: %d parent pairs, %d fund pairs",
                len(parent_pairs), len(fund_pairs),
            )

            total_rows = 0
            total_rows += self._process_parent_pairs(
                staging_con, alias, parent_pairs,
            )
            total_rows += self._process_fund_pairs(
                staging_con, alias, fund_pairs,
            )
        finally:
            if alias:
                try:
                    staging_con.execute(f"DETACH {alias}")
                except duckdb.Error:  # nosec B110 — best-effort detach on cleanup
                    pass

        duration = time.monotonic() - t0
        self._logger.info(
            "parse complete: %d total rows in %.1fs", total_rows, duration,
        )
        return ParseResult(
            run_id="",
            rows_parsed=total_rows,
            target_staging_table=self.target_table,
            duration_seconds=duration,
        )

    def _process_parent_pairs(
        self,
        staging_con: Any,
        alias: Optional[str],
        pairs: list[tuple[str, str]],
    ) -> int:
        total = 0
        for q_from, q_to in pairs:
            self._materialize_parent_flows(staging_con, alias, q_from, q_to)
            try:
                for rollup_type in _PARENT_ROLLUP_TYPES:
                    for active_only in (False, True):
                        t0 = time.monotonic()
                        n = self._insert_aggregate(
                            staging_con, alias, q_from, q_to,
                            level="parent",
                            rollup_type=rollup_type,
                            active_only=active_only,
                            flows_table="flows_parent_pair",
                        )
                        total += n
                        self._logger.info(
                            "pair=%s→%s level=parent rollup=%s active=%s "
                            "rows=%d time=%.2fs",
                            q_from, q_to, rollup_type, active_only, n,
                            time.monotonic() - t0,
                        )
            finally:
                staging_con.execute("DROP TABLE IF EXISTS flows_parent_pair")
        return total

    def _process_fund_pairs(
        self,
        staging_con: Any,
        alias: Optional[str],
        pairs: list[tuple[str, str]],
    ) -> int:
        total = 0
        for q_from, q_to in pairs:
            self._materialize_fund_flows(staging_con, alias, q_from, q_to)
            try:
                t0 = time.monotonic()
                n = self._insert_aggregate(
                    staging_con, alias, q_from, q_to,
                    level="fund",
                    rollup_type="economic_control_v1",
                    active_only=False,
                    flows_table="flows_fund_pair",
                )
                total += n
                self._logger.info(
                    "pair=%s→%s level=fund rollup=economic_control_v1 "
                    "active=False rows=%d time=%.2fs",
                    q_from, q_to, n, time.monotonic() - t0,
                )
            finally:
                staging_con.execute("DROP TABLE IF EXISTS flows_fund_pair")
        return total

    # ---- validate ------------------------------------------------------

    def validate(
        self, staging_con: Any, prod_con: Any,
    ) -> ValidationResult:
        vr = ValidationResult()
        try:
            staged_total = staging_con.execute(
                f"SELECT COUNT(*) FROM {self.target_table}"  # nosec B608
            ).fetchone()[0]
        except duckdb.Error:
            staged_total = 0

        if staged_total == 0:
            vr.blocks.append(
                "sector_flows_rollup is empty after parse — "
                "check holdings_v2/fund_holdings_v2 source data"
            )
            return vr

        try:
            prior_total = prod_con.execute(
                f"SELECT COUNT(*) FROM {self.target_table}"  # nosec B608
            ).fetchone()[0]
        except duckdb.Error:
            prior_total = 0

        if prior_total > 0:
            swing_pct = abs(staged_total - prior_total) / prior_total * 100
            if swing_pct > 50:
                vr.flags.append(
                    f"row count swing {swing_pct:.1f}% "
                    f"(staged={staged_total:,} prior={prior_total:,})"
                )

        per_bucket = staging_con.execute(f"""
            SELECT level, rollup_type, active_only, COUNT(*) AS rows
              FROM {self.target_table}
             GROUP BY level, rollup_type, active_only
             ORDER BY level, rollup_type, active_only
        """).fetchall()
        for level, rollup_type, active_only, n in per_bucket:
            self._logger.info(
                "validate: level=%s rollup=%s active_only=%s rows=%d",
                level, rollup_type, active_only, n,
            )

        return vr

    # ---- helpers -------------------------------------------------------

    def _attach_prod(self, staging_con: Any) -> Optional[str]:
        if self._staging_db_path == self._prod_db_path:
            return None
        alias = "src_prod"
        try:
            staging_con.execute(f"DETACH {alias}")
        except duckdb.Error:  # nosec B110 — alias may not be attached yet
            pass
        staging_con.execute(
            f"ATTACH '{self._prod_db_path}' AS {alias} (READ_ONLY)"
        )
        return alias

    @staticmethod
    def _src(alias: Optional[str], table: str) -> str:
        return f"{alias}.{table}" if alias else table

    def _fetch_quarters(
        self, staging_con: Any, alias: Optional[str], table: str,
    ) -> list[str]:
        rows = staging_con.execute(
            f"SELECT DISTINCT quarter FROM {self._src(alias, table)} "  # nosec B608
            f"WHERE quarter IS NOT NULL ORDER BY quarter"
        ).fetchall()
        return [r[0] for r in rows]

    def _materialize_parent_flows(
        self, staging_con: Any, alias: Optional[str],
        q_from: str, q_to: str,
    ) -> None:
        """Materialize per-row flows for one parent pair, including
        ``entity_type`` for the active_only filter and ``flow_type`` for
        the new/exit/change classification.

        The CTE shape mirrors the original ``get_sector_flows`` parent
        query but adds ``entity_type`` to ``h_agg`` (the original missed
        it, breaking ``active_only=True`` at runtime — int-22 fix).
        """
        staging_con.execute("DROP TABLE IF EXISTS flows_parent_pair")
        staging_con.execute(f"""
            CREATE TEMP TABLE flows_parent_pair AS
            WITH h_agg AS (
                SELECT cik,
                       MAX(entity_type)      AS entity_type,
                       ticker,
                       quarter,
                       SUM(shares)           AS shares,
                       SUM(market_value_usd) AS market_value_usd
                  FROM {self._src(alias, 'holdings_v2')}
                 WHERE ticker IS NOT NULL
                   AND quarter IN (?, ?)
                   AND is_latest = TRUE
                 GROUP BY cik, ticker, quarter
            )
            SELECT
                c.cik          AS eid,
                c.entity_type  AS entity_type,
                c.ticker       AS ticker,
                (c.shares - COALESCE(p.shares, 0))
                  * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0))
                  AS active_flow,
                CASE WHEN p.cik IS NULL THEN 'new' ELSE 'change' END
                  AS flow_type
              FROM h_agg c
              LEFT JOIN h_agg p
                ON c.cik = p.cik
               AND c.ticker = p.ticker
               AND p.quarter = ?
             WHERE c.quarter = ?
            UNION ALL
            SELECT
                p.cik          AS eid,
                p.entity_type  AS entity_type,
                p.ticker       AS ticker,
                -p.market_value_usd AS active_flow,
                'exit'         AS flow_type
              FROM h_agg p
              LEFT JOIN h_agg c
                ON p.cik = c.cik
               AND p.ticker = c.ticker
               AND c.quarter = ?
             WHERE p.quarter = ?
               AND c.cik IS NULL
        """, [q_from, q_to, q_from, q_to, q_to, q_from])  # nosec B608 — table identifiers are class constants

    def _materialize_fund_flows(
        self, staging_con: Any, alias: Optional[str],
        q_from: str, q_to: str,
    ) -> None:
        """Materialize per-row flows for one fund pair. fund_holdings_v2
        has no entity_type column and the original query did not filter
        on it — fund rows are ``active_only=False`` only."""
        staging_con.execute("DROP TABLE IF EXISTS flows_fund_pair")
        staging_con.execute(f"""
            CREATE TEMP TABLE flows_fund_pair AS
            WITH f_agg AS (
                SELECT series_id,
                       ticker,
                       quarter,
                       SUM(shares_or_principal) AS shares,
                       SUM(market_value_usd)    AS market_value_usd
                  FROM {self._src(alias, 'fund_holdings_v2')}
                 WHERE ticker IS NOT NULL
                   AND quarter IN (?, ?)
                   AND is_latest = TRUE
                 GROUP BY series_id, ticker, quarter
            )
            SELECT
                c.series_id    AS eid,
                c.ticker       AS ticker,
                (c.shares - COALESCE(p.shares, 0))
                  * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0))
                  AS active_flow,
                CASE WHEN p.series_id IS NULL THEN 'new' ELSE 'change' END
                  AS flow_type
              FROM f_agg c
              LEFT JOIN f_agg p
                ON c.series_id = p.series_id
               AND c.ticker = p.ticker
               AND p.quarter = ?
             WHERE c.quarter = ?
            UNION ALL
            SELECT
                p.series_id    AS eid,
                p.ticker       AS ticker,
                -p.market_value_usd AS active_flow,
                'exit'         AS flow_type
              FROM f_agg p
              LEFT JOIN f_agg c
                ON p.series_id = c.series_id
               AND p.ticker = c.ticker
               AND c.quarter = ?
             WHERE p.quarter = ?
               AND c.series_id IS NULL
        """, [q_from, q_to, q_from, q_to, q_to, q_from])  # nosec B608 — table identifiers are class constants

    def _insert_aggregate(
        self,
        staging_con: Any,
        alias: Optional[str],
        q_from: str,
        q_to: str,
        *,
        level: str,
        rollup_type: str,
        active_only: bool,
        flows_table: str,
    ) -> int:
        """Aggregate the per-row flows temp into per-sector rollup rows
        and INSERT them into the staging target. Returns the row count
        inserted for this (level × rollup_type × active_only) bucket.

        The market_data join applies a TRIM filter so the lone
        whitespace-only sector is excluded; 'Derivative' / 'ETF' /
        other non-empty sectors are *included* — read-side queries
        filter them.
        """
        # Active filter is applied only on the parent path. Fund flows
        # do not carry entity_type and active_only is forced FALSE.
        if active_only and level == "parent":
            active_clause = (
                f"AND f.entity_type IN {_ACTIVE_ENTITY_TYPES!r}"
            )
        else:
            active_clause = ""

        before = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE quarter_from = ? AND quarter_to = ? "
            f"AND level = ? AND rollup_type = ? AND active_only = ?",
            [q_from, q_to, level, rollup_type, active_only],
        ).fetchone()[0]

        staging_con.execute(f"""
            INSERT INTO {self.target_table}
            (quarter_from, quarter_to, level, rollup_type, active_only,
             gics_sector, net, inflow, outflow, new_positions, exits,
             managers, loaded_at)
            SELECT
                ? AS quarter_from,
                ? AS quarter_to,
                ? AS level,
                ? AS rollup_type,
                ? AS active_only,
                md.sector AS gics_sector,
                SUM(f.active_flow) AS net,
                SUM(CASE WHEN f.active_flow > 0 THEN f.active_flow ELSE 0 END) AS inflow,
                SUM(CASE WHEN f.active_flow < 0 THEN f.active_flow ELSE 0 END) AS outflow,
                COUNT(DISTINCT CASE WHEN f.flow_type='new'
                                     THEN CAST(f.eid AS VARCHAR) || '|' || f.ticker END)
                  AS new_positions,
                COUNT(DISTINCT CASE WHEN f.flow_type='exit'
                                     THEN CAST(f.eid AS VARCHAR) || '|' || f.ticker END)
                  AS exits,
                COUNT(DISTINCT f.eid) AS managers,
                CURRENT_TIMESTAMP AS loaded_at
              FROM {flows_table} f
              JOIN {self._src(alias, 'market_data')} md ON f.ticker = md.ticker
             WHERE md.sector IS NOT NULL
               AND TRIM(md.sector) <> ''
               {active_clause}
             GROUP BY md.sector
        """, [
            q_from, q_to, level, rollup_type, active_only,
        ])  # nosec B608 — active_clause built from constants; table identifiers are class constants

        after = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE quarter_from = ? AND quarter_to = ? "
            f"AND level = ? AND rollup_type = ? AND active_only = ?",
            [q_from, q_to, level, rollup_type, active_only],
        ).fetchone()[0]
        return after - before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _project_dry_run(prod_db_path: str) -> int:
    """Read-only projection. Counts source quarter pairs × sectors × buckets
    without materializing flows. Returns total projected row count.
    """
    if not os.path.exists(prod_db_path):
        print(f"DB not found: {prod_db_path} — skipping projection")
        return 0

    con = duckdb.connect(prod_db_path, read_only=True)
    try:
        sectors = [
            r[0] for r in con.execute(
                "SELECT DISTINCT TRIM(sector) AS sector "
                "FROM market_data "
                "WHERE sector IS NOT NULL AND TRIM(sector) <> '' "
                "ORDER BY sector"
            ).fetchall()
        ]
        parent_quarters = [
            r[0] for r in con.execute(
                "SELECT DISTINCT quarter FROM holdings_v2 "
                "WHERE quarter IS NOT NULL ORDER BY quarter"
            ).fetchall()
        ]
        fund_quarters = [
            r[0] for r in con.execute(
                "SELECT DISTINCT quarter FROM fund_holdings_v2 "
                "WHERE quarter IS NOT NULL ORDER BY quarter"
            ).fetchall()
        ]
        parent_pairs = max(0, len(parent_quarters) - 1)
        fund_pairs = max(0, len(fund_quarters) - 1)
        parent_rows = (
            len(sectors) * parent_pairs
            * len(_PARENT_ROLLUP_TYPES) * 2  # 2 active_only states
        )
        fund_rows = len(sectors) * fund_pairs * 1 * 1
        total = parent_rows + fund_rows

        print(f"sectors:            {len(sectors)}")
        print(f"parent pairs:       {parent_pairs}")
        print(f"fund pairs:         {fund_pairs}")
        print(f"parent rollup_types: {len(_PARENT_ROLLUP_TYPES)} "
              f"× 2 active_only = {len(_PARENT_ROLLUP_TYPES) * 2} buckets")
        print()
        print(f"Projected parent rows: {parent_rows:,}")
        print(f"Projected fund rows:   {fund_rows:,}")
        print(f"Projected total rows:  {total:,}")
        return total
    finally:
        con.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute sector_flows_rollup precompute table.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Read-only row count projection. No writes.",
    )
    parser.add_argument(
        "--staging", action="store_true",
        help="Run fetch + parse + validate against staging DB; do not promote to prod.",
    )
    parser.add_argument(
        "--prod-db", default=None,
        help="Override prod DB path (defaults to db.PROD_DB).",
    )
    parser.add_argument(
        "--staging-db", default=None,
        help="Override staging DB path (defaults to db.STAGING_DB).",
    )
    return parser.parse_args()


def _resolve_db_paths(
    prod_override: Optional[str], staging_override: Optional[str],
) -> tuple[str, str]:
    if prod_override and staging_override:
        return prod_override, staging_override
    try:
        from db import PROD_DB, STAGING_DB  # noqa: WPS433
        return prod_override or PROD_DB, staging_override or STAGING_DB
    except ImportError:
        return (
            prod_override or os.path.join(BASE_DIR, "data", "13f.duckdb"),
            staging_override or os.path.join(BASE_DIR, "data", "13f_staging.duckdb"),
        )


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    prod_db, staging_db = _resolve_db_paths(args.prod_db, args.staging_db)

    if args.dry_run:
        target_db = staging_db if args.staging else prod_db
        print(f"DRY-RUN against {target_db}")
        print("=" * 78)
        _project_dry_run(target_db)
        print("=" * 78)
        print("DRY-RUN: no writes. Re-run without --dry-run to apply.")
        return

    pipeline = ComputeSectorFlowsPipeline(
        prod_db_path=prod_db,
        staging_db_path=staging_db,
    )
    t0 = time.monotonic()
    run_id = pipeline.run(scope={})
    print(f"run() complete: run_id={run_id} ({time.monotonic() - t0:.1f}s)")

    if args.staging:
        print(
            f"--staging: stopped at pending_approval. "
            f"Output is in {staging_db}.{pipeline.target_table}. "
            f"Re-run without --staging to promote to prod."
        )
        return

    result = pipeline.approve_and_promote(run_id)
    print(
        f"promoted: rows_inserted={result.rows_inserted} "
        f"rows_upserted={result.rows_upserted} "
        f"({result.duration_seconds:.1f}s)"
    )


if __name__ == "__main__":
    main()
