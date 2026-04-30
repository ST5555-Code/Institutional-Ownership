"""Cross-ownership and two-company overlap queries."""

import pandas as pd

from serializers import (
    clean_for_json,
)
from .common import (
    LQ,
    _rollup_col,
    _quarter_to_date,
    _resolve_pct_of_so_denom,
)



def _cross_ownership_query(con, tickers, anchor=None, active_only=False, limit=25, rollup_type='economic_control_v1', quarter=LQ):
    """Shared logic for cross-ownership matrix.

    If anchor is set: rows = top holders of that ticker, ordered by anchor holding.
    If anchor is None: rows = top holders by total across all tickers.
    """
    rn = _rollup_col(rollup_type)
    # Company names
    placeholders = ','.join(['?'] * len(tickers))
    names_df = con.execute(f"""
        SELECT ticker, MODE(issuer_name) as name
        FROM holdings_v2
        WHERE ticker IN ({placeholders}) AND quarter = '{quarter}' AND is_latest = TRUE
        GROUP BY ticker
    """, tickers).fetchdf()
    companies = {r['ticker']: r['name'] for _, r in names_df.iterrows()}

    type_filter = "AND h.entity_type NOT IN ('passive')" if active_only else ""
    all_tickers_ph = ','.join(['?'] * len(tickers))

    pivot_cols = ', '.join(
        "SUM(CASE WHEN ph.ticker = '{}' THEN ph.holding_value END) AS \"{}\"".format(t, t)  # pylint: disable=duplicate-string-formatting-argument
        for t in tickers
    )
    total_expr = ' + '.join('COALESCE("{}", 0)'.format(t) for t in tickers)

    if anchor and anchor in tickers:
        order_clause = 'COALESCE("{}", 0) DESC'.format(anchor)
    else:
        order_clause = '({}) DESC'.format(total_expr)

    df = con.execute(f"""
        WITH parent_holdings AS (
            SELECT
                COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as investor,
                MAX(h.manager_type) as type,
                h.ticker,
                SUM(h.market_value_live) as holding_value
            FROM holdings_v2 h
            WHERE h.ticker IN ({all_tickers_ph})
              AND h.quarter = '{quarter}'
              {type_filter}
              AND h.is_latest = TRUE
            GROUP BY investor, h.ticker
        ),
        portfolio_totals AS (
            SELECT
                COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as investor,
                SUM(h.market_value_live) as total_portfolio
            FROM holdings_v2 h
            WHERE h.quarter = '{quarter}' AND h.is_latest = TRUE
            GROUP BY investor
        )
        SELECT
            ph.investor,
            MAX(ph.type) as type,
            pt.total_portfolio,
            {pivot_cols}
        FROM parent_holdings ph
        LEFT JOIN portfolio_totals pt ON ph.investor = pt.investor
        GROUP BY ph.investor, pt.total_portfolio
        ORDER BY {order_clause}
        LIMIT {int(limit)}
    """, tickers).fetchdf()

    investors = []
    for _, row in df.iterrows():
        ticker_holdings = {}
        total_across = 0
        for t in tickers:
            val = row[t]
            if pd.notna(val) and val != 0:
                ticker_holdings[t] = float(val)
                total_across += float(val)
            else:
                ticker_holdings[t] = None
        total_port = float(row['total_portfolio']) if pd.notna(row['total_portfolio']) and row['total_portfolio'] > 0 else None
        pct = round(total_across / total_port * 100, 4) if total_port else None
        investors.append({
            'investor': row['investor'],
            'type': row['type'],
            'holdings': ticker_holdings,
            'total_across': total_across if total_across > 0 else None,
            'pct_of_portfolio': pct,
        })

    return clean_for_json({
        'tickers': tickers,
        'companies': companies,
        'investors': investors,
    })


# ---------------------------------------------------------------------------
# Market Summary — top institutions by 13F book value
# ---------------------------------------------------------------------------


