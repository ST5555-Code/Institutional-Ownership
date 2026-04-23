# Pre-Phase-B Verification — 2026-04-23

Investigation-only ground-truth check of ten claims in [comprehensive-audit-2026-04-23.md](./comprehensive-audit-2026-04-23.md) before Phase B (filesystem reorg) is authorized. No file moves, no tracker edits, no pipeline runs — read-only on prod DB, one new report file.

**Base commit:** `04d314c` (audit commit).
**Prod DB:** `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb` (opened read-only).

---

## V1 — `queries.py` reader on legacy `fund_holdings`

**Claim (audit §3.c):** `scripts/queries.py` still reads from the legacy `fund_holdings` table (22,030 rows, writer-retired).

**Commands:**

```
grep -n "fund_holdings" scripts/queries.py | grep -v "fund_holdings_v2" | head -30
grep -cE "(FROM|JOIN)\s+fund_holdings[^_v]" scripts/queries.py
grep -c "fund_holdings_v2" scripts/queries.py
```

**Evidence:**

- 9 grep hits for bare "fund_holdings" — all in **docstrings or inline comments**, zero in live SQL. Representative hits: L264 (docstring), L356 (docstring), L571 (docstring), L2092 (docstring), L2355 (comment), L2691 (comment), L2940 (comment), L3034 (docstring).
- Live SQL reference count `(FROM|JOIN)\s+fund_holdings[^_v]` → **0**.
- Live SQL reference count to `fund_holdings_v2` → **42**.

**Verdict:** **DISCONFIRMED.** `queries.py` has no live readers of legacy `fund_holdings`. The 9 hits are all narrative ("N-PORT `fund_holdings`" as a concept). Actual SQL exclusively targets `fund_holdings_v2`.

**Phase-B implication:** `fund_holdings` (22,030 rows) is safe to drop after a final writer-audit sweep. No `queries.py` rewrite needed.

---

## V2 — `raw_infotable` / `raw_coverpage` / `raw_submissions` readers

**Claim (audit §3.b):** These three tables (13.6M rows combined) have zero readers and are written only by `scripts/load_13f.py`.

**Commands:**

```
grep -rn "raw_infotable\|raw_coverpage\|raw_submissions" scripts/ tests/ web/ \
  --include="*.py" --include="*.sh" --include="*.sql"
# + prod DB constraints + row counts + load_13f_v2.py check
```

**Evidence:**

| Location | Role |
|---|---|
| `scripts/load_13f.py` (15 hits: L45, L57, L62, L83, L88, L104, L134-136, L140/L151/L171, L203, L213, L234-235, L263, L327, L393) | **WRITER** — CREATE/INSERT/DROP |
| `scripts/pipeline/registry.py` (3 hits: L68, L73, L78) | **METADATA ONLY** — `DatasetSpec` declarations with stated `downstream` (not read) |
| `scripts/load_13f_v2.py` | **0 hits** — the new SourcePipeline-framework loader does not touch `raw_*` |
| All other scripts/tests/web | **0 hits** |

Prod DB row counts (read-only):
- `raw_infotable` = 13,540,608
- `raw_coverpage` = 43,358
- `raw_submissions` = 43,358
- `filings` = 43,358 (CTAS target from raw_submissions + raw_coverpage)
- `holdings_v2` = 12,270,984 (CTAS target from raw_infotable)

No FK/CHECK constraints on any of the five tables (information_schema.table_constraints → empty).

**Verdict:** **CONFIRMED.** `raw_*` trio is intermediate scratch written by `load_13f.py` and never consumed by anything outside that script. `load_13f_v2.py` (the SourcePipeline replacement) does not use them at all — it builds `holdings_v2` and `filings` from a different path.

**Phase-B implication:** `raw_*` trio + `load_13f.py` can be retired together after `load_13f_v2.py` is confirmed as the sole 13F loader (see V3). Drop order: retire `load_13f.py` → drop `raw_*` → update `registry.py` `downstream` specs.

---

## V3 — `load_13f.py` vs `load_13f_v2.py` live status

**Claim (audit §2.a, §6.c):** `load_13f.py` is "actively called" but ships alongside `load_13f_v2.py` which the Pass-2 classifier flagged as "never called."

**Commands:**

