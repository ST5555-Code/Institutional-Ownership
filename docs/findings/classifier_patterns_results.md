# Classifier Pattern Sweep — Results (PR-2)

**Branch:** `classifier-name-patterns`
**HEAD at start:** `8349f1f` (PR-1e index-to-passive)
**Scope:** Extend `INDEX_PATTERNS` in the N-PORT classifier to catch passive funds the original keyword set missed (QQQ, Target Retirement / Date funds, leveraged + inverse ETFs). Reclassify 253 affected funds to `fund_strategy='passive'` across `fund_universe` and `fund_holdings_v2`. Rebuild `peer_rotation_flows`. Add a write-path lock so the next pipeline run preserves the canonical `fund_strategy` value once it has been set.

After this PR the classifier covers all systemic passive name patterns AND historical canonical values are protected from drift.

---

## 1. Pre-state (Phase 1 audit, baseline)

Baseline captured against prod `data/13f.duckdb` immediately before Phase 4, after PR-1e completed.

`fund_universe` distribution:

| `fund_strategy` | Rows |
|---|---:|
| `equity` | 4,978 |
| `excluded` | 3,681 |
| `bond_or_other` | 2,751 |
| `passive` | 1,264 |
| `balanced` | 655 |
| `multi_asset` | 240 |
| `final_filing` | 54 |
| **Total** | **13,623** |

`fund_holdings_v2` distribution:

| `fund_strategy` | Rows |
|---|---:|
| `bond_or_other` | 4,264,299 |
| `equity` | 3,596,436 |
| `passive` | 3,055,575 |
| `excluded` | 1,809,797 |
| `balanced` | 1,113,414 |
| `multi_asset` | 714,874 |
| `final_filing` | 14,380 |
| **Total** | **14,568,775** |

`peer_rotation_flows` fund-level distribution:

| `entity_type` | Rows |
|---|---:|
| `equity` | 2,195,291 |
| `passive` | 1,499,478 |
| `excluded` | 614,942 |
| `balanced` | 474,067 |
| `multi_asset` | 186,532 |
| `bond_or_other` | 90,319 |
| `final_filing` | 4,571 |

Backup carried over from PR-1a at `data/backups/13f_backup_20260430_185107` per plan instruction. No new backup created.

---

## 2. Phase 1 — Extended `INDEX_PATTERNS`

[scripts/pipeline/nport_parsers.py:38](scripts/pipeline/nport_parsers.py:38) — the regex now covers eight additional alternations on top of the original keyword set (INDEX, S&P 500, Russell, NASDAQ, Total Stock/Bond/Market, Wilshire, MSCI, FTSE, Barclays, Aggregate, Broad Market):

```
qqq | target\s*retirement | target\s*date |
\d+(?:\.\d+)?x | proshares | profund | direxion |
daily\s*inverse | inverse
```

Header comment captures the rationale and the `\bUltra\b` rejection (see §4 below).

### Pattern coverage smoke test

Manually verified on 17 fund-name fixtures including 4 active-fund stress cases (American Century Ultra, Wasatch Ultra Growth, Long-Short Concentrated, Active Equity Income). All 17 hit the expected branch.

### `\bUltra\b` rejection

The plan listed `\bUltra\b` and `\bUltraPro\b` as candidate patterns. The first dry-run revealed false positives on actively-managed funds whose name contains "Ultra" as brand naming, not leveraged-ETF terminology:

| Fund | AUM | Read |
|---|---:|---|
| Ultra Fund (American Century) | $26.31B | active growth — "Ultra" is brand |
| LVIP American Century Ultra(R) Fund | $1.26B | variant of above |
| Wasatch Ultra Growth Fund | $0.48B | active growth |
| Bridgeway Ultra-Small Company Fund | $0.09B | actively-managed sibling of Ultra-Small Company *Market* |

Replacement: `\bProShares\b`. ProShares Trust is exclusively a passive / leveraged-ETF family, so matching the issuer brand catches every "ProShares Ultra X" and "ProShares UltraPro X" fund without false positives. Same logic already applies to `\bDirexion\b` and `\bProFund\b`.

Trade-off captured below in §6 (out of scope).

---

## 3. Phase 2 — Pipeline write-path lock

[scripts/pipeline/load_nport.py](scripts/pipeline/load_nport.py) — two new code paths.

### `_apply_fund_strategy_lock(prod_con, series_touched)` (pre-promote)

