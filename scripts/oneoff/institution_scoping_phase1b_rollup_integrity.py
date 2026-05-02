"""
Phase 1B — Fund-to-institution rollup completeness.

Read-only audit of fund_holdings_v2 (is_latest=TRUE) rollup integrity.
Sub-tasks:
  1B.1 Orphan funds (dm_rollup_entity_id NULL, or pointing to nonexistent entity row)
  1B.2 Dangling rollup (rolls up to N/A-named entity 11278 or any suspicious-name entity)
  1B.3 Wrong-shelf rollup (rollup canonical_name does not match fund_cik manager_name)
  1B.4 Headline integrity number (union, deduped at row_id level)
"""
import duckdb
import json
import re
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "13f.duckdb"
OUT = Path(__file__).resolve().parents[2] / "docs" / "findings" / "_phase1b_raw.json"


def jaccard_words(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ta = set(re.findall(r"[a-z0-9]+", a.lower()))
    tb = set(re.findall(r"[a-z0-9]+", b.lower()))
    # Strip common stopwords / corporate suffixes
    stopwords = {"the", "of", "and", "fund", "funds", "trust", "co", "corp", "corporation",
                 "inc", "incorporated", "ltd", "llc", "lp", "lllp", "company", "group",
                 "holdings", "advisors", "advisers", "management", "capital", "investments",
                 "investment", "partners", "asset", "assets"}
    ta -= stopwords
    tb -= stopwords
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def main():
    con = duckdb.connect(str(DB), read_only=True)

    out = {}

    # Universe baseline
    universe = con.execute("""
        SELECT COUNT(*) AS rows, SUM(market_value_usd) AS aum
        FROM fund_holdings_v2 WHERE is_latest=TRUE
    """).fetchone()
    out["universe"] = {"rows": universe[0], "aum": universe[1]}

    # ---------- 1B.1 ORPHAN FUNDS ----------
    # 1B.1a: dm_rollup_entity_id NULL
    null_rollup = con.execute("""
        SELECT COUNT(*) AS rows, SUM(market_value_usd) AS aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id IS NULL
    """).fetchone()
    null_rollup_samples = con.execute("""
        SELECT DISTINCT fund_cik, fund_name, series_id
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id IS NULL
        ORDER BY fund_cik
        LIMIT 10
    """).fetchall()

    # 1B.1b: dm_rollup_entity_id NOT NULL but no entity row
    no_entity = con.execute("""
        SELECT COUNT(*) AS rows, SUM(f.market_value_usd) AS aum
        FROM fund_holdings_v2 f
        LEFT JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest=TRUE AND f.dm_rollup_entity_id IS NOT NULL AND e.entity_id IS NULL
    """).fetchone()
    no_entity_samples = con.execute("""
        SELECT DISTINCT f.fund_cik, f.fund_name, f.series_id, f.dm_rollup_entity_id
        FROM fund_holdings_v2 f
        LEFT JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest=TRUE AND f.dm_rollup_entity_id IS NOT NULL AND e.entity_id IS NULL
        ORDER BY f.fund_cik
        LIMIT 10
    """).fetchall()

    out["1b1_orphan"] = {
        "null_rollup": {"rows": null_rollup[0], "aum": null_rollup[1], "samples": null_rollup_samples},
        "no_entity_row": {"rows": no_entity[0], "aum": no_entity[1], "samples": no_entity_samples},
    }

    # ---------- 1B.2 DANGLING ROLLUP ----------
    # Rolled-to entity exists but is N/A-named or suspicious entity_type
    dangling_by_name = con.execute("""
        SELECT COUNT(*) AS rows, SUM(f.market_value_usd) AS aum,
               COUNT(DISTINCT f.dm_rollup_entity_id) AS n_distinct_entities
        FROM fund_holdings_v2 f
        JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest=TRUE
          AND (UPPER(TRIM(COALESCE(e.canonical_name,''))) IN ('N/A','NA','UNKNOWN','NONE','NULL','')
               OR e.canonical_name IS NULL)
    """).fetchone()

    # Rolls up to entity_id=11278 specifically (Calamos N/A shape)
    e11278 = con.execute("""
        SELECT COUNT(*) AS rows, SUM(f.market_value_usd) AS aum
        FROM fund_holdings_v2 f
        WHERE f.is_latest=TRUE AND f.dm_rollup_entity_id=11278
    """).fetchone()

    # Per-entity-type breakdown of rollup targets (rolled to a fund entity, not an institution)
    rolled_to_fund = con.execute("""
        SELECT COUNT(*) AS rows, SUM(f.market_value_usd) AS aum,
               COUNT(DISTINCT f.dm_rollup_entity_id) AS n_distinct_entities
        FROM fund_holdings_v2 f
        JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest=TRUE AND e.entity_type='fund'
    """).fetchone()
    rolled_to_fund_samples = con.execute("""
        SELECT f.dm_rollup_entity_id, e.canonical_name, e.entity_type,
               COUNT(*) AS rows, SUM(f.market_value_usd) AS aum
        FROM fund_holdings_v2 f
        JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest=TRUE AND e.entity_type='fund'
        GROUP BY f.dm_rollup_entity_id, e.canonical_name, e.entity_type
        ORDER BY aum DESC NULLS LAST
        LIMIT 15
    """).fetchall()

    # Suspicious entity_type (not 'institution')
    bad_type = con.execute("""
        SELECT e.entity_type, COUNT(*) AS rows, SUM(f.market_value_usd) AS aum,
               COUNT(DISTINCT f.dm_rollup_entity_id) AS n_distinct_entities
        FROM fund_holdings_v2 f
        LEFT JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        WHERE f.is_latest=TRUE AND f.dm_rollup_entity_id IS NOT NULL
          AND (e.entity_type IS NULL OR e.entity_type IN ('mixed','unknown','N/A','fund'))
        GROUP BY e.entity_type
        ORDER BY rows DESC
    """).fetchall()

    out["1b2_dangling"] = {
        "by_suspicious_name": {"rows": dangling_by_name[0], "aum": dangling_by_name[1],
                                "n_entities": dangling_by_name[2]},
        "entity_id_11278_residual": {"rows": e11278[0], "aum": e11278[1]},
        "rolled_to_fund_entity_type": {
            "rows": rolled_to_fund[0], "aum": rolled_to_fund[1],
            "n_entities": rolled_to_fund[2], "samples": rolled_to_fund_samples,
        },
        "by_entity_type": bad_type,
    }

    # ---------- 1B.3 WRONG-SHELF ROLLUP ----------
    # Compare entity canonical_name at dm_rollup_entity_id vs the fund's family_name
    # from fund_universe (preferred) and fund_name + family_name fields in fund_holdings_v2.
    # managers.cik does NOT match fund_cik (fund CIKs are mutual-fund issuer CIKs;
    # managers.cik = 13F-filer CIKs), so we use fund_universe / fhv2 family_name instead.
    pairs = con.execute("""
        SELECT f.fund_cik, f.dm_rollup_entity_id, e.canonical_name AS rollup_name,
               f.family_name, fu.family_name AS fu_family_name, fu.fund_name AS fu_fund_name,
               COUNT(*) AS rows, SUM(f.market_value_usd) AS aum
        FROM fund_holdings_v2 f
        JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
        LEFT JOIN fund_universe fu
               ON fu.fund_cik = f.fund_cik AND fu.series_id = f.series_id
        WHERE f.is_latest=TRUE
          AND f.dm_rollup_entity_id IS NOT NULL
          AND e.canonical_name IS NOT NULL
        GROUP BY f.fund_cik, f.dm_rollup_entity_id, e.canonical_name,
                 f.family_name, fu.family_name, fu.fund_name
    """).fetchall()

    wrong_shelf = []
    rows_total = 0
    aum_total = 0.0
    no_ref_rows = 0
    no_ref_aum = 0.0
    for fund_cik, drid, rollup_name, fhv_fam, fu_fam, fu_name, n_rows, aum in pairs:
        candidates = [c for c in (fu_fam, fhv_fam, fu_name) if c]
        if not candidates:
            no_ref_rows += n_rows
            no_ref_aum += aum or 0.0
            continue
        best = max(jaccard_words(rollup_name, c) for c in candidates)
        if best < 0.25:
            rows_total += n_rows
            aum_total += aum or 0.0
            wrong_shelf.append({
                "fund_cik": fund_cik,
                "dm_rollup_entity_id": drid,
                "rollup_name": rollup_name,
                "fu_family_name": fu_fam,
                "fhv_family_name": fhv_fam,
                "fu_fund_name": fu_name,
                "rows": n_rows,
                "aum": aum,
                "jaccard": round(best, 3),
            })
    wrong_shelf.sort(key=lambda x: -(x["aum"] or 0))

    out["1b3_wrong_shelf"] = {
        "rows": rows_total,
        "aum": aum_total,
        "n_pairs": len(wrong_shelf),
        "no_reference_row": {"rows": no_ref_rows, "aum": no_ref_aum},
        "samples": wrong_shelf[:15],
    }

    # ---------- 1B.4 UNION (HEADLINE) ----------
    # Build unique set of fund-row identifiers across all three failure modes.
    # 1B.1 + 1B.2 + part of 1B.3.
    # We re-run a single SQL union by row_id.
    headline = con.execute("""
        WITH bad AS (
          -- 1B.1 NULL rollup
          SELECT row_id, market_value_usd FROM fund_holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NULL
          UNION
          -- 1B.1 no entity row
          SELECT f.row_id, f.market_value_usd
          FROM fund_holdings_v2 f
          LEFT JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
          WHERE f.is_latest=TRUE AND f.dm_rollup_entity_id IS NOT NULL AND e.entity_id IS NULL
          UNION
          -- 1B.2 N/A-named rollup target
          SELECT f.row_id, f.market_value_usd
          FROM fund_holdings_v2 f
          JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
          WHERE f.is_latest=TRUE
            AND (UPPER(TRIM(COALESCE(e.canonical_name,''))) IN ('N/A','NA','UNKNOWN','NONE','NULL','')
                 OR e.canonical_name IS NULL)
          UNION
          -- 1B.2 entity_type=fund (rolled up to a fund, not an institution)
          SELECT f.row_id, f.market_value_usd
          FROM fund_holdings_v2 f
          JOIN entities e ON e.entity_id = f.dm_rollup_entity_id
          WHERE f.is_latest=TRUE AND e.entity_type='fund'
        )
        SELECT COUNT(*) AS rows, SUM(market_value_usd) AS aum FROM bad
    """).fetchone()

    # Add wrong-shelf rows from python pass (they may overlap with 1B.2 unions but
    # the row-level dedup happens via the SQL universe above; for 1B.3 we report it
    # separately and as additive to the headline.)
    out["1b4_headline"] = {
        "sql_union_rows": headline[0],
        "sql_union_aum": headline[1],
        "pct_universe_rows": round(100.0 * (headline[0] or 0) / max(universe[0], 1), 4),
        "pct_universe_aum": round(100.0 * (headline[1] or 0) / max(universe[1] or 1, 1), 4),
        "plus_wrong_shelf_rows": rows_total,
        "plus_wrong_shelf_aum": aum_total,
        "with_wrong_shelf_rows": (headline[0] or 0) + rows_total,  # may double-count; flagged
        "with_wrong_shelf_aum": (headline[1] or 0) + aum_total,
    }

    # Save
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, default=str, indent=2)
    print(f"WROTE {OUT}")
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != 'samples'})
                      for k, v in out.items()}, default=str, indent=2)[:4000])


if __name__ == "__main__":
    main()
