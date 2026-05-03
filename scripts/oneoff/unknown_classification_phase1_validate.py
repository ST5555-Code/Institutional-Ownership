"""Phase 1: re-validate ECH classification='unknown' cohort size.

Read-only. Compares against institution_scoping.md §2.1 baseline (3,852 unknown
on open ECH, 99.9% coverage). Aborts if drift > 5%.
"""
import duckdb
import sys
from pathlib import Path

DB = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb")
SENTINEL = "DATE '9999-12-31'"
BASELINE = 3852
DRIFT_PCT = 0.05


def main() -> int:
    con = duckdb.connect(str(DB), read_only=True)

    open_unknown = con.execute(
        f"SELECT COUNT(*) FROM entity_classification_history "
        f"WHERE classification='unknown' AND valid_to = {SENTINEL}"
    ).fetchone()[0]

    open_total = con.execute(
        f"SELECT COUNT(*) FROM entity_classification_history "
        f"WHERE valid_to = {SENTINEL}"
    ).fetchone()[0]

    universe = con.execute(
        "SELECT COUNT(DISTINCT entity_id) FROM entities WHERE entity_type='institution'"
    ).fetchone()[0]

    no_ech_inst = con.execute(
        f"""
        SELECT COUNT(*) FROM entities e
        WHERE e.entity_type='institution'
        AND NOT EXISTS (
            SELECT 1 FROM entity_classification_history h
            WHERE h.entity_id = e.entity_id AND h.valid_to = {SENTINEL}
        )
        """
    ).fetchone()[0]

    coverage = (open_total / universe) if universe else 0.0
    drift = abs(open_unknown - BASELINE) / BASELINE

    print(f"PHASE 1 — re-validate cohort size")
    print(f"  open ECH classification='unknown': {open_unknown:,}")
    print(f"  open ECH total:                    {open_total:,}")
    print(f"  institution universe:              {universe:,}")
    print(f"  open-row coverage of universe:     {coverage:.4%}")
    print(f"  institutions w/ zero open ECH:     {no_ech_inst:,}")
    print(f"  baseline (institution_scoping §2.1): {BASELINE:,}")
    print(f"  drift vs baseline:                 {drift:.2%}")

    if drift > DRIFT_PCT:
        print(f"\nABORT: cohort drift {drift:.2%} exceeds {DRIFT_PCT:.0%}")
        return 1

    print(f"\nOK: drift within {DRIFT_PCT:.0%}, proceeding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
