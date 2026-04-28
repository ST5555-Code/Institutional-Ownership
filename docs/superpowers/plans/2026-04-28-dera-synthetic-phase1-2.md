# DERA Synthetic Series — Phase 1 (Tier 1) + Phase 2 (Tier 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all DERA synthetic series_ids that *can* be stabilized in this pass — swap the 1 Tier 1 case to its real S-number, and collapse the 55 Tier 3 single-fund stand-alone registrants from per-quarter `{cik}_{accession}` keys to one stable `SYN_{cik}` per registrant. Tier 4 (658 unmapped CIKs) is out of scope.

**Architecture:** One new oneoff script `scripts/oneoff/dera_synthetic_stabilize.py` does both phases behind `--phase {1,2,all}` and the standard `--dry-run`/`--confirm` flags. It UPDATEs `fund_holdings_v2.series_id` in place on prod, UPSERTs `fund_universe`, then backfills `entity_id` and `rollup_entity_id` from `entity_identifiers` + `entity_rollup_history`. Downstream is recomputed via the existing pipelines (`compute_parent_fund_map`, `compute_sector_flows`, `compute_flows`, `build_summaries`) and finished with `refresh_snapshot.sh`. Backup is taken before any write; baselines (row counts, total NAV, distinct-series counts) are captured pre/post and asserted.

**Tech Stack:** Python 3, DuckDB, existing repo conventions (db.PROD_DB, oneoff dry-run/confirm pattern).

**Reference:** [docs/findings/dera-synthetic-resolution-scoping.md](../../findings/dera-synthetic-resolution-scoping.md)

---

## Pre-flight (mandatory, do once at start)

**Files touched:** none (read-only).

- [ ] **Step 1: Confirm working directory and DB paths**

The repo lives at `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership`. The
worktree at `.claude/worktrees/nice-vaughan-8da17c/` has an empty `data/` dir, so
all pipeline runs that touch the prod DB must run from the main checkout. Code
edits stay in the worktree (PR diff). Capture both paths now:

```bash
WORKTREE=/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/nice-vaughan-8da17c
MAIN=/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership
echo "worktree=$WORKTREE"
echo "main=$MAIN"
ls "$MAIN/data/13f.duckdb" "$MAIN/data/13f_staging.duckdb"
```

Expected: both DB files print without error.

- [ ] **Step 2: Verify app is not running**

```bash
ps aux | grep -E "flask|gunicorn|uvicorn|python.*app\.py" | grep -v grep
```

Expected: empty. If anything prints, stop the process before the apply step.

- [ ] **Step 3: Capture baseline metrics from prod DB (pre-state)**

```bash
cd "$MAIN"
python3 - <<'PY'
import duckdb
con = duckdb.connect("data/13f.duckdb", read_only=True)
print("--- pre-state baselines ---")
for q in [
    "SELECT COUNT(*) AS rows, COUNT(DISTINCT series_id) AS series, COALESCE(SUM(market_value_usd),0)/1e9 AS nav_b FROM fund_holdings_v2 WHERE is_latest",
    "SELECT COUNT(*) FROM fund_universe",
    # synthetic-key inventory
    "SELECT COUNT(DISTINCT series_id) AS synth_series FROM fund_holdings_v2 WHERE is_latest AND (series_id LIKE '%\\_%' ESCAPE '\\' AND series_id NOT LIKE 'S%' AND series_id NOT LIKE 'SYN_%')",
    # tier-1 specific
    "SELECT series_id, fund_cik, fund_name, COUNT(*) rows, COALESCE(SUM(market_value_usd),0)/1e6 nav_m FROM fund_holdings_v2 WHERE is_latest AND series_id = '2060415_0002071691-26-007379' GROUP BY 1,2,3",
    "SELECT series_id, fund_cik, COUNT(*) rows FROM fund_holdings_v2 WHERE is_latest AND series_id = 'S000093420' GROUP BY 1,2",
]:
    print(q)
    for r in con.execute(q).fetchall():
        print("  ", r)
PY
```

Save the printed numbers — they are the pre-state assertion targets in Step "Verify (post-state)" below.

- [ ] **Step 4: Backup prod DB**

