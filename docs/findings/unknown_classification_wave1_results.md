# Unknown Classification — Wave 1 Results

**Date:** 2026-05-03
**Branch:** `unknown-classification-wave-1` (worktree `sleepy-wright-49f441`)
**Per:** D4 decision + `docs/findings/unknown-classification-discovery.md` §5.1+§6
**Manifest:** [data/working/unknown-classification-wave1-manifest.csv](../../data/working/unknown-classification-wave1-manifest.csv) — 133 rows
**Pre-flight backup:** `data/backups/13f_backup_20260503_072956`

---

## 1. Cohort drift

| Metric | Value |
|---|---|
| Open ECH `classification='unknown'` (pre-execute) | **3,852** |
| Discovery baseline (`unknown-classification-discovery.md` §1) | 3,852 |
| Drift | **0.00 %** |
| Drift gate (≤ 5 %) | PASS |

390 Tier A entities re-checked — all 390 still in the open unknown cohort.

---

## 2. Wave 1 candidates under refined keyword set v2

The original Wave-1 plan used a phrase-only ACTIVE keyword set. Phase 1
returned only 23 candidates — outside the [100, 250] gate. Chat issued
**refined keyword set v2** (2026-05-03):

- **Phrase-only ACTIVE:** `Income Fund`, `Income Trust`, `Closed-End`,
  `Closed End`, `CEF`, `Municipal`, `MuniYield`, `Interval Fund`,
  `BDC`, `Business Development`, `High Yield`, `High Income`,
  `Opportunity Fund`, `Opportunity Trust`, `Opportunity Inc`.
- **Qualified Trust:** right-anchored suffix
  (`Trust` / `Trust Inc` / `Trust Inc.` / `Trust, Inc.` /
  `Trust LLC` / `Trust LP` / `Trust L.P.`, with optional trailing
  punctuation) **AND** name does NOT contain `Bank | Bancorp | Trust Company`.
- **Qualified Private:** any of `Private Capital | Private Credit |
  Private Equity Fund | Private Markets | Private Lending |
  Private Income`.
- **Dropped:** bare `Opportunity`, bare `Trust`, bare `Private`,
  `Closed End` and `Interval` without suffix.
- **PASSIVE (unchanged):** `SPDR`, `iShares`, `Vanguard`, `ETF`,
  `Index`, `PowerShares`, `Direxion`, `ProShares`, `ProFund`,
  `WisdomTree`, `Innovator`.

Re-run lands at **133 candidates** — inside the gate.

---

## 3. Per-path counts

| Path | Source string | Count |
|---|---|---|
| `name_pattern_active` | `wave1_name_pattern_active` | **131** |
| `name_pattern_passive` | `wave1_name_pattern_passive` | **1** |
| `adv_strategy` | `wave1_adv_strategy` | **1** |
| **Total** | | **133** |

### Per-classification

| Classification | Count |
|---|---|
| `active` | 132 |
| `passive` | 1 |

### Per matched keyword (active path)

| Keyword | Hits |
|---|---|
| `Trust (right-anchored, ex-bank)` | 39 (31 + 5 + 3) |
| `Private Markets` | 24 |
| `Income Trust` | 23 |
| `Opportunity Fund` | 15 |
| `High Yield` | 10 |
| `Private Credit` | 9 |
| `MuniYield` | 7 |
| `High Income` | 3 |
| `Private Capital` | 1 |
| `ETF` (passive) | 1 |
| `active` (ADV strategy) | 1 |

### Conflicts dropped to Wave 4e

- Active name-pattern with `signal_D != active`: **0**
- Passive name-pattern with `signal_D != passive`: **0**

(All Tier A active-name candidates have NULL `signal_D_value`,
because Tier A path-3 entities — D-fallback only — already segment
as `recommended_wave=3` in the source CSV. Wave 1 captures path-1/2
entities exclusively.)

---

## 4. AUM exposure

| Bucket | Pre-execute | Post-execute |
|---|---|---|
| `unknown` cohort (count) | 3,852 | **3,719** |
| Wave 1 manifest (count) | — | 133 |
| Wave 1 institution AUM | — | $0.00 B |
| Wave 1 fund-rollup AUM | — | **$138.21 B** |

The institution-AUM bucket is $0 because every Wave-1 candidate is a
fund-typed entity (CEFs, registered fund vehicles, fund-of-funds);
they do not carry direct `holdings_v2` rows but feed `fund_holdings_v2`
under their parent rollup.

---

## 5. Tier A residual after Wave 1

| Tier | Count | Wave-1 exit | Residual |
|---|---|---|---|
| **A** | 390 | 133 | **257** |
| B | 509 | — | 509 |
| C | 2,953 | — | 2,953 |

The 257 Tier A residual decomposes as:

- **199** D4-fallback (`manager_type` only) → **Wave 2** scope
  (deferred to next PR per plan).