Reads prod `fund_universe` for the touched series_ids; for any row whose `fund_strategy IS NOT NULL`, rewrites the corresponding staged `fund_holdings_v2.fund_strategy` and `stg_nport_fund_universe.{fund_strategy, fund_category}` to the prod value **before** `super().promote()` inserts the new holdings rows.

Wired into `promote()` immediately after `_enrich_staging_entities` and before the base append-is-latest INSERT.

### `_upsert_fund_universe(prod_con, series_touched)` (COALESCE safety net)

Reads prod's prior `fund_strategy` and `fund_category` for each touched series_id, then performs the existing DELETE+INSERT with `COALESCE(prior, staged)` so even if `_apply_fund_strategy_lock` is bypassed (test fixture, future caller, etc.) the prod values still win when they are non-null.

### Three-branch lock semantics

| Branch | Prod state | Outcome |
|---|---|---|
| A — new series | no row in `fund_universe` | classifier output written |
| B — existing locked | row exists, `fund_strategy IS NOT NULL` | prior value preserved |
| C — NULL backfill | row exists, `fund_strategy IS NULL` | classifier output written |

Five new unit tests in [tests/pipeline/test_load_nport.py](tests/pipeline/test_load_nport.py) — one per branch, plus an empty-set no-op test and a missing-table fallback test — exercise both the lock helper and the COALESCE upsert. All 27 tests in `test_load_nport.py` pass; full `tests/pipeline/` suite passes 227/227.

---

## 4. Phase 3 — Dry-run reclassification audit

[scripts/oneoff/reclassify_with_new_patterns.py](scripts/oneoff/reclassify_with_new_patterns.py) — `--dry-run` (default) walks `fund_universe` for every row whose `fund_strategy ∈ ('equity','balanced','multi_asset')` and whose name matches the extended `INDEX_PATTERNS`, attributes the trigger to the first PR-2 pattern that matches, and writes [docs/findings/pr2_reclassification_dryrun.csv](docs/findings/pr2_reclassification_dryrun.csv).

### First dry-run (with `\bUltra\b|\bUltraPro\b`)

Triggered the plan's STOP gate at 257 candidates. 4 false positives surfaced in the `ultra` bucket (American Century Ultra, LVIP American Century Ultra, Wasatch Ultra Growth, Bridgeway Ultra-Small Company). Halted; reported to user.

### Second dry-run (after `\bUltra\b|\bUltraPro\b` → `\bProShares\b`)

| Pattern | Funds | AUM |
|---|---:|---:|
| `target_date` | 67 | $362.9B |
| `profund` | 67 | $3.9B |
| `target_retirement` | 49 | $839.6B |
| `leveraged_digit_x` | 40 | $23.6B |
| `proshares` | 20 | $6.1B |
| `inverse` | 6 | $0.0B |
| `qqq` | 4 | $444.9B |
| **Total** | **253** | **$1,681.0B** |

Discretionary-token check passed (after refining the regex to exclude `consumer\s+discretionary`, the GICS sector name used in passive sector ETFs).

User waived the 200 cap — the count reflects accurate scope (116 target-date / retirement funds alone). The hard cap is now 300 to keep the orchestrator a regression guard going forward.

Top 10 by AUM (the entire reclassification list of 253 is in [pr2_reclassification_dryrun.csv](docs/findings/pr2_reclassification_dryrun.csv)):

| series_id | Fund | Pattern | AUM |
|---|---|---|---:|
| S000101292 | Invesco QQQ Trust, Series 1 | qqq | $407.7B |
| S000002573 | Vanguard Target Retirement 2035 | target_retirement | $119.4B |
| S000012761 | Vanguard Target Retirement 2040 | target_retirement | $109.1B |
| S000002574 | Vanguard Target Retirement 2045 | target_retirement | $109.0B |
| S000012760 | Vanguard Target Retirement 2030 | target_retirement | $108.9B |
| S000012762 | Vanguard Target Retirement 2050 | target_retirement | $96.0B |
| S000002572 | Vanguard Target Retirement 2025 | target_retirement | $76.5B |
| S000029700 | Vanguard Target Retirement 2055 | target_retirement | $66.9B |
| S000015560 | American Funds 2035 Target Date Retirement | target_date | $55.4B |
| S000015559 | American Funds 2030 Target Date Retirement | target_date | $52.8B |

---

## 5. Phase 4 — Reclassification UPDATEs

Flask was not running. DuckDB had no other readers.

