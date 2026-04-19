#!/usr/bin/env python3
"""
Build a small, deterministic CI fixture DuckDB from a production DB.

Reads prod READ-ONLY (via ATTACH) and writes to a separate fixture file.
Never mutates prod. Used by Phase 0-B2 smoke CI per
docs/ci_fixture_design.md (Option 2 — committed binary snapshot).

Usage (default):
    python3 scripts/build_fixture.py --dry-run        # row-count preview
    python3 scripts/build_fixture.py --yes            # write fixture

Safety rails:
  - Source is always opened with ATTACH ... (READ_ONLY).
  - Aborts if --source and --dest resolve to the same path.
  - Aborts if dest exists without --force.
  - Dry-run mode writes nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


REFERENCE_TICKERS = ["AAPL", "MSFT", "EQT", "NVDA"]
LATEST_QUARTER = "2025Q4"
# Only the latest quarter is retained in the fixture. flow_analysis is not a
# Phase 0-B2 smoke endpoint; extending back quarters just inflates fixture
# size. Add more quarters here if a future smoke test needs multi-quarter
# flows.
FLOW_QUARTERS = [LATEST_QUARTER]


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="data/13f.duckdb",
                    help="Production DB path (read-only). Default: data/13f.duckdb")
    ap.add_argument("--dest", default="tests/fixtures/13f_fixture.duckdb",
                    help="Fixture output path. Default: tests/fixtures/13f_fixture.duckdb")
    ap.add_argument("--tickers", default=",".join(REFERENCE_TICKERS))
    ap.add_argument("--quarter", default=LATEST_QUARTER)
    ap.add_argument("--flow-quarters", default=",".join(FLOW_QUARTERS))
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing dest file")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report row counts without writing")
    ap.add_argument("--yes", action="store_true",
                    help="Skip interactive confirmation prompt")
    return ap.parse_args()


def confirm(args, tickers, flow_qs):
    src = Path(args.source).resolve()
    dest = Path(args.dest).resolve()
    if src == dest:
        sys.exit("ERROR: --source and --dest resolve to the same path")
    print(f"[build_fixture] source:        {src} (read-only)")
    print(f"[build_fixture] dest:          {dest}")
    print(f"[build_fixture] tickers:       {tickers}")
    print(f"[build_fixture] quarter:       {args.quarter}")
    print(f"[build_fixture] flow quarters: {flow_qs}")
    print(f"[build_fixture] mode:          {'DRY RUN' if args.dry_run else 'WRITE'}")
    if args.dry_run or args.yes:
        return
    reply = input("Proceed? [y/N] ").strip().lower()
    if reply not in ("y", "yes"):
        sys.exit("Aborted by user.")


def _sql_list(vals):
    return ",".join(f"'{v}'" for v in vals)


def main():
    args = parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    flow_qs = [q.strip() for q in args.flow_quarters.split(",") if q.strip()]
    confirm(args, tickers, flow_qs)

    src = Path(args.source)
    dest = Path(args.dest)
    if not src.exists():
        sys.exit(f"ERROR: source DB not found at {src}")

    if not args.dry_run:
        if dest.exists() and not args.force:
            sys.exit(f"ERROR: dest {dest} exists. Pass --force to overwrite.")
        if dest.exists():
            dest.unlink()
        dest.parent.mkdir(parents=True, exist_ok=True)

    # dest is the main connection; prod is ATTACHed read-only.
    con = duckdb.connect(":memory:" if args.dry_run else str(dest))
    con.execute(f"ATTACH '{src}' AS prod (READ_ONLY)")

    tickers_sql = _sql_list(tickers)
    flow_qs_sql = _sql_list(flow_qs)
    quarter = args.quarter

    sizes = {}

    def create(name: str, select_sql: str, order_by: str | None = None):
        full = f"SELECT * FROM ({select_sql}) ORDER BY {order_by}" if order_by else select_sql
        if args.dry_run:
            n = con.execute(f"SELECT COUNT(*) FROM ({select_sql})").fetchone()[0]
        else:
            con.execute(f"CREATE TABLE {name} AS {full}")
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        sizes[name] = n
        print(f"[build_fixture] {name:38s} {n:>10,}")

    # ── 1. Reference — full copy (tiny) ────────────────────────────────────
    create("fund_family_patterns",
           "SELECT * FROM prod.fund_family_patterns",
           "inst_parent_name, pattern")
    create("data_freshness",
           "SELECT * FROM prod.data_freshness",
           "table_name")
    create("entity_overrides_persistent",
           "SELECT * FROM prod.entity_overrides_persistent",
           "override_id")

    # ── 2. Ticker-scoped (not quarter) ─────────────────────────────────────
    create("securities",
           f"SELECT * FROM prod.securities WHERE ticker IN ({tickers_sql})",
           "cusip")
    create("market_data",
           f"SELECT * FROM prod.market_data WHERE ticker IN ({tickers_sql})",
           "ticker")

    # ── 3. Ticker + latest-quarter ─────────────────────────────────────────
    create("shares_outstanding_history",
           f"""SELECT * FROM prod.shares_outstanding_history
               WHERE ticker IN ({tickers_sql})""",
           "ticker, as_of_date")

    create("holdings_v2",
           f"""SELECT * FROM prod.holdings_v2
               WHERE ticker IN ({tickers_sql}) AND quarter = '{quarter}'""",
           "ticker, cik, cusip")
    create("fund_holdings_v2",
           f"""SELECT * FROM prod.fund_holdings_v2
               WHERE ticker IN ({tickers_sql}) AND quarter = '{quarter}'""",
           "ticker, fund_cik, cusip")
    create("summary_by_ticker",
           f"SELECT * FROM prod.summary_by_ticker WHERE ticker IN ({tickers_sql})",
           "ticker, quarter")
    create("ticker_flow_stats",
           f"SELECT * FROM prod.ticker_flow_stats WHERE ticker IN ({tickers_sql})",
           "ticker, quarter_from")
    create("beneficial_ownership_current",
           f"SELECT * FROM prod.beneficial_ownership_current WHERE subject_ticker IN ({tickers_sql})",
           "subject_ticker, filer_cik")

    # investor_flows is intentionally EXCLUDED from the fixture. None of the
    # 4 Phase 0-B2 smoke endpoints (/api/tickers, /api/query1,
    # /api/entity_graph, /api/summary) read from it. flow_analysis is not
    # a smoke endpoint. If a future smoke test needs flows, add a scoped
    # create() here filtered to a single ticker + quarter.

    # ── 5. Entity closure (seed + rollup_history walk to fixed point) ──────
    # Seed eids come from the holdings/fund_holdings we just filtered.
    if args.dry_run:
        h_src = f"(SELECT * FROM prod.holdings_v2 WHERE ticker IN ({tickers_sql}) AND quarter = '{quarter}')"
        fh_src = f"(SELECT * FROM prod.fund_holdings_v2 WHERE ticker IN ({tickers_sql}) AND quarter = '{quarter}')"
    else:
        h_src = "holdings_v2"
        fh_src = "fund_holdings_v2"

    seed_sql = f"""
        SELECT entity_id          FROM {h_src}  WHERE entity_id          IS NOT NULL
        UNION SELECT rollup_entity_id    FROM {h_src}  WHERE rollup_entity_id    IS NOT NULL
        UNION SELECT dm_rollup_entity_id FROM {h_src}  WHERE dm_rollup_entity_id IS NOT NULL
        UNION SELECT entity_id           FROM {fh_src} WHERE entity_id           IS NOT NULL
        UNION SELECT rollup_entity_id    FROM {fh_src} WHERE rollup_entity_id    IS NOT NULL
        UNION SELECT dm_entity_id        FROM {fh_src} WHERE dm_entity_id        IS NOT NULL
        UNION SELECT dm_rollup_entity_id FROM {fh_src} WHERE dm_rollup_entity_id IS NOT NULL
    """

    con.execute(f"""
        CREATE TEMP TABLE _eids AS
        WITH RECURSIVE seed AS ({seed_sql}),
        closure(entity_id) AS (
            SELECT entity_id FROM seed
            UNION
            SELECT r.rollup_entity_id
            FROM prod.entity_rollup_history r
            JOIN closure c ON r.entity_id = c.entity_id
            WHERE r.rollup_entity_id IS NOT NULL
        )
        SELECT DISTINCT entity_id FROM closure WHERE entity_id IS NOT NULL
    """)
    n_eids = con.execute("SELECT COUNT(*) FROM _eids").fetchone()[0]
    print(f"[build_fixture] entity closure:                      {n_eids:>10,}")

    # ── 6. Entity tables filtered to closure ───────────────────────────────
    # entity_rollup_history is trimmed to CURRENT rows only. Prod uses
    # `valid_to = '9999-12-31'` as the open-row sentinel (not NULL). Smoke
    # endpoints only read the current rollup graph; historical SCD rows
    # inflate the fixture without exercising any tested code path.
    create("entities",
           "SELECT * FROM prod.entities WHERE entity_id IN (SELECT entity_id FROM _eids)",
           "entity_id")
    create("entity_aliases",
           "SELECT * FROM prod.entity_aliases WHERE entity_id IN (SELECT entity_id FROM _eids)",
           "entity_id, alias_name")
    create("entity_identifiers",
           "SELECT * FROM prod.entity_identifiers WHERE entity_id IN (SELECT entity_id FROM _eids)",
           "entity_id, identifier_type, identifier_value")
    create("entity_relationships",
           """SELECT * FROM prod.entity_relationships
              WHERE parent_entity_id IN (SELECT entity_id FROM _eids)
                 OR child_entity_id  IN (SELECT entity_id FROM _eids)""",
           "parent_entity_id, child_entity_id")
    create("entity_rollup_history",
           """SELECT * FROM prod.entity_rollup_history
              WHERE valid_to = DATE '9999-12-31'
                AND (entity_id        IN (SELECT entity_id FROM _eids)
                  OR rollup_entity_id IN (SELECT entity_id FROM _eids))""",
           "entity_id, rollup_type, valid_from")
    create("entity_classification_history",
           "SELECT * FROM prod.entity_classification_history WHERE entity_id IN (SELECT entity_id FROM _eids)",
           "entity_id, valid_from")

    # ── 7. Managers scoped by CIKs of entity closure ───────────────────────
    create("managers",
           """SELECT * FROM prod.managers
              WHERE cik IN (
                  SELECT identifier_value FROM prod.entity_identifiers
                  WHERE identifier_type = 'cik'
                    AND entity_id IN (SELECT entity_id FROM _eids)
              )""",
           "cik")

    # ── 8. summary_by_parent filtered by eid closure ───────────────────────
    create("summary_by_parent",
           f"""SELECT * FROM prod.summary_by_parent
               WHERE quarter = '{quarter}'
                 AND rollup_entity_id IN (SELECT entity_id FROM _eids)""",
           "rollup_entity_id")

    # ── 9. ncen_adviser_map scoped by funds in fixture ─────────────────────
    ncen_scope = ("(SELECT DISTINCT fund_cik FROM prod.fund_holdings_v2 "
                  f"WHERE ticker IN ({tickers_sql}) AND quarter = '{quarter}')") \
        if args.dry_run else "(SELECT DISTINCT fund_cik FROM fund_holdings_v2)"
    create("ncen_adviser_map",
           f"SELECT * FROM prod.ncen_adviser_map WHERE registrant_cik IN {ncen_scope}",
           "registrant_cik, adviser_crd, filing_date")

    # ── 10. fund_universe scoped by funds in fixture ───────────────────────
    fu_scope = ("(SELECT DISTINCT fund_cik FROM prod.fund_holdings_v2 "
                f"WHERE ticker IN ({tickers_sql}) AND quarter = '{quarter}')") \
        if args.dry_run else "(SELECT DISTINCT fund_cik FROM fund_holdings_v2)"
    create("fund_universe",
           f"SELECT * FROM prod.fund_universe WHERE fund_cik IN {fu_scope}",
           "fund_cik, series_id")

    con.execute("DROP TABLE _eids")

    # ── 11. Recreate the entity_current view ───────────────────────────────
    # Mirrored verbatim from prod DDL (see `duckdb_views()` output). The
    # smoke /api/entity_graph endpoint reads from it directly. Keep in sync
    # if prod redefines the view.
    con.execute("""
        CREATE VIEW entity_current AS
        SELECT e.entity_id,
               e.entity_type,
               e.created_at,
               COALESCE(ea.alias_name, e.canonical_name) AS display_name,
               ech.classification,
               ech.is_activist,
               ech.confidence AS classification_confidence,
               er.rollup_entity_id,
               er.rollup_type
        FROM entities AS e
        LEFT JOIN (
            SELECT entity_id, alias_name
            FROM entity_aliases
            WHERE is_preferred = TRUE
              AND valid_to = DATE '9999-12-31'
        ) AS ea ON e.entity_id = ea.entity_id
        LEFT JOIN entity_classification_history AS ech
            ON e.entity_id = ech.entity_id
           AND ech.valid_to = DATE '9999-12-31'
        LEFT JOIN entity_rollup_history AS er
            ON e.entity_id = er.entity_id
           AND er.rollup_type = 'economic_control_v1'
           AND er.valid_to = DATE '9999-12-31'
    """)

    con.execute("DETACH prod")
    if not args.dry_run:
        con.execute("CHECKPOINT")
    con.close()

    if not args.dry_run:
        size_kb = dest.stat().st_size / 1024
        print(f"\n[build_fixture] wrote {dest} — {size_kb:,.0f} KB")
        if size_kb > 1024:
            print("[build_fixture] WARNING: size exceeds 1 MB target")
    else:
        total = sum(sizes.values())
        print(f"\n[build_fixture] DRY RUN — {len(sizes)} tables, {total:,} rows total. No file written.")


if __name__ == "__main__":
    main()
