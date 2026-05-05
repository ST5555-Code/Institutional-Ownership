#!/usr/bin/env python3
"""cp_5_adams_phase1_recon.py — Phase 1 read-only reconnaissance.

Surfaces every Adams entity, drift-checks against the PR #278 cohort manifest,
identifies duplicate pairs via X1-normalized canonical_name, captures pre-merge
baselines per entity, and confirms prior CP-4 bridges still persist.

Read-only. ABORTs only at the manifest-drift gate; everything else is print +
proceed so the operator can see the full landscape before authoring the merge
script.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DB = BASE_DIR / "data" / "13f.duckdb"
COHORT_CSV = BASE_DIR / "data" / "working" / "cp-5-bundle-b-adams-cohort.csv"

OPEN_DATE = "9999-12-31"

PRIOR_BRIDGE_IDS = [20813, 20814, 20820, 20821, 20822, 20823]

# Standard X1 corporate-suffix strip set per cp-4b precedent.
SUFFIX_STRIPS = [
    r",?\s+inc\.?$",
    r",?\s+l\.?l\.?c\.?$",
    r",?\s+l\.?p\.?$",
    r",?\s+ltd\.?$",
    r",?\s+limited$",
    r",?\s+co\.?$",
    r",?\s+corp\.?$",
    r",?\s+corporation$",
    r",?\s+/[a-z]{2}/$",
]


def normalize_name(name: str) -> str:
    s = (name or "").strip().lower()
    # collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    # iterative suffix strip until stable
    while True:
        prev = s
        for pat in SUFFIX_STRIPS:
            s = re.sub(pat, "", s, flags=re.IGNORECASE)
        s = s.strip().rstrip(",").strip()
        if s == prev:
            break
    return s


@dataclass
class EntitySnapshot:
    entity_id: int
    canonical_name: str
    entity_type: str
    cik: str | None
    holdings_v2_rows: int = 0
    holdings_v2_aum_usd: float = 0.0
    fh_v2_rollup_rows: int = 0
    fh_v2_rollup_aum_usd: float = 0.0
    fh_v2_dmrollup_rows: int = 0
    fh_v2_entity_id_rows: int = 0
    fh_v2_dmentity_rows: int = 0
    open_ech: int = 0
    open_erh_from: int = 0
    open_erh_at: int = 0
    open_aliases: int = 0
    open_relationships_parent: int = 0
    open_relationships_child: int = 0


def fetch_adams_universe(con: duckdb.DuckDBPyConnection) -> list[EntitySnapshot]:
    rows = con.execute(
        """
        SELECT e.entity_id, e.canonical_name, e.entity_type
        FROM entities e
        WHERE e.canonical_name ILIKE '%Adams%'
           OR e.canonical_name ILIKE 'Adams %'
        ORDER BY e.canonical_name, e.entity_id
        """
    ).fetchall()
    snaps: list[EntitySnapshot] = []
    for eid, name, etype in rows:
        cik_row = con.execute(
            """
            SELECT identifier_value FROM entity_identifiers
            WHERE entity_id = ? AND identifier_type = 'cik'
              AND valid_to = DATE '9999-12-31'
            LIMIT 1
            """,
            [eid],
        ).fetchone()
        cik = cik_row[0] if cik_row else None
        snaps.append(EntitySnapshot(int(eid), name, etype, cik))
    return snaps


def populate_baselines(con: duckdb.DuckDBPyConnection, snap: EntitySnapshot) -> None:
    eid = snap.entity_id

    # holdings_v2 (13F filer footprint)
    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM holdings_v2
        WHERE entity_id = ? AND is_latest = TRUE
        """,
        [eid],
    ).fetchone()
    snap.holdings_v2_rows = int(row[0])
    snap.holdings_v2_aum_usd = float(row[1])

    # fund_holdings_v2 — entity at rollup, dm_rollup, entity_id, dm_entity_id
    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE rollup_entity_id = ? AND is_latest = TRUE
        """,
        [eid],
    ).fetchone()
    snap.fh_v2_rollup_rows = int(row[0])
    snap.fh_v2_rollup_aum_usd = float(row[1])

    snap.fh_v2_dmrollup_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()[0])

    snap.fh_v2_entity_id_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()[0])

    snap.fh_v2_dmentity_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE dm_entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()[0])

    # SCD layer counts
    snap.open_ech = int(con.execute(
        "SELECT COUNT(*) FROM entity_classification_history WHERE entity_id = ? AND valid_to = DATE '9999-12-31'",
        [eid],
    ).fetchone()[0])
    snap.open_erh_from = int(con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND valid_to = DATE '9999-12-31'",
        [eid],
    ).fetchone()[0])
    snap.open_erh_at = int(con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE rollup_entity_id = ? AND valid_to = DATE '9999-12-31'",
        [eid],
    ).fetchone()[0])
    snap.open_aliases = int(con.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = DATE '9999-12-31'",
        [eid],
    ).fetchone()[0])
    snap.open_relationships_parent = int(con.execute(
        "SELECT COUNT(*) FROM entity_relationships WHERE parent_entity_id = ? AND valid_to = DATE '9999-12-31'",
        [eid],
    ).fetchone()[0])
    snap.open_relationships_child = int(con.execute(
        "SELECT COUNT(*) FROM entity_relationships WHERE child_entity_id = ? AND valid_to = DATE '9999-12-31'",
        [eid],
    ).fetchone()[0])


def load_cohort_csv() -> list[dict]:
    with COHORT_CSV.open() as f:
        return [r for r in csv.DictReader(f)]


def main() -> int:
    if not DB.exists():
        print(f"ERROR: db not found: {DB}", file=sys.stderr)
        return 1
    if not COHORT_CSV.exists():
        print(f"ERROR: cohort csv not found: {COHORT_CSV}", file=sys.stderr)
        return 1

    con = duckdb.connect(str(DB), read_only=True)

    # Step 1a — surface all Adams entities
    print("=" * 90)
    print("Step 1a — All Adams entities in DB")
    print("=" * 90)
    snaps = fetch_adams_universe(con)
    for s in snaps:
        print(f"  eid={s.entity_id:>5} type={s.entity_type:<11} cik={(s.cik or '-'):<14} name={s.canonical_name}")
    print(f"\n  Total Adams entities in DB: {len(snaps)}")

    # Step 1b — drift vs manifest
    print("\n" + "=" * 90)
    print("Step 1b — Drift vs PR #278 cohort manifest")
    print("=" * 90)
    cohort_rows = load_cohort_csv()
    cohort_eids = {int(r["entity_id"]) for r in cohort_rows}
    db_eids = {s.entity_id for s in snaps}
    missing_in_db = cohort_eids - db_eids
    new_in_db = db_eids - cohort_eids
    print(f"  manifest entity count: {len(cohort_eids)}")
    print(f"  current DB Adams count: {len(db_eids)}")
    print(f"  missing-in-DB (manifest had, gone now): {sorted(missing_in_db) or 'none'}")
    print(f"  new-in-DB (added since manifest): {sorted(new_in_db) or 'none'}")
    if missing_in_db:
        print("\n  ABORT condition: cohort eids dropped from DB. Manifest is stale.", file=sys.stderr)
        return 2

    # Step 1c — pairing via X1 normalization
    print("\n" + "=" * 90)
    print("Step 1c — Duplicate pairing via X1-normalized canonical_name")
    print("=" * 90)
    cohort_snaps = [s for s in snaps if s.entity_id in cohort_eids]
    for s in cohort_snaps:
        populate_baselines(con, s)

    groups: dict[str, list[EntitySnapshot]] = defaultdict(list)
    for s in cohort_snaps:
        groups[normalize_name(s.canonical_name)].append(s)

    pair_specs: list[tuple[EntitySnapshot, EntitySnapshot]] = []
    for norm_name, members in sorted(groups.items()):
        if len(members) <= 1:
            print(f"  [singleton] '{norm_name}' -> eid={members[0].entity_id}")
            continue
        # Determine canonical via plan's selection rules
        # Rule 1: holdings_v2 active (non-zero rows)
        active = [m for m in members if m.holdings_v2_rows > 0]
        if active:
            # Rule 2: greatest AUM among active
            canonical = max(active, key=lambda m: m.holdings_v2_aum_usd)
        else:
            # Rule 3: prefer fund_holdings_v2 rollup footprint
            with_footprint = [m for m in members if m.fh_v2_rollup_rows > 0]
            if with_footprint:
                canonical = max(with_footprint, key=lambda m: m.fh_v2_rollup_rows)
            else:
                # Rule 4: lowest eid
                canonical = min(members, key=lambda m: m.entity_id)
        duplicates = [m for m in members if m.entity_id != canonical.entity_id]
        print(f"\n  [GROUP] '{norm_name}' ({len(members)} entities)")
        print(f"    CANONICAL: eid={canonical.entity_id} type={canonical.entity_type} cik={canonical.cik or '-'}")
        print(f"               h_v2_rows={canonical.holdings_v2_rows:,} aum=${canonical.holdings_v2_aum_usd/1e9:,.2f}B "
              f"fh_rollup_rows={canonical.fh_v2_rollup_rows:,} fh_entity_rows={canonical.fh_v2_entity_id_rows:,}")
        for d in duplicates:
            print(f"    DUPLICATE: eid={d.entity_id} type={d.entity_type} cik={d.cik or '-'}")
            print(f"               h_v2_rows={d.holdings_v2_rows:,} aum=${d.holdings_v2_aum_usd/1e9:,.2f}B "
                  f"fh_rollup_rows={d.fh_v2_rollup_rows:,} fh_entity_rows={d.fh_v2_entity_id_rows:,}")
            pair_specs.append((canonical, d))

    print(f"\n  Total pairs to merge: {len(pair_specs)}")

    # Step 1d — pre-merge baselines for cohort entities (already populated)
    print("\n" + "=" * 90)
    print("Step 1d — Per-entity SCD layer baselines (cohort)")
    print("=" * 90)
    for s in cohort_snaps:
        print(
            f"  eid={s.entity_id:>5} type={s.entity_type:<11} "
            f"h_v2={s.holdings_v2_rows:>4} fh_rollup={s.fh_v2_rollup_rows:>4} "
            f"fh_dmrollup={s.fh_v2_dmrollup_rows:>4} fh_entity={s.fh_v2_entity_id_rows:>4} "
            f"fh_dmentity={s.fh_v2_dmentity_rows:>4} ech={s.open_ech} "
            f"erh_from={s.open_erh_from} erh_at={s.open_erh_at} "
            f"aliases={s.open_aliases} rel_p={s.open_relationships_parent} "
            f"rel_c={s.open_relationships_child}"
        )

    # Step 1e — entity_relationships baseline
    print("\n" + "=" * 90)
    print("Step 1e — entity_relationships global baseline")
    print("=" * 90)
    open_rel = con.execute(
        "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = DATE '9999-12-31'"
    ).fetchone()[0]
    max_rel_id = con.execute(
        "SELECT MAX(relationship_id) FROM entity_relationships"
    ).fetchone()[0]
    print(f"  open relationships: {open_rel:,}")
    print(f"  max relationship_id: {max_rel_id}")
    print(f"  Op E will allocate sequential MAX+1..MAX+N: {max_rel_id+1}..{max_rel_id+len(pair_specs)}")

    # Step 1f — confirm prior CP-4 bridges
    print("\n" + "=" * 90)
    print("Step 1f — Prior CP-4 bridges sanity")
    print("=" * 90)
    prior_rows = con.execute(
        "SELECT relationship_id FROM entity_relationships WHERE relationship_id IN ?",
        [PRIOR_BRIDGE_IDS],
    ).fetchall()
    found = {int(r[0]) for r in prior_rows}
    expected = set(PRIOR_BRIDGE_IDS)
    print(f"  expected: {sorted(expected)}")
    print(f"  found:    {sorted(found)}")
    missing = expected - found
    if missing:
        print(f"  ABORT: missing CP-4 bridges {sorted(missing)}", file=sys.stderr)
        return 3
    print("  All 6 prior CP-4 bridges present.")

    # Total cohort row footprint (sanity vs "120-row finding")
    print("\n" + "=" * 90)
    print("Aggregate cohort footprint (sanity vs '120-row' finding)")
    print("=" * 90)
    duplicate_eids = [d.entity_id for _, d in pair_specs]
    if duplicate_eids:
        rows_in_holdings_v2 = con.execute(
            "SELECT COUNT(*) FROM holdings_v2 WHERE entity_id IN ? AND is_latest = TRUE",
            [duplicate_eids],
        ).fetchone()[0]
        rows_in_fhv2 = con.execute(
            """
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE (rollup_entity_id IN ? OR dm_rollup_entity_id IN ?
                OR entity_id IN ? OR dm_entity_id IN ?) AND is_latest = TRUE
            """,
            [duplicate_eids, duplicate_eids, duplicate_eids, duplicate_eids],
        ).fetchone()[0]
        ech_rows = con.execute(
            "SELECT COUNT(*) FROM entity_classification_history WHERE entity_id IN ?",
            [duplicate_eids],
        ).fetchone()[0]
        erh_rows = con.execute(
            """
            SELECT COUNT(*) FROM entity_rollup_history
            WHERE entity_id IN ? OR rollup_entity_id IN ?
            """,
            [duplicate_eids, duplicate_eids],
        ).fetchone()[0]
        ea_rows = con.execute(
            "SELECT COUNT(*) FROM entity_aliases WHERE entity_id IN ?",
            [duplicate_eids],
        ).fetchone()[0]
        er_rows = con.execute(
            """
            SELECT COUNT(*) FROM entity_relationships
            WHERE parent_entity_id IN ? OR child_entity_id IN ?
            """,
            [duplicate_eids, duplicate_eids],
        ).fetchone()[0]
        ei_rows = con.execute(
            "SELECT COUNT(*) FROM entity_identifiers WHERE entity_id IN ?",
            [duplicate_eids],
        ).fetchone()[0]
        print(f"  duplicate eids: {duplicate_eids}")
        print(f"  holdings_v2 rows: {rows_in_holdings_v2}")
        print(f"  fund_holdings_v2 rows (any reference): {rows_in_fhv2}")
        print(f"  entity_classification_history rows: {ech_rows}")
        print(f"  entity_rollup_history rows (entity_id or rollup_entity_id): {erh_rows}")
        print(f"  entity_aliases rows: {ea_rows}")
        print(f"  entity_relationships rows: {er_rows}")
        print(f"  entity_identifiers rows: {ei_rows}")
        total = rows_in_holdings_v2 + rows_in_fhv2 + ech_rows + erh_rows + ea_rows + er_rows + ei_rows
        print(f"  TOTAL row footprint: {total}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
