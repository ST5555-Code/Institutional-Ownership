"""CP-4b discovery — Phase 2 per-brand pairing for top-20 AUTHOR_NEW_BRIDGE.

Read-only. For each top-20 brand, gather pairing evidence in priority order
per docs/decisions/inst_eid_bridge_decisions.md (BLOCKER 2):

  Step 2a — direct CIK reuse: brand CIK appears on a different
            holdings_v2-visible eid (PRIMARY ADV signal).
  Step 2b — CRD bridge:
              brand CRD on entity_identifiers (lookup both 6-digit and
              zero-padded 9-digit forms) ->
                ncen_adviser_map.adviser_crd OR adv_managers.crd_number ->
                  adv_managers.cik -> entity_identifiers -> visible filer.
            (PRIMARY ADV signal.)
  Step 2c — alias/name match against holdings_v2 manager_name and
            entity_aliases on visible filers (VERIFICATION ONLY,
            not a confidence upgrade per BLOCKER 2).

Confidence rubric per the prompt:

  HIGH    — Step 2a fires (direct CIK reuse on visible eid) OR Step 2b
            returns a single unambiguous adviser-CRD chain to one
            visible filer.
  MEDIUM  — Step 2b candidate exists but is ambiguous (multiple
            CRDs / multiple chains / CIK-chain rather than direct).
  LOW     — no Step 2a/2b signal. Step 2c name match (if present) is
            recorded as supplementary evidence ONLY. EXCLUDED from
            cp-4b-author-top20 author PR.

Refs docs/decisions/inst_eid_bridge_decisions.md (BLOCKER 2).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"


def load_visible_filers(con: duckdb.DuckDBPyConnection) -> set[int]:
    rows = con.execute("""
        SELECT DISTINCT entity_id FROM holdings_v2
        WHERE is_latest = TRUE AND entity_id IS NOT NULL
        UNION
        SELECT DISTINCT dm_rollup_entity_id FROM holdings_v2
        WHERE is_latest = TRUE AND dm_rollup_entity_id IS NOT NULL
    """).fetchall()
    return {r[0] for r in rows}


def crd_variants(raw: str) -> list[str]:
    """Return both unpadded and 9-zero-padded forms of a CRD."""
    s = str(raw).strip()
    s = s.lstrip("0") or "0"
    return list({s, s.zfill(9), s.zfill(7)})


def step_2a_direct_cik(con, brand_cik: str | None, brand_eid: int,
                       visible: set[int]) -> list[dict]:
    if not brand_cik:
        return []
    rows = con.execute(f"""
        SELECT DISTINCT entity_id
        FROM entity_identifiers
        WHERE identifier_type = 'cik'
          AND identifier_value = ?
          AND (valid_to IS NULL OR valid_to = {SENTINEL} OR valid_to >= CURRENT_DATE)
          AND entity_id != ?
    """, [brand_cik, brand_eid]).fetchall()
    out = []
    for (eid,) in rows:
        if eid in visible:
            out.append({"eid": eid, "evidence": f"direct CIK reuse {brand_cik}"})
    return out


def step_2b_crd_bridge(con, brand_eid: int,
                       visible: set[int]) -> list[dict]:
    """Walk brand CRDs into adv_managers and N-CEN, resolve to visible eids."""
    crd_rows = con.execute(f"""
        SELECT DISTINCT identifier_value
        FROM entity_identifiers
        WHERE entity_id = ? AND identifier_type = 'crd'
          AND (valid_to IS NULL OR valid_to = {SENTINEL}
               OR valid_to >= CURRENT_DATE)
    """, [brand_eid]).fetchall()
    crds: list[str] = []
    for (c,) in crd_rows:
        crds.extend(crd_variants(c))
    crds = list(set(crds))
    if not crds:
        return []

    placeholders = ",".join("?" * len(crds))
    # adv_managers by CRD
    adv = con.execute(f"""
        SELECT crd_number, cik, firm_name
        FROM adv_managers
        WHERE crd_number IN ({placeholders})
    """, crds).fetchdf()

    out: list[dict] = []

    # Resolve adv_managers CIK to a visible eid (if different from brand)
    for _, a in adv.iterrows():
        if not a["cik"]:
            continue
        cik_padded = str(a["cik"]).zfill(10)
        cik_unpadded = str(a["cik"]).lstrip("0") or "0"
        rows = con.execute(f"""
            SELECT DISTINCT entity_id
            FROM entity_identifiers
            WHERE identifier_type = 'cik'
              AND identifier_value IN (?, ?)
              AND (valid_to IS NULL OR valid_to = {SENTINEL}
                   OR valid_to >= CURRENT_DATE)
              AND entity_id != ?
        """, [cik_padded, cik_unpadded, brand_eid]).fetchall()
        for (eid,) in rows:
            if eid in visible:
                out.append({
                    "eid": eid,
                    "evidence": (f"CRD {a['crd_number']} -> adv_managers cik "
                                 f"{a['cik']} ({a['firm_name']}) -> visible eid"),
                })

    # ncen_adviser_map: brand CRD as adviser_crd -> registrant_cik -> resolve?
    # In this DB, registrant_cik is the FUND, not a visible 13F filer, so this
    # rarely produces a visible-eid match. Still record any hits.
    ncen = con.execute(f"""
        SELECT DISTINCT registrant_cik, registrant_name, role,
               COUNT(*) AS n_filings
        FROM ncen_adviser_map
        WHERE adviser_crd IN ({placeholders})
          AND valid_to = {SENTINEL}
        GROUP BY 1, 2, 3
        ORDER BY n_filings DESC
        LIMIT 50
    """, crds).fetchdf()
    for _, n in ncen.iterrows():
        rcik = n["registrant_cik"]
        if not rcik:
            continue
        rcik_padded = str(rcik).zfill(10)
        rows = con.execute(f"""
            SELECT DISTINCT entity_id FROM entity_identifiers
            WHERE identifier_type='cik' AND identifier_value=?
              AND (valid_to IS NULL OR valid_to = {SENTINEL}
                   OR valid_to >= CURRENT_DATE)
              AND entity_id != ?
        """, [rcik_padded, brand_eid]).fetchall()
        for (eid,) in rows:
            if eid in visible:
                out.append({
                    "eid": eid,
                    "evidence": (f"N-CEN registrant {n['registrant_name']} "
                                 f"(role={n['role']}) -> visible eid"),
                })

    return out


_token_re = re.compile(r"[A-Z0-9]+")


def name_tokens(name: str) -> set[str]:
    if not name:
        return set()
    stop = {"INC", "LLC", "LP", "LTD", "CO", "CORP", "GROUP", "MANAGEMENT",
            "ASSET", "ADVISERS", "ADVISORS", "ADVISOR", "INVESTMENT",
            "INVESTMENTS", "CAPITAL", "FUND", "FUNDS", "TRUST", "AND",
            "PARTNERS", "GLOBAL", "INTERNATIONAL", "AMERICA", "U", "S",
            "INC.", "L.P.", "L.L.C.", "AGGREGATOR", "HOLDINGS"}
    toks = {t for t in _token_re.findall(name.upper()) if len(t) >= 2}
    return toks - stop


def step_2c_name_match(con, brand_name: str, brand_eid: int,
                       visible: set[int]) -> list[dict]:
    if not brand_name:
        return []
    btoks = name_tokens(brand_name)
    if not btoks:
        return []
    # Pull holdings_v2 13F filers
    h = con.execute("""
        SELECT DISTINCT entity_id, ANY_VALUE(manager_name) AS name,
                        ANY_VALUE(cik) AS cik, COUNT(*) AS n
        FROM holdings_v2
        WHERE is_latest = TRUE AND entity_id IS NOT NULL
        GROUP BY entity_id
    """).fetchdf()
    out = []
    for _, r in h.iterrows():
        if r["entity_id"] == brand_eid or r["entity_id"] not in visible:
            continue
        toks = name_tokens(r["name"])
        if not toks:
            continue
        overlap = btoks & toks
        if len(overlap) >= 1 and (len(overlap) / max(len(btoks), 1)) >= 0.5:
            out.append({
                "eid": int(r["entity_id"]),
                "evidence": (f"name-token overlap {sorted(overlap)} with "
                             f"13F filer '{r['name']}' (cik={r['cik']}, n={int(r['n'])})"),
                "score": len(overlap) / max(len(btoks), 1),
                "n_holdings": int(r["n"]),
            })
    out.sort(key=lambda d: (-d["score"], -d.get("n_holdings", 0)))
    return out[:5]


def visible_filer_label(con, eid: int) -> str:
    row = con.execute("""
        SELECT ANY_VALUE(display_name)
        FROM entity_current WHERE entity_id = ?
    """, [eid]).fetchone()
    return row[0] if row and row[0] else f"eid={eid}"


def visible_filer_cik(con, eid: int) -> str | None:
    row = con.execute(f"""
        SELECT identifier_value
        FROM entity_identifiers
        WHERE entity_id = ? AND identifier_type = 'cik'
          AND (valid_to IS NULL OR valid_to = {SENTINEL}
               OR valid_to >= CURRENT_DATE)
        ORDER BY valid_from DESC LIMIT 1
    """, [eid]).fetchone()
    return row[0] if row else None


def parent_summary(con, brand_eid: int, visible: set[int]) -> str:
    rows = con.execute(f"""
        SELECT DISTINCT parent_entity_id, relationship_type, source
        FROM entity_relationships
        WHERE child_entity_id = ?
          AND valid_to = {SENTINEL}
    """, [brand_eid]).fetchall()
    if not rows:
        return "no parent"
    parts = []
    for (pid, rtype, src) in rows:
        v = "visible" if pid in visible else "invisible"
        nm = visible_filer_label(con, pid)
        parts.append(f"parent eid={pid} ({nm}, {v}, type={rtype}, src={src})")
    return "; ".join(parts)


def classify(s2a: list[dict], s2b: list[dict],
             _s2c: list[dict]) -> tuple[str, dict | None, str]:
    # _s2c is intentionally unused: BLOCKER 2 forbids name-similarity from
    # upgrading confidence. Name evidence is recorded as a supplementary
    # column in the manifest, not in the classification.
    if s2a:
        rec = s2a[0]
        return "HIGH", rec, rec["evidence"]
    if s2b:
        # group by visible eid
        agg: dict[int, list[dict]] = {}
        for r in s2b:
            agg.setdefault(r["eid"], []).append(r)
        if len(agg) == 1:
            eid, evs = next(iter(agg.items()))
            return ("HIGH", {"eid": eid, "evidence": evs[0]["evidence"]},
                    evs[0]["evidence"] + " (single CRD chain to one visible eid)")
        # multi-candidate
        # pick top by lexical first
        eid, evs = sorted(agg.items())[0]
        ev = (evs[0]["evidence"]
              + f" (also {len(agg)-1} other candidate visible eids; ambiguous)")
        return "MEDIUM", {"eid": eid, "evidence": ev}, ev
    return "LOW", None, "no Step 2a/2b ADV signal"


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    visible = load_visible_filers(con)
    print(f"visible filer eids: {len(visible):,}")

    top20 = pd.read_csv("data/working/cp-4b-top20-input.csv", dtype={"cik": str})
    print(f"top-20 input rows: {len(top20)}\n")

    rows_out = []
    for rank, (_, b) in enumerate(top20.iterrows(), 1):
        brand_eid = int(b["eid"])
        brand_name = b["display_name"]
        if pd.isna(b["cik"]):
            brand_cik = None
        else:
            raw = str(b["cik"]).strip()
            if raw.endswith(".0"):
                raw = raw[:-2]
            brand_cik = raw.zfill(10) if raw and raw != "nan" else None
        fund_aum = float(b["fund_aum"])

        s2a = step_2a_direct_cik(con, brand_cik, brand_eid, visible)
        s2b = step_2b_crd_bridge(con, brand_eid, visible)
        s2c = step_2c_name_match(con, brand_name, brand_eid, visible)

        confidence, rec, ev = classify(s2a, s2b, s2c)

        if rec is None:
            paired_eid = None
            paired_name = None
            paired_cik = None
            next_action = "MANUAL_PAIRING_REQUIRED"
        else:
            paired_eid = rec["eid"]
            paired_name = visible_filer_label(con, paired_eid)
            paired_cik = visible_filer_cik(con, paired_eid)
            next_action = ("BRIDGE_READY" if confidence == "HIGH"
                           else "MANUAL_VERIFY")

        # supplementary fields
        parent_text = parent_summary(con, brand_eid, visible)
        name_match_top = (s2c[0]["evidence"] if s2c else "")

        rows_out.append({
            "rank": rank,
            "brand_eid": brand_eid,
            "brand_canonical_name": brand_name,
            "brand_cik": brand_cik,
            "fund_aum_usd_billions": round(fund_aum / 1e9, 1),
            "paired_filer_eid": paired_eid,
            "paired_filer_name": paired_name,
            "paired_filer_cik": paired_cik,
            "pairing_evidence": ev,
            "confidence": confidence,
            "next_action": next_action,
            "supplementary_name_match": name_match_top,
            "parent_relationship_summary": parent_text,
            "n_step2a": len(s2a),
            "n_step2b": len(s2b),
            "n_step2c": len(s2c),
        })

        print(f"[{rank:>2}] {brand_name[:50]:<50s} cik={brand_cik or '----------'}  "
              f"-> {confidence:<6s}  {next_action}")
        if paired_eid:
            print(f"     paired eid={paired_eid} ({paired_name}, cik={paired_cik})")
        print(f"     ev: {ev[:140]}")
        if name_match_top:
            print(f"     supp name: {name_match_top[:140]}")
        if parent_text != "no parent":
            print(f"     parent: {parent_text[:140]}")
        print()

    df = pd.DataFrame(rows_out)
    out_path = Path("data/working/cp-4b-discovery-manifest.csv")
    df.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}")

    summary = df.groupby("confidence").agg(
        n=("rank", "count"),
        aum_b=("fund_aum_usd_billions", "sum"),
    ).reset_index()
    print("\n=== confidence summary ===")
    print(summary.to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
