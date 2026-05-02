"""inst-eid-bridge Phase 0 — Re-validate PR #252 numbers vs current data/13f.duckdb.

Read-only. No DB writes.

Outputs JSON to docs/findings/_inst_eid_bridge_phase0.json:
  - distinct_holdings_v2_eids
  - distinct_fund_rollup_eids (dm_rollup_entity_id)
  - mode_a_count (fund-rollup eids absent from holdings_v2)
  - mode_a_fund_aum
  - schema_holdings_v2 (column list)
  - schema_fund_holdings_v2 (column list)
  - schema_fund_universe (column list)
  - schema_entities (column list)
  - schema_entity_classification_history (column list)
  - schema_entity_relationships (column list)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
DB = ROOT / "data" / "13f.duckdb"
OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "findings"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "_inst_eid_bridge_phase0.json"


def schema(con, table: str) -> list[str]:
    rows = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [r[1] for r in rows]


def main():
    con = duckdb.connect(str(DB), read_only=True)
    out: dict = {}

    # Schemas
    for t in (
        "holdings_v2",
        "fund_holdings_v2",
        "fund_universe",
        "entities",
        "entity_classification_history",
        "entity_relationships",
        "managers",
    ):
        try:
            out[f"schema_{t}"] = schema(con, t)
        except Exception as e:
            out[f"schema_{t}_error"] = str(e)

    # Distinct eid universes
    h_eids = con.execute(
        "SELECT COUNT(DISTINCT entity_id) FROM holdings_v2 WHERE is_latest=TRUE"
    ).fetchone()[0]
    out["distinct_holdings_v2_entity_ids_latest"] = h_eids

    f_eids = con.execute(
        "SELECT COUNT(DISTINCT dm_rollup_entity_id) FROM fund_holdings_v2 "
        "WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL"
    ).fetchone()[0]
    out["distinct_fund_holdings_v2_dm_rollup_eids_latest"] = f_eids

    # Mode A — fund-rollup eids absent from holdings_v2 (entity_id only — strict)
    mode_a = con.execute(
        """
        WITH fund_inst AS (
          SELECT DISTINCT dm_rollup_entity_id AS eid
          FROM fund_holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        ),
        h_inst AS (
          SELECT DISTINCT entity_id AS eid FROM holdings_v2 WHERE is_latest=TRUE
        )
        SELECT COUNT(*) FROM fund_inst f
        LEFT JOIN h_inst h ON h.eid=f.eid
        WHERE h.eid IS NULL
        """
    ).fetchone()[0]
    out["mode_a_count_strict_entity_id"] = mode_a

    mode_a_aum = con.execute(
        """
        WITH fund_inst AS (
          SELECT DISTINCT dm_rollup_entity_id AS eid
          FROM fund_holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        ),
        h_inst AS (
          SELECT DISTINCT entity_id AS eid FROM holdings_v2 WHERE is_latest=TRUE
        ),
        missing AS (
          SELECT f.eid FROM fund_inst f
          LEFT JOIN h_inst h ON h.eid=f.eid
          WHERE h.eid IS NULL
        )
        SELECT COUNT(*) AS rows, SUM(market_value_usd) AS aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id IN (SELECT eid FROM missing)
        """
    ).fetchone()
    out["mode_a_fund_rows"] = mode_a_aum[0]
    out["mode_a_fund_aum_usd"] = float(mode_a_aum[1]) if mode_a_aum[1] is not None else 0.0

    # Holdings v2 totals (sanity)
    h_totals = con.execute(
        "SELECT COUNT(*), SUM(market_value_usd) FROM holdings_v2 WHERE is_latest=TRUE"
    ).fetchone()
    out["holdings_v2_latest_rows"] = h_totals[0]
    out["holdings_v2_latest_aum_usd"] = float(h_totals[1]) if h_totals[1] is not None else 0.0

    # Fund holdings v2 totals
    f_totals = con.execute(
        "SELECT COUNT(*), SUM(market_value_usd) FROM fund_holdings_v2 WHERE is_latest=TRUE"
    ).fetchone()
    out["fund_holdings_v2_latest_rows"] = f_totals[0]
    out["fund_holdings_v2_latest_aum_usd"] = (
        float(f_totals[1]) if f_totals[1] is not None else 0.0
    )

    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {OUT_PATH}")
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("schema_")}, indent=2, default=str))


if __name__ == "__main__":
    main()
