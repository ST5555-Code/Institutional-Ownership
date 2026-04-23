#!/usr/bin/env python3
"""
build_fund_classes.py — Extract share class (C-number) data from cached N-PORT XMLs.

Builds the fund_classes table from class IDs found in N-PORT filings and
populates lei_reference from leiOfSeries / seriesLei. The three-step flow
is: build --staging → promote_staging.py → --enrichment-only (prod
fund_holdings_v2.lei ALTER + UPDATE).

Usage:
    python3 scripts/build_fund_classes.py                   # write to prod
    python3 scripts/build_fund_classes.py --staging         # write to staging
    python3 scripts/build_fund_classes.py --dry-run         # project counts, no writes
    python3 scripts/build_fund_classes.py --enrichment-only # post-promote prod LEI update
"""

import argparse
import glob
import os
import sys
from datetime import datetime

import duckdb
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import (  # noqa: E402
    get_db_path,
    is_staging_mode,
    record_freshness,
    seed_staging,
    set_staging_mode,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "nport_raw")
NS = {"n": "http://www.sec.gov/edgar/nport"}

CHECKPOINT_EVERY = 2000  # flush WAL every N XMLs processed


def create_tables(con):
    """Create fund_classes and lei_reference tables."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS fund_classes (
            series_id VARCHAR,
            class_id VARCHAR,
            fund_cik VARCHAR,
            fund_name VARCHAR,
            report_date DATE,
            quarter VARCHAR,
            loaded_at TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS lei_reference (
            lei VARCHAR PRIMARY KEY,
            entity_name VARCHAR,
            entity_type VARCHAR,
            series_id VARCHAR,
            fund_cik VARCHAR,
            updated_at TIMESTAMP
        )
    """)


def parse_xml_for_classes(xml_path):
    """Extract class IDs and LEI from a cached N-PORT XML.

    Returns (result_dict, series_lei, reg_lei) on success or
    (None, None, None) on parse failure. Parse failures are surfaced to
    the caller via an error counter rather than silently swallowed.
    """
    try:
        root = etree.parse(xml_path).getroot()
    except (etree.XMLSyntaxError, OSError) as e:
        print(f"  [parse_error] {os.path.basename(xml_path)}: "
              f"{type(e).__name__}: {e}", flush=True)
        return None, None, None

    series_id = root.findtext(".//n:seriesId", namespaces=NS) or ""
    series_name = root.findtext(".//n:seriesName", namespaces=NS) or ""
    series_lei = root.findtext(".//n:seriesLei", namespaces=NS) or ""
    reg_cik = root.findtext(".//n:regCik", namespaces=NS) or ""
    rep_date = root.findtext(".//n:repPdDate", namespaces=NS) or ""

    class_ids = [c.text.strip() for c in root.findall(".//n:classId", NS) if c.text]

    reg_lei = root.findtext(".//n:regLei", namespaces=NS) or ""

    return {
        "series_id": series_id,
        "series_name": series_name,
        "series_lei": series_lei,
        "reg_cik": reg_cik.lstrip("0").zfill(10),
        "reg_lei": reg_lei,
        "report_date": rep_date,
        "class_ids": class_ids,
    }, series_lei, reg_lei


