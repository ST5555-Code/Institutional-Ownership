#!/usr/bin/env python3
"""apply_series_triage.py — apply int-21 unified series triage decisions.

Inputs:
  * Triage CSV (default: data/reports/unresolved_series_triage.csv)
      decision column values:
        RESOLVE_TO:<entity_name>   — point pending row at existing entity
        EXCLUDE:<reason>           — mark pending row as excluded_other
        NEW_ENTITY                 — resolve to a newly-minted entity
                                     (one entity per unique filer_cik,
                                      driven by the worksheet)
        ACCEPT_UNRESOLVED          — no-op (kept pending)

  * New-entity worksheet (default: data/reports/new_entity_worksheet.csv)
      one row per filer_cik, with manager_type, is_passive, rollup_target,
      inst_parent_name. 67 unique CIKs cover the 100 NEW_ENTITY series.

Two-pass design (mirrors resolve_13dg_filers.py):

  Pass 1 — staging (entity creation):
      For each of 67 filer_ciks create an institution entity in the staging
      DB with alias + cik identifier + classification + dual rollup history
      (economic_control_v1 + decision_maker_v1). Flows through the standard
      INF1 sync → diff → review → promote workflow.

  Pass 2 — prod (pending_entity_resolution updates):
      RESOLVE_TO (27): resolve entity name → entity_id via entities /
        entity_aliases, set status='resolved', resolved_entity_id=<eid>.
      EXCLUDE  (0):    set status='excluded_other', resolution_notes=<reason>.
      NEW_ENTITY (100 series across 67 CIKs): requires --manifest from the
        staging pass (so the resolved entity_id lines up with the promoted
        staging entity). Marks each series row resolved with the new eid.

Default is --dry-run. Pass --confirm to write.

Usage:
  # Pass 1 — staging entity creation
  python3 scripts/sync_staging.py
  python3 scripts/oneoff/apply_series_triage.py --staging --dry-run
  python3 scripts/oneoff/apply_series_triage.py --staging --confirm
  # … validate + diff + promote_staging --approved …

  # Pass 2 — prod pending_entity_resolution updates
  python3 scripts/oneoff/apply_series_triage.py --prod-updates --dry-run \\
      --manifest logs/int21_new_entity_manifest.csv
  python3 scripts/oneoff/apply_series_triage.py --prod-updates --confirm \\
      --manifest logs/int21_new_entity_manifest.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

SOURCE_TAG = "int-21_series_triage"
DEFAULT_TRIAGE = os.path.expanduser("~/Downloads/unresolved_series_triage_resolved.csv")
DEFAULT_WORKSHEET = os.path.expanduser("~/Downloads/new_entity_worksheet_filled.csv")
DEFAULT_MANIFEST = os.path.join(
    BASE_DIR, "logs", "int21_new_entity_manifest.csv",
)


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------
def _classify_decision(raw: str) -> tuple[str, str]:
    """Return (kind, detail) from a decision string."""
    d = (raw or "").strip()
    if d.startswith("RESOLVE_TO:"):
        return "RESOLVE_TO", d[len("RESOLVE_TO:"):].strip()
    if d.startswith("EXCLUDE:"):
        return "EXCLUDE", d[len("EXCLUDE:"):].strip() or "excluded"
    if d == "EXCLUDE":
        return "EXCLUDE", "excluded"
    if d == "NEW_ENTITY":
        return "NEW_ENTITY", ""
    if d == "ACCEPT_UNRESOLVED":
        return "ACCEPT_UNRESOLVED", ""
    return "UNKNOWN", d


def load_triage(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_kind"], r["_detail"] = _classify_decision(r.get("decision", ""))
        raw_cik = (r.get("filer_cik") or "").strip()
        # CSV stores filer_cik as numeric float ('1275214.0'); normalize.
        if raw_cik.endswith(".0"):
            raw_cik = raw_cik[:-2]
        r["_cik_padded"] = raw_cik.zfill(10) if raw_cik else ""
    return rows


def load_worksheet(path: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cik_raw = (row.get("filer_cik") or "").strip()
            if cik_raw.endswith(".0"):
                cik_raw = cik_raw[:-2]
            if not cik_raw:
                continue
            cik = cik_raw.zfill(10)
            row["_cik_padded"] = cik
            out[cik] = row
    return out


# ---------------------------------------------------------------------------
# Name → entity_id resolver (used by RESOLVE_TO + rollup_target lookups)
# ---------------------------------------------------------------------------
def _pick_by_aum(candidates: list[tuple[int, str]]) -> tuple[int, str]:
    """Pick the (eid, label) with highest 2025Q4 AUM in holdings_v2.

    Opens a read-only prod connection per call (infrequent). Mirrors the
    tiebreaker pattern in resolve_13dg_filers.py.
    """
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
    return sorted(candidates, key=lambda c: aum_by_eid.get(c[0], 0), reverse=True)[0]


_PARENT_SEEDS_CACHE: list[tuple[str, int, str]] | None = None


def _parent_seed_table(con) -> list[tuple[str, int, str]]:
    """Build (variant_upper, entity_id, canonical) table from PARENT_SEEDS.

    PARENT_SEEDS entries resolve to institution entity_ids by exact-match
    on entities.canonical_name. Includes both the canonical label and all
    declared variants. Preferred over AUM-tiebreak substring matches when
    possible because PARENT_SEEDS targets advisers, not underlying funds.
    """
    global _PARENT_SEEDS_CACHE  # pylint: disable=W0603  # module-level cache, built once per run
    if _PARENT_SEEDS_CACHE is not None:
        return _PARENT_SEEDS_CACHE
    try:
        from build_managers import PARENT_SEEDS
    except ImportError:
        _PARENT_SEEDS_CACHE = []
        return _PARENT_SEEDS_CACHE
    seed_rows = con.execute(
        "SELECT entity_id, canonical_name FROM entities WHERE entity_type = 'institution'"
    ).fetchall()
    canon_to_eid = {n: eid for eid, n in seed_rows}
    out: list[tuple[str, int, str]] = []
    for canonical, _strategy, variants in PARENT_SEEDS:
        eid = canon_to_eid.get(canonical)
        if not eid:
            continue
        out.append((canonical.upper(), eid, canonical))
        for v in variants:
            out.append((v.upper(), eid, canonical))
    _PARENT_SEEDS_CACHE = out
    return out


def resolve_entity_by_name(con, name: str) -> tuple[int | None, str]:
    """Return (entity_id, reason). None eid ⇒ not found.

    Tiers:
      1. PARENT_SEEDS canonical/variant exact (preferred — authoritative
         adviser-brand map; avoids AUM-tiebreak drifting to underlying funds)
      2. entities.canonical_name exact (case-insensitive)
      3. entity_aliases exact active (case-insensitive)
      4. entity_aliases word-boundary substring (padded guard) with AUM
         tiebreaker. Capped at 20 hits.
    """
    if not name:
        return None, "empty name"

    target = name.strip()
    target_up = target.upper()

    # Tier 1 — PARENT_SEEDS exact
    for variant, eid, canonical in _parent_seed_table(con):
        if variant == target_up:
            return eid, f"PARENT_SEED: {canonical}"

    # Tier 2 — entities.canonical_name exact
    rows = con.execute(
        "SELECT entity_id, canonical_name FROM entities "
        "WHERE LOWER(canonical_name) = LOWER(?)",
        [target],
    ).fetchall()
    if rows:
        eid, label = _pick_by_aum(rows)
        suffix = f" (+{len(rows) - 1} by-AUM)" if len(rows) > 1 else ""
        return eid, f"canonical exact: {label}{suffix}"

    # Tier 2 — alias exact active
    rows = con.execute(
        """SELECT DISTINCT entity_id, alias_name FROM entity_aliases
           WHERE LOWER(alias_name) = LOWER(?)
             AND valid_to = DATE '9999-12-31'""",
        [target],
    ).fetchall()
    if rows:
        eid, label = _pick_by_aum(rows)
        suffix = f" (+{len(rows) - 1} by-AUM)" if len(rows) > 1 else ""
        return eid, f"alias exact: {label}{suffix}"

    # Tier 3 — word-boundary substring on alias_name, AUM tiebreak
    padded = f"% {target} %"
    rows = con.execute(
        """SELECT DISTINCT entity_id, alias_name FROM entity_aliases
           WHERE (' ' || alias_name || ' ') ILIKE ?
             AND valid_to = DATE '9999-12-31'
           ORDER BY entity_id
           LIMIT 20""",
        [padded],
    ).fetchall()
    if rows:
        eid, label = _pick_by_aum(rows)
        suffix = f" (+{len(rows) - 1} by-AUM)" if len(rows) > 1 else ""
        return eid, f"alias substring {target!r} → {label}{suffix}"

    return None, f"no match for {target!r}"


# ---------------------------------------------------------------------------
# STAGING pass — NEW_ENTITY creations
# ---------------------------------------------------------------------------
def _cik_already_mapped(con, cik_padded: str) -> int | None:
    row = con.execute(
        """SELECT entity_id FROM entity_identifiers
             WHERE identifier_type = 'cik' AND identifier_value = ?
               AND valid_to = DATE '9999-12-31' LIMIT 1""",
        [cik_padded],
    ).fetchone()
    return row[0] if row else None


def _classification_from_passive(is_passive_raw: str) -> str:
    v = (is_passive_raw or "").strip().upper()
    if v == "TRUE":
        return "passive"
    if v == "FALSE":
        return "active"
    return "unknown"


def _plan_new_entities(
    con, triage: list[dict], worksheet: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    """Return (plan_rows, warnings). Each plan_row:
       {cik, name, classification, rollup_target_name, rollup_eid (or None),
        rollup_is_self (bool), series_ids (list[str]), existing_eid or None}.
    """
    warnings: list[str] = []

    ne_rows = [r for r in triage if r["_kind"] == "NEW_ENTITY"]
    series_by_cik: dict[str, list[str]] = defaultdict(list)
    for r in ne_rows:
        cik = r["_cik_padded"]
        sid = r.get("series_id", "")
        if cik and sid:
            series_by_cik[cik].append(sid)

    plan: list[dict] = []
    for cik, series in series_by_cik.items():
        wrow = worksheet.get(cik)
        if not wrow:
            warnings.append(f"CIK {cik}: in triage NEW_ENTITY but missing from worksheet")
            continue

        entity_name = (wrow.get("entity_name") or wrow.get("filer_name") or "").strip()
        classification = _classification_from_passive(wrow.get("is_passive"))
        rollup_raw = (wrow.get("rollup_target") or "").strip()
        rollup_is_self = rollup_raw.upper() == "SELF" or not rollup_raw

        rollup_eid: int | None = None
        rollup_resolution = ""
        if rollup_is_self:
            rollup_resolution = "SELF"
        else:
            eid, reason = resolve_entity_by_name(con, rollup_raw)
            if eid is None:
                # Fall back: try inst_parent_name if distinct
                alt = (wrow.get("inst_parent_name") or "").strip()
                if alt and alt.lower() != rollup_raw.lower():
                    eid, reason = resolve_entity_by_name(con, alt)
            if eid is None:
                warnings.append(
                    f"CIK {cik} ({entity_name}): rollup_target={rollup_raw!r} "
                    f"unresolved ({reason}); defaulting to SELF"
                )
                rollup_is_self = True
                rollup_resolution = f"FALLBACK_SELF ({reason})"
            else:
                rollup_eid = eid
                rollup_resolution = f"{reason} → eid={eid}"

        existing_eid = _cik_already_mapped(con, cik)

        plan.append({
            "cik": cik,
            "name": entity_name,
            "manager_type": wrow.get("manager_type", ""),
            "is_passive": wrow.get("is_passive", ""),
            "classification": classification,
            "rollup_target": rollup_raw,
            "rollup_is_self": rollup_is_self,
            "rollup_eid": rollup_eid,
            "rollup_resolution": rollup_resolution,
            "series_ids": series,
            "existing_eid": existing_eid,
        })
    return plan, warnings


def _execute_new_entities(
    con, plan: list[dict], write_manifest: str | None,
) -> tuple[int, dict[str, int]]:
    """Create staging entities per plan. Returns (created_count, cik→eid)."""
    created_count = 0
    manifest: dict[str, int] = {}

    for item in plan:
        cik = item["cik"]
        if item["existing_eid"] is not None:
            manifest[cik] = item["existing_eid"]
            continue

        eid = con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]
        con.execute(
            """INSERT INTO entities
                 (entity_id, entity_type, canonical_name, created_source, is_inferred)
               VALUES (?, 'institution', ?, ?, FALSE)""",
            [eid, item["name"], SOURCE_TAG],
        )
        con.execute(
            """INSERT INTO entity_aliases
                 (entity_id, alias_name, alias_type, is_preferred, preferred_key,
                  source_table, is_inferred, valid_from, valid_to)
               VALUES (?, ?, 'filing', TRUE, ?, ?, FALSE,
                       DATE '2020-01-01', DATE '9999-12-31')""",
            [eid, item["name"], eid, SOURCE_TAG],
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
               VALUES (?, ?, FALSE, 'medium', ?, FALSE,
                       DATE '2020-01-01', DATE '9999-12-31')""",
            [eid, item["classification"], SOURCE_TAG],
        )
        rollup_eid = eid if item["rollup_is_self"] else item["rollup_eid"]
        rule_label = "self" if item["rollup_is_self"] else "manual_worksheet"
        for rollup_type in ("economic_control_v1", "decision_maker_v1"):
            con.execute(
                """INSERT INTO entity_rollup_history
                     (entity_id, rollup_entity_id, rollup_type, rule_applied,
                      confidence, valid_from, valid_to, computed_at, source,
                      routing_confidence)
                   VALUES (?, ?, ?, ?, 'high',
                           DATE '2020-01-01', DATE '9999-12-31',
                           CURRENT_TIMESTAMP, ?, 'high')""",
                [eid, rollup_eid, rollup_type, rule_label, SOURCE_TAG],
            )
        manifest[cik] = eid
        created_count += 1

    if write_manifest:
        os.makedirs(os.path.dirname(write_manifest), exist_ok=True)
        with open(write_manifest, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filer_cik", "new_entity_id", "canonical_name"])
            for item in plan:
                eid = manifest.get(item["cik"])
                if eid is None:
                    continue
                w.writerow([item["cik"], eid, item["name"]])

    return created_count, manifest


def staging_pass(args) -> int:
    triage = load_triage(args.triage)
    worksheet = load_worksheet(args.worksheet)

    kind_counts = Counter(r["_kind"] for r in triage)
    print(f"Triage  : {args.triage}")
    print(f"Worksheet: {args.worksheet}")
    print(f"Triage rows: {len(triage)}  kinds: {dict(kind_counts)}")
    print(f"Worksheet rows: {len(worksheet)}")

    db.set_staging_mode(True)
    print(f"\nSTAGING DB: {db.get_db_path()}")

    con = db.connect_write()
    try:
        con.execute("BEGIN TRANSACTION")
        plan, warnings = _plan_new_entities(con, triage, worksheet)

        print(f"\n=== NEW_ENTITY plan: {len(plan)} CIKs ===")
        to_create = sum(1 for p in plan if p["existing_eid"] is None)
        already = sum(1 for p in plan if p["existing_eid"] is not None)
        print(f"  to_create  : {to_create}")
        print(f"  already_has_cik: {already}")
        if warnings:
            print(f"\nWARNINGS ({len(warnings)}):")
            for w in warnings:
                print(f"  [warn] {w}")
        print("\nPer-CIK detail (first 40):")
        for p in plan[:40]:
            eid_str = f"existing eid={p['existing_eid']}" if p["existing_eid"] else "NEW"
            print(
                f"  cik={p['cik']}  {eid_str:20s}  "
                f"{p['manager_type']:12s} cls={p['classification']:7s} "
                f"rollup={p['rollup_resolution']}  "
                f"name={p['name'][:45]!r}  series={len(p['series_ids'])}"
            )
        if len(plan) > 40:
            print(f"  … and {len(plan) - 40} more")

        if args.dry_run:
            con.execute("ROLLBACK")
            print("\n[DRY RUN] staging transaction rolled back — no writes.")
            # Also write a preview manifest for the prod-updates dry-run
            if args.manifest:
                os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
                with open(args.manifest, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["filer_cik", "new_entity_id", "canonical_name"])
                    for p in plan:
                        # dry-run: tag with placeholder so prod pass refuses --confirm
                        eid = p["existing_eid"] if p["existing_eid"] else "DRY_RUN_PLACEHOLDER"
                        w.writerow([p["cik"], eid, p["name"]])
                print(f"[DRY RUN] wrote preview manifest → {args.manifest}")
            return 0

        created, manifest = _execute_new_entities(con, plan, args.manifest)
        con.execute("COMMIT")
        try:
            con.execute("CHECKPOINT")
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] CHECKPOINT failed: {e}")
        print(f"\n[OK] staging pass committed. Created {created} new entities.")
        if args.manifest:
            print(f"     manifest → {args.manifest}")
    finally:
        con.close()
    return 0


