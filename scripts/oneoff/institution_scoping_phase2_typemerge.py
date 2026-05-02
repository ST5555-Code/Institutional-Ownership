"""Phase 2 type-merge audit: PE+VC, WM+FO, HF+multi_strategy.

READ-ONLY. No writes. Emits a markdown fragment to stdout.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"
PAIRS = [
    ("private_equity", "venture_capital"),
    ("wealth_management", "family_office"),
    ("hedge_fund", "multi_strategy"),
]


def section(title: str) -> None:
    print(f"\n### {title}\n")


def per_type_summary(con: duckdb.DuckDBPyConnection, mt: str) -> None:
    df = con.execute(
        """
        SELECT
          COUNT(DISTINCT cik) AS ciks,
          COUNT(*) AS rows,
          ROUND(SUM(market_value_usd) / 1e9, 2) AS aum_b
        FROM holdings_v2
        WHERE is_latest = TRUE AND manager_type = ?
        """,
        [mt],
    ).fetchdf()
    print(f"**`{mt}` totals (holdings_v2, is_latest=TRUE):**\n")
    print(df.to_markdown(index=False))
    print()


def top10_firms(con: duckdb.DuckDBPyConnection, mt: str) -> None:
    df = con.execute(
        """
        SELECT
          manager_name,
          cik,
          ROUND(SUM(market_value_usd) / 1e9, 2) AS aum_b,
          COUNT(*) AS rows
        FROM holdings_v2
        WHERE is_latest = TRUE AND manager_type = ?
        GROUP BY 1, 2
        ORDER BY aum_b DESC NULLS LAST
        LIMIT 10
        """,
        [mt],
    ).fetchdf()
    print(f"**Top 10 `{mt}` firms by AUM:**\n")
    print(df.to_markdown(index=False))
    print()


def edge_cases(con: duckdb.DuckDBPyConnection, mt_a: str, mt_b: str) -> None:
    """Surface CIKs where holdings_v2.manager_type and managers.strategy_type
    suggest the firm could plausibly land in either category."""
    df = con.execute(
        f"""
        WITH h AS (
          SELECT DISTINCT cik, manager_type, manager_name
          FROM holdings_v2
          WHERE is_latest = TRUE AND manager_type IN ('{mt_a}', '{mt_b}')
        ),
        agg AS (
          SELECT cik, MAX(manager_name) AS manager_name, MAX(manager_type) AS h_mt
          FROM h GROUP BY cik
        )
        SELECT
          a.cik,
          a.manager_name,
          a.h_mt,
          m.strategy_type AS m_st,
          ROUND((SELECT SUM(market_value_usd)/1e9 FROM holdings_v2
                 WHERE is_latest=TRUE AND cik = a.cik), 2) AS aum_b
        FROM agg a
        LEFT JOIN managers m USING (cik)
        WHERE
          (a.h_mt = '{mt_a}' AND m.strategy_type = '{mt_b}')
          OR (a.h_mt = '{mt_b}' AND m.strategy_type = '{mt_a}')
          OR (a.h_mt = '{mt_a}' AND lower(a.manager_name) LIKE '%{mt_b.replace("_", " ")}%')
          OR (a.h_mt = '{mt_b}' AND lower(a.manager_name) LIKE '%{mt_a.replace("_", " ")}%')
        ORDER BY aum_b DESC NULLS LAST
        LIMIT 25
        """
    ).fetchdf()
    label = f"{mt_a} vs {mt_b}"
    print(f"**Debatable / hybrid cases — {label} (sample 25 by AUM):**\n")
    if df.empty:
        print("_No edge cases surfaced via cross-tab heuristic._\n")
    else:
        print(df.to_markdown(index=False))
        print()


def name_pattern_hybrid(con: duckdb.DuckDBPyConnection, mt: str, patterns: list[str]) -> None:
    like_clauses = " OR ".join([f"lower(manager_name) LIKE '%{p}%'" for p in patterns])
    df = con.execute(
        f"""
        SELECT manager_name, cik,
               ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
        FROM holdings_v2
        WHERE is_latest = TRUE
          AND manager_type = '{mt}'
          AND ({like_clauses})
        GROUP BY 1, 2
        ORDER BY aum_b DESC NULLS LAST
        LIMIT 15
        """
    ).fetchdf()
    print(f"**`{mt}` rows where name matches `{patterns}` (potential hybrid):**\n")
    if df.empty:
        print("_None._\n")
    else:
        print(df.to_markdown(index=False))
        print()


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("## Phase 2.1 — Pre-decided merge audit\n")

    for mt_a, mt_b in PAIRS:
        section(f"Pair: `{mt_a}` + `{mt_b}`")
        per_type_summary(con, mt_a)
        per_type_summary(con, mt_b)

        # combined
        df_combined = con.execute(
            """
            SELECT
              COUNT(DISTINCT cik) AS ciks,
              COUNT(*) AS rows,
              ROUND(SUM(market_value_usd) / 1e9, 2) AS aum_b
            FROM holdings_v2
            WHERE is_latest = TRUE AND manager_type IN (?, ?)
            """,
            [mt_a, mt_b],
        ).fetchdf()
        print(f"**Combined `{mt_a}+{mt_b}`:**\n")
        print(df_combined.to_markdown(index=False))
        print()

        top10_firms(con, mt_a)
        top10_firms(con, mt_b)
        edge_cases(con, mt_a, mt_b)

    # additional name-pattern hybrid scans
    section("Hybrid-name scans (growth equity / family office crossover)")
    name_pattern_hybrid(con, "private_equity", ["growth", "venture", "ventures"])
    name_pattern_hybrid(con, "venture_capital", ["growth", "private", "equity"])
    name_pattern_hybrid(con, "wealth_management", ["family", "office", "trust"])
    name_pattern_hybrid(con, "family_office", ["wealth", "advisor"])
    name_pattern_hybrid(con, "hedge_fund", ["multi-strategy", "multi strategy", "multistrategy"])
    name_pattern_hybrid(con, "multi_strategy", ["hedge"])

    con.close()


if __name__ == "__main__":
    main()
