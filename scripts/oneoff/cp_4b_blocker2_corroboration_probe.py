"""CP-4b BLOCKER 2 corroboration probe — read-only.

For each of the 19 LOW brands in data/working/cp-4b-discovery-manifest.csv, run
four orthogonal corroboration probes:

  X1 — normalized name equality (canonical_name vs visible filer
       canonical_name + manager_name, with corporate suffixes stripped).
  X2 — entity_aliases cross-link (brand alias matches filer alias on a
       different visible eid).
  X3 — shared CIK across identifier_types (open-rows; identical to
       discovery Step 2a — confirms zero new hits).
  X4 — N-CEN cross-link (4a CRD, 4b name, 4c multi-adviser registrant).

Outputs:

  - data/working/cp-4b-corroboration-matrix.csv (19 rows × signal cols).
  - stdout summary: cohort drift, per-brand state snapshot, per-brand
    signal hits, bucket counts, public-record sanity check.

Refs docs/decisions/inst_eid_bridge_decisions.md (BLOCKER 2),
docs/findings/cp-4b-discovery.md.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
# DB lives at the main repo data/ dir; worktrees do not duplicate the file.
DB_PATH = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
MANIFEST_IN = REPO_ROOT / "data" / "working" / "cp-4b-discovery-manifest.csv"
MATRIX_OUT = REPO_ROOT / "data" / "working" / "cp-4b-corroboration-matrix.csv"

SENTINEL = "DATE '9999-12-31'"
TROWE_PARENT_EID = 3616
TROWE_CHILD_EID = 17924
EXPECTED_LOW_AUM_BILLIONS = 11_435.5
LOW_AUM_TOLERANCE = 0.05  # 5%


# X1 normalization — applied to both brand and filer names.
# Suffixes are stripped iteratively (longest first to avoid prefix chops).
_SUFFIXES = [
    "ASSET MANAGEMENT", "INVESTMENT MANAGEMENT", "INVESTMENT MANAGERS",
    "INVESTMENT ADVISERS", "INVESTMENT ADVISORS", "ADVISORY SERVICES",
    "FUND MANAGEMENT", "GLOBAL ADVISORS",
    "ADVISERS", "ADVISORS", "ADVISER", "ADVISOR", "ADVISORY",
    "MANAGEMENT", "FINANCIAL", "CAPITAL", "HOLDINGS", "GROUP",
    "L.L.C.", "LLC", "L.L.P.", "LLP", "L.P.", "LP",
    "LIMITED", "LTD.", "LTD",
    "INC.", "INC", "CORP.", "CORP", "CORPORATION", "COMPANY",
    "CO.", "CO",
    "PLC",
    "FUNDS", "FUND",
    "/DE/", "/MD/", "/FI/", "/FA/", "/CA/", "/NY/", "/MA/", "/DE\\",
]
_PUNCT_RE = re.compile(r"[^\w\s/]+")
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Iteratively strip corporate suffixes and punctuation; uppercase."""
    if not raw:
        return ""
    s = raw.upper().strip()
    s = _PUNCT_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()

    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if s.endswith(" " + suf):
                s = s[: -len(suf) - 1].strip()
                changed = True
                break
            if s == suf:
                s = ""
                changed = True
                break
        # also strip standalone trailing tokens (",")
        s = s.rstrip(", ").strip()
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def crd_variants(raw: str) -> list[str]:
    s = str(raw).strip()
    if not s:
        return []
    s = s.lstrip("0") or "0"
    return list({s, s.zfill(7), s.zfill(9)})


def cik_padded(raw: str) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.zfill(10)


def load_low_rows() -> list[dict]:
    rows: list[dict] = []
    with MANIFEST_IN.open() as f:
        for r in csv.DictReader(f):
            if r["confidence"] == "LOW":
                rows.append(r)
    return rows


