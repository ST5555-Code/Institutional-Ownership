#!/usr/bin/env python3
"""cp_5_cycle_truncated_merges_recon.py — Phase 1 read-only reconnaissance
for the cp-5-cycle-truncated-merges P0 cohort.

Reproduces Bundle B Phase 2.1's cycle-truncation detection, identifies the
~10-11 mutually-cycling entity pairs (21 entities total per Bundle B §2.2),
applies cp-5-adams-duplicates Phase 1 selection rules to pick canonical /
duplicate per pair, categorizes pairs (Category I single vs Category II
multi-duplicate), enumerates collision patterns, audits inverted rollups,
and captures pre-merge state baselines.

Drives chat-side design of 2-3 batched execute PRs.

Read-only. ABORTs only when cohort drift exceeds 10% from Bundle B's 21-entity
expectation; surfaces everything else for human inspection.

Outputs:
  data/working/cp-5-cycle-truncated-pair-manifest.csv
  data/working/cp-5-cycle-truncated-collision-matrix.csv
  data/working/cp-5-cycle-truncated-pre-merge-state.csv

Refs:
  docs/findings/cp-5-bundle-b-discovery.md §2.2
  docs/findings/cp-5-comprehensive-remediation.md §3.1
  docs/findings/cp-5-adams-duplicates-results.md (PR #283)
  scripts/oneoff/cp_5_bundle_b_common.py (cycle detection)
  scripts/oneoff/cp_5_adams_phase1_recon.py (op-shape precedent)
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")

WORKDIR = Path("data/working")

PAIR_MANIFEST_CSV = WORKDIR / "cp-5-cycle-truncated-pair-manifest.csv"
COLLISION_CSV = WORKDIR / "cp-5-cycle-truncated-collision-matrix.csv"
PRE_MERGE_CSV = WORKDIR / "cp-5-cycle-truncated-pre-merge-state.csv"

# Bundle B baseline: 21 entities → ~10-11 pairs. 10% drift on entity count = 19-23.
BUNDLE_B_ENTITY_COUNT = 21
DRIFT_TOLERANCE_PCT = 10.0

# X1 corporate-suffix strip set per cp-4b/cp-5-adams-duplicates precedent.
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


def normalize_name(name: str | None) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    while True:
        prev = s
        for pat in SUFFIX_STRIPS:
            s = re.sub(pat, "", s, flags=re.IGNORECASE)
        s = s.strip().rstrip(",").strip()
        if s == prev:
            break
    return s


@dataclass
class EntitySnap:
    entity_id: int
    canonical_name: str = ""
    entity_type: str = ""
    cik: str | None = None
    crd: str | None = None
    n_identifiers: int = 0
    holdings_v2_rows: int = 0
    holdings_v2_aum_usd: float = 0.0
    fh_v2_rollup_rows: int = 0
    fh_v2_rollup_aum_usd: float = 0.0
    fh_v2_dmrollup_rows: int = 0
    fh_v2_entity_id_rows: int = 0
    open_ech: int = 0
    open_erh_from: int = 0
    open_erh_at: int = 0
    open_aliases: int = 0
    open_relationships_parent: int = 0
    open_relationships_child: int = 0
    rollup_self_rows: int = 0  # rows where entity_id = rollup_entity_id (self-rolling)


@dataclass
class Pair:
    pair_id: int
    canonical_eid: int
    duplicate_eid: int
    canonical_name: str
    duplicate_name: str
    cycle_member_count: int  # 2 = clean 2-cycle; >2 = longer cycle
    cycle_members: tuple[int, ...]
    canonical_snap: EntitySnap = field(default_factory=lambda: EntitySnap(0))
    duplicate_snap: EntitySnap = field(default_factory=lambda: EntitySnap(0))
    selection_reason: str = ""
    ambiguous_selection: bool = False
    inverted_rollup: bool = False
    rollup_classification: str = ""  # NORMAL / INVERTED / DUPLICATE_ALSO_INVERTED / AMBIGUOUS
    inst_to_inst_relationship_ids: list[int] = field(default_factory=list)


def connect_ro() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DB_PATH, read_only=True)


def detect_cycle_truncated(con: duckdb.DuckDBPyConnection) -> tuple[list[int], dict[int, int]]:
    """Reproduce Bundle B Phase 2.1 cycle detection.

    Returns:
        (cycle_eids, edge_map) where:
          cycle_eids = list of institution eids whose top-parent climb hit a cycle
          edge_map = canonical {child_eid: parent_eid} after ordered dedup
    """
    types_sql = ", ".join(f"'{t}'" for t in ROLLUP_CTRL_TYPES)
    edges = con.execute(f"""
        SELECT er.child_entity_id, er.parent_entity_id
        FROM entity_relationships er
        JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
        JOIN entity_current cec ON cec.entity_id = er.child_entity_id
        WHERE er.valid_to = {SENTINEL}
          AND er.control_type IN ({types_sql})
          AND pec.entity_type = 'institution'
          AND cec.entity_type = 'institution'
    """).fetchdf()
    edges = edges.sort_values(["child_entity_id", "parent_entity_id"]).drop_duplicates(
        "child_entity_id", keep="first"
    )
    edge_map: dict[int, int] = dict(
        zip(edges["child_entity_id"].astype(int), edges["parent_entity_id"].astype(int))
    )

    seed = con.execute(
        "SELECT entity_id FROM entity_current WHERE entity_type='institution'"
    ).fetchdf()
    seed_eids = [int(e) for e in seed["entity_id"].tolist()]

    cycle_eids: set[int] = set()
    for eid in seed_eids:
        cur = eid
        visited: set[int] = {eid}
        for _ in range(20):
            nxt = edge_map.get(cur)
            if nxt is None or nxt == cur:
                break
            if nxt in visited:
                cycle_eids.add(eid)
                break
            visited.add(nxt)
            cur = nxt
    return sorted(cycle_eids), edge_map


def trace_cycle_members(eid: int, edge_map: dict[int, int]) -> tuple[int, ...]:
    """Return the cycle members reached from eid (the SCC of size >= 2)."""
    cur = eid
    visited: list[int] = [eid]
    for _ in range(40):
        nxt = edge_map.get(cur)
        if nxt is None or nxt == cur:
            return ()
        if nxt in visited:
            # Cycle starts at the index of nxt
            idx = visited.index(nxt)
            return tuple(sorted(visited[idx:]))
        visited.append(nxt)
        cur = nxt
    return ()


def populate_snap(con: duckdb.DuckDBPyConnection, snap: EntitySnap) -> None:
    eid = snap.entity_id
    row = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id = ?",
        [eid],
    ).fetchone()
    if row:
        snap.canonical_name = row[0] or ""
        snap.entity_type = row[1] or ""
    cik_row = con.execute(
        f"""
        SELECT identifier_value FROM entity_identifiers
        WHERE entity_id = ? AND identifier_type = 'cik' AND valid_to = {SENTINEL} LIMIT 1
        """,
        [eid],
    ).fetchone()
    snap.cik = cik_row[0] if cik_row else None
    crd_row = con.execute(
        f"""
        SELECT identifier_value FROM entity_identifiers
        WHERE entity_id = ? AND identifier_type = 'crd' AND valid_to = {SENTINEL} LIMIT 1
        """,
        [eid],
    ).fetchone()
    snap.crd = crd_row[0] if crd_row else None
    snap.n_identifiers = int(con.execute(
        f"SELECT COUNT(*) FROM entity_identifiers WHERE entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])

    h_row = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0) "
        "FROM holdings_v2 WHERE entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()
    snap.holdings_v2_rows = int(h_row[0])
    snap.holdings_v2_aum_usd = float(h_row[1])

    fh_rollup = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0) "
        "FROM fund_holdings_v2 WHERE rollup_entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()
    snap.fh_v2_rollup_rows = int(fh_rollup[0])
    snap.fh_v2_rollup_aum_usd = float(fh_rollup[1])
    snap.fh_v2_dmrollup_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()[0])
    snap.fh_v2_entity_id_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id = ? AND is_latest = TRUE",
        [eid],
    ).fetchone()[0])

    snap.open_ech = int(con.execute(
        f"SELECT COUNT(*) FROM entity_classification_history WHERE entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])
    snap.open_erh_from = int(con.execute(
        f"SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])
    snap.open_erh_at = int(con.execute(
        f"SELECT COUNT(*) FROM entity_rollup_history WHERE rollup_entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])
    snap.rollup_self_rows = int(con.execute(
        f"SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND rollup_entity_id = ? AND valid_to = {SENTINEL}",
        [eid, eid],
    ).fetchone()[0])
    snap.open_aliases = int(con.execute(
        f"SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])
    snap.open_relationships_parent = int(con.execute(
        f"SELECT COUNT(*) FROM entity_relationships WHERE parent_entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])
    snap.open_relationships_child = int(con.execute(
        f"SELECT COUNT(*) FROM entity_relationships WHERE child_entity_id = ? AND valid_to = {SENTINEL}",
        [eid],
    ).fetchone()[0])


def select_canonical(members: list[EntitySnap]) -> tuple[EntitySnap, str, bool]:
    """Apply prompt Phase 1c selection rules.

    Returns (canonical, reason, ambiguous_flag).
    """
    # Rule 1: prefer non-zero holdings_v2 rows
    active = [m for m in members if m.holdings_v2_rows > 0]
    if active:
        # Rule 2: prefer greater AUM
        sorted_active = sorted(active, key=lambda m: -m.holdings_v2_aum_usd)
        if (len(sorted_active) > 1 and sorted_active[0].holdings_v2_aum_usd > 0
                and sorted_active[1].holdings_v2_aum_usd > 0
                and sorted_active[0].holdings_v2_aum_usd / max(sorted_active[1].holdings_v2_aum_usd, 1) < 1.10):
            # both meaningful holdings within 10% — flag ambiguous
            return sorted_active[0], "rule2_aum_close_ambiguous", True
        return sorted_active[0], "rule1_active_filer", False

    # Rule 3: prefer greater fund_holdings_v2 rollup footprint
    with_footprint = [m for m in members if m.fh_v2_rollup_rows > 0]
    if with_footprint:
        sorted_fp = sorted(with_footprint, key=lambda m: -m.fh_v2_rollup_rows)
        if (len(sorted_fp) > 1
                and sorted_fp[0].fh_v2_rollup_rows / max(sorted_fp[1].fh_v2_rollup_rows, 1) < 1.10):
            return sorted_fp[0], "rule3_fh_footprint_close_ambiguous", True
        return sorted_fp[0], "rule3_fh_footprint", False

    # Rule 4: lowest eid
    return min(members, key=lambda m: m.entity_id), "rule4_lowest_eid", False


def classify_rollup_direction(canonical: EntitySnap, duplicate: EntitySnap,
                               can_rollup_targets: list[int],
                               dup_rollup_targets: list[int]) -> tuple[str, bool]:
    """Per prompt Phase 4a: classify rollup direction for the pair.

    Returns (classification, inverted_flag).

    Classifications:
      INVERTED: canonical's rollup_entity_id = duplicate (this is the bad case
        — Op H Branch 2 must run)
      NORMAL: canonical self-rolls or rolls to a 3rd entity correctly
      DUPLICATE_ALSO_INVERTED: duplicate rolls to canonical (expected; merge
        resolves)
      AMBIGUOUS: rollup direction unclear
    """
    can_to_dup = duplicate.entity_id in can_rollup_targets
    dup_to_can = canonical.entity_id in dup_rollup_targets

    if can_to_dup and dup_to_can:
        return "AMBIGUOUS_BOTH_DIRECTIONS", True
    if can_to_dup:
        return "INVERTED", True
    if dup_to_can:
        return "DUPLICATE_TO_CANONICAL", False
    # Neither direction; canonical may self-roll or roll to a 3rd.
    if canonical.rollup_self_rows > 0 and not can_to_dup:
        return "NORMAL_SELF", False
    return "NORMAL_OTHER", False


def main() -> int:
    if not Path(DB_PATH).exists():
        print(f"ERROR: db not found: {DB_PATH}", file=sys.stderr)
        return 1
    WORKDIR.mkdir(parents=True, exist_ok=True)

    con = connect_ro()
    print("=" * 90)
    print("Phase 1a — Re-validate cycle-truncated cohort (Bundle B §2.2 method)")
    print("=" * 90)
    cycle_eids, edge_map = detect_cycle_truncated(con)
    n_entities = len(cycle_eids)
    print(f"  cycle-truncated entities found: {n_entities}")
    print(f"  Bundle B baseline: {BUNDLE_B_ENTITY_COUNT}")
    drift_pct = 100.0 * abs(n_entities - BUNDLE_B_ENTITY_COUNT) / BUNDLE_B_ENTITY_COUNT
    print(f"  drift: {drift_pct:.1f}% (tolerance: {DRIFT_TOLERANCE_PCT:.1f}%)")
    if drift_pct > DRIFT_TOLERANCE_PCT:
        print("  *** ABORT: cohort drift exceeds tolerance. ***", file=sys.stderr)
        return 2

    # Print eids + names
    print("\n  cycle-truncated entity list:")
    name_rows = con.execute(
        f"SELECT entity_id, canonical_name, entity_type FROM entities "
        f"WHERE entity_id IN ({','.join(str(e) for e in cycle_eids)})"
    ).fetchall()
    name_map = {int(r[0]): (r[1], r[2]) for r in name_rows}
    for eid in cycle_eids:
        nm, et = name_map.get(eid, ("?", "?"))
        print(f"    eid={eid:>6}  type={et:<12} name={nm}")

    # Group eids into cycles via SCC
    print("\n" + "=" * 90)
    print("Phase 1a (cont) — Group eids into cycle SCCs")
    print("=" * 90)
    eid_to_cycle: dict[int, tuple[int, ...]] = {}
    for eid in cycle_eids:
        members = trace_cycle_members(eid, edge_map)
        if members:
            eid_to_cycle[eid] = members
        else:
            print(f"  WARN: eid={eid} did not yield a cycle on retrace", file=sys.stderr)

    cycle_groups: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for eid, cyc in eid_to_cycle.items():
        cycle_groups[cyc].append(eid)

    print(f"  distinct cycles: {len(cycle_groups)}")
    print(f"  cycle size distribution:")
    sizes_count: dict[int, int] = defaultdict(int)
    for cyc in cycle_groups:
        sizes_count[len(cyc)] += 1
    for sz, n in sorted(sizes_count.items()):
        print(f"    {sz}-cycle: {n} groups")

    # Build pairs from 2-cycles. Flag longer cycles as needing chat decision.
    print("\n" + "=" * 90)
    print("Phase 1b — Pair manifest (per-eid baselines)")
    print("=" * 90)

    # First, snap every cycle-truncated entity
    snaps: dict[int, EntitySnap] = {}
    for eid in cycle_eids:
        s = EntitySnap(entity_id=eid)
        populate_snap(con, s)
        snaps[eid] = s

    # Print baseline table
    print(f"\n  per-entity baseline:")
    hdr = (f"  {'eid':>6} {'type':<12} {'cik':<12} {'h_v2':>5} "
           f"{'h_v2_aum_b':>10} {'fh_rollup':>9} {'fh_rollup_aum_b':>15} "
           f"{'fh_dmrollup':>11} {'fh_entity':>9} "
           f"{'ech':>4} {'erh_from':>8} {'erh_at':>6} {'aliases':>7} "
           f"{'rel_p':>5} {'rel_c':>5} {'name':<40}")
    print(hdr)
    for eid in cycle_eids:
        s = snaps[eid]
        print(f"  {s.entity_id:>6} {s.entity_type:<12} {(s.cik or '-'):<12} "
              f"{s.holdings_v2_rows:>5} {s.holdings_v2_aum_usd/1e9:>10.3f} "
              f"{s.fh_v2_rollup_rows:>9} {s.fh_v2_rollup_aum_usd/1e9:>15.3f} "
              f"{s.fh_v2_dmrollup_rows:>11} {s.fh_v2_entity_id_rows:>9} "
              f"{s.open_ech:>4} {s.open_erh_from:>8} {s.open_erh_at:>6} "
              f"{s.open_aliases:>7} {s.open_relationships_parent:>5} "
              f"{s.open_relationships_child:>5} {s.canonical_name[:40]}")

    # Construct Pair objects from cycle groups
    pairs: list[Pair] = []
    longer_cycle_groups: list[tuple[tuple[int, ...], list[int]]] = []
    pair_id_seq = 1
    for cyc, members in sorted(cycle_groups.items()):
        if len(cyc) == 2:
            member_snaps = [snaps[e] for e in cyc]
            canonical, reason, ambiguous = select_canonical(member_snaps)
            duplicate = next(s for s in member_snaps if s.entity_id != canonical.entity_id)
            p = Pair(
                pair_id=pair_id_seq,
                canonical_eid=canonical.entity_id,
                duplicate_eid=duplicate.entity_id,
                canonical_name=canonical.canonical_name,
                duplicate_name=duplicate.canonical_name,
                cycle_member_count=2,
                cycle_members=cyc,
                canonical_snap=canonical,
                duplicate_snap=duplicate,
                selection_reason=reason,
                ambiguous_selection=ambiguous,
            )
            pairs.append(p)
            pair_id_seq += 1
        else:
            longer_cycle_groups.append((cyc, members))

    print(f"\n  pairs constructed from 2-cycles: {len(pairs)}")
    if longer_cycle_groups:
        print(f"  *** longer cycles ({len(longer_cycle_groups)}) require chat decision ***")
        for cyc, members in longer_cycle_groups:
            print(f"    cycle members: {cyc}  truncated_from: {members}")

    # Phase 1c: print canonical/duplicate per pair
    print("\n" + "=" * 90)
    print("Phase 1c — Canonical-eid selection per pair")
    print("=" * 90)
    for p in pairs:
        flag = " [AMBIGUOUS]" if p.ambiguous_selection else ""
        print(f"  pair_id={p.pair_id}: canonical={p.canonical_eid} ({p.canonical_name})")
        print(f"           duplicate={p.duplicate_eid} ({p.duplicate_name})")
        print(f"           reason={p.selection_reason}{flag}")
        print(f"           canonical: h_v2={p.canonical_snap.holdings_v2_rows} aum=${p.canonical_snap.holdings_v2_aum_usd/1e9:.3f}B "
              f"fh_rollup={p.canonical_snap.fh_v2_rollup_rows} fh_rollup_aum=${p.canonical_snap.fh_v2_rollup_aum_usd/1e9:.3f}B")
        print(f"           duplicate: h_v2={p.duplicate_snap.holdings_v2_rows} aum=${p.duplicate_snap.holdings_v2_aum_usd/1e9:.3f}B "
              f"fh_rollup={p.duplicate_snap.fh_v2_rollup_rows} fh_rollup_aum=${p.duplicate_snap.fh_v2_rollup_aum_usd/1e9:.3f}B")

    # Capture inst↔inst relationship_ids per pair
    for p in pairs:
        rels = con.execute(
            f"""SELECT relationship_id FROM entity_relationships
                WHERE valid_to = {SENTINEL}
                  AND ((parent_entity_id = ? AND child_entity_id = ?)
                    OR (parent_entity_id = ? AND child_entity_id = ?))""",
            [p.canonical_eid, p.duplicate_eid, p.duplicate_eid, p.canonical_eid],
        ).fetchall()
        p.inst_to_inst_relationship_ids = sorted(int(r[0]) for r in rels)

    # =========================================================
    # Phase 2 — categorize Category I vs Category II
    # =========================================================
    print("\n" + "=" * 90)
    print("Phase 2 — Pair-shape categorization")
    print("=" * 90)
    canonicals_count: dict[int, int] = defaultdict(int)
    for p in pairs:
        canonicals_count[p.canonical_eid] += 1

    print(f"\n  duplicates per canonical:")
    for cid, n in sorted(canonicals_count.items(), key=lambda x: (-x[1], x[0])):
        nm = name_map.get(cid, ("?", "?"))[0]
        print(f"    canonical={cid:>6} duplicates={n}  ({nm})")

    cat_i = [p for p in pairs if canonicals_count[p.canonical_eid] == 1]
    cat_ii = [p for p in pairs if canonicals_count[p.canonical_eid] >= 2]
    print(f"\n  Category I (simple, 1 duplicate per canonical): {len(cat_i)} pairs")
    print(f"  Category II (multi-duplicate canonical): {len(cat_ii)} pairs")
    cat_ii_canonicals = sorted({p.canonical_eid for p in cat_ii})
    if cat_ii_canonicals:
        print(f"  Category II canonicals: {cat_ii_canonicals}")

    # =========================================================
    # Phase 3 — collision pattern enumeration
    # =========================================================
    print("\n" + "=" * 90)
    print("Phase 3 — Collision pattern enumeration (entity_aliases)")
    print("=" * 90)

    # For each duplicate, list aliases; check if same (alias_name, alias_type, valid_from)
    # already exists open on canonical.
    collision_rows = []
    # Track aliases per canonical for chained-collision risk detection
    canonical_alias_keys: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
    duplicate_aliases_by_pair: dict[int, list[tuple]] = {}
    for p in pairs:
        existing = con.execute(
            f"""SELECT alias_name, alias_type, valid_from FROM entity_aliases
                WHERE entity_id = ? AND valid_to = {SENTINEL}""",
            [p.canonical_eid],
        ).fetchall()
        canonical_alias_keys[p.canonical_eid] = {
            (r[0], r[1], str(r[2])) for r in existing
        }

    # Collect each duplicate's aliases
    for p in pairs:
        rows = con.execute(
            f"""SELECT alias_name, alias_type, valid_from, is_preferred FROM entity_aliases
                WHERE entity_id = ? AND valid_to = {SENTINEL}""",
            [p.duplicate_eid],
        ).fetchall()
        duplicate_aliases_by_pair[p.pair_id] = rows

    # Pre-compute chain risk: for each canonical, bag of (alias_name, alias_type, valid_from)
    # appearing across multiple duplicates of same canonical
    chain_alias_keys: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
    for canonical_eid in cat_ii_canonicals:
        canonical_pairs = [p for p in pairs if p.canonical_eid == canonical_eid]
        all_dup_alias_keys = []
        for p in canonical_pairs:
            for nm, at, vf, _pref in duplicate_aliases_by_pair[p.pair_id]:
                all_dup_alias_keys.append((nm, at, str(vf)))
        cnt: dict[tuple[str, str, str], int] = defaultdict(int)
        for k in all_dup_alias_keys:
            cnt[k] += 1
        for k, c in cnt.items():
            if c >= 2:
                chain_alias_keys[canonical_eid].add(k)

    direct_total = will_repoint_total = chain_risk_total = 0
    pair_collision_summary: dict[int, dict[str, int]] = {}
    for p in pairs:
        direct = will_repoint = chain_risk = 0
        # Pre-image on canonical preferred
        can_pref_row = con.execute(
            f"""SELECT alias_name, alias_type FROM entity_aliases
                WHERE entity_id = ? AND is_preferred = TRUE AND valid_to = {SENTINEL} LIMIT 1""",
            [p.canonical_eid],
        ).fetchone()
        dup_pref_row = con.execute(
            f"""SELECT alias_name, alias_type FROM entity_aliases
                WHERE entity_id = ? AND is_preferred = TRUE AND valid_to = {SENTINEL} LIMIT 1""",
            [p.duplicate_eid],
        ).fetchone()
        canonical_side_preferred = "true" if can_pref_row else "false"
        duplicate_side_preferred = "true" if dup_pref_row else "false"

        for alias_name, alias_type, valid_from, is_preferred in duplicate_aliases_by_pair[p.pair_id]:
            key = (alias_name, alias_type, str(valid_from))
            if key in canonical_alias_keys[p.canonical_eid]:
                direct += 1
                category = "DIRECT_COLLISION"
            elif key in chain_alias_keys.get(p.canonical_eid, set()):
                chain_risk += 1
                category = "CHAINED_COLLISION_RISK"
            else:
                will_repoint += 1
                category = "WILL_RE_POINT"
            collision_rows.append({
                "pair_id": p.pair_id,
                "canonical_eid": p.canonical_eid,
                "duplicate_eid": p.duplicate_eid,
                "alias_name": alias_name,
                "alias_type": alias_type,
                "valid_from": str(valid_from),
                "is_preferred": str(is_preferred),
                "category": category,
            })
        direct_total += direct
        will_repoint_total += will_repoint
        chain_risk_total += chain_risk
        pair_collision_summary[p.pair_id] = {
            "direct_collision": direct,
            "will_repoint": will_repoint,
            "chained_collision_risk": chain_risk,
            "canonical_side_preferred": canonical_side_preferred,
            "duplicate_side_preferred": duplicate_side_preferred,
        }

    print(f"\n  cohort-level totals:")
    print(f"    DIRECT_COLLISION: {direct_total}")
    print(f"    WILL_RE_POINT: {will_repoint_total}")
    print(f"    CHAINED_COLLISION_RISK: {chain_risk_total}")

    print(f"\n  per-pair collision summary:")
    print(f"  {'pair':>4} {'canon':>6} {'dup':>6} {'direct':>7} "
          f"{'repoint':>8} {'chain':>6} {'can_pref':>9} {'dup_pref':>9}")
    for p in pairs:
        s = pair_collision_summary[p.pair_id]
        print(f"  {p.pair_id:>4} {p.canonical_eid:>6} {p.duplicate_eid:>6} "
              f"{s['direct_collision']:>7} {s['will_repoint']:>8} {s['chained_collision_risk']:>6} "
              f"{s['canonical_side_preferred']:>9} {s['duplicate_side_preferred']:>9}")

    # =========================================================
    # Phase 4 — inverted-rollup audit
    # =========================================================
    print("\n" + "=" * 90)
    print("Phase 4 — Inverted-rollup audit")
    print("=" * 90)
    for p in pairs:
        can_targets = [int(r[0]) for r in con.execute(
            f"""SELECT DISTINCT rollup_entity_id FROM entity_rollup_history
                WHERE entity_id = ? AND valid_to = {SENTINEL}""",
            [p.canonical_eid],
        ).fetchall() if r[0] is not None]
        dup_targets = [int(r[0]) for r in con.execute(
            f"""SELECT DISTINCT rollup_entity_id FROM entity_rollup_history
                WHERE entity_id = ? AND valid_to = {SENTINEL}""",
            [p.duplicate_eid],
        ).fetchall() if r[0] is not None]
        cls, inv = classify_rollup_direction(p.canonical_snap, p.duplicate_snap, can_targets, dup_targets)
        p.rollup_classification = cls
        p.inverted_rollup = inv

    inverted_pairs = [p for p in pairs if p.rollup_classification == "INVERTED"]
    ambig_pairs = [p for p in pairs if p.rollup_classification == "AMBIGUOUS_BOTH_DIRECTIONS"]

    print(f"\n  inverted (canonical→duplicate, needs Op H Branch 2): {len(inverted_pairs)}")
    for p in inverted_pairs:
        print(f"    pair={p.pair_id}: {p.canonical_eid} → {p.duplicate_eid}  ({p.canonical_name})")
    print(f"  ambiguous (both directions present, chat decision): {len(ambig_pairs)}")
    for p in ambig_pairs:
        print(f"    pair={p.pair_id}: {p.canonical_eid} ↔ {p.duplicate_eid}  ({p.canonical_name})")

    print(f"\n  classification breakdown:")
    cls_counts: dict[str, int] = defaultdict(int)
    for p in pairs:
        cls_counts[p.rollup_classification] += 1
    for c, n in sorted(cls_counts.items()):
        print(f"    {c}: {n}")

    print(f"\n  per-pair rollup direction:")
    print(f"  {'pair':>4} {'canon':>6} {'dup':>6} {'classification':<28}")
    for p in pairs:
        print(f"  {p.pair_id:>4} {p.canonical_eid:>6} {p.duplicate_eid:>6} {p.rollup_classification:<28}")

    # =========================================================
    # Phase 5 — pre-merge baselines summary
    # =========================================================
    print("\n" + "=" * 90)
    print("Phase 5 — Pre-merge state baselines (cohort-level summary)")
    print("=" * 90)
    total_dup_h13f = sum(p.duplicate_snap.holdings_v2_aum_usd for p in pairs) / 1e9
    total_can_h13f = sum(p.canonical_snap.holdings_v2_aum_usd for p in pairs) / 1e9
    total_dup_fh = sum(p.duplicate_snap.fh_v2_rollup_aum_usd for p in pairs) / 1e9
    total_can_fh = sum(p.canonical_snap.fh_v2_rollup_aum_usd for p in pairs) / 1e9
    print(f"  total canonical 13F AUM (pre): ${total_can_h13f:,.2f}B")
    print(f"  total duplicate 13F AUM (pre): ${total_dup_h13f:,.2f}B")
    print(f"  total canonical fund-tier rollup AUM (pre): ${total_can_fh:,.2f}B")
    print(f"  total duplicate fund-tier rollup AUM (pre): ${total_dup_fh:,.2f}B")
    print(f"  total cohort fund-tier AUM impact (transferred): ${total_dup_fh:,.2f}B")
    print(f"  per-pair AUM (descending by duplicate fund-tier AUM):")
    print(f"  {'pair':>4} {'canon':>6} {'dup':>6} {'dup_fh_aum_b':>13} "
          f"{'can_fh_aum_b':>13} {'dup_h13f_aum_b':>15} {'name':<50}")
    for p in sorted(pairs, key=lambda x: -x.duplicate_snap.fh_v2_rollup_aum_usd):
        print(f"  {p.pair_id:>4} {p.canonical_eid:>6} {p.duplicate_eid:>6} "
              f"{p.duplicate_snap.fh_v2_rollup_aum_usd/1e9:>13.3f} "
              f"{p.canonical_snap.fh_v2_rollup_aum_usd/1e9:>13.3f} "
              f"{p.duplicate_snap.holdings_v2_aum_usd/1e9:>15.3f} "
              f"{p.canonical_name[:50]}")

    # =========================================================
    # Phase 6 — sizing recommendation
    # =========================================================
    print("\n" + "=" * 90)
    print("Phase 6 — Execute PR sizing recommendation")
    print("=" * 90)
    print(f"  Category I count: {len(cat_i)}")
    print(f"  Category II count: {len(cat_ii)}")
    print(f"  Category II distinct canonicals: {len(cat_ii_canonicals)}")

    # Per chat decision: simple-pair batch + multi-duplicate batch
    if len(cat_ii_canonicals) >= 4 and len(cat_ii) >= 10:
        print("  recommended: 3 PRs (Cat I; Cat II 2-dup; Cat II 3+-dup)")
    else:
        print("  recommended: 2 PRs (Category I batch + Category II batch)")

    # =========================================================
    # Write CSV outputs
    # =========================================================
    with PAIR_MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pair_id", "canonical_eid", "duplicate_eid",
            "canonical_name", "duplicate_name",
            "cycle_member_count", "cycle_members",
            "selection_reason", "ambiguous_selection",
            "canonical_type", "duplicate_type",
            "canonical_cik", "duplicate_cik",
            "canonical_crd", "duplicate_crd",
            "canonical_n_identifiers", "duplicate_n_identifiers",
            "canonical_h_v2_rows", "canonical_h_v2_aum_b",
            "duplicate_h_v2_rows", "duplicate_h_v2_aum_b",
            "canonical_fh_rollup_rows", "canonical_fh_rollup_aum_b",
            "duplicate_fh_rollup_rows", "duplicate_fh_rollup_aum_b",
            "canonical_fh_dmrollup_rows", "duplicate_fh_dmrollup_rows",
            "canonical_fh_entity_rows", "duplicate_fh_entity_rows",
            "category", "n_dup_per_canonical",
            "rollup_classification", "inverted_rollup",
            "inst_inst_relationship_ids",
        ])
        for p in pairs:
            cat = "I" if canonicals_count[p.canonical_eid] == 1 else "II"
            w.writerow([
                p.pair_id, p.canonical_eid, p.duplicate_eid,
                p.canonical_name, p.duplicate_name,
                p.cycle_member_count, ";".join(str(e) for e in p.cycle_members),
                p.selection_reason, p.ambiguous_selection,
                p.canonical_snap.entity_type, p.duplicate_snap.entity_type,
                p.canonical_snap.cik or "", p.duplicate_snap.cik or "",
                p.canonical_snap.crd or "", p.duplicate_snap.crd or "",
                p.canonical_snap.n_identifiers, p.duplicate_snap.n_identifiers,
                p.canonical_snap.holdings_v2_rows, f"{p.canonical_snap.holdings_v2_aum_usd/1e9:.4f}",
                p.duplicate_snap.holdings_v2_rows, f"{p.duplicate_snap.holdings_v2_aum_usd/1e9:.4f}",
                p.canonical_snap.fh_v2_rollup_rows, f"{p.canonical_snap.fh_v2_rollup_aum_usd/1e9:.4f}",
                p.duplicate_snap.fh_v2_rollup_rows, f"{p.duplicate_snap.fh_v2_rollup_aum_usd/1e9:.4f}",
                p.canonical_snap.fh_v2_dmrollup_rows, p.duplicate_snap.fh_v2_dmrollup_rows,
                p.canonical_snap.fh_v2_entity_id_rows, p.duplicate_snap.fh_v2_entity_id_rows,
                cat, canonicals_count[p.canonical_eid],
                p.rollup_classification, p.inverted_rollup,
                ";".join(str(r) for r in p.inst_to_inst_relationship_ids),
            ])
    print(f"\n  Wrote {PAIR_MANIFEST_CSV}")

    with COLLISION_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pair_id", "canonical_eid", "duplicate_eid",
            "alias_name", "alias_type", "valid_from",
            "is_preferred", "category",
        ])
        for r in collision_rows:
            w.writerow([
                r["pair_id"], r["canonical_eid"], r["duplicate_eid"],
                r["alias_name"], r["alias_type"], r["valid_from"],
                r["is_preferred"], r["category"],
            ])
    print(f"  Wrote {COLLISION_CSV}")

    with PRE_MERGE_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pair_id", "side", "entity_id", "entity_name",
            "entity_type", "cik", "h_v2_rows", "h_v2_aum_b",
            "fh_rollup_rows", "fh_rollup_aum_b",
            "fh_dmrollup_rows", "fh_entity_id_rows",
            "open_ech", "open_erh_from", "open_erh_at",
            "open_aliases", "open_rel_parent", "open_rel_child",
            "rollup_self_rows",
        ])
        for p in pairs:
            for side, s in (("canonical", p.canonical_snap), ("duplicate", p.duplicate_snap)):
                w.writerow([
                    p.pair_id, side, s.entity_id, s.canonical_name,
                    s.entity_type, s.cik or "",
                    s.holdings_v2_rows, f"{s.holdings_v2_aum_usd/1e9:.4f}",
                    s.fh_v2_rollup_rows, f"{s.fh_v2_rollup_aum_usd/1e9:.4f}",
                    s.fh_v2_dmrollup_rows, s.fh_v2_entity_id_rows,
                    s.open_ech, s.open_erh_from, s.open_erh_at,
                    s.open_aliases, s.open_relationships_parent, s.open_relationships_child,
                    s.rollup_self_rows,
                ])
    print(f"  Wrote {PRE_MERGE_CSV}")

    # =========================================================
    # Phase 6d — chat decisions surfaced
    # =========================================================
    print("\n" + "=" * 90)
    print("Phase 6d — Chat decisions needed before execute PRs")
    print("=" * 90)
    chat_blockers: list[str] = []
    if longer_cycle_groups:
        chat_blockers.append(
            f"{len(longer_cycle_groups)} cycle(s) of size > 2 require non-pairwise op-shape"
        )
    ambig_select = [p for p in pairs if p.ambiguous_selection]
    if ambig_select:
        chat_blockers.append(
            f"{len(ambig_select)} pair(s) have ambiguous canonical selection: "
            f"{[(p.pair_id, p.canonical_eid, p.duplicate_eid) for p in ambig_select]}"
        )
    if ambig_pairs:
        chat_blockers.append(
            f"{len(ambig_pairs)} pair(s) have AMBIGUOUS_BOTH_DIRECTIONS rollup: "
            f"{[(p.pair_id, p.canonical_eid, p.duplicate_eid) for p in ambig_pairs]}"
        )
    # Surface pairs where duplicate has open ECH (Op C will close — needs visible flag)
    dup_open_ech = [p for p in pairs if p.duplicate_snap.open_ech > 0]
    if dup_open_ech:
        chat_blockers.append(
            f"{len(dup_open_ech)} pair(s) have open ECH on duplicate (Op C will close): "
            f"{[(p.pair_id, p.duplicate_eid, p.duplicate_snap.open_ech) for p in dup_open_ech]}"
        )
    # Surface pairs where duplicate has 13F holdings (AUM transfer non-trivial)
    dup_h13f = [p for p in pairs if p.duplicate_snap.holdings_v2_rows > 0]
    if dup_h13f:
        chat_blockers.append(
            f"{len(dup_h13f)} pair(s) have non-zero holdings_v2 on duplicate (AUM transfer): "
            f"{[(p.pair_id, p.duplicate_eid, p.duplicate_snap.holdings_v2_rows, round(p.duplicate_snap.holdings_v2_aum_usd/1e9, 3)) for p in dup_h13f]}"
        )

    if chat_blockers:
        for i, b in enumerate(chat_blockers, 1):
            print(f"  {i}. {b}")
    else:
        print("  (none — recon found no chat-blocking conditions)")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
