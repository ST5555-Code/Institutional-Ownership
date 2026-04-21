#!/usr/bin/env python3
"""
resolve_long_tail.py — Phase 3: Batch resolve unmatched CIKs via SEC EDGAR.

Targets entities with:
  - CIK identifier
  - Self-rollup (no parent relationship)
  - Classification = 'unknown'
  - Not seeded from PARENT_SEEDS

For each CIK, calls SEC EDGAR submissions API to get company metadata,
then attempts:
  1. Fuzzy match against existing parent entity aliases → parent_brand relationship
  2. SIC-based classification → reclassify from 'unknown' to financial category
  3. Update entity's preferred alias with the SEC-registered name

Usage:
  python3 scripts/resolve_long_tail.py --staging --limit 100   # test run
  python3 scripts/resolve_long_tail.py --staging --all          # full run
  python3 scripts/resolve_long_tail.py --staging --limit 50 --dry-run  # no DB writes

Rate limit: 5 req/s max. SEC API identity: serge.tismen@gmail.com
"""
from __future__ import annotations

# pylint: disable=too-many-locals,too-many-statements,too-many-branches,broad-exception-caught

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure progress output is visible in background/redirected runs
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
elif not sys.stdout.isatty():
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402
import entity_sync  # noqa: E402
from config import SEC_HEADERS  # noqa: E402

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
RESULTS_CSV = LOG_DIR / "phase3_resolution_results.csv"
UNMATCHED_CSV = LOG_DIR / "phase3_unmatched.csv"

SEC_RATE_LIMIT = 0.2  # 5 req/s = 200ms between requests


def get_unresolved_ciks(con) -> list[tuple]:
    """Return list of (cik, entity_id, canonical_name) for unresolved entities."""
    return con.execute("""
        SELECT ei.identifier_value AS cik, e.entity_id, e.canonical_name
        FROM entity_identifiers ei
        JOIN entities e ON e.entity_id = ei.entity_id
        JOIN entity_rollup_history erh
          ON erh.entity_id = e.entity_id
          AND erh.rollup_type = 'economic_control_v1'
          AND erh.valid_to = DATE '9999-12-31'
        JOIN entity_classification_history ech
          ON ech.entity_id = e.entity_id
          AND ech.valid_to = DATE '9999-12-31'
        WHERE ei.identifier_type = 'cik'
          AND ei.valid_to = DATE '9999-12-31'
          AND erh.rule_applied = 'self'
          AND ech.classification = 'unknown'
          AND e.created_source != 'PARENT_SEEDS'
        ORDER BY ei.identifier_value
    """).fetchall()


def get_already_resolved(con) -> set[str]:
    """
    CIKs that were resolved in a prior run. An entity is 'resolved' if it
    either has a non-self rollup or a non-unknown classification, indicating
    a prior resolve_long_tail run already processed it.
    """
    # Entities that USED to be self-rollup but now have a parent_brand rollup
    resolved_via_parent = con.execute("""
        SELECT ei.identifier_value
        FROM entity_identifiers ei
        JOIN entity_rollup_history erh ON erh.entity_id = ei.entity_id
          AND erh.rollup_type = 'economic_control_v1'
          AND erh.valid_to = DATE '9999-12-31'
          AND erh.rule_applied = 'parent_brand'
        WHERE ei.identifier_type = 'cik' AND ei.valid_to = DATE '9999-12-31'
    """).fetchall()
    return {r[0] for r in resolved_via_parent}


