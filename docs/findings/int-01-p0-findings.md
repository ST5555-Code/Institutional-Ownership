# int-01-p0 — Phase 0 findings: RC1 OpenFIGI foreign-exchange ticker filter

_Prepared: 2026-04-21 — branch `remediation/int-01-p0` off main HEAD `cf508a8`._

_Tracker: [docs/REMEDIATION_PLAN.md](../REMEDIATION_PLAN.md) Theme 1 row `int-01` (status "OPEN (Phase 0 done)" at prog-00); [docs/REMEDIATION_CHECKLIST.md](../REMEDIATION_CHECKLIST.md) Batch 1-A. Upstream finding: [docs/BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md](../BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md) §4.1 (RC1)._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverables: this document + Phase 1 scope.

**Headline.** The RC1 code fix has already shipped to main in commit [`bcc5867`](../../commit/bcc5867) (_fix(openfigi): RC1 — prefer US-priceable listing over data[0]_, 2026-04-18 09:46 EDT) and is live on both call sites today. What remains is (a) a narrow whitelist gap (four US OpenFIGI exchCodes not covered) and (b) a residual-data sweep — 216 `cusip_classifications` rows + 276 `securities` rows still carry pre-fix foreign-exchange selections because their cached listing was written before the fix landed and they have not been re-queried since. Phase 1 therefore reduces to: patch the whitelist, re-queue the affected CUSIPs, re-run the retry, and verify row counts drop to the ADR residual.

---

## §1. Current state of the code fix

### §1.1 Call-site #1 — `scripts/build_cusip.py:206-213`

```python
for cusip, result in zip(batch, results):
    data = result.get("data") or []
    if data:
        preferred = next(
            (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
            None,
        )
        item = preferred or data[0]
```

[scripts/build_cusip.py:206-213](../../scripts/build_cusip.py:206). `US_PRICEABLE_EXCHCODES` imported from `pipeline.cusip_classifier` at [scripts/build_cusip.py:56](../../scripts/build_cusip.py:56). Introduced by commit `bcc5867` on 2026-04-18 (git blame confirms lines 209-213 bear that SHA; surrounding lines 206-208/214+ are from the original `7081886` of 2026-04-14).

### §1.2 Call-site #2 — `scripts/run_openfigi_retry.py:256-263`

```python
for cusip, result in zip(batch, response):
    data = result.get('data') or []
    if data:
        preferred = next(
            (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
            None,
        )
        _update_resolved(con, cusip, preferred or data[0])
```

[scripts/run_openfigi_retry.py:256-263](../../scripts/run_openfigi_retry.py:256). Import at [scripts/run_openfigi_retry.py:44-48](../../scripts/run_openfigi_retry.py:44) alongside `US_PRICEABLE_EXCHANGES` and `MAX_ATTEMPTS`. Same `bcc5867` blame for lines 259-263; surrounding lines from `c5eada8` of 2026-04-14.

### §1.3 Whitelist — `scripts/pipeline/cusip_classifier.py:46-48`

```python
US_PRICEABLE_EXCHCODES = frozenset({
    'US', 'UN', 'UW', 'UQ', 'UR', 'UA', 'UF', 'UP', 'UV', 'UD', 'UX',
})
```

[scripts/pipeline/cusip_classifier.py:46-48](../../scripts/pipeline/cusip_classifier.py:46). 11 codes: composite (`US`) + 10 per-venue codes.

### §1.4 Scope: other `data[0]` sites were reviewed and are out of scope

Grep across `scripts/` surfaces three other `data[0]` occurrences:

| File:line | Site | In scope? |
|---|---|---|
| [scripts/admin_bp.py:389-390](../../scripts/admin_bp.py:389) | Admin debug: `data[0]['data'][0].get('figi')` on a ticker→CUSIP probe | **No** — diagnostic UI, no persistent writes. Flagged by [BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §7 addendum](../BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md) and is not listed in this prompt's file allowlist. |
| [scripts/retired/build_cusip_legacy.py:152](../../scripts/retired/build_cusip_legacy.py:152) | Retired legacy builder | **No** — under `retired/`; superseded by `build_cusip.py`. |
| [scripts/api_register.py:210-213](../../scripts/api_register.py:210), [scripts/export.py:35](../../scripts/export.py:35), [scripts/resolve_adv_ownership.py:723](../../scripts/resolve_adv_ownership.py:723) | Unrelated (API payload shape checks, Excel header derivation, CSV writer) | **No** — not OpenFIGI paths. |

Conclusion: both RC1 persistent call sites are patched; no third live persistent site exists.

---

## §2. Live row-count impact

