#!/usr/bin/env python3
"""backfill_orphan_fund_universe.py — fund-orphan-backfill (closes the
302-series / 160,934-row exposure surfaced by PR #244).

Inserts canonical rows into ``fund_universe`` for S9-digit orphan
``series_id`` values that have holdings in ``fund_holdings_v2`` but no
matching row in ``fund_universe``. Read-only with respect to existing
fund_universe rows — INSERT-only, no UPDATE path. Safe alongside
PR-2 pipeline lock.

PR #248 forward-looking patch: now also derives ``total_net_assets``
per series during manifest construction and writes it on INSERT.

  Canonical: NAV = MEDIAN(market_value_usd * 100.0 / pct_of_nav) on the
             most-recent quarter's is_latest=TRUE rows. ``pct_of_nav`` is
             stored on the percent scale (0–100); validated against funds
             with existing ``total_net_assets`` (ratio = 1.000000…).
  Fallback : NAV = SUM(market_value_usd) when no row has usable
             pct_of_nav. ``strategy_source`` suffixed
             ``|aum_summed_fallback`` for those rows.
  Null-res : NAV stays NULL when neither path resolves; surfaced in
             the dryrun manifest's ``nav_source`` column for review.

Cohort scope (per PR #244 audit):
  * S9digit (``S\\d{9}``)        — backfill candidates (~301 series).
  * UNKNOWN_literal (``UNKNOWN``) — left orphan by design (1 series,
    3,184 rows, $10.0B). Multiple historic fund_names funnel into the
    literal sentinel; no canonical resolution available without source
    rework.

Per-fund deferred decisions (P3 SKIP list):
  * Calamos Global Total Return Fund                — defer
  * Eaton Vance Tax-Advantaged Dividend Income Fund — defer
  In current data both these names live under ``series_id='UNKNOWN'``
  (UNKNOWN_literal cohort, already orphan by design). The S9digit
  ILIKE-match step is therefore a no-op safety net.

Manual override (1 entry):
  * S000045538 (Blackstone Alternative Multi-Strategy Fund) → multi_asset
    Snapshot fund_strategy_at_filing is exclusively 'bond_or_other'
    (legacy auto-classification artifact). The fund is a multi-manager
    hedge fund replication vehicle, not a bond fund.

Strategy derivation (S9digit, non-skip, non-override):
  Majority vote on ``fund_strategy_at_filing`` weighted by
  ``market_value_usd``, ``is_latest = TRUE``. Tiebreak: most-recent
  ``quarter``. If no non-NULL strategy votes, ABORT — never synthesize a
  default.

Modes:
  --dry-run  (default) writes manifest CSV + findings markdown only;
             no DB writes. Read-only DuckDB connection.
  --confirm  reads the existing manifest CSV and INSERTs rows in a
             single transaction. Refuses to run if the manifest is
             missing or if Phase 1 inventory has drifted.

Outputs:
  data/working/orphan_backfill_manifest.csv
  docs/findings/fund_orphan_backfill_dryrun.md  (dry-run mode)

Pattern precedent: PR #233 (fund-strategy-backfill), PR #235
(peer-rotation-rebuild).
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
PROD_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "orphan_backfill_manifest.csv"
DRYRUN_DOC = BASE_DIR / "docs" / "findings" / "fund_orphan_backfill_dryrun.md"

EXPECTED_DISTINCT_SERIES = 302
EXPECTED_ROW_COUNT = 160_934
EXPECTED_AUM_USD = 658_486_891_871.78  # $658.5B
TOLERANCE = 0.05  # 5%

CANONICAL_STRATEGIES = (
    "active",
    "balanced",
    "multi_asset",
    "passive",
    "bond_or_other",
    "excluded",
    "final_filing",
)

SKIP_NAME_PATTERNS = (
    "Calamos Global Total Return%",
    "Eaton Vance Tax-Advantaged%",
)

OVERRIDES = {
    # series_id -> (fund_strategy, rationale)
    "S000045538": (
        "multi_asset",
        "Blackstone Alternative Multi-Strategy Fund — multi-manager hedge "
        "fund replication, not bond. Snapshot exclusively 'bond_or_other' "
        "(legacy auto-classification artifact).",
    ),
}

STRATEGY_SOURCE_TAG = "orphan_backfill_2026Q2"


# ---------------------------------------------------------------------------
# Phase 1 — re-validate inventory
# ---------------------------------------------------------------------------

def validate_inventory(con: duckdb.DuckDBPyConnection) -> dict:
    """Re-run Phase 1 totals; abort on >TOLERANCE drift."""
    row = con.execute(
        """
        WITH orphan AS (
            SELECT fh.* FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu USING (series_id)
            WHERE fu.series_id IS NULL
        )
        SELECT COUNT(DISTINCT series_id) AS distinct_series,
               COUNT(*)                  AS row_count,
               SUM(market_value_usd)     AS aum_usd
        FROM orphan WHERE is_latest = TRUE
        """
    ).fetchone()
    distinct_series, row_count, aum_usd = row
    aum_usd = float(aum_usd or 0.0)

    def diverged(actual, expected):
        if expected == 0:
            return actual != 0
        return abs(actual - expected) / expected > TOLERANCE

    if (
        diverged(distinct_series, EXPECTED_DISTINCT_SERIES)
        or diverged(row_count, EXPECTED_ROW_COUNT)
        or diverged(aum_usd, EXPECTED_AUM_USD)
    ):
        raise SystemExit(
            f"ABORT: orphan inventory diverged from PR #244 audit "
            f"(>{int(TOLERANCE*100)}%). "
            f"observed=(series={distinct_series}, rows={row_count}, "
            f"aum=${aum_usd:,.2f}); "
            f"expected=({EXPECTED_DISTINCT_SERIES}, {EXPECTED_ROW_COUNT}, "
            f"${EXPECTED_AUM_USD:,.2f}). Cohort changed since audit; "
            f"do not proceed."
        )

    return {
        "distinct_series": distinct_series,
        "row_count": row_count,
        "aum_usd": aum_usd,
    }


# ---------------------------------------------------------------------------
# Phase 2 — derivation
# ---------------------------------------------------------------------------

def derive_manifest(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Build per-series manifest entries.

    For every S9-digit orphan series_id (is_latest=TRUE):
      - Resolve fund_name = MAX(fund_name) FROM fund_holdings_v2 (fallback
        series_id literal).
      - Resolve fund_cik = MODE(fund_cik) — primary CIK by row count.
      - Apply SKIP / OVERRIDE / majority-vote in that order.

    UNKNOWN_literal cohort is NOT included; it stays orphan by design.
    """
    rows = con.execute(
        f"""
        WITH orphan AS (
            SELECT fh.*
            FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu USING (series_id)
            WHERE fu.series_id IS NULL AND fh.is_latest = TRUE
        ),
        s9 AS (
            SELECT *
            FROM orphan
            WHERE regexp_matches(series_id, '^S[0-9]{{9}}$')
        ),
        nav_per_q AS (
            SELECT series_id, quarter,
                   MEDIAN(CASE WHEN pct_of_nav IS NOT NULL AND pct_of_nav > 0
                               THEN market_value_usd * 100.0 / pct_of_nav END)
                                                            AS implied_nav,
                   SUM(market_value_usd)                    AS sum_mv
            FROM s9
            GROUP BY series_id, quarter
        ),
        nav_ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY series_id ORDER BY quarter DESC
                   ) AS rn
            FROM nav_per_q
        ),
        nav_pick AS (
            SELECT series_id, implied_nav, sum_mv
            FROM nav_ranked WHERE rn = 1
        ),
        agg AS (
            SELECT
                series_id,
                MAX(fund_name)              AS fund_name,
                MODE(fund_cik)              AS fund_cik,
                COUNT(*)                    AS row_count,
                SUM(market_value_usd)       AS aum_usd
            FROM s9
            GROUP BY series_id
        ),
        weighted AS (
            SELECT
                series_id,
                fund_strategy_at_filing,
                SUM(market_value_usd)        AS weight,
                MAX(quarter)                 AS most_recent_quarter
            FROM s9
            WHERE fund_strategy_at_filing IS NOT NULL
              AND fund_strategy_at_filing IN (
                  'active','balanced','multi_asset',
                  'passive','bond_or_other','excluded','final_filing'
              )
            GROUP BY series_id, fund_strategy_at_filing
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY series_id
                       ORDER BY weight DESC NULLS LAST,
                                most_recent_quarter DESC NULLS LAST
                   ) AS rn
            FROM weighted
        ),
        winners AS (
            SELECT series_id,
                   fund_strategy_at_filing AS derived_strategy,
                   weight                  AS winning_weight
            FROM ranked WHERE rn = 1
        ),
        totals AS (
            SELECT series_id, SUM(weight) AS total_weight
            FROM weighted GROUP BY series_id
        )
        SELECT
            agg.series_id,
            agg.fund_name,
            agg.fund_cik,
            agg.row_count,
            agg.aum_usd,
            winners.derived_strategy,
            COALESCE(winners.winning_weight / NULLIF(totals.total_weight, 0), 0.0)
                AS support_pct,
            nav_pick.implied_nav,
            nav_pick.sum_mv
        FROM agg
        LEFT JOIN winners  USING (series_id)
        LEFT JOIN totals   USING (series_id)
        LEFT JOIN nav_pick USING (series_id)
        ORDER BY agg.row_count DESC
        """
    ).fetchall()

    manifest: list[dict] = []
    for (series_id, fund_name, fund_cik, row_count, aum_usd, derived,
         support, implied_nav, sum_mv) in rows:
        # Canonical N-PORT TotalNetAssets reconstruction.
        # pct_of_nav is on percent scale (0–100); validated against funds
        # with existing total_net_assets at ratio = 1.000000…
        # See PR #248 / docs/findings/fund_universe_corrections_results.md.
        if implied_nav is not None and float(implied_nav) > 0:
            total_net_assets = float(implied_nav)
            nav_source = "canonical_nport"
        elif sum_mv is not None and float(sum_mv) > 0:
            total_net_assets = float(sum_mv)
            nav_source = "aum_summed_fallback"
        else:
            total_net_assets = None
            nav_source = "null_residual"
        # Fallbacks
        if not fund_name:
            fund_name = series_id

        # Step 1 — SKIP list (per-fund-deferred-decisions P3)
        skip = False
        if fund_name:
            for pat in SKIP_NAME_PATTERNS:
                # ILIKE semantics: case-insensitive, % wildcard
                lit = pat.rstrip("%").lower()
                if fund_name.lower().startswith(lit):
                    skip = True
                    break
        if skip:
            manifest.append({
                "series_id": series_id,
                "fund_name": fund_name,
                "fund_cik": fund_cik,
                "row_count": int(row_count),
                "aum_usd": float(aum_usd or 0.0),
                "derived_strategy": "",
                "support_pct": 0.0,
                "source": "skip",
                "total_net_assets": total_net_assets,
                "nav_source": nav_source,
            })
            continue

        # Step 2 — Manual override
        if series_id in OVERRIDES:
            override_strategy, _ = OVERRIDES[series_id]
            manifest.append({
                "series_id": series_id,
                "fund_name": fund_name,
                "fund_cik": fund_cik,
                "row_count": int(row_count),
                "aum_usd": float(aum_usd or 0.0),
                "derived_strategy": override_strategy,
                "support_pct": float(support or 0.0),
                "source": "override",
                "total_net_assets": total_net_assets,
                "nav_source": nav_source,
            })
            continue

        # Step 3 — Majority vote
        if not derived:
            raise SystemExit(
                f"ABORT: series_id={series_id} has no non-NULL "
                f"fund_strategy_at_filing votes. Refusing to synthesize "
                f"a default. Investigate manually."
            )
        manifest.append({
            "series_id": series_id,
            "fund_name": fund_name,
            "fund_cik": fund_cik,
            "row_count": int(row_count),
            "aum_usd": float(aum_usd or 0.0),
            "derived_strategy": derived,
            "support_pct": float(support or 0.0),
            "source": "majority",
            "total_net_assets": total_net_assets,
            "nav_source": nav_source,
        })

    return manifest