def load_visible_filers(con) -> dict[int, dict]:
    """Visible 13F filers: entity_id with ≥100 holdings_v2 rows.

    Returns {eid: {canonical_name, primary_manager_name, n_rows, cik}}.
    """
    df = con.execute(f"""
        WITH counts AS (
          SELECT entity_id, COUNT(*) AS n
          FROM holdings_v2
          WHERE is_latest = TRUE AND entity_id IS NOT NULL
          GROUP BY entity_id
          HAVING COUNT(*) >= 100
        )
        SELECT c.entity_id,
               e.canonical_name,
               (SELECT manager_name FROM holdings_v2 h
                WHERE h.entity_id = c.entity_id AND h.is_latest = TRUE
                LIMIT 1) AS manager_name,
               (SELECT identifier_value FROM entity_identifiers ei
                WHERE ei.entity_id = c.entity_id AND ei.identifier_type='cik'
                  AND ei.valid_to = {SENTINEL}
                LIMIT 1) AS cik,
               c.n
        FROM counts c
        LEFT JOIN entities e USING (entity_id)
    """).fetchdf()
    out = {}
    for _, r in df.iterrows():
        eid = int(r["entity_id"])
        out[eid] = {
            "canonical_name": r["canonical_name"] or "",
            "manager_name": r["manager_name"] or "",
            "cik": r["cik"],
            "n_rows": int(r["n"]),
        }
    return out


def brand_state_snapshot(con, eid: int) -> dict:
    e = con.execute(
        "SELECT canonical_name, entity_type FROM entities WHERE entity_id=?",
        [eid],
    ).fetchone()
    ids = con.execute(f"""
        SELECT identifier_type, identifier_value
        FROM entity_identifiers
        WHERE entity_id=? AND valid_to={SENTINEL}
        ORDER BY identifier_type, identifier_value
    """, [eid]).fetchall()
    aliases = con.execute(f"""
        SELECT alias_name, is_preferred
        FROM entity_aliases
        WHERE entity_id=? AND valid_to={SENTINEL}
        ORDER BY is_preferred DESC, alias_name
    """, [eid]).fetchall()
    rels_out = con.execute(f"""
        SELECT relationship_id, child_entity_id, relationship_type, source
        FROM entity_relationships
        WHERE parent_entity_id=? AND valid_to={SENTINEL}
    """, [eid]).fetchall()
    rels_in = con.execute(f"""
        SELECT relationship_id, parent_entity_id, relationship_type, source
        FROM entity_relationships
        WHERE child_entity_id=? AND valid_to={SENTINEL}
    """, [eid]).fetchall()
    dm = con.execute("""
        SELECT COUNT(*) AS n, COALESCE(SUM(market_value_usd), 0) AS mv
        FROM holdings_v2
        WHERE is_latest = TRUE
          AND (rollup_entity_id = ? OR dm_rollup_entity_id = ?)
    """, [eid, eid]).fetchone()
    return {
        "canonical_name": e[0] if e else None,
        "entity_type": e[1] if e else None,
        "identifiers": ids,
        "aliases": aliases,
        "rels_out": rels_out,
        "rels_in": rels_in,
        "dm_rollup_n": int(dm[0]) if dm else 0,
        "dm_rollup_mv": float(dm[1]) if dm else 0.0,
    }


def confirm_trowe(con) -> bool:
    n = con.execute(f"""
        SELECT COUNT(*) FROM entity_relationships
        WHERE parent_entity_id=? AND child_entity_id=? AND valid_to={SENTINEL}
    """, [TROWE_PARENT_EID, TROWE_CHILD_EID]).fetchone()[0]
    return n == 1


# =============================================================================
# Probes
# =============================================================================


def probe_x1_name_equality(
    brand_eid: int, brand_canonical: str, visible: dict[int, dict],
) -> tuple[bool, list[int], list[str]]:
    """X1: normalized brand canonical_name equals normalized filer canonical
    or manager name. Operates entirely on the pre-loaded visible dict; no DB
    handle needed."""
    bn = normalize_name(brand_canonical)
    if not bn:
        return False, [], []
    candidates = []
    evidence = []
    for eid, info in visible.items():
        if eid == brand_eid:
            continue
        for field in ("canonical_name", "manager_name"):
            fn = normalize_name(info.get(field, "") or "")
            if fn and fn == bn:
                candidates.append(eid)
                evidence.append(
                    f"eid={eid} {field}='{info.get(field)}' "
                    f"normalized='{fn}' n_holdings={info['n_rows']}"
                )
                break
    return (len(candidates) > 0), sorted(set(candidates)), evidence