def get_two_company_overlap(subject, second, quarter, con):
    """Compare institutional + fund holders of two tickers in a single quarter.

    Returns: {'institutional': [...], 'fund': [...], 'meta': {...}}
    """
    # --- 3a. Period-accurate denominator for both tickers (null-safe) ----
    # Tier cascade: SOH quarter-end → md.shares_outstanding → md.float_shares.
    # N-PORT fund holdings aggregate to `quarter`; quarter-end anchor is
    # the representative reference date (same staleness caveat applies).
    qe = _quarter_to_date(quarter)
    subj_denom, subj_denom_source = _resolve_pct_of_so_denom(con, subject, qe)
    sec_denom, sec_denom_source = _resolve_pct_of_so_denom(con, second, qe)

    # --- 3b. Institutional panel (top 50 by Subject $) -------------------
    inst_rows = con.execute("""
        WITH subj_holders AS (
            SELECT
                COALESCE(h.rollup_name, h.inst_parent_name, h.manager_name) as holder,
                MAX(h.manager_type) as manager_type,
                SUM(h.shares) as subj_shares,
                SUM(h.market_value_live) as subj_dollars
            FROM holdings_v2 h
            WHERE h.ticker = ?
              AND h.quarter = ?
              AND h.market_value_live > 0
              AND h.is_latest = TRUE
            GROUP BY holder
        ),
        sec_holders AS (
            SELECT
                COALESCE(h.rollup_name, h.inst_parent_name, h.manager_name) as holder,
                SUM(h.shares) as sec_shares,
                SUM(h.market_value_live) as sec_dollars
            FROM holdings_v2 h
            WHERE h.ticker = ?
              AND h.quarter = ?
              AND h.market_value_live > 0
              AND h.is_latest = TRUE
            GROUP BY holder
        )
        SELECT
            s.holder,
            s.manager_type,
            s.subj_shares,
            s.subj_dollars,
            COALESCE(p.sec_shares, 0)   as sec_shares,
            COALESCE(p.sec_dollars, 0)  as sec_dollars
        FROM subj_holders s
        LEFT JOIN sec_holders p ON p.holder = s.holder
        ORDER BY s.subj_dollars DESC
        LIMIT 50
    """, [subject, quarter, second, quarter]).fetchall()

    institutional = []
    for r in inst_rows:
        holder, mtype, subj_shares, subj_dollars, sec_shares, sec_dollars = r
        subj_shares_f = float(subj_shares) if subj_shares is not None else 0.0
        sec_shares_f = float(sec_shares) if sec_shares is not None else 0.0
        subj_dollars_f = float(subj_dollars) if subj_dollars is not None else 0.0
        sec_dollars_f = float(sec_dollars) if sec_dollars is not None else 0.0
        institutional.append({
            'holder': holder,
            'manager_type': mtype,
            'subj_shares': subj_shares_f,
            'subj_dollars': subj_dollars_f,
            'subj_pct_so': (subj_shares_f / subj_denom * 100.0) if subj_denom else None,
            'subj_pct_of_so_source': subj_denom_source if subj_denom else None,
            'sec_shares': sec_shares_f,
            'sec_dollars': sec_dollars_f,
            'sec_pct_so': (sec_shares_f / sec_denom * 100.0) if sec_denom else None,
            'sec_pct_of_so_source': sec_denom_source if sec_denom else None,
            'is_overlap': bool(subj_dollars_f > 0 and sec_dollars_f > 0),
        })

    # --- 3c. Fund panel (top 50 by Subject $) ----------------------------
    fund_rows = con.execute("""
        WITH subj_funds AS (
            SELECT
                fh.fund_name as holder,
                fh.series_id,
                fh.family_name,
                SUM(fh.shares_or_principal) as subj_shares,
                SUM(fh.market_value_usd)    as subj_dollars
            FROM fund_holdings_v2 fh
            WHERE fh.ticker = ?
              AND fh.quarter = ?
              AND fh.market_value_usd > 0
              AND fh.is_latest = TRUE
            GROUP BY fh.fund_name, fh.series_id, fh.family_name
        ),
        sec_funds AS (
            SELECT
                fh.fund_name as holder,
                fh.series_id,
                SUM(fh.shares_or_principal) as sec_shares,
                SUM(fh.market_value_usd)    as sec_dollars
            FROM fund_holdings_v2 fh
            WHERE fh.ticker = ?
              AND fh.quarter = ?
              AND fh.market_value_usd > 0
              AND fh.is_latest = TRUE
            GROUP BY fh.fund_name, fh.series_id
        )
        SELECT
            s.holder,
            s.series_id,
            s.family_name,
            s.subj_shares,
            s.subj_dollars,
            COALESCE(p.sec_shares, 0)  as sec_shares,
            COALESCE(p.sec_dollars, 0) as sec_dollars,
            fu.is_actively_managed     as is_active
        FROM subj_funds s
        LEFT JOIN sec_funds p ON p.series_id = s.series_id
        LEFT JOIN fund_universe fu ON fu.series_id = s.series_id
        ORDER BY s.subj_dollars DESC
        LIMIT 50
    """, [subject, quarter, second, quarter]).fetchall()

    fund = []
    for r in fund_rows:
        holder, series_id, family_name, subj_shares, subj_dollars, sec_shares, sec_dollars, is_active = r
        subj_shares_f = float(subj_shares) if subj_shares is not None else 0.0
        sec_shares_f = float(sec_shares) if sec_shares is not None else 0.0
        subj_dollars_f = float(subj_dollars) if subj_dollars is not None else 0.0
        sec_dollars_f = float(sec_dollars) if sec_dollars is not None else 0.0
        fund.append({
            'holder': holder,
            'series_id': series_id,
            'family_name': family_name,
            'subj_shares': subj_shares_f,
            'subj_dollars': subj_dollars_f,
            'subj_pct_so': (subj_shares_f / subj_denom * 100.0) if subj_denom else None,
            'subj_pct_of_so_source': subj_denom_source if subj_denom else None,
            'sec_shares': sec_shares_f,
            'sec_dollars': sec_dollars_f,
            'sec_pct_so': (sec_shares_f / sec_denom * 100.0) if sec_denom else None,
            'sec_pct_of_so_source': sec_denom_source if sec_denom else None,
            'is_overlap': bool(subj_dollars_f > 0 and sec_dollars_f > 0),
            # fund_universe.is_actively_managed — None if the fund isn't in
            # fund_universe; the frontend treats None as "active" (included
            # in active-only view) rather than silently dropping rows.
            'is_active': bool(is_active) if is_active is not None else None,
        })

    # --- 3d. Meta block --------------------------------------------------
    name_rows = con.execute("""
        SELECT ticker, MODE(issuer_name) as name
        FROM holdings_v2
        WHERE ticker IN (?, ?) AND quarter = ? AND is_latest = TRUE
        GROUP BY ticker
    """, [subject, second, quarter]).fetchall()
    name_map = {row[0]: row[1] for row in name_rows}

    meta = {
        'subject': subject,
        'second': second,
        'quarter': quarter,
        'subj_denom': subj_denom,
        'subj_pct_of_so_source': subj_denom_source,
        'sec_denom': sec_denom,
        'sec_pct_of_so_source': sec_denom_source,
        'subject_name': name_map.get(subject),
        'second_name': name_map.get(second),
    }

    return clean_for_json({
        'institutional': institutional,
        'fund': fund,
        'meta': meta,
    })


