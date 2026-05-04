#!/usr/bin/env python3
"""cp_4b_author_fmr.py — CP-4b-author-fmr: single-brand AUTHOR_NEW_BRIDGE.

Inserts one entity_relationships row bridging Fidelity / FMR brand
eid=11 to filer eid=10443 (FMR LLC) via wholly_owned/control.

Pairing source: cp-4b-blocker2-corroboration-probe Bucket C (X2
alias-only match with raw-string identical alias on both eids),
MEDIUM confidence, public-record verified per
docs/findings/cp-4b-blocker2-corroboration-probe.md §6/§7
(Bucket C carve-out predicate: brand_alias-shape brands where X2
alone fires with raw-string identical aliases on both sides).
Fund AUM bridged: ~$415.3B.

Standard CP-4b BRIDGE shape per PR #267 (cp-4b-author-trowe) and
PR #269 (cp-4b-author-first-trust) precedent. Pure new-row INSERT.
No fund_holdings_v2 re-point, no SCD closure on brand eid, no
recompute pipelines. peer_rotation_flows expected delta 0. Brand
eid stays alive; bridge metadata only.

Direct prod write per docs/decisions/inst_eid_bridge_decisions.md
(staging-workflow note: CP-4a + CP-4b-blackrock + CP-4b-trowe +
CP-4b-first-trust precedent).

Hard guards (--confirm):
  - Brand and filer entity rows present, both entity_type='institution'.
  - No existing open bridge between (10443, 11).
  - Filer 10443 hv2 presence non-zero.
  - Planned relationship_id does not collide.
  - BEGIN/COMMIT wrap; ROLLBACK on any constraint violation.
  - Post-INSERT: row count delta = +1 and pair-specific count = 1.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "cp-4b-author-fmr-manifest.csv"

OPEN_DATE = date(9999, 12, 31)

FILER_EID = 10443
BRAND_EID = 11
PAIR_NO = 1

PAIRING_SOURCE = "cp-4b-corroboration-probe-bucket-C"
CONFIDENCE = "MEDIUM"
SIGNALS = "X2"
PUBLIC_RECORD_REF = "cp-4b-blocker2-corroboration-probe.md_§7"


def _build_source(pair_no: int) -> str:
    return (
        f"CP-4b-author-fmr|pair={pair_no}|"
        f"pairing_source={PAIRING_SOURCE}|confidence={CONFIDENCE}|"
        f"signals={SIGNALS}|public_record_verified={PUBLIC_RECORD_REF}"
    )


@dataclass
class BridgePair:
    pair_no: int
    brand_eid: int
    brand_label: str

    brand_canonical_name: str = ""
    brand_entity_type: str = ""
    fund_rows: int = 0
    fund_aum_usd: float = 0.0
    open_ech: int = 0
    open_erh: int = 0
    open_aliases: int = 0
    open_relationships: int = 0
    existing_bridge_count: int = 0

    new_relationship_id: int = 0


PAIR = BridgePair(pair_no=PAIR_NO, brand_eid=BRAND_EID, brand_label="Fidelity / FMR")


def capture_filer(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id = ?",
        [FILER_EID],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"filer eid={FILER_EID} missing from entities")
    name, etype = row
    if etype != "institution":
        raise RuntimeError(f"filer eid={FILER_EID} entity_type={etype!r} (expected 'institution')")
    hv2 = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0) FROM holdings_v2 "
        "WHERE entity_id = ? AND is_latest = TRUE",
        [FILER_EID],
    ).fetchone()
    if int(hv2[0]) == 0:
        raise RuntimeError(f"filer eid={FILER_EID} has zero hv2 presence")
    return {
        "canonical_name": name,
        "entity_type": etype,
        "hv2_rows": int(hv2[0]),
        "hv2_aum_usd": float(hv2[1]),
    }


def capture_preimage(con: duckdb.DuckDBPyConnection, p: BridgePair) -> None:
    row = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id = ?",
        [p.brand_eid],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"[{p.brand_label}] brand_eid={p.brand_eid} missing from entities")
    p.brand_canonical_name, p.brand_entity_type = row
    if p.brand_entity_type != "institution":
        raise RuntimeError(
            f"[{p.brand_label}] brand_eid={p.brand_eid} entity_type={p.brand_entity_type!r} "
            "(expected 'institution')"
        )

    fh = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.brand_eid, p.brand_eid],
    ).fetchone()
    p.fund_rows = int(fh[0])
    p.fund_aum_usd = float(fh[1])

    p.open_ech = con.execute(
        "SELECT COUNT(*) FROM entity_classification_history "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    p.open_erh = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    p.open_aliases = con.execute(
        "SELECT COUNT(*) FROM entity_aliases "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    p.open_relationships = con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE (parent_entity_id = ? OR child_entity_id = ?) AND valid_to = ?",
        [p.brand_eid, p.brand_eid, OPEN_DATE],
    ).fetchone()[0]

    if p.open_ech == 0 and p.open_erh == 0 and p.open_aliases == 0:
        raise RuntimeError(
            f"[{p.brand_label}] brand_eid={p.brand_eid} has no open SCD rows — effectively closed"
        )

    p.existing_bridge_count = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = ?
          AND ( (parent_entity_id = ? AND child_entity_id = ?)
             OR (parent_entity_id = ? AND child_entity_id = ?) )
        """,
        [OPEN_DATE, FILER_EID, p.brand_eid, p.brand_eid, FILER_EID],
    ).fetchone()[0]
    if p.existing_bridge_count != 0:
        raise RuntimeError(
            f"[{p.brand_label}] open bridge to filer {FILER_EID} already exists "
            f"({p.existing_bridge_count} rows). Pair is TRUE_BRIDGE_ENCODED — exclude."
        )


