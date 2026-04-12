# 13F Ownership — Next Session Context

_Last updated: 2026-04-12 (Phase 3 visual polish complete, HEAD: pending)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (pending push)
- **HEAD:** `c836813`
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - Flask — `scripts/app.py` (~1400 lines) + `scripts/admin_bp.py` (~700 lines, admin Blueprint, INF12)
  - DuckDB — `data/13f.duckdb` (prod), `data/13f_staging.duckdb` (staging)
  - Vanilla JS — `web/static/app.js` (~5600 lines)
  - Jinja templates — `web/templates/index.html` + `web/templates/admin.html`
  - **React full-app (Phase 3 COMPLETE)** — `web/react-app/` (port 5174). All 11 tabs ported + Phase 3 polish done (badge consolidation, Fund Portfolio → Register cross-nav, print CSS, Playwright scaffold). See `REACT_MIGRATION.md`. Next: Phase 4 cut over (`npm run build` → Flask serves `dist/`).

---

## First 5 minutes — read these

1. **`~/ClaudeWorkspace/CLAUDE.md`** — workspace rules
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF18. COMPLETED section at line ~260+.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — React app migration plan
5. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`

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

### 1. Stage 5 cleanup — scheduled 2026-05-09+, requires explicit authorization

Original tables retained for 30-day rollback after Phase 4 cutover (2026-04-09). Cleanup list:
- Delete 4 INF9d ghost entities (eid=20194, 20196, 20201, 20203 — no aliases, no identifiers, no holdings)
- Drop legacy pre-entity tables (holdings v1, old parent_bridge snapshots, etc.)
- Requires explicit user authorization before any deletion

### 2. N-PORT data refresh

`fund_holdings_v2` data is stale through Oct 2025. Pipeline run needed to fetch current N-PORT filings. Run manually from terminal:
```bash
! python3 -u scripts/fetch_nport.py --test  # test first
! python3 -u scripts/fetch_nport.py          # full run (authorized)
```
This is a pipeline operation, NOT a data QC task. Do not run without explicit user authorization.

### 3. React migration — ongoing parallel workstream

**Phase 3 COMPLETE** (2026-04-12). RegisterTab badge → shared `getTypeStyle`, Fund Portfolio ticker → Register cross-nav, print CSS gaps closed on ShortInterest/PeerRotation/SectorRotation, Playwright scaffold (`@playwright/test`, config + 11-tab spec, `npm run test:visual` scripts). Baselines not yet captured. One-time setup for next session:
```bash
! cd web/react-app && npx playwright install chromium    # ~150MB
! cd web/react-app && npm run test:visual:update         # captures baselines; Flask must be up on :8001
```
**Next: Phase 4 cut over.** `npm run build` → Flask serves `web/react-app/dist/index.html`. One-line change in `scripts/app.py`. Revertable in 30 seconds. Retire `web/react-src/` POC afterward. See `REACT_MIGRATION.md` for backend migration plan (gated on Phase 6).

### 4. Minor follow-ups

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
