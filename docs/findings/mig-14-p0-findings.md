# mig-14-p0 — Phase 0 findings: REWRITE_BUILD_MANAGERS remaining scope verification

_Prepared: 2026-04-22 — branch `mig-14-p0` off main HEAD `4484137`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3-B row `mig-14` (REWRITE_BUILD_MANAGERS remaining scope). `docs/REMEDIATION_CHECKLIST.md:85` still shows the item as `[ ]` open. This Phase 0 cross-references the original scope against HEAD and recommends disposition._

Phase 0 is investigation only. No code writes and no DB writes were performed.

---

## §1. Original mig-14 scope

From `docs/REMEDIATION_PLAN.md:133`:

> mig-14 | REWRITE_BUILD_MANAGERS remaining scope (INF1 staging routing + --dry-run + data_freshness) | … | OPEN | `scripts/build_managers.py`, `scripts/db.py` (CANONICAL_TABLES), `scripts/promote_staging.py` (PK_COLUMNS + new `rebuild` kind) | …

Three explicit deliverables:
1. **INF1 staging routing** — builder must be able to write to the staging DB.
2. **`--dry-run`** — a no-writes preview mode.
3. **`data_freshness` stamps** — every output table stamped post-build.

Plus the supporting plumbing noted in "files": `db.CANONICAL_TABLES` must list the outputs, and `promote_staging.PK_COLUMNS` must be extended along with a new `rebuild` promote kind.

---

## §2. HEAD verification — `scripts/build_managers.py`

Read the full file at HEAD (`4484137`). Every original-scope deliverable is present and wired into `main()`:

| Deliverable | Status | Evidence |
|---|---|---|
| a. `--staging` flag | **LIVE** | Arg declared at [build_managers.py:728-730](scripts/build_managers.py:728); honoured via `db.set_staging_mode(True)` at [:770](scripts/build_managers.py:770); `db.seed_staging()` called when `--staging` at [:784-785](scripts/build_managers.py:784). |
| b. `--dry-run` flag | **LIVE** | Arg declared at [build_managers.py:735-738](scripts/build_managers.py:735); threaded into every CTAS/UPDATE via `dry_run=args.dry_run` at [:794](scripts/build_managers.py:794), [:797](scripts/build_managers.py:797), [:800](scripts/build_managers.py:800), [:805](scripts/build_managers.py:805); individual builders short-circuit with `[dry-run] would …` projection messages at [:323-329](scripts/build_managers.py:323), [:466-479](scripts/build_managers.py:466), [:510-528](scripts/build_managers.py:510), [:654-664](scripts/build_managers.py:654). |
| c. `--enrichment-only` mode | **LIVE** | Arg declared at [build_managers.py:739-747](scripts/build_managers.py:739); skip branch at [:792](scripts/build_managers.py:792) bypasses the four CTAS builds and only runs `enrich_holdings_v2`. |
| d. `db.seed_staging()` under `--staging` | **LIVE** | [build_managers.py:784-785](scripts/build_managers.py:784). |
| e. `record_freshness` on all outputs | **LIVE** | `parent_bridge` at [:336](scripts/build_managers.py:336); `cik_crd_links` at [:487](scripts/build_managers.py:487); `cik_crd_direct` at [:497](scripts/build_managers.py:497); `managers` at [:619](scripts/build_managers.py:619); `holdings_v2` at [:681](scripts/build_managers.py:681). All five outputs covered. |
| f. Fail-fast input guards | **LIVE (bonus)** | `_assert_inputs_present(con)` at [:233-249](scripts/build_managers.py:233), invoked at [:790](scripts/build_managers.py:790). |

Commits delivering the work (from `git log scripts/build_managers.py`):
- `67e81f3` — `feat(build_managers): --dry-run, --staging, fail-fast, retrofits` (239 insertions).
- `2a71f8a` — `fix(build_managers): dedupe parent_bridge on cik` (cik-uniqueness fix enabling `pk_diff` promote).
- `4e64473` — `feat(build_managers): COALESCE on holdings_v2 enrichment — preserve legacy` (preserves the `backfill_manager_types.py` curation during enrichment UPDATE).
- `1719320` — `refactor(build_managers): repoint holdings enrichment to holdings_v2` (the original "holdings retire" partial-close already on the checklist).

---

## §3. HEAD verification — `scripts/promote_staging.py`

Read the full file at HEAD. Both supporting artifacts are present:

| Deliverable | Status | Evidence |
|---|---|---|
| a. `PK_COLUMNS` entries for build_managers outputs | **LIVE** | `parent_bridge: ["cik"]` at [promote_staging.py:67](scripts/promote_staging.py:67); `cik_crd_direct: ["cik"]` at [:68](scripts/promote_staging.py:68). The comment block at [:63-66](scripts/promote_staging.py:63) explicitly documents the rationale ("added 2026-04-19 — Batch 3 close"). |
| b. New `rebuild` promote kind | **LIVE** | `PROMOTE_KIND` dict at [promote_staging.py:122-126](scripts/promote_staging.py:122) maps `managers` and `cik_crd_links` to `"rebuild"`. |
| c. Rebuild dispatch | **LIVE** | `_kind_for()` helper at [promote_staging.py:129-131](scripts/promote_staging.py:129); `_apply_table()` dispatches on kind at [:326-329](scripts/promote_staging.py:326); `_apply_table_rebuild()` full-replace implementation at [:310-323](scripts/promote_staging.py:310). |
| d. Rebuild-safe snapshot restore | **LIVE** | `_restore_snapshot()` at [:157-191](scripts/promote_staging.py:157) branches on `_kind_for(t) == "rebuild"` for both teardown (DROP vs DELETE) and rehydrate (CREATE AS SELECT vs INSERT) paths — so rollback works correctly even after a `rebuild`-kind forward path changed the schema. |
| e. Rebuild-aware dry-run | **LIVE** | `_count_diff()` rebuild branch at [:424-427](scripts/promote_staging.py:424); `dry_run()` rebuild message at [:511-515](scripts/promote_staging.py:511). |
| f. Validator map coverage | **LIVE (with intentional None entries)** | `VALIDATOR_MAP` at [:86-105](scripts/promote_staging.py:86) explicitly maps all four build_managers outputs to `None`, triggering the `[warn] No validator registered …` path. Matches the entity-table pattern for canonical reference tables with no registered validator. |

