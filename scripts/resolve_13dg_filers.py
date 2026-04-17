#!/usr/bin/env python3
"""resolve_13dg_filers.py — staging-only resolution of unmatched 13D/G filer CIKs.

Reads `data/reference/13dg_filer_research_v2.csv` (human-reviewed classification
from the 2,776-row research worksheet) and applies five actions:

  MERGE       — add CIK identifier to an existing MDM entity (28 rows, 24 unique CIKs)
  NEW_ENTITY  — create institution entity + alias + CIK + classification + self-rollups
  INDIVIDUAL  — insert pending_entity_resolution row with resolution_status='excluded_individual'
  LAW_FIRM    — same, status='excluded_law_firm'
  EXCLUDE     — same, status='excluded_other'

Deduplicates on CIK: each unique filer_cik processed once. Multiple CSV rows for
the same CIK (name-drift duplicates) collapse to the highest filing_count row.

CIK normalization: CSV CIKs are unpadded (e.g. '1306550'); MDM uses 10-digit
zero-padded ('0001306550'). All identifier writes and lookups zfill(10).

MERGE and NEW_ENTITY writes land in ENTITY_TABLES (entities, entity_identifiers,
entity_aliases, entity_classification_history, entity_rollup_history) and flow
staging → prod via the standard INF1 workflow.

INDIVIDUAL / LAW_FIRM / EXCLUDE writes go to `pending_entity_resolution`, which
is NOT in `db.ENTITY_TABLES`. The staging workflow does not carry that table,
so exclusions are written directly to prod via `--prod-exclusions` — only after
MERGE + NEW_ENTITY have been promoted.

The two write targets are kept in separate passes; a single invocation performs
at most one of them.

Usage:
    # Pass 1 — staging (MERGE + NEW_ENTITY):
    python3 scripts/sync_staging.py
    python3 scripts/resolve_13dg_filers.py --staging --dry-run
    python3 scripts/resolve_13dg_filers.py --staging
    # ... validate + diff + promote_staging --approved ...

    # Pass 2 — prod-direct (INDIVIDUAL/LAW_FIRM/EXCLUDE):
    python3 scripts/resolve_13dg_filers.py --prod-exclusions --dry-run
    python3 scripts/resolve_13dg_filers.py --prod-exclusions
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

CSV_PATH = os.path.join(BASE_DIR, "data", "reference", "13dg_filer_research_v2.csv")
SOURCE_TAG = "manual_13dg_resolution"
IDENTITY_VALID_FROM = "2020-01-01"
IDENTITY_VALID_TO = "9999-12-31"

EXCLUDE_STATUS = {
    "INDIVIDUAL": "excluded_individual",
    "LAW_FIRM": "excluded_law_firm",
    "EXCLUDE": "excluded_other",
}

# Human-pinned target resolutions for MERGE rows. Confirmed 2026-04-17.
#   int        → merge to that entity_id (bypasses name search)
#   ("NEW_ENTITY", classification) → create as NEW_ENTITY instead of merge
MANUAL_TARGET_OVERRIDES: dict[str, object] = {
    "GIC":                       ("NEW_ENTITY", "SWF"),  # no MDM entity
    "Insight Partners":          4505,                   # Insight Partners Public Equities GP
    "Apollo Global Management":  9576,                   # Apollo Management Holdings, L.P.
}


def _pad_cik(raw: str) -> str:
    return str(raw or "").strip().zfill(10)


def _read_csv_deduped() -> dict[str, dict]:
    """Return {padded_cik: row}, keeping row with highest filing_count per CIK."""
    by_cik: dict[str, dict] = {}
    conflicts: dict[str, set[str]] = defaultdict(set)
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cik = _pad_cik(row["filer_cik"])
            cls = (row.get("manual_classification") or "").strip().upper()
            if not cls:
                continue
            conflicts[cik].add(cls)
            row["_cik_padded"] = cik
            try:
                row["_filing_count_int"] = int(row.get("filing_count") or 0)
            except ValueError:
                row["_filing_count_int"] = 0
            prior = by_cik.get(cik)
            if prior is None or row["_filing_count_int"] > prior["_filing_count_int"]:
                by_cik[cik] = row

    mixed = {c: v for c, v in conflicts.items() if len(v) > 1}
    if mixed:
        print(f"  [warn] {len(mixed)} CIKs have conflicting manual_classification "
              f"across rows (picked highest filing_count):")
        for c, vals in list(mixed.items())[:10]:
            print(f"    cik={c}  classes={sorted(vals)}  winner={by_cik[c]['manual_classification']}")
    return by_cik


# ---------------------------------------------------------------------------
# MERGE
# ---------------------------------------------------------------------------

def _extract_target_name(action: str) -> str | None:
    if not action:
        return None
    prefix = "add CIK identifier to "
    if not action.startswith(prefix):
        return None
    return action[len(prefix):].strip() or None


def _resolve_target_entity(con, target_name: str, row: dict) -> int | None:
    """Find the canonical MDM entity for a target name. Returns entity_id or None."""
    # Special case: Credit Suisse → UBS (per prompt)
    is_cs_ubs = "Credit Suisse" in row.get("filer_name", "") or target_name in ("UBS", "Credit Suisse")

    def _query(patterns: list[tuple[str, list]]) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []
        for sql, params in patterns:
            for r in con.execute(sql, params).fetchall():
                results.append((r[0], r[1]))
        # dedupe preserving order
        seen = set()
        deduped = []
        for eid, name in results:
            if eid not in seen:
                seen.add(eid)
                deduped.append((eid, name))
        return deduped

    if is_cs_ubs:
        # Prefer UBS if present, else Credit Suisse, else fall through to target_name
        for name in ("UBS", "Credit Suisse"):
            matches = _query([
                ("""SELECT DISTINCT ea.entity_id, ea.alias_name
                     FROM entity_aliases ea
                     WHERE ea.valid_to = DATE '9999-12-31'
                       AND ea.alias_name ILIKE ?""",
                 [f"%{name}%"]),
            ])
            if matches:
                chosen = _pick_by_aum(con, matches)
                note = f"CS→UBS mapping: chose '{name}' hit eid={chosen[0]} ({chosen[1]})"
                print(f"    [merge-special] {note}")
                return chosen[0]
        return None

    # Tier 1: exact (case-insensitive) on canonical_name
    exact = _query([
        ("""SELECT e.entity_id, e.canonical_name
             FROM entities e
             WHERE LOWER(e.canonical_name) = LOWER(?)""",
         [target_name]),
    ])
    # Tier 2: exact alias match
    exact_alias = _query([
        ("""SELECT DISTINCT ea.entity_id, ea.alias_name
             FROM entity_aliases ea
             WHERE ea.valid_to = DATE '9999-12-31'
               AND LOWER(ea.alias_name) = LOWER(?)""",
         [target_name]),
    ])
    combined = exact + [m for m in exact_alias if m[0] not in {e[0] for e in exact}]
    if combined:
        chosen = _pick_by_aum(con, combined)
        if len(combined) > 1:
            print(f"    [merge-ambig]   exact-match pool for '{target_name}': "
                  f"{len(combined)} hits; picked eid={chosen[0]} by AUM")
        return chosen[0]

    # Tier 3: substring, word-boundary guarded. Pad both sides with spaces so
    # short names ("GIC", "ARK") don't substring-match inside "STRATEGIC",
    # "MONARK", etc. Mirrors resolve_pending_series.py:526-534 fix.
    padded = f"% {target_name} %"
    subs = _query([
        ("""SELECT DISTINCT ea.entity_id, ea.alias_name
             FROM entity_aliases ea
             WHERE ea.valid_to = DATE '9999-12-31'
               AND (' ' || ea.alias_name || ' ') ILIKE ?
             ORDER BY ea.entity_id""",
         [padded]),
    ])
    if not subs:
        return None
    chosen = _pick_by_aum(con, subs)
    if len(subs) > 1:
        print(f"    [merge-ambig]   substring pool for '{target_name}': "
              f"{len(subs)} hits; picked eid={chosen[0]} ({chosen[1]}) by AUM")
    return chosen[0]


def _pick_by_aum(con, candidates: list[tuple[int, str]]) -> tuple[int, str]:
    """Given (eid, name) list, pick the one with highest 2025Q4 AUM in holdings_v2.

    AUM source is prod (holdings_v2 is not mirrored to staging). The `con` arg
    is unused — kept for a stable call signature. Opens a read-only prod
    connection per call (infrequent).
    """
    _ = con
    if len(candidates) == 1:
        return candidates[0]
    eids = [c[0] for c in candidates]
    placeholders = ",".join(["?"] * len(eids))
    prod = db.connect_read()
    try:
        rows = prod.execute(
            f"""SELECT ei.entity_id, COALESCE(SUM(h.market_value_usd), 0) AS aum
                 FROM entity_identifiers ei
                 LEFT JOIN holdings_v2 h
                   ON h.cik = ei.identifier_value
                  AND h.quarter = '2025Q4'
                 WHERE ei.identifier_type = 'cik'
                   AND ei.valid_to = DATE '9999-12-31'
                   AND ei.entity_id IN ({placeholders})
                 GROUP BY ei.entity_id""",
            eids,
        ).fetchall()
    finally:
        prod.close()
    aum_by_eid = {r[0]: r[1] for r in rows}
    ranked = sorted(candidates, key=lambda c: aum_by_eid.get(c[0], 0), reverse=True)
    return ranked[0]


def _cik_already_mapped(con, cik_padded: str) -> int | None:
    row = con.execute(
        """SELECT entity_id FROM entity_identifiers
             WHERE identifier_type = 'cik'
               AND identifier_value = ?
               AND valid_to = DATE '9999-12-31'
             LIMIT 1""",
        [cik_padded],
    ).fetchone()
    return row[0] if row else None


def _insert_cik_identifier(con, eid: int, cik_padded: str) -> None:
    con.execute(
        """INSERT INTO entity_identifiers
             (entity_id, identifier_type, identifier_value, confidence,
              source, is_inferred, valid_from, valid_to)
           VALUES (?, 'cik', ?, 'high', ?, FALSE,
                   DATE '2020-01-01', DATE '9999-12-31')""",
        [eid, cik_padded, SOURCE_TAG],
    )


def process_merge(con, rows: dict[str, dict]) -> dict:
    stats = Counter()
    merge_rows = [r for r in rows.values() if r["manual_classification"].upper() == "MERGE"]
    print(f"\n=== MERGE ({len(merge_rows)} unique CIKs) ===")
    for row in merge_rows:
        cik = row["_cik_padded"]
        target = _extract_target_name(row.get("action", ""))
        if not target:
            print(f"  [skip-action]  cik={cik} filer='{row['filer_name']}' — "
                  f"unparseable action='{row['action']}'")
            stats["skipped_no_action"] += 1
            continue

        existing_eid = _cik_already_mapped(con, cik)
        if existing_eid is not None:
            print(f"  [already-map]  cik={cik} → eid={existing_eid} (target='{target}')")
            stats["already_mapped"] += 1
            continue

        override = MANUAL_TARGET_OVERRIDES.get(target)
        if isinstance(override, int):
            _insert_cik_identifier(con, override, cik)
            print(f"  [merge-override] cik={cik} → eid={override} ({target})")
            stats["merged_override"] += 1
            continue
        if isinstance(override, tuple) and override[0] == "NEW_ENTITY":
            # Reroute MERGE row through NEW_ENTITY creation with forced classification.
            forced_cls = override[1]
            eid = _create_new_entity(con, row, forced_classification=forced_cls)
            if eid is None:
                stats["override_newentity_skipped"] += 1
            else:
                print(f"  [merge→new]    cik={cik} → eid={eid} "
                      f"(target '{target}' rerouted to NEW_ENTITY / {forced_cls})")
                stats["merged_as_new_entity"] += 1
            continue

        eid = _resolve_target_entity(con, target, row)
        if eid is None:
            print(f"  [UNRESOLVED]   cik={cik} target='{target}' filer='{row['filer_name']}'")
            stats["unresolved"] += 1
            continue

        _insert_cik_identifier(con, eid, cik)
        print(f"  [merged]       cik={cik} → eid={eid} ({target})")
        stats["merged"] += 1
    return dict(stats)


# ---------------------------------------------------------------------------
# NEW_ENTITY
# ---------------------------------------------------------------------------

def _parse_classification(action: str) -> str:
    marker = "classify as "
    if marker in (action or ""):
        return action.split(marker, 1)[1].strip()
    return "active"  # safe default


def _is_activist(notes: str) -> bool:
    return "is_activist=TRUE" in (notes or "")


def _create_new_entity(con, row: dict,
                       forced_classification: str | None = None) -> int | None:
    cik = row["_cik_padded"]
    filer_name = row["filer_name"].strip()
    action = row.get("action", "") or ""
    classification = forced_classification or _parse_classification(action)
    activist_flag = False if forced_classification else _is_activist(row.get("notes", ""))

    existing_eid = _cik_already_mapped(con, cik)
    if existing_eid is not None:
        print(f"  [already-exists] cik={cik} → eid={existing_eid} ({filer_name[:50]})")
        return None

    eid = con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]
    con.execute(
        """INSERT INTO entities
             (entity_id, entity_type, canonical_name, created_source, is_inferred)
           VALUES (?, 'institution', ?, ?, FALSE)""",
        [eid, filer_name, SOURCE_TAG],
    )
    con.execute(
        """INSERT INTO entity_aliases
             (entity_id, alias_name, alias_type, is_preferred, preferred_key,
              source_table, is_inferred, valid_from, valid_to)
           VALUES (?, ?, 'filing', TRUE, ?, ?, FALSE,
                   DATE '2020-01-01', DATE '9999-12-31')""",
        [eid, filer_name, eid, SOURCE_TAG],
    )
    con.execute(
        """INSERT INTO entity_identifiers
             (entity_id, identifier_type, identifier_value, confidence,
              source, is_inferred, valid_from, valid_to)
           VALUES (?, 'cik', ?, 'high', ?, FALSE,
                   DATE '2020-01-01', DATE '9999-12-31')""",
        [eid, cik, SOURCE_TAG],
    )
    con.execute(
        """INSERT INTO entity_classification_history
             (entity_id, classification, is_activist, confidence,
              source, is_inferred, valid_from, valid_to)
           VALUES (?, ?, ?, 'medium', ?, FALSE,
                   DATE '2020-01-01', DATE '9999-12-31')""",
        [eid, classification, activist_flag, SOURCE_TAG],
    )
    for rollup_type in ("economic_control_v1", "decision_maker_v1"):
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to, computed_at, source,
                  routing_confidence)
               VALUES (?, ?, ?, 'self', 'high',
                       DATE '2020-01-01', DATE '9999-12-31',
                       CURRENT_TIMESTAMP, ?, 'high')""",
            [eid, eid, rollup_type, SOURCE_TAG],
        )
    return eid


