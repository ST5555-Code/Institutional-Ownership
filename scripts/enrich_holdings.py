#!/usr/bin/env python3
"""enrich_holdings.py — Batch 3 Group 3 enrichment for `holdings_v2` (and
optional `fund_holdings_v2.ticker` pass).

Owns the post-promote enrichment pass for:
  - holdings_v2.ticker
  - holdings_v2.security_type_inferred
  - holdings_v2.market_value_live
  - holdings_v2.pct_of_so               (renamed from pct_of_float in 008)
  - holdings_v2.pct_of_so_source        (audit column added in 008)
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
  * Pass B period-accuracy (BLOCK-PCT-OF-SO-PERIOD-ACCURACY, 2026-04-19):
    pct_of_so denominator is the ASOF match from
    `shares_outstanding_history` keyed by (ticker, as_of_date <= quarter_end)
    — not `market_data.float_shares` (latest, period-agnostic). Fallback
    tier when no SOH match: `market_data.shares_outstanding` (or
    `float_shares` backstop). Each row is stamped with a
    `pct_of_so_source` audit value: 'soh_period_accurate' or
    'market_data_latest'.
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
#
# `md_shares_outstanding` / `md_float_shares` are the LATEST market_data
# denominator columns, used only as fallback when SOH has no period
# match for a (ticker, quarter_end) pair. Period-accurate pct_of_so
# uses `shares_outstanding_history.shares` via ASOF JOIN in
# `_pass_b_resolved_cte` below.
_LOOKUP_SQL = """
    SELECT c.cusip,
           s.security_type_inferred,
           c.is_equity,
           CASE WHEN c.is_equity THEN s.ticker END AS new_ticker,
           md.price_live,
           md.shares_outstanding AS md_shares_outstanding,
           md.float_shares       AS md_float_shares
      FROM cusip_classifications c
      LEFT JOIN securities  s  ON s.cusip = c.cusip
      LEFT JOIN market_data md ON md.ticker = s.ticker
"""


# Period-accurate denominator resolution for Pass B.
#
# For every distinct (cusip, report_date) pair in holdings_v2, resolve:
#   - lookup columns (is_equity, ticker, price_live, md fallbacks)
#   - SOH row at `as_of_date <= strptime(report_date)` (greatest prior)
#
# DuckDB ASOF LEFT JOIN keeps rows with no SOH match — those fall through
# to the market_data fallback tier. Equality predicate `soh.ticker =
# lookup.new_ticker` + inequality `soh.as_of_date <= qe` yields the latest
# prior stamp for each (ticker, quarter_end) pair.
#
# The per-row UPDATE then joins holdings_v2 back to resolved on
# (cusip, report_date). Multiple holdings_v2 rows with the same
# (cusip, report_date) key (intentional dup groups) all receive the same
# denominator — correct, since denominator is a ticker-level quantity.
_RESOLVED_CTE = f"""
    WITH lookup AS ({_LOOKUP_SQL}),
    keys AS (
        SELECT DISTINCT h.cusip, h.report_date,
               strptime(h.report_date, '%d-%b-%Y')::DATE AS quarter_end
          FROM holdings_v2 h
         WHERE h.report_date IS NOT NULL
           {{where_q_keys}}
    ),
    resolved AS (
        SELECT k.cusip, k.report_date, k.quarter_end,
               lookup.security_type_inferred,
               lookup.is_equity,
               lookup.new_ticker,
               lookup.price_live,
               lookup.md_shares_outstanding,
               lookup.md_float_shares,
               soh.shares     AS soh_shares,
               soh.as_of_date AS soh_as_of_date
          FROM keys k
          JOIN lookup ON lookup.cusip = k.cusip
          ASOF LEFT JOIN shares_outstanding_history soh
            ON soh.ticker = lookup.new_ticker
           AND soh.as_of_date <= k.quarter_end
    )
