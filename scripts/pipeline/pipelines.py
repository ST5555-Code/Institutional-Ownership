"""PIPELINE_REGISTRY — map pipeline names to SourcePipeline subclasses.

p2-07. Consumed by scripts/admin_bp.py to dispatch refresh / approve /
reject / rollback calls to the correct pipeline implementation.

Only pipelines that have migrated to the ``SourcePipeline`` framework
are registered here. The remaining five (NPORT, 13D/G, N-CEN, ADV,
market_data) register as they migrate in the wave-2 sessions — see
docs/admin_refresh_system_design.md §12.
"""
from __future__ import annotations

from typing import Type

from .base import SourcePipeline


def _load_13f_cls() -> Type[SourcePipeline]:
    """Lazy-import Load13FPipeline so this module can be imported without
    pulling in load_13f_v2.py's heavier deps (requests, EDGAR config)
    during unit-test collection that patches the registry."""
    # pylint: disable=import-outside-toplevel
    import importlib
    module = importlib.import_module("load_13f_v2")
    return module.Load13FPipeline


def _load_13dg_cls() -> Type[SourcePipeline]:
    """Lazy-import Load13DGPipeline. Same rationale as ``_load_13f_cls``
    — avoids eager import of ``requests`` / EDGAR config when callers
    only need to enumerate registered pipelines."""
    # pylint: disable=import-outside-toplevel
    import importlib
    module = importlib.import_module("pipeline.load_13dg")
    return module.Load13DGPipeline


PIPELINE_REGISTRY: dict[str, "Type[SourcePipeline]"] = {
    "13f_holdings":   _load_13f_cls,   # type: ignore[dict-item]
    "13dg_ownership": _load_13dg_cls,  # type: ignore[dict-item]
}


def get_pipeline(name: str) -> SourcePipeline:
    """Instantiate and return the pipeline registered under ``name``.

    Raises KeyError if ``name`` is not registered.
    """
    if name not in PIPELINE_REGISTRY:
        raise KeyError(
            f"Unknown pipeline: {name!r}. "
            f"Available: {sorted(PIPELINE_REGISTRY.keys())}"
        )
    entry = PIPELINE_REGISTRY[name]
    cls = entry() if callable(entry) and not isinstance(entry, type) else entry
    return cls()


def available_pipelines() -> list[str]:
    """Sorted list of pipeline names registered in PIPELINE_REGISTRY."""
    return sorted(PIPELINE_REGISTRY.keys())
