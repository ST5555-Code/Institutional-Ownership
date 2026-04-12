# 13F Ownership — Next Session Context

_Last updated: 2026-04-11 (session end, HEAD: ab199e5)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `ab199e5`
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - Flask — `scripts/app.py` (~1400 lines post-INF12 split) + `scripts/admin_bp.py` (~700 lines, admin Blueprint, gated by `ENABLE_ADMIN` + `ADMIN_TOKEN`, INF12)
  - DuckDB — `data/13f.duckdb` (prod), `data/13f_staging.duckdb` (staging)
  - Vanilla JS — `web/static/app.js` (~5600 lines, tco IIFE removed in React POC)
  - Jinja templates — `web/templates/index.html` (Flask) + `web/templates/admin.html` (admin dashboard, now sends `X-Admin-Token` on every fetch via `adminFetch()` helper)
  - **React POC (live)** — `web/react-src/` (2 Companies Overlap tab, React 18 + TS + Vite + Tailwind v3 + AG Grid v35). Built bundle at `web/static/dist/tco-bundle.{js,css}`, gitignored, loaded as `<script type="module">` from `index.html`. Production-serving today; retires once the full React app cuts over.
  - **React full-app (in progress)** — `web/react-app/` (port 5174) — Phase 1 shell + Phase 2 Register tab complete (20 commits `c38a866`→`ab199e5`). Register tab is fully functional with 12-col fixed layout, collapsible hierarchy, fund view, shared components (QuarterSelector, RollupToggle, ActiveOnlyToggle, InvestorTypeFilter, FundViewToggle, InvestorSearchWithDropdown, ExportBar, TableFooter, ColumnGroupHeader), rollup toggle wired to API. Next: pick second tab to port. See `REACT_MIGRATION.md` at repo root.

---

## First 5 minutes — read these

1. **`~/ClaudeWorkspace/CLAUDE.md`** — workspace rules (folder structure, tone, OneDrive deliverable routing, IB color conventions, EDGAR identity)
2. **`ROADMAP.md`** — full project state. INFRASTRUCTURE table tracks INF1–INF17. COMPLETED section below. 2026-04-11 entries at top.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **`REACT_MIGRATION.md`** — full React app migration plan (parallel work stream, independent of data QC work)
5. **Auto memory** at `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/` persists across sessions

---

## Recent sessions (2026-04-11) — data QC thread

The 2026-04-11 working sessions covered four discrete data-quality items in
sequence: INF12 admin auth, INF9 Route A override persistence, INF7 Soros/VSS
identity resolution, and INF17 systematic managers-CRD pollution audit.

### INF12 — admin Blueprint with token auth (`d51db60`, `c91afd2`) — DONE

- 15 admin routes moved to `scripts/admin_bp.py` under `/api/admin/*`
- `POST /api/add_ticker` renamed to `POST /api/admin/add_ticker` (only caller `admin.html`, updated in same commit)
- `@admin_bp.before_request` token guard: 503 when `ENABLE_ADMIN != 1` or `ADMIN_TOKEN` unset, 403 on missing/wrong `X-Admin-Token` header, `hmac.compare_digest` for timing-safe compare
- `run_pipeline.sh` and `merge_staging.py` dropped from `/api/admin/run_script` whitelist — never web-triggerable
- **Exception:** `/api/admin/quarter_config` stays on main app (public UI loads it every page)
- `admin.html` gained `adminFetch()` helper — prompts for token on first load, stores in `localStorage`, sends `X-Admin-Token` on all 11 admin fetches, clears on 403
- Bind unchanged (`0.0.0.0` for Render) — auth enforced at Blueprint layer
- Smoke-tested: port 8001 (no env) → 503; port 8002 (`ENABLE_ADMIN=1 ADMIN_TOKEN=test123`) → 403 bare / 200 with header
- pre-commit pylint + bandit on `app.py` + `admin_bp.py` clean

### INF9 Route A — 24 reclassify overrides persisted (`b53e3fa`) — DONE

- 24 rows in `data/13f_staging.duckdb` `entity_overrides_persistent` covering Section 3 L4 reclassify fixes (23 `market_maker` + 1 `venture_capital`)
- **Scope narrowed from 39→24** after reading `replay_persistent_overrides()` — only 3 action types supported (`reclassify classification`, `alias_add`, `merge → economic_control_v1`), hard-codes `is_activist=FALSE`
- Staging validation: 9 PASS / 0 FAIL / 7 MANUAL — no regression
- Remaining replayability gaps decomposed into INF9a–e (is_activist flag, rollup_type on merge, delete_relationship, CIK-less entities, staging workflow coverage)
- **Prod `--reset` still blocked** by INF9a–e; staging `--reset` would replay Route A correctly
- **Sync preservation confirmed this session**: `sync_staging.py` SKIPs `entity_overrides_persistent` because it's not in prod — the staging copy is preserved across syncs (earlier warning about "Route A wiped by sync" was wrong; the 24 rows are intact)

### INF7 — eid 2218 Soros/VSS + eid=8443 Peter Soros/Orion (`1a43376`, `59e8a0d`) — DONE

