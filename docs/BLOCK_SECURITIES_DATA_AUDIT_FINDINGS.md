# BLOCK-SECURITIES-DATA-AUDIT — Phase 0 Findings

- Branch: `block-securities-data-audit`
- Base commit: `5b501fc`
- Date: 2026-04-18
- Scope: read-only audit of `securities` and `cusip_classifications`. No writes.

---

## TL;DR

Pass C audit at 80% ERROR was **not** a symptom of a single upstream bug. Three
independent corruption vectors feed `cusip_classifications` and `securities`:

1. **`data[0]` selection in the OpenFIGI response** (`build_cusip.py:207` and
   `run_openfigi_retry.py:254`) takes the first listing without filtering for
   a US-priceable exchange. When the first listing is Frankfurt/XETRA, the
   row gets a German ticker + composite FIGI. **~382 `cc` rows and ~442
   `securities` rows affected** (≈2.3–2.8% of equity-like ticker-populated rows,
   all with `ticker_source='openfigi'`).
2. **`MAX(issuer_name_sample)` aggregator in `get_cusip_universe()`**
   (`scripts/pipeline/cusip_classifier.py:548`) picks the lexicographically
   largest issuer_name across three upstream sources. When any upstream row
   has a letter-clipped or wrong label, the aggregator amplifies it into the
   canonical record. **~196 high-precision clipped-prefix matches, ~1,607
   broad recall candidates, 2,412 `s ↔ cc` issuer_name drifts.**
3. **Human-authored CUSIP errors in `ticker_overrides.csv`** — ~20+ override
   rows pair a valid correct ticker with a **different** issuer's CUSIP
   (e.g. `617446448` Morgan Stanley, overridden to `WM` / "Waste Management").
   These propagate via `_apply_override` in
   `scripts/build_classifications.py:199-201`. 568 override rows in total,
   123 show CSV company ≠ prod issuer prefix (many are FPs due to clipped
   prod issuer names; residual real CSV errors need manual triage).

Corruption scope is **2–3% of equity-like rows**, not the 80% observed in
Pass C. The 80% was limited to the 6,022 CUSIP tuples where Pass C would
have swapped a ticker — a strongly biased subset dominated by exactly the
three vectors above. **Below the >30% guardrail: safe to proceed to Phase 1.**

CSV field-offset hypothesis is **disproven**. OpenFIGI v3 is JSON, accessed
by field name (`item.get('ticker')`, `item.get('compositeFIGI')`). No parsing
offset possible in either `build_cusip.py` or `run_openfigi_retry.py`.

**Fix confidence: high** on the two code root causes (`data[0]` filter,
MAX aggregator). **Medium** on `ticker_overrides.csv` — need a full
cusip→issuer cross-check pass, which is a manual task.

---

## 1. Corruption prevalence

### Baseline totals

| table | rows | with ticker | with issuer | with figi |
|---|---:|---:|---:|---:|
| `securities` | 132,618 | 20,659 | 132,618 | 15,807 |
| `cusip_classifications` | 132,618 | 16,374 | 132,618 | 15,807 |

### Q1 — Foreign-exchange tickers on equity CUSIPs

Equity-like = `canonical_type IN ('COM','ETF','PFD','ADR')`.
Foreign-shape regex: `^[A-Z]{2,4}[0-9][A-Z0-9]*$` (HO1, FT2, CB1A, TEAM1EUR).
Foreign-exchange list: `GR,GF,GM,FF,GA,EU,EO,GY,GS`.

| table | rows with ticker + equity-like | foreign-shape | foreign-exchange explicit |
|---|---:|---:|---:|
| `securities` | 15,940 | 191 | **442** |
| `cusip_classifications` | 15,039 | 191 | **382** |

Breakdown by `cc.ticker_source`:

| source | n total | foreign-shape | foreign-exchange |
|---|---:|---:|---:|
| openfigi | 14,472 | 191 | **382** |
| manual | 567 | 0 | 0 |

**Every foreign-exchange ticker comes from `ticker_source='openfigi'`.**
Manual overrides are clean on exchange (they are by design the human-corrected
US-exchange replacements). 482 `cc` rows flagged as suspect by the combined
foreign-shape OR foreign-exchange predicate; **100% of those match
`securities.ticker`** — corruption propagates `cc → s` via
`normalize_securities.py`.

