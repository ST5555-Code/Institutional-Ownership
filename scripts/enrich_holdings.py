#!/usr/bin/env python3
"""enrich_holdings.py — Batch 3 Group 3 enrichment for `holdings_v2` (and
optional `fund_holdings_v2.ticker` pass).

Owns the post-promote enrichment pass for:
  - holdings_v2.ticker
  - holdings_v2.security_type_inferred
  - holdings_v2.market_value_live
  - holdings_v2.pct_of_float
  - fund_holdings_v2.ticker  (when --fund-holdings)

Design notes:
  * Universe gate (holdings_v2): cusip_classifications.is_equity = TRUE.
    Non-equity rows get NULLs (legacy contamination cleanup — OPTION /
    BOND / CASH / WARRANT lines previously carried tickers from the
    legacy COALESCE-on-cusip path).
  * Join key: lookup is keyed by cusip (1:1 in cusip_classifications,
    securities, market_data.ticker — verified against live DB
    2026-04-16). Per-row mvl / pof use the OUTER row's `shares`, so the
    lookup-keyed-by-cusip pattern is safe even though
    (accession_number, cusip, quarter) is NOT unique on holdings_v2
    (~1.29M dup groups, ~4.97M rows).
  * D6 resolved as option (b): full refresh of historical rows on every
    run. Provide --quarter YYYYQN to scope to one quarter.

CLI:
  --staging              write to staging DB instead of prod
  --dry-run              projection only — show row deltas, no writes
  --quarter YYYYQN       scope to a single quarter
  --fund-holdings        also populate fund_holdings_v2.ticker

Run:
  python3 scripts/enrich_holdings.py --dry-run
  python3 scripts/enrich_holdings.py --staging --dry-run
  python3 scripts/enrich_holdings.py                        # prod full refresh
  python3 scripts/enrich_holdings.py --quarter 2026Q1
  python3 scripts/enrich_holdings.py --fund-holdings
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  pylint: disable=wrong-import-position

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")


# Cusip-keyed lookup. One row per cusip (verified 1:1 across
# cusip_classifications / securities / market_data).
#
# `security_type_inferred` reads from `securities.security_type_inferred`
# (legacy domain: equity / etf / derivative / money_market) and is NOT
# gated on `is_equity` — it tags every row with a usable type label
# regardless of whether the row is equity-priceable. The newer
# `cusip_classifications.canonical_type` (BOND/COM/OPTION/ETF/...) lives
# in a different domain that the app's read-paths don't speak; introducing
# it here would change ~12.27M rows for no downstream consumer.
_LOOKUP_SQL = """
    SELECT c.cusip,
           s.security_type_inferred,
           c.is_equity,
           CASE WHEN c.is_equity THEN s.ticker END AS new_ticker,
           md.price_live,
           md.float_shares
      FROM cusip_classifications c
      LEFT JOIN securities  s  ON s.cusip = c.cusip
      LEFT JOIN market_data md ON md.ticker = s.ticker
