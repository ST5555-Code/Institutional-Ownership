# mig-09-p0 — Phase 0 findings: INF45 schema-parity L4 extension

_Prepared: 2026-04-22 — branch `mig-09-p0` off main HEAD `c7f5605`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-09` (Batch 3-C). Sibling of `mig-10` (L0 control-plane, disjoint `accept.yaml` sections; parallel-eligible). Source design: `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` §9 / §14 (INF45 deferred extension)._

Phase 0 is investigation only. No code changes, no DB writes. READ-ONLY inspection of the validator, accept-list, and data-layer inventory.

---

## §1. Current validator scope at HEAD

[scripts/pipeline/validate_schema_parity.py](scripts/pipeline/validate_schema_parity.py) (871 lines) validates **prod vs staging schema parity** across four dimensions: `columns`, `indexes`, `constraints`, `ddl`.

**Table selection.** Hardcoded constant `L3_TABLES` at [validate_schema_parity.py:47](scripts/pipeline/validate_schema_parity.py:47), 29 tables total. Exposed via `get_l3_tables()` at [:92](scripts/pipeline/validate_schema_parity.py:92). CLI `--tables` narrows the set but rejects anything not in `L3_TABLES` ([:777](scripts/pipeline/validate_schema_parity.py:777)). No dynamic discovery — the list is curated to match `docs/data_layers.md` §2.

**Current coverage (29 tables).**
- Entity MDM core (7): `entities`, `entity_identifiers`, `entity_relationships`, `entity_aliases`, `entity_classification_history`, `entity_rollup_history`, `entity_overrides_persistent`
- Entity MDM additional (7): `cik_crd_direct`, `cik_crd_links`, `lei_reference`, `other_managers`, `parent_bridge`, `fetched_tickers_13dg`, `listed_filings_13dg`
- Reference / other L3 (11): `securities`, `market_data`, `short_interest`, `fund_universe`, `shares_outstanding_history`, `adv_managers`, `ncen_adviser_map`, `filings`, `filings_deduped`, `cusip_classifications`, `_cache_openfigi`
- Core facts (3): `beneficial_ownership_v2`, `fund_holdings_v2`, `holdings_v2`
- Staging companions (2): `entity_identifiers_staging`, `entity_relationships_staging`

**Introspection.** Four DuckDB system-table queries per table, all scoped to `database_name = current_database() AND schema_name = 'main'`:
- `introspect_columns` → `duckdb_columns()` — name, data_type, is_nullable, column_default, column_index ([:158](scripts/pipeline/validate_schema_parity.py:158))
- `introspect_indexes` → `duckdb_indexes()` — index_name, is_unique, is_primary, sql ([:176](scripts/pipeline/validate_schema_parity.py:176))
- `introspect_constraints` → `duckdb_constraints()` — constraint_type, constraint_text ([:193](scripts/pipeline/validate_schema_parity.py:193))
- `introspect_ddl` → `duckdb_tables()` — CREATE TABLE body ([:202](scripts/pipeline/validate_schema_parity.py:202))

**Normalizers** (applied before comparators, [:212-331](scripts/pipeline/validate_schema_parity.py:212)):
- DDL whitespace collapse / trailing semicolon strip
- `NOT NULL` constraint dedupe (duplicates `is_nullable=False` from `duckdb_columns`)
- PK ↔ UNIQUE-index equivalence (one side PK, other side UNIQUE index on identical column set → both dropped)

**Accept-list contract** ([:474-520](scripts/pipeline/validate_schema_parity.py:474)): YAML file; each entry matched by case-insensitive `(table, dimension, detail)` tuple. Validator rejects entries with `justification` shorter than 30 chars, unknown dimensions, missing required fields, or ISO-malformed `expiry_date`. Expired or stale entries surface in the report.

**Exit codes**: 0 = parity or all divergences accepted (without `--fail-on-accepted`); 1 = unaccepted divergence or expired entry; 2 = invocation error.

---

## §2. Current accept-list state

[config/schema_parity_accept.yaml](config/schema_parity_accept.yaml) (41 lines): the `accepted:` list is empty. Baseline policy set at INF39 block close (2026-04-19, BLOCK_SCHEMA_DIFF §13.2): Option B "remediate-all" — Phase 1 staging rebuild produced **zero divergences**, so anything new is real drift and must be remediated or justified.

The example block is commented out because the validator rejects short-justification entries (including its own example).

---

## §3. L4 table inventory (full)

From [docs/data_layers.md:94-131](docs/data_layers.md:94) (`| L4 |` rows):

| # | Table | Rebuild pattern | Row count | Note |
|---|---|---|---|---|
| 1 | `beneficial_ownership_current` | `promote_13dg.py` + `rebuild_beneficial_ownership_current` | 24,756 | Latest-per-(filer_cik, subject_ticker); 5 entity columns enriched |
| 2 | `summary_by_parent` | `build_summaries.py` rebuild per (quarter, rollup_type) | 63,916 | PK `(quarter, rollup_type, rollup_entity_id)` per migration 004 |
| 3 | `summary_by_ticker` | `build_summaries.py` rebuild per quarter | 47,642 | Rollup-agnostic |
| 4 | `investor_flows` | `compute_flows.py` rebuild per (period, rollup_type) | 17,396,524 | 4 periods × 2 worldviews (EC + DM) |
| 5 | `ticker_flow_stats` | `compute_flows.py` rebuild per (period, rollup_type) | 80,322 | 40,161 × 2 worldviews |
| 6 | `managers` | `build_managers.py` rebuild | 12,005 | Derived from `entity_current` + `adv_managers` |
| 7 | `fund_classes` | `build_fund_classes.py` rebuild | 31,056 | Fund class → series |
| 8 | `fund_family_patterns` | `migrate_batch_3a.py` seed + manual edits | 83 | N-PORT fund-family regex patterns |
| 9 | `fund_best_index` | `build_fund_classes.py` step 2 rebuild | 6,151 | Best-fit index per series |
| 10 | `fund_index_scores` | `build_fund_classes.py` step 1 rebuild | 80,271 | Index correlation scores |
| 11 | `fund_name_map` | `build_fund_classes.py` rebuild | ~6.23M | Fund-name → entity_id lookup |
| 12 | `index_proxies` | `build_fund_classes.py` rebuild | 13,641 | |
| 13 | `benchmark_weights` | `build_benchmark_weights.py` rebuild | 55 | Per-quarter US-equity sector weights |
| 14 | `peer_groups` | Manual seed | 27 | Sector peer-group reference |
| 15 | `entity_current` | `entity_schema.sql` rebuild (VIEW) | — | L4 VIEW (not a base table) |

**14 base tables + 1 VIEW.** Matches BLOCK_SCHEMA_DIFF §9 / §14 scope exactly.

### L3 vs L4 — what's currently missing

All 15 of the above are outside the current `L3_TABLES` constant. None have accept-list entries (accept-list is empty).

---

## §4. Known gap: `entity_current` is a VIEW

Current `introspect_ddl` ([:202](scripts/pipeline/validate_schema_parity.py:202)) queries `duckdb_tables()` — which does **not** include views. For `entity_current` the query returns empty, so `compare_ddl` reports `prod="" vs staging=""` (parity) even if the VIEW definition differs between environments.

Known context (memory / BLOCK_SCHEMA_DIFF §10 Q3, §15 bullet 5):
- `entity_current` is the **only user-defined view in prod**
- Q3 at Phase 1 sign-off deferred VIEW handling to INF45 (this item)
- Staging rebuild 2026-04-19 recreated the view; parity at that point was fine

Two options for Phase 1:

**Option A — Defer VIEW (recommended).** Cover the 14 base tables only; leave `entity_current` to a micro-follow-up. Minimal validator change (one constant + wiring).

**Option B — Extend introspection to views.** Add `introspect_view_ddl` using `duckdb_views()`, add a `view` comparator branch or route VIEW rows through `compare_ddl`. Touches more surface area; requires a new test class for VIEW introspection.

Recommend A. INF45 trigger per §9 is "a concrete incident where an L4 build fails on prod but passed on staging"; VIEW drift is a separate failure mode (app-tab queries against `entity_current`) and belongs in its own micro-item.

---

## §5. Changes needed for Phase 1

### 5.1 Validator code (minimal)

[scripts/pipeline/validate_schema_parity.py](scripts/pipeline/validate_schema_parity.py):

1. **Add `L4_TABLES` constant** near `L3_TABLES` ([:47](scripts/pipeline/validate_schema_parity.py:47)). 14 entries per §3 above (exclude `entity_current` per §4).
2. **Add `get_l4_tables()`** mirroring `get_l3_tables()` ([:92](scripts/pipeline/validate_schema_parity.py:92)).
3. **Add `--layer` CLI flag** to `main()` ([:737](scripts/pipeline/validate_schema_parity.py:737)) accepting `l3` (default — preserves current behavior), `l4`, or `all`. Compose the table list from the chosen layer(s). Keep existing `--tables` behavior; widen its allow-list to `L3_TABLES ∪ L4_TABLES`.
4. **Update report header** (`format_human` [:547](scripts/pipeline/validate_schema_parity.py:547), `_human_from_report` [:817](scripts/pipeline/validate_schema_parity.py:817)) to reflect the active layer.
5. **Report `layer` in the JSON `summary`** so downstream tooling can distinguish L3-only runs from mixed runs.

Default remains **L3-only** to preserve current semantics for anyone invoking the validator today (including the Phase 2 pre-flight Makefile target). L4 coverage is opt-in via `--layer l4` or `--layer all`.

Estimated diff size: ~60–100 LoC added, zero lines modified in existing comparator/normalizer logic.

### 5.2 Accept-list (`config/schema_parity_accept.yaml`)

Start empty. Two scenarios to expect on the first L4 run against prod+staging:

- **Most likely — zero divergences.** L4 tables are DROP+CTAS regenerated each cycle; if both DBs were last rebuilt from the same code, schemas match.
- **Possible drift sources:**
  - `beneficial_ownership_current` is **not** CTAS — `rebuild_beneficial_ownership_current` runs incremental patches on the table. Schema evolution via ALTER is plausible.
  - `summary_by_parent` PK was changed by migration 004 (2026-04-16). If one DB had the migration applied and the other didn't at some snapshot, PK drift would appear — but staging rebuild 2026-04-19 should have caught that.
  - `fund_name_map` and `investor_flows` are the two large tables; column-default drift would manifest as a `columns` divergence with `column_default` differing.

If the first run surfaces drift, remediate per §13.1 of BLOCK_SCHEMA_DIFF (staging rebuild), not by adding accept-list entries — Option B remediate-all remains the baseline policy.

### 5.3 Unit tests

[tests/pipeline/test_validate_schema_parity.py](tests/pipeline/test_validate_schema_parity.py) (678 lines) already covers comparator + normalizer + accept-list + introspection logic with synthetic duckdb fixtures. Additions for Phase 1:

1. `TestL4TableList` — assert `L4_TABLES` is non-empty and disjoint from `L3_TABLES` (no accidental double-listing).
2. `TestLayerFlag` — `--layer l3` yields the current 29 tables; `--layer l4` yields 14; `--layer all` yields 43; invalid value exits 2.
3. `TestL4IntrospectionSmoke` — build a tmp_path DuckDB with 2–3 L4 tables (`summary_by_parent`, `benchmark_weights`, a synthetic `fund_classes`), run `compare_table` against an identical copy, assert zero divergences. Confirms introspection SQL works against real L4 DDL shapes.

Estimated test additions: 30–50 LoC.

### 5.4 Docstring / README touch-ups

- Module docstring at [:2-21](scripts/pipeline/validate_schema_parity.py:2) mentions only L3; extend to "L3 + L4 base tables" with a note that `--layer` defaults to L3.
- `config/schema_parity_accept.yaml` header (line 8) lists dimensions — no change needed.

### 5.5 No Phase 2 blocker

REMEDIATION_PLAN.md:325 notes that **Phase 2 migration adds a new L0 table and column-adds three L3 tables**. L4 parity (mig-09) is **not** on the critical path for Phase 2 — that requirement is satisfied by L3 (already covered) + L0 (sibling mig-10). mig-09 can land independently and feeds mig-11 (CI wiring).

---

## §6. Phase 1 file list and effort

**Files touched:**
- `scripts/pipeline/validate_schema_parity.py` (~60–100 LoC added)
- `tests/pipeline/test_validate_schema_parity.py` (~30–50 LoC added)
- `config/schema_parity_accept.yaml` — only if first run surfaces drift (likely no change)
- `docs/data_layers.md` — optional: add a one-line note under `validate_schema_parity.py` cross-reference

**Out of scope for Phase 1:**
- `entity_current` VIEW (§4 Option A — deferred to micro-follow-up)
- CI wiring (mig-11 / INF47)
- L0 coverage (mig-10 / INF46, sibling)

**Effort estimate:** 1 working session. Validator additions are mechanical; tests piggyback on the existing fixture pattern; the only unknown is the first real-DB run — if it returns zero divergences, ship. If it returns drift, triage before committing accept-list entries.

---

## §7. Risk notes

1. **Sibling parallelism (mig-10).** mig-10 also edits `L3_TABLES` region and `config/schema_parity_accept.yaml`. Disjoint accept.yaml sections (empty today) reduce conflict risk but both PRs touch the same constants block in the validator. Merge order matters — recommend mig-10 goes first (L0 is the Phase 2 blocker) then rebase mig-09. Or land them together as a single batched PR.

2. **L4 indexes / constraints likely sparse.** Most L4 rebuild paths are `DROP TABLE; CREATE TABLE AS SELECT ...` which produces tables with zero indexes and zero constraints beyond NOT NULL. The validator will report parity trivially. This is fine — it means the dimension survey is cheap; it also means the informational value of L4 parity is lower than L3. INF45 §9 explicitly names this as the reason for original deferral.

3. **`fund_name_map` size.** 6.23M rows. Schema introspection is metadata-only (DuckDB catalog tables) so row count is irrelevant to the parity check; noted for awareness in case anyone reuses the tables list for a row-level check later.

4. **`beneficial_ownership_current` is ALTER-driven.** Unlike the other 13 L4 tables, this one is not DROP+CTAS — it's mutated by `shared.rebuild_beneficial_ownership_current`. Schema drift risk is marginally higher. First real-DB run will reveal whether it matches.

5. **Staging missing tables.** If any L4 table exists in prod but not staging (or vice versa), `introspect_columns` returns `[]` on the missing side; `compare_columns` then emits one "column added" divergence per prod column — potentially dozens of noisy rows. Unlikely given the 2026-04-19 staging rebuild covered all 4 L4 outputs (`holdings_v2_enrichment`, `investor_flows`, `ticker_flow_stats`, `summary_by_parent`, `summary_by_ticker`) but worth catching in Phase 1 with a missing-table pre-check that emits a single clean `ddl` divergence instead.

6. **Report header count.** `_human_from_report` at [:817](scripts/pipeline/validate_schema_parity.py:817) hardcodes `L3 ({len(L3_TABLES)} tables inc. staging companions)` — needs templating by the active layer, otherwise L4 or mixed runs print a misleading header.

---

## §8. Open questions for Phase 1 sign-off

**Q1. `entity_current` VIEW — in or out of Phase 1?** Recommendation: out (§4 Option A). Defer to a micro-item once INF45 is live; keep this PR minimal.

**Q2. `--layer` default — L3 or all?** Recommendation: L3 default to preserve backward compatibility with existing callers (Phase 2 pre-flight Makefile target, any scripted invocations). L4 coverage opt-in.

**Q3. Sibling merge order with mig-10.** Recommendation: land mig-10 first (it's the Phase 2 migration blocker per REMEDIATION_PLAN.md:325), rebase mig-09 on top. Alternative: combined PR. Serge's call.

**Q4. Should first real L4 parity run be reported in the Phase 1 PR?** Recommendation: yes — include `pytest` output plus a manual `--layer l4 --json` run against local prod/staging DBs in the PR description so reviewer sees the empirical baseline.

---

_End of Phase 0 findings. No code changes, no DB writes, no migrations. Findings doc is the only artifact._
