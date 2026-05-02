# inst-eid-bridge-fix-aliases (CP-4a) — Phase 2 dry-run

Generated 2026-05-02 by `scripts/oneoff/inst_eid_bridge_aliases_merge.py --dry-run`.

## Scope

2 BRAND_TO_FILER alias merges per `docs/decisions/inst_eid_bridge_decisions.md`
BLOCKER 1 (brand has no CIK and is name-only synthetic => MERGE):

- **Vanguard** brand_eid=1 → filer_eid=4375 (`VANGUARD GROUP INC`)
- **PIMCO** brand_eid=30 → filer_eid=2322 (`PACIFIC INVESTMENT MANAGEMENT CO LLC`)

Original prompt framed CP-4a as 5 merges. Phase 1 discovery against
`data/working/inst_eid_bridge/eid_inventory.csv` returned **zero** qualifying
`BRAND_HAS_NAME_MATCH` candidates: only 4 such rows exist in the inventory,
all MEDIUM/LOW confidence with brand_name significantly different from
filer_name (Aperio/Ascent, Altaba/Alphabet, Oaktree/Olstein, Robinson/
Revelation). These match the Calvert → "Stanley Capital Management"
false-positive prototype the decisions doc BLOCKER 2 explicitly rejected.
Per prompt instruction, no synthesis from lower-confidence tiers; scope
collapses to 2. Decisions doc correction lands in CP-4a results commit.

## Phase 1 schema findings

Five corrections to the original prompt's op shape, surfaced during
read-only re-validation 2026-05-02 and confirmed in chat:

1. **OP D dropped.** The `entities` table has no `valid_to` column —
   it is a flat registry. SCD lives in `entity_identifiers`,
   `entity_relationships`, `entity_classification_history`,
   `entity_rollup_history`, `entity_aliases`. "Closing" a brand
   means closing its open SCD-layer rows.
2. **OP A column scope reduced.** `entity_id` and `dm_entity_id` in
   `fund_holdings_v2` are FUND-level and never carry the brand_eid.
   Setting them to filer would mass-mis-attribute every fund's identity
   to the manager. `family_name` and `fund_name` are fund-level labels
   (`VANGUARD MUNICIPAL BOND FUNDS` etc.) and stay. Only
   `rollup_entity_id`, `dm_rollup_entity_id`, `dm_rollup_name` shift.
3. **OP A WHERE uses OR**, not AND, on the two rollup columns. PIMCO
   has 92 rows where `rollup_entity_id=30` but `dm_rollup_entity_id=18402`;
   `WHERE dm_rollup_entity_id=:brand` alone misses them.
4. **OP B re-points fund_sponsor edges**, does not close them. The
   brands sponsor 57 (Vanguard) / 25 (PIMCO) fund_eids via open
   `entity_relationships` rows; closing would orphan those funds
   from sponsor lineage. Re-point parent_entity_id from brand to
   filer instead. Op B' separately closes the single brand↔filer
   alias-bridge row (different shape per pair: Vanguard has
   `parent=4375 child=1 wholly_owned`; PIMCO has `parent=30 child=2322`
   `fund_sponsor` parent_bridge — would become self-loop after re-point).
5. **OPs F + G added.** The original prompt missed `entity_rollup_history`
   and `entity_aliases` SCD layers. `entity_current` view depends on
   both for display; without closure/re-point, brand display would
   stay anchored at the brand_eid. F closes the 2 open rollup rows
   per brand. G re-points open brand aliases to filer entity_id with
   pre-flight demotion of incoming `is_preferred=TRUE` rows where the
   filer already has a same-`alias_type` preferred alias open.

Schema sentinels: `valid_to = DATE '9999-12-31'` for open SCD rows
(NOT `IS NULL`); `CURRENT_DATE` for closure (DATE type, not TIMESTAMP).
OP E reuses `relationship_type='parent_brand'` with `control_type='merge'`
rather than introducing a novel `merged_into` enum value.

## Per-pair pre-image counts

### Vanguard (brand_eid=1 → filer_eid=4375)

- filer canonical_name: `VANGUARD GROUP INC`
- `fund_holdings_v2` is_latest=TRUE:
  - brand-side rows: 267,751 / $2,541.53B
  - filer-side rows pre-merge: 569,793 / $38,729.80B
  - filer-side AUM expected post-merge: $41,271.33B
- Op B re-point fund_sponsor edges: 57 rows
- Op B' close alias-bridge / self-loop: 1 row
- Op C close entity_classification_history: 1 row
- Op E insert audit row: 1 (parent_brand / merge)
- Op F close entity_rollup_history: 2 rows
- Op G re-point entity_aliases: 0 rows (0 demoted preferred)

### PIMCO (brand_eid=30 → filer_eid=2322)

- filer canonical_name: `PACIFIC INVESTMENT MANAGEMENT CO LLC`
- `fund_holdings_v2` is_latest=TRUE:
  - brand-side rows: 289,132 / $1,717.00B
  - filer-side rows pre-merge: 34,561 / $327.20B
  - filer-side AUM expected post-merge: $2,044.20B
- Op B re-point fund_sponsor edges: 25 rows
- Op B' close alias-bridge / self-loop: 1 row
- Op C close entity_classification_history: 1 row
- Op E insert audit row: 1 (parent_brand / merge)
- Op F close entity_rollup_history: 2 rows
- Op G re-point entity_aliases: 2 rows (1 demoted preferred)

## Aggregate

- Total brand-side fund_holdings_v2 rows re-pointed: 556,883
- Total brand-side AUM moved to filer: $4,258.53B
- Total entity_relationships re-pointed: 82
- Total entity_relationships closed (alias bridges): 2
- Total entity_classification_history closed: 2
- Total entity_rollup_history closed: 4
- Total entity_aliases re-pointed: 2
  (of which demoted from preferred to non-preferred: 1)
- Total OP E audit rows inserted: 2

## Hard guards (--confirm)

- Refuse if pre-image counts diverge >5% from manifest at confirm time.
- Refuse if any per-pair sanity check fails.
- Refuse if AUM conservation fails (>$0.01B post-merge filer-AUM delta).
- BEGIN/COMMIT wraps all 2 pairs; ROLLBACK on any constraint violation.

## Next

Authorization gate: per `inst_eid_bridge_decisions.md` sequencing note +
the manual review gate added in c53337c, --confirm requires explicit
chat authorization after this dry-run review.