```bash
cd "$MAIN"
python3 scripts/backup_db.py --no-confirm
ls -lh data/backups/ | tail -3
```

Expected: a fresh `13f.duckdb.<timestamp>.bak` (or whatever convention `backup_db.py` uses) sized close to 24 GB.

---

## Task 1: Tier 1 — single-row series swap (Phase 1)

The Tier 1 case is fully deterministic per the scoping doc:

| | Synthetic | Real |
|---|---|---|
| series_id | `2060415_0002071691-26-007379` | `S000093420` |
| fund_cik | `0002060415` | `0002060415` |
| fund_name | First Eagle High Yield Municipal Completion Fund | First Eagle High Yield Municipal Completion Fund |
| report_month | 2026-01 | 2025-10 |
| rows | 72 | 68 |

The synthetic key was generated because the Q1'26 DERA bulk dropped `SERIES_ID`
for that filing; Q4'25 carried it. This is two adjacent quarters of the same
fund, so the resolution is simply a series_id rename on the synthetic-keyed
rows. **No row count change.** No recompute is needed for Tier 1 alone, but
we batch the recompute with Tier 3 below.

**Files:**
- Create: `scripts/oneoff/dera_synthetic_stabilize.py`

- [ ] **Step 1.1: Scaffold the script (CLI + safety + helpers)**

Skeleton at the top of the file. Default mode is `--dry-run`; require
`--confirm` for any write. Mirrors `scripts/oneoff/apply_series_triage.py`.

```python
#!/usr/bin/env python3
"""dera_synthetic_stabilize.py — Phase 1 + Phase 2 DERA synthetic resolution.

Phase 1 (Tier 1, 1 registrant): swap synthetic series_id
   '2060415_0002071691-26-007379' -> 'S000093420' (real series_id from
   the same fund's other-quarter row).

Phase 2 (Tier 3, 55 registrants): collapse per-quarter synthetic series_ids
   of the form '{cik}_{accession}' to a stable 'SYN_{cik}' for each of the
   55 entity-mapped single-fund registrants. Backfill entity_id +
   rollup_entity_id (EC + DM) on the affected fund_holdings_v2 rows.

Default: --dry-run. Pass --confirm to write.

Usage:
  python3 scripts/oneoff/dera_synthetic_stabilize.py --phase 1 --dry-run
  python3 scripts/oneoff/dera_synthetic_stabilize.py --phase 1 --confirm
  python3 scripts/oneoff/dera_synthetic_stabilize.py --phase 2 --dry-run
  python3 scripts/oneoff/dera_synthetic_stabilize.py --phase 2 --confirm
  python3 scripts/oneoff/dera_synthetic_stabilize.py --phase all --confirm

Reference: docs/findings/dera-synthetic-resolution-scoping.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import db  # noqa: E402

SOURCE_TAG = "dera_synthetic_stabilize"

# Pinned Tier 1 case (only one in fund_holdings_v2 as of 2026-04-28).
TIER1_SYNTH = "2060415_0002071691-26-007379"
TIER1_REAL = "S000093420"
TIER1_FUND_CIK = "0002060415"

# Sentinel for entity_rollup_history open rows (project_scd_sentinel.md).
SCD_OPEN = "9999-12-31"
```

- [ ] **Step 1.2: Tier 1 dry-run reporter**

```python
def phase1_report(con) -> dict:
    """Print Tier 1 pre-state. Returns counts for assertions."""
    synth = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE is_latest AND series_id = ?", [TIER1_SYNTH]
    ).fetchone()[0]
    real = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE is_latest AND series_id = ?", [TIER1_REAL]
    ).fetchone()[0]
    fu_synth = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE series_id = ?",
        [TIER1_SYNTH],
    ).fetchone()[0]
    fu_real = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE series_id = ?",
        [TIER1_REAL],
    ).fetchone()[0]
    print("PHASE 1 (Tier 1) pre-state:")
    print(f"  fund_holdings_v2 synthetic={synth} real={real}")
    print(f"  fund_universe   synthetic={fu_synth} real={fu_real}")
    if synth == 0:
        print("  -> nothing to do (synthetic key already absent).")
    return {"synth_holdings": synth, "real_holdings": real,
            "synth_fu": fu_synth, "real_fu": fu_real}
```

