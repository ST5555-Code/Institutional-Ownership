# ARCHITECTURE_REVIEW.md — revision pass

## Context

`ARCHITECTURE_REVIEW.md` (435 lines, committed `2c99d34`) laid out a 6-phase,
9-batch upgrade plan. A critical review surfaced 6 substantive issues plus 4
missing items. After review-of-review, user accepted 6 critiques as concrete
changes, 2 with modifications, and rejected 2 with justification. This plan
applies the accepted changes in a single edit pass.

Purpose: close real gaps in the plan (backward-compat, async/sync boundary,
CI priority, performance/freshness measurability) without scope creep into
testing/observability planning (deferred to separate doc).

No source code, DB, or pipeline scripts touched. Documentation-only change
to one file.

## Critical file

- `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/ARCHITECTURE_REVIEW.md` — only file modified

## Changes — 6 concrete (C1–C6, with C3b as a tightly-paired addition)

### C1. Dual-mount strategy for `/api/v1/` (Batch 1-A, §Phase 1)

**Where:** Batch 1-A "API versioning" row + new "Backward compatibility" row.

**What:** Replace "Add `/api/v1/` prefix to all public routes via Blueprint
`url_prefix`. One registration change." with:

> Dual-mount: register public routes under BOTH `/api/*` (existing) and
> `/api/v1/*` (new) during the React Phase 4 cutover window. Old frontend at
> :8001 continues to call `/api/*`; React migrates to `/api/v1/*` first.
> Deprecation: remove `/api/*` mount only after vanilla-JS frontend retired
> (React Phase 4 confirmed stable ≥1 week). Tracked as a Phase 5 prerequisite.

Update "Not doing here" line: confirm vanilla-JS frontend retirement is
separate (React Phase 4 cutover task).

### C2. FastAPI sync-route requirement + revised estimate (Batch 4-C)

**Where:** Batch 4-C header + table + "Done means" block.

**What:**
1. Change header estimate from "~half day" to "~2–3 days".
2. Add a new "Thread-local preservation" row to the table:

   > Thread-local DB connections — FastAPI routes declared as `def`, NOT
   > `async def`. Sync routes run in FastAPI's threadpool, preserving
   > `_threading.local()` semantics and the `get_db()` cache. Any future
   > async route must explicitly opt out of the cache or use an async DuckDB
   > adapter (not currently used).

3. Add to "Done means": "All routes are `def`, not `async def`. Thread-local
   `get_db()` cache hit rate unchanged from Flask baseline."

4. Add a "Known risks" footnote: `before_request` token guard in
   `admin_bp.py` requires FastAPI `Depends()` conversion — estimate includes
   this. `jsonify` → Pydantic return type required for every endpoint.

### C3. Ticker regex widened to accept share-class notation (Batch 1-A)

**Where:** Batch 1-A "Input guards" row.

**What:** Change `^[A-Z]{1,5}$` to `^[A-Z]{1,6}[.A-Z]?$` to accept
`BRK.B`, `BF.B`, and ADRs. Append to same cell: "DB-universe validation
(lookup against `tickers` table) is a follow-on — tracked as BL-7 below.
Deferred from 1-A to avoid coupling route layer to a DB query."

### C3b. Add BL-7 — DB-universe ticker validation (follow-on to C3)

**Where:** §Backlog table, new row after BL-6.

**What:**

> | BL-7 | DB-universe ticker validation | Route-layer check against the
> `tickers` table (or cached set). Catches typos the regex passes.
> Follow-on to Batch 1-A regex guard (ARCH-1A). Keep route layer
> decoupled from DB by loading the ticker set at app startup or
> caching with short TTL. |

### C4. Promote BL-1 (CI) to pre-Phase-1 prerequisite

**Where:** New "Phase 0 — Prerequisite" section before Phase 1. Remove from
Backlog table.

**What:** New section immediately after §4 "Execution Logic":

