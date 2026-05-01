"""Phase 4a + 4b of fund-cleanup-batch: audit UNKNOWN orphans + 8 named CEFs."""

from __future__ import annotations

from pathlib import Path
import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_db_path() -> Path:
    primary = REPO_ROOT / "data" / "13f.duckdb"
    if primary.exists():
        return primary
    parts = REPO_ROOT.parts
    if ".claude" in parts:
        idx = parts.index(".claude")
        parent = Path(*parts[: idx])
        candidate = parent / "data" / "13f.duckdb"
        if candidate.exists():
            return candidate
    return primary


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def show(con, sql: str, label: str | None = None) -> list[tuple]:
    if label:
        print(f"--- {label}")
    rows = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
    print("  cols:", cols)
    for r in rows:
        print(" ", r)
    return rows


def main() -> int:
    db = _resolve_db_path()
    print(f"DB: {db}")
    con = duckdb.connect(str(db), read_only=True)

    section("4a. UNKNOWN orphan rows by snapshot strategy")
    show(
        con,
        """
        SELECT fund_strategy_at_filing, COUNT(*) AS rows,
               COUNT(DISTINCT fund_name) AS distinct_fund_names
        FROM fund_holdings_v2
        WHERE series_id = 'UNKNOWN'
        GROUP BY fund_strategy_at_filing;
        """,
    )

    section("4a. UNKNOWN orphan rows by fund_name")
    show(
        con,
        """
        SELECT fund_name, COUNT(*) AS rows,
               MIN(quarter) AS first_quarter,
               MAX(quarter) AS last_quarter,
               COUNT(DISTINCT quarter) AS n_quarters
        FROM fund_holdings_v2
        WHERE series_id = 'UNKNOWN'
        GROUP BY fund_name
        ORDER BY rows DESC;
        """,
    )

    section("4b. 8 named CEFs in fund_universe — current classification")
    show(
        con,
        """
        SELECT fu.series_id, fu.fund_name, fu.fund_strategy, fu.total_net_assets
        FROM fund_universe fu
        WHERE fu.fund_name LIKE '%Calamos Global Total Return%'
           OR fu.fund_name LIKE '%Saba Capital Income%'
           OR fu.fund_name LIKE '%ASA Gold%'
           OR fu.fund_name LIKE '%Asa Gold%'
           OR fu.fund_name LIKE '%Eaton Vance Tax-Advantaged%'
           OR fu.fund_name LIKE '%NXG Cushing%'
           OR fu.fund_name LIKE '%AMG Pantheon Credit%'
           OR fu.fund_name LIKE '%AIP Alternative Lending%'
        ORDER BY fu.fund_name;
        """,
    )

    section("4c. Pre-execution exact-match check on whitelist")
    show(
        con,
        """
        SELECT series_id, fund_name, fund_strategy, total_net_assets
        FROM fund_universe
        WHERE fund_name IN (
            'AMG Pantheon Credit Solutions Fund',
            'AIP Alternative Lending Fund P'
        );
        """,
    )

    section("4c. Cascading rows in fund_holdings_v2 if reclassification proceeds")
    show(
        con,
        """
        SELECT fu.series_id, fu.fund_name, fu.fund_strategy AS canonical,
               fh.fund_strategy_at_filing AS snapshot, COUNT(*) AS rows
        FROM fund_universe fu
        JOIN fund_holdings_v2 fh ON fu.series_id = fh.series_id
        WHERE fu.fund_name IN (
            'AMG Pantheon Credit Solutions Fund',
            'AIP Alternative Lending Fund P'
        )
        GROUP BY fu.series_id, fu.fund_name, fu.fund_strategy, fh.fund_strategy_at_filing
        ORDER BY fu.fund_name, fh.fund_strategy_at_filing;
        """,
    )

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
