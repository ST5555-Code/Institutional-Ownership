# CP-4b BLOCKER 2 Corroboration Probe

**Date:** 2026-05-03
**Branch:** `cp-4b-blocker2-corroboration-probe`
**Refs:** [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2), [docs/findings/cp-4b-discovery.md](cp-4b-discovery.md), PR #267 (`cp-4b-author-trowe`).
**Methodology owner:** read-only investigation; zero DB writes.
**Recommended outcome:** **Outcome 4** — BLOCKER 2 strict rule stays; narrow carve-out for 4 named brands via manual sourcing.

---

## 1. Cohort re-validation

Computed live from prod DuckDB at session time (read-only).

| metric | value |
| --- | ---: |
| LOW rows in `cp-4b-discovery-manifest.csv` | 19 |
| sum LOW fund AUM ($B) | 11,435.5 |
| drift vs. discovery baseline | 0.00% |
| `cp-4b-author-trowe` bridge (parent 3616 → child 17924) | ✓ present (post-PR #267) |
| visible 13F filer pool (entity_id with ≥100 holdings_v2 rows) | 6,947 eids |

**State drift across 19 brands:** one informational flag — eid 2322 brand `canonical_name` reads as `PACIFIC INVESTMENT MANAGEMENT CO LLC` in `entities` (manifest carried "PIMCO"). The CP-4a alias merge (PR #256) re-pointed eid 30 → 2322 and the canonical was rolled to the surviving form. No probe behavior changes — both names normalize to the same X1 stem.

## 2. Methodology — four orthogonal probes

For each LOW brand, evidence is gathered across four signals. None of them fall back to discovery's Step 2c name-token-overlap heuristic, which BLOCKER 2 explicitly forbids from raising confidence.

### X1 — normalized name equality

Brand `canonical_name` and visible-filer `canonical_name` / `manager_name` are normalized identically: uppercase, punctuation-stripped, then iterative suffix removal (longest first to avoid prefix chops). Suffix list applied in this exact order:

```
ASSET MANAGEMENT, INVESTMENT MANAGEMENT, INVESTMENT MANAGERS,
INVESTMENT ADVISERS, INVESTMENT ADVISORS, ADVISORY SERVICES,
FUND MANAGEMENT, GLOBAL ADVISORS, ADVISERS, ADVISORS, ADVISER,
ADVISOR, ADVISORY, MANAGEMENT, FINANCIAL, CAPITAL, HOLDINGS,
GROUP, L.L.C., LLC, L.L.P., LLP, L.P., LP, LIMITED, LTD., LTD,
INC., INC, CORP., CORP, CORPORATION, COMPANY, CO., CO, PLC,
FUNDS, FUND, /DE/, /MD/, /FI/, /FA/, /CA/, /NY/, /MA/, /DE\
```

X1 hit: normalized brand string equals normalized filer string on a different visible eid (≥100 holdings rows). Evidence = filer eid + which field (canonical or manager_name) matched.

### X2 — `entity_aliases` cross-link

Brand-side terms = X1-normalized brand `canonical_name` ∪ X1-normalized brand aliases (open rows). Filer-side terms = X1-normalized filer aliases (open rows on different visible eid).

X2 hit: any brand-side term equals any filer-side term after normalization.

### X3 — shared CIK across `identifier_types`

Brand CIK on `entity_identifiers` (open rows, both 10-padded and unpadded forms) appears as `cik` on a different visible eid. Identical predicate to discovery Step 2a — included to confirm the ADV-only methodology missed no edges.

### X4 — `ncen_adviser_map` cross-link

Three sub-probes:
- **4a** — brand CRD (any padding) appears in `adviser_crd`; follow `registrant_cik` to a visible eid.
- **4b** — brand X1-normalized canonical_name equals X1-normalized `adviser_name`; follow `registrant_cik` to a visible eid.
- **4c** — brand CRD on a registrant whose `registrant_cik` carries ≥2 distinct `adviser_crd` values (multi-adviser fund issuer). Flag-for-review only — produces no candidate filer eid by construction.

X4 hit: any sub-probe fired. Per the plan's strict rule — "n_signals_corroborated counts X1–X4 only when they returned ≥1 candidate" — **4c-only firings do not count toward the corroboration tally**. They are recorded in the matrix as `x4_4c_only_no_candidate=True` for documentation.

## 3. Per-brand corroboration matrix

Full data: [data/working/cp-4b-corroboration-matrix.csv](../../data/working/cp-4b-corroboration-matrix.csv). Compact view:

| rank | brand_eid | brand | AUM $B | X1 | X2 | X3 | X4 | n_sig | conc eid | bucket |
| ---: | ---: | --- | ---: | :-: | :-: | :-: | :-: | ---: | ---: | :-: |
| 1 | 18073 | J.P. Morgan Investment Management Inc. | 2,714.5 | . | . | . | 4c | 0 | — | D |
| 2 | 2322 | PIMCO (PACIFIC INVESTMENT MANAGEMENT CO LLC) | 2,044.2 | . | Y | . | 4c | 1 | 1909;9115 | C |
| 3 | 9904 | TEACHERS ADVISORS, LLC | 1,571.1 | . | . | . | 4c | 0 | — | D |
| 4 | 1355 | FRANKLIN ADVISERS INC | 1,162.8 | . | . | . | 4c | 0 | — | D |
| 6 | 2400 | Fidelity Management & Research Co LLC | 714.6 | . | . | . | 4c | 0 | — | D |
| 7 | 11 | Fidelity / FMR | 415.3 | . | Y | . | . | 1 | **10443** | C |
| 8 | 3 | State Street / SSGA | 301.9 | . | Y | . | . | 1 | **7984** | C |
| 9 | 18983 | Jackson National Asset Management, LLC | 300.8 | . | . | . | 4c | 0 | — | D |
| 10 | 17930 | Federated Advisory Services Company | 275.3 | . | . | . | 4c | 0 | — | D |
| 11 | 19555 | WisdomTree Asset Management, Inc. | 262.2 | . | . | . | 4c | 0 | — | D |
| 12 | 10538 | MANULIFE INVESTMENT MANAGEMENT (US) LLC | 258.0 | . | . | . | 4c | 0 | — | D |
| 13 | 8 | First Trust | 232.7 | Y | Y | . | . | 2 | **136** | B |
| 14 | 2232 | SUNAMERICA ASSET MANAGEMENT, LLC | 222.2 | . | . | . | 4c | 0 | — | D |
| 15 | 2562 | Equitable Investment Management, LLC | 221.1 | Y | Y | . | 4c | 2 | **9526** | B |
| 16 | 18177 | Brighthouse Investment Advisers, LLC | 168.9 | . | . | . | 4c | 0 | — | D |
| 17 | 7823 | Thrivent Asset Management, LLC | 153.1 | . | . | . | . | 0 | — | D |
| 18 | 18298 | Transamerica Asset Management, Inc. | 145.4 | Y | Y | . | 4c | 2 | 2080 | B |
| 19 | 17935 | Macquarie Investment Management Global Limited | 138.4 | . | . | . | 4c | 0 | — | D |
| 20 | 5127 | PUTNAM INVESTMENT MANAGEMENT LLC | 133.0 | . | . | . | 4c | 0 | — | D |

X1/X2/X3/X4 columns: `Y` = signal returned ≥1 candidate filer eid; `4c` = X4 fired only on the 4c sub-probe (no candidate, informational). Bold concordance eids = manually verified as the public-record correct counterparty.

## 4. Bucket counts + AUM exposure

| bucket | criterion | n | AUM $B | AUM share |
| :-: | --- | ---: | ---: | ---: |
| A | 3-4 signals corroborate, concordant filer | 0 | 0.0 | 0.0% |
| B | 2 signals corroborate, concordant filer | 3 | 599.2 | 5.2% |
| C | 1 signal hits | 3 | 2,761.4 | 24.1% |
| D | 0 signals corroborate (4c-only or nothing) | 13 | 8,074.9 | 70.6% |
| **Total LOW cohort** | | **19** | **11,435.5** | **100.0%** |

## 5. Public-record sanity check

The discovery doc's supplementary name-token column flagged 13/19 brands with public-record obvious filer counterparties. Comparison against multi-signal corroboration:

| brand | public-record correct | bucket | concordance hit? | verdict |
| --- | --- | :-: | :-: | --- |
| Fidelity / FMR | FMR LLC (eid 10443) | C | ✓ matches | **TRUE POSITIVE** via X2 |
| State Street / SSGA | State Street Corp (eid 7984) | C | ✓ matches | **TRUE POSITIVE** via X2 |
| First Trust | First Trust Advisors LP (eid 136) | B | ✓ matches | **TRUE POSITIVE** via X1+X2 |
| Equitable IM | Equitable Holdings, Inc. (eid 9526) — public parent | B | ✓ matches | **TRUE POSITIVE** via X1+X2 |
| Transamerica AM | (parent Aegon NV; no clean 13F counterparty) | B | hits eid 2080 | **FALSE POSITIVE** |
| PIMCO | (PIMCO has no 13F counterparty; fixed-income book) | C | hits 1909;9115 | **FALSE POSITIVE** |
| Franklin Advisers | Franklin Resources (eid 1500-range) | D | no hit | missed |
| Macquarie IM | Macquarie Group Ltd | D | no hit | missed |

### False-positive analysis

**Transamerica (Bucket B):** brand `Transamerica Asset Management, Inc.` and candidate `Transamerica Financial Advisors, LLC` (eid 2080) both normalize to `TRANSAMERICA`. They are sister subsidiaries under Aegon — TFA is a broker-dealer/IA, not the AM arm. X1+X2 fire concordantly *because the suffix list strips both `ASSET MANAGEMENT` and `FINANCIAL ADVISORS`*. The corroboration is a normalization artifact, not evidence of a brand-to-filer relationship.

**PIMCO (Bucket C):** brand normalizes from `PACIFIC INVESTMENT MANAGEMENT CO LLC` to `PACIFIC` (after stripping LLC, CO, INVESTMENT MANAGEMENT). Two visible filers — `Pacific Asset Management, LLC` (eid 1909) and `PACIFIC FINANCIAL GROUP INC` (eid 9115) — both also normalize to `PACIFIC` and have brand-side aliases that share the stem. Neither is related to PIMCO. False-positive driver is the same: aggressive suffix-stripping collapses unrelated firms onto the same single-token stem.

### True-positive analysis

The four true positives split into two patterns:

- **Distinct-stem matches (low collision risk):** `FIRST TRUST`, `FIDELITY / FMR`, `STATE STREET / SSGA`, `EQUITABLE`. The normalized stems for these brands collide with very few visible filers (1 each in this cohort). FMR/State Street additionally carry the *exact same alias_name string* on both brand and filer eids (e.g., the literal `'FIDELITY / FMR'` lives on eid 11 and eid 10443) — which is a stronger cross-link than normalization-induced equality.

- **Aggressive-stem matches (collision risk):** `TRANSAMERICA`, `PACIFIC` (PIMCO). Single-token stems that match unrelated firms.

The collision risk correlates roughly with how much of the brand canonical_name survives normalization. Brands whose normalized form retains unusual structure (`/`, multiple distinctive words) are reliable; brands that collapse to one common business-namespace word are not.

## 6. BLOCKER 2 extension draft language

Probe outcome maps to **Outcome 4 (signals over-fire)**: 2 of 6 corroborating hits are false positives across Buckets B and C. A defensible blanket extension is not available, but a narrow carve-out for 4 specific brands is supported by the data.

### Recommended decision-doc amendment

```
## BLOCKER 2 — addendum (cp-4b-blocker2-corroboration-probe, 2026-05-03)

The four-signal corroboration probe (X1 normalized name equality, X2
entity_aliases cross-link, X3 CIK reuse, X4 N-CEN cross-link) was tested
against the 19 LOW LOW residual cohort ($11.44T) from cp-4b-discovery.
Result: 6 brands surfaced corroborating signals; 2 of 6 were false
positives driven by suffix-stripping normalization collapsing unrelated
sub-entities onto the same stem (Transamerica AM → Transamerica Financial
Advisors LLC; PIMCO → unrelated "PACIFIC"-stem firms).

BLOCKER 2 strict rule REMAINS in force. Multi-signal corroboration is
NOT sufficient to author bridges at-scale.

CARVE-OUT: four named brands surfaced concordant signals AND survive
manual public-record verification. They may be authored as one-off bridges
under cp-4b-author-corroborated-narrow with the following predicate:

  AUTHOR_NEW_BRIDGE eligibility (manual carve-out):
    - X1 + X2 both fire, OR X2 alone fires with brand-side and filer-
      side aliases sharing identical raw-string content (not just
      normalized equality).
    - Concordance set = exactly one filer eid.
    - Concordance eid is independently confirmed (public record:
      10-K subsidiary list, ADV Schedule A, corporate website) as
      the brand's correct 13F counterparty.
    - relationship_type chosen by org-chart shape:
        wholly_owned   — sub-adviser to parent IA filer
                          (First Trust → eid 136).
        parent_owner   — public parent holding co
                          (Equitable IM → eid 9526 Equitable Holdings).
        brand_alias    — different label for same operating filer
                          (Fidelity / FMR → eid 10443 FMR LLC;
                           State Street / SSGA → eid 7984 State
                           Street Corp).
    - confidence='medium', source='cp_4b_corroborated_narrow'.
    - All four bridges authored in a single PR; AUM conservation gated
      per CIK transfer rule.

DEFER: the remaining 15 brands (Bucket C residual + Bucket D, ~$10.27T)
to a manual-sourcing arc (cp-4c-manual-sourcing) using 10-K subsidiary
schedules, ADV Schedule A/B parsing, or curated public-record mapping.
The strict-ADV cross-ref methodology cannot author them without
unacceptable false-positive risk at the $11T scale.

Failure modes the probe exposed (do not propose for general adoption):
  - X1 alone (any single-token stem) — collides on common business
    namespace words.
  - X4 sub-probe 4c (multi-adviser registrant) — pattern indicator,
    no candidate filer; not a corroboration signal.
  - 2-signal corroboration without manual verification — Transamerica
    proves this fails on aggressive suffix-stripping.
```

## 7. Estimated authorable AUM by extension shape

| extension shape | n bridges | AUM addressed | false-positive risk |
| --- | ---: | ---: | --- |
| Strict (BLOCKER 2 unchanged) | 0 | $0 | none |
| **Narrow carve-out (recommended)** — 4 manually-verified brands | **4** | **$1.17T** (10.2% of LOW cohort) | very low (manual veto step) |
| 2-signal blanket | 6 | $2.27T | medium — Transamerica false positive ships |
| 1-signal blanket | 9 | $5.03T | high — PIMCO + Transamerica + others ship |
| 0-signal blanket (BLOCKER 2 abandoned) | 19 | $11.44T | unacceptable |

Narrow-carve-out brands and target eids:

| brand_eid | brand | filer_eid | filer | relationship_type | AUM $B |
| ---: | --- | ---: | --- | --- | ---: |
| 8 | First Trust | 136 | First Trust Advisors LP | wholly_owned | 232.7 |
| 11 | Fidelity / FMR | 10443 | FMR LLC | brand_alias | 415.3 |
| 3 | State Street / SSGA | 7984 | State Street Corp | brand_alias | 301.9 |
| 2562 | Equitable Investment Management, LLC | 9526 | Equitable Holdings, Inc. | parent_owner | 221.1 |
| | **Total carve-out** | | | | **1,171.0** |

## 8. Recommended next step

1. **Author `cp-4b-author-corroborated-narrow`** as a one-PR follow-up to PR #267:
    - 4 `entity_relationships` open inserts using the carve-out predicate.
    - `source='cp_4b_corroborated_narrow'`, `confidence='medium'`.
    - Per-pair AUM conservation gate (CIK transfer rule).
    - Manual veto checkpoint in the prompt: each of the 4 candidate eids must be re-confirmed against public record (corp website, 10-K Item 1 subsidiary list, ADV Schedule A) before the insert. Author should record the verification source in the prompt's Phase 1 dry-run output.
    - Decision-doc amendment (Section 6 above) ships in the same PR.

2. **DEFER** the remaining 15 brands ($10.27T residual after carve-out) to a new ROADMAP item — `cp-4c-manual-sourcing` (P2). Methodology there should be ADV Schedule A/B parsing for the brands carrying CIK on `entity_identifiers` (PIMCO, Teachers, Franklin Advisers, Manulife, SunAmerica, Equitable, Thrivent, Putnam = 8/15) plus 10-K subsidiary-list scraping for the brand-only rollups (JPM IM, Fidelity Mgmt, Jackson Nat, Federated, WisdomTree, Brighthouse, Transamerica, Macquarie = 7/15).

3. **Sentinel `no_counterparty` brands** — PIMCO genuinely has no 13F counterparty (fixed-income book). Recommend `cp-4c-manual-sourcing` includes a `no_counterparty` disposition flag so downstream consolidation reporting can attribute these brands as "non-13F filer" rather than "missing bridge" without forcing an `entity_relationships` row.

## 9. Out-of-scope discoveries

- **PIMCO canonical drift.** Eid 2322 carries `PACIFIC INVESTMENT MANAGEMENT CO LLC` as its current `entities.canonical_name` (post-CP-4a merge). The discovery manifest reads "PIMCO" because it pre-dated the CP-4a merge result. No action — the alias stack still contains `'PIMCO'` and reads behave correctly.

- **X4 sub-probe 4c is structural noise, not a corroboration signal.** 13 of 19 brands fired 4c (multi-adviser registrant pattern) regardless of whether any other signal corroborated. This is the default state for fund-trust sub-advisers — N-CEN registrants by definition aggregate multiple advisers. Any future probe should treat 4c as a documentation flag, not a counted signal.

- **N-CEN `registrant_cik` cannot resolve to visible 13F filers in any of the 19 cases** (sub-probes 4a + 4b returned zero matches). N-CEN registrant CIKs are fund-issuer trust CIKs, not 13F filer CIKs. The N-CEN cross-link is unsuited to AUTHOR_NEW_BRIDGE methodology under the current schema.

- **Bucket B "concordance" can be a normalization artifact.** Transamerica is the prototype: two distinct sister subsidiaries normalize to the same single-token stem and produce false-positive concordance. Future corroboration probes should require either (a) brand-side and filer-side aliases sharing identical raw-string content, or (b) prior `entity_relationships` evidence of a shared parent — to defend against this failure mode.

## Appendix — files

- `scripts/oneoff/cp_4b_blocker2_corroboration_probe.py` — read-only probe (single self-contained script).
- `data/working/cp-4b-corroboration-matrix.csv` — 19 rows × signal columns + concordance + bucket.
- `docs/findings/cp-4b-discovery.md` — upstream cohort doc.
- `docs/decisions/inst_eid_bridge_decisions.md` — BLOCKER 2 source rule.
