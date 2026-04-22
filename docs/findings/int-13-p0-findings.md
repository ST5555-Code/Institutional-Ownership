# int-13 — INF29 OTC grey-market `is_otc` classifier — Phase 0 findings

**Date:** 2026-04-22
**Branch:** `int-13-p0`
**Base:** `main` @ `c3d84b7`
**Scope:** Read-only scan of `securities`, `cusip_classifications`, `_cache_openfigi`, and `data/reference/sec_company_tickers.csv`. Confirms the candidate set for `is_otc = TRUE`, compares three classification signals, and sketches the Phase 1 migration + classifier wiring. No code changes.

---

## 1. TL;DR

- **Decision locked (per remediation prompt):** add `is_otc BOOLEAN DEFAULT FALSE` to `securities` and `cusip_classifications`. Leave `is_priceable` untouched. Liquid-only queries compose `WHERE is_priceable AND NOT is_otc`.
- **Three candidate signals, only two carry weight for `is_priceable=TRUE` rows:**
  | Rule | Source | Priceable rows | Non-priceable rows |
  |---|---|---:|---:|
  | **A.** `UPPER(ticker) IN` SEC ticker-ref with `exchange='OTC'` | [`data/reference/sec_company_tickers.csv`](../../data/reference/sec_company_tickers.csv) (2,596 OTC tickers) | **561** | 253 |
  | **B.** `securities.exchange IN ('OTC US','NOT LISTED')` | OpenFIGI via `_cache_openfigi` | **289** | 0 |
  | **C.** `canonical_type = 'OTHER'` | classifier residual bucket | **0** | 1,097 |
- **Rule A and Rule B are disjoint** (0 rows satisfy both). Union A∪B = **850 priceable CUSIPs** across **672 holdings-active CUSIPs / 28,563 holdings_v2 rows / $226.7 B of 13-F AUM**.
- **The prompt's "~185" figure is a substantial undercount.** It reflects the Rule-B (OpenFIGI exchange) signal only, further filtered to `COM`+`PREF` unlisted non-ETF. The real exposure, once foreign-ADR OTC listings (F-suffix) are included, is 4.6× larger at **850 CUSIPs** and four orders of magnitude larger in AUM ($743 M → $226.7 B).
- **Recommendation for Phase 1:** flag A∪B as `is_otc=TRUE`. Do **not** flag Rule C for priceable semantics (adds zero priceable rows), but optionally flag the 1,097 OTHER-bucket rows so the column stays a complete "OTC universe" tag for downstream enrichment. Call this out as a separate decision in Phase 1.
- **RSMDF (the canonical example from `data_layers.md` §6 S1) alone accounts for $90.6 B of AUM** and is flagged by Rule A only (`securities.exchange='GR'`). Rule B misses it entirely. Any implementation that skips Rule A re-produces the exact hazard INF29 was opened for.
- **Migration is one column.** Classifier update is one new predicate in [`cusip_classifier.classify()`](../../scripts/pipeline/cusip_classifier.py). Backfill is one `UPDATE … SET is_otc=TRUE` query, run once against prod + staging after the column ships.

---

## 2. What `is_otc` needs to mean

**Functional definition.** A row is `is_otc=TRUE` when the security's primary US-accessible venue is OTC (pink / grey / expert market) rather than a registered national exchange (NYSE/Nasdaq/Cboe/NYSE Arca/NYSE American/BATS). Composition in downstream queries:

- Liquid equity universe: `WHERE is_priceable AND NOT is_otc`
- "All OTC regardless of priceability": `WHERE is_otc`
- Existing semantics preserved: `is_priceable` continues to track OpenFIGI's response (no retroactive flip).

**What `is_otc` does NOT mean:**

- Not "illiquid" — some OTC names trade heavily (DTEGY, RTNTF, RSMDF).
- Not "foreign" — many domestic OTC preferred stocks (Fannie/Freddie preferred, regional-bank preferred).
- Not "bond / TRACE-quoted" — TRACE is a FINRA reporting facility for bond dealer-to-dealer trades. Bonds already have `is_priceable=FALSE` and `canonical_type='BOND'`; TRACE-tagged equities are classifier bugs (§5.4) that belong in a separate remediation.

---

## 3. Population counts (read-only on prod @ `c3d84b7`)

### 3.1 `cusip_classifications.canonical_type` distribution

