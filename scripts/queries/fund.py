"""Fund + portfolio_context queries."""
import logging

from .common import (
    LQ,
    _rollup_col,
    get_db,
    get_cusip,
    get_nport_children_batch,
)

logger = logging.getLogger(__name__)

_YF_TO_GICS = {
    'Technology': ('Information Technology', 'TEC'),
    'Financial Services': ('Financials', 'FIN'),  # REITs moved to Real Estate via industry
    'Healthcare': ('Health Care', 'HCR'),
    'Industrials': ('Industrials', 'IND'),
    'Consumer Cyclical': ('Consumer Discretionary', 'CND'),
    'Consumer Defensive': ('Consumer Staples', 'CNS'),
    'Energy': ('Energy', 'ENE'),
    'Basic Materials': ('Materials', 'MAT'),
    'Communication Services': ('Communication Services', 'COM'),
    'Utilities': ('Utilities', 'UTL'),
    'Real Estate': ('Real Estate', 'REA'),
}


def _gics_sector(yf_sector, yf_industry):
    """Map Yahoo sector+industry to GICS sector name and 3-letter code."""
    if not yf_sector:
        return ('Unknown', 'UNK')
    # ETF is a special bucket — excluded from sector math
    if yf_sector == 'ETF':
        return ('ETF', 'ETF')
    # Special case: REITs under Financial Services → Real Estate
    if yf_sector == 'Financial Services' and yf_industry and 'REIT' in yf_industry.upper():
        return ('Real Estate', 'REA')
    return _YF_TO_GICS.get(yf_sector, ('Unknown', 'UNK'))


