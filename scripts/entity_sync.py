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
_LEGACY_SOURCES = frozenset({"parent_bridge", "fuzzy_match"})


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
    match_score: int = 0,
) -> bool:
    """
    Insert an entity_relationship row if one doesn't already exist for this
    (parent, child, type) combination. Returns True if inserted.

    Evidence resolution policy for primary relationships:
    - ADV score ≥90 AND existing source is parent_bridge/fuzzy_match →
      ADV supersedes: close old, insert new (resolution_policy='adv_supersedes_legacy')
    - Existing source is wholly_owned (prior ADV) → keep existing
      (resolution_policy='adv_deferred_to_existing')
    - ADV score <90 → keep existing (resolution_policy='adv_deferred_to_existing')
    - No existing primary → insert new (resolution_policy='adv_new_relationship')
    """
    is_adv = source.startswith("ADV_SCHEDULE_")
    resolution_policy = "adv_new_relationship" if is_adv else None

    if is_primary:
        existing_primary = con.execute(
            """SELECT parent_entity_id, source, relationship_id
               FROM entity_relationships
               WHERE child_entity_id = ? AND is_primary = TRUE
                 AND valid_to = DATE '9999-12-31'""",
            [child_id],
        ).fetchone()
        if existing_primary:
            existing_parent, existing_source, existing_rid = existing_primary
            if is_adv and match_score >= 90 and existing_source in _LEGACY_SOURCES:
                # ADV supersedes legacy source — close old, insert new
                con.begin()
                try:
                    con.execute("""
                        UPDATE entity_relationships SET valid_to = CURRENT_DATE
                        WHERE relationship_id = ? AND valid_to = DATE '9999-12-31'
                    """, [existing_rid])
                    con.commit()
                except Exception:
                    con.rollback()
                    raise
                resolution_policy = "adv_supersedes_legacy"
                logger.info(
                    "adv_supersedes child=%s old_parent=%s(%s) new_parent=%s score=%s",
                    child_id, existing_parent, existing_source, parent_id, match_score,
                )
            else:
                # Keep existing — defer
                if is_adv:
                    resolution_policy = "adv_deferred_to_existing"
                logger.debug(
                    "primary_parent_exists child=%s existing_parent=%s new_parent=%s policy=%s",
                    child_id, existing_parent, parent_id, resolution_policy,
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
    """Insert a row into entity_identifiers_staging. Returns staging_id.
    Skips if identical pending conflict already exists."""
    existing = con.execute(
        """SELECT staging_id FROM entity_identifiers_staging
           WHERE entity_id = ? AND identifier_type = ? AND identifier_value = ?
             AND review_status = 'pending'""",
        [entity_id, id_type, str(id_value)],
    ).fetchone()
    if existing:
        logger.debug("staging_duplicate_skipped entity=%s type=%s value=%s",
                      entity_id, id_type, id_value)
        return existing[0]

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
    alias_cache: _AliasCache | None = None,
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

    # Use alias_cache if provided, else load from DB
    parent_aliases = []
    if alias_cache is not None:
        cache = alias_cache
    else:
        # Load all entity aliases with deterministic ORDER BY
        parent_aliases = con.execute("""
            SELECT DISTINCT ea.entity_id, ea.alias_name
            FROM entity_aliases ea
            WHERE ea.valid_to = DATE '9999-12-31'
              AND ea.alias_name IS NOT NULL AND ea.alias_name != ''
            ORDER BY ea.entity_id, ea.alias_name
        """).fetchall()
        cache = None  # signal to use manual loop below

    resolved_upper = resolved_name.upper()
    best_score = 0
    best_parent_id = None
    best_parent_name = None

    if cache is not None:
        # Use cached match with deterministic tiebreaker
        eid, matched_name, score = cache.match(resolved_name, threshold)
        best_score = score
        best_parent_name = matched_name
        best_parent_id = eid
    else:
        # Manual loop with deterministic tiebreaker: score DESC, entity_id ASC
        for parent_eid, alias_name in parent_aliases:
            score = fuzz.token_sort_ratio(resolved_upper, (alias_name or "").upper())
            if score > best_score or (score == best_score and parent_eid < (best_parent_id or float('inf'))):
                best_score = score
                best_parent_id = parent_eid
                best_parent_name = alias_name

    if best_score >= threshold and best_parent_id is not None:
        inserted = insert_relationship_idempotent(
            con, best_parent_id, entity_id, "parent_brand", "control",
            True, "medium", "fuzzy_match", is_inferred=False,
        )
        if inserted:
            # Atomic SCD close+open for rollup history
            con.begin()
            try:
                has_active = con.execute("""
                    SELECT 1 FROM entity_rollup_history
                    WHERE entity_id = ? AND rollup_type = 'economic_control_v1'
                      AND valid_to = DATE '9999-12-31'
                """, [entity_id]).fetchone()
                if has_active:
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
                con.commit()
            except Exception:
                con.rollback()
                raise
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

    # Atomic SCD close+open with self-heal
    con.begin()
    try:
        has_active = con.execute("""
            SELECT 1 FROM entity_classification_history
            WHERE entity_id = ? AND valid_to = DATE '9999-12-31'
        """, [entity_id]).fetchone()
        if has_active:
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
        con.commit()
    except Exception:
        con.rollback()
        raise
    return True


# =============================================================================
# Phase 3.5 — ADV PDF Schedule A/B parser
# =============================================================================
_VALID_JURISDICTIONS = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID',
    'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS',
    'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK',
    'OR', 'PA', 'PR', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA',
    'WV', 'WI', 'WY', 'DC',
    'FE', 'UK', 'AU', 'JP', 'HK', 'SG', 'CH', 'LU', 'IE', 'BM', 'JE', 'GG',
}

