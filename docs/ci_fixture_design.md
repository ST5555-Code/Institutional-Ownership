# CI Fixture DB Design (Phase 0-B1)

_Created: 2026-04-13. Design-decision artifact. No code in this batch —
implementation lands in Phase 0-B2 per `ARCHITECTURE_REVIEW.md`._

## Problem

Phase 0-B2 wires four smoke endpoints (`/api/tickers`, `/api/query1`,
`/api/entity_graph`, `/api/summary`) into CI. Each must return HTTP 200
+ non-empty JSON against a committed fixture DB — never against
`data/13f.duckdb` (which is 12M+ rows, quarters of PII-adjacent holder
data, and absent from the CI runner).

Phase 0-B2 also commits response snapshots to
`tests/fixtures/responses/*.json` and asserts via
`test_smoke_response_equality()` that each endpoint returns the same
top-level keys, row-count ±5%, and at least one sentinel value. For
those assertions to be stable, the fixture DB must be **deterministic**
across CI runs and readable from whatever the smoke workflow starts.

## Surface area the fixture must cover

The 4 monitored endpoints touch approximately 14 tables once the
entity rollup and N-PORT children paths are exercised:

- Holdings / securities: `holdings_v2`, `fund_holdings_v2`,
  `fund_universe`, `market_data`, `securities`
- Entity MDM: `entities`, `entity_aliases`, `entity_identifiers`,
  `entity_relationships`, `entity_rollup_history`,
  `entity_classification_history`
- Reference: `fund_family_patterns` (new, Batch 3-A),
  `ncen_adviser_map`
- Summary: `summary_by_parent` (optional JOIN in query1 /
  portfolio_context)

All tables need consistent subsets — if a ticker appears in
`holdings_v2` but its holders have no `entity_aliases` rows, the
response shape changes. The fixture must be built as a coherent
slice, not table-by-table sampling.

## Three options

### Option 1 — Seed script from SQL text fixtures

**Shape.** `tests/fixtures/seed.sql` contains explicit
`CREATE TABLE` + `INSERT INTO` statements for every table the smoke
tests touch. CI runs `duckdb tests/fixtures/ci.duckdb < seed.sql` (or
a Python driver equivalent) as the first step of the smoke workflow,
then points the Flask app at `ci.duckdb`.

**Pros.**
- 100 % text in git — PRs diff cleanly. Changes in test data are
  reviewable line-by-line.
- Fixture lives next to the tests that exercise it; obvious coupling.
- Easy to hand-author a tiny tight subset (5 tickers, 20 holders each).

**Cons.**
- Schema drift is a footgun. When production adds a column (e.g. the
  `gics_code` fields pushed into the N-PORT queries in Batch 2-A, or
  the new `fund_family_patterns` table in 3-A), the seed SQL must be
  updated by hand. Easy to miss an added column until a smoke test
  surfaces the NULL.
- ~300–500 lines of hand-written INSERT data to cover 14 tables with
  coherent rows. Maintenance burden grows with every schema change.
- Entity rollup consistency is painful to fake — getting the ADV /
  parent-bridge / classification chain internally consistent requires
  understanding the MDM invariants for every fixture row.

**Implementation estimate.** ~1 day to author the initial seed +
validate against the four smoke endpoints + iterate on row sets until
shapes match production.

### Option 2 — Committed binary snapshot + rebuild script

**Shape.** A tiny DuckDB file (`tests/fixtures/13f_fixture.duckdb`,
target < 1 MB) is committed to the repo. A `scripts/build_fixture.py`
script rebuilds it from a read-only production connection by picking a
small set of reference tickers (e.g. AAPL, MSFT, EQT, NVDA) and
pulling the full support graph — every holder of those tickers, their
rollup chain, their N-PORT children, the relevant family patterns,
etc. The build script is the source of truth for "what's in the
fixture" and is reviewable.

CI step is `cp tests/fixtures/13f_fixture.duckdb /tmp/ci.duckdb` then
point the Flask app at `/tmp/ci.duckdb`. No DDL on CI startup; fixture
is already fully formed.

**Pros.**
- Schema is captured automatically. Adding a column in prod +
  re-running the build script picks it up with no further action.
- Entity rollup + classification + identifier chains are inherently
  consistent because they were filtered out of a live, validated prod
  DB.
- Build script defines intent in Python; binary file is the artifact.
- Zero DDL runtime at CI startup — fastest possible smoke workflow.

**Cons.**
- Binary files in git: PRs can't show meaningful diffs of the fixture
  itself, only of the build script and the committed snapshots. Git
  LFS is unnecessary at < 1 MB but the ergonomic cost remains.
- Rebuilding requires a local production DB. A CI runner cannot
  regenerate the fixture; contributors without the prod DB have to
  trust the committed blob.
- Adding a schema change requires the author to run the build script
  locally and commit the updated binary. One extra step per schema
  change.

**Implementation estimate.** ~2-3 hours — write
`scripts/build_fixture.py` that picks reference tickers, walks the
rollup / N-PORT / market-data chains, writes a filtered copy to
`tests/fixtures/13f_fixture.duckdb`. Validate size < 1 MB. Commit.