- [ ] **Step 1.3: Tier 1 apply path**

```python
def phase1_apply(con) -> None:
    pre = phase1_report(con)
    if pre["synth_holdings"] == 0:
        return

    # Sanity guards: same fund_cik, same fund_name, real key already present.
    bad_cik = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 "
        "WHERE is_latest AND series_id = ? AND fund_cik <> ?",
        [TIER1_SYNTH, TIER1_FUND_CIK],
    ).fetchone()[0]
    if bad_cik:
        raise RuntimeError(
            f"Tier1 abort: {bad_cik} synthetic rows do not match fund_cik {TIER1_FUND_CIK}"
        )
    if pre["real_holdings"] == 0:
        raise RuntimeError(
            f"Tier1 abort: real key {TIER1_REAL} not present in fund_holdings_v2"
        )

    con.execute("BEGIN")
    try:
        con.execute(
            "UPDATE fund_holdings_v2 SET series_id = ? WHERE series_id = ?",
            [TIER1_REAL, TIER1_SYNTH],
        )
        # fund_universe: drop the synthetic row if it exists (the real row
        # already covers the fund). Per scoping doc, fund_universe has
        # exactly 0 real rows for Tier 1 CIKs but may have a synthetic row.
        con.execute(
            "DELETE FROM fund_universe WHERE series_id = ?", [TIER1_SYNTH]
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    post_synth = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE series_id = ?",
        [TIER1_SYNTH],
    ).fetchone()[0]
    if post_synth:
        raise RuntimeError(f"Tier1 verify: {post_synth} synthetic rows remain")
    print(f"PHASE 1: swapped {pre['synth_holdings']} rows "
          f"{TIER1_SYNTH} -> {TIER1_REAL}; "
          f"{pre['synth_fu']} fund_universe synthetic row(s) deleted.")
```

- [ ] **Step 1.4: CLI plumbing for Phase 1**

Wire `argparse` + a top-level `main()` that dispatches by `--phase`. `--dry-run`
runs `phase1_report` only; `--confirm` runs `phase1_apply`.

```python
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=["1", "2", "all"], required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--confirm", action="store_true")
    p.add_argument("--prod-db", default=db.PROD_DB)
    args = p.parse_args()

    if args.confirm:
        args.dry_run = False

    import duckdb  # noqa: WPS433
    con = duckdb.connect(args.prod_db, read_only=args.dry_run)
    try:
        if args.phase in ("1", "all"):
            print(f"--- PHASE 1 (Tier 1) {'DRY-RUN' if args.dry_run else 'APPLY'} ---")
            if args.dry_run:
                phase1_report(con)
            else:
                phase1_apply(con)
        if args.phase in ("2", "all"):
            print(f"--- PHASE 2 (Tier 3) {'DRY-RUN' if args.dry_run else 'APPLY'} ---")
            if args.dry_run:
                phase2_report(con)
            else:
                phase2_apply(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.5: Run Phase 1 dry-run, eyeball output**

```bash
cd "$MAIN"
python3 "$WORKTREE/scripts/oneoff/dera_synthetic_stabilize.py" --phase 1 --dry-run
```

Expected output: `synth=72  real=68` (matches scoping doc Step 3 table). If
either count is 0 or the synth count doesn't match, stop and investigate.

- [ ] **Step 1.6: Run Phase 1 apply**

```bash
cd "$MAIN"
python3 "$WORKTREE/scripts/oneoff/dera_synthetic_stabilize.py" --phase 1 --confirm
```

Expected: `swapped 72 rows 2060415_0002071691-26-007379 -> S000093420`.

- [ ] **Step 1.7: Verify Phase 1 post-state**

```bash
cd "$MAIN"
python3 - <<'PY'
import duckdb
con = duckdb.connect("data/13f.duckdb", read_only=True)
synth = con.execute("SELECT COUNT(*) FROM fund_holdings_v2 WHERE series_id = '2060415_0002071691-26-007379'").fetchone()[0]
real = con.execute("SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest AND series_id = 'S000093420'").fetchone()[0]
print(f"synth={synth} (expect 0) real={real} (expect 140 = 72+68)")
PY
```

- [ ] **Step 1.8: Commit Phase 1**

```bash
cd "$WORKTREE"
git add scripts/oneoff/dera_synthetic_stabilize.py
git commit -m "$(cat <<'EOF'
dera-synthetic-phase1: Tier 1 series swap (1 registrant, 72 rows)

