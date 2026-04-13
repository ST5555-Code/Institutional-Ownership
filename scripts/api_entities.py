"""Entity graph endpoints.

Routes:
  /api/v1/entity_search
  /api/v1/entity_children
  /api/v1/entity_graph          (enveloped, Phase 1-B2)
  /api/v1/entity_resolve
  /api/v1/entity_market_summary
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from api_common import LQ, respond
from app_db import get_db
import queries
from schemas import EntityGraphEnvelope

entities_bp = Blueprint('api_entities', __name__, url_prefix='/api/v1')


def _eg_quarter(req):
    """Validate the `quarter` query param against config.QUARTERS, falling back
    to LATEST_QUARTER if missing or unrecognized."""
    q = (req.args.get('quarter') or '').strip()
    from config import QUARTERS as _QUARTERS
    return q if q in _QUARTERS else LQ


@entities_bp.route('/entity_search')
def api_entity_search():
    """Type-ahead search for the Institution dropdown. Searches rollup parents
    only (entity_id = rollup_entity_id). Requires q ≥ 2 chars."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        results = queries.search_entity_parents(q, con)
        return jsonify(queries.clean_for_json(results))
    except Exception as e:
        current_app.logger.error("entity_search error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@entities_bp.route('/entity_children')
def api_entity_children():
    """Cascading dropdown population. `level` is 'filer' or 'fund'.
    Filer level returns CIK-bearing descendants (tree walk, fallback to self).
    Fund level returns series_id-bearing children with NAV from fund_universe.
    """
    entity_id = (request.args.get('entity_id') or '').strip()
    level = (request.args.get('level') or 'filer').strip()
    if not entity_id:
        return jsonify({'error': 'Missing entity_id parameter'}), 400
    try:
        eid = int(entity_id)
    except ValueError:
        return jsonify({'error': f'Invalid entity_id: {entity_id}'}), 400

    quarter = _eg_quarter(request)

    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        if level == 'filer':
            data = queries.get_entity_filer_children(eid, quarter, con)
            return jsonify(queries.clean_for_json(data))
        elif level == 'fund':
            try:
                top_n = int(request.args.get('top_n', '0'))
            except ValueError:
                top_n = 0
            if top_n <= 0:
                top_n = 10000
            data = queries.get_entity_fund_children(eid, top_n, con)
            return jsonify(queries.clean_for_json(data))
        else:
            return jsonify({'error': f'Invalid level: {level}'}), 400
    except Exception as e:
        current_app.logger.error("entity_children error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@entities_bp.route('/entity_graph')
def api_entity_graph():
    """Main graph data endpoint — returns {nodes, edges, metadata}.

    The selected entity is resolved to its institution root (via rollup_entity_id),
    filer children are walked from there, fund children come from the institution
    root (funds attach at the institution level in this data model), and
    sub-advisers are pulled per fund when include_sub_advisers=true.
    """
    entity_id = (request.args.get('entity_id') or '').strip()
    if not entity_id:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing entity_id parameter'},
            schema=EntityGraphEnvelope,
            status=400,
        )
    try:
        eid = int(entity_id)
    except ValueError:
        return respond(
            error={'code': 'invalid_param', 'message': f'Invalid entity_id: {entity_id}'},
            schema=EntityGraphEnvelope,
            status=400,
        )

    quarter = _eg_quarter(request)
    try:
        depth = int(request.args.get('depth', '2'))
    except ValueError:
        depth = 2
    include_sub = (request.args.get('include_sub_advisers', 'true').lower() != 'false')
    try:
        top_n_funds = int(request.args.get('top_n_funds', '20'))
    except ValueError:
        top_n_funds = 20
    if top_n_funds <= 0:
        top_n_funds = 20

    try:
        con = get_db()
    except Exception as e:
        return respond(
            error={'code': 'db_unavailable', 'message': f'Database unavailable: {e}'},
            schema=EntityGraphEnvelope,
            status=503,
        )
    try:
        data = queries.build_entity_graph(eid, quarter, depth, include_sub, top_n_funds, con)
        if isinstance(data, dict) and data.get('error'):
            return respond(
                error={'code': 'not_found', 'message': str(data['error'])},
                schema=EntityGraphEnvelope,
                status=404,
            )
        return respond(data=queries.clean_for_json(data), schema=EntityGraphEnvelope)
    except Exception as e:
        current_app.logger.error("entity_graph error: %s", e, exc_info=True)
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=EntityGraphEnvelope,
            status=500,
        )
    finally:
        con.close()


@entities_bp.route('/entity_resolve')
def api_entity_resolve():
    """Resolve any entity_id to its canonical institution root.

    Thin wrapper around the rollup_entity_id walk already used by
    build_entity_graph(). Lets external tooling resolve a descendant entity
    (a filer subsidiary, a fund series) to its top-level institution without
    pulling the full graph payload. Returns the canonical root plus the
    selected entity for round-tripping.
    """
    entity_id = (request.args.get('entity_id') or '').strip()
    if not entity_id:
        return jsonify({'error': 'Missing entity_id parameter'}), 400
    try:
        eid = int(entity_id)
    except ValueError:
        return jsonify({'error': f'Invalid entity_id: {entity_id}'}), 400

    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        ent = queries.get_entity_by_id(eid, con)
        if not ent:
            return jsonify({'error': f'entity_id {eid} not found'}), 404

        root_id = ent['rollup_entity_id'] if ent['rollup_entity_id'] else ent['entity_id']
        root = ent if root_id == ent['entity_id'] else queries.get_entity_by_id(root_id, con)
        if not root:
            root = ent
            root_id = ent['entity_id']

        return jsonify(queries.clean_for_json({
            'selected_entity_id': eid,
            'selected_display_name': ent['display_name'],
            'root_entity_id': root_id,
            'root_display_name': root['display_name'],
            'entity_type': root.get('entity_type'),
            'classification': root.get('classification'),
            'is_self_root': root_id == ent['entity_id'],
        }))
    except Exception as e:
        current_app.logger.error("entity_resolve error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@entities_bp.route('/entity_market_summary')
def api_entity_market_summary():
    """Market-wide: top institutions by 13F book value with filer + fund counts."""
    try:
        limit = int(request.args.get('limit', 25))
    except ValueError:
        limit = 25
    try:
        from queries import get_market_summary
        result = get_market_summary(limit=limit)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error("entity_market_summary error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
