"""Shared API helpers for the Phase 4 domain Blueprints.

Holds:
  - Input-guard regexes (TICKER_RE, QUARTER_RE) + VALID_ROLLUP_TYPES set
  - _RT_AWARE_QUERIES frozenset (rollup-aware queryN dispatch)
  - QUERY_FUNCTIONS dispatch table
  - LQ / FQ / PQ quarter constants
  - _get_rollup_type(req) request helper
  - validate_query_params() before_request hook
  - respond() envelope helper (Phase 1-B2)

No Flask app instantiation here — this file is imported by every api_*.py
Blueprint module AND by scripts/app.py. Keep it dependency-light so it
doesn't introduce circular imports.
"""
from __future__ import annotations

import logging
import re

from flask import current_app, jsonify, request
from pydantic import ValidationError

from config import LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER
from queries import (
    VALID_ROLLUP_TYPES,
    query1, query2, query3, query4, query5,
    query6, query7, query8, query9, query10,
    query11, query12, query14, query15, query16,
)
from schemas import iso_now

log = logging.getLogger(__name__)


# ── Input-guard regexes (ARCH-1A) ──────────────────────────────────────────
# Ticker regex accepts BRK.B, BF.B, ADRs. Quarter regex matches 20XXQ[1-4].
# Transitional — Pydantic validation in Batch 4-C (FastAPI) replaces these.
TICKER_RE = re.compile(r'^[A-Z]{1,6}(\.[A-Z])?$')
QUARTER_RE = re.compile(r'^20\d{2}Q[1-4]$')


# ── Quarter constants (re-exported from config.py) ─────────────────────────
# Edit ONLY scripts/config.py to roll forward. These propagate everywhere.
LQ = LATEST_QUARTER
FQ = FIRST_QUARTER
PQ = PREV_QUARTER


# ── Query dispatch tables ──────────────────────────────────────────────────

QUERY_FUNCTIONS = {
    1: query1, 2: query2, 3: query3, 4: query4, 5: query5,
    6: query6, 7: query7, 8: query8, 9: query9, 10: query10,
    11: query11, 12: query12, 14: query14, 15: query15,
    16: query16,
}

# Queries that accept rollup_type. Shared by api_query and api_export so
# Excel export mirrors on-screen semantics (Batch 1-B1 export parity).
# Keep in sync with queries.py signatures.
_RT_AWARE_QUERIES = frozenset({1, 2, 3, 5, 12, 14})


def _get_rollup_type(req) -> str:
    """Extract rollup_type query parameter, validated against VALID_ROLLUP_TYPES.
    Default: 'economic_control_v1' (fund sponsor / voting view).
    """
    rt = req.args.get('rollup_type', 'economic_control_v1').strip()
    if rt not in VALID_ROLLUP_TYPES:
        rt = 'economic_control_v1'
    return rt


# ── Input guards (ARCH-1A) ─────────────────────────────────────────────────
# Registered as a Flask @before_request in app.py. Validates /api/v1/*.
# /api/admin/* has its own before_request (admin_bp token auth).

def validate_query_params():
    path = request.path
    if not path.startswith('/api/v1/'):
        return None
    ticker = request.args.get('ticker')
    if ticker and not TICKER_RE.match(ticker.upper().strip()):
        return jsonify({'error': f'Invalid ticker format: {ticker!r}'}), 400
    quarter = request.args.get('quarter')
    if quarter and not QUARTER_RE.match(quarter.strip()):
        return jsonify({'error': f'Invalid quarter format: {quarter!r}'}), 400
    rollup = request.args.get('rollup_type')
    if rollup and rollup.strip() not in VALID_ROLLUP_TYPES:
        return jsonify({'error': f'Invalid rollup_type: {rollup!r}'}), 400
    return None


# ── Phase 1-B2 envelope helper ─────────────────────────────────────────────
# respond() wraps payloads in the {data, error, meta} envelope. Applied
# opt-in per endpoint — handlers NOT migrated still call jsonify() directly.

def _build_meta() -> dict:
    return {
        "quarter": request.args.get("quarter"),
        "rollup_type": request.args.get("rollup_type"),
        "generated_at": iso_now(),
    }


def respond(data=None, *, schema=None, error=None, status=200):
    """Return a Flask JSON response wrapped in the Phase 1-B2 envelope.

    Args:
        data: payload. Can be list/dict. `None` when `error` is set.
        schema: optional Pydantic envelope type (e.g. `TickersEnvelope`);
                validates the {data, error, meta} shape on the way out.
        error: optional ErrorShape-compatible dict or pydantic model.
        status: HTTP status code.
    """
    err_payload = None
    if error is not None:
        err_payload = error if isinstance(error, dict) else error.model_dump()

    envelope = {"data": data, "error": err_payload, "meta": _build_meta()}

    if schema is not None:
        try:
            schema.model_validate(envelope)
        except ValidationError as e:
            current_app.logger.error("[respond] envelope schema validation failed: %s", e)
            return jsonify({
                "data": None,
                "error": {
                    "code": "schema_validation_error",
                    "message": "Response failed server-side validation",
                    "detail": {"errors": e.errors()[:5]},
                },
                "meta": _build_meta(),
            }), 500

    return jsonify(envelope), status


# ── FastAPI envelope helpers (Phase 4+ Batch 4-C) ─────────────────────────
# Added alongside Flask's `respond()` during the FastAPI migration. No
# callers yet — the cutover commit swaps every handler from respond() to
# these. respond() + _build_meta() deleted once callers gone.
#
# Shape-identical to `respond()`: `{data, error, meta}`. Meta is sourced
# from the FastAPI request.query_params (same keys: quarter, rollup_type,
# generated_at). Pass the request via the second positional argument — the
# dependency machinery makes that cheap.


def _build_meta_fastapi(request) -> dict:
    """FastAPI analogue of _build_meta(). `request` is starlette.Request."""
    return {
        "quarter": request.query_params.get("quarter"),
        "rollup_type": request.query_params.get("rollup_type"),
        "generated_at": iso_now(),
    }


def envelope_success(data, request, *, schema=None, status: int = 200):
    """FastAPI: return a successful envelope response."""
    # Deferred import — starlette is a fastapi transitive, not a Flask-time dep.
    from starlette.responses import JSONResponse  # pylint: disable=import-outside-toplevel

    envelope = {"data": data, "error": None, "meta": _build_meta_fastapi(request)}
    if schema is not None:
        try:
            schema.model_validate(envelope)
        except ValidationError as e:
            # Downgrade to 500 — same semantics as Flask respond()
            return JSONResponse(
                status_code=500,
                content={
                    "data": None,
                    "error": {
                        "code": "schema_validation_error",
                        "message": "Response failed server-side validation",
                        "detail": {"errors": e.errors()[:5]},
                    },
                    "meta": _build_meta_fastapi(request),
                },
            )
    return JSONResponse(status_code=status, content=envelope)


def envelope_error(code: str, message: str, request, *,
                   schema=None, status: int = 500, detail=None):
    """FastAPI: return an error envelope response."""
    from starlette.responses import JSONResponse  # pylint: disable=import-outside-toplevel

    err = {"code": code, "message": message}
    if detail is not None:
        err["detail"] = detail
    envelope = {"data": None, "error": err, "meta": _build_meta_fastapi(request)}
    # Schema validation optional — same contract as respond()
    if schema is not None:
        try:
            schema.model_validate(envelope)
        except ValidationError:
            # Already an error response; don't mask the original with a
            # schema-validation fallback. Return as-is.
            pass
    return JSONResponse(status_code=status, content=envelope)
