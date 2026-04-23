# entity-curation-w1 — session log

**Date:** 2026-04-23
**Branch:** `entity-curation-w1`
**Scope:** batch-close **INF37** + **int-21 SELF-fallback** + **43e family_office** (standing curation cluster).

## Outcome summary

| Item | Result | Rows / entities affected |
|---|---|---|
| INF37 (NULL manager_type) | **APPLIED to prod.** CSV edit + prod backfill. 0 residuals. | 14,368 holdings_v2 rows / 9 entities |
| int-21 SELF-fallback | **SELF-CONFIRMED for all 12** (plan said 11 — actual = 12). No MDM writes. | 0 |
| 43e family_office | **DE-SCOPED** per Phase 4 audit. Downstream enum surface (build_summaries.py + queries.py) needs a bucket-membership policy call. Deferred to follow-on. | 0 |

**Prod state after session:**
- `holdings_v2` manager_type NULL/unknown rows: **14,368 → 0** (zero residuals).
- `summary_by_ticker`: 47,642 → 47,732 (+90 rows, expected from newly classified entities).
- `summary_by_parent`: 63,916 (unchanged — rollup graph untouched).
- `validate_entities.py` prod baseline: **8 PASS / 1 FAIL / 7 MANUAL** preserved (pre-existing `wellington_sub_advisory` FAIL untouched).

---

## Item A — INF37 resolution

### Phase 1 identification (prod)

```sql
SELECT COALESCE(inst_parent_name, manager_name) AS name, COUNT(*) AS rows, SUM(market_value_usd)/1e9 AS aum_b
FROM holdings_v2 WHERE manager_type IS NULL OR manager_type = 'unknown'
GROUP BY 1 ORDER BY aum_b DESC;
```

| Entity | Rows | AUM ($B) | ADV CRD | ADV RAUM ($B) | ADV pct_disc |
|---|---:|---:|---|---:|---:|
| MML INVESTORS SERVICES, LLC | 11,401 | 78.58 | 10409 | 90.02 | 59.0 |
| Invst, LLC | 877 | 2.46 | 282863 | 1.79 | 72.7 |
| Foyston, Gordon & Payne Inc | 223 | 1.76 | 121591 | 4.72 | 74.6 |
| Compton Financial Group, LLC | 210 | 1.59 | 166912 | 0.84 | 53.8 |
| DRAVO BAY LLC | 193 | 0.86 | 298558 | 0.34 | 72.8 |
| LOWERY THOMAS, LLC | 218 | 0.65 | 110058 | 0.34 | 56.2 |
| Retireful, LLC | 422 | 0.43 | 313126 | 0.23 | 36.8 |
| Savior LLC | 64 | 0.09 | 299178 | 0.11 | 69.6 |
| CKW FINANCIAL GROUP | 760 | 0.00 | 152116 | 2.21 | 51.8 |

### Phase 2 decision table

| Entity | Assigned `manager_type` | Rationale |
|---|---|---|
| MML INVESTORS SERVICES, LLC | `wealth_management` | MassMutual retail broker-dealer/RIA; 59% discretionary, retail-facing |
| Invst, LLC | `wealth_management` | Small Indianapolis RIA; retail advisory |
| Foyston, Gordon & Payne Inc | `active` | Toronto institutional equity manager (AGF-owned); discretionary active mandates, no retail-wealth posture |
| Compton Financial Group, LLC | `wealth_management` | Towson MD RIA (Red Oak Financial Group d/b/a) |
| DRAVO BAY LLC | `wealth_management` | Delaware RIA (Blue Rock Financial Group d/b/a) |
| LOWERY THOMAS, LLC | `wealth_management` | Small RIA |
| Retireful, LLC | `wealth_management` | Retirement-planning RIA |
| Savior LLC | `wealth_management` | Wellesley MA RIA (Savior Wealth d/b/a) |
| CKW FINANCIAL GROUP | `wealth_management` | Honolulu RIA |

### Phase 3 — staging validation

```
sync_staging.py: 9 entity tables copied, 256 overrides, sequences reset.
backfill_manager_types.py (staging dry-run): 11,177 rows projected to update across 9 entities
  (staging.holdings_v2 is stale — 9.28M rows vs prod's 12.27M — but all 9 entities match, classifications apply).
backfill_manager_types.py (staging apply): 11,177 rows flipped, 0 residuals.
diff_staging.py: 0 entities / 0 classifications / 0 rollups / 0 relationships changed
  (436 override line-level diff is pre-existing NULL-override_id drift per INF22, not this session's work).
validate_entities.py --staging: 8 PASS / 1 FAIL / 7 MANUAL — baseline preserved.
```