```
grep -rn "load_13f\b\|load_13f\.py\|load_13f_v2\|import load_13f" ...
```

**Evidence — `load_13f.py` live:**

- `scripts/update.py:74` — `steps = [..., "load_13f.py", ...]` — scheduled as pipeline step #4.
- `Makefile:111` — `$(PY) $(SCRIPTS)/load_13f.py $(if $(QUARTER),--quarter $(QUARTER),)` — pipeline step 1b.
- `scripts/benchmark.py:20` — listed in benchmark matrix.
- `scripts/pipeline/registry.py` L69/L74/L79/L113/L118/L175 — declared owner on 6 datasets.
- `scripts/build_managers.py:228` — referenced as upstream producer of `filings_deduped`.

**Evidence — `load_13f_v2.py` live:**

- `scripts/pipeline/pipelines.py:23` — `importlib.import_module("load_13f_v2").Load13FPipeline` (p2-07 pipeline registry consumed by `scripts/admin_bp.py` for refresh / approve / reject / rollback).
- `tests/pipeline/test_load_13f_v2.py` — unit suite (imports `Load13FPipeline`).
- `tests/test_admin_refresh_endpoints.py:213,303` — patches `load_13f_v2.Load13FPipeline.run` / `.reject`.

**Verdict:** **BOTH LIVE** (different surfaces). `load_13f.py` is the CLI / Makefile pipeline step; `load_13f_v2.py` is the admin-refresh `SourcePipeline` subclass. `REMEDIATION_PLAN.md:131` already notes this — "Legacy `scripts/load_13f.py` now flagged SUPERSEDED; retire after one clean quarterly cycle." Neither is dead code.

**Phase-B implication:** Do **not** move `load_13f.py` to `scripts/retired/` in Phase B. The one-clean-quarter retirement gate is an open condition (see REMEDIATION_PLAN.md mig-12 CLOSED note). Phase B should instead: (a) verify the quarterly-cycle gate is satisfied, (b) if yes, cut `load_13f.py` over to a tombstone after removing it from `update.py` + `Makefile` + `registry.py` owner fields.

---

## V4 — `REMEDIATION_CHECKLIST.md` three stale checkboxes

**Claim (audit §4.a, §7.d):** Three drifts — `L39 int-18/INF37`, `L98 mig-05`, `L101 mig-12` — all still `[ ]` but closed/superseded elsewhere.

**Commands:**

```
sed -n '39p;98p;101p' docs/REMEDIATION_CHECKLIST.md
grep -n "int-18\|INF37" ROADMAP.md docs/REMEDIATION_PLAN.md
grep -n "mig-05\|mig-12" docs/REMEDIATION_PLAN.md
```

**Evidence:**

| Line | Current text | Authoritative state elsewhere | Drift |
|---|---|---|---|
| L39 | `- [ ] int-18 INF37 backfill_manager_types residual 9 entities (no closure expected)` | `ROADMAP.md:580` — **CLEARED 2026-04-23 (`entity-curation-w1`)**, 14,368 → 0 NULL/unknown rows | **YES** |
| L98 | `- [ ] mig-05 BLOCK-4 admin refresh pre-restart rework (BLOCKED — upstream design doc missing)` | `REMEDIATION_PLAN.md:445` — **SUPERSEDED** by full Phase 2 scope (`prog-01`, 2026-04-20); design doc recovered at commit `03db9ad` | **YES** |
| L101 | `- [ ] mig-12 load_13f_v2 rewrite (fetch_13f.py + promote_13f.py + build_managers reader)` | `REMEDIATION_PLAN.md:131` — **CLOSED 2026-04-22 (conv-12)**; absorbed by p2-05 | **YES** |

Note on L39 framing: the checkbox label says "(no closure expected)" — the STANDING framing applied before the 2026-04-23 `entity-curation-w1` close. ROADMAP.md explicitly flipped INF37 to `CLEARED` after residual was driven to zero, so the STANDING exception no longer holds and the checkbox should now flip.

**Verdict:** **CONFIRMED (3 of 3).** All three drifts are genuine; the tracker states they should inherit are consistent with other authoritative docs.

**Phase-B implication:** Apply three checkbox flips in `REMEDIATION_CHECKLIST.md` as part of Phase B's tracker-hygiene sweep. No decoupling from filesystem reorg — mechanical edit.

