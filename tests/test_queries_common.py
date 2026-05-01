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