def main():
    ap = argparse.ArgumentParser(description="Phase 3: resolve long-tail CIKs via SEC EDGAR")
    ap.add_argument("--staging", action="store_true", required=True, help="Target staging DB")
    ap.add_argument("--limit", type=int, default=500, help="Max CIKs to process (default 500)")
    ap.add_argument("--all", action="store_true", help="Process ALL unresolved CIKs (overrides --limit)")
    ap.add_argument("--dry-run", action="store_true", help="Resolve + log but do not write to DB")
    args = ap.parse_args()

    db.set_staging_mode(True)
    con = db.connect_write()

    print("Phase 3 — resolve_long_tail.py")
    print(f"  DB: {db.get_db_path()}")
    print(f"  dry_run: {args.dry_run}")
    print(f"  started: {datetime.now().isoformat()}")

    # Load targets
    unresolved = get_unresolved_ciks(con)
    already = get_already_resolved(con)
    targets = [(cik, eid, name) for cik, eid, name in unresolved if cik not in already]

    if not args.all:
        targets = targets[:args.limit]

    print(f"  unresolved: {len(unresolved)}, already resolved: {len(already)}, targets: {len(targets)}")

    if not targets:
        print("  Nothing to resolve.")
        con.close()
        return

    # Session for connection reuse
    import requests
    session = requests.Session()
    session.headers.update(SEC_HEADERS)

    # Counters
    resolved = 0
    parent_matched = 0
    sic_classified = 0
    failed = 0
    already_matched_count = 0

    results = []
    unmatched_rows = []
    t0 = time.time()

    # Pre-load alias cache once for the entire batch (Bug 6: eliminates O(n×m) DB queries)
    alias_cache = entity_sync.build_alias_cache(con) if not args.dry_run else None

    for i, (cik, entity_id, canonical_name) in enumerate(targets):
        # Progress
        if (i + 1) % 25 == 0 or i < 3:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(
                f"  [{i+1}/{len(targets)}] "
                f"resolved={resolved} matched={parent_matched} "
                f"classified={sic_classified} failed={failed} "
                f"({rate:.1f} CIK/s)"
            )

        # Rate limit
        time.sleep(SEC_RATE_LIMIT)

        # Resolve via SEC
        info = entity_sync.resolve_cik_via_sec(cik, session=session)
        if not info:
            failed += 1
            results.append({
                "cik": cik, "entity_id": entity_id, "canonical_name": canonical_name,
                "sec_name": None, "sic": None, "sic_desc": None, "category": None,
                "state": None, "parent_matched": False, "parent_name": None,
                "match_score": 0, "sic_classified": False, "new_classification": None,
                "status": "sec_lookup_failed",
            })
            continue

        resolved += 1
        sec_name = info.get("name") or canonical_name
        sic = info.get("sic")
        sic_desc = info.get("sicDescription")

        row = {
            "cik": cik, "entity_id": entity_id, "canonical_name": canonical_name,
            "sec_name": sec_name, "sic": sic, "sic_desc": sic_desc,
            "category": info.get("category"), "state": info.get("stateOfIncorporation"),
            "parent_matched": False, "parent_name": None, "match_score": 0,
            "sic_classified": False, "new_classification": None, "status": "resolved",
        }

        if not args.dry_run:
            # Attempt parent match
            match = entity_sync.attempt_parent_match(con, entity_id, sec_name,
                                                      alias_cache=alias_cache)
            if match.get("matched"):
                row["parent_matched"] = True
                row["parent_name"] = match.get("parent_name")
                row["match_score"] = match.get("score", 0)
                if not match.get("skipped"):
                    parent_matched += 1
                else:
                    already_matched_count += 1
                row["status"] = "parent_matched"
            else:
                row["match_score"] = match.get("best_score", 0)
                unmatched_rows.append({
                    "cik": cik, "entity_id": entity_id, "canonical_name": canonical_name,
                    "sec_name": sec_name, "best_parent": match.get("best_name"),
                    "best_score": match.get("best_score", 0),
                })

            # SIC classification
            if entity_sync.update_classification_from_sic(con, entity_id, sic):
                sic_classified += 1
                row["sic_classified"] = True
                row["new_classification"] = entity_sync.classify_from_sic(sic)
                row["status"] = "classified" if not row["parent_matched"] else "parent_matched+classified"

            # Update preferred alias with SEC-registered name if different
            if sec_name and sec_name != canonical_name:
                con.execute("""
                    INSERT INTO entity_aliases
                      (entity_id, alias_name, alias_type, is_preferred, preferred_key,
                       source_table, is_inferred, valid_from, valid_to)
                    VALUES (?, ?, 'filing', FALSE, NULL, 'SEC_EDGAR', FALSE,
                            CURRENT_DATE, DATE '9999-12-31')
                    ON CONFLICT DO NOTHING
                """, [entity_id, sec_name])
        else:
            row["status"] = "dry_run"

        results.append(row)

    elapsed = time.time() - t0

    # Write results CSV
    if results:
        fieldnames = list(results[0].keys())
        with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(results)

    # Write unmatched CSV
    if unmatched_rows:
        with open(UNMATCHED_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(unmatched_rows[0].keys()))
            w.writeheader()
            w.writerows(unmatched_rows)

    # Summary
    print(f"\n{'='*60}")
    print("PHASE 3 RESOLUTION SUMMARY")
    print(f"{'='*60}")
    print(f"  Targets processed:  {len(targets)}")
    print(f"  SEC resolved:       {resolved} ({resolved/len(targets)*100:.1f}%)")
    print(f"  SEC lookup failed:  {failed}")
    print(f"  Parent matched:     {parent_matched}")
    print(f"  SIC classified:     {sic_classified}")
    print(f"  Unmatched:          {len(unmatched_rows)}")
    print(f"  Already matched:    {already_matched_count}")
    print(f"  Elapsed:            {elapsed:.1f}s ({len(targets)/elapsed:.1f} CIK/s)")
    print(f"  Results:            {RESULTS_CSV}")
    print(f"  Unmatched log:      {UNMATCHED_CSV}")
    print(f"{'='*60}")

    con.close()


if __name__ == "__main__":
    main()
