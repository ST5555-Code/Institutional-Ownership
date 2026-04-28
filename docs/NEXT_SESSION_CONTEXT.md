# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`dera-synthetic-tier4` (this session, branch `claude/optimistic-lamport-78dc7e`,
not yet merged). Phase 3 (Tier 4) of the DERA synthetic-series resolution
shipped: 657 institution-entity bootstraps + 1 Calamos attach, all 658 Tier 4
CIKs migrated to `SYN_{cik_padded}` stable keys. **Closes the umbrella DERA
synthetic initiative** across all four tiers (Tier 1: 1 reg / 72 rows; Tier 3:
55 regs / 1.29M rows / $1.98T NAV; Tier 4: 658 regs / 884K rows / $567B NAV;
$2.55T NAV total resolved across 714 registrants).

## This session

| Phase | Slug | Outcome |
|---|---|---|
| Pre-flight | discovery + dedup | Read-only against prod. Cohort = 658 distinct CIKs (matches scoping doc; +0 delta). 100% have `fund_holdings_v2.fund_name`; 0% in `managers`/`filings`; 1 in `adv_managers`. AUM tiers: 0 >$10B, 181 $1-10B, 372 $100M-1B, 105 <$100M. Top NAV $5.3B (First Trust Alt Opps) — no fat-tail single registrant. **Dedup gate: 3 name hits / threshold 50 → PROCEED.** Cross-checked the 3 hits' fund_cik on existing eids: 2 are name collisions (Nuveen FRI eid 20950 maps to fund_cik 0001071336 / Nuveen Investment Trust III; Alt Strats eid 16596 maps to fund_cik 0000875186 / Morgan Stanley Pathway Funds — different registrants); only Calamos (CIK 0001285650, eids 20206 + 20207) is a true match (duplicate-entity-at-entity-layer). |
| Pre-flight | backup + baselines | App not running — no stop needed. Backup `data/backups/13f_backup_20260428_134957/` (3.2 GB EXPORT DATABASE PARQUET). Pre-state: fund_holdings_v2 14,568,775 (all) / 14,568,704 (`is_latest`); 14,389 distinct series_id (`is_latest`); $161,598,742,805,816.56 NAV (`is_latest`); fund_universe 13,014; entities 26,602 / entity_identifiers 35,516 / max_eid 26,602; 55 SYN_* keys; 883,912 residual `{cik}_{accession}` synth rows. |
| Phase 3 | dera-synthetic-tier4 | Extended `scripts/oneoff/dera_synthetic_stabilize.py` with `--phase 3` (choices `1\|2\|3\|all`). 657 CIKs bootstrap fresh institution entities (`entity_type='institution'`, `created_source='bootstrap_tier4'`, `classification='unknown'` per Serge sign-off — no name-keyword guessing); 1 CIK (Calamos) attached to existing eid 20206 with stale synth-series identifiers closed on both 20206 + 20207. Per CIK in one tx: bootstrap-or-attach → rekey holdings on LPAD'd prefix → DELETE fund_universe by fund_cik → INSERT canonical SYN_{cik} fund_universe row → backfill entity columns. **Apply output:** "bootstrapped 657 entities, reused 1 (Calamos); rekeyed 883,912 holdings rows; fund_universe -49 +658 (canon_from_fu=48, canon_from_holdings=610); backfilled 883,912 entity/rollup cells". |
| Recompute | downstream pipelines | `compute_parent_fund_map` (109,721 upserted, 119s); `compute_sector_flows` (321 upserted, 2s); `compute_flows` (19,224,688 investor_flows / 69,142 ticker_flow_stats, 22s); `build_summaries` (10,969 / 8,438 / 8,438, 1.8s); `refresh_snapshot.sh` (7.8 GB / 378 tables). |
| Verify | post-state assertions | All 10 PASS: fund_holdings_v2 totals **unchanged** at 14,568,775 / 14,568,704; NAV `is_latest` $161,598,742,805,818.09 (delta vs pre +9.48e-13%, float aggregation); 0 residual `{cik}_{accession}` synth rows for the 658 cohort (was 883,912); SYN_* keys = 713 (= 55 Phase 2 + 658 Phase 3); 0 NULL entity_id on SYN_* rows; entities +657 (26,602 → 27,259); entity_identifiers +658; fund_universe +609 (13,014 → 13,623 = -49 +658); distinct series_id `is_latest` -470 (14,389 → 13,919); Calamos stale synth-series identifiers on 20206 + 20207 closed; CIK 0001285650 attached to eid 20206. `validate_entities --prod --read-only` 7 PASS / 1 FAIL (`wellington_sub_advisory` baseline) / 8 MANUAL — same as `dera-synthetic-phase1-2` close. |

