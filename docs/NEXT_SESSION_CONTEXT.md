# 13F Ownership — Next Session Context

_Last updated: 2026-04-12 (session end, HEAD: 903e913)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `73f6acd`
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
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF17b. COMPLETED section at line ~233+.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — React app migration plan
5. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`

---

## Items completed this session (2026-04-11 + 2026-04-12)

### Data QC completed

| Item | Commit | Snapshot | Summary |
|---|---|---|---|
| **INF12** | `d51db60` | — | Admin Blueprint with token auth. 15 routes gated, `hmac.compare_digest`. |
| **INF7** | `1a43376` | `20260411_180047` | Soros/VSS + Peter Soros/Orion fuzzy-match cleanup. 9 entity edits + 3 managers scrubs. |
| **INF17 Phase 2** | `6743f11` | `20260411_214440` | Self-root 5 misattributed entities ($1.27B corrected). |
| **INF17 Phase 3** | `0634682` | — | Fix `build_managers.py` fuzzy matcher: brand-token overlap gate + rejection log. |
| **INF4** | `ff49dbc` | `20260411_221854` | Loomis Sayles merge (eid=17973→7650). 38 sub_adviser rels + 25 DM rollups transferred, DM self-root fix. |
| **L4-2** | `a3c20e8` | `20260412_061258` | 3 classification mismatches fixed (Invesco/Nuveen/Security Investors → mixed). Geode confirmed passive. |
| **INF6** | `eaab03b` | `20260412_063446` | Tortoise Capital merge (eid=20187→2273). 6 fund_sponsor rels + circular pair closed. |
| **INF8** | `ffa9796` | `20260412_064353` | Trian merge (eid=1090+9075→107). 3 identifiers transferred, 2 rels closed. |
| **INF4b** | `d89e663` | — | CRD normalization in entity resolver: `_normalize_crd()` + LTRIM retroactive lookup. |
| **INF17b** (partial) | `d89e663` | — | CRD normalization in `fetch_ncen.py` adviser_cik. Brand-token gate still remaining. |
| **INF4d** | `eddb05c` | `20260412_074237` | Boston Partners merge (eid=17933→9143). $96.58B Q4. 9 fund_sponsor + 15 sub_adviser rels + 11 DM + 9 EC rollups re-pointed. |
| **INF4c** | `73f6acd` | `20260412_075814` | Batch merge 96 CRD-format fragmented pairs. 5,888 row ops. 41 DM self-root fixes. 15 excluded (11 CRD pollutions → INF17, 4 borderline → INF4e). |

### Production validation after all promotions: 9 PASS / 0 FAIL / 7 MANUAL

---

## Open items — current priority order

### 1. INF4e — 4 borderline pairs investigation

4 pairs excluded from INF4c batch because both entities have holdings but names suggest same firm: CRD 104702 WCM/WIM ($49B), CRD 122997 LongView ($9.6B), CRD 168777 Thrive/Thryve ($0.9B), CRD 309790 Wealth Mgmt Partners ($0.5B). Investigate each, then merge or exclude.

### 2. L4-1 — Mixed classification review (1,037 entities)

Top 11 with ≥3 N-PORT series children are highest-priority review targets. 3 confirmed mis-classified as mixed that should be active (Franklin Templeton, PIMCO, Nomura).

### 3. INF17 Phase 1 — Blanket managers table CRD scrub

`UPDATE managers SET crd_number=NULL, aum_total=NULL WHERE cik IN (~125 CIKs)` — now includes 114 original + 11 INF4c-discovered pollutions. Also reset `manually_verified=FALSE` + scrub 2 Trian parent_name pollutions (Triangle Securities, Iron Triangle). Flows through `merge_staging.py --tables managers`. Subsumes INF16 (Soros aum_total recompute).

### 4. INF17b remaining — Brand-token overlap gate for fetch_ncen.py

CRD normalization done (`d89e663`). The `fuzz.token_sort_ratio ≥ 85` fuzzy match in `fetch_ncen.py:328` still lacks the brand-token overlap check. Same fix pattern as `build_managers.py` Phase 3 (`0634682`). Staging-only column so no prod impact currently.

### 5. INF9e — entity_overrides_persistent diff/promote/DDL

Extend `diff_staging.py` + `promote_staging.py` + prod DDL so the 24 INF9 Route A staged rows can reach prod. Without this, overrides are staging-local indefinitely.

### 6. INF17 Phase 4 — Preserve coincidentally-correct rollups

`parent_bridge_sync` manual writes for Carillon→RJF, Nikko→Sumitomo, Martin Currie→Martin Currie Ltd BEFORE any CRD scrub that would break their ADV Schedule A chain. Depends on INF9c `preserve_relationship` action.

### 7. Other infrastructure

- **INF13 part 2** — snapshot fallback `shutil.copy2` race condition
- **INF9a–d** — prod `--reset` still blocked (is_activist, rollup_type, delete_relationship, CIK-less entities)
- **Amundi → Amundi Taiwan rollup** — eid=830 + eid=4248, separate from CRD pollution

### 8. React migration — next tab

Phase 2 complete (Register + Ownership Trend + Conviction). Pick next tab to port. See `REACT_MIGRATION.md`.

---

## Critical gotchas — discovered the hard way

### a–e: Flask, IIFEs, switchTab, bandit 1.8.3, nosec B608

Unchanged from prior sessions. See gotchas a–e in the previous version of this file.

### f. Data model traps

- **`managers.aum_total`** — ~114 values are INF17-polluted (wrong firm's RAUM). Use `SUM(holdings_v2.market_value_usd)` instead.
- **`holdings_v2.cik`** — 10-digit zero-padded. Matches `entity_identifiers.identifier_value` for `cik` type.
- **`fund_universe.is_actively_managed`** — authoritative active/passive flag. `NULL` = unknown.
- **`entity_relationships`** — 5 types. Exclude `sub_adviser` when walking ownership trees.
- **13F-NT vs 13F-HR** — NT filers have zero `holdings_v2` rows. Don't assume brand-name firms have holdings under their CIK.
- **CRD normalization** — entity resolver now strips leading zeros (INF4b, `d89e663`). Old data has a mix of padded/unpadded; LTRIM lookup handles retroactive matching. New inserts are always unpadded.

### g–h: React/AG Grid/Tailwind landmines, inline style cascade

10 specific gotchas from TCO port. See gotchas g–h in prior version.

### i. Fuzzy name matching — use brand-token Jaccard, not token_sort_ratio

`fuzz.token_sort_ratio` collapses under shared corporate suffixes. Use stopword-aware token-set Jaccard with ≥1 brand token overlap. See `build_managers.py` `_BRAND_STOPWORDS` + `_brand_tokens_overlap()` for the reference implementation.

### j. DuckDB has no pg_trgm similarity()

Use Python-side matching or `jaccard` as first-pass filter.

### k. Audit queries — join on (CIK, CRD) pair, not CRD alone

Over-flags entities that legitimately own a CRD also polluted onto another entity.

### l. merge_staging.py — managers uses DROP+CREATE path

Silently drops schema-drifting columns (e.g., `adviser_cik`). "Added 12,005" output is misleading.

### m. sync_staging.py SKIP preserves staging-only tables

`entity_overrides_persistent` (INF9 Route A 24 rows) survives syncs.

### n. `manually_verified=True` is unreliable

4/114 INF17 pollutions + 3/3 INF7 pollutions carried the flag.

### o. 13F-NT filers distort AUM-at-risk estimates

Always separate "entities affected" from "entities with holdings at risk". INF17's $180.71B → $1.27B after filtering.

### p. CRD format normalization (INF4b)

`entity_sync._normalize_crd()` strips leading zeros. `entity_identifiers` lookup now uses `LTRIM(identifier_value, '0')` for CRD type — retroactively matches old un-normalized data. `build_entities._try_insert()` normalizes before Python dedup dict and SQL INSERT. 214 entity pairs had CRD format mismatches; 96 merged in INF4c batch + 4 in INF4/INF6/INF8/INF4d individual merges = 100 resolved. 15 excluded (11 CRD pollutions, 4 borderline). Code fix prevents new occurrences.

### q. Batch entity merge: always transfer CIK identifiers from merge source to survivor

Do NOT just close a merge source's CIK identifier — **INSERT a copy on the survivor first**, then close the source row. Closing a CIK without transferring breaks the `total_aum` validation gate because `managers.aum_total` is summed through `managers m JOIN entity_identifiers ei ON m.cik = ei.identifier_value JOIN entity_rollup_history erh ON ...` — if the CIK has no active `entity_identifiers` row, that manager's AUM drops out of the join. INF4c batch merge hit a 0.457% gap (~$166B) when 12 CIKs were closed on merge sources that had their own CIKs (the "both entities have CIK" case). Fixed by transferring 12 CIKs to survivors after the main transaction. Same pattern as INF8 Trian where identifiers were explicitly transferred to eid=107.

---

## Sanity checklist

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: 73f6acd or newer
pgrep -f "scripts/app.py"       # dev server PID
curl -s http://localhost:8001/api/tickers | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"  # 6500+
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/admin/stats  # 503
pre-commit run pylint --files scripts/app.py scripts/queries.py scripts/admin_bp.py
pre-commit run bandit --files scripts/app.py scripts/queries.py scripts/admin_bp.py
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
- **Never use `fuzz.token_sort_ratio` alone for firm name matching.**
- **CRD values must be normalized** via `_normalize_crd()` before any insert or lookup (INF4b).
- **Batch entity merges: always transfer CIK identifiers** from merge source to survivor before closing them (gotcha q). Closing without transferring breaks `total_aum` gate.

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
17265a8 ROADMAP: update INF17 Phase 2 with concrete 5-entity fix list
95b30bd ROADMAP: update INF17 with revised four-phase plan
41f9a8c ROADMAP: add INF17 — systematic managers CRD pollution (127 rows)
59e8a0d ROADMAP: add INF7 aum_total follow-up
1a43376 INF7 Done: Soros/VSS + Peter Soros/Orion fuzzy-match cleanup promoted
c91afd2 ROADMAP: mark INF12 Done
d51db60 INF12: admin Blueprint with token auth — gate all /api/admin/* except quarter_config
b53e3fa INF9 Route A: persist 24 reclassify overrides to staging entity_overrides_persistent
```
