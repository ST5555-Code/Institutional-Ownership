"""
Phase 1.5 — Cross-tier consistency.

Read-only:
  1.5.1 Institution presence — fund-side institutions missing from holdings_v2.is_latest=TRUE
  1.5.2 AUM plausibility — fund_aum_at_inst > inst_13f_aum * 1.10
  1.5.3 Merged / superseded entities — funds rolling up to deprecated entities
"""
import duckdb
import json
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"
OUT = Path(__file__).resolve().parents[2] / "docs" / "findings" / "_phase15_raw.json"


def main():
    con = duckdb.connect(str(DB), read_only=True)
    out = {}

    # ---------- 1.5.1 INSTITUTION PRESENCE ----------
    # Fund-side institutions: distinct dm_rollup_entity_id (and rollup_entity_id) on is_latest=TRUE.
    # Holdings_v2 institution-level identifiers: rollup_entity_id is the canonical institution
    # (per "Tier-2 institution-layer" convention used by Admin Refresh).
    presence = con.execute("""
        WITH fund_inst AS (
          SELECT DISTINCT dm_rollup_entity_id AS eid
          FROM fund_holdings_v2 WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
          UNION
          SELECT DISTINCT rollup_entity_id AS eid
          FROM fund_holdings_v2 WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
        ),
        h_inst AS (
          SELECT DISTINCT rollup_entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
          UNION
          SELECT DISTINCT entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND entity_id IS NOT NULL
        ),
        missing AS (
          SELECT fi.eid FROM fund_inst fi
          LEFT JOIN h_inst hi ON hi.eid = fi.eid
          WHERE hi.eid IS NULL
        )
        SELECT COUNT(*) FROM missing
    """).fetchone()

    # Compute exposure & samples
    missing_exposure = con.execute("""
        WITH fund_inst AS (
          SELECT DISTINCT dm_rollup_entity_id AS eid FROM fund_holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
          UNION
          SELECT DISTINCT rollup_entity_id AS eid FROM fund_holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
        ),
        h_inst AS (
          SELECT DISTINCT rollup_entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
          UNION
          SELECT DISTINCT entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND entity_id IS NOT NULL
        ),
        missing AS (
          SELECT fi.eid FROM fund_inst fi
          LEFT JOIN h_inst hi ON hi.eid = fi.eid
          WHERE hi.eid IS NULL
        )
        SELECT COUNT(*) AS rows, SUM(f.market_value_usd) AS aum
        FROM fund_holdings_v2 f
        WHERE f.is_latest=TRUE
          AND (f.dm_rollup_entity_id IN (SELECT eid FROM missing)
               OR f.rollup_entity_id IN (SELECT eid FROM missing))
    """).fetchone()

    missing_samples = con.execute("""
        WITH fund_inst AS (
          SELECT DISTINCT dm_rollup_entity_id AS eid FROM fund_holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
          UNION
          SELECT DISTINCT rollup_entity_id AS eid FROM fund_holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
        ),
        h_inst AS (
          SELECT DISTINCT rollup_entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
          UNION
          SELECT DISTINCT entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND entity_id IS NOT NULL
        ),
        missing AS (
          SELECT fi.eid FROM fund_inst fi
          LEFT JOIN h_inst hi ON hi.eid = fi.eid
          WHERE hi.eid IS NULL
        )
        SELECT m.eid, e.canonical_name, e.entity_type,
               COUNT(*) AS rows, SUM(f.market_value_usd) AS aum
        FROM missing m
        LEFT JOIN entities e ON e.entity_id = m.eid
        LEFT JOIN fund_holdings_v2 f
               ON f.is_latest=TRUE
              AND (f.dm_rollup_entity_id = m.eid OR f.rollup_entity_id = m.eid)
        GROUP BY m.eid, e.canonical_name, e.entity_type
        ORDER BY aum DESC NULLS LAST
        LIMIT 20
    """).fetchall()

    out["1_5_1_institution_presence"] = {
        "missing_count": presence[0],
        "fund_side_rows_exposed": missing_exposure[0],
        "fund_side_aum_exposed": missing_exposure[1],
        "samples": missing_samples,
    }

    # ---------- 1.5.2 AUM PLAUSIBILITY ----------
    # fund-side AUM at institution: SUM fund_holdings_v2.market_value_usd by dm_rollup_entity_id (is_latest)
    # institution 13F AUM: SUM holdings_v2.market_value_usd by rollup_entity_id (is_latest)
    plausibility = con.execute("""
        WITH fund_aum AS (
          SELECT dm_rollup_entity_id AS eid, SUM(market_value_usd) AS fund_aum_at_inst
          FROM fund_holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
          GROUP BY dm_rollup_entity_id
        ),
        inst_aum AS (
          SELECT rollup_entity_id AS eid, SUM(market_value_usd) AS inst_13f_aum
          FROM holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
          GROUP BY rollup_entity_id
        )
        SELECT fa.eid, e.canonical_name,
               fa.fund_aum_at_inst,
               COALESCE(ia.inst_13f_aum, 0) AS inst_13f_aum,
               (fa.fund_aum_at_inst - COALESCE(ia.inst_13f_aum, 0)) AS abs_delta,
               CASE WHEN COALESCE(ia.inst_13f_aum,0) > 0
                    THEN fa.fund_aum_at_inst / ia.inst_13f_aum
                    ELSE NULL END AS ratio
        FROM fund_aum fa
        LEFT JOIN inst_aum ia ON ia.eid = fa.eid
        LEFT JOIN entities e ON e.entity_id = fa.eid
        WHERE fa.fund_aum_at_inst > COALESCE(ia.inst_13f_aum, 0) * 1.10
           OR ia.inst_13f_aum IS NULL
        ORDER BY abs_delta DESC NULLS LAST
        LIMIT 25
    """).fetchall()

    # Total count of mismatches
    plausibility_count = con.execute("""
        WITH fund_aum AS (
          SELECT dm_rollup_entity_id AS eid, SUM(market_value_usd) AS fund_aum_at_inst
          FROM fund_holdings_v2 WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
          GROUP BY dm_rollup_entity_id
        ),
        inst_aum AS (
          SELECT rollup_entity_id AS eid, SUM(market_value_usd) AS inst_13f_aum
          FROM holdings_v2 WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
          GROUP BY rollup_entity_id
        )
        SELECT
          COUNT(*) FILTER (WHERE fa.fund_aum_at_inst > COALESCE(ia.inst_13f_aum,0) * 1.10
                                 OR ia.inst_13f_aum IS NULL) AS n_mismatch,
          COUNT(*) AS n_total
        FROM fund_aum fa
        LEFT JOIN inst_aum ia ON ia.eid = fa.eid
    """).fetchone()

    out["1_5_2_aum_plausibility"] = {
        "n_mismatch": plausibility_count[0],
        "n_total_inst_with_funds": plausibility_count[1],
        "top25": plausibility,
    }

    # ---------- 1.5.3 MERGED / SUPERSEDED ENTITIES ----------
    # Use entity_classification_history with valid_to < CURRENT_DATE
    # (open rows are 9999-12-31 sentinel) to flag deprecated entities.
    deprecated = con.execute("""
        WITH closed AS (
          SELECT entity_id, MAX(valid_to) AS last_valid_to
          FROM entity_classification_history
          WHERE valid_to IS NOT NULL
            AND valid_to < CURRENT_DATE
            AND valid_to <> DATE '9999-12-31'
          GROUP BY entity_id
        ),
        open_rows AS (
          SELECT DISTINCT entity_id FROM entity_classification_history
          WHERE valid_to = DATE '9999-12-31' OR valid_to IS NULL OR valid_to >= CURRENT_DATE
        ),
        truly_closed AS (
          SELECT c.entity_id, c.last_valid_to FROM closed c
          LEFT JOIN open_rows o ON o.entity_id = c.entity_id
          WHERE o.entity_id IS NULL
        ),
        fund_rollups AS (
          SELECT dm_rollup_entity_id AS eid, COUNT(*) AS rows, SUM(market_value_usd) AS aum
          FROM fund_holdings_v2 WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
          GROUP BY dm_rollup_entity_id
        )
        SELECT fr.eid, e.canonical_name, e.entity_type, tc.last_valid_to,
               fr.rows, fr.aum
        FROM fund_rollups fr
        JOIN truly_closed tc ON tc.entity_id = fr.eid
        LEFT JOIN entities e ON e.entity_id = fr.eid
        ORDER BY fr.aum DESC NULLS LAST
    """).fetchall()

    out["1_5_3_deprecated_rollups"] = {
        "n": len(deprecated),
        "rows_total": sum(r[4] or 0 for r in deprecated),
        "aum_total": sum(r[5] or 0 for r in deprecated),
        "samples": deprecated[:20],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, default=str, indent=2)
    print(f"WROTE {OUT}")
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk not in ('samples','top25')})
                      for k, v in out.items()}, default=str, indent=2)[:3000])


if __name__ == "__main__":
    main()
