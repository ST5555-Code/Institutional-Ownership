# obs-01-p0 — Phase 0 findings: N-CEN + ADV manifest registration

_Prepared: 2026-04-21 — branch `remediation/obs-01-p0` off main HEAD `9812ef5`._

_Tracker: [docs/REMEDIATION_PLAN.md:84](docs/REMEDIATION_PLAN.md:84) Theme 2 row `obs-01`; [docs/REMEDIATION_CHECKLIST.md](docs/REMEDIATION_CHECKLIST.md) Batch 2-A. Audit refs: SYSTEM_AUDIT §3.1 MAJOR-9 (D-07/P-05)._

Phase 0 is investigation only. No code writes and no DB writes were performed. Prod DB (`data/13f.duckdb`) was read through `duckdb.connect(..., read_only=True)`.

---

## §1. Current state of `fetch_ncen.py` and `fetch_adv.py`

### §1.1 `fetch_ncen.py` — flow inventory

| Aspect | Detail |
|---|---|
| Source | SEC EDGAR per-CIK submissions JSON: `https://data.sec.gov/submissions/CIK{cik}.json`. For each fund CIK in `fund_universe`, picks the first `form == 'N-CEN'` entry and downloads `primary_doc.xml` from `https://www.sec.gov/Archives/edgar/data/{cik}/{acc_path}/primary_doc.xml` ([scripts/fetch_ncen.py:88-116](scripts/fetch_ncen.py:88), [:119-138](scripts/fetch_ncen.py:119)). |
| Target table | `ncen_adviser_map` — adviser/subadviser → series_id mapping. DDL at [scripts/fetch_ncen.py:275-290](scripts/fetch_ncen.py:275) (created with `CREATE TABLE IF NOT EXISTS`). |
| Write pattern | DELETE-then-INSERT per batch of registrant CIKs, row-by-row inside a Python loop ([scripts/fetch_ncen.py:304-331](scripts/fetch_ncen.py:304)). Idempotent on `registrant_cik`. Calls `CHECKPOINT` every 25 CIKs ([:501-502](scripts/fetch_ncen.py:501)). |
| Iteration grain | One HTTP round-trip per fund CIK (`fund_universe` ≈ 12,870 rows per prod data_freshness, §3). One N-CEN accession per CIK. Each accession contributes many rows (one per adviser × series). |
| Run identity | **None.** No `run_id` generation, no timestamp-scoped key. Rerunning the whole script replays against every CIK in `fund_universe` minus `get_processed_ciks(con)` ([:293-301](scripts/fetch_ncen.py:293)) — the "processed" filter is based on `registrant_cik` already having at least one row in `ncen_adviser_map`, not on a manifest. |
| Freshness | Calls `record_freshness(con, "ncen_adviser_map")` at end of run ([scripts/fetch_ncen.py:559-563](scripts/fetch_ncen.py:559)). Current prod `data_freshness` row: `ncen_adviser_map` last_computed 2026-04-17 13:12, 11,209 rows (§3.2). |
| Manifest / impacts | **Zero writes.** `grep 'ingestion_manifest\|ingestion_impacts\|write_manifest\|write_impact\|get_or_create_manifest'` against `scripts/fetch_ncen.py` → no matches. |

### §1.2 `fetch_adv.py` — flow inventory

