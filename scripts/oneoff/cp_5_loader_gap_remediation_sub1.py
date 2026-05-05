"""cp-5-loader-gap-remediation-sub1: link 23 fund_ciks to existing entities.

Closes the linkable portion of the 84,363-row entity_id IS NULL cohort
in fund_holdings_v2 (Bundle B Phase 2.4 / Bundle C §7.5 Gap 1).

Phases:
  --validate : Phase 1 read-only cohort revalidation + classification.
  --dry-run  : Phase 2 manifest of linkable updates.
  --confirm  : Phase 3 execute UPDATE in a single tx with 6 hard guards.

Usage:
  python scripts/oneoff/cp_5_loader_gap_remediation_sub1.py --validate
  python scripts/oneoff/cp_5_loader_gap_remediation_sub1.py --dry-run
  python scripts/oneoff/cp_5_loader_gap_remediation_sub1.py --confirm
"""

import argparse
import csv
import sys
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DB = BASE_DIR / "data" / "13f.duckdb"
WORKING = BASE_DIR / "data" / "working"

CIK_BREAKDOWN_CSV = WORKING / "cp-5-loader-gap-cik-breakdown.csv"
CLASSIFICATION_CSV = WORKING / "cp-5-loader-gap-classification.csv"
MANIFEST_CSV = WORKING / "cp-5-loader-gap-remediation-sub1-manifest.csv"

EXPECTED_COHORT_ROWS = 84_363
EXPECTED_COHORT_AUM_B = 418.5
EXPECTED_COHORT_CIKS = 50
COHORT_DRIFT_TOLERANCE = 0.10

# Carve-outs applied per chat decision: fund_ciks whose pre-existing
# entity_identifiers linkage violates the canonical shape. Routed to sub-PR 2.
CARVE_OUTS = {
    "0000945908": {
        "reason": "linked to FMR LLC eid=10443 (parent adviser, 2 open CIKs); "
                  "violates 1:1 fund-cik shape; routed to sub-PR 2",
    },
}

# Relaxed canonical-shape check (chat decision May 5):
#   entity_type IN ('fund','institution') AND exactly 1 open CIK identifier
ALLOWED_TYPES = ("fund", "institution")


def _connect(read_only=True):
    return duckdb.connect(str(DB), read_only=read_only)


def _within_tolerance(actual, expected, tol=COHORT_DRIFT_TOLERANCE):
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / expected <= tol


