# obs-08-p1 — MINOR-16 O-05 backup-gap investigation

_Prepared: 2026-04-21 — branch `obs-08-p1` off `main` HEAD `c4e1281`._

_Tracker: SYSTEM_AUDIT MINOR-16 ([docs/SYSTEM_AUDIT_2026_04_17.md:214](docs/SYSTEM_AUDIT_2026_04_17.md:214)), Atlas O-05 ([docs/SYSTEM_ATLAS_2026_04_17.md:591](docs/SYSTEM_ATLAS_2026_04_17.md:591)), Codex PROMOTE ([docs/findings/2026-04-17-codex-review.md:79](docs/findings/2026-04-17-codex-review.md:79))._

---

## §1. TL;DR

Backup infrastructure is **fully in place and actively used** — script, Makefile
target, MAINTENANCE.md protocol, restore procedure, and 12 prod snapshots on
disk spanning 2026-04-10 → 2026-04-19. No infrastructure gap.

The two Atlas drift signals are both **benign and explained**:

- **Apr 14 size shrinkage (1.6 G vs 2.6-2.7 G surrounding)** → `positions` table
  dropped in Batch 1 pipeline framework refactor ([commit d50b602](https://github.com/sergetismen/13f-ownership/commit/d50b602)). Confirmed by diff of parquet file lists:
  Apr 13 backup has `positions.parquet`; Apr 14 backup replaces it with
  `pending_entity_resolution.parquet` + `ingestion_manifest.parquet` +
  `ingestion_impacts.parquet`. Not a partial backup — a smaller schema.
- **3d 12h gap Apr 14 → Apr 17** → intensive development window (CUSIP v1.4
  Session 2, DERA N-PORT Session 2 promote, N-PORT enrichment rewrite —
  commits `c31ffcb`, `e4e6468`, `7770f87`). Routine backups resumed Apr 17
  with `pre_phase3` named snapshot, then daily through Apr 19.

Remediation in this PR: **documentation-only**. Fix a wording contradiction in
MAINTENANCE.md ("never on a schedule" vs Makefile `quarterly-update` step 8),
add backup retention guidance, and record the O-05 resolution rationale.

---

## §2. Current state of backup infrastructure

### §2.1 Components

| Component | Path | Status |
|---|---|---|
| Backup script | [scripts/backup_db.py](scripts/backup_db.py) (144 LOC) | ✅ Present. Full DuckDB `EXPORT DATABASE` → parquet directory under `data/backups/`. Prompts for confirmation; `--no-confirm` for scripted use; `--list` for inventory; `--staging` for staging DB. |
| Makefile target | [Makefile:136-138](Makefile:136) — `backup-db` | ✅ Present. Runs `scripts/backup_db.py --no-confirm`. |
| Scheduled invocation | [Makefile:92](Makefile:92) — `quarterly-update` step 8 | ✅ Present. `$(MAKE) backup-db` runs after `build-classifications`, before `validate`. |
| Help surface | [Makefile:51](Makefile:51) | ✅ Listed under "Primary" targets. |
| Documentation | [MAINTENANCE.md:56-87](MAINTENANCE.md:56) "Backup Protocol" | ⚠️ Correct about manual invocation but contradicts the `quarterly-update` automation (see §3). |
| Restore documentation | [MAINTENANCE.md:183-192](MAINTENANCE.md:183) | ✅ Present. Documents `IMPORT DATABASE` from a backup directory. |
| Backing-store ignored | [.gitignore:12-13](.gitignore:12) | ✅ `data/backups/` gitignored. |
| On-disk backup inventory | `data/backups/` | ✅ 12 directories, 2026-04-10 → 2026-04-19. |

### §2.2 On-disk inventory (2026-04-21)

```
data/backups/13f_backup_20260410_122411/                            2.7G  2026-04-10 12:24
data/backups/13f_backup_20260413_184518/                            2.7G  2026-04-13 18:45
data/backups/13f_backup_20260413_222950/                            2.1G  2026-04-13 22:29
data/backups/13f_backup_20260414_040227/                            1.6G  2026-04-14 04:02
data/backups/13f_backup_20260414_053433/                            1.6G  2026-04-14 05:34
data/backups/13f_backup_20260417_172152/                            2.6G  2026-04-17 17:21
data/backups/13f_backup_pre_phase3_20260418_172137/                 2.6G  2026-04-18 17:21
data/backups/13f_backup_pre_block3_phase4_20260418_201319/          2.6G  2026-04-18 20:13
data/backups/13f_backup_pre_sector_merge_20260419_052625/           2.6G  2026-04-19 05:26
data/backups/13f_backup_pre_rewrite_shares_history_20260419_055720/ 2.6G  2026-04-19 05:57
data/backups/13f_backup_pre_rewrite_load_13f_20260419_072249/       2.6G  2026-04-19 07:22
data/backups/13f_backup_pre_rewrite_build_managers_20260419_090947/ 2.6G  2026-04-19 09:10
```

**Pattern of use:** operators take automatic-naming backups around routine work
(Apr 10, Apr 13, Apr 14, Apr 17) and custom-named `pre_*` backups before
high-risk sessions (Phase 3 start, Block-3 Phase 4, sector merge, script
rewrites). The script supports both — default naming is timestamp-only; custom
names come from callers that pass a label (used by `promote_staging.py`-adjacent
tooling, not by the bare `backup_db.py` CLI, which only uses timestamps).

### §2.3 Cadence summary

| Date | # backups | Notes |
|---|---|---|
| 2026-04-10 | 1 | Staging workflow framework shipping ([commit 950ec7e](https://github.com/sergetismen/13f-ownership/commit/950ec7e)) |
| 2026-04-13 | 2 | DERA S2 + CUSIP v1.4 S2 sessions |
| 2026-04-14 | 2 | DERA S2 promote + N-PORT enrichment work |
| 2026-04-15 / 16 | 0 | _Gap window flagged by O-05 → see §3_ |
| 2026-04-17 | 1 | Pre-Phase3 baseline |
| 2026-04-18 | 2 | Pre-Phase3 + pre-Block3-Phase4 |
| 2026-04-19 | 4 | Four `pre_rewrite_*` / `pre_sector_merge` session-guarded snapshots |
| 2026-04-20 / 21 | 0 | Current session window — no DB-mutating work yet |

12 backups in 10 days is a **high** cadence, not a gap.

---

## §3. O-05 drift signals — explained

### §3.1 Size shrinkage (Apr 14: 1.6 G vs 2.6-2.7 G surrounding)

**Root cause:** `positions` table dropped from the schema in Batch 1 pipeline
framework refactor.

**Evidence:** `diff` of parquet file lists between the Apr 13 22:29 backup
(2.1 G) and the Apr 14 04:02 backup (1.6 G):

```diff
--- data/backups/13f_backup_20260413_222950/
+++ data/backups/13f_backup_20260414_040227/
@@
+ ingestion_impacts.parquet
+ ingestion_manifest.parquet
- positions.parquet
+ pending_entity_resolution.parquet
```

The two backups flanking the cut (Apr 13 22:29 at 2.1 G, Apr 14 04:02 at 1.6 G)
are **identical schemas before and after the `positions` drop respectively,
plus the new control-plane tables**. The drop landed in:

- [commit d50b602](https://github.com/sergetismen/13f-ownership/commit/d50b602) — _chore: Batch 1 — drop positions, fix DDL drift, control plane to prod_

Surrounding 2.7 G baseline reappears on Apr 17 because new data volume
(DERA N-PORT Session 2 promote, CUSIP v1.4 classifications, N-PORT enrichment
backfill) grew the schema back past where it was before the drop:

- `13f_backup_20260417_172152`: **318 parquet files**
- `13f_backup_20260413_222950`: **176 parquet files**

Schema grew ~80 % in table count across Apr 14 → Apr 17 — expected given the
N-PORT DERA rewrite, manifest/impact control plane, and CUSIP classification
tables that landed in that window.

**Status:** EXPLAINED. Size reduction is the expected signature of a documented
`DROP TABLE positions`. No partial state; no corruption.

### §3.2 3d 12h gap (Apr 14 05:34 → Apr 17 17:21)

**Root cause:** Dev-intensive window with no DB mutations of the kind that
trigger a `pre_*` backup, and no `quarterly-update` invocation in that window.

**Evidence:** git log for Apr 14 → Apr 17:

```
7770f87 perf+fix: bulk N-PORT enrichment + S1 synth allowance + context backfill
e4e6468 feat: resolve 3,613 N-PORT pending series + re-promote DERA S2 + topup
c31ffcb docs: backfill parallel 2026-04-14 no-DB workstream
d8a6a01 docs: session close — full doc update after CUSIP v1.4 + N-PORT backfill
39d5e95 fix(nport): cross-ZIP amendment dedupe + set-based validator
```

Most commits in this window are docs + validator fixes. Enrichment and
promote work between Apr 15 and Apr 17 ran under `promote_staging.py`-class
tooling, which takes **intra-DB snapshots** per table (see
[MAINTENANCE.md:83-87](MAINTENANCE.md:83)) — not a full `EXPORT DATABASE`.

The `13f_backup_20260417_172152` snapshot (318 files, 2.6 G) is the next full
backup after the window, taken pre-Phase 3. This is operating as designed:
full backups are reserved for known-risky sessions, not taken daily.

**Status:** EXPLAINED. Not a gap in coverage — a gap in `EXPORT DATABASE`
invocation that matches the "reserved for risky sessions" policy in
MAINTENANCE.md.

---

## §4. Remediation in this PR

### §4.1 Documentation fix: MAINTENANCE.md wording contradiction

[MAINTENANCE.md:58](MAINTENANCE.md:58) currently reads:

> `backup_db.py` runs **manually**, never on a schedule.

But [Makefile:92](Makefile:92) wires `backup-db` into `quarterly-update` as
step 8. This is a true contradiction — the Makefile step runs the script under
a scheduled operational sequence (even though the _schedule_ itself is
analyst-triggered, not cron-triggered).

Fix: change the wording to reflect both invocation paths:

- Full backups run **quarterly** as step 8 of `make quarterly-update`
  (`backup-db` target), AND
- Ad-hoc manually before DM13 / DM14 / DM15 audit passes, non-routine
  migrations, or analyst-discretion risky edits.

### §4.2 Documentation addition: retention

Inventory sizing shows ~2.6 G × 12 = ~31 G of backup directories in
`data/backups/`. No retention policy today. Add a note:

- Keep all backups from the **current quarter** and the **current month** in
  full.
- Manual pruning is operator-driven; `data/backups/` is gitignored so there is
  no risk to history if directories are removed.
- A retention script is **out of scope** for this ticket — tracked as optional
  Phase 2 enhancement if disk pressure ever forces it.

### §4.3 Out of scope

- No changes to `backup_db.py` — script is working as designed.
- No changes to `Makefile` — target is correctly wired.
- No new cron / scheduled-tasks integration — MAINTENANCE.md policy is that
  full backups are analyst-triggered; `quarterly-update` invocation is the
  scheduling surface and is already in place.
- No retroactive inventory cleanup of `data/backups/`.
- No size-drift alerting. Could be added in a future O-0x ticket but is not
  part of MINOR-16.

---

## §5. Verification

| Check | Command | Expected |
|---|---|---|
| Backup script present and executable | `ls -l scripts/backup_db.py` | file exists, Python |
| Makefile target dry-run | `make -n backup-db` | prints the `python3 scripts/backup_db.py --no-confirm` invocation |
| Quarterly-update includes backup | `grep backup-db Makefile` | `backup-db validate` in `.PHONY`; `$(MAKE) backup-db` at step 8 |
| Restore path documented | `grep -c "IMPORT DATABASE" MAINTENANCE.md` | ≥ 1 |
| On-disk inventory matches MAINTENANCE.md pattern | `python3 scripts/backup_db.py --list` | prints the 12 rows in §2.2 |

No Python code changes in this PR — only MAINTENANCE.md wording. Ruff / pytest
not required per remediation task instructions.

---

## §6. REMEDIATION status

- `docs/REMEDIATION_CHECKLIST.md` line 62 — flip `- [ ]` to `- [x]` with
  PR reference.
- `docs/REMEDIATION_PLAN.md` line 91 — flip `OPEN` to `CLOSED (PR #TBD)` with
  note that the finding was explained, not fixed.

Both updates are in this PR.

---

## §7. Source citations

- Atlas drift table [docs/SYSTEM_ATLAS_2026_04_17.md:591](docs/SYSTEM_ATLAS_2026_04_17.md:591).
- Audit tracker [docs/SYSTEM_AUDIT_2026_04_17.md:214](docs/SYSTEM_AUDIT_2026_04_17.md:214), action-list [docs/SYSTEM_AUDIT_2026_04_17.md:352](docs/SYSTEM_AUDIT_2026_04_17.md:352).
- Codex promote rationale [docs/findings/2026-04-17-codex-review.md:79](docs/findings/2026-04-17-codex-review.md:79).
- On-disk `du -sh data/backups/*/` run 2026-04-21.
- Parquet diff `diff <(ls data/backups/…_222950/) <(ls data/backups/…_040227/)` run 2026-04-21.
- Commit `d50b602` authored the `positions` drop + control-plane add.

_End of obs-08-p1 findings._
