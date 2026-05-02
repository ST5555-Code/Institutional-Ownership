# ingestion-manifest-reconcile — Phase 2 dry-run findings

Read-only audit per institution_scoping.md §9 G4 BLOCKER and §12 Open Question 1. Path B (live schema canonical) per chat decision 2026-05-02. CP-2 in inst_eid_bridge_decisions.md.

## Summary

- RENAME (doc-only): 3
- ADD COLUMN candidates: 0
- DROP_FROM_DESIGN: 2
- DOC_RECONCILE (narrative/enum alignment): 2
- ALREADY_LIVE: 0

**Phase 3 schema migration scope: empty.** No ADD COLUMN candidates surfaced. Phase 3 will execute as a no-op; reconciliation is doc-only (Phase 4).

## Live ingestion_manifest schema

Source: `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb` (26 columns).

| # | Column | Type | Nullable | Key | Default |
|---|---|---|---|---|---|
| 1 | `manifest_id` | BIGINT | NO | PRI |  |
| 2 | `source_type` | VARCHAR | NO |  |  |
| 3 | `object_type` | VARCHAR | NO |  |  |
| 4 | `object_key` | VARCHAR | NO | UNI |  |
| 5 | `source_url` | VARCHAR | YES |  |  |
| 6 | `accession_number` | VARCHAR | YES |  |  |
| 7 | `report_period` | DATE | YES |  |  |
| 8 | `filing_date` | DATE | YES |  |  |
| 9 | `accepted_at` | TIMESTAMP | YES |  |  |
| 10 | `run_id` | VARCHAR | NO |  |  |
| 11 | `discovered_at` | TIMESTAMP | YES |  | CURRENT_TIMESTAMP |
| 12 | `fetch_started_at` | TIMESTAMP | YES |  |  |
| 13 | `fetch_completed_at` | TIMESTAMP | YES |  |  |
| 14 | `fetch_status` | VARCHAR | NO |  | 'pending' |
| 15 | `http_code` | INTEGER | YES |  |  |
| 16 | `source_bytes` | BIGINT | YES |  |  |
| 17 | `source_checksum` | VARCHAR | YES |  |  |
| 18 | `local_path` | VARCHAR | YES |  |  |
| 19 | `retry_count` | INTEGER | NO |  | 0 |
| 20 | `error_message` | VARCHAR | YES |  |  |
| 21 | `parser_version` | VARCHAR | YES |  |  |
| 22 | `schema_version` | VARCHAR | YES |  |  |
| 23 | `is_amendment` | BOOLEAN | NO |  | CAST('f' AS BOOLEAN) |
| 24 | `prior_accession` | VARCHAR | YES |  |  |
| 25 | `superseded_by_manifest_id` | BIGINT | YES |  |  |
| 26 | `created_at` | TIMESTAMP | YES |  | CURRENT_TIMESTAMP |

## Live fetch_status enum (observed)

Migration 001 schema comment enumerates `'pending' | 'fetching' | 'complete' | 'failed' | 'skipped'`. Actual values present in prod (top counts):

| source_type | fetch_status | count |
|---|---|---|
| 13DG | complete | 51,905 |
| NPORT | complete | 21,252 |
| MARKET | complete | 83 |
| peer_rotation | complete | 9 |
| parent_fund_map | complete | 4 |
| sector_flows | complete | 4 |
| peer_rotation | failed | 3 |
| 13f_holdings | rolled_back | 1 |
| ADV | complete | 1 |
| nport_holdings | complete | 1 |
| MARKET | fetching | 1 |
| 13f_holdings | failed | 1 |
| parent_fund_map | parsing | 1 |
| parent_fund_map | pending_approval | 1 |
| sector_flows | rolled_back | 1 |

Notable extra values not in the migration 001 enum comment: `pending_approval`, `rolled_back`, `parsing`. These are written by live pipelines (`load_*.py` + admin path) and the comment in migration 001 should be updated, but they are not new columns and require no schema change.

## Field-level reconciliation table

