# int-04-p0 — Phase 0 findings: RC4 issuer_name propagation scope guard

_Prepared: 2026-04-21 — branch `remediation/int-04-p0` off main HEAD `8a7afb2`._

_Tracker: [docs/REMEDIATION_PLAN.md](../REMEDIATION_PLAN.md) Theme 1 row `int-04`; [docs/REMEDIATION_CHECKLIST.md](../REMEDIATION_CHECKLIST.md) Batch 1-A. Upstream finding: [docs/findings/2026-04-18-block-securities-data-audit.md](../2026-04-18-block-securities-data-audit.md) §5 (RC4 — "Scope guard — issuer_name propagation to `securities`")._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverables: this document + Phase 1 scope.

**Headline.** RC4 is **half-shipped**. Commit [`889e4e1`](../../commit/889e4e1) (_fix(normalize_securities): RC2 guard — refresh issuer_name from cc_, 2026-04-18 09:49 EDT) added the issuer_name refresh to `normalize_securities.py::UPDATE_SQL`, and today's prod + staging DBs show **zero `s ↔ cc` issuer_name divergence** across 430,149 matched CUSIPs (original finding measured 2,412 drifts on 132K rows). However a **parallel cc → s port** in `scripts/build_cusip.py::SECURITIES_UPDATE_SQL` (lines 313-327) — the one wired into `make build-cusip` — was **not updated** with the same fix. It still omits `issuer_name`. The next `make build-cusip` run after `build_classifications.py` refreshes `cc.issuer_name` will re-open the drift unless `normalize_securities.py` is run afterward. Phase 1 is therefore: add the missing one-line `issuer_name = COALESCE(...)` to `build_cusip.py:SECURITIES_UPDATE_SQL`, then add a regression assertion. No data sweep required (state is already clean).

---

## §1. Current state of the code fix

### §1.1 `normalize_securities.py::UPDATE_SQL` — fixed ✅

```python
UPDATE securities s
SET
    canonical_type        = cc.canonical_type,
    canonical_type_source = cc.canonical_type_source,
    is_equity             = cc.is_equity,
    is_priceable          = cc.is_priceable,
    ticker_expected       = cc.ticker_expected,
    is_active             = cc.is_active,
    figi                  = COALESCE(cc.figi, s.figi),
    ticker                = COALESCE(cc.ticker, s.ticker),
    exchange              = COALESCE(cc.exchange, s.exchange),
    market_sector         = COALESCE(cc.market_sector, s.market_sector),
    issuer_name           = COALESCE(cc.issuer_name, s.issuer_name)  -- ← RC4 fix (line 50)
FROM cusip_classifications cc
WHERE s.cusip = cc.cusip
```

[scripts/normalize_securities.py:37-53](../../scripts/normalize_securities.py:37). The `issuer_name = COALESCE(...)` line was introduced by commit [`889e4e1`](../../commit/889e4e1) on 2026-04-18 09:49 EDT (`git log --oneline -- scripts/normalize_securities.py` confirms this is the only change to that SQL since the file was created in `c5eada8` on 2026-04-14). The commit message explicitly frames the addition as the RC4 scope-guard remediation: _"add `issuer_name = COALESCE(cc.issuer_name, s.issuer_name)` to UPDATE_SQL, matching the pattern used for ticker/exchange/etc. Once the RC2 aggregator cleans cc.issuer_name, this resolves the 2,412 drifts on the next normalize_securities run."_

Scope guard analysis for this path:
- **Row filter:** `WHERE s.cusip = cc.cusip` — no NULL-gated, no timestamp-gated; updates every securities row that has a matching cc row.
- **Value guard:** `COALESCE(cc.issuer_name, s.issuer_name)` — a NULL cc value will not wipe a populated s value. In practice `build_classifications.py` guarantees `cc.issuer_name IS NOT NULL` for every row it writes, so this is effectively an unconditional refresh today. The COALESCE is defensive against future schema changes or mid-migration states.
- **Inverse** (cc populated, s NULL): covered — s gets the cc value.
- **Deletion semantics:** neither path deletes. A CUSIP dropped from cc would leave its securities row untouched (stale). Out of scope for RC4; flagged for a separate issue if it matters.

### §1.2 `normalize_securities.py::INSERT_MISSING_SQL` — was always correct ✅

