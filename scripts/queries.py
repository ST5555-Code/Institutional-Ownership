"""
queries.py — SQL query functions for the 13F ownership research app.

All database queries are defined here. Route handlers in app.py
import and call these functions — no raw SQL in app.py.
"""

import logging
import math
import pandas as pd
# import duckdb  # unused, connection passed in
from config import QUARTERS, LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER, SUBADVISER_EXCLUSIONS
from cache import cached, CACHE_KEY_SUMMARY
# Response-shaping helpers moved to serializers.py in Phase 4 Batch 4-B.
# clean_for_json / df_to_records are re-exported here so existing handler
# imports (`from queries import clean_for_json, df_to_records`) keep
# working without touching api_*.py files.
from serializers import (  # noqa: F401 — re-exports for backward compat
    clean_for_json,
    df_to_records,
    resolve_filer_names_in_records,
    _13f_entity_footnote,
    get_subadviser_note,
)

logger = logging.getLogger(__name__)

# --- Rollup type parameterization ---
VALID_ROLLUP_TYPES = {'economic_control_v1', 'decision_maker_v1'}

def _rollup_col(rollup_type='economic_control_v1'):
    """Return the rollup column name for the given rollup type.
    economic_control_v1 -> 'rollup_name' (fund sponsor / voting)
    decision_maker_v1   -> 'dm_rollup_name' (sub-adviser making decisions)
    """
    if rollup_type not in VALID_ROLLUP_TYPES:
        raise ValueError(f'Invalid rollup_type: {rollup_type}. Must be one of {VALID_ROLLUP_TYPES}')
    return 'dm_rollup_name' if rollup_type == 'decision_maker_v1' else 'rollup_name'


LQ = LATEST_QUARTER
FQ = FIRST_QUARTER
PQ = PREV_QUARTER

# Lazy import to avoid circular dependency with app.py
_get_db = None
_has_table = None


def _setup(get_db_fn, has_table_fn):
    """Called by app.py at startup to inject DB access functions."""
    global _get_db, _has_table  # pylint: disable=global-statement
    _get_db = get_db_fn
    _has_table = has_table_fn


def get_db():
    """Get a read-only DuckDB connection."""
    if _get_db is None:
        raise RuntimeError("queries._setup() not called — import queries in app.py and call queries._setup(get_db, has_table)")
    return _get_db()


def has_table(name):
    if _has_table is None:
        return True  # assume exists if not initialized
    return _has_table(name)



def get_cusip(con, ticker):
    """Resolve ticker to CUSIP."""
    row = con.execute(
        "SELECT cusip FROM securities WHERE ticker = ? LIMIT 1", [ticker]
    ).fetchone()
    return row[0] if row else ''


# ---------------------------------------------------------------------------
# Filer name → institutional parent resolution
# ---------------------------------------------------------------------------

# Filer-name → institutional parent resolution moved to serializers.py in
# Phase 4 Batch 4-B. `resolve_filer_to_parent` / `resolve_filer_names_in_records`
# imported at the top of this module and used unchanged below.


# ---------------------------------------------------------------------------
# N-PORT family name matching utility
# ---------------------------------------------------------------------------


# Fallback dict used when the fund_family_patterns table is missing or empty
# (fresh deploy before Batch 3-A migration has run). Kept here verbatim so a
# broken DDL does not take down match_nport_family(). The DB is the
# authoritative source once migrated; remove this constant in a later pass
# after confirming no deploy path is missing the table.
_FAMILY_PATTERNS_FALLBACK = {
    'fidelity': ['Fidelity', 'FMR', 'Puritan', 'Rutland', 'Strategic Advisers'],
    'geode': ['Geode'],
    'vanguard': ['Vanguard'],
    'blackrock': ['BlackRock', 'iShares', 'BGFA'],
    'wellington': ['Wellington'],
    't. rowe': ['T. Rowe', 'Price Associates'],
    'dimensional': ['DFA', 'Dimensional'],
    'mfs': ['MFS', 'Massachusetts Financial'],
    'neuberger': ['Neuberger Berman'],
    'aqr': ['AQR'],
    'loomis': ['Loomis Sayles'],
    'victory': ['Victory Capital'],
    'american century': ['American Century'],
    'dodge': ['Dodge & Cox'],
    'putnam': ['Putnam'],
    'columbia': ['Columbia'],
    'invesco': ['Invesco', 'AIM', 'PowerShares'],
    'jpmorgan': ['JPMorgan', 'J.P. Morgan'],
    'goldman': ['Goldman Sachs'],
    'morgan stanley': ['Morgan Stanley', 'Eaton Vance'],
    'nuveen': ['Nuveen', 'TIAA', 'Teachers'],
    'northern trust': ['Northern Trust', 'FlexShares'],
    'state street': ['State Street', 'SSGA', 'SPDR', 'Select Sector'],
    'pimco': ['PIMCO', 'Pacific Investment'],
    'franklin': ['Franklin', 'Templeton'],
    'affiliated managers': ['AMG', 'Affiliated Managers'],
    'harbor': ['Harbor'],
    'carillon': ['Carillon'],
    'calvert': ['Calvert'],
    'baird': ['Baird'],
    'principal': ['Principal'],
    'lord abbett': ['Lord Abbett'],
    'alliancebernstein': ['AllianceBernstein', 'AB Funds'],
    'lazard': ['Lazard'],
    'royce': ['Royce'],
    'gabelli': ['Gabelli'],
    'oakmark': ['Oakmark', 'Harris Associates'],
    'artisan': ['Artisan'],
    'brown advisory': ['Brown Advisory'],
    'wasatch': ['Wasatch'],
    'william blair': ['William Blair'],
    'parnassus': ['Parnassus'],
    'calamos': ['Calamos'],
    'schwab': ['Schwab', 'Charles Schwab'],
    'capital group': ['Capital Research', 'Capital Group', 'American Funds'],
    'deutsche': ['DWS', 'Xtrackers', 'Deutsche'],
    'bny mellon': ['BNY', 'Mellon', 'Dreyfus'],
    'ubs': ['UBS'],
    'bank of america': ['BofA', 'Merrill Lynch'],
    'legal & general': ['Legal & General', 'L&G'],
}

_family_patterns_cache = None


def get_nport_family_patterns():
    """Map inst_parent_name keywords to N-PORT fund_holdings family_name
    search patterns.

    Reads from the fund_family_patterns DB table (Batch 3-A, ARCH-3A).
    Falls back to _FAMILY_PATTERNS_FALLBACK if the table is missing,
    empty, or the DB is unreachable (e.g., during testing without the
    staging / prod DDL applied).

    Memoized at module scope — patterns are effectively static during
    a process lifetime. Restart the app to pick up new DB rows.
    """
    global _family_patterns_cache  # pylint: disable=global-statement
    if _family_patterns_cache is not None:
        return _family_patterns_cache
    try:
        con = get_db()
        rows = con.execute("""
            SELECT inst_parent_name, pattern
            FROM fund_family_patterns
            ORDER BY inst_parent_name, pattern
        """).fetchall()
        if rows:
            grouped = {}
            for key, pattern in rows:
                grouped.setdefault(key, []).append(pattern)
            _family_patterns_cache = grouped
            return grouped
    except Exception as e:
        logger.warning("[get_nport_family_patterns] DB unavailable, using fallback: %s", e)
    _family_patterns_cache = _FAMILY_PATTERNS_FALLBACK
    return _FAMILY_PATTERNS_FALLBACK



def _classify_fund_type(fund_name):
    """Classify a fund as passive or active based on fund name keywords."""
    if not fund_name:
        return 'active'
    name_upper = fund_name.upper()

    # Direct keyword matches → passive
    PASSIVE_KEYWORDS = [
        'INDEX', 'ETF', 'MSCI', 'FTSE', 'STOXX', 'NIKKEI',
        'TOTAL STOCK', 'TOTAL MARKET', 'TOTAL BOND', 'TOTAL INTERNATIONAL',
        'BROAD MARKET', 'TRACKER',
        'NASDAQ', 'DOW JONES', 'WILSHIRE',
    ]
    if any(kw in name_upper for kw in PASSIVE_KEYWORDS):
        return 'passive'

    # Index number + known index name → passive
    # Catches "S&P 500", "Russell 1000", "Russell 2000", "Russell 3000"
    INDEX_COMBOS = [
        ('S&P', '500'), ('S&P', '400'), ('S&P', '600'), ('S&P', '100'),
        ('RUSSELL', '1000'), ('RUSSELL', '2000'), ('RUSSELL', '3000'),
        ('BLOOMBERG', '500'), ('BLOOMBERG', 'AGGREGATE'),
        ('ALL', 'CAP INDEX'), ('ALL', 'CAP EQUITY INDEX'),
    ]
    for prefix, suffix in INDEX_COMBOS:
        if prefix in name_upper and suffix in name_upper:
            return 'passive'

    return 'active'


def match_nport_family(inst_parent_name):
    """Return list of search patterns for N-PORT family_name matching."""
    if not inst_parent_name:
        return []
    name_lower = inst_parent_name.lower()
    patterns = get_nport_family_patterns()
    for key, search_terms in patterns.items():
        # Match on key substring OR any search term substring in the parent name
        if key in name_lower or any(t.lower() in name_lower for t in search_terms):
            return search_terms
    # Fallback: use first word of the parent name
    first_word = inst_parent_name.split('/')[0].split('(')[0].strip()
    return [first_word] if first_word and len(first_word) > 2 else []



def _get_subadviser_exclusions(family_patterns):
    """Return list of adviser names to exclude for this family's N-PORT rollup."""
    exclusions = []
    for pattern in family_patterns:
        for key, excl_list in SUBADVISER_EXCLUSIONS.items():
            if key in pattern.lower():
                exclusions.extend(excl_list)
    return exclusions


def get_nport_position(family_patterns, ticker, quarter, con):
    """Query fund_holdings for a family's position in a ticker.
    Deduplicates by series_id and excludes sub-adviser positions."""
    if not family_patterns:
        return None
    try:
        like_patterns = ['%' + p + '%' for p in family_patterns]
        placeholders = ','.join(['?'] * len(like_patterns))

        # Build sub-adviser exclusion clause
        exclusions = _get_subadviser_exclusions(family_patterns)
        excl_clause = ""
        excl_params = []
        if exclusions:
            excl_placeholders = ','.join(['?'] * len(exclusions))
            excl_patterns = ['%' + e + '%' for e in exclusions]
            excl_clause = f"""
                AND fh.series_id NOT IN (
                    SELECT DISTINCT nam.series_id FROM ncen_adviser_map nam
                    WHERE EXISTS (SELECT 1 FROM UNNEST([{excl_placeholders}]) x(p) WHERE nam.adviser_name ILIKE x.p)
                )"""
            excl_params = excl_patterns

        # Deduplicate by series_id: one row per fund, then aggregate
        result = con.execute(f"""
            WITH per_fund AS (
                SELECT series_id,
                       MAX(market_value_usd) as market_value_usd,
                       MAX(shares_or_principal) as shares,
                       MAX(pct_of_nav) as pct_of_nav
                FROM fund_holdings_v2 fh
                WHERE EXISTS (SELECT 1 FROM UNNEST([{placeholders}]) t(p) WHERE family_name ILIKE t.p)
                  AND ticker = ? AND quarter = ?
                  {excl_clause}
                GROUP BY series_id
            )
            SELECT SUM(market_value_usd), SUM(shares), AVG(pct_of_nav), COUNT(*)
            FROM per_fund
        """, like_patterns + [ticker, quarter] + excl_params).fetchone()
        if result and result[0]:
            return {
                'nport_value': float(result[0]),
                'nport_shares': float(result[1]) if result[1] else None,
                'nport_pct_nav': float(result[2]) if result[2] else None,
                'fund_count': int(result[3]),
                'source': 'N-PORT',
            }
    except Exception as e:
        logger.error("[get_nport_position] %s", e, exc_info=True)
    return None



def get_nport_coverage(ticker, quarter, con):
    """Get overall N-PORT coverage stats for a ticker. Deduplicates by series_id."""
    try:
        result = con.execute("""
            WITH per_fund AS (
                SELECT series_id,
                       MAX(market_value_usd) as market_value_usd
                FROM fund_holdings_v2
                WHERE ticker = ? AND quarter = ?
                GROUP BY series_id
            )
            SELECT SUM(market_value_usd) as total_value,
                   COUNT(*) as fund_count
            FROM per_fund
        """, [ticker, quarter]).fetchone()
        if result and result[0]:
            return {'nport_total_value': float(result[0]), 'nport_fund_count': int(result[1])}
    except Exception as e:
        logger.error("[get_nport_coverage] %s", e, exc_info=True)
    return {'nport_total_value': None, 'nport_fund_count': 0}


# ---------------------------------------------------------------------------
# Subadviser notes — explains why some managers show 13F instead of N-PORT
# ---------------------------------------------------------------------------


# _13f_entity_footnote / get_subadviser_note / SUBADVISER_NOTES /
# _13F_ENTITY_NOTES moved to serializers.py (Phase 4 Batch 4-B). The two
# helper functions are imported at the top of this module and used below.


def _build_excl_clause(family_patterns):
    """Build SQL exclusion clause and params for sub-adviser dedup."""
    exclusions = _get_subadviser_exclusions(family_patterns)
    if not exclusions:
        return "", []
    excl_ph = ','.join(['?'] * len(exclusions))
    excl_patterns = ['%' + e + '%' for e in exclusions]
    clause = f"""
        AND fh.series_id NOT IN (
            SELECT DISTINCT nam.series_id FROM ncen_adviser_map nam
            WHERE EXISTS (SELECT 1 FROM UNNEST([{excl_ph}]) x(p) WHERE nam.adviser_name ILIKE x.p)
        )"""
    return clause, excl_patterns


def get_nport_children_batch(inst_parent_names, ticker, quarter, con, limit=5):
    """Batched version of get_nport_children (ARCH-2A.1).

    Resolves top-N N-PORT fund children for multiple institution parents in
    a single SQL round-trip. Eliminates the N+1 pattern in query1 / Register
    and portfolio_context / Conviction. Measured hotspot before this fix:
    286ms / 45% of the portfolio_context HTTP budget (2026-04-12).

    Returns: dict parent_name -> list of child row dicts (same shape as
    get_nport_children). Parents with no matching family patterns or no
    N-PORT rows for this ticker/quarter are simply absent from the dict.
    """
    if not inst_parent_names:
        return {}
    unique_parents = list(dict.fromkeys(inst_parent_names))

    parent_patterns = []
    parent_exclusions = []
    for pname in unique_parents:
        patterns = match_nport_family(pname)
        if not patterns:
            continue
        for p in patterns:
            parent_patterns.append((pname, '%' + p + '%'))
        for e in _get_subadviser_exclusions(patterns):
            parent_exclusions.append((pname, '%' + e + '%'))
    if not parent_patterns:
        return {}

    float_row = con.execute(
        "SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]
    ).fetchone()
    float_shares = float_row[0] if float_row and float_row[0] else None

    pp_ph = ', '.join(['(?, ?)'] * len(parent_patterns))
    pp_params = [v for row in parent_patterns for v in row]

    if parent_exclusions:
        pe_ph = ', '.join(['(?, ?)'] * len(parent_exclusions))
        pe_params = [v for row in parent_exclusions for v in row]
        excl_cte = f""",
        parent_exclusions AS (
            SELECT * FROM (VALUES {pe_ph}) AS t(parent_name, excl_pattern)
        ),
        excluded_series AS (
            SELECT DISTINCT pe.parent_name, nam.series_id
            FROM parent_exclusions pe
            JOIN ncen_adviser_map nam ON nam.adviser_name ILIKE pe.excl_pattern
        )"""
        excl_where = """
          AND NOT EXISTS (
              SELECT 1 FROM excluded_series es
              WHERE es.parent_name = pp.parent_name
                AND es.series_id = fh.series_id
          )"""
    else:
        excl_cte = ""
        excl_where = ""
        pe_params = []

    try:
        df = con.execute(f"""
            WITH parent_patterns AS (
                SELECT * FROM (VALUES {pp_ph}) AS t(parent_name, pattern)
            ){excl_cte}
            SELECT
                pp.parent_name,
                fh.fund_name,
                MAX(fh.market_value_usd) AS value,
                MAX(fh.shares_or_principal) AS shares,
                MAX(fh.pct_of_nav) AS pct_of_nav,
                fh.series_id,
                MAX(fu.total_net_assets) / 1e6 AS aum_mm
            FROM parent_patterns pp
            JOIN fund_holdings_v2 fh ON fh.family_name ILIKE pp.pattern
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE fh.ticker = ?
              AND fh.quarter = ?
              {excl_where}
            GROUP BY pp.parent_name, fh.fund_name, fh.series_id
            QUALIFY row_number() OVER (
                PARTITION BY pp.parent_name
                ORDER BY value DESC NULLS LAST
            ) <= {int(limit)}
        """, pp_params + pe_params + [ticker, quarter]).fetchdf()
    except Exception as e:
        logger.error("[get_nport_children_batch] %s", e, exc_info=True)
        return {}

    result = {}
    for r in df_to_records(df):
        pname = r.get('parent_name')
        if not pname:
            continue
        shares = r.get('shares') or 0
        pct_float = round(shares * 100.0 / float_shares, 2) if float_shares and shares else None
        aum_val = r.get('aum_mm')
        aum = int(aum_val) if aum_val and aum_val > 0 else None
        pct_aum = round(float(r.get('pct_of_nav')), 2) if r.get('pct_of_nav') else None
        result.setdefault(pname, []).append({
            'institution': r.get('fund_name'),
            'value_live': r.get('value'),
            'shares': shares,
            'pct_float': pct_float,
            'aum': aum,
            'pct_aum': pct_aum,
            'source': 'N-PORT',
        })
    return result


