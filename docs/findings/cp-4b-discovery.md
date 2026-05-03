# CP-4b Discovery — Top-20 AUTHOR_NEW_BRIDGE Manifest

**Date:** 2026-05-03
**Branch:** `cp-4b-discovery`
**Refs:** [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2), conv-25 BlackRock 5-way bridge (commit `24b00dd`).
**Methodology owner:** read-only investigation; no DB writes.

## 1. Re-validation snapshot (Phase 1)

Computed live from prod DuckDB at session time.

| metric | value |
| --- | ---: |
| invisible brands (fund_holdings_v2 dm_rollup with no holdings_v2 entity_id match) | **1,223** |
| invisible-brand fund AUM exposure | **$25.26T** |
| TRUE_BRIDGE_ENCODED | 110 brands / **$6.96T** |
| AUTHOR_NEW_BRIDGE | 1,113 brands / **$18.30T** |

Drift vs. conv-25 baseline (TRUE_BRIDGE_ENCODED 196 / unbridged ~$22.1T): the
ASA flip + relabel + cef-residual-cleanup PRs after 2026-04-23 reshaped the
cohort. Numbers above are authoritative as of HEAD `1a6e400`.

Sanity gates:
- `entity_relationships` open-row sentinel = `DATE '9999-12-31'` (16,320 rows). ✓
- `adv_managers` row count = 16,606 (>1000 threshold). ✓
- `entity_identifiers` PK = `(identifier_type, identifier_value, valid_from)`,
  `identifier_type` lowercase (`cik`, `crd`, `series_id`). ✓
- AUTHOR_NEW_BRIDGE n=1,113 within bounds (10..2000). ✓

## 2. Methodology — ADV-first per BLOCKER 2

For each top-20 brand, evidence is gathered in priority order:

- **Step 2a — direct CIK reuse.** Brand CIK (from `entity_identifiers`)
  appears on a *different* `entity_id` that is `holdings_v2`-visible.
  Strongest possible signal — same SEC reporter on two eids = mergeable.
- **Step 2b — CRD bridge.** Brand CRD on `entity_identifiers` →
  `adv_managers.crd_number` → `adv_managers.cik` → re-resolve via
  `entity_identifiers` → visible `entity_id`. Both 9-digit zero-padded
  and unpadded CRD forms tested. Also: brand CRD as `adviser_crd` in
  `ncen_adviser_map` → `registrant_cik` → visible eid.
- **Step 2c — name-token / alias match.** Set-overlap of normalized name
  tokens (stop-words removed) between brand canonical_name and visible
  13F manager_name. **Verification only** — never raises confidence
  per BLOCKER 2 (Calvert → "Stanley Capital Management" prototype was
  rejected because the name-only signal misfires on holding-co names
  containing "Morgan", "Franklin", "First", etc.).

Schema-driven adaptation: `adv_managers` in this DB does **not** carry
`parent_owner_crd` / `direct_owner_crd` / `control_owner_crd` columns.
The closest functional substitute is `ncen_adviser_map` (registrant_cik
↔ adviser_crd), but its `registrant_cik` is the fund-side trust/series
CIK rather than a 13F filer CIK. Result: N-CEN rarely promotes a brand
into a HIGH/MEDIUM bucket without an additional corroborating chain.

### Confidence rubric

| tier | criterion | next_action |
| --- | --- | --- |
| HIGH | Step 2a fires, OR Step 2b returns a single CRD chain to one visible eid | BRIDGE_READY |
| MEDIUM | Step 2b candidate exists but ambiguous (multiple chains / candidate eids) | MANUAL_VERIFY |
| LOW | no Step 2a/2b signal | MANUAL_PAIRING_REQUIRED |

Step 2c hits on a LOW row are recorded as `supplementary_name_match`
in the manifest but do **not** upgrade confidence.

## 3. Top-20 manifest

Full manifest at `data/working/cp-4b-discovery-manifest.csv`.

