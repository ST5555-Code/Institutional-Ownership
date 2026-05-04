"""CP-5 comprehensive discovery — Bundle A, Probe 1: R5 dedup-rule defects.

Read-only investigation. Quantifies the three R5 defects identified in
docs/findings/cp-5-discovery.md §6:
  1.1 — fund-of-fund cross-holdings (intra-family vs extra-family)
  1.2 — non-valid CUSIP cohort (sentinel and missing CUSIPs)
  1.3 — 13F_only anomaly for asset-manager top-parents
  1.4 — modified R5 rule synthesis (recommendations only)

Outputs:
  data/working/cp-5-bundle-a-fof-footprint.csv
  data/working/cp-5-bundle-a-null-cusip-cohort.csv
  data/working/cp-5-bundle-a-13f-only-anomalies.csv

Refs docs/findings/cp-5-discovery.md, docs/decisions/d4-classification-precedence.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
COVERAGE_QUARTER = "2025Q4"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")
WORKDIR = Path("data/working")


def build_inst_to_tp(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Reproduce Phase 1 institution-to-top-parent climb (deterministic, cycle-safe)."""
    types_sql = ", ".join(f"'{t}'" for t in ROLLUP_CTRL_TYPES)
    edges = con.execute(f"""
        SELECT er.child_entity_id, er.parent_entity_id
        FROM entity_relationships er
        JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
        JOIN entity_current cec ON cec.entity_id = er.child_entity_id
        WHERE er.valid_to = {SENTINEL}
          AND er.control_type IN ({types_sql})
          AND pec.entity_type = 'institution'
          AND cec.entity_type = 'institution'
    """).fetchdf()
    edges = edges.sort_values(["child_entity_id", "parent_entity_id"]).drop_duplicates(
        "child_entity_id", keep="first"
    )
    edge_map = dict(zip(edges["child_entity_id"], edges["parent_entity_id"]))

    seed = con.execute(
        "SELECT entity_id FROM entity_current WHERE entity_type='institution'"
    ).fetchdf()
    cur = {eid: eid for eid in seed["entity_id"]}
    visited = {eid: {eid} for eid in cur}
    cycles: set[int] = set()
    for _ in range(20):
        changed = 0
        for ent, tp in list(cur.items()):
            if ent in cycles:
                continue
            nxt = edge_map.get(tp)
            if nxt is None or nxt == tp:
                continue
            if nxt in visited[ent]:
                cycles.add(ent)
                continue
            visited[ent].add(nxt)
            cur[ent] = nxt
            changed += 1
        if changed == 0:
            break
    return pd.DataFrame(
        {"entity_id": list(cur.keys()), "top_parent_entity_id": list(cur.values())}
    )


