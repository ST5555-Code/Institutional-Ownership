#!/usr/bin/env python3
"""bootstrap_residual_advisers.py — staging-only seeding for 7 ETF advisers.

Creates entity rows for the residual-616 Tier B adviser set: ETF trust
sponsors whose ADV CRD is not yet mapped to an entity in the MDM.
Mirrors `scripts/bootstrap_etf_advisers.py` (2026-04-15 session, which
added Van Eck / Aptus / BondBloxx).

Seeds:
  1. Stone Ridge Asset Management LLC       — Stone Ridge Trust (14 series)
  2. Bitwise Investment Manager LLC         — Bitwise Funds Trust (11 series)
  3. Volatility Shares LLC                  — Volatility Shares Trust (11 series)
  4. Dupree & Company, Inc.                 — Dupree Mutual Funds (7 series)
                                              Distinct from the pre-existing
                                              eid 4135 "Dupree Financial
                                              Group, LLC" (different firm).
  5. Abacus FCF Advisors LLC                — Abacus FCF ETF Trust (6 series)
  6. Baron Capital Management, Inc.         — Baron ETF Trust (5 series)
  7. Grayscale Advisors                     — Grayscale Funds Trust (5 series)

Each gets the standard SCD row set:
  * entities (canonical_name, entity_type='institution')
  * entity_identifiers (cik + crd from adv_managers; CRD LTRIM'd)
  * entity_aliases (preferred=TRUE, alias_type='brand')
  * entity_classification_history
  * entity_rollup_history × 2 (economic_control_v1 + decision_maker_v1,
    rule_applied='self')

Designed to run AFTER `sync_staging.py` and BEFORE
`resolve_pending_series.py`. Prints assigned eids for wiring into
SUPPLEMENTARY_BRANDS.

Usage:
    python3 scripts/bootstrap_residual_advisers.py
"""
from __future__ import annotations

import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

# Curated seed list — verified against adv_managers on 2026-04-16.
# CIKs included when adv_managers carries one; CRDs are always present.
# strategy_inferred from adv_managers used to pick classification.
NEW_ADVISERS = [
    {
        "canonical": "Stone Ridge Asset Management LLC",
        "cik":       "0001584728",
        "crd":       "165598",
        "classification": "active",     # hedge_fund in ADV, active mgmt
        "source":    "residual_616_bootstrap",
    },
    {
        "canonical": "Bitwise Investment Manager LLC",
        "cik":       None,
        "crd":       "317943",
        "classification": "passive",    # passive crypto index ETFs
        "source":    "residual_616_bootstrap",
    },
    {
        "canonical": "Volatility Shares LLC",
        "cik":       "0001855529",
        "crd":       "321955",
        "classification": "active",     # leveraged/inverse ETFs
        "source":    "residual_616_bootstrap",
    },
    {
        "canonical": "Dupree & Company, Inc.",
        "cik":       None,
        "crd":       "1697",
        "classification": "active",     # active muni bond mgmt
        "source":    "residual_616_bootstrap",
    },
    {
        "canonical": "Abacus FCF Advisors LLC",
        "cik":       None,
        "crd":       "135152",
        "classification": "active",     # active thematic equity
        "source":    "residual_616_bootstrap",
    },
    {
        "canonical": "Baron Capital Management, Inc.",
        "cik":       None,
        "crd":       "110791",
        "classification": "active",     # active growth equity
        "source":    "residual_616_bootstrap",
    },
    {
        "canonical": "Grayscale Advisors",
        "cik":       None,
        "crd":       "314868",
        "classification": "passive",    # index-tracking crypto trusts
        "source":    "residual_616_bootstrap",
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
            print(f"  [reuse-crd]  {canonical:40s} → existing eid={existing[0]}")
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
            print(f"  [reuse-cik]  {canonical:40s} → existing eid={existing[0]}")
            return existing[0]

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

    print(f"  [created]    {canonical:40s}  eid={eid}  cik={spec['cik']}  "
          f"crd={spec['crd']}  classification={spec['classification']}")
    return eid


def main() -> None:
    """CLI entry."""
    db.set_staging_mode(True)
    print(f"bootstrap_residual_advisers.py — staging DB: {db.get_db_path()}")
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
        print(f"  {spec['canonical']:<42s} eid={results[spec['canonical']]}")


if __name__ == "__main__":
    main()
