#!/usr/bin/env python3
"""
build_managers.py — Build managers and parent_bridge tables.
                    Link CIK to CRD via name fuzzy match.
                    Seed top 50 institutional parents.
                    Enrich holdings_v2 with manager metadata.

Run: python3 scripts/build_managers.py                  # full run, prod
     python3 scripts/build_managers.py --staging        # full run, staging DB
     python3 scripts/build_managers.py --dry-run        # no writes, print projections
     python3 scripts/build_managers.py --enrichment-only # only UPDATE holdings_v2
     (Requires pipeline/load_adv.py and load_13f.py to have run first)
"""

import os
import sys
import csv
import re
import argparse
import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
from db import record_freshness  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# INF17 Phase 3 — Brand-token verification gate
# ---------------------------------------------------------------------------
# rapidfuzz.fuzz.token_sort_ratio with score_cutoff=85 alone produces false
# positives when firm names share generic corporate-suffix tokens ("LLC",
# "Capital", "Management") without sharing any distinguishing brand tokens.
# INF17's audit found 127 such pollutions — e.g., "SOROS FUND MANAGEMENT LLC"
# vs "VSS FUND MANAGEMENT LLC" scored 94, well above the 85 cutoff. We add a
# second gate: require at least one non-stopword brand token in common.
# Stopword list kept minimal per INF17 spec; expand only if the rejection
# log surfaces a pattern worth generalizing.
_BRAND_STOPWORDS = frozenset({
    "llc", "lp", "inc", "ltd", "co", "corp", "fund", "capital", "management",
    "advisors", "partners", "holdings", "group", "the", "and", "of", "asset",
    "investment", "financial", "services", "wealth",
})


def _brand_tokens(name):
    """Return the set of non-stopword brand tokens in a firm name.

    Lowercase, split on any non-alphanumeric character, drop stopwords and
    tokens shorter than 3 chars. Used as a second gate on top of rapidfuzz
    (INF17 Phase 3).
    """
    if not name:
        return set()
    raw = re.split(r"[^a-z0-9]+", str(name).lower())
    return {t for t in raw if len(t) >= 3 and t not in _BRAND_STOPWORDS}


def _brand_tokens_overlap(a, b):
    """True if two firm names share at least one brand token after stopword removal."""
    ta = _brand_tokens(a)
    tb = _brand_tokens(b)
    return bool(ta and tb and (ta & tb))


def _city_state_compatible(filer_city, filer_state, adv_city, adv_state):
    """True if city+state match, or if either side is missing values.

    Returns False only when both sides are populated and disagree. Missing
    values on either side short-circuit to True so we don't block matches
    where verification data isn't available (e.g. the filer side, which
    currently never has city/state in filings_deduped — future-proofing).
    """
    if not filer_city or not filer_state or not adv_city or not adv_state:
        return True
    return (
        str(filer_city).strip().upper() == str(adv_city).strip().upper()
        and str(filer_state).strip().upper() == str(adv_state).strip().upper()
    )


