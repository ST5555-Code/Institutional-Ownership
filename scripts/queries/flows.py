"""Flow analysis + cohort queries."""
import logging

from config import (
    QUARTERS,
)
from cache import (
    cached,
    CACHE_KEY_COHORT,
    CACHE_TTL_COHORT,
)
from serializers import (
    clean_for_json,
    df_to_records,
)
from .common import (
    LQ,
    FQ,
    PQ,
    top_parent_canonical_name_sql,
    get_db,
    has_table,
    _quarter_to_date,
    _resolve_pct_of_so_denom,
    ACTIVE_FUND_STRATEGIES,
)

logger = logging.getLogger(__name__)

def _build_cohort(q1_map, q4_map):
    """Core cohort logic shared by parent-level and fund-level analysis.
    Returns (detail, summary_data) given two dicts keyed by entity name.
    """
    q1_set, q4_set = set(q1_map.keys()), set(q4_map.keys())
    retained = q1_set & q4_set
    new_entries_set = q4_set - q1_set
    exits_set = q1_set - q4_set

    increased, decreased, unchanged = [], [], []
    for inv in retained:
        s1 = q1_map[inv].get('shares') or 0
        s4 = q4_map[inv].get('shares') or 0
        (increased if s4 > s1 else decreased if s4 < s1 else unchanged).append(inv)

    total_inst_shares = sum((q4_map[i].get('shares') or 0) for i in q4_set)

    def _stats(investors, src, delta_src=None):
        """src = position source, delta_src = other quarter for computing deltas."""
        c = len(investors)
        s = sum((src[i].get('shares') or 0) for i in investors)
        v = sum((src[i].get('value') or 0) for i in investors)
        pct_so = round(s / total_inst_shares * 100, 2) if total_inst_shares > 0 else 0
        # Net deltas
        if delta_src is not None:
            delta_s = sum(((src[i].get('shares') or 0) - (delta_src.get(i, {}).get('shares') or 0)) for i in investors)
            delta_v = sum(((src[i].get('value') or 0) - (delta_src.get(i, {}).get('value') or 0)) for i in investors)
        else:
            delta_s = s   # new entries: entire position is delta
            delta_v = v
        return {'holders': c, 'shares': s, 'value': v,
                'avg_position': round(v / c, 2) if c > 0 else 0,
                'pct_so_moved': pct_so,
                'delta_shares': delta_s, 'delta_value': delta_v}

    def _top5(investors, src, delta_src=None, sort_key='value', reverse=True):
        """Return top 5 entity rows sorted by sort_key."""
        def _entity_delta(inv):
            s_now = src.get(inv, {}).get('shares') or 0
            v_now = src.get(inv, {}).get('value') or 0
            if delta_src is not None:
                s_prev = delta_src.get(inv, {}).get('shares') or 0
                v_prev = delta_src.get(inv, {}).get('value') or 0
                ds, dv = s_now - s_prev, v_now - v_prev
            else:
                ds, dv = s_now, v_now  # new = entire position; exits handled by caller
            return {'category': inv, 'holders': 1, 'shares': s_now, 'value': v_now,
                    'avg_position': v_now, 'delta_shares': ds, 'delta_value': dv,
                    'pct_so_moved': round(s_now / total_inst_shares * 100, 4) if total_inst_shares > 0 else 0,
                    'level': 2}
        rows = [_entity_delta(i) for i in investors]
        # For exits, flip delta sign
        if delta_src is None and not reverse:
            for r in rows:
                r['delta_shares'] = -r['shares']
                r['delta_value'] = -r['value']
        sk = sort_key if sort_key != 'delta' else 'delta_value'
        rows.sort(key=lambda r: abs(r.get(sk) or 0), reverse=True)
        return rows[:5]

    inc_stats = _stats(increased, q4_map, q1_map)
    dec_stats = _stats(decreased, q4_map, q1_map)
    unc_stats = _stats(unchanged, q4_map, q1_map)
    exit_stats = _stats(list(exits_set), q1_map)
    exit_stats['delta_shares'] = -exit_stats['shares']
    exit_stats['delta_value'] = -exit_stats['value']
    new_stats = _stats(list(new_entries_set), q4_map)

    # Top 5 per category
    inc_top5 = _top5(increased, q4_map, q1_map, sort_key='delta')
    dec_top5 = _top5(decreased, q4_map, q1_map, sort_key='delta')
    unc_top5 = _top5(unchanged, q4_map, None, sort_key='value')
    new_top5 = _top5(list(new_entries_set), q4_map, None, sort_key='value')
    exit_top5 = _top5(list(exits_set), q1_map, None, sort_key='value', reverse=False)
    for r in exit_top5:
        r['delta_shares'] = -r['shares']
        r['delta_value'] = -r['value']

    # Retained parent totals
    ret_holders = inc_stats['holders'] + dec_stats['holders'] + unc_stats['holders']
    ret_shares = inc_stats['shares'] + dec_stats['shares'] + unc_stats['shares']
    ret_value = inc_stats['value'] + dec_stats['value'] + unc_stats['value']
    ret_delta_s = inc_stats['delta_shares'] + dec_stats['delta_shares'] + unc_stats['delta_shares']
    ret_delta_v = inc_stats['delta_value'] + dec_stats['delta_value'] + unc_stats['delta_value']
    ret_pct = round(ret_shares / total_inst_shares * 100, 2) if total_inst_shares > 0 else 0

    detail = [
        {'category': 'Retained', 'holders': ret_holders, 'shares': ret_shares,
         'value': ret_value, 'avg_position': round(ret_value / ret_holders, 2) if ret_holders > 0 else 0,
         'pct_so_moved': ret_pct, 'delta_shares': ret_delta_s, 'delta_value': ret_delta_v,
         'level': 0, 'is_parent': True, 'has_children': False},
        {'category': 'Increased', 'level': 1, 'has_children': True, 'children': inc_top5, **inc_stats},
        {'category': 'Decreased', 'level': 1, 'has_children': True, 'children': dec_top5, **dec_stats},
        {'category': 'Unchanged', 'level': 1, 'has_children': True, 'children': unc_top5, **unc_stats},
        {'category': 'New Entries', 'level': 0, 'has_children': True, 'children': new_top5, **new_stats},
        {'category': 'Exits', 'level': 0, 'has_children': True, 'children': exit_top5, **exit_stats},
    ]

    total_q1 = len(q1_set)
    net_holders = len(new_entries_set) - len(exits_set)
    net_shares = ret_delta_s + new_stats['delta_shares'] + exit_stats['delta_shares']
    net_value = (sum((q4_map[i].get('value') or 0) for i in q4_set)
                 - sum((q1_map[i].get('value') or 0) for i in q1_set))

    # Top 10 holders in latest quarter — which cohort bucket
    top10_inv = sorted(q4_map.keys(), key=lambda x: q4_map[x].get('value') or 0, reverse=True)[:10]
    top10 = {
        'increased': sum(1 for i in top10_inv if i in set(increased)),
        'decreased': sum(1 for i in top10_inv if i in set(decreased)),
        'new': sum(1 for i in top10_inv if i in new_entries_set),
        'unchanged': sum(1 for i in top10_inv if i in set(unchanged)),
    }

    # Economic-weighted retention: investor-level, share-based, capped at 100%
    # weight_i = Q1_shares_i / total_Q1_shares; retention_i = min(Q4_shares / Q1_shares, 1.0)
    # Exits get retention=0 with their Q1 weight. New entries excluded.
    total_q1_shares = sum((q1_map[i].get('shares') or 0) for i in q1_set)
    if total_q1_shares > 0:
        weighted_sum = 0
        for inv in q1_set:
            s1 = q1_map[inv].get('shares') or 0
            if s1 <= 0:
                continue
            weight = s1 / total_q1_shares
            if inv in q4_set:
                s4 = q4_map[inv].get('shares') or 0
                inv_ret = min(s4 / s1, 1.0)  # cap at 100%
            else:
                inv_ret = 0  # exit
            weighted_sum += weight * inv_ret
        econ_retention = round(weighted_sum * 100, 1)
    else:
        econ_retention = 0

    # Totals row (no double-counting): all unique entities in Q4
    total_q4_holders = len(q4_set)
    total_q4_shares = sum((q4_map[i].get('shares') or 0) for i in q4_set)
    total_q4_value = sum((q4_map[i].get('value') or 0) for i in q4_set)
    total_delta_s = net_shares
    total_delta_v = net_value

    detail.append({
        'category': 'Total', 'holders': total_q4_holders, 'shares': total_q4_shares,
        'value': total_q4_value, 'avg_position': round(total_q4_value / total_q4_holders, 2) if total_q4_holders > 0 else 0,
        'pct_so_moved': 100.0, 'delta_shares': total_delta_s, 'delta_value': total_delta_v,
        'level': -1, 'is_total': True, 'has_children': False,
    })

    summary = {
        'retention_rate': round(len(retained) / total_q1 * 100, 2) if total_q1 > 0 else 0,
        'econ_retention': econ_retention,
        'net_holders': net_holders,
        'net_shares': net_shares,
        'net_value': net_value,
        'top10': top10,
    }
    return detail, summary