### Phase 5 — prod apply

```
backfill_manager_types.py --production:
  BEFORE: unknown rows=14,368, unknown entities=9
  AFTER:  unknown rows=0, unknown entities=0
  Recovered: 14,368 rows, 9 entities

  Distribution delta on prod:
    wealth_management  1,292,108 → 1,306,253  (+14,145)
    active             4,544,437 → 4,544,660  (+223)
    unknown               14,368 → 0          (-14,368)

build_summaries.py --rebuild: summary_by_ticker 47,642→47,732, summary_by_parent 63,916 (unchanged).
validate_entities.py (prod): 8 PASS / 1 FAIL / 7 MANUAL — baseline preserved.
```

`promote_staging.py` intentionally NOT run — Item A touches only `holdings_v2` which is outside `ENTITY_TABLES` (cf. `scripts/db.py:92`). The staging workflow is scoped to the entity MDM; fact-table writes follow the direct prod-apply pattern (precedent: Rewrite5 prod apply `7747af2`).

---

## Item B — int-21 SELF-fallback, all 12 confirmed SELF

### Phase 1 identification

Query (case-corrected — `source='self'` is lowercase; `int-21_series_triage` source captures the curation cohort):

```sql
SELECT ec.entity_id, ec.display_name, ec.classification
FROM entity_current ec
JOIN entity_rollup_history erh ON erh.entity_id = ec.entity_id
WHERE erh.rollup_entity_id = ec.entity_id
  AND erh.valid_to = DATE '9999-12-31'
  AND erh.source = 'int-21_series_triage'
ORDER BY ec.entity_id;
```

Actual count = **12 entities** (plan said 11 — off by one). All 12 enumerated below.

### Phase 2 decision — all SELF-confirmed

Each of the 12 entities is a **zero-impact MDM root** in current data:

| Check (per entity) | Result for all 12 |
|---|---|
| `holdings_v2` rows (manager-side) | 0 |
| `fund_holdings_v2` rows | 0 |
| Child entities rolling up to this eid | 0 |
| `entity_relationships` (as parent or child) | 0 rows |
| `ncen_adviser_map` registrant match by CIK | 0 matches |

Because these entities hold nothing, have no children, no relationships, and no N-CEN adviser link to disambiguate parent, assigning a speculative parent produces zero data-flow benefit and carries risk of misclassifying when future fund data lands. Per plan's "confirm SELF is correct (standalone filer)" branch, all 12 are closed as SELF.

| eid | Name | Current classification | Resolution |
|---|---|---|---|
| 26548 | ARK ETF Trust | active | SELF-confirmed — ARK ETF Trust is the fund trust vehicle; the adviser (eid 1531, ARK Investment Management LLC) lives in the MDM but this is the inert trust registrant. Reassign on-demand if holdings attach. |
| 26557 | AXONIC FUNDS | active | SELF-confirmed — "Axonic Capital" adviser not in MDM. |
| 26562 | AFL CIO Housing Investment Trust | active | SELF-confirmed — standalone trust, no parent adviser. |
| 26566 | Ironwood Institutional Multi-Strategy Fund LLC | active | SELF-confirmed — Ironwood Capital Management (the correct adviser) not in MDM. |
| 26584 | Reaves Utility Income Fund | active | SELF-confirmed — adviser W.H. Reaves & Co (eid 2844) exists, but fund trust has zero holdings; defer reassignment until holdings attach. |
| 26588 | COMMUNITY CAPITAL TRUST | active | SELF-confirmed — Community Capital Management adviser not in MDM. |
| 26589 | Bluerock Private Real Estate Fund | active | SELF-confirmed — Bluerock Capital not in MDM. |
| 26590 | Leader Funds Trust | active | SELF-confirmed — Leader Capital Management not in MDM. |
| 26592 | APOLLO DIVERSIFIED REAL ESTATE FUND | active | SELF-confirmed — Apollo Global Management umbrella not clean in MDM (only Apollo Management Holdings LP, eid 9576); defer. |
| 26595 | Gabelli Dividend & Income Trust | active | SELF-confirmed — Gabelli umbrella (eid 20 / eid 756 GABELLI FUNDS LLC) exists, but trust has zero holdings; defer reassignment. |
| 26597 | Ironwood Multi-Strategy Fund LLC | active | SELF-confirmed — same rationale as 26566. |
| 26601 | Emerging Markets Local Income Portfolio | active | SELF-confirmed — Dimensional Fund Advisors has 5 candidate eids (7, 1328, 4790, 5026, 6248) with no disambiguator; defer. |

