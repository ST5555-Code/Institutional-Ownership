"""Read-only audit helper for ingestion-manifest-reconcile (CP-2).

Reconciles the live `ingestion_manifest` schema against the field
references in `docs/admin_refresh_system_design.md`. Writes a
machine-readable reconciliation manifest (CSV) and a narrative
findings document (Markdown). No schema mutation.

Per institution_scoping.md §9 G4 BLOCKER and §12 Open Question 1.
Path B per chat decision (2026-05-02): live schema is canonical;
design + admin queries reconcile toward live.

Usage:
    python3 scripts/oneoff/ingestion_manifest_reconcile_audit.py

Exit code 0 on success.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import Any

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
# Allow the DB path to be overridden when running from a git worktree whose
# data/ dir is empty (worktrees only share .git). Defaults to the in-repo
# canonical location.
DB_PATH = Path(os.environ.get("INGESTION_MANIFEST_DB", REPO_ROOT / "data" / "13f.duckdb"))
DESIGN_DOC = REPO_ROOT / "docs" / "admin_refresh_system_design.md"
CSV_OUT = REPO_ROOT / "data" / "working" / "ingestion_manifest_reconcile_manifest.csv"
MD_OUT = REPO_ROOT / "docs" / "findings" / "ingestion_manifest_reconcile_dryrun.md"


# Hand-curated reconciliation table. Each row asserts one design-doc field
# reference and the recommended action under Path B (live is canonical).
#
# Classification values:
#   RENAME            — design field is a different name for an existing live
#                       field. Action: doc-only rewrite. No schema change.
#   ADD               — design field genuinely needed by the admin dashboard
#                       and has no live equivalent. Requires chat
#                       authorization before any ALTER TABLE.
#   DROP_FROM_DESIGN  — design field is over-specified; no admin endpoint
#                       actually consumes it. Action: remove from design.
#   DOC_RECONCILE     — design narrative uses a value/term that doesn't
#                       match the live enum. Action: align design language
#                       and surface the actual live values.
#   ALREADY_LIVE      — design field already matches live schema name.
RECONCILIATION = [
    {
        "design_field": "pipeline_name",
        "classification": "RENAME",
        "target_live_field": "source_type",
        "semantic_meaning": "Source identifier per ingestion_manifest row",
        "read_sites": (
            "design.md L619-620 (Migration 008 fund_holdings_v2 SQL); "
            "design.md L818 (per-card 'Last run' admin query). "
            "Note: design.md L377-381 references pipeline_name as PK of a "
            "separate admin_preferences table — out of scope; that table "
            "does not exist in live schema and the column there is not on "
            "ingestion_manifest."
        ),
        "confidence": "HIGH",
        "blast_radius_notes": (
            "Doc-only. admin_bp.py already maps live source_type → API "
            "field 'pipeline_name' at serialization (admin_bp.py:1363, "
            "admin_bp.py:1393, admin_bp.py:1563). No code change required."
        ),
    },
    {
        "design_field": "status",
        "classification": "RENAME",
        "target_live_field": "fetch_status",
        "semantic_meaning": "Lifecycle state of the manifest row",
        "read_sites": (
            "design.md L150, L174, L176, L189, L620, L837 (narrative). "
            "Live update_manifest_status() in scripts/pipeline/manifest.py "
            "already accepts a `status` parameter and stores it in the "
            "fetch_status column."
        ),
        "confidence": "HIGH",
        "blast_radius_notes": (
            "Doc-only when describing the column. admin_bp.py already maps "
            "live fetch_status → API 'status' (admin_bp.py:1272, "
            "admin_bp.py:1359). No code change."
        ),
    },
    {
        "design_field": "completed_at",
        "classification": "RENAME",
        "target_live_field": "fetch_completed_at",
        "semantic_meaning": "Wall-clock when the fetch step finished",
        "read_sites": (
            "design.md L615, L618 (Migration 008 fund_holdings_v2 SQL); "
            "design.md L818 (per-card 'Last run' admin query)."
        ),
        "confidence": "HIGH",
        "blast_radius_notes": (
            "Doc-only. admin_bp.py already reads fetch_completed_at and "
            "serializes it as 'completed_at' (admin_bp.py:1274, "
            "admin_bp.py:1360, admin_bp.py:1395, admin_bp.py:1565)."
        ),
    },
    {
        "design_field": "row_counts_json",
        "classification": "DROP_FROM_DESIGN",
        "target_live_field": "ingestion_impacts.rows_promoted (aggregate)",
        "semantic_meaning": (
            "Per-target row counts from the most recent run. Design "
            "intended a JSON blob on ingestion_manifest; live design has "
            "this populated per-impact in ingestion_impacts.rows_promoted "
            "(BIGINT, NOT NULL DEFAULT 0)."
        ),
        "read_sites": (
            "design.md L822 ('Rows added last run' card field); "
            "design.md L837 ('rows_added' run-history drilldown column). "
            "Zero references in any pipeline writer or admin endpoint — "
            "phantom column."
        ),
        "confidence": "MEDIUM",
        "blast_radius_notes": (
            "Replacement query is a SUM(rows_promoted) GROUP BY "
            "manifest_id against ingestion_impacts. Already populated by "
            "all v1.2 SourcePipeline subclasses. Design doc must change "
            "L822 to point to the impacts aggregate; no schema column "
            "needed. Blast radius: zero existing admin code reads "
            "row_counts_json."
        ),
    },
    {
        "design_field": "requested_by",
        "classification": "DROP_FROM_DESIGN",
        "target_live_field": "(none — multi-user feature deferred)",
        "semantic_meaning": (
            "User identity that triggered a manual refresh. Design §11 "
            "explicitly labels this as 'Multi-user (future)' work, not "
            "current scope."
        ),
        "read_sites": (
            "design.md L895 ('Add `requested_by` to ingestion_manifest' "
            "under §11 Non-Functional Requirements → Multi-user (future))."
        ),
        "confidence": "HIGH",
        "blast_radius_notes": (
            "Already gated behind 'future' wording. Reconciliation: keep "
            "the future-work note but make explicit that it's out of "
            "scope until multi-user roles ship. No current admin endpoint "
            "needs this. Zero ADD COLUMN."
        ),
    },
    {
        "design_field": "fetch_status enum value 'verify_failed'",
        "classification": "DOC_RECONCILE",
        "target_live_field": "fetch_status (enum content)",
        "semantic_meaning": (
            "Step-7 verify gate from design L191. Verify-after-promote "
            "step is conceptual; no writer ever sets fetch_status to "
            "'verify_failed'."
        ),
        "read_sites": (
            "design.md L191 ('manifest row flagged status='verify_failed'')."
        ),
        "confidence": "MEDIUM",
        "blast_radius_notes": (
            "Reconcile design narrative: either remove the reference, or "
            "explicitly mark Step 7 (Verify) as not yet implemented. The "
            "live fetch_status enum from migration 001 schema comment is "
            "{ pending | fetching | complete | failed | skipped }. "
            "Observed values in prod also include { pending_approval, "
            "rolled_back, parsing }."
        ),
    },
    {
        "design_field": "fetch_status enum values 'parsing'/'validating'/'staging'/'promoting'",
        "classification": "DOC_RECONCILE",
        "target_live_field": "fetch_status (enum content)",
        "semantic_meaning": (
            "Granular state machine (lines L174-L189). Live writers only "
            "drive fetch_status through a smaller subset; deeper run-state "
            "is tracked at run_id level via the admin-endpoint state, not "
            "this column."
        ),
        "read_sites": (
            "design.md L174 ('status=fetching'), L176 ('status=parsing'), "
            "L189 ('status=complete')."
        ),
        "confidence": "MEDIUM",
        "blast_radius_notes": (
            "Add a 'Schema mapping' section in the design doc enumerating "
            "the actual fetch_status enum values present in live data: "
            "complete, failed, fetching, parsing, pending, "
            "pending_approval, rolled_back. Note that 'parsing' is "
            "transient and rare. No code change."
        ),
    },
]


def describe_table(con: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, Any]]:
    rows = con.execute(f"DESCRIBE {table}").fetchall()
    cols = []
    for r in rows:
        cols.append({
            "column_name": r[0],
            "column_type": r[1],
            "nullable": r[2],
            "key": r[3],
            "default": r[4],
        })
    return cols


def fetch_status_distribution(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, int]]:
    return con.execute(
        """
        SELECT source_type, fetch_status, COUNT(*) AS n
          FROM ingestion_manifest
         GROUP BY 1, 2
         ORDER BY n DESC
        """
    ).fetchall()


def write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "design_field",
        "classification",
        "target_live_field",
        "semantic_meaning",
        "read_sites",
        "confidence",
        "blast_radius_notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in RECONCILIATION:
            w.writerow(row)


def write_markdown(
    path: Path,
    schema: list[dict[str, Any]],
    enum_dist: list[tuple[str, str, int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rename_n = sum(1 for r in RECONCILIATION if r["classification"] == "RENAME")
    add_n = sum(1 for r in RECONCILIATION if r["classification"] == "ADD")
    drop_n = sum(1 for r in RECONCILIATION if r["classification"] == "DROP_FROM_DESIGN")
    doc_n = sum(1 for r in RECONCILIATION if r["classification"] == "DOC_RECONCILE")
    already_n = sum(1 for r in RECONCILIATION if r["classification"] == "ALREADY_LIVE")

    lines: list[str] = []
    lines.append("# ingestion-manifest-reconcile — Phase 2 dry-run findings")
    lines.append("")
    lines.append(
        "Read-only audit per institution_scoping.md §9 G4 BLOCKER and §12 "
        "Open Question 1. Path B (live schema canonical) per chat decision "
        "2026-05-02. CP-2 in inst_eid_bridge_decisions.md."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- RENAME (doc-only): {rename_n}")
    lines.append(f"- ADD COLUMN candidates: {add_n}")
    lines.append(f"- DROP_FROM_DESIGN: {drop_n}")
    lines.append(f"- DOC_RECONCILE (narrative/enum alignment): {doc_n}")
    lines.append(f"- ALREADY_LIVE: {already_n}")
    lines.append("")
    if add_n == 0:
        lines.append(
            "**Phase 3 schema migration scope: empty.** No ADD COLUMN "
            "candidates surfaced. Phase 3 will execute as a no-op; "
            "reconciliation is doc-only (Phase 4)."
        )
    else:
        lines.append(
            f"**Phase 3 gate active.** {add_n} ADD COLUMN candidate(s) "
            "require explicit chat authorization before Phase 3 schema "
            "migration."
        )
    lines.append("")

    lines.append("## Live ingestion_manifest schema")
    lines.append("")
    try:
        db_label = DB_PATH.relative_to(REPO_ROOT)
    except ValueError:
        db_label = DB_PATH
    lines.append(f"Source: `{db_label}` ({len(schema)} columns).")
    lines.append("")
    lines.append("| # | Column | Type | Nullable | Key | Default |")
    lines.append("|---|---|---|---|---|---|")
    for i, c in enumerate(schema, 1):
        default = c["default"] if c["default"] is not None else ""
        key = c["key"] if c["key"] is not None else ""
        lines.append(
            f"| {i} | `{c['column_name']}` | {c['column_type']} | "
            f"{c['nullable']} | {key} | {default} |"
        )
    lines.append("")

    lines.append("## Live fetch_status enum (observed)")
    lines.append("")
    lines.append(
        "Migration 001 schema comment enumerates "
        "`'pending' | 'fetching' | 'complete' | 'failed' | 'skipped'`. "
        "Actual values present in prod (top counts):"
    )
    lines.append("")
    lines.append("| source_type | fetch_status | count |")
    lines.append("|---|---|---|")
    for st, fs, n in enum_dist:
        lines.append(f"| {st} | {fs} | {n:,} |")
    lines.append("")
    lines.append(
        "Notable extra values not in the migration 001 enum comment: "
        "`pending_approval`, `rolled_back`, `parsing`. These are written "
        "by live pipelines (`load_*.py` + admin path) and the comment in "
        "migration 001 should be updated, but they are not new columns "
        "and require no schema change."
    )
    lines.append("")

    lines.append("## Field-level reconciliation table")
    lines.append("")
    lines.append("| Design field | Classification | Target live field | Confidence |")
    lines.append("|---|---|---|---|")
    for r in RECONCILIATION:
        lines.append(
            f"| `{r['design_field']}` | {r['classification']} | "
            f"`{r['target_live_field']}` | {r['confidence']} |"
        )
    lines.append("")
    lines.append(
        "Full per-row narrative (semantic meaning, read sites, blast "
        "radius) lives in "
        "`data/working/ingestion_manifest_reconcile_manifest.csv`."
    )
    lines.append("")

    lines.append("## ADD COLUMN candidates (gating Phase 3)")
    lines.append("")
    add_rows = [r for r in RECONCILIATION if r["classification"] == "ADD"]
    if not add_rows:
        lines.append(
            "**None.** Every design field with no live equivalent "
            "(`row_counts_json`, `requested_by`) has been classified as "
            "`DROP_FROM_DESIGN` per the prompt's bias-toward-DROP rule:"
        )
        lines.append("")
        lines.append(
            "- `row_counts_json` — design wanted a JSON blob on the "
            "manifest row; live data already populates per-target row "
            "counts on `ingestion_impacts.rows_promoted`. The admin "
            "dashboard \"Rows added last run\" card (design.md L822) "
            "should aggregate impacts, not read a non-existent JSON "
            "column. Zero admin endpoint or pipeline writer references "
            "this field today."
        )
        lines.append(
            "- `requested_by` — design.md §11 already labels this as "
            "\"Multi-user (future)\" work. Adding the column now would "
            "be ahead of the auth-role feature it depends on. No admin "
            "endpoint reads it; no writer populates it."
        )
    else:
        for r in add_rows:
            lines.append(f"### `{r['design_field']}`")
            lines.append("")
            lines.append(f"- **Target name:** `{r['target_live_field']}`")
            lines.append(f"- **Confidence:** {r['confidence']}")
            lines.append(f"- **Semantic meaning:** {r['semantic_meaning']}")
            lines.append(f"- **Read sites:** {r['read_sites']}")
            lines.append(f"- **Blast radius:** {r['blast_radius_notes']}")
            lines.append("")
    lines.append("")

    lines.append("## DROP_FROM_DESIGN justifications")
    lines.append("")
    for r in [x for x in RECONCILIATION if x["classification"] == "DROP_FROM_DESIGN"]:
        lines.append(f"### `{r['design_field']}`")
        lines.append("")
        lines.append(f"- **Read sites:** {r['read_sites']}")
        lines.append(f"- **Why drop:** {r['blast_radius_notes']}")
        lines.append("")

    lines.append("## Writer audit summary")
    lines.append("")
    lines.append(
        "All writes to `ingestion_manifest` go through "
        "`scripts/pipeline/manifest.py` (`get_or_create_manifest_row`, "
        "`update_manifest_status`, `supersede_manifest`, "
        "`mirror_manifest_and_impacts`). Direct INSERTs outside this "
        "module are flagged as a design violation in the module "
        "docstring. Per-pipeline writers "
        "(`load_13f_v2.py`, `load_nport.py`, `load_13dg.py`, "
        "`load_adv.py`, `load_ncen.py`, `load_market.py`) all delegate "
        "to these helpers."
    )
    lines.append("")
    lines.append(
        "No writer in the repo populates `row_counts_json` or "
        "`requested_by` (grep across `scripts/`). Both fields are "
        "design-only aspirations."
    )
    lines.append("")

    lines.append("## Admin endpoint readiness")
    lines.append("")
    lines.append(
        "Admin endpoints already exist in `scripts/admin_bp.py` "
        "(`/admin/status`, `/admin/runs/pending`, "
        "`/admin/runs/{run_id}/diff`, `/admin/run/{run_id}`). They "
        "already read the live schema and serialize to the design's "
        "API field names — `source_type` → `pipeline_name`, "
        "`fetch_status` → `status`, `fetch_completed_at` → "
        "`completed_at`. Phase 4 design-doc updates align the doc to "
        "what the code already does; no admin endpoint code changes are "
        "needed."
    )
    lines.append("")

    lines.append("## Phase 3 / 4 plan")
    lines.append("")
    lines.append(
        "1. **Phase 3 (schema migration):** no-op. Zero ADD COLUMN "
        "candidates surfaced; gate is empty."
    )
    lines.append(
        "2. **Phase 4 (doc reconciliation):** rewrite design.md L150, "
        "L174-L191, L610-L621, L815-L822, L835-L837, L889-L897 to use "
        "live field names; replace `row_counts_json` reference with "
        "`ingestion_impacts.rows_promoted` aggregate; mark `requested_by` "
        "explicitly as not-yet-scoped under §11 Multi-user. Add a new "
        "\"Schema mapping\" appendix with the live ingestion_manifest "
        "DDL and the API field translation table that admin_bp.py "
        "already implements."
    )
    lines.append(
        "3. **Phase 5 (validation):** pytest, npm build, smoke a single "
        "writer (`scripts/pipeline/load_market.py --dry-run` or "
        "equivalent) to confirm ingestion_manifest writes still succeed."
    )
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not DB_PATH.exists():
        print(f"ABORT: db not found: {DB_PATH}", file=sys.stderr)
        return 1
    if not DESIGN_DOC.exists():
        print(f"ABORT: design doc not found: {DESIGN_DOC}", file=sys.stderr)
        return 1

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        schema = describe_table(con, "ingestion_manifest")
        enum_dist = fetch_status_distribution(con)
    finally:
        con.close()

    write_csv(CSV_OUT)
    write_markdown(MD_OUT, schema, enum_dist)

    print(f"wrote {CSV_OUT.relative_to(REPO_ROOT)}")
    print(f"wrote {MD_OUT.relative_to(REPO_ROOT)}")
    rename_n = sum(1 for r in RECONCILIATION if r["classification"] == "RENAME")
    add_n = sum(1 for r in RECONCILIATION if r["classification"] == "ADD")
    drop_n = sum(1 for r in RECONCILIATION if r["classification"] == "DROP_FROM_DESIGN")
    doc_n = sum(1 for r in RECONCILIATION if r["classification"] == "DOC_RECONCILE")
    print(
        f"summary: RENAME={rename_n} ADD={add_n} DROP_FROM_DESIGN={drop_n} "
        f"DOC_RECONCILE={doc_n}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