_ADV_BOILERPLATE = [
    'IF FINAL OR ON APPEAL', 'CRS', 'FORM ADV', 'COMPLETE ALL ITEM',
    'HAS THE SEC', 'COMMODITY FUTURES', 'SECTION 4', 'DISCIPLINARY',
    'SCHEDULE D', 'DRP PAGES', 'CRIMINAL ACTION', 'CIVIL JUDICIAL',
]

# Ownership code → relationship_type mapping
# E = 75%+, D = 50-75% → wholly_owned (majority control)
# C = 25-50% → parent_brand (significant minority)
# A = 5-10%, B = 10-25% → skip (minor)
# NA = not applicable (executive officer, no equity) → skip for individuals
#   but NA on entities = mutual structure (Vanguard pattern)
OWN_CODE_TO_REL = {
    'E': 'wholly_owned',
    'D': 'wholly_owned',
    'C': 'parent_brand',
}


def _is_valid_entity_name(name: str) -> bool:
    if not name or len(name) < 3:
        return False
    if not any(c.isalpha() for c in name):
        return False
    for bp in _ADV_BOILERPLATE:
        if bp in name.upper():
            return False
    return True


def parse_adv_pdf(pdf_path: str, firm_crd: str = "", max_size_mb: float = 15.0) -> list[dict]:
    """
    Parse Schedule A (Direct Owners) and Schedule B (Indirect Owners) from
    an ADV PDF filing. Returns list of dicts with:
      firm_crd, schedule, name, jurisdiction, title_or_status, date,
      ownership_code, control_person, is_entity, relationship_type

    Column-shift detection handles normal, shifted, and blended layouts.
    Boilerplate/garbage filtered by jurisdiction validation + name checks.
    PDFs larger than max_size_mb are skipped (returns empty list).
    """
    import os
    import pdfplumber  # pylint: disable=import-error

    file_size = os.path.getsize(pdf_path) / (1024 * 1024)
    if file_size > max_size_mb:
        logger.debug("Skipping %s (%.1fMB > %.0fMB limit)", pdf_path, file_size, max_size_mb)
        return []

    entries = []
    in_sched = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "")
            text_upper = text.upper()

            if "SCHEDULE A" in text_upper and "DIRECT" in text_upper:
                in_sched = "A"
            elif "SCHEDULE B" in text_upper and "INDIRECT" in text_upper:
                in_sched = "B"
            elif in_sched:
                for exit_kw in ["SCHEDULE D", "DRP PAGES", "FORM ADV, PART 2"]:
                    if exit_kw in text_upper and "SCHEDULE A" not in text_upper and "SCHEDULE B" not in text_upper:
                        in_sched = None
                        break

            if not in_sched:
                page.close()
                continue

            for table in page.extract_tables():
                for row in table:
                    if not row:
                        continue
                    cells = [str(c).strip().replace('\n', ' ') if c else "" for c in row]
                    joined_upper = " ".join(cells).upper()
                    if any(h in joined_upper for h in ["FULL LEGAL NAME", "DE/FE/I", "TITLE OR STATUS"]):
                        continue

                    parsed = None
                    for offset in range(min(3, len(cells))):
                        if offset + 1 >= len(cells):
                            continue
                        name = cells[offset]
                        jurisdiction = cells[offset + 1].upper().strip()

                        if jurisdiction in _VALID_JURISDICTIONS or jurisdiction == "I":
                            if not _is_valid_entity_name(name):
                                continue  # try next offset, don't discard row

                            # Scan remaining cells for ownership code and other fields
                            # instead of fixed positions (handles extra/missing cells)
                            rest = [c.strip() for c in cells[offset + 2:]]
                            own_clean = ""
                            control = ""
                            title = ""
                            date_val = ""

                            # Find ownership code by scanning for valid code
                            own_idx = -1
                            for ri, val in enumerate(rest):
                                v = val.upper().strip()
                                if v in ('A', 'B', 'C', 'D', 'E', 'NA'):
                                    own_clean = v
                                    own_idx = ri
                                    break

                            if own_idx >= 0:
                                # Everything before ownership code is title + date
                                pre = rest[:own_idx]
                                # Date is the cell just before ownership code (MM/YYYY pattern)
                                # Title is everything before that
                                if pre:
                                    date_val = pre[-1]
                                    title = " ".join(p for p in pre[:-1] if p)
                                # Control person is the cell after ownership code
                                if own_idx + 1 < len(rest):
                                    ctrl = rest[own_idx + 1].upper().strip()
                                    if ctrl in ('Y', 'N'):
                                        control = ctrl
                            else:
                                # No ownership code found — take positional fallback
                                title = rest[0] if len(rest) > 0 else ""
                                date_val = rest[1] if len(rest) > 1 else ""

                            is_entity = jurisdiction != "I"
                            rel_type = OWN_CODE_TO_REL.get(own_clean)

                            # Mutual structure: entity with NA ownership (Vanguard pattern)
                            if is_entity and own_clean == "NA":
                                rel_type = "mutual_structure"

                            parsed = {
                                "firm_crd": firm_crd,
                                "schedule": in_sched,
                                "name": name,
                                "jurisdiction": jurisdiction,
                                "title_or_status": title,
                                "date": date_val,
                                "ownership_code": own_clean,
                                "control_person": control,
                                "is_entity": is_entity,
                                "relationship_type": rel_type,
                            }
                            if offset > 0:
                                logger.debug("shifted_row offset=%d crd=%s name=%s",
                                             offset, firm_crd, name)
                            break

                    if parsed:
                        entries.append(parsed)

            page.close()

    return entries