def get_nport_children(inst_parent_name, ticker, quarter, con, limit=5):
    """Get top fund series from fund_holdings for a parent institution.

    Returns list of child row dicts or None if no N-PORT data.
    """
    patterns = match_nport_family(inst_parent_name)
    if not patterns:
        return None
    try:
        like_patterns = ['%' + p + '%' for p in patterns]
        ph = ','.join(['?'] * len(like_patterns))
        excl_clause, excl_params = _build_excl_clause(patterns)
        # Get float_shares for pct_of_float calculation
        float_row = con.execute(
            "SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        float_shares = float_row[0] if float_row and float_row[0] else None

        df = con.execute(f"""
            SELECT
                fh.fund_name,
                MAX(fh.market_value_usd) as value,
                MAX(fh.shares_or_principal) as shares,
                MAX(fh.pct_of_nav) as pct_of_nav,
                fh.series_id,
                MAX(fu.total_net_assets) / 1e6 as aum_mm
            FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE EXISTS (SELECT 1 FROM UNNEST([{ph}]) t(p) WHERE fh.family_name ILIKE t.p)
              AND fh.ticker = ?
              AND fh.quarter = ?
              {excl_clause}
            GROUP BY fh.fund_name, fh.series_id
            ORDER BY value DESC NULLS LAST
            LIMIT {int(limit)}
        """, like_patterns + [ticker, quarter] + excl_params).fetchdf()
        rows = df_to_records(df)
        if not rows:
            return None
        result = []
        for r in rows:
            shares = r.get('shares') or 0
            pct_float = round(shares * 100.0 / float_shares, 2) if float_shares and shares else None
            aum_val = r.get('aum_mm')
            aum = int(aum_val) if aum_val and aum_val > 0 else None
            # % of AUM/NAV: use pct_of_nav from N-PORT (position value as % of fund NAV)
            pct_aum = round(float(r.get('pct_of_nav')), 2) if r.get('pct_of_nav') else None
            result.append({'institution': r.get('fund_name'), 'value_live': r.get('value'),
                           'shares': shares, 'pct_float': pct_float,
                           'aum': aum, 'pct_aum': pct_aum, 'source': 'N-PORT'})
        return result
    except Exception as e:
        logger.error("[get_nport_children] %s", e, exc_info=True)
        return None



def get_nport_children_q2(inst_parent_name, ticker, con, limit=5):
    """Get N-PORT fund series with Q1 vs Q4 share comparison for Holder Changes."""
    patterns = match_nport_family(inst_parent_name)
    if not patterns:
        return None
    try:
        like_patterns = ['%' + p + '%' for p in patterns]
        ph = ','.join(['?'] * len(like_patterns))
        excl_clause, excl_params = _build_excl_clause(patterns)
        df = con.execute(f"""
            SELECT
                fund_name,
                MAX(CASE WHEN quarter = '{FQ}' THEN shares_or_principal END) as q1_shares,
                MAX(CASE WHEN quarter = '{LQ}' THEN shares_or_principal END) as q4_shares,
                MAX(CASE WHEN quarter = '{LQ}' THEN market_value_usd END) as q4_value,
                series_id
            FROM fund_holdings_v2 fh
            WHERE EXISTS (SELECT 1 FROM UNNEST([{ph}]) t(p) WHERE family_name ILIKE t.p)
              AND ticker = ?
              AND quarter IN ('{FQ}', '{LQ}')
              {excl_clause}
            GROUP BY fund_name, series_id
            HAVING MAX(CASE WHEN quarter = '{LQ}' THEN shares_or_principal END) IS NOT NULL
                OR MAX(CASE WHEN quarter = '{FQ}' THEN shares_or_principal END) IS NOT NULL
            ORDER BY q4_value DESC NULLS LAST
            LIMIT {int(limit)}
        """, like_patterns + [ticker] + excl_params).fetchdf()
        rows = df_to_records(df)
        if not rows:
            return None
        result = []
        for r in rows:
            q1 = r.get('q1_shares') or 0
            q4 = r.get('q4_shares') or 0
            chg = q4 - q1
            pct = round(chg / q1 * 100, 1) if q1 > 0 else None
            result.append({
                'fund_name': r.get('fund_name'),
                'q1_shares': r.get('q1_shares'),
                'q4_shares': r.get('q4_shares'),
                'change_shares': chg if chg != 0 else None,
                'change_pct': pct,
                'source': 'N-PORT',
            })
        return result
    except Exception as e:
        logger.error("[get_nport_children_q2] %s", e, exc_info=True)
        return None



def get_13f_children(inst_parent_name, ticker, cusip, quarter, con, limit=5, rollup_type='economic_control_v1'):
    """Get 13F filing entity child rows as fallback."""
    rn = _rollup_col(rollup_type)
    df = con.execute(f"""
        SELECT
            h.fund_name as institution,
            COALESCE(h.manager_type, 'unknown') as type,
            SUM(h.market_value_live) as value_live,
            SUM(h.shares) as shares,
            SUM(h.pct_of_float) as pct_float
        FROM holdings_v2 h
        WHERE h.quarter = '{quarter}'
          AND (h.ticker = ? OR h.cusip = ?)
          AND COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) = ?
        GROUP BY h.fund_name, type
        ORDER BY value_live DESC NULLS LAST
        LIMIT {int(limit)}
    """, [ticker, cusip, inst_parent_name or '']).fetchdf()
    rows = df_to_records(df)
    return [{'institution': r.get('institution'), 'value_live': r.get('value_live'),
             'shares': r.get('shares'), 'pct_float': r.get('pct_float'),
             'type': r.get('type'), 'source': '13F'} for r in rows]



def get_nport_children_ncen(inst_parent_name, ticker, quarter, con, limit=5):
    """Get N-PORT fund series via N-CEN adviser mapping (direct join, no fuzzy).

    Uses ncen_adviser_map to find all series managed/subadvised by an adviser
    whose name fuzzy-matches the 13F parent institution.
    Returns list of child row dicts or None.
    """
    if not has_table('ncen_adviser_map'):
        return None

    try:
        # Find adviser name in ncen_adviser_map matching this parent
        like_param = '%' + (inst_parent_name or '') + '%'
        df = con.execute("""
            SELECT DISTINCT
                fh.fund_name,
                SUM(fh.market_value_usd) as value,
                SUM(fh.shares_or_principal) as shares,
                AVG(fh.pct_of_nav) as pct_of_nav,
                fh.series_id,
                MAX(nam.role) as role
            FROM ncen_adviser_map nam
            JOIN fund_holdings_v2 fh ON nam.series_id = fh.series_id
            WHERE nam.adviser_name ILIKE ?
              AND fh.ticker = ?
              AND fh.quarter = ?
            GROUP BY fh.fund_name, fh.series_id
            ORDER BY value DESC NULLS LAST
            LIMIT ?
        """, [like_param, ticker, quarter, limit]).fetchdf()

        rows = df_to_records(df)
        if not rows:
            return None

        return [{'institution': r.get('fund_name'), 'value_live': r.get('value'),
                 'shares': r.get('shares'), 'pct_float': r.get('pct_of_nav'),
                 'source': f"N-PORT ({r.get('role', 'adviser')})"} for r in rows]
    except Exception as e:
        logger.error("[get_nport_children_ncen] %s", e, exc_info=True)
        return None



def get_children(inst_parent_name, ticker, cusip, quarter, con,
                  limit=5, parent_shares=None):
    """Get child rows: N-CEN → N-PORT fuzzy → 13F entity fallback.

    Only uses N-PORT children if they cover at least 10% of the parent's
    13F-reported shares. This prevents showing tiny niche funds when the
    bulk of the position is in large index funds not in our N-PORT data.

    Returns (children_list, source_type) where source_type is 'N-PORT' or '13F'.
    """
    # Try N-CEN direct join first (most accurate for subadvisers)
    ncen_result = get_nport_children_ncen(inst_parent_name, ticker, quarter, con, limit)
    if ncen_result and len(ncen_result) >= 1:
        return ncen_result, 'N-PORT'

    # Fallback to fuzzy family matching
    nport = get_nport_children(inst_parent_name, ticker, quarter, con, limit)
    if nport and len(nport) >= 1:
        # Coverage check: do N-PORT children represent a meaningful fraction?
        nport_shares = sum(c.get('shares') or 0 for c in nport)
        if parent_shares and parent_shares > 0 and nport_shares > 0:
            coverage = nport_shares / parent_shares
            if coverage < 0.10:
                # N-PORT covers less than 10% — misleading, fall back to 13F
                fallback = get_13f_children(inst_parent_name, ticker, cusip, quarter, con, limit)
                return fallback, '13F'
        return nport, 'N-PORT'
    fallback = get_13f_children(inst_parent_name, ticker, cusip, quarter, con, limit)
    return fallback, '13F'



# _clean_val / clean_for_json / df_to_records moved to serializers.py in
# Phase 4 Batch 4-B. Imported (and re-exported) at the top of this module
# so existing handler imports (`from queries import clean_for_json,
# df_to_records`) keep working.


# ---------------------------------------------------------------------------
# Query functions — ported exactly from research.ipynb
# ---------------------------------------------------------------------------


def query1(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Current shareholder register — two-level parent/fund hierarchy.
    Batched: parents + all 13F children fetched in 2 queries total."""
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)

        # Query 1: parents (aggregated by inst_parent_name)
        parents = con.execute(f"""
            WITH by_fund AS (
                SELECT
                    COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as parent_name,
                    h.fund_name,
                    h.cik,
                    COALESCE(h.manager_type, 'unknown') as type,
                    h.market_value_live,
                    h.shares,
                    h.pct_of_float
                FROM holdings_v2 h
                WHERE h.quarter = '{quarter}'
                  AND (h.ticker = ? OR h.cusip = ?)
            )
            SELECT
                parent_name,
                MAX(type) as type,
                SUM(market_value_live) as total_value_live,
                SUM(shares) as total_shares,
                SUM(pct_of_float) as pct_float,
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
                FROM holdings_v2 WHERE quarter = '{quarter}' AND COALESCE({rn}, inst_parent_name) IN ({ph_aum})
                GROUP BY COALESCE({rn}, inst_parent_name)
            """, parent_names).fetchdf()
            for _, r in fallback_df.iterrows():
                pn = r['parent_name']
                if pn not in aum_map and r['val_mm'] and r['val_mm'] > 0:
                    aum_map[pn] = int(r['val_mm'])
        except Exception:  # nosec B110
            pass

        # N-PORT coverage % per parent (from summary_by_parent)
        coverage_map = {}
        try:
            cov_df = con.execute(f"""
                SELECT inst_parent_name, nport_coverage_pct
                FROM summary_by_parent
                WHERE quarter = '{quarter}' AND inst_parent_name IN ({ph_aum})
            """, parent_names).fetchdf()
            coverage_map = {r['inst_parent_name']: r['nport_coverage_pct']
                            for _, r in cov_df.iterrows()
                            if r['nport_coverage_pct'] is not None}
        except Exception:  # nosec B110
            pass

        # Query 2: ALL 13F children for all parents in one pass
        ph = ','.join(['?'] * len(parent_names))
        all_children_df = con.execute(f"""
            SELECT
                COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as parent_name,
                h.fund_name as institution,
                COALESCE(h.manager_type, 'unknown') as type,
                SUM(h.market_value_live) as value_live,
                SUM(h.shares) as shares,
                SUM(h.pct_of_float) as pct_float
            FROM holdings_v2 h
            WHERE h.quarter = '{quarter}'
              AND (h.ticker = ? OR h.cusip = ?)
              AND COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) IN ({ph})
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
                    'pct_float': row['pct_float'],
                    'type': row['type'],
                    'source': '13F entity' if note else '13F',
                    'subadviser_note': note,
                })

        # N-PORT fund series lookup — batched to eliminate N+1 (ARCH-2A.1).
        nport_by_parent = {}
        if has_table('fund_holdings'):
            nport_by_parent = get_nport_children_batch(parent_names, ticker, quarter, con, limit=5)
            for kids in nport_by_parent.values():
                for k in kids:
                    k['type'] = _classify_fund_type(k.get('institution'))

        # Build results — prefer N-PORT children, supplement with 13F entities
        results = []
        for rank, (_, parent) in enumerate(parents.iterrows(), 1):
            pname = parent['parent_name']
            nport_kids = nport_by_parent.get(pname, [])
            f13_kids = children_by_parent.get(pname, [])

            # Merge: N-PORT funds first, then 13F entities not covered by N-PORT
            merged = list(nport_kids)
            nport_names = {c['institution'].lower() for c in nport_kids}
            for c in f13_kids:
                if c['institution'].lower() not in nport_names and c.get('subadviser_note'):
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
                'pct_float': parent['pct_float'],
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
                        'pct_float': c.get('pct_float'),
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
                COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as parent_name,
                SUM(h.market_value_live) as total_value,
                SUM(h.shares) as total_shares,
                SUM(h.pct_of_float) as pct_float
            FROM holdings_v2 h
            WHERE h.quarter = '{quarter}' AND (h.ticker = ? OR h.cusip = ?)
            GROUP BY parent_name
        """, [ticker, cusip]).fetchdf()

        all_totals = {
            'value_live': float(all_totals_df['total_value'].sum()) if len(all_totals_df) else 0,
            'shares': float(all_totals_df['total_shares'].sum()) if len(all_totals_df) else 0,
            'pct_float': float(all_totals_df['pct_float'].sum()) if len(all_totals_df) else 0,
            'count': len(all_totals_df),
        }
        # By-type totals
        type_totals = {}
        for _, trow in all_totals_df.iterrows():
            t = trow['type'] or 'unknown'
            if t not in type_totals:
                type_totals[t] = {'value_live': 0, 'shares': 0, 'pct_float': 0, 'count': 0}
            type_totals[t]['value_live'] += float(trow['total_value'] or 0)
            type_totals[t]['shares'] += float(trow['total_shares'] or 0)
            type_totals[t]['pct_float'] += float(trow['pct_float'] or 0)
            type_totals[t]['count'] += 1

        return {'rows': results, 'all_totals': all_totals, 'type_totals': type_totals}
    finally:
        pass  # connection managed by thread-local cache



def query2(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """4-quarter ownership change (Q1 vs Q4 2025)."""
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        # Top 15 parents by Q4 value
        top_parents = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                   SUM(market_value_live) as parent_val
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND (ticker = ? OR cusip = ?)
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
                WHERE quarter = '{FQ}' AND (ticker = ? OR cusip = ?)
                GROUP BY cik, manager_name, parent_name
            ),
            q4_agg AS (
                SELECT cik, manager_name,
                       COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                       MAX(manager_type) as manager_type,
                       SUM(shares) as q4_shares
                FROM holdings_v2
                WHERE quarter = '{quarter}' AND (ticker = ? OR cusip = ?)
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



def holder_momentum(ticker, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ):
    """Full-year share momentum.
    level='parent': top 25 13F parents with collapsible N-PORT children.
    level='fund': top 25 individual N-PORT funds (flat).
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        qs = QUARTERS
        q_placeholders = ','.join([f"'{q}'" for q in qs])

        # --- Fund-level branch ---
        if level == 'fund':
            # SQL-level filter via fund_universe.is_actively_managed (N21: fixed)
            af = "AND fu.is_actively_managed = true" if active_only else ""
            top_funds = con.execute(f"""
                SELECT fh.fund_name, SUM(fh.market_value_usd) as val
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.quarter = '{quarter}' {af}
                GROUP BY fh.fund_name
                ORDER BY val DESC NULLS LAST LIMIT 25
            """, [ticker]).fetchdf()

            if top_funds.empty:
                return []

            fund_names = top_funds['fund_name'].tolist()
            ph_f = ','.join(['?'] * len(fund_names))
            fund_df = con.execute(f"""
                SELECT fund_name, quarter, SUM(shares_or_principal) as shares
                FROM fund_holdings_v2
                WHERE ticker = ?
                  AND quarter IN ({q_placeholders})
                  AND fund_name IN ({ph_f})
                GROUP BY fund_name, quarter
            """, [ticker] + fund_names).fetchdf()

            fund_data = {}
            for _, r in fund_df.iterrows():
                fn = r['fund_name']
                if fn not in fund_data:
                    fund_data[fn] = {}
                fund_data[fn][r['quarter']] = float(r['shares'] or 0)

            results = []
            for rank, (_, frow) in enumerate(top_funds.iterrows(), 1):
                fn = frow['fund_name']
                qshares = fund_data.get(fn, {})
                first_s = next((qshares.get(q) for q in qs if qshares.get(q)), 0)
                last_s = qshares.get(qs[-1], 0)
                chg = last_s - first_s
                chg_pct = round(chg / first_s * 100, 1) if first_s > 0 else None
                # Name-based classification (matches type rendering elsewhere)
                fund_type = _classify_fund_type(fn)
                row = {
                    'rank': rank,
                    'institution': fn,
                    'type': fund_type,
                    'is_parent': False,
                    'child_count': 0,
                    'level': 0,
                    'change': chg,
                    'change_pct': chg_pct,
                }
                for q in qs:
                    row[q] = qshares.get(q)
                results.append(row)
            return results

        # --- Parent-level branch (original logic) ---
        # Top 25 parents by latest quarter value
        top_parents = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                   SUM(market_value_live) as parent_val
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND (ticker = ? OR cusip = ?)
            GROUP BY parent_name
            ORDER BY parent_val DESC NULLS LAST
            LIMIT 25
        """, [ticker, cusip]).fetchdf()['parent_name'].tolist()

        if not top_parents:
            return []

        # Shares per quarter per parent
        ph = ','.join(['?'] * len(top_parents))
        parent_df = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                   quarter,
                   SUM(shares) as shares,
                   MAX(manager_type) as type
            FROM holdings_v2
            WHERE (ticker = ? OR cusip = ?)
              AND quarter IN ({q_placeholders})
              AND COALESCE({rn}, inst_parent_name, manager_name) IN ({ph})
            GROUP BY parent_name, quarter
        """, [ticker, cusip] + top_parents).fetchdf()

        # Build parent → {quarter: shares} map
        parent_data = {}
        parent_types = {}
        for _, r in parent_df.iterrows():
            pn = r['parent_name']
            if pn not in parent_data:
                parent_data[pn] = {}
            parent_data[pn][r['quarter']] = float(r['shares'] or 0)
            if r['type'] and r['type'] != 'unknown':
                parent_types[pn] = r['type']

        # For each parent, get N-PORT fund children across all quarters
        # Union of top 5 per quarter → up to ~10 unique funds
        def _get_fund_children(pname):
            patterns = match_nport_family(pname)
            if not patterns:
                return []
            like_patterns = ['%' + p + '%' for p in patterns]
            lph = ','.join(['?'] * len(like_patterns))
            excl_clause, excl_params = _build_excl_clause(patterns)
            try:
                fund_df = con.execute(f"""
                    SELECT fund_name, quarter,
                           MAX(shares_or_principal) as shares,
                           series_id
                    FROM fund_holdings_v2 fh
                    WHERE EXISTS (SELECT 1 FROM UNNEST([{lph}]) t(p) WHERE family_name ILIKE t.p)
                      AND ticker = ?
                      AND quarter IN ({q_placeholders})
                      {excl_clause}
                    GROUP BY fund_name, quarter, series_id
                """, like_patterns + [ticker] + excl_params).fetchdf()
                if fund_df.empty:
                    return []

                # For each quarter, rank funds by shares and take top 5
                top_funds = set()
                for q in qs:
                    qf = fund_df[fund_df['quarter'] == q].nlargest(5, 'shares')
                    top_funds.update(qf['fund_name'].tolist())

                # Cap at 10
                if len(top_funds) > 10:
                    # Keep the ones with highest max shares across any quarter
                    fund_max = fund_df.groupby('fund_name')['shares'].max().to_dict()
                    top_funds = sorted(top_funds, key=lambda f: fund_max.get(f, 0), reverse=True)[:10]
                else:
                    top_funds = list(top_funds)

                # Build fund → {quarter: shares}
                children = []
                for fn in top_funds:
                    frows = fund_df[fund_df['fund_name'] == fn]
                    qmap = {}
                    for _, fr in frows.iterrows():
                        qmap[fr['quarter']] = float(fr['shares'] or 0)
                    children.append({'fund_name': fn, 'quarters': qmap})
                # Sort by latest quarter shares desc
                children.sort(key=lambda c: c['quarters'].get(qs[-1], 0), reverse=True)
                return children
            except Exception:
                return []

        # Build results
        results = []
        for rank, pname in enumerate(top_parents, 1):
            qshares = parent_data.get(pname, {})
            # Change: first available → latest
            first_s = next((qshares.get(q) for q in qs if qshares.get(q)), 0)
            last_s = qshares.get(qs[-1], 0)
            chg = last_s - first_s
            chg_pct = round(chg / first_s * 100, 1) if first_s > 0 else None

            children = _get_fund_children(pname)
            has_kids = len(children) >= 2

            row = {
                'rank': rank,
                'institution': pname,
                'type': parent_types.get(pname, 'unknown'),
                'is_parent': has_kids,
                'child_count': len(children),
                'level': 0,
                'change': chg,
                'change_pct': chg_pct,
            }
            for q in qs:
                row[q] = qshares.get(q)
            results.append(row)

            if has_kids:
                for child in children:
                    cq = child['quarters']
                    c_first = next((cq.get(q) for q in qs if cq.get(q)), 0)
                    c_last = cq.get(qs[-1], 0)
                    c_chg = c_last - c_first
                    c_pct = round(c_chg / c_first * 100, 1) if c_first > 0 else None
                    crow = {
                        'institution': child['fund_name'],
                        'type': None,
                        'is_parent': False,
                        'child_count': 0,
                        'level': 1,
                        'change': c_chg,
                        'change_pct': c_pct,
                    }
                    for q in qs:
                        crow[q] = cq.get(q)
                    results.append(crow)

        return results
    finally:
        pass