# ---------------------------------------------------------------------------
# Phase 2 outputs
# ---------------------------------------------------------------------------

def write_manifest_csv(manifest: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "series_id",
                "fund_name",
                "fund_cik",
                "derived_strategy",
                "support_pct",
                "row_count",
                "aum_usd",
                "source",
                "total_net_assets",
                "nav_source",
            ],
        )
        writer.writeheader()
        for r in manifest:
            tna = r.get("total_net_assets")
            writer.writerow({
                "series_id": r["series_id"],
                "fund_name": r["fund_name"],
                "fund_cik": r.get("fund_cik") or "",
                "derived_strategy": r["derived_strategy"],
                "support_pct": f"{r['support_pct']:.6f}",
                "row_count": r["row_count"],
                "aum_usd": f"{r['aum_usd']:.2f}",
                "source": r["source"],
                "total_net_assets": (
                    f"{tna:.2f}" if tna is not None else ""
                ),
                "nav_source": r.get("nav_source", ""),
            })


def write_dryrun_doc(
    manifest: list[dict],
    inventory: dict,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    insert_rows = [r for r in manifest if r["source"] != "skip"]
    skip_rows = [r for r in manifest if r["source"] == "skip"]

    # Group totals by derived_strategy (insert rows only)
    by_strategy: dict[str, dict] = {}
    for r in insert_rows:
        s = r["derived_strategy"]
        agg = by_strategy.setdefault(s, {"series": 0, "rows": 0, "aum": 0.0})
        agg["series"] += 1
        agg["rows"] += r["row_count"]
        agg["aum"] += r["aum_usd"]

    lines: list[str] = []
    lines.append("# fund-orphan-backfill — Phase 2 dry-run manifest")
    lines.append("")
    lines.append(f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_")
    lines.append("")
    lines.append("## Inventory re-validation")
    lines.append("")
    lines.append(f"- Distinct orphan series (`is_latest=TRUE`): **{inventory['distinct_series']}**")
    lines.append(f"- Orphan rows: **{inventory['row_count']:,}**")
    lines.append(f"- Orphan AUM: **${inventory['aum_usd']:,.2f}**")
    lines.append("")
    lines.append(
        f"Expected per PR #244 audit: "
        f"{EXPECTED_DISTINCT_SERIES} / {EXPECTED_ROW_COUNT:,} / "
        f"${EXPECTED_AUM_USD:,.2f}. Drift within ±{int(TOLERANCE*100)}%."
    )
    lines.append("")
    lines.append("## Group totals by derived_strategy (INSERT scope)")
    lines.append("")
    lines.append("| Strategy | Series | Rows | AUM (USD) |")
    lines.append("|---|---:|---:|---:|")
    for strat, agg in sorted(by_strategy.items(), key=lambda kv: -kv[1]["rows"]):
        lines.append(
            f"| {strat} | {agg['series']:,} | {agg['rows']:,} | "
            f"${agg['aum']:,.2f} |"
        )
    lines.append(
        f"| **TOTAL (INSERTs)** | **{len(insert_rows):,}** | "
        f"**{sum(r['row_count'] for r in insert_rows):,}** | "
        f"**${sum(r['aum_usd'] for r in insert_rows):,.2f}** |"
    )
    lines.append("")
    lines.append("## SKIP list (per-fund-deferred-decisions P3)")
    lines.append("")
    if skip_rows:
        lines.append("| series_id | fund_name | rows | AUM (USD) |")
        lines.append("|---|---|---:|---:|")
        for r in skip_rows:
            lines.append(
                f"| `{r['series_id']}` | {r['fund_name']} | "
                f"{r['row_count']:,} | ${r['aum_usd']:,.2f} |"
            )
    else:
        lines.append(
            "_No S9-digit orphan series matched the SKIP-name patterns._ "
            "Calamos Global Total Return Fund and Eaton Vance Tax-Advantaged "
            "Dividend Income Fund both currently funnel into "
            "`series_id='UNKNOWN'` (UNKNOWN_literal cohort), which is "
            "orphan by design and out of scope for this PR."
        )
    lines.append("")
    lines.append("## Manifest (sorted by row_count DESC)")
    lines.append("")
    lines.append("| series_id | fund_name | derived_strategy | support_pct | rows | AUM (USD) | source |")
    lines.append("|---|---|---|---:|---:|---:|---|")
    for r in sorted(manifest, key=lambda x: -x["row_count"]):
        lines.append(
            f"| `{r['series_id']}` | {r['fund_name']} | "
            f"{r['derived_strategy'] or '—'} | "
            f"{r['support_pct']*100:.1f}% | "
            f"{r['row_count']:,} | ${r['aum_usd']:,.2f} | "
            f"{r['source']} |"
        )
    lines.append("")

    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Phase 3 — execute backfill
# ---------------------------------------------------------------------------

def load_manifest_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"ABORT: manifest not found at {path}. "
            f"Run --dry-run first."
        )
    out: list[dict] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["row_count"] = int(row["row_count"])
            row["aum_usd"] = float(row["aum_usd"])
            row["support_pct"] = float(row["support_pct"])
            tna_str = row.get("total_net_assets") or ""
            row["total_net_assets"] = (
                float(tna_str) if tna_str else None
            )
            row["nav_source"] = row.get("nav_source", "") or ""
            out.append(row)
    return out


def execute_backfill(con: duckdb.DuckDBPyConnection, manifest: list[dict]) -> dict:
    """Single-transaction INSERT of manifest rows where source != 'skip'."""
    inserts = [r for r in manifest if r["source"] != "skip"]
    if not inserts:
        raise SystemExit("ABORT: no manifest rows eligible for INSERT.")

    # Validate canonical strategy values
    bad = [r for r in inserts if r["derived_strategy"] not in CANONICAL_STRATEGIES]
    if bad:
        raise SystemExit(
            f"ABORT: {len(bad)} manifest rows have non-canonical "
            f"derived_strategy values: "
            f"{[(r['series_id'], r['derived_strategy']) for r in bad[:5]]}"
        )

    # Pre-check: ensure no manifest series_id already in fund_universe
    sids = [r["series_id"] for r in inserts]
    placeholders = ",".join(["?"] * len(sids))
    existing = con.execute(
        f"SELECT series_id FROM fund_universe WHERE series_id IN ({placeholders})",
        sids,
    ).fetchall()
    if existing:
        raise SystemExit(
            f"ABORT: {len(existing)} manifest series_id values already "
            f"exist in fund_universe (cohort drift). "
            f"Sample: {[e[0] for e in existing[:5]]}"
        )

    pre_count = con.execute("SELECT COUNT(*) FROM fund_universe").fetchone()[0]
    print(f"[backfill] fund_universe rows pre-INSERT: {pre_count:,}")

    now = datetime.utcnow()
    rows_inserted = 0
    con.execute("BEGIN")
    try:
        for r in inserts:
            tna = r.get("total_net_assets")
            nav_source = r.get("nav_source") or "null_residual"
            row_source_tag = (
                STRATEGY_SOURCE_TAG + "|aum_summed_fallback"
                if nav_source == "aum_summed_fallback"
                else STRATEGY_SOURCE_TAG
            )
            con.execute(
                """
                INSERT INTO fund_universe (
                    fund_cik, fund_name, series_id, family_name,
                    total_net_assets, total_holdings_count,
                    equity_pct, top10_concentration,
                    last_updated, fund_strategy,
                    best_index, strategy_narrative,
                    strategy_source, strategy_fetched_at
                ) VALUES (
                    ?, ?, ?, NULL,
                    ?, NULL,
                    NULL, NULL,
                    ?, ?,
                    NULL, NULL,
                    ?, ?
                )
                """,
                [
                    r["fund_cik"] or None,
                    r["fund_name"],
                    r["series_id"],
                    tna,
                    now,
                    r["derived_strategy"],
                    row_source_tag,
                    now,
                ],
            )
            rows_inserted += 1
        con.execute("COMMIT")
    except Exception as exc:
        con.execute("ROLLBACK")
        raise SystemExit(f"ABORT: INSERT failed mid-transaction: {exc}") from exc

    post_count = con.execute("SELECT COUNT(*) FROM fund_universe").fetchone()[0]
    delta = post_count - pre_count
    print(f"[backfill] fund_universe rows post-INSERT: {post_count:,} (Δ={delta:,})")

    if delta != rows_inserted:
        raise SystemExit(
            f"ABORT: row delta mismatch — expected {rows_inserted}, "
            f"got {delta}."
        )

    return {
        "pre_count": pre_count,
        "post_count": post_count,
        "rows_inserted": rows_inserted,
        "skip_count": len(manifest) - len(inserts),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--dry-run",
        action="store_true",
        help="Build manifest CSV + findings markdown; no DB writes.",
    )
    grp.add_argument(
        "--confirm",
        action="store_true",
        help="Read manifest CSV + execute INSERTs in a single transaction.",
    )
    args = parser.parse_args()

    if args.dry_run:
        con = duckdb.connect(str(PROD_DB), read_only=True)
        try:
            inventory = validate_inventory(con)
            print(
                f"[dry-run] inventory OK: "
                f"series={inventory['distinct_series']}, "
                f"rows={inventory['row_count']:,}, "
                f"aum=${inventory['aum_usd']:,.2f}"
            )
            manifest = derive_manifest(con)
        finally:
            con.close()

        write_manifest_csv(manifest, MANIFEST_CSV)
        write_dryrun_doc(manifest, inventory, DRYRUN_DOC)

        insert_n = sum(1 for r in manifest if r["source"] != "skip")
        skip_n = sum(1 for r in manifest if r["source"] == "skip")
        override_n = sum(1 for r in manifest if r["source"] == "override")
        majority_n = sum(1 for r in manifest if r["source"] == "majority")
        print(
            f"[dry-run] manifest entries: total={len(manifest)} "
            f"(majority={majority_n}, override={override_n}, skip={skip_n}); "
            f"would INSERT {insert_n} rows."
        )
        print(f"[dry-run] manifest CSV: {MANIFEST_CSV}")
        print(f"[dry-run] dryrun doc:   {DRYRUN_DOC}")
        return

    if args.confirm:
        manifest = load_manifest_csv(MANIFEST_CSV)
        con = duckdb.connect(str(PROD_DB), read_only=False)
        try:
            inventory = validate_inventory(con)
            print(
                f"[confirm] inventory OK: "
                f"series={inventory['distinct_series']}, "
                f"rows={inventory['row_count']:,}, "
                f"aum=${inventory['aum_usd']:,.2f}"
            )
            stats = execute_backfill(con, manifest)
        finally:
            con.close()

        print(
            f"[confirm] DONE — INSERTed {stats['rows_inserted']} rows "
            f"({stats['skip_count']} SKIP-list series left orphan). "
            f"fund_universe: {stats['pre_count']:,} → "
            f"{stats['post_count']:,}."
        )
        return


if __name__ == "__main__":
    main()
