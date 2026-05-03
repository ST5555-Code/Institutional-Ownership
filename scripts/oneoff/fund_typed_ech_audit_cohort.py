"""
fund-typed-ech-audit Phase 1a + 1b — read-only cohort + source breakdown.

No writes. Confirms the open fund-typed ECH cohort from prior session and
enumerates distinct source values for the writer audit.

Usage:
    python3 scripts/oneoff/fund_typed_ech_audit_cohort.py
"""

import duckdb

DB = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    print("=== Phase 1a: open fund-typed ECH by classification ===")
    rows = con.execute(
        """
        SELECT classification, COUNT(*) AS n
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'fund'
          AND ech.valid_to = DATE '9999-12-31'
        GROUP BY classification
        ORDER BY 2 DESC
        """
    ).fetchall()
    total = 0
    for cls, n in rows:
        print(f"  {cls or '(NULL)':<24} {n:>8,}")
        total += n
    print(f"  {'TOTAL':<24} {total:>8,}")

    print()
    print("=== Phase 1b: open fund-typed ECH by source ===")
    src_rows = con.execute(
        """
        SELECT source, COUNT(*) AS n,
               MIN(valid_from) AS first_seen,
               MAX(valid_from) AS last_seen
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'fund'
          AND ech.valid_to = DATE '9999-12-31'
        GROUP BY source
        ORDER BY 2 DESC
        """
    ).fetchall()
    for src, n, first_seen, last_seen in src_rows:
        print(f"  {src or '(NULL)':<32} {n:>8,}  {first_seen}  {last_seen}")

    print()
    print("=== Phase 1b cross-tab: source x classification ===")
    cross = con.execute(
        """
        SELECT source, classification, COUNT(*) AS n
        FROM entity_classification_history ech
        JOIN entities e ON e.entity_id = ech.entity_id
        WHERE e.entity_type = 'fund'
          AND ech.valid_to = DATE '9999-12-31'
        GROUP BY source, classification
        ORDER BY source, n DESC
        """
    ).fetchall()
    cur_src = None
    for src, cls, n in cross:
        if src != cur_src:
            print(f"  {src or '(NULL)'}:")
            cur_src = src
        print(f"      {cls or '(NULL)':<20} {n:>8,}")


if __name__ == "__main__":
    main()
