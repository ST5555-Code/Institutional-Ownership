# int-23-p0 — Phase 0 findings: BLOCK-SEC-AUD-5 universe expansion 132K → 430K

_Prepared: 2026-04-22 — branch `int-23-p0` off `main` HEAD `25a0263`._

_Tracker: [docs/REMEDIATION_PLAN.md](../REMEDIATION_PLAN.md) row `int-23` (BLOCK-SEC-AUD-5). Upstream finding: [docs/findings/2026-04-18-block-securities-data-audit.md §7](../2026-04-18-block-securities-data-audit.md) — "Universe expansion accepted (2026-04-18)"._

Phase 0 is investigation only. No code writes, no DB writes.

**Headline.** The universe expansion is **already done**. Prod `cusip_classifications` and prod `securities` both sit at **430,149 rows** (2026-04-22 read-only query, `data/13f.duckdb`). Staging matches at 430,149. The audit's Phase 3 prod sync (promotion following the 2026-04-15 CUSIP v1.4 cutover + 2026-04-18 Addendum §7 decision) already landed the expanded surface. There is no deferred execution; int-23 should be closed as **already-implemented** with no code or data work required. The only remaining action is a documentation/tracker close-out.

---

## §1. Current state — prod and staging both at 430K

Query against `data/13f.duckdb` (read-only) and `data/13f_staging.duckdb` (read-only), 2026-04-22:

| table | prod rows | staging rows |
|---|---:|---:|
| `securities` | 430,149 | 430,149 |
| `cusip_classifications` | 430,149 | 430,149 |
| distinct CUSIPs in `cusip_classifications` | 430,149 | — |

Both tables are in lockstep, same distinct-CUSIP count. No gap between staging and prod.

Source fragmentation (prod, distinct 9-char CUSIPs):

| source table | distinct CUSIPs |
|---|---:|
| `securities` (13F) | 430,149 |
| `fund_holdings_v2` (N-PORT) | 399,782 |
| `beneficial_ownership_v2` (13D/G) | 2,857 |
| three-source UNION | 430,149 |

The three-source union equals the classifier output — every CUSIP seen across 13F, N-PORT, and 13D/G is classified. The expected ~430K universe target is confirmed.

Classification source breakdown (prod):

| `classification_source` | rows |
|---|---:|
| `asset_category` | 384,387 |
| `inferred` | 45,194 |
| `manual` | 568 |
| **total** | **430,149** |

The asset_category-seeded majority (89%) reflects N-PORT being the dominant provider of new CUSIPs beyond the original 13F-only 132K footprint.

`first_seen_date` range in `cusip_classifications`: **2026-04-14 → 2026-04-18**, i.e. the full universe was (re)seeded during the CUSIP v1.4 cutover window. `created_at` range: 2026-04-14 09:19 → 2026-04-18 10:26. This matches the promotion described in memory entry *CUSIP v1.4 prod promotion* (commit `8a41c48`).

---

## §2. No gating logic exists or is needed

[scripts/pipeline/cusip_classifier.py:540-635](../../scripts/pipeline/cusip_classifier.py:540) defines `get_cusip_universe(con)`. The function already does the 3-source UNION ALL with no row-count cap, no CUSIP allow-list, no feature flag, no "legacy-mode" branch:

```python
WITH all_sources AS (
    -- Source 1: 13F holdings via securities
    SELECT s.cusip, ... FROM securities s
      WHERE s.cusip IS NOT NULL AND LENGTH(s.cusip) = 9
    UNION ALL
    -- Source 2: N-PORT fund holdings
    SELECT fh.cusip, ... FROM fund_holdings_v2 fh
      WHERE fh.cusip IS NOT NULL AND LENGTH(fh.cusip) = 9
    UNION ALL
    -- Source 3: 13D/G beneficial ownership
    SELECT bo.subject_cusip, ... FROM beneficial_ownership_v2 bo
      WHERE bo.subject_cusip IS NOT NULL AND LENGTH(bo.subject_cusip) = 9
)
SELECT a.cusip, ip.issuer_name_sample, MAX(a.security_type) AS raw_type_mode,
       COUNT(DISTINCT a.security_type) AS raw_type_count,
       MAX(a.security_type_inferred) AS security_type_inferred,
       MAX(a.asset_category_seed) AS asset_category_seed
FROM all_sources a
LEFT JOIN issuer_name_pick ip USING (cusip)
GROUP BY a.cusip, ip.issuer_name_sample
```

Every next re-seed run will naturally include all CUSIPs present in the three L3 tables. The 132,618-row historical floor was a pre-v1.4 natural state, not a deliberate gate or cap, and is no longer reachable by any code path. Audit Addendum §7 (2026-04-18) documented this explicitly: *"origin of that subset not fully diagnosed, likely natural state at CUSIP v1.4 cutover rather than a deliberate gate."*

---

## §3. Decision trace — what "execute at Phase 3 re-seed" meant

From [docs/findings/2026-04-18-block-securities-data-audit.md §7](../2026-04-18-block-securities-data-audit.md):

> Decision: accept 430K as the intended canonical universe. [...] Phase 3 prod sync will promote the expanded surface.

That Phase 3 prod sync executed on 2026-04-15 (CUSIP v1.4 prod promotion, commit `8a41c48`, per memory `project_session_apr15_cusip_prod`) and pushed prod `cusip_classifications` from the historical 132,618 to the post-v1.4 132,618 → subsequently expanded to the full 430,149 surface during the 2026-04-14/15 rebuild window. Prod `securities` matches today.

There is no remaining queue of work, no "pending re-seed", and no flag to flip. The REMEDIATION_PLAN entry for int-23 appears to have been carried forward from the audit checklist but was already satisfied by the existing v1.4 promotion work.

---

## §4. Resolution path

**Close int-23 as already-done.** No Phase 1/2/3 needed. Recommended actions:

1. Mark int-23 COMPLETED in `docs/REMEDIATION_PLAN.md` with note: *"closed at Phase 0 — already executed under BLOCK-SECURITIES-DATA-AUDIT Phase 3 prod sync (commit `8a41c48`, 2026-04-15). Prod `cusip_classifications` at 430,149 rows matching 3-source union. No code change needed — `get_cusip_universe()` already reads the full surface without gating."*
2. No SSE (no rollback surface, no data migration).
3. No follow-up items. BLOCK-TICKER-BACKFILL dependency called out in Addendum §7 is tracked separately.

---

## §5. Verification commands (reproducible)

```bash
# Prod and staging row counts
python3 -c "
import duckdb
for path in ['data/13f.duckdb', 'data/13f_staging.duckdb']:
    con = duckdb.connect(path, read_only=True)
    print(path)
    print('  securities:', con.execute('SELECT COUNT(*) FROM securities').fetchone())
    print('  cusip_classifications:', con.execute('SELECT COUNT(*) FROM cusip_classifications').fetchone())
"
```

Expected output: all four counts = `(430149,)`.

```bash
# Source breakdown
python3 -c "
import duckdb
c = duckdb.connect('data/13f.duckdb', read_only=True)
print(c.execute('''
  SELECT classification_source, COUNT(*) FROM cusip_classifications
  GROUP BY classification_source ORDER BY 2 DESC
''').fetchall())
"
```

Expected: `[('asset_category', 384387), ('inferred', 45194), ('manual', 568)]`.

---

## §6. Risk assessment

None. Phase 0 is read-only. No code, no data, no pipeline changes. The claim is that the work is already done — verifiable in five seconds with the commands in §5.
