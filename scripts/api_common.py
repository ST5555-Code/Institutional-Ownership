"""Shared API helpers for the FastAPI domain routers (Phase 4+ Batch 4-C).

Holds:
  - Input-guard regexes (TICKER_RE, QUARTER_RE) + VALID_ROLLUP_TYPES set
  - _RT_AWARE_QUERIES frozenset (rollup-aware queryN dispatch)
  - QUERY_FUNCTIONS dispatch table
  - LQ / FQ / PQ quarter constants
  - get_rollup_type(request) request helper
  - validate_query_params_dep() FastAPI dependency
  - envelope_success / envelope_error helpers

No FastAPI app instantiation here — this file is imported by every api_*.py
router AND by scripts/app.py. Keep it dependency-light so it doesn't
introduce circular imports.
"""
from __future__ import annotations

import logging
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
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
TICKER_RE = re.compile(r'^[A-Z]{1,6}(\.[A-Z])?$')
QUARTER_RE = re.compile(r'^20\d{2}Q[1-4]$')


# ── Quarter constants (re-exported from config.py) ─────────────────────────
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
_RT_AWARE_QUERIES = frozenset({1, 2, 3, 5, 12, 14})


def get_rollup_type(request: Request) -> str:
    """Extract rollup_type query parameter, validated against VALID_ROLLUP_TYPES.
    Default: 'economic_control_v1' (fund sponsor / voting view).
    """
    rt = (request.query_params.get('rollup_type') or 'economic_control_v1').strip()
    if rt not in VALID_ROLLUP_TYPES:
        rt = 'economic_control_v1'
    return rt


# ── Input guards (ARCH-1A) — FastAPI dependency ────────────────────────────
# Applied via APIRouter(dependencies=[Depends(validate_query_params_dep)]).
# Raises HTTPException(400, ...) on invalid input. /api/admin/* routers
# bring their own token-auth dependency instead.

def validate_query_params_dep(request: Request) -> None:
    """FastAPI dependency: validate shape of ticker / quarter / rollup_type."""
    ticker = request.query_params.get('ticker')
    if ticker and not TICKER_RE.match(ticker.upper().strip()):
        raise HTTPException(
            status_code=400,
            detail={'error': f'Invalid ticker format: {ticker!r}'},
        )
    quarter = request.query_params.get('quarter')
    if quarter and not QUARTER_RE.match(quarter.strip()):
        raise HTTPException(
            status_code=400,
            detail={'error': f'Invalid quarter format: {quarter!r}'},
        )
    rollup = request.query_params.get('rollup_type')
    if rollup and rollup.strip() not in VALID_ROLLUP_TYPES:
        raise HTTPException(
            status_code=400,
            detail={'error': f'Invalid rollup_type: {rollup!r}'},
        )


# ── Phase 1-B2 envelope helpers (Phase 4+ Batch 4-C form) ─────────────────
# Replaces the Flask respond() helper. Each enveloped endpoint constructs
# {data, error, meta} via envelope_success() on the happy path and
# envelope_error() on the failure paths. `schema` is a Pydantic Envelope
# class (e.g. TickersEnvelope) validated on the way out — a shape mismatch
# downgrades the response to a standard 500 error envelope.


def _build_meta(request: Request) -> dict:
    return {
        "quarter": request.query_params.get("quarter"),
        "rollup_type": request.query_params.get("rollup_type"),
        "generated_at": iso_now(),
    }


def envelope_success(data, request: Request, *, schema=None, status: int = 200):
    """Return a JSONResponse wrapped in the Phase 1-B2 envelope."""
    envelope = {"data": data, "error": None, "meta": _build_meta(request)}
    if schema is not None:
        try:
            schema.model_validate(envelope)
        except ValidationError as e:
            log.error("[envelope_success] schema validation failed: %s", e)
            return JSONResponse(
                status_code=500,
                content={
                    "data": None,
                    "error": {
                        "code": "schema_validation_error",
                        "message": "Response failed server-side validation",
                        "detail": {"errors": e.errors()[:5]},
                    },
                    "meta": _build_meta(request),
                },
            )
    return JSONResponse(status_code=status, content=envelope)


def envelope_error(code: str, message: str, request: Request, *,
                   schema=None, status: int = 500, detail=None):
    """Return an error envelope response."""
    err = {"code": code, "message": message}
    if detail is not None:
        err["detail"] = detail
    envelope = {"data": None, "error": err, "meta": _build_meta(request)}
    # Schema validation on error paths is best-effort — don't mask the
    # original failure with a schema-validation fallback.
    if schema is not None:
        try:
            schema.model_validate(envelope)
        except ValidationError:
            pass
    return JSONResponse(status_code=status, content=envelope)
