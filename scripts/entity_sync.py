"""
entity_sync.py — Shared entity MDM feeder logic.

Used by:
  - build_entities.py (--reset full rebuild, Step 4 ncen relationships)
  - fetch_ncen.py (incremental per-row sync after each batch write)
  - Future: Phase 3 long-tail resolver, Phase 3.5 ADV Schedule A/B

All functions expect a DuckDB read-write connection to the STAGING DB.
All identifier conflict handling routes through entity_identifiers_staging
(Phase 2) instead of silently dropping via ON CONFLICT DO NOTHING.

Sentinel date 9999-12-31 = "currently active" throughout.
"""
from __future__ import annotations

# pylint: disable=too-many-arguments,too-many-positional-arguments,broad-exception-caught

import logging
from typing import NamedTuple

logger = logging.getLogger("entity_sync")

ACTIVE = "9999-12-31"


class SyncResult(NamedTuple):
    entity_id: int
    was_created: bool
    conflict_logged: bool


# =============================================================================
# Core: get-or-create by identifier
# =============================================================================
def get_or_create_entity_by_identifier(
    con,
    id_type: str,
    id_value: str,
    name: str,
    entity_type: str,
    source: str,
    *,
    is_inferred: bool = True,
) -> SyncResult:
    """
    Look up an entity by identifier. If found, return it. If not found, create
    a new entity and attempt to attach the identifier.

    If the identifier is already claimed by another entity (active mapping
    exists), the new entity is still created but the identifier is logged to
    entity_identifiers_staging with conflict_reason='duplicate_active_mapping'
    and the new entity has NO identifier in the canonical table.

    Returns SyncResult(entity_id, was_created, conflict_logged).
    """
    if not id_value:
        raise ValueError(f"id_value is required (type={id_type})")

    # 1. Lookup existing active mapping
    existing = con.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type = ? AND identifier_value = ?
             AND valid_to = DATE '9999-12-31'""",
        [id_type, str(id_value)],
    ).fetchone()
    if existing:
        return SyncResult(existing[0], False, False)

    # 2. Create new entity
    eid = con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]
    con.execute(
        """INSERT INTO entities
           (entity_id, entity_type, canonical_name, created_source, is_inferred)
           VALUES (?, ?, ?, ?, ?)""",
        [eid, entity_type, name or f"{id_type.upper()} {id_value}", source, is_inferred],
    )

    # 3. Attempt to insert identifier
    result = con.execute(
        """INSERT INTO entity_identifiers
           (entity_id, identifier_type, identifier_value, confidence, source, is_inferred)
           VALUES (?, ?, ?, 'exact', ?, ?)
           ON CONFLICT DO NOTHING
           RETURNING entity_id""",
        [eid, id_type, str(id_value), source, is_inferred],
    ).fetchall()

    if result:
        return SyncResult(eid, True, False)

    # 4. Conflict — identifier was claimed between our check and insert (unlikely
    #    in single-writer DuckDB but possible across transactions), or our own
    #    transaction inserted it earlier. Log to staging.
    claimant = con.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type = ? AND identifier_value = ?
             AND valid_to = DATE '9999-12-31'""",
        [id_type, str(id_value)],
    ).fetchone()
    log_identifier_conflict(
        con, eid, id_type, id_value,
        existing_entity_id=claimant[0] if claimant else None,
        reason="duplicate_active_mapping",
        source=source,
    )
    return SyncResult(eid, True, True)


# =============================================================================
# Convenience wrappers
# =============================================================================
def get_or_create_entity_by_crd(
    con, crd: str, name: str, source: str, *, is_inferred: bool = True,
) -> SyncResult:
    return get_or_create_entity_by_identifier(
        con, "crd", crd, name, "institution", source, is_inferred=is_inferred,
    )


def get_or_create_entity_by_cik(
    con, cik: str, name: str, source: str, *, is_inferred: bool = True,
) -> SyncResult:
    return get_or_create_entity_by_identifier(
        con, "cik", cik, name, "institution", source, is_inferred=is_inferred,
    )


def get_or_create_fund_entity(
    con, series_id: str, name: str, source: str, *, is_inferred: bool = True,
) -> SyncResult:
    return get_or_create_entity_by_identifier(
        con, "series_id", series_id, name, "fund", source, is_inferred=is_inferred,
    )