> ## Phase 0 — Prerequisite (BL-1 promoted)
>
> ### Batch 0-A — GitHub Actions CI
> _~2 hours · new `.github/workflows/*.yml` · low risk_
>
> Pre-commit (pylint + bandit + ruff) on push. Smoke test against 5
> critical endpoints (`/api/tickers`, `/api/query1`, `/api/entity_graph`,
> `/api/summary`, `/api/admin/stats`) using a headless fixture DB.
>
> **Done means:** CI runs on every push. A B608-class bug (mis-placed
> nosec injecting `#` into SQL) fails CI, not production.
>
> **Gate:** Phase 1 does not start until CI is green on main.

Update §Backlog table: remove BL-1, renumber BL-2..BL-6 or leave numbers
sparse (note that BL-1 moved to Phase 0).

### C5. Performance budgets per-batch

**Where:** Batch 2-A and general exit gates.

**What:**
1. Batch 2-A "Done means" — add: "`get_nport_children` batched call
   completes ≤50ms for a 25-fund portfolio (down from 286ms measured
   2026-04-12)."
2. Add a new "Endpoint performance budgets" row in §2 "What Is Solid"
   (reframed as "What to preserve"):

   > | Endpoint class | p95 budget (warm, local) |
   > |---|---|
   > | Tabular data (`/register`, `/conviction`, `/flow_analysis`) | ≤800ms |
   > | Drilldown (`/fund_portfolio_managers`, `/query7`) | ≤500ms |
   > | Small lookups (`/summary`, `/tickers`, `/config/quarters`) | ≤150ms |
   > | Precomputed artifacts (`/portfolio_context`, future) | ≤50ms |
   >
   > Budgets are guidance, not SLOs. Regressions vs. these budgets require
   > commit-message justification.

### C6. Data-freshness SLA (Batch 3-A.2)

**Where:** Batch 3-A "data_freshness table" row.

**What:** Append to the row:

> **Staleness SLA per table:**
>
> | Table | Fresh | Stale | Alert |
> |---|---|---|---|
> | `investor_flows` | ≤24h | >24h | footer amber |
> | `ticker_flow_stats` | ≤24h | >24h | footer amber |
> | `summary_by_parent` | ≤quarter+7d | >quarter+30d | footer red |
> | `beneficial_ownership_current` | ≤48h | >7d | footer amber |
> | `fund_holdings_v2` | ≤quarter+60d | >quarter+120d | footer red |
>
> Thresholds are pragmatic (reflect pipeline cadence), not regulatory.
> Stale ≠ wrong — surfaces "data older than expected" for the operator.

## Changes — 3 annotations

### A1. 1-A/1-B guards noted as temporary (§Phase 1 intro + Batches 1-A/1-B)

**Where:** After §Phase 1 header, add a one-line note. Also add inline
annotations to 1-A "Input guards" row and 1-B "Pydantic schemas" row.

**What:**
1. Phase 1 intro note:
   > _Note: Batch 1-A input guards and Batch 1-B hand-written Pydantic
   > schemas are transitional. FastAPI (Batch 4-C) auto-validates via
   > Pydantic and auto-generates schemas from response models — these
   > hand-written artifacts are scaffolding, not permanent code._

2. Batch 1-A "Input guards" row, append: "_Transitional — replaced by
   FastAPI Pydantic validation in Batch 4-C._"

3. Batch 1-B "Pydantic schemas" row, append: "_Transitional — regenerated
   from FastAPI response models via openapi-typescript in Batch 4-C._"

### A2. queries.py per-domain split as deferred Phase 6 follow-on

**Where:** Batch 4-B "Done means" block + §Phase 6.

**What:**
1. Batch 4-B "Done means" — add a final paragraph:
   > _Note: queries.py remains large after this split (SQL-only, ~3,500
   > lines estimated). Per-domain split — `queries_register.py`,
   > `queries_flows.py`, `queries_entities.py`, `queries_market.py` — is
   > explicitly deferred to Phase 6 as a follow-on. Do not attempt in 4-B._