---

## §4. HEAD verification — `scripts/db.py`

Read the relevant constants (via Grep). All four build_managers outputs are in `CANONICAL_TABLES`:

| Table | Location in db.py |
|---|---|
| `parent_bridge` | [db.py:130](scripts/db.py:130) |
| `cik_crd_direct` | [db.py:131](scripts/db.py:131) |
| `managers` | [db.py:132](scripts/db.py:132) |
| `cik_crd_links` | [db.py:133](scripts/db.py:133) |

The comment block at [db.py:117-126](scripts/db.py:117) attributes the addition to "the build_managers.py REWRITE (Batch 3 close)" on 2026-04-19. `PROMOTABLE_TABLES = ENTITY_TABLES + CANONICAL_TABLES` at [db.py:141](scripts/db.py:141) means `--tables` validation in `promote_staging.py` accepts these names automatically.

---

## §5. Cross-reference with sec-05-p0 findings

`docs/findings/sec-05-p0-findings.md` §2 (line 91) already reached the same conclusion when triaging its own scope boundary:

> **What remains.** Nothing, code-wise. The builder is fully routable + dry-runnable + promotable. The only open question is whether `docs/REMEDIATION_CHECKLIST.md` line 85 (`mig-14`) should be flipped to closed — that's a checklist-hygiene task, not a code task.

And §5 (line 93):

> **Conclusion.** `build_managers.py` is **not in sec-05 scope**. The `REMEDIATION_PLAN.md` line 161 claim "`scripts/build_managers.py` (routing pending)" is **stale** — routing shipped in `67e81f3`. Confirmed by reading the file and git log.

sec-05 then shipped under PR #43 / PR #45. This Phase 0 independently re-verified the file and confirms sec-05's reading is accurate.

---

## §6. Scope-boundary dependencies — still clean

`docs/REMEDIATION_PLAN.md:248` and `:251` flag two scope-boundary risks involving mig-14:

1. **int-14 ↔ mig-14** — share `scripts/promote_staging.py` + `scripts/merge_staging.py`. The risk was "mig-14 proposes a new `rebuild` strategy that may collide with int-14 mode."

   **Resolution.** The `rebuild` kind is already in `promote_staging.py:122-126` and is orthogonal to `merge_staging.py`'s NULL-only semantics (which is int-14's subject). `_kind_for()` dispatch is additive — int-14 can later extend `PROMOTE_KIND` with a new kind or change `merge_staging.py` semantics without touching `rebuild`. No collision observed at HEAD.

2. **sec-05 ↔ mig-14** — same file, different perspectives. Must be merged into one scope.

   **Resolution.** sec-05 shipped (PR #43 / #45) and `docs/findings/sec-05-p0-findings.md` §5 confirms `build_managers.py` was already out of sec-05 scope by the time Phase 0 ran. The two items converged cleanly.

No residual scope boundary conflict remains.

---

## §7. Recommendation

**mig-14 is already satisfied at HEAD.** The three original-scope deliverables (INF1 staging routing, `--dry-run`, `data_freshness` stamps) plus the supporting plumbing (`db.CANONICAL_TABLES`, `promote_staging.PK_COLUMNS`, new `rebuild` promote kind) are all live and commit-provable.

**No code change required.**

Two doc-hygiene follow-ups, both out of this Phase 0's scope (no-code findings only):

1. `docs/REMEDIATION_CHECKLIST.md:85` — flip `[ ]` to `[x]` for mig-14, cross-referencing the three closing commits (`67e81f3`, `2a71f8a`, `4e64473`) and the supporting `promote_staging.py` + `db.py` extensions.
2. `docs/REMEDIATION_PLAN.md:133` — update the mig-14 row's status from `OPEN` to `CLOSED (already satisfied)` with the same commit pointers. The `PARTIALLY CLOSED` row at `:439` (REWRITE_BUILD_MANAGERS summary) should be flipped to `CLOSED`.

These two edits can land in the next convergence update (conv-08 or equivalent) alongside any other Batch 3-B closings.

---

## §8. Verification method summary

- Read `scripts/build_managers.py` end-to-end at HEAD (`4484137`).
- Read `scripts/promote_staging.py` end-to-end at HEAD.
- Grep'd `scripts/db.py` for `CANONICAL_TABLES`, `PROMOTABLE_TABLES`, and the four build_managers output names.
- Cross-referenced against `docs/REMEDIATION_PLAN.md` (scope row, file-conflict matrix, scope-boundary risks) and `docs/REMEDIATION_CHECKLIST.md:85`.
- Confirmed the three closing commits exist in `git log --all -- scripts/build_managers.py`.
- Cross-checked conclusion against `docs/findings/sec-05-p0-findings.md` §2 + §5.

No DB queries, no code writes, no DB writes.
