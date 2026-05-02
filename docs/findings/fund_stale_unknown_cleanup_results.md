# fund-stale-unknown-cleanup — Phase 3–5 results

**Date:** 2026-05-02
**Branch:** `fund-stale-unknown-cleanup`
**Scope:** BRANCH 1 only (6 pairs / 2,738 rows / $5.283B). BRANCH 2
(2 pairs / 446 rows / $4.741B) deferred to `cef-attribution-path` workstream.

Closes the stale-loader artifact partially surfaced by PR #246 — the
Apr-15 v2 loader (commit `e868772`) wrote authoritative `SYN_*` rows but
did not flip `is_latest=FALSE` on the legacy `series_id='UNKNOWN'` rows
for the same `(cik, accession_number)`. This PR flips the 6 pairs whose
SYN_ companion is now live; the 2 closed-end-fund pairs that have no
SYN_ companion are deferred (see _Deferred items_ below).

---

## Phase 3 — `--confirm` execution

```
[confirm] cohort OK: pairs=8, rows=3,184, aum=$10,024,654,105.56
[confirm] pre-flip UNKNOWN is_latest=TRUE rows: 3,184
[confirm] flipping 6 (cik, fund_name) pairs, expected row delta: 2,738
[confirm] post-flip UNKNOWN is_latest=TRUE rows: 446 (Δ=2,738)
[confirm] DONE — flipped is_latest on 2,738 rows across 6 pairs.
          UNKNOWN is_latest=TRUE: 3,184 → 446.
```

Pairs flipped (`is_latest=TRUE → FALSE` on `series_id='UNKNOWN'`):

| cik | fund_name | rows | UNKNOWN AUM | live SYN_ | SYN strategy |
|---|---|---:|---:|---|---|
| 0001253327 | Eaton Vance Tax-Advantaged Dividend Income Fund | 157 | $2.864B | `SYN_0001253327` | balanced |
| 0001709406 | AIP Alternative Lending Fund P | 2 | $1.018B | `SYN_0001709406` | bond_or_other |
| 0001995940 | AMG Pantheon Credit Solutions Fund | 33 | $0.689B | `SYN_0001995940` | bond_or_other |
| 0001285650 | Calamos Global Total Return Fund | 1,412 | $0.325B | `SYN_0001285650` | balanced |
| 0001400897 | NXG Cushing Midstream Energy Fund | 43 | $0.258B | `SYN_0001400897` | active |
| 0000826020 | Saba Capital Income & Opportunities Fund | 1,091 | $0.129B | `SYN_0000826020` | balanced |
| **TOTAL** | | **2,738** | **$5.283B** | | |

All hard guards passed: cohort drift gate (0%), expected vs actual flip
delta (2,738 == 2,738), `BEGIN/COMMIT` wrapped UPDATE.

The Calamos branch shifted from PR #246's `HOLD` into `FLIP` because the
v2 loader wrote `SYN_0001285650` (1,459 `is_latest=TRUE` rows) some time
between #246's audit and this run.

## Phase 4 — peer_rotation_flows rebuild

```
2026-05-02 05:52:59,655 INFO parse complete: 17,489,751 total rows in 46.7s
2026-05-02 05:53:01,059 INFO run(): pending_approval inserts=17,489,751
promoted: rows_upserted=17,489,751 (193.1s)
```

| metric | pre-rebuild | post-rebuild | Δ |
|---|---:|---:|---:|
| `peer_rotation_flows` row count | 17,490,106 | 17,489,751 | -355 (0.002%) |

The -355 row delta is well within the brief's ±0.5% tolerance and is
explained by the 2,738 holdings rows leaving the `is_latest=TRUE`
universe — most of those rows were already collapsing into existing
SYN_-side fund identities in the prior aggregate, so the net change in
distinct (quarter_pair × sector × entity × ticker) tuples is small.

### Spot-check (3 affected SYN_ series, by `entity` in peer_rotation_flows)

`peer_rotation_flows.entity` is a `fund_name` literal (not `series_id`),
so cases where the UNKNOWN side and SYN_ side share a fund_name
collapsed under the same entity pre-rebuild and now reflect SYN_-only
contributions; the case-different Calamos pair shows the UNKNOWN-side
entity vanishing entirely.

| entity (level=fund) | pre rows | pre Σ flow | post rows | post Σ flow | interpretation |
|---|---:|---:|---:|---:|---|
| `CALAMOS GLOBAL TOTAL RETURN FUND` (SYN_-side, uppercase) | 127 | $47.6M | 127 | $47.6M | unchanged — SYN_ rows already authoritative |
| `Calamos Global Total Return Fund` (UNKNOWN-side, mixed-case) | 142 | -$272.7M | 0 | — | entity vanished (UNKNOWN rows now `is_latest=FALSE`) |
| `Eaton Vance Tax-Advantaged Dividend Income Fund` | 242 | $2.088B | 121 | $1.688B | UNKNOWN contributions removed; SYN_-only remains |
| `NXG Cushing Midstream Energy Fund` | 121 | -$34.3M | 66 | $0 | UNKNOWN contributions removed; SYN_-only remains |