def _lei_column_exists(con) -> bool:
    """Probe information_schema to avoid speculative ALTER."""
    row = con.execute("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_name = 'fund_holdings_v2' AND column_name = 'lei'
    """).fetchone()
    return bool(row and row[0])


def enrich_fund_holdings_v2(con, dry_run: bool = False):
    """ALTER + UPDATE fund_holdings_v2 with LEI data from lei_reference.

    Split out of the builder path so --enrichment-only can invoke it in
    isolation — same shape as build_managers.enrich_holdings_v2. This
    mutates a ~9.3M-row prod surface and must never run against staging
    (see sec-05-p0-findings.md §6 Risk 3: staging schema would diverge
    from prod). `--staging` callers skip this step; the three-step flow
    is: build --staging → promote → --enrichment-only against prod.
    """
    if dry_run:
        projected = con.execute("""
            SELECT COUNT(*) FROM fund_holdings_v2 h
            JOIN lei_reference lr ON h.series_id = lr.series_id
            WHERE h.lei IS NULL
        """).fetchone()[0] if _lei_column_exists(con) else con.execute("""
            SELECT COUNT(*) FROM fund_holdings_v2 h
            JOIN lei_reference lr ON h.series_id = lr.series_id
        """).fetchone()[0]
        print(f"  [DRY-RUN] would enrich fund_holdings_v2.lei: "
              f"{projected:,} rows", flush=True)
        return projected

    if not _lei_column_exists(con):
        con.execute("ALTER TABLE fund_holdings_v2 ADD COLUMN lei VARCHAR")
        print("  Added lei column to fund_holdings_v2")

    con.execute("""
        UPDATE fund_holdings_v2
        SET lei = lr.lei
        FROM lei_reference lr
        WHERE fund_holdings_v2.series_id = lr.series_id
          AND fund_holdings_v2.lei IS NULL
    """)
    updated_lei = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE lei IS NOT NULL"
    ).fetchone()[0]
    print(f"fund_holdings_v2 with LEI: {updated_lei:,}")
    return updated_lei


def run_enrichment_only(dry_run: bool = False):
    """Post-promote enrichment: update prod fund_holdings_v2.lei from the
    already-promoted prod lei_reference. Mirrors the build_managers.py
    --enrichment-only flow."""
    con = duckdb.connect(get_db_path(), read_only=dry_run)
    try:
        enrich_fund_holdings_v2(con, dry_run=dry_run)
        if not dry_run:
            con.execute("CHECKPOINT")
    finally:
        con.close()
    print("\nDone." + (" (DRY-RUN)" if dry_run else ""))


def _get_existing_classes(con) -> set:
    """Read existing (series_id, class_id) pairs. Returns empty set if
    fund_classes is missing (first run) — any other DuckDB error
    propagates so we don't silently re-insert the whole universe."""
    try:
        rows = con.execute(
            "SELECT series_id, class_id FROM fund_classes"
        ).fetchall()
    except duckdb.CatalogException:
        return set()
    return {(r[0], r[1]) for r in rows}


def run(dry_run: bool = False):
    con = duckdb.connect(get_db_path(), read_only=dry_run)
    if not dry_run:
        create_tables(con)

    xml_files = glob.glob(os.path.join(RAW_DIR, "*", "*.xml"))
    print(f"Found {len(xml_files)} cached N-PORT XMLs")

    existing = _get_existing_classes(con) if not dry_run else set()

    classes_added = 0
    leis_added = 0
    lei_cache = set()
    parse_errors = 0
    lei_errors = 0
    now = datetime.now().isoformat()

    for i, xml_path in enumerate(xml_files):
        if not dry_run and (i + 1) % CHECKPOINT_EVERY == 0:
            con.execute("CHECKPOINT")
        if (i + 1) % 5000 == 0:
            print(f"  [{i+1}/{len(xml_files)}] {classes_added} classes, "
                  f"{leis_added} LEIs, {parse_errors} parse errors...",
                  flush=True)

        result, series_lei, _reg_lei = parse_xml_for_classes(xml_path)
        if result is None:
            parse_errors += 1
            continue
        if not result["series_id"]:
            continue

        series_id = result["series_id"]

        for class_id in result["class_ids"]:
            if (series_id, class_id) in existing:
                continue
            if not dry_run:
                con.execute("""
                    INSERT INTO fund_classes
                    (series_id, class_id, fund_cik, fund_name, report_date,
                     quarter, loaded_at)
                    VALUES (?, ?, ?, ?, TRY_CAST(? AS DATE), NULL, ?)
                """, [series_id, class_id, result["reg_cik"],
                      result["series_name"], result["report_date"], now])
            existing.add((series_id, class_id))
            classes_added += 1

        if series_lei and series_lei not in lei_cache:
            if not dry_run:
                try:
                    con.execute("""
                        INSERT OR REPLACE INTO lei_reference
                        (lei, entity_name, entity_type, series_id, fund_cik,
                         updated_at)
                        VALUES (?, ?, 'fund_series', ?, ?, ?)
                    """, [series_lei, result["series_name"], series_id,
                          result["reg_cik"], now])
                except duckdb.Error as e:
                    lei_errors += 1
                    print(f"  [lei_error] lei={series_lei} "
                          f"series={series_id}: {type(e).__name__}: {e}",
                          flush=True)
                    continue
            lei_cache.add(series_lei)
            leis_added += 1

    if not dry_run:
        con.execute("CHECKPOINT")

    # fund_holdings_v2.lei enrichment runs only against prod. Staging
    # skips it — the prod-surface UPDATE belongs in --enrichment-only,
    # invoked after promote_staging.py lands lei_reference in prod.
    if not is_staging_mode():
        enrich_fund_holdings_v2(con, dry_run=dry_run)

    total_classes = con.execute(
        "SELECT COUNT(*) FROM fund_classes"
    ).fetchone()[0] if not dry_run else 0
    total_leis = con.execute(
        "SELECT COUNT(*) FROM lei_reference"
    ).fetchone()[0] if not dry_run else 0
    unique_series = con.execute(
        "SELECT COUNT(DISTINCT series_id) FROM fund_classes"
    ).fetchone()[0] if not dry_run else 0

    print(f"\n{'='*60}")
    print("SUMMARY" + (" (DRY-RUN)" if dry_run else ""))
    print(f"{'='*60}")
    print(f"XMLs scanned:     {len(xml_files):,}")
    print(f"Parse errors:     {parse_errors:,}")
    print(f"LEI insert errors:{lei_errors:,}")
    if dry_run:
        print(f"Would add classes: {classes_added:,}")
        print(f"Would add LEIs:    {leis_added:,}")
    else:
        print(f"Fund classes: {total_classes:,} (new: {classes_added:,})")
        print(f"Unique series with classes: {unique_series:,}")
        print(f"LEI references: {total_leis:,} (new: {leis_added:,})")

    # Unresolved-% gate: XML parse failure rate.
    if xml_files:
        err_pct = 100 * parse_errors / len(xml_files)
        if err_pct > 1.0:
            print(f"\n  [WARN] parse error rate {err_pct:.2f}% exceeds "
                  f"1% threshold — inspect parse_error log lines above.",
                  flush=True)

    if not dry_run:
        fc = con.execute("""
            SELECT class_id, fund_name, series_id
            FROM fund_classes
            WHERE series_id = 'S000006036'
            ORDER BY class_id
        """).fetchall()
        if fc:
            print(f"\nFidelity Contrafund classes ({len(fc)}):")
            for r in fc:
                print(f"  {r[0]:15s} {r[1]:40s} series={r[2]}")

    if not dry_run:
        con.execute("CHECKPOINT")
        # Freshness is stamped only when writing directly to prod. In
        # --staging the stamp is deferred until promote_staging.py
        # commits the new rows to prod (sec-05-p0-findings.md §3).
        if not is_staging_mode():
            record_freshness(con, "fund_classes")

    con.close()
    print("\nDone." + (" (DRY-RUN)" if dry_run else ""))


def _parse_args() -> argparse.Namespace:
    """CLI parser.

    `--staging` redirects the write target to the staging DB.
    `--dry-run` projects row counts without any mutations (read-only conn).
    `--enrichment-only` runs only the fund_holdings_v2.lei ALTER + UPDATE
    against prod (used after promote_staging.py lands lei_reference).
    """
    parser = argparse.ArgumentParser(
        description=("Extract share-class + LEI data from cached N-PORT XMLs "
                     "into fund_classes / lei_reference / "
                     "fund_holdings_v2.lei."),
    )
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB instead of prod.")
    parser.add_argument("--dry-run", action="store_true",
                        help=("Projection mode: parse XMLs + count what "
                              "would be written; no DB mutations. Opens a "
                              "read-only connection."))
    parser.add_argument(
        "--enrichment-only", action="store_true",
        help=(
            "Skip the XML parse + fund_classes/lei_reference writes and "
            "only run the fund_holdings_v2.lei ALTER + UPDATE against "
            "prod. Used in the three-step flow: build --staging → "
            "promote_staging.py → --enrichment-only."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    _args = _parse_args()
    if _args.staging and _args.enrichment_only:
        raise SystemExit(
            "ERROR: --staging and --enrichment-only are mutually exclusive. "
            "The enrichment step mutates prod fund_holdings_v2."
        )
    if _args.staging:
        set_staging_mode(True)
        seed_staging()
    if _args.enrichment_only:
        run_enrichment_only(dry_run=_args.dry_run)
    else:
        run(dry_run=_args.dry_run)