def query3(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Active holder market cap analysis."""
    rn = _rollup_col(rollup_type)
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
                    MAX(COALESCE(h.{rn}, h.inst_parent_name, h.manager_name)) as parent_name,
                    MAX(h.manager_type) as manager_type,
                    SUM(h.market_value_live) as position_value,
                    SUM(h.shares) as shares,
                    MAX(h.pct_of_portfolio) as pct_of_portfolio,
                    SUM(h.pct_of_float) as pct_of_float
                FROM holdings_v2 h
                WHERE h.quarter = '{quarter}'
                  AND (h.ticker = ? OR h.cusip = ?)
                  AND h.entity_type IN ('active', 'hedge_fund', 'activist', 'quantitative')
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
                    ) as holdings_below,
                    (
                        SELECT COUNT(*)
                        FROM holdings_v2 h2
                        INNER JOIN market_data m2 ON h2.ticker = m2.ticker
                        WHERE h2.cik = ca.cik AND h2.quarter = '{quarter}'
                          AND h2.security_type_inferred IN ('equity', 'etf')
                          AND m2.market_cap IS NOT NULL AND m2.market_cap > 0
                    ) as total_with_mktcap
                FROM cik_agg ca
            )
            SELECT
                manager_name,
                parent_name,
                position_value,
                pct_of_portfolio,
                pct_of_float,
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
        if parent_names and has_table('fund_holdings') and has_table('fund_universe'):
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
                            WHERE fu.family_name ILIKE ? AND fh.ticker = ? AND fh.quarter = '{quarter}'
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
        coverage_map = {}
        if parent_names:
            try:
                ph_cov = ','.join(['?'] * len(parent_names))
                cov_df = con.execute(f"""
                    SELECT inst_parent_name, nport_coverage_pct
                    FROM summary_by_parent
                    WHERE quarter = '{quarter}' AND inst_parent_name IN ({ph_cov})
                """, parent_names).fetchdf()
                coverage_map = {r['inst_parent_name']: r['nport_coverage_pct']
                                for _, r in cov_df.iterrows()
                                if r['nport_coverage_pct'] is not None}
            except Exception:  # nosec B110
                pass

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
            if has_flows:
                flow = con.execute(f"""
                    SELECT net_shares, pct_change, price_adj_flow, momentum_signal,
                           is_new_entry, is_exit
                    FROM investor_flows
                    WHERE ticker = ? AND inst_parent_name = ?
                      AND quarter_from = '{FQ}' AND quarter_to = '{quarter}'
                """, [ticker, parent]).fetchone()
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
            if has_table('holdings'):
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
                              LIMIT 1
                          )
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
                except Exception:  # nosec B110
                    pass

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
                    'pct_of_float': None,
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
                    'pct_of_float': None,
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
                CASE
                    WHEN entity_type = 'passive' THEN 'Passive (Index)'
                    WHEN entity_type = 'activist' THEN 'Activist'
                    WHEN manager_type IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
                    ELSE 'Other/Unknown'
                END as category,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares,
                SUM(market_value_live) as total_value,
                SUM(pct_of_float) as total_pct_float
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND ticker = ?
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
    rn = _rollup_col(rollup_type)
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
                WHERE ticker = ?
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



def query6(ticker, quarter=LQ):
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
                WHERE subject_ticker = ?
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
                pct_of_float
            FROM holdings_v2
            WHERE ticker = ? AND is_activist = true
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
            FROM holdings_v2 WHERE {meta_where}
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
                SUM(h.pct_of_float) as pct_of_float,
                MAX(m.market_cap) as market_cap
            FROM holdings_v2 h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            LEFT JOIN (
                SELECT cusip, MAX(sector) as sector
                FROM securities WHERE sector IS NOT NULL AND sector != ''
                GROUP BY cusip
            ) s ON h.cusip = s.cusip
            WHERE {where}
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
                WHERE ticker = ? AND quarter = '{quarter}'
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
            )
            SELECT
                s.sector,
                COUNT(DISTINCT h.ticker) as num_stocks,
                SUM(h.market_value_live) as sector_value,
                SUM(h.market_value_live) * 100.0 / SUM(SUM(h.market_value_live)) OVER () as pct_of_total
            FROM holdings_v2 h
            INNER JOIN target_ciks tc ON h.cik = tc.cik
            INNER JOIN securities s ON h.cusip = s.cusip
            WHERE h.quarter = '{quarter}' AND s.sector IS NOT NULL AND s.sector != ''
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
                q4.pct_of_portfolio, q4.pct_of_float
            FROM holdings_v2 q4
            LEFT JOIN holdings_v2 q3 ON q4.cik = q3.cik AND q3.ticker = ? AND q3.quarter = '{PQ}'
            WHERE q4.ticker = ? AND q4.quarter = '{quarter}' AND q3.cik IS NULL
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
            LEFT JOIN holdings_v2 q4 ON q3.cik = q4.cik AND q4.ticker = ? AND q4.quarter = '{quarter}'
            WHERE q3.ticker = ? AND q3.quarter = '{PQ}' AND q4.cik IS NULL
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
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        df = con.execute(f"""
            WITH ranked AS (
                SELECT
                    COALESCE({rn}, inst_parent_name, manager_name) as holder,
                    SUM(pct_of_float) as total_pct_float,
                    SUM(shares) as total_shares,
                    ROW_NUMBER() OVER (ORDER BY SUM(pct_of_float) DESC) as rn
                FROM holdings_v2
                WHERE ticker = ? AND quarter = '{quarter}' AND pct_of_float IS NOT NULL
                GROUP BY holder
            )
            SELECT
                rn as rank,
                holder,
                total_pct_float,
                total_shares,
                SUM(total_pct_float) OVER (ORDER BY rn) as cumulative_pct
            FROM ranked
            ORDER BY rn
            LIMIT 20
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def get_sector_flows(active_only=False, level="parent"):
    """Multi-quarter sector flow analysis — active money flows by GICS sector.

    level: 'parent' uses 13F holdings; 'fund' uses N-PORT fund_holdings.
    active_only: filter to active/hedge/activist (13F only, ignored for N-PORT).
    """
    con = get_db()
    try:
        use_nport = (level == "fund")
        source = "fund_holdings_v2" if use_nport else "holdings_v2"

        quarters = sorted([r[0] for r in con.execute(
            f"SELECT DISTINCT quarter FROM {source} ORDER BY quarter"
        ).fetchall()])
        if len(quarters) < 2:
            return {"periods": [], "sectors": []}

        pairs = [(quarters[i], quarters[i + 1]) for i in range(len(quarters) - 1)]
        active_filter = ("AND c.entity_type IN ('active', 'hedge_fund', 'activist')"
                         if active_only and not use_nport else "")
        active_filter_p = ("AND p.entity_type IN ('active', 'hedge_fund', 'activist')"
                           if active_only and not use_nport else "")
        sector_filter = "AND md.sector NOT IN ('', 'Derivative', 'ETF') AND md.sector IS NOT NULL"

        all_flows = {}

        for q_from, q_to in pairs:
            pk = f"{q_from}_{q_to}"

            if use_nport:
                df = con.execute(f"""
                    WITH f_agg AS (
                        SELECT series_id, ticker, quarter,
                               SUM(shares_or_principal) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM fund_holdings_v2
                        WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY series_id, ticker, quarter
                    ),
                    flows AS (
                        SELECT c.series_id AS eid, c.ticker,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow,
                               CASE WHEN p.series_id IS NULL THEN 'new' ELSE 'change' END AS flow_type
                        FROM f_agg c
                        LEFT JOIN f_agg p ON c.series_id = p.series_id
                            AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                        WHERE c.quarter = '{q_to}'
                        UNION ALL
                        SELECT p.series_id AS eid, p.ticker,
                               -p.market_value_usd AS active_flow, 'exit' AS flow_type
                        FROM f_agg p
                        LEFT JOIN f_agg c ON p.series_id = c.series_id
                            AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                        WHERE p.quarter = '{q_from}' AND c.series_id IS NULL
                    )
                    SELECT md.sector,
                           SUM(f.active_flow) AS net,
                           SUM(CASE WHEN f.active_flow > 0 THEN f.active_flow ELSE 0 END) AS inflow,
                           SUM(CASE WHEN f.active_flow < 0 THEN f.active_flow ELSE 0 END) AS outflow,
                           COUNT(DISTINCT CASE WHEN f.flow_type='new' THEN f.eid||'|'||f.ticker END) AS new_positions,
                           COUNT(DISTINCT CASE WHEN f.flow_type='exit' THEN f.eid||'|'||f.ticker END) AS exits,
                           COUNT(DISTINCT f.eid) AS managers
                    FROM flows f
                    JOIN market_data md ON f.ticker = md.ticker
                    WHERE 1=1 {sector_filter}
                    GROUP BY md.sector
                """).fetchdf()
            else:
                df = con.execute(f"""
                    WITH h_agg AS (
                        SELECT cik, manager_type, ticker, quarter,
                               SUM(shares) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM holdings_v2
                        WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY cik, manager_type, ticker, quarter
                    ),
                    flows AS (
                        SELECT c.cik AS eid, c.ticker,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow,
                               CASE WHEN p.cik IS NULL THEN 'new' ELSE 'change' END AS flow_type
                        FROM h_agg c
                        LEFT JOIN h_agg p ON c.cik = p.cik AND c.ticker = p.ticker
                            AND p.quarter = '{q_from}'
                        WHERE c.quarter = '{q_to}' {active_filter}
                        UNION ALL
                        SELECT p.cik AS eid, p.ticker,
                               -p.market_value_usd AS active_flow, 'exit' AS flow_type
                        FROM h_agg p
                        LEFT JOIN h_agg c ON p.cik = c.cik AND p.ticker = c.ticker
                            AND c.quarter = '{q_to}'
                        WHERE p.quarter = '{q_from}' AND c.cik IS NULL {active_filter_p}
                    )
                    SELECT md.sector,
                           SUM(f.active_flow) AS net,
                           SUM(CASE WHEN f.active_flow > 0 THEN f.active_flow ELSE 0 END) AS inflow,
                           SUM(CASE WHEN f.active_flow < 0 THEN f.active_flow ELSE 0 END) AS outflow,
                           COUNT(DISTINCT CASE WHEN f.flow_type='new' THEN f.eid||'|'||f.ticker END) AS new_positions,
                           COUNT(DISTINCT CASE WHEN f.flow_type='exit' THEN f.eid||'|'||f.ticker END) AS exits,
                           COUNT(DISTINCT f.eid) AS managers
                    FROM flows f
                    JOIN market_data md ON f.ticker = md.ticker
                    WHERE 1=1 {sector_filter}
                    GROUP BY md.sector
                """).fetchdf()

            for row in df.to_dict(orient="records"):
                sector = row["sector"]
                if sector not in all_flows:
                    all_flows[sector] = {}
                all_flows[sector][pk] = {
                    "net": row.get("net"), "inflow": row.get("inflow"),
                    "outflow": row.get("outflow"), "new_positions": row.get("new_positions"),
                    "exits": row.get("exits"), "managers": row.get("managers"),
                }

        periods = [{"label": f"{qf} \u2192 {qt}", "from": qf, "to": qt}
                    for qf, qt in pairs]
        latest_pk = f"{pairs[-1][0]}_{pairs[-1][1]}" if pairs else None

        sectors = []
        for sector, period_data in all_flows.items():
            total_net = sum((v.get("net") or 0) for v in period_data.values())
            latest_net = (period_data.get(latest_pk, {}).get("net") or 0) if latest_pk else 0
            sectors.append({
                "sector": sector,
                "flows": clean_for_json(period_data),
                "total_net": total_net,
                "latest_net": latest_net,
            })

        sectors.sort(key=lambda s: s["total_net"] or 0, reverse=True)
        return {"periods": periods, "sectors": sectors}
    finally:
        pass


def get_sector_flow_movers(q_from, q_to, sector, active_only=False, level="parent", rollup_type='economic_control_v1'):
    """Top 5 net buyers + top 5 net sellers for one sector in one quarter
    transition. Returns summary stats + two lists.

    level: 'parent' groups by inst_parent_name; 'fund' groups by cik/manager_name.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        active_filter = "AND c.entity_type IN ('active', 'hedge_fund', 'activist')" if active_only else ""
        active_filter_p = "AND p.entity_type IN ('active', 'hedge_fund', 'activist')" if active_only else ""

        if level == "fund":
            group_expr = "c.cik || '|' || c.manager_name"
            group_label = "c.manager_name"
            group_expr_p = "p.cik || '|' || p.manager_name"
            group_label_p = "p.manager_name"
        else:
            group_expr = f"COALESCE(c.{rn}, c.inst_parent_name, c.manager_name)"
            group_label = group_expr
            group_expr_p = f"COALESCE(p.{rn}, p.inst_parent_name, p.manager_name)"
            group_label_p = group_expr_p

        df = con.execute(f"""
            WITH h_agg AS (
                SELECT cik, {rn}, inst_parent_name, manager_name, manager_type,
                       ticker, quarter,
                       SUM(shares) AS shares,
                       SUM(market_value_usd) AS market_value_usd
                FROM holdings_v2
                WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                GROUP BY cik, {rn}, inst_parent_name, manager_name, manager_type, ticker, quarter
            ),
            flows AS (
                SELECT {group_label} AS institution,
                       c.ticker,
                       (c.shares - COALESCE(p.shares, 0))
                         * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                FROM h_agg c
                LEFT JOIN h_agg p
                    ON c.cik = p.cik AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                WHERE c.quarter = '{q_to}' {active_filter}

                UNION ALL

                SELECT {group_label_p} AS institution,
                       p.ticker,
                       -p.market_value_usd AS active_flow
                FROM h_agg p
                LEFT JOIN h_agg c
                    ON p.cik = c.cik AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                WHERE p.quarter = '{q_from}' AND c.cik IS NULL {active_filter_p}
            )
            SELECT institution,
                   SUM(active_flow) AS net_flow,
                   COUNT(DISTINCT ticker) AS positions_changed,
                   SUM(CASE WHEN active_flow > 0 THEN active_flow ELSE 0 END) AS buying,
                   SUM(CASE WHEN active_flow < 0 THEN active_flow ELSE 0 END) AS selling
            FROM flows
            GROUP BY institution
            HAVING ABS(SUM(active_flow)) > 0
            ORDER BY net_flow DESC
        """, [sector, sector]).fetchdf()

        records = df_to_records(df)

        # Summary
        total_inflow = sum(r.get("buying") or 0 for r in records)
        total_outflow = sum(r.get("selling") or 0 for r in records)
        total_net = sum(r.get("net_flow") or 0 for r in records)
        new_pos = sum(1 for r in records if (r.get("net_flow") or 0) > 0)
        exits = sum(1 for r in records if (r.get("net_flow") or 0) < 0)

        return {
            "sector": sector,
            "period": {"from": q_from, "to": q_to},
            "summary": {
                "net": total_net,
                "inflow": total_inflow,
                "outflow": total_outflow,
                "buyers": new_pos,
                "sellers": exits,
            },
            "top_buyers": records[:5],
            "top_sellers": list(reversed(records[-5:])) if len(records) > 5 else
                           [r for r in reversed(records) if (r.get("net_flow") or 0) < 0][:5],
        }
    finally:
        pass



def get_sector_flow_detail(sector, active_only=False, level="parent", rank_by="total", rollup_type='economic_control_v1'):
    """Full cross-quarter detail for one sector: inflow/outflow/net per period
    + top 5 buyers and top 5 sellers with per-period breakdown.

    rank_by: 'total' ranks by sum across all periods; 'latest' ranks by the
    last quarter transition only.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        quarters = sorted([r[0] for r in con.execute(
            "SELECT DISTINCT quarter FROM holdings_v2 ORDER BY quarter"
        ).fetchall()])
        if len(quarters) < 2:
            return {"periods": [], "inflows": {}, "outflows": {}, "nets": {},
                    "top_buyers": [], "top_sellers": []}

        pairs = [(quarters[i], quarters[i + 1]) for i in range(len(quarters) - 1)]
        active_filter = "AND c.entity_type IN ('active', 'hedge_fund', 'activist')" if active_only else ""
        active_filter_p = "AND p.entity_type IN ('active', 'hedge_fund', 'activist')" if active_only else ""

        use_nport = (level == "fund")

        # Collect per-institution flows across all periods
        all_inst = {}  # institution -> {period_key: flow}
        inflows = {}
        outflows = {}
        nets = {}

        for q_from, q_to in pairs:
            pk = f"{q_from}_{q_to}"

            if use_nport:
                # N-PORT fund_holdings: each series_id is a separate fund
                df = con.execute(f"""
                    WITH f_agg AS (
                        SELECT series_id, fund_name, family_name, ticker, quarter,
                               SUM(shares_or_principal) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM fund_holdings_v2
                        WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY series_id, fund_name, family_name, ticker, quarter
                    ),
                    flows AS (
                        SELECT c.fund_name AS institution,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                        FROM f_agg c
                        LEFT JOIN f_agg p ON c.series_id = p.series_id AND c.ticker = p.ticker
                                             AND p.quarter = '{q_from}'
                        JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                        WHERE c.quarter = '{q_to}'

                        UNION ALL

                        SELECT p.fund_name AS institution,
                               -p.market_value_usd AS active_flow
                        FROM f_agg p
                        LEFT JOIN f_agg c ON p.series_id = c.series_id AND p.ticker = c.ticker
                                             AND c.quarter = '{q_to}'
                        JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                        WHERE p.quarter = '{q_from}' AND c.series_id IS NULL
                    )
                    SELECT institution,
                           SUM(active_flow) AS net_flow,
                           SUM(CASE WHEN active_flow > 0 THEN active_flow ELSE 0 END) AS buying,
                           SUM(CASE WHEN active_flow < 0 THEN active_flow ELSE 0 END) AS selling
                    FROM flows
                    GROUP BY institution
                """, [sector, sector]).fetchdf()
            else:
                # 13F holdings: group by parent institution
                inst_expr = f"COALESCE(c.{rn}, c.inst_parent_name, c.manager_name)"
                inst_expr_p = f"COALESCE(p.{rn}, p.inst_parent_name, p.manager_name)"
                df = con.execute(f"""
                    WITH h_agg AS (
                        SELECT cik, {rn}, inst_parent_name, manager_name, manager_type,
                               ticker, quarter,
                               SUM(shares) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM holdings_v2
                        WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY cik, {rn}, inst_parent_name, manager_name, manager_type, ticker, quarter
                    ),
                    flows AS (
                        SELECT {inst_expr} AS institution,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                        FROM h_agg c
                        LEFT JOIN h_agg p ON c.cik = p.cik AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                        JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                        WHERE c.quarter = '{q_to}' {active_filter}

                        UNION ALL

                        SELECT {inst_expr_p} AS institution,
                               -p.market_value_usd AS active_flow
                        FROM h_agg p
                        LEFT JOIN h_agg c ON p.cik = c.cik AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                        JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                        WHERE p.quarter = '{q_from}' AND c.cik IS NULL {active_filter_p}
                    )
                    SELECT institution,
                           SUM(active_flow) AS net_flow,
                           SUM(CASE WHEN active_flow > 0 THEN active_flow ELSE 0 END) AS buying,
                           SUM(CASE WHEN active_flow < 0 THEN active_flow ELSE 0 END) AS selling
                    FROM flows
                    GROUP BY institution
                """, [sector, sector]).fetchdf()

            period_inflow = 0
            period_outflow = 0
            for _, row in df.iterrows():
                inst = row["institution"]
                nf = row["net_flow"] or 0
                buy = row["buying"] or 0
                sell = row["selling"] or 0
                period_inflow += buy
                period_outflow += sell
                if inst not in all_inst:
                    all_inst[inst] = {}
                all_inst[inst][pk] = nf

            inflows[pk] = period_inflow
            outflows[pk] = period_outflow
            nets[pk] = period_inflow + period_outflow

        # Compute totals
        inflows["total"] = sum(inflows.values())
        outflows["total"] = sum(outflows.values())
        nets["total"] = inflows["total"] + outflows["total"]

        # Rank institutions
        period_keys = [f"{qf}_{qt}" for qf, qt in pairs]
        latest_pk = period_keys[-1] if period_keys else None
        inst_totals = []
        for inst, flows_dict in all_inst.items():
            total = sum(flows_dict.get(pk, 0) for pk in period_keys)
            latest = flows_dict.get(latest_pk, 0) if latest_pk else 0
            inst_totals.append({
                "institution": inst, "flows": flows_dict,
                "total": total, "latest": latest,
            })

        sort_key = "latest" if rank_by == "latest" else "total"
        inst_totals.sort(key=lambda x: x[sort_key], reverse=True)

        top_buyers = inst_totals[:5]
        sellers_pool = [x for x in inst_totals if x[sort_key] < 0]
        sellers_pool.sort(key=lambda x: x[sort_key])
        top_sellers = sellers_pool[:5]

        periods = [{"label": f"{qf} \u2192 {qt}", "from": qf, "to": qt}
                    for qf, qt in pairs]

        return clean_for_json({
            "sector": sector,
            "periods": periods,
            "inflows": inflows,
            "outflows": outflows,
            "nets": nets,
            "top_buyers": top_buyers,
            "top_sellers": top_sellers,
        })
    finally:
        pass


def query14(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Manager AUM vs position size — consolidated with conviction data."""
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as manager_name,
                h.manager_type,
                h.is_activist,
                m.aum_total / 1e9 as manager_aum_bn,
                SUM(h.market_value_live) / 1e6 as position_mm,
                MAX(h.pct_of_portfolio) as pct_of_portfolio,
                SUM(h.pct_of_float) as pct_of_float,
                SUM(h.shares) as shares
            FROM holdings_v2 h
            LEFT JOIN managers m ON h.cik = m.cik
            WHERE h.ticker = ? AND h.quarter = '{quarter}'
            GROUP BY COALESCE(h.{rn}, h.inst_parent_name, h.manager_name), h.manager_type, h.is_activist, m.aum_total
            HAVING SUM(h.market_value_live) > 0
            ORDER BY SUM(h.market_value_live) DESC NULLS LAST
            LIMIT 25
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass



def query15(ticker=None, quarter=LQ):
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
                COUNT(CASE WHEN pct_of_float IS NOT NULL THEN 1 END) as with_float_pct
            FROM holdings_v2 WHERE quarter = '{quarter}'
        """).fetchone()
        total = coverage[0] or 1
        stats['coverage'] = {
            'total': total,
            'ticker_pct': round(coverage[1] / total * 100, 1),
            'manager_type_pct': round(coverage[2] / total * 100, 1),
            'live_value_pct': round(coverage[3] / total * 100, 1),
            'float_pct_pct': round(coverage[4] / total * 100, 1),
        }
        return clean_for_json([stats])
    finally:
        pass  # connection managed by thread-local cache


def query16(ticker, quarter=LQ):
    """Fund-level register — top 25 individual funds by position value."""
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        # Get float_shares for % of float calculation
        float_row = con.execute(
            "SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        float_shares = float_row[0] if float_row and float_row[0] else None

        df = con.execute(f"""
            SELECT
                fh.fund_name,
                fh.family_name,
                fh.series_id,
                SUM(fh.market_value_usd) as value,
                SUM(fh.shares_or_principal) as shares,
                AVG(fh.pct_of_nav) as pct_of_nav,
                MAX(fu.total_net_assets) / 1e6 as aum_mm
            FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE fh.ticker = ? AND fh.quarter = '{quarter}'
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
            pct_float = round(shares * 100.0 / float_shares, 2) if float_shares and shares else None
            fund_type = _classify_fund_type(fund_name)

            results.append({
                'rank': rank,
                'institution': fund_name,
                'family': r['family_name'] or '',
                'value_live': value,
                'shares': shares,
                'pct_float': pct_float,
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
                AVG(fh.pct_of_nav) as pct_of_nav
            FROM fund_holdings_v2 fh
            WHERE fh.ticker = ? AND fh.quarter = '{quarter}'
            GROUP BY fh.fund_name, fh.series_id
        """, [ticker]).fetchdf()

        all_totals = {
            'value_live': float(all_df['total_value'].sum()) if len(all_df) else 0,
            'shares': float(all_df['total_shares'].sum()) if len(all_df) else 0,
            'pct_float': round(float(all_df['total_shares'].sum()) * 100.0 / float_shares, 2) if float_shares and len(all_df) else 0,
            'count': len(all_df),
        }

        # By-type totals
        type_totals = {}
        for _, trow in all_df.iterrows():
            t = _classify_fund_type(trow['fund_name'])
            if t not in type_totals:
                type_totals[t] = {'value_live': 0, 'shares': 0, 'pct_float': 0, 'count': 0}
            type_totals[t]['value_live'] += float(trow['total_value'] or 0)
            s = float(trow['total_shares'] or 0)
            type_totals[t]['shares'] += s
            type_totals[t]['count'] += 1
        # Compute pct_float per type
        for t in type_totals:
            if float_shares and type_totals[t]['shares']:
                type_totals[t]['pct_float'] = round(type_totals[t]['shares'] * 100.0 / float_shares, 2)

        return {'rows': results, 'all_totals': all_totals, 'type_totals': type_totals}
    finally:
        pass


# ---------------------------------------------------------------------------
# New query functions — Ownership Trend, Cohort Analysis, Flow Analysis
# ---------------------------------------------------------------------------


def ownership_trend_summary(ticker, level='parent', active_only=False, rollup_type='economic_control_v1'):
    """Aggregated institutional ownership trend across all quarters.
    level: 'parent' (13F) or 'fund' (N-PORT).
    active_only: fund level — only include funds classified as active.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        float_row = con.execute(
            "SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        float_shares = float_row[0] if float_row and float_row[0] else None

        if level == 'fund':
            # Fund-level: aggregate from fund_holdings joined to fund_universe.
            # Uses fund_universe.is_actively_managed (N21: now reliable after
            # classification backfill). Active/passive split at SQL level.
            af = "AND fu.is_actively_managed = true" if active_only else ""
            df = con.execute(f"""
                SELECT fh.quarter,
                       SUM(fh.shares_or_principal) as total_inst_shares,
                       SUM(fh.market_value_usd) as total_inst_value,
                       COUNT(DISTINCT fh.fund_name) as holder_count,
                       SUM(CASE WHEN fu.is_actively_managed = true
                                THEN fh.market_value_usd ELSE 0 END) as active_value,
                       SUM(CASE WHEN fu.is_actively_managed = false
                                THEN fh.market_value_usd ELSE 0 END) as passive_value
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.market_value_usd > 0 {af}
                GROUP BY fh.quarter ORDER BY fh.quarter
            """, [ticker]).fetchdf()
        else:
            df = con.execute(f"""
                SELECT quarter,
                       SUM(shares) as total_inst_shares,
                       SUM(market_value_usd) as total_inst_value,
                       COUNT(DISTINCT COALESCE({rn}, inst_parent_name, manager_name)) as holder_count,
                       SUM(CASE WHEN entity_type NOT IN ('passive') THEN market_value_usd ELSE 0 END) as active_value,
                       SUM(CASE WHEN entity_type = 'passive' THEN market_value_usd ELSE 0 END) as passive_value
                FROM holdings_v2 WHERE ticker = ? GROUP BY quarter ORDER BY quarter
            """, [ticker]).fetchdf()

        rows = df_to_records(df)
        prev_shares = None
        prev_holders = None
        for row in rows:
            total_shares = row.get('total_inst_shares') or 0
            total_value = row.get('total_inst_value') or 0
            holders = row.get('holder_count') or 0
            row['pct_float'] = round(total_shares / float_shares * 100, 2) if float_shares and float_shares > 0 else None
            active_val = row.get('active_value') or 0
            passive_val = row.get('passive_value') or 0
            row['active_pct'] = round(active_val / total_value * 100, 1) if total_value > 0 else 0
            row['passive_pct'] = round(passive_val / total_value * 100, 1) if total_value > 0 else 0
            if prev_shares is not None:
                net_change = total_shares - prev_shares
                row['net_shares_change'] = net_change
                row['net_holder_change'] = holders - prev_holders if prev_holders is not None else None
                pct_change = net_change / prev_shares if prev_shares > 0 else 0
                row['signal'] = '\u2191' if pct_change > 0.005 else ('\u2193' if pct_change < -0.005 else '\u2192')
            else:
                row['net_shares_change'] = None
                row['net_holder_change'] = None
                row['signal'] = None
            prev_shares = total_shares
            prev_holders = holders

        summary = {}
        if len(rows) >= 2:
            first, last = rows[0], rows[-1]
            fs = first.get('total_inst_shares') or 0
            ls = last.get('total_inst_shares') or 0
            total_added = ls - fs
            total_flow = (last.get('total_inst_value') or 0) - (first.get('total_inst_value') or 0)
            net_new = (last.get('holder_count') or 0) - (first.get('holder_count') or 0)
            pct = total_added / fs if fs > 0 else 0
            trend = '\u2191 Accumulating' if pct > 0.005 else ('\u2193 Distributing' if pct < -0.005 else '\u2192 Stable')
            summary = {'trend': trend, 'total_shares_added': total_added, 'total_dollar_flow': total_flow, 'net_new_holders': net_new}

        return {'quarters': rows, 'summary': summary, 'level': level}
    finally:
        pass  # connection managed by thread-local cache



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
        pct_float = round(s / total_inst_shares * 100, 2) if total_inst_shares > 0 else 0
        # Net deltas
        if delta_src is not None:
            delta_s = sum(((src[i].get('shares') or 0) - (delta_src.get(i, {}).get('shares') or 0)) for i in investors)
            delta_v = sum(((src[i].get('value') or 0) - (delta_src.get(i, {}).get('value') or 0)) for i in investors)
        else:
            delta_s = s   # new entries: entire position is delta
            delta_v = v
        return {'holders': c, 'shares': s, 'value': v,
                'avg_position': round(v / c, 2) if c > 0 else 0,
                'pct_float_moved': pct_float,
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
                    'pct_float_moved': round(s_now / total_inst_shares * 100, 4) if total_inst_shares > 0 else 0,
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
         'pct_float_moved': ret_pct, 'delta_shares': ret_delta_s, 'delta_value': ret_delta_v,
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
        'pct_float_moved': 100.0, 'delta_shares': total_delta_s, 'delta_value': total_delta_v,
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
    """Cohort retention analysis: compare two quarters.
    level: 'parent' (13F institutional) or 'fund' (N-PORT fund series).
    active_only: when level='fund', exclude passive/index funds.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        fq = from_quarter or PQ
        lq = quarter

        if level == 'fund':
            # Fund-level from fund_holdings, filter via fund_universe.is_actively_managed
            join_clause = "LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id"
            active_filter = "AND fu.is_actively_managed = true" if active_only else ""
            q1_df = con.execute(f"""
                SELECT fh.fund_name as investor,
                       SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
                FROM fund_holdings_v2 fh {join_clause}
                WHERE fh.ticker = ? AND fh.quarter = '{fq}' {active_filter}
                GROUP BY fh.fund_name
            """, [ticker]).fetchdf()
            q4_df = con.execute(f"""
                SELECT fh.fund_name as investor,
                       SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
                FROM fund_holdings_v2 fh {join_clause}
                WHERE fh.ticker = ? AND fh.quarter = '{lq}' {active_filter}
                GROUP BY fh.fund_name
            """, [ticker]).fetchdf()
        else:
            # Parent-level from holdings (13F)
            q1_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name, manager_name) as investor,
                       SUM(shares) as shares, SUM(market_value_usd) as value
                FROM holdings_v2 WHERE ticker = ? AND quarter = '{fq}' GROUP BY investor
            """, [ticker]).fetchdf()
            q4_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name, manager_name) as investor,
                       SUM(shares) as shares, SUM(market_value_usd) as value
                FROM holdings_v2 WHERE ticker = ? AND quarter = '{lq}' GROUP BY investor
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
                    SELECT COALESCE({rn}, inst_parent_name, manager_name) as investor,
                           SUM(shares) as shares
                    FROM holdings_v2
                    WHERE ticker = ? AND quarter = '{q_from}'
                      AND entity_type NOT IN ('passive', 'unknown')
                    GROUP BY investor
                """, [ticker]).fetchdf()
                to_df = con.execute(f"""
                    SELECT COALESCE({rn}, inst_parent_name, manager_name) as investor,
                           SUM(shares) as shares
                    FROM holdings_v2
                    WHERE ticker = ? AND quarter = '{q_to}'
                      AND entity_type NOT IN ('passive', 'unknown')
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
            except Exception:  # nosec B110
                pass
        summary['econ_retention_trend'] = econ_retention_trend

        return {'summary': summary, 'detail': detail}
    finally:
        pass  # connection managed by thread-local cache



def _compute_flows_live(ticker, quarter_from, quarter_to, con, level='parent', active_only=False, rollup_type='economic_control_v1'):
    """Compute buyer/seller/new/exit flows live from holdings or fund_holdings.
    Returns (buyers, sellers, new_entries, exits) lists.
    """
    rn = _rollup_col(rollup_type)
    # Get float_shares once for fund-level % float calculation
    float_row = con.execute(
        "SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]
    ).fetchone()
    float_shares = float(float_row[0]) if float_row and float_row[0] else None

    if level == 'fund':
        # Filter via fund_universe.is_actively_managed
        join_clause = "LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id"
        af = "AND fu.is_actively_managed = true" if active_only else ""
        from_df = con.execute(f"""
            SELECT fh.fund_name as entity, SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
            FROM fund_holdings_v2 fh {join_clause}
            WHERE fh.ticker = ? AND fh.quarter = '{quarter_from}' {af} GROUP BY fh.fund_name
        """, [ticker]).fetchdf()
        to_df = con.execute(f"""
            SELECT fh.fund_name as entity, SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
            FROM fund_holdings_v2 fh {join_clause}
            WHERE fh.ticker = ? AND fh.quarter = '{quarter_to}' {af} GROUP BY fh.fund_name
        """, [ticker]).fetchdf()
    else:
        from_df = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as entity,
                   MAX(manager_type) as manager_type,
                   SUM(shares) as shares, SUM(market_value_usd) as value,
                   SUM(pct_of_float) as pct_of_float
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter_from}' GROUP BY entity
        """, [ticker]).fetchdf()
        to_df = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as entity,
                   MAX(manager_type) as manager_type,
                   SUM(shares) as shares, SUM(market_value_usd) as value,
                   SUM(pct_of_float) as pct_of_float
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter_to}' GROUP BY entity
        """, [ticker]).fetchdf()

    from_map = {r['entity']: r for _, r in from_df.iterrows()}
    to_map = {r['entity']: r for _, r in to_df.iterrows()}
    from_set, to_set = set(from_map), set(to_map)

    def _pct_float(shares):
        """Compute % of float from shares, fall back to None if no float data."""
        if float_shares and shares:
            return round(shares / float_shares * 100, 3)
        return None

    def _get_pf(entity_row, fallback_shares):
        """Safely extract pct_of_float from a pandas row, fall back to computed."""
        raw = entity_row.get('pct_of_float') if entity_row is not None else None
        try:
            if raw is not None and not (isinstance(raw, float) and raw != raw):
                return float(raw)
        except (TypeError, ValueError):
            pass
        return _pct_float(fallback_shares)

    rows = []
    # Retained: compare shares
    for entity in from_set & to_set:
        fs = float(from_map[entity].get('shares') or 0)
        ts = float(to_map[entity].get('shares') or 0)
        fv = float(from_map[entity].get('value') or 0)
        tv = float(to_map[entity].get('value') or 0)
        net_s = ts - fs
        mt = from_map[entity].get('manager_type') if level == 'parent' else None
        pf = _get_pf(to_map[entity], ts) if level == 'parent' else _pct_float(ts)
        rows.append({
            'inst_parent_name': entity, 'manager_type': mt or '',
            'from_shares': fs, 'to_shares': ts, 'net_shares': net_s,
            'from_value': fv, 'to_value': tv, 'net_value': tv - fv,
            'pct_change': (net_s / fs) if fs > 0 else None,
            'pct_float': pf,
            'is_new_entry': False, 'is_exit': False,
        })
    # New entries
    for entity in to_set - from_set:
        ts = float(to_map[entity].get('shares') or 0)
        tv = float(to_map[entity].get('value') or 0)
        mt = to_map[entity].get('manager_type') if level == 'parent' else None
        pf = _get_pf(to_map[entity], ts) if level == 'parent' else _pct_float(ts)
        rows.append({
            'inst_parent_name': entity, 'manager_type': mt or '',
            'from_shares': 0, 'to_shares': ts, 'net_shares': ts,
            'from_value': 0, 'to_value': tv, 'net_value': tv,
            'pct_change': None, 'pct_float': pf,
            'is_new_entry': True, 'is_exit': False,
        })
    # Exits
    for entity in from_set - to_set:
        fs = float(from_map[entity].get('shares') or 0)
        fv = float(from_map[entity].get('value') or 0)
        mt = from_map[entity].get('manager_type') if level == 'parent' else None
        pf = _get_pf(from_map[entity], fs) if level == 'parent' else _pct_float(fs)
        rows.append({
            'inst_parent_name': entity, 'manager_type': mt or '',
            'from_shares': fs, 'to_shares': 0, 'net_shares': -fs,
            'from_value': fv, 'to_value': 0, 'net_value': -fv,
            'pct_change': -1.0, 'pct_float': pf,
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
    rn = _rollup_col(rollup_type)
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
        cnt = con.execute(
            "SELECT COUNT(*) FROM investor_flows WHERE ticker = ? AND quarter_from = ?",
            [ticker, quarter_from]
        ).fetchone()[0]
        if cnt == 0:
            return {'error': 'No flow data for this ticker/period.',
                    'buyers': [], 'sellers': [], 'new_entries': [], 'exits': [],
                    'charts': {'flow_intensity': [], 'churn': []}}

        # Implied prices
        ip = con.execute("""
            SELECT SUM(market_value_usd) / NULLIF(SUM(shares), 0)
            FROM holdings_v2 WHERE ticker = ? AND quarter = ? AND shares > 0
        """, [ticker, quarter_from]).fetchone()
        implied_from = ip[0] if ip and ip[0] else None
        ip2 = con.execute(f"""
            SELECT SUM(market_value_usd) / NULLIF(SUM(shares), 0)
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter}' AND shares > 0
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
                WHERE ticker = ? AND quarter_from = ?
                ORDER BY net_shares DESC NULLS LAST
            """, [ticker, quarter_from]).fetchdf()
            rows = df_to_records(df)
            # Compute net_value and pct_of_float using float_shares
            fr = con.execute("SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]).fetchone()
            flt = float(fr[0]) if fr and fr[0] else None
            for r in rows:
                r['net_value'] = (r.get('to_value') or 0) - (r.get('from_value') or 0)
                ts = r.get('to_shares') or 0
                fs = r.get('from_shares') or 0
                ns = abs(r.get('net_shares') or 0)
                # pct_float = the relevant change as % of float:
                #   buyers/sellers: net change / float (how much they added/reduced)
                #   new entries: to_shares / float (entire new position)
                #   exits: from_shares / float (entire prior position)
                if r.get('is_new_entry'):
                    change_shares = ts
                elif r.get('is_exit'):
                    change_shares = fs
                else:
                    change_shares = ns
                r['pct_float'] = round(change_shares / flt * 100, 3) if flt and change_shares else None
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
        except Exception:  # nosec B110
            pass

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
                        COALESCE(h.manager_type, 'unknown') as mtype,
                        SUM(CASE WHEN h.quarter = '{qf}' THEN h.shares ELSE 0 END) as from_s,
                        SUM(CASE WHEN h.quarter = '{qt}' THEN h.shares ELSE 0 END) as to_s,
                        SUM(CASE WHEN h.quarter = '{qf}' THEN h.market_value_usd ELSE 0 END) as from_v,
                        SUM(CASE WHEN h.quarter = '{qt}' THEN h.market_value_usd ELSE 0 END) as to_v
                    FROM (
                        SELECT COALESCE({rn}, inst_parent_name, manager_name) as inv, manager_type, quarter,
                               SUM(shares) as shares, SUM(market_value_usd) as market_value_usd
                        FROM holdings_v2 WHERE ticker = ? AND quarter IN ('{qf}', '{qt}')
                        GROUP BY inv, manager_type, quarter
                    ) h
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
            except Exception:  # nosec B110
                pass

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
        except Exception:  # nosec B110
            pass
        subj_spx_weight = mkt_weights.get(subj_gics_sector, None)

        # Top 25 parents or funds by latest quarter value (same as Register)
        if level == 'fund':
            active_filter = "AND fu.is_actively_managed = true" if active_only else ""
            top_holders_df = con.execute(f"""
                SELECT fh.fund_name as holder, SUM(fh.market_value_usd) as val,
                       MAX(fu.is_actively_managed) as is_active
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.quarter = '{quarter}' {active_filter}
                GROUP BY fh.fund_name
                ORDER BY val DESC NULLS LAST LIMIT 25
            """, [ticker]).fetchdf()
        else:
            top_holders_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name, manager_name) as holder,
                       SUM(market_value_live) as val,
                       MAX(manager_type) as mtype
                FROM holdings_v2
                WHERE (ticker = ? OR cusip = ?) AND quarter = '{quarter}'
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
                    GROUP BY fh.fund_name, fh.ticker, m.sector, m.industry
                """, list(all_child_funds)).fetchdf()

                # Also need is_actively_managed per fund for child type
                fund_meta_df = con.execute(f"""
                    SELECT DISTINCT fh.fund_name, MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active
                    FROM fund_holdings_v2 fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.fund_name IN ({ph_funds}) AND fh.quarter = '{quarter}'
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


def short_interest_analysis(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Comprehensive short interest analysis for a ticker.
    Combines N-PORT fund-level shorts, FINRA daily volume, and long/short cross-reference.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        result = {}

        # 1. N-PORT short positions by quarter (trend)
        # Get live price early for value recomputation across sections
        price_row = con.execute(
            "SELECT price_live FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        live_price = float(price_row[0]) if price_row and price_row[0] else None

        nport_trend = []
        try:
            # Dedupe by (fund_name, quarter) first to avoid double-counting series
            trend_df = con.execute("""
                SELECT quarter,
                       COUNT(*) as fund_count,
                       SUM(short_shares) as short_shares,
                       SUM(short_value) as short_value
                FROM (
                    SELECT quarter, fund_name,
                           SUM(ABS(shares_or_principal)) as short_shares,
                           SUM(ABS(market_value_usd)) as short_value
                    FROM fund_holdings_v2
                    WHERE ticker = ? AND shares_or_principal < 0
                    GROUP BY quarter, fund_name
                )
                GROUP BY quarter ORDER BY quarter
            """, [ticker]).fetchdf()
            nport_trend = df_to_records(trend_df)
            # Recompute value from shares × live_price for consistency across quarters
            if live_price:
                for r in nport_trend:
                    shares = r.get('short_shares') or 0
                    if shares > 0:
                        r['short_value'] = shares * live_price
        except Exception:  # nosec B110
            pass
        result['nport_trend'] = nport_trend

        # 2. N-PORT short positions detail (latest quarter) — dedupe by fund_name
        nport_detail = []
        try:
            detail_df = con.execute(f"""
                SELECT fund_name,
                       MAX(family_name) as family_name,
                       SUM(ABS(shares_or_principal)) as short_shares,
                       SUM(ABS(market_value_usd)) as short_value,
                       MAX(quarter) as quarter,
                       MAX(fund_aum_mm) as fund_aum_mm,
                       MAX(is_active) as is_active
                FROM (
                    SELECT fh.fund_name, fh.family_name,
                           fh.shares_or_principal, fh.market_value_usd,
                           fh.quarter, fh.series_id,
                           fu.total_net_assets / 1e6 as fund_aum_mm,
                           CAST(fu.is_actively_managed AS INTEGER) as is_active
                    FROM fund_holdings_v2 fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.ticker = ? AND fh.shares_or_principal < 0
                      AND fh.quarter = '{quarter}'
                )
                GROUP BY fund_name
                ORDER BY short_shares DESC
            """, [ticker]).fetchdf()
            nport_detail = df_to_records(detail_df)
            for r in nport_detail:
                shares = r.get('short_shares') or 0
                val = r.get('short_value') or 0
                # Data quality guard: if implied per-share price is off by >3x from live
                # (or if value is zero/missing), recompute as shares × live_price.
                # This fixes corrupted N-PORT filings where market_value_usd is mangled.
                if live_price and shares > 0:
                    implied = val / shares if val > 0 else 0
                    if implied == 0 or implied > live_price * 3 or implied < live_price / 3:
                        r['short_value'] = shares * live_price
                        r['value_recomputed'] = True
                aum = r.get('fund_aum_mm')
                val2 = r.get('short_value')
                r['pct_of_nav'] = round(val2 / (aum * 1e6) * 100, 3) if aum and aum > 0 and val2 else None
                # Name-based classification for consistent type display
                r['type'] = _classify_fund_type(r.get('fund_name') or '')
        except Exception:  # nosec B110
            pass
        result['nport_detail'] = nport_detail

        # 3. N-PORT short positions history per fund — dedupe by (fund_name, quarter)
        nport_by_fund = []
        try:
            fund_hist = con.execute("""
                SELECT fh.fund_name, fh.quarter,
                       SUM(ABS(fh.shares_or_principal)) as short_shares,
                       MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.shares_or_principal < 0
                GROUP BY fh.fund_name, fh.quarter
                ORDER BY fh.fund_name, fh.quarter
            """, [ticker]).fetchdf()
            # Pivot: fund → {quarter: shares, type}
            funds_seen = {}
            for _, r in fund_hist.iterrows():
                fn = r['fund_name']
                if fn not in funds_seen:
                    funds_seen[fn] = {'fund_name': fn, 'type': _classify_fund_type(fn)}
                funds_seen[fn][r['quarter']] = float(r['short_shares'])
            nport_by_fund = list(funds_seen.values())
            nport_by_fund.sort(key=lambda x: x.get(quarter, 0), reverse=True)
        except Exception:  # nosec B110
            pass
        result['nport_by_fund'] = nport_by_fund

        # 4. FINRA daily short volume (all available days)
        short_volume = []
        try:
            sv_df = con.execute("""
                SELECT report_date, short_volume, total_volume, short_pct
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date
            """, [ticker]).fetchdf()
            short_volume = df_to_records(sv_df)
        except Exception:  # nosec B110
            pass
        result['short_volume'] = short_volume

        # 5. Long/short cross-reference — institutions both long and short
        cross_ref = []
        try:
            # Long from 13F
            long_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent,
                       SUM(shares) as long_shares, SUM(market_value_live) as long_value,
                       MAX(manager_type) as manager_type
                FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter}'
                GROUP BY parent
            """, [ticker]).fetchdf()
            long_map = {r['parent']: r for _, r in long_df.iterrows()}

            # Short from N-PORT — aggregate per family (dedupe series)
            short_df = con.execute(f"""
                SELECT family_name,
                       SUM(short_shares) as short_shares,
                       SUM(short_value) as short_value
                FROM (
                    SELECT family_name, fund_name,
                           SUM(ABS(shares_or_principal)) as short_shares,
                           SUM(ABS(market_value_usd)) as short_value
                    FROM fund_holdings_v2
                    WHERE ticker = ? AND shares_or_principal < 0 AND quarter = '{quarter}'
                    GROUP BY family_name, fund_name
                )
                GROUP BY family_name
            """, [ticker]).fetchdf()

            # Accumulate shorts per parent (dedupe by institution name)
            parent_shorts = {}  # parent -> {short_shares, short_value}
            for _, s in short_df.iterrows():
                fam = s['family_name'] or ''
                # Try to match to a long parent
                for parent, lrow in long_map.items():
                    parent_lower = parent.lower()
                    fam_words = fam.lower().split()[:2]
                    if any(w in parent_lower for w in fam_words if len(w) > 3):
                        if parent not in parent_shorts:
                            parent_shorts[parent] = {'short_shares': 0, 'short_value': 0}
                        parent_shorts[parent]['short_shares'] += float(s['short_shares'] or 0)
                        parent_shorts[parent]['short_value'] += float(s['short_value'] or 0)
                        break

            for parent, shorts in parent_shorts.items():
                lrow = long_map[parent]
                ls = float(lrow['long_shares'] or 0)
                lv = float(lrow['long_value'] or 0)
                ss = shorts['short_shares']
                sv = shorts['short_value']
                # Recompute short value if implied price is way off from live
                if live_price and ss > 0:
                    implied = sv / ss if sv > 0 else 0
                    if implied == 0 or implied > live_price * 3 or implied < live_price / 3:
                        sv = ss * live_price
                net_pct = round((ls - ss) / ls * 100, 1) if ls > 0 else 0
                cross_ref.append({
                    'institution': parent,
                    'type': lrow.get('manager_type') or 'unknown',
                    'long_shares': ls, 'long_value': lv,
                    'short_shares': ss, 'short_value': sv,
                    'net_exposure_pct': net_pct,
                })
            cross_ref.sort(key=lambda x: x['short_shares'], reverse=True)
        except Exception:  # nosec B110
            pass
        result['cross_ref'] = cross_ref

        # 7. Short-only funds (N-PORT shorts without matching 13F long parent)
        short_only = []
        try:
            sof_df = con.execute(f"""
                SELECT fund_name,
                       MAX(family_name) as family_name,
                       SUM(short_shares) as short_shares,
                       SUM(short_value) as short_value,
                       MAX(fund_aum_mm) as fund_aum_mm,
                       MAX(is_active) as is_active
                FROM (
                    SELECT fh.fund_name, fh.family_name, fh.series_id,
                           SUM(ABS(fh.shares_or_principal)) as short_shares,
                           SUM(ABS(fh.market_value_usd)) as short_value,
                           MAX(fu.total_net_assets) / 1e6 as fund_aum_mm,
                           MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active
                    FROM fund_holdings_v2 fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.ticker = ? AND fh.shares_or_principal < 0 AND fh.quarter = '{quarter}'
                    GROUP BY fh.fund_name, fh.family_name, fh.series_id
                )
                GROUP BY fund_name
                ORDER BY short_value DESC
            """, [ticker]).fetchdf()
            # Exclude funds whose family matched a long parent in cross_ref
            matched_families = set()
            for c in cross_ref:
                matched_families.add(c['institution'].lower())
            for _, r in sof_df.iterrows():
                fam = (r['family_name'] or '').lower()
                is_matched = False
                for m in matched_families:
                    if any(w in m for w in fam.split()[:2] if len(w) > 3):
                        is_matched = True
                        break
                if not is_matched:
                    ss = float(r['short_shares'] or 0)
                    sv = float(r['short_value'] or 0)
                    # Recompute if implied price is way off
                    if live_price and ss > 0:
                        implied = sv / ss if sv > 0 else 0
                        if implied == 0 or implied > live_price * 3 or implied < live_price / 3:
                            sv = ss * live_price
                    short_only.append({
                        'fund_name': r['fund_name'],
                        'family_name': r['family_name'],
                        'type': _classify_fund_type(r['fund_name']),
                        'short_shares': ss,
                        'short_value': sv,
                        'fund_aum_mm': float(r['fund_aum_mm'] or 0) if r['fund_aum_mm'] else None,
                    })
        except Exception:  # nosec B110
            pass
        result['short_only_funds'] = short_only

        # 8. Summary card data
        total_short_shares = sum(r.get(quarter, 0) for r in nport_by_fund)
        total_short_funds = len([r for r in nport_by_fund if r.get(quarter, 0) > 0])
        avg_short_vol = sum(r.get('short_pct', 0) for r in short_volume[-20:]) / max(len(short_volume[-20:]), 1) if short_volume else 0
        result['summary'] = {
            'short_funds': total_short_funds,
            'short_shares': total_short_shares,
            'avg_short_vol_pct': round(avg_short_vol, 1),
            'cross_ref_count': len(cross_ref),
            'quarters_available': [q.get('quarter') for q in nport_trend],
        }

        return clean_for_json(result)
    finally:
        pass


