"""Phase 2 — is_passive boolean redundancy audit.

1. Grep for read sites of `is_passive` across scripts/, web/, app.py.
2. Cross-validate is_passive=TRUE rows against manager_type and fund_strategy
   (where available) to determine whether the boolean is fully derivable.

READ-ONLY. Emits a markdown fragment to stdout.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "13f.duckdb"


def grep_read_sites() -> list[tuple[str, int, str]]:
    """Find is_passive read sites — exclude obvious write sites (assignments)."""
    cmd = [
        "grep",
        "-rn",
        "--include=*.py",
        "--include=*.sql",
        "--include=*.ts",
        "--include=*.tsx",
        "--include=*.js",
        "is_passive",
        str(REPO_ROOT / "scripts"),
        str(REPO_ROOT / "web"),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False).stdout

    # Also check app.py at root if present
    app_py = REPO_ROOT / "app.py"
    if app_py.exists():
        out2 = subprocess.run(
            ["grep", "-n", "is_passive", str(app_py)],
            capture_output=True, text=True, check=False
        ).stdout
        out += "\n" + "\n".join(f"{app_py}:{ln}" for ln in out2.splitlines())

    rows: list[tuple[str, int, str]] = []
    for line in out.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not m:
            continue
        path, lineno, snippet = m.groups()
        rows.append((path, int(lineno), snippet.strip()))
    return rows


def classify_site(snippet: str) -> str:
    s = snippet.lower()
    # heuristics — assignment vs read
    if re.search(r"\bis_passive\s*=\s*", s) and "==" not in s:
        return "WRITE/ASSIGN"
    if "set is_passive" in s or "update " in s and "is_passive" in s:
        return "WRITE/ASSIGN"
    if "boolean" in s and "is_passive" in s:
        return "SCHEMA"
    if "create table" in s or "alter table" in s:
        return "SCHEMA"
    if "select" in s or "where" in s or "filter" in s or "case when" in s:
        return "READ"
    if "is_passive=" in s.replace(" ", "") and "==" not in s:
        return "WRITE/ASSIGN"
    return "READ?"


def main() -> None:
    print("## Phase 2.3 — `is_passive` boolean redundancy audit\n")

    print("### Read-site grep (scripts/, web/, app.py)\n")
    sites = grep_read_sites()
    print(f"_Total grep hits: {len(sites)}._\n")

    # Group by file for a tighter table
    print("| file | line | classification | snippet |")
    print("|---|---|---|---|")
    for path, lineno, snippet in sites:
        cls = classify_site(snippet)
        rel = str(Path(path).relative_to(REPO_ROOT)) if path.startswith(str(REPO_ROOT)) else path
        # truncate long snippets
        snip = snippet[:120].replace("|", "\\|")
        print(f"| `{rel}` | {lineno} | {cls} | `{snip}` |")
    print()

    # Cross-validation in DB
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("### Cross-validation in `holdings_v2`\n")

    df = con.execute(
        """
        SELECT
          is_passive,
          manager_type,
          COUNT(DISTINCT cik) AS ciks,
          COUNT(*) AS rows,
          ROUND(SUM(market_value_usd)/1e9, 1) AS aum_b
        FROM holdings_v2
        WHERE is_latest = TRUE
        GROUP BY 1, 2
        ORDER BY is_passive DESC NULLS LAST, rows DESC
        """
    ).fetchdf()
    print("**is_passive × manager_type:**\n")
    print(df.to_markdown(index=False))
    print()

    # is_passive=TRUE & manager_type != 'passive'
    df_div = con.execute(
        """
        SELECT manager_name, cik, manager_type,
               ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
        FROM holdings_v2
        WHERE is_latest = TRUE AND is_passive = TRUE
          AND (manager_type IS NULL OR manager_type <> 'passive')
        GROUP BY 1, 2, 3
        ORDER BY aum_b DESC NULLS LAST
        LIMIT 20
        """
    ).fetchdf()
    print("**Divergence: `is_passive=TRUE` BUT `manager_type<>passive` (top 20 by AUM):**\n")
    if df_div.empty:
        print("_No divergence rows._\n")
    else:
        print(df_div.to_markdown(index=False))
        print()

    # also: passive manager_type with is_passive=FALSE
    df_div2 = con.execute(
        """
        SELECT manager_name, cik, is_passive,
               ROUND(SUM(market_value_usd)/1e9, 2) AS aum_b
        FROM holdings_v2
        WHERE is_latest = TRUE AND manager_type = 'passive'
          AND (is_passive IS DISTINCT FROM TRUE)
        GROUP BY 1, 2, 3
        ORDER BY aum_b DESC NULLS LAST
        LIMIT 20
        """
    ).fetchdf()
    print("**Divergence: `manager_type='passive'` BUT `is_passive` not TRUE (top 20):**\n")
    if df_div2.empty:
        print("_No divergence rows._\n")
    else:
        print(df_div2.to_markdown(index=False))
        print()

    # check for fund_strategy column
    cols = [c[0] for c in con.execute("DESCRIBE holdings_v2").fetchall()]
    if "fund_strategy" in cols:
        df_fs = con.execute(
            """
            SELECT fund_strategy, is_passive, COUNT(*) AS rows
            FROM holdings_v2 WHERE is_latest = TRUE
            GROUP BY 1, 2 ORDER BY rows DESC LIMIT 30
            """
        ).fetchdf()
        print("**fund_strategy × is_passive:**\n")
        print(df_fs.to_markdown(index=False))
        print()
    else:
        print("_No `fund_strategy` column on holdings_v2 — skipping that cross-tab._\n")

    con.close()


if __name__ == "__main__":
    main()