For the same-fund_name cases (Eaton Vance, NXG) the previously-summed
contributions from UNKNOWN + SYN_ both feeding the same entity bucket
have now collapsed to SYN_-only — the rebuild cleanly de-duped what was
double-counted before. For the case-different Calamos case the UNKNOWN
entity is gone and the SYN_ entity is unchanged. Both are the correct
semantics.

## Phase 5 — validation

| check | command | result |
|---|---|---|
| pytest | `python3 -m pytest tests/` | **373 passed** in 56.46s |
| unknown inventory | `audit_unknown_inventory.py` | 1 orphan series, **446 rows / $4.74B** (expected: 2 BRANCH 2 pairs) |
| orphan inventory | `audit_orphan_inventory.py` | `phase2_cohort_summary` = `[UNKNOWN_literal, 1, 446, 4,741,195,026]` (expected: same) |
| frontend build | `cd web/react-app && npm run build` | **✓ built in 1.41s, 0 errors** |
| spot-check FLIP pair (Eaton Vance) | `SELECT series_id, COUNT(*) FROM fund_holdings_v2 WHERE cik=0001253327 AND fund_name=... AND is_latest=TRUE GROUP BY series_id` | `[(SYN_0001253327, 311)]` — UNKNOWN gone ✓ |
| spot-check FLIP pair (AMG) | `... cik=0001995940 ...` | `[(SYN_0001995940, 77)]` — UNKNOWN gone ✓ |
| spot-check FLIP pair (Saba) | `... cik=0000826020 ...` | `[(SYN_0000826020, 2185)]` — UNKNOWN gone ✓ |
| spot-check HOLD pair (Adams) | `... cik=0000002230 ...` | `[(UNKNOWN, 96)]` — preserved by design ✓ |
| spot-check HOLD pair (Asa Gold) | `... cik=0001230869 ...` | `[(UNKNOWN, 350)]` — preserved by design ✓ |

---

## Deferred items

The 2 BRANCH 2 pairs are deferred to a new workstream named
**`cef-attribution-path`** (closed-end fund attribution). `ROADMAP.md` is
updated separately to track the workstream.

| cik | ticker | fund_name | rows | AUM | type |
|---|---|---|---:|---:|---|
| 0000002230 | NYSE: ADX | Adams Diversified Equity Fund | 96 | $2.989B | closed-end |
| 0001230869 | NYSE: ASA | ASA Gold & Precious Metals Ltd | 350 | $1.752B | closed-end |

**Why deferred (architectural).** The `SYN_*` series_id pattern was
introduced by the Apr-15 N-PORT v2 loader (`SYN_{cik}` synthetic series
for funds whose `<seriesId>` was absent in the source filing). Both
deferred pairs are **closed-end funds (CEFs)** that file on **N-CSR /
NSAR-A / NSAR-B**, not on N-PORT. Synthesizing `SYN_0000002230` and
`SYN_0001230869` `fund_universe` rows here would create fund-universe
entries that no future N-PORT load reconciles against — wrong
architectural shelf. Resolution belongs in a CEF-aware loader path that
hangs off the closed-end-fund filings, not in this stale-loader cleanup.

Until `cef-attribution-path` lands, these 446 rows / $4.741B will
continue to display under the `unknown` fund_strategy bucket. This is
the **expected residual** — the audit re-runs above show exactly this
count, and that count is *not* a regression.

> **See also:** [ROADMAP.md § cef-attribution-path](../../ROADMAP.md#cef-attribution-path) — full 5-PR workstream spec (scoping → fetch → parse → load → display); [ROADMAP.md § v2-loader-is-latest-watchpoint](../../ROADMAP.md#v2-loader-is-latest-watchpoint) — post-Q1-cycle residual check that closes Open Question #4.

---

## Out-of-scope / surfaced for follow-up

The Apr-15 v2 loader bug that left the 8 UNKNOWN pairs `is_latest=TRUE`
in the first place is **not** patched in this PR. Per the brief, fixing
the write-path retroactively is out of scope; the cleanup is a one-shot
oneoff. A future loader PR could add a guard at v2 write time that
flips `is_latest=FALSE` on any pre-existing `(fund_cik, fund_name,
accession_number)` rows whose series_id differs from the new SYN_-write,
which would prevent this class of artifact from re-appearing. That is
the upstream fix and remains an open question (#4 in PR #246's
attribution doc).

---

## Appendix — files

- [scripts/oneoff/cleanup_stale_unknown.py](scripts/oneoff/cleanup_stale_unknown.py) — `--dry-run` / `--confirm` orchestrator with `--accept-deferred-holds` opt-in for skipping HOLD_NO_MATCH pairs.
- [data/working/stale_unknown_cleanup_manifest.csv](data/working/stale_unknown_cleanup_manifest.csv) — single source of truth consumed by `--confirm` (8-pair audit; 6 FLIP, 2 HOLD_NO_MATCH).
- [docs/findings/fund_stale_unknown_cleanup_dryrun.md](docs/findings/fund_stale_unknown_cleanup_dryrun.md) — Phase 2 dry-run snapshot (committed in `940576c`).
