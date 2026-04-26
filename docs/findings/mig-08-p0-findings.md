# mig-08-p0 — Phase 0 findings: INF42 derived-artifact hygiene

_Prepared: 2026-04-22 — branch `mig-08-p0` off main HEAD `4ced172`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-08` (Batch 3-D). Scope per row: `.gitignore`, `web/react-app/dist/`, `tests/fixtures/13f_fixture.duckdb`, build scripts. Proposed fix: checksum/hash validation + forced rebuild triggers. Predecessor: `obs-13` (PR #65) — verified `web/react-app/dist/` clean post-ff1ff71 and explicitly left "INF42 (derived-artifact hygiene CI gate) remains a standing gap."_

Phase 0 is investigation only. No code changes, no DB writes, no edits to `.gitignore`. READ-ONLY inspection of the two in-scope derived artifacts, their tracking state, the current rebuild tooling, and the checksum surface — plus a proposal with open questions for Serge sign-off.

---

## §1. Artifact #1 — `web/react-app/dist/`

**Current on-disk state.** Directory does not exist in the worktree (`ls web/react-app/dist/` → "No such file or directory"). Clean slate; nothing to compare against source.

**Git tracking.** Not tracked:

```
$ git ls-files web/react-app/dist/
(empty)
```

**Ignore coverage.** Two layers:

1. **Nested `web/react-app/.gitignore`** (6 lines) ignores `dist/`:
   ```
   node_modules/
   dist/
   *.log
   .vite/
   test-results/
   playwright-report/
   ```
   This is the authoritative rule — Vite's default scaffold and sufficient by itself.

2. **Repo-root [`.gitignore`](.gitignore)** line 44 ignores `web/static/dist/` (a *different* path — the legacy Flask static bundle location, not the React SPA build output). Root gitignore does not mention `web/react-app/dist/`.

**Build command.** [web/react-app/package.json:6](web/react-app/package.json:6) — `npm run build` → `tsc -b && vite build`. No checksum or provenance stamped into output bundle.

**Closure status.** obs-13 (PR #65, 2026-04-19) verified the served dist bundle was free of `pct_of_so` post-ff1ff71 and closed that specific regression. INF42 as a CI gate remained open — no automated test catches "someone rebuilt locally with stale source" or "someone committed `web/react-app/dist/` by mistake."

**Upshot for mig-08.** The `dist/` portion is already in a reasonable state on the tracking axis (nested ignore works, nothing committed, obs-13 verified last build was clean). The gap is *defence-in-depth*: there's no repo-level hardening against a contributor accidentally removing the nested `.gitignore` or running `git add -f web/react-app/dist/` and shipping a stale bundle.

---

## §2. Artifact #2 — `tests/fixtures/13f_fixture.duckdb`

**Current on-disk state.** Present, 13 MB (`13,119,488 bytes`), mtime `Apr 22 04:53`. Last two touching commits:

- `ff1ff71` — post-merge-fixes: CI smoke fixture regenerated (SOH table + snapshots)
- `8cf0d82` — feat: Phase 0-B2 — smoke CI fixture + response snapshot tests (initial creation)

**Git tracking.** Tracked:

```
$ git ls-files tests/fixtures/
tests/fixtures/13f_fixture.duckdb
tests/fixtures/responses/entity_graph.json
tests/fixtures/responses/query1.json
tests/fixtures/responses/summary.json
tests/fixtures/responses/tickers.json
```

Total size: 13 MB (the fixture dominates; the four response JSONs are small). Binary `.duckdb` file — diffs are opaque, review leans entirely on the build script.

**Ignore coverage.** Not in `.gitignore`. Committing is the design choice, not an oversight.

**Design intent.** [docs/ci_fixture_design.md](docs/ci_fixture_design.md) §Option 2 (Phase 0-B1 decision, 2026-04-13): *"committed binary snapshot + rebuild script"*. Explicitly chose commit-the-blob over seed-from-SQL (Option 1) or parquet-export (Option 3). Rationale captured in :76-91: "Schema is captured automatically… entity rollup + classification + identifier chains are inherently consistent because they were filtered out of a live, validated prod DB."

**Size overshoot.** Design target: "< 1 MB" ([docs/ci_fixture_design.md:72](docs/ci_fixture_design.md:72)). Actual: 13 MB — 13× the target. Not blocking (13 MB binary in git is still tractable), but worth flagging as drift against the captured decision.

**CI enforcement today.** [.github/workflows/smoke.yml:47-50](.github/workflows/smoke.yml:47):

```yaml
- name: Verify fixture DB committed
  run: |
    test -f tests/fixtures/13f_fixture.duckdb \
      || (echo "Missing tests/fixtures/13f_fixture.duckdb — run scripts/build_fixture.py and commit it" && exit 1)
    ls -lh tests/fixtures/13f_fixture.duckdb