| Aspect | Detail |
|---|---|
| Source | One bulk ZIP from SEC: `https://www.sec.gov/files/investment/data/other/information-about-registered-investment-advisers-exempt-reporting-advisers/ia030226.zip` (hardcoded, [scripts/fetch_adv.py:29-33](scripts/fetch_adv.py:29)). File name encodes publish month (`ia030226` = 2026-03 edition). |
| Target table | `adv_managers`. DDL is implicit: `CREATE TABLE adv_managers AS SELECT * FROM df_out` after `DROP TABLE IF EXISTS` ([scripts/fetch_adv.py:247-249](scripts/fetch_adv.py:247)). Row shape is whatever pandas writes. |
| Write pattern | **DROP + CREATE AS SELECT** — not transactional. The table is absent mid-run. This is MAJOR-14 / mig-02 territory ([docs/REMEDIATION_PLAN.md:121](docs/REMEDIATION_PLAN.md:121)). Out-of-scope here, but obs-01's manifest writes must not add rows while the canonical table is in the DROP'd state; see §5.2. |
| Iteration grain | Single-shot. One download, one parse, one bulk write. |
| Run identity | **None.** No `run_id`. Calls to `download_adv_zip`, `extract_csv`, `load_and_parse`, `save_to_duckdb` all sequentially in `main()` ([:272-297](scripts/fetch_adv.py:272)). |
| Freshness | Calls `record_freshness(con, "adv_managers", row_count=row_count)` at [scripts/fetch_adv.py:268](scripts/fetch_adv.py:268). **Current prod `data_freshness`: no `adv_managers` row** (§3.2). The freshness hook was added 2026-04-15 in commit `831e5b4` ("feat: Makefile + freshness hooks"); the script has not been re-run against prod since that commit landed. This is the obs-02 gap, not obs-01. |
| Manifest / impacts | **Zero writes.** Same grep as §1.1 on `scripts/fetch_adv.py` → no matches. |

### §1.3 Natural unit of work for manifest / impact

Given the flows above, the grain choices are:

- **N-CEN**: one manifest row per N-CEN accession (object_key = accession_number — matches the 13D/G and N-PORT per-filing convention; see §2.2). One impact row per (registrant_cik, report_date), target_table=`ncen_adviser_map`, unit_type=`registrant_report`. A full run produces ~12k manifest rows and ~12k impacts (scales with `fund_universe`, currently 12,870 — matches the existing ~11k ncen_adviser_map registrant fan-out). Matches the NPORT-XML grain (21,244 NPORT XML manifest rows in prod today, §3.2).
- **ADV**: one manifest row per ZIP download (object_key = ZIP filename, e.g. `ADV_BULK:ia030226.zip`, object_type = `ZIP`). One impact row for the bulk load, target_table=`adv_managers`, unit_type=`bulk_load`, unit_key_json=`{"filename":"ia030226.zip"}`. Matches the DERA_ZIP NPORT grain (§2.2) — one manifest per bulk artifact.

---

## §2. Control plane API and reference patterns

### §2.1 Control-plane primitives

`scripts/pipeline/manifest.py` (233 lines) exports:

| Call | Signature highlights | Behavior |
|---|---|---|
| `get_or_create_manifest_row(con, *, source_type, object_type, source_url, accession_number, run_id, object_key, **kwargs) -> int` | `object_key` is the UNIQUE natural key; accepts arbitrary column kwargs ([scripts/pipeline/manifest.py:21-65](scripts/pipeline/manifest.py:21)). | Idempotent on `object_key`. Returns existing `manifest_id` if one exists; else allocates via `allocate_id(con, "ingestion_manifest", "manifest_id")` and INSERTs. |
| `update_manifest_status(con, manifest_id, status, **kwargs) -> None` | [scripts/pipeline/manifest.py:68-81](scripts/pipeline/manifest.py:68) | Sets `fetch_status` + any other column. Used for fetching→complete / failed transitions. |
| `write_impact(con, *, manifest_id, target_table, unit_type, unit_key_json, report_date=None, rows_staged=0, load_status="pending", **kwargs) -> int` | [scripts/pipeline/manifest.py:113-150](scripts/pipeline/manifest.py:113) | Allocates `impact_id` via `allocate_id(...)` (obs-03-p1 output); INSERTs one row. |
| `update_impact_status(con, manifest_id, unit_type, unit_key_json, **kwargs) -> None` | [scripts/pipeline/manifest.py:153-172](scripts/pipeline/manifest.py:153) | Matches by `(manifest_id, unit_type, unit_key_json)` — caller does not carry `impact_id`. |
| `supersede_manifest(con, old_manifest_id, new_manifest_id) -> None` | [scripts/pipeline/manifest.py:84-106](scripts/pipeline/manifest.py:84) | Marks old superseded, new as amendment. Relevant if we ever ingest N-CEN amendments; see §5.4. |

