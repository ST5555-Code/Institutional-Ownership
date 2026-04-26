# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

Today's session (HEAD `a7e040a`, PRs #153–#166):

- **bug-1 / bug-2 closure** — moved from P0 to COMPLETED (PR #153, doc-sync PR #154).
- **audit-tracker staleness CI** — `audit_tracker_staleness.py` wired into pre-commit + CI (PR #155).
- **app-hardening (43b SECURITY)** — `ALLOWED_FLAGS` gate + B608/B110 nosec cleanup (PR #156); doc-sync PR #157.
- **perf-P0** — `compute_peer_rotation` precompute pipeline (PR #158) + `get_peer_rotation*` reads from `peer_rotation_flows` (PR #159). Latency 11.4s → 540ms parent (21x), 46ms detail. Doc-sync PR #160.
- **eqt-classify-codefix** — classifier stops reading stale `security_type_inferred` (PR #162); 8,148 CUSIPs reclassified, 662K holdings ticker changes, 342 `manual_correction` rows eliminated. Doc-sync PRs #161 + #163.
- **snapshot-retention-cadence** — `make snapshot-retention[-dry]` + wired into `make quarterly-update` (PR #164).
- **pk-enforce** — migration 020 declared PRIMARY KEY on 21 L3/L4 tables (PR #165). 1 dup row deleted from `cik_crd_links`; `entity_current` view dropped + recreated; total wall 137.7s. `other_managers` deferred (5,518 NULL `other_cik` rows; PK shape needs review). Stamp `020_pk_enforcement` at 2026-04-26 08:18 UTC.
- **INF16 — Soros AUM recompute** — `managers.aum_total` recomputed for CIKs `0001029160` and `0001748240`.
- **BL-4 — snapshot roles documented** — `docs/snapshot_roles.md` added; documents serving / rollback / archive roles.
- **cusip-classifications-registry** — registered `cusip_classifications` (L3) + `peer_rotation_flows` (L4) in `DATASET_REGISTRY` (PR #166).

## Up next

- See `ROADMAP.md` "Current backlog". P0 empty.
- **P1:** `ui-audit-walkthrough` (live walkthrough — not a Code session).
- **P2 sprint candidates:** `perf-P1`, `DM13`, `DM15d`, `pct-rename-sweep`.
- **P3 quick wins:** React-1, React-2, dead-endpoints, `other_managers` PK shape decision, `ncen_adviser_map` NULLs.

## Reminders

- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix landed (PR #162), but the `security_type_inferred` column still exists in the schema — column drop is a separate migration. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) is authorized on or after 2026-05-09 per `MAINTENANCE.md`. Do not drop earlier.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` is blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely `(accession_number, sequence_number)` with 19-row dedupe) before scheduling.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
