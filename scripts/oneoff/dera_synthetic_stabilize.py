#!/usr/bin/env python3
"""dera_synthetic_stabilize.py — Phase 1 + Phase 2 DERA synthetic resolution.

Phase 1 (Tier 1, 1 registrant): swap synthetic series_id
  '2060415_0002071691-26-007379' -> 'S000093420' (real S-number that already
  exists in the same fund's prior-quarter row). Pure key rename, no row
  count change, no entity backfill.

Phase 2 (Tier 3, 55 registrants): collapse per-quarter '{cik}_{accession}'
  synthetic keys to a stable 'SYN_{cik_padded}' for the 55 entity-mapped
  single-fund stand-alone registrants (ETFs, BDCs, interval funds, CEFs).
  Per CIK:
    - rekey fund_holdings_v2 rows
    - replace per-quarter fund_universe synthetic rows with one canonical
      SYN_{cik_padded} row (carrying the most-recent attributes)
    - backfill entity_id, rollup_entity_id, dm_entity_id,
      dm_rollup_entity_id, dm_rollup_name from entity_identifiers +
      entity_rollup_history (SCD open at 9999-12-31).

Default is --dry-run. Pass --confirm to write.

Reference: docs/findings/dera-synthetic-resolution-scoping.md
"""
from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

SOURCE_TAG = "dera_synthetic_stabilize"

# Pinned Tier 1 case (only one in fund_holdings_v2 as of 2026-04-28).
TIER1_SYNTH = "2060415_0002071691-26-007379"
TIER1_REAL = "S000093420"
TIER1_FUND_CIK = "0002060415"

# entity_rollup_history open-row sentinel.
SCD_OPEN = "9999-12-31"

EXPECTED_TIER3_CIKS = 55


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------
def phase1_report(con) -> dict:
    synth = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE is_latest AND series_id = ?", [TIER1_SYNTH]
    ).fetchone()[0]
    real = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE is_latest AND series_id = ?", [TIER1_REAL]
    ).fetchone()[0]
    fu_synth = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE series_id = ?",
        [TIER1_SYNTH],
    ).fetchone()[0]
    fu_real = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE series_id = ?",
        [TIER1_REAL],
    ).fetchone()[0]
    print("PHASE 1 (Tier 1) state:")
    print(f"  fund_holdings_v2 synthetic={synth} real={real}")
    print(f"  fund_universe   synthetic={fu_synth} real={fu_real}")
    if synth == 0:
        print("  -> nothing to do (synthetic key already absent).")
    return {
        "synth_holdings": synth, "real_holdings": real,
        "synth_fu": fu_synth, "real_fu": fu_real,
    }


def phase1_apply(con) -> None:
    pre = phase1_report(con)
    if pre["synth_holdings"] == 0:
        return

    # Sanity guard: every synthetic row must match the pinned fund_cik.
    bad_cik = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE series_id = ? AND fund_cik <> ?",
        [TIER1_SYNTH, TIER1_FUND_CIK],
    ).fetchone()[0]
    if bad_cik:
        raise RuntimeError(
            f"Tier1 abort: {bad_cik} synthetic rows do not match "
            f"fund_cik {TIER1_FUND_CIK}"
        )
    if pre["real_holdings"] == 0:
        raise RuntimeError(
            f"Tier1 abort: real key {TIER1_REAL} not present in fund_holdings_v2"
        )

    con.execute("BEGIN")
    try:
        con.execute(
            "UPDATE fund_holdings_v2 SET series_id = ? WHERE series_id = ?",
            [TIER1_REAL, TIER1_SYNTH],
        )
        if pre["synth_fu"]:
            con.execute(
                "DELETE FROM fund_universe WHERE series_id = ?", [TIER1_SYNTH]
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    post_synth = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE series_id = ?",
        [TIER1_SYNTH],
    ).fetchone()[0]
    if post_synth:
        raise RuntimeError(f"Tier1 verify: {post_synth} synthetic rows remain")
    print(
        f"PHASE 1: swapped {pre['synth_holdings']} rows "
        f"{TIER1_SYNTH} -> {TIER1_REAL}; "
        f"{pre['synth_fu']} fund_universe synthetic row(s) deleted."
    )


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------
TIER3_CIKS_SQL = r"""
WITH synth_holdings AS (
    SELECT DISTINCT
        SPLIT_PART(series_id, '_', 1) AS raw_cik,
        LPAD(SPLIT_PART(series_id, '_', 1), 10, '0') AS cik_padded
    FROM fund_holdings_v2
    WHERE is_latest
      AND series_id NOT LIKE 'S%'
      AND series_id NOT LIKE 'SYN_%'
      AND series_id <> 'UNKNOWN'
      AND series_id LIKE '%\_%' ESCAPE '\'
),
has_real_in_fu AS (
    SELECT DISTINCT fund_cik FROM fund_universe WHERE series_id LIKE 'S%'
),
entity_ciks AS (
    SELECT DISTINCT identifier_value AS cik_padded, entity_id
    FROM entity_identifiers
    WHERE identifier_type = 'cik'
)
SELECT s.raw_cik, s.cik_padded, e.entity_id
FROM synth_holdings s
JOIN entity_ciks e ON e.cik_padded = s.cik_padded
LEFT JOIN has_real_in_fu fu ON fu.fund_cik = s.cik_padded
WHERE fu.fund_cik IS NULL
ORDER BY s.cik_padded
"""


