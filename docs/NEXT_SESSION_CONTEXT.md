# 13F Ownership — Next Session Context

_Last updated: 2026-04-11 (session end, HEAD: 59410e7)_

Paste this file's contents — or reference it by path — at the start of a
fresh Claude Code session to land fully oriented. Regenerate at the end of
each working session so the top block stays current.

---

## Project summary

- **Working dir:** `~/ClaudeWorkspace/Projects/13f-ownership`
- **Branch:** `main` (even with `origin/main`)
- **HEAD:** `59410e7`
- **Repo:** github.com/ST5555-Code/Institutional-Ownership
- **Stack:**
  - Flask — `scripts/app.py` (2000+ lines)
  - DuckDB — `data/13f.duckdb`
  - Vanilla JS — `web/static/app.js` (6000+ lines)
  - Jinja templates — `web/templates/index.html`

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

26 commits from baseline `56bfa3f` → `59410e7`. Four main deliverables,
a critical bug fix, and an entity-override persistence pass.

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

---

## Open items you might pick up

### UI tweaks still pending

- 2 Companies Overlap tfoot still labels "Top 15 Total" even when
  Active-only drops the visible count below 15. ~2-line fix to adapt
  the label dynamically. User flagged and accepted as not urgent.

### Known preexisting bugs

- **INF12 — high priority before any deploy.** `/api/add_ticker`,
  `/api/admin/run_script`, `/api/admin/entity_override` have zero
  auth. Render deployment would expose prod writes to the internet.
  Fix: middleware + env var token, split admin endpoints into a
  separate Blueprint mounted only when `ENABLE_ADMIN=1`, bind to
  `127.0.0.1` by default.
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

## Session ledger (commits since 2026-04-11 start)

```
59410e7 2 Companies Overlap: locked width spec, Active Only, summary card
f0bcc14 2 Companies Overlap: fix two regressions from c7feb65
c7feb65 2 Companies Overlap: polish pass (HTML renderers, headers, layout, z-index)
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
