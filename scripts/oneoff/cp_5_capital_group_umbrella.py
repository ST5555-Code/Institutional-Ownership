#!/usr/bin/env python3
"""cp_5_capital_group_umbrella.py — CP-5-pre: bridge 3 Capital Group filer arms.

Authors 3 entity_relationships rows bridging the Capital Group umbrella
(eid=12, "Capital Group / American Funds") to its 3 13F filer arms via
wholly_owned/control. Path A locked per Bundle B §1.3 explicit naming.

Arms (canonical eid-ascending order):
  pair 1: eid 12 -> 6657  (Capital World Investors,           CIK 0001422849)
  pair 2: eid 12 -> 7125  (Capital Research Global Investors, CIK 0001422848)
  pair 3: eid 12 -> 7136  (Capital International Investors,   CIK 0001562230)

NO MERGE OPS. The 3 filer arms remain as independent visible entities
(they file 13F under different CIKs and stay that way). This PR is
purely additive — entity_relationships rows only.

Two-relationship-layer coexistence per chat decision 2026-05-05: the
existing parent_bridge / advisory layer (eid=12 has 87 such rows) stays
untouched. The new wholly_owned / control rows add the corporate
ownership layer on top. Both serve distinct queries (sponsor-view vs
ownership-view); they are not redundant.

Standard CP-4b BRIDGE shape per PR #271 (cp-4b-author-ssga most recent):
14-column INSERT, is_primary=TRUE, primary_parent_key=<parent_eid>,
confidence='high' (Bundle B Path A naming is explicit, not inferred).

Hard guards (--confirm):
  - Umbrella + 3 arm entity rows present, all entity_type='institution'.
  - 0 existing open wholly_owned/control bridges between umbrella and
    any of the 3 arms (additivity check).
  - Cross-arm relationships count = 0.
  - 3 prepared relationship_ids do not collide.
  - BEGIN/COMMIT wrap; ROLLBACK on any constraint violation.
  - Post-INSERT: row count delta = +3, open-row delta = +3,
    MAX(relationship_id) post = pre+3.
  - Per-arm hv2 AUM unchanged (BRIDGE does not re-point holdings).
  - Per-arm fund_holdings_v2 rollup AUM unchanged.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "cp-5-capital-group-umbrella-manifest.csv"

OPEN_DATE = date(9999, 12, 31)
UMBRELLA_EID = 12
PUBLIC_RECORD_REF = "cp-5-bundle-b-discovery.md_§1.3"
PATH = "Path A"


@dataclass
class BridgePair:
    pair_no: int
    arm_eid: int

    arm_canonical_name: str = ""
    arm_entity_type: str = ""
    hv2_rows: int = 0
    hv2_aum_usd: float = 0.0
    fh2_rollup_rows: int = 0
    fh2_rollup_aum_usd: float = 0.0
    existing_control_bridge_count: int = 0

    new_relationship_id: int = 0


PAIRS = [
    BridgePair(pair_no=1, arm_eid=6657),
    BridgePair(pair_no=2, arm_eid=7125),
    BridgePair(pair_no=3, arm_eid=7136),
]


def _build_source(arm_canonical_name: str) -> str:
    return (
        f"CP-5-pre:cp-5-capital-group-umbrella"
        f"|arm={arm_canonical_name}"
        f"|{PATH}"
        f"|coexists_with_parent_bridge_layer"
        f"|public_record_verified={PUBLIC_RECORD_REF}"
    )


def capture_umbrella(con: duckdb.DuckDBPyConnection) -> Dict[str, object]:
    row = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id = ?",
        [UMBRELLA_EID],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"umbrella eid={UMBRELLA_EID} missing from entities")
    name, etype = row
    if etype != "institution":
        raise RuntimeError(
            f"umbrella eid={UMBRELLA_EID} entity_type={etype!r} (expected 'institution')"
        )
    return {"canonical_name": name, "entity_type": etype}


def capture_arm_preimage(con: duckdb.DuckDBPyConnection, p: BridgePair) -> None:
    row = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id = ?",
        [p.arm_eid],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"[pair {p.pair_no}] arm_eid={p.arm_eid} missing from entities")
    p.arm_canonical_name, p.arm_entity_type = row
    if p.arm_entity_type != "institution":
        raise RuntimeError(
            f"[pair {p.pair_no}] arm_eid={p.arm_eid} entity_type={p.arm_entity_type!r} "
            "(expected 'institution')"
        )

    hv2 = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0) FROM holdings_v2 "
        "WHERE entity_id = ? AND is_latest = TRUE",
        [p.arm_eid],
    ).fetchone()
    p.hv2_rows = int(hv2[0])
    p.hv2_aum_usd = float(hv2[1])
    if p.hv2_rows == 0:
        raise RuntimeError(f"[pair {p.pair_no}] arm_eid={p.arm_eid} has zero hv2 presence")

    fh = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.arm_eid, p.arm_eid],
    ).fetchone()
    p.fh2_rollup_rows = int(fh[0])
    p.fh2_rollup_aum_usd = float(fh[1])

    p.existing_control_bridge_count = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = ?
          AND relationship_type = 'wholly_owned'
          AND control_type = 'control'
          AND ( (parent_entity_id = ? AND child_entity_id = ?)
             OR (parent_entity_id = ? AND child_entity_id = ?) )
        """,
        [OPEN_DATE, UMBRELLA_EID, p.arm_eid, p.arm_eid, UMBRELLA_EID],
    ).fetchone()[0]
    if p.existing_control_bridge_count != 0:
        raise RuntimeError(
            f"[pair {p.pair_no}] open wholly_owned/control bridge between "
            f"{UMBRELLA_EID} and {p.arm_eid} already exists "
            f"({p.existing_control_bridge_count} rows). Pair already authored — abort."
        )