def write_manifest(p: BridgePair, filer: dict, prepared_rel_id: int) -> None:
    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "pair",
        "parent_entity_id",
        "child_entity_id",
        "parent_canonical_name",
        "child_canonical_name",
        "relationship_type",
        "control_type",
        "source",
        "confidence",
        "fund_aum_billions",
        "prepared_relationship_id",
    ]
    with MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerow(
            [
                p.pair_no,
                FILER_EID,
                p.brand_eid,
                filer["canonical_name"],
                p.brand_canonical_name,
                "wholly_owned",
                "control",
                _build_source(p.pair_no),
                "medium",
                f"{p.fund_aum_usd / 1e9:.4f}",
                prepared_rel_id,
            ]
        )


def execute_pair(con: duckdb.DuckDBPyConnection, p: BridgePair, new_id: int) -> None:
    today = date.today()
    src = _build_source(p.pair_no)
    con.execute(
        """
        INSERT INTO entity_relationships
            (relationship_id, parent_entity_id, child_entity_id,
             relationship_type, control_type, is_primary, primary_parent_key,
             confidence, source, is_inferred, valid_from, valid_to,
             created_at, last_refreshed_at)
        VALUES (?, ?, ?, 'wholly_owned', 'control', TRUE, ?,
                'medium', ?, FALSE, ?, ?, NOW(), NOW())
        """,
        [new_id, FILER_EID, p.brand_eid, FILER_EID, src, today, OPEN_DATE],
    )
    p.new_relationship_id = new_id

    cnt = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE parent_entity_id = ? AND child_entity_id = ?
          AND relationship_type = 'wholly_owned'
          AND control_type = 'control'
          AND valid_to = ?
        """,
        [FILER_EID, p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    if cnt != 1:
        raise RuntimeError(
            f"[{p.brand_label}] post-INSERT sanity-check failed: "
            f"{cnt} open wholly_owned rows from {FILER_EID} to {p.brand_eid} (expected 1)"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to 13f.duckdb")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="Read-only manifest emit")
    grp.add_argument("--confirm", action="store_true", help="Execute the INSERT")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            filer = capture_filer(con)
            capture_preimage(con, PAIR)
            max_rel_id = int(
                con.execute("SELECT MAX(relationship_id) FROM entity_relationships").fetchone()[0]
            )
            open_rels_pre = int(
                con.execute(
                    "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = ?",
                    [OPEN_DATE],
                ).fetchone()[0]
            )
        finally:
            con.close()
        prepared = max_rel_id + 1
        write_manifest(PAIR, filer, prepared)
        print(f"[dry-run] manifest: {MANIFEST_CSV}")
        print(
            f"[dry-run] pair {PAIR.pair_no}: brand eid={PAIR.brand_eid} "
            f"({PAIR.brand_canonical_name}) -> filer eid={FILER_EID} "
            f"({filer['canonical_name']})"
        )
        print(
            f"[dry-run] fund AUM bridged: ${PAIR.fund_aum_usd / 1e9:,.2f}B "
            f"({PAIR.fund_rows:,} rows)"
        )
        print(
            f"[dry-run] open relationships baseline: {open_rels_pre:,}; "
            f"max relationship_id: {max_rel_id:,}; prepared new id: {prepared:,}"
        )
        print(f"[dry-run] existing bridge count (must be 0): {PAIR.existing_bridge_count}")
        print(f"[dry-run] source string: {_build_source(PAIR.pair_no)}")
        return 0

    con = duckdb.connect(str(db_path), read_only=False)
    try:
        filer = capture_filer(con)
        capture_preimage(con, PAIR)

        if MANIFEST_CSV.exists():
            with MANIFEST_CSV.open() as f:
                rows = list(csv.DictReader(f))
            if len(rows) != 1:
                raise RuntimeError(f"manifest expected 1 row, got {len(rows)}")
            m = rows[0]
            if int(m["parent_entity_id"]) != FILER_EID or int(m["child_entity_id"]) != BRAND_EID:
                raise RuntimeError(
                    f"manifest pair mismatch: manifest=({m['parent_entity_id']},"
                    f"{m['child_entity_id']}) script=({FILER_EID},{BRAND_EID})"
                )

        pre_count = int(con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0])
        pre_open = int(
            con.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = ?", [OPEN_DATE]
            ).fetchone()[0]
        )
        pre_max = int(
            con.execute("SELECT MAX(relationship_id) FROM entity_relationships").fetchone()[0]
        )
        new_id = pre_max + 1

        exists = int(
            con.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE relationship_id = ?",
                [new_id],
            ).fetchone()[0]
        )
        if exists != 0:
            raise RuntimeError(f"prepared relationship_id={new_id} already exists")

        con.execute("BEGIN")
        try:
            execute_pair(con, PAIR, new_id)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        post_count = int(con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0])
        post_open = int(
            con.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = ?", [OPEN_DATE]
            ).fetchone()[0]
        )
        post_max = int(
            con.execute("SELECT MAX(relationship_id) FROM entity_relationships").fetchone()[0]
        )

        if post_count - pre_count != 1:
            raise RuntimeError(f"row count delta {post_count - pre_count} != 1")
        if post_open - pre_open != 1:
            raise RuntimeError(f"open-row delta {post_open - pre_open} != 1")
        if post_max != pre_max + 1:
            raise RuntimeError(f"max relationship_id post={post_max} != pre+1={pre_max + 1}")

        print(f"[confirm] DONE — relationship_id={new_id}")
        print(f"[confirm] entity_relationships rows: {pre_count:,} -> {post_count:,} (Δ +1)")
        print(f"[confirm] open relationships: {pre_open:,} -> {post_open:,} (Δ +1)")
        print(f"[confirm] max(relationship_id): {pre_max:,} -> {post_max:,}")
        print(
            f"[confirm] bridged fund AUM: ${PAIR.fund_aum_usd / 1e9:,.2f}B "
            f"({PAIR.fund_rows:,} rows)"
        )
        print(f"[confirm] source: {_build_source(PAIR.pair_no)}")
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