def get_short_long_comparison(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Find managers who are long (13F) AND short (N-PORT) the same ticker."""
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        result = {'ticker': ticker, 'long_short_managers': [], 'short_only_funds': []}

        if not _has_table('fund_holdings_v2'):
            return result

        # Managers with 13F long positions
        longs = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as manager,
                   SUM(shares) as long_shares,
                   SUM(market_value_usd) as long_value,
                   manager_type
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}' AND shares > 0
            GROUP BY manager, manager_type
        """, [ticker]).fetchdf()

        # N-PORT short positions (negative shares = short)
        shorts = con.execute("""
            SELECT fh.fund_name,
                   nam.adviser_name,
                   ABS(fh.shares_or_principal) as short_shares,
                   ABS(fh.market_value_usd) as short_value,
                   fh.quarter
            FROM fund_holdings_v2 fh
            LEFT JOIN ncen_adviser_map nam ON fh.series_id = nam.series_id
            WHERE fh.ticker = ? AND fh.shares_or_principal < 0
              AND fh.asset_category IN ('EC', 'EP')
            ORDER BY ABS(fh.shares_or_principal) DESC
        """, [ticker]).fetchdf()

        if shorts.empty:
            return result

        # Match short fund advisers to long 13F parents
        long_managers = set(longs['manager'].str.upper().tolist()) if not longs.empty else set()

        for _, row in shorts.iterrows():
            adviser = (row.get('adviser_name') or '').upper()
            fund_name = row.get('fund_name', '')
            short_shares = row.get('short_shares', 0)
            short_value = row.get('short_value', 0)

            # Check if adviser matches any long parent
            matched_long = None
            for lm in long_managers:
                # Fuzzy match: check if key words overlap
                adviser_words = set(adviser.split())
                lm_words = set(lm.split())
                if adviser_words & lm_words - {'INC', 'LLC', 'LP', 'CORP', 'GROUP', 'CO', 'THE', 'OF', 'AND', '&'}:
                    matched_long = lm
                    break

            if matched_long:
                long_row = longs[longs['manager'].str.upper() == matched_long].iloc[0]
                result['long_short_managers'].append({
                    'manager': matched_long,
                    'fund_name': fund_name,
                    'long_shares': int(long_row['long_shares']),
                    'long_value': float(long_row['long_value']),
                    'short_shares': int(short_shares),
                    'short_value': float(short_value),
                    'net_shares': int(long_row['long_shares']) - int(short_shares),
                    'manager_type': long_row.get('manager_type'),
                })
            else:
                result['short_only_funds'].append({
                    'fund_name': fund_name,
                    'adviser': row.get('adviser_name'),
                    'short_shares': int(short_shares),
                    'short_value': float(short_value),
                })

        return clean_for_json(result)
    finally:
        pass


