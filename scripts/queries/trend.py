"""Holder momentum, ownership trend, peer rotation queries."""
import math

import pandas as pd

from config import (
    QUARTERS,
)
from serializers import (
    clean_for_json,
    df_to_records,
)
from .common import (
    LQ,
    _rollup_col,
    get_db,
    has_table,
    _quarter_to_date,
    _resolve_pct_of_so_denom,
    get_cusip,
    _classify_fund_type,
    match_nport_family,
    _build_excl_clause,
)



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
                WHERE fh.ticker = ? AND fh.quarter = '{quarter}' {af} AND fh.is_latest = TRUE
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
                  AND is_latest = TRUE
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

        # --- Parent-level branch ---
        # rollup_entity_id column on holdings_v2 mirrors `rn` (the rollup
        # name column). Used to JOIN against parent_fund_map below.
        eid_col = (
            'dm_rollup_entity_id' if rollup_type == 'decision_maker_v1'
            else 'rollup_entity_id'
        )

        # Top 25 parents by latest quarter value. Also fetch the rollup
        # entity_id so the parent_fund_map JOIN below avoids a name->eid
        # lookup. parents without a rollup_entity_id (the COALESCE fallback
        # to inst_parent_name / manager_name) carry eid=None and fall
        # through to the legacy ILIKE path inside _get_fund_children.
        top_df = con.execute(f"""
            SELECT COALESCE({rn}, inst_parent_name, manager_name) as parent_name,
                   MAX({eid_col}) as rollup_eid,
                   SUM(market_value_live) as parent_val
            FROM holdings_v2
            WHERE quarter = '{quarter}' AND (ticker = ? OR cusip = ?) AND is_latest = TRUE
            GROUP BY parent_name
            ORDER BY parent_val DESC NULLS LAST
            LIMIT 25
        """, [ticker, cusip]).fetchdf()

        if top_df.empty:
            return []

        top_parents = top_df['parent_name'].tolist()
        parent_eids = {
            row['parent_name']: (
                int(row['rollup_eid']) if pd.notna(row['rollup_eid']) else None
            )
            for _, row in top_df.iterrows()
        }

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
              AND is_latest = TRUE
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

        pfm_available = has_table('parent_fund_map')

        # Batched fund-children lookup (perf-P2): one SQL fetches every
        # parent's N-PORT fund children at once. Replaces the 25 sequential
        # per-parent ILIKE queries (728ms / 91% of pre-rewrite latency).
        # parent_fund_map provides (rollup_entity_id → series_id, quarter);
        # JOIN to fund_holdings_v2 on (series_id, quarter) returns share
        # totals for the subject ticker across all quarters in one round-trip.
        eids_with_rollups = [
            parent_eids[p] for p in top_parents if parent_eids.get(p) is not None
        ]
        children_by_parent: dict[str, pd.DataFrame] = {}
        if pfm_available and eids_with_rollups:
            try:
                eid_ph = ','.join(['?'] * len(eids_with_rollups))
                batch_df = con.execute(f"""
                    SELECT pfm.rollup_entity_id AS eid,
                           fh.fund_name,
                           fh.quarter,
                           MAX(fh.shares_or_principal) AS shares,
                           fh.series_id
                      FROM parent_fund_map pfm
                      JOIN fund_holdings_v2 fh
                        ON fh.series_id = pfm.series_id
                       AND fh.quarter   = pfm.quarter
                     WHERE pfm.rollup_entity_id IN ({eid_ph})
                       AND pfm.rollup_type = ?
                       AND fh.ticker = ?
                       AND fh.quarter IN ({q_placeholders})
                       AND fh.is_latest = TRUE
                     GROUP BY pfm.rollup_entity_id, fh.fund_name, fh.quarter, fh.series_id
                """, eids_with_rollups + [rollup_type, ticker]).fetchdf()
                if not batch_df.empty:
                    for eid_val, group in batch_df.groupby('eid'):
                        children_by_parent[int(eid_val)] = group
            except Exception:
                children_by_parent = {}

        def _get_fund_children(pname, rollup_eid):
            """Return up to 10 child fund rows for ``pname`` shaped as
            ``[{'fund_name': str, 'quarters': {q: shares}}]``.
            Resolves from the batched parent_fund_map result when
            ``rollup_eid`` is populated; falls back to the legacy
            per-call ILIKE path otherwise."""
            fund_df = None
            try:
                if rollup_eid is not None and rollup_eid in children_by_parent:
                    fund_df = children_by_parent[rollup_eid]
                elif not pfm_available or rollup_eid is None:
                    patterns = match_nport_family(pname)
                    if not patterns:
                        return []
                    like_patterns = ['%' + p + '%' for p in patterns]
                    lph = ','.join(['?'] * len(like_patterns))
                    excl_clause, excl_params = _build_excl_clause(patterns)
                    fund_df = con.execute(f"""
                        SELECT fund_name, quarter,
                               MAX(shares_or_principal) as shares,
                               series_id
                        FROM fund_holdings_v2 fh
                        WHERE EXISTS (SELECT 1 FROM UNNEST([{lph}]) t(p) WHERE family_name ILIKE t.p)
                          AND ticker = ?
                          AND quarter IN ({q_placeholders})
                          {excl_clause}
                          AND fh.is_latest = TRUE
                        GROUP BY fund_name, quarter, series_id
                    """, like_patterns + [ticker] + excl_params).fetchdf()
                if fund_df is None or fund_df.empty:
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

            children = _get_fund_children(pname, parent_eids.get(pname))
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


