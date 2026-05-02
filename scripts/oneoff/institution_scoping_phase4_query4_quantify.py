"""Phase 4 quantification: query4 silent-drop bug.

READ-ONLY. Quantifies how many holdings_v2 rows / AUM are silently
dropped to "Other/Unknown" by the buggy CASE expression in
scripts/queries/register.py:746-750.

Bug pattern (current):
    CASE
        WHEN entity_type = 'passive' THEN 'Passive (Index)'
        WHEN entity_type = 'activist' THEN 'Activist'
        WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
        ELSE 'Other/Unknown'
    END

Issue: rows where manager_type is one of the active values BUT
entity_type is set to something OTHER than 'passive'/'activist' (e.g.
entity_type='institution', entity_type='mixed', etc.) are correctly
caught by the third branch — but rows where entity_type holds an
"active-equivalent" value while manager_type is NULL or non-active fall
to "Other/Unknown" and are invisible in the chart. Conversely, a row
with manager_type='hedge_fund' AND entity_type='passive' is bucketed as
Passive (Index), losing the active signal.

This helper builds slice tables that show:
  1. row + AUM totals across the four query4 categories at the LQ
     ticker-agnostic level (proxy for "what query4 would emit summed
     over all tickers", giving a worst-case envelope)
  2. the specific silent-drop slice — rows that COULD have a signal but
     fall to Other/Unknown
  3. the disagreement slice — rows where manager_type and entity_type
     point to different buckets

Run:
    python3 scripts/oneoff/institution_scoping_phase4_query4_quantify.py
"""

from __future__ import annotations

import os
import duckdb