def process_new_entity(con, rows: dict[str, dict]) -> dict:
    stats = Counter()
    cls_breakdown = Counter()
    new_rows = [r for r in rows.values() if r["manual_classification"].upper() == "NEW_ENTITY"]
    print(f"\n=== NEW_ENTITY ({len(new_rows)} unique CIKs) ===")
    for i, row in enumerate(new_rows, 1):
        eid = _create_new_entity(con, row)
        if eid is None:
            stats["skipped_already_exists"] += 1
        else:
            stats["created"] += 1
            cls = _parse_classification(row.get("action", ""))
            cls_breakdown[cls] += 1
            if _is_activist(row.get("notes", "")):
                cls_breakdown["__activist_flag__"] += 1
        if i % 250 == 0:
            print(f"  ...progress: {i}/{len(new_rows)} processed")
    return {"stats": dict(stats), "classification_breakdown": dict(cls_breakdown)}


# ---------------------------------------------------------------------------
# INDIVIDUAL / LAW_FIRM / EXCLUDE
# ---------------------------------------------------------------------------

def process_excludes(con, rows: dict[str, dict]) -> dict:
    stats = Counter()
    exclude_rows = [r for r in rows.values()
                    if r["manual_classification"].upper() in EXCLUDE_STATUS]
    print(f"\n=== EXCLUDE/INDIVIDUAL/LAW_FIRM ({len(exclude_rows)} unique CIKs) ===")
    for row in exclude_rows:
        cik = row["_cik_padded"]
        cls = row["manual_classification"].upper()
        status = EXCLUDE_STATUS[cls]
        notes = (row.get("notes") or "").strip() or f"auto-classified as {cls}"

        # Skip if already resolved to an entity (defense — shouldn't happen)
        already_entity = _cik_already_mapped(con, cik)
        if already_entity is not None:
            print(f"  [skip-mapped]  cik={cik} already eid={already_entity} ({cls})")
            stats[f"{cls}_skipped_already_entity"] += 1
            continue

        pending_key = f"cik:{cik}"
        existing = con.execute(
            "SELECT resolution_id, resolution_status FROM pending_entity_resolution "
            "WHERE pending_key = ? LIMIT 1",
            [pending_key],
        ).fetchone()
        if existing:
            rid, cur_status = existing
            if cur_status == status:
                stats[f"{cls}_already_flagged"] += 1
                continue
            con.execute(
                """UPDATE pending_entity_resolution
                     SET resolution_status = ?,
                         resolution_notes = ?,
                         resolved_by = ?,
                         resolved_at = CURRENT_TIMESTAMP
                     WHERE resolution_id = ?""",
                [status, notes[:500], SOURCE_TAG, rid],
            )
            stats[f"{cls}_updated"] += 1
            continue

        rid = con.execute("SELECT nextval('resolution_id_seq')").fetchone()[0]
        con.execute(
            """INSERT INTO pending_entity_resolution
                 (resolution_id, source_type, identifier_type, identifier_value,
                  resolution_status, pending_key, resolved_by, resolved_at,
                  resolution_notes)
               VALUES (?, '13DG', 'cik', ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
            [rid, cik, status, pending_key, SOURCE_TAG, notes[:500]],
        )
        stats[f"{cls}_inserted"] += 1
    return dict(stats)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staging", action="store_true",
                      help="Pass 1: MERGE + NEW_ENTITY against staging DB")
    mode.add_argument("--prod-exclusions", action="store_true",
                      help="Pass 2: INDIVIDUAL/LAW_FIRM/EXCLUDE against prod "
                           "pending_entity_resolution (not in staging scope)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Roll back transaction at the end; do not CHECKPOINT")
    args = ap.parse_args()

    if not os.path.exists(CSV_PATH):
        print(f"ERROR: research CSV not found at {CSV_PATH}", file=sys.stderr)
        return 2

    by_cik = _read_csv_deduped()
    print(f"Deduped CIKs: {len(by_cik)}")
    print("  by manual_classification:",
          dict(Counter(r["manual_classification"].upper() for r in by_cik.values())))

    if args.staging:
        db.set_staging_mode(True)
        print(f"resolve_13dg_filers.py [staging pass] — DB: {db.get_db_path()}")
        print(f"CSV: {CSV_PATH}")
        con = db.connect_write()
        try:
            con.execute("BEGIN TRANSACTION")
            merge_stats = process_merge(con, by_cik)
            new_stats = process_new_entity(con, by_cik)

            print("\n" + "=" * 60)
            print("SUMMARY (staging pass)")
            print("=" * 60)
            print(f"MERGE:       {merge_stats}")
            print(f"NEW_ENTITY:  {new_stats['stats']}")
            print(f"  classifications: {new_stats['classification_breakdown']}")

            if args.dry_run:
                con.execute("ROLLBACK")
                print("\n[DRY RUN] transaction rolled back — no changes persisted.")
            else:
                con.execute("COMMIT")
                con.execute("CHECKPOINT")
                print("\n[OK] transaction committed + checkpointed.")
        finally:
            con.close()
        return 0

    # prod-exclusions pass
    db.set_staging_mode(False)
    print(f"resolve_13dg_filers.py [prod-exclusions pass] — DB: {db.get_db_path()}")
    print(f"CSV: {CSV_PATH}")
    con = db.connect_write()
    try:
        con.execute("BEGIN TRANSACTION")
        excl_stats = process_excludes(con, by_cik)

        print("\n" + "=" * 60)
        print("SUMMARY (prod-exclusions pass)")
        print("=" * 60)
        print(f"EXCLUDE set: {excl_stats}")

        if args.dry_run:
            con.execute("ROLLBACK")
            print("\n[DRY RUN] transaction rolled back — no changes persisted.")
        else:
            con.execute("COMMIT")
            con.execute("CHECKPOINT")
            print("\n[OK] transaction committed + checkpointed.")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
