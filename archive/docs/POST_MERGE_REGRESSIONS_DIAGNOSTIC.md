# Post-merge regressions — diagnostic findings

Branch: `diag/post-merge-regressions`
Base commit: `bee49ff` (main HEAD, merge of `block/pct-of-float-period-accuracy`)
Date: 2026-04-19
Ticker under test: AAPL · Quarter: 2025Q4 · Flask: live on :8001 (PID 24145)

Diagnostic-only pass. No code changes. No DB writes. No fixes.

---

## §1 Register %FLOAT column

### API response field names

Response sample (first row, top holder by AUM):

```json
{
  "rank": 1,
  "institution": "Vanguard Group",
  "value_live": 376293956711.39996,
  "shares": 1428602721.0,
  "pct_so": 9.716599192679059,
  "aum": 6907926,
  "pct_aum": 5.45,
  "nport_cov": 100.0,
  "type": "passive",
  "is_parent": true,
  "child_count": 5,
  "level": 0,
  "source": "N-PORT",
  "subadviser_note": null
}
```

Grep results against `/tmp/query1_response.json`:

| Field name variant | Present? |
|---|---|
| `pct_so` | **Yes** — present on every row |
| `pct_of_so` | No |
| `pct_of_float` | No |
| `pct_float` | No |
| Any `flt` / `float` substring | No |

The backend rename from `pct_of_float` → `pct_so` (commit `f956096`, Phase 1b read-site migration) is complete on the server.

### React component expected field name

Source — worktree, post-merge:

- [web/react-app/src/components/tabs/RegisterTab.tsx:913](web/react-app/src/components/tabs/RegisterTab.tsx:913) — `<td style={TD_RIGHT}>{fmtPctSo(row.pct_so)}</td>`
- [web/react-app/src/components/tabs/RegisterTab.tsx:647](web/react-app/src/components/tabs/RegisterTab.tsx:647) — `<th style={TH_RIGHT}>% SO</th>`
- [web/react-app/src/types/api.ts:460](web/react-app/src/types/api.ts:460) — `pct_so: number | null`

Source matches the API — TSX expects `row.pct_so` with column header `% SO`. Full-tree grep for `% FLOAT` / `pct_of_float` / `pct_float` in `web/react-app/src/` returns **zero** matches (one unrelated `FLOATING MODAL` comment in `EntityGraphTab.tsx:448`).

### Built bundle is stale

The user-facing UI renders a column labeled `% FLOAT` — a name that exists nowhere in current source. Flask (PID 24145, cwd = main repo root) serves the React app from `web/react-app/dist/index.html`; the on-disk bundle was built **2026-04-13 17:33**, six days before the `pct-of-so` rename swept through source.

Bundled artifact: `web/react-app/dist/assets/RegisterTab-C1IGmHDk.js`

```
grep -c  pct_of_float|pct_float   → 2 hits (source-level references compiled in)
grep -o  pct_of_float|pct_float|pct_so|"% [A-Z]+"  →
   7  pct_float
   0  pct_so
```

Bundle reads `row.pct_float` and renders header `% FLOAT`. API returns `pct_so`. `row.pct_float` is `undefined` → `fmtPctSo(null)` → em-dash, on every row.

### Hypothesis

Register `% FLOAT` column shows `—` because the deployed `dist/` bundle pre-dates the `pct_of_float` → `pct_so` rename (`f956096`); source is correct, bundle is stale.

---

## §2 Flow Analysis name duplication

### First 8 Buyers entries (from API response)

```json
[
  { "inst_parent_name": "Cardano Risk Management B.V.", "net_shares": 37746784.0,
    "pct_change": 8.906690048621693, "pct_so": 0.257, "momentum_signal": null },
  { "inst_parent_name": "Cardano Risk Management B.V.", "net_shares": 37746784.0,
    "pct_change": 8.906690048621693, "pct_so": 0.257, "momentum_signal": null },
  { "inst_parent_name": "Capital Group / American Funds", "net_shares": 33069026.0,
    "pct_change": 0.2677748006061525, "pct_so": 0.225, "momentum_signal": "ACCEL" },
  { "inst_parent_name": "Capital Group / American Funds", "net_shares": 33069026.0,
    "pct_change": 0.2677748006061525, "pct_so": 0.225, "momentum_signal": "ACCEL" },
  { "inst_parent_name": "Vanguard Group", "net_shares": 26929254.0,
    "pct_change": 0.019212216421301494, "pct_so": 0.183, "momentum_signal": null },
  { "inst_parent_name": "Vanguard Group", "net_shares": 26929254.0,
    "pct_change": 0.019212216421301494, "pct_so": 0.183, "momentum_signal": null },
  { "inst_parent_name": "Cerity Partners LLC", "net_shares": 20325731.0,
    "pct_change": 1.0635587032156306, "pct_so": 0.138, "momentum_signal": "ACCEL" },
  { "inst_parent_name": "Cerity Partners LLC", "net_shares": 20325731.0,
    "pct_change": 1.0635587032156306, "pct_so": 0.138, "momentum_signal": "ACCEL" }
]
```