# =============================================================================
# Relationship insertion
# =============================================================================
def insert_relationship_idempotent(
    con,
    parent_id: int,
    child_id: int,
    rel_type: str,
    control_type: str,
    is_primary: bool,
    confidence: str,
    source: str,
    *,
    is_inferred: bool = True,
) -> bool:
    """
    Insert an entity_relationship row if one doesn't already exist for this
    (parent, child, type) combination. Returns True if inserted.

    For primary relationships: checks DB for an existing active primary parent
    on this child. If one exists from a different source, logs conflict and
    skips. This replaces the in-memory has_primary_parent set from Phase 1
    with a DB query, making it safe for both batch and incremental paths.
    """
    if is_primary:
        existing_primary = con.execute(
            """SELECT parent_entity_id, source FROM entity_relationships
               WHERE child_entity_id = ? AND is_primary = TRUE
                 AND valid_to = DATE '9999-12-31'""",
            [child_id],
        ).fetchone()
        if existing_primary:
            logger.debug(
                "primary_parent_exists child=%s existing_parent=%s new_parent=%s",
                child_id, existing_primary[0], parent_id,
            )
            return False

    rid = con.execute("SELECT nextval('relationship_id_seq')").fetchone()[0]
    primary_key = child_id if is_primary else None
    result = con.execute(
        """INSERT INTO entity_relationships
           (relationship_id, parent_entity_id, child_entity_id, relationship_type,
            control_type, is_primary, primary_parent_key, confidence, source,
            is_inferred, valid_from, valid_to)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATE '2000-01-01', DATE '9999-12-31')
           ON CONFLICT DO NOTHING
           RETURNING relationship_id""",
        [rid, parent_id, child_id, rel_type, control_type, is_primary, primary_key,
         confidence, source, is_inferred],
    ).fetchall()
    return len(result) > 0


# =============================================================================
# Conflict logging
# =============================================================================
def log_identifier_conflict(
    con,
    entity_id: int,
    id_type: str,
    id_value: str,
    existing_entity_id: int | None,
    reason: str,
    source: str,
    *,
    notes: str | None = None,
) -> int:
    """Insert a row into entity_identifiers_staging. Returns staging_id."""
    sid = con.execute("SELECT nextval('identifier_staging_id_seq')").fetchone()[0]
    con.execute(
        """INSERT INTO entity_identifiers_staging
           (staging_id, entity_id, identifier_type, identifier_value,
            confidence, source, conflict_reason, existing_entity_id, notes)
           VALUES (?, ?, ?, ?, 'exact', ?, ?, ?, ?)""",
        [sid, entity_id, id_type, str(id_value), source, reason,
         existing_entity_id, notes],
    )
    logger.info(
        "identifier_conflict_staged staging_id=%s type=%s value=%s "
        "entity=%s existing=%s reason=%s source=%s",
        sid, id_type, id_value, entity_id, existing_entity_id, reason, source,
    )
    return sid


