# INF9 closure — 2026-04-10 Route A overrides persistence

_Session: `inf9-persist` (2026-04-23). Branch: `inf9-persist`._

## Question

Verify that the full 2026-04-10 Route A fix set is written to
`entity_overrides_persistent` in production. Persist any missing rows via the
standard staging workflow so that a future `build_entities.py --reset` does not
wipe them.

## Method

Cross-referenced:

1. `git show ada58ac` — the original 2026-04-10 DM12 promotion commit covering
   Section 1a (Securian/Sterling), Section 1b (HC Capital Trust 7 series), and
   Section 1c (Catholic Responsible Investments 5 series).
2. `git show b53e3fa` — INF9 Route A: 24 reclassify overrides written to
   staging.
3. `git log --grep "INF9"` — all subsequent INF9a–INF9e closure commits.
4. Current state of `entity_overrides_persistent` in prod (245 rows;
   confirmed equal to staging — zero diff).
5. Current state of `entity_rollup_history` for the HC Capital + CRI series
   referenced in `ada58ac`.

## Inventory of 2026-04-10 fixes vs persisted overrides

| Group | Origin commit | Live in DB | Override rows in prod | Status |
|-------|--------------|------------|----------------------|--------|
| Section 3 L4 reclassify (23 market_maker + 1 venture_capital) | `67f9ef4` | 24 SCD rows | IDs 1–24 (`claude-code-2026-04-10`) | ✓ persisted |
| Section 1a Securian DM12 series merges | `ada58ac` | 9 SFT-series DM routings → Securian | IDs 27–35 (`claude-code-2026-04-10`) | ✓ persisted (INF9b) |
| Section 1a Securian/Sterling parent_bridge deletes (relid 12171, 12172) | `ada58ac` | hard-DELETEd from `entity_relationships` | n/a (closed by INF5 Tier 1a verifier) | ✓ closed |
| Section 1b HC Capital Trust 7 DM-only sub-adviser routings | `ada58ac` | 7 SCD rows in `entity_rollup_history` (rule_applied='ncen_sub_adviser', source='N-CEN', computed_at=2026-04-10 14:31) | **none** before this session | ✗ missing → fixed here (6/7) |
| Section 1c Catholic Responsible Investments 5 DM-only sub-adviser routings | `ada58ac` | 5 SCD rows in `entity_rollup_history` (rule_applied='ncen_sub_adviser', source='N-CEN'/'manual', computed_at=2026-04-10 14:32) | **none** before this session | ✗ missing → fixed here (5/5) |
| Section 3 activist flag flips (Mantle Ridge, Triangle Securities) | Apr 10 | 2 set_activist rows | IDs 25, 26 (`claude-code-2026-04-12`) | ✓ persisted (INF9a) |
| Section 4 INF9c parent_bridge L5 audit | b543030 / 11d7cce | 6 suppress_relationship rows | within ID range (`claude-code-2026-04-12`) | ✓ persisted (INF9c) |
| 4 INF9d orphan/CRD-only entity reclassifies | Apr 10–11 | classifications live | n/a (won't-fix per INF9d) | ✓ closed |
| 28 L5 batch parent_bridge / ADV deletions | Apr 10 | overwritten by INF4c/d/INF6/INF8 batch work | n/a (closed by INF5 + INF9c fresh audit) | ✓ closed |

### Gap

**11 missing rows**, all `merge` action with `rollup_type='decision_maker_v1'`,
covering Section 1b (HC Capital Trust 6 series) + Section 1c (CRI 5 series).

| Series | Eid (source) | Target | Target CIK | New override |
|--------|--------------|--------|------------|--------------|
| S000009376 | 19018 | Parametric Portfolio Associates LLC (eid 11164) | 0000932859 | yes |
| S000009382 | 19022 | Parametric Portfolio Associates LLC | 0000932859 | yes |
| S000009383 | 19015 | Parametric Portfolio Associates LLC | 0000932859 | yes |
| S000009384 | 19019 | RhumbLine Advisers (eid 6480) | 0001115418 | yes |
| S000029853 | 19016 | Mellon Investments Corp (eid 3050) | 0000874779 | yes |
| S000029854 | 19017 | Parametric Portfolio Associates LLC | 0000932859 | yes |
| S000073781 | 20137 | Mercer Investments LLC (eid 6361) | 0001409728 | yes |
| S000073782 | 20138 | Wellington Management Co LLP (eid 9935) | 0001633863 | yes |
| S000073783 | 20139 | LOOMIS SAYLES & CO L P (eid 7650; merged from 17973 per INF4) | 0000312348 | yes |
| S000073785 | 20136 | Parametric Portfolio Associates LLC | 0000932859 | yes |
| S000073786 | 17348 | Teachers Advisors LLC (eid 9904) | 0000939222 | yes |

### Residual (1 row, non-persistable under current schema)

| Series | Eid | Intended target | Reason |
|--------|-----|-----------------|--------|
| S000029852 | 19020 | Agincourt Capital Management, LLC (eid 19021) | Agincourt has only `crd='000112096'` in `entity_identifiers` — no CIK. The `merge` action in `replay_persistent_overrides()` resolves the **target** by CIK only (line 825-829 of `scripts/build_entities.py`), so this override would skip on replay. Same shape as INF9d's "merge target identifier_type" gap, but on the target side instead of source side. Out of scope for this session (modifying scripts is excluded). Track as **INF9f** for future schema extension. |

## Replay risk for live rows

The 11 routings live as `entity_rollup_history` rows with
`rule_applied='ncen_sub_adviser'`, `source='N-CEN'`. On a
`build_entities.py --reset`, the DM1 rebuild would re-derive these from N-CEN
data — which routes them to the **fund umbrella primary adviser** (HC Capital
Solutions for the 7 HC series; Christian Brothers Investment Services for the
5 CRI series), not to the specific external sub-advisers we re-routed them to
on Apr 10. Without override rows, the manual fixes are silently lost.

## Phase 2 result

11 rows inserted into staging `entity_overrides_persistent` (override_id
246–256). True delta confirmed via override_id-keyed diff (the natural-key
diff in `diff_staging.py` is noisy for series_id-keyed rows because the
key `(entity_cik, action, field, new_value)` collapses to NULL on the
`entity_cik` side and SQL NULL≠NULL semantics report every existing
NULL-cik row as both added and deleted — known limitation, unrelated).

`validate_entities.py --staging`: 8 PASS / 1 FAIL (wellington baseline) /
7 MANUAL — no regression vs prod baseline.

## Phase 3 — replay idempotency

Full `build_entities.py --reset` against staging is **blocked by a
pre-existing infra gap** unrelated to INF9: `sync_staging.py` mirrors
prod tables via CTAS, which strips `PRIMARY KEY` / `UNIQUE` constraints
defined in `entity_schema.sql`. `build_entities.py` and
`entity_sync.insert_relationship_idempotent()` both rely on
`INSERT ... ON CONFLICT DO NOTHING` (no explicit conflict target), which
DuckDB rejects when the target table has no inferable unique constraints.
First failure on the rebuild path was `step3_populate_identifiers` →
`Binder Error: There are no UNIQUE/PRIMARY KEY constraints…`. INF9b's 9
override rows (already live in prod since 2026-04-12) were never
exercised through a full staging `--reset` either — same blocker.

To get coverage on the 11 new rows specifically, ran an isolated replay
test on a clone of staging that calls the exact SQL emitted by
`replay_persistent_overrides()` for `action='merge'`:

- 5 / 11 rows replayed end-to-end cleanly (CRI series — primary parent
  already present, so `insert_relationship_idempotent` returned False
  on the early-exit branch and never hit the constraint-dependent INSERT
  path; the SCD close + INSERT into `entity_rollup_history` then ran
  cleanly).
- 6 / 11 rows (HC Capital series) hit the same staging-only constraint
  binder error from `insert_relationship_idempotent`'s INSERT path.

This gives high confidence the 11 rows will replay cleanly **in prod**
where the schema constraints exist, matching the established INF9b
pattern. The full staging `--reset` verification gap is captured for
future infra work as INF40 (suggestion: have `sync_staging.py` rebuild
target tables via DDL from `entity_schema.sql` rather than CTAS, or
have `validate_schema_parity.py` (INF39) gate on constraint parity too).

## Phase 4 — promote (DONE)

Initial promote attempt was blocked by `scripts/app.py` (Flask, port
8001, PID 64487) holding a shared read lock on `data/13f.duckdb`. After
the app was stopped, `scripts/promote_staging.py --approved` ran cleanly:

- Snapshot id: **`20260423_080406`** (245-row baseline preserved across
  all 9 entity tables; rollback path available).
- `entity_overrides_persistent`: **deleted=0, modified=0, added=11**.
  All other entity tables: 0 changes.
- Embedded `validate_entities.py --prod` after promote:
  **8 PASS / 1 FAIL (wellington baseline) / 7 MANUAL** — no regression.
- Direct `validate_entities.py --prod` re-run: same result.

Prod state confirmed: **256 rows** in `entity_overrides_persistent`,
all 11 `claude-inf9-persist` rows present at IDs 246–256 with the
expected `(series_id, target_cik)` pairs and
`rollup_type='decision_maker_v1'`.

## Phase 5 — done

ROADMAP: INF9 moved from §Open items to §Closed items (log) with
snapshot id + summary. INF9f + INF40 added as new follow-ups.
NEXT_SESSION_CONTEXT: closure note + `entity_overrides_persistent`
count refreshed to 256.

## Out of scope

- Modifying `replay_persistent_overrides()` or any code in `scripts/`.
- Persisting INF9f (S000029852 → Agincourt) — schema gap on merge-target side.
  Track separately.
- Fixing the staging CTAS-without-constraints gap blocking `--reset`
  (INF40 candidate). Not specific to INF9.
- Any other entity edit unrelated to the 2026-04-10 Route A residual.
