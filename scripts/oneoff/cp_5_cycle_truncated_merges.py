#!/usr/bin/env python3
"""cp_5_cycle_truncated_merges.py — 10-pair cycle-truncated cohort MERGE.

Second P0 pre-execution PR per docs/findings/cp-5-comprehensive-remediation.md
§3.1. Closes the 10-pair cycle-truncated entity duplicate cohort surfaced in
Bundle B Phase 2.1 and scoped in PR #284 recon by merging duplicate -> canonical
using the cp-4a-style MERGE shape with FOUR op-shape extensions:

  Adjustment 1 (cp-4a / Adams):    close-on-collision in Op G.
  Adjustment 2 (this PR / Op A.3): holdings_v2.entity_id re-point.
  Adjustment 3 (this PR / Op A.4): entity_identifiers SCD transfer.
  Adjustment 4 (this PR / Op A):   two-step column-independent fund_holdings_v2
                                    re-point (Op A.1 rollup_entity_id;
                                    Op A.2 dm_rollup_entity_id + dm_rollup_name).

D1 generalization: Op B' supports N cycle edges per pair (cohort = 2 each).

Adjustment 4 supersedes the cp-4a one-step OR-clause Op A in cp-5-style true-
duplicate-merge contexts. The cp-4a brand→filer bridge semantic (PR #256)
remains correct as designed for that PR. Adams cohort (PR #283) inherited the
one-step shape but was data-safe due to $0 / near-$0 duplicate footprint;
Phase 1.5 paper audit confirmed no THIRD-entity damage. Going forward,
Adjustment 4 (split Op A) is canonical for true-duplicate merges.

Op shape (per pair, 12 ops, single transaction across ALL pairs):

  Op A.1  fund_holdings_v2.rollup_entity_id re-point (column-independent).
            UPDATE rollup_entity_id = canonical
            WHERE rollup_entity_id = duplicate AND is_latest = TRUE.

  Op A.2  fund_holdings_v2.dm_rollup_entity_id + dm_rollup_name re-point
          (column-independent).
            UPDATE dm_rollup_entity_id = canonical, dm_rollup_name = X
            WHERE dm_rollup_entity_id = duplicate AND is_latest = TRUE.

  Op A.3  holdings_v2.entity_id re-point (Adjustment 2). Pair 5 only.

  Op A.4  entity_identifiers SCD transfer (Adjustment 3). Per identifier_type
          where duplicate carries an open identifier the canonical lacks:
          close at duplicate (valid_to = today) + insert at canonical with
          valid_from = today.

  Op B    entity_relationships re-point parent + child sides
          (excludes the cycle edges Op B' handles).

  Op B'   Close all canonical<->duplicate cycle edges (D1: N edges).
          Cohort has 2 per pair; total 20 edges across cohort.

  Op C    entity_classification_history close duplicate-side.

  Op E    entity_relationships INSERT audit row
          (relationship_type='parent_brand', control_type='merge';
           relationship_id = sequential MAX+1 .. MAX+10).

  Op F    entity_rollup_history close duplicate-side FROM rows.

  Op G    entity_aliases re-point with Adjustment 1 (close-on-collision).

  Op H    entity_rollup_history AT-side cleanup (88 rows, mostly Goldman):
          Branch 1 — general AT re-point (close + insert with rollup=canonical
          preserving rule_applied/confidence/source/routing_confidence/
          review_due_date).
          Branch 2 — canonical self-rollup recreate. Cohort = 0 rows
          (all 10 pairs have inverted_rollup=False).

Hard guards (per pair, 11 checks; ROLLBACK on any failure):
  1a. Zero leftover rows with rollup_entity_id = duplicate.
  1b. Zero leftover rows with dm_rollup_entity_id = duplicate.
  1c. Zero leftover holdings_v2 rows with entity_id = duplicate.
  2.  Exactly 1 open relationship ref dup (the Op E audit row).
  3.  Zero open ECH on dup.
  4.  Zero open ERH FROM-side on dup.
  5.  Zero open ERH AT-side on dup.
  6.  Zero open aliases on dup.
  6b. Zero open entity_identifiers on dup.
  7a. AUM conservation rollup-side (per-column exact):
        post_can_rollup = pre_can_rollup + pre_dup_rollup ± $0.01B.
  7b. AUM conservation dm_rollup-side (per-column exact):
        post_can_dm = pre_can_dm + pre_dup_dm ± $0.01B.
  7c. AUM conservation h_v2-side:
        post_can_h_v2 = pre_can_h_v2 + pre_dup_h_v2 ± $0.01B.

Per-column conservation is exact because Phase 1 confirmed zero "mixed" rows
(rollup=can ∧ dm_rollup=dup or vice versa) for this cohort, so the union sets
involved in Op A.1 and Op A.2 are disjoint at the canonical side.

BEGIN/COMMIT wraps all 10 pairs; ROLLBACK on any guard failure.

Refs:
  docs/findings/cp-5-comprehensive-remediation.md §3.1
  docs/findings/cp-5-bundle-b-discovery.md §2.1
  docs/findings/cp-5-cycle-truncated-merges-recon-results.md (PR #284)
  docs/findings/cp-5-adams-duplicates-results.md (PR #283; Adjustment 1)
  docs/findings/inst_eid_bridge_aliases_results.md (PR #256; cp-4a brand→filer)
  docs/decisions/inst_eid_bridge_decisions.md (Adjustments 1/2/3/4 canonical)
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "cp-5-cycle-truncated-merges-manifest.csv"

OPEN_DATE = date(9999, 12, 31)
AUM_TOL_USD = 0.01 * 1e9  # $0.01B

# 13 prior bridges that must persist (PR #256 + cp-4b carve-out + PR #283 Adams).
PRIOR_BRIDGE_IDS = [
    20813, 20814,                                  # PR #256 cp-4a (Vanguard, PIMCO)
    20820, 20821, 20822, 20823,                    # cp-4b carve-out (Trowe, FT, FMR, SSGA)
    20824, 20825, 20826, 20827, 20828, 20829, 20830,  # PR #283 Adams 7-pair
]


@dataclass
class Pair:
    pair_id: int
    canonical_eid: int
    duplicate_eid: int
    label: str

    # Pre-image
    canonical_canonical_name: str = ""
    duplicate_canonical_name: str = ""

    # Pre-merge AUM (per-column, both sides)
    can_rollup_aum_pre_usd: float = 0.0
    can_dm_rollup_aum_pre_usd: float = 0.0
    dup_rollup_aum_pre_usd: float = 0.0
    dup_dm_rollup_aum_pre_usd: float = 0.0
    can_h_v2_aum_pre_usd: float = 0.0
    dup_h_v2_aum_pre_usd: float = 0.0

    # Pre-merge counts
    fh_dup_rollup_rows: int = 0
    fh_dup_dm_rollup_rows: int = 0
    h_v2_dup_rows: int = 0
    op_b_parent_count: int = 0
    op_b_child_count: int = 0
    op_b_prime_count: int = 0
    open_ech: int = 0
    open_erh_from: int = 0
    open_erh_at: int = 0
    open_aliases: int = 0
    open_identifiers: int = 0

    # Op A.4 plan
    a4_transfers: list = field(default_factory=list)

    # Post-confirm stats
    confirm_stats: dict = field(default_factory=dict)


PAIRS: list[Pair] = [
    Pair(pair_id=1,  canonical_eid=22,    duplicate_eid=17941, label="Goldman Sachs Asset Management"),
    Pair(pair_id=2,  canonical_eid=58,    duplicate_eid=18070, label="Lazard Asset Management"),
    Pair(pair_id=3,  canonical_eid=70,    duplicate_eid=18357, label="Ariel Investments"),
    Pair(pair_id=4,  canonical_eid=893,   duplicate_eid=17916, label="Lord, Abbett & Co"),
    Pair(pair_id=5,  canonical_eid=1600,  duplicate_eid=9722,  label="Financial Partners Group"),
    Pair(pair_id=6,  canonical_eid=2562,  duplicate_eid=9668,  label="Equitable Investment Management"),
    Pair(pair_id=7,  canonical_eid=2925,  duplicate_eid=18537, label="Thornburg Investment Management"),
    Pair(pair_id=8,  canonical_eid=7558,  duplicate_eid=18029, label="Fayez Sarofim & Co"),
    Pair(pair_id=9,  canonical_eid=7655,  duplicate_eid=18649, label="Leavell Investment Management"),
    Pair(pair_id=10, canonical_eid=10501, duplicate_eid=19846, label="Stonebridge Capital Advisors"),
]


def capture_preimage(con: duckdb.DuckDBPyConnection, p: Pair) -> None:
    p.canonical_canonical_name = con.execute(
        "SELECT canonical_name FROM entities WHERE entity_id = ?",
        [p.canonical_eid],
    ).fetchone()[0]
    p.duplicate_canonical_name = con.execute(
        "SELECT canonical_name FROM entities WHERE entity_id = ?",
        [p.duplicate_eid],
    ).fetchone()[0]

    # Per-column AUM and row counts.
    p.can_rollup_aum_pre_usd = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 "
        "WHERE rollup_entity_id = ? AND is_latest = TRUE",
        [p.canonical_eid],
    ).fetchone()[0])
    p.can_dm_rollup_aum_pre_usd = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 "
        "WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [p.canonical_eid],
    ).fetchone()[0])
    p.dup_rollup_aum_pre_usd = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 "
        "WHERE rollup_entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0])
    p.dup_dm_rollup_aum_pre_usd = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 "
        "WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0])

    p.fh_dup_rollup_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE rollup_entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0])
    p.fh_dup_dm_rollup_rows = int(con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0])

    # holdings_v2 (Op A.3).
    p.can_h_v2_aum_pre_usd = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM holdings_v2 "
        "WHERE entity_id = ? AND is_latest = TRUE",
        [p.canonical_eid],
    ).fetchone()[0])
    p.dup_h_v2_aum_pre_usd = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM holdings_v2 "
        "WHERE entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0])
    p.h_v2_dup_rows = int(con.execute(
        "SELECT COUNT(*) FROM holdings_v2 WHERE entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0])

    # Op B counts.
    p.op_b_parent_count = int(con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE parent_entity_id = ? AND child_entity_id != ? AND valid_to = ?",
        [p.duplicate_eid, p.canonical_eid, OPEN_DATE],
    ).fetchone()[0])
    p.op_b_child_count = int(con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE child_entity_id = ? AND parent_entity_id != ? AND valid_to = ?",
        [p.duplicate_eid, p.canonical_eid, OPEN_DATE],
    ).fetchone()[0])
    p.op_b_prime_count = int(con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE valid_to = ? AND ((parent_entity_id = ? AND child_entity_id = ?) "
        "OR (parent_entity_id = ? AND child_entity_id = ?))",
        [OPEN_DATE, p.canonical_eid, p.duplicate_eid,
         p.duplicate_eid, p.canonical_eid],
    ).fetchone()[0])

    p.open_ech = int(con.execute(
        "SELECT COUNT(*) FROM entity_classification_history "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_erh_from = int(con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_erh_at = int(con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_aliases = int(con.execute(
        "SELECT COUNT(*) FROM entity_aliases "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_identifiers = int(con.execute(
        "SELECT COUNT(*) FROM entity_identifiers "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])

    # Op A.4 plan.
    dup_ids = con.execute(
        "SELECT identifier_type, identifier_value, confidence, source, valid_from "
        "FROM entity_identifiers WHERE entity_id = ? AND valid_to = ? "
        "ORDER BY identifier_type, identifier_value",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchall()
    can_ids = {(r[0], r[1]) for r in con.execute(
        "SELECT identifier_type, identifier_value FROM entity_identifiers "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.canonical_eid, OPEN_DATE],
    ).fetchall()}
    p.a4_transfers = [
        (itype, ival, conf, src, vf)
        for (itype, ival, conf, src, vf) in dup_ids
        if (itype, ival) not in can_ids
    ]


def write_manifest(pairs: list[Pair]) -> None:
    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "pair_id", "canonical_eid", "duplicate_eid",
        "canonical_canonical_name", "duplicate_canonical_name",
        "op_a1_rows", "op_a2_rows", "op_a3_rows", "op_a4_transfers",
        "op_b_parent_count", "op_b_child_count", "op_b_prime_count",
        "op_c_count", "op_e_relationship_id", "op_f_count",
        "op_g_alias_count", "op_h_total_count",
        "rollup_aum_pre_can_b", "rollup_aum_pre_dup_b", "rollup_aum_post_expected_b",
        "dm_rollup_aum_pre_can_b", "dm_rollup_aum_pre_dup_b", "dm_rollup_aum_post_expected_b",
        "h_v2_aum_pre_can_b", "h_v2_aum_pre_dup_b", "h_v2_aum_post_expected_b",
    ]
    with MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in pairs:
            w.writerow([
                p.pair_id, p.canonical_eid, p.duplicate_eid,
                p.canonical_canonical_name, p.duplicate_canonical_name,
                p.fh_dup_rollup_rows, p.fh_dup_dm_rollup_rows,
                p.h_v2_dup_rows, len(p.a4_transfers),
                p.op_b_parent_count, p.op_b_child_count, p.op_b_prime_count,
                p.open_ech, "TBD", p.open_erh_from,
                p.open_aliases, p.open_erh_at,
                f"{p.can_rollup_aum_pre_usd / 1e9:.4f}",
                f"{p.dup_rollup_aum_pre_usd / 1e9:.4f}",
                f"{(p.can_rollup_aum_pre_usd + p.dup_rollup_aum_pre_usd) / 1e9:.4f}",
                f"{p.can_dm_rollup_aum_pre_usd / 1e9:.4f}",
                f"{p.dup_dm_rollup_aum_pre_usd / 1e9:.4f}",
                f"{(p.can_dm_rollup_aum_pre_usd + p.dup_dm_rollup_aum_pre_usd) / 1e9:.4f}",
                f"{p.can_h_v2_aum_pre_usd / 1e9:.4f}",
                f"{p.dup_h_v2_aum_pre_usd / 1e9:.4f}",
                f"{(p.can_h_v2_aum_pre_usd + p.dup_h_v2_aum_pre_usd) / 1e9:.4f}",
            ])


def execute_pair(
    con: duckdb.DuckDBPyConnection, p: Pair, next_rel_id: int
) -> dict:
    today = date.today()
    stats: dict = {}

    def _affected(cur) -> int:
        row = cur.fetchone()
        return int(row[0]) if row else 0

    # ---- Op A.1 — fund_holdings_v2.rollup_entity_id re-point ----
    cur = con.execute(
        """
        UPDATE fund_holdings_v2 SET rollup_entity_id = ?
        WHERE rollup_entity_id = ? AND is_latest = TRUE
        """,
        [p.canonical_eid, p.duplicate_eid],
    )
    stats["op_a1_rows"] = _affected(cur)

    # ---- Op A.2 — fund_holdings_v2.dm_rollup_entity_id + dm_rollup_name ----
    cur = con.execute(
        """
        UPDATE fund_holdings_v2
        SET dm_rollup_entity_id = ?, dm_rollup_name = ?
        WHERE dm_rollup_entity_id = ? AND is_latest = TRUE
        """,
        [p.canonical_eid, p.canonical_canonical_name, p.duplicate_eid],
    )
    stats["op_a2_rows"] = _affected(cur)

    # ---- Op A.3 — holdings_v2.entity_id re-point (Adjustment 2) ----
    if p.h_v2_dup_rows > 0:
        cur = con.execute(
            "UPDATE holdings_v2 SET entity_id = ? "
            "WHERE entity_id = ? AND is_latest = TRUE",
            [p.canonical_eid, p.duplicate_eid],
        )
        stats["op_a3_rows"] = _affected(cur)
    else:
        stats["op_a3_rows"] = 0

    # ---- Op A.4 — entity_identifiers SCD transfer (Adjustment 3) ----
    a4_closed = 0
    a4_inserted = 0
    for itype, ival, conf, src, vf in p.a4_transfers:
        coll = con.execute(
            "SELECT entity_id FROM entity_identifiers "
            "WHERE identifier_type = ? AND identifier_value = ? "
            "AND valid_from = ?",
            [itype, ival, today],
        ).fetchone()
        if coll is not None:
            raise RuntimeError(
                f"[pair={p.pair_id} {p.label}] Op A.4 PK collision: "
                f"({itype}, {ival}, {today}) already taken by entity {coll[0]}"
            )
        cur = con.execute(
            "UPDATE entity_identifiers SET valid_to = ? "
            "WHERE entity_id = ? AND identifier_type = ? "
            "AND identifier_value = ? AND valid_from = ? AND valid_to = ?",
            [today, p.duplicate_eid, itype, ival, vf, OPEN_DATE],
        )
        a4_closed += _affected(cur)
        con.execute(
            """
            INSERT INTO entity_identifiers
                (entity_id, identifier_type, identifier_value, confidence,
                 source, is_inferred, valid_from, valid_to, created_at)
            VALUES (?, ?, ?, ?, ?, FALSE, ?, ?, NOW())
            """,
            [p.canonical_eid, itype, ival, conf, src, today, OPEN_DATE],
        )
        a4_inserted += 1
    stats["op_a4_closed"] = a4_closed
    stats["op_a4_inserted"] = a4_inserted

    # ---- Op B — entity_relationships re-point parent + child sides ----
    cur = con.execute(
        """
        UPDATE entity_relationships
        SET parent_entity_id = ?, last_refreshed_at = NOW()
        WHERE parent_entity_id = ?
          AND child_entity_id != ?
          AND valid_to = ?
        """,
        [p.canonical_eid, p.duplicate_eid, p.canonical_eid, OPEN_DATE],
    )
    op_b_parent = _affected(cur)
    cur = con.execute(
        """
        UPDATE entity_relationships
        SET child_entity_id = ?, last_refreshed_at = NOW()
        WHERE child_entity_id = ?
          AND parent_entity_id != ?
          AND valid_to = ?
        """,
        [p.canonical_eid, p.duplicate_eid, p.canonical_eid, OPEN_DATE],
    )
    op_b_child = _affected(cur)
    stats["op_b_parent_rows"] = op_b_parent
    stats["op_b_child_rows"] = op_b_child

    # ---- Op B' — close all cycle edges (D1: N edges) ----
    cycle_edges = con.execute(
        """
        SELECT relationship_id, parent_entity_id, child_entity_id,
               relationship_type, source
        FROM entity_relationships
        WHERE valid_to = ?
          AND ((parent_entity_id = ? AND child_entity_id = ?)
            OR (parent_entity_id = ? AND child_entity_id = ?))
        ORDER BY relationship_id
        """,
        [OPEN_DATE, p.canonical_eid, p.duplicate_eid,
         p.duplicate_eid, p.canonical_eid],
    ).fetchall()
    if len(cycle_edges) == 0:
        sub_summary = "no_subsumption"
        stats["op_b_prime_rows"] = 0
    else:
        sub_parts = [f"{rt}/{pe}->{ce}/{sr}" for rid, pe, ce, rt, sr in cycle_edges]
        sub_summary = ";".join(sub_parts)
        cur = con.execute(
            """
            UPDATE entity_relationships
            SET valid_to = ?, last_refreshed_at = NOW()
            WHERE relationship_id IN ?
            """,
            [today, [r[0] for r in cycle_edges]],
        )
        stats["op_b_prime_rows"] = _affected(cur)

    # ---- Op C — close ECH ----
    cur = con.execute(
        "UPDATE entity_classification_history SET valid_to = ? "
        "WHERE entity_id = ? AND valid_to = ?",
        [today, p.duplicate_eid, OPEN_DATE],
    )
    stats["op_c_rows"] = _affected(cur)

    # ---- Op E — INSERT audit row ----
    audit_source = (
        f"CP-5-pre:cp-5-cycle-truncated-merges|pair={p.pair_id}|"
        f"merged_duplicate_to_canonical|subsumes:{sub_summary}"
    )
    con.execute(
        """
        INSERT INTO entity_relationships
            (relationship_id, parent_entity_id, child_entity_id,
             relationship_type, control_type, is_primary, primary_parent_key,
             confidence, source, is_inferred, valid_from, valid_to,
             created_at, last_refreshed_at)
        VALUES (?, ?, ?, 'parent_brand', 'merge', FALSE, NULL,
                'high', ?, FALSE, ?, ?, NOW(), NOW())
        """,
        [next_rel_id, p.canonical_eid, p.duplicate_eid, audit_source,
         today, OPEN_DATE],
    )
    stats["op_e_relationship_id"] = next_rel_id
    stats["op_e_source"] = audit_source

    # ---- Op F — close ERH FROM-side ----
    cur = con.execute(
        "UPDATE entity_rollup_history SET valid_to = ? "
        "WHERE entity_id = ? AND valid_to = ?",
        [today, p.duplicate_eid, OPEN_DATE],
    )
    stats["op_f_rows"] = _affected(cur)

    # ---- Op G — entity_aliases (ADJUSTMENT 1: close-on-collision) ----
    dup_aliases = con.execute(
        """
        SELECT alias_name, alias_type, valid_from, is_preferred
        FROM entity_aliases
        WHERE entity_id = ? AND valid_to = ?
        """,
        [p.duplicate_eid, OPEN_DATE],
    ).fetchall()
    op_g_repointed = 0
    op_g_closed = 0
    op_g_demoted = 0
    for alias_name, alias_type, valid_from, is_preferred in dup_aliases:
        coll = con.execute(
            "SELECT 1 FROM entity_aliases "
            "WHERE entity_id = ? AND alias_name = ? AND alias_type = ? "
            "AND valid_from = ? AND valid_to = ? LIMIT 1",
            [p.canonical_eid, alias_name, alias_type, valid_from, OPEN_DATE],
        ).fetchone()
        if coll is not None:
            cur = con.execute(
                "UPDATE entity_aliases SET valid_to = ? "
                "WHERE entity_id = ? AND alias_name = ? AND alias_type = ? "
                "AND valid_from = ? AND valid_to = ?",
                [today, p.duplicate_eid, alias_name, alias_type, valid_from, OPEN_DATE],
            )
            op_g_closed += _affected(cur)
        else:
            if is_preferred:
                cur = con.execute(
                    "UPDATE entity_aliases SET is_preferred = FALSE "
                    "WHERE entity_id = ? AND alias_type = ? "
                    "AND alias_name != ? AND is_preferred = TRUE "
                    "AND valid_to = ?",
                    [p.canonical_eid, alias_type, alias_name, OPEN_DATE],
                )
                op_g_demoted += _affected(cur)
            cur = con.execute(
                "UPDATE entity_aliases SET entity_id = ? "
                "WHERE entity_id = ? AND alias_name = ? AND alias_type = ? "
                "AND valid_from = ? AND valid_to = ?",
                [p.canonical_eid, p.duplicate_eid, alias_name, alias_type, valid_from, OPEN_DATE],
            )
            op_g_repointed += _affected(cur)
    stats["op_g_repointed"] = op_g_repointed
    stats["op_g_closed"] = op_g_closed
    stats["op_g_demoted"] = op_g_demoted

    # ---- Op H — entity_rollup_history AT-side cleanup ----
    op_h_b1 = 0
    op_h_b2 = 0

    branch_1_rows = con.execute(
        """
        SELECT entity_id, rollup_type, rule_applied, confidence,
               source, routing_confidence, review_due_date, valid_from
        FROM entity_rollup_history
        WHERE rollup_entity_id = ? AND valid_to = ?
          AND NOT (entity_id = ? AND rollup_entity_id = ?)
        """,
        [p.duplicate_eid, OPEN_DATE, p.canonical_eid, p.duplicate_eid],
    ).fetchall()
    if branch_1_rows:
        for entity_id, rollup_type in [(int(r[0]), r[1]) for r in branch_1_rows]:
            coll = con.execute(
                """
                SELECT 1 FROM entity_rollup_history
                WHERE entity_id = ? AND rollup_type = ?
                  AND rollup_entity_id = ? AND valid_to = ?
                LIMIT 1
                """,
                [entity_id, rollup_type, p.canonical_eid, OPEN_DATE],
            ).fetchone()
            if coll is not None:
                raise RuntimeError(
                    f"[pair={p.pair_id} {p.label}] Op H B1 collision: "
                    f"canonical {p.canonical_eid} already has open ERH for "
                    f"entity_id={entity_id} rollup_type={rollup_type}"
                )
        cur = con.execute(
            """
            UPDATE entity_rollup_history SET valid_to = ?
            WHERE rollup_entity_id = ? AND valid_to = ?
              AND NOT (entity_id = ? AND rollup_entity_id = ?)
            """,
            [today, p.duplicate_eid, OPEN_DATE, p.canonical_eid, p.duplicate_eid],
        )
        b1_closed = _affected(cur)
        for (entity_id, rollup_type, rule_applied, confidence, source,
             routing_conf, review_due, _vf_old) in branch_1_rows:
            con.execute(
                """
                INSERT INTO entity_rollup_history
                    (entity_id, rollup_entity_id, rollup_type, rule_applied,
                     confidence, valid_from, valid_to, computed_at, source,
                     routing_confidence, review_due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, NOW(), ?, ?, ?)
                """,
                [entity_id, p.canonical_eid, rollup_type, rule_applied,
                 confidence, today, OPEN_DATE, source, routing_conf, review_due],
            )
        op_h_b1 = len(branch_1_rows)
        if b1_closed != op_h_b1:
            raise RuntimeError(
                f"[pair={p.pair_id}] Op H B1 close mismatch: "
                f"closed={b1_closed} expected={op_h_b1}"
            )

    branch_2_rows = con.execute(
        """
        SELECT entity_id, rollup_type
        FROM entity_rollup_history
        WHERE entity_id = ? AND rollup_entity_id = ? AND valid_to = ?
        """,
        [p.canonical_eid, p.duplicate_eid, OPEN_DATE],
    ).fetchall()
    if branch_2_rows:
        cur = con.execute(
            """
            UPDATE entity_rollup_history SET valid_to = ?
            WHERE entity_id = ? AND rollup_entity_id = ? AND valid_to = ?
            """,
            [today, p.canonical_eid, p.duplicate_eid, OPEN_DATE],
        )
        b2_closed = _affected(cur)
        b2_inserted = 0
        for entity_id, rollup_type in branch_2_rows:
            existing_self = con.execute(
                """
                SELECT 1 FROM entity_rollup_history
                WHERE entity_id = ? AND rollup_entity_id = ?
                  AND rollup_type = ? AND valid_to = ?
                LIMIT 1
                """,
                [entity_id, entity_id, rollup_type, OPEN_DATE],
            ).fetchone()
            if existing_self is not None:
                continue
            con.execute(
                """
                INSERT INTO entity_rollup_history
                    (entity_id, rollup_entity_id, rollup_type, rule_applied,
                     confidence, valid_from, valid_to, computed_at, source,
                     routing_confidence, review_due_date)
                VALUES (?, ?, ?, 'self', 'exact', ?, ?, NOW(), ?, 'high', NULL)
                """,
                [entity_id, p.canonical_eid, rollup_type, today, OPEN_DATE,
                 f"CP-5-pre:cp-5-cycle-truncated-merges|pair={p.pair_id}"],
            )
            b2_inserted += 1
        op_h_b2 = b2_inserted
        if b2_closed != len(branch_2_rows):
            raise RuntimeError(
                f"[pair={p.pair_id}] Op H B2 close mismatch: "
                f"closed={b2_closed} expected={len(branch_2_rows)}"
            )

    stats["op_h_branch_1"] = op_h_b1
    stats["op_h_branch_2"] = op_h_b2

    # ---- Hard guards (11 per pair) ----
    g1a = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE rollup_entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0]
    if g1a != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 1a fail: {g1a} fh_v2 rows still have rollup=dup")

    g1b = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0]
    if g1b != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 1b fail: {g1b} fh_v2 rows still have dm_rollup=dup")

    g1c = con.execute(
        "SELECT COUNT(*) FROM holdings_v2 WHERE entity_id = ? AND is_latest = TRUE",
        [p.duplicate_eid],
    ).fetchone()[0]
    if g1c != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 1c fail: {g1c} h_v2 rows still ref dup")

    g2 = con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        "WHERE valid_to = ? AND (parent_entity_id = ? OR child_entity_id = ?)",
        [OPEN_DATE, p.duplicate_eid, p.duplicate_eid],
    ).fetchone()[0]
    if g2 != 1:
        raise RuntimeError(
            f"[pair={p.pair_id}] Guard 2 fail: {g2} open rels ref dup (expected 1: Op E audit)"
        )

    g3 = con.execute(
        "SELECT COUNT(*) FROM entity_classification_history "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if g3 != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 3 fail: {g3} ECH still open on dup")

    g4 = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if g4 != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 4 fail: {g4} ERH FROM open on dup")

    g5 = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history "
        "WHERE rollup_entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if g5 != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 5 fail: {g5} ERH AT open on dup")

    g6 = con.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if g6 != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 6 fail: {g6} aliases open on dup")

    g6b = con.execute(
        "SELECT COUNT(*) FROM entity_identifiers WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if g6b != 0:
        raise RuntimeError(f"[pair={p.pair_id}] Guard 6b fail: {g6b} identifiers open on dup")

    # ---- Guard 7a/7b/7c — AUM conservation, per-column exact ----
    post_can_rollup = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 "
        "WHERE rollup_entity_id = ? AND is_latest = TRUE",
        [p.canonical_eid],
    ).fetchone()[0])
    expected_rollup = p.can_rollup_aum_pre_usd + p.dup_rollup_aum_pre_usd
    delta_rollup = abs(post_can_rollup - expected_rollup)
    if delta_rollup > AUM_TOL_USD:
        raise RuntimeError(
            f"[pair={p.pair_id}] Guard 7a (rollup) fail: "
            f"post=${post_can_rollup/1e9:.4f}B expected=${expected_rollup/1e9:.4f}B "
            f"delta=${delta_rollup/1e9:.6f}B"
        )

    post_can_dm = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 "
        "WHERE dm_rollup_entity_id = ? AND is_latest = TRUE",
        [p.canonical_eid],
    ).fetchone()[0])
    expected_dm = p.can_dm_rollup_aum_pre_usd + p.dup_dm_rollup_aum_pre_usd
    delta_dm = abs(post_can_dm - expected_dm)
    if delta_dm > AUM_TOL_USD:
        raise RuntimeError(
            f"[pair={p.pair_id}] Guard 7b (dm_rollup) fail: "
            f"post=${post_can_dm/1e9:.4f}B expected=${expected_dm/1e9:.4f}B "
            f"delta=${delta_dm/1e9:.6f}B"
        )

    post_can_h = float(con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM holdings_v2 "
        "WHERE entity_id = ? AND is_latest = TRUE",
        [p.canonical_eid],
    ).fetchone()[0])
    expected_h = p.can_h_v2_aum_pre_usd + p.dup_h_v2_aum_pre_usd
    delta_h = abs(post_can_h - expected_h)
    if delta_h > AUM_TOL_USD:
        raise RuntimeError(
            f"[pair={p.pair_id}] Guard 7c (h_v2) fail: "
            f"post=${post_can_h/1e9:.4f}B expected=${expected_h/1e9:.4f}B "
            f"delta=${delta_h/1e9:.6f}B"
        )

    stats["post_canonical_rollup_aum_usd"] = post_can_rollup
    stats["post_canonical_dm_rollup_aum_usd"] = post_can_dm
    stats["post_canonical_h_v2_aum_usd"] = post_can_h
    stats["aum_delta_rollup_usd"] = delta_rollup
    stats["aum_delta_dm_rollup_usd"] = delta_dm
    stats["aum_delta_h_v2_usd"] = delta_h

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            for p in PAIRS:
                capture_preimage(con, p)
        finally:
            con.close()
        write_manifest(PAIRS)
        print(f"[dry-run] manifest: {MANIFEST_CSV}")
        for p in PAIRS:
            print(
                f"[dry-run] pair={p.pair_id:>2} {p.label[:36]:<36} "
                f"can={p.canonical_eid:>5} dup={p.duplicate_eid:>5}: "
                f"a1={p.fh_dup_rollup_rows:>6} a2={p.fh_dup_dm_rollup_rows:>6} "
                f"a3={p.h_v2_dup_rows:>4} a4={len(p.a4_transfers):>2} "
                f"b_par={p.op_b_parent_count:>3} b_chi={p.op_b_child_count:>2} "
                f"b'={p.op_b_prime_count} ech={p.open_ech} erh_F={p.open_erh_from} "
                f"erh_A={p.open_erh_at:>3} al={p.open_aliases} ids={p.open_identifiers}"
            )
        tot_dup_rollup = sum(p.dup_rollup_aum_pre_usd for p in PAIRS) / 1e9
        tot_dup_dm = sum(p.dup_dm_rollup_aum_pre_usd for p in PAIRS) / 1e9
        tot_dup_h = sum(p.dup_h_v2_aum_pre_usd for p in PAIRS) / 1e9
        print(
            f"[dry-run] cohort totals — dup_rollup_aum=${tot_dup_rollup:.4f}B "
            f"dup_dm_rollup_aum=${tot_dup_dm:.4f}B "
            f"dup_h_v2_aum=${tot_dup_h:.4f}B"
        )
        return 0

    # --confirm path
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        for p in PAIRS:
            capture_preimage(con, p)

        prior = con.execute(
            "SELECT relationship_id FROM entity_relationships "
            "WHERE relationship_id IN ?",
            [PRIOR_BRIDGE_IDS],
        ).fetchall()
        found = {int(r[0]) for r in prior}
        missing = set(PRIOR_BRIDGE_IDS) - found
        if missing:
            raise RuntimeError(f"prior bridges missing: {sorted(missing)}")

        max_rel_id = con.execute(
            "SELECT COALESCE(MAX(relationship_id), 0) FROM entity_relationships"
        ).fetchone()[0]
        rel_ids = list(range(max_rel_id + 1, max_rel_id + 1 + len(PAIRS)))
        print(f"[confirm] Op E relationship_ids: {rel_ids[0]}..{rel_ids[-1]}")

        con.execute("BEGIN")
        try:
            for p, next_rel_id in zip(PAIRS, rel_ids):
                p.confirm_stats = execute_pair(con, p, next_rel_id)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()

    print("[confirm] DONE — all 110 hard guards (11 × 10 pairs) passed")
    for p in PAIRS:
        s = p.confirm_stats
        print(
            f"[confirm] pair={p.pair_id:>2} {p.label[:32]:<32} "
            f"{p.canonical_eid:>5}<-{p.duplicate_eid:>5}: "
            f"a1={s['op_a1_rows']} a2={s['op_a2_rows']} a3={s['op_a3_rows']} "
            f"a4=({s['op_a4_closed']},{s['op_a4_inserted']}) "
            f"b=({s['op_b_parent_rows']},{s['op_b_child_rows']}) b'={s['op_b_prime_rows']} "
            f"c={s['op_c_rows']} e_id={s['op_e_relationship_id']} f={s['op_f_rows']} "
            f"g_rep={s['op_g_repointed']} g_close={s['op_g_closed']} g_dem={s['op_g_demoted']} "
            f"h1={s['op_h_branch_1']} h2={s['op_h_branch_2']} "
            f"Δrollup=${s['aum_delta_rollup_usd']/1e9:.6f}B "
            f"Δdm=${s['aum_delta_dm_rollup_usd']/1e9:.6f}B "
            f"Δh_v2=${s['aum_delta_h_v2_usd']/1e9:.6f}B"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