# ---------------------------------------------------------------------------
# Top 50 institutional parent seed list
# Each entry: (parent_name, strategy_type, [name variants for matching])
# ---------------------------------------------------------------------------
PARENT_SEEDS = [
    # Passive (index-dominant)
    ("Vanguard Group", "passive", ["VANGUARD GROUP", "VANGUARD"]),
    ("BlackRock / iShares", "passive", ["BLACKROCK", "ISHARES"]),
    ("State Street / SSGA", "passive", ["STATE STREET", "SSGA"]),
    ("Invesco", "passive", ["INVESCO"]),
    ("Charles Schwab", "passive", ["CHARLES SCHWAB", "SCHWAB"]),
    ("Northern Trust", "passive", ["NORTHERN TRUST"]),
    ("Dimensional Fund Advisors", "passive", ["DIMENSIONAL FUND", "DFA "]),
    ("First Trust", "passive", ["FIRST TRUST ADVISORS"]),
    ("Nuveen / TIAA", "passive", ["NUVEEN", "TIAA"]),
    ("Legal & General", "passive", ["LEGAL & GENERAL", "LEGAL AND GENERAL"]),

    # Active
    ("Fidelity / FMR", "active", ["FMR LLC", "FIDELITY"]),
    ("Capital Group / American Funds", "active", ["CAPITAL GROUP", "CAPITAL RESEARCH", "AMERICAN FUNDS"]),
    ("T. Rowe Price", "active", ["T. ROWE PRICE", "T ROWE PRICE"]),
    ("Wellington Management", "active", ["WELLINGTON MANAGEMENT"]),
    ("Dodge & Cox", "active", ["DODGE & COX", "DODGE AND COX"]),
    ("Putnam Investments", "active", ["PUTNAM"]),
    ("MFS Investment Management", "active", ["MFS INVESTMENT", "MFS INST"]),
    ("American Century", "active", ["AMERICAN CENTURY"]),
    ("Eaton Vance", "active", ["EATON VANCE"]),
    ("Gabelli", "active", ["GABELLI"]),

    # Mixed (active + passive)
    ("JPMorgan Asset Management", "mixed", ["JPMORGAN", "JP MORGAN", "J.P. MORGAN"]),
    ("Goldman Sachs Asset Management", "mixed", ["GOLDMAN SACHS"]),
    ("Morgan Stanley Investment Management", "mixed", ["MORGAN STANLEY"]),
    ("UBS Asset Management", "mixed", ["UBS "]),
    ("Deutsche Asset Management", "mixed", ["DEUTSCHE", "DWS"]),
    ("BNY Mellon / Dreyfus", "mixed", ["BNY MELLON", "BANK OF NEW YORK MELLON", "DREYFUS"]),
    ("Affiliated Managers Group", "mixed", ["AFFILIATED MANAGERS"]),
    ("Franklin Templeton", "mixed", ["FRANKLIN TEMPLETON", "FRANKLIN RESOURCES"]),
    ("Legg Mason", "mixed", ["LEGG MASON"]),
    ("PIMCO", "mixed", ["PIMCO", "PACIFIC INVESTMENT"]),

    # Quantitative
    ("AQR Capital", "quantitative", ["AQR CAPITAL"]),
    ("Two Sigma", "quantitative", ["TWO SIGMA"]),
    ("Renaissance Technologies", "quantitative", ["RENAISSANCE TECHNOLOGIES"]),
    ("DE Shaw", "quantitative", ["D. E. SHAW", "DE SHAW", "D E SHAW"]),
    ("Winton Group", "quantitative", ["WINTON"]),
    ("Man Group", "quantitative", ["MAN GROUP"]),
    ("Millennium Management", "quantitative", ["MILLENNIUM MANAGEMENT"]),
    ("Citadel Advisors", "quantitative", ["CITADEL"]),
    ("Point72", "quantitative", ["POINT72"]),
    ("Balyasny", "quantitative", ["BALYASNY"]),

    # Hedge fund / activist
    ("Bridgewater Associates", "hedge_fund", ["BRIDGEWATER"]),
    ("Elliott Investment Management", "activist", ["ELLIOTT INVESTMENT", "ELLIOTT MANAGEMENT"]),
    ("Icahn Capital", "activist", ["ICAHN"]),
    ("Third Point", "activist", ["THIRD POINT"]),
    ("Pershing Square", "activist", ["PERSHING SQUARE"]),
    ("ValueAct Capital", "activist", ["VALUEACT"]),
    ("Jana Partners", "activist", ["JANA PARTNERS"]),
    ("Starboard Value", "activist", ["STARBOARD"]),
    ("Engine No. 1", "activist", ["ENGINE NO"]),
    ("Corvex Management", "activist", ["CORVEX"]),

    # --- Extended seeds (Tier 2) ---
    # Active
    ("Janus Henderson", "active", ["JANUS HENDERSON", "JANUS CAPITAL"]),
    ("Columbia Threadneedle", "active", ["COLUMBIA THREADNEEDLE", "COLUMBIA MANAGEMENT"]),
    ("Hartford Funds", "active", ["HARTFORD"]),
    ("Principal Financial", "active", ["PRINCIPAL FINANCIAL", "PRINCIPAL GLOBAL"]),
    ("Neuberger Berman", "active", ["NEUBERGER BERMAN"]),
    ("Lord Abbett", "active", ["LORD ABBETT"]),
    ("AllianceBernstein", "active", ["ALLIANCEBERNSTEIN", "AB FUNDS", "SANFORD BERNSTEIN"]),
    ("Lazard Asset Management", "active", ["LAZARD"]),
    ("Artisan Partners", "active", ["ARTISAN"]),
    ("Brown Advisory", "active", ["BROWN ADVISORY"]),
    ("Wasatch Global", "active", ["WASATCH"]),
    ("Parnassus Investments", "active", ["PARNASSUS"]),
    ("Calamos Investments", "active", ["CALAMOS"]),
    ("Oakmark / Harris", "active", ["OAKMARK", "HARRIS ASSOCIATES"]),
    ("Royce Investment Partners", "active", ["ROYCE"]),
    ("Sands Capital", "active", ["SANDS CAPITAL"]),
    ("Fred Alger", "active", ["FRED ALGER", "ALGER"]),
    ("Loomis Sayles", "active", ["LOOMIS SAYLES"]),
    ("Victory Capital", "active", ["VICTORY CAPITAL"]),
    ("Ariel Investments", "active", ["ARIEL INVESTMENTS"]),
    ("Harding Loevner", "active", ["HARDING LOEVNER"]),
    ("William Blair", "active", ["WILLIAM BLAIR"]),
    ("Baird", "active", ["BAIRD"]),
    ("Harbor Capital", "active", ["HARBOR CAPITAL"]),
    ("Calvert Research", "active", ["CALVERT"]),
    ("Carillon Tower", "active", ["CARILLON"]),
    ("PGIM", "active", ["PGIM", "PRUDENTIAL FINANCIAL"]),

    # Mixed / Banks
    ("Bank of America / Merrill", "mixed", ["BANK OF AMERICA", "MERRILL LYNCH"]),
    ("Wells Fargo", "mixed", ["WELLS FARGO"]),
    ("Citigroup", "mixed", ["CITIGROUP", "CITIBANK"]),
    ("HSBC", "mixed", ["HSBC"]),
    ("Barclays", "mixed", ["BARCLAYS"]),
    ("Credit Suisse", "mixed", ["CREDIT SUISSE"]),
    ("BMO Financial", "mixed", ["BMO FINANCIAL", "BMO CAPITAL"]),
    ("RBC Global", "mixed", ["RBC ", "ROYAL BANK OF CANADA"]),
    ("TD Asset Management", "mixed", ["TD ASSET", "TD SECURITIES"]),
    ("Nomura", "mixed", ["NOMURA"]),
    ("Susquehanna", "mixed", ["SUSQUEHANNA"]),

    # Passive / Index
    ("Geode Capital Management", "passive", ["GEODE CAPITAL"]),
    ("Parametric Portfolio", "passive", ["PARAMETRIC"]),
    ("Norges Bank", "passive", ["NORGES BANK"]),

    # Hedge fund
    ("Soros Fund Management", "hedge_fund", ["SOROS"]),
    ("Appaloosa Management", "hedge_fund", ["APPALOOSA"]),
    ("Lone Pine Capital", "hedge_fund", ["LONE PINE"]),
    ("Viking Global", "hedge_fund", ["VIKING GLOBAL"]),
    ("Tiger Global", "hedge_fund", ["TIGER GLOBAL"]),
    ("Coatue Management", "hedge_fund", ["COATUE"]),
    ("Dragoneer Investment", "hedge_fund", ["DRAGONEER"]),
    ("Baupost Group", "hedge_fund", ["BAUPOST"]),
    ("Greenlight Capital", "hedge_fund", ["GREENLIGHT"]),
    ("Tudor Investment", "hedge_fund", ["TUDOR"]),
    ("Och-Ziff / Sculptor", "hedge_fund", ["OCH-ZIFF", "SCULPTOR"]),
    ("Marshall Wace", "hedge_fund", ["MARSHALL WACE"]),
    ("Farallon Capital", "hedge_fund", ["FARALLON"]),
    ("Maverick Capital", "hedge_fund", ["MAVERICK CAPITAL"]),
    ("Anchorage Capital", "hedge_fund", ["ANCHORAGE"]),

    # Activist (additional)
    ("Trian Fund Management", "activist", ["TRIAN"]),
    ("Sachem Head", "activist", ["SACHEM HEAD"]),
    ("Cevian Capital", "activist", ["CEVIAN"]),
    ("Land & Buildings", "activist", ["LAND & BUILDINGS"]),
]


