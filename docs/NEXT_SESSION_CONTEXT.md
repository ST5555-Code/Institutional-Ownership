# 13F Ownership — Next Session Context

_Last updated: 2026-04-12 (session end, HEAD: 50c9065)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `50c9065`
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

### Data QC completed

| Item | Commit | Snapshot | Summary |
|---|---|---|---|
| **INF12** | `d51db60` | — | Admin Blueprint with token auth. 15 routes gated. |
| **INF7** | `1a43376` | `20260411_180047` | Soros/VSS + Peter Soros/Orion fuzzy-match cleanup. 9 entity edits + 3 managers scrubs. |
| **INF17 Phase 2** | `6743f11` | `20260411_214440` | Self-root 5 misattributed entities ($1.27B corrected). |
| **INF17 Phase 3** | `0634682` | — | Fix `build_managers.py` fuzzy matcher: brand-token overlap gate + rejection log. |
| **INF4** | `ff49dbc` | `20260411_221854` | Loomis Sayles merge (eid=17973→7650). 38 sub_adviser rels + 25 DM rollups, DM self-root fix. |
| **L4-2** | `a3c20e8` | `20260412_061258` | 3 classification mismatches (Invesco/Nuveen/Security Investors → mixed). |
| **INF6** | `eaab03b` | `20260412_063446` | Tortoise Capital merge (eid=20187→2273). 6 fund_sponsor rels + circular pair. |
| **INF8** | `ffa9796` | `20260412_064353` | Trian merge (eid=1090+9075→107). 3 identifiers transferred, 2 rels closed. |
| **INF4b** | `d89e663` | — | CRD normalization in entity resolver: `_normalize_crd()` + LTRIM retroactive lookup. |
| **INF4d** | `eddb05c` | `20260412_074237` | Boston Partners merge (eid=17933→9143). $96.58B Q4. 24 rels + 20 rollups re-pointed. |
| **INF4c** | `73f6acd` | `20260412_075814` | Batch merge 96 CRD-format fragmented pairs. 5,888 row ops. 41 DM self-root fixes. |
| **INF4e** | `dba066b` | — | All 4 borderline pairs excluded as CRD pollutions → INF17 Phase 1. |
| **L4-1** | `1e01b6b` | `20260412_085048` | 3 mixed→active (Ameriprise, PIMCO, AMG). 6 LOW_COV kept mixed. |
| **INF17 Phase 1** | `46877c5` | — | Scrub 127 managers rows (crd_number + aum_total → NULL) + 2 Trian parent_name. |
| **INF17b** | `4ff0006` | — | Brand-token overlap gate in `fetch_ncen.py` adviser_cik matching. |

### Production validation after all promotions: 9 PASS / 0 FAIL / 7 MANUAL

---

## Open items — current priority order

### 1. INF17 Phase 4 — Preserve coincidentally-correct rollups