def ownership_trend_summary(ticker, level='parent', active_only=False, rollup_type='economic_control_v1'):
    """Aggregated institutional ownership trend across all quarters.
    level: 'parent' (13F) or 'fund' (N-PORT).
    active_only: fund level — only include funds classified as active.
    """
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        # Per-quarter denominator cache (avoids per-row queries in the loop).
        # Each quarter resolves to its own (denom, source) via the tier
        # cascade. Fund-level N-PORT rows are aggregated per `quarter` so
        # the quarter-end anchor is the representative reference.
        denom_cache: dict = {}

        def _qdenom(q):
            if q not in denom_cache:
                denom_cache[q] = _resolve_pct_of_so_denom(
                    con, ticker, _quarter_to_date(q))
            return denom_cache[q]

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
                WHERE fh.ticker = ? AND fh.market_value_usd > 0 {af} AND fh.is_latest = TRUE
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
                FROM holdings_v2 WHERE ticker = ? AND is_latest = TRUE GROUP BY quarter ORDER BY quarter
            """, [ticker]).fetchdf()

        rows = df_to_records(df)
        prev_shares = None
        prev_holders = None
        for row in rows:
            total_shares = row.get('total_inst_shares') or 0
            total_value = row.get('total_inst_value') or 0
            holders = row.get('holder_count') or 0
            denom, denom_source = _qdenom(row.get('quarter'))
            if denom and denom > 0:
                row['pct_so'] = round(total_shares / denom * 100, 2)
                row['pct_of_so_source'] = denom_source
            else:
                row['pct_so'] = None
                row['pct_of_so_source'] = None
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


_ACTIVE_PARENT_TYPES = ("active", "hedge_fund", "activist")
_ACTIVE_FUND_TYPES = ("active", "equity", "mixed", "balanced", "multi_asset")


def get_peer_rotation(ticker, active_only=False, level="parent", rollup_type='economic_control_v1'):
    """Peer rotation analysis: how institutional money rotates between a
    subject ticker and its sector/industry peers across quarters.

    Reads from the precomputed ``peer_rotation_flows`` table (perf-p0-s2).
    The active_only filter is applied as an entity_type predicate on the
    precompute read rather than re-aggregating live holdings.

    Returns subject vs sector flows, substitution peers (industry + broader
    sector), top 5 sector movers, and top 10 entity rotation stories.
    """
    con = get_db()
    pr_level = "fund" if level == "fund" else "parent"

    ctx = con.execute(
        "SELECT sector, industry FROM market_data WHERE ticker = ?", [ticker]
    ).fetchone()
    if not ctx:
        return {"error": f"No market data for {ticker}"}
    sector, industry = ctx

    empty_result = {
        "subject": {"ticker": ticker, "sector": sector, "industry": industry},
        "periods": [], "subject_flows": {}, "sector_flows": {},
        "subject_pct_of_sector": {}, "industry_substitutions": [],
        "sector_substitutions": [], "top_sector_movers": [],
        "entity_stories": [],
    }

    params = [sector, pr_level, rollup_type]
    active_clause = ""
    if active_only:
        active_types = _ACTIVE_PARENT_TYPES if pr_level == "parent" else _ACTIVE_FUND_TYPES
        active_clause = " AND entity_type IN (" + ",".join(["?"] * len(active_types)) + ")"
        params.extend(active_types)

    rows = con.execute(f"""
        SELECT entity, ticker, quarter_from, quarter_to,
               SUM(active_flow) AS flow
          FROM peer_rotation_flows
         WHERE sector = ?
           AND level = ?
           AND rollup_type = ?{active_clause}
         GROUP BY entity, ticker, quarter_from, quarter_to
    """, params).fetchall()

    if not rows:
        return empty_result

    pairs_set = set()
    all_entity_ticker_flows = {}  # {entity: {ticker: {pk: flow}}}

    for ent, tkr, q_from, q_to, fl in rows:
        if fl is None or (isinstance(fl, float) and math.isnan(fl)):
            continue
        fl = float(fl)
        pk = f"{q_from}_{q_to}"
        pairs_set.add((q_from, q_to))
        ent_map = all_entity_ticker_flows.setdefault(ent, {})
        tkr_map = ent_map.setdefault(tkr, {})
        tkr_map[pk] = tkr_map.get(pk, 0) + fl

    pairs = sorted(pairs_set)

    # Per-pair subject and sector net flows. Prefill all observed pairs so
    # the output shape matches the prior live query.
    subj_flows_by_pk = {f"{qf}_{qt}": {"net": 0} for qf, qt in pairs}
    sector_flows_by_pk = {f"{qf}_{qt}": {"net": 0} for qf, qt in pairs}
    for ticker_flows in all_entity_ticker_flows.values():
        for tkr, pf in ticker_flows.items():
            for pk_key, val in pf.items():
                sector_flows_by_pk[pk_key]["net"] += val
                if tkr == ticker:
                    subj_flows_by_pk[pk_key]["net"] += val

    subj_total = sum(v["net"] for v in subj_flows_by_pk.values())
    sector_total = sum(v["net"] for v in sector_flows_by_pk.values())
    subj_flows_by_pk["total"] = {"net": subj_total}
    sector_flows_by_pk["total"] = {"net": sector_total}

    pct_of_sector = {}
    for pk in list(subj_flows_by_pk.keys()):
        s_net = sector_flows_by_pk.get(pk, {}).get("net", 0)
        pct_of_sector[pk] = round(subj_flows_by_pk[pk]["net"] / s_net * 100, 1) if s_net else 0

    # --- Substitution detection ---
    peer_subs = {}

    for ticker_flows in all_entity_ticker_flows.values():
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

    peer_tickers = list(peer_subs.keys())
    peer_industries = {}
    if peer_tickers:
        ph = ','.join(['?'] * len(peer_tickers))
        for row in con.execute(
            f"SELECT ticker, industry FROM market_data WHERE ticker IN ({ph})",
            peer_tickers
        ).fetchall():
            peer_industries[row[0]] = row[1]

    all_subs = []
    for tkr, data in peer_subs.items():
        ind = peer_industries.get(tkr, "")
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
    ticker_totals = {}
    for ticker_flows in all_entity_ticker_flows.values():
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

    top_movers = movers[:5]
    if not any(m["is_subject"] for m in top_movers):
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

    periods = [{"label": f"{qf} → {qt}", "from": qf, "to": qt}
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


def get_peer_rotation_detail(ticker, peer, active_only=False, level="parent", rollup_type='economic_control_v1'):
    """Entity-level breakdown for a specific subject+peer substitution pair.

    Reads from the precomputed ``peer_rotation_flows`` table (perf-p0-s2).

    Shows which entities are driving the rotation between ticker and peer.
    """
    con = get_db()
    pr_level = "fund" if level == "fund" else "parent"

    ctx = con.execute(
        "SELECT sector FROM market_data WHERE ticker = ?", [ticker]
    ).fetchone()
    if not ctx:
        return {"error": f"No market data for {ticker}"}
    sector = ctx[0]

    params = [sector, pr_level, rollup_type, ticker, peer]
    active_clause = ""
    if active_only:
        active_types = _ACTIVE_PARENT_TYPES if pr_level == "parent" else _ACTIVE_FUND_TYPES
        active_clause = " AND entity_type IN (" + ",".join(["?"] * len(active_types)) + ")"
        params.extend(active_types)

    rows = con.execute(f"""
        SELECT entity, ticker, quarter_from, quarter_to,
               SUM(active_flow) AS flow
          FROM peer_rotation_flows
         WHERE sector = ?
           AND level = ?
           AND rollup_type = ?
           AND ticker IN (?, ?){active_clause}
         GROUP BY entity, ticker, quarter_from, quarter_to
    """, params).fetchall()

    entity_data = {}
    for ent, tkr, _qf, _qt, fl in rows:
        if fl is None or (isinstance(fl, float) and math.isnan(fl)):
            continue
        fl = float(fl)
        if ent not in entity_data:
            entity_data[ent] = {"subject_flow": 0, "peer_flow": 0}
        if tkr == ticker:
            entity_data[ent]["subject_flow"] += fl
        elif tkr == peer:
            entity_data[ent]["peer_flow"] += fl

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