# Map query number to function
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
            f"SELECT MODE(issuer_name) FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter}'",
            [ticker]
        ).fetchone()
        company_name = name_row[0] if name_row else ticker

        # Latest quarter
        q_row = con.execute("""
            SELECT MAX(quarter) FROM holdings_v2 WHERE ticker = ?
        """, [ticker]).fetchone()
        latest_quarter = q_row[0] if q_row else 'N/A'

        # Total institutional holdings
        totals = con.execute(f"""
            SELECT
                SUM(market_value_live) as total_value,
                SUM(pct_of_float) as total_pct_float,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}'
        """, [ticker]).fetchone()

        # Active vs passive split
        split = con.execute(f"""
            SELECT
                SUM(CASE WHEN entity_type = 'passive' THEN market_value_live ELSE 0 END) as passive_value,
                SUM(CASE WHEN entity_type IN ('active','hedge_fund','quantitative','activist')
                    THEN market_value_live ELSE 0 END) as active_value
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}'
        """, [ticker]).fetchone()

        # Full type breakdown for stacked bar
        type_df = con.execute(f"""
            SELECT COALESCE(manager_type, 'unknown') as mtype,
                   SUM(market_value_live) as val
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{quarter}' AND market_value_live IS NOT NULL
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
                SELECT MAX(report_date) FROM fund_holdings_v2 WHERE ticker = ?
            """, [ticker]).fetchone()
            if nd and nd[0]:
                nport_date = str(nd[0])[:10]  # YYYY-MM-DD
        except Exception:  # nosec B110
            pass

        result = {
            'company_name': company_name,
            'ticker': ticker,
            'latest_quarter': latest_quarter,
            'total_value': totals[0],
            'total_pct_float': totals[1],
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
        WHERE ticker IN ({placeholders}) AND quarter = '{quarter}'
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
            GROUP BY investor, h.ticker
        ),
        portfolio_totals AS (
            SELECT
                COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) as investor,
                SUM(h.market_value_live) as total_portfolio
            FROM holdings_v2 h
            WHERE h.quarter = '{quarter}'
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


