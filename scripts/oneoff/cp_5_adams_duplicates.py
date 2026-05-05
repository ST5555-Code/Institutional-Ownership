#!/usr/bin/env python3
"""cp_5_adams_duplicates.py — Adams duplicate-eid cohort MERGE.

First P0 pre-execution PR per docs/findings/cp-5-comprehensive-remediation.md
§3.4. Closes the 14-entity Adams cohort surfaced in Bundle B Phase 3.3 by
merging 7 duplicate-eid pairs (canonical <- duplicate) using the cp-4a-style
8-op MERGE shape per PR #256 precedent, with Adjustment 1 (close-on-collision
in Op G) for chained-merge alias PK collisions.

Op shape (per pair, 8 ops, single transaction across ALL pairs):

  Op A  fund_holdings_v2 re-point
        UPDATE rollup_entity_id, dm_rollup_entity_id, dm_rollup_name
        WHERE (rollup_entity_id = :duplicate OR dm_rollup_entity_id = :duplicate)
              AND is_latest = TRUE
        Note: entity_id and dm_entity_id are FUND-level identity and never
        carry a duplicate-typed eid in this cohort (all duplicate fund eids
        have ZERO fh_v2 footprint per Phase 1 recon); Op A is no-op for
        pairs 2-7.

  Op B  entity_relationships re-point parent edges
        UPDATE parent_entity_id = :canonical
        WHERE parent_entity_id = :duplicate
              AND child_entity_id != :canonical
              AND valid_to = DATE '9999-12-31'

  Op B' entity_relationships close subsumed canonical<->duplicate edge
        Captures the row, then closes (valid_to = CURRENT_DATE).
        Pair 1 (4909 <- 19509): rel_id=15149 wholly_owned (orphan_scan).
        Pairs 2-7: rel_id=16137..16142 fund_sponsor (fund_cik_sibling).

  Op C  entity_classification_history close duplicate-side
        UPDATE valid_to = CURRENT_DATE WHERE entity_id = :duplicate AND
        valid_to = open. (Pair 1: 1 row. Pairs 2-7: 0 rows; duplicates have
        no open ECH.)

  Op E  entity_relationships INSERT audit row
        relationship_type='parent_brand', control_type='merge'
        source = 'CP-5-pre:cp-5-adams-duplicates|pair=<N>|merged_duplicate_to_canonical|subsumes:<type>/<p>-><c>/<orig_src>'
        relationship_id = sequential MAX+1 .. MAX+N

  Op F  entity_rollup_history close duplicate-side FROM
        UPDATE valid_to = CURRENT_DATE WHERE entity_id = :duplicate AND
        valid_to = open.

  Op G  entity_aliases re-point — ADJUSTMENT 1 (close-on-collision)
        Per duplicate-side alias D, before re-pointing:

          collision = EXISTS (SELECT 1 FROM entity_aliases
                              WHERE entity_id = :canonical
                                AND alias_name = D.alias_name
                                AND alias_type = D.alias_type
                                AND valid_from = D.valid_from
                                AND valid_to = open)

          If collision:
            CLOSE-ON-COLLISION:
              UPDATE entity_aliases SET valid_to = CURRENT_DATE
              WHERE entity_id = :duplicate AND alias_name = D.alias_name
                AND alias_type = D.alias_type AND valid_from = D.valid_from
                AND valid_to = open;
            (Canonical's existing alias preserved; duplicate's redundant.)

          Else:
            RE-POINT (cp-4a precedent):
              If D.is_preferred AND canonical has open preferred=TRUE
              alias of same alias_type (alias_name != D.alias_name):
                Demote canonical's preferred=FALSE.
              UPDATE entity_aliases SET entity_id = :canonical
              WHERE entity_id = :duplicate AND alias_name = D.alias_name
                AND alias_type = D.alias_type AND valid_from = D.valid_from
                AND valid_to = open;

        Pair processing order: (canonical_eid, pair_id) asc. This makes
        chained-collision pairs predictable: pair 2 re-points first, then
        pairs 3/4 close-on-collision against canonical's now-mixed-case
        alias. Same for pairs 5/6/7.

  Op H  entity_rollup_history AT-side cleanup
        Branch 1 — general AT-side re-point (excludes canonical self-rollup case):
          For each open ERH row where rollup_entity_id=:duplicate AND NOT
          (entity_id=:canonical AND rollup_entity_id=:duplicate):
            close the row, then insert a new row with rollup_entity_id=:canonical
            preserving rule_applied, confidence, source, routing_confidence,
            review_due_date.
          Pair 1: 2 rows for fund 16030 (decision_maker_v1, economic_control_v1).
          Pairs 2-7: 0 rows.
        Branch 2 — canonical self-rollup recreate:
          For each open ERH row where entity_id=:canonical AND
          rollup_entity_id=:duplicate:
            close + insert fresh self-rollup (rollup_entity_id=:canonical,
            rule_applied='self', confidence='exact', source='CP-5-pre:cp-5-adams-duplicates|pair=<N>',
            routing_confidence='high', review_due_date=NULL).
          Pair 1: 2 rows (canonical 4909 currently rolls UP to duplicate 19509;
          merge inverts this — surfaced anomaly per Phase 1 recon).
          Pairs 2-7: 0 rows (canonicals 2961/6471 already self-roll correctly).

Hard guards (per pair, asserted before COMMIT):
  1. Zero leftover duplicate refs in fund_holdings_v2 (rollup or dm_rollup).
  2. <=1 open relationship referencing duplicate (the Op E audit row).
  3. Zero open ECH rows on duplicate.
  4. Zero open ERH FROM-side rows on duplicate.
  5. Zero open ERH AT-side rows on duplicate.
  6. Zero open alias rows on duplicate.
  7. AUM conservation: post-merge canonical AUM = pre-merge canonical AUM +
     duplicate AUM (within $0.01B tolerance). Trivially $0.000000B for all
     7 pairs since duplicates have $0 holdings.

BEGIN/COMMIT wraps all 7 pairs; ROLLBACK on any constraint violation.

Refs:
  docs/findings/cp-5-comprehensive-remediation.md §3.4
  docs/findings/cp-5-bundle-b-discovery.md §3.3 (Adams cohort)
  data/working/cp-5-bundle-b-adams-cohort.csv (PR #278 manifest)
  docs/findings/inst_eid_bridge_aliases_results.md (PR #256 cp-4a op-shape precedent)
  docs/decisions/inst_eid_bridge_decisions.md (Adjustment 1 op-shape canonical addendum)
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
MANIFEST_CSV = BASE_DIR / "data" / "working" / "cp-5-adams-duplicates-manifest.csv"
RESULTS_DOC = BASE_DIR / "docs" / "findings" / "cp-5-adams-duplicates-results.md"

OPEN_DATE = date(9999, 12, 31)
AUM_CONSERVATION_TOLERANCE_USD = 0.01 * 1e9  # $0.01B

PRIOR_BRIDGE_IDS = [20813, 20814, 20820, 20821, 20822, 20823]


@dataclass
class Pair:
    pair_id: int
    canonical_eid: int
    duplicate_eid: int
    label: str  # "Adams Asset Advisors" etc.

    # Pre-image
    canonical_canonical_name: str = ""
    duplicate_canonical_name: str = ""
    fh_dup_rows: int = 0
    fh_dup_aum_usd: float = 0.0
    fh_can_rows_pre: int = 0
    fh_can_aum_pre_usd: float = 0.0
    op_b_repoint_count: int = 0
    open_ech: int = 0
    open_erh_from: int = 0
    open_erh_at_total: int = 0
    open_aliases: int = 0

    # Post-confirm
    confirm_stats: dict = field(default_factory=dict)


# Pairs in (canonical_eid, pair_id) ascending order. This is the processing
# order used by --confirm so chained-collision semantics are stable: pair 2
# re-points its mixed-case alias to canonical 2961 first, then pairs 3/4
# close-on-collision against canonical's now-mixed-case alias. Same for 6471.
PAIRS: list[Pair] = [
    Pair(pair_id=2, canonical_eid=2961, duplicate_eid=20213, label="Adams Diversified Equity Fund"),
    Pair(pair_id=3, canonical_eid=2961, duplicate_eid=20214, label="Adams Diversified Equity Fund"),
    Pair(pair_id=4, canonical_eid=2961, duplicate_eid=20215, label="Adams Diversified Equity Fund"),
    Pair(pair_id=1, canonical_eid=4909, duplicate_eid=19509, label="Adams Asset Advisors"),
    Pair(pair_id=5, canonical_eid=6471, duplicate_eid=20210, label="Adams Natural Resources Fund"),
    Pair(pair_id=6, canonical_eid=6471, duplicate_eid=20211, label="Adams Natural Resources Fund"),
    Pair(pair_id=7, canonical_eid=6471, duplicate_eid=20212, label="Adams Natural Resources Fund"),
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

    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.duplicate_eid, p.duplicate_eid],
    ).fetchone()
    p.fh_dup_rows = int(row[0])
    p.fh_dup_aum_usd = float(row[1])

    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.canonical_eid, p.canonical_eid],
    ).fetchone()
    p.fh_can_rows_pre = int(row[0])
    p.fh_can_aum_pre_usd = float(row[1])

    p.op_b_repoint_count = int(con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE parent_entity_id = ? AND child_entity_id != ?
          AND valid_to = ?
        """,
        [p.duplicate_eid, p.canonical_eid, OPEN_DATE],
    ).fetchone()[0])

    p.open_ech = int(con.execute(
        "SELECT COUNT(*) FROM entity_classification_history WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_erh_from = int(con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_erh_at_total = int(con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE rollup_entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])
    p.open_aliases = int(con.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0])


def write_manifest(pairs: list[Pair]) -> None:
    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "pair_id", "canonical_eid", "duplicate_eid",
        "canonical_name", "duplicate_name",
        "duplicate_aum_b", "canonical_aum_pre_b", "canonical_aum_post_expected_b",
        "fh_dup_rows", "op_b_repoint_count", "op_b_prime_count",
        "op_c_count", "op_e_relationship_id", "op_f_count",
        "op_g_alias_count", "op_h_total_count",
    ]
    with MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        # Sequential MAX+1..MAX+N for Op E. Compute on dry-run.
        for p in pairs:
            w.writerow([
                p.pair_id, p.canonical_eid, p.duplicate_eid,
                p.canonical_canonical_name, p.duplicate_canonical_name,
                f"{p.fh_dup_aum_usd / 1e9:.4f}",
                f"{p.fh_can_aum_pre_usd / 1e9:.4f}",
                f"{(p.fh_can_aum_pre_usd + p.fh_dup_aum_usd) / 1e9:.4f}",
                p.fh_dup_rows, p.op_b_repoint_count, 1,
                p.open_ech, "TBD",  # filled in --confirm
                p.open_erh_from, p.open_aliases, p.open_erh_at_total,
            ])


