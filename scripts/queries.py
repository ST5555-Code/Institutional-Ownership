"""
queries.py — SQL query functions for the 13F ownership research app.

All database queries are defined here. Route handlers in app.py
import and call these functions — no raw SQL in app.py.
"""

import logging
import math
import time as _time
import pandas as pd
import duckdb
from config import QUARTERS, LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER, SUBADVISER_EXCLUSIONS

logger = logging.getLogger(__name__)

# Simple time-based cache for expensive queries
_query_cache = {}
CACHE_TTL = 300  # 5 minutes


def _cached(key, fn):
    """Return cached result if fresh, else compute and cache."""
    now = _time.time()
    if key in _query_cache:
        val, ts = _query_cache[key]
        if now - ts < CACHE_TTL:
            return val
    result = fn()
    _query_cache[key] = (result, now)
    return result

LQ = LATEST_QUARTER
FQ = FIRST_QUARTER
PQ = PREV_QUARTER

# Lazy import to avoid circular dependency with app.py
_get_db = None
_has_table = None


def _setup(get_db_fn, has_table_fn):
    """Called by app.py at startup to inject DB access functions."""
    global _get_db, _has_table
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

# Known filing agent CIKs — these are not real beneficial owners
_FILING_AGENT_CIKS = {
    '0001104659', '0001193125', '0000902664', '0001445546', '0001213900',
    '0001493152', '0001567619', '0001062993', '0001214659', '0001398344',
    '0001072613', '0001178913', '0001193805', '0001532155', '0000929638',
    '0000950142', '0001140361', '0001564590', '0000950170', '0000950103',
    '0001437749', '0001628280',
}

# Name fragments → canonical parent name
_NAME_TO_PARENT = {
    'blackrock': 'BlackRock, Inc.',
    'ishares': 'BlackRock, Inc.',
    'bgfa': 'BlackRock, Inc.',
    'vanguard': 'Vanguard Group Inc',
    'fidelity': 'FMR LLC',
    'fmr': 'FMR LLC',
    'strategic advisers': 'FMR LLC',
    'state street': 'State Street Corp',
    'ssga': 'State Street Corp',
    'jpmorgan': 'JPMorgan Chase & Co',
    'j.p. morgan': 'JPMorgan Chase & Co',
    'goldman sachs': 'Goldman Sachs Group Inc',
    'morgan stanley': 'Morgan Stanley',
    'wellington': 'Wellington Management Group LLP',
    'dimensional': 'Dimensional Fund Advisors LP',
    't. rowe price': 'T. Rowe Price Associates',
    'price t rowe': 'T. Rowe Price Associates',
    'price associates': 'T. Rowe Price Associates',
    'capital research': 'Capital Group Companies Inc',
    'capital world': 'Capital Group Companies Inc',
    'american funds': 'Capital Group Companies Inc',
    'invesco': 'Invesco Ltd.',
    'franklin': 'Franklin Resources Inc',
    'templeton': 'Franklin Resources Inc',
    'northern trust': 'Northern Trust Corp',
    'geode': 'Geode Capital Management, LLC',
    'citadel': 'Citadel Advisors LLC',
    'renaissance': 'Renaissance Technologies LLC',
    'ubs': 'UBS Group AG',
    'pimco': 'PIMCO',
    'schwab': 'Charles Schwab Corp',
    'nuveen': 'Nuveen / TIAA',
}

# Known filing agent entity names
_FILING_AGENT_NAMES = {
    'toppan merrill', 'edgarfilings', 'edgar filing', 'edgar agents',
    'advisor consultant network', 'adviser compliance associates',
    'seward & kissel', 'shartsis friese', 'olshan frome',
}


def resolve_filer_to_parent(filer_name, filer_cik=None):
    """Map a filer_name to its institutional parent.
    Returns the parent name, or the original name if no mapping found."""
    if not filer_name:
        return filer_name

    # Filing agent detection
    if filer_cik and filer_cik in _FILING_AGENT_CIKS:
        # For filing agents, the filer_name might be the actual owner (if resolved)
        # or the agent name itself (if not resolved)
        pass

    name_lower = filer_name.lower()

    # Skip if it's a known filing agent name
    for agent in _FILING_AGENT_NAMES:
        if agent in name_lower:
            return filer_name  # can't resolve further

    # Try parent mapping
    for fragment, parent in _NAME_TO_PARENT.items():
        if fragment in name_lower:
            return parent

    return filer_name


def resolve_filer_names_in_records(records):
    """Post-process query results to apply parent rollup to filer_name."""
    for r in records:
        raw_name = r.get('filer_name', '')
        if raw_name:
            r['filer_name'] = resolve_filer_to_parent(raw_name)
    return records


# ---------------------------------------------------------------------------
# N-PORT family name matching utility
# ---------------------------------------------------------------------------


