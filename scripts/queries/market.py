"""Sector / market-summary / short-interest queries."""
import logging

from serializers import (
    clean_for_json,
    df_to_records,
)
from .common import (
    LQ,
    VALID_ROLLUP_TYPES,
    _rollup_name_sql,
    get_db,
    _fund_type_label,
    top_parent_canonical_name_sql,
)

logger = logging.getLogger(__name__)

def get_sector_flows(active_only=False, level="parent",
                     rollup_type='economic_control_v1'):
    """Multi-quarter sector flow analysis — active money flows by GICS sector.

    Reads from the ``sector_flows_rollup`` precompute table populated by
    ``scripts/pipeline/compute_sector_flows.py`` (perf-P1). Target latency
    <50ms; previously ~1.2s scanning ``holdings_v2`` / ``fund_holdings_v2``
    on every request.

    level:        'parent' uses 13F holdings; 'fund' uses N-PORT fund holdings.
    active_only:  parent only — filter to active/hedge/activist. Ignored on
                  the fund path (matches original CTE behavior; rollup table
                  carries only active_only=FALSE rows for fund).
    rollup_type:  parent only — 'economic_control_v1' or 'decision_maker_v1'.
                  Aggregates are rollup-agnostic today (managers count
                  CIKs, not rollup entities) so EC and DM rows return
                  identical values; the parameter exists for forward
                  compatibility. Fund rows are stored under EC only.
    """
    if rollup_type not in VALID_ROLLUP_TYPES:
        raise ValueError(
            f'Invalid rollup_type: {rollup_type}. '
            f'Must be one of {VALID_ROLLUP_TYPES}'
        )
    con = get_db()
    try:
        use_nport = (level == "fund")
        source = "fund_holdings_v2" if use_nport else "holdings_v2"

        quarters = sorted([r[0] for r in con.execute(
            f"SELECT DISTINCT quarter FROM {source} "  # nosec B608
            f"WHERE quarter IS NOT NULL ORDER BY quarter"
        ).fetchall()])
        if len(quarters) < 2:
            return {"periods": [], "sectors": []}
        pairs = [(quarters[i], quarters[i + 1])
                 for i in range(len(quarters) - 1)]

        # Fund rows always stored under (EC, active_only=FALSE).
        # Parent rows respect both rollup_type and active_only.
        if use_nport:
            row_active_only = False
            row_rollup_type = 'economic_control_v1'
        else:
            row_active_only = bool(active_only)
            row_rollup_type = rollup_type

        df = con.execute(
            """
            SELECT quarter_from, quarter_to, gics_sector AS sector,
                   net, inflow, outflow,
                   new_positions, exits, managers
              FROM sector_flows_rollup
             WHERE level = ?
               AND rollup_type = ?
               AND active_only = ?
               AND gics_sector NOT IN ('', 'Derivative', 'ETF')
               AND gics_sector IS NOT NULL
            """,
            [level, row_rollup_type, row_active_only],
        ).fetchdf()

        all_flows = {}
        for row in df.to_dict(orient="records"):
            sector = row["sector"]
            pk = f"{row['quarter_from']}_{row['quarter_to']}"
            if sector not in all_flows:
                all_flows[sector] = {}
            all_flows[sector][pk] = {
                "net": row.get("net"),
                "inflow": row.get("inflow"),
                "outflow": row.get("outflow"),
                "new_positions": row.get("new_positions"),
                "exits": row.get("exits"),
                "managers": row.get("managers"),
            }

        periods = [{"label": f"{qf} → {qt}", "from": qf, "to": qt}
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

def get_sector_summary():
    """Market-wide totals for the latest quarter — used by Sector Rotation
    KPI row. Always total market; ignores active/passive filters and rollup
    type. Reads ``holdings_v2`` for the latest quarter where
    ``is_latest = TRUE``.

    Returns:
        quarter, total_aum, total_holders, type_breakdown — an array of
        {type, pct_aum, aum} sorted by pct_aum desc, one entry per distinct
        manager_type in the latest quarter (pct as 0–100 percent).
    """
    con = get_db()
    tpn = top_parent_canonical_name_sql('h')
    try:
        head = con.execute(
            f"""
            WITH latest AS (
                SELECT MAX(quarter) AS q FROM holdings_v2 WHERE is_latest = TRUE
            )
            SELECT (SELECT q FROM latest) AS quarter,
                   SUM(h.market_value_usd) AS total_aum,
                   COUNT(DISTINCT {tpn}) AS total_holders
              FROM holdings_v2 h, latest
             WHERE h.quarter = latest.q AND h.is_latest = TRUE
            """
        ).fetchone()
        quarter, total_aum, total_holders = head
        total_aum = float(total_aum or 0)
        denom = total_aum if total_aum > 0 else None

        rows = con.execute(
            """
            WITH latest AS (
                SELECT MAX(quarter) AS q FROM holdings_v2 WHERE is_latest = TRUE
            )
            SELECT manager_type, SUM(market_value_usd) AS aum
              FROM holdings_v2, latest
             WHERE holdings_v2.quarter = latest.q AND is_latest = TRUE
             GROUP BY manager_type
             ORDER BY aum DESC
            """
        ).fetchall()
        type_breakdown = []
        for mt, aum in rows:
            aum_f = float(aum or 0)
            type_breakdown.append({
                "type": mt or "unknown",
                "aum": aum_f,
                "pct_aum": (aum_f / denom * 100.0) if denom else 0.0,
            })

        return clean_for_json({
            "quarter": quarter,
            "total_aum": total_aum,
            "total_holders": int(total_holders or 0),
            "type_breakdown": type_breakdown,
        })
    finally:
        pass


def get_fund_quarter_completeness():
    """Per-quarter monthly filing completeness for fund_holdings_v2.

    Returns one row per quarter with the count of distinct report_month
    values present, plus a ``complete`` flag (True iff all 3 months are
    filed). Drives the Sector Rotation tab's Fund-view filter to hide
    partial-quarter destination periods that would otherwise underreport
    flows.
    """
    con = get_db()
    try:
        rows = con.execute(
            """
            SELECT quarter,
                   COUNT(DISTINCT report_month) AS months_available
              FROM fund_holdings_v2
             WHERE quarter IS NOT NULL
             GROUP BY quarter
             ORDER BY quarter
            """
        ).fetchall()
        return [
            {
                "quarter": q,
                "months_available": int(m),
                "complete": int(m) == 3,
            }
            for q, m in rows
        ]
    finally:
        pass


def get_sector_monthly_flows(sector, quarter):
    """Monthly net active flows for one (sector, quarter) at fund level.

    For each report month in the requested filing quarter, computes the
    net flow contribution from funds that filed N-PORTs in BOTH the
    current month and the immediately preceding calendar month, summing
    delta_shares × implied price per (institution, ticker) where the
    ticker maps to ``sector`` via ``market_data``. Funds present in only
    one of the two months are excluded — most N-PORT filers report just
    once per quarter, so a missing month is a non-filing rather than an
    exit, and treating it as an exit produces spurious trillion-dollar
    swings.

    Months are derived from ``fund_holdings_v2`` rather than from the
    quarter label because N-PORT report months trail the filing quarter
    by one period (e.g. quarter='2026Q1' contains report_months
    2025-10/11/12).

    Drives the Sector Rotation tab's Fund-view tooltip drill-down on
    quarterly heatmap cells.
    """
    if not quarter or not sector:
        return {"sector": sector, "quarter": quarter, "months": []}

    con = get_db()
    try:
        months = [r[0] for r in con.execute(
            """
            SELECT DISTINCT report_month
              FROM fund_holdings_v2
             WHERE quarter = ?
               AND report_month IS NOT NULL
             ORDER BY report_month
            """, [quarter],
        ).fetchall()]

        if not months:
            return {"sector": sector, "quarter": quarter, "months": []}

        def prev_calendar_month(m):
            y, mm = int(m[:4]), int(m[5:7])
            if mm == 1:
                return f"{y - 1}-12"
            return f"{y}-{mm - 1:02d}"

        # Build (prev, curr) pairs — first month chains off the calendar
        # month immediately preceding it; subsequent months chain off
        # their predecessor in the quarter.
        pairs = []
        for i, m_to in enumerate(months):
            m_from = months[i - 1] if i > 0 else prev_calendar_month(m_to)
            pairs.append((m_from, m_to))

        results = []
        for m_from, m_to in pairs:
            row = con.execute(
                """
                WITH h_agg AS (
                    SELECT COALESCE(family_name, fund_name) AS institution,
                           ticker, report_month,
                           SUM(shares_or_principal) AS shares,
                           SUM(market_value_usd) AS market_value_usd
                      FROM fund_holdings_v2
                     WHERE ticker IS NOT NULL
                       AND asset_category IN ('EC','EP')
                       AND shares_or_principal > 0
                       AND report_month IN (?, ?)
                       AND is_latest = TRUE
                     GROUP BY institution, ticker, report_month
                ),
                paired_filers AS (
                    -- Restrict to (institution, ticker) pairs present in
                    -- BOTH months. Missing-month rows are non-filings,
                    -- not exits, so we cannot attribute flow to them.
                    SELECT c.institution, c.ticker,
                           c.shares AS curr_shares,
                           c.market_value_usd AS curr_mv,
                           p.shares AS prev_shares
                      FROM h_agg c
                      JOIN h_agg p
                        ON c.institution = p.institution
                       AND c.ticker = p.ticker
                       AND p.report_month = ?
                      JOIN market_data md
                        ON c.ticker = md.ticker AND md.sector = ?
                     WHERE c.report_month = ?
                )
                SELECT SUM(
                    (curr_shares - prev_shares)
                    * (curr_mv * 1.0 / NULLIF(curr_shares, 0))
                ) AS net
                  FROM paired_filers
                """,
                [m_from, m_to, m_from, sector, m_to],
            ).fetchone()
            net = float(row[0]) if row and row[0] is not None else 0.0
            results.append({"month": m_to, "net": net})
        return clean_for_json({
            "sector": sector,
            "quarter": quarter,
            "months": results,
        })
    finally:
        pass


def get_sector_flow_movers(q_from, q_to, sector, active_only=False, level="parent", rollup_type='economic_control_v1'):
    """Top 5 net buyers + top 5 net sellers for one sector in one quarter
    transition. Returns summary stats + two lists.

    level='parent' reads from the ``peer_rotation_flows`` precompute table
    (perf-P0; rebuilt per quarter by ``compute_peer_rotation.py``). Each
    row already aggregates one entity's net active flow into one ticker
    for one (q_from, q_to, sector, level, rollup_type) bucket, so this
    function only needs to GROUP BY entity and pick the top/bottom 5.
    Target latency <200ms; previously ~340-405ms scanning ``holdings_v2``
    on every request.

    Parity divergence vs the pre-perf-P1 implementation (parent only):

      * ``summary.net`` and per-institution ``net_flow`` match exactly —
        net is preserved under any GROUP BY granularity.
      * ``summary.buyers`` / ``summary.sellers`` (counts) match exactly.
      * Top-5 ranking by net_flow matches exactly (institution name and
        value).
      * ``summary.inflow`` / ``summary.outflow`` and per-institution
        ``buying`` / ``selling`` shift ~1% on average. The pre-perf-P1
        SQL summed positive/negative active_flow at the (CIK, ticker)
        granularity; ``peer_rotation_flows`` pre-aggregates per
        (entity, ticker), collapsing internal sub-CIK offsetting flows.
        Net flow per institution is unchanged but gross buying / selling
        components shrink. The size of the shift scales with how
        aggressively the institution's sub-managers trade against each
        other — small for single-CIK institutions, larger for
        multi-CIK rollups (e.g., Nomura, Vanguard).
      * ``positions_changed`` differs slightly because the precompute's
        ``HAVING SUM(active_flow) IS NOT NULL`` excludes (entity, ticker)
        pairs whose flows degenerated to NULL (typically c.shares=0
        cases that survived h_agg). Same physical positions; the
        precompute simply doesn't carry zero-row carriers.

    int-22 follow-on — the pre-rewrite SQL referenced ``c.entity_type``
    on a CTE that did not project the column, raising
    ``BinderException`` whenever ``active_only=True`` was passed.
    Production never observed it because the only caller passed False.
    The new path reads ``entity_type`` directly off
    ``peer_rotation_flows`` and supports ``active_only=True`` correctly.

    level='fund' keeps the original ``holdings_v2`` query (groups by
    ``cik|manager_name`` rather than rollup entity — perf-P0 stores fund
    rows under series_id/fund_name, a different definition of "fund"
    that does not align with the per-filer aggregation this endpoint
    uses for the fund branch). The fund-path BinderException on
    active_only=True is preserved as-is for that branch — no caller in
    the current API uses level='fund' + active_only=True.
    """
    if rollup_type not in VALID_ROLLUP_TYPES:
        raise ValueError(
            f'Invalid rollup_type: {rollup_type}. '
            f'Must be one of {VALID_ROLLUP_TYPES}'
        )
    con = get_db()
    try:
        if level == "parent":
            active_clause = (
                "AND entity_type IN ('active', 'hedge_fund', 'activist')"
                if active_only else ""
            )
            df = con.execute(f"""
                SELECT entity AS institution,
                       SUM(active_flow) AS net_flow,
                       COUNT(DISTINCT ticker) AS positions_changed,
                       SUM(CASE WHEN active_flow > 0 THEN active_flow ELSE 0 END) AS buying,
                       SUM(CASE WHEN active_flow < 0 THEN active_flow ELSE 0 END) AS selling
                  FROM peer_rotation_flows
                 WHERE quarter_from = ?
                   AND quarter_to = ?
                   AND sector = ?
                   AND level = 'parent'
                   AND rollup_type = ?
                   {active_clause}
                 GROUP BY entity
                HAVING ABS(SUM(active_flow)) > 0
                 ORDER BY net_flow DESC
            """, [q_from, q_to, sector, rollup_type]).fetchdf()  # nosec B608 — active_clause built from a constant

            records = df_to_records(df)
        else:
            # level='fund' — query fund_holdings_v2 (N-PORT). Group by
            # family_name (fall back to fund_name) as the institution. Active
            # flow = delta_shares * implied_price; exits = -prior_value.
            df = con.execute(f"""
                WITH h_agg AS (
                    SELECT COALESCE(family_name, fund_name) AS institution,
                           ticker, quarter,
                           SUM(shares_or_principal) AS shares,
                           SUM(market_value_usd) AS market_value_usd
                    FROM fund_holdings_v2
                    WHERE ticker IS NOT NULL
                      AND asset_category IN ('EC','EP')
                      AND shares_or_principal > 0
                      AND quarter IN ('{q_from}', '{q_to}')
                      AND is_latest = TRUE
                    GROUP BY institution, ticker, quarter
                ),
                flows AS (
                    SELECT c.institution,
                           c.ticker,
                           (c.shares - COALESCE(p.shares, 0))
                             * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                    FROM h_agg c
                    LEFT JOIN h_agg p
                        ON c.institution = p.institution AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                    JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                    WHERE c.quarter = '{q_to}'

                    UNION ALL

                    SELECT p.institution,
                           p.ticker,
                           -p.market_value_usd AS active_flow
                    FROM h_agg p
                    LEFT JOIN h_agg c
                        ON p.institution = c.institution AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                    JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                    WHERE p.quarter = '{q_from}' AND c.institution IS NULL
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


def get_sector_flow_mover_detail(q_from, q_to, sector, institution,
                                 active_only=False, level="parent",
                                 rollup_type='economic_control_v1'):
    """Top 5 individual ticker moves making up one institution's net flow
    inside a sector for one quarter transition. Drives the click-through
    drill-down on the Sector Rotation movers panel.

    level='parent' reads ``peer_rotation_flows`` (already aggregated to
    one row per (entity, ticker, sector, period)).
    level='fund'   reads ``fund_holdings_v2`` and computes active_flow on
    the fly, mirroring the fund-level movers query.

    Returns: { sector, period, institution, level, rows: [{ticker,
    company_name, net_flow, shares_changed}] } where rows are sorted by
    abs(net_flow) desc, top 5.
    """
    if rollup_type not in VALID_ROLLUP_TYPES:
        raise ValueError(
            f'Invalid rollup_type: {rollup_type}. '
            f'Must be one of {VALID_ROLLUP_TYPES}'
        )
    con = get_db()
    try:
        if level == "parent":
            active_clause = (
                "AND prf.entity_type IN ('active', 'hedge_fund', 'activist')"
                if active_only else ""
            )
            df = con.execute(f"""
                SELECT prf.ticker AS ticker,
                       MAX(s.issuer_name) AS company_name,
                       SUM(prf.active_flow) AS net_flow,
                       NULL::DOUBLE AS shares_changed
                  FROM peer_rotation_flows prf
                  LEFT JOIN securities s ON prf.ticker = s.ticker
                 WHERE prf.quarter_from = ?
                   AND prf.quarter_to = ?
                   AND prf.sector = ?
                   AND prf.level = 'parent'
                   AND prf.rollup_type = ?
                   AND prf.entity = ?
                   {active_clause}
                 GROUP BY prf.ticker
                HAVING ABS(SUM(prf.active_flow)) > 0
                 ORDER BY ABS(SUM(prf.active_flow)) DESC
                 LIMIT 5
            """, [q_from, q_to, sector, rollup_type, institution]).fetchdf()  # nosec B608
        else:
            # level='fund' — recompute from fund_holdings_v2.
            df = con.execute(f"""
                WITH h_agg AS (
                    SELECT COALESCE(family_name, fund_name) AS institution,
                           ticker, quarter,
                           SUM(shares_or_principal) AS shares,
                           SUM(market_value_usd) AS market_value_usd
                    FROM fund_holdings_v2
                    WHERE ticker IS NOT NULL
                      AND asset_category IN ('EC','EP')
                      AND shares_or_principal > 0
                      AND quarter IN ('{q_from}', '{q_to}')
                      AND is_latest = TRUE
                    GROUP BY institution, ticker, quarter
                ),
                flows AS (
                    SELECT c.institution, c.ticker,
                           (c.shares - COALESCE(p.shares, 0)) AS shares_changed,
                           (c.shares - COALESCE(p.shares, 0))
                             * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
                    FROM h_agg c
                    LEFT JOIN h_agg p
                        ON c.institution = p.institution AND c.ticker = p.ticker AND p.quarter = '{q_from}'
                    JOIN market_data md ON c.ticker = md.ticker AND md.sector = ?
                    WHERE c.quarter = '{q_to}' AND c.institution = ?

                    UNION ALL

                    SELECT p.institution, p.ticker,
                           -p.shares AS shares_changed,
                           -p.market_value_usd AS active_flow
                    FROM h_agg p
                    LEFT JOIN h_agg c
                        ON p.institution = c.institution AND p.ticker = c.ticker AND c.quarter = '{q_to}'
                    JOIN market_data md ON p.ticker = md.ticker AND md.sector = ?
                    WHERE p.quarter = '{q_from}' AND c.institution IS NULL AND p.institution = ?
                )
                SELECT f.ticker AS ticker,
                       MAX(s.issuer_name) AS company_name,
                       SUM(f.active_flow) AS net_flow,
                       SUM(f.shares_changed) AS shares_changed
                  FROM flows f
                  LEFT JOIN securities s ON f.ticker = s.ticker
                 GROUP BY f.ticker
                HAVING ABS(SUM(f.active_flow)) > 0
                 ORDER BY ABS(SUM(f.active_flow)) DESC
                 LIMIT 5
            """, [sector, institution, sector, institution]).fetchdf()  # nosec B608

        return clean_for_json({
            "sector": sector,
            "period": {"from": q_from, "to": q_to},
            "institution": institution,
            "level": level,
            "rows": df_to_records(df),
        })
    finally:
        pass


def short_interest_analysis(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Comprehensive short interest analysis for a ticker.
    Combines N-PORT fund-level shorts, FINRA daily volume, and long/short cross-reference.
    """
    rn = _rollup_name_sql('', rollup_type)
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
                    WHERE ticker = ? AND shares_or_principal < 0 AND is_latest = TRUE
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
        except Exception:
            logger.debug("optional enrichment failed: nport_trend", exc_info=True)
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
                       MAX(fund_strategy) as fund_strategy
                FROM (
                    SELECT fh.fund_name, fh.family_name,
                           fh.shares_or_principal, fh.market_value_usd,
                           fh.quarter, fh.series_id,
                           fu.total_net_assets / 1e6 as fund_aum_mm,
                           fu.fund_strategy as fund_strategy
                    FROM fund_holdings_v2 fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.ticker = ? AND fh.shares_or_principal < 0
                      AND fh.quarter = '{quarter}'
                      AND fh.is_latest = TRUE
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
                r['type'] = _fund_type_label(r.get('fund_strategy'))
                r.pop('fund_strategy', None)
        except Exception:
            logger.debug("optional enrichment failed: nport_detail", exc_info=True)
        result['nport_detail'] = nport_detail

        # 3. N-PORT short positions history per fund — dedupe by (fund_name, quarter)
        nport_by_fund = []
        try:
            fund_hist = con.execute("""
                SELECT fh.fund_name, fh.quarter,
                       SUM(ABS(fh.shares_or_principal)) as short_shares,
                       MAX(fu.fund_strategy) as fund_strategy
                FROM fund_holdings_v2 fh
                LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                WHERE fh.ticker = ? AND fh.shares_or_principal < 0 AND fh.is_latest = TRUE
                GROUP BY fh.fund_name, fh.quarter
                ORDER BY fh.fund_name, fh.quarter
            """, [ticker]).fetchdf()
            # Pivot: fund → {quarter: shares, type}
            funds_seen = {}
            for _, r in fund_hist.iterrows():
                fn = r['fund_name']
                if fn not in funds_seen:
                    funds_seen[fn] = {'fund_name': fn,
                                      'type': _fund_type_label(r.get('fund_strategy'))}
                funds_seen[fn][r['quarter']] = float(r['short_shares'])
            nport_by_fund = list(funds_seen.values())
            nport_by_fund.sort(key=lambda x: x.get(quarter, 0), reverse=True)
        except Exception:
            logger.debug("optional enrichment failed: nport_by_fund", exc_info=True)
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
            logger.debug("optional enrichment failed: short_volume", exc_info=True)
        result['short_volume'] = short_volume

        # 5. Long/short cross-reference — institutions both long and short
        cross_ref = []
        try:
            # Long from 13F
            long_df = con.execute(f"""
                SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent,
                       SUM(shares) as long_shares, SUM(market_value_live) as long_value,
                       MAX(manager_type) as manager_type
                FROM holdings_v2 WHERE ticker = ? AND quarter = '{quarter}' AND is_latest = TRUE
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
                    WHERE ticker = ? AND shares_or_principal < 0 AND quarter = '{quarter}' AND is_latest = TRUE
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
        except Exception:
            logger.debug("optional enrichment failed: cross_ref", exc_info=True)
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
                       MAX(fund_strategy) as fund_strategy
                FROM (
                    SELECT fh.fund_name, fh.family_name, fh.series_id,
                           SUM(ABS(fh.shares_or_principal)) as short_shares,
                           SUM(ABS(fh.market_value_usd)) as short_value,
                           MAX(fu.total_net_assets) / 1e6 as fund_aum_mm,
                           MAX(fu.fund_strategy) as fund_strategy
                    FROM fund_holdings_v2 fh
                    LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
                    WHERE fh.ticker = ? AND fh.shares_or_principal < 0 AND fh.quarter = '{quarter}' AND fh.is_latest = TRUE
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
                        'type': _fund_type_label(r.get('fund_strategy')),
                        'short_shares': ss,
                        'short_value': sv,
                        'fund_aum_mm': float(r['fund_aum_mm'] or 0) if r['fund_aum_mm'] else None,
                    })
        except Exception:
            logger.debug("optional enrichment failed: short_only_funds", exc_info=True)
        result['short_only_funds'] = short_only

        # 8. Summary card data
        total_short_shares = sum(r.get(quarter, 0) for r in nport_by_fund)
        avg_short_vol = sum(r.get('short_pct', 0) for r in short_volume[-20:]) / max(len(short_volume[-20:]), 1) if short_volume else 0

        # Distinct series_id count using SEC payoff_profile = 'Short' (latest)
        try:
            short_funds_count_row = con.execute("""
                SELECT COUNT(DISTINCT series_id)
                FROM fund_holdings_v2
                WHERE ticker = ? AND payoff_profile = 'Short' AND is_latest = TRUE
            """, [ticker]).fetchone()
            short_funds_count = int(short_funds_count_row[0]) if short_funds_count_row and short_funds_count_row[0] else 0
        except Exception:
            logger.debug("short_funds_count failed", exc_info=True)
            short_funds_count = 0

        # Market data for SI%SO + days-to-cover
        so = None
        avg_vol_30d = None
        try:
            md_row = con.execute(
                "SELECT shares_outstanding, avg_volume_30d FROM market_data WHERE ticker = ?",
                [ticker]
            ).fetchone()
            if md_row:
                so = float(md_row[0]) if md_row[0] else None
                avg_vol_30d = float(md_row[1]) if md_row[1] else None
        except Exception:
            logger.debug("market_data lookup failed", exc_info=True)

        # SI % SO from latest short_interest report + days-to-cover proxy
        si_pct_so = None
        latest_short_volume = None
        try:
            si_row = con.execute("""
                SELECT short_volume FROM short_interest
                WHERE ticker = ? ORDER BY report_date DESC LIMIT 1
            """, [ticker]).fetchone()
            if si_row and si_row[0]:
                latest_short_volume = float(si_row[0])
                if so and so > 0:
                    si_pct_so = round(latest_short_volume / so * 100, 2)
        except Exception:
            logger.debug("si_pct_so lookup failed", exc_info=True)

        short_value_total = (total_short_shares * live_price) if (live_price and total_short_shares) else 0
        days_to_cover = (
            round(latest_short_volume / avg_vol_30d, 1)
            if (latest_short_volume and avg_vol_30d and avg_vol_30d > 0)
            else None
        )

        result['summary'] = {
            'short_funds': short_funds_count,
            'short_shares': total_short_shares,
            'short_value': short_value_total,
            'days_to_cover': days_to_cover,
            'si_pct_so': si_pct_so,
            'avg_short_vol_pct': round(avg_short_vol, 1),
            'cross_ref_count': len(cross_ref),
            'quarters_available': [q.get('quarter') for q in nport_trend],
        }

        return clean_for_json(result)
    finally:
        pass


def get_short_position_pct(ticker):
    """Quarterly fund-level short positions as % of shares outstanding.

    Returns the ticker's series alongside sector and industry averages
    (averaged across tickers per quarter) for overlay on a bar chart.
    """
    con = get_db()
    sector_name = None
    industry_name = None
    md = con.execute(
        "SELECT sector, industry, shares_outstanding FROM market_data WHERE ticker = ?",
        [ticker]
    ).fetchone()
    if md:
        sector_name = md[0]
        industry_name = md[1]
        ticker_so = float(md[2]) if md[2] else None
    else:
        ticker_so = None

    # Ticker's quarterly short shares
    ticker_data = []
    if ticker_so and ticker_so > 0:
        rows = con.execute("""
            SELECT quarter, SUM(ABS(shares_or_principal)) as short_shares
            FROM fund_holdings_v2
            WHERE ticker = ? AND payoff_profile = 'Short' AND is_latest = TRUE
            GROUP BY quarter ORDER BY quarter
        """, [ticker]).fetchall()
        ticker_data = [
            {'quarter': r[0], 'pct': round(float(r[1]) / ticker_so * 100, 4)}
            for r in rows if r[1]
        ]

    def _peer_avg(filter_col, filter_val):
        if not filter_val:
            return []
        try:
            rows = con.execute(f"""
                WITH per_ticker AS (
                    SELECT fh.quarter, fh.ticker,
                           SUM(ABS(fh.shares_or_principal)) AS short_shares,
                           MAX(md.shares_outstanding) AS so
                    FROM fund_holdings_v2 fh
                    JOIN market_data md ON fh.ticker = md.ticker
                    WHERE md.{filter_col} = ?
                      AND fh.payoff_profile = 'Short'
                      AND fh.is_latest = TRUE
                      AND md.shares_outstanding IS NOT NULL
                      AND md.shares_outstanding > 0
                    GROUP BY fh.quarter, fh.ticker
                )
                SELECT quarter, AVG(short_shares / so) * 100 as pct
                FROM per_ticker
                WHERE short_shares > 0
                GROUP BY quarter ORDER BY quarter
            """, [filter_val]).fetchall()  # nosec B608
            return [{'quarter': r[0], 'pct': round(float(r[1]), 4)} for r in rows if r[1]]
        except Exception:
            logger.debug("peer avg failed for %s=%s", filter_col, filter_val, exc_info=True)
            return []

    return clean_for_json({
        'ticker_data': ticker_data,
        'sector_avg': _peer_avg('sector', sector_name),
        'industry_avg': _peer_avg('industry', industry_name),
        'sector_name': sector_name,
        'industry_name': industry_name,
    })


def get_short_volume_comparison(ticker):
    """Daily FINRA short volume % for a ticker plus sector/industry medians.

    Each series shares the same date axis from the short_interest table.
    """
    con = get_db()
    sector_name = None
    industry_name = None
    md = con.execute(
        "SELECT sector, industry FROM market_data WHERE ticker = ?",
        [ticker]
    ).fetchone()
    if md:
        sector_name = md[0]
        industry_name = md[1]

    ticker_rows = con.execute("""
        SELECT report_date, short_pct
        FROM short_interest
        WHERE ticker = ? ORDER BY report_date
    """, [ticker]).fetchall()
    ticker_data = [
        {'date': str(r[0]), 'pct': round(float(r[1]), 2)}
        for r in ticker_rows if r[1] is not None
    ]

    def _peer_median(filter_col, filter_val):
        if not filter_val:
            return []
        try:
            rows = con.execute(f"""
                SELECT si.report_date,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY si.short_pct) AS median_pct
                FROM short_interest si
                JOIN market_data md ON si.ticker = md.ticker
                WHERE md.{filter_col} = ?
                  AND si.short_pct IS NOT NULL
                GROUP BY si.report_date
                ORDER BY si.report_date
            """, [filter_val]).fetchall()  # nosec B608
            return [
                {'date': str(r[0]), 'pct': round(float(r[1]), 2)}
                for r in rows if r[1] is not None
            ]
        except Exception:
            logger.debug("peer median failed for %s=%s", filter_col, filter_val, exc_info=True)
            return []

    return clean_for_json({
        'ticker_data': ticker_data,
        'sector_median': _peer_median('sector', sector_name),
        'industry_median': _peer_median('industry', industry_name),
        'sector_name': sector_name,
        'industry_name': industry_name,
    })


# Map query number to function


def get_market_summary(limit=25, quarter=LQ, rollup_type='economic_control_v1'):
    """Top N institutions by total 13F holdings value (market-wide).

    Returns a ranked list with AUM, filer count, and fund count per
    institution. Uses holdings_v2 for AUM (avoids polluted managers.aum_total),
    entity_relationships for filer count, and fund children for fund count.

    rollup_type is applied to the summary_by_parent coverage lookup so the
    returned nport_coverage_pct matches the caller's rollup (INF34 sweep).
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
                WHERE quarter = '{quarter}' AND is_latest = TRUE
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
            except Exception:
                logger.debug("optional enrichment failed: entity_id_lookup", exc_info=True)
                r['entity_id'] = None
                r['filer_count'] = r['num_ciks']
                r['fund_count'] = 0

            # N-PORT coverage from summary_by_parent
            # INF34: filter on rollup_type (one row per rollup since migration 004).
            try:
                cov = con.execute(f"""
                    SELECT nport_coverage_pct
                    FROM summary_by_parent
                    WHERE inst_parent_name = ? AND quarter = '{quarter}'
                      AND rollup_type = ?
                """, [r['institution'], rollup_type]).fetchone()
                r['nport_coverage_pct'] = cov[0] if cov and cov[0] is not None else None
            except Exception:
                logger.debug("optional enrichment failed: nport_coverage_lookup", exc_info=True)
                r['nport_coverage_pct'] = None

        return clean_for_json(rows)
    finally:
        pass  # connection managed by thread-local cache


# ---------------------------------------------------------------------------
# Peer Rotation — per-ticker substitution analysis within sector
# ---------------------------------------------------------------------------