def phase1_validate():
    print("=" * 72)
    print("PHASE 1 — read-only cohort revalidation + classification")
    print("=" * 72)
    con = _connect(read_only=True)

    # Step 1a: cohort total
    n_rows, aum_b, n_ciks = con.execute(
        """
        SELECT
          COUNT(*),
          COALESCE(SUM(market_value_usd), 0) / 1e9,
          COUNT(DISTINCT fund_cik)
        FROM fund_holdings_v2
        WHERE entity_id IS NULL AND is_latest = TRUE
        """
    ).fetchone()
    print(f"\n[1a] cohort: rows={n_rows:,} aum_b={aum_b:,.2f} n_ciks={n_ciks}")
    print(
        f"     expected: ~{EXPECTED_COHORT_ROWS:,} rows / ~${EXPECTED_COHORT_AUM_B}B / "
        f"~{EXPECTED_COHORT_CIKS} ciks"
    )

    drift_ok = (
        _within_tolerance(n_rows, EXPECTED_COHORT_ROWS)
        and _within_tolerance(aum_b, EXPECTED_COHORT_AUM_B)
    )
    if not drift_ok:
        print(
            f"[1a] ABORT: cohort drift > {COHORT_DRIFT_TOLERANCE * 100:.0f}% "
            f"vs Bundle B baseline"
        )
        sys.exit(2)
    print("[1a] OK — cohort stable within tolerance")

    # Step 1b: per-CIK breakdown
    rows = con.execute(
        """
        SELECT
          fund_cik,
          MIN(fund_name) AS sample_fund_name,
          COUNT(*) AS n_rows,
          COALESCE(SUM(market_value_usd), 0) / 1e9 AS aum_billions
        FROM fund_holdings_v2
        WHERE entity_id IS NULL AND is_latest = TRUE
        GROUP BY fund_cik
        ORDER BY aum_billions DESC
        """
    ).fetchall()
    print(f"\n[1b] {len(rows)} distinct fund_ciks in cohort")
    print("     top 50:")
    print(f"     {'fund_cik':<14}{'n_rows':>8}{'aum_b':>12}  sample_fund_name")
    for r in rows[:50]:
        print(
            f"     {str(r[0]):<14}{r[2]:>8,}{r[3]:>12,.2f}  "
            f"{(r[1] or '')[:60]}"
        )

    WORKING.mkdir(parents=True, exist_ok=True)
    with open(CIK_BREAKDOWN_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fund_cik", "sample_fund_name", "n_rows", "aum_billions"])
        for r in rows:
            w.writerow(r)
    print(f"[1b] wrote {CIK_BREAKDOWN_CSV.relative_to(BASE_DIR)}")

    # Step 1c: classify each CIK
    classified = []
    for fund_cik, sample_name, n_rows_cik, aum_b_cik in rows:
        open_matches = con.execute(
            """
            SELECT entity_id
            FROM entity_identifiers
            WHERE identifier_type = 'cik'
              AND identifier_value = ?
              AND valid_to = DATE '9999-12-31'
            """,
            [str(fund_cik)],
        ).fetchall()
        closed_count = con.execute(
            """
            SELECT COUNT(*)
            FROM entity_identifiers
            WHERE identifier_type = 'cik'
              AND identifier_value = ?
              AND valid_to <> DATE '9999-12-31'
            """,
            [str(fund_cik)],
        ).fetchone()[0]

        if str(fund_cik) in CARVE_OUTS:
            classification = "CARVED_OUT"
            target_eid = open_matches[0][0] if len(open_matches) == 1 else None
        elif len(open_matches) == 1:
            classification = "LINKABLE"
            target_eid = open_matches[0][0]
        elif len(open_matches) > 1:
            classification = "LINKABLE_MULTI"
            target_eid = None
        elif closed_count > 0:
            classification = "EXISTS_BUT_CLOSED"
            target_eid = None
        else:
            classification = "UNMATCHED"
            target_eid = None

        classified.append(
            {
                "fund_cik": fund_cik,
                "sample_fund_name": sample_name,
                "n_rows": n_rows_cik,
                "aum_billions": aum_b_cik,
                "classification": classification,
                "target_entity_id": target_eid,
            }
        )

    counts = {}
    for row in classified:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    linkable_rows = sum(r["n_rows"] for r in classified if r["classification"] == "LINKABLE")
    linkable_aum = sum(r["aum_billions"] for r in classified if r["classification"] == "LINKABLE")
    unmatched_rows = sum(r["n_rows"] for r in classified if r["classification"] == "UNMATCHED")
    unmatched_aum = sum(r["aum_billions"] for r in classified if r["classification"] == "UNMATCHED")

    if counts.get("CARVED_OUT", 0):
        print(f"\n[1c] CARVE-OUTS APPLIED ({counts['CARVED_OUT']}):")
        for r in classified:
            if r["classification"] == "CARVED_OUT":
                meta = CARVE_OUTS[str(r["fund_cik"])]
                print(
                    f"     cik={r['fund_cik']} rows={r['n_rows']:,} "
                    f"aum_b={r['aum_billions']:,.4f} → {meta['reason']}"
                )
    print(f"\n[1c] classification counts: {counts}")
    print(
        f"     LINKABLE: {counts.get('LINKABLE', 0)} ciks, "
        f"{linkable_rows:,} rows, ${linkable_aum:,.2f}B"
    )
    print(
        f"     UNMATCHED: {counts.get('UNMATCHED', 0)} ciks, "
        f"{unmatched_rows:,} rows, ${unmatched_aum:,.2f}B"
    )
    if counts.get("LINKABLE_MULTI", 0):
        print(
            f"     ABORT: {counts['LINKABLE_MULTI']} LINKABLE_MULTI rows present "
            "(D4 / uniqueness invariant violation). Halt for chat resolution."
        )
        sys.exit(3)
    if counts.get("EXISTS_BUT_CLOSED", 0):
        print(
            f"     NOTE: {counts['EXISTS_BUT_CLOSED']} EXISTS_BUT_CLOSED ciks — "
            "surfacing for visibility; not in sub-PR 1 scope"
        )

    with open(CLASSIFICATION_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "fund_cik",
                "sample_fund_name",
                "n_rows",
                "aum_billions",
                "classification",
                "target_entity_id",
            ]
        )
        for r in classified:
            w.writerow(
                [
                    r["fund_cik"],
                    r["sample_fund_name"],
                    r["n_rows"],
                    f"{r['aum_billions']:.6f}",
                    r["classification"],
                    r["target_entity_id"] if r["target_entity_id"] is not None else "",
                ]
            )
    print(f"[1c] wrote {CLASSIFICATION_CSV.relative_to(BASE_DIR)}")

    # Step 1d: sanity-check linkable target entities (relaxed shape per chat May 5)
    print("\n[1d] linkable target entity sanity (relaxed shape)")
    print(f"     rule: entity_type IN {ALLOWED_TYPES} AND open CIK count = 1")
    bad = []
    type_counts = {}
    for r in classified:
        if r["classification"] != "LINKABLE":
            continue
        eid = r["target_entity_id"]
        ent = con.execute(
            "SELECT entity_id, canonical_name, entity_type FROM entities WHERE entity_id = ?",
            [eid],
        ).fetchone()
        if ent is None:
            bad.append((r["fund_cik"], eid, "entity row missing"))
            continue
        cls = con.execute(
            """
            SELECT classification
            FROM entity_classification_history
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
            """,
            [eid],
        ).fetchone()
        cls_val = cls[0] if cls else None
        n_ciks = con.execute(
            """
            SELECT COUNT(*) FROM entity_identifiers
            WHERE entity_id = ? AND identifier_type = 'cik'
              AND valid_to = DATE '9999-12-31'
            """,
            [eid],
        ).fetchone()[0]
        r["target_canonical_name"] = ent[1]
        r["target_entity_type"] = ent[2]
        r["target_classification"] = cls_val
        r["target_n_ciks"] = n_ciks
        type_counts[ent[2]] = type_counts.get(ent[2], 0) + 1
        if ent[2] not in ALLOWED_TYPES:
            bad.append((r["fund_cik"], eid, f"unexpected entity_type={ent[2]}"))
        if n_ciks != 1:
            bad.append((r["fund_cik"], eid, f"shape violation n_ciks={n_ciks}"))
        if cls_val is None:
            bad.append((r["fund_cik"], eid, "no open ECH classification"))
    n_linkable = sum(1 for r in classified if r["classification"] == "LINKABLE")
    print(f"     checked {n_linkable} entities; type distribution: {type_counts}")
    if bad:
        print(f"     ABORT: {len(bad)} suspicious targets:")
        for row in bad:
            print(f"       {row}")
        sys.exit(4)
    print("     OK — all linkable targets pass relaxed shape check")

    # Step 1e: pre-write baseline
    pre_attributed = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id IS NOT NULL AND is_latest = TRUE"
    ).fetchone()[0]
    pre_total_aum = con.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 WHERE is_latest = TRUE"
    ).fetchone()[0]
    print(
        f"\n[1e] baseline: attributed_rows={pre_attributed:,} "
        f"total_aum=${pre_total_aum / 1e9:,.2f}B"
    )
    con.close()
    print("\nPHASE 1 OK")
    return classified


