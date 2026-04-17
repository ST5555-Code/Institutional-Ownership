#!/usr/bin/env python3
"""resolve_pending_series.py — wire pending N-PORT series to entity MDM.

Three-tier resolver for `pending_entity_resolution` rows with
identifier_type='series_id':

  T1 (N-CEN)    — fund_cik → ncen_adviser_map.registrant_cik → adviser_crd
                  → entity_identifiers. Authoritative (source='N-CEN').
  T2 (family)   — family_name fuzzy match (≥90, DM13 pre-insert verified)
                  against entity_aliases. One-to-one family_name →
                  adviser_entity resolution; skipped if multiple advisers
                  match at the same score.
  T3 (fund)     — fund_name fuzzy match (≥90, DM13 pre-insert verified)
                  when family_name didn't carry the brand (e.g., MFS Series
                  Trust III housing MFS-branded funds under a generic trust).

Writes only to the STAGING DB. Follows the standard entity workflow:
sync → work → validate → diff → review → approve → promote.

Each resolved series gets a fresh fund entity with:
  - entity (entity_type='fund')
  - entity_identifiers (series_id)
  - entity_aliases (fund_name, is_preferred=TRUE, source_table='stg_nport_fund_universe')
  - entity_classification_history ('active'/'passive'/'unknown' from is_actively_managed)
  - entity_relationships (fund_sponsor to adviser)
  - entity_rollup_history × 2 (economic_control_v1 + decision_maker_v1)

Synthetic `{cik}_{accession}` series:
  - S1 (fund_cik already an entity) — wired as regular fund under that trust entity.
  - S2 (fund_cik not an entity)     — deferred; logged as `deferred_synthetic`.

Run:
  python3 scripts/resolve_pending_series.py --staging --dry-run
  python3 scripts/resolve_pending_series.py --staging
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import duckdb

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import db  # noqa: E402
from build_managers import PARENT_SEEDS  # noqa: E402
from entity_sync import (  # noqa: E402
    _verify_adv_relationship,
    get_or_create_fund_entity,
    insert_relationship_idempotent,
)

# Supplementary brand variants beyond PARENT_SEEDS. These cover ETF
# specialist sponsors whose family_name carries a brand token that doesn't
# appear in PARENT_SEEDS.variants. Each row:
#   (variant_upper, entity_id, canonical_label)
# Validated against staging DB during a 2026-04-15 dry-run; canonical_label
# is advisory only (the entity_id is the source of truth). These rows are
# treated as high-confidence, curated additions — they skip the DM13 ADV
# verification for the same reason PARENT_SEED matches do (the target
# entities are known brand-level rollup targets or registered adviser
# parents of their ETF trusts).
SUPPLEMENTARY_BRANDS = [
    # Relaxed PARENT_SEEDS variants (point to same seed entity)
    ("DIMENSIONAL",               7,    "Dimensional Fund Advisors"),
    ("FIRST TRUST",               8,    "First Trust"),
    ("FRANKLIN",                 28,    "Franklin Templeton"),
    ("MFS SERIES",               17,    "MFS Investment Management"),
    # ETF-specialist sponsors with their own entity rows
    ("INNOVATOR",              4342,    "Innovator Capital Management"),
    ("TIDAL",                  9013,    "Tidal Investments"),
    ("HARBOR",                   74,    "Harbor Capital"),
    ("PACER",                  8726,    "Pacer Advisors"),
    ("GRANITESHARES",          5836,    "GraniteShares Advisors"),
    ("THEMES",                 7107,    "Themes Management"),
    ("ROUNDHILL",              6007,    "Roundhill Financial"),
    ("SIMPLIFY",               3827,    "Simplify Asset Management"),
    ("AMPLIFY",                5233,    "Amplify Investments"),
    ("ALPS",                   6785,    "ALPS Advisors"),
    ("ADVISORSHARES",          9003,    "AdvisorShares Investments"),
    ("JOHN HANCOCK",           4313,    "John Hancock Investment Management"),
    ("DBX ETF",                8390,    "DBX Advisors"),
    ("EXCHANGE TRADED CONCEPTS", 3738,  "Exchange Traded Concepts"),
    ("ALLIANCEBERNSTEIN",        57,    "AllianceBernstein"),
    ("AB ACTIVE",                57,    "AllianceBernstein"),
    # 2026-04-15 ETF brand additions — confirmed against adv_managers.
    # Wires each trust family's series to its primary adviser.
    ("GLOBAL X",               8005,    "Global X Management"),
    ("KRANE",                  5640,    "Krane Funds Advisors"),
    ("SPDR SERIES",               3,    "State Street / SSGA"),       # PARENT_SEED brand
    ("COLUMBIA ETF",             52,    "Columbia Threadneedle"),     # PARENT_SEED brand
    ("EXCHANGE LISTED FUNDS", 3738,    "Exchange Traded Concepts"),
    # NEW entity created via scripts/bootstrap_etf_advisers.py (2026-04-15);
    # Van Eck and Aptus already existed in the entity graph and the
    # bootstrap script reused those eids instead of creating duplicates.
    ("VANECK",                 6197,    "Van Eck Associates"),       # existing
    ("AIM ETF",                8977,    "Aptus Capital Advisors"),    # existing
    ("BONDBLOXX",             23819,    "BondBloxx Investment Management"),
    # Multi-sub-adviser series-trust families. The trust's primary adviser
    # holds the advisory contract; per-series sub-adviser routing
    # (decision_maker_v1) is deferred to a future DM12-style audit and
    # should not be inferred from this wiring.
    # See `MULTI_SUBADVISER_VARIANTS` below for the runtime caveat tag.
    ("EA SERIES",              2944,    "Empowered Funds (Alpha Architect)"),
    ("ETF OPPORTUNITIES",      9013,    "Tidal Investments"),
    ("LISTED FUNDS",           8646,    "Vident Advisory"),
    # 2026-04-16 residual-616 additions — 25 Tier A (existing entity reuse)
    # and 7 Tier B (new entities from bootstrap_residual_advisers.py).
    # Each variant_upper is chosen as a multi-word prefix of the trust's
    # family_name to avoid collision with other brands (e.g. MFS MUNICIPAL
    # SERIES rather than bare MFS, since MFS SERIES already exists above).
    # Tier A — existing MDM entity reuse:
    ("MFS MUNICIPAL SERIES",          5047, "Massachusetts Financial Services"),
    ("MFS ACTIVE EXCHANGE",           5047, "Massachusetts Financial Services"),
    ("PRINCIPAL EXCHANGE",            6348, "Principal Global Investors"),
    ("REX ETF",                       3031, "REX Advisers, LLC"),
    ("NEW YORK LIFE INVESTMENTS ACTIVE", 8473, "New York Life Investment Management"),
    ("NEW YORK LIFE INVESTMENTS ETF", 8473, "New York Life Investment Management"),
    ("GUGGENHEIM FUNDS",               195, "Guggenheim Partners Investment Management"),
    ("SEI EXCHANGE TRADED",           9858, "SEI Investments Management Corp"),
    ("SEI TAX EXEMPT",                9858, "SEI Investments Management Corp"),
    ("ANGEL OAK FUNDS",              10620, "Angel Oak Capital Advisors"),
    ("VIKING MUTUAL",                 7821, "Viking Fund Management LLC"),
    ("THRIVENT ETF",                  7823, "Thrivent Asset Management"),
    ("RUSSELL INVESTMENTS EXCHANGE",  7856, "Russell Investments Implementation Services"),
    ("COHEN & STEERS ETF",             142, "Cohen & Steers Capital Management"),
    ("CAMBRIA ETF",                   3449, "Cambria Investment Management"),
    ("VIRTUS ETF",                     676, "Virtus Investment Advisers"),
    ("VIRTUS MANAGED ACCOUNT",         676, "Virtus Investment Advisers"),
    ("TCW ETF",                       1238, "TCW Investment Management"),
    ("TCW METROPOLITAN",              1238, "TCW Investment Management"),
    ("KURV ETF",                      4559, "Kurv Investment Management"),
    ("DOUBLELINE ETF",               18058, "DoubleLine Capital LP"),
    ("ALLSPRING EXCHANGE",            3421, "Allspring Global Investments"),
    ("VOYA FUNDS",                   17915, "Voya Investment Management"),
    ("TOUCHSTONE ETF",               18185, "Touchstone Advisors"),
    ("WESTERN ASSET FUNDS",           4636, "Western Asset Management"),
    # Tier B — new entities from bootstrap_residual_advisers.py (2026-04-16):
    ("STONE RIDGE",                  24348, "Stone Ridge Asset Management"),
    ("BITWISE FUNDS",                24349, "Bitwise Investment Manager"),
    ("VOLATILITY SHARES",            24350, "Volatility Shares LLC"),
    ("DUPREE MUTUAL",                24351, "Dupree & Company, Inc."),
    ("ABACUS FCF",                    3375, "Abacus FCF Advisors LLC"),
    # Baron ETF Trust's adviser is BAMCO Inc. (CRD=110789, CIK=0001017918),
    # which is already in MDM as eid=4830. The earlier bootstrap created
    # eid=24352 "Baron Capital Management" (a distinct Baron Group entity,
    # CRD=110791) but Baron ETF Trust does NOT use that advisory contract.
    # eid=24352 is retained but flagged for DM15b merge-cleanup review
    # (distinct entity, no downstream attribution yet).
    ("BARON ETF",                     4830, "BAMCO Inc. (Baron Capital)"),
    ("GRAYSCALE",                    24353, "Grayscale Advisors"),

    # 2026-04-17 Tier C additions — existing MDM eid reuse (76 families,
    # 475 pending series). Variants chosen as distinctive family-name
    # prefixes/fragments that won't collide with existing PARENT_SEEDS or
    # earlier SUPPLEMENTARY_BRANDS entries. All targets verified via
    # adv_managers CRD or preferred alias exact match.
    ("STRATEGY SHARES",              5731, "Rational Advisors, Inc."),
    ("WEBS ETF",                     7586, "BlackRock Fund Advisors"),
    ("ARK ETF",                      1531, "ARK Investment Management"),
    ("ETFIS SERIES",                  676, "Virtus Investment Advisers"),
    # FEDERATED HERMES covers ETF Trust + Core Trust + Institutional Trust
    # + Municipal Securities + ~8 other sub-trusts all advised by the US
    # entity (eid=7633), NOT the UK LLP (eid=4635 FEDERATED HERMES INC).
    ("FEDERATED HERMES",             7633, "Federated Investment Management Co"),
    ("FLEXSHARES",                   3704, "Northern Trust Investments"),
    ("GMO ETF",                      7119, "Grantham, Mayo, Van Otterloo"),
    ("E-VALUATOR",                   1275, "Systelligence, LLC"),
    ("ALLIANZ VARIABLE INSURANCE",   7807, "Allianz Investment Management"),
    ("MASSMUTUAL ADVANTAGE",        17969, "MML Investment Advisers"),
    ("DAVIS FUNDAMENTAL",            3703, "Davis Selected Advisers"),
    ("MADISON ETFS",                 4314, "Madison Asset Management"),
    ("TEXAS CAPITAL FUNDS",          6207, "Texas Capital Bank Wealth Mgmt"),
    ("THORNBURG ETF",                2925, "Thornburg Investment Management"),
    ("VALKYRIE ETF",                 1057, "Valkyrie Funds LLC"),
    ("ABSOLUTE SHARES",              1000, "WBI Investments, LLC"),
    ("ASPIRIANT TRUST",              8201, "Aspiriant, LLC"),
    ("AMERICAN BEACON SELECT",      10486, "American Beacon Advisors"),
    ("GUGGENHEIM STRATEGY",           195, "Guggenheim Partners Investment Mgmt"),
    ("GUGGENHEIM VARIABLE",           195, "Guggenheim Partners Investment Mgmt"),
    ("MILLER INVESTMENT",            7858, "Miller Value Partners, LLC"),
    ("SEI DAILY INCOME",             9858, "SEI Investments Management Corp"),
    ("SIT MUTUAL",                   4281, "Sit Investment Associates"),
    ("SIT U S GOVERNMENT",           4281, "Sit Investment Associates"),
    ("STRATEGIC TRUST",              5687, "Charles Schwab Investment Mgmt"),
    ("TEMPLETON INCOME",             1355, "Franklin Advisers, Inc."),
    ("ABRDN",                        4450, "abrdn Inc."),
    ("HOMESTEAD",                    7816, "Homestead Advisers Corp"),
    ("HUMANKIND",                    8920, "Humankind Investments LLC"),
    ("INTERNATIONAL INCOME PORTFOLIO", 3586, "BlackRock Advisors, LLC"),
    ("MASTER INVESTMENT PORTFOLIO",  7586, "BlackRock Fund Advisors"),
    ("NATIXIS ETF",                  2271, "Natixis Advisors, LLC"),
    ("POPULAR HIGH GRADE",          19360, "Popular Asset Management"),
    ("POPULAR INCOME",              19360, "Popular Asset Management"),
    ("THRIVE SERIES",                1022, "Thrive Wealth Management"),
    ("AB CORPORATE SHARES",            57, "AllianceBernstein"),
    ("AB MUNICIPAL INCOME",            57, "AllianceBernstein"),

    # 2026-04-17 Tier C bootstraps — 6 new entities from
    # scripts/bootstrap_tier_c_advisers.py (eids 24633-24638).
    # Explicit long-form variant for Exchange Listed Funds Trust — paired
    # with the longest-match tiebreaker in try_brand_substring to beat the
    # legacy `LISTED FUNDS` → 8646 (Vident) collision on this family.
    ("EXCHANGE LISTED FUNDS TRUST",     3738, "Exchange Traded Concepts"),
    # 2026-04-17 Tier D additions:
    ("TEMA ETF",                        7238, "TEMA ETFS LLC"),
    ("PALMER SQUARE FUNDS",           24862, "Palmer Square Capital Management"),
    ("RAYLIANT FUNDS",                24863, "Rayliant Investment Research"),
    ("COLLABORATIVE INVESTMENT SERIES", 24633, "Collaborative Fund Management"),
    ("SPINNAKER ETF SERIES",           24634, "Spinnaker Financial Advisors"),
    ("TRUTH SOCIAL",                   24635, "Yorkville Capital Management"),
    ("FUNDX INVESTMENT",               24636, "FundX Investment Group"),
    ("PROCURE ETF",                    24637, "Procure AM, LLC"),
    ("COMMUNITY DEVELOPMENT FUND",     24638, "Community Development Fund Advisors"),
]

# Variants whose target trust hosts multiple sub-advisers per series.
# Surfaces as a caveat string in the resolver decision log so that the
# DM12 audit can recover the rows that need per-series sub-adviser
# routing.
MULTI_SUBADVISER_VARIANTS = {
    "EA SERIES",
    "ETF OPPORTUNITIES",
    "LISTED FUNDS",
    "EXCHANGE LISTED FUNDS",
}

BASE_DIR = os.path.dirname(SCRIPT_DIR)
PROD_DB = os.path.join(BASE_DIR, "data", "13f.duckdb")

logger = logging.getLogger("resolve_pending_series")


# ---------------------------------------------------------------------------
# Data model for a single resolution attempt
# ---------------------------------------------------------------------------
@dataclass
class Pending:
    series_id: str
    fund_cik: Optional[str]
    fund_name: Optional[str]
    family_name: Optional[str]
    is_actively_managed: Optional[bool]
    is_synthetic: bool


@dataclass
class Decision:
    series_id: str
    tier: str                # 'T1', 'T2', 'T3', 'S1', 'unresolved', 'deferred_synthetic', 'verification_failed'
    adviser_entity_id: Optional[int] = None
    adviser_crd: Optional[str] = None
    match_name: Optional[str] = None
    score: Optional[int] = None
    confidence: str = "unknown"
    reason: str = ""
    new_fund_entity_id: Optional[int] = None


@dataclass
class Stats:
    total: int = 0
    t1: int = 0
    t2: int = 0
    t3: int = 0
    s1: int = 0
    deferred_synthetic: int = 0
    verification_failed: int = 0
    unresolved: int = 0
    new_fund_entities: int = 0
    new_adviser_entities: int = 0
    relationships_inserted: int = 0
    rollup_rows_inserted: int = 0
    errors: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Staging constraint bootstrap
# ---------------------------------------------------------------------------
def _ensure_staging_indexes(con) -> None:
    """Prep staging for entity_sync.py's INSERT + ON CONFLICT pattern.

    sync_staging.py uses CTAS which strips BOTH indexes AND column
    defaults from staging. entity_sync.get_or_create_entity_by_identifier
    relies on:
      1. A unique index so bare `ON CONFLICT DO NOTHING` resolves.
      2. The valid_from / valid_to column defaults from entity_schema.sql
         (DATE '2000-01-01' / DATE '9999-12-31') — the INSERT does NOT
         set those columns explicitly, so without defaults the rows land
         with NULL sentinels and are invisible to every SCD-filter query.

    Both are safe to add in staging: verified 0 dups on either index key
    and 0 NULL dates in the synced-from-prod rows.
    """
    # Column defaults (no-op if already present)
    try:
        con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_from "
                    "SET DEFAULT DATE '2000-01-01'")
        con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_to "
                    "SET DEFAULT DATE '9999-12-31'")
    except duckdb.Error as e:
        # Pre-existing dependency (unique index) blocks ALTER — drop and
        # re-try, then recreate the index below.
        if "Dependency Error" in str(e):
            con.execute("DROP INDEX IF EXISTS ux_staging_eid_type_value")
            con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_from "
                        "SET DEFAULT DATE '2000-01-01'")
            con.execute("ALTER TABLE entity_identifiers ALTER COLUMN valid_to "
                        "SET DEFAULT DATE '9999-12-31'")
        else:
            raise

    # Unique indexes for ON CONFLICT targets
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_staging_eid_type_value "
        "ON entity_identifiers (identifier_type, identifier_value, entity_id)"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_staging_er_triple "
        "ON entity_relationships (parent_entity_id, child_entity_id, "
        "relationship_type, valid_to)"
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_pending_with_context(con, limit: Optional[int]) -> list[Pending]:
    """Attach prod read-only, pull pending series, join to stg_nport metadata."""
    con.execute(f"ATTACH '{PROD_DB}' AS prod (READ_ONLY)")  # nosec B608 — internal constant
    try:
        rows = con.execute(
            """
            WITH p AS (
                SELECT identifier_value AS series_id
                FROM prod.pending_entity_resolution
                WHERE identifier_type = 'series_id'
                  AND resolution_status = 'pending'
            ),
            ctx AS (
                SELECT
                    s.series_id,
                    ANY_VALUE(s.fund_cik)       AS fund_cik,
                    ANY_VALUE(s.fund_name)      AS fund_name,
                    ANY_VALUE(s.family_name)    AS family_name,
                    ANY_VALUE(u.is_actively_managed) AS is_actively_managed
                FROM stg_nport_holdings s
                LEFT JOIN stg_nport_fund_universe u USING (series_id)
                GROUP BY s.series_id
            )
            SELECT p.series_id, ctx.fund_cik, ctx.fund_name,
                   ctx.family_name, ctx.is_actively_managed
            FROM p LEFT JOIN ctx USING (series_id)
            ORDER BY p.series_id
            """ + (f" LIMIT {int(limit)}" if limit else "")
        ).fetchall()
    finally:
        con.execute("DETACH prod")

    result = []
    for series_id, fund_cik, fund_name, family_name, actively in rows:
        is_synth = not series_id.startswith("S")
        result.append(Pending(
            series_id=series_id,
            fund_cik=fund_cik,
            fund_name=fund_name,
            family_name=family_name,
            is_actively_managed=bool(actively) if actively is not None else None,
            is_synthetic=is_synth,
        ))
    return result


def load_ncen_trust_map(con) -> dict[str, list[tuple]]:
    """{registrant_cik_padded -> [(adviser_crd, adviser_name, role, filing_date), ...]}.

    ORDER BY filing_date DESC so the first row per trust is the most recent.
    """
    rows = con.execute(
        """
        SELECT LPAD(registrant_cik, 10, '0') AS reg_cik,
               adviser_crd,
               adviser_name,
               COALESCE(role, 'adviser') AS role,
               filing_date
        FROM ncen_adviser_map
        WHERE adviser_crd IS NOT NULL AND adviser_crd != ''
        ORDER BY reg_cik, filing_date DESC
        """
    ).fetchall()
    out: dict[str, list[tuple]] = {}
    for reg, crd, name, role, fdate in rows:
        out.setdefault(reg, []).append((crd, name, role, fdate))
    return out


def load_entity_crd_map(con) -> dict[str, int]:
    """{crd_normalized -> entity_id} for active identifiers. LTRIM leading zeros."""
    rows = con.execute(
        """
        SELECT LTRIM(identifier_value, '0') AS crd_norm, entity_id
        FROM entity_identifiers
        WHERE identifier_type = 'crd'
          AND valid_to = DATE '9999-12-31'
        """
    ).fetchall()
    return {crd: eid for crd, eid in rows}


def load_entity_cik_map(con) -> dict[str, int]:
    """{cik_padded -> entity_id} for active identifiers."""
    rows = con.execute(
        """
        SELECT identifier_value AS cik_padded, entity_id
        FROM entity_identifiers
        WHERE identifier_type = 'cik'
          AND valid_to = DATE '9999-12-31'
        """
    ).fetchall()
    return {cik: eid for cik, eid in rows}


def build_brand_table(con) -> list[tuple[str, int, str]]:
    """Build a substring-matchable list of (variant_upper, entity_id, canonical).

    Two sources:
      1. PARENT_SEEDS from build_managers.py — authoritative 110 brands / 147
         variants. Canonical names map to existing entities by exact-match on
         entities.canonical_name.
      2. fund_family_patterns — 83 additional patterns, each with an
         inst_parent_name lowercase key; we resolve the key to an entity via
         a best-effort canonical-name ILIKE match. Only retained when the
         resolution is unambiguous.
    """
    brands: list[tuple[str, int, str]] = []

    # Source 1 — PARENT_SEEDS
    seed_rows = con.execute(
        "SELECT entity_id, canonical_name FROM entities "
        "WHERE entity_type = 'institution'"
    ).fetchall()
    canonical_to_eid = {name: eid for eid, name in seed_rows}
    for canonical, _strategy, variants in PARENT_SEEDS:
        eid = canonical_to_eid.get(canonical)
        if not eid:
            continue
        for v in variants:
            brands.append((v.upper().strip(), eid, canonical))

    # Source 2 — SUPPLEMENTARY_BRANDS (curated ETF-specialist additions)
    # Filter to brands whose entity_id still exists in staging (guards
    # against staged deletion; defensive only).
    valid_eids = {row[0] for row in seed_rows}
    for variant, s_eid, canonical in SUPPLEMENTARY_BRANDS:
        if s_eid in valid_eids:
            brands.append((variant.upper().strip(), s_eid, canonical))

    # Note: fund_family_patterns is NOT merged here because (a) its
    # inst_parent_name → entity_id resolution requires unsafe ILIKE
    # fallback that picks arbitrary subsidiaries, and (b) its top brands
    # already appear in PARENT_SEEDS. Residual specialty sponsors (VanEck,
    # Global X, Krane Shares, BondBloxx, EA Series, Listed Funds) lack
    # resolvable US-adviser entities and stay in the unresolved report
    # for manual follow-up.

    # Deduplicate on (variant, entity_id), sort longest-variant-first so the
    # most specific match is tried first (e.g. 'J.P. MORGAN' before 'MORGAN').
    dedup: dict[tuple[str, int], str] = {}
    for v, eid, canonical in brands:
        key = (v, eid)
        if key not in dedup:
            dedup[key] = canonical
    brand_list = [(v, eid, c) for (v, eid), c in dedup.items()]
    brand_list.sort(key=lambda x: -len(x[0]))
    logger.info("Brand table loaded: %d variants from %d PARENT_SEEDS",
                len(brand_list), len(PARENT_SEEDS))
    return brand_list


# ---------------------------------------------------------------------------
# Resolution tiers
# ---------------------------------------------------------------------------
def try_t1_ncen(p: Pending, ncen_map, crd_entity_map) -> Optional[Decision]:
    """N-CEN: trust's most-recent adviser CRD → existing entity."""
    if not p.fund_cik:
        return None
    reg_padded = p.fund_cik.zfill(10)
    trust_rows = ncen_map.get(reg_padded)
    if not trust_rows:
        return None

    # Prefer role='adviser' (primary). If absent, take most recent row regardless.
    advisers = [r for r in trust_rows if r[2] == "adviser"]
    if not advisers:
        advisers = trust_rows

    # Most recent filing already first due to ORDER BY. Pick the first whose
    # CRD maps to an existing entity; skip CRDs that don't resolve.
    for crd, name, role, fdate in advisers:
        crd_norm = (crd or "").lstrip("0")
        eid = crd_entity_map.get(crd_norm)
        if eid:
            return Decision(
                series_id=p.series_id, tier="T1",
                adviser_entity_id=eid, adviser_crd=crd,
                match_name=name, confidence="exact",
                reason=f"ncen registrant_cik={reg_padded} role={role} filing_date={fdate}",
            )
    return None