```
BOND         359,287
COM           32,678
OPTION        20,450
CASH           6,128
ETF            5,580
PREF           1,450
FOREIGN        1,150
OTHER          1,097   ← Rule C candidate
MUTUAL_FUND      627
ADR              610
WARRANT          555
CLO              121
REIT             120
BANK_LOAN        106
CEF               71
CONVERT           69
SPAC              50
```

All 1,097 `OTHER` rows already carry `is_priceable=FALSE` and **zero** of them appear in `holdings_v2`. Rule C contributes nothing to priceable-query semantics.

### 3.2 Signal Rule B — OpenFIGI exchange code

Distinct `_cache_openfigi.exchange` values relevant to OTC classification (all listed with row count in §5.1 below). The two codes that mean "OTC / grey" are:

- `'OTC US'` (54 in cache, 67 in `securities`)
- `'NOT LISTED'` (205 in cache, 222 in `securities`)

All 289 `securities` rows on these codes are `is_priceable=TRUE` today. Breakdown:

| exchange    | canonical_type | priceable rows |
|-------------|----------------|---------------:|
| NOT LISTED  | COM            | 178            |
| NOT LISTED  | PREF           | 42             |
| NOT LISTED  | ETF            | 2              |
| OTC US      | COM            | 9              |
| OTC US      | PREF           | 54             |
| OTC US      | ETF            | 4              |
| **total**   |                | **289**        |

### 3.3 Signal Rule A — SEC ticker reference `exchange='OTC'`

`data/reference/sec_company_tickers.csv` has **2,596** tickers with `exchange='OTC'` (out of 10,433 total). Joining to `securities` on `UPPER(ticker)`:

- **814** securities rows match by ticker (priceable + non-priceable)
- **561** of those are currently `is_priceable=TRUE`
- **0** of those also satisfy Rule B (no overlap — Rule A catches foreign-ADR OTCs with F-suffix; Rule B catches domestic OTC preferreds / unlisted notes)

The F-suffix convention (`RSMDF`, `TCKRF`, `CNDIF`, `NBRWF`, `JHIUF`, `NIOIF`, `LAAOF`, `PHTCF`, …) is the standard OTC marker for foreign-company ordinary shares. `securities.exchange` for these rows is typically the foreign primary listing (`GR`, `CN`, `''`, `TRACE`) because OpenFIGI returns the primary venue, not the US OTC surface.

### 3.4 Holdings impact — A∪B on priceable

```
flagged priceable CUSIPs:                850
holdings_v2 rows referencing them:    28,563
distinct CUSIPs in holdings_v2:           672
holdings_v2 AUM (sum market_value_usd): $226,745,407,258  (~ $226.7 B)
```

For scale: total `holdings_v2` AUM is $243 T. Flagged = ~0.09% — but the individual names are material:

| CUSIP | ticker | issuer | securities.exchange | 13-F AUM |
|-------|--------|--------|------------|--------:|
| 761152107 | RSMDF | ResMed Inc                    | GR    | $90.6 B |
| 878742204 | TCKRF | Teck Resources Ltd            | CN    | $56.6 B |
| G0378L100 | CNDIF | AngloGold Ashanti PLC         | —     | $44.6 B |
| 387437205 | GRTUF | Granite Real Estate Investment Trust | CN | $7.1 B |
| G9001E128 | LILAB | Liberty Latin America Ltd     | —     | $3.3 B |
| 47030M106 | JHIUF | James Hardie Industries PLC   | —     | $3.0 B |
| 50202MAB8 | LAAOF | Li Auto Inc                   | TRACE | $2.7 B |
| G6359F137 | NBRWF | Nabors Industries Ltd         | —     | $2.2 B |
| 852234AJ2 | BSQKZ | Block Inc                     | TRACE | $1.9 B |
| 62914VAK2 | NIOIF | NIO Inc                       | TRACE | $1.5 B |

Every one of these is flagged by Rule A and **none** by Rule B.

---

## 4. Recommended classification rule

**Rule A ∪ Rule B**:

```sql
UPDATE securities
SET is_otc = TRUE
WHERE (UPPER(ticker) IN (SELECT UPPER(ticker) FROM sec_otc_ref))
   OR (exchange IN ('OTC US','NOT LISTED'))
```

Where `sec_otc_ref` is derived from `data/reference/sec_company_tickers.csv` filtered to `exchange='OTC'`. The exact load pattern is a Phase 1 decision — two realistic options:

1. **Embed the lookup set inside the classifier** as a module-level constant loaded on import from the reference CSV. Matches the pattern used for `DERIVATIVE_ASSET_CATEGORY` and similar classifier constants. Simple, auditable, no DB dependency.
2. **Persist the OTC ticker list as a lookup table** (e.g., `reference_otc_tickers`) loaded by `build_classifications.py`. Adds one more table to migration 003's follow-on and one more row in `docs/data_layers.md` §5. Benefits: joinable from SQL, single source of truth for future rules that need the same list.

Option 1 is the smaller change and fits the existing classifier structure. Option 2 is the more extensible posture if other rules (e.g., foreign-venue normalization) will reuse the SEC OTC list.

**Optional extension — Rule C:** separately consider flagging `canonical_type='OTHER'` (1,097 rows) as `is_otc=TRUE`. It changes no priceable query behavior (all 1,097 are already `is_priceable=FALSE`) but gives the column a cleaner "OTC universe" semantic. Zero risk; zero functional impact. Recommendation: **defer the Rule-C decision to Phase 1** — surface it explicitly and let the implementer pick. Not blocking for this remediation.

**TRACE-tagged equities (out of scope):** 687 `is_priceable=TRUE` rows carry `securities.exchange='TRACE'` with `canonical_type IN ('COM','PREF','ETF')`. Spot-check confirms these are bond tranches whose OpenFIGI record returned `security_type='SDBCV'`/`'DEBT ...'` and the classifier coerced them to `COM`/`PREF` via the ticker-expected rule (example: `53802LAB8` LivaNova PLC bond returned as `COM`). These are classifier bugs, not OTC grey-market. They should be re-triaged via the canonical-type classifier (separate int-item), not silently folded into `is_otc`. Flagging them here would mask the root cause.

---

## 5. Phase 1 scope

### 5.1 Migration — `011_securities_is_otc.py`

```sql
ALTER TABLE securities              ADD COLUMN IF NOT EXISTS is_otc BOOLEAN DEFAULT FALSE;
ALTER TABLE cusip_classifications   ADD COLUMN IF NOT EXISTS is_otc BOOLEAN DEFAULT FALSE;
```

- Follows the `--staging` / `--prod` / `--both` pattern of [`scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py`](../../scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py).
- Idempotent via `IF NOT EXISTS`.
- Add `schema_versions` row: `011_securities_is_otc`.
- Index strategy: no new index needed. `is_otc=TRUE` cardinality is ~850, all queries that filter on it will already filter on `is_priceable` or `cusip`.

### 5.2 Classifier wiring — [`scripts/pipeline/cusip_classifier.py`](../../scripts/pipeline/cusip_classifier.py)

Where `classify()` builds the output dict (current line 504+ `return {...}`), add:

```python
is_otc = (exchange in _OTC_EXCHANGE_CODES) or (ticker and ticker.upper() in _SEC_OTC_TICKERS)
# …
return {
    'canonical_type': canonical_type,
    …
    'is_priceable': bool(is_priceable),
    'is_otc':       bool(is_otc),
    …
}
```

With module-level constants:

```python
_OTC_EXCHANGE_CODES = frozenset({'OTC US', 'NOT LISTED'})
_SEC_OTC_TICKERS    = _load_sec_otc_tickers()   # reads data/reference/sec_company_tickers.csv once
```

`build_classifications.py` writes the new column into `cusip_classifications`. `normalize_securities.py` [(line 38-49)](../../scripts/normalize_securities.py) already does `UPDATE securities SET … FROM cusip_classifications`; adding `is_otc = cc.is_otc` to that SET clause propagates the flag into `securities`. Both are small mechanical edits.

### 5.3 One-shot backfill

After migration lands, run the SQL in §4 once against prod + staging (not at classifier-run time). This covers the 850 currently-priceable CUSIPs that Phase 1 code paths won't re-visit until the next organic classification pass. Expected affected rows per above: 850 priceable + 253 non-priceable + (optionally 1,097 OTHER) = 1,103 or 2,200 depending on Rule-C choice.

### 5.4 Docs update — [`docs/data_layers.md`](../../docs/data_layers.md) §6 S1

- Mark INF29 / S1 as **DECIDED (Option C — separate `is_otc` column)**.
- Update the `securities` row in §5 to list `is_otc` as an 8th classification column.
- Amend §6 S1 narrative: retire the "tighten `is_priceable`" option, record the rule (A ∪ B), and remove the "~185" placeholder.
- `ROADMAP.md` INF29 → COMPLETED with this PR's SHA once merged.