ID allocation goes through [scripts/pipeline/id_allocator.py](scripts/pipeline/id_allocator.py) (obs-03-p1). Both `(ingestion_manifest, manifest_id)` and `(ingestion_impacts, impact_id)` are already on the allow-list ([scripts/pipeline/id_allocator.py:59-62](scripts/pipeline/id_allocator.py:59)). The prompt's wording ("`write_manifest`", "`stamp_freshness`") does not match the real API; correct names are `get_or_create_manifest_row` and, for freshness, `db.record_freshness` / `pipeline.shared.stamp_freshness` (which wraps `record_freshness` with a log line — [scripts/pipeline/shared.py:169-187](scripts/pipeline/shared.py:169)).

### §2.2 How the existing fetchers register

| Fetcher | source_type | Manifest grain | Impact grain |
|---|---|---|---|
| `fetch_market.py` | `MARKET` | One manifest per ticker batch. `object_type='price_batch'`, `object_key=f"market_{run_id}_{uuid}"` ([scripts/fetch_market.py:611-621](scripts/fetch_market.py:611)). Sample row: `(1, 'MARKET', 'price_batch', 'MARKET:6da824633aeaf173c01f676388c80eeb', 'complete')` (§3.2). | One impact per ticker, `unit_type='ticker_date'`, `unit_key_json={"ticker":t,"as_of_date":today}` ([:731-742](scripts/fetch_market.py:731)). |
| `fetch_nport_v2.py` (primary) | `NPORT` | One manifest per N-PORT XML. `object_type='XML'`, `object_key=accession_number` ([scripts/fetch_nport_v2.py:486-496](scripts/fetch_nport_v2.py:486)). | One impact per (series_id, report_month), `unit_type='series_month'` ([:709-719](scripts/fetch_nport_v2.py:709)). |
| `fetch_nport_v2.py` (DERA) | `NPORT` | One manifest per DERA quarterly ZIP. `object_type='DERA_ZIP'`, `object_key=f"DERA_ZIP:{year}Q{quarter}"` ([scripts/fetch_nport_v2.py:261-275](scripts/fetch_nport_v2.py:261)). Sample: `(5679, 'NPORT', 'DERA_ZIP', 'DERA:0000940400-25-005345', 'complete')`. | One impact per quarter, `unit_type='quarter'` ([:276-285](scripts/fetch_nport_v2.py:276)). |
| `fetch_13dg_v2.py` | `13DG` | One manifest per filing. `object_type='TXT'`, `object_key=accession_number` ([scripts/fetch_13dg_v2.py:336-346](scripts/fetch_13dg_v2.py:336)). | One impact per (filer_cik, subject_cusip), written at [:532](scripts/fetch_13dg_v2.py:532). |

All three follow the same three-step pattern:

1. `get_or_create_manifest_row(..., fetch_status="fetching", fetch_started_at=now())`
2. `update_manifest_status(..., "complete", fetch_completed_at=now(), http_code=..., source_bytes=...)`
3. `write_impact(...)` once per unit.

Each step opens its own short-lived `duckdb.connect(get_db_path())` and closes it after a `CHECKPOINT` to minimize the write-lock hold window.

---

## §3. Prod database state (read-only observation)

Queries issued against `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb` via `duckdb.connect(..., read_only=True)` on 2026-04-21.

### §3.1 `ingestion_manifest` — source_type distribution

```
source_type   rows
NPORT        21252
MARKET          84
13DG             3
```

MAX(manifest_id) = 26,997. No `NCEN` or `ADV` rows.

### §3.2 `data_freshness` — relevant rows

```
ncen_adviser_map         2026-04-17 13:12:37  rows=11,209
market_data              2026-04-16 23:27:35  rows=10,064
fund_holdings_v2         2026-04-17 11:11:28  rows=14,090,397
beneficial_ownership_v2  2026-04-14 04:05:04  rows=51,905
...
(no adv_managers row)
```

`adv_managers` physical table exists with 16,606 rows, but is absent from `data_freshness`. This is the obs-02 gap referenced in [docs/REMEDIATION_PLAN.md:85](docs/REMEDIATION_PLAN.md:85).

