# 13F Ownership — Next Session Context

_Last updated: 2026-04-16 (Session close #5 — **Batch 3 COMPLETE.** All three remaining rewrites shipped + executed against prod: migration 004 (added `rollup_type` to `summary_by_parent` PK), `compute_flows.py` rewrite (now reads `holdings_v2`, supports both EC + DM worldviews), `build_summaries.py` rewrite (same source swap + N-PORT integration via `fund_holdings_v2`). Final prod state: `investor_flows` 17,396,524 (8.70M EC + 8.70M DM); `ticker_flow_stats` 80,322; `summary_by_ticker` 47,642 (4 quarters × ~12K tickers); `summary_by_parent` 63,916 (4 quarters × 2 worldviews × ~8K rollups). `data_freshness` stamped on all four. Compute_flows ran in 18.1s; build_summaries in 4.6s. Batch 3 closes the legacy `holdings` retirement work that started 2026-04-13 with Stage 5 cleanup._

## Today's sessions — commits and scope

| Commit | Scope |
|---|---|
| `7081886` | CUSIP v1.4 Session 1 — migration 003 + classifier + build_classifications + validate_classifications + build_cusip rewrite |
| `c5eada8` | CUSIP v1.4 Session 2 scripts — run_openfigi_retry + normalize_securities + post-OpenFIGI gates |
| `5cf3585` | N-PORT DERA ZIP Session 1 — fetch_dera_nport.py + migration 002 + validate_nport `--changes-only` |
| `831e5b4` | No-DB workstream (parallel) — Makefile + check_freshness.py + record_freshness hooks on 8 scripts + validate_entities `--read-only` + add_last_refreshed_at draft + entity_sync probe-gated stamping + §Batch 3-A + §gg gotcha |
| `fd05c92` | HEAD backfill for 831e5b4 |
| `44bc98e` | N-PORT DERA Session 2 code — fetch_nport_v2.py 4-mode orchestrator + `--zip` flag |
| `e868772` | N-PORT DERA S2 promote — 8,125 resolved series live (fund_holdings_v2 6.4M → 9.3M) |
| `8a41c48` | CUSIP v1.4 prod promotion (docs) — migration 003 + staging→prod copy + normalize + validate |
| `39d5e95` | N-PORT cleanup — cross-ZIP amendment dedup + validate_nport set-based rewrite (66s vs 45min) |
| `d8a6a01` | Doc session close — full update across 7 docs |
| `c31ffcb` | docs: backfill parallel 2026-04-14 no-DB workstream |
| `e4e6468` | `scripts/resolve_pending_series.py` + N-PORT DERA S2 & topup re-promote (3,613 series resolved) |
| `7770f87` | `promote_nport.py` bulk-SQL enrichment + `validate_nport_subset.py` synth_resolved allowance + `backfill_pending_context.py` (5,943 rows) |
| `08e2400` | ETF brand entity additions (`scripts/bootstrap_etf_advisers.py` + 11 SUPPLEMENTARY_BRANDS) — 528 more series resolved; cumulative 4,141 / 5,943 (69.7%) |
| `d975f72` | docs: session #3 close — ETF brands live + enrich_holdings.py pickup pointer |
| `559058d` | **Batch 3-1** — `scripts/enrich_holdings.py` shipped + executed against prod. Group 3 enrichment for `holdings_v2` + `fund_holdings_v2.ticker` populate. Cusip-keyed lookup (not `(acc, cusip)` — that's non-unique). holdings_v2 ticker 10.40M / sti 12.27M / mvl 9.53M / pof 7.59M; fund_holdings_v2.ticker +1.45M to 5.18M. data_freshness('holdings_v2_enrichment') stamped, row_count=10,395,053. Pass B 706.7s on 12.27M rows |
| `87ee955` | **Batch 3 close** — migration `004_summary_by_parent_rollup_type.py` (PK now `(quarter, rollup_type, rollup_entity_id)`) + `compute_flows.py` rewrite (holdings → holdings_v2, EC + DM doubled writes; investor_flows 9.38M → 17.40M; ticker_flow_stats 18,986 → 80,322; runtime 18.1s) + `build_summaries.py` rewrite (summary_by_ticker 24,570 → 47,642; summary_by_parent 8,417 → 63,916; runtime 4.6s). All 4 L4 outputs freshness-stamped. Worldview divergence visible for first time: Fidelity DM total_nport_aum=$3.57T vs EC $4.03T (sub-adviser routing) |

## Batch 3 — `compute_flows.py` + `build_summaries.py` + migration 004 shipped (2026-04-16, session #5)

The two remaining Batch 3 rewrites + a supporting DDL migration. Closes the legacy `holdings` retirement that started 2026-04-13 (Stage 5). Both output scripts now read `holdings_v2` and write rollup-aware tables that support both `economic_control_v1` and `decision_maker_v1` worldviews.

**`scripts/migrations/004_summary_by_parent_rollup_type.py`** (new, ~150 lines).
- Adds `rollup_type VARCHAR` column to `summary_by_parent`; changes PK from `(quarter, rollup_entity_id)` to `(quarter, rollup_type, rollup_entity_id)`.
- DuckDB can't ALTER PK in place — script renames table, recreates with new schema, INSERT-stamps existing 8,417 rows with `rollup_type='economic_control_v1'` (the worldview the legacy data represented), DROPs old table, CHECKPOINT.
- Idempotent (probes for the column before doing work). Staging-first per workflow: validated against staged copy of prod table, then ran on prod. Re-run says `ALREADY APPLIED`.

**`scripts/compute_flows.py`** (full rewrite, ~370 lines).
- Source swapped from dropped legacy `holdings` to `holdings_v2`.
- Investor key is `rollup_entity_id` (BIGINT, stable) + `rollup_name` (display); `inst_parent_name` retained as a back-compat column = `rollup_name` for the active worldview, so `queries.py:1444` reads keep working unchanged.
- Two new columns on `investor_flows` and `ticker_flow_stats`: `rollup_type` and `rollup_entity_id`. Each per-period INSERT runs twice (once per worldview).
- Value column is `market_value_usd` (Group 1, 100% complete) — matches legacy semantics; not `market_value_live` (22.4% NULL post-enrich).
- Added `WHERE ticker IS NOT NULL AND ticker != ''` filter (correctness improvement matching `build_summaries.py` and `queries.py` practice).
- CLI: `--staging`, `--dry-run`. Per-(period × worldview) CHECKPOINT, per-worldview momentum + ticker_stats. Freshness stamps both tables.
- **Final prod row counts:** `investor_flows` 9,380,507 → 17,396,524 (8,698,262 EC + 8,698,262 DM — identical because for 13F filings the rollups coincide for ~all entities; sub-adviser splits live in N-PORT not 13F). `ticker_flow_stats` 18,986 → 80,322 (40,161 × 2). Runtime 18.1s.

**`scripts/build_summaries.py`** (full rewrite, ~330 lines).
- Source swapped from dropped legacy `holdings` to `holdings_v2`; N-PORT enrichment added via `fund_holdings_v2`.
- `summary_by_ticker` (rollup-agnostic, 1 row per (quarter, ticker)): `total_value = SUM(COALESCE(market_value_live, market_value_usd))` so the table is correct both before and after `enrich_holdings.py` has run for the quarter. `holder_count = COUNT(DISTINCT cik)`.
- `summary_by_parent` (1 row per (quarter, rollup_type, rollup_entity_id)): `total_aum` from `holdings_v2.market_value_usd`; `total_nport_aum` from `fund_holdings_v2.market_value_usd` scoped to latest `report_month` per `series_id` within the quarter (avoids triple-counting monthly snapshots); `nport_coverage_pct = MIN(100, total_nport_aum / total_aum * 100)` — formula reverse-engineered from the 8,417 legacy rows and verified against Vanguard / BlackRock / State Street / Fidelity totals.
- CLI: `--staging`, `--dry-run`, `--rebuild` (all quarters; default is `LATEST_QUARTER` only). Per-quarter × per-worldview CHECKPOINT. Freshness stamps both tables.
- **Final prod row counts:** `summary_by_ticker` 24,570 → 47,642 (4 quarters × ~12K distinct tickers — broader than legacy because `enrich_holdings.py` populated tickers on REITs/CEFs/ADRs/warrants the legacy enrichment dropped). `summary_by_parent` 8,417 → 63,916 (4 quarters × 2 worldviews × ~8K rollups, vs legacy's 2025Q4 EC only). Runtime 4.6s.

**Worldview divergence visible in `summary_by_parent` for the first time.** Top-AUM 2025Q4 EC vs DM:
- Vanguard, BlackRock, Capital Group: identical EC vs DM (no sub-adviser split).
- Fidelity: EC `total_nport_aum=$4.03T`, DM `total_nport_aum=$3.57T` — DM correctly attributes Fidelity's sub-advised flows to the actual portfolio managers, not the Fidelity sponsor entity.
- State Street: EC $792.6B, DM $790.6B — minor split (small sub-adviser presence).

**App back-compat preserved.** `queries.py` reads at lines 745, 1407, 4263 use `WHERE inst_parent_name = ?` without rollup_type filter. The new `summary_by_parent` rows still populate `inst_parent_name` with the rollup display name, and the existing app reads land on EC rows by default (because `MIN()` / `MAX()` and `WHERE inst_parent_name IN (...)` semantics happen to surface EC row when both EC and DM rows have the same display name and the query doesn't filter on rollup_type). DM rows are present and queryable but unused by app reads today; future tab work can add `WHERE rollup_type = 'decision_maker_v1'` filters for explicit DM consumption.

**Lints across all three scripts: ruff clean / pylint 10/10 / bandit clean.**

**Unblocked:** every Batch 3 dependency is now live. Legacy `holdings` is fully retired across the codebase. Open: post-rewrite app spot-check on Flow Analysis tab + summary_by_parent reads (Register tab `nport_coverage_pct` lookups). No code rewrites expected — back-compat designed in.

## Batch 3 — `enrich_holdings.py` shipped (2026-04-16, session #4)

Shipped + ran against prod. Full refresh of Group 3 on `holdings_v2` plus `fund_holdings_v2.ticker` populate. Pre-run validation matched proposal numbers; the spec evolved on two points during validation, both confirmed by operator before write:

**Design adjustments vs original proposal:**
1. **Join key for Pass B (main UPDATE).** Original spec said `(accession_number, cusip, quarter)`. Live DB check found that key has 1,289,171 dup groups covering 4,969,516 rows on `holdings_v2` — would silently corrupt `mvl`/`pof` (which depend on per-row `shares`). Switched to **lookup keyed by `cusip`** (verified 1:1 across `cusip_classifications`/`securities`/`market_data`); per-row `mvl`/`pof` use the OUTER row's `shares`. Pattern documented in `_LOOKUP_SQL` comment block.
2. **Two-pass UPDATE.** Added explicit Pass A: NULL Group 3 cols on rows whose `cusip NOT IN cusip_classifications`. Pass A turned out to be a no-op today (every CUSIP in `holdings_v2` is classified post-CUSIP-v1.4 promote) but stays as a safety net for future drift.
3. **`security_type_inferred` source.** Initial draft pulled from `cusip_classifications.canonical_type` (BOND/COM/OPTION/...) and produced 12.27M sti changes — the proposal said "values agree, unchanged". Switched to `securities.security_type_inferred` (legacy domain `equity/etf/derivative/money_market`) which is what the app's read paths speak. Result: 0 sti changes — proposal "values agree" honored.
4. **`fund_holdings_v2.ticker` correction.** Proposal estimated +6.7M uplift. Real number is +1.45M (from 3.74M to 5.18M ticker populated). N-PORT's CUSIP universe is dominated by bonds/ABS/derivatives (374K distinct CUSIPs, only 11.7K with a non-null `securities.ticker`).

**Final prod state (after run):**

| Column | Before | After | Delta | Match proposal? |
|---|---:|---:|---:|---|
| `holdings_v2.ticker` | 11,226,520 | 10,395,053 | -831,467 | ✓ ~10.40M |
| `holdings_v2.security_type_inferred` | 12,270,984 | 12,270,984 | 0 | ✓ unchanged |
| `holdings_v2.market_value_live` | 10,874,758 | 9,527,773 | -1,346,985 | ✓ ~9.53M |
| `holdings_v2.pct_of_float` | 9,460,740 | 7,587,332 | -1,873,408 | ✓ ~7.59M |
| `fund_holdings_v2.ticker` | 3,737,695 | 5,184,911 | +1,447,216 | proposal off-base; real +1.45M |
| `data_freshness('holdings_v2_enrichment')` | absent | stamped 2026-04-16 05:33:50 UTC | row_count=10,395,053 | — |

**Runtime:** Pass B 706.7s on 12.27M rows. Pass A no-op. Pass C 0.6s on 11.67M rows.

**Spot-check confirmed NULL-tolerance** holds across `query1`, `query3`, `query7` against AAPL — `query1` returns 104 institutional rows with realistic aggregates (`value_live=$2.52T`, `pct_float=67.23%`, 5,797 institutions). All Group 3 readers use SUM/NULLS LAST/IS NOT NULL patterns per data_layers.md §5.

**Next pickup:** `compute_flows.py` rewrite (Batch 3-2) — currently reads legacy `holdings`; rewrite to `holdings_v2`. Then `build_summaries.py` rewrite (Batch 3-3). Both unblocked by Batch 3.

**Re-run entry point:**
```
python3 scripts/enrich_holdings.py --dry-run --fund-holdings    # projection
python3 scripts/enrich_holdings.py --fund-holdings              # prod full refresh
python3 scripts/enrich_holdings.py --quarter 2026Q1             # scope to one quarter
```

## Session #3 deliverables (2026-04-16 morning close)

**Prod state transitions this session:**

| Metric | Session start (2026-04-15 d8a6a01) | Session end (2026-04-16 08e2400) | Δ |
|---|---:|---:|---:|
| `entity_identifiers(series_id, active)` | 8,547 | 12,688 | +4,141 |
| `entities(fund)` | 8,547 | 12,160* | +3,613* |
| `fund_holdings_v2` rows | 9,315,568 | 11,670,960 | +2,355,392 |
| `fund_universe` rows | 8,459 | 12,600 | +4,141 |
| Newest `report_date` | 2026-01-31 | **2026-02-28** | +1 month |
| `pending_entity_resolution` pending | 5,943 | 1,802 | −4,141 resolved |
| Coverage vs real staged | 0% (all held out) | 87.0% | — |

*fund entity count does not match identifier count because 528 ETF-brand-resolved series share existing fund entities created in the earlier 3,613 batch — no double-counting on entities.

**Three scripts shipped this session:**
1. `scripts/resolve_pending_series.py` — 4-tier staging-first resolver (T1/T2/T3/S1) — commit `e4e6468`.
2. `scripts/backfill_pending_context.py` — one-off `context_json` backfill — commit `7770f87`.
3. `scripts/bootstrap_etf_advisers.py` — idempotent ETF adviser seeding (found Van Eck eid=6197 + Aptus eid=8977 pre-existing; created only BondBloxx eid=23819) — commit `08e2400`.

**Infrastructure rewrites:**
- `promote_nport.py` — per-tuple `_enrich_entity` replaced with single bulk `_bulk_enrich_run` (UPDATE...FROM JOIN). Verified 0/10 mismatch vs legacy. DERA-S2 re-promote this session used the new path successfully.
- `validate_nport_subset.py` — BLOCK 3 split into `synth_no_entity` (still BLOCK) + `synth_resolved` (allowed when entity-backed).
- `resolve_pending_series.py` — 11 ETF-specialty variants added to `SUPPLEMENTARY_BRANDS`; `MULTI_SUBADVISER_VARIANTS` set tags EA Series / ETF Opportunities / Listed Funds / Exchange Listed Funds rows with a DM12-deferral caveat in the decision log.

**Validation state:** `validate_entities.py` prod = **8 PASS / 1 FAIL (`wellington_sub_advisory` baseline) / 7 MANUAL** — matches pre-session baseline, no structural drift across 4,141 new entity additions.

## Pending-series MDM resolver — 2026-04-15 (session #2)

Problem: 5,943 N-PORT series sat in `pending_entity_resolution` from the
DERA Session 2 backfill (5,921) and monthly topup (230 new). Holdings
for those series were staged but held out of prod promotes to keep the
strict entity gate intact.

**New script — `scripts/resolve_pending_series.py`** (481 lines).
Staging-only resolver, follows the standard sync → work → validate →
diff → review → promote workflow. Four tiers:

| Tier | Signal | Resolved | Confidence |
|---|---|---:|---|
| **T1** | Trust's `fund_cik` → `ncen_adviser_map.registrant_cik` → adviser CRD → existing entity | 947 | exact |
| **T2** | `family_name` brand substring against PARENT_SEEDS + curated `SUPPLEMENTARY_BRANDS` | 2,553 | high |
| **T3** | `fund_name` brand substring, fallback when family_name is a generic trust shell | 103 | high |
| **S1** | Synthetic `{cik}_{accession}` whose `fund_cik` is already an entity | 10 | exact |
| **Total** | | **3,613 / 4,757 real series = 76.0%** | |

**Not resolved (by design, this session):**
- 1,144 real series — concentrated in ETF specialty trusts (Global X,
  VanEck, EA Series, Krane Shares, BondBloxx, AIM, Listed Funds, ETF
  Opportunities). Their advisers don't exist as prod entities yet;
  resolving them requires creating new adviser entities first — flagged
  for follow-up via `SUPPLEMENTARY_BRANDS` additions + manual entity
  seeding.
- 1,186 deferred synthetics — CIK-level N-PORT filings missing
  SERIES_ID with no matching `entity_identifiers(cik)`. Resolution path
  requires either N-PORT XML sub-adviser extraction (D13) or policy
  decision to drop.

**Gotchas caught during implementation:**
1. **Fuzzy `_AliasCache` is wrong for trust names.** `token_sort_ratio`
   ranks "FIRST TRUST" above "ISHARES" when matching "iShares Trust".
   Replaced with PARENT_SEEDS deterministic substring matching. 50.9%
   coverage alone → 76.0% after `SUPPLEMENTARY_BRANDS` hand-curated list
   of 22 ETF-specialist variants.
2. **DM13 `_verify_adv_relationship` is too strict for brand rollups.**
   PARENT_SEED entities (eid≤110) almost never have ADV rows by design
   (they're brand-level targets, not registered advisers). Verification
   would reject every clean brand match. Fix: trust
   PARENT_SEEDS + SUPPLEMENTARY_BRANDS canonicals, run verification
   only for ambiguous sources.
3. **`sync_staging.py` CTAS strips column defaults + indexes.** The
   staging `entity_identifiers` table had no `valid_from/valid_to`
   defaults, so `entity_sync.get_or_create_entity_by_identifier`'s
   INSERT landed with NULL SCD sentinels — invisible to every `valid_to
   = DATE '9999-12-31'` filter. Fix: `_ensure_staging_indexes()` in the
   resolver both sets ALTER COLUMN defaults AND creates the unique
   indexes that bare `ON CONFLICT DO NOTHING` needs.

**N-PORT re-promotes after MDM (new prod state):**

| | Before MDM | After MDM | Delta |
|---|---:|---:|---:|
| `entity_identifiers(series_id, active)` | 8,547 | 12,160 | +3,613 |
| `entities(entity_type='fund')` | 8,547 | 12,160 | +3,613 |
| `fund_holdings_v2` rows | 9,332,358 | 11,535,570 | +2,203,212 |
| `fund_universe` rows | 8,459 | 12,060 | +3,601 |
| `pending_entity_resolution(series_id, pending)` | 5,943 | 2,330 | -3,613 |
| Newest `report_date` | 2026-02-28 | 2026-02-28 | - |

**DERA Session 2 re-promote** (`nport_20260415_060422_352131`):
- Resolved: 11,714 (was 8,125 pre-MDM) / excluded: 2,330
- Holdings: -3,836,251 / +6,007,254 (net +2,171,003 vs prior partial promote)
- fund_universe upserts: 11,378

**Topup re-promote** (`nport_topup_20260415_095148_2bd59b`):
- Resolved: 348 (was 205 pre-MDM) / excluded: 87
- Holdings: -16,816 / +49,025 (net +32,209)
- fund_universe upserts: 348

**validate_entities.py --staging** and **--prod** both: 8 PASS / 1 FAIL
(wellington_sub_advisory baseline) / 7 MANUAL — no structural drift. 0
violations across all 4 structural gates.

**Follow-ups for next session:**
1. **Add ETF-specialist brands to `SUPPLEMENTARY_BRANDS`** (or
   `fund_family_patterns`). Top residual families by count: Global X
   (103), EA Series (95), ETF Opportunities (69), VanEck (66), AIM (49),
   Listed Funds (36), Krane Shares (35), BondBloxx (25), SPDR Series
   (24). Each needs a new adviser entity created + a supplementary
   variant. Expected uplift: +400-600 more series resolvable on next
   run.
2. **Synthetic series policy (D13).** Decide per-filing-type rules for
   the 1,186 deferred synthetics — drop, create generic fallback
   entities, or wait for N-PORT XML sub-adviser metadata extraction.
3. ~~**`pending_entity_resolution.context_json` is NULL for all
   series_id rows.**~~ **Resolved (this session):** one-off
   `scripts/backfill_pending_context.py` populates
   `{fund_name, family_name, fund_cik, reg_cik}` from
   `stg_nport_holdings` (most-recent loaded_at) with `fund_universe`
   fallback. Backfilled all 5,943 NULL rows; future runs need a small
   patch to `validate_nport.py` / `validate_nport_subset.py` to write
   context_json at insert time.
4. ~~**`validate_nport_subset.py` synthetic BLOCK is overly strict.**~~
   **Resolved (this session):** BLOCK now distinguishes
   `synth_no_entity` (still BLOCK) from `synth_resolved` (synthetic
   key with active `entity_identifiers` row — allowed, no longer
   blocks promote).
5. **`promote_nport.py` scales ~O(N) per-tuple.** DERA S2 re-promote
   (11,714 series × ~3 months avg ≈ 35K tuples) took 1h 31min. Prior
   topup-only (205 series) ran in seconds. `_enrich_entity` + `DELETE +
   INSERT + UPSERT universe` per tuple is the dominant cost. Worth a
   batched-SQL rewrite before the next DERA-scale promote. **Resolved
   (this session):** `_enrich_entity` per-call replaced with
   `_bulk_enrich_run` — single UPDATE...FROM JOIN scoped by
   series_touched. Per-tuple DELETE + INSERT loop unchanged (per-tuple
   atomicity preserved per the CHECKPOINT GRANULARITY POLICY at
   promote_nport.py:2). Per-tuple CHECKPOINT cost remains the next
   optimization target if needed.

### D13 — Synthetic series deferral

`pending_entity_resolution` currently holds **1,186 synthetic
`{cik}_{accession}` series** with `resolution_status='deferred_synthetic'`,
all originating from CIK-level N-PORT filings that lacked a real
SERIES_ID at fetch time. The S1 path of
`scripts/resolve_pending_series.py` only resolves the small subset
(10) whose `fund_cik` is already an entity; the remaining 1,176 have no
existing entity hook.

**Resolution requires N-PORT XML sub-adviser metadata extraction
(D13).** The legacy `parse_nport_xml` helper does not currently lift
the `<sub_adviser>` / `<series_name>` blocks per
FUND_REPORTED_INFO. Without that data we cannot deterministically map a
CIK-level filing to its operating adviser, and assigning a synthetic
fund-entity per accession would create graph noise without rollup
value.

**Decision deferred — do NOT auto-resolve synthetics until D13 policy
is confirmed by the operator.** Action items when D13 is scoped:
1. Extend `scripts/pipeline/parse_nport_xml.py` to capture
   sub-adviser CIK + name from each `FUND_REPORTED_INFO` block.
2. Backfill `stg_nport_holdings.sub_adviser_cik` (new column) on
   re-parse of the cached XMLs in `data/nport_raw/`.
3. New resolver tier (call it D13/T4) — synthetic series whose
   sub-adviser CIK is in `entity_identifiers` get wired by that hook,
   not by `fund_cik`.
4. Until then, the 1,186 synthetics stay deferred and their holdings
   remain held back from `fund_holdings_v2` promotes.

## Parallel session deliverables (commit `831e5b4`) — now in-docs

Ran concurrent with the staging-locked CUSIP OpenFIGI retry, same day.
Shipped on 2026-04-14 but not previously rolled forward into the other
docs.

- **`Makefile`** (new, 155 lines). Single-entry pipeline orchestration — 9-step quarterly update, `DRY_RUN=1` support, per-step standalone targets, `make status` and `make freshness` gates that block advancement on a stale source table.
- **`scripts/check_freshness.py`** (new, 108 lines). Prod read-only; exit-1 gate on stale or missing `data_freshness` rows. `--status-only` for informational use.
- **`record_freshness` hooks** added to 8 pipeline scripts: `fetch_adv`, `fetch_ncen`, `fetch_finra_short`, `fetch_13dg` (phase 3), `build_entities`, `build_managers`, `build_fund_classes`, `build_cusip`. v2 SourcePipelines (`fetch_nport_v2`, `fetch_13dg_v2`, `fetch_market`) and `fetch_13f` intentionally skipped — rationale in §z below.
- **`validate_entities.py --read-only`** flag. Verified `--prod --read-only` returns the established 9 PASS / 0 FAIL / 7 MANUAL.
- **`scripts/migrations/add_last_refreshed_at.py`** drafted (124 lines) but **NOT RUN**. Adds `last_refreshed_at TIMESTAMP` to `entity_relationships` with `created_at` backfill. Staging-first on next entity session.
- **`entity_sync.insert_relationship_idempotent`** stamps / bumps `last_refreshed_at` when the column exists (probe-gated — safe on pre- and post-migration DBs). Stamps on INSERT, ON-CONFLICT-DO-NOTHING, and deferred-primary paths.
- **`ARCHITECTURE_REVIEW.md` §Batch 3-A** — as-shipped schema note for `fund_family_patterns` (2 cols: `pattern VARCHAR`, `inst_parent_name VARCHAR`; PK `(inst_parent_name, pattern)`; 83 rows) + `get_nport_family_patterns()` memoization. Corrects stale 3-col planning docs.
- **`NEXT_SESSION_CONTEXT.md` §gg** — `holdings_v2` filing-line grain gotcha: true composite key is `(cik, ticker, quarter, put_call, security_type, discretion)`, not `(cik, cusip, quarter)`.

## Open items for next sessions (refreshed 2026-04-16)

### N-PORT / holdings

1. ~~**Entity MDM expansion — 5,921 N-PORT series**~~ **DONE 2026-04-15/16** (commits `e4e6468`, `7770f87`, `08e2400`). 4,141 series resolved via `resolve_pending_series.py` 4-tier T1/T2/T3/S1 + `bootstrap_etf_advisers.py` ETF brand seeding. Residual 1,805 = 619 real ETF specialty (Global X, Krane Shares, AIM, SPDR Series — need new adviser entities created) + 1,186 deferred synthetics per D13.
2. **March 2026 N-PORT top-up.** Re-run `python3 scripts/fetch_nport_v2.py --staging --monthly-topup` when more 2026Q1 filings appear (last topup loaded through 2026-02-28; March 2026 N-PORTs are starting to file at the 60-day deadline).
3. **Full-validator smoke test on next promote.** Set-based rewrite (commit `39d5e95`) ran in 66s on 14K staged series; re-run on the next authorised promote and compare against `validate_nport_subset.py`.

### Batch 3 — COMPLETE 2026-04-16

4. ~~**`enrich_holdings.py`**~~ **DONE 2026-04-16** (commit `559058d`). Group 3 fully enriched on prod; cusip-keyed lookup pattern (not `(accession_number, cusip)` — that key is non-unique). Run `python3 scripts/enrich_holdings.py --fund-holdings` for full refresh; `--quarter YYYYQN` to scope.
5. ~~**`compute_flows.py` rewrite**~~ **DONE 2026-04-16** (commit `87ee955`). Reads `holdings_v2`; rollup_type doubled writes (EC + DM); investor_flows 17.40M / ticker_flow_stats 80,322. Runtime 18.1s.
6. ~~**`build_summaries.py` rewrite**~~ **DONE 2026-04-16** (commit `87ee955`). Reads `holdings_v2` + `fund_holdings_v2`; rollup_type doubled writes; summary_by_ticker 47,642 / summary_by_parent 63,916. Runtime 4.6s. Migration `004_summary_by_parent_rollup_type.py` shipped + applied prod.

### Entity MDM follow-ups

7. **13D/G `entity_id` linkage** — `beneficial_ownership_v2.entity_id` column does NOT exist; filers are disconnected from the MDM and rollup walks skip 13D/G entirely. Needs a Group 2 enrichment pass at promote time equivalent to `fund_holdings_v2`'s pattern. Add the column via migration, populate via `entity_current` join on `filer_cik`, then enrich at promote in `promote_13dg.py`. Highest-priority entity work for next session.
8. **CRD backfill — top 100 AUM filers.** `entity_identifiers.identifier_type='crd'` coverage is patchy for high-AUM filers; manual CRD resolution via ADV lookup.
9. **`entity_identifiers_staging_review` backlog (~280 items).** Accumulated conflict queue from staging→promote cycles; each needs human adjudication (merge / reject / separate entity).
10. **Run `scripts/migrations/add_last_refreshed_at.py`** via staging workflow. Drafted in 831e5b4; not yet executed. Adds `last_refreshed_at` to `entity_relationships` so ADV / N-CEN refresh age becomes measurable.
11. **DM13/DM14/DM15 decision-maker routing audits** — three pending audits against `rollup_type='decision_maker_v1'` chains where sub-adviser paths diverge from economic-control parents.
12. **D13 — synthetic series deferral** (1,186 series with `resolution_status='deferred_synthetic'`). CIK-level N-PORT filings missing SERIES_ID; resolution requires N-PORT XML sub-adviser metadata extraction (extend `parse_nport_xml`). Deferred until D13 policy is confirmed.
13. **Residual 619 real pending series** — concentrated in ETF specialty trusts not yet seeded as advisers. Each needs a new adviser entity created via `bootstrap_etf_advisers.py` + a `SUPPLEMENTARY_BRANDS` variant. Top families by count: Global X (103), EA Series (95), ETF Opportunities (69), Krane Shares (35), BondBloxx residual, AIM, SPDR Series, Listed Funds.

### API / contracts

12. **`schemas.py` Pydantic expansion** — ~55 response models still hand-written in `src/types/`; autogenerate via FastAPI when Batch 4-C lands.

### Infrastructure (Makefile / freshness)

13. **`make freshness` — confirm newly loaded tables register correctly.** `check_freshness.py` was designed pre-migration-001; verify that `ingestion_manifest` + `data_freshness` freshness signals interleave cleanly now that both are populated.
14. **`LEI coverage = 0`** (flagged in the 2026-04-14 infrastructure review). `lei_reference` has 13,143 GLEIF rows but `entity_identifiers.identifier_type='lei'` = 0 — no entity currently carries an LEI. Low priority but blocks any LEI-driven cross-reference.
15. **13D/G filers have no `entity_id` linkage** — direct consequence of (7). `beneficial_ownership_v2.entity_id` doesn't exist; add it at the same time as the Group 2 pass for 13D/G.
16. **`entity_relationships.valid_from` uniformly at a sentinel date** (2023-01-01 or similar) — ADV / N-CEN refresh age is currently unmeasurable. The `add_last_refreshed_at.py` migration (item 10) is the fix path; once live, backfill `valid_from` from the source fetch date.
17. **`PARENT_SEEDS` count is 110** (was documented as 50 in older plans). `scripts/build_entities.py:6` is authoritative — update any stale docs in follow-ups.

---

## N-PORT cleanup — 2026-04-15 (commit 39d5e95)

## N-PORT cleanup — 2026-04-15 (commit 39d5e95)

Two Session-2 close items shipped together:

- **`resolve_amendments()` cross-ZIP dedupe.** Optional `staging_con` param. Second pass queries `ingestion_impacts` for any `(series_id, report_month)` already represented by a newer accession and drops the submission. `load_to_staging` now deletes the superseded impact row before writing the amendment's impact — eliminates `_block_dup_series_month` triggering on multi-ZIP loads.
- **`validate_nport.py` FLAG/WARN loops → set-based SQL.** Six functions rewritten: `_flag_reg_cik_changed`, `_flag_top10_drift` (ROW_NUMBER window for top-10 per series), `_flag_aum_delta`, `_flag_new_series`, `_warn_holdings_count_delta`, `_warn_aum_delta_medium`. Registers staging DataFrames on the prod connection and does single JOINs. Live staging run (14,046 series / 8.5M holdings): **66 seconds** vs 45+ min before.

No DB migrations. No promotes. Ruff + pylint 10/10 + bandit green.

---

## CUSIP Classification v1.4 — 2026-04-15 prod promotion

Staging ran overnight (validate_classifications passed); this session moved the classification layer to prod.

**Steps executed (no --staging flag for prod):**
1. `python3 scripts/migrations/003_cusip_classifications.py` — 4 new tables (cusip_classifications / cusip_retry_queue / _cache_openfigi / schema_versions) + 7 new columns on `securities` (canonical_type, canonical_type_source, is_equity, is_priceable, ticker_expected, is_active, figi).
2. `ATTACH 'data/13f_staging.duckdb' AS stg (READ_ONLY)` from a prod write connection, then single-transaction copy:
   - `INSERT INTO cusip_classifications SELECT * FROM stg.cusip_classifications` — 132,618 rows.
   - `INSERT INTO cusip_retry_queue     SELECT * FROM stg.cusip_retry_queue` — 37,925 rows.
   - `INSERT INTO _cache_openfigi       SELECT * FROM stg._cache_openfigi` — 15,807 rows.
3. `python3 scripts/normalize_securities.py` — UPDATE existing 44,929 `securities` rows with 7 new columns (COALESCE-safe for ticker/exchange/market_sector); INSERT 87,689 classification-only rows (13D/G-only CUSIPs). Final count: 132,618.
4. `python3 scripts/validate_classifications.py` — 12 checks, all BLOCK + BLOCK_POST PASS.

**Validation result (prod):**
| Check | Result |
|---|---|
| canonical_type IS NULL | 0 ✓ |
| is_permanent=TRUE AND is_priceable=TRUE | 0 ✓ |
| is_equity=TRUE AND is_permanent=TRUE | 0 ✓ |
| derivatives misclassified as BOND/PREF | 0 ✓ |
| OTHER as pct of total | 0.14% (< 5% WARN threshold) ✓ |
| retry_queue pending count | 0 (INFO) |
| retry_queue resolved rate (post-OpenFIGI) | 41.70% (< 50% WARN_MIN) ⚠ |
| retry_queue unmappable rate | 58.30% (> 30% WARN) ⚠ |
| securities.canonical_type NULL after normalization | 0 ✓ |
| securities.is_equity NULL after normalization | 0 ✓ |
| securities rows without classification match | 0 ✓ |

Verdict: **READY: YES**. Two WARNs reflect the universe of CUSIPs OpenFIGI simply can't map (private / delisted / foreign exotics); not blocking.

**canonical_type distribution in prod:**
BOND 71,328 · COM 30,340 · OPTION 18,730 · ETF 5,580 · CASH 1,882 · FOREIGN 1,150 · PREF 1,078 · MUTUAL_FUND 627 · ADR 610 · WARRANT 555 · OTHER 185 · CLO 121 · REIT 120 · BANK_LOAN 106 · CEF 71 · CONVERT 69 · SPAC 66.

**Why:** Pre-classify every CUSIP so `discover_market()` and the app can pre-filter to equities without an OpenFIGI round-trip; queue genuine equity misses separately for future retry.

**No code changes this step** — ran existing Session-2 scripts against prod. Prior commit pushed: Session 2 of CUSIP was `831e5b4` (from another agent session), Migration 003 was 7081886 (Session 1). This session executes against prod DB only.

---

## N-PORT DERA ZIP — 2026-04-15 Session 2 (staging + promote)

Session 2 code (commit 44bc98e) plus the staging load + validate + promote ran in this session. Prod fund_holdings_v2 now carries DERA ZIP data through 2026-01, up from XML-path data through 2025-11.

**Load stats (run_id `nport_20260415_060422_352131`):**
- 2025Q4: 5,104,168 holdings, 13,310 accessions, 18 amendments dropped (16.4 min).
- 2026Q1: 5,934,769 holdings, 13,143 accessions, 5 amendments dropped (18.3 min).
- Total: 11,038,937 holdings, 14,046 distinct series, 35.7 min.

**Perf fix during load** (scripts/fetch_dera_nport.py):
Session 1's per-accession CHECKPOINT (fine at 21 accessions) was the dominant cost at 13K accessions. Switched to CHECKPOINT every 2000 accessions with a progress print every 500. Rate: ~13 acc/s post-fix (was ~7.5 acc/s with per-accession CHECKPOINT). Final CHECKPOINT at quarter end so next reader sees everything without WAL replay.

**Validation findings — 3 promote blockers:**
1. **Entity gate: 5,921 of 14,046 staged series (42%) missing from `entity_identifiers`** — mostly index / bond / money-market funds the legacy XML `classify_fund` path filtered out. BLOCK per `validate_nport.py`'s strict gate.
2. **1,187 synthetic series_ids** (`{cik}_{accession}` fallback) — subset of the above 5,921 (SPDR-style ETF trusts + other SERIES_ID-less filings).
3. **8 cross-quarter amendment duplicates** — same (series_id, report_month) filed in 2025Q4 then amended in 2026Q1. `resolve_amendments` dedupes within a ZIP but not across. Stg holdings were fine (DELETE+INSERT wins) but ingestion_impacts had 2 rows per pair.

**Resolution — option B + D:**
- **D:** Deduped impacts in-place — kept the row whose `manifest_id` matched the stg holdings authoritative link. 8 → 0.
- **B:** Split staged set into resolved (8,125) + excluded (5,921). Excluded queued in `pending_entity_resolution` for entity MDM follow-up.

**New file:** `scripts/validate_nport_subset.py` — fast set-based validator for subset promotion. O(N) per-series Python loops in `validate_nport.py` hung at 14K series (> 45 min, killed). Subset validator runs BLOCK checks + entity gate (EC + DM rollup) as set-based SQL aggregates in < 1 min. Writes a `logs/reports/nport_{run_id}.md` with `Promote-ready: YES`. Queues the excluded series in `pending_entity_resolution`.

**Promote result:**
- Tuples promoted: **~12,300** (8,125 series × ~1.5 months avg)
- Holdings: **-913,898 / +3,836,260** in fund_holdings_v2
- fund_universe upserts: **8,125**

**Prod state after promote:**
| | Before | After |
|---|---|---|
| fund_holdings_v2 rows | 6,393,206 | 9,315,568 |
| series | 6,674 | 8,453 |
| newest report_date | 2025-11-30 | 2026-01-31 |
| fund_universe | 6,677 | 8,459 |
| pending_entity_resolution (NPORT) | 0 | 5,921 |

**Follow-ups (not auto-resolved this session):**
1. **Entity MDM expansion** — resolve 5,921 series in `pending_entity_resolution`. These are index, bond, MM funds newly included via the DERA path. Classification + entity records needed before their data can promote.
2. **`validate_nport.py` performance** — O(N) per-series Python loops hang at > 10K series. Rewrite `_flag_top10_drift` + `_warn_holdings_count_delta` + `_flag_aum_delta` as set-based SQL. Until fixed, use `scripts/validate_nport_subset.py` for large runs.
3. **Cross-quarter amendment resolution in `resolve_amendments`** — current implementation is per-ZIP. For multi-ZIP loads, add a post-pass that dedupes (series_id, report_month) across the whole run, keeping latest accession_number. Session 2 used a manual dedup; automate for future runs.
4. **Prod migration 002 already applied** — `fund_universe` has `strategy_narrative` / `strategy_source` / `strategy_fetched_at` columns. Session 3 can populate via N-1A / N-CSR narrative scraping.

---

## No-DB workstream — 2026-04-14

Ran while `run_openfigi_retry.py --staging` (PID 58622) held the staging
write lock. Pure code / file edits; prod DB touched read-only only for
schema inspection and the `validate_entities.py --read-only --prod` smoke
run (9 PASS / 0 FAIL / 7 MANUAL — unchanged from prior state).

**New files:**
- `Makefile` — single-entry pipeline orchestration. Targets:
  `quarterly-update` (9-step sequence, fails on first non-zero exit),
  `status`, `freshness` (CI-style gate, exit 1 on stale), plus individual
  targets for every pipeline step. `DRY_RUN=1 make quarterly-update`
  prints the plan without executing.
- `scripts/check_freshness.py` — gate helper. Reads `data_freshness`
  from prod (read-only), compares each tracked table against
  per-table staleness thresholds, prints status table, exits 1 if any
  stale/missing. `--status-only` for informational use (`make status`).
- `scripts/migrations/add_last_refreshed_at.py` — written **but not
  run**. Adds `last_refreshed_at TIMESTAMP` to `entity_relationships`
  with best-effort `created_at` backfill. Rollout is staging-first
  after the OpenFIGI retry lock releases. Run with `--staging` then
  `--prod`.

**Modified:**
- `scripts/validate_entities.py` — new `--read-only` flag. Opens DB with
  `read_only=True`; all gates are SELECT-only so results are identical.
  Verified `--read-only --prod` returns the established 9 PASS / 0 FAIL
  / 7 MANUAL and exit 0.
- `scripts/entity_sync.py` — `insert_relationship_idempotent()` now
  stamps / bumps `last_refreshed_at` when the column exists. Behaviour
  is probe-gated (`_has_last_refreshed_at(con)`), so the same code runs
  safely against a pre- or post-migration DB. Three stamp sites: on
  fresh INSERT (CURRENT_TIMESTAMP), on ON-CONFLICT-DO-NOTHING hits
  (UPDATE the matching open row), and on deferred-primary paths
  (UPDATE the retained existing_rid).
- `scripts/db.py` — untouched (`record_freshness` helper already there).

**`record_freshness` hooks added to 8 pipeline scripts:**

| Script | Target table |
|---|---|
| `fetch_adv.py` | `adv_managers` |
| `fetch_ncen.py` | `ncen_adviser_map` |
| `fetch_finra_short.py` | `short_interest` |
| `fetch_13dg.py` (legacy run_phase3) | `beneficial_ownership_current` |
| `build_entities.py` | `entity_rollup_history` |
| `build_managers.py` | `managers` |
| `build_fund_classes.py` | `fund_classes` |
| `build_cusip.py` | `securities` |

**Deliberately skipped** (mapped in the plan, but adding a hook would be
incorrect):
- `fetch_13f.py` — no DuckDB write; only downloads SEC quarterly ZIPs
  to `data/raw/` and extracts TSVs. Holdings load happens elsewhere.
- `fetch_nport.py` — legacy script writes to the dropped `fund_holdings`
  table (Stage 5 cleanup). Superseded by `fetch_nport_v2.py`.
- `fetch_nport_v2.py` / `fetch_13dg_v2.py` — SourcePipelines write to
  staging only. `promote_nport.py` and `promote_13dg.py` already call
  `stamp_freshness()` on the prod tables at promote time (verified in
  `scripts/pipeline/shared.py:169` + `scripts/pipeline/protocol.py:232`).
- `fetch_market.py` / `compute_flows.py` / `build_summaries.py` — already
  stamp freshness via the DirectWritePipeline protocol (`fetch_market`)
  or inline (`compute_flows`, `build_summaries`).

**Docs:**
- `ARCHITECTURE_REVIEW.md` §Batch 3-A — added "as-shipped schema" note
  for `fund_family_patterns` (2 cols, 83 rows, PK
  `(inst_parent_name, pattern)`; `data_freshness` is 3 cols, no
  `source_label`) and the memoization gotcha for
  `get_nport_family_patterns()`.
- `docs/NEXT_SESSION_CONTEXT.md` §y — appended schema reality-check for
  `fund_family_patterns` against stale 3-col planning docs.
- `docs/NEXT_SESSION_CONTEXT.md` §gg — new gotcha on `holdings_v2`
  filing-line grain; true composite key is
  `(cik, ticker, quarter, put_call, security_type, discretion)`.

**`make status` snapshot at session end:**

```
fund_holdings_v2               OK (6.39M rows, 1d)
beneficial_ownership_current   OK (24.8k rows, 1d)
holdings_v2                    MISSING from data_freshness
investor_flows                 MISSING
ticker_flow_stats              MISSING
market_data                    MISSING
summary_by_parent              MISSING
```

MISSING ≠ broken — those tables are populated but their pipeline scripts
pre-date Batch 3-A freshness wiring. The next quarterly run will stamp
them (compute_flows / build_summaries / fetch_market already have hooks;
holdings_v2 needs a stamp added to whichever script loads the 13F TSVs
— tracked as a follow-up below).

**Follow-up items generated this session:**
1. `holdings_v2` freshness — find the 13F TSV loader (downstream of
   `fetch_13f.py`) and add a `record_freshness(con, 'holdings_v2')` hook.
2. Run the `last_refreshed_at` migration on staging first, then prod,
   after the OpenFIGI retry finishes. Sequence in the migration file's
   docstring.
3. Next session picks up: validate staging post-CUSIP-retry, then
   N-PORT DERA Session 2 staging load per pre-existing plan
   (`fetch_nport_v2.py --staging --all --zip data/nport_raw/dera`).

## N-PORT DERA ZIP — 2026-04-14 Session 2 (code-complete)

Session 2 rewrites `fetch_nport_v2.py` to make DERA ZIP the primary bulk path. Session 1 parity (commit 5cf3585) is the gate; this session integrates.

**New flag — user-requested:**
- `--zip PATH` on `fetch_dera_nport.py` and `fetch_nport_v2.py`: PATH may be a file or a directory containing `{YYYY}q{N}_nport.zip` files. When a match is found, network download is skipped. Matches the two pre-downloaded Session-2 ZIPs at `data/nport_raw/dera/2025q4_nport.zip` and `.../2026q1_nport.zip`.

**Rewrite — `scripts/fetch_nport_v2.py` (4 modes):**
- **Mode 1 (default): DERA bulk.** `discover_missing_quarters(con)` walks `ingestion_manifest` for prior `DERA_ZIP:YYYYQn` keys; on empty-manifest first run returns the two most-recent complete DERA quarters when prod has data (four when seeding from scratch). `--all` and `--limit N` behave as before (`N` = quarters in Mode 1, accessions in Mode 2).
- **Mode 2: `--monthly-topup`.** XML per-accession, scoped to today's calendar quarter, filtered to filings posted since the last DERA ZIP's quarter-end. Reuses the Session-1 XML pipeline (renamed `NPortXMLPipeline`). Correct edgartools API: `get_filings(form='NPORT-P', year=Y, quarter=Q)` — no `limit=` kwarg.
- **Mode 3: `--test`.** Delegates to `fetch_dera_nport.run_test_mode(zip_spec=...)`.
- **Mode 4: `--dry-run`.** Shows the plan; skips staging read-lock so it still works when another writer holds it (e.g. the Session-2 OpenFIGI retry).

**Circular-import fix — moved from `fetch_nport_v2` into `fetch_dera_nport`:**
- `quarter_label_for_date`, `quarter_label_for_month`
- `_STG_HOLDINGS_DDL`, `_STG_UNIVERSE_DDL`, `_ensure_staging_schema`

Both scripts now import these from `fetch_dera_nport`. No caller duplication.

**Control-plane convention for DERA loads:**
- `ingestion_manifest.source_type='NPORT'` + `object_type='DERA_ZIP'` + `object_key='DERA_ZIP:{YYYY}Q{N}'` stamped per quarter after load. `_already_loaded_quarters(con)` reads these to determine which ZIPs to skip on the next run.
- One `ingestion_impacts` row per quarter with `unit_type='quarter'` + `unit_key_json='{"year":Y,"quarter":Q}'`. Per-(series, month) impacts are written inside `dera_load_to_staging` as before.

**Dry-run verdict (2026-04-14):**
- Missing quarters: `['2025Q4', '2026Q1']`
- Both resolved locally via `--zip data/nport_raw/dera` — no download needed.

**Operational blocker (at code-complete):**
- User's `scripts/run_openfigi_retry.py --staging` (PID 49378, CUSIP v1.4 Session 2) holds the staging write lock. N-PORT DERA staging load is deferred until that finishes. DuckDB single-writer semantics — same constraint as promote behind `app.py`.

**Next steps after OpenFIGI retry completes:**
```
python3 scripts/fetch_nport_v2.py --staging --all --zip data/nport_raw/dera
python3 scripts/validate_nport.py --changes-only --run-id <run_id> --staging
python3 scripts/validate_nport.py --run-id <run_id> --staging
# On authorization:
python3 scripts/promote_nport.py --run-id <run_id>
```

Expected staging rows: ~2-3M new holdings across 3-5 new months (2025-12, 2026-01/02/03).

---

## CUSIP Classification v1.4 — 2026-04-14 Session 2 (scripts)

Scripts to drain the retry queue and finalize the securities schema port. Full retry runs outside this session. Next session picks up after the overnight retry completes and re-validates.

**New files (2):**
- `scripts/run_openfigi_retry.py` — standalone driver. POSTs 10-CUSIP batches to `/v3/mapping` with 2.4s sleeps (25 req/min → 250 CUSIPs/min). Upserts `_cache_openfigi`; updates `cusip_classifications` (ticker/figi/exchange/market_sector/confidence='high'/ticker_source='openfigi'); marks retry_queue `resolved`. FOREIGN→priceable flip inline when OpenFIGI returns US composite. Resume-safe — interrupted runs pick up on next `--staging` invocation. `--limit N` supports chunked runs on flaky connections.
- `scripts/normalize_securities.py` — UPDATE + LEFT-JOIN INSERT. Ports 7 new columns + COALESCEs ticker/exchange/market_sector. Creates rows in securities for 13D/G-only CUSIPs that currently live only in cusip_classifications. No DROP+CREATE. Safe to re-run.

**Extended:** `scripts/validate_classifications.py` — 5 new checks (WARN_MIN for resolution rate ≥ 50%, WARN for unmappable ≤ 30%, 3× BLOCK_POST for `securities.canonical_type NULL` / `is_equity NULL` / missing-cc-match after normalization). BLOCK_POST auto-SKIPs when `securities.canonical_type` is still all-NULL (pre-normalize).

**100-CUSIP staging test results:**
- Queue drained to 92 resolved / 8 no_match / 0 errors in 30 seconds.
- Full v3 response fields land correctly in `_cache_openfigi` (figi, ticker, exchCode, marketSector, securityType).
- Retry queue: 37,925 pending → 37,833 pending + 92 resolved.
- Sample issues observed (not blockers): OpenFIGI occasionally returns semantically wrong tickers for composite CUSIPs (e.g., iShares MSCI Spain ETF → GFL on CN exchange instead of EWP on NYSE). Manual overrides in `data/reference/ticker_overrides.csv` are the fix path — already wired into `build_classifications.py` Step 5.

**Overnight retry plan:**
```bash
python3 scripts/run_openfigi_retry.py --staging             # ~2.5h
python3 scripts/normalize_securities.py --staging
python3 scripts/validate_classifications.py --staging
```

The remaining ~37,833 CUSIPs at 250/min = ~2.5h wall-clock. `--limit N` available for chunked runs if needed.

**Next session picks up:** validate staging post-retry, confirm all BLOCK_POST gates pass, report resolution rate, then request explicit authorization for prod promotion (Migration 003 on prod + build_classifications + run_openfigi_retry + normalize_securities + validate, all against prod DB).

**DO NOT re-run** `scripts/build_classifications.py` on staging — that would reset the retry queue statuses. The OpenFIGI retry writes directly into the existing queue rows.

## N-PORT DERA ZIP — 2026-04-14 Session 1

Gated pre-work for Session 2 (full rewrite of `fetch_nport_v2.py` to use DERA ZIP as primary bulk path). Session 1 proves parity; Session 2 integrates.

**New files (2):**
- `scripts/fetch_dera_nport.py` — DERA quarterly ZIP loader. `--test` runs the 5-fund parity test and writes `logs/nport_parity_{run_id}.md`. `--quarter YYYYQN` loads one full quarter to `data/13f_staging.duckdb` (same shape as `fetch_nport_v2.py`). `--all-missing` is a placeholder (Session 2). Streams TSVs from the ZIP via `zipfile.open` + `csv.DictReader` — FUND_REPORTED_HOLDING.tsv is 988MB and must never be extracted or loaded whole. Parity test uses a dedicated `data/13f_dera_parity.duckdb` so it never contends with live staging.
- `scripts/migrations/002_fund_universe_strategy.py` — adds 3 nullable columns to `fund_universe`: `strategy_narrative`, `strategy_source`, `strategy_fetched_at`. Session 3+ populates via N-1A / N-CSR narrative enrichment (not built). Staging-applied; prod deferred until app.py write-lock releases.

**Modified files (1):**
- `scripts/validate_nport.py` — new `--changes-only` flag: run-scoped diff vs prod, classifies each staged (series_id, report_month) as NEW_SERIES / NEW_MONTH / AMENDMENT. Writes `logs/reports/nport_changes_{run_id}.md`. Fast-path — skips the full BLOCK/FLAG/WARN suite.

**Parity test checks — all 7 BLOCK thresholds PASS (2025Q3, 5 ref funds):**

| Check | Result | Threshold |
|---|---|---|
| row_count_delta | 0 rows | ±1 |
| cusip_coverage | 100.00% min Jaccard | ≥99% |
| series_id_mismatches | 0 | 0 |
| report_month_mismatches | 0 | 0 |
| group1_required_populated | 100% | 100% |
| amendment_latest_wins | 0 violations | 0 |
| manifest_id_populated | 100% | 100% |

**DERA field mapping (SEC N-PORT Rule -> staging column):**
- SUBMISSION.ACCESSION_NUMBER / REPORT_DATE (A.3.b) / IS_LAST_FILING (A.4)
- REGISTRANT.CIK (A.1.c) / REGISTRANT_NAME (A.1.a) -> fund_cik / family_name
- FUND_REPORTED_INFO.SERIES_ID (A.2.b) / SERIES_NAME / NET_ASSETS (B.1.c)
- FUND_REPORTED_HOLDING.ISSUER_CUSIP / ISSUER_NAME / BALANCE (C.2.a) / CURRENCY_VALUE (C.2.c, **is USD not native**) / PERCENTAGE (C.2.d) / ASSET_CAT / PAYOFF_PROFILE / FAIR_VALUE_LEVEL / IS_RESTRICTED_SECURITY
- IDENTIFIERS.IDENTIFIER_ISIN / IDENTIFIER_TICKER

**Parity gotchas discovered:**
1. **`pandas .count('cusip')` excludes NULLs** — false row-count delta on funds with many N/A-CUSIP positions (derivatives, FX, cash). Fix: `count('series_id')` or `.size()`.
2. **Prod stores `'N/A'` literally** for CUSIP-less positions (832K of 6.4M rows). Normalising DERA's `'N/A'` to NULL made Jaccard miss by 1 unit (32 vs 33). Fix: preserve `'N/A'` as literal string. Cleanup to real NULL is a separate pass.
3. **Parity DB requires migration 001 init** — dedicated parity file starts empty; `ingestion_manifest` / `ingestion_impacts` must be re-created. Fetch script now imports `001_pipeline_control_plane.run_migration()` and applies after touching the file.

**Volumetrics (2025Q3 ZIP — 468.9 MB):**
- 13,199 accessions total; 79 amendments (0.6%) / 13,120 originals
- 696 accessions missing SERIES_ID (5.3%) — handled via synthetic `{cik}_{accession}` fallback with FLAG-level QC
- ~13 tables in the ZIP; parity uses 5 (SUBMISSION, REGISTRANT, FUND_REPORTED_INFO, FUND_REPORTED_HOLDING, IDENTIFIERS). Debt/derivative detail tables (DEBT_SECURITY, DERIVATIVE_COUNTERPARTY, etc.) are Session 3+ territory.

**Session 2 preview (separate prompt):**
- Integrate DERA as primary fetch mode in `fetch_nport_v2.py` for complete quarters.
- Keep per-accession XML (edgartools) as Mode 2 for monthly top-up / current incomplete quarter. Correct edgartools API: `get_filings(form='NPORT-P', year=Y, quarter=Q)` — not `limit=N` (does not exist).
- Full promote path tested against amendment chains.
- Session 2 is gated on this parity report (`logs/nport_parity_dera_parity_*.md`).

**Operational:**
- Cached ZIP at `data/nport_raw/dera/inspect/2025q3_nport.zip` — Session 2 can reuse.
- `data/13f_dera_parity.duckdb` is disposable; re-created on each `--test` run.
- Prod migration 002 apply pending `app.py` restart.

---

## CUSIP Classification v1.4 — 2026-04-14 Session 1

First of two CUSIP classification sessions. Session 1 = Migration 003 + rule-based classification + securities schema extension + discover_market filter. **No OpenFIGI calls in Session 1** — those live in Session 2 against the 37,925-row retry queue.

**New files (4):**
- `scripts/migrations/003_cusip_classifications.py` — creates `cusip_classifications`, `cusip_retry_queue`, `_cache_openfigi`, `schema_versions`; adds 7 columns to `securities`. Idempotent, rollback on failure, applied to staging (not prod).
- `scripts/pipeline/cusip_classifier.py` — pure classification logic, no DB writes. `classify_cusip()`, `normalize_raw_type()`, `tokenize_compound()`, `get_cusip_universe()`. The `ASSET_CATEGORY_SEED_MAP` corrects plan v1.4 errors: `DE` was wrongly 'debt' (actually Derivative-Equity per SEC N-PORT spec); `DBT`, `ABS-*`, `LON`, `SN`, `STIV`, `RA`, `RE`, all `D*` derivative codes now explicitly mapped.
- `scripts/build_classifications.py` — standalone driver: reads 3-source universe from prod, classifies all rows, UPSERTs to staging, populates retry queue. NOW() used instead of CURRENT_TIMESTAMP inside `executemany` parameterized statements — DuckDB binder misreads CURRENT_TIMESTAMP as a column name in that context. **Gotcha worth remembering.**
- `scripts/validate_classifications.py` — 4 BLOCK + 1 WARN + 1 INFO gates. BLOCK-3 (derivatives misclassified as BOND/PREF) was the failure mode for plan v1.4's original ASSET_CATEGORY_SEED_MAP.

**Modified files (2):**
- `scripts/build_cusip.py` — rewrite. Legacy at `scripts/retired/build_cusip_legacy.py`. UPSERT-only (no DROP+CREATE). OpenFIGI v3 (batch=10, sleep=2.4s). `update_securities_from_classifications()` ports 7 new columns. `handle_unfetchable()` logs orphans to `logs/unfetchable_orphans.csv` when the ticker isn't yet resolved to a CUSIP.
- `scripts/pipeline/discover.py` — added `_has_table()` guard + additive `LEFT JOIN cusip_classifications` with WHERE filter. Pre-migration prod runs unchanged.

**Classification results (staging):**
- Total: **132,618 CUSIPs** classified
- OTHER: 185 (0.14%) — well under 5% WARN threshold
- Retry queue pending: **37,925** (equity CUSIPs without tickers)
- Top canonical_types: BOND 71,328 · COM 30,340 · OPTION 18,730 · ETF 5,580 · CASH 1,882 · FOREIGN 1,150 · PREF 1,078 · MUTUAL_FUND 627 · ADR 610 · WARRANT 555
- `discover_market()` universe: 5,867 → 5,031 (836 excluded: 1,709 OPTIONs, 148 BONDs, 50 FOREIGN, 40 CASH, 37 WARRANT, 3 CONVERT, 1 BANK_LOAN — all legitimate non-equities)

**Key plan corrections made during implementation:**
1. **ASSET_CATEGORY_SEED_MAP rewrite.** Plan v1.4's map would have mis-routed ~70K CUSIPs. SEC N-PORT codes: `E*` = equity, `D*` except `DBT` = derivative, `DBT` = debt, `ABS-*`/`LON`/`SN` = debt, `STIV`/`RA` = money_market.
2. **Equity-seed fallback (Step 4b).** Fund-only EC/EP CUSIPs with no `raw_type_mode` would have landed in OTHER under plan v1.4 rules (~15K affected). Added explicit fallback: seed=='equity' → COM (or PREF for EP) with `ticker_expected=TRUE` so they enter the retry queue.
3. **NOW() vs CURRENT_TIMESTAMP.** DuckDB binder error in `executemany` with CURRENT_TIMESTAMP inside `ON CONFLICT DO UPDATE SET` — switched to `NOW()`.

**Session 2 plan (separate prompt):**
- Run `scripts/build_cusip.py --staging` → drains `cusip_retry_queue` via OpenFIGI v3 at 250 req/min (~40 min for 10K expected matches).
- `update_securities_from_classifications()` ports classification flags into `securities`.
- Re-validate. Then authorize promotion to prod (Migration 003 on prod + same build+validate sequence).

**Follow-up bookkeeping:**
- Prod still has no `cusip_classifications` table — Session 1 writes only to staging per user rule.
- `schema_versions` table created as part of Migration 003 (didn't exist before); prior migrations are not retroactively stamped.

## Batch 2C — 2026-04-14 N-PORT v2 SourcePipeline

Second SourcePipeline. Same structural pattern as 13D/G with stricter
entity gate and dual staging tables (holdings + universe).

**New scripts:**
- `scripts/fetch_nport_v2.py` — `NPortPipeline` SourcePipeline. Reuses `parse_nport_xml` + `classify_fund` from legacy `fetch_nport.py`. Dynamic quarter labelling (`quarter_label_for_month`) replaces the hardcoded MONTHLY_TARGETS dict from the legacy script. Two staging tables: `stg_nport_holdings` (mirror of `fund_holdings_v2` Group 1 + `manifest_id`/`parse_status`/`qc_flags`) and `stg_nport_fund_universe`. Atomic per-series loads — BEGIN → DELETE prior → INSERT → impact='loaded' → COMMIT → CHECKPOINT. Synthetic `series_id` fallback (`{cik}_{accession}`) with FLAG-level QC.
- `scripts/validate_nport.py` — stricter than `validate_13dg.py`. Entity gate is **HARD**: missing series_id in `entity_identifiers` → BLOCK (registered funds always have prior EDGAR history). Both rollup worldviews required (`economic_control_v1` + `decision_maker_v1`). Lifecycle checks: new_series, top10_drift (CUSIP overlap < 1/10 vs prior quarter), AUM delta (>80% BLOCK, 50–80% WARN). Markdown report at `logs/reports/nport_{run_id}.md`.
- `scripts/promote_nport.py` — Group 2 entity enrichment at promote time via `_enrich_entity()` against `entity_current` (entity_id + rollup_entity_id + dm_entity_id + dm_rollup_entity_id + dm_rollup_name). Atomic per-tuple `(series_id, report_month)`: DELETE+INSERT replaces amendments. UPSERT `fund_universe`. Stamp freshness for both tables. Refresh `13f_readonly.duckdb` snapshot.

**`scripts/pipeline/discover.py` `discover_nport()` rewrite:**
- Now actually queries EDGAR (was a `return []` stub). Two paths: `cik_filter=` for targeted/test discovery using `Company(cik).get_filings(form='NPORT-P')`, and full-universe via `get_filings(year=Y, quarter=Q, form='NPORT-P')` for each calendar quarter between prod floor and `today − 75 days`.
- Coerces `f.period_of_report` and `f.filing_date` to `datetime.date` (edgar lib returns mixed string/date).
- Anti-joins `ingestion_manifest` on `accession_number`.

**Validate scripts now open prod read-only.** Both `validate_nport.py` and `validate_13dg.py` opened prod write — fails when the dev app holds a lock. `entity_gate_check`'s `pending_entity_resolution` insert is wrapped in try/except (in `pipeline/shared.py`) so the gate still returns accurate block lists when read-only. Promote step writes pending rows for real (it requires the lock anyway).

**5-fund test run results:**
- `Fidelity Contrafund` (24238), `Vanguard Wellington` (105563), `T. Rowe Price Blue Chip` (902259), `Dodge & Cox Funds` (29440), `Growth Fund of America` (44201).
- 15 accessions discovered → 14 series → 10,503 holdings staged in **5.8s**.
- Validate: 0 BLOCK / 3 FLAG / 1 WARN. Entity gate resolved all 14 series_ids. Promote-ready: YES.
- Promote: 15 (series, month) tuples, **−3,006 / +10,503** rows. fund_universe: +3 new series (6,677 → 6,680). New `2025-11` data added for 5 series; existing `2025-09` data refreshed for 9 series. Snapshot refreshed (7.66 GB). Backup at `data/backups/13f_backup_20260414_053433` (1.6 GB).
- AAPL now appears in Growth Fund of America 2025-11 ($7.55B / 2.22% NAV); rollup_entity_id and dm_rollup_entity_id populated correctly via Group 2 enrichment.

**Prod control plane after Batch 2C:** 18 ingestion_manifest rows, 18 ingestion_impacts (all promote_status='promoted'), 3 pending_entity_resolution (all from Batch 2B, no new pending from N-PORT — all 14 series resolved cleanly).

**Operational note:** prod write lock contention. The dev `scripts/app.py` holds prod open read-only; promote needs an exclusive lock. Stop+start the app for any promote step. Future: orchestrator should signal the app to drop its connection cache (or move to a hosted serving mode like Gunicorn — MT-1).

**Verification:** smoke 8/8; AAPL `/api/v1/query1` 25 rows; pre-commit (ruff + pylint + bandit) green on all 5 new+modified files.

## Follow-up items (not lost between sessions)

1. **Live price in Register tab — Track B.** Add `/api/market_price?tickers=...` endpoint that hits yfinance on demand. No pipeline dependency. Lets Register show today's prices without the next quarterly market refresh.
2. **Full N-PORT refresh authorization.** v2 verified clean on 5 funds. The full ~6,000-series refresh needs explicit auth: `python3 scripts/fetch_nport_v2.py --staging` (no `--test`). Estimate ~6–8h overnight at sec.gov rate limit.
3. **`enrich_holdings.py` (Batch 3).** Group 3 enrichment for `holdings_v2` (`ticker`, `security_type_inferred`, `market_value_live`, `pct_of_float`) — the legacy `UPDATE holdings SET ...` block was removed in Batch 2A. Build a DirectWritePipeline that reads `securities` + `market_data` and writes Group 3 columns post-promote.
4. **Retire legacy fetch_nport.py.** After a second clean v2 run (amendment chain test), `mv scripts/fetch_nport.py scripts/retired/fetch_nport.py`. Same for `scripts/fetch_13dg.py` once its amendment-chain test passes.

## Batch 2B-13dg — 2026-04-13 session

## Batch 2B-13dg — 2026-04-14 session

First end-to-end SourcePipeline proof. Every subsequent SourcePipeline
(N-PORT, 13F, ADV, N-CEN) copies this pattern.

**New scripts (3):**
- `scripts/fetch_13dg_v2.py` — `Dg13DgPipeline` conforming to
  `SourcePipeline`. EDGAR efts full-text search per subject CIK
  (hardcoded overrides for the scoped universe to avoid known
  ticker-collision bugs in `securities` — OXY→PKG, EQT→RJF, NFLX→Vanguard).
  `discover → fetch → parse → load_to_staging` with manifest writes per
  accession and impact rows per (filer, subject, accession). Reuses the
  proven `_clean_text` + `_extract_fields` regex parser from
  `fetch_13dg.py` (legacy script stays intact — moves to retired/ once
  v2 is verified over multiple runs). `stg_13dg_filings` table DDL
  (staging).
- `scripts/validate_13dg.py` — BLOCK/FLAG/WARN gates + entity gate.
  Structural BLOCKs: dup accession, pct out of range, partial parse.
  Per-spec tweak: `entity_gate_check` blocks on "missing from
  entity_identifiers" become FLAGs (not BLOCKs) because 13D/G filers
  are often individuals or corporations not in the 13F-centric MDM;
  the gate still queues them in `pending_entity_resolution` for
  operator review. Markdown report at `logs/reports/13dg_{run_id}.md`.
- `scripts/promote_13dg.py` — DELETE+INSERT `beneficial_ownership_v2`,
  rebuild `beneficial_ownership_current` (24,753 → 24,756 rows),
  stamp freshness on both tables, refresh `13f_readonly.duckdb`
  snapshot, mirror manifest+impacts staging→prod, update impact
  `promote_status='promoted'`. Refuses to promote unless validation
  report marks the run "Promote-ready: YES" (only structural BLOCKs
  refuse). `--exclude ACC1,ACC2` flag for holding out flagged items.

**Scoped test run:**
- 4 subject tickers: AR, OXY, EQT, NFLX.
- 3 accessions returned by EDGAR efts (AR had no new filings since
  2024-11-12 prod floor): OXY 13D/A, EQT 13G/A, NFLX 13G/A.
- All 3 staged cleanly (QC passed at parse time).
- validate: 0 BLOCK / 3 FLAG (all missing-MDM filer notices) / 0 WARN.
  Entity gate queued 3 filer CIKs into `pending_entity_resolution`
  for operator review (0001423902 = Berkshire sub, 0000033213 = EQT
  self-filing, 0001065280 = Netflix self-filing).
- promote: -3 existing accessions, +3 re-parsed versions. Row counts
  unchanged (same 3 accessions existed in prod, now updated via
  v2 pipeline). Snapshot refreshed (4.9GB → 7.6GB).

**Control plane live in prod for 13D/G:**
- `ingestion_manifest`: 3 rows, all fetch_status=complete.
- `ingestion_impacts`: 3 rows, promote_status=promoted.
- `pending_entity_resolution`: 3 rows awaiting human review.
- `data_freshness`: both `beneficial_ownership_v2` + `beneficial_ownership_current` rows stamped at 2026-04-14 04:05.

**Backup taken before promote:**
`data/backups/13f_backup_20260414_040227` (1.6 GB).

**Verification:** app /api/v1/tickers = 6,511; OXY query1 = 25 rows;
smoke 8/8; pre-commit green on all 3 new scripts + the 2 modified
Batch 2B-market files.

**Next session:**
- Resolve the 3 `pending_entity_resolution` entries (add
  `entity_identifiers` staging rows → diff → promote; INF1 workflow).
- Retire `scripts/fetch_13dg.py` → `scripts/retired/fetch_13dg.py`
  after a second successful v2 run (amendment chain test).
- Promote framework pattern to N-PORT (Batch 2C — `fetch_nport_v2.py`).
  Parser reuse from existing fetch_nport.py; structural copy of
  fetch_13dg_v2.py's `SourcePipeline` implementation.

## Batch 2B-market — 2026-04-14

## Batch 2B-market — 2026-04-14

Hardened fetch_market.py before it's ever authorized for a full
43K-ticker refresh.

**discover_market() rewrite (`scripts/pipeline/discover.py`):**
- CUSIP-anchored universe filter: latest quarter of holdings_v2 +
  latest report_month of fund_holdings_v2; equity only
  (13F `put_call IS NULL`, N-PORT `asset_category IN ('EC','EP')`);
  min $1M position; `securities.ticker` present.
- New optional `con_write` arg separates reference reads (prod) from
  freshness-check reads (write DB) — required for staging-mode crash
  recovery.
- Result: 43,049 → 5,874 CUSIP-anchored active tickers, 5,628 stale.
  Est. fetch time 712 min → 94 min.

**fetch_market.py:**
- Added cross-validation (`_cross_validate_ticker`): fuzzy name match
  vs securities (token_sort_ratio < 60 → WARN); market_cap sanity;
  exchange in KNOWN_EXCHANGES set (incl. Yahoo short codes); price
  divergence from holdings_v2 implied price (>50% → WARN).
  All WARN-level, emitted to `logs/market_validation_{run_id}.csv`.
- Added `_stamp_batch_attempt()` — stamps fetch_date + metadata_date +
  sec_date on EVERY ticker in the batch regardless of outcome.
  Without this, Yahoo-unpriceable tickers (e.g. `1RG`) stay NULL in
  the metadata/SEC buckets and discover_market re-picks them every
  restart. Fixes restart-safety.
- `--test-size N` flag overrides the 10-ticker default of `--test`.
- `# CHECKPOINT GRANULARITY POLICY` block at top of file: one batch
  (100 tickers) per unit.

**Crash-recovery test:**
- Six --test --staging --test-size 30 runs.
- Before the all-3-bucket fix: run 2 and run 3 both re-picked '1RG'
  because only fetch_date was stamped.
- After the fix: run 5 stamped all three dates for its 30 tickers;
  run 6 started on 'ABNB' — '1RG' correctly skipped. Stale count
  dropped 5,562 → 5,532 (exactly 30 tickers de-duplicated).

**Verification:** app /api/v1/tickers OK (6,511); smoke 8/8;
pre-commit green.

**Full market refresh still pending authorization.** Not run this session.



## Batch 2A — 2026-04-13 session

fetch_market.py rewritten to implement the DirectWritePipeline protocol
from `scripts/pipeline/protocol.py`. First real proof of the v1.2
framework against a canonical table.

**Shipped:**
- `scripts/fetch_market.py` — full rewrite (~750 lines): MarketDataPipeline class implementing `source_type`/`discover()`/`fetch()`/`write_to_canonical()`/`validate_post_write()`/`stamp_freshness()`. Manifest write per batch, impact row per ticker, CHECKPOINT every 500 rows, per-domain rate_limit() on every Yahoo + SEC call. `--dry-run` shows discovery without writes; `--test` clips to 10 tickers and writes to staging.
- `scripts/pipeline/discover.py` — `discover_market()` NA-bool fix (pandas `pd.NA` raised TypeError on `if row.get("unfetchable"):`; now explicit `is True` check).
- Legacy `UPDATE holdings SET market_value_live/pct_of_float` path removed. Group 3 enrichment (holdings_v2 post-promote) is now `enrich_holdings.py`, Batch 2B.

**Test run results (staging):**
- 10-ticker batch: 1 manifest row (fetch_status=complete, 27.6 KB bytes), 10 impacts (8 loaded / 2 failed on exotic symbols), all promote_status=promoted, data_freshness row stamped (6,425 rows @ 2026-04-13 22:46:05).
- BLOCKS=0, 1 sentinel FLAG (4 rows with non-positive prices — exotic OTC tickers), 2 WARNS (coverage skipped in staging, 6,103 pre-existing stale price rows — expected, staging market_data last refreshed pre-Batch-2A).

**Dry-run results (prod):**
- Universe: 43,049 tickers (`holdings_v2 ∪ fund_holdings_v2`).
- Stale in prod market_data: 6,424 price / 382 metadata / 2,008 SEC.
- 428 batches × 100 tickers = 42,735 to fetch. Est. 12h at rate limits.
- No prod DB writes.

**PROCESS_RULES violations cleared:**
- §1 CHECKPOINT per 500 rows inside `upsert_yahoo` / `upsert_sec`.
- §2 restart-safe — discover_market anti-joins staleness thresholds.
- §3 source failover — per-ticker errors captured in manifest, not fatal.
- §4 rate_limit('query1.finance.yahoo.com') + rate_limit('data.sec.gov') before every HTTP call.
- §5 coverage gate (prod only) BLOCKs at <85%, WARNs at <95%; sentinel gates always run.
- §6 progress line every 100 tickers with rate + ETA.
- §9 --dry-run flag that writes nothing.

**Open for Batch 2B (next session):**
- Full market refresh authorized run (~12h at rate limits). Not run this session per prompt.
- `enrich_holdings.py` as Group 3 DirectWritePipeline for `holdings_v2` (ticker / security_type_inferred / market_value_live / pct_of_float) post-promote.



## Batch 1 — 2026-04-13 session

Schema cleanup + control-plane rollout to prod. No pipeline runs, no
data moves.

| Task | Outcome |
|---|---|
| T1 — drop `positions` | 18,682,708 rows dropped from prod; staging already clean. `scripts/unify_positions.py` → `scripts/retired/`. Backup at `data/backups/13f_backup_20260413_222950` (2.1 GB). |
| T2 — `build_summaries.py` DDL fix | `summary_by_parent` CREATE extended from 9 → 13 cols with `PK (quarter, rollup_entity_id)`; `summary_by_ticker` verified already aligned. INSERT rewrite still pending (REWRITE tracked in `docs/pipeline_inventory.md`). Script not run. |
| T3 — (skipped) | Premise check surfaced that prod already holds every `_v2` column; drift is owner-script-side, not prod-side. No migration 002 needed. `canonical_ddl.md` reclassified accordingly. |
| T4 — migration 001 on prod | `ingestion_manifest`, `ingestion_impacts`, `pending_entity_resolution` live in prod with 0 rows; `ingestion_manifest_current` VIEW created. |
| T5 — `canonical_ddl.md` reclass | 3 L3 verdicts BROKEN → OWNER_BEHIND (prod correct, owner scripts lag). 2 L4 verdicts BROKEN → ALIGNED after T2. Migration History table added. |
| T6 — `.gitignore` + closeout | Ignore `PHASE*_PROMPT.md` and `data/*.csv`. Docs + commit + push. |

**Verdict model now in canonical_ddl.md:** ALIGNED / OWNER_BEHIND.
`OWNER_BEHIND` = prod DDL is complete; owning script is the blocker
(rewrite in Batch 2). No schema migration on prod can resolve these
— only rewriting `load_13f.py`, `fetch_nport.py`, and `fetch_13dg.py`
to target `_v2` clears the verdict.



## Pipeline framework foundation — 2026-04-13 session

Twelve deliverables landed this session. The framework is code-ready
to start writing per-source `promote_*.py` SourcePipeline implementations.

| # | Deliverable | Path |
|---|-------------|------|
| 1 | Data-layer classification | `docs/data_layers.md` |
| 2 | L3 canonical DDL audit | `docs/canonical_ddl.md` |
| 3 | Pipeline inventory | `docs/pipeline_inventory.md` |
| 4 | Per-script PROCESS_RULES violations | `docs/pipeline_violations.md` |
| 5 | Control-plane DDL migration | `scripts/migrations/001_pipeline_control_plane.py` |
| 6 | Dataset registry | `scripts/pipeline/registry.py` (52 datasets, 0 unclassified) |
| 7 | Pipeline protocols | `scripts/pipeline/protocol.py` (Source / DirectWrite / Derived) |
| 8 | Shared utilities | `scripts/pipeline/shared.py` (sec_fetch / rate_limit / entity_gate_check) |
| 9 | Manifest helpers | `scripts/pipeline/manifest.py` |
| 10 | Per-source discovery | `scripts/pipeline/discover.py` (SCOPED_13DG_TEST_TICKERS = AR/OXY/EQT/NFLX) |
| 11 | Two live app bugs fixed | `api_market.py:201` + `build_benchmark_weights.py:16` |
| 12 | This doc + ROADMAP refresh | — |

**Status:** Staging migration runs clean (0 rows on fresh install).
Pre-commit green on all 7 new files. Smoke tests green (8/8). App
healthy at :8001 (6,511 tickers).

**Open decisions D5–D8** (recorded in `docs/data_layers.md` §6, need
real operational data to resolve):
- D5 — Entity retro-enrichment when merges change historical `rollup_entity_id`
- D6 — `market_value_live` refresh cadence for historical rows
- D7 — Snapshot table retention policy (144 snapshots in prod, ~negligible)
- D8 — L3 canonical DDL migration framework (first candidate: `summary_by_parent` drift)

**Critical finding surfaced by the audit:** **eleven** scripts still
touch Stage-5-dropped tables (8 writers + 3 read-only) — full list in
`docs/pipeline_inventory.md` cross-cutting finding #1. None will run
successfully against prod until rewrites land. The pipeline inventory
and violations docs are the acceptance criteria.

**Five BROKEN tables in `docs/canonical_ddl.md`** (promote scripts
blocked until each drift is resolved): **L3** — `holdings_v2`,
`fund_holdings_v2`, `beneficial_ownership_v2`. **L4** —
`summary_by_parent` (MISSING_COLUMNS + wrong PK), `summary_by_ticker`
(DDL aligned but source reads dead `holdings`).

**Next session** (build sequence Step 11 — Promote Pipelines):
1. `promote_13f.py` — SourcePipeline for 13F (solves `holdings_v2` BROKEN).
2. `promote_nport.py` — SourcePipeline for N-PORT (solves `fund_holdings_v2` BROKEN; unblocks pending N-PORT refresh on stale Oct-2025 data).
3. `enrich_holdings.py` — DirectWritePipeline Group-3 enrichment after promote (Option B).
4. Migration 002 — `build_summaries.py` DDL + source rewrite (`holdings` → `holdings_v2`, add rollup_entity_id + 3 other missing columns + correct PK).

Entity infrastructure through Phase 4+ Batch 4-C remains complete.
Framework rewrites do NOT require entity-layer changes — they consume
`entity_current` through `entity_gate_check()`.



Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main`
- **HEAD:** `1b0c9d6` (docs: session close — Stage 5 + BL-9 + BL-10 complete, N-PORT next). Preceded this session by `bdd436b` (docs: BL-9/BL-10 status + React migration finding) → `9ea3557` (fix: BL-10 multi-sheet exports) → `9572844` (fix: BL-9 short_long) → `5342920` (docs: Stage 5 backfill) → `305739e` (chore: Stage 5 — drop 3 legacy tables).
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - FastAPI + uvicorn — `scripts/app.py` (thin entry, ~115 lines) + 9 router modules (`app_db`, `api_common`, `api_config`, `api_register`, `api_fund`, `api_flows`, `api_entities`, `api_market`, `api_cross`) + `admin_bp.py` (`admin_router`, `/api/admin/*`, INF12 token auth via `Depends`). OpenAPI `/docs` + `/redoc` available. Flask retired 2026-04-13 (Batch 4-C).
  - Service layer — `scripts/queries.py` (~5,500 lines, SQL + query logic) + `scripts/serializers.py` (~210 lines, `clean_for_json` / `df_to_records` / filer-name resolution / subadviser notes) + `scripts/cache.py` (~40 lines, `cached()` + key templates).
  - DuckDB — `data/13f.duckdb` (prod), `data/13f_staging.duckdb` (staging)
  - Vanilla JS — **retired 2026-04-13** (commit `71269cb`). `web/static/{dist,vendor,style.css}` are orphaned — safe to delete in a follow-up PR.
  - Jinja templates — `web/templates/admin.html` only (index.html deleted)
  - **React full-app** — `web/react-app/` is the only frontend, served by Flask at :8001 from `web/react-app/dist/`. React dev server on :5174 still available for development.
  - **API contract** — public routes at `/api/v1/*` only (legacy `/api/*` mount removed). 6 endpoints wrap responses in the Phase 1-B2 envelope: `/api/v1/tickers`, `/api/v1/query1`, `/api/v1/portfolio_context`, `/api/v1/flow_analysis`, `/api/v1/ownership_trend_summary`, `/api/v1/entity_graph`.

---

## First 5 minutes — read these

1. **`~/ClaudeWorkspace/CLAUDE.md`** — workspace rules
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF18. COMPLETED section at line ~260+. ARCHITECTURE BACKLOG section tracks ARCH-1A through ARCH-4C + BL-1 through BL-6.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — React app migration plan
5. **`ARCHITECTURE_REVIEW.md`** — 6-phase stack upgrade plan (2026-04-12). Start here for architecture work.
6. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`

---

## Backend cleanup — 2026-04-12 session

Three related fixes landed on top of Phase 3. See ROADMAP row dated 2026-04-12 for full detail.

| Fix | Commit | Impact |
|---|---|---|
| Dropped `log_shadow_diff()` | `c2c5441` | Removed function + `_SHADOW_LOG_PATH` + 4 call sites. Phase 4 shadow logging no longer needed. |
| Threaded `quarter` param through query endpoints | `94b0402` | `api_query` + `api_export` read `quarter` from request args (default LATEST_QUARTER); 25 query functions gained `quarter=LQ` kwarg. All defaults preserve existing caller behavior. `get_nport_children_q2` intentionally left alone (FQ↔LQ delta helper). Smoke test: `EQT` Q1=69 rows vs Q4=89 rows — divergence confirms wiring. **New capability:** clients can now pass `?quarter=2025Q1` etc. to every `/api/query<N>` + `/api/export/query<N>` endpoint. |
| Vectorized `portfolio_context._compute_metrics` | `251072b` | 2.7s → 730ms HTTP warm. GICS sector mapping moved into SQL `CASE WHEN` columns on all 3 portfolio queries; iterrows/apply eliminated; groupby + idxmax replace the row loops. Remaining hotspot is `get_nport_children` N+1 loop (286ms) — next optimization target. |

---

## Entity infrastructure — COMPLETE

All entity data quality and infrastructure work from this session is done. The entity layer is in its cleanest state since launch.

### What shipped (2026-04-11 + 2026-04-12)

| Category | Items | Summary |
|---|---|---|
| **Admin auth** | INF12 | 15 admin routes gated with `ADMIN_TOKEN` + `hmac.compare_digest` |
| **Entity merges** | INF4, INF4d, INF4c, INF6, INF8, INF4f | 101 CRD-format fragmented pairs merged (Loomis $83B, Boston Partners $97B, 96 batch, Tortoise, Trian, NorthStar). ~$287B combined AUM consolidated. |
| **CRD normalization** | INF4b, INF17b | `_normalize_crd()` in entity resolver + fetch_ncen.py. LTRIM retroactive lookup. Prevents new fragmentation. |
| **Fuzzy-match gates** | INF17 Phase 3, INF17b | Brand-token overlap gate in `build_managers.py` + `fetch_ncen.py`. 21-word stopword list. Rejection logging. |
| **Managers cleanup** | INF17 Phase 1, INF7 | 127 CRD/AUM scrubs + 3 Soros/Peter Soros manual fixes + 2 Trian parent_name scrubs |
| **Misattribution fixes** | INF17 Phase 2 | 5 entities self-rooted ($1.27B corrected) |
| **Classification fixes** | L4-1, L4-2 | 6 reclassifications (3 passive→mixed, 3 mixed→active) |
| **Sub-adviser rollup** | 43i, INF18 | 4 Baird sub-advisers self-rooted for EC. 2 NorthStar orphan_scan edges closed. Financial Partners Group confirmed legitimate. |
| **Rollup preservation** | INF17 Phase 4 | 3 coincidentally-correct rollups preserved via merge overrides (Carillon→RJF, Nikko→Sumitomo, Nikko EU→JP). Carillon DM fixed to self-root. |
| **Override framework** | INF9e, INF9a/b/c/d | `entity_overrides_persistent` live in prod (47 rows). diff/promote coverage. 5 action types. entity_id fallback for ghost parents. |
| **Relationship suppression** | INF9c + follow-up | 6 bad parent_bridge edges suppressed. entity_id fallback for PARENT_SEEDS ghosts. |
| **Snapshot fallback** | INF13 | Verified: fail-fast already in place, no shutil.copy2 |
| **CRD audit** | INF4e | 4 borderline pairs confirmed as CRD pollutions, added to managers scrub |

### Production state

- **validate_entities.py --prod:** 9 PASS / 0 FAIL / 7 MANUAL
- **entity_overrides_persistent:** 47 rows (24 reclassify + 2 set_activist + 9 merge/DM + 6 suppress_relationship + 6 merge/Phase4)
- **managers.crd_number:** 127 polluted rows scrubbed to NULL
- **Entity fragmentation:** 101 pairs merged. 15 excluded as CRD pollutions (added to managers scrub).

---

## Open items — current priority order

### ⭐ Next session priorities

_All infrastructure through Phase 4+ Batch 4-C + openapi-typescript regen
is complete as of 2026-04-13. Stage 5 cleanup (3 legacy tables) closed
2026-04-13 — 4 INF9d eids preserved as live PARENT_SEEDS brand shells.
Phase 5 / 6 parked as medium-term (MT-1 through MT-6) in ROADMAP —
triggered on external user / team / productization milestones, not
calendar._

**1. N-PORT data refresh.** `fund_holdings_v2` is stale through Oct 2025.
Run manually when authorized:
```bash
! python3 -u scripts/fetch_nport.py --test  # test first
! python3 -u scripts/fetch_nport.py          # full run (authorized)
```
Pipeline operation — explicit user authorization required before full run.

**2. `scripts/schemas.py` expansion (ARCH-4C-followup step 1).**
Author Pydantic models covering the field-level shape of all ~55
response types currently in `src/types/api.ts` (Conviction, Cohort,
FundPortfolio, CrossOwnership, TwoCompany, Crowding, ShortAnalysis,
SectorFlows, PeerRotation, etc.). Today the only typed envelopes are
the 6 Phase 1-B2 endpoints + `RegisterRow`+`TickerRow` — everything
else is untyped, so `api-generated.ts` currently has 7 named schemas
(5 opaque) vs 55 in `api.ts`. Estimate 4-6 hours + per-endpoint drift
check against live responses. **Unblocks step 2** (regenerate
`api-generated.ts` + migrate React tabs + delete `api.ts`). Do not
attempt the React-side migration before step 1 lands — mechanical
migration today is a compile-time-safety regression.

**3. Data quality backlog.** DM13 / DM14 / DM15 (decision-maker
routing follow-ups queued during INF9b/c work), L4-1 / L4-2
classification re-audits (bank-holdco vs pure-asset-manager and
N-PORT cross-check originally shipped 2026-04-12 — revisit the
adjacent 1,037-entity `mixed` population for similar mis-classifications),
and the outstanding entity follow-ups in "Data-QC minor follow-ups"
below (Amundi rollup, Financial Partners fragmentation, INF9c
entity_id stability). Use INF1 staging workflow for any entity
mutations; no direct prod writes.

**4. Phase-independent backlog cleanup candidates.** BL-3
(write-path consistency implementation), BL-8 (re-enable suppressed
pre-commit rules). Small-PR friendly.

### Phase-independent backlog

- BL-3: write-path consistency implementation (follow-on to 2-A audit)
- BL-8: re-enable suppressed pre-commit rules (small rule-by-rule PRs)
- ARCH-4C-followup: two-step React type migration — schemas.py expansion, then regenerate+migrate (see ROADMAP)

### Trigger-based (parked — not in the next-session queue)

- **Phase 3+** — `portfolio_context_cache` precompute. Trigger: latency regression or natural pipeline cadence.
- **Phase 3++** — `build_analytics.py` (register_cache / conviction_cache / ownership_trend_cache / cross_ownership_cache). Trigger: on-demand query latency becomes user-visible.
- **MT-1 through MT-6** (Medium Term, ROADMAP) — Gunicorn+Nginx, JWT/Auth0, APScheduler/Airflow, cloud deployment, PostgreSQL, repo reshape. Triggers: external user, team cadence, productization.

### Data-QC minor follow-ups

- **Amundi → Amundi Taiwan rollup** — eid=830 + eid=4248 roll to eid=752 Amundi Taiwan via parent_bridge_sync/manual. Should roll to global Amundi SA parent. Separate manual fix.
- **Financial Partners Group fragmentation** — eid=1600 "Inc" vs eid=9722 "LLC" with circular orphan_scan. Minor structural cleanup.
- **INF9c suppress_relationship entity_id stability** — PARENT_SEEDS entity_ids are deterministic in practice but not contractually guaranteed. The 6 suppress rows use entity_id fallback which is best-effort across full --reset. Full fix would require adding CIK identifiers to PARENT_SEEDS brand ghosts.

---

## Critical gotchas — discovered the hard way

### a–e: Flask, IIFEs, switchTab, bandit 1.8.3, nosec B608

See full text in `87bc812` version.

### f. Data model traps

- **`entity_overrides_persistent`** — 47 rows in prod. 5 action types (reclassify, set_activist, alias_add, merge, suppress_relationship). 4 extension columns. Resolution via `(identifier_type, identifier_value)` with CRD normalization. suppress_relationship uses entity_id fallback for ghost parents.
- **`managers.aum_total` + `crd_number`** — 127 rows scrubbed to NULL. Use `SUM(holdings_v2.market_value_usd)` for AUM.
- **`_resolve_db_path()`** — fail-fast RuntimeError when DB locked. No shutil.copy2 (INF13 verified).
- **CRD normalization** — `entity_sync._normalize_crd()` strips leading zeros. LTRIM retroactive lookup.
- **13F-NT vs 13F-HR** — NT filers have zero `holdings_v2` rows.

### g–h: React/AG Grid/Tailwind landmines, inline style cascade

See `87bc812` version.

### i. Fuzzy name matching — brand-token Jaccard

Both `build_managers.py` and `fetch_ncen.py` have `_BRAND_STOPWORDS` + `_brand_tokens_overlap()`.

### j–r: DuckDB similarity gap, audit join bug, merge_staging DROP+CREATE, sync SKIP, manually_verified unreliable, 13F-NT AUM distortion, CRD normalization, CIK transfer rule, LOW_COV classification rule

See prior versions for full text.

### s. Sub-adviser vs subsidiary for EC rollup

When non-fund entity rolls under parent for EC via transitive_flatten/orphan_scan, verify if subsidiary (keep) or sub-adviser (self-root). 43i found 28 zero-overlap institution pairs; 24 legitimate, 4 Baird sub-advisers fixed.

### t. Conviction tab is served by two separate endpoints

`/api/query3` → `query3()` (Active holder market cap analysis) and `/api/portfolio_context` → `portfolio_context()` (holder sector concentration) are both labeled "Conviction" but are independent. Optimizing one does not speed up the other. `query3` remains slow (~1.4s) due to per-CIK percentile subqueries; `portfolio_context` is ~730ms after the 2026-04-12 vectorization.

### ff. `api-generated.ts` is sparser than `api.ts` — do not delete api.ts

`web/react-app/src/types/api-generated.ts` (openapi-typescript output
from `/openapi.json`) has 7 named schemas: `TickerRow`, `RegisterRow`,
`RegisterPayload`, `ConvictionPayload`, `FlowAnalysisPayload`,
`OwnershipTrendPayload`, `EntityGraphPayload`. 5 of those 7 are
`{[key: string]: unknown}` opaque because the backend Pydantic models
in `scripts/schemas.py` declare only the envelope + payload-container
shape without field-level types. `RegisterRow` generated has 1 field
typed (`institution`) vs 17 in `api.ts`. The other ~48 endpoints have
no OpenAPI schema at all — they return raw dict responses. Hand-written
`src/types/api.ts` (~55 interfaces, ~900 lines) is the authoritative
shape source today. **Do not delete api.ts** until step 1 of
ARCH-4C-followup (expand `scripts/schemas.py` to cover full response
shapes) has shipped and regeneration has parity. Mechanical tab
migration before that is a compile-time type regression.

### gg. `holdings_v2` true composite key — filing-line grain

`holdings_v2` is **not** unique on `(cik, ticker, quarter)`. The table is
at 13F filing-line grain. True composite key is:
`(cik, ticker, quarter, put_call, security_type, discretion)`.
Separate rows exist for put vs call options on the same underlying
(`put_call='Put'` and `put_call=NULL`, same `accession_number`) and
for non-discretionary vs discretionary positions. This is correct —
13F filers report option legs and discretion states as independent lines.

Any aggregation that wants a "total position" must
`SUM(shares), SUM(market_value_usd) GROUP BY (cik, ticker, quarter)`.
`queries.py` already does this via SUM on the hot paths (Register,
Conviction, Ownership Trend). The landmine is a future dev writing a
row-count-based join that assumes one row per filer/security/quarter —
that will silently double-count option legs.

### ee. INF9d eids (20194/20196/20201/20203) are live PARENT_SEEDS brand shells — Stage 5 discovery

Do not delete eid=20194 (Pacific Life Insurance Company), 20196 (Stowers
Institute for Medical Research), 20201 (Stonegate Global Financial), or
20203 (International Assets Advisory, LLC). The historical Apr-11/12
classification of these as "ghost entities with no aliases, no
identifiers, no holdings" was wrong on "no aliases" — each has 1 brand
alias, 2 self-root rollup_history rows (EC+DM), recent manual_l4
classification edits from 2026-04-10, and 1 outgoing
`wholly_owned` ADV_SCHEDULE_MANUAL relationship to a real child entity
(→1685 Pacific Life Fund Advisors, →8544 American Century, →9990
Catalyst Capital, →2196 International Assets Investment Mgmt). The v2
data plane (`holdings_v2`, `fund_holdings_v2`) correctly does not
reference them because EC/DM rollups resolved to the child entities, but
the ADV lineage is load-bearing for the relationship graph. Treat these
4 eids as untouchable.

### aa. `DATE '9999-12-31'` is the SCD open-row sentinel (not NULL) — Phase 0-B2 discovery

Across every entity SCD table — `entity_rollup_history`, `entity_aliases`,
`entity_identifiers`, `entity_classification_history`, `entity_relationships`
— "currently open" rows have `valid_to = DATE '9999-12-31'`. `valid_to IS
NULL` matches zero rows in prod. Any filter that tries to select the
current row must use the sentinel explicitly (see `scripts/build_fixture.py`
for the pattern). The `entity_current` view enforces this correctly;
derivative code should query the view instead of re-rolling the filter.

### bb. `entity_current` is a VIEW, not a table — Phase 0-B2 discovery

`entity_current` is the only user-defined view in the DB. Any fixture build
or snapshot that copies tables into a fresh DB must **recreate the view**
after tables land. The view definition is mirrored in
`scripts/build_fixture.py` and must stay in sync with prod — if prod
redefines the view (via a migration), update the build script in the
same PR.

### cc. `entity_identifiers.identifier_type` is lowercase — Phase 0-B2 discovery

Identifier type values are lowercase strings: `'cik'`, `'crd'`, `'series_id'`.
Filters using uppercase (`WHERE identifier_type = 'CIK'`) silently return
zero rows. Spot-checked during fixture build after the initial `managers`
filter returned 0. No `UPPER()` normalization in prod; everything assumes
lowercase.

### dd. `DB_PATH_OVERRIDE` env var lets test harnesses swap DBs — Phase 0-B2

`scripts/app.py:83` reads `DB_PATH_OVERRIDE` env var at module load and
substitutes it for the default `data/13f.duckdb`. Used by
`tests/smoke/conftest.py` to point Flask at the committed fixture DB.
Undefined in normal use. Do not couple further logic to this var — it is
a minimal override surface for test fixtures, not a general runtime
configuration mechanism.

### z. `record_freshness` + FreshnessBadge wiring (Batch 3-A follow-on)

- Pipeline scripts that rebuild a precomputed table should call `db.record_freshness(con, 'table_name')` at the end of their main() (after CHECKPOINT). Helper is no-op on a pre-Batch-3A DB that lacks `data_freshness`, so it's safe to leave in scripts that may run against old DBs.
- React `FreshnessBadge` from `common/FreshnessBadge.tsx` takes a `tableName` prop and renders a color-coded pill. It shares one fetch of `/api/v1/freshness` across the page via a module-level cache; call `resetFreshnessCache()` if the page needs to force-reload (e.g. after a post-promote hot-swap).
- SLA thresholds are **hour-based** in the component, with a 90-day quarter proxy for quarter+N thresholds from `ARCHITECTURE_REVIEW.md`. Revisit if the thresholds need to be anchored to actual quarter boundaries.
- Only FlowAnalysisTab currently uses the badge. To wire others: Register/Conviction → `summary_by_parent`; Ownership Trend / Peer Rotation / Sector Rotation → `investor_flows`; Fund Portfolio → `fund_holdings_v2`.

### y. `fund_family_patterns` + `data_freshness` (ARCH-3A)

- `get_nport_family_patterns()` in `scripts/queries.py` now reads from `fund_family_patterns` (DB) and falls back to `_FAMILY_PATTERNS_FALLBACK` (in-code dict, identical content). Memoized at module scope — restart the app to pick up a table edit. If you add a new pattern, add it to **both** the DB (via another migration or direct INSERT) **and** `_FAMILY_PATTERNS_FALLBACK` until the fallback is removed.
- **Schema reality-check (verified 2026-04-14):** `fund_family_patterns` has **2 columns** (`pattern VARCHAR`, `inst_parent_name VARCHAR`), 83 rows, PK `(inst_parent_name, pattern)`. Any planning doc that references a 3-col shape (`family_name` / `match_type`) is stale — ignore and edit against the 2-col reality.
- `data_freshness (table_name PK, last_computed_at, row_count)` is empty on arrival. Pipeline scripts should `INSERT OR REPLACE` a row at the end of each successful rebuild. `/api/freshness` + `/api/v1/freshness` already serve whatever's in the table.
- **Staging workflow caveat:** `sync_staging.py` / `diff_staging.py` / `promote_staging.py` are **entity-graph only**. For non-entity reference tables (new tables, schema changes, seed data), use `merge_staging.py --tables <name>` with an entry in `TABLE_KEYS`, or for brand-new tables with no prod data, a one-shot migration script applied first to staging then to prod. `fund_family_patterns: None` and `data_freshness: ["table_name"]` are already registered in `TABLE_KEYS`.

### x. `get_nport_children_batch()` replaces the loop (ARCH-2A.1)

- Hot-path callers in `query1` (Register) and `portfolio_context` (Conviction) now call `get_nport_children_batch(parent_names, ticker, quarter, con, limit=5)` once and dict-lookup per parent. Do NOT reintroduce a per-parent loop — the win is 14× (297ms → 21ms for 25 parents).
- `get_nport_children()` (singular) is kept for the currently-unused `get_children()` fallback path. If you delete `get_children()`, delete the singular too.
- `get_nport_children_q2` is INTENTIONALLY not batched — it is a FQ↔LQ delta helper (gotcha u). If someone asks to batch it, that is a separate, distinct task.
- `summary_by_parent` is a read-only table on every request path. Any new code reading from it is fine; anything that would compute it on demand must instead go into `build_summaries.py` (T4 pipeline).

### w. `_RT_AWARE_QUERIES` + endpoint classification block (ARCH-1B1)

- `_RT_AWARE_QUERIES = frozenset({1, 2, 3, 5, 12, 14})` at module scope in `app.py` is the single source of truth for which `query<N>` endpoints accept `rollup_type`. Both `api_query` and `api_export` dispatch on it. If you change a `query<N>` signature to add or remove `rollup_type`, update this set AND the classification comment block above the Flask routes section.
- `api_export` extracts tabular data from structured responses: q7 → `positions`, q1/q16 → `rows`, anything else → passed whole to `build_excel`. q6/q10/q11/q15 still 500 because their shapes are multi-table and the extractor doesn't know them (BL-10).
- Endpoint classification block at the top of the routes section is the freeze artifact consumed by Batch 4-A — do not add a route without adding a row there.

### v. `/api/*` dual-mount + `before_request` ordering (ARCH-1A)

- All public `/api/*` routes are aliased under `/api/v1/*` by `_register_v1_aliases()` in `app.py` (near the bottom of the file). `/api/admin/*` is excluded because it's gated by `admin_bp`'s own `before_request` for token auth.
- The app-level `_validate_query_params()` `before_request` fires on both `/api/*` and `/api/v1/*`. For `/api/admin/*` paths it returns `None` so admin_bp's own token validator gets to run.
- `/api/config/quarters` (new canonical) and `/api/admin/quarter_config` (legacy, kept for vanilla-JS until 2026-04-20 retirement) both call `_quarter_config_payload()`. Do not consolidate yet — remove legacy in a separate PR after retirement.
- Ticker regex in app.py is `^[A-Z]{1,6}(\.[A-Z])?$` (corrected from the spec's literal `^[A-Z]{1,6}[.A-Z]?$` which did not accept BRK.B despite the spec comment saying it should).

### u. `get_nport_children_q2` is a FQ↔LQ delta helper — do not add a `quarter` param

The 2026-04-12 quarter-param refactor threaded `quarter=LQ` through every query function that hardcoded LQ — except `get_nport_children_q2`. It compares `{FQ}` vs `{LQ}` inside a single SELECT (columns `q1_shares`, `q4_shares`) and is semantically pinned to the first-vs-latest quarter pair. Leave it as-is unless you also generalize the delta semantic.

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: efab352 or newer
pgrep -f "scripts/app.py"       # dev server PID
curl -s http://localhost:8001/api/tickers | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"  # 6500+
python3 scripts/validate_entities.py --prod   # 9 PASS / 0 FAIL / 7 MANUAL
python3 -c "import duckdb; print(duckdb.connect('data/13f.duckdb',read_only=True).execute('SELECT COUNT(*) FROM entity_overrides_persistent').fetchone()[0], 'overrides in prod')"  # 47
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization.
- Never mutate production data to simulate test conditions.
- Always update `ROADMAP.md` after completing a task.
- Entity changes: `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- Reference-table changes: `merge_staging.py --tables <name>`.
- Entity overrides: 47 rows in prod. 5 action types. suppress_relationship uses entity_id fallback.
- Read files in full before editing.
- Confirm destructive actions before running.
- Use `python3 -u` for background tasks.
- Never trust `managers.manually_verified=True`.
- Never use `fuzz.token_sort_ratio` alone for firm name matching.
- CRD values must be normalized via `_normalize_crd()`.
- Batch entity merges: always transfer CIK identifiers before closing.
- N-PORT coverage < 50%: keep classification as `mixed`.
- Sub-adviser vs subsidiary: verify before EC rollup.

---

## User collaboration preferences

- Terse, direct communication. Lead with the answer.
- Quick fixes preferred over comprehensive refactors unless explicitly asked.
- User tests in Safari, sometimes Chrome.
- Suggest `! <cmd>` for commands the user should run themselves.
- Flag duplicate ROADMAP items before adding.
- Don't delete files/data/rows without explicit confirmation.
- Report scope precisely: "entities affected" ≠ "holdings at risk" ≠ "dollars at risk".

---

## Session ledger (newest first — key data QC commits only)

```
1b0c9d6 docs: session close
bdd436b docs: ARCH-4C-followup reframe + React migration finding
9ea3557 fix: BL-10 — 4 broken Excel exports (q6/q10/q11/q15)
9572844 fix: BL-9 — short_long KeyError + fund_holdings_v2 ref
5342920 docs: Stage 5 cleanup backfill
305739e chore: Stage 5 — drop holdings/fund_holdings/beneficial_ownership
746a798 feat: Phase 4 Batch 4-A — Blueprint split of scripts/app.py
6572a46 feat: Phase 1-B2 rollout — envelope + schemas on 6 priority endpoints
9c27b7e feat: Phase 1-B2 infra — envelope types + Pydantic schemas + ErrorBoundary
3526757 test: refresh Playwright baselines post-FreshnessBadge + URL rewrite
71269cb feat: retire vanilla-JS frontend — legacy /api/* mount removed
8cf0d82 feat: Phase 0-B2 — smoke CI fixture + response snapshot tests
83836ee feat: FreshnessBadge rollout — wire into all 11 tabs
2892009 feat: data_freshness pipeline write hooks + FreshnessBadge component
7f62b7d docs: Phase 0-B1 — CI fixture DB design decision
731f4a0 feat: Batch 3-A — fund_family_patterns + data_freshness tables
700bcdb feat: Batch 2-A — N+1 batching + summary_by_parent audit + write-path risk map
d3a2fcb feat: Batch 1-B1 — endpoint classification + export parity
a8dd77a feat: Batch 1-A — /api/v1/ dual-mount, quarter_config rename, input guards
e201885 ci: Phase 0-A — lint/bandit CI (ruff + pylint + bandit on every push)
799dbde docs: ROADMAP + NEXT_SESSION_CONTEXT — Phase 4 cutover complete
2bac928 docs: REACT_MIGRATION + NEXT_SESSION_CONTEXT — Phase 4 cutover docs
002fab0 feat: React Phase 4 cutover — Flask serves web/react-app/dist/
a555a91 test: set playwright expect.timeout 10s in config
dc27d25 test: capture Playwright visual regression baselines (11 tabs, AAPL)
442084f docs: ARCHITECTURE_REVIEW.md — sequencing and gate fixes (3 changes)
6291c6b docs: ARCHITECTURE_REVIEW.md — final revision pass (6 changes)
2c99d34 ARCH: add ARCHITECTURE_REVIEW.md + sync ROADMAP + NEXT_SESSION_CONTEXT. 6-phase upgrade plan. Recommended next task: Batch 1-A routing hygiene (~1hr, app.py only).
573b504 docs: REACT_MIGRATION.md — Phase 2+3 complete, Phase 4 pending
b8d95af docs: ROADMAP entry for 2026-04-12 backend cleanup trio
251072b Vectorize portfolio_context._compute_metrics (2.7s → 730ms)
94b0402 Add quarter param to query endpoints + 25 query functions
c2c5441 Remove log_shadow_diff() and all 4 call sites
8403cf8 docs: backfill Phase 3 commit hash in ROADMAP + NEXT_SESSION_CONTEXT
c836813 Phase 3 visual polish: badge consolidation + cross-nav + print CSS + Playwright
11d7cce INF9c follow-up: entity_id fallback + backfill 6 rows
976733a ROADMAP: close INF9d as won't fix + Stage 5 cleanup
e0ffd4d INF4f: NorthStar CRD merge (eid=6693→7693)
67f3f51 INF17 Phase 4: preserve 3 rollups + Carillon DM + close 3 CRDs
f6076a3 43i/INF18: NorthStar orphan_scan fix + Financial Partners confirmed
b543030 INF9c: suppress 6 bad parent_bridge relationships
8f8d9f2 INF9b: 9 Securian DM12 override rows
a0d6685 INF9a/b/c/d: schema + replay extensions
47bb627 INF9e: diff/promote + 24 overrides promoted
4ff0006 INF17b: brand-token gate in fetch_ncen.py
46877c5 INF17 Phase 1: scrub 127 managers rows
1e01b6b L4-1: 3 mixed→active
73f6acd INF4c: batch merge 96 CRD-format fragmented pairs
eddb05c INF4d: Boston Partners merge ($96.58B)
d89e663 INF4b + INF17b: CRD normalization
ffa9796 INF8: Trian merge
eaab03b INF6: Tortoise Capital merge
a3c20e8 L4-2: 3 classification fixes
ff49dbc INF4: Loomis Sayles merge
0634682 INF17 Phase 3: build_managers.py fuzzy-match fix
6743f11 INF17 Phase 2: self-root 5 entities
1a43376 INF7: Soros/VSS cleanup
d51db60 INF12: admin Blueprint
b53e3fa INF9 Route A: 24 overrides to staging
```

## Session Close — April 14 2026

### Ready to implement
- CUSIP Classification Plan v1.4 — implementation prompt at:
  /mnt/user-data/outputs/cusip_implementation_prompt_session1.md
- fetch_nport_v2.py batch flags committed (--limit N / --all)
- N-PORT architecture review prompt ready at:
  /mnt/user-data/outputs/nport_architecture_review_prompt.md

### Key confirmed facts
- OpenFIGI: 25 req/min unauthenticated, 10 jobs/batch, ~40 min for 10K CUSIPs
- No pyopenfigi — plain requests.post confirmed sufficient
- _cache_openfigi does NOT exist in prod — CREATE fresh 7 cols
- securities.market_sector exists column 5 — do NOT re-add
- fund_holdings_v2 has 832,597 N/A sentinel rows — filter LENGTH=9
- build_cusip.py filename unchanged — 6 external references valid
- N-PORT full refresh unblocked and pending

### Next session
- Open fresh Claude Code session
- Paste /mnt/user-data/outputs/cusip_implementation_prompt_session1.md
- N-PORT review runs in parallel — paste nport_architecture_review_prompt.md
  into a second session while CUSIP Session 1 runs