[scripts/normalize_securities.py:55-72](../../scripts/normalize_securities.py:55). Brand-new CUSIPs (cc-only) get `cc.issuer_name` copied straight to `securities.issuer_name`. This was never the bug — RC4 was about **existing** rows whose issuer_name was frozen after the first INSERT. For completeness: `WHERE s.cusip IS NULL` filter is correct, runs only once per new CUSIP, and the `issuer_name` column is in the SELECT list (line 63).

### §1.3 `scripts/build_cusip.py::SECURITIES_UPDATE_SQL` — **NOT fixed** ❌

```python
SECURITIES_UPDATE_SQL = """
UPDATE securities s
SET ticker                = COALESCE(cc.ticker, s.ticker),
    exchange              = COALESCE(cc.exchange, s.exchange),
    market_sector         = COALESCE(cc.market_sector, s.market_sector),
    canonical_type        = cc.canonical_type,
    canonical_type_source = cc.canonical_type_source,
    is_equity             = cc.is_equity,
    is_priceable          = cc.is_priceable,
    ticker_expected       = cc.ticker_expected,
    is_active             = cc.is_active,
    figi                  = COALESCE(cc.figi, s.figi)
    -- issuer_name column intentionally absent prior to RC4;
    -- NOT updated by commit 889e4e1 (which only touched normalize_securities.py)
FROM cusip_classifications cc
WHERE s.cusip = cc.cusip
"""
```

[scripts/build_cusip.py:313-327](../../scripts/build_cusip.py:313). `git log --oneline -- scripts/build_cusip.py` shows the last touch was [`68b6dcd`](../../commit/68b6dcd) (_subprocess hook — trigger ticker backfill post-securities-update_, 2026-04-18). `git blame scripts/build_cusip.py 313..327` should resolve these 10 SET lines to the original `7081886` of 2026-04-14; the RC4 commit `889e4e1` did not touch this file. The parallel UPDATE path is therefore still missing the `issuer_name = COALESCE(...)` line.

### §1.4 `scripts/build_cusip.py::SECURITIES_UPSERT_SQL` (INSERT) — correct ✅

[scripts/build_cusip.py:296-311](../../scripts/build_cusip.py:296). Same pattern as `normalize_securities.py::INSERT_MISSING_SQL` — `issuer_name` is in both the column list (line 298) and SELECT (line 303). New CUSIPs are fine. The bug is UPDATE-only.

### §1.5 Upstream — `scripts/pipeline/cusip_classifier.py` issuer_name_pick — fixed (separate fix, RC2) ✅

[scripts/pipeline/cusip_classifier.py:605-624](../../scripts/pipeline/cusip_classifier.py:605) — `issuer_name_pick` CTE introduced by commit [`fc2bbbc`](../../commit/fc2bbbc) replaces the original `MAX(issuer_name_sample)` aggregator with a most-common + longest-name + alphabetic tie-break window. Keeps the downstream cc rows stable across builds. RC2 is out of scope for int-04 per the prompt but is relevant context: without RC2, even a perfect RC4 fix would only be as clean as the upstream picker.

---

## §2. Current divergence measurement

Measured against `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb` (prod) and `…/13f_staging.duckdb`, read-only, 2026-04-21.

### §2.1 Row counts

| Table | Prod | Staging |
| --- | ---: | ---: |
| `securities` | 430,149 | 430,149 |
| `cusip_classifications` | 430,149 | 430,149 |
| `securities` rows with no cc match (`s` only) | 0 | 0 |
| `cusip_classifications` rows with no s match (`cc` only) | 0 | 0 |

The 1:1 alignment is expected: `build_classifications.py` sources the CUSIP universe from the union of `securities`, `fund_holdings_v2`, and `beneficial_ownership_current`, so every `s.cusip` eventually flows into `cc.cusip`, and every cc CUSIP is seeded back into `s` via `SECURITIES_UPSERT_SQL`. INSERT-side parity is structural.

### §2.2 issuer_name divergence (prod)

```sql
SELECT
  COUNT(*)                                                                AS matched,
  SUM(CASE WHEN s.issuer_name IS NULL AND cc.issuer_name IS NOT NULL THEN 1 ELSE 0 END) AS s_null_cc_nonnull,
  SUM(CASE WHEN s.issuer_name IS NOT NULL AND cc.issuer_name IS NULL THEN 1 ELSE 0 END) AS s_nonnull_cc_null,
  SUM(CASE WHEN s.issuer_name IS NOT NULL AND cc.issuer_name IS NOT NULL
            AND s.issuer_name != cc.issuer_name THEN 1 ELSE 0 END)        AS both_nonnull_differ,
  SUM(CASE WHEN s.issuer_name = cc.issuer_name THEN 1 ELSE 0 END)         AS both_equal
FROM securities s JOIN cusip_classifications cc USING (cusip);
```