- **Investigation.** Found two independent fuzzy-match pollutions in `managers`:
  1. CIK `0001029160` (real Soros Fund Management, $8.6B Q4 book) was paired with CRD `156600` (VSS FUND MANAGEMENT LLC, unrelated $977M NY firm). `managers.aum_total` = VSS's exact ADV RAUM. The bad CRD walked through VSS's ADV Schedule A on Apr 7 and briefly wired eid=2218 under eid=1630 (Verus Capital Partners) via `wholly_owned` until Apr 10 self-root broke the chain — but the CRD was left behind in `entity_identifiers` and the `managers` row.
  2. CIK `0001748240` (Peter Soros SOROS CAPITAL MANAGEMENT LLC, Coronado CA) was paired with CRD `119428` (ORION CAPITAL MANAGEMENT LLC, also Coronado CA, $256.7M matching exactly). Same city + "Capital Management LLC" name fuzz drove the mispair.
  3. eid=92 was a PARENT_SEEDS brand-parent ghost with zero identifiers, acting as a fuzzy_match rollup target for three Soros-named CIKs with no verified corporate relationship.
- **Option A fix via INF1 staging workflow, 9 edits in one transaction:**
  - (a) Close CRD 156600 on eid=2218 in `entity_identifiers`
  - (b) Close relationship_id=418 (92→8443) in `entity_relationships`
  - (c) Self-root eid=8443 (SOROS CAPITAL MGMT) in both rollup_types
  - (d) Close relationship_id=507 (92→10228) in `entity_relationships`
  - (e) Self-root eid=10228 (SOROS GEORGE individual) in both rollup_types
  - (f) Close both active aliases on eid=92 (brand + filing) — entity row preserved
  - (g) `UPDATE managers SET crd_number=NULL WHERE cik='0001029160'` (scrub VSS CRD at source)
  - (h) `UPDATE managers SET parent_name=NULL WHERE cik='0001748240'` (kill fuzzy_match path)
  - (h-bis) `UPDATE managers SET crd_number=NULL WHERE cik='0001748240'` (scrub Orion CRD at source)
- **Workflow results:** diff_staging.py → 9 line-level changes; validate --staging → 9/0/7; promote_staging.py --approved → snapshot `20260411_180047` + 13 row-level changes + auto-validation green; merge_staging.py --tables managers → prod rebuilt via DROP+CREATE (12,005 rows, 15 cols); final prod validate → 9/0/7
- **Follow-ups deferred to INF16:** recompute `managers.aum_total` for both CIKs (VSS's $977M and Orion's $257M still on the rows but no longer feeding downstream since CRDs are broken)
- **Rollback path:** `python3 scripts/promote_staging.py --rollback 20260411_180047`

### INF17 — systematic managers CRD pollution audit (`41f9a8c`, `95b30bd`, `17265a8`) — AUDITED + SCOPED, NOT YET EXECUTED

- **INF7 was not a one-off.** Ran a full audit on `managers ⋈ adv_managers` and found **127 name-mismatch rows (8.4% of CRD-linked rows) = 114 unique (cik, crd) pairs after dedup**. **All 114 also have `managers.aum_total` exactly equal to the wrong `adv_managers.adv_5f_raum`** — confirms mechanical upstream bug, not manual entry error.
- **Root cause located:** `scripts/build_managers.py:270-292` → `link_cik_to_crd()` uses `rapidfuzz.fuzz.token_sort_ratio` with `score_cutoff=85`. Token-sort-ratio gives high scores to pairs sharing corporate-suffix tokens ("Financial LLC", "Capital Management LLC") even when distinguishing brand words differ completely. Phase 2 of `build_managers_table()` then copies `a.adv_5f_raum as aum_total` via LEFT JOIN on the bad CRD (line 377). Secondary contaminator: `fetch_ncen.py:328` same `>=85` threshold on `token_sort_ratio` for the `adviser_cik` column (staging-only, not in prod).
- **Downstream propagation:** all 114 bad CRDs landed on `entity_identifiers` with `source='managers'` (100% propagation). 16 entities have active non-self rollups (11 via `wholly_owned`/`ADV_SCHEDULE_A`, 3 via `fund_sponsor`/`N-CEN`, 2 via `orphan_scan`, 3 via `parent_bridge_sync`/`manual`).
- **Per-entity verification (16 entities classified):**
  - **4 spot-checked** (Geode, Carillon, Nikko Japan, Nikko Europe): all coincidentally or legitimately correct rollup targets — the bad CRDs walked through ADV Schedule A to parents that happen to be (or are) the real corporate parent. All 4 were 13F-NT filers with $0 holdings.
  - **12 batch-verified**: 5 WRONG (7G, Capital Insight, Compton Financial, IFS Advisors, Scion Capital Group), 4 LEGIT (AEW, Martin Currie, Centre, Baird), 2 ODD TARGET (Amundi US/Asset Management both rolling to Amundi Taiwan via parent_bridge_sync/manual — unrelated to CRD pollution, separate concern), 1 NOT POLLUTED (IMA Advisory Services — Step 2 audit over-flagged because it joined on CRD alone).