def cohort_analysis(ticker, from_quarter=None, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ):
    """Cohort retention analysis: compare two quarters. Cached for 60s.

    level: 'parent' (13F institutional) or 'fund' (N-PORT fund series).
    active_only: when level='fund', exclude passive/index funds.
    """
    fq = from_quarter or PQ
    key = CACHE_KEY_COHORT.format(
        ticker=ticker, quarter=quarter, rollup_type=rollup_type,
        level=level, active_only=active_only, from_quarter=fq,
    )
    return cached(
        key,
        lambda: _cohort_analysis_impl(
            ticker, from_quarter=fq, level=level, active_only=active_only,
            rollup_type=rollup_type, quarter=quarter,
        ),
        ttl=CACHE_TTL_COHORT,
    )


def _cohort_analysis_impl(ticker, from_quarter=None, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ):  # pylint: disable=unused-argument
    # CP-5.5: parent-level branch reads canonical top-parent name via
    # top_parent_canonical_name_sql() (rollup-type-independent climb through
    # inst_to_top_parent). rollup_type retained on signature for caller-API
    # stability (cache key + endpoint param surface) but no longer drives
    # name resolution here.
    tp_name = top_parent_canonical_name_sql('h')
    con = get_db()
    try:
        fq = from_quarter or PQ
        lq = quarter

        if level == 'fund':
            # Fund-level from fund_holdings, filter via canonical fund_strategy partition
            join_clause = "LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id"
            active_filter = ""
            active_params = []
            if active_only:
                active_ph = ','.join('?' * len(ACTIVE_FUND_STRATEGIES))
                active_filter = f"AND fu.fund_strategy IN ({active_ph})"
                active_params = list(ACTIVE_FUND_STRATEGIES)
            q1_df = con.execute(f"""
                SELECT fh.fund_name as investor,
                       SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
                FROM fund_holdings_v2 fh {join_clause}
                WHERE fh.ticker = ? AND fh.quarter = '{fq}' {active_filter} AND fh.is_latest = TRUE
                GROUP BY fh.fund_name
            """, [ticker] + active_params).fetchdf()
            q4_df = con.execute(f"""
                SELECT fh.fund_name as investor,
                       SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
                FROM fund_holdings_v2 fh {join_clause}
                WHERE fh.ticker = ? AND fh.quarter = '{lq}' {active_filter} AND fh.is_latest = TRUE
                GROUP BY fh.fund_name
            """, [ticker] + active_params).fetchdf()
        else:
            # Parent-level from holdings (13F)
            q1_df = con.execute(f"""
                SELECT {tp_name} as investor,
                       SUM(h.shares) as shares, SUM(h.market_value_usd) as value
                FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter = '{fq}' AND h.is_latest = TRUE GROUP BY investor
            """, [ticker]).fetchdf()
            q4_df = con.execute(f"""
                SELECT {tp_name} as investor,
                       SUM(h.shares) as shares, SUM(h.market_value_usd) as value
                FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter = '{lq}' AND h.is_latest = TRUE GROUP BY investor
            """, [ticker]).fetchdf()

        q1_map = {r['investor']: r for r in df_to_records(q1_df)}
        q4_map = {r['investor']: r for r in df_to_records(q4_df)}

        detail, summary = _build_cohort(q1_map, q4_map)
        summary['from_quarter'] = fq
        summary['to_quarter'] = lq
        summary['level'] = level
        summary['active_only'] = active_only

        # Economic retention for last 3 QoQ transitions (active investors only)
        # Share-weighted, investor-level, capped at 100% per investor
        econ_retention_trend = []
        for i in range(len(QUARTERS) - 1):
            q_from, q_to = QUARTERS[i], QUARTERS[i + 1]
            try:
                from_df = con.execute(f"""
                    SELECT {tp_name} as investor,
                           SUM(h.shares) as shares
                    FROM holdings_v2 h
                    WHERE h.ticker = ? AND h.quarter = '{q_from}'
                      AND h.entity_type NOT IN ('passive', 'unknown')
                      AND h.is_latest = TRUE
                    GROUP BY investor
                """, [ticker]).fetchdf()
                to_df = con.execute(f"""
                    SELECT {tp_name} as investor,
                           SUM(h.shares) as shares
                    FROM holdings_v2 h
                    WHERE h.ticker = ? AND h.quarter = '{q_to}'
                      AND h.entity_type NOT IN ('passive', 'unknown')
                      AND h.is_latest = TRUE
                    GROUP BY investor
                """, [ticker]).fetchdf()
                from_map = {r['investor']: float(r['shares'] or 0) for _, r in from_df.iterrows()}
                to_map = {r['investor']: float(r['shares'] or 0) for _, r in to_df.iterrows()}
                total_from = sum(from_map.values())
                if total_from > 0:
                    weighted_sum = 0
                    for inv, s_from in from_map.items():
                        if s_from <= 0:
                            continue
                        w = s_from / total_from
                        s_to = to_map.get(inv, 0)
                        weighted_sum += w * min(s_to / s_from, 1.0)
                    er = round(weighted_sum * 100, 1)
                else:
                    er = 0
                econ_retention_trend.append({
                    'from': q_from, 'to': q_to,
                    'econ_retention': er,
                    'active_holders_from': len(from_map),
                    'active_holders_to': len(to_map),
                })
            except Exception:
                logger.debug("optional enrichment failed: econ_retention", exc_info=True)
        summary['econ_retention_trend'] = econ_retention_trend

        return {'summary': summary, 'detail': detail}
    finally:
        pass  # connection managed by thread-local cache