def get_overlap_institution_detail(subject, second, institution, quarter, con):
    """Drill-down into an institution's funds for a two-ticker overlap view.

    Returns funds under `institution` (matched on fund_holdings_v2.dm_rollup_name
    or family_name) holding `subject` and/or `second` in `quarter`. Funds that
    hold both are returned in `overlapping`; funds that hold only one are in
    `non_overlapping`.
    """
    rows = con.execute("""
        WITH inst_funds AS (
            SELECT DISTINCT
                fh.fund_name,
                fh.series_id,
                fh.family_name
            FROM fund_holdings_v2 fh
            WHERE fh.quarter = ?
              AND fh.is_latest = TRUE
              AND (fh.dm_rollup_name = ? OR fh.family_name = ?)
              AND fh.ticker IN (?, ?)
        ),
        subj_pos AS (
            SELECT fh.series_id, SUM(fh.market_value_usd) AS value
            FROM fund_holdings_v2 fh
            WHERE fh.quarter = ?
              AND fh.is_latest = TRUE
              AND fh.ticker = ?
              AND fh.market_value_usd > 0
            GROUP BY fh.series_id
        ),
        sec_pos AS (
            SELECT fh.series_id, SUM(fh.market_value_usd) AS value
            FROM fund_holdings_v2 fh
            WHERE fh.quarter = ?
              AND fh.is_latest = TRUE
              AND fh.ticker = ?
              AND fh.market_value_usd > 0
            GROUP BY fh.series_id
        )
        SELECT
            f.fund_name,
            f.series_id,
            f.family_name,
            fu.is_actively_managed AS is_active,
            COALESCE(sp.value, 0) AS value_a,
            COALESCE(xp.value, 0) AS value_b
        FROM inst_funds f
        LEFT JOIN subj_pos sp ON sp.series_id = f.series_id
        LEFT JOIN sec_pos  xp ON xp.series_id = f.series_id
        LEFT JOIN fund_universe fu ON fu.series_id = f.series_id
        ORDER BY (COALESCE(sp.value, 0) + COALESCE(xp.value, 0)) DESC
    """, [quarter, institution, institution, subject, second,
          quarter, subject,
          quarter, second]).fetchall()

    overlapping = []
    non_overlapping = []
    for r in rows:
        fund_name, series_id, family_name, is_active, value_a, value_b = r
        va = float(value_a) if value_a is not None else 0.0
        vb = float(value_b) if value_b is not None else 0.0
        if va <= 0 and vb <= 0:
            continue
        type_label = (
            'active' if is_active is True
            else 'passive' if is_active is False
            else 'mixed'
        )
        if va > 0 and vb > 0:
            overlapping.append({
                'fund_name': fund_name,
                'series_id': series_id,
                'family_name': family_name,
                'type': type_label,
                'value_a': va,
                'value_b': vb,
            })
        else:
            non_overlapping.append({
                'fund_name': fund_name,
                'series_id': series_id,
                'family_name': family_name,
                'type': type_label,
                'holds': subject if va > 0 else second,
                'value': va if va > 0 else vb,
            })

    return clean_for_json({
        'institution': institution,
        'subject': subject,
        'second': second,
        'quarter': quarter,
        'overlapping': overlapping,
        'non_overlapping': non_overlapping,
    })


