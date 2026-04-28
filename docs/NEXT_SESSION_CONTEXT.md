# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`conv-16-doc-sync` — final-session doc sync covering the **31-PR arc #169–#200**. Current HEAD: `5a77c5c` (PR #200 `calamos-merge-tier4-classify`). The umbrella **DERA synthetic-series initiative is fully resolved across Tiers 1+3+4** ($2.55T NAV / 714 registrants / 713 distinct `SYN_*` stable keys / 2,170,629 holdings rows rekeyed). The Calamos eid 20206/20207 entity-merge surfaced by Tier 4 close was applied in PR #200 alongside a Tier 4 keyword classification sweep (230 of 657 `bootstrap_tier4` entities labeled `active`/`passive`; 427 remain `unknown` and are logged as new P3).

This sync (no PR yet — being opened):

- **`ROADMAP.md`** — added two missing scoping rows so all 31 PRs have standalone COMPLETED entries: PR #190 `perf-p2-discovery` and PR #197 `dera-synthetic-series-discovery`.
- **`MAINTENANCE.md`** — last-updated stamp refreshed to `conv-16-doc-sync`; precompute row count corrected to 111,941.
- **`ENTITY_ARCHITECTURE.md`** — header rewritten with current prod counts (entities 27,259; overrides 1,104 / MAX 1,106; relationships 18,363 / 16,315 active; aliases 27,601; identifiers 36,174; rollup_history open 27,259 each on EC + DM; classifications_active 27,152 with full distribution; fund_holdings_v2 14,568,775 / 14,568,704; SYN_* 713; fund_universe 13,623; parent_fund_map 111,941; sector_flows_rollup 321).
- **`docs/findings/CHAT_HANDOVER.md`** — full rewrite for the 31-PR arc.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only — live Serge+Claude session, not a Code session.
- **P2:** empty (DERA umbrella initiative closed across all four tiers in #198/#199; Calamos merge follow-up closed in #200).
- **P3 (3 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Type-badge family_office color` — `web/react-app/src/common/typeConfig.ts` needs a `family_office` case so the 36,950 reclassified `holdings_v2` rows render with a dedicated chip color.
  - `Tier 4 unmatched classifications (427)` — surfaced by PR #200's keyword sweep; remaining 427 `bootstrap_tier4` entities still carry `classification='unknown'`. Trigger: next entity-curation pass willing to expand the keyword set (`Trust`, `MuniYield`, `Private`, `Opportunity`, `High Yield`, ADV-anchored CEF lookup) or do per-entity manual sign-off. NAV exposure bounded at ~$370B (427 / 657 × $566.7B Tier-4 cohort).

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants (script is idempotent). |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **PR for this conv-16-doc-sync session is open but NOT merged.** Per session brief: "do not merge". One commit on `conv-16-doc-sync` covering the 5 doc updates.
- **App is started from `data/13f_readonly.duckdb`** (last refreshed in PR #200, 2026-04-28 ~15:09). It carries the 657 Tier-4 institution bootstraps + Calamos merge + Tier-4 keyword sweep.
- **`SYN_{cik_padded}` stable-key pattern** is now applied to every entity-mapped synth registrant (713 distinct keys: 55 Phase 2 + 658 Phase 3). The `{cik}_{accession}` minting in `scripts/fetch_dera_nport.py:460` is upstream and only fires when DERA `FUND_REPORTED_INFO.SERIES_ID` is missing in the source XML.
- **Validator FLAG `series_id_synthetic_fallback` (`scripts/pipeline/load_nport.py:437`) can be retired** in the next `load_nport.py` audit pass — there are no remaining Tier 1/3/4 candidates as of PR #200. Future N-PORT filings without SERIES_ID will mint net-new `{raw_cik}_{accession}` keys; re-running `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period absorbs them.
- **`make audit` baseline preserved post Tier-4 + Calamos merge.** `validate_entities --prod` 7 PASS / 1 FAIL (`wellington_sub_advisory`) / 8 MANUAL.
- **657 new Tier-4 institution entities** opened in PR #199 with `classification='unknown'`. PR #200 keyword sweep closed 230 of them (1 passive + 229 active); the next `build_classifications.py` non-`--reset` sweep will reassign based on fund_strategy / SIC / N-PORT signals.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** Same as previous sessions (PR #162 eqt-classify-codefix changed what the classifier reads; a `--reset` would re-seed from a column the classifier no longer reads).
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172** (`dm13-de-discovery`) remains intentionally OPEN — paired-with-#173 triage CSV; close after reconciling.