---

## V5 — `fetch_finra_short.py` --dry-run gap

**Claim (audit §6.d):** `fetch_finra_short.py` has no `--dry-run` / `--apply` flag; `--test` still writes.

**Commands:**

```
grep -nE "argparse|add_argument|--dry-run|--apply|--test|dry_run|dry-run" scripts/fetch_finra_short.py
grep -nE "INSERT|UPDATE|DELETE|REPLACE|executemany" scripts/fetch_finra_short.py
```

**Evidence:**

- argparse flags defined at L260-263: `--days` (int, default 30), `--update`, `--test`, `--staging`.
- No `--dry-run`, `--apply`, `dry_run`, or equivalent guard.
- L154-160: `INSERT OR IGNORE INTO short_interest (...)` → unconditional write on every invocation.
- `--test` only narrows `days=30 → days=5` (L176-177); it still passes through to `run()` which still inserts.

**Verdict:** **CONFIRMED.** The script has no dry-run mode. Every invocation writes to `short_interest`. `--test` is a data-subset knob, not a safety flag.

**Phase-B implication:** Out of scope for filesystem reorg; tracked separately as an ops-hygiene follow-on. Phase B should not attempt this fix. Recommend opening a dedicated `fetch-finra-short-dry-run` ticket.

---

## V6 — `canonical_ddl.md` v2 column-count claims

**Claim (audit §6.a):** `canonical_ddl.md` claims `holdings_v2=33`, `fund_holdings_v2=26`, `beneficial_ownership_v2=22` columns; DB reports `30, 30, 28`.

**Commands:**

```
# DB:
SELECT table_name, COUNT(*) FROM information_schema.columns WHERE table_name IN (...)
# Doc:
grep -nE "([0-9]+) col" docs/canonical_ddl.md
```

**Evidence — doc claims:**

| File:Line | Claim |
|---|---|
| `docs/canonical_ddl.md:23` | "holdings_v2 ... already has all **33 cols**" |
| `docs/canonical_ddl.md:68` | "Prod DDL (**34 columns**):" — header of the holdings_v2 DDL block (note: inconsistent with the L23 "33") |
| `docs/canonical_ddl.md:121` | "Prod DDL (**26 columns**):" — fund_holdings_v2 block |
| `docs/canonical_ddl.md:153` | "all **26 columns** listed above" — fund_holdings_v2 summary |
| `docs/canonical_ddl.md:169` | "Prod DDL (**22 columns**):" — beneficial_ownership_v2 block |

**Evidence — actual DB:**

| Table | Actual column count |
|---|---|
| `holdings_v2` | **38** |
| `fund_holdings_v2` | **30** |
| `beneficial_ownership_v2` | **28** |

Gaps (prod ∖ canonical_ddl doc):

- `holdings_v2` drift = +5 from the "33" claim (+4 from the "34" claim). Missing columns in doc likely include: `entity_type`, `dm_rollup_entity_id`, `dm_rollup_name`, `pct_of_so_source`, `is_latest`, `backfill_quality` (full cross-check deferred — doc DDL block not fully read in this session).
- `fund_holdings_v2` drift = +4. Missing likely: `dm_entity_id`, `dm_rollup_entity_id`, `dm_rollup_name`, `is_latest`, `backfill_quality` (doc block claimed 7 missing at L149 — reconcile).
- `beneficial_ownership_v2` drift = +6. Doc block at L195 already notes only 2 missing; delta is larger than doc self-admits.

**Verdict:** **PARTIAL.** The direction of the claim is correct (doc is stale) and the canonical_ddl numbers (33/26/22) are right as quoted. **The audit's own DB numbers are wrong** — it reported 30/30/28, actual is **38/30/28**. The `holdings_v2` gap is bigger than the audit flagged (5 missing cols, not 3).

**Phase-B implication:** `canonical_ddl.md` needs a full column-by-column regen against prod — not a one-line patch. Scope-up risk for Phase C (doc consolidation). Also: the audit self-reporting error on `holdings_v2=30` means Phase B planners should re-derive the numbers themselves before trusting any audit table.

---

## V7 — Pass 2 false-positive count

