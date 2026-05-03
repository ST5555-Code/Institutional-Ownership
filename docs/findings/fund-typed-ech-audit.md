# fund-typed-ech-audit — writer + reader scoping

**HEAD at audit:** `394f962` (unknown-classification-wave-1: Tier A auto-resolutions, #261).
**Read-only investigation.** No DB writes. Drives the disable-writers + reader-migrate + close-rows PR sequence per chat decision 2026-05-03 (`docs/decisions/d4-classification-precedence.md`).

---

## 1. Cohort snapshot

Open ECH rows where `entities.entity_type = 'fund'` AND `valid_to = DATE '9999-12-31'`.

### 1.1 By classification

| classification | rows  |
|---             |---    |
| passive        | 5,681 |
| active         | 5,663 |
| unknown        | 1,876 |
| **TOTAL**      | **13,220** |

Matches expected cohort from prior session within tolerance.

### 1.2 By source

| source                    | rows  | first_seen | last_seen  |
|---                        |---    |---         |---         |
| `fund_universe`           | 6,671 | 2000-01-01 | 2000-01-01 |
| `stg_nport_fund_universe` | 4,673 | 2000-01-01 | 2000-01-01 |
| `default_unknown`         | 1,876 | 2000-01-01 | 2000-01-01 |

All open fund-typed rows carry `valid_from = DATE '2000-01-01'` — they are bulk-seeded during `build_entities --reset`. Three sources, no others.

### 1.3 Source × classification

| source                    | passive | active | unknown |
|---                        |---     |---     |---     |
| `fund_universe`           | 1,035  | 5,636  | —      |
| `stg_nport_fund_universe` | 4,646  | 27     | —      |
| `default_unknown`         | —      | —      | 1,876  |

Two-way pattern is clean: `fund_universe` is the active-leaning source (build-time canonical), `stg_nport_fund_universe` is the passive-leaning source (N-PORT registrant-reported), `default_unknown` is the orphan-fund fallback.

---

## 2. Writer inventory

Full per-writer detail in [`data/working/fund-typed-ech-writers.csv`](../../data/working/fund-typed-ech-writers.csv). Eighteen distinct write sites surveyed across `scripts/`. Of these, **only three currently produce open fund-typed rows**:

### 2.1 Active producers (need disable PRs)

| writer | rows produced | source | class |
|---|---|---|---|
| [build_entities.py:584-602 step6 → fund_rows loop](../../scripts/build_entities.py:584) | 6,671 | `fund_universe` | active_pipeline |
| [build_entities.py:638-641 step6 → 'remaining' loop](../../scripts/build_entities.py:638) | 1,876 | `default_unknown` | active_pipeline |
| [resolve_pending_series.py:694-701 wire_fund_entity](../../scripts/resolve_pending_series.py:694) | 4,673 | `stg_nport_fund_universe` | active_pipeline |

`build_entities.py` step 6 fires on every `--reset` rebuild. `resolve_pending_series.py` fires whenever N-PORT pending-series resolution lands a new fund.

### 2.2 Theoretical producers (can target funds, currently 0 open rows)

| writer | source | class | gate strategy |
|---|---|---|---|
| [build_entities.py:799-811 replay_persistent_overrides](../../scripts/build_entities.py:799) | `manual_override` | replay | one_line_gate (skip when entity_type='fund') |
| [admin_bp.py:1041-1080 CSV reclassify import](../../scripts/admin_bp.py:1041) | `manual` | active_pipeline | one_line_gate (reject fund eids in CSV) |
| [entity_sync.py:679-689 update_classification_from_sic](../../scripts/entity_sync.py:679) | `SEC_SIC` | active_pipeline | one_line_gate (entry guard on entity_type) |

These three could in principle stamp a fund-typed ECH row through their existing flows. They currently have zero open fund-typed rows — but to make the close-rows PR safe and durable, each needs a gate so a future `--reset` or operator action does not reintroduce.

### 2.3 Institution-only writers (no action needed)

Twelve writers create or update only `entity_type='institution'` rows by construction. They are listed in the writers CSV with `disable_strategy='none_needed'` and brief justification per file. Highlights: all `bootstrap_*_advisers.py`, `resolve_13dg_filers.py`, every fund-naming oneoff (`apply_series_triage.py` despite the name creates institutions, `dera_synthetic_stabilize.py`, `calamos_merge_tier4_classify_apply.py`, `dm15c_amundi_sa_apply.py`, `bootstrap_tier_c_wave2.py`, `unknown_classification_wave1_apply.py`), and the close-only `inst_eid_bridge_aliases_merge.py`.

---

## 3. Reader inventory

Full per-reader detail in [`data/working/fund-typed-ech-readers.csv`](../../data/working/fund-typed-ech-readers.csv). Seventeen reader sites surveyed across live code paths (excluding migrations and oneoff archaeology).

### 3.1 Blast radius summary

| blast_radius | reader count | example sites |
|---|---|---|
| none   | 11 | `queries_helpers.classification_join`, `get_entity_filer_children`, `get_entity_fund_children`, `build_fixture` view rebuild, `diff_staging` |
| low    |  5 | `search_entity_parents`, `admin_bp` is_activist branch, `pipeline.shared` requires_classification gate, `entity_sync` SCD self-read, `resolve_long_tail` worker queue |
| medium |  1 | `get_entity_by_id` via `entity_current` |
| high   |  0 | — |

### 3.2 The one medium-blast reader

[`scripts/queries/entities.py:34-38 get_entity_by_id`](../../scripts/queries/entities.py:34) reads `ec.classification` for any `entity_id`, including funds. Powers the node-detail panel in the web app. After the close-rows PR, fund eids will return `classification = NULL` from `entity_current`. The UI will show an empty cell rather than `'active'` / `'passive'`.

**Migration target:** when `ec.entity_type = 'fund'`, resolve classification through `entity_identifiers.identifier_value (series_id)` → `fund_universe.fund_strategy`. This is the canonical fund classification source per chat decision 2026-05-03 (precedence document).

### 3.3 Why the rest are 'none' or 'low'

The dominant pattern is that `holdings_v2.entity_id` references the **manager institution** that filed the 13F — not a fund. Every Tier 4 query that joins `entity_current` or `entity_classification_history` from `holdings_v2` keys on the manager. Funds appear in `fund_holdings_v2` (N-PORT) but the live readers there pull NAV from `fund_universe`, not classification from ECH. So the most heavily-trafficked reader path — the holdings analytics surface — is not a fund-typed ECH consumer.

The remaining `entity_current` consumers in `queries/entities.py` mostly read `display_name`, not classification. Where they do read classification (`search_entity_parents`, `get_entity_sub_advisers`), an entity_type or relationship-type filter implicitly excludes funds.

---

## 4. Writer-reader cross-check

The audit looks for load-bearing dependencies — writers whose output is consumed by a reader that does not filter by entity_type, where naive close-then-disable would break behavior.

| writer | downstream readers that consume fund-typed rows | failure mode if closed first |
|---|---|---|
| `build_entities.py` step6 (`fund_universe` source) | `get_entity_by_id` via entity_current | UI shows NULL classification on fund nodes — cosmetic |
| `build_entities.py` step6 ('remaining' / `default_unknown`) | `get_entity_by_id` via entity_current | same as above |
| `resolve_pending_series.py:694` (`stg_nport_fund_universe`) | `get_entity_by_id` via entity_current | same as above |

No reader fails hard on missing fund-typed ECH rows. Every consumer either:
- uses `LEFT JOIN` (entity_current view itself, classification_join helper, fixture rebuild)
- filters out funds by entity_type or identifier (cik / series_id presence)
- consumes only `display_name`, not classification

The `pipeline.shared` gate is the only theoretical hard-fail, and all live callers pass `requires_classification=False`. The retired `validate_nport.py` is the only `True` caller.

**Conclusion:** there is no load-bearing dependency that forces writer-disable to land before close-rows. The two phases can be sequenced safely either way, but writers-first is preferred so the close PR is the last write touching fund-typed rows and remains durable.

---

## 5. entity_current view assessment

Captured DDL (formatted for readability):

```sql
CREATE VIEW entity_current AS
SELECT e.entity_id, e.entity_type, e.created_at,
       COALESCE(ea.alias_name, e.canonical_name) AS display_name,
       ech.classification, ech.is_activist,
       ech.confidence AS classification_confidence,
       er.rollup_entity_id, er.rollup_type
FROM entities AS e
LEFT JOIN (
    SELECT entity_id, alias_name FROM entity_aliases
    WHERE is_preferred = TRUE AND valid_to = DATE '9999-12-31'
) AS ea ON e.entity_id = ea.entity_id
LEFT JOIN entity_classification_history AS ech
    ON e.entity_id = ech.entity_id
   AND ech.valid_to = DATE '9999-12-31'
LEFT JOIN entity_rollup_history AS er
    ON e.entity_id = er.entity_id
   AND er.rollup_type = 'economic_control_v1'
   AND er.valid_to = DATE '9999-12-31';
```

Key properties:

- `LEFT JOIN` on ECH means a missing open row produces `classification = NULL` rather than excluding the entity. Funds remain visible after close.
- The view does not filter by `entity_type` — it serves funds and institutions identically.
- Closing all fund-typed open ECH rows ⇒ every fund row in `entity_current` shows `classification = NULL`. Readers must tolerate that.
- All six readers of `entity_current` in `queries/entities.py` use this view — the radius assessment in §3 is grounded in the LEFT JOIN behavior.

No view rewrite is required for the close PR. A future enhancement could enrich the view to coalesce `fund_universe.fund_strategy` for fund rows, but that belongs in the reader-migrate PR for `get_entity_by_id`, not in entity_current itself.

---

## 6. Risk register

Dependencies that could surprise the close-rows PR if the audit missed them:

1. **Operator CSV import targeting a fund eid** — `admin_bp.py` write path is gated only by `entity_id IN entities`, no entity_type guard. Risk if an analyst uploads a CSV row with a fund_id without realizing it. **Mitigation:** PR-W2 adds entity_type=fund rejection at the import handler.

2. **Persistent override replay** — `entity_overrides_persistent` with `still_valid=TRUE` rows could replay to a fund eid on the next `build_entities --reset`. Current cohort shows zero `manual_override` source rows for fund-typed, so no override targets a fund today, but a future operator could write one. **Mitigation:** PR-W2 adds entity_type guard in `replay_persistent_overrides`.

3. **`pipeline.shared` requires_classification flip** — if a future load script flips this flag to `True` after PR-C lands, every fund-typed staged row would block at the gate. **Mitigation:** add a comment in `pipeline.shared.py:317` noting the fund-typed close decision and that requires_classification=True is institution-only.

4. **resolve_long_tail.py picking up fund-typed CIKs** — `get_unresolved_ciks` does not filter by entity_type. After PR-C, fund eids drop from the queue (no ECH row → INNER JOIN fails). This is the intended behavior, but worth flagging in the PR description so the next operator running long-tail does not panic at the row count drop.

5. **`pending_entity_resolution` queue** — not directly an ECH reader, but `resolve_pending_series.py` writes ECH for new fund eids it lands. After PR-W1 disables that branch, pending series will still land an entity row but with no ECH attached. UI must surface fund classification via the migrated reader path (PR-R1), not via entity_current alone.

6. **Diff-staging noise on the close cycle** — `diff_staging.py` will report 13,220 deleted ECH rows on the first staging cycle after PR-C. Operationally informational — the runbook for that cycle should call this out so it does not get treated as an unintended deletion.

---

## 7. Recommended PR sequence

The audit supports this seven-PR sequence to reach the end state — zero open fund-typed ECH rows, no writer producing new ones, all readers tolerate or sidestep the missing rows.

```
PR-W1 disable-fund-writes-build-entities      [active producers]
PR-W2 disable-fund-writes-replay-and-admin    [theoretical producers]
PR-W3 disable-fund-writes-resolve-pending     [active producer]
PR-W4 disable-fund-writes-sic-and-long-tail   [theoretical producer]
PR-R1 migrate-get-entity-by-id-fund-strategy  [medium-blast reader]
(decision point — chat reviews PR-R1 + remaining audit hooks)
PR-C  close-fund-typed-ech-rows               [close all 13220 open rows]
```

### 7.1 Per-PR sizing and scope

**PR-W1 — disable-fund-writes-build-entities** (small, ~30 lines)
- `scripts/build_entities.py`: gate `_insert_cls` to skip when target entity_type='fund' (1 SELECT lookup + branch). Update step 6 fund_rows loop to no-op for funds. Update 'remaining' loop query to filter `e.entity_type <> 'fund'`. Refresh tests.
- After this PR a clean `--reset` will not produce `fund_universe` or `default_unknown` fund-typed rows. Existing rows still in place — they get closed in PR-C.

**PR-W2 — disable-fund-writes-replay-and-admin** (small, ~25 lines)
- `scripts/build_entities.py:replay_persistent_overrides`: add entity_type=fund guard at the `reclassify` action branch.
- `scripts/admin_bp.py:1041 reclassify handler`: reject CSV rows where entity_id resolves to entity_type='fund'.

**PR-W3 — disable-fund-writes-resolve-pending** (small, ~15 lines)
- `scripts/resolve_pending_series.py:wire_fund_entity`: skip the ECH INSERT block (lines 681-701). Keep the entity + identifier + alias + relationship + rollup writes. Add a comment pointing at the fund_strategy reader.

**PR-W4 — disable-fund-writes-sic-and-long-tail** (small, ~10 lines)
- `scripts/entity_sync.py:update_classification_from_sic`: add entity_type=fund early-return guard.
- Document in `scripts/resolve_long_tail.py` that fund-typed eids drop from the worker queue after PR-C; no code change required there but add a docstring note.

**PR-R1 — migrate-get-entity-by-id-fund-strategy** (medium, ~50 lines + tests)
- `scripts/queries/entities.py:get_entity_by_id`: when `entity_type='fund'`, resolve classification by joining `entity_identifiers` (identifier_type='series_id') → `fund_universe.fund_strategy`, then map fund_strategy → 'active'/'passive'/'unknown' via the `ACTIVE_FUND_STRATEGIES` constant in `queries/common.py` (the same mapping `build_entities.step2_create_fund_entities` uses today).
- Add a unit test confirming the migrated path returns the same value for a representative fund as the pre-close ECH row.
- Optional: also migrate `search_entity_parents` so the type-ahead dropdown displays fund classification correctly when a fund eid surfaces as self-rollup. Could split into PR-R1a/R1b if scope grows.

**Decision point — chat review.** After PR-R1 lands, chat reviews the audit output, confirms the close cohort, and authorizes PR-C.

**PR-C — close-fund-typed-ech-rows** (small, single transaction)
- One-shot SCD close for all 13,220 open fund-typed rows in a single transaction. `UPDATE entity_classification_history SET valid_to = CURRENT_DATE WHERE entity_id IN (SELECT entity_id FROM entities WHERE entity_type='fund') AND valid_to = DATE '9999-12-31'`.
- Pre-flight: re-run cohort audit to confirm 13,220 (±tolerance). Refuse if PR-W1/W2/W3/W4 are not all merged.
- Post-flight: assert open fund-typed count = 0; assert entity_current view returns NULL classification for representative fund eids; assert get_entity_by_id returns the migrated classification.

### 7.2 Dependency graph

```
PR-W1 ─┐
PR-W2 ─┼─→ PR-R1 ─→ PR-C
PR-W3 ─┤
PR-W4 ─┘
```

PR-W1..W4 can be authored in parallel (no shared lines). PR-R1 must follow because PR-C will leave fund classifications missing in the UI until the migrated reader path is in place. PR-C runs last.

---

## 8. Open questions for chat decision

1. **Scope of PR-R1.** Migrate just `get_entity_by_id`, or also `search_entity_parents`? The latter affects the type-ahead dropdown for self-rollup fund eids — a small cohort but visible.
2. **PR-R1 location of the fund_strategy → classification mapping.** Inline in `get_entity_by_id`, or factor into a `classify_fund_strategy(strategy: str) -> str` helper in `queries/common.py`? Current tactical answer: helper, because step 2.6 of `build_entities.py` already encodes the same mapping inline (lines 245-250) and a shared helper retires that duplication.
3. **Should PR-C also drop the `default_unknown` fund-typed cohort from `entity_overrides_persistent` — if any persistent overrides target fund eids?** Audit shows zero today, but a sweep on the override table is cheap insurance.
4. **Should PR-W4 (`resolve_long_tail`) actually filter the queue at SQL level rather than rely on the post-close INNER JOIN drop-out?** Adds three lines, reduces operator surprise on the next long-tail run.
5. **Diff-staging runbook update.** Should the next staging cycle's diff report be annotated in advance to flag the expected 13,220 'deleted' rows — or is a one-line PR description enough?

---

*Audit produced 2026-05-03 by fund-typed-ech-audit branch off `394f962`.*
