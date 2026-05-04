"""CP-5 Bundle B — Phase 3: identifier completeness + cross-period CIK + Adams cohort.

  3.1 Per-tier identifier coverage (CIK / CRD / LEI / FIGI / series_id)
  3.2 Cross-period CIK reconciliation (same series_id with different cik;
      same canonical-name but different CIKs)
  3.3 Adams duplicate cohort (Bundle A 120-row residual)

Outputs:
  data/working/cp-5-bundle-b-identifier-coverage.csv
  data/working/cp-5-bundle-b-cross-period-cik.csv
  data/working/cp-5-bundle-b-adams-cohort.csv

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
    connect,
)


def phase_3_1_coverage(con) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("Phase 3.1 — per-tier identifier coverage")
    print("=" * 80)

    # Build tier classification matching Phase 1.2
    tier_sql = f"""
    WITH ent AS (
      SELECT entity_id, entity_type, display_name FROM entity_current
    ),
    h13f_rc AS (
      SELECT entity_id, COUNT(*) AS h13f_rows
      FROM holdings_v2 WHERE is_latest GROUP BY 1
    ),
    brand AS (
      SELECT DISTINCT entity_id FROM entity_aliases
      WHERE alias_type='brand' AND valid_to={SENTINEL}
    ),
    has_parent AS (
      SELECT DISTINCT er.child_entity_id AS entity_id
      FROM entity_relationships er
      JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
      WHERE er.valid_to = {SENTINEL}
        AND er.control_type IN ('control','mutual','merge')
        AND pec.entity_type='institution'
    ),
    has_children AS (
      SELECT DISTINCT er.parent_entity_id AS entity_id
      FROM entity_relationships er
      JOIN entity_current cec ON cec.entity_id = er.child_entity_id
      WHERE er.valid_to = {SENTINEL}
        AND er.control_type IN ('control','mutual','merge')
        AND cec.entity_type='institution'
    )
    SELECT
      ent.entity_id,
      ent.entity_type,
      CASE
        WHEN ent.entity_type='fund' THEN 'T7_fund'
        WHEN ent.entity_type<>'institution' THEN 'other_'||ent.entity_type
        WHEN ent.entity_id IN (SELECT entity_id FROM has_parent) AND ent.entity_id IN (SELECT entity_id FROM has_children) THEN 'T2_mid'
        WHEN ent.entity_id NOT IN (SELECT entity_id FROM has_parent) THEN
          CASE
            WHEN COALESCE(h.h13f_rows,0) >= 100 THEN 'T1+T3_top_active'
            WHEN COALESCE(h.h13f_rows,0) > 0 THEN 'T1_top_low_filer'
            WHEN ent.entity_id IN (SELECT entity_id FROM brand) THEN 'T1+T5_top_brand'
            ELSE 'T1_top_quiet'
          END
        ELSE
          CASE
            WHEN COALESCE(h.h13f_rows,0) >= 100 THEN 'T3_active_subsidiary'
            WHEN COALESCE(h.h13f_rows,0) > 0 THEN 'subsidiary_low_filer'
            WHEN ent.entity_id IN (SELECT entity_id FROM brand) THEN 'T5_brand_subsidiary'
            ELSE 'T4_op_AM_or_quiet_sub'
          END
      END AS tier
    FROM ent
    LEFT JOIN h13f_rc h ON h.entity_id = ent.entity_id
    """
    tier_df = con.execute(tier_sql).fetchdf()
    print(f"  Tier-classified entities: {len(tier_df):,}")

    ids_df = con.execute(f"""
      SELECT entity_id,
             MAX(CASE WHEN identifier_type='cik' THEN 1 ELSE 0 END) AS has_cik,
             MAX(CASE WHEN identifier_type='crd' THEN 1 ELSE 0 END) AS has_crd,
             MAX(CASE WHEN identifier_type='lei' THEN 1 ELSE 0 END) AS has_lei,
             MAX(CASE WHEN identifier_type='figi' THEN 1 ELSE 0 END) AS has_figi,
             MAX(CASE WHEN identifier_type='series_id' THEN 1 ELSE 0 END) AS has_series_id
      FROM entity_identifiers
      WHERE valid_to = {SENTINEL}
      GROUP BY 1
    """).fetchdf()

    df = tier_df.merge(ids_df, on="entity_id", how="left").fillna(0)
    for c in ["has_cik", "has_crd", "has_lei", "has_figi", "has_series_id"]:
        df[c] = df[c].astype(int)

    summary = (
        df.groupby("tier")
        .agg(
            n=("entity_id", "size"),
            cik_pct=("has_cik", lambda s: round(100.0 * s.mean(), 1)),
            crd_pct=("has_crd", lambda s: round(100.0 * s.mean(), 1)),
            lei_pct=("has_lei", lambda s: round(100.0 * s.mean(), 1)),
            figi_pct=("has_figi", lambda s: round(100.0 * s.mean(), 1)),
            series_pct=("has_series_id", lambda s: round(100.0 * s.mean(), 1)),
        )
        .reset_index()
        .sort_values("n", ascending=False)
    )
    print("\n  Identifier coverage by tier:")
    print(summary.to_string(index=False))
    summary.to_csv(WORKDIR / "cp-5-bundle-b-identifier-coverage.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-b-identifier-coverage.csv'}")
    return summary


def phase_3_2_cross_period_cik(con) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("Phase 3.2 — cross-period CIK reconciliation")
    print("=" * 80)

    # 3.2a — same series_id with different fund_cik across quarters
    series_drift = con.execute("""
        WITH x AS (
          SELECT series_id, fund_cik
          FROM fund_holdings_v2
          WHERE is_latest AND series_id IS NOT NULL AND series_id <> ''
            AND series_id NOT LIKE 'SYN_%'
            AND series_id <> 'UNKNOWN'
          GROUP BY 1, 2
        )
        SELECT series_id, COUNT(*) AS n_distinct_ciks
        FROM x
        GROUP BY 1
        HAVING n_distinct_ciks > 1
        ORDER BY 2 DESC
    """).fetchdf()
    print(f"  Series with >1 distinct fund_cik across quarters: {len(series_drift):,}")
    if len(series_drift):
        print(series_drift.head(20).to_string(index=False))

    # 3.2b — same canonical_name (display_name normalized) but different CIKs.
    # Use a simple uppercase strip-non-alnum normalization.
    name_dup = con.execute(f"""
        WITH norm AS (
          SELECT ec.entity_id, ec.display_name,
                 REGEXP_REPLACE(UPPER(ec.display_name), '[^A-Z0-9]', '', 'g') AS norm_name,
                 ei.identifier_value AS cik
          FROM entity_current ec
          LEFT JOIN entity_identifiers ei
            ON ei.entity_id = ec.entity_id
           AND ei.identifier_type='cik'
           AND ei.valid_to = {SENTINEL}
          WHERE ec.entity_type='institution'
        )
        SELECT norm_name,
               COUNT(DISTINCT entity_id) AS n_eids,
               COUNT(DISTINCT cik) AS n_ciks,
               STRING_AGG(DISTINCT entity_id::VARCHAR, ',') AS eids,
               STRING_AGG(DISTINCT cik, ',') AS ciks,
               ANY_VALUE(display_name) AS sample_name
        FROM norm
        WHERE norm_name <> ''
        GROUP BY 1
        HAVING n_eids > 1 AND n_ciks >= 2
        ORDER BY n_eids DESC, n_ciks DESC
        LIMIT 200
    """).fetchdf()
    print(f"\n  Same-name-different-CIK entity pairs (institutions): {len(name_dup):,}")
    if len(name_dup):
        print("  Top 20 by n_eids:")
        print(name_dup.head(20).to_string(index=False, max_colwidth=40))

    name_dup.to_csv(WORKDIR / "cp-5-bundle-b-cross-period-cik.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-b-cross-period-cik.csv'}")
    return name_dup


def phase_3_3_adams(con) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("Phase 3.3 — Adams duplicate cohort")
    print("=" * 80)

    rows = con.execute(f"""
        SELECT
          ec.entity_id, ec.entity_type, ec.display_name,
          (SELECT identifier_value FROM entity_identifiers ei
           WHERE ei.entity_id=ec.entity_id AND ei.identifier_type='cik'
             AND ei.valid_to={SENTINEL} LIMIT 1) AS cik,
          (SELECT identifier_value FROM entity_identifiers ei
           WHERE ei.entity_id=ec.entity_id AND ei.identifier_type='series_id'
             AND ei.valid_to={SENTINEL} LIMIT 1) AS series_id,
          (SELECT COUNT(*) FROM entity_aliases ea
           WHERE ea.entity_id=ec.entity_id AND ea.valid_to={SENTINEL}) AS n_aliases,
          (SELECT COUNT(*) FROM entity_relationships er
           WHERE (er.parent_entity_id=ec.entity_id OR er.child_entity_id=ec.entity_id)
             AND er.valid_to={SENTINEL}) AS n_relationships
        FROM entity_current ec
        WHERE UPPER(ec.display_name) LIKE 'ADAMS%'
        ORDER BY ec.display_name, ec.entity_id
    """).fetchdf()
    print(f"  Adams entities: {len(rows):,}")
    print(rows.to_string(index=False, max_colwidth=60))

    # Group by display_name to identify duplicate runs
    dup = (
        rows.groupby("display_name")
        .agg(n=("entity_id", "size"))
        .reset_index()
        .sort_values("n", ascending=False)
    )
    print("\n  Duplicate display_name groups:")
    print(dup[dup["n"] > 1].to_string(index=False))

    # Also surface fund_holdings_v2 footprint per Adams entity
    eids = ",".join(str(int(e)) for e in rows["entity_id"])
    if eids:
        fh = con.execute(f"""
            SELECT entity_id, COUNT(*) AS n_rows,
                   SUM(market_value_usd)/1e9 AS aum_b,
                   COUNT(DISTINCT quarter) AS n_quarters
            FROM fund_holdings_v2
            WHERE is_latest AND entity_id IN ({eids})
            GROUP BY 1
        """).fetchdf()
        rows = rows.merge(fh, on="entity_id", how="left").fillna(
            {"n_rows": 0, "aum_b": 0, "n_quarters": 0}
        )
        print("\n  Adams entities with fund_holdings_v2 footprint:")
        print(rows[rows["n_rows"] > 0].to_string(index=False, max_colwidth=60))

    rows.to_csv(WORKDIR / "cp-5-bundle-b-adams-cohort.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-b-adams-cohort.csv'}")
    return rows


def main() -> int:
    con = connect()
    WORKDIR.mkdir(parents=True, exist_ok=True)
    phase_3_1_coverage(con)
    phase_3_2_cross_period_cik(con)
    phase_3_3_adams(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
