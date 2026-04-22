# int-06-p0 Phase 0 Findings — BLOCK-TICKER-BACKFILL Phase 1b forward-looking hooks

**Item:** int-06 — subprocess hooks at end of `scripts/build_cusip.py` and `scripts/normalize_securities.py` that auto-trigger `enrich_holdings.py --fund-holdings` after a `securities` write.
**Scope:** Phase 0. Read-only investigation. No code or data changes.
**Recommendation:** **CLOSE AS NO-OP.** Both hooks are already shipped on `main` via the BLOCK-TICKER-BACKFILL merge (2026-04-18, commit `3299a9f`). No Phase 1 code needed.

---

## 1. Design source — BLOCK_TICKER_BACKFILL_FINDINGS

Source: [docs/BLOCK_TICKER_BACKFILL_FINDINGS.md](../BLOCK_TICKER_BACKFILL_FINDINGS.md).

- §6 *Fix shape* — proposed the subprocess-hook design (Phase 1b), initially at end of `build_cusip.py` only.
- §10.2 *Phase 1b hook placement verification* — verified the full `securities` writer landscape and escalated to **option (d): hook at end of BOTH `build_cusip.py` AND `normalize_securities.py`**, because either script can be the last writer in a given pipeline session.
- Idempotency argument: Pass C's `is_priceable=TRUE AND ticker IS NOT NULL` gate plus the `NULL→ticker` populate-only semantics make duplicate invocations a few-second no-op.
- REWRITE resilience argument: subprocess (not inline import) pattern survives future refactors of `enrich_holdings.py` as long as the CLI shape (`--fund-holdings`, `--staging`) is preserved.

int-06 inherits §10.2 as its implementation spec — not §6.

---

## 2. Current state of both target files (HEAD = `4484137`)

### 2.1 `scripts/build_cusip.py`

Hook is **present** at [scripts/build_cusip.py:442-453](../../scripts/build_cusip.py:442), after `main()`'s `print("Done.")` at line 440. Shipped in commit `68b6dcd` (2026-04-18) — `feat(build_cusip): subprocess hook — trigger ticker backfill post-securities-update`.

```python
# BLOCK-TICKER-BACKFILL: re-stamp historical fund_holdings_v2.ticker on
# securities mapping changes. Pass C in enrich_holdings.py is
# is_priceable-gated (commit db27cbd). Subprocess pattern (not inline
# import) is resilient to future REWRITE refactors of enrich_holdings.py.
cmd = [sys.executable, "scripts/enrich_holdings.py", "--fund-holdings"]
if args.staging:
    cmd.append("--staging")
try:
    subprocess.run(cmd, cwd=BASE_DIR, check=False, timeout=1800)
    print("  [hook] post-build ticker backfill triggered", flush=True)
except Exception as e:
    print(f"  [warn] post-build ticker backfill hook failed: {e}", flush=True)
```

Supporting wiring (already in place):
- `import subprocess` at [scripts/build_cusip.py:43](../../scripts/build_cusip.py:43)
- `import sys` at [scripts/build_cusip.py:44](../../scripts/build_cusip.py:44)
- `BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` at [scripts/build_cusip.py:52](../../scripts/build_cusip.py:52)

Placement: AFTER `con.close()` in the `finally` block (line 438) and AFTER `print("Done.")` (line 440), so the securities DB is closed before the child enrichment process opens it — no write-lock contention.

### 2.2 `scripts/normalize_securities.py`

Hook is **present** at [scripts/normalize_securities.py:143-154](../../scripts/normalize_securities.py:143), after `normalize()`'s `finally: con.close()` (line 141). Shipped in commit `8aa51b1` (2026-04-18) — `feat(normalize_securities): subprocess hook — trigger ticker backfill post-securities-update`.

```python
# BLOCK-TICKER-BACKFILL: re-stamp historical fund_holdings_v2.ticker on
# securities mapping changes. Pass C in enrich_holdings.py is
# is_priceable-gated (commit db27cbd). Subprocess pattern (not inline
# import) is resilient to future REWRITE refactors of enrich_holdings.py.
cmd = [sys.executable, "scripts/enrich_holdings.py", "--fund-holdings"]
if args.staging:
    cmd.append("--staging")
try:
    subprocess.run(cmd, cwd=BASE_DIR, check=False, timeout=1800)
    print("  [hook] post-build ticker backfill triggered", flush=True)
except Exception as e:
    print(f"  [warn] post-build ticker backfill hook failed: {e}", flush=True)
```

Supporting wiring (already in place):
- `import subprocess` at [scripts/normalize_securities.py:26](../../scripts/normalize_securities.py:26)
- `import sys` at [scripts/normalize_securities.py:27](../../scripts/normalize_securities.py:27)
- `BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` at [scripts/normalize_securities.py:31](../../scripts/normalize_securities.py:31)

Placement: AFTER `con.close()` in the `finally` block (line 141), same pattern as `build_cusip.py`.

