# BLOCK-TICKER-BACKFILL — Close-out Report

- Branch: `block-ticker-backfill` (rebased onto `origin/main` at `0dc0d5d`)
- Head after rebase: `8aa51b1`
- Date: 2026-04-18

## Scope delivered

The durable value BLOCK-TICKER-BACKFILL ships is the pair of forward-looking
subprocess hooks. The retroactive prod backfill and its validation were
absorbed into BLOCK-3's Phase 4 prod apply during the block interleave;
no duplicate prod work is required from this branch.

### Phases completed on this branch

- **Phase 0** (findings + addendum) — `a64d5f6`, `168927e`. Documents the
  writer inventory, per-month NULL-ticker quantification, regression-path
  specifics, `market_data.sector` secondary gap, structural root cause
  ("Pass C is manually invoked"), and the option-(d) hook placement
  decision covering both canonical securities writers.
- **Phase 0.5** — review gate cleared.
- **Phase 1a** (retroactive enrichment in staging against post-Audit prod)
  — `67e3442`. Audit-clean run: 1,218,264 populated, 159,145 refreshed,
  VTSM S000002848 @ 2025-09 went 3,556 NULL → 555 NULL. Audit CUSIP
  spot-check (VZ / STZ / FHN / TEAM / HOLX) confirmed the is_priceable
  gate behaves as designed — 4 of 5 refreshed cleanly, HOLX held by
  `is_priceable=FALSE` on its securities row as expected.
- **Phase 1b** (forward-looking hooks) — `68b6dcd`, `8aa51b1`. Subprocess
  hooks added at the end-of-main of both canonical securities writers
  (`scripts/build_cusip.py`, `scripts/normalize_securities.py`). Each
  fires `enrich_holdings.py --fund-holdings` with `--staging` forwarded
  when present. Pattern is subprocess (not inline import) so the hook
  survives future REWRITE refactors of `enrich_holdings.py`.

### Phases absorbed by BLOCK-3

- **Phase 2** (staging validation against tightened gate) — satisfied by
  [docs/reports/block3_phase2_rerun_20260418_193735.md](docs/reports/block3_phase2_rerun_20260418_193735.md).
  The post-Audit staging state produces a 44-row `US_MKT` benchmark_weights
  output that cleared the three-part gate; 2025Q4 regression closed.
- **Phase 3** — review gate cleared by BLOCK-3's Phase 3 sign-off.
- **Phase 4** (prod apply) — satisfied by
  [docs/reports/block3_phase4_prod_apply_20260418_201319.md](docs/reports/block3_phase4_prod_apply_20260418_201319.md).
  Prod `fund_holdings_v2.ticker` backfill applied via BLOCK-3's merge
  sequence (`92b5bf0..0dc0d5d` on main). BLOCK-TICKER-BACKFILL does not
  replay these writes — they're already in prod.

## What merges to main

Five commits on `block-ticker-backfill` post-rebase:

| # | commit | description | net diff |
|---|---|---|---|
| 1 | `a64d5f6` | docs(block-ticker-backfill): findings and fix plan | docs only |
| 2 | `168927e` | docs(block-ticker-backfill): addendum — cusip step-change note + hook placement verification | docs only |
| 3 | `67e3442` | chore(block-ticker-backfill): phase 1a rerun complete — clean prod state | empty (milestone record in history) |
| 4 | `68b6dcd` | feat(build_cusip): subprocess hook — trigger ticker backfill post-securities-update | +14 LOC |
| 5 | `8aa51b1` | feat(normalize_securities): subprocess hook — trigger ticker backfill post-securities-update | +14 LOC |

File-level diff against `origin/main`:

| file | lines added |
|---|---:|
| `docs/BLOCK_TICKER_BACKFILL_FINDINGS.md` | +358 |
| `scripts/build_cusip.py` | +14 |
| `scripts/normalize_securities.py` | +14 |
| **total** | **+386** |

Dropped during rebase:
- `db27cbd` (is_priceable gate on `enrich_holdings.py`) — already on main
  via BLOCK-3's cherry-pick as `334eac6`. Rebase auto-detected as
  duplicate.
