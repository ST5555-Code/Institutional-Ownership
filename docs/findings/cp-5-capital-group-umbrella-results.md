# cp-5-capital-group-umbrella — results

Third P0 pre-execution PR per CP-5 comprehensive remediation plan.
Bridges 3 Capital Group filer arms to the Capital Group umbrella entity
via `wholly_owned`/`control`. Path A locked at Phase 1 — umbrella
entity already exists.

## 1. Phase 1 investigation

### 1.1 Filer arms confirmed

| eid  | canonical_name                       | CIK         | hv2 rows | hv2 AUM (latest) |
|-----:|--------------------------------------|-------------|---------:|-----------------:|
| 6657 | Capital World Investors              | 0001422849  |    2,274 |       $2,772.49B |
| 7125 | Capital Research Global Investors    | 0001422848  |    1,754 |       $2,034.06B |
| 7136 | Capital International Investors      | 0001562230  |    1,786 |       $2,346.46B |
|      | **TOTAL**                            |             |    5,814 |    **$7,153.01B**|

Latest-period AUM (4Q rolling). The original prompt's "$1,915B" cite
mis-read Bundle B's per-quarter snapshot; full 4Q rolling is consistent
with Bundle B §1.3 which reports $7,153B.

Cross-arm relationships: zero (confirmed via Step 1d guard).

### 1.2 Path determination — Path A locked

Bundle B §1.3 explicitly names **eid=12 "Capital Group / American Funds"**
as the canonical umbrella (`eid 12 ← {6657, 7125, 7136} via 3 separate
control ER rows`). Path A locked despite the existence of two other
plausible candidates (eid=6873 "Capital Group Companies, Inc." and
eid=3938 "CAPITAL RESEARCH & MANAGEMENT CO") — neither was named in
the discovery doc and both have weaker structural fit.

eid=12 is a live PARENT_SEEDS-sourced entity (per memory:
`project_inf9d_parent_seeds.md`). Open SCD state at Phase 1 capture:

- 4 open aliases: `Capital Group / American Funds` (brand, preferred);
  `AMERICAN FUNDS` / `CAPITAL GROUP` / `CAPITAL RESEARCH` (filing).
- 1 open ECH row, classification=`active`, source=`PARENT_SEEDS`.
- 2 open ERH self-rows (economic_control_v1, decision_maker_v1).
- 87 open `entity_relationships` as parent — all
  `relationship_type='fund_sponsor'`, `control_type='advisory'`,
  source `parent_bridge` or `family_name_alias_match`. **None** in
  `wholly_owned`/`control` shape.
- 0 hv2 rows (umbrella does not directly hold positions).
- $14,336.20B fh2 rollup AUM (aggregating American Funds family).

### 1.3 Step 1d gating — chat resolution

Plan's Step 1d says "ABORT and surface to chat" if any existing
umbrella → arm bridge exists. **rel_id=358** matched: `(parent=12,
child=7125, fund_sponsor, advisory, parent_bridge)`. Surfaced to
chat 2026-05-05.

Chat decision: **proceed**. The new `wholly_owned`/`control` rows
coexist with the existing `fund_sponsor`/`advisory` row — they
encode different semantic layers. See §3 below and the new section
in [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md).

### 1.4 Pre-write baselines

| metric | value |
|---|---:|
| open `entity_relationships` | 16,314 |
| MAX(`relationship_id`) | 20,840 |
| MAX(`entity_id`) | 27,259 |
| prior bridges sanity (9 ids) | 9/9 intact |

## 2. Phase 2 — skipped (Path A)

Umbrella eid=12 already exists. No new entity rows authored.

## 3. Phase 3 — BRIDGE rows authored

3 new rows in `entity_relationships`, all `wholly_owned`/`control`:

| relationship_id | parent (umbrella) | child (arm) | child name                          |
|----------------:|------------------:|------------:|-------------------------------------|
|          20,841 |                12 |        6657 | Capital World Investors             |
|          20,842 |                12 |        7125 | Capital Research Global Investors   |
|          20,843 |                12 |        7136 | Capital International Investors    |

**Source field encoded per chat decision:**

```
CP-5-pre:cp-5-capital-group-umbrella|arm=<canonical_name>|Path A|coexists_with_parent_bridge_layer|public_record_verified=cp-5-bundle-b-discovery.md_§1.3
```

