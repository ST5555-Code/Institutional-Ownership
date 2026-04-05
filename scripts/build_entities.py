#!/usr/bin/env python3
"""
Entity MDM Phase 1 — build_entities.py

Builds the entity MDM tables in the STAGING database from existing sources:
  - PARENT_SEEDS (build_managers.py)    → seed parent entities (~110)
  - managers                            → filer entities + CIK identifiers
  - adv_managers                        → additional adviser entities + CRD identifiers
  - fund_universe                       → fund entities + series_id identifiers
  - ncen_adviser_map                    → adviser→fund relationships
  - parent_bridge                       → parent→manager relationships (fuzzy matched)
  - cik_crd_links / cik_crd_direct      → CIK→CRD mapping

See ENTITY_ARCHITECTURE.md and PHASE1_PROMPT.md for full design context.

Sentinel date 9999-12-31 = "currently active" (see Apr 5 2026 decision log entry).
All Phase 1 seed data has is_inferred=TRUE and valid_from='2000-01-01'.

Usage:
  python scripts/build_entities.py            # build in staging (default)
  python scripts/build_entities.py --reset    # truncate entity tables before build

Staging only. Never touches production.
"""
from __future__ import annotations

# pylint: disable=too-many-locals,too-many-statements,too-many-branches,too-many-arguments,too-many-positional-arguments,broad-exception-caught

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# ---- path setup
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

# ---- logging
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
BUILD_LOG = LOG_DIR / "entity_build.log"
CONFLICT_LOG = LOG_DIR / "entity_build_conflicts.log"

logger = logging.getLogger("entity_build")
logger.setLevel(logging.INFO)
# File handler
_fh = logging.FileHandler(BUILD_LOG, mode="a")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_fh)
# Console
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_ch)

conflict_logger = logging.getLogger("entity_build_conflicts")
conflict_logger.setLevel(logging.INFO)
_cfh = logging.FileHandler(CONFLICT_LOG, mode="a")
_cfh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
conflict_logger.addHandler(_cfh)


ACTIVE = "9999-12-31"  # sentinel for "currently active"
VALID_FROM = "2000-01-01"


# =============================================================================
# Helpers
# =============================================================================
def _normalize(name: str) -> str:
    """Lowercase + collapse whitespace for 'normalized' alias type."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def load_parent_seeds():
    """Import PARENT_SEEDS constant without running build_managers.py."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_managers", ROOT / "scripts" / "build_managers.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PARENT_SEEDS  # list of (canonical_name, strategy_type, [variants])


def next_entity_id(con) -> int:
    return con.execute("SELECT nextval('entity_id_seq')").fetchone()[0]


def next_relationship_id(con) -> int:
    return con.execute("SELECT nextval('relationship_id_seq')").fetchone()[0]


def reset_entity_tables(con):
    """Truncate all entity tables and reset sequences for a clean rebuild."""
    logger.info("[reset] truncating entity tables and resetting sequences")
    # Delete in FK-safe order
    for t in [
        "entity_rollup_history",
        "entity_classification_history",
        "entity_aliases",
        "entity_relationships",
        "entity_identifiers",
        "entities",
    ]:
        con.execute(f"DELETE FROM {t}")  # nosec B608 — t is from a hard-coded list above
    con.execute("DROP SEQUENCE IF EXISTS entity_id_seq")
    con.execute("DROP SEQUENCE IF EXISTS relationship_id_seq")
    con.execute("CREATE SEQUENCE entity_id_seq START 1")
    con.execute("CREATE SEQUENCE relationship_id_seq START 1")


# =============================================================================
# Step 2 — Seed top parent entities from PARENT_SEEDS
# =============================================================================
def step2_seed_parents(con, seeds):
    """Create an entity per PARENT_SEEDS entry. Returns {canonical_name: entity_id}."""
    logger.info("[step 2] seeding %d PARENT_SEEDS entities", len(seeds))
    seed_map: dict[str, int] = {}
    con.execute("BEGIN TRANSACTION")
    try:
        for canonical, _strategy, _variants in seeds:
            eid = next_entity_id(con)
            con.execute(
                """INSERT INTO entities
                   (entity_id, entity_type, canonical_name, created_source, is_inferred)
                   VALUES (?, 'institution', ?, 'PARENT_SEEDS', TRUE)""",
                [eid, canonical],
            )
            seed_map[canonical] = eid
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    logger.info("[step 2] created %d parent entities (ids %d..%d)",
                len(seed_map), min(seed_map.values()), max(seed_map.values()))
    return seed_map