- **True AUM at risk: ~$1.27B** (not the Step 2 estimate of $180.71B — inflated by 13F-NT filers and coincidentally-correct rollups). Breakdown: 7G Capital $161M + Capital Insight $473M + Compton Financial $442M + IFS Advisors $192M + Scion $0.
- **Four-phase cleanup plan** documented in ROADMAP INF17:
  - **Phase 1** — scrub bad CRDs from `managers.crd_number` + `aum_total` for all ~114 affected CIKs (reference-table only, flows through `merge_staging.py --tables managers`)
  - **Phase 2** — targeted 5-entity fix: self-root eid=2195, eid=6285, eid=7606, eid=10514, eid=6267 + scrub their CRDs via INF1 staging workflow
  - **Phase 3** — upstream fix in `build_managers.py:276`: replace `fuzz.token_sort_ratio` + `score_cutoff=85` with stopword-aware brand-token matcher (the exact heuristic the audit used — cleanly separated 2/2 known bad from 8/8 good) OR raise threshold to 95+ with city+state secondary verification. Also fix `fetch_ncen.py:328`.
  - **Phase 4** — preserve coincidentally-correct rollups via `parent_bridge_sync` manual writes BEFORE scrubbing their CRDs (else the ADV Schedule A chain that currently lands at the right parent breaks on `--reset`). Depends on INF9c's `preserve_relationship` action.

---

## Critical gotchas — discovered the hard way

### a. Flask template cache

`app.py` runs with `debug=False`. Jinja does **NOT** auto-reload templates in production mode. Every `web/templates/index.html` change requires a full Flask server restart:

```bash
kill $(pgrep -f "scripts/app.py")
cd ~/ClaudeWorkspace/Projects/13f-ownership
python3 scripts/app.py --port 8001
```

`web/static/app.js` and `web/static/style.css` are served fresh by Flask's static handler on every request — just hard-reload the browser (`Cmd+Shift+R` / `Cmd+Opt+R` in Safari).

### b. Two IIFEs fight over `results-area`

The Entity Graph and 2 Companies Overlap IIFEs both attach parallel click listeners to every `.tab` element and both toggle `results-area.style.display`. Whichever listener runs **last** wins.

**Solution: use the `.hidden` CSS class** (`display:none !important`) instead of inline `style.display` in the tco IIFE. The class can't be overridden by inline-style clearing. The Entity Graph IIFE still uses inline style — if you add a third IIFE, match the tco pattern.

See `ba8bfd0` for the commit that fixed this after a confusing diagnostic session where `results-area` kept reappearing when the tco tab was active.

### c. New tabs go through `switchTab()`

`app.js` L365 dispatches tabs via an `else if (tabId === ...)` chain. A new tab branch should:

1. Call `window.loadXxx()` published from an IIFE at the bottom of `app.js`
2. Hide `results-area` via `classList.add('hidden')` (NOT inline style)
3. The top-of-`switchTab` guard already calls `_tcoDeactivate()` for non-tco tabs — mirror that pattern for your new IIFE so switching away from your new tab restores the previous panel

### d. Pre-commit bandit 1.8.3 quirk

Multi-code nosec like `# nosec B607,B603` only suppresses the **last** code in bandit 1.8.3 (the pre-commit pinned version). Upstream bandit 1.8.6+ parses correctly. For multi-issue lines under the 1.8.3 pin, use bare `# nosec` with a trailing comment naming the codes:

```python
ps = subprocess.run(['pgrep', '-f', script], ..., check=False)  # nosec  # B607 + B603 — known partial-path subprocess
```

### e. `# nosec B608` in `app.py` is dead code

The pre-commit config has `args: [-r, "--skip=B101,B608"]` — B608 is globally skipped at the hook level. Source annotations are defensive docs only. **But never put them on a `con.execute(f"""` line** — they end up inside the SQL string and DuckDB errors on `#`.

The correct pattern for B608 annotation in app.py (Variant B, empirically derived):

```python
df = con.execute(
    f""  # nosec B608
    f"""
    SELECT ticker, ...
    WHERE quarter = '{LQ}'
    """, [params]
).fetchdf()
```

The empty `f""` is an implicit-concat anchor on a physical line bandit recognizes for the nosec suppression; Python compiles `f"" + f"""..."""` into a single f-string identical to the original.

### f. Data model traps

- **`managers.aum` does not exist.** Columns are `aum_total` and `aum_discretionary` (ADV Part 1A sources, ~1,500 managers covered). **Warning:** ~114 `managers.aum_total` values are currently polluted — they're copied directly from the wrong `adv_managers.adv_5f_raum` by the `build_managers.py` fuzzy matcher (see INF17). For any visualization, prefer holdings-derived AUM: `SUM(holdings_v2.market_value_usd) WHERE quarter = :q`
- **`holdings_v2.cik`** stores 10-digit zero-padded format (`0000102909`). `entity_identifiers.identifier_value` for `identifier_type='cik'` matches exactly.
- **`fund_universe.is_actively_managed`** is the authoritative active/passive flag for fund series. `NULL` = fund not in universe (treat as unknown — the 2 Companies Overlap active filter keeps NULL funds visible).
- **`fund_holdings_v2.market_value_usd`** is the column name; there is no `market_value`. Old `fund_holdings` table also exists but the app uses v2 throughout.
- **`entity_relationships`** has 5 types: `fund_sponsor` (most common), `sub_adviser`, `wholly_owned`, `mutual_structure`, `parent_brand`. Exclude `sub_adviser` when walking descendants for ownership trees — it's a decision-maker relationship, not a containment one.
- **Parents are self-rollup:** `entity_current WHERE entity_id = rollup_entity_id` (10,935 rows). Non-parent entities have `rollup_entity_id` pointing to their canonical parent.
- **13F-NT vs 13F-HR filings.** 13F-HR (Holdings Report) has the actual positions; 13F-NT (Notice) is a cross-reference filing that says "another entity reports my holdings". A CIK that files 13F-NT will have **zero rows** in `holdings_v2`. Many of the INF17 polluted entities are 13F-NT filers (Geode Holdings, Carillon, Nikko group, Baird Financial Corp) — the real holdings live under a sibling CIK. Don't assume a "real firm with big brand name" has holdings under its obvious CIK.

