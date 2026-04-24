# ops-batch-5B — Batch 5-B doc updates: write_path_risk_map + api_architecture + MAINTENANCE refetch

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 5; `docs/REMEDIATION_CHECKLIST.md` Batch 5-B). Three parallel-eligible doc-only items that are disjoint files.

**No code writes, no DB writes.** Pure documentation.

## Branch

`remediation/ops-batch-5B` off main HEAD.

## Files this session will touch

Write:
- `docs/write_path_risk_map.md` — ops-06: refresh to reflect current pipeline state (Stage 5 with SourcePipeline, id_allocator, atomic promotes)
- `docs/api_architecture.md` (new) — ops-09: document the Blueprint/router split across api_config.py, api_register.py, api_fund.py, api_flows.py, api_entities.py, api_market.py, api_cross.py, admin_bp.py
- `MAINTENANCE.md` — ops-15: add §Refetch Pattern documenting the manual prod-apply workflow (re-queue → retry → propagate → promote)
- `docs/findings/ops-batch-5B-findings.md` (new) — meta-doc listing what changed

Read (verification only):
- `scripts/app.py` — router wiring for api_architecture doc
- `scripts/api_*.py` — endpoint inventory per router
- `scripts/admin_bp.py` — admin router inventory
- `docs/pipeline_violations.md` — current write-path state for risk map refresh
- `docs/data_layers.md` — cross-reference for risk map

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### ops-06 — `docs/write_path_risk_map.md` refresh

Update the existing risk map to reflect:
- SourcePipeline pattern (fetch_13dg_v2, fetch_nport_v2)
- id_allocator centralization (obs-03-p1)
- Atomic promotes (mig-01-p1 if merged; otherwise note as pending)
- sec-02-p1 flock guards on /run_script
- sec-03-p1 flock guard on /add_ticker
- sec-04-p1 validator read-only defaults
- Any retired scripts (fetch_nport.py legacy, etc.)

If the file does not exist, check if it is at a different path or create it fresh based on the current pipeline state.

### ops-09 — `docs/api_architecture.md` (new)

Document the current API router architecture:
- List each router, its module, prefix, auth dependency
- Count of endpoints per router (GET vs POST)
- Which routers are read-only vs have write endpoints
- Reference sec-03-p0 findings §2 for the admin write-surface table

### ops-15 — `MAINTENANCE.md` §Refetch Pattern

Add a new section documenting the manual prod-apply workflow:
1. Re-queue affected items (e.g. `scripts/oneoff/int_01_requeue.py`)
2. Retry against staging (`run_openfigi_retry.py --staging`)
3. Propagate staging tables (`build_cusip.py --staging --skip-openfigi`)
4. Verify acceptance criteria (read-only SQL checks)
5. Promote staging → prod (requires authorization)

This closes the DOC_UPDATE_PROPOSAL item 7.

## Out of scope

- ops-13 (data_layers.md §7 denorm drift) — Batch 5-C, depends on Theme 1 decisions.
- ops-14 (ROADMAP rows) — Batch 5-C.
- Any code changes.

## Hard stop

Do NOT merge. Open PR with title `remediation/ops-batch-5B: write_path_risk_map + api_architecture + MAINTENANCE refetch`. Report PR URL + CI status.
