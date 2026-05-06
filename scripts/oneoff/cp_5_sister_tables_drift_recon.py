"""CP-5 sister-tables drift recon — read-only investigation.

Sizes drift state on holdings_v2 and beneficial_ownership_v2 — the two
sister tables flagged by PR #288 fh2 recon as carrying the same
denormalize-from-ERH pattern that fund_holdings_v2 had before PR #289
dropped its columns.

Drives the chat-side decision: do sister-table drop PRs ship before
CP-5.1 (drift material), with CP-5.1, or after (low drift, schema
consistency only)?

Outputs:
  data/working/cp-5-sister-table-holdings_v2-drift.csv
  data/working/cp-5-sister-table-beneficial_ownership_v2-drift.csv

Refs:
  docs/findings/cp-5-fh2-dm-rollup-decision-recon-results.md (PR #288)
  docs/findings/cp-5-fh2-dm-rollup-drop-results.md (PR #289)
  docs/findings/cp-5-bundle-c-discovery.md §7.5
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
ROLLUP_TYPE_CANONICAL = "decision_maker_v1"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")

REPO = Path(__file__).resolve().parents[2]
WORKDIR = REPO / "data" / "working"


# --- Per-table specs ---
TABLES = {
    "holdings_v2": {
        "value_col": "market_value_usd",
        "is_latest_col": "is_latest",
        "loaded_col": "loaded_at",
    },
    "beneficial_ownership_v2": {
        "value_col": "aggregate_value",
        "is_latest_col": "is_latest",
        "loaded_col": "loaded_at",
    },
}


def build_inst_to_top_parent(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cycle-safe institution→top-parent climb. Mirrors
    cp_5_fh2_dm_rollup_decision_recon_phase1.build_inst_to_top_parent."""
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

    seed = con.execute("""
        SELECT entity_id FROM entity_current WHERE entity_type = 'institution'
    """).fetchdf()
    cur = {ent: ent for ent in seed["entity_id"]}
    visited = {ent: {ent} for ent in cur}
    cycles = set()
    for _ in range(20):
        changed = 0
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
            changed += 1
        if changed == 0:
            break
    return pd.DataFrame({
        "institution_entity_id": list(cur.keys()),
        "top_parent_entity_id": list(cur.values()),
    })


