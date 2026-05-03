# cp-4b-author-trowe — results

Generated 2026-05-03 by `scripts/oneoff/cp_4b_author_trowe.py --confirm`.

Single-brand AUTHOR_NEW_BRIDGE for T. Rowe Price. Bridges brand
eid=17924 (T. Rowe Price Associates, Inc.) to filer eid=3616
(PRICE T ROWE ASSOCIATES INC /MD/) via the standard CP-4b
`wholly_owned` / `control` BRIDGE shape per PR #258 (CP-4b-blackrock)
precedent. Pure new-row INSERT — no fund_holdings_v2 re-point, no SCD
closure on the brand eid, no recompute pipelines.

Pairing source: `cp-4b-discovery_rank5` (PR #260). Confidence HIGH via
single CRD chain `105496 -> cik:80255`. Direct prod write per
`docs/decisions/inst_eid_bridge_decisions.md` staging-workflow note
(CP-4a + CP-4b-blackrock precedent).

Pre-flight backup: `data/backups/13f_backup_20260503_121103` re-used
(post-PR-C, HEAD 9e58e8f). Intervening commit 1b68aac is docs-only
(ROADMAP.md + NEXT_SESSION_CONTEXT.md only); DB mtime unchanged at
2026-05-03 12:11:22 — backup is byte-identical to live DB. User
confirmation in chat.

## 1. Pre-execution Phase 1 confirmations

### 1a. Brand and filer eids

| eid    | canonical_name                    | entity_type |
| ------ | --------------------------------- | ----------- |
| 3616   | PRICE T ROWE ASSOCIATES INC /MD/  | institution |
| 17924  | T. Rowe Price Associates, Inc.    | institution |

### 1b. CRD chain

- `entity_identifiers` for eid 17924, type=crd, open: `000105496` (9-digit
  zero-padded form; `adv_managers.crd_number` stores `'105496'` unpadded).
- `adv_managers` row for crd `105496`: cik=`80255`,
  firm_name=`T. ROWE PRICE ASSOCIATES, INC.`
- `entity_identifiers` for cik `0000080255`, open: eid=`3616`.

CRD chain validated: `eid 17924 -> crd 105496 -> cik 80255 -> eid 3616`.

### 1c. Idempotency check

Existing open `entity_relationships` rows between (3616, 17924): **0**.
No collision; pair is genuinely unbridged.

### 1d. Filer hv2 visibility

`holdings_v2` rows for entity_id=3616: **18,064** (matches
cp-4b-discovery §4 expected ~18,064).

### 1e. Fund AUM exposure for brand 17924

`fund_holdings_v2` (rollup_entity_id OR dm_rollup_entity_id = 17924,
is_latest=TRUE): **66,552 rows / $1,105.54B** (~$1.11T, matches
discovery rank-5 expectation).

### 1f. Pre-write baseline

- Open relationships (`valid_to = '9999-12-31'`): **16,320**
- MAX(relationship_id): **20,819**
- Prepared new relationship_id: **20,820**

## 2. INSERT execution

Single BEGIN/COMMIT, all guards passed inside the transaction.

### Pre-flight guards

- ✓ Brand entity row present (eid 17924).
- ✓ Filer entity row present (eid 3616).
- ✓ Filer hv2 presence non-zero (18,064 rows).
- ✓ Existing bridge count (3616↔17924, either direction) = 0.
- ✓ Brand has open SCD rows (ECH/ERH/aliases > 0).
- ✓ Prepared relationship_id 20,820 does not pre-exist.

### INSERT shape

| column              | value                                                                          |
| ------------------- | ------------------------------------------------------------------------------ |
| relationship_id     | 20820                                                                          |
| parent_entity_id    | 3616                                                                           |
| child_entity_id     | 17924                                                                          |
| relationship_type   | `wholly_owned`                                                                 |
| control_type        | `control`                                                                      |
| is_primary          | TRUE                                                                           |
| primary_parent_key  | 3616                                                                           |
| confidence          | `high`                                                                         |
| source              | `CP-4b-author-trowe|pair=1|pairing_source=cp-4b-discovery_rank5|confidence=HIGH|crd_chain=105496->cik:80255` |
| is_inferred         | FALSE                                                                          |
| valid_from          | 2026-05-03                                                                     |
| valid_to            | 9999-12-31                                                                     |
| created_at          | 2026-05-03 16:11:51.186368                                                     |
| last_refreshed_at   | 2026-05-03 16:11:51.186368                                                     |

### Post-execution guards

- ✓ Row count delta: 18,370 → 18,371 (Δ +1).
- ✓ Open-row delta: 16,320 → 16,321 (Δ +1, matches Phase 1f baseline + 1).
- ✓ MAX(relationship_id) post: 20,820 (= pre + 1).
- ✓ Pair-specific count `(parent=3616, child=17924, wholly_owned, control,
  open)` = 1 (exactly).

## 3. Post-execution validation

### Spot-check

The new row matches the planned shape exactly (see §2 INSERT shape).

### Filer 3616 holdings_v2 AUM (sanity — must be unchanged)

- 18,064 rows / **$3.56B** in `holdings_v2` (latest). Unchanged from
  Phase 1d capture. BRIDGE does not re-point holdings — confirmed.
- Note: filer-side 13F-only AUM is small because most T. Rowe Price
  exposure flows through fund-side brand eid 17924's $1.11T.

### Bridge-encoded children (parent has hv2 presence)

- Pre-write: 4,731 distinct child_entity_ids.
- Post-write: 4,732. Δ = +1, matches expectation.

## 4. peer_rotation_flows status

No recompute run. Per PR #258 (CP-4b-blackrock) finding, BRIDGE-only
inserts have zero impact on `peer_rotation_flows` (read side only —
Phase B2 rollup feeds off `holdings_v2`/`fund_holdings_v2` which were
not touched). Skipped optional belt-and-suspenders run; expected delta 0.

## 5. Quality gates

- pytest tests/: **416 passed** (matches main baseline).
- web/react-app `npm run build`: **0 errors** (built in 1.47s).

## 6. Workstream status

- **cp-4b-author-trowe**: SHIPPED (this PR). Single-brand bridge for
  T. Rowe Price brand eid 17924 → filer eid 3616. ~$1.11T fund AUM
  bridged.
- **Open queue (next)**:
  1. `cp-4b-blocker2-corroboration-probe` — read-only investigation of
     LOW cohort signals against the $11.44T residual.
  2. backup-pruning ops PR.

## Refs

- `docs/decisions/inst_eid_bridge_decisions.md` (BLOCKER 2)
- `docs/findings/cp-4b-discovery.md` §4 Rank 5 + §8 recommendation
- PR #258 — CP-4b-blackrock (5-way bridge precedent)
- PR #260 — CP-4b-discovery (rank manifest)