2. Phase 6 "Likely shape if needed" code block — add `queries/{register,
   flows, entities, market}.py` as sub-items of `queries/` to make the
   follow-on concrete.

### A3. Estimates exclude smoke-testing — top-of-doc note

**Where:** After §4 "Execution Logic", before Phase 1.

**What:** Insert a one-paragraph note:

> _Estimates below are authoring time for the batch. Smoke-testing,
> deployment, and React type regeneration are separate steps — budget
> an additional 30–60 min per batch for these. Exit gates assume
> smoke-testing has run._

## Residuals handled (from review-of-review)

### R1. G1 wording — explicit change

**Where:** §3 Stack layer gaps, G1 header line (exact string replace).

**What:** Replace the header line verbatim:

- Old: `**G1 — Untyped API contract (highest consequence gap)**`
- New: `**G1 — Untyped API contract (highest value before team sharing)**`

Also update the paragraph's last sentence from "This is the most
consequential gap in the current stack." to "This is the highest-value
gap to close before the tool gets shared with a second operator."

### R2. Out-of-scope pointer for testing + observability

**Where:** New subsection at the end of §3 "Architecture Gaps" —
immediately after G11 (last operational gap), immediately before §4
"Execution Logic".

**What:**
> ### Out of scope for this document
>
> The following are real gaps but covered in separate docs to keep the
> architecture plan focused:
>
> - **Testing strategy** — unit tests for `queries.py`, contract tests
>   between React types and API responses, Playwright CI integration.
>   _Separate doc: `docs/TESTING_STRATEGY.md` (TODO)._
> - **Observability** — structured logs, request tracing, audit log for
>   staging promotions, latency metrics.
>   _Separate doc: `docs/OBSERVABILITY_PLAN.md` (TODO)._
> - **Schema migration tooling** — current DDL changes go through staging
>   workflow manually. Alembic-style tooling is a separate concern.
>   _Separate doc: `docs/SCHEMA_MIGRATIONS.md` (TODO)._

### R3. Ticker validation — route regex + deferred DB-universe check

Addressed in C3 and C3b. C3 widens the regex in Batch 1-A to
`^[A-Z]{1,6}[.A-Z]?$` and names BL-7 as the deferred follow-on. C3b
adds BL-7 to the §Backlog table.

## Verification

Doc-only change — no code execution needed. Verify by:

1. Re-read the doc top to bottom — confirm flow still reads logically
   with Phase 0 inserted, G1 reworded, annotations in place.
2. Grep for internal consistency:
   ```
   grep -c "highest consequence" ARCHITECTURE_REVIEW.md           # expect 0
   grep -c "highest value before team sharing" ARCHITECTURE_REVIEW.md  # expect ≥1
   grep -c "Phase 0" ARCHITECTURE_REVIEW.md                       # expect ≥3
   grep -c "2–3 days" ARCHITECTURE_REVIEW.md                      # expect ≥1 (Batch 4-C)
   grep -c "dual-mount" ARCHITECTURE_REVIEW.md                    # expect ≥1
   grep -c "BL-7" ARCHITECTURE_REVIEW.md                          # expect ≥2 (backlog row + C3 reference)
   grep -c "Out of scope for this document" ARCHITECTURE_REVIEW.md  # expect 1
   ```
3. Confirm ROADMAP.md "ARCHITECTURE BACKLOG" section is still consistent
   — Phase 0 CI promotion means BL-1 should update or move there too
   (separate commit, noted but not in this plan's scope).
4. Line count check — expect ~490–510 lines (435 current + ~60 additions).

## Commit plan

Single commit: `docs: ARCHITECTURE_REVIEW.md — revision pass after critical review`

Body summarizes the 6 concrete + 3 annotation + 3 residual changes.
Follow-on commit updates ROADMAP.md to reflect BL-1 → Phase 0 promotion
(out of scope for this plan).
