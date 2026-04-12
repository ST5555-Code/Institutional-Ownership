# 13F Ownership — Next Session Context

_Last updated: 2026-04-12 (session close, HEAD: f3d32db)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `f3d32db`
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - Flask — `scripts/app.py` (~1400 lines) + `scripts/admin_bp.py` (~700 lines, admin Blueprint, INF12)
  - DuckDB — `data/13f.duckdb` (prod), `data/13f_staging.duckdb` (staging)
  - Vanilla JS — `web/static/app.js` (~5600 lines)
  - Jinja templates — `web/templates/index.html` + `web/templates/admin.html`
  - **React full-app (in progress)** — `web/react-app/` (port 5174). Phase 2 complete: Register + Ownership Trend + Conviction tabs ported. See `REACT_MIGRATION.md`.

---

## First 5 minutes — read these

1. **`~/ClaudeWorkspace/CLAUDE.md`** — workspace rules
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF18. COMPLETED section at line ~250+.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — React app migration plan
5. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`

---

## Items completed this session (2026-04-11 + 2026-04-12)

### Data QC + infrastructure completed (20 items)

| Item | Commit | Snapshot | Summary |
|---|---|---|---|
| **INF12** | `d51db60` | — | Admin Blueprint with token auth. 15 routes gated. |
| **INF7** | `1a43376` | `20260411_180047` | Soros/VSS + Peter Soros/Orion fuzzy-match cleanup. |
| **INF17 Ph2** | `6743f11` | `20260411_214440` | Self-root 5 misattributed entities ($1.27B corrected). |
| **INF17 Ph3** | `0634682` | — | Fix `build_managers.py` fuzzy matcher: brand-token overlap gate. |
| **INF4** | `ff49dbc` | `20260411_221854` | Loomis Sayles merge (eid=17973→7650). |
| **L4-2** | `a3c20e8` | `20260412_061258` | 3 classification mismatches → mixed. |
| **INF6** | `eaab03b` | `20260412_063446` | Tortoise Capital merge (eid=20187→2273). |
| **INF8** | `ffa9796` | `20260412_064353` | Trian merge (eid=1090+9075→107). |
| **INF4b** | `d89e663` | — | CRD normalization: `_normalize_crd()` + LTRIM lookup. |
| **INF4d** | `eddb05c` | `20260412_074237` | Boston Partners merge (eid=17933→9143). $96.58B. |
| **INF4c** | `73f6acd` | `20260412_075814` | Batch merge 96 CRD-format fragmented pairs. |
| **INF4e** | `dba066b` | — | 4 borderline pairs excluded as CRD pollutions. |
| **L4-1** | `1e01b6b` | `20260412_085048` | 3 mixed→active (Ameriprise, PIMCO, AMG). |
| **INF17 Ph1** | `46877c5` | — | Scrub 127 managers rows. |
| **INF17b** | `4ff0006` | — | Brand-token gate in `fetch_ncen.py`. |
| **INF9e** | `47bb627` | `20260412_092411` | diff/promote extended. 24 overrides promoted to prod. |
| **INF9a/b/c/d** | `a0d6685` | — | Schema + replay extensions. 4 columns, 3 new action types. |
| **INF9b data** | `8f8d9f2` | — | 9 Securian DM12 override rows written. |
| **INF13** | `f3d32db` | — | Verified: fail-fast already in place, no code change. |
| **43i** | `f3d32db` | `20260412_103422` | 4 Baird sub-advisers self-rooted for EC. |

### Production validation: 9 PASS / 0 FAIL / 7 MANUAL

---

## INF9 status — entity_overrides_persistent

**35 rows in prod.** Schema has 4 extension columns (INF9a/b/c/d).

| Component | Status | Detail |
|---|---|---|
| **Table in prod** | ✓ Live | 35 rows: 24 reclassify + 2 set_activist + 9 merge/DM |
| **diff/promote/sync** | ✓ Done | Full staging workflow coverage (INF9e) |
| **Schema extensions** | ✓ Done | identifier_type, identifier_value, rollup_type, relationship_context |
| **5 action types** | ✓ Code ready | reclassify, set_activist, alias_add, merge (with rollup_type), suppress_relationship |
| **INF9b data** | ✓ Done | 9 Securian fund series. HC Capital/CRI were planning-phase, never executed. |
| **INF9c data** | ⏳ Pending | L5 deletion list not recoverable — needs fresh L5 parent_bridge audit |
| **INF9d orphans** | ⏳ Pending | 3 entities (Pacific Life, Stowers, Stonegate) need manual_entities_preserve |

---

## Open items — current priority order

### 1. INF9c data — Fresh L5 parent_bridge audit

Code framework (`suppress_relationship` action) is ready. Original L5 deletion list not recoverable from current DB state. Need to re-audit parent_bridge fuzzy-match relationships to identify which are still bad. INF5 verifier backstops ADV-sourced subset.

### 2. INF9d — manual_entities_preserve for 3 orphan entities

Pacific Life (eid=20194), Stowers (eid=20196), Stonegate (eid=20201) get dropped on `--reset`. Need a curated list in `build_entities.py` that re-creates them before replaying overrides.

### 3. INF18 — Financial Partners Group children investigation

Cassaday, LVW Advisors, Quadrant Private Wealth roll under Financial Partners Group for EC via orphan_scan. Verify if legitimate subsidiaries (FPG is an RIA aggregator) or sub-advisers. If subs: self-root for EC.

### 4. INF17 Phase 4 — Preserve coincidentally-correct rollups

`parent_bridge_sync` manual writes for Carillon→RJF, Nikko→Sumitomo, Martin Currie→Martin Currie Ltd. Depends on INF9c data landing first.

### 5. Amundi → Amundi Taiwan rollup

eid=830 + eid=4248 → eid=752 Amundi Taiwan. Should roll to global Amundi SA parent.

### 6. React migration — next tab

Phase 2 complete (Register + Ownership Trend + Conviction). Pick next tab. See `REACT_MIGRATION.md`.

---

## Critical gotchas — discovered the hard way

### a–e: Flask, IIFEs, switchTab, bandit 1.8.3, nosec B608

See full text in `87bc812` version.

### f. Data model traps

- **`entity_overrides_persistent`** — **35 rows in prod.** 5 action types, 4 extension columns (INF9a/b/c/d `a0d6685`). Flows through standard staging workflow. `replay_persistent_overrides()` resolves via `(identifier_type, identifier_value)` with CRD normalization.
- **`managers.aum_total` + `crd_number`** — 127 rows scrubbed to NULL (INF17 Phase 1). Use `SUM(holdings_v2.market_value_usd)` for AUM.
- **`holdings_v2.cik`** — 10-digit zero-padded.
- **`fund_universe.is_actively_managed`** — authoritative active/passive flag. `NULL` = unknown.
- **`entity_relationships`** — 5 types. Exclude `sub_adviser` when walking ownership trees.
- **13F-NT vs 13F-HR** — NT filers have zero `holdings_v2` rows.
- **CRD normalization** — `entity_sync._normalize_crd()` strips leading zeros (INF4b). LTRIM lookup handles retroactive matching.
- **`_resolve_db_path()`** — fail-fast RuntimeError when main DB locked and no snapshot exists. `shutil.copy2` removed (INF13 verified).

### g–h: React/AG Grid/Tailwind landmines, inline style cascade

See `87bc812` version.

### i. Fuzzy name matching — brand-token Jaccard, not token_sort_ratio

Both `build_managers.py` and `fetch_ncen.py` have `_BRAND_STOPWORDS` + `_brand_tokens_overlap()`.

### j–k: DuckDB similarity gap + audit query join bug

### l. merge_staging.py — managers uses DROP+CREATE path

### m. sync_staging.py — entity_overrides_persistent syncs normally

### n. `manually_verified=True` is unreliable

### o. 13F-NT filers distort AUM-at-risk estimates

### p. CRD format normalization (INF4b)

100 entity pairs merged, 15 excluded. Code fix prevents new occurrences.

### q. Batch entity merge: always transfer CIK identifiers

INSERT on survivor before closing source. INF4c lesson (~$166B gap).

### r. L4-1 LOW_COV: N-PORT coverage < 50% → keep mixed

### s. Sub-adviser vs subsidiary for EC rollup (NEW — 43i)

When a non-fund entity rolls under a parent for `economic_control_v1` via `transitive_flatten` or `orphan_scan`, check whether the child is a **subsidiary** (legitimate EC rollup — brand-name subsidiaries like Carillon→Raymond James, Royce→Franklin Templeton) or a **sub-adviser** (should self-root for EC — GAMMA/Reinhart/Strategas sub-advising Baird funds but not owned by Baird). The brand-token overlap heuristic catches most cases, but sub-advisers with no name overlap AND no ownership relationship are the ones that need manual review. The 43i audit found 28 zero-overlap institution pairs; 24 were legitimate subsidiaries, 4 were mis-classified sub-advisers (all under Baird).

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: f3d32db or newer
pgrep -f "scripts/app.py"       # dev server PID
curl -s http://localhost:8001/api/tickers | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"  # 6500+
python3 scripts/validate_entities.py --prod   # 9 PASS / 0 FAIL / 7 MANUAL
python3 -c "import duckdb; print(duckdb.connect('data/13f.duckdb',read_only=True).execute('SELECT COUNT(*) FROM entity_overrides_persistent').fetchone()[0], 'overrides in prod')"  # 35
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization.
- Never mutate production data to simulate test conditions.
- Always update `ROADMAP.md` after completing a task.
- Entity changes: `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- Reference-table changes: `merge_staging.py --tables <name>`.
- **Entity overrides: 35 rows in prod.** 5 action types. Resolution uses `(identifier_type, identifier_value)` with CRD normalization.
- Read files in full before editing.
- Confirm destructive actions before running.
- Use `python3 -u` for background tasks.
- Never trust `managers.manually_verified=True`.
- Never use `fuzz.token_sort_ratio` alone for firm name matching.
- CRD values must be normalized via `_normalize_crd()`.
- Batch entity merges: always transfer CIK identifiers before closing.
- N-PORT coverage < 50%: keep classification as `mixed`.
- Sub-adviser vs subsidiary: verify before EC rollup (gotcha s).

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