### §3.3 `ingestion_impacts` — target_table distribution

```
target_table              rows
fund_holdings_v2         21244
market_data               8284
beneficial_ownership_v2      3
```

MAX(impact_id) = 40,845. No rows with `target_table` in (`adv_managers`, `ncen_adviser_map`).

### §3.4 Schema — does migration 001 need changes?

No. `source_type` is `VARCHAR NOT NULL` with no check constraint; `object_type` likewise ([scripts/migrations/001_pipeline_control_plane.py:54-82](scripts/migrations/001_pipeline_control_plane.py:54)). Information_schema confirms: the only constraints on either table are NOT NULL and the PRIMARY KEY / UNIQUE on `object_key`. The migration's schema comment already lists `'NCEN'` and `'ADV'` as expected values ([scripts/migrations/001_pipeline_control_plane.py:55](scripts/migrations/001_pipeline_control_plane.py:55)) — the free-text column was designed to accept them; no DDL change needed.

The `id_allocator.py` allow-list already includes both `ingestion_manifest` and `ingestion_impacts` ([scripts/pipeline/id_allocator.py:59-62](scripts/pipeline/id_allocator.py:59)); no allocator change needed.

---

## §4. Cross-item interactions

| Item | File(s) | Risk | Handling |
|---|---|---|---|
| obs-02 (ADV freshness + log) | `fetch_adv.py`, `pipeline/freshness.py` (not yet created) | Same file as obs-01. Adds a stdout log line + ensures the `data_freshness` row lands. `record_freshness` already called at [scripts/fetch_adv.py:268](scripts/fetch_adv.py:268); obs-02 wraps with `pipeline.shared.stamp_freshness` for the log line. | **Serial** with obs-01 per plan ([docs/REMEDIATION_PLAN.md:250](docs/REMEDIATION_PLAN.md:250)). obs-01 lands first; obs-02 picks up the manifest-registered baseline. |
| obs-03 (id_allocator) | `pipeline/manifest.py`, `pipeline/id_allocator.py` | **Merged.** obs-01 calls `write_impact` / `get_or_create_manifest_row`, which now internally call `allocate_id`. No direct `_next_id` or `DEFAULT nextval`. | Verified — the only two APIs obs-01 will use (`get_or_create_manifest_row` and `write_impact`) both sit on top of `allocate_id`. |
| obs-04 (13D/G impacts backfill) | `pipeline/manifest.py`, `promote_13dg.py` | No file overlap. obs-04 will bulk-insert via `reserve_ids`. | Disjoint; no coordination. |
| mig-02 (fetch_adv.py DROP→CREATE atomic fix) | `fetch_adv.py:247-249` | Same file as obs-01. Will convert the DROP+CREATE to a single `CREATE OR REPLACE TABLE` (or staging+rename). | **Serial** with obs-01 per plan ([docs/REMEDIATION_PLAN.md:121](docs/REMEDIATION_PLAN.md:121), [:226](docs/REMEDIATION_PLAN.md:226)). obs-01 must place its manifest-write calls so that mig-02 can later wrap the canonical write atomically without re-threading the manifest logic. Concretely: write the manifest row **before** the table mutation and the impact row **after**, with `update_manifest_status` recording `fetch_completed_at` at the very end. This keeps the atomic block in mig-02 narrow. |
| sec-06 (UA constant) | `fetch_adv.py`, `fetch_ncen.py`, plus many others | obs-01 does not touch the `SEC_HEADERS` string; sec-06 is independent. | No conflict. |

---

## §5. Proposed Phase 1 design

### §5.1 `fetch_ncen.py` changes

1. Add `run_id = f"ncen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"` in `run()`.
2. Replace the inner loop body ([scripts/fetch_ncen.py:461-498](scripts/fetch_ncen.py:461)) with:
   - After `find_ncen_filing(cik)` succeeds: open a short-lived connection, call `get_or_create_manifest_row(con, source_type="NCEN", object_type="XML", source_url=..., accession_number=filing["accession"], run_id=run_id, object_key=filing["accession"], fetch_status="fetching", fetch_started_at=...)`. Skip fetch if an existing manifest row has `fetch_status='complete'` for this accession (idempotency).
   - Download + parse as today.
   - On success: `update_manifest_status(con, manifest_id, "complete", fetch_completed_at=..., http_code=200, source_bytes=len(xml))`.
   - On download failure: `update_manifest_status(con, manifest_id, "failed", ...)`.
