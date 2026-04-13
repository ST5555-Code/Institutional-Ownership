"""Phase 0-B2 smoke endpoint tests.

Two test suites per endpoint:

  test_smoke_endpoint_ok          — HTTP 200 + non-empty JSON body.
  test_smoke_response_equality    — response matches the committed
                                    snapshot on (a) top-level keys,
                                    (b) list-typed row counts within ±5%,
                                    (c) an endpoint-specific sentinel value.

Snapshots live at tests/fixtures/responses/<endpoint>.json. Regenerate via
`python tests/smoke/capture_snapshots.py --update` after an intentional
shape change — not on test failure.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from .endpoints import ENDPOINTS

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "responses"
TOLERANCE = 0.05  # ±5 % row count

# Endpoint-specific sentinel predicates. Each returns True when the
# response contains at least one known-good value that would be absent
# after a broken schema rename or dropped field.
SENTINELS = {
    "tickers":      lambda body: any(
        isinstance(r, dict) and r.get("ticker") == "AAPL" for r in (body or [])
    ),
    # query1 response is {rows, all_totals, type_totals} — no ticker echo.
    # Sentinel: Vanguard Group appears in the register for AAPL.
    "query1":       lambda body: isinstance(body, dict)
                                  and isinstance(body.get("rows"), list)
                                  and any(
                                      isinstance(r, dict) and r.get("institution") == "Vanguard Group"
                                      for r in body["rows"]
                                  ),
    "summary":      lambda body: isinstance(body, dict)
                                  and (body.get("ticker") or "").upper() == "AAPL",
    "entity_graph": lambda body: isinstance(body, dict)
                                  and isinstance(body.get("nodes"), list)
                                  and len(body["nodes"]) > 0,
}


@pytest.mark.parametrize("name,path", list(ENDPOINTS.items()))
def test_smoke_endpoint_ok(client, name, path):
    resp = client.get(path)
    assert resp.status_code == 200, (
        f"{name}: HTTP {resp.status_code} body={resp.data[:200]!r}"
    )
    body = resp.get_json()
    assert body, f"{name}: empty JSON body"


@pytest.mark.parametrize("name,path", list(ENDPOINTS.items()))
def test_smoke_response_equality(client, name, path):
    snap = SNAPSHOT_DIR / f"{name}.json"
    if not snap.exists():
        pytest.skip(
            f"no snapshot at {snap} — run `python tests/smoke/capture_snapshots.py --update`"
        )
    expected = json.loads(snap.read_text())
    actual = client.get(path).get_json()
    _assert_keys_match(name, actual, expected)
    _assert_row_counts(name, actual, expected)
    _assert_sentinel(name, actual)


# ── Assertion helpers ──────────────────────────────────────────────────────


def _assert_keys_match(name: str, actual, expected) -> None:
    if isinstance(expected, list):
        assert isinstance(actual, list), (
            f"{name}: expected list, got {type(actual).__name__}"
        )
        return
    assert isinstance(actual, dict), (
        f"{name}: expected dict, got {type(actual).__name__}"
    )
    exp_keys, act_keys = set(expected.keys()), set(actual.keys())
    missing = exp_keys - act_keys
    extra = act_keys - exp_keys
    assert not missing and not extra, (
        f"{name}: key drift — missing={sorted(missing)} extra={sorted(extra)}"
    )


def _assert_row_counts(name: str, actual, expected) -> None:
    def _counts(obj):
        if isinstance(obj, list):
            return {"__root__": len(obj)}
        return {k: len(v) for k, v in obj.items() if isinstance(v, list)}

    exp_counts = _counts(expected)
    act_counts = _counts(actual)
    for k, exp_n in exp_counts.items():
        act_n = act_counts.get(k, 0)
        if exp_n == 0:
            assert act_n == 0, f"{name}.{k}: count {act_n} expected 0"
            continue
        lo = int(exp_n * (1 - TOLERANCE))
        hi = int(exp_n * (1 + TOLERANCE)) + 1
        assert lo <= act_n <= hi, (
            f"{name}.{k}: row count {act_n} outside ±{int(TOLERANCE*100)}% of {exp_n}"
        )


def _assert_sentinel(name: str, actual) -> None:
    check = SENTINELS.get(name)
    assert check is not None, f"{name}: no sentinel defined"
    assert check(actual), f"{name}: sentinel check failed"
