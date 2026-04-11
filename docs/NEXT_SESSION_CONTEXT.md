# 13F Ownership — Next Session Context

_Last updated: 2026-04-11 (session end, HEAD: a0f26c1)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `a0f26c1`
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - Flask — `scripts/app.py` (2000+ lines) + `scripts/admin_bp.py` (admin Blueprint, gated by `ENABLE_ADMIN` + `ADMIN_TOKEN`, INF12)
  - DuckDB — `data/13f.duckdb`
  - Vanilla JS — `web/static/app.js` (~5600 lines, tco IIFE removed in React port)
  - Jinja templates — `web/templates/index.html`
  - **React POC** — `web/react-src/` (2 Companies Overlap tab, React 18 + TS + Vite + Tailwind v3 + AG Grid v35). Built bundle at `web/static/dist/tco-bundle.{js,css}`, gitignored, loaded as `<script type="module">` from `index.html`. POC is production-serving today but will be retired once the full React app (see `REACT_MIGRATION.md`) ships and cuts over.
  - **React full-app plan** — `REACT_MIGRATION.md` at repo root. Parallel build planned at `web/react-app/` (port 5174), Zustand store, dark-navy sidebar shell, 4 nav sections / 11 tabs. Not yet scaffolded — first scaffold commit is the next session's Phase 1.

---

## First 5 minutes — read these

1. **`~/ClaudeWorkspace/CLAUDE.md`** — workspace rules (folder structure,
   tone, OneDrive deliverable routing, IB color conventions, EDGAR
   identity)
2. **`ROADMAP.md`** — full project state. COMPLETED section at line 220+.
   INFRASTRUCTURE table (L87+) tracks all INF1–INF15. 2026-04-11 entries
   at top of COMPLETED.
3. **`docs/PROCESS_RULES.md`** — rules for large-data scripts
4. **Auto memory** at
   `/Users/sergetismen/.claude/projects/-Users-sergetismen-ClaudeWorkspace-Projects-13f-ownership/memory/`
   persists across sessions — already contains user feedback rules

---

## Last session (2026-04-11) — what shipped

~50 commits from baseline `56bfa3f` → `fdda6b2`. Four main deliverables
(Entity Graph, 2 Companies Overlap vanilla JS, B608 fix, INF9 Route A),
an INF12 admin-auth hardening pass, a **full React port** of the 2
Companies Overlap tab (scaffold → production-ready, 16 commits), and
the **React full-app migration plan** (`REACT_MIGRATION.md`) for the
next session.

Post-`59410e7` work that the previous version of this file missed:

- **INF12 admin Blueprint** (`d51db60`, `c91afd2`) — 15 admin routes
  moved to `scripts/admin_bp.py` under `/api/admin/*`, gated by
  `ENABLE_ADMIN=1` + `ADMIN_TOKEN` env vars with `hmac.compare_digest`
  token compare. `admin.html` sends `X-Admin-Token` header via
  `adminFetch()`. Exception: `/api/admin/quarter_config` left ungated
  because the public React UI fetches it every page load. Commit
  message on `d51db60` has the full detail.

- **2 Companies Overlap — React iteration continuation** (8 commits
  after `59410e7`): `a5c3b99` (width/height/gap pass), `64e4692`
  (fixed-basis flex panels + drop duplicate group header border),
  `39c9bb9` (autoHeight + suppressHorizontalScroll, drop overlap cell
  strip, cohort math rewrite), `013cf3b` (wider $ columns for
  NVDA-class values, bidirectional cohort math), `ce2a356` (R1-R4
  polish: overlap highlight selector heavier, rank valueGetter,
  bordered summary cards, cohort number per row), `680549c` (ROADMAP
  entry consolidating all 16 React commits), `fdda6b2`
  (REACT_MIGRATION.md plan).

### 1. Entity Graph tab (`a028153`, `9080885`)

- vis.js 9.1.9 vendored to `web/static/vendor/`
- Four endpoints:
  - `/api/entity_search` — type-ahead for rollup parents
  - `/api/entity_children` — cascading dropdown population
  - `/api/entity_graph` — full `{nodes, edges, metadata}` payload
  - `/api/entity_resolve` — resolve any entity_id to its canonical root
