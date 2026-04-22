#!/usr/bin/env python3
"""compute_flows.py — Institutional investor flow analytics from holdings_v2.

Rewrite (Batch 3-2, 2026-04-16): swapped source table from legacy
`holdings` (dropped 2026-04-13 Stage 5) to `holdings_v2`, and added
explicit support for both rollup worldviews (economic_control_v1 +
decision_maker_v1). Each period's INSERT runs twice — once per
worldview — tagged with the `rollup_type` column.

Design notes:
  * Investor key: `rollup_entity_id` (BIGINT, stable) + `rollup_name`
    (display string). `inst_parent_name` retained as a back-compat
    column equal to `rollup_name` for the chosen worldview, so existing
    app reads at `queries.py:1444` (`WHERE inst_parent_name = ?`) keep
    working unchanged.
  * Value column: `market_value_usd` (Group 1, 100% complete). Matches
    legacy semantics (filing-date value, from which `from_price =
    from_value/from_shares` implies price AT filing) — NOT
    `market_value_live` (Group 3, 22.4% NULL post-enrich).
  * Full rebuild every run. Per-(period × worldview) CHECKPOINT.
  * Momentum signals and ticker_flow_stats computed per worldview.

Usage:
  python3 scripts/compute_flows.py --dry-run           # projection
  python3 scripts/compute_flows.py --staging           # write to staging DB
  python3 scripts/compute_flows.py                     # prod full rebuild
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  pylint: disable=wrong-import-position
from config import FLOW_PERIODS  # noqa: E402  pylint: disable=wrong-import-position

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")

_ROLLUP_SPECS = [
    # (rollup_type label, rollup_entity_id col, rollup_name col)
    ("economic_control_v1", "rollup_entity_id", "rollup_name"),
    ("decision_maker_v1",   "dm_rollup_entity_id", "dm_rollup_name"),
]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _Tee:
    """Mirror prints to stdout and a log file. Use as a context manager."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._fh = None

    def __enter__(self) -> "_Tee":
        self._fh = open(  # pylint: disable=consider-using-with
            self.path, "w", encoding="utf-8", buffering=1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._fh is not None:
            self._fh.close()

    def line(self, msg: str = "") -> None:
        """Write a line to stdout and the log file."""
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
        if self._fh is not None:
            self._fh.write(msg + "\n")


# ---------------------------------------------------------------------------
# Schema (DROP+CREATE — full rebuild every run)
# ---------------------------------------------------------------------------

def _create_tables(con) -> None:
    """Drop and recreate the flow output tables with rollup_type support."""
    con.execute("DROP TABLE IF EXISTS investor_flows")
    con.execute("""
        CREATE TABLE investor_flows (
            ticker VARCHAR,
            period VARCHAR,
            quarter_from VARCHAR,
            quarter_to VARCHAR,
            rollup_type VARCHAR,
            rollup_entity_id BIGINT,
            rollup_name VARCHAR,
            inst_parent_name VARCHAR,
            manager_type VARCHAR,
            from_shares DOUBLE,
            to_shares DOUBLE,
            net_shares DOUBLE,
            pct_change DOUBLE,
            from_value DOUBLE,
            to_value DOUBLE,
            from_price DOUBLE,
            price_adj_flow DOUBLE,
            raw_flow DOUBLE,
            price_effect DOUBLE,
            is_new_entry BOOLEAN,
            is_exit BOOLEAN,
            flow_4q DOUBLE,
            flow_2q DOUBLE,
            momentum_ratio DOUBLE,
            momentum_signal VARCHAR
        )
    """)
    con.execute("DROP TABLE IF EXISTS ticker_flow_stats")
    con.execute("""
        CREATE TABLE ticker_flow_stats (
            ticker VARCHAR,
            quarter_from VARCHAR,
            quarter_to VARCHAR,
            rollup_type VARCHAR,
            flow_intensity_total DOUBLE,
            flow_intensity_active DOUBLE,
            flow_intensity_passive DOUBLE,
            churn_nonpassive DOUBLE,
            churn_active DOUBLE,
            computed_at TIMESTAMP
        )
    """)


# ---------------------------------------------------------------------------
# Per-period × per-worldview INSERT
# ---------------------------------------------------------------------------

def _insert_period_flows(  # pylint: disable=too-many-positional-arguments,too-many-arguments
    con,
    period_label: str,
    q_from: str,
    q_to: str,
    rollup_type: str,
    rid_col: str,
    rname_col: str,
) -> int:
    """INSERT one period's flows for one worldview. Returns row count."""
    con.execute(f"""
        INSERT INTO investor_flows (
            ticker, period, quarter_from, quarter_to,
            rollup_type, rollup_entity_id, rollup_name, inst_parent_name,
            manager_type,
            from_shares, to_shares, net_shares, pct_change,
            from_value, to_value, from_price,
            price_adj_flow, raw_flow, price_effect,
            is_new_entry, is_exit,
            flow_4q, flow_2q, momentum_ratio, momentum_signal
        )
        WITH q_from AS (
            SELECT ticker,
                   {rid_col}   AS rollup_entity_id,
                   {rname_col} AS rollup_name,
                   MAX(manager_type) AS manager_type,
                   SUM(shares)           AS shares,
                   SUM(market_value_usd) AS value
            FROM holdings_v2
            WHERE quarter = '{q_from}'
              AND ticker IS NOT NULL AND ticker != ''
              AND is_latest = TRUE
            GROUP BY ticker, {rid_col}, {rname_col}
        ),
        q_to AS (
            SELECT ticker,
                   {rid_col}   AS rollup_entity_id,
                   {rname_col} AS rollup_name,
                   MAX(manager_type) AS manager_type,
                   SUM(shares)           AS shares,
                   SUM(market_value_usd) AS value
            FROM holdings_v2
            WHERE quarter = '{q_to}'
              AND ticker IS NOT NULL AND ticker != ''
              AND is_latest = TRUE
            GROUP BY ticker, {rid_col}, {rname_col}
        ),
        combined AS (
            SELECT
                COALESCE(t.ticker, f.ticker)                     AS ticker,
                COALESCE(t.rollup_entity_id, f.rollup_entity_id) AS rollup_entity_id,
                COALESCE(t.rollup_name, f.rollup_name)           AS rollup_name,
                COALESCE(t.manager_type, f.manager_type)         AS manager_type,
                COALESCE(f.shares, 0) AS from_shares,
                COALESCE(t.shares, 0) AS to_shares,
                COALESCE(f.value,  0) AS from_value,
                COALESCE(t.value,  0) AS to_value
            FROM q_to t
            FULL OUTER JOIN q_from f
                ON t.ticker = f.ticker
               AND t.rollup_entity_id IS NOT DISTINCT FROM f.rollup_entity_id
        ),
        flows AS (
            SELECT *,
                to_shares - from_shares AS net_shares,
                CASE WHEN from_shares > 0
                     THEN (to_shares - from_shares) / from_shares END AS pct_change,
                from_shares = 0 AND to_shares > 0 AS is_new_entry,
                from_shares > 0 AND to_shares = 0 AS is_exit,
                CASE WHEN from_shares > 0 AND from_value > 0
                     THEN from_value / from_shares END AS from_price,
                CASE WHEN from_shares > 0 AND from_value > 0
                     THEN (to_shares - from_shares) * (from_value / from_shares)
                     END AS price_adj_flow,
                to_value - from_value AS raw_flow,
                CASE WHEN from_shares > 0 AND from_value > 0
                     THEN (to_value - from_value)
                          - ((to_shares - from_shares) * (from_value / from_shares))
                     END AS price_effect
            FROM combined
            WHERE from_shares > 0 OR to_shares > 0
        )
        SELECT
            ticker,
            '{period_label}' AS period,
            '{q_from}' AS quarter_from,
            '{q_to}' AS quarter_to,
            '{rollup_type}' AS rollup_type,
            rollup_entity_id,
            rollup_name,
            rollup_name AS inst_parent_name,   -- back-compat for queries.py:1444
            manager_type,
            CASE WHEN from_shares > 0 THEN from_shares END,
            CASE WHEN to_shares   > 0 THEN to_shares   END,
            CASE WHEN net_shares != 0 THEN net_shares  END,
            pct_change,
            CASE WHEN from_value > 0 THEN from_value END,
            CASE WHEN to_value   > 0 THEN to_value   END,
            from_price,
            price_adj_flow,
            CASE WHEN raw_flow != 0 THEN raw_flow END,
            price_effect,
            is_new_entry,
            is_exit,
            NULL, NULL, NULL, NULL   -- momentum fields filled in next pass
        FROM flows
    """)
    return con.execute(
        f"SELECT COUNT(*) FROM investor_flows "
        f"WHERE period = '{period_label}' AND rollup_type = '{rollup_type}'"
    ).fetchone()[0]


def _project_period_flows(
    con,
    q_from: str,
    q_to: str,
    rid_col: str,
    rname_col: str,
) -> int:
    """Dry-run projection: count rows that would be inserted for this slice."""
    row = con.execute(f"""
        WITH q_from AS (
            SELECT ticker, {rid_col} AS rid, {rname_col} AS rname,
                   SUM(shares) AS shares, SUM(market_value_usd) AS value
            FROM holdings_v2
            WHERE quarter = '{q_from}' AND ticker IS NOT NULL AND ticker != '' AND is_latest = TRUE
            GROUP BY ticker, {rid_col}, {rname_col}
        ),
        q_to AS (
            SELECT ticker, {rid_col} AS rid, {rname_col} AS rname,
                   SUM(shares) AS shares, SUM(market_value_usd) AS value
            FROM holdings_v2
            WHERE quarter = '{q_to}' AND ticker IS NOT NULL AND ticker != '' AND is_latest = TRUE
            GROUP BY ticker, {rid_col}, {rname_col}
        )
        SELECT COUNT(*)
        FROM q_to t
        FULL OUTER JOIN q_from f
            ON t.ticker = f.ticker
           AND t.rid IS NOT DISTINCT FROM f.rid
        WHERE COALESCE(f.shares, 0) > 0 OR COALESCE(t.shares, 0) > 0
    """).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Momentum + ticker stats (per-worldview)
# ---------------------------------------------------------------------------

def _compute_momentum(con, rollup_type: str) -> None:
    """Fill flow_4q / flow_2q / momentum_ratio / momentum_signal."""
    con.execute(f"""
        UPDATE investor_flows f
           SET flow_4q = m4.price_adj_flow
          FROM investor_flows m4
         WHERE f.ticker           = m4.ticker
           AND f.rollup_entity_id IS NOT DISTINCT FROM m4.rollup_entity_id
           AND f.rollup_type      = m4.rollup_type
           AND m4.period          = '4Q'
           AND f.rollup_type      = '{rollup_type}'
           AND f.flow_4q IS NULL
    """)
    con.execute(f"""
        UPDATE investor_flows f
           SET flow_2q = m1.price_adj_flow
          FROM investor_flows m1
         WHERE f.ticker           = m1.ticker
           AND f.rollup_entity_id IS NOT DISTINCT FROM m1.rollup_entity_id
           AND f.rollup_type      = m1.rollup_type
           AND m1.period          = '1Q'
           AND f.rollup_type      = '{rollup_type}'
           AND f.flow_2q IS NULL
    """)
    con.execute(f"""
        UPDATE investor_flows
           SET momentum_ratio = CASE WHEN flow_4q != 0 AND flow_2q IS NOT NULL
                                     THEN flow_2q / flow_4q END
         WHERE rollup_type = '{rollup_type}'
    """)
    con.execute(f"""
        UPDATE investor_flows
           SET momentum_signal = CASE
                WHEN manager_type = 'passive' THEN NULL
                WHEN is_new_entry             THEN 'NEW'
                WHEN is_exit                  THEN 'EXIT'
                WHEN momentum_ratio IS NULL   THEN NULL
                WHEN momentum_ratio >  0.65   THEN 'ACCEL'
                WHEN momentum_ratio >= 0.35   THEN 'STEADY'
                WHEN momentum_ratio >= 0.10   THEN 'FADING'
                WHEN momentum_ratio >= 0      THEN 'MINIMAL'
                ELSE 'REVERSING'
             END
         WHERE rollup_type = '{rollup_type}'
    """)


def _compute_ticker_stats(con, rollup_type: str) -> int:
    """INSERT aggregate flow_intensity + churn per (ticker, period) for a worldview.

    flow_intensity_total = SUM(price_adj_flow) / market_cap, summed over
    continuing holders only (rows where NOT is_new_entry AND NOT is_exit);
    `price_adj_flow = net_shares * from_price` isolates share-count change
    at filing-date price (no price effect). Output is a unitless ratio —
    net institutional $-flow as a fraction of ticker market cap for the
    (quarter_from → quarter_to) window. `flow_intensity_active` /
    `flow_intensity_passive` are the same formula scoped to
    manager_type != 'passive' / manager_type = 'passive'.
    """
    con.execute(f"""
        INSERT INTO ticker_flow_stats
        SELECT
            f.ticker,
            quarter_from,
            quarter_to,
            '{rollup_type}' AS rollup_type,
            SUM(CASE WHEN NOT is_new_entry AND NOT is_exit
                     THEN price_adj_flow ELSE 0 END)
                / NULLIF(MAX(m.market_cap), 0) AS fi_total,
            SUM(CASE WHEN NOT is_new_entry AND NOT is_exit
                          AND manager_type != 'passive'
                     THEN price_adj_flow ELSE 0 END)
                / NULLIF(MAX(m.market_cap), 0) AS fi_active,
            SUM(CASE WHEN NOT is_new_entry AND NOT is_exit
                          AND manager_type  = 'passive'
                     THEN price_adj_flow ELSE 0 END)
                / NULLIF(MAX(m.market_cap), 0) AS fi_passive,
            (SUM(CASE WHEN is_new_entry AND manager_type != 'passive'
                      THEN to_value ELSE 0 END)
             + SUM(CASE WHEN is_exit AND manager_type != 'passive'
                        THEN from_value ELSE 0 END))
            / NULLIF((SUM(CASE WHEN NOT is_new_entry AND manager_type != 'passive'
                                THEN from_value ELSE 0 END)
                    + SUM(CASE WHEN NOT is_exit AND manager_type != 'passive'
                                THEN to_value ELSE 0 END)) / 2, 0) AS churn_np,
            (SUM(CASE WHEN is_new_entry AND manager_type = 'active'
                      THEN to_value ELSE 0 END)
             + SUM(CASE WHEN is_exit AND manager_type = 'active'
                        THEN from_value ELSE 0 END))
            / NULLIF((SUM(CASE WHEN NOT is_new_entry AND manager_type = 'active'
                                THEN from_value ELSE 0 END)
                    + SUM(CASE WHEN NOT is_exit AND manager_type = 'active'
                                THEN to_value ELSE 0 END)) / 2, 0) AS churn_active,
            CURRENT_TIMESTAMP
        FROM investor_flows f
        LEFT JOIN market_data m ON f.ticker = m.ticker
        WHERE f.rollup_type = '{rollup_type}'
        GROUP BY f.ticker, quarter_from, quarter_to
    """)
    return con.execute(
        f"SELECT COUNT(*) FROM ticker_flow_stats "
        f"WHERE rollup_type = '{rollup_type}'"
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """CLI parser."""
    parser = argparse.ArgumentParser(
        description="Compute investor flow analytics from holdings_v2.",
    )
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB (default: prod)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Project per-slice row counts, no writes")
    return parser.parse_args()


def _open_connection(args: argparse.Namespace):
    """Open a connection per --staging / --dry-run."""
    if args.staging:
        db.set_staging_mode(True)
    if args.dry_run:
        return duckdb.connect(db.get_db_path(), read_only=True)
    return db.connect_write()


def _run_dry(con, log: _Tee) -> None:
    """Project per-(period × worldview) row counts without writes."""
    log.line("Dry-run projection — per (period × worldview)")
    log.line(f"{'period':8s} {'worldview':22s} {'from → to':18s} {'projected rows':>16s}")
    grand_total = 0
    for period_label, q_from, q_to in FLOW_PERIODS:
        for rollup_type, rid_col, rname_col in _ROLLUP_SPECS:
            n = _project_period_flows(con, q_from, q_to, rid_col, rname_col)
            grand_total += n
            log.line(f"{period_label:8s} {rollup_type:22s} "
                     f"{q_from} → {q_to}  {n:>16,}")
    log.line("")
    log.line(f"  TOTAL projected investor_flows rows : {grand_total:>16,}")
    log.line(f"  (legacy row count was 9,380,507 on {len(FLOW_PERIODS)} periods × 1 worldview;")
    log.line(f"   new shape is {len(FLOW_PERIODS)} periods × {len(_ROLLUP_SPECS)} worldviews.)")


def _run_write(con, log: _Tee) -> None:
    """Full rebuild: drop + recreate tables, INSERT per (period × worldview)."""
    _create_tables(con)
    log.line("Tables dropped + recreated with rollup_type column.")
    log.line("")

    log.line("Inserting flows — per (period × worldview)")
    for period_label, q_from, q_to in FLOW_PERIODS:
        for rollup_type, rid_col, rname_col in _ROLLUP_SPECS:
            t0 = time.time()
            n = _insert_period_flows(
                con, period_label, q_from, q_to, rollup_type, rid_col, rname_col)
            con.execute("CHECKPOINT")
            log.line(f"  {period_label:3s} {rollup_type:22s} "
                     f"{q_from}→{q_to}  {n:>10,} rows  "
                     f"({time.time()-t0:.1f}s, CHECKPOINT)")
    log.line("")

    log.line("Computing momentum signals (per worldview)")
    for rollup_type, _, _ in _ROLLUP_SPECS:
        t0 = time.time()
        _compute_momentum(con, rollup_type)
        con.execute("CHECKPOINT")
        log.line(f"  {rollup_type}  ({time.time()-t0:.1f}s, CHECKPOINT)")
    log.line("")

    log.line("Computing ticker-level stats (per worldview)")
    for rollup_type, _, _ in _ROLLUP_SPECS:
        t0 = time.time()
        n = _compute_ticker_stats(con, rollup_type)
        con.execute("CHECKPOINT")
        log.line(f"  {rollup_type}  {n:>10,} rows  "
                 f"({time.time()-t0:.1f}s, CHECKPOINT)")
    log.line("")

    total_flows = con.execute("SELECT COUNT(*) FROM investor_flows").fetchone()[0]
    total_stats = con.execute("SELECT COUNT(*) FROM ticker_flow_stats").fetchone()[0]
    db.record_freshness(con, "investor_flows",    total_flows)
    db.record_freshness(con, "ticker_flow_stats", total_stats)
    log.line(f"Post-state: investor_flows {total_flows:,} / "
             f"ticker_flow_stats {total_stats:,}")
    log.line("data_freshness stamped on both tables.")


def main() -> None:
    """Entry point — orchestrates dry-run or full rebuild."""
    args = _parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"compute_flows_{ts}.log")

    with _Tee(log_path) as log:
        mode = "DRY-RUN" if args.dry_run else "WRITE"
        target = "staging" if args.staging else "prod"
        if args.staging:
            db.set_staging_mode(True)
        log.line(f"compute_flows.py — {mode} against {target} DB "
                 f"({db.get_db_path()})")
        log.line(f"  periods  : {FLOW_PERIODS}")
        log.line(f"  worldviews: {[r[0] for r in _ROLLUP_SPECS]}")
        log.line(f"  log      : {log_path}")
        log.line("=" * 78)

        con = _open_connection(args)
        t_start = time.time()
        try:
            if args.dry_run:
                _run_dry(con, log)
                log.line("")
                log.line("=" * 78)
                log.line("DRY-RUN: no writes. Re-run without --dry-run to apply.")
            else:
                _run_write(con, log)
        finally:
            con.close()

        log.line("")
        log.line(f"Completed in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