`parent_bridge_sync` manual writes for Carillon→RJF, Nikko→Sumitomo, Martin Currie→Martin Currie Ltd BEFORE any future `build_entities.py --reset` that would break their ADV Schedule A chain (the bad CRDs are now scrubbed from `managers`, so the ADV walk can't re-derive them). Depends on INF9c `preserve_relationship` action. Without Phase 4, these entities lose their correct parent rollup on `--reset`.

### 2. INF9e — entity_overrides_persistent diff/promote/DDL

Extend `diff_staging.py` + `promote_staging.py` + prod DDL so the 24 INF9 Route A staged rows can reach prod. Without this, overrides are staging-local indefinitely.

### 3. INF9a–d — prod `--reset` unblock (4 remaining items)

- **INF9a** — `is_activist` flag (2 rows, Mantle Ridge + Triangle). Schema column + replay extension.
- **INF9b** — `rollup_type` on `merge` for DM12 routings (13 rows).
- **INF9c** — `delete_relationship` action OR parent_bridge verifier (28 L5 deletions). Also needed by INF17 Phase 4.
- **INF9d** — CIK-less entities (4 rows, 3 orphans + 1 CRD-only).

### 4. INF13 part 2 — Snapshot fallback race condition

`_resolve_db_path()` hot-path `shutil.copy2` on live DuckDB file. Part 1 was `refresh_snapshot.sh` fix.

### 5. Amundi → Amundi Taiwan rollup

eid=830 + eid=4248 both roll to `eid=752 Amundi Taiwan Ltd.` via `parent_bridge_sync/manual`. Should roll to global Amundi SA parent. Not CRD-driven — separate manual fix.

### 6. React migration — next tab

Phase 2 complete (Register + Ownership Trend + Conviction). Pick next tab to port. See `REACT_MIGRATION.md`.

---

## Critical gotchas — discovered the hard way

### a–e: Flask, IIFEs, switchTab, bandit 1.8.3, nosec B608

Unchanged from prior sessions. See full text in the 87bc812 version of this file.

### f. Data model traps

- **`managers.aum_total`** — 127 rows just scrubbed to NULL in INF17 Phase 1 (`46877c5`). For ALL managers, prefer holdings-derived AUM: `SUM(holdings_v2.market_value_usd) WHERE quarter = :q`.
- **`managers.crd_number`** — same 127 rows scrubbed. After INF17 Phase 1, only CRDs that passed the brand-token overlap gate remain.
- **`holdings_v2.cik`** — 10-digit zero-padded. Matches `entity_identifiers.identifier_value` for `cik` type.
- **`fund_universe.is_actively_managed`** — authoritative active/passive flag. `NULL` = unknown.
- **`entity_relationships`** — 5 types. Exclude `sub_adviser` when walking ownership trees.
- **13F-NT vs 13F-HR** — NT filers have zero `holdings_v2` rows.
- **CRD normalization** — entity resolver strips leading zeros (INF4b). LTRIM lookup handles retroactive matching.

### g–h: React/AG Grid/Tailwind landmines, inline style cascade

10 specific gotchas from TCO port. See full text in the 87bc812 version.

### i. Fuzzy name matching — use brand-token Jaccard, not token_sort_ratio

`fuzz.token_sort_ratio` collapses under shared corporate suffixes. Reference implementation: `build_managers.py` `_BRAND_STOPWORDS` + `_brand_tokens_overlap()`. Now also applied in `fetch_ncen.py` (INF17b `4ff0006`).

### j–k: DuckDB similarity gap + audit query join bug

DuckDB has no pg_trgm `similarity()`. Audit queries must join on (CIK, CRD) pair, not CRD alone.

### l. merge_staging.py — managers uses DROP+CREATE path

Silently drops schema-drifting columns (e.g., `adviser_cik`). "Added 12,005" output is misleading.

### m. sync_staging.py SKIP preserves staging-only tables

`entity_overrides_persistent` (INF9 Route A 24 rows) survives syncs.

### n. `manually_verified=True` is unreliable

4/114 INF17 pollutions + 3/3 INF7 pollutions carried the flag.

### o. 13F-NT filers distort AUM-at-risk estimates

INF17's $180.71B → $1.27B after filtering. Always separate "entities affected" from "holdings at risk".

### p. CRD format normalization (INF4b)

`entity_sync._normalize_crd()` strips leading zeros. 100 entity pairs merged (INF4+INF4d+INF4c), 15 excluded as pollutions (all added to INF17). Code fix prevents new occurrences.

### q. Batch entity merge: always transfer CIK identifiers

Do NOT just close a merge source's CIK — **INSERT a copy on the survivor first**. INF4c hit a 0.457% gap (~$166B) when 12 CIKs were closed without transferring. `total_aum` gate compares `SUM(managers.aum_total)` through the `entity_identifiers → entity_rollup_history` chain — dropped CIKs break the join.

### r. L4-1 LOW_COV: N-PORT coverage < 50% → keep mixed (NEW)

When N-PORT series coverage is below 50% of a firm's total 13F AUM, the active/passive split from N-PORT doesn't represent the whole firm. Goldman Sachs (27%), Franklin Templeton (27%), Nomura (32%), Focus Partners (35%) were all flagged ≥90% active by N-PORT but kept `mixed` because the uncovered AUM (banking, passive ETFs, fixed income) could flip the ratio. Only reclassify to `active`/`passive` when coverage is ≥50% OR the firm is structurally known (e.g., PIMCO = pure bond manager with no 13F).

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: 50c9065 or newer
pgrep -f "scripts/app.py"       # dev server PID
curl -s http://localhost:8001/api/tickers | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"  # 6500+
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/admin/stats  # 503
python3 scripts/validate_entities.py --prod   # 9 PASS / 0 FAIL / 7 MANUAL
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization. `--test` mode only unless user says otherwise.
- Never mutate production data to simulate test conditions. Use flags or parameters.
- Always update `ROADMAP.md` after completing a task — move items to COMPLETED with date and details.
- Entity changes go through the staging workflow (INF1): `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- **Reference-table changes** (like `managers`) go through `merge_staging.py --tables <name>`, NOT `promote_staging.py`.
- Entity overrides: Route A reclassify rows are in staging `entity_overrides_persistent` (24 rows, commit `b53e3fa`) and preserved across sync cycles. Prod `--reset` still wipes anything not covered by INF9a–e.
- Read files **in full** before editing.
- Confirm destructive actions before running.
- Use `python3 -u` for background tasks.
- **Never trust `managers.manually_verified=True`.**
- **Never use `fuzz.token_sort_ratio` alone for firm name matching.** Both `build_managers.py` and `fetch_ncen.py` now have brand-token gates.
- **CRD values must be normalized** via `_normalize_crd()` before any insert or lookup (INF4b).
- **Batch entity merges: always transfer CIK identifiers** from merge source to survivor before closing them (gotcha q).
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
50c9065 ROADMAP: mark L4-1 Done + INF17 Phase 1 Done + INF17b fully Done
4ff0006 INF17b: add brand-token overlap gate to fetch_ncen.py adviser_cik matching
46877c5 INF17 Phase 1: scrub bad crd_number + aum_total from 127 managers rows
1e01b6b L4-1: reclassify 3 mixed entities to active based on N-PORT series split
dba066b ROADMAP: mark INF4e Done — all 4 excluded as CRD pollutions
436032f docs: update NEXT_SESSION_CONTEXT.md — INF4c gotcha + priority reorder
73f6acd INF4c: batch merge 96 CRD-format fragmented entity pairs
76dc31f ROADMAP: add INF17 Phase 1 additions (11 CRD pollutions) + INF4e (4 borderline pairs)
eddb05c INF4d: merge eid=17933 into eid=9143 — Boston Partners fragmentation
5a1dc66 ROADMAP: clarify INF17b remaining scope + regenerate NEXT_SESSION_CONTEXT.md
903e913 ROADMAP: mark INF4b + INF17b Done
d89e663 INF4b + INF17b: normalize CRD format in entity resolver and fetch_ncen
9b53f9b ROADMAP: add INF4c (115 CRD-fragment batch) + INF4d (Boston Partners priority)
ffa9796 INF8: merge eid=1090 + eid=9075 into eid=107 — Trian Fund Management fragmentation
2130f16 ROADMAP: mark INF6 Done
eaab03b INF6: merge eid=20187 into eid=2273 — Tortoise Capital Advisors fragmentation
58868b6 ROADMAP: mark L4-2 Done
a3c20e8 L4-2: fix 3 classification mismatches vs N-PORT series split
e2d2b30 ROADMAP: mark INF4 Done + add INF4b CRD normalization
ff49dbc INF4: merge eid=17973 into eid=7650 — Loomis Sayles fragmentation
ba4fb89 ROADMAP: mark INF17 Phase 3 Done
0634682 INF17 Phase 3: fix build_managers.py CRD fuzzy-match — add brand-token overlap gate
14f8250 ROADMAP: mark INF17 Phase 2 Done
6743f11 INF17 Phase 2: self-root 5 misattributed entities from CRD pollution audit
1a43376 INF7 Done: Soros/VSS + Peter Soros/Orion fuzzy-match cleanup promoted
c91afd2 ROADMAP: mark INF12 Done
d51db60 INF12: admin Blueprint with token auth — gate all /api/admin/* except quarter_config
b53e3fa INF9 Route A: persist 24 reclassify overrides to staging entity_overrides_persistent
```
