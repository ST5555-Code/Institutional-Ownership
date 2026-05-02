"""Phase 2 — market_maker backfill candidate scan.

Find CIKs in holdings_v2 / managers where manager_type/strategy_type is NULL
or 'unknown'/'mixed'/'active' but the manager_name matches market-making firm
patterns.

READ-ONLY. Emits a markdown fragment to stdout.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"

# Names + tokens characteristic of market makers / liquidity providers.
NAME_LIKE_PATTERNS = [
    "citadel securities",
    "virtu",
    "susquehanna",
    "jane street",
    "imc ",
    "imc-",
    "imc trading",
    "gts ",
    "gts capital",
    "gts securities",
    "hudson river",
    "two sigma securities",
    "flow traders",
    "drw ",
    "drw holdings",
    "drw securities",
    "tower research",
    "jump trading",
    "optiver",
    "akuna",
    "wolverine trading",
    "wolverine securities",
    "belvedere trading",
    "geneva trading",
    "five rings",
    "old mission",
    "xr trading",
    "xtx",
    "headlands",
    "peak6",
    "global electronic trading",
    "get co",
    "getco",
    "knight capital",
    "nyse arca",
    "market making",
    "market maker",
]


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("## Phase 2.2 — market_maker backfill scan\n")

    like_clauses_h = " OR ".join(
        [f"lower(h.manager_name) LIKE '%{p}%'" for p in NAME_LIKE_PATTERNS]
    )

    # universe: latest holdings AUM-weighted, looking for non-MM-typed
    candidate_query = f"""
        SELECT
          h.cik,
          MAX(h.manager_name) AS manager_name,
          MAX(h.manager_type) AS h_manager_type,
          MAX(m.strategy_type) AS m_strategy_type,
          ROUND(SUM(h.market_value_usd) / 1e9, 3) AS aum_b,
          COUNT(*) AS rows
        FROM holdings_v2 h
        LEFT JOIN managers m USING (cik)
        WHERE h.is_latest = TRUE
          AND ({like_clauses_h})
        GROUP BY h.cik
        ORDER BY aum_b DESC NULLS LAST
    """
    df = con.execute(candidate_query).fetchdf()
    print(f"**Candidate firms matching MM name patterns: {len(df):,} CIKs.**\n")
    print(f"**Candidate AUM total: ${df['aum_b'].sum():,.2f}B**\n")

    print("**Top 50 candidates by AUM:**\n")
    print(df.head(50).to_markdown(index=False))
    print()

    # Of those, how many are NOT already classified as market_maker anywhere?
    # entity_classification_history scan
    like_clauses = " OR ".join(
        [f"lower(manager_name) LIKE '%{p}%'" for p in NAME_LIKE_PATTERNS]
    )
    eh_df = con.execute(
        f"""
        WITH cand AS (
          SELECT DISTINCT cik, manager_name
          FROM holdings_v2
          WHERE is_latest = TRUE AND ({like_clauses})
        )
        SELECT
          c.cik, c.manager_name,
          ec.classification AS current_eh_classification
        FROM cand c
        LEFT JOIN entity_identifiers ei
          ON ei.identifier_type = 'cik' AND ei.identifier_value = c.cik
        LEFT JOIN entity_current ec USING (entity_id)
        ORDER BY c.manager_name
        LIMIT 100
        """
    ).fetchdf()
    print("**Candidates × entity_current classification (sample 100):**\n")
    print(eh_df.to_markdown(index=False))
    print()

    # Sanity: how many already classified market_maker in entity_current?
    mm_existing = con.execute(
        "SELECT COUNT(*) FROM entity_current WHERE classification = 'market_maker'"
    ).fetchone()[0]
    print(f"_Currently classified as `market_maker` in `entity_current`: {mm_existing}._\n")

    con.close()


if __name__ == "__main__":
    main()
