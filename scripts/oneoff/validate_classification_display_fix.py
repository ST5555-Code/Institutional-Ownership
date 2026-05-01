#!/usr/bin/env python3
"""validate_classification_display_fix.py — PR-1d post-fix validator.

Hits each fund-level endpoint touched by PR-1d and asserts the canonical
display contract:

  1. Every fund row carries a `type` field whose value is in the canonical
     set: {active, passive, bond, excluded, unknown}.
  2. Cross-Ownership level=fund rows do NOT carry a fund family name
     (Vanguard, BlackRock, etc.) in `type` — that was the pre-PR-1d bug
     at cross.py:215.
  3. short_analysis fund-level responses (nport_detail, nport_by_fund,
     short_only_funds) do NOT include an `is_active` field — per D7 the
     two-signal contract collapses to `type` only.
  4. No response leaks raw `fund_strategy` values to the public surface.

Runs against the committed CI fixture DB by default. Exit 0 on all pass,
1 otherwise.

Usage:
  python3 scripts/oneoff/validate_classification_display_fix.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"

CANONICAL_TYPES = {"active", "passive", "bond", "excluded", "unknown"}

# Common fund-family names that previously leaked through cross.py:215.
# A `type` value matching one of these (case-insensitive) is a regression.
KNOWN_FAMILY_NAMES = {
    "vanguard", "blackrock", "ishares", "fidelity", "state street",
    "spdr", "schwab", "invesco", "jpmorgan", "j.p. morgan", "t. rowe price",
    "pimco", "dimensional", "american funds", "capital group",
    "northern trust", "geode", "wells fargo", "morgan stanley",
}


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _payload(body):
    """Return the rows-bearing payload (handles both bare and enveloped)."""
    if isinstance(body, dict) and "data" in body and "error" in body:
        return body["data"]
    return body


def _iter_fund_rows(payload):
    """Yield every fund row from an arbitrary endpoint payload shape."""
    if isinstance(payload, list):
        for r in payload:
            if isinstance(r, dict):
                yield r
        return
    if not isinstance(payload, dict):
        return
    # Common containers
    for key in ("rows", "investors", "funds", "nport_detail",
                "nport_by_fund", "short_only_funds", "overlapping",
                "ticker_a_only", "ticker_b_only"):
        v = payload.get(key)
        if isinstance(v, list):
            for r in v:
                if isinstance(r, dict):
                    yield r


def check_canonical_types(label: str, payload, allow_parent_types=False) -> bool:
    """Assert every `type` field in fund rows is canonical. If
    allow_parent_types is True, parent-level rows (level=0 with N-PORT
    children) are skipped — they carry the institution-level `manager_type`
    taxonomy which is out of scope for PR-1d."""
    bad = []
    for r in _iter_fund_rows(payload):
        if allow_parent_types and r.get("level") == 0 and r.get("is_parent"):
            continue
        if "type" not in r:
            continue
        t = r.get("type")
        if t is None:
            bad.append(("None", r.get("institution") or r.get("fund_name")))
            continue
        if str(t).lower() not in CANONICAL_TYPES:
            # Parent rows are allowed to carry manager_type values; skip
            # them when allow_parent_types is set.
            if allow_parent_types and r.get("level") == 0:
                continue
            bad.append((t, r.get("institution") or r.get("fund_name")))
    if bad:
        for t, inst in bad[:5]:
            _fail(f"{label}: non-canonical type={t!r} on {inst!r}")
        if len(bad) > 5:
            _fail(f"{label}: …and {len(bad) - 5} more")
        return False
    _ok(f"{label}: all type values canonical")
    return True


def check_no_family_name_in_type(label: str, payload) -> bool:
    bad = []
    for r in _iter_fund_rows(payload):
        t = (r.get("type") or "")
        if str(t).lower() in KNOWN_FAMILY_NAMES:
            bad.append((t, r.get("investor") or r.get("fund_name")))
    if bad:
        for t, inst in bad[:5]:
            _fail(f"{label}: family name leaked into type={t!r} on {inst!r}")
        return False
    _ok(f"{label}: no fund family names in type column")
    return True


def check_no_is_active(label: str, payload) -> bool:
    bad = []
    for r in _iter_fund_rows(payload):
        if "is_active" in r:
            bad.append(r.get("fund_name") or r.get("institution"))
    if bad:
        _fail(f"{label}: is_active field present on {len(bad)} rows (e.g. {bad[:3]})")
        return False
    _ok(f"{label}: no is_active field on fund rows")
    return True


def check_no_raw_fund_strategy(label: str, payload) -> bool:
    bad = []
    for r in _iter_fund_rows(payload):
        if "fund_strategy" in r:
            bad.append(r.get("fund_name") or r.get("institution"))
    if bad:
        _fail(f"{label}: fund_strategy leaked into response on {len(bad)} rows (e.g. {bad[:3]})")
        return False
    _ok(f"{label}: no raw fund_strategy in response")
    return True


def main() -> int:
    if not FIXTURE_DB.exists():
        print(f"FAIL: fixture DB missing at {FIXTURE_DB}", file=sys.stderr)
        return 1
    os.environ["DB_PATH_OVERRIDE"] = str(FIXTURE_DB)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))

    from fastapi.testclient import TestClient
    import app as app_module
    client = TestClient(app_module.app)

    # Use the largest institution name in the fixture for the fund_detail probe.
    # 'Vanguard Group' is present in the AAPL holdings_v2 set.
    inst = "Vanguard Group"

    cases = [
        ("portfolio_context fund",
         "/api/v1/portfolio_context?ticker=AAPL&level=fund",
         ["canonical", "is_active_absent", "fund_strategy_absent"]),
        ("portfolio_context parent (N-PORT children)",
         "/api/v1/portfolio_context?ticker=AAPL&level=parent",
         ["canonical_with_parent_skip", "is_active_absent", "fund_strategy_absent"]),
        ("cross_ownership fund",
         "/api/v1/cross_ownership?tickers=AAPL&level=fund",
         ["canonical", "no_family_in_type", "is_active_absent",
          "fund_strategy_absent"]),
        ("cross_ownership_fund_detail",
         f"/api/v1/cross_ownership_fund_detail?tickers=AAPL&institution={inst}&anchor=AAPL",
         ["canonical", "is_active_absent", "fund_strategy_absent"]),
        ("holder_momentum fund",
         "/api/v1/holder_momentum?ticker=AAPL&level=fund",
         ["canonical", "is_active_absent", "fund_strategy_absent"]),
        ("holder_momentum parent (children)",
         "/api/v1/holder_momentum?ticker=AAPL&level=parent",
         ["canonical_with_parent_skip", "is_active_absent",
          "fund_strategy_absent"]),
        ("short_analysis (nport_detail / by_fund / short_only)",
         "/api/v1/short_analysis?ticker=AAPL",
         ["canonical", "is_active_absent", "fund_strategy_absent"]),
        ("query1 register (N-PORT children)",
         "/api/v1/query1?ticker=AAPL",
         ["canonical_with_parent_skip", "is_active_absent",
          "fund_strategy_absent"]),
    ]

    all_ok = True
    print("=" * 70)
    print("PR-1d classification display fix — endpoint contract validation")
    print("=" * 70)
    for label, url, checks in cases:
        print(f"\n* {label}")
        print(f"  GET {url}")
        resp = client.get(url)
        if resp.status_code != 200:
            _fail(f"HTTP {resp.status_code}: {resp.text[:200]}")
            all_ok = False
            continue
        try:
            body = resp.json()
        except json.JSONDecodeError:
            _fail("response is not JSON")
            all_ok = False
            continue
        payload = _payload(body)

        if "canonical" in checks:
            all_ok &= check_canonical_types(label, payload)
        if "canonical_with_parent_skip" in checks:
            all_ok &= check_canonical_types(label, payload,
                                            allow_parent_types=True)
        if "no_family_in_type" in checks:
            all_ok &= check_no_family_name_in_type(label, payload)
        if "is_active_absent" in checks:
            all_ok &= check_no_is_active(label, payload)
        if "fund_strategy_absent" in checks:
            all_ok &= check_no_raw_fund_strategy(label, payload)

    print("\n" + "=" * 70)
    print("RESULT:", "PASS" if all_ok else "FAIL")
    print("=" * 70)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