"""


# pct_of_so value + source expressions, used by both project and apply.
# Three-tier fallback, each distinctly audited (Phase 1c, 2026-04-19):
#   1. soh.shares > 0                       → 'soh_period_accurate'
#   2. md_shares_outstanding > 0            → 'market_data_so_latest'
#   3. md_float_shares > 0                  → 'market_data_float_latest'
#   4. otherwise                            → NULL
#
# Tier 3 is the "pct_of_float stored in pct_of_so column" case —
# semantic mixing kept visible in the audit flag so downstream readers
# (admin quality widgets, analytics) can filter it out or warn.
_POF_VALUE_EXPR = """
    CASE
        WHEN r.is_equity AND r.soh_shares             > 0
            THEN h.shares * 100.0 / r.soh_shares
        WHEN r.is_equity AND r.md_shares_outstanding  > 0
            THEN h.shares * 100.0 / r.md_shares_outstanding
        WHEN r.is_equity AND r.md_float_shares        > 0
            THEN h.shares * 100.0 / r.md_float_shares
        ELSE NULL
    END
"""
_POF_SOURCE_EXPR = """
    CASE
        WHEN r.is_equity AND r.soh_shares             > 0 THEN 'soh_period_accurate'
        WHEN r.is_equity AND r.md_shares_outstanding  > 0 THEN 'market_data_so_latest'
        WHEN r.is_equity AND r.md_float_shares        > 0 THEN 'market_data_float_latest'
        ELSE NULL
    END
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
            COUNT(*) FILTER (WHERE pct_of_so              IS NOT NULL) AS pof_clear
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
               pct_of_so              = NULL,
               pct_of_so_source       = NULL
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
    """Project Pass B per-column changes and projected post-state populations.

    Uses the period-accurate ASOF-resolved CTE (SOH → market_data fallback).
    Also returns per-source population counts and a staleness counter
    (SOH matches older than 60 days relative to quarter_end).
    """
    where_q = "AND h.quarter = ?" if quarter else ""
    where_q_keys = "AND h.quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    # Projection query uses the full resolved CTE. keys CTE needs its own
    # where_q binding (same quarter value when scoped).
    resolved_cte = _RESOLVED_CTE.format(where_q_keys=where_q_keys)
    row = con.execute(
        f"""
        {resolved_cte},
        proj AS (
            SELECT
                h.shares,
                h.ticker                 AS old_ticker,
                h.security_type_inferred AS old_sti,
                h.market_value_live      AS old_mvl,
                h.pct_of_so              AS old_pof,
                h.pct_of_so_source       AS old_pof_source,
                r.new_ticker,
                r.security_type_inferred AS new_sti,
                r.is_equity,
                r.soh_shares,
                r.soh_as_of_date,
                r.quarter_end,
                CASE WHEN r.is_equity AND r.price_live IS NOT NULL
                     THEN h.shares * r.price_live END               AS new_mvl,
                {_POF_VALUE_EXPR}                                   AS new_pof,
                {_POF_SOURCE_EXPR}                                  AS new_pof_source
            FROM holdings_v2 h
            JOIN resolved r
              ON r.cusip = h.cusip
             AND r.report_date = h.report_date
            WHERE 1=1 {where_q}
        )
        SELECT
            COUNT(*) AS rows_in_scope,
            COUNT(*) FILTER (WHERE old_ticker     IS DISTINCT FROM new_ticker)     AS ticker_changes,
            COUNT(*) FILTER (WHERE old_sti        IS DISTINCT FROM new_sti)        AS sti_changes,
            COUNT(*) FILTER (WHERE old_mvl        IS DISTINCT FROM new_mvl)        AS mvl_changes,
            COUNT(*) FILTER (WHERE old_pof        IS DISTINCT FROM new_pof)        AS pof_changes,
            COUNT(*) FILTER (WHERE old_pof_source IS DISTINCT FROM new_pof_source) AS pof_source_changes,
            COUNT(*) FILTER (WHERE new_ticker     IS NOT NULL)                      AS ticker_post,
            COUNT(*) FILTER (WHERE new_sti        IS NOT NULL)                      AS sti_post,
            COUNT(*) FILTER (WHERE new_mvl        IS NOT NULL)                      AS mvl_post,
            COUNT(*) FILTER (WHERE new_pof        IS NOT NULL)                      AS pof_post,
            COUNT(*) FILTER (WHERE new_pof_source = 'soh_period_accurate')          AS pof_source_soh,
            COUNT(*) FILTER (WHERE new_pof_source = 'market_data_so_latest')        AS pof_source_md_so,
            COUNT(*) FILTER (WHERE new_pof_source = 'market_data_float_latest')     AS pof_source_md_float,
            COUNT(*) FILTER (WHERE is_equity AND new_pof_source IS NULL)            AS pof_source_null_equity,
            COUNT(*) FILTER (
                WHERE new_pof_source = 'soh_period_accurate'
                  AND soh_as_of_date IS NOT NULL
                  AND (quarter_end - soh_as_of_date) > 60
            )                                                                       AS pof_stale_gt60
        FROM proj
        """,
        params + params,  # where_q_keys + where_q
    ).fetchone()
    return {
        "rows_in_scope":            row[0],
        "ticker_changes":           row[1],
        "sti_changes":              row[2],
        "mvl_changes":              row[3],
        "pof_changes":              row[4],
        "pof_source_changes":       row[5],
        "ticker_post":              row[6],
        "sti_post":                 row[7],
        "mvl_post":                 row[8],
        "pof_post":                 row[9],
        "pof_source_soh":           row[10],
        "pof_source_md_so":         row[11],
        "pof_source_md_float":      row[12],
        "pof_source_null_equity":   row[13],
        "pof_stale_gt60":           row[14],
    }


