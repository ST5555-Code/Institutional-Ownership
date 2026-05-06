# cp-5-pipeline-contract-cleanup — results

Closes Gaps 4 + 7 from `docs/findings/cp-5-bundle-c-discovery.md` §7.5.
Single PR, two cleanups: retire dormant bootstrap scripts; codify and
backfill `entity_relationships.is_inferred` per its convention.

Date: 2026-05-05.

---

## 1. Gap 4 — bootstrap scripts retire/gate decisions

### Investigation (read-only)

| Script | Last commit | Active callers | Verdict |
| --- | --- | --- | --- |
| `scripts/bootstrap_etf_advisers.py` | `08e2400` 2026-04-15 | 0 (docstring refs only) | RETIRE |
| `scripts/bootstrap_residual_advisers.py` | `d330d8f` 2026-04-16 | 0 (docstring refs only) | RETIRE |
| `scripts/bootstrap_tier_c_advisers.py` | `9463b6d` 2026-04-17 | 0 (docstring refs only) | RETIRE |

Caller search: grep across `*.py`, `Makefile`, `*.sh`, `*.yml/yaml`. The
only matches are explanatory docstring comments in
`scripts/oneoff/dera_synthetic_stabilize.py:526`,
`scripts/oneoff/bootstrap_tier_c_wave2.py:5`, and four sites in
`scripts/resolve_pending_series.py`. No `import` statements; no runtime
dependency. The 2026-04-23 comprehensive audit also flagged each as
"never called in current tree".

### Action taken

`git mv` of all three from `scripts/` to `scripts/retired/` (using the
existing convention; `scripts/retired/` already houses other one-shot
fetch/promote/validate scripts). Added `scripts/retired/README.md` with
a per-script cohort table and originating-commit references.

Plan literally specified `scripts/_retired/`; deviation noted — the
existing repo convention is `scripts/retired/` (no underscore prefix),
so the move follows that to avoid creating a parallel directory.

Post-move recheck: `grep -rn` confirms no active code path imports or
invokes any of the three scripts. Pytest suite unaffected (none were
under `tests/`).

---

## 2. Gap 7 — `is_inferred` convention + backfill

### Investigation (read-only)

Pre-state pivot of open rows
(`valid_to = DATE '9999-12-31'`):

| relationship_type | control_type | is_inferred | n |
| --- | --- | --- | --- |
| fund_sponsor | advisory | FALSE | 858 |
| fund_sponsor | advisory | TRUE | 12,128 |
| mutual_structure | mutual | FALSE | 23 |
| parent_brand | control | FALSE | 19 |
| parent_brand | merge | FALSE | 19 |
| sub_adviser | advisory | TRUE | 2,933 |
| wholly_owned | control | FALSE | 337 |

Bundle C §7.5 framed Gap 7 as "1 of 2 'merge' rows uses is_inferred";
the current state has 19 `parent_brand`/`merge` rows, all FALSE — that
description was already stale at write time. **Zero NULLs across all
18,394 rows** (18,394 total; 16,317 open). The column is fully
populated.

Convention (codified in
`docs/decisions/inst_eid_bridge_decisions.md`):

- `is_inferred=TRUE` when programmatic (loader-inferred,
  classifier-inferred, name-similarity-derived).
- `is_inferred=FALSE` when explicitly authored (operator bridge PR,
  SCD MERGE op, registrant-declared in a filing).

Per-source map verified against current data — all rows match the
convention except the orphan_scan cohort. See decisions doc for the
full table.

### Action taken — backfill

Single transaction, hard-guarded:

```sql
BEGIN;
UPDATE entity_relationships
   SET is_inferred = TRUE
 WHERE source = 'orphan_scan'
   AND relationship_type = 'wholly_owned'
   AND control_type = 'control'
   AND is_inferred = FALSE
   AND valid_to = DATE '9999-12-31';
-- 140 rows
COMMIT;
```

Guards verified:

- pre: 140 candidate FALSE rows
- post: 0 FALSE / 140 TRUE on the same predicate
- open-row total unchanged at 16,317
- NULL count unchanged at 0

Closed historical rows on the same `(source, relationship_type,
control_type)` tuple (34 rows) were intentionally left untouched per
SCD immutability.

### Action taken — codify convention

Appended an `is_inferred` convention section to
`docs/decisions/inst_eid_bridge_decisions.md`. Future MERGE / BRIDGE /
loader PRs MUST populate `is_inferred` per the rule. Current invariant
(0 NULLs across all rows) preserved.

### Ambiguous / not flipped

- `name_inference` rows on `wholly_owned/control` (5) and
  `parent_brand/control` (1): currently FALSE. Deliberate carve-out
  per `scripts/oneoff/dm14b_apply.py` docstring — operator asserts the
  corporate fact is verifiable externally despite the heuristic's
  name-match origin. Convention captures this.
- `ADV_SCHEDULE_A`/`B`/`MANUAL` rows (201 across `wholly_owned`,
  `mutual_structure`, `parent_brand`): currently FALSE. Defensible —
  registrant-declared in the ADV filing, so authorship sits with the
  filer, not with our code.
- `nport_orphan_fix` on `fund_sponsor/advisory` (858 rows): currently
  FALSE. Documented as "write-time-only — ambiguous under the rule
  since the underlying script no longer runs". Not flipped this PR.

---

## 3. Validation results

| Check | Result |
| --- | --- |
| `pytest tests/` | **416 passed** in 168s (baseline maintained) |
| `cd web/react-app && npm run build` | **0 errors**, 1.84s |
| App smoke (`./scripts/start_app.sh`, `curl localhost:8001`) | **HTTP 200** |
| `grep` for active callers post-move | 0 active references |
| Backfill row count | 140 flipped exactly |
| Open-row count drift | 0 (16,317 → 16,317) |
| NULL is_inferred drift | 0 (0 → 0) |

---

## 4. CP-5 P0 pre-execution status

7 / 11 PRs shipped (this PR closes #7). Next:
`cp-5-sister-tables-sized-investigation`.

---

## 5. Out-of-scope discoveries / surprises

- Bundle C §7.5's framing of Gap 7 was already stale by the time of
  execution (19 merge rows FALSE, not 1-of-2). Worth a future audit
  pass — Bundle-C numbers may have drifted on other gaps too.
- The `is_inferred` column is more populated than expected: 0 NULLs
  across 18,394 rows. The remaining "ambiguity" is not missing data
  but a documentation gap about what the FALSE/TRUE choice should
  mean per source. That documentation now exists.
- `scripts/retired/` already exists as an established convention — the
  plan's `scripts/_retired/` would have created a parallel directory.
  Followed existing convention.
- Three docstring/comment references to the retired scripts remain in
  newer code (`dera_synthetic_stabilize.py`, `bootstrap_tier_c_wave2.py`,
  `resolve_pending_series.py`). They are explanatory only — left as-is.