"""


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
        """Write a line to both stdout and the log file."""
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
        if self._fh is not None:
            self._fh.write(msg + "\n")


# ---------------------------------------------------------------------------
# Pass A — NULL cleanup on holdings_v2 for unclassified cusips
# ---------------------------------------------------------------------------

def _pass_a_project(con, quarter: str | None) -> dict:
    """Count rows that Pass A would touch and clear, per column."""
    where_q = "AND quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    row = con.execute(
        f"""
        SELECT
            COUNT(*) AS rows_targeted,
            COUNT(*) FILTER (WHERE ticker                 IS NOT NULL) AS ticker_clear,
            COUNT(*) FILTER (WHERE security_type_inferred IS NOT NULL) AS sti_clear,
            COUNT(*) FILTER (WHERE market_value_live      IS NOT NULL) AS mvl_clear,
            COUNT(*) FILTER (WHERE pct_of_float           IS NOT NULL) AS pof_clear
        FROM holdings_v2
        WHERE cusip NOT IN (SELECT cusip FROM cusip_classifications)
          {where_q}
        """,
        params,
    ).fetchone()
    return {
        "rows_targeted": row[0],
        "ticker_clear": row[1],
        "sti_clear":    row[2],
        "mvl_clear":    row[3],
        "pof_clear":    row[4],
    }


def _pass_a_apply(con, quarter: str | None) -> int:
    """Run Pass A: NULL Group 3 columns on rows whose cusip isn't classified."""
    where_q = "AND quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    con.execute(
        f"""
        UPDATE holdings_v2
           SET ticker                 = NULL,
               security_type_inferred = NULL,
               market_value_live      = NULL,
               pct_of_float           = NULL
         WHERE cusip NOT IN (SELECT cusip FROM cusip_classifications)
           {where_q}
        """,
        params,
    )
    return con.execute(
        f"""
        SELECT COUNT(*) FROM holdings_v2
        WHERE cusip NOT IN (SELECT cusip FROM cusip_classifications)
          {where_q}
        """,
        params,
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Pass B — Main enrichment on holdings_v2
# ---------------------------------------------------------------------------

def _pass_b_project(con, quarter: str | None) -> dict:
    """Project Pass B per-column changes and projected post-state populations."""
    where_q = "AND h.quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    row = con.execute(
        f"""
        WITH lookup AS ({_LOOKUP_SQL}),
        proj AS (
            SELECT
                h.shares,
                h.ticker                 AS old_ticker,
                h.security_type_inferred AS old_sti,
                h.market_value_live      AS old_mvl,
                h.pct_of_float           AS old_pof,
                lookup.new_ticker        AS new_ticker,
                lookup.security_type_inferred AS new_sti,
                CASE WHEN lookup.is_equity AND lookup.price_live IS NOT NULL
                     THEN h.shares * lookup.price_live END AS new_mvl,
                CASE WHEN lookup.is_equity AND lookup.float_shares > 0
                     THEN h.shares * 100.0 / lookup.float_shares END AS new_pof
            FROM holdings_v2 h
            JOIN lookup ON lookup.cusip = h.cusip
            WHERE 1=1 {where_q}
        )
        SELECT
            COUNT(*) AS rows_in_scope,
            COUNT(*) FILTER (WHERE old_ticker IS DISTINCT FROM new_ticker) AS ticker_changes,
            COUNT(*) FILTER (WHERE old_sti    IS DISTINCT FROM new_sti)    AS sti_changes,
            COUNT(*) FILTER (WHERE old_mvl    IS DISTINCT FROM new_mvl)    AS mvl_changes,
            COUNT(*) FILTER (WHERE old_pof    IS DISTINCT FROM new_pof)    AS pof_changes,
            COUNT(*) FILTER (WHERE new_ticker IS NOT NULL) AS ticker_post,
            COUNT(*) FILTER (WHERE new_sti    IS NOT NULL) AS sti_post,
            COUNT(*) FILTER (WHERE new_mvl    IS NOT NULL) AS mvl_post,
            COUNT(*) FILTER (WHERE new_pof    IS NOT NULL) AS pof_post
        FROM proj
        """,
        params,
    ).fetchone()
    return {
        "rows_in_scope":  row[0],
        "ticker_changes": row[1],
        "sti_changes":    row[2],
        "mvl_changes":    row[3],
        "pof_changes":    row[4],
        "ticker_post":    row[5],
        "sti_post":       row[6],
        "mvl_post":       row[7],
        "pof_post":       row[8],
    }


