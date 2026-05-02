"""Phase 2.5 — mixed / unknown bucket characterization.

READ-ONLY. Emits a markdown fragment to stdout.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("## Phase 2.5 — `mixed` and `unknown` buckets\n")

    # holdings_v2: manager_type
    print("### `holdings_v2.manager_type IN ('mixed', NULL, 'unknown')`\n")
    df = con.execute(
        """
        SELECT
          COALESCE(manager_type, '<NULL>') AS manager_type,
          COUNT(DISTINCT cik) AS ciks,
          COUNT(*) AS rows,
          ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
        FROM holdings_v2 WHERE is_latest = TRUE
          AND (manager_type = 'mixed' OR manager_type IS NULL OR manager_type = 'unknown')
        GROUP BY 1
        """
    ).fetchdf()
    print(df.to_markdown(index=False))
    print()

    # entity_type
    print("### `holdings_v2.entity_type IN ('mixed', NULL, 'unknown')`\n")
    df_et = con.execute(
        """
        SELECT
          COALESCE(entity_type, '<NULL>') AS entity_type,
          COUNT(DISTINCT cik) AS ciks,
          COUNT(*) AS rows,
          ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
        FROM holdings_v2 WHERE is_latest = TRUE
          AND (entity_type = 'mixed' OR entity_type IS NULL OR entity_type = 'unknown')
        GROUP BY 1
        """
    ).fetchdf()
    print(df_et.to_markdown(index=False))
    print()

    # samples for each cohort
    for label, where in [
        ("manager_type='mixed'", "manager_type = 'mixed'"),
        ("manager_type IS NULL", "manager_type IS NULL"),
        ("entity_type='mixed'", "entity_type = 'mixed'"),
        ("entity_type IS NULL", "entity_type IS NULL"),
    ]:
        print(f"**Sample 25 by AUM — `{label}`:**\n")
        df_s = con.execute(
            f"""
            SELECT manager_name, cik, manager_type, entity_type,
                   ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
            FROM holdings_v2
            WHERE is_latest = TRUE AND {where}
            GROUP BY 1, 2, 3, 4
            ORDER BY aum_b DESC NULLS LAST
            LIMIT 25
            """
        ).fetchdf()
        print(df_s.to_markdown(index=False))
        print()

    # entity_classification_history 'unknown'
    print("### `entity_classification_history.classification = 'unknown'` (current open rows)\n")
    df_eh = con.execute(
        """
        SELECT COUNT(*) AS rows
        FROM entity_classification_history
        WHERE classification = 'unknown' AND valid_to = DATE '9999-12-31'
        """
    ).fetchdf()
    print(df_eh.to_markdown(index=False))
    print()

    con.close()


if __name__ == "__main__":
    main()
