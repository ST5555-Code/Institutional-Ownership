#!/usr/bin/env python3
"""correct_fund_universe_values.py — fund-universe-value-corrections.

Two value corrections to ``fund_universe`` after PRs #244–#247:

  BLOCK A — Rareview reclassify (1 row).
    series_id='S000090077' (Rareview 2x Bull Cryptocurrency & Precious
    Metals ETF). Row was tagged ``fund_strategy='excluded'`` by the
    PR #245 majority-vote backfill because the leveraged-name regex
    ('\\dx') matched in the upstream classifier before the ETF/passive
    pattern. Per the PR #246 unknown-bucket audit, the fund is a
    leveraged passive ETF, not excluded. Manual override.

  BLOCK B — total_net_assets backfill (301 rows).
    PR #245's ``backfill_orphan_fund_universe.py`` populated
    ``fund_strategy`` only and left ``total_net_assets`` NULL. The
    canonical N-PORT TotalNetAssets value is not persisted at the
    series level in prod — it can be reconstructed exactly from
    ``fund_holdings_v2`` via:

        NAV = MEDIAN(market_value_usd * 100.0 / pct_of_nav)

    over the most-recent quarter's ``is_latest=TRUE`` rows.
    ``pct_of_nav`` is stored on the percent scale (0–100). Empirical
    cross-check on 10 randomly sampled funds with existing
    total_net_assets reproduces the stored value exactly (ratio =
    1.000000…).

    Fallback (none required for current cohort): if no row has
    pct_of_nav populated, derive ``total_net_assets =
    SUM(market_value_usd)`` and append ``|aum_summed_fallback`` to
    the strategy_source tag.

Pipeline lock context: ``fund_universe.fund_strategy`` is canonical
and locked at the *pipeline write path* (PR-2). Manual overrides
via this script are explicit, tagged with ``strategy_source``, and
do not bypass any hard schema constraint.

Modes:
  --dry-run  Build manifest CSV + dryrun findings markdown; no DB
             writes. Read-only DuckDB connection. Re-validates
             Phase 1 targets.
  --confirm  Read manifest CSV; execute Block A + Block B in a
             single transaction. Refuses to run on Phase 1 drift.

Outputs:
  data/working/fund_universe_corrections_manifest.csv
  docs/findings/fund_universe_corrections_dryrun.md  (dry-run)
"""
from __future__ import annotations

import argparse
import csv
import subprocess
from datetime import datetime
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]


def _resolve_prod_db() -> Path:
    """Find data/13f.duckdb. Works from main repo or from a git worktree
    (worktrees have their own empty data/ dir; the DB lives at the
    primary working tree)."""
    primary = BASE_DIR / "data" / "13f.duckdb"
    if primary.exists():
        return primary
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=BASE_DIR,
            text=True,
        ).strip()
        main_root = Path(common).parent
        candidate = main_root / "data" / "13f.duckdb"
        if candidate.exists():
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    raise SystemExit(
        f"ABORT: prod DB not found at {primary} or via git common-dir."
    )


PROD_DB = _resolve_prod_db()
MANIFEST_CSV = (
    BASE_DIR / "data" / "working" / "fund_universe_corrections_manifest.csv"
)
DRYRUN_DOC = (
    BASE_DIR / "docs" / "findings" / "fund_universe_corrections_dryrun.md"
)

# --- Block A constants -----------------------------------------------------

RAREVIEW_SERIES_ID = "S000090077"
RAREVIEW_EXPECTED_NAME_LIKE = "Rareview 2x Bull Cryptocurrency"
RAREVIEW_EXPECTED_CURRENT_STRATEGY = "excluded"
RAREVIEW_NEW_STRATEGY = "passive"
RAREVIEW_NEW_SOURCE = "unknown_cleanup_2026Q2"

# --- Block B constants -----------------------------------------------------

BACKFILL_SOURCE_TAG = "orphan_backfill_2026Q2"
BACKFILL_FALLBACK_SUFFIX = "|aum_summed_fallback"
EXPECTED_BACKFILL_ROW_COUNT = 301


# ---------------------------------------------------------------------------
# Phase 1 — re-validate targets (read-only)
# ---------------------------------------------------------------------------

