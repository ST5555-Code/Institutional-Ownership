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
        df = con.execute(f"""
            SELECT
                fund_name,
                MAX(market_value_usd) as value,
                MAX(shares_or_principal) as shares,
                MAX(pct_of_nav) as pct_of_nav,
                series_id
            FROM fund_holdings fh
            WHERE EXISTS (SELECT 1 FROM UNNEST([{ph}]) t(p) WHERE family_name ILIKE t.p)
              AND ticker = ?
              AND quarter = ?
              {excl_clause}
            GROUP BY fund_name, series_id
            ORDER BY value DESC NULLS LAST
            LIMIT {int(limit)}
        """, like_patterns + [ticker, quarter] + excl_params).fetchdf()
        rows = df_to_records(df)
        if not rows:
            return None
        return [{'institution': r.get('fund_name'), 'value_live': r.get('value'),
                 'shares': r.get('shares'), 'pct_float': r.get('pct_of_nav'),
                 'source': 'N-PORT'} for r in rows]
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

        # N-PORT fund series lookup (same as query3)
        nport_by_parent = {}
        if has_table('fund_holdings') and has_table('fund_universe'):
            try:
                for pname in parent_names:
                    mp = match_nport_family(pname)
                    if not mp:
                        continue
                    for pat in mp:
                        like_pat = '%' + pat + '%'
                        kids = con.execute(f"""
                            SELECT fh.fund_name, SUM(fh.shares_or_principal) as shares,
                                   SUM(fh.market_value_usd) as value
                            FROM fund_holdings fh
                            JOIN fund_universe fu ON fh.series_id = fu.series_id
                            WHERE fu.family_name ILIKE ? AND fh.ticker = ? AND fh.quarter = '{LQ}'
                            GROUP BY fh.fund_name ORDER BY value DESC NULLS LAST LIMIT 5
                        """, [like_pat, ticker]).fetchall()
                        if kids:
                            if pname not in nport_by_parent:
                                nport_by_parent[pname] = []
                            seen = {c['institution'] for c in nport_by_parent[pname]}
                            for k in kids:
                                if k[0] not in seen:
                                    nport_by_parent[pname].append({
                                        'institution': k[0], 'value_live': k[2],
                                        'shares': k[1], 'pct_float': None,
                                        'type': 'active', 'source': 'N-PORT',
                                        'subadviser_note': None,
                                    })
                                    seen.add(k[0])
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

            # If no N-PORT, use 13F children as-is
            if not nport_kids:
                merged = f13_kids

            effective_children = len(merged)
            source = 'N-PORT' if nport_kids else '13F'

            results.append({
                'rank': rank,
                'institution': pname,
                'value_live': parent['total_value_live'],
                'shares': parent['total_shares'],
                'pct_float': parent['pct_float'],
                'type': parent['type'],
                'is_parent': effective_children >= 2,
                'child_count': effective_children,
                'level': 0,
                'source': source,
                'subadviser_note': get_subadviser_note(pname) if not nport_kids else None,
            })

            if effective_children >= 2:
                for c in merged:
                    results.append({
                        'rank': None,
                        'institution': c.get('institution'),
                        'value_live': c.get('value_live'),
                        'shares': c.get('shares'),
                        'pct_float': c.get('pct_float'),
                        'type': c.get('type', parent['type']),
                        'is_parent': False,
                        'child_count': 0,
                        'level': 1,
                        'source': c.get('source', '13F'),
                        'subadviser_note': c.get('subadviser_note'),
                    })
        return results
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
    """Largest new positions (Q4 entries)."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                q4.manager_name,
                q4.manager_type,
                q4.shares,
                q4.market_value_live,
                q4.pct_of_portfolio,
                q4.pct_of_float
            FROM holdings q4
            LEFT JOIN holdings q3 ON q4.cik = q3.cik AND q3.ticker = ? AND q3.quarter = '{PQ}'
            WHERE q4.ticker = ? AND q4.quarter = '{LQ}' AND q3.cik IS NULL
            ORDER BY q4.market_value_live DESC NULLS LAST
            LIMIT 20
        """, [ticker, ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query11(ticker):
    """Largest exits (Q3 holders gone in Q4)."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                q3.manager_name,
                q3.manager_type,
                q3.shares as q3_shares,
                q3.market_value_usd as q3_value,
                q3.pct_of_portfolio as q3_pct
            FROM holdings q3
            LEFT JOIN holdings q4 ON q3.cik = q4.cik AND q4.ticker = ? AND q4.quarter = '{LQ}'
            WHERE q3.ticker = ? AND q3.quarter = '{PQ}' AND q4.cik IS NULL
            ORDER BY q3.market_value_usd DESC
            LIMIT 20
        """, [ticker, ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



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



def query13(ticker=None):
    """Energy sector institutional rotation (Q1 to Q4 2025)."""
    con = get_db()
    try:
        df = con.execute(f"""
            WITH energy_moves AS (
                SELECT
                    h4.ticker,
                    h4.issuer_name,
                    COUNT(DISTINCT CASE WHEN h4.shares > COALESCE(h1.shares, 0) THEN h4.cik END) as buyers,
                    COUNT(DISTINCT CASE WHEN h4.shares < COALESCE(h1.shares, 0) THEN h4.cik END) as sellers,
                    COUNT(DISTINCT CASE WHEN h1.cik IS NULL THEN h4.cik END) as new_positions,
                    SUM(h4.market_value_live) as q4_total_value
                FROM holdings h4
                INNER JOIN securities s ON h4.cusip = s.cusip AND s.is_energy = true
                LEFT JOIN holdings h1 ON h4.cik = h1.cik AND h4.ticker = h1.ticker AND h1.quarter = '{FQ}'
                WHERE h4.quarter = '{LQ}'
                  AND h4.manager_type IN ('active', 'hedge_fund', 'activist')
                GROUP BY h4.ticker, h4.issuer_name
            )
            SELECT *,
                buyers - sellers as net_flow,
                ROUND(buyers * 100.0 / (buyers + sellers), 1) as buy_pct
            FROM energy_moves
            WHERE buyers + sellers >= 5
            ORDER BY net_flow DESC
            LIMIT 25
        """).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



def query14(ticker):
    """Manager AUM vs position size."""
    con = get_db()
    try:
        df = con.execute(f"""
            SELECT
                h.manager_name,
                h.manager_type,
                h.is_activist,
                m.aum_total / 1e9 as manager_aum_bn,
                h.market_value_live / 1e6 as position_mm,
                h.pct_of_portfolio,
                h.shares
            FROM holdings h
            LEFT JOIN managers m ON h.cik = m.cik
            WHERE h.ticker = ? AND h.quarter = '{LQ}'
              AND m.aum_total IS NOT NULL AND m.aum_total > 0
            ORDER BY h.market_value_live DESC NULLS LAST
            LIMIT 50
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache



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
        for row in rows:
            total_shares = row.get('total_inst_shares') or 0
            total_value = row.get('total_inst_value') or 0
            row['pct_float'] = round(total_shares / float_shares * 100, 2) if float_shares and float_shares > 0 else None
            active_val = row.get('active_value') or 0
            row['active_pct'] = round(active_val / total_value * 100, 2) if total_value > 0 else None
            row['passive_pct'] = round((total_value - active_val) / total_value * 100, 2) if total_value > 0 else None
            if prev_shares is not None:
                net_change = total_shares - prev_shares
                row['net_shares_change'] = net_change
                pct_change = net_change / prev_shares if prev_shares > 0 else 0
                row['signal'] = '\u2191' if pct_change > 0.005 else ('\u2193' if pct_change < -0.005 else '\u2192')
            else:
                row['net_shares_change'] = None
                row['signal'] = None
            prev_shares = total_shares

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



def cohort_analysis(ticker):
    """Cohort retention analysis: Q1 vs Q4 holders."""
    con = get_db()
    try:
        q1_df = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as investor,
                   SUM(shares) as shares, SUM(market_value_usd) as value
            FROM holdings WHERE ticker = ? AND quarter = '{FQ}' GROUP BY investor
        """, [ticker]).fetchdf()
        q4_df = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as investor,
                   SUM(shares) as shares, SUM(market_value_usd) as value
            FROM holdings WHERE ticker = ? AND quarter = '{LQ}' GROUP BY investor
        """, [ticker]).fetchdf()

        q1_map = {r['investor']: r for r in df_to_records(q1_df)}
        q4_map = {r['investor']: r for r in df_to_records(q4_df)}
        q1_set, q4_set = set(q1_map.keys()), set(q4_map.keys())
        retained = q1_set & q4_set
        new_entries_set = q4_set - q1_set
        exits_set = q1_set - q4_set

        increased, decreased, unchanged = [], [], []
        for inv in retained:
            s1 = q1_map[inv].get('shares') or 0
            s4 = q4_map[inv].get('shares') or 0
            (increased if s4 > s1 else decreased if s4 < s1 else unchanged).append(inv)

        def _stats(investors, src):
            c = len(investors)
            s = sum((src[i].get('shares') or 0) for i in investors)
            v = sum((src[i].get('value') or 0) for i in investors)
            return {'holders': c, 'shares': s, 'value': v, 'avg_position': round(v / c, 2) if c > 0 else 0}

        detail = [
            {'category': 'Retained \u2014 increased', **_stats(increased, q4_map)},
            {'category': 'Retained \u2014 decreased', **_stats(decreased, q4_map)},
            {'category': 'Retained \u2014 unchanged', **_stats(unchanged, q4_map)},
            {'category': 'New entries', **_stats(list(new_entries_set), q4_map)},
            {'category': 'Exits', **_stats(list(exits_set), q1_map)},
        ]

        total_q1 = len(q1_set)
        summary = {
            'retention_rate': round(len(retained) / total_q1 * 100, 2) if total_q1 > 0 else 0,
            'new_entries_count': len(new_entries_set),
            'new_entries_shares': sum((q4_map[i].get('shares') or 0) for i in new_entries_set),
            'exits_count': len(exits_set),
            'exits_shares': sum((q1_map[i].get('shares') or 0) for i in exits_set),
            'net_adds_count': len(increased),
            'net_adds_value': sum(((q4_map[i].get('value') or 0) - (q1_map[i].get('value') or 0)) for i in increased),
            'net_trims_count': len(decreased),
            'net_trims_value': sum(((q4_map[i].get('value') or 0) - (q1_map[i].get('value') or 0)) for i in decreased),
        }
        return {'summary': summary, 'detail': detail}
    finally:
        pass  # connection managed by thread-local cache



def flow_analysis(ticker, period='4Q', peers=None):
    """Flow analysis using pre-computed investor_flows and ticker_flow_stats tables.

    Falls back to live computation if pre-computed tables do not exist.
    """
    period_map = {'4Q': FQ, '2Q': QUARTERS[1] if len(QUARTERS) > 1 else FQ, '1Q': PQ}
    quarter_from = period_map.get(period, FQ)
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

        # Fetch flows for this period
        df = con.execute("""
            SELECT inst_parent_name, manager_type, from_shares, to_shares, net_shares,
                   pct_change, from_value, to_value, from_price,
                   price_adj_flow, raw_flow, price_effect,
                   is_new_entry, is_exit, flow_4q, flow_2q,
                   momentum_ratio, momentum_signal
            FROM investor_flows
            WHERE ticker = ? AND quarter_from = ?
            ORDER BY price_adj_flow DESC NULLS LAST
        """, [ticker, quarter_from]).fetchdf()
        rows = df_to_records(df)

        # Add subadviser notes
        for r in rows:
            r['subadviser_note'] = get_subadviser_note(r.get('inst_parent_name'))

        # Split into categories
        buyers = [r for r in rows if not r.get('is_new_entry') and not r.get('is_exit')
                  and r.get('price_adj_flow') is not None and r['price_adj_flow'] > 0][:25]
        sellers_all = [r for r in rows if not r.get('is_new_entry') and not r.get('is_exit')
                       and r.get('price_adj_flow') is not None and r['price_adj_flow'] < 0]
        sellers = sellers_all[-25:] if len(sellers_all) > 25 else sellers_all
        new_entries = [r for r in rows if r.get('is_new_entry')]
        new_entries.sort(key=lambda x: x.get('to_value') or 0, reverse=True)
        new_entries = new_entries[:25]
        exits = [r for r in rows if r.get('is_exit')]
        exits.sort(key=lambda x: x.get('from_value') or 0, reverse=True)
        exits = exits[:25]

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

        return clean_for_json({
            'period': period,
            'quarter_from': quarter_from,
            'quarter_to': quarter_to,
            'implied_prices': {quarter_from: implied_from, quarter_to: implied_to},
            'buyers': buyers,
            'sellers': sellers,
            'new_entries': new_entries,
            'exits': exits,
            'charts': {
                'flow_intensity': chart_data,
                'churn': chart_data,
            },
        })
    finally:
        pass  # connection managed by thread-local cache


# ---------------------------------------------------------------------------
# Short vs Long comparison (Item 9)
# ---------------------------------------------------------------------------


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
