# Phase 5 Findings — CEF Scoping: N-CSR Parser Feasibility (READ-ONLY)

**Worktree:** `naughty-bell-727cea`
**Date:** 2026-05-02
**Status:** READ-ONLY research. No DB writes. Helper script: `scripts/oneoff/cef_scoping_phase_5_ncsr_sample.py` (verified zero writes).
**Scope reframe:** Phase 4 confirmed CEFs are in scope for N-PORT (Rule 30b1-9). Modern (2019+) CEF holdings ride the existing N-PORT loader. **Phase 5 only addresses pre-2019 historical backfill feasibility** — informational, not load-bearing.

---

## 1. Sample Selection

| CIK | Name | Vintage targeted | Vintage actually fetched | Accession | Filed | Period |
|---|---|---|---|---|---|---|
| 0000002230 | Adams Diversified Equity Fund (ADX) | latest | 2026 (FY 2025-12-31) | 0001104659-26-018080 | 2026-02-20 | 2025-12-31 |
| 0001230869 | ASA Gold & Precious Metals Ltd | latest | 2026 (FY 2025-11-30) | 0001398344-26-002448 | 2026-02-06 | 2025-11-30 |
| 0001912938 | First Trust Private Assets Fund | latest | 2025 (FY 2025-03-31) | 0001104659-25-057883 | 2025-06-09 | 2025-03-31 |
| 0001166258 | Pioneer High Income Fund | 2020-2023 | 2023 | 0001193125-23-160638 | 2023-06-05 | n/a |
| 0000810943 | High Income Securities Fund | pre-2020 | 2019 | 0000898531-19-000532 | 2019-10-31 | 2019-08-31 |

All 5 fetches succeeded. No substitutions needed beyond the requested vintage windows.

---

## 2. Per-Filing Analysis

### 2.1 ADX — Adams Diversified Equity (2026 / 2024+ vintage)