# ---------------------------------------------------------------------------
# Fail-fast input guards
# ---------------------------------------------------------------------------
_REQUIRED_INPUTS = [
    ("filings_deduped", "load_13f.py"),
    ("adv_managers", "pipeline/load_adv.py"),
]


def _assert_inputs_present(con):
    """Raise with an actionable message if a required input table is
    missing or empty. Prevents the downstream SELECT from emitting an
    opaque duckdb Catalog/Binder error mid-run."""
    for tbl, producer in _REQUIRED_INPUTS:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception as e:
            raise RuntimeError(
                f"build_managers: required input `{tbl}` is missing "
                f"(produced by {producer}). {e}"
            ) from e
        if n == 0:
            raise RuntimeError(
                f"build_managers: required input `{tbl}` is empty "
                f"(run {producer} first)."
            )


def build_parent_bridge(con, dry_run=False):
    """Build parent_bridge table mapping CIK to parent group."""
    print("Building parent_bridge table...", flush=True)

    # Get all unique filers from 13F data
    filers = con.execute("""
        SELECT DISTINCT cik, manager_name, crd_number
        FROM filings_deduped
        WHERE manager_name IS NOT NULL
    """).fetchdf()
    print(f"  Unique filers: {len(filers):,}")

    # Build parent assignments
    records = []
    matched_ciks = set()

    for parent_name, strategy_type, variants in PARENT_SEEDS:
        for _, row in filers.iterrows():
            name_upper = str(row["manager_name"]).upper()
            cik = row["cik"]
            if cik in matched_ciks:
                continue
            for variant in variants:
                if variant in name_upper:
                    records.append({
                        "cik": cik,
                        "manager_name": row["manager_name"],
                        "crd_number": row["crd_number"],
                        "parent_name": parent_name,
                        "strategy_type": strategy_type,
                        "is_activist": strategy_type == "activist",
                        "manually_verified": True,
                    })
                    matched_ciks.add(cik)
                    break

    df_bridge = pd.DataFrame(records)
    print(f"  Matched to parent groups: {len(df_bridge):,} CIKs")

    # Show match counts per parent
    if len(df_bridge) > 0:
        parent_counts = df_bridge.groupby("parent_name").size().sort_values(ascending=False)
        print("\n  Top parent matches:")
        for p, c in parent_counts.head(15).items():
            print(f"    {p}: {c} CIKs")

    # For unmatched filers, assign unknown parent
    unmatched = filers[~filers["cik"].isin(matched_ciks)]
    print(f"\n  Unmatched filers: {len(unmatched):,}")

    # Try address-based clustering for unmatched (simplified: just mark as unaffiliated)
    for _, row in unmatched.iterrows():
        records.append({
            "cik": row["cik"],
            "manager_name": row["manager_name"],
            "crd_number": row["crd_number"],
            "parent_name": row["manager_name"],  # Self as parent
            "strategy_type": "unknown",
            "is_activist": False,
            "manually_verified": False,
        })

    df_bridge_full = pd.DataFrame(records)
    # Dedupe on cik: the unmatched loop iterates `SELECT DISTINCT cik,
    # manager_name, crd_number FROM filings_deduped` which fans out when
    # a CIK has multiple (name, crd) variants across quarters. Keep the
    # first occurrence so cik stays empirically unique and the pk_diff
    # promote path is sound (see REWRITE_BUILD_MANAGERS_FINDINGS.md §2.3
    # — this was the 870-dupe pattern surfaced in Phase 2 validation).
    df_bridge_full = df_bridge_full.drop_duplicates(subset=["cik"], keep="first")

    if dry_run:
        print(
            f"\n  [dry-run] would DROP+CREATE parent_bridge "
            f"({len(df_bridge_full):,} rows)",
            flush=True,
        )
        return len(df_bridge_full)

    con.execute("DROP TABLE IF EXISTS parent_bridge")
    con.execute("CREATE TABLE parent_bridge AS SELECT * FROM df_bridge_full")
    count = con.execute("SELECT COUNT(*) FROM parent_bridge").fetchone()[0]
    print(f"\n  parent_bridge table: {count:,} rows", flush=True)
    try:
        record_freshness(con, "parent_bridge")
    except Exception as e:
        print(f"  [warn] record_freshness(parent_bridge) failed: {e}", flush=True)
    return count