- Original Phase 1a milestone commit (was `15b537f`) — dropped per
  kickoff spec; numbers were pre-Audit and obsolete. The Phase 1a rerun
  milestone (`67e3442`) records the canonical numbers.

## Hooks on merge — behavior

When `scripts/build_cusip.py` runs (prod or staging):
1. Existing main flow: OpenFIGI retry → `update_securities_from_classifications` → CHECKPOINT → `record_freshness`.
2. Post-main (new): subprocess to `python3 scripts/enrich_holdings.py --fund-holdings [--staging]`.
3. `enrich_holdings.py` Pass C applies the `is_priceable=TRUE` gate (from commit `334eac6` on main) and writes NULL→ticker transitions to `fund_holdings_v2`.
4. Try/except wraps the subprocess; a Pass C failure does not break `build_cusip.py`'s exit status.

When `scripts/normalize_securities.py` runs: identical hook pattern post-`normalize()`.

### Dry-run and error-path safety

- `build_cusip.py --dry-run` returns before the hook (main line 407 early return). No spurious Pass C run on dry-runs.
- `normalize_securities.py` has no `--dry-run` mode (UPDATE+INSERT is already transactional+idempotent). If `cusip_classifications` is missing, `main()` calls `sys.exit(1)` before reaching the hook.
- Both hooks respect `--staging` — if the parent wrote to staging, Pass C targets staging.

### Duplicate-invocation note

A pipeline session that invokes both `build_cusip.py` and
`normalize_securities.py` (the typical end-to-end flow) will fire Pass C
twice. Each invocation is idempotent — the `is_priceable=TRUE` gate plus
the `fh.ticker IS NULL` filter means the second run finds zero additional
transitions. Duplicate cost: seconds of wasted wall-clock. Not worth a
de-dup guard at this block's scope; a pipeline-orchestration redesign is
the cleaner long-term answer and belongs outside BLOCK-TICKER-BACKFILL.

## Known residuals carried forward

Both tracked as out-of-scope follow-ons — not fixed by this block:

1. **Pre-existing foreign-shape tickers in `fund_holdings_v2`** (~10K+
   rows: `HO1`, `SYU1`, `APY1EUR`, etc.). Pass C is populate-only; it
   does not clear stale non-priceable tickers already in the table.
   To clear requires either (a) a refresh pass with NULL-out semantics
   for non-priceable tickers, or (b) re-parsing source XML with
   corrected CUSIP→ticker logic.

2. **OTC grey-market tickers flagged `is_priceable=TRUE`** (e.g., CUSIP
   `761152107` `RSMDF` for ResMed). The filter does not catch them as
   designed. Candidate for a future **BLOCK-PRICEABILITY-REFINEMENT** or
   **BLOCK-SCHEMA-CONSTRAINT-HYGIENE**.

Both residuals are noted in the findings doc at
`docs/BLOCK_TICKER_BACKFILL_FINDINGS.md` §10.1 and in the Phase 1a rerun
milestone commit body (`67e3442`).

## Merge instructions (for Serge)

```
git checkout main
git pull
git merge block-ticker-backfill --no-ff
git push
```

After merge, the hooks are active on every subsequent `build_cusip.py` or
`normalize_securities.py` run.

## Linked artifacts

- Findings: [docs/BLOCK_TICKER_BACKFILL_FINDINGS.md](docs/BLOCK_TICKER_BACKFILL_FINDINGS.md)
- Phase 1a rerun log (staging, uncommitted): `logs/phase1a_rerun_20260418_215425.log`
- BLOCK-3 Phase 2 rerun report (validated our Pass C outcome): [docs/reports/block3_phase2_rerun_20260418_193735.md](docs/reports/block3_phase2_rerun_20260418_193735.md)
- BLOCK-3 Phase 4 prod apply report (satisfies BLOCK-TICKER-BACKFILL Phase 4): [docs/reports/block3_phase4_prod_apply_20260418_201319.md](docs/reports/block3_phase4_prod_apply_20260418_201319.md)
- Pre-merge branch tip: `8aa51b1`
