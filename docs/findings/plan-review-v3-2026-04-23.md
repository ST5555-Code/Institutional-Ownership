# Plan Review v3 — 2026-04-23

**Session:** `plan-review-v3-2026-04-23`
**Mode:** Read-only critique of v3's CHANGES from v2.
**Subject:** `docs/plans/2026-04-23-phase-b-c-execution-plan.md` (commit `727e5aa`).
**Scope:** Sections new or substantially changed since v2 (per plan §10). Confirmed-in-v2 sections not re-verified.

---

## §1 Summary

| Category | Count |
|---|---|
| Critical | 1 |
| Recommended revisions | 5 |
| Minor corrections | 4 |
| Questions for Serge | 2 |

Net read: v3 closes the v2 gaps (B2.5 added, §4 fresh, V-Q3 co-lands named, R1/R3/R5/R6/M1/M2/M3 addressed). The new content introduces one critical (C1 prompt enumeration won't work as written) and several gaps in B2.5 co-land scope. None block adoption; all are tractable in a single revision pass.

---

## §2 Critical issues

### C1. Phase C1 prompt enumeration won't surface any tables

`docs/plans/2026-04-23-phase-b-c-execution-plan.md:493` (Phase 2 of the C1 prompt) says:

```
> grep "^### " docs/canonical_ddl.md
Extract the list of tables documented.
```

`docs/canonical_ddl.md` uses **`## ` (H2)** headings, not `### ` (H3). The grep returns zero rows (verified). The prompt's enumeration step silently fails and the session would have no table list to feed Phase 3.

Compounding issue: canonical_ddl.md is a **drift report**, not a per-table catalog. Several headings group multiple tables (e.g., `## 6. filings, filings_deduped, raw_* — ALIGNED`, `## 11. adv_managers, lei_reference, cik_crd_* — ALIGNED`). Even with the right grep, the result is not a clean table list — the session would need to parse comma-separated names out of headings.

**Fix options:**
- (a) Change `^### ` → `^## ` and post-process headings to split comma-separated lists.
- (b) Better: enumerate from `scripts/pipeline/registry.py` `DATASET_REGISTRY` (authoritative, single source of truth, already used by `reference_tables()`/`merge_table_keys()`/`unclassified_tables()`). Cross-check against `SHOW TABLES`.

See also Q2.

---

## §3 Recommended revisions

### R1. Phase B2.5 §5.2 omits `other_managers` registry owner update

[scripts/pipeline/registry.py:175](scripts/pipeline/registry.py:175) declares:

```python
"other_managers": DatasetSpec(
    layer=3, owner="scripts/load_13f.py",
    ...
)
```

[scripts/load_13f_v2.py:719](scripts/load_13f_v2.py:719) writes `other_managers` (verified: `INSERT INTO other_managers`). Plan §5.2 only co-lands owner updates for `filings` (L113) and `filings_deduped` (L118). `other_managers` is left pointing at V1 and is **not a raw_\*** entry, so it doesn't get cleaned up in B3 either (B3 §7.2 item 8 only removes the three raw_\* L1 specs).

**Fix:** add `registry.py:175 other_managers owner → "scripts/load_13f_v2.py"` to §5.2 list. Update §5.6 phase 3.5 prompt likewise.

### R2. Phase B2.5 doesn't address `quarterly-update` Make target orchestration

[Makefile:80-100](Makefile:80) `quarterly-update` target invokes `$(MAKE) load-13f` **without** `QUARTER=`. Today V1 supports no-quarter mode (full reload). After cutover, V2 requires `--quarter` (verified at [scripts/load_13f_v2.py:762](scripts/load_13f_v2.py:762) `required=True`) — the cycle entry point will crash on first `make quarterly-update` post-merge.

Plan §5.2 line 590 mentions "confirm Makefile always passes one in cycle context" but doesn't prescribe a fix, and §5.6 phase 5 smoke test only checks `make -n load-13f QUARTER=2025Q4` (the standalone target, not the cycle entry). Help text on Makefile:45 says `QUARTER=YYYYQn optional`, which would also need updating.

**Fix options:**
- (a) Update `quarterly-update` to require `QUARTER=` and pass it through (plus update `make help`).
- (b) Wrap V2 invocation with quarter-detection helper (compute current quarter when not supplied).
- Either way, name the chosen approach in §5.2/§5.6 and remove the "load-13f QUARTER optional" line from Makefile help.

### R3. Wrong cross-reference for V10 fix location (§2.1.1 + §2.6 phase 4)

Plan line 134 (§2.1.1 Mitigation 2):
> "This is independent from V10 grouped-row fix (which lives in `line_kind()` / `extract_table_title()` — **§7.2 scope**)."

Plan line 215 (§2.6 phase 4 prompt):
> "Note: this is INDEPENDENT of V10 grouped-row fix (**§7.2**). Do not try to fix V10 here."

§7.2 is the **B3 DB cleanup** scope. The V10 fix actually lives in **§8.2** (`audit-ticket-numbers-refinement-v10`, lines 918-924). Both references need to flip §7.2 → §8.2. The R1 correction successfully decoupled M2 from V10 conceptually, but the section pointer leaks readers into the wrong section.

### R4. build_managers.py upstream comment also at L12 (not just L228)

Plan §5.2 line 598 + §5.6 phase 3.4 say "near line 228 per V3, but use semantic match". `grep -n "load_13f" scripts/build_managers.py` returns **two** hits:
- L12 — module docstring "(Requires pipeline/load_adv.py and load_13f.py to have run first)"
- L228 — `("filings_deduped", "load_13f.py"),` upstream tuple

The prompt's semantic search ("comment about filings_deduped or upstream producer") would catch L228 but might miss L12. Either name both explicitly, or broaden the semantic anchor to "any load_13f.py reference".

### R5. B2.5 §5.4 grep gate is over-permissive

The "after completing" gate at §5.4:
```
grep -rn "load_13f.py" Makefile scripts/ returns only:
  - Reference in scripts/load_13f.py itself
  - Reference in scripts/load_13f_v2.py docstring/comments
  - Reference in documentation/comments
```

This is hard to evaluate mechanically (any `.py` containing the substring as a comment passes). Tighten: enumerate the **specific** acceptable files (V1 file path, V2 file path, build_managers.py:12 docstring if intentionally retained) and require a literal diff of expected vs actual matches. As written, the gate would silently pass even if `update.py` or `benchmark.py` retained a stale invocation.

---

## §4 Minor corrections

### M1. `scripts/update.py` — actual line is L74, plan says L75

[scripts/update.py:72-78](scripts/update.py:72) — `"load_13f.py"` is at **L74** (entry inside the `steps = [...]` list). Plan §5.2 line 592 + §5.6 phase 3.2 say L75. The prompt instructs "or semantically equivalent line", so the escape hatch covers this. Off-by-one only.

### M2. Owner string convention: "manual seed" vs "manual"

Plan §3.1 / §3.6 specifies `owner="manual"` for `migrate_batch_3a.py` revert. Existing convention in registry: [scripts/pipeline/registry.py:317](scripts/pipeline/registry.py:317) uses `owner="manual seed"` for `peer_groups` (analogous one-shot seeder). Suggest `"manual seed"` to match precedent.

### M3. queries.py contains stale "fund_holdings" prose comments

Comments at [scripts/queries.py](scripts/queries.py) L264, L356, L571, L2092, L2355, L2691, L2940, L3034 reference "fund_holdings" when they semantically mean `fund_holdings_v2` (verified: no live SQL `FROM fund_holdings` in queries.py — all SQL is on `_v2`). Plan §7.2 doesn't include these. Cosmetic; not a functional gap, but they'd flag as ghost references in any future audit.

### M4. B2.5 smoke validation is dry-run only

Plan §5.6 phase 5 runs `make -n load-13f QUARTER=...` (Make dry-run, doesn't execute) plus `pytest tests/pipeline/test_load_13f_v2.py` (tests the **class**, not the new CLI `--auto-approve` chain). The actual cutover code path — `make load-13f` → `python load_13f_v2.py --quarter X --auto-approve` against staging or fixture DB — isn't exercised before PR merge. The single-line-revert mitigation is real, but a 60-second `--auto-approve` smoke against the fixture DB would catch any CLI wiring issues before they hit Q1 cycle.

---

## §5 Questions for Serge

### Q1. Calendar runway for B1 → B2 → B2.5 before Q1 2026 cycle

Plan §1 / §5.3 require B2.5 to land **before Q1 2026 13F cycle starts**. Q1 2026 13F filings are due ~45 days after Mar 31 → mid-May 2026. Today is 2026-04-23. Three sequential gated PRs in ~3 weeks (B1 must merge before B2, which must merge before B2.5).

Is the calendar feasible as-stated, or do you want to (a) combine B2 + B2.5 into one session (file-disjoint enough?), (b) start B2.5 in parallel with B1 (only doc-overlap), or (c) accept slipping B2.5 into the Q1 cycle and run cycle on V1 one more time?

### Q2. C1 enumeration: canonical_ddl.md headings vs DATASET_REGISTRY

Per C1 critical above, the canonical_ddl.md heading-grep won't yield a clean per-table list. Do you want C1's prompt to enumerate from `DATASET_REGISTRY` instead (authoritative, single-source-of-truth, already shaped per-table), with canonical_ddl.md only consulted for migration-history color? Or keep canonical_ddl.md as the scope anchor and fix the enumeration to handle the multi-table headings?