### g. React + AG Grid + Tailwind landmines (discovered during TCO port)

All of these cost at least one diagnostic round-trip during the React port. Copy the fixes verbatim into any new React app (`web/react-app/` Phase 1 especially).

1. **AG Grid v32+ dropped community module auto-registration.** Without `ModuleRegistry.registerModules([AllCommunityModule])` at the bundle boundary (top of `main.tsx`), the grid renders headers only, no rows. Symptom: tab mounts, no error, no data. Fix is one line in `main.tsx`, but you MUST remember to do it.

2. **AG Grid v33+ Theming API conflicts with legacy CSS imports.** If you import `ag-grid-community/styles/ag-grid.css` and `ag-theme-alpine.css`, you MUST pass `theme="legacy"` as a prop on every `<AgGridReact>`. Without it the grid errors code 240 ("themeQuartz default with ag-grid.css included") and may refuse to commit rows.

3. **AG Grid React wrapper treats function cellRenderers as React components.** Returning an `HTMLElement` from a cellRenderer throws "Objects are not valid as a React child" and crashes the whole subtree. For bold pinned-row text, return JSX `<span style={{fontWeight:600}}>{v}</span>` — NOT `document.createElement('span')`.

4. **AG Grid row class rules alpha stacking.** If both `.tco-overlap-row` AND `.tco-overlap-row .ag-cell` set a semi-transparent background, cells get double alpha (0.18 + 0.18 ≈ 0.33) while row-only areas stay at 0.18. Fix: row-only selector, no cell-level rule.

5. **Tailwind v4 default drops `init -p`.** `npm install -D tailwindcss` pulls v4 by default. Pin to v3 explicitly: `tailwindcss@^3`.

6. **Tailwind Preflight leaks globally.** `input { color: inherit }` made the main `#ticker-input` text invisible against the white header background. Fix: `corePlugins: { preflight: false }` in `tailwind.config.js`.

7. **Never `innerHTML = ''` a React-controlled mount element.** React 18's reconciler corrupts silently when the DOM it thinks it owns is cleared externally. Fix: hide via `classList.add('hidden')` only; let React keep managing its subtree.

8. **Module script tags are deferred — race against tab clicks.** Stash current ticker on `window.__tcoPendingTicker` from `switchTab` when `tcoActivate` is not yet defined, and have `main.tsx` auto-mount read/clear it.

9. **AG Grid internal scroll viewports.** Use `domLayout="autoHeight"` + `suppressHorizontalScroll={true}` to eliminate phantom scrollbar tracks.

10. **AG Grid spacer columns inherit theme background in headers.** Add `headerClass: 'tco-spacer-header'` with a transparent override.

### h. Inline style vs !important cascade

Inline styles (via `style={...}` or `element.style.X`) normally beat CSS rules. But `!important` CSS beats non-important inline styles. So `.tco-overlap-row .ag-cell { background-color: X !important }` WILL override the spacer's inline `backgroundColor: 'transparent'`.

### i. Fuzzy name matching landmines (discovered INF7/INF17)

**Never use `rapidfuzz.fuzz.token_sort_ratio` with a threshold < 95 on firm names** and never use it alone. Token-sort-ratio gives high scores to pairs that share corporate-suffix tokens ("Financial LLC", "Capital Management LLC", "Asset Management"), so "SWP FINANCIAL LLC" vs "LPL FINANCIAL LLC" scores ~94 even though they're completely different firms. Same failure mode as pg_trgm `similarity()` and `jaro_winkler_similarity` — all character-level metrics collapse under shared corporate suffixes.

**What works: token-set Jaccard on brand words after stopword removal.** Strip dots, lowercase, split on non-alphanumeric, drop tokens shorter than 2 chars AND drop common corporate stopwords (`llc`, `lp`, `inc`, `fund`, `funds`, `capital`, `management`, `mgmt`, `advisors`, `advisers`, `advisory`, `asset`, `investment`, `investments`, `partners`, `holdings`, `group`, `financial`, `the`, `and`, `of`, `trust`, `securities`, `global`, `international`, `research`, `services`). Then match if any brand tokens overlap OR if one side's concatenated brand tokens is a substring of the other side's (handles "JPMorgan" ↔ "J.P. Morgan" → "jp"+"morgan"="jpmorgan" case). Anything else = mismatch. Verified on 13 calibration pairs: 2/2 known bad, 8/8 known good, 2/2 obvious nonmatch.

This is the fix path for INF17 Phase 3 (`build_managers.py:276`) and also for the staging-only `fetch_ncen.py:328` adviser_cik matching.

### j. DuckDB similarity function gap

