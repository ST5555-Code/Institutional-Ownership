# query4 silent-drop fix — results (Phase 5)

**Date:** 2026-05-02
**Branch:** `query4-fix-option-a`
**Scope:** CP-3 of Wave 1 critical-path. `scripts/queries/register.py:746–750` only.
**Out of scope:** parent-level-display-canonical-reads sweep (CP-5), independent of CP-1.

## Context

`/api/v1/query4` (passive vs active ownership split) used a CASE expression that
mixed `entity_type` and `manager_type` inconsistently. Rows where `entity_type`
carried a classification signal (`active`, `hedge_fund`, `quantitative`,
`passive`-via-`manager_type`, etc.) but `manager_type` did not, fell through to
`Other/Unknown` — silently invisible in the chart.

PR #252 Phase 4 quantified the bug at LQ:
- Other/Unknown: **1,543,537 rows / $23,032.4B** (48.15% rows / 34.21% AUM)
- Disagreement subset: **324,194 rows / $5,496.1B** (10.11% / 8.16%)

No React tab consumes `/api/v1/query4` today, so visible blast radius is small.
This is a correctness fix, not a UX fix.

## Change

`scripts/queries/register.py:746–750` — CASE rewrite to coalesce both columns.

**Canonical form: Option A — `COALESCE(entity_type, manager_type)`.**
`entity_type` is the canonical post-PR-migration source per ROADMAP
parent-level-display-canonical-reads. `manager_type` is the legacy fallback.
Option B (`COALESCE(manager_type, entity_type)`) would re-assert the legacy
column as primary and contradict the migration direction.

**Disagreement-row convention:** when `entity_type` AND `manager_type` are both
non-NULL but disagree, `entity_type` wins (consistent with COALESCE order).
Documented in the code comment at the rewrite site.

```sql
-- before
CASE
    WHEN entity_type = 'passive' THEN 'Passive (Index)'
    WHEN entity_type = 'activist' THEN 'Activist'
    WHEN manager_type IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
    ELSE 'Other/Unknown'
END

-- after
CASE
    WHEN COALESCE(entity_type, manager_type) = 'passive' THEN 'Passive (Index)'
    WHEN COALESCE(entity_type, manager_type) = 'activist' THEN 'Activist'
    WHEN COALESCE(entity_type, manager_type) IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
    ELSE 'Other/Unknown'
END
```

## Pre-fix vs post-fix LQ Other/Unknown counts

LQ = `2025Q4`. Total LQ universe: 3,205,650 rows / $67,321.2B.

| Bucket           | Pre-fix rows | Pre-fix AUM ($B) | Post-fix rows | Post-fix AUM ($B) | Δ rows   | Δ AUM ($B) |
|------------------|-------------:|-----------------:|--------------:|------------------:|---------:|-----------:|
| Other/Unknown    |    1,543,537 |         23,032.4 |     1,567,788 |          19,661.6 |  +24,251 |   −3,370.8 |
| Active           |              |                  |     1,471,173 |          26,726.1 |          |            |
| Passive (Index)  |              |                  |       166,424 |          20,845.5 |          |            |
| Activist         |              |                  |           265 |              87.9 |          |            |

Post-fix Other/Unknown share: **48.91% rows / 29.21% AUM** (was 48.15% / 34.21%).
Net AUM moved out of Other/Unknown: **−$3.37T** (−14.6% relative). Row count
ticks up slightly because some `m=active_family, e=other_family` rows
reclassify out of Active under the entity-type-wins convention; this is the
deliberate disagreement-rule outcome, not a regression.

## Spot-check (5 previously-dropped rows)

All five rows were `Other/Unknown` pre-fix and now bucket per the COALESCE
order:

| manager_type       | entity_type   | ticker | cik         |   value | pre-fix       | post-fix |
|--------------------|---------------|--------|-------------|--------:|---------------|----------|
| `mixed`            | `hedge_fund`  | SPY    | 0001446194  | $36.1B  | Other/Unknown | Active   |
| `mixed`            | `active`      | AAPL   | 0000895421  | $27.2B  | Other/Unknown | Active   |
| `passive`          | `quantitative`| NVDA   | 0000354204  | $15.1B  | Other/Unknown | Active   |
| `wealth_management`| `active`      | NVDA   | 0001600064  | $3.2B   | Other/Unknown | Active   |
| `passive`          | `active`      | CSCO   | 0001125816  | $2.0B   | Other/Unknown | Active   |

Each result matches the expected bucket per the documented convention.

## Verification

| Step                                              | Result |
|---------------------------------------------------|--------|
| 1. `pytest tests/`                                | **373 passed**, 1 warning, 83.35s |
| 2. `cd web/react-app && npm run build`            | **0 errors**, vite build OK |
| 3. Pre/post LQ Other/Unknown breakdown            | Captured above; AUM −$3.37T moved out |
| 4. 5-row spot-check                               | 5/5 reclassify into expected bucket |

## Pre-flight evidence

- DB backup `data/backups/13f_backup_20260502_172551` present (today, ≥17:25:51).
- Port 8001 empty.

## Rollback boundary

Local to `scripts/queries/register.py:746–750`. Revert is one diff hunk;
no schema, no data migration, no API contract change. Independent of CP-1
(different code surface, different data, different rollback boundary).

## Out-of-scope follow-ups

- CP-5: parent-level-display-canonical-reads sweep — every other read site that
  references `manager_type`/`entity_type` should be audited and converted to
  the canonical COALESCE pattern (or to `entity_type` direct if that surface
  has already migrated).
- React tab wiring for `/api/v1/query4` if/when the Active/Passive split
  becomes a visible chart.