def link_cik_to_crd(con, dry_run=False):
    """Fuzzy match CIK from 13F data to CRD from ADV data."""
    print("\nLinking CIK to CRD via fuzzy name match...", flush=True)

    # Get 13F filers without CRD
    filers_no_crd = con.execute("""
        SELECT DISTINCT cik, manager_name
        FROM filings_deduped
        WHERE (crd_number IS NULL OR crd_number = '')
          AND manager_name IS NOT NULL
    """).fetchdf()
    print(f"  Filers without CRD: {len(filers_no_crd):,}")

    # Get ADV firms. city + state added for INF17 Phase 3 city/state gate.
    adv = con.execute("""
        SELECT crd_number, firm_name, cik as adv_cik, city, state
        FROM adv_managers
        WHERE firm_name IS NOT NULL
    """).fetchdf()
    print(f"  ADV firms to match against: {len(adv):,}")

    # First, try direct CIK match (ADV has CIK field)
    adv_cik_map = {}
    for _, row in adv.iterrows():
        if pd.notna(row["adv_cik"]) and str(row["adv_cik"]).strip():
            padded = str(row["adv_cik"]).strip().zfill(10)
            adv_cik_map[padded] = row["crd_number"]

    direct_matches = 0
    for _, row in filers_no_crd.iterrows():
        if row["cik"] in adv_cik_map:
            direct_matches += 1
    print(f"  Direct CIK matches: {direct_matches}")

    # Build name lookup for fuzzy matching. adv_by_name carries crd, city, state
    # per firm_name so the INF17 Phase 3 gates can cross-check location.
    adv_names = adv["firm_name"].tolist()
    adv_by_name = {
        r["firm_name"]: {
            "crd": r["crd_number"],
            "city": r["city"],
            "state": r["state"],
        }
        for _, r in adv.iterrows()
    }

    # Fuzzy match remaining
    fuzzy_matches = []
    threshold = 85
    filers_list = filers_no_crd[~filers_no_crd["cik"].isin(adv_cik_map)].to_dict("records")

    # INF17 Phase 3: every candidate that clears the rapidfuzz score cutoff
    # but fails a secondary gate is recorded to an audit CSV so the heuristic
    # can be tuned later from real data.
    rejections_path = os.path.join(BASE_DIR, "logs", "build_managers_rejected_crds.csv")
    os.makedirs(os.path.dirname(rejections_path), exist_ok=True)
    rejected_count = 0
    with open(rejections_path, "w", encoding="utf-8", newline="") as rej_file:
        rej_writer = csv.writer(rej_file)
        rej_writer.writerow(
            ["manager_cik", "manager_name", "candidate_crd", "candidate_firm", "score", "reason"]
        )

        print(
            f"  Fuzzy matching {len(filers_list):,} filers "
            f"(threshold={threshold}, brand-token gate on, city/state gate on)..."
        )
        for i, row in enumerate(filers_list):
            name = str(row["manager_name"])
            result = process.extractOne(
                name, adv_names,
                scorer=fuzz.token_sort_ratio, score_cutoff=threshold,
            )
            if result:
                matched_name, score, _ = result
                adv_row = adv_by_name[matched_name]
                crd = adv_row["crd"]

                # Gate (a) INF17 Phase 3: brand-token overlap required.
                if not _brand_tokens_overlap(name, matched_name):
                    rej_writer.writerow(
                        [row["cik"], name, crd, matched_name, score, "brand_token_mismatch"]
                    )
                    rejected_count += 1
                # Gate (b) INF17 Phase 3: city+state compatibility. Short-circuits
                # to accept when filer side lacks city/state (current pipeline
                # state — filings_deduped has no location columns).
                elif not _city_state_compatible(
                    row.get("city"), row.get("state"),
                    adv_row.get("city"), adv_row.get("state"),
                ):
                    rej_writer.writerow(
                        [row["cik"], name, crd, matched_name, score, "city_state_mismatch"]
                    )
                    rejected_count += 1
                else:
                    fuzzy_matches.append({
                        "cik": row["cik"],
                        "crd_number": crd,
                        "filing_name": name,
                        "adv_name": matched_name,
                        "match_score": score,
                    })
            if (i + 1) % 1000 == 0:
                print(
                    f"    Processed {i + 1:,} / {len(filers_list):,} "
                    f"({len(fuzzy_matches):,} kept, {rejected_count:,} rejected)",
                    flush=True,
                )

    print(
        f"  Fuzzy matches found: {len(fuzzy_matches):,}  "
        f"(rejected: {rejected_count:,})",
        flush=True,
    )
    print(f"  Rejection log: {rejections_path}", flush=True)

    # Build the direct-match frame outside the dry-run branch so row
    # counts are comparable.
    direct_records = [
        {"cik": cik, "crd_number": crd, "match_type": "direct_cik"}
        for cik, crd in adv_cik_map.items()
    ]

    if dry_run:
        print(
            f"  [dry-run] would DROP+CREATE cik_crd_links "
            f"({len(fuzzy_matches):,} rows)",
            flush=True,
        )
        print(
            f"  [dry-run] would DROP+CREATE cik_crd_direct "
            f"({len(direct_records):,} rows)",
            flush=True,
        )
        total_linked = direct_matches + len(fuzzy_matches)
        print(f"  Total CIK-CRD links (projected): {total_linked:,}", flush=True)
        return total_linked

    # Save link table
    if fuzzy_matches:
        df_links = pd.DataFrame(fuzzy_matches)
        con.execute("DROP TABLE IF EXISTS cik_crd_links")
        con.execute("CREATE TABLE cik_crd_links AS SELECT * FROM df_links")
        try:
            record_freshness(con, "cik_crd_links")
        except Exception as e:
            print(f"  [warn] record_freshness(cik_crd_links) failed: {e}", flush=True)

    # Also save direct CIK-CRD matches
    if direct_records:
        df_direct = pd.DataFrame(direct_records)
        con.execute("DROP TABLE IF EXISTS cik_crd_direct")
        con.execute("CREATE TABLE cik_crd_direct AS SELECT * FROM df_direct")
        try:
            record_freshness(con, "cik_crd_direct")
        except Exception as e:
            print(f"  [warn] record_freshness(cik_crd_direct) failed: {e}", flush=True)

    total_linked = direct_matches + len(fuzzy_matches)
    print(f"  Total CIK-CRD links: {total_linked:,}", flush=True)
    return total_linked


