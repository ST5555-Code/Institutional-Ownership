"""CP-5 Bundle C — Probe 7.1+7.2: canonical climb mechanism + rollup_type
divergence handling.

Read-only investigation. Resolves the two PR #279 open questions:
  * Open Q1 — canonical climb mechanism for fund-tier rollup
  * Open Q2 — rollup_type divergence handling (dm vs ec, 13.8% diverged)

Outputs:
  data/working/cp-5-bundle-c-rollup-type-divergence.csv

Refs:
  scripts/oneoff/cp_5_bundle_b_common.py (canonical helper)
  scripts/oneoff/cp_5_coverage_matrix_revalidation.py (alternate path)
  data/working/cp-5-bundle-b-r5-validation.csv (`fund_tier_corrected_b` field)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
COVERAGE_QUARTER = "2025Q4"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")
WORKDIR = Path("data/working")


def build_inst_to_tp(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cycle-safe inst→top-parent climb (same shape as both candidate helpers)."""
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
    edge_map = dict(zip(edges["child_entity_id"], edges["parent_entity_id"]))
    seed = con.execute(
        "SELECT entity_id FROM entity_current WHERE entity_type='institution'"
    ).fetchdf()
    cur = {e: e for e in seed["entity_id"]}
    visited = {e: {e} for e in cur}
    cycles = set()
    for _ in range(20):
        ch = 0
        for ent, tp in list(cur.items()):
            if ent in cycles:
                continue
            nxt = edge_map.get(tp)
            if nxt is None or nxt == tp:
                continue
            if nxt in visited[ent]:
                cycles.add(ent)
                continue
            visited[ent].add(nxt)
            cur[ent] = nxt
            ch += 1
        if ch == 0:
            break
    return pd.DataFrame({"entity_id": list(cur.keys()),
                         "top_parent_entity_id": list(cur.values())})


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # === 7.1 — Canonical climb mechanism ===
    print("=" * 78)
    print("PHASE 7.1 — canonical climb mechanism (Open Q1)")
    print("=" * 78)
    print("""
  TWO CANDIDATE MECHANISMS:

  Method A — entity_rollup_history.rollup_entity_id traversal (canonical for
    both Bundle B and the matrix re-validation helper):
      JOIN entity_rollup_history ON entity_id = fund.id
      WHERE rollup_type = 'decision_maker_v1' AND valid_to = sentinel
      → gives the institution_entity_id (fund's "decision maker" institution)
      → then climb inst→top_parent via entity_relationships.

  Method B — fund_holdings_v2.dm_rollup_entity_id (denormalized column):
      Read fh.dm_rollup_entity_id directly per-row (avoids the
      entity_rollup_history JOIN). This column is populated by the loader at
      ingestion time from the same entity_rollup_history snapshot.

  Both are derived from `entity_rollup_history.rollup_type='decision_maker_v1'`
  but at different times (read-time vs load-time). For frozen periods these
  are identical. For periods where rollups were re-derived after ingestion,
  the fund_holdings_v2 column becomes stale.
""")

    inst_to_tp = build_inst_to_tp(con)
    con.register("inst_to_tp_df", inst_to_tp)
    n_diff = con.execute(f"""
        WITH method_a AS (
            SELECT erh.entity_id AS fund_eid, erh.rollup_entity_id AS inst_eid
            FROM entity_rollup_history erh
            JOIN entity_current ec ON ec.entity_id = erh.entity_id
            WHERE erh.valid_to = {SENTINEL}
              AND erh.rollup_type = 'decision_maker_v1'
              AND ec.entity_type = 'fund'
        ),
        per_row AS (
            SELECT fh.entity_id AS fund_eid,
                   fh.dm_rollup_entity_id AS inst_eid_b,
                   ANY_VALUE(method_a.inst_eid) AS inst_eid_a
            FROM fund_holdings_v2 fh
            LEFT JOIN method_a ON method_a.fund_eid = fh.entity_id
            WHERE fh.is_latest AND fh.quarter = '{COVERAGE_QUARTER}'
              AND fh.asset_category = 'EC'
            GROUP BY fh.entity_id, fh.dm_rollup_entity_id
        )
        SELECT
          COUNT(*) AS n_funds,
          SUM(CASE WHEN inst_eid_a IS NOT DISTINCT FROM inst_eid_b THEN 1 ELSE 0 END) AS aligned,
          SUM(CASE WHEN inst_eid_a IS DISTINCT FROM inst_eid_b THEN 1 ELSE 0 END) AS diverged
        FROM per_row
    """).fetchone()
    print(f"  Method A vs Method B alignment (active 2025Q4 EC funds):")
    print(f"    n funds: {n_diff[0]:,}; aligned: {n_diff[1]:,}; diverged: {n_diff[2]:,}")

    # Empirical: top-25 fund_tier under each method
    cov = pd.read_csv("data/working/cp-5-coverage-matrix-corrected.csv")
    top25 = cov.sort_values("combined_aum_billions", ascending=False).head(25).copy()

    rows = []
    for _, r in top25.iterrows():
        tp = int(r["top_parent_entity_id"])
        # Method A — entity_rollup_history → inst → top_parent
        a = con.execute(f"""
            WITH fund_to_tp AS (
                SELECT erh.entity_id AS fund_eid,
                       inst_to_tp_df.top_parent_entity_id AS tp
                FROM entity_rollup_history erh
                JOIN entity_current ec ON ec.entity_id = erh.entity_id
                JOIN inst_to_tp_df ON inst_to_tp_df.entity_id = erh.rollup_entity_id
                WHERE erh.valid_to = {SENTINEL}
                  AND erh.rollup_type = 'decision_maker_v1'
                  AND ec.entity_type = 'fund'
            )
            SELECT COALESCE(SUM(fh.market_value_usd)/1e9, 0)
            FROM fund_holdings_v2 fh
            JOIN fund_to_tp ON fund_to_tp.fund_eid = fh.entity_id
            WHERE fh.is_latest AND fh.quarter='{COVERAGE_QUARTER}'
              AND fh.asset_category='EC' AND fund_to_tp.tp = {tp}
        """).fetchone()[0]
        # Method B — fh.dm_rollup_entity_id → inst → top_parent
        b = con.execute(f"""
            SELECT COALESCE(SUM(fh.market_value_usd)/1e9, 0)
            FROM fund_holdings_v2 fh
            JOIN inst_to_tp_df ON inst_to_tp_df.entity_id = fh.dm_rollup_entity_id
            WHERE fh.is_latest AND fh.quarter='{COVERAGE_QUARTER}'
              AND fh.asset_category='EC' AND inst_to_tp_df.top_parent_entity_id = {tp}
        """).fetchone()[0]
        rows.append({"top_parent_entity_id": tp,
                     "name": r["top_parent_canonical_name"],
                     "method_a_b": round(a, 2),
                     "method_b_b": round(b, 2),
                     "delta_b": round(a - b, 2)})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 40)
    print(f"\n  Per-firm fund_tier $B under each method (top-25):")
    print(df.to_string(index=False))

    # === 7.2 — rollup_type divergence handling ===
    print()
    print("=" * 78)
    print("PHASE 7.2 — rollup_type divergence handling (Open Q2)")
    print("=" * 78)
    print()

    # Re-confirm the 13.8% divergence
    align = con.execute(f"""
        WITH fr AS (
            SELECT erh.entity_id,
                   MAX(CASE WHEN erh.rollup_type='decision_maker_v1' THEN erh.rollup_entity_id END) AS dm_r,
                   MAX(CASE WHEN erh.rollup_type='economic_control_v1' THEN erh.rollup_entity_id END) AS ec_r
            FROM entity_rollup_history erh
            JOIN entity_current ec ON ec.entity_id = erh.entity_id
            WHERE erh.valid_to = {SENTINEL} AND ec.entity_type = 'fund'
            GROUP BY erh.entity_id
        )
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN dm_r = ec_r THEN 1 ELSE 0 END) AS aligned,
               SUM(CASE WHEN dm_r IS DISTINCT FROM ec_r THEN 1 ELSE 0 END) AS diverged
        FROM fr
    """).fetchone()
    print(f"  Fund alignment (revalidation §1.2 baseline check):")
    print(f"    total funds: {align[0]:,}; aligned: {align[1]:,} ({100*align[1]/align[0]:.1f}%); "
          f"diverged: {align[2]:,} ({100*align[2]/align[0]:.1f}%)")

    # Sample divergent funds with name context
    div = con.execute(f"""
        WITH fr AS (
            SELECT erh.entity_id,
                   MAX(CASE WHEN erh.rollup_type='decision_maker_v1' THEN erh.rollup_entity_id END) AS dm_eid,
                   MAX(CASE WHEN erh.rollup_type='economic_control_v1' THEN erh.rollup_entity_id END) AS ec_eid
            FROM entity_rollup_history erh
            JOIN entity_current ec ON ec.entity_id = erh.entity_id
            WHERE erh.valid_to = {SENTINEL} AND ec.entity_type = 'fund'
            GROUP BY erh.entity_id
        ),
        div AS (
            SELECT fr.entity_id, fr.dm_eid, fr.ec_eid,
                   (SELECT display_name FROM entity_current ecf WHERE ecf.entity_id = fr.entity_id LIMIT 1) AS fund_name,
                   (SELECT display_name FROM entity_current ecd WHERE ecd.entity_id = fr.dm_eid LIMIT 1) AS dm_name,
                   (SELECT display_name FROM entity_current ecc WHERE ecc.entity_id = fr.ec_eid LIMIT 1) AS ec_name
            FROM fr WHERE fr.dm_eid IS DISTINCT FROM fr.ec_eid
        )
        SELECT div.entity_id, div.fund_name,
               div.dm_eid, div.dm_name, div.ec_eid, div.ec_name,
               COALESCE(SUM(fh.market_value_usd)/1e9, 0) AS fund_aum_b
        FROM div
        LEFT JOIN fund_holdings_v2 fh ON fh.entity_id = div.entity_id
          AND fh.is_latest AND fh.quarter='{COVERAGE_QUARTER}' AND fh.asset_category='EC'
        GROUP BY 1,2,3,4,5,6
        ORDER BY fund_aum_b DESC NULLS LAST
        LIMIT 50
    """).fetchdf()
    print(f"\n  Top-50 divergent funds by 2025Q4 EC AUM:")
    print(div.head(20).to_string(index=False))

    div.to_csv(WORKDIR / "cp-5-bundle-c-rollup-type-divergence.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-c-rollup-type-divergence.csv'}")

    # rollup_type loader semantic — inspect the builder
    print()
    print("  Loader semantics (from build_managers.py / build_classifications.py grep):")
    print("    decision_maker_v1: fund's named registrant adviser (the 'who manages this fund')")
    print("    economic_control_v1: ultimate parent that owns the adviser (the 'who owns the adviser')")
    print("    These align for ~86% of funds (where adviser IS the top operating AM).")
    print("    They diverge when the adviser is itself owned by a different parent — e.g.")
    print("    BlackRock Inc. (eid 3241) sub-adviser arms whose dm = arm-eid but ec = umbrella-eid.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
