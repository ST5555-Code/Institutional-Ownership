"""Tests for fund-typed ECH reader migration (PR-R1).

Pins reader behavior post-migration:
- queries.entities.get_entity_by_id and search_entity_parents resolve
  fund classification from fund_universe.fund_strategy via
  classify_fund_strategy() when entity_type='fund', not from
  entity_current.classification (which is dropping out as PR-C closes
  the legacy fund-typed ECH rows).
- build_entities.step2_create_fund_entities centralizes the
  fund_strategy → 'active'/'passive'/'unknown' mapping through the same
  helper.

Reference: docs/findings/fund-typed-ech-audit.md §7,
docs/decisions/d4-classification-precedence.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Shared DDL for reader-side tests
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
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

DDL_FUND_UNIVERSE = """
CREATE TABLE fund_universe (
    series_id     VARCHAR PRIMARY KEY,
    fund_name     VARCHAR,
    family_name   VARCHAR,
    fund_strategy VARCHAR
)
"""

DDL_ENTITY_CURRENT_VIEW = """
CREATE VIEW entity_current AS
SELECT
    e.entity_id,
    e.entity_type,
    e.created_at,
    COALESCE(ea.alias_name, e.canonical_name) AS display_name,
    ech.classification,
    ech.is_activist,
    ech.confidence AS classification_confidence,
    er.rollup_entity_id,
    er.rollup_type
FROM entities e
LEFT JOIN (
    SELECT entity_id, alias_name
    FROM entity_aliases
    WHERE is_preferred = TRUE AND valid_to = DATE '9999-12-31'
) ea ON e.entity_id = ea.entity_id
LEFT JOIN entity_classification_history ech
    ON e.entity_id = ech.entity_id
    AND ech.valid_to = DATE '9999-12-31'
LEFT JOIN entity_rollup_history er
    ON e.entity_id = er.entity_id
    AND er.rollup_type = 'economic_control_v1'
    AND er.valid_to = DATE '9999-12-31'