def build_managers_table(con, dry_run=False):
    """Build the managers table joining 13F, ADV, and parent_bridge."""
    print("\nBuilding managers table...", flush=True)

    if dry_run:
        # Project via a CTE that mirrors the CREATE TABLE body — cheaper
        # than staging the full CTAS, and avoids requiring parent_bridge
        # to have been materialized in dry-run mode (it hasn't — its
        # builder also short-circuited).
        projected = con.execute("""
            SELECT COUNT(*) FROM (
                SELECT f.cik
                FROM (
                    SELECT cik FROM filings_deduped GROUP BY cik
                ) f
            )
        """).fetchone()[0]
        print(
            f"  [dry-run] would DROP+CREATE managers "
            f"(~{projected:,} rows, ±LEFT-JOIN fan-out)",
            flush=True,
        )
        return projected

    con.execute("DROP TABLE IF EXISTS managers")
    con.execute("""
        CREATE TABLE managers AS
        SELECT
            f.cik,
            f.manager_name,
            COALESCE(f.crd_number, d.crd_number, l.crd_number) as crd_number,
            p.parent_name,
            COALESCE(
                CASE WHEN p.strategy_type != 'unknown' THEN p.strategy_type END,
                a.strategy_inferred,
                -- Keyword-based fallback classification
                CASE
                    WHEN UPPER(f.manager_name) LIKE '%INDEX%'
                      OR UPPER(f.manager_name) LIKE '%ETF%'
                      OR UPPER(f.manager_name) LIKE '%SPDR%'
                      OR UPPER(f.manager_name) LIKE '%PASSIVE%'
                      THEN 'passive'
                    WHEN UPPER(f.manager_name) LIKE '%HEDGE%'
                      OR UPPER(f.manager_name) LIKE '%CAPITAL PARTNERS%'
                      OR UPPER(f.manager_name) LIKE '%MASTER FUND%'
                      OR UPPER(f.manager_name) LIKE '%OFFSHORE%'
                      THEN 'hedge_fund'
                    WHEN UPPER(f.manager_name) LIKE '%PRIVATE EQUITY%'
                      OR UPPER(f.manager_name) LIKE '%BUYOUT%'
                      OR UPPER(f.manager_name) LIKE '%VENTURE CAPITAL%'
                      OR UPPER(f.manager_name) LIKE '%VENTURES%'
                      THEN 'private_equity'
                    WHEN UPPER(f.manager_name) LIKE '%BANK%'
                      OR UPPER(f.manager_name) LIKE '%TRUST CO%'
                      OR UPPER(f.manager_name) LIKE '%WEALTH MANAGEMENT%'
                      OR UPPER(f.manager_name) LIKE '%FINANCIAL GROUP%'
                      THEN 'mixed'
                    WHEN UPPER(f.manager_name) LIKE '%QUANT%'
                      OR UPPER(f.manager_name) LIKE '%ALGORITHMIC%'
                      OR UPPER(f.manager_name) LIKE '%SYSTEMATIC%'
                      THEN 'quantitative'
                    WHEN UPPER(f.manager_name) LIKE '%ADVISORS%'
                      OR UPPER(f.manager_name) LIKE '%ADVISERS%'
                      OR UPPER(f.manager_name) LIKE '%ASSET MANAGEMENT%'
                      OR UPPER(f.manager_name) LIKE '%INVESTMENT MANAGEMENT%'
                      OR UPPER(f.manager_name) LIKE '%CAPITAL MANAGEMENT%'
                      THEN 'active'
                    ELSE NULL
                END
            ) as strategy_type,
            COALESCE(p.is_activist, a.is_activist, false) as is_activist,
            CASE
                WHEN COALESCE(
                    CASE WHEN p.strategy_type != 'unknown' THEN p.strategy_type END,
                    a.strategy_inferred
                ) = 'passive'
                OR UPPER(f.manager_name) LIKE '%INDEX%'
                OR UPPER(f.manager_name) LIKE '%ETF%'
                OR UPPER(f.manager_name) LIKE '%SPDR%'
                THEN true
                ELSE false
            END as is_passive,
            a.adv_5f_raum as aum_total,
            a.adv_5f_raum_discrtnry as aum_discretionary,
            a.pct_discretionary,
            a.city as adv_city,
            a.state as adv_state,
            p.manually_verified,
            f.num_filings,
            f.total_positions
        FROM (
            SELECT
                cik,
                MAX(manager_name) as manager_name,
                MAX(crd_number) as crd_number,
                COUNT(DISTINCT quarter) as num_filings,
                COUNT(*) as total_positions
            FROM filings_deduped
            GROUP BY cik
        ) f
        LEFT JOIN parent_bridge p ON f.cik = p.cik
        LEFT JOIN cik_crd_direct d ON f.cik = d.cik
        LEFT JOIN (
            SELECT cik, crd_number FROM cik_crd_links
            WHERE match_score >= 85
            QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY match_score DESC) = 1
        ) l ON f.cik = l.cik
        LEFT JOIN adv_managers a ON COALESCE(f.crd_number, d.crd_number, l.crd_number) = a.crd_number
    """)

    count = con.execute("SELECT COUNT(*) FROM managers").fetchone()[0]
    print(f"  managers table: {count:,} rows", flush=True)
    try:
        record_freshness(con, "managers")
    except Exception as e:
        print(f"  [warn] record_freshness(managers) failed: {e}", flush=True)
    return count