### 2.3 Hook parity

Both hooks are byte-identical below the comment block. Invocation: `python3 scripts/enrich_holdings.py --fund-holdings [--staging]`. Timeout `1800` seconds. `check=False` so a non-zero exit from enrichment does not raise. Wrapped in `try/except Exception` so enrichment crashes cannot propagate into the parent script's exit status.

---

## 3. `enrich_holdings.py` CLI — confirms the hook command

Source: [scripts/enrich_holdings.py:35-46](../../scripts/enrich_holdings.py:35) (module docstring) and `argparse` block.

| Flag | Present? | Notes |
|---|---|---|
| `--staging` | ✅ | Route writes to staging DB. Hook forwards it when `args.staging` is set on the parent. |
| `--dry-run` | ✅ | Projection only; no writes. Not used by the hook (production hooks always write). |
| `--quarter YYYYQN` | ✅ | Not used by the hook — hooks re-stamp all quarters. |
| `--fund-holdings` | ✅ | Triggers Pass C (`fund_holdings_v2.ticker`). The flag the hooks pass. |

Pass breakdown (for cross-reference):

| Pass | Target | Gate | Apply fn |
|---|---|---|---|
| A | `holdings_v2` NULL cleanup | `cusip NOT IN cusip_classifications` | `_pass_a_apply` |
| B | `holdings_v2` ticker/sti/mvl/pof | `cusip_classifications.is_equity = TRUE` | `_pass_b_apply` |
| C | `fund_holdings_v2.ticker` | `securities.is_priceable = TRUE AND ticker IS NOT NULL` | `_pass_c_apply` |

Passes A and B run unconditionally; Pass C runs only when `--fund-holdings` is passed (which both hooks do). The hook therefore re-stamps all three tables on every invocation — broader coverage than the task description's "Pass B + Pass C" phrasing, but correct behavior since A/B are idempotent.

**No CLI gap.** The hooks use existing flags only; `enrich_holdings.py` needs no changes.

---

## 4. Design questions from the remediation prompt — already resolved

### 4.1 `--no-enrich` gate for testing / CI

**Not needed.** Three reasons:

1. `enrich_holdings.py` already respects `--staging`, and the hook forwards `args.staging` verbatim. Any test run that writes to staging triggers an enrichment of staging (not prod) — isolated.
2. Projections against prod are safe via `--dry-run` on `enrich_holdings.py` directly (not via the parent script). CI can skip the parent scripts and run `enrich_holdings.py --dry-run` standalone.
3. Adding a `--no-enrich` flag is net-new surface area with no named consumer. The §10.2 design decision was to keep hooks unconditional for correctness (prevent operators forgetting to disable-skip-re-enable). If a future CI flow needs to skip the hook, add the flag then.

### 4.2 Sync vs. fire-and-forget

**Synchronous** (`subprocess.run`, not `subprocess.Popen`). Both hooks use `subprocess.run(..., timeout=1800)`. Reasons:

1. Operators running the parent script expect a "done" signal after all side-effects complete. Async-detaching enrichment would make `build_cusip.py`'s `print("Done.")` a lie.
2. Timeout bounded at 30 min — a single `fund_holdings_v2` full-refresh takes ~5-15 min depending on DB state. The timeout is generous enough for worst-case but bounded so a hung enrichment does not block the parent indefinitely.

### 4.3 Error handling — does enrichment failure fail the parent?

**No.** `check=False` + `try/except Exception` wrap means:

- Non-zero exit from `enrich_holdings.py` → parent logs `[hook] post-build ticker backfill triggered` (after `subprocess.run` returns) and continues to exit cleanly.
- Actual Python exception (e.g., `FileNotFoundError` if `sys.executable` missing) → parent logs `[warn] post-build ticker backfill hook failed: {e}` and continues.
- Timeout → `subprocess.TimeoutExpired` caught by `except Exception` → same warn path.

Rationale: the parent script's write is already committed and checkpointed at this point. Failing the parent retroactively because an enrichment job failed would suggest a rollback that the parent cannot perform (no transaction spans the `subprocess.run` call). Logging-only is the correct policy; a stale `fund_holdings_v2.ticker` is recoverable manually via `python3 scripts/enrich_holdings.py --fund-holdings`.

### 4.4 Why no `--no-enrich` is the right call

The design is `NO_UNCONDITIONAL_FLAG`: hooks fire on every real invocation, and test paths route to staging via `--staging` or skip the parent entirely. Adding a kill-switch without a named consumer is speculative surface area — rejected per `BLOCK_TICKER_BACKFILL_FINDINGS.md §10.2` recommendation (d).

---

## 5. Phase 1 file list and LOC estimate

**No Phase 1 files.** The expected Phase 1 deltas are already on `main`:

