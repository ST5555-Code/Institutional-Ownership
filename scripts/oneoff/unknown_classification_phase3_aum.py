"""Phase 3: AUM exposure for the 3,852 ECH unknown cohort.

Read-only.
  institution_aum: SUM(holdings_v2.market_value_usd) WHERE entity_id=e AND is_latest.
  fund_rollup_aum: SUM(fund_holdings_v2.market_value_usd) WHERE dm_rollup_entity_id=e AND is_latest.
"""
import duckdb
from pathlib import Path

DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
SENTINEL = "DATE '9999-12-31'"


def fmt_b(v: float) -> str:
    return f"${v / 1e9:>10,.2f}B"


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    print("PHASE 3 — AUM exposure (latest period only)\n")

    print("(a) totals across whole cohort:")
    inst_total = con.execute(
        f"""
        WITH cohort AS (
            SELECT entity_id FROM entity_classification_history
            WHERE classification='unknown' AND valid_to = {SENTINEL}
        )
        SELECT COALESCE(SUM(h.market_value_usd), 0)
        FROM holdings_v2 h
        JOIN cohort c ON c.entity_id = h.entity_id
        WHERE h.is_latest
        """
    ).fetchone()[0]
    fund_total = con.execute(
        f"""
        WITH cohort AS (
            SELECT entity_id FROM entity_classification_history
            WHERE classification='unknown' AND valid_to = {SENTINEL}
        )
        SELECT COALESCE(SUM(f.market_value_usd), 0)
        FROM fund_holdings_v2 f
        JOIN cohort c ON c.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest
        """
    ).fetchone()[0]
    print(f"  institution_aum (holdings_v2 direct):       {fmt_b(inst_total)}")
    print(f"  fund_rollup_aum (fund_holdings_v2 rollup):  {fmt_b(fund_total)}")
    print(f"  combined (likely some overlap):             {fmt_b(inst_total + fund_total)}\n")

    print("(b) per ECH-source bucket:")
    rows = con.execute(
        f"""
        WITH cohort AS (
            SELECT h.entity_id, COALESCE(h.source, '<NULL>') AS src
            FROM entity_classification_history h
            WHERE h.classification='unknown' AND h.valid_to = {SENTINEL}
        ),
        per_inst AS (
            SELECT c.src, COALESCE(SUM(h.market_value_usd), 0) AS inst_aum
            FROM cohort c
            LEFT JOIN holdings_v2 h ON h.entity_id = c.entity_id AND h.is_latest
            GROUP BY c.src
        ),
        per_fund AS (
            SELECT c.src, COALESCE(SUM(f.market_value_usd), 0) AS fund_aum
            FROM cohort c
            LEFT JOIN fund_holdings_v2 f ON f.dm_rollup_entity_id = c.entity_id AND f.is_latest
            GROUP BY c.src
        ),
        cnt AS (
            SELECT src, COUNT(*) AS n FROM cohort GROUP BY src
        )
        SELECT cnt.src, cnt.n, per_inst.inst_aum, per_fund.fund_aum
        FROM cnt
        LEFT JOIN per_inst USING (src)
        LEFT JOIN per_fund USING (src)
        ORDER BY cnt.n DESC
        """
    ).fetchall()
    print(f"  {'source':<22s}  {'count':>6s}  {'inst_aum':>14s}  {'fund_aum':>14s}")
    for src, n, ia, fa in rows:
        print(f"  {src:<22s}  {n:>6,}  {fmt_b(ia or 0):>14s}  {fmt_b(fa or 0):>14s}")

    print("\n(c) per entity_type bucket:")
    rows = con.execute(
        f"""
        WITH cohort AS (
            SELECT h.entity_id, COALESCE(e.entity_type, '<NULL>') AS et
            FROM entity_classification_history h
            JOIN entities e ON e.entity_id = h.entity_id
            WHERE h.classification='unknown' AND h.valid_to = {SENTINEL}
        )
        SELECT
            c.et,
            COUNT(*) AS n,
            COALESCE(SUM((SELECT SUM(h.market_value_usd) FROM holdings_v2 h
                          WHERE h.entity_id = c.entity_id AND h.is_latest)), 0) AS inst_aum,
            COALESCE(SUM((SELECT SUM(f.market_value_usd) FROM fund_holdings_v2 f
                          WHERE f.dm_rollup_entity_id = c.entity_id AND f.is_latest)), 0) AS fund_aum
        FROM cohort c
        GROUP BY c.et
        ORDER BY n DESC
        """
    ).fetchall()
    print(f"  {'entity_type':<14s}  {'count':>6s}  {'inst_aum':>14s}  {'fund_aum':>14s}")
    for et, n, ia, fa in rows:
        print(f"  {et:<14s}  {n:>6,}  {fmt_b(ia or 0):>14s}  {fmt_b(fa or 0):>14s}")

    # How many entities have ZERO AUM?
    print("\n(d) entities in cohort with ZERO AUM (no holdings + no fund-rollup):")
    zero = con.execute(
        f"""
        WITH cohort AS (
            SELECT entity_id FROM entity_classification_history
            WHERE classification='unknown' AND valid_to = {SENTINEL}
        )
        SELECT COUNT(*)
        FROM cohort c
        WHERE NOT EXISTS (SELECT 1 FROM holdings_v2 h
                          WHERE h.entity_id = c.entity_id AND h.is_latest)
          AND NOT EXISTS (SELECT 1 FROM fund_holdings_v2 f
                          WHERE f.dm_rollup_entity_id = c.entity_id AND f.is_latest)
        """
    ).fetchone()[0]
    print(f"  zero-AUM entities: {zero:,}  (Tier C residual candidates)")


if __name__ == "__main__":
    main()
