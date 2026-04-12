# Next Session Prompt — 13F Ownership

Paste this at the start of the next Claude Code session.

---

## Context

Read `docs/NEXT_SESSION_CONTEXT.md` before doing any work.

**Entity data QC is complete.** 24 infrastructure items shipped across
2026-04-11 + 2026-04-12. Entity layer is in its cleanest state since
launch: 101 CRD-format merges, 47 override rows in prod, 127 managers
scrubs, 6 classification fixes, all validation gates green (9/0/7).

**React Phase 2 is complete.** All 11 tabs ported to `web/react-app/`
(port 5174): Register, Ownership Trend, Conviction, Fund Portfolio,
Flow Analysis, Cross-Ownership, Overlap Analysis, Peer Rotation,
Sector Rotation, Entity Graph, Short Interest. See `REACT_MIGRATION.md`.

## What's next — pick one track

### Track A: React Phase 3 — Visual polish + UX refinement

Read `REACT_MIGRATION.md` Phase 3 section. The 11 tabs are functional
but need visual polish before cut over:
- Consistent spacing/padding across all tabs
- Loading states and error boundaries
- Empty state handling ("No data for ticker X")
- Print/export formatting
- Mobile responsiveness (if needed)
- Playwright visual regression setup (now that 3+ tabs exist)

### Track B: React Phase 4 — Cut over

If Phase 3 polish is deferred or minimal:
- One-line change in `scripts/app.py` to serve `web/react-app/dist/`
  instead of `web/templates/index.html`
- Test on port 8001 (Flask serves the React build)
- Revertable in 30 seconds

### Track C: N-PORT data refresh

`fund_holdings_v2` data is stale (last fetch was Oct 2025).
Pipeline run needed:
```bash
! python3 -u scripts/fetch_nport.py --test   # test first
! python3 -u scripts/fetch_nport.py           # full run
```
Requires explicit authorization. Do not run without it.

### Track D: Stage 5 cleanup (2026-05-09+)

Scheduled for on or after 2026-05-09 (30 days post-Phase 4 cutover).
Requires explicit authorization before any deletion:
- Delete 4 INF9d ghost entities (eid=20194, 20196, 20201, 20203)
- Drop legacy pre-entity tables
- Archive old snapshots

### Track E: Minor data QC follow-ups

- Amundi → Amundi Taiwan rollup (eid=830 + eid=4248)
- Financial Partners Group fragmentation (eid=1600/9722)
- INF9c entity_id stability (PARENT_SEEDS ghosts)

---

## Key files to read first

1. `~/ClaudeWorkspace/CLAUDE.md` — workspace rules
2. `ROADMAP.md` — full project state
3. `docs/NEXT_SESSION_CONTEXT.md` — session context + gotchas
4. `REACT_MIGRATION.md` — React migration plan
5. `docs/PROCESS_RULES.md` — pipeline rules

## Production state

```bash
python3 scripts/validate_entities.py --prod   # 9 PASS / 0 FAIL / 7 MANUAL
python3 -c "import duckdb; print(duckdb.connect('data/13f.duckdb',read_only=True).execute('SELECT COUNT(*) FROM entity_overrides_persistent').fetchone()[0], 'overrides')"  # 47
```