DuckDB does NOT have PostgreSQL's pg_trgm `similarity()` function. It has `jaro_winkler_similarity`, `jaro_similarity`, `jaccard`, `levenshtein`, `damerau_levenshtein`, `hamming` — but for **firm name matching, none of them work** (calibrated on SOROS/VSS and Peter Soros/Orion — all five metrics put the bad pairs at scores HIGHER than legitimate same-firm pairs).

If you need firm name similarity in a SQL query:
- Accept that you'll need to pull into Python and use a custom matcher
- OR run `jaccard` as a first-pass filter and post-process in Python
- OR raise the threshold to 0.95+ on `jaro_winkler_similarity` AND require city+state match

### k. Audit query join bug — CRD-only vs (CIK, CRD) pair

When auditing `entity_identifiers` for downstream impact of a polluted `managers` row, **JOIN on the `(cik, crd)` PAIR, not on `crd` alone.** A polluted CRD can legitimately appear on another entity (the real owner); a CRD-only join over-flags that legitimate owner.

Example from this session: CRD `112091` was polluted onto CIK `0001303042` (Avantax) by the fuzzy matcher, but it's ALSO legitimately owned by CIK `0001455495` (IMA Advisory Services, eid=3559). My Step 2 downstream query joined on CRD alone, flagging eid=3559 as polluted when it wasn't. The correct join predicate is:

```sql
JOIN bad_pairs bp
  ON ei.identifier_value = bp.crd
  AND (SELECT identifier_value FROM entity_identifiers WHERE entity_id = ei.entity_id AND identifier_type = 'cik' AND valid_to = DATE '9999-12-31') = bp.cik
```

Or resolve via `managers` in the bad_pairs source:

```sql
JOIN bad_pairs bp ON ei.identifier_value = bp.crd
JOIN managers m ON m.cik = bp.cik AND m.crd_number = bp.crd
```

### l. merge_staging.py semantics — TABLE_KEYS vs DROP+CREATE

`scripts/merge_staging.py` has two code paths selected by `TABLE_KEYS`:

1. **PK-based upsert** (tables in `TABLE_KEYS` with non-None pk_cols): DELETE by PK then INSERT, preserves all other rows
2. **Full replacement (DROP+CREATE)** for tables NOT in `TABLE_KEYS` OR with `pk_cols=None`: drops the prod table, recreates via `CREATE TABLE AS SELECT FROM staging_db.X`

**The `managers` table uses the DROP+CREATE path.** This has two consequences:
- Any column in staging that doesn't exist in prod is **silently dropped** (e.g., staging `managers` has an `adviser_cik` column from `fetch_ncen.py` that prod doesn't have — gone after merge). Flagged for separate review.
- Any column in prod that doesn't exist in staging is also lost. Happens to be none right now but could bite later.

When planning a `merge_staging.py --tables managers` run, be aware that ALL 12,005 rows flow staging→prod, not just the changed ones. The warning output "Added 12,005, Replaced 0" is misleading — it reports prod_count_before (post-DROP, 0) + new rows, not "12,005 new rows were inserted on top of existing data".

### m. sync_staging.py SKIP preserves staging-only tables

`scripts/sync_staging.py` SKIPs tables that don't exist in prod — the log line "`SKIP entity_overrides_persistent: not present in prod (staging copy left empty)`" plus the subsequent "`+ entity_overrides_persistent: created empty in staging`" is **misleading**. The first line means "I'm leaving staging alone because there's no prod source to copy from"; the second line means "I created the column definition if it didn't exist, currently empty OR with whatever staging already had". The INF9 Route A 24 rows are preserved across sync cycles. My earlier worry (Apr 11 INF7 session) that sync would wipe Route A was wrong.

### n. `manually_verified=True` flag in managers is unreliable

`managers.manually_verified` is set by `build_managers.py` based on a match between a seeded parent and the fuzzy matcher's output. It does NOT mean "a human eyeballed this row". **4 of the 114 INF17-polluted rows carry `manually_verified=True`** (Carillon Tower/Raymond James IM, Scion Capital/Siris Capital, Geode Capital Holdings/GPB Capital Holdings, Baird Financial Corp/Birks Financial Corp). INF7 hit 3 `manually_verified=True` rows too. Do NOT use this flag as protection when cleaning up `managers` — reset it to FALSE during any Phase 1 scrub.

### o. 13F-NT filers distort "AUM at risk" estimates

When a CIK files 13F-NT (Notice), it has zero rows in `holdings_v2`. Any aggregate query like "total holdings attributed to entities with a bad CRD" will vastly overcount if it doesn't filter to 13F-HR filers first. Step 2 of the INF17 audit produced a "$180.71B at risk" figure that dropped to **~$1.27B** after filtering to entities with non-zero Q4 holdings. **When reporting scope of a data quality issue, always separate "entities affected" from "entities with actual holdings at risk".**

---

## Open items you might pick up

### Next direction — INF17 Phase 1 → Phase 2 → Phase 3

**Primary next-session data-QC goal.** INF17 is scoped and ready to execute. Order of operations:

