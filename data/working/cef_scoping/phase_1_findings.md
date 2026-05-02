# cef-scoping — Phase 1 Findings

**Date:** 2026-05-02
**Scope:** READ-ONLY research. No DB writes, no production module changes.
**Goal:** Size the closed-end-fund (CEF) attribution problem in `fund_holdings_v2`
before deciding the fix shape for the residual 446-row / $4.741B UNKNOWN cohort
(Adams ADX + ASA Gold), deferred from PR #247.

---

## 1. Methodology

### 1.1 CEF universe (proxy for "active CEF as of 2026")

- Tool: `edgartools` (`from edgar import get_filings, set_identity`).
- Identity: `serge.tismen@gmail.com` (per `CLAUDE.md`).
- Calls: `get_filings(form='N-2', year=Y)` and `get_filings(form='N-2/A', year=Y)`
  for `Y in 2020..2026`. Form N-2 is the SEC registration statement for closed-end
  funds (any CIK that has filed N-2 or its N-2/A amendment in the last ~6 years
  is a live CEF registrant).
- Per-CIK enrichment: most-recent `N-CSR` / `N-CSRS` certified shareholder report
  date (2020–2026 window) — confirms the CEF is operating, not just registered.
- Headers only — NO N-CSR body fetches in this phase (Phase 5 owns that, capped
  at 5 filings).
- Raw counts: 3,946 N-2 + N-2/A filings → **757 unique CIKs** registered or
  amended since 2020-01-01. 458 of them (60.5%) also have an N-CSR/N-CSRS in
  the same window — this is the "active operating CEF" core.

### 1.2 Validation spot-check (5 of 5 verified)

Random sample of 5 CIKs with active N-CSR (random_state=42):

| CIK | Registrant | External classification |
|-----|-----------|--------------------------|
| 1875084 | PGIM Private Real Estate Fund | Non-listed interval CEF (PGIM website) — ✓ |
| 917100  | India Fund, Inc. (IFN)        | NYSE-listed CEF (cefconnect / abrdn) — ✓ |
| 1957121 | Felicitas Private Markets Fund | Non-listed tender-offer CEF — ✓ |
| 1794287 | Angel Oak Dynamic Financial Strategies Income Term Trust | Listed term CEF (NYSE: DYFN, since liquidated 2022) — ✓ |
| 1566388 | DoubleLine Income Solutions Fund (DSL) | NYSE-listed CEF (cefconnect) — ✓ |

All 5 are bona fide CEF / interval-fund registrants — no false positives.
Universe size 757 is **within the spec window of ~500–800** (CEFA + cefconnect
list ~440 listed CEFs; the additional ~300 are interval funds, tender-offer
funds, BDCs, and recent registrations that haven't yet listed — N-2 captures
all four classes, which is correct for our "could appear in 13F" question).

### 1.3 Cross-reference query

`fund_holdings_v2` filtered to `is_latest = TRUE`. `fund_cik` is VARCHAR with
zero-padding to 10 digits (sample: `'0000908695'`); the query joins on both the
zero-padded and unpadded forms for safety. Tier classification:

- **Tier A** = any rows with `series_id = 'UNKNOWN'`
- **Tier B** = any rows with `series_id LIKE 'SYN_%'` AND no UNKNOWN
- **Tier C** = only canonical `series_id` (no SYN_, no UNKNOWN)
- **Tier D** = not in `fund_holdings_v2` at all

---

## 2. CEF Universe Size

**757 unique CIKs** with N-2 or N-2/A filed 2020-01-01 → 2026-05-02.
- 458 with N-CSR/N-CSRS in the window (active core).
- 299 N-2-only (recent registrations not yet reporting, or wound-down funds).
- Year distribution by most-recent N-2 filing: 2020:106 / 2021:81 / 2022:89 / 2023:69 / 2024:121 / 2025:170 / 2026:121.
  Heavy 2025-2026 weight reflects new BDC + interval-fund launches.

