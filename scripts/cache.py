"""Simple TTL cache for expensive query results.

Split out of scripts/queries.py in Phase 4 Batch 4-B.

Per spec, cache keys are expressed as explicit string constants here (not
inline f-strings at call sites). Callers call `.format()` on the template
to build the actual key. Add a constant here when a new caller joins.

Per-call TTL is supported via the `ttl=` arg to `cached()` so callers
that need shorter freshness (e.g. cohort_analysis at 60s) don't share
the default 5-minute window.
"""
from __future__ import annotations

import time as _time


CACHE_TTL = 300  # 5 minutes — default for `cached()`
CACHE_TTL_COHORT = 60  # cohort_analysis: cheap enough to recompute often


# ── Cache key templates ────────────────────────────────────────────────────
# Use via `CACHE_KEY_SUMMARY.format(ticker=ticker)` — keeps the key shape
# in one place so migrations (e.g. adding a quarter dimension) land here
# instead of being hunted across call sites.

CACHE_KEY_SUMMARY = "summary:{ticker}"
CACHE_KEY_COHORT = (
    "cohort:{ticker}:{quarter}:{rollup_type}:{level}:{active_only}:{from_quarter}"
)


_query_cache: dict = {}


def cached(key, fn, ttl=CACHE_TTL):
    """Return cached result if fresh, else compute via `fn()` and cache."""
    now = _time.time()
    if key in _query_cache:
        val, ts = _query_cache[key]
        if now - ts < ttl:
            return val
    result = fn()
    _query_cache[key] = (result, now)
    return result


# Backwards-compat alias for any internal call site that still uses the
# pre-Batch-4-B underscore-prefixed name. Remove once all callers migrate.
_cached = cached