1. **Phase 1 — blanket scrub** of ~114 `managers` rows (reference-table only, no entity-layer touch). `UPDATE managers SET crd_number=NULL, aum_total=NULL WHERE cik IN (114 CIKs)`. Flows through `merge_staging.py --tables managers`. Also reset `manually_verified=FALSE` on affected rows (the flag is unreliable).
2. **Phase 2 — targeted 5-entity fix:** self-root eid=2195 (7G Capital $161M), eid=6285 (Capital Insight $473M), eid=7606 (Compton Financial $442M), eid=10514 (IFS Advisors $192M), eid=6267 (Scion Capital $0 but visible embarrassment). Plus close their bad CRD rows in `entity_identifiers`. Flows through INF1 staging workflow — same pattern as INF7 (9 edits in one transaction).
3. **Phase 3 — upstream fix in `build_managers.py:276`.** Replace `fuzz.token_sort_ratio` + `score_cutoff=85` with the stopword-aware brand-token matcher (heuristic in gotcha `i`). Also fix `fetch_ncen.py:328`. Without Phase 3, any `build_entities.py --reset` re-introduces the entire pollution.
4. **Phase 4 — rollup preservation** via `parent_bridge_sync` manual writes for coincidentally-correct entities (Carillon→Raymond James Financial, Nikko→Sumitomo, Martin Currie→Martin Currie Ltd). Depends on INF9c `preserve_relationship` action — can defer unless Phase 3 is about to ship.

After INF17 Phases 1-3, attention shifts to **INF4 Loomis Sayles** (highest dollar fragmentation cleanup, $246.9B), then **L4-2** (3 parents with N-PORT vs classification mismatch — Invesco, Nuveen/TIAA, Security Investors), then **INF6 Tortoise** and **INF8 Trian** (smaller INF4-style consolidations).

### Parallel direction — React full-app migration

**Independent work stream.** Read `REACT_MIGRATION.md` at repo root. Phase 1 (scaffold + shell) and Phase 2 (Register tab + shared components) both complete. Register tab is the first fully-ported tab with all controls wired. 20 commits total from `c38a866` through `ab199e5` covering: doc fix (React 18→19), scaffold, types + Zustand store, global styles, shell components, tab placeholders, main.tsx, Recharts, endpoint type audit (`api.ts`), rollupType in store, 9 shared components, Register initial build, Register polish (shared components + sticky footer + fund view + export + investor search dropdown), column alignment fixes (table-layout: fixed + colgroup + gap columns), Port. Coverage rename + badge + tooltip, spellcheck disable on all inputs.

Existing Flask app at `:8001` stays untouched through the migration. Cut over happens in a separate commit at the end (all 11 tabs migrated): one-line change in `scripts/app.py` to serve `web/react-app/dist/index.html` instead of `web/templates/index.html`. Revertable in 30 seconds.

**Nav structure:**
- Overall Market: Sector Rotation, Entity Graph
- Ownership: Register, Ownership Trend, Conviction, Fund Portfolio
- Flow & Rotation: Flow Analysis, Peer Rotation
- Investor Targeting: Cross-Ownership, Overlap Analysis, Short Interest

**Color scheme:** dark navy shell + light content. Shell `#0a0f1e`, sidebar `#0d1526` (active `#1a2a4a`), accent gold `#f5a623`, content `#f4f6f9`, cards `#ffffff`. Oxford Blue `#002147` and Glacier Blue `#4A90D9` retained for legacy.

**Deferred React items:** Playwright visual regression (add at 3+ tabs), `/api/admin/*` token handling in React fetch layer (server-side done in INF12; client-side helper still needs porting from `adminFetch()`), activist flag red highlight on Register + Conviction rows, Short Interest tab content.

### UI tweaks still pending

- 2 Companies Overlap tfoot still labels "Top 15 Total" even when Active-only drops the visible count below 15. ~2-line fix to adapt the label dynamically.

### Known preexisting bugs

- ~~**INF7 — eid 2218 Soros/VSS.**~~ **DONE** (`1a43376`, snapshot `20260411_180047`). Full close-out in ROADMAP.
- ~~**INF12 — admin auth gate.**~~ **DONE** (`d51db60`, `c91afd2`).
- **INF17 — systematic managers CRD pollution.** Scoped, audited, Phase 2 fix list documented. Phases 1-3 are the top data-QC priority for the next session.
- **INF13 part 2.** Snapshot fallback in `_resolve_db_path` uses `shutil.copy2` on live DuckDB file → race with concurrent writes. Part 1 was the `refresh_snapshot.sh` fix (`d0677b1`); part 2 for the hot-path `app.py` fallback still pending.
- **INF4 Loomis Sayles fragmentation.** eid=17973 vs eid=7650, $246.9B, highest-dollar cleanup on the entity-fragmentation list.
- **INF6 Tortoise Capital.** eid=2273 vs eid=20187, $14.8B, simple INF4-style consolidation.
- **INF8 Trian Fund Management.** eid=107 vs eid=1090 vs eid=9075, $5.33B, INF4 pattern.
- **INF9 / 9a / 9b / 9c / 9d / 9e — prod `--reset` still blocked.** Route A landed (`b53e3fa`), 24 rows in staging. Five follow-ups gate a full prod `--reset`:
  - **INF9a** — `is_activist` flag (2 Apr-10 rows, Mantle Ridge + Triangle). Schema column + replay extension.
  - **INF9b** — `rollup_type` on `merge` so DM12 routings can target `decision_maker_v1` (13 rows).
  - **INF9c** — `delete_relationship` action OR parent_bridge verifier (28 L5 deletions, parent_bridge subset). Also needed by INF17 Phase 4.
  - **INF9d** — replace `entity_cik` with `(identifier_type, identifier_value)` pair for CIK-less entities (4 rows, 3 orphans + 1 CRD-only).
  - **INF9e** — extend `diff_staging.py` + `promote_staging.py` + prod DDL so the 24 staged rows can reach prod.