Adds scripts/oneoff/dera_synthetic_stabilize.py with --phase 1 / --phase 2 /
--phase all + standard --dry-run / --confirm. Phase 1 swaps the only Tier 1
case (CIK 0002060415 First Eagle High Yield Municipal Completion Fund) from
synthetic series '2060415_0002071691-26-007379' to its real S000093420
series_id, which exists in the same fund's Q4'25 row.

Reference: docs/findings/dera-synthetic-resolution-scoping.md (Step 3 Tier 1).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Tier 3 — derive the 55 candidate CIKs (Phase 2 part A)

Tier 3 = registrants where `entity_identifiers` has a `cik` row but `fund_universe`
has no real `S%` series for that CIK and `fund_holdings_v2` carries one or more
synthetic series in the `{cik}_%` shape. The scoping doc says n=55. We
re-derive at runtime against the live DB rather than hardcoding the list, then
assert the count matches 55.

**Files:**
- Modify: `scripts/oneoff/dera_synthetic_stabilize.py`

- [ ] **Step 2.1: Add the candidate-CIK SQL helper**

```python
TIER3_CIKS_SQL = """
WITH synth_holdings AS (
    -- All distinct (raw_cik, padded_cik) pairs for synthetic rows.
    -- A synthetic series_id is '{cik}_{accession}' where {cik} is the
    -- *unpadded* registrant CIK from the DERA submission.
    SELECT DISTINCT
        SPLIT_PART(series_id, '_', 1) AS raw_cik,
        LPAD(SPLIT_PART(series_id, '_', 1), 10, '0') AS cik_padded
    FROM fund_holdings_v2
    WHERE is_latest
      AND series_id NOT LIKE 'S%'
      AND series_id NOT LIKE 'SYN_%'
      AND series_id <> 'UNKNOWN'
      AND series_id LIKE '%\\_%' ESCAPE '\\'
),
has_real_in_fu AS (
    SELECT DISTINCT fund_cik
    FROM fund_universe
    WHERE series_id LIKE 'S%'
),
entity_ciks AS (
    SELECT DISTINCT identifier_value AS cik_padded, entity_id
    FROM entity_identifiers
    WHERE identifier_type = 'cik'
)
SELECT s.raw_cik, s.cik_padded, e.entity_id
FROM synth_holdings s
JOIN entity_ciks e ON e.cik_padded = s.cik_padded
LEFT JOIN has_real_in_fu fu ON fu.fund_cik = s.cik_padded
WHERE fu.fund_cik IS NULL
ORDER BY s.cik_padded
"""

def load_tier3_candidates(con):
    """Return list of (raw_cik, cik_padded, entity_id). Asserts count==55."""
    rows = con.execute(TIER3_CIKS_SQL).fetchall()
    if len(rows) != 55:
        raise RuntimeError(
            f"Tier3 candidate count mismatch: got {len(rows)}, expected 55. "
            "Check docs/findings/dera-synthetic-resolution-scoping.md and "
            "investigate whether new entities or new filings shifted the set."
        )
    return rows
```

Note: `identifier_type` is lowercase `'cik'` (memory: `project_identifier_type_lowercase.md`).

- [ ] **Step 2.2: Add Phase 2 dry-run reporter**