def enrich_holdings_v2(con, dry_run=False):
    """Update holdings_v2 with manager metadata. Repointed from the
    dropped legacy `holdings` table per the REWRITE findings — see
    docs/REWRITE_BUILD_MANAGERS_FINDINGS.md §4. holdings_v2 already has
    inst_parent_name/manager_type/is_passive/is_activist with the
    correct types (VARCHAR/VARCHAR/BOOLEAN/BOOLEAN), so the historical
    ALTER-to-fix-types block is retired.

    All four columns are updated via COALESCE(m.<src>, h.<dst>) per
    Risk 1 resolution (Phase 2 report, Pre-Phase-4 investigation).
    manager_type is the load-bearing case: 4,163 CIKs / 5.33M rows
    have legacy values from backfill_manager_types.py + the
    categorized_institutions_funds_v2.csv curation (commit 87e832b),
    for filer types ADV does not cover (strategic holders like
    Berkshire, SWFs, pension plans, endowments, wealth-management
    broker-dealers, foreign market makers). Straight UPDATE would
    overwrite those with NULL from managers.strategy_type (only 52%
    populated today). COALESCE preserves the curation for legacy-only
    CIKs and refreshes every row where the current build has an
    opinion. inst_parent_name / is_passive / is_activist have
    effectively zero legacy-only exposure (0 to 3 CIKs) but COALESCE
    is applied uniformly as defense against any future managers-side
    NULL regression.

    Split out of build_managers_table() so --enrichment-only can invoke
    it in isolation — see Option A flag matrix in the REWRITE findings.
    """
    print("\nUpdating holdings_v2 with manager metadata...", flush=True)

    if dry_run:
        projected = con.execute("""
            SELECT COUNT(*) FROM holdings_v2 h
            JOIN managers m ON h.cik = m.cik
        """).fetchone()[0]
        print(
            f"  [dry-run] would UPDATE ~{projected:,} rows in holdings_v2 "
            f"(join managers on cik, preserving legacy via COALESCE)",
            flush=True,
        )
        return projected

    con.execute("""
        UPDATE holdings_v2 h
        SET
            inst_parent_name = COALESCE(m.parent_name,    h.inst_parent_name),
            manager_type     = COALESCE(m.strategy_type, h.manager_type),
            is_passive       = COALESCE(m.is_passive,    h.is_passive),
            is_activist      = COALESCE(m.is_activist,   h.is_activist)
        FROM managers m
        WHERE h.cik = m.cik
    """)
    updated = con.execute("""
        SELECT COUNT(*) FROM holdings_v2 WHERE manager_type IS NOT NULL
    """).fetchone()[0]
    print(f"  holdings_v2 updated with manager data: {updated:,}", flush=True)
    try:
        record_freshness(con, "holdings_v2")
    except Exception as e:
        print(f"  [warn] record_freshness(holdings_v2) failed: {e}", flush=True)
    return updated


