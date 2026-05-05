"""cp-5-loader-gap-remediation-sub2: create 53 entities + close loader gap.

Closes the loader-gap workstream surfaced in Bundle B §2.4 / Bundle C §7.5
Gap 1. PR #290 (sub-PR 1) linked the 23 LINKABLE fund_ciks. This sub-PR
creates 53 new institution-typed entities for the remaining 52 UNMATCHED
fund_ciks plus the 1 FMR carve-out (CIK 0000945908, Fidelity CLO ETF —
SCD-transferred out of eid 10443 FMR LLC).

Per chat decision 2026-05-05, ERH self-rollup is populated inline at
entity creation (cp-5-capital-group-umbrella PR #287 Phase 2e pattern).
Sub-PR 3 (separate ERH rebuild) eliminated.

Phases:
  --validate : Phase 1 read-only cohort revalidation + manifest preview.
  --dry-run  : Phase 2 manifest with new_entity_id assignments + op flags.
  --confirm  : Phase 3 execute INSERT/UPDATE in a single tx with 9 guards.

Usage:
  python scripts/oneoff/cp_5_loader_gap_remediation_sub2.py --validate
  python scripts/oneoff/cp_5_loader_gap_remediation_sub2.py --dry-run
  python scripts/oneoff/cp_5_loader_gap_remediation_sub2.py --confirm
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import duckdb

# Absolute path to the prod DB in the main repo (worktree's data/ is empty).
DB = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"

BASE_DIR = Path(__file__).resolve().parents[2]
WORKING = BASE_DIR / "data" / "working"
MANIFEST_CSV = WORKING / "cp-5-loader-gap-sub2-manifest.csv"

FMR_CARVE_OUT_CIK = "0000945908"
FMR_LLC_EID = 10443

EXPECTED_COHORT_ROWS = 26_008  # Bundle B §2.4 / PR #290: 25,988 UNMATCHED + 20 FMR
EXPECTED_COHORT_AUM_B = 32.17
EXPECTED_COHORT_CIKS = 53
COHORT_DRIFT_TOLERANCE = 0.10

PRIOR_BRIDGES = (20813, 20814, 20820, 20821, 20822, 20823, 20830, 20840, 20843)

ROW_SOURCE = "CP-5-pre:cp-5-loader-gap-remediation-sub2"
ECH_SOURCE = (
    f"{ROW_SOURCE}|inferred_from_nport_registrant"
)
ERH_DM_SOURCE_TMPL = (
    f"{ROW_SOURCE}|created_for_fund_cik={{cik}}"
)
ERH_EC_SOURCE_TMPL = (
    f"{ROW_SOURCE}|economic_control_v1_self|cik={{cik}}"
)
EID_SOURCE_TMPL = f"{ROW_SOURCE}|cik={{cik}}"


def _connect(read_only=True):
    return duckdb.connect(DB, read_only=read_only)


def _within_tolerance(actual, expected, tol=COHORT_DRIFT_TOLERANCE):
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / expected <= tol


def _classify_cik(con, fund_cik):
    """Return (open_eids, closed_count) for an identifier_type='cik' row."""
    open_rows = con.execute(
        """
        SELECT entity_id FROM entity_identifiers
        WHERE identifier_type = 'cik'
          AND identifier_value = ?
          AND valid_to = DATE '9999-12-31'
        """,
        [str(fund_cik)],
    ).fetchall()
    closed = con.execute(
        """
        SELECT COUNT(*) FROM entity_identifiers
        WHERE identifier_type = 'cik'
          AND identifier_value = ?
          AND valid_to <> DATE '9999-12-31'
        """,
        [str(fund_cik)],
    ).fetchone()[0]
    return [r[0] for r in open_rows], closed


def _pick_canonical_name(name_counter):
    """Most-common variant; ties → lexicographic min for determinism."""
    if not name_counter:
        return ""
    items = sorted(name_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[0][0]


def phase1_validate():
    print("=" * 72)
    print("PHASE 1 — read-only cohort revalidation")
    print("=" * 72)
    con = _connect(read_only=True)

    # Step 1a — cohort total (UNMATCHED + FMR carve-out remainder)
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
        f"     expected: ~{EXPECTED_COHORT_ROWS:,} rows / "
        f"~${EXPECTED_COHORT_AUM_B}B / ~{EXPECTED_COHORT_CIKS} ciks"
    )

    drift_ok = (
        _within_tolerance(n_rows, EXPECTED_COHORT_ROWS)
        and _within_tolerance(aum_b, EXPECTED_COHORT_AUM_B)
        and n_ciks == EXPECTED_COHORT_CIKS
    )
    if not drift_ok:
        print("[1a] ABORT — cohort shifted materially since PR #290")
        sys.exit(2)
    print("[1a] OK — cohort stable")

    # Step 1b — per-CIK manifest with name-variant resolution
    rows = con.execute(
        """
        SELECT
          fund_cik,
          fund_name,
          COUNT(*) AS n_rows,
          COALESCE(SUM(market_value_usd), 0) / 1e9 AS aum_b
        FROM fund_holdings_v2
        WHERE entity_id IS NULL AND is_latest = TRUE
        GROUP BY fund_cik, fund_name
        ORDER BY fund_cik, n_rows DESC
        """
    ).fetchall()

    by_cik = {}
    for fund_cik, fund_name, nr, ab in rows:
        d = by_cik.setdefault(
            fund_cik,
            {"names": Counter(), "n_rows": 0, "aum_b": 0.0},
        )
        d["names"][fund_name or ""] += nr
        d["n_rows"] += nr
        d["aum_b"] += ab

    classified = []
    for fund_cik, d in by_cik.items():
        canonical = _pick_canonical_name(d["names"])
        n_variants = len(d["names"])
        open_eids, _ = _classify_cik(con, fund_cik)
        if str(fund_cik) == FMR_CARVE_OUT_CIK:
            source = "FMR_CARVE_OUT"
        elif not open_eids:
            source = "UNMATCHED"
        else:
            source = "ANOMALY"
        classified.append(
            {
                "fund_cik": fund_cik,
                "canonical_fund_name": canonical,
                "n_rows": d["n_rows"],
                "aum_billions": d["aum_b"],
                "n_name_variants": n_variants,
                "name_variants": dict(d["names"]),
                "source": source,
            }
        )

    classified.sort(key=lambda r: (-r["aum_billions"], r["fund_cik"]))

    counts = Counter(r["source"] for r in classified)
    print(f"\n[1b] {len(classified)} distinct fund_ciks; sources: {dict(counts)}")
    print(
        f"     {'cik':<14}{'rows':>7}{'aum_b':>10}{'nvar':>5}  "
        f"{'source':<14}canonical_fund_name"
    )
    for r in classified:
        print(
            f"     {str(r['fund_cik']):<14}{r['n_rows']:>7,}"
            f"{r['aum_billions']:>10,.2f}"
            f"{r['n_name_variants']:>5}  "
            f"{r['source']:<14}{(r['canonical_fund_name'] or '')[:60]}"
        )

    print("\n[1b-i] CIKs with name variants > 1:")
    has_variants = [r for r in classified if r["n_name_variants"] > 1]
    if not has_variants:
        print("       (none)")
    for r in has_variants:
        print(f"       cik={r['fund_cik']} canonical={r['canonical_fund_name'][:60]!r}")
        for name, n in sorted(r["name_variants"].items(), key=lambda kv: -kv[1]):
            print(f"         {n:>6,} × {name[:80]!r}")

    if counts.get("ANOMALY", 0):
        print(
            f"\n[1b] ABORT — {counts['ANOMALY']} ANOMALY CIKs have open eids "
            "but were not pre-linked. Halt for chat."
        )
        for r in classified:
            if r["source"] == "ANOMALY":
                print(f"       cik={r['fund_cik']} rows={r['n_rows']:,}")
        sys.exit(3)

    if counts.get("FMR_CARVE_OUT", 0) != 1:
        print(
            f"\n[1b] ABORT — expected exactly 1 FMR_CARVE_OUT row, "
            f"got {counts.get('FMR_CARVE_OUT', 0)}"
        )
        sys.exit(3)
    if counts.get("UNMATCHED", 0) != 52:
        print(
            f"\n[1b] ABORT — expected exactly 52 UNMATCHED rows, "
            f"got {counts.get('UNMATCHED', 0)}"
        )
        sys.exit(3)

    # Step 1c — pre-write entity baseline
    max_eid = con.execute("SELECT MAX(entity_id) FROM entities").fetchone()[0]
    max_rid = con.execute(
        "SELECT MAX(relationship_id) FROM entity_relationships"
    ).fetchone()[0]
    print(f"\n[1c] max entity_id={max_eid}  max relationship_id={max_rid}")

    # Step 1d — confirm FMR carve-out state
    fmr_open_for_carve = con.execute(
        """
        SELECT entity_id, identifier_value
        FROM entity_identifiers
        WHERE identifier_type = 'cik'
          AND identifier_value = ?
          AND valid_to = DATE '9999-12-31'
        """,
        [FMR_CARVE_OUT_CIK],
    ).fetchall()
    print(f"\n[1d] FMR carve-out CIK {FMR_CARVE_OUT_CIK} open rows: {fmr_open_for_carve}")
    if not (len(fmr_open_for_carve) == 1
            and fmr_open_for_carve[0][0] == FMR_LLC_EID):
        print(
            f"     ABORT — expected exactly 1 open row pointing to eid={FMR_LLC_EID}"
        )
        sys.exit(4)

    fmr_total_open_ciks = con.execute(
        """
        SELECT COUNT(*) FROM entity_identifiers
        WHERE entity_id = ?
          AND identifier_type = 'cik'
          AND valid_to = DATE '9999-12-31'
        """,
        [FMR_LLC_EID],
    ).fetchone()[0]
    print(f"     FMR LLC eid={FMR_LLC_EID} total open CIKs (pre): {fmr_total_open_ciks}")
    if fmr_total_open_ciks != 2:
        print(
            "     ABORT — expected exactly 2 open CIKs on FMR LLC pre-execution"
        )
        sys.exit(4)
    print("[1d] OK — FMR carve-out pre-state matches expectation")

    # Step 1e — prior bridges intact
    found = con.execute(
        f"""
        SELECT relationship_id FROM entity_relationships
        WHERE relationship_id IN ({','.join(str(x) for x in PRIOR_BRIDGES)})
        """
    ).fetchall()
    print(
        f"\n[1e] prior bridges present: {len(found)}/{len(PRIOR_BRIDGES)}"
    )
    if len(found) != len(PRIOR_BRIDGES):
        print("     ABORT — expected all prior bridges intact")
        sys.exit(5)
    print("[1e] OK")

    con.close()
    print("\nPHASE 1 OK")
    return classified, max_eid


def _build_manifest(classified, max_eid):
    """Assign sequential new_entity_id to each row in the source-sorted manifest.

    Sort: FMR_CARVE_OUT first deterministically, then UNMATCHED in (-aum, cik)
    order. (Source tag drives op_b_identifier_action.)
    """
    fmr = [r for r in classified if r["source"] == "FMR_CARVE_OUT"]
    unm = sorted(
        [r for r in classified if r["source"] == "UNMATCHED"],
        key=lambda r: (-r["aum_billions"], r["fund_cik"]),
    )
    ordered = fmr + unm
    next_eid = max_eid + 1
    manifest = []
    for r in ordered:
        op_b = "transfer" if r["source"] == "FMR_CARVE_OUT" else "insert"
        manifest.append({
            **r,
            "new_entity_id": next_eid,
            "op_b_identifier_action": op_b,
            "op_c_alias_insert": True,
            "op_d_ech_insert": True,
            "op_e_erh_insert": True,
            "op_a_fh2_update_count": r["n_rows"],
        })
        next_eid += 1
    return manifest


def phase2_dry_run():
    print("=" * 72)
    print("PHASE 2 — dry-run manifest")
    print("=" * 72)
    classified, max_eid = phase1_validate()
    manifest = _build_manifest(classified, max_eid)

    WORKING.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "fund_cik", "canonical_fund_name", "n_rows", "aum_billions",
            "source", "new_entity_id", "op_b_identifier_action",
            "op_c_alias_insert", "op_d_ech_insert", "op_e_erh_insert",
            "op_a_fh2_update_count",
        ])
        for r in manifest:
            w.writerow([
                r["fund_cik"], r["canonical_fund_name"], r["n_rows"],
                f"{r['aum_billions']:.6f}", r["source"], r["new_entity_id"],
                r["op_b_identifier_action"],
                r["op_c_alias_insert"], r["op_d_ech_insert"],
                r["op_e_erh_insert"], r["op_a_fh2_update_count"],
            ])
    print(f"\nwrote {MANIFEST_CSV.relative_to(BASE_DIR)} ({len(manifest)} rows)")

    # Phase 3 entry gate
    n_total = len(manifest)
    n_fmr = sum(1 for r in manifest if r["op_b_identifier_action"] == "transfer")
    n_unm = sum(1 for r in manifest if r["op_b_identifier_action"] == "insert")
    sum_rows = sum(r["n_rows"] for r in manifest)
    sum_aum = sum(r["aum_billions"] for r in manifest)
    eids = [r["new_entity_id"] for r in manifest]

    print("\nPhase 3 entry gate:")
    print(f"  manifest rows                  : {n_total} (expect 53)")
    print(f"  FMR_CARVE_OUT (transfer)       : {n_fmr} (expect 1)")
    print(f"  UNMATCHED (insert)             : {n_unm} (expect 52)")
    print(f"  new_entity_id sequential       : {min(eids)}..{max(eids)}")
    print(f"  total fh2 rows                 : {sum_rows:,}")
    print(f"  total aum                      : ${sum_aum:,.2f}B")

    fail = []
    if n_total != 53:
        fail.append(f"manifest rows {n_total} != 53")
    if n_fmr != 1:
        fail.append(f"transfer rows {n_fmr} != 1")
    if n_unm != 52:
        fail.append(f"insert rows {n_unm} != 52")
    if eids != list(range(min(eids), min(eids) + n_total)):
        fail.append("new_entity_id not contiguous sequential")
    if fail:
        print("\nABORT (entry gate failed):")
        for f in fail:
            print(f"  - {f}")
        sys.exit(6)
    print("\nentry gate OK")
    return manifest


def phase3_confirm():
    print("=" * 72)
    print("PHASE 3 — execute single transaction with 9 guards")
    print("=" * 72)
    manifest = phase2_dry_run()
    if not manifest:
        print("ABORT — empty manifest")
        sys.exit(7)

    pre_eid_min = manifest[0]["new_entity_id"]
    pre_eid_max = manifest[-1]["new_entity_id"]

    # Capture pre-state for guards
    con_ro = _connect(read_only=True)
    pre_fh2_total_rows = con_ro.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest = TRUE"
    ).fetchone()[0]
    pre_fh2_total_aum = con_ro.execute(
        "SELECT COALESCE(SUM(market_value_usd), 0) "
        "FROM fund_holdings_v2 WHERE is_latest = TRUE"
    ).fetchone()[0]
    pre_fh2_null_rows = con_ro.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE entity_id IS NULL AND is_latest = TRUE"
    ).fetchone()[0]
    print(
        f"\nbaseline: fh2 total_rows={pre_fh2_total_rows:,} "
        f"null_entity_rows={pre_fh2_null_rows:,} "
        f"total_aum=${pre_fh2_total_aum / 1e9:,.4f}B"
    )
    con_ro.close()

    con = _connect(read_only=False)
    try:
        con.execute("BEGIN TRANSACTION")

        # Op A — INSERT entities
        for r in manifest:
            con.execute(
                "INSERT INTO entities "
                "(entity_id, canonical_name, entity_type, "
                " created_source, is_inferred) "
                "VALUES (?, ?, 'institution', ?, TRUE)",
                [r["new_entity_id"], r["canonical_fund_name"], ROW_SOURCE],
            )

        # Op B — entity_identifiers (52 INSERT + 1 transfer)
        for r in manifest:
            cik = str(r["fund_cik"])
            new_eid = r["new_entity_id"]
            if r["op_b_identifier_action"] == "transfer":
                # Op B.1 — close the old open linkage at eid 10443
                con.execute(
                    "UPDATE entity_identifiers "
                    "SET valid_to = CURRENT_DATE "
                    "WHERE entity_id = ? AND identifier_type = 'cik' "
                    "AND identifier_value = ? "
                    "AND valid_to = DATE '9999-12-31'",
                    [FMR_LLC_EID, cik],
                )
            # Op B.2 (and UNMATCHED insert) — open linkage at the new entity
            con.execute(
                "INSERT INTO entity_identifiers "
                "(entity_id, identifier_type, identifier_value, "
                " confidence, source, is_inferred, "
                " valid_from, valid_to) "
                "VALUES (?, 'cik', ?, 'exact', ?, TRUE, "
                "        CURRENT_DATE, DATE '9999-12-31')",
                [new_eid, cik, EID_SOURCE_TMPL.format(cik=cik)],
            )

        # Op C — entity_aliases
        for r in manifest:
            con.execute(
                "INSERT INTO entity_aliases "
                "(entity_id, alias_name, alias_type, is_preferred, "
                " preferred_key, source_table, is_inferred, "
                " valid_from, valid_to) "
                "VALUES (?, ?, 'brand', TRUE, ?, ?, TRUE, "
                "        CURRENT_DATE, DATE '9999-12-31')",
                [
                    r["new_entity_id"], r["canonical_fund_name"],
                    r["new_entity_id"], ROW_SOURCE,
                ],
            )

        # Op D — entity_classification_history
        for r in manifest:
            con.execute(
                "INSERT INTO entity_classification_history "
                "(entity_id, classification, is_activist, confidence, "
                " source, is_inferred, valid_from, valid_to) "
                "VALUES (?, 'mixed', FALSE, 'medium', ?, TRUE, "
                "        CURRENT_DATE, DATE '9999-12-31')",
                [r["new_entity_id"], ECH_SOURCE],
            )

        # Op E — entity_rollup_history self-rollup (decision_maker_v1)
        for r in manifest:
            con.execute(
                "INSERT INTO entity_rollup_history "
                "(entity_id, rollup_entity_id, rollup_type, rule_applied, "
                " confidence, source, routing_confidence, review_due_date, "
                " valid_from, valid_to) "
                "VALUES (?, ?, 'decision_maker_v1', 'self', 'exact', ?, "
                "        'high', NULL, CURRENT_DATE, DATE '9999-12-31')",
                [
                    r["new_entity_id"],
                    r["new_entity_id"],
                    ERH_DM_SOURCE_TMPL.format(cik=r["fund_cik"]),
                ],
            )

        # Op E2 — entity_rollup_history self-rollup (economic_control_v1)
        # bootstrap_tier4 precedent + entity_current view requirement.
        # Discovered in-flight (post-COMMIT of original 5-op plan); preserved
        # here so the script captures the full remediation. See findings §3.2.
        for r in manifest:
            con.execute(
                "INSERT INTO entity_rollup_history "
                "(entity_id, rollup_entity_id, rollup_type, rule_applied, "
                " confidence, source, routing_confidence, review_due_date, "
                " valid_from, valid_to) "
                "VALUES (?, ?, 'economic_control_v1', 'self', 'exact', ?, "
                "        'high', NULL, CURRENT_DATE, DATE '9999-12-31')",
                [
                    r["new_entity_id"],
                    r["new_entity_id"],
                    ERH_EC_SOURCE_TMPL.format(cik=r["fund_cik"]),
                ],
            )

        # Op F — fund_holdings_v2.entity_id population
        per_cik_post = {}
        for r in manifest:
            cik = str(r["fund_cik"])
            new_eid = r["new_entity_id"]
            con.execute(
                "UPDATE fund_holdings_v2 SET entity_id = ? "
                "WHERE fund_cik = ? AND entity_id IS NULL "
                "AND is_latest = TRUE",
                [new_eid, cik],
            )
            n_post = con.execute(
                "SELECT COUNT(*) FROM fund_holdings_v2 "
                "WHERE fund_cik = ? AND entity_id = ? "
                "AND is_latest = TRUE",
                [cik, new_eid],
            ).fetchone()[0]
            per_cik_post[cik] = n_post

        # ─── Hard guards (assert before COMMIT) ───────────────────────────

        # Guard 1: 53 new entities exist
        n_new_entities = con.execute(
            "SELECT COUNT(*) FROM entities "
            "WHERE entity_id BETWEEN ? AND ?",
            [pre_eid_min, pre_eid_max],
        ).fetchone()[0]
        if n_new_entities != 53:
            raise RuntimeError(
                f"Guard 1 FAIL — n_new_entities={n_new_entities} != 53"
            )
        print(f"Guard 1 OK — {n_new_entities} new entities present")

        # Guard 2: 1 open CIK identifier per new eid + FMR LLC down to 1
        bad2 = []
        for r in manifest:
            n_open = con.execute(
                "SELECT COUNT(*) FROM entity_identifiers "
                "WHERE entity_id = ? AND identifier_type = 'cik' "
                "AND valid_to = DATE '9999-12-31'",
                [r["new_entity_id"]],
            ).fetchone()[0]
            if n_open != 1:
                bad2.append((r["new_entity_id"], n_open))
        if bad2:
            raise RuntimeError(f"Guard 2a FAIL — non-1 open CIK for new eids: {bad2[:5]}")
        fmr_open_post = con.execute(
            "SELECT COUNT(*) FROM entity_identifiers "
            "WHERE entity_id = ? AND identifier_type = 'cik' "
            "AND valid_to = DATE '9999-12-31'",
            [FMR_LLC_EID],
        ).fetchone()[0]
        if fmr_open_post != 1:
            raise RuntimeError(
                f"Guard 2b FAIL — FMR LLC eid={FMR_LLC_EID} "
                f"open CIKs post={fmr_open_post} != 1"
            )
        print(
            f"Guard 2 OK — 1 open CIK per new eid; "
            f"FMR LLC reduced 2→{fmr_open_post}"
        )

        # Guard 3: 53 open aliases
        n_aliases = con.execute(
            "SELECT COUNT(*) FROM entity_aliases "
            "WHERE entity_id BETWEEN ? AND ? "
            "AND valid_to = DATE '9999-12-31'",
            [pre_eid_min, pre_eid_max],
        ).fetchone()[0]
        if n_aliases != 53:
            raise RuntimeError(f"Guard 3 FAIL — n_aliases={n_aliases} != 53")
        print(f"Guard 3 OK — {n_aliases} open aliases")

        # Guard 4: 53 open ECH rows
        n_ech = con.execute(
            "SELECT COUNT(*) FROM entity_classification_history "
            "WHERE entity_id BETWEEN ? AND ? "
            "AND valid_to = DATE '9999-12-31'",
            [pre_eid_min, pre_eid_max],
        ).fetchone()[0]
        if n_ech != 53:
            raise RuntimeError(f"Guard 4 FAIL — n_ech={n_ech} != 53")
        print(f"Guard 4 OK — {n_ech} open ECH rows")

        # Guard 5: 53 open ERH self-rollups for both rollup types
        for rollup_type in ("decision_maker_v1", "economic_control_v1"):
            n_erh = con.execute(
                "SELECT COUNT(*) FROM entity_rollup_history "
                "WHERE entity_id BETWEEN ? AND ? "
                "AND entity_id = rollup_entity_id "
                "AND rollup_type = ? "
                "AND valid_to = DATE '9999-12-31'",
                [pre_eid_min, pre_eid_max, rollup_type],
            ).fetchone()[0]
            if n_erh != 53:
                raise RuntimeError(
                    f"Guard 5 FAIL — n_erh[{rollup_type}]={n_erh} != 53"
                )
            print(f"Guard 5 OK — {n_erh} open {rollup_type} self-rollups")

        # Guard 6: fh2 entity_id NULL count drops to 0 (or near-0)
        post_null = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 "
            "WHERE entity_id IS NULL AND is_latest = TRUE"
        ).fetchone()[0]
        if post_null != 0:
            raise RuntimeError(
                f"Guard 6 FAIL — post_null_rows={post_null} != 0"
            )
        print(f"Guard 6 OK — fh2 NULL entity_id count: {pre_fh2_null_rows:,} → {post_null}")

        # Guard 7: fh2 row count unchanged
        post_total_rows = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest = TRUE"
        ).fetchone()[0]
        if post_total_rows != pre_fh2_total_rows:
            raise RuntimeError(
                f"Guard 7 FAIL — fh2 row count "
                f"pre={pre_fh2_total_rows:,} post={post_total_rows:,}"
            )
        print(f"Guard 7 OK — fh2 total rows unchanged ({post_total_rows:,})")

        # Guard 8: fh2 AUM unchanged
        post_total_aum = con.execute(
            "SELECT COALESCE(SUM(market_value_usd), 0) "
            "FROM fund_holdings_v2 WHERE is_latest = TRUE"
        ).fetchone()[0]
        if abs(post_total_aum - pre_fh2_total_aum) > 1e7:
            raise RuntimeError(
                f"Guard 8 FAIL — total AUM drift "
                f"pre=${pre_fh2_total_aum / 1e9:.4f}B "
                f"post=${post_total_aum / 1e9:.4f}B"
            )
        print(
            f"Guard 8 OK — total AUM ${pre_fh2_total_aum / 1e9:,.4f}B → "
            f"${post_total_aum / 1e9:,.4f}B (within $0.01B tolerance)"
        )

        # Guard 9: Method A coverage check — for the rows we just linked
        # (filter by new entity_id; fund_cik is not 1:1 to entity in fh2)
        sample = manifest[:10]
        bad9 = []
        for r in sample:
            cik = str(r["fund_cik"])
            new_eid = r["new_entity_id"]
            joined = con.execute(
                """
                SELECT COUNT(*) FROM fund_holdings_v2 fh
                JOIN entity_rollup_history erh
                  ON erh.entity_id = fh.entity_id
                  AND erh.rollup_type = 'decision_maker_v1'
                  AND erh.valid_to = DATE '9999-12-31'
                WHERE fh.fund_cik = ? AND fh.entity_id = ?
                  AND fh.is_latest = TRUE
                """,
                [cik, new_eid],
            ).fetchone()[0]
            if joined != r["n_rows"]:
                bad9.append((cik, r["n_rows"], joined))
        if bad9:
            raise RuntimeError(f"Guard 9 FAIL — Method A JOIN mismatch: {bad9}")
        print(
            f"Guard 9 OK — Method A JOIN matches manifest for 10 samples"
        )

        con.execute("COMMIT")
        print("\nCOMMIT OK — all 9 guards passed")
    except Exception as exc:
        con.execute("ROLLBACK")
        print(f"\nROLLBACK due to: {exc}")
        sys.exit(8)
    finally:
        con.close()

    # Post-commit summary
    print("\nPost-commit summary:")
    print(f"  new entities created     : 53 (eid {pre_eid_min}..{pre_eid_max})")
    print(f"  fh2 rows linked          : {sum(r['n_rows'] for r in manifest):,}")
    print(f"  fh2 AUM linked           : ${sum(r['aum_billions'] for r in manifest):,.2f}B")
    print("\nPHASE 3 OK")


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