def _pass_b_apply(con, quarter: str | None) -> int:
    """Run Pass B: cusip-keyed UPDATE...FROM (lookup) populating Group 3."""
    where_q = "AND h.quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    con.execute(
        f"""
        UPDATE holdings_v2 AS h
           SET ticker                 = lookup.new_ticker,
               security_type_inferred = lookup.security_type_inferred,
               market_value_live      = CASE WHEN lookup.is_equity
                                              AND lookup.price_live IS NOT NULL
                                             THEN h.shares * lookup.price_live END,
               pct_of_float           = CASE WHEN lookup.is_equity
                                              AND lookup.float_shares > 0
                                             THEN h.shares * 100.0
                                                  / lookup.float_shares END
          FROM ({_LOOKUP_SQL}) AS lookup
         WHERE h.cusip = lookup.cusip
           {where_q}
        """,
        params,
    )
    return con.execute(
        f"""
        SELECT COUNT(*) FROM holdings_v2 h
        JOIN cusip_classifications c ON c.cusip = h.cusip
        WHERE 1=1 {where_q}
        """,
        params,
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Pass C — fund_holdings_v2.ticker populate (is_priceable gate, no is_equity gate)
# ---------------------------------------------------------------------------
# Pass C populates ticker from `securities` rows that are both non-null and
# `is_priceable = TRUE`. Two intentional choices:
#
#   1. No is_equity gate. N-PORT holds many ETF / CEF / ADR positions
#      whose CUSIPs carry a real ticker in `securities` but classify as
#      is_equity=FALSE (asset_category EC is broader than 13F equity).
#      Gating on is_equity would suppress legitimate fund-level ticker
#      enrichment.
#
#   2. is_priceable = TRUE gate. Post-BLOCK-SECURITIES-DATA-AUDIT the
#      securities universe (~430K rows) carries ~389K is_priceable=FALSE
#      rows — foreign-shape tickers (HO1, FT2, CB1A), non-US composite
#      exchange listings, preferreds, warrants, and OTC grey-market codes.
#      Without this gate, Pass C would stamp ~517K fund_holdings_v2 rows
#      with functionally-wrong tickers (foreign secondary listings in
#      place of US primaries). is_priceable is broader than is_equity, so
#      the ETF/CEF/ADR inclusion above is preserved.
#
# Idempotent populate, not a refresh — does NOT clear stale tickers.

def _pass_c_project(con, quarter: str | None) -> dict:
    """Project Pass C: NULL→ticker populates and ticker→ticker changes."""
    where_q = "AND fh.quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    row = con.execute(
        f"""
        WITH proj AS (
            SELECT fh.ticker AS old_ticker,
                   s.ticker  AS new_ticker
              FROM fund_holdings_v2 fh
              LEFT JOIN securities s
                     ON s.cusip = fh.cusip
                    AND s.is_priceable = TRUE
             WHERE 1=1 {where_q}
        )
        SELECT
            COUNT(*) AS rows_in_scope,
            COUNT(*) FILTER (WHERE old_ticker IS NULL
                             AND new_ticker IS NOT NULL) AS will_populate,
            COUNT(*) FILTER (WHERE old_ticker IS NOT NULL
                             AND new_ticker IS NOT NULL
                             AND old_ticker IS DISTINCT FROM new_ticker)
                                                         AS will_change,
            COUNT(*) FILTER (WHERE COALESCE(new_ticker, old_ticker)
                             IS NOT NULL)                AS ticker_post
        FROM proj
        """,
        params,
    ).fetchone()
    return {
        "rows_in_scope": row[0],
        "will_populate": row[1],
        "will_change":   row[2],
        "ticker_post":   row[3],
    }


def _pass_c_apply(con, quarter: str | None) -> int:
    """Run Pass C: populate fund_holdings_v2.ticker from securities by cusip."""
    where_q = "AND fh.quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    con.execute(
        f"""
        UPDATE fund_holdings_v2 AS fh
           SET ticker = s.ticker
          FROM securities s
         WHERE s.cusip = fh.cusip
           AND s.ticker IS NOT NULL
           AND s.is_priceable = TRUE
           {where_q}
        """,
        params,
    )
    return con.execute(
        f"""
        SELECT COUNT(*) FROM fund_holdings_v2 fh
        WHERE ticker IS NOT NULL
          {where_q}
        """,
        params,
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _baseline_h(con, quarter: str | None) -> dict:
    """Snapshot Group 3 NULL rates on holdings_v2 in the given scope."""
    where_q = "WHERE quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    row = con.execute(
        f"""
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE ticker                 IS NOT NULL),
            COUNT(*) FILTER (WHERE security_type_inferred IS NOT NULL),
            COUNT(*) FILTER (WHERE market_value_live      IS NOT NULL),
            COUNT(*) FILTER (WHERE pct_of_float           IS NOT NULL)
        FROM holdings_v2
        {where_q}
        """,
        params,
    ).fetchone()
    return {"total": row[0], "ticker": row[1], "sti": row[2],
            "mvl": row[3], "pof": row[4]}


def _baseline_fh(con, quarter: str | None) -> dict:
    """Snapshot ticker NULL rate on fund_holdings_v2 in the given scope."""
    where_q = "WHERE quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    row = con.execute(
        f"""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE ticker IS NOT NULL)
        FROM fund_holdings_v2
        {where_q}
        """,
        params,
    ).fetchone()
    return {"total": row[0], "ticker": row[1]}


def _fmt_pct(numer: int, denom: int) -> str:
    """Format `numer/denom` as a right-padded percentage with 2 decimals."""
    if not denom:
        return "  n/a "
    return f"{100*numer/denom:6.2f}%"


def _print_baseline(log: _Tee, baseline: dict) -> None:
    """Emit the holdings_v2 baseline block."""
    log.line("Baseline — holdings_v2:")
    log.line(f"  rows in scope         : {baseline['total']:>14,}")
    for key, label in (("ticker", "ticker populated"),
                       ("sti",    "sti populated   "),
                       ("mvl",    "mvl populated   "),
                       ("pof",    "pof populated   ")):
        pct = _fmt_pct(baseline[key], baseline['total'])
        log.line(f"  {label}      : {baseline[key]:>14,}  ({pct})")
    log.line("")