def get_two_company_subject(subject, quarter, con):
    """Subject-only variant of get_two_company_overlap.

    Used by the 2 Companies Overlap tab for the immediate first render when
    no second ticker has been selected yet. Returns the same payload shape
    as get_two_company_overlap — {'institutional': [...], 'fund': [...],
    'meta': {...}} — with every `sec_*` field set to None so the frontend
    can render "—" placeholders in the second-company columns. The subject
    panels are top 50 holders ordered by dollar value, same as the overlap
    endpoint's left-hand side.
    """
    # --- Period-accurate denominator for percent-of-SO computation -------
    # Tier cascade: SOH quarter-end → md.shares_outstanding → md.float_shares.
    subj_denom, subj_denom_source = _resolve_pct_of_so_denom(
        con, subject, _quarter_to_date(quarter))

    # --- Institutional panel (top 50 holders of subject) -----------------
    inst_rows = con.execute("""
        SELECT
            COALESCE(h.rollup_name, h.inst_parent_name, h.manager_name) as holder,
            MAX(h.manager_type) as manager_type,
            SUM(h.shares) as subj_shares,
            SUM(h.market_value_live) as subj_dollars
        FROM holdings_v2 h
        WHERE h.ticker = ?
          AND h.quarter = ?
          AND h.market_value_live > 0
          AND h.is_latest = TRUE
        GROUP BY holder
        ORDER BY subj_dollars DESC
        LIMIT 50
    """, [subject, quarter]).fetchall()

    institutional = []
    for r in inst_rows:
        holder, mtype, subj_shares, subj_dollars = r
        subj_shares_f = float(subj_shares) if subj_shares is not None else 0.0
        subj_dollars_f = float(subj_dollars) if subj_dollars is not None else 0.0
        institutional.append({
            'holder': holder,
            'manager_type': mtype,
            'subj_shares': subj_shares_f,
            'subj_dollars': subj_dollars_f,
            'subj_pct_so': (subj_shares_f / subj_denom * 100.0) if subj_denom else None,
            'subj_pct_of_so_source': subj_denom_source if subj_denom else None,
            'sec_shares': None,
            'sec_dollars': None,
            'sec_pct_so': None,
            'sec_pct_of_so_source': None,
            'is_overlap': False,
        })

    # --- Fund panel (top 50 fund series by NAV position in subject) ------
    fund_rows = con.execute("""
        WITH subj_funds AS (
            SELECT
                fh.fund_name as holder,
                fh.series_id,
                fh.family_name,
                SUM(fh.shares_or_principal) as subj_shares,
                SUM(fh.market_value_usd)    as subj_dollars
            FROM fund_holdings_v2 fh
            WHERE fh.ticker = ?
              AND fh.quarter = ?
              AND fh.market_value_usd > 0
              AND fh.is_latest = TRUE
            GROUP BY fh.fund_name, fh.series_id, fh.family_name
        )
        SELECT
            s.holder,
            s.series_id,
            s.family_name,
            s.subj_shares,
            s.subj_dollars,
            fu.is_actively_managed as is_active
        FROM subj_funds s
        LEFT JOIN fund_universe fu ON fu.series_id = s.series_id
        ORDER BY s.subj_dollars DESC
        LIMIT 50
    """, [subject, quarter]).fetchall()

    fund = []
    for r in fund_rows:
        holder, series_id, family_name, subj_shares, subj_dollars, is_active = r
        subj_shares_f = float(subj_shares) if subj_shares is not None else 0.0
        subj_dollars_f = float(subj_dollars) if subj_dollars is not None else 0.0
        fund.append({
            'holder': holder,
            'series_id': series_id,
            'family_name': family_name,
            'subj_shares': subj_shares_f,
            'subj_dollars': subj_dollars_f,
            'subj_pct_so': (subj_shares_f / subj_denom * 100.0) if subj_denom else None,
            'subj_pct_of_so_source': subj_denom_source if subj_denom else None,
            'sec_shares': None,
            'sec_dollars': None,
            'sec_pct_so': None,
            'sec_pct_of_so_source': None,
            'is_overlap': False,
            'is_active': bool(is_active) if is_active is not None else None,
        })

    # --- Meta block ------------------------------------------------------
    name_row = con.execute("""
        SELECT MODE(issuer_name) as name
        FROM holdings_v2
        WHERE ticker = ? AND quarter = ? AND is_latest = TRUE
    """, [subject, quarter]).fetchone()
    subject_name = name_row[0] if name_row else None

    meta = {
        'subject': subject,
        'second': None,
        'quarter': quarter,
        'subj_denom': subj_denom,
        'subj_pct_of_so_source': subj_denom_source,
        'sec_denom': None,
        'sec_pct_of_so_source': None,
        'subject_name': subject_name,
        'second_name': None,
    }

    return clean_for_json({
        'institutional': institutional,
        'fund': fund,
        'meta': meta,
    })