**Claim (audit §7.b):** 48 of the 77 Pass-2 "retire candidates" are false positives. Real count is 10-25.

**Method:** Re-classified each of the 77 candidates with a tighter rule-set:

- A (migration): `scripts/migrations/*.py` — applied-once, NOT retire.
- B (oneoff): `scripts/oneoff/*.py` — historical, NOT retire.
- C (CLI/CI/Makefile/admin allowlist) — referenced in build or ops surface, NOT retire.
- D (dotted-path import via pipeline framework) — imported dynamically, NOT retire.
- E (active session usage — e.g., `audit_ticket_numbers.py` ran on 2026-04-23) — NOT retire.

Full classifier output (77 rows) computed via per-script `grep -rln <stem> scripts/ tests/ web/ docs/ .github/ Makefile README.md` + category match.

**Result:**

| Bucket | Count |
|---|---|
| Category A (migrations 002-017 + add_last_refreshed_at) | 16 |
| Category B (oneoff/) | 9 |
| Category C/D/E (strong ref or 3+ refs in other trees) | 42 |
| **Subtotal false positive** | **67** |
| **Genuine retire candidates (≤2 refs, not in known kept categories)** | **10** |

The 10 genuine candidates:

| Path | Why still on list | Notes |
|---|---|---|
| `scripts/audit_ticket_numbers.py` | Ran this session; referenced in PR #131 commit message only | KEEP — produced audit output; move to scripts/hygiene/ in Phase B |
| `scripts/backfill_pending_context.py` | 2 refs | Historic one-off, move to scripts/oneoff/ |
| `scripts/bootstrap_tier_c_wave2.py` | 2 refs | Historic bootstrap, move to scripts/oneoff/ |
| `scripts/cleanup_merged_worktree.sh` | 2 refs (PR #128) | KEEP — worktree hygiene; move to scripts/hygiene/ |
| `scripts/dm14_layer1_apply.py` | 2 refs | Historic DM one-off, move to scripts/oneoff/ |
| `scripts/dm14b_apply.py` | 2 refs | Historic DM one-off, move to scripts/oneoff/ |
| `scripts/dm15_layer1_apply.py` | 2 refs | Historic DM one-off, move to scripts/oneoff/ |
| `scripts/inf23_apply.py` | 2 refs | Historic one-off, move to scripts/oneoff/ |
| `scripts/smoke_yahoo_client.py` | 1 ref | Genuine retire candidate |
| `scripts/snapshot_manager_type_legacy.py` | 1 ref | Genuine retire candidate |

Note: most "retire candidates" above are really **relocate-not-retire** — they belong in `scripts/oneoff/` or a new `scripts/hygiene/` directory.

**Verdict:** **CONFIRMED (direction and range).** Real retire count = ~10 (true retire) + ~7 (relocate to oneoff/hygiene), vs the 77 raw flag list. The audit's "real count 10-25" range is correct; the specific "48 FP" figure is low — my tighter sweep puts FPs at **67**.

**Phase-B implication:** Phase B should not bulk-move 77 files. Instead: (a) relocate ~7 historic one-offs into `scripts/oneoff/`, (b) retire the 2-3 genuine orphans (`smoke_yahoo_client.py`, `snapshot_manager_type_legacy.py`), (c) create `scripts/hygiene/` for `audit_*` + `cleanup_merged_worktree.sh`.

---

## V8 — 292 snapshot tables

**Claim (audit §3, §8.Q7):** 292 point-in-time audit snapshots of **12** base tables exist.

**Commands:**

```
SELECT REGEXP_EXTRACT(table_name, '^(.+)_snapshot_\d{8}_\d{6}$', 1) AS base, COUNT(*) ...
```

**Evidence:**

- Total snapshot tables: **292** ✓ matches audit.
- Distinct base tables: **15** (not 12).
- Sum of estimated rows: ~30.47M.
- Database size (whole DB, not just snapshots): 15.1 GiB on disk.

| Base table | Snap count | Oldest | Newest |
|---|---|---|---|
| `entities` | 33 | 20260411_180047 | 20260423_084622 |
| `entity_aliases` | 33 | 20260411_180047 | 20260423_084622 |
| `entity_classification_history` | 33 | 20260411_180047 | 20260423_084622 |
| `entity_identifiers` | 33 | 20260411_180047 | 20260423_084622 |
| `entity_rollup_history` | 33 | 20260411_180047 | 20260423_084622 |
| `entity_identifiers_staging` | 32 | 20260411_180047 | 20260423_084622 |
| `entity_relationships` | 32 | 20260411_180047 | 20260423_084622 |
| `entity_relationships_staging` | 32 | 20260411_180047 | 20260423_084622 |
| `entity_overrides_persistent` | 23 | 20260412_092411 | 20260423_084622 |
| `cik_crd_direct` | 1 | 20260419_091455 | 20260419_091455 |
| `cik_crd_links` | 1 | 20260419_091455 | 20260419_091455 |
| `cusip_classifications` | 1 | 20260418_172203 | 20260418_172203 |
| `managers` | 1 | 20260419_091455 | 20260419_091455 |
| `parent_bridge` | 1 | 20260419_091455 | 20260419_091455 |
| `securities` | 1 | 20260418_172203 | 20260418_172203 |

**Verdict:** **PARTIAL.** Total count `292` is correct. Base-table count is **15, not 12** — audit undercounted by 3. The 6 single-shot snapshots (`cik_crd_*`, `cusip_classifications`, `managers`, `parent_bridge`, `securities`) look like ad-hoc safety nets around specific migrations (CUSIP v1.4 promotion on 04-18; merge-wave on 04-19), not routine SCD cadence.

**Phase-B implication:** Snapshot retention policy question is still live, but now spans 15 tables not 12. Phase B should stay out of snapshot pruning — it's a DB ops task, not a filesystem-reorg task. Recommend: fold "snapshot retention policy" into a separate `ops-snapshot-retention` ticket.

---

## V9 — Four undocumented pipeline modules

**Claim (audit §6.c):** `scripts/pipeline/protocol.py`, `discover.py`, `id_allocator.py`, `cusip_classifier.py` all present but not in `docs/pipeline_inventory.md`.

**Commands:**

```
ls scripts/pipeline/ | grep -E "protocol|discover|id_allocator|cusip_classifier"
grep -cE "protocol\.py|discover\.py|id_allocator\.py|cusip_classifier\.py" docs/pipeline_inventory.md
```

**Evidence:**

- All four files present in `scripts/pipeline/`.
- `docs/pipeline_inventory.md` match count = **0** for the four filenames.

**Verdict:** **CONFIRMED.** All four modules are undocumented in `pipeline_inventory.md`.

**Phase-B implication:** `pipeline_inventory.md` needs a four-row append. Not a file-move task — Phase C doc update. No blocking impact on Phase B filesystem reorg.

---

## V10 — DM3 / DM6 duplicate titles in `dm-open-surface-2026-04-22.md`

**Claim (audit §4.b, §5.b, §7.d, §8.Q5):** L152-153 of the DM findings doc has duplicate (different-title) headings for DM3 and DM6 — violates PR #131 retire-forever hygiene rule.

**Commands:**

```
sed -n '145,165p' docs/findings/dm-open-surface-2026-04-22.md
grep -nE "DM3|DM6" docs/findings/dm-open-surface-2026-04-22.md
```

**Evidence — every DM3 / DM6 occurrence in the file:**

| Line | Context | DM3 meaning | DM6 meaning |
|---|---|---|---|
| L26 | `\| DM3 — N-PORT metadata \| Deferred \| ...` | N-PORT metadata | — |
| L28 | `\| DM6 — N-1A prospectus parser \| Low / deferred \| ...` | — | N-1A prospectus parser |
| L117-123 | Umbrella-trust table — references: "Needs DM6 (N-1A) or DM3 (N-PORT metadata)" | N-PORT metadata | N-1A parser |
| L125 | Implication paragraph | N-PORT metadata extension | N-1A prospectus parser |
| L152 | `\| **DM15e — Prospectus-blocked umbrella trusts** ... DM6 (N-1A parser) or DM3 (N-PORT metadata) \| ...` | N-PORT metadata (inline ref) | N-1A parser (inline ref) |
| L153 | `\| **DM2 / DM3 / DM6** \| ADV Schedule 7.B reparse / N-PORT metadata / N-1A parser \| ...` | N-PORT metadata | N-1A parser |
| L175 | Summary line | referenced | referenced |

Every reference is internally consistent: **DM3 → N-PORT metadata, DM6 → N-1A prospectus parser**.

L152 and L153 are **table rows whose bold lead-cell labels are `DM15e` and `DM2 / DM3 / DM6`** respectively — not standalone DM3 or DM6 headings. The auto-classifier in `audit_ticket_numbers.py` appears to have tokenized the first-column text ("DM2 / DM3 / DM6") as implying a DM3 title of "ADV Schedule 7.B reparse / N-PORT metadata / N-1A parser" — a classifier artifact, since that cell is the combined scope for a grouped row.

**Verdict:** **DISCONFIRMED.** There are **no** duplicate DM3 or DM6 titles in this file. All references use the consistent L26/L28 definitions. The "2 distinct titles each" flag is a false positive from the audit tool's handling of grouped table rows.

**Phase-B implication:** Do **not** open a `dm-taxonomy-hygiene` ticket to retire duplicate DM3/DM6 labels — there are no duplicates. Instead, open a dedicated `audit_ticket_numbers.py` refinement ticket so grouped table rows (e.g. `DM2 / DM3 / DM6`) are not treated as title-defining occurrences. The **INF40 reuse** half of audit §8.Q5 is untouched by this result — that finding stands.

---

## Summary matrix

| # | Claim | Verdict | One-line Phase-B implication |
|---|---|---|---|
| V1 | `queries.py` reads legacy `fund_holdings` | **DISCONFIRMED** | Legacy `fund_holdings` table is drop-safe from a `queries.py` perspective. |
| V2 | `raw_*` trio has zero readers, only `load_13f.py` writer | **CONFIRMED** | Retire `raw_*` + `load_13f.py` together, after V3's quarterly gate passes. |
| V3 | `load_13f.py` active, `load_13f_v2.py` "never called" | **BOTH LIVE** (different surfaces) | Do not move `load_13f.py` to `retired/` yet — gate on one-clean-quarter cycle first. |
| V4 | Three checkbox drifts at L39/L98/L101 | **CONFIRMED (3/3)** | Apply three mechanical checkbox flips as part of the Phase B hygiene sweep. |
| V5 | `fetch_finra_short.py` has no `--dry-run`, `--test` still writes | **CONFIRMED** | Out of scope for Phase B; spin off as `fetch-finra-short-dry-run` ticket. |
| V6 | `canonical_ddl.md` v2 column counts stale (33/26/22 vs DB 30/30/28) | **PARTIAL** — doc stale confirmed, but actual DB is 38/30/28 (audit's own numbers wrong for holdings_v2) | `canonical_ddl.md` needs full column-by-column regen; `holdings_v2` gap is +5 not +3. |
| V7 | 48 of 77 Pass-2 candidates are FP; real = 10-25 | **CONFIRMED (direction/range)** — tighter sweep puts FPs at 67, real = ~10 | Don't bulk-retire 77; relocate ~7 oneoffs, retire 2-3 genuine orphans, introduce `scripts/hygiene/`. |
| V8 | 292 snapshots of 12 base tables | **PARTIAL** — 292 correct, 15 base tables (not 12) | Snapshot retention is a separate ops ticket spanning 15 tables, not part of Phase B. |
| V9 | 4 pipeline modules undocumented | **CONFIRMED** | Phase C `pipeline_inventory.md` append, no filesystem impact. |
| V10 | DM3/DM6 duplicate titles at L152-153 | **DISCONFIRMED** | No duplicate titles exist; refine `audit_ticket_numbers.py` grouped-row handling instead. |

**Tally:** 4 CONFIRMED · 2 DISCONFIRMED · 3 PARTIAL · 1 reclassified (V3 "both live").

**Most impactful surprise:** **V6.** The audit's own reported DB column counts are wrong — `holdings_v2` has 38 columns in prod, not 30 as the audit stated. The gap between canonical_ddl doc and prod is therefore wider than the audit flagged (+5 on `holdings_v2` instead of +3, +4 on `fund_holdings_v2` instead of +0), which scopes up the Phase C doc-regen task. Implication for Phase B planning: re-derive any number used to gate decisions — don't trust audit counts without verification.