### 5.5 Test plan (Phase 1)

- Unit test `cusip_classifier.classify()` for three fixtures:
  1. RSMDF (cusip `761152107`) → `is_otc=TRUE` via Rule A
  2. Fannie Mae Pfd F (cusip `313586703`) → `is_otc=TRUE` via Rule B
  3. COM on NYSE → `is_otc=FALSE`
- Gate query for CI (similar to INF39 schema-parity): assert `(SELECT COUNT(*) FROM securities WHERE is_otc=TRUE) >= 800` after backfill, and that the backfill is idempotent (re-run changes 0 rows).

### 5.6 Not in scope

- `holdings_v2` / `fund_holdings_v2` / `beneficial_ownership_v2` denormalized `is_otc` mirror. Not needed — downstream queries join `securities` when they need the flag. Adding the column to `holdings_v2` would re-introduce Class B drift risk (`data_layers.md` §7).
- Fixing TRACE-tagged equities (687 rows). Separate classifier-bug remediation.
- Reclassifying `canonical_type='FOREIGN'` (1,150 rows, all `is_priceable=FALSE`). Orthogonal to `is_otc`.
- Live OTC reference refresh cadence. Current `data/reference/sec_company_tickers.csv` staleness belongs in mig-08's fixture-provenance regime.

---

## 6. Open questions for Phase 1

1. **Rule C disposition.** Flag `canonical_type='OTHER'` as `is_otc=TRUE` (1,097 extra rows, all non-priceable) or leave them `FALSE`? Recommendation above is: defer decision, default to `FALSE`.
2. **Source-of-truth for the OTC ticker list.** Embed in classifier module vs. persist as `reference_otc_tickers` table. Recommendation: embed for this first pass, migrate to a table only if a second rule needs the same list.
3. **Backfill timing.** Run as part of migration 011, or as a separate `scripts/oneoff/int_13_backfill.py`? Recommendation: separate one-off script — it makes the migration a pure schema change and keeps the data mutation auditable.
4. **Non-priceable rows flagged by Rule A** (253 rows — e.g., `canonical_type='FOREIGN'` that already pushed `is_priceable=FALSE` but ticker is in SEC OTC list). Flag `is_otc=TRUE` anyway? Recommendation: **yes** — the column is about identity, not priceability, and these rows may become `is_priceable=TRUE` in future classifier passes, at which point `is_otc` is already correct.

---

## 7. Exit state

- Populations verified on prod DB @ `c3d84b7`:
  - `canonical_type='OTHER'`: 1,097 (all `is_priceable=FALSE`, 0 holdings)
  - `exchange IN ('OTC US','NOT LISTED')`: 289 (all `is_priceable=TRUE`)
  - `UPPER(ticker) IN sec_otc_ref`: 814 (561 priceable, 253 non-priceable)
  - Union A∪B priceable: **850 CUSIPs**
  - Holdings impact A∪B: 28,563 rows / 672 CUSIPs / $226.7 B AUM
- No code changes. No DB writes. No `is_otc` column exists on disk yet.
- Phase 1 deliverables identified: migration 011, classifier edit, `normalize_securities` SET-clause extension, backfill, docs, tests.
- Ready for Phase 1 prompt.

---

## 8. Citations

- Decision context: [docs/data_layers.md §6 S1](../data_layers.md#L486-L504)
- Roadmap entry: [ROADMAP.md INF29](../../ROADMAP.md#L590)
- Remediation plan row: [docs/REMEDIATION_PLAN.md:49](../REMEDIATION_PLAN.md#L49)
- Prior RSMDF audit: [docs/reports/block_securities_audit_phase2b_20260418_155554.md:47](../reports/block_securities_audit_phase2b_20260418_155554.md#L47)
- Classifier entry point: [scripts/pipeline/cusip_classifier.py:372-523](../../scripts/pipeline/cusip_classifier.py#L372-L523)
- `normalize_securities` propagation site: [scripts/normalize_securities.py:38-49](../../scripts/normalize_securities.py#L38-L49)
- Migration template (capture-and-recreate pattern reference): [scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py](../../scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py)
- Reference CSV: [data/reference/sec_company_tickers.csv](../../data/reference/sec_company_tickers.csv) (10,433 rows; 2,596 with `exchange='OTC'`)
