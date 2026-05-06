#!/usr/bin/env python3
"""bootstrap_etf_advisers.py — staging-only seeding for 3 ETF brand advisers.

Creates entity rows for Van Eck Associates, Aptus Capital Advisors, and
BondBloxx Investment Management — three trust-level ETF sponsors that
have ADV records but no entity in the MDM. Each gets the standard SCD
row set:
  * entities (canonical_name, entity_type='institution')
  * entity_identifiers (cik + crd from adv_managers; LPAD'd)
  * entity_aliases (preferred=TRUE, alias_type='brand')
  * entity_classification_history
  * entity_rollup_history × 2 (economic_control_v1 + decision_maker_v1,
    rule_applied='self')

Designed to run AFTER `sync_staging.py` and BEFORE
`resolve_pending_series.py` so the new entity_ids are available for
SUPPLEMENTARY_BRANDS lookup.

Prints the assigned entity_ids on stdout for the operator to wire into
SUPPLEMENTARY_BRANDS in `resolve_pending_series.py`.

Usage:
    python3 scripts/bootstrap_etf_advisers.py
"""
from __future__ import annotations

import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

# Curated seed list — verified against adv_managers on 2026-04-15.
# strategy_inferred from adv_managers used to pick classification.
NEW_ADVISERS = [
    {
        "canonical": "Van Eck Associates",
        "cik":       "0000869178",
        "crd":       "105080",
        "classification": "active",   # adv_managers.strategy_inferred='active'
        "source":    "manual_etf_bootstrap",
    },
    {
        "canonical": "Aptus Capital Advisors",
        "cik":       None,             # no CIK in adv_managers
        "crd":       "167626",
        "classification": "active",
        "source":    "manual_etf_bootstrap",
    },
    {
        "canonical": "BondBloxx Investment Management",
        "cik":       None,
        "crd":       "317318",
        "classification": "passive",
        "source":    "manual_etf_bootstrap",
    },
]


def _ensure_staging_indexes(con) -> None:
    """Mirror the index/default setup from resolve_pending_series.py.

    sync_staging.py CTAS strips both. The bare `ON CONFLICT` semantics
    used by entity_sync.py (and the inserts below) need a unique index
    + default-date columns to avoid silently NULL-dating new rows.
    """
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
    """Insert one new institution + its full SCD row set. Returns eid.

    Idempotency — checked in this order (first hit wins):
      1. CRD match (LTRIM-normalized — `entity_identifiers` stores both
         padded and unpadded variants depending on source).
      2. CIK match (exact, including leading zeros).
      3. canonical_name exact match.
    Skips the create + reuses the existing eid when any of the above hit.
    """
    canonical = spec["canonical"]

    # 1. CRD lookup (normalized).
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
            print(f"  [reuse-crd] {canonical:40s} → existing eid={existing[0]}")
            return existing[0]

    # 2. CIK lookup (exact).
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
            print(f"  [reuse-cik] {canonical:40s} → existing eid={existing[0]}")
            return existing[0]

    # 3. canonical_name lookup.
    existing = con.execute(
        "SELECT entity_id FROM entities WHERE canonical_name = ?",
        [canonical],
    ).fetchone()
    if existing:
        print(f"  [reuse-name] {canonical:40s} → existing eid={existing[0]}")
        return existing[0]

    eid = con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]
    con.execute(
        """INSERT INTO entities
           (entity_id, entity_type, canonical_name, created_source, is_inferred)
           VALUES (?, 'institution', ?, ?, FALSE)""",
        [eid, canonical, spec["source"]],
    )

    # Identifiers (cik + crd, both when available)
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

    # Preferred brand alias
    con.execute(
        """INSERT INTO entity_aliases
             (entity_id, alias_name, alias_type, is_preferred,
              preferred_key, source_table, is_inferred,
              valid_from, valid_to)
           VALUES (?, ?, 'brand', TRUE, ?,
                   ?, FALSE, DATE '2000-01-01', DATE '9999-12-31')""",
        [eid, canonical, eid, spec["source"]],
    )

    # Classification
    con.execute(
        """INSERT INTO entity_classification_history
             (entity_id, classification, is_activist, confidence,
              source, is_inferred, valid_from, valid_to)
           VALUES (?, ?, FALSE, 'exact', ?, FALSE,
                   DATE '2000-01-01', DATE '9999-12-31')""",
        [eid, spec["classification"], spec["source"]],
    )

    # Self-rollup × 2 worldviews
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

    print(f"  [created]  {canonical:40s}  eid={eid}  cik={spec['cik']}  crd={spec['crd']}  classification={spec['classification']}")
    return eid


def main() -> None:
    db.set_staging_mode(True)
    print(f"bootstrap_etf_advisers.py — staging DB: {db.get_db_path()}")
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
    print("Wire these eids into SUPPLEMENTARY_BRANDS:")
    print(f"  Van Eck Associates              eid={results['Van Eck Associates']}")
    print(f"  Aptus Capital Advisors          eid={results['Aptus Capital Advisors']}")
    print(f"  BondBloxx Investment Management eid={results['BondBloxx Investment Management']}")


if __name__ == "__main__":
    main()
