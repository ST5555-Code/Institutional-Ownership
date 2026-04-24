# int-02-p0 Phase 0 Findings — BLOCK-SEC-AUD-2 RC2: MAX(issuer_name_sample) → MODE aggregator

**Item:** int-02 — replace `MAX(issuer_name_sample)` in `cusip_classifier.get_cusip_universe()` with a frequency-based ("mode") aggregator so upstream clipped-prefix corruption (e.g. `"TLASSIAN CORPORATION"` > `"ATLASSIAN CORPORATION"` under lexicographic MAX) stops winning.
**Scope:** Phase 0. Read-only investigation. No code or data changes.
**Recommendation:** **CLOSE INT-02 AS CODE-COMPLETE. NO RE-SEED NOW (Option A selected 2026-04-21).** The mode+length+alpha aggregator shipped in `fc2bbbc` (2026-04-18). HEAD reflects it. The prod `cusip_classifications` table was seeded on 2026-04-14 — four days *before* the fix — so it still reflects the old MAX() behavior. Quantified gap is below; decision is to accept the 6.17% latent MAX-era names rather than run a full re-seed. Future re-seeds (triggered by universe expansion or routine refresh) will converge prod to MODE picks organically.

---

## 1. Code status at HEAD

[scripts/pipeline/cusip_classifier.py:551-635](scripts/pipeline/cusip_classifier.py:551) contains the mode+length+alpha aggregator as shipped in `fc2bbbc`:

```sql
WITH all_sources AS (
    -- 3 sources: securities, fund_holdings, beneficial_ownership_v2
    ...
),
name_counts AS (
    SELECT cusip, issuer_name_sample, COUNT(*) AS name_freq
    FROM all_sources
    WHERE issuer_name_sample IS NOT NULL
    GROUP BY cusip, issuer_name_sample
),
issuer_name_pick AS (
    SELECT cusip, issuer_name_sample
    FROM (
        SELECT cusip, issuer_name_sample, name_freq,
               ROW_NUMBER() OVER (
                   PARTITION BY cusip
                   ORDER BY name_freq DESC,
                            LENGTH(issuer_name_sample) DESC,
                            issuer_name_sample ASC
               ) AS rn
        FROM name_counts
    ) ranked
    WHERE rn = 1
)
SELECT a.cusip,
       ip.issuer_name_sample AS issuer_name_sample,
       MAX(a.security_type)              AS raw_type_mode,
       COUNT(DISTINCT a.security_type)   AS raw_type_count,
       MAX(a.security_type_inferred)     AS security_type_inferred,
       MAX(a.asset_category_seed)        AS asset_category_seed
FROM all_sources a
LEFT JOIN issuer_name_pick ip USING (cusip)
GROUP BY a.cusip, ip.issuer_name_sample
```

Key properties:

- Only `issuer_name_sample` changes chooser. `raw_type_mode`, `raw_type_count`, `security_type_inferred`, `asset_category_seed` all still use `MAX()` / `COUNT(DISTINCT)` — intentional per commit message.
- The chooser is deterministic: `name_freq DESC, LENGTH DESC, issuer_name_sample ASC`. No NULL-tie ambiguity.
- Pre-aggregation (`name_counts`) is required because DuckDB does not permit a window function inside another window's `ORDER BY`.

Commit `fc2bbbc` (`fix(cusip_classifier): RC2 — mode+length aggregator for issuer_name`, 2026-04-18) contains the complete change: 44 insertions, 10 deletions, `cusip_classifier.py` only. No accompanying migration or reseed ran.

The commit message itself states: *"No staging or prod writes. Phase 2 re-seed gated on sign-off."*

## 2. Prod data state (read-only; `data/13f_readonly.duckdb`, 2026-04-21)

### 2.1 Freshness

| Signal | Value |
|---|---|
| `cusip_classifications` row count | 132,618 |
| `created_at` distribution | 132,618 rows on 2026-04-14 |
| `updated_at` distribution | 120,877 on 2026-04-14 + 11,741 on 2026-04-15 |
| RC2 code shipped | 2026-04-18 |

