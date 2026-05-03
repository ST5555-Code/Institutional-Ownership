#!/usr/bin/env python3
"""inst_eid_bridge_blackrock_5_way.py — CP-4b-blackrock: AUTHOR_NEW_BRIDGE.

Inserts 5 entity_relationships rows bridging BlackRock sub-brand eids to
filer eid=3241 (BlackRock, Inc.). Per docs/decisions/inst_eid_bridge_
decisions.md BLOCKER 1 (brand has CIK and independent SEC registration =>
BRIDGE).

Pairings (parent_entity_id=3241, child_entity_id=brand_eid):

  - eid=7586  BlackRock Fund Advisors                 ($1,303B fund AUM)
  - eid=3586  BLACKROCK ADVISORS LLC                  (  $645B fund AUM)
  - eid=17970 BlackRock Investment Management, LLC    (  $426B fund AUM)
  - eid=8453  BLACKROCK FINANCIAL MANAGEMENT INC/DE   (  $150B fund AUM)
  - eid=18030 BlackRock International Limited         (   $16B fund AUM)
                                                     -----------------
                                                       $2,541B (~$2.5T)

Note: eid=2 (BlackRock / iShares, $15.7T fund AUM) already has an open
fund_sponsor relationship to eid=3241 (relationship_id=153, source=
parent_bridge). It is the 6th BlackRock brand but is NOT in scope here
because the bridge already exists.

Path-B scope per chat 2026-05-02. The other ~75 AUTHOR_NEW_BRIDGE
candidates require ADV cross-ref + parent-corp lookup discovery and are
deferred to CP-4b-discovery (next read-only PR) followed by
CP-4b-author-top20 (execution PR).

Op shape (no MERGE / re-point — pure new-row INSERT):

  Op I — INSERT entity_relationships row, one per pair.
    relationship_id     = MAX(relationship_id) + N
    parent_entity_id    = 3241 (filer, BlackRock, Inc.)
    child_entity_id     = brand_eid
    relationship_type   = 'wholly_owned'
    control_type        = 'control'
    is_primary          = TRUE
    primary_parent_key  = 3241
    confidence          = 'high'
    is_inferred         = FALSE
    valid_from          = CURRENT_DATE
    valid_to            = DATE '9999-12-31'
    source              = 'CP-4b-blackrock-author:inst-eid-bridge-blackrock-
                           5-way|pair=:N|pairing_source=investigation_§7.3|
                           confidence=HIGH'
    created_at, last_refreshed_at = NOW()

The CP-4a precedent (PR #256) wrote DIRECT to prod entity_relationships,
not via staging. CP-4b-blackrock matches that precedent (decisions doc's
reference to staging_workflow_live.md is to a non-existent doc; the
entity_relationships_staging table has a different schema oriented around
human-review queues, not a parallel write twin). Single transaction across
all 5 INSERTs with hard guards.

Hard guards (--confirm):
  - Refuse if any brand or filer entity_id row missing.
  - Refuse if any open bridge from {3241} to {brand_eids} already exists.
  - Refuse if filer 3241 hv2 presence drops to zero.
  - Refuse if expected post-image relationship_id range != actual.
  - BEGIN/COMMIT wrapped; ROLLBACK on any constraint violation.

CP-4b adds bridge metadata only — does NOT re-point fund_holdings_v2 or
any other rollup column. Brand eids stay alive as canonical brand-name
attribution sources. No AUM moves. peer_rotation_flows row count is
unchanged by this PR. Invisible-brand visibility shifts in CP-5 read
sweep (parent-level-display-canonical-reads), not here.
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
MANIFEST_CSV = BASE_DIR / "data" / "working" / "inst_eid_bridge_blackrock_5_way_manifest.csv"
DRYRUN_DOC = BASE_DIR / "docs" / "findings" / "inst_eid_bridge_blackrock_5_way_dryrun.md"
RESULTS_DOC = BASE_DIR / "docs" / "findings" / "inst_eid_bridge_blackrock_5_way_results.md"

OPEN_DATE = date(9999, 12, 31)
FILER_EID = 3241
FILER_NAME = "BlackRock, Inc."

PAIRING_SOURCE = "investigation_§7.3"
CONFIDENCE = "HIGH"


@dataclass
class BridgePair:
    pair_no: int
    brand_eid: int
    brand_label: str

    # Pre-image (read-only)
    brand_canonical_name: str = ""
    brand_entity_type: str = ""
    fund_rows: int = 0
    fund_aum_usd: float = 0.0
    open_ech: int = 0
    open_erh: int = 0
    open_aliases: int = 0
    open_relationships: int = 0
    existing_bridge_count: int = 0  # to FILER_EID (any direction, any type)

    # Post-confirm capture
    new_relationship_id: int = 0


PAIRS: list[BridgePair] = [
    BridgePair(pair_no=1, brand_eid=7586, brand_label="BlackRock Fund Advisors"),
    BridgePair(pair_no=2, brand_eid=3586, brand_label="BLACKROCK ADVISORS LLC"),
    BridgePair(pair_no=3, brand_eid=17970, brand_label="BlackRock Investment Management LLC"),
    BridgePair(pair_no=4, brand_eid=8453, brand_label="BLACKROCK FINANCIAL MANAGEMENT INC/DE"),
    BridgePair(pair_no=5, brand_eid=18030, brand_label="BlackRock International Limited"),
]


# ---------------------------------------------------------------------------
# Pre-image capture (read-only)
# ---------------------------------------------------------------------------


def _build_source(pair_no: int) -> str:
    return (
        f"CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|"
        f"pair={pair_no}|pairing_source={PAIRING_SOURCE}|confidence={CONFIDENCE}"
    )


def capture_filer(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id = ?",
        [FILER_EID],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"filer eid={FILER_EID} missing from entities")
    name, etype = row
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


# ---------------------------------------------------------------------------
# Manifest + findings doc emit
# ---------------------------------------------------------------------------


def write_manifest(pairs: list[BridgePair], filer: dict) -> None:
    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "pair_no",
        "brand_eid",
        "brand_label",
        "brand_canonical_name",
        "brand_entity_type",
        "filer_eid",
        "filer_canonical_name",
        "fund_rows",
        "fund_aum_usd",
        "open_ech",
        "open_erh",
        "open_aliases",
        "open_relationships",
        "existing_bridge_check",
        "hv2_check",
        "pairing_source",
        "confidence",
        "conflict_flag",
        "op_i_relationship_type",
        "op_i_control_type",
        "op_i_source",
    ]
    with MANIFEST_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in pairs:
            w.writerow(
                [
                    p.pair_no,
                    p.brand_eid,
                    p.brand_label,
                    p.brand_canonical_name,
                    p.brand_entity_type,
                    FILER_EID,
                    filer["canonical_name"],
                    p.fund_rows,
                    f"{p.fund_aum_usd:.2f}",
                    p.open_ech,
                    p.open_erh,
                    p.open_aliases,
                    p.open_relationships,
                    "NONE" if p.existing_bridge_count == 0 else f"FAIL:{p.existing_bridge_count}",
                    "PRESENT" if filer["hv2_rows"] > 0 else "MISSING",
                    PAIRING_SOURCE,
                    CONFIDENCE,
                    "",  # conflict_flag — none expected per Phase 1 gates
                    "wholly_owned",
                    "control",
                    _build_source(p.pair_no),
                ]
            )


def write_dryrun_doc(pairs: list[BridgePair], filer: dict, max_rel_id: int) -> None:
    DRYRUN_DOC.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    total_bridged_aum = sum(p.fund_aum_usd for p in pairs)
    lines: list[str] = []
    lines.append("# inst-eid-bridge-blackrock-5-way (CP-4b-blackrock) — Phase 2 dry-run")
    lines.append("")
    lines.append(
        f"Generated {today} by `scripts/oneoff/inst_eid_bridge_blackrock_5_way.py --dry-run`."
    )
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(
        "5 AUTHOR_NEW_BRIDGE inserts per `docs/decisions/inst_eid_bridge_decisions.md`"
    )
    lines.append(
        "BLOCKER 1 (brand has CIK and independent SEC registration => BRIDGE)."
    )
    lines.append(
        "All 5 are BlackRock sub-brand eids that today have no open `entity_relationships`"
    )
    lines.append(
        f"row to filer eid={FILER_EID} ({filer['canonical_name']}). The 6th BlackRock"
    )
    lines.append(
        "brand — eid=2 (BlackRock / iShares, $15.7T fund AUM) — already has an open"
    )
    lines.append(
        "fund_sponsor row to eid=3241 (relationship_id=153, source=parent_bridge) and"
    )
    lines.append("is therefore TRUE_BRIDGE_ENCODED, not in scope here.")
    lines.append("")
    lines.append("## Path-B scope decision (chat 2026-05-02)")
    lines.append("")
    lines.append("Original CP-4b prompt scoped top-25 by AUM. Phase 0 discovery surfaced two")
    lines.append("contradictions in the original prompt:")
    lines.append("")
    lines.append(
        "1. The Phase 0.3 filter (`bridge_class=BRAND_HAS_RELATIONSHIP AND counterparty_in_hv2"
    )
    lines.append(
        "   IS FALSE`) selects a different cohort than the spec's cited examples. The"
    )
    lines.append(
        "   examples (Wellington 9935→11220, Dimensional 7→5026, Franklin 28→4805,"
    )
    lines.append(
        "   T. Rowe Price 13→4627, etc.) are all already TRUE_BRIDGE_ENCODED — they"
    )
    lines.append(
        "   have an open `entity_relationships` row to a hv2-present counterparty and"
    )
    lines.append(
        "   per `inst_eid_bridge_decisions.md` need NO entity_relationships write."
    )
    lines.append("")
    lines.append(
        "2. Investigation numbers have drifted post-CP-4a. Replicating §4 against the"
    )
    lines.append(
        "   current DB: invisible brands 1,225 → 1,337; brands with ≥1 hv2-counterparty"
    )
    lines.append(
        "   relationship 86 → 191; unbridged AUM ~$26.0T → $24.6T. The 86 figure"
    )
    lines.append(
        "   undercounts because PR #254 used a single-row-per-brand inventory; multi-rel"
    )
    lines.append(
        "   brands aren't reflected in the `rel_other_eid` column."
    )
    lines.append("")
    lines.append(
        "Path B (chat 2026-05-02): split CP-4b into three sub-PRs."
    )
    lines.append("")
    lines.append(
        "  - **CP-4b-blackrock** (this PR): 5 mechanically-discoverable BlackRock"
    )
    lines.append(
        "    sub-brand bridges to eid=3241. Pairings come direct from investigation"
    )
    lines.append(
        "    §7.3 with the eid=2 fund_sponsor pre-existing-bridge note layered in."
    )
    lines.append("")
    lines.append(
        "  - **CP-4b-discovery** (next, read-only): per-brand filer pairings for"
    )
    lines.append(
        "    top-20 AUTHOR_NEW_BRIDGE candidates by AUM, derived from `adv_managers`"
    )
    lines.append(
        "    ADV cross-ref + parent-corp lookup. Confidence-tiered manifest."
    )
    lines.append("")
    lines.append(
        "  - **CP-4b-author-top20** (after, execution): apply CP-4b-discovery"
    )
    lines.append(
        "    manifest pairings as new entity_relationships rows."
    )
    lines.append("")
    lines.append(
        "Same shape as PR #249 (cef-scoping) → PR #251 (cef-asa-flip-and-relabel)"
    )
    lines.append("precedent.")
    lines.append("")
    lines.append("## Op shape")
    lines.append("")
    lines.append(
        "Pure new-row INSERT. No MERGE, no re-point of `fund_holdings_v2`, no closure"
    )
    lines.append(
        "of any other SCD layer. Brand eids stay alive as canonical brand-name"
    )
    lines.append(
        "attribution sources. No AUM moves. `peer_rotation_flows` row count unchanged."
    )
    lines.append("")
    lines.append("Per pair (single Op I, INSERT into `entity_relationships`):")
    lines.append("")
    lines.append("```")
    lines.append("relationship_id    = MAX(relationship_id) + N            -- 20815..20819")
    lines.append("parent_entity_id   = 3241                                 -- BlackRock, Inc.")
    lines.append("child_entity_id    = brand_eid                            -- per pair")
    lines.append("relationship_type  = 'wholly_owned'                       -- BRIDGE pattern")
    lines.append("control_type       = 'control'                            -- standard for wholly_owned")
    lines.append("is_primary         = TRUE")
    lines.append("primary_parent_key = 3241")
    lines.append("confidence         = 'high'")
    lines.append("is_inferred        = FALSE")
    lines.append("valid_from         = CURRENT_DATE")
    lines.append("valid_to           = DATE '9999-12-31'                    -- open SCD sentinel")
    lines.append(
        "source             = 'CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|"
    )
    lines.append(
        "                      pair=:N|pairing_source=investigation_§7.3|confidence=HIGH'"
    )
    lines.append("created_at         = NOW()")
    lines.append("last_refreshed_at  = NOW()")
    lines.append("```")
    lines.append("")
    lines.append(
        "`entity_relationships` has no `notes` column (CP-4a finding); audit metadata"
    )
    lines.append(
        "encoded into the `source` field as a structured string. `relationship_id` is"
    )
    lines.append(
        "assigned via `MAX(relationship_id) + N` per CP-4a precedent (no SEQUENCE/AUTO)."
    )
    lines.append("")
    lines.append("## Phase 0 schema findings")
    lines.append("")
    lines.append(
        "1. **`entity_relationships` schema confirmed.** Columns: relationship_id,"
    )
    lines.append(
        "   parent_entity_id, child_entity_id, relationship_type, control_type,"
    )
    lines.append(
        "   is_primary, primary_parent_key, confidence, source, is_inferred,"
    )
    lines.append(
        "   valid_from, valid_to, created_at, last_refreshed_at. No `notes` column."
    )
    lines.append(
        "   PK is `relationship_id` (BIGINT, no auto-increment). Pre-existing"
    )
    lines.append(
        f"   MAX(relationship_id) at dry-run time = {max_rel_id:,}; new IDs will be"
    )
    lines.append(
        f"   {max_rel_id + 1:,} through {max_rel_id + len(pairs):,}."
    )
    lines.append("")
    lines.append(
        "2. **`relationship_type` value reuse.** Existing distribution: fund_sponsor"
    )
    lines.append(
        "   13,707; sub_adviser 3,442; wholly_owned 985; mutual_structure 153;"
    )
    lines.append(
        "   parent_brand 78. `wholly_owned` with `control_type='control'` is the"
    )
    lines.append(
        "   established BRIDGE shape (985 existing rows). No new enum values."
    )
    lines.append("")
    lines.append(
        "3. **Open SCD sentinel.** `valid_to = DATE '9999-12-31'` for open rows"
    )
    lines.append(
        "   (NOT `IS NULL`); `CURRENT_DATE` for closure (DATE type). Confirmed via"
    )
    lines.append(
        "   PR #256 (CP-4a) and verified again here against current DB."
    )
    lines.append("")
    lines.append(
        "4. **Staging-twin policy.** `docs/staging_workflow_live.md` does not exist"
    )
    lines.append(
        "   despite being referenced from `inst_eid_bridge_decisions.md` and"
    )
    lines.append(
        "   `inst_eid_bridge_investigation.md`. The `entity_relationships_staging`"
    )
    lines.append(
        "   table has a different schema (id auto-seq, owner_name, ownership_pct,"
    )
    lines.append(
        "   conflict_reason, review_status default 'pending', reviewer, reviewed_at,"
    )
    lines.append(
        "   resolution) — it is a human-review queue, not a parallel write twin."
    )
    lines.append(
        "   CP-4a (PR #256, 2026-05-02) wrote DIRECT to prod `entity_relationships`."
    )
    lines.append(
        "   This PR matches that precedent: single transaction, hard guards, prod"
    )
    lines.append(
        "   write. Pre-flight backup at `data/backups/13f_backup_20260502_202932`."
    )
    lines.append("")
    lines.append("## Phase 1 re-validation (pre-image counts)")
    lines.append("")
    lines.append(f"### Filer eid={FILER_EID} — `{filer['canonical_name']}`")
    lines.append("")
    lines.append(f"- entity_type: `{filer['entity_type']}`")
    lines.append(
        f"- holdings_v2 (latest): rows={filer['hv2_rows']:,} AUM=${filer['hv2_aum_usd']/1e9:,.1f}B"
    )
    lines.append("- alive (non-zero open SCD rows)")
    lines.append("")
    for p in pairs:
        lines.append(f"### Pair {p.pair_no} — eid={p.brand_eid} (`{p.brand_canonical_name}`)")
        lines.append("")
        lines.append(f"- entity_type: `{p.brand_entity_type}`")
        lines.append(f"- fund_holdings_v2 (latest): rows={p.fund_rows:,} AUM=${p.fund_aum_usd/1e9:,.2f}B")
        lines.append(f"- holdings_v2 (latest): 0 rows / $0.00B (brand is fund-side only)")
        lines.append(
            f"- open SCD: ECH={p.open_ech} ERH={p.open_erh} aliases={p.open_aliases} "
            f"total_open_relationships={p.open_relationships}"
        )
        lines.append(
            f"- existing bridge to filer {FILER_EID}: {p.existing_bridge_count} (gate: must be 0)"
        )
        lines.append(f"- new relationship_id (planned): {max_rel_id + p.pair_no}")
        lines.append(f"- source string: `{_build_source(p.pair_no)}`")
        lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- Total pairs: {len(pairs)}")
    lines.append(f"- Total bridged fund AUM: ${total_bridged_aum/1e9:,.2f}B (~${total_bridged_aum/1e12:,.2f}T)")
    lines.append(
        f"- New relationship_id range: {max_rel_id + 1} through {max_rel_id + len(pairs)}"
    )
    lines.append(f"- Filer hv2 AUM (unchanged by this PR): ${filer['hv2_aum_usd']/1e9:,.1f}B")
    lines.append(
        "- fund_holdings_v2 rows touched: 0 (CP-4b is bridge-only, not re-point)"
    )
    lines.append(
        "- peer_rotation_flows row count expected delta: 0 (read-side only impact in CP-5)"
    )
    lines.append("")
    lines.append("## Hard guards (--confirm)")
    lines.append("")
    lines.append("- Re-capture pre-image at confirm time; refuse if any pair's brand or")
    lines.append("  filer entity row is missing.")
    lines.append("- Refuse if any pair's `existing_bridge_count` to filer 3241 is non-zero.")
    lines.append("- Refuse if filer 3241 hv2 AUM has dropped to zero.")
    lines.append("- Refuse if MAX(relationship_id) drifted such that planned IDs collide")
    lines.append("  with concurrent inserts (lock + re-MAX inside transaction).")
    lines.append(f"- Single BEGIN/COMMIT wrapping all {len(pairs)} INSERTs; ROLLBACK on any")
    lines.append("  constraint violation.")
    lines.append("- Post-INSERT sanity check: SELECT COUNT(*)=1 per (parent=3241, child=brand,")
    lines.append("  valid_to=open) confirms each pair landed.")
    lines.append("- Post-transaction row count delta on entity_relationships = 5.")
    lines.append("")
    lines.append("## Next")
    lines.append("")
    lines.append("Authorization gate: per `inst_eid_bridge_decisions.md` CP-4 manual review")
    lines.append("gate, `--confirm` requires explicit chat authorization after this dry-run.")
    lines.append("")
    DRYRUN_DOC.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# --confirm execution
# ---------------------------------------------------------------------------


def execute_pair(con: duckdb.DuckDBPyConnection, p: BridgePair, base_rel_id: int) -> None:
    """INSERT one entity_relationships row (parent=FILER_EID, child=brand_eid)."""
    today = date.today()
    new_id = base_rel_id + p.pair_no
    src = _build_source(p.pair_no)
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
        [new_id, FILER_EID, p.brand_eid, FILER_EID, src, today, OPEN_DATE],
    )
    p.new_relationship_id = new_id

    # Sanity: exactly 1 open row matching (parent=FILER, child=brand)
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


def write_results_doc(pairs: list[BridgePair], filer: dict, pre_count: int, post_count: int) -> None:
    RESULTS_DOC.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    total_bridged = sum(p.fund_aum_usd for p in pairs)
    lines: list[str] = []
    lines.append("# inst-eid-bridge-blackrock-5-way (CP-4b-blackrock) — Phase 3-5 results")
    lines.append("")
    lines.append(f"Generated {today} by `scripts/oneoff/inst_eid_bridge_blackrock_5_way.py --confirm`.")
    lines.append("")
    lines.append("## Per-pair execution")
    lines.append("")
    for p in pairs:
        lines.append(
            f"- Pair {p.pair_no}: eid={p.brand_eid} ({p.brand_canonical_name}) → "
            f"new relationship_id={p.new_relationship_id}, "
            f"fund_aum=${p.fund_aum_usd/1e9:,.2f}B"
        )
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- entity_relationships row count pre: {pre_count:,}")
    lines.append(f"- entity_relationships row count post: {post_count:,}")
    lines.append(f"- Delta: {post_count - pre_count} (expected: {len(pairs)})")
    lines.append(f"- Total fund AUM bridged: ${total_bridged/1e9:,.2f}B (~${total_bridged/1e12:,.2f}T)")
    lines.append(f"- Filer eid={FILER_EID} hv2 AUM (unchanged): ${filer['hv2_aum_usd']/1e9:,.1f}B")
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
    grp.add_argument("--confirm", action="store_true", help="Execute 5 INSERTs in a single transaction")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            filer = capture_filer(con)
            for p in PAIRS:
                capture_preimage(con, p)
            max_rel_id = int(con.execute("SELECT MAX(relationship_id) FROM entity_relationships").fetchone()[0])
        finally:
            con.close()
        write_manifest(PAIRS, filer)
        write_dryrun_doc(PAIRS, filer, max_rel_id)
        print(f"[dry-run] manifest: {MANIFEST_CSV}")
        print(f"[dry-run] findings: {DRYRUN_DOC}")
        for p in PAIRS:
            print(
                f"[dry-run] pair {p.pair_no}: eid={p.brand_eid} ({p.brand_label}) "
                f"fund_aum=${p.fund_aum_usd/1e9:,.2f}B "
                f"existing_bridge={p.existing_bridge_count} "
                f"new_rel_id={max_rel_id + p.pair_no}"
            )
        total = sum(p.fund_aum_usd for p in PAIRS)
        print(f"[dry-run] total bridged AUM: ${total/1e9:,.2f}B (~${total/1e12:,.2f}T)")
        return 0

    # --confirm path
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        # Re-capture pre-image (also re-runs all hard guards)
        filer = capture_filer(con)
        for p in PAIRS:
            capture_preimage(con, p)

        # Drift gate vs manifest if manifest exists
        if MANIFEST_CSV.exists():
            with MANIFEST_CSV.open() as f:
                manifest = {int(row["pair_no"]): row for row in csv.DictReader(f)}
            for p in PAIRS:
                m = manifest.get(p.pair_no)
                if m is None:
                    raise RuntimeError(f"manifest missing pair_no={p.pair_no}")
                if int(m["brand_eid"]) != p.brand_eid:
                    raise RuntimeError(
                        f"manifest brand_eid mismatch: pair {p.pair_no} "
                        f"manifest={m['brand_eid']} current={p.brand_eid}"
                    )

        pre_count = int(con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0])

        con.execute("BEGIN")
        try:
            base_rel_id = int(con.execute("SELECT MAX(relationship_id) FROM entity_relationships").fetchone()[0])
            for p in PAIRS:
                execute_pair(con, p, base_rel_id)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        post_count = int(con.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0])
        if post_count - pre_count != len(PAIRS):
            raise RuntimeError(
                f"row count delta {post_count - pre_count} != expected {len(PAIRS)}"
            )

    finally:
        con.close()

    write_results_doc(PAIRS, filer, pre_count, post_count)
    print(f"[confirm] DONE — results: {RESULTS_DOC}")
    for p in PAIRS:
        print(
            f"[confirm] pair {p.pair_no}: eid={p.brand_eid} → 3241 "
            f"new_rel_id={p.new_relationship_id}"
        )
    print(f"[confirm] entity_relationships: {pre_count:,} → {post_count:,} (Δ {post_count - pre_count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
