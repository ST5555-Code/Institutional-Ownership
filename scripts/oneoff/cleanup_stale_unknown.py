#!/usr/bin/env python3
"""cleanup_stale_unknown.py — fund-stale-unknown-cleanup (closes the
stale-loader artifact surfaced by PR #246).

Flips ``is_latest=FALSE`` on legacy ``series_id='UNKNOWN'`` rows in
``fund_holdings_v2`` whose ``(fund_cik, fund_name)`` pair has a live
``SYN_*`` companion (``is_latest=TRUE``). The Apr-15 v2 loader (commit
e868772) wrote authoritative SYN_ rows but did not flip is_latest on the
legacy UNKNOWN rows for the same (cik, accession_number).

Per-pair branching:
  BRANCH 1  FLIP            — UNKNOWN row has matching live SYN_* counterpart
                              (exact CIK + normalized fund_name match,
                              SYN_ row has is_latest=TRUE).
  BRANCH 2  HOLD_NO_MATCH   — UNKNOWN row has no SYN_* counterpart at all.
                              Do not synthesize; surface for chat decision.
  BRANCH 3  HOLD_SYN_INACTIVE — SYN_ row exists but is_latest=FALSE.
                                Different problem; surface separately.

Out of scope:
  * Cohort B (Rareview reclassify) — separate PR.
  * Cohort B2 (total_net_assets backfill on 301 funds) — separate PR.
  * Loader retroactive fix for the Apr-15 v2 bug — surfaced in results doc only.

Modes:
  --dry-run  (default) writes manifest CSV + dryrun findings MD; no DB writes.
  --confirm  reads the manifest CSV and flips is_latest=FALSE on BRANCH 1
             pairs only, in a single transaction.

Outputs:
  data/working/stale_unknown_cleanup_manifest.csv
  docs/findings/fund_stale_unknown_cleanup_dryrun.md  (dry-run)

Pattern precedent: scripts/oneoff/backfill_orphan_fund_universe.py (PR #245).
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
PROD_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "stale_unknown_cleanup_manifest.csv"
DRYRUN_DOC = BASE_DIR / "docs" / "findings" / "fund_stale_unknown_cleanup_dryrun.md"

EXPECTED_PAIR_COUNT = 8
EXPECTED_ROW_COUNT = 3_184
EXPECTED_AUM_USD = 10_025_000_000.0  # ~$10.025B from PR #246
TOLERANCE = 0.05  # 5% drift gate on row + pair counts


def norm(text: str | None) -> str:
    """Match the normalization used by audit_unknown_cohortA.py."""
    if not text:
        return ""
    out = text.lower().strip()
    out = re.sub(r"[^a-z0-9]+", " ", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


# ---------------------------------------------------------------------------
# Phase 1 — re-validate cohort
# ---------------------------------------------------------------------------

def validate_cohort(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        """
        WITH unk AS (
            SELECT fund_cik, fund_name,
                   COUNT(*) AS row_count,
                   SUM(COALESCE(market_value_usd,0)) AS aum_usd
            FROM fund_holdings_v2
            WHERE series_id='UNKNOWN' AND is_latest=TRUE
            GROUP BY fund_cik, fund_name
        )
        SELECT COUNT(*)        AS pair_count,
               SUM(row_count)  AS row_count,
               SUM(aum_usd)    AS aum_usd
        FROM unk
        """
    ).fetchone()
    pair_count, row_count, aum_usd = row
    pair_count = int(pair_count or 0)
    row_count = int(row_count or 0)
    aum_usd = float(aum_usd or 0.0)

    def diverged(actual, expected, tol):
        if expected == 0:
            return actual != 0
        return abs(actual - expected) / expected > tol

    if diverged(pair_count, EXPECTED_PAIR_COUNT, TOLERANCE) or \
       diverged(row_count, EXPECTED_ROW_COUNT, TOLERANCE):
        raise SystemExit(
            f"ABORT: cohort drifted from PR #246 (>{int(TOLERANCE*100)}%). "
            f"observed=(pairs={pair_count}, rows={row_count:,}, "
            f"aum=${aum_usd:,.2f}); "
            f"expected=({EXPECTED_PAIR_COUNT}, {EXPECTED_ROW_COUNT:,}, "
            f"~${EXPECTED_AUM_USD:,.2f}). Do not proceed."
        )

    return {
        "pair_count": pair_count,
        "row_count": row_count,
        "aum_usd": aum_usd,
    }


# ---------------------------------------------------------------------------
# Phase 2 — build per-pair manifest with branch classification
# ---------------------------------------------------------------------------

def build_manifest(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """For each (fund_cik, fund_name) pair under series_id='UNKNOWN' is_latest=TRUE,
    look up SYN_* companion via exact CIK + normalized fund_name match.
    Branch:
      - SYN match exists with any is_latest=TRUE row -> BRANCH 1 (FLIP).
      - No SYN match found at all                    -> BRANCH 2 (HOLD_NO_MATCH).
      - SYN match exists but no is_latest=TRUE rows  -> BRANCH 3 (HOLD_SYN_INACTIVE).
    """
    unk_rows = con.execute(
        """
        SELECT fund_cik,
               fund_name,
               COUNT(*)                              AS unk_row_count,
               SUM(COALESCE(market_value_usd,0))     AS unk_aum_usd
        FROM fund_holdings_v2
        WHERE series_id='UNKNOWN' AND is_latest=TRUE
        GROUP BY fund_cik, fund_name
        ORDER BY unk_aum_usd DESC
        """
    ).fetchall()

    syn_rows = con.execute(
        """
        SELECT fund_cik,
               fund_name,
               series_id,
               SUM(CASE WHEN is_latest=TRUE  THEN 1 ELSE 0 END) AS syn_latest_rows,
               SUM(CASE WHEN is_latest=FALSE THEN 1 ELSE 0 END) AS syn_old_rows
        FROM fund_holdings_v2
        WHERE series_id LIKE 'SYN_%'
        GROUP BY fund_cik, fund_name, series_id
        """
    ).fetchall()

    syn_idx: dict[tuple[str, str], list[tuple[str, int, int, str]]] = {}
    for cik, fname, sid, latest_n, old_n in syn_rows:
        key = (cik, norm(fname))
        syn_idx.setdefault(key, []).append((sid, int(latest_n or 0), int(old_n or 0), fname))

    fu_strategy = {
        sid: strat
        for sid, strat in con.execute(
            "SELECT series_id, fund_strategy FROM fund_universe WHERE series_id LIKE 'SYN_%'"
        ).fetchall()
    }

    manifest: list[dict] = []
    for cik, fname, urs, uaum in unk_rows:
        key = (cik, norm(fname))
        candidates = syn_idx.get(key, [])
        if not candidates:
            branch = "HOLD_NO_MATCH"
            syn_sid = None
            syn_strategy = None
            syn_latest_rows = 0
            syn_old_rows = 0
            syn_matched_name = None
        else:
            best = max(candidates, key=lambda c: c[1])
            syn_sid, syn_latest_rows, syn_old_rows, syn_matched_name = best
            syn_strategy = fu_strategy.get(syn_sid)
            if syn_latest_rows > 0:
                branch = "FLIP"
            else:
                branch = "HOLD_SYN_INACTIVE"

        manifest.append({
            "fund_cik": cik,
            "fund_name": fname,
            "unknown_row_count": int(urs or 0),
            "unknown_aum_usd": float(uaum or 0.0),
            "branch": branch,
            "syn_series_id": syn_sid or "",
            "syn_fund_strategy": syn_strategy or "",
            "syn_matched_name": syn_matched_name or "",
            "syn_latest_rows": syn_latest_rows,
            "syn_old_rows": syn_old_rows,
        })

    return manifest


def write_manifest_csv(manifest: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "fund_cik",
                "fund_name",
                "unknown_row_count",
                "unknown_aum_usd",
                "branch",
                "syn_series_id",
                "syn_fund_strategy",
                "syn_matched_name",
                "syn_latest_rows",
                "syn_old_rows",
            ],
        )
        writer.writeheader()
        for r in manifest:
            writer.writerow({
                "fund_cik": r["fund_cik"],
                "fund_name": r["fund_name"],
                "unknown_row_count": r["unknown_row_count"],
                "unknown_aum_usd": f"{r['unknown_aum_usd']:.2f}",
                "branch": r["branch"],
                "syn_series_id": r["syn_series_id"],
                "syn_fund_strategy": r["syn_fund_strategy"],
                "syn_matched_name": r["syn_matched_name"],
                "syn_latest_rows": r["syn_latest_rows"],
                "syn_old_rows": r["syn_old_rows"],
            })


def write_dryrun_doc(manifest: list[dict], cohort: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    by_branch: dict[str, dict] = {
        "FLIP": {"pairs": 0, "rows": 0, "aum": 0.0},
        "HOLD_NO_MATCH": {"pairs": 0, "rows": 0, "aum": 0.0},
        "HOLD_SYN_INACTIVE": {"pairs": 0, "rows": 0, "aum": 0.0},
    }
    for r in manifest:
        agg = by_branch[r["branch"]]
        agg["pairs"] += 1
        agg["rows"] += r["unknown_row_count"]
        agg["aum"] += r["unknown_aum_usd"]

    lines: list[str] = []
    lines.append("# fund-stale-unknown-cleanup — Phase 2 dry-run manifest")
    lines.append("")
    lines.append(f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_")
    lines.append("")
    lines.append("## Cohort re-validation")
    lines.append("")
    lines.append(f"- (fund_cik, fund_name) pairs where `series_id='UNKNOWN'` AND `is_latest=TRUE`: **{cohort['pair_count']}**")
    lines.append(f"- Rows: **{cohort['row_count']:,}**")
    lines.append(f"- AUM (sum of market_value_usd): **${cohort['aum_usd']:,.2f}**")
    lines.append("")
    lines.append(
        f"Expected per PR #246 audit: {EXPECTED_PAIR_COUNT} / "
        f"{EXPECTED_ROW_COUNT:,} / ~${EXPECTED_AUM_USD:,.2f}. "
        f"Drift gate: ±{int(TOLERANCE*100)}% on pair + row counts."
    )
    lines.append("")
    lines.append("## Branch breakdown")
    lines.append("")
    lines.append("| Branch | Pairs | UNKNOWN rows | UNKNOWN AUM (USD) | Action |")
    lines.append("|---|---:|---:|---:|---|")
    lines.append(
        f"| **BRANCH 1 — FLIP**              | {by_branch['FLIP']['pairs']:>3} | "
        f"{by_branch['FLIP']['rows']:>5,} | ${by_branch['FLIP']['aum']:,.2f} | "
        f"`UPDATE ... SET is_latest=FALSE` in Phase 3 |"
    )
    lines.append(
        f"| **BRANCH 2 — HOLD_NO_MATCH**     | {by_branch['HOLD_NO_MATCH']['pairs']:>3} | "
        f"{by_branch['HOLD_NO_MATCH']['rows']:>5,} | ${by_branch['HOLD_NO_MATCH']['aum']:,.2f} | "
        f"HOLD — no SYN_ companion; would orphan rows. Surfaced for chat. |"
    )
    lines.append(
        f"| **BRANCH 3 — HOLD_SYN_INACTIVE** | {by_branch['HOLD_SYN_INACTIVE']['pairs']:>3} | "
        f"{by_branch['HOLD_SYN_INACTIVE']['rows']:>5,} | ${by_branch['HOLD_SYN_INACTIVE']['aum']:,.2f} | "
        f"HOLD — SYN_ side also stale; different problem. Surfaced separately. |"
    )
    lines.append("")
    lines.append("## Per-pair manifest (sorted by UNKNOWN AUM DESC)")
    lines.append("")
    lines.append("| branch | fund_cik | fund_name | UNKNOWN rows | UNKNOWN AUM (USD) | SYN series_id | SYN strategy | SYN is_latest=TRUE rows | SYN is_latest=FALSE rows |")
    lines.append("|---|---|---|---:|---:|---|---|---:|---:|")
    for r in sorted(manifest, key=lambda x: -x["unknown_aum_usd"]):
        lines.append(
            f"| {r['branch']} | {r['fund_cik']} | {r['fund_name']} | "
            f"{r['unknown_row_count']:,} | ${r['unknown_aum_usd']:,.2f} | "
            f"`{r['syn_series_id'] or '—'}` | {r['syn_fund_strategy'] or '—'} | "
            f"{r['syn_latest_rows']} | {r['syn_old_rows']} |"
        )
    lines.append("")
    lines.append("## Phase 3 entry gate")
    lines.append("")
    if by_branch["HOLD_NO_MATCH"]["pairs"] or by_branch["HOLD_SYN_INACTIVE"]["pairs"]:
        lines.append(
            f"**STOP.** {by_branch['HOLD_NO_MATCH']['pairs']} BRANCH 2 + "
            f"{by_branch['HOLD_SYN_INACTIVE']['pairs']} BRANCH 3 pair(s) require "
            f"chat decision before --confirm can run. Per brief: do not synthesize "
            f"or rewrite series_id; surface findings instead."
        )
    else:
        lines.append("All pairs are BRANCH 1. Phase 3 may proceed with `--confirm`.")
    lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Phase 3 — execute is_latest flip
# ---------------------------------------------------------------------------

def load_manifest_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"ABORT: manifest not found at {path}. Run --dry-run first.")
    out: list[dict] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["unknown_row_count"] = int(row["unknown_row_count"])
            row["unknown_aum_usd"] = float(row["unknown_aum_usd"])
            row["syn_latest_rows"] = int(row["syn_latest_rows"])
            row["syn_old_rows"] = int(row["syn_old_rows"])
            out.append(row)
    return out


def execute_flip(
    con: duckdb.DuckDBPyConnection,
    manifest: list[dict],
    accept_deferred_holds: bool = False,
) -> dict:
    flip_rows = [r for r in manifest if r["branch"] == "FLIP"]
    hold = [r for r in manifest if r["branch"] != "FLIP"]

    # SYN_INACTIVE is a different problem — never accept silently.
    syn_inactive = [r for r in hold if r["branch"] == "HOLD_SYN_INACTIVE"]
    if syn_inactive:
        raise SystemExit(
            f"ABORT: manifest contains {len(syn_inactive)} HOLD_SYN_INACTIVE "
            f"pair(s). The SYN_ side is also stale; this is a separate "
            f"data-integrity problem and cannot be silently deferred."
        )

    no_match = [r for r in hold if r["branch"] == "HOLD_NO_MATCH"]
    if no_match and not accept_deferred_holds:
        raise SystemExit(
            f"ABORT: manifest contains {len(no_match)} HOLD_NO_MATCH "
            f"pair(s). Re-run with --accept-deferred-holds to skip them and "
            f"flip BRANCH 1 only, or re-run --dry-run with an all-BRANCH-1 "
            f"manifest."
        )
    if not flip_rows:
        raise SystemExit("ABORT: no BRANCH 1 (FLIP) pairs in manifest.")

    expected_flip_total = sum(r["unknown_row_count"] for r in flip_rows)

    pre_unknown_latest = con.execute(
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE series_id='UNKNOWN' AND is_latest=TRUE"
    ).fetchone()[0]
    print(f"[confirm] pre-flip UNKNOWN is_latest=TRUE rows: {pre_unknown_latest:,}")

    pairs_set = [(r["fund_cik"], r["fund_name"]) for r in flip_rows]
    print(f"[confirm] flipping {len(pairs_set)} (cik, fund_name) pairs, "
          f"expected row delta: {expected_flip_total:,}")

    con.execute("BEGIN")
    try:
        con.register("flip_pairs", _to_pairs_relation(pairs_set))
        con.execute(
            """
            UPDATE fund_holdings_v2
               SET is_latest = FALSE
             WHERE series_id = 'UNKNOWN'
               AND is_latest = TRUE
               AND (fund_cik, fund_name) IN (SELECT fund_cik, fund_name FROM flip_pairs)
            """
        )
        post_unknown_latest = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 WHERE series_id='UNKNOWN' AND is_latest=TRUE"
        ).fetchone()[0]
        actual_delta = pre_unknown_latest - post_unknown_latest
        print(f"[confirm] post-flip UNKNOWN is_latest=TRUE rows: {post_unknown_latest:,} "
              f"(Δ={actual_delta:,})")

        if actual_delta != expected_flip_total:
            raise SystemExit(
                f"ABORT: row delta mismatch — expected {expected_flip_total:,}, "
                f"got {actual_delta:,}. Rolling back."
            )
        con.execute("COMMIT")
    except SystemExit:
        con.execute("ROLLBACK")
        raise
    except Exception as exc:
        con.execute("ROLLBACK")
        raise SystemExit(f"ABORT: UPDATE failed mid-transaction: {exc}") from exc

    return {
        "pairs_flipped": len(pairs_set),
        "rows_flipped": expected_flip_total,
        "pre_unknown_latest": pre_unknown_latest,
        "post_unknown_latest": post_unknown_latest,
    }


def _to_pairs_relation(pairs: list[tuple[str, str]]):
    import pandas as pd
    return pd.DataFrame(pairs, columns=["fund_cik", "fund_name"])


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true",
                     help="Build manifest CSV + dryrun MD; no DB writes.")
    grp.add_argument("--confirm", action="store_true",
                     help="Read manifest CSV + execute is_latest flip in single transaction.")
    parser.add_argument(
        "--accept-deferred-holds",
        action="store_true",
        help=(
            "With --confirm: skip HOLD_NO_MATCH pairs and proceed with "
            "BRANCH 1 only. Use when HOLD pairs are explicitly deferred to "
            "another workstream (e.g. cef-attribution-path)."
        ),
    )
    args = parser.parse_args()

    if args.dry_run:
        con = duckdb.connect(str(PROD_DB), read_only=True)
        try:
            cohort = validate_cohort(con)
            print(
                f"[dry-run] cohort OK: pairs={cohort['pair_count']}, "
                f"rows={cohort['row_count']:,}, aum=${cohort['aum_usd']:,.2f}"
            )
            manifest = build_manifest(con)
        finally:
            con.close()

        write_manifest_csv(manifest, MANIFEST_CSV)
        write_dryrun_doc(manifest, cohort, DRYRUN_DOC)

        from collections import Counter
        c = Counter(r["branch"] for r in manifest)
        print(f"[dry-run] branches: FLIP={c.get('FLIP',0)}, "
              f"HOLD_NO_MATCH={c.get('HOLD_NO_MATCH',0)}, "
              f"HOLD_SYN_INACTIVE={c.get('HOLD_SYN_INACTIVE',0)}")
        print(f"[dry-run] manifest CSV: {MANIFEST_CSV}")
        print(f"[dry-run] dryrun doc:   {DRYRUN_DOC}")
        if c.get("HOLD_NO_MATCH", 0) or c.get("HOLD_SYN_INACTIVE", 0):
            print("[dry-run] STOP gate: HOLD branches present; --confirm refused "
                  "until manifest is all-BRANCH-1.")
        return

    if args.confirm:
        manifest = load_manifest_csv(MANIFEST_CSV)
        con = duckdb.connect(str(PROD_DB), read_only=False)
        try:
            cohort = validate_cohort(con)
            print(
                f"[confirm] cohort OK: pairs={cohort['pair_count']}, "
                f"rows={cohort['row_count']:,}, aum=${cohort['aum_usd']:,.2f}"
            )
            stats = execute_flip(con, manifest, accept_deferred_holds=args.accept_deferred_holds)
        finally:
            con.close()
        print(
            f"[confirm] DONE — flipped is_latest on {stats['rows_flipped']:,} rows "
            f"across {stats['pairs_flipped']} (cik, fund_name) pairs. "
            f"UNKNOWN is_latest=TRUE: {stats['pre_unknown_latest']:,} "
            f"→ {stats['post_unknown_latest']:,}."
        )
        return


if __name__ == "__main__":
    main()