def _print_pass_a(log: _Tee, proj: dict) -> None:
    """Emit Pass A (NULL cleanup) projection block."""
    log.line("Pass A — NULL cleanup on holdings_v2 for unclassified cusips")
    log.line(f"  rows targeted (cusip not classified) : {proj['rows_targeted']:>14,}")
    log.line(f"  ticker values that will clear        : {proj['ticker_clear']:>14,}")
    log.line(f"  sti    values that will clear        : {proj['sti_clear']:>14,}")
    log.line(f"  mvl    values that will clear        : {proj['mvl_clear']:>14,}")
    log.line(f"  pof    values that will clear        : {proj['pof_clear']:>14,}")


def _print_pass_b(log: _Tee, proj: dict) -> None:
    """Emit Pass B (main enrichment) projection block."""
    log.line("Pass B — Main enrichment on holdings_v2 (cusip-keyed lookup)")
    log.line(f"  rows in scope (equity-classifiable cusip) : {proj['rows_in_scope']:>14,}")
    log.line(f"  ticker changes                            : {proj['ticker_changes']:>14,}")
    log.line(f"  sti    changes                            : {proj['sti_changes']:>14,}")
    log.line(f"  mvl    changes                            : {proj['mvl_changes']:>14,}")
    log.line(f"  pof    changes                            : {proj['pof_changes']:>14,}")
    log.line("  projected post-state in scope:")
    log.line(f"    ticker populated : {proj['ticker_post']:>14,}")
    log.line(f"    sti    populated : {proj['sti_post']:>14,}")
    log.line(f"    mvl    populated : {proj['mvl_post']:>14,}")
    log.line(f"    pof    populated : {proj['pof_post']:>14,}")


def _print_pass_c(log: _Tee, baseline_fh: dict, proj: dict) -> None:
    """Emit Pass C (fund_holdings_v2 ticker) projection block."""
    log.line("Pass C — fund_holdings_v2.ticker populate (no is_equity gate)")
    pct = _fmt_pct(baseline_fh['ticker'], baseline_fh['total'])
    log.line(f"  fund_holdings_v2 rows in scope : {baseline_fh['total']:>14,}")
    log.line(f"  ticker populated today         : {baseline_fh['ticker']:>14,}  ({pct})")
    log.line(f"  rows that will populate (NULL->non-NULL) : {proj['will_populate']:>14,}")
    log.line(f"  rows that will change   (X->Y, both non-null): {proj['will_change']:>14,}")
    log.line(f"  projected ticker populated post : {proj['ticker_post']:>14,}")


def _print_post(log: _Tee, before: dict, after: dict, label: str) -> None:
    """Emit a post-write summary for a baseline dict (holdings_v2 or fund_holdings_v2)."""
    log.line(f"Post-state — {label}:")
    log.line(f"  rows in scope         : {after['total']:>14,}")
    for key, name in (("ticker", "ticker populated"),
                      ("sti",    "sti populated   "),
                      ("mvl",    "mvl populated   "),
                      ("pof",    "pof populated   ")):
        if key not in after:
            continue
        delta = after[key] - before[key]
        log.line(f"  {name}      : {after[key]:>14,}  (delta {delta:+,})")


# ---------------------------------------------------------------------------
# Pass orchestrators (broken out to keep main() flat)
# ---------------------------------------------------------------------------

def _run_pass_a(con, log: _Tee, args) -> None:
    """Project (and apply, when not dry-run) Pass A."""
    proj = _pass_a_project(con, args.quarter)
    _print_pass_a(log, proj)
    if not args.dry_run:
        t0 = time.time()
        cleaned = _pass_a_apply(con, args.quarter)
        con.execute("CHECKPOINT")
        elapsed = time.time() - t0
        log.line(f"  applied — {cleaned:,} rows now NULL across 4 cols  "
                 f"({elapsed:.1f}s, CHECKPOINT)")
    log.line("")


def _run_pass_b(con, log: _Tee, args) -> None:
    """Project (and apply, when not dry-run) Pass B."""
    proj = _pass_b_project(con, args.quarter)
    _print_pass_b(log, proj)
    if not args.dry_run:
        t0 = time.time()
        scope = _pass_b_apply(con, args.quarter)
        con.execute("CHECKPOINT")
        elapsed = time.time() - t0
        log.line(f"  applied — {scope:,} rows touched  "
                 f"({elapsed:.1f}s, CHECKPOINT)")
    log.line("")