Methodology mirrors [BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §1 Q1](../BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md): equity-like = `canonical_type IN ('COM','ETF','PFD','ADR')`; foreign-shape regex `^[A-Z]{2,4}[0-9][A-Z0-9]*$`; foreign-exchange list `GR,GF,GM,FF,GA,EU,EO,GY,GS`. Read-only queries against `data/13f.duckdb` on 2026-04-21.

### §2.1 Baselines

| table | rows | with ticker | with issuer | with figi |
|---|---:|---:|---:|---:|
| `securities` | **430,149** | 21,142 | 429,717 | 16,291 |
| `cusip_classifications` | **430,149** | 16,852 | 429,717 | 16,285 |

Universe expanded from 132,618 → 430,149 per [BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §7 addendum](../BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md) (accepted 2026-04-18). `securities` and `cc` row counts are now aligned at 430,149 after the CUSIP v1.4 prod promotion ([`8a41c48`](../../commit/8a41c48)).

### §2.2 Foreign-exchange tickers on equity CUSIPs (current)

| table | rows with ticker + equity-like | foreign-shape | foreign-exchange explicit |
|---|---:|---:|---:|
| `securities` | 16,133 | 139 | **276** |
| `cusip_classifications` | 15,228 | 139 | **216** |

**Reconciliation vs. audit baseline (2026-04-18):**

| metric | 2026-04-18 (audit) | 2026-04-21 (current) | delta |
|---|---:|---:|---:|
| `cc` equity-like ticker rows | 15,039 | 15,228 | +189 |
| `cc` foreign-shape | 191 | 139 | **−52** |
| `cc` foreign-exchange explicit | **382** | **216** | **−166** |
| `s` foreign-exchange explicit | **442** | **276** | **−166** |

Rows dropped even though no re-fetch of the 216 affected CUSIPs has happened (see §2.4). The delta is attributable to the 132K → 430K promotion: some previously-foreign-exchange openfigi entries were superseded by classifier re-runs under the RC2 mode-aggregator ([`fc2bbbc`](../../commit/fc2bbbc)) + CUSIP v1.4 promote, which also re-flowed cache entries for CUSIPs that now resolve to a cleaner ticker. The **shape of the bug is unchanged**: every affected row remains openfigi-sourced and propagates 1:1 from `cc` to `securities`.

### §2.3 By `ticker_source`

| source | rows with ticker + equity-like | foreign-shape | foreign-exchange explicit |
|---|---:|---:|---:|
| openfigi | 14,661 | 139 | **216** |
| manual | 567 | 0 | 0 |

Zero manual-override rows have foreign-exchange tickers. The 216 are 100% `ticker_source='openfigi'`, 100% match `securities.ticker` (confirmed by self-join).

### §2.4 Why the fix hasn't cleared the residue

`_cache_openfigi` stores exactly one listing per CUSIP — the listing picked at write time. Only a fresh OpenFIGI response flowing through the patched selector replaces it.

Among the 216 affected `cc` rows (queried 2026-04-21):

| bucket | count |
|---|---:|
| `last_openfigi_attempt IS NULL` | 0 |
| `last_openfigi_attempt <` 2026-04-18 13:46 UTC (pre-fix) | **216** |
| `last_openfigi_attempt ≥` 2026-04-18 13:46 UTC (post-fix) | **0** |

No affected CUSIP has been retried since the selector was patched. `openfigi_attempts` on the 10-row sample pulled for §2.5 is 2 across the board (below `MAX_ATTEMPTS=3`), so the attempt budget has not been exhausted.

`cusip_retry_queue` coverage of the 216:

| `cusip_retry_queue.status` | rows |
|---|---:|
| `resolved` | **212** |
| (no queue row) | 4 |

`run_openfigi_retry.py` only pulls `status='pending'` ([scripts/run_openfigi_retry.py:219-224](../../scripts/run_openfigi_retry.py:219)); 0 of the 216 are currently `pending`. **Re-running the retry script as-is will not re-hit them.** This is the gating observation for Phase 1.

### §2.5 Evidence sample

10 `cc` rows drawn from the affected set (ordered by `last_openfigi_attempt`):

```
cusip      ticker   exch  issuer (first 35)                      status  attempts
10806B100  53S      GR    Bridge Investment Group Holdings Inc   success  2
531229870  LM05     GR    Liberty Media Corp Ser A Formu         success  2
635309107  NCMIEUR  EO    National CineMedia, Inc.               success  2
37611X100  DNA4EUR  EO    Ginkgo Bioworks Holdings, Inc.         success  2
00773U207  AVU0     GR    Adverum Biotechnologies Inc            success  2
449585108  1K0      GR    IGM Biosciences Inc                    success  2
46138G623  GBLDUSD  EU    Invesco MSCI Green Building ETF        success  2
35804X101  AMZEUSD  EO    FRESH VINE WINE, INC.                  success  2
460690100  IPG      GR    Interpublic Group of Cos Inc/The       success  2
90187B408  TWOEUR   EO    TWO HARBORS INVESTMENT CORP.           success  2
```

