#!/usr/bin/env python3
"""
INF39 Phase 1: Staging rebuild via Strategy C (per-table capture-and-recreate).

For each L3 table:
  1. Capture prod DDL (table + indexes) via duckdb_tables.sql / duckdb_indexes.sql.
  2. Pre-check row counts on prod + staging.
  3. DROP staging table (drops associated indexes).
  4. Recreate table from captured prod DDL.
  5. Recreate indexes from captured prod DDL.
  6. For mirror tables: INSERT INTO staging.<t> SELECT * FROM p.<t> via ATTACH.
     For schema-only companions (*_staging): skip the INSERT.
  7. Post-check: row count, column count, index count.
  8. CHECKPOINT to flush.

Writes to data/13f_staging.duckdb only. Prod is attached read-only.
Log appended to docs/SCHEMA_DIFF_PHASE_1_REBUILD_LOG.md.

Usage:
    python3 scripts/inf39_rebuild_staging.py [--tables t1,t2] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(BASE_DIR, "data", "13f.duckdb")
STAGING_DB = os.path.join(BASE_DIR, "data", "13f_staging.duckdb")
LOG_PATH = os.path.join(BASE_DIR, "docs", "SCHEMA_DIFF_PHASE_1_REBUILD_LOG.md")

# L3 mirror tables — rebuild schema + reload data from prod.
# Order: entity MDM roots first, then identifiers/relationships, then
# reference, then facts. No FKs exist so ordering matters only for
# interruption-recovery readability.
MIRROR_TABLES = [
    # Entity MDM core (7)
    "entities",
    "entity_identifiers",
    "entity_relationships",
    "entity_aliases",
    "entity_classification_history",
    "entity_rollup_history",
    "entity_overrides_persistent",
    # Entity MDM additional (6)
    "cik_crd_direct",
    "cik_crd_links",
    "lei_reference",
    "other_managers",
    "parent_bridge",
    "fetched_tickers_13dg",
    "listed_filings_13dg",
    # Reference / other L3 (11)
    "securities",
    "market_data",
    "short_interest",
    "fund_universe",
    "shares_outstanding_history",
    "adv_managers",
    "ncen_adviser_map",
    "filings",
    "filings_deduped",
    "cusip_classifications",
    "_cache_openfigi",
    # Core facts (3) — last, largest
    "beneficial_ownership_v2",
    "fund_holdings_v2",
    "holdings_v2",
]

# Schema-only companions — rebuild schema, skip data copy.
# Per Phase 1 prompt: these are staging-only queue tables; prod rows are not
# copied back during rebuild (pre-existing staging queue rows are discarded
# and will be re-seeded by the sync → diff → promote workflow as needed).
SCHEMA_ONLY_TABLES = [
    "entity_identifiers_staging",
    "entity_relationships_staging",
]

ALL_TABLES = MIRROR_TABLES + SCHEMA_ONLY_TABLES

# Fact tables that carry a surrogate ``row_id`` sequence (mig-06 / INF40).
# After a MIRROR rebuild via ``INSERT INTO t SELECT * FROM p.t`` the staging
# rows retain prod's row_id values, but the staging sequence state is
# untouched — so a subsequent staging-only INSERT would allocate row_id=1
# and collide with the mirrored rows. The post-rebuild ``setval(...)``
# clamp below advances the staging sequence past the maximum row_id in
# the rebuilt table. Harmless if row_id is absent (pre-migration-014).
ROW_ID_FACT_TABLES = {
    "holdings_v2",
    "fund_holdings_v2",
    "beneficial_ownership_v2",
}


def capture_prod_ddl(prod_con, table: str) -> tuple[str, list[tuple[str, str]]]:
    row = prod_con.execute(
        "SELECT sql FROM duckdb_tables() "
        "WHERE database_name = current_database() "
        "AND schema_name='main' AND table_name=?",
        [table],
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"Table {table} not found in prod or has empty DDL")
    table_ddl = row[0].rstrip()
    if not table_ddl.endswith(";"):
        table_ddl += ";"

    idx_rows = prod_con.execute(
        "SELECT index_name, sql FROM duckdb_indexes() "
        "WHERE database_name = current_database() "
        "AND schema_name='main' AND table_name=? "
        "ORDER BY index_name",
        [table],
    ).fetchall()
    indexes = []
    for name, sql in idx_rows:
        if sql:
            s = sql.rstrip()
            if not s.endswith(";"):
                s += ";"
            indexes.append((name, s))
    return table_ddl, indexes


def row_count(con, table: str) -> int:
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return -1


def column_count(con, table: str) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM duckdb_columns() "
        "WHERE database_name = current_database() "
        "AND schema_name='main' AND table_name=?",
        [table],
    ).fetchone()[0]


def index_count(con, table: str) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM duckdb_indexes() "
        "WHERE database_name = current_database() "
        "AND schema_name='main' AND table_name=?",
        [table],
    ).fetchone()[0]


def rebuild_one(staging_con, prod_con, table: str, copy_data: bool) -> dict:
    start = time.monotonic()
    steps: dict[str, float] = {}

    t0 = time.monotonic()
    prod_rows = row_count(prod_con, table)
    staging_rows_before = row_count(staging_con, table)
    steps["precheck_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    table_ddl, indexes = capture_prod_ddl(prod_con, table)
    steps["capture_ddl_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    staging_con.execute(f'DROP TABLE IF EXISTS "{table}"')
    steps["drop_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    staging_con.execute(table_ddl)
    steps["create_table_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    for _, idx_sql in indexes:
        staging_con.execute(idx_sql)
    steps["create_indexes_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    if copy_data:
        staging_con.execute(f'INSERT INTO "{table}" SELECT * FROM p."{table}"')
    steps["insert_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    if copy_data and table in ROW_ID_FACT_TABLES:
        has_row_id = staging_con.execute(
            "SELECT 1 FROM duckdb_columns() "
            "WHERE schema_name='main' AND table_name=? AND column_name='row_id'",
            [table],
        ).fetchone() is not None
        if has_row_id:
            seq = f"{table}_row_id_seq"
            staging_con.execute(
                f"SELECT setval('{seq}', "
                f'(SELECT COALESCE(MAX(row_id), 0) + 1 FROM "{table}"))'
            )
    steps["row_id_clamp_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    staging_rows_after = row_count(staging_con, table)
    staging_cols = column_count(staging_con, table)
    prod_cols = column_count(prod_con, table)
    staging_idx = index_count(staging_con, table)
    prod_idx = index_count(prod_con, table)
    steps["postcheck_s"] = round(time.monotonic() - t0, 3)

    t0 = time.monotonic()
    staging_con.execute("CHECKPOINT")
    steps["checkpoint_s"] = round(time.monotonic() - t0, 3)

    total = round(time.monotonic() - start, 3)

    if copy_data:
        row_ok = staging_rows_after == prod_rows
    else:
        row_ok = staging_rows_after == 0
    col_ok = staging_cols == prod_cols
    idx_ok = staging_idx == prod_idx
    ok = row_ok and col_ok and idx_ok

    return {
        "table": table,
        "copy_data": copy_data,
        "prod_rows": prod_rows,
        "staging_rows_before": staging_rows_before,
        "staging_rows_after": staging_rows_after,
        "prod_cols": prod_cols,
        "staging_cols": staging_cols,
        "prod_indexes": prod_idx,
        "staging_indexes": staging_idx,
        "index_count_captured": len(indexes),
        "indexes_captured": [n for n, _ in indexes],
        "total_s": total,
        "steps": steps,
        "ok": ok,
        "row_ok": row_ok,
        "col_ok": col_ok,
        "idx_ok": idx_ok,
    }


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}m{s:04.1f}s"


def write_log(results: list[dict], total_wall_s: float, started_at: str, ended_at: str) -> None:
    lines = []
    lines.append("# INF39 Phase 1 — Staging Rebuild Execution Log")
    lines.append("")
    lines.append(f"_Generated by `scripts/inf39_rebuild_staging.py`._")
    lines.append("")
    lines.append(f"- Started:  {started_at}")
    lines.append(f"- Ended:    {ended_at}")
    lines.append(f"- Elapsed:  {format_duration(total_wall_s)}")
    lines.append(f"- Strategy: C (per-table capture-and-recreate)")
    lines.append(f"- Prod:     `{PROD_DB}` (read-only ATTACH as `p`)")
    lines.append(f"- Staging:  `{STAGING_DB}` (read-write)")
    lines.append(f"- Tables:   {len(results)} total "
                 f"({sum(1 for r in results if r['copy_data'])} mirror + "
                 f"{sum(1 for r in results if not r['copy_data'])} schema-only)")
    lines.append("")
    ok_n = sum(1 for r in results if r["ok"])
    lines.append(f"## Summary")
    lines.append("")
    lines.append(f"- Per-table verdicts: {ok_n}/{len(results)} OK")
    lines.append(f"- Aggregate rows reloaded into staging: "
                 f"{sum(r['staging_rows_after'] for r in results if r['copy_data']):,}")
    lines.append("")

    lines.append("### Per-table summary table")
    lines.append("")
    lines.append("| # | Table | Mode | Prod rows | Staging before | Staging after | Cols | Idx | Total | Verdict |")
    lines.append("|---|-------|------|-----------|----------------|---------------|------|-----|-------|---------|")
    for i, r in enumerate(results, 1):
        mode = "MIRROR" if r["copy_data"] else "SCHEMA-ONLY"
        verdict = "OK" if r["ok"] else "FAIL"
        lines.append(
            f"| {i} | `{r['table']}` | {mode} | "
            f"{r['prod_rows']:,} | {r['staging_rows_before']:,} | {r['staging_rows_after']:,} | "
            f"{r['staging_cols']}/{r['prod_cols']} | {r['staging_indexes']}/{r['prod_indexes']} | "
            f"{format_duration(r['total_s'])} | {verdict} |"
        )
    lines.append("")

    lines.append("## Per-table detail")
    lines.append("")
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. `{r['table']}` ({'MIRROR' if r['copy_data'] else 'SCHEMA-ONLY'})")
        lines.append("")
        lines.append(f"- Prod rows:             {r['prod_rows']:,}")
        lines.append(f"- Staging rows (before): {r['staging_rows_before']:,}")
        lines.append(f"- Staging rows (after):  {r['staging_rows_after']:,}")
        lines.append(f"- Columns (staging/prod): {r['staging_cols']}/{r['prod_cols']}")
        lines.append(f"- Indexes (staging/prod): {r['staging_indexes']}/{r['prod_indexes']}")
        lines.append(f"- Indexes captured:       {r['index_count_captured']} "
                     f"({', '.join(r['indexes_captured']) if r['indexes_captured'] else '(none)'})")
        lines.append(f"- Verdict: row_ok={r['row_ok']} col_ok={r['col_ok']} idx_ok={r['idx_ok']} → "
                     f"**{'OK' if r['ok'] else 'FAIL'}**")
        lines.append(f"- Step timings: " + ", ".join(f"{k}={v}s" for k, v in r["steps"].items()))
        lines.append(f"- Total: {format_duration(r['total_s'])}")
        if r["copy_data"] and r["staging_rows_before"] != r["prod_rows"]:
            delta = r["staging_rows_before"] - r["prod_rows"]
            sign = "+" if delta > 0 else ""
            lines.append(f"- Note: staging drifted by {sign}{delta:,} rows vs prod before rebuild; resolved via reload.")
        if not r["copy_data"]:
            lines.append(f"- Note: schema-only rebuild per Phase 1 decision; pre-existing staging rows discarded.")
        lines.append("")

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", type=str, default=None,
                    help="Comma-separated table subset (default: all 32)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Capture DDL + print plan, no writes")
    args = ap.parse_args()

    if not os.path.exists(PROD_DB):
        print(f"ERROR: prod DB missing: {PROD_DB}", file=sys.stderr)
        return 2
    if not os.path.exists(STAGING_DB):
        print(f"ERROR: staging DB missing: {STAGING_DB}", file=sys.stderr)
        return 2

    tables = ALL_TABLES
    if args.tables:
        requested = [t.strip() for t in args.tables.split(",") if t.strip()]
        unknown = [t for t in requested if t not in ALL_TABLES]
        if unknown:
            print(f"ERROR: unknown tables: {unknown}", file=sys.stderr)
            return 2
        tables = requested

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wall_start = time.monotonic()
    print(f"[{started_at}] INF39 rebuild start — {len(tables)} tables", flush=True)

    if args.dry_run:
        prod = duckdb.connect(PROD_DB, read_only=True)
        for t in tables:
            mode = "MIRROR" if t in MIRROR_TABLES else "SCHEMA-ONLY"
            ddl, idxs = capture_prod_ddl(prod, t)
            print(f"  {mode:12s} {t:40s} prod_rows={row_count(prod, t):>12,} "
                  f"indexes={len(idxs)}", flush=True)
        prod.close()
        return 0

    staging = duckdb.connect(STAGING_DB)
    staging.execute(f"ATTACH '{PROD_DB}' AS p (READ_ONLY)")
    prod_read = duckdb.connect(PROD_DB, read_only=True)

    results: list[dict] = []
    try:
        for i, t in enumerate(tables, 1):
            copy = t in MIRROR_TABLES
            mode = "MIRROR" if copy else "SCHEMA-ONLY"
            print(f"  [{i}/{len(tables)}] {mode:12s} {t}", end="", flush=True)
            r = rebuild_one(staging, prod_read, t, copy)
            verdict = "OK" if r["ok"] else "FAIL"
            print(f"  rows={r['staging_rows_after']:>12,} "
                  f"idx={r['staging_indexes']}/{r['prod_indexes']} "
                  f"[{format_duration(r['total_s'])}] {verdict}",
                  flush=True)
            results.append(r)
            if not r["ok"]:
                print(f"ABORT: {t} rebuild verdict FAIL", file=sys.stderr, flush=True)
                break
    finally:
        staging.execute("DETACH p")
        staging.close()
        prod_read.close()

    wall_s = time.monotonic() - wall_start
    ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_log(results, wall_s, started_at, ended_at)
    ok_all = all(r["ok"] for r in results) and len(results) == len(tables)
    print(f"[{ended_at}] INF39 rebuild {'COMPLETE' if ok_all else 'FAILED'} "
          f"({format_duration(wall_s)}) — log: {LOG_PATH}", flush=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