def validate_block_a(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        """
        SELECT series_id, fund_name, fund_strategy, strategy_source,
               total_net_assets
        FROM fund_universe WHERE series_id = ?
        """,
        [RAREVIEW_SERIES_ID],
    ).fetchone()
    if row is None:
        raise SystemExit(
            f"ABORT: Block A target series_id={RAREVIEW_SERIES_ID} not "
            f"found in fund_universe."
        )
    series_id, fund_name, fund_strategy, strategy_source, tna = row

    if fund_strategy == RAREVIEW_NEW_STRATEGY:
        raise SystemExit(
            f"ABORT: Block A target already at fund_strategy="
            f"'{RAREVIEW_NEW_STRATEGY}' (a separate process may have "
            f"already handled it). Skipping."
        )

    if fund_strategy != RAREVIEW_EXPECTED_CURRENT_STRATEGY:
        raise SystemExit(
            f"ABORT: Block A target fund_strategy='{fund_strategy}' "
            f"(expected '{RAREVIEW_EXPECTED_CURRENT_STRATEGY}'). "
            f"Cohort drift; investigate manually."
        )

    if RAREVIEW_EXPECTED_NAME_LIKE not in (fund_name or ""):
        raise SystemExit(
            f"ABORT: Block A target fund_name='{fund_name}' does not "
            f"contain '{RAREVIEW_EXPECTED_NAME_LIKE}'. Investigate."
        )

    return {
        "series_id": series_id,
        "fund_name": fund_name,
        "current_strategy": fund_strategy,
        "current_source": strategy_source,
        "current_tna": tna,
    }


def validate_block_b(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        """
        SELECT COUNT(*)                          AS total,
               COUNT(total_net_assets)           AS with_tna,
               SUM(CASE WHEN total_net_assets IS NULL THEN 1 ELSE 0 END)
                   AS null_tna
        FROM fund_universe WHERE strategy_source = ?
        """,
        [BACKFILL_SOURCE_TAG],
    ).fetchone()
    total, with_tna, null_tna = row

    if total != EXPECTED_BACKFILL_ROW_COUNT:
        raise SystemExit(
            f"ABORT: Block B cohort drift — found {total} rows tagged "
            f"'{BACKFILL_SOURCE_TAG}' (expected "
            f"{EXPECTED_BACKFILL_ROW_COUNT}). Do not proceed."
        )
    return {
        "total": total,
        "with_tna": with_tna,
        "null_tna": null_tna,
    }


# ---------------------------------------------------------------------------
# Phase 2 — derivation
# ---------------------------------------------------------------------------

