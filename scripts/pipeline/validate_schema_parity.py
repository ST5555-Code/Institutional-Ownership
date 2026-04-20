#!/usr/bin/env python3
"""
Schema parity validator: prod vs staging L3 tables.

Pre-flight gate for Phase 2 staging validation. Detects schema drift across
columns, indexes, constraints, and table DDL. Exits non-zero on unaccepted
divergence. Accept-list lets known drift through with justification + expiry.

Precedent: pct-of-so Phase 4 prod apply aborted on DependencyException because
staging had 0 indexes on holdings_v2 while prod had 4 (`docs/REWRITE_PCT_OF_SO_
PERIOD_ACCURACY_FINDINGS.md` §14.0). This check would have caught that
divergence before Phase 4 ever started.

Usage:
    python3 scripts/pipeline/validate_schema_parity.py [options]

Exit codes:
    0 — parity; or all divergences accepted (without --fail-on-accepted)
    1 — unaccepted divergence or expired accept-list entry
    2 — invocation error (missing file, bad YAML, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

try:
    import duckdb  # type: ignore[import-not-found]
except ImportError:
    duckdb = None  # allow unit tests to exercise comparator logic without duckdb

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:
    yaml = None  # accept-list loader guards on this

# ---------------------------------------------------------------------------
# L3 table inventory (Phase 0 §1 — aligned with docs/data_layers.md §2)
# ---------------------------------------------------------------------------

L3_TABLES: list[str] = [
    # Entity MDM core (7)
    "entities",
    "entity_identifiers",
    "entity_relationships",
    "entity_aliases",
    "entity_classification_history",
    "entity_rollup_history",
    "entity_overrides_persistent",
    # Entity MDM additional (6)
    "cik_crd_direct",
    "cik_crd_links",
    "lei_reference",
    "other_managers",
    "parent_bridge",
    "fetched_tickers_13dg",
    "listed_filings_13dg",
    # Reference / other L3 (11)
    "securities",
    "market_data",
    "short_interest",
    "fund_universe",
    "shares_outstanding_history",
    "adv_managers",
    "ncen_adviser_map",
    "filings",
    "filings_deduped",
    "cusip_classifications",
    "_cache_openfigi",
    # Core facts (3)
    "beneficial_ownership_v2",
    "fund_holdings_v2",
    "holdings_v2",
    # Staging companions (2) — L3-adjacent soft-landing queues
    "entity_identifiers_staging",
    "entity_relationships_staging",
]

DIMENSIONS: list[str] = ["columns", "indexes", "constraints", "ddl"]

DEFAULT_PROD_DB = "data/13f.duckdb"
DEFAULT_STAGING_DB = "data/13f_staging.duckdb"
DEFAULT_ACCEPT_LIST = "config/schema_parity_accept.yaml"


def get_l3_tables() -> list[str]:
    """Return the canonical L3 table list."""
    return list(L3_TABLES)


# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------


@dataclass
class Divergence:
    table: str
    dimension: str
    detail: str
    prod_value: Any = None
    staging_value: Any = None

    def key(self) -> tuple[str, str, str]:
        return (self.table.lower(), self.dimension.lower(), self.detail.lower())


@dataclass
class AcceptEntry:
    table: str
    dimension: str
    detail: str
    justification: str
    reviewer: str
    expiry_date: Optional[str] = None
    _source_idx: int = -1

    def key(self) -> tuple[str, str, str]:
        return (self.table.lower(), self.dimension.lower(), self.detail.lower())

    def is_expired(self, today: Optional[date] = None) -> bool:
        if not self.expiry_date:
            return False
        today = today or date.today()
        raw = self.expiry_date
        if isinstance(raw, date):
            exp = raw
        else:
            try:
                exp = date.fromisoformat(str(raw))
            except ValueError as exc:
                raise ValueError(
                    f"accept-list entry for {self.table}/{self.dimension}/{self.detail}: "
                    f"expiry_date {raw!r} is not ISO format"
                ) from exc
        return today >= exp


# ---------------------------------------------------------------------------
# Introspection (DuckDB-specific)
# ---------------------------------------------------------------------------


def _filtered_query(base_select: str, base_from: str) -> str:
    return (
        f"{base_select} FROM {base_from} "
        "WHERE database_name = current_database() "
        "AND schema_name = 'main' AND table_name = ?"
    )


def introspect_columns(con, table: str) -> list[dict]:
    sql = _filtered_query(
        "SELECT column_name, data_type, is_nullable, column_default, column_index",
        "duckdb_columns()",
    ) + " ORDER BY column_index"
    rows = con.execute(sql, [table]).fetchall()
    return [
        {
            "column_name": r[0],
            "data_type": r[1],
            "is_nullable": bool(r[2]),
            "column_default": r[3],
            "column_index": r[4],
        }
        for r in rows
    ]


def introspect_indexes(con, table: str) -> list[dict]:
    sql = _filtered_query(
        "SELECT index_name, is_unique, is_primary, sql",
        "duckdb_indexes()",
    ) + " ORDER BY index_name"
    rows = con.execute(sql, [table]).fetchall()
    return [
        {
            "index_name": r[0],
            "is_unique": bool(r[1]),
            "is_primary": bool(r[2]),
            "sql": r[3] or "",
        }
        for r in rows
    ]


def introspect_constraints(con, table: str) -> list[dict]:
    sql = _filtered_query(
        "SELECT constraint_type, constraint_text",
        "duckdb_constraints()",
    ) + " ORDER BY constraint_type, constraint_text"
    rows = con.execute(sql, [table]).fetchall()
    return [{"constraint_type": r[0], "constraint_text": r[1]} for r in rows]


def introspect_ddl(con, table: str) -> str:
    sql = _filtered_query("SELECT sql", "duckdb_tables()")
    row = con.execute(sql, [table]).fetchone()
    if not row or not row[0]:
        return ""
    return row[0]


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_ddl_whitespace(ddl: str) -> str:
    """Collapse whitespace; trim; normalize line endings. Conservative."""
    if not ddl:
        return ""
    s = ddl.replace("\r\n", "\n").replace("\r", "\n").strip()
    s = _WHITESPACE_RE.sub(" ", s)
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


_PK_COLS_RE = re.compile(r"PRIMARY\s+KEY\s*\(\s*([^)]+)\)", re.IGNORECASE)
_INDEX_COLS_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+\S+\s+ON\s+\S+\s*\(\s*([^)]+)\)",
    re.IGNORECASE,
)


def _split_cols(cols_str: str) -> tuple[str, ...]:
    """Split column list from PK or CREATE INDEX body; lower-case, dequote."""
    parts = [p.strip().strip('"').strip("'").lower() for p in cols_str.split(",")]
    return tuple(p for p in parts if p)


def _pk_columns_from_constraint(ct: str) -> Optional[tuple[str, ...]]:
    m = _PK_COLS_RE.search(ct or "")
    if not m:
        return None
    return _split_cols(m.group(1))


def _index_columns_from_sql(sql: str) -> Optional[tuple[str, ...]]:
    m = _INDEX_COLS_RE.search(sql or "")
    if not m:
        return None
    return _split_cols(m.group(1))


def normalize_pk_index_equivalence(
    prod_constraints: list[dict],
    prod_indexes: list[dict],
    staging_constraints: list[dict],
    staging_indexes: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """If one side expresses uniqueness as a PK constraint and the other side
    expresses the same uniqueness as a UNIQUE non-primary index on identical
    columns, drop both the PK row and the UNIQUE index row on each side so they
    don't surface as spurious divergences.

    Conservative: only pairs PK↔UNIQUE-INDEX when column sets match exactly (order-free).
    """
    def pk_col_sets(constraints):
        return {
            frozenset(cols)
            for c in constraints
            if c.get("constraint_type") == "PRIMARY KEY"
            for cols in [_pk_columns_from_constraint(c.get("constraint_text", ""))]
            if cols
        }

    def unique_nonpk_index_col_sets(indexes):
        sets = {}
        for idx in indexes:
            if not idx.get("is_unique") or idx.get("is_primary"):
                continue
            cols = _index_columns_from_sql(idx.get("sql", ""))
            if cols:
                sets[frozenset(cols)] = idx.get("index_name")
        return sets

    prod_pk_sets = pk_col_sets(prod_constraints)
    stg_pk_sets = pk_col_sets(staging_constraints)
    prod_uniq = unique_nonpk_index_col_sets(prod_indexes)
    stg_uniq = unique_nonpk_index_col_sets(staging_indexes)

    # Case A: prod has PK, staging has matching UNIQUE index (no PK)
    pairs_a = [cols for cols in prod_pk_sets if cols in stg_uniq and cols not in stg_pk_sets]
    # Case B: staging has PK, prod has matching UNIQUE index (no PK)
    pairs_b = [cols for cols in stg_pk_sets if cols in prod_uniq and cols not in prod_pk_sets]

    if not pairs_a and not pairs_b:
        return prod_constraints, prod_indexes, staging_constraints, staging_indexes

    def filter_pk(constraints, cols_to_drop):
        out = []
        for c in constraints:
            if c.get("constraint_type") == "PRIMARY KEY":
                cols = _pk_columns_from_constraint(c.get("constraint_text", ""))
                if cols and frozenset(cols) in cols_to_drop:
                    continue
            out.append(c)
        return out

    def filter_uniq_idx(indexes, cols_to_drop):
        out = []
        for idx in indexes:
            if idx.get("is_unique") and not idx.get("is_primary"):
                cols = _index_columns_from_sql(idx.get("sql", ""))
                if cols and frozenset(cols) in cols_to_drop:
                    continue
            out.append(idx)
        return out

    prod_c = filter_pk(prod_constraints, set(pairs_a))
    stg_c = filter_pk(staging_constraints, set(pairs_b))
    stg_i = filter_uniq_idx(staging_indexes, set(pairs_a))
    prod_i = filter_uniq_idx(prod_indexes, set(pairs_b))
    return prod_c, prod_i, stg_c, stg_i


def dedupe_not_null_constraint(constraints: list[dict]) -> list[dict]:
    """Drop bare NOT NULL rows from duckdb_constraints — they duplicate
    is_nullable=False in duckdb_columns and have no column identity, making
    them unmatchable at the dimension-detail level."""
    return [c for c in constraints if c.get("constraint_type") != "NOT NULL"]


# ---------------------------------------------------------------------------
# Comparators
# ---------------------------------------------------------------------------


def compare_columns(
    prod_cols: list[dict], staging_cols: list[dict], table: str
) -> list[Divergence]:
    out: list[Divergence] = []
    prod_by = {c["column_name"].lower(): c for c in prod_cols}
    stg_by = {c["column_name"].lower(): c for c in staging_cols}
    all_names = sorted(set(prod_by) | set(stg_by))
    for name in all_names:
        p = prod_by.get(name)
        s = stg_by.get(name)
        display = (p or s)["column_name"]
        if p is None:
            out.append(Divergence(table, "columns", display, None, s))
            continue
        if s is None:
            out.append(Divergence(table, "columns", display, p, None))
            continue
        diff_fields = {}
        for field_name in ("data_type", "is_nullable", "column_default", "column_index"):
            if p.get(field_name) != s.get(field_name):
                diff_fields[field_name] = (p.get(field_name), s.get(field_name))
        if diff_fields:
            out.append(Divergence(
                table, "columns", display,
                {"column": p, "diffs": diff_fields},
                {"column": s, "diffs": diff_fields},
            ))
    return out


def compare_indexes(
    prod_idx: list[dict], staging_idx: list[dict], table: str
) -> list[Divergence]:
    out: list[Divergence] = []
    prod_by = {i["index_name"].lower(): i for i in prod_idx}
    stg_by = {i["index_name"].lower(): i for i in staging_idx}
    all_names = sorted(set(prod_by) | set(stg_by))
    for name in all_names:
        p = prod_by.get(name)
        s = stg_by.get(name)
        display = (p or s)["index_name"]
        if p is None or s is None:
            out.append(Divergence(table, "indexes", display, p, s))
            continue
        p_sql = normalize_ddl_whitespace(p.get("sql", ""))
        s_sql = normalize_ddl_whitespace(s.get("sql", ""))
        diffs: dict[str, tuple] = {}
        for fld in ("is_unique", "is_primary"):
            if p.get(fld) != s.get(fld):
                diffs[fld] = (p.get(fld), s.get(fld))
        if p_sql != s_sql:
            diffs["sql"] = (p_sql, s_sql)
        if diffs:
            out.append(Divergence(table, "indexes", display, p, s))
    return out


def compare_constraints(
    prod_c: list[dict], staging_c: list[dict], table: str
) -> list[Divergence]:
    """Compare constraints after NOT NULL dedupe + PK↔UNIQUE-index normalization
    (both applied by caller). Match by (type, text)."""
    out: list[Divergence] = []

    def keyset(constraints):
        return [(c["constraint_type"], c["constraint_text"]) for c in constraints]

    prod_set = keyset(prod_c)
    stg_set = keyset(staging_c)
    # For stable ordering, sort the symmetric diff
    for item in sorted(set(prod_set) - set(stg_set)):
        out.append(Divergence(
            table, "constraints", f"{item[0]}:{item[1]}", item, None
        ))
    for item in sorted(set(stg_set) - set(prod_set)):
        out.append(Divergence(
            table, "constraints", f"{item[0]}:{item[1]}", None, item
        ))
    return out


def compare_ddl(prod_ddl: str, staging_ddl: str, table: str) -> list[Divergence]:
    p = normalize_ddl_whitespace(prod_ddl)
    s = normalize_ddl_whitespace(staging_ddl)
    if p == s:
        return []
    return [Divergence(table, "ddl", "CREATE TABLE", p, s)]


def compare_table(
    prod_con,
    staging_con,
    table: str,
    dimensions: list[str],
) -> list[Divergence]:
    """Run all requested dimensions for one table, with normalizers applied
    before comparators so cross-dimension equivalences are collapsed."""
    divs: list[Divergence] = []

    prod_cols = introspect_columns(prod_con, table)
    stg_cols = introspect_columns(staging_con, table)

    prod_idx = introspect_indexes(prod_con, table)
    stg_idx = introspect_indexes(staging_con, table)

    prod_c_raw = introspect_constraints(prod_con, table)
    stg_c_raw = introspect_constraints(staging_con, table)

    # Dedupe NOT NULL cross-dimension
    prod_c = dedupe_not_null_constraint(prod_c_raw)
    stg_c = dedupe_not_null_constraint(stg_c_raw)

    # Normalize PK ↔ UNIQUE-index equivalence (both sides)
    prod_c, prod_idx, stg_c, stg_idx = normalize_pk_index_equivalence(
        prod_c, prod_idx, stg_c, stg_idx
    )

    if "columns" in dimensions:
        divs.extend(compare_columns(prod_cols, stg_cols, table))
    if "indexes" in dimensions:
        divs.extend(compare_indexes(prod_idx, stg_idx, table))
    if "constraints" in dimensions:
        divs.extend(compare_constraints(prod_c, stg_c, table))
    if "ddl" in dimensions:
        prod_ddl = introspect_ddl(prod_con, table)
        stg_ddl = introspect_ddl(staging_con, table)
        divs.extend(compare_ddl(prod_ddl, stg_ddl, table))
    return divs


# ---------------------------------------------------------------------------
# Accept-list
# ---------------------------------------------------------------------------


_REQUIRED_ACCEPT_FIELDS = ("table", "dimension", "detail", "justification", "reviewer")


def load_accept_list(path: str) -> list[AcceptEntry]:
    if not os.path.exists(path):
        return []
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot parse accept-list")
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    raw = doc.get("accepted", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            f"accept-list {path}: 'accepted' must be a list, got {type(raw).__name__}"
        )
    entries: list[AcceptEntry] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"accept-list {path} entry {i}: must be a mapping")
        missing = [f for f in _REQUIRED_ACCEPT_FIELDS if f not in row]
        if missing:
            raise ValueError(
                f"accept-list {path} entry {i}: missing required fields: {missing}"
            )
        just = str(row["justification"]).strip()
        if len(just) < 30:
            raise ValueError(
                f"accept-list {path} entry {i}: justification must be ≥30 chars "
                "(prevents lazy 'tbd' entries)"
            )
        if row["dimension"] not in DIMENSIONS:
            raise ValueError(
                f"accept-list {path} entry {i}: dimension must be one of {DIMENSIONS}, "
                f"got {row['dimension']!r}"
            )
        entries.append(AcceptEntry(
            table=row["table"],
            dimension=row["dimension"],
            detail=str(row["detail"]),
            justification=just,
            reviewer=str(row["reviewer"]),
            expiry_date=row.get("expiry_date"),
            _source_idx=i,
        ))
    return entries


def match_accept(
    divergence: Divergence, entries: list[AcceptEntry]
) -> Optional[AcceptEntry]:
    for e in entries:
        if e.key() == divergence.key():
            return e
    return None


# ---------------------------------------------------------------------------
# Reporters
# ---------------------------------------------------------------------------


def format_human(
    divergences: list[Divergence],
    accepted: list[tuple[Divergence, AcceptEntry]],
    stale_accepts: list[AcceptEntry],
    expired_accepts: list[AcceptEntry],
    unaccepted: list[Divergence],
    fail_on_accepted: bool,
) -> str:
    lines: list[str] = []
    lines.append("═══ Schema parity report ═══")
    lines.append(f"  tables scanned  : L3 ({len(L3_TABLES)} tables inc. staging companions)")
    lines.append(f"  divergences     : {len(divergences)} total "
                 f"({len(accepted)} accepted, {len(unaccepted)} unaccepted)")
    lines.append(f"  accept-list     : {len(accepted) + len(stale_accepts) + len(expired_accepts)} entries "
                 f"({len(stale_accepts)} stale, {len(expired_accepts)} expired)")
    lines.append(f"  fail-on-accepted: {fail_on_accepted}")
    lines.append("")
    if unaccepted:
        lines.append("── UNACCEPTED DIVERGENCES ──")
        for d in unaccepted:
            lines.append(f"  [FAIL] {d.table} :: {d.dimension} :: {d.detail}")
            if d.prod_value is not None:
                lines.append(f"         prod:    {_short_repr(d.prod_value)}")
            if d.staging_value is not None:
                lines.append(f"         staging: {_short_repr(d.staging_value)}")
        lines.append("")
    if accepted:
        lines.append("── ACCEPTED DIVERGENCES (WARN) ──")
        for d, e in accepted:
            exp = f" [expires {e.expiry_date}]" if e.expiry_date else ""
            lines.append(f"  [WARN] {d.table} :: {d.dimension} :: {d.detail}{exp}")
            lines.append(f"         {e.justification.splitlines()[0][:100]}")
        lines.append("")
    if expired_accepts:
        lines.append("── EXPIRED ACCEPT-LIST ENTRIES ──")
        for e in expired_accepts:
            lines.append(f"  [FAIL] expired {e.expiry_date}: {e.table} :: {e.dimension} :: {e.detail}")
        lines.append("")
    if stale_accepts:
        lines.append("── STALE ACCEPT-LIST ENTRIES (no matching divergence) ──")
        for e in stale_accepts:
            lines.append(f"  [WARN] stale: {e.table} :: {e.dimension} :: {e.detail}")
        lines.append("")
    if not divergences and not expired_accepts:
        lines.append("✓ PARITY — no unaccepted divergences")
    elif not unaccepted and not expired_accepts:
        lines.append("✓ PARITY — all divergences accepted")
    else:
        lines.append("✗ FAIL — unaccepted divergences present")
    return "\n".join(lines)


def _short_repr(val: Any, limit: int = 180) -> str:
    s = repr(val)
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def format_json(
    divergences: list[Divergence],
    accepted: list[tuple[Divergence, AcceptEntry]],
    stale_accepts: list[AcceptEntry],
    expired_accepts: list[AcceptEntry],
    unaccepted: list[Divergence],
    fail_on_accepted: bool,
) -> dict:
    def div_to_dict(d: Divergence) -> dict:
        return {
            "table": d.table,
            "dimension": d.dimension,
            "detail": d.detail,
            "prod_value": _jsonify(d.prod_value),
            "staging_value": _jsonify(d.staging_value),
        }
    accepted_pairs = [
        {"divergence": div_to_dict(d), "accept_entry": _accept_entry_dict(e)}
        for d, e in accepted
    ]
    return {
        "summary": {
            "total": len(divergences),
            "accepted": len(accepted),
            "unaccepted": len(unaccepted),
            "stale_accepts": len(stale_accepts),
            "expired_accepts": len(expired_accepts),
            "fail_on_accepted": fail_on_accepted,
            "verdict": "PARITY" if (not unaccepted and not expired_accepts) else "FAIL",
        },
        "divergences": [div_to_dict(d) for d in divergences],
        "unaccepted": [div_to_dict(d) for d in unaccepted],
        "accepted": accepted_pairs,
        "stale_accepts": [_accept_entry_dict(e) for e in stale_accepts],
        "expired_accepts": [_accept_entry_dict(e) for e in expired_accepts],
    }


def _jsonify(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, dict):
        return {k: _jsonify(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_jsonify(v) for v in val]
    return str(val)


def _accept_entry_dict(e: AcceptEntry) -> dict:
    d = asdict(e)
    d.pop("_source_idx", None)
    return d


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    prod_path: str,
    staging_path: str,
    tables: list[str],
    dimensions: list[str],
    accept_list_path: str,
    fail_on_accepted: bool,
    verbose: bool = False,
) -> tuple[int, dict]:
    """Execute the parity check. Returns (exit_code, report_dict).

    Report is the JSON payload; human text is derived from it via format_human.
    """
    if duckdb is None:
        print("ERROR: duckdb not installed", file=sys.stderr)
        return 2, {}

    for p, label in ((prod_path, "prod"), (staging_path, "staging")):
        if not os.path.exists(p):
            print(f"ERROR: {label} DB missing: {p}", file=sys.stderr)
            return 2, {}

    try:
        accept_list = load_accept_list(accept_list_path)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: accept-list {accept_list_path}: {exc}", file=sys.stderr)
        return 2, {}

    # Expired entries — identify before scanning
    expired: list[AcceptEntry] = []
    try:
        for e in accept_list:
            if e.is_expired():
                expired.append(e)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2, {}

    prod_con = duckdb.connect(prod_path, read_only=True)
    staging_con = duckdb.connect(staging_path, read_only=True)

    all_divergences: list[Divergence] = []
    try:
        for t in tables:
            if verbose:
                print(f"  scanning {t}", file=sys.stderr, flush=True)
            all_divergences.extend(compare_table(prod_con, staging_con, t, dimensions))
    finally:
        prod_con.close()
        staging_con.close()

    # Match against accept-list
    accepted_pairs: list[tuple[Divergence, AcceptEntry]] = []
    unaccepted: list[Divergence] = []
    matched_entry_keys: set[tuple[str, str, str]] = set()
    for d in all_divergences:
        e = match_accept(d, accept_list)
        if e is None:
            unaccepted.append(d)
        else:
            accepted_pairs.append((d, e))
            matched_entry_keys.add(e.key())

    # Stale accept-list entries (no matching divergence, and not expired)
    stale = [e for e in accept_list if e.key() not in matched_entry_keys and e not in expired]

    # Decide exit code
    if fail_on_accepted and accepted_pairs:
        exit_code = 1
    elif unaccepted or expired:
        exit_code = 1
    else:
        exit_code = 0

    report = format_json(
        all_divergences, accepted_pairs, stale, expired, unaccepted, fail_on_accepted
    )
    return exit_code, report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate schema parity between prod and staging L3 tables"
    )
    parser.add_argument("--prod", default=DEFAULT_PROD_DB, help="Prod DB path")
    parser.add_argument("--staging", default=DEFAULT_STAGING_DB, help="Staging DB path")
    parser.add_argument(
        "--tables",
        default=None,
        help="Comma-separated table subset (default: all L3)",
    )
    parser.add_argument(
        "--dimensions",
        default=",".join(DIMENSIONS),
        help=f"Comma-separated dimensions (choices: {','.join(DIMENSIONS)})",
    )
    parser.add_argument("--accept-list", default=DEFAULT_ACCEPT_LIST)
    parser.add_argument(
        "--fail-on-accepted",
        action="store_true",
        help="Treat accepted divergences as failures (CI drift-hardening mode)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    # Resolve defaults relative to repo root
    def _resolve(path: str) -> str:
        if os.path.isabs(path):
            return path
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(root, path)

    prod_path = _resolve(args.prod)
    staging_path = _resolve(args.staging)
    accept_list_path = _resolve(args.accept_list)

    tables = get_l3_tables()
    if args.tables:
        requested = [t.strip() for t in args.tables.split(",") if t.strip()]
        unknown = [t for t in requested if t not in L3_TABLES]
        if unknown:
            print(f"ERROR: unknown tables: {unknown}", file=sys.stderr)
            return 2
        tables = requested

    dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    bad_dims = [d for d in dimensions if d not in DIMENSIONS]
    if bad_dims:
        print(f"ERROR: unknown dimensions: {bad_dims}", file=sys.stderr)
        return 2

    exit_code, report = run(
        prod_path=prod_path,
        staging_path=staging_path,
        tables=tables,
        dimensions=dimensions,
        accept_list_path=accept_list_path,
        fail_on_accepted=args.fail_on_accepted,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        # Reconstruct typed lists for format_human from report
        # (simpler: re-run orchestration-returned objects — but run() throws them away)
        # We recompute the human formatter from stored fields
        print(_human_from_report(report))
    return exit_code


def _human_from_report(report: dict) -> str:
    """Render human output from the JSON report shape (keeps format_human
    decoupled from Divergence objects for reuse)."""
    if not report:
        return ""
    summary = report.get("summary", {})
    lines = []
    lines.append("═══ Schema parity report ═══")
    lines.append(f"  tables scanned  : L3 ({len(L3_TABLES)} tables inc. staging companions)")
    lines.append(f"  divergences     : {summary.get('total', 0)} total "
                 f"({summary.get('accepted', 0)} accepted, "
                 f"{summary.get('unaccepted', 0)} unaccepted)")
    lines.append(f"  accept-list     : "
                 f"{summary.get('accepted', 0) + summary.get('stale_accepts', 0) + summary.get('expired_accepts', 0)} entries "
                 f"({summary.get('stale_accepts', 0)} stale, "
                 f"{summary.get('expired_accepts', 0)} expired)")
    lines.append(f"  fail-on-accepted: {summary.get('fail_on_accepted', False)}")
    lines.append("")
    unaccepted = report.get("unaccepted", [])
    if unaccepted:
        lines.append("── UNACCEPTED DIVERGENCES ──")
        for d in unaccepted:
            lines.append(f"  [FAIL] {d['table']} :: {d['dimension']} :: {d['detail']}")
            if d.get("prod_value") is not None:
                lines.append(f"         prod:    {_short_repr(d['prod_value'])}")
            if d.get("staging_value") is not None:
                lines.append(f"         staging: {_short_repr(d['staging_value'])}")
        lines.append("")
    for d_pair in report.get("accepted", []):
        lines_header_added = False
        if not lines_header_added:
            lines.append("── ACCEPTED DIVERGENCES (WARN) ──")
            lines_header_added = True
        d = d_pair["divergence"]
        e = d_pair["accept_entry"]
        exp = f" [expires {e['expiry_date']}]" if e.get("expiry_date") else ""
        lines.append(f"  [WARN] {d['table']} :: {d['dimension']} :: {d['detail']}{exp}")
        lines.append(f"         {e['justification'].splitlines()[0][:100]}")
    if report.get("accepted"):
        lines.append("")
    if report.get("expired_accepts"):
        lines.append("── EXPIRED ACCEPT-LIST ENTRIES ──")
        for e in report["expired_accepts"]:
            lines.append(f"  [FAIL] expired {e['expiry_date']}: {e['table']} :: {e['dimension']} :: {e['detail']}")
        lines.append("")
    if report.get("stale_accepts"):
        lines.append("── STALE ACCEPT-LIST ENTRIES (no matching divergence) ──")
        for e in report["stale_accepts"]:
            lines.append(f"  [WARN] stale: {e['table']} :: {e['dimension']} :: {e['detail']}")
        lines.append("")
    verdict = summary.get("verdict", "UNKNOWN")
    if verdict == "PARITY":
        if summary.get("accepted", 0) > 0:
            lines.append("✓ PARITY — all divergences accepted")
        else:
            lines.append("✓ PARITY — no unaccepted divergences")
    else:
        lines.append("✗ FAIL — unaccepted divergences present")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
