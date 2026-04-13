"""Entity graph endpoints (FastAPI).

Routes:
  /api/v1/entity_search
  /api/v1/entity_children
  /api/v1/entity_graph          (enveloped, Phase 1-B2)
  /api/v1/entity_resolve
  /api/v1/entity_market_summary
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api_common import LQ, envelope_error, envelope_success, validate_query_params_dep
from app_db import get_db
import queries
from schemas import EntityGraphEnvelope

log = logging.getLogger(__name__)

entities_router = APIRouter(
    prefix='/api/v1',
    tags=['entities'],
    dependencies=[Depends(validate_query_params_dep)],
)


def _eg_quarter(request: Request) -> str:
    """Validate `quarter` query param against config.QUARTERS, fallback to LQ."""
    q = (request.query_params.get('quarter') or '').strip()
    from config import QUARTERS as _QUARTERS
    return q if q in _QUARTERS else LQ


@entities_router.get('/entity_search')
def api_entity_search(q: str = ''):
    """Type-ahead search for the Institution dropdown. Searches rollup parents
    only (entity_id = rollup_entity_id). Requires q ≥ 2 chars."""
    q = (q or '').strip()
    if len(q) < 2:
        return []
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        results = queries.search_entity_parents(q, con)
        return queries.clean_for_json(results)
    except Exception as e:
        log.error("entity_search error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@entities_router.get('/entity_children')
def api_entity_children(request: Request):
    """Cascading dropdown population. `level` is 'filer' or 'fund'."""
    entity_id = (request.query_params.get('entity_id') or '').strip()
    level = (request.query_params.get('level') or 'filer').strip()
    if not entity_id:
        return JSONResponse(status_code=400, content={'error': 'Missing entity_id parameter'})
    try:
        eid = int(entity_id)
    except ValueError:
        return JSONResponse(status_code=400, content={'error': f'Invalid entity_id: {entity_id}'})

    quarter = _eg_quarter(request)

    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        if level == 'filer':
            data = queries.get_entity_filer_children(eid, quarter, con)
            return queries.clean_for_json(data)
        elif level == 'fund':
            try:
                top_n = int(request.query_params.get('top_n', '0'))
            except ValueError:
                top_n = 0
            if top_n <= 0:
                top_n = 10000
            data = queries.get_entity_fund_children(eid, top_n, con)
            return queries.clean_for_json(data)
        else:
            return JSONResponse(status_code=400, content={'error': f'Invalid level: {level}'})
    except Exception as e:
        log.error("entity_children error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@entities_router.get('/entity_graph', response_model=EntityGraphEnvelope)
def api_entity_graph(request: Request):
    """Main graph data endpoint — returns {nodes, edges, metadata}."""
    entity_id = (request.query_params.get('entity_id') or '').strip()
    if not entity_id:
        return envelope_error(
            'missing_param', 'Missing entity_id parameter',
            request, schema=EntityGraphEnvelope, status=400,
        )
    try:
        eid = int(entity_id)
    except ValueError:
        return envelope_error(
            'invalid_param', f'Invalid entity_id: {entity_id}',
            request, schema=EntityGraphEnvelope, status=400,
        )

    quarter = _eg_quarter(request)
    try:
        depth = int(request.query_params.get('depth', '2'))
    except ValueError:
        depth = 2
    include_sub = (request.query_params.get('include_sub_advisers', 'true').lower() != 'false')
    try:
        top_n_funds = int(request.query_params.get('top_n_funds', '20'))
    except ValueError:
        top_n_funds = 20
    if top_n_funds <= 0:
        top_n_funds = 20

    try:
        con = get_db()
    except Exception as e:
        return envelope_error(
            'db_unavailable', f'Database unavailable: {e}',
            request, schema=EntityGraphEnvelope, status=503,
        )
    try:
        data = queries.build_entity_graph(eid, quarter, depth, include_sub, top_n_funds, con)
        if isinstance(data, dict) and data.get('error'):
            return envelope_error(
                'not_found', str(data['error']),
                request, schema=EntityGraphEnvelope, status=404,
            )
        return envelope_success(queries.clean_for_json(data),
                                request, schema=EntityGraphEnvelope)
    except Exception as e:
        log.error("entity_graph error: %s", e, exc_info=True)
        return envelope_error(
            'internal_error', str(e),
            request, schema=EntityGraphEnvelope, status=500,
        )
    finally:
        con.close()


@entities_router.get('/entity_resolve')
def api_entity_resolve(entity_id: str = ''):
    """Resolve any entity_id to its canonical institution root."""
    entity_id = (entity_id or '').strip()
    if not entity_id:
        return JSONResponse(status_code=400, content={'error': 'Missing entity_id parameter'})
    try:
        eid = int(entity_id)
    except ValueError:
        return JSONResponse(status_code=400, content={'error': f'Invalid entity_id: {entity_id}'})

    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        ent = queries.get_entity_by_id(eid, con)
        if not ent:
            return JSONResponse(status_code=404, content={'error': f'entity_id {eid} not found'})

        root_id = ent['rollup_entity_id'] if ent['rollup_entity_id'] else ent['entity_id']
        root = ent if root_id == ent['entity_id'] else queries.get_entity_by_id(root_id, con)
        if not root:
            root = ent
            root_id = ent['entity_id']

        return queries.clean_for_json({
            'selected_entity_id': eid,
            'selected_display_name': ent['display_name'],
            'root_entity_id': root_id,
            'root_display_name': root['display_name'],
            'entity_type': root.get('entity_type'),
            'classification': root.get('classification'),
            'is_self_root': root_id == ent['entity_id'],
        })
    except Exception as e:
        log.error("entity_resolve error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@entities_router.get('/entity_market_summary')
def api_entity_market_summary(limit: int = 25):
    """Market-wide: top institutions by 13F book value with filer + fund counts."""
    try:
        from queries import get_market_summary
        result = get_market_summary(limit=limit)
        return result
    except Exception as e:
        log.error("entity_market_summary error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
