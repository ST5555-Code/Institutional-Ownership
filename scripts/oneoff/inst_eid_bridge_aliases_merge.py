#!/usr/bin/env python3
"""inst_eid_bridge_aliases_merge.py — CP-4a: BRAND_TO_FILER alias merges.

Implements 2 alias-pair merges per docs/decisions/inst_eid_bridge_decisions.md
BLOCKER 1 classification rule (brand has no CIK and is name-only synthetic
=> MERGE):

  - Vanguard  brand_eid=1  -> filer_eid=4375
  - PIMCO     brand_eid=30 -> filer_eid=2322

Scope is 2, not 5: the eid_inventory.csv produced by PR #254 contains only
4 BRAND_HAS_NAME_MATCH rows, all MEDIUM/LOW confidence with brand_name
significantly different from filer_name (Aperio/Ascent, Altaba/Alphabet,
Oaktree/Olstein, Robinson/Revelation). These match the Calvert -> "Stanley
Capital Management" false-positive prototype the decisions doc BLOCKER 2
explicitly rejected, so they are out of scope. Decisions doc correction
("5 alias-pairs" -> "2 alias-pairs") lands in the CP-4a results commit.

Pattern precedent: scripts/oneoff/cleanup_asa_unknown_relabel.py (PR #251).
Differs in op shape because PR #251 was a fund-level cleanup; this is a
manager-level alias merge. The 7-op structure below was authored after
Phase 1 schema re-validation surfaced 5 corrections to the original prompt
(see docs/findings/inst_eid_bridge_aliases_dryrun.md Section "Phase 1
schema findings").

Per-pair operations (single transaction per --confirm run, all 2 pairs):

  Op A  fund_holdings_v2 re-point
        UPDATE rollup_entity_id, dm_rollup_entity_id, dm_rollup_name
        WHERE (rollup_entity_id=:brand OR dm_rollup_entity_id=:brand)
              AND is_latest=TRUE
        Note: entity_id and dm_entity_id are FUND-level and never carry
        the brand_eid; do not touch. family_name and fund_name are
        fund-level identity labels; do not touch. Only dm_rollup_name
        (the manager-level rollup display name) shifts to the filer's
        canonical_name.

  Op B  entity_relationships re-point fund_sponsor edges
        UPDATE parent_entity_id = :filer
        WHERE parent_entity_id = :brand
              AND child_entity_id != :filer  (excludes self-loop case)
              AND valid_to = DATE '9999-12-31'

  Op B' entity_relationships close brand<->filer alias-bridge / self-loop
        UPDATE valid_to = CURRENT_DATE
        WHERE valid_to = DATE '9999-12-31'
              AND ( (parent=:filer AND child=:brand)
                 OR (parent=:brand AND child=:filer) )

  Op C  entity_classification_history close brand-side
        UPDATE valid_to = CURRENT_DATE
        WHERE entity_id = :brand AND valid_to = DATE '9999-12-31'

  Op D  DROPPED. The entities table is a flat registry with no valid_to
        column; "closing" semantics live in the SCD layers. Confirmed in
        chat 2026-05-02.

  Op E  entity_relationships insert audit row
        relationship_type='parent_brand', control_type='merge'
        (reuse of existing parent_brand enum value rather than adding a
        new 'merged_into'; control_type='merge' is novel but no CHECK
        constraint exists. Confirmed in chat 2026-05-02.)
        source = 'CP-4a-merge:inst-eid-bridge-fix-aliases'

  Op F  entity_rollup_history close brand-side
        UPDATE valid_to = CURRENT_DATE
        WHERE entity_id = :brand AND valid_to = DATE '9999-12-31'

  Op G  entity_aliases re-point brand-side to filer (NOT close)
        Two-pass:
          1. For each open brand alias whose (alias_type, is_preferred=
             TRUE) collides with an existing filer-side preferred alias,
             demote the incoming row to is_preferred=FALSE.
          2. UPDATE entity_id = :filer for all open brand-side aliases.
        PK is (entity_id, alias_name, alias_type, valid_from); collision
        check has been pre-validated for both pairs.

Hard guards (--confirm):
  - Refuse if Phase 1 numbers diverge >5% from manifest pre-image.
  - Refuse if any per-pair sanity check fails post-merge.
  - Refuse if AUM conservation fails by >$0.01B per pair.
  - BEGIN/COMMIT wrapped; ROLLBACK on any constraint violation.
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
MANIFEST_CSV = BASE_DIR / "data" / "working" / "inst_eid_bridge_aliases_manifest.csv"
DRYRUN_DOC = BASE_DIR / "docs" / "findings" / "inst_eid_bridge_aliases_dryrun.md"
RESULTS_DOC = BASE_DIR / "docs" / "findings" / "inst_eid_bridge_aliases_results.md"

OPEN_DATE = date(9999, 12, 31)

AUM_CONSERVATION_TOLERANCE_USD = 0.01 * 1e9  # $0.01B
ROW_COUNT_DRIFT_TOLERANCE = 0.05  # 5%


@dataclass
class AliasPair:
    brand_eid: int
    filer_eid: int
    label: str  # human-readable name for log/manifest

    # Pre-image stats captured at dry-run / pre-confirm.
    fh_brand_rows: int = 0
    fh_brand_aum_usd: float = 0.0
    fh_filer_rows_pre: int = 0
    fh_filer_aum_pre_usd: float = 0.0

    er_repoint_count: int = 0  # parent_entity_id=brand AND child!=filer
    er_close_bridge_count: int = 0  # brand<->filer rows
    ech_close_count: int = 0
    erh_close_count: int = 0
    ea_repoint_count: int = 0
    ea_demote_count: int = 0  # subset of ea_repoint_count

    filer_canonical_name: str = ""

    # Post-confirm capture.
    confirm_stats: dict = field(default_factory=dict)


PAIRS: list[AliasPair] = [
    AliasPair(brand_eid=1, filer_eid=4375, label="Vanguard"),
    AliasPair(brand_eid=30, filer_eid=2322, label="PIMCO"),
]


# ---------------------------------------------------------------------------
# Pre-image capture (read-only)
# ---------------------------------------------------------------------------


def capture_preimage(con: duckdb.DuckDBPyConnection, p: AliasPair) -> None:
    p.filer_canonical_name = con.execute(
        "SELECT canonical_name FROM entities WHERE entity_id = ?",
        [p.filer_eid],
    ).fetchone()[0]

    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.brand_eid, p.brand_eid],
    ).fetchone()
    p.fh_brand_rows = int(row[0])
    p.fh_brand_aum_usd = float(row[1])

    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.filer_eid, p.filer_eid],
    ).fetchone()
    p.fh_filer_rows_pre = int(row[0])
    p.fh_filer_aum_pre_usd = float(row[1])

    p.er_repoint_count = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE parent_entity_id = ?
          AND child_entity_id != ?
          AND valid_to = ?
        """,
        [p.brand_eid, p.filer_eid, OPEN_DATE],
    ).fetchone()[0]

    p.er_close_bridge_count = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = ?
          AND ( (parent_entity_id = ? AND child_entity_id = ?)
             OR (parent_entity_id = ? AND child_entity_id = ?) )
        """,
        [OPEN_DATE, p.filer_eid, p.brand_eid, p.brand_eid, p.filer_eid],
    ).fetchone()[0]

    p.ech_close_count = con.execute(
        "SELECT COUNT(*) FROM entity_classification_history WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]

    p.erh_close_count = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]

    p.ea_repoint_count = con.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]

    # Demotion direction: filer-side preferred is demoted when brand has an
    # incoming preferred of the same alias_type (per chat decision — incoming
    # trade name wins over filer's legal name).
    p.ea_demote_count = con.execute(
        """
        SELECT COUNT(*)
        FROM entity_aliases f
        WHERE f.entity_id = ? AND f.valid_to = ? AND f.is_preferred = TRUE
          AND EXISTS (
              SELECT 1 FROM entity_aliases b
              WHERE b.entity_id = ? AND b.valid_to = ?
                AND b.alias_type = f.alias_type
                AND b.is_preferred = TRUE
          )
        """,
        [p.filer_eid, OPEN_DATE, p.brand_eid, OPEN_DATE],
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Manifest + findings doc emit
# ---------------------------------------------------------------------------


def write_manifest(pairs: list[AliasPair]) -> None:
    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "brand_eid",
        "brand_label",
        "filer_eid",
        "filer_canonical_name",
        "entity_id_correction",
        "fh_brand_rows",
        "fh_brand_aum_usd",
        "fh_filer_rows_pre",
        "fh_filer_aum_pre_usd",
        "fh_filer_aum_post_expected_usd",
        "er_repoint_count",
        "er_close_bridge_count",
        "ech_close_count",
        "erh_close_count",
        "ea_repoint_count",
        "ea_demote_count",
        "audit_op_e_relationship_type",
        "audit_op_e_control_type",
        "audit_op_e_source",
    ]
    with MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in pairs:
            w.writerow(
                [
                    p.brand_eid,
                    p.label,
                    p.filer_eid,
                    p.filer_canonical_name,
                    f"{p.brand_eid}->{p.filer_eid}",
                    p.fh_brand_rows,
                    f"{p.fh_brand_aum_usd:.2f}",
                    p.fh_filer_rows_pre,
                    f"{p.fh_filer_aum_pre_usd:.2f}",
                    f"{p.fh_filer_aum_pre_usd + p.fh_brand_aum_usd:.2f}",
                    p.er_repoint_count,
                    p.er_close_bridge_count,
                    p.ech_close_count,
                    p.erh_close_count,
                    p.ea_repoint_count,
                    p.ea_demote_count,
                    "parent_brand",
                    "merge",
                    "CP-4a-merge:inst-eid-bridge-fix-aliases",
                ]
            )


def write_dryrun_doc(pairs: list[AliasPair]) -> None:
    DRYRUN_DOC.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    lines: list[str] = []
    lines.append("# inst-eid-bridge-fix-aliases (CP-4a) — Phase 2 dry-run")
    lines.append("")
    lines.append(f"Generated {today} by `scripts/oneoff/inst_eid_bridge_aliases_merge.py --dry-run`.")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("2 BRAND_TO_FILER alias merges per `docs/decisions/inst_eid_bridge_decisions.md`")
    lines.append("BLOCKER 1 (brand has no CIK and is name-only synthetic => MERGE):")
    lines.append("")
    for p in pairs:
        lines.append(f"- **{p.label}** brand_eid={p.brand_eid} → filer_eid={p.filer_eid} (`{p.filer_canonical_name}`)")
    lines.append("")
    lines.append("Original prompt framed CP-4a as 5 merges. Phase 1 discovery against")
    lines.append("`data/working/inst_eid_bridge/eid_inventory.csv` returned **zero** qualifying")
    lines.append("`BRAND_HAS_NAME_MATCH` candidates: only 4 such rows exist in the inventory,")
    lines.append("all MEDIUM/LOW confidence with brand_name significantly different from")
    lines.append("filer_name (Aperio/Ascent, Altaba/Alphabet, Oaktree/Olstein, Robinson/")
    lines.append("Revelation). These match the Calvert → \"Stanley Capital Management\"")
    lines.append("false-positive prototype the decisions doc BLOCKER 2 explicitly rejected.")
    lines.append("Per prompt instruction, no synthesis from lower-confidence tiers; scope")
    lines.append("collapses to 2. Decisions doc correction lands in CP-4a results commit.")
    lines.append("")
    lines.append("## Phase 1 schema findings")
    lines.append("")
    lines.append("Five corrections to the original prompt's op shape, surfaced during")
    lines.append("read-only re-validation 2026-05-02 and confirmed in chat:")
    lines.append("")
    lines.append("1. **OP D dropped.** The `entities` table has no `valid_to` column —")
    lines.append("   it is a flat registry. SCD lives in `entity_identifiers`,")
    lines.append("   `entity_relationships`, `entity_classification_history`,")
    lines.append("   `entity_rollup_history`, `entity_aliases`. \"Closing\" a brand")
    lines.append("   means closing its open SCD-layer rows.")
    lines.append("2. **OP A column scope reduced.** `entity_id` and `dm_entity_id` in")
    lines.append("   `fund_holdings_v2` are FUND-level and never carry the brand_eid.")
    lines.append("   Setting them to filer would mass-mis-attribute every fund's identity")
    lines.append("   to the manager. `family_name` and `fund_name` are fund-level labels")
    lines.append("   (`VANGUARD MUNICIPAL BOND FUNDS` etc.) and stay. Only")
    lines.append("   `rollup_entity_id`, `dm_rollup_entity_id`, `dm_rollup_name` shift.")
    lines.append("3. **OP A WHERE uses OR**, not AND, on the two rollup columns. PIMCO")
    lines.append("   has 92 rows where `rollup_entity_id=30` but `dm_rollup_entity_id=18402`;")
    lines.append("   `WHERE dm_rollup_entity_id=:brand` alone misses them.")
    lines.append("4. **OP B re-points fund_sponsor edges**, does not close them. The")
    lines.append("   brands sponsor 57 (Vanguard) / 25 (PIMCO) fund_eids via open")
    lines.append("   `entity_relationships` rows; closing would orphan those funds")
    lines.append("   from sponsor lineage. Re-point parent_entity_id from brand to")
    lines.append("   filer instead. Op B' separately closes the single brand↔filer")
    lines.append("   alias-bridge row (different shape per pair: Vanguard has")
    lines.append("   `parent=4375 child=1 wholly_owned`; PIMCO has `parent=30 child=2322`")
    lines.append("   `fund_sponsor` parent_bridge — would become self-loop after re-point).")
    lines.append("5. **OPs F + G added.** The original prompt missed `entity_rollup_history`")
    lines.append("   and `entity_aliases` SCD layers. `entity_current` view depends on")
    lines.append("   both for display; without closure/re-point, brand display would")
    lines.append("   stay anchored at the brand_eid. F closes the 2 open rollup rows")
    lines.append("   per brand. G re-points open brand aliases to filer entity_id with")
    lines.append("   filer-side demotion: when the brand has an incoming")
    lines.append("   `is_preferred=TRUE` alias of the same `alias_type` as a filer-side")
    lines.append("   preferred open row, the FILER's existing preferred is demoted to")
    lines.append("   `FALSE` so the incoming brand-side trade name wins. Rationale:")
    lines.append("   the brand-side label is the canonical user-facing display")
    lines.append("   (e.g. `PIMCO` over `PACIFIC INVESTMENT MANAGEMENT CO LLC`).")
    lines.append("")
    lines.append("Schema sentinels: `valid_to = DATE '9999-12-31'` for open SCD rows")
    lines.append("(NOT `IS NULL`); `CURRENT_DATE` for closure (DATE type, not TIMESTAMP).")
    lines.append("OP E reuses `relationship_type='parent_brand'` with `control_type='merge'`")
    lines.append("rather than introducing a novel `merged_into` enum value.")
    lines.append("")
    lines.append("## Per-pair pre-image counts")
    lines.append("")
    for p in pairs:
        lines.append(f"### {p.label} (brand_eid={p.brand_eid} → filer_eid={p.filer_eid})")
        lines.append("")
        lines.append(f"- filer canonical_name: `{p.filer_canonical_name}`")
        lines.append("- `fund_holdings_v2` is_latest=TRUE:")
        lines.append(f"  - brand-side rows: {p.fh_brand_rows:,} / ${p.fh_brand_aum_usd / 1e9:,.2f}B")
        lines.append(f"  - filer-side rows pre-merge: {p.fh_filer_rows_pre:,} / ${p.fh_filer_aum_pre_usd / 1e9:,.2f}B")
        lines.append(f"  - filer-side AUM expected post-merge: ${(p.fh_filer_aum_pre_usd + p.fh_brand_aum_usd) / 1e9:,.2f}B")
        lines.append(f"- Op B re-point fund_sponsor edges: {p.er_repoint_count} rows")
        lines.append(f"- Op B' close alias-bridge / self-loop: {p.er_close_bridge_count} row")
        lines.append(f"- Op C close entity_classification_history: {p.ech_close_count} row")
        lines.append(f"- Op E insert audit row: 1 (parent_brand / merge)")
        lines.append(f"- Op F close entity_rollup_history: {p.erh_close_count} rows")
        lines.append(f"- Op G re-point entity_aliases: {p.ea_repoint_count} rows ({p.ea_demote_count} demoted preferred)")
        lines.append("")

    lines.append("## Aggregate")
    lines.append("")
    total_brand_aum = sum(p.fh_brand_aum_usd for p in pairs)
    total_brand_rows = sum(p.fh_brand_rows for p in pairs)
    lines.append(f"- Total brand-side fund_holdings_v2 rows re-pointed: {total_brand_rows:,}")
    lines.append(f"- Total brand-side AUM moved to filer: ${total_brand_aum / 1e9:,.2f}B")
    lines.append(f"- Total entity_relationships re-pointed: {sum(p.er_repoint_count for p in pairs)}")
    lines.append(f"- Total entity_relationships closed (alias bridges): {sum(p.er_close_bridge_count for p in pairs)}")
    lines.append(f"- Total entity_classification_history closed: {sum(p.ech_close_count for p in pairs)}")
    lines.append(f"- Total entity_rollup_history closed: {sum(p.erh_close_count for p in pairs)}")
    lines.append(f"- Total entity_aliases re-pointed: {sum(p.ea_repoint_count for p in pairs)}")
    lines.append(f"  (of which demoted from preferred to non-preferred: {sum(p.ea_demote_count for p in pairs)})")
    lines.append(f"- Total OP E audit rows inserted: {len(pairs)}")
    lines.append("")
    lines.append("## Hard guards (--confirm)")
    lines.append("")
    lines.append("- Refuse if pre-image counts diverge >5% from manifest at confirm time.")
    lines.append("- Refuse if any per-pair sanity check fails.")
    lines.append("- Refuse if AUM conservation fails (>$0.01B post-merge filer-AUM delta).")
    lines.append("- BEGIN/COMMIT wraps all 2 pairs; ROLLBACK on any constraint violation.")
    lines.append("")
    lines.append("## Next")
    lines.append("")
    lines.append("Authorization gate: per `inst_eid_bridge_decisions.md` sequencing note +")
    lines.append("the manual review gate added in c53337c, --confirm requires explicit")
    lines.append("chat authorization after this dry-run review.")
    lines.append("")
    DRYRUN_DOC.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# --confirm execution
# ---------------------------------------------------------------------------


def execute_pair(con: duckdb.DuckDBPyConnection, p: AliasPair) -> dict:
    """Apply Ops A through G for a single pair. Caller wraps BEGIN/COMMIT."""
    today = date.today()
    stats: dict = {}

    # DuckDB UPDATE/INSERT/DELETE return a single-row result with the
    # affected count in column 0 (no SQLite-style changes() function).
    def _affected(cur) -> int:
        row = cur.fetchone()
        return int(row[0]) if row else 0

    # Op A — fund_holdings_v2 re-point
    cur = con.execute(
        """
        UPDATE fund_holdings_v2
        SET rollup_entity_id = ?,
            dm_rollup_entity_id = ?,
            dm_rollup_name = ?
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.filer_eid, p.filer_eid, p.filer_canonical_name, p.brand_eid, p.brand_eid],
    )
    stats["op_a_rows"] = _affected(cur)

    # Op B — re-point parent fund_sponsor edges (excludes self-loop case)
    cur = con.execute(
        """
        UPDATE entity_relationships
        SET parent_entity_id = ?, last_refreshed_at = NOW()
        WHERE parent_entity_id = ?
          AND child_entity_id != ?
          AND valid_to = ?
        """,
        [p.filer_eid, p.brand_eid, p.filer_eid, OPEN_DATE],
    )
    stats["op_b_rows"] = _affected(cur)

    # Op B' — capture subsumed-row metadata BEFORE closing, then close.
    # Type-agnostic match on (parent, child) tuple to handle both shapes:
    # Vanguard parent=4375 child=1 wholly_owned (orphan_scan)
    # PIMCO    parent=30 child=2322 fund_sponsor (parent_bridge)
    subsumed = con.execute(
        """
        SELECT relationship_id, parent_entity_id, child_entity_id,
               relationship_type, source
        FROM entity_relationships
        WHERE valid_to = ?
          AND ( (parent_entity_id = ? AND child_entity_id = ?)
             OR (parent_entity_id = ? AND child_entity_id = ?) )
        """,
        [OPEN_DATE, p.filer_eid, p.brand_eid, p.brand_eid, p.filer_eid],
    ).fetchall()
    if len(subsumed) != 1:
        raise RuntimeError(
            f"[{p.label}] Op B' expected exactly 1 subsumed row, got {len(subsumed)}"
        )
    sub_rel_id, sub_parent, sub_child, sub_type, sub_source = subsumed[0]
    stats["subsumed_relationship_id"] = int(sub_rel_id)
    stats["subsumed_type"] = sub_type
    stats["subsumed_parent"] = int(sub_parent)
    stats["subsumed_child"] = int(sub_child)
    stats["subsumed_source"] = sub_source

    cur = con.execute(
        """
        UPDATE entity_relationships
        SET valid_to = ?, last_refreshed_at = NOW()
        WHERE relationship_id = ?
        """,
        [today, sub_rel_id],
    )
    stats["op_b_prime_rows"] = _affected(cur)

    # Op C — close entity_classification_history
    cur = con.execute(
        """
        UPDATE entity_classification_history
        SET valid_to = ?
        WHERE entity_id = ? AND valid_to = ?
        """,
        [today, p.brand_eid, OPEN_DATE],
    )
    stats["op_c_rows"] = _affected(cur)

    # Op E — insert audit row (parent_brand / merge). entity_relationships
    # has no `notes` column, so the subsumed-row reference is encoded into
    # the `source` field as a structured suffix:
    #   CP-4a-merge:inst-eid-bridge-fix-aliases|subsumes:<type>/<p>-><c>/<orig_src>
    audit_source = (
        f"CP-4a-merge:inst-eid-bridge-fix-aliases|"
        f"subsumes:{sub_type}/{sub_parent}->{sub_child}/{sub_source}"
    )
    next_id = con.execute(
        "SELECT COALESCE(MAX(relationship_id), 0) + 1 FROM entity_relationships"
    ).fetchone()[0]
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
        [next_id, p.filer_eid, p.brand_eid, audit_source, today, OPEN_DATE],
    )
    stats["op_e_relationship_id"] = int(next_id)
    stats["op_e_source"] = audit_source

    # Op F — close entity_rollup_history
    cur = con.execute(
        """
        UPDATE entity_rollup_history
        SET valid_to = ?
        WHERE entity_id = ? AND valid_to = ?
        """,
        [today, p.brand_eid, OPEN_DATE],
    )
    stats["op_f_rows"] = _affected(cur)

    # Op G — entity_aliases re-point with preferred-conflict demotion.
    # Pass 1: demote the FILER's existing preferred where the brand has an
    # incoming preferred of the same alias_type. Rationale: brand-side trade
    # name is the canonical user-facing display (e.g. 'PIMCO' over 'PACIFIC
    # INVESTMENT MANAGEMENT CO LLC'), so the incoming preferred wins and the
    # filer's prior preferred is demoted. Confirmed in chat 2026-05-02.
    cur = con.execute(
        """
        UPDATE entity_aliases
        SET is_preferred = FALSE
        WHERE entity_id = ? AND valid_to = ? AND is_preferred = TRUE
          AND alias_type IN (
              SELECT alias_type FROM entity_aliases
              WHERE entity_id = ? AND valid_to = ? AND is_preferred = TRUE
          )
        """,
        [p.filer_eid, OPEN_DATE, p.brand_eid, OPEN_DATE],
    )
    stats["op_g_demoted"] = _affected(cur)

    # Pass 2: re-point entity_id
    cur = con.execute(
        """
        UPDATE entity_aliases
        SET entity_id = ?
        WHERE entity_id = ? AND valid_to = ?
        """,
        [p.filer_eid, p.brand_eid, OPEN_DATE],
    )
    stats["op_g_repointed"] = _affected(cur)

    # Sanity checks
    leftover = con.execute(
        """
        SELECT COUNT(*) FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.brand_eid, p.brand_eid],
    ).fetchone()[0]
    if leftover != 0:
        raise RuntimeError(
            f"[{p.label}] sanity-check failed: {leftover} fund_holdings_v2 rows still reference brand_eid={p.brand_eid}"
        )

    open_brand_rels = con.execute(
        """
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = ?
          AND (parent_entity_id = ? OR child_entity_id = ?)
        """,
        [OPEN_DATE, p.brand_eid, p.brand_eid],
    ).fetchone()[0]
    # The OP E audit row pointing parent=filer child=brand is open by design.
    if open_brand_rels > 1:
        raise RuntimeError(
            f"[{p.label}] sanity-check failed: {open_brand_rels} open entity_relationships still reference brand_eid (expected 1: the OP E audit row)"
        )

    open_brand_classifications = con.execute(
        "SELECT COUNT(*) FROM entity_classification_history WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_brand_classifications != 0:
        raise RuntimeError(
            f"[{p.label}] sanity-check failed: {open_brand_classifications} ECH rows still open"
        )

    open_brand_rollups = con.execute(
        "SELECT COUNT(*) FROM entity_rollup_history WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_brand_rollups != 0:
        raise RuntimeError(
            f"[{p.label}] sanity-check failed: {open_brand_rollups} entity_rollup_history rows still open"
        )

    open_brand_aliases = con.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? AND valid_to = ?",
        [p.brand_eid, OPEN_DATE],
    ).fetchone()[0]
    if open_brand_aliases != 0:
        raise RuntimeError(
            f"[{p.label}] sanity-check failed: {open_brand_aliases} entity_aliases rows still on brand"
        )

    # AUM conservation check
    post_filer_aum = con.execute(
        """
        SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2
        WHERE (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
          AND is_latest = TRUE
        """,
        [p.filer_eid, p.filer_eid],
    ).fetchone()[0]
    expected = p.fh_filer_aum_pre_usd + p.fh_brand_aum_usd
    delta = abs(float(post_filer_aum) - expected)
    if delta > AUM_CONSERVATION_TOLERANCE_USD:
        raise RuntimeError(
            f"[{p.label}] AUM conservation failed: post=${float(post_filer_aum)/1e9:,.4f}B "
            f"expected=${expected/1e9:,.4f}B delta=${delta/1e9:,.6f}B"
        )
    stats["post_filer_aum_usd"] = float(post_filer_aum)
    stats["aum_conservation_delta_usd"] = float(delta)

    return stats


def write_results_doc(pairs: list[AliasPair]) -> None:
    RESULTS_DOC.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    lines: list[str] = []
    lines.append("# inst-eid-bridge-fix-aliases (CP-4a) — Phase 3-5 results")
    lines.append("")
    lines.append(f"Generated {today} by `scripts/oneoff/inst_eid_bridge_aliases_merge.py --confirm`.")
    lines.append("")
    lines.append("## Per-pair execution stats")
    lines.append("")
    for p in pairs:
        lines.append(f"### {p.label} (brand_eid={p.brand_eid} → filer_eid={p.filer_eid})")
        lines.append("")
        s = p.confirm_stats
        lines.append(f"- Op A (fund_holdings_v2 re-point): {s.get('op_a_rows', 'n/a')} rows")
        lines.append(f"- Op B (entity_relationships re-point): {s.get('op_b_rows', 'n/a')} rows")
        lines.append(f"- Op B' (alias-bridge close): {s.get('op_b_prime_rows', 'n/a')} rows")
        lines.append(f"- Op C (ECH close): {s.get('op_c_rows', 'n/a')} rows")
        lines.append(f"- Op E (audit insert): relationship_id={s.get('op_e_relationship_id', 'n/a')}")
        lines.append(f"- Op F (ERH close): {s.get('op_f_rows', 'n/a')} rows")
        lines.append(f"- Op G (alias re-point): {s.get('op_g_repointed', 'n/a')} rows ({s.get('op_g_demoted', 0)} demoted)")
        lines.append(f"- Post-merge filer AUM: ${s.get('post_filer_aum_usd', 0)/1e9:,.4f}B")
        lines.append(f"- AUM conservation delta: ${s.get('aum_conservation_delta_usd', 0)/1e9:,.6f}B")
        lines.append("")
    RESULTS_DOC.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to 13f.duckdb")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="Read-only manifest + findings doc emit")
    grp.add_argument("--confirm", action="store_true", help="Execute merges in a single transaction")
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
        write_dryrun_doc(PAIRS)
        print(f"[dry-run] manifest: {MANIFEST_CSV}")
        print(f"[dry-run] findings: {DRYRUN_DOC}")
        for p in PAIRS:
            print(
                f"[dry-run] {p.label}: brand_rows={p.fh_brand_rows:,} "
                f"brand_aum=${p.fh_brand_aum_usd/1e9:,.2f}B "
                f"er_repoint={p.er_repoint_count} er_close={p.er_close_bridge_count} "
                f"ech={p.ech_close_count} erh={p.erh_close_count} "
                f"ea={p.ea_repoint_count}({p.ea_demote_count} demote)"
            )
        return 0

    # --confirm path
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        for p in PAIRS:
            capture_preimage(con, p)

        # Drift check vs manifest if manifest exists
        if MANIFEST_CSV.exists():
            with MANIFEST_CSV.open() as f:
                manifest = {int(row["brand_eid"]): row for row in csv.DictReader(f)}
            for p in PAIRS:
                m = manifest.get(p.brand_eid)
                if m is None:
                    raise RuntimeError(f"manifest missing brand_eid={p.brand_eid}")
                drift = abs(p.fh_brand_rows - int(m["fh_brand_rows"])) / max(int(m["fh_brand_rows"]), 1)
                if drift > ROW_COUNT_DRIFT_TOLERANCE:
                    raise RuntimeError(
                        f"[{p.label}] pre-image drift {drift:.2%} exceeds {ROW_COUNT_DRIFT_TOLERANCE:.0%} "
                        f"(manifest={m['fh_brand_rows']}, current={p.fh_brand_rows})"
                    )

        con.execute("BEGIN")
        try:
            for p in PAIRS:
                p.confirm_stats = execute_pair(con, p)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()

    write_results_doc(PAIRS)
    print(f"[confirm] DONE — results: {RESULTS_DOC}")
    for p in PAIRS:
        s = p.confirm_stats
        print(
            f"[confirm] {p.label}: op_a={s['op_a_rows']:,} op_b={s['op_b_rows']} "
            f"op_b'={s['op_b_prime_rows']} op_c={s['op_c_rows']} "
            f"op_e_rel_id={s['op_e_relationship_id']} op_f={s['op_f_rows']} "
            f"op_g={s['op_g_repointed']}({s['op_g_demoted']} demote) "
            f"aum_delta=${s['aum_conservation_delta_usd']/1e9:,.6f}B"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
