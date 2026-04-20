# Data Sources

This database aggregates institutional ownership and fund holdings data from public SEC filings and commercial market data. This page documents what is in each source, when it becomes available, and how current the data in this system is.

---

## Overview

| Source | Purpose | Cadence | Public lag | Table |
|---|---|---|---|---|
| 13F-HR | Long equity holdings by institutional managers ≥ $100M AUM | Quarterly | 45 days after quarter end | `holdings_v2` |
| N-PORT | Monthly portfolio holdings by registered investment companies | Monthly (public on rolling 60-day lag) | 60 days | `fund_holdings_v2` |
| 13D | Active-intent beneficial ownership > 5% | Event-driven | 10 days after material change | `beneficial_ownership_v2` |
| 13G | Passive beneficial ownership > 5% | Annual + event amendments | 45 days after year end | `beneficial_ownership_v2` |
| N-CEN | Annual adviser / sub-adviser identity for fund families | Annual, per fund fiscal year | 75 days after fiscal year end | `ncen_adviser_map` |
| ADV | Investment adviser business, AUM, ownership | Annual + prompt amendments | Varies | `adv_managers` |
| Market data | Prices, market cap, float, shares outstanding | Daily | None (real-time intraday) | `market_data` |

---

## 13F-HR — Institutional Holdings Reports

**Who files.** Institutional investment managers with investment discretion over $100 million or more in §13(f) securities (listed US stocks, certain ADRs, convertible debt, and options).

**What it contains.** Long positions in 13(f) securities as of the last day of the quarter. Shares, market value, investment discretion (sole / defined / other), voting authority, put/call indicator for options.

**What it does NOT contain.** Short positions. Non-US securities. Cash. Private investments. Positions below $200,000 or 10,000 shares.

**Cadence.** Quarterly. Report period ends on the last day of each calendar quarter.

**Filing deadline.** 45 days after quarter end:
- Q1 (Mar 31) → May 15
- Q2 (Jun 30) → August 14
- Q3 (Sep 30) → November 14
- Q4 (Dec 31) → February 14

**Amendments.** 13F-HR/A filings correct or restate a prior 13F-HR. Common in the first 90 days after the original. `holdings_v2` carries `accession_number` today (populated by `load_13f.py` post-rewrite, commit `a58c107`); the full amendment-history semantics (`is_latest` flag + per-amendment row retention) land with migration 009 per the Admin Refresh design doc §5 — currently pending.

**Our coverage (as of 2026-04-19).** Quarters 2025Q1 through 2025Q4 fully loaded. 12,270,984 rows in `holdings_v2` across approximately 12,000 filer CIKs. `data_freshness[holdings_v2].last_computed_at` = 2026-04-19. Q1 2026 loads on or after May 16, 2026.

**Known gaps.**
- Confidential treatment filings are excluded from the public dataset until the confidentiality order expires (typically 12 months).
- Sub-advisory relationships are not disclosed on 13F directly — we cross-reference with N-CEN adviser maps to identify sub-advised positions.

---

## N-PORT — Registered Investment Company Portfolio Holdings

**Who files.** Mutual funds, ETFs, closed-end funds, and other registered investment companies (Form N-PORT, replacing the older N-Q).

**What it contains.** Monthly portfolio holdings. Equities, fixed income, derivatives, FX, short positions, counterparty exposure. More detail than 13F — includes cost basis, maturity date, coupon, and fair value hierarchy.

**What it does NOT contain.** Holdings of private funds, business development companies filing separately, or separately managed accounts.

**Cadence.** Monthly. Filed within 30 days of month end.

**Public availability.** Only the last month of each quarter is made public, and only 60 days after the quarter closes. The first two months of each quarter remain confidential. Practical effect:
- March filings → public around May 31
- June filings → public around August 31
- September filings → public around November 30
- December filings → public around February 28

**Amendments.** N-PORT/A filings are common. Current system treats latest accession as authoritative via `delete_insert(series_id, report_month)`. Retrofit to `is_latest` flag is scheduled with migration 009 (design §5) — currently pending; `fund_holdings_v2` carries `loaded_at` today but not yet `accession_number` or `is_latest`.

