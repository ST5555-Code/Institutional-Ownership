"""Regression tests for the RC1 US-preferred OpenFIGI listing selector.

Phase 0 finding (docs/findings/int-01-p0-findings.md): four US exchCodes
(UB, UC, UM, UT) were missing from ``US_PRICEABLE_EXCHCODES``. Phase 1
expanded the whitelist to all 15 known US equity venue codes. These
tests lock in both the whitelist membership and the selector semantics
used in ``scripts/build_cusip.py`` / ``scripts/run_openfigi_retry.py``.
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from pipeline.cusip_classifier import US_PRICEABLE_EXCHCODES  # noqa: E402


def _pick(data):
    """Mirror the selector used by build_cusip.py / run_openfigi_retry.py."""
    preferred = next(
        (d for d in data if d.get('exchCode') in US_PRICEABLE_EXCHCODES),
        None,
    )
    return preferred or (data[0] if data else None)


def test_whitelist_contains_all_known_us_codes():
    """All 15 US exchCodes are in the whitelist."""
    expected = {
        'US', 'UA', 'UB', 'UC', 'UD', 'UF', 'UM', 'UN',
        'UP', 'UQ', 'UR', 'UT', 'UV', 'UW', 'UX',
    }
    assert US_PRICEABLE_EXCHCODES == expected


def test_us_preferred_picks_uc_over_gr():
    data = [
        {'exchCode': 'GR', 'ticker': 'FOO1', 'compositeFIGI': 'BBG000A'},
        {'exchCode': 'UC', 'ticker': 'FOO',  'compositeFIGI': 'BBG000B'},
    ]
    assert _pick(data)['ticker'] == 'FOO'


def test_us_preferred_picks_ub_over_eo():
    data = [
        {'exchCode': 'EO', 'ticker': 'BAR1', 'compositeFIGI': 'BBG000C'},
        {'exchCode': 'UB', 'ticker': 'BAR',  'compositeFIGI': 'BBG000D'},
    ]
    assert _pick(data)['ticker'] == 'BAR'


def test_pure_foreign_falls_back_to_data0():
    data = [
        {'exchCode': 'GR', 'ticker': 'XFOO', 'compositeFIGI': 'BBG000E'},
        {'exchCode': 'GF', 'ticker': 'XFOO1', 'compositeFIGI': 'BBG000F'},
    ]
    assert _pick(data)['exchCode'] == 'GR'


def test_empty_data_returns_none():
    assert _pick([]) is None
