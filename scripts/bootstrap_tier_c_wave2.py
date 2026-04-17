#!/usr/bin/env python3
"""bootstrap_tier_c_wave2.py — staging-only seeding for 3 more advisers.

Second wave of Tier C / Tier D bootstraps (2026-04-17 batch).
Mirrors `bootstrap_tier_c_advisers.py`.

Seeds:
  1. Palmer Square Capital Management LLC  — Palmer Square Funds Trust (4 series)
     CRD=155697, CIK=0001483325 (both in ADV)
  2. Rayliant Investment Research          — Rayliant Funds Trust (1 series)
     CRD=306119, CIK=None (ADV has CRD only)
  3. Victory Capital Holdings Inc          — Amundi/Victory rollup parent
     CIK=0001570827 (holding parent; operating sub eid=9130 already in MDM)
     Bootstrapped to carry the Amundi US rollup after the April 2025 merger.

Tema ETFs LLC (CRD=332224) was already in MDM as eid=7238 — no bootstrap
needed; it's wired via SUPPLEMENTARY_BRANDS directly.

Quaker Investment Trust (user-supplied CRD 114114 mismatched — that CRD
belongs to TRUNORTH FINANCIAL SERVICES in ADV, not Quaker) is SKIPPED
this round pending correct CRD lookup.

Usage:
    python3 scripts/bootstrap_tier_c_wave2.py
"""
from __future__ import annotations

import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

NEW_ADVISERS = [
    {
        "canonical": "Palmer Square Capital Management LLC",
        "cik":       "0001483325",
        "crd":       "155697",
        "classification": "active",
        "source":    "tier_c_wave2",
    },
    {
        "canonical": "Rayliant Investment Research",
        "cik":       None,
        "crd":       "306119",
        "classification": "active",
        "source":    "tier_c_wave2",
    },
    {
        "canonical": "Victory Capital Holdings Inc.",
        "cik":       "0001570827",
        "crd":       None,
        "classification": "active",
        "source":    "tier_c_wave2_victory",
    },
]


def _ensure_staging_indexes(con) -> None:
    try:
        con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_from "
                    "SET DEFAULT DATE '2000-01-01'")
        con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_to "
                    "SET DEFAULT DATE '9999-12-31'")
    except duckdb.Error as e:
        if "Dependency Error" in str(e):
            con.execute("DROP INDEX IF EXISTS ux_staging_eid_type_value")
            con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_from "
                        "SET DEFAULT DATE '2000-01-01'")
            con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_to "
                        "SET DEFAULT DATE '9999-12-31'")
        else:
            raise
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_staging_eid_type_value "
        "ON entity_identifiers (identifier_type, identifier_value, entity_id)"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_staging_er_triple "
        "ON entity_relationships (parent_entity_id, child_entity_id, "
        "relationship_type, valid_to)"
    )


def _create_entity(con, spec: dict) -> int:
    canonical = spec["canonical"]

    if spec["crd"]:
        existing = con.execute(
            """SELECT entity_id FROM entity_identifiers
               WHERE identifier_type = 'crd'
                 AND LTRIM(identifier_value, '0') = LTRIM(?, '0')
                 AND valid_to = DATE '9999-12-31'
               LIMIT 1""",
            [spec["crd"]],
        ).fetchone()
        if existing:
            print(f"  [reuse-crd]  {canonical:45s} → existing eid={existing[0]}")
            return existing[0]

    if spec["cik"]:
        existing = con.execute(
            """SELECT entity_id FROM entity_identifiers
               WHERE identifier_type = 'cik'
                 AND identifier_value = ?
                 AND valid_to = DATE '9999-12-31'
               LIMIT 1""",
            [spec["cik"]],
        ).fetchone()
        if existing:
            print(f"  [reuse-cik]  {canonical:45s} → existing eid={existing[0]}")
            return existing[0]

    existing = con.execute(
        "SELECT entity_id FROM entities WHERE canonical_name = ?",
        [canonical],
    ).fetchone()
    if existing:
        print(f"  [reuse-name] {canonical:45s} → existing eid={existing[0]}")
        return existing[0]

    eid = con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]
    con.execute(
        """INSERT INTO entities
           (entity_id, entity_type, canonical_name, created_source, is_inferred)
           VALUES (?, 'institution', ?, ?, FALSE)""",
        [eid, canonical, spec["source"]],
    )

    if spec["cik"]:
        con.execute(
            """INSERT INTO entity_identifiers
                 (entity_id, identifier_type, identifier_value,
                  confidence, source, is_inferred,
                  valid_from, valid_to)
               VALUES (?, 'cik', ?, 'exact', ?, FALSE,
                       DATE '2000-01-01', DATE '9999-12-31')""",
            [eid, spec["cik"], spec["source"]],
        )
    if spec["crd"]:
        con.execute(
            """INSERT INTO entity_identifiers
                 (entity_id, identifier_type, identifier_value,
                  confidence, source, is_inferred,
                  valid_from, valid_to)
               VALUES (?, 'crd', ?, 'exact', ?, FALSE,
                       DATE '2000-01-01', DATE '9999-12-31')""",
            [eid, spec["crd"].lstrip("0"), spec["source"]],
        )

    con.execute(
        """INSERT INTO entity_aliases
             (entity_id, alias_name, alias_type, is_preferred,
              preferred_key, source_table, is_inferred,
              valid_from, valid_to)
           VALUES (?, ?, 'brand', TRUE, ?,
                   ?, FALSE, DATE '2000-01-01', DATE '9999-12-31')""",
        [eid, canonical, eid, spec["source"]],
    )

    con.execute(
        """INSERT INTO entity_classification_history
             (entity_id, classification, is_activist, confidence,
              source, is_inferred, valid_from, valid_to)
           VALUES (?, ?, FALSE, 'exact', ?, FALSE,
                   DATE '2000-01-01', DATE '9999-12-31')""",
        [eid, spec["classification"], spec["source"]],
    )

    for rollup_type in ("economic_control_v1", "decision_maker_v1"):
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to, computed_at, source,
                  routing_confidence)
               VALUES (?, ?, ?, 'self', 'exact',
                       DATE '2000-01-01', DATE '9999-12-31',
                       CURRENT_TIMESTAMP, ?, 'high')""",
            [eid, eid, rollup_type, spec["source"]],
        )

    print(f"  [created]    {canonical:45s}  eid={eid}  cik={spec['cik']}  "
          f"crd={spec['crd']}  classification={spec['classification']}")
    return eid


def main() -> None:
    db.set_staging_mode(True)
    print(f"bootstrap_tier_c_wave2.py — staging DB: {db.get_db_path()}")
    con = db.connect_write()
    try:
        _ensure_staging_indexes(con)
        results: dict[str, int] = {}
        for spec in NEW_ADVISERS:
            results[spec["canonical"]] = _create_entity(con, spec)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    print()
    print("Wire these eids into SUPPLEMENTARY_BRANDS / DM14c apply:")
    for spec in NEW_ADVISERS:
        print(f"  {spec['canonical']:<48s} eid={results[spec['canonical']]}")


if __name__ == "__main__":
    main()
