# obs-03-p0 — Phase 0 findings: market `impact_id` allocation hardening

_Prepared: 2026-04-20 — branch `remediation/obs-03-p0` off main HEAD `4dd676b`._

_Tracker: [docs/REMEDIATION_PLAN.md:86](docs/REMEDIATION_PLAN.md:86) Theme 2 row `obs-03`; [docs/REMEDIATION_CHECKLIST.md:50](docs/REMEDIATION_CHECKLIST.md:50) Batch 2-A. Audit refs: [docs/SYSTEM_AUDIT_2026_04_17.md:327](docs/SYSTEM_AUDIT_2026_04_17.md:327) MAJOR-13 / P-04; [docs/SYSTEM_ATLAS_2026_04_17.md:303](docs/SYSTEM_ATLAS_2026_04_17.md:303); [docs/findings/2026-04-17-codex-review.md:40](docs/findings/2026-04-17-codex-review.md:40); [docs/findings/2026-04-17-codex-review.md:112](docs/findings/2026-04-17-codex-review.md:112)._

Phase 0 is investigation only. No code writes and no DB writes were performed. The prod database was read-only; all SQL below was executed through `duckdb.connect(..., read_only=True)`.

---

## §1. `ingestion_impacts` writer inventory

Exact-string search `INSERT INTO ingestion_impacts` across the repo returns **four call sites** in `scripts/`. They decompose into two allocation regimes.

### §1.1 Allocating-path (assigns a new `impact_id`)

| # | File:line | Helper / raw SQL | Allocator | Notes |
|---|---|---|---|---|
| 1 | [scripts/pipeline/manifest.py:190](scripts/pipeline/manifest.py:190) | `write_impact(...)` wrapper | `_next_id(con, 'ingestion_impacts', 'impact_id')` → `SELECT COALESCE(MAX(impact_id),0)+1` | Canonical entry point. All active fetchers go through here. |
| 2 | [scripts/pipeline/shared.py:450](scripts/pipeline/shared.py:450) | `write_impact_row(...)` wrapper | DuckDB `DEFAULT nextval('impact_id_seq')` via `... RETURNING impact_id` | **Bypass.** Rgrep for callers: zero (`write_impact_row(` only matches the definition). Dead-but-reachable. |

Only callers of `write_impact` (helper 1):

- [scripts/fetch_market.py:75](scripts/fetch_market.py:75), [:731](scripts/fetch_market.py:731) — per-ticker impact per batch.
- [scripts/fetch_nport_v2.py:80](scripts/fetch_nport_v2.py:80), [:276](scripts/fetch_nport_v2.py:276), [:709](scripts/fetch_nport_v2.py:709) — per-quarter (DERA ZIP) + per (series, report_month).
- [scripts/fetch_13dg_v2.py:63](scripts/fetch_13dg_v2.py:63), [:532](scripts/fetch_13dg_v2.py:532) — per (filer_cik, subject_cusip, accession).
- [scripts/fetch_dera_nport.py:657](scripts/fetch_dera_nport.py:657), [:737](scripts/fetch_dera_nport.py:737) — per (series, report_month) + `DELETE ... WHERE manifest_id <> ?` cleanup for cross-ZIP amendments.

