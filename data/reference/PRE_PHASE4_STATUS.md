# Pre-Phase 4 Item Status

_Updated: April 9, 2026_

**Process rules:** All Items 3-9 follow `docs/PROCESS_RULES.md` — incremental saves,
restart-safe, multi-source failover, error thresholds before proceeding.

## Item 1 — Validation Gates ✅ COMPLETE
- 0 FAILs, 8 PASS, 7 MANUAL (all documented)
- Thresholds updated in validate_entities.py
- Committed: 848ec04

## Item 2 — Filing Agent Names in beneficial_ownership ✅ COMPLETE
- All 14,870 filing agent rows resolved (100%)
- Pass 1: EFTS search-index API resolved 13,920 rows
- Pass 2: .hdr.sgml header download resolved remaining 950
- Overall: 60,135 / 60,135 = 100% name resolution
- Script: `scripts/resolve_bo_agents.py`
- beneficial_ownership_current rebuilt (24,737 rows)

## Item 3 — International Parent Entities ✅ COMPLETE
- 77 rows wired across 10 international groups (67 children + 10 parent alignments)
- Amundi ($368B, 14 entities), MUFG AM ($190B, 4), Sumitomo Trust ($183B, 4),
  Allianz AM ($99B, 10), Natixis IM ($28B, 5), Macquarie ($23B, 3), Nikko AM ($17B, 4),
  BNP Paribas AM (7), Daiwa (8), AXA IM (6)
- Banks, insurance, broker-dealers left independent per rollup policy
- DWS/Deutsche (18), Invesco (17), HSBC (16), UBS (16), Nomura (14) already wired

## Item 4 — Top 50 Self-Rollup Verification ✅ COMPLETE
- Capital Group: unwired 44 false matches, wired Capital World ($735B) + Capital International ($638B) → $1.9T consolidated
- Franklin Templeton: +ClearBridge ($125B) + 3 Franklin advisers → $533B
- Ameriprise: +Columbia Threadneedle + 5 subs → $443B
- MFS: main entity ($310B) + 4 intl subs wired → $310B consolidated
- BMO Financial: +9 subs including Bank of Montreal ($289B) → $289B
- PGIM: +Jennison ($167B) → $256B
- 1832 AM: +2 Scotia AM entities
- Confirmed independent: Jane Street, LPL, Envestnet, Fisher, Berkshire, CalPERS, FIL Ltd, etc.
- Deduplicated parent_bridge: 12,005 → 11,135 rows (870 duplicates removed)

## Item 5 — N15: Fidelity International Sub-Adviser Dedup ✅ COMPLETE (no changes needed)
- Verified: series-level dedup (GROUP BY series_id + MAX) in all 4 N-PORT rollup queries
- Verified: Geode exclusion active via SUBADVISER_EXCLUSIONS in config.py
- 174 shared series (HK:111, Japan:63) correctly deduped — not double-counted
- Remaining ~116% ratio is structural: N-PORT monthly MAX vs 13F quarter-end
- N15 investigation (already Done in ROADMAP) concluded: no further exclusions needed

## Item 6 — R1/R2/R3: 13D/G Data Quality Audit ✅ COMPLETE
- **R1 — pct_owned**: 13G null 4-5% (good), 13D null 96-98% (structural — cover page format).
  34 outliers >100% nullified. avg 13G/A corrected 3,880% → 8.61%.
- **R2 — filer matching**: 12.3% match to 13F parent_bridge. 87.7% unmatched is expected
  (~1,976 individuals, ~639 funds/trusts, ~32 law firms, ~5 filing agents).
- **R3 — amendments**: 8,227 duplicate rows removed (60,135 → 51,908). 0 remaining.
- **R7 — 13D re-parse**: 7,271 filings re-downloaded. pct_owned 96%→0.6% null. shares_owned 16.5%→0.3% null.
- **R7b — amendment backfill**: same-filer+ticker backfill for amendments without cover page.
- **R9 — HM Treasury**: 37 TR-1 format filings parsed for pct_owned.
- **R10 — filing agent resolution**: 5,128 agent/law-firm filer names resolved to actual owners.
- **Suspect shares QC**: 2,333 values failed QC (implied >100% or <0.01%), nulled and re-parsed.
- **Exit filings**: 1,117 rows with pct=0% marked shares_owned=0 (validated below-threshold exits).
- **13F cross-validation**: 159 shares values backfilled from 13F holdings.
- **Parser hardening** (all 3 scripts synced: `fetch_13dg.py`, `reparse_13d.py`, `reparse_all_nulls.py`):
  - `clean_text()`: em-dash `&#x2013;`/`&#x2014;`, hex entities, spaced digit fix (`2 2 . 7` → `22.7`)
  - pct: 12 patterns — `Percentage` variant, wide gap `\D{0,80}`, no-`%`-sign fallback, entity-prefix, TR-1
  - shares: 8 patterns — AGGREGATE→SHARED→SOLE order, footnote `(1)` stripping, QC gate `val==0 or val>=100`
