"""Phase 2: source attribution distribution for the 3,852 ECH unknown cohort.

Read-only. Groups by ECH.source, entities.created_source, entities.entity_type.
Highlights bootstrap_tier4 (ROADMAP-tracked).
"""
import duckdb
from pathlib import Path

DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
SENTINEL = "DATE '9999-12-31'"


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    print("PHASE 2 — source attribution\n")

    print("(a) entity_classification_history.source on the open unknown row:")
    rows = con.execute(
        f"""
        SELECT COALESCE(source, '<NULL>') AS src, COUNT(*) AS n
        FROM entity_classification_history
        WHERE classification='unknown' AND valid_to = {SENTINEL}
        GROUP BY src
        ORDER BY n DESC
        """
    ).fetchall()
    total = sum(r[1] for r in rows)
    for src, n in rows:
        flag = "  <-- ROADMAP" if src == "bootstrap_tier4" else ""
        print(f"  {n:>5,}  {src}{flag}")
    print(f"  {total:>5,}  TOTAL\n")

    print("(b) entities.created_source for the cohort:")
    rows = con.execute(
        f"""
        SELECT COALESCE(e.created_source, '<NULL>') AS cs, COUNT(*) AS n
        FROM entity_classification_history h
        JOIN entities e ON e.entity_id = h.entity_id
        WHERE h.classification='unknown' AND h.valid_to = {SENTINEL}
        GROUP BY cs
        ORDER BY n DESC
        """
    ).fetchall()
    total = sum(r[1] for r in rows)
    for cs, n in rows:
        print(f"  {n:>5,}  {cs}")
    print(f"  {total:>5,}  TOTAL\n")

    print("(c) entities.entity_type for the cohort:")
    rows = con.execute(
        f"""
        SELECT COALESCE(e.entity_type, '<NULL>') AS et, COUNT(*) AS n
        FROM entity_classification_history h
        JOIN entities e ON e.entity_id = h.entity_id
        WHERE h.classification='unknown' AND h.valid_to = {SENTINEL}
        GROUP BY et
        ORDER BY n DESC
        """
    ).fetchall()
    total = sum(r[1] for r in rows)
    for et, n in rows:
        print(f"  {n:>5,}  {et}")
    print(f"  {total:>5,}  TOTAL\n")

    # Cross-tab source x entity_type — useful for tiering
    print("(d) cross-tab source x entity_type (top buckets):")
    rows = con.execute(
        f"""
        SELECT
            COALESCE(h.source, '<NULL>') AS src,
            COALESCE(e.entity_type, '<NULL>') AS et,
            COUNT(*) AS n
        FROM entity_classification_history h
        JOIN entities e ON e.entity_id = h.entity_id
        WHERE h.classification='unknown' AND h.valid_to = {SENTINEL}
        GROUP BY src, et
        ORDER BY n DESC
        LIMIT 25
        """
    ).fetchall()
    for src, et, n in rows:
        print(f"  {n:>5,}  {src:<32s}  {et}")


if __name__ == "__main__":
    main()