# =============================================================================
# N-CEN row sync (the main feeder entry point)
# =============================================================================
def sync_from_ncen_row(
    con,
    adviser_name: str | None,
    adviser_crd: str | None,
    series_id: str | None,
    role: str,
    source: str = "ncen_adviser_map",
) -> dict:
    """
    Process one ncen_adviser_map row into entity relationships.

    1. Resolve adviser entity by CRD (get-or-create)
    2. Resolve fund entity by series_id (get-or-create)
    3. Insert relationship (fund_sponsor primary for 'adviser', sub_adviser
       non-primary for 'subadviser')

    Returns dict with keys: adviser_entity_id, fund_entity_id, relationship_inserted,
    adviser_created, fund_created, adviser_conflict, fund_conflict, skipped_reason.
    """
    result = {
        "adviser_entity_id": None,
        "fund_entity_id": None,
        "relationship_inserted": False,
        "adviser_created": False,
        "fund_created": False,
        "adviser_conflict": False,
        "fund_conflict": False,
        "skipped_reason": None,
    }

    # 1. Resolve adviser
    if not adviser_crd:
        result["skipped_reason"] = "no_adviser_crd"
        return result
    adv = get_or_create_entity_by_crd(
        con, adviser_crd, adviser_name or f"CRD {adviser_crd}", source,
    )
    result["adviser_entity_id"] = adv.entity_id
    result["adviser_created"] = adv.was_created
    result["adviser_conflict"] = adv.conflict_logged

    # 2. Resolve fund
    if not series_id:
        result["skipped_reason"] = "no_series_id"
        return result
    fund = get_or_create_fund_entity(
        con, series_id, series_id, source,  # name will be series_id if fund_universe doesn't have it
    )
    result["fund_entity_id"] = fund.entity_id
    result["fund_created"] = fund.was_created
    result["fund_conflict"] = fund.conflict_logged

    # 3. Insert relationship
    if role == "adviser":
        inserted = insert_relationship_idempotent(
            con, adv.entity_id, fund.entity_id, "fund_sponsor", "control",
            True, "exact", source,
        )
    elif role == "subadviser":
        inserted = insert_relationship_idempotent(
            con, adv.entity_id, fund.entity_id, "sub_adviser", "advisory",
            False, "exact", source,
        )
    else:
        result["skipped_reason"] = f"unknown_role_{role}"
        return result

    result["relationship_inserted"] = inserted
    return result


# =============================================================================
# Phase 3 — SEC company search resolver
# =============================================================================
SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}


def resolve_cik_via_sec(cik: str, session=None) -> dict | None:
    """
    Resolve a CIK via SEC EDGAR submissions API.

    Calls https://data.sec.gov/submissions/CIK{padded}.json and extracts:
      name, sic, sicDescription, category, stateOfIncorporation

    Rate limit: caller is responsible for throttling to 5 req/s.
    Returns dict on success, None on failure (404, timeout, parse error).
    """
    import time

    padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"

    requester = session
    if requester is None:
        import requests
        requester = requests

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requester.get(url, headers=SEC_HEADERS, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "cik": cik,
                    "name": data.get("name"),
                    "sic": data.get("sic"),
                    "sicDescription": data.get("sicDescription"),
                    "category": data.get("category"),
                    "stateOfIncorporation": data.get("stateOfIncorporation"),
                    "entityType": data.get("entityType"),
                    "tickers": data.get("tickers", []),
                }
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 503):
                wait = 2 ** (attempt + 1)
                logger.debug("SEC %s for CIK %s, retrying in %ss", resp.status_code, cik, wait)
                time.sleep(wait)
                continue
        except Exception as e:
            logger.debug("SEC request failed for CIK %s: %s", cik, str(e)[:100])
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None


# =============================================================================
# Phase 3 — SIC → classification mapper
# =============================================================================
_SIC_CLASSIFICATION_MAP = {
    # State commercial banks
    range(6020, 6030): "active",
    # Savings institutions
    range(6030, 6037): "active",
    # Security brokers and dealers
    (6211,): "active",
    # Investment advice
    (6282,): "active",
    # Investment offices NEC (holding companies, family offices, hedge funds)
    (6726,): "hedge_fund",
    # Finance services
    (6199,): "active",
    # Insurance
    range(6310, 6400): "active",
    # Trusts
    range(6710, 6727): "active",
}


def classify_from_sic(sic_code: str | int | None) -> str:
    """
    Map a SIC code to an entity classification.

    Returns one of: 'active', 'hedge_fund', 'unknown'.
    Financial SIC codes (6xxx) are mapped to specific classifications.
    Non-financial or unrecognized codes return 'unknown'.
    """
    if not sic_code:
        return "unknown"
    try:
        code = int(sic_code)
    except (ValueError, TypeError):
        return "unknown"
    for sic_range, classification in _SIC_CLASSIFICATION_MAP.items():
        if code in sic_range:
            return classification
    return "unknown"