Edge inclusions:
- Some BDCs (e.g. MSC Income Fund, CIK 1535778) appear because they filed N-2
  for unit-class registration. These rarely show up in 13F holdings.
- Wound-down CEFs (e.g. Angel Oak DYFN) are still in the universe via their
  pre-liquidation N-2 amendment.

Edge exclusions:
- Legacy CEFs registered pre-2020 and never amended via N-2/A in our window
  are NOT in the universe. **This is the source of the gap surfaced below.**

---

## 3. Tier Breakdown

Universe = 757 CIKs. Cross-referenced against `fund_holdings_v2 is_latest=TRUE`.

| Tier | Definition | n CIKs | Rows | AUM (USD) |
|------|------------|--------|------|-----------|
| A | UNKNOWN-bearing | **0** ← see §4 | 0 | $0 |
| B | SYN_-only (no UNKNOWN) | **436** | 815,183 | **$625.94B** |
| C | Canonical series_id only | **0** | 0 | $0 |
| D | Not in `fund_holdings_v2` | **321** | 0 | $0 |

### Tier B sample (top 5 by AUM)

| CIK | Registrant | rows_syn | AUM |
|-----|-----------|----------|-----|
| 1735964 | Cliffwater Corporate Lending Fund | 14,948 | $91.71B |
| 1447247 | Partners Group Private Equity Fund, LLC | 3,365 | $34.52B |
| 1510599 | PIMCO Dynamic Income Fund | 3,921 | $15.07B |
| 1678124 | CION Ares Diversified Credit Fund | 5,014 | $14.94B |
| 1500233 | Ironwood Institutional Multi-Strategy Fund LLC | 81 | $12.26B |

### Tier C sample

Empty — no CEF in our universe is loaded with a canonical (non-`SYN_`,
non-`UNKNOWN`) series_id. This is consistent with `entity_current` series-ID
semantics: CEFs receive synthetic SYN_ identifiers because EDGAR rarely
emits real series_ids for non-mutual-fund N-2 registrants.

### Tier D sample

321 CEFs with N-2 in our window but zero rows in `fund_holdings_v2`. Sample:

| CIK | Registrant |
|-----|-----------|
| 1535778 | MSC Income Fund, Inc. (BDC) |
| 1804308 | Stone Ridge Longevity Risk Premium Fixed Income Trust 72F |
| 2095816 | VanEck CLO Opportunities Fund (recent launch) |
| 2051024 | Champion Fund (recent launch) |
| 2049810 | Virtus Global Credit Opportunities Fund (recent launch) |

These are mostly recent-launch BDCs / interval funds that haven't filed an
N-PORT yet, plus single-investor private vehicles. Expected behaviour.

---

## 4. Tier A — the residual cohort (independently verified)

Tier A is empty against the 757-CIK N-2 universe **but `fund_holdings_v2` does
contain UNKNOWN rows.** Direct query confirms the universe of UNKNOWN-bearing
CIKs in prod is exactly the two seeds carried over from PR #247:

| fund_cik | fund_name | unknown_rows | unknown_AUM | mig015_UNKNOWN prefix | other backfill | EDGAR accession | SYN companion rows | SYN companion AUM | has_SYN_companion |
|----------|-----------|--------------|-------------|----------------------|----------------|-----------------|--------------------|-------------------|-------------------|
| 0000002230 | ADAMS DIVERSIFIED EQUITY FUND, INC. (ADX) | 96 | $2.989B | **96 (100%)** | 0 | 0 | 291 | $8.826B | **YES** |
| 0001230869 | ASA Gold & Precious Metals Ltd (ASA) | 350 | $1.752B | **350 (100%)** | 0 | 0 | 143 | $1.094B | **YES** |
| **TOTAL** | | **446** | **$4.741B** | **446 (100%)** | 0 | 0 | 434 | $9.920B | |

