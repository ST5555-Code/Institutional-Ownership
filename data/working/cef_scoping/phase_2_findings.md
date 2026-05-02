# Phase 2 Findings — cef-scoping load-path classification

_Read-only investigation, 2026-05-02._
_Scope: 446 fund_holdings_v2 rows under series_id='UNKNOWN' (ADX 96, ASA 350) +
the 434 SYN_-keyed sibling rows (ADX 291, ASA 143)._

## TL;DR

**MIXED, lean BY_DESIGN. Confidence: HIGH.**

CEFs do file N-PORT (verified — all 4 sampled real EDGAR accessions are
NPORT-P or NPORT-P/A). The SYN_ rows are the correct, current-pipeline
artifact — written Apr 15 by the v2 N-PORT DERA load (commit `e868772`)
+ Apr 15 dera_synthetic_stabilize Tier 3 collapse. The UNKNOWN rows are
**residue from the legacy retired loader** `scripts/retired/fetch_nport.py`,
written Apr 3 (12 days before the v2 cutover landed CEF data with stable
SYN_ keys).

For ADX 2025-09 the two write paths produced **byte-identical duplicates**
(96 UNKNOWN rows + 96 SYN_ rows, all 96 CUSIPs share the same shares and
market_value). For ASA the two paths cover **non-overlapping report_months**
(UNKNOWN: 2024-11, 2025-02, 2025-08; SYN_: 2025-11) — so dropping the
UNKNOWN side would lose three full filing periods unless the v2 loader is
also backfilled.

Recommendation: **roll the ADX/ASA cleanup into the existing
`cef-attribution-path` workstream** (PR-2 fetch + PR-4 load), not a
separate fix. UNKNOWN rows are not loader misfires — they're stale data
from a retired loader that was correctly superseded by the v2 path on the
ETF/mutual-fund side but never got the equivalent SYN_ companions on
ADX/ASA's earlier periods.

## 1. Loader trace

### Migration 015 — sentinel only, not the row writer

`scripts/migrations/015_amendment_semantics.py:181-202` — adds three
columns (`accession_number`, `is_latest`, `backfill_quality`) and bulk
UPDATEs every existing fund_holdings_v2 row with synthetic accession
`'BACKFILL_MIG015_' || series_id || '_' || report_month`. Pure additive
UPDATE; does not write rows, does not dedupe rows, does not touch series_id.

For the 446 UNKNOWN rows, MIG015 produced accession
`BACKFILL_MIG015_UNKNOWN_<period>` (because the literal `series_id`
column value was already `'UNKNOWN'`). For the SYN_ rows it produced
`BACKFILL_MIG015_SYN_<cik>_<period>` — except prod shows
`BACKFILL_MIG015_<short_cik>_<real_accession>_<period>` for these CIKs,
which means dera_synthetic_stabilize ran first, mig015 second, and a
later v2-loader pass overwrote with the real-accession-encoded sentinel.
(Full reconstruction not required for this scoping — the load-path
attribution is already settled by `loaded_at` timestamps.)

### Real row writers

| Bucket | Source | Evidence |
|---|---|---|
| UNKNOWN (446) | `scripts/retired/fetch_nport.py` lines 311, 367, 484: `series_id = metadata.get("series_id") or "UNKNOWN"` | Single literal-`UNKNOWN` write site in the entire repo. Legacy loader, since retired. `loaded_at` clusters Apr 3 13:08 (ADX) and Apr 3 11:22-12:54 (ASA). |
| SYN_ (434) | `scripts/load_13f_v2.py` (Apr 15 v2 cutover) + `scripts/oneoff/dera_synthetic_stabilize.py` Phase 2 (Tier 3 collapse) | `loaded_at` clusters Apr 15 06:04-06:21. Aligns with session memory `e868772` (Apr 15 — N-PORT DERA S2 promote, +2.9M rows, 5,921 queued for entity MDM). |

The current pipeline (`scripts/pipeline/load_nport.py:619`) emits
`{cik}_{accession}` synthetic series_ids when metadata lacks series —
never literal `'UNKNOWN'`. Zero hits for `'UNKNOWN'` series_id writes
in any active loader script.

**Verdict:** The 446 UNKNOWN rows came from the retired fetcher. The 434
SYN_ rows came from the current v2 path. They are **not from the same
loader**.

## 2. SEC form types — sampled accessions

| CIK | Accession | Form | Filed | Report date | Issuer |
|---|---|---|---|---|---|
| 0000002230 (ADX) | 0001104659-25-124101 | NPORT-P/A | 2025-12-23 | 2025-06-30 | Adams Diversified Equity Fund, Inc. |
| 0000002230 (ADX) | 0001104659-25-124108 | NPORT-P/A | 2025-12-23 | 2025-09-30 | Adams Diversified Equity Fund, Inc. |
| 0000002230 (ADX) | 0001104659-26-019620 | NPORT-P  | 2026-02-25 | 2025-12-31 | Adams Diversified Equity Fund, Inc. |
| 0001230869 (ASA) | 0001049169-26-000039 | NPORT-P  | 2026-01-27 | 2025-11-30 | ASA Gold & Precious Metals Ltd     |