Exchange breakdown of the 216: `GR`=94, `EO`=83, `EU`=22, `GF`=13, `GM`=2, `GS`=2. All are Bloomberg foreign exchCodes; none are US venues.

`460690100` (Interpublic) is a textbook case: IPG trades on NYSE (exchCode `UN`) but the cache still holds the Frankfurt (`GR`) listing from the pre-fix call. Phase 1 re-fetch will flip it to `UN`.

---

## §3. Whitelist audit — four US exchCodes are missing

The proposed whitelist in [BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §4.1](../BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md) was 11 codes: `US, UN, UW, UQ, UR, UA, UF, UP, UV, UD, UX`. Shipped verbatim in [scripts/pipeline/cusip_classifier.py:46-48](../../scripts/pipeline/cusip_classifier.py:46).

Scanning `_cache_openfigi` for any 2-char `U?` exchCode not in the whitelist surfaces four additional codes that have appeared in live OpenFIGI responses:

| code | cache rows | Bloomberg meaning (per OpenFIGI exchCode reference) |
|---|---:|---|
| `UC` | 17 | National Stock Exchange (NSX / NYSE National) — US |
| `UB` | 13 | NASDAQ OMX BX — US |
| `UM` | 4 | Chicago Stock Exchange (CHX / NYSE Chicago) — US |
| `UT` | 2 | Direct Edge A (now Cboe EDGA) — US |

All four are US equity venues. Under the current whitelist the sweep skips past any CUSIP whose only US-listed entry is on one of these venues and falls back to `data[0]` — potentially picking a non-US listing. Live example in cache: any row currently stamped `UC`/`UB`/`UM`/`UT` was selected because it was already first in `data`, but for a CUSIP whose `UC` listing is second while `data[0]` is `GR`, today's selector would still miss.

Gap is narrow (36 cache rows total, ≤ a handful of equity-like openfigi-sourced rows likely affected) but it is a true false-negative of the intended fix. **Phase 1 should add these four codes.**

### §3.1 Proposed Phase 1 whitelist

```python
US_PRICEABLE_EXCHCODES = frozenset({
    'US',                                              # composite
    'UA', 'UB', 'UC', 'UD', 'UF', 'UM', 'UN',
    'UP', 'UQ', 'UR', 'UT', 'UV', 'UW', 'UX',
})
```

15 codes. Single-file, single-symbol change in [scripts/pipeline/cusip_classifier.py:46-48](../../scripts/pipeline/cusip_classifier.py:46); no call-site edits required.

### §3.2 What remains on `data[0]` fallback by design

For ADRs and pure-foreign CUSIPs, no US listing exists in `data`. `data[0]` fallback is the correct behaviour for those — they should retain their foreign ticker. The post-fix residual foreign-exchange count is bounded by the population of legitimate foreign-only equity CUSIPs in our universe (ADR originals, foreign-domiciled ordinary shares held by 13F filers). No fresh sample of OpenFIGI responses was drawn during Phase 0 to enumerate this set; Phase 1 acceptance criteria below treats any residual ≥ 50 as a signal to re-investigate rather than a hard pass/fail.

---

## §4. Cross-item dependencies

| item | dependency on int-01 | status |
|---|---|---|
| int-02 (RC2 mode aggregator) | Needs RC1-fixed data to measure true RC2 impact per [REMEDIATION_PLAN.md Batch 1-B](../REMEDIATION_PLAN.md). | RC2 code also shipped in [`fc2bbbc`](../../commit/fc2bbbc) ([scripts/pipeline/cusip_classifier.py:603-622](../../scripts/pipeline/cusip_classifier.py:603), mode-frequency + length tiebreak). Same re-seed dependency; Phase 1 data sweep for int-01 will simultaneously exercise RC2. |
| int-03 (RC3 override triage) | Uses OpenFIGI US-preferred as gold standard. | Gold-standard path is live after int-01 Phase 1 re-fetch. No blocker beyond that. |
| int-06 (Pass C forward-hook) | Subprocess hook exists today at [scripts/build_cusip.py:445-452](../../scripts/build_cusip.py:445) calling `enrich_holdings.py --fund-holdings`. Must not regress after RC1 whitelist expansion. | Hook is invocation-only; no code coupling to the selector. Expected to be unaffected. |
| int-23 (universe expansion acceptance) | Accepted 2026-04-18. | `cc` is now 430,149 rows. Phase 1 re-seed operates on post-expansion state. |