def _compute_flows_live(ticker, quarter_from, quarter_to, con, level='parent', active_only=False, rollup_type='economic_control_v1'):  # pylint: disable=unused-argument
    """Compute buyer/seller/new/exit flows live from holdings or fund_holdings.
    Returns (buyers, sellers, new_entries, exits) lists.
    """
    # CP-5.5: parent-tier name resolution via rollup-type-independent climb.
    tp_name = top_parent_canonical_name_sql('h')
    # Period-accurate pct_of_so denominator per quarter (fund-level uses
    # to_quarter for retained/new, from_quarter for exits). Tier cascade:
    # SOH quarter-end → md.shares_outstanding → md.float_shares.
    from_denom, from_denom_source = _resolve_pct_of_so_denom(
        con, ticker, _quarter_to_date(quarter_from))
    to_denom, to_denom_source = _resolve_pct_of_so_denom(
        con, ticker, _quarter_to_date(quarter_to))

    if level == 'fund':
        # Filter via canonical fund_strategy partition
        join_clause = "LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id"
        af = ""
        active_params = []
        if active_only:
            active_ph = ','.join('?' * len(ACTIVE_FUND_STRATEGIES))
            af = f"AND fu.fund_strategy IN ({active_ph})"
            active_params = list(ACTIVE_FUND_STRATEGIES)
        from_df = con.execute(f"""
            SELECT fh.fund_name as entity, SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
            FROM fund_holdings_v2 fh {join_clause}
            WHERE fh.ticker = ? AND fh.quarter = '{quarter_from}' {af} AND fh.is_latest = TRUE GROUP BY fh.fund_name
        """, [ticker] + active_params).fetchdf()
        to_df = con.execute(f"""
            SELECT fh.fund_name as entity, SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
            FROM fund_holdings_v2 fh {join_clause}
            WHERE fh.ticker = ? AND fh.quarter = '{quarter_to}' {af} AND fh.is_latest = TRUE GROUP BY fh.fund_name
        """, [ticker] + active_params).fetchdf()
    else:
        from_df = con.execute(f"""
            SELECT {tp_name} as entity,
                   MAX(h.manager_type) as manager_type,
                   SUM(h.shares) as shares, SUM(h.market_value_usd) as value,
                   SUM(h.pct_of_so) as pct_of_so
            FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter = '{quarter_from}' AND h.is_latest = TRUE GROUP BY entity
        """, [ticker]).fetchdf()
        to_df = con.execute(f"""
            SELECT {tp_name} as entity,
                   MAX(h.manager_type) as manager_type,
                   SUM(h.shares) as shares, SUM(h.market_value_usd) as value,
                   SUM(h.pct_of_so) as pct_of_so
            FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter = '{quarter_to}' AND h.is_latest = TRUE GROUP BY entity
        """, [ticker]).fetchdf()

    from_map = {r['entity']: r for _, r in from_df.iterrows()}
    to_map = {r['entity']: r for _, r in to_df.iterrows()}
    from_set, to_set = set(from_map), set(to_map)

    def _pct_so(shares, use='to'):
        """Compute % of SO from shares using the tier-cascade denominator.

        use: 'to' (default) uses quarter_to denominator; 'from' uses
        quarter_from denominator. Returns (pct, source_str).
        """
        denom = to_denom if use == 'to' else from_denom
        source = to_denom_source if use == 'to' else from_denom_source
        if denom and shares:
            return round(shares / denom * 100, 3), source
        return None, None

    def _get_pf(entity_row, fallback_shares, use='to'):
        """Safely extract pct_of_so from a pandas row, fall back to computed.

        Returns (pct, source_str). When the pandas row already has a
        pre-computed pct_of_so (from a SUM over holdings_v2), the source
        is inherited from the underlying rows — surface None here rather
        than claim the tier; the per-entity aggregation may mix tiers.
        """
        raw = entity_row.get('pct_of_so') if entity_row is not None else None
        try:
            if raw is not None and not (isinstance(raw, float) and raw != raw):
                return float(raw), None  # pre-aggregated; tier unknown
        except (TypeError, ValueError):
            pass
        return _pct_so(fallback_shares, use=use)

    rows = []
    # Retained: compare shares
    for entity in from_set & to_set:
        fs = float(from_map[entity].get('shares') or 0)
        ts = float(to_map[entity].get('shares') or 0)
        fv = float(from_map[entity].get('value') or 0)
        tv = float(to_map[entity].get('value') or 0)
        net_s = ts - fs
        mt = from_map[entity].get('manager_type') if level == 'parent' else None
        pf, pf_src = (_get_pf(to_map[entity], ts, use='to') if level == 'parent'
                      else _pct_so(ts, use='to'))
        rows.append({
            'inst_parent_name': entity, 'manager_type': mt or '',
            'from_shares': fs, 'to_shares': ts, 'net_shares': net_s,
            'from_value': fv, 'to_value': tv, 'net_value': tv - fv,
            'pct_change': (net_s / fs) if fs > 0 else None,
            'pct_so': pf, 'pct_of_so_source': pf_src,
            'is_new_entry': False, 'is_exit': False,
        })
    # New entries
    for entity in to_set - from_set:
        ts = float(to_map[entity].get('shares') or 0)
        tv = float(to_map[entity].get('value') or 0)
        mt = to_map[entity].get('manager_type') if level == 'parent' else None
        pf, pf_src = (_get_pf(to_map[entity], ts, use='to') if level == 'parent'
                      else _pct_so(ts, use='to'))
        rows.append({
            'inst_parent_name': entity, 'manager_type': mt or '',
            'from_shares': 0, 'to_shares': ts, 'net_shares': ts,
            'from_value': 0, 'to_value': tv, 'net_value': tv,
            'pct_change': None, 'pct_so': pf, 'pct_of_so_source': pf_src,
            'is_new_entry': True, 'is_exit': False,
        })
    # Exits
    for entity in from_set - to_set:
        fs = float(from_map[entity].get('shares') or 0)
        fv = float(from_map[entity].get('value') or 0)
        mt = from_map[entity].get('manager_type') if level == 'parent' else None
        pf, pf_src = (_get_pf(from_map[entity], fs, use='from') if level == 'parent'
                      else _pct_so(fs, use='from'))
        rows.append({
            'inst_parent_name': entity, 'manager_type': mt or '',
            'from_shares': fs, 'to_shares': 0, 'net_shares': -fs,
            'from_value': fv, 'to_value': 0, 'net_value': -fv,
            'pct_change': -1.0, 'pct_so': pf, 'pct_of_so_source': pf_src,
            'is_new_entry': False, 'is_exit': True,
        })

    # Split and sort by net_shares (shares-based primary)
    buyers = sorted([r for r in rows if not r['is_new_entry'] and not r['is_exit'] and r['net_shares'] > 0],
                    key=lambda x: x['net_shares'], reverse=True)[:25]
    sellers = sorted([r for r in rows if not r['is_new_entry'] and not r['is_exit'] and r['net_shares'] < 0],
                     key=lambda x: x['net_shares'])[:25]
    new_entries = sorted([r for r in rows if r['is_new_entry']],
                         key=lambda x: x['to_shares'], reverse=True)[:25]
    exits = sorted([r for r in rows if r['is_exit']],
                   key=lambda x: x['from_shares'], reverse=True)[:25]

    return buyers, sellers, new_entries, exits