def print_summary(con):
    """Print summary statistics."""
    print("\n--- Manager Summary ---")

    print("\nBy strategy_type:")
    strat = con.execute("""
        SELECT strategy_type, COUNT(*) as cnt,
               SUM(aum_total) / 1e12 as total_aum_tn
        FROM managers
        WHERE strategy_type IS NOT NULL
        GROUP BY strategy_type
        ORDER BY cnt DESC
    """).fetchdf()
    print(strat.to_string(index=False))

    print("\nActivist managers in database:")
    activists = con.execute("""
        SELECT m.cik, m.manager_name, m.parent_name, m.strategy_type,
               m.aum_total / 1e9 as aum_bn
        FROM managers m
        WHERE m.is_activist = true
        ORDER BY m.aum_total DESC NULLS LAST
    """).fetchdf()
    print(activists.to_string(index=False))

    print("\nTop 15 parents by AUM:")
    parents = con.execute("""
        SELECT parent_name, strategy_type, COUNT(*) as subsidiaries,
               SUM(aum_total) / 1e12 as total_aum_tn
        FROM managers
        WHERE parent_name IS NOT NULL AND manually_verified = true
        GROUP BY parent_name, strategy_type
        ORDER BY total_aum_tn DESC NULLS LAST
        LIMIT 15
    """).fetchdf()
    print(parents.to_string(index=False))


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--staging", action="store_true",
        help="write to the staging DB (13f_staging.duckdb) instead of prod",
    )
    p.add_argument(
        "--test", action="store_true",
        help="write to the test DB (13f_test.duckdb)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="no DB writes; print projected row counts for each target",
    )
    p.add_argument(
        "--enrichment-only", action="store_true",
        help=(
            "skip the four CTAS builds (parent_bridge, cik_crd_links, "
            "cik_crd_direct, managers) and only UPDATE holdings_v2 from "
            "the existing managers table. Used in the Phase 4 three-step "
            "flow to apply enrichment to prod after staging→prod promote."
        ),
    )
    return p.parse_args()


