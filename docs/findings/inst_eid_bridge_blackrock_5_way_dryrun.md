# inst-eid-bridge-blackrock-5-way (CP-4b-blackrock) — Phase 2 dry-run

Generated 2026-05-02 by `scripts/oneoff/inst_eid_bridge_blackrock_5_way.py --dry-run`.

## Scope

5 AUTHOR_NEW_BRIDGE inserts per `docs/decisions/inst_eid_bridge_decisions.md`
BLOCKER 1 (brand has CIK and independent SEC registration => BRIDGE).
All 5 are BlackRock sub-brand eids that today have no open `entity_relationships`
row to filer eid=3241 (BlackRock, Inc.). The 6th BlackRock
brand — eid=2 (BlackRock / iShares, $15.7T fund AUM) — already has an open
fund_sponsor row to eid=3241 (relationship_id=153, source=parent_bridge) and
is therefore TRUE_BRIDGE_ENCODED, not in scope here.

## Path-B scope decision (chat 2026-05-02)

Original CP-4b prompt scoped top-25 by AUM. Phase 0 discovery surfaced two
contradictions in the original prompt:

1. The Phase 0.3 filter (`bridge_class=BRAND_HAS_RELATIONSHIP AND counterparty_in_hv2
   IS FALSE`) selects a different cohort than the spec's cited examples. The
   examples (Wellington 9935→11220, Dimensional 7→5026, Franklin 28→4805,
   T. Rowe Price 13→4627, etc.) are all already TRUE_BRIDGE_ENCODED — they
   have an open `entity_relationships` row to a hv2-present counterparty and
   per `inst_eid_bridge_decisions.md` need NO entity_relationships write.

2. Investigation numbers have drifted post-CP-4a. Replicating §4 against the
   current DB: invisible brands 1,225 → 1,337; brands with ≥1 hv2-counterparty
   relationship 86 → 191; unbridged AUM ~$26.0T → $24.6T. The 86 figure
   undercounts because PR #254 used a single-row-per-brand inventory; multi-rel
   brands aren't reflected in the `rel_other_eid` column.

Path B (chat 2026-05-02): split CP-4b into three sub-PRs.

  - **CP-4b-blackrock** (this PR): 5 mechanically-discoverable BlackRock
    sub-brand bridges to eid=3241. Pairings come direct from investigation
    §7.3 with the eid=2 fund_sponsor pre-existing-bridge note layered in.

  - **CP-4b-discovery** (next, read-only): per-brand filer pairings for
    top-20 AUTHOR_NEW_BRIDGE candidates by AUM, derived from `adv_managers`
    ADV cross-ref + parent-corp lookup. Confidence-tiered manifest.

  - **CP-4b-author-top20** (after, execution): apply CP-4b-discovery
    manifest pairings as new entity_relationships rows.

Same shape as PR #249 (cef-scoping) → PR #251 (cef-asa-flip-and-relabel)
precedent.

## Op shape

Pure new-row INSERT. No MERGE, no re-point of `fund_holdings_v2`, no closure
of any other SCD layer. Brand eids stay alive as canonical brand-name
attribution sources. No AUM moves. `peer_rotation_flows` row count unchanged.

Per pair (single Op I, INSERT into `entity_relationships`):

```
relationship_id    = MAX(relationship_id) + N            -- 20815..20819
parent_entity_id   = 3241                                 -- BlackRock, Inc.
child_entity_id    = brand_eid                            -- per pair
relationship_type  = 'wholly_owned'                       -- BRIDGE pattern
control_type       = 'control'                            -- standard for wholly_owned
is_primary         = TRUE
primary_parent_key = 3241
confidence         = 'high'
is_inferred        = FALSE
valid_from         = CURRENT_DATE
valid_to           = DATE '9999-12-31'                    -- open SCD sentinel
source             = 'CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|
                      pair=:N|pairing_source=investigation_§7.3|confidence=HIGH'
created_at         = NOW()
last_refreshed_at  = NOW()
```

`entity_relationships` has no `notes` column (CP-4a finding); audit metadata
encoded into the `source` field as a structured string. `relationship_id` is
assigned via `MAX(relationship_id) + N` per CP-4a precedent (no SEQUENCE/AUTO).

## Phase 0 schema findings

1. **`entity_relationships` schema confirmed.** Columns: relationship_id,
   parent_entity_id, child_entity_id, relationship_type, control_type,
   is_primary, primary_parent_key, confidence, source, is_inferred,
   valid_from, valid_to, created_at, last_refreshed_at. No `notes` column.
   PK is `relationship_id` (BIGINT, no auto-increment). Pre-existing
   MAX(relationship_id) at dry-run time = 20,814; new IDs will be
   20,815 through 20,819.

2. **`relationship_type` value reuse.** Existing distribution: fund_sponsor
   13,707; sub_adviser 3,442; wholly_owned 985; mutual_structure 153;
   parent_brand 78. `wholly_owned` with `control_type='control'` is the
   established BRIDGE shape (985 existing rows). No new enum values.

3. **Open SCD sentinel.** `valid_to = DATE '9999-12-31'` for open rows
   (NOT `IS NULL`); `CURRENT_DATE` for closure (DATE type). Confirmed via
   PR #256 (CP-4a) and verified again here against current DB.