| Design field | Classification | Target live field | Confidence |
|---|---|---|---|
| `pipeline_name` | RENAME | `source_type` | HIGH |
| `status` | RENAME | `fetch_status` | HIGH |
| `completed_at` | RENAME | `fetch_completed_at` | HIGH |
| `row_counts_json` | DROP_FROM_DESIGN | `ingestion_impacts.rows_promoted (aggregate)` | MEDIUM |
| `requested_by` | DROP_FROM_DESIGN | `(none — multi-user feature deferred)` | HIGH |
| `fetch_status enum value 'verify_failed'` | DOC_RECONCILE | `fetch_status (enum content)` | MEDIUM |
| `fetch_status enum values 'parsing'/'validating'/'staging'/'promoting'` | DOC_RECONCILE | `fetch_status (enum content)` | MEDIUM |

Full per-row narrative (semantic meaning, read sites, blast radius) lives in `data/working/ingestion_manifest_reconcile_manifest.csv`.

## ADD COLUMN candidates (gating Phase 3)

**None.** Every design field with no live equivalent (`row_counts_json`, `requested_by`) has been classified as `DROP_FROM_DESIGN` per the prompt's bias-toward-DROP rule:

- `row_counts_json` — design wanted a JSON blob on the manifest row; live data already populates per-target row counts on `ingestion_impacts.rows_promoted`. The admin dashboard "Rows added last run" card (design.md L822) should aggregate impacts, not read a non-existent JSON column. Zero admin endpoint or pipeline writer references this field today.
- `requested_by` — design.md §11 already labels this as "Multi-user (future)" work. Adding the column now would be ahead of the auth-role feature it depends on. No admin endpoint reads it; no writer populates it.

## DROP_FROM_DESIGN justifications

### `row_counts_json`

- **Read sites:** design.md L822 ('Rows added last run' card field); design.md L837 ('rows_added' run-history drilldown column). Zero references in any pipeline writer or admin endpoint — phantom column.
- **Why drop:** Replacement query is a SUM(rows_promoted) GROUP BY manifest_id against ingestion_impacts. Already populated by all v1.2 SourcePipeline subclasses. Design doc must change L822 to point to the impacts aggregate; no schema column needed. Blast radius: zero existing admin code reads row_counts_json.

### `requested_by`

- **Read sites:** design.md L895 ('Add `requested_by` to ingestion_manifest' under §11 Non-Functional Requirements → Multi-user (future)).
- **Why drop:** Already gated behind 'future' wording. Reconciliation: keep the future-work note but make explicit that it's out of scope until multi-user roles ship. No current admin endpoint needs this. Zero ADD COLUMN.

## Writer audit summary

All writes to `ingestion_manifest` go through `scripts/pipeline/manifest.py` (`get_or_create_manifest_row`, `update_manifest_status`, `supersede_manifest`, `mirror_manifest_and_impacts`). Direct INSERTs outside this module are flagged as a design violation in the module docstring. Per-pipeline writers (`load_13f_v2.py`, `load_nport.py`, `load_13dg.py`, `load_adv.py`, `load_ncen.py`, `load_market.py`) all delegate to these helpers.

No writer in the repo populates `row_counts_json` or `requested_by` (grep across `scripts/`). Both fields are design-only aspirations.

## Admin endpoint readiness

Admin endpoints already exist in `scripts/admin_bp.py` (`/admin/status`, `/admin/runs/pending`, `/admin/runs/{run_id}/diff`, `/admin/run/{run_id}`). They already read the live schema and serialize to the design's API field names — `source_type` → `pipeline_name`, `fetch_status` → `status`, `fetch_completed_at` → `completed_at`. Phase 4 design-doc updates align the doc to what the code already does; no admin endpoint code changes are needed.

## Phase 3 / 4 plan

1. **Phase 3 (schema migration):** no-op. Zero ADD COLUMN candidates surfaced; gate is empty.
2. **Phase 4 (doc reconciliation):** rewrite design.md L150, L174-L191, L610-L621, L815-L822, L835-L837, L889-L897 to use live field names; replace `row_counts_json` reference with `ingestion_impacts.rows_promoted` aggregate; mark `requested_by` explicitly as not-yet-scoped under §11 Multi-user. Add a new "Schema mapping" appendix with the live ingestion_manifest DDL and the API field translation table that admin_bp.py already implements.
3. **Phase 5 (validation):** pytest, npm build, smoke a single writer (`scripts/pipeline/load_market.py --dry-run` or equivalent) to confirm ingestion_manifest writes still succeed.