```sql
UPDATE fund_universe
   SET fund_strategy       = 'passive',
       fund_category       = 'passive',
       is_actively_managed = FALSE
 WHERE series_id IN (<253 ids>);

UPDATE fund_holdings_v2
   SET fund_strategy = 'passive'
 WHERE series_id IN (<253 ids>);
```

Plan-vs-actual: the plan's stated UPDATE only touched `fund_strategy` and `fund_category`. Post-write check revealed the PR-1a invariant `passive → is_actively_managed=FALSE` broke (253 rows of `fund_strategy='passive' AND is_actively_managed=TRUE`). Root cause: the funds were moving from active-bucket strategies (`equity`/`balanced`/`multi_asset` → `is_actively_managed=TRUE`) to passive (must be FALSE). A follow-up `UPDATE fund_universe SET is_actively_managed=FALSE WHERE fund_strategy='passive' AND is_actively_managed=TRUE` flipped the residual 253 rows; orchestrator updated to include the flag in the same UPDATE statement going forward.

Row counts:

| Table | Rows updated |
|---|---:|
| `fund_universe` | 253 |
| `fund_holdings_v2` | 186,943 |

Total row counts unchanged (`fund_universe` 13,623; `fund_holdings_v2` 14,568,775). Value migration:

| Table | `passive` pre | `passive` post | Δ |
|---|---:|---:|---:|
| `fund_universe` | 1,264 | 1,517 | +253 |
| `fund_holdings_v2` | 3,055,575 | 3,242,518 | +186,943 |

`fund_universe` consistency post-UPDATE:

| Check | Count |
|---|---:|
| `fund_strategy != fund_category` | 0 |
| `fund_strategy='passive' AND is_actively_managed=TRUE` | 0 |

---

## 6. Phase 5 — `peer_rotation_flows` rebuild

```
python3 scripts/pipeline/compute_peer_rotation.py
```

Runtime breakdown:

| Stage | Wall clock |
|---|---:|
| parse | 62.1 s |
| validate + snapshot | ~3 s |
| promote | 205.0 s |
| **total** | ~4:30 min |

- Run ID: `peer_rotation_empty_20260501_130057`
- Inserts: `17,490,106`
- Auto-snapshot: `data/backups/peer_rotation_peer_rotation_empty_20260501_130057.duckdb`
- Validate gates: PASS (0% row swing)

Post-rebuild fund-level distribution:

| `entity_type` | Pre | Post | Δ |
|---|---:|---:|---:|
| `equity` | 2,195,291 | 2,159,208 | -36,083 |
| `passive` | 1,499,478 | 1,658,866 | **+159,388** |
| `excluded` | 614,942 | 614,942 | 0 |
| `balanced` | 474,067 | 379,560 | -94,507 |
| `multi_asset` | 186,532 | 157,737 | -28,795 |
| `bond_or_other` | 90,319 | 90,316 | -3 |
| `final_filing` | 4,571 | 4,571 | 0 |

Active-bucket (equity + balanced + multi_asset) shrank by 159,385 rows; `passive` grew by 159,388. The 3-row spread on `bond_or_other` is rebuild noise (consecutive-pair recomputation); total row count unchanged at 17,490,106.

Parent-level (institution taxonomy) untouched — `passive=268,988` matches the pre-state baseline exactly.

---

## 7. Validation

`scripts/oneoff/validate_classifier_patterns.py` runs DB checks, the lock unit-test subset, and an optional FastAPI smoke test. Output:

```
=== fund_universe ===
  [PASS] passive count = pre-state + reclassified — observed=1517 expected=1517
  [PASS] all reclassified series locked to passive/FALSE — observed=253 expected=253
  [PASS] fund_strategy == fund_category for all rows — observed=0
  [PASS] passive funds never flagged actively managed — observed=0
  [PASS] no reclassified fund name carries discretionary tokens — observed=0 suspicious

=== fund_holdings_v2 ===
  [PASS] all historical holdings rows for reclassified series are passive — total=186943 passive=186943
  [PASS] fund_holdings_v2 passive count = pre + reclassified rows — observed=3242518 expected=3242518

=== peer_rotation_flows ===
  [PASS] fund-level passive count increased — observed=1658866 pre=1499478
  [PASS] fund-level active-bucket count decreased — observed=2696505 pre=2855890 delta=-159,385
  [PASS] parent-level 'passive' rows untouched — observed=268988 expected=268988

=== pipeline lock — unit tests ===
  [PASS] pytest pr2_lock tests — 5 passed, 22 deselected, 1 warning in 0.52s

=== smoke test (optional FastAPI endpoints) ===
  [PASS] GET /api/v1/portfolio_context?ticker=AAPL&level=fund — 10575 bytes
  [PASS] GET /api/v1/cross_ownership?tickers=AAPL&level=fund — 3911 bytes
  [PASS] GET /api/v1/holder_momentum?ticker=AAPL&level=fund — 5747 bytes
  [PASS] GET /api/v1/short_analysis?ticker=AAPL — 9912 bytes
  [PASS] Invesco QQQ Trust now type='passive'

=== summary ===
  db_checks    : PASS
  lock_tests   : PASS
  smoke_test   : PASS
  overall      : PASS
```

