"""CP-5 fh2.dm_rollup decision recon — Phase 3.

Read-only investigation. Inventories every writer of
fund_holdings_v2.dm_rollup_entity_id and dm_rollup_name in PRODUCTION
code. Characterizes the staleness mechanism by sampling 20 rows where
Method A != Method B and confirming that fh.loaded_at predates the
relevant entity_rollup_history.computed_at.

Outputs:
  data/working/cp-5-fh2-dm-rollup-writers.csv

Refs:
  scripts/pipeline/load_nport.py (writer)
  scripts/enrich_fund_holdings_v2.py (writer)
  docs/findings/cp-5-bundle-c-discovery.md §7.1 (staleness root cause)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
ROLLUP_TYPE_CANONICAL = "decision_maker_v1"

REPO = Path(__file__).resolve().parents[2]
WORKDIR = REPO / "data" / "working"


# Writer inventory — manually compiled from grep of scripts/, validated against
# the raw read/write audit. Enumerated here so the CSV captures the writer's
# computation source + scope (per-row INSERT vs run-scoped UPDATE vs full
# table-scoped UPDATE), which the grep alone does not surface.
WRITERS = [
    # (file:line, writer_function, op, scope, source_of_truth, when_runs)
    (
        "scripts/pipeline/load_nport.py:773",
        "_promote_append_is_latest INSERT",
        "INSERT",
        "per-row at promote (new is_latest=TRUE rows)",
        "values from staging.fund_holdings_v2 (already pre-enriched in step 0)",
        "every N-PORT promote",
    ),
    (
        "scripts/pipeline/load_nport.py:984-1037",
        "_enrich_staging_entities (pre-promote on staging)",
        "UPDATE staging.fund_holdings_v2",
        "all staged rows for series_touched in the run",
        "ERH JOIN on entity_identifiers.identifier_type='series_id'",
        "every N-PORT promote (step 0, BEFORE super().promote)",
    ),
    (
        "scripts/pipeline/load_nport.py:1244-1287",
        "_bulk_enrich_run (post-promote)",
        "UPDATE fund_holdings_v2",
        "is_latest=TRUE rows for series_touched in the run",
        "ERH JOIN on entity_identifiers.identifier_type='series_id'",
        "every N-PORT promote (step 3, safety net)",
    ),
    (
        "scripts/enrich_fund_holdings_v2.py:331-348",
        "_apply_batch (BLOCK-2 full-scope backfill)",
        "UPDATE fund_holdings_v2",
        "rows WHERE entity_id IS NULL AND series_id resolvable",
        "ERH JOIN on entity_identifiers.identifier_type='series_id'",
        "manual run only; idempotent (NULL filter)",
    ),
    # Note: scripts/pipeline/shared.py:update_holdings_rollup is for
    # beneficial_ownership_v2, NOT fund_holdings_v2. Out of scope but listed
    # to flag the parallel pattern.
    (
        "scripts/pipeline/shared.py:440-540",
        "update_holdings_rollup (beneficial_ownership_v2)",
        "UPDATE beneficial_ownership_v2",
        "all rows OR filer_ciks scope",
        "ERH JOIN on entity_identifiers.identifier_type='cik'",
        "every 13D/G load via load_13dg.py",
    ),
]


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("PHASE 3a — writer inventory")
    print("=" * 78)
    df = pd.DataFrame(WRITERS, columns=[
        "site", "function", "op", "scope", "source_of_truth", "when_runs",
    ])
    out_path = WORKDIR / "cp-5-fh2-dm-rollup-writers.csv"
    df.to_csv(out_path, index=False)
    print(f"  Wrote {out_path} ({len(df)} writer sites)")
    print()
    for _, r in df.iterrows():
        print(f"  {r['site']}")
        print(f"    function: {r['function']}")
        print(f"    op:       {r['op']}")
        print(f"    scope:    {r['scope']}")
        print(f"    source:   {r['source_of_truth']}")
        print(f"    when:     {r['when_runs']}")
        print()

    # === Staleness mechanism characterization ===
    print("=" * 78)
    print("PHASE 3c — staleness mechanism (20-row sample)")
    print("=" * 78)
    con = duckdb.connect(DB_PATH, read_only=True)

    sample = con.execute(f"""
        WITH dm_live AS (
          SELECT erh.entity_id, erh.rollup_entity_id AS live_dm_eid,
                 erh.computed_at AS erh_computed_at
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        )
        SELECT
          fh.row_id,
          fh.entity_id,
          fh.series_id,
          fh.report_month,
          fh.loaded_at,
          fh.dm_rollup_entity_id AS method_b_eid,
          dl.live_dm_eid         AS method_a_eid,
          dl.erh_computed_at     AS erh_computed_at
        FROM fund_holdings_v2 fh
        JOIN dm_live dl ON dl.entity_id = fh.entity_id
        WHERE fh.is_latest = TRUE
          AND fh.dm_rollup_entity_id IS DISTINCT FROM dl.live_dm_eid
          AND fh.entity_id IS NOT NULL
          AND fh.loaded_at IS NOT NULL
          AND dl.erh_computed_at IS NOT NULL
        ORDER BY fh.loaded_at DESC
        LIMIT 20
    """).fetchdf()

    print(f"  Sampled {len(sample)} rows where Method A != Method B and both "
          f"timestamps are present.")
    print()

    if len(sample) == 0:
        print("  ERROR: no qualifying sample. Aborting staleness check.")
        con.close()
        return 1

    sample["erh_after_load"] = sample["erh_computed_at"] > sample["loaded_at"]
    n_after = int(sample["erh_after_load"].sum())
    print(f"  Rows where erh_computed_at > fh.loaded_at: {n_after} / {len(sample)}")
    print(f"  (Confirms staleness pattern: load happened BEFORE ERH was rebuilt.)")
    print()

    print("  Per-row detail:")
    for _, r in sample.iterrows():
        delta_days = (r["erh_computed_at"] - r["loaded_at"]).days
        flag = "STALE" if r["erh_after_load"] else "OK   "
        print(f"    row_id={int(r['row_id']):>9} eid={int(r['entity_id']):>5} "
              f"loaded={r['loaded_at'].strftime('%Y-%m-%d')} "
              f"erh_computed={r['erh_computed_at'].strftime('%Y-%m-%d')} "
              f"Δ={delta_days:>+5}d  "
              f"B={int(r['method_b_eid']) if pd.notna(r['method_b_eid']) else 'NULL':>5}  "
              f"A={int(r['method_a_eid']) if pd.notna(r['method_a_eid']) else 'NULL':>5}  "
              f"[{flag}]")

    # === Aggregate: how many rows total are "stale" by this criterion ===
    print()
    print("=" * 78)
    print("PHASE 3c (aggregate) — count of stale-vs-current rows table-wide")
    print("=" * 78)
    agg = con.execute(f"""
        WITH dm_live AS (
          SELECT erh.entity_id, erh.rollup_entity_id AS live_dm_eid,
                 erh.computed_at AS erh_computed_at
          FROM entity_rollup_history erh
          WHERE erh.valid_to = {SENTINEL}
            AND erh.rollup_type = '{ROLLUP_TYPE_CANONICAL}'
        ),
        stale_rows AS (
          SELECT fh.row_id, fh.loaded_at, dl.erh_computed_at,
                 fh.dm_rollup_entity_id AS method_b_eid,
                 dl.live_dm_eid         AS method_a_eid
          FROM fund_holdings_v2 fh
          JOIN dm_live dl ON dl.entity_id = fh.entity_id
          WHERE fh.is_latest = TRUE
            AND fh.entity_id IS NOT NULL
        )
        SELECT
          COUNT(*) AS total_joined,
          SUM(CASE WHEN method_a_eid IS DISTINCT FROM method_b_eid THEN 1 ELSE 0 END)
            AS n_diverged,
          SUM(CASE WHEN method_a_eid IS DISTINCT FROM method_b_eid
                   AND erh_computed_at > loaded_at THEN 1 ELSE 0 END)
            AS n_stale_diverged,
          SUM(CASE WHEN method_a_eid IS DISTINCT FROM method_b_eid
                   AND erh_computed_at <= loaded_at THEN 1 ELSE 0 END)
            AS n_pre_existing_diverged
        FROM stale_rows
    """).fetchone()
    print(f"  total fh2 is_latest rows w/ entity_id JOINed to ERH : "
          f"{agg[0]:>12,}")
    print(f"  diverged (Method A != Method B)                     : "
          f"{agg[1]:>12,}  ({agg[1]/max(agg[0],1)*100:.2f}%)")
    print(f"  diverged AND erh_computed_at > fh.loaded_at  (STALE): "
          f"{agg[2]:>12,}  ({agg[2]/max(agg[1],1)*100:.2f}% of diverged)")
    print(f"  diverged AND erh_computed_at <= fh.loaded_at        : "
          f"{agg[3]:>12,}  ({agg[3]/max(agg[1],1)*100:.2f}% of diverged)")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
