"""Phase 1 of fund-cleanup-batch: canonical-value coverage audit (read-only).

Runs queries 1a–1h against prod data/13f.duckdb and emits results to stdout.
Schema notes (post-PR-4):
  * fund_universe.fund_strategy is the sole canonical fund-level column
    (fund_category and is_actively_managed dropped in PR-3).
  * fund_holdings_v2.fund_strategy was renamed to fund_strategy_at_filing in PR-4.
  * Canonical values: active, balanced, multi_asset (active set);
    passive, bond_or_other, excluded, final_filing (passive set).
"""

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
        parent_repo = Path(*parts[: idx])
        candidate = parent_repo / "data" / "13f.duckdb"
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

    section("1a. NULL fund_strategy in fund_universe (expected 0)")
    show(con, "SELECT COUNT(*) AS null_count FROM fund_universe WHERE fund_strategy IS NULL;")

    section("1b. Orphan series in fund_holdings_v2 (no fund_universe match)")
    show(
        con,
        """
        SELECT COUNT(*) AS orphan_holdings_rows,
               COUNT(DISTINCT fh.series_id) AS orphan_series_count
        FROM fund_holdings_v2 fh
        LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
        WHERE fu.series_id IS NULL;
        """,
    )
    show(
        con,
        """
        SELECT fh.series_id, MAX(fh.fund_name) AS sample_fund_name, COUNT(*) AS rows
        FROM fund_holdings_v2 fh
        LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
        WHERE fu.series_id IS NULL
        GROUP BY fh.series_id
        ORDER BY rows DESC
        LIMIT 20;
        """,
        label="top 20 orphan series",
    )

    section("1c. UNKNOWN orphan rows by fund_strategy_at_filing")
    show(
        con,
        """
        SELECT fund_strategy_at_filing, COUNT(*) AS rows
        FROM fund_holdings_v2
        WHERE series_id = 'UNKNOWN'
        GROUP BY fund_strategy_at_filing
        ORDER BY rows DESC;
        """,
    )

    section("1d. SYN funds — canonical vs holdings drift (latest only)")
    show(
        con,
        """
        SELECT COUNT(*) AS syn_latest_holding_rows,
               COUNT(CASE WHEN fu.fund_strategy != fh.fund_strategy_at_filing THEN 1 END) AS disagreement_rows,
               COUNT(DISTINCT CASE WHEN fu.fund_strategy != fh.fund_strategy_at_filing THEN fu.series_id END) AS disagreement_series
        FROM fund_universe fu
        JOIN fund_holdings_v2 fh ON fu.series_id = fh.series_id
        WHERE fu.series_id LIKE 'SYN_%'
          AND fh.is_latest = TRUE;
        """,
    )
    show(
        con,
        """
        SELECT fu.series_id, fu.fund_name,
               fu.fund_strategy AS canonical,
               fh.fund_strategy_at_filing AS snapshot,
               COUNT(*) AS latest_rows
        FROM fund_universe fu
        JOIN fund_holdings_v2 fh ON fu.series_id = fh.series_id
        WHERE fu.series_id LIKE 'SYN_%'
          AND fh.is_latest = TRUE
          AND fu.fund_strategy != fh.fund_strategy_at_filing
        GROUP BY fu.series_id, fu.fund_name, fu.fund_strategy, fh.fund_strategy_at_filing
        ORDER BY fu.fund_name;
        """,
        label="SYN drifters detail",
    )

    section("1e. 12 BlackRock muni trusts — final_filing status")
    show(
        con,
        """
        SELECT fu.series_id, fu.fund_name, fu.fund_strategy,
               fu.total_net_assets, MAX(fh.quarter) AS latest_quarter
        FROM fund_universe fu
        LEFT JOIN fund_holdings_v2 fh ON fu.series_id = fh.series_id
        WHERE fu.fund_name LIKE '%BlackRock%'
          AND fu.fund_strategy = 'final_filing'
        GROUP BY fu.series_id, fu.fund_name, fu.fund_strategy, fu.total_net_assets
        ORDER BY fu.fund_name;
        """,
    )

    section("1f. ProShares short / inverse / bear funds")
    show(
        con,
        """
        SELECT fu.series_id, fu.fund_name, fu.fund_strategy, fu.total_net_assets
        FROM fund_universe fu
        WHERE fu.fund_name LIKE '%ProShares%'
          AND (fu.fund_name LIKE '%Short%'
               OR fu.fund_name LIKE '%Inverse%'
               OR fu.fund_name LIKE '%Bear%')
        ORDER BY fu.total_net_assets DESC NULLS LAST;
        """,
    )

    section("1g. Holdings drift — canonical vs snapshot")
    show(
        con,
        """
        SELECT
          COUNT(*) AS total_rows,
          COUNT(CASE WHEN fu.fund_strategy != fh.fund_strategy_at_filing THEN 1 END) AS divergent_rows,
          COUNT(CASE WHEN fu.fund_strategy != fh.fund_strategy_at_filing
                      AND fh.is_latest = TRUE THEN 1 END) AS divergent_latest_only
        FROM fund_holdings_v2 fh
        JOIN fund_universe fu ON fh.series_id = fu.series_id;
        """,
    )

    section("1h. cross.py 3-way CASE branch coverage on latest holdings")
    show(
        con,
        """
        SELECT
          COUNT(*) AS total_latest_holdings,
          COUNT(CASE WHEN fu.fund_strategy IS NULL THEN 1 END) AS null_arm_rows,
          COUNT(CASE WHEN fu.fund_strategy IN ('active', 'balanced', 'multi_asset') THEN 1 END) AS active_arm_rows,
          COUNT(CASE WHEN fu.fund_strategy IN ('passive', 'bond_or_other', 'excluded', 'final_filing') THEN 1 END) AS passive_arm_rows
        FROM fund_holdings_v2 fh
        LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
        WHERE fh.is_latest = TRUE;
        """,
    )

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