def recon_table(con, table, spec, inst_to_tp):
    print("=" * 78)
    print(f"TABLE — {table}")
    print("=" * 78)

    val = spec["value_col"]
    lat = spec["is_latest_col"]

    # Step 1b — column population
    pop = con.execute(f"""
        SELECT
          COUNT(*) AS total,
          COUNT(dm_rollup_entity_id) AS dm_eid_pop,
          COUNT(dm_rollup_name)      AS dm_name_pop,
          COUNT(*) FILTER (WHERE {lat} = TRUE)              AS is_latest_rows,
          COUNT(*) FILTER (WHERE {lat} = TRUE AND dm_rollup_entity_id IS NOT NULL) AS lat_dm_pop
        FROM {table}
    """).fetchone()
    print(f"  total                : {pop[0]:>15,}")
    print(f"  dm_rollup_eid pop    : {pop[1]:>15,} ({pop[1]/max(pop[0],1)*100:.2f}%)")
    print(f"  dm_rollup_name pop   : {pop[2]:>15,} ({pop[2]/max(pop[0],1)*100:.2f}%)")
    print(f"  is_latest=TRUE rows  : {pop[3]:>15,} ({pop[3]/max(pop[0],1)*100:.2f}%)")
    print(f"  is_latest dm_eid pop : {pop[4]:>15,}")

    # Step 2a — Method A vs Method B per top-parent
    con.register("inst_to_tp", inst_to_tp)

    method_a = con.execute(f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id        AS fund_entity_id,
                 erh.rollup_entity_id AS dm_rollup_eid_a
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT
          COALESCE(itp.top_parent_entity_id, dr.dm_rollup_eid_a) AS top_parent_eid,
          SUM(t.{val}) AS aum_method_a
        FROM {table} t
        LEFT JOIN dm_rollup dr  ON dr.fund_entity_id = t.entity_id
        LEFT JOIN inst_to_tp itp ON itp.institution_entity_id = dr.dm_rollup_eid_a
        WHERE t.{lat} = TRUE
          AND t.{val} IS NOT NULL
        GROUP BY top_parent_eid
    """).fetchdf()

    method_b = con.execute(f"""
        SELECT
          COALESCE(itp.top_parent_entity_id, t.dm_rollup_entity_id) AS top_parent_eid,
          SUM(t.{val}) AS aum_method_b
        FROM {table} t
        LEFT JOIN inst_to_tp itp ON itp.institution_entity_id = t.dm_rollup_entity_id
        WHERE t.{lat} = TRUE
          AND t.{val} IS NOT NULL
        GROUP BY top_parent_eid
    """).fetchdf()

    drift = method_a.merge(method_b, on="top_parent_eid", how="outer").fillna(0.0)
    drift["delta_aum"] = drift["aum_method_a"] - drift["aum_method_b"]
    drift["abs_delta_aum"] = drift["delta_aum"].abs()
    drift["combined_aum"] = drift["aum_method_a"] + drift["aum_method_b"]

    name_lookup = con.execute("SELECT entity_id, display_name FROM entity_current").fetchdf()
    drift = drift.merge(
        name_lookup.rename(columns={"entity_id": "top_parent_eid"}),
        on="top_parent_eid", how="left",
    )

    drift_top = drift.sort_values("combined_aum", ascending=False).head(50).copy()
    drift_top["aum_method_a_b"] = (drift_top["aum_method_a"] / 1e9).round(3)
    drift_top["aum_method_b_b"] = (drift_top["aum_method_b"] / 1e9).round(3)
    drift_top["delta_aum_b"]    = (drift_top["delta_aum"]    / 1e9).round(3)
    drift_top["delta_pct"]      = (drift_top["delta_aum"] /
                                   drift_top["aum_method_a"].where(
                                       drift_top["aum_method_a"] != 0)).round(4)
    out = drift_top[[
        "top_parent_eid", "display_name",
        "aum_method_a_b", "aum_method_b_b",
        "delta_aum_b", "delta_pct",
    ]].rename(columns={"display_name": "top_parent_name"})

    out_path = WORKDIR / f"cp-5-sister-table-{table}-drift.csv"
    out.to_csv(out_path, index=False)
    print(f"\n  Wrote {out_path} ({len(out)} rows)")

    print("\n  Top 25 by |delta_aum|:")
    top25 = drift.sort_values("abs_delta_aum", ascending=False).head(25).copy()
    nonzero = (drift["abs_delta_aum"] > 0).sum()
    print(f"  (top-parents with non-zero drift: {nonzero})")
    for _, r in top25.iterrows():
        nm = r["display_name"] if isinstance(r["display_name"], str) else "(no-name)"
        eid = int(r["top_parent_eid"]) if pd.notna(r["top_parent_eid"]) else -1
        print(f"    eid={eid:>6} {nm[:42]:<42} "
              f"A=${r['aum_method_a']/1e9:>10,.3f}B "
              f"B=${r['aum_method_b']/1e9:>10,.3f}B "
              f"Δ=${r['delta_aum']/1e9:>10,.3f}B")

    # Step 2c — diverged-row count + per-firm
    print("\n  Per-fund alignment (is_latest=TRUE, dm_rollup_eid Method A vs Method B):")
    aligned = con.execute(f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id, erh.rollup_entity_id
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        ),
        per_row AS (
          SELECT t.dm_rollup_entity_id AS method_b_eid,
                 dr.rollup_entity_id   AS method_a_eid
          FROM {table} t
          LEFT JOIN dm_rollup dr ON dr.entity_id = t.entity_id
          WHERE t.{lat} = TRUE
        )
        SELECT
          COUNT(*) AS n_rows,
          SUM(CASE WHEN method_a_eid IS NOT DISTINCT FROM method_b_eid
                   THEN 1 ELSE 0 END) AS n_aligned,
          SUM(CASE WHEN method_a_eid IS DISTINCT FROM method_b_eid
                   THEN 1 ELSE 0 END) AS n_diverged
        FROM per_row
    """).fetchone()
    print(f"    n_rows    : {aligned[0]:>10,}")
    print(f"    n_aligned : {aligned[1]:>10,}  ({aligned[1]/max(aligned[0],1)*100:.2f}%)")
    print(f"    n_diverged: {aligned[2]:>10,}  ({aligned[2]/max(aligned[0],1)*100:.2f}%)")

    return {
        "table": table,
        "total": pop[0],
        "is_latest": pop[3],
        "n_aligned": aligned[1],
        "n_diverged": aligned[2],
        "nonzero_top_parents": int(nonzero),
        "abs_drift_total_b": float(drift["abs_delta_aum"].sum() / 1e9),
    }


def staleness_check(con, table, spec):
    """Step 2b — sample 10 diverged rows and check load timestamp vs ERH update."""
    print(f"\n  Step 2b — staleness mechanism for {table} (10 sample diverged rows):")
    val = spec["value_col"]
    lat = spec["is_latest_col"]
    loaded = spec["loaded_col"]
    sample = con.execute(f"""
        WITH dm_rollup AS (
          SELECT erh.entity_id, erh.rollup_entity_id, erh.computed_at AS erh_computed_at
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT t.entity_id,
               t.dm_rollup_entity_id AS method_b_eid,
               dr.rollup_entity_id   AS method_a_eid,
               t.{loaded}            AS row_loaded_at,
               dr.erh_computed_at,
               t.{val}               AS value
        FROM {table} t
        LEFT JOIN dm_rollup dr ON dr.entity_id = t.entity_id
        WHERE t.{lat} = TRUE
          AND dr.rollup_entity_id IS DISTINCT FROM t.dm_rollup_entity_id
        ORDER BY t.entity_id
        LIMIT 10
    """).fetchdf()
    if sample.empty:
        print("    (no diverged rows)")
        return
    for _, r in sample.iterrows():
        stale = r["row_loaded_at"] < r["erh_computed_at"] if pd.notna(r["erh_computed_at"]) else False
        print(f"    eid={r['entity_id']:>6} A={r['method_a_eid']} B={r['method_b_eid']} "
              f"row_loaded={r['row_loaded_at']} erh_computed={r['erh_computed_at']} "
              f"stale={stale}")


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    inst_to_tp = build_inst_to_top_parent(con)
    print(f"inst_to_tp size: {len(inst_to_tp):,} institutions\n")

    summaries = []
    for tbl, spec in TABLES.items():
        s = recon_table(con, tbl, spec, inst_to_tp)
        staleness_check(con, tbl, spec)
        summaries.append(s)
        print()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for s in summaries:
        print(f"  {s['table']:<28} total={s['total']:>11,}  is_latest={s['is_latest']:>10,}  "
              f"diverged={s['n_diverged']:>9,}  abs_drift=${s['abs_drift_total_b']:>10,.2f}B  "
              f"nonzero_top_parents={s['nonzero_top_parents']}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