def get_nport_family_patterns():
    """Map inst_parent_name keywords to N-PORT fund_holdings family_name search patterns."""
    return {
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
                FROM fund_holdings fh
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
        logger.error(f"[get_nport_position] {e}", exc_info=True)
    return None



def get_nport_coverage(ticker, quarter, con):
    """Get overall N-PORT coverage stats for a ticker. Deduplicates by series_id."""
    try:
        result = con.execute("""
            WITH per_fund AS (
                SELECT series_id,
                       MAX(market_value_usd) as market_value_usd
                FROM fund_holdings
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
        logger.error(f"[get_nport_coverage] {e}", exc_info=True)
    return {'nport_total_value': None, 'nport_fund_count': 0}


# ---------------------------------------------------------------------------
# Subadviser notes — explains why some managers show 13F instead of N-PORT
# ---------------------------------------------------------------------------


# Known 13F entities that do not file N-PORT — shown as fund-equivalent with footnotes
_13F_ENTITY_NOTES = {
    'fiam': 'Institutional separate accounts \u2014 pension funds, endowments. No N-PORT.',
    'fidelity management trust': '401(k) and retirement plan trust. No N-PORT.',
    'strategic advisers': 'Multi-manager advisory arm. No N-PORT.',
    'fidelity diversifying': 'Alternative strategies. No N-PORT.',
    'blackrock fund advisors': 'iShares ETF management. Not in N-PORT scrape.',
    'blackrock institutional trust': 'Institutional index/trust products. No N-PORT.',
    'ssga funds management': 'State Street index management. No N-PORT as separate entity.',
    'geode capital': 'Index fund subadviser for Fidelity. Files under Fidelity fund trusts.',
}


def _13f_entity_footnote(entity_name):
    """Return footnote for known 13F entities that don't file N-PORT, or None."""
    if not entity_name:
        return None
    name_lower = entity_name.lower()
    for pattern, note in _13F_ENTITY_NOTES.items():
        if pattern in name_lower:
            return note
    return None


SUBADVISER_NOTES = {
    'wellington': 'Subadviser \u2014 fund-level holdings filed under client fund companies (Hartford, Vanguard Windsor, John Hancock, MassMutual)',
    'dodge': 'Primarily manages separate accounts \u2014 limited registered fund filings',
    'capital group': 'American Funds filed under separate CIKs \u2014 may not match via family name',
    'causeway': 'Subadviser \u2014 files under client fund companies',
    'harris': 'Oakmark funds filed under Harris Associates \u2014 check Oakmark family',
    'southeastern': 'Longleaf Partners \u2014 filed under Southeastern Asset Management',
    'grantham': 'GMO \u2014 primarily institutional separate accounts, limited N-PORT',
    'pzena': 'Primarily separate accounts \u2014 limited registered fund filings',
    'hotchkis': 'Primarily separate accounts \u2014 limited registered fund filings',
    'sanders': 'Primarily separate accounts',
    'numeric': 'Subadviser \u2014 quantitative, files under client fund companies',
    'intech': 'Subadviser \u2014 files under client fund companies',
    'acadian': 'Primarily separate accounts and subadvised mandates',
    'epoch': 'Subadviser \u2014 files under client fund companies',
    'martin currie': 'Subadviser \u2014 files under client fund companies',
    'manning': 'Primarily separate accounts',
}



def get_subadviser_note(inst_parent_name):
    """Return explanatory note for managers that show 13F instead of N-PORT."""
    if not inst_parent_name:
        return None
    name_lower = inst_parent_name.lower()
    for key, note in SUBADVISER_NOTES.items():
        if key in name_lower:
            return note
    return None



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
            FROM fund_holdings fh
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
        logger.error(f"[get_nport_children] {e}", exc_info=True)
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
            FROM fund_holdings fh
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
        logger.error(f"[get_nport_children_q2] {e}", exc_info=True)
        return None



def get_13f_children(inst_parent_name, ticker, cusip, quarter, con, limit=5):
    """Get 13F filing entity child rows as fallback."""
    df = con.execute(f"""
        SELECT
            h.fund_name as institution,
            COALESCE(h.manager_type, 'unknown') as type,
            SUM(h.market_value_live) as value_live,
            SUM(h.shares) as shares,
            SUM(h.pct_of_float) as pct_float
        FROM holdings h
        WHERE h.quarter = '{quarter}'
          AND (h.ticker = ? OR h.cusip = ?)
          AND COALESCE(h.inst_parent_name, h.manager_name) = ?
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
            JOIN fund_holdings fh ON nam.series_id = fh.series_id
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
        logger.error(f"[get_nport_children_ncen] {e}", exc_info=True)
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



def _clean_val(v):
    """Replace NaN/Inf with None; convert numpy types to native Python."""
    if v is None:
        return None
    if isinstance(v, float):
        import math
        if math.isnan(v) or math.isinf(v):
            return None
    # numpy scalar types — convert to native Python
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            import math
            if math.isnan(v) or math.isinf(v):
                return None
            return float(v)
        if isinstance(v, np.bool_):
            return bool(v)
    except ImportError:
        pass
    return v



def clean_for_json(data):
    """Recursively clean NaN/Inf/numpy types from dicts and lists."""
    if isinstance(data, list):
        return [{k: _clean_val(v) for k, v in row.items()} if isinstance(row, dict) else row
                for row in data]
    if isinstance(data, dict):
        return {k: clean_for_json(v) if isinstance(v, (dict, list))
                else _clean_val(v)
                for k, v in data.items()}
    return _clean_val(data)



def df_to_records(df):
    """Convert DataFrame to list of dicts with NaN/Inf replaced by None."""
    records = df.to_dict(orient='records')
    return clean_for_json(records)


# ---------------------------------------------------------------------------
# Query functions — ported exactly from research.ipynb
# ---------------------------------------------------------------------------


def query1(ticker):
    """Current shareholder register — two-level parent/fund hierarchy.
    Batched: parents + all 13F children fetched in 2 queries total."""
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)

        # Query 1: parents (aggregated by inst_parent_name)
        parents = con.execute(f"""
            WITH by_fund AS (
                SELECT
                    COALESCE(h.inst_parent_name, h.manager_name) as parent_name,
                    h.fund_name,
                    h.cik,
                    COALESCE(h.manager_type, 'unknown') as type,
                    h.market_value_live,
                    h.shares,
                    h.pct_of_float
                FROM holdings h
                WHERE h.quarter = '{LQ}'
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
                SELECT inst_parent_name, SUM(market_value_usd) / 1e6 as val_mm
                FROM holdings WHERE quarter = '{LQ}' AND inst_parent_name IN ({ph_aum})
                GROUP BY inst_parent_name
            """, parent_names).fetchdf()
            for _, r in fallback_df.iterrows():
                pn = r['inst_parent_name']
                if pn not in aum_map and r['val_mm'] and r['val_mm'] > 0:
                    aum_map[pn] = int(r['val_mm'])
        except Exception:
            pass

        # Query 2: ALL 13F children for all parents in one pass
        ph = ','.join(['?'] * len(parent_names))
        all_children_df = con.execute(f"""
            SELECT
                COALESCE(h.inst_parent_name, h.manager_name) as parent_name,
                h.fund_name as institution,
                COALESCE(h.manager_type, 'unknown') as type,
                SUM(h.market_value_live) as value_live,
                SUM(h.shares) as shares,
                SUM(h.pct_of_float) as pct_float
            FROM holdings h
            WHERE h.quarter = '{LQ}'
              AND (h.ticker = ? OR h.cusip = ?)
              AND COALESCE(h.inst_parent_name, h.manager_name) IN ({ph})
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

        # N-PORT fund series lookup — uses get_nport_children (deduped + exclusions + %float)
        nport_by_parent = {}
        if has_table('fund_holdings'):
            for pname in parent_names:
                try:
                    kids = get_nport_children(pname, ticker, LQ, con, limit=5)
                    if kids:
                        for k in kids:
                            k['type'] = _classify_fund_type(k.get('institution'))
                        nport_by_parent[pname] = kids
                except Exception:
                    pass

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
                COALESCE(h.inst_parent_name, h.manager_name) as parent_name,
                SUM(h.market_value_live) as total_value,
                SUM(h.shares) as total_shares,
                SUM(h.pct_of_float) as pct_float
            FROM holdings h
            WHERE h.quarter = '{LQ}' AND (h.ticker = ? OR h.cusip = ?)
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



def query2(ticker):
    """4-quarter ownership change (Q1 vs Q4 2025)."""
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        # Top 15 parents by Q4 value
        top_parents = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as parent_name,
                   SUM(market_value_live) as parent_val
            FROM holdings
            WHERE quarter = '{LQ}' AND (ticker = ? OR cusip = ?)
            GROUP BY parent_name
            ORDER BY parent_val DESC NULLS LAST
            LIMIT 25
        """, [ticker, cusip]).fetchdf()['parent_name'].tolist()

        q2 = con.execute(f"""
            WITH q1_agg AS (
                SELECT cik, manager_name,
                       COALESCE(inst_parent_name, manager_name) as parent_name,
                       MAX(manager_type) as manager_type,
                       SUM(shares) as q1_shares
                FROM holdings
                WHERE quarter = '{FQ}' AND (ticker = ? OR cusip = ?)
                GROUP BY cik, manager_name, parent_name
            ),
            q4_agg AS (
                SELECT cik, manager_name,
                       COALESCE(inst_parent_name, manager_name) as parent_name,
                       MAX(manager_type) as manager_type,
                       SUM(shares) as q4_shares
                FROM holdings
                WHERE quarter = '{LQ}' AND (ticker = ? OR cusip = ?)
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



def holder_momentum(ticker):
    """Full-year share momentum for top 25 parents, with fund-level children.
    Returns shares per quarter for each parent and up to 10 N-PORT funds per parent
    (union of top 5 from each quarter to capture movement).
    """
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        qs = QUARTERS  # e.g. ['2025Q1','2025Q2','2025Q3','2025Q4']
        q_placeholders = ','.join([f"'{q}'" for q in qs])

        # Top 25 parents by latest quarter value
        top_parents = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as parent_name,
                   SUM(market_value_live) as parent_val
            FROM holdings
            WHERE quarter = '{LQ}' AND (ticker = ? OR cusip = ?)
            GROUP BY parent_name
            ORDER BY parent_val DESC NULLS LAST
            LIMIT 25
        """, [ticker, cusip]).fetchdf()['parent_name'].tolist()

        if not top_parents:
            return []

        # Shares per quarter per parent
        ph = ','.join(['?'] * len(top_parents))
        parent_df = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as parent_name,
                   quarter,
                   SUM(shares) as shares,
                   MAX(manager_type) as type
            FROM holdings
            WHERE (ticker = ? OR cusip = ?)
              AND quarter IN ({q_placeholders})
              AND COALESCE(inst_parent_name, manager_name) IN ({ph})
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
                    FROM fund_holdings fh
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


def query3(ticker):
    """Active holder market cap analysis."""
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
                    MAX(COALESCE(h.inst_parent_name, h.manager_name)) as parent_name,
                    MAX(h.manager_type) as manager_type,
                    SUM(h.market_value_live) as position_value,
                    SUM(h.shares) as shares,
                    MAX(h.pct_of_portfolio) as pct_of_portfolio,
                    SUM(h.pct_of_float) as pct_of_float
                FROM holdings h
                WHERE h.quarter = '{LQ}'
                  AND (h.ticker = ? OR h.cusip = ?)
                  AND h.manager_type IN ('active', 'hedge_fund', 'activist', 'quantitative')
                GROUP BY h.cik
                ORDER BY position_value DESC NULLS LAST
                LIMIT 15
            ),
            with_percentile AS (
                SELECT
                    ca.*,
                    (
                        SELECT COUNT(*)
                        FROM holdings h2
                        INNER JOIN market_data m2 ON h2.ticker = m2.ticker
                        WHERE h2.cik = ca.cik AND h2.quarter = '{LQ}'
                          AND h2.security_type_inferred IN ('equity', 'etf')
                          AND m2.market_cap IS NOT NULL AND m2.market_cap > 0
                          AND m2.market_cap <= {target_mktcap}
                    ) as holdings_below,
                    (
                        SELECT COUNT(*)
                        FROM holdings h2
                        INNER JOIN market_data m2 ON h2.ticker = m2.ticker
                        WHERE h2.cik = ca.cik AND h2.quarter = '{LQ}'
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
                            FROM fund_holdings fh
                            JOIN fund_universe fu ON fh.series_id = fu.series_id
                            WHERE fu.family_name ILIKE ? AND fh.ticker = ? AND fh.quarter = '{LQ}'
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
                logger.error(f"[query3 nport batch] {e}", exc_info=True)

        results = []
        for row in records:
            parent = row.get('parent_name') or row.get('manager_name')

            # Enhancement 1 — Position history (Since + Held)
            history = con.execute("""
                SELECT quarter, SUM(shares) as shares
                FROM holdings
                WHERE COALESCE(inst_parent_name, manager_name) = ?
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
                      AND quarter_from = '{FQ}' AND quarter_to = '{LQ}'
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
                        FROM holdings
                        WHERE COALESCE(inst_parent_name, manager_name) = ?
                          AND ticker = ? AND quarter = '{LQ}'
                          AND fund_name NOT IN (
                              SELECT DISTINCT manager_name FROM holdings
                              WHERE COALESCE(inst_parent_name, manager_name) = ?
                                AND ticker = ? AND quarter = '{LQ}'
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
                except Exception:
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



def query4(ticker):
    """Passive vs active ownership split."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                CASE
                    WHEN manager_type = 'passive' THEN 'Passive (Index)'
                    WHEN manager_type = 'activist' THEN 'Activist'
                    WHEN manager_type IN ('active', 'hedge_fund', 'quantitative') THEN 'Active'
                    ELSE 'Other/Unknown'
                END as category,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares,
                SUM(market_value_live) as total_value,
                SUM(pct_of_float) as total_pct_float
            FROM holdings
            WHERE quarter = '{LQ}' AND ticker = ?
            GROUP BY category
            ORDER BY total_value DESC NULLS LAST
        """, [ticker]).fetchdf()
        grand_total = df['total_value'].sum()
        df['pct_of_inst'] = df['total_value'] / grand_total * 100 if grand_total > 0 else 0
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query5(ticker):
    """Quarterly share change heatmap."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH pivoted AS (
                SELECT
                    COALESCE(inst_parent_name, manager_name) as holder,
                    manager_type,
                    SUM(CASE WHEN quarter='{FQ}' THEN shares END) as q1_shares,
                    SUM(CASE WHEN quarter='{QUARTERS[1]}' THEN shares END) as q2_shares,
                    SUM(CASE WHEN quarter='{PQ}' THEN shares END) as q3_shares,
                    SUM(CASE WHEN quarter='{LQ}' THEN shares END) as q4_shares
                FROM holdings
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



def query6(ticker):
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
                FROM beneficial_ownership
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
            FROM holdings
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



def query7(ticker, cik=None, fund_name=None):
    """Single fund portfolio — aggregated by ticker, with stats header."""
    con = get_db()
    try:
        if not cik:
            # Default to top non-passive holder of the ticker
            row = con.execute(f"""
                SELECT cik, fund_name FROM holdings
                WHERE ticker = ? AND quarter = '{LQ}'
                  AND manager_type NOT IN ('passive')
                ORDER BY market_value_live DESC NULLS LAST
                LIMIT 1
            """, [ticker]).fetchone()
            if not row:
                return {'stats': {}, 'positions': []}
            cik = row[0]
            fund_name = fund_name or row[1]

        # Build the WHERE filter — cik always, fund_name when provided
        where = "h.cik = ? AND h.quarter = '{LQ}'"
        params = [cik]
        if fund_name:
            where += " AND h.fund_name = ?"
            params.append(fund_name)

        # Fund metadata
        meta_where = "cik = ? AND quarter = '{LQ}'"
        meta_params = [cik]
        if fund_name:
            meta_where += " AND fund_name = ?"
            meta_params.append(fund_name)
        mgr_row = con.execute(f"""
            SELECT fund_name, MAX(manager_type) as manager_type
            FROM holdings WHERE {meta_where}
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
            FROM holdings h
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



def query8(ticker):
    """Cross-holder overlap — stocks most commonly held by same institutions."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH target_holders AS (
                SELECT DISTINCT cik
                FROM holdings
                WHERE ticker = ? AND quarter = '{LQ}'
            )
            SELECT
                h.ticker,
                h.issuer_name,
                COUNT(DISTINCT h.cik) as shared_holders,
                SUM(h.market_value_live) as total_value,
                (SELECT COUNT(*) FROM target_holders) as target_holders_count
            FROM holdings h
            INNER JOIN target_holders th ON h.cik = th.cik
            WHERE h.quarter = '{LQ}'
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



def query9(ticker):
    """Sector rotation analysis — sector allocation of active holders."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH target_ciks AS (
                SELECT DISTINCT cik
                FROM holdings
                WHERE ticker = ? AND quarter = '{LQ}'
                AND manager_type IN ('active', 'hedge_fund')
            )
            SELECT
                s.sector,
                COUNT(DISTINCT h.ticker) as num_stocks,
                SUM(h.market_value_live) as sector_value,
                SUM(h.market_value_live) * 100.0 / SUM(SUM(h.market_value_live)) OVER () as pct_of_total
            FROM holdings h
            INNER JOIN target_ciks tc ON h.cik = tc.cik
            INNER JOIN securities s ON h.cusip = s.cusip
            WHERE h.quarter = '{LQ}' AND s.sector IS NOT NULL AND s.sector != ''
            GROUP BY s.sector
            ORDER BY sector_value DESC NULLS LAST
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query10(ticker):
    """Position Changes — new entries AND exits combined."""
    con = get_db()
    try:
        entries = con.execute(f"""
            SELECT
                q4.manager_name, q4.manager_type,
                q4.shares, q4.market_value_live,
                q4.pct_of_portfolio, q4.pct_of_float
            FROM holdings q4
            LEFT JOIN holdings q3 ON q4.cik = q3.cik AND q3.ticker = ? AND q3.quarter = '{PQ}'
            WHERE q4.ticker = ? AND q4.quarter = '{LQ}' AND q3.cik IS NULL
            ORDER BY q4.market_value_live DESC NULLS LAST
            LIMIT 25
        """, [ticker, ticker]).fetchdf()

        exits = con.execute(f"""
            SELECT
                q3.manager_name, q3.manager_type,
                q3.shares as q3_shares,
                q3.market_value_usd as q3_value,
                q3.pct_of_portfolio as q3_pct
            FROM holdings q3
            LEFT JOIN holdings q4 ON q3.cik = q4.cik AND q4.ticker = ? AND q4.quarter = '{LQ}'
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


def query11(ticker):
    """Redirects to query10 (consolidated Position Changes)."""
    return query10(ticker)



def query12(ticker):
    """Concentration analysis — top holders cumulative % of float."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH ranked AS (
                SELECT
                    COALESCE(inst_parent_name, manager_name) as holder,
                    SUM(pct_of_float) as total_pct_float,
                    SUM(shares) as total_shares,
                    ROW_NUMBER() OVER (ORDER BY SUM(pct_of_float) DESC) as rn
                FROM holdings
                WHERE ticker = ? AND quarter = '{LQ}' AND pct_of_float IS NOT NULL
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



def query13(ticker=None, sector=None):
    """Sector rotation — institutional buying/selling by sector.
    If sector is provided, shows stocks in that sector.
    If no sector, shows all sectors with net flow summary."""
    con = get_db()
    try:
        if sector:
            # Specific sector: show individual stock rotation
            df = con.execute(f"""
                WITH sector_moves AS (
                    SELECT
                        h4.ticker,
                        h4.issuer_name,
                        COUNT(DISTINCT CASE WHEN h4.shares > COALESCE(h1.shares, 0) THEN h4.cik END) as buyers,
                        COUNT(DISTINCT CASE WHEN h4.shares < COALESCE(h1.shares, 0) THEN h4.cik END) as sellers,
                        COUNT(DISTINCT CASE WHEN h1.cik IS NULL THEN h4.cik END) as new_positions,
                        SUM(h4.market_value_live) as q4_total_value
                    FROM holdings h4
                    INNER JOIN market_data md ON h4.ticker = md.ticker AND md.sector = ?
                    LEFT JOIN holdings h1 ON h4.cik = h1.cik AND h4.ticker = h1.ticker AND h1.quarter = '{FQ}'
                    WHERE h4.quarter = '{LQ}'
                      AND h4.manager_type IN ('active', 'hedge_fund', 'activist')
                    GROUP BY h4.ticker, h4.issuer_name
                )
                SELECT *,
                    buyers - sellers as net_flow,
                    ROUND(buyers * 100.0 / NULLIF(buyers + sellers, 0), 1) as buy_pct
                FROM sector_moves
                WHERE buyers + sellers >= 3
                ORDER BY net_flow DESC
                LIMIT 25
            """, [sector]).fetchdf()
        else:
            # All sectors: summary view
            df = con.execute(f"""
                WITH sector_flows AS (
                    SELECT
                        md.sector,
                        COUNT(DISTINCT h4.ticker) as stocks,
                        COUNT(DISTINCT CASE WHEN h4.shares > COALESCE(h1.shares, 0) THEN h4.cik || h4.ticker END) as buy_moves,
                        COUNT(DISTINCT CASE WHEN h4.shares < COALESCE(h1.shares, 0) THEN h4.cik || h4.ticker END) as sell_moves,
                        SUM(h4.market_value_live) as q4_total_value
                    FROM holdings h4
                    INNER JOIN market_data md ON h4.ticker = md.ticker
                    LEFT JOIN holdings h1 ON h4.cik = h1.cik AND h4.ticker = h1.ticker AND h1.quarter = '{FQ}'
                    WHERE h4.quarter = '{LQ}' AND md.sector IS NOT NULL
                      AND h4.manager_type IN ('active', 'hedge_fund', 'activist')
                    GROUP BY md.sector
                )
                SELECT sector, stocks,
                    buy_moves, sell_moves,
                    buy_moves - sell_moves as net_flow,
                    ROUND(buy_moves * 100.0 / NULLIF(buy_moves + sell_moves, 0), 1) as buy_pct,
                    q4_total_value
                FROM sector_flows
                ORDER BY net_flow DESC
            """).fetchdf()
        return df_to_records(df)
    finally:
        pass



def query14(ticker):
    """Manager AUM vs position size — consolidated with conviction data."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                COALESCE(h.inst_parent_name, h.manager_name) as manager_name,
                h.manager_type,
                h.is_activist,
                m.aum_total / 1e9 as manager_aum_bn,
                SUM(h.market_value_live) / 1e6 as position_mm,
                MAX(h.pct_of_portfolio) as pct_of_portfolio,
                SUM(h.pct_of_float) as pct_of_float,
                SUM(h.shares) as shares
            FROM holdings h
            LEFT JOIN managers m ON h.cik = m.cik
            WHERE h.ticker = ? AND h.quarter = '{LQ}'
            GROUP BY COALESCE(h.inst_parent_name, h.manager_name), h.manager_type, h.is_activist, m.aum_total
            HAVING SUM(h.market_value_live) > 0
            ORDER BY SUM(h.market_value_live) DESC NULLS LAST
            LIMIT 25
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass



def query15(ticker=None):
    """Database statistics."""
    con = get_db()
    try:
        stats = {}
        stats['total_holdings'] = con.execute('SELECT COUNT(*) FROM holdings').fetchone()[0]
        stats['unique_filers'] = con.execute('SELECT COUNT(DISTINCT cik) FROM holdings').fetchone()[0]
        stats['unique_securities'] = con.execute('SELECT COUNT(DISTINCT cusip) FROM holdings').fetchone()[0]
        stats['quarters_loaded'] = con.execute('SELECT COUNT(DISTINCT quarter) FROM holdings').fetchone()[0]
        stats['manager_records'] = con.execute('SELECT COUNT(*) FROM managers').fetchone()[0]
        stats['securities_mapped'] = con.execute('SELECT COUNT(*) FROM securities').fetchone()[0]
        stats['market_data_tickers'] = con.execute('SELECT COUNT(*) FROM market_data').fetchone()[0]
        stats['adv_records'] = con.execute('SELECT COUNT(*) FROM adv_managers').fetchone()[0]

        # Quarter breakdown
        qstats = con.execute("""
            SELECT quarter, COUNT(*) as rows, COUNT(DISTINCT cik) as filers,
                   COUNT(DISTINCT cusip) as securities,
                   SUM(market_value_usd) / 1e9 as total_value_bn
            FROM holdings GROUP BY quarter ORDER BY quarter
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
            FROM holdings WHERE quarter = '{LQ}'
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


def query16(ticker):
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
            FROM fund_holdings fh
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE fh.ticker = ? AND fh.quarter = '{LQ}'
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
            FROM fund_holdings fh
            WHERE fh.ticker = ? AND fh.quarter = '{LQ}'
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


def ownership_trend_summary(ticker):
    """Aggregated institutional ownership trend across all quarters."""
    con = get_db()
    try:
        float_row = con.execute(
            "SELECT float_shares FROM market_data WHERE ticker = ?", [ticker]
        ).fetchone()
        float_shares = float_row[0] if float_row and float_row[0] else None

        df = con.execute("""
            SELECT quarter,
                   SUM(shares) as total_inst_shares,
                   SUM(market_value_usd) as total_inst_value,
                   COUNT(DISTINCT COALESCE(inst_parent_name, manager_name)) as holder_count,
                   SUM(CASE WHEN manager_type NOT IN ('passive') THEN market_value_usd ELSE 0 END) as active_value,
                   SUM(CASE WHEN manager_type = 'passive' THEN market_value_usd ELSE 0 END) as passive_value
            FROM holdings WHERE ticker = ? GROUP BY quarter ORDER BY quarter
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

        return {'quarters': rows, 'summary': summary}
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


def cohort_analysis(ticker, from_quarter=None, level='parent', active_only=False):
    """Cohort retention analysis: compare two quarters.
    level: 'parent' (13F institutional) or 'fund' (N-PORT fund series).
    active_only: when level='fund', exclude passive/index funds.
    """
    con = get_db()
    try:
        fq = from_quarter or PQ
        lq = LQ

        if level == 'fund':
            # Fund-level from fund_holdings, filter via fund_universe.is_actively_managed
            join_clause = "LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id"
            active_filter = "AND fu.is_actively_managed = true" if active_only else ""
            q1_df = con.execute(f"""
                SELECT fh.fund_name as investor,
                       SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
                FROM fund_holdings fh {join_clause}
                WHERE fh.ticker = ? AND fh.quarter = '{fq}' {active_filter}
                GROUP BY fh.fund_name
            """, [ticker]).fetchdf()
            q4_df = con.execute(f"""
                SELECT fh.fund_name as investor,
                       SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
                FROM fund_holdings fh {join_clause}
                WHERE fh.ticker = ? AND fh.quarter = '{lq}' {active_filter}
                GROUP BY fh.fund_name
            """, [ticker]).fetchdf()
        else:
            # Parent-level from holdings (13F)
            q1_df = con.execute(f"""
                SELECT COALESCE(inst_parent_name, manager_name) as investor,
                       SUM(shares) as shares, SUM(market_value_usd) as value
                FROM holdings WHERE ticker = ? AND quarter = '{fq}' GROUP BY investor
            """, [ticker]).fetchdf()
            q4_df = con.execute(f"""
                SELECT COALESCE(inst_parent_name, manager_name) as investor,
                       SUM(shares) as shares, SUM(market_value_usd) as value
                FROM holdings WHERE ticker = ? AND quarter = '{lq}' GROUP BY investor
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
                    SELECT COALESCE(inst_parent_name, manager_name) as investor,
                           SUM(shares) as shares
                    FROM holdings
                    WHERE ticker = ? AND quarter = '{q_from}'
                      AND manager_type NOT IN ('passive', 'unknown')
                    GROUP BY investor
                """, [ticker]).fetchdf()
                to_df = con.execute(f"""
                    SELECT COALESCE(inst_parent_name, manager_name) as investor,
                           SUM(shares) as shares
                    FROM holdings
                    WHERE ticker = ? AND quarter = '{q_to}'
                      AND manager_type NOT IN ('passive', 'unknown')
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
                pass
        summary['econ_retention_trend'] = econ_retention_trend

        return {'summary': summary, 'detail': detail}
    finally:
        pass  # connection managed by thread-local cache



def _compute_flows_live(ticker, quarter_from, quarter_to, con, level='parent', active_only=False):
    """Compute buyer/seller/new/exit flows live from holdings or fund_holdings.
    Returns (buyers, sellers, new_entries, exits) lists.
    """
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
            FROM fund_holdings fh {join_clause}
            WHERE fh.ticker = ? AND fh.quarter = '{quarter_from}' {af} GROUP BY fh.fund_name
        """, [ticker]).fetchdf()
        to_df = con.execute(f"""
            SELECT fh.fund_name as entity, SUM(fh.shares_or_principal) as shares, SUM(fh.market_value_usd) as value
            FROM fund_holdings fh {join_clause}
            WHERE fh.ticker = ? AND fh.quarter = '{quarter_to}' {af} GROUP BY fh.fund_name
        """, [ticker]).fetchdf()
    else:
        from_df = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as entity,
                   MAX(manager_type) as manager_type,
                   SUM(shares) as shares, SUM(market_value_usd) as value,
                   SUM(pct_of_float) as pct_of_float
            FROM holdings WHERE ticker = ? AND quarter = '{quarter_from}' GROUP BY entity
        """, [ticker]).fetchdf()
        to_df = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as entity,
                   MAX(manager_type) as manager_type,
                   SUM(shares) as shares, SUM(market_value_usd) as value,
                   SUM(pct_of_float) as pct_of_float
            FROM holdings WHERE ticker = ? AND quarter = '{quarter_to}' GROUP BY entity
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


def flow_analysis(ticker, period='1Q', peers=None, level='parent', active_only=False):
    """Flow analysis — default QoQ (1Q = most recent quarter).
    level: 'parent' (13F) or 'fund' (N-PORT).
    """
    period_map = {'4Q': FQ, '2Q': QUARTERS[1] if len(QUARTERS) > 1 else FQ, '1Q': PQ}
    quarter_from = period_map.get(period, PQ)
    quarter_to = LQ

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
            FROM holdings WHERE ticker = ? AND quarter = ? AND shares > 0
        """, [ticker, quarter_from]).fetchone()
        implied_from = ip[0] if ip and ip[0] else None
        ip2 = con.execute(f"""
            SELECT SUM(market_value_usd) / NULLIF(SUM(shares), 0)
            FROM holdings WHERE ticker = ? AND quarter = '{LQ}' AND shares > 0
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
                ref_shares = ts if ts > 0 else fs
                r['pct_float'] = round(ref_shares / flt * 100, 3) if flt and ref_shares else None
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
                        SELECT COALESCE(inst_parent_name, manager_name) as inv, manager_type, quarter,
                               SUM(shares) as shares, SUM(market_value_usd) as market_value_usd
                        FROM holdings WHERE ticker = ? AND quarter IN ('{qf}', '{qt}')
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
            except Exception:
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
        pass  # connection managed by thread-local cache


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


def portfolio_context(ticker, level='parent', active_only=False):
    """Conviction tab — portfolio concentration context for top holders.
    Returns each holder's sector breakdown with emphasis on the subject ticker's sector.
    """
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
        bench_date = q_date_map.get(LQ, '2025-12-31')
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
            pass
        subj_spx_weight = mkt_weights.get(subj_gics_sector, None)

        # Top 25 parents or funds by latest quarter value (same as Register)
        if level == 'fund':
            active_filter = "AND fu.is_actively_managed = true" if active_only else ""
            top_holders_df = con.execute(f"""
                SELECT fh.fund_name as holder, SUM(fh.market_value_usd) as val,
                       MAX(fu.is_actively_managed) as is_active
                FROM fund_holdings fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.quarter = '{LQ}' {active_filter}
                GROUP BY fh.fund_name
                ORDER BY val DESC NULLS LAST LIMIT 25
            """, [ticker]).fetchdf()
        else:
            top_holders_df = con.execute(f"""
                SELECT COALESCE(inst_parent_name, manager_name) as holder,
                       SUM(market_value_live) as val,
                       MAX(manager_type) as mtype
                FROM holdings
                WHERE (ticker = ? OR cusip = ?) AND quarter = '{LQ}'
                GROUP BY holder ORDER BY val DESC NULLS LAST LIMIT 25
            """, [ticker, cusip]).fetchdf()

        if top_holders_df.empty:
            return {'rows': [], 'subject_sector': subj_gics_sector,
                    'subject_sector_code': subj_gics_code,
                    'subject_industry': subj_yf_industry or ''}

        top_holders = top_holders_df['holder'].tolist()
        ph = ','.join(['?'] * len(top_holders))

        # Pull full portfolios for all top holders in one query, grouped by sector
        if level == 'fund':
            portfolio_df = con.execute(f"""
                SELECT
                    fh.fund_name as holder,
                    fh.ticker,
                    COALESCE(m.sector, 'Unknown') as yf_sector,
                    COALESCE(m.industry, '') as yf_industry,
                    SUM(fh.market_value_usd) as value
                FROM fund_holdings fh
                LEFT JOIN market_data m ON fh.ticker = m.ticker
                WHERE fh.quarter = '{LQ}' AND fh.fund_name IN ({ph})
                  AND fh.market_value_usd > 0
                GROUP BY fh.fund_name, fh.ticker, m.sector, m.industry
            """, top_holders).fetchdf()
        else:
            portfolio_df = con.execute(f"""
                SELECT
                    COALESCE(h.inst_parent_name, h.manager_name) as holder,
                    h.ticker,
                    COALESCE(m.sector, 'Unknown') as yf_sector,
                    COALESCE(m.industry, '') as yf_industry,
                    SUM(h.market_value_live) as value
                FROM holdings h
                LEFT JOIN market_data m ON h.ticker = m.ticker
                WHERE h.quarter = '{LQ}'
                  AND COALESCE(h.inst_parent_name, h.manager_name) IN ({ph})
                  AND h.market_value_live > 0
                GROUP BY holder, h.ticker, m.sector, m.industry
            """, top_holders).fetchdf()

        def _compute_metrics(holder_df, subject_value):
            """Compute all concentration metrics for a single holder's portfolio."""
            if holder_df.empty:
                return None
            total = float(holder_df['value'].sum())
            if total <= 0:
                return None
            unknown_val = float(holder_df[holder_df['yf_sector'] == 'Unknown']['value'].sum())
            etf_val = float(holder_df[holder_df['yf_sector'] == 'ETF']['value'].sum())
            unk_pct_ = round(unknown_val / total * 100, 1)
            etf_pct_ = round(etf_val / total * 100, 1)

            sector_totals_ = {}
            for _, prow in holder_df.iterrows():
                gics, code = _gics_sector(prow['yf_sector'], prow['yf_industry'])
                if gics in ('Unknown', 'ETF'):
                    continue
                sector_totals_[(gics, code)] = sector_totals_.get((gics, code), 0) + float(prow['value'])

            sorted_s = sorted(sector_totals_.items(), key=lambda x: x[1], reverse=True)
            subj_key_ = (subj_gics_sector, subj_gics_code)
            subj_sec_value = sector_totals_.get(subj_key_, 0)
            subj_sec_pct = round(subj_sec_value / total * 100, 1)
            subj_sec_rank = None
            for i, ((s, _), _) in enumerate(sorted_s, 1):
                if s == subj_gics_sector:
                    subj_sec_rank = i
                    break

            co_rank = None
            if subj_sec_value > 0:
                sec_rows = holder_df[
                    holder_df.apply(lambda r: _gics_sector(r['yf_sector'], r['yf_industry'])[0] == subj_gics_sector, axis=1)
                ].sort_values('value', ascending=False).reset_index(drop=True)
                for i, srow in sec_rows.iterrows():
                    if srow['ticker'] == ticker:
                        co_rank = i + 1
                        break

            ind_rank = None
            if subj_yf_industry:
                ind_rows = holder_df[holder_df['yf_industry'] == subj_yf_industry].sort_values('value', ascending=False).reset_index(drop=True)
                for i, srow in ind_rows.iterrows():
                    if srow['ticker'] == ticker:
                        ind_rank = i + 1
                        break

            top3_ = [code for (_, code), _ in sorted_s[:3]]
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
                'diversity': len(sector_totals_),
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
            # Fetch top 5 N-PORT children per parent
            children_by_parent = {}  # parent_name -> list of {fund_name, value}
            all_child_funds = set()
            for parent_row in results:
                pname = parent_row['institution']
                try:
                    kids = get_nport_children(pname, ticker, LQ, con, limit=5)
                    if kids:
                        children_by_parent[pname] = kids
                        for k in kids:
                            if k.get('institution'):
                                all_child_funds.add(k['institution'])
                except Exception:
                    continue

            if all_child_funds:
                # Batch query portfolios for all child funds
                ph_funds = ','.join(['?'] * len(all_child_funds))
                child_portfolio_df = con.execute(f"""
                    SELECT
                        fh.fund_name as holder,
                        fh.ticker,
                        COALESCE(m.sector, 'Unknown') as yf_sector,
                        COALESCE(m.industry, '') as yf_industry,
                        SUM(fh.market_value_usd) as value
                    FROM fund_holdings fh
                    LEFT JOIN market_data m ON fh.ticker = m.ticker
                    WHERE fh.quarter = '{LQ}' AND fh.fund_name IN ({ph_funds})
                      AND fh.market_value_usd > 0
                    GROUP BY fh.fund_name, fh.ticker, m.sector, m.industry
                """, list(all_child_funds)).fetchdf()

                # Also need is_actively_managed per fund for child type
                fund_meta_df = con.execute(f"""
                    SELECT DISTINCT fh.fund_name, MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active
                    FROM fund_holdings fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.fund_name IN ({ph_funds}) AND fh.quarter = '{LQ}'
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


def short_interest_analysis(ticker):
    """Comprehensive short interest analysis for a ticker.
    Combines N-PORT fund-level shorts, FINRA daily volume, and long/short cross-reference.
    """
    con = get_db()
    try:
        result = {}

        # 1. N-PORT short positions by quarter (trend)
        nport_trend = []
        try:
            trend_df = con.execute("""
                SELECT quarter,
                       COUNT(DISTINCT fund_name) as fund_count,
                       SUM(ABS(shares_or_principal)) as short_shares,
                       SUM(ABS(market_value_usd)) as short_value
                FROM fund_holdings
                WHERE ticker = ? AND shares_or_principal < 0
                GROUP BY quarter ORDER BY quarter
            """, [ticker]).fetchdf()
            nport_trend = df_to_records(trend_df)
        except Exception:
            pass
        result['nport_trend'] = nport_trend

        # 2. N-PORT short positions detail (latest quarter)
        nport_detail = []
        try:
            detail_df = con.execute(f"""
                SELECT fh.fund_name, fh.family_name,
                       ABS(fh.shares_or_principal) as short_shares,
                       ABS(fh.market_value_usd) as short_value,
                       fh.quarter,
                       fu.total_net_assets / 1e6 as fund_aum_mm
                FROM fund_holdings fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.shares_or_principal < 0
                  AND fh.quarter = '{LQ}'
                ORDER BY ABS(fh.shares_or_principal) DESC
            """, [ticker]).fetchdf()
            nport_detail = df_to_records(detail_df)
            # Add pct of NAV
            for r in nport_detail:
                aum = r.get('fund_aum_mm')
                val = r.get('short_value')
                r['pct_of_nav'] = round(val / (aum * 1e6) * 100, 3) if aum and aum > 0 and val else None
        except Exception:
            pass
        result['nport_detail'] = nport_detail

        # 3. N-PORT short positions history per fund (for cross-quarter comparison)
        nport_by_fund = []
        try:
            fund_hist = con.execute("""
                SELECT fund_name, quarter, ABS(shares_or_principal) as short_shares
                FROM fund_holdings
                WHERE ticker = ? AND shares_or_principal < 0
                ORDER BY fund_name, quarter
            """, [ticker]).fetchdf()
            # Pivot: fund → {quarter: shares}
            funds_seen = {}
            for _, r in fund_hist.iterrows():
                fn = r['fund_name']
                if fn not in funds_seen:
                    funds_seen[fn] = {'fund_name': fn}
                funds_seen[fn][r['quarter']] = float(r['short_shares'])
            nport_by_fund = list(funds_seen.values())
            # Sort by latest quarter shares
            nport_by_fund.sort(key=lambda x: x.get(LQ, 0), reverse=True)
        except Exception:
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
        except Exception:
            pass
        result['short_volume'] = short_volume

        # 5. Long/short cross-reference — institutions both long and short
        cross_ref = []
        try:
            # Long from 13F
            long_df = con.execute(f"""
                SELECT COALESCE(inst_parent_name, manager_name) as parent,
                       SUM(shares) as long_shares, SUM(market_value_live) as long_value
                FROM holdings WHERE ticker = ? AND quarter = '{LQ}'
                GROUP BY parent
            """, [ticker]).fetchdf()
            long_map = {r['parent']: r for _, r in long_df.iterrows()}

            # Short from N-PORT — match family to parent
            short_df = con.execute(f"""
                SELECT family_name,
                       SUM(ABS(shares_or_principal)) as short_shares,
                       SUM(ABS(market_value_usd)) as short_value
                FROM fund_holdings
                WHERE ticker = ? AND shares_or_principal < 0 AND quarter = '{LQ}'
                GROUP BY family_name
            """, [ticker]).fetchdf()

            for _, s in short_df.iterrows():
                fam = s['family_name'] or ''
                # Try to match to a long parent
                for parent, lrow in long_map.items():
                    parent_lower = parent.lower()
                    fam_words = fam.lower().split()[:2]
                    if any(w in parent_lower for w in fam_words if len(w) > 3):
                        ls = float(lrow['long_shares'] or 0)
                        lv = float(lrow['long_value'] or 0)
                        ss = float(s['short_shares'] or 0)
                        sv = float(s['short_value'] or 0)
                        net_pct = round((ls - ss) / ls * 100, 1) if ls > 0 else 0
                        cross_ref.append({
                            'institution': parent,
                            'long_shares': ls, 'long_value': lv,
                            'short_shares': ss, 'short_value': sv,
                            'net_exposure_pct': net_pct,
                        })
                        break
            cross_ref.sort(key=lambda x: x['short_shares'], reverse=True)
        except Exception:
            pass
        result['cross_ref'] = cross_ref

        # 6. Long positions aggregated by manager type (from Smart Money)
        long_by_type = []
        try:
            lbt = con.execute(f"""
                SELECT COALESCE(manager_type, 'unknown') as manager_type,
                       COUNT(DISTINCT cik) as holders,
                       SUM(shares) as long_shares,
                       SUM(market_value_live) as long_value
                FROM holdings WHERE ticker = ? AND quarter = '{LQ}'
                GROUP BY manager_type ORDER BY long_value DESC NULLS LAST
            """, [ticker]).fetchdf()
            long_by_type = df_to_records(lbt)
        except Exception:
            pass
        result['long_by_type'] = long_by_type

        # 7. Short-only funds (N-PORT shorts without matching 13F long parent)
        short_only = []
        try:
            sof_df = con.execute(f"""
                SELECT fh.fund_name, fh.family_name,
                       ABS(fh.shares_or_principal) as short_shares,
                       ABS(fh.market_value_usd) as short_value,
                       MAX(fu.total_net_assets) / 1e6 as fund_aum_mm
                FROM fund_holdings fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.shares_or_principal < 0 AND fh.quarter = '{LQ}'
                GROUP BY fh.fund_name, fh.family_name, fh.series_id
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
                    short_only.append({
                        'fund_name': r['fund_name'],
                        'family_name': r['family_name'],
                        'short_shares': float(r['short_shares'] or 0),
                        'short_value': float(r['short_value'] or 0),
                        'fund_aum_mm': float(r['fund_aum_mm'] or 0) if r['fund_aum_mm'] else None,
                    })
        except Exception:
            pass
        result['short_only_funds'] = short_only

        # 8. Summary card data
        total_short_shares = sum(r.get(LQ, 0) for r in nport_by_fund)
        total_short_funds = len([r for r in nport_by_fund if r.get(LQ, 0) > 0])
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


def get_short_long_comparison(ticker):
    """Find managers who are long (13F) AND short (N-PORT) the same ticker."""
    con = get_db()
    try:
        result = {'ticker': ticker, 'long_short_managers': [], 'short_only_funds': []}

        if not _has_table('fund_holdings'):
            return result

        # Managers with 13F long positions
        longs = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as manager,
                   SUM(shares) as long_shares,
                   SUM(market_value_usd) as long_value,
                   manager_type
            FROM holdings
            WHERE ticker = ? AND quarter = '{LQ}' AND shares > 0
            GROUP BY manager, manager_type
        """, [ticker]).fetchdf()

        # N-PORT short positions (negative shares = short)
        shorts = con.execute(f"""
            SELECT fh.fund_name,
                   nam.adviser_name,
                   ABS(fh.shares_or_principal) as short_shares,
                   ABS(fh.market_value_usd) as short_value,
                   fh.quarter
            FROM fund_holdings fh
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
                    'long_value_k': float(long_row['long_value_k']),
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


# ---------------------------------------------------------------------------
# Short squeeze signal (Item 10)
# ---------------------------------------------------------------------------


def get_short_squeeze_candidates():
    """Flag tickers with high institutional crowding + high short interest."""
    con = get_db()
    try:
        if not _has_table('short_interest'):
            return []

        df = con.execute(f"""
            WITH crowd AS (
                SELECT ticker,
                       COUNT(DISTINCT cik) as num_holders,
                       SUM(shares) as total_shares,
                       SUM(market_value_usd) as total_value
                FROM holdings
                WHERE quarter = '{LQ}'
                GROUP BY ticker
            ),
            si AS (
                SELECT ticker,
                       MAX(short_pct) as max_short_pct,
                       MAX(short_volume) as latest_short_vol,
                       MAX(report_date) as latest_date
                FROM short_interest
                GROUP BY ticker
            ),
            mkt AS (
                SELECT ticker, market_cap, float_shares
                FROM market_data
                WHERE market_cap > 0
            )
            SELECT c.ticker,
                   c.num_holders,
                   c.total_value_k,
                   si.max_short_pct,
                   si.latest_short_vol,
                   m.market_cap,
                   m.float_shares,
                   -- Crowding score: institutional ownership concentration
                   CASE WHEN m.float_shares > 0
                        THEN c.total_shares * 100.0 / m.float_shares
                        ELSE NULL END as inst_pct_float,
                   -- Squeeze score: high short + high institutional = potential squeeze
                   CASE WHEN m.float_shares > 0 AND si.max_short_pct > 0
                        THEN si.max_short_pct * (c.total_shares * 1.0 / m.float_shares)
                        ELSE NULL END as squeeze_score
            FROM crowd c
            JOIN si ON c.ticker = si.ticker
            LEFT JOIN mkt m ON c.ticker = m.ticker
            WHERE si.max_short_pct >= 15  -- at least 15% short
            ORDER BY squeeze_score DESC NULLS LAST
            LIMIT 50
        """).fetchdf()

        return df_to_records(df)
    finally:
        pass


# Map query number to function
QUERY_FUNCTIONS = {
    1: query1, 2: query2, 3: query3, 4: query4, 5: query5,
    6: query6, 7: query7, 8: query8, 9: query9, 10: query10,
    11: query11, 12: query12, 13: query13, 14: query14, 15: query15,
}

QUERY_NAMES = {
    1: 'Register', 2: 'Holder Changes', 3: 'Conviction',
    6: 'Activist', 7: 'Fund Portfolio', 8: 'Cross-Ownership',
    9: 'Sector Rotation', 10: 'New Positions', 11: 'Exits',
    14: 'AUM vs Position', 15: 'DB Statistics',
}


# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------


def get_summary(ticker):
    """Quick summary stats for the header card. Cached for 5 min."""
    return _cached(f"summary:{ticker}", lambda: _get_summary_impl(ticker))

def _get_summary_impl(ticker):
    con = get_db()
    try:
        cusip = get_cusip(con, ticker)
        if not cusip:
            return None

        # Company name — use most common issuer_name from filings (avoids CUSIP cross-contamination)
        name_row = con.execute(
            f"SELECT MODE(issuer_name) FROM holdings WHERE ticker = ? AND quarter = '{LQ}'",
            [ticker]
        ).fetchone()
        company_name = name_row[0] if name_row else ticker

        # Latest quarter
        q_row = con.execute("""
            SELECT MAX(quarter) FROM holdings WHERE ticker = ?
        """, [ticker]).fetchone()
        latest_quarter = q_row[0] if q_row else 'N/A'

        # Total institutional holdings
        totals = con.execute(f"""
            SELECT
                SUM(market_value_live) as total_value,
                SUM(pct_of_float) as total_pct_float,
                COUNT(DISTINCT cik) as num_holders,
                SUM(shares) as total_shares
            FROM holdings
            WHERE ticker = ? AND quarter = '{LQ}'
        """, [ticker]).fetchone()

        # Active vs passive split
        split = con.execute(f"""
            SELECT
                SUM(CASE WHEN manager_type = 'passive' THEN market_value_live ELSE 0 END) as passive_value,
                SUM(CASE WHEN manager_type IN ('active','hedge_fund','quantitative','activist')
                    THEN market_value_live ELSE 0 END) as active_value
            FROM holdings
            WHERE ticker = ? AND quarter = '{LQ}'
        """, [ticker]).fetchone()

        # Market data
        mkt = con.execute(
            "SELECT price_live, market_cap, float_shares FROM market_data WHERE ticker = ?",
            [ticker]
        ).fetchone()

        # N-PORT coverage
        nport = get_nport_coverage(ticker, LQ, con)
        total_value = totals[0] if totals else 0
        nport_val = nport.get('nport_total_value') or 0
        nport_pct = round(nport_val / total_value * 100, 1) if total_value and total_value > 0 else None

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
            'nport_coverage': nport_pct,
            'nport_funds': nport.get('nport_fund_count', 0),
        }
        return clean_for_json(result)
    finally:
        pass  # connection managed by thread-local cache


# ---------------------------------------------------------------------------
# Excel export helper
# ---------------------------------------------------------------------------




def _cross_ownership_query(con, tickers, anchor=None, active_only=False, limit=25):
    """Shared logic for cross-ownership matrix.

    If anchor is set: rows = top holders of that ticker, ordered by anchor holding.
    If anchor is None: rows = top holders by total across all tickers.
    """
    # Company names
    placeholders = ','.join(['?'] * len(tickers))
    names_df = con.execute(f"""
        SELECT ticker, MODE(issuer_name) as name
        FROM holdings
        WHERE ticker IN ({placeholders}) AND quarter = '{LQ}'
        GROUP BY ticker
    """, tickers).fetchdf()
    companies = {r['ticker']: r['name'] for _, r in names_df.iterrows()}

    type_filter = "AND h.manager_type NOT IN ('passive')" if active_only else ""
    all_tickers_ph = ','.join(['?'] * len(tickers))

    pivot_cols = ', '.join(
        "SUM(CASE WHEN ph.ticker = '{}' THEN ph.holding_value END) AS \"{}\"".format(t, t)
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
                COALESCE(h.inst_parent_name, h.manager_name) as investor,
                MAX(h.manager_type) as type,
                h.ticker,
                SUM(h.market_value_live) as holding_value
            FROM holdings h
            WHERE h.ticker IN ({all_tickers_ph})
              AND h.quarter = '{LQ}'
              {type_filter}
            GROUP BY investor, h.ticker
        ),
        portfolio_totals AS (
            SELECT
                COALESCE(h.inst_parent_name, h.manager_name) as investor,
                SUM(h.market_value_live) as total_portfolio
            FROM holdings h
            WHERE h.quarter = '{LQ}'
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
        holdings = {}
        total_across = 0
        for t in tickers:
            val = row[t]
            if pd.notna(val) and val != 0:
                holdings[t] = float(val)
                total_across += float(val)
            else:
                holdings[t] = None
        total_port = float(row['total_portfolio']) if pd.notna(row['total_portfolio']) and row['total_portfolio'] > 0 else None
        pct = round(total_across / total_port * 100, 4) if total_port else None
        investors.append({
            'investor': row['investor'],
            'type': row['type'],
            'holdings': holdings,
            'total_across': total_across if total_across > 0 else None,
            'pct_of_portfolio': pct,
        })

    return clean_for_json({
        'tickers': tickers,
        'companies': companies,
        'investors': investors,
    })
