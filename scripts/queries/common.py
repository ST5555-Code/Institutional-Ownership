"""
queries/common.py — shared helpers for the queries package.

Originally the body of scripts/queries.py; split into a domain
package (register, fund, flows, market, cross, trend, entities)
during the G7 refactor. All low-level helpers (DB access wrappers,
pct_of_so resolver, CUSIP lookup, N-PORT family-pattern logic,
N-PORT children fetchers, _setup state) live here. Domain modules
import from .common.

is_latest filter policy (p2-04, migration 015):
  Every read from holdings_v2, fund_holdings_v2, or
  beneficial_ownership_v2 filters on is_latest=TRUE to see only
  current-state rows (never superseded by an amendment). Placement:

    - FROM / INNER JOIN / bare table  -> WHERE clause.
    - LEFT / RIGHT / FULL OUTER JOIN  -> ON clause (preserves
      NULL-semantics for new-entry / exit detection that tests
      `<alias>.key IS NULL` in WHERE).

  Until amendments start landing (pipeline Phase 4) the filter is a
  no-op: migration 015 backfilled every existing row to
  is_latest=TRUE. Exclusions — where a query legitimately needs the
  full row set including superseded versions — live OUTSIDE this
  module:

    1. Pipeline promote/rollback scripts (scripts/pipeline/*,
       scripts/promote_*.py, scripts/enrich_*.py) — need the full
       row set for INSERT/UPDATE/DELETE bookkeeping.
    2. Migration scripts (scripts/migrations/*).
    3. Admin row-count diagnostics on beneficial_ownership_v2 in
       scripts/admin_bp.py — intentionally count ALL rows for DQ
       totals / coverage.
"""

import logging

from config import LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER, SUBADVISER_EXCLUSIONS
# Response-shaping helpers (clean_for_json, df_to_records, etc.) are
# re-exported by queries/__init__.py directly from serializers — common.py
# itself does not use them. df_to_records is the only one referenced here.
from serializers import df_to_records  # noqa: F401 — used in NPORT children helpers

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



# ---------------------------------------------------------------------------
# pct_of_so denominator resolution (BLOCK-PCT-OF-SO-PERIOD-ACCURACY Phase 1c)
# ---------------------------------------------------------------------------
#
# Shared helpers for the N-PORT / flow compute paths that previously used
# `market_data.float_shares` as a latest-value denominator. Matches the 13F
# enrichment cascade in scripts/enrich_holdings.py Pass B:
#
#   tier 1 — shares_outstanding_history ASOF match at/before as_of_date
#            → source 'soh_period_accurate'
#   tier 2 — market_data.shares_outstanding (latest)
#            → source 'market_data_so_latest'
#   tier 3 — market_data.float_shares (latest)
#            → source 'market_data_float_latest'
#   tier 4 — no data available
#            → (None, None); caller stores pct_of_so=None, source=None
#
# Staleness tolerance note for N-PORT month-ends: N-PORT `fh.report_date`
# values include non-quarter months (Jan, Feb, Apr, May, Jul, Aug, Oct, Nov).
# us-gaap:CSO XBRL facts are predominantly filed at calendar quarter-ends,
# so the ASOF match for a Jan-31 N-PORT report can be up to ~90 days stale
# (prior Dec-31 10-K). Tier-1 match is still preferred over latest market_data,
# but downstream consumers may want to flag stale matches in display.

_QUARTER_END_DATES = {
    'Q1': ('{year}-03-31', 31),
    'Q2': ('{year}-06-30', 30),
    'Q3': ('{year}-09-30', 30),
    'Q4': ('{year}-12-31', 31),
}


def _quarter_to_date(quarter):
    """Convert 'YYYYQN' -> ISO date string 'YYYY-MM-DD' for quarter-end.

    Returns None for malformed input — callers pass None through as
    as_of_date, which disables the SOH tier and falls through to
    market_data.
    """
    if not quarter or len(quarter) != 6 or quarter[4] != 'Q':
        return None
    spec = _QUARTER_END_DATES.get(quarter[4:6])
    if not spec:
        return None
    template, _ = spec
    return template.format(year=quarter[:4])