## Session ledger (newest first)

```
f3d32db 43i: self-root 4 Baird sub-advisers for EC + INF13 verified Done + INF18
8f8d9f2 INF9b: write 9 Securian DM12 override rows
a0d6685 INF9a/b/c/d: schema + replay extensions
47bb627 INF9e: diff/promote extended + 24 overrides promoted
50c9065 ROADMAP: L4-1 + INF17 Phase 1 + INF17b Done
4ff0006 INF17b: brand-token gate in fetch_ncen.py
46877c5 INF17 Phase 1: scrub 127 managers rows
1e01b6b L4-1: 3 mixed→active
dba066b INF4e Done: 4 pairs excluded as CRD pollutions
73f6acd INF4c: batch merge 96 CRD-format fragmented pairs
eddb05c INF4d: Boston Partners merge
d89e663 INF4b + INF17b: CRD normalization
ffa9796 INF8: Trian merge
eaab03b INF6: Tortoise Capital merge
a3c20e8 L4-2: 3 classification fixes
ff49dbc INF4: Loomis Sayles merge
0634682 INF17 Phase 3: build_managers.py fuzzy-match fix
6743f11 INF17 Phase 2: self-root 5 misattributed entities
1a43376 INF7: Soros/VSS cleanup
d51db60 INF12: admin Blueprint with token auth
b53e3fa INF9 Route A: 24 reclassify overrides to staging
```