| rank | brand_eid | brand_canonical_name | brand_cik | fund AUM ($B) | paired_filer_eid | paired_filer_name | paired_cik | confidence | next_action |
| ---: | ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |
| 1 | 18073 | J.P. Morgan Investment Management Inc. | — | 2,714.5 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 2 | 2322 | PIMCO | 0001163368 | 2,044.2 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 3 | 9904 | TEACHERS ADVISORS, LLC | 0000939222 | 1,571.1 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 4 | 1355 | FRANKLIN ADVISERS INC | 0000898420 | 1,162.8 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 5 | 17924 | T. Rowe Price Associates | — | 1,105.5 | 3616 | T. Rowe Price | 0000080255 | **HIGH** | **BRIDGE_READY** |
| 6 | 2400 | Fidelity Management & Research Co LLC | 0000035368 | 714.6 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 7 | 11 | Fidelity / FMR | — | 415.3 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 8 | 3 | State Street / SSGA | — | 301.9 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 9 | 18983 | Jackson National Asset Management, LLC | — | 300.8 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 10 | 17930 | Federated Advisory Services Company | — | 275.3 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 11 | 19555 | WisdomTree Asset Management, Inc. | — | 262.2 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 12 | 10538 | MANULIFE INVESTMENT MANAGEMENT (US) LLC | 0001034182 | 258.0 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 13 | 8 | First Trust | — | 232.7 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 14 | 2232 | SUNAMERICA ASSET MANAGEMENT, LLC | 0000863926 | 222.2 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 15 | 2562 | Equitable Investment Management, LLC | 0001965856 | 221.1 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 16 | 18177 | Brighthouse Investment Advisers, LLC | — | 168.9 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 17 | 7823 | Thrivent Asset Management, LLC | 0001346952 | 153.1 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 18 | 18298 | Transamerica Asset Management, Inc. | — | 145.4 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 19 | 17935 | Macquarie Investment Management Global Limited | — | 138.4 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |
| 20 | 5127 | PUTNAM INVESTMENT MANAGEMENT LLC | 0000081273 | 133.0 | — | — | — | LOW | MANUAL_PAIRING_REQUIRED |

## 4. Per-pair pairing evidence

### Rank 5 — T. Rowe Price Associates (HIGH, BRIDGE_READY)

Brand eid 17924 has CRD `105496` on `entity_identifiers`. `adv_managers`
row for CRD `105496` shows firm `T. ROWE PRICE ASSOCIATES, INC.` with
CIK `80255`. Re-resolving CIK `0000080255` against `entity_identifiers`
returns eid **3616** ("T. Rowe Price"), which appears as a 13F filer in
`holdings_v2` (n=18,064 holdings rows). Single CRD chain, single visible
eid resolution, exact firm-name match — unambiguous. Bridge-ready.

### Rank 1 — J.P. Morgan Investment Management Inc. (LOW)

