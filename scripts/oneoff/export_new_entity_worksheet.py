#!/usr/bin/env python3
"""export_new_entity_worksheet.py — int-21 new-entity creation worksheet.

READ-ONLY. Consumes the offline-triaged file
``unresolved_series_triage_resolved.csv`` (Serge's decisions), filters to rows
where ``decision = 'NEW_ENTITY'``, and emits one row per distinct ``filer_cik``
with context pre-filled from the database so Serge can complete entity
metadata offline.

Output columns (per distinct CIK):
  - filer_cik              (pre-filled, zero-padded 10-digit)
  - filer_name             (managers.manager_name, else triage family_name)
  - inst_parent_name       (managers.parent_name, blank if missing)
  - series_count           (count of NEW_ENTITY series for this CIK)
  - total_nav              (sum of total_nav across those series, USD string)
  - series_names_sample    (first 5 series names, "... and N more" suffix)
  - entity_name            (pre-filled = filer_name; Serge edits)
  - manager_type           (BLANK — Serge fills)
  - is_passive             (BLANK — Serge fills)
  - rollup_target          (parent entity_id if parent match found, else SELF)

Usage:
    python scripts/oneoff/export_new_entity_worksheet.py
    python scripts/oneoff/export_new_entity_worksheet.py \\
        --triage /path/to/unresolved_series_triage_resolved.csv \\
        --db data/13f.duckdb \\
        --output data/reports/new_entity_worksheet.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB  # noqa: E402

DEFAULT_TRIAGE = os.path.expanduser(
    "~/Downloads/unresolved_series_triage_resolved.csv"
)
OUTPUT_REL = os.path.join("data", "reports", "new_entity_worksheet.csv")

NEW_ENTITY_DECISION = "NEW_ENTITY"


def _norm_cik(raw: str | None) -> str | None:
    """Return a 10-digit zero-padded CIK, or None if input is empty/invalid."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    if not s.isdigit():
        return None
    return s.zfill(10)


def _fmt_dollars(v: float | None) -> str:
    if v is None:
        return ""
    return f"${v:,.0f}"


def _series_sample(names: list[str], limit: int = 5) -> str:
    clean = [n for n in names if n]
    if not clean:
        return ""
    if len(clean) <= limit:
        return " | ".join(clean)
    head = " | ".join(clean[:limit])
    return f"{head} | ... and {len(clean) - limit} more"


def _load_triage(triage_path: str) -> list[dict]:
    with open(triage_path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("decision") == NEW_ENTITY_DECISION]


def _aggregate_by_cik(new_entity_rows: list[dict]) -> dict[str, dict]:
    """Group the filtered triage rows by normalized filer_cik."""
    buckets: dict[str, dict] = {}
    for r in new_entity_rows:
        cik = _norm_cik(r.get("filer_cik"))
        if cik is None:
            continue
        bucket = buckets.setdefault(
            cik,
            {
                "filer_cik": cik,
                "triage_filer_names": set(),
                "triage_parent_names": set(),
                "family_names": set(),
                "series_names": [],
                "series_ids": [],
                "total_nav": 0.0,
            },
        )
        if r.get("filer_name"):
            bucket["triage_filer_names"].add(r["filer_name"].strip())
        if r.get("inst_parent_name"):
            bucket["triage_parent_names"].add(r["inst_parent_name"].strip())
        if r.get("family_name"):
            bucket["family_names"].add(r["family_name"].strip())
        sn = (r.get("series_name") or "").strip()
        if sn:
            bucket["series_names"].append(sn)
        sid = (r.get("series_id") or "").strip()
        if sid:
            bucket["series_ids"].append(sid)
        nav = r.get("total_nav")
        try:
            bucket["total_nav"] += float(nav) if nav not in (None, "") else 0.0
        except ValueError:
            pass
    return buckets


def _enrich_from_db(
    con: duckdb.DuckDBPyConnection, ciks: list[str]
) -> tuple[dict[str, dict], dict[str, int], dict[str, int]]:
    """Return (manager_by_cik, existing_entity_by_cik, parent_entity_id_by_name).

    * manager_by_cik: manager_name, parent_name for each filer_cik if present.
    * existing_entity_by_cik: entity_id if entity_identifiers already has
      (type='cik', value=cik). Should be empty for a clean NEW_ENTITY set.
    * parent_entity_id_by_name: display_name (upper) -> entity_id, for every
      entity_current row that some other entity rolls up to. Used to match
      filer_name/family_name to a known parent for rollup_target pre-fill.
    """
    if not ciks:
        return {}, {}, {}

    placeholders = ",".join(["?"] * len(ciks))
    manager_rows = con.execute(
        f"SELECT cik, manager_name, parent_name FROM managers WHERE cik IN ({placeholders})",
        ciks,
    ).fetchall()
    manager_by_cik = {
        r[0]: {"manager_name": r[1], "parent_name": r[2]} for r in manager_rows
    }

    ei_rows = con.execute(
        f"""SELECT identifier_value, entity_id FROM entity_identifiers
            WHERE identifier_type = 'cik' AND identifier_value IN ({placeholders})""",
        ciks,
    ).fetchall()
    existing_entity_by_cik = {r[0]: r[1] for r in ei_rows}

    # Build parent-candidate lookup: any entity that is someone's rollup target.
    parent_rows = con.execute(
        """
        SELECT DISTINCT ec.entity_id, UPPER(TRIM(ec.display_name)) AS name_u
        FROM entity_current ec
        WHERE ec.entity_id IN (SELECT DISTINCT rollup_entity_id
                               FROM entity_current
                               WHERE rollup_entity_id IS NOT NULL)
          AND ec.display_name IS NOT NULL
        """
    ).fetchall()
    parent_entity_id_by_name: dict[str, int] = {}
    for entity_id, name_u in parent_rows:
        if name_u and name_u not in parent_entity_id_by_name:
            parent_entity_id_by_name[name_u] = entity_id

    return manager_by_cik, existing_entity_by_cik, parent_entity_id_by_name