def build_fund_to_tp(
    con: duckdb.DuckDBPyConnection, inst_to_tp: pd.DataFrame
) -> pd.DataFrame:
    """Map every fund-typed entity to its top_parent via decision_maker_v1 rollup."""
    fund_chain = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id,
               erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND ec_f.entity_type = 'fund'
          AND erh.rollup_type = 'decision_maker_v1'
    """).fetchdf()
    fund_chain = fund_chain.merge(
        inst_to_tp.rename(columns={"entity_id": "institution_entity_id"}),
        on="institution_entity_id",
        how="left",
    )
    return fund_chain


# Brand-stem normalization for fund-of-fund detection. The canonical_type
# filter on `securities` (ETF/MUTUAL_FUND/CEF) misses institutional share
# classes that securities.canonical_type tags as 'COM' (e.g., VSMPX, VGTSX,
# VTBIX). We pivot to a name-based brand-token match: a held position is
# "intra-family" when the held security's issuer_name shares a high-signal
# brand token with the outer fund's family_name.
#
# Stopwords: words that appear across many families and don't disambiguate.
BRAND_STOPWORDS = {
    "FUNDS", "FUND", "TRUST", "INDEX", "ETF", "ETFS", "GROUP", "INC",
    "INC.", "LLC", "LP", "LTD", "LTD.", "CORP", "CORP.", "COMPANY", "CO",
    "CO.", "THE", "AND", "OF", "FOR", "ADVISORS", "ADVISERS", "ADVISORY",
    "MANAGEMENT", "INVESTMENT", "INVESTMENTS", "CAPITAL", "ASSET", "ASSETS",
    "SERIES", "SHARES", "PORTFOLIO", "PORTFOLIOS", "INSTITUTIONAL",
    "ETF.", "EXCHANGE", "EXCHANGE-TRADED", "INDEX-TRACKING",
    "INTERNATIONAL", "INTERNATIONAL,", "GLOBAL", "AMERICA", "AMERICAN",
    "U.S.", "US", "USA", "MUNICIPAL", "BOND", "BONDS", "EQUITY",
    "EQUITIES", "STOCK", "STOCKS", "INCOME", "GROWTH", "VALUE", "TOTAL",
    "VARIABLE", "INSURANCE", "STRATEGIC", "TARGET", "RETIREMENT",
    "BALANCED", "MIDCAP", "SMALLCAP", "LARGECAP", "MULTI", "MULTI-",
    "ESG", "TAX", "TAX-EXEMPT", "TAX-MANAGED", "FUNDS,", "TRUST,",
    "TRUSTS", "FAMILY", "INVESTORS", "FUND,", "ACTIVE", "PASSIVE",
}


def _brand_stem(name: str | None) -> str | None:
    """Extract the leading high-signal brand token (uppercase, alphanum)."""
    if not isinstance(name, str) or not name:
        return None
    tokens = [
        "".join(ch for ch in tok.upper() if ch.isalnum())
        for tok in name.split()
    ]
    for tok in tokens:
        if not tok:
            continue
        if tok in BRAND_STOPWORDS:
            continue
        if len(tok) <= 2:
            continue
        return tok
    return None


def probe_1_1_fof(
    con: duckdb.DuckDBPyConnection, fund_to_tp: pd.DataFrame
) -> pd.DataFrame:
    """Probe 1.1 — fund-of-fund cross-holdings (intra-family vs extra-family).

    Two-pass detection:
      Pass A — securities.canonical_type IN ('ETF','MUTUAL_FUND','CEF')
               (catches well-classified fund securities)
      Pass B — name-based brand-stem match (catches institutional share
               classes mis-classified as COM, e.g., VSMPX/VGTSX/VTBIX)
    The union is the FoF cohort. Intra vs extra family is determined by
    matching the held security's brand stem to the outer fund's family stem.
    """
    print("\n" + "=" * 72)
    print("PROBE 1.1 — fund-of-fund cross-holdings (name-based detection)")
    print("=" * 72)

    # Pass A — securities canonical_type catches ETFs, mutual funds, CEFs
    fund_typed_cusips = con.execute("""
        SELECT cusip, canonical_type, issuer_name AS sec_issuer
        FROM securities
        WHERE canonical_type IN ('ETF', 'MUTUAL_FUND', 'CEF')
          AND cusip IS NOT NULL AND LENGTH(cusip) = 9
    """).fetchdf()
    print(
        f"  Pass A — fund-typed CUSIPs by canonical_type: "
        f"{len(fund_typed_cusips):,} "
        f"({fund_typed_cusips['canonical_type'].value_counts().to_dict()})"
    )

    # Pass B — name-based: any held security in fund_holdings_v2 whose
    # issuer_name shares a brand stem with the outer fund's family_name.
    # We compute this in pandas (cleanest path; SQL would need a UDF).
    con.register("fund_to_tp_df", fund_to_tp)

    held_sql = f"""
    SELECT fh.entity_id AS outer_fund_eid,
           fh.family_name AS outer_family,
           fh.fund_name AS outer_fund_name,
           ftp.top_parent_entity_id AS outer_top_parent,
           fh.cusip AS held_cusip,
           fh.issuer_name AS held_issuer,
           fh.ticker AS held_ticker,
           fh.market_value_usd
    FROM fund_holdings_v2 fh
    LEFT JOIN fund_to_tp_df ftp ON ftp.fund_entity_id = fh.entity_id
    WHERE fh.is_latest
      AND fh.quarter = '{COVERAGE_QUARTER}'
      AND fh.asset_category = 'EC'
      AND fh.cusip IS NOT NULL
      AND fh.cusip ~ '^[0-9A-Z]{{9}}$'
    """
    held = con.execute(held_sql).fetchdf()
    print(f"  All EC valid-CUSIP holdings (2025Q4): {len(held):,} rows")

    # Tag fund-typed via Pass A
    pass_a_set = set(fund_typed_cusips["cusip"])
    held["is_fund_typed_passA"] = held["held_cusip"].isin(pass_a_set)

    # Pass B — name-based. A held security is fund-typed if its issuer_name
    # shares a brand stem with ANY family in our universe (heuristic: brand
    # stem matches a known fund-family brand stem). We approximate by
    # building the set of brand stems from `family_name` in fund_holdings_v2
    # itself — those stems are by construction fund families.
    held["outer_family_stem"] = held["outer_family"].map(_brand_stem)
    held["held_issuer_stem"] = held["held_issuer"].map(_brand_stem)
    family_stems = set(held["outer_family_stem"].dropna().unique())
    print(f"  Distinct family brand stems: {len(family_stems):,}")

    held["is_fund_typed_passB"] = held["held_issuer_stem"].isin(family_stems)
    held["is_fof"] = held["is_fund_typed_passA"] | held["is_fund_typed_passB"]

    fof = held[held["is_fof"]].copy()
    print(
        f"  FoF candidate rows: {len(fof):,}  "
        f"(passA={held['is_fund_typed_passA'].sum():,}, "
        f"passB={held['is_fund_typed_passB'].sum():,}, "
        f"union={fof['is_fof'].sum():,})"
    )

    # Intra-family: brand stems match
    fof["family_match"] = "extra_family"
    fof.loc[
        (fof["outer_family_stem"].notna())
        & (fof["held_issuer_stem"].notna())
        & (fof["outer_family_stem"] == fof["held_issuer_stem"]),
        "family_match",
    ] = "intra_family"
    fof.loc[
        (fof["outer_family_stem"].isna()) | (fof["held_issuer_stem"].isna()),
        "family_match",
    ] = "unknown_match"

    summary = (
        fof.groupby("family_match")
        .agg(n_rows=("market_value_usd", "size"),
             aum_b=("market_value_usd", lambda s: s.sum() / 1e9))
        .reset_index()
        .sort_values("aum_b", ascending=False)
    )
    print("\n  Aggregate FoF AUM by family-match class:")
    print(summary.to_string(index=False))

    # Top 25 top_parents by intra-family FoF AUM
    intra = (
        fof[fof["family_match"] == "intra_family"]
        .groupby("outer_top_parent")
        .agg(n_rows=("market_value_usd", "size"),
             aum_b=("market_value_usd", lambda s: s.sum() / 1e9))
        .reset_index()
        .sort_values("aum_b", ascending=False)
        .head(25)
    )
    name_map = (
        con.execute(
            "SELECT entity_id, display_name FROM entity_current "
            "WHERE entity_type='institution'"
        )
        .fetchdf()
        .set_index("entity_id")["display_name"]
        .to_dict()
    )
    intra["top_parent_name"] = intra["outer_top_parent"].map(
        lambda x: name_map.get(int(x), "?") if pd.notna(x) else "(unmapped)"
    )
    print("\n  Top 25 top-parents by intra-family FoF AUM ($B):")
    print(
        intra[["outer_top_parent", "top_parent_name", "n_rows", "aum_b"]]
        .to_string(index=False)
    )

    # Per-(top_parent, family_match) rollup for the CSV
    fof_rolled = (
        fof.groupby(["outer_top_parent", "outer_family", "family_match"])
        .agg(n_rows=("market_value_usd", "size"),
             aum_b=("market_value_usd", lambda s: s.sum() / 1e9))
        .reset_index()
    )
    fof_rolled.to_csv(WORKDIR / "cp-5-bundle-a-fof-footprint.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-a-fof-footprint.csv'}")
    return fof_rolled


def probe_1_2_null_cusip(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Probe 1.2 — non-valid CUSIP cohort + secondary key feasibility."""
    print("\n" + "=" * 72)
    print("PROBE 1.2 — non-valid CUSIP cohort")
    print("=" * 72)

    bucket_sql = f"""
    WITH classified AS (
      SELECT
        CASE
          WHEN cusip IS NULL THEN 'NULL'
          WHEN cusip = '' THEN 'empty'
          WHEN cusip = 'N/A' OR cusip = 'NA' THEN 'NA_lit'
          WHEN cusip = '000000000' OR cusip = '999999999' THEN 'zeros_or_nines'
          WHEN LENGTH(cusip) < 9 THEN 'short_cusip'
          WHEN cusip ~ '^[0-9A-Z]{{9}}$' THEN 'valid_format'
          ELSE 'other'
        END AS cusip_bucket,
        asset_category, isin, issuer_name, ticker, market_value_usd
      FROM fund_holdings_v2
      WHERE is_latest AND quarter = '{COVERAGE_QUARTER}'
    )
    SELECT cusip_bucket,
           asset_category,
           COUNT(*) AS n_rows,
           SUM(market_value_usd) / 1e9 AS aum_b,
           SUM(CASE WHEN isin IS NOT NULL AND isin <> '' THEN 1 ELSE 0 END) AS n_isin,
           SUM(CASE WHEN issuer_name IS NOT NULL AND issuer_name <> '' THEN 1 ELSE 0 END) AS n_issuer,
           SUM(CASE WHEN ticker IS NOT NULL AND ticker <> '' THEN 1 ELSE 0 END) AS n_ticker
    FROM classified
    GROUP BY 1, 2
    ORDER BY n_rows DESC
    """
    buckets = con.execute(bucket_sql).fetchdf()
    print("\n  Cohort by (cusip_bucket, asset_category) — 2025Q4 is_latest:")
    print(buckets.to_string(index=False))

    # Top issuers in non-valid bucket (any cohort that is not valid_format)
    top_issuer_sql = f"""
    WITH classified AS (
      SELECT
        CASE
          WHEN cusip IS NULL THEN 'NULL'
          WHEN cusip = '' THEN 'empty'
          WHEN cusip = 'N/A' OR cusip = 'NA' THEN 'NA_lit'
          WHEN cusip = '000000000' OR cusip = '999999999' THEN 'zeros_or_nines'
          WHEN LENGTH(cusip) < 9 THEN 'short_cusip'
          WHEN cusip ~ '^[0-9A-Z]{{9}}$' THEN 'valid_format'
          ELSE 'other'
        END AS cusip_bucket,
        asset_category, issuer_name, market_value_usd, isin
      FROM fund_holdings_v2
      WHERE is_latest AND quarter = '{COVERAGE_QUARTER}'
    )
    SELECT cusip_bucket, asset_category, COALESCE(issuer_name, '(NULL)') AS issuer_name,
           COUNT(*) AS n_rows,
           SUM(market_value_usd) / 1e9 AS aum_b,
           ANY_VALUE(isin) AS sample_isin
    FROM classified
    WHERE cusip_bucket <> 'valid_format'
    GROUP BY 1, 2, 3
    ORDER BY aum_b DESC NULLS LAST
    LIMIT 100
    """
    top_issuers = con.execute(top_issuer_sql).fetchdf()
    print("\n  Top 30 issuers in non-valid CUSIP cohort by AUM:")
    print(top_issuers.head(30).to_string(index=False, max_colwidth=60))

    # Recoverability via ISIN
    recover_sql = f"""
    WITH ec_only AS (
      SELECT cusip, isin, issuer_name, market_value_usd
      FROM fund_holdings_v2
      WHERE is_latest AND quarter = '{COVERAGE_QUARTER}'
        AND asset_category = 'EC'
        AND NOT (cusip ~ '^[0-9A-Z]{{9}}$')
    )
    SELECT
      COUNT(*) AS n_rows,
      SUM(CASE WHEN isin IS NOT NULL AND LENGTH(isin) = 12 THEN 1 ELSE 0 END) AS n_with_valid_isin,
      SUM(market_value_usd) / 1e9 AS aum_b_total,
      SUM(CASE WHEN isin IS NOT NULL AND LENGTH(isin) = 12
               THEN market_value_usd ELSE 0 END) / 1e9 AS aum_b_recoverable
    FROM ec_only
    """
    rec = con.execute(recover_sql).fetchdf()
    print("\n  EC asset_category non-valid CUSIP recoverability via ISIN:")
    print(rec.to_string(index=False))

    # Save full per-bucket / per-asset_category cohort
    buckets.to_csv(WORKDIR / "cp-5-bundle-a-null-cusip-cohort.csv", index=False)
    top_issuers.to_csv(WORKDIR / "cp-5-bundle-a-null-cusip-top-issuers.csv", index=False)
    print(f"\n  Wrote cp-5-bundle-a-null-cusip-cohort.csv (+ -top-issuers.csv)")
    return buckets