4. **Staging-twin policy.** `docs/staging_workflow_live.md` does not exist
   despite being referenced from `inst_eid_bridge_decisions.md` and
   `inst_eid_bridge_investigation.md`. The `entity_relationships_staging`
   table has a different schema (id auto-seq, owner_name, ownership_pct,
   conflict_reason, review_status default 'pending', reviewer, reviewed_at,
   resolution) — it is a human-review queue, not a parallel write twin.
   CP-4a (PR #256, 2026-05-02) wrote DIRECT to prod `entity_relationships`.
   This PR matches that precedent: single transaction, hard guards, prod
   write. Pre-flight backup at `data/backups/13f_backup_20260502_202932`.

## Phase 1 re-validation (pre-image counts)

### Filer eid=3241 — `BlackRock, Inc.`

- entity_type: `institution`
- holdings_v2 (latest): rows=199,623 AUM=$21,642.7B
- alive (non-zero open SCD rows)

### Pair 1 — eid=7586 (`BlackRock Fund Advisors`)

- entity_type: `institution`
- fund_holdings_v2 (latest): rows=70,554 AUM=$1,303.29B
- holdings_v2 (latest): 0 rows / $0.00B (brand is fund-side only)
- open SCD: ECH=1 ERH=2 aliases=2 total_open_relationships=16
- existing bridge to filer 3241: 0 (gate: must be 0)
- new relationship_id (planned): 20815
- source string: `CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|pair=1|pairing_source=investigation_§7.3|confidence=HIGH`

### Pair 2 — eid=3586 (`BLACKROCK ADVISORS LLC`)

- entity_type: `institution`
- fund_holdings_v2 (latest): rows=213,206 AUM=$645.07B
- holdings_v2 (latest): 0 rows / $0.00B (brand is fund-side only)
- open SCD: ECH=1 ERH=2 aliases=2 total_open_relationships=19
- existing bridge to filer 3241: 0 (gate: must be 0)
- new relationship_id (planned): 20816
- source string: `CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|pair=2|pairing_source=investigation_§7.3|confidence=HIGH`

### Pair 3 — eid=17970 (`BlackRock Investment Management, LLC`)

- entity_type: `institution`
- fund_holdings_v2 (latest): rows=95,262 AUM=$426.48B
- holdings_v2 (latest): 0 rows / $0.00B (brand is fund-side only)
- open SCD: ECH=1 ERH=2 aliases=1 total_open_relationships=102
- existing bridge to filer 3241: 0 (gate: must be 0)
- new relationship_id (planned): 20817
- source string: `CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|pair=3|pairing_source=investigation_§7.3|confidence=HIGH`

### Pair 4 — eid=8453 (`BLACKROCK FINANCIAL MANAGEMENT INC/DE`)

- entity_type: `institution`
- fund_holdings_v2 (latest): rows=5,499 AUM=$149.54B
- holdings_v2 (latest): 0 rows / $0.00B (brand is fund-side only)
- open SCD: ECH=1 ERH=2 aliases=2 total_open_relationships=1
- existing bridge to filer 3241: 0 (gate: must be 0)
- new relationship_id (planned): 20818
- source string: `CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|pair=4|pairing_source=investigation_§7.3|confidence=HIGH`

### Pair 5 — eid=18030 (`BlackRock International Limited`)

- entity_type: `institution`
- fund_holdings_v2 (latest): rows=10,063 AUM=$16.32B
- holdings_v2 (latest): 0 rows / $0.00B (brand is fund-side only)
- open SCD: ECH=1 ERH=2 aliases=1 total_open_relationships=35
- existing bridge to filer 3241: 0 (gate: must be 0)
- new relationship_id (planned): 20819
- source string: `CP-4b-blackrock-author:inst-eid-bridge-blackrock-5-way|pair=5|pairing_source=investigation_§7.3|confidence=HIGH`

## Aggregate

- Total pairs: 5
- Total bridged fund AUM: $2,540.70B (~$2.54T)
- New relationship_id range: 20815 through 20819
- Filer hv2 AUM (unchanged by this PR): $21,642.7B
- fund_holdings_v2 rows touched: 0 (CP-4b is bridge-only, not re-point)
- peer_rotation_flows row count expected delta: 0 (read-side only impact in CP-5)

## Hard guards (--confirm)

- Re-capture pre-image at confirm time; refuse if any pair's brand or
  filer entity row is missing.
- Refuse if any pair's `existing_bridge_count` to filer 3241 is non-zero.
- Refuse if filer 3241 hv2 AUM has dropped to zero.
- Refuse if MAX(relationship_id) drifted such that planned IDs collide
  with concurrent inserts (lock + re-MAX inside transaction).
- Single BEGIN/COMMIT wrapping all 5 INSERTs; ROLLBACK on any
  constraint violation.
- Post-INSERT sanity check: SELECT COUNT(*)=1 per (parent=3241, child=brand,
  valid_to=open) confirms each pair landed.
- Post-transaction row count delta on entity_relationships = 5.

## Next

Authorization gate: per `inst_eid_bridge_decisions.md` CP-4 manual review
gate, `--confirm` requires explicit chat authorization after this dry-run.

