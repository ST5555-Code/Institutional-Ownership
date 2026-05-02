"""Phase 3 — family_office and multi_strategy migration prerequisites.

READ-ONLY. Emits a markdown fragment to stdout.

Goals:
1. Map current population of family_office / multi_strategy in holdings_v2 and
   managers tables.
2. Cross-check entity_classification_history — how many of these CIKs already
   have an entity_id and a classification row?
3. Confirm classification value space accepts new values.
4. Document migration script SHAPE as pseudo-SQL (NOT YET EXECUTED).
5. Sequencing graph.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"


def section(title: str) -> None:
    print(f"\n### {title}\n")


def map_manager_type(con, mt: str) -> None:
    print(f"**holdings_v2 `manager_type = '{mt}'`:**\n")
    df = con.execute(
        """
        SELECT
          COUNT(DISTINCT cik) AS ciks,
          COUNT(*) AS rows,
          ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
        FROM holdings_v2 WHERE is_latest = TRUE AND manager_type = ?
        """,
        [mt],
    ).fetchdf()
    print(df.to_markdown(index=False))
    print()

    print(f"**Sample 25 by AUM — `manager_type='{mt}'`:**\n")
    df_s = con.execute(
        """
        SELECT
          h.manager_name, h.cik,
          ROUND(SUM(h.market_value_usd)/1e9, 2) AS aum_b,
          MAX(m.strategy_type) AS m_strategy_type,
          MAX(m.parent_name) AS parent_name
        FROM holdings_v2 h
        LEFT JOIN managers m USING(cik)
        WHERE h.is_latest = TRUE AND h.manager_type = ?
        GROUP BY 1, 2 ORDER BY aum_b DESC NULLS LAST LIMIT 25
        """,
        [mt],
    ).fetchdf()
    print(df_s.to_markdown(index=False))
    print()


def map_strategy(con, st: str) -> None:
    print(f"**managers `strategy_type = '{st}'`:**\n")
    df = con.execute(
        "SELECT COUNT(*) AS ciks FROM managers WHERE strategy_type = ?", [st]
    ).fetchdf()
    print(df.to_markdown(index=False))
    print()


def cross_check_eh(con, mt: str) -> None:
    print(
        f"**Of CIKs with `manager_type='{mt}'` in holdings_v2 — what does `entity_classification_history` say?**\n"
    )
    df = con.execute(
        """
        WITH cand AS (
          SELECT DISTINCT cik
          FROM holdings_v2 WHERE is_latest = TRUE AND manager_type = ?
        ),
        ent AS (
          SELECT c.cik, ei.entity_id
          FROM cand c
          LEFT JOIN entity_identifiers ei
            ON ei.identifier_type = 'cik' AND ei.identifier_value = c.cik
        ),
        eh_open AS (
          SELECT entity_id, classification
          FROM entity_classification_history
          WHERE valid_to = DATE '9999-12-31'
        )
        SELECT
          COALESCE(eh.classification, '<NO_OPEN_ROW>') AS eh_classification,
          COUNT(DISTINCT ent.cik) AS ciks,
          COUNT(DISTINCT ent.entity_id) FILTER (WHERE ent.entity_id IS NOT NULL) AS with_entity_id,
          COUNT(DISTINCT ent.cik) FILTER (WHERE ent.entity_id IS NULL) AS no_entity_id
        FROM ent
        LEFT JOIN eh_open eh USING(entity_id)
        GROUP BY 1
        ORDER BY ciks DESC
        """,
        [mt],
    ).fetchdf()
    print(df.to_markdown(index=False))
    print()


def conflict_sample(con, mt: str) -> None:
    print(
        f"**Pre-existing conflicting open `entity_classification_history` rows for `{mt}` candidates (sample 25):**\n"
    )
    df = con.execute(
        """
        WITH cand AS (
          SELECT DISTINCT cik FROM holdings_v2
          WHERE is_latest = TRUE AND manager_type = ?
        ),
        ent AS (
          SELECT c.cik, ei.entity_id
          FROM cand c
          JOIN entity_identifiers ei
            ON ei.identifier_type = 'cik' AND ei.identifier_value = c.cik
        )
        SELECT
          ent.cik, ent.entity_id,
          eh.classification AS existing_classification,
          eh.source, eh.valid_from
        FROM ent
        JOIN entity_classification_history eh
          ON eh.entity_id = ent.entity_id AND eh.valid_to = DATE '9999-12-31'
        WHERE eh.classification <> ?
        LIMIT 25
        """,
        [mt, mt],
    ).fetchdf()
    if df.empty:
        print("_No conflicting rows._\n")
    else:
        print(df.to_markdown(index=False))
        print()


def hf_multistrategy_overlap(con) -> None:
    section("HF × multi_strategy CIK-level overlap")
    df = con.execute(
        """
        WITH h AS (
          SELECT DISTINCT cik, manager_type, manager_name
          FROM holdings_v2 WHERE is_latest = TRUE
            AND manager_type IN ('hedge_fund', 'multi_strategy')
        )
        SELECT manager_type, COUNT(DISTINCT cik) AS ciks
        FROM h GROUP BY 1
        """
    ).fetchdf()
    print(df.to_markdown(index=False))
    print()
    df_overlap = con.execute(
        """
        SELECT manager_name, cik, manager_type
        FROM (
          SELECT DISTINCT cik, manager_type, manager_name
          FROM holdings_v2 WHERE is_latest = TRUE AND manager_type = 'multi_strategy'
        ) ms
        ORDER BY manager_name
        """
    ).fetchdf()
    print("**All `multi_strategy` rows in holdings_v2:**\n")
    print(df_overlap.to_markdown(index=False))
    print()


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    print("## Phase 3 — migration prerequisites\n")

    section("3.1 `family_office` migration")
    map_manager_type(con, "family_office")
    map_strategy(con, "family_office")
    cross_check_eh(con, "family_office")
    conflict_sample(con, "family_office")

    section("3.2 `multi_strategy` migration")
    map_manager_type(con, "multi_strategy")
    map_strategy(con, "multi_strategy")
    cross_check_eh(con, "multi_strategy")
    conflict_sample(con, "multi_strategy")

    hf_multistrategy_overlap(con)

    # entity_classification_history value space confirmation
    section("3.3 `entity_classification_history.classification` value space")
    df_vals = con.execute(
        """
        SELECT classification, COUNT(*) AS rows
        FROM entity_classification_history
        GROUP BY 1 ORDER BY rows DESC
        """
    ).fetchdf()
    print(df_vals.to_markdown(index=False))
    print()
    has_fo = "family_office" in df_vals["classification"].astype(str).tolist()
    has_ms = "multi_strategy" in df_vals["classification"].astype(str).tolist()
    print(f"_Already contains `family_office`: **{has_fo}**._\n")
    print(f"_Already contains `multi_strategy`: **{has_ms}**._\n")

    con.close()


if __name__ == "__main__":
    main()