```python
def phase2_report(con) -> dict:
    cands = load_tier3_candidates(con)
    raw_ciks = [r[0] for r in cands]
    padded_ciks = [r[1] for r in cands]

    # Per-tier metrics on synthetic rows for these 55 CIKs.
    placeholders = ",".join(["?"] * len(raw_ciks))
    sql = (
        f"SELECT COUNT(*) rows, COUNT(DISTINCT series_id) series, "
        f"COALESCE(SUM(market_value_usd),0)/1e9 nav_b "
        f"FROM fund_holdings_v2 WHERE is_latest AND ("
        + " OR ".join([f"series_id LIKE ?" for _ in raw_ciks])
        + ")"
    )
    like_args = [f"{c}\\_%" for c in raw_ciks]  # escape underscore? duckdb
    # Simpler/safer: use regexp_matches.
    sql = (
        "SELECT COUNT(*) AS rows, "
        "COUNT(DISTINCT series_id) AS series, "
        "COALESCE(SUM(market_value_usd),0)/1e9 AS nav_b "
        "FROM fund_holdings_v2 "
        "WHERE is_latest AND series_id NOT LIKE 'S%' "
        "  AND series_id NOT LIKE 'SYN_%' "
        "  AND SPLIT_PART(series_id, '_', 1) IN ("
        + ",".join(["?"] * len(raw_ciks)) + ")"
    )
    rows, series, nav_b = con.execute(sql, raw_ciks).fetchone()

    fu_count = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE fund_cik IN ("
        + ",".join(["?"] * len(padded_ciks)) + ")",
        padded_ciks,
    ).fetchone()[0]

    print("PHASE 2 (Tier 3) pre-state:")
    print(f"  candidate CIKs: {len(cands)} (expect 55)")
    print(f"  synthetic rows: {rows:,}  distinct series: {series}  nav_b: {nav_b:.1f}")
    print(f"  fund_universe rows for these CIKs: {fu_count}")
    return {"candidates": cands, "rows": rows, "series": series, "nav_b": nav_b, "fu_count": fu_count}
```

- [ ] **Step 2.3: Add Phase 2 apply path (UPDATE + UPSERT + backfill)**

For each of the 55 CIKs, in one transaction:
1. UPDATE fund_holdings_v2 set series_id='SYN_{cik_padded}' for that CIK's synth rows.
2. DELETE any existing fund_universe rows whose series_id matches `{raw_cik}_%` for that CIK (these are per-quarter synthetic sidecar rows).
3. INSERT one fund_universe row keyed by series_id='SYN_{cik_padded}' carrying the most-recent fund_cik / fund_name / family_name / total_net_assets / last_updated.
4. UPDATE fund_holdings_v2 set entity_id, rollup_entity_id, dm_entity_id, dm_rollup_entity_id, dm_rollup_name on the rows just rekeyed (using entity_identifiers + entity_rollup_history at SCD_OPEN sentinel).

