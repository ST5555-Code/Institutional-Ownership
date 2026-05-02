# cef-asa-prep-investigation — PR-B scoping (read-only)

**Date:** 2026-05-02
**Cohort:** ASA Gold (CIK 0001230869), 350 UNKNOWN rows / $1.752B
**PR-B (downstream):** `cef-asa-period-backfill`
**Roadmap precedent:** PR #249 (cef-scoping), PR #250 (cef-residual-cleanup-adx)
**Source helpers:** `scripts/oneoff/cef_asa_prep_inspect.py` (read-only),
`data/working/asa_unknown_baseline.csv`,
`data/working/asa_nport_baseline.json`

---

## Headline finding

**ASA's UNKNOWN-side rows are byte-identical to ASA's N-PORT filings.**
The 350 UNKNOWN rows / $1.752B total exactly match the holdings extracted
from the 3 corresponding NPORT-P primary_doc.xml filings — same row count,
same per-security market_value_usd, same pct_of_nav, $0.00 delta in every
period.

This rewrites PR-B's scope. The original assumption — that we needed to
*populate* SYN_0001230869 companion rows via a v2 loader rerun, then flip
UNKNOWN — is wrong. The data is already in place; only the label is
wrong. PR-B becomes a **flip-and-relabel** operation similar to PR #250
(ADX), not a fetch-and-load.

---

## Question 1 — Loader rerun mechanism

### CLI surface (`scripts/pipeline/load_nport.py:1358`)

```
--quarter YYYY[Q1-4]   # DERA bulk load for full quarter
--monthly-topup        # XML per-accession top-up for current calendar quarter
--month YYYY-MM        # XML top-up for one month
--zip <path>           # local DERA ZIP override
--exclude-file <path>  # series_id exclusion list
--dry-run / --auto-approve / --staging
```

There is **no `--cik` flag and no `--period` flag**. The loader is scoped
to calendar quarters (DERA) or filing months (XML top-up). A per-CIK
rerun via the existing CLI is not directly supported.

### Per-CIK rerun feasibility (XML top-up path)

`_fetch_xml_topup` (`scripts/pipeline/load_nport.py:530`) calls
`edgar.get_filings(year, quarter, form="NPORT-P")` and anti-joins
`ingestion_manifest` for already-loaded accessions. For ASA:

- The 3 ASA accessions matching UNKNOWN periods are **NOT in
  `ingestion_manifest`** (verified: `SELECT ... WHERE
  accession_number IN (...)` returns 0 rows). The UNKNOWN cohort was
  written by a legacy synth path (`accession_number =
  BACKFILL_MIG015_UNKNOWN_<period>`, `backfill_quality = 'inferred'`),
  not by the v2 pipeline.
- Therefore `--month 2025-01`, `--month 2025-03`, `--month 2025-09`
  would re-fetch ASA's filings — but would also re-fetch every other
  fund's NPORT-P filing for those months. Far too broad.
