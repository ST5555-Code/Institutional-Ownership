"""Tests for the fund-typed ECH writer-disable gates.

Bundled writer-disable PR closes 6 producer paths + the resolve_long_tail
queue filter so that no live code path can stamp an open
entity_classification_history row whose entity is entity_type='fund'.
Reference: docs/findings/fund-typed-ech-audit.md §7,
docs/decisions/d4-classification-precedence.md.

The 8 tests below pin one gate each. Each test seeds an isolated DuckDB
with the minimum schema the writer touches, exercises the writer with a
fund-typed target, and asserts no ECH row was produced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Shared DDL — minimum schema the writer paths touch.
# ---------------------------------------------------------------------------

DDL_ENTITIES = """
CREATE TABLE entities (
    entity_id      BIGINT PRIMARY KEY,
    entity_type    VARCHAR,
    canonical_name VARCHAR,
    created_source VARCHAR,
    is_inferred    BOOLEAN,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_ECH = """
CREATE TABLE entity_classification_history (
    entity_id      BIGINT,
    classification VARCHAR,
    is_activist    BOOLEAN,
    confidence     VARCHAR,
    source         VARCHAR,
    is_inferred    BOOLEAN,
    valid_from     DATE,
    valid_to       DATE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_IDENTIFIERS = """
CREATE TABLE entity_identifiers (
    entity_id        BIGINT,
    identifier_type  VARCHAR,
    identifier_value VARCHAR,
    confidence       VARCHAR,
    source           VARCHAR,
    is_inferred      BOOLEAN,
    valid_from       DATE DEFAULT DATE '2000-01-01',
    valid_to         DATE DEFAULT DATE '9999-12-31',
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (identifier_type, identifier_value, valid_to)
)
"""

DDL_ALIASES = """
CREATE TABLE entity_aliases (
    entity_id     BIGINT,
    alias_name    VARCHAR,
    alias_type    VARCHAR,
    is_preferred  BOOLEAN,
    preferred_key BIGINT,
    source_table  VARCHAR,
    is_inferred   BOOLEAN,
    valid_from    DATE,
    valid_to      DATE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_RELATIONSHIPS = """
CREATE TABLE entity_relationships (
    relationship_id    BIGINT PRIMARY KEY,
    parent_entity_id   BIGINT,
    child_entity_id    BIGINT,
    relationship_type  VARCHAR,
    control_type       VARCHAR,
    is_primary         BOOLEAN,
    primary_parent_key BIGINT,
    confidence         VARCHAR,
    source             VARCHAR,
    is_inferred        BOOLEAN,
    valid_from         DATE,
    valid_to           DATE,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_refreshed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_ROLLUP = """
CREATE TABLE entity_rollup_history (
    entity_id          BIGINT,
    rollup_entity_id   BIGINT,
    rollup_type        VARCHAR,
    rule_applied       VARCHAR,
    confidence         VARCHAR,
    valid_from         DATE,
    valid_to           DATE,
    computed_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source             VARCHAR,
    routing_confidence VARCHAR,
    review_due_date    DATE
)
"""

DDL_OVERRIDES = """
CREATE TABLE entity_overrides_persistent (
    override_id          BIGINT PRIMARY KEY,
    entity_cik           VARCHAR,
    action               VARCHAR,
    field                VARCHAR,
    old_value            VARCHAR,
    new_value            VARCHAR,
    reason               VARCHAR,
    analyst              VARCHAR,
    still_valid          BOOLEAN,
    applied_at           TIMESTAMP,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    identifier_type      VARCHAR,
    identifier_value     VARCHAR,
    rollup_type          VARCHAR,
    relationship_context VARCHAR
)
"""


def _open_count(con, entity_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM entity_classification_history "
        "WHERE entity_id = ? AND valid_to = DATE '9999-12-31'",
        [entity_id],
    ).fetchone()[0]


def _seed_entities(con, fund_eid: int = 100, inst_eid: int = 200) -> None:
    """Seed one fund-typed and one institution-typed entity."""
    con.execute(DDL_ENTITIES)
    con.execute(DDL_ECH)
    con.execute(
        "INSERT INTO entities (entity_id, entity_type, canonical_name, "
        "created_source, is_inferred) VALUES (?, ?, ?, ?, ?)",
        [fund_eid, "fund", "Test Fund Series", "fund_universe", True],
    )
    con.execute(
        "INSERT INTO entities (entity_id, entity_type, canonical_name, "
        "created_source, is_inferred) VALUES (?, ?, ?, ?, ?)",
        [inst_eid, "institution", "Test Institution", "managers", False],
    )


@pytest.fixture
def con(tmp_path):
    """Isolated DuckDB with entities + ECH seeded with one fund + one inst."""
    db = tmp_path / "writer_gate_test.duckdb"
    c = duckdb.connect(str(db))
    _seed_entities(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Test 1 — _insert_cls fund-typed guard (Gate 1, choke-point)
# ---------------------------------------------------------------------------


class TestInsertClsFundGuard:
    """build_entities._insert_cls is the shared INSERT helper for step 6.
    A fund-typed entity_id passed to it must short-circuit and write nothing.
    """

    def test_fund_typed_eid_writes_no_row(self, con):
        # Arrange — exercise the helper as step6 does. We simulate the
        # closure by replicating the helper's wiring locally.
        from build_entities import step6_populate_classifications  # noqa: E402

        # Put fund_eid in the fund_rows tuple list — this is the route
        # step6 uses to call _insert_cls for funds.
        fund_rows = [(100, 'S001', 'Test Fund', 'Test Family', True)]
        step6_populate_classifications(
            con, seeds=[], seed_map={}, manager_rows=[], fund_rows=fund_rows,
        )

        # Assert — no ECH row stamped for the fund eid
        assert _open_count(con, 100) == 0, (
            "Gate 1 failed: _insert_cls wrote an ECH row for entity_type='fund'"
        )


# ---------------------------------------------------------------------------
# Test 2 — step6 fund_rows loop is a no-op (Gate 2)
# ---------------------------------------------------------------------------


class TestStep6FundRowsLoopIsNoop:
    """The step6 loop iterating fund_rows previously called _insert_cls
    for every fund. After the gate, the loop must not produce ECH rows
    even if the helper guard were absent.
    """

    def test_step6_fund_rows_loop_inserts_zero(self, con):
        from build_entities import step6_populate_classifications  # noqa: E402

        fund_rows = [
            (100, 'S001', 'Test Fund A', 'Family A', True),   # active
            (100, 'S002', 'Test Fund B', 'Family B', False),  # passive
        ]
        step6_populate_classifications(
            con, seeds=[], seed_map={}, manager_rows=[], fund_rows=fund_rows,
        )

        total_fund_rows = con.execute(
            "SELECT COUNT(*) FROM entity_classification_history "
            "WHERE source = 'fund_universe'"
        ).fetchone()[0]
        assert total_fund_rows == 0, (
            "Gate 2 failed: step6 fund_rows loop produced "
            f"{total_fund_rows} fund_universe ECH rows"
        )


# ---------------------------------------------------------------------------
# Test 3 — step6 'remaining' loop excludes funds (Gate 3)
# ---------------------------------------------------------------------------


class TestStep6RemainingLoopExcludesFunds:
    """The step6 'remaining' query previously selected ALL entities lacking
    classification — including fund-typed ones — and stamped them
    'unknown' / source='default_unknown'. After the gate, only
    institution-typed entities should land in default_unknown.
    """

    def test_remaining_loop_skips_funds_includes_institutions(self, con):
        from build_entities import step6_populate_classifications  # noqa: E402

        # No fund_rows / manager_rows — both fund (100) and inst (200) are
        # unclassified entering step6.
        step6_populate_classifications(
            con, seeds=[], seed_map={}, manager_rows=[], fund_rows=[],
        )

        fund_default_unknown = con.execute(
            "SELECT COUNT(*) FROM entity_classification_history "
            "WHERE entity_id = ? AND source = 'default_unknown'",
            [100],
        ).fetchone()[0]
        inst_default_unknown = con.execute(
            "SELECT COUNT(*) FROM entity_classification_history "
            "WHERE entity_id = ? AND source = 'default_unknown'",
            [200],
        ).fetchone()[0]

        assert fund_default_unknown == 0, (
            "Gate 3 failed: 'remaining' loop wrote default_unknown for fund"
        )
        assert inst_default_unknown == 1, (
            "Gate 3 over-applied: institution lost its default_unknown row"
        )


# ---------------------------------------------------------------------------
# Test 4 — replay_persistent_overrides skips fund targets (Gate 4)
# ---------------------------------------------------------------------------


class TestReplayPersistentOverridesSkipsFunds:
    """A reclassify-action override targeting a fund-typed entity must
    not stamp an ECH row even if the override is still_valid=TRUE."""

    def test_reclassify_against_fund_eid_writes_no_ech(self, con):
        from build_entities import replay_persistent_overrides  # noqa: E402

        con.execute(DDL_IDENTIFIERS)
        con.execute(DDL_OVERRIDES)
        # Bind the override to fund eid via series_id identifier
        con.execute(
            "INSERT INTO entity_identifiers (entity_id, identifier_type, "
            "identifier_value, valid_to) VALUES (?, ?, ?, DATE '9999-12-31')",
            [100, 'series_id', 'S0FUNDX'],
        )
        con.execute(
            "INSERT INTO entity_overrides_persistent "
            "(override_id, entity_cik, action, field, old_value, new_value, "
            " reason, analyst, still_valid, identifier_type, identifier_value) "
            "VALUES (?, ?, 'reclassify', 'classification', ?, ?, ?, ?, TRUE, "
            " 'series_id', ?)",
            [1, None, 'unknown', 'active', 'Test', 'analyst', 'S0FUNDX'],
        )

        replay_persistent_overrides(con)

        assert _open_count(con, 100) == 0, (
            "Gate 4 failed: replay_persistent_overrides wrote ECH for fund"
        )


# ---------------------------------------------------------------------------
# Test 5 — resolve_pending_series.wire_fund_entity skips ECH write (Gate 5)
# ---------------------------------------------------------------------------


class TestWireFundEntitySkipsECH:
    """wire_fund_entity must continue to create the entity, identifier,
    alias, relationship, and rollup rows but must not stamp ECH."""

    def test_wire_fund_entity_creates_no_ech_row(self, tmp_path):
        from resolve_pending_series import (  # noqa: E402
            wire_fund_entity, Pending, Decision, Stats,
        )

        db = tmp_path / "wire_fund_test.duckdb"
        con = duckdb.connect(str(db))
        try:
            con.execute(DDL_ENTITIES)
            con.execute(DDL_ECH)
            con.execute(DDL_IDENTIFIERS)
            con.execute(DDL_ALIASES)
            con.execute(DDL_RELATIONSHIPS)
            con.execute(DDL_ROLLUP)
            con.execute("CREATE SEQUENCE entity_id_seq START 1000")
            con.execute("CREATE SEQUENCE relationship_id_seq START 1")
            # Adviser (institution) parent
            con.execute(
                "INSERT INTO entities (entity_id, entity_type, canonical_name, "
                "created_source, is_inferred) VALUES (?, ?, ?, ?, ?)",
                [500, 'institution', 'Test Adviser', 'managers', False],
            )

            p = Pending(
                series_id='S99NEW', fund_cik='0001234567',
                fund_name='New Test Fund', family_name='Test Family',
                is_actively_managed=True, is_synthetic=False,
            )
            d = Decision(
                series_id='S99NEW', tier='T1', adviser_entity_id=500,
                confidence='high', score=95,
            )
            s = Stats()

            ok = wire_fund_entity(con, p, d, source='nport_test', stats=s)

            # The function should still succeed — it creates the fund.
            assert ok, "wire_fund_entity should still wire the fund entity"
            new_eid = d.new_fund_entity_id
            assert new_eid is not None, "wire_fund_entity must allocate a fund eid"
            # Sibling writes still happen
            assert con.execute(
                "SELECT COUNT(*) FROM entity_aliases WHERE entity_id = ? "
                "AND valid_to = DATE '9999-12-31'", [new_eid],
            ).fetchone()[0] == 1
            # ECH write must NOT happen
            assert _open_count(con, new_eid) == 0, (
                "Gate 5 failed: wire_fund_entity stamped an ECH row"
            )
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Test 6 — admin_bp CSV reclassify rejects fund eids (Gate 6)
# ---------------------------------------------------------------------------


class TestAdminCsvRejectsFundEids:
    """The /entity_override CSV reclassify handler must reject any row
    whose entity_id resolves to entity_type='fund' before any DB writes.
    Tested directly against the gate helper to keep the unit isolated
    from FastAPI session machinery.
    """

    def test_validate_helper_returns_fund_eids(self, con):
        from admin_bp import _validate_no_fund_reclassify_targets  # noqa: E402

        # Fund eid (100) must be flagged. Institution eid (200) must not.
        flagged = _validate_no_fund_reclassify_targets(con, [200, 100])
        assert flagged == [100], (
            "Gate 6 helper failed: should return fund-typed eids only"
        )

    def test_validate_helper_returns_empty_for_inst_only(self, con):
        from admin_bp import _validate_no_fund_reclassify_targets  # noqa: E402

        flagged = _validate_no_fund_reclassify_targets(con, [200])
        assert flagged == [], (
            "Gate 6 helper false positive: institution-only input flagged"
        )


# ---------------------------------------------------------------------------
# Test 7 — entity_sync.update_classification_from_sic guards funds (Gate 7)
# ---------------------------------------------------------------------------


class TestUpdateClassificationFromSicGuardsFunds:
    """update_classification_from_sic must early-return for fund-typed
    entities even when SIC code maps to a known classification and the
    current row is 'unknown'.
    """

    def test_fund_typed_entity_writes_no_new_ech(self, con):
        from entity_sync import update_classification_from_sic  # noqa: E402

        # Seed an existing 'unknown' open ECH row for the fund (preconditions
        # for the function's body to fire if the guard were absent).
        con.execute(
            "INSERT INTO entity_classification_history "
            "(entity_id, classification, is_activist, confidence, source, "
            " is_inferred, valid_from, valid_to) "
            "VALUES (?, 'unknown', FALSE, 'low', 'default_unknown', TRUE, "
            "DATE '2000-01-01', DATE '9999-12-31')",
            [100],
        )

        # SIC 6211 maps to 'active' per _SIC_CLASSIFICATION_MAP. Without
        # the guard, this would close the open 'unknown' row and insert
        # a new 'active' row.
        result = update_classification_from_sic(con, 100, '6211')

        assert result is False, (
            "Gate 7 failed: update_classification_from_sic should skip funds"
        )
        # Exactly one open row, still unknown, source still default_unknown
        rows = con.execute(
            "SELECT classification, source FROM entity_classification_history "
            "WHERE entity_id = ? AND valid_to = DATE '9999-12-31'", [100],
        ).fetchall()
        assert rows == [('unknown', 'default_unknown')], (
            "Gate 7 failed: ECH row was modified for fund-typed entity"
        )


# ---------------------------------------------------------------------------
# Test 8 — resolve_long_tail.get_unresolved_ciks filters funds (Gate 8)
# ---------------------------------------------------------------------------


class TestGetUnresolvedCiksFiltersFunds:
    """The long-tail resolution worker queue must not include fund-typed
    eids. Pre-PR-C they may still have an open 'unknown' ECH row, but
    post-PR these eids should drop from the queue at the SQL level.
    """

    def test_queue_excludes_fund_typed_ciks(self, tmp_path):
        from resolve_long_tail import get_unresolved_ciks  # noqa: E402

        db = tmp_path / "longtail_test.duckdb"
        con = duckdb.connect(str(db))
        try:
            con.execute(DDL_ENTITIES)
            con.execute(DDL_ECH)
            con.execute(DDL_IDENTIFIERS)
            con.execute(DDL_ROLLUP)

            con.execute(
                "INSERT INTO entities (entity_id, entity_type, canonical_name, "
                "created_source, is_inferred) VALUES (?, ?, ?, ?, ?)",
                [100, 'fund', 'Fund A', 'fund_universe', True],
            )
            con.execute(
                "INSERT INTO entities (entity_id, entity_type, canonical_name, "
                "created_source, is_inferred) VALUES (?, ?, ?, ?, ?)",
                [200, 'institution', 'Inst A', 'managers', False],
            )

            for eid, cik in [(100, '0000000100'), (200, '0000000200')]:
                con.execute(
                    "INSERT INTO entity_identifiers (entity_id, identifier_type, "
                    "identifier_value, valid_to) VALUES (?, 'cik', ?, "
                    "DATE '9999-12-31')",
                    [eid, cik],
                )
                con.execute(
                    "INSERT INTO entity_classification_history "
                    "(entity_id, classification, is_activist, confidence, "
                    " source, is_inferred, valid_from, valid_to) VALUES "
                    "(?, 'unknown', FALSE, 'low', 'default_unknown', TRUE, "
                    "DATE '2000-01-01', DATE '9999-12-31')",
                    [eid],
                )
                con.execute(
                    "INSERT INTO entity_rollup_history "
                    "(entity_id, rollup_entity_id, rollup_type, rule_applied, "
                    " confidence, valid_from, valid_to) VALUES "
                    "(?, ?, 'economic_control_v1', 'self', 'exact', "
                    "DATE '2000-01-01', DATE '9999-12-31')",
                    [eid, eid],
                )

            rows = get_unresolved_ciks(con)
            ciks = [r[0] for r in rows]

            assert '0000000200' in ciks, (
                "Gate 8 over-applied: institution-typed CIK was excluded"
            )
            assert '0000000100' not in ciks, (
                "Gate 8 failed: fund-typed CIK still in long-tail queue"
            )
        finally:
            con.close()