- Query helpers in `queries.py`: `search_entity_parents`,
  `get_entity_by_id`, `get_entity_cik`, `compute_aum_by_cik`,
  `compute_aum_for_subtree`, `get_entity_filer_children`,
  `get_entity_fund_children`, `get_entity_sub_advisers`,
  `build_entity_graph`
- Walks `entity_relationships` (excluding `sub_adviser` edges) for
  CIK-bearing descendants at shallowest depth
- **Funds attach at institution root, not per-filer.** Discovered
  empirically — BlackRock's 26 filer subsidiaries have 0 direct fund
  children. Filer tier is parallel to fund tier, not a parent of it.
- **Filer fallback** for single-filer firms (Vanguard pattern) —
  returns institution itself when no CIK descendants exist

### 2. 2 Companies Overlap tab (`5942449` + 13 UI-polish commits)

- Two endpoints:
  - `/api/two_company_overlap` — pairwise comparison
  - `/api/two_company_subject` — subject-only variant for immediate
    tab-activation render
- **Subject auto-fills** from main header ticker input on tab
  activation (reads `#ticker-input.value`)
- **Second-ticker autocomplete** reuses the existing page-global
  `tickerList` + `filterTickers()` function — matches Cross-Ownership
  pattern, no per-keystroke `/api/tickers` fetch
- Two side-by-side tables with grouped headers:
  - `% Owned` (subject + second ticker columns under a sandstone
    underline)
  - `Value ($M)` (subject + second ticker columns under a sandstone
    underline)
- Top 15 body rows, Top 15 + Top 25 tfoot totals, Top 25 + Top 50
  cohort summary per panel
- **Per-panel "Active only" toggles**:
  - Institutional: `manager_type !== 'passive'`
  - Fund: `fund_universe.is_actively_managed` (NULL = unknown = keep)
- Client-side `_tcoLastData` cache → toggle change re-renders without
  refetching
- Sandstone (`#C9B99A`) group-header underline matches existing
  `.column-group-row th.group-header` pattern in `style.css`
- Safari `background-clip: padding-box` workaround for WebKit
  sticky-header background bleed at `border-collapse:collapse`
  boundaries

### 3. B608 nosec placement fix (`794c81e`) — 26 endpoints restored

- **Preexisting breakage** since commit `ee5e7cb` (pre-session)
- Root cause: `# nosec B608` was placed on `con.execute(f"""` lines,
  injecting the literal comment text into the SQL f-string. DuckDB
  errored with `Parser Error: syntax error at or near "#"`
- Silently broke **26 endpoints**, including:
  - `/api/tickers` — **the autocomplete root**. Broke the entire
    header search bar — a real production impact, not a corner case
  - `/api/admin/manager_changes` (was tracked as INF15)
  - `/api/heatmap`, `/api/fund_portfolio_managers`, `/api/amendments`,
    `/api/short_long`, `/api/manager_detail`, `/api/nport_shorts`, and
    18 more
- Fix pattern: split `con.execute(` onto its own line, use implicit
  `f""  # nosec B608` empty-string concat to anchor bandit's nosec
  recognition on a physical line the SQL interpreter never sees
- **Closed INF15 as duplicate** of this root cause
- Added `SMOKE TEST` marker comment above `api_tickers` route in
  `app.py` so future smoke tests always include `/api/tickers` in
  their curl set — the gap that let this bug live for weeks

### 4. INF9 Route A — 24 reclassify overrides persisted (`b53e3fa`)

- **Scope narrowed from 39 → 24** after reading
  `replay_persistent_overrides()` in `build_entities.py`. The replay
  function supports exactly three action types:
  `reclassify classification`, `alias_add`, `merge → economic_control_v1`,
  and it hard-codes `is_activist=FALSE`. Not every Apr-10 fix maps.
- **24 rows written** to `data/13f_staging.duckdb`
  `entity_overrides_persistent` covering the full Section 3 L4 audit
  reclassify fixes: 23 `market_maker` reclassifications (Susquehanna ×3,
  Jane Street ×7, Optiver ×3, SIG ×2, CTC, Citadel Securities, DRW,
  Flow Traders, HRT, IMC, Two Sigma Securities, Virtu) + 1
  `SC US (TTGP) → venture_capital` (= Sequoia Capital US).