"""


def _seed_schema(con):
    con.execute(DDL_ENTITIES)
    con.execute(DDL_ECH)
    con.execute(DDL_IDENTIFIERS)
    con.execute(DDL_ALIASES)
    con.execute(DDL_ROLLUP)
    con.execute(DDL_FUND_UNIVERSE)
    con.execute(DDL_ENTITY_CURRENT_VIEW)


def _add_fund(con, eid, name, series_id, fund_strategy, *,
              with_rollup=True, with_ech=False, ech_classification=None):
    con.execute(
        "INSERT INTO entities (entity_id, entity_type, canonical_name, "
        "created_source, is_inferred) VALUES (?, 'fund', ?, 'fund_universe', TRUE)",
        [eid, name],
    )
    if series_id is not None:
        con.execute(
            "INSERT INTO entity_identifiers (entity_id, identifier_type, "
            "identifier_value, confidence, source, is_inferred, valid_from, "
            "valid_to) VALUES (?, 'series_id', ?, 'exact', 'fund_universe', "
            "FALSE, DATE '2000-01-01', DATE '9999-12-31')",
            [eid, series_id],
        )
        con.execute(
            "INSERT INTO fund_universe (series_id, fund_name, family_name, "
            "fund_strategy) VALUES (?, ?, ?, ?)",
            [series_id, name, name, fund_strategy],
        )
    if with_rollup:
        con.execute(
            "INSERT INTO entity_rollup_history (entity_id, rollup_entity_id, "
            "rollup_type, rule_applied, confidence, valid_from, valid_to, "
            "source, routing_confidence) VALUES "
            "(?, ?, 'economic_control_v1', 'self', 'exact', DATE '2000-01-01', "
            "DATE '9999-12-31', 'test', 'exact')",
            [eid, eid],
        )
    if with_ech:
        con.execute(
            "INSERT INTO entity_classification_history (entity_id, "
            "classification, is_activist, confidence, source, is_inferred, "
            "valid_from, valid_to) VALUES (?, ?, FALSE, 'inferred', 'legacy', "
            "TRUE, DATE '2000-01-01', DATE '9999-12-31')",
            [eid, ech_classification],
        )


def _add_institution(con, eid, name, classification, *, with_rollup=True):
    con.execute(
        "INSERT INTO entities (entity_id, entity_type, canonical_name, "
        "created_source, is_inferred) VALUES (?, 'institution', ?, 'managers', "
        "FALSE)",
        [eid, name],
    )
    con.execute(
        "INSERT INTO entity_classification_history (entity_id, classification, "
        "is_activist, confidence, source, is_inferred, valid_from, valid_to) "
        "VALUES (?, ?, FALSE, 'exact', 'managers', FALSE, DATE '2000-01-01', "
        "DATE '9999-12-31')",
        [eid, classification],
    )
    if with_rollup:
        con.execute(
            "INSERT INTO entity_rollup_history (entity_id, rollup_entity_id, "
            "rollup_type, rule_applied, confidence, valid_from, valid_to, "
            "source, routing_confidence) VALUES "
            "(?, ?, 'economic_control_v1', 'self', 'exact', DATE '2000-01-01', "
            "DATE '9999-12-31', 'test', 'exact')",
            [eid, eid],
        )


@pytest.fixture
def con(tmp_path):
    db = tmp_path / "reader_migration_test.duckdb"
    c = duckdb.connect(str(db))
    _seed_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# get_entity_by_id — institution baseline (unchanged)
# ---------------------------------------------------------------------------


class TestGetEntityByIdInstitutionUnchanged:
    def test_institution_returns_ech_classification_verbatim(self, con):
        from queries.entities import get_entity_by_id
        _add_institution(con, 200, "Test Institution", "active")
        row = get_entity_by_id(200, con)
        assert row is not None
        assert row['entity_type'] == 'institution'
        assert row['classification'] == 'active'

    def test_institution_passive_unchanged(self, con):
        from queries.entities import get_entity_by_id
        _add_institution(con, 201, "Passive Inst", "passive")
        row = get_entity_by_id(201, con)
        assert row['classification'] == 'passive'

    def test_institution_unknown_unchanged(self, con):
        from queries.entities import get_entity_by_id
        _add_institution(con, 202, "Unknown Inst", "unknown")
        row = get_entity_by_id(202, con)
        assert row['classification'] == 'unknown'


# ---------------------------------------------------------------------------
# get_entity_by_id — fund-typed migration
# ---------------------------------------------------------------------------


class TestGetEntityByIdFundMigration:
    @pytest.mark.parametrize("fund_strategy,expected", [
        ('active', 'active'),
        ('balanced', 'active'),
        ('multi_asset', 'active'),
        ('passive', 'passive'),
        ('bond_or_other', 'passive'),
        ('excluded', 'passive'),
        ('final_filing', 'passive'),
    ])
    def test_fund_classification_resolved_from_fund_universe(
        self, con, fund_strategy, expected,
    ):
        from queries.entities import get_entity_by_id
        eid = 1000 + hash(fund_strategy) % 1000
        _add_fund(con, eid, f"Fund {fund_strategy}", f"S-{fund_strategy}",
                  fund_strategy)
        row = get_entity_by_id(eid, con)
        assert row is not None
        assert row['entity_type'] == 'fund'
        assert row['classification'] == expected, (
            f"fund_strategy={fund_strategy!r} → {row['classification']!r}, "
            f"expected {expected!r}"
        )

    def test_fund_ignores_legacy_ech_row(self, con):
        """If a legacy fund-typed ECH row still exists (pre-PR-C), reader
        must take fund_universe as the authority and NOT return the ECH
        value.
        """
        from queries.entities import get_entity_by_id
        # ECH says 'passive', but fund_strategy says 'active'. Reader must
        # follow fund_universe.
        _add_fund(con, 300, "Mismatch Fund", "S-MISMATCH", "active",
                  with_ech=True, ech_classification="passive")
        row = get_entity_by_id(300, con)
        assert row['classification'] == 'active'

    def test_fund_with_no_series_id_identifier_returns_unknown(self, con):
        from queries.entities import get_entity_by_id
        _add_fund(con, 301, "Orphan Fund", series_id=None,
                  fund_strategy=None)
        row = get_entity_by_id(301, con)
        assert row['classification'] == 'unknown'

    def test_fund_with_series_id_no_fund_universe_row(self, con):
        from queries.entities import get_entity_by_id
        # Insert fund + series_id identifier, but skip fund_universe row.
        con.execute(
            "INSERT INTO entities (entity_id, entity_type, canonical_name, "
            "created_source, is_inferred) VALUES (?, 'fund', ?, "
            "'fund_universe', TRUE)",
            [302, "Fund Without Universe"],
        )
        con.execute(
            "INSERT INTO entity_identifiers (entity_id, identifier_type, "
            "identifier_value, confidence, source, is_inferred, valid_from, "
            "valid_to) VALUES (?, 'series_id', ?, 'exact', 'fund_universe', "
            "FALSE, DATE '2000-01-01', DATE '9999-12-31')",
            [302, "S-NO-UNIVERSE"],
        )
        row = get_entity_by_id(302, con)
        assert row['classification'] == 'unknown'

    def test_fund_with_null_fund_strategy_returns_unknown(self, con):
        from queries.entities import get_entity_by_id
        _add_fund(con, 303, "Null Strategy Fund", "S-NULL", None)
        row = get_entity_by_id(303, con)
        assert row['classification'] == 'unknown'

    def test_fund_with_closed_series_id_treated_as_no_identifier(self, con):
        """An identifier row whose valid_to is not the open sentinel must
        not be used to resolve fund_strategy.
        """
        from queries.entities import get_entity_by_id
        con.execute(
            "INSERT INTO entities (entity_id, entity_type, canonical_name, "
            "created_source, is_inferred) VALUES (?, 'fund', ?, "
            "'fund_universe', TRUE)",
            [304, "Fund With Closed Series Id"],
        )
        # Closed identifier (valid_to in the past).
        con.execute(
            "INSERT INTO entity_identifiers (entity_id, identifier_type, "
            "identifier_value, confidence, source, is_inferred, valid_from, "
            "valid_to) VALUES (?, 'series_id', ?, 'exact', 'fund_universe', "
            "FALSE, DATE '2000-01-01', DATE '2020-01-01')",
            [304, "S-CLOSED"],
        )
        con.execute(
            "INSERT INTO fund_universe (series_id, fund_name, family_name, "
            "fund_strategy) VALUES (?, ?, ?, ?)",
            ["S-CLOSED", "Should not be used", "Family", "active"],
        )
        row = get_entity_by_id(304, con)
        assert row['classification'] == 'unknown'


# ---------------------------------------------------------------------------
# search_entity_parents — must apply the same fund-typed branch
# ---------------------------------------------------------------------------


class TestSearchEntityParentsFundMigration:
    def _add_self_rollup_alias(self, con, eid, alias):
        con.execute(
            "INSERT INTO entity_aliases (entity_id, alias_name, alias_type, "
            "is_preferred, preferred_key, source_table, is_inferred, "
            "valid_from, valid_to) VALUES "
            "(?, ?, 'preferred', TRUE, ?, 'test', FALSE, DATE '2000-01-01', "
            "DATE '9999-12-31')",
            [eid, alias, eid],
        )

    def test_institution_match_returns_ech_classification(self, con):
        from queries.entities import search_entity_parents
        _add_institution(con, 400, "Acme Capital Partners", "active")
        results = search_entity_parents("Acme", con)
        match = [r for r in results if r['entity_id'] == 400]
        assert match, "expected Acme institution to match"
        assert match[0]['classification'] == 'active'

    def test_fund_match_returns_helper_mapped_classification(self, con):
        from queries.entities import search_entity_parents
        _add_fund(con, 401, "Vanguard Total Bond Fund", "S-VBT",
                  "bond_or_other")
        results = search_entity_parents("Vanguard", con)
        match = [r for r in results if r['entity_id'] == 401]
        assert match, "expected Vanguard fund to match"
        assert match[0]['classification'] == 'passive'

    def test_fund_match_active_strategy(self, con):
        from queries.entities import search_entity_parents
        _add_fund(con, 402, "Dodge & Cox Stock", "S-DODSX", "active")
        results = search_entity_parents("Dodge", con)
        match = [r for r in results if r['entity_id'] == 402]
        assert match
        assert match[0]['classification'] == 'active'

    def test_fund_match_with_legacy_ech_ignored(self, con):
        from queries.entities import search_entity_parents
        _add_fund(con, 403, "Mismatch Search Fund", "S-MISMSEARCH",
                  "passive", with_ech=True, ech_classification="active")
        results = search_entity_parents("Mismatch", con)
        match = [r for r in results if r['entity_id'] == 403]
        assert match
        assert match[0]['classification'] == 'passive'


# ---------------------------------------------------------------------------
# build_entities.step2_create_fund_entities uses the helper
# ---------------------------------------------------------------------------


class TestStep2UsesClassifyFundStrategy:
    """step2_create_fund_entities must surface classify_fund_strategy()
    output in the 5th column of fund_entity_rows, replacing the inline
    SQL CASE that produced a tri-state boolean. The previous boolean was
    not consumed downstream (step5 destructures as `_active`, step6 body
    is a no-op per PR #263), so this is purely centralization.
    """

    @pytest.fixture
    def step2_con(self, tmp_path):
        c = duckdb.connect(str(tmp_path / "step2_test.duckdb"))
        c.execute(DDL_ENTITIES)
        c.execute(DDL_FUND_UNIVERSE)
        c.execute("CREATE SEQUENCE entity_id_seq START 1")
        yield c
        c.close()

    @pytest.mark.parametrize("fund_strategy,expected", [
        ('active', 'active'),
        ('balanced', 'active'),
        ('multi_asset', 'active'),
        ('passive', 'passive'),
        ('bond_or_other', 'passive'),
        ('excluded', 'passive'),
        ('final_filing', 'passive'),
        (None, 'unknown'),
    ])
    def test_fund_rows_carry_helper_classification(
        self, step2_con, fund_strategy, expected,
    ):
        from build_entities import step2_create_fund_entities
        step2_con.execute(
            "INSERT INTO fund_universe (series_id, fund_name, family_name, "
            "fund_strategy) VALUES (?, ?, ?, ?)",
            ["S-1", "Test Fund", "Test Family", fund_strategy],
        )
        _series_to_eid, fund_rows = step2_create_fund_entities(step2_con)
        assert len(fund_rows) == 1
        # Tuple shape: (eid, series_id, fund_name, family_name, classification)
        assert fund_rows[0][4] == expected, (
            f"fund_strategy={fund_strategy!r} → step2 returned "
            f"{fund_rows[0][4]!r}, expected {expected!r}"
        )

    def test_fund_rows_match_classify_fund_strategy_helper(self, step2_con):
        """The 5th column must equal classify_fund_strategy(strategy) for
        every row — pins the centralization contract.
        """
        from build_entities import step2_create_fund_entities
        from queries.common import classify_fund_strategy

        cases = [
            ("S-A", "active"),
            ("S-B", "balanced"),
            ("S-C", "multi_asset"),
            ("S-D", "passive"),
            ("S-E", "bond_or_other"),
            ("S-F", "excluded"),
            ("S-G", "final_filing"),
            ("S-H", None),
        ]
        for series_id, strat in cases:
            step2_con.execute(
                "INSERT INTO fund_universe (series_id, fund_name, "
                "family_name, fund_strategy) VALUES (?, ?, ?, ?)",
                [series_id, f"Fund {series_id}", "Test", strat],
            )

        _, fund_rows = step2_create_fund_entities(step2_con)
        rows_by_series = {r[1]: r for r in fund_rows}
        for series_id, strat in cases:
            assert rows_by_series[series_id][4] == classify_fund_strategy(
                strat
            ), series_id
