"""Phase 4: probe signals A-E for the 3,852 ECH unknown cohort.

Read-only. Builds a per-entity signal table and emits hit-rate aggregates.

  Signal A — adv_managers ADV registration (via crd identifier).
  Signal B — N-CEN role (adviser_crd matching).
  Signal C — name-pattern keyword match.
  Signal D — holdings_v2.manager_type fallback (D4 elevated).
  Signal E — holdings_v2.entity_type fallback.

Builds the join table once into a temp view and queries it. Persists per-entity
table to a temp table for Phase 5 consumption (kept in memory, not on disk).
"""
import duckdb
from pathlib import Path

DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
SENTINEL = "DATE '9999-12-31'"

# Keyword groups (extends PR #200 Tier 4 spec per user prompt).
ACTIVE_KW = [
    "CEF", "Closed-End", "Closed End", "Interval", "Municipal", "BDC",
    "Business Development", "Income Fund", "Trust", "MuniYield", "Private",
    "Opportunity", "High Yield", "High Income",
]
PASSIVE_KW = [
    "SPDR", "iShares", "Vanguard", "ETF", "Index", "Powershares",
    "Direxion", "ProShares", "ProFund",
]
HEDGE_KW = ["LP", "L.P.", "L P "]


def kw_match_clause(col: str, words: list[str], label: str) -> str:
    """Build a CASE expression returning label when any word matches col, else NULL."""
    conds = " OR ".join(f"UPPER({col}) LIKE UPPER('%{w}%')" for w in words)
    return f"CASE WHEN {conds} THEN '{label}' ELSE NULL END"


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    # Build the per-entity probe table (no writes — pure SELECT).
    sql = f"""
    WITH cohort AS (
        SELECT h.entity_id, COALESCE(h.source, '<NULL>') AS ech_source
        FROM entity_classification_history h
        WHERE h.classification='unknown' AND h.valid_to = {SENTINEL}
    ),
    cohort_meta AS (
        SELECT
            c.entity_id,
            c.ech_source,
            e.canonical_name,
            e.entity_type,
            e.created_source
        FROM cohort c
        JOIN entities e ON e.entity_id = c.entity_id
    ),
    crd_map AS (
        SELECT entity_id, identifier_value AS crd
        FROM entity_identifiers
        WHERE identifier_type='crd' AND valid_to = {SENTINEL}
    ),
    cik_map AS (
        SELECT entity_id, identifier_value AS cik
        FROM entity_identifiers
        WHERE identifier_type='cik' AND valid_to = {SENTINEL}
    ),
    -- Signal A: ADV registration
    sig_a AS (
        SELECT
            cm.entity_id,
            BOOL_OR(am.crd_number IS NOT NULL) AS hit,
            ANY_VALUE(am.strategy_inferred) AS strategy_inferred,
            BOOL_OR(am.has_hedge_funds = 'Y' OR am.has_pe_funds = 'Y' OR am.has_vc_funds = 'Y') AS has_pooled
        FROM cohort_meta cm
        LEFT JOIN crd_map ON crd_map.entity_id = cm.entity_id
        LEFT JOIN adv_managers am ON am.crd_number = crd_map.crd
        GROUP BY cm.entity_id
    ),
    -- Signal B: N-CEN role
    sig_b AS (
        SELECT
            cm.entity_id,
            BOOL_OR(nm.adviser_crd IS NOT NULL) AS hit,
            ANY_VALUE(nm.role) AS ncen_role
        FROM cohort_meta cm
        LEFT JOIN crd_map ON crd_map.entity_id = cm.entity_id
        LEFT JOIN ncen_adviser_map nm
            ON nm.adviser_crd = crd_map.crd AND nm.valid_to = {SENTINEL}
        GROUP BY cm.entity_id
    ),
    -- Signal C: name-pattern
    sig_c AS (
        SELECT
            entity_id,
            COALESCE(
                {kw_match_clause('canonical_name', PASSIVE_KW, 'passive')},
                {kw_match_clause('canonical_name', ACTIVE_KW, 'active')},
                {kw_match_clause('canonical_name', HEDGE_KW, 'hedge_fund_candidate')}
            ) AS kw_label
        FROM cohort_meta
    ),
    -- Signal D & E: holdings_v2 fallback
    sig_de AS (
        SELECT
            entity_id,
            ANY_VALUE(manager_type) AS mgr_type,
            ANY_VALUE(entity_type)  AS h_entity_type,
            COUNT(*) AS h_rows
        FROM holdings_v2
        WHERE is_latest
        GROUP BY entity_id
    )
    SELECT
        cm.entity_id,
        cm.canonical_name,
        cm.entity_type,
        cm.ech_source,
        cm.created_source,
        a.hit                AS sig_a_hit,
        a.strategy_inferred  AS sig_a_strategy,
        a.has_pooled         AS sig_a_has_pooled,
        b.hit                AS sig_b_hit,
        b.ncen_role          AS sig_b_role,
        c.kw_label           AS sig_c_label,
        (c.kw_label IS NOT NULL) AS sig_c_hit,
        (de.entity_id IS NOT NULL) AS sig_d_hit,
        de.mgr_type          AS sig_d_mgr_type,
        (de.entity_id IS NOT NULL) AS sig_e_hit,
        de.h_entity_type     AS sig_e_h_entity_type,
        de.h_rows            AS sig_de_rows
    FROM cohort_meta cm
    LEFT JOIN sig_a a ON a.entity_id = cm.entity_id
    LEFT JOIN sig_b b ON b.entity_id = cm.entity_id
    LEFT JOIN sig_c c ON c.entity_id = cm.entity_id
    LEFT JOIN sig_de de ON de.entity_id = cm.entity_id
    """
    df = con.execute(sql).fetch_df()
    print(f"PHASE 4 — signal probes: {len(df):,} rows\n")

    # Aggregate: signal hit rates
    print("(a) signal hit rates:")
    for sig in ("sig_a_hit", "sig_b_hit", "sig_c_hit", "sig_d_hit"):
        n_hit = int(df[sig].fillna(False).sum())
        print(f"  {sig:<12s}: {n_hit:>5,} / {len(df):,}  ({n_hit/len(df):.1%})")

    print("\n(b) Signal A — adv_strategy_inferred breakdown (within hits):")
    print(df[df["sig_a_hit"].fillna(False)]["sig_a_strategy"].fillna("<NULL>").value_counts().to_string())

    print("\n(c) Signal B — role breakdown (within hits):")
    print(df[df["sig_b_hit"].fillna(False)]["sig_b_role"].fillna("<NULL>").value_counts().to_string())

    print("\n(d) Signal C — keyword label breakdown:")
    print(df["sig_c_label"].fillna("<no_match>").value_counts().to_string())

    print("\n(e) Signal D — manager_type breakdown (within hits):")
    print(df[df["sig_d_hit"].fillna(False)]["sig_d_mgr_type"].fillna("<NULL>").value_counts().to_string())

    print("\n(f) any-signal coverage:")
    any_hit = (df["sig_a_hit"].fillna(False) | df["sig_b_hit"].fillna(False)
               | df["sig_c_hit"].fillna(False) | df["sig_d_hit"].fillna(False))
    no_hit = ~any_hit
    print(f"  >=1 signal hit: {int(any_hit.sum()):,}  ({any_hit.mean():.1%})")
    print(f"  zero signals:   {int(no_hit.sum()):,}  ({no_hit.mean():.1%})")

    # Persist to parquet for Phase 5 consumption (it's read-only output).
    out = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/nervous-faraday-6ca32e/data/working/unknown-classification-signals.parquet")
    df.to_parquet(out, index=False)
    print(f"\nWrote: {out}  ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