Why these two were absent from the N-2 universe: both are legacy listed CEFs
that registered well before 2020 (Adams since 1929; ASA Gold since 1958) and
have not filed an N-2/A amendment in the 2020–2026 window. This is the
**Tier A gap reason** — the N-2 universe captures registrants but misses old
CEFs that are still active under their original registration. An N-CSR-only
re-cut (the alternate active proxy) would catch them but is out of scope for
this phase.

Both Tier A CIKs already have `SYN_*` companions (i.e., the loader correctly
created synthetic series for known periods on these funds). The UNKNOWN rows
are exclusively period-only `BACKFILL_MIG015_UNKNOWN_<period>` accessions —
the migration-015 leftover pattern.

---

## 5. Implications — verdict: **(a) migration-015 cleanup**

This is **not a loader-architecture gap, not a live loader bug, and not a
universe-wide CEF attribution problem.** Evidence:

1. **Scope is exactly 2 CIKs / 446 rows / $4.741B** — matches the PR #247
   deferred cohort byte-for-byte. No other UNKNOWN-bearing CEFs exist in prod.
2. **100% of UNKNOWN rows carry the `BACKFILL_MIG015_UNKNOWN_*` accession
   prefix** — these are migration-015 historical artefacts where CIK could not
   be resolved at backfill time, not live-loader failures.
3. **Both seeds have SYN_* companions** with real EDGAR accession numbers
   (291 + 143 = 434 SYN_ rows totalling $9.92B). The loader handles these CIKs
   correctly today; the UNKNOWN rows are legacy residue.
4. **Tier B (436 CEFs / $625.94B) is healthy** — every active CEF that loads
   into `fund_holdings_v2` does so via the SYN_ namespace cleanly. The
   architecture is working.
5. **Tier C is empty** — confirms there is no second attribution path producing
   silent canonical-series-ID writes for CEFs.

**Recommended fix shape:**
- Targeted SCD-style flip on the 2 UNKNOWN seeds (close `is_latest=FALSE` on
  the 446 rows; promote the 434 existing SYN_ companion rows where periods
  overlap; for periods with no companion, optionally synthesize one via a
  one-shot backfill keyed off the fund_cik that's already known).
- This is materially the same operation already executed for the BRANCH 1 / 6
  pairs in PR #247 (commit `0296107`, 2,738 rows / $5.28B), just on the
  remaining 2 stragglers that BRANCH 2 deferred because their SYN_ companion
  rows didn't fully cover the UNKNOWN periods.
- **No loader change required.** No new architecture. No N-CSR body parsing.
- Out-of-scope-but-flag: the N-2 universe missed the 2 active legacy CEFs
  that we already know about. If you want a defensive guard for *future*
  migration-015-style residue on legacy CEFs, the right monitor is "any
  fund_cik with `BACKFILL_MIG015_UNKNOWN_*` accession on `is_latest=TRUE`" —
  zero rows is the green target. That belongs in the gates, not in this PR.

---

## 6. Helper scripts

- `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/scripts/oneoff/cef_scoping_phase_1_1_universe.py`
  — builds `data/working/cef_scoping/cef_universe.csv` (757 rows).
- `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/scripts/oneoff/cef_scoping_phase_1_2_crossref.py`
  — builds `data/working/cef_scoping/tiers_summary.csv` and the Tier A
  worksheet. Both scripts confirmed read-only via grep:
  `grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b'`
  returns only pandas `.drop(columns=...)` / `.sort_values(...)` matches —
  zero SQL writes.

## 7. Output files

- `data/working/cef_scoping/cef_universe.csv` — 757 CEF CIKs
- `data/working/cef_scoping/tiers_summary.csv` — Tier B/D row+AUM totals
- `data/working/cef_scoping/tier_a_cohort.csv` — 2 verified UNKNOWN-bearing CIKs
- `data/working/cef_scoping/phase_1_findings.md` — this file
