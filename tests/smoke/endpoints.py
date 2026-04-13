"""Shared endpoint registry for smoke tests and the snapshot capture script.

Keep this list in sync with `.github/workflows/smoke.yml` coverage and the
four endpoints named in ARCHITECTURE_REVIEW.md Phase 0-B2.

entity_graph uses a stable high-AUM eid (BlackRock / iShares, eid=2) that is
guaranteed to exist in any fixture built from a recent prod DB. Change only
if the fixture tickers change.
"""
from __future__ import annotations

ENDPOINTS: dict[str, str] = {
    "tickers":      "/api/v1/tickers",
    "query1":       "/api/v1/query1?ticker=AAPL",
    "summary":      "/api/v1/summary?ticker=AAPL",
    "entity_graph": "/api/v1/entity_graph?entity_id=2",
}
