# 13F Ownership — Next Session Context

_Last updated: 2026-04-12 (session close, HEAD: a0d6685)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `a0d6685`
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
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF17b. COMPLETED section at line ~240+.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — React app migration plan
5. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`

---

## Items completed this session (2026-04-11 + 2026-04-12)

### Data QC + infrastructure completed

| Item | Commit | Snapshot | Summary |
|---|---|---|---|
| **INF12** | `d51db60` | — | Admin Blueprint with token auth. 15 routes gated. |
| **INF7** | `1a43376` | `20260411_180047` | Soros/VSS + Peter Soros/Orion fuzzy-match cleanup. |
| **INF17 Phase 2** | `6743f11` | `20260411_214440` | Self-root 5 misattributed entities ($1.27B corrected). |
| **INF17 Phase 3** | `0634682` | — | Fix `build_managers.py` fuzzy matcher: brand-token overlap gate. |
| **INF4** | `ff49dbc` | `20260411_221854` | Loomis Sayles merge (eid=17973→7650). |
| **L4-2** | `a3c20e8` | `20260412_061258` | 3 classification mismatches (Invesco/Nuveen/Security Investors → mixed). |
| **INF6** | `eaab03b` | `20260412_063446` | Tortoise Capital merge (eid=20187→2273). |
| **INF8** | `ffa9796` | `20260412_064353` | Trian merge (eid=1090+9075→107). |
| **INF4b** | `d89e663` | — | CRD normalization: `_normalize_crd()` + LTRIM retroactive lookup. |
| **INF4d** | `eddb05c` | `20260412_074237` | Boston Partners merge (eid=17933→9143). $96.58B Q4. |
| **INF4c** | `73f6acd` | `20260412_075814` | Batch merge 96 CRD-format fragmented pairs. 5,888 row ops. |
| **INF4e** | `dba066b` | — | All 4 borderline pairs excluded as CRD pollutions. |
| **L4-1** | `1e01b6b` | `20260412_085048` | 3 mixed→active (Ameriprise, PIMCO, AMG). |
| **INF17 Phase 1** | `46877c5` | — | Scrub 127 managers rows (crd_number + aum_total → NULL). |
| **INF17b** | `4ff0006` | — | Brand-token overlap gate in `fetch_ncen.py`. |
| **INF9e** | `47bb627` | `20260412_092411` | diff_staging + promote_staging extended. 24 overrides promoted to prod. |
| **INF9a/b/c/d** | `a0d6685` | — | Schema + replay extensions. 4 new columns, 3 new action types, 2 override rows written. |

### Production validation after all promotions: 9 PASS / 0 FAIL / 7 MANUAL

---

## INF9 status — entity_overrides_persistent

**Table is live in prod** (26 rows). Schema extended with 4 new columns (`a0d6685`).

| Component | Status | Detail |
|---|---|---|
| **Table in prod** | ✓ Live | 26 rows (24 Route A reclassify + 2 INF9a set_activist) |
| **diff_staging.py** | ✓ Done | Shows overrides in diff output (INF9e) |
| **promote_staging.py** | ✓ Done | Auto-creates table if missing + syncs rows (INF9e) |
| **sync_staging.py** | ✓ Working | Copies prod→staging normally (no more SKIP) |
| **Schema: identifier_type/value** | ✓ Done | Generic lookup replaces CIK-only (INF9d) |
| **Schema: rollup_type** | ✓ Done | Merge action reads from row (INF9b) |
| **Schema: relationship_context** | ✓ Done | JSON for suppress_relationship (INF9c) |
| **Action: reclassify** | ✓ Working | 24 rows in prod |
| **Action: set_activist** | ✓ Working | 2 rows in prod (INF9a) |
| **Action: alias_add** | ✓ Working | Code ready, no rows yet |
| **Action: merge** | ✓ Working | Code ready with rollup_type support, no rows yet |
| **Action: suppress_relationship** | ✓ Working | Code ready, no rows yet |
| **INF9b data** | ⏳ Pending | 13 DM12 sub-adviser routing override rows — need CIK investigation |
| **INF9c data** | ⏳ Pending | ~28 suppress_relationship rows — need L5 deletion list |
| **INF9d orphans** | ⏳ Pending | 3 entities (Pacific Life, Stowers, Stonegate) need manual_entities_preserve mechanism |

---

## Open items — current priority order

### 1. INF9b data — identify 13 DM12 CIKs and write override rows

Schema and replay code are ready (`a0d6685`). Need to investigate the Apr-10 session's DM12 narrow routing fixes (Securian/Sterling false ADV match + HC Capital Trust 7 sub-adviser routings + CRI 5 sub-adviser routings) to extract the specific CIKs and parent CIKs. Write 13 `merge` override rows with `rollup_type='decision_maker_v1'` to both staging + prod.

### 2. INF9c data — enumerate L5 deletion list and write suppress rows

Schema and replay code are ready. Need to enumerate the parent_bridge fuzzy-match subset of the 28 L5 deletions from Apr 10 (ADV subset already backstopped by INF5 verifier). For each: write a `suppress_relationship` override row with `relationship_context` JSON containing `{parent_cik, child_cik, relationship_type}`.

### 3. INF9d — manual_entities_preserve mechanism for 3 orphan entities

Pacific Life (eid=20194), Stowers Institute (eid=20196), Stonegate Global Financial (eid=20201) are orphan entities with no feeder backing — they get dropped on `--reset`. Need a curated list that `build_entities.py` re-creates after `--reset` before replaying overrides. International Assets Advisory (eid=20203, CRD-only) can now use `identifier_type='crd'` for resolution.

### 4. Amundi → Amundi Taiwan rollup

eid=830 + eid=4248 both roll to `eid=752 Amundi Taiwan Ltd.` via `parent_bridge_sync/manual`. Should roll to global Amundi SA parent.

### 5. INF13 part 2 — Snapshot fallback race condition

`_resolve_db_path()` hot-path `shutil.copy2` on live DuckDB file. Verify current status — the INF13 ROADMAP row says Part 1 was the `refresh_snapshot.sh` fix and the hot-path copy was removed. May already be resolved.

### 6. INF17 Phase 4 — Preserve coincidentally-correct rollups

`parent_bridge_sync` manual writes for Carillon→RJF, Nikko→Sumitomo, Martin Currie→Martin Currie Ltd. Depends on INF9c data rows landing first (the `suppress_relationship` action is needed to prevent the bad edges from being re-created). After INF9c data lands, INF17 Phase 4 can use the same mechanism.

### 7. React migration — next tab

Phase 2 complete (Register + Ownership Trend + Conviction). Pick next tab to port. See `REACT_MIGRATION.md`.

---

## Critical gotchas — discovered the hard way

### a–e: Flask, IIFEs, switchTab, bandit 1.8.3, nosec B608

Unchanged from prior sessions. See full text in `87bc812` version.

### f. Data model traps

- **`entity_overrides_persistent`** — **live in prod** (26 rows). Schema extended with `identifier_type`, `identifier_value`, `rollup_type`, `relationship_context` (INF9a/b/c/d `a0d6685`). `sync_staging.py` copies normally. `diff_staging.py` shows overrides. `promote_staging.py` auto-creates if missing.
- **`managers.aum_total` + `managers.crd_number`** — 127 rows scrubbed to NULL (INF17 Phase 1). Use `SUM(holdings_v2.market_value_usd)` for AUM.
- **`holdings_v2.cik`** — 10-digit zero-padded.
- **`fund_universe.is_actively_managed`** — authoritative active/passive flag. `NULL` = unknown.
- **`entity_relationships`** — 5 types. Exclude `sub_adviser` when walking ownership trees.
- **13F-NT vs 13F-HR** — NT filers have zero `holdings_v2` rows.
- **CRD normalization** — `entity_sync._normalize_crd()` strips leading zeros (INF4b). LTRIM lookup handles retroactive matching. Also used in `replay_persistent_overrides()` for CRD-type overrides.

### g–h: React/AG Grid/Tailwind landmines, inline style cascade

10 specific gotchas from TCO port. See full text in `87bc812` version.

### i. Fuzzy name matching — use brand-token Jaccard, not token_sort_ratio

Reference: `build_managers.py` + `fetch_ncen.py` both have `_BRAND_STOPWORDS` + `_brand_tokens_overlap()`.

### j–k: DuckDB similarity gap + audit query join bug

### l. merge_staging.py — managers uses DROP+CREATE path

### m. sync_staging.py — entity_overrides_persistent now syncs normally

No longer staging-only — live in prod since INF9e.

### n. `manually_verified=True` is unreliable

### o. 13F-NT filers distort AUM-at-risk estimates

### p. CRD format normalization (INF4b)

100 entity pairs merged, 15 excluded. Code fix prevents new occurrences.

### q. Batch entity merge: always transfer CIK identifiers

Do NOT just close a merge source's CIK — **INSERT a copy on the survivor first**. INF4c hit ~$166B gap when 12 CIKs were closed without transferring. `total_aum` gate compares `SUM(managers.aum_total)` through the `entity_identifiers → entity_rollup_history` chain — dropped CIKs break the join. Same pattern as INF8 Trian.

### r. L4-1 LOW_COV: N-PORT coverage < 50% → keep mixed

Goldman (27%), Franklin Templeton (27%), Nomura (32%), Focus (35%) kept mixed despite ≥90% active N-PORT split.

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: a0d6685 or newer
pgrep -f "scripts/app.py"       # dev server PID
curl -s http://localhost:8001/api/tickers | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"  # 6500+
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/admin/stats  # 503
python3 scripts/validate_entities.py --prod   # 9 PASS / 0 FAIL / 7 MANUAL
python3 -c "import duckdb; print(duckdb.connect('data/13f.duckdb',read_only=True).execute('SELECT COUNT(*) FROM entity_overrides_persistent').fetchone()[0], 'overrides in prod')"  # 26
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization. `--test` mode only unless user says otherwise.
- Never mutate production data to simulate test conditions. Use flags or parameters.
- Always update `ROADMAP.md` after completing a task — move items to COMPLETED with date and details.
- Entity changes go through the staging workflow (INF1): `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- **Reference-table changes** (like `managers`) go through `merge_staging.py --tables <name>`, NOT `promote_staging.py`.
- **Entity overrides: live in prod** (26 rows). `entity_overrides_persistent` flows through standard staging workflow (INF9e). Supports 5 action types: `reclassify`, `set_activist`, `alias_add`, `merge` (with `rollup_type`), `suppress_relationship` (with `relationship_context` JSON). Entity resolution uses `(identifier_type, identifier_value)` with CRD normalization fallback.
- Read files **in full** before editing.
- Confirm destructive actions before running.
- Use `python3 -u` for background tasks.
- **Never trust `managers.manually_verified=True`.**
- **Never use `fuzz.token_sort_ratio` alone for firm name matching.**
- **CRD values must be normalized** via `_normalize_crd()` before any insert or lookup (INF4b).
- **Batch entity merges: always transfer CIK identifiers** from merge source to survivor before closing them (gotcha q). Closing without transferring breaks `total_aum` gate.
- **N-PORT coverage < 50%: keep classification as `mixed`** regardless of active/passive split (gotcha r).