def phase2_dry_run():
    print("=" * 72)
    print("PHASE 2 — dry-run manifest")
    print("=" * 72)
    classified = phase1_validate()
    linkable = [r for r in classified if r["classification"] == "LINKABLE"]

    with open(MANIFEST_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "fund_cik",
                "sample_fund_name",
                "n_rows_to_update",
                "aum_billions",
                "target_entity_id",
                "target_canonical_name",
                "target_entity_type",
                "target_classification",
            ]
        )
        for r in linkable:
            w.writerow(
                [
                    r["fund_cik"],
                    r["sample_fund_name"],
                    r["n_rows"],
                    f"{r['aum_billions']:.6f}",
                    r["target_entity_id"],
                    r.get("target_canonical_name", ""),
                    r.get("target_entity_type", ""),
                    r.get("target_classification", ""),
                ]
            )
    print(f"\nwrote {MANIFEST_CSV.relative_to(BASE_DIR)} ({len(linkable)} rows)")

    print("\nPhase 3 entry gate:")
    total_rows = sum(r["n_rows"] for r in linkable)
    total_aum = sum(r["aum_billions"] for r in linkable)
    print(f"  manifest LINKABLE ciks: {len(linkable)}")
    print(f"  total rows to update : {total_rows:,}")
    print(f"  total aum            : ${total_aum:,.2f}B")
    print("  no LINKABLE_MULTI / UNMATCHED in manifest: OK (Phase 1 already gated)")
    print("  every target_entity_id verified to exist: OK")
    return linkable


