"""Phase 4c of fund-cleanup-batch: reclassify 2 whitelisted credit funds.

Whitelist (must match exactly 2 fund_universe rows; otherwise abort):
  - AMG Pantheon Credit Solutions Fund  (currently 'balanced')
  - AIP Alternative Lending Fund P     (currently 'active')

Both are reclassified to 'bond_or_other'. Cascades to fund_holdings_v2
.fund_strategy_at_filing for the same 2 series_ids.

Hard gates:
  * Pre-check returns exactly 2 rows in fund_universe (else abort).
  * UPDATE on fund_universe touches exactly 2 rows (else ROLLBACK + abort).

Run with --confirm to execute. Default is dry-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]

WHITELIST = (
    "AMG Pantheon Credit Solutions Fund",
    "AIP Alternative Lending Fund P",
)
TARGET = "bond_or_other"


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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", action="store_true", help="Execute (default dry-run).")
    args = p.parse_args()

    db = _resolve_db_path()
    print(f"DB: {db}")
    print(f"Mode: {'EXECUTE' if args.confirm else 'DRY-RUN'}")
    print(f"Whitelist (n={len(WHITELIST)}): {WHITELIST}")
    print(f"Target fund_strategy: {TARGET}")
    print()

    con = duckdb.connect(str(db), read_only=not args.confirm)

    # Pre-check
    rows = con.execute(
        """
        SELECT series_id, fund_name, fund_strategy
        FROM fund_universe
        WHERE fund_name IN (?, ?)
        ORDER BY fund_name;
        """,
        list(WHITELIST),
    ).fetchall()
    print(f"Pre-check returned {len(rows)} rows:")
    for r in rows:
        print(f"  {r}")
    print()

    if len(rows) != len(WHITELIST):
        print(f"ABORT: pre-check expected exactly {len(WHITELIST)} rows, got {len(rows)}.")
        return 2

    series_ids = [r[0] for r in rows]

    if not args.confirm:
        print("Dry-run complete. Re-run with --confirm to execute.")
        # Show what cascade would touch
        cascade = con.execute(
            f"""
            SELECT series_id, COUNT(*) AS rows
            FROM fund_holdings_v2
            WHERE series_id IN ({','.join(['?'] * len(series_ids))})
            GROUP BY series_id
            ORDER BY series_id;
            """,
            series_ids,
        ).fetchall()
        print("Cascade preview (fund_holdings_v2 rows):")
        for c in cascade:
            print(f"  {c}")
        return 0

    # Execute in a single transaction
    try:
        con.execute("BEGIN TRANSACTION;")

        # 1. fund_universe update
        con.execute(
            f"""
            UPDATE fund_universe
            SET fund_strategy = '{TARGET}'
            WHERE fund_name IN (?, ?);
            """,
            list(WHITELIST),
        )
        # Verify exactly 2 rows now have target strategy with whitelisted names
        verify = con.execute(
            """
            SELECT COUNT(*) FROM fund_universe
            WHERE fund_name IN (?, ?) AND fund_strategy = ?;
            """,
            [*WHITELIST, TARGET],
        ).fetchone()[0]
        if verify != len(WHITELIST):
            print(f"ABORT: fund_universe verify expected {len(WHITELIST)}, got {verify}. Rolling back.")
            con.execute("ROLLBACK;")
            return 3

        # 2. fund_holdings_v2 cascade
        cascade_rows_before = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE series_id IN ({','.join(['?'] * len(series_ids))});
            """,
            series_ids,
        ).fetchone()[0]
        con.execute(
            f"""
            UPDATE fund_holdings_v2
            SET fund_strategy_at_filing = '{TARGET}'
            WHERE series_id IN ({','.join(['?'] * len(series_ids))});
            """,
            series_ids,
        )
        cascade_rows_after = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE series_id IN ({','.join(['?'] * len(series_ids))})
              AND fund_strategy_at_filing = ?;
            """,
            [*series_ids, TARGET],
        ).fetchone()[0]
        if cascade_rows_after != cascade_rows_before:
            print(
                f"ABORT: cascade count mismatch — "
                f"before={cascade_rows_before} after_with_target={cascade_rows_after}. Rolling back."
            )
            con.execute("ROLLBACK;")
            return 4

        con.execute("COMMIT;")
        print(f"COMMIT — fund_universe rows updated: {len(WHITELIST)}")
        print(f"COMMIT — fund_holdings_v2 rows updated: {cascade_rows_after}")
    except Exception as exc:  # pragma: no cover
        print(f"EXCEPTION: {exc}. Rolling back.")
        con.execute("ROLLBACK;")
        raise

    # Final post-state
    final = con.execute(
        """
        SELECT fu.series_id, fu.fund_name, fu.fund_strategy
        FROM fund_universe fu
        WHERE fu.fund_name IN (?, ?)
        ORDER BY fu.fund_name;
        """,
        list(WHITELIST),
    ).fetchall()
    print("\nFinal fund_universe state:")
    for r in final:
        print(f"  {r}")

    holdings_final = con.execute(
        f"""
        SELECT series_id, fund_strategy_at_filing, COUNT(*) AS rows
        FROM fund_holdings_v2
        WHERE series_id IN ({','.join(['?'] * len(series_ids))})
        GROUP BY series_id, fund_strategy_at_filing
        ORDER BY series_id, fund_strategy_at_filing;
        """,
        series_ids,
    ).fetchall()
    print("\nFinal fund_holdings_v2 state:")
    for r in holdings_final:
        print(f"  {r}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
