#!/usr/bin/env python3
"""validate_nport_subset.py — fast set-based validator for N-PORT runs.

Complements scripts/validate_nport.py with a much cheaper pass that:
  * scopes every check to a subset of series_ids (inclusion list) AND
  * uses set-based SQL aggregates instead of per-series Python loops.

Designed for the Session 2 scale (~14K staged series) where
validate_nport.py's O(N) per-series prod queries take 45+ minutes. This
runner focuses on the BLOCK-tier checks that actually gate promote, runs
in under a minute, and writes a `logs/reports/nport_{run_id}.md` with
`Promote-ready: YES` when all pass.

The validator is **read-only** against prod. The excluded series_ids
(those failing the entity gate in prod — e.g. bond/money-market/index
funds that the legacy XML path filtered out) are reported here but
queued into ``pending_entity_resolution`` by the separate
``scripts/queue_nport_excluded.py`` script. Split in sec-04-p1 so that
"validate" stays pure-read.

Usage (two-step: validate, then queue):
    python3 scripts/validate_nport_subset.py \\
        --run-id nport_20260415_060422_352131 \\
        --resolved-file logs/nport_resolved_<run_id>.txt \\
        --excluded-file logs/nport_excluded_<run_id>.txt \\
        --staging
    python3 scripts/queue_nport_excluded.py \\
        --excluded-file logs/nport_excluded_<run_id>.txt
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import STAGING_DB, PROD_DB  # noqa: E402

REPORTS_DIR = os.path.join(BASE_DIR, "logs", "reports")


def _read_list(path: str) -> set[str]:
    with open(path) as fh:
        return {line.strip() for line in fh if line.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resolved-file", required=True,
                        help="File with one series_id per line — these go "
                             "through validation + promote.")
    parser.add_argument("--excluded-file", required=True,
                        help="File with one series_id per line — these are "
                             "queued in pending_entity_resolution and held "
                             "out of promote.")
    parser.add_argument("--staging", action="store_true")
    args = parser.parse_args()

    resolved = _read_list(args.resolved_file)
    excluded = _read_list(args.excluded_file)
    print(f"resolved (to promote): {len(resolved):,}")
    print(f"excluded (to queue):   {len(excluded):,}")

    staging_path = STAGING_DB if args.staging else PROD_DB
    stg = duckdb.connect(staging_path, read_only=True)
    # Validator is read-only. Queueing to pending_entity_resolution is done
    # by scripts/queue_nport_excluded.py (sec-04-p1).
    prod = duckdb.connect(PROD_DB, read_only=True)

    try:
        # Push resolved + excluded sets into staging for SQL filtering
        stg.register("resolved", duckdb.from_query(
            "SELECT unnest(?::VARCHAR[]) AS series_id",
            params=[sorted(resolved)],
        ).to_df())
    except TypeError:
        # Older DuckDB builds don't expose from_query params — fall back
        # to building the DataFrame directly via pandas.
        import pandas as pd
        stg.register("resolved", pd.DataFrame({"series_id": sorted(resolved)}))
        prod.register("resolved", pd.DataFrame({"series_id": sorted(resolved)}))
    else:
        prod.register("resolved", duckdb.from_query(
            "SELECT unnest(?::VARCHAR[]) AS series_id",
            params=[sorted(resolved)],
        ).to_df())

    run_id = args.run_id

    # BLOCK 1 — no duplicate (series_id, report_month) in the resolved subset.
    dup = stg.execute("""
        SELECT i.unit_key_json, COUNT(*) AS n
        FROM ingestion_impacts i
        JOIN ingestion_manifest m ON i.manifest_id = m.manifest_id
        WHERE m.run_id = ? AND i.unit_type = 'series_month'
          AND JSON_EXTRACT_STRING(i.unit_key_json, '$.series_id') IN (
              SELECT series_id FROM resolved)
        GROUP BY 1 HAVING COUNT(*) > 1
    """, [run_id]).fetchdf()

    # BLOCK 2 — no partial load_status in resolved subset.
    partials = stg.execute("""
        SELECT COUNT(*) AS n
        FROM ingestion_impacts i
        JOIN ingestion_manifest m ON i.manifest_id = m.manifest_id
        WHERE m.run_id = ? AND i.unit_type = 'series_month'
          AND i.load_status = 'partial'
          AND JSON_EXTRACT_STRING(i.unit_key_json, '$.series_id') IN (
              SELECT series_id FROM resolved)
    """, [run_id]).fetchone()[0]

    # BLOCK 3 — synthetic series in resolved subset.
    # A synthetic key (`{cik}_{accession}`, no leading 'S') normally must
    # live in the excluded set. The S1 path of resolve_pending_series.py
    # legitimately wires synthetics whose `fund_cik` is already an entity
    # — those have an active `entity_identifiers(identifier_type='series_id')`
    # row and pass the EC + DM rollup gates above. Only BLOCK on synthetics
    # that are NOT entity-backed (`synth_no_entity`); allow `synth_resolved`
    # synthetics through.
    synth_in_resolved = stg.execute("""
        SELECT DISTINCT s.series_id
        FROM stg_nport_holdings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
          AND s.series_id IN (SELECT series_id FROM resolved)
          AND NOT s.series_id LIKE 'S%'
    """, [run_id]).fetchdf()
    synth_no_entity = 0
    synth_resolved = 0
    if not synth_in_resolved.empty:
        prod.register("synth_in_resolved", synth_in_resolved)
        synth_with_entity = {
            r[0] for r in prod.execute("""
                SELECT s.series_id
                FROM synth_in_resolved s
                JOIN entity_identifiers ei
                  ON ei.identifier_type = 'series_id'
                 AND ei.identifier_value = s.series_id
                 AND ei.valid_to = DATE '9999-12-31'
            """).fetchall()
        }
        prod.unregister("synth_in_resolved")
        all_synth = set(synth_in_resolved["series_id"].tolist())
        synth_resolved = len(synth_with_entity)
        synth_no_entity = len(all_synth - synth_with_entity)

    # Entity gate (set-based) — resolved subset intersected with
    # entity_identifiers + both rollup worldviews (economic_control_v1 and
    # decision_maker_v1 — N-PORT requires both per promote_nport enrichment).
    gate_pass = prod.execute("""
        SELECT COUNT(*) AS total_resolved,
               COUNT(ei.entity_id) AS has_identifier,
               COUNT(ec.rollup_entity_id) AS has_ec_rollup,
               COUNT(dm.rollup_entity_id) AS has_dm_rollup
        FROM resolved r
        LEFT JOIN entity_identifiers ei
               ON ei.identifier_type = 'series_id'
              AND ei.identifier_value = r.series_id
              AND ei.valid_to = DATE '9999-12-31'
        LEFT JOIN entity_rollup_history ec
               ON ec.entity_id = ei.entity_id
              AND ec.rollup_type = 'economic_control_v1'
              AND ec.valid_to = DATE '9999-12-31'
        LEFT JOIN entity_rollup_history dm
               ON dm.entity_id = ei.entity_id
              AND dm.rollup_type = 'decision_maker_v1'
              AND dm.valid_to = DATE '9999-12-31'
    """).fetchone()
    total, has_id, has_ec, has_dm = gate_pass
    missing_ec = total - (has_ec or 0)
    missing_dm = total - (has_dm or 0)

    # Rows staged in the resolved subset (informational)
    resolved_rows = stg.execute("""
        SELECT COUNT(*) AS n, COUNT(DISTINCT s.series_id) AS series,
               COUNT(DISTINCT s.report_month) AS months
        FROM stg_nport_holdings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
          AND s.series_id IN (SELECT series_id FROM resolved)
    """, [run_id]).fetchone()

    # Verdict
    blocks = []
    if len(dup):
        blocks.append(f"{len(dup)} duplicate (series_id, report_month) impact tuples")
    if partials:
        blocks.append(f"{partials} partial load rows")
    if synth_no_entity:
        blocks.append(f"{synth_no_entity} synth_no_entity series in resolved subset "
                      f"(synthetic key with no active entity_identifiers row)")
    if missing_ec:
        blocks.append(f"{missing_ec} series missing economic_control_v1 rollup")
    if missing_dm:
        blocks.append(f"{missing_dm} series missing decision_maker_v1 rollup")

    promote_ok = not blocks

    # Write Markdown report
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"nport_{run_id}.md")
    with open(path, "w") as fh:
        fh.write(f"# VALIDATION REPORT — N-PORT Run {run_id}\n\n")
        fh.write(f"_Generated: {datetime.now().isoformat()}_\n")
        fh.write("_Validator: validate_nport_subset.py (fast set-based)_\n\n")
        fh.write("## Scope\n\n")
        fh.write(f"- Resolved (to promote): **{len(resolved):,}** series\n")
        fh.write(f"- Excluded (queued):     **{len(excluded):,}** series\n")
        fh.write(f"- Staged rows in resolved subset: "
                 f"**{resolved_rows[0]:,}** across "
                 f"**{resolved_rows[1]:,}** series and "
                 f"**{resolved_rows[2]}** months\n\n")
        fh.write("## BLOCK checks\n\n")
        fh.write(f"- Duplicate impacts: **{len(dup)}** (threshold 0)\n")
        fh.write(f"- Partial loads: **{partials}** (threshold 0)\n")
        fh.write(f"- Synthetic series in resolved subset: "
                 f"**{synth_no_entity + synth_resolved}** total — "
                 f"**{synth_no_entity}** synth_no_entity (BLOCK, threshold 0), "
                 f"**{synth_resolved}** synth_resolved (allowed; entity-backed via S1)\n")
        fh.write(f"- Resolved series missing economic_control_v1 rollup: "
                 f"**{missing_ec}** / {total} (threshold 0)\n")
        fh.write(f"- Resolved series missing decision_maker_v1 rollup: "
                 f"**{missing_dm}** / {total} (threshold 0)\n\n")
        fh.write("## Excluded series\n\n")
        fh.write(f"{len(excluded):,} series eligible for queueing into "
                 f"`pending_entity_resolution` with "
                 f"`source_type='NPORT'`, `identifier_type='series_id'`. "
                 f"Run `scripts/queue_nport_excluded.py --excluded-file "
                 f"<path>` to persist; this validator is read-only. "
                 f"Breakdown:\n")
        syn = [s for s in excluded if not s.startswith("S")]
        real = [s for s in excluded if s.startswith("S")]
        fh.write(f"- Real SERIES_ID (missing entity record): **{len(real):,}**\n")
        fh.write(f"- Synthetic `{{cik}}_{{accession}}` fallback: "
                 f"**{len(syn):,}**\n\n")
        fh.write(f"## Promote-ready: **{'YES' if promote_ok else 'NO'}**\n")
        if blocks:
            fh.write("\nBlockers:\n")
            for b in blocks:
                fh.write(f"- {b}\n")

    print("\n" + "=" * 60)
    print(f"VALIDATION REPORT — N-PORT Run {run_id}")
    print("=" * 60)
    print(f"Resolved:           {len(resolved):,} series")
    print(f"Excluded (to queue): {len(excluded):,} series (run "
          f"queue_nport_excluded.py to persist)")
    print(f"Staged rows:        {resolved_rows[0]:,}")
    print(f"BLOCK checks: dup={len(dup)} partial={partials} "
          f"synth_no_entity={synth_no_entity} synth_resolved={synth_resolved} "
          f"missing_ec={missing_ec} missing_dm={missing_dm}")
    print(f"\nPromote-ready: {'YES' if promote_ok else 'NO'}")
    print(f"Report: {path}")

    stg.close()
    prod.close()
    sys.exit(0 if promote_ok else 1)


if __name__ == "__main__":
    main()