| Metric | Prod | Staging |
| --- | ---: | ---: |
| Matched CUSIPs | 430,149 | 430,149 |
| `s` NULL, `cc` non-NULL | **0** | 0 |
| `s` non-NULL, `cc` NULL | **0** | 0 |
| Both non-NULL, values differ | **0** | 0 |
| Both non-NULL and equal | 429,717 | 429,717 |
| Both NULL | 432 | 432 |

**Zero divergence.** This is consistent with a `normalize_securities.py` run having completed after `889e4e1` landed and after `fc2bbbc` re-seeded `cc.issuer_name`. The 432 both-NULL rows are `BOND` / `OPTION` / `CASH` CUSIPs where no upstream source provided an issuer_name (sample row CUSIPs: `05634EWV0`, `6669917V0`, `00CBTCPR0`, `CTTRZVFS1`, `00PBZ2MB9` — all `is_priceable=False`). COALESCE preserves NULL when both sides are NULL; this is expected behavior, not a defect.

### §2.3 Coverage vs universe expansion

| Phase | Matched CUSIPs | Origin |
| --- | ---: | --- |
| Pre-DERA (Apr 14, `7081886`) | 132,618 | Session 1 classification |
| Post-DERA Session 2 promote (Apr 15, `e868772`) | +297,531 | N-PORT DERA ZIP resolved |
| Current prod | 430,149 | = 132,618 + 297,531 |

The universe **has** grown from 132K → 430K since the 2,412-drift finding was first written. Despite the expansion (≈3.2× more rows), divergence is zero today. This rules out the worry in the prompt scope §1 about post-expansion CUSIPs being unprotected — they all landed via `INSERT_MISSING_SQL` / `SECURITIES_UPSERT_SQL` which have always written `issuer_name` correctly. The scope guard bug was never on the INSERT side.

### §2.4 Freshness signal

`data_freshness` does not track `securities` or `cusip_classifications` (both absent from the table). `cc.updated_at` max across prod is **2026-04-18 17:20:50 UTC** — 7.5 hours after `889e4e1` was committed, strongly implying a `normalize_securities.py` run happened after the RC4 fix landed. Absent a freshness row, that is the best-available timestamp for "when was the fix exercised." Recommendation: add `securities` + `cusip_classifications` to `data_freshness` as an incidental Phase 1 fixup (one-line call in both scripts).

---

## §3. Why the divergence is zero today but RC4 is still "open"

The scope-guard defect is a **process defect, not a state defect**. Today the state is clean. But:

1. **Two active writers, only one patched.** `scripts/build_cusip.py::update_securities_from_classifications` ([lines 330-345](../../scripts/build_cusip.py:330)) and `scripts/normalize_securities.py::normalize` ([lines 75-116](../../scripts/normalize_securities.py:75)) both own the cc → s UPDATE. Only the latter was patched by `889e4e1`.

2. **Makefile wires `build_cusip.py`, not `normalize_securities.py`.** `make build-cusip` → `build_cusip.py` (Makefile:149-150). `normalize_securities.py` has no Makefile target and no pipeline script reference. It is a manual ad-hoc script. Engineers running the documented pipeline (`make build-cusip`) will bypass the RC4 fix.

3. **Regression path.** Sequence: (a) `build_classifications.py` refreshes `cc.issuer_name` using the RC2 aggregator; (b) `make build-cusip` runs `SECURITIES_UPDATE_SQL` which updates everything **except** issuer_name in `securities`; (c) `securities.issuer_name` is now stale relative to `cc.issuer_name`. The 2,412-drift symptom from the original finding reappears at whatever rate RC2 picks a different winner than what happens to be cached in `securities`.

4. **Triggering condition.** Any event that changes `cc.issuer_name` without a subsequent `normalize_securities.py` run re-opens the drift. Normal events: Session 3+ CUSIP fetches, new N-PORT quarters, manual `ticker_overrides.csv` additions, future whitelist/classifier tweaks (e.g. int-01 Phase 2 re-queue).

