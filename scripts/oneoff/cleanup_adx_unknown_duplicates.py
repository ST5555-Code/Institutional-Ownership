#!/usr/bin/env python3
"""cleanup_adx_unknown_duplicates.py — cef-residual-cleanup-adx
(closes the ADX side of fund-stale-unknown-cleanup BRANCH 2 deferred
to PR #249).

Flips ``is_latest=FALSE`` on the 96 ADX (CIK 0000002230)
``series_id='UNKNOWN'`` rows in ``fund_holdings_v2`` that are
byte-identical duplicates of live ``SYN_0000002230`` companions. The
UNKNOWN side is migration-015 residue from the retired loader; the
SYN_ side is canonical (Apr-15 v2 loader, commit e868772).

Pattern precedent: scripts/oneoff/cleanup_stale_unknown.py (PR #247).
Differs in that ADX rows have no live SYN_ counterpart at the
(fund_cik, fund_name) pair level (UNKNOWN literal name vs. SYN_
fund_name), so verification anchors on ``(cusip, report_date)``
rather than fund_name.

Modes:
  --dry-run  (default) writes manifest CSV + dryrun findings MD; no DB writes.
  --confirm  reads the manifest CSV and flips is_latest=FALSE on FLIP
             rows only, in a single transaction.

Outputs:
  data/working/adx_unknown_cleanup_manifest.csv
  docs/findings/cef_residual_cleanup_adx_dryrun.md  (dry-run)
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "adx_unknown_cleanup_manifest.csv"
DRYRUN_DOC = BASE_DIR / "docs" / "findings" / "cef_residual_cleanup_adx_dryrun.md"

ADX_CIK = "0000002230"
SYN_SERIES_ID = "SYN_0000002230"
EXPECTED_ROW_COUNT = 96
EXPECTED_AUM_USD = 2_988_710_095.76
TOLERANCE = 0.05  # 5% drift gate on row count + AUM


# ---------------------------------------------------------------------------
# Phase 1 — re-validate cohort
# ---------------------------------------------------------------------------

def validate_cohort(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        f"""
        SELECT COUNT(*)                          AS row_count,
               SUM(COALESCE(market_value_usd,0)) AS aum_usd
        FROM fund_holdings_v2
        WHERE fund_cik='{ADX_CIK}'
          AND series_id='UNKNOWN'
          AND is_latest=TRUE
        """
    ).fetchone()
    row_count = int(row[0] or 0)
    aum_usd = float(row[1] or 0.0)

    def diverged(actual, expected, tol):
        if expected == 0:
            return actual != 0
        return abs(actual - expected) / expected > tol

    if diverged(row_count, EXPECTED_ROW_COUNT, TOLERANCE) or \
       diverged(aum_usd, EXPECTED_AUM_USD, TOLERANCE):
        raise SystemExit(
            f"ABORT: ADX UNKNOWN cohort drifted from PR #249 (>{int(TOLERANCE*100)}%). "
            f"observed=(rows={row_count:,}, aum=${aum_usd:,.2f}); "
            f"expected=({EXPECTED_ROW_COUNT:,}, ~${EXPECTED_AUM_USD:,.2f})."
        )

    syn_row = con.execute(
        f"""
        SELECT COUNT(*) FROM fund_holdings_v2
        WHERE fund_cik='{ADX_CIK}'
          AND series_id='{SYN_SERIES_ID}'
          AND is_latest=TRUE
        """
    ).fetchone()
    syn_latest_count = int(syn_row[0] or 0)
    if syn_latest_count == 0:
        raise SystemExit(
            f"ABORT: no SYN_{ADX_CIK[-4:]} companion rows with is_latest=TRUE. "
            f"Cannot drop UNKNOWN duplicates without a canonical companion."
        )

    return {
        "row_count": row_count,
        "aum_usd": aum_usd,
        "syn_latest_count": syn_latest_count,
    }


# ---------------------------------------------------------------------------
# Phase 2 — build per-row manifest with byte-identical classification
# ---------------------------------------------------------------------------

def build_manifest(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """For each ADX UNKNOWN row, look up SYN_ companion at the same
    (cusip, report_date). Compare quantity + descriptor columns.
    Classify each row as byte_identical | mismatch | orphan.
    Action is FLIP iff classification is byte_identical, else HOLD.
    """
    rows = con.execute(
        f"""
        WITH unk AS (
            SELECT cusip, report_date, accession_number,
                   market_value_usd, shares_or_principal, pct_of_nav,
                   issuer_name, asset_category, ticker, isin
            FROM fund_holdings_v2
            WHERE fund_cik='{ADX_CIK}'
              AND series_id='UNKNOWN'
              AND is_latest=TRUE
        ),
        syn AS (
            SELECT cusip, report_date,
                   market_value_usd, shares_or_principal, pct_of_nav,
                   issuer_name, asset_category, ticker, isin
            FROM fund_holdings_v2
            WHERE fund_cik='{ADX_CIK}'
              AND series_id='{SYN_SERIES_ID}'
              AND is_latest=TRUE
        )
        SELECT
            u.accession_number,
            u.report_date,
            u.cusip,
            u.market_value_usd,
            u.shares_or_principal,
            u.pct_of_nav,
            u.issuer_name,
            u.asset_category,
            u.ticker,
            u.isin,
            s.market_value_usd     AS syn_mv,
            s.shares_or_principal  AS syn_shares,
            s.pct_of_nav           AS syn_pct,
            s.issuer_name          AS syn_issuer,
            s.asset_category       AS syn_asset_cat,
            s.ticker               AS syn_ticker,
            s.isin                 AS syn_isin,
            (s.cusip IS NOT NULL)  AS has_syn,
            (s.cusip IS NOT NULL
             AND u.market_value_usd     IS NOT DISTINCT FROM s.market_value_usd
             AND u.shares_or_principal  IS NOT DISTINCT FROM s.shares_or_principal
             AND u.pct_of_nav           IS NOT DISTINCT FROM s.pct_of_nav
             AND u.issuer_name          IS NOT DISTINCT FROM s.issuer_name
             AND u.asset_category       IS NOT DISTINCT FROM s.asset_category
             AND u.ticker               IS NOT DISTINCT FROM s.ticker
             AND u.isin                 IS NOT DISTINCT FROM s.isin) AS is_byte_identical
        FROM unk u
        LEFT JOIN syn s
          ON s.cusip = u.cusip AND s.report_date = u.report_date
        ORDER BY u.report_date, u.cusip
        """
    ).fetchall()

    manifest: list[dict] = []
    for r in rows:
        if not r[17]:  # has_syn
            syn_match = "orphan"
        elif r[18]:  # is_byte_identical
            syn_match = "byte_identical"
        else:
            syn_match = "mismatch"
        action = "FLIP" if syn_match == "byte_identical" else "HOLD"
        manifest.append({
            "accession_number": r[0],
            "report_date": r[1].isoformat(),
            "cusip": r[2],
            "market_value_usd": float(r[3] or 0.0),
            "syn_match": syn_match,
            "action": action,
        })
    return manifest


def write_manifest_csv(manifest: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "accession_number",
                "report_date",
                "cusip",
                "market_value_usd",
                "syn_match",
                "action",
            ],
        )
        writer.writeheader()
        for r in manifest:
            writer.writerow({
                "accession_number": r["accession_number"],
                "report_date": r["report_date"],
                "cusip": r["cusip"],
                "market_value_usd": f"{r['market_value_usd']:.2f}",
                "syn_match": r["syn_match"],
                "action": r["action"],
            })


def write_dryrun_doc(manifest: list[dict], cohort: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_match: dict[str, dict] = {
        "byte_identical": {"rows": 0, "aum": 0.0},
        "mismatch": {"rows": 0, "aum": 0.0},
        "orphan": {"rows": 0, "aum": 0.0},
    }
    by_action: dict[str, dict] = {
        "FLIP": {"rows": 0, "aum": 0.0},
        "HOLD": {"rows": 0, "aum": 0.0},
    }
    for r in manifest:
        bm = by_match[r["syn_match"]]
        bm["rows"] += 1
        bm["aum"] += r["market_value_usd"]
        ba = by_action[r["action"]]
        ba["rows"] += 1
        ba["aum"] += r["market_value_usd"]

    periods: dict[str, int] = {}
    for r in manifest:
        periods[r["report_date"]] = periods.get(r["report_date"], 0) + 1

    accessions = sorted({r["accession_number"] for r in manifest})

    lines: list[str] = []
    lines.append("# cef-residual-cleanup-adx — Phase 2 dry-run manifest")
    lines.append("")
    lines.append(f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_")
    lines.append("")
    lines.append("## Cohort re-validation (Phase 1)")
    lines.append("")
    lines.append(f"- ADX (CIK `{ADX_CIK}`) UNKNOWN rows with `is_latest=TRUE`: **{cohort['row_count']:,}**")
    lines.append(f"- AUM (sum of market_value_usd): **${cohort['aum_usd']:,.2f}**")
    lines.append(f"- SYN_{ADX_CIK[-4:]} companion rows with `is_latest=TRUE`: **{cohort['syn_latest_count']:,}**")
    lines.append("")
    lines.append(
        f"Expected per PR #249: {EXPECTED_ROW_COUNT:,} rows / "
        f"~${EXPECTED_AUM_USD:,.2f}. "
        f"Drift gate: ±{int(TOLERANCE*100)}% on row count + AUM."
    )
    lines.append("")
    lines.append("## Period coverage")
    lines.append("")
    lines.append("| Period | UNKNOWN rows |")
    lines.append("|---|---:|")
    for p in sorted(periods):
        lines.append(f"| {p} | {periods[p]:,} |")
    lines.append("")
    lines.append("## Accession verification")
    lines.append("")
    for a in accessions:
        lines.append(f"- `{a}`")
    lines.append("")
    lines.append("## SYN-match classification")
    lines.append("")
    lines.append("| Classification | Rows | AUM (USD) | Action |")
    lines.append("|---|---:|---:|---|")
    lines.append(
        f"| **byte_identical** | {by_match['byte_identical']['rows']:>4,} | "
        f"${by_match['byte_identical']['aum']:,.2f} | FLIP `is_latest=FALSE` in Phase 3 |"
    )
    lines.append(
        f"| **mismatch**       | {by_match['mismatch']['rows']:>4,} | "
        f"${by_match['mismatch']['aum']:,.2f} | HOLD — surfaced for chat decision |"
    )
    lines.append(
        f"| **orphan**         | {by_match['orphan']['rows']:>4,} | "
        f"${by_match['orphan']['aum']:,.2f} | HOLD — no SYN companion |"
    )
    lines.append("")
    lines.append(
        f"Action totals: **FLIP={by_action['FLIP']['rows']:,} rows / "
        f"${by_action['FLIP']['aum']:,.2f}**, "
        f"HOLD={by_action['HOLD']['rows']:,} rows / ${by_action['HOLD']['aum']:,.2f}."
    )
    lines.append("")
    lines.append("## Phase 3 entry gate")
    lines.append("")
    if by_action["HOLD"]["rows"] > 0:
        lines.append(
            f"**STOP.** {by_action['HOLD']['rows']:,} HOLD row(s) require "
            f"chat decision before --confirm can run."
        )
    else:
        lines.append("All rows are FLIP. Phase 3 may proceed with `--confirm`.")
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
            row["market_value_usd"] = float(row["market_value_usd"])
            out.append(row)
    return out


def execute_flip(
    con: duckdb.DuckDBPyConnection,
    manifest: list[dict],
) -> dict:
    flip_rows = [r for r in manifest if r["action"] == "FLIP"]
    hold_rows = [r for r in manifest if r["action"] != "FLIP"]

    if hold_rows:
        raise SystemExit(
            f"ABORT: manifest contains {len(hold_rows)} HOLD row(s). "
            f"Resolve in chat and re-run --dry-run before --confirm."
        )
    if not flip_rows:
        raise SystemExit("ABORT: no FLIP rows in manifest.")

    expected_flip = len(flip_rows)

    pre = con.execute(
        f"""
        SELECT COUNT(*) FROM fund_holdings_v2
        WHERE fund_cik='{ADX_CIK}' AND series_id='UNKNOWN' AND is_latest=TRUE
        """
    ).fetchone()[0]
    print(f"[confirm] pre-flip ADX UNKNOWN is_latest=TRUE rows: {pre:,}")
    print(f"[confirm] flipping {expected_flip:,} rows by (cusip, report_date)")

    import pandas as pd
    keys = pd.DataFrame(
        [(r["cusip"], r["report_date"]) for r in flip_rows],
        columns=["cusip", "report_date"],
    )
    keys["report_date"] = pd.to_datetime(keys["report_date"]).dt.date

    con.execute("BEGIN")
    try:
        con.register("flip_keys", keys)
        con.execute(
            f"""
            UPDATE fund_holdings_v2
               SET is_latest = FALSE
             WHERE fund_cik = '{ADX_CIK}'
               AND series_id = 'UNKNOWN'
               AND is_latest = TRUE
               AND (cusip, report_date) IN (
                   SELECT cusip, report_date FROM flip_keys
               )
            """
        )
        post = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_holdings_v2
            WHERE fund_cik='{ADX_CIK}' AND series_id='UNKNOWN' AND is_latest=TRUE
            """
        ).fetchone()[0]
        actual_delta = pre - post
        print(f"[confirm] post-flip ADX UNKNOWN is_latest=TRUE rows: {post:,} "
              f"(Δ={actual_delta:,})")
        if actual_delta != expected_flip:
            raise SystemExit(
                f"ABORT: row delta mismatch — expected {expected_flip:,}, "
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
        "rows_flipped": expected_flip,
        "pre_unknown_latest": pre,
        "post_unknown_latest": post,
    }


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
        "--db", type=str, default=str(DEFAULT_DB),
        help=f"Path to DuckDB. Default: {DEFAULT_DB}",
    )
    parser.add_argument(
        "--manifest", type=str, default=str(MANIFEST_CSV),
        help="Manifest CSV path.",
    )
    parser.add_argument(
        "--findings", type=str, default=str(DRYRUN_DOC),
        help="Dry-run findings markdown path.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    manifest_path = Path(args.manifest)
    findings_path = Path(args.findings)

    if args.dry_run:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            cohort = validate_cohort(con)
            print(
                f"[dry-run] cohort OK: rows={cohort['row_count']:,}, "
                f"aum=${cohort['aum_usd']:,.2f}, "
                f"syn_latest={cohort['syn_latest_count']:,}"
            )
            manifest = build_manifest(con)
        finally:
            con.close()

        write_manifest_csv(manifest, manifest_path)
        write_dryrun_doc(manifest, cohort, findings_path)

        from collections import Counter
        c = Counter(r["syn_match"] for r in manifest)
        a = Counter(r["action"] for r in manifest)
        print(f"[dry-run] classification: byte_identical={c.get('byte_identical',0)}, "
              f"mismatch={c.get('mismatch',0)}, orphan={c.get('orphan',0)}")
        print(f"[dry-run] action: FLIP={a.get('FLIP',0)}, HOLD={a.get('HOLD',0)}")
        print(f"[dry-run] manifest CSV: {manifest_path}")
        print(f"[dry-run] dryrun doc:   {findings_path}")
        if a.get("HOLD", 0):
            print("[dry-run] STOP gate: HOLD rows present; --confirm refused "
                  "until manifest is all-FLIP.")
        return

    if args.confirm:
        manifest = load_manifest_csv(manifest_path)
        con = duckdb.connect(str(db_path), read_only=False)
        try:
            cohort = validate_cohort(con)
            print(
                f"[confirm] cohort OK: rows={cohort['row_count']:,}, "
                f"aum=${cohort['aum_usd']:,.2f}, "
                f"syn_latest={cohort['syn_latest_count']:,}"
            )
            stats = execute_flip(con, manifest)
        finally:
            con.close()
        print(
            f"[confirm] DONE — flipped is_latest on {stats['rows_flipped']:,} ADX "
            f"UNKNOWN rows. UNKNOWN is_latest=TRUE: "
            f"{stats['pre_unknown_latest']:,} → {stats['post_unknown_latest']:,}."
        )
        return


if __name__ == "__main__":
    main()
