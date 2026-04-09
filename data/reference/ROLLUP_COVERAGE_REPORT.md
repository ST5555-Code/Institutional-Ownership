# Entity Rollup Coverage Report

_Generated: April 8, 2026_
_Source: 13f_staging.duckdb Entity MDM (Phase 3.5 complete)_

---

## Summary

| Metric | Count |
|--------|-------|
| Total entities | 20,205 |
| Rolls up to parent | 9,258 (45.8%) |
| Self-rollup (independent) | 10,947 (54.2%) |
| Unique parent entities | 708 |
| Total relationships | 13,541 |

---

## Rollup Coverage by Entity Type

### 13F Filers (CIK-based)

| Status | Count | % |
|--------|-------|---|
| Total 13F entities | 11,135 | 100% |
| Rolls up to parent | 972 | 8.7% |
| Self-rollup | 10,163 | 91.3% |

**Impact:** 10,163 13F filers are treated as independent institutions. Their holdings are attributed to themselves, not consolidated under a parent. This is correct for most (standalone corporates, banks, pension funds) but fragments analysis for firms that ARE subsidiaries but file independently.

**AUM at risk of fragmentation:**
- Self-rollup 13F filers hold **$26.2 trillion** (38.9% of total $67.3T)
- Top self-rollup filers include sovereign wealth funds (Norges Bank $935B), independent managers (Dodge & Cox $185B), and market makers (Jane Street $662B) — these are correctly independent

### N-PORT Fund Series

| Status | Count | % |
|--------|-------|---|
| Total N-PORT entities | 8,547 | 100% |
| Rolls up to parent | 8,269 | 96.7% |
| Self-rollup (orphan) | 278 | 3.3% |

**Impact:** 920 fund series don't roll up to their adviser/sponsor. In shareholder analysis, these funds appear as independent holders rather than under their managing firm.

**Examples of N-PORT orphans:**
- Invesco Global Allocation Fund — should roll up to Invesco
- Eaton Vance Emerging Markets — should roll up to Morgan Stanley (via Eaton Vance)
- Fidelity Founders Fund — should roll up to FMR LLC

### ADV Advisers (CRD-based)

| Status | Count | % |
|--------|-------|---|
| Total CRD entities | 7,157 | 100% |
| Rolls up to parent | 667 | 9.3% |
| Self-rollup | 6,490 | 90.7% |

**Impact:** Most CRD entities are legitimately independent RIAs. The 667 that roll up were wired via ADV Schedule A parsing + manual review. The 6,490 self-rollup include 1,827 explicitly confirmed independent firms.

---

## Top Self-Rollup 13F Filers (Correctly Independent)

These are the largest self-rollup filers. Most are correctly independent — sovereign wealth funds, pension funds, independent managers, and market makers.

| CIK | Name | 13F Holdings |
|-----|------|-------------|
| 0001374170 | Norges Bank (Norway sovereign) | $934.8B |
| 0001422849 | Capital World Investors | $735.3B |
| 0001595888 | Jane Street Group | $662.1B |
| 0001562230 | Capital International Investors | $638.0B |
| 0000820027 | Ameriprise Financial | $442.5B |
| 0001330387 | Amundi | $368.0B |
| 0001403438 | LPL Financial | $366.2B |
| 0001407543 | Envestnet Asset Management | $337.1B |
| 0000720005 | Raymond James Financial | $321.4B |
| 0000912938 | MFS (Mass Financial Services) | $310.1B |
| 0000850529 | Fisher Investments | $293.0B |
| 0000927971 | Bank of Montreal | $288.7B |
| 0001067983 | Berkshire Hathaway | $274.2B |
| 0000200217 | Dodge & Cox | $185.3B |
| 0000919079 | CalPERS | $174.9B |
| 0001582202 | Swiss National Bank | $168.0B |
| 0001283718 | Canada Pension Plan | $149.5B |
| 0001608046 | National Pension Service (Korea) | $135.1B |

**Note:** Capital World Investors and Capital International Investors are both Capital Group entities — they file separately by design (different investment committees). This is not a rollup gap.

---

## Relationship Types

| Type | Count | Drives Rollup? |
|------|-------|---------------|
| fund_sponsor | 8,141 | Yes — fund series → sponsor/adviser |
| sub_adviser | 3,442 | No — informational only |
| wholly_owned | 1,046 | Yes — subsidiary → parent |
| mutual_structure | 157 | No — Vanguard-style collective ownership |
| parent_brand | 77 | Yes — 25-50% ownership |

---

## Rollup Rules Applied

| Rule | Count | Source |
|------|-------|--------|
| self | 11,485 | Default for all entities |
| fund_sponsor | 8,141 | N-CEN filing data |
| wholly_owned | 397 | ADV Schedule A + manual |
| orphan_scan | 174 | Name-similarity consolidation |
| parent_brand | 8 | ADV Schedule A (25-50% ownership) |

---

## What Happens to Non-Rollup Entities

### In a Registry/Shareholder Analysis

1. **Self-rollup entities appear as independent institutions** — their holdings are attributed to themselves
2. **No consolidation** — Morgan Stanley Investment Management ($165B) appears separately from Morgan Stanley ($500B+) if not wired
3. **Top holder lists fragment** — makes ownership look more diversified than reality
4. **Voting power understated** — combined voting power of a parent + subsidiaries not visible

### Current Mitigations

1. **ADV ownership wiring** — 1,095 relationships from Schedule A parsing
2. **Orphan consolidation** — 174 subsidiaries linked by name similarity + firm identity verification
3. **Manual review** — 99 relationships from external enrichment file
4. **N-CEN fund sponsor** — 8,141 fund series → adviser relationships from structured filings
5. **Validated independent** — 1,827 firms explicitly confirmed as having no corporate parent

### Remaining Gaps

1. **920 N-PORT orphan series** — fund series without adviser linkage (10.8%)
2. **~200 large self-rollup 13F filers** — some may be subsidiaries not yet identified
3. **International parents** — foreign holding companies not in SEC filings (Amundi, Sumitomo, Mitsubishi UFJ)
4. **Market makers** — Jane Street, IMC, Optiver, Simplex file large 13F positions but are trading firms, not traditional asset managers

---

## Phase 4 Implications

Before migrating to entity_id FK in holdings tables:
1. ~~Wire the 920 N-PORT orphan series~~ Done (858 wired, 99.3% coverage)
2. Verify top 50 self-rollup 13F filers are correctly independent
3. Add international parent entities for foreign subsidiaries filing US 13F
4. The $26.2T in self-rollup holdings is mostly correct — sovereign funds, pension funds, and independent managers should NOT be consolidated