def try_brand_substring(
    p: Pending, brands: list[tuple[str, int, str]], con, tier: str,
) -> Optional[Decision]:
    """T2/T3: substring-match against known brand variants.

    T2 uses family_name; T3 uses fund_name. Matches only on unambiguous
    single-canonical hits. DM13 pre-insert verification then confirms the
    parent is a registered adviser in adv_managers (rejects umbrella-
    trust-only matches).
    """
    name = p.family_name if tier == "T2" else p.fund_name
    if not name:
        return None
    query = name.upper()
    # Word-boundary guard: pad both sides so substring matches only fire
    # at whitespace/string boundaries (e.g. 'ARK ETF' no longer matches
    # inside 'CROSSMARK ETF TRUST'). The padded comparison still accepts
    # legitimate mid-string brand tokens that are themselves word-bounded
    # (e.g. 'LISTED FUNDS' in 'EXCHANGE LISTED FUNDS TRUST').
    padded = " " + query + " "

    # Collect substring hits; dedupe on entity_id so PARENT_SEEDS +
    # fund_family_patterns both resolving to the same brand don't trigger
    # spurious ambiguity. Prefer PARENT_SEEDS canonical label (comes first
    # in the brand list).
    hits: list[tuple[str, int, str]] = []  # (variant, entity_id, canonical)
    seen_eids: set[int] = set()
    for variant, eid, canonical in brands:
        if f" {variant} " in padded and eid not in seen_eids:
            hits.append((variant, eid, canonical))
            seen_eids.add(eid)

    if not hits:
        return None

    # Longest-match tiebreaker: when multiple hits exist and one variant
    # is a strict superstring of another covering the same match, prefer
    # the more specific one. Example: 'EXCHANGE LISTED FUNDS TRUST'
    # (3738) wins over 'LISTED FUNDS' (8646) inside 'Exchange Listed
    # Funds Trust'. `brands` is pre-sorted longest-variant-first at load
    # time, so the first hit is always the longest — if it covers any
    # shorter hit's variant as a substring at the same query position,
    # drop the shorter hit.
    if len(hits) > 1:
        primary_variant, _pri_eid, _pri_canonical = hits[0]
        filtered = [hits[0]]
        for h_variant, h_eid, h_canonical in hits[1:]:
            if f" {h_variant} " in f" {primary_variant} ":
                continue
            filtered.append((h_variant, h_eid, h_canonical))
        hits = filtered

    if len(hits) != 1:
        return Decision(
            series_id=p.series_id, tier=f"{tier}_ambiguous", confidence="low",
            reason=(f"{tier} ambiguous: {len(hits)} entities matched "
                    f"[{', '.join(h[2] for h in hits[:3])}]"),
        )

    (variant, eid, canonical) = hits[0]

    # Curated brand matches (PARENT_SEEDS + SUPPLEMENTARY_BRANDS) skip
    # the DM13 ADV verification. PARENT_SEED entities are brand-level
    # rollup targets with no ADV row by design; SUPPLEMENTARY_BRANDS were
    # hand-curated against staging. Any other sources go through the
    # standard _verify_adv_relationship gate.
    if canonical not in _TRUSTED_CANONICALS:
        verified, _conf, vreason = _verify_adv_relationship(
            con, child_entity_id=0, parent_entity_id=eid, owner_name=canonical,
        )
        if not verified:
            return Decision(
                series_id=p.series_id, tier="verification_failed",
                adviser_entity_id=eid, match_name=canonical,
                confidence="low", reason=f"{tier}_{vreason}",
            )

    reason = f"brand substring {variant!r} in {name!r} → {canonical}"
    if variant in MULTI_SUBADVISER_VARIANTS:
        reason += (" [PRIMARY-ADVISER ATTRIBUTION ONLY — multi-sub-adviser trust;"
                   " per-series sub-adviser routing deferred to future DM12 audit]")
    return Decision(
        series_id=p.series_id, tier=tier,
        adviser_entity_id=eid, match_name=canonical,
        score=100, confidence="high",
        reason=reason,
    )