---

## User collaboration preferences

- Terse, direct communication. Lead with the answer.
- Quick fixes preferred over comprehensive refactors unless explicitly asked.
- User tests in Safari, sometimes Chrome.
- Suggest `! <cmd>` for commands the user should run themselves.
- Flag duplicate ROADMAP items before adding.
- Don't delete files/data/rows without explicit confirmation.
- Report scope precisely: "entities affected" ≠ "entities with holdings at risk" ≠ "dollars at risk".

---

## Session ledger (newest first)

```
a0d6685 INF9a/b/c/d: extend entity_overrides_persistent schema and replay
47bb627 INF9e: extend diff_staging + promote_staging + prod DDL + 24 overrides promoted
50c9065 ROADMAP: mark L4-1 Done + INF17 Phase 1 Done + INF17b fully Done
4ff0006 INF17b: add brand-token overlap gate to fetch_ncen.py
46877c5 INF17 Phase 1: scrub 127 managers rows
1e01b6b L4-1: reclassify 3 mixed entities to active
dba066b ROADMAP: mark INF4e Done
73f6acd INF4c: batch merge 96 CRD-format fragmented pairs
eddb05c INF4d: merge eid=17933 into eid=9143 — Boston Partners
d89e663 INF4b + INF17b: normalize CRD format in entity resolver
ffa9796 INF8: merge eid=1090 + eid=9075 into eid=107 — Trian
eaab03b INF6: merge eid=20187 into eid=2273 — Tortoise Capital
a3c20e8 L4-2: fix 3 classification mismatches
ff49dbc INF4: merge eid=17973 into eid=7650 — Loomis Sayles
0634682 INF17 Phase 3: fix build_managers.py CRD fuzzy-match
6743f11 INF17 Phase 2: self-root 5 misattributed entities
1a43376 INF7 Done: Soros/VSS + Peter Soros/Orion cleanup
d51db60 INF12: admin Blueprint with token auth
b53e3fa INF9 Route A: persist 24 reclassify overrides to staging
```