def phase3_confirm():
    # Re-run Phase 1 + Phase 2 to get a fresh manifest
    print("=" * 72)
    print("PHASE 3 — execute UPDATE in single transaction with 6 hard guards")
    print("=" * 72)
    linkable = phase2_dry_run()
    if not linkable:
        print("ABORT: empty manifest")
        sys.exit(5)

    # capture pre-baseline
    con_ro = _connect(read_only=True)
    pre_attributed = con_ro.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id IS NOT NULL AND is_latest = TRUE"
    ).fetchone()[0]
    pre_total_aum = con_ro.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 WHERE is_latest = TRUE"
    ).fetchone()[0]
    pre_unmatched = con_ro.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id IS NULL AND is_latest = TRUE"
    ).fetchone()[0]
    pre_per_cik = {}
    for r in linkable:
        cnt = con_ro.execute(
            """
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE fund_cik = ? AND entity_id IS NULL AND is_latest = TRUE
            """,
            [str(r["fund_cik"])],
        ).fetchone()[0]
        pre_per_cik[r["fund_cik"]] = cnt
    con_ro.close()

    expected_updates = sum(r["n_rows"] for r in linkable)
    print(
        f"\nbaseline: attributed_rows={pre_attributed:,} "
        f"unmatched_rows={pre_unmatched:,} "
        f"total_aum=${pre_total_aum / 1e9:,.2f}B"
    )
    print(f"expected updates: {expected_updates:,}")

    # Cross-check pre-counts against manifest
    mismatches = [
        (r["fund_cik"], r["n_rows"], pre_per_cik[r["fund_cik"]])
        for r in linkable
        if pre_per_cik[r["fund_cik"]] != r["n_rows"]
    ]
    if mismatches:
        print("ABORT: per-cik pre-counts diverge from manifest:")
        for m in mismatches[:10]:
            print(f"  cik={m[0]} manifest={m[1]} actual={m[2]}")
        sys.exit(6)
    print("pre-cik counts match manifest: OK")

    con = _connect(read_only=False)
    try:
        con.execute("BEGIN TRANSACTION")
        per_cik_updates = {}
        for r in linkable:
            cik = str(r["fund_cik"])
            target = r["target_entity_id"]
            con.execute(
                """
                UPDATE fund_holdings_v2
                SET entity_id = ?
                WHERE fund_cik = ? AND entity_id IS NULL AND is_latest = TRUE
                """,
                [target, cik],
            )
            post_n = con.execute(
                """
                SELECT COUNT(*) FROM fund_holdings_v2
                WHERE fund_cik = ? AND entity_id = ? AND is_latest = TRUE
                """,
                [cik, target],
            ).fetchone()[0]
            per_cik_updates[cik] = post_n

        # Guard 1: per-CIK counts
        bad1 = [
            (r["fund_cik"], r["n_rows"], per_cik_updates[str(r["fund_cik"])])
            for r in linkable
            if per_cik_updates[str(r["fund_cik"])] < r["n_rows"]
        ]
        if bad1:
            raise RuntimeError(f"Guard 1 FAIL — per-cik post-counts below manifest: {bad1[:5]}")
        print("Guard 1 OK — per-cik update counts >= manifest expectations")

        # Guard 2: zero leftover NULL for LINKABLE ciks
        bad2 = []
        for r in linkable:
            cik = str(r["fund_cik"])
            n_left = con.execute(
                """
                SELECT COUNT(*) FROM fund_holdings_v2
                WHERE fund_cik = ? AND entity_id IS NULL AND is_latest = TRUE
                """,
                [cik],
            ).fetchone()[0]
            if n_left != 0:
                bad2.append((cik, n_left))
        if bad2:
            raise RuntimeError(f"Guard 2 FAIL — leftover NULL rows for linkable ciks: {bad2}")
        print("Guard 2 OK — 0 leftover NULL entity_id for all linkable ciks")

        # Guard 3: UNMATCHED untouched
        post_unmatched_total = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id IS NULL AND is_latest = TRUE"
        ).fetchone()[0]
        expected_unmatched = pre_unmatched - expected_updates
        if post_unmatched_total != expected_unmatched:
            raise RuntimeError(
                f"Guard 3 FAIL — post unmatched={post_unmatched_total:,} "
                f"expected={expected_unmatched:,}"
            )
        print(
            f"Guard 3 OK — unmatched rows reduced exactly by {expected_updates:,} "
            f"(pre={pre_unmatched:,} → post={post_unmatched_total:,})"
        )

        # Guard 4: no spurious entity_id changes
        post_attributed = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 WHERE entity_id IS NOT NULL AND is_latest = TRUE"
        ).fetchone()[0]
        expected_attributed = pre_attributed + expected_updates
        if post_attributed != expected_attributed:
            raise RuntimeError(
                f"Guard 4 FAIL — post attributed={post_attributed:,} "
                f"expected={expected_attributed:,}"
            )
        print(
            f"Guard 4 OK — attributed rows increased exactly by {expected_updates:,} "
            f"(pre={pre_attributed:,} → post={post_attributed:,})"
        )

        # Guard 5: AUM unchanged
        post_total_aum = con.execute(
            "SELECT COALESCE(SUM(market_value_usd), 0) FROM fund_holdings_v2 WHERE is_latest = TRUE"
        ).fetchone()[0]
        if abs(post_total_aum - pre_total_aum) > 1e7:  # $0.01B tolerance
            raise RuntimeError(
                f"Guard 5 FAIL — total AUM drift "
                f"pre=${pre_total_aum / 1e9:.4f}B post=${post_total_aum / 1e9:.4f}B"
            )
        print(f"Guard 5 OK — total AUM unchanged within $0.01B tolerance")

        # Guard 6: referential integrity
        bad6 = con.execute(
            """
            SELECT DISTINCT fh.entity_id
            FROM fund_holdings_v2 fh
            LEFT JOIN entities e ON e.entity_id = fh.entity_id
            WHERE fh.entity_id IS NOT NULL AND e.entity_id IS NULL
              AND fh.is_latest = TRUE
            """
        ).fetchall()
        if bad6:
            raise RuntimeError(f"Guard 6 FAIL — orphan entity_ids: {bad6[:10]}")
        print("Guard 6 OK — every fh2 entity_id links to entities")

        con.execute("COMMIT")
        print("\nCOMMIT OK")
    except Exception as exc:
        con.execute("ROLLBACK")
        print(f"\nROLLBACK due to: {exc}")
        sys.exit(7)
    finally:
        con.close()

    # Phase 4 inline — ERH coverage spot-check (read-only after commit)
    print("\nPHASE 4 — ERH coverage spot-check (5 sample CIKs)")
    con_ro = _connect(read_only=True)
    sample = linkable[:5]
    for r in sample:
        rows = con_ro.execute(
            """
            SELECT fh.entity_id, erh.rollup_entity_id
            FROM fund_holdings_v2 fh
            LEFT JOIN entity_rollup_history erh
              ON erh.entity_id = fh.entity_id
              AND erh.rollup_type = 'decision_maker_v1'
              AND erh.valid_to = DATE '9999-12-31'
            WHERE fh.fund_cik = ? AND fh.is_latest = TRUE
            LIMIT 5
            """,
            [str(r["fund_cik"])],
        ).fetchall()
        present = sum(1 for x in rows if x[1] is not None)
        print(
            f"  cik={r['fund_cik']} eid={r['target_entity_id']} "
            f"rollup_present={present}/{len(rows)}"
        )
    con_ro.close()
    print("\nPHASE 3+4 OK")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--validate", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    if args.validate:
        phase1_validate()
    elif args.dry_run:
        phase2_dry_run()
    elif args.confirm:
        phase3_confirm()


if __name__ == "__main__":
    main()