_TRUSTED_CANONICALS = (
    {s[0] for s in PARENT_SEEDS}
    | {c for _v, _e, c in SUPPLEMENTARY_BRANDS}
)


def try_s1_synthetic(p: Pending, cik_entity_map) -> Optional[Decision]:
    """Synthetic series whose fund_cik is already in entity_identifiers."""
    if not p.is_synthetic or not p.fund_cik:
        return None
    eid = cik_entity_map.get(p.fund_cik.zfill(10))
    if not eid:
        return None
    return Decision(
        series_id=p.series_id, tier="S1",
        adviser_entity_id=eid, confidence="exact",
        reason=f"fund_cik={p.fund_cik} already wired as entity_id={eid}",
    )


# ---------------------------------------------------------------------------
# Write phase — create fund entity + all its SCD rows
# ---------------------------------------------------------------------------
def wire_fund_entity(
    con, p: Pending, d: Decision, source: str, stats: Stats
) -> bool:
    """Create fund entity + identifier + alias + classification + relationship
    + two rollup rows, all in one transaction. Returns True on success.
    """
    adviser_eid = d.adviser_entity_id
    assert adviser_eid is not None

    # Guard against double-creation if the series already landed in a prior run.
    existing = con.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type='series_id' AND identifier_value=?
             AND valid_to = DATE '9999-12-31'""",
        [p.series_id],
    ).fetchone()
    if existing:
        # Already an entity; attach the relationship only if missing.
        fund_eid = existing[0]
        d.new_fund_entity_id = fund_eid
    else:
        display_name = p.fund_name or p.series_id
        fund_result = get_or_create_fund_entity(
            con, p.series_id, display_name, source, is_inferred=True,
        )
        fund_eid = fund_result.entity_id
        d.new_fund_entity_id = fund_eid
        if fund_result.was_created:
            stats.new_fund_entities += 1

        # Alias row — only if the entity has no preferred alias yet
        existing_alias = con.execute(
            """SELECT 1 FROM entity_aliases
               WHERE entity_id=? AND is_preferred=TRUE
                 AND valid_to = DATE '9999-12-31'""",
            [fund_eid],
        ).fetchone()
        if not existing_alias:
            con.execute(
                """INSERT INTO entity_aliases
                     (entity_id, alias_name, alias_type, is_preferred,
                      preferred_key, source_table, is_inferred,
                      valid_from, valid_to)
                   VALUES (?, ?, 'brand', TRUE, ?,
                           'stg_nport_fund_universe', TRUE,
                           DATE '2000-01-01', DATE '9999-12-31')""",
                [fund_eid, display_name, fund_eid],
            )

        # Classification row
        classification = "unknown"
        if p.is_actively_managed is True:
            classification = "active"
        elif p.is_actively_managed is False:
            classification = "passive"
        existing_cls = con.execute(
            """SELECT 1 FROM entity_classification_history
               WHERE entity_id=? AND valid_to = DATE '9999-12-31'""",
            [fund_eid],
        ).fetchone()
        if not existing_cls:
            con.execute(
                """INSERT INTO entity_classification_history
                     (entity_id, classification, is_activist, confidence,
                      source, is_inferred, valid_from, valid_to)
                   VALUES (?, ?, FALSE, 'exact',
                           'stg_nport_fund_universe', TRUE,
                           DATE '2000-01-01', DATE '9999-12-31')""",
                [fund_eid, classification],
            )

    # Relationship: fund_sponsor, primary, control
    inserted = insert_relationship_idempotent(
        con,
        parent_id=adviser_eid,
        child_id=fund_eid,
        rel_type="fund_sponsor",
        control_type="advisory",
        is_primary=True,
        confidence=d.confidence,
        source=source,
        is_inferred=True,
        match_score=d.score or 0,
    )
    if inserted:
        stats.relationships_inserted += 1

    # Rollup rows — two (economic_control_v1 + decision_maker_v1)
    for rollup_type in ("economic_control_v1", "decision_maker_v1"):
        existing_rh = con.execute(
            """SELECT 1 FROM entity_rollup_history
               WHERE entity_id=? AND rollup_type=?
                 AND valid_to = DATE '9999-12-31'""",
            [fund_eid, rollup_type],
        ).fetchone()
        if existing_rh:
            continue
        routing_conf = "high" if d.tier in ("T1", "S1") else (
            "medium" if (d.score or 0) >= 95 else "low"
        )
        src_label = "N-CEN" if d.tier == "T1" else (
            "sibling_cik" if d.tier == "S1" else "alias_match"
        )
        con.execute(
            """INSERT INTO entity_rollup_history
                 (entity_id, rollup_entity_id, rollup_type, rule_applied,
                  confidence, valid_from, valid_to, computed_at, source,
                  routing_confidence)
               VALUES (?, ?, ?, 'fund_sponsor', ?,
                       DATE '2000-01-01', DATE '9999-12-31',
                       CURRENT_TIMESTAMP, ?, ?)""",
            [fund_eid, adviser_eid, rollup_type, d.confidence,
             src_label, routing_conf],
        )
        stats.rollup_rows_inserted += 1
    return True


# ---------------------------------------------------------------------------
# CSV log
# ---------------------------------------------------------------------------
def write_log(path: str, decisions: list[Decision], pending_by_sid: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "series_id", "tier", "fund_cik", "fund_name", "family_name",
            "adviser_entity_id", "adviser_crd", "match_name", "score",
            "confidence", "new_fund_entity_id", "reason",
        ])
        for d in decisions:
            p = pending_by_sid.get(d.series_id)
            w.writerow([
                d.series_id, d.tier,
                p.fund_cik if p else "",
                p.fund_name if p else "",
                p.family_name if p else "",
                d.adviser_entity_id or "",
                d.adviser_crd or "",
                d.match_name or "",
                d.score or "",
                d.confidence,
                d.new_fund_entity_id or "",
                d.reason,
            ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staging", action="store_true", required=True,
                    help="Safety gate — must be set; prod writes not allowed.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute decisions + log, but don't write to staging.")
    ap.add_argument("--tiers", default="T1,T2,T3,S1",
                    help="Comma-separated tier subset (default: all).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N pending series (for testing).")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    tiers_on = set(t.strip() for t in args.tiers.split(","))

    db.set_staging_mode(True)
    staging_path = db.get_db_path()
    logger.info("=" * 70)
    logger.info("resolve_pending_series.py — dry_run=%s tiers=%s limit=%s",
                args.dry_run, sorted(tiers_on), args.limit)
    logger.info("  staging = %s", staging_path)
    logger.info("  prod    = %s", PROD_DB)
    logger.info("=" * 70)

    con = db.connect_write()
    try:
        _ensure_staging_indexes(con)

        pendings = load_pending_with_context(con, args.limit)
        logger.info("Loaded %d pending series from prod", len(pendings))
        pending_by_sid = {p.series_id: p for p in pendings}

        ncen_map = load_ncen_trust_map(con)
        crd_entity_map = load_entity_crd_map(con)
        cik_entity_map = load_entity_cik_map(con)
        logger.info("N-CEN trusts indexed: %d   CRDs→entities: %d   CIKs→entities: %d",
                    len(ncen_map), len(crd_entity_map), len(cik_entity_map))

        brands = build_brand_table(con)

        stats = Stats(total=len(pendings))
        decisions: list[Decision] = []

        for i, p in enumerate(pendings, 1):
            d = None

            # Tier 1 — N-CEN authoritative
            if "T1" in tiers_on:
                d = try_t1_ncen(p, ncen_map, crd_entity_map)

            # Synthetic S1 — fund_cik already an entity
            if d is None and p.is_synthetic and "S1" in tiers_on:
                d = try_s1_synthetic(p, cik_entity_map)

            # Synthetic S2 — defer (no further tiers for synthetics; their
            # family_name is usually the umbrella trust, not the brand)
            if d is None and p.is_synthetic:
                d = Decision(
                    series_id=p.series_id, tier="deferred_synthetic",
                    confidence="low",
                    reason="synthetic series_id with no fund_cik entity",
                )
                decisions.append(d)
                stats.deferred_synthetic += 1
                continue

            # Tier 2 — family_name brand substring
            prior: Optional[Decision] = None
            if d is None and "T2" in tiers_on:
                d = try_brand_substring(p, brands, con, "T2")
                # Retry with T3 on ambiguity or verification failure
                if d and (d.tier.endswith("_ambiguous")
                          or d.tier == "verification_failed"):
                    prior = d
                    d = None

            # Tier 3 — fund_name brand substring
            if d is None and "T3" in tiers_on:
                d = try_brand_substring(p, brands, con, "T3")
                if d and d.tier.endswith("_ambiguous"):
                    d = None
            # Fall back to T2's earlier failure record if T3 produced nothing
            if d is None and prior is not None:
                d = prior

            if d is None:
                d = Decision(
                    series_id=p.series_id, tier="unresolved", confidence="low",
                    reason="no tier matched",
                )
                decisions.append(d)
                stats.unresolved += 1
                continue

            if d.tier == "verification_failed":
                decisions.append(d)
                stats.verification_failed += 1
                continue
            if d.tier.endswith("_ambiguous"):
                # Both T2 and T3 returned ambiguous matches — log + skip.
                decisions.append(d)
                stats.unresolved += 1
                continue

            # Wire the fund entity
            if not args.dry_run:
                try:
                    con.execute("BEGIN TRANSACTION")
                    wire_fund_entity(
                        con, p, d,
                        source={
                            "T1": "ncen_adviser_map",
                            "T2": "family_name_alias_match",
                            "T3": "fund_name_alias_match",
                            "S1": "fund_cik_sibling",
                        }[d.tier],
                        stats=stats,
                    )
                    con.execute("COMMIT")
                except Exception as e:
                    con.execute("ROLLBACK")
                    stats.errors.append((p.series_id, str(e)))
                    logger.error("series_id=%s wire failed: %s", p.series_id, e)
                    d = Decision(
                        series_id=p.series_id, tier="error",
                        confidence="low", reason=f"wire_exception: {e}",
                    )
                    decisions.append(d)
                    continue

            decisions.append(d)
            if d.tier == "T1":
                stats.t1 += 1
            elif d.tier == "T2":
                stats.t2 += 1
            elif d.tier == "T3":
                stats.t3 += 1
            elif d.tier == "S1":
                stats.s1 += 1

            if i % 500 == 0:
                try:
                    con.execute("CHECKPOINT")
                except duckdb.Error:
                    pass
                logger.info(
                    "  [%d/%d] t1=%d t2=%d t3=%d s1=%d "
                    "synth_deferred=%d verify_fail=%d unresolved=%d",
                    i, len(pendings),
                    stats.t1, stats.t2, stats.t3, stats.s1,
                    stats.deferred_synthetic,
                    stats.verification_failed, stats.unresolved,
                )

        try:
            con.execute("CHECKPOINT")
        except duckdb.Error:
            pass

    finally:
        con.close()

    # Log CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(
        BASE_DIR, "logs", f"pending_series_resolution_{ts}.csv",
    )
    write_log(log_path, decisions, pending_by_sid)

    # Summary
    logger.info("=" * 70)
    logger.info("RESOLUTION SUMMARY (dry_run=%s)", args.dry_run)
    logger.info("  total pending:          %d", stats.total)
    logger.info("  T1 N-CEN:               %d", stats.t1)
    logger.info("  T2 family fuzzy:        %d", stats.t2)
    logger.info("  T3 fund name fuzzy:     %d", stats.t3)
    logger.info("  S1 synthetic via CIK:   %d", stats.s1)
    logger.info("  verification_failed:    %d", stats.verification_failed)
    logger.info("  deferred_synthetic:     %d", stats.deferred_synthetic)
    logger.info("  unresolved:             %d", stats.unresolved)
    resolved = stats.t1 + stats.t2 + stats.t3 + stats.s1
    real_pending = stats.total - stats.deferred_synthetic
    pct = (resolved / real_pending * 100) if real_pending else 0
    logger.info("  resolved / real pending: %d / %d (%.1f%%)",
                resolved, real_pending, pct)
    logger.info("  new fund entities:      %d", stats.new_fund_entities)
    logger.info("  relationships inserted: %d", stats.relationships_inserted)
    logger.info("  rollup rows inserted:   %d", stats.rollup_rows_inserted)
    if stats.errors:
        logger.warning("  errors:                 %d", len(stats.errors))
    logger.info("  log: %s", log_path)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