- Series_id fallback: ASA's NPORT-P metadata returns
  `series_id = None` (CEFs don't report a series). `_fetch_xml_topup`
  line 619 would assign `f"{cik}_{accession}"`, e.g.
  `1230869_0001752724-25-018310` — **inconsistent with the existing
  2025-11 row's series_id `SYN_0001230869`**. Ingesting via v2 would
  create a fourth set of rows under a yet-different series_id.
- Amendment_strategy: `append_is_latest` keyed on `(series_id,
  report_month)` (`scripts/pipeline/load_nport.py:275`). UNKNOWN rows
  would NOT auto-flip to `is_latest=FALSE` when new rows arrive —
  different series_id means different amendment partition. A separate
  manual flip is required regardless of which path PR-B takes.

### Staging-twin policy

The v2 loader honours staging-twin: `run(scope)` writes to
`13f_staging.duckdb`, then `approve_and_promote(run_id)` snapshots prod
and copies staging→prod. `--staging` flag swaps prod for staging as
the target. This is the standard project pattern (memory:
*Staging workflow live (INF1)*).

### Recommended PR-B mechanism

Given the byte-identical match between UNKNOWN-side rows and N-PORT
filings, **a v2 loader rerun is unnecessary and wrong-shaped for PR-B**.
The data is already in `fund_holdings_v2`; it just needs to be
relabelled from `series_id='UNKNOWN'` to `series_id='SYN_0001230869'`
(matching the existing 2025-11 companion row's pattern).

Two viable mechanism options for PR-B Phase 4:

**Option A — direct flip-and-relabel (recommended).**
Write a oneoff harness `scripts/oneoff/cef_asa_period_backfill.py`
that, for each of the 3 UNKNOWN periods:
1. INSERTS new rows into `fund_holdings_v2` with `series_id =
   'SYN_0001230869'`, `is_latest = TRUE`, copying every other column
   from the existing UNKNOWN rows. New `accession_number` carries the
   real ASA accession (so the rows are sourceable to a primary_doc.xml
   URL); `backfill_quality` set to a value reflecting the relabel
   provenance (e.g., `relabel_from_unknown`).
2. UPDATEs the corresponding UNKNOWN rows to `is_latest = FALSE`.
Both writes go through the staging-twin pattern (write to staging,
diff, promote). Pattern mirrors PR #250.

**Option B — UPDATE in place.**
Single UPDATE per period setting `series_id = 'SYN_0001230869'` on the
existing rows. Simpler but breaks the `(series_id, report_month, cusip,
is_latest)` PK assumption that rows are immutable once written, and
loses the audit trail of "this row was originally UNKNOWN." Not
recommended.

In neither case does PR-B require touching the v2 loader code or
running `--month` / `--quarter`. The investigation closes the
"populate companion rows" branch of PR #249's scoping.

---

## Question 2 — Period coverage match

### UNKNOWN-cohort periods (prod)

| period  | rows | aum_usd       | distinct_cusip | distinct_isin |
|---------|------|---------------|----------------|---------------|
| 2024-11 | 108  | 439,912,633.43 | 13            | 64            |
| 2025-02 | 112  | 521,336,911.36 | 11            | 64            |
| 2025-08 | 130  | 791,235,386.08 | 13            | 70            |
| **Total** | **350** | **1,752,484,930.87** |              |              |

Note: Most ASA holdings are foreign micro-cap miners that don't carry
US CUSIPs — the parser fills `cusip='N/A'` and relies on ISIN. This is
expected, not a defect.

### EDGAR NPORT-P filings (24 total, ASA CIK 0001230869)

Filings matching UNKNOWN periods:

| filing_date | accession                | report_period |
|-------------|--------------------------|---------------|
| 2025-01-29  | 0001752724-25-018310     | 2024-11-30    |
| 2025-03-31  | 0001752724-25-075250     | 2025-02-28    |
| 2025-09-30  | 0001230869-25-000013     | 2025-08-31    |

**All 3 UNKNOWN periods have matching N-PORT filings on EDGAR. All
backfill-feasible. Zero blockers.**

### Existing 2025-11 SYN_0001230869 row (informational)

| period  | accession                                              | rows | aum_usd        |
|---------|--------------------------------------------------------|------|----------------|
| 2025-11 | BACKFILL_MIG015_1230869_0001049169-26-000039_2025-11   | 143  | 1,094,382,494.85 |

The 2025-11 row's source accession (`0001049169-26-000039`) does not
appear in ASA's NPORT-P filing list — the row was synthesized from a
non-N-PORT source (filer 0001049169 = Donnelley Financial Solutions,
a filing agent). This is informational only; PR-B targets the 3
UNKNOWN periods, not 2025-11.

ASA's other NPORT-P filings (21 filings spanning 2020-05-31 through
2025-08-31) are all on EDGAR but outside the UNKNOWN cohort — no
action required.

---

## Question 3 — AUM matching baseline

### Per-period parity (UNKNOWN side vs N-PORT side)

| period  | unknown_mv      | nport_mv        | delta    | delta_%   |
|---------|-----------------|-----------------|----------|-----------|
| 2024-11 | 439,912,633.43  | 439,912,633.43  | 0.0000   | 0.000000% |
| 2025-02 | 521,336,911.36  | 521,336,911.36  | 0.0000   | 0.000000% |
| 2025-08 | 791,235,386.08  | 791,235,386.08  | 0.0000   | 0.000000% |

### Per-row spot check (period 2025-08, top 5 by ISIN)

| isin            | unknown_mv    | nport_mv      | delta    |
|-----------------|---------------|---------------|----------|
| CA36270K1021    | 94,452,979.94 | 94,452,979.94 | 0.000000 |
| CA03062D8035    | 75,944,262.58 | 75,944,262.58 | 0.000000 |
| CA68634K1066    | 68,572,000.00 | 68,572,000.00 | 0.000000 |
| CA29446Y5020    | 42,850,693.56 | 42,850,693.56 | 0.000000 |
| AU000000PDI8    | 32,313,624.34 | 32,313,624.34 | 0.000000 |

### Net assets context (NAV vs holdings sum)

| period  | nport_nav       | nport_mv_sum    | nav-cash residual |
|---------|-----------------|-----------------|-------------------|
| 2024-11 | 444,153,651.52  | 439,912,633.43  | 4,241,018.09 (~0.96% NAV) |
| 2025-02 | 523,572,250.70  | 521,336,911.36  | 2,235,339.34 (~0.43% NAV) |
| 2025-08 | 791,627,594.31  | 791,235,386.08  | 392,208.23 (~0.05% NAV) |

The residuals are cash + receivables/payables not booked as portfolio
holdings — expected.

### Threshold recommendation

Default thresholds for PR-B Phase 4 verification:

- **Per-(period, security) MV delta ≤ $0.01:** acceptable (rounding noise only).
- **$0.01 < delta ≤ 0.1% of row MV:** surface for chat review.
- **delta > 0.1% of row MV, OR any row count mismatch, OR any
  per-period total delta ≠ $0.00:** halt and re-investigate.

Rationale: UNKNOWN-side rows were synthesized from the same
primary_doc.xml the v2 path would parse, using the same
`parse_nport_xml` parser (`scripts/pipeline/nport_parsers.py`). Any
non-zero per-period delta indicates either a parser regression, a
schema drift in the source XML between synth-time and rerun-time, or
a bug in the relabel logic. None of those should be tolerated. The
normal "±5% / ±15%" thresholds proposed in the original prompt are
too loose for this cohort because the data is identical-by-construction.

---

## Other findings worth flagging

1. **Parser-key gotcha for future PR-B work:**
   `parse_nport_xml` returns holdings dicts keyed on `val_usd` (not
   `value_usd`). Any oneoff that sums holdings must use the right
   key — see `scripts/pipeline/nport_parsers.py:114`.

2. **CEF series_id semantics:**
   ASA's NPORT-P primary_doc.xml has no `<seriesId>` element — CEFs
   report at the registrant level only. `_fetch_xml_topup` line 619
   falls back to `f"{cik}_{accession}"`. PR-B should override this
   to `SYN_0001230869` to maintain consistency with the existing
   2025-11 row, OR adopt a different series_id convention for the
   2025-11 row at the same time.

3. **2025-11 row provenance:**
   The existing 2025-11 SYN_0001230869 row's source accession
   (0001049169-26-000039) is from Donnelley Financial Solutions, not
   from ASA's own NPORT-P filings. Out of PR-B's scope but flagging
   for cef-residual-cleanup roadmap.

4. **`backfill_quality` taxonomy:**
   UNKNOWN cohort uses `backfill_quality='inferred'`. The 2025-11
   companion row has `backfill_quality=NULL` (from the snapshot
   query). PR-B should standardise on a value that documents the
   relabel provenance — e.g., `relabel_from_unknown` or
   `direct_nport_match`.

5. **No pipeline lock concern for PR-B:**
   Direct `fund_holdings_v2` writes through a oneoff harness
   bypass the v2 loader's lock. This is consistent with PR #250's
   ADX cleanup pattern, which used a manifest-driven flip script
   rather than the loader.

---

## Reproduction

```
python3 -u scripts/oneoff/cef_asa_prep_inspect.py
```

Outputs:
- `data/working/asa_unknown_baseline.csv` — full UNKNOWN-side row
  detail for all 350 rows across 3 periods.
- `data/working/asa_nport_baseline.json` — per-period N-PORT
  metadata + top-10 holdings for delta comparison.
- stdout — Probes 1–3 summary numbers used in this doc.

Read-only verified: `grep -iE
'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b'` on the
oneoff matches only `sys.path.insert`.