def load_tier3_candidates(con) -> list[tuple]:
    rows = con.execute(TIER3_CIKS_SQL).fetchall()
    if len(rows) != EXPECTED_TIER3_CIKS:
        raise RuntimeError(
            f"Tier3 candidate count mismatch: got {len(rows)}, "
            f"expected {EXPECTED_TIER3_CIKS}. Investigate before applying."
        )
    return rows


def phase2_report(con) -> dict:
    cands = load_tier3_candidates(con)
    raw_ciks = [r[0] for r in cands]
    padded = [r[1] for r in cands]

    placeholders = ",".join(["?"] * len(raw_ciks))
    n_rows, n_series, nav_b = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT series_id), "
        f"COALESCE(SUM(market_value_usd),0)/1e9 "
        f"FROM fund_holdings_v2 "
        f"WHERE is_latest AND series_id NOT LIKE 'S%' "
        f"  AND series_id NOT LIKE 'SYN_%' "
        f"  AND SPLIT_PART(series_id, '_', 1) IN ({placeholders})",
        raw_ciks,
    ).fetchone()

    fu_count = con.execute(
        f"SELECT COUNT(*) FROM fund_universe "
        f"WHERE fund_cik IN ({','.join(['?'] * len(padded))})",
        padded,
    ).fetchone()[0]

    print("PHASE 2 (Tier 3) state:")
    print(f"  candidate CIKs: {len(cands)} (expect {EXPECTED_TIER3_CIKS})")
    print(
        f"  synthetic rows: {n_rows:,}  distinct series: {n_series}  "
        f"nav_b: {nav_b:.1f}"
    )
    print(f"  fund_universe rows for these CIKs: {fu_count}")
    return {
        "candidates": cands, "rows": n_rows, "series": n_series,
        "nav_b": nav_b, "fu_count": fu_count,
    }


def _lookup_rollup(con, entity_id: int, rollup_type: str):
    row = con.execute(
        "SELECT rollup_entity_id FROM entity_rollup_history "
        "WHERE entity_id = ? AND rollup_type = ? "
        "  AND valid_to = DATE '" + SCD_OPEN + "' "
        "ORDER BY valid_from DESC LIMIT 1",
        [entity_id, rollup_type],
    ).fetchone()
    return row[0] if row else None


def _canonical_name(con, entity_id: int):
    if entity_id is None:
        return None
    row = con.execute(
        "SELECT canonical_name FROM entities WHERE entity_id = ?",
        [entity_id],
    ).fetchone()
    return row[0] if row else None


def _canon_from_fund_universe(con, cik_padded: str):
    """Pull a canonical fund_universe row (most-recent last_updated) keyed by
    fund_cik. fund_universe.fund_cik is always 10-padded; series_id prefixes
    are inconsistently padded so we match on fund_cik."""
    return con.execute(
        "SELECT fund_cik, fund_name, family_name, total_net_assets, "
        "  fund_category, is_actively_managed, total_holdings_count, "
        "  equity_pct, top10_concentration, last_updated, "
        "  fund_strategy, best_index, strategy_narrative, "
        "  strategy_source, strategy_fetched_at "
        "FROM fund_universe WHERE fund_cik = ? "
        "ORDER BY last_updated DESC NULLS LAST LIMIT 1",
        [cik_padded],
    ).fetchone()


def _canon_from_holdings(con, raw_cik: str, _cik_padded: str):
    """Synthesize a canonical row from fund_holdings_v2 when fund_universe is
    empty for this CIK. Picks the most-recent (fund_cik, fund_name, family_name)
    triple by report_month."""
    row = con.execute(
        "SELECT fund_cik, fund_name, family_name "
        "FROM fund_holdings_v2 "
        "WHERE is_latest "
        "  AND SPLIT_PART(series_id, '_', 1) = ? "
        "  AND series_id NOT LIKE 'S%' "
        "  AND series_id NOT LIKE 'SYN_%' "
        "ORDER BY report_month DESC LIMIT 1",
        [raw_cik],
    ).fetchone()
    if row is None:
        return None
    fc, fn, fam = row
    # fund_universe.fund_cik is always padded; fund_holdings_v2.fund_cik is
    # already padded too (verified at script time), but coerce defensively.
    if fc and len(fc) < 10:
        fc = fc.zfill(10)
    return (fc, fn, fam, None, None, None, None, None, None, None,
            None, None, None, None, None)


