"""queries package — split from the original scripts/queries.py monolith.

Domain modules:
  - common   : shared DB / NPORT helpers
  - register : query1..query16 + summary
  - fund     : portfolio_context
  - flows    : flow_analysis + cohort_analysis
  - market   : sector_flows / market_summary / short_interest
  - cross    : cross-ownership + two-company overlap
  - trend    : holder_momentum + ownership_trend + peer_rotation
  - entities : entity graph

This __init__ re-exports every public name so existing
`from queries import X` imports keep working unchanged.
"""

# --- common surface (DB wrappers, helpers, logger) -----------------------
from .common import (  # noqa: F401
    # state setup
    _setup,
    get_db,
    has_table,
    # rollup
    VALID_ROLLUP_TYPES,
    _rollup_name_sql,
    _rollup_eid_sql,
    LQ, FQ, PQ,
    # quarter helpers
    _QUARTER_END_DATES,
    _quarter_to_date,
    # pct_of_so + cusip
    _resolve_pct_of_so_denom,
    get_cusip,
    # NPORT family-pattern helpers
    _FAMILY_PATTERNS_FALLBACK,
    get_nport_family_patterns,
    _fund_type_label,
    match_nport_family,
    _get_subadviser_exclusions,
    get_nport_position,
    get_nport_coverage,
    _build_excl_clause,
    get_nport_children_batch,
    get_nport_children,
    get_nport_children_q2,
    get_13f_children,
    get_nport_children_ncen,
    get_children,
    # logger
    logger,
)

# --- serializers re-exports (preserve `from queries import clean_for_json` etc.)
from serializers import (  # noqa: F401
    clean_for_json,
    df_to_records,
    resolve_filer_names_in_records,
    _13f_entity_footnote,
    get_subadviser_note,
)

# --- cache re-exports ----------------------------------------------------
from cache import (  # noqa: F401
    cached,
    CACHE_KEY_SUMMARY,
    CACHE_KEY_COHORT,
    CACHE_TTL_COHORT,
)

# --- register --------------------------------------------------------------
from .register import (  # noqa: F401
    query1, query2, query3, query4, query5, query6, query7, query8,
    query9, query10, query11, query12, query14, query15, query16,
    QUERY_FUNCTIONS, QUERY_NAMES,
    get_summary, _get_summary_impl,
)

# --- fund -----------------------------------------------------------------
from .fund import (  # noqa: F401
    portfolio_context,
    _gics_sector,
    _YF_TO_GICS,
)

# --- flows ----------------------------------------------------------------
from .flows import (  # noqa: F401
    _build_cohort,
    cohort_analysis,
    _cohort_analysis_impl,
    _compute_flows_live,
    flow_analysis,
)

# --- market ---------------------------------------------------------------
from .market import (  # noqa: F401
    get_sector_flows,
    get_sector_flow_movers,
    get_sector_flow_mover_detail,
    get_sector_summary,
    get_fund_quarter_completeness,
    get_sector_monthly_flows,
    short_interest_analysis,
    get_short_position_pct,
    get_short_volume_comparison,
    get_market_summary,
)

# --- cross ----------------------------------------------------------------
from .cross import (  # noqa: F401
    _cross_ownership_query,
    get_two_company_overlap,
    get_two_company_subject,
    get_overlap_institution_detail,
    get_cross_ownership_fund_detail,
)

# --- trend ----------------------------------------------------------------
from .trend import (  # noqa: F401
    holder_momentum,
    ownership_trend_summary,
    _ACTIVE_PARENT_TYPES,
    _ACTIVE_FUND_TYPES,
    get_peer_rotation,
    get_peer_rotation_detail,
)

# --- entities -------------------------------------------------------------
from .entities import (  # noqa: F401
    search_entity_parents,
    get_entity_by_id,
    get_entity_cik,
    compute_aum_by_cik,
    compute_aum_for_subtree,
    get_entity_filer_children,
    get_entity_fund_children,
    get_entity_sub_advisers,
    get_institution_hierarchy,
    build_entity_graph,
    _eg_node_institution,
    _eg_node_filer,
    _eg_node_fund,
    _eg_node_sub_adviser,
    _eg_edge,
    _eg_fmt_aum_label,
)
