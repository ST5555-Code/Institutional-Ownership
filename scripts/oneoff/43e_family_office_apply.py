"""
43e — apply family_office reclassification to managers + holdings_v2.

Reads data/reference/categorized_institutions_funds_v2.csv, filters to
category='family_office' (57 rows), and UPDATEs the two tables to flip
matching rows to 'family_office' regardless of current value.

Why a one-off and not backfill_manager_types.py: the existing backfill
script only fills NULL/unknown rows. With prod at unknown=0 it is a no-op
(see rule9-43e PR #194 dry-run report). To actually land the
reclassification we have to UPDATE existing values, which is what this
script does — scoped to one category (family_office) so the blast radius
is bounded to the 43e taxonomy work.

Targets prod by default. Writes are gated behind --apply; default mode
is dry-run.

Usage:
  python3 scripts/oneoff/43e_family_office_apply.py            # dry-run
  python3 scripts/oneoff/43e_family_office_apply.py --apply    # write to prod
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from db import PROD_DB, record_freshness  # noqa: E402

DEFAULT_CSV_PATH = os.path.join(ROOT, "data", "reference",
                                "categorized_institutions_funds_v2.csv")


def load_family_names(csv_path: str) -> list[str]:
    """Return the lower-trimmed name_clean list for category=family_office."""
    out = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("category") == "family_office":
                name = (row.get("name") or "").strip().lower()
                if name:
                    out.append(name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Apply family_office reclassification to managers + holdings_v2.",
    )
    ap.add_argument("--apply", action="store_true",
                    help="Write to prod. Default is dry-run.")
    ap.add_argument("--csv-path", default=DEFAULT_CSV_PATH,
                    help=f"Override CSV source (default: {DEFAULT_CSV_PATH}).")
    args = ap.parse_args()

    names = load_family_names(args.csv_path)
    if not names:
        print(f"FATAL: no family_office rows in {args.csv_path}", file=sys.stderr)
        return 2
    print(f"CSV: {args.csv_path}")
    print(f"CSV family_office names: {len(names)}")

    if not os.path.exists(PROD_DB):
        print(f"FATAL: prod DB missing: {PROD_DB}", file=sys.stderr)
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Mode: {mode}")
    print(f"DB:   {PROD_DB}")
    print(f"Started: {datetime.now().isoformat(timespec='seconds')}")
    print()

    con = duckdb.connect(PROD_DB, read_only=not args.apply)
    try:
        con.execute("CREATE TEMP TABLE _fo_names(name_clean VARCHAR)")
        con.executemany("INSERT INTO _fo_names VALUES (?)", [(n,) for n in names])

        # ---- BEFORE ----
        m_before = con.execute("""
            SELECT m.strategy_type, COUNT(*)
            FROM managers m
            JOIN _fo_names f
              ON LOWER(TRIM(COALESCE(m.parent_name, m.manager_name))) = f.name_clean
            WHERE m.strategy_type IS DISTINCT FROM 'family_office'
            GROUP BY 1 ORDER BY 2 DESC
        """).fetchall()
        m_total = sum(n for _, n in m_before)

        h_before = con.execute("""
            SELECT h.manager_type, COUNT(*)
            FROM holdings_v2 h
            JOIN _fo_names f
              ON LOWER(TRIM(COALESCE(h.inst_parent_name, h.manager_name))) = f.name_clean
            WHERE h.manager_type IS DISTINCT FROM 'family_office'
            GROUP BY 1 ORDER BY 2 DESC
        """).fetchall()
        h_total = sum(n for _, n in h_before)

        print(f"managers rows that will flip → family_office: {m_total}")
        for current, n in m_before:
            print(f"  {current!r:30s} {n:>6}")
        print()
        print(f"holdings_v2 rows that will flip → family_office: {h_total:,}")
        for current, n in h_before:
            print(f"  {current!r:30s} {n:>10,}")
        print()

        if not args.apply:
            print("[dry-run] no UPDATE issued.")
            return 0

        # ---- APPLY ----
        print("Applying UPDATE on managers...", flush=True)
        con.execute("""
            UPDATE managers
            SET strategy_type = 'family_office'
            FROM _fo_names f
            WHERE LOWER(TRIM(COALESCE(managers.parent_name, managers.manager_name)))
                = f.name_clean
              AND managers.strategy_type IS DISTINCT FROM 'family_office'
        """)

        print("Applying UPDATE on holdings_v2...", flush=True)
        con.execute("""
            UPDATE holdings_v2
            SET manager_type = 'family_office'
            FROM _fo_names f
            WHERE LOWER(TRIM(COALESCE(holdings_v2.inst_parent_name,
                                      holdings_v2.manager_name))) = f.name_clean
              AND holdings_v2.manager_type IS DISTINCT FROM 'family_office'
        """)

        # ---- VERIFY ----
        m_after = con.execute(
            "SELECT COUNT(*) FROM managers WHERE strategy_type = 'family_office'"
        ).fetchone()[0]
        h_after = con.execute(
            "SELECT COUNT(*) FROM holdings_v2 WHERE manager_type = 'family_office'"
        ).fetchone()[0]
        print(f"AFTER: managers family_office rows = {m_after}")
        print(f"AFTER: holdings_v2 family_office rows = {h_after:,}")

        # Stamp freshness on both tables
        try:
            record_freshness(con, "managers")
            record_freshness(con, "holdings_v2")
            print("Stamped data_freshness for managers + holdings_v2.")
        except Exception as e:
            print(f"WARN: record_freshness failed: {e}")

        con.execute("CHECKPOINT")
        print(f"Done: {datetime.now().isoformat(timespec='seconds')}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
