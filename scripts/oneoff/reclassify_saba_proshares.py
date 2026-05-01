"""saba-proshares-reclassify: two whitelisted reclassifications, single PR.

Phase 2 (Saba) — align Saba Capital Income & Opportunities Fund II to its sibling.
  Whitelist (must match exactly 1 fund_universe row; otherwise abort):
    - SYN_0000828803  Saba Capital Income & Opportunities Fund II  (multi_asset -> balanced)
  Sibling SYN_0000826020 Fund I is already 'balanced' via PR-1a tiebreaker (NO-OP).

Phase 3 (ProShares) — reclassify 39 ProShares short / inverse / leveraged-short funds.
  Whitelist (39 series_ids currently 'bond_or_other' or 'excluded' -> 'passive').
  13 already-'passive' series are NO-OPs and excluded by `fund_strategy != 'passive'`.

Cascades to fund_holdings_v2.fund_strategy_at_filing for the same series_ids.

Hard gates per phase:
  * Pre-check returns exactly the whitelist size (else abort).
  * UPDATE on fund_universe touches exactly the whitelist size (else ROLLBACK + abort).

Run with --confirm to execute. Default is dry-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]

SABA_WHITELIST = ("SYN_0000828803",)  # Saba Capital Income & Opportunities Fund II
SABA_TARGET = "balanced"

# 39 ProShares series_ids currently bond_or_other or excluded (per Phase 1b audit, 2026-05-01).
# Audit query: SELECT series_id FROM fund_universe WHERE fund_name LIKE '%ProShares%'
#   AND (name matches Short/Inverse/Bear/UltraShort/UltraPro Short)
#   AND fund_strategy != 'passive'
PROSHARES_WHITELIST = (
    # 29 currently bond_or_other
    "S000024909", "S000006831", "S000006824", "S000024910", "S000006830",
    "S000014263", "S000024913", "S000006823", "S000014287", "S000018723",
    "S000014307", "S000014306", "S000014300", "S000014276", "S000014282",
    "S000014304", "S000014308", "S000014299", "S000014302", "S000014264",
    "S000006829", "S000014310", "S000014298", "S000024912", "S000014301",
    "S000090186", "S000014296", "S000014288", "S000006822",
    # 10 currently excluded
    "S000018733", "S000084462", "S000076601", "S000084463", "S000018721",
    "S000082336", "S000024917", "S000018720", "S000018732", "S000059656",
)
PROSHARES_TARGET = "passive"


def _resolve_db_path() -> Path:
    primary = REPO_ROOT / "data" / "13f.duckdb"
    if primary.exists():
        return primary
    parts = REPO_ROOT.parts
    if ".claude" in parts:
        idx = parts.index(".claude")
        parent = Path(*parts[:idx])
        candidate = parent / "data" / "13f.duckdb"
        if candidate.exists():
            return candidate
    return primary


def _phase(con, label: str, whitelist: tuple[str, ...], target: str, confirm: bool) -> int:
    print(f"\n=== {label} ===")
    print(f"Whitelist (n={len(whitelist)}): target='{target}'")

    placeholders = ",".join(["?"] * len(whitelist))

    pre = con.execute(
        f"""
        SELECT series_id, fund_name, fund_strategy
        FROM fund_universe
        WHERE series_id IN ({placeholders})
          AND fund_strategy != ?
        ORDER BY series_id;
        """,
        [*whitelist, target],
    ).fetchall()
    print(f"Pre-check (rows where current strategy != '{target}'): {len(pre)}")
    for r in pre:
        print(f"  {r}")

    if len(pre) != len(whitelist):
        print(f"ABORT: pre-check expected exactly {len(whitelist)} non-target rows, got {len(pre)}.")
        return 2

    if not confirm:
        cascade = con.execute(
            f"""
            SELECT series_id, fund_strategy_at_filing, COUNT(*) AS rows
            FROM fund_holdings_v2
            WHERE series_id IN ({placeholders})
              AND fund_strategy_at_filing != ?
            GROUP BY series_id, fund_strategy_at_filing
            ORDER BY series_id, fund_strategy_at_filing;
            """,
            [*whitelist, target],
        ).fetchall()
        cascade_total = sum(r[2] for r in cascade)
        print(f"Cascade preview ({cascade_total} fund_holdings_v2 rows would be touched):")
        for r in cascade:
            print(f"  {r}")
        return 0

    try:
        con.execute("BEGIN TRANSACTION;")

        con.execute(
            f"""
            UPDATE fund_universe
            SET fund_strategy = ?
            WHERE series_id IN ({placeholders})
              AND fund_strategy != ?;
            """,
            [target, *whitelist, target],
        )
        verify = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_universe
            WHERE series_id IN ({placeholders}) AND fund_strategy = ?;
            """,
            [*whitelist, target],
        ).fetchone()[0]
        if verify != len(whitelist):
            print(f"ABORT: fund_universe verify expected {len(whitelist)}, got {verify}. Rolling back.")
            con.execute("ROLLBACK;")
            return 3

        cascade_rows_before = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE series_id IN ({placeholders})
              AND fund_strategy_at_filing != ?;
            """,
            [*whitelist, target],
        ).fetchone()[0]
        con.execute(
            f"""
            UPDATE fund_holdings_v2
            SET fund_strategy_at_filing = ?
            WHERE series_id IN ({placeholders})
              AND fund_strategy_at_filing != ?;
            """,
            [target, *whitelist, target],
        )
        cascade_total = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE series_id IN ({placeholders});
            """,
            list(whitelist),
        ).fetchone()[0]
        cascade_target = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE series_id IN ({placeholders})
              AND fund_strategy_at_filing = ?;
            """,
            [*whitelist, target],
        ).fetchone()[0]
        if cascade_target != cascade_total:
            print(
                f"ABORT: cascade verify mismatch — "
                f"all_rows_for_series={cascade_total} rows_with_target={cascade_target}. Rolling back."
            )
            con.execute("ROLLBACK;")
            return 4

        con.execute("COMMIT;")
        print(f"COMMIT — fund_universe rows updated: {len(whitelist)}")
        print(f"COMMIT — fund_holdings_v2 rows updated: {cascade_rows_before}")
    except Exception as exc:
        print(f"EXCEPTION: {exc}. Rolling back.")
        con.execute("ROLLBACK;")
        raise

    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", action="store_true", help="Execute (default dry-run).")
    args = p.parse_args()

    db = _resolve_db_path()
    print(f"DB: {db}")
    print(f"Mode: {'EXECUTE' if args.confirm else 'DRY-RUN'}")

    con = duckdb.connect(str(db), read_only=not args.confirm)

    rc = _phase(con, "PHASE 2 — Saba", SABA_WHITELIST, SABA_TARGET, args.confirm)
    if rc != 0:
        return rc

    rc = _phase(con, "PHASE 3 — ProShares", PROSHARES_WHITELIST, PROSHARES_TARGET, args.confirm)
    if rc != 0:
        return rc

    if args.confirm:
        print("\n=== Final fund_universe distribution (Saba + ProShares) ===")
        saba = con.execute(
            """
            SELECT series_id, fund_name, fund_strategy
            FROM fund_universe
            WHERE fund_name ILIKE '%Saba%' OR family_name ILIKE '%Saba%'
            ORDER BY fund_name;
            """
        ).fetchall()
        for r in saba:
            print(f"  {r}")

        proshares = con.execute(
            """
            SELECT fund_strategy, COUNT(*)
            FROM fund_universe
            WHERE fund_name LIKE '%ProShares%'
              AND (fund_name LIKE '%Short%' OR fund_name LIKE '%Inverse%' OR
                   fund_name LIKE '%Bear%' OR fund_name LIKE '%UltraShort%' OR
                   fund_name LIKE '%UltraPro Short%')
            GROUP BY fund_strategy ORDER BY fund_strategy;
            """
        ).fetchall()
        print("ProShares short/inverse/bear distribution:")
        for r in proshares:
            print(f"  {r}")

    con.close()
    print("\nDone." if args.confirm else "\nDry-run complete. Re-run with --confirm to execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
