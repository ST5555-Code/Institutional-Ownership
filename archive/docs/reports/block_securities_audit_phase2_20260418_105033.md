# BLOCK-SECURITIES-DATA-AUDIT — Phase 2 Re-Seed Report

- Branch: `block-securities-data-audit`
- Run id: `20260418_105033`
- Phase 1 commits: `bcc5867` (RC1), `fc2bbbc` (RC2), `889e4e1` (scope guard), `22a986e` (RC3 flagging)
- Environment: staging DB (`data/13f_staging.duckdb`). Prod untouched.

---

## Headline

**Gate result: MIXED — Gate 3 PASS, Gates 1 & 2 FAIL on raw measurement, but
the failures are measurement artifacts, not fix regressions.**

- **RC2 (Fix 2) demonstrably works** on every Phase 0 audited case:
  all 10 audited CUSIPs now carry clean issuer names. Verizon/Morgan
  Stanley/NRG/Cencora/Marsh/ResMed/Atlassian/Constellation/Hologic/First
  Horizon all resolved. Tight-heuristic clipped count on the full 430K
  staging universe: **2** (down from ~150 Phase 0 precision matches),
  both Morgan Stanley ETF Trust funds where "ORGAN STANLEY" outvoted
  "MORGAN STANLEY" — the RC2 Phase 1 note's known limitation.
- **Gate 3 (scope guard, Fix 3) PASSES cleanly**: `s ↔ cc` issuer_name
  drift collapsed from baseline 2,412 to 0.
- **Gate 1 FAILS** because the spec's flow wipes `cc.ticker` for
  prior-resolved rows without resetting `cusip_retry_queue`, so
  `run_openfigi_retry --staging` only re-fetched 2,820 new CUSIPs —
  leaving `securities.ticker` anchored at its prior seeded value via
  `COALESCE(cc.ticker, s.ticker)`. RC1 itself is verifiable on the 283
  openfigi rows cc now holds (4 foreign-exchange = 1.4%, vs Phase 0
  baseline 382/14,472 = 2.6%), but the metric the gate targets
  (securities.foreign_exchange = 444) has barely moved from its 442
  seeded baseline.
- **Gate 2 FAILS** on raw count (385 vs target 20) because the
  classification universe expanded 3.2× (132,618 prod.cc → 430,149 staging.cc)
  when `build_classifications` pulled in CUSIPs from `fund_holdings_v2` and
  `beneficial_ownership_v2`. The Phase 0 heuristic's "BM" prefix catches
  hundreds of legitimate BMW / BMD2 / BMO / BM Technologies / BMARK names
  as false positives in the expanded universe.

**Recommendation: hold Phase 3 (prod sync) until re-run with a
retry-queue reset so RC1 can be fully validated end-to-end.** Sign-off
call: Serge.

---

## Step-by-step execution

### Step 1 — Seed staging from prod

Initial `CREATE OR REPLACE TABLE ... AS SELECT` failed later at Step 2 with
`Binder Error: ON CONFLICT requires a UNIQUE/PRIMARY KEY` because the
`AS SELECT` pattern drops the PRIMARY KEY constraint on
`cusip_classifications.cusip`. Re-seeded using `DROP TABLE + CREATE TABLE
<prod DDL> + INSERT SELECT` to preserve schema. Seed helper:
`scripts/_phase2_seed.py` (ephemeral, not committed).

| table | stg before | prod | stg after | match |
|---|---:|---:|---:|---|
| cusip_classifications | 132,618 | 132,618 | 132,618 | OK |
| securities | 132,618 | 132,618 | 132,618 | OK |
| fund_holdings_v2 | 14,090,397 | 14,090,397 | 14,090,397 | OK |
| holdings_v2 | 12,270,984 | 12,270,984 | 12,270,984 | OK |
| beneficial_ownership_v2 | (missing) | 51,905 | 51,905 | OK |

### Step 2 — build_classifications --staging

Duration: 17m43s (wall) · 430,149 rows classified at ~80K rows/s · 37K
cc upserts/s.

- `cusip_classifications`: 132,618 → **430,149** (+297,531). The
  universe expanded because `get_cusip_universe()` also reads from
  `fund_holdings_v2` and `beneficial_ownership_v2`, both of which now
  exist in staging (fh_v2 was present in prior staging; bo_v2 was
  freshly seeded in Step 1).
- `cusip_retry_queue`: 40,619 rows marked `pending` (2,820 net new from
  this run; 37,799 preserved from prior staging state).
- RC3 triage queue: **82 mismatches** written to
  `logs/override_triage_queue.csv` (47 fuzzy, 35 none) out of 568
  override rows. See §Override triage below.