- 14 attachments. Primary doc `tm261680d1_ncsr.htm` (890 KB).
- `Filing.obj()` → `None` — no structured holdings extractor.
- 34 HTML tables, largest 41 rows × 8 cols. "Schedule of Investments" keyword present.
- No PDF attachments. No XBRL exhibits (older filer hadn't yet adopted IXBRL when this filing went out).
- **Format:** HTML-table parseable. **Effort:** MEDIUM.

### 2.2 ASA Gold & Precious Metals (2026 / 2024+ vintage)

- 20 attachments. Primary doc is Inline-XBRL HTML (`fp0097502-1_ncsrixbrl.htm`, 677 KB).
- Full IXBRL exhibit set: `.xsd / _def.xml / _lab.xml / _pre.xml`.
- `Filing.obj()` → `XBRL` document object (recognizes IXBRL but does **not** expose a `holdings()` DataFrame — returns metadata/cover-page entity facts).
- 109 HTML tables, largest 59 rows × 33 cols. "Schedule of Investments" present.
- **Format:** Inline-XBRL HTML; SoI itself is HTML tables (not XBRL-tagged at line-item level for the schedule of investments — XBRL covers the financial statement facts).
- **Effort:** MEDIUM (HTML scrape) — the IXBRL wrapper does not help for holdings.

### 2.3 First Trust Private Assets (2025 / 2024+ vintage)

- 14 attachments. Primary doc `tm2515361d2_ncsr.htm` (1.05 MB).
- `Filing.obj()` → `None`.
- 75 HTML tables, largest 42 rows × 17 cols. SoI keyword present.
- No PDFs, no IXBRL exhibits.
- **Format:** HTML-table parseable. **Effort:** MEDIUM.

### 2.4 Pioneer High Income Fund (2023 / mid vintage)

- 20 attachments. Primary doc 2.17 MB — largest in the sample.
- IXBRL exhibits present (early adopter or larger-filer compliance).
- `Filing.obj()` → `XBRL` (cover-page facts only, again no holdings DataFrame).
- **304 HTML tables**, largest 45 rows × 7 cols.
- High table count likely reflects multi-fund umbrella or rich SoI detail (high-yield credit holdings).
- **Format:** HTML-table parseable but high noise (304 tables → need heuristics to find the SoI table among financial statement tables, performance summaries, expense examples, fee tables).
- **Effort:** MEDIUM-to-HARD (table identification harder).

### 2.5 High Income Securities Fund (2019 / pre-2020 vintage)

- Just 4 attachments — minimal filing. Primary doc 642 KB.
- `Filing.obj()` → `None`. No XBRL exhibits.
- 47 HTML tables, largest 51 rows × 6 cols. SoI keyword present.
- No PDFs.
- **Format:** Plain HTML — actually the cleanest of the five for scraping (low table count, simple structure).
- **Effort:** MEDIUM.

---

## 3. Coverage Matrix

| CIK | Vintage | Format | edgartools structured? | HTML-table parseable? | Needs OCR? | Holdings rows visible | Effort |
|---|---|---|---|---|---|---|---|
| 0000002230 (ADX) | 2024+ | HTML | No (`obj()`=None) | Yes | No | ~41 | MEDIUM |
| 0001230869 (ASA) | 2024+ | IXBRL HTML | Partial (`obj()`=XBRL cover only, no holdings) | Yes | No | ~59 | MEDIUM |
| 0001912938 (FT Private Assets) | 2024+ | HTML | No (`obj()`=None) | Yes | No | ~42 | MEDIUM |
| 0001166258 (Pioneer HI) | 2023 | IXBRL HTML | Partial (XBRL cover only) | Yes (304 tables, noisy) | No | ~45 | MEDIUM-HARD |
| 0000810943 (HISF) | 2019 | HTML | No | Yes | No | ~51 | MEDIUM |

**Tier breakdown:** TRIVIAL=0, MEDIUM=4, MEDIUM-HARD=1, HARD=0, UNPARSEABLE=0. Zero PDF/OCR exposure across the sample.

Key empirical findings:
- `edgartools` does **not** expose a `holdings()` accessor for N-CSR. `Filing.obj()` returns either `None` or an `XBRL` cover-page object — never a Schedule of Investments DataFrame.
- IXBRL wrapping (post-2024 tailored shareholder report rule) tags **financial statement** facts, not SoI line items. It does not help holdings extraction.
- All 5 samples have HTML SoI tables with reasonable row counts (~40–60). Custom BeautifulSoup + table-classification scrape is feasible.
- No PDF attachments in any sample → OCR exposure for this vintage spread appears low. (A larger sweep would be needed to confirm pre-2019 PDF prevalence — small Goldstein-managed funds like HISF use HTML; some boutique pre-2010 filers may use PDF/scanned exhibits.)

---

## 4. Recommendation: **D — Skip historical N-CSR backfill entirely**

### Rationale

1. **Net new modern data = 0.** N-PORT (already loaded by `fetch_nport_v2.py` / `load_13f_v2.py` since Apr 15 promotion, see memory `project_session_apr15_dera_promote.md`) covers all 458 active CEF N-CSR filers from 2019-Q1 forward at monthly granularity. N-CSR provides **no incremental modern-era coverage**.
2. **Historical depth value is low for the workstream's purpose.** The pipeline supports flow-analysis / conviction tabs that work on quarterly aggregations. Pre-2019 history adds 2 points/year per CEF (semiannual N-CSR cadence), one-quarter the resolution of N-PORT. Most analyst use-cases for institutional-ownership flow analysis run on 4–12 quarter lookbacks where N-PORT is sufficient.
3. **Effort is real, not trivial.** All 5 samples are MEDIUM (custom HTML scrape with SoI table classification). One is MEDIUM-HARD (Pioneer, 304 tables). Building a robust extractor across 458 CEFs, with the heterogeneous filer/printer formats characteristic of N-CSR, is a multi-week effort with ongoing maintenance burden as filers change templates.
4. **Phase 4 already descoped this workstream.** The original ROADMAP framing (NSAR/N-CSR as primary CEF holdings source) was wrong. Now that N-PORT is the canonical path, N-CSR is supplemental and historical only — and the historical leg has weak ROI.
5. **edgartools provides no shortcut.** Zero TRIVIAL filings in the sample. Even IXBRL filings require HTML scraping for the SoI; the IXBRL wrapper covers the financial statements only.

**If the user later decides historical backfill is required** (e.g., for a 5-year+ flow study spanning the N-PORT boundary), Path B is the fallback:

> **B — edgartools + HTML-table fallback.** Use `edgartools` for filing discovery + attachment listing + primary HTML retrieval, then BeautifulSoup-based SoI table identification with heuristics ("Schedule of Investments" header proximity, column signature: Description / Shares / Value).

Path C (OCR) is **not recommended** based on this sample (no PDFs observed across pre-2020 to 2024+); a broader sweep would be prudent before committing.

---

## 5. Effort Estimate — Recommended Path D (Skip)

**Engineering effort: 0 hours.** Close out the historical-backfill question; rely on N-PORT going forward. Add a one-line note to `docs/PROCESS_RULES.md` or roadmap that pre-2019 CEF holdings are out of scope.

### Counterfactual: Effort if Path B were authorized (458 CEFs)

Scope assumptions:
- 458 active CEF N-CSR filers (per Phase 4 cross-ref).
- Pre-2019 history: avg ~10 years × 2 N-CSRs/year = ~20 filings/CEF → **~9,160 filings** to fetch.
- Throughput at 5 req/sec EDGAR ceiling, mostly parse-bound: **~6–8 hours fetch** + **~1–2 days parse/classify** in parallel workers.
- Parser maintenance burden: HTML templates vary by filer/printer (RR Donnelley, Toppan Merrill, Workiva, in-house) and across vintages. Expect ~15–25% initial extraction failure rate requiring per-filer overrides — similar to the v1.4 CUSIP retries (memory `project_session_apr14_cusip_v14.md`).

| Work item | Estimate |
|---|---|
| Filing-history sweep + accession enumeration (458 CIKs × N-CSR/N-CSRS) | 2 days |
| Parser core: SoI table classifier + column inference + CUSIP/ticker resolution | 5–8 days |
| Per-filer override layer for the long tail of formatting variants | 5–10 days (incremental) |
| QA + entity/security MDM reconciliation against existing v1.4 securities table | 3–5 days |
| Schema additions (`fund_holdings_historical` shadow table, source-of-record column) | 1–2 days |
| **Total (one-time build)** | **~3–5 weeks** |
| **Ongoing maintenance** | low — dataset is frozen pre-2019 |

This estimate does **not** include OCR contingency. If pre-2019 PDF-only filings turn out to be common in the broader population (the sample's 5/5 HTML rate is suggestive but not conclusive), add another 1–2 weeks for a pdfplumber + manual review tier.

**Conclusion: Recommend D. Defer or kill. Re-open only if a specific user need for pre-2019 CEF holdings depth appears.**