def _pick(*values: str | None) -> str:
    for v in values:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def build_worksheet_rows(
    buckets: dict[str, dict],
    manager_by_cik: dict[str, dict],
    existing_entity_by_cik: dict[str, int],
    parent_entity_id_by_name: dict[str, int],
) -> list[dict]:
    out: list[dict] = []
    for cik, b in buckets.items():
        m = manager_by_cik.get(cik) or {}
        triage_filer = next(iter(b["triage_filer_names"]), "")
        triage_parent = next(iter(b["triage_parent_names"]), "")
        family_name = next(iter(b["family_names"]), "")

        filer_name = _pick(m.get("manager_name"), triage_filer, family_name)
        inst_parent = _pick(m.get("parent_name"), triage_parent)

        # known_parent_check: try filer_name, then inst_parent, then family
        rollup_entity_id: int | None = None
        for cand in (filer_name, inst_parent, family_name):
            if not cand:
                continue
            key = cand.upper().strip()
            if key in parent_entity_id_by_name:
                rollup_entity_id = parent_entity_id_by_name[key]
                break

        rollup_target = str(rollup_entity_id) if rollup_entity_id is not None else "SELF"

        out.append(
            {
                "filer_cik": cik,
                "filer_name": filer_name,
                "inst_parent_name": inst_parent,
                "series_count": len(b["series_ids"]),
                "total_nav": _fmt_dollars(b["total_nav"]),
                "total_nav_numeric": b["total_nav"],
                "series_names_sample": _series_sample(b["series_names"]),
                "entity_name": filer_name,
                "manager_type": "",
                "is_passive": "",
                "rollup_target": rollup_target,
                "existing_entity_id": existing_entity_by_cik.get(cik, ""),
            }
        )

    out.sort(key=lambda r: r["total_nav_numeric"], reverse=True)
    return out


OUTPUT_COLUMNS = [
    "filer_cik",
    "filer_name",
    "inst_parent_name",
    "series_count",
    "total_nav",
    "series_names_sample",
    "entity_name",
    "manager_type",
    "is_passive",
    "rollup_target",
    "existing_entity_id",
]


def write_csv(rows: list[dict], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run(triage_path: str, db_path: str, output_path: str) -> list[dict]:
    if not os.path.exists(triage_path):
        raise FileNotFoundError(f"Triage CSV not found: {triage_path}")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB not found: {db_path}")

    ne_rows = _load_triage(triage_path)
    total_ne_series = len(ne_rows)

    buckets = _aggregate_by_cik(ne_rows)
    ciks = sorted(buckets.keys())

    con = duckdb.connect(db_path, read_only=True)
    try:
        manager_by_cik, existing_by_cik, parent_by_name = _enrich_from_db(con, ciks)
    finally:
        con.close()

    rows = build_worksheet_rows(buckets, manager_by_cik, existing_by_cik, parent_by_name)
    write_csv(rows, output_path)

    _print_summary(total_ne_series, rows, output_path)
    return rows


def _print_summary(total_ne_series: int, rows: list[dict], output_path: str) -> None:
    distinct = len(rows)
    pre_filled_parent = sum(1 for r in rows if r["rollup_target"] != "SELF")
    already_existing = sum(1 for r in rows if r["existing_entity_id"] != "")

    print(f"Wrote {distinct} rows → {output_path}")
    print(f"Total NEW_ENTITY series: {total_ne_series}")
    print(f"Distinct filer_cik (worksheet rows): {distinct}")
    print(f"Pre-filled rollup_target (known parent match): {pre_filled_parent}")
    print(f"WARNING: already-existing entity rows: {already_existing}")

    print("\nTop 5 by total_nav:")
    for r in rows[:5]:
        name = r["filer_name"] or "(unknown)"
        print(
            f"  {r['total_nav']:>20s}  cik={r['filer_cik']}  "
            f"name={name[:50]:<50s}  series={r['series_count']}"
        )

    if pre_filled_parent:
        print(f"\nCIKs with known parent matches (top 10 of {pre_filled_parent}):")
        shown = 0
        for r in rows:
            if r["rollup_target"] == "SELF":
                continue
            print(
                f"  cik={r['filer_cik']}  parent_entity_id={r['rollup_target']}  "
                f"filer={r['filer_name'][:40]}"
            )
            shown += 1
            if shown >= 10:
                break


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--triage",
        default=DEFAULT_TRIAGE,
        help=f"Path to Serge's triage CSV (default: {DEFAULT_TRIAGE}).",
    )
    parser.add_argument(
        "--db",
        default=PROD_DB,
        help=f"Path to DuckDB (default: {PROD_DB}).",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(BASE_DIR, OUTPUT_REL),
        help=f"Output CSV path (default: <repo>/{OUTPUT_REL}).",
    )
    args = parser.parse_args()
    run(args.triage, args.db, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