**Follow-on trigger:** when any of these 12 entities gains `fund_holdings_v2` or `holdings_v2` rows, re-run triage with full series lineage and reassign parent if the adviser is in MDM.

No writes applied for Item B. No `entity_overrides_persistent` rows added.

---

## Item C — 43e family_office, DE-SCOPED

### Phase 4 downstream audit

Adding `family_office` as a new `manager_type` value touches two closed-list enumerations:

- `scripts/build_summaries.py:173,181` — `SUM(CASE WHEN h.manager_type IN ('active','hedge_fund','quantitative','activist') THEN …)` → populates `active_weight_usd` on `summary_by_ticker`/`summary_by_parent`. Family offices should arguably be counted as active, but the call is a policy decision (some family offices run primarily passive/index positions).
- `scripts/queries.py:1724` — `WHEN manager_type IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'` → maps types to the Active/Passive dichotomy for surface queries.

Pre-existing inconsistency: `multi_strategy` and `SWF` already exist as holdings_v2 values and are **not** in either IN-list today. A clean fix for `family_office` should resolve `multi_strategy` / `SWF` bucket membership at the same time — i.e. this is a taxonomy refactor, not a one-line add.

Frontend (`web/react-app/src/components/common/typeConfig.ts`) already degrades gracefully — unknown types render with the fallback (gray badge, raw label) via `getTypeStyle`. Not a blocker.

**Conclusion:** scope exceeds a single batch-close session. Item C remains **open** in ROADMAP §Open items, re-filed as a dedicated "taxonomy refactor — family_office + multi_strategy + SWF bucket membership" follow-on. This PR does not touch the taxonomy.

### Candidates inventoried (for the follow-on)

From ROADMAP 43e list + this session's lookups:

| Candidate | MDM eid(s) | Current class | Notes |
|---|---|---|---|
| Soros Fund Management | 92, 2218 | hedge_fund | Converted to family office 2011 |
| Moore Capital Management | 9928 | hedge_fund | Closed to outside capital 2019 (family office) |
| ICONIQ Capital, LLC | 1676 (+ 1463, 2009, 2522, 4513, 6798, 8734, 9547) | hedge_fund / active / unknown | Started as Zuckerberg family office; now hybrid PE/VC |
| Longview Partners | 10236, 10735 | unknown / active | **NOT** a family office — UK global equity shop. Exclude. |
| Briar Hall Management LLC | 5422 | strategic | Family office |
| Consulta Ltd | 1927 | strategic | Bertarelli family office (London) |
| Allen & Co | 3985, 8989 | unknown | **NOT** a pure family office — merchant bank/boutique. Exclude. |

Filtered final candidate list for follow-on: 5 confirmed family offices (Soros, Moore, ICONIQ, Briar Hall, Consulta). Longview + Allen excluded on classification grounds.

---

## Files modified

- `categorized_institutions_funds_v2.csv` — **+9 rows** (Item A classifications).
- `ROADMAP.md` — INF37 moved to closed log; int-21 SELF-fallback closed; 43e refiled as taxonomy-refactor follow-on.
- `docs/NEXT_SESSION_CONTEXT.md` — Cluster 2 item closed with this PR.
- `docs/findings/entity-curation-w1-log.md` — this file (new).

## Not modified / intentionally out of scope

- `entity_overrides_persistent` — no new rows (Item B all SELF-confirmed).
- `scripts/build_summaries.py`, `scripts/queries.py`, `web/react-app/src/components/common/typeConfig.ts` — Item C de-scoped.
- Securian/Sterling, HC Capital Trust, CRI/Christian Brothers — per session brief, closed by DM12 (2026-04-10, `ada58ac`), confirmed by PR #112.
- Entity fragmentation work (INF5/6/7/8/16) — separate.

## Verification

- Staging workflow clean (0 entity-substance diff).
- `validate_entities.py` prod baseline preserved (8 PASS / 1 FAIL / 7 MANUAL).
- `build_summaries.py --rebuild` ran cleanly (7.7s).
- No direct-to-prod writes on entity tables. Item A prod write is to `holdings_v2` (fact table, outside `ENTITY_TABLES`), following the Rewrite5 precedent.