- **58** name-pattern entities that fell out under v2 — routed to
  **Wave 4b** review per chat instruction step 7. Includes:
  - Trust banks excluded by the `Bank|Bancorp|Trust Company` rule
    (Boston Trust Walden, Wilmington Trust Investment Advisors).
  - Adviser-suffix LP forms (`First Trust Advisors L.P.`).
  - "Private Limited" corporate forms (`Quantum Advisors Private Limited`).
  - Bare `Opportunity` / `Closed End` / `Interval` matches without
    a qualifying suffix.

---

## 6. Spot-check (5 random reclassifications)

All five show the canonical SCD pattern: prior `unknown` row closed at
2026-05-03, new classification row open with sentinel `9999-12-31`.

| eid | canonical_name | new | source | confidence |
|---|---|---|---|---|
| 26821 | VOYA GLOBAL EQUITY DIVIDEND & PREMIUM OPPORTUNITY FUND | active | wave1_name_pattern_active | high |
| 26904 | ROYCE GLOBAL TRUST, INC. | active | wave1_name_pattern_active | high |
| 26695 | BlackRock MuniYield Quality Fund, Inc. | active | wave1_name_pattern_active | high |
| 26744 | Gabelli Utility Trust | active | wave1_name_pattern_active | high |
| 27140 | Felicitas Private Markets Fund | active | wave1_name_pattern_active | high |

### Top 10 by combined AUM (manifest)

| AUM (B) | eid | name | path | matched keyword |
|---|---|---|---|---|
| 13.25 | 18157 | Segall Bryant and Hamill LLC | adv_strategy | active |
| 5.19 | 26773 | PIMCO Corporate & Income Opportunity Fund | name_pattern_active | Opportunity Fund |
| 5.08 | 27004 | John Hancock GA Mortgage Trust | name_pattern_active | Trust (Trust) |
| 4.85 | 27178 | Franklin Lexington Private Markets Fund | name_pattern_active | Private Markets |
| 4.17 | 26622 | Gabelli Equity Trust Inc | name_pattern_active | Trust (Trust Inc) |
| 4.02 | 27051 | NB Private Markets Access Fund LLC | name_pattern_active | Private Markets |
| 3.07 | 27136 | JPMorgan Private Markets Fund | name_pattern_active | Private Markets |
| 3.04 | 26695 | BlackRock MuniYield Quality Fund, Inc. | name_pattern_active | MuniYield |
| 3.00 | 26956 | BlackRock Science & Technology Trust | name_pattern_active | Trust (Trust) |
| 2.92 | 26769 | Skybridge Opportunity Fund | name_pattern_active | Opportunity Fund |

---

## 7. Discovered edge cases / surprises

1. **Original tightened set (pre-v2) was over-aggressive** — only 23
   candidates vs. plan-expected 100–250. STOP gate triggered at
   Phase 1 as designed; chat issued v2 calibration before any DB
   writes occurred. This validates the gate mechanism.
2. **All Tier A active-name candidates have NULL `signal_D_value`** —
   path-1 (active name) and path-3 (D-fallback) are disjoint by
   construction in the Phase 5 tier script (a name-pattern hit short-
   circuits before the D-fallback branch). Result: no conflicts to drop.
3. **`Income Trust` is a high-volume v2 add (23 hits)** — covers
   common BlackRock / Nuveen / Gabelli CEF naming. Was not in the
   original tightened set but was added in v2 alongside the
   right-anchored Trust rule.
4. **Hedge fund LPs flagged as `active` by `Opportunity Fund`** —
   `RPD Opportunity Fund LP`, `Malta Opportunity Fund LP`, etc. The
   binary `active`/`passive` split treats hedge funds as `active`,
   which is the correct downstream behavior; the `hedge_fund` sub-class
   is captured by `holdings_v2.manager_type` if/when the entity carries
   13F filings.
5. **Symlink workaround for npm build** — worktree has no
   `node_modules`; symlink to parent's `web/react-app/node_modules`
   was created and removed cleanly post-build (no commit footprint).

---

## 8. Validation summary

| Check | Result |
|---|---|
| Phase 1 cohort drift gate (≤ 5 %) | PASS (0.00 %) |
| Phase 1 candidate range gate [100, 250] | PASS (133) |
| Phase 1 v2 spot-check (4 INCLUDED, 2 EXCLUDED) | PASS |
| Phase 3 entry gates (4 hard guards) | PASS |
| Phase 3 commit guards (count delta, post-state) | PASS |
| Cohort post-state count | 3,719 (= 3,852 − 133) ✓ |
| Manifest entities still in unknown cohort | 0 ✓ |
| New Wave 1 open rows | 133 ✓ |
| `pytest tests/` | 373 / 373 passed ✓ |
| `npm run build` | 0 errors ✓ |

---

## 9. Next

- **Wave 2** — D4-fallback `manager_type` propagation (199 Tier A
  path-3 entities). Separate PR per plan.
- **Wave 4b** — name-pattern review for the 58 v2 dropouts (trust
  banks, adviser LPs, "Private Limited" corporate forms,
  bare Opportunity).

Both follow-ups remain blockers for the admin-unresolved-firms-display
target of ≤ 500 visible residual.