- All 24 CIKs pre-validated to resolve against
  `entity_identifiers` at commit time. Staging validation:
  **9 PASS / 0 FAIL / 7 MANUAL** — no regression.
  `diff_staging.py` reports 0 line-level changes across the 6 diffed
  table categories (the overrides table is not yet in diff coverage
  — tracked as INF9e).
- **Remaining gaps decomposed into 5 follow-ups**, all in
  `ROADMAP.md` under INFRASTRUCTURE:
  - **INF9a** — extend replay for `is_activist=TRUE` (2 Apr-10 flag
    fixes: Mantle Ridge LP FALSE→TRUE, Triangle Securities Wealth
    TRUE→FALSE). Schema change on `entity_overrides_persistent`
    required.
  - **INF9b** — add `rollup_type` column to override row so `merge`
    can target `decision_maker_v1` (13 DM12 sub-adviser routings).
  - **INF9c** — add `delete_relationship` / suppress_edge action,
    OR port ADV-style Tier 1+2 verifier to the `parent_bridge`
    loader (28 L5 deletions; ADV subset already backstopped by INF5,
    parent_bridge subset still exposed).
  - **INF9d** — CIK-less entities (3 orphans: Pacific Life, Stowers
    Institute, Stonegate Global Financial; + 1 CRD-only:
    International Assets Advisory) can't be reached by the current
    CIK-keyed replay. Schema option: replace `entity_cik` with
    `(identifier_type, identifier_value)` pair.
  - **INF9e** — extend `diff_staging.py` + `promote_staging.py` to
    cover the overrides table, and create the table in prod via DDL
    migration from `entity_schema.sql`. Until this lands, the 24
    rows live in staging only.
- **INF9 is no longer the hard gate on `build_entities.py --reset`
  in the strict sense** — 24 rows are safely persisted in staging,
  and a staging `--reset` cycle would replay them correctly. But a
  **prod `--reset` is still blocked**, now by the combination of
  INF9a–e rather than by a single "write 39 rows" task. Root reason
  unchanged (manual fixes not yet replayable end-to-end across a
  rebuild); task has been decomposed into an honest shape.

### Bonus: INF14 pre-commit wall paid down (`f272570`)

- 39 pylint warnings on `app.py` + 13 on `queries.py` + 33 bandit
  issues → **zero**
- All formatting-only fixes (74 line-for-line replacements):
  - W1203 logger f-strings → `%s` style
  - W1514 `open()` → `encoding='utf-8'`
  - W1510 `subprocess.run` → `check=False`
  - W0107 unnecessary `pass` removed
  - W0603/W0404/W0212/E0401 inline `# pylint: disable=...` comments
  - B110/B112/B404/B603/B607/B104/B113 `# nosec` annotations
- Pre-commit hooks now run clean on `app.py` + `queries.py` — no more
  `--no-verify` required for edits in those files

---

## Critical gotchas — discovered the hard way

### a. Flask template cache

`app.py` runs with `debug=False`. Jinja does **NOT** auto-reload
templates in production mode. Every `web/templates/index.html` change
requires a full Flask server restart:

```bash
kill $(pgrep -f "scripts/app.py")
cd ~/ClaudeWorkspace/Projects/13f-ownership
python3 scripts/app.py --port 8001
```

`web/static/app.js` and `web/static/style.css` are served fresh by
Flask's static handler on every request — just hard-reload the browser
(`Cmd+Shift+R` / `Cmd+Opt+R` in Safari).

### b. Two IIFEs fight over `results-area`

The Entity Graph and 2 Companies Overlap IIFEs both attach parallel
click listeners to every `.tab` element and both toggle
`results-area.style.display`. Whichever listener runs **last** wins.

**Solution: use the `.hidden` CSS class** (`display:none !important`)
instead of inline `style.display` in the tco IIFE. The class can't be
overridden by inline-style clearing. The Entity Graph IIFE still uses
inline style — if you add a third IIFE, match the tco pattern.

