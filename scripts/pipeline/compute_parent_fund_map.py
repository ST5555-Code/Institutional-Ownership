"""ComputeParentFundMapPipeline — precompute for ``parent_fund_map``.

perf-P2. Materializes the per-(rollup_entity_id × rollup_type × series_id ×
quarter) parent-to-N-PORT-fund-children mapping previously computed at
request time inside ``queries.holder_momentum._get_fund_children`` via 25
``family_name ILIKE`` patterns against the 14.6M-row ``fund_holdings_v2``
table per parent.

Hot-path verification (perf-P2 scoping doc §4.2):
  * ``holder_momentum`` parent path AAPL/EQT median 800/745 ms
  * ``_get_fund_children`` loop 728 ms / 91% of total

After this precompute, ``_get_fund_children`` becomes a single JOIN keyed
on ``(rollup_entity_id, rollup_type)`` against ``parent_fund_map`` plus a
``(series_id, quarter)`` JOIN to ``fund_holdings_v2``. Target latency:
800 ms → <200 ms.

Source tables:
  * ``holdings_v2`` — distinct ``(rollup_entity_id, rollup_name)`` and
    ``(dm_rollup_entity_id, dm_rollup_name)`` pairs are the universe of
    parent rollups to map. Both rollup_types are materialized.
  * ``fund_holdings_v2`` — all ``is_latest=TRUE`` rows; family-name ILIKE
    join produces the per-parent fund-series set.
  * ``ncen_adviser_map`` — drives the sub-adviser exclusions defined in
    ``config.SUBADVISER_EXCLUSIONS`` (currently Geode under Fidelity/FMR).
  * ``fund_family_patterns`` — keyword → search-term map; same lookup as
    ``queries.match_nport_family``.

Match semantics are kept identical to ``queries.match_nport_family``:
  1. Each parent rollup name is lowercased and looked up against the
     ``fund_family_patterns`` keyword groupings.
  2. If no key matches, fall back to the parent name's first
     slash/paren-delimited word (length > 2).
  3. Sub-adviser exclusions defined in ``SUBADVISER_EXCLUSIONS`` are
     filtered out via ``ncen_adviser_map``.

Build strategy: collect every ``(rollup_entity_id, rollup_type, pattern)``
in Python, build a single VALUES-table CTE per rollup_type, then run one
JOIN against ``fund_holdings_v2`` with the optional sub-adviser
``NOT EXISTS`` filter. One INSERT per rollup_type; no per-parent loop in
SQL.

Promote semantics: ``direct_write`` with the base ABC's per-PK-row
DELETE-then-INSERT. Row count is bounded (estimated 200K-600K rows on
the current corpus), so the fine-grained delete is acceptable.

Usage::

    python3 scripts/pipeline/compute_parent_fund_map.py --dry-run
    python3 scripts/pipeline/compute_parent_fund_map.py --staging
    python3 scripts/pipeline/compute_parent_fund_map.py
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
    ("rollup_entity_id", "BIGINT"),
    ("rollup_type",      "VARCHAR"),
    ("series_id",        "VARCHAR"),
    ("quarter",          "VARCHAR"),
    ("fund_name",        "VARCHAR"),
    ("family_name",      "VARCHAR"),
    ("loaded_at",        "TIMESTAMP"),
]

_STG_TARGET_DDL = (
    "CREATE TABLE parent_fund_map (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)

# (rollup_type label, rollup-name column, rollup-eid column on holdings_v2).
_PARENT_ROLLUP_SPECS: list[tuple[str, str, str]] = [
    ("economic_control_v1", "rollup_name",    "rollup_entity_id"),
    ("decision_maker_v1",   "dm_rollup_name", "dm_rollup_entity_id"),
]


# ---------------------------------------------------------------------------
# Match-pattern helpers (mirror queries.match_nport_family semantics).
# Kept inline rather than importing from queries.py so the pipeline does
# not depend on the request-path module.
# ---------------------------------------------------------------------------

def _match_patterns(
    name: str,
    patterns_by_key: dict[str, list[str]],
) -> list[str]:
    if not name:
        return []
    name_lower = name.lower()
    for key, search_terms in patterns_by_key.items():
        if key in name_lower or any(
            t.lower() in name_lower for t in search_terms
        ):
            return search_terms
    first_word = name.split('/')[0].split('(')[0].strip()
    return [first_word] if first_word and len(first_word) > 2 else []


def _exclusions_for(
    family_patterns: list[str],
    exclusions_by_key: dict[str, list[str]],
) -> list[str]:
    out: list[str] = []
    for pattern in family_patterns:
        for key, excl_list in exclusions_by_key.items():
            if key in pattern.lower():
                out.extend(excl_list)
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ComputeParentFundMapPipeline(SourcePipeline):
    """SourcePipeline for the ``parent_fund_map`` precompute table."""

    name = "parent_fund_map"
    target_table = "parent_fund_map"
    amendment_strategy = "direct_write"
    amendment_key = (
        "rollup_entity_id", "rollup_type", "series_id", "quarter",
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
        """Build per-rollup_type VALUES CTEs and run one JOIN against a
        pre-aggregated ``(series_id, quarter, family_name, fund_name)``
        temp.

        Pre-aggregating fund_holdings_v2 first is critical: a direct
        ILIKE JOIN against the 14.6M-row table balloons to a multi-hour
        nested loop. The DISTINCT temp is ~50K rows, so the same JOIN
        runs in seconds.
        """
        t0 = time.monotonic()
        alias = self._attach_prod(staging_con)
        try:
            patterns_by_key = self._load_family_patterns(staging_con, alias)
            exclusions_by_key = self._load_subadviser_exclusions()

            self._materialize_fund_series_temp(staging_con, alias)
            try:
                total_rows = 0
                for rollup_type, name_col, eid_col in _PARENT_ROLLUP_SPECS:
                    t_rt = time.monotonic()
                    n = self._build_for_rollup(
                        staging_con, alias,
                        rollup_type=rollup_type,
                        name_col=name_col,
                        eid_col=eid_col,
                        patterns_by_key=patterns_by_key,
                        exclusions_by_key=exclusions_by_key,
                    )
                    total_rows += n
                    self._logger.info(
                        "rollup=%s rows=%d time=%.2fs",
                        rollup_type, n, time.monotonic() - t_rt,
                    )
            finally:
                staging_con.execute("DROP TABLE IF EXISTS pfm_fund_series")
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
                "parent_fund_map is empty after parse — "
                "check holdings_v2 / fund_holdings_v2 source data and "
                "fund_family_patterns coverage"
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
            SELECT rollup_type, COUNT(*) AS rows,
                   COUNT(DISTINCT rollup_entity_id) AS distinct_parents
              FROM {self.target_table}
             GROUP BY rollup_type
             ORDER BY rollup_type
        """).fetchall()
        for rollup_type, n, parents in per_bucket:
            self._logger.info(
                "validate: rollup=%s rows=%d distinct_parents=%d",
                rollup_type, n, parents,
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

    def _materialize_fund_series_temp(
        self, staging_con: Any, alias: Optional[str],
    ) -> None:
        """Pre-aggregate fund_holdings_v2 to (series_id, quarter,
        family_name, fund_name). Drops cardinality from 14.6M rows to
        ~50K so the family-name ILIKE JOIN against parent_patterns
        completes in seconds rather than hours.
        """
        t0 = time.monotonic()
        staging_con.execute("DROP TABLE IF EXISTS pfm_fund_series")
        staging_con.execute(f"""
            CREATE TEMP TABLE pfm_fund_series AS
            SELECT
                series_id,
                quarter,
                family_name,
                ANY_VALUE(fund_name) AS fund_name
              FROM {self._src(alias, 'fund_holdings_v2')}
             WHERE is_latest = TRUE
               AND series_id IS NOT NULL
               AND family_name IS NOT NULL
             GROUP BY series_id, quarter, family_name
        """)  # nosec B608 — table identifiers are class constants
        n = staging_con.execute(
            "SELECT COUNT(*) FROM pfm_fund_series"
        ).fetchone()[0]
        self._logger.info(
            "materialized pfm_fund_series: %d rows in %.2fs",
            n, time.monotonic() - t0,
        )

    def _load_family_patterns(
        self, staging_con: Any, alias: Optional[str],
    ) -> dict[str, list[str]]:
        """Load fund_family_patterns from prod (or fall back to the
        in-process constant). Same lookup shape as
        ``queries.get_nport_family_patterns``: dict keyed by
        ``inst_parent_name`` keyword → list of search patterns."""
        try:
            rows = staging_con.execute(
                f"SELECT inst_parent_name, pattern "
                f"FROM {self._src(alias, 'fund_family_patterns')} "
                f"ORDER BY inst_parent_name, pattern"
            ).fetchall()
        except duckdb.Error as e:
            self._logger.warning(
                "fund_family_patterns unavailable: %s", e,
            )
            return {}
        grouped: dict[str, list[str]] = {}
        for key, pattern in rows:
            grouped.setdefault(key, []).append(pattern)
        return grouped

    @staticmethod
    def _load_subadviser_exclusions() -> dict[str, list[str]]:
        from config import SUBADVISER_EXCLUSIONS  # noqa: WPS433  pylint: disable=import-outside-toplevel
        return dict(SUBADVISER_EXCLUSIONS)

    def _build_for_rollup(
        self,
        staging_con: Any,
        alias: Optional[str],
        *,
        rollup_type: str,
        name_col: str,
        eid_col: str,
        patterns_by_key: dict[str, list[str]],
        exclusions_by_key: dict[str, list[str]],
    ) -> int:
        """For one rollup_type: collect distinct (eid, name) parents from
        holdings_v2, expand each via match_nport_family, build a VALUES
        table of (eid, pattern) + (eid, excl_pattern), and run one INSERT
        joining ``fund_holdings_v2``.
        """
        rows = staging_con.execute(f"""
            SELECT DISTINCT {eid_col} AS eid,
                   {name_col} AS name
              FROM {self._src(alias, 'holdings_v2')}
             WHERE is_latest = TRUE
               AND {eid_col} IS NOT NULL
               AND {name_col} IS NOT NULL
        """).fetchall()  # nosec B608 — column / table identifiers come from class constants

        eid_pattern_pairs: list[tuple[int, str]] = []
        eid_excl_pairs: list[tuple[int, str]] = []
        for eid, name in rows:
            patterns = _match_patterns(name, patterns_by_key)
            if not patterns:
                continue
            for p in patterns:
                eid_pattern_pairs.append((int(eid), '%' + p + '%'))
            for excl in _exclusions_for(patterns, exclusions_by_key):
                eid_excl_pairs.append((int(eid), '%' + excl + '%'))

        if not eid_pattern_pairs:
            self._logger.warning(
                "no parent patterns produced for rollup=%s — skipping",
                rollup_type,
            )
            return 0

        # Build VALUES list literally — DuckDB's parameterized VALUES does
        # not handle this many tuples efficiently. Pattern strings are
        # bounded (family-name keywords) and come from the seeded
        # ``fund_family_patterns`` table or a parent's first word; not
        # user-provided. SQL-quote escape via doubled single quotes.
        pp_values = ", ".join(
            f"({eid}, '{p.replace(chr(39), chr(39) * 2)}')"
            for eid, p in eid_pattern_pairs
        )

        if eid_excl_pairs:
            pe_values = ", ".join(
                f"({eid}, '{p.replace(chr(39), chr(39) * 2)}')"
                for eid, p in eid_excl_pairs
            )
            excl_cte = f""",
            parent_exclusions AS (
                SELECT * FROM (VALUES {pe_values}) AS t(eid, excl_pattern)
            ),
            excluded_series AS (
                SELECT DISTINCT pe.eid, nam.series_id
                  FROM parent_exclusions pe
                  JOIN {self._src(alias, 'ncen_adviser_map')} nam
                    ON nam.adviser_name ILIKE pe.excl_pattern
            )"""
            excl_where = """
              AND NOT EXISTS (
                  SELECT 1 FROM excluded_series es
                   WHERE es.eid = pp.eid
                     AND es.series_id = fh.series_id
              )"""
        else:
            excl_cte = ""
            excl_where = ""

        before = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE rollup_type = ?",
            [rollup_type],
        ).fetchone()[0]

        staging_con.execute(f"""
            INSERT INTO {self.target_table}
            (rollup_entity_id, rollup_type, series_id, quarter,
             fund_name, family_name, loaded_at)
            WITH parent_patterns AS (
                SELECT * FROM (VALUES {pp_values}) AS t(eid, pattern)
            ){excl_cte}
            SELECT
                pp.eid AS rollup_entity_id,
                ? AS rollup_type,
                fs.series_id,
                fs.quarter,
                ANY_VALUE(fs.fund_name)   AS fund_name,
                ANY_VALUE(fs.family_name) AS family_name,
                CURRENT_TIMESTAMP         AS loaded_at
              FROM parent_patterns pp
              JOIN pfm_fund_series fs
                ON fs.family_name ILIKE pp.pattern
             WHERE 1=1
               {excl_where.replace('fh.series_id', 'fs.series_id')}
             GROUP BY pp.eid, fs.series_id, fs.quarter
        """, [rollup_type])  # nosec B608 — table identifiers are class constants

        after = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE rollup_type = ?",
            [rollup_type],
        ).fetchone()[0]
        return after - before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _project_dry_run(prod_db_path: str) -> int:
    """Read-only projection. Counts distinct rollup parents and the
    fund_holdings_v2 universe size to bound the row count."""
    if not os.path.exists(prod_db_path):
        print(f"DB not found: {prod_db_path} — skipping projection")
        return 0

    con = duckdb.connect(prod_db_path, read_only=True)
    try:
        ec_parents = con.execute(
            "SELECT COUNT(DISTINCT rollup_entity_id) FROM holdings_v2 "
            "WHERE is_latest = TRUE AND rollup_entity_id IS NOT NULL"
        ).fetchone()[0]
        dm_parents = con.execute(
            "SELECT COUNT(DISTINCT dm_rollup_entity_id) FROM holdings_v2 "
            "WHERE is_latest = TRUE AND dm_rollup_entity_id IS NOT NULL"
        ).fetchone()[0]
        fund_quarters = con.execute(
            "SELECT COUNT(DISTINCT quarter) FROM fund_holdings_v2 "
            "WHERE is_latest = TRUE"
        ).fetchone()[0]
        print(f"distinct EC parents: {ec_parents:,}")
        print(f"distinct DM parents: {dm_parents:,}")
        print(f"fund quarters:       {fund_quarters}")
        # Coarse upper-bound estimate: each parent x ~10 series x ~16 quarters
        # is a worst-case fan-out; actual depends on family-pattern coverage.
        upper = (ec_parents + dm_parents) * 10 * fund_quarters
        print(f"row-count upper bound (very loose): {upper:,}")
        return upper
    finally:
        con.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute parent_fund_map precompute table.",
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

    pipeline = ComputeParentFundMapPipeline(
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