- **INF16 — aum_total recompute for two Soros CIKs.** Low priority follow-up to INF7. Likely subsumed by INF17 Phase 1 (blanket `aum_total=NULL` covers these two CIKs too).

### Data quality follow-ups

- **L4-1.** 1,037 entities in `mixed` classification — ~10-30 are probably pure asset managers misclassified (Franklin Templeton, PIMCO, Nomura confirmed; 11 have ≥3 N-PORT series children = highest-priority review batch).
- **L4-2.** 3 parents with classification contradicting N-PORT series child split: Invesco ($352.5B, classified passive, 96.7% active), Nuveen/TIAA ($292.2B, classified passive, 90.1% active), Security Investors LLC ($6.9B, classified active, 80.9% passive). 3 surgical `reclassify` overrides — smallest-effort, biggest-AUM classification fix available.
- **Amundi → Amundi Taiwan rollup** (eid=830 + eid=4248, flagged during INF17 Phase 2 batch verification). Both Amundi US and Amundi Asset Management roll to `eid=752 Amundi Taiwan Ltd.` via `parent_bridge_sync/manual`. Should roll to global Amundi SA parent, not Taiwan regional. Separate item, not part of INF17 since rule is manual, not CRD-driven.
- **20 "unknown" rows from INF17 audit** — audit heuristic couldn't evaluate them because one side had zero brand tokens after stopword removal (e.g., "Financial Management Company"). Separate sweep required.

### Verification tasks

- Spot-check other admin/F6 data-quality endpoints with curl to confirm no other silent 500s survive the B608 fix. The 26 affected endpoints from `794c81e` are now known; anything else returning 500 is a different bug.

---

## Sanity checklist (run before touching code)

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership

# 1. Branch state clean?
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: 17265a8 at top or newer

# 2. Dev server running?
pgrep -f "scripts/app.py"       # returns PID if up

# 3. Autocomplete root endpoint works?
curl -s http://localhost:8001/api/tickers \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"
# expect: 6500+

# 4. Admin auth gate works? (should return 503 when env vars unset)
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/admin/stats
# expect: 503 (or 403 if user has ENABLE_ADMIN=1 set without header)

# 5. Pre-commit still clean?
pre-commit run pylint --files scripts/app.py scripts/queries.py scripts/admin_bp.py
pre-commit run bandit --files scripts/app.py scripts/queries.py scripts/admin_bp.py

