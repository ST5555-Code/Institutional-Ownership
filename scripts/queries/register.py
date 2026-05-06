"""Register / shareholder-list queries (query1..query16, summary)."""
import logging

import pandas as pd

from config import (
    QUARTERS,
)
from cache import (
    cached,
    CACHE_KEY_SUMMARY,
)
from serializers import (
    clean_for_json,
    df_to_records,
    resolve_filer_names_in_records,
    _13f_entity_footnote,
    get_subadviser_note,
)
from .common import (
    LQ,
    FQ,
    PQ,
    _rollup_name_sql,
    get_db,
    has_table,
    _quarter_to_date,
    _resolve_pct_of_so_denom,
    get_cusip,
    _fund_type_label,
    match_nport_family,
    get_nport_coverage,
    get_nport_children_batch,
    get_nport_children_q2,
)

logger = logging.getLogger(__name__)

def query1(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Current shareholder register — two-level parent/fund hierarchy.
    Batched: parents + all 13F children fetched in 2 queries total."""
    rn = _rollup_name_sql('h', rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)

        # Query 1: parents (aggregated by inst_parent_name)
        parents = con.execute(f"""
            WITH by_fund AS (
                SELECT
                    COALESCE({rn}, h.inst_parent_name, h.manager_name) as parent_name,
                    h.fund_name,
                    h.cik,
                    COALESCE(h.manager_type, 'unknown') as type,
                    h.market_value_live,
                    h.shares,
                    h.pct_of_so
                FROM holdings_v2 h
                WHERE h.quarter = '{quarter}'
                  AND (h.ticker = ? OR h.cusip = ?)
                  AND h.is_latest = TRUE
            )
            SELECT
                parent_name,
                MAX(type) as type,
                SUM(market_value_live) as total_value_live,
                SUM(shares) as total_shares,
                SUM(pct_of_so) as pct_so,
                COUNT(DISTINCT fund_name) as child_count
            FROM by_fund
            GROUP BY parent_name
            ORDER BY total_value_live DESC NULLS LAST
            LIMIT 25
        """, [ticker, cusip]).fetchdf()

        parent_names = parents['parent_name'].tolist()
        if not parent_names:
            return []

        # R14: Fetch AUM in $M — ADV data first, 13F total value as fallback
        aum_map = {}
        try:
            aum_df = con.execute("""
                SELECT parent_name, SUM(aum_total) / 1e6 as aum_mm
                FROM managers WHERE aum_total IS NOT NULL AND aum_total > 1e9
                GROUP BY parent_name
            """).fetchdf()
            aum_map = {r['parent_name']: int(r['aum_mm']) for _, r in aum_df.iterrows() if r['aum_mm']}

            ph_aum = ','.join(['?'] * len(parent_names))
            fallback_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name) as parent_name, SUM(market_value_usd) / 1e6 as val_mm
                FROM holdings_v2 WHERE quarter = '{quarter}' AND COALESCE({rn}, inst_parent_name) IN ({ph_aum}) AND is_latest = TRUE
                GROUP BY COALESCE({rn}, inst_parent_name)
            """, parent_names).fetchdf()
            for _, r in fallback_df.iterrows():
                pn = r['parent_name']
                if pn not in aum_map and r['val_mm'] and r['val_mm'] > 0:
                    aum_map[pn] = int(r['val_mm'])
        except Exception:
            logger.debug("optional enrichment failed: aum_fallback", exc_info=True)

        # N-PORT coverage % per parent (from summary_by_parent)
        # INF34: summary_by_parent has one row per (quarter, inst_parent_name,
        # rollup_type) since migration 004 — filter on current rollup_type to
        # avoid duplicated rows / arbitrary row selection.
        coverage_map = {}
        try:
            cov_df = con.execute(f"""
                SELECT inst_parent_name, nport_coverage_pct
                FROM summary_by_parent
                WHERE quarter = '{quarter}' AND inst_parent_name IN ({ph_aum})
                  AND rollup_type = ?
            """, parent_names + [rollup_type]).fetchdf()
            coverage_map = {r['inst_parent_name']: r['nport_coverage_pct']
                            for _, r in cov_df.iterrows()
                            if r['nport_coverage_pct'] is not None}
        except Exception:
            logger.debug("optional enrichment failed: coverage_map", exc_info=True)

        # Query 2: ALL 13F children for all parents in one pass
        ph = ','.join(['?'] * len(parent_names))
        all_children_df = con.execute(f"""
            SELECT
                COALESCE({rn}, h.inst_parent_name, h.manager_name) as parent_name,
                h.fund_name as institution,
                COALESCE(h.manager_type, 'unknown') as type,
                SUM(h.market_value_live) as value_live,
                SUM(h.shares) as shares,
                SUM(h.pct_of_so) as pct_so
            FROM holdings_v2 h
            WHERE h.quarter = '{quarter}'
              AND (h.ticker = ? OR h.cusip = ?)
              AND COALESCE({rn}, h.inst_parent_name, h.manager_name) IN ({ph})
              AND h.is_latest = TRUE
            GROUP BY parent_name, h.fund_name, type
            ORDER BY parent_name, value_live DESC NULLS LAST
        """, [ticker, cusip] + parent_names).fetchdf()

        # Group 13F children by parent + add footnotes for known entities
        children_by_parent = {}
        for _, row in all_children_df.iterrows():
            pname = row['parent_name']
            if pname not in children_by_parent:
                children_by_parent[pname] = []
            if len(children_by_parent[pname]) < 8:
                note = _13f_entity_footnote(row['institution'])
                children_by_parent[pname].append({
                    'institution': row['institution'],
                    'value_live': row['value_live'],
                    'shares': row['shares'],
                    'pct_so': row['pct_so'],
                    'type': row['type'],
                    'source': '13F entity' if note else '13F',
                    'subadviser_note': note,
                })

        # N-PORT fund series lookup — batched to eliminate N+1 (ARCH-2A.1).
        nport_by_parent = {}
        if has_table('fund_holdings_v2'):
            nport_by_parent = get_nport_children_batch(parent_names, ticker, quarter, con, limit=5)
            for kids in nport_by_parent.values():
                for k in kids:
                    k['type'] = _fund_type_label(k.get('fund_strategy'))

        # Build results — prefer N-PORT children, supplement with 13F entities
        results = []
        for rank, (_, parent) in enumerate(parents.iterrows(), 1):
            pname = parent['parent_name']
            nport_kids = nport_by_parent.get(pname, [])
            f13_kids = children_by_parent.get(pname, [])

            # Merge: N-PORT funds first, then 13F entities not covered by N-PORT
            merged = list(nport_kids)
            # Null-safe handling: skip rows where institution is NULL rather than crash.
            # Added post-int-22 as defensive hygiene. Surfaces upstream NULL-institution
            # bugs via silent filtering rather than HTTP 500. If NULL rows appear at scale,
            # investigate upstream data plane (loader promote, enrichment pipeline) before
            # removing this guard.
            nport_names = {(c['institution'] or '').lower() for c in nport_kids if c.get('institution')}
            for c in f13_kids:
                inst = (c.get('institution') or '').lower()
                if inst and inst not in nport_names and c.get('subadviser_note'):
                    merged.append(c)

            # Only show N-PORT children as expandable. No N-PORT = flat row.
            has_nport = len(nport_kids) > 0
            # Limit to top 5 N-PORT children by value
            children_to_show = sorted(nport_kids, key=lambda c: c.get('value_live') or 0, reverse=True)[:5]
            source = 'N-PORT' if has_nport else '13F'

            parent_aum = aum_map.get(pname)
            # % of AUM: position value / AUM (both in $M after conversion)
            parent_pct_aum = None
            if parent_aum and parent['total_value_live']:
                val_mm = parent['total_value_live'] / 1e6
                parent_pct_aum = round(val_mm / parent_aum * 100, 2) if parent_aum > 0 else None
            results.append({
                'rank': rank,
                'institution': pname,
                'value_live': parent['total_value_live'],
                'shares': parent['total_shares'],
                'pct_so': parent['pct_so'],
                'aum': parent_aum,
                'pct_aum': parent_pct_aum,
                'nport_cov': coverage_map.get(pname),
                'type': parent['type'],
                'is_parent': has_nport and len(children_to_show) > 0,
                'child_count': len(children_to_show),
                'level': 0,
                'source': source,
                'subadviser_note': get_subadviser_note(pname) if not has_nport else None,
            })

            if has_nport and children_to_show:
                for child_rank, c in enumerate(children_to_show, 1):
                    results.append({
                        'rank': child_rank,
                        'institution': c.get('institution'),
                        'value_live': c.get('value_live'),
                        'shares': c.get('shares'),
                        'pct_so': c.get('pct_so'),
                        'aum': c.get('aum'),
                        'pct_aum': c.get('pct_aum'),
                        'type': c.get('type', parent['type']),
                        'is_parent': False,
                        'child_count': 0,
                        'level': 1,
                        'source': c.get('source', '13F'),
                        'subadviser_note': c.get('subadviser_note'),
                    })
        # Compute all-investor totals (beyond top 25) and by-type totals
        all_totals_df = con.execute(f"""
            SELECT
                COALESCE(MAX(h.manager_type), 'unknown') as type,
                COALESCE({rn}, h.inst_parent_name, h.manager_name) as parent_name,
                SUM(h.market_value_live) as total_value,
                SUM(h.shares) as total_shares,
                SUM(h.pct_of_so) as pct_so
            FROM holdings_v2 h
            WHERE h.quarter = '{quarter}' AND (h.ticker = ? OR h.cusip = ?) AND h.is_latest = TRUE
            GROUP BY parent_name
        """, [ticker, cusip]).fetchdf()

        all_totals = {
            'value_live': float(all_totals_df['total_value'].sum()) if len(all_totals_df) else 0,
            'shares': float(all_totals_df['total_shares'].sum()) if len(all_totals_df) else 0,
            'pct_so': float(all_totals_df['pct_so'].sum()) if len(all_totals_df) else 0,
            'count': len(all_totals_df),
        }
        # By-type totals
        type_totals = {}
        for _, trow in all_totals_df.iterrows():
            t = trow['type'] or 'unknown'
            if t not in type_totals:
                type_totals[t] = {'value_live': 0, 'shares': 0, 'pct_so': 0, 'count': 0}
            type_totals[t]['value_live'] += float(trow['total_value'] or 0)
            type_totals[t]['shares'] += float(trow['total_shares'] or 0)
            type_totals[t]['pct_so'] += float(trow['pct_so'] or 0)
            type_totals[t]['count'] += 1

        return {'rows': results, 'all_totals': all_totals, 'type_totals': type_totals}
    finally:
        pass  # connection managed by thread-local cache