DB = os.environ.get("DB_PATH", "data/13f.duckdb")


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    # Find latest quarter present (avoid hardcoding LQ).
    lq = con.execute(
        "SELECT quarter FROM holdings_v2 WHERE is_latest = TRUE "
        "GROUP BY 1 ORDER BY 1 DESC LIMIT 1"
    ).fetchone()[0]
    print(f"Latest quarter (LQ): {lq}")
    print("=" * 78)

    # ---------- 1. Buggy CASE breakdown across LQ (all tickers) ----------
    print("\n[1] BUGGY CASE breakdown (current production query4 expression)")
    print("    Aggregated across all tickers at LQ for envelope visibility.")
    df_buggy = con.execute(
        """
        SELECT
            CASE
                WHEN entity_type = 'passive' THEN 'Passive (Index)'
                WHEN entity_type = 'activist' THEN 'Activist'
                WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
                ELSE 'Other/Unknown'
            END AS category,
            COUNT(*)                    AS n_rows,
            SUM(market_value_usd)/1e9   AS aum_billion
        FROM holdings_v2
        WHERE is_latest = TRUE AND quarter = ?
        GROUP BY category
        ORDER BY n_rows DESC
        """,
        [lq],
    ).fetchdf()
    print(df_buggy.to_string(index=False))
    total_rows = int(df_buggy["n_rows"].sum())
    total_aum = float(df_buggy["aum_billion"].sum())
    print(f"    Total: {total_rows:,} rows / ${total_aum:,.1f}B AUM")

    other_row = df_buggy[df_buggy["category"] == "Other/Unknown"]
    if not other_row.empty:
        ou_rows = int(other_row.iloc[0]["n_rows"])
        ou_aum = float(other_row.iloc[0]["aum_billion"])
        print(
            f"    Other/Unknown bucket: {ou_rows:,} rows ({ou_rows/total_rows*100:.1f}%) "
            f"/ ${ou_aum:,.1f}B ({ou_aum/total_aum*100:.1f}% of AUM)"
        )

    # ---------- 2. Disagreement: rows where the two columns point to different buckets ----------
    print("\n[2] DISAGREEMENT MATRIX — manager_type x entity_type at LQ")
    print("    (where both NON-NULL)")
    df_matrix = con.execute(
        """
        SELECT
            COALESCE(manager_type,'<NULL>') AS manager_type,
            COALESCE(entity_type,'<NULL>')  AS entity_type,
            COUNT(*)                        AS n_rows,
            SUM(market_value_usd)/1e9       AS aum_billion
        FROM holdings_v2
        WHERE is_latest = TRUE AND quarter = ?
        GROUP BY 1,2
        ORDER BY n_rows DESC
        """,
        [lq],
    ).fetchdf()
    print(df_matrix.to_string(index=False))

    # ---------- 3. Silent drops — rows that have a SIGNAL but fall to Other/Unknown ----------
    # A row is silently dropped if:
    #   - entity_type NOT IN ('passive','activist')   (first two branches don't fire)
    #   - manager_type NOT IN ('active','hedge_fund','quantitative')   (third branch doesn't fire)
    #   - BUT manager_type or entity_type carries some classification signal
    #     (i.e. one of them is non-NULL and not equal to 'unknown')
    print("\n[3] SILENT-DROP SLICE — rows hitting 'Other/Unknown' that DO carry a signal")
    df_drops = con.execute(
        """
        WITH bucket AS (
            SELECT
                manager_type,
                entity_type,
                market_value_usd,
                CASE
                    WHEN entity_type = 'passive' THEN 'Passive (Index)'
                    WHEN entity_type = 'activist' THEN 'Activist'
                    WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
                    ELSE 'Other/Unknown'
                END AS category
            FROM holdings_v2
            WHERE is_latest = TRUE AND quarter = ?
        )
        SELECT
            COALESCE(manager_type,'<NULL>') AS manager_type,
            COALESCE(entity_type,'<NULL>')  AS entity_type,
            COUNT(*)                        AS n_rows,
            SUM(market_value_usd)/1e9       AS aum_billion
        FROM bucket
        WHERE category = 'Other/Unknown'
          AND ( (manager_type IS NOT NULL AND manager_type <> 'unknown')
             OR (entity_type IS NOT NULL  AND entity_type  <> 'unknown') )
        GROUP BY 1,2
        ORDER BY n_rows DESC
        """,
        [lq],
    ).fetchdf()
    print(df_drops.to_string(index=False))
    silent_rows = int(df_drops["n_rows"].sum()) if not df_drops.empty else 0
    silent_aum = float(df_drops["aum_billion"].sum()) if not df_drops.empty else 0.0
    print(
        f"    SILENT DROP TOTAL: {silent_rows:,} rows / ${silent_aum:,.1f}B "
        f"(of total {total_rows:,} rows / ${total_aum:,.1f}B)"
    )
    if total_rows:
        print(
            f"    Silent drops as share of all LQ rows: {silent_rows/total_rows*100:.2f}% "
            f"of rows / {silent_aum/total_aum*100:.2f}% of AUM"
        )

    # ---------- 4. Disagreement count specifically (manager_type vs entity_type) ----------
    print("\n[4] DISAGREEMENT-ONLY SUBSET — both columns non-null AND map to different buckets")
    print(
        "    (manager_type bucket = active/passive/activist family; "
        "entity_type bucket = same family from entity_type)"
    )
    df_disagree = con.execute(
        """
        WITH norm AS (
            SELECT
                manager_type,
                entity_type,
                market_value_usd,
                CASE
                    WHEN manager_type = 'passive' THEN 'passive_family'
                    WHEN manager_type = 'activist' THEN 'activist_family'
                    WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'active_family'
                    ELSE 'other_family'
                END AS m_bucket,
                CASE
                    WHEN entity_type = 'passive' THEN 'passive_family'
                    WHEN entity_type = 'activist' THEN 'activist_family'
                    WHEN entity_type IN ('active','hedge_fund','quantitative') THEN 'active_family'
                    ELSE 'other_family'
                END AS e_bucket
            FROM holdings_v2
            WHERE is_latest = TRUE AND quarter = ?
              AND manager_type IS NOT NULL AND entity_type IS NOT NULL
        )
        SELECT
            m_bucket, e_bucket,
            COUNT(*)                        AS n_rows,
            SUM(market_value_usd)/1e9       AS aum_billion
        FROM norm
        WHERE m_bucket <> e_bucket
        GROUP BY 1,2
        ORDER BY n_rows DESC
        """,
        [lq],
    ).fetchdf()
    if df_disagree.empty:
        print("    No disagreements found.")
    else:
        print(df_disagree.to_string(index=False))
        d_rows = int(df_disagree["n_rows"].sum())
        d_aum = float(df_disagree["aum_billion"].sum())
        print(f"    DISAGREEMENT TOTAL: {d_rows:,} rows / ${d_aum:,.1f}B")
        print(
            f"    Disagreements as share of LQ rows: {d_rows/total_rows*100:.2f}% rows / "
            f"{d_aum/total_aum*100:.2f}% AUM"
        )

    # ---------- 5. PER-TICKER worst case — which tickers see the largest Other/Unknown share ----------
    print("\n[5] PER-TICKER worst case — top 15 tickers by Other/Unknown rows")
    df_tk = con.execute(
        """
        WITH bucket AS (
            SELECT
                ticker,
                market_value_usd,
                CASE
                    WHEN entity_type = 'passive' THEN 'Passive (Index)'
                    WHEN entity_type = 'activist' THEN 'Activist'
                    WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
                    ELSE 'Other/Unknown'
                END AS category
            FROM holdings_v2
            WHERE is_latest = TRUE AND quarter = ?
              AND ticker IS NOT NULL
        )
        SELECT
            ticker,
            COUNT(*) FILTER (WHERE category='Other/Unknown')           AS ou_rows,
            COUNT(*)                                                   AS total_rows,
            SUM(market_value_usd) FILTER (WHERE category='Other/Unknown')/1e9
                                                                       AS ou_aum_b,
            SUM(market_value_usd)/1e9                                  AS total_aum_b
        FROM bucket
        GROUP BY ticker
        HAVING ou_rows > 0
        ORDER BY ou_rows DESC
        LIMIT 15
        """,
        [lq],
    ).fetchdf()
    print(df_tk.to_string(index=False))


if __name__ == "__main__":
    main()