def derive_block_b_manifest(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-series NAV derivation for the 301-row backfill cohort.

    Canonical: NAV = MEDIAN(market_value_usd * 100.0 / pct_of_nav)
    over most-recent quarter's is_latest=TRUE rows. This reconstructs
    N-PORT TotalNetAssets exactly (validated against funds with
    existing total_net_assets, ratio = 1.000…).

    Fallback: NAV = SUM(market_value_usd) — equity holdings only,
    lower bound. Source tag suffixed '|aum_summed_fallback'.

    NULL-residual: series with no usable holdings at all (no canonical
    AND no fallback). Surfaced for chat decision; --confirm refuses
    to run if any present.

    Block A's series_id is excluded so its strategy_source flip is
    not silently overwritten by Block B's UPDATE.
    """
    rows = con.execute(
        f"""
        WITH bf AS (
            SELECT series_id, fund_name
            FROM fund_universe
            WHERE strategy_source = '{BACKFILL_SOURCE_TAG}'
              AND series_id <> '{RAREVIEW_SERIES_ID}'
        ),
        per_q AS (
            SELECT
                fh.series_id,
                fh.quarter,
                COUNT(*)                                         AS row_count,
                SUM(market_value_usd)                            AS sum_mv,
                MEDIAN(CASE WHEN pct_of_nav IS NOT NULL AND pct_of_nav > 0
                            THEN market_value_usd * 100.0 / pct_of_nav END)
                                                                 AS implied_nav
            FROM fund_holdings_v2 fh
            JOIN bf USING (series_id)
            WHERE fh.is_latest = TRUE
            GROUP BY fh.series_id, fh.quarter
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY series_id ORDER BY quarter DESC
                   ) AS rn
            FROM per_q
        )
        SELECT bf.series_id, bf.fund_name,
               r.quarter, r.row_count, r.sum_mv, r.implied_nav
        FROM bf
        LEFT JOIN ranked r ON r.series_id = bf.series_id AND r.rn = 1
        ORDER BY bf.series_id
        """
    ).fetchall()

    manifest: list[dict] = []
    for series_id, fund_name, quarter, row_count, sum_mv, implied_nav in rows:
        sum_mv_f = float(sum_mv) if sum_mv is not None else None
        implied_nav_f = float(implied_nav) if implied_nav is not None else None

        if implied_nav_f is not None and implied_nav_f > 0:
            new_tna = implied_nav_f
            source = "canonical_nport"
            new_source_tag = BACKFILL_SOURCE_TAG  # unchanged
        elif sum_mv_f is not None and sum_mv_f > 0:
            new_tna = sum_mv_f
            source = "aum_summed_fallback"
            new_source_tag = BACKFILL_SOURCE_TAG + BACKFILL_FALLBACK_SUFFIX
        else:
            new_tna = None
            source = "null_residual"
            new_source_tag = None

        manifest.append({
            "block": "B",
            "series_id": series_id,
            "fund_name": fund_name or "",
            "current_value": "",
            "proposed_value": (
                f"{new_tna:.2f}" if new_tna is not None else ""
            ),
            "source": source,
            "new_strategy_source": new_source_tag or "",
            "support_quarter": quarter or "",
            "support_row_count": row_count or 0,
            "support_sum_mv": (
                f"{sum_mv_f:.2f}" if sum_mv_f is not None else ""
            ),
            "support_implied_nav": (
                f"{implied_nav_f:.2f}" if implied_nav_f is not None else ""
            ),
        })

    return manifest


def derive_block_a_nav(con: duckdb.DuckDBPyConnection) -> float | None:
    """Apply the same canonical NAV derivation as Block B to Rareview,
    so Block A's UPDATE populates total_net_assets in one shot."""
    row = con.execute(
        """
        WITH per_q AS (
          SELECT quarter,
                 MEDIAN(CASE WHEN pct_of_nav IS NOT NULL AND pct_of_nav > 0
                             THEN market_value_usd * 100.0 / pct_of_nav END)
                                                            AS implied_nav,
                 SUM(market_value_usd)                       AS sum_mv
          FROM fund_holdings_v2
          WHERE series_id = ? AND is_latest = TRUE
          GROUP BY quarter
        ),
        ranked AS (
          SELECT *, ROW_NUMBER() OVER (ORDER BY quarter DESC) AS rn
          FROM per_q
        )
        SELECT implied_nav, sum_mv FROM ranked WHERE rn = 1
        """,
        [RAREVIEW_SERIES_ID],
    ).fetchone()
    if row is None:
        return None
    implied, sum_mv = row
    if implied is not None and implied > 0:
        return float(implied)
    if sum_mv is not None and sum_mv > 0:
        return float(sum_mv)
    return None


def build_block_a_entry(b_a: dict, nav: float | None) -> dict:
    return {
        "block": "A",
        "series_id": b_a["series_id"],
        "fund_name": b_a["fund_name"] or "",
        "current_value": b_a["current_strategy"],
        "proposed_value": RAREVIEW_NEW_STRATEGY,
        "source": "manual_override",
        "new_strategy_source": RAREVIEW_NEW_SOURCE,
        "support_quarter": "",
        "support_row_count": 0,
        "support_sum_mv": "",
        "support_implied_nav": (
            f"{nav:.2f}" if nav is not None else ""
        ),
    }


# ---------------------------------------------------------------------------
# Phase 2 outputs
# ---------------------------------------------------------------------------

MANIFEST_FIELDS = [
    "block",
    "series_id",
    "fund_name",
    "current_value",
    "proposed_value",
    "source",
    "new_strategy_source",
    "support_quarter",
    "support_row_count",
    "support_sum_mv",
    "support_implied_nav",
]


