"""Read-only inventory of fund_holdings_v2 series_ids that have no
matching row in fund_universe (the "orphan" cohort surfaced by PR #242).

Produces a JSON dump on stdout consumed by the investigation doc.
No DB writes — pure SELECTs against data/13f.duckdb.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"

ORPHAN_CTE = """
WITH orphan AS (
    SELECT fh.*
    FROM fund_holdings_v2 fh
    LEFT JOIN fund_universe fu USING (series_id)
    WHERE fu.series_id IS NULL
)
"""


def fetch(con, sql, params=None):
    return con.execute(sql, params or []).fetchall()


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    out: dict = {}

    # ---- Phase 1: totals ------------------------------------------------
    out["phase1_totals_is_latest"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT
            COUNT(DISTINCT series_id) AS distinct_series,
            COUNT(*)                  AS row_count,
            SUM(market_value_usd)     AS aum_usd
        FROM orphan
        WHERE is_latest = TRUE
        """,
    )[0]

    out["phase1_totals_all_history"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT
            COUNT(DISTINCT series_id) AS distinct_series,
            COUNT(*)                  AS row_count,
            SUM(market_value_usd)     AS aum_usd
        FROM orphan
        """,
    )[0]

    out["phase1_per_quarter"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT quarter,
               COUNT(DISTINCT series_id) AS distinct_series,
               COUNT(*)                  AS row_count,
               SUM(market_value_usd)     AS aum_usd
        FROM orphan
        WHERE is_latest = TRUE
        GROUP BY quarter
        ORDER BY quarter
        """,
    )

    out["phase1_top25_by_rows"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT series_id,
               ANY_VALUE(fund_name)  AS fund_name,
               ANY_VALUE(fund_cik)   AS fund_cik,
               COUNT(*)              AS row_count,
               SUM(market_value_usd) AS aum_usd
        FROM orphan
        WHERE is_latest = TRUE
        GROUP BY series_id
        ORDER BY row_count DESC
        LIMIT 25
        """,
    )

    out["phase1_top25_by_aum"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT series_id,
               ANY_VALUE(fund_name)  AS fund_name,
               ANY_VALUE(fund_cik)   AS fund_cik,
               COUNT(*)              AS row_count,
               SUM(market_value_usd) AS aum_usd
        FROM orphan
        WHERE is_latest = TRUE
        GROUP BY series_id
        ORDER BY aum_usd DESC NULLS LAST
        LIMIT 25
        """,
    )

    out["phase1_per_series_date_range_count"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT series_id,
               MIN(report_month) AS first_seen,
               MAX(report_month) AS last_seen,
               COUNT(DISTINCT report_month) AS month_count
        FROM orphan
        GROUP BY series_id
        ORDER BY last_seen DESC
        LIMIT 25
        """,
    )

    # ---- Phase 2: cohort partition --------------------------------------
    cohort_sql = ORPHAN_CTE + """,
    classed AS (
        SELECT *,
               CASE
                 WHEN series_id LIKE 'SYN_%'                   THEN 'SYN_prefix'
                 WHEN regexp_matches(series_id, '^S[0-9]{9}$') THEN 'S9digit'
                 WHEN series_id = 'UNKNOWN'                    THEN 'UNKNOWN_literal'
                 ELSE 'Other'
               END AS cohort
        FROM orphan
    )
    SELECT cohort,
           COUNT(DISTINCT series_id) AS distinct_series,
           COUNT(*)                  AS row_count_latest,
           SUM(market_value_usd)     AS aum_usd_latest
    FROM classed
    WHERE is_latest = TRUE
    GROUP BY cohort
    ORDER BY row_count_latest DESC
    """
    out["phase2_cohort_summary"] = fetch(con, cohort_sql)

    # Sample "Other" cohort
    out["phase2_other_sample"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT series_id,
               ANY_VALUE(fund_name) AS fund_name,
               COUNT(*)             AS row_count
        FROM orphan
        WHERE is_latest = TRUE
          AND series_id NOT LIKE 'SYN_%'
          AND NOT regexp_matches(series_id, '^S[0-9]{9}$')
          AND series_id <> 'UNKNOWN'
        GROUP BY series_id
        ORDER BY row_count DESC
        LIMIT 25
        """,
    )

    # ---- Phase 3: root-cause trace per cohort ---------------------------
    # 3a. per-cohort fund_strategy_at_filing distribution (snapshot label)
    out["phase3_strategy_at_filing_by_cohort"] = fetch(
        con,
        ORPHAN_CTE
        + """,
        classed AS (
            SELECT *,
                   CASE
                     WHEN series_id LIKE 'SYN_%'                   THEN 'SYN_prefix'
                     WHEN regexp_matches(series_id, '^S[0-9]{9}$') THEN 'S9digit'
                     WHEN series_id = 'UNKNOWN'                    THEN 'UNKNOWN_literal'
                     ELSE 'Other'
                   END AS cohort
            FROM orphan
        )
        SELECT cohort,
               COALESCE(fund_strategy_at_filing, '<null>') AS strategy,
               COUNT(*)              AS row_count,
               SUM(market_value_usd) AS aum_usd
        FROM classed
        WHERE is_latest = TRUE
        GROUP BY cohort, strategy
        ORDER BY cohort, row_count DESC
        """,
    )

    # 3b. cohort-by-cik fan-out for S9digit cohort
    out["phase3_s9_top_ciks"] = fetch(
        con,
        ORPHAN_CTE
        + """
        SELECT fund_cik,
               COUNT(DISTINCT series_id) AS distinct_series,
               COUNT(*)                  AS row_count,
               SUM(market_value_usd)     AS aum_usd
        FROM orphan
        WHERE is_latest = TRUE
          AND regexp_matches(series_id, '^S[0-9]{9}$')
        GROUP BY fund_cik
        ORDER BY row_count DESC
        LIMIT 25
        """,
    )

    # 3c. near-name match: orphan fund_name vs fund_universe.fund_name
    # For each S9digit orphan series, see whether ANY fund_universe row exists
    # at the same CIK or near-name. This is a coarse rename/merge candidate test.
    out["phase3_s9_name_match_candidates"] = fetch(
        con,
        ORPHAN_CTE
        + """,
        s9 AS (
            SELECT DISTINCT series_id,
                            fund_cik,
                            lower(trim(fund_name)) AS norm_name,
                            ANY_VALUE(fund_name) AS fund_name
            FROM orphan
            WHERE is_latest = TRUE
              AND regexp_matches(series_id, '^S[0-9]{9}$')
            GROUP BY series_id, fund_cik, norm_name
        )
        SELECT
            COUNT(*) FILTER (WHERE same_cik_match) AS same_cik_in_fu,
            COUNT(*) FILTER (WHERE name_exact_match) AS name_exact_match_in_fu,
            COUNT(*) FILTER (WHERE NOT same_cik_match AND NOT name_exact_match) AS no_obvious_match,
            COUNT(*) AS total_s9_series
        FROM (
            SELECT s9.series_id,
                   EXISTS (SELECT 1 FROM fund_universe fu
                           WHERE fu.fund_cik = s9.fund_cik) AS same_cik_match,
                   EXISTS (SELECT 1 FROM fund_universe fu
                           WHERE lower(trim(fu.fund_name)) = s9.norm_name) AS name_exact_match
            FROM s9
        ) t
        """,
    )

    # 3d. spot checks — four named cases
    spot_targets = [
        ("Tax Exempt Bond Fund of America", "%tax exempt bond fund of america%"),
        ("Blackstone Alternative Multi-Strategy Fund", "%blackstone alternative multi-strategy%"),
        ("VOYA INTERMEDIATE BOND FUND", "%voya intermediate bond fund%"),
        ("Calamos Global Total Return Fund", "%calamos global total return%"),
    ]
    spot = {}
    for label, like in spot_targets:
        spot[label] = {
            "orphan_rows": fetch(
                con,
                """
                SELECT fh.series_id,
                       fh.fund_name,
                       fh.fund_cik,
                       MIN(fh.report_month) AS first_seen,
                       MAX(fh.report_month) AS last_seen,
                       COUNT(*)             AS rows_latest,
                       SUM(fh.market_value_usd) AS aum_usd
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu USING (series_id)
                WHERE fu.series_id IS NULL
                  AND fh.is_latest = TRUE
                  AND lower(fh.fund_name) LIKE ?
                GROUP BY fh.series_id, fh.fund_name, fh.fund_cik
                ORDER BY rows_latest DESC
                LIMIT 5
                """,
                [like],
            ),
            "fund_universe_matches": fetch(
                con,
                """
                SELECT series_id, fund_name, fund_cik, fund_strategy
                FROM fund_universe
                WHERE lower(fund_name) LIKE ?
                LIMIT 10
                """,
                [like],
            ),
        }
    out["phase3_spot_checks"] = spot

    # ---- Phase 4 inputs: per-cohort row × strategy snapshot for default
    out["phase4_strategy_snapshot_majority_by_cohort"] = fetch(
        con,
        ORPHAN_CTE
        + """,
        classed AS (
            SELECT *,
                   CASE
                     WHEN series_id LIKE 'SYN_%'                   THEN 'SYN_prefix'
                     WHEN regexp_matches(series_id, '^S[0-9]{9}$') THEN 'S9digit'
                     WHEN series_id = 'UNKNOWN'                    THEN 'UNKNOWN_literal'
                     ELSE 'Other'
                   END AS cohort
            FROM orphan
        )
        SELECT cohort,
               COALESCE(fund_strategy_at_filing, '<null>') AS strategy,
               COUNT(*) AS row_count
        FROM classed
        WHERE is_latest = TRUE
        GROUP BY cohort, strategy
        ORDER BY cohort, row_count DESC
        """,
    )

    con.close()

    def default(o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)

    print(json.dumps(out, default=default, indent=2))


if __name__ == "__main__":
    main()
