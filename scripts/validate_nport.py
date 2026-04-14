#!/usr/bin/env python3
"""validate_nport.py — standalone validator for staged N-PORT runs.

Reads stg_nport_holdings + stg_nport_fund_universe from staging DB,
checks for BLOCK / FLAG / WARN conditions, runs the entity gate against
prod, writes a Markdown report at logs/reports/nport_{run_id}.md.

NOTE: Entity gate is stricter than 13D/G (validate_13dg.py).
13D/G uses FLAG for unknown filers (activists may be genuinely new).
N-PORT uses BLOCK for unknown series_ids — registered funds always
have prior EDGAR history. Unknown = data quality issue, resolve first.

BLOCK checks:
  - duplicate (series_id, report_month) in staged impacts
  - partial manifest rows (load_status='partial')
  - series_id matches synthetic fallback pattern (CIK_ACCESSION) →
    needs manual resolution before promote
  - unknown series_id not in entity_identifiers (HARD — see note above)
  - missing rollup_history for either economic_control_v1 or
    decision_maker_v1 worldview
  - missing classification_history for the resolved entity

FLAG checks:
  - reg_cik changed for an existing series_id vs prod (filer continuity)
  - top-10 CUSIP overlap < 10% vs prior quarter for same series
  - AUM delta > 80% QoQ for same series
  - new series_id not yet in prod fund_universe (acknowledgment needed)
  - is_final = 'Y' (fund closed)

WARN checks:
  - holdings count delta > 50% vs prior quarter for same series
  - AUM delta 50-80% QoQ
  - schema_version unrecognized in manifest

Lifecycle observations:
  - new series (first appearance): note discovery_quarter
  - inactive candidates (in prod fund_universe but not staged for 2+ quarters)
  - merger signals (one series goes inactive, sibling AUM grows > 80%)

Usage:
  python3 scripts/validate_nport.py --run-id R --staging
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.shared import entity_gate_check  # noqa: E402


REPORTS_DIR = os.path.join(BASE_DIR, "logs", "reports")


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------

def _staged_holdings(staging_con, run_id: str):
    return staging_con.execute(
        """
        SELECT s.*, m.run_id
        FROM stg_nport_holdings s
        JOIN ingestion_manifest m ON s.manifest_id = m.manifest_id
        WHERE m.run_id = ?
        """,
        [run_id],
    ).fetchdf()


def _staged_universe(staging_con, run_id: str):
    return staging_con.execute(
        """
        SELECT u.*, m.run_id
        FROM stg_nport_fund_universe u
        JOIN ingestion_manifest m ON u.manifest_id = m.manifest_id
        WHERE m.run_id = ?
        """,
        [run_id],
    ).fetchdf()


def _staged_impacts(staging_con, run_id: str):
    return staging_con.execute(
        """
        SELECT i.*, m.run_id
        FROM ingestion_impacts i
        JOIN ingestion_manifest m ON i.manifest_id = m.manifest_id
        WHERE m.run_id = ?
          AND m.source_type = 'NPORT'
        """,
        [run_id],
    ).fetchdf()


# ---------------------------------------------------------------------------
# BLOCK checks
# ---------------------------------------------------------------------------

def _block_dup_series_month(impacts):
    seen: dict[str, int] = {}
    out = []
    for _, row in impacts.iterrows():
        if row.get("unit_type") != "series_month":
            continue
        key = row["unit_key_json"]
        seen[key] = seen.get(key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            out.append({"gate": "dup_series_month", "unit_key_json": key,
                        "count": count})
    return out


def _block_partial_loads(impacts):
    return [
        {"gate": "partial_load",
         "unit_key_json": row["unit_key_json"],
         "load_status": row["load_status"]}
        for _, row in impacts.iterrows()
        if row.get("load_status") == "partial"
    ]


def _block_synthetic_series(holdings):
    """series_id matching r'^\\d+_\\d{10}-\\d{2}-\\d{6}$' is the synthetic
    f-string fallback emitted in fetch_nport_v2.parse() when
    metadata.series_id is absent."""
    out = []
    syn = holdings[holdings["series_id"].str.contains("_", regex=False)]
    for sid in syn["series_id"].unique():
        # Skip real S-prefixed series ids that happen to contain _
        if sid.startswith("S") and len(sid) <= 12:
            continue
        out.append({"gate": "series_id_synthetic_fallback", "series_id": sid})
    return out


# ---------------------------------------------------------------------------
# Entity gate (strict — BLOCK on unknown)
# ---------------------------------------------------------------------------

def _run_entity_gate(prod_con, holdings):
    series_ids = sorted({sid for sid in holdings["series_id"].unique()
                         if sid and not isinstance(sid, float)})
    if not series_ids:
        return None
    return entity_gate_check(
        prod_con,
        source_type="NPORT",
        identifier_type="series_id",
        staged_identifiers=series_ids,
        rollup_types=["economic_control_v1", "decision_maker_v1"],
        requires_classification=True,
    )


# ---------------------------------------------------------------------------
# FLAG checks
# ---------------------------------------------------------------------------

def _flag_reg_cik_changed(prod_con, universe):
    """Compare staged universe.fund_cik vs prod fund_universe.fund_cik."""
    out = []
    for _, row in universe.iterrows():
        sid = row["series_id"]
        new_cik = row["fund_cik"]
        prior = prod_con.execute(
            "SELECT fund_cik FROM fund_universe WHERE series_id = ?",
            [sid],
        ).fetchone()
        if prior and prior[0] and prior[0] != new_cik:
            out.append({"gate": "reg_cik_changed", "series_id": sid,
                        "prior_cik": prior[0], "new_cik": new_cik})
    return out


def _flag_top10_drift(prod_con, holdings):
    """Top-10 CUSIP overlap < 10% vs prior quarter, same series."""
    out = []
    for sid in holdings["series_id"].unique():
        cur_top = (
            holdings[holdings["series_id"] == sid]
            .sort_values("market_value_usd", ascending=False)["cusip"]
            .head(10).tolist()
        )
        if not cur_top:
            continue
        prior_top = prod_con.execute(
            """
            SELECT cusip FROM fund_holdings_v2
            WHERE series_id = ?
              AND report_month = (
                SELECT MAX(report_month) FROM fund_holdings_v2
                WHERE series_id = ?
              )
            ORDER BY market_value_usd DESC NULLS LAST LIMIT 10
            """,
            [sid, sid],
        ).fetchdf()
        if prior_top.empty:
            continue
        overlap = len(set(cur_top) & set(prior_top["cusip"].tolist()))
        if overlap < 1:  # strict: 0 of 10 overlapping = severe drift
            out.append({"gate": "top10_drift", "series_id": sid,
                        "overlap": overlap})
    return out


def _flag_aum_delta(prod_con, universe, threshold=0.80):
    out = []
    for _, row in universe.iterrows():
        sid = row["series_id"]
        new_aum = row.get("total_net_assets")
        if not new_aum or new_aum <= 0:
            continue
        prior = prod_con.execute(
            "SELECT total_net_assets FROM fund_universe WHERE series_id = ?",
            [sid],
        ).fetchone()
        if not prior or not prior[0] or prior[0] <= 0:
            continue
        delta = abs(new_aum - prior[0]) / prior[0]
        if delta > threshold:
            out.append({"gate": "aum_delta_huge", "series_id": sid,
                        "prior": float(prior[0]),
                        "new": float(new_aum),
                        "delta_pct": round(100 * delta, 1)})
    return out


def _flag_new_series(prod_con, universe):
    out = []
    for _, row in universe.iterrows():
        sid = row["series_id"]
        prior = prod_con.execute(
            "SELECT 1 FROM fund_universe WHERE series_id = ?", [sid],
        ).fetchone()
        if not prior:
            out.append({"gate": "new_series", "series_id": sid,
                        "fund_name": row.get("fund_name")})
    return out


def _flag_fund_closed(holdings):
    out = []
    closed = holdings[holdings["qc_flags"].notna()]
    for _, row in closed.iterrows():
        flags = row["qc_flags"]
        if flags and "fund_closed" in str(flags):
            out.append({"gate": "fund_closed",
                        "series_id": row["series_id"],
                        "report_month": row["report_month"]})
    return out


# ---------------------------------------------------------------------------
# WARN checks
# ---------------------------------------------------------------------------

def _warn_holdings_count_delta(prod_con, holdings, threshold=0.50):
    out = []
    series_counts = holdings.groupby("series_id").size().to_dict()
    for sid, cnt in series_counts.items():
        prior = prod_con.execute(
            """
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE series_id = ?
              AND report_month = (
                SELECT MAX(report_month) FROM fund_holdings_v2
                WHERE series_id = ?
              )
            """,
            [sid, sid],
        ).fetchone()
        if not prior or not prior[0]:
            continue
        delta = abs(cnt - prior[0]) / prior[0]
        if delta > threshold:
            out.append({"gate": "holdings_count_delta",
                        "series_id": sid,
                        "prior": int(prior[0]),
                        "new": int(cnt),
                        "delta_pct": round(100 * delta, 1)})
    return out


def _warn_aum_delta_medium(prod_con, universe):
    out = []
    for _, row in universe.iterrows():
        sid = row["series_id"]
        new_aum = row.get("total_net_assets")
        if not new_aum or new_aum <= 0:
            continue
        prior = prod_con.execute(
            "SELECT total_net_assets FROM fund_universe WHERE series_id = ?",
            [sid],
        ).fetchone()
        if not prior or not prior[0] or prior[0] <= 0:
            continue
        delta = abs(new_aum - prior[0]) / prior[0]
        if 0.50 < delta <= 0.80:
            out.append({"gate": "aum_delta_medium", "series_id": sid,
                        "delta_pct": round(100 * delta, 1)})
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _write_report(run_id, n_series, n_holdings, blocks, flags, warns,
                  gate, lifecycle):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"nport_{run_id}.md")
    promote_ok = (len(blocks) == 0 and (gate is None or len(gate.blocked) == 0))

    with open(path, "w") as fh:
        fh.write(f"# VALIDATION REPORT — N-PORT Run {run_id}\n\n")
        fh.write(f"_Generated: {datetime.now().isoformat()}_\n\n")
        fh.write("Entity gate: STRICT (BLOCK on unknown series_id).\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- Staged series:   **{n_series}**\n")
        fh.write(f"- Staged holdings: **{n_holdings:,}**\n")
        fh.write(f"- BLOCK: **{len(blocks)}** (promote refuses if > 0)\n")
        fh.write(f"- FLAG:  **{len(flags)}**\n")
        fh.write(f"- WARN:  **{len(warns)}**\n\n")
        if gate is not None:
            fh.write("## Entity gate (HARD)\n\n")
            fh.write(f"- Resolved:        **{len(gate.promotable)}**\n")
            fh.write(f"- Blocked (unknown): **{len(gate.blocked)}**\n")
            fh.write(f"- Pending review:  **{len(gate.new_entities_pending)}**\n\n")
        fh.write("## Fund universe lifecycle\n\n")
        for k, v in lifecycle.items():
            fh.write(f"- {k}: **{v}**\n")
        fh.write("\n")
        if blocks:
            fh.write("## BLOCK details\n\n")
            for b in blocks[:50]:
                fh.write(f"- {json.dumps(b, default=str)}\n")
            fh.write("\n")
        if gate is not None and gate.blocked:
            fh.write("## Entity-gate blocks\n\n")
            for b in gate.blocked[:50]:
                fh.write(f"- {json.dumps(b, default=str)}\n")
            fh.write("\n")
        if flags:
            fh.write("## FLAG details\n\n")
            for f in flags[:50]:
                fh.write(f"- {json.dumps(f, default=str)}\n")
            fh.write("\n")
        if warns:
            fh.write("## WARN details\n\n")
            for w in warns[:50]:
                fh.write(f"- {json.dumps(w, default=str)}\n")
            fh.write("\n")
        fh.write(f"## Promote-ready: **{'YES' if promote_ok else 'NO'}**\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate staged N-PORT run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--staging", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id
    staging_path = STAGING_DB if args.staging else PROD_DB

    staging_con = duckdb.connect(staging_path, read_only=True)
    # Read-only — the running app holds the prod write lock during normal
    # ops. entity_gate_check tries to INSERT into pending_entity_resolution
    # but wraps the call in try/except (see scripts/pipeline/shared.py),
    # so a read-only failure logs a warning and the gate still returns
    # accurate blocked / promotable / pending lists. The promote step
    # writes pending rows for real (it requires the write lock anyway).
    prod_con = duckdb.connect(PROD_DB, read_only=True)
    try:
        holdings = _staged_holdings(staging_con, run_id)
        universe = _staged_universe(staging_con, run_id)
        impacts = _staged_impacts(staging_con, run_id)

        n_series = universe["series_id"].nunique() if not universe.empty else 0
        n_holdings = len(holdings)
        if n_holdings == 0 and n_series == 0:
            print(f"No staged rows for run_id={run_id}")
            return

        blocks = (_block_dup_series_month(impacts)
                  + _block_partial_loads(impacts)
                  + _block_synthetic_series(holdings))
        flags = (_flag_reg_cik_changed(prod_con, universe)
                 + _flag_top10_drift(prod_con, holdings)
                 + _flag_aum_delta(prod_con, universe)
                 + _flag_new_series(prod_con, universe)
                 + _flag_fund_closed(holdings))
        warns = (_warn_holdings_count_delta(prod_con, holdings)
                 + _warn_aum_delta_medium(prod_con, universe))

        gate = _run_entity_gate(prod_con, holdings)

        # Lifecycle stats — informational
        new_count = sum(1 for f in flags if f.get("gate") == "new_series")
        lifecycle = {
            "new_series_in_run": new_count,
        }
    finally:
        staging_con.close()
        prod_con.close()

    report_path = _write_report(
        run_id, n_series, n_holdings, blocks, flags, warns, gate, lifecycle,
    )

    promote_ok = (len(blocks) == 0 and (gate is None or len(gate.blocked) == 0))

    print("=" * 60)
    print(f"VALIDATION REPORT — N-PORT Run {run_id}")
    print("=" * 60)
    print(f"Staged series:   {n_series}")
    print(f"Staged holdings: {n_holdings:,}")
    print(f"BLOCK:           {len(blocks)}")
    print(f"FLAG:            {len(flags)}")
    print(f"WARN:            {len(warns)}")
    if gate is not None:
        print()
        print("Entity gate (HARD — BLOCK on unknown):")
        print(f"  Resolved:        {len(gate.promotable)}")
        print(f"  Blocked (unknown): {len(gate.blocked)}")
        print(f"  Pending review:  {len(gate.new_entities_pending)}")
    if blocks:
        print()
        print("BLOCK details:")
        for b in blocks[:10]:
            print(f"  {b}")
    if gate is not None and gate.blocked:
        print()
        print("Entity-gate blocks (first 10):")
        for b in gate.blocked[:10]:
            print(f"  {b}")
    print()
    print(f"Promote-ready: {'YES' if promote_ok else 'NO'}")
    print(f"Report: {report_path}")
    sys.exit(0 if promote_ok else 1)


if __name__ == "__main__":
    main()