See `ba8bfd0` for the commit that fixed this after a confusing
diagnostic session where `results-area` kept reappearing when the tco
tab was active.

### c. New tabs go through `switchTab()`

`app.js` L365 dispatches tabs via an `else if (tabId === ...)` chain. A
new tab branch should:

1. Call `window.loadXxx()` published from an IIFE at the bottom of
   `app.js`
2. Hide `results-area` via `classList.add('hidden')` (NOT inline
   style)
3. The top-of-`switchTab` guard already calls `_tcoDeactivate()` for
   non-tco tabs — mirror that pattern for your new IIFE so switching
   away from your new tab restores the previous panel

### d. Pre-commit bandit 1.8.3 quirk

Multi-code nosec like `# nosec B607,B603` only suppresses the **last**
code in bandit 1.8.3 (the pre-commit pinned version). Upstream bandit
1.8.6+ parses correctly. For multi-issue lines under the 1.8.3 pin,
use bare `# nosec` with a trailing comment naming the codes:

```python
ps = subprocess.run(['pgrep', '-f', script], ..., check=False)  # nosec  # B607 + B603 — known partial-path subprocess
```

### e. `# nosec B608` in `app.py` is dead code

The pre-commit config has `args: [-r, "--skip=B101,B608"]` — B608 is
globally skipped at the hook level. Source annotations are defensive
docs only. **But never put them on a `con.execute(f"""` line** — they
end up inside the SQL string and DuckDB errors on `#`.

The correct pattern for B608 annotation in app.py (Variant B,
empirically derived):

```python
df = con.execute(
    f""  # nosec B608
    f"""
    SELECT ticker, ...
    WHERE quarter = '{LQ}'
    """, [params]
).fetchdf()
```

The empty `f""` is an implicit-concat anchor on a physical line bandit
recognizes for the nosec suppression; Python compiles
`f"" + f"""..."""` into a single f-string identical to the original.

### f. Data model traps

- **`managers.aum` does not exist.** Columns are `aum_total` and
  `aum_discretionary` (ADV Part 1A sources, ~1,500 managers covered).
  For visualizations prefer holdings-derived AUM:
  `SUM(holdings_v2.market_value_usd) WHERE quarter = :q`
- **`holdings_v2.cik`** stores 10-digit zero-padded format
  (`0000102909`). `entity_identifiers.identifier_value` for
  `identifier_type='cik'` matches exactly.
- **`fund_universe.is_actively_managed`** is the authoritative
  active/passive flag for fund series. `NULL` = fund not in universe
  (treat as unknown — the 2 Companies Overlap active filter keeps
  NULL funds visible).
- **`fund_holdings_v2.market_value_usd`** is the column name; there is
  no `market_value`. Old `fund_holdings` table also exists but the app
  uses v2 throughout.
- **`entity_relationships`** has 5 types: `fund_sponsor` (most common),
  `sub_adviser`, `wholly_owned`, `mutual_structure`, `parent_brand`.
  Exclude `sub_adviser` when walking descendants for ownership trees —
  it's a decision-maker relationship, not a containment one.
- **Parents are self-rollup:** `entity_current WHERE entity_id =
  rollup_entity_id` (10,935 rows). Non-parent entities have
  `rollup_entity_id` pointing to their canonical parent.

### g. React + AG Grid + Tailwind landmines (discovered during TCO port)

All of these cost at least one diagnostic round-trip during the React
port. Copy the fixes verbatim into any new React app (`web/react-app/`
Phase 1 especially).

1. **AG Grid v32+ dropped community module auto-registration.**
   Without `ModuleRegistry.registerModules([AllCommunityModule])` at
   the bundle boundary (top of `main.tsx`), the grid renders headers
   only, no rows. Symptom: tab mounts, no error, no data. Fix is one
   line in `main.tsx`, but you MUST remember to do it.

2. **AG Grid v33+ Theming API conflicts with legacy CSS imports.** If
   you import `ag-grid-community/styles/ag-grid.css` and
   `ag-theme-alpine.css`, you MUST pass `theme="legacy"` as a prop on
   every `<AgGridReact>`. Without it the grid errors code 240
   ("themeQuartz default with ag-grid.css included") and may refuse
   to commit rows. The alternative is to fully adopt the Theming API
   and drop the CSS imports — more invasive.

