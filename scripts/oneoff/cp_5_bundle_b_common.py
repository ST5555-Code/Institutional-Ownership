"""CP-5 Bundle B — shared read-only helpers.

Mirrors `cp_5_bundle_a_probe1_r5_defects.py` conventions: cycle-safe inst→top-parent
climb (control_type IN ('control','mutual','merge')), fund→top-parent via
entity_rollup_history (rollup_type='decision_maker_v1'), brand-stem normalization
for fund-of-fund detection.

Read-only. No DB writes. No view creation.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
COVERAGE_QUARTER = "2025Q4"
ROLLUP_CTRL_TYPES = ("control", "mutual", "merge")
WORKDIR = Path("data/working")

# Brand-stem stopwords — copied from probe1; centralized here for reuse.
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


def brand_stem(name: str | None) -> str | None:
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


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DB_PATH, read_only=True)


def build_inst_to_tp(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cycle-safe inst→top-parent climb. Returns (entity_id, top_parent_entity_id, hops)."""
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
    hops = {eid: 0 for eid in cur}
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
            hops[ent] += 1
            changed += 1
        if changed == 0:
            break
    df = pd.DataFrame(
        {
            "entity_id": list(cur.keys()),
            "top_parent_entity_id": list(cur.values()),
            "hops": [hops[e] for e in cur.keys()],
            "cycle_truncated": [e in cycles for e in cur.keys()],
        }
    )
    return df


def build_fund_to_tp(
    con: duckdb.DuckDBPyConnection, inst_to_tp: pd.DataFrame
) -> pd.DataFrame:
    fund_chain = con.execute(f"""
        SELECT erh.entity_id AS fund_entity_id,
               erh.rollup_entity_id AS institution_entity_id
        FROM entity_rollup_history erh
        JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
        WHERE erh.valid_to = {SENTINEL}
          AND ec_f.entity_type = 'fund'
          AND erh.rollup_type = 'decision_maker_v1'
    """).fetchdf()
    return fund_chain.merge(
        inst_to_tp[["entity_id", "top_parent_entity_id"]].rename(
            columns={"entity_id": "institution_entity_id"}
        ),
        on="institution_entity_id",
        how="left",
    )


def display_name_map(con: duckdb.DuckDBPyConnection) -> dict[int, str]:
    df = con.execute(
        "SELECT entity_id, display_name FROM entity_current"
    ).fetchdf()
    return dict(zip(df["entity_id"], df["display_name"]))