(Truncated for brevity — relevant fields only. Full JSON at `/tmp/flow_analysis_response.json`.)

### Distinct vs total

- `buyers[]` length: **25**
- distinct `inst_parent_name`: **needs dedupe count** — manual inspection of first 8 shows every institution appears exactly twice, adjacent, byte-identical on the numerics → API fan-out, not UI bug.

### Backend trace

Route: `api_flows.py:164` `api_portfolio_context` → not this; flow handler is at `api_flows.py` → `flow_analysis` in [scripts/queries.py:3109](scripts/queries.py:3109).

Precomputed path — [scripts/queries.py:3156-3165](scripts/queries.py:3156):

```python
df = con.execute("""
    SELECT inst_parent_name, manager_type, from_shares, to_shares, net_shares,
           pct_change, from_value, to_value, from_price,
           price_adj_flow, raw_flow, price_effect,
           is_new_entry, is_exit, flow_4q, flow_2q,
           momentum_ratio, momentum_signal
    FROM investor_flows
    WHERE ticker = ? AND quarter_from = ?
    ORDER BY net_shares DESC NULLS LAST
""", [ticker, quarter_from]).fetchdf()
```

**No `rollup_type` filter.** `_rollup_col(rollup_type)` is assigned at [queries.py:3113](scripts/queries.py:3113) but the precomputed SELECT never references it.

Live-DB check against `investor_flows`:

```
DESCRIBE investor_flows  →  rollup_type VARCHAR, rollup_entity_id BIGINT, rollup_name VARCHAR, inst_parent_name VARCHAR, ...

SELECT rollup_type, COUNT(*) FROM investor_flows
WHERE ticker='AAPL' AND quarter_from='2025Q3' GROUP BY 1;
  economic_control_v1  6025
  decision_maker_v1    6025
```

Vanguard-specific:

```
rollup_type           inst_parent_name                 net_shares  pct_change
economic_control_v1   Vanguard Capital Wealth Advisors 566         0.010213
economic_control_v1   Vanguard Group                   26929254    0.019212
decision_maker_v1     Vanguard Group                   26929254    0.019212
decision_maker_v1     Vanguard Capital Wealth Advisors 566         0.010213
```

Every institution carries one row per `rollup_type`. The SELECT omits the filter, so each is returned twice — same stats, adjacent in the response because the `ORDER BY net_shares` tie-breaks them together.

This is the INF34 pattern called out in the prompt: `investor_flows` gained `rollup_type` as a first-class key during Phase 4b, but this SELECT was not updated to filter on it.

### Hypothesis

Flow Analysis duplicates come from the API itself: `queries.flow_analysis` precomputed SELECT (lines 3156–3165) does not filter `investor_flows` by `rollup_type`, so both `economic_control_v1` and `decision_maker_v1` rows are returned for every institution.

---

## §3 Conviction 500

### Curl response

```
> GET /api/v1/portfolio_context?ticker=AAPL&level=parent&active_only=false&rollup_type=economic_control_v1
< HTTP/1.1 500 Internal Server Error
< server: uvicorn
< content-type: application/json

{"data":null,"error":{"code":"internal_error","message":"boolean value of NA is ambiguous"},
 "meta":{"quarter":null,"rollup_type":"economic_control_v1","generated_at":"2026-04-19T18:44:02Z"}}
```

### Full Python traceback

Reproduced by calling `queries.portfolio_context('AAPL', level='parent', active_only=False, rollup_type='economic_control_v1')` directly after bootstrapping `scripts.app`:

