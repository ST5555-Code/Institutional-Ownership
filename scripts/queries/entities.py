"""Entity graph queries (parents, filers, funds, sub-advisers, edges)."""

from queries.common import classify_fund_strategy


def _resolve_fund_classification(entity_id, con):
    """Resolve a fund-typed entity's classification from fund_universe.

    Joins entity_identifiers (series_id, valid_to=open) → fund_universe
    and runs classify_fund_strategy on the result. Returns 'unknown' for
    every gap-state (no series_id, no fund_universe row, NULL strategy).
    Per D4 precedence (docs/decisions/d4-classification-precedence.md),
    fund-typed entities do not carry ECH rows — this is the canonical
    read path.
    """
    row = con.execute(
        """
        SELECT fu.fund_strategy
        FROM entity_identifiers ei
        JOIN fund_universe fu ON fu.series_id = ei.identifier_value
        WHERE ei.entity_id = ?
          AND ei.identifier_type = 'series_id'
          AND ei.valid_to = DATE '9999-12-31'
        LIMIT 1
        """,
        [int(entity_id)],
    ).fetchone()
    if row is None:
        return 'unknown'
    return classify_fund_strategy(row[0])


def search_entity_parents(q, con):
    """Type-ahead search for rollup parent entities (Institution dropdown).

    Returns entities where entity_id = rollup_entity_id (self-rollup = canonical
    parent). The caller is responsible for ensuring `q` is at least 2 chars.

    Fund-typed results have classification resolved from
    fund_universe.fund_strategy via classify_fund_strategy (D4 precedence:
    fund-typed entities do not carry ECH).
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
            'classification': (
                _resolve_fund_classification(r[0], con)
                if r[2] == 'fund'
                else r[3]
            ),
        }
        for r in rows
    ]


def get_entity_by_id(entity_id, con):
    """Fetch a single entity's core row for node-resolve logic.

    Fund-typed entities have classification resolved from
    fund_universe.fund_strategy via classify_fund_strategy (D4 precedence:
    fund-typed entities do not carry ECH). All gap states (no series_id,
    no fund_universe row, NULL fund_strategy) resolve to 'unknown'.
    """
    row = con.execute("""
        SELECT entity_id, display_name, entity_type, classification, rollup_entity_id
        FROM entity_current
        WHERE entity_id = ?
    """, [int(entity_id)]).fetchone()
    if not row:
        return None
    classification = (
        _resolve_fund_classification(row[0], con)
        if row[2] == 'fund'
        else row[3]
    )
    return {
        'entity_id': row[0],
        'display_name': row[1],
        'entity_type': row[2],
        'classification': classification,
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
        WHERE cik = ? AND quarter = ? AND is_latest = TRUE
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
          AND h.is_latest = TRUE
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
                 WHERE cik = s.cik AND quarter = ? AND is_latest = TRUE) AS aum
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


def get_institution_hierarchy(entity_id, quarter, con):
    """3-level institution drill-down for the Investor Detail tab.

    Returns the institution's 13F filer entities with per-filer AUM (computed
    from holdings_v2 for the given quarter) and the fund series each filer
    sponsors with NAV from fund_universe.
    """
    eid = int(entity_id)
    inst = get_entity_by_id(eid, con)
    if not inst:
        return {'error': f'entity_id {eid} not found'}

    filer_rows = con.execute("""
        SELECT er.child_entity_id,
               ec.display_name,
               MIN(ei.identifier_value) AS cik
        FROM entity_relationships er
        JOIN entity_current ec ON ec.entity_id = er.child_entity_id
        JOIN entity_identifiers ei
          ON ei.entity_id = er.child_entity_id
         AND ei.identifier_type = 'cik'
         AND ei.valid_to = DATE '9999-12-31'
        WHERE er.parent_entity_id = ?
          AND er.relationship_type != 'sub_adviser'
          AND er.valid_to = DATE '9999-12-31'
        GROUP BY er.child_entity_id, ec.display_name
        ORDER BY ec.display_name
    """, [eid]).fetchall()

    self_cik = get_entity_cik(eid, con)
    seen_eids = {r[0] for r in filer_rows}
    if self_cik and eid not in seen_eids:
        filer_rows = list(filer_rows) + [(eid, inst['display_name'], self_cik)]

    filers = []
    for fid, fname, cik in filer_rows:
        aum = compute_aum_by_cik(cik, quarter, con) if cik else None
        funds_q = con.execute("""
            SELECT ec.entity_id,
                   ec.display_name AS fund_name,
                   MIN(ei.identifier_value) AS series_id,
                   MAX(fu.total_net_assets) AS nav
            FROM entity_relationships er
            JOIN entity_current ec ON ec.entity_id = er.child_entity_id
            LEFT JOIN entity_identifiers ei
              ON ei.entity_id = er.child_entity_id
             AND ei.identifier_type = 'series_id'
             AND ei.valid_to = DATE '9999-12-31'
            LEFT JOIN fund_universe fu ON fu.series_id = ei.identifier_value
            WHERE er.parent_entity_id = ?
              AND er.relationship_type = 'fund_sponsor'
              AND er.valid_to = DATE '9999-12-31'
              AND ei.identifier_value IS NOT NULL
            GROUP BY ec.entity_id, ec.display_name
            ORDER BY MAX(fu.total_net_assets) DESC NULLS LAST, ec.display_name
        """, [int(fid)]).fetchall()
        funds = [
            {
                'entity_id': fr[0],
                'fund_name': fr[1],
                'series_id': fr[2],
                'nav': float(fr[3]) if fr[3] is not None else None,
            }
            for fr in funds_q
        ]
        filers.append({
            'entity_id': int(fid),
            'name': fname,
            'cik': cik,
            'aum': aum,
            'fund_count': len(funds),
            'funds': funds,
        })

    filers.sort(key=lambda x: (x['aum'] or 0), reverse=True)

    return {
        'entity_id': eid,
        'institution': inst['display_name'],
        'quarter': quarter,
        'filers': filers,
    }


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


def build_entity_graph(entity_id, quarter, _depth, include_sub_advisers, top_n_funds, con):
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
