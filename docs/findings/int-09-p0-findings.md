# int-09-p0 Phase 0 Findings — INF25 BLOCK-DENORM-RETIREMENT sequencing

**Item:** int-09 — should Step 4 of the Class B denormalized-column retirement sequence (drop `ticker`, `entity_id`, `rollup_entity_id` from `holdings_v2` / `fund_holdings_v2`) execute now, or defer to Phase 2?
**Scope:** Phase 0. Read-only evidence gathering + decision. No code or schema changes.
**Recommendation:** **DEFER STEP 4 TO PHASE 2.** Steps 1–3 of the sequence are complete, drift is bounded by forward hooks + backfills, but the read-site footprint in `scripts/queries.py` is too large to rewrite as a remediation-window task. Phase 1 scope is doc-only: formalize the deferral and exit criteria.

---

## 1. Retirement sequence — step-by-step status

Source: [docs/data_layers.md §7](../data_layers.md) (lines 561–579), cross-referenced against [ROADMAP.md](../../ROADMAP.md) line 569 (INF25 row) and the 2026-04-19 session header (line 5).

| Step | Name | Status | Evidence |
|---|---|---|---|
| 1 | BLOCK-TICKER-BACKFILL | **SHIPPED** `3299a9f` | Full one-time backfill of `fund_holdings_v2.ticker` (3.94M → 5.15M rows) + forward-looking subprocess hooks at end of `build_cusip.py` and `normalize_securities.py`. int-06 closed as NO-OP. |
| 2 | BLOCK-3 | **SHIPPED** `0dc0d5d` | Legacy `fetch_nport.py` retired; `build_benchmark_weights` + `build_fund_classes` repointed to `fund_holdings_v2`. Removes readers that would have been broken by a Class B retirement. |
| 3 | Batch 3 REWRITE queue | **CLOSED** | All five target scripts shipped per 2026-04-19 session header: `build_shares_history` (`d7ba1c2`), `build_summaries` (`3234c8a`, already at `87ee955`), `compute_flows` (`34710d1`, already at `87ee955`), `load_13f` Rewrite4 (`7e68cf9`, prod `a58c107`), `build_managers` Rewrite5 (`223b4d9`, prod `7747af2`). All five clear their `pipeline_violations.md` entries. |
| 4 | BLOCK-DENORM-RETIREMENT | **PENDING → DEFER** | Actual column drops on `holdings_v2` / `fund_holdings_v2`. This is the int-09 decision. |

Drift is stabilized. Forward hooks (int-06) auto-trigger ticker re-stamp on every `securities` write. CUSIP v1.4 live. Benchmark weights validated post-BLOCK-3. No active drift incidents since the backfills merged.

---

## 2. Read-site inventory — Class B columns on `holdings_v2` / `fund_holdings_v2`

Counts below are raw `grep -cE "\b<col>\b"` against full files — they over-count slightly (local-variable reuse, docstrings, comments) but floor the conversion work.

### 2.1 `scripts/queries.py` — hot path, core query layer

| Column | Total references |
|---|---|
| `ticker` | **405** |
| `entity_id` | **69** |
| `rollup_entity_id` | **6** |
| `dm_rollup_entity_id` | 0 |

Of the 405 `ticker` refs: **92 WHERE clauses, 36 SELECT projections, 21 GROUP BY clauses**, balance is JOIN / CTE-shadowing / alias reuse. Many are direct `FROM holdings_v2 WHERE ticker = ?` — hot-path single-ticker lookups with no current `securities` join. Sample sites: [scripts/queries.py:2667](scripts/queries.py:2667), [scripts/queries.py:2912](scripts/queries.py:2912), [scripts/queries.py:3152](scripts/queries.py:3152), [scripts/queries.py:3273](scripts/queries.py:3273), [scripts/queries.py:3879](scripts/queries.py:3879), [scripts/queries.py:4126](scripts/queries.py:4126).

