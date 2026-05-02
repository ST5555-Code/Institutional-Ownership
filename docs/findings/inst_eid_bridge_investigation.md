# Brand-vs-filer eid bridge — investigation

Read-only scoping investigation. Snapshot date: **2026-05-02**. Prod DB:
`data/13f.duckdb`. No DB writes, no schema changes, no production module
modifications.

Continues PR #252 (`institution_scoping`) by enumerating the 1,225 invisible
institutions per-brand-eid with proposed remediation actions. Critical-path
PR-1 (CP-1) deliverable; CP-4 will land the bridge mappings.

Helper scripts: `scripts/oneoff/inst_eid_bridge_*.py` (4 helpers).
Verification: `grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b'`
returns only `CREATE OR REPLACE TEMP VIEW` lines (in-memory, read-only
connection) and zero DDL/DML executes against the prod DB.

---

## 1. Executive summary

**The PR #252 headline replicates exactly: 1,225 invisible brand
eids / $27,797.71B fund-side AUM.**

**Material reframe: the CIK-keyed Mode A/B/C audit the plan asked for is a
dead-end on this DB.** `fund_holdings_v2.fund_cik` (N-PORT trust CIK) and
`holdings_v2.cik` (13F filer adviser CIK) are mutually exclusive populations.
The eid mismatch lives one layer up — at the entity level — not at the CIK
level. **Mode B (CIK-keyed eid mismatch) = 0 ciks / $0**. **Mode B' (eid pairs
sharing a CIK via `entity_identifiers`) = 0 pairs.**

The audit reframes around the **eid-level** picture:

| Cohort | Brand eids | Fund AUM | Action |
|---|---:|---:|---|
| **TRUE_BRIDGE_ENCODED** — counterparty in holdings_v2 | 86 | (subset of $27T) | Already encoded, read sites just don't traverse |
| **BRIDGE_DANGLES_TO_FUNDS** — relationships exist, but only to fund-trust eids | 412 | ~$26.0T | **No real bridge.** Most relationships are `fund_sponsor`/`sub_adviser` connecting brand→fund-trust, not brand→filer |
| **BRAND_HAS_NAME_MATCH** — exact normalized-name match to filer eid | 4 | $1.6B | Low confidence (3 are identical-name duplicates) |
| **BRAND_ORPHAN** — no relationship, no name match, no CIK overlap | 723 | $943B | Investigate — long tail of small brands |
| **TOTAL** | **1,225** | **$27,797.71B** | |

**Concentration: Top 10 invisible brand eids = 51.2% of AUM. Top 25 = 68.2%.
Top 100 = 90.9%.** Per-institution remediation against the top 100 captures
nearly all the exposure; the orphan long tail is small-dollar.

**ECH coverage of invisible brands = 1,207 / 1,225 (98.5%) by count;
99.76% by AUM.** ECH has classifications for the brands but does NOT encode
the brand-vs-filer relationship.

**`entity_identifiers` is not a bridge.** Of 1,225 invisible brands, 791 have
at least one CIK in `entity_identifiers`. **Zero of those CIKs appear in
`holdings_v2.cik`.** Brand entities carry trust/fund CIKs (N-PORT
registrants); filer entities carry adviser CIKs. The two CIK universes are
disjoint.

**Vanguard, PIMCO, BlackRock together = $22.6T of $27.8T (~81%)**, matching
PR #252's expectation that the three named families dominate. Each has a
distinct shape:
- **Vanguard:** simple alias-pair shape (eid=1 ↔ eid=4375). Recommended
  action: **BRAND_TO_FILER** (re-point fund rolls FROM 1 TO 4375), or merge.
  HIGH confidence. PR #251 ASA-style.