**Implementation refinements vs Phase 2:**

- Holdings rekey matches by `LPAD(SPLIT_PART(series_id,'_',1),10,'0') = ?`
  rather than the unpadded `SPLIT_PART` of Phase 2 — the Tier 4 cohort has
  11 CIKs with both padded and unpadded raw_cik representations
  (`0001581005_…` and `1581005_…` for the same registrant).
- New `_canon_from_holdings_padded` helper (mirrors Phase 2's
  `_canon_from_holdings` but matches by LPAD'd prefix).
- `_bootstrap_new_institution` inlined in this script rather than reusing
  `bootstrap_residual_advisers._create_entity` — that script targets
  staging via `db.set_staging_mode(True)` and curates a hand-coded
  `NEW_ADVISERS` seed list, neither of which fits a 657-CIK prod-direct run.
- `_attach_calamos` is a single-purpose helper carrying the dedup
  decision constants (`CALAMOS_CIK = "0001285650"`, `CALAMOS_REUSE_EID = 20206`,
  `CALAMOS_DUP_EID = 20207`).

**Worktree note.** Worktree path `.claude/worktrees/optimistic-lamport-78dc7e/`
has no `data/` subdir by default. Symlinked the prod DB files (`13f.duckdb`,
`13f_readonly.duckdb`, `13f_staging.duckdb`, `admin.duckdb`, `backups/`,
`nport_raw/`, `13dg_raw/`, `cache/`) into worktree `data/` from
`../../../../data/`; logs/`phase3_resolution_results.csv` symlinked from
`../../../../logs/`. With these symlinks, all relative paths in scripts
resolve correctly and `db.PROD_DB` resolves to the canonical prod DB. The
symlinks are git-untracked (`data/*.duckdb` and `data/backups/` are
gitignored).

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** empty (`DERA-synthetic-series-resolution Tier 4` closed in this session).
- **P3 (3 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Type-badge family_office color` — `web/react-app/src/common/typeConfig.ts` needs a `family_office` case so the 36,950 reclassified `holdings_v2` rows render with a dedicated chip.
  - `Calamos eid 20206 / 20207 entity-merge` — surfaced this session. Merge orphan eid 20207 into 20206 (re-point relationships / overrides / aliases, close entities row) in the next entity-curation pass.
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; gate to drop snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes and of `compute_parent_fund_map.py` quarterly rebuild. **Re-measure all DERA tier residuals** after this drop — new filings will mint `{raw_cik}_{accession}` keys for any registrant whose N-PORT lacks SERIES_ID. The `dera_synthetic_stabilize.py` script is idempotent; re-run `--phase all --confirm` against the new period to absorb any new Tier 3/4 candidates.

## Reminders

- **PR for this session is open but NOT merged.** Per session brief: "do not merge". One commit on `claude/optimistic-lamport-78dc7e` covering the script extension + ROADMAP / NEXT_SESSION / CHAT_HANDOVER updates.
- **App is started from `data/13f_readonly.duckdb`** (refreshed in this session). If the user starts it with the standard incantation it will pick up the 658 new SYN_* keys + entity backfill automatically.
- **`SYN_{cik_padded}` stable-key pattern is now applied to all entity-mapped synth registrants** (713 distinct keys: 55 Phase 2 + 658 Phase 3). The remaining `{cik}_{accession}` minting in `scripts/fetch_dera_nport.py:460` is upstream and fires only when DERA `FUND_REPORTED_INFO.SERIES_ID` is missing in the source XML — that path can be flipped to mint `SYN_{cik_padded}` directly in a follow-up to retire the `series_id_synthetic_fallback` validator FLAG.
- **Validator FLAG `series_id_synthetic_fallback` (`scripts/pipeline/load_nport.py:437`) can be retired** in the next `load_nport.py` audit pass — there are no remaining Tier 1/3/4 candidates as of close. New synthetic keys minted by future N-PORT filings will be net-new (Tier 4-shape, fixable by re-running `dera_synthetic_stabilize.py --phase 3 --confirm`); the FLAG no longer protects against legacy backlog.
- **`make audit` baseline preserved post-Tier-4.** `validate_entities --prod` 7 PASS / 1 FAIL (`wellington_sub_advisory`) / 8 MANUAL.
- **657 new institution entities are `classification='unknown'`.** The classification pipeline (next `build_classifications.py` non-`--reset` sweep) will assign them based on fund_strategy / SIC / N-PORT signals. No manual classification was done in this session — Serge's explicit instruction.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full.
- **Do not run `build_classifications.py --reset`.** Same as previous sessions.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