# =============================================================================
# Phase 3 — Parent matcher (fuzzy match against existing parent aliases)
# =============================================================================
def attempt_parent_match(
    con,
    entity_id: int,
    resolved_name: str,
    *,
    threshold: int = 85,
) -> dict:
    """
    Attempt to match a resolved entity name against existing parent entities'
    aliases using fuzzy matching (rapidfuzz token_sort_ratio).

    Only matches against entities that ARE rollup targets for at least one
    other entity (i.e., actual parents in entity_rollup_history), to avoid
    matching against random standalone filers.

    If match found (score >= threshold):
      - Inserts entity_relationship (parent_brand, control, is_primary=TRUE)
      - Returns {"matched": True, "parent_entity_id": ..., "parent_name": ..., "score": ...}
    If no match:
      - Returns {"matched": False, "best_name": ..., "best_score": ...}

    Never creates new parent entities.
    """
    from rapidfuzz import fuzz

    if not resolved_name:
        return {"matched": False, "best_name": None, "best_score": 0}

    # Check if this entity already has a non-self rollup parent
    existing = con.execute("""
        SELECT rollup_entity_id FROM entity_rollup_history
        WHERE entity_id = ? AND rollup_type = 'economic_control_v1'
          AND valid_to = DATE '9999-12-31' AND rule_applied != 'self'
    """, [entity_id]).fetchone()
    if existing:
        return {"matched": True, "parent_entity_id": existing[0],
                "parent_name": "(already matched)", "score": 100, "skipped": True}

    # Load aliases of entities that are actual parents (rollup targets)
    parent_aliases = con.execute("""
        SELECT DISTINCT ea.entity_id, ea.alias_name
        FROM entity_aliases ea
        JOIN (
            SELECT DISTINCT rollup_entity_id
            FROM entity_rollup_history
            WHERE rule_applied != 'self' AND valid_to = DATE '9999-12-31'
        ) parents ON ea.entity_id = parents.rollup_entity_id
        WHERE ea.valid_to = DATE '9999-12-31'
    """).fetchall()

    resolved_upper = resolved_name.upper()
    best_score = 0
    best_parent_id = None
    best_parent_name = None

    for parent_eid, alias_name in parent_aliases:
        score = fuzz.token_sort_ratio(resolved_upper, (alias_name or "").upper())
        if score > best_score:
            best_score = score
            best_parent_id = parent_eid
            best_parent_name = alias_name

    if best_score >= threshold and best_parent_id is not None:
        inserted = insert_relationship_idempotent(
            con, best_parent_id, entity_id, "parent_brand", "control",
            True, "medium", "fuzzy_match", is_inferred=False,
        )
        if inserted:
            # Update rollup: close old self-rollup, insert parent rollup
            con.execute("""
                UPDATE entity_rollup_history
                SET valid_to = CURRENT_DATE
                WHERE entity_id = ? AND rollup_type = 'economic_control_v1'
                  AND valid_to = DATE '9999-12-31'
            """, [entity_id])
            con.execute("""
                INSERT INTO entity_rollup_history
                  (entity_id, rollup_entity_id, rollup_type, rule_applied,
                   confidence, valid_from, valid_to)
                VALUES (?, ?, 'economic_control_v1', 'parent_brand',
                        'medium', CURRENT_DATE, DATE '9999-12-31')
            """, [entity_id, best_parent_id])
        return {
            "matched": True,
            "parent_entity_id": best_parent_id,
            "parent_name": best_parent_name,
            "score": best_score,
        }

    return {
        "matched": False,
        "best_name": best_parent_name,
        "best_score": best_score,
    }


def update_classification_from_sic(
    con, entity_id: int, sic_code: str | int | None, source: str = "SEC_SIC",
) -> bool:
    """
    Update entity_classification_history if current classification is 'unknown'
    and SIC code maps to a known classification. SCD Type 2: closes old row,
    inserts new row. Returns True if updated.
    """
    new_cls = classify_from_sic(sic_code)
    if new_cls == "unknown":
        return False

    current = con.execute("""
        SELECT classification FROM entity_classification_history
        WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
    """, [entity_id]).fetchone()
    if not current or current[0] != "unknown":
        return False

    con.execute("""
        UPDATE entity_classification_history
        SET valid_to = CURRENT_DATE
        WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
    """, [entity_id])
    con.execute("""
        INSERT INTO entity_classification_history
          (entity_id, classification, is_activist, confidence, source,
           is_inferred, valid_from, valid_to)
        VALUES (?, ?, FALSE, 'medium', ?, FALSE, CURRENT_DATE, DATE '9999-12-31')
    """, [entity_id, new_cls, source])
    return True
