#!/usr/bin/env python3
"""dera_synthetic_stabilize.py — Phase 1 + 2 + 3 DERA synthetic resolution.

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

Phase 3 (Tier 4, 658 registrants): bootstrap entity rows for the 658
  registrant CIKs that don't yet exist in entity_identifiers, then apply
  the same SYN_{cik_padded} stable-key migration. Per CIK:
    - 657 CIKs: create new institution entity (entities,
      entity_identifiers cik, entity_aliases preferred, classification
      'unknown', entity_rollup_history × 2 self-rooted) — canonical_name
      sourced from fund_holdings_v2.fund_name (no managers/filings hits
      for this cohort). created_source='bootstrap_tier4'.
    - 1 CIK (Calamos 0001285650): attach CIK to existing fund eid 20206;
      close stale synth-series_id identifiers on 20206 + 20207
      (sibling-eid is logged as a follow-up entity-merge candidate).
    - Then rekey + fund_universe collapse + backfill (same as Phase 2).

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
EXPECTED_TIER4_CIKS = 658

# Tier 4 dedup gate (one true match — Calamos sibling-eid case).
# Both 20206 and 20207 represent CALAMOS GLOBAL TOTAL RETURN FUND with
# fund_cik=0001285650 (per-quarter synthetic series_ids). Attaching the
# CIK to 20206 collapses the holdings; 20207 is logged as a follow-up
# entity-merge candidate.
CALAMOS_CIK = "0001285650"
CALAMOS_REUSE_EID = 20206
CALAMOS_DUP_EID = 20207

TIER4_BOOTSTRAP_SOURCE = "bootstrap_tier4"


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
# Phase 3 (Tier 4) — bootstrap unmapped CIKs + stable-key migration
# ---------------------------------------------------------------------------
TIER4_CIKS_SQL = r"""
WITH synth_holdings AS (
    SELECT DISTINCT
        LPAD(SPLIT_PART(series_id, '_', 1), 10, '0') AS cik_padded
    FROM fund_holdings_v2
    WHERE is_latest
      AND series_id NOT LIKE 'S%'
      AND series_id NOT LIKE 'SYN_%'
      AND series_id <> 'UNKNOWN'
      AND series_id LIKE '%\_%' ESCAPE '\'
),
ec AS (
    SELECT DISTINCT identifier_value AS cik_padded
    FROM entity_identifiers
    WHERE identifier_type = 'cik'
),
unmapped AS (
    SELECT s.cik_padded
    FROM synth_holdings s
    LEFT JOIN ec ON ec.cik_padded = s.cik_padded
    WHERE ec.cik_padded IS NULL
),
named AS (
    SELECT u.cik_padded,
           ARG_MAX(h.fund_name, h.report_month)   AS fund_name,
           ARG_MAX(h.family_name, h.report_month) AS family_name
    FROM unmapped u
    JOIN fund_holdings_v2 h
      ON LPAD(SPLIT_PART(h.series_id, '_', 1), 10, '0') = u.cik_padded
     AND h.is_latest
     AND h.series_id NOT LIKE 'S%'
     AND h.series_id NOT LIKE 'SYN_%'
    GROUP BY u.cik_padded
)
SELECT cik_padded, fund_name, family_name
FROM named
ORDER BY cik_padded
"""


def load_tier4_candidates(con) -> list[tuple]:
    rows = con.execute(TIER4_CIKS_SQL).fetchall()
    if len(rows) != EXPECTED_TIER4_CIKS:
        raise RuntimeError(
            f"Tier4 candidate count mismatch: got {len(rows)}, "
            f"expected {EXPECTED_TIER4_CIKS}. Investigate before applying."
        )
    return rows


def phase3_report(con) -> dict:
    cands = load_tier4_candidates(con)
    cik_list = [c[0] for c in cands]

    placeholders = ",".join(["?"] * len(cik_list))
    n_rows, n_series, nav_b = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT series_id), "
        f"COALESCE(SUM(market_value_usd),0)/1e9 "
        f"FROM fund_holdings_v2 "
        f"WHERE is_latest "
        f"  AND series_id NOT LIKE 'S%' "
        f"  AND series_id NOT LIKE 'SYN_%' "
        f"  AND LPAD(SPLIT_PART(series_id,'_',1),10,'0') IN ({placeholders})",
        cik_list,
    ).fetchone()

    fu_count = con.execute(
        f"SELECT COUNT(*) FROM fund_universe "
        f"WHERE fund_cik IN ({placeholders})",
        cik_list,
    ).fetchone()[0]

    has_calamos = sum(1 for c in cands if c[0] == CALAMOS_CIK)
    print("PHASE 3 (Tier 4) state:")
    print(f"  candidate CIKs:          {len(cands)} (expect {EXPECTED_TIER4_CIKS})")
    print(f"    new bootstrap:         {len(cands) - has_calamos}")
    print(f"    reuse existing eid:    {has_calamos} (Calamos -> {CALAMOS_REUSE_EID})")
    print(
        f"  synthetic rows:          {n_rows:,}  "
        f"distinct series: {n_series:,}  nav_b: {nav_b:.1f}"
    )
    print(f"  fund_universe rows for these CIKs: {fu_count}")
    return {
        "candidates": cands, "rows": n_rows, "series": n_series,
        "nav_b": nav_b, "fu_count": fu_count,
    }


def _canon_from_holdings_padded(con, cik_padded: str):
    """Phase-3 variant of _canon_from_holdings.

    Matches by LPAD'd CIK prefix because Tier 4 includes 11 CIKs whose
    synthetic series_id appears with both padded and unpadded prefix
    variants (e.g. '1581005_…' and '0001581005_…')."""
    row = con.execute(
        "SELECT fund_cik, fund_name, family_name "
        "FROM fund_holdings_v2 "
        "WHERE is_latest "
        "  AND LPAD(SPLIT_PART(series_id, '_', 1), 10, '0') = ? "
        "  AND series_id NOT LIKE 'S%' "
        "  AND series_id NOT LIKE 'SYN_%' "
        "ORDER BY report_month DESC LIMIT 1",
        [cik_padded],
    ).fetchone()
    if row is None:
        return None
    fc, fn, fam = row
    if fc and len(fc) < 10:
        fc = fc.zfill(10)
    return (fc, fn, fam, None, None, None, None, None, None, None,
            None, None, None, None, None)


def _bootstrap_new_institution(con, cik_padded: str, fund_name: str) -> int:
    """Create a fresh institution entity with the standard SCD row set.

    Returns the new entity_id. Pattern mirrors
    bootstrap_residual_advisers._create_entity but inlined here because
    the Tier 4 cohort runs against prod (not staging) and the seed-list
    pattern doesn't fit 657 CIKs. classification='unknown' lets the
    classification pipeline assign on the next sweep."""
    eid = con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]

    con.execute(
        "INSERT INTO entities "
        "(entity_id, entity_type, canonical_name, created_source, is_inferred) "
        "VALUES (?, 'institution', ?, ?, FALSE)",
        [eid, fund_name, TIER4_BOOTSTRAP_SOURCE],
    )
    con.execute(
        "INSERT INTO entity_identifiers "
        "(entity_id, identifier_type, identifier_value, "
        " confidence, source, is_inferred, valid_from, valid_to) "
        "VALUES (?, 'cik', ?, 'exact', ?, FALSE, "
        "        DATE '2000-01-01', DATE '9999-12-31')",
        [eid, cik_padded, TIER4_BOOTSTRAP_SOURCE],
    )
    con.execute(
        "INSERT INTO entity_aliases "
        "(entity_id, alias_name, alias_type, is_preferred, "
        " preferred_key, source_table, is_inferred, "
        " valid_from, valid_to) "
        "VALUES (?, ?, 'brand', TRUE, ?, ?, FALSE, "
        "        DATE '2000-01-01', DATE '9999-12-31')",
        [eid, fund_name, eid, TIER4_BOOTSTRAP_SOURCE],
    )
    con.execute(
        "INSERT INTO entity_classification_history "
        "(entity_id, classification, is_activist, confidence, "
        " source, is_inferred, valid_from, valid_to) "
        "VALUES (?, 'unknown', FALSE, 'exact', ?, FALSE, "
        "        DATE '2000-01-01', DATE '9999-12-31')",
        [eid, TIER4_BOOTSTRAP_SOURCE],
    )
    for rollup_type in ("economic_control_v1", "decision_maker_v1"):
        con.execute(
            "INSERT INTO entity_rollup_history "
            "(entity_id, rollup_entity_id, rollup_type, rule_applied, "
            " confidence, valid_from, valid_to, computed_at, "
            " source, routing_confidence) "
            "VALUES (?, ?, ?, 'self', 'exact', "
            "        DATE '2000-01-01', DATE '9999-12-31', "
            "        CURRENT_TIMESTAMP, ?, 'high')",
            [eid, eid, rollup_type, TIER4_BOOTSTRAP_SOURCE],
        )
    return eid


def _attach_calamos(con) -> int:
    """Attach CIK 0001285650 to existing eid 20206 + close stale
    synth-series identifiers on both 20206 and 20207."""
    # Sanity: verify the reuse target still exists (don't assume).
    e = con.execute(
        "SELECT entity_type, canonical_name FROM entities WHERE entity_id = ?",
        [CALAMOS_REUSE_EID],
    ).fetchone()
    if e is None:
        raise RuntimeError(
            f"Calamos reuse target eid={CALAMOS_REUSE_EID} not found"
        )

    # Add the CIK identifier (only if not already there — re-run safety).
    already = con.execute(
        "SELECT 1 FROM entity_identifiers "
        "WHERE entity_id = ? AND identifier_type = 'cik' "
        "  AND identifier_value = ? "
        "  AND valid_to = DATE '9999-12-31'",
        [CALAMOS_REUSE_EID, CALAMOS_CIK],
    ).fetchone()
    if already is None:
        con.execute(
            "INSERT INTO entity_identifiers "
            "(entity_id, identifier_type, identifier_value, "
            " confidence, source, is_inferred, valid_from, valid_to) "
            "VALUES (?, 'cik', ?, 'exact', ?, FALSE, "
            "        DATE '2000-01-01', DATE '9999-12-31')",
            [CALAMOS_REUSE_EID, CALAMOS_CIK, TIER4_BOOTSTRAP_SOURCE],
        )

    # Close stale synth-series identifiers on 20206 + 20207. Both eids
    # carry one synth-series identifier each (per discovery); after the
    # rekey those identifiers point to keys that no longer exist.
    con.execute(
        "UPDATE entity_identifiers SET valid_to = CURRENT_DATE "
        "WHERE entity_id IN (?, ?) "
        "  AND identifier_type = 'series_id' "
        "  AND valid_to = DATE '9999-12-31' "
        "  AND identifier_value LIKE ?",
        [CALAMOS_REUSE_EID, CALAMOS_DUP_EID,
         CALAMOS_CIK.lstrip("0") + "_%"],
    )
    return CALAMOS_REUSE_EID


def phase3_apply(con) -> None:
    cands = load_tier4_candidates(con)
    print(f"PHASE 3: applying to {len(cands)} CIKs")

    bootstrap_count = 0
    reuse_count = 0
    rekeyed_total = 0
    fu_inserted = 0
    fu_deleted = 0
    holdings_backfilled_total = 0
    canon_from_fu = 0
    canon_from_holdings = 0

    for cik_padded, fund_name, family_name in cands:
        new_series = f"SYN_{cik_padded}"

        con.execute("BEGIN")
        try:
            # 1. Materialize the entity (bootstrap or attach).
            if cik_padded == CALAMOS_CIK:
                eid = _attach_calamos(con)
                reuse_count += 1
            else:
                eid = _bootstrap_new_institution(con, cik_padded, fund_name)
                bootstrap_count += 1

            ec_rollup = _lookup_rollup(con, eid, "economic_control_v1")
            dm_rollup = _lookup_rollup(con, eid, "decision_maker_v1")
            dm_name = _canonical_name(con, dm_rollup) if dm_rollup else None

            # 2. Pre-source canonical fund_universe row, then rekey.
            canon = _canon_from_fund_universe(con, cik_padded)
            if canon is None:
                canon = _canon_from_holdings_padded(con, cik_padded)
                canon_from_holdings += 1
            else:
                canon_from_fu += 1

            # 3. Rekey holdings — match on LPAD'd prefix to capture both
            #    padded and unpadded raw_cik variants (11 CIKs in cohort).
            rk = con.execute(
                "SELECT COUNT(*) FROM fund_holdings_v2 "
                "WHERE LPAD(SPLIT_PART(series_id, '_', 1), 10, '0') = ? "
                "  AND series_id NOT LIKE 'S%' "
                "  AND series_id NOT LIKE 'SYN_%'",
                [cik_padded],
            ).fetchone()[0]
            con.execute(
                "UPDATE fund_holdings_v2 SET series_id = ? "
                "WHERE LPAD(SPLIT_PART(series_id, '_', 1), 10, '0') = ? "
                "  AND series_id NOT LIKE 'S%' "
                "  AND series_id NOT LIKE 'SYN_%'",
                [new_series, cik_padded],
            )
            rekeyed_total += rk

            # 4. Drop old fund_universe rows for this CIK (always padded).
            fud = con.execute(
                "SELECT COUNT(*) FROM fund_universe WHERE fund_cik = ?",
                [cik_padded],
            ).fetchone()[0]
            con.execute(
                "DELETE FROM fund_universe WHERE fund_cik = ?",
                [cik_padded],
            )
            fu_deleted += fud

            # 5. Insert canonical fund_universe row keyed by SYN_{cik}.
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

            # 6. Backfill entity columns on rekeyed rows.
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
                [eid, ec_rollup, eid, dm_rollup, dm_name, new_series],
            )
            holdings_backfilled_total += bf

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    print(
        f"PHASE 3: bootstrapped {bootstrap_count} entities, "
        f"reused {reuse_count} (Calamos); "
        f"rekeyed {rekeyed_total:,} holdings rows; "
        f"fund_universe -{fu_deleted} +{fu_inserted} "
        f"(canon_from_fu={canon_from_fu}, "
        f"canon_from_holdings={canon_from_holdings}); "
        f"backfilled {holdings_backfilled_total:,} entity/rollup cells"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=["1", "2", "3", "all"], required=True)
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
        if args.phase in ("3", "all"):
            print("--- PHASE 3 (Tier 4) ---")
            if apply:
                phase3_apply(con)
            else:
                phase3_report(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
