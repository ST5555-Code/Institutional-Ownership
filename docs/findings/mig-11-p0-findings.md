# mig-11-p0 — Phase 0 findings: INF47 schema-parity CI wiring

_Prepared: 2026-04-22 — branch `mig-11-p0` off main HEAD `25a0263`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-11` (Batch 3-D). Predecessors: `mig-09` (L4 extension, PR #74) and `mig-10` (L0 extension, PR #74) both shipped. Source design: `docs/findings/2026-04-19-block-schema-diff.md` §10 Q5 / §14 INF47 (deferred CI wiring)._

Phase 0 is investigation only. No code changes, no DB writes. READ-ONLY inspection of the workflow file, validator behaviour, fixture inventory, and test coverage — plus a design proposal for CI integration with two open questions for Serge sign-off.

---

## §1. Current `.github/workflows/smoke.yml` at HEAD

[.github/workflows/smoke.yml](.github/workflows/smoke.yml) (53 lines). Single job `smoke` on `ubuntu-latest`:

1. `actions/checkout@v6`
2. `actions/setup-python@v6` — Python 3.11, pip cache
3. **Install runtime deps** (pinned to `requirements.txt`): `duckdb==1.4.4`, `fastapi==0.115.4`, `httpx==0.28.1`, `jinja2==3.1.6`, `pandas==2.3.3`, `pydantic==2.12.5`, `requests==2.32.5`, `openpyxl==3.1.5`, `rapidfuzz==3.13.0`, `tabulate==0.9.0`, `uvicorn==0.39.0`, `pytest==8.3.3`. **Does not install `pyyaml`** — required by `load_accept_list` ([validate_schema_parity.py:572](scripts/pipeline/validate_schema_parity.py:572)).
4. **Verify fixture DB committed** — `test -f tests/fixtures/13f_fixture.duckdb`
5. **Run smoke tests** — `pytest tests/smoke/ -v`

Triggers on every push to any branch and on every PR. Concurrency group cancels in-progress runs on the same ref.

**Sibling workflow.** [.github/workflows/lint.yml](.github/workflows/lint.yml) runs `pre-commit` (ruff + pylint + bandit) in a separate job. No shared state.

---

## §2. Fixture DB inventory

[tests/fixtures/13f_fixture.duckdb](tests/fixtures/13f_fixture.duckdb) — **13 MB, 21 user tables**. Introspected with `duckdb_tables()` filtered to `database_name = current_database() AND schema_name = 'main'`:

| Fixture table | Layer | In inventory? |
|---|---|---|
| `entities` | L3 MDM core | yes |
| `entity_identifiers` | L3 MDM core | yes |
| `entity_relationships` | L3 MDM core | yes |
| `entity_aliases` | L3 MDM core | yes |
| `entity_classification_history` | L3 MDM core | yes |
| `entity_rollup_history` | L3 MDM core | yes |
| `entity_overrides_persistent` | L3 MDM core | yes |
| `fund_universe` | L3 ref | yes |
| `ncen_adviser_map` | L3 ref | yes |
| `securities` | L3 ref | yes |
| `market_data` | L3 ref | yes |
| `shares_outstanding_history` | L3 ref | yes |
| `fund_holdings_v2` | L3 fact | yes |
| `holdings_v2` | L3 fact | yes |
| `beneficial_ownership_current` | L4 derived | yes |
| `summary_by_parent` | L4 derived | yes |
| `summary_by_ticker` | L4 derived | yes |
| `ticker_flow_stats` | L4 derived | yes |
| `managers` | L4 derived | yes |
| `fund_family_patterns` | L4 derived | yes |
| `data_freshness` | L0 control-plane | yes |

**Count vs inventory.** Fixture covers 14 of 29 L3 tables (48%), 6 of 14 L4 tables (43%), 1 of 6 L0 tables (17%) — 21 of 49 overall (43%).

**Missing tables** (present in inventory but absent from fixture): 15 L3, 8 L4, 5 L0 — see §4 below for the `TABLE MISSING` blast-radius.

**Fixture builder.** [scripts/build_fixture.py](scripts/build_fixture.py) (exists, not inspected here — fixture rebuild procedure is `mig-08` territory).

---

## §3. Validator exit codes, missing-table behaviour, and CLI shape

From [scripts/pipeline/validate_schema_parity.py](scripts/pipeline/validate_schema_parity.py):

**Exit codes** (:24-27, :838-844):
- **0** — parity, or all divergences accepted without `--fail-on-accepted`
- **1** — unaccepted divergence OR expired accept-list entry
- **2** — invocation error (missing DB file, YAML parse failure, unknown tables/dimensions, `duckdb` not installed)

**Missing-table handling** ([compare_table:499-531](scripts/pipeline/validate_schema_parity.py:499)):
- Missing **both sides** → silently skipped, no divergence (nothing to compare)
- Missing **one side only** → single clean `ddl / TABLE MISSING` divergence, per-dimension comparators skipped (prevents column-by-column flood from the missing side)
- Present both sides → normal column / index / constraint / ddl comparison

**Self-parity (both paths identical).** The validator does not short-circuit when `--prod` and `--staging` resolve to the same file. It opens two independent `duckdb.connect(..., read_only=True)` handles, runs introspection against each, and compares. Because the two handles read the same file, every comparator returns 0 divergences — a trivially-green result that exercises the full code path including introspection + normalizers, but carries no cross-DB parity signal.

**CLI shape relevant to CI:**
- `--prod`, `--staging` — DB paths (resolved relative to repo root)
- `--layer {l3,l4,l0,all}` — default `l3`
- `--tables <csv>` — narrow to a subset; rejected if any name not in the active `--layer` inventory ([:902-911](scripts/pipeline/validate_schema_parity.py:902))
- `--dimensions <csv>` — default all four (`columns,indexes,constraints,ddl`)
- `--accept-list <path>` — default `config/schema_parity_accept.yaml`
- `--fail-on-accepted` — flip accepted divergences to hard fails
- `--json` — machine-readable report to stdout
- `--verbose` — per-table scan trace to stderr

---

## §4. Self-parity outcome against the fixture (projected)

Not executed in Phase 0 (no code runs), but behaviour is determinate from §2 + §3:

**Scenario A.** `--prod fixture.duckdb --staging fixture.duckdb --layer l3`
- 29 tables scanned. 14 present on both sides → 0 divergences.
- 15 absent on both sides → silently skipped per `compare_table` both-sides-missing guard.
- **Exit 0.** Zero rows. Zero signal.

**Scenario B.** `--prod fixture.duckdb --staging fixture.duckdb --layer all`
- 49 tables. 21 present both sides → 0 divergences. 28 absent both sides → silently skipped.
- **Exit 0.** Still zero signal — the skip rule eats every gap.

**Scenario C.** `--prod fixture.duckdb --staging empty-or-sparse.duckdb --layer all`
- Would surface the absent tables as `TABLE MISSING` rows. But CI has no "second DB" to contrast against the fixture, so this scenario is infrastructure we'd have to build before it's reachable.

**Upshot.** The validator's real product — cross-DB parity between two materially-different schemas — is unreachable from CI today, exactly as flagged in `2026-04-19-block-schema-diff.md` §10 Q5 and §14 INF47. The fixture is built fresh from a single source and never exhibits drift against itself.

---

## §5. Existing test coverage — what's *already* wired and what's missing

[tests/pipeline/test_validate_schema_parity.py](tests/pipeline/test_validate_schema_parity.py) — **885 lines of pure-Python unit tests** exercising the comparator logic. Test classes (partial, via `grep`):

- `TestDDLWhitespaceNormalizer` — whitespace collapse, line-ending normalization, semicolon trimming, empty-string edge cases
- `TestPKIndexEquivalence` — PK ↔ UNIQUE-index normalization in both directions, column-order flexibility
- Plus: `load_accept_list` validation, `compare_columns`/`compare_indexes`/`compare_constraints`, expiry-date parsing, `TABLE MISSING` guard (from mig-09 work)

**Currently skipped in CI.** `smoke.yml` step 5 runs `pytest tests/smoke/` — `tests/pipeline/` is out of scope. The validator's unit tests run only via local dev invocation or `pre-commit`'s test hooks (none configured).

This is the single largest gap: 885 lines of validator-specific regression tests sit outside the CI loop despite being free to run (pure logic, no DB handles, imports only `duckdb`+`pytest`).

---

## §6. CI integration design — three options

### Option A — Unit-test wiring (recommended)

Extend `smoke.yml` step 5 from `pytest tests/smoke/` to `pytest tests/smoke/ tests/pipeline/test_validate_schema_parity.py` (or broaden to `tests/pipeline/` if other tests there are CI-safe — needs a quick audit). Add `pyyaml` to the install-deps step so `load_accept_list` tests can run.

**Pros:**
- Highest signal-to-cost ratio. 885 lines of existing regression coverage for the comparator logic, already written, already passing.
- Catches real regressions: if a future change breaks `normalize_ddl_whitespace`, `compare_columns` accounting, or accept-list parsing, CI fails immediately.
- Pure logic — no DB, no flakiness. Runs in seconds.
- Unblocks safe future extension of the validator (mig-09, mig-10, future layer additions).

**Cons:**
- Does not exercise the end-to-end validator against a real DuckDB file. Introspection-layer bugs (e.g. a DuckDB 1.4 → 1.5 system-table rename) would still slip through.
- Does not actually run `validate_schema_parity.py` as an executable — only its library functions.

### Option B — Unit tests + self-parity liveness check

Option A plus: run `python scripts/pipeline/validate_schema_parity.py --prod tests/fixtures/13f_fixture.duckdb --staging tests/fixtures/13f_fixture.duckdb --layer all --json > /tmp/parity.json` and assert exit code 0. Acts as a liveness test — catches DuckDB API drift, accept-list YAML parse errors, validator import failures — but produces zero parity signal (see §4).

**Pros:**
- Covers the CLI-level wiring unit tests cannot reach (argparse, `_resolve`, `duckdb.connect`, `duckdb_tables()` / `duckdb_indexes()` / `duckdb_constraints()` / `duckdb_columns()` queries).
- Trivially green on any correctly-installed stack.
- Would have caught, e.g., a `duckdb_tables()` column rename in a DuckDB bump.

**Cons:**
- Zero parity signal. Both sides of the comparison are the same file.
- Adds ~1-2 s to CI and a second step to maintain.

### Option C — Full parity gate (out of scope for mig-11)

Commit a second synthetic fixture (`13f_fixture_staging.duckdb`) deliberately engineered to exhibit known accepted divergences; run the validator against both; assert the expected JSON output. This tests the comparators end-to-end against real DuckDB introspection, against real divergence. But it requires fixture authoring, a maintenance story for two fixtures, and doubles the review surface. This is the infrastructure gap INF47 foresaw.

**Recommendation: defer to a follow-up block (`mig-11a` or a new row)** — it's real work and changes the shape of `mig-08` fixture tooling. mig-11 should ship the lowest-friction wins.

### Recommended bundle

**Ship Option A in mig-11.** Optionally add Option B if Serge wants a CLI-level smoke — it's 4 lines of YAML and carries its own weight. **Defer Option C.**

---

## §7. Answers to the tasked design questions

**4a. Which layers to validate in CI?**
- Unit tests (Option A) cover all three layers automatically — `tables_for_layer` and the `L3_TABLES` / `L4_TABLES` / `L0_TABLES` constants are exercised in the test module.
- If a CLI smoke step is added (Option B), use `--layer all`. It's free — the missing-both-sides skip rule means every absent table silently no-ops. Running `all` future-proofs against anyone extending the fixture without updating the CI command.

**4b. What serves as "staging" in CI?** The fixture, if Option B is adopted. There is no second DB.

**4c. What serves as "prod" in CI?** Also the fixture (same path). Trivial parity by construction. This is not a bug — §4 documents why the cross-DB value is unreachable until Option C ships.

**4d. Does the validator need a `--self-check` mode?** No new flag is required. The current validator already handles self-parity correctly (runs the full pipeline, returns 0). Adding a flag would be ceremonial. If Serge wants the intent to be explicit in CI, a comment in the workflow file is cheaper than a CLI flag and accept-list plumbing.

---

## §8. Hard-fail vs warning semantics

Question: should the CI step treat validator divergences as hard failure or warning?

**For Option A (unit tests).** Always hard fail. Unit-test failure = regression. No gray zone.

**For Option B (self-parity smoke).** Hard fail on exit 1 or 2. Exit 0 is expected; anything else means the validator itself is broken.

**For Option C (cross-DB parity, future).** Hard fail, with the accept-list providing the escape valve. This matches the baseline policy from INF39 Option B (`2026-04-19-block-schema-diff.md` §13.2): remediate-all, zero-baseline, any new drift is real drift.

No warning tier needed in any scenario. The accept-list already serves the "known-accepted drift" role.

---

## §9. Dependency and ordering notes

- **pyyaml.** `load_accept_list` requires PyYAML ([validate_schema_parity.py:46-48](scripts/pipeline/validate_schema_parity.py:46)). Currently installed transitively via `pre-commit`, but smoke.yml does not pull pre-commit. Adding `pyyaml==6.0.2` (or the version in `requirements.txt`) to the runtime-deps step is a prerequisite for Option A.
- **Duckdb version pin.** Fixture was produced under DuckDB 1.4.4 (per `requirements.txt` pin matching `smoke.yml`). A later bump triggers a re-introspection risk — Option B would surface this.
- **Order of workflow steps.** New CI steps should run *after* the fixture-verify step (so the `test -f` guard still fires first) and can co-locate with the pytest step. No dependency on `lint.yml`.

---

## §10. Open questions for Serge — Phase 1 sign-off

**Q1. Option A or Option A+B?** Recommendation is Option A alone (unit tests). Option B adds a CLI-level smoke for ~1-2 s of CI time and modest maintenance; it's a judgement call.

**Q2. Broaden `pytest tests/smoke/` to `pytest tests/smoke/ tests/pipeline/` — audit needed?** `tests/pipeline/` contains at least one 885-line file. There may be sibling tests that need DB fixtures beyond `13f_fixture.duckdb` or mark-skip logic. A ~15-minute audit in Phase 1 confirms scope.

**Q3. Defer Option C to a new row or fold into mig-11?** Recommendation is a new row (`mig-11a` — "synthetic-staging parity fixture for CI"). The work crosses into `mig-08` fixture tooling and should not gate mig-11.

**Q4. Accept-list behaviour for CI-absent tables.** If Option B ships with `--layer all` against the fixture alone, there is no accept-list entry needed (the skip rule covers both-sides-missing). **No accept-list growth expected from mig-11.**

---

_End of Phase 0 findings. No code changes, no DB writes, no migrations. Findings doc is the only artifact._