def portfolio_context(ticker, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ):
    """Conviction tab — portfolio concentration context for top holders.
    Returns each holder's sector breakdown with emphasis on the subject ticker's sector.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)

        # Get subject ticker's sector/industry
        subj = con.execute(
            "SELECT sector, industry FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        subj_yf_sector = subj[0] if subj else None
        subj_yf_industry = subj[1] if subj else None
        subj_gics_sector, subj_gics_code = _gics_sector(subj_yf_sector, subj_yf_industry)

        # Load US market benchmark weights for the latest data quarter.
        # Benchmark is derived from Vanguard Total Stock Market Index Fund (S000002848)
        # and stored per-quarter so historical analysis uses period-appropriate weights.
        q_date_map = {
            '2025Q1': '2025-03-31', '2025Q2': '2025-06-30',
            '2025Q3': '2025-09-30', '2025Q4': '2025-12-31',
        }
        bench_date = q_date_map.get(quarter, '2025-12-31')
        mkt_weights = {}
        try:
            bw = con.execute("""
                SELECT gics_sector, weight_pct FROM benchmark_weights
                WHERE index_name = 'US_MKT' AND as_of_date = ?
            """, [bench_date]).fetchall()
            for sec, wt in bw:
                mkt_weights[sec] = float(wt)
            # Fallback to latest available if quarter-specific not found
            if not mkt_weights:
                bw = con.execute("""
                    SELECT gics_sector, weight_pct FROM benchmark_weights
                    WHERE index_name = 'US_MKT' ORDER BY as_of_date DESC
                """).fetchall()
                for sec, wt in bw:
                    if sec not in mkt_weights:
                        mkt_weights[sec] = float(wt)
        except Exception:
            logger.debug("optional enrichment failed: mkt_weights", exc_info=True)
        subj_spx_weight = mkt_weights.get(subj_gics_sector, None)

        # Top 25 parents or funds by latest quarter value (same as Register)
        if level == 'fund':
            active_filter = "AND fu.is_actively_managed = true" if active_only else ""
            top_holders_df = con.execute(f"""
                SELECT fh.fund_name as holder, SUM(fh.market_value_usd) as val,
                       MAX(fu.is_actively_managed) as is_active
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.quarter = '{quarter}' {active_filter} AND fh.is_latest = TRUE
                GROUP BY fh.fund_name
                ORDER BY val DESC NULLS LAST LIMIT 25
            """, [ticker]).fetchdf()
        else:
            top_holders_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name, manager_name) as holder,
                       SUM(market_value_live) as val,
                       MAX(manager_type) as mtype
                FROM holdings_v2
                WHERE (ticker = ? OR cusip = ?) AND quarter = '{quarter}' AND is_latest = TRUE
                GROUP BY holder ORDER BY val DESC NULLS LAST LIMIT 25
            """, [ticker, cusip]).fetchdf()

        if top_holders_df.empty:
            return {'rows': [], 'subject_sector': subj_gics_sector,
                    'subject_sector_code': subj_gics_code,
                    'subject_industry': subj_yf_industry or ''}

        top_holders = top_holders_df['holder'].tolist()
        ph = ','.join(['?'] * len(top_holders))

        # GICS sector mapping in SQL — mirrors _gics_sector() to keep row-level
        # mapping out of Python. REIT-under-Financial-Services goes first so it
        # wins against the plain Financial Services branch.
        gics_case = """
            CASE
                WHEN m.sector = 'Financial Services' AND m.industry ILIKE '%REIT%' THEN 'Real Estate'
                WHEN m.sector = 'Technology' THEN 'Information Technology'
                WHEN m.sector = 'Financial Services' THEN 'Financials'
                WHEN m.sector = 'Healthcare' THEN 'Health Care'
                WHEN m.sector = 'Consumer Cyclical' THEN 'Consumer Discretionary'
                WHEN m.sector = 'Consumer Defensive' THEN 'Consumer Staples'
                WHEN m.sector = 'Basic Materials' THEN 'Materials'
                WHEN m.sector IN ('Industrials','Energy','Communication Services','Utilities','Real Estate') THEN m.sector
                WHEN m.sector = 'ETF' THEN 'ETF'
                ELSE 'Unknown'
            END AS gics_sector,
            CASE
                WHEN m.sector = 'Financial Services' AND m.industry ILIKE '%REIT%' THEN 'REA'
                WHEN m.sector = 'Technology' THEN 'TEC'
                WHEN m.sector = 'Financial Services' THEN 'FIN'
                WHEN m.sector = 'Healthcare' THEN 'HCR'
                WHEN m.sector = 'Industrials' THEN 'IND'
                WHEN m.sector = 'Consumer Cyclical' THEN 'CND'
                WHEN m.sector = 'Consumer Defensive' THEN 'CNS'
                WHEN m.sector = 'Energy' THEN 'ENE'
                WHEN m.sector = 'Basic Materials' THEN 'MAT'
                WHEN m.sector = 'Communication Services' THEN 'COM'
                WHEN m.sector = 'Utilities' THEN 'UTL'
                WHEN m.sector = 'Real Estate' THEN 'REA'
                WHEN m.sector = 'ETF' THEN 'ETF'
                ELSE 'UNK'
            END AS gics_code"""

        # Pull full portfolios for all top holders in one query, grouped by sector
        if level == 'fund':
            portfolio_df = con.execute(f"""
                SELECT
                    fh.fund_name as holder,
                    fh.ticker,
                    COALESCE(m.sector, 'Unknown') as yf_sector,
                    COALESCE(m.industry, '') as yf_industry,
                    {gics_case},
                    SUM(fh.market_value_usd) as value
                FROM fund_holdings_v2 fh
                LEFT JOIN market_data m ON fh.ticker = m.ticker
                WHERE fh.quarter = '{quarter}' AND fh.fund_name IN ({ph})
                  AND fh.market_value_usd > 0
                  AND fh.is_latest = TRUE
                GROUP BY fh.fund_name, fh.ticker, m.sector, m.industry
            """, top_holders).fetchdf()
        else:
            portfolio_df = con.execute(f"""
                SELECT
                    COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as holder,
                    h.ticker,
                    COALESCE(m.sector, 'Unknown') as yf_sector,
                    COALESCE(m.industry, '') as yf_industry,
                    {gics_case},
                    SUM(h.market_value_live) as value
                FROM holdings_v2 h
                LEFT JOIN market_data m ON h.ticker = m.ticker
                WHERE h.quarter = '{quarter}'
                  AND COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) IN ({ph})
                  AND h.market_value_live > 0
                  AND h.is_latest = TRUE
                GROUP BY holder, h.ticker, m.sector, m.industry
            """, top_holders).fetchdf()

        def _compute_metrics(holder_df, subject_value):
            """Compute all concentration metrics for a single holder's portfolio.
            Vectorized: gics_sector/gics_code come pre-computed from SQL, so all
            per-row work collapses to groupby / boolean mask / idxmax."""
            if holder_df.empty:
                return None
            total = float(holder_df['value'].sum())
            if total <= 0:
                return None

            gics_col = holder_df['gics_sector']
            unknown_val = float(holder_df.loc[gics_col == 'Unknown', 'value'].sum())
            etf_val = float(holder_df.loc[gics_col == 'ETF', 'value'].sum())
            unk_pct_ = round(unknown_val / total * 100, 1)
            etf_pct_ = round(etf_val / total * 100, 1)

            real = holder_df.loc[~gics_col.isin(['Unknown', 'ETF'])]
            sector_sums = real.groupby(['gics_sector', 'gics_code'], sort=False)['value'].sum()
            sorted_s = sector_sums.sort_values(ascending=False)

            subj_sec_value = float(sorted_s.get((subj_gics_sector, subj_gics_code), 0))
            subj_sec_pct = round(subj_sec_value / total * 100, 1)

            subj_sec_rank = None
            if len(sorted_s) > 0:
                sec_names = sorted_s.index.get_level_values('gics_sector')
                sec_mask = sec_names == subj_gics_sector
                if sec_mask.any():
                    subj_sec_rank = int(sec_mask.argmax()) + 1

            co_rank = None
            if subj_sec_value > 0:
                sec_rows = (holder_df.loc[gics_col == subj_gics_sector]
                            .sort_values('value', ascending=False)
                            .reset_index(drop=True))
                co_mask = sec_rows['ticker'] == ticker
                if co_mask.any():
                    co_rank = int(co_mask.idxmax()) + 1

            ind_rank = None
            if subj_yf_industry:
                ind_rows = (holder_df.loc[holder_df['yf_industry'] == subj_yf_industry]
                            .sort_values('value', ascending=False)
                            .reset_index(drop=True))
                ind_mask = ind_rows['ticker'] == ticker
                if ind_mask.any():
                    ind_rank = int(ind_mask.idxmax()) + 1

            top3_ = [{'code': code, 'weight_pct': round(float(val) / total * 100, 1)}
                     for (_, code), val in sorted_s.head(3).items()]
            vs_ = round(subj_sec_pct - subj_spx_weight, 1) if subj_spx_weight is not None else None
            score_ = 0
            if vs_ is not None:
                score_ += max(0, min(vs_ / 50 * 40, 40))
            if subj_sec_rank == 1: score_ += 20
            elif subj_sec_rank == 2: score_ += 10
            elif subj_sec_rank == 3: score_ += 5
            if co_rank == 1: score_ += 15
            elif co_rank == 2: score_ += 10
            elif co_rank == 3: score_ += 5
            if ind_rank == 1: score_ += 15
            elif ind_rank == 2: score_ += 10
            elif ind_rank == 3: score_ += 5

            return {
                'value': subject_value,
                'subject_sector_pct': subj_sec_pct,
                'vs_spx': vs_,
                'conviction_score': round(score_, 0),
                'sector_rank': subj_sec_rank,
                'co_rank_in_sector': co_rank,
                'industry_rank': ind_rank,
                'top3': top3_,
                'diversity': int(sector_sums.size),
                'unk_pct': unk_pct_,
                'etf_pct': etf_pct_,
            }

        # Build per-holder aggregates
        results = []
        for idx, h_row in top_holders_df.iterrows():
            holder = h_row['holder']
            subject_value = float(h_row['val'] or 0)

            holder_df = portfolio_df[portfolio_df['holder'] == holder]
            metrics = _compute_metrics(holder_df, subject_value)
            if metrics is None:
                continue

            # Type
            if level == 'fund':
                row_type = 'active' if h_row.get('is_active') else 'passive'
            else:
                row_type = h_row.get('mtype') or 'unknown'

            results.append({
                'rank': idx + 1,
                'institution': holder,
                'type': row_type,
                'value': metrics['value'],
                'subject_sector_pct': metrics['subject_sector_pct'],
                'vs_spx': metrics['vs_spx'],
                'conviction_score': metrics['conviction_score'],
                'sector_rank': metrics['sector_rank'],
                'co_rank_in_sector': metrics['co_rank_in_sector'],
                'industry_rank': metrics['industry_rank'],
                'top3': metrics['top3'],
                'diversity': metrics['diversity'],
                'unk_pct': metrics['unk_pct'],
                'etf_pct': metrics['etf_pct'],
                'level': 0,
                'is_parent': False,
                'child_count': 0,
            })

        # Keep the top-25-by-value order (same as Register) — do NOT resort by score.
        # Frontend allows user to click column headers to sort interactively.
        for i, r in enumerate(results, 1):
            r['rank'] = i

        # --- Children: top 5 N-PORT funds per parent (parent level only) ---
        if level == 'parent':
            # Fetch top 5 N-PORT children per parent — batched (ARCH-2A.1).
            parent_list = [pr['institution'] for pr in results]
            children_by_parent = get_nport_children_batch(parent_list, ticker, quarter, con, limit=5)
            all_child_funds = set()
            for kids in children_by_parent.values():
                for k in kids:
                    if k.get('institution'):
                        all_child_funds.add(k['institution'])

            if all_child_funds:
                # Batch query portfolios for all child funds
                ph_funds = ','.join(['?'] * len(all_child_funds))
                child_portfolio_df = con.execute(f"""
                    SELECT
                        fh.fund_name as holder,
                        fh.ticker,
                        COALESCE(m.sector, 'Unknown') as yf_sector,
                        COALESCE(m.industry, '') as yf_industry,
                        {gics_case},
                        SUM(fh.market_value_usd) as value
                    FROM fund_holdings_v2 fh
                    LEFT JOIN market_data m ON fh.ticker = m.ticker
                    WHERE fh.quarter = '{quarter}' AND fh.fund_name IN ({ph_funds})
                      AND fh.market_value_usd > 0
                      AND fh.is_latest = TRUE
                    GROUP BY fh.fund_name, fh.ticker, m.sector, m.industry
                """, list(all_child_funds)).fetchdf()

                # Also need is_actively_managed per fund for child type
                fund_meta_df = con.execute(f"""
                    SELECT DISTINCT fh.fund_name, COALESCE(MAX(CAST(fu.is_actively_managed AS INTEGER)), 0) as is_active
                    FROM fund_holdings_v2 fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.fund_name IN ({ph_funds}) AND fh.quarter = '{quarter}' AND fh.is_latest = TRUE
                    GROUP BY fh.fund_name
                """, list(all_child_funds)).fetchdf()
                fund_is_active = {r['fund_name']: bool(r['is_active']) for _, r in fund_meta_df.iterrows()}

                # Build results with children interleaved under each parent
                new_results = []
                for parent_row in results:
                    pname = parent_row['institution']
                    kids = children_by_parent.get(pname, [])
                    if kids:
                        parent_row['is_parent'] = True
                        parent_row['child_count'] = len(kids)
                    new_results.append(parent_row)

                    for kid in kids:
                        fund_name = kid.get('institution')
                        subj_val = float(kid.get('value_live') or 0)
                        kid_df = child_portfolio_df[child_portfolio_df['holder'] == fund_name]
                        kid_metrics = _compute_metrics(kid_df, subj_val)
                        if kid_metrics is None:
                            # Child has no portfolio data — show with just position
                            new_results.append({
                                'institution': fund_name,
                                'type': 'active' if fund_is_active.get(fund_name, False) else 'passive',
                                'value': subj_val,
                                'subject_sector_pct': None,
                                'vs_spx': None,
                                'conviction_score': 0,
                                'sector_rank': None,
                                'co_rank_in_sector': None,
                                'industry_rank': None,
                                'top3': [],
                                'diversity': 0,
                                'unk_pct': None,
                                'etf_pct': None,
                                'level': 1,
                                'is_parent': False,
                                'child_count': 0,
                                'parent_name': pname,
                            })
                        else:
                            new_results.append({
                                'institution': fund_name,
                                'type': 'active' if fund_is_active.get(fund_name, False) else 'passive',
                                'value': kid_metrics['value'],
                                'subject_sector_pct': kid_metrics['subject_sector_pct'],
                                'vs_spx': kid_metrics['vs_spx'],
                                'conviction_score': kid_metrics['conviction_score'],
                                'sector_rank': kid_metrics['sector_rank'],
                                'co_rank_in_sector': kid_metrics['co_rank_in_sector'],
                                'industry_rank': kid_metrics['industry_rank'],
                                'top3': kid_metrics['top3'],
                                'diversity': kid_metrics['diversity'],
                                'unk_pct': kid_metrics['unk_pct'],
                                'etf_pct': kid_metrics['etf_pct'],
                                'level': 1,
                                'is_parent': False,
                                'child_count': 0,
                                'parent_name': pname,
                            })
                results = new_results

        return {
            'rows': results,
            'subject_sector': subj_gics_sector,
            'subject_sector_code': subj_gics_code,
            'subject_industry': subj_yf_industry or '',
            'subject_spx_weight': subj_spx_weight,
            'level': level,
            'active_only': active_only,
        }
    finally:
        pass