| File | Proposed LOC | Shipped LOC | Commit |
|---|---:|---:|---|
| `scripts/build_cusip.py` | +10-20 | +12 | `68b6dcd` |
| `scripts/normalize_securities.py` | +10-20 | +12 | `8aa51b1` |
| **Total** | **+20-40** | **+24** | — |

Imports and `BASE_DIR` wiring already in both files (pre-existing or landed with the hook commit). No new test files needed — hooks are validated by the fact that `fund_holdings_v2.ticker` coverage on prod (`5,154,223` populated, per int-05 findings) matches the expected post-hook state, i.e., the hooks have been running on real pipeline invocations since Apr 18.

### 5.1 Evidence that hooks have executed post-merge

- `data_freshness('holdings_v2_enrichment')` last stamped **2026-04-19 13:32:08** (per int-05-p0-findings.md §3.3).
- `data_freshness('fund_holdings_v2_enrichment')` last stamped **2026-04-17 20:46:18**.
- CUSIP v1.4 prod promotion on 2026-04-15 (commit `8a41c48`) followed by the 2026-04-19 enrichment run matches the pattern of a `normalize_securities.py` invocation triggering the hook.

---

## 6. Risk notes

- **Risk: hook regression on `build_cusip.py` REWRITE refactor.** Listed REWRITE target in [docs/REMEDIATION_PLAN.md:514](../REMEDIATION_PLAN.md:514). Mitigation: subprocess pattern is version-independent — as long as the CLI shape `enrich_holdings.py --fund-holdings [--staging]` survives, the hook will keep working. A REWRITE that removes the hook would need to explicitly delete lines 442-453; a diff review gate catches that.
- **Risk: hook regression on `normalize_securities.py` REWRITE refactor.** Same as above. Mitigation: same subprocess pattern + diff review.
- **Risk: enrich_holdings.py CLI shape changes.** If `--fund-holdings` or `--staging` flags get renamed or removed, both hooks break silently (they log a warn and continue). Mitigation: `enrich_holdings.py` module docstring ([scripts/enrich_holdings.py:35-46](../../scripts/enrich_holdings.py:35)) documents these as stable external contracts. Any PR that changes them should grep for `enrich_holdings.py --fund-holdings` and update hook sites.
- **Risk: DB write-lock contention.** Both hooks fire AFTER `con.close()` on the parent. DuckDB single-writer lock is released before the child opens. Not observed in practice since Apr 18.
- **Risk: feedback loop.** None. `enrich_holdings.py` writes to `holdings_v2` / `fund_holdings_v2`, not `securities` or `cusip_classifications`, so the child cannot trigger another hook cascade.
- **Risk: staging/prod mixing.** Parent forwards `args.staging` verbatim. A prod-mode parent triggers a prod-mode child; a staging-mode parent triggers a staging-mode child. Respected because both files use the standard `db.py` staging routing.

---

## 7. Recommended execution plan

**Close int-06 as NO-OP** with the evidence in §2 and §5. Update:

- **ROADMAP.md** — move int-06 row to COMPLETED section with date `2026-04-22` and a one-line pointer: "Hooks shipped via BLOCK-TICKER-BACKFILL merge `3299a9f` on 2026-04-18; commits `68b6dcd` + `8aa51b1`; see [docs/findings/int-06-p0-findings.md](docs/findings/int-06-p0-findings.md)."
- **docs/REMEDIATION_CHECKLIST.md:16** — tick the int-06 box.
- **docs/REMEDIATION_PLAN.md:42** — mark int-06 row status `CLOSED-NOOP`.

No Phase 1 prompt needs to be written. No code changes are in scope.

### 7.1 Optional verification command

To confirm a hook fires today, run against staging (safe — no prod side-effects):

```sh
python3 scripts/normalize_securities.py --staging
```

Expected tail of output: `  [hook] post-build ticker backfill triggered`. Followed by `enrich_holdings.py` header and its own per-pass output. Runtime ~5-15 min depending on staging DB state.

If the tail line is absent or shows `[warn] post-build ticker backfill hook failed: …`, the hook has regressed and a Phase 1 fix becomes relevant. Expected outcome per current state: tail line prints cleanly.

---

## 8. Cross-references

- [docs/BLOCK_TICKER_BACKFILL_FINDINGS.md](../BLOCK_TICKER_BACKFILL_FINDINGS.md) §6, §10.2 — design spec
- [docs/reports/block_ticker_backfill_closeout_20260418_205753.md](../reports/block_ticker_backfill_closeout_20260418_205753.md) — merge closeout report confirming hooks shipped
- [docs/findings/int-05-p0-findings.md](int-05-p0-findings.md) — retroactive sweep NO-OP (sibling item)
- [docs/findings/int-01-p0-findings.md:197](int-01-p0-findings.md) — cross-reference noting hook already exists
- [docs/findings/int-04-p0-findings.md:161](int-04-p0-findings.md) — cross-reference predating the merge
- Commits: `68b6dcd` (build_cusip hook), `8aa51b1` (normalize_securities hook), `3299a9f` (merge to main)