def probe_x2_alias_match(
    con, brand_eid: int, brand_canonical: str, visible: dict[int, dict],
) -> tuple[bool, list[int], list[str]]:
    """X2: brand-side canonical_name OR alias matches filer-side alias on a
    different visible eid (after X1 normalization)."""
    brand_aliases = con.execute(f"""
        SELECT alias_name FROM entity_aliases
        WHERE entity_id=? AND valid_to={SENTINEL}
    """, [brand_eid]).fetchall()
    brand_terms = {normalize_name(brand_canonical)}
    for (a,) in brand_aliases:
        n = normalize_name(a)
        if n:
            brand_terms.add(n)
    brand_terms.discard("")
    if not brand_terms:
        return False, [], []

    # Pull all alias_name rows (open) on different eids; normalize in Python
    # because suffix-stripping isn't doable in SQL portably.
    rows = con.execute(f"""
        SELECT entity_id, alias_name
        FROM entity_aliases
        WHERE valid_to={SENTINEL} AND entity_id != ?
    """, [brand_eid]).fetchall()
    candidates = []
    evidence = []
    seen = set()
    for eid, alias in rows:
        if eid not in visible:
            continue
        n = normalize_name(alias)
        if n and n in brand_terms:
            key = (eid, n)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(eid)
            evidence.append(
                f"eid={eid} alias='{alias}' normalized='{n}' "
                f"n_holdings={visible[eid]['n_rows']}"
            )
    return (len(candidates) > 0), sorted(set(candidates)), evidence


def probe_x3_cik_reuse(
    con, brand_eid: int, brand_cik: str | None, visible: dict[int, dict],
) -> tuple[bool, list[int], list[str]]:
    if not brand_cik:
        return False, [], []
    cik_p = cik_padded(brand_cik)
    cik_u = brand_cik.lstrip("0") or "0"
    rows = con.execute(f"""
        SELECT DISTINCT entity_id
        FROM entity_identifiers
        WHERE identifier_type='cik' AND identifier_value IN (?, ?)
          AND valid_to={SENTINEL} AND entity_id != ?
    """, [cik_p, cik_u, brand_eid]).fetchall()
    candidates = [int(eid) for (eid,) in rows if int(eid) in visible]
    evidence = []
    for eid in candidates:
        info = visible[eid]
        evidence.append(f"eid={eid} canonical='{info['canonical_name']}' shares CIK {brand_cik}")
    return (len(candidates) > 0), sorted(set(candidates)), evidence


