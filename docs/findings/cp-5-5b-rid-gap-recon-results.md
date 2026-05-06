# CP-5.5b — `fund_holdings_v2` NULL `rollup_entity_id` Recon

Read-only investigation triggered by the Phase 2a Phase-0 ABORT in
`gifted-goldwasser-8fed2e`. Probe (d) flagged a non-trivial population of
NULL `rollup_entity_id` rows on the live slice of `fund_holdings_v2`,
contradicting the CP-5.5b plan addendum §1 claim that the EC path is
"already populated."

DB: `data/13f.duckdb` @ HEAD `8c7d0de` (origin/main).
Branch: `cp-5-5b-rid-gap-recon` (worktree `quirky-curie-9a3f2b`).
Pytest baseline: 447 passed, 8 skipped.

All probes are read-only. No DML executed.

---

## 1. Headline

| Metric                                    | Value |
|-------------------------------------------|------:|
| `fund_holdings_v2` rows, latest, NULL rid | **84,363** |
| AUM exposure                              | **$418,546,733,678** ($418.5B) |
| Distinct `series_id`                      | 104 |
| Distinct `fund_cik`                       | 76 |
| Share of `is_latest=TRUE` row count       | 0.58% |
| Share of `is_latest=TRUE` AUM             | 0.26% |

A small slice numerically — but four-tenths of a *trillion* dollars in
fund-side AUM is not invisible at the rollup layer. Every `entity_id`
on the affected rows is already populated; only the `rollup_entity_id`
and `dm_entity_id` projection columns are NULL.

---

## 2. Cluster analysis

### 2.1 By quarter (B1)

| Quarter | Rows   | AUM            |
|---------|-------:|---------------:|
| 2026Q1  | 25,022 | $102.0B |
| 2025Q4  | 53,669 | $301.3B |
| 2025Q3  |  5,672 |  $15.2B |