def main():
    # No-flag default runs two architecturally-different operations in
    # sequence against prod:
    #   (1) rebuild four canonical tables: parent_bridge, cik_crd_links,
    #       cik_crd_direct, managers (DROP+CTAS each)
    #   (2) UPDATE holdings_v2 with per-manager metadata from (1)
    # Operation (1) is normally routed through staging (build with
    # --staging then promote via promote_staging.py). Operation (2) is
    # direct-write to prod because holdings_v2 is too large to route
    # through snapshot/diff promotion — same pattern as
    # enrich_holdings.py. The no-flag path is preserved for
    # backward compatibility with existing scheduler / Makefile / cron
    # invocations; new operators should prefer the three-step
    # --staging flow documented in REWRITE_BUILD_MANAGERS_FINDINGS.md.
    args = _parse_args()

    if args.test:
        db.set_test_mode(True)
    if args.staging:
        db.set_staging_mode(True)

    mode_tags = []
    if args.test: mode_tags.append("TEST")
    if args.staging: mode_tags.append("STAGING")
    if args.dry_run: mode_tags.append("DRY-RUN")
    if args.enrichment_only: mode_tags.append("ENRICHMENT-ONLY")
    mode_str = " ".join(mode_tags) if mode_tags else "PROD"

    print("=" * 60, flush=True)
    print(f"SCRIPT 2 — build_managers.py  [{mode_str}]", flush=True)
    print("=" * 60, flush=True)
    print(f"  DB: {db.get_db_path()}", flush=True)

    if args.staging:
        db.seed_staging()

    con = db.connect_write()
    db.assert_write_safe(con)

    _assert_inputs_present(con)

    if not args.enrichment_only:
        # Step 1: Build parent_bridge
        build_parent_bridge(con, dry_run=args.dry_run)

        # Step 2: Link CIK to CRD
        link_cik_to_crd(con, dry_run=args.dry_run)

        # Step 3: Build managers table
        build_managers_table(con, dry_run=args.dry_run)

    # Step 4: Enrich holdings_v2 (always runs unless explicitly skipped
    # in a future flag — --enrichment-only still runs this step, it just
    # skips the preceding three).
    enrich_holdings_v2(con, dry_run=args.dry_run)

    # Step 5: Summary (only after a real build — summary queries rely on
    # the managers table having the expected shape)
    if not args.dry_run and not args.enrichment_only:
        print_summary(con)

    if not args.dry_run:
        try:
            con.execute("CHECKPOINT")
        except Exception as e:
            print(f"  [warn] CHECKPOINT failed: {e}", flush=True)
    con.close()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