Brand eid 18073 has CRD `107038` on `entity_identifiers`, but no row
exists in `adv_managers` for CRD `107038` (under any padding form), and
no `cik` is recorded on the brand. `holdings_v2` shows JPMorgan's 13F
filer is "JPMorgan Chase & Co" eid 4433 (CIK `0000019617`, n=129,604) —
the publicly traded parent. The CRD-bridge methodology has no edge that
connects 18073 → 4433 because there is no `adv_managers` record for the
brand-side CRD. Manual pairing required: brand 18073 → filer 4433 is
the public-record correct pairing, but evidence must be authored
(e.g., from JPM's 10-K subsidiary list or ADV Schedule A of CIK 19617).

### Rank 2 — PIMCO (LOW)

Brand eid 2322 has CIK `0001163368` and CRD `104559`. `adv_managers`
row exists (CRD 104559, CIK 1163368, "PACIFIC INVESTMENT MANAGEMENT
COMPANY LLC") but the resolved CIK matches the brand itself — there is
no *different* visible eid sharing this CIK. PIMCO files essentially
zero 13F (its book is fixed-income); the only "Pacific Investment"-named
13F filer in `holdings_v2` is "Mountain Pacific Investment Advisers
LLC" (CIK 0001067324, eid 4377), which is unrelated. Manual pairing
required, but the realistic answer is "no 13F counterparty exists" —
PIMCO's $2T fund AUM is genuinely non-13F.

### Rank 3 — TEACHERS ADVISORS, LLC (LOW)

Brand eid 9904 has CIK `0000939222` (the CREF / TIAA-CREF Funds CIK
on the fund-issuer side) and CRD `107157`. `adv_managers` shows a row
but CIK `939222` resolves only to the brand itself. The TIAA umbrella
13F filer (typically CIK `0001020999` "TIAA Board of Overseers") is
not connected by ADV signal alone. Manual pairing required.

### Rank 4 — FRANKLIN ADVISERS INC (LOW)

Brand eid 1355 has CIK `0000898420` and CRD `104517`. No `adv_managers`
row matches CRD `104517` directly; no `entity_identifiers` re-resolution
fires. Public-record correct counterparty is "Franklin Resources Inc"
eid 1500-range (CIK `0000038777`, n=55,862 in holdings_v2 — the
publicly traded parent). Cannot be authored from ADV alone in the
current schema.

### Ranks 6–20 — same structural pattern

All remaining 15 LOW rows fall into one of three structural classes:

1. **Fund-issuer CIKs** (PIMCO, Franklin Advisers, SunAmerica, Equitable,
   Thrivent, Putnam, Manulife US): the brand CIK is the fund-issuer or
   subsidiary adviser CIK; the 13F is filed by the parent/holding co
   under a different CIK that does not appear on `entity_identifiers`
   for the brand eid.
2. **Brand-only rollups with no CIK** (JPM IM, T. Rowe, Fidelity FMR,
   State Street SSGA, Jackson National, Federated, WisdomTree, First
   Trust, Brighthouse, Transamerica, Macquarie): the brand has no CIK
   on `entity_identifiers` at all, so Step 2a is impossible. Only the
   single T. Rowe Price case has a working CRD-bridge through
   `adv_managers` because both the brand-CRD and the parent-CIK are
   resolvable to two distinct eids.
3. **No ADV signal of any kind**: WisdomTree (Rank 11) — the brand has
   CRD `139684` but no `adv_managers` row for that CRD, no parent
   relationship, no CIK alias on a visible eid.

The supplementary name-token column flags the public-record correct
counterparty in 13/19 LOW cases (Franklin → Franklin Resources Inc,
FMR → FMR LLC, State Street → State Street Corp, Macquarie → Macquarie
Group Ltd, etc.) but per BLOCKER 2 these are NOT auto-promoted to
authorable bridges.

## 5. Confidence-tier counts

| tier | n | fund AUM ($B) | fund AUM ($T) |
| --- | ---: | ---: | ---: |
| HIGH | 1 | 1,105.5 | 1.11 |
| MEDIUM | 0 | 0.0 | 0.00 |
| LOW | 19 | 11,435.5 | 11.44 |
| **Total top-20** | **20** | **12,541.0** | **12.54** |

## 6. AUM bridged if HIGH+MEDIUM ship

If `cp-4b-author-top20` ships only the HIGH+MEDIUM rows, **$1.11T of
fund AUM** would be bridged in this round (T. Rowe Price only).

The remaining $11.44T across 19 LOW rows requires either a different
methodology (parent-corp 13F-filer mapping per public-record subsidiary
relationships) or per-brand manual sourcing (e.g., 10-K subsidiary
schedules, ADV Schedule A/B parsing). It is **not** addressable by the
strict-ADV CP-4b methodology as scoped.

## 7. Open questions for chat decision

1. **Single-brand author PR or skip?** The HIGH cohort is just one row
   (T. Rowe Price). Worth a dedicated PR, or fold into the next
   broader CP-4b sweep where additional HIGH rows accumulate?

2. **Methodology for the LOW $11.44T cohort.** The supplementary
   name-token column already identifies likely counterparties for
   13/19 rows, all of which are public-record obvious (FMR LLC for
   Fidelity FMR, State Street Corp for State Street SSGA, etc.). Should
   we (a) accept the BLOCKER 2 constraint and defer these to a future
   manual-sourcing arc, or (b) loosen the rubric for cases where the
   brand canonical_name *equals* the visible filer's manager_name
   stripped of suffixes (e.g., "First Trust" brand vs. "First Trust
   Advisors LP" 13F filer where the parent_relationship_summary
   confirms a `wholly_owned` link)?

3. **N-CEN registrant_cik enrichment.** N-CEN rarely promoted a row
   here because `registrant_cik` is fund-issuer-side. Worth a separate
   read-only investigation to score `registrant_cik` → visible-13F-eid
   resolution rate? If high, this could become Step 2b' for sub-adviser
   bridges.

4. **PIMCO and Franklin Advisers are partially dead-ends.** Even with
   manual sourcing, PIMCO's fixed-income business genuinely has no 13F
   counterparty. If `cp-4b-author-top20` includes a "no_counterparty"
   sentinel disposition for these cases, downstream consolidation
   reporting can correctly attribute the AUM as "non-13F filer" rather
   than "missing bridge."

## 8. Recommended next step — `cp-4b-author-top20` prompt scope

Given the 1 HIGH / 19 LOW split, recommend `cp-4b-author-top20` be
**scoped down** rather than executed as a top-20 sweep:

- **`cp-4b-author-trowe`** (very narrow, single-brand): author the
  T. Rowe Price brand 17924 → filer 3616 bridge. Standard
  `entity_relationships` insert with `source='cp_4b_adv_crd_bridge'`,
  `confidence='high'`, `relationship_type='wholly_owned'` or similar.
  Sanity gate via `total_aum` parity (per CIK transfer rule from prior
  conv memory). Open as standalone PR.

- **`cp-4b-discovery-cohort-2`** (read-only investigation, before any
  further author PR): expand discovery to ranks 21–100 to see whether
  the strict-ADV methodology produces more HIGH rows further down the
  AUM curve, or whether the methodology continues to misfire on the
  fund-issuer-CIK + holding-co-13F structural pattern. If HIGH yield
  remains <10% we re-scope CP-4b before authoring further bridges.

- **DEFER** any LOW-row authoring until BLOCKER 2 is explicitly
  loosened in `inst_eid_bridge_decisions.md` with a stated trigger
  rule (e.g., name-equality + parent_relationship_summary corroboration).

## Appendix — files

- `data/working/cp-4b-top20-input.csv` — Phase 1 cohort top-20 input.
- `data/working/cp-4b-cohort-summary.csv` — Phase 1 cohort split.
- `data/working/cp-4b-discovery-manifest.csv` — Phase 2 manifest (this
  doc's primary deliverable, 20 rows).
- `scripts/oneoff/cp_4b_discovery_phase1_inventory.py` — read-only.
- `scripts/oneoff/cp_4b_discovery_phase2_pairing.py` — read-only.