- **Full rescan**: 928 suspect rows re-downloaded + re-parsed (implied >100%, pct=100% with tiny shares, shares/pct diverge >10x). 908 shares + 55 pct corrected. Pre-split/merger temporal mismatches (771) confirmed legitimate.
- **Manual fixes**: 3 duplicate filer+ticker+date pairs resolved (Baupost/FWONK, Aikawa/SBC, Abigail/HBB). Jana/THS pct=9.2%, MCVT x3 pct=11.1/10.5/10.5%, Mubadala/EDR shares=2,232,747 pct=0.7% (all from filing text). SMITH/TXMD 2.3B shares was dollar value → exit. 
- **Final**: 51,905 rows. pct_null=0, shares_null=1 (PGGM preferred, no outstanding), duplicates=0, range errors=0, inconsistencies=0. **DATA QUALITY: CLEAN.**

## Item 7 — Item 43: app.py Lint Debt ✅ COMPLETE
- flake8: 116 issues → 0 (E402 imports reorganized, F401 unused removed, F541 f-strings fixed, E127/E302/E303 formatting)
- bandit B608: 28 SQL injection warnings → 0 (all verified safe — config constants, not user input. `.bandit` config added)
- `setup.cfg` added: max-line-length=120, E501 per-file-ignore for app.py
- 17 bare `except Exception:` → `except Exception as e:` + `app.logger.debug()`
- Pre-commit path unblocked for Phase 4 app.py changes
- Remaining low-priority: B110 try-except-pass review, B603 subprocess allowlist, B104 bind restriction → roadmap Item 43b

## Item 8 — N21 TODOs: Investor Type Classification ✅ COMPLETE
- NULL manager_type: 787 (9.1%, $1.21T) → **0 (0%, $0)**
- **Manager-level**: 14 categories, 8,639 managers, $67.3T. Full category-by-category review:
  - passive 45 ($22.2T) — pure index/ETF providers. Pension/insurance removed to correct categories.
  - mixed 1,657 ($16.1T) — multi-line banks/asset managers
  - active 4,126 ($14.2T) — traditional stock pickers
  - wealth_management 500 ($4.5T) — RIA platforms, broker-dealers
  - quantitative 68 ($4.3T) — market makers, systematic (Jane Street, Citadel, Optiver, etc.)
  - hedge_fund 1,342 ($2.4T) — verified against known HF lists
  - pension_insurance 139 ($2.0T) — expanded from 29 by moving from passive/mixed
  - strategic 543 ($0.6T) — corporate treasuries, holding companies
  - SWF 17 ($0.3T) — sovereign funds (PIF, Mubadala, Temasek, AP-fonden, etc.)
  - endowment_foundation 61 ($0.3T) — universities, foundations (removed commercial trusts)
  - activist 31 ($0.1T) — expanded to 28+ per comprehensive industry list
  - PE 76 ($0.2T), VC 32 ($0.01T), multi_strategy 2
  - 177 LOW confidence >$10B entities manually reviewed and fixed
  - Remaining LOW/MEDIUM <$10B tracked in roadmap item 43c
- **Fund-level**: 5,717 series classified by S&P500 overlap + fund name keywords + 8-index correlation
  - passive 1,017 ($12.4T), active 4,892 ($10.3T), mixed 416 ($3.1T)
- **New tables**: fund_classification, index_proxies, fund_index_scores, fund_best_index
- **New columns**: holdings.classification_source, fund_holdings.fund_strategy, fund_holdings.best_index

## Item 9 — Final Pre-Phase 4 Validation ✅ COMPLETE
- ALL VALIDATION GATES PASS
- beneficial_ownership: 51,905 rows, pct_null=0, shares_null=1, duplicates=0, range errors=0, names=100% resolved
- holdings: 3,205,650 rows (latest quarter), 14 manager_type categories, 0 NULL, 8,639 managers, $67.3T
- parent_bridge: 11,135 rows, 0 duplicate CIKs
- fund_classification: 5,717 series, fund_holdings coverage 96.1%
- entity tables (staging): 20,205 entities, 13,715 relationships, 29,023 identifiers, 20,439 aliases
- beneficial_ownership_current rebuilt: 24,753 rows
- **READY FOR PHASE 4**
