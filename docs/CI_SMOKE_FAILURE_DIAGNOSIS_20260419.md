# CI smoke workflow failure — diagnosis (2026-04-19)

## Workflow config

- [.github/workflows/smoke.yml](../.github/workflows/smoke.yml) —
  runs on push to `main` and on PRs. Single job `smoke` on `ubuntu-latest`:
  checkout → setup-python 3.11 → pip install pinned runtime deps →
  verify `tests/fixtures/13f_fixture.duckdb` is committed →
  `pytest tests/smoke/ -v`.
- [.github/workflows/lint.yml](../.github/workflows/lint.yml) — pre-commit (ruff + pylint + bandit). Not failing.

## Failing run

- Run: [24627971057](https://github.com/ST5555-Code/Institutional-Ownership/actions/runs/24627971057)
  (merge commit `7e68cf9`, 2026-04-19T11:26:36Z, 30s wall-clock).
- Failed test: `tests/smoke/test_smoke_endpoints.py::test_smoke_response_equality[query1-/api/v1/query1?ticker=AAPL]`.
- Assertion: `AssertionError: query1.rows: row count 104 outside ±5% of 25`.
- Other 7 smoke tests pass, including `test_smoke_endpoint_ok[query1]` and all
  three other equality tests (`tickers`, `summary`, `entity_graph`).

## Last-pass / first-fail commits

| Boundary | Run | Commit | Title |
| --- | --- | --- | --- |
| Last pass | [24614429508](https://github.com/ST5555-Code/Institutional-Ownership/actions/runs/24614429508) | `92b5bf0` | Merge `block-securities-data-audit` |
| First fail | [24617396603](https://github.com/ST5555-Code/Institutional-Ownership/actions/runs/24617396603) | `0dc0d5d` | Merge `block-3-fund-holdings-retirement` |

Every smoke run since `0dc0d5d` has failed with the same assertion. The
fixture DB (`tests/fixtures/13f_fixture.duckdb`) has not been touched since
Phase 0-B2 landed at `8cf0d82` on 2026-04-13 — so the fixture is not the
moving part.

Commits on the block-3 branch that landed between the two boundaries:

- `22278b8` refactor(nport): BLOCK-3 Phase 1 — extract N-PORT parsers + repoint legacy readers
- `118fb2f` fix(queries): repoint `has_table()` gates to `_v2` variants (BLOCK-3 addendum)  ← **root cause**
- `ec75ca2` feat(builders): add `--staging` gate to unblock BLOCK-3 Phase 2
- `334eac6` fix(enrich_holdings): gate Pass C on `securities.is_priceable`
- `a643b65`, `2405df1`, `6909031`, `8c654d9` — Phase 2/4 data apply + retire `fetch_nport.py`

## Root cause

Commit `118fb2f` flipped three `has_table()` gates in `scripts/queries.py`
from legacy table names to their `_v2` counterparts. The relevant gate for
`query1` is at `scripts/queries.py:792`:

```diff
-        if has_table('fund_holdings'):
+        if has_table('fund_holdings_v2'):
             nport_by_parent = get_nport_children_batch(parent_names, ticker, quarter, con, limit=5)
```

The fixture DB contains only the `_v2` tables (`fund_holdings_v2`,
`holdings_v2`) — no legacy `fund_holdings` / `holdings`. Verified:

```
$ python3 -c "import duckdb; ..." tests/fixtures/13f_fixture.duckdb
fund_family_patterns
fund_holdings_v2
fund_universe
holdings_v2
```

Consequence:

- **Pre-`118fb2f`**: `has_table('fund_holdings')` returned False on the
  fixture → `get_nport_children_batch()` was skipped → AAPL `query1.rows`
  held 25 parent-level rows. This was the state when
  `tests/fixtures/responses/query1.json` was captured.
- **Post-`118fb2f`**: `has_table('fund_holdings_v2')` returns True →
  N-PORT children are included → AAPL `query1.rows` now holds 104 rows
  (parents + N-PORT sub-fund breakdowns).

Totals are unchanged — the failing-run diff shows identical
`all_totals.value_live = 2521728609725.92`, `shares = 9853581626.0`, and
`pct_float = 67.0041` between actual and snapshot. Only the `rows` list
expanded as the N-PORT children section came online.

`query3` received the same fix at two more sites (`:1364`, `:1478`). It
is not monitored by smoke, so the effect there is not visible in CI, but
the same behavior applies.

## Failure classification

- **Class**: snapshot drift from an intentional, correctness-motivated
  query change.
- **Smoke test is working as designed**: the ±5% row-count tolerance
  caught the shape change exactly as the docstring at
  [`tests/smoke/test_smoke_endpoints.py:11-13`](../tests/smoke/test_smoke_endpoints.py:11)
  says it should — "regenerate via `python tests/smoke/capture_snapshots.py
  --update` after an intentional shape change."
- **`118fb2f` itself is not a bug.** The pre-fix state was a latent bug
  waiting to fire when the 2026-05-09 legacy-table DROP window lands. The
  commit is the correct fix; the snapshot simply was not refreshed as part
  of the merge.

## Proposed fix

**Scope: one-line / small.** Regenerate the four committed smoke
snapshots against the current fixture DB and commit the refreshed JSON:

```bash
python tests/smoke/capture_snapshots.py --update
git add tests/fixtures/responses/*.json
git commit -m "fix(ci): refresh smoke snapshots post BLOCK-3 has_table repoint"
```

Then push and confirm the workflow turns green on the branch before
merging. Only `tests/fixtures/responses/*.json` should change —
no code, no config, no fixture DB.

Confidence: **high**. Totals match exactly, only row count drifted, the
driving commit is documented and intentional, and the smoke suite itself
explicitly calls out this refresh procedure as the correct response.

## Non-fixes to avoid

- **Do not revert `118fb2f`.** It is a forward-looking correctness fix
  ahead of the 2026-05-09 legacy-table DROP.
- **Do not widen the ±5% tolerance.** A 4× row-count change should trip
  the guard; loosening it defeats the purpose.
- **Do not rebuild the fixture DB.** It matches prod shape today. The
  drift is in the snapshot, not the fixture.
- **Do not disable the smoke workflow.**