**Our coverage.** ~14 million rows across ~14,000 fund series. Newest report_date February 2026 (March 2026 not yet available per the 60-day lag rule). DERA bulk quarterly ZIPs are the primary ingest path (`fetch_nport_v2.py`, commit `44bc98e`); per-accession XML used for monthly top-up.

**Known gaps.**
- Securities with `'N/A'` CUSIP (derivatives, FX, cash) account for ~13% of rows. Preserved as literal string for DERA parity.
- Synthetic `{cik}_{accession}` series_id fallback used for ~5% of filings that lack series_id in the SEC submission.

---

## 13D — Schedule 13D (Active Beneficial Ownership)

**Who files.** Any person or group acquiring beneficial ownership of more than 5% of a voting class of equity securities, with intent to influence control of the issuer.

**What it contains.** Identity of the beneficial owner, number of shares, percentage of class, source of funds, purpose of the transaction, material agreements, prior filings on the issuer.

**Cadence.** Event-driven. Initial 13D due within 10 days of crossing the 5% threshold.

**Amendments.** 13D/A filings required "promptly" (interpreted as within 10 days) upon any material change — additional purchases/sales of 1% or more, change in intent, or change in agreements.

**Our coverage.** ~52,000 filings across the coverage universe. `beneficial_ownership_v2` is the canonical table (carries `accession_number` + `loaded_at` today; `is_latest` retrofit pending with migration 009); 94.5% enriched with entity MDM rollups as of April 2026.

**Key use case.** Activist campaigns, hostile bidder disclosures, control-group formations.

---

## 13G — Schedule 13G (Passive Beneficial Ownership)

**Who files.** Qualified institutional investors (banks, insurance companies, registered investment companies, investment advisers, pension plans, etc.) and "exempt investors" who acquire more than 5% but have no intent to influence control.

**What it contains.** Simpler than 13D — ownership stake, class of securities, percentage of class. No statement of purpose or agreements.

**Cadence.**
- Institutions: annual filing within 45 days of year end for holdings as of December 31.
- Exempt investors: annual filing within 45 days of year end.
- Material changes (crossing 10%, or changes of 5% or more in position): amendments within 10 days.

**Amendments.** 13G/A filings filed in the same table as 13G; distinguished by form type.

**Our coverage.** Included in `beneficial_ownership_v2` alongside 13D. Combined v2 table with entity linkage.

**Key use case.** Large passive holder tracking — index funds, long-only mutual funds at concentration thresholds.

---

## N-CEN — Annual Census for Investment Companies

**Who files.** Registered investment companies (mutual funds, ETFs, closed-end funds).

**What it contains.** Annual census-style report. Fund identity, adviser and sub-adviser CRD numbers, service providers, directors, fees, legal proceedings, securities lending activity.

**Critical field for this system.** Adviser and sub-adviser identity with CRD numbers — enables entity resolution between the fund series reported on N-PORT and the investment adviser reported on ADV. Without N-CEN, Wellington's sub-advisory of Hartford / John Hancock funds cannot be cleanly attributed.

**Cadence.** Annual, within 75 days of fund fiscal year end. Fund fiscal years are staggered throughout the calendar year — N-CEN filings arrive continuously.

**Amendments.** N-CEN/A for corrections.

**Our coverage.** 9,363 adviser-series mappings across 978 advisers. Hardened with `--ciks` flag and idempotent inserts as of April 2026.

---

## Form ADV — Investment Adviser Registration

**Who files.** SEC-registered investment advisers (and state-registered advisers for some parts).

**What it contains.**
- Part 1A: firm identity, AUM, number of clients, types of clients, employees, affiliations, disciplinary history.
- Part 1A Schedules A, B, C, D: direct and indirect owners, related persons, specific affiliates.
- Part 2: narrative brochure describing services, fees, conflicts, and personnel (not structured data, PDF).

**Critical fields for this system.** Adviser CRD, legal and business names, AUM categories, ownership structure (Schedule A parent chain).