def assert_no_cross_arm(con: duckdb.DuckDBPyConnection) -> None:
    arms = [p.arm_eid for p in PAIRS]
    placeholders = ",".join(["?"] * len(arms))
    cnt = con.execute(
        f"""
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = ?
          AND parent_entity_id IN ({placeholders})
          AND child_entity_id IN ({placeholders})
        """,
        [OPEN_DATE, *arms, *arms],
    ).fetchone()[0]
    if cnt != 0:
        raise RuntimeError(f"unexpected cross-arm relationships: {cnt} rows")


def write_manifest(umbrella: Dict[str, object]) -> None:
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
        "hv2_aum_billions",
        "fh2_rollup_aum_billions",
        "prepared_relationship_id",
        "path",
    ]
    with MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in PAIRS:
            w.writerow(
                [
                    p.pair_no,
                    UMBRELLA_EID,
                    p.arm_eid,
                    umbrella["canonical_name"],
                    p.arm_canonical_name,
                    "wholly_owned",
                    "control",
                    _build_source(p.arm_canonical_name),
                    "high",
                    f"{p.hv2_aum_usd / 1e9:.4f}",
                    f"{p.fh2_rollup_aum_usd / 1e9:.4f}",
                    p.new_relationship_id,
                    PATH,
                ]
            )