- **PIMCO:** **PIMCO does not file 13F** under any in-DB entity. Both eid=30
  ("PIMCO" name-only) and eid=2322 (PACIFIC INVESTMENT MANAGEMENT CO LLC
  with CIK 0001163368) carry $0 in `holdings_v2`. CIK 0001163368 is absent
  from `holdings_v2.cik` entirely. **INVESTIGATE_FURTHER** — the gap is
  upstream (13F ingestion does not seem to reach PIMCO's CIK).
- **BlackRock:** classic **BRIDGE** shape. eid=2 ("BlackRock / iShares")
  with 6 fund-trust CIKs holds $15.7T fund AUM. eid=3241 ("BlackRock, Inc.")
  with 1 corp CIK (0002012383) holds $21.6T filer AUM. Two distinct legal
  entities, no `entity_relationships` row connecting them. Bridge needs
  authoring. Plus 5 sub-brand fund-side eids (Fund Advisors $1.3T,
  Advisors LLC $645B, Investment Mgmt $426B, Financial Mgmt $149B,
  International $16B) — each is a sub-bridge candidate to eid=3241.

**Critical-path observation.** `entity_relationships` already accommodates a
`wholly_owned` / `parent_brand` shape for brand→filer mappings — 8 of the top
12 true bridge candidates use it. CP-4 can extend this pattern (no schema
change required) for the ~80–100 missing top-tier mappings.

---

## 2. Phase 0 — Re-validation

PR #252 numbers replicate exactly against `data/13f.duckdb` 2026-05-02:

| Metric | PR #252 | This audit | Delta |
|---|---:|---:|---:|
| Distinct holdings_v2 entity_ids (latest) | 9,121 | 9,121 | 0 |
| Distinct fund_holdings_v2 dm_rollup_entity_ids | 1,707 | 1,707 | 0 |
| Invisible brand eids (any-join definition) | 1,225 | 1,225 | 0 |
| Invisible AUM | $27,797.71B | $27,797.71B | $0 |
| Invisible rows | — | 6,929,560 | — |
| holdings_v2 latest rows | — | 12,270,984 | — |
| holdings_v2 latest AUM | — | $243,366.79B | — |
| fund_holdings_v2 latest rows | — | 14,565,870 | — |
| fund_holdings_v2 latest AUM | — | $161,590.47B | — |

The institution layer has **not** materially changed since PR #252. Audit
proceeds.

---

## 3. Phase 1 — CIK-keyed inventory: Mode A / B / C

The plan asked for a CIK-based join between `fund_holdings_v2` (fund-tier)
and `holdings_v2` (institution-tier). Result:

| Mode | Definition | CIK count | Fund/filer AUM |
|---|---|---:|---:|
| A | fund_cik in fund-tier with no holdings_v2 row at same CIK | 1,991 | $161,576B (fund-side) |
| **B** | **same CIK in both, brand_eid ≠ filer_eid** | **0** | **$0** |
| C | filer cik in holdings_v2 with no fund-tier row at same CIK | 9,116 | $243,341B (filer-side) |

**Mode B is zero.** This is the structurally important finding from the
CIK-keyed pass: `fund_cik` is the N-PORT trust CIK; `holdings_v2.cik` is the
13F filer adviser CIK. These are different SEC registration types and
overlap is essentially nil. Mode A subsumes virtually all fund-tier rows
(99.99% of fund AUM is on a CIK that doesn't appear in `holdings_v2`); Mode
C subsumes virtually all institution-tier rows. Neither is a useful signal.

The brand-vs-filer eid issue lives at the entity-mapping layer — between
fund-tier `dm_rollup_entity_id` and holdings-tier `entity_id` — not at the
CIK level. PR #252 framed it correctly. The plan's CIK-keyed framing was a
hypothesis worth testing; it tested negative.

CSVs: `data/working/inst_eid_bridge/mode_a_brand_no_filer.csv` (1,991 rows),
`mode_b_eid_mismatch.csv` (0 rows), `mode_c_filer_no_brand.csv` (9,116 rows).
Helper: `scripts/oneoff/inst_eid_bridge_phase1_inventory.py`.

---

## 4. Phase 1b — Eid-level inventory (the real audit)

Reframed audit per the eid-level shape PR #252 surfaced.

### 4.1 Per-brand classification

For each of 1,225 invisible brand eids:

| Bridge class | Recommended action | Confidence | Brand count | Fund AUM |
|---|---|---|---:|---:|
| BRAND_HAS_RELATIONSHIP | BRIDGE | HIGH | 498 | $26,853B |
| BRAND_HAS_NAME_MATCH | FILER_TO_BRAND | MEDIUM | 3 | $1.6B |
| BRAND_HAS_NAME_MATCH | FILER_TO_BRAND | LOW | 1 | $0.01B |
| BRAND_ORPHAN | INVESTIGATE_FURTHER | LOW | 723 | $943B |
| **Total** |  |  | **1,225** | **$27,798B** |

Then a critical sub-cut: **of the 498 BRAND_HAS_RELATIONSHIP brands, only
86 have a counterparty that's actually in `holdings_v2`.** The rest have
relationships of type `fund_sponsor` / `sub_adviser` connecting brand to
fund-trust eids — useful for fund-tier rollup attribution but NOT for
bridging to the 13F filer side.

### 4.2 Relationship type breakdown (498 BRAND_HAS_RELATIONSHIP)

| relationship_type | control_type | distinct brands | row count | AUM (sum across fund-tier) |
|---|---|---:|---:|---:|
| fund_sponsor | advisory | 372 | 6,217 | (rolls to fund-trust counterparties) |
| sub_adviser | advisory | 191 | 1,729 | (rolls to fund-trust counterparties) |
| wholly_owned | control | 83 | 103 | (mostly brand→parent-firm, useful) |
| parent_brand | control | 2 | 2 | (useful) |
| mutual_structure | mutual | 1 | 1 | (rare) |

**Counterparty-in-hv2 resolution**: 8,003 (brand, counterparty) pairs total,
**only 96 pairs (86 distinct brands) have the counterparty in
`holdings_v2`**. The 86 brands are the actionable bridge cohort.

### 4.3 Top-12 actionable bridge candidates (counterparty in hv2)

| brand_eid | brand_name | counterparty_eid | counterparty_name | rel_type | fund AUM |
|---:|---|---:|---|---|---:|
| 1 | Vanguard Group | 4375 | VANGUARD GROUP INC | wholly_owned | $2,541.5B |
| 9935 | Wellington Management Co LLP | 11220 | WELLINGTON MANAGEMENT GROUP LLP | fund_sponsor | $757.5B |
| 7 | Dimensional Fund Advisors | 5026 | DIMENSIONAL FUND ADVISORS LP | wholly_owned | $510.8B |
| 18062 | GQG Partners LLC | 7623 | GQG Partners LLC | wholly_owned | $325.9B |
| 77 | PGIM | 10914 | PRUDENTIAL FINANCIAL INC | wholly_owned | $269.4B |
| 8994 | MANULIFE FINANCIAL CORP | 8179 | MANUFACTURERS LIFE INSURANCE | wholly_owned | $265.7B |
| 28 | Franklin Templeton | 4805 | FRANKLIN RESOURCES INC | wholly_owned | $147.9B |
| 13 | T. Rowe Price | 4627 | T. Rowe Price Investment Management | fund_sponsor | $141.0B |
| 142 | COHEN & STEERS CAPITAL MANAGEMENT | 4595 | COHEN & STEERS, INC. | wholly_owned | $138.0B |
| 3704 | Northern Trust Investments | 4435 | NORTHERN TRUST CORP | fund_sponsor | $84.3B |
| 2981 | Calvert Research & Management | 1100 | Stanley Capital Management | wholly_owned | $76.8B |
| 19 | Eaton Vance | 2920 | MORGAN STANLEY | wholly_owned | $49.4B |

These are the eids whose `entity_relationships` row genuinely bridges to a
13F filer that's present in `holdings_v2`. The pattern is dominantly
**brand→parent-corp** (`wholly_owned`) — the 13F filer is the parent firm
that aggregates positions across all sub-advisers, and the brand entity is
the operating-company sub-adviser.

**Anomaly to surface for chat review:** eid=2981 Calvert Research &
Management → eid=1100 "Stanley Capital Management, LLC" looks wrong (Calvert
was acquired by Eaton Vance / Morgan Stanley, not "Stanley Capital
Management"). Likely a stale or mis-merged relationship row. Flag for CP-4
data-quality pass.

CSVs: `eid_inventory.csv` (1,225 rows, full per-brand inventory),
`relationship_types.csv` (8,003 (brand, counterparty) pairs),
`mode_b_prime_eid_pairs.csv` (0 rows — confirms no `entity_identifiers`
overlap).

Helper: `scripts/oneoff/inst_eid_bridge_phase1b_eid_level.py`.

### 4.4 BRAND_ORPHAN long tail (723 brands / $943B)

| brand_entity_type | brand count | fund AUM |
|---|---:|---:|
| institution | 692 | $906.66B |
| fund | 31 | $36.62B |
| **Total** | **723** | **$943.28B** |

| created_source | is_inferred | brand count | fund AUM |
|---|---|---:|---:|
| bootstrap_tier4 | False | 656 | $567.44B |
| managers | True | 3 | $144.78B |
| ncen_adviser_map | True | 16 | $125.24B |
| int-21_series_triage | False | 6 | $41.17B |
| fund_universe | True | 31 | $36.62B |
| manual_13dg_resolution | False | 11 | $28.03B |

**90% of orphan brands** were created via `bootstrap_tier4` (cohort/wave
processes). These are mid-tier MDM-created entities with no upstream
relationships authored. Long tail is small-dollar (avg $1.3B per brand);
top-50 orphans are written to `orphan_top50.csv` for sample review.

The 31 `entity_type='fund'` orphans / $36.6B are mis-typed funds rolling up
to themselves — they should be classified as `entity_type='institution'`
or pruned (likely captured by the existing
`fund-holdings-orphan-investigation` ROADMAP item).

---

## 5. Phase 2 — Per-institution recommended action

Bridge action mapping by class:

| Class | Action | When to use | Verification |
|---|---|---|---|
| BRAND_HAS_RELATIONSHIP, counterparty in hv2 (86 brands) | **BRIDGE** (use existing row) | Read-site sweep traverses entity_relationships and unions hv2 rows | Counterparty appears in `holdings_v2.entity_id` AND has same canonical-firm meaning |
| BRAND_HAS_RELATIONSHIP, counterparty NOT in hv2 (412 brands, ~$26T) | **AUTHOR_NEW_BRIDGE** | Existing relationship is brand→fund-trust, not brand→filer; need a new `entity_relationships` row of type `wholly_owned` or `parent_brand` connecting brand to its 13F filer | Brand has filer-side eid ∈ {NULL — must discover} |
| BRAND_HAS_NAME_MATCH (4 brands, $1.6B) | **FILER_TO_BRAND** or merge | Same canonical name on both sides — likely a duplicate | Manual review |
| BRAND_ORPHAN (723 brands, $943B) | **INVESTIGATE_FURTHER** | No bridging signal at all | Per-brand triage; expect most to be inactive shells |

**The dominant cohort is AUTHOR_NEW_BRIDGE (412 brands / ~$26T).** The
investigation deliverable here is naming the cohort, not generating the
mappings (which is a CP-4 build). For each top-100 brand by AUM, the CP-4
build needs to:
1. Identify the firm's actual 13F filer eid (heuristics: parent-corp lookup,
   Form ADV cross-ref, manual pairing).
2. Author a new `entity_relationships` row of type `wholly_owned` (parent =
   filer, child = brand) or `parent_brand`.
3. Decide whether read sites bridge via the relationship (BRIDGE), re-point
   fund_holdings_v2.dm_rollup_entity_id (BRAND_TO_FILER), or merge entities.

Top-100 manifest is in `eid_inventory.csv` (sorted by `fund_aum` DESC,
filter `bridge_class != 'BRAND_ORPHAN'` for actionable rows).

---

## 6. Phase 3 — ECH coverage check

| Metric | Value |
|---|---:|
| Invisible brand eids with open ECH classification | 1,207 / 1,225 (98.5%) |
| Invisible AUM with ECH classification | $27,730.0B / $27,797.7B (99.76%) |
| Invisible brand eids with NO open ECH | 18 / 1,225 (1.5%) |

Open ECH classification distribution for invisible brands:

| classification | distinct brands | fund AUM |
|---|---:|---:|
| active | 429 | $14,849.3B |
| passive | 32 | $6,151.9B |
| unknown | 703 | $4,731.1B |
| private_equity | 2 | $727.5B |
| mixed | 13 | $645.5B |
| hedge_fund | 19 | $617.3B |
| strategic | 8 | $7.3B |
| quantitative | 1 | $0.1B |

**ECH knows about the brands and classifies them, but does NOT encode the
brand-vs-filer relationship.** The bridge defect is `entity_relationships`-
shaped, not ECH-shaped. The fix does NOT require ECH writes.

The 703 brands classified `unknown` overlap heavily with the 723 BRAND_ORPHAN
cohort — most orphans are also classification-unknown. Their resolution is
joint: classification migration via existing pending_entity_resolution flow,
plus a per-orphan investigation to determine if the brand should be merged,
re-pointed, or left as a fund-only attribution.

Helper: `scripts/oneoff/inst_eid_bridge_phase2_relationships.py` (covers
both Phase 2 relationship analysis and Phase 3 ECH).

---

## 7. Phase 4 — Vanguard / PIMCO / BlackRock deep-dives

Helper: `scripts/oneoff/inst_eid_bridge_phase4_deepdives.py`.
CSVs: `deepdive_Vanguard.csv`, `deepdive_PIMCO.csv`, `deepdive_BlackRock.csv`,
`deepdive_Pacific_Investment_Management.csv`.

### 7.1 Vanguard

196 entities match `canonical_name LIKE '%VANGUARD%'`. Activity concentrated
in 4:

| eid | name | type | ECH | fund AUM | filer AUM | CIKs |
|---:|---|---|---|---:|---:|---|
| **4375** | VANGUARD GROUP INC | institution | passive | **$38,729.8B** | **$25,287.3B** | 0000102909, 0000932471 (+CRD 105958) |
| **1** | Vanguard Group | institution | passive | $2,541.5B | $0 | (none) |
| 4364 | Vanguard Personalized Indexing Management, LLC | institution | passive | $0 | $35.7B | 0001767306 |
| 842 | Vanguard Capital Wealth Advisors | institution | wealth_management | $0 | $0.4B | 0001730578 |

eid=4375 is the canonical Vanguard Group registration with both CIKs and a
CRD. eid=1 is a name-only synthetic with no CIK that holds $2.5T of fund
rolls but zero filer presence.

**Recommendation:** **BRAND_TO_FILER** with HIGH confidence. Re-point
fund_holdings_v2.dm_rollup_entity_id (and 3 sibling columns: rollup_entity_id,
dm_entity_id, entity_id) FROM 1 TO 4375 across ~267,751 rows. Equivalent
shape to the PR #251 ASA fix. Existing `wholly_owned` relationship row
1↔4375 supports the merge.

eid=4364 (Vanguard Personalized Indexing) and 842 (Vanguard Capital Wealth
Advisors) are independent sub-entities with their own filer presence; leave
them alone.

224 open relationships involve Vanguard-named entities — most are
`fund_sponsor` rows linking 4375 → individual Vanguard funds, expected.

### 7.2 PIMCO / Pacific Investment Management

Two relevant brand entities, plus 17 PIMCO-named CEFs:

| eid | name | type | ECH | fund AUM | filer AUM | CIK |
|---:|---|---|---|---:|---:|---|
| **30** | PIMCO | institution | active | $1,716.0B | **$0** | (none) |
| **2322** | PACIFIC INVESTMENT MANAGEMENT CO LLC | institution | mixed | $327.2B | **$0** | 0001163368 |
| 26773 | PIMCO Corporate & Income Opportunity Fund | institution | unknown | $5.2B | $0 | 0001190935 |
| ... 16 more PIMCO CEFs ... | | | | (varies) | $0 | (per-fund) |

**Critical finding: PIMCO's CIK 0001163368 is absent from
`holdings_v2.cik` entirely.** The institution-tier ingestion has no record of
PIMCO filing 13F at all. Verified by direct lookup:
`SELECT * FROM holdings_v2 WHERE cik='0001163368'` returns 0 rows.

Allianz-side check: PIMCO is a subsidiary of Allianz SE. Allianz SE
(eid=1358, CIK 0001127508) does file 13F ($20.4B), and Allianz Asset
Management GmbH (eid=589, CIK 0001535323) files $348.4B. **None of these is
plausibly PIMCO's $1.7T US-equity rollup target** — the AUM numbers don't
match.

**Most likely diagnosis:** PIMCO US's 13F filings are missing from the
`holdings_v2` ingestion universe (a gap upstream — possibly because PIMCO
files a small 13F covering only US equities while most assets are
fixed-income, or because the ingestion filter excluded their
`form-13F-NT` filings). **This is not a bridge problem; it's an ingestion
problem.**

**Recommendation:** **INVESTIGATE_FURTHER** at the ingestion layer (out of
CP-4 scope). Brand eid=30 ("PIMCO" name-only with no CIK) should still be
merged into eid=2322 (BRAND_TO_FILER, HIGH confidence) so the canonical
PIMCO entity is the one with a CIK. The $1.7T fund rollups can re-point
from 30 → 2322 immediately. The "where does the $1.7T 13F filing live"
question stays open as a P2 ROADMAP item.

57 open relationships involve PIMCO/Pacific Investment Management entities
— mostly `fund_sponsor` rows.

### 7.3 BlackRock

257 entities match `canonical_name LIKE '%BLACKROCK%'`. Activity concentrated
in 6 brand eids (fund-side only) plus 1 filer eid:

| eid | name | type | ECH | fund AUM | filer AUM | CIKs |
|---:|---|---|---|---:|---:|---|
| **3241** | BlackRock, Inc. | institution | passive | $0 | **$21,642.7B** | 0002012383 |
| **2** | BlackRock / iShares | institution | passive | **$15,738.2B** | $0 | 0001306550, 0001364742, 0001137391, 0000888410, 0000882152, 0000884216 |
| 7586 | BlackRock Fund Advisors | institution | passive | $1,303.3B | $0 | 0001006249 |
| 3586 | BLACKROCK ADVISORS LLC | institution | passive | $645.1B | $0 | 0001086364 |
| 17970 | BlackRock Investment Management, LLC | institution | active | $426.5B | $0 | (none) |
| 8453 | BLACKROCK FINANCIAL MANAGEMENT INC/DE | institution | passive | $149.5B | $0 | 0001086363 |
| 18030 | BlackRock International Limited | institution | active | $16.3B | $0 | (none) |
| 9160 | BLACKROCK (SINGAPORE) LTD. | institution | passive | $11.8B | $0 | 0001559921 |
| 17999 | BlackRock Advisors, LLC | institution | (NULL) | $7.8B | $0 | (none) |
| ... 56 BlackRock CEFs (small) ... | | | | (varies) | $0 | |

**This is the textbook brand-vs-filer eid duplication shape.** All BlackRock
fund AUM (~$18.3T across 6 brand eids) routes through fund-side-only
entities. ALL BlackRock 13F filings ($21.6T) route through one filer-only
entity (eid=3241, CIK 0002012383, recently created). **Zero
`entity_relationships` rows directly connect any of the 6 brand eids to
eid=3241.**

The 6 fund-side brand entities map to mutual fund trust CIKs (the eid=2
universe is iShares trusts; eid=7586 is BlackRock Fund Advisors LLC; etc.).
None of those CIKs appears in `holdings_v2.cik`.

**Recommendation:** **BRIDGE** with HIGH confidence — author 6 new
`entity_relationships` rows of type `wholly_owned` (parent_entity_id=3241,
child_entity_id=each_brand_eid). Then read sites bridge via traversal.

Alternative: **BRAND_TO_FILER** to merge all 6 fund rollups into eid=3241 —
simpler reads but loses the brand-name attribution (a fund displays as
"BlackRock, Inc." instead of "iShares" or "BlackRock Fund Advisors"). Loss
of granularity; not recommended unless brand-name display is dropped from
the read surface.

761 open relationships involve BlackRock-named entities — all are
`fund_sponsor`/`sub_adviser` brand→fund-trust rows.

### 7.4 Three-family AUM share

| Family | Fund AUM (invisible brands) | Share of $27.8T |
|---|---:|---:|
| BlackRock (6 brand eids excluding CEFs) | $18,289.4B | 65.8% |
| Vanguard (eid=1 only) | $2,541.5B | 9.1% |
| PIMCO (eids 30 + 2322) | $2,043.2B | 7.3% |
| **Three-family total** | **$22,874.1B** | **82.3%** |

PR #252 expected the three families to "account for >50%". They account for
**82%**. The long tail is even smaller than expected — strengthens the case
for top-100-driven CP-4 scoping.

---

## 8. Phase 5 — CP-4 dependency map

### 8.1 Per-action dependency table

| Action | Affected tables | Affected read sites | Sequencing notes |
|---|---|---|---|
| BRIDGE (read-site sweep) | None (read-only) | All 18 parent-level read sites + Datasette + React | **Folds into CP-5** (parent-level-display-canonical-reads). Same sweep that handles ECH-aware joins handles relationship traversal. |
| BRAND_TO_FILER (re-point fund_holdings_v2) | `fund_holdings_v2` (4 columns: dm_rollup_entity_id, rollup_entity_id, dm_entity_id, entity_id), `entities` (close brand eid valid_to), `entity_relationships` (close brand-side rows), `entity_classification_history` (close brand-side ECH row) | Anything joining on brand eid (Top-25, query5, fund tab, market tab, register query1/2/3) | **Pre-CP-5.** Loader must re-stamp on next quarter. Apr 11–12 entity-merge-marathon CIK-transfer rule applies (memory: `cik_transfer_rule.md`). |
| AUTHOR_NEW_BRIDGE (insert entity_relationships row) | `entity_relationships` (1 row per pairing; staging→sync→promote per `staging_workflow_live.md`) | Read sites that traverse relationships post-CP-5 | **Bundles into CP-4.** Top-100 brands — manual pairing inputs needed (see Open Question #2). |
| INVESTIGATE_FURTHER (orphan triage) | None during investigation; merges/closes after | None | **Defers past CP-5.** New ROADMAP item: `inst-eid-bridge-orphan-triage` (P3). |

### 8.2 Interaction with existing ROADMAP items

Investigation interacts with these queued items:

| ROADMAP item | Relationship |
|---|---|
| `parent-level-display-canonical-reads` (CP-5) | CP-4's bridge writes change what CP-5's read sweep reads. CP-4 must land first. |
| `deprecated-fund-rollup-targets-cleanup` (P3, captured 2026-05-02) | 19 deprecated entities still receive fund rolls ($68.7B). Any merged-eid in scope here is also a CP-4 input — check overlap. |
| `ingestion-manifest-reconcile` (CP-2) | Independent — no eid-layer dependency. |
| `query4-fix-option-a` (CP-3) | Independent — entity_type/manager_type CASE bug is separate from eid bridge. |
| `fund-holdings-orphan-investigation` (P2) | Sub-cohort overlap: 31 orphan brands have entity_type='fund'; both items can resolve them. Coordinate so CP-4 doesn't trample fund-side orphan triage. |
| `apr11_12_data_qc.md` (memory) | The 656 `bootstrap_tier4` brands in BRAND_ORPHAN are leftovers from cohort/wave merges. CIK transfer rule (memory `cik_transfer_rule.md`) applies if any are merged. |

### 8.3 Single-transaction or staged?

CP-4 cannot ship as a single transaction. Recommended sequence:

```
CP-4a: BRAND_TO_FILER for top-3 trivial cases — Vanguard eid=1 → 4375;
       PIMCO eid=30 → 2322; small alias-pair cases discovered during
       per-brand triage. Apr 11–12 cohort-merge shape. ~5 brands. SMALL.
CP-4b: AUTHOR_NEW_BRIDGE for top-25 by AUM — BlackRock 6-way bridge to 3241;
       Wellington 9935→11220; Dimensional 7→5026; etc. ~25 entity_relationships
       inserts via staging→sync→promote. MEDIUM.
CP-4c: AUTHOR_NEW_BRIDGE for next-75 (top-100 total). MEDIUM, but
       parallelizable with CP-5 read sweep.
```

Each sub-PR (4a/4b/4c) is independently shippable. CP-5 (read sweep) needs
4a + 4b minimum — bridge for ~$24T of $27.8T — to give enough payoff to
justify the read-site sweep effort. The orphan tail and 4c can post-date.

### 8.4 Sequencing within Q1 cycle

CP-4a and 4b are pre-cycle eligible (small brands, manual pairings, no
data-volume risk). CP-4c needs Q1 data to surface any new fund-tier rollup
targets and is post-cycle. CP-5 follows CP-4a+4b.

---

## 9. Open questions for chat decision

Per CP-1 critical-path gate: each must be resolved BEFORE CP-4 prompt is
written.

1. **(BLOCKER)** **Bridge mode for top-100: BRAND_TO_FILER (merge) or
   AUTHOR_NEW_BRIDGE (relationship row)?** They imply different write
   shapes, different entity-count outcomes, and different display behavior
   downstream:
   - Merge: simpler reads, single eid per firm, but loses brand-name
     granularity (BlackRock funds display as "BlackRock, Inc." not "iShares").
   - Bridge: preserves brand-name attribution; reads must traverse a
     relationship; entity count grows.
   Recommended **BRIDGE for BlackRock-shape (multi-brand → one filer)**;
   **MERGE for Vanguard-shape (alias pair, no brand-name to preserve)**.
2. **(BLOCKER)** **Pairing source for top-100 AUTHOR_NEW_BRIDGE.**
   We have 86 brands with existing relationships pointing to a hv2-present
   counterparty — those are easy. The other ~14 of the top-100 need a
   pairing input. Three options: (a) Form ADV cross-ref via `adv_managers`
   table; (b) manual pairing list authored in CP-4; (c) regex /
   fuzzy-name match with manual review. Recommended (a) + (b) hybrid.
3. **(BLOCKER)** **PIMCO 13F gap.** Should the investigation surface a
   ROADMAP item to find PIMCO's missing 13F filings (CIK 0001163368
   absent from `holdings_v2`), or is this expected (PIMCO files
   form-13F-NT only)? Affects whether top-100 includes a "find missing
   PIMCO" task or just resolves the eid=30→2322 alias.
4. **(non-blocker)** **eid=2981 Calvert → eid=1100 "Stanley Capital
   Management" anomaly.** Is the relationship row correct, mis-merged, or
   a typo for "Morgan Stanley"? Spot-check during CP-4b.
5. **(non-blocker)** **31 orphan `entity_type='fund'` brands.** Mis-typed
   institutions, or actual self-rollup-to-fund cases? Coordinate with
   `fund-holdings-orphan-investigation` (P2).
6. **(non-blocker)** **6 BlackRock sub-brand bridges all to eid=3241?** Or
   should sub-brands first bridge to a brand-wrapper eid (eid=2 BlackRock
   / iShares) and then eid=2 → eid=3241? Two-tier bridge is more accurate
   to org structure but doubles read-site complexity.
7. **(non-blocker)** **Long-tail BRAND_ORPHAN (723 / $943B) treatment.**
   Per-brand triage is high effort, low yield ($1.3B avg). Recommended
   defer to a new P3 ROADMAP item (`inst-eid-bridge-orphan-triage`); ship
   only if a triggering display gap surfaces.

---

## 10. Recommended CP-4 manifest

The investigation deliverable is a manifest for top-100 invisible brands.
Concentrating on the actionable cohort (excluding orphans):

- **TRUE_BRIDGE_ENCODED**: 86 brands. Action: BRIDGE. Read-side only.
  Folds into CP-5.
- **AUTHOR_NEW_BRIDGE (top-25 by AUM, hv2-counterparty discoverable)**:
  ~25 brands. Action: AUTHOR new `entity_relationships` rows. CP-4b.
- **AUTHOR_NEW_BRIDGE (top-26 to top-100 by AUM)**: ~75 brands. Action: as
  above. CP-4c.
- **BRAND_TO_FILER alias-pair merges (Vanguard eid=1→4375, PIMCO 30→2322,
  small aliases)**: ~5 brands. Action: re-point fund_holdings_v2. CP-4a.

Total CP-4 scope: ~100–110 entity-layer writes, all idempotent and
restart-safe via the staging→sync→promote workflow established in
`staging_workflow_live.md`.

---

## 11. Verification

```bash
# Read-only constraint on all helpers (only CREATE TEMP VIEW matches expected):
grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b' \
    scripts/oneoff/inst_eid_bridge_*.py
# 0 matches — no DDL/DML

grep -nE '\bCREATE\b' scripts/oneoff/inst_eid_bridge_*.py
# Only CREATE OR REPLACE TEMP VIEW lines (in-memory views over read_only connection)

# Helpers (worktree-relative):
ls scripts/oneoff/inst_eid_bridge_*.py
# 4 helpers: phase0_baseline, phase1_inventory, phase1b_eid_level,
#            phase2_relationships, phase4_deepdives
```

Output artifacts:
- `data/working/inst_eid_bridge/eid_inventory.csv` (1,225 rows, full inventory)
- `data/working/inst_eid_bridge/relationship_types.csv` (8,003 pair rows)
- `data/working/inst_eid_bridge/orphan_top50.csv`
- `data/working/inst_eid_bridge/deepdive_Vanguard.csv`
- `data/working/inst_eid_bridge/deepdive_PIMCO.csv`
- `data/working/inst_eid_bridge/deepdive_BlackRock.csv`
- `data/working/inst_eid_bridge/mode_a_brand_no_filer.csv`
- `data/working/inst_eid_bridge/mode_c_filer_no_brand.csv`
- `data/working/inst_eid_bridge/mode_b_eid_mismatch.csv` (empty — see §3)
- `data/working/inst_eid_bridge/mode_b_prime_eid_pairs.csv` (empty — see §1)
- `docs/findings/_inst_eid_bridge_phase0.json` (Phase 0 baseline)
- `docs/findings/_inst_eid_bridge_phase1.json` (Phase 1 CIK-keyed)
- `docs/findings/_inst_eid_bridge_phase1b.json` (Phase 1b eid-level)
- `docs/findings/_inst_eid_bridge_phase2.json` (Phase 2/3)
- `docs/findings/_inst_eid_bridge_phase4.json` (Phase 4 deep-dives)

## 12. Cross-references

- **PR #252** (`institution_scoping`) — original surfacing of brand-vs-filer
  eid duplication. This investigation refines and quantifies the cohort.
- **PR #251** (`cef-asa-flip-and-relabel`) — precedent for the
  BRAND_TO_FILER alias-pair shape (Calamos ASA flip, 350 rows).
- **`docs/findings/institution_scoping.md`** — full PR #252 decision doc
  containing the 1,225/$27.8T headline.
- ROADMAP item: `inst-eid-bridge-fix` (CP-4 in PR #252 sequencing). This
  doc is the CP-1 deliverable. CP-4 prompt awaits chat resolution of
  Open Questions #1–#3.
- **`docs/decisions/inst_eid_bridge_decisions.md`** — chat decisions
  locking the seven §9 open questions and CP-4 split (added 2026-05-02
  post-PR #254 review).