Column shape per cp-4b precedent (PR #271 ssga most recent):

| column | value |
|---|---|
| relationship_type | `wholly_owned` |
| control_type | `control` |
| is_primary | `TRUE` |
| primary_parent_key | `12` (umbrella_eid) |
| confidence | `high` (Bundle B explicit naming, not inferred) |
| is_inferred | `FALSE` |
| valid_from | 2026-05-05 |
| valid_to | 9999-12-31 |

### 3.1 Two-layer coexistence (post-INSERT state on (12, 7125))

| relationship_id | parent | child | relationship_type | control_type | source                       |
|----------------:|-------:|------:|-------------------|--------------|------------------------------|
|             358 |     12 |  7125 | fund_sponsor      | advisory     | `parent_bridge`              |
|          20,842 |     12 |  7125 | wholly_owned      | control      | `CP-5-pre:cp-5-capital-...`  |

Two rows on the same `(parent, child)` pair, two different semantic
layers. Sponsor-view queries use the first; ownership-view (CP-5
read layer) uses the second. Neither is redundant.

## 4. Phase 4/5 — hard guards + validation

All hard guards passed inside the BEGIN/COMMIT block:

| guard | result |
|---|---|
| Guard 1: 3 new umbrella→arm wholly_owned/control rows | **3 (pass)** |
| Guard 2: open-row delta = +3 | **16,314 → 16,317 (pass)** |
| Guard 3: MAX(rel_id) = pre+3 | **20,840 → 20,843 (pass)** |
| Guard 4: per-arm hv2 row count + AUM unchanged | **3/3 pass** |
| Guard 5: per-arm fh2 rollup row count + AUM unchanged | **3/3 pass** |

Post-validation:

- `pytest tests/` → **416 passed, 0 failed** (54s).
- `cd web/react-app && npm run build` → **0 errors** (1.60s).
- `entity_current.display_name` for 3 arms unchanged.
- Each arm reachable from umbrella via Method A traversal
  (`wholly_owned`/`control` edge): 3/3 confirmed.
- prior bridges (cp-4a 20813/20814, cp-4b 20820-20823, Adams 20830,
  cycle-truncated 20831/20840) still intact.

## 5. P0 pre-execution status

| # | cohort                              | status           | PR                                            |
|--:|-------------------------------------|------------------|-----------------------------------------------|
| 1 | cp-5-adams-duplicates               | shipped          | [#283](https://github.com/.../pull/283)       |
| 2 | cp-5-cycle-truncated-merges         | shipped          | [#285](https://github.com/.../pull/285)       |
| 3 | **cp-5-capital-group-umbrella**     | **this PR**      | (forthcoming)                                 |
| 4 | cp-5-pipeline-contract-gaps         | next             | (read Bundle C §7.5; size individually)       |
| 5 | cp-5-loader-gap-remediation         | heaviest cohort  | (84K rows; 2-3 sub-PRs)                       |

Then CP-5.1 — helper + Method A view definition — for which the new
bridge rows are the prerequisite rollup graph input.

## 6. Out-of-scope discoveries / surprises

**Two-relationship-layer coexistence pattern (now canonical for umbrella firms).**
Bundle B §1.3 stated that eid=12 had no inst→inst edges to its
siblings. Current data shows 87 `parent_bridge` `fund_sponsor` rows on
eid=12 — including 1 row to one of the 3 arms (rel 358 → 7125). This
is a different mechanism (sponsor-brand layer, likely auto-populated
by N-CEN / parent_bridge_sync loader), not a stale snapshot mismatch.

Chat decision 2026-05-05 codified this as a permanent architectural
pattern — see new section "Two-relationship-layer coexistence pattern
for umbrella firms" in `docs/decisions/inst_eid_bridge_decisions.md`.

**Follow-up parked as P3:** `parent-bridge-mechanism-audit` — read-only
audit surfacing all firms carrying `parent_bridge` relationships, to
establish scope of the sponsor-brand layer across the database. Does
not block CP-5; will fold into a future doc-sync.

**eid=6873 ("Capital Group Companies, Inc.") and eid=3938 ("CAPITAL
RESEARCH & MANAGEMENT CO") remain unbridged to the 3 arms.** Bundle B
chose eid=12 as canonical umbrella; the holding-company entity
(eid=6873) and the operating-adviser entity (eid=3938) are not
incorporated into this bridge cohort. If a future cohort wants
multi-tier corporate structure (Capital Group Companies → CRMC → 3
divisions), that is separate work — not in scope here.

**AUM cite correction.** Original prompt cited "~$1,915B" as the AUM
bridged. Actual latest-period (4Q rolling) total is **$7,153.01B**
across the 3 arms, matching Bundle B §1.3. Per-quarter snapshot is
~$1.79T. The prompt mis-read Bundle B's per-quarter figure as the total.