### 2.2 `scripts/app.py`

| Column | References |
|---|---|
| `ticker` / `entity_id` / `rollup_entity_id` | **0** |

Correction to plan prompt: the prompt says "Many app.py query endpoints use the denormalized columns directly." In fact **all denorm reads are routed through `queries.py`**. `app.py` is a thin Flask dispatcher. This does not change the decision — the 405 sites still exist — but the work concentrates in one file.

### 2.3 Other scripts

- 41 scripts touch `holdings_v2` / `fund_holdings_v2`.
- Producers (writers) that stamp Class B columns — must either be retired or repointed to join-at-read: `promote_nport.py` (entity_id), `enrich_holdings.py` Pass A/B/C (ticker), `enrich_fund_holdings_v2.py` (entity_id), `build_managers.py` / `backfill_manager_types.py` (enrichment cols; Class A-adjacent, not in INF25 scope), `build_fund_classes.py` (LEI).
- `scripts/pipeline/discover.py`, `scripts/fetch_market.py`, `scripts/admin_bp.py`, `scripts/build_fixture.py` all read `holdings_v2.ticker` / `fund_holdings_v2.ticker` directly.

### 2.4 React / TypeScript layer

Not inventoried here — reads through API endpoints served by `app.py` → `queries.py`. Any API-response-shape change would ripple through the React layer (recall INF41 / mig-07 "read-site inventory discipline" is the open tool item for this).

---

## 3. Decision — DEFER STEP 4 TO PHASE 2

**Evidence.**

1. **Read-site footprint is large.** 405 `ticker` + 69 `entity_id` + 6 `rollup_entity_id` references in `queries.py` alone. Each `WHERE ticker = ?` becomes a `JOIN securities s ON s.cusip = h.cusip WHERE s.ticker = ?` (or an inlined subquery). Every `GROUP BY ticker` needs the join lifted into the grouping key. Converting ~500 call-sites in a hot-path query file is substantial and risk-heavy work — it is a dedicated project, not a remediation ticket.

2. **`rollup_entity_id` is more than a ticker-style lookup.** The column encodes a dual-graph resolution (`economic_control_v1` vs `decision_maker_v1`). Converting it to a read-time join means every reader chooses a graph explicitly at query time. That's a semantic decision to thread through `queries.py` + the API layer, not a mechanical rewrite.