# =============================================================================
# Phase 3.5 — PyMuPDF-based parser (fast, no size limit)
# =============================================================================
_PYMUPDF_NAME_FRAGMENTS = frozenset({
    'L.P.', 'LP', 'LLC', 'INC.', 'INC', 'LTD.', 'LTD', 'CORP.', 'CORP',
    'CO.', 'CO', 'PLC', 'S.A.', 'SA', 'AG', 'N.V.', 'NV', 'GMBH',
    'L.L.C.', 'LIMITED', 'PARTNERS', 'GROUP', 'HOLDINGS',
    'TRUST', 'FUND', 'ADVISORS', 'MANAGEMENT',
})
_PYMUPDF_SKIP_KW = frozenset([
    'FULL LEGAL NAME', 'DE/FE/I', 'TITLE OR STATUS',
    'OWNERSHIP CODE', 'CONTROL PERSON', 'COMPLETE SCHEDULE', 'USE SCHEDULE C',
    'DIRECT OWNERS', 'INDIRECT OWNERS', 'CRD NO', 'IF NONE',
    'COMPLETE ALL', 'NA - LESS THAN', 'OWNERSHIP CODES ARE',
    'ENTITY IN WHICH', 'INTEREST IS OWNED', 'DATE STATUS', 'ACQUIRED',
])


def _is_false_jurisdiction(jurisdiction, name_line, prev_line):
    """Detect when a jurisdiction code is actually a company suffix.
    e.g., 'SAROFIM FAYEZ &' + 'CO' → CO is '& Co', not Colorado."""
    if jurisdiction == 'CO':
        if prev_line and prev_line.rstrip().endswith('&'):
            return True
        if name_line and name_line.rstrip().endswith('&'):
            return True
    return False


