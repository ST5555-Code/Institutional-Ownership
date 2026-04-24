# ops-batch-5B — Findings (doc-only batch)

_Prepared: 2026-04-21 — branch `remediation/ops-batch-5B` off main HEAD
(after `60c8713 docs(mig-01): add Phase 1 implementation prompt for
atomic promotes` landed). No code or DB writes._

Meta-doc for the Batch 5-B doc updates: ops-06, ops-09, ops-15. See
`archive/docs/prompts/ops-batch-5B.md` for the driving prompt and
`docs/REMEDIATION_PLAN.md` Theme 5 for context.

## Changes

### ops-06 — `docs/write_path_risk_map.md` (refresh)

Refreshed the existing risk map to reflect the Stage 5 pipeline state:

- Added a **Current architectural pattern** section covering the three
  `Protocol`s in `scripts/pipeline/protocol.py` (`SourcePipeline`,
  `DirectWritePipeline`, `DerivedPipeline`), the
  `scripts/pipeline/id_allocator.py` centralization (obs-03-p1), and
  the shared `manifest.py` helpers.
- Marked cleared T2 entries with dates and commit hashes: `load_13f.py`
  (Rewrite4 `7e68cf9`), `build_managers.py` (Rewrite5 `223b4d9`),
  `build_cusip.py` (CUSIP v1.4), `build_summaries.py` + `compute_flows.py`
  (Batch 3 close `87ee955`), `build_shares_history.py` (Rewrite1
  `d7ba1c2`).
- Added a dedicated **Promote-path atomicity (mig-01)** section noting
  mig-01-p0 as merged (commit `dd03780`) and mig-01-p1 as open
  (prompt `60c8713`). Flagged that `promote_*.py` remains T2-shape
  until mig-01-p1 lands.
- Added **Admin write-surface concurrency (sec-02 / sec-03)** section
  documenting the flock guards on `/run_script`, `/add_ticker`, and
  the 409-on-concurrent-write semantics for `/entity_override`.
- Added **Validator read-only defaults (sec-04)** section.
- Added **Retired scripts** section listing `fetch_nport.py`,
  `fetch_13dg.py`, `scripts/retired/build_cusip_legacy.py`.
- Updated T3 to promote `fetch_nport_v2.py`, `fetch_13dg_v2.py`,
  `fetch_dera_nport.py` as the current SourcePipeline writers.
- Revised **Follow-on work** to track mig-01-p1 (critical), mig-02
  (fetch_adv.py), build_benchmark_weights.py, build_fund_classes.py,
  and `update.py` retirement.

Header now reads _"Refreshed 2026-04-21 under remediation ops-06"_;
original 2026-04-13 creation date retained for provenance.

### ops-09 — `docs/api_architecture.md` (new)

New file documenting the FastAPI router architecture introduced in
Batch 4-C (2026-04-13):

- Entry-point description (`scripts/app.py`).
- Module-by-module summary (`app_db.py`, `api_common.py`, seven
  `api_*.py` routers, `admin_bp.py`).
- **Domain routers** table: 7 read-only routers, 40 GET endpoints, 0
  writes. Full column inventory: router, module, prefix, auth dep,
  GET count, POST count, notes.
- **Admin router** section: 12 GET + 6 POST, listing every write
  endpoint with its concurrency guard (CSRF + rate limit for login,
  `fcntl.flock` on `data/.add_ticker_lock` and `data/.run_script_lock`
  for sec-02-p1 / sec-03-p1, 409-on-concurrent for `/entity_override`).
- Router registration order (from `app.py`).
- Static assets + Jinja template mounts (`/assets/*`, `/admin`).
- Lifespan handler behaviour.
- Cross-references to `docs/endpoint_classification.md`,
  `docs/findings/sec-03-p0-findings.md` §2,
  `docs/findings/sec-02-p1-findings.md`,
  `docs/findings/sec-03-p1-findings.md`,
  `archive/docs/REACT_MIGRATION.md`.
- Follow-on: Phase 2 admin refresh will add ~9 endpoints — living
  inventory needed to prevent drift.

### ops-15 — `MAINTENANCE.md` §Refetch Pattern (concrete workflow)

`MAINTENANCE.md` already had a `## Refetch Pattern for Prod Apply` H2
section (the general BLOCK-3 precedent). Added a new `###` subsection
**Concrete workflow — OpenFIGI / CUSIP refetch** under it:

- Five-step command sequence (re-queue → retry → propagate →
  verify → promote) matching the int-01 refetch loop.
- Authorization note clarifying that step 5 (`promote_staging.py
  --approved`) is the only step that writes to `data/13f.duckdb`.
- "Why this shape" paragraph explaining restart-safety and reversibility.

Changed references to the concrete scripts (`int_01_requeue.py`,
`run_openfigi_retry.py`, `build_cusip.py`, `validate_classifications.py`,
`promote_staging.py`) — all verified to exist on main HEAD at the time
of writing.

## Files touched

- `docs/write_path_risk_map.md` — refreshed (ops-06).
- `docs/api_architecture.md` — new (ops-09).
- `MAINTENANCE.md` — new §Concrete workflow subsection (ops-15).
- `docs/findings/ops-batch-5B-findings.md` — this meta-doc.

No source / test / migration / DB touches.

## Out of scope (not this batch)

- ops-13 (data_layers.md §7 denorm drift) — Batch 5-C, depends on
  Theme 1 decisions.
- ops-14 (ROADMAP rows) — Batch 5-C.
- Any code changes to `scripts/`, `web/`, or migrations.

## Change log

- 2026-04-21: initial write-up. Branch `remediation/ops-batch-5B` off
  main HEAD after `60c8713`. Doc-only PR; no code / DB writes.
