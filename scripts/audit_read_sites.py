"""mig-07 Mode 1 — on-demand read-site inventory audit.

Scans the codebase for SQL-like patterns (SELECT/JOIN/UPDATE/INSERT/DELETE)
and React field references (row.ticker, data.entity_id, …), then reports
which files read from which tables/columns.

Typical usage:
    python3 scripts/audit_read_sites.py                    # summary to stdout
    python3 scripts/audit_read_sites.py --table securities # filter one table
    python3 scripts/audit_read_sites.py --column ticker    # filter one column
    python3 scripts/audit_read_sites.py --csv              # write CSV report

Intended workflow: before dropping or renaming a column, run this tool to
find every read site. Mode 2 (CI gate wiring) is a future follow-on.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SqlRef:
    file: str
    line: int
    table: str
    operation: str  # SELECT | JOIN | UPDATE | INSERT | DELETE | FROM
    columns_referenced: list[str] = field(default_factory=list)
    context_snippet: str = ""


@dataclass
class ReactFieldRef:
    file: str
    line: int
    object: str   # row | data | item | record
    field: str
    context_snippet: str = ""


# ---------------------------------------------------------------------------
# SQL pattern extraction
# ---------------------------------------------------------------------------


# Match <KEYWORD> <table>; allow optional schema prefix and backticks/quotes.
_SQL_PATTERNS = [
    ("SELECT", re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)),
    ("JOIN",   re.compile(r"\bJOIN\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)),
    ("UPDATE", re.compile(r"\bUPDATE\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)),
    ("INSERT", re.compile(r"\bINSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)),
    ("DELETE", re.compile(r"\bDELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)),
]

# Words that look like identifiers but are SQL keywords — filter them out of
# any matched "table" group so "FROM WHERE" doesn't yield table=WHERE.
_SQL_KEYWORDS = {
    "where", "select", "from", "join", "on", "and", "or", "not", "null",
    "inner", "outer", "left", "right", "full", "cross", "using", "group",
    "order", "by", "having", "limit", "offset", "union", "intersect",
    "except", "as", "when", "case", "then", "else", "end", "into", "values",
    "set", "distinct", "in", "is", "like", "between", "all", "any", "exists",
    "with", "returning",
}

# Also filter SQL's own reserved words appearing in source context.
_RE_SELECT_CLAUSE = re.compile(r"SELECT\s+(.+?)\s+FROM\b", re.IGNORECASE | re.DOTALL)

# For line-number attribution, we need to find matches within a text blob
# and know which source line they start on. The approach: iterate each
# regex match in the full source and map its char offset back to a line.


def _char_to_line(src: str, offset: int) -> int:
    """Convert a character offset into a 1-based line number."""
    return src.count("\n", 0, offset) + 1


def _line_text(src: str, line_num: int) -> str:
    """Return the text of `line_num` (1-based) in `src`, stripped."""
    lines = src.splitlines()
    if 1 <= line_num <= len(lines):
        return lines[line_num - 1].strip()
    return ""


def _is_likely_comment_only(line: str) -> bool:
    """True if the line is Python-comment-only (starts with '#')."""
    s = line.lstrip()
    return s.startswith("#")


_RE_PYTHON_FROM_IMPORT = re.compile(
    r"^\s*from\s+[A-Za-z_][\w.]*\s+import\b", re.IGNORECASE,
)


def _is_python_import_line(line: str) -> bool:
    """True if the line is a Python `from X import …` statement."""
    return bool(_RE_PYTHON_FROM_IMPORT.match(line))


def extract_select_columns(src: str) -> list[str]:
    """Best-effort column extraction from the first SELECT … FROM clause.

    Returns ['*'] if star; strips table aliases and AS aliases.
    """
    m = _RE_SELECT_CLAUSE.search(src)
    if not m:
        return []
    clause = m.group(1).strip()
    if clause == "*":
        return ["*"]
    # Split on commas at top level (good enough — no nested-paren handling).
    parts = [p.strip() for p in clause.split(",")]
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        # Strip AS alias
        no_as = re.split(r"\s+AS\s+", p, flags=re.IGNORECASE)[0].strip()
        # Strip trailing alias (e.g. "h.ticker t")
        tokens = no_as.split()
        head = tokens[0] if tokens else no_as
        # Strip leading table qualifier
        if "." in head:
            head = head.rsplit(".", 1)[1]
        # Keep identifier-like tokens; drop function calls, *, etc.
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", head):
            out.append(head)
        elif head == "*":
            out.append("*")
    return out


def extract_sql_refs(src: str) -> list[SqlRef]:
    """Extract every SQL read/write reference in `src`.

    Returns a list of SqlRef — file='' (caller fills it), with line,
    table, operation, columns_referenced, and a truncated context_snippet.
    """
    refs: list[SqlRef] = []
    cols_for_select = extract_select_columns(src)

    for op, pat in _SQL_PATTERNS:
        for m in pat.finditer(src):
            table = m.group(1)
            if table.lower() in _SQL_KEYWORDS:
                continue
            line_num = _char_to_line(src, m.start())
            line_txt = _line_text(src, line_num)
            if _is_likely_comment_only(line_txt):
                continue
            if op == "SELECT" and _is_python_import_line(line_txt):
                # `from X import Y` — Python import, not SQL
                continue
            snippet = line_txt[:200]
            cols = cols_for_select if op == "SELECT" else []
            refs.append(SqlRef(
                file="", line=line_num, table=table, operation=op,
                columns_referenced=list(cols), context_snippet=snippet,
            ))
    return refs


# ---------------------------------------------------------------------------
# React field-reference extraction
# ---------------------------------------------------------------------------


_REACT_TARGET_OBJECTS = ("row", "data", "item", "record")
_RE_REACT_FIELD = re.compile(
    r"\b(" + "|".join(_REACT_TARGET_OBJECTS) + r")\.([A-Za-z_][A-Za-z0-9_]*)"
)


def extract_react_field_refs(src: str) -> list[ReactFieldRef]:
    refs: list[ReactFieldRef] = []
    for m in _RE_REACT_FIELD.finditer(src):
        obj = m.group(1)
        fld = m.group(2)
        line_num = _char_to_line(src, m.start())
        line_txt = _line_text(src, line_num)
        refs.append(ReactFieldRef(
            file="", line=line_num, object=obj, field=fld,
            context_snippet=line_txt[:200],
        ))
    return refs


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


def _iter_files(base: Path, suffixes: tuple[str, ...], skip_dirs: tuple[str, ...]) -> Iterable[Path]:
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in suffixes:
            continue
        parts = set(p.parts)
        if any(s in parts for s in skip_dirs):
            continue
        yield p


def scan_python_dir(dir_path: Path, root: Path | None = None) -> list[SqlRef]:
    """Scan all .py files under `dir_path`, skipping retired/ and __pycache__.

    `root` is used to compute the file path reported in each ref (relative
    to root when provided, else relative to dir_path).
    """
    root = root or dir_path
    out: list[SqlRef] = []
    for py in _iter_files(dir_path, (".py",), ("retired", "__pycache__")):
        try:
            src = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(py.relative_to(root)) if root in py.parents or root == py.parent else str(py)
        try:
            rel = str(py.relative_to(root))
        except ValueError:
            rel = str(py)
        for r in extract_sql_refs(src):
            r.file = rel
            out.append(r)
    return out


def scan_react_dir(dir_path: Path, root: Path | None = None) -> list[ReactFieldRef]:
    """Scan all .tsx/.ts files under `dir_path`."""
    root = root or dir_path
    out: list[ReactFieldRef] = []
    for f in _iter_files(dir_path, (".tsx", ".ts"), ("node_modules", "dist", "build")):
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            rel = str(f.relative_to(root))
        except ValueError:
            rel = str(f)
        for r in extract_react_field_refs(src):
            r.file = rel
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def filter_refs(
    refs: list[SqlRef],
    table: str | None = None,
    column: str | None = None,
) -> list[SqlRef]:
    out = refs
    if table:
        t = table.lower()
        out = [r for r in out if r.table.lower() == t]
    if column:
        c = column.lower()
        out = [r for r in out if any(col.lower() == c for col in r.columns_referenced)]
    return out


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


CSV_HEADERS = [
    "file", "line", "table", "operation",
    "columns_referenced", "context_snippet",
]


def write_csv(refs: list[SqlRef], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        w.writeheader()
        for r in refs:
            w.writerow({
                "file": r.file,
                "line": r.line,
                "table": r.table,
                "operation": r.operation,
                "columns_referenced": ";".join(r.columns_referenced),
                "context_snippet": r.context_snippet,
            })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_summary(refs: list[SqlRef], react_refs: list[ReactFieldRef]) -> None:
    """Print a table → [files] summary to stdout."""
    by_table: dict[str, set[str]] = {}
    for r in refs:
        by_table.setdefault(r.table, set()).add(r.file)

    print(f"SQL read sites — {len(refs)} refs across {len(by_table)} tables")
    print("=" * 72)
    for table in sorted(by_table.keys()):
        files = sorted(by_table[table])
        print(f"\n{table}  ({len(files)} file{'s' if len(files) != 1 else ''})")
        for f in files:
            print(f"  {f}")

    if react_refs:
        by_field: dict[str, set[str]] = {}
        for rr in react_refs:
            by_field.setdefault(rr.field, set()).add(rr.file)
        print()
        print(f"React field refs — {len(react_refs)} refs across {len(by_field)} fields")
        print("=" * 72)
        for fld in sorted(by_field.keys()):
            files = sorted(by_field[fld])
            print(f"  {fld}  ({len(files)} file{'s' if len(files) != 1 else ''})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="audit_read_sites",
        description="Scan the codebase for SQL and React read sites (mig-07 Mode 1).",
    )
    ap.add_argument("--csv", action="store_true",
                    help="Write detailed CSV report to data/reports/read_site_inventory.csv")
    ap.add_argument("--table", type=str, default=None,
                    help="Filter to a specific table name (case-insensitive)")
    ap.add_argument("--column", type=str, default=None,
                    help="Filter to a specific column name across all tables")
    ap.add_argument("--scripts-dir", type=str, default="scripts",
                    help="Python scripts directory to scan (default: scripts)")
    ap.add_argument("--react-dir", type=str, default="web/react-app/src",
                    help="React source directory to scan (default: web/react-app/src)")
    ap.add_argument("--report-path", type=str,
                    default="data/reports/read_site_inventory.csv",
                    help="Path to write CSV report (with --csv)")
    args = ap.parse_args(argv)

    cwd = Path.cwd()
    scripts_dir = cwd / args.scripts_dir
    react_dir = cwd / args.react_dir

    sql_refs: list[SqlRef] = []
    react_refs: list[ReactFieldRef] = []

    if scripts_dir.is_dir():
        sql_refs = scan_python_dir(scripts_dir, root=cwd)
    if react_dir.is_dir():
        react_refs = scan_react_dir(react_dir, root=cwd)

    sql_refs = filter_refs(sql_refs, table=args.table, column=args.column)

    _print_summary(sql_refs, react_refs)

    if args.csv:
        report = cwd / args.report_path
        write_csv(sql_refs, report)
        print(f"\nCSV report: {report}")
        print(f"  rows: {len(sql_refs)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