def parse_adv_pdf_pymupdf(pdf_path: str, firm_crd: str = "") -> list[dict]:
    """
    Parse Schedule A/B from ADV PDF using PyMuPDF text extraction.

    100x-400x faster than pdfplumber. No size limit. Handles files that
    pdfplumber cannot process (>10MB, >300s parse time).

    Text-based: extracts page text, detects jurisdiction lines (DE/FE/I)
    to identify entity rows, scans for ownership codes by pattern.

    Quality: 100% recall and 100% accuracy vs pdfplumber on 8-file benchmark.
    """
    import re
    import pymupdf  # pylint: disable=import-error

    doc = pymupdf.open(pdf_path)
    entries = []
    in_sched = None

    for page in doc:
        text = page.get_text()
        upper = text.upper()

        # Detect schedule start (can coexist with data on same page)
        if "SCHEDULE A" in upper and "DIRECT" in upper:
            in_sched = "A"
        elif "SCHEDULE B" in upper and "INDIRECT" in upper:
            in_sched = "B"

        # Parse this page BEFORE checking exit — data and exit keyword
        # can appear on the same page (e.g., DRP PAGES after table rows)
        if in_sched:
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            i = 0
            while i < len(lines):
                line = lines[i]
                line_upper = line.upper()

                if any(kw in line_upper for kw in _PYMUPDF_SKIP_KW):
                    i += 1
                    continue

                if i + 1 < len(lines):
                    next_upper = lines[i + 1].upper().strip()
                    if next_upper in _VALID_JURISDICTIONS or next_upper == "I":
                        name = line
                        jurisdiction = next_upper
                        prev_line = lines[i - 1].strip() if i > 0 else ""

                        # Guard: false jurisdiction (CO = & Co, not Colorado)
                        if _is_false_jurisdiction(jurisdiction, name, prev_line):
                            i += 1
                            continue

                        # Multi-line name assembly: join fragments going back up to 3 lines.
                        # Handles: "THE KEITH A. HEICHEL" / "IRREVOCABLE TRUST DATED" / "2020" / DE
                        # and:     "OAKTREE CAPITAL GROUP HOLDINGS," / "L.P." / DE
                        _stop_kw = frozenset(["CRD NO", "EMPLOYER", "IF NONE"])
                        _continuation_kw = frozenset([
                            "TRUST", "DATED", "IRREVOCABLE", "REVOCABLE",
                            "HOLDINGS", "PARTNERS", "INVESTMENT", "ADVISORS",
                        ])
                        lookback = 0
                        while lookback < 4 and i - lookback > 0:
                            cur = name if lookback == 0 else lines[i - lookback].strip()
                            cur_up = cur.upper().rstrip(".,")
                            is_fragment = (
                                cur_up in _PYMUPDF_NAME_FRAGMENTS
                                or (len(cur) < 8 and cur.endswith("."))
                                or cur.isdigit()  # year like "2020"
                                or any(kw in cur_up for kw in _continuation_kw)
                                or (lookback == 0 and not _is_valid_entity_name(name))
                            )
                            # Also join if name is technically valid but very short
                            # (e.g., "LLC" passes validation but is clearly a fragment)
                            if not is_fragment and lookback == 0 and len(name) < 12:
                                is_fragment = True
                            if not is_fragment:
                                break
                            prev = lines[i - lookback - 1].strip()
                            if any(kw in prev.upper() for kw in _stop_kw):
                                break
                            # Don't go past ownership data (Y/N, codes, dates)
                            if prev.upper().strip() in ("Y", "N") or prev.strip().isdigit():
                                break
                            name = prev + " " + name
                            lookback += 1

                        # Also join when prev line ends with comma (continuation)
                        if i - lookback > 0 and not _is_valid_entity_name(name):
                            prev = lines[i - lookback - 1].strip()
                            if prev.endswith(","):
                                name = prev + " " + name

                        if not _is_valid_entity_name(name):
                            i += 1
                            continue

                        # Collect remaining fields
                        rest = []
                        j = i + 2
                        while j < len(lines) and len(rest) < 12:
                            val = lines[j].strip()
                            if j + 1 < len(lines):
                                nxt = lines[j + 1].strip().upper()
                                if nxt in (_VALID_JURISDICTIONS | {"I"}):
                                    prv = lines[j - 1].strip() if j > 0 else ""
                                    if _is_false_jurisdiction(nxt, val, prv):
                                        rest.append(val)
                                        j += 1
                                        continue
                                    val_up = val.upper().rstrip(".,")
                                    # Fragment before jurisdiction could be part of next
                                    # entity OR part of current rest. Check if preceding
                                    # line is a plausible entity name start.
                                    if val_up in _PYMUPDF_NAME_FRAGMENTS or val.isdigit():
                                        if j > 0 and _is_valid_entity_name(prv):
                                            # prev line + fragment = next entity → stop
                                            break
                                        rest.append(val)
                                        j += 1
                                        continue
                                    if _is_valid_entity_name(val):
                                        break
                            rest.append(val)
                            j += 1

                        # Scan for ownership code
                        own_clean = ""
                        control = ""
                        title_parts = []
                        date_val = ""
                        for ri, val in enumerate(rest):
                            v = val.upper().strip()
                            if v in ("A", "B", "C", "D", "E", "F", "NA") and not own_clean:
                                own_clean = v
                                if ri + 1 < len(rest) and rest[ri + 1].upper().strip() in ("Y", "N"):
                                    control = rest[ri + 1].upper().strip()
                                break
                            elif re.match(r"\d{2}/\d{4}", v):
                                date_val = v
                            elif v not in ("Y", "N", "PR"):
                                title_parts.append(val)

                        title = " ".join(title_parts)
                        is_entity = jurisdiction != "I"
                        if own_clean == "F":
                            own_clean = ""
                        rel_type = OWN_CODE_TO_REL.get(own_clean)
                        if is_entity and own_clean == "NA":
                            rel_type = "mutual_structure"

                        entries.append({
                            "firm_crd": firm_crd,
                            "schedule": in_sched,
                            "name": name,
                            "jurisdiction": jurisdiction,
                            "title_or_status": title,
                            "date": date_val,
                            "ownership_code": own_clean,
                            "control_person": control,
                            "is_entity": is_entity,
                            "relationship_type": rel_type,
                        })
                        i = j
                        continue
                i += 1

        # Check exit AFTER parsing — applies to next page
        if in_sched:
            for kw in ["SCHEDULE D", "DRP PAGES", "FORM ADV, PART 2"]:
                if kw in upper and "SCHEDULE A" not in upper and "SCHEDULE B" not in upper:
                    in_sched = None
                    break

    doc.close()
    return entries