```python
def phase2_apply(con) -> None:
    cands = load_tier3_candidates(con)
    print(f"PHASE 2: applying to {len(cands)} CIKs")

    rekeyed = 0
    fu_inserted = 0
    fu_deleted = 0
    holdings_backfilled = 0

    for raw_cik, cik_padded, entity_id in cands:
        new_series = f"SYN_{cik_padded}"

        # Lookup rollups (EC + DM) once per CIK.
        ec_row = con.execute(
            "SELECT rollup_entity_id FROM entity_rollup_history "
            "WHERE entity_id = ? AND rollup_type = 'economic_control_v1' "
            "  AND valid_to = DATE '" + SCD_OPEN + "' "
            "ORDER BY valid_from DESC LIMIT 1",
            [entity_id],
        ).fetchone()
        dm_row = con.execute(
            "SELECT rollup_entity_id FROM entity_rollup_history "
            "WHERE entity_id = ? AND rollup_type = 'decision_maker_v1' "
            "  AND valid_to = DATE '" + SCD_OPEN + "' "
            "ORDER BY valid_from DESC LIMIT 1",
            [entity_id],
        ).fetchone()
        ec_rollup = ec_row[0] if ec_row else None
        dm_rollup = dm_row[0] if dm_row else None
        # dm_rollup_name may already be set; recompute from entities.entity_name.
        dm_name = None
        if dm_rollup is not None:
            r = con.execute(
                "SELECT entity_name FROM entities WHERE entity_id = ?", [dm_rollup]
            ).fetchone()
            dm_name = r[0] if r else None

        con.execute("BEGIN")
        try:
            # 1. Pick a single canonical fund_universe row to keep.
            # Use the synthetic row with the latest last_updated (or any one if
            # tied) BEFORE we change keys.
            canon = con.execute(
                "SELECT fund_cik, fund_name, family_name, total_net_assets, "
                "  fund_category, is_actively_managed, total_holdings_count, "
                "  equity_pct, top10_concentration, last_updated, "
                "  fund_strategy, best_index, strategy_narrative, "
                "  strategy_source, strategy_fetched_at "
                "FROM fund_universe "
                "WHERE SPLIT_PART(series_id, '_', 1) = ? "
                "ORDER BY last_updated DESC NULLS LAST LIMIT 1",
                [raw_cik],
            ).fetchone()

            # 2. Rekey holdings.
            con.execute(
                "UPDATE fund_holdings_v2 SET series_id = ? "
                "WHERE SPLIT_PART(series_id, '_', 1) = ? "
                "  AND series_id NOT LIKE 'S%' "
                "  AND series_id NOT LIKE 'SYN_%'",
                [new_series, raw_cik],
            )
            rk = con.execute("SELECT changes()").fetchone()[0]
            rekeyed += rk

            # 3. Drop old fund_universe rows for this CIK's synthetic keys.
            con.execute(
                "DELETE FROM fund_universe "
                "WHERE SPLIT_PART(series_id, '_', 1) = ? "
                "  AND series_id NOT LIKE 'S%' "
                "  AND series_id NOT LIKE 'SYN_%'",
            [raw_cik])
            fud = con.execute("SELECT changes()").fetchone()[0]
            fu_deleted += fud

            # 4. Insert canonical fund_universe row keyed by SYN_{cik}.
            if canon:
                con.execute(
                    "INSERT INTO fund_universe ("
                    "  fund_cik, fund_name, series_id, family_name, "
                    "  total_net_assets, fund_category, is_actively_managed, "
                    "  total_holdings_count, equity_pct, top10_concentration, "
                    "  last_updated, fund_strategy, best_index, "
                    "  strategy_narrative, strategy_source, strategy_fetched_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (series_id) DO UPDATE SET "
                    "  fund_cik=EXCLUDED.fund_cik, "
                    "  fund_name=EXCLUDED.fund_name, "
                    "  family_name=EXCLUDED.family_name, "
                    "  total_net_assets=EXCLUDED.total_net_assets, "
                    "  last_updated=EXCLUDED.last_updated",
                    [
                        canon[0], canon[1], new_series, canon[2],
                        canon[3], canon[4], canon[5], canon[6],
                        canon[7], canon[8], canon[9], canon[10],
                        canon[11], canon[12], canon[13], canon[14],
                    ],
                )
                fu_inserted += 1

            # 5. Backfill entity_id, rollup_entity_id, dm_*.
            con.execute(
                "UPDATE fund_holdings_v2 SET "
                "  entity_id = ?, "
                "  rollup_entity_id = ?, "
                "  dm_entity_id = ?, "
                "  dm_rollup_entity_id = ?, "
                "  dm_rollup_name = ? "
                "WHERE series_id = ?",
                [entity_id, ec_rollup, entity_id, dm_rollup, dm_name, new_series],
            )
            bf = con.execute("SELECT changes()").fetchone()[0]
            holdings_backfilled += bf

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    print(f"PHASE 2: rekeyed {rekeyed:,} holdings rows; "
          f"fund_universe -{fu_deleted} +{fu_inserted}; "
          f"backfilled {holdings_backfilled:,} entity/rollup cells")
```

- [ ] **Step 2.4: Phase 2 dry-run**

```bash
cd "$MAIN"
python3 "$WORKTREE/scripts/oneoff/dera_synthetic_stabilize.py" --phase 2 --dry-run
```

Expected: candidate CIKs = 55; synthetic rows ≈ 1,285,842; nav_b ≈ 1982.6
(matches the scoping doc Tier 3 line). If 55 doesn't match exactly, **stop**
and investigate before applying.

- [ ] **Step 2.5: Phase 2 apply**

```bash
cd "$MAIN"
python3 -u "$WORKTREE/scripts/oneoff/dera_synthetic_stabilize.py" --phase 2 --confirm 2>&1 | tee "$WORKTREE/logs/dera_synthetic_phase2.log"
```

Use `-u` (unbuffered, per `feedback_buffered_output.md`). Expected: rekeyed
≈1,285,842; +55 fund_universe inserts; backfilled ≈1,285,842 cells.

- [ ] **Step 2.6: Commit Phase 2 script + log**

