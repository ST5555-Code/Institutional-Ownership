# obs-13: DIAG-23 Register %FLOAT Dist Bundle Verification

**Status:** PASS — recommend closing obs-13
**Date:** 2026-04-21
**Branch:** obs-13-verify

## Summary

The stale `pct_of_so` references flagged in DIAG-23 are absent from both the
React source tree and the currently-built dist bundle. The `pct_of_so →
pct_of_so` rename landed at the source layer in commit f956096 (pct-of-so Phase
1b, 2026-04-19 11:22 EDT) and the dist bundle in the main worktree was rebuilt
at 2026-04-19 15:26 EDT, after that source migration.

Commit ff1ff71 (post-merge-fixes CI smoke fixture regeneration, 2026-04-19 15:28
EDT) touched only `scripts/build_fixture.py`, `tests/fixtures/13f_fixture.duckdb`,
and `tests/fixtures/responses/*.json`. It did **not** modify any React source
under `web/react-app/src/`, so ff1ff71 does not require a dist rebuild.

## Evidence

### 1. Source layer is clean (no stale references)

```
$ grep -rn "pct_of_so" web/react-app/src/
(no matches)

$ grep -rn "pct_of_so\|pct_of_so\|FLOAT" web/react-app/src/components/tabs/RegisterTab.tsx
(no matches)
```

`RegisterTab.tsx` uses the `pct_so` field name exclusively (see
[api.ts:75](web/react-app/src/types/api.ts:75) — `RegisterRow.pct_so`) and
renders the column header as "% SO" (not "%FLOAT"):
- [RegisterTab.tsx:440](web/react-app/src/components/tabs/RegisterTab.tsx:440) — export header
- [RegisterTab.tsx:647](web/react-app/src/components/tabs/RegisterTab.tsx:647) — table header
- [RegisterTab.tsx:913](web/react-app/src/components/tabs/RegisterTab.tsx:913) — `fmtPctSo(row.pct_so)`

### 2. Dist bundle is clean

`web/react-app/dist/` is gitignored (see [.gitignore](web/react-app/.gitignore)) — it
is never committed to the repo; it is rebuilt locally or in CI. The current
bundle in the main worktree:

```
$ ls -la web/react-app/dist/assets/ | head -5
-rw-r--r--  BarChart-C0Gvj1h8.js       Apr 19 15:26
-rw-r--r--  RegisterTab-MyOzRHgg.js    Apr 19 15:26
...

$ grep -l "pct_of_so" web/react-app/dist/assets/*.js
(no matches)

$ grep -c "pct_of_so" web/react-app/dist/assets/*.js
FundPortfolioTab-BLLB4ISe.js:2  (matches source — exported CSV column name)
```

### 3. Dist timestamp vs. ff1ff71 timestamp

| Artifact              | Timestamp (EDT)      |
|-----------------------|----------------------|
| f956096 (src migrate) | 2026-04-19 11:22     |
| dist bundle           | 2026-04-19 15:26     |
| ff1ff71 (fixtures)    | 2026-04-19 15:28     |

The dist bundle is 2 minutes older than ff1ff71. That gap is irrelevant: ff1ff71
changed only CI fixture artifacts, not React source. The dist already reflects
the pct_of_so rename from f956096.

### 4. Test suite

```
$ pytest tests/ -x
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collected 97 items
...
======================== 97 passed, 1 warning in 6.49s =========================
```

## Recommendation

**Close obs-13.** The dist bundle is current with respect to the pct_of_so →
pct_of_so rename. No rebuild required in this remediation.

### Related standing gap (not blocking obs-13)

INF42 — "derived artifact hygiene" — remains open as a systemic risk: no
pre-commit or CI check re-runs `scripts/build_fixture.py` or the React build
when schema migrations land. If the next schema rename ships without a matching
dist + fixture refresh, the same DIAG-23 pattern could recur. Tracked separately.