# ---------------------------------------------------------------------------
# PROD pass — pending_entity_resolution updates
# ---------------------------------------------------------------------------
def _load_manifest(path: str) -> tuple[dict[str, int], set[str]]:
    """Return (cik→eid, cik_set_preview_only).

    preview_only set contains CIKs from a dry-run manifest where the eid was
    recorded as 'DRY_RUN_PLACEHOLDER'. Those CIKs are known to be in the
    plan but have no real eid yet, so prod updates cannot target them; the
    prod dry-run reports them as `would-link-post-promote`.
    """
    if not os.path.exists(path):
        return {}, set()
    out: dict[str, int] = {}
    preview: set[str] = set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            cik = (r.get("filer_cik") or "").strip().zfill(10)
            eid_raw = (r.get("new_entity_id") or "").strip()
            try:
                out[cik] = int(eid_raw)
            except ValueError:
                preview.add(cik)
    return out, preview


def _find_pending_by_series(con, series_id: str) -> tuple[int, str] | None:
    row = con.execute(
        """SELECT resolution_id, resolution_status FROM pending_entity_resolution
             WHERE identifier_type = 'series_id' AND identifier_value = ?
             LIMIT 1""",
        [series_id],
    ).fetchone()
    return (row[0], row[1]) if row else None


def prod_updates_pass(args) -> int:
    triage = load_triage(args.triage)
    manifest, preview_ciks = (
        _load_manifest(args.manifest) if args.manifest else ({}, set())
    )

    kind_counts = Counter(r["_kind"] for r in triage)
    print(f"Triage   : {args.triage}")
    print(f"Manifest : {args.manifest}  "
          f"({len(manifest)} real eids, {len(preview_ciks)} preview-only)")
    print(f"Triage rows: {len(triage)}  kinds: {dict(kind_counts)}")

    if not args.dry_run and preview_ciks:
        print(f"\nERROR: manifest {args.manifest} contains "
              f"{len(preview_ciks)} DRY_RUN_PLACEHOLDER entries. Re-run the "
              "staging pass with --confirm to allocate real entity_ids, "
              "promote staging → prod, then re-run this pass.",
              file=sys.stderr)
        return 2

    db.set_staging_mode(False)
    print(f"\nPROD DB: {db.get_db_path()}")
    con = db.connect_write()

    try:
        con.execute("BEGIN TRANSACTION")

        # --- RESOLVE_TO ---
        resolve_rows = [r for r in triage if r["_kind"] == "RESOLVE_TO"]
        print(f"\n=== RESOLVE_TO: {len(resolve_rows)} rows ===")
        resolve_stats = Counter()
        for r in resolve_rows:
            sid = r.get("series_id", "")
            name = r["_detail"]
            eid, reason = resolve_entity_by_name(con, name)
            if eid is None:
                print(f"  [UNRESOLVED]  series={sid}  name={name!r}  ({reason})")
                resolve_stats["unresolved"] += 1
                continue
            pending = _find_pending_by_series(con, sid)
            if pending is None:
                print(f"  [no-pending]  series={sid}  → eid={eid}  ({reason})")
                resolve_stats["no_pending_row"] += 1
                continue
            rid, status = pending
            if status == "resolved":
                resolve_stats["already_resolved"] += 1
                continue
            print(f"  [resolve]     series={sid}  → eid={eid}  ({reason})")
            if not args.dry_run:
                con.execute(
                    """UPDATE pending_entity_resolution
                         SET resolution_status = 'resolved',
                             resolved_entity_id = ?,
                             resolved_by = ?,
                             resolved_at = CURRENT_TIMESTAMP,
                             resolution_notes = ?
                         WHERE resolution_id = ?""",
                    [eid, SOURCE_TAG, f"int-21 RESOLVE_TO:{name}"[:500], rid],
                )
            resolve_stats["updated"] += 1

        # --- EXCLUDE ---
        exclude_rows = [r for r in triage if r["_kind"] == "EXCLUDE"]
        print(f"\n=== EXCLUDE: {len(exclude_rows)} rows ===")
        exclude_stats = Counter()
        for r in exclude_rows:
            sid = r.get("series_id", "")
            reason = r["_detail"] or "excluded"
            pending = _find_pending_by_series(con, sid)
            if pending is None:
                print(f"  [no-pending]  series={sid}  reason={reason!r}")
                exclude_stats["no_pending_row"] += 1
                continue
            rid, status = pending
            if status != "pending":
                exclude_stats[f"skip_status={status}"] += 1
                continue
            print(f"  [exclude]     series={sid}  reason={reason!r}")
            if not args.dry_run:
                con.execute(
                    """UPDATE pending_entity_resolution
                         SET resolution_status = 'excluded_other',
                             resolved_by = ?,
                             resolved_at = CURRENT_TIMESTAMP,
                             resolution_notes = ?
                         WHERE resolution_id = ?""",
                    [SOURCE_TAG, f"int-21 EXCLUDE:{reason}"[:500], rid],
                )
            exclude_stats["updated"] += 1

        # --- NEW_ENTITY series linking ---
        new_rows = [r for r in triage if r["_kind"] == "NEW_ENTITY"]
        print(f"\n=== NEW_ENTITY series linking: {len(new_rows)} series "
              f"(manifest: {len(manifest)} real, {len(preview_ciks)} preview) ===")
        new_stats = Counter()
        for r in new_rows:
            sid = r.get("series_id", "")
            cik = r["_cik_padded"]
            eid = manifest.get(cik)
            if eid is None:
                if cik in preview_ciks:
                    new_stats["preview_post_promote"] += 1
                else:
                    print(f"  [no-manifest] series={sid}  cik={cik}")
                    new_stats["no_manifest"] += 1
                continue
            pending = _find_pending_by_series(con, sid)
            if pending is None:
                new_stats["no_pending_row"] += 1
                continue
            rid, status = pending
            if status == "resolved":
                new_stats["already_resolved"] += 1
                continue
            if not args.dry_run:
                con.execute(
                    """UPDATE pending_entity_resolution
                         SET resolution_status = 'resolved',
                             resolved_entity_id = ?,
                             resolved_by = ?,
                             resolved_at = CURRENT_TIMESTAMP,
                             resolution_notes = ?
                         WHERE resolution_id = ?""",
                    [eid, SOURCE_TAG, "int-21 NEW_ENTITY creation", rid],
                )
            new_stats["updated"] += 1

        # Summary
        print("\n" + "=" * 60)
        print("PROD UPDATES SUMMARY")
        print("=" * 60)
        print(f"  RESOLVE_TO : {dict(resolve_stats)}")
        print(f"  EXCLUDE    : {dict(exclude_stats)}")
        print(f"  NEW_ENTITY : {dict(new_stats)}")

        if args.dry_run:
            con.execute("ROLLBACK")
            print("\n[DRY RUN] prod transaction rolled back — no writes.")
        else:
            con.execute("COMMIT")
            try:
                con.execute("CHECKPOINT")
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] CHECKPOINT failed: {e}")
            print("\n[OK] prod updates committed + checkpointed.")
    finally:
        con.close()
    return 0


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staging", action="store_true",
                      help="Pass 1: create NEW_ENTITY entities in staging.")
    mode.add_argument("--prod-updates", action="store_true",
                      help="Pass 2: apply RESOLVE_TO/EXCLUDE/NEW_ENTITY "
                           "updates to prod pending_entity_resolution.")

    write = ap.add_mutually_exclusive_group()
    write.add_argument("--dry-run", action="store_true", default=True,
                       help="Default. Plan + rollback. No DB writes.")
    write.add_argument("--confirm", action="store_true",
                       help="Execute the pass. Overrides --dry-run.")

    ap.add_argument("--triage", default=DEFAULT_TRIAGE)
    ap.add_argument("--worksheet", default=DEFAULT_WORKSHEET)
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST,
                    help="Staging-pass manifest path (CIK → new entity_id). "
                         "Written by --staging, read by --prod-updates.")
    args = ap.parse_args()

    # --confirm flips dry_run off
    if args.confirm:
        args.dry_run = False

    print("=" * 70)
    print(f"apply_series_triage.py  dry_run={args.dry_run}  "
          f"{'staging' if args.staging else 'prod-updates'}  "
          f"{datetime.now().isoformat(timespec='seconds')}")
    print("=" * 70)

    for p in (args.triage, args.worksheet):
        if args.staging and not os.path.exists(p):
            print(f"ERROR: missing input {p}", file=sys.stderr)
            return 2
    if args.prod_updates and not os.path.exists(args.triage):
        print(f"ERROR: missing triage {args.triage}", file=sys.stderr)
        return 2

    if args.staging:
        return staging_pass(args)
    return prod_updates_pass(args)


if __name__ == "__main__":
    raise SystemExit(main())