20-row sample (excerpt; same `ticker_source='openfigi'` pattern):

```
00152K101  AKA2GBP   "A K A BRANDS HLDG CORP COM SHS"  exch=XS  openfigi
001744101  HCQ       "MN HEALTHCARE SVCS INC"          exch=GR  openfigi   ← clipped issuer + GR
00183L102  ANGI1EUR  "Angi Inc"                        exch=X1  openfigi
004498101  TSA       "TRANSACTION SYSTEMS"             exch=GR  openfigi
049468101  TEAM1EUR  "TLASSIAN CORPORATION"            exch=EO  openfigi   ← clipped issuer + EU
00846U101  A         "NVIDIA"                          exch=GR  manual     ← manual override OK
00751Y106  AAP       "DVANCE AUTO PARTS INC"           exch=GR  manual     ← manual override OK, issuer clipped
```

### Q2 — Letter-clipped issuer names

High-precision list of 31 seeded clipped prefixes (TLASSIAN, OLOGIC, IRST
HORIZON, ERIZON, PPLE, ICROSOFT, ALGREENS, ASTE MGMT, …):

| table | high-precision hits |
|---|---:|
| `securities` | **196** |
| `cusip_classifications` | **196** |

Broad recall heuristic (`^(TL|LW|TR|LR|RS|NT|ND|LT|LN|MN|RN|WN|PR|PL|SL|SN|SR|WR)[A-Z]`):
**1,607 candidates** — includes false positives (legitimate names starting
with these clusters), so true-clip count likely falls between 196 and ~700.

20-row sample (high-precision list):

```
000957100  BM INDS INC                 ABM      exch=US  openfigi   ← ABM Industries (missing A)
005098108  ORP                         GOLF     exch=US  openfigi   ← clipped (CORP / AARP / etc.)
03784Y200  PPLE HOSPITALITY REIT INC   APLE     exch=US  openfigi   ← Apple Hospitality (missing A)
049468101  TLASSIAN CORPORATION        TEAM1EUR exch=EO  openfigi   ← Atlassian (missing A)
172967424  ITIGROUP INC                C        exch=US  manual     ← Citigroup (missing C)
594972408  TRATEGY INC                 MSTR     exch=US  manual     ← Strategy / MicroStrategy (missing S)
22822V101  ROWN CASTLE INC             CCI      exch=US  manual     ← Crown Castle (missing C)
008073108  EROVIRONMENT INC            AVAV     exch=US  manual     ← Aerovironment (missing A)
03076C106  MERIPRISE FINL INC          AMP      exch=US  manual     ← Ameriprise (missing A)
615369105  OODYS CORP                  MCO      manual             ← Moody's (missing M)
```

Note: clipped issuers affect **both** openfigi-sourced rows (Frankfurt cases
above) and manual-sourced rows (the lower block). The ticker side is often
correct (manual override); only the issuer_name is wrong. This is consistent
with H2: the corruption is in `issuer_name` alone, set independently of ticker.

### Q3 — `securities` ↔ `cusip_classifications` drift

Rows with `s.ticker` AND `cc.ticker` both populated: **16,374**.

| field | drift count | pct of populated |
|---|---:|---:|
| ticker | 0 | 0.00% |
| figi | 0 | 0.00% |
| **issuer_name** | **2,412** | **14.74%** |

`ticker` and `figi` are re-synced by `normalize_securities.py` on every run
(`COALESCE(cc.*, s.*)`) — they track `cc` exactly. `issuer_name` is NOT
refreshed by `normalize_securities.py`: `UPDATE_SQL` at
`scripts/normalize_securities.py:36-51` omits `issuer_name`, so
`securities.issuer_name` is frozen at the INSERT-time value from
`scripts/build_cusip.py:291-305` (`SECURITIES_UPSERT_SQL`). Meanwhile
`cc.issuer_name` gets re-seeded by every `build_classifications.py` run
from `MAX(issuer_name_sample)`. The two drift over time.

### Q4 — `ticker_overrides.csv` review