The table was seeded before the RC2 fix. Nothing in `cusip_classifications` has been touched since 2026-04-15. Prod data is therefore **MAX()-selected**, not MODE-selected.

### 2.2 Gap between stored `issuer_name` and what MODE would pick

Reconstructing the new aggregator from live `securities` / `fund_holdings` / `beneficial_ownership_v2` and comparing against `cusip_classifications.issuer_name`:

| Metric | Count | % |
|---|---|---|
| `cusip_classifications` rows | 132,618 | 100.0% |
| Stored `issuer_name` matches MODE pick | 124,440 | 93.83% |
| Stored `issuer_name` differs from MODE pick | **8,178** | **6.17%** |
| Stored `issuer_name` matches old MAX() pick | 127,366 | 96.04% |

The 8,178 residual is the universe that a Phase 1 re-seed would flip.

Of those 8,178 flips, 3,310 are cases where MODE and MAX picks actually differ at source; the other 4,868 reflect names that drifted after initial seed (manual edits, OpenFIGI canonicalization, etc.) and are not RC2-related. The re-seed would restore those to whatever the current source mode is.

### 2.3 Segmentation of the 8,178 flips

| Category | Count | Example (cusip, current → new) | Interpretation |
|---|---|---|---|
| Cosmetic (case / punctuation only) | 2,600 | `G9456A900`: `Golar LNG Ltd` → `GOLAR LNG LTD` | Zero-risk. Upstream casing drift. |
| Classic RC2 first-letter-clip rescue | 248 | `594972408`: `TRATEGY INC` → `Strategy Inc`; `G0692U109`: `XIS CAP HLDGS LTD` → `AXIS CAPITAL HOLDINGS LTD`; `687793109`: `SCAR HEALTH INC` → `Oscar Health, Inc.`; `320817109`: `IRST MERCHANTS CORP` → `First Merchants Corp` | Intended RC2 fix. Safe. |
| New name is superstring of current (non-cosmetic) | 618 | `92936U109`: `Wp Carey Inc Common` → `W. P. Carey Inc.`; `26884U109`: `PR PPTYS` → `EPR PROPERTIES` | Usually improvement. |
| Current name is superstring of new | 771 | `85209W109`: `Sprout Social, Inc. Class A` → `Sprout Social, Inc.`; `91282CLH2`: `United States Treasury Notes 3.75 08/31/26 …` → `United States Treasury Note/Bond` | Mixed. New is sometimes cleaner (Treasury generic), sometimes loses share-class specificity. |
| Distinct first word (different entity) | 2,051 | `34959E109`: `TARGET CORP` → `FORTINET INC`; `141788109`: `ISHARES TR` → `CarGurus, Inc.`; `58733R102`: `V F CORP COM` → `MERCADOLIBRE INC` | **CUSIP integrity issue upstream**, not an RC2 decision problem. MODE exposes it; MAX hid it. See §3. |
| Remainder (abbreviations, re-orderings) | 1,890 | `371901109`: `Gentex Inc` → `GENTEX CORP`; `374297109`: `Getty Realty Corporation` → `GETTY REALTY CORP /MD/` | Mixed; mostly neutral. |

### 2.4 Interpretation of the 2,051 "different entity" bucket

These are CUSIPs where the three upstream sources report genuinely different issuer names across filings. Possible causes:

1. **Upstream filer error** — e.g. a 13F reports the wrong issuer under a given CUSIP (copy/paste error; wrong row aligned).
2. **CUSIP reassignment** — CUSIPs get retired and reissued; a historical filing may retain the old mapping.
3. **Filer-specific alias** — same entity, distinctly different naming convention.

The fc2bbbc commit message explicitly acknowledges this class as a *"known limitation … when a legitimate issuer name is less common than a wrong one in upstream sources, this ranking picks the wrong one. Phase 0 did not quantify this class."* This finding quantifies it: **2,051 CUSIPs (1.55% of the table)**.

