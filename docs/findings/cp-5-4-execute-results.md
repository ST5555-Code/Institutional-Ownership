# CP-5.4 execute — Crowding + Conviction + Smart Money + FPM1 reader migration

Fourth reader-migration PR for CP-5. Bundles Crowding + Conviction +
Smart Money per Bundle C §7.4 plus the adjacent FPM1 site
(`/fund_portfolio_managers`) per chat decision 2026-05-06 (Q1 — bundle
into CP-5.4 to avoid sibling-tab visual drift).

5 CLEAN sub-sites swap from `COALESCE(rollup_name, inst_parent_name,
manager_name)` to `top_parent_canonical_name_sql('h')` helper. No new
infrastructure. No new fixtures. Zero BLOCKED migration sites.

## 1. Phase 0 cleanup

Worktree clean of untracked artefacts in `data/working/`. Branch
`cp-5-4-execute` opened off `main` at HEAD `28eed8d` (PR #302 merge).
Pytest baseline verified at 438 passing pre-migration.

## 2. Phase 1 site re-validation

### 2.1 5-site manifest re-confirmation

Each PR #302 inventory entry re-greps to the same file:line on HEAD
`28eed8d` post fast-forward. No drift since PR #302 landed.

| id | file:line | shape |
|----|-----------|-------|
| C1 | `scripts/queries/market.py:135` | `COUNT(DISTINCT COALESCE(...))` head query in `get_market_summary` |
| C2 | `scripts/api_market.py:199` | `/crowding` holders top-20 GROUP BY |
| CV1 | `scripts/queries/fund.py:110` | `portfolio_context` top-25 holders parent branch |
| CV2 | `scripts/queries/fund.py:179` + `:188` | `portfolio_context` portfolio_df SELECT + WHERE pair |
| FPM1 | `scripts/api_fund.py:42` | `/fund_portfolio_managers` GROUP BY |

### 2.2 Helper-variant decision

The PR #302 prompt sketch suggested a noalias variant for sites C1 and
CV1 (where the FROM clause did not alias `holdings_v2`). The DuckDB
binder fails the noalias variant inside C1's `FROM holdings_v2,
latest` cross-join because the helper subquery's correlated bare
`entity_id` reference is ambiguous against the inner `ittp.entity_id`
/ `e.entity_id` columns in the subquery JOIN.

Resolution: alias `holdings_v2` as `h` in C1 and CV1 (matching the
existing C2 / CV2 / FPM1 alias convention) and use
`top_parent_canonical_name_sql('h')` for all 5 sites uniformly. No
behavioural change vs. the noalias variant — the helper resolves the
same canonical top-parent regardless of how the outer table is named.

This is a small variance from the recon §4.3 plan but lands cleaner
(single helper-variant pattern across the whole PR; no noalias
codepath needed for CP-5.4).

## 3. Phase 2 migrations

5 sub-sites swap to `top_parent_canonical_name_sql('h')`. Per-site
before/after manifest:
[data/working/cp-5-4-execute-migration-manifest.csv](../../data/working/cp-5-4-execute-migration-manifest.csv).

### 3.1 Per-site notes

- **C1** — added `h` alias to `FROM holdings_v2, latest` cross-join;
  `holdings_v2.quarter` and `is_latest` references prefixed with
  `h.` for consistency. `latest` CTE retains its name.
- **C2** — added `h` alias to `FROM holdings_v2`; `ticker`, `quarter`,
  `is_latest`, `manager_type`, `pct_of_so`, `market_value_live`
  references prefixed with `h.`.
- **CV1** — added `h` alias; removed unused `rn_noalias` local; kept
  `_ = rollup_type` no-op for signature compatibility (helper is
  rollup-type independent per CP-5.1 §3).
- **CV2** — `holdings_v2 h` alias was already present; just swapped
  the SELECT (line 179) and WHERE-clause IN-list (line 188) to the
  same `{tpn}` expression so the GROUP BY rows match the IN filter
  exactly.
- **FPM1** — added `h` alias; column references prefixed with `h.`;
  `MAX(COALESCE(...))` becomes `MAX({tpn})` (semantically identical
  inside MAX since the helper output is a scalar string).

### 3.2 Live-DB smoke (post-migration)

Read-only probe `scripts/oneoff/cp_5_4_execute_smoke.py` against prod
DuckDB / 2025Q4 / AAPL:

```
[C1 market_summary] quarter=2025Q4 total_holders=8554
[C2 crowding AAPL] holders=20 top=VANGUARD GROUP INC
[CV1 conviction_top_holders AAPL] holders=25 top=VANGUARD GROUP INC
[CV2 portfolio_df] rows=94302 distinct_holders=25 (expect=25)
[FPM1 fund_portfolio_managers AAPL] rows=50 top=Berkshire Hathaway Inc
smoke OK
```

Pre-migration recon showed `total_holders=8437` and `top=Vanguard
Group`; post-migration values are 8554 and `VANGUARD GROUP INC`. The
holder-count delta (+117) is the entity-keyed climb collapsing brand
variants under canonical top-parents; the top name change is the
shift from denorm `rollup_name` to `entities.canonical_name`. CV2's
SELECT/WHERE pair returns all 25 expected holders (no internal name
drift between CV1 and CV2).

## 4. Phase 3 validation

### 4.1 pytest

Baseline: 438 passing post fast-forward to `28eed8d`.

New suite:
[tests/test_cp5_4_crowding_conviction_smart_money.py](../../tests/test_cp5_4_crowding_conviction_smart_money.py)
adds 6 tests:

| test | site | invariant |
|------|------|-----------|
| T_A | C2 | /crowding holders panel parses + returns canonical-named rows |
| T_B | CV1 | top-25 holders carry no duplicate canonical names |
| T_C | CV1+CV2 | every CV1 holder appears in CV2 portfolio_df (SELECT/WHERE pair invariant) |
| T_D | C1 / SM | per-manager_type distinct-holder counts ≥ global distinct (Smart Money shared-denominator inheritance) |
| T_E | FPM1 | one row per (cik, fund_name) with canonical inst_parent_name |
| T_F | helper | `top_parent_canonical_name_sql('h')` parses + returns row |

Post-migration total: **444 passing, 6 skipped** (438 + 6). Within the
+6 to +8 estimate from recon §4.4.

### 4.2 React build

`web/react-app && npm run build` clean — 0 errors, 0 warnings,
all 17 chunks emitted. ConvictionTab and FundPortfolioTab bundles
unchanged in shape (consume the same endpoint payloads).

### 4.3 Smoke-suite regen + sentinel updates

The shared smoke endpoint registry
([tests/smoke/endpoints.py](../../tests/smoke/endpoints.py)) covers
`/tickers`, `/query1`, `/summary`, `/entity_graph` only — none of
the CP-5.4 endpoints (`/crowding`, `/portfolio_context`,
`/smart_money`, `/fund_portfolio_managers`) are in the smoke suite
today. The `query1` sentinel uses lowercase
`startswith("vanguard")`, which is already canonical-name tolerant.

No smoke regen or sentinel updates needed.

### 4.4 App smoke (live)

Started app via `DB_PATH_OVERRIDE=...prod.duckdb python3 scripts/app.py
--port 8001`; curled all 4 endpoints with `?ticker=AAPL`:

```
/crowding              → holders=20 top=VANGUARD GROUP INC
/portfolio_context     → rows=96 top=VANGUARD GROUP INC
/smart_money           → keys=['long_by_type','short_volume','short_pct','short_date','nport_shorts']
/fund_portfolio_managers → rows=50 top=Berkshire Hathaway Inc
```

App stopped cleanly. The `portfolio_context` row count includes
parent-tier 25 plus N-PORT fund-tier children (CV3 path), confirming
that the canonical-name shift in CV1 doesn't break the downstream CV3
regex matcher (recon §6.3 visual-QC anchor).

## 5. CP-5 status

| PR | branch | status |
|----|--------|--------|
| CP-5.1 | cp-5-1-helper-design-recon | merged (#298) |
| CP-5.1b | cp-5-1b-helper-and-view | merged (#299) |
| CP-5.2 | cp-5-2-register-partial-and-unified-quarter-fix | merged (#300) |
| CP-5.3 | cp-5-3-cross-ownership-readers | merged (#301) |
| CP-5.4-recon | cp-5-4-recon | merged (#302) |
| **CP-5.4** | **cp-5-4-execute** | **this PR** |
| CP-5.5 | not authored | next |
| CP-5.6 | not authored | post CP-5.5 |

CP-5.4 closes the 4th of 6 CP-5.x execution PRs. Next: CP-5.5 Sector
Rotation / New-Exits / AUM / Activist scoping (Bundle C §7.4 sized
M-L).

## 6. Out-of-scope discoveries / surprises

### 6.1 BlackRock brand-vs-filer double-count visible

AAPL post-migration `/portfolio_context` and `/crowding` panels
surface both `BLACKROCK INC.` (eid 3241) and `BLACKROCK / ISHARES`
(eid 2) as separate top-parent canonical entries — same caveat as
CP-5.2 §7.1 / CP-5.3 §6. Tracked in `inst-eid-bridge` / cp-4c
(post-CP-5 ROADMAP P3 backlog). Not a CP-5.4 regression — visible
because the migration now keys on entity canonical name, surfacing
the bridge gap.

### 6.2 CV3 fund-tier NPORT family bridge deferred

`get_nport_children_batch` (CV3 reference at
`scripts/queries/common.py:488-820`) remains regex-name based.
Migrated CV1 holder names feed in as `parent_list`; CV3's regex
matcher is name-string agnostic and continues to work post-shift.
Defer to ROADMAP P2 (NPORT family bridge replacement, Workstream 3)
per Q2 chat decision 2026-05-06.

### 6.3 Bundle C api-files extension

Bundle C's 27-row inventory scoped `scripts/queries/*` only. C2 and
FPM1 surface `scripts/api_*.py` as a second reader layer with
identical rollup-coalesce patterns. Per Q3 chat decision 2026-05-06,
the api-files extension lands in a separate tiny PR after CP-5.4
ships (extends Bundle C csv + §7.4 to enumerate api_*.py reader
sites for future CP-5.5+ recons).

### 6.4 Noalias-variant ambiguity in DuckDB binder

Recorded for future helper-design awareness: the noalias variant of
`top_parent_canonical_name_sql('')` fails to bind inside DuckDB
queries that have multiple correlated `entity_id` references in
scope (e.g., `FROM holdings_v2, latest` cross-join; the helper's
inner `ittp.entity_id` / `e.entity_id` columns shadow the bare
`entity_id` reference). The fix is to add a table alias to the outer
`holdings_v2`. The helper itself is unchanged — adding-alias is the
caller's burden. Future CP-5.x callers should default to the alias
variant and only use noalias for queries with a single
unambiguous outer table.

## 7. Files touched (this PR)

| file | shape |
|------|-------|
| `scripts/queries/market.py` | C1 migration + helper import |
| `scripts/api_market.py` | C2 migration + helper import |
| `scripts/queries/fund.py` | CV1 + CV2 migration; remove `_rollup_name_sql` import |
| `scripts/api_fund.py` | FPM1 migration + helper import |
| `tests/test_cp5_4_crowding_conviction_smart_money.py` | new — 6 tests |
| `scripts/oneoff/cp_5_4_execute_smoke.py` | new — read-only post-migration smoke |
| `data/working/cp-5-4-execute-migration-manifest.csv` | new — per-site before/after |
| `docs/findings/cp-5-4-execute-results.md` | new — this doc |