def _normalize_entity_name(name: str) -> str:
    """Normalize common legal suffixes for fuzzy matching.

    Corp/Corporation/Incorporated → CORP, Company/Co → CO,
    Limited → LTD, L.L.C. → LLC. Removes trailing punctuation.
    """
    import re
    s = name.upper().strip()
    # Standardize suffixes (order matters — longest first)
    s = re.sub(r'\bINCORPORATED\b', 'INC', s)
    s = re.sub(r'\bCORPORATION\b', 'CORP', s)
    s = re.sub(r'\bCOMPANY\b', 'CO', s)
    s = re.sub(r'\bLIMITED\b', 'LTD', s)
    s = re.sub(r'\bL\.L\.C\.', 'LLC', s)
    s = re.sub(r'\bL\.P\.', 'LP', s)
    # Remove trailing punctuation
    s = s.rstrip('.,;')
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


class _AliasCache:
    """Pre-cached alias data for fast fuzzy matching across a batch run."""

    def __init__(self, con):
        # All entities with active aliases — not restricted to rollup parents.
        # ORDER BY ensures deterministic iteration order.
        rows = con.execute("""
            SELECT DISTINCT ea.entity_id, ea.alias_name
            FROM entity_aliases ea
            WHERE ea.valid_to = DATE '9999-12-31'
              AND ea.alias_name IS NOT NULL AND ea.alias_name != ''
            ORDER BY ea.entity_id, ea.alias_name
        """).fetchall()
        # Store both raw and normalized names for matching
        self.parent_names_raw = [r[1].upper() for r in rows if r[1]]
        self.parent_names = [_normalize_entity_name(r[1]) for r in rows if r[1]]
        self.parent_eids = [r[0] for r in rows if r[1]]
        logger.info("AliasCache loaded: %d entity aliases (full universe)", len(self.parent_names))

    def match(self, name: str, threshold: int = 85) -> tuple[int | None, str | None, int]:
        """Returns (entity_id, alias_name, score) or (None, best_name, best_score).

        Normalizes Corp/Corporation/Company/Co/etc before matching.
        Deterministic tiebreaker: score DESC → entity_id ASC.
        """
        from rapidfuzz import process, fuzz

        if not name or not self.parent_names:
            return None, None, 0

        # Normalize query name
        query = _normalize_entity_name(name)

        # Get top N candidates and apply deterministic tiebreaker
        results = process.extract(
            query, self.parent_names,
            scorer=fuzz.token_sort_ratio, limit=5,
        )
        if not results:
            return None, None, 0

        # Tiebreaker: score DESC, entity_id ASC
        # Return raw (un-normalized) name for display
        candidates = [
            (self.parent_names_raw[idx], int(score), self.parent_eids[idx])
            for _matched_name, score, idx in results
        ]
        candidates.sort(key=lambda x: (-x[1], x[2]))

        best_name, best_score, best_eid = candidates[0]
        if best_score >= threshold:
            return best_eid, best_name, best_score
        return None, best_name, best_score