**Cadence.** Annual updating amendment within 90 days of the adviser's fiscal year end. Most advisers are calendar-year, so peak filing season is mid-March to March 31.

**Amendments.** Promptly filed on material changes (ownership, disciplinary events, AUM thresholds).

**Our coverage.** `adv_managers` table with CIK↔CRD mapping and LEI reference. Phase 3.5 ADV ownership resolver processes 3,585 CRDs with Schedule A/B parsing.

**Rewrite pending.** Current `fetch_adv.py` uses full DROP+CTAS and lacks dry-run gate. Rewrite to SourcePipeline pattern is tracked.

---

## Market Data

**Sources.** Yahoo Finance primary, SEC XBRL for shares outstanding history backfill.

**Fields.** Last price, market capitalization, enterprise value, shares outstanding, float shares, 52-week high/low, sector, industry.

**Cadence.** Daily end-of-day snapshot. Intraday quotes fetched on demand via separate endpoint (not persisted).

**Our coverage.** ~5,900 active tickers (CUSIP-anchored universe — tickers with positions in the most recent 13F quarter or N-PORT report month). The full Yahoo universe of 43,000+ tickers is not refreshed — only actively-held names.

**Stale threshold.** 3 days. Market data is considered stale if the last refresh is more than 3 calendar days old.

---

## How Data Flows Into This System

1. **Ingest.** A pipeline fetches source data from EDGAR (or Yahoo) into staging tables with an `ingestion_manifest` record.
2. **Validate.** Gates check schema conformance, entity resolution completeness, QC rules (percent ownership 0-100, share counts not row numbers, etc.).
3. **Promote.** Validated staging data is appended to the canonical L3 table (`holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`). Amendments handled via `is_latest` flag (13F) or accession-key upsert (13D/G) or `delete_insert` on report key (N-PORT).
4. **Enrich.** Secondary pipelines populate derived columns — entity rollups, ticker lookups, market value at quarter end, percent of float.
5. **Aggregate.** L4 tables (`summary_by_parent`, `summary_by_ticker`, `investor_flows`) are rebuilt from L3 on a deterministic schedule.

Pipeline freshness is tracked in the `data_freshness` table. The Admin tab surfaces this directly.

---

## Timeline at a Glance

```
Calendar                              Public availability
─────────                             ──────────────────────────
Q1 quarter end ─── Mar 31 ─────────── Source data period close
                         ↓
              +30 days   Apr 30 ───── N-PORT filed (confidential)
                         ↓
              +45 days   May 15 ───── 13F-HR filed and public
                         ↓
              +60 days   May 31 ───── N-PORT March public via DERA ZIP
                         ↓
              +75 days   Jun 15 ───── N-CEN (for March fiscal-year funds)
                         ↓
              +90 days   Jun 30 ───── ADV annual amendments (Dec fiscal)

13D and 13G: filed event-by-event, 10-day rule on material changes.
13G annual: due 45 days after December 31 → February 14.
Market data: refreshed daily, always current.
```

---

## Data Quality Notes

- **Amendment chain.** 13F and N-PORT amendments are common in the 60-90 days after original. When running point-in-time analysis, use `loaded_at` and `accession_number` to pin the view.
- **CUSIP resolution.** Approximately 132,000 CUSIPs are classified (canonical type, equity flag, ticker mapping). Unmappable CUSIPs (22,000) are flagged in `cusip_retry_queue` as `unmappable` — typically private securities, delisted names, or exotic derivatives.
- **Entity rollup.** Every fact row carries an `entity_id` resolved through the MDM, plus `rollup_entity_id` for operating-parent grouping. Two worldviews are maintained: EC (economic consolidation) and DM (discretionary management). The UI offers a toggle where relevant.
- **Missing parent data.** Approximately 1,500 fund series remain pending entity resolution as of April 2026. These positions are still loaded and queryable by CIK but do not roll up to a parent entity.

---

*Last updated: 2026-04-19 (status annotation pass; original content 2026-04-17). This document currently lives at `Plans/data_sources.md`; per design §9 + §12 phase 12, it will move to `docs/data_sources.md` when the Data Source UI tab ships. That move is currently pending.*