def probe_x4_ncen_crosslink(
    con, brand_eid: int, brand_canonical: str, visible: dict[int, dict],
) -> tuple[bool, list[int], list[str], list[str]]:
    """X4: three sub-probes through ncen_adviser_map.

    4a: brand CRD as adviser_crd → registrant_cik → entity_identifiers → eid.
    4b: brand canonical_name (X1-normalized) matches adviser_name (normalized).
    4c: brand CRD AND registrant_cik has multiple distinct adviser_crd values
        (multi-adviser fund-issuer registrant).
    """
    crd_rows = con.execute(f"""
        SELECT identifier_value FROM entity_identifiers
        WHERE entity_id=? AND identifier_type='crd' AND valid_to={SENTINEL}
    """, [brand_eid]).fetchall()
    crds = []
    for (c,) in crd_rows:
        crds.extend(crd_variants(c))
    crds = list(set(crds))

    fired_subprobes: list[str] = []
    candidates: list[int] = []
    evidence: list[str] = []

    # ---- 4a: CRD chain via N-CEN ----
    if crds:
        ph = ",".join(["?"] * len(crds))
        nrows = con.execute(f"""
            SELECT DISTINCT registrant_cik, registrant_name
            FROM ncen_adviser_map
            WHERE adviser_crd IN ({ph}) AND valid_to={SENTINEL}
              AND registrant_cik IS NOT NULL
        """, crds).fetchall()
        for rcik, rname in nrows:
            rcik_p = cik_padded(rcik)
            if not rcik_p:
                continue
            erows = con.execute(f"""
                SELECT DISTINCT entity_id FROM entity_identifiers
                WHERE identifier_type='cik' AND identifier_value=?
                  AND valid_to={SENTINEL} AND entity_id != ?
            """, [rcik_p, brand_eid]).fetchall()
            for (eid,) in erows:
                eid = int(eid)
                if eid in visible:
                    if "4a" not in fired_subprobes:
                        fired_subprobes.append("4a")
                    candidates.append(eid)
                    evidence.append(
                        f"4a: brand CRD -> N-CEN registrant_cik={rcik} "
                        f"({rname}) -> visible eid={eid}"
                    )

    # ---- 4b: name match against adviser_name ----
    bn = normalize_name(brand_canonical)
    if bn:
        # Pull all distinct adviser_name + registrant_cik for normalized match
        nrows = con.execute(f"""
            SELECT DISTINCT adviser_name, registrant_cik, registrant_name
            FROM ncen_adviser_map
            WHERE valid_to={SENTINEL} AND adviser_name IS NOT NULL
              AND registrant_cik IS NOT NULL
        """).fetchall()
        for aname, rcik, rname in nrows:
            if normalize_name(aname) != bn:
                continue
            rcik_p = cik_padded(rcik)
            if not rcik_p:
                continue
            erows = con.execute(f"""
                SELECT DISTINCT entity_id FROM entity_identifiers
                WHERE identifier_type='cik' AND identifier_value=?
                  AND valid_to={SENTINEL} AND entity_id != ?
            """, [rcik_p, brand_eid]).fetchall()
            for (eid,) in erows:
                eid = int(eid)
                if eid in visible:
                    if "4b" not in fired_subprobes:
                        fired_subprobes.append("4b")
                    candidates.append(eid)
                    evidence.append(
                        f"4b: brand name matches N-CEN adviser_name='{aname}'"
                        f" -> registrant_cik={rcik} ({rname}) -> visible eid={eid}"
                    )

    # ---- 4c: brand CRD on a multi-adviser registrant ----
    if crds:
        ph = ",".join(["?"] * len(crds))
        rcik_rows = con.execute(f"""
            SELECT DISTINCT registrant_cik
            FROM ncen_adviser_map
            WHERE adviser_crd IN ({ph}) AND valid_to={SENTINEL}
              AND registrant_cik IS NOT NULL
        """, crds).fetchall()
        rciks = [r[0] for r in rcik_rows if r[0]]
        for rc in rciks:
            n_distinct = con.execute(f"""
                SELECT COUNT(DISTINCT adviser_crd)
                FROM ncen_adviser_map
                WHERE registrant_cik=? AND valid_to={SENTINEL}
                  AND adviser_crd IS NOT NULL
            """, [rc]).fetchone()[0]
            if n_distinct and n_distinct >= 2:
                if "4c" not in fired_subprobes:
                    fired_subprobes.append("4c")
                evidence.append(
                    f"4c: registrant_cik={rc} has {n_distinct} distinct"
                    f" adviser_crd values (multi-adviser fund issuer)"
                )

    return (len(fired_subprobes) > 0), sorted(set(candidates)), evidence, fired_subprobes


# =============================================================================
# Synthesis
# =============================================================================


def assign_bucket(
    n_signals: int, candidate_concordance: bool,
) -> str:
    if n_signals >= 3 and candidate_concordance:
        return "A"
    if n_signals == 2 and candidate_concordance:
        return "B"
    if n_signals >= 1:
        return "C"
    return "D"