def _pass_b_apply(con, quarter: str | None) -> int:
    """Run Pass B: period-accurate ASOF UPDATE populating Group 3 + pof audit."""
    where_q = "AND h.quarter = ?" if quarter else ""
    where_q_keys = "AND h.quarter = ?" if quarter else ""
    params = [quarter] if quarter else []
    resolved_cte = _RESOLVED_CTE.format(where_q_keys=where_q_keys)
    # resolved is a CTE, so UPDATE ... FROM pulls from it. DuckDB supports
    # WITH ... UPDATE ... FROM <cte-name> syntax.
    con.execute(
        f"""
        {resolved_cte}
        UPDATE holdings_v2 AS h
           SET ticker                 = r.new_ticker,
               security_type_inferred = r.security_type_inferred,
               market_value_live      = CASE WHEN r.is_equity
                                              AND r.price_live IS NOT NULL
                                             THEN h.shares * r.price_live END,
               pct_of_so              = {_POF_VALUE_EXPR},
               pct_of_so_source       = {_POF_SOURCE_EXPR}
          FROM resolved r
         WHERE h.cusip = r.cusip
           AND h.report_date = r.report_date
           {where_q}
        """,
        params + params,  # where_q_keys + where_q
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
            COUNT(*) FILTER (WHERE pct_of_so              IS NOT NULL)
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
    log.line("Pass B — Main enrichment on holdings_v2 "
             "(cusip-keyed lookup + ASOF SOH)")
    log.line(f"  rows in scope (equity-classifiable cusip)   : {proj['rows_in_scope']:>14,}")
    log.line(f"  ticker       changes                        : {proj['ticker_changes']:>14,}")
    log.line(f"  sti          changes                        : {proj['sti_changes']:>14,}")
    log.line(f"  mvl          changes                        : {proj['mvl_changes']:>14,}")
    log.line(f"  pct_of_so    changes                        : {proj['pof_changes']:>14,}")
    log.line(f"  pof_source   changes                        : {proj['pof_source_changes']:>14,}")
    log.line("  projected post-state in scope:")
    log.line(f"    ticker                populated           : {proj['ticker_post']:>14,}")
    log.line(f"    sti                   populated           : {proj['sti_post']:>14,}")
    log.line(f"    mvl                   populated           : {proj['mvl_post']:>14,}")
    log.line(f"    pct_of_so             populated           : {proj['pof_post']:>14,}")
    # Tier distribution — every equity row lands in exactly one tier.
    # Sum of (soh + md_so + md_float + null_equity) == is_equity count.
    log.line("  tier distribution (equity rows):")
    log.line(f"    1. soh_period_accurate     (tier 1)       : {proj['pof_source_soh']:>14,}")
    log.line(f"    2. market_data_so_latest   (tier 2 SO)    : {proj['pof_source_md_so']:>14,}")
    log.line(f"    3. market_data_float_latest(tier 3 float) : {proj['pof_source_md_float']:>14,}")
    log.line(f"    4. NULL (equity, no denom) (tier 4)       : {proj['pof_source_null_equity']:>14,}")
    log.line(f"    SOH matches with staleness > 60 days      : {proj['pof_stale_gt60']:>14,}")


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
