#!/usr/bin/env python3
"""enrich_fund_holdings_v2.py — BLOCK-2 full-scope entity_id backfill for
`fund_holdings_v2`.

Context (archive/docs/SYSTEM_AUDIT_2026_04_17.md §10.1, archive/docs/SYSTEM_PASS2_2026_04_17.md §1):

  `_bulk_enrich_run` in `promote_nport.py:153-218` is run-scoped — it only
  enriches rows whose `series_id` was part of the current promote's
  `series_touched` set. Rows from prior promotes whose `series_id` *later*
  became resolvable in `entity_identifiers` are never revisited. As of
  2026-04-17, `fund_holdings_v2.entity_id` is 40.09% populated overall
  (0.18% for 2025-11), yet 76–94% of the NULL population is resolvable
  against the current entity MDM.

This script is the table-scoped backfill. The SQL join pattern and the
five-column write surface (entity_id, rollup_entity_id, dm_entity_id,
dm_rollup_entity_id, dm_rollup_name) are bit-for-bit identical to
`_bulk_enrich_run`; do not drift.

Scope:
  WHERE fund_holdings_v2.entity_id IS NULL
    AND fund_holdings_v2.series_id IN (
        SELECT identifier_value FROM entity_identifiers
         WHERE identifier_type = 'series_id'
           AND valid_to = DATE '9999-12-31')

Read-only on entity MDM tables. The only write surface is
`fund_holdings_v2`. Freshness stamped as `fund_holdings_v2_enrichment`
(mirrors the `holdings_v2_enrichment` name used by `enrich_holdings.py`).

CLI (PROCESS_RULES §9 — dry-run by default):
  python3 -u scripts/enrich_fund_holdings_v2.py                    # dry-run
  python3 -u scripts/enrich_fund_holdings_v2.py --apply            # real writes
  python3 -u scripts/enrich_fund_holdings_v2.py --limit 10000      # testing cap
  python3 -u scripts/enrich_fund_holdings_v2.py --report-month 2026-01

Restart safety (PROCESS_RULES §2): the `entity_id IS NULL` filter is the
natural restart-exclusion. Re-runs after partial completion pick up
exactly the still-NULL tail; a run that fully completes is a no-op on
the next invocation (idempotent).
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

# UPDATE + CHECKPOINT cadence (PROCESS_RULES §1). Batches group series_ids
# until cumulative NULL rows cross this threshold.
BATCH_ROWS = 500

# Per-month warn threshold on the unresolvable tail (PROCESS_RULES §5).
# This is genuinely unresolvable input (series not in entity_identifiers
# at all) — a WARNING, not a STOP, since backfill cannot fix input collapse.
UNRESOLVED_WARN_PCT = 5.0

REPORT_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Mirror of _bulk_enrich_run (promote_nport.py:153-218). The JOIN shape
# and the five-column SET list are bit-for-bit identical; deviation here
# would produce enrichment values inconsistent with the per-run path.
_LOOKUP_DDL = """
CREATE OR REPLACE TEMP TABLE _enrich_lookup AS
SELECT ei.identifier_value      AS series_id,
       ei.entity_id             AS entity_id,
       ec.rollup_entity_id      AS ec_rollup_entity_id,
       dm.rollup_entity_id      AS dm_rollup_entity_id,
       ea.alias_name            AS dm_rollup_name
  FROM entity_identifiers ei
  LEFT JOIN entity_rollup_history ec
         ON ec.entity_id = ei.entity_id
        AND ec.rollup_type = 'economic_control_v1'
        AND ec.valid_to = DATE '9999-12-31'
  LEFT JOIN entity_rollup_history dm
         ON dm.entity_id = ei.entity_id
        AND dm.rollup_type = 'decision_maker_v1'
        AND dm.valid_to = DATE '9999-12-31'
  LEFT JOIN entity_aliases ea
         ON ea.entity_id = ec.rollup_entity_id
        AND ea.is_preferred = TRUE
        AND ea.valid_to = DATE '9999-12-31'
 WHERE ei.identifier_type = 'series_id'
   AND ei.valid_to = DATE '9999-12-31'
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
        """Write a line to stdout and the log file."""
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
        if self._fh is not None:
            self._fh.write(msg + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """CLI parser — PROCESS_RULES §9 (dry-run default)."""
    parser = argparse.ArgumentParser(
        description=("BLOCK-2 full-scope entity_id backfill for "
                     "fund_holdings_v2. Default mode is dry-run. "
                     "Pass --apply for real writes."),
    )
    parser.add_argument("--apply", action="store_true",
                        help="Write to prod. Without it, the script is "
                             "a read-only projection.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip all writes (PROCESS_RULES §9). Overrides "
                             "--apply if both are set.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total NULL rows targeted (for testing).")
    parser.add_argument("--report-month", dest="report_month", default=None,
                        help="Scope to one report_month (YYYY-MM).")
    args = parser.parse_args()
    if args.dry_run:
        args.apply = False
    if args.report_month and not REPORT_MONTH_RE.match(args.report_month):
        raise SystemExit(
            f"--report-month must be YYYY-MM (got {args.report_month!r})")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be a positive integer")
    return args


def _open_connection(apply_mode: bool):
    """RW when applying, read-only for dry-run."""
    if apply_mode:
        return db.connect_write()
    return duckdb.connect(db.get_db_path(), read_only=True)


# ---------------------------------------------------------------------------
# Lookup + coverage
# ---------------------------------------------------------------------------

def _build_lookup(con) -> int:
    """Materialize the resolvable-series lookup as a TEMP table."""
    con.execute(_LOOKUP_DDL)
    return con.execute("SELECT COUNT(*) FROM _enrich_lookup").fetchone()[0]


def _coverage_by_month(con, report_month: str | None) -> list[tuple]:
    """Per-report_month breakdown of total, populated, NULL, resolvable
    NULL, unresolvable NULL. Joins against `_enrich_lookup` (must be built).
    """
    where = "WHERE fh.report_month = ?" if report_month else ""
    params = [report_month] if report_month else []
    return con.execute(
        f"""
        SELECT fh.report_month,
               COUNT(*)                                         AS total,
               COUNT(*) FILTER (WHERE fh.entity_id IS NOT NULL) AS populated,
               COUNT(*) FILTER (WHERE fh.entity_id IS NULL)     AS null_rows,
               COUNT(*) FILTER (WHERE fh.entity_id IS NULL
                                  AND e.series_id IS NOT NULL)  AS resolvable_null,
               COUNT(*) FILTER (WHERE fh.entity_id IS NULL
                                  AND e.series_id IS NULL)      AS unresolvable_null
          FROM fund_holdings_v2 fh
          LEFT JOIN _enrich_lookup e ON e.series_id = fh.series_id
          {where}
         GROUP BY fh.report_month
         ORDER BY fh.report_month
        """,
        params,
    ).fetchall()


def _print_coverage(log: _Tee, rows: list[tuple], phase: str) -> None:
    """Emit a coverage table for one phase (pre- or post-backfill)."""
    log.line(f"Coverage — {phase}:")
    header = ("  report_month |      total |   populated |  null_rows "
              "| resolvable |  unresolvable |  pre-cov% | post-cov%")
    log.line(header)
    log.line("  " + "-" * (len(header) - 2))
    t_tot = t_pop = t_null = t_res = t_unres = 0
    for (rm, total, populated, nulls, resolvable, unresolvable) in rows:
        pre = (100.0 * populated / total) if total else 0.0
        post = (100.0 * (populated + resolvable) / total) if total else 0.0
        log.line(
            f"  {str(rm):12} | {total:>10,} | {populated:>11,} "
            f"| {nulls:>10,} | {resolvable:>10,} | {unresolvable:>13,} "
            f"| {pre:>7.2f}% | {post:>7.2f}%"
        )
        t_tot += total
        t_pop += populated
        t_null += nulls
        t_res += resolvable
        t_unres += unresolvable
    if t_tot:
        pre = 100.0 * t_pop / t_tot
        post = 100.0 * (t_pop + t_res) / t_tot
        log.line("  " + "-" * (len(header) - 2))
        log.line(
            f"  {'TOTAL':12} | {t_tot:>10,} | {t_pop:>11,} "
            f"| {t_null:>10,} | {t_res:>10,} | {t_unres:>13,} "
            f"| {pre:>7.2f}% | {post:>7.2f}%"
        )
    log.line("")


def _warn_unresolved(log: _Tee, rows: list[tuple]) -> None:
    """PROCESS_RULES §5 — warn (not stop) when unresolvable > 5% of a month."""
    over = []
    for (rm, total, _pop, _nulls, _res, unresolvable) in rows:
        if not total:
            continue
        pct = 100.0 * unresolvable / total
        if pct > UNRESOLVED_WARN_PCT:
            over.append((rm, pct, unresolvable, total))
    if not over:
        return
    log.line(
        f"WARNING (PROCESS_RULES §5): unresolvable tail > "
        f"{UNRESOLVED_WARN_PCT:.0f}% of rows on these months "
        "(true input collapse; backfill cannot fix — MDM work required):"
    )
    for (rm, pct, unres, total) in over:
        log.line(f"  {rm}: {pct:5.2f}%  ({unres:,} / {total:,})")
    log.line("")


# ---------------------------------------------------------------------------
# Target set + batching
# ---------------------------------------------------------------------------

def _target_series(con, report_month: str | None,
                   limit: int | None) -> list[tuple[str, int]]:
    """Return [(series_id, null_row_count)] for resolvable-NULL series.

    Natural restart-exclusion (PROCESS_RULES §2): counts only
    `entity_id IS NULL` rows in a resolvable series, so a re-run after a
    partial completion sees a shorter list.
    """
    where = "AND fh.report_month = ?" if report_month else ""
    params = [report_month] if report_month else []
    rows = con.execute(
        f"""
        SELECT fh.series_id, COUNT(*) AS null_rows
          FROM fund_holdings_v2 fh
          JOIN _enrich_lookup e ON e.series_id = fh.series_id
         WHERE fh.entity_id IS NULL
           {where}
         GROUP BY fh.series_id
         ORDER BY fh.series_id
        """,
        params,
    ).fetchall()
    if limit is None:
        return rows
    truncated = []
    acc = 0
    for sid, cnt in rows:
        if acc >= limit:
            break
        truncated.append((sid, cnt))
        acc += cnt
    return truncated


def _group_batches(series_counts, batch_rows):
    """Group (series_id, null_rows) into batches where cumulative rows >=
    `batch_rows` (final batch may be smaller). A single series larger
    than the threshold gets its own batch.
    """
    batch = []
    total = 0
    for sid, cnt in series_counts:
        batch.append(sid)
        total += cnt
        if total >= batch_rows:
            yield batch, total
            batch = []
            total = 0
    if batch:
        yield batch, total


def _apply_batch(con, series_ids: list[str],
                 report_month: str | None) -> int:
    """Run one batch UPDATE. Returns rows updated (pre − post NULL count).

    The SET list and JOIN semantics mirror `_bulk_enrich_run` in
    `promote_nport.py:153-218`. The added `fh.entity_id IS NULL` filter
    is the idempotency guarantee: a second pass matches zero rows.
    """
    placeholders = ",".join("?" * len(series_ids))
    month_clause = "AND fh.report_month = ?" if report_month else ""
    params = list(series_ids) + (
        [report_month] if report_month else [])
    before = con.execute(
        f"""
        SELECT COUNT(*) FROM fund_holdings_v2 fh
         WHERE fh.entity_id IS NULL
           AND fh.series_id IN ({placeholders})
           {month_clause}
        """,
        params,
    ).fetchone()[0]
    con.execute(
        f"""
        UPDATE fund_holdings_v2 AS fh
           SET entity_id           = e.entity_id,
               rollup_entity_id    = e.ec_rollup_entity_id,
               dm_entity_id        = e.entity_id,
               dm_rollup_entity_id = e.dm_rollup_entity_id,
               dm_rollup_name      = e.dm_rollup_name
          FROM _enrich_lookup AS e
         WHERE fh.series_id = e.series_id
           AND fh.entity_id IS NULL
           AND fh.series_id IN ({placeholders})
           {month_clause}
        """,
        params,
    )
    after = con.execute(
        f"""
        SELECT COUNT(*) FROM fund_holdings_v2 fh
         WHERE fh.entity_id IS NULL
           AND fh.series_id IN ({placeholders})
           {month_clause}
        """,
        params,
    ).fetchone()[0]
    return before - after


# ---------------------------------------------------------------------------
# Orchestrate
# ---------------------------------------------------------------------------

def _dry_run_summary(log: _Tee, targets, total_null_rows) -> None:
    """Emit the dry-run what-would-happen block."""
    batch_count = sum(1 for _ in _group_batches(targets, BATCH_ROWS))
    log.line("DRY-RUN projection:")
    log.line(f"  series in target set  : {len(targets):>12,}")
    log.line(f"  NULL rows targeted    : {total_null_rows:>12,}")
    log.line(f"  UPDATE batches        : {batch_count:>12,} "
             f"(~{BATCH_ROWS} rows each)")
    log.line("")


def _run_backfill(con, log: _Tee, args) -> int:
    """Execute the backfill loop. Returns rows updated (0 on dry-run)."""
    targets = _target_series(con, args.report_month, args.limit)
    total_null_rows = sum(cnt for _, cnt in targets)
    log.line(f"Target set: {len(targets):,} series, "
             f"{total_null_rows:,} NULL rows to update")
    if args.limit is not None:
        log.line(f"  --limit {args.limit:,} active — target list truncated")
    log.line("")

    if not targets:
        log.line("Nothing to do — no resolvable-NULL series in scope.")
        return 0

    if not args.apply:
        _dry_run_summary(log, targets, total_null_rows)
        return 0

    updated = 0
    processed_rows = 0
    t0 = time.time()
    last_progress = 0
    for batch_series, batch_rows_expected in _group_batches(
            targets, BATCH_ROWS):
        updated += _apply_batch(con, batch_series, args.report_month)
        processed_rows += batch_rows_expected
        con.execute("CHECKPOINT")
        if processed_rows - last_progress >= BATCH_ROWS:
            elapsed = time.time() - t0
            rate = processed_rows / elapsed if elapsed > 0 else 0.0
            remaining = max(0, total_null_rows - processed_rows)
            eta_min = (remaining / rate / 60.0) if rate > 0 else 0.0
            log.line(
                f"  progress: {processed_rows:>11,} / {total_null_rows:,} "
                f"rows | updated {updated:>11,} | "
                f"{rate:>7.0f} rows/s | ETA {eta_min:6.1f}m"
            )
            last_progress = processed_rows
    elapsed = time.time() - t0
    rate = (updated / elapsed) if elapsed > 0 else 0.0
    log.line(f"  done: {updated:,} rows updated in {elapsed:.1f}s "
             f"({rate:.0f} rows/s)")
    return updated


def main() -> None:
    """Entry point — dry-run by default, --apply for writes."""
    args = _parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    mode = "apply" if args.apply else "dryrun"
    log_path = os.path.join(
        LOG_DIR, f"enrich_fund_holdings_v2_{mode}_{ts}.log")

    with _Tee(log_path) as log:
        log.line("enrich_fund_holdings_v2.py — "
                 f"{'APPLY' if args.apply else 'DRY-RUN'} mode")
        log.line(f"  db            : {db.get_db_path()}")
        log.line(f"  report-month  : {args.report_month or 'ALL'}")
        log.line(f"  limit         : "
                 f"{args.limit if args.limit is not None else 'none'}")
        log.line(f"  log           : {log_path}")
        log.line("=" * 78)

        con = _open_connection(args.apply)
        try:
            lookup_n = _build_lookup(con)
            log.line(f"Resolvable series_id count in entity_identifiers: "
                     f"{lookup_n:,}")
            log.line("")

            pre = _coverage_by_month(con, args.report_month)
            _print_coverage(log, pre, "pre-backfill (post-cov% = "
                                      "projected after full backfill)")
            _warn_unresolved(log, pre)

            updated = _run_backfill(con, log, args)

            if args.apply:
                post = _coverage_by_month(con, args.report_month)
                _print_coverage(log, post, "post-backfill (actual)")
                db.record_freshness(
                    con, "fund_holdings_v2_enrichment",
                    row_count=updated)
                log.line("data_freshness('fund_holdings_v2_enrichment') "
                         f"stamped, row_count={updated:,}")
            else:
                log.line("=" * 78)
                log.line("DRY-RUN complete — no writes performed. "
                         "Re-run with --apply after review.")
        finally:
            con.close()


if __name__ == "__main__":
    main()
