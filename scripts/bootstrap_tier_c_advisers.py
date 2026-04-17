#!/usr/bin/env python3
"""bootstrap_tier_c_advisers.py — staging-only seeding for 6 Tier C advisers.

Second wave of ETF-sponsor bootstraps. Mirrors
`bootstrap_residual_advisers.py` (7 entities, eids 24348-24353 + 3375).

Seeds:
  1. Collaborative Fund Management, LLC       — Collaborative Investment Series Trust (15 series)
  2. Spinnaker Financial Advisors, LLC        — SPINNAKER ETF SERIES (15 series)
  3. Yorkville Capital Management, LLC        — Truth Social Funds (5 series)
  4. FundX Investment Group, LLC              — FundX Investment Trust (5 series)
  5. Procure AM, LLC                          — Procure ETF Trust II (1 series)
  6. Community Development Fund Advisors, LLC — THE COMMUNITY DEVELOPMENT FUND (1 series)

Only (6) has a CRD in adv_managers (281617). The other 5 trusts'
advisers have no ADV row as of 2026-04-17 — entities are created by
canonical_name only; CRD can be backfilled later via entity_sync.

Designed to run AFTER `sync_staging.py` and BEFORE
`resolve_pending_series.py`. Prints assigned eids for wiring into
SUPPLEMENTARY_BRANDS.

Usage:
    python3 scripts/bootstrap_tier_c_advisers.py
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
        "canonical": "Collaborative Fund Management, LLC",
        "cik":       None,
        "crd":       None,
        "classification": "active",
        "source":    "tier_c_bootstrap",
    },
    {
        "canonical": "Spinnaker Financial Advisors, LLC",
        "cik":       None,
        "crd":       None,
        "classification": "active",
        "source":    "tier_c_bootstrap",
    },
    {
        "canonical": "Yorkville Capital Management, LLC",
        "cik":       None,
        "crd":       None,
        "classification": "active",
        "source":    "tier_c_bootstrap",
    },
    {
        "canonical": "FundX Investment Group, LLC",
        "cik":       None,
        "crd":       None,
        "classification": "active",
        "source":    "tier_c_bootstrap",
    },
    {
        "canonical": "Procure AM, LLC",
        "cik":       None,
        "crd":       None,
        "classification": "active",
        "source":    "tier_c_bootstrap",
    },
    {
        "canonical": "Community Development Fund Advisors, LLC",
        "cik":       None,
        "crd":       "281617",
        "classification": "active",
        "source":    "tier_c_bootstrap",
    },
]


def _ensure_staging_indexes(con) -> None:
    """Mirror index/default setup from bootstrap_residual_advisers.py."""
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
    print(f"bootstrap_tier_c_advisers.py — staging DB: {db.get_db_path()}")
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
    for spec in NEW_ADVISERS:
        print(f"  {spec['canonical']:<48s} eid={results[spec['canonical']]}")


if __name__ == "__main__":
    main()
