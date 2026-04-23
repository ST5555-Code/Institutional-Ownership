"""Unit tests for scripts/queries_helpers.py.

Golden-string tests for the Tier 4 join-pattern helper library introduced in
the int-09 Step 4 forward-compat proposal
(docs/proposals/tier-4-join-pattern-proposal.md, merged via PR #113).

Helpers are pure-Python string assembly with no side effects. These tests
pin the exact output so callers can rely on stable SQL fragments.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# ticker_join
# ---------------------------------------------------------------------------


class TestTickerJoin:
    def test_default_aliases(self):
        import queries_helpers as qh  # noqa: E402
        assert qh.ticker_join() == "JOIN securities s ON s.cusip = h.cusip"

    def test_custom_holdings_alias(self):
        import queries_helpers as qh
        got = qh.ticker_join(h="holdings")
        assert got == "JOIN securities s ON s.cusip = holdings.cusip"

    def test_custom_securities_alias(self):
        import queries_helpers as qh
        got = qh.ticker_join(h="h", s="sec")
        assert got == "JOIN securities sec ON sec.cusip = h.cusip"


# ---------------------------------------------------------------------------
# entity_join
# ---------------------------------------------------------------------------


class TestEntityJoin:
    def test_default_entity_id_path(self):
        import queries_helpers as qh
        assert qh.entity_join() == "LEFT JOIN entity_current ec ON ec.entity_id = h.entity_id"

    def test_custom_alias(self):
        import queries_helpers as qh
        got = qh.entity_join(h="holdings", ec="mgr")
        assert got == "LEFT JOIN entity_current mgr ON mgr.entity_id = holdings.entity_id"

    def test_via_cik_forward_compat_path(self):
        import queries_helpers as qh
        got = qh.entity_join(via="cik")
        # Golden string: identifier_type='cik' on the entity_identifiers leg,
        # valid_to sentinel for open rows, then the entity_current lookup.
        assert got == (
            "LEFT JOIN entity_identifiers ei_ec "
            "  ON ei_ec.identifier_type = 'cik' "
            " AND ei_ec.identifier_value = h.cik "
            " AND ei_ec.valid_to = DATE '9999-12-31' "
            "LEFT JOIN entity_current ec ON ec.entity_id = ei_ec.entity_id"
        )

    def test_invalid_via_raises(self):
        import queries_helpers as qh
        with pytest.raises(ValueError):
            qh.entity_join(via="crd")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# rollup_join
# ---------------------------------------------------------------------------


class TestRollupJoin:
    def test_economic_control_v1(self):
        import queries_helpers as qh
        got = qh.rollup_join(worldview="economic_control_v1")
        assert got == (
            "LEFT JOIN entity_current ec_rollup "
            "  ON ec_rollup.entity_id = ec.rollup_entity_id"
        )

    def test_default_worldview_is_economic_control(self):
        import queries_helpers as qh
        assert qh.rollup_join() == qh.rollup_join(worldview="economic_control_v1")

    def test_decision_maker_v1_bypasses_view(self):
        import queries_helpers as qh
        got = qh.rollup_join(worldview="decision_maker_v1")
        # DM path must hit entity_rollup_history directly because
        # entity_current hardcodes rollup_type='economic_control_v1'
        # (see §6.3 of the proposal).
        assert "entity_rollup_history" in got
        assert "decision_maker_v1" in got
        assert "valid_to = DATE '9999-12-31'" in got
        # Full golden string:
        assert got == (
            "LEFT JOIN entity_rollup_history erh_ec_rollup "
            "  ON erh_ec_rollup.entity_id = h.entity_id "
            " AND erh_ec_rollup.rollup_type = 'decision_maker_v1' "
            " AND erh_ec_rollup.valid_to = DATE '9999-12-31' "
            "LEFT JOIN entity_current ec_rollup "
            "  ON ec_rollup.entity_id = erh_ec_rollup.rollup_entity_id"
        )

    def test_unknown_worldview_raises(self):
        import queries_helpers as qh
        with pytest.raises(ValueError):
            qh.rollup_join(worldview="control_chain_v2")  # type: ignore[arg-type]

    def test_empty_worldview_raises(self):
        import queries_helpers as qh
        with pytest.raises(ValueError):
            qh.rollup_join(worldview="")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# classification_join
# ---------------------------------------------------------------------------


class TestClassificationJoin:
    def test_default(self):
        import queries_helpers as qh
        got = qh.classification_join()
        assert got == (
            "LEFT JOIN entity_classification_history ech "
            "  ON ech.entity_id = h.entity_id "
            " AND ech.valid_to = DATE '9999-12-31'"
        )

    def test_custom_alias(self):
        import queries_helpers as qh
        got = qh.classification_join(ec="cls", h="holdings")
        assert "cls.entity_id = holdings.entity_id" in got
        assert "cls.valid_to = DATE '9999-12-31'" in got


# ---------------------------------------------------------------------------
# Module-level purity
# ---------------------------------------------------------------------------


class TestNoSideEffects:
    def test_import_is_silent_and_pure(self):
        # Drop any cached import so we measure a fresh one.
        sys.modules.pop("queries_helpers", None)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            import queries_helpers  # noqa: F401
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == ""

    def test_helpers_are_functions_not_values(self):
        import queries_helpers as qh
        for name in ("ticker_join", "entity_join", "rollup_join", "classification_join"):
            assert callable(getattr(qh, name)), f"{name} should be callable"