def execute_pair(con: duckdb.DuckDBPyConnection, p: BridgePair, new_id: int) -> None:
    today = date.today()
    src = _build_source(p.arm_canonical_name)
    con.execute(
        """
        INSERT INTO entity_relationships
            (relationship_id, parent_entity_id, child_entity_id,
             relationship_type, control_type, is_primary, primary_parent_key,
             confidence, source, is_inferred, valid_from, valid_to,
             created_at, last_refreshed_at)
        VALUES (?, ?, ?, 'wholly_owned', 'control', TRUE, ?,
                'high', ?, FALSE, ?, ?, NOW(), NOW())
        """,
        [new_id, UMBRELLA_EID, p.arm_eid, UMBRELLA_EID, src, today, OPEN_DATE],
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
        [UMBRELLA_EID, p.arm_eid, OPEN_DATE],
    ).fetchone()[0]
    if cnt != 1:
        raise RuntimeError(
            f"[pair {p.pair_no}] post-INSERT sanity-check failed: "
            f"{cnt} open wholly_owned rows from {UMBRELLA_EID} to {p.arm_eid} (expected 1)"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to 13f.duckdb")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="Read-only manifest emit")
    grp.add_argument("--confirm", action="store_true", help="Execute the 3 INSERTs")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            umbrella = capture_umbrella(con)
            for p in PAIRS:
                capture_arm_preimage(con, p)
            assert_no_cross_arm(con)
            max_rel_id = int(
                con.execute(
                    "SELECT MAX(relationship_id) FROM entity_relationships"
                ).fetchone()[0]
            )
            open_rels_pre = int(
                con.execute(
                    "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = ?",
                    [OPEN_DATE],
                ).fetchone()[0]
            )
        finally:
            con.close()
        for i, p in enumerate(PAIRS):
            p.new_relationship_id = max_rel_id + i + 1
        write_manifest(umbrella)
        print(f"[dry-run] manifest: {MANIFEST_CSV}")
        print(
            f"[dry-run] umbrella eid={UMBRELLA_EID} ({umbrella['canonical_name']}); "
            f"path={PATH}"
        )
        total_hv2 = sum(p.hv2_aum_usd for p in PAIRS)
        for p in PAIRS:
            print(
                f"[dry-run] pair {p.pair_no}: arm eid={p.arm_eid} ({p.arm_canonical_name}) "
                f"hv2 ${p.hv2_aum_usd / 1e9:,.2f}B "
                f"fh2_rollup ${p.fh2_rollup_aum_usd / 1e9:,.2f}B "
                f"rel_id={p.new_relationship_id}"
            )
        print(f"[dry-run] total hv2 AUM bridged: ${total_hv2 / 1e9:,.2f}B")
        print(
            f"[dry-run] open relationships baseline: {open_rels_pre:,}; "
            f"max relationship_id: {max_rel_id:,}; prepared new ids: "
            f"{PAIRS[0].new_relationship_id:,}-{PAIRS[-1].new_relationship_id:,}"
        )
        for p in PAIRS:
            print(
                f"[dry-run] existing wholly_owned/control bridge {UMBRELLA_EID}<->{p.arm_eid} "
                f"(must be 0): {p.existing_control_bridge_count}"
            )
        print("[dry-run] sample source string:")
        print(f"  {_build_source(PAIRS[0].arm_canonical_name)}")
        return 0

    con = duckdb.connect(str(db_path), read_only=False)
    try:
        umbrella = capture_umbrella(con)
        for p in PAIRS:
            capture_arm_preimage(con, p)
        assert_no_cross_arm(con)

        if MANIFEST_CSV.exists():
            with MANIFEST_CSV.open() as f:
                rows = list(csv.DictReader(f))
            if len(rows) != len(PAIRS):
                raise RuntimeError(f"manifest expected {len(PAIRS)} rows, got {len(rows)}")
            for m, p in zip(rows, PAIRS):
                if (
                    int(m["parent_entity_id"]) != UMBRELLA_EID
                    or int(m["child_entity_id"]) != p.arm_eid
                ):
                    raise RuntimeError(
                        f"manifest pair {p.pair_no} mismatch: "
                        f"manifest=({m['parent_entity_id']},{m['child_entity_id']}) "
                        f"script=({UMBRELLA_EID},{p.arm_eid})"
                    )

        pre_count = int(
            con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0]
        )
        pre_open = int(
            con.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = ?",
                [OPEN_DATE],
            ).fetchone()[0]
        )
        pre_max = int(
            con.execute(
                "SELECT MAX(relationship_id) FROM entity_relationships"
            ).fetchone()[0]
        )

        # Capture per-arm hv2 + fh2 baselines for unchanged-AUM guards.
        baselines = {}
        for p in PAIRS:
            baselines[p.arm_eid] = {
                "hv2_rows": p.hv2_rows,
                "hv2_aum": p.hv2_aum_usd,
                "fh2_rows": p.fh2_rollup_rows,
                "fh2_aum": p.fh2_rollup_aum_usd,
            }

        prepared_ids = []
        for i, _ in enumerate(PAIRS):
            new_id = pre_max + i + 1
            exists = int(
                con.execute(
                    "SELECT COUNT(*) FROM entity_relationships WHERE relationship_id = ?",
                    [new_id],
                ).fetchone()[0]
            )
            if exists != 0:
                raise RuntimeError(f"prepared relationship_id={new_id} already exists")
            prepared_ids.append(new_id)

        con.execute("BEGIN")
        try:
            for p, new_id in zip(PAIRS, prepared_ids):
                execute_pair(con, p, new_id)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        post_count = int(
            con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0]
        )
        post_open = int(
            con.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE valid_to = ?",
                [OPEN_DATE],
            ).fetchone()[0]
        )
        post_max = int(
            con.execute(
                "SELECT MAX(relationship_id) FROM entity_relationships"
            ).fetchone()[0]
        )

        # Hard guards
        if post_count - pre_count != len(PAIRS):
            raise RuntimeError(f"row count delta {post_count - pre_count} != {len(PAIRS)}")
        if post_open - pre_open != len(PAIRS):
            raise RuntimeError(f"open-row delta {post_open - pre_open} != {len(PAIRS)}")
        if post_max != pre_max + len(PAIRS):
            raise RuntimeError(
                f"max relationship_id post={post_max} != pre+{len(PAIRS)}={pre_max + len(PAIRS)}"
            )

        # Guard 1: exactly 3 new open relationships in the prescribed shape
        arms = [p.arm_eid for p in PAIRS]
        placeholders = ",".join(["?"] * len(arms))
        new_count = int(
            con.execute(
                f"""
                SELECT COUNT(*) FROM entity_relationships
                WHERE parent_entity_id = ?
                  AND child_entity_id IN ({placeholders})
                  AND relationship_type = 'wholly_owned'
                  AND control_type = 'control'
                  AND valid_to = ?
                """,
                [UMBRELLA_EID, *arms, OPEN_DATE],
            ).fetchone()[0]
        )
        if new_count != len(PAIRS):
            raise RuntimeError(
                f"Guard 1 FAILED: expected {len(PAIRS)} new umbrella->arm "
                f"wholly_owned/control rows, got {new_count}"
            )

        # Guard 4 + 5: per-arm hv2 + fh2 AUM unchanged within $0.01B tolerance.
        for p in PAIRS:
            base = baselines[p.arm_eid]
            hv2_now = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0) FROM holdings_v2 "
                "WHERE entity_id = ? AND is_latest = TRUE",
                [p.arm_eid],
            ).fetchone()
            if int(hv2_now[0]) != base["hv2_rows"]:
                raise RuntimeError(
                    f"Guard 4 FAILED: arm {p.arm_eid} hv2 row count "
                    f"{int(hv2_now[0])} != baseline {base['hv2_rows']}"
                )
            if abs(float(hv2_now[1]) - base["hv2_aum"]) > 1e7:
                raise RuntimeError(
                    f"Guard 4 FAILED: arm {p.arm_eid} hv2 AUM drifted "
                    f"{float(hv2_now[1]):,.2f} vs baseline {base['hv2_aum']:,.2f}"
                )
            fh2_now = con.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
                FROM fund_holdings_v2
                WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
                  AND is_latest = TRUE
                """,
                [p.arm_eid, p.arm_eid],
            ).fetchone()
            if int(fh2_now[0]) != base["fh2_rows"]:
                raise RuntimeError(
                    f"Guard 5 FAILED: arm {p.arm_eid} fh2 row count "
                    f"{int(fh2_now[0])} != baseline {base['fh2_rows']}"
                )
            if abs(float(fh2_now[1]) - base["fh2_aum"]) > 1e7:
                raise RuntimeError(
                    f"Guard 5 FAILED: arm {p.arm_eid} fh2 AUM drifted "
                    f"{float(fh2_now[1]):,.2f} vs baseline {base['fh2_aum']:,.2f}"
                )

        write_manifest(umbrella)

        print("[confirm] DONE")
        for p in PAIRS:
            print(
                f"[confirm] pair {p.pair_no}: relationship_id={p.new_relationship_id} "
                f"({UMBRELLA_EID} -> {p.arm_eid}, {p.arm_canonical_name})"
            )
        print(f"[confirm] entity_relationships rows: {pre_count:,} -> {post_count:,} (Δ +{len(PAIRS)})")
        print(f"[confirm] open relationships: {pre_open:,} -> {post_open:,} (Δ +{len(PAIRS)})")
        print(f"[confirm] max(relationship_id): {pre_max:,} -> {post_max:,}")
        total_hv2 = sum(p.hv2_aum_usd for p in PAIRS)
        print(f"[confirm] total hv2 AUM bridged: ${total_hv2 / 1e9:,.2f}B (3 arms)")
        print(f"[confirm] manifest: {MANIFEST_CSV}")
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
