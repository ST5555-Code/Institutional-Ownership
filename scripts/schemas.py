"""Phase 1-B2 — transitional Pydantic response schemas + envelope.

Defines the `{data, error, meta}` envelope applied to the 6 priority
endpoints (see ARCHITECTURE_REVIEW.md Batch 1-B2) plus loose per-endpoint
payload schemas.

Intentionally loose — deep field validation is deferred to Phase 4-C
(FastAPI + openapi-typescript auto-generation). These schemas exist to
enforce the outer contract (top-level keys present, list fields are
lists) so a dropped/renamed column fails fast on the server instead of
silently rendering a broken tab in React.

Usage (server side):
    from schemas import Envelope, TickersPayload, build_envelope
    return jsonify(build_envelope(data=rows, schema=list[TickerRow]))
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


# ── Envelope ──────────────────────────────────────────────────────────────


class ErrorShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    detail: Optional[dict[str, Any]] = None


class MetaShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quarter: Optional[str] = None
    rollup_type: Optional[str] = None
    generated_at: str  # ISO-8601 UTC


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    data: Optional[T] = None
    error: Optional[ErrorShape] = None
    meta: MetaShape


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── Per-endpoint payload schemas (loose; extra fields allowed) ────────────
#
# Each payload mirrors the current response shape with `extra='allow'` so
# new fields don't break validation. Required fields are only those that
# React consumers dereference unconditionally.


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class TickerRow(_Loose):
    ticker: str
    name: Optional[str] = None


# /api/v1/tickers returns a bare list — envelope wraps as data: list[TickerRow].

class SummaryPayload(_Loose):
    # /api/v1/summary?ticker=X returns a single object.
    ticker: str


class RegisterRow(_Loose):
    institution: str


class RegisterPayload(_Loose):
    # /api/v1/query1 — Register
    rows: list[RegisterRow]


class ConvictionPayload(_Loose):
    # /api/v1/portfolio_context — Conviction
    # Shape: {rows, metrics, ...} — loose.
    pass


class FlowAnalysisPayload(_Loose):
    # /api/v1/flow_analysis
    buyers: list[dict[str, Any]]
    sellers: list[dict[str, Any]]
    new_entries: list[dict[str, Any]]
    exits: list[dict[str, Any]]


class OwnershipTrendPayload(_Loose):
    # /api/v1/ownership_trend_summary — Ownership Trend
    # Shape is {quarters, totals, ...} — loose.
    pass


class EntityGraphPayload(_Loose):
    # /api/v1/entity_graph
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