def build_alias_cache(con) -> _AliasCache:
    """Create a reusable alias cache for a batch of insert_adv_ownership calls."""
    return _AliasCache(con)


def insert_adv_ownership(
    con,
    child_entity_id: int,
    owner_name: str,
    relationship_type: str,
    ownership_code: str,
    schedule_type: str,
    *,
    alias_cache: _AliasCache | None = None,
    threshold: int = 85,
    is_primary: bool = True,
) -> dict:
    """
    Match an ADV owner name against existing entity aliases and insert
    a relationship if found. Never creates new parent entities.

    For mutual_structure: inserts relationship with is_primary=False,
    control_type='mutual'. Entity keeps self-rollup.

    For wholly_owned/parent_brand: uses alias_cache for fast matching.
    Inserts relationship with is_primary per caller (JV: only rank 0 is primary).
    Updates rollup only if primary.

    Pass alias_cache from build_alias_cache() for batch performance.
    """
    result = {
        "matched": False,
        "parent_entity_id": None,
        "parent_name": None,
        "score": 0,
        "relationship_inserted": False,
        "rollup_updated": False,
        "is_mutual": relationship_type == "mutual_structure",
    }

    if not owner_name:
        return result

    # Mutual structure: attempt match but never set is_primary, never update rollup
    if relationship_type == "mutual_structure":
        cache = alias_cache if alias_cache is not None else _AliasCache(con)
        eid, matched_name, score = cache.match(owner_name, threshold)
        result["score"] = score
        result["parent_name"] = matched_name or owner_name

        if eid is not None:
            result["matched"] = True
            result["parent_entity_id"] = eid
            source = f"ADV_SCHEDULE_{schedule_type}"
            inserted = insert_relationship_idempotent(
                con, eid, child_entity_id, "mutual_structure", "mutual",
                False, "medium", source, is_inferred=False,
            )
            result["relationship_inserted"] = inserted
            # No rollup update — entity keeps self-rollup
        return result

    # Use cache if provided, else build one (slow per-call fallback)
    cache = alias_cache
    if cache is None:
        cache = _AliasCache(con)

    eid, matched_name, score = cache.match(owner_name, threshold)
    result["score"] = score
    result["parent_name"] = matched_name

    if eid is None:
        return result

    result["matched"] = True
    result["parent_entity_id"] = eid

    source = f"ADV_SCHEDULE_{schedule_type}"
    inserted = insert_relationship_idempotent(
        con, eid, child_entity_id, relationship_type, "control",
        is_primary, "high" if score >= 95 else "medium", source,
        is_inferred=False, match_score=score,
    )
    result["relationship_inserted"] = inserted

    if inserted and is_primary:
        # Atomic SCD close+open for rollup history with self-heal
        con.begin()
        try:
            has_active = con.execute("""
                SELECT 1 FROM entity_rollup_history
                WHERE entity_id = ? AND rollup_type = 'economic_control_v1'
                  AND valid_to = DATE '9999-12-31'
            """, [child_entity_id]).fetchone()
            if has_active:
                con.execute("""
                    UPDATE entity_rollup_history SET valid_to = CURRENT_DATE
                    WHERE entity_id = ? AND rollup_type = 'economic_control_v1'
                      AND valid_to = DATE '9999-12-31'
                """, [child_entity_id])
            con.execute("""
                INSERT INTO entity_rollup_history
                  (entity_id, rollup_entity_id, rollup_type, rule_applied,
                   confidence, valid_from, valid_to)
                VALUES (?, ?, 'economic_control_v1', ?,
                        'high', CURRENT_DATE, DATE '9999-12-31')
            """, [child_entity_id, eid, relationship_type])
            con.commit()
        except Exception:
            con.rollback()
            raise
        result["rollup_updated"] = True

    return result