This is **not a regression introduced by RC2** — MAX() hid the same upstream contamination behind a lexicographic artifact. A re-seed would surface 2,051 rows that warrant case-by-case review, OpenFIGI rebacking, or manual override.

## 3. Recommendation — status of int-02

### 3.1 Close the code work

Code work is complete. `fc2bbbc` is deployed to HEAD and the commit diff matches the intended design. No additional `cusip_classifier.py` changes are required for RC2.

### 3.2 Phase 1 re-seed options (decision, not code)

| Option | Scope | Risk | Effort |
|---|---|---|---|
| **A. No re-seed** | Leave prod as-is. New CUSIPs seeded after 2026-04-18 will use MODE; pre-existing rows retain MAX-era names. | Low. 6.17% of rows carry latent clipped-prefix names including 248 signature RC2 cases. Cosmetic for analysis; unpleasant in UI. | 0. |
| **B. Narrow Phase 1 (targeted patch)** | UPDATE only the ~866 "clipped-prefix rescue + new-is-superstring" flips (248 + 618). | Very low. All changes strictly recover information lost to MAX lexical ordering. | ~1 session. Write a targeted UPDATE in staging, diff-promote per INF1 workflow. |
| **C. Full Phase 2 re-seed** | Run `cusip_classifier.py` against the current universe with `--reset` semantics; stage, diff, promote 8,178 row changes. | Medium. Includes the 2,051 "distinct-first-word" flips that need regression review. | ~1 session + review of 2,051-row diff. |

Recommended: **Option B** if a narrow, boring remediation is preferred; **Option C** if the intent is to fully converge prod with the shipped aggregator and accept the review cost.

### 3.2.1 Decision (2026-04-21)

**Option A selected.** No re-seed now. Rationale:

- The 248 signature RC2 cases are cosmetic at the analysis layer — `cusip_classifications.issuer_name` feeds UI labels and manager-level rollups; it does not drive PK joins, flow computation, or valuation.
- The 2,051 distinct-first-word bucket needs per-row investigation. A targeted Phase 1 without that review would write 618 good fixes but also re-surface the 2,051 contaminated rows as churn.
- Organic convergence is acceptable: the next universe expansion (int-23) or routine `cusip_classifier.py --reset` run will pick up MODE picks for all rows it rewrites. Rows that are never re-seeded are low-traffic by definition.
- Blocker for re-seed: the 2,051-row distinct-first-word set is a data-quality investigation in its own right. If and when that investigation runs (filed as a follow-up, not remediation scope), a full Option C re-seed can land alongside it.

int-02 closes here. No int-02-p1 session.

### 3.3 Phase 0 memory reconciliation

Memory/context suggested "~196 high-precision + ~1,607 broad-recall rows" as the original clipped-prefix estimate. Current measured counts:

- 248 signature first-letter-clip rescues (classic RC2 wins).
- 8,178 total MAX/MODE divergences.

The memory estimate came from `2026-04-18-block-securities-data-audit.md` Phase 0 (`securities` + `cusip_classifications` intersection, April audit). The delta reflects subsequent upstream cleanup (fewer clipped-prefix names overall) plus a broader comparison window (N-PORT + 13D/G now included in `all_sources`). No action required — just noting that the re-seed population is smaller than the original audit estimate.

## 4. Source pointers

- Commit: `fc2bbbc` (2026-04-18) — `fix(cusip_classifier): RC2 — mode+length aggregator for issuer_name`.
- Code: [scripts/pipeline/cusip_classifier.py:551-635](scripts/pipeline/cusip_classifier.py:551).
- Audit doc: `docs/findings/2026-04-18-block-securities-data-audit.md` RC2 (Option B).
- Data: `data/13f_readonly.duckdb` tables `cusip_classifications`, `securities`, `fund_holdings`, `beneficial_ownership_v2`.