def write_manifest_csv(manifest: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in manifest:
            writer.writerow({k: row.get(k, "") for k in MANIFEST_FIELDS})


def load_manifest_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"ABORT: manifest not found at {path}. Run --dry-run first."
        )
    out: list[dict] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(row)
    return out


def write_dryrun_doc(
    manifest: list[dict],
    block_a: dict,
    block_b_inv: dict,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    a_rows = [r for r in manifest if r["block"] == "A"]
    b_rows = [r for r in manifest if r["block"] == "B"]
    b_canonical = [r for r in b_rows if r["source"] == "canonical_nport"]
    b_fallback = [r for r in b_rows if r["source"] == "aum_summed_fallback"]
    b_null = [r for r in b_rows if r["source"] == "null_residual"]

    def _sum_proposed(rows):
        total = 0.0
        for r in rows:
            try:
                total += float(r["proposed_value"])
            except (TypeError, ValueError):
                pass
        return total

    lines: list[str] = []
    lines.append("# fund-universe-value-corrections — Phase 2 dry-run")
    lines.append("")
    lines.append(
        f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_"
    )
    lines.append("")
    lines.append("## Block A — Rareview reclassify")
    lines.append("")
    lines.append(f"- `series_id`: `{block_a['series_id']}`")
    lines.append(f"- `fund_name`: {block_a['fund_name']}")
    lines.append(
        f"- Current `fund_strategy`: **{block_a['current_strategy']}** "
        f"(`strategy_source`={block_a['current_source']})"
    )
    lines.append(
        f"- Proposed `fund_strategy`: **{RAREVIEW_NEW_STRATEGY}** "
        f"(`strategy_source`={RAREVIEW_NEW_SOURCE})"
    )
    lines.append("")
    lines.append(
        "Rationale: classifier order matched leveraged-name regex "
        "(`\\dx`) before the ETF/passive pattern, tagging the fund "
        "`excluded`. Per PR #246 audit, this is a leveraged passive "
        "ETF, not excluded. Manual override."
    )
    lines.append("")

    lines.append("## Block B — total_net_assets backfill (301 rows)")
    lines.append("")
    lines.append(
        f"- Cohort: `strategy_source='{BACKFILL_SOURCE_TAG}'`"
    )
    lines.append(
        f"- Re-validated inventory: {block_b_inv['total']} rows, "
        f"{block_b_inv['with_tna']} with `total_net_assets`, "
        f"{block_b_inv['null_tna']} NULL."
    )
    lines.append("")
    lines.append(
        "Canonical derivation: `NAV = MEDIAN(market_value_usd * 100.0 / "
        "pct_of_nav)` over most-recent-quarter `is_latest=TRUE` rows. "
        "`pct_of_nav` is stored on the percent scale (0–100). Method "
        "validated against 10 funds with existing `total_net_assets` "
        "(ratio = 1.000000…)."
    )
    lines.append("")
    lines.append(
        "Fallback: `NAV = SUM(market_value_usd)` for series with no "
        "usable `pct_of_nav` rows; `strategy_source` suffixed "
        f"`{BACKFILL_FALLBACK_SUFFIX}`."
    )
    lines.append("")
    lines.append("### Block B summary")
    lines.append("")
    lines.append("| Source | Series | Total NAV (USD) |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| canonical_nport | {len(b_canonical):,} | "
        f"${_sum_proposed(b_canonical):,.2f} |"
    )
    lines.append(
        f"| aum_summed_fallback | {len(b_fallback):,} | "
        f"${_sum_proposed(b_fallback):,.2f} |"
    )
    lines.append(
        f"| null_residual | {len(b_null):,} | — |"
    )
    lines.append(
        f"| **TOTAL** | **{len(b_rows):,}** | "
        f"**${_sum_proposed(b_canonical) + _sum_proposed(b_fallback):,.2f}** |"
    )
    lines.append("")

    if b_null:
        lines.append("### NULL-residual series (require chat decision)")
        lines.append("")
        lines.append("| series_id | fund_name |")
        lines.append("|---|---|")
        for r in b_null:
            lines.append(f"| `{r['series_id']}` | {r['fund_name']} |")
        lines.append("")
    else:
        lines.append("_No NULL-residual series — full coverage._")
        lines.append("")

    lines.append("## Full manifest (sorted by block, source, series_id)")
    lines.append("")
    lines.append(
        "| block | series_id | fund_name | current_value | proposed_value | "
        "source | new_strategy_source |"
    )
    lines.append("|---|---|---|---|---:|---|---|")
    for r in sorted(
        manifest, key=lambda x: (x["block"], x["source"], x["series_id"])
    ):
        proposed = r["proposed_value"]
        if proposed and r["block"] == "B":
            try:
                proposed = f"${float(proposed):,.0f}"
            except (TypeError, ValueError):
                pass
        lines.append(
            f"| {r['block']} | `{r['series_id']}` | {r['fund_name']} | "
            f"{r['current_value'] or '—'} | {proposed or '—'} | "
            f"{r['source']} | {r['new_strategy_source'] or '—'} |"
        )
    lines.append("")

    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Phase 3 — execute corrections
# ---------------------------------------------------------------------------

def execute_corrections(
    con: duckdb.DuckDBPyConnection,
    manifest: list[dict],
) -> dict:
    a_rows = [r for r in manifest if r["block"] == "A"]
    b_rows = [r for r in manifest if r["block"] == "B"]
    b_eligible = [r for r in b_rows if r["source"] != "null_residual"]
    b_null = [r for r in b_rows if r["source"] == "null_residual"]

    if b_null:
        raise SystemExit(
            f"ABORT: {len(b_null)} NULL-residual series in manifest. "
            f"Resolve in chat before running --confirm. "
            f"Sample: {[r['series_id'] for r in b_null[:5]]}"
        )

    if len(a_rows) != 1:
        raise SystemExit(
            f"ABORT: expected 1 Block A row, got {len(a_rows)}."
        )
    expected_b = EXPECTED_BACKFILL_ROW_COUNT - 1  # Rareview is in Block A
    if len(b_eligible) != expected_b:
        raise SystemExit(
            f"ABORT: expected {expected_b} Block B eligible rows, "
            f"got {len(b_eligible)}."
        )

    pre_a = con.execute(
        "SELECT fund_strategy FROM fund_universe WHERE series_id=?",
        [RAREVIEW_SERIES_ID],
    ).fetchone()
    pre_b_with = con.execute(
        f"""
        SELECT COUNT(total_net_assets) FROM fund_universe
        WHERE strategy_source LIKE '{BACKFILL_SOURCE_TAG}%'
        """
    ).fetchone()[0]

    print(
        f"[confirm] pre-update: Block A strategy='{pre_a[0]}', "
        f"Block B with_tna={pre_b_with}"
    )

    now = datetime.utcnow()
    con.execute("BEGIN")
    try:
        # Block A — single-row UPDATE setting strategy + NAV in one shot
        a_row = a_rows[0]
        try:
            a_nav = (
                float(a_row["support_implied_nav"])
                if a_row.get("support_implied_nav")
                else None
            )
        except (TypeError, ValueError):
            a_nav = None
        a_returned = con.execute(
            """
            UPDATE fund_universe
            SET fund_strategy=?, strategy_source=?, total_net_assets=?,
                strategy_fetched_at=?, last_updated=?
            WHERE series_id=? AND fund_strategy=?
            RETURNING series_id
            """,
            [
                RAREVIEW_NEW_STRATEGY,
                RAREVIEW_NEW_SOURCE,
                a_nav,
                now,
                now,
                RAREVIEW_SERIES_ID,
                RAREVIEW_EXPECTED_CURRENT_STRATEGY,
            ],
        ).fetchall()
        a_changes = len(a_returned)
        if a_changes != 1:
            raise SystemExit(
                f"ABORT: Block A UPDATE affected {a_changes} rows "
                f"(expected 1)."
            )

        # Block B
        b_changes_total = 0
        for r in b_eligible:
            new_tna = float(r["proposed_value"])
            new_source = r["new_strategy_source"]
            b_returned = con.execute(
                """
                UPDATE fund_universe
                SET total_net_assets=?, strategy_source=?, last_updated=?
                WHERE series_id=? AND total_net_assets IS NULL
                RETURNING series_id
                """,
                [new_tna, new_source, now, r["series_id"]],
            ).fetchall()
            b_changes_total += len(b_returned)

        if b_changes_total != len(b_eligible):
            raise SystemExit(
                f"ABORT: Block B UPDATE affected {b_changes_total} rows "
                f"(expected {len(b_eligible)})."
            )

        # Sanity: post-state matches expectations
        residual_null = con.execute(
            f"""
            SELECT COUNT(*) FROM fund_universe
            WHERE strategy_source LIKE '{BACKFILL_SOURCE_TAG}%'
              AND total_net_assets IS NULL
            """
        ).fetchone()[0]
        if residual_null != 0:
            raise SystemExit(
                f"ABORT: post-update residual NULL count = {residual_null} "
                f"(expected 0). Rolling back."
            )

        post_a = con.execute(
            "SELECT fund_strategy FROM fund_universe WHERE series_id=?",
            [RAREVIEW_SERIES_ID],
        ).fetchone()
        if post_a[0] != RAREVIEW_NEW_STRATEGY:
            raise SystemExit(
                f"ABORT: Block A post-update strategy='{post_a[0]}' "
                f"(expected '{RAREVIEW_NEW_STRATEGY}'). Rolling back."
            )

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    print(
        f"[confirm] DONE — Block A: 1 row → {RAREVIEW_NEW_STRATEGY}; "
        f"Block B: {b_changes_total} rows populated total_net_assets."
    )

    return {
        "block_a_updates": a_changes,
        "block_b_updates": b_changes_total,
        "null_residual": 0,
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
        help="Build manifest CSV + dryrun findings markdown; no DB writes.",
    )
    grp.add_argument(
        "--confirm",
        action="store_true",
        help="Read manifest CSV; UPDATE Block A + Block B in one transaction.",
    )
    args = parser.parse_args()

    if args.dry_run:
        con = duckdb.connect(str(PROD_DB), read_only=True)
        try:
            block_a_inv = validate_block_a(con)
            block_b_inv = validate_block_b(con)
            print(
                f"[dry-run] Block A OK: series_id={block_a_inv['series_id']}, "
                f"current_strategy='{block_a_inv['current_strategy']}'"
            )
            print(
                f"[dry-run] Block B OK: {block_b_inv['total']} rows, "
                f"{block_b_inv['null_tna']} NULL on total_net_assets"
            )
            block_a_nav = derive_block_a_nav(con)
            block_b_manifest = derive_block_b_manifest(con)
        finally:
            con.close()

        manifest = [build_block_a_entry(block_a_inv, block_a_nav)] + block_b_manifest
        write_manifest_csv(manifest, MANIFEST_CSV)
        write_dryrun_doc(manifest, block_a_inv, block_b_inv, DRYRUN_DOC)

        n_canonical = sum(
            1 for r in block_b_manifest if r["source"] == "canonical_nport"
        )
        n_fallback = sum(
            1 for r in block_b_manifest if r["source"] == "aum_summed_fallback"
        )
        n_null = sum(
            1 for r in block_b_manifest if r["source"] == "null_residual"
        )
        print(
            f"[dry-run] Block B derivation: canonical={n_canonical}, "
            f"fallback={n_fallback}, null_residual={n_null}"
        )
        print(f"[dry-run] manifest CSV: {MANIFEST_CSV}")
        print(f"[dry-run] dryrun doc:   {DRYRUN_DOC}")
        return

    if args.confirm:
        manifest = load_manifest_csv(MANIFEST_CSV)
        con = duckdb.connect(str(PROD_DB), read_only=False)
        try:
            validate_block_a(con)
            validate_block_b(con)
            stats = execute_corrections(con, manifest)
        finally:
            con.close()

        print(
            f"[confirm] stats: block_a_updates={stats['block_a_updates']}, "
            f"block_b_updates={stats['block_b_updates']}, "
            f"null_residual={stats['null_residual']}"
        )
        return


if __name__ == "__main__":
    main()
