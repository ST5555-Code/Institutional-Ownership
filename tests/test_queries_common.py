"""Unit tests for scripts/queries/common.py — fund_strategy partitions.

Pins the canonical active/passive split so the constants stay in sync with
the seven fund_strategy values produced by `scripts/pipeline/nport_parsers`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_active_fund_strategies_value():
    from queries.common import ACTIVE_FUND_STRATEGIES
    assert ACTIVE_FUND_STRATEGIES == ('active', 'balanced', 'multi_asset')


def test_passive_fund_strategies_value():
    from queries.common import PASSIVE_FUND_STRATEGIES
    assert PASSIVE_FUND_STRATEGIES == (
        'passive', 'bond_or_other', 'excluded', 'final_filing'
    )


def test_partitions_cover_all_canonical_values_with_no_overlap():
    from queries.common import ACTIVE_FUND_STRATEGIES, PASSIVE_FUND_STRATEGIES
    canonical = {
        'active', 'balanced', 'multi_asset',
        'passive', 'bond_or_other', 'excluded', 'final_filing',
    }
    active = set(ACTIVE_FUND_STRATEGIES)
    passive = set(PASSIVE_FUND_STRATEGIES)
    assert active.union(passive) == canonical, "active ∪ passive must cover all 7 values"
    assert active.isdisjoint(passive), "active ∩ passive must be empty"


def test_fund_type_label_uses_active_partition():
    from queries.common import _fund_type_label, ACTIVE_FUND_STRATEGIES
    for s in ACTIVE_FUND_STRATEGIES:
        assert _fund_type_label(s) == 'active'
    assert _fund_type_label('passive') == 'passive'
    assert _fund_type_label('bond_or_other') == 'bond'
    assert _fund_type_label('excluded') == 'excluded'
    assert _fund_type_label('final_filing') == 'excluded'
    assert _fund_type_label(None) == 'unknown'
    assert _fund_type_label('something_else') == 'unknown'


# ---------------------------------------------------------------------------
# classify_fund_strategy — ECH-shape mapping for fund-typed entities
# ---------------------------------------------------------------------------
# Per docs/decisions/d4-classification-precedence.md, fund-typed entities do
# NOT carry ECH rows. Reader paths (queries/entities.get_entity_by_id and
# search_entity_parents) and the entity-build classification field instead
# resolve fund classification from fund_universe.fund_strategy via this
# helper. Mapping derived from build_entities.step6 historical docstring
# ('active = equity|balanced|multi_asset; passive = everything else;
# unknown if no canonical strategy') reconciled with the ACTIVE/PASSIVE
# tuple constants above and _fund_type_label display labels.
# ---------------------------------------------------------------------------

import pytest


def test_classify_fund_strategy_active_set():
    from queries.common import classify_fund_strategy, ACTIVE_FUND_STRATEGIES
    for s in ACTIVE_FUND_STRATEGIES:
        assert classify_fund_strategy(s) == 'active', s


def test_classify_fund_strategy_passive_set():
    from queries.common import classify_fund_strategy, PASSIVE_FUND_STRATEGIES
    for s in PASSIVE_FUND_STRATEGIES:
        assert classify_fund_strategy(s) == 'passive', s


def test_classify_fund_strategy_none_is_unknown():
    from queries.common import classify_fund_strategy
    assert classify_fund_strategy(None) == 'unknown'


def test_classify_fund_strategy_empty_string_is_unknown():
    from queries.common import classify_fund_strategy
    assert classify_fund_strategy('') == 'unknown'


def test_classify_fund_strategy_invalid_raises():
    from queries.common import classify_fund_strategy
    with pytest.raises(ValueError):
        classify_fund_strategy('not_a_real_strategy')


def test_classify_fund_strategy_covers_all_canonical_values():
    """Pin: every canonical fund_strategy value maps to active or passive."""
    from queries.common import (
        classify_fund_strategy,
        ACTIVE_FUND_STRATEGIES,
        PASSIVE_FUND_STRATEGIES,
    )
    canonical = set(ACTIVE_FUND_STRATEGIES) | set(PASSIVE_FUND_STRATEGIES)
    for s in canonical:
        result = classify_fund_strategy(s)
        assert result in ('active', 'passive'), (s, result)