```bash
cd "$WORKTREE"
git add scripts/oneoff/dera_synthetic_stabilize.py logs/dera_synthetic_phase2.log
git commit -m "$(cat <<'EOF'
dera-synthetic-phase2: Tier 3 stable-key migration (55 registrants, ~$1.98T NAV)

Collapses per-quarter synthetic series_ids of the form '{cik}_{accession}' to
stable 'SYN_{cik}' for the 55 entity-mapped single-fund stand-alone
registrants (ETFs, BDCs, interval funds, CEFs). Each registrant now has one
fund_universe row keyed by SYN_{cik}. fund_holdings_v2.entity_id,
rollup_entity_id, dm_entity_id, dm_rollup_entity_id, dm_rollup_name are
backfilled from entity_identifiers + entity_rollup_history (SCD open at
9999-12-31) for both EC and DM rollups.

No row deletions in fund_holdings_v2; only series_id rewrites and
entity-column backfills. fund_universe loses ~108 per-quarter synth rows
and gains 55 stable rows.

Reference: docs/findings/dera-synthetic-resolution-scoping.md (Tier 3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Recompute downstream + refresh snapshot

**Files:** none modified — runs existing pipelines.

- [ ] **Step 3.1: Re-emit parent_fund_map**

```bash
cd "$MAIN"
python3 -u scripts/pipeline/compute_parent_fund_map.py 2>&1 | tee -a "$WORKTREE/logs/dera_synthetic_phase2.log"
```

Expected: `promoted: rows_inserted=... rows_upserted=...` with no error.

- [ ] **Step 3.2: Re-emit sector flows rollup**

```bash
cd "$MAIN"
python3 -u scripts/pipeline/compute_sector_flows.py 2>&1 | tee -a "$WORKTREE/logs/dera_synthetic_phase2.log"
```

- [ ] **Step 3.3: Re-emit flows + summaries**

```bash
cd "$MAIN"
python3 -u scripts/compute_flows.py 2>&1 | tee -a "$WORKTREE/logs/dera_synthetic_phase2.log"
python3 -u scripts/build_summaries.py 2>&1 | tee -a "$WORKTREE/logs/dera_synthetic_phase2.log"
```

- [ ] **Step 3.4: Refresh readonly snapshot**

```bash
cd "$MAIN"
bash scripts/refresh_snapshot.sh
```

Expected: `Snapshot updated:` with current timestamp; readonly DB at ~8 GB.

---

## Task 4: Verification (post-state, fail-loud)

**Files:** none.

- [ ] **Step 4.1: Synthetic-key residual = 0 for the 56 in-scope CIKs**

```bash
cd "$MAIN"
python3 - <<'PY'
import duckdb
con = duckdb.connect("data/13f.duckdb", read_only=True)

# Tier 1 + Tier 3: 1 + 55 = 56 in-scope CIKs. After this pass, none of them
# should still have a {cik}_{accession}-shape series_id.
n = con.execute("""
    SELECT COUNT(*)
    FROM fund_holdings_v2
    WHERE is_latest
      AND series_id NOT LIKE 'S%'
      AND series_id NOT LIKE 'SYN_%'
      AND series_id <> 'UNKNOWN'
      AND series_id LIKE '%\\_%' ESCAPE '\\'
      AND SPLIT_PART(series_id, '_', 1) IN (
        SELECT regexp_replace(identifier_value, '^0+', '')
        FROM entity_identifiers WHERE identifier_type = 'cik'
      )
""").fetchone()[0]
assert n == 0, f"residual synthetic rows for in-scope CIKs: {n}"

syn = con.execute(
    "SELECT COUNT(DISTINCT series_id) FROM fund_holdings_v2 "
    "WHERE is_latest AND series_id LIKE 'SYN_%'"
).fetchone()[0]
assert syn == 55, f"expected 55 SYN_* keys, got {syn}"

null_eid = con.execute(
    "SELECT COUNT(*) FROM fund_holdings_v2 "
    "WHERE is_latest AND series_id LIKE 'SYN_%' AND entity_id IS NULL"
).fetchone()[0]
assert null_eid == 0, f"{null_eid} SYN_* rows missing entity_id"

