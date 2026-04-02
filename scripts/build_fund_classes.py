#!/usr/bin/env python3
"""
build_fund_classes.py — Extract share class (C-number) data from cached N-PORT XMLs.

Builds the fund_classes table from class IDs found in N-PORT filings.
Also extracts LEI data from N-PORT (leiOfSeries / seriesLei).

Run: python3 scripts/build_fund_classes.py
"""

import glob
import os
import sys
from datetime import datetime

import duckdb
from lxml import etree

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")
RAW_DIR = os.path.join(BASE_DIR, "data", "nport_raw")
NS = {"n": "http://www.sec.gov/edgar/nport"}


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
    """Extract class IDs and LEI from a cached N-PORT XML."""
    try:
        root = etree.parse(xml_path).getroot()
    except Exception:
        return None, None, None

    # Series info
    series_id = root.findtext(".//n:seriesId", namespaces=NS) or ""
    series_name = root.findtext(".//n:seriesName", namespaces=NS) or ""
    series_lei = root.findtext(".//n:seriesLei", namespaces=NS) or ""
    reg_cik = root.findtext(".//n:regCik", namespaces=NS) or ""
    rep_date = root.findtext(".//n:repPdDate", namespaces=NS) or ""

    # Class IDs
    class_ids = [c.text.strip() for c in root.findall(".//n:classId", NS) if c.text]

    # Fund-level LEI
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


def run():
    con = duckdb.connect(DB_PATH)
    create_tables(con)

    # Find all cached N-PORT XMLs
    xml_files = glob.glob(os.path.join(RAW_DIR, "*", "*.xml"))
    print(f"Found {len(xml_files)} cached N-PORT XMLs")

    # Get already-processed series+quarter combos
    existing = set()
    try:
        rows = con.execute("SELECT series_id, class_id FROM fund_classes").fetchall()
        existing = {(r[0], r[1]) for r in rows}
    except Exception:
        pass

    classes_added = 0
    leis_added = 0
    lei_cache = set()
    now = datetime.now().isoformat()

    for i, xml_path in enumerate(xml_files):
        if (i + 1) % 5000 == 0:
            print(f"  [{i+1}/{len(xml_files)}] {classes_added} classes, {leis_added} LEIs...")
            con.execute("CHECKPOINT")

        result, series_lei, reg_lei = parse_xml_for_classes(xml_path)
        if not result or not result["series_id"]:
            continue

        series_id = result["series_id"]

        # Insert class IDs
        for class_id in result["class_ids"]:
            if (series_id, class_id) not in existing:
                con.execute("""
                    INSERT INTO fund_classes (series_id, class_id, fund_cik, fund_name, report_date, quarter, loaded_at)
                    VALUES (?, ?, ?, ?, TRY_CAST(? AS DATE), NULL, ?)
                """, [series_id, class_id, result["reg_cik"], result["series_name"],
                      result["report_date"], now])
                existing.add((series_id, class_id))
                classes_added += 1

        # Insert LEIs
        if series_lei and series_lei not in lei_cache:
            try:
                con.execute("""
                    INSERT OR REPLACE INTO lei_reference (lei, entity_name, entity_type, series_id, fund_cik, updated_at)
                    VALUES (?, ?, 'fund_series', ?, ?, ?)
                """, [series_lei, result["series_name"], series_id, result["reg_cik"], now])
                lei_cache.add(series_lei)
                leis_added += 1
            except Exception:
                pass

    con.execute("CHECKPOINT")

    # Also add LEI to fund_holdings table if not already present
    try:
        con.execute("ALTER TABLE fund_holdings ADD COLUMN lei VARCHAR")
        print("  Added lei column to fund_holdings")
    except Exception:
        pass

    # Update fund_holdings.lei from lei_reference
    con.execute("""
        UPDATE fund_holdings
        SET lei = lr.lei
        FROM lei_reference lr
        WHERE fund_holdings.series_id = lr.series_id
          AND fund_holdings.lei IS NULL
    """)
    updated_lei = con.execute("SELECT COUNT(*) FROM fund_holdings WHERE lei IS NOT NULL").fetchone()[0]

    # Summary
    total_classes = con.execute("SELECT COUNT(*) FROM fund_classes").fetchone()[0]
    total_leis = con.execute("SELECT COUNT(*) FROM lei_reference").fetchone()[0]
    unique_series = con.execute("SELECT COUNT(DISTINCT series_id) FROM fund_classes").fetchone()[0]

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Fund classes: {total_classes} (new: {classes_added})")
    print(f"Unique series with classes: {unique_series}")
    print(f"LEI references: {total_leis} (new: {leis_added})")
    print(f"fund_holdings with LEI: {updated_lei:,}")

    # Test: Fidelity Contrafund classes
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

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    run()
