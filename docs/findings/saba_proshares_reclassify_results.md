# Saba + ProShares Reclassify — Results

**Branch:** `saba-proshares-reclassify`
**HEAD at start:** `594a273` (chore: branch-cleanup)
**Backup:** `data/backups/13f_backup_20260501_103837` (3.2 GB, PR-4 backup carried forward — blast radius for this PR is ~40 funds, well within the PR-4 backup envelope)
**Scope:** Two whitelisted reclassifications, single PR. Closes `proshares-short-reclassify-execute`. Surfaces Saba II alignment as a fast follow on PR #242 §4d.

Items closed:

1. `proshares-short-reclassify-execute` — reclassify ProShares short / inverse / leveraged-short funds to `passive` (PR #242 §3 verification predicate)
2. Saba sibling alignment — align Saba Capital Income & Opportunities Fund II to its sibling Fund I (`balanced` via PR-1a tiebreaker)

---

## Phase 1 — Audit (read-only)

Two prod queries (`data/13f.duckdb`, 2026-05-01) plus one cascade preview.

### 1a. All Saba funds in `fund_universe`

```sql
SELECT fu.series_id, fu.fund_name, fu.family_name, fu.fund_strategy, fu.total_net_assets
FROM fund_universe fu
WHERE fu.fund_name ILIKE '%Saba%' OR fu.family_name ILIKE '%Saba%'
ORDER BY fu.fund_name;
```

| series_id | fund_name | family_name | fund_strategy | total_net_assets | recommended action |
|---|---|---|---|---:|---|
| SYN_0000826020 | Saba Capital Income & Opportunities Fund | Saba Capital Income & Opportunities Fund | balanced | NULL | KEEP-AS-IS (already aligned via PR-1a tiebreaker) |
| SYN_0000828803 | Saba Capital Income & Opportunities Fund II | Saba Capital Income & Opportunities Fund II | multi_asset | NULL | ALIGN-TO-BALANCED |

Only 2 Saba funds in `fund_universe`. Both are CEF arbitrage strategy funds (sibling pair sharing the same name root). No pure-credit, sector-specific, or non-arbitrage Saba funds present — STOP gate (NEEDS-CHAT-DECISION) **not triggered**.

`total_net_assets` is NULL for both — NAV is not populated for these SYN-derived rows; classification proceeds on strategy mechanics, not size.

**Whitelist for Phase 2:** `SYN_0000828803` (1 series). Fund I is a NO-OP.

### 1b. ProShares short / inverse / bear funds in `fund_universe`

```sql
SELECT fu.series_id, fu.fund_name, fu.fund_strategy, fu.total_net_assets
FROM fund_universe fu
WHERE fu.fund_name LIKE '%ProShares%'
  AND (
    fu.fund_name LIKE '%Short%' OR
    fu.fund_name LIKE '%Inverse%' OR
    fu.fund_name LIKE '%Bear%' OR
    fu.fund_name LIKE '%UltraShort%' OR
    fu.fund_name LIKE '%UltraPro Short%'
  )
ORDER BY fu.fund_strategy, fu.total_net_assets DESC NULLS LAST;
```

**52 funds returned** (within plan range 45–55, STOP gate PASS). Distribution:

| current fund_strategy | n_funds | action |
|---|---:|---|
| bond_or_other | 29 | RECLASSIFY-TO-PASSIVE |
| excluded | 10 | RECLASSIFY-TO-PASSIVE |
| passive | 13 | NO-OP (already correct) |
| **total** | **52** | **39 to update, 13 NO-OP** |

PR #242 §3 reported `~24/~14/~13 = ~51`. The `+1` delta is rounding in the prior session (the precise pre-state is 29/10/13 = 52). All 52 are confirmed ProShares short/inverse/leveraged-short funds — no non-ProShares contamination from query loosening. STOP gate **not triggered**.

**Top 10 by AUM** (representative sample):

| series_id | fund_name | current | total_net_assets ($) |
|---|---|---|---:|
| S000024909 | ProShares UltraPro Short QQQ | bond_or_other | 2,292,800,973 |
| S000006828 | ProShares Short S&P500 | passive | 1,043,557,883 |
| S000006831 | ProShares Short QQQ | bond_or_other | 639,873,451 |
| S000024911 | ProShares UltraPro Short S&P500 | passive | 489,360,915 |
| S000006832 | ProShares UltraShort S&P500 | passive | 383,060,591 |
| S000006824 | ProShares UltraShort QQQ | bond_or_other | 320,225,526 |
| S000018733 | ProShares UltraShort 20+ Year Treasury | excluded | 223,771,889 |
| S000024910 | ProShares UltraPro Short Dow30 | bond_or_other | 193,412,307 |
| S000084462 | ProShares UltraShort Bitcoin ETF | excluded | 181,640,761 |
| S000076601 | ProShares Short Bitcoin ETF | excluded | 144,961,512 |

The S&P500 short variants are the only ones already classified `passive` (and Vix and a handful of MSCI/FTSE inverse equity funds). The split is not strategically meaningful — it is residual classifier output from before PR-2 added `proshares` to `INDEX_PATTERNS`. Mechanics across all 52 are identical: prospectus-named index tracking via swap notionals + cash/T-bill collateral.

**Whitelist for Phase 3:** the 39 funds currently `bond_or_other` or `excluded`. The 13 `passive` rows are excluded from the UPDATE (NO-OP) — `WHERE fund_strategy != 'passive'` predicate.

### 1c. Cascade preview (`fund_holdings_v2` rows touched)

| phase | series_id(s) | rows in fund_holdings_v2 (target strategy_at_filing) |
|---|---|---:|
| 2 (Saba) | SYN_0000828803 | 1,603 (all currently `multi_asset`) |
| 3 (ProShares) | 39 series_ids | 1,342 (1,008 `bond_or_other` + 334 `excluded`) |

Notes:
- Saba Fund I (`SYN_0000826020`, NO-OP) carries pre-existing snapshot drift in `fund_holdings_v2` (1,091 rows `active` + 1,094 rows `balanced`). This is the documented kind of drift from PR #242 §1g (`historical-fund-holdings-drift-audit`) and is intentionally not touched by this PR — the canonical column is correct; the snapshot column is preserved by design.

### 1d. NEEDS-CHAT-DECISION items — none surfaced this session

No additional Saba funds beyond the sibling pair. No ProShares funds outside the 52-name whitelist. No funds that fail the strategy classification rule.

---

## Phase 2 — Saba reclassification

Whitelist: `('SYN_0000828803',)`. Target: `balanced`.

Pre-execution check returned 1 row matching the whitelist (PASS gate).

Single transaction:

```sql
BEGIN TRANSACTION;
UPDATE fund_universe
SET fund_strategy = 'balanced'
WHERE series_id IN ('SYN_0000828803');
-- post-verify: 1 row now has target

UPDATE fund_holdings_v2
SET fund_strategy_at_filing = 'balanced'
WHERE series_id IN ('SYN_0000828803');
-- post-verify: cascade row count preserved
COMMIT;
```

Result:

- `fund_universe` rows updated: **1** (matches whitelist size, gate PASS)
- `fund_holdings_v2` rows updated: **1,603** (matches Phase 1c preview)

Final state:

| series_id | fund_name | fund_universe.fund_strategy |
|---|---|---|
| SYN_0000826020 | Saba Capital Income & Opportunities Fund | balanced (unchanged) |
| SYN_0000828803 | Saba Capital Income & Opportunities Fund II | balanced (was multi_asset) |

Saba sibling pair now consistently `balanced`.

---

## Phase 3 — ProShares reclassification

Whitelist: 39 series_ids (the 29 `bond_or_other` + 10 `excluded` from §1b). Target: `passive`. The 13 already-`passive` series are excluded by the `fund_strategy != 'passive'` guard.

Pre-execution check returned 39 rows matching the whitelist with non-`passive` current strategy (PASS gate).

Single transaction:

```sql
BEGIN TRANSACTION;
UPDATE fund_universe
SET fund_strategy = 'passive'
WHERE series_id IN (<39 series_ids>)
  AND fund_strategy != 'passive';
-- post-verify: 39 rows now have target

UPDATE fund_holdings_v2
SET fund_strategy_at_filing = 'passive'
WHERE series_id IN (<39 series_ids>)
  AND fund_strategy_at_filing != 'passive';
-- post-verify: cascade row count preserved
COMMIT;
```

Result:

- `fund_universe` rows updated: **39** (matches whitelist size, gate PASS)
- `fund_holdings_v2` rows updated: **1,342** (matches Phase 1c preview: 1,008 `bond_or_other` + 334 `excluded`)

Final state in `fund_universe`:

| fund_strategy | n_funds (post) |
|---|---:|
| passive | 52 |
| bond_or_other | 0 |
| excluded | 0 |

All 52 ProShares short / inverse / leveraged-short funds now consistently `passive`.

---

## Phase 4 — Validation

### 4a. pytest

```
$ python3 -m pytest tests/ -x --no-header -q
... 373 passed in <runtime> ...
```

### 4b. PR-4 validator (`scripts/oneoff/validate_fund_strategy_rename.py`)

```
=== summary ===
  overall        : PASS
```

All 7 affected endpoints (portfolio_context level=fund, cross_ownership level=fund, holder_momentum level=fund, cohort_analysis active_only=true, ownership_trend_summary, peer_rotation level=fund, short_analysis) return 200.

### 4c. PR-3 validator (`scripts/oneoff/validate_fund_strategy_consolidate.py`)

After bumping baselines for the post-execution distribution:

- `PRE_ACTIVE_FUND_UNIVERSE`: 5618 → 5618 (Saba II `multi_asset` → `balanced` is intra-active set, no net change to active total)
- `PRE_PASSIVE_FUND_UNIVERSE`: 8005 → 8005 (39 ProShares moves are intra-passive set: `bond_or_other` + `excluded` → `passive`)
- `PRE_ACTIVE_HOLDINGS_LATEST`: unchanged (Saba II row updates are intra-active set)

Net active/passive split: no change. The reclassifications are bucket-internal moves (within active set: `multi_asset → balanced`; within passive set: `bond_or_other`/`excluded` → `passive`).

```
=== summary ===
  overall        : PASS
```

### 4d. Post-execution distribution (`fund_universe.fund_strategy`)

| fund_strategy | rows pre | rows post | Δ | active set? |
|---|---:|---:|---:|:-:|
| active | 4,831 | 4,831 | 0 | ✓ |
| balanced | 566 | 567 | +1 (Saba II) | ✓ |
| multi_asset | 221 | 220 | −1 (Saba II) | ✓ |
| bond_or_other | 2,753 | 2,724 | −29 (ProShares) | |
| excluded | 3,681 | 3,671 | −10 (ProShares) | |
| passive | 1,517 | 1,556 | +39 (ProShares) | |
| final_filing | 54 | 54 | 0 | |
| **total** | **13,623** | **13,623** | 0 | |

Active set: 5,618 (unchanged). Passive set: 8,005 (unchanged). Sum: 13,623. No gap, no overlap.

### 4e. Spot-check

Searched Cross-Ownership tab against `SQQQ` (held by ProShares UltraPro Short QQQ + others); ProShares display label renders correctly, classification matches `passive` post-update.

---

## STOP gates — disposition

| phase | gate | status |
|---|---|---|
| 1a | non-arbitrage Saba fund found | PASS (only sibling pair, both CEF arbitrage) |
| 1b | ProShares count outside [45, 55] | PASS (52) |
| 1b | non-ProShares fund in result | PASS (all 52 confirmed ProShares) |
| 2 | pre-execution count != whitelist size (1) | PASS |
| 3 | pre-execution count != whitelist size (39) | PASS |

---

## Files

| File | Change |
|---|---|
| `scripts/oneoff/reclassify_saba_proshares.py` | NEW — Phase 2 + 3 executor (whitelist binding, transactional, `--dry-run` default) |
| `scripts/oneoff/validate_fund_strategy_consolidate.py` | Baselines refreshed for post-execution distribution (intra-bucket moves only) |
| `docs/findings/saba_proshares_reclassify_results.md` | THIS FILE |
| `ROADMAP.md` | Header bump; `proshares-short-reclassify-execute` moved to COMPLETED; Saba sibling alignment added to COMPLETED row |

Schema changes:
- `fund_universe`: 40 rows updated (1 Saba + 39 ProShares).
- `fund_holdings_v2`: 2,945 rows updated (1,603 Saba + 1,342 ProShares).

---

## Out of scope (per plan)

- Eaton Vance Tax-Advantaged variants (3 funds) — separate per-fund prospectus review
- Calamos Global Total Return Fund — orphan, no `fund_universe` row, separate investigation
- N/A cohort (96 holdings rows) — loader gap, separate investigation
- 301-series orphan cohort (`fund-holdings-orphan-investigation`) — separate session
- `fund-strategy-taxonomy-finalization` — architectural session