def probe_1_3_13f_only(
    con: duckdb.DuckDBPyConnection,
    inst_to_tp: pd.DataFrame,
    fund_to_tp: pd.DataFrame,
) -> pd.DataFrame:
    """Probe 1.3 — Schwab/D&C-style 13F_only anomaly investigation.

    Loads the Phase 1 coverage matrix, identifies 13F_only top-parents that
    look like asset managers (heuristic on canonical_name), and checks
    whether fund_holdings_v2 has any rollup chain that traces to them.
    """
    print("\n" + "=" * 72)
    print("PROBE 1.3 — 13F_only top-parent anomalies")
    print("=" * 72)

    cov = pd.read_csv("data/working/cp-5-top-parent-coverage-matrix.csv")
    only13f = cov[cov["coverage_class"] == "13F_only"].copy()
    print(f"  13F_only top-parents in coverage matrix (top-100 file): {len(only13f):,}")

    # Asset-manager name heuristic
    keywords = (
        "ADVISORS",
        "ASSET MANAGEMENT",
        "INVESTMENT MANAGEMENT",
        "INVESTMENT ADVISERS",
        "INVESTMENT ADVISORS",
        "INVESTMENTS",
        "CAPITAL",
        "FUNDS",
        "WEALTH",
        "ASSETS",
        "PARTNERS",
        "GLOBAL INVESTORS",
        "MANAGEMENT, LLC",
        "& CO.",
        "GROUP, INC.",
        "DODGE & COX",
        "SCHWAB",
    )

    def looks_like_am(name: str) -> bool:
        if not isinstance(name, str):
            return False
        upper = name.upper()
        return any(kw in upper for kw in keywords)

    only13f["am_heuristic"] = only13f["top_parent_canonical_name"].apply(looks_like_am)
    am_candidates = only13f[only13f["am_heuristic"]].copy()
    print(
        f"  Asset-manager-looking 13F_only top-parents (top-100 only): {len(am_candidates):,}"
    )

    # For each, check fund_holdings_v2 trace via rollup graph
    con.register("fund_to_tp_df", fund_to_tp)

    trace_sql = f"""
    SELECT ftp.top_parent_entity_id AS top_parent_entity_id,
           COUNT(*) AS n_rows,
           SUM(fh.market_value_usd) / 1e9 AS fund_tier_trace_aum_b,
           COUNT(DISTINCT fh.fund_cik) AS n_funds
    FROM fund_holdings_v2 fh
    JOIN fund_to_tp_df ftp ON ftp.fund_entity_id = fh.entity_id
    WHERE fh.is_latest
      AND fh.quarter = '{COVERAGE_QUARTER}'
      AND fh.asset_category = 'EC'
    GROUP BY 1
    """
    trace = con.execute(trace_sql).fetchdf()
    am_candidates = am_candidates.merge(
        trace, left_on="top_parent_entity_id", right_on="top_parent_entity_id", how="left"
    )
    am_candidates["fund_tier_trace_aum_b"] = am_candidates["fund_tier_trace_aum_b"].fillna(0)
    am_candidates["n_rows"] = am_candidates["n_rows"].fillna(0).astype(int)
    am_candidates["n_funds"] = am_candidates["n_funds"].fillna(0).astype(int)

    am_candidates["category"] = am_candidates.apply(
        lambda r: (
            "B_rollup_gap"
            if r["fund_tier_trace_aum_b"] > 0
            else "A_genuine_13F_only_or_C_loader_gap"
        ),
        axis=1,
    )

    print("\n  Asset-manager-looking 13F_only top-parents — categorization:")
    cols = [
        "top_parent_entity_id",
        "top_parent_canonical_name",
        "thirteen_f_aum_billions",
        "n_funds",
        "fund_tier_trace_aum_b",
        "category",
    ]
    print(am_candidates[cols].to_string(index=False))

    am_candidates.to_csv(WORKDIR / "cp-5-bundle-a-13f-only-anomalies.csv", index=False)
    print(f"\n  Wrote cp-5-bundle-a-13f-only-anomalies.csv")

    # Sub-probe 1.3-bis: Schwab (eid 5) + Dodge & Cox (eid 15) (top_parent,
    # ticker)-pair behavior. The cp-5-discovery's Phase 2 surfaced these by
    # name as showing 13F_only behavior despite known fund footprints; here
    # we verify against current rollup state.
    print(
        "\n  Sub-probe — Schwab (eid 5) + Dodge & Cox (eid 15) "
        "(top_parent, ticker) pairs:"
    )
    sub_sql = f"""
    WITH thirteenf AS (
      SELECT itp.top_parent_entity_id, h.ticker, h.cusip,
             SUM(h.market_value_usd) / 1e9 AS thirteen_f_aum_b
      FROM holdings_v2 h
      JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
      WHERE h.is_latest
        AND h.quarter = '{COVERAGE_QUARTER}'
        AND itp.top_parent_entity_id IN (5, 15)
        AND h.ticker IN ('AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'XOM')
      GROUP BY 1, 2, 3
    ),
    fundtier AS (
      SELECT ftp.top_parent_entity_id, fh.ticker, fh.cusip,
             SUM(fh.market_value_usd) / 1e9 AS fund_tier_aum_b
      FROM fund_holdings_v2 fh
      JOIN fund_to_tp_df ftp ON ftp.fund_entity_id = fh.entity_id
      WHERE fh.is_latest
        AND fh.quarter = '{COVERAGE_QUARTER}'
        AND fh.asset_category = 'EC'
        AND ftp.top_parent_entity_id IN (5, 15)
        AND fh.ticker IN ('AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'XOM')
      GROUP BY 1, 2, 3
    )
    SELECT COALESCE(t.top_parent_entity_id, f.top_parent_entity_id) AS top_parent,
           COALESCE(t.ticker, f.ticker) AS ticker,
           COALESCE(t.thirteen_f_aum_b, 0) AS thirteen_f_aum_b,
           COALESCE(f.fund_tier_aum_b, 0) AS fund_tier_aum_b
    FROM thirteenf t
    FULL OUTER JOIN fundtier f
      ON t.top_parent_entity_id = f.top_parent_entity_id
     AND t.ticker = f.ticker AND t.cusip = f.cusip
    ORDER BY top_parent, ticker
    """
    con.register("inst_to_tp_df", inst_to_tp)
    sub = con.execute(sub_sql).fetchdf()
    print(sub.to_string(index=False))

    return am_candidates


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    print("Building inst_to_tp + fund_to_tp maps...")
    inst_to_tp = build_inst_to_tp(con)
    fund_to_tp = build_fund_to_tp(con, inst_to_tp)
    print(
        f"  inst_to_tp rows: {len(inst_to_tp):,}; "
        f"fund_to_tp rows (with resolved tp): "
        f"{fund_to_tp['top_parent_entity_id'].notna().sum():,} of {len(fund_to_tp):,}"
    )

    probe_1_1_fof(con, fund_to_tp)
    probe_1_2_null_cusip(con)
    probe_1_3_13f_only(con, inst_to_tp, fund_to_tp)

    print("\n" + "=" * 72)
    print("Probe 1 complete.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
