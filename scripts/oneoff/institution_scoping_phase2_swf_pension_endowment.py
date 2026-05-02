"""Phase 2.4 — SWF / pension / endowment keep-separate confirmation.

READ-ONLY. Emits a markdown fragment to stdout.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"
TYPES = ["SWF", "pension_insurance", "endowment_foundation"]


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("## Phase 2.4 — SWF / pension_insurance / endowment_foundation\n")

    for t in TYPES:
        df_tot = con.execute(
            """
            SELECT
              COUNT(DISTINCT cik) AS ciks,
              COUNT(*) AS rows,
              ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
            FROM holdings_v2 WHERE is_latest = TRUE AND manager_type = ?
            """,
            [t],
        ).fetchdf()
        print(f"### `{t}`\n")
        print(df_tot.to_markdown(index=False))
        print()

        df_top = con.execute(
            """
            SELECT manager_name, cik,
                   ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
            FROM holdings_v2
            WHERE is_latest = TRUE AND manager_type = ?
            GROUP BY 1, 2 ORDER BY aum_b DESC NULLS LAST LIMIT 25
            """,
            [t],
        ).fetchdf()
        print(f"**Top 25 `{t}` firms by AUM:**\n")
        print(df_top.to_markdown(index=False))
        print()

    con.close()


if __name__ == "__main__":
    main()