The scope guard at `normalize_securities.py` (int-04/RC4) is independent of int-01 and is the companion item in Batch 1-A — it refreshes `s.issuer_name` from `cc.issuer_name` and does not touch ticker selection. No interaction expected.

---

## §5. Phase 1 scope

### §5.1 Code change — whitelist only

Single edit to [scripts/pipeline/cusip_classifier.py:46-48](../../scripts/pipeline/cusip_classifier.py:46) per §3.1. No selector changes. No call-site changes.

**Diff shape:**

```diff
-US_PRICEABLE_EXCHCODES = frozenset({
-    'US', 'UN', 'UW', 'UQ', 'UR', 'UA', 'UF', 'UP', 'UV', 'UD', 'UX',
-})
+US_PRICEABLE_EXCHCODES = frozenset({
+    'US',
+    'UA', 'UB', 'UC', 'UD', 'UF', 'UM', 'UN',
+    'UP', 'UQ', 'UR', 'UT', 'UV', 'UW', 'UX',
+})
```

### §5.2 Data sweep — re-queue + retry

The 216 affected CUSIPs currently sit at `cusip_retry_queue.status='resolved'` (212) or absent (4). `run_openfigi_retry.py` filters to `status='pending'` — they will not be touched. Phase 1 must therefore:

1. Build a re-queue list from the same predicate used in §2.2:
   ```sql
   SELECT cusip FROM cusip_classifications
   WHERE ticker IS NOT NULL
     AND canonical_type IN ('COM','ETF','PFD','ADR')
     AND ticker_source = 'openfigi'
     AND exchange IN ('GR','GF','GM','FF','GA','EU','EO','GY','GS')
   ```
2. For queue rows: `UPDATE cusip_retry_queue SET status='pending', attempt_count=0, last_error=NULL WHERE cusip IN (…)`.
3. For the 4 not-in-queue rows: INSERT to `cusip_retry_queue` with `status='pending'`, `attempt_count=0`.
4. Run `python3 scripts/run_openfigi_retry.py --staging` (then promote once verified).
5. Run `python3 scripts/build_cusip.py --staging --skip-openfigi` to re-port `cc → securities` via `update_securities_from_classifications`.

Re-queue step can be a one-shot helper script under `scripts/oneoff/int-01-requeue.py` or a manual SQL block in the Phase 1 commit; the former preserves an audit trail.

### §5.3 Test plan

Regression fixtures: add a pytest that exercises the selector with a synthetic OpenFIGI payload containing both a `UC`/`UB`/`UM`/`UT` entry and a `GR` entry. The `UC` entry must be selected. Place under `tests/pipeline/test_openfigi_us_preferred.py` or extend the nearest existing OpenFIGI selector test. No network, no DB.

Unit shape:

```python
def test_us_preferred_picks_uc_over_gr():
    data = [
        {'exchCode': 'GR', 'ticker': 'FOO1', 'compositeFIGI': 'BBG000…'},
        {'exchCode': 'UC', 'ticker': 'FOO',  'compositeFIGI': 'BBG001…'},
    ]
    preferred = next(
        (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
        None,
    )
    item = preferred or data[0]
    assert item['ticker'] == 'FOO'
```

Plus a pure-foreign CUSIP regression: `data = [{'exchCode':'GR',...}]` → falls back to `data[0]`.

### §5.4 Acceptance criteria

Run against staging:

- `cc` equity-like foreign-exchange count drops from 216 → **< 50** (target matches the `<50` threshold articulated in [BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §5](../BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md) for ADR + legitimate-foreign-only residual).
- `securities` equity-like foreign-exchange count drops from 276 → **< 50** (by propagation).
- `s ↔ cc` ticker divergence on the affected set: 0 (confirmed today; must stay 0 post-sweep).
- Zero new `openfigi_status='error'` rows attributable to the re-queue.
- Residual exchange values on the post-sweep foreign set are all legitimate foreign (e.g. an ADR whose US listing genuinely does not exist in OpenFIGI's response) — spot-check ≥10 rows by hand.

If residual > 50, escalate before promote — indicates either another whitelist gap or an OpenFIGI response-shape regression.

---

## §6. Hard stop

No code writes performed. No DB writes performed. Phase 1 work blocked pending Serge review of this document.

A PR will be opened with title `remediation/int-01-p0: Phase 0 findings — RC1 OpenFIGI foreign-exchange filter`. Await review.
