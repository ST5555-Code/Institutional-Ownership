"""ComputePeerRotationPipeline — precompute for ``peer_rotation_flows``.

perf-p0-s1. Materializes the per-(quarter pair × sector × entity × ticker)
net active flow that ``queries.get_peer_rotation`` previously computed at
request time. Session 2 (separate ticket) rewires ``queries.py`` to read
from this table.

Source tables:
  * ``holdings_v2`` (level='parent') — both ``economic_control_v1`` and
    ``decision_maker_v1`` rollups.
  * ``fund_holdings_v2`` (level='fund') — ``economic_control_v1`` only;
    fund series do not have a DM rollup.
  * ``market_data`` for sector mapping (TRIM-aware match; the lone
    whitespace-only sector — 268 tickers, data-quality debt — is excluded
    via ``TRIM(sector) <> ''``).

Quarter pairs are derived from ``SELECT DISTINCT quarter`` on each source
table — consecutive pairs only.

Per-pair the pipeline materializes ONE temp aggregate covering all
sectors, then loops sectors over the materialized temp. This avoids the
26-redundant-full-table-scan pattern of running the original CTE
per-sector. The temp is dropped after each pair before the next pair is
processed.

Validation gates:
  * BLOCK if 0 rows produced.
  * FLAG ≥20% row-count swing vs the prior prod row count (skipped on
    first run when prod has none).

Promote semantics: ``direct_write`` with a coarse-grained scope-set
delete keyed on ``(quarter_from, quarter_to, level, rollup_type)`` —
the base ABC's per-PK-row delete would issue one DELETE per staged
row (~9M+ for a full rebuild). We override ``promote()`` to delete
once per scope tuple, then bulk INSERT.

Usage::

    python3 scripts/pipeline/compute_peer_rotation.py --dry-run
    python3 scripts/pipeline/compute_peer_rotation.py --staging
    python3 scripts/pipeline/compute_peer_rotation.py
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
    FetchResult, ParseResult, PromoteResult, SourcePipeline, ValidationResult,
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("quarter_from", "VARCHAR"),
    ("quarter_to",   "VARCHAR"),
    ("sector",       "VARCHAR"),
    ("entity",       "VARCHAR"),
    ("entity_type",  "VARCHAR"),
    ("ticker",       "VARCHAR"),
    ("active_flow",  "DOUBLE"),
    ("level",        "VARCHAR"),
    ("rollup_type",  "VARCHAR"),
    ("loaded_at",    "TIMESTAMP"),
]

_STG_TARGET_DDL = (
    "CREATE TABLE peer_rotation_flows (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)

# (rollup_type label, rollup-name column on holdings_v2). Fund path uses
# economic_control_v1 only — fund_holdings_v2 has no DM rollup column.
_PARENT_ROLLUP_SPECS: list[tuple[str, str]] = [
    ("economic_control_v1", "rollup_name"),
    ("decision_maker_v1",   "dm_rollup_name"),
]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ComputePeerRotationPipeline(SourcePipeline):
    """SourcePipeline for the ``peer_rotation_flows`` precompute table."""

    name = "peer_rotation"
    target_table = "peer_rotation_flows"
    amendment_strategy = "direct_write"
    # Coarse scope key for the overridden ``promote()``. Each staged row
    # carries the full PK (quarter_from, quarter_to, sector, entity,
    # ticker, level, rollup_type); the scope key below identifies the
    # range we wipe-and-rewrite per run.
    amendment_key = ("quarter_from", "quarter_to", "level", "rollup_type")

    # ---- target_table_spec ---------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": [
                "quarter_from", "quarter_to", "sector", "entity",
                "ticker", "level", "rollup_type",
            ],
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
        """Materialize per-pair temp aggregates, then loop sectors × rollup
        types and INSERT into the staging target table."""
        t0 = time.monotonic()
        alias = self._attach_prod(staging_con)
        try:
            sectors = self._fetch_sectors(staging_con, alias)
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
                "parse: %d sectors, %d parent pairs, %d fund pairs",
                len(sectors), len(parent_pairs), len(fund_pairs),
            )

            total_rows = 0
            total_rows += self._process_parent_pairs(
                staging_con, alias, parent_pairs, sectors,
            )
            total_rows += self._process_fund_pairs(
                staging_con, alias, fund_pairs, sectors,
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
        sectors: list[str],
    ) -> int:
        total = 0
        for q_from, q_to in pairs:
            self._materialize_parent_agg(staging_con, alias, q_from, q_to)
            try:
                for sector in sectors:
                    for rollup_type, rn_col in _PARENT_ROLLUP_SPECS:
                        t0 = time.monotonic()
                        n = self._insert_parent_flows(
                            staging_con, alias,
                            q_from, q_to, sector, rollup_type, rn_col,
                        )
                        total += n
                        self._logger.info(
                            "sector=%s pair=%s→%s level=parent "
                            "rollup=%s rows=%d time=%.2fs",
                            sector, q_from, q_to, rollup_type, n,
                            time.monotonic() - t0,
                        )
            finally:
                staging_con.execute("DROP TABLE IF EXISTS h_agg_pair")
        return total

    def _process_fund_pairs(
        self,
        staging_con: Any,
        alias: Optional[str],
        pairs: list[tuple[str, str]],
        sectors: list[str],
    ) -> int:
        total = 0
        for q_from, q_to in pairs:
            self._materialize_fund_agg(staging_con, alias, q_from, q_to)
            try:
                for sector in sectors:
                    t0 = time.monotonic()
                    n = self._insert_fund_flows(
                        staging_con, alias, q_from, q_to, sector,
                    )
                    total += n
                    self._logger.info(
                        "sector=%s pair=%s→%s level=fund "
                        "rollup=economic_control_v1 rows=%d time=%.2fs",
                        sector, q_from, q_to, n,
                        time.monotonic() - t0,
                    )
            finally:
                staging_con.execute("DROP TABLE IF EXISTS f_agg_pair")
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
                "peer_rotation_flows is empty after parse — "
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
            if swing_pct > 20:
                vr.flags.append(
                    f"row count swing {swing_pct:.1f}% "
                    f"(staged={staged_total:,} prior={prior_total:,})"
                )

        per_level = staging_con.execute(f"""
            SELECT level, rollup_type, COUNT(*) AS rows
              FROM {self.target_table}
             GROUP BY level, rollup_type
             ORDER BY level, rollup_type
        """).fetchall()
        for level, rollup_type, n in per_level:
            self._logger.info(
                "validate: level=%s rollup=%s rows=%d",
                level, rollup_type, n,
            )

        return vr

    # ---- promote (override) -------------------------------------------

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        """Coarse-scope DELETE-then-bulk-INSERT. The base ``direct_write``
        deletes per-row by ``amendment_key``; for this table the staged
        row count can run into the millions and per-row DELETE would
        thrash. We delete once per ``(quarter_from, quarter_to, level,
        rollup_type)`` scope tuple touched, then bulk INSERT.
        """
        rows = self._read_staged_rows()
        if rows.empty:
            return PromoteResult(run_id=run_id)

        manifest_id = self._manifest_id_for_run(prod_con, run_id)
        scope_keys = (
            rows[["quarter_from", "quarter_to", "level", "rollup_type"]]
            .drop_duplicates()
            .to_dict("records")
        )
        col_list = ", ".join(rows.columns)

        prod_con.execute("BEGIN TRANSACTION")
        try:
            for key in scope_keys:
                prod_con.execute(
                    f"DELETE FROM {self.target_table} "  # nosec B608
                    f"WHERE quarter_from = ? AND quarter_to = ? "
                    f"AND level = ? AND rollup_type = ?",
                    [
                        key["quarter_from"], key["quarter_to"],
                        key["level"], key["rollup_type"],
                    ],
                )
                self.record_impact(
                    prod_con, manifest_id=manifest_id, run_id=run_id,
                    action="upsert", rowkey=key,
                )

            prod_con.register("staged_rows", rows)
            try:
                prod_con.execute(
                    f"INSERT INTO {self.target_table} "  # nosec B608
                    f"({col_list}) SELECT {col_list} FROM staged_rows"
                )
            finally:
                prod_con.unregister("staged_rows")

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        return PromoteResult(
            run_id=run_id,
            rows_upserted=len(rows),
        )

    # ---- helpers -------------------------------------------------------

    def _attach_prod(self, staging_con: Any) -> Optional[str]:
        """Attach the prod DB read-only inside the staging connection
        under alias ``src_prod`` so source-table reads can join across.
        Returns the alias, or None when staging IS prod (no attach needed).
        """
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

    def _fetch_sectors(
        self, staging_con: Any, alias: Optional[str],
    ) -> list[str]:
        rows = staging_con.execute(
            f"SELECT DISTINCT TRIM(sector) AS sector "  # nosec B608
            f"FROM {self._src(alias, 'market_data')} "
            f"WHERE sector IS NOT NULL AND TRIM(sector) <> '' "
            f"ORDER BY sector"
        ).fetchall()
        return [r[0] for r in rows]

    def _materialize_parent_agg(
        self, staging_con: Any, alias: Optional[str],
        q_from: str, q_to: str,
    ) -> None:
        # PR #295's drop PR removed ``holdings_v2.dm_rollup_name``; resolve
        # the DM rollup name at read time via a LEFT JOIN to
        # ``entity_rollup_history`` + ``entities`` (Method A, canonical per
        # PR #280). Per-(cik, ticker, quarter) grouping aggregates with MAX
        # — same shape as the prior denormalized read.
        staging_con.execute("DROP TABLE IF EXISTS h_agg_pair")
        staging_con.execute(f"""
            CREATE TEMP TABLE h_agg_pair AS
            SELECT h.cik,
                   MAX(h.rollup_name)        AS rollup_name,
                   MAX(dm_e.canonical_name)  AS dm_rollup_name,
                   MAX(h.inst_parent_name)   AS inst_parent_name,
                   MAX(h.manager_name)       AS manager_name,
                   MAX(h.entity_type)        AS entity_type,
                   h.ticker,
                   h.quarter,
                   SUM(h.shares)             AS shares,
                   SUM(h.market_value_usd)   AS market_value_usd
              FROM {self._src(alias, 'holdings_v2')} h
              LEFT JOIN {self._src(alias, 'entity_rollup_history')} dm_erh
                     ON dm_erh.entity_id = h.entity_id
                    AND dm_erh.rollup_type = 'decision_maker_v1'
                    AND dm_erh.valid_to = DATE '9999-12-31'
              LEFT JOIN {self._src(alias, 'entities')} dm_e
                     ON dm_e.entity_id = dm_erh.rollup_entity_id
             WHERE h.ticker IS NOT NULL
               AND h.quarter IN (?, ?)
               AND h.is_latest = TRUE
             GROUP BY h.cik, h.ticker, h.quarter
        """, [q_from, q_to])  # nosec B608 — identifier is from class constant

    def _materialize_fund_agg(
        self, staging_con: Any, alias: Optional[str],
        q_from: str, q_to: str,
    ) -> None:
        # PR-4: read fund_strategy from fund_universe (the canonical, locked
        # source) rather than fund_holdings_v2 (per-row, per-quarter snapshot
        # that drifts when classify_fund recomputes). The JOIN replaces the
        # MAX(fh.fund_strategy) aggregate; series_id with no fund_universe
        # row falls back to NULL (LEFT JOIN), preserving the prior behaviour
        # for orphan series (small set; covered by canonical-value-coverage-
        # audit follow-up).
        staging_con.execute("DROP TABLE IF EXISTS f_agg_pair")
        staging_con.execute(f"""
            CREATE TEMP TABLE f_agg_pair AS
            SELECT fh.series_id,
                   MAX(fh.fund_name)     AS fund_name,
                   MAX(fu.fund_strategy) AS fund_strategy,
                   fh.ticker,
                   fh.quarter,
                   SUM(fh.shares_or_principal) AS shares,
                   SUM(fh.market_value_usd)    AS market_value_usd
              FROM {self._src(alias, 'fund_holdings_v2')} fh
              LEFT JOIN {self._src(alias, 'fund_universe')} fu
                ON fh.series_id = fu.series_id
             WHERE fh.ticker IS NOT NULL
               AND fh.quarter IN (?, ?)
               AND fh.is_latest = TRUE
             GROUP BY fh.series_id, fh.ticker, fh.quarter
        """, [q_from, q_to])  # nosec B608 — identifier is from class constant

    def _insert_parent_flows(
        self,
        staging_con: Any,
        alias: Optional[str],
        q_from: str,
        q_to: str,
        sector: str,
        rollup_type: str,
        rn_col: str,
    ) -> int:
        before = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE quarter_from = ? AND quarter_to = ? AND sector = ? "
            f"AND level = 'parent' AND rollup_type = ?",
            [q_from, q_to, sector, rollup_type],
        ).fetchone()[0]
        staging_con.execute(f"""
            INSERT INTO {self.target_table}
            (quarter_from, quarter_to, sector, entity, entity_type, ticker,
             active_flow, level, rollup_type, loaded_at)
            WITH flows AS (
                SELECT
                    COALESCE(c.{rn_col}, c.inst_parent_name, c.manager_name) AS entity,
                    c.entity_type AS entity_type,
                    c.ticker,
                    (c.shares - COALESCE(p.shares, 0))
                      * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0))
                      AS active_flow
                  FROM h_agg_pair c
                  LEFT JOIN h_agg_pair p
                    ON c.cik = p.cik
                   AND c.ticker = p.ticker
                   AND p.quarter = ?
                  JOIN {self._src(alias, 'market_data')} md
                    ON c.ticker = md.ticker
                   AND TRIM(md.sector) = ?
                   AND TRIM(md.sector) <> ''
                 WHERE c.quarter = ?
                UNION ALL
                SELECT
                    COALESCE(p.{rn_col}, p.inst_parent_name, p.manager_name) AS entity,
                    p.entity_type AS entity_type,
                    p.ticker,
                    -p.market_value_usd AS active_flow
                  FROM h_agg_pair p
                  LEFT JOIN h_agg_pair c
                    ON p.cik = c.cik
                   AND p.ticker = c.ticker
                   AND c.quarter = ?
                  JOIN {self._src(alias, 'market_data')} md
                    ON p.ticker = md.ticker
                   AND TRIM(md.sector) = ?
                   AND TRIM(md.sector) <> ''
                 WHERE p.quarter = ?
                   AND c.cik IS NULL
            )
            SELECT
                ? AS quarter_from,
                ? AS quarter_to,
                ? AS sector,
                entity,
                MAX(entity_type) AS entity_type,
                ticker,
                SUM(active_flow) AS active_flow,
                'parent' AS level,
                ? AS rollup_type,
                CURRENT_TIMESTAMP AS loaded_at
              FROM flows
             WHERE entity IS NOT NULL
             GROUP BY entity, ticker
            HAVING SUM(active_flow) IS NOT NULL
        """, [
            q_from, sector, q_to,
            q_to, sector, q_from,
            q_from, q_to, sector, rollup_type,
        ])  # nosec B608 — table/column identifiers are class constants and an enum-checked rn_col
        after = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE quarter_from = ? AND quarter_to = ? AND sector = ? "
            f"AND level = 'parent' AND rollup_type = ?",
            [q_from, q_to, sector, rollup_type],
        ).fetchone()[0]
        return after - before

    def _insert_fund_flows(
        self,
        staging_con: Any,
        alias: Optional[str],
        q_from: str,
        q_to: str,
        sector: str,
    ) -> int:
        before = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE quarter_from = ? AND quarter_to = ? AND sector = ? "
            f"AND level = 'fund' AND rollup_type = 'economic_control_v1'",
            [q_from, q_to, sector],
        ).fetchone()[0]
        staging_con.execute(f"""
            INSERT INTO {self.target_table}
            (quarter_from, quarter_to, sector, entity, entity_type, ticker,
             active_flow, level, rollup_type, loaded_at)
            WITH flows AS (
                SELECT
                    c.fund_name AS entity,
                    c.fund_strategy AS entity_type,
                    c.ticker,
                    (c.shares - COALESCE(p.shares, 0))
                      * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0))
                      AS active_flow
                  FROM f_agg_pair c
                  LEFT JOIN f_agg_pair p
                    ON c.series_id = p.series_id
                   AND c.ticker = p.ticker
                   AND p.quarter = ?
                  JOIN {self._src(alias, 'market_data')} md
                    ON c.ticker = md.ticker
                   AND TRIM(md.sector) = ?
                   AND TRIM(md.sector) <> ''
                 WHERE c.quarter = ?
                UNION ALL
                SELECT
                    p.fund_name AS entity,
                    p.fund_strategy AS entity_type,
                    p.ticker,
                    -p.market_value_usd AS active_flow
                  FROM f_agg_pair p
                  LEFT JOIN f_agg_pair c
                    ON p.series_id = c.series_id
                   AND p.ticker = c.ticker
                   AND c.quarter = ?
                  JOIN {self._src(alias, 'market_data')} md
                    ON p.ticker = md.ticker
                   AND TRIM(md.sector) = ?
                   AND TRIM(md.sector) <> ''
                 WHERE p.quarter = ?
                   AND c.series_id IS NULL
            )
            SELECT
                ? AS quarter_from,
                ? AS quarter_to,
                ? AS sector,
                entity,
                MAX(entity_type) AS entity_type,
                ticker,
                SUM(active_flow) AS active_flow,
                'fund' AS level,
                'economic_control_v1' AS rollup_type,
                CURRENT_TIMESTAMP AS loaded_at
              FROM flows
             WHERE entity IS NOT NULL
             GROUP BY entity, ticker
            HAVING SUM(active_flow) IS NOT NULL
        """, [
            q_from, sector, q_to,
            q_to, sector, q_from,
            q_from, q_to, sector,
        ])  # nosec B608 — table identifiers are class constants
        after = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE quarter_from = ? AND quarter_to = ? AND sector = ? "
            f"AND level = 'fund' AND rollup_type = 'economic_control_v1'",
            [q_from, q_to, sector],
        ).fetchone()[0]
        return after - before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _project_dry_run(prod_db_path: str) -> int:
    """Read-only projection. Counts source rows per (pair × level × sector)
    without materializing flows. Returns total projected (entity, ticker)
    pairs across all scopes — an upper bound on the precompute row count.

    The actual row count after the LEFT JOIN + COALESCE-on-entity step is
    smaller because (a) entities with NULL across all three name columns
    are dropped, and (b) zero-flow groups are excluded by ``HAVING``.
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
        parent_pairs = list(zip(parent_quarters[:-1], parent_quarters[1:]))
        fund_pairs = list(zip(fund_quarters[:-1], fund_quarters[1:]))

        print(f"sectors:       {len(sectors)}")
        print(f"parent pairs:  {len(parent_pairs)}")
        print(f"fund pairs:    {len(fund_pairs)}")
        print()
        print("Projection (upper bound, summed across rollup types):")
        print(f"  {'level':6s} {'pair':18s} {'sector':40s} {'rows':>10s}")

        total = 0
        for q_from, q_to in parent_pairs:
            for sector in sectors:
                row = con.execute("""
                    SELECT COUNT(*)
                      FROM (
                          SELECT DISTINCT cik, ticker
                            FROM holdings_v2
                           WHERE quarter IN (?, ?)
                             AND is_latest = TRUE
                             AND ticker IS NOT NULL
                      ) h
                      JOIN market_data md
                        ON h.ticker = md.ticker
                       AND TRIM(md.sector) = ?
                       AND TRIM(md.sector) <> ''
                """, [q_from, q_to, sector]).fetchone()
                # Multiplied by 2 rollup types for parent.
                n = (row[0] or 0) * 2
                total += n
                if n:
                    print(f"  parent {q_from}->{q_to:8s} {sector:40s} {n:>10,}")
        for q_from, q_to in fund_pairs:
            for sector in sectors:
                row = con.execute("""
                    SELECT COUNT(*)
                      FROM (
                          SELECT DISTINCT series_id, ticker
                            FROM fund_holdings_v2
                           WHERE quarter IN (?, ?)
                             AND is_latest = TRUE
                             AND ticker IS NOT NULL
                      ) f
                      JOIN market_data md
                        ON f.ticker = md.ticker
                       AND TRIM(md.sector) = ?
                       AND TRIM(md.sector) <> ''
                """, [q_from, q_to, sector]).fetchone()
                n = row[0] or 0
                total += n
                if n:
                    print(f"  fund   {q_from}->{q_to:8s} {sector:40s} {n:>10,}")

        print()
        print(f"Projected total rows (upper bound): {total:,}")
        return total
    finally:
        con.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute peer_rotation_flows precompute table.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Read-only row count projection per (pair × level × sector). No writes.",
    )
    parser.add_argument(
        "--staging", action="store_true",
        help="Run fetch + parse + validate against staging DB; do not promote to prod.",
    )
    return parser.parse_args()


def _resolve_db_paths() -> tuple[str, str]:
    """Return ``(prod_db_path, staging_db_path)``. Falls back to the
    repository's ``data/`` directory under BASE_DIR when ``db.py`` cannot
    be imported (e.g., misconfigured environment)."""
    try:
        from db import PROD_DB, STAGING_DB  # noqa: WPS433
        return PROD_DB, STAGING_DB
    except ImportError:
        return (
            os.path.join(BASE_DIR, "data", "13f.duckdb"),
            os.path.join(BASE_DIR, "data", "13f_staging.duckdb"),
        )


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    prod_db, staging_db = _resolve_db_paths()

    if args.dry_run:
        target_db = staging_db if args.staging else prod_db
        print(f"DRY-RUN against {target_db}")
        print("=" * 78)
        _project_dry_run(target_db)
        print("=" * 78)
        print("DRY-RUN: no writes. Re-run without --dry-run to apply.")
        return

    pipeline = ComputePeerRotationPipeline(
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
        f"promoted: rows_upserted={result.rows_upserted} "
        f"({result.duration_seconds:.1f}s)"
    )


if __name__ == "__main__":
    main()