def query2(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """4-quarter ownership change (Q1 vs Q4 2025)."""
    rn = _rollup_name_sql('', rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        # Top 15 parents by Q4 value
        top_parents = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                   SUM(market_value_live) as parent_val
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND (ticker = ? OR cusip = ?) AND is_latest = TRUE
            GROUP BY parent_name
            ORDER BY parent_val DESC NULLS LAST
            LIMIT 25
        """, [ticker, cusip]).fetchdf()['parent_name'].tolist()

        q2 = con.execute(f"""
            WITH q1_agg AS (
                SELECT cik, manager_name,
                       COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                       MAX(manager_type) as manager_type,
                       SUM(shares) as q1_shares
                FROM holdings_v2
                WHERE quarter = '{FQ}' AND (ticker = ? OR cusip = ?) AND is_latest = TRUE
                GROUP BY cik, manager_name, parent_name
            ),
            q4_agg AS (
                SELECT cik, manager_name,
                       COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                       MAX(manager_type) as manager_type,
                       SUM(shares) as q4_shares
                FROM holdings_v2
                WHERE quarter = '{quarter}' AND (ticker = ? OR cusip = ?) AND is_latest = TRUE
                GROUP BY cik, manager_name, parent_name
            ),
            combined AS (
                SELECT
                    COALESCE(q4.parent_name, q1.parent_name) as parent_name,
                    COALESCE(q4.manager_name, q1.manager_name) as fund_name,
                    COALESCE(q4.cik, q1.cik) as cik,
                    COALESCE(q4.manager_type, q1.manager_type, 'unknown') as type,
                    q1.q1_shares,
                    q4.q4_shares,
                    COALESCE(q4.q4_shares, 0) - COALESCE(q1.q1_shares, 0) as change_shares,
                    CASE
                        WHEN q1.q1_shares > 0 AND q4.q4_shares IS NOT NULL
                        THEN ROUND((q4.q4_shares - q1.q1_shares) * 100.0 / q1.q1_shares, 1)
                        WHEN q1.q1_shares IS NULL THEN NULL
                        ELSE -100.0
                    END as change_pct,
                    CASE WHEN q1.q1_shares IS NULL THEN true ELSE false END as is_entry,
                    CASE WHEN q4.q4_shares IS NULL THEN true ELSE false END as is_exit
                FROM q4_agg q4
                FULL OUTER JOIN q1_agg q1 ON q4.cik = q1.cik AND q4.manager_name = q1.manager_name
            )
            SELECT * FROM combined
            ORDER BY parent_name, ABS(change_shares) DESC
        """, [ticker, cusip, ticker, cusip]).fetchdf()

        results = []
        # Main holdings (top parents, not entries/exits)
        q2_top = q2[q2['parent_name'].isin(top_parents) & ~q2['is_entry'] & ~q2['is_exit']]

        # Count distinct funds per parent
        parent_child_counts = q2_top.groupby('parent_name')['fund_name'].nunique()

        # Process parents: try N-PORT children with Q1/Q4 comparison, fall back to 13F
        seen_parents = set()
        for _, row in q2_top.iterrows():
            pname = row['parent_name']
            if pname in seen_parents:
                continue
            seen_parents.add(pname)

            parent_rows = q2_top[q2_top['parent_name'] == pname]
            p_q1 = parent_rows['q1_shares'].sum()
            p_q4 = parent_rows['q4_shares'].sum()
            p_chg = p_q4 - p_q1
            p_pct = (p_chg / p_q1 * 100) if p_q1 > 0 else None

            # Try N-PORT children with Q1/Q4 comparison
            nport_kids = get_nport_children_q2(pname, ticker, con, limit=5)
            if nport_kids and len(nport_kids) >= 2:
                src = 'N-PORT'
                child_list = nport_kids
            else:
                src = '13F'
                # 13F fallback: use the existing q2_top rows for this parent
                child_list = []
                for _, cr in parent_rows.iterrows():
                    child_list.append({
                        'fund_name': cr['fund_name'],
                        'q1_shares': cr['q1_shares'],
                        'q4_shares': cr['q4_shares'],
                        'change_shares': cr['change_shares'],
                        'change_pct': cr['change_pct'],
                        'source': '13F',
                    })

            effective_count = len(child_list)

            sa_note = get_subadviser_note(pname) if src != 'N-PORT' else None
            if effective_count < 2:
                # Flat row
                results.append({
                    'institution': pname, 'fund_name': pname,
                    'q1_shares': p_q1, 'q4_shares': p_q4,
                    'change_shares': p_chg, 'change_pct': p_pct,
                    'type': row['type'], 'is_parent': False,
                    'child_count': 1, 'section': 'holders', 'level': 0,
                    'source': src, 'subadviser_note': sa_note,
                })
            else:
                # Parent summary + children
                results.append({
                    'institution': pname, 'fund_name': '(parent total)',
                    'q1_shares': p_q1, 'q4_shares': p_q4,
                    'change_shares': p_chg, 'change_pct': p_pct,
                    'type': None, 'is_parent': True,
                    'child_count': effective_count, 'section': 'holders', 'level': 0,
                    'source': src, 'subadviser_note': sa_note,
                })
                for c in child_list:
                    results.append({
                        'institution': pname,
                        'fund_name': c.get('fund_name'),
                        'q1_shares': c.get('q1_shares'),
                        'q4_shares': c.get('q4_shares'),
                        'change_shares': c.get('change_shares'),
                        'change_pct': c.get('change_pct'),
                        'type': row['type'] if src == '13F' else None,
                        'is_parent': False, 'child_count': 0,
                        'section': 'holders', 'level': 1,
                        'source': c.get('source', src),
                    })

        # Entries (new in Q4, >100K shares)
        entries = q2[q2['is_entry'] & (q2['q4_shares'] >= 100000)].sort_values(
            'q4_shares', ascending=False
        )
        for _, e in entries.head(15).iterrows():
            results.append({
                'institution': e['parent_name'],
                'fund_name': e['fund_name'],
                'q1_shares': None,
                'q4_shares': e['q4_shares'],
                'change_shares': e['q4_shares'],
                'change_pct': None,
                'type': e['type'],
                'is_parent': False,
                'child_count': 0,
                'section': 'entries',
                'level': 0,
            })

        # Exits (in Q1, gone in Q4, >100K shares)
        exits = q2[q2['is_exit'] & (q2['q1_shares'] >= 100000)].sort_values(
            'q1_shares', ascending=False
        )
        for _, e in exits.head(15).iterrows():
            results.append({
                'institution': e['parent_name'],
                'fund_name': e['fund_name'],
                'q1_shares': e['q1_shares'],
                'q4_shares': None,
                'change_shares': -e['q1_shares'] if pd.notna(e['q1_shares']) else None,
                'change_pct': -100.0,
                'type': e['type'],
                'is_parent': False,
                'child_count': 0,
                'section': 'exits',
                'level': 0,
            })
        return results
    finally:
        pass  # connection managed by thread-local cache


def query3(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Active holder market cap analysis."""
    rn = _rollup_name_sql('h', rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        mktcap_row = con.execute(
            "SELECT market_cap FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        target_mktcap = mktcap_row[0] if mktcap_row else 0

        df = con.execute(f"""
            WITH cik_agg AS (
                SELECT
                    h.cik,
                    MAX(h.manager_name) as manager_name,
                    MAX(COALESCE({rn}, h.inst_parent_name, h.manager_name)) as parent_name,
                    MAX(h.manager_type) as manager_type,
                    SUM(h.market_value_live) as position_value,
                    SUM(h.shares) as shares,
                    MAX(h.pct_of_portfolio) as pct_of_portfolio,
                    SUM(h.pct_of_so) as pct_of_so
                FROM holdings_v2 h
                WHERE h.quarter = '{quarter}'
                  AND (h.ticker = ? OR h.cusip = ?)
                  AND h.entity_type IN ('active', 'hedge_fund', 'activist', 'quantitative')
                  AND h.is_latest = TRUE
                GROUP BY h.cik
                ORDER BY position_value DESC NULLS LAST
                LIMIT 15
            ),
            with_percentile AS (
                SELECT
                    ca.*,
                    (
                        SELECT COUNT(*)
                        FROM holdings_v2 h2
                        INNER JOIN market_data m2 ON h2.ticker = m2.ticker
                        WHERE h2.cik = ca.cik AND h2.quarter = '{quarter}'
                          AND h2.security_type_inferred IN ('equity', 'etf')
                          AND m2.market_cap IS NOT NULL AND m2.market_cap > 0
                          AND m2.market_cap <= {target_mktcap}
                          AND h2.is_latest = TRUE
                    ) as holdings_below,
                    (
                        SELECT COUNT(*)
                        FROM holdings_v2 h2
                        INNER JOIN market_data m2 ON h2.ticker = m2.ticker
                        WHERE h2.cik = ca.cik AND h2.quarter = '{quarter}'
                          AND h2.security_type_inferred IN ('equity', 'etf')
                          AND m2.market_cap IS NOT NULL AND m2.market_cap > 0
                          AND h2.is_latest = TRUE
                    ) as total_with_mktcap
                FROM cik_agg ca
            )
            SELECT
                manager_name,
                parent_name,
                position_value,
                pct_of_portfolio,
                pct_of_so,
                CASE WHEN total_with_mktcap > 0
                     THEN ROUND(holdings_below * 100.0 / total_with_mktcap, 1)
                     ELSE NULL END as mktcap_percentile,
                manager_type,
                '13F estimate' as source
            FROM with_percentile
            ORDER BY position_value DESC NULLS LAST
        """, [ticker, cusip]).fetchdf()

        records = df_to_records(df)

        # Check if investor_flows table exists
        has_flows = has_table('investor_flows')

        # Batch N-PORT fund series for all parents (single query)
        parent_names = [r.get('parent_name') or r.get('manager_name') for r in records]
        nport_by_parent = {}
        if parent_names and has_table('fund_holdings_v2') and has_table('fund_universe'):
            try:
                patterns = []
                for p in parent_names:
                    mp = match_nport_family(p)
                    if mp:
                        for pat in mp:
                            patterns.append((p, '%' + pat + '%'))

                if patterns:
                    # Build a batch query for all parents' fund children
                    for parent_name, like_pat in patterns:
                        kids = con.execute(f"""
                            SELECT fh.fund_name, SUM(fh.shares_or_principal) as shares,
                                   SUM(fh.market_value_usd) as value, AVG(fh.pct_of_nav) as pct_of_nav
                            FROM fund_holdings_v2 fh
                            JOIN fund_universe fu ON fh.series_id = fu.series_id
                            WHERE fu.family_name ILIKE ? AND fh.ticker = ? AND fh.quarter = '{quarter}' AND fh.is_latest = TRUE
                            GROUP BY fh.fund_name
                            ORDER BY value DESC NULLS LAST
                            LIMIT 8
                        """, [like_pat, ticker]).fetchall()
                        if kids:
                            if parent_name not in nport_by_parent:
                                nport_by_parent[parent_name] = []
                            seen = {c['fund_name'] for c in nport_by_parent[parent_name]}
                            for k in kids:
                                if k[0] not in seen:
                                    nport_by_parent[parent_name].append({
                                        'fund_name': k[0], 'shares': k[1],
                                        'value': k[2], 'pct_of_nav': k[3],
                                    })
                                    seen.add(k[0])
            except Exception as e:
                logger.error("[query3 nport batch] %s", e, exc_info=True)

        # N-PORT coverage % per parent (from summary_by_parent)
        # INF34: filter on rollup_type (one row per rollup since migration 004).
        coverage_map = {}
        if parent_names:
            try:
                ph_cov = ','.join(['?'] * len(parent_names))
                cov_df = con.execute(f"""
                    SELECT inst_parent_name, nport_coverage_pct
                    FROM summary_by_parent
                    WHERE quarter = '{quarter}' AND inst_parent_name IN ({ph_cov})
                      AND rollup_type = ?
                """, parent_names + [rollup_type]).fetchdf()
                coverage_map = {r['inst_parent_name']: r['nport_coverage_pct']
                                for _, r in cov_df.iterrows()
                                if r['nport_coverage_pct'] is not None}
            except Exception:
                logger.debug("optional enrichment failed: coverage_map", exc_info=True)

        results = []
        for row in records:
            parent = row.get('parent_name') or row.get('manager_name')
            row['nport_cov'] = coverage_map.get(parent)

            # Enhancement 1 — Position history (Since + Held)
            history = con.execute(f"""
                SELECT quarter, SUM(shares) as shares
                FROM holdings_v2
                WHERE COALESCE({rn}, inst_parent_name, manager_name) = ?
                  AND ticker = ? AND shares > 0
                  AND is_latest = TRUE
                GROUP BY quarter ORDER BY quarter
            """, [parent, ticker]).fetchall()
            quarters_held = [r[0] for r in history if r[1] and r[1] > 0]
            since_raw = quarters_held[0] if quarters_held else None
            held_count = len(quarters_held)
            # Format: '{FQ}' → 'Q1 2025'
            since = (since_raw[4:] + ' ' + since_raw[:4]) if since_raw else None
            row['since'] = since
            row['held_count'] = held_count
            row['held_label'] = '{}/{}'.format(held_count, 4)

            # Enhancement 2 — Direction from investor_flows
            # INF34: filter on rollup_type (one row per rollup since migration 004).
            if has_flows:
                flow = con.execute(f"""
                    SELECT net_shares, pct_change, price_adj_flow, momentum_signal,
                           is_new_entry, is_exit
                    FROM investor_flows
                    WHERE ticker = ? AND inst_parent_name = ?
                      AND quarter_from = '{FQ}' AND quarter_to = '{quarter}'
                      AND rollup_type = ?
                """, [ticker, parent, rollup_type]).fetchone()
                if flow:
                    pct_chg = float(flow[1]) if flow[1] is not None else None
                    if flow[4]:  # is_new_entry
                        direction = 'NEW'
                    elif flow[5]:  # is_exit
                        direction = 'EXIT'
                    elif pct_chg is None:
                        direction = None
                    elif pct_chg > 0.05:
                        direction = 'ADDING'
                    elif pct_chg < -0.05:
                        direction = 'TRIMMING'
                    else:
                        direction = 'STABLE'
                    row['direction'] = direction
                    row['pct_change'] = pct_chg
                    row['price_adj_flow'] = float(flow[2]) if flow[2] is not None else None
                else:
                    row['direction'] = None
                    row['pct_change'] = None
                    row['price_adj_flow'] = None
            else:
                row['direction'] = None
                row['pct_change'] = None
                row['price_adj_flow'] = None

            # N-PORT fund-level children + 13F entity fallback
            nport_children = nport_by_parent.get(parent, [])

            # 13F entities that don't file N-PORT — show as fund-equivalent
            entity_children = []
            if has_table('holdings_v2'):
                try:
                    entities = con.execute(f"""
                        SELECT fund_name, SUM(shares) as shares, SUM(market_value_live) as value
                        FROM holdings_v2
                        WHERE COALESCE({rn}, inst_parent_name, manager_name) = ?
                          AND ticker = ? AND quarter = '{quarter}'
                          AND fund_name NOT IN (
                              SELECT DISTINCT manager_name FROM holdings_v2
                              WHERE COALESCE({rn}, inst_parent_name, manager_name) = ?
                                AND ticker = ? AND quarter = '{quarter}'
                                AND is_latest = TRUE
                              LIMIT 1
                          )
                          AND is_latest = TRUE
                        GROUP BY fund_name
                        HAVING SUM(market_value_live) > 0
                        ORDER BY value DESC LIMIT 5
                    """, [parent, ticker, parent, ticker]).fetchall()
                    for e in entities:
                        # Check if this entity name is already covered by N-PORT
                        if not any(e[0].lower() in c['fund_name'].lower() for c in nport_children):
                            note = _13f_entity_footnote(e[0])
                            if note:  # only include entities we can explain
                                entity_children.append({
                                    'fund_name': e[0], 'shares': e[1],
                                    'value': e[2], 'note': note,
                                })
                except Exception:
                    logger.debug("optional enrichment failed: entity_children", exc_info=True)

            all_children = nport_children + entity_children
            if all_children:
                row['source'] = 'N-PORT' if nport_children else '13F'
                row['subadviser_note'] = None
                row['is_parent'] = True
                row['child_count'] = len(all_children)
            else:
                row['source'] = '13F estimate'
                row['subadviser_note'] = get_subadviser_note(parent)
                row['is_parent'] = False
                row['child_count'] = 0

            row['level'] = 0
            row['institution'] = parent
            results.append(row)

            for c in nport_children:
                results.append({
                    'manager_name': c['fund_name'],
                    'institution': c['fund_name'],
                    'position_value': c['value'],
                    'shares': c['shares'],
                    'pct_of_portfolio': c['pct_of_nav'],
                    'pct_of_so': None,
                    'mktcap_percentile': None,
                    'manager_type': row.get('manager_type'),
                    'source': 'N-PORT',
                    'direction': None, 'since': None, 'held_label': None,
                    'is_parent': False, 'child_count': 0, 'level': 1,
                    'subadviser_note': None,
                })
            for c in entity_children:
                results.append({
                    'manager_name': c['fund_name'],
                    'institution': c['fund_name'],
                    'position_value': c['value'],
                    'shares': c['shares'],
                    'pct_of_portfolio': None,
                    'pct_of_so': None,
                    'mktcap_percentile': None,
                    'manager_type': row.get('manager_type'),
                    'source': '13F entity',
                    'direction': None, 'since': None, 'held_label': None,
                    'is_parent': False, 'child_count': 0, 'level': 1,
                    'subadviser_note': c.get('note'),
                })

        # Item 14: Add short interest summary for this ticker
        if has_table('short_interest') and results:
            si = con.execute("""
                SELECT short_volume, total_volume, short_pct
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date DESC LIMIT 1
            """, [ticker]).fetchone()
            if si:
                for row in results:
                    if row.get('level', 0) == 0:
                        row['short_pct'] = si[2]

        return results
    finally:
        pass  # connection managed by thread-local cache



def query4(ticker, quarter=LQ):
    """Passive vs active ownership split."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                -- COALESCE(entity_type, manager_type): entity_type is the canonical
                -- post-migration source (parent-level-display-canonical-reads);
                -- manager_type is the legacy fallback. Disagreement convention:
                -- when both columns are non-NULL but disagree, entity_type wins.
                CASE
                    WHEN COALESCE(entity_type, manager_type) = 'passive' THEN 'Passive (Index)'
                    WHEN COALESCE(entity_type, manager_type) = 'activist' THEN 'Activist'
                    WHEN COALESCE(entity_type, manager_type) IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
                    ELSE 'Other/Unknown'
                END as category,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares,
                SUM(market_value_live) as total_value,
                SUM(pct_of_so) as total_pct_so
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND ticker = ? AND is_latest = TRUE
            GROUP BY category
            ORDER BY total_value DESC NULLS LAST
        """, [ticker]).fetchdf()
        grand_total = df['total_value'].sum()
        df['pct_of_inst'] = df['total_value'] / grand_total * 100 if grand_total > 0 else 0
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query5(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Quarterly share change heatmap."""
    rn = _rollup_name_sql('', rollup_type)
    con = get_db()
    try:
        df = con.execute(f"""
            WITH pivoted AS (
                SELECT
                    COALESCE({rn}, inst_parent_name, manager_name) as holder,
                    manager_type,
                    SUM(CASE WHEN quarter='{FQ}' THEN shares END) as q1_shares,
                    SUM(CASE WHEN quarter='{QUARTERS[1]}' THEN shares END) as q2_shares,
                    SUM(CASE WHEN quarter='{PQ}' THEN shares END) as q3_shares,
                    SUM(CASE WHEN quarter='{quarter}' THEN shares END) as q4_shares
                FROM holdings_v2
                WHERE ticker = ? AND is_latest = TRUE
                GROUP BY holder, manager_type
            )
            SELECT *,
                q2_shares - q1_shares as q1_to_q2,
                q3_shares - q2_shares as q2_to_q3,
                q4_shares - q3_shares as q3_to_q4,
                q4_shares - q1_shares as full_year_change
            FROM pivoted
            WHERE q4_shares IS NOT NULL
            ORDER BY q4_shares DESC
            LIMIT 25
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query6(ticker, quarter=LQ):  # pylint: disable=W0613  # dispatch protocol: query fn signature; quarter unused here
    """Activist & beneficial ownership tracker — combines 13D/G and 13F data."""
    con = get_db()
    try:
        has_bo = has_table('beneficial_ownership_current')

        sections = {}

        # Section 1: 13D filers (activist intent, ≥5% threshold)
        if has_bo:
            df_13d = con.execute("""
                SELECT filer_name, pct_owned, shares_owned,
                    latest_filing_date AS filing_date,
                    latest_filing_type AS filing_type,
                    days_since_filing, is_current, crossed_5pct,
                    prior_intent, amendment_count
                FROM beneficial_ownership_current
                WHERE subject_ticker = ? AND intent = 'activist'
                ORDER BY latest_filing_date DESC
            """, [ticker]).fetchdf()
            sections['activist_13d'] = resolve_filer_names_in_records(df_to_records(df_13d))

        # Section 2: 13G filers (passive ≥5%)
        if has_bo:
            df_13g = con.execute("""
                SELECT filer_name, pct_owned, shares_owned,
                    latest_filing_date AS filing_date,
                    latest_filing_type AS filing_type,
                    days_since_filing, is_current, crossed_5pct,
                    prior_intent, amendment_count
                FROM beneficial_ownership_current
                WHERE subject_ticker = ? AND intent = 'passive'
                ORDER BY pct_owned DESC NULLS LAST
            """, [ticker]).fetchdf()
            sections['passive_5pct'] = resolve_filer_names_in_records(df_to_records(df_13g))

        # Section 3: Historical timeline
        if has_bo:
            df_hist = con.execute("""
                SELECT filer_name, filing_type, filing_date,
                    pct_owned, shares_owned, intent, purpose_text
                FROM beneficial_ownership_v2
                WHERE subject_ticker = ? AND is_latest = TRUE
                ORDER BY filing_date DESC
            """, [ticker]).fetchdf()
            sections['history'] = resolve_filer_names_in_records(df_to_records(df_hist))

        # Section 4: Legacy 13F activist holdings (from holdings table)
        df_legacy = con.execute("""
            SELECT
                manager_name AS filer_name,
                quarter,
                shares AS shares_owned,
                market_value_usd,
                market_value_live,
                pct_of_portfolio,
                pct_of_so
            FROM holdings_v2
            WHERE ticker = ? AND is_activist = true AND is_latest = TRUE
            ORDER BY manager_name, quarter
        """, [ticker]).fetchdf()
        sections['activist_13f'] = df_to_records(df_legacy)

        # Item 17: Short interest context for activist analysis
        if has_table('short_interest'):
            si = con.execute("""
                SELECT short_volume, total_volume, short_pct, report_date
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date DESC LIMIT 1
            """, [ticker]).fetchone()
            if si:
                sections['short_interest'] = {
                    'short_volume': si[0], 'total_volume': si[1],
                    'short_pct': si[2], 'date': str(si[3]),
                }

        return sections
    finally:
        pass  # connection managed by thread-local cache



def query7(ticker, cik=None, fund_name=None, quarter=LQ):
    """Single fund portfolio — aggregated by ticker, with stats header."""
    con = get_db()
    try:
        if not cik:
            # Default to top non-passive holder of the ticker
            row = con.execute(f"""
                SELECT cik, fund_name FROM holdings_v2
                WHERE ticker = ? AND quarter = '{quarter}'
                  AND entity_type NOT IN ('passive')
                  AND is_latest = TRUE
                ORDER BY market_value_live DESC NULLS LAST
                LIMIT 1
            """, [ticker]).fetchone()
            if not row:
                return {'stats': {}, 'positions': []}
            cik = row[0]
            fund_name = fund_name or row[1]

        # Build the WHERE filter — cik always, fund_name when provided
        where = f"h.cik = ? AND h.quarter = '{quarter}'"
        params = [cik]
        if fund_name:
            where += " AND h.fund_name = ?"
            params.append(fund_name)

        # Fund metadata
        meta_where = f"cik = ? AND quarter = '{quarter}'"
        meta_params = [cik]
        if fund_name:
            meta_where += " AND fund_name = ?"
            meta_params.append(fund_name)
        mgr_row = con.execute(f"""
            SELECT fund_name, MAX(manager_type) as manager_type
            FROM holdings_v2 WHERE {meta_where} AND is_latest = TRUE
            GROUP BY fund_name LIMIT 1
        """, meta_params).fetchone()
        display_name = mgr_row[0] if mgr_row else cik
        mgr_type = mgr_row[1] if mgr_row else 'unknown'

        # Aggregated portfolio by ticker
        df = con.execute(f"""
            SELECT
                h.ticker,
                MAX(h.issuer_name) as issuer_name,
                MAX(s.sector) as sector,
                SUM(h.shares) as shares,
                SUM(h.market_value_live) as market_value_live,
                MAX(h.pct_of_portfolio) as pct_of_portfolio,
                SUM(h.pct_of_so) as pct_of_so,
                MAX(m.market_cap) as market_cap
            FROM holdings_v2 h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            LEFT JOIN (
                SELECT cusip, MAX(sector) as sector
                FROM securities WHERE sector IS NOT NULL AND sector != ''
                GROUP BY cusip
            ) s ON h.cusip = s.cusip
            WHERE {where} AND h.is_latest = TRUE
            GROUP BY h.ticker
            ORDER BY market_value_live DESC NULLS LAST
        """, params).fetchdf()

        records = df_to_records(df)

        # Add rank
        for i, r in enumerate(records, 1):
            r['rank'] = i

        # Portfolio stats
        total_value = df['market_value_live'].sum()
        num_positions = len(df)
        top10_value = df.head(10)['market_value_live'].sum()
        top10_pct = (top10_value / total_value * 100) if total_value > 0 else 0

        stats = {
            'manager_name': display_name,
            'cik': cik,
            'manager_type': mgr_type,
            'total_value': total_value,
            'num_positions': num_positions,
            'top10_concentration_pct': round(top10_pct, 2),
        }

        return clean_for_json({'stats': stats, 'positions': records})
    finally:
        pass  # connection managed by thread-local cache



def query8(ticker, quarter=LQ):
    """Cross-holder overlap — stocks most commonly held by same institutions."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH target_holders AS (
                SELECT DISTINCT cik
                FROM holdings_v2
                WHERE ticker = ? AND quarter = '{quarter}' AND is_latest = TRUE
            )
            SELECT
                h.ticker,
                h.issuer_name,
                COUNT(DISTINCT h.cik) as shared_holders,
                SUM(h.market_value_live) as total_value,
                (SELECT COUNT(*) FROM target_holders) as target_holders_count
            FROM holdings_v2 h
            INNER JOIN target_holders th ON h.cik = th.cik
            WHERE h.quarter = '{quarter}'
              AND h.ticker != ?
              AND h.ticker IS NOT NULL
              AND h.is_latest = TRUE
            GROUP BY h.ticker, h.issuer_name
            ORDER BY shared_holders DESC
            LIMIT 20
        """, [ticker, ticker]).fetchdf()
        if len(df) > 0:
            df['overlap_pct'] = df['shared_holders'] / df['target_holders_count'] * 100
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query9(ticker, quarter=LQ):
    """Sector rotation analysis — sector allocation of active holders."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH target_ciks AS (
                SELECT DISTINCT cik
                FROM holdings_v2
                WHERE ticker = ? AND quarter = '{quarter}'
                AND entity_type IN ('active', 'hedge_fund')
                AND is_latest = TRUE
            )
            SELECT
                s.sector,
                COUNT(DISTINCT h.ticker) as num_stocks,
                SUM(h.market_value_live) as sector_value,
                SUM(h.market_value_live) * 100.0 / SUM(SUM(h.market_value_live)) OVER () as pct_of_total
            FROM holdings_v2 h
            INNER JOIN target_ciks tc ON h.cik = tc.cik
            INNER JOIN securities s ON h.cusip = s.cusip
            WHERE h.quarter = '{quarter}' AND s.sector IS NOT NULL AND s.sector != '' AND h.is_latest = TRUE
            GROUP BY s.sector
            ORDER BY sector_value DESC NULLS LAST
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query10(ticker, quarter=LQ):
    """Position Changes — new entries AND exits combined."""
    con = get_db()
    try:
        entries = con.execute(f"""
            SELECT
                q4.manager_name, q4.manager_type,
                q4.shares, q4.market_value_live,
                q4.pct_of_portfolio, q4.pct_of_so
            FROM holdings_v2 q4
            LEFT JOIN holdings_v2 q3 ON q4.cik = q3.cik AND q3.ticker = ? AND q3.quarter = '{PQ}' AND q3.is_latest = TRUE
            WHERE q4.ticker = ? AND q4.quarter = '{quarter}' AND q3.cik IS NULL AND q4.is_latest = TRUE
            ORDER BY q4.market_value_live DESC NULLS LAST
            LIMIT 25
        """, [ticker, ticker]).fetchdf()

        exits = con.execute(f"""
            SELECT
                q3.manager_name, q3.manager_type,
                q3.shares as q3_shares,
                q3.market_value_usd as q3_value,
                q3.pct_of_portfolio as q3_pct
            FROM holdings_v2 q3
            LEFT JOIN holdings_v2 q4 ON q3.cik = q4.cik AND q4.ticker = ? AND q4.quarter = '{quarter}' AND q4.is_latest = TRUE
            WHERE q3.ticker = ? AND q3.quarter = '{PQ}' AND q4.cik IS NULL AND q3.is_latest = TRUE
            ORDER BY q3.market_value_usd DESC
            LIMIT 25
        """, [ticker, ticker]).fetchdf()

        return clean_for_json({
            'new_entries': df_to_records(entries),
            'exits': df_to_records(exits),
        })
    finally:
        pass


def query11(ticker, quarter=LQ):
    """Redirects to query10 (consolidated Position Changes)."""
    return query10(ticker, quarter=quarter)



def query12(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Concentration analysis — top holders cumulative % of float."""
    rn = _rollup_name_sql('', rollup_type)
    con = get_db()
    try:
        df = con.execute(f"""
            WITH ranked AS (
                SELECT
                    COALESCE({rn}, inst_parent_name, manager_name) as holder,
                    SUM(pct_of_so) as total_pct_so,
                    SUM(shares) as total_shares,
                    ROW_NUMBER() OVER (ORDER BY SUM(pct_of_so) DESC) as rn
                FROM holdings_v2
                WHERE ticker = ? AND quarter = '{quarter}' AND pct_of_so IS NOT NULL AND is_latest = TRUE
                GROUP BY holder
            )
            SELECT
                rn as rank,
                holder,
                total_pct_so,
                total_shares,
                SUM(total_pct_so) OVER (ORDER BY rn) as cumulative_pct
            FROM ranked
            ORDER BY rn
            LIMIT 20
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache


def query14(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Manager AUM vs position size — consolidated with conviction data."""
    rn = _rollup_name_sql('h', rollup_type)
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                COALESCE({rn}, h.inst_parent_name, h.manager_name) as manager_name,
                h.manager_type,
                h.is_activist,
                m.aum_total / 1e9 as manager_aum_bn,
                SUM(h.market_value_live) / 1e6 as position_mm,
                MAX(h.pct_of_portfolio) as pct_of_portfolio,
                SUM(h.pct_of_so) as pct_of_so,
                SUM(h.shares) as shares
            FROM holdings_v2 h
            LEFT JOIN managers m ON h.cik = m.cik
            WHERE h.ticker = ? AND h.quarter = '{quarter}' AND h.is_latest = TRUE
            GROUP BY COALESCE({rn}, h.inst_parent_name, h.manager_name), h.manager_type, h.is_activist, m.aum_total
            HAVING SUM(h.market_value_live) > 0
            ORDER BY SUM(h.market_value_live) DESC NULLS LAST
            LIMIT 25
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass



def query15(ticker=None, quarter=LQ):  # pylint: disable=W0613  # dispatch protocol: query fn signature; ticker unused (global stats)
    """Database statistics."""
    con = get_db()
    try:
        stats = {}
        stats['total_holdings'] = con.execute('SELECT COUNT(*) FROM holdings_v2').fetchone()[0]
        stats['unique_filers'] = con.execute('SELECT COUNT(DISTINCT cik) FROM holdings_v2').fetchone()[0]
        stats['unique_securities'] = con.execute('SELECT COUNT(DISTINCT cusip) FROM holdings_v2').fetchone()[0]
        stats['quarters_loaded'] = con.execute('SELECT COUNT(DISTINCT quarter) FROM holdings_v2').fetchone()[0]
        stats['manager_records'] = con.execute('SELECT COUNT(*) FROM managers').fetchone()[0]
        stats['securities_mapped'] = con.execute('SELECT COUNT(*) FROM securities').fetchone()[0]
        stats['market_data_tickers'] = con.execute('SELECT COUNT(*) FROM market_data').fetchone()[0]
        stats['adv_records'] = con.execute('SELECT COUNT(*) FROM adv_managers').fetchone()[0]

        # Quarter breakdown
        qstats = con.execute("""
            SELECT quarter, COUNT(*) as rows, COUNT(DISTINCT cik) as filers,
                   COUNT(DISTINCT cusip) as securities,
                   SUM(market_value_usd) / 1e9 as total_value_bn
            FROM holdings_v2 GROUP BY quarter ORDER BY quarter
        """).fetchdf()
        stats['quarters'] = df_to_records(qstats)

        # Coverage rates
        coverage = con.execute(f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN ticker IS NOT NULL THEN 1 END) as with_ticker,
                COUNT(CASE WHEN manager_type IS NOT NULL THEN 1 END) as with_manager_type,
                COUNT(CASE WHEN market_value_live IS NOT NULL THEN 1 END) as with_live_value,
                COUNT(CASE WHEN pct_of_so IS NOT NULL THEN 1 END) as with_so_pct
            FROM holdings_v2 WHERE quarter = '{quarter}' AND is_latest = TRUE
        """).fetchone()
        total = coverage[0] or 1
        stats['coverage'] = {
            'total': total,
            'ticker_pct': round(coverage[1] / total * 100, 1),
            'manager_type_pct': round(coverage[2] / total * 100, 1),
            'live_value_pct': round(coverage[3] / total * 100, 1),
            'so_pct_pct': round(coverage[4] / total * 100, 1),
        }
        return clean_for_json([stats])
    finally:
        pass  # connection managed by thread-local cache


def query16(ticker, quarter=LQ):
    """Fund-level register — top 25 individual funds by position value."""
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        # Period-accurate pct_of_so denominator via tier cascade
        # (SOH at quarter_end → md.shares_outstanding → md.float_shares).
        # N-PORT rows aggregate across month-ends within the quarter;
        # quarter-end anchor is the representative reference date.
        denom, denom_source = _resolve_pct_of_so_denom(
            con, ticker, _quarter_to_date(quarter))

        df = con.execute(f"""
            SELECT
                fh.fund_name,
                fh.family_name,
                fh.series_id,
                SUM(fh.market_value_usd) as value,
                SUM(fh.shares_or_principal) as shares,
                AVG(fh.pct_of_nav) as pct_of_nav,
                MAX(fu.total_net_assets) / 1e6 as aum_mm,
                MAX(fu.fund_strategy) as fund_strategy
            FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE fh.ticker = ? AND fh.quarter = '{quarter}' AND fh.is_latest = TRUE
            GROUP BY fh.fund_name, fh.family_name, fh.series_id
            ORDER BY value DESC NULLS LAST
            LIMIT 25
        """, [ticker]).fetchdf()

        if df.empty:
            return {'rows': [], 'all_totals': None, 'type_totals': {}}

        results = []
        for rank, (_, r) in enumerate(df.iterrows(), 1):
            fund_name = r['fund_name'] or ''
            shares = float(r['shares'] or 0)
            value = float(r['value'] or 0)
            aum_val = r['aum_mm']
            aum = int(aum_val) if aum_val and aum_val > 0 else None
            pct_of_nav = round(float(r['pct_of_nav']), 2) if r['pct_of_nav'] else None
            pct_so = round(shares * 100.0 / denom, 2) if denom and shares else None
            fund_type = _fund_type_label(r.get('fund_strategy'))

            results.append({
                'rank': rank,
                'institution': fund_name,
                'family': r['family_name'] or '',
                'value_live': value,
                'shares': shares,
                'pct_so': pct_so,
                'pct_of_so_source': denom_source if pct_so is not None else None,
                'aum': aum,
                'pct_aum': pct_of_nav,
                'type': fund_type,
                'level': 0,
            })

        # All-funds totals
        all_df = con.execute(f"""
            SELECT
                fh.fund_name,
                SUM(fh.market_value_usd) as total_value,
                SUM(fh.shares_or_principal) as total_shares,
                AVG(fh.pct_of_nav) as pct_of_nav,
                MAX(fu.fund_strategy) as fund_strategy
            FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE fh.ticker = ? AND fh.quarter = '{quarter}' AND fh.is_latest = TRUE
            GROUP BY fh.fund_name, fh.series_id
        """, [ticker]).fetchdf()

        all_totals = {
            'value_live': float(all_df['total_value'].sum()) if len(all_df) else 0,
            'shares': float(all_df['total_shares'].sum()) if len(all_df) else 0,
            'pct_so': round(float(all_df['total_shares'].sum()) * 100.0 / denom, 2) if denom and len(all_df) else 0,
            'pct_of_so_source': denom_source if denom and len(all_df) else None,
            'count': len(all_df),
        }

        # By-type totals
        type_totals = {}
        for _, trow in all_df.iterrows():
            t = _fund_type_label(trow.get('fund_strategy'))
            if t not in type_totals:
                type_totals[t] = {'value_live': 0, 'shares': 0, 'pct_so': 0,
                                  'pct_of_so_source': None, 'count': 0}
            type_totals[t]['value_live'] += float(trow['total_value'] or 0)
            s = float(trow['total_shares'] or 0)
            type_totals[t]['shares'] += s
            type_totals[t]['count'] += 1
        # Compute pct_so per type
        for t in type_totals:
            if denom and type_totals[t]['shares']:
                type_totals[t]['pct_so'] = round(type_totals[t]['shares'] * 100.0 / denom, 2)
                type_totals[t]['pct_of_so_source'] = denom_source

        return {'rows': results, 'all_totals': all_totals, 'type_totals': type_totals,
                'pct_of_so_source': denom_source}
    finally:
        pass


# ---------------------------------------------------------------------------
# New query functions — Ownership Trend, Cohort Analysis, Flow Analysis
# ---------------------------------------------------------------------------


QUERY_FUNCTIONS = {
    1: query1, 2: query2, 3: query3, 4: query4, 5: query5,
    6: query6, 7: query7, 8: query8, 9: query9, 10: query10,
    11: query11, 12: query12, 14: query14, 15: query15,
}

QUERY_NAMES = {
    1: 'Register', 2: 'Holder Changes', 3: 'Conviction',
    6: 'Activist', 7: 'Fund Portfolio', 8: 'Cross-Ownership',
    10: 'New Positions', 11: 'Exits',
    14: 'AUM vs Position', 15: 'DB Statistics',
}


# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------


def get_summary(ticker):
    """Quick summary stats for the header card. Cached for 5 min."""
    return cached(CACHE_KEY_SUMMARY.format(ticker=ticker), lambda: _get_summary_impl(ticker))

def _get_summary_impl(ticker, quarter=LQ):
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        if not cusip:
            return None

        # Company name — use most common issuer_name from filings (avoids CUSIP cross-contamination)
        name_row = con.execute(
            f"SELECT MODE(issuer_name) FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter}' AND is_latest = TRUE",
            [ticker]
        ).fetchone()
        company_name = name_row[0] if name_row else ticker

        # Latest quarter
        q_row = con.execute("""
            SELECT MAX(quarter) FROM holdings_v2 WHERE ticker = ? AND is_latest = TRUE
        """, [ticker]).fetchone()
        latest_quarter = q_row[0] if q_row else 'N/A'

        # Total institutional holdings
        totals = con.execute(f"""
            SELECT
                SUM(market_value_live) as total_value,
                SUM(pct_of_so) as total_pct_so,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}' AND is_latest = TRUE
        """, [ticker]).fetchone()

        # Active vs passive split
        split = con.execute(f"""
            SELECT
                SUM(CASE WHEN entity_type = 'passive' THEN market_value_live ELSE 0 END) as passive_value,
                SUM(CASE WHEN entity_type IN ('active','hedge_fund','quantitative','activist')
                    THEN market_value_live ELSE 0 END) as active_value
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}' AND is_latest = TRUE
        """, [ticker]).fetchone()

        # Full type breakdown for stacked bar
        type_df = con.execute(f"""
            SELECT COALESCE(manager_type, 'unknown') as mtype,
                   SUM(market_value_live) as val
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}' AND market_value_live IS NOT NULL AND is_latest = TRUE
            GROUP BY mtype
            ORDER BY val DESC
        """, [ticker]).fetchdf()
        type_breakdown = []
        for _, row in type_df.iterrows():
            if row['val'] and row['val'] > 0:
                type_breakdown.append({'type': row['mtype'], 'value': float(row['val'])})

        # Market data
        mkt = con.execute(
            "SELECT price_live, market_cap, float_shares, fetch_date FROM market_data WHERE ticker = ?",
            [ticker]
        ).fetchone()

        # N-PORT coverage
        nport = get_nport_coverage(ticker, quarter, con)
        total_value = totals[0] if totals else 0
        nport_val = nport.get('nport_total_value') or 0
        nport_pct = round(nport_val / total_value * 100, 1) if total_value and total_value > 0 else None

        # Latest N-PORT report date (most recent monthly filing in our data)
        nport_date = None
        try:
            nd = con.execute("""
                SELECT MAX(report_date) FROM fund_holdings_v2 WHERE ticker = ? AND is_latest = TRUE
            """, [ticker]).fetchone()
            if nd and nd[0]:
                nport_date = str(nd[0])[:10]  # YYYY-MM-DD
        except Exception:
            logger.debug("optional enrichment failed: nport_latest_date", exc_info=True)

        result = {
            'company_name': company_name,
            'ticker': ticker,
            'latest_quarter': latest_quarter,
            'total_value': totals[0],
            'total_pct_so': totals[1],
            'num_holders': totals[2],
            'total_shares': totals[3],
            'passive_value': split[0] if split else None,
            'active_value': split[1] if split else None,
            'price': mkt[0] if mkt else None,
            'market_cap': mkt[1] if mkt else None,
            'shares_float': mkt[2] if mkt else None,
            'price_date': mkt[3] if mkt else None,
            'type_breakdown': type_breakdown,
            'nport_coverage': nport_pct,
            'nport_funds': nport.get('nport_fund_count', 0),
            'nport_latest_date': nport_date,
        }
        return clean_for_json(result)
    finally:
        pass  # connection managed by thread-local cache


# ---------------------------------------------------------------------------
# Excel export helper
# ---------------------------------------------------------------------------