def _resolve_pct_of_so_denom(con, ticker, as_of_date=None):
    """Three-tier denominator + source for pct_of_so.

    as_of_date : ISO 'YYYY-MM-DD' or None.
                 If provided, ASOF-matches SOH at/before that date.
                 If None, SOH tier skipped.
    Returns    : (denominator: float | None, source: str | None).
    """
    if not ticker:
        return None, None
    if as_of_date:
        row = con.execute(
            """
            SELECT shares FROM shares_outstanding_history
             WHERE ticker = ? AND as_of_date <= ?
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            [ticker, as_of_date],
        ).fetchone()
        if row and row[0] and row[0] > 0:
            return float(row[0]), 'soh_period_accurate'

    row = con.execute(
        "SELECT shares_outstanding, float_shares FROM market_data WHERE ticker = ?",
        [ticker],
    ).fetchone()
    if not row:
        return None, None
    md_so, md_float = row
    if md_so and md_so > 0:
        return float(md_so), 'market_data_so_latest'
    if md_float and md_float > 0:
        return float(md_float), 'market_data_float_latest'
    return None, None


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



# ---------------------------------------------------------------------------
# Canonical fund_strategy partitions (PR-3)
# ---------------------------------------------------------------------------
# Single source of truth for the active/passive split at the fund layer.
# Replaces six+ hardcoded inclusion lists across query files and the
# now-dropped `fund_universe.is_actively_managed` boolean column. Together
# these tuples cover all seven canonical fund_strategy values with no gap
# and no overlap.

ACTIVE_FUND_STRATEGIES = ('equity', 'balanced', 'multi_asset')
PASSIVE_FUND_STRATEGIES = ('passive', 'bond_or_other', 'excluded', 'final_filing')


def _fund_type_label(fund_strategy):
    """Map canonical fund_strategy values to display labels.

    Single source of truth for fund-level type display across all endpoints.
    Returns one of: 'active', 'passive', 'bond', 'excluded', 'unknown'.
    """
    if fund_strategy in ACTIVE_FUND_STRATEGIES:
        return 'active'
    if fund_strategy == 'passive':
        return 'passive'
    if fund_strategy == 'bond_or_other':
        return 'bond'
    if fund_strategy in ('excluded', 'final_filing'):
        return 'excluded'
    return 'unknown'


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
                  AND fh.is_latest = TRUE
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
                WHERE ticker = ? AND quarter = ? AND is_latest = TRUE
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

    # N-PORT month-end staleness: this function resolves the denominator at
    # calendar quarter-end derived from `quarter`. For non-quarter N-PORT
    # report months the 90-day staleness tolerance applies (see helper docs).
    denom, denom_source = _resolve_pct_of_so_denom(
        con, ticker, _quarter_to_date(quarter))

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
                MAX(fu.total_net_assets) / 1e6 AS aum_mm,
                MAX(fu.fund_strategy) AS fund_strategy
            FROM parent_patterns pp
            JOIN fund_holdings_v2 fh ON fh.family_name ILIKE pp.pattern
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE fh.ticker = ?
              AND fh.quarter = ?
              {excl_where}
              AND fh.is_latest = TRUE
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
        pct_so = round(shares * 100.0 / denom, 2) if denom and shares else None
        aum_val = r.get('aum_mm')
        aum = int(aum_val) if aum_val and aum_val > 0 else None
        pct_aum = round(float(r.get('pct_of_nav')), 2) if r.get('pct_of_nav') else None
        result.setdefault(pname, []).append({
            'institution': r.get('fund_name'),
            'value_live': r.get('value'),
            'shares': shares,
            'pct_so': pct_so,
            'pct_of_so_source': denom_source if pct_so is not None else None,
            'aum': aum,
            'pct_aum': pct_aum,
            'source': 'N-PORT',
            'fund_strategy': r.get('fund_strategy'),
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
        # Period-accurate denominator (tier cascade: SOH → md.so → md.float).
        # Anchored at calendar quarter-end derived from `quarter`; N-PORT
        # month-end staleness caveat applies (see helper docs).
        denom, denom_source = _resolve_pct_of_so_denom(
            con, ticker, _quarter_to_date(quarter))

        df = con.execute(f"""
            SELECT
                fh.fund_name,
                MAX(fh.market_value_usd) as value,
                MAX(fh.shares_or_principal) as shares,
                MAX(fh.pct_of_nav) as pct_of_nav,
                fh.series_id,
                MAX(fu.total_net_assets) / 1e6 as aum_mm,
                MAX(fu.fund_strategy) as fund_strategy
            FROM fund_holdings_v2 fh
            LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
            WHERE EXISTS (SELECT 1 FROM UNNEST([{ph}]) t(p) WHERE fh.family_name ILIKE t.p)
              AND fh.ticker = ?
              AND fh.quarter = ?
              {excl_clause}
              AND fh.is_latest = TRUE
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
            pct_so = round(shares * 100.0 / denom, 2) if denom and shares else None
            aum_val = r.get('aum_mm')
            aum = int(aum_val) if aum_val and aum_val > 0 else None
            # % of AUM/NAV: use pct_of_nav from N-PORT (position value as % of fund NAV)
            pct_aum = round(float(r.get('pct_of_nav')), 2) if r.get('pct_of_nav') else None
            result.append({'institution': r.get('fund_name'), 'value_live': r.get('value'),
                           'shares': shares, 'pct_so': pct_so,
                           'pct_of_so_source': denom_source if pct_so is not None else None,
                           'aum': aum, 'pct_aum': pct_aum, 'source': 'N-PORT',
                           'fund_strategy': r.get('fund_strategy')})
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
              AND fh.is_latest = TRUE
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
            SUM(h.pct_of_so) as pct_so
        FROM holdings_v2 h
        WHERE h.quarter = '{quarter}'
          AND (h.ticker = ? OR h.cusip = ?)
          AND COALESCE(h.{rn}, h.inst_parent_name, h.manager_name) = ?
          AND h.is_latest = TRUE
        GROUP BY h.fund_name, type
        ORDER BY value_live DESC NULLS LAST
        LIMIT {int(limit)}
    """, [ticker, cusip, inst_parent_name or '']).fetchdf()
    rows = df_to_records(df)
    return [{'institution': r.get('institution'), 'value_live': r.get('value_live'),
             'shares': r.get('shares'), 'pct_so': r.get('pct_so'),
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
              AND fh.is_latest = TRUE
            GROUP BY fh.fund_name, fh.series_id
            ORDER BY value DESC NULLS LAST
            LIMIT ?
        """, [like_param, ticker, quarter, limit]).fetchdf()

        rows = df_to_records(df)
        if not rows:
            return None

        return [{'institution': r.get('fund_name'), 'value_live': r.get('value'),
                 'shares': r.get('shares'), 'pct_so': r.get('pct_of_nav'),
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


