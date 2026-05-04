"""CP-5 Bundle B — Phase 2: rollup graph correctness.

  2.1 Multi-hop traversal stress (hop distribution, cycle detection)
  2.2 Quarter-by-quarter graph state (Q1-Q4 2025 — graph is time-invariant
      under current schema, so this primarily checks rollup *resolution* per
      quarter)
  2.3 84K rollup-builder-gap row cause categorization (Layer C from Bundle A)
  2.4 Operating-AM rollup policy enforcement audit (top-50 by AUM)

Outputs:
  data/working/cp-5-bundle-b-rollup-gap-cohort.csv
  data/working/cp-5-bundle-b-rollup-policy-audit.csv

Read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cp_5_bundle_b_common import (  # noqa: E402
    SENTINEL,
    WORKDIR,
    build_fund_to_tp,
    build_inst_to_tp,
    connect,
)


def phase_2_1_multi_hop(con) -> None:
    print("\n" + "=" * 80)
    print("Phase 2.1 — multi-hop traversal correctness")
    print("=" * 80)

    inst_to_tp = build_inst_to_tp(con)
    print(f"  inst_to_tp rows: {len(inst_to_tp):,}")
    print("  hop distribution:")
    for hopn, n in inst_to_tp["hops"].value_counts().sort_index().items():
        print(f"    hop={hopn}: {n:,}")
    cycles = inst_to_tp[inst_to_tp["cycle_truncated"]]
    print(f"  cycle-truncated entities: {len(cycles)}")
    if len(cycles):
        names = con.execute(
            f"SELECT entity_id, display_name FROM entity_current "
            f"WHERE entity_id IN ({','.join(str(int(e)) for e in cycles['entity_id'])})"
        ).fetchdf()
        print("    cycle eids + names:")
        print(names.to_string(index=False))

    max_hops = int(inst_to_tp["hops"].max())
    print(f"  max hop_count: {max_hops}")
    if max_hops > 10:
        print("  *** STOP: max hop > 10 — cycle bug suspected. ***")


def phase_2_2_quarter_state(con) -> None:
    print("\n" + "=" * 80)
    print("Phase 2.2 — quarter-by-quarter rollup resolution state")
    print("=" * 80)

    # The entity_relationships graph itself is time-invariant under current
    # schema (single open row per relationship). Per-quarter state is about
    # rollup *resolution rate* on that quarter's holdings.
    inst_to_tp = build_inst_to_tp(con)
    fund_to_tp = build_fund_to_tp(con, inst_to_tp)
    con.register("inst_to_tp_df", inst_to_tp[["entity_id", "top_parent_entity_id"]])
    con.register("fund_to_tp_df", fund_to_tp[["fund_entity_id", "top_parent_entity_id"]])

    rows = []
    for q in ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]:
        h13f_total = con.execute(
            f"SELECT COUNT(*) FROM holdings_v2 WHERE is_latest AND quarter='{q}'"
        ).fetchone()[0]
        h13f_resolved = con.execute(f"""
            SELECT COUNT(*)
            FROM holdings_v2 h
            JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
            WHERE h.is_latest AND h.quarter='{q}'
        """).fetchone()[0]
        fund_total = con.execute(
            f"SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest AND quarter='{q}' AND asset_category='EC'"
        ).fetchone()[0]
        fund_resolved = con.execute(f"""
            SELECT COUNT(*)
            FROM fund_holdings_v2 fh
            JOIN fund_to_tp_df ftp ON ftp.fund_entity_id = fh.entity_id
            WHERE fh.is_latest AND fh.quarter='{q}' AND fh.asset_category='EC'
              AND ftp.top_parent_entity_id IS NOT NULL
        """).fetchone()[0]
        rows.append({
            "quarter": q,
            "h13f_total": h13f_total,
            "h13f_resolved": h13f_resolved,
            "h13f_resolved_pct": round(100.0 * h13f_resolved / max(h13f_total, 1), 2),
            "fund_ec_total": fund_total,
            "fund_ec_resolved": fund_resolved,
            "fund_ec_resolved_pct": round(100.0 * fund_resolved / max(fund_total, 1), 2),
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    # Surface entities that resolve in some quarters but not others.
    # Method: list distinct entity_ids per quarter, count how many quarters
    # each appears in (in fund_holdings_v2 EC), and check if the (entity →
    # top_parent) resolution differs.
    flow = con.execute("""
        SELECT entity_id, COUNT(DISTINCT quarter) AS n_quarters_present
        FROM fund_holdings_v2
        WHERE is_latest AND asset_category='EC'
          AND quarter IN ('2025Q1','2025Q2','2025Q3','2025Q4')
        GROUP BY 1
    """).fetchdf()
    flow_with_tp = flow.merge(
        fund_to_tp.rename(columns={"fund_entity_id": "entity_id"})[
            ["entity_id", "top_parent_entity_id"]
        ],
        on="entity_id", how="left"
    )
    n_resolved = flow_with_tp["top_parent_entity_id"].notna().sum()
    n_unresolved = flow_with_tp["top_parent_entity_id"].isna().sum()
    print(f"  Distinct fund_entity_ids active 2025Q1-Q4: {len(flow_with_tp):,}")
    print(f"    resolved-to-top-parent: {n_resolved:,}")
    print(f"    unresolved (no rollup chain): {n_unresolved:,}")


def phase_2_3_rollup_gap(con) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("Phase 2.3 — 84K rollup-builder-gap row analysis")
    print("=" * 80)

    # The 84K cohort from Bundle A: fund_holdings_v2.is_latest where
    # rollup_entity_id IS NULL OR dm_rollup_entity_id IS NULL.
    cohort_count = con.execute("""
        SELECT
          COUNT(*) AS total_rows,
          SUM(market_value_usd)/1e9 AS total_aum_b,
          SUM(CASE WHEN rollup_entity_id IS NULL THEN 1 ELSE 0 END) AS null_rollup,
          SUM(CASE WHEN dm_rollup_entity_id IS NULL THEN 1 ELSE 0 END) AS null_dm_rollup,
          SUM(CASE WHEN rollup_entity_id IS NULL AND dm_rollup_entity_id IS NULL THEN 1 ELSE 0 END) AS null_both,
          COUNT(DISTINCT entity_id) AS n_distinct_funds,
          COUNT(DISTINCT fund_cik) AS n_distinct_ciks,
          COUNT(DISTINCT series_id) AS n_distinct_series
        FROM fund_holdings_v2
        WHERE is_latest
          AND (rollup_entity_id IS NULL OR dm_rollup_entity_id IS NULL)
    """).fetchdf()
    print(cohort_count.to_string(index=False))

    # Diagnose entity_id-NULL vs entity_id-present-but-rollup-NULL.
    null_eid = con.execute("""
        SELECT
          SUM(CASE WHEN entity_id IS NULL THEN 1 ELSE 0 END) AS rows_null_eid,
          SUM(CASE WHEN entity_id IS NOT NULL THEN 1 ELSE 0 END) AS rows_eid_present,
          COUNT(*) AS total
        FROM fund_holdings_v2
        WHERE is_latest
          AND (rollup_entity_id IS NULL OR dm_rollup_entity_id IS NULL)
    """).fetchdf()
    print("\n  entity_id presence in gap cohort:")
    print(null_eid.to_string(index=False))

    # Top fund_cik / series_id contributors (since entity_id is NULL).
    top_ciks = con.execute("""
        SELECT fund_cik,
               COUNT(*) AS n_rows,
               SUM(market_value_usd)/1e9 AS aum_b,
               COUNT(DISTINCT series_id) AS n_series,
               ANY_VALUE(family_name) AS sample_family,
               ANY_VALUE(fund_name) AS sample_fund
        FROM fund_holdings_v2
        WHERE is_latest
          AND (rollup_entity_id IS NULL OR dm_rollup_entity_id IS NULL)
        GROUP BY 1
        ORDER BY aum_b DESC NULLS LAST
        LIMIT 100
    """).fetchdf()
    print("\n  Top 20 fund_ciks in gap cohort by AUM:")
    print(top_ciks.head(20).to_string(index=False, max_colwidth=50))

    # Are these CIKs known to entity_identifiers (i.e., the entity exists but
    # the loader didn't link it)? Or genuinely unknown to the entity layer?
    cik_csv = ", ".join(f"'{c}'" for c in top_ciks["fund_cik"].dropna().head(50))
    if cik_csv:
        cik_link = con.execute(f"""
            SELECT ei.identifier_value AS fund_cik,
                   COUNT(DISTINCT ei.entity_id) AS n_eids
            FROM entity_identifiers ei
            WHERE ei.identifier_type IN ('cik','fund_cik','series_id')
              AND ei.valid_to = {SENTINEL}
              AND ei.identifier_value IN ({cik_csv})
            GROUP BY 1
        """).fetchdf()
        n_resolvable = len(cik_link)
        n_unresolvable = 50 - n_resolvable
        print(f"\n  Top-50 gap CIKs CIK→entity resolvability:")
        print(f"    resolvable to >=1 entity_id: {n_resolvable}")
        print(f"    unknown to entity_identifiers: {n_unresolvable}")

    top_ciks.to_csv(WORKDIR / "cp-5-bundle-b-rollup-gap-cohort.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-b-rollup-gap-cohort.csv'} (top 100 ciks)")
    return top_ciks


def phase_2_4_op_am_policy(_con) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("Phase 2.4 — operating-AM rollup policy audit (top-50 by AUM)")
    print("=" * 80)

    # _con not used — heuristic operates on the Phase 1 coverage matrix CSV.
    cov = pd.read_csv("data/working/cp-5-top-parent-coverage-matrix.csv")
    top50 = cov.head(50)

    # For each top_parent in top-50, check whether display_name suggests
    # bank/insurance/holding company (which would be a violation per memory
    # rule). Heuristic keyword match.
    bank_holding_terms = (
        "BANK ", "BANK,", "BANK\n", "BANCORP", "INSURANCE", "INSURANCE.",
        "FINANCIAL CORP", "FINANCIAL HOLDINGS", "GROUP HOLDINGS", "HOLDING CO",
        "HOLDINGS LLC", "HOLDINGS INC", "MUTUAL OF",
    )
    flagged = []
    for _, r in top50.iterrows():
        name = (r["top_parent_canonical_name"] or "").upper()
        match = [t for t in bank_holding_terms if t in name + " "]
        if match:
            flagged.append({
                "top_parent_entity_id": int(r["top_parent_entity_id"]),
                "name": r["top_parent_canonical_name"],
                "matched_terms": ";".join(match),
                "thirteen_f_b": r["thirteen_f_aum_billions"],
                "fund_tier_b_matrix_doubled": r["fund_tier_aum_billions"],
                "coverage_class": r["coverage_class"],
            })
    df = pd.DataFrame(flagged)
    if df.empty:
        print("  No top-50 top-parents have bank/insurance/holding-company name signals.")
    else:
        print(f"  Top-50 top-parents with bank/insurance/holding-co naming ({len(df)}):")
        print(df.to_string(index=False))

    df.to_csv(WORKDIR / "cp-5-bundle-b-rollup-policy-audit.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-b-rollup-policy-audit.csv'}")
    return df


def main() -> int:
    con = connect()
    WORKDIR.mkdir(parents=True, exist_ok=True)
    phase_2_1_multi_hop(con)
    phase_2_2_quarter_state(con)
    phase_2_3_rollup_gap(con)
    phase_2_4_op_am_policy(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