def execute_pair(con: duckdb.DuckDBPyConnection, p: Pair, next_rel_id: int) -> dict:
    today = date.today()
    stats: dict = {}

    def _affected(cur) -> int:
        row = cur.fetchone()
        return int(row[0]) if row else 0

    # ---- Op A — fund_holdings_v2 re-point ----
    cur = con.execute(
        """
        UPDATE fund_holdings_v2
        SET rollup_entity_id = ?, dm_rollup_entity_id = ?, dm_rollup_name = ?
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.canonical_eid, p.canonical_eid, p.canonical_canonical_name,
         p.duplicate_eid, p.duplicate_eid],
    )
    stats["op_a_rows"] = _affected(cur)

    # ---- Op B — entity_relationships re-point parent edges ----
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
    stats["op_b_rows"] = _affected(cur)

    # ---- Op B' — capture + close subsumed canonical<->duplicate edges ----
    subsumed = con.execute(
        """
        SELECT relationship_id, parent_entity_id, child_entity_id,
               relationship_type, source
        FROM entity_relationships
        WHERE valid_to = ?
          AND ( (parent_entity_id = ? AND child_entity_id = ?)
             OR (parent_entity_id = ? AND child_entity_id = ?) )
        """,
        [OPEN_DATE, p.canonical_eid, p.duplicate_eid,
         p.duplicate_eid, p.canonical_eid],
    ).fetchall()
    if len(subsumed) == 0:
        # No direct edge — Op B' is no-op. Encode that in source.
        sub_summary = "no_subsumption"
        stats["op_b_prime_rows"] = 0
    elif len(subsumed) == 1:
        sub_rel_id, sub_parent, sub_child, sub_type, sub_source = subsumed[0]
        sub_summary = f"{sub_type}/{sub_parent}->{sub_child}/{sub_source}"
        cur = con.execute(
            """
            UPDATE entity_relationships
            SET valid_to = ?, last_refreshed_at = NOW()
            WHERE relationship_id = ?
            """,
            [today, sub_rel_id],
        )
        stats["op_b_prime_rows"] = _affected(cur)
    else:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Op B' expected 0 or 1 subsumed row, got {len(subsumed)}"
        )

    # ---- Op C — close ECH ----
    cur = con.execute(
        """
        UPDATE entity_classification_history
        SET valid_to = ?
        WHERE entity_id = ? AND valid_to = ?
        """,
        [today, p.duplicate_eid, OPEN_DATE],
    )
    stats["op_c_rows"] = _affected(cur)

    # ---- Op E — INSERT audit row ----
    audit_source = (
        f"CP-5-pre:cp-5-adams-duplicates|pair={p.pair_id}|"
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
        [next_rel_id, p.canonical_eid, p.duplicate_eid, audit_source, today, OPEN_DATE],
    )
    stats["op_e_relationship_id"] = next_rel_id
    stats["op_e_source"] = audit_source

    # ---- Op F — close ERH FROM-side ----
    cur = con.execute(
        """
        UPDATE entity_rollup_history
        SET valid_to = ?
        WHERE entity_id = ? AND valid_to = ?
        """,
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
        # Collision check
        collides = con.execute(
            """
            SELECT 1 FROM entity_aliases
            WHERE entity_id = ?
              AND alias_name = ?
              AND alias_type = ?
              AND valid_from = ?
              AND valid_to = ?
            LIMIT 1
            """,
            [p.canonical_eid, alias_name, alias_type, valid_from, OPEN_DATE],
        ).fetchone()
        if collides is not None:
            # Branch CLOSE-ON-COLLISION
            cur = con.execute(
                """
                UPDATE entity_aliases SET valid_to = ?
                WHERE entity_id = ? AND alias_name = ? AND alias_type = ?
                  AND valid_from = ? AND valid_to = ?
                """,
                [today, p.duplicate_eid, alias_name, alias_type, valid_from, OPEN_DATE],
            )
            op_g_closed += _affected(cur)
        else:
            # Branch RE-POINT (cp-4a precedent + scoped preferred-conflict demotion)
            if is_preferred:
                cur = con.execute(
                    """
                    UPDATE entity_aliases SET is_preferred = FALSE
                    WHERE entity_id = ?
                      AND alias_type = ?
                      AND alias_name != ?
                      AND is_preferred = TRUE
                      AND valid_to = ?
                    """,
                    [p.canonical_eid, alias_type, alias_name, OPEN_DATE],
                )
                op_g_demoted += _affected(cur)
            cur = con.execute(
                """
                UPDATE entity_aliases SET entity_id = ?
                WHERE entity_id = ? AND alias_name = ? AND alias_type = ?
                  AND valid_from = ? AND valid_to = ?
                """,
                [p.canonical_eid, p.duplicate_eid, alias_name, alias_type, valid_from, OPEN_DATE],
            )
            op_g_repointed += _affected(cur)

    stats["op_g_repointed"] = op_g_repointed
    stats["op_g_closed"] = op_g_closed
    stats["op_g_demoted"] = op_g_demoted

    # ---- Op H — entity_rollup_history AT-side ----
    op_h_b1 = 0
    op_h_b2 = 0

    # Branch 1 — general AT-side re-point (excludes canonical self-rollup case).
    # After Op F closed entity_id=duplicate rows (including duplicate's own
    # self-rollup at rollup_entity_id=duplicate), the remaining open rows
    # where rollup_entity_id=duplicate are entity_id != duplicate.
    branch_1_rows = con.execute(
        """
        SELECT entity_id, rollup_type, rule_applied, confidence,
               source, routing_confidence, review_due_date
        FROM entity_rollup_history
        WHERE rollup_entity_id = ? AND valid_to = ?
          AND NOT (entity_id = ? AND rollup_entity_id = ?)
        """,
        [p.duplicate_eid, OPEN_DATE, p.canonical_eid, p.duplicate_eid],
    ).fetchall()
    if branch_1_rows:
        # Pre-flight collision check at canonical
        b1_eids = [int(r[0]) for r in branch_1_rows]
        coll = con.execute(
            """
            SELECT entity_id, rollup_type FROM entity_rollup_history
            WHERE entity_id IN ?
              AND rollup_entity_id = ?
              AND valid_to = ?
            """,
            [b1_eids, p.canonical_eid, OPEN_DATE],
        ).fetchall()
        if coll:
            raise RuntimeError(
                f"[pair={p.pair_id} {p.label}] Op H Branch 1 collision: "
                f"canonical {p.canonical_eid} already has open rollup rows for "
                f"{[(int(r[0]), r[1]) for r in coll]}"
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
        for entity_id, rollup_type, rule_applied, confidence, source, routing_conf, review_due in branch_1_rows:
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
                f"[pair={p.pair_id}] Op H Branch 1 close count mismatch: closed={b1_closed} expected={op_h_b1}"
            )

    # Branch 2 — canonical self-rollup recreate
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
        # Pre-flight: canonical may already have an open self-rollup at the
        # same rollup_type (e.g. canonicals 2961, 6471 do). If so we skip the
        # insert. Pair 1 (4909) does NOT have one — recreation populates the
        # missing self-row.
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
                 f"CP-5-pre:cp-5-adams-duplicates|pair={p.pair_id}"],
            )
            b2_inserted += 1
        op_h_b2 = b2_inserted
        if b2_closed != len(branch_2_rows):
            raise RuntimeError(
                f"[pair={p.pair_id}] Op H Branch 2 close count mismatch: closed={b2_closed} expected={len(branch_2_rows)}"
            )

    stats["op_h_branch_1"] = op_h_b1
    stats["op_h_branch_2"] = op_h_b2

    # ---- Hard guards ----
    leftover_fh = con.execute(
        """
        SELECT COUNT(*) FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.duplicate_eid, p.duplicate_eid],
    ).fetchone()[0]
    if leftover_fh != 0:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 1 failed: {leftover_fh} fund_holdings_v2 rows still ref duplicate"
        )

    open_dup_rels = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = ? AND (parent_entity_id = ? OR child_entity_id = ?)
        """,
        [OPEN_DATE, p.duplicate_eid, p.duplicate_eid],
    ).fetchone()[0]
    if open_dup_rels > 1:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 2 failed: {open_dup_rels} open relationships ref duplicate (expected <=1: Op E audit row)"
        )

    open_dup_ech = con.execute(
        "SELECT COUNT(*) FROM entity_classification_history WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_dup_ech != 0:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 3 failed: {open_dup_ech} ECH rows still open on duplicate"
        )

    open_dup_erh_from = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_dup_erh_from != 0:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 4 failed: {open_dup_erh_from} ERH FROM-side rows open"
        )

    open_dup_erh_at = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE rollup_entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_dup_erh_at != 0:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 5 failed: {open_dup_erh_at} ERH AT-side rows open"
        )

    open_dup_aliases = con.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = ?",
        [p.duplicate_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_dup_aliases != 0:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 6 failed: {open_dup_aliases} alias rows open on duplicate"
        )

    # AUM conservation
    post_can_aum = con.execute(
        """
        SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.canonical_eid, p.canonical_eid],
    ).fetchone()[0]
    expected = p.fh_can_aum_pre_usd + p.fh_dup_aum_usd
    delta = abs(float(post_can_aum) - expected)
    if delta > AUM_CONSERVATION_TOLERANCE_USD:
        raise RuntimeError(
            f"[pair={p.pair_id} {p.label}] Guard 7 failed: AUM conservation "
            f"post=${float(post_can_aum)/1e9:,.4f}B expected=${expected/1e9:,.4f}B "
            f"delta=${delta/1e9:,.6f}B"
        )
    stats["post_canonical_aum_usd"] = float(post_can_aum)
    stats["aum_conservation_delta_usd"] = float(delta)

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
                f"[dry-run] pair={p.pair_id} {p.label} canonical={p.canonical_eid} duplicate={p.duplicate_eid}: "
                f"fh_dup_rows={p.fh_dup_rows} fh_dup_aum=${p.fh_dup_aum_usd/1e9:,.4f}B "
                f"op_b={p.op_b_repoint_count} ech={p.open_ech} erh_from={p.open_erh_from} "
                f"erh_at={p.open_erh_at_total} aliases={p.open_aliases}"
            )
        return 0

    # --confirm path
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        for p in PAIRS:
            capture_preimage(con, p)

        # Confirm prior CP-4 bridges still present
        prior = con.execute(
            "SELECT relationship_id FROM entity_relationships WHERE relationship_id IN ?",
            [PRIOR_BRIDGE_IDS],
        ).fetchall()
        found = {int(r[0]) for r in prior}
        missing = set(PRIOR_BRIDGE_IDS) - found
        if missing:
            raise RuntimeError(f"prior CP-4 bridges missing: {sorted(missing)}")

        # Allocate sequential relationship_ids
        max_rel_id = con.execute(
            "SELECT COALESCE(MAX(relationship_id), 0) FROM entity_relationships"
        ).fetchone()[0]
        rel_ids = list(range(max_rel_id + 1, max_rel_id + 1 + len(PAIRS)))

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

    print("[confirm] DONE")
    for p in PAIRS:
        s = p.confirm_stats
        print(
            f"[confirm] pair={p.pair_id} {p.label} {p.canonical_eid}<-{p.duplicate_eid}: "
            f"a={s['op_a_rows']} b={s['op_b_rows']} b'={s['op_b_prime_rows']} "
            f"c={s['op_c_rows']} e_id={s['op_e_relationship_id']} f={s['op_f_rows']} "
            f"g_repoint={s['op_g_repointed']} g_close={s['op_g_closed']} g_demote={s['op_g_demoted']} "
            f"h_b1={s['op_h_branch_1']} h_b2={s['op_h_branch_2']} "
            f"aum_delta=${s['aum_conservation_delta_usd']/1e9:,.6f}B"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