3. **AG Grid React wrapper treats function cellRenderers as React
   components.** Returning an `HTMLElement` from a cellRenderer
   throws "Objects are not valid as a React child" and crashes the
   whole subtree. For bold pinned-row text, return JSX
   `<span style={{fontWeight:600}}>{v}</span>` — NOT
   `document.createElement('span')`.

4. **AG Grid row class rules alpha stacking.** If both
   `.tco-overlap-row` AND `.tco-overlap-row .ag-cell` set a
   semi-transparent background, cells get double alpha (0.18 + 0.18
   ≈ 0.33) while row-only areas stay at 0.18. At the spacer-column
   boundary where the cell-level rule doesn't paint (spacers have
   inline `cellStyle: { backgroundColor: 'transparent' }`), a visible
   darker edge appears. Fix: row-only selector, no cell-level rule.

5. **Tailwind v4 default drops `init -p`.** `npm install -D tailwindcss`
   pulls v4 by default, which uses CSS-first config and has no
   `init -p` command. Pin to v3 explicitly: `tailwindcss@^3`. Don't
   fight the v4 upgrade in the middle of a migration.

6. **Tailwind Preflight (`@tailwind base`) leaks globally.** If your
   built React CSS bundle is linked from the main Flask page, the
   preflight reset applies to EVERY input / button / select on the
   page — not just elements inside the React root. `input { color:
   inherit }` made the main `#ticker-input` text white (inherited
   from `.header { color: white }`), invisible against the white
   input background. Fix: `corePlugins: { preflight: false }` in
   `tailwind.config.js`. The component classes (`border`, `p-4`,
   etc.) still work without the reset.

7. **Never `innerHTML = ''` a React-controlled mount element.** React
   18's reconciler corrupts silently when the DOM it thinks it owns
   is cleared externally. The POC's `switchTab()` deactivate block
   used to clear `#tco-react-root.innerHTML = ''` when switching
   away; next time React tried to render, the commit silently
   failed (no error thrown, no visible content). Fix: hide the
   panel via `classList.add('hidden')` only; let React keep
   managing its subtree. Defense in depth in `main.tsx`: if the
   mount element has been externally cleared, drop the cached
   `_root` and recreate it.

8. **Module script tags are deferred — race against tab clicks.**
   `<script type="module">` always defers until after HTML parsing.
   If the user clicks the 2 Companies Overlap tab BEFORE
   `tco-bundle.js` has parsed, `window.tcoActivate` is still
   undefined and the click is lost. Fix: stash the current ticker on
   `window.__tcoPendingTicker` from the `switchTab` branch when
   `tcoActivate` is not yet defined, and have `main.tsx` auto-mount
   read and clear that pending ticker on load.

9. **AG Grid internal scroll viewports.** With `domLayout="normal"`,
   AG Grid always reserves ~17px of scrollbar track at the bottom of
   the grid even when no scroll is needed. Combined with a slightly
   miscalculated container height, this creates phantom
   scrollbars. Use `domLayout="autoHeight"` +
   `suppressHorizontalScroll={true}` to eliminate both tracks
   entirely — the grid sizes itself exactly to its content.

10. **AG Grid spacer columns: header cells inherit theme background.**
    A top-level `ColDef` with no field / no renderer and
    `cellStyle: { backgroundColor: 'transparent' }` renders
    transparently in the body but its HEADER cell still picks up
    `.ag-header-cell { background-color: #003366 }` — showing as a
    thin blue vertical bar at the top of the column. If you add
    spacer columns, add a `headerClass: 'tco-spacer-header'` with a
    transparent override to silence this.

### h. Inline style vs !important cascade

Inline styles (via `style={...}` in React or `element.style.X` in
JS) normally beat CSS rules. But `!important` CSS beats non-important
inline styles. So a CSS rule like
`.tco-overlap-row .ag-cell { background-color: X !important }` WILL
override the spacer's inline `backgroundColor: 'transparent'`. This
is why the double-coat overlap rule stacked on top of the spacer's
inline transparent style.