### §3.1 Test: will the next `make build-cusip` regress state?

Not yet attempted (Phase 0 is read-only). Reasoning: RC2 (`fc2bbbc`) already re-seeded `cc.issuer_name` to the mode-aggregator winner. A clean normalize run after that (implied by §2.4 timestamp) propagated it to `s`. A subsequent `make build-cusip` with **no new upstream issuer_name changes** would compute the same values in cc, leaving s untouched because s already matches. The regression only triggers when cc.issuer_name diverges from its previous value — e.g. when a new filing adds a more-common-than-current variant, or when a manual override rewrites a row. Until then, §2.2 stays at zero. Phase 1 verification plan (see §5) should simulate that condition before claiming acceptance.

---

## §4. Cross-item interactions

| Item | Status | Interaction with int-04 |
| --- | --- | --- |
| int-01 (RC1 whitelist) | Merged `2066682` | Re-queue script (`scripts/requeue_foreign_exchange_cusips.py` per int-01-p1) will touch ~500 rows across `cusip_classifications` + `securities`. That refresh path already writes `issuer_name` via the INSERT branch; no int-04 dependency. |
| int-02 (RC2 aggregator) | Shipped `fc2bbbc` | Changes `cc.issuer_name` values. Without int-04 Phase 1, every RC2 run risks re-opening drift on any rows whose mode winner changed. Zero divergence today implies a post-RC2 normalize run has propagated; int-04 Phase 1 hardens this. |
| int-05 (Pass C sweep) | Pending | Depends on int-04. Pass C in `enrich_holdings.py` consumes `securities.ticker` / `securities.issuer_name` to backfill `fund_holdings_v2`. If s.issuer_name is stale, Pass C will stamp stale values onto 10M+ holdings rows. Blocker relationship confirmed. |
| int-06 (forward hooks) | Pending | Plan per `docs/findings/2026-04-18-block-ticker-backfill.md` §6 is to auto-trigger a cc → s port at the end of the main pipeline. int-06 can choose either `build_cusip.py` or `normalize_securities.py` as the target. **Recommendation:** int-04 Phase 1 should patch `build_cusip.py` directly so int-06 can cleanly wire in whichever is most ergonomic without inheriting the scope-guard bug. |

The `enrich_holdings.py` subprocess hook at [scripts/build_cusip.py:441-449](../../scripts/build_cusip.py:441) and [scripts/normalize_securities.py:143-154](../../scripts/normalize_securities.py:143) already fire `enrich_holdings.py --fund-holdings` post-port. Pass C consumes whatever `securities.*` looks like at that moment, so an issuer_name miss in the build_cusip path would cascade into `fund_holdings_v2.issuer_name` too (int-05 scope). Another reason to patch build_cusip.

---

## §5. Phase 1 scope

### §5.1 Code change

One line, one file.

```diff
--- a/scripts/build_cusip.py
+++ b/scripts/build_cusip.py
@@ -320,7 +320,8 @@ SET ticker                = COALESCE(cc.ticker, s.ticker),
     is_equity             = cc.is_equity,
     is_priceable          = cc.is_priceable,
     ticker_expected       = cc.ticker_expected,
     is_active             = cc.is_active,
-    figi                  = COALESCE(cc.figi, s.figi)
+    figi                  = COALESCE(cc.figi, s.figi),
+    issuer_name           = COALESCE(cc.issuer_name, s.issuer_name)
 FROM cusip_classifications cc
 WHERE s.cusip = cc.cusip
 """
```

Targets [scripts/build_cusip.py:313-327](../../scripts/build_cusip.py:313). Matches the pattern in [scripts/normalize_securities.py:37-53](../../scripts/normalize_securities.py:37) exactly. No new dependencies, no signature changes, no data migrations.

### §5.2 Optional hygiene follow-ups (not blocking)

These are separate commits in the same Phase 1 PR if the reviewer wants a single atomic change, or a follow-up `int-04-p1-cleanup` if they want minimal blast radius:

1. **De-duplicate the two UPDATE paths.** `build_cusip.py::SECURITIES_UPDATE_SQL` and `normalize_securities.py::UPDATE_SQL` are near-identical now. Consider extracting a shared constant from `scripts/pipeline/` or deleting one in favor of the other. Deletion candidate: `normalize_securities.py` is ad-hoc + unreachable via Makefile; if `build_cusip.py` is patched, `normalize_securities.py` becomes redundant. Flagged, not decided.
2. **Add `data_freshness` row for `securities` + `cusip_classifications`.** Would eliminate the §2.4 timestamp inference. One line each in `update_securities_from_classifications` and `normalize()`: `record_freshness(con, 'securities')` + `record_freshness(con, 'cusip_classifications')`.
3. **Regression test.** `tests/test_normalize_scope_guard.py`: fixture with one cc row whose `issuer_name` changes between runs, assert `securities.issuer_name` picks up the new value after both code paths.

### §5.3 Acceptance criteria

After the Phase 1 patch:
1. `scripts/build_cusip.py::SECURITIES_UPDATE_SQL` contains the `issuer_name = COALESCE(...)` line, confirmed via `git show HEAD -- scripts/build_cusip.py`.
2. `python3 scripts/build_cusip.py --staging --skip-openfigi` runs green against staging. Post-run, the §2.2 SQL reports `both_nonnull_differ = 0` (same as pre-run).
3. **Regression simulation:** write one staging cc row with a new issuer_name, run `scripts/build_cusip.py --staging --skip-openfigi`, confirm `securities.issuer_name` for that CUSIP matches cc. Then run on prod. (Needs explicit staging DB write authorization per CLAUDE.md rules; do not autonomously run.)
4. No new rows diverged in §2.2 metrics on prod after the next full-pipeline run.

### §5.4 Test plan

1. **Pre-check** (read-only): run §2.2 SQL on prod + staging. Record baseline `both_nonnull_differ` count — should be 0.
2. **Unit regression test** (new): fixture cc row with issuer_name="A"; run port; change cc to "B"; run port; assert s.issuer_name="B" via both `build_cusip.py` and `normalize_securities.py`.
3. **Staging exercise** (with authorization): inject one mutated cc.issuer_name; `make build-cusip` (staging); §2.2 re-run → `both_nonnull_differ` must stay 0 (the mutated row must propagate, not persist as a diff).
4. **Prod exercise** (with authorization): `python3 scripts/build_cusip.py --skip-openfigi`; §2.2 re-run → `both_nonnull_differ` must stay 0.
5. **Acceptance commit** appends `docs/findings/int-04-p1-findings.md` with before/after row counts and the measured drift delta (expected: 0 → 0).

### §5.5 Non-goals (explicitly out of Phase 1)

- **Data sweep.** Not needed; §2.2 shows zero existing drift. Phase 1 is a forward-guard-only patch.
- **int-05 Pass C trigger.** Separate item.
- **int-06 forward hook wiring.** Separate item; Phase 1 simplifies int-06 by making either port path safe to call.
- **Deduplication of the two UPDATE paths.** Flagged in §5.2 but not required for int-04 acceptance.

---

## §6. Risk summary

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Patch introduces wrong-issuer-for-CUSIP rows | **Low** | The exact same COALESCE expression already runs in `normalize_securities.py` with 430K rows and zero bad outcomes. Pattern is battle-tested. |
| Patch accidentally clobbers a hand-maintained `securities.issuer_name` | **Low** | No such override path exists. `securities.issuer_name` has no manual-override loader (unlike `ticker_overrides.csv`). All writes are from cc. |
| Phase 1 ships but Makefile still runs pre-patched cached bytecode | **Very low** | No `.pyc` caching concerns — scripts run from source. |
| Phase 1 changes divergence metric (§2.2) from 0 to non-zero | **Very low** | Would require `cc.issuer_name` to contain bad values. RC2 already filters for most-common + longest + alphabetic, which is the best available signal. If this materializes, it is an RC2 issue, not RC4. |
| Duplicate port paths drift further in the future | **Medium** | §5.2 item 1 (de-duplicate) is the clean fix; out-of-scope today but should be tracked. |

---

## §7. Recommendation

Approve Phase 1 as a one-line patch to `scripts/build_cusip.py:313-327` + a new regression test. Add `data_freshness` rows for `securities` and `cusip_classifications` as an incidental fixup. Defer the dedup decision to a separate "tech-debt" item.

**Estimated Phase 1 effort:** 30 minutes code, 30 minutes test, 30 minutes staging verification (with authorization).

**Next prompt:** `archive/docs/prompts/int-04-p1.md` — Phase 1 implementation prompt for RC4 scope-guard patch + regression test.