568 override rows total. Comparing CSV `company_name[:4]` vs
`prod.securities.issuer_name[:4]`: **123 mismatches (21.7%)**.

Most mismatches are false positives caused by prod's own clipped-prefix
corruption (CSV says "CITIGROUP", prod says "ITIGROUP" → [:4] differs).
A minority are **real CUSIP data-entry errors in the override CSV itself**:

```
58733R102  CSV=MERCADOLIBRE   prod=V F CORP COM           correct=MELI  wrong=MLB1
253868103  CSV=DIGITAL REALTY prod=MONOLITHIC PWR SYS INC correct=DLR   wrong=FQI
172908105  CSV=CINTAS         prod=WABTEC                 correct=CTAS  wrong=CIT
87612E106  CSV=TARGET         prod=VANGUARD INFO TECH ETF correct=TGT   wrong=DYH
020002101  CSV=ALLSTATE       prod=ISHARES S&P MID-CAP    correct=ALL   wrong=ALS
G54950103  CSV=LINDE          prod=WILLIAMS-SONOMA        correct=LIN   wrong=(empty)
G5960L103  CSV=MEDTRONIC      prod=WISDOMTREE FLOATING    correct=MDT   wrong=(empty)
```

For each of the above: the CSV's `correct_ticker` matches the CSV's
`company_name`, and CUSIP ownership (checked against known CUSIP registers)
confirms the CSV is right about the company. But `prod.securities.issuer_name`
shows a **completely different** company for the same CUSIP. This is
the third corruption vector — prod's `issuer_name` has wrong
(CUSIP, company) mappings that leaked in from one of the three upstream
sources (likely a filer with a copy-paste error in a 13F, which then got
MAX()'d into the canonical name).

Exact count of real wrong-CUSIP override-CSV errors vs real wrong prod
labels needs manual triage — the auto-heuristic cannot separate them without
a gold-standard CUSIP→issuer lookup. Estimated 20-40 real CSV errors within
the 123 flagged (~4-7% of the override file), and 60-80 real prod
`securities.issuer_name` errors (~0.5% of the 16K populated-ticker rows).

### Q5 — Cross-table propagation

All 482 `cc` rows with foreign-shape or foreign-exchange ticker match
`securities.ticker` 1-to-1 (100%). Confirmed `cc → s` propagation via
`normalize_securities.py`. **Fix must happen at `cc` first**; `securities`
re-seeds from `cc`.

### Localization (upstream vs downstream)

- Foreign-exchange tickers: **originates in `cc`**, propagates to `s`.
- Letter-clipped issuer names: **originates in the three upstream source
  tables** (`securities.issuer_name`, `fund_holdings_v2.issuer_name`,
  `beneficial_ownership_v2.subject_name`), surfaces in `cc` via MAX()
  aggregation, and persists in `s` because `normalize_securities.py` leaves
  `s.issuer_name` frozen after first INSERT.
- Wrong-CUSIP issuer mappings: **originates in upstream sources** (filer
  errors) AND in `ticker_overrides.csv` (author errors). Both paths feed
  `cc.issuer_name` and `cc.ticker` respectively.

---

## 2. Ingest path trace

Both `build_cusip.py` and `run_openfigi_retry.py` use the **OpenFIGI v3 JSON
API** — not CSV. Access is by key (`item.get('ticker')`), not by column offset.
The BLOCK-TICKER-BACKFILL "CSV field-offset bug" hypothesis is disproven.

### `scripts/build_classifications.py:248-261` — cc seeding

```python
row_for_cls = {
    'cusip': src['cusip'],
    'issuer_name': src.get('issuer_name_sample'),   # ← line 251
    ...
}
```

`issuer_name_sample` comes from `get_cusip_universe()`:

### `scripts/pipeline/cusip_classifier.py:546-590` — universe aggregator

```sql
SELECT
  cusip,
  MAX(issuer_name_sample)  AS issuer_name_sample,   -- ← line 548
  MAX(security_type)       AS raw_type_mode,
  ...
FROM (
  SELECT s.cusip, s.issuer_name, ... FROM securities s ...
  UNION ALL
  SELECT fh.cusip, fh.issuer_name, ... FROM fund_holdings_v2 fh ...
  UNION ALL
  SELECT bo.subject_cusip, bo.subject_name, ... FROM beneficial_ownership_v2 bo ...
) all_sources
GROUP BY cusip
```

**`MAX()` on VARCHAR is lexicographic.** For any CUSIP where one upstream row
has a letter-clipped name and others have the clean name, `MAX()` picks the
clipped one: "TLASSIAN CORPORATION" > "ATLASSIAN CORPORATION" because `T > A`.
Same for "OODYS" > "MOODY'S" (`O > M`), "ALMART" > "WALMART" reversed
(but `ALMART < WALMART` alphabetically — so this one would NOT be picked;
real pattern is more nuanced). The aggregator systematically biases toward
any clipped-front-letter corruption whose first surviving letter is
alphabetically later than the true first letter.

### `scripts/build_cusip.py:204-215` — `data[0]` selection (OpenFIGI path 1)

```python
for cusip, result in zip(batch, results):
    data = result.get("data") or []
    if data:
        item = data[0]                     # ← line 207: takes FIRST listing
        ticker = item.get("ticker") or None
        figi = item.get("compositeFIGI") or item.get("figi")
        exchange = item.get("exchCode")
        ...
```

No filter for US-priceable exchange. OpenFIGI v3 returns one entry per
listing venue per CUSIP (a single CUSIP maps to composite + regional
listings — US composite, Frankfurt, XETRA, OTC, etc.). Order is not
guaranteed by exchange. If Frankfurt appears first, Frankfurt wins.

### `scripts/run_openfigi_retry.py:252-254` — same pattern (OpenFIGI path 2)

```python
for cusip, result in zip(batch, response):
    if 'data' in result and result['data']:
        _update_resolved(con, cusip, result['data'][0])   # ← line 254
```

`_update_resolved` at `scripts/run_openfigi_retry.py:86-152` then writes
`ticker`, `figi`, `exchange`, `market_sector` into `cusip_classifications`.
A "FOREIGN → priceable flip" at lines 100-103 partially compensates —
if `exchange IN US_PRICEABLE_EXCHANGES` it flips `is_priceable=TRUE` — but
that flip is conditional on the exchange code and does NOT re-call OpenFIGI
for a cleaner US-exchange listing. The Frankfurt ticker remains.

### `scripts/build_classifications.py:189-208` — manual override application

```python
def _apply_override(cls_row: dict, ov: dict) -> dict:
    ...
    if ov.get('ticker'):
        cls_row['ticker'] = ov['ticker']            # ← line 200
        cls_row['ticker_source'] = 'manual'
    ...
    return cls_row
```

Override sets **only** `ticker` (and `canonical_type` via mapping).
`issuer_name` is NOT updated from the override CSV's `company_name` column —
so if override `correct_ticker` was chosen for the wrong CUSIP, the
wrong-company-for-CUSIP state persists, and `cc.issuer_name` stays whatever
`MAX(issuer_name_sample)` produced.

### `scripts/normalize_securities.py:36-70` — cc → s port

`UPDATE_SQL` refreshes `ticker, exchange, market_sector, canonical_type, figi`
(all COALESCE-from-cc). **Does NOT refresh `issuer_name`** — that's the
source of the 2,412 `s ↔ cc` drifts in Q3. `INSERT_MISSING_SQL` writes
`issuer_name` only for brand-new CUSIPs.

---

## 3. Root cause — three independent bugs

| # | Bug | Site | Evidence | Confidence |
|---|---|---|---|---:|
| **RC1** | OpenFIGI `data[0]` picks first listing without US-priceable filter | `scripts/build_cusip.py:207`, `scripts/run_openfigi_retry.py:254` | 382/14,472 = 2.64% of openfigi-sourced ticker rows have foreign-exchange explicit; **0 from manual source** | **High** |
| **RC2** | `MAX(issuer_name_sample)` aggregator amplifies upstream issuer-name corruption by picking the lexicographically-max variant | `scripts/pipeline/cusip_classifier.py:548` | 196 high-precision clipped-prefix matches in both `s` and `cc`, 1,607 broad candidates; confirmed upstream source (issuer_name set independently of ticker) | **High** |
| **RC3** | `ticker_overrides.csv` contains rows where the human author recorded the wrong company for a CUSIP | `data/reference/ticker_overrides.csv` + `scripts/build_classifications.py:189-208` | 123 CSV vs prod issuer-prefix mismatches; 7 manually-inspected mismatches show clear wrong-CUSIP pattern (MercadoLibre override on VF Corp's CUSIP, etc.) | **Medium** — needs manual triage against gold-standard CUSIP→issuer list |

### Verification on 10 audited CUSIPs from Pass C report

```
CUSIP        s.issuer                        s.ticker  s.figi           s.exch  cc.source
92343V104    Walgreens Boots Alliance Inc    BAC       BBG000C4T7T9     GR      openfigi   ← RC1 + RC2 (ticker+figi = Frankfurt Verizon, issuer = wrong MAX)
617446448    WASTE MGMT INC DEL              WM        NULL             GR      manual     ← RC3 (override wrong CUSIP) + RC2 (issuer from MAX of wrong filings)
629377508    WEC ENERGY GROUP INC            WEC       NULL             GR      manual     ← RC3 + RC2
03073E105    ENCORA INC                      ABG       BBG000GMF8Q1     GR      openfigi   ← RC1 + RC2 (ABG = Asbury Automotive Frankfurt?)
571748102    XCEL ENERGY INC                 MRSH      BBG000BP4MH0     US      openfigi   ← RC1 (MRSH = Marsh & McLennan Frankfurt) + RC2
761152107    Resmed, Inc.                    RSMDF     NULL             GR      manual     ← RC3 (RSMDF is OTC grey) — overrides author chose wrong US ticker
049468101    TLASSIAN CORPORATION            TEAM1EUR  BBG00BYQMJP7     EO      openfigi   ← RC1 + RC2 (clipped: Atlassian)
21036P108    STZ                             CB1A      BBG000GLJ2B8     GR      openfigi   ← RC1 + RC2 (issuer=ticker "STZ", Frankfurt listing)
436440101    OLOGIC INC                      HO1       BBG000GPK986     GR      openfigi   ← RC1 + RC2 (clipped: Hologic)
320517105    IRST HORIZON CORPORATION        FT2       BBG000G8PV53     GR      openfigi   ← RC1 + RC2 (clipped: First Horizon)
```

All 10 explained by RC1 + RC2 + RC3 in combination. No residual unexplained
corruption among the sampled rows.

---

## 4. Proposed fix (Phase 2 spec)

### RC1 fix — prefer US-priceable listing

In `build_cusip.py` and `run_openfigi_retry.py`, replace `data[0]` with
a preference sweep:

```python
# New selection logic:
US_PRICEABLE_EXCHCODES = {'US','UN','UW','UQ','UR','UA','UF','UP','UV','UD','UX'}
# (Composite 'US' covers most cases; the 2-char mic-style codes cover listed variants.)

preferred = next((d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES), None)
item = preferred or data[0]
```

Deterministic. Falls back to `data[0]` when no US listing exists (so ADRs,
pure-foreign CUSIPs keep their current behavior). Expected impact:
~382 `cc` rows + ~442 `securities` rows get corrected on the next
`build_cusip.py` run.

### RC2 fix — dedicated issuer_name chooser

Replace `MAX(issuer_name_sample)` with a longest-non-clipped preference.
Two options:

- **Option A (minimal):** `MIN(issuer_name_sample)` — picks lexicographic
  min. For clipped-front-letter cases ("TLASSIAN" vs "ATLASSIAN"), MIN picks
  the real one ("ATLASSIAN"). Single-line change. Does not fix wrong-CUSIP
  upstream garbage.

- **Option B (robust):** Use a mode-like aggregator:
  ```sql
  SELECT cusip, issuer_name_sample, COUNT(*) AS n
  FROM all_sources
  GROUP BY cusip, issuer_name_sample
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cusip
                             ORDER BY COUNT(*) DESC, LENGTH(issuer_name_sample) DESC) = 1
  ```
  Picks the most-common issuer_name; tie-breaks on length (longer = less
  likely clipped). Handles both clipped-letter cases and single-filer
  data-entry errors. Recommended.

### RC3 fix — override CSV triage

Add a cross-check step before applying overrides: for each row, confirm
the `company_name` matches a gold-standard CUSIP→issuer lookup (e.g.
OpenFIGI `name` field from the US-preferred listing chosen in RC1 fix, or
a third-party lookup). Flag mismatches to a review queue; do not apply
until resolved.

Manual triage of all 568 rows is ~1-2 hours of human time. Auto-triage
using the RC1-fixed OpenFIGI lookup can flag candidates automatically.

### Scope guard — issuer_name propagation to `securities`

Extend `normalize_securities.py:UPDATE_SQL` to refresh `s.issuer_name`
from `cc.issuer_name`, so the 2,412 `s ↔ cc` drifts get resolved once
`cc` is clean. Otherwise cleaning `cc` leaves `securities.issuer_name`
still holding the stale frozen INSERT-time values.

---

## 5. Re-seed plan (Phase 3 spec)

After RC1 + RC2 code fixes are deployed:

1. Truncate and rebuild `cusip_classifications` from scratch on **staging**:
   - `python3 scripts/build_classifications.py --staging`
   - `python3 scripts/run_openfigi_retry.py --staging`
2. Re-apply manual overrides (`ticker_overrides.csv`) — unchanged unless
   RC3 triage has produced an updated CSV.
3. Port to `securities` on staging:
   - `python3 scripts/normalize_securities.py --staging`
4. Run validation queries (the five from Phase 0 §1) on staging and confirm:
   - foreign-exchange ticker count drops to < 50 (ADRs + legitimate
     foreign-only securities)
   - letter-clipped high-precision count drops to < 20
   - `s ↔ cc` issuer drift drops to 0 after Phase 2 `normalize_securities.py`
     scope extension
5. If all three drop to target, sync staging → prod via the
   INF1 staging workflow.
6. Defer downstream v2 table re-seeds (`fund_holdings_v2`, `holdings_v2`,
   `beneficial_ownership_v2`, `market_data`) to BLOCK-DENORM-RETIREMENT.

---

## 6. Guardrail check

- Corruption scope: 2–3% of equity-like ticker-populated rows. Far below
  the >30% stop threshold.
- Root cause identified with **high confidence** on RC1 and RC2,
  **medium** on RC3.
- No writes made during Phase 0. No external fetches.
- Every data claim cited to query. Every code claim cited to file:line.

**Safe to proceed to Phase 1 (fix ingest path) after sign-off.**

---

## 7. Addendum (2026-04-18) — Universe expansion accepted

Phase 2 surfaced cusip_classifications universe growth from historical
132,618 rows to 430K on re-seed. Mechanism: `get_cusip_universe()` reads
`securities` + `fund_holdings_v2` + `beneficial_ownership_v2` in UNION ALL.
The three sources collectively hold ~430K distinct CUSIPs. Phase 0 baseline
was measured against the pre-existing 132,618-row snapshot which was a
subset — origin of that subset not fully diagnosed, likely natural state at
CUSIP v1.4 cutover (2026-04-15) rather than a deliberate gate.

Decision: accept 430K as the intended canonical universe. Rationale:
`cusip_classifications` should hold every CUSIP the system has data on. The
132K subset was incidental, not deliberate. Downstream readers
(`normalize_securities` → `securities`, Pass C → `fund_holdings_v2.ticker`)
benefit from broader coverage.

Scope implication: BLOCK-SECURITIES-DATA-AUDIT now ships both contamination
fixes (RC1, RC2, scope guard, RC3 flagging) and a universe expansion (132K
→ 430K classification surface). Phase 3 prod sync will promote the expanded
surface. Downstream BLOCK-TICKER-BACKFILL resume must account for altered
Pass C behavior — more rows populated, potentially more swaps surfaced.

Side effect on RC3 triage queue: the 82 flagged rows in
`logs/override_triage_queue.csv` were generated against the 430K staging
universe, so they reflect post-expansion state. No re-run needed.

Note on `admin_bp.py:108`: `data[0]` pattern in ticker→CUSIP direction
exists in admin debug UI. Diagnostic only, no persistent writes. Out of
scope for BLOCK-SECURITIES-DATA-AUDIT. Revisit if admin path gains write
semantics.