Concentrated in the most recent loads. Consistent with the timing of
the CP-5 loader-gap-remediation arc (PRs #290/#291) — entities were
inserted *after* fh2 rows were already in prod with NULL rid.

### 2.2 By `series_id` (B2)

104 distinct series_ids, all "real" S-prefixed identifiers (no `SYN_*`,
no `UNKNOWN`, no NULL). Top-30 fully covered by `fund_universe`
(matched 30/30). Highest concentration: `S000009238` (10,606 rows /
$48.2B), `S000009229` (7,418 / $26.6B), `S000045538` (7,152 / $2.5B).

### 2.3 By `fund_cik` (B3)

76 distinct fund CIKs. Top-30 cover ~80% of rows. No mass of "shell"
or unattributed CIKs — every CIK resolves to a known entity (see §3).

### 2.4 By `fund_strategy_at_filing` (B4)

| Strategy        | Rows   | Share |
|-----------------|-------:|------:|
| `bond_or_other` | 75,916 | 90.0% |
| `excluded`      |  6,527 |  7.7% |
| `passive`       |  1,263 |  1.5% |
| `active`        |    657 |  0.8% |

Heavily weighted to `bond_or_other` — i.e. the very buckets the
CP-5.5b denominator carve-out narrows AUM-coverage to. This is
exactly the slice Phase 2a is trying to read from.

### 2.5 By `series_id` prefix (B5)

All 84,363 rows are real `S<digit>+` series_ids. **Zero** synthetic
series IDs, zero `UNKNOWN` literals. No "noise" cluster to triage out.

---

## 3. Resolvability

### 3.1 `entity_id` is already populated

```text
entity_id SET, dm_entity_id NULL  →  rows=84,363  aum=$418.5B  (100%)
entity_id NULL                    →  rows=0
```

All affected rows have `entity_id` set. The miss is **purely the
projection step** — `rollup_entity_id` and `dm_entity_id` columns
were never written, despite `entity_id` being correctly linked.

### 3.2 Direct EC projection from `entity_id` resolves 100%

Single-hop JOIN `fund_holdings_v2.entity_id → entity_rollup_history
(rollup_type='economic_control_v1', valid_to = '9999-12-31')`:

```text
total_rows   = 84,363
resolvable   = 84,363  ($418,546,733,678)
unresolvable = 0
```

Across all 76 distinct `entity_id`s:
- 76/76 have an **open EC** rollup row.
- 76/76 have an **open DM** rollup row.

The entity infrastructure is **complete**. The gap is between the
entity layer and the projection columns on `fund_holdings_v2`.

### 3.3 Provenance of the 76 `entity_id`s

| `entities.created_source`                 | Count |
|-------------------------------------------|------:|
| `CP-5-pre:cp-5-loader-gap-remediation-sub2` | 53 |
| `int-21_series_triage`                       | 23 |

`entity_id` range: 26537 .. 27312. The 53 sub2 entities sit inside the
PR #291 range (27260..27312, per memory `cp-5-loader-gap-remediation-sub2`).
The 23 int-21 entities are older (from PR #100). All 76 received
self-rollups for both `decision_maker_v1` and `economic_control_v1`
(per memory `entity_creation_both_rollup_types`).

---

## 4. `holdings_v2` cross-check (Phase 2)

```text
holdings_v2 NULL rid (latest)  rows=0  aum=$0
holdings_v2 entity_id NULL      rows=0  aum=$0
holdings_v2 total (latest)      rows=12,270,984  aum=$243.4T
```

`holdings_v2` is **clean** on the EC projection — both `entity_id`
and `rollup_entity_id` are 100% populated on `is_latest=TRUE`. The
plan addendum §1 claim is correct *for `holdings_v2` only*.

The asymmetry: `holdings_v2` is the institution-tier tape and is
projected by the 13F loader, which has been re-run cleanly post the
loader-gap-remediation arc. `fund_holdings_v2` is the fund-tier tape
populated by N-PORT and was **not re-projected** after the new
entities landed.

---

## 5. Plan addendum §1 correction

| Claim (per CP-5.5b plan addendum §1)                                     | Evidence                                                |
|--------------------------------------------------------------------------|----------------------------------------------------------|
| "EC rollup column already populated; direct projection works"            | True only for `holdings_v2`.                             |
| "fund_holdings_v2 EC column already populated; direct projection works"  | **WRONG.** 84,363 rows / $418.5B / 76 entities NULL rid. |
| "No backfill required for CP-5.5b Phase 2a"                              | **WRONG.** 100% deterministic backfill is required.       |

The original Phase-0 probe (d) was correct to ABORT. The "already
populated" framing in the addendum was inherited from the
`holdings_v2` shape and not separately verified for
`fund_holdings_v2`.

---

## 6. Why the loader's own projection JOIN missed these rows

`load_nport.py::_bulk_enrich_run` (and `_enrich_staging_entities`)
projects rid via:

```sql
JOIN entity_identifiers ei
  ON ei.identifier_type = 'series_id'
 AND ei.valid_to = DATE '9999-12-31'
 AND ei.identifier_value IN (:series_touched)
```

Of the 76 distinct `entity_id`s on the affected rows, **0** have an
open `series_id` identifier in `entity_identifiers`. They were
linked through a different path (`cik` or N-PORT manifest), so the
loader's series-keyed JOIN cannot resolve them.

This is a structural mismatch: the entity-link key (`cik`/manifest)
diverges from the projection-JOIN key (`series_id`). For the loader-gap
sub1/sub2 cohort, the `entity_id` was written directly (probably by
a one-shot remediation UPDATE), without populating an open series_id
alias on the `entity_identifiers` row.

---

## 7. Recommended backfill scope

**Cluster A — deterministically resolvable (single SQL UPDATE):**

  - Rows: 84,363 (100% of the gap)
  - AUM:  $418.5B (100% of the gap)
  - JOIN key: `fund_holdings_v2.entity_id` → `entity_rollup_history.entity_id`
    (NOT `series_id`; bypasses the loader's existing JOIN shape)
  - Required updates: `rollup_entity_id`, `dm_entity_id`
  - Source: `entity_rollup_history` open rows for both
    `economic_control_v1` and `decision_maker_v1`

**Cluster B — manual / new-entity work:**

  - Empty. No rows in this category.

The full $418.5B is in Cluster A.

---

## 8. Recommended next step

**Recommendation: split CP-5.5b Phase 2a into two PRs.**

  1. **`cp-5-5b-fh2-rid-backfill`** (a single SQL UPDATE, scoped to
     `WHERE rollup_entity_id IS NULL AND is_latest = TRUE`, JOIN on
     `entity_id`). Drop-in: surgically closes the 84,363-row gap and
     restores the precondition the addendum §1 claimed. Touches one
     table, one column path, no compute changes. Includes assertion
     gates: (a) post-UPDATE NULL rid count == 0 on live slice;
     (b) total live AUM unchanged within 1¢; (c) projection delta
     == $418,546,733,678.
  2. **`cp-5-5b-precompute-rebuild`** (the original Phase 2a in
     `gifted-goldwasser-8fed2e`) resumes once Phase 1 is green.

The split keeps the projection-fix and the precompute-refactor
independently reviewable and revertable. It also fixes the loader's
JOIN-key mismatch (§6) as a separate concern — the long-term fix is
either to back-add a series_id alias on the 76 entities, or to switch
the loader projection JOIN to `entity_id` (mirroring the backfill
shape).

---

## 9. Re-verification of plan addendum claims §1–7

| §  | Claim                                                              | Status |
|----|--------------------------------------------------------------------|--------|
| 1  | EC column already populated; direct projection                     | **WRONG for fund_holdings_v2** ($418.5B gap). Holds for holdings_v2. |
| 2  | DM rollup follows same path as EC                                  | Same gap. `dm_entity_id` is NULL on every NULL-rid row. |
| 3  | No new compute reads required                                       | Holds (verification only — read-only Phase 4). |
| 4  | Sector-rotation reads off rid                                       | Will SUM zero AUM for the 76 affected entities until §7 fix lands. |
| 5  | New-exits reads off rid                                             | Same caveat — quarter-on-quarter exit detection on these series silently treats them as unattributed. |
| 6  | AUM-tier denominator unaffected                                     | $418.5B / $161.6T = 0.26% — material if any one of the 76 entities crosses a tier boundary; fix first, recompute denominators second. |
| 7  | Activist column unaffected                                          | Holds — `is_activist` is sourced separately from rid; no overlap. |

Recommend re-running addendum §4–§6 numerically after the §7
backfill PR lands and a fresh AUM precompute is generated.

---

## 10. Loader follow-up (out of CP-5.5b scope)

The structural mismatch in §6 will cause the next N-PORT load to
silently re-introduce NULL-rid rows for any new entity that gets
linked to `fund_holdings_v2` via `cik`/manifest without a series_id
alias being authored. Two options for permanent remediation:

  - **Option A** — backfill open `series_id` aliases on the 76
    entities (and going forward, on every loader-gap remediation PR).
  - **Option B** — switch `load_nport.py::_bulk_enrich_run` to JOIN
    on `entity_id` directly via the (now-populated) staged
    `entity_id` column, fall back to series_id only when entity_id
    is NULL.

Option B is the lower-risk fix and aligns the loader's projection
key with the backfill shape recommended in §7. Either way, this is
a separate workstream and should not block CP-5.5b.

---

## 11. Read-only confirmation

No DML, no DDL, no schema changes. All probes read against
`data/13f.duckdb` with `read_only=True`. The Phase 2a worktree
`gifted-goldwasser-8fed2e` was not touched.
