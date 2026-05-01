#!/usr/bin/env python3
"""reclassify_with_new_patterns.py — PR-2 N-PORT classifier sweep.

Apply the extended INDEX_PATTERNS regex (PR-2 additions: QQQ, Target
Retirement|Date, leveraged/inverse ETFs) against every series in
fund_universe and reclassify funds whose name now matches but were
classified as 'equity' / 'balanced' / 'multi_asset' under the original
keyword set.

Mode flags:

  --dry-run   (default) — emit a CSV of candidates. No DB writes.
  --confirm             — execute the UPDATEs against prod fund_universe
                          + fund_holdings_v2.

Stop conditions (dry-run):

  * candidate count > 200            → exit 2 (regex too broad).
  * any name looks discretionary     → exit 3 (audit required).

Both stop conditions print the offending rows. The user reviews the
CSV, then re-runs with --confirm if clean.

Outputs:

  * ``docs/findings/pr2_reclassification_dryrun.csv``
      columns: series_id, fund_name, family_name,
               current_fund_strategy, proposed_fund_strategy,
               total_net_assets, triggering_pattern.

The CSV is rewritten on every dry-run.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from typing import List, Tuple

import duckdb

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB  # noqa: E402
from pipeline.nport_parsers import INDEX_PATTERNS  # noqa: E402

# Patterns that were ADDED in PR-2. The dry-run flags only candidates
# whose name matches one of these (rather than any INDEX_PATTERNS hit) so
# the report cleanly attributes the reclassification to the new regex.
PR2_ADDED_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("qqq",                re.compile(r"\bqqq\b", re.IGNORECASE)),
    ("target_retirement",  re.compile(r"\btarget\s*retirement\b", re.IGNORECASE)),
    ("target_date",        re.compile(r"\btarget\s*date\b", re.IGNORECASE)),
    ("leveraged_digit_x",  re.compile(r"\b\d+(?:\.\d+)?x\b", re.IGNORECASE)),
    ("proshares",          re.compile(r"\bproshares\b", re.IGNORECASE)),
    ("profund",            re.compile(r"\bprofund\b", re.IGNORECASE)),
    ("direxion",           re.compile(r"\bdirexion\b", re.IGNORECASE)),
    ("daily_inverse",      re.compile(r"\bdaily\s*inverse\b", re.IGNORECASE)),
    ("inverse",            re.compile(r"\binverse\b", re.IGNORECASE)),
]

# Heuristic active-fund tokens. If a candidate fund name contains any of
# these, the dry-run aborts so the user can review (Phase 3 STOP rule).
# `discretionary` is matched only when NOT preceded by "consumer" — the
# GICS sector name "Consumer Discretionary" is widely used in passive
# sector ETFs (ProShares Ultra Consumer Discretionary, Direxion Consumer
# Discretionary Bull 3X, etc.) and is not a discretionary-management
# signal.
DISCRETIONARY_TOKENS = re.compile(
    r"\b(active|fundamental|long[- ]short|concentrated)\b"
    r"|(?<!consumer\s)\bdiscretionary\b",
    re.IGNORECASE,
)

# Strategies eligible for PR-2 sweep. PR-1e renamed 'index' to 'passive';
# we only flip to 'passive' from these *active-bucket* values.
SWEEP_FROM = ("equity", "balanced", "multi_asset")

# Output CSV path.
DRY_RUN_CSV = os.path.join(
    BASE_DIR, "docs", "findings", "pr2_reclassification_dryrun.csv",
)

# Hard cap per plan Phase 3 STOP condition. Plan author estimated 100-150;
# actual dry-run yielded ~253 legitimate candidates after the ProShares-brand
# refinement (116 target-date + 63 ProFunds + leveraged/inverse + QQQ). User
# waived the original 200 cap on 2026-05-01 after manual audit. The cap is
# kept as a 300 upper bound to catch any future regex regressions.
HARD_CAP = 300


def _first_pattern(name: str) -> str:
    """Return the name of the first PR-2 pattern that matches ``name``,
    or an empty string. Order in PR2_ADDED_PATTERNS dictates priority."""
    for tag, rx in PR2_ADDED_PATTERNS:
        if rx.search(name):
            return tag
    return ""


def _query_candidates(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = con.execute(
        """
        SELECT series_id, fund_name, family_name, fund_strategy,
               total_net_assets
          FROM fund_universe
         WHERE fund_strategy IN ('equity', 'balanced', 'multi_asset')
        """
    ).fetchall()

    out: list[dict] = []
    for series_id, fund_name, family_name, fund_strategy, tna in rows:
        name = fund_name or ""
        # Must match the FULL INDEX_PATTERNS regex (not just the PR-2 set)
        # so we never over-fire on something that the original regex would
        # not have caught either; then filter to PR-2 pattern attribution.
        if not INDEX_PATTERNS.search(name):
            continue
        tag = _first_pattern(name)
        if not tag:
            continue
        out.append({
            "series_id": series_id,
            "fund_name": name,
            "family_name": family_name or "",
            "current_fund_strategy": fund_strategy,
            "proposed_fund_strategy": "passive",
            "total_net_assets": tna or 0.0,
            "triggering_pattern": tag,
        })
    out.sort(key=lambda r: -float(r["total_net_assets"] or 0.0))
    return out


def _write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "series_id", "fund_name", "family_name",
                "current_fund_strategy", "proposed_fund_strategy",
                "total_net_assets", "triggering_pattern",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _summarise(rows: list[dict]) -> None:
    by_pattern: dict[str, list[dict]] = {}
    for r in rows:
        by_pattern.setdefault(r["triggering_pattern"], []).append(r)
    total_aum = sum(float(r["total_net_assets"] or 0.0) for r in rows)
    print(f"\nCandidates: {len(rows)}")
    print(f"Total AUM:  ${total_aum/1e9:,.1f}B")
    print(f"\nBy triggering pattern:")
    for pat, group in sorted(
        by_pattern.items(), key=lambda kv: -len(kv[1]),
    ):
        aum = sum(float(r["total_net_assets"] or 0.0) for r in group)
        print(f"  {pat:20s} {len(group):4d} funds   ${aum/1e9:>8,.1f}B")
    print(f"\nTop 10 by AUM:")
    for r in rows[:10]:
        print(
            f"  {r['series_id']:10s} "
            f"{(r['fund_name'] or '')[:50]:50s} "
            f"{r['current_fund_strategy']:10s} → passive  "
            f"(${float(r['total_net_assets'] or 0)/1e9:>6,.1f}B, "
            f"{r['triggering_pattern']})"
        )


def _check_stop_conditions(rows: list[dict]) -> int:
    """Return exit code (0 ok, 2 too-many, 3 discretionary)."""
    if len(rows) > HARD_CAP:
        print(
            f"\n*** STOP: candidate count {len(rows)} exceeds the hard "
            f"cap of {HARD_CAP}. A regex is too broad. Aborting.",
            file=sys.stderr,
        )
        return 2
    discretionary_hits = [
        r for r in rows
        if DISCRETIONARY_TOKENS.search(r["fund_name"] or "")
    ]
    if discretionary_hits:
        print(
            f"\n*** STOP: {len(discretionary_hits)} candidate(s) carry a "
            f"discretionary token (Active/Fundamental/Long-Short/...). "
            f"Aborting for user review:",
            file=sys.stderr,
        )
        for r in discretionary_hits[:20]:
            print(
                f"  {r['series_id']:10s} {r['fund_name']:60s} "
                f"({r['triggering_pattern']})",
                file=sys.stderr,
            )
        return 3
    return 0


def _execute_updates(
    con: duckdb.DuckDBPyConnection, series_ids: list[str],
) -> dict[str, int]:
    """Run the Phase 4 UPDATEs. Returns a dict of {table: rows_affected}."""
    if not series_ids:
        return {"fund_universe": 0, "fund_holdings_v2": 0}

    placeholders = ",".join("?" * len(series_ids))

    pre_u = con.execute(
        f"SELECT COUNT(*) FROM fund_universe "
        f"WHERE series_id IN ({placeholders})",
        series_ids,
    ).fetchone()[0]
    pre_h = con.execute(
        f"SELECT COUNT(*) FROM fund_holdings_v2 "
        f"WHERE series_id IN ({placeholders})",
        series_ids,
    ).fetchone()[0]

    con.execute(
        f"""
        UPDATE fund_universe
           SET fund_strategy       = 'passive',
               fund_category       = 'passive',
               is_actively_managed = FALSE
         WHERE series_id IN ({placeholders})
        """,
        series_ids,
    )
    con.execute(
        f"""
        UPDATE fund_holdings_v2
           SET fund_strategy = 'passive'
         WHERE series_id IN ({placeholders})
        """,
        series_ids,
    )
    con.execute("CHECKPOINT")
    return {"fund_universe": int(pre_u), "fund_holdings_v2": int(pre_h)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PR-2 reclassification with extended INDEX_PATTERNS",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Execute UPDATEs (default is dry-run).",
    )
    parser.add_argument(
        "--db", default=PROD_DB,
        help="Path to prod DuckDB file (default: data/13f.duckdb).",
    )
    args = parser.parse_args()

    con = duckdb.connect(args.db, read_only=not args.confirm)
    try:
        rows = _query_candidates(con)
        _write_csv(rows, DRY_RUN_CSV)
        print(f"Dry-run CSV → {DRY_RUN_CSV}")
        _summarise(rows)

        stop = _check_stop_conditions(rows)
        if stop:
            return stop

        if not args.confirm:
            print(
                f"\nDry-run complete. Re-run with --confirm to execute "
                f"UPDATEs against {args.db}.",
            )
            return 0

        print(f"\n*** EXECUTING UPDATEs against {args.db} ***")
        series_ids = [r["series_id"] for r in rows]
        affected = _execute_updates(con, series_ids)
        print(
            f"  fund_universe:    {affected['fund_universe']} rows updated\n"
            f"  fund_holdings_v2: {affected['fund_holdings_v2']} rows updated"
        )
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