3. After `insert_records(...)` for a given CIK, compute rows contributed and call `write_impact(con, manifest_id=manifest_id, target_table="ncen_adviser_map", unit_type="registrant_report", unit_key_json=json.dumps({"registrant_cik":cik,"report_date":filing["report_date"]}), report_date=..., rows_staged=len(records), load_status="loaded")`.
4. Leave `record_freshness("ncen_adviser_map")` in place ([:561](scripts/fetch_ncen.py:561)) — that's the data_freshness side; obs-01 adds the manifest side only.

Estimated extra write volume per full run: ~12,000 manifest rows + ~12,000 impact rows (one per fund CIK that has an N-CEN). Both tables are append-only; the 25-row CHECKPOINT cadence already in place absorbs this.

### §5.2 `fetch_adv.py` changes

1. Add `run_id = f"adv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"` in `main()`.
2. Before `download_adv_zip()`: open a connection, call `get_or_create_manifest_row(con, source_type="ADV", object_type="ZIP", source_url=ADV_ZIP_URL, accession_number=None, run_id=run_id, object_key=f"ADV_BULK:{os.path.basename(ADV_ZIP_URL)}", fetch_status="fetching", fetch_started_at=...)`. Close.
3. After the download/extract: `update_manifest_status(con, manifest_id, "downloaded", source_bytes=len(r.content), local_path=csv_path)` (new intermediate status is optional; an alternative is to keep `fetching` → `complete` only).
4. After `save_to_duckdb` finishes and `record_freshness` has stamped: call `write_impact(con, manifest_id=manifest_id, target_table="adv_managers", unit_type="bulk_load", unit_key_json=json.dumps({"filename":os.path.basename(ADV_ZIP_URL)}), report_date=today, rows_staged=row_count, load_status="loaded", promote_status="promoted", rows_promoted=row_count, promoted_at=now())`. (Direct-write = promoted at write time, same as fetch_market.py [:745-750](scripts/fetch_market.py:745).)
5. Finally: `update_manifest_status(con, manifest_id, "complete", fetch_completed_at=..., http_code=200)`.

Interaction with mig-02: the manifest row exists throughout the DROP+CREATE window. That is acceptable — the manifest row is append-only and its existence does not imply the table is readable. mig-02 will later make the canonical write atomic; no rewrite of obs-01's manifest code is needed at that point.

Estimated extra write volume per run: 1 manifest + 1 impact. Negligible.

### §5.3 `migrations/001` changes

**None required.** `source_type` is free-text VARCHAR with documentation comments already listing `NCEN` and `ADV` ([scripts/migrations/001_pipeline_control_plane.py:55](scripts/migrations/001_pipeline_control_plane.py:55)). The schema comment for `object_type` already includes `ZIP` and `XML` ([:56](scripts/migrations/001_pipeline_control_plane.py:56)). No allow-list changes in `id_allocator.py`.

### §5.4 Amendments

N-CEN amendments (`N-CEN/A`) are not handled by `fetch_ncen.py` today; `find_ncen_filing` only picks the first `N-CEN` entry and ignores `N-CEN/A` ([scripts/fetch_ncen.py:106-107](scripts/fetch_ncen.py:106)). This is an existing gap, not an obs-01 regression. **Out of scope.** If a future ticket adds amendment handling, `supersede_manifest(...)` is the correct tool and would need a companion migration to add `prior_accession` population logic. ADV bulk is a full snapshot — amendments don't apply.

### §5.5 Test plan (Phase 1)