def get_market_summary(limit=25, quarter=LQ):
    """Top N institutions by total 13F holdings value (market-wide).

    Returns a ranked list with AUM, filer count, and fund count per
    institution. Uses holdings_v2 for AUM (avoids polluted managers.aum_total),
    entity_relationships for filer count, and fund children for fund count.
    """
    con = get_db()
    try:
        # Top institutions by 13F book value
        df = con.execute(f"""
            WITH inst_aum AS (
                SELECT
                    COALESCE(rollup_name, inst_parent_name, manager_name) as institution,
                    SUM(market_value_usd) as total_aum,
                    COUNT(DISTINCT ticker) as num_holdings,
                    COUNT(DISTINCT cik) as num_ciks,
                    MAX(manager_type) as manager_type
                FROM holdings_v2
                WHERE quarter = '{quarter}'
                GROUP BY institution
                ORDER BY total_aum DESC NULLS LAST
                LIMIT ?
            )
            SELECT * FROM inst_aum
        """, [limit]).fetchdf()

        if len(df) == 0:
            return []

        rows = df_to_records(df)

        # Enrich with entity-level filer + fund counts where possible
        for i, r in enumerate(rows, 1):
            r['rank'] = i
            # Look up entity_id for this institution name
            try:
                ent = con.execute("""
                    SELECT ea.entity_id
                    FROM entity_aliases ea
                    WHERE ea.alias_name = ? AND ea.valid_to = '9999-12-31'
                    LIMIT 1
                """, [r['institution']]).fetchone()
                if ent:
                    eid = ent[0]
                    r['entity_id'] = eid
                    # Filer count: children that have a CIK identifier
                    # (actual 13F filing entities, not fund series)
                    fc = con.execute("""
                        SELECT COUNT(DISTINCT er.child_entity_id)
                        FROM entity_relationships er
                        JOIN entity_identifiers ei
                          ON er.child_entity_id = ei.entity_id
                          AND ei.identifier_type = 'cik'
                          AND ei.valid_to = '9999-12-31'
                        WHERE er.parent_entity_id = ? AND er.valid_to = '9999-12-31'
                          AND er.relationship_type != 'sub_adviser'
                    """, [eid]).fetchone()
                    # +1 for the institution itself if it has a CIK (self-filer)
                    self_cik = con.execute("""
                        SELECT COUNT(*) FROM entity_identifiers
                        WHERE entity_id = ? AND identifier_type = 'cik'
                          AND valid_to = '9999-12-31'
                    """, [eid]).fetchone()
                    filer_n = (fc[0] if fc else 0) + (1 if self_cik and self_cik[0] > 0 else 0)
                    r['filer_count'] = max(filer_n, r['num_ciks'])
                    # Fund count: fund_sponsor children
                    fnc = con.execute("""
                        SELECT COUNT(DISTINCT child_entity_id)
                        FROM entity_relationships
                        WHERE parent_entity_id = ? AND valid_to = '9999-12-31'
                          AND relationship_type = 'fund_sponsor'
                    """, [eid]).fetchone()
                    r['fund_count'] = fnc[0] if fnc else 0
                else:
                    r['entity_id'] = None
                    r['filer_count'] = r['num_ciks']
                    r['fund_count'] = 0
            except Exception:  # nosec B110
                r['entity_id'] = None
                r['filer_count'] = r['num_ciks']
                r['fund_count'] = 0

            # N-PORT coverage from summary_by_parent
            try:
                cov = con.execute(f"""
                    SELECT nport_coverage_pct
                    FROM summary_by_parent
                    WHERE inst_parent_name = ? AND quarter = '{quarter}'
                """, [r['institution']]).fetchone()
                r['nport_coverage_pct'] = cov[0] if cov and cov[0] is not None else None
            except Exception:  # nosec B110
                r['nport_coverage_pct'] = None

        return clean_for_json(rows)
    finally:
        pass  # connection managed by thread-local cache


# ---------------------------------------------------------------------------
# Peer Rotation — per-ticker substitution analysis within sector
# ---------------------------------------------------------------------------