def phase2_apply(con) -> None:
    cands = load_tier3_candidates(con)
    print(f"PHASE 2: applying to {len(cands)} CIKs")

    rekeyed = 0
    fu_inserted = 0
    fu_deleted = 0
    holdings_backfilled = 0
    canon_from_fu = 0
    canon_from_holdings = 0

    for raw_cik, cik_padded, entity_id in cands:
        new_series = f"SYN_{cik_padded}"

        ec_rollup = _lookup_rollup(con, entity_id, "economic_control_v1")
        dm_rollup = _lookup_rollup(con, entity_id, "decision_maker_v1")
        dm_name = _canonical_name(con, dm_rollup) if dm_rollup else None

        con.execute("BEGIN")
        try:
            canon = _canon_from_fund_universe(con, cik_padded)
            if canon is None:
                canon = _canon_from_holdings(con, raw_cik, cik_padded)
                canon_from_holdings += 1
            else:
                canon_from_fu += 1

            # 1. Rekey holdings. Pre-count the predicate then run UPDATE; the
            #    count is the rowcount (DuckDB has no SELECT changes()).
            rk = con.execute(
                "SELECT COUNT(*) FROM fund_holdings_v2 "
                "WHERE SPLIT_PART(series_id, '_', 1) = ? "
                "  AND series_id NOT LIKE 'S%' "
                "  AND series_id NOT LIKE 'SYN_%'",
                [raw_cik],
            ).fetchone()[0]
            con.execute(
                "UPDATE fund_holdings_v2 SET series_id = ? "
                "WHERE SPLIT_PART(series_id, '_', 1) = ? "
                "  AND series_id NOT LIKE 'S%' "
                "  AND series_id NOT LIKE 'SYN_%'",
                [new_series, raw_cik],
            )
            rekeyed += rk

            # 2. Drop old fund_universe rows for this CIK. Match by fund_cik
            #    (padded) — series_id prefixes are inconsistently padded so
            #    a series_id-prefix match would miss some. By construction
            #    these CIKs have NO real S% row in fund_universe.
            fud = con.execute(
                "SELECT COUNT(*) FROM fund_universe WHERE fund_cik = ?",
                [cik_padded],
            ).fetchone()[0]
            con.execute(
                "DELETE FROM fund_universe WHERE fund_cik = ?",
                [cik_padded],
            )
            fu_deleted += fud

            # 3. Insert canonical fund_universe row keyed by SYN_{cik}.
            if canon is not None:
                con.execute(
                    "INSERT INTO fund_universe ("
                    "  fund_cik, fund_name, series_id, family_name, "
                    "  total_net_assets, fund_category, is_actively_managed, "
                    "  total_holdings_count, equity_pct, top10_concentration, "
                    "  last_updated, fund_strategy, best_index, "
                    "  strategy_narrative, strategy_source, strategy_fetched_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (series_id) DO UPDATE SET "
                    "  fund_cik=EXCLUDED.fund_cik, "
                    "  fund_name=EXCLUDED.fund_name, "
                    "  family_name=EXCLUDED.family_name, "
                    "  total_net_assets=EXCLUDED.total_net_assets, "
                    "  last_updated=EXCLUDED.last_updated",
                    [
                        canon[0], canon[1], new_series, canon[2],
                        canon[3], canon[4], canon[5], canon[6],
                        canon[7], canon[8], canon[9], canon[10],
                        canon[11], canon[12], canon[13], canon[14],
                    ],
                )
                fu_inserted += 1

            # 4. Backfill entity columns on rekeyed rows.
            bf = con.execute(
                "SELECT COUNT(*) FROM fund_holdings_v2 WHERE series_id = ?",
                [new_series],
            ).fetchone()[0]
            con.execute(
                "UPDATE fund_holdings_v2 SET "
                "  entity_id = ?, "
                "  rollup_entity_id = ?, "
                "  dm_entity_id = ?, "
                "  dm_rollup_entity_id = ?, "
                "  dm_rollup_name = ? "
                "WHERE series_id = ?",
                [entity_id, ec_rollup, entity_id, dm_rollup, dm_name, new_series],
            )
            holdings_backfilled += bf

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    print(
        f"PHASE 2: rekeyed {rekeyed:,} holdings rows; "
        f"fund_universe -{fu_deleted} +{fu_inserted} "
        f"(canon_from_fu={canon_from_fu}, canon_from_holdings={canon_from_holdings}); "
        f"backfilled {holdings_backfilled:,} entity/rollup cells"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=["1", "2", "all"], required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--confirm", action="store_true")
    p.add_argument("--prod-db", default=db.PROD_DB)
    args = p.parse_args()

    apply = bool(args.confirm)

    import duckdb  # noqa: WPS433
    con = duckdb.connect(args.prod_db, read_only=not apply)
    try:
        print(f"DB: {args.prod_db}  mode: {'APPLY' if apply else 'DRY-RUN'}")
        if args.phase in ("1", "all"):
            print("--- PHASE 1 (Tier 1) ---")
            if apply:
                phase1_apply(con)
            else:
                phase1_report(con)
        if args.phase in ("2", "all"):
            print("--- PHASE 2 (Tier 3) ---")
            if apply:
                phase2_apply(con)
            else:
                phase2_report(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