```
Traceback (most recent call last):
  File "<string>", line 8, in <module>
  File "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/scripts/queries.py",
      line 3658, in portfolio_context
    fund_is_active = {r['fund_name']: bool(r['is_active'])
                      for _, r in fund_meta_df.iterrows()}
  File "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/scripts/queries.py",
      line 3658, in <dictcomp>
    fund_is_active = {r['fund_name']: bool(r['is_active'])
                      for _, r in fund_meta_df.iterrows()}
  File "pandas/_libs/missing.pyx", line 392, in pandas._libs.missing.NAType.__bool__
TypeError: boolean value of NA is ambiguous
```

### Failure site

[scripts/queries.py:3651-3658](scripts/queries.py:3651):

```python
fund_meta_df = con.execute(f"""
    SELECT DISTINCT fh.fund_name,
           MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active
    FROM fund_holdings_v2 fh
    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
    WHERE fh.fund_name IN ({ph_funds}) AND fh.quarter = '{quarter}'
    GROUP BY fh.fund_name
""", list(all_child_funds)).fetchdf()
fund_is_active = {r['fund_name']: bool(r['is_active']) for _, r in fund_meta_df.iterrows()}
```

The SQL is a `LEFT JOIN` on `fund_universe`. When a child fund's `series_id` does not match any row in `fund_universe`, `MAX(CAST(... AS INTEGER))` over an empty group returns NULL, which pandas materialises as `pd.NA` (integer-typed column with nulls). `bool(pd.NA)` raises `TypeError: boolean value of NA is ambiguous`.

This path only fires for tickers that reach the child-fund N-PORT branch of `portfolio_context`; AAPL does because it has Vanguard/BlackRock N-PORT funds with no `fund_universe` match for at least one `series_id`.

### Hypothesis

Conviction tab 500 is a pandas nullability bug at queries.py:3658: `bool(r['is_active'])` is called on a `pd.NA` produced by an unmatched `LEFT JOIN fund_universe` where `series_id` does not resolve.

---

## §4 Fix-scope preview

### §1 Register %FLOAT — **frontend build only**
Pure artifact drift. The TSX/TS source is already post-rename (commit `f956096`). Fix is to rebuild `web/react-app/dist/` (`npm --prefix web/react-app run build`) and either commit the rebuilt bundle or wire the build into `scripts/start_app.sh` so a stale `dist/` can't outlive a rename again. No backend edit, no DB change. The fix should also double-check the `dist/` rebuild for any residual `pct_of_float` / `pct_float` strings before declaring done.

### §2 Flow Analysis duplication — **backend query only**
One-line-class fix in [scripts/queries.py:3156](scripts/queries.py:3156): add `AND rollup_type = ?` to the `investor_flows` SELECT (and pass `rollup_type` as the third bind). Frontend is fine — it already renders whatever rows the API gives it. Worth also checking the live-fallback branch (`_compute_flows_live`, line 3153) and any `summary_by_parent`-adjacent SELECT for the same oversight, since INF34 stated `summary_by_parent` PK now includes `rollup_type`. No migration, no backfill.

### §3 Conviction 500 — **backend only, trivial null-handling**
Fix at [scripts/queries.py:3658](scripts/queries.py:3658). Two equivalent options: (a) SQL — `COALESCE(MAX(CAST(fu.is_actively_managed AS INTEGER)), 0)` inside the SELECT; or (b) Python — `bool(r['is_active']) if pd.notna(r['is_active']) else False`. SQL form is preferable — it pushes the default into the source and avoids re-introducing the same bug on future callers of `fund_meta_df`. Worth a quick sweep for other `bool(r['...'])` on `LEFT JOIN`-sourced columns; none obvious in the same function but the pattern is easy to propagate.

---

## Severity ranking (most → least user-impacting)

1. **§3 Conviction 500** — tab does not load at all. Hard failure. Every ticker with an unmapped `series_id` in `fund_holdings_v2` hits this. **Fix first.**
2. **§2 Flow Analysis duplicates** — tab loads but data is visibly wrong and actively misleading (every institution shown twice at inflated ranks; counts sum incorrectly).
3. **§1 Register `% FLOAT`** — column renders `—` everywhere, but the rest of the Register tab (institution, shares, value, AUM%, type) is correct. Cosmetic-ish from a "can the user work?" standpoint, but a trust-degrading regression.

---

## Artifacts

- `/tmp/query1_response.json` — full query1 envelope, 1,695 lines
- `/tmp/flow_analysis_response.json` — full flow_analysis envelope, 2,433 lines
- `/tmp/portfolio_context_curl.txt` — verbose curl trace with headers

Flask remained live throughout (PID 24145). No DB writes, no schema changes, no fixes applied.