def get_peer_rotation(ticker, active_only=False, level="parent", rollup_type='economic_control_v1', quarter=LQ):
    """Peer rotation analysis: how institutional money rotates between a
    subject ticker and its sector/industry peers across quarters.

    Returns subject vs sector flows, substitution peers (industry + broader
    sector), top 5 sector movers, and top 10 entity rotation stories.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        use_nport = (level == "fund")
        source = "fund_holdings_v2" if use_nport else "holdings_v2"

        # Step 1: subject context
        ctx = con.execute(
            "SELECT sector, industry FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        if not ctx:
            return {"error": f"No market data for {ticker}"}
        sector, industry = ctx

        # Quarter pairs
        quarters = sorted([r[0] for r in con.execute(
            f"SELECT DISTINCT quarter FROM {source} ORDER BY quarter"
        ).fetchall()])
        if len(quarters) < 2:
            return {"subject": {"ticker": ticker, "sector": sector, "industry": industry},
                    "periods": [], "subject_flows": {}, "sector_flows": {},
                    "subject_pct_of_sector": {}, "industry_substitutions": [],
                    "sector_substitutions": [], "top_sector_movers": [],
                    "entity_stories": []}

        pairs = [(quarters[i], quarters[i + 1]) for i in range(len(quarters) - 1)]
        active_filter = ("AND c.entity_type IN ('active', 'hedge_fund', 'activist')"
                         if active_only and not use_nport else "")
        active_filter_p = ("AND p.entity_type IN ('active', 'hedge_fund', 'activist')"
                           if active_only and not use_nport else "")

        # Accumulators across periods
        subj_flows_by_pk = {}
        sector_flows_by_pk = {}
        # Per-period entity×ticker flows for substitution detection
        all_entity_ticker_flows = {}  # {entity: {ticker: {pk: flow}}}

        for q_from, q_to in pairs:
            pk = f"{q_from}_{q_to}"

            if use_nport:
                df = con.execute(f"""
                    WITH f_agg AS (
                        SELECT series_id, fund_name, ticker, quarter,
                               SUM(shares_or_principal) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM fund_holdings_v2
                        WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY series_id, fund_name, ticker, quarter
                    ),
                    flows AS (
                        SELECT c.fund_name AS entity, c.ticker,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                        FROM f_agg c
                        LEFT JOIN f_agg p ON c.series_id = p.series_id
                            AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                        JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                        WHERE c.quarter = '{q_to}'
                        UNION ALL
                        SELECT p.fund_name AS entity, p.ticker,
                               -p.market_value_usd AS active_flow
                        FROM f_agg p
                        LEFT JOIN f_agg c ON p.series_id = c.series_id
                            AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                        JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                        WHERE p.quarter = '{q_from}' AND c.series_id IS NULL
                    )
                    SELECT entity, ticker, SUM(active_flow) AS flow
                    FROM flows GROUP BY entity, ticker
                """, [sector, sector]).fetchdf()
            else:
                inst_expr = f"COALESCE(c.{rn}, c.inst_parent_name, c.manager_name)"
                inst_expr_p = f"COALESCE(p.{rn}, p.inst_parent_name, p.manager_name)"
                df = con.execute(f"""
                    WITH h_agg AS (
                        SELECT cik, {rn}, inst_parent_name, manager_name, manager_type,
                               ticker, quarter,
                               SUM(shares) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM holdings_v2
                        WHERE ticker IS NOT NULL AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY cik, {rn}, inst_parent_name, manager_name, manager_type, ticker, quarter
                    ),
                    flows AS (
                        SELECT {inst_expr} AS entity, c.ticker,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                        FROM h_agg c
                        LEFT JOIN h_agg p ON c.cik = p.cik AND c.ticker = p.ticker
                            AND p.quarter = '{q_from}'
                        JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                        WHERE c.quarter = '{q_to}' {active_filter}
                        UNION ALL
                        SELECT {inst_expr_p} AS entity, p.ticker,
                               -p.market_value_usd AS active_flow
                        FROM h_agg p
                        LEFT JOIN h_agg c ON p.cik = c.cik AND p.ticker = c.ticker
                            AND c.quarter = '{q_to}'
                        JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                        WHERE p.quarter = '{q_from}' AND c.cik IS NULL {active_filter_p}
                    )
                    SELECT entity, ticker, SUM(active_flow) AS flow
                    FROM flows GROUP BY entity, ticker
                """, [sector, sector]).fetchdf()

            # Accumulate per-entity per-ticker flows
            subj_net = 0
            sector_net = 0
            for _, row in df.iterrows():
                ent = row["entity"]
                tkr = row["ticker"]
                fl = row["flow"]
                if fl is None or (isinstance(fl, float) and math.isnan(fl)):
                    continue
                fl = float(fl)
                sector_net += fl
                if tkr == ticker:
                    subj_net += fl
                if ent not in all_entity_ticker_flows:
                    all_entity_ticker_flows[ent] = {}
                if tkr not in all_entity_ticker_flows[ent]:
                    all_entity_ticker_flows[ent][tkr] = {}
                all_entity_ticker_flows[ent][tkr][pk] = \
                    all_entity_ticker_flows[ent][tkr].get(pk, 0) + fl

            subj_flows_by_pk[pk] = {"net": subj_net}
            sector_flows_by_pk[pk] = {"net": sector_net}

        # Totals
        subj_total = sum(v["net"] for v in subj_flows_by_pk.values())
        sector_total = sum(v["net"] for v in sector_flows_by_pk.values())
        subj_flows_by_pk["total"] = {"net": subj_total}
        sector_flows_by_pk["total"] = {"net": sector_total}

        # Subject % of sector
        pct_of_sector = {}
        for pk in list(subj_flows_by_pk.keys()):
            s_net = sector_flows_by_pk.get(pk, {}).get("net", 0)
            pct_of_sector[pk] = round(subj_flows_by_pk[pk]["net"] / s_net * 100, 1) if s_net else 0

        # --- Substitution detection ---
        # For each entity, compute total subject flow and per-peer contra flows
        # A substitution: entity sells subject & buys peer (or vice versa)
        period_keys = [f"{qf}_{qt}" for qf, qt in pairs]
        peer_subs = {}  # peer_ticker -> {net_peer_flow, contra_subject_flow, num_entities, flows_by_pk, industry}

        for ent, ticker_flows in all_entity_ticker_flows.items():
            subj_total_ent = sum(
                sum(pf.values()) for tkr, pf in ticker_flows.items() if tkr == ticker
            )
            if subj_total_ent == 0:
                continue
            subj_sign = 1 if subj_total_ent > 0 else -1
            for tkr, pf in ticker_flows.items():
                if tkr == ticker:
                    continue
                peer_total = sum(pf.values())
                # Opposite sign = substitution
                if peer_total == 0 or (1 if peer_total > 0 else -1) == subj_sign:
                    continue
                mag = min(abs(peer_total), abs(subj_total_ent))
                if tkr not in peer_subs:
                    peer_subs[tkr] = {"net_peer_flow": 0, "contra_subject_flow": 0,
                                      "num_entities": 0, "magnitude": 0, "flows": {}}
                peer_subs[tkr]["net_peer_flow"] += peer_total
                peer_subs[tkr]["contra_subject_flow"] += subj_total_ent
                peer_subs[tkr]["num_entities"] += 1
                peer_subs[tkr]["magnitude"] += mag
                for pk_key, val in pf.items():
                    peer_subs[tkr]["flows"][pk_key] = peer_subs[tkr]["flows"].get(pk_key, 0) + val

        # Get industry for each peer
        peer_tickers = list(peer_subs.keys())
        peer_industries = {}
        if peer_tickers:
            ph = ','.join(['?'] * len(peer_tickers))
            for row in con.execute(
                f"SELECT ticker, industry FROM market_data WHERE ticker IN ({ph})",
                peer_tickers
            ).fetchall():
                peer_industries[row[0]] = row[1]

        # Build substitution lists
        all_subs = []
        for tkr, data in peer_subs.items():
            ind = peer_industries.get(tkr, "")
            # Direction: if net_peer_flow > 0 and contra < 0, peer is "replacing" subject
            direction = "replacing" if data["net_peer_flow"] > 0 else "replaced_by"
            all_subs.append({
                "ticker": tkr,
                "industry": ind,
                "direction": direction,
                "net_peer_flow": data["net_peer_flow"],
                "contra_subject_flow": data["contra_subject_flow"],
                "num_entities": data["num_entities"],
                "flows": data["flows"],
            })
        all_subs.sort(key=lambda x: peer_subs[x["ticker"]]["magnitude"], reverse=True)

        industry_subs = [s for s in all_subs if s["industry"] == industry][:10]
        sector_subs = [s for s in all_subs if s["industry"] != industry][:10]

        # --- Top 5 sector movers (by ticker) ---
        ticker_totals = {}  # ticker -> {net, inflow, outflow, industry}
        for ent, ticker_flows in all_entity_ticker_flows.items():
            for tkr, pf in ticker_flows.items():
                if tkr not in ticker_totals:
                    ticker_totals[tkr] = {"net": 0, "inflow": 0, "outflow": 0}
                for val in pf.values():
                    ticker_totals[tkr]["net"] += val
                    if val > 0:
                        ticker_totals[tkr]["inflow"] += val
                    else:
                        ticker_totals[tkr]["outflow"] += val

        movers = []
        for tkr, data in ticker_totals.items():
            movers.append({
                "ticker": tkr,
                "industry": peer_industries.get(tkr, industry if tkr == ticker else ""),
                "net_flow": data["net"],
                "inflow": data["inflow"],
                "outflow": data["outflow"],
                "is_subject": tkr == ticker,
            })
        movers.sort(key=lambda x: abs(x["net_flow"]), reverse=True)

        # Ensure subject is in the list even if not top 5
        top_movers = movers[:5]
        subject_in_top = any(m["is_subject"] for m in top_movers)
        if not subject_in_top:
            subj_mover = next((m for m in movers if m["is_subject"]), None)
            if subj_mover:
                top_movers.append(subj_mover)
        for i, m in enumerate(top_movers):
            m["rank"] = i + 1

        # --- Entity rotation stories (top 10) ---
        entity_stories = []
        for ent, ticker_flows in all_entity_ticker_flows.items():
            subj_flow = sum(sum(pf.values()) for tkr, pf in ticker_flows.items() if tkr == ticker)
            sect_flow = sum(sum(pf.values()) for pf in ticker_flows.values())
            if subj_flow == 0 and sect_flow == 0:
                continue
            # Top 3 contra-direction peers
            subj_sign = 1 if subj_flow > 0 else -1 if subj_flow < 0 else 0
            contra = []
            for tkr, pf in ticker_flows.items():
                if tkr == ticker:
                    continue
                pf_total = sum(pf.values())
                if subj_sign != 0 and pf_total != 0 and (1 if pf_total > 0 else -1) != subj_sign:
                    contra.append({"ticker": tkr, "flow": pf_total})
            contra.sort(key=lambda x: abs(x["flow"]), reverse=True)
            entity_stories.append({
                "entity": ent,
                "subject_flow": subj_flow,
                "sector_flow": sect_flow,
                "top_contra_peers": contra[:3],
            })
        entity_stories.sort(key=lambda x: abs(x["subject_flow"]), reverse=True)
        entity_stories = entity_stories[:10]

        periods = [{"label": f"{qf} \u2192 {qt}", "from": qf, "to": qt}
                    for qf, qt in pairs]

        return clean_for_json({
            "subject": {"ticker": ticker, "sector": sector, "industry": industry},
            "periods": periods,
            "subject_flows": subj_flows_by_pk,
            "sector_flows": sector_flows_by_pk,
            "subject_pct_of_sector": pct_of_sector,
            "industry_substitutions": industry_subs,
            "sector_substitutions": sector_subs,
            "top_sector_movers": top_movers,
            "entity_stories": entity_stories,
        })
    finally:
        pass


def get_peer_rotation_detail(ticker, peer, active_only=False, level="parent", rollup_type='economic_control_v1'):
    """Entity-level breakdown for a specific subject+peer substitution pair.

    Shows which entities are driving the rotation between ticker and peer.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        use_nport = (level == "fund")
        source = "fund_holdings_v2" if use_nport else "holdings_v2"

        ctx = con.execute(
            "SELECT sector FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        if not ctx:
            return {"error": f"No market data for {ticker}"}
        sector = ctx[0]

        quarters = sorted([r[0] for r in con.execute(
            f"SELECT DISTINCT quarter FROM {source} ORDER BY quarter"
        ).fetchall()])
        if len(quarters) < 2:
            return {"entities": []}

        pairs = [(quarters[i], quarters[i + 1]) for i in range(len(quarters) - 1)]
        active_filter = ("AND c.entity_type IN ('active', 'hedge_fund', 'activist')"
                         if active_only and not use_nport else "")
        active_filter_p = ("AND p.entity_type IN ('active', 'hedge_fund', 'activist')"
                           if active_only and not use_nport else "")

        # Collect per-entity flows for both subject and peer across periods
        entity_data = {}  # entity -> {subject_flow, peer_flow}
        period_keys = [f"{qf}_{qt}" for qf, qt in pairs]

        target_tickers = [ticker, peer]
        ph = ','.join(['?'] * len(target_tickers))

        for q_from, q_to in pairs:
            pk = f"{q_from}_{q_to}"

            if use_nport:
                df = con.execute(f"""
                    WITH f_agg AS (
                        SELECT series_id, fund_name, ticker, quarter,
                               SUM(shares_or_principal) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM fund_holdings_v2
                        WHERE ticker IN ({ph}) AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY series_id, fund_name, ticker, quarter
                    ),
                    flows AS (
                        SELECT c.fund_name AS entity, c.ticker,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                        FROM f_agg c
                        LEFT JOIN f_agg p ON c.series_id = p.series_id
                            AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                        WHERE c.quarter = '{q_to}'
                        UNION ALL
                        SELECT p.fund_name AS entity, p.ticker,
                               -p.market_value_usd AS active_flow
                        FROM f_agg p
                        LEFT JOIN f_agg c ON p.series_id = c.series_id
                            AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                        WHERE p.quarter = '{q_from}' AND c.series_id IS NULL
                    )
                    SELECT entity, ticker, SUM(active_flow) AS flow
                    FROM flows GROUP BY entity, ticker
                """, target_tickers).fetchdf()
            else:
                inst_expr = f"COALESCE(c.{rn}, c.inst_parent_name, c.manager_name)"
                inst_expr_p = f"COALESCE(p.{rn}, p.inst_parent_name, p.manager_name)"
                df = con.execute(f"""
                    WITH h_agg AS (
                        SELECT cik, {rn}, inst_parent_name, manager_name, manager_type,
                               ticker, quarter,
                               SUM(shares) AS shares,
                               SUM(market_value_usd) AS market_value_usd
                        FROM holdings_v2
                        WHERE ticker IN ({ph}) AND quarter IN ('{q_from}', '{q_to}')
                        GROUP BY cik, {rn}, inst_parent_name, manager_name, manager_type, ticker, quarter
                    ),
                    flows AS (
                        SELECT {inst_expr} AS entity, c.ticker,
                               (c.shares - COALESCE(p.shares, 0))
                                 * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                        FROM h_agg c
                        LEFT JOIN h_agg p ON c.cik = p.cik AND c.ticker = p.ticker
                            AND p.quarter = '{q_from}'
                        WHERE c.quarter = '{q_to}' {active_filter}
                        UNION ALL
                        SELECT {inst_expr_p} AS entity, p.ticker,
                               -p.market_value_usd AS active_flow
                        FROM h_agg p
                        LEFT JOIN h_agg c ON p.cik = c.cik AND p.ticker = c.ticker
                            AND c.quarter = '{q_to}'
                        WHERE p.quarter = '{q_from}' AND c.cik IS NULL {active_filter_p}
                    )
                    SELECT entity, ticker, SUM(active_flow) AS flow
                    FROM flows GROUP BY entity, ticker
                """, target_tickers).fetchdf()

            for _, row in df.iterrows():
                ent = row["entity"]
                tkr = row["ticker"]
                fl = row["flow"]
                if fl is None or (isinstance(fl, float) and math.isnan(fl)):
                    continue
                fl = float(fl)
                if ent not in entity_data:
                    entity_data[ent] = {"subject_flow": 0, "peer_flow": 0}
                if tkr == ticker:
                    entity_data[ent]["subject_flow"] += fl
                elif tkr == peer:
                    entity_data[ent]["peer_flow"] += fl

        # Filter to entities with contra-directional flows (the actual rotation)
        entities = []
        for ent, data in entity_data.items():
            sf = data["subject_flow"]
            pf = data["peer_flow"]
            if sf == 0 and pf == 0:
                continue
            entities.append({
                "entity": ent,
                "subject_flow": sf,
                "peer_flow": pf,
            })
        entities.sort(key=lambda x: abs(x["subject_flow"]) + abs(x["peer_flow"]), reverse=True)

        return clean_for_json({
            "ticker": ticker,
            "peer": peer,
            "entities": entities[:20],
        })
    finally:
        pass


# ---------------------------------------------------------------------------
# Entity Graph tab — search / cascade / graph assembly
# ---------------------------------------------------------------------------
#
# Powers the Entity Graph UI tab. All functions accept `con` as the final
# required parameter and return plain Python dicts/lists ready for
# clean_for_json() in the route handlers. No raw SQL lives in app.py.
#
# Filer model (per spec decision):
#   A "filer" is any descendant entity carrying a `cik` identifier, discovered
#   by walking entity_relationships (excluding sub_adviser edges) from the
#   selected institution. The walk returns entities at the *shallowest* depth
#   at which any CIK-bearing entity is found — so Vanguard (institution itself
#   has a CIK) returns just Vanguard at depth 0, while BlackRock (logical
#   parent with no CIK) returns its 26 CIK-bearing subsidiaries at depth 1.
#   If the walk finds nothing, the institution is returned as a single entry
#   so the filer dropdown is never empty.
#
# AUM computation:
#   - Institution and sub-adviser nodes: SUM(market_value_usd) from holdings_v2
#     across all CIKs in the entity's subtree for the selected quarter
#   - Filer nodes: SUM(market_value_usd) from holdings_v2 where cik = filer.cik
#   - Fund (series) nodes: fund_universe.total_net_assets via series_id
#   - managers.aum_total is NOT used — holdings-based only, always quarterly


def search_entity_parents(q, con):
    """Type-ahead search for rollup parent entities (Institution dropdown).

    Returns entities where entity_id = rollup_entity_id (self-rollup = canonical
    parent). The caller is responsible for ensuring `q` is at least 2 chars.
    """
    like = '%' + q + '%'
    rows = con.execute("""
        SELECT entity_id, display_name, entity_type, classification
        FROM entity_current
        WHERE entity_id = rollup_entity_id
          AND display_name ILIKE ?
        ORDER BY display_name
        LIMIT 20
    """, [like]).fetchall()
    return [
        {
            'entity_id': r[0],
            'display_name': r[1],
            'entity_type': r[2],
            'classification': r[3],
        }
        for r in rows
    ]


def get_entity_by_id(entity_id, con):
    """Fetch a single entity's core row for node-resolve logic."""
    row = con.execute("""
        SELECT entity_id, display_name, entity_type, classification, rollup_entity_id
        FROM entity_current
        WHERE entity_id = ?
    """, [int(entity_id)]).fetchone()
    if not row:
        return None
    return {
        'entity_id': row[0],
        'display_name': row[1],
        'entity_type': row[2],
        'classification': row[3],
        'rollup_entity_id': row[4],
    }


def get_entity_cik(entity_id, con):
    """Return the first current CIK for an entity, or None."""
    row = con.execute("""
        SELECT identifier_value FROM entity_identifiers
        WHERE entity_id = ? AND identifier_type = 'cik'
          AND valid_to = DATE '9999-12-31'
        LIMIT 1
    """, [int(entity_id)]).fetchone()
    return row[0] if row else None


def compute_aum_by_cik(cik, quarter, con):
    """AUM for a single filer-CIK: SUM(holdings_v2.market_value_usd) for quarter."""
    if not cik:
        return None
    row = con.execute("""
        SELECT SUM(market_value_usd)
        FROM holdings_v2
        WHERE cik = ? AND quarter = ?
    """, [cik, quarter]).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def compute_aum_for_subtree(entity_id, quarter, con):
    """AUM across all CIKs in an entity's subtree (non-sub_adviser descendants).

    Used for institution and sub_adviser node totals where the entity is a
    logical parent aggregating multiple filer CIKs. Self is always included.
    """
    row = con.execute("""
        WITH RECURSIVE descendants(entity_id, depth) AS (
            SELECT CAST(? AS BIGINT), 0
            UNION ALL
            SELECT er.child_entity_id, d.depth + 1
            FROM entity_relationships er
            JOIN descendants d ON d.entity_id = er.parent_entity_id
            WHERE er.valid_to = DATE '9999-12-31'
              AND er.relationship_type != 'sub_adviser'
              AND d.depth < 4
        ),
        subtree_ciks AS (
            SELECT DISTINCT ei.identifier_value AS cik
            FROM descendants d
            JOIN entity_identifiers ei
              ON ei.entity_id = d.entity_id
             AND ei.identifier_type = 'cik'
             AND ei.valid_to = DATE '9999-12-31'
        )
        SELECT SUM(h.market_value_usd)
        FROM holdings_v2 h
        WHERE h.cik IN (SELECT cik FROM subtree_ciks)
          AND h.quarter = ?
    """, [int(entity_id), quarter]).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def get_entity_filer_children(entity_id, quarter, con):
    """Return the filer-level children of an institution.

    Walks entity_relationships (excluding sub_adviser edges) down from the
    given entity_id and collects CIK-bearing descendants at the shallowest
    depth where any exist. If the walk is empty (no descendant has a CIK),
    returns the institution itself as a single filer entry so the dropdown
    is never empty. AUM is computed per-row from holdings_v2 for `quarter`.
    """
    rows = con.execute("""
        WITH RECURSIVE descendants(entity_id, depth) AS (
            SELECT CAST(? AS BIGINT), 0
            UNION ALL
            SELECT er.child_entity_id, d.depth + 1
            FROM entity_relationships er
            JOIN descendants d ON d.entity_id = er.parent_entity_id
            WHERE er.valid_to = DATE '9999-12-31'
              AND er.relationship_type != 'sub_adviser'
              AND d.depth < 3
        ),
        cik_entities AS (
            SELECT ec.entity_id,
                   ec.display_name,
                   ei.identifier_value AS cik,
                   MIN(d.depth) AS min_depth
            FROM descendants d
            JOIN entity_current ec ON ec.entity_id = d.entity_id
            JOIN entity_identifiers ei
              ON ei.entity_id = d.entity_id
             AND ei.identifier_type = 'cik'
             AND ei.valid_to = DATE '9999-12-31'
            GROUP BY ec.entity_id, ec.display_name, ei.identifier_value
        ),
        shallowest AS (
            SELECT * FROM cik_entities
            WHERE min_depth = (SELECT MIN(min_depth) FROM cik_entities)
        )
        SELECT s.entity_id,
               s.display_name,
               s.cik,
               (SELECT SUM(market_value_usd) FROM holdings_v2
                 WHERE cik = s.cik AND quarter = ?) AS aum
        FROM shallowest s
        ORDER BY aum DESC NULLS LAST, s.display_name
    """, [int(entity_id), quarter]).fetchall()

    if rows:
        return [
            {
                'entity_id': r[0],
                'display_name': r[1],
                'cik': r[2],
                'aum': float(r[3]) if r[3] is not None else None,
            }
            for r in rows
        ]

    # Fallback: walk produced no CIK-bearing descendant — return institution
    # itself as a single entry so the filer dropdown is never empty.
    ent = get_entity_by_id(entity_id, con)
    if not ent:
        return []
    self_cik = get_entity_cik(entity_id, con)
    return [{
        'entity_id': ent['entity_id'],
        'display_name': ent['display_name'],
        'cik': self_cik,
        'aum': compute_aum_by_cik(self_cik, quarter, con) if self_cik else None,
    }]


def get_entity_fund_children(entity_id, top_n, con):
    """Return fund-series children of a filer/institution, ranked by NAV.

    Returns up to `top_n` rows plus a `total_count` indicator for truncation.
    Fund NAV comes from fund_universe.total_net_assets via the series_id
    identifier (not holdings_v2 — per spec decision, fund nodes use NAV).
    """
    rows = con.execute("""
        SELECT ec.entity_id,
               ec.display_name,
               ei.identifier_value AS series_id,
               fu.total_net_assets AS nav
        FROM entity_relationships er
        JOIN entity_current ec ON ec.entity_id = er.child_entity_id
        LEFT JOIN entity_identifiers ei
          ON ei.entity_id = er.child_entity_id
         AND ei.identifier_type = 'series_id'
         AND ei.valid_to = DATE '9999-12-31'
        LEFT JOIN fund_universe fu ON fu.series_id = ei.identifier_value
        WHERE er.parent_entity_id = ?
          AND er.valid_to = DATE '9999-12-31'
          AND ei.identifier_value IS NOT NULL
        ORDER BY fu.total_net_assets DESC NULLS LAST, ec.display_name
        LIMIT ?
    """, [int(entity_id), int(top_n)]).fetchall()

    # Separate total count for truncation indicator
    total = con.execute("""
        SELECT COUNT(*)
        FROM entity_relationships er
        JOIN entity_identifiers ei
          ON ei.entity_id = er.child_entity_id
         AND ei.identifier_type = 'series_id'
         AND ei.valid_to = DATE '9999-12-31'
        WHERE er.parent_entity_id = ?
          AND er.valid_to = DATE '9999-12-31'
    """, [int(entity_id)]).fetchone()
    total_count = int(total[0]) if total and total[0] is not None else 0

    children = [
        {
            'entity_id': r[0],
            'display_name': r[1],
            'series_id': r[2],
            'nav': float(r[3]) if r[3] is not None else None,
        }
        for r in rows
    ]
    return {'children': children, 'total_count': total_count}


def get_entity_sub_advisers(child_entity_id, quarter, con):
    """Return sub-adviser institutions pointing at the given fund entity.

    An edge (parent=sub_adviser, child=fund) with relationship_type='sub_adviser'
    means the sub_adviser advises the fund. AUM is computed as the subtree sum
    for each sub_adviser entity in the selected quarter.
    """
    rows = con.execute("""
        SELECT DISTINCT ec.entity_id, ec.display_name, ec.classification
        FROM entity_relationships er
        JOIN entity_current ec ON ec.entity_id = er.parent_entity_id
        WHERE er.child_entity_id = ?
          AND er.relationship_type = 'sub_adviser'
          AND er.valid_to = DATE '9999-12-31'
        ORDER BY ec.display_name
    """, [int(child_entity_id)]).fetchall()

    out = []
    for r in rows:
        out.append({
            'entity_id': r[0],
            'display_name': r[1],
            'classification': r[2],
            'aum': compute_aum_for_subtree(r[0], quarter, con),
        })
    return out


def build_entity_graph(entity_id, quarter, depth, include_sub_advisers, top_n_funds, con):
    """Assemble the node/edge/metadata payload for the Entity Graph tab.

    The caller resolves the institution root (walking up to rollup_entity_id
    if the selected entity is not itself a parent). From there we pull filer
    children, then fund children per filer, then optionally sub-advisers per
    fund. Everything is returned as vis.js-compatible dicts.
    """
    # --- 1. Resolve the selected entity and its canonical institution root ---
    ent = get_entity_by_id(entity_id, con)
    if not ent:
        return {'error': f'entity_id {entity_id} not found'}

    root_id = ent['rollup_entity_id'] if ent['rollup_entity_id'] else ent['entity_id']
    root = get_entity_by_id(root_id, con) if root_id != ent['entity_id'] else ent
    if not root:
        root = ent
        root_id = ent['entity_id']

    # --- 2. Filer children (tree walk, fallback to self) ---
    filers = get_entity_filer_children(root_id, quarter, con)

    # --- 3. Funds attach to the institution root, not per-filer ---
    #
    # In this data model, fund-series entities are direct children of the
    # institution (e.g. all 302 BlackRock funds belong to entity_id=2, not to
    # the 26 filer subsidiaries). Filers and funds are sibling subtrees under
    # the institution rather than a strict 3-level cascade.
    nodes = []
    edges = []
    total_funds_by_filer = {}
    shown_funds_by_filer = {}
    truncated = False

    # Institution root node (level 0)
    inst_aum = compute_aum_for_subtree(root_id, quarter, con)
    nodes.append(_eg_node_institution(root, inst_aum, quarter))

    seen_node_ids = {f'inst-{root_id}'}

    # Filer subtree
    for filer in filers:
        filer_node_id = f'filer-{filer["entity_id"]}'
        if filer_node_id not in seen_node_ids:
            nodes.append(_eg_node_filer(filer, quarter))
            seen_node_ids.add(filer_node_id)
        edges.append(_eg_edge(f'inst-{root_id}', filer_node_id, 'fund_sponsor'))

    # Fund subtree (queried once from the institution root)
    fund_res = get_entity_fund_children(root_id, top_n_funds, con)
    funds = fund_res['children']
    total_funds = fund_res['total_count']
    total_funds_by_filer[str(root_id)] = total_funds
    shown_funds_by_filer[str(root_id)] = len(funds)
    if total_funds > len(funds):
        truncated = True

    for fund in funds:
        fund_node_id = f'fund-{fund["entity_id"]}'
        if fund_node_id not in seen_node_ids:
            nodes.append(_eg_node_fund(fund))
            seen_node_ids.add(fund_node_id)
        edges.append(_eg_edge(f'inst-{root_id}', fund_node_id, 'fund_sponsor'))

        # Sub-advisers for this fund
        if include_sub_advisers:
            subs = get_entity_sub_advisers(fund['entity_id'], quarter, con)
            for sub in subs:
                sub_node_id = f'sub-{sub["entity_id"]}'
                if sub_node_id not in seen_node_ids:
                    nodes.append(_eg_node_sub_adviser(sub, quarter))
                    seen_node_ids.add(sub_node_id)
                edges.append(_eg_edge(sub_node_id, fund_node_id, 'sub_adviser'))

    # Truncation indicator node ("Show all N") attached at institution
    if total_funds > len(funds):
        trigger_id = f'expand-{root_id}'
        nodes.append({
            'id': trigger_id,
            'label': f'Show all {total_funds}',
            'title': f'{total_funds - len(funds)} more funds available',
            'level': 2,
            'node_type': 'expand_trigger',
            'filer_entity_id': root_id,
            'color': {'background': '#F5F5F5', 'border': '#999999'},
            'font': {'color': '#666666'},
            'shapeProperties': {'borderDashes': [4, 4]},
        })
        edges.append(_eg_edge(f'inst-{root_id}', trigger_id, 'expand'))

    # Breadcrumb text — only institution level for initial render
    breadcrumb = root['display_name']

    return {
        'nodes': nodes,
        'edges': edges,
        'metadata': {
            'breadcrumb': breadcrumb,
            'root_entity_id': root_id,
            'root_name': root['display_name'],
            'selected_entity_id': int(entity_id),
            'quarter': quarter,
            'truncated': truncated,
            'total_funds_by_filer': total_funds_by_filer,
            'shown_funds_by_filer': shown_funds_by_filer,
            'filer_count': len(filers),
        },
    }


# --- vis.js node/edge builders (private) ---
#
# Palette:
#   institution    Oxford Blue  #002147 on white
#   filer          Glacier Blue #4A90D9
#   fund           Green        #2E7D32
#   sub_adviser    Sandstone    #C9B99A on Oxford Blue text
# Edge colors:
#   fund_sponsor / wholly_owned : Oxford Blue #002147 solid
#   sub_adviser                 : Sandstone  #C9B99A dashed


def _eg_node_institution(ent, aum, quarter):
    label_aum = _eg_fmt_aum_label(aum)
    return {
        'id': f'inst-{ent["entity_id"]}',
        'label': f'{ent["display_name"]}\n{label_aum}',
        'title': f'{ent["display_name"]}<br>13F AUM as of {quarter}: {label_aum}',
        'level': 0,
        'node_type': 'institution',
        'entity_id': ent['entity_id'],
        'display_name': ent['display_name'],
        'classification': ent.get('classification'),
        'aum': aum,
        'aum_type': f'13F AUM as of {quarter}',
        'color': {'background': '#002147', 'border': '#001530'},
        'font': {'color': '#FFFFFF'},
    }


def _eg_node_filer(filer, quarter):
    label_aum = _eg_fmt_aum_label(filer.get('aum'))
    name = filer['display_name']
    return {
        'id': f'filer-{filer["entity_id"]}',
        'label': f'{name}\n{label_aum}',
        'title': f'{name}<br>CIK: {filer.get("cik") or "—"}<br>13F AUM as of {quarter}: {label_aum}',
        'level': 1,
        'node_type': 'filer',
        'entity_id': filer['entity_id'],
        'display_name': name,
        'cik': filer.get('cik'),
        'aum': filer.get('aum'),
        'aum_type': f'13F AUM as of {quarter}',
        'color': {'background': '#4A90D9', 'border': '#2E6EB5'},
        'font': {'color': '#FFFFFF'},
    }


def _eg_node_fund(fund):
    nav = fund.get('nav')
    label_nav = _eg_fmt_aum_label(nav)
    name = fund['display_name']
    return {
        'id': f'fund-{fund["entity_id"]}',
        'label': f'{name}\n{label_nav}',
        'title': f'{name}<br>Series ID: {fund.get("series_id") or "—"}<br>Fund NAV: {label_nav}',
        'level': 2,
        'node_type': 'fund',
        'entity_id': fund['entity_id'],
        'display_name': name,
        'series_id': fund.get('series_id'),
        'aum': nav,
        'aum_type': 'Fund NAV',
        'color': {'background': '#2E7D32', 'border': '#1B5E20'},
        'font': {'color': '#FFFFFF'},
    }


def _eg_node_sub_adviser(sub, quarter):
    label_aum = _eg_fmt_aum_label(sub.get('aum'))
    name = sub['display_name']
    return {
        'id': f'sub-{sub["entity_id"]}',
        'label': f'{name}\n{label_aum}',
        'title': f'{name} (sub-adviser)<br>13F AUM as of {quarter}: {label_aum}',
        'level': 2,
        'node_type': 'sub_adviser',
        'entity_id': sub['entity_id'],
        'display_name': name,
        'classification': sub.get('classification'),
        'aum': sub.get('aum'),
        'aum_type': f'13F AUM as of {quarter}',
        'color': {'background': '#C9B99A', 'border': '#A89776'},
        'font': {'color': '#002147'},
    }


def _eg_edge(from_id, to_id, relationship_type):
    is_sub = relationship_type == 'sub_adviser'
    return {
        'from': from_id,
        'to': to_id,
        'arrows': 'to',
        'dashes': bool(is_sub),
        'color': {'color': '#C9B99A' if is_sub else '#002147'},
        'relationship_type': relationship_type,
    }


def _eg_fmt_aum_label(val):
    """Compact $B/$M string for node labels. Returns '—' when null."""
    if val is None:
        return '\u2014'
    try:
        v = float(val)
    except (TypeError, ValueError):
        return '\u2014'
    if v == 0:
        return '\u2014'
    a = abs(v)
    if a >= 1e12:
        return f'${v / 1e12:.1f}T'
    if a >= 1e9:
        return f'${v / 1e9:.1f}B'
    if a >= 1e6:
        return f'${v / 1e6:.0f}M'
    if a >= 1e3:
        return f'${v / 1e3:.0f}K'
    return f'${v:.0f}'


# ---------------------------------------------------------------------------
# Two Companies Overlap tab
# ---------------------------------------------------------------------------
#
# Pairwise institutional + fund-level holder comparison between a Subject
# ticker and a Second ticker for a given quarter. Returns top-50 holders of
# the Subject (institutional and fund panels) annotated with the Second
# company's position size for each shared holder, plus a meta block carrying
# float shares and issuer names. % of float is computed in Python from
# market_data.float_shares (null-safe — never divides by zero).
#
# The frontend renders this as two side-by-side tables and a small overlap
# summary that's computed entirely client-side from the 50-row arrays
# (no second API call).


def get_two_company_overlap(subject, second, quarter, con):
    """Compare institutional + fund holders of two tickers in a single quarter.

    Returns: {'institutional': [...], 'fund': [...], 'meta': {...}}
    """
    # --- 3a. Float shares for both tickers (null-safe) -------------------
    float_rows = con.execute("""
        SELECT ticker, float_shares
        FROM market_data
        WHERE ticker IN (?, ?)
    """, [subject, second]).fetchall()
    float_map = {row[0]: row[1] for row in float_rows}
    subj_float = float_map.get(subject)
    sec_float = float_map.get(second)
    # Treat 0 the same as null — guards the per-row pct_float division below.
    if not subj_float:
        subj_float = None
    if not sec_float:
        sec_float = None

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
            'subj_pct_float': (subj_shares_f / subj_float * 100.0) if subj_float else None,
            'sec_shares': sec_shares_f,
            'sec_dollars': sec_dollars_f,
            'sec_pct_float': (sec_shares_f / sec_float * 100.0) if sec_float else None,
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
            'subj_pct_float': (subj_shares_f / subj_float * 100.0) if subj_float else None,
            'sec_shares': sec_shares_f,
            'sec_dollars': sec_dollars_f,
            'sec_pct_float': (sec_shares_f / sec_float * 100.0) if sec_float else None,
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
        WHERE ticker IN (?, ?) AND quarter = ?
        GROUP BY ticker
    """, [subject, second, quarter]).fetchall()
    name_map = {row[0]: row[1] for row in name_rows}

    meta = {
        'subject': subject,
        'second': second,
        'quarter': quarter,
        'subj_float': subj_float,
        'sec_float': sec_float,
        'subject_name': name_map.get(subject),
        'second_name': name_map.get(second),
    }

    return clean_for_json({
        'institutional': institutional,
        'fund': fund,
        'meta': meta,
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
    # --- Float shares for percent-of-float computation -------------------
    float_row = con.execute(
        "SELECT float_shares FROM market_data WHERE ticker = ?",
        [subject],
    ).fetchone()
    subj_float = float_row[0] if float_row else None
    if not subj_float:
        subj_float = None

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
            'subj_pct_float': (subj_shares_f / subj_float * 100.0) if subj_float else None,
            'sec_shares': None,
            'sec_dollars': None,
            'sec_pct_float': None,
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
            'subj_pct_float': (subj_shares_f / subj_float * 100.0) if subj_float else None,
            'sec_shares': None,
            'sec_dollars': None,
            'sec_pct_float': None,
            'is_overlap': False,
            'is_active': bool(is_active) if is_active is not None else None,
        })

    # --- Meta block ------------------------------------------------------
    name_row = con.execute("""
        SELECT MODE(issuer_name) as name
        FROM holdings_v2
        WHERE ticker = ? AND quarter = ?
    """, [subject, quarter]).fetchone()
    subject_name = name_row[0] if name_row else None

    meta = {
        'subject': subject,
        'second': None,
        'quarter': quarter,
        'subj_float': subj_float,
        'sec_float': None,
        'subject_name': subject_name,
        'second_name': None,
    }

    return clean_for_json({
        'institutional': institutional,
        'fund': fund,
        'meta': meta,
    })