print("ALL POST-STATE ASSERTIONS PASS")
PY
```

- [ ] **Step 4.2: Total row count + total NAV unchanged within float tolerance**

Compare against the pre-state baselines captured in pre-flight Step 3. Total
fund_holdings_v2 row count should be **identical**. Total `SUM(market_value_usd)`
on `is_latest` should be within 0.01% (float aggregation order changes can
shift the last few cents on a $2.5T total).

```bash
cd "$MAIN"
python3 - <<'PY'
import duckdb
con = duckdb.connect("data/13f.duckdb", read_only=True)
print(con.execute(
    "SELECT COUNT(*), COUNT(DISTINCT series_id), SUM(market_value_usd)/1e9 "
    "FROM fund_holdings_v2 WHERE is_latest"
).fetchone())
PY
```

Compare to baseline. If row count differs, **investigate before refreshing
snapshot or merging.**

- [ ] **Step 4.3: validate_entities baseline preserved**

```bash
cd "$MAIN"
python3 -u scripts/validate_entities.py --prod --read-only 2>&1 | tail -40
```

Expected: same gate count as last green run. Diff against baseline if needed
(memory: this script is the entity-layer hard gate).

- [ ] **Step 4.4: Restart app**

The user's spec mentions stopping/starting the app. We didn't actually start
or stop anything in this session (it wasn't running). If the user typically
runs it via uvicorn/flask, defer to them. Note: app reads
`data/13f_readonly.duckdb`, which Step 3.4 already refreshed.

---

## Task 5: Documentation + handoff

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/NEXT_SESSION_CONTEXT.md`

- [ ] **Step 5.1: Update ROADMAP.md**

Move the DERA synthetic Phase 1 + Phase 2 line from the active section to
COMPLETED with date 2026-04-28 (per `feedback_update_roadmap.md`). Note that
Tier 4 (658 unmapped CIKs, $570.8B) remains.

- [ ] **Step 5.2: Update docs/NEXT_SESSION_CONTEXT.md**

Per `feedback_update_next_session_context.md`: add the new commit hashes,
note the Tier 1 swap and Tier 3 stable-key migration, the 55 SYN_* keys now
in fund_universe, and the open follow-up (Tier 4 bootstrap).

- [ ] **Step 5.3: Commit docs**

```bash
cd "$WORKTREE"
git add ROADMAP.md docs/NEXT_SESSION_CONTEXT.md
git commit -m "$(cat <<'EOF'
dera-synthetic-phase1-2: roadmap + next-session context update

Phase 1 (Tier 1, 1 reg) + Phase 2 (Tier 3, 55 regs, ~$1.98T NAV) complete.
Tier 4 (658 unmapped CIKs, $570.8B) is the remaining synthetic-resolution
work and is deferred per the original FLAG decision.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Push + open PR (do not merge)

- [ ] **Step 6.1: Push branch**

```bash
cd "$WORKTREE"
git push -u origin claude/nice-vaughan-8da17c
```

- [ ] **Step 6.2: Open PR**

Use `gh pr create --title "DERA synthetic Phase 1 + 2 — Tier 1 swap + Tier 3 stable keys (55 regs)"` with a body summarizing the three commits, the pre/post numbers, and the explicit "Tier 4 deferred" note. Per spec: **do not merge.**

---

## Self-Review Notes

- **Spec coverage:** Tier 1 (Task 1) + Tier 3 (Task 2) + recompute (Task 3) + verify (Task 4) + roadmap/context (Task 5) + push/PR (Task 6). All 7 user-listed steps for Phase 1 and all 7 user-listed steps for Phase 2 are mapped.
- **Things to confirm with operator BEFORE Step 2.5 apply:** the dry-run candidate count must be exactly 55. If a recent N-PORT load has shifted that number (e.g. a new entity-bootstrap promoted a Tier 4 CIK into Tier 3), pause and decide whether to run on the new set or filter back to the original 55.
- **Backups:** Step "Pre-flight 4" creates a `.bak` before any write. Restore command if something goes wrong: `cp data/backups/13f.duckdb.<ts>.bak data/13f.duckdb && bash scripts/refresh_snapshot.sh`.
- **Out of scope per user instruction:** Tier 4 CIKs, entity bootstrap, `build_classifications.py --reset`, deleting any rows.