# =============================================================================
# Step 2.5 — Create manager entities (one per managers row not already a seed)
# =============================================================================
def step2_create_manager_entities(con, seed_map):
    """
    Create entities for each DISTINCT CIK in managers (not per row).

    managers contains duplicate CIK rows (a single CIK can have multiple rows
    from different manager_name variants — e.g., name change history). All such
    rows refer to the same SEC filer, so the entity MDM model creates ONE entity
    per CIK and treats the other manager_names as aliases (added in Step 5).

    Dedupe strategy per CIK:
      - Keep the row with highest aum_total as the "canonical" manager row
        (ties broken by first occurrence).
      - Use that row's manager_name as entities.canonical_name.
      - parent_name/strategy_type/is_activist/crd taken from the same canonical row.

    Absorb rule: if managers.parent_name matches a seed canonical AND the
    canonical manager_name ~= parent_name (the filer IS the seed), attach the
    CIK to the seed entity instead of creating a new entity.

    Returns:
      cik_to_entity: {cik: entity_id}
      manager_entity_rows: one per DISTINCT CIK: (entity_id, cik, manager_name,
                           parent_name, strategy_type, is_activist, crd,
                           all_manager_names: list)
    """
    rows = con.execute(
        """SELECT cik, manager_name, parent_name, strategy_type, is_activist, crd_number, aum_total
           FROM managers
           WHERE cik IS NOT NULL"""
    ).fetchall()
    logger.info("[step 2.5] processing %d managers rows", len(rows))

    # Group by CIK, pick canonical row (highest AUM)
    by_cik: dict[str, dict] = {}
    for cik, mname, pname, strat, activist, crd, aum in rows:
        if cik not in by_cik:
            by_cik[cik] = {
                "canonical": (mname, pname, strat, activist, crd, aum or 0),
                "all_names": {mname} if mname else set(),
            }
        else:
            rec = by_cik[cik]
            if mname:
                rec["all_names"].add(mname)
            # Promote to canonical if higher AUM
            if (aum or 0) > rec["canonical"][5]:
                rec["canonical"] = (mname, pname, strat, activist, crd, aum or 0)

    logger.info("[step 2.5] distinct CIKs: %d (row dedupe collapsed %d rows)",
                len(by_cik), len(rows) - len(by_cik))

    cik_to_entity: dict[str, int] = {}
    manager_entity_rows = []
    seed_absorbed = 0

    con.execute("BEGIN TRANSACTION")
    try:
        for cik, rec in by_cik.items():
            mname, pname, strat, activist, crd, _aum = rec["canonical"]
            all_names = rec["all_names"]
            absorb = False
            if pname in seed_map and _normalize(mname or "") == _normalize(pname or ""):
                absorb = True
            if absorb:
                eid = seed_map[pname]
                seed_absorbed += 1
            else:
                eid = next_entity_id(con)
                con.execute(
                    """INSERT INTO entities
                       (entity_id, entity_type, canonical_name, created_source, is_inferred)
                       VALUES (?, 'institution', ?, 'managers', TRUE)""",
                    [eid, mname or f"CIK {cik}"],
                )
            cik_to_entity[cik] = eid
            manager_entity_rows.append(
                (eid, cik, mname, pname, strat, activist, crd, sorted(all_names))
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    logger.info(
        "[step 2.5] %d manager entities (%d absorbed into seeds)",
        len(cik_to_entity), seed_absorbed,
    )
    return cik_to_entity, manager_entity_rows


# =============================================================================
# Step 2.6 — Create fund entities (one per fund_universe.series_id)
# =============================================================================
def step2_create_fund_entities(con):
    rows = con.execute(
        """SELECT series_id, fund_name, family_name, is_actively_managed
           FROM fund_universe
           WHERE series_id IS NOT NULL"""
    ).fetchall()
    logger.info("[step 2.6] creating %d fund entities", len(rows))
    series_to_entity: dict[str, int] = {}
    fund_entity_rows = []
    con.execute("BEGIN TRANSACTION")
    try:
        for series_id, fname, _family, active in rows:
            eid = next_entity_id(con)
            con.execute(
                """INSERT INTO entities
                   (entity_id, entity_type, canonical_name, created_source, is_inferred)
                   VALUES (?, 'fund', ?, 'fund_universe', TRUE)""",
                [eid, fname or series_id],
            )
            series_to_entity[series_id] = eid
            fund_entity_rows.append((eid, series_id, fname, _family, active))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    logger.info("[step 2.6] done: %d fund entities", len(series_to_entity))
    return series_to_entity, fund_entity_rows


# =============================================================================
# Step 3 — Populate entity_identifiers (CIK, CRD, series_id)
# =============================================================================
def step3_populate_identifiers(con, cik_to_entity, series_to_entity, manager_rows):
    """
    Load identifiers:
      - 'cik'       from managers  → manager entities
      - 'crd'       from managers.crd_number (if non-null)
      - 'crd'       from cik_crd_links / cik_crd_direct (mapping CIK→CRD)
      - 'series_id' from fund_universe
    Hard-fails on duplicate active mapping via ux_identifier_active. Conflicts logged.
    """
    logger.info("[step 3] populating entity_identifiers")
    added = {"cik": 0, "crd": 0, "series_id": 0}
    conflicts = 0

    # Track (type, value) pairs already seen so we can log conflicts (ON CONFLICT
    # DO NOTHING silently skips duplicates — we log separately for diagnostics).
    seen_id_keys: dict[tuple[str, str], int] = {}

    def _try_insert(entity_id, id_type, id_value, confidence, source):
        nonlocal conflicts
        if not id_value:
            return False
        key = (id_type, str(id_value))
        prior_entity = seen_id_keys.get(key)
        if prior_entity is not None and prior_entity != entity_id:
            conflicts += 1
            conflict_logger.info(
                "identifier_conflict type=%s value=%s prior_entity=%s new_entity=%s source=%s",
                id_type, id_value, prior_entity, entity_id, source,
            )
            return False
        seen_id_keys[key] = entity_id
        if prior_entity == entity_id:
            return False  # same entity, same identifier — idempotent skip
        con.execute(
            """INSERT INTO entity_identifiers
               (entity_id, identifier_type, identifier_value, confidence, source, is_inferred)
               VALUES (?, ?, ?, ?, ?, TRUE)
               ON CONFLICT DO NOTHING""",
            [entity_id, id_type, str(id_value), confidence, source],
        )
        added[id_type] = added.get(id_type, 0) + 1
        return True

    con.execute("BEGIN TRANSACTION")
    try:
        # CIKs from managers (one per distinct CIK — already deduped in step 2.5)
        for (entity_id, cik, _mn, _pn, _st, _ia, crd, _all) in manager_rows:
            _try_insert(entity_id, "cik", cik, "exact", "managers")
            if crd:
                _try_insert(entity_id, "crd", crd, "exact", "managers")
        # Additional CRDs from cik_crd_links (fuzzy_match)
        for cik, crd, _score in con.execute(
            "SELECT cik, crd_number, match_score FROM cik_crd_links"
        ).fetchall():
            eid = cik_to_entity.get(cik)
            if eid and crd:
                _try_insert(eid, "crd", crd, "fuzzy_match", "cik_crd_links")
        # Additional CRDs from cik_crd_direct (exact)
        for cik, crd in con.execute(
            "SELECT cik, crd_number FROM cik_crd_direct"
        ).fetchall():
            eid = cik_to_entity.get(cik)
            if eid and crd:
                _try_insert(eid, "crd", crd, "exact", "cik_crd_direct")
        # series_ids from fund_universe (already seeded)
        for series_id, eid in series_to_entity.items():
            _try_insert(eid, "series_id", series_id, "exact", "fund_universe")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    logger.info("[step 3] identifiers added: %s (conflicts logged: %d)", added, conflicts)
    return added, conflicts


# =============================================================================
# Step 4 — Populate entity_relationships
# =============================================================================
def insert_relationship(
    con, parent_id, child_id, rel_type, control_type, is_primary,
    confidence, source, has_primary_parent: set[int] | None = None,
):
    """
    Atomic insert of a relationship. Returns True if inserted, False if skipped.

    If is_primary=TRUE, checks has_primary_parent set first — if the child already
    has a primary parent, demotes this insert by logging a conflict and skipping.
    Caller is responsible for updating has_primary_parent on successful primary insert.
    """
    if is_primary and has_primary_parent is not None and child_id in has_primary_parent:
        conflict_logger.info(
            "primary_parent_conflict child=%s existing_primary=skipped new_parent=%s source=%s",
            child_id, parent_id, source,
        )
        return False
    rid = next_relationship_id(con)
    primary_key = child_id if is_primary else None
    # ON CONFLICT DO NOTHING guards against duplicate (parent,child,type,valid_to)
    # and duplicate primary_parent_key entries that slip past the Python check.
    result = con.execute(
        """INSERT INTO entity_relationships
           (relationship_id, parent_entity_id, child_entity_id, relationship_type,
            control_type, is_primary, primary_parent_key, confidence, source,
            is_inferred, valid_from, valid_to)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, DATE '2000-01-01', DATE '9999-12-31')
           ON CONFLICT DO NOTHING
           RETURNING relationship_id""",
        [rid, parent_id, child_id, rel_type, control_type, is_primary, primary_key,
         confidence, source],
    ).fetchall()
    inserted = len(result) > 0
    if inserted and is_primary and has_primary_parent is not None:
        has_primary_parent.add(child_id)
    return inserted


def step4_populate_relationships(
    con, seed_map, series_to_entity, manager_rows,
):
    """
    Populate entity_relationships from two sources:
      A) parent_bridge / managers  → seed→manager fund_sponsor (primary) where matched
      B) ncen_adviser_map          → adviser→fund fund_sponsor (primary) / sub_adviser (non-primary)

    Source A runs first so manager entities have their primary parents from the
    fuzzy-matched PARENT_SEEDS mapping. Source B (ncen) is exact; if ncen tries
    to set a second primary parent on a child that already has one, the conflict
    is logged and the second insert is skipped (ux_primary_parent blocks it).
    """
    logger.info("[step 4] populating entity_relationships")
    inserted = {"seed_fund_sponsor": 0, "ncen_fund_sponsor": 0, "ncen_sub_adviser": 0}
    skipped = {"self_parent": 0, "seed_not_found": 0, "adviser_not_found": 0, "fund_not_found": 0}
    has_primary_parent: set[int] = set()

    # --- Source A: parent_bridge via managers
    con.execute("BEGIN TRANSACTION")
    try:
        for (entity_id, _cik, mname, pname, _st, _ia, _crd, _all) in manager_rows:
            if not pname or _normalize(pname) == _normalize(mname or ""):
                skipped["self_parent"] += 1
                continue
            parent_eid = seed_map.get(pname)
            if parent_eid is None:
                skipped["seed_not_found"] += 1
                continue
            if parent_eid == entity_id:
                # absorbed case: entity IS the seed, no self-relationship needed
                skipped["self_parent"] += 1
                continue
            if insert_relationship(
                con, parent_eid, entity_id, "fund_sponsor", "control",
                True, "fuzzy_match", "parent_bridge", has_primary_parent,
            ):
                inserted["seed_fund_sponsor"] += 1
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    # --- Source B: ncen_adviser_map
    # Build CRD→entity_id lookup (advisers) from already-populated identifiers
    crd_to_entity = dict(con.execute(
        """SELECT identifier_value, entity_id FROM entity_identifiers
           WHERE identifier_type='crd' AND valid_to = DATE '9999-12-31'"""
    ).fetchall())

    # Any ncen advisers without a CRD match need a new entity created
    # (adv_managers has ~16k CRDs; managers/adv_managers overlap heavily but some
    #  ncen advisers are not in either).
    ncen_rows = con.execute(
        """SELECT adviser_name, adviser_crd, series_id, role
           FROM ncen_adviser_map
           WHERE series_id IS NOT NULL AND adviser_crd IS NOT NULL"""
    ).fetchall()
    logger.info("[step 4] ncen rows with series_id and crd: %d", len(ncen_rows))

    # Pre-create missing adviser entities in one transaction
    missing_crds: dict[str, str] = {}
    for adv_name, crd, _sid, _role in ncen_rows:
        if crd and crd not in crd_to_entity and crd not in missing_crds:
            missing_crds[crd] = adv_name or f"CRD {crd}"
    if missing_crds:
        logger.info("[step 4] creating %d new adviser entities for ncen-only CRDs", len(missing_crds))
        con.execute("BEGIN TRANSACTION")
        try:
            for crd, name in missing_crds.items():
                eid = next_entity_id(con)
                con.execute(
                    """INSERT INTO entities
                       (entity_id, entity_type, canonical_name, created_source, is_inferred)
                       VALUES (?, 'institution', ?, 'ncen_adviser_map', TRUE)""",
                    [eid, name],
                )
                con.execute(
                    """INSERT INTO entity_identifiers
                       (entity_id, identifier_type, identifier_value, confidence, source, is_inferred)
                       VALUES (?, 'crd', ?, 'exact', 'ncen_adviser_map', TRUE)""",
                    [eid, crd],
                )
                crd_to_entity[crd] = eid
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    # Insert ncen relationships
    con.execute("BEGIN TRANSACTION")
    try:
        for adv_name, crd, series_id, role in ncen_rows:
            adv_eid = crd_to_entity.get(crd)
            fund_eid = series_to_entity.get(series_id)
            if adv_eid is None:
                skipped["adviser_not_found"] += 1
                continue
            if fund_eid is None:
                skipped["fund_not_found"] += 1
                continue
            if role == "adviser":
                ok = insert_relationship(
                    con, adv_eid, fund_eid, "fund_sponsor", "control",
                    True, "exact", "ncen_adviser_map", has_primary_parent,
                )
                if ok:
                    inserted["ncen_fund_sponsor"] += 1
            elif role == "subadviser":
                ok = insert_relationship(
                    con, adv_eid, fund_eid, "sub_adviser", "advisory",
                    False, "exact", "ncen_adviser_map", has_primary_parent,
                )
                if ok:
                    inserted["ncen_sub_adviser"] += 1
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    logger.info("[step 4] relationships inserted: %s", inserted)
    logger.info("[step 4] relationships skipped: %s", skipped)
    return inserted, skipped


# =============================================================================
# Step 5 — Populate entity_aliases
# =============================================================================
def step5_populate_aliases(con, seed_map, seeds, manager_rows, fund_rows):
    """
    Every entity MUST have exactly one preferred alias (structural gate 1).
    Alias types:
      - 'brand'      — display name (is_preferred=TRUE for one per entity)
      - 'legal'      — legal name (not used in Phase 1)
      - 'filing'     — name as appears in filings
      - 'normalized' — lowercase whitespace-collapsed version
    """
    logger.info("[step 5] populating entity_aliases")

    # Track which entities already have a preferred alias (structural invariant)
    preferred_set: set[int] = set()
    added = {"brand": 0, "filing": 0, "normalized": 0}

    # Track (entity_id, alias_name) to dedupe across sources
    seen_aliases: set[tuple[int, str]] = set()

    def _insert_alias(entity_id, alias_name, alias_type, is_preferred, source_table):
        if not alias_name:
            return False
        key = (entity_id, alias_name)
        if key in seen_aliases:
            return False
        # Enforce "one preferred per entity" in Python BEFORE insert; downgrade if needed.
        if is_preferred and entity_id in preferred_set:
            is_preferred = False
        preferred_key = entity_id if is_preferred else None
        res = con.execute(
            """INSERT INTO entity_aliases
               (entity_id, alias_name, alias_type, is_preferred, preferred_key,
                source_table, is_inferred, valid_from, valid_to)
               VALUES (?, ?, ?, ?, ?, ?, TRUE, DATE '2000-01-01', DATE '9999-12-31')
               ON CONFLICT DO NOTHING
               RETURNING entity_id""",
            [entity_id, alias_name, alias_type, is_preferred, preferred_key, source_table],
        ).fetchall()
        if res:
            seen_aliases.add(key)
            added[alias_type] = added.get(alias_type, 0) + 1
            if is_preferred:
                preferred_set.add(entity_id)
            return True
        return False

    con.execute("BEGIN TRANSACTION")
    try:
        # --- PARENT_SEEDS: brand (preferred) + filing variants + normalized
        for canonical, _strat, variants in seeds:
            eid = seed_map[canonical]
            _insert_alias(eid, canonical, "brand", True, "PARENT_SEEDS")
            for v in variants:
                _insert_alias(eid, v, "filing", False, "PARENT_SEEDS")
            norm = _normalize(canonical)
            if norm and norm != canonical.lower():
                _insert_alias(eid, norm, "normalized", False, "PARENT_SEEDS")

        # --- Manager entities (one per distinct CIK)
        # First name (canonical) becomes preferred brand alias; all other name
        # variants (from duplicate CIK rows in managers) are added as filing aliases.
        # _insert_alias auto-downgrades is_preferred=TRUE to FALSE if the entity
        # already has a preferred alias (e.g., absorbed-into-seed case).
        for (entity_id, _cik, mname, _pn, _st, _ia, _crd, all_names) in manager_rows:
            if not mname:
                continue
            _insert_alias(entity_id, mname, "brand", True, "managers")
            norm = _normalize(mname)
            if norm and norm != mname.lower():
                _insert_alias(entity_id, norm, "normalized", False, "managers")
            # Additional name variants from duplicate CIK rows → filing aliases
            for alt in all_names:
                if alt and alt != mname:
                    _insert_alias(entity_id, alt, "filing", False, "managers")

        # --- Fund entities
        for (entity_id, series_id, fname, _family, _active) in fund_rows:
            if not fname:
                _insert_alias(entity_id, series_id, "brand", True, "fund_universe")
                continue
            _insert_alias(entity_id, fname, "brand", True, "fund_universe")
            norm = _normalize(fname)
            if norm and norm != fname.lower():
                _insert_alias(entity_id, norm, "normalized", False, "fund_universe")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    # --- Entities with NO preferred alias (adviser-only entities from ncen): give them a fallback
    logger.info("[step 5] backfilling preferred aliases for entities created via ncen_adviser_map")
    con.execute("BEGIN TRANSACTION")
    try:
        no_pref = con.execute(
            """SELECT e.entity_id, e.canonical_name
               FROM entities e
               LEFT JOIN entity_aliases ea
                 ON e.entity_id = ea.entity_id
                 AND ea.is_preferred = TRUE
                 AND ea.valid_to = DATE '9999-12-31'
               WHERE ea.entity_id IS NULL"""
        ).fetchall()
        for eid, cname in no_pref:
            _insert_alias(eid, cname, "brand", True, "canonical_name_fallback")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    logger.info("[step 5] aliases added: %s", added)
    return added


# =============================================================================
# Step 6 — Populate entity_classification_history
# =============================================================================
def step6_populate_classifications(con, seeds, seed_map, manager_rows, fund_rows):
    """
    Classification sources:
      - PARENT_SEEDS.strategy_type for seed entities
      - managers.strategy_type / is_activist for manager entities (non-absorbed)
      - fund_universe.is_actively_managed → 'active'|'passive'|'unknown'
      - canonical_name_fallback adviser entities → 'unknown'
    Exactly one active row per entity.
    """
    logger.info("[step 6] populating entity_classification_history")
    # Seeds win: their classification comes from PARENT_SEEDS
    classified: set[int] = set()
    added = 0

    def _insert_cls(entity_id, classification, is_activist, confidence, source):
        nonlocal added
        if entity_id in classified:
            return False
        try:
            con.execute(
                """INSERT INTO entity_classification_history
                   (entity_id, classification, is_activist, confidence, source,
                    is_inferred, valid_from, valid_to)
                   VALUES (?, ?, ?, ?, ?, TRUE, DATE '2000-01-01', DATE '9999-12-31')""",
                [entity_id, classification, bool(is_activist), confidence, source],
            )
            classified.add(entity_id)
            added += 1
            return True
        except Exception as e:
            conflict_logger.info(
                "classification_conflict entity=%s err=%s", entity_id, str(e)[:120]
            )
            return False

    con.execute("BEGIN TRANSACTION")
    try:
        # PARENT_SEEDS classifications
        for canonical, strat, _variants in seeds:
            eid = seed_map[canonical]
            activist = strat == "activist"
            _insert_cls(eid, strat or "unknown", activist, "exact", "PARENT_SEEDS")

        # Manager entity classifications (skip absorbed ones — seed wins)
        for (entity_id, _cik, _mn, _pn, strat, activist, _crd, _all) in manager_rows:
            if entity_id in classified:
                continue
            _insert_cls(entity_id, strat or "unknown", activist, "fuzzy_match", "managers")

        # Fund classifications
        for (entity_id, _sid, _fn, _family, active) in fund_rows:
            if entity_id in classified:
                continue
            if active is True:
                cls = "active"
            elif active is False:
                cls = "passive"
            else:
                cls = "unknown"
            _insert_cls(entity_id, cls, False, "exact", "fund_universe")

        # Anything else (ncen-only advisers) → unknown
        remaining = con.execute(
            """SELECT e.entity_id
               FROM entities e
               LEFT JOIN entity_classification_history ech
                 ON e.entity_id = ech.entity_id
                 AND ech.valid_to = DATE '9999-12-31'
               WHERE ech.entity_id IS NULL"""
        ).fetchall()
        for (eid,) in remaining:
            _insert_cls(eid, "unknown", False, "low", "default_unknown")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    logger.info("[step 6] classifications added: %d (total entities classified)", added)
    return added


# =============================================================================
# Step 7 — Compute entity_rollup_history (economic_control_v1)
# =============================================================================
def step7_compute_rollups(con):
    """
    For each entity:
      - If there is an active is_primary=TRUE relationship where
        relationship_type IN ('wholly_owned','fund_sponsor','parent_brand'),
        rollup_entity_id = parent_entity_id, rule_applied = relationship_type
      - Else rollup_entity_id = self, rule_applied = 'self'

    Sub-adviser relationships never drive rollup.
    This is the ONLY source aggregation queries may join for rollup information.
    """
    logger.info("[step 7] computing entity_rollup_history (economic_control_v1)")
    con.execute("BEGIN TRANSACTION")
    try:
        # Insert primary-parent rollups
        con.execute("""
            INSERT INTO entity_rollup_history
              (entity_id, rollup_entity_id, rollup_type, rule_applied, confidence,
               valid_from, valid_to)
            SELECT
                er.child_entity_id,
                er.parent_entity_id,
                'economic_control_v1',
                er.relationship_type,
                er.confidence,
                DATE '2000-01-01',
                DATE '9999-12-31'
            FROM entity_relationships er
            WHERE er.is_primary = TRUE
              AND er.valid_to = DATE '9999-12-31'
              AND er.relationship_type IN ('wholly_owned','fund_sponsor','parent_brand')
        """)
        # Insert self-rollups for any entity not yet rolled up
        con.execute("""
            INSERT INTO entity_rollup_history
              (entity_id, rollup_entity_id, rollup_type, rule_applied, confidence,
               valid_from, valid_to)
            SELECT
                e.entity_id,
                e.entity_id,
                'economic_control_v1',
                'self',
                'exact',
                DATE '2000-01-01',
                DATE '9999-12-31'
            FROM entities e
            LEFT JOIN entity_rollup_history erh
              ON e.entity_id = erh.entity_id
              AND erh.rollup_type = 'economic_control_v1'
              AND erh.valid_to = DATE '9999-12-31'
            WHERE erh.entity_id IS NULL
        """)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    stats = con.execute("""
        SELECT rule_applied, COUNT(*) FROM entity_rollup_history
         WHERE rollup_type = 'economic_control_v1' AND valid_to = DATE '9999-12-31'
         GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    logger.info("[step 7] rollups by rule_applied: %s", stats)
    return stats


# =============================================================================
# Main
# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="Truncate entity tables before build")
    args = ap.parse_args()

    db.set_staging_mode(True)
    db_path = db.get_db_path()
    logger.info("=" * 72)
    logger.info("Entity MDM Phase 1 build — %s", datetime.now().isoformat())
    logger.info("Staging DB: %s", db_path)
    logger.info("=" * 72)

    seeds = load_parent_seeds()
    con = db.connect_write()
    try:
        if args.reset:
            reset_entity_tables(con)

        seed_map = step2_seed_parents(con, seeds)
        cik_to_entity, manager_rows = step2_create_manager_entities(con, seed_map)
        series_to_entity, fund_rows = step2_create_fund_entities(con)

        step3_populate_identifiers(con, cik_to_entity, series_to_entity, manager_rows)
        step4_populate_relationships(con, seed_map, series_to_entity, manager_rows)
        step5_populate_aliases(con, seed_map, seeds, manager_rows, fund_rows)
        step6_populate_classifications(con, seeds, seed_map, manager_rows, fund_rows)
        step7_compute_rollups(con)

        # Summary counts
        logger.info("-" * 72)
        for t in [
            "entities",
            "entity_identifiers",
            "entity_relationships",
            "entity_aliases",
            "entity_classification_history",
            "entity_rollup_history",
        ]:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # nosec B608 — t from hard-coded list
            logger.info("  %-32s %d", t, n)
        logger.info("-" * 72)
        logger.info("Build complete. Run validate_entities.py before merging.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
