# Chat Handover — 2026-04-26

## State

HEAD: ee33611 (post-PR #168)
Migrations: 001–020 applied
Open PRs: #107 only (ui-audit-walkthrough, intentional — needs live session)
P0: empty
Worktrees: clean (main only)

## Session 2026-04-25/26 — what landed

PRs #153–#168 (15 PRs):
- Snapshot retention first fire + Makefile automation (#164)
- bug-1 + bug-2 closed (stale ROADMAP entries, #153, #154)
- audit-tracker-staleness-ci wired to pre-commit + CI (#155)
- 43b SECURITY: ALLOWED_FLAGS subprocess gap, B608 relocated, B110 tightened (#156)
- perf-P0: peer_rotation_flows precompute (16.97M rows), 11.4s → 540ms (#158, #159)
- EQT data fix: 342→8,148 CUSIPs reclassified, 765K tickers enriched
- eqt-classify-codefix: classifier stop reading stale security_type_inferred (#162)
- L3 PK enforcement: 21 tables (#165)
- INF16: Soros AUM recomputed
- cusip-classifications + peer_rotation_flows registered in DATASET_REGISTRY (#166)
- BL-4: snapshot roles documented (#166)
- snapshot-retention-cadence: Makefile target (#164)
- DM13-A: 131 self-referential ADV edges suppressed (#168)

## In progress — DM13 B+C triage

- 214 rows exported to data/reports/dm13_bc_triage.csv
- 185 of 214 have currently_drives_rollup=TRUE — cannot blanket suppress
- 29 with currently_drives_rollup=FALSE are safe to suppress (graph noise)
- Next step: suppress the 29, defer the 185 for case-by-case review
- A Code session may still be open on the dm13-fix-bc branch — check with `git worktree list`

## Rules carried forward

- ROADMAP.md is the single source of truth for all items
- Do NOT run build_classifications.py --reset (eqt-classify-codefix landed but security_type_inferred column still in schema)
- Stage 5 DROP authorized on or after May 9, 2026
- Approach first, prompt second — always present approach and wait for confirmation before writing code
- Git ops: Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- Staging workflow mandatory for all entity changes
- All sessions named (short names)

## Recommended next steps (priority order)

A. DM13 B+C — suppress the 29 non-rollup edges. 15 min.
B. DM15d — N-CEN umbrella trusts (Sterling, NEOS, Segall Bryant). ~1 hr.
C. pct-rename-sweep — terminology cleanup. 1-2 hrs.
D. perf-P1 — 3 more precompute tables. Multi-day, start fresh.