```

Presence-only check. No content validation, no schema validation, no staleness detection.

---

## §3. Rebuild tooling inventory

**Fixture rebuild — [scripts/build_fixture.py](scripts/build_fixture.py)** (310 lines, tracked):

- ATTACH prod READ-ONLY (safety guard — aborts if `--source` and `--dest` resolve to the same path; aborts if dest exists without `--force`)
- Selects 4 reference tickers (`AAPL`, `MSFT`, `EQT`, `NVDA`) and 1 quarter (`2025Q4`)
- Walks the rollup / identifier / classification graph to produce a coherent slice
- Flags: `--dry-run`, `--force`, `--yes` (CI-friendly), `--source`, `--dest`, `--tickers`, `--quarter`, `--flow-quarters`
- No provenance metadata written to output DB (confirmed: `grep -c "checksum\|sha256\|hash" scripts/build_fixture.py` → 0)

**Response snapshot capture — `tests/smoke/capture_snapshots.py`** (referenced in earlier grep, not inspected in depth in Phase 0). Produces `tests/fixtures/responses/*.json`.

**React build — `npm run build`** in `web/react-app/` (vite + tsc). No wrapping script pins node version or emits a checksum.

**Gap.** No script or CI step computes a hash of the fixture after build, stamps it into a sidecar, or asserts the committed hash matches a regeneration done fresh against the current prod schema.

---

## §4. Checksum / validation surface today

Explicit audit:

| Check | Status |
|---|---|
| SHA256 sidecar (`*.sha256` or `.duckdb.sha256`) | ❌ none |
| Fixture metadata table (build timestamp, source DB hash, DuckDB version, builder git SHA) | ❌ none |
| CI step: rebuild fixture from prod + diff against committed | N/A — CI has no prod DB |
| CI step: verify committed fixture opens + has expected tables | ❌ none |
| CI step: verify committed fixture schema matches migrations count | ❌ none |
| CI step: verify `dist/` is absent from `git ls-files` | ❌ none |
| Pre-commit hook: block accidental `git add web/react-app/dist/*` | ❌ none |
| Pre-commit hook: prompt-or-rebuild on migration file change | ❌ none |

Net: the only hygiene today is `test -f` on the fixture and human discipline on the dist bundle.

---

## §5. Proposed Phase 1 changes

Three buckets, independently shippable, ordered by cost:

### Bucket A — `.gitignore` belt-and-braces (low cost, high clarity)

Add explicit entries to repo-root [`.gitignore`](.gitignore):

```
# React SPA build output — regenerated via `npm run build` in web/react-app/
web/react-app/dist/
```

**Redundant with nested ignore but defends against:** (a) contributor removing/editing the nested `.gitignore`; (b) onboarding readers who check root `.gitignore` to understand what's regenerated. The existing root-level comment "React build output" (line 43 header for `web/static/dist/`) reads as stale — `web/static/dist/` is the legacy Flask path; the live React SPA is `web/react-app/dist/`. Worth a comment update regardless.

**No-op for git tracking** — nothing is currently tracked in `web/react-app/dist/`, so no `git rm` needed.

### Bucket B — Fixture provenance metadata (medium cost, catches real staleness)

Extend [scripts/build_fixture.py](scripts/build_fixture.py) to write a small `_fixture_metadata` table into the fixture at build time:

| Column | Example value |
|---|---|
| `built_at` | `2026-04-22 04:53:12 UTC` |
| `source_db_mtime` | mtime of `data/13f.duckdb` at build time |
| `builder_git_sha` | `git rev-parse HEAD` |
| `duckdb_version` | `duckdb.__version__` |
| `reference_tickers` | `AAPL,MSFT,EQT,NVDA` |
| `fixture_quarter` | `2025Q4` |
| `max_migration_id` | max applied migration number at build time (if migrations tracked in a table) |

Add a CI step in `smoke.yml` that opens the fixture, reads `_fixture_metadata`, and asserts:

1. Table exists and has exactly one row.
2. `duckdb_version` matches the DuckDB pin in `requirements.txt` (catches version drift).
3. `max_migration_id` ≥ the count of migration files in `scripts/pipeline/migrations/` — or equal; Phase 1 spec to decide (catches "someone added migration 004 but didn't rebuild fixture").

**Pros.** Catches the two real staleness failure modes: schema drift (migration added, fixture not rebuilt) and version skew (DuckDB pin bumped, fixture built under old version). Zero runtime cost. Human-readable when inspecting the fixture locally.

**Cons.** Rebuild-after-migration becomes mandatory rather than advisory; shifts friction onto the schema-change author. Mitigated by clear error message and `build_fixture.py --force` one-liner.

### Bucket C — SHA256 sidecar (low cost, low signal — optional)

Commit `tests/fixtures/13f_fixture.duckdb.sha256` alongside the binary; CI recomputes hash and asserts match. Catches only *tampering* — a corrupted fixture still hashes identically if DB is intact. Staleness detection (Bucket B) is the higher-value play. **Recommend defer or drop** unless audit requirement surfaces.

### Bucket D — Forced rebuild triggers (out of scope for mig-08)

Pre-commit hook that diffs staged migration files against the fixture's recorded `max_migration_id` and blocks commit with a clear "run `scripts/build_fixture.py --force --yes`" message. Requires pre-commit framework is installed on every contributor's workstation and that migrations have a consistent numbering convention. **Recommend defer to a follow-up row** (`mig-08a` or similar) — the fixture-metadata CI gate from Bucket B already catches the same failure post-push. Pre-commit is a nicer-UX variant, not a correctness improvement.

### Recommended bundle

**Ship Bucket A + Bucket B in mig-08.** Skip C unless Serge wants it. Defer D.

---

## §6. Risk notes

1. **Removing tracked files from git is a one-way door.** Bucket A is additive-only (just a new ignore line + comment edit) — no `git rm` needed since nothing is currently tracked under `web/react-app/dist/`. Safe.

2. **Binary fixture is not being removed.** Bucket B extends the build script and the fixture's internal schema; it does not change the "committed binary snapshot" decision from `ci_fixture_design.md`. No history rewrite, no `git rm --cached`, no force-push.

3. **Metadata schema backward-compat.** Adding `_fixture_metadata` is a new table; existing smoke tests reference specific fact/dim tables only and won't see it. CI assertion step would be new — first rollout must rebuild the fixture so the table exists, otherwise the assertion step fails on the very first CI run. Phase 1 PR must bundle: (a) script change, (b) regenerated fixture, (c) CI step addition. All three land together.

4. **Strict `max_migration_id` equality check** (Bucket B variant 3b) could paint Serge into a corner where every migration-adding PR must also regenerate the fixture or CI fails. Weaker `≥` variant is preferable — Phase 1 spec. Worth explicit decision.

5. **13 MB overshoot vs 1 MB design target** is not directly addressed by mig-08 as written. If Serge wants to act on it, scope expands — ticker count reduction, quarter count reduction, or per-table row caps would need design work. Recommend flagging but not blocking this batch.

6. **No prod DB in CI.** All proposed checks assume the fixture is pre-built locally by a contributor with prod-DB access. CI validates the committed artifact but cannot regenerate from source — this preserves the Phase 0-B1 design decision.

---

## §7. Open questions for Serge — Phase 1 sign-off

**Q1. Bucket A alone, A+B, or A+B+C?** Recommendation: A+B (explicit ignore + fixture provenance metadata + CI staleness gate). Skip C unless there's a compliance/audit reason.

**Q2. `max_migration_id` comparison semantics.** Strict equality (`=`) or forward-compat (`≥`)? Strict equality catches stale fixtures but forces fixture rebuild in every schema PR. `≥` catches the common case (forgot to rebuild after adding migration) without the ergonomic cost. Recommendation: `≥`.

**Q3. Defer Bucket D (pre-commit hook) to `mig-08a`?** Yes recommended. The CI gate from B is sufficient for correctness; pre-commit is UX polish.

**Q4. 13 MB → 1 MB target.** In scope or separate row? Recommendation: **new row** (`mig-08b` or fold into an ambient cleanup batch). Requires fixture redesign discussion, not derived-artifact hygiene per se.

**Q5. Response snapshots (`tests/fixtures/responses/*.json`) — do they get metadata too?** They're regenerated by `tests/smoke/capture_snapshots.py`. Smaller surface, lower risk of staleness (they're driven by the fixture itself). Recommendation: out of scope for mig-08; if the fixture is stamped and staleness-gated, the snapshots follow.

---

## §8. Dependency and ordering notes

- Phase 1 PR must bundle: script edit + regenerated fixture (new `_fixture_metadata` table) + `smoke.yml` step + root `.gitignore` edit. Landing them separately creates a flaky middle commit.
- Migration numbering convention. If migrations are filenames like `001_*.sql` the `max_migration_id` check works out of the box. Phase 1 will need to confirm the actual convention — [scripts/pipeline/](scripts/pipeline/) should have this; Phase 0 did not inspect.
- DuckDB version pin. `requirements.txt` pins `duckdb==1.4.4`. Bucket B's version-match assertion assumes this is authoritative — no drift between local dev and CI. If contributors regularly build fixtures under `duckdb` master or an unpinned dev version, the check would fail spuriously. Phase 1 should verify current practice.
- obs-13 has already shipped. No conflicts — mig-08 extends hygiene past the point obs-13 stopped.

---

_End of Phase 0 findings. No code changes, no DB writes, no `.gitignore` edits. Findings doc is the only artifact._