Smoke spot-check — `/api/v1/portfolio_context?ticker=AAPL&level=fund` rank 7:

```
{"rank": 7, "institution": "Invesco QQQ Trust, Series 1",
 "type": "passive", "value": 32648953841.52, ...}
```

QQQ row carries `type='passive'`. Pre-PR it was `type='active'` because `fund_universe.fund_strategy` was `'equity'` and `_fund_type_label` mapped that to `'active'`.

---

## 8. Files changed

| File | Change |
|---|---|
| `scripts/pipeline/nport_parsers.py` | Extended `INDEX_PATTERNS` with QQQ / Target Date|Retirement / `\dX` / ProShares / ProFund / Direxion / Inverse alternations |
| `scripts/pipeline/load_nport.py` | New `_apply_fund_strategy_lock` (pre-promote) + COALESCE-on-prior-value path inside `_upsert_fund_universe` |
| `tests/pipeline/test_load_nport.py` | 5 new tests covering the three lock branches + empty-set + missing-table fallbacks |
| `scripts/oneoff/reclassify_with_new_patterns.py` | New — dry-run / `--confirm` orchestrator with PR-2 pattern attribution + STOP gates (count cap, discretionary tokens) |
| `scripts/oneoff/validate_classifier_patterns.py` | New — DB + lock-test + FastAPI smoke validator |
| `docs/findings/pr2_reclassification_dryrun.csv` | New — 253 reclassified series with triggering pattern + AUM |
| `docs/findings/classifier_patterns_results.md` | This file |
| `ROADMAP.md` | PR-2 moved to COMPLETED, header bump, new Stage B turnover deferred-funds entry |

---

## 9. Stage B turnover deferred candidates

Three Vanguard funds and similar individual cases are passive in behaviour but their names do not match systemic `INDEX_PATTERNS` rules:

- Vanguard Primecap (~$76B)
- Vanguard Windsor II (~$65B)
- Vanguard Equity Income (~$62B)

These will be flagged for reclassification by Stage B (position turnover detection) which validates passive behaviour via holdings stability rather than name regex. Total ~$203B AUM affected.

Adjacent case: **Bridgeway Ultra-Small Company Market** (~$0.13B) is technically passive (Bridgeway-internal index tracker) but was excluded when the `\bUltra\b` pattern was rejected. `\bBridgeway\b` is mixed-purpose (Bridgeway also runs active funds) so the issuer-brand approach used for ProShares does not apply; Stage B is the appropriate gate.

---

## 10. Out of scope (per plan)

- Dropping `fund_category` / `is_actively_managed` columns — PR-3.
- Renaming `equity` → `active`, `fund_holdings_v2.fund_strategy` → `fund_strategy_at_filing` — PR-4.
- Position turnover detection (Stage B) — separate roadmap initiative.
- Vanguard Primecap, Windsor II, Equity Income — added to roadmap, not reclassified in this PR.
- Parent-level classification work — separate institution-level sequence.
- Bear, Short, Long/Short keywords — too high false-positive risk; deferred to Stage B.

---

## 11. Sequence

| PR | Status |
|---|---|
| PR-1a fund-strategy-backfill | done (2026-04-30) |
| PR-1b peer-rotation-rebuild | done (2026-04-30) |
| PR-1c classification-display-audit | done (2026-04-30) |
| PR-1d classification-display-fix | done (2026-05-01) |
| PR-1e index-to-passive | done (2026-05-01) |
| **PR-2 classifier-name-patterns (this)** | **done (2026-05-01)** |
| PR-3 drop fund_category / is_actively_managed | next |
| PR-4 column rename + JOIN switch | queued |