def flow_analysis(ticker, period='1Q', peers=None, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ):
    """Flow analysis — default QoQ (1Q = most recent quarter).
    level: 'parent' (13F) or 'fund' (N-PORT).
    """
    # CP-5.5: live qoq_charts computation uses canonical top-parent name.
    # Precomputed investor_flows read in this same function remains on
    # legacy name-key path until CP-5.5b precompute rebuild keys by tp_eid.
    tp_name = top_parent_canonical_name_sql('h')
    period_map = {'4Q': FQ, '2Q': QUARTERS[1] if len(QUARTERS) > 1 else FQ, '1Q': PQ}
    quarter_from = period_map.get(period, PQ)
    quarter_to = quarter

    con = get_db()
    try:
        # Check if pre-computed tables exist
        has_precomputed = has_table('investor_flows') and has_table('ticker_flow_stats')

        if not has_precomputed:
            # Fallback: return empty with message
            return {'error': 'Flow data not yet computed. Run scripts/compute_flows.py first.',
                    'buyers': [], 'sellers': [], 'new_entries': [], 'exits': [],
                    'charts': {'flow_intensity': [], 'churn': []}}

        # Check if this ticker has data
        # INF34: filter on rollup_type (one row per rollup since migration 004).
        cnt = con.execute(
            "SELECT COUNT(*) FROM investor_flows "
            "WHERE ticker = ? AND quarter_from = ? AND rollup_type = ?",
            [ticker, quarter_from, rollup_type]
        ).fetchone()[0]
        if cnt == 0:
            return {'error': 'No flow data for this ticker/period.',
                    'buyers': [], 'sellers': [], 'new_entries': [], 'exits': [],
                    'charts': {'flow_intensity': [], 'churn': []}}

        # Implied prices
        ip = con.execute("""
            SELECT SUM(market_value_usd) / NULLIF(SUM(shares), 0)
            FROM holdings_v2 WHERE ticker = ? AND quarter = ? AND shares > 0 AND is_latest = TRUE
        """, [ticker, quarter_from]).fetchone()
        implied_from = ip[0] if ip and ip[0] else None
        ip2 = con.execute(f"""
            SELECT SUM(market_value_usd) / NULLIF(SUM(shares), 0)
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter}' AND shares > 0 AND is_latest = TRUE
        """, [ticker]).fetchone()
        implied_to = ip2[0] if ip2 and ip2[0] else None

        # Fetch flows — use precomputed for parent level, live for fund level
        if level == 'fund' or not has_precomputed or cnt == 0:
            buyers, sellers, new_entries, exits = _compute_flows_live(
                ticker, quarter_from, quarter_to, con, level=level, active_only=active_only)
        else:
            df = con.execute("""
                SELECT inst_parent_name, manager_type, from_shares, to_shares, net_shares,
                       pct_change, from_value, to_value, from_price,
                       price_adj_flow, raw_flow, price_effect,
                       is_new_entry, is_exit, flow_4q, flow_2q,
                       momentum_ratio, momentum_signal
                FROM investor_flows
                WHERE ticker = ? AND quarter_from = ? AND rollup_type = ?
                ORDER BY net_shares DESC NULLS LAST
            """, [ticker, quarter_from, rollup_type]).fetchdf()
            rows = df_to_records(df)
            # Period-accurate pct_of_so denominator. Use quarter_from for
            # exits (prior-quarter position) and quarter_to for
            # buyers/sellers/new (current-quarter position). Tier cascade:
            # SOH quarter-end → md.shares_outstanding → md.float_shares.
            from_flt, from_src = _resolve_pct_of_so_denom(
                con, ticker, _quarter_to_date(quarter_from))
            to_flt, to_src = _resolve_pct_of_so_denom(
                con, ticker, _quarter_to_date(quarter_to))
            for r in rows:
                r['net_value'] = (r.get('to_value') or 0) - (r.get('from_value') or 0)
                ts = r.get('to_shares') or 0
                fs = r.get('from_shares') or 0
                ns = abs(r.get('net_shares') or 0)
                # pct_so = the relevant change as % of SO:
                #   buyers/sellers: net change / SO@to (how much they added/reduced)
                #   new entries: to_shares / SO@to (entire new position)
                #   exits: from_shares / SO@from (entire prior position)
                if r.get('is_new_entry'):
                    change_shares = ts
                    flt, src = to_flt, to_src
                elif r.get('is_exit'):
                    change_shares = fs
                    flt, src = from_flt, from_src
                else:
                    change_shares = ns
                    flt, src = to_flt, to_src
                if flt and change_shares:
                    r['pct_so'] = round(change_shares / flt * 100, 3)
                    r['pct_of_so_source'] = src
                else:
                    r['pct_so'] = None
                    r['pct_of_so_source'] = None
            buyers = [r for r in rows if not r.get('is_new_entry') and not r.get('is_exit')
                      and (r.get('net_shares') or 0) > 0][:25]
            sellers = sorted([r for r in rows if not r.get('is_new_entry') and not r.get('is_exit')
                              and (r.get('net_shares') or 0) < 0],
                             key=lambda x: x.get('net_shares') or 0)[:25]
            new_entries = sorted([r for r in rows if r.get('is_new_entry')],
                                 key=lambda x: x.get('to_shares') or 0, reverse=True)[:25]
            exits = sorted([r for r in rows if r.get('is_exit')],
                           key=lambda x: x.get('from_shares') or 0, reverse=True)[:25]

        # Charts: flow intensity and churn for ticker + peers
        chart_tickers = [ticker]
        if peers:
            chart_tickers += [t.strip() for t in peers.split(',') if t.strip()]

        chart_data = []
        for t in chart_tickers:
            stat = con.execute("""
                SELECT flow_intensity_total, flow_intensity_active, flow_intensity_passive,
                       churn_nonpassive, churn_active
                FROM ticker_flow_stats
                WHERE ticker = ? AND quarter_from = ?
            """, [t, quarter_from]).fetchone()
            if stat:
                chart_data.append({
                    'ticker': t,
                    'flow_intensity_total': stat[0], 'flow_intensity_active': stat[1],
                    'flow_intensity_passive': stat[2],
                    'churn_nonpassive': stat[3], 'churn_active': stat[4],
                })

        # Multi-period flow trend (all periods for this ticker)
        flow_trend = []
        try:
            trend_df = con.execute("""
                SELECT quarter_from, quarter_to,
                       flow_intensity_total, flow_intensity_active, flow_intensity_passive,
                       churn_nonpassive, churn_active
                FROM ticker_flow_stats WHERE ticker = ?
                ORDER BY quarter_from
            """, [ticker]).fetchdf()
            flow_trend = df_to_records(trend_df)
        except Exception:
            logger.debug("optional enrichment failed: flow_trend", exc_info=True)

        # QoQ chart data: compute flow intensity & churn for each sequential quarter pair
        qoq_charts = []
        mktcap_row = con.execute(
            "SELECT market_cap FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        mktcap = float(mktcap_row[0]) if mktcap_row and mktcap_row[0] else None
        for i in range(len(QUARTERS) - 1):
            qf, qt = QUARTERS[i], QUARTERS[i + 1]
            try:
                agg = con.execute(f"""
                    SELECT
                        COALESCE(agg.manager_type, 'unknown') as mtype,
                        SUM(CASE WHEN agg.quarter = '{qf}' THEN agg.shares ELSE 0 END) as from_s,
                        SUM(CASE WHEN agg.quarter = '{qt}' THEN agg.shares ELSE 0 END) as to_s,
                        SUM(CASE WHEN agg.quarter = '{qf}' THEN agg.market_value_usd ELSE 0 END) as from_v,
                        SUM(CASE WHEN agg.quarter = '{qt}' THEN agg.market_value_usd ELSE 0 END) as to_v
                    FROM (
                        SELECT {tp_name} as inv, h.manager_type, h.quarter,
                               SUM(h.shares) as shares, SUM(h.market_value_usd) as market_value_usd
                        FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter IN ('{qf}', '{qt}') AND h.is_latest = TRUE
                        GROUP BY inv, h.manager_type, h.quarter
                    ) agg
                    GROUP BY mtype
                """, [ticker]).fetchdf()
                total_net = 0
                active_net = 0
                passive_net = 0
                nonpassive_churn_v = 0
                nonpassive_avg_v = 0
                active_churn_v = 0
                active_avg_v = 0
                for _, r in agg.iterrows():
                    mt = r['mtype'] or 'unknown'
                    net_v = float(r['to_v'] or 0) - float(r['from_v'] or 0)
                    avg_v = (float(r['to_v'] or 0) + float(r['from_v'] or 0)) / 2
                    total_net += net_v
                    if mt == 'passive':
                        passive_net += net_v
                    else:
                        active_net += net_v if mt not in ('unknown',) else 0
                        nonpassive_churn_v += abs(net_v)
                        nonpassive_avg_v += avg_v
                        if mt not in ('passive', 'unknown'):
                            active_churn_v += abs(net_v)
                            active_avg_v += avg_v
                fi_total = total_net / mktcap if mktcap and mktcap > 0 else 0
                fi_active = active_net / mktcap if mktcap and mktcap > 0 else 0
                ch_np = nonpassive_churn_v / nonpassive_avg_v if nonpassive_avg_v > 0 else 0
                ch_act = active_churn_v / active_avg_v if active_avg_v > 0 else 0
                qoq_charts.append({
                    'from': qf, 'to': qt,
                    'label': qf.replace('2025', '') + '\u2192' + qt.replace('2025', ''),
                    'flow_intensity_total': round(fi_total, 6),
                    'flow_intensity_active': round(fi_active, 6),
                    'churn_nonpassive': round(ch_np, 6),
                    'churn_active': round(ch_act, 6),
                })
            except Exception:
                logger.debug("optional enrichment failed: flow_intensity", exc_info=True)

        return clean_for_json({
            'period': period,
            'quarter_from': quarter_from,
            'quarter_to': quarter_to,
            'level': level,
            'implied_prices': {quarter_from: implied_from, quarter_to: implied_to},
            'buyers': buyers,
            'sellers': sellers,
            'new_entries': new_entries,
            'exits': exits,
            'charts': {
                'flow_intensity': chart_data,
                'churn': chart_data,
            },
            'qoq_charts': qoq_charts,
            'flow_trend': flow_trend,
        })
    finally:
        pass


# ---------------------------------------------------------------------------
# Short vs Long comparison (Item 9)
# ---------------------------------------------------------------------------


# GICS sector mapping from Yahoo Finance taxonomy