def _run_pass_c(con, log: _Tee, args) -> dict:
    """Project (and apply, when not dry-run) Pass C. Returns baseline_fh."""
    baseline_fh = _baseline_fh(con, args.quarter)
    proj = _pass_c_project(con, args.quarter)
    _print_pass_c(log, baseline_fh, proj)
    if not args.dry_run:
        t0 = time.time()
        post = _pass_c_apply(con, args.quarter)
        con.execute("CHECKPOINT")
        elapsed = time.time() - t0
        log.line(f"  applied — {post:,} rows now have ticker  "
                 f"({elapsed:.1f}s, CHECKPOINT)")
    log.line("")
    return baseline_fh


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """CLI parser."""
    parser = argparse.ArgumentParser(
        description=("Batch 3 Group 3 enrichment for holdings_v2 "
                     "(and optional fund_holdings_v2.ticker pass)."),
    )
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB (default: prod)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Project deltas without writing")
    parser.add_argument("--quarter", default=None,
                        help="Scope to one quarter (YYYYQN)")
    parser.add_argument("--fund-holdings", action="store_true",
                        help="Also populate fund_holdings_v2.ticker")
    args = parser.parse_args()
    if args.quarter and not QUARTER_RE.match(args.quarter):
        raise SystemExit(f"--quarter must match YYYYQN (got {args.quarter!r})")
    return args


def _open_connection(args: argparse.Namespace):
    """Open a write or read-only connection per --staging / --dry-run."""
    if args.staging:
        db.set_staging_mode(True)
    if args.dry_run:
        return duckdb.connect(db.get_db_path(), read_only=True)
    return db.connect_write()


def main() -> None:
    """Entry point — orchestrates Pass A → B → (C) and freshness stamping."""
    args = _parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"enrich_holdings_{ts}.log")

    with _Tee(log_path) as log:
        mode = "DRY-RUN" if args.dry_run else "WRITE"
        target = "staging" if args.staging else "prod"
        qtr = args.quarter or "ALL"

        if args.staging:
            db.set_staging_mode(True)
        log.line(f"enrich_holdings.py — {mode} against {target} DB "
                 f"({db.get_db_path()})")
        log.line(f"  quarter scope   : {qtr}")
        log.line(f"  fund-holdings   : {'YES' if args.fund_holdings else 'NO'}")
        log.line(f"  log             : {log_path}")
        log.line("=" * 78)

        con = _open_connection(args)
        try:
            baseline_h = _baseline_h(con, args.quarter)
            _print_baseline(log, baseline_h)

            _run_pass_a(con, log, args)
            _run_pass_b(con, log, args)
            baseline_fh = _run_pass_c(con, log, args) if args.fund_holdings else None

            if args.dry_run:
                log.line("=" * 78)
                log.line("DRY-RUN: no writes performed. "
                         "Re-run without --dry-run to apply.")
                return

            after_h = _baseline_h(con, args.quarter)
            _print_post(log, baseline_h, after_h, "holdings_v2")
            if args.fund_holdings:
                after_fh = _baseline_fh(con, args.quarter)
                delta = after_fh["ticker"] - baseline_fh["ticker"]
                log.line(f"  fund_holdings_v2 ticker populated: "
                         f"{after_fh['ticker']:>14,}  (delta {delta:+,})")

            db.record_freshness(con, "holdings_v2_enrichment",
                                row_count=after_h["ticker"])
            # Also stamp the L3 table itself. `holdings_v2` currently has
            # no active INSERT-side writer (legacy load_13f.py targets the
            # dropped `holdings` table; a v2 loader is not yet built).
            # Enrichment is the only script that touches the full table
            # regularly, so `enrich_holdings.py` owns the freshness stamp
            # until a dedicated 13F loader lands.
            holdings_total = con.execute(
                "SELECT COUNT(*) FROM holdings_v2"
            ).fetchone()[0]
            db.record_freshness(con, "holdings_v2", row_count=holdings_total)
            log.line("")
            log.line("data_freshness('holdings_v2_enrichment') stamped, "
                     f"row_count={after_h['ticker']:,}")
            log.line("data_freshness('holdings_v2') stamped, "
                     f"row_count={holdings_total:,}")
        finally:
            con.close()


if __name__ == "__main__":
    main()