1. **Schema**: before/after row counts on `ingestion_manifest` (`source_type IN ('NCEN','ADV')`) and `ingestion_impacts` (`target_table IN ('ncen_adviser_map','adv_managers')`). Must be 0 before, non-zero after.
2. **Idempotency**: re-run `fetch_ncen.py --test` twice on the same 10 CIKs. Second run must see all 10 manifest rows as `complete` and short-circuit without re-downloading. `ncen_adviser_map` row count must not change.
3. **Idempotency (ADV)**: re-run `fetch_adv.py` twice. Second run must update the same manifest row (same `object_key`) and not create a duplicate. `adv_managers` row count may vary slightly as SEC publishes a new month; manifest `object_key` should change when the URL's filename changes.
4. **Failure path**: inject a 404 into `find_ncen_filing` for one CIK and confirm the `fetch_status='failed'` manifest row lands with a populated `error_message`.
5. **admin dashboard**: visit `/admin/pipelines` (or equivalent) after a run and confirm N-CEN and ADV cards show `last_run`, `Age`, and `Status` populated (obs-02 completes the dashboard wiring; obs-01 produces the data those queries read).
6. **Regression**: `fund_holdings_v2` impact rows must not be perturbed. `COUNT(*) FROM ingestion_impacts WHERE target_table='fund_holdings_v2'` equal before and after.

### §5.6 Acceptance criteria

- After a full `fetch_ncen.py` run, `ingestion_manifest` has ≥ 1 row with `source_type='NCEN'` per registrant CIK touched; `ingestion_impacts` has matching rows with `target_table='ncen_adviser_map'`.
- After a full `fetch_adv.py` run, `ingestion_manifest` has exactly one row with `source_type='ADV'` for the current ZIP's `object_key`; `ingestion_impacts` has exactly one matching row with `target_table='adv_managers'`.
- Neither fetcher writes `ingestion_manifest` or `ingestion_impacts` via anything other than `pipeline.manifest` helpers (grep audit).
- `data_freshness` for both `ncen_adviser_map` and `adv_managers` is current (fresh timestamp).
- `make check-freshness` (see [scripts/check_freshness.py](scripts/check_freshness.py)) exits 0.
- Admin-dashboard pipeline cards for N-CEN and ADV render populated.

---

## §6. Open questions (flagged for Phase 1 prompt)

1. **N-CEN report_date field.** `fetch_ncen.py` reads `reportPeriodDate` from the XML into records, but does not retain it at the filing level in `ncen_adviser_map`. For the `report_date` column on `ingestion_impacts`, use `filing["filing_date"]` as a fallback when `reportPeriodDate` is missing. Confirm in Phase 1.
2. **ADV snapshot cadence.** The hardcoded ZIP URL ([scripts/fetch_adv.py:29-33](scripts/fetch_adv.py:29)) pins the 2026-03 edition. If a later run updates the URL to `ia040226.zip`, the `object_key` changes and a new manifest row is created — desired behavior. Confirm no one is running against the hardcoded URL in a loop expecting new data from the same `object_key`.
3. **Entity-sync interaction.** `fetch_ncen.py` calls `entity_sync.sync_from_ncen_row(...)` per record when `--staging` and entity tables exist ([:487-498](scripts/fetch_ncen.py:487)). This pre-dates the manifest framework and writes to `entity_identifiers_staging` / `pending_entity_resolution`. obs-01 does not touch that path. Phase 1 should verify that `manifest_id` is *not* passed into `entity_sync.sync_from_ncen_row` today (grep to confirm), so we have no manifest-FK work to do.
4. **Parser version / schema version.** `ingestion_manifest` has `parser_version` and `schema_version` columns ([scripts/migrations/001_pipeline_control_plane.py:74-75](scripts/migrations/001_pipeline_control_plane.py:74)). `fetch_nport_v2` populates them; `fetch_market.py` does not. Recommendation: leave both NULL for obs-01 Phase 1 (match market) and address in obs-09 if it becomes load-bearing for the admin UI.

---

## §7. Phase 1 scope summary

**In:** N-CEN + ADV manifest/impact registration via `pipeline.manifest` helpers. No DDL changes. No allocator changes.

**Out:** ADV freshness log line (obs-02). ADV atomicity (mig-02). N-CEN amendment handling. `parser_version` / `schema_version` population. Admin dashboard UI wiring (Phase 2 / obs-02 finishing touches).