def main() -> int:
    print("=" * 72)
    print("CP-4b BLOCKER 2 corroboration probe")
    print("=" * 72)

    con = duckdb.connect(str(DB_PATH), read_only=True)

    # ------------------------------------------------------------------
    # Phase 1: re-validate
    # ------------------------------------------------------------------
    low_rows = load_low_rows()
    n_low = len(low_rows)
    sum_aum = sum(float(r["fund_aum_usd_billions"]) for r in low_rows)
    drift_pct = abs(sum_aum - EXPECTED_LOW_AUM_BILLIONS) / EXPECTED_LOW_AUM_BILLIONS

    print(f"\nPHASE 1 — cohort re-validation")
    print(f"  LOW rows loaded:          {n_low}")
    print(f"  expected LOW count:       19")
    print(f"  sum LOW fund AUM ($B):    {sum_aum:,.1f}")
    print(f"  expected sum ($B):        {EXPECTED_LOW_AUM_BILLIONS:,.1f}")
    print(f"  drift from expected:      {drift_pct:.2%}")
    if n_low != 19 or drift_pct > LOW_AUM_TOLERANCE:
        print("  ABORT — drift exceeds tolerance")
        return 1
    print("  ✓ cohort matches discovery")

    # cp-4b-author-trowe confirmation
    trowe_ok = confirm_trowe(con)
    print(
        f"\n  cp-4b-author-trowe bridge "
        f"({TROWE_PARENT_EID}->{TROWE_CHILD_EID}): "
        f"{'✓ present' if trowe_ok else '✗ MISSING'}"
    )
    if not trowe_ok:
        print("  ABORT — PR #267 trowe bridge not found in prod")
        return 1

    # Build visible-filer pool
    visible = load_visible_filers(con)
    print(f"\n  visible 13F filer pool (≥100 rows): {len(visible):,} eids")

    # ------------------------------------------------------------------
    # Phase 2: per-brand probes
    # ------------------------------------------------------------------
    print(f"\nPHASE 2 — per-brand probes")
    matrix = []
    drift_flags = []
    for r in low_rows:
        brand_eid = int(r["brand_eid"])
        brand_canonical = r["brand_canonical_name"]
        brand_cik = r.get("brand_cik") or None
        snap = brand_state_snapshot(con, brand_eid)

        # drift sanity
        if snap["canonical_name"] != brand_canonical:
            drift_flags.append(
                f"  eid={brand_eid}: name drift "
                f"'{brand_canonical}' -> '{snap['canonical_name']}'"
            )

        x1_hit, x1_eids, x1_ev = probe_x1_name_equality(
            brand_eid, brand_canonical, visible
        )
        x2_hit, x2_eids, x2_ev = probe_x2_alias_match(
            con, brand_eid, brand_canonical, visible
        )
        x3_hit, x3_eids, x3_ev = probe_x3_cik_reuse(
            con, brand_eid, brand_cik, visible
        )
        x4_hit, x4_eids, x4_ev, x4_subs = probe_x4_ncen_crosslink(
            con, brand_eid, brand_canonical, visible
        )

        # Per the plan: n_signals_corroborated counts X1-X4 only when they
        # returned ≥1 candidate filer eid. X4 sub-probe 4c flags a fund-
        # issuer pattern but produces no candidate, so 4c-only does NOT
        # count as corroboration (it is recorded as informational).
        firing_sets: list[set[int]] = []
        signal_returned_candidate = []
        for hit, eids in (
            (x1_hit, x1_eids),
            (x2_hit, x2_eids),
            (x3_hit, x3_eids),
            (x4_hit, x4_eids),
        ):
            if hit and eids:
                firing_sets.append(set(eids))
                signal_returned_candidate.append(True)
            else:
                signal_returned_candidate.append(False)
        n_signals = sum(signal_returned_candidate)
        x4_4c_only_flag = (x4_hit and not x4_eids and "4c" in x4_subs)
        if firing_sets:
            concordance_set = set.intersection(*firing_sets)
            concordance = bool(concordance_set)
        else:
            concordance_set = set()
            concordance = (n_signals == 0)  # vacuous concordance for D

        bucket = assign_bucket(n_signals, concordance)

        rec = {
            "rank": int(r["rank"]),
            "brand_eid": brand_eid,
            "brand_canonical_name": brand_canonical,
            "brand_cik": brand_cik or "",
            "fund_aum_billions": float(r["fund_aum_usd_billions"]),
            "supplementary_name_token_filer": r.get("supplementary_name_match", ""),
            "x1_hit": x1_hit,
            "x1_candidates": ";".join(str(e) for e in x1_eids),
            "x1_evidence": " | ".join(x1_ev),
            "x2_hit": x2_hit,
            "x2_candidates": ";".join(str(e) for e in x2_eids),
            "x2_evidence": " | ".join(x2_ev),
            "x3_hit": x3_hit,
            "x3_candidates": ";".join(str(e) for e in x3_eids),
            "x3_evidence": " | ".join(x3_ev),
            "x4_hit": x4_hit,
            "x4_candidates": ";".join(str(e) for e in x4_eids),
            "x4_subprobes": ";".join(x4_subs),
            "x4_evidence": " | ".join(x4_ev),
            "n_signals_corroborated": n_signals,
            "x4_4c_only_no_candidate": x4_4c_only_flag,
            "candidate_concordance": concordance,
            "concordance_eids": ";".join(str(e) for e in sorted(concordance_set)),
            "bucket": bucket,
        }
        matrix.append(rec)
        # Per-signal markers: Y when signal returned a candidate, c
        # (lowercase) when X4 only fired sub-probe 4c (no candidate).
        x4_marker = "c" if x4_4c_only_flag else ("Y" if (x4_hit and x4_eids) else ".")
        print(
            f"  rank {rec['rank']:>2} eid={brand_eid:<6} "
            f"AUM=${rec['fund_aum_billions']:>7,.1f}B  "
            f"X1={'Y' if x1_hit else '.'} "
            f"X2={'Y' if x2_hit else '.'} "
            f"X3={'Y' if x3_hit else '.'} "
            f"X4={x4_marker} "
            f"({''.join(x4_subs) or '--'})  "
            f"signals={n_signals} conc={'Y' if concordance else '.'} "
            f"bucket={bucket}  {brand_canonical[:42]}"
        )

    if drift_flags:
        print("\n  Drift flags (informational):")
        for f in drift_flags:
            print(f)
    else:
        print("\n  ✓ no canonical_name drift across the 19 LOW brands")

    # ------------------------------------------------------------------
    # Phase 3: bucket counts + AUM
    # ------------------------------------------------------------------
    print(f"\nPHASE 3 — bucket synthesis")
    buckets = {"A": [], "B": [], "C": [], "D": []}
    for rec in matrix:
        buckets[rec["bucket"]].append(rec)
    bucket_titles = {
        "A": "3-4 signals, concordant filer (HIGH)",
        "B": "2 signals, concordant filer (MEDIUM)",
        "C": "1 signal or non-concordant (LOW — keep BLOCKER 2)",
        "D": "0 signals (no_counterparty candidate)",
    }
    for b in ("A", "B", "C", "D"):
        recs = buckets[b]
        n = len(recs)
        aum = sum(rec["fund_aum_billions"] for rec in recs)
        print(f"  Bucket {b} {bucket_titles[b]:<55} n={n:>2}  AUM=${aum:>8,.1f}B")

    # Public-record sanity check (named-cohort)
    named_cohort = [
        ("FMR", "FMR LLC"),
        ("State Street", "State Street Corp"),
        ("Franklin", "Franklin Resources"),
        ("Macquarie", "Macquarie Group"),
    ]
    print(f"\nPHASE 3 — public-record sanity check (named cohort)")
    for needle, expected in named_cohort:
        for rec in matrix:
            if needle.lower() in rec["brand_canonical_name"].lower():
                print(
                    f"  '{needle:<14}' -> {rec['brand_canonical_name'][:50]:<50} "
                    f"bucket={rec['bucket']} signals={rec['n_signals_corroborated']} "
                    f"x1={'Y' if rec['x1_hit'] else '.'} "
                    f"x2={'Y' if rec['x2_hit'] else '.'} "
                    f"x4={'Y' if rec['x4_hit'] else '.'} "
                    f"(expected counterparty: {expected})"
                )

    # ------------------------------------------------------------------
    # Write CSV
    # ------------------------------------------------------------------
    MATRIX_OUT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(matrix[0].keys())
    with MATRIX_OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for rec in matrix:
            w.writerow(rec)
    print(f"\nWrote matrix: {MATRIX_OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