No caller of `shared.write_impact_row` exists today. The risk is latent: any future caller would inherit the sequence-drift bug that commit [`11a35e9`](https://github.com/ST5555-Code/13f-ownership/commit/11a35e9) fixed in `write_impact`, because `impact_id_seq.last_value=192` is still ~40,653 behind `MAX(impact_id)=40,845` (see §3).

### §1.2 Mirror-path (copies an already-allocated `impact_id`)

| # | File:line | Shape | Allocator role |
|---|---|---|---|
| 3 | [scripts/promote_nport.py:135-144](scripts/promote_nport.py:135) | `INSERT INTO ingestion_impacts SELECT im.* FROM im WHERE NOT EXISTS (...)` | Copies staging rows into prod with the staging-assigned `impact_id` verbatim, gated by `(manifest_id, unit_type, unit_key_json)` anti-join. |
| 4 | [scripts/promote_13dg.py:259-268](scripts/promote_13dg.py:259) | Same shape. | Same semantics. |

Both are `INSERT ... SELECT` from a `register()`-ed pandas frame (`prod_con.register('im', im_rows)`), so the DuckDB storage layer takes `impact_id` as a user-supplied value rather than invoking `nextval`. This is exactly the mechanism that caused `impact_id_seq.last_value` to drift 32,559 behind `MAX(impact_id)` at the time of the 2026-04-16 crash (see commit [`11a35e9`](https://github.com/ST5555-Code/13f-ownership/commit/11a35e9) message).

### §1.3 Non-allocating writes

For completeness, `UPDATE ingestion_impacts ...` statements (no PK allocation risk): [scripts/fetch_market.py:746](scripts/fetch_market.py:746), [scripts/fetch_nport_v2.py:789](scripts/fetch_nport_v2.py:789), [scripts/fetch_dera_nport.py:813](scripts/fetch_dera_nport.py:813), [scripts/promote_nport.py:465](scripts/promote_nport.py:465)/[:480](scripts/promote_nport.py:480), [scripts/promote_13dg.py:150](scripts/promote_13dg.py:150). These mutate `load_status` / `promote_status` / `promoted_at` and are not in scope for the allocator redesign; they are listed here only so the reader can see the full `ingestion_impacts` write surface in one place.

Admin surface: [scripts/admin_bp.py:260-285](scripts/admin_bp.py:260) launches `fetch_*.py` scripts via `subprocess.Popen` under a `pgrep` guard. It does not write `ingestion_impacts` itself. The CODEX-flagged TOCTOU race ([docs/findings/2026-04-17-codex-review.md:111](docs/findings/2026-04-17-codex-review.md:111)) between pgrep and spawn can only double-launch a fetcher; DuckDB's per-file write lock would fail the loser with a "Conflicting lock" IOException (see `fetch_nport_v2_crash.log` 2026-04-14 13:04, cited at [docs/SYSTEM_ATLAS_2026_04_17.md:304](docs/SYSTEM_ATLAS_2026_04_17.md:304)). That is a loud failure, not a silent duplicate-PK crash.

---

## §2. Crash reproduction and one-writer invariant

### §2.1 What actually happened on 2026-04-16 15:28:59

The audit trail is in [docs/SYSTEM_ATLAS_2026_04_17.md:303](docs/SYSTEM_ATLAS_2026_04_17.md:303): `ConstraintException: Duplicate key "impact_id: 191" ...`. The physical crash log `logs/fetch_market_crash.log` is **no longer present in the repo or worktree** (`find / -name fetch_market_crash*` returns nothing; the Atlas snapshot is the canonical reproduction artifact). The obs-03-p0 prompt's reference to `logs/fetch_market_crash.log:35-49` cannot be verified against the physical log today; the timeline is instead reconstructed from (a) the crash excerpt in Atlas §3.4, (b) the fix commit [`11a35e9`](https://github.com/ST5555-Code/13f-ownership/commit/11a35e9) timestamp 2026-04-16 16:29:28, and (c) the current prod `ingestion_impacts` row distribution (§3 below).

**Mechanism.** Three events preceded the crash:

1. `fetch_13dg_v2.py` wrote three impact rows on 2026-04-14 04:02:43 via `write_impact` using `DEFAULT nextval('impact_id_seq')`. That advanced the sequence to `last_value=193`. Prod `impact_id` range for 13DG today is 191..193 (§3.1).
2. `promote_nport.py` mirrored 21,244 NPORT impacts from staging into prod via `INSERT INTO ingestion_impacts SELECT im.* FROM im` ([scripts/promote_nport.py:135](scripts/promote_nport.py:135)). Those rows carried staging-assigned `impact_id`s in the range 194..32,751. Because the INSERT supplied explicit PK values, the prod sequence was **not** advanced. `impact_id_seq.last_value` stayed at ~192.
3. `fetch_market.py` launched 2026-04-16 15:27:47. It called `write_impact_row` → `DEFAULT nextval('impact_id_seq')`. The sequence returned 1, 2, 3, … (visible in prod: 190 MARKET impacts with `impact_id < 1000`, §3.1). Somewhere around `nextval()=191` the DuckDB PK enforcer saw a collision with the 13DG row already present at 191 and threw the `ConstraintException`.

**The fix** ([`11a35e9`](https://github.com/ST5555-Code/13f-ownership/commit/11a35e9), 2026-04-16 16:29) replaced `DEFAULT nextval` with `_next_id(con, table, pk_col)` at [scripts/pipeline/manifest.py:27-51](scripts/pipeline/manifest.py:27) and [:157-193](scripts/pipeline/manifest.py:157). The restart at 16:30:43 immediately allocated from `MAX(impact_id)+1 = 32,752`, skipping the collision zone. Prod row distribution at MARKET id ≥ 10000 confirms this (§3.1, third bucket).

### §2.2 Is the one-writer invariant actually held?

**Yes, strictly, by DuckDB's own storage.** DuckDB uses a per-file OS-level advisory write lock; a second `duckdb.connect(path)` call against an already-RW-open file returns `IOException: Could not set lock on ... (Conflicting lock, PID ...)` (the `fetch_nport_v2_crash.log` entry above is precisely this). That makes cross-process concurrent RW on the same DB file impossible by construction, not by convention.

- `fetch_market.py` uses **no threading, no multiprocessing, no subprocess**. `grep -n "threading\|ThreadPool\|concurrent\.futures\|multiprocessing\|subprocess"` in `scripts/fetch_market.py` returns zero hits. Connections are opened and closed per batch ([scripts/fetch_market.py:609](scripts/fetch_market.py:609), [:707](scripts/fetch_market.py:707)) on a single main thread.
- `admin_bp.py` rejects a second invocation of the same fetcher via `pgrep` ([scripts/admin_bp.py:270-272](scripts/admin_bp.py:270)). A TOCTOU race could double-launch, but the second instance would hit DuckDB's write lock, not the PK, so that race is a noisy availability problem and not an impact_id collision path.
- `fetch_nport_v2.py` already documents lock contention against staging as a live concern ([CODEX 3c, docs/findings/2026-04-17-codex-review.md:113](docs/findings/2026-04-17-codex-review.md:113)).

**`_next_id(con, table, pk_col)` is also transactionally safe within its owning connection.** The `SELECT MAX(...)+1` and the subsequent `INSERT` run on the same `con` in sequence and see a consistent MVCC snapshot until commit; a second write on the same connection cannot interleave because Python executes the two calls serially.

**Therefore:** the one-writer invariant holds *today* for every allocating writer. The fragility is structural, not current:

- Any future caller that goes direct to `INSERT INTO ingestion_impacts` with `DEFAULT nextval('impact_id_seq')` re-introduces the 2026-04-16 class of bug, because `impact_id_seq.last_value` is still 192 (§3.2) and every promote-mirror run continues to widen the drift.
- The dead-but-reachable `scripts/pipeline/shared.py:430` `write_impact_row` is exactly that future caller in waiting.
- obs-01 (N-CEN + ADV manifest registration, [docs/REMEDIATION_PLAN.md:84](docs/REMEDIATION_PLAN.md:84)) will add two new allocating writers. If obs-01 code uses `manifest.write_impact` the invariant holds; if it forks a new direct-INSERT path (e.g. for bulk-insert efficiency) the bug comes back.
- obs-04 (13D/G retro-mirror, [docs/REMEDIATION_PLAN.md:87](docs/REMEDIATION_PLAN.md:87)) will bulk-insert thousands of historical impact rows. Bulk paths are the classic place where engineers reach past per-row helpers for performance.

---

## §3. Current `ingestion_impacts` state (prod, read-only SQL)

All figures from `duckdb.connect('data/13f.duckdb', read_only=True)` on 2026-04-20.

### §3.1 Per-source counts and PK ranges

| source_type | impacts | min(impact_id) | max(impact_id) | manifest rows |
|---|---:|---:|---:|---:|
| NPORT | 21,244 | 194 | 32,751 | 21,252 |
| MARKET | 8,284 | 1 | 40,845 | 84 |
| 13DG | 3 | 191 | 193 | 3 |
| **Total** | **29,531** | 1 | 40,845 | 21,339 |

No duplicate `impact_id` anywhere in prod (`SELECT impact_id, COUNT(*) FROM ingestion_impacts GROUP BY 1 HAVING COUNT(*) > 1` → empty). The PK constraint is currently honored.

MARKET `impact_id` distribution bucket view:

| bucket | count | earliest created_at | latest created_at |
|---|---:|---|---|
| `id < 1000` | 190 | 2026-04-16 15:27:47.844 | 2026-04-16 15:28:59.195 |
| `10000 ≤ id < 33000` | 248 | 2026-04-16 16:30:43.858 | 2026-04-16 16:33:05.943 |
| `id ≥ 33000` | 7,846 | 2026-04-16 16:33:05.943 | 2026-04-16 23:27:34.638 |

The first bucket is the pre-crash pre-fix window. The second bucket begins 14 minutes after the fix commit and starts at `MAX(impact_id)+1`, which at that moment sat just above the NPORT ceiling 32,751. The third bucket extends past 33,000 as NPORT promotes continued during the evening.

### §3.2 Sequence drift

```
impact_id_seq.last_value   = 192      MAX(impact_id)   = 40,845   drift = 40,653
manifest_id_seq.last_value = 3        MAX(manifest_id) ≈ 26,935   drift = ~26,932
```

Both sequences are effectively abandoned by current code. They still exist as DDL defaults on `impact_id` / `manifest_id`, but `_next_id` is the only allocator that actually runs. Any path that triggers `DEFAULT nextval` will start at 193 / 4 and collide within one INSERT.

### §3.3 Gaps in allocated `impact_id` space

`LAG()`-based gap scan: **9 gap regions, 11,314 missing ids in the range 1..40,845**. These correspond to:

- `193 → 194` boundary (13DG/NPORT handoff).
- `32,751 → ~33,001` boundary (end-of-NPORT-mirror to post-fix MARKET restart window).
- Several smaller gaps inside the MARKET `id ≥ 33,000` range, consistent with the per-batch `_next_id` call pattern where MARKET fetchers interleaved with NPORT promotes (each promote carried fresh staging impact_ids into the same prod space, pushing MARKET's next `MAX+1` forward by the imported batch size).

Gaps are cosmetic — they do not break audit queries, they only waste PK space. Not a defect.

### §3.4 Sources not yet in manifest

`SELECT DISTINCT source_type FROM ingestion_manifest` returns **only** `{NPORT, 13DG, MARKET}`. N-CEN and ADV are still absent (confirms [docs/SYSTEM_AUDIT_2026_04_17.md:327](docs/SYSTEM_AUDIT_2026_04_17.md:327) MAJOR-9 / P-05 and is the scope of obs-01). That matters for obs-03 because whatever allocator design we pick must be live before obs-01 lands its first N-CEN / ADV impact row, otherwise obs-01 re-introduces the direct-INSERT pattern under time pressure.

---

## §4. Cross-item awareness

### §4.1 obs-01 (N-CEN + ADV manifest registration)

- New writers: [scripts/fetch_ncen.py](scripts/fetch_ncen.py) and [scripts/fetch_adv.py](scripts/fetch_adv.py) will begin calling into the control plane. Per [docs/REMEDIATION_PLAN.md:84](docs/REMEDIATION_PLAN.md:84), obs-01 also touches `scripts/migrations/001_pipeline_control_plane.py` for new `source_type` values.
- Allocator impact: each new fetcher must use the *same* allocator that the current fetchers use. Any hand-rolled `MAX+1` repetition in obs-01 would reintroduce the same transactional-coupling risk that obs-03 exists to remove.
- Parallelism note: [docs/REMEDIATION_PLAN.md:100](docs/REMEDIATION_PLAN.md:100) states obs-01 ∥ obs-03 is parallel-safe because files are disjoint. That is true for the *write* phase; the Phase 1 obs-03 allocator must be **strictly additive** (keep `write_impact` API-compatible) so obs-01 can adopt it without waiting for obs-03 to finish.

### §4.2 obs-04 (13D/G retro-mirror)

- Shape: per [docs/REMEDIATION_PLAN.md:87](docs/REMEDIATION_PLAN.md:87), obs-04 will retro-mirror pre-v2 13D/G history into `ingestion_impacts` via `scripts/promote_13dg.py`. The existing mirror path is `INSERT INTO ingestion_impacts SELECT im.* FROM im` with staging-assigned PKs ([scripts/promote_13dg.py:259](scripts/promote_13dg.py:259)).
- Allocator impact: the bulk insert carries impact_ids sourced from staging's own allocator. If staging's allocator and prod's allocator ever disagree (e.g. staging runs the old sequence while prod runs `_next_id`), the mirror path can drop collisions into prod.
- Requirement for Phase 1: the centralized allocator must expose a **bulk allocation primitive** — "reserve N contiguous ids starting at `MAX+1`" — so obs-04's retro-mirror can pre-allocate prod ids and rewrite the staging frame before insert, rather than trusting staging PKs.

### §4.3 Interactions with ongoing audit items

- [docs/findings/2026-04-17-codex-review.md:96-98](docs/findings/2026-04-17-codex-review.md:96) — `promote_nport.py` / `promote_13dg.py` are not enclosed in `BEGIN TRANSACTION` during delete+insert. An allocator change that widens the PK write window must respect the same transaction semantics the mirror paths already (imperfectly) assume. Our centralization must not add a second non-atomic step.
- [docs/findings/2026-04-17-codex-review.md:112](docs/findings/2026-04-17-codex-review.md:112) — CODEX explicitly states `_next_id` is only safe under the one-writer invariant and flags that invariant has been violated in production operation at least once. Our Phase 1 must make the violation *impossible*, not just *unlikely*.

---

## §5. Proposed Phase 1 centralization

### §5.1 Design requirements

1. **Single entry point.** Every `INSERT INTO ingestion_impacts` in the repo must resolve to one allocator function. No helper module (`shared.py`, future `bulk.py`, admin handlers) may implement its own.
2. **Transactional coupling.** Allocation and INSERT must be atomic from the caller's perspective. If the INSERT aborts, the next allocation must still succeed and not leak the id.
3. **Cross-process safety, defense in depth.** Even though DuckDB's per-file lock guarantees cross-process mutual exclusion today, the allocator must additionally hold an explicit advisory file lock (`fcntl.flock` on a sibling `.ingestion_lock` file) for the read–write allocation window. This makes the invariant self-enforcing: a future engineer who opens a second DuckDB handle in attached / readonly mode cannot drift in.
4. **Sequence retirement.** `impact_id_seq` and `manifest_id_seq` are already vestigial (drift 40k+). Phase 1 should either (a) drop the `DEFAULT nextval` clauses and remove the sequences, forcing every writer through the allocator, or (b) re-home the sequences under the allocator's control. Option (a) is simpler and matches current behavior.
5. **Bulk primitive.** Expose `reserve_impact_ids(con, n: int) → (start, end)` for obs-04 bulk mirror. Callers rewrite their staging frame's `impact_id` column to `range(start, end+1)` before insert.
6. **API-compatible.** Keep `write_impact(...)` signature intact. Drop-in replacement for existing fetcher code. New functions are additive.
7. **Observable.** Every allocation writes one audit row (or log line) with `(table, start, end, caller, pid, run_id)`. This is what closes the "did anyone bypass the allocator" question going forward.

### §5.2 Proposed module shape

- Move `_next_id` out of `scripts/pipeline/manifest.py` (currently lines 27-51) into a dedicated `scripts/pipeline/id_allocator.py` and rename to `allocate_id`. Keep `manifest.py` as the call-site only.
- In `id_allocator.py`:
  - `allocate_id(con, table, pk_col) → int` — single-id allocation. Takes out a `fcntl.flock` on `<db_path>.ingestion_lock`, runs `SELECT COALESCE(MAX(pk), 0)+1`, yields the value, releases lock on return. Caller INSERTs inside the same `con` immediately after. `_ID_TABLES` allow-list stays.
  - `reserve_ids(con, table, pk_col, n) → range` — bulk primitive for obs-04. Same lock discipline; returns `range(start, start+n)`. Caller rewrites its batch frame before `INSERT ... SELECT`.
  - `require_allocator_for_table(table)` — a runtime guard that, when imported at module load in any file touching `ingestion_impacts`, logs a `WARN` if that file's source also contains `DEFAULT nextval` or a literal `INSERT INTO ingestion_impacts` that does not sit within this module. Cheap, detects the next bypass.
- Delete `scripts/pipeline/shared.py:430-455` `write_impact_row`. No callers; removing it prevents accidental adoption.
- Migrate `promote_nport.py:135-144` and `promote_13dg.py:259-268` to go through `reserve_ids` + frame rewrite, not the staging-PK copy. This closes the sequence-drift root cause permanently — prod never sees a staging-assigned PK again.
- Drop `DEFAULT nextval('impact_id_seq')` / `DEFAULT nextval('manifest_id_seq')` from the DDL in `scripts/migrations/001_pipeline_control_plane.py:90, :54` via a new migration (additive: `ALTER TABLE ... ALTER COLUMN ... DROP DEFAULT`). Keep the sequences in the DB briefly for rollback safety, then drop them in a follow-up.

### §5.3 Migration path for existing callers

| Caller | Today | After Phase 1 | Breakage risk |
|---|---|---|---|
| `manifest.write_impact` | `_next_id` inline | `id_allocator.allocate_id` inline | None — same semantics, same signature. |
| `fetch_market.py` / `fetch_nport_v2.py` / `fetch_13dg_v2.py` / `fetch_dera_nport.py` | `write_impact(...)` | Unchanged | None. |
| `shared.write_impact_row` | `DEFAULT nextval` via `RETURNING` | Deleted | None — no callers. |
| `promote_nport.py` / `promote_13dg.py` mirror | Copy staging PKs | `reserve_ids(n)` + frame rewrite | Requires staging + prod to re-promote one run to validate (scope of Phase 2). |
| obs-01 N-CEN / ADV (future) | — | `write_impact(...)` | None. obs-01 adopts the existing fetcher pattern. |
| obs-04 retro-mirror (future) | — | `reserve_ids(n)` + frame rewrite | Depends on obs-03 Phase 1 shipping first. |

### §5.4 Test plan for Phase 1 (concurrency suite)

1. **Unit:** `allocate_id` returns `MAX+1`, monotonically increasing, across successive calls with a shared connection.
2. **Unit:** `reserve_ids(con, table, pk_col, 1000)` returns a contiguous range and advances `MAX` by 1000 after the caller INSERTs.
3. **Two-process race simulation:** spawn two `python3 -c` subprocess workers, each opens prod in RW mode. DuckDB's own lock will let only one start; the other must fail with `IOException` — not with duplicate PK. Capture both outcomes and assert.
4. **Advisory-lock stress:** mock `fcntl.flock` to hold for 5s on worker A; worker B's `allocate_id` blocks and then succeeds with a post-A id. Asserts the defense-in-depth holds even in the unlikely case that DuckDB's own lock is ever misconfigured (e.g. attached DB mode).
5. **Promote replay (obs-04 hazard):** pre-populate a staging run with 2,000 impact rows whose PKs collide with prod's `MAX(impact_id)` range; run the new mirror path; assert zero `ConstraintException` and post-mirror PK continuity.
6. **Integration smoke:** run `fetch_market.py --test` (10 tickers, staging) back-to-back twice, then `promote_nport.py` (if a pending run is available), and assert MAX(impact_id) strictly increases and no sequence is ever read by `nextval`. Covered by the existing `.github/workflows/smoke.yml` contract; this adds one more step.

### §5.5 Out of scope for Phase 1

- `ingestion_manifest` already shares the same `_next_id` allocator (same file, same logic). Phase 1 should migrate it alongside `ingestion_impacts` for symmetry — same code, same tests — but any behavior-changing work on manifest grain belongs to obs-01 / obs-04, not obs-03.
- Atomicity of the surrounding promote mirror (CODEX `promote_nport.py` / `promote_13dg.py` non-transactional sequences) is a separate item (int-style transaction-wrapping work, not observability). Phase 1 must not regress it, but does not fix it.

---

## §6. Open questions for Phase 1

1. **Bulk primitive granularity.** Should `reserve_ids` take a single `n` (current proposal) or a pre-built frame whose length it infers? Frame-first is ergonomic for obs-04; `n`-first is simpler. Default to `n` and let obs-04 decide.
2. **Fcntl on macOS / WSL.** Local dev is macOS; deploy target is Linux (per [docs/docs/deployment.md](docs/docs/deployment.md)). `fcntl.flock` behaves identically, but the sibling lock file path must be on the same filesystem as `13f.duckdb`. Confirm `data/.ingestion_lock` as the canonical path.
3. **Sequence removal order.** Drop `DEFAULT nextval` first, then drop sequences. Or keep sequences in the DB for one release cycle as a diagnostic (`SELECT nextval(...)` in a health check). Prefer the latter — cheap signal that "nothing ever calls this".
4. **Migration ordering against obs-01.** obs-01 is parallel-eligible with obs-03 per the plan. If obs-01 lands first, it adopts today's `write_impact` and inherits the Phase 1 change for free. If obs-03 lands first, obs-01 inherits `allocate_id` directly. Either order is safe **iff** Phase 1 is API-compatible. That constraint is load-bearing — call it out in the Phase 1 prompt.
5. **Observability write.** Do we stamp allocations into a new `ingestion_allocations` table (queryable, durable) or only to the standard log? The former is cheap (∼29k impacts / ~21k manifests over the full history) and closes the "did anyone bypass" question with a SQL query forever. The latter is simpler. Recommend the table; make it additive migration.

---

## §7. Summary

- The 2026-04-16 crash root cause is fully understood and the [`11a35e9`](https://github.com/ST5555-Code/13f-ownership/commit/11a35e9) fix is holding in production: zero duplicate impact_ids today, `_next_id`-driven allocation for every real caller.
- One dead-but-reachable bypass exists at [scripts/pipeline/shared.py:430](scripts/pipeline/shared.py:430) (`write_impact_row`), and two structural re-introduction vectors exist in obs-01 and obs-04.
- DuckDB's per-file write lock makes the current one-writer invariant real, not aspirational; however the invariant is enforced externally and cannot protect callers that bypass `_next_id` via `DEFAULT nextval` (both sequences are 26k–40k behind `MAX`, so any such caller collides on its first INSERT).
- Phase 1 should centralize into `scripts/pipeline/id_allocator.py`, keep `write_impact` API-compatible, add a `reserve_ids` bulk primitive for obs-04, delete the dead `write_impact_row` path, drop `DEFAULT nextval` from DDL, and ship a concurrency-oriented test suite.

**Hard stop:** obs-03-p0 is investigation-only. No code writes, no DB writes, no merge. Phase 1 implementation prompt to follow.
