"""Phase 1.2 - master inventory of fund-strategy 'unknown' rows.

Read-only audit. Two sources combined:
  1. fund_universe rows where fund_strategy IS NULL (display 'unknown')
  2. fund_holdings_v2 (is_latest=TRUE) rows with no fund_universe match

fund_universe.fund_strategy IS NULL is currently 0 (post PR #245), so the
unknown bucket comes entirely from holdings orphans.
"""
from __future__ import annotations
import csv
import os
import duckdb

DB = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
con = duckdb.connect(DB, read_only=True)

nu_total = con.execute("SELECT COUNT(*) FROM fund_universe").fetchone()[0]
nu_null = con.execute("SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IS NULL").fetchone()[0]
print(f"fund_universe rows: {nu_total:,}  NULL strategy: {nu_null:,}")

agg_q = """
WITH latest AS (
    SELECT series_id, fund_name, fund_cik, market_value_usd
    FROM fund_holdings_v2
    WHERE is_latest = TRUE
)
SELECT
    l.series_id,
    ANY_VALUE(l.fund_name) AS sample_name,
    ANY_VALUE(l.fund_cik)  AS sample_cik,
    COUNT(*)               AS row_count,
    SUM(COALESCE(l.market_value_usd,0))/1e9 AS aum_billions,
    COUNT(DISTINCT l.fund_name) AS distinct_names,
    COUNT(DISTINCT l.fund_cik)  AS distinct_ciks
FROM latest l
LEFT JOIN fund_universe fu USING(series_id)
WHERE fu.series_id IS NULL
GROUP BY l.series_id
ORDER BY aum_billions DESC NULLS LAST
"""
orphans = con.execute(agg_q).fetchall()
total_rows = sum(r[3] for r in orphans)
total_aum = sum((r[4] or 0) for r in orphans)
print(f"orphan series count: {len(orphans):,}  rows (is_latest): {total_rows:,}  AUM: ${total_aum:,.2f}B")

unknown_lit = next((r for r in orphans if r[0] == 'UNKNOWN'), None)
if unknown_lit:
    print(f"Cohort A (series_id='UNKNOWN'): rows={unknown_lit[3]:,}  AUM=${unknown_lit[4] or 0:,.2f}B  distinct_names={unknown_lit[5]} distinct_ciks={unknown_lit[6]}")

print("\nTop 50 named orphan series by AUM:")
shown = 0
for r in orphans:
    if r[0] == 'UNKNOWN':
        continue
    print(f"  {r[0]:<14} aum=${r[4] or 0:>9,.3f}B rows={r[3]:>6,d} names={r[5]} ciks={r[6]} | {r[1][:65] if r[1] else ''}")
    shown += 1
    if shown >= 50:
        break

out = os.path.join(os.path.dirname(__file__), '_unknown_orphans.csv')
with open(out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['series_id', 'sample_name', 'sample_cik', 'row_count', 'aum_billions', 'distinct_names', 'distinct_ciks'])
    for r in orphans:
        w.writerow([r[0], r[1], r[2], r[3], f"{r[4] or 0:.6f}", r[5], r[6]])
print(f"\nAll named orphans CSV -> {out}  ({len(orphans)} rows)")
