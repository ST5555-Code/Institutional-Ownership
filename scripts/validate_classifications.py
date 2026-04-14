#!/usr/bin/env python3
"""
validate_classifications.py — validation gates after initial classification.

Run after scripts/build_classifications.py. BLOCK checks must all pass
before Session 2 (OpenFIGI retry). WARN checks print a warning but do
not fail the run. INFO checks print a count only.

Exit code:
    0 — all BLOCK checks passed
    1 — at least one BLOCK check failed

Usage:
    python3 scripts/validate_classifications.py            # prod
    python3 scripts/validate_classifications.py --staging
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402


# Each tuple: (label, sql, threshold, severity)
#   severity = 'BLOCK' | 'WARN' | 'INFO'
#   BLOCK:   count must equal `threshold` (typically 0) — hard failure
#   WARN:    value must be <= `threshold` — prints warning
#   INFO:    just prints the count (threshold ignored)
#
# securities_read_db is the prod DB (source data lives there). The
# "derivatives misclassified" check joins across DBs using ATTACH when
# running against staging (which has classifications but not securities
# beyond the reference copy).
CHECKS: list[tuple[str, str, object, str]] = [
    ("canonical_type IS NULL",
     "SELECT COUNT(*) FROM cusip_classifications WHERE canonical_type IS NULL",
     0, 'BLOCK'),

    ("is_permanent=TRUE AND is_priceable=TRUE",
     "SELECT COUNT(*) FROM cusip_classifications "
     "WHERE is_permanent = TRUE AND is_priceable = TRUE",
     0, 'BLOCK'),

    ("is_equity=TRUE AND is_permanent=TRUE",
     "SELECT COUNT(*) FROM cusip_classifications "
     "WHERE is_equity = TRUE AND is_permanent = TRUE",
     0, 'BLOCK'),

    ("derivatives misclassified as BOND/PREF",
     """SELECT COUNT(*) FROM cusip_classifications cc
        JOIN securities s ON cc.cusip = s.cusip
        WHERE s.security_type_inferred = 'derivative'
          AND cc.canonical_type IN ('BOND','PREF')""",
     0, 'BLOCK'),

    ("canonical_type=OTHER as pct of total",
     """SELECT ROUND(
            COUNT(*) FILTER (WHERE canonical_type = 'OTHER') * 100.0
            / NULLIF(COUNT(*), 0),
            2
        ) FROM cusip_classifications""",
     5.0, 'WARN'),

    ("retry_queue pending count",
     "SELECT COUNT(*) FROM cusip_retry_queue WHERE status = 'pending'",
     None, 'INFO'),

    # --- Post-OpenFIGI (Session 2) checks ---
    #
    # These gates only matter once the OpenFIGI retry has run and
    # ``normalize_securities.py`` has ported classifications into the
    # ``securities`` table.  Queries are written to degrade gracefully
    # when those steps haven't run yet — INFO-tier retry rates stay 0%,
    # BLOCK-tier columns are only checked when at least one row has the
    # new columns populated.

    ("retry_queue resolved rate (post-OpenFIGI)",
     """SELECT ROUND(
            COUNT(*) FILTER (WHERE status = 'resolved') * 100.0
            / NULLIF(COUNT(*), 0),
            1
        ) FROM cusip_retry_queue""",
     50.0, 'WARN_MIN'),

    ("retry_queue unmappable rate",
     """SELECT ROUND(
            COUNT(*) FILTER (WHERE status = 'unmappable') * 100.0
            / NULLIF(COUNT(*), 0),
            1
        ) FROM cusip_retry_queue""",
     30.0, 'WARN'),

    ("securities.canonical_type NULL after normalization",
     """SELECT CASE
            WHEN (SELECT COUNT(canonical_type) FROM securities) = 0 THEN 0
            ELSE (SELECT COUNT(*) FROM securities WHERE canonical_type IS NULL)
        END""",
     0, 'BLOCK_POST'),

    ("securities.is_equity NULL after normalization",
     """SELECT CASE
            WHEN (SELECT COUNT(canonical_type) FROM securities) = 0 THEN 0
            ELSE (SELECT COUNT(*) FROM securities WHERE is_equity IS NULL)
        END""",
     0, 'BLOCK_POST'),

    ("securities rows without classification match",
     """SELECT CASE
            WHEN (SELECT COUNT(canonical_type) FROM securities) = 0 THEN 0
            ELSE (
                SELECT COUNT(*) FROM securities s
                LEFT JOIN cusip_classifications cc ON s.cusip = cc.cusip
                WHERE cc.cusip IS NULL
            )
        END""",
     0, 'BLOCK_POST'),

    ("retry_queue pending after OpenFIGI",
     "SELECT COUNT(*) FROM cusip_retry_queue WHERE status = 'pending'",
     None, 'INFO'),
]


def _fmt(val) -> str:
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:.2f}"
    return f"{val:,}"


def run_checks(db_path: str) -> int:
    """Run every check. Return non-zero exit code on any BLOCK failure."""
    if not os.path.exists(db_path):
        print(f"ERROR: {db_path} does not exist", file=sys.stderr)
        return 2

    con = duckdb.connect(db_path, read_only=True)

    # If the caller gave us staging, attach prod so the derivatives-cross-
    # check can JOIN the authoritative securities table.
    attached_prod = False
    if os.path.abspath(db_path) != os.path.abspath(PROD_DB):
        con.close()
        con = duckdb.connect(db_path)
        con.execute(f"ATTACH '{PROD_DB}' AS prod_src (READ_ONLY)")
        attached_prod = True

    total = con.execute(
        "SELECT COUNT(*) FROM cusip_classifications"
    ).fetchone()[0]

    print("CLASSIFICATION VALIDATION")
    print("=" * 60)
    print(f"DB: {db_path}")
    print(f"Total classified: {total:,}")
    print()

    block_failures: list[str] = []
    warn_triggered: list[str] = []

    for label, sql, threshold, severity in CHECKS:
        q = sql
        # Rewrite the derivatives check to go through prod_src when attached.
        if attached_prod and "JOIN securities" in q:
            q = q.replace("JOIN securities s", "JOIN prod_src.securities s")
        try:
            val = con.execute(q).fetchone()[0]
        except Exception as e:
            print(f"  [{severity}] {label}: ERROR ({e})")
            if severity in ('BLOCK', 'BLOCK_POST'):
                block_failures.append(label)
            continue

        if severity == 'BLOCK':
            ok = val == threshold
            tag = "PASS" if ok else "FAIL"
            print(f"  [{tag}]  {label}: {_fmt(val)} (expected {threshold})")
            if not ok:
                block_failures.append(label)
        elif severity == 'BLOCK_POST':
            # Post-OpenFIGI block — gated on securities having canonical_type
            # populated (normalize_securities.py has run). Pre-normalize
            # runs treat these checks as informational.
            normalized = con.execute(
                "SELECT COUNT(canonical_type) FROM securities"
            ).fetchone()[0]
            if normalized == 0:
                print(f"  [SKIP]  {label}: securities not yet normalized")
                continue
            ok = val == threshold
            tag = "PASS" if ok else "FAIL"
            print(f"  [{tag}]  {label}: {_fmt(val)} (expected {threshold})")
            if not ok:
                block_failures.append(label)
        elif severity == 'WARN':
            ok = (val is not None and val <= threshold)
            tag = "PASS" if ok else "WARN"
            print(f"  [{tag}]  {label}: {_fmt(val)}%  "
                  f"(threshold ≤ {threshold}%)")
            if not ok:
                warn_triggered.append(f"{label}={_fmt(val)}")
        elif severity == 'WARN_MIN':
            # WARN if below minimum threshold (e.g., resolution rate >= 50%)
            ok = (val is not None and val >= threshold)
            tag = "PASS" if ok else "WARN"
            print(f"  [{tag}]  {label}: {_fmt(val)}%  "
                  f"(threshold ≥ {threshold}%)")
            if not ok:
                warn_triggered.append(f"{label}={_fmt(val)}")
        else:  # INFO
            print(f"  [INFO]  {label}: {_fmt(val)}")

    print()
    if block_failures:
        print(f"BLOCK FAILURES ({len(block_failures)}): "
              + ", ".join(block_failures))
        print("READY: NO")
        return 1

    if warn_triggered:
        print(f"WARNINGS: {', '.join(warn_triggered)}")
    print("READY: YES")
    con.close()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Validate CUSIP classifications")
    p.add_argument("--staging", action="store_true",
                   help="Validate staging DB")
    args = p.parse_args()

    db = STAGING_DB if args.staging else PROD_DB
    sys.exit(run_checks(db))


if __name__ == "__main__":
    main()