# 6. Production validation still green?
python3 scripts/validate_entities.py --prod   # expect: 9 PASS / 0 FAIL / 7 MANUAL
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization. `--test` mode only unless user says otherwise.
- Never mutate production data to simulate test conditions. Use flags or parameters.
- Always update `ROADMAP.md` after completing a task — move items to COMPLETED with date and details.
- Entity changes go through the staging workflow (INF1): `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- **Reference-table changes** (like `managers`) go through `merge_staging.py --tables <name>`, NOT `promote_staging.py`. Two distinct promotion paths.
- Entity overrides: Route A reclassify rows are in staging `entity_overrides_persistent` (24 rows, commit `b53e3fa`) and preserved across sync cycles. Five categories are still NOT persisted — see INF9a–e. A **prod** `--reset` still wipes anything not covered. A **staging** `--reset` would replay Route A correctly.
- Read files **in full** before editing — no partial reads on first touch of a file you intend to modify.
- Confirm destructive actions before running (kill, `rm`, `git reset --hard`, db mutations).
- Use `python3 -u` for background tasks — `print()` fully buffers when redirected.
- **Never trust `managers.manually_verified=True` as data integrity protection** — 4 of 114 INF17 pollutions and 3 of 3 INF7 pollutions carried the flag.
- **Never use `fuzz.token_sort_ratio` or `jaro_winkler_similarity` alone for firm name matching** — both collapse under shared corporate suffixes. See gotcha `i`.

---

## User collaboration preferences

- **Terse, direct communication.** Match the user's pace. No consultant-speak, no preambles, lead with the answer.
- **Quick fixes preferred** over comprehensive refactors unless explicitly asked.
- User often tests in **Safari**, sometimes Chrome. Cross-browser rendering differences matter (especially sticky headers, f-string edge cases, subpixel borders).
- User will paste DevTools Console output when asked — prepare **one tight diagnostic command** rather than multiple.
- User runs the Flask dev server on port 8001 manually. If they need to run a shell command themselves, suggest they type `! <cmd>` in the prompt.
- **Flag duplicate ROADMAP items** before adding — check existing rows.
- **Don't delete** files, data, or rows without explicit confirmation. State what will be deleted and wait for a clear yes.
- When doing data-QC work, **report scope precisely** — "entities affected" ≠ "entities with holdings at risk" ≠ "dollars at risk". The INF17 audit's initial "$180.71B" estimate dropped to ~$1.27B after proper filtering; user values honest scope revisions.

---

## Session ledger (newest first — 2026-04-11 working sessions)

```
ab199e5 Phase 2: disable spellcheck/autocorrect on all search inputs
039c259 Phase 2: Register — insert two 120px gap columns (after Type, after %Float)
32ba627 Phase 2: Register — Institution 440, numeric cols uniform 120, horizontal scroll fallback
dd5a53a Phase 2: Register — pin Institution column to 220px via trailing spacer col
10a1959 Phase 2: Register — table-layout: fixed + colgroup to stop Fund view column drift
6364c3c Phase 2: Register fixes — fund view columns, Port. Coverage label, fixed badge width, coverage tooltip
281cd82 Phase 2: Register polish — dark thead, child ranks 1-N, fund view columns fixed, investor search dropdown
bf81ca0 Phase 2: Register tab polish — shared components, sticky footer, fund view, export, investor controls
789aa11 Phase 2: fix TableFooter — sticky bottom, same font size as body, dynamic totalColumns
14525c3 Phase 2: shared components — 9 shared components in src/components/common/
6ea9fa5 Phase 2 infra: add rollupType to Zustand store
596dee2 Phase 2: Register tab — top 25 holders, collapsible hierarchy, type badges, N-PORT coverage
1ee3f35 ROADMAP: log query7 f-string bug — Fund Portfolio 404
f15ea16 Phase 2 infra: endpoint type audit — api.ts with interfaces for all 11 tabs
a933778 Phase 2 infra: add Recharts
8763d56 Phase 1: sidebar section labels gold, rename section, push nav down
be08feb Phase 1 complete: React shell live on port 5174
e4dbfaf Phase 1 Step 7: fix CompanyData field names to match /api/summary
c38a866 REACT_MIGRATION.md: correct React version 18 → 19
ba4fb89 ROADMAP: mark INF17 Phase 3 Done
0634682 INF17 Phase 3: fix build_managers.py CRD fuzzy-match — add brand-token overlap gate
14f8250 ROADMAP: mark INF17 Phase 2 Done
6743f11 INF17 Phase 2: self-root 5 misattributed entities from CRD pollution audit
87bc812 docs: regenerate NEXT_SESSION_CONTEXT.md post-session
17265a8 ROADMAP: update INF17 Phase 2 with concrete 5-entity fix list
95b30bd ROADMAP: update INF17 with revised four-phase plan
41f9a8c ROADMAP: add INF17 — systematic managers CRD pollution (127 rows)
59e8a0d ROADMAP: add INF7 aum_total follow-up
1a43376 INF7 Done: Soros/VSS + Peter Soros/Orion fuzzy-match cleanup promoted
bf81ca0 Phase 2: Register tab polish — shared components, sticky footer, fund view, export, investor controls
789aa11 Phase 2: fix TableFooter — sticky bottom, same font size as body, dynamic totalColumns
14525c3 Phase 2: shared components — QuarterSelector, RollupToggle, ActiveOnlyToggle, InvestorTypeFilter, FundViewToggle, InvestorSearch, ExportBar, TableFooter, ColumnGroupHeader
6ea9fa5 Phase 2 infra: add rollupType to Zustand store
596dee2 Phase 2: Register tab — top 25 holders, collapsible hierarchy, type badges, N-PORT coverage
1ee3f35 ROADMAP: log query7 f-string bug — Fund Portfolio 404
f15ea16 Phase 2 infra: endpoint type audit — api.ts with interfaces for all 11 tabs
a933778 Phase 2 infra: add Recharts
8763d56 Phase 1: sidebar section labels gold, rename section, push nav down
be08feb Phase 1 complete: React shell live on port 5174
e4dbfaf Phase 1 Step 7: fix CompanyData field names to match /api/summary
680549c ROADMAP: add 2026-04-11 2 Companies Overlap React port entry
ce2a356 2 Companies Overlap: fix R1-R4 (overlap highlight, rank, summary cards)
013cf3b 2 Companies Overlap: wider % and $ columns + bidirectional cohort math
39c9bb9 2 Companies Overlap: kill scrollbars, fix overlap strip, fix cohort math
c91afd2 ROADMAP: mark INF12 Done
d51db60 INF12: admin Blueprint with token auth — gate all /api/admin/* except quarter_config
64e4692 2 Companies Overlap: fixed-basis panels + drop duplicate group header border
a5c3b99 2 Companies Overlap: widths, height, gap, summary, overlap, group header
5303b0f 2 Companies Overlap: new column widths + pinned-row overlap exclusion
59410e7 2 Companies Overlap: locked width spec, Active Only, summary card
b53e3fa INF9 Route A: persist 24 reclassify overrides to staging entity_overrides_persistent
292feba ROADMAP: add 2026-04-11 session entries
a841ddb Close INF15 + add /api/tickers smoke-test marker
794c81e Fix B608 nosec placement — 26 endpoints returning HTTP 500
f272570 INF14: clear pylint/bandit wall on app.py and queries.py
5942449 Add 2 Companies Overlap tab — institutional and fund-level holder comparison
9080885 Add /api/entity_resolve endpoint — resolve any entity_id to canonical institution root
a028153 Add Entity Graph tab (vis.js) — institution/filer/fund hierarchy with sub-adviser edges
```