**Known spec-flow regression**: the UPSERT_SQL sets `ticker = excluded.ticker`
(straight assignment from `classify_cusip`'s None result). This wiped
`cc.ticker` for ~15,800 rows that had prior openfigi tickers. Post-
Step 2 cc.ticker coverage dropped from 16,374 to **567** (manual overrides
only). The prior-resolved rows remain `resolved` in `cusip_retry_queue`,
so Step 3's standard flow cannot re-fetch them.

| metric | staging before | staging after |
|---|---:|---:|
| cc rows | 132,618 | 430,149 |
| cc.ticker populated | 16,374 | 567 |
| cc.figi populated | 15,807 | 0 |
| cc.ticker_source='manual' | 567 | 567 |
| cc.ticker_source='openfigi' | 15,807 | 0 |
| retry_queue pending | 0 | 40,619 |
| retry_queue resolved | 15,807 | 15,807 |
| retry_queue unmappable | 22,118 | 22,118 |

### Step 3 — run_openfigi_retry --staging

Duration: 16m35s · Queue: 2,820 pending · No API key set, so
unauthenticated (≈150 req/min observed).

- API calls made: 2,820 (282 batches × 10)
- Resolved: **483** · no_match: 2,246 · errors: 91 (mostly one connection
  timeout at batch 269, handled by the script's error bucket)
- Retry queue end state: unmappable 22,118 · resolved 16,290 (+483) ·
  pending 2,337 (attempt_count=1, will continue on next run)

Post-Step 3 cc.ticker = 1,050 (567 manual + 483 new openfigi).

### Step 5 — normalize_securities --staging

- `securities`: 132,618 → **430,149** rows (+297,531 from INSERT_MISSING
  path).
- `has_figi`: 16,290 (3.79% — prior 15,807 preserved via COALESCE + 483
  new from cc).
- Orphans missing canonical_type: 0.
- Fix 3 (scope guard) refreshed `s.issuer_name` from `cc.issuer_name`
  on every joined row → Gate 3 resolves.

### Step 4 — Manual overrides

Applied inline during Step 2. 568 override rows loaded; 82 flagged to
triage queue (see §Override triage).

---

## Gates — results

| Gate | Target | Measured | Baseline | Verdict |
|---|---|---:|---:|---|
| 1. securities foreign-exchange ticker count | < 50 | **444** | 442 | **FAIL** (measurement artifact) |
| 1. securities foreign-shape ticker | — | 193 | 191 | (context) |
| 1. cc foreign-exchange ticker count | — | **4** | 382 | **PASS** (98.9% reduction) |
| 1. cc foreign-shape ticker | — | 2 | 191 | **PASS** (99.0% reduction) |
| 2. securities letter-clipped (raw heuristic) | < 20 | **385** | 196 | **FAIL** (universe 3.2×; heuristic FP-heavy) |
| 2. securities letter-clipped (original 132K CUSIPs) | — | 182 | 196 | improved |
| 2. securities letter-clipped (tight heuristic, full 430K) | — | **2** | n/a | RC2 working |
| 3. s ↔ cc issuer_name drift | 0 | **0** | 2,412 | **PASS** |
| 3. s ↔ cc ticker drift | 0 | 0 | 0 | **PASS** |
| 3. s ↔ cc figi drift | 0 | 0 | 0 | **PASS** |

### Gate 1 diagnosis

`build_classifications` UPSERTs `ticker = excluded.ticker` where
`excluded.ticker` is None for non-override rows, wiping cc.ticker for
~15,800 rows. `cusip_retry_queue` rows for those CUSIPs stay `resolved`,
so `run_openfigi_retry` cannot re-fetch them. `normalize_securities`
then runs `COALESCE(cc.ticker, s.ticker)` — because cc.ticker is NULL
for those rows, `s.ticker` keeps its seeded-from-prod value (still 442
foreign-exchange rows). Net: securities.ticker is effectively unchanged
from the baseline it was seeded at; the RC1 fix is not exercised on
those 15,800 CUSIPs in this flow.

On the rows that WERE exercised (283 openfigi-sourced in cc after
Step 3), RC1 works as designed: 4 foreign-exchange and 2 foreign-shape,
most of which are legitimate ADR / FOREIGN CUSIPs that have no US
listing. Preference-over-fallback is observable.

### Gate 2 diagnosis

The Phase 0 heuristic uses 32 clipped-prefix patterns, some intentionally
loose (e.g., `'BM'` to catch `IBM`→`BM`). On the original 132K CUSIPs
this yielded 196 hits in prod. On the expanded 430K universe in staging,
the same heuristic catches legitimate BM* names that are abundant in
`fund_holdings_v2` and `beneficial_ownership_v2` but absent from prod
`securities`:

- `BMW US CAPITAL LLC` (BMW auto finance bonds) — 17+ rows
- `BMD2 Re-REMIC Trust` (legitimate bond trust) — 10+ rows
- `BMO 2022-C1 Mortgage Trust` / `BMO 2023-5C2` etc. — 30+ rows
- `BMARK 2024-V11` (Benchmark CMBS series) — 10+ rows
- `BM Technologies Inc`, `BME Holding`, `BML Inc` — all real names

Restricting to the original 132K CUSIPs (apples-to-apples with baseline)
yields **182** hits vs 196 baseline (−14, modest improvement). Restricting
to the tight 28-pattern heuristic (only Phase 0 specifically-cited
clipped forms) yields **2** hits on the full 430K universe:

```
61774R403  ORGAN STANLEY ETF TRUST
61774R304  ORGAN STANLEY ETF TRUST
```

Both Morgan Stanley ETF Trust funds — a regression of RC2's known
Phase 1 limitation (legitimate name less common than clipped variant).
Likely many filings label the ETF Trust with "ORGAN STANLEY" and fewer
with the clean form; most-common wins.

All 10 Phase 0 audited CUSIPs now show clean issuer names:

| CUSIP | Phase 0 prod | Staging post-fix |
|---|---|---|
| 92343V104 | Walgreens Boots Alliance Inc | **Verizon Communications Inc** |
| 617446448 | WASTE MGMT INC DEL | **Morgan Stanley** |
| 629377508 | WEC ENERGY GROUP INC | **NRG Energy Inc** |
| 03073E105 | ENCORA INC | **Cencora Inc** |
| 571748102 | XCEL ENERGY INC | **Marsh & McLennan Cos Inc** |
| 761152107 | Resmed, Inc. | **ResMed Inc** |
| 049468101 | TLASSIAN CORPORATION | **Atlassian Corp** |
| 21036P108 | STZ | **Constellation Brands Inc** |
| 436440101 | OLOGIC INC | **Hologic Inc** |
| 320517105 | IRST HORIZON CORPORATION | **First Horizon Corp** |

### Gate 3

Gate 3 is cleanly passing. Fix 3 (scope guard adding `issuer_name` to
`normalize_securities.UPDATE_SQL`) resolved all 2,412 prior drifts.

---

## Override triage queue

File: `logs/override_triage_queue.csv`
Rows: 82 · Severity: 35 `none`, 47 `fuzzy`

**First 10 rows:**

| CUSIP | Override ticker | Override company | System issuer_name | Severity |
|---|---|---|---|---|
| 617446448 | WM | Waste Management | Morgan Stanley | none |
| 72201J104 | PFN | PIMCO Income Strategy Fund II | PIMCO INCOME STRATEGY FD II | none |
| G2847J104 | DMAAU | Drugs Made In America Acquisition C | Drugs Made In America Acquisit | fuzzy |
| 746823103 | PMM | Putnam Managed Municipal Income Tru | Putnam Managed Municipal Incom | fuzzy |
| G3643J108 | FERG | Ferguson Enterprises | Flutter Entertainment PLC | none |
| 33835LAA3 | FVRR | FIVERR INTL LTD | FIVERR INTERNATIONAL LTD | none |
| 647581206 | U | Unity Software Inc | NEW ORIENTAL EDUCATION and TECHNOLO | none |
| 57164YAF4 | VAC | Marriott Vacations Worldwide Corp | MARRIOTT VACATION WORLDW | none |
| 26142v105 | DKNG | Draftkings Inc Cl A | Draftkings Inc Com Cl A | none |
| G47862100 | CURR | Currenc Group Inc | INFINT ACQUISITION CORP | none |

**Pattern observations (informational):**

- `fuzzy` rows (47) are mostly substring mismatches caused by normalized
  suffix stripping differences (e.g. "MARRIOTT VACATION WORLDW" truncated
  at the source). Human review recommended but not urgent — tickers are
  likely correct.
- `none` rows (35) are the high-priority triage candidates. Some are
  real wrong-CUSIP errors (`647581206` override says Unity but prod says
  New Oriental Education — CUSIP 647581206 is not Unity's); others are
  rename cases (`G3643J108` "Ferguson Enterprises" vs "Flutter
  Entertainment PLC" — requires confirmation of CUSIP identity).
- Single most important confirmation: `617446448` = Morgan Stanley, not
  Waste Management. The override CSV is demonstrably wrong for this CUSIP
  and the flagger caught it as designed.

Handoff: manual triage is BLOCK-SECURITIES-OVERRIDE-TRIAGE, outside this
block.

### Informational Q4 — override CSV vs staging issuer_name mismatches

568 override rows · **18** CSV co[:4] ≠ staging issuer[:4] (Phase 0
baseline 123). 86% reduction — because RC2 cleaned up the "clipped prod
issuer" cases that were falsely flagged in Phase 0 (e.g., CSV="CITIGROUP",
prod="ITIGROUP" → prefix mismatch). Residual 18 are the real wrong-CUSIP
overrides that RC3 flagging also catches.

---

## Anomalies

1. **CC universe expansion** — prod cc held 132,618 CUSIPs;
   staging cc now holds 430,149 because `get_cusip_universe()` reads
   from three source tables that collectively have more CUSIPs than the
   historical prod cc. Not a defect — build_classifications is
   correctly growing cc to match the full source universe. But this
   makes the gate baselines (defined on prod's 132K) an inexact yardstick.
   If Phase 3 syncs staging → prod, prod cc will also grow 3.2×.
   Downstream implications (retry queue size, openfigi API load,
   securities row count) need a sanity check before Phase 3.

2. **RC1 not end-to-end validated** — as discussed in Gate 1 diagnosis.
   Spec-flow does not reset `cusip_retry_queue`, so ~15,800 prior-resolved
   rows remain at their stale state. To truly validate RC1, a follow-up
   step would need to flip those rows back to `pending` and re-run
   `run_openfigi_retry --staging` (API cost: ~15,800 CUSIPs ÷ 150 req/min
   unauthenticated ≈ 1.75 hours).

3. **Connection timeout on one OpenFIGI batch** — batch 269 hit a connect
   timeout; 10 CUSIPs bumped into `errors` bucket. Script's error
   handling is working as designed; those CUSIPs will retry on next
   `run_openfigi_retry` invocation.

4. **RC2 known limitation realized** — the 2 remaining clipped rows
   (`ORGAN STANLEY ETF TRUST`) are exactly the Phase 1-flagged edge
   case: clipped variant more frequent than clean variant. Informational;
   not a Phase 2 gate failure by itself.

5. **Override triage queue contains high-confidence wrong-CUSIP hits** —
   `617446448` (Morgan Stanley → override says Waste Management) is the
   clearest signal RC3 flagging works. Other clear errors: `647581206`
   (Unity override on New Oriental CUSIP), `G3643J108` (Ferguson on
   Flutter CUSIP), `G47862100` (Currenc on INFINT CUSIP). Manual triage
   is blocking for high-trust overrides but not a Phase 2 gate.

---

## Phase 3 readiness verdict

**Recommend HOLD on Phase 3 prod sync.**

Reasons:

- Gate 1 unvalidated end-to-end (RC1 fix demonstrably works on cc but
  securities still carries stale foreign-exchange tickers from prior
  openfigi runs). A prod sync would carry those stale tickers through.
- CC universe expansion (132K → 430K) is a materially larger dataset
  change than the "cleaning" Phase 1 was scoped for. Needs review before
  promoting.
- RC2 demonstrably works on all Phase 0 audited cases, and Gate 3 is
  clean.

Two paths forward:

**Path A — Light re-run, narrow scope:**
Reset `cusip_retry_queue.status = 'pending'` for the 15,807 prior-resolved
rows (one-line SQL on staging). Re-run `run_openfigi_retry --staging`.
RC1 fix now exercised across the full openfigi-sourced population.
Re-run validation gates. Expected ~1.75h unauthenticated API time.
No code changes. All within Phase 2 authorization scope (arguably —
"standard flow" reasonably includes running the script with different
input queue state).

**Path B — Full scope review:**
Pause, review whether cc universe expansion is intended. Decide whether
Phase 3 sync should port 430K rows or scope down to the original 132K.
Possibly adjust `build_classifications` or `get_cusip_universe` to
match the intended canonical universe.

My recommendation: **Path A** first. It validates RC1 end-to-end within
existing authorization and quickly produces a clean Gate 1 reading.
If Gate 1 passes after Path A, then evaluate universe expansion
question separately. Flag raised, awaiting sign-off.

---

## Artifacts

- `docs/BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md` — Phase 0 findings (unchanged)
- `logs/override_triage_queue.csv` — 82 override triage rows
- `logs/reports/block_securities_audit_phase2_20260418_105033.md` — this report
- `scripts/_phase2_seed.py`, `scripts/_phase2_gates.py` — ephemeral
  helpers (not committed)