3. **mig-12 (`load_13f_v2`) is Phase 3 scope.** `load_13f.py` itself does not currently stamp Class B columns (verified — no `ticker`/`entity_id`/`rollup_entity_id` writes in the file), but the broader fetch/promote rewrite into `promote_13f.py` is still outstanding per [REMEDIATION_PLAN mig-12](../REMEDIATION_PLAN.md#mig-12). Retiring columns before the writer side is rewritten invites an ordering trap: a writer that still emits stamps into columns that no longer exist will fail hard on the next ingest. Sequencing Step 4 behind mig-12 keeps writer + reader contract aligned.

4. **The urgency case is gone.** int-06 forward hooks restamp `fund_holdings_v2.ticker` on every `securities` update; int-01/04 shipped RC1/RC4; int-07 benchmark gates all PASS. The original BLOCK-TICKER-BACKFILL / BLOCK-2 drift incidents (59% → 3.7%; 40% → 84%) were the forcing function for INF25. That function is now satisfied without the column drops. The remaining structural argument ("joins are the right shape") does not need to land inside the current remediation program.

5. **Correction to plan prompt.** The prompt states "mig-14 closed" — per REMEDIATION_PLAN line 133, mig-14 is **OPEN** (INF1 staging routing + `--dry-run` + data_freshness decisions pending). mig-14 scope is build_managers routing/atomicity, **not** denorm retirement, so this does not change the int-09 decision; flagging for accuracy.

**Counter-evidence reviewed and rejected.**

- *"Forward hooks plus backfill campaigns are a recurring maintenance cost."* True but bounded. Each backfill costs minutes, not hours. Not worth a 500-site rewrite under remediation time pressure.
- *"The drift surface grows with every entity merge / `securities` reclassification."* Also true. But forward hooks linearize that growth (restamp happens automatically). Without the hooks, cost is super-linear. With them, cost is bounded at the population rate of new `holdings_v2` / `fund_holdings_v2` rows.

---

## 4. Exit criteria — when Step 4 can execute

Step 4 (BLOCK-DENORM-RETIREMENT) may execute when **all** of the following are true:

1. **mig-12 complete.** `load_13f_v2` / `promote_13f.py` rewrite shipped and stable; all 13F writers go through the new promote path. Ensures no writer emits stamps into columns slated for drop.
2. **Read-site audit tool exists.** mig-07 (INF41 read-site inventory discipline) ships — a scripted audit that enumerates every read site of a target column across `queries.py`, `api_*.py`, `web/react-app/src/**/*.tsx`, and fixture responses. Provides the exhaustiveness proof Step 4 needs.
3. **Read-time join helpers proven.** At least one representative `queries.py` endpoint has been converted to the join pattern (Class A CUSIP join → `securities.ticker` / `entity_current.entity_id`) with parity tests against the legacy stamped read. Establishes the repeatable conversion pattern before the 500-site sweep.
4. **Dual-graph resolution strategy chosen.** Decision document for `rollup_entity_id` — either (a) replace with an explicit graph selector in the API layer, (b) retain as a materialized column populated by a view over `entity_current`, or (c) a hybrid. INF25 cannot drop the column without picking (a) or (b).
5. **Drift gate stable for ≥2 consecutive quarters.** Observable metric that forward hooks are holding `ticker` / `entity_id` coverage steady without manual backfills. Confirms the stabilization layer is load-bearing.
6. **INF41 rename-sweep discipline applied.** Any column removal goes through the same exhaustiveness tooling slated for renames; no ad-hoc grep-and-delete.

---

## 5. Phase 1 scope — doc-only

int-09 Phase 1 writes, no code:

| File | Change |
|---|---|
| [docs/data_layers.md §7](../data_layers.md) | Add a sub-clause under "Planned retirement sequence" formalizing Step 4's deferral to Phase 2. Include exit criteria list from §4 above. Update Step 3 status from "Batch 3 REWRITE" to "**SHIPPED**" with commit references. |
| [ENTITY_ARCHITECTURE.md](../../ENTITY_ARCHITECTURE.md) *Known Limitations* #6 and *Design Decision Log* 2026-04-18 entry | Append a 2026-04-22 addendum stating Step 4 deferral + Phase 2 trigger (mig-12 + mig-07). |
| [ROADMAP.md](../../ROADMAP.md) INF25 row (line 569) | Status text "Sequenced" → "Sequenced — Steps 1–3 shipped; Step 4 deferred to Phase 2 per int-09 Phase 0 decision (2026-04-22). Exit criteria in `docs/findings/int-09-p0-findings.md` §4." |
| [docs/REMEDIATION_CHECKLIST.md](../REMEDIATION_CHECKLIST.md) line 27 | Flip int-09 checkbox after Phase 1 docs land. |

No schema changes. No DDL. No code touches `queries.py`, `app.py`, or any writer. The Class B columns stay on both fact tables.

---

## 6. Summary

int-09 asks a sequencing question; the evidence answers **defer**. Steps 1–3 are complete, drift is bounded by the forward hooks, and Step 4's footprint (~500 read sites in `queries.py` + the `rollup_entity_id` dual-graph decision) is larger than a remediation-window task. Phase 1 formalizes the deferral in `data_layers.md §7`, `ENTITY_ARCHITECTURE.md`, and the ROADMAP INF25 row; Phase 2 reopens the decision once mig-12 + mig-07 exit criteria are met.