### Option 3 — Stripped `EXPORT DATABASE` dump

**Shape.** DuckDB's `EXPORT DATABASE` serializes a DB to a directory
of per-table parquet files + a single `schema.sql` + `load.sql`. The
output (stripped to the rows the smoke tests need) is committed to
`tests/fixtures/export_dir/`. CI runs
`IMPORT DATABASE 'tests/fixtures/export_dir'` into a fresh in-memory
or temp-file DB before tests.

**Pros.**
- Schema lives as plain-text `schema.sql` — reviewable in PRs.
- Per-table parquet files are smaller than a single DuckDB file.
- Same automatic-schema-capture benefit as Option 2.

**Cons.**
- Still binary for the data itself (parquet). Same PR-readability
  downside as Option 2.
- Has to be paired with a pre-strip step (a build script that
  constructs the filtered DB first, then `EXPORT`s it). So the build
  script is still needed — Option 3 ≈ Option 2 + an extra step.
- CI has to run IMPORT DATABASE (~seconds) on every workflow run
  instead of just copying a file.
- DuckDB `EXPORT DATABASE` includes every table present — including
  quarter-partitioned big fact tables — unless the pre-strip step
  deletes them first. Getting a small export requires extra work vs.
  Option 2 where filtering happens during SELECT INTO.

**Implementation estimate.** ~3 hours — write the pre-strip build +
EXPORT wrapper. Then commit the parquet directory.

## Comparison summary

| Axis | Opt 1 (SQL seed) | Opt 2 (binary snapshot) | Opt 3 (EXPORT dump) |
|---|---|---|---|
| PR-readable diffs of data | ✅ | ❌ (binary) | ❌ (parquet) |
| PR-readable diffs of schema | ✅ | ❌ (binary) | ✅ (schema.sql) |
| Automatic schema capture | ❌ | ✅ | ✅ |
| Entity consistency guaranteed | ❌ | ✅ | ✅ |
| Maintenance burden | high | low | low-medium |
| CI runtime overhead | 1-2 s | 0 s | 1-2 s |
| Repo size impact | ~50 KB text | ~500 KB binary | ~500 KB parquet |
| Implementation time | ~1 day | ~2-3 hours | ~3 hours |

## Recommendation — Option 2 (committed binary snapshot + rebuild script)

The dominant axis is **entity-graph consistency**. The smoke tests
exercise code paths that walk ADV, parent-bridge, classification, and
rollup-history chains simultaneously — inconsistencies across those
tables produce ghost entities, missing rollups, or surprise NULL
inst_parent_name values that an author hand-building seed SQL would
almost certainly introduce. Options 2 and 3 avoid this class of bug
entirely by filtering a live, validated production DB.

Option 2 beats Option 3 on simplicity: one file, one CI step (`cp`),
and no `IMPORT DATABASE` overhead. Option 3's parquet-readable-schema
advantage is real but small — the schema is also captured in
production's own DDL and in the build script. The binary-file
downside is mitigated by the accompanying build script being fully
reviewable in diffs.

Option 1 (SQL seed) is the wrong call here because the MDM graph is
the dominant source of fixture complexity. The tables it would
require us to hand-seed (`entity_rollup_history`,
`entity_relationships`, classification history) have strong internal
invariants that `validate_entities.py` enforces at promotion time.
Reproducing those invariants by hand-authored INSERT text is
equivalent to writing a second, unblessed test-scope validator, and
each schema change doubles the cost.

**Estimated Phase 0-B2 implementation time using Option 2**: half a
day total — 2-3 hours on the build script, 1 hour wiring the CI
workflow, 1 hour capturing the four response snapshots and writing
`test_smoke_response_equality()`.

## Acceptance criteria for Phase 0-B2 (carrying this decision forward)

- `scripts/build_fixture.py` exists, is idempotent, and produces
  `tests/fixtures/13f_fixture.duckdb` (< 1 MB) deterministically from
  a production DB.
- Build script picks a documented set of reference tickers and walks
  the full support graph so that all 4 smoke endpoints return
  non-empty bodies against the fixture.
- `.github/workflows/smoke.yml` copies the fixture into place, starts
  the Flask app against it, and runs the smoke test suite.
- `tests/fixtures/responses/*.json` holds one snapshot per endpoint.
  Snapshots are regenerated by a gated script (`--update` flag) — not
  by the test itself on failure.
- `test_smoke_response_equality()` asserts: HTTP 200, non-empty body,
  top-level keys present, row count within ±5 %, ≥ 1 sentinel value.

## Out of scope

- Implementation of `build_fixture.py` (Phase 0-B2).
- Choosing the reference tickers (Phase 0-B2 will pick from
  `{AAPL, MSFT, EQT, NVDA}` or similar — the selection itself is a
  small follow-up, not a design question).
- Extending the smoke coverage beyond the 4 endpoints. That is a
  separate expansion — gate it on Phase 0-B2 being stable first.