All four are N-PORT — confirms CEFs DO file N-PORT (the original
ROADMAP framing "CEFs file N-CSR / NSAR not N-PORT" was incorrect, at
least for these two issuers). ADX is calendar-year quarter-end; ASA is
non-calendar (Feb / May / Aug / Nov fiscal quarters).

Holdings counts vs filing positions: 95-100 rows per accession on the
SYN_ side — consistent with ADX's ~95-position equity portfolio and
ASA's ~140-position gold-mining book per the FundReport totals
($3.0B and $1.1B respectively).

## 3. By-design hypothesis spot-check

ADX (CUSIP `006212104`) and ASA (CUSIP `G3156P103`) both appear as 13F
portfolio positions held by other managers, attributed to the **holder's**
manager_id, not to ADX/ASA's CIK as a fund:

| CUSIP | Issuer | Top holder (cik / manager) | MV |
|---|---|---|---|
| G3156P103 | ASA Gold & Precious Mtls | 0001510281 / Saba Capital Management | $735.8M |
| G3156P103 | ASA Gold & Precious Mtls | 0000895421 / Morgan Stanley       | $212.7M |
| 006212104 | Adams Diversified Equity | 0000895421 / Morgan Stanley       | $201.8M |
| 006212104 | Adams Diversified Equity | 0001510281 / Saba Capital Management | $176.9M |

The ASA L-share CUSIP has 85 distinct 13F filers / 261 positions /
$1.69B aggregate — third-party 13F attribution is working correctly.

ADX (CIK 0000002230) **also files its own 13F-HR** as a multi-strategy
manager: 376 holdings_v2 rows, $11.3B aggregate AUM, 2025Q1-Q4
coverage. This is independent of the N-PORT data path.

## 4. Classification

**MIXED. Confidence: HIGH.**

- **BY_DESIGN portion (~96 ADX rows):** The 96 UNKNOWN rows for ADX
  2025-09 are pure duplicates of 96 SYN_ rows (same accession, same
  CUSIPs, same shares, same MV). Drop the UNKNOWN side; SYN_ already
  carries the same data correctly. Cleanup-only fix.

- **MIXED portion (~350 ASA rows + 0 ADX rows):** ASA has UNKNOWN rows
  for 2024-11 / 2025-02 / 2025-08 that have **no SYN_ companion**.
  Dropping these UNKNOWN rows without a parallel SYN_ backfill would
  delete three filing periods of valid ASA holdings. Real fix requires
  re-running the v2 N-PORT DERA loader against the older periods so
  ASA's SYN_0001230869 series gets the same period coverage as the
  current 2025-11 entry.

- **No BY_ACCIDENT signal:** No active loader writes `series_id='UNKNOWN'`.
  The retired fetcher that did is not on the pipeline cron.

## 5. Scope of the same broken path on other Tier A CIKs

**Bounded.** The literal-`UNKNOWN` series_id pattern in fund_holdings_v2
is **strictly limited to ADX (96 rows) + ASA (350 rows)**. Database-wide
scan:

```
Pattern         CIKs
unk+syn          2   <- ADX, ASA only
syn_only       711
real_only     1283
```

No other Tier A CIK from Phase 1 sits in `unk+syn` or `unk_only`. The
other ~711 CIKs that the v2 N-PORT loader picked up (`syn_only`) never
went through the retired fetcher. The retired loader's CEF blast radius
was 2 issuers — likely because those were the only CEFs queued in its
input list at the time, not a systemic loader bug.

## 6. Recommendation

**Roll into `cef-attribution-path`. Do not surface as a separate fix.**

Concrete shape:
- **PR-2 fetch / PR-4 load (cef-attribution-path):** when re-running
  v2 N-PORT loader against ADX + ASA's older filing periods, generate
  SYN_-keyed companions for ASA 2024-11 / 2025-02 / 2025-08. Sentinel
  the ADX 2025-09 case as already-covered (96 byte-identical duplicates;
  drop UNKNOWN side at the same time).
- **One-time cleanup script** (oneoff, post-PR-4): UPDATE
  `is_latest=FALSE` on the 446 UNKNOWN rows once SYN_ companions exist
  for every period. Mirrors the BRANCH 1 flip from #247
  (`cleanup_stale_unknown.py`) — same shape, same safety gates.
- **Loader hygiene:** none required. Retired loader is already retired;
  current loader does not produce UNKNOWN. No active code path bug.

The existing `cef-attribution-path` ROADMAP entry already names ADX +
ASA as the seed cohort and frames the fix as a 5-PR workstream. This
investigation refines its scoping question 2 ("by design or by accident")
to: **legacy-loader residue, the v2 path is correct architecture, just
needs period coverage extended.**