---

## Open items you might pick up

### Next direction — React full-app migration (Phase 1)

**Primary next session goal.** Read `REACT_MIGRATION.md` at repo root.
Plan is to scaffold `web/react-app/` as a parallel build alongside the
existing Flask-served app (which stays at `:8001` untouched until cut
over). Tech stack: React 18 + TS + Vite on port **5174** (POC uses
5173, don't collide) + Tailwind v3 (preflight OFF) + AG Grid Community
v35 (with `AllCommunityModule` registered + `theme="legacy"` on every
grid) + Zustand for shared state.

Phase 1 is **shell only** — no tab content. Ship:

1. `web/react-app/` scaffold (Vite + TS + Tailwind + Zustand)
2. `AppShell` + `Sidebar` (4 nav sections, 11 tab placeholders) +
   `Header` (ticker input, company card, view toggle)
3. `useAppStore` Zustand store — `ticker`, `company`, `quarter`,
   `loadCompany(ticker)` that calls `/api/summary?ticker=X`
4. Empty tab component files for all 11 tabs (just return a
   placeholder `<div>Coming soon</div>`)
5. Vite proxy `/api/*` → Flask `:8001`
6. End-state smoke test: `http://localhost:5174` loads, shell
   renders, typing a ticker in the header populates the company card

The existing Flask app at `:8001` stays completely untouched through
Phase 1. Cut over happens in a separate commit at the end of the full
migration (all 11 tabs migrated): one-line change in `scripts/app.py`
to serve `web/react-app/dist/index.html` instead of
`web/templates/index.html`. Revertable in 30 seconds.

**Nav structure** (from `REACT_MIGRATION.md`):
- Overall Market: Sector Rotation, Entity Graph
- Ownership: Register, Ownership Trend, Conviction, Fund Portfolio
- Flow & Rotation: Flow Analysis, Peer Rotation
- Investor Targeting: Cross-Ownership, Overlap Analysis, Short Interest

**Color scheme** (Bloomberg pattern): dark navy shell + light content
area. Shell `#0a0f1e`, sidebar `#0d1526` (active `#1a2a4a`), accent
gold `#f5a623`, content `#f4f6f9`, cards `#ffffff`. Oxford Blue
`#002147` and Glacier Blue `#4A90D9` retained for legacy components.

**Do NOT build yet** (explicitly deferred):
- **Playwright visual regression testing** — add when **3+ tabs
  migrated**, not before. Too much churn on the shell in Phase 1 to
  lock screenshots in early.
- `/api/admin/*` token handling in the React fetch layer (INF12
  landed the server-side gating; client side still needs the
  `X-Admin-Token` header helper ported from `admin.html`'s
  `adminFetch()`).
- Activist flag as red highlight on Register + Conviction rows
  (styling only, not a tab).
- Short Interest tab content (tab placeholder still fine — the
  data pipeline exists in Flask).

### UI tweaks still pending

- 2 Companies Overlap tfoot still labels "Top 15 Total" even when
  Active-only drops the visible count below 15. ~2-line fix to adapt
  the label dynamically. User flagged and accepted as not urgent.

### Known preexisting bugs

- ~~**INF12 — high priority before any deploy.**~~ **DONE** (`d51db60`).
  Admin Blueprint with `ENABLE_ADMIN` + `ADMIN_TOKEN` env gating,
  `X-Admin-Token` header, `hmac.compare_digest` compare. 15 routes
  moved to `/api/admin/*` with one exception: `/api/admin/quarter_config`
  stays ungated because the public main UI fetches it every page load.
  Render deployment safe.
- **INF13 part 2.** Snapshot fallback in `_resolve_db_path` uses
  `shutil.copy2` on live DuckDB file → race with concurrent writes.
  Part 1 was the `refresh_snapshot.sh` fix (`d0677b1`); part 2 for
  the hot-path app.py fallback is still pending.
- **INF4/6/7/8 fragmentation cleanups.** Loomis Sayles (INF4),
  Tortoise Capital (INF6), eid 2218 Soros/VSS identity confusion
  (INF7 — HIGH priority), Trian (INF8).
- **INF9 / 9a / 9b / 9c / 9d / 9e — prod `--reset` still blocked.**
  Route A landed 2026-04-11 (`b53e3fa`): 24 Section 3 L4 reclassify
  overrides written to staging `entity_overrides_persistent`. That
  subset is replayable today. Five follow-ups gate a full prod
  `--reset`:
  - **INF9a** — `is_activist` flag (2 Apr-10 rows, Mantle Ridge +
    Triangle Securities Wealth). Needs schema column + replay
    extension.
  - **INF9b** — `rollup_type` on `merge` so DM12 routings can target
    `decision_maker_v1` (13 rows).
  - **INF9c** — `delete_relationship` action OR parent_bridge
    verifier to cover the 28 L5 deletion subset not backstopped by
    INF5.
  - **INF9d** — replace `entity_cik` with
    `(identifier_type, identifier_value)` pair so CIK-less entities
    (4 rows) are reachable. Three of the four are orphan entities
    with no feeder backing at all and need a separate
    `manual_entities_preserve` mechanism.
  - **INF9e** — extend `diff_staging.py` + `promote_staging.py` +
    prod DDL so the 24 staged rows can actually reach prod. Without
    this, INF9 Route A is staging-local indefinitely.
  - Staging `--reset` would work today and validate replay. A
    **prod** `--reset` must wait until all five follow-ups land.

### Data quality follow-ups

- **L4-1.** 1,037 entities in `mixed` classification — ~10-30 are
  probably pure asset managers misclassified (Franklin Templeton,
  PIMCO, Nomura confirmed; full population review pending).
- **L4-2.** 3 parents with classification contradicting N-PORT series
  child split: Invesco ($352B, classified passive, 96.7% active),
  Nuveen/TIAA ($292B, classified passive, 90.1% active), Security
  Investors LLC ($6.9B, classified active, 80.9% passive).

### Verification tasks

- Spot-check other admin/F6 data-quality endpoints with curl to
  confirm no other silent 500s survive the B608 fix. The 26 affected
  endpoints from `794c81e` are now known; anything else returning 500
  is a different bug.

---

## Sanity checklist (run before touching code)

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership

# 1. Branch state clean?
git status -sb                  # expect: ## main...origin/main
git log -5 --oneline            # expect: 292feba at top or newer

# 2. Dev server running?
pgrep -f "scripts/app.py"       # returns PID if up

# 3. Autocomplete root endpoint works?
curl -s http://localhost:8001/api/tickers \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"
# expect: 6500+

# 4. Pre-commit still clean?
pre-commit run pylint --files scripts/app.py scripts/queries.py
pre-commit run bandit --files scripts/app.py scripts/queries.py
```

---

## Hard rules (from auto memory + CLAUDE.md)

- Never start a full pipeline run without explicit user authorization.
  `--test` mode only unless user says otherwise.
- Never mutate production data to simulate test conditions. Use flags
  or parameters.
- Always update `ROADMAP.md` after completing a task — move items to
  COMPLETED with date and details.
- Entity changes go through the staging workflow (INF1):
  `sync_staging.py` → `diff_staging.py` → `promote_staging.py`.
- Entity overrides: Route A reclassify rows are in staging
  `entity_overrides_persistent` (24 rows, commit `b53e3fa`). Five
  categories are still NOT persisted — see INF9a–e. A **prod**
  `--reset` still wipes anything not covered. A **staging** `--reset`
  would replay Route A correctly.
- Read files **in full** before editing — no partial reads on first
  touch of a file you intend to modify.
- Confirm destructive actions before running (kill, `rm`, `git reset
  --hard`, db mutations).
- Use `python3 -u` for background tasks — `print()` fully buffers when
  redirected.

---

## User collaboration preferences

- **Terse, direct communication.** Match the user's pace. No
  consultant-speak, no preambles, lead with the answer.
- **Quick fixes preferred** over comprehensive refactors unless
  explicitly asked.
- User often tests in **Safari**, sometimes Chrome. Cross-browser
  rendering differences matter (especially sticky headers, f-string
  edge cases, subpixel borders).
- User will paste DevTools Console output when asked — prepare **one
  tight diagnostic command** rather than multiple.
- User runs the Flask dev server on port 8001 manually. If they need
  to run a shell command themselves, suggest they type `! <cmd>` in
  the prompt.
- **Flag duplicate ROADMAP items** before adding — check existing rows.
- **Don't delete** files, data, or rows without explicit confirmation.
  State what will be deleted and wait for a clear yes.

---

## Session ledger (commits since 2026-04-11 start, newest first)

```
fdda6b2 Add REACT_MIGRATION.md — Phase 1 plan and architecture decisions
680549c ROADMAP: add 2026-04-11 2 Companies Overlap React port entry
ce2a356 2 Companies Overlap: fix R1-R4 (overlap highlight, rank, summary cards)
013cf3b 2 Companies Overlap: wider % and $ columns + bidirectional cohort math
39c9bb9 2 Companies Overlap: kill scrollbars, fix overlap strip, fix cohort math
64e4692 2 Companies Overlap: fixed-basis panels + drop duplicate group header border
c91afd2 ROADMAP: mark INF12 Done
d51db60 INF12: admin Blueprint with token auth — gate all /api/admin/* except quarter_config
a5c3b99 2 Companies Overlap: widths, height, gap, summary, overlap, group header
5303b0f 2 Companies Overlap: new column widths + pinned-row overlap exclusion
59410e7 2 Companies Overlap: locked width spec, Active Only, summary card
f0bcc14 2 Companies Overlap: fix two regressions from c7feb65
c7feb65 2 Companies Overlap: polish pass (HTML renderers, headers, layout, z-index)
c2cbec1 2 Companies Overlap: stop stomping React's DOM
71da99b 2 Companies Overlap: AG Grid theme="legacy"
68b40ff 2 Companies Overlap: register AG Grid community modules
cee679f 2 Companies Overlap: disable Tailwind Preflight
d48a8fd 2 Companies Overlap: fix React bundle load race
5a7fcde 2 Companies Overlap: React components built
e200623 React POC scaffold: Vite + TypeScript + Tailwind + AG Grid
b53e3fa INF9 Route A: persist 24 reclassify overrides to staging entity_overrides_persistent
292feba ROADMAP: add 2026-04-11 session entries (Entity Graph, 2 Companies Overlap, B608 fix)
33a39f9 2 Companies Overlap: per-panel active-only toggles + wider header search
de09d87 2 Companies Overlap: 1-decimal totals + owned-by cohort labels, wider header ticker input
95d80f7 2 Companies Overlap: background-clip:padding-box on thead cells for Safari
2df5a2c 2 Companies Overlap: restore 3pt trailing spacer column
ba8bfd0 2 Companies Overlap: use .hidden class (not inline style) to defeat IIFE collision
887e469 2 Companies Overlap: remove 3px trailing spacer column
7514e67 2 Companies Overlap: group header underline color → sandstone
eb74487 2 Companies Overlap: switchTab deactivation + explicit thead border:none
10ccea7 2 Companies Overlap: tables fluid to panel width
fb6bcfc 2 Companies Overlap: table-layout:fixed + Top 25 totals row
ed892f1 2 Companies Overlap: explicit column widths + group header underline
f4b5cae 2 Companies Overlap: autocomplete + immediate subject load
978dcec 2 Companies Overlap: UI fixes — grouped headers, top 15, ranking, auto-fill, summary per panel
a841ddb Close INF15 + add /api/tickers smoke-test marker
794c81e Fix B608 nosec placement — 26 endpoints returning HTTP 500
fcf7583 ROADMAP: mark INF14 Done + add INF15 for manager_changes 500
f272570 INF14: clear pylint/bandit wall on app.py and queries.py
5942449 Add 2 Companies Overlap tab — institutional and fund-level holder comparison
9080885 Add /api/entity_resolve endpoint — resolve any entity_id to canonical institution root
c01be5c ROADMAP: add INF14 — pre-commit pylint/bandit debt on app.py + queries.py
a028153 Add Entity Graph tab (vis.js) — institution/filer/fund hierarchy with sub-adviser edges
```
