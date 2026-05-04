"""CP-5 discovery — Phase 6: cp-4c brand re-categorization under CP-5 framing.

Read-only. Re-categorizes the 19 LOW cohort brands from cp-4b discovery + the
4 already-bridged brands (cp-4b carve-out) under the CP-5 read-layer framing:

  Category A — already bridged via cp-4b carve-out (T.Rowe, First Trust, FMR, SSGA).
               No CP-5 action needed; existing bridges sufficient.
  Category B — clean 13F counterparty available; needs bridge sub-PR under CP-5.
               Likely candidates from public-record sanity check (cp-4b probe).
  Category C — no 13F counterparty by design; CP-5 read layer reaches
               fund_holdings_v2 directly via the rollup graph.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Source: cp-4b discovery manifest + cp-4b BLOCKER 2 corroboration probe
# AUM figures = brand-side fund AUM ($B) from cp-4b-discovery snapshot
ROWS = [
    # === Category A — already bridged (cp-4b carve-out) ===
    (17924, "T. Rowe Price Associates", 1105.5, "A",
     "BRIDGED — relationship_id=20820 (PR #267 cp-4b-author-trowe). brand eid 17924 → filer eid 3616.",
     "filer eid 3616"),
    (8, "First Trust", 232.7, "A",
     "BRIDGED — relationship_id=20821 (PR #269 cp-4b-author-first-trust). brand eid 8 → filer eid 136.",
     "filer eid 136"),
    (11, "Fidelity / FMR (brand)", 415.3, "A",
     "BRIDGED — relationship_id=20822 (PR #270 cp-4b-author-fmr). brand eid 11 → filer eid 10443.",
     "filer eid 10443"),
    (3, "State Street / SSGA (brand)", 301.9, "A",
     "BRIDGED — relationship_id=20823 (PR #271 cp-4b-author-ssga). brand eid 3 → filer eid 7984.",
     "filer eid 7984"),

    # === Category B — clean 13F counterparty, needs bridge ===
    (18073, "J.P. Morgan Investment Management Inc.", 2714.5, "B",
     "Public-record bridge target: filer eid 4433 (JPMorgan Chase & Co, 13F filer). "
     "ADV CRD chain absent; manual bridge from JPM 10-K/ADV Schedule A.",
     "JPMorgan Chase & Co (eid 4433)"),
    (9904, "TEACHERS ADVISORS, LLC", 1571.1, "B",
     "Public-record bridge target: TIAA / Nuveen (visible eid pending). "
     "Teachers Advisors is a TIAA subsidiary; needs ADV Schedule A or N-CEN crosswalk.",
     "Nuveen / TIAA (TBD eid)"),
    (1355, "FRANKLIN ADVISERS INC", 1162.8, "B",
     "Public-record bridge target: Franklin Resources (parent). cp-4b probe missed. "
     "Manual bridge via 10-K subsidiary list.",
     "Franklin Resources (TBD eid)"),
    (2400, "Fidelity Management & Research Co LLC", 714.6, "B",
     "Public-record bridge target: FMR LLC (eid 10443) — same target as bridged brand 11. "
     "Add second bridge edge or merge brand into existing bridge.",
     "FMR LLC (eid 10443)"),
    (18983, "Jackson National Asset Management, LLC", 300.8, "B",
     "Public-record bridge target: Jackson Financial Inc / Prudential plc subsidiary. "
     "Needs corporate-action research.",
     "Jackson Financial (TBD eid)"),
    (17930, "Federated Advisory Services Company", 275.3, "B",
     "Public-record bridge target: Federated Hermes (visible eid). Manual bridge.",
     "Federated Hermes (TBD eid)"),
    (10538, "MANULIFE INVESTMENT MANAGEMENT (US) LLC", 258.0, "B",
     "Public-record bridge target: Manulife Financial Corp (eid 8994 from Phase 1 top-20). "
     "Brand → top-parent already implicit; needs explicit bridge for visibility.",
     "Manulife Financial Corp (eid 8994)"),
    (2232, "SUNAMERICA ASSET MANAGEMENT, LLC", 222.2, "B",
     "Public-record bridge target: AIG / Corebridge Financial subsidiary. Manual bridge.",
     "AIG/Corebridge (TBD eid)"),
    (2562, "Equitable Investment Management, LLC", 221.1, "B",
     "Public-record bridge target: Equitable Holdings Inc (eid 9526 — concordant from cp-4b probe). "
     "Bridge READY to author per probe Bucket B finding.",
     "Equitable Holdings (eid 9526)"),
    (18177, "Brighthouse Investment Advisers, LLC", 168.9, "B",
     "Public-record bridge target: Brighthouse Financial Inc. Manual bridge.",
     "Brighthouse Financial (TBD eid)"),
    (7823, "Thrivent Asset Management, LLC", 153.1, "B",
     "Public-record bridge target: Thrivent Financial. Manual bridge.",
     "Thrivent Financial (TBD eid)"),
    (18298, "Transamerica Asset Management, Inc.", 145.4, "B",
     "Public-record bridge target: Aegon NV (Transamerica parent). cp-4b probe surfaced "
     "FALSE POSITIVE (eid 2080 = Transamerica Financial Advisors, broker-dealer, not AM arm). "
     "Manual bridge to Aegon required.",
     "Aegon NV (TBD eid)"),
    (5127, "PUTNAM INVESTMENT MANAGEMENT LLC", 133.0, "B",
     "Public-record bridge target: Franklin Resources (acquired Putnam from Power Corp 2024). "
     "Manual bridge — note acquisition history.",
     "Franklin Resources (TBD eid; same as Franklin Advisers parent)"),

    # === Category C — no 13F counterparty by design ===
    (2322, "PIMCO (PACIFIC INVESTMENT MANAGEMENT CO LLC)", 2044.2, "C",
     "NO 13F COUNTERPARTY: PIMCO is a fixed-income manager; equity book is small/fund-only. "
     "13F filings non-existent or de minimis. CP-5 read layer must reach fund_holdings_v2 "
     "directly via rollup graph for PIMCO's equity exposure (small).",
     "(none — fund-only via rollup)"),
    (19555, "WisdomTree Asset Management, Inc.", 262.2, "C",
     "Possible C: WisdomTree files some 13F via affiliates but main vehicle is ETF (N-PORT). "
     "Reach via fund_holdings_v2.",
     "(ETF-primary; fund-tier)"),
    (17935, "Macquarie Investment Management Global Limited", 138.4, "C",
     "Macquarie has multi-jurisdiction structure; US 13F filers exist but rollup is non-trivial. "
     "Default to fund-tier reach via rollup graph until manual bridge authored.",
     "(fund-tier default)"),
]


def main() -> int:
    df = pd.DataFrame(ROWS, columns=[
        "brand_entity_id",
        "brand_canonical_name",
        "fund_aum_b",
        "category",
        "recommended_treatment",
        "candidate_filer_or_target",
    ])

    out_path = Path("data/working/cp-5-brand-categorization.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(df)} rows)")

    print("\n=== category distribution ===")
    print(df.groupby("category").agg(
        n=("brand_entity_id", "count"),
        aum_b=("fund_aum_b", "sum"),
    ).to_string())

    print(f"\n=== Category B candidates (need bridge under CP-5) ===")
    print(df[df["category"] == "B"][["brand_entity_id", "brand_canonical_name",
                                       "fund_aum_b", "candidate_filer_or_target"]].to_string(index=False))

    print(f"\n=== Category C (no 13F counterparty by design) ===")
    print(df[df["category"] == "C"][["brand_entity_id", "brand_canonical_name",
                                       "fund_aum_b"]].to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
