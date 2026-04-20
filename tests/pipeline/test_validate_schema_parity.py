"""Unit tests for scripts/pipeline/validate_schema_parity.py."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))

import validate_schema_parity as vsp  # noqa: E402


# ---------------------------------------------------------------------------
# DDL whitespace normalizer
# ---------------------------------------------------------------------------


class TestDDLWhitespaceNormalizer:
    def test_collapses_multi_space(self):
        assert vsp.normalize_ddl_whitespace("CREATE  TABLE   foo ( a INT )") \
            == "CREATE TABLE foo ( a INT )"

    def test_normalizes_line_endings(self):
        assert vsp.normalize_ddl_whitespace("CREATE TABLE foo\r\n(a INT)") \
            == vsp.normalize_ddl_whitespace("CREATE TABLE foo\n(a INT)")

    def test_trims_trailing_semicolon(self):
        assert vsp.normalize_ddl_whitespace("CREATE TABLE foo(a INT);") \
            == "CREATE TABLE foo(a INT)"

    def test_empty_string(self):
        assert vsp.normalize_ddl_whitespace("") == ""

    def test_whitespace_only(self):
        assert vsp.normalize_ddl_whitespace("   \t\n  ") == ""


# ---------------------------------------------------------------------------
# PK ↔ UNIQUE-index equivalence normalizer
# ---------------------------------------------------------------------------


class TestPKIndexEquivalence:
    def test_prod_pk_matches_staging_unique_index_on_same_cols(self):
        prod_c = [{"constraint_type": "PRIMARY KEY",
                   "constraint_text": "PRIMARY KEY(ticker, as_of_date)"}]
        prod_i = []
        stg_c = []
        stg_i = [{"index_name": "idx_soh_pk",
                  "is_unique": True, "is_primary": False,
                  "sql": "CREATE UNIQUE INDEX idx_soh_pk ON t(ticker, as_of_date);"}]

        pc, pi, sc, si = vsp.normalize_pk_index_equivalence(prod_c, prod_i, stg_c, stg_i)
        assert pc == []  # PK dropped from prod
        assert si == []  # UNIQUE index dropped from staging
        assert pi == []
        assert sc == []

    def test_column_order_flexibility(self):
        """PK and index on same cols but different listed order still pair."""
        prod_c = [{"constraint_type": "PRIMARY KEY",
                   "constraint_text": "PRIMARY KEY(a, b)"}]
        stg_i = [{"index_name": "idx_pk",
                  "is_unique": True, "is_primary": False,
                  "sql": "CREATE UNIQUE INDEX idx_pk ON t(b, a);"}]
        pc, _, _, si = vsp.normalize_pk_index_equivalence(prod_c, [], [], stg_i)
        assert pc == []
        assert si == []

    def test_reverse_direction_staging_pk_prod_index(self):
        stg_c = [{"constraint_type": "PRIMARY KEY",
                  "constraint_text": "PRIMARY KEY(x)"}]
        prod_i = [{"index_name": "idx_x", "is_unique": True, "is_primary": False,
                   "sql": "CREATE UNIQUE INDEX idx_x ON t(x);"}]
        _, pi, sc, _ = vsp.normalize_pk_index_equivalence([], prod_i, stg_c, [])
        assert pi == []
        assert sc == []

    def test_different_columns_do_not_pair(self):
        prod_c = [{"constraint_type": "PRIMARY KEY",
                   "constraint_text": "PRIMARY KEY(a)"}]
        stg_i = [{"index_name": "idx_b", "is_unique": True, "is_primary": False,
                  "sql": "CREATE UNIQUE INDEX idx_b ON t(b);"}]
        pc, _, _, si = vsp.normalize_pk_index_equivalence(prod_c, [], [], stg_i)
        assert pc == prod_c  # PK stays
        assert si == stg_i  # index stays

    def test_non_unique_index_does_not_pair(self):
        prod_c = [{"constraint_type": "PRIMARY KEY",
                   "constraint_text": "PRIMARY KEY(a)"}]
        stg_i = [{"index_name": "idx_a", "is_unique": False, "is_primary": False,
                  "sql": "CREATE INDEX idx_a ON t(a);"}]
        pc, _, _, si = vsp.normalize_pk_index_equivalence(prod_c, [], [], stg_i)
        assert pc == prod_c
        assert si == stg_i


class TestNotNullDedupe:
    def test_strips_not_null_only(self):
        constraints = [
            {"constraint_type": "PRIMARY KEY", "constraint_text": "PRIMARY KEY(a)"},
            {"constraint_type": "NOT NULL", "constraint_text": "NOT NULL"},
            {"constraint_type": "CHECK", "constraint_text": "CHECK (a > 0)"},
        ]
        out = vsp.dedupe_not_null_constraint(constraints)
        assert len(out) == 2
        assert all(c["constraint_type"] != "NOT NULL" for c in out)


# ---------------------------------------------------------------------------
# Dimension comparators
# ---------------------------------------------------------------------------


class TestCompareColumns:
    def test_identical_columns_no_divergence(self):
        cols = [
            {"column_name": "id", "data_type": "BIGINT", "is_nullable": False,
             "column_default": None, "column_index": 1},
            {"column_name": "name", "data_type": "VARCHAR", "is_nullable": True,
             "column_default": None, "column_index": 2},
        ]
        assert vsp.compare_columns(cols, list(cols), "t") == []

    def test_type_mismatch_flagged(self):
        prod = [{"column_name": "id", "data_type": "BIGINT", "is_nullable": False,
                 "column_default": None, "column_index": 1}]
        stg = [{"column_name": "id", "data_type": "INTEGER", "is_nullable": False,
                "column_default": None, "column_index": 1}]
        divs = vsp.compare_columns(prod, stg, "t")
        assert len(divs) == 1
        assert divs[0].dimension == "columns"
        assert divs[0].detail == "id"

    def test_nullability_mismatch_flagged(self):
        prod = [{"column_name": "x", "data_type": "VARCHAR", "is_nullable": False,
                 "column_default": None, "column_index": 1}]
        stg = [{"column_name": "x", "data_type": "VARCHAR", "is_nullable": True,
                "column_default": None, "column_index": 1}]
        divs = vsp.compare_columns(prod, stg, "t")
        assert len(divs) == 1

    def test_missing_column_in_staging(self):
        prod = [{"column_name": "id", "data_type": "BIGINT", "is_nullable": False,
                 "column_default": None, "column_index": 1}]
        divs = vsp.compare_columns(prod, [], "t")
        assert len(divs) == 1
        assert divs[0].staging_value is None

    def test_case_insensitive_match(self):
        prod = [{"column_name": "ID", "data_type": "BIGINT", "is_nullable": False,
                 "column_default": None, "column_index": 1}]
        stg = [{"column_name": "id", "data_type": "BIGINT", "is_nullable": False,
                "column_default": None, "column_index": 1}]
        # Case-insensitive: treated as same column; then fields match
        assert vsp.compare_columns(prod, stg, "t") == []


class TestCompareIndexes:
    def test_identical_indexes_no_divergence(self):
        idxs = [{"index_name": "idx_a", "is_unique": False, "is_primary": False,
                 "sql": "CREATE INDEX idx_a ON t(a);"}]
        assert vsp.compare_indexes(idxs, list(idxs), "t") == []

    def test_missing_index_in_staging(self):
        prod = [{"index_name": "idx_a", "is_unique": False, "is_primary": False,
                 "sql": "CREATE INDEX idx_a ON t(a);"}]
        divs = vsp.compare_indexes(prod, [], "t")
        assert len(divs) == 1
        assert divs[0].detail == "idx_a"

    def test_sql_whitespace_normalized(self):
        prod = [{"index_name": "idx_a", "is_unique": False, "is_primary": False,
                 "sql": "CREATE  INDEX idx_a  ON t(a);"}]
        stg = [{"index_name": "idx_a", "is_unique": False, "is_primary": False,
                "sql": "CREATE INDEX idx_a ON t(a);"}]
        assert vsp.compare_indexes(prod, stg, "t") == []


class TestCompareDDL:
    def test_whitespace_tolerant(self):
        # Conservative normalizer: collapse multi-space, normalize line endings,
        # strip trailing semicolon. Does NOT rewrite punctuation spacing.
        p = "CREATE TABLE foo (a INT, b VARCHAR);"
        s = "CREATE  TABLE\r\nfoo (a INT, b VARCHAR)"
        assert vsp.compare_ddl(p, s, "t") == []

    def test_real_difference_flagged(self):
        p = "CREATE TABLE foo (a INT)"
        s = "CREATE TABLE foo (a BIGINT)"
        divs = vsp.compare_ddl(p, s, "t")
        assert len(divs) == 1
        assert divs[0].detail == "CREATE TABLE"


class TestCompareConstraints:
    def test_missing_pk(self):
        prod = [{"constraint_type": "PRIMARY KEY",
                 "constraint_text": "PRIMARY KEY(a)"}]
        divs = vsp.compare_constraints(prod, [], "t")
        assert len(divs) == 1
        assert divs[0].dimension == "constraints"


# ---------------------------------------------------------------------------
# ATTACH filter — regression guard for the duckdb_columns() bug found during
# Phase 1 rebuild. Without the `database_name = current_database()` filter,
# introspection queries return rows from every attached database, not just
# the connected one.
# ---------------------------------------------------------------------------


class TestIntrospectionFilterIsolatesCurrentDatabase:
    """If the `database_name = current_database()` filter in _filtered_query
    is removed, these tests regress: introspection queries would double-count
    columns/indexes/constraints by pulling rows from attached databases too."""

    def _build_two_dbs(self, tmp_path):
        a = tmp_path / "a.duckdb"
        b = tmp_path / "b.duckdb"
        con_a = duckdb.connect(str(a))
        con_a.execute("CREATE TABLE entities (entity_id BIGINT, entity_type VARCHAR)")
        con_a.execute("CREATE INDEX idx_a ON entities(entity_type)")
        con_a.execute("CHECKPOINT")
        con_a.close()
        con_b = duckdb.connect(str(b))
        con_b.execute("CREATE TABLE entities (entity_id BIGINT, entity_type VARCHAR)")
        con_b.execute("CREATE INDEX idx_b ON entities(entity_type)")
        con_b.execute("CHECKPOINT")
        con_b.close()
        return str(a), str(b)

    def test_columns_introspection_ignores_attached_db(self, tmp_path):
        a, b = self._build_two_dbs(tmp_path)
        con = duckdb.connect(a)
        try:
            con.execute(f"ATTACH '{b}' AS other (READ_ONLY)")
            cols = vsp.introspect_columns(con, "entities")
            # Expect exactly 2 columns (from the connected DB `a`),
            # NOT 4 (which would indicate rows from the attached `other` DB too).
            assert len(cols) == 2
            names = [c["column_name"] for c in cols]
            assert names == ["entity_id", "entity_type"]
        finally:
            con.close()

    def test_indexes_introspection_ignores_attached_db(self, tmp_path):
        a, b = self._build_two_dbs(tmp_path)
        con = duckdb.connect(a)
        try:
            con.execute(f"ATTACH '{b}' AS other (READ_ONLY)")
            idxs = vsp.introspect_indexes(con, "entities")
            # Expect exactly 1 index (idx_a from `a`), not 2 (idx_a + idx_b).
            assert len(idxs) == 1
            assert idxs[0]["index_name"] == "idx_a"
        finally:
            con.close()

    def test_ddl_introspection_ignores_attached_db(self, tmp_path):
        a, b = self._build_two_dbs(tmp_path)
        con = duckdb.connect(a)
        try:
            con.execute(f"ATTACH '{b}' AS other (READ_ONLY)")
            ddl = vsp.introspect_ddl(con, "entities")
            # Returns a single DDL string, not concatenated or doubled.
            assert isinstance(ddl, str)
            assert ddl.upper().startswith("CREATE TABLE")
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Accept-list
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "accept.yaml"
    p.write_text(content)
    return p


class TestLoadAcceptList:
    def test_missing_file_returns_empty(self, tmp_path):
        assert vsp.load_accept_list(str(tmp_path / "missing.yaml")) == []

    def test_empty_accepted_list(self, tmp_path):
        p = _write_yaml(tmp_path, "accepted: []\n")
        assert vsp.load_accept_list(str(p)) == []

    def test_valid_entry(self, tmp_path):
        p = _write_yaml(tmp_path, """
accepted:
  - table: holdings_v2
    dimension: indexes
    detail: idx_hv2_ticker_quarter
    justification: "This is a long-enough justification for the linter to accept."
    reviewer: serge.tismen
""")
        entries = vsp.load_accept_list(str(p))
        assert len(entries) == 1
        assert entries[0].table == "holdings_v2"

    def test_short_justification_rejected(self, tmp_path):
        p = _write_yaml(tmp_path, """
accepted:
  - table: t
    dimension: columns
    detail: col
    justification: "tbd"
    reviewer: me
""")
        with pytest.raises(ValueError, match="justification must be"):
            vsp.load_accept_list(str(p))

    def test_missing_required_field(self, tmp_path):
        p = _write_yaml(tmp_path, """
accepted:
  - table: t
    dimension: columns
    justification: "long enough justification to pass the length floor"
    reviewer: me
""")
        with pytest.raises(ValueError, match="missing required fields"):
            vsp.load_accept_list(str(p))

    def test_bad_dimension(self, tmp_path):
        p = _write_yaml(tmp_path, """
accepted:
  - table: t
    dimension: bogus
    detail: x
    justification: "a justification long enough to pass the length floor"
    reviewer: me
""")
        with pytest.raises(ValueError, match="dimension must be one of"):
            vsp.load_accept_list(str(p))

    def test_malformed_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("accepted: [invalid: mapping: here")
        with pytest.raises(Exception):  # yaml.YAMLError or ValueError
            vsp.load_accept_list(str(p))


class TestAcceptEntryExpiry:
    def test_no_expiry_never_expires(self):
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
        )
        assert e.is_expired() is False

    def test_future_date_not_expired(self):
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
            expiry_date=(date.today() + timedelta(days=30)).isoformat(),
        )
        assert e.is_expired() is False

    def test_past_date_expired(self):
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
            expiry_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        assert e.is_expired() is True

    def test_same_day_expired(self):
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
            expiry_date=date.today().isoformat(),
        )
        assert e.is_expired() is True

    def test_bad_date_format_raises(self):
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
            expiry_date="not-a-date",
        )
        with pytest.raises(ValueError, match="not ISO format"):
            e.is_expired()


class TestMatchAccept:
    def test_exact_match(self):
        d = vsp.Divergence(table="t", dimension="columns", detail="c")
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
        )
        assert vsp.match_accept(d, [e]) is e

    def test_case_insensitive_match(self):
        d = vsp.Divergence(table="T", dimension="Columns", detail="C")
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="c",
            justification="x" * 40, reviewer="me",
        )
        assert vsp.match_accept(d, [e]) is e

    def test_no_match(self):
        d = vsp.Divergence(table="t", dimension="columns", detail="c")
        e = vsp.AcceptEntry(
            table="t", dimension="columns", detail="different",
            justification="x" * 40, reviewer="me",
        )
        assert vsp.match_accept(d, [e]) is None


# ---------------------------------------------------------------------------
# End-to-end: run() against temp DuckDB files
# ---------------------------------------------------------------------------


def _build_duckdb(path: str, ddl_list: list[str]):
    con = duckdb.connect(path)
    for ddl in ddl_list:
        con.execute(ddl)
    con.execute("CHECKPOINT")
    con.close()


@pytest.fixture()
def matched_dbs(tmp_path):
    """Two DuckDB files with identical schemas."""
    prod = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    ddl = [
        "CREATE TABLE entities (entity_id BIGINT, entity_type VARCHAR);",
        "CREATE INDEX idx_e_type ON entities(entity_type);",
    ]
    _build_duckdb(str(prod), ddl)
    _build_duckdb(str(staging), ddl)
    return str(prod), str(staging)


@pytest.fixture()
def drifted_dbs(tmp_path):
    """Prod has an extra index vs staging — the classic pct-of-so drift."""
    prod = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    _build_duckdb(str(prod), [
        "CREATE TABLE entities (entity_id BIGINT, entity_type VARCHAR);",
        "CREATE INDEX idx_e_type ON entities(entity_type);",
    ])
    _build_duckdb(str(staging), [
        "CREATE TABLE entities (entity_id BIGINT, entity_type VARCHAR);",
        # staging missing idx_e_type — matches the prototypical pct-of-so failure
    ])
    return str(prod), str(staging)


class TestRunExitCodes:
    def test_parity_exit_0(self, matched_dbs, tmp_path):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        rc, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 0
        assert report["summary"]["verdict"] == "PARITY"
        assert report["summary"]["total"] == 0

    def test_unaccepted_divergence_exit_1(self, drifted_dbs, tmp_path):
        prod, staging = drifted_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        rc, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 1
        assert report["summary"]["verdict"] == "FAIL"
        assert report["summary"]["unaccepted"] >= 1

    def test_all_accepted_exit_0(self, drifted_dbs, tmp_path):
        prod, staging = drifted_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("""
accepted:
  - table: entities
    dimension: indexes
    detail: idx_e_type
    justification: "staging intentionally lacks this index for local dev speed"
    reviewer: test
""")
        rc, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 0
        assert report["summary"]["verdict"] == "PARITY"
        assert report["summary"]["accepted"] == 1
        assert report["summary"]["unaccepted"] == 0

    def test_fail_on_accepted_reverses_verdict(self, drifted_dbs, tmp_path):
        prod, staging = drifted_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("""
accepted:
  - table: entities
    dimension: indexes
    detail: idx_e_type
    justification: "staging intentionally lacks this index for local dev speed"
    reviewer: test
""")
        rc, _ = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=True,
        )
        assert rc == 1

    def test_expired_entry_exits_1(self, matched_dbs, tmp_path):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        past = (date.today() - timedelta(days=5)).isoformat()
        accept.write_text(f"""
accepted:
  - table: entities
    dimension: indexes
    detail: no_such_index
    justification: "long-enough justification text for the linter to accept this"
    reviewer: test
    expiry_date: {past}
""")
        rc, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 1
        assert report["summary"]["expired_accepts"] == 1

    def test_stale_entry_is_warning_not_failure(self, matched_dbs, tmp_path):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("""
accepted:
  - table: entities
    dimension: indexes
    detail: totally_nonexistent_index
    justification: "this entry references a divergence that does not exist anymore"
    reviewer: test
""")
        rc, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 0
        assert report["summary"]["stale_accepts"] == 1

    def test_missing_db_exit_2(self, tmp_path):
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        rc, _ = vsp.run(
            prod_path=str(tmp_path / "nope.duckdb"),
            staging_path=str(tmp_path / "also_nope.duckdb"),
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 2

    def test_bad_accept_yaml_exit_2(self, matched_dbs, tmp_path):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("""
accepted:
  - table: t
    dimension: columns
    detail: c
    justification: "short"
    reviewer: me
""")
        rc, _ = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert rc == 2


class TestJsonOutputShape:
    def test_parity_json_shape(self, matched_dbs, tmp_path):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        _, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        # Must be JSON-serializable
        j = json.dumps(report, default=str)
        assert "summary" in report
        for key in ("total", "accepted", "unaccepted", "verdict"):
            assert key in report["summary"]
        for key in ("divergences", "unaccepted", "accepted", "stale_accepts", "expired_accepts"):
            assert key in report
            assert isinstance(report[key], list)
        assert len(j) > 0

    def test_unaccepted_entries_populated(self, drifted_dbs, tmp_path):
        prod, staging = drifted_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        _, report = vsp.run(
            prod_path=prod, staging_path=staging,
            tables=["entities"], dimensions=vsp.DIMENSIONS,
            accept_list_path=str(accept), fail_on_accepted=False,
        )
        assert len(report["unaccepted"]) >= 1
        d = report["unaccepted"][0]
        for key in ("table", "dimension", "detail"):
            assert key in d


# ---------------------------------------------------------------------------
# CLI main() smoke tests
# ---------------------------------------------------------------------------


class TestCliMain:
    def test_unknown_dimension_flag(self, matched_dbs, tmp_path, capsys):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        rc = vsp.main([
            "--prod", prod, "--staging", staging,
            "--accept-list", str(accept),
            "--dimensions", "columns,bogus",
            "--tables", "entities",
        ])
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown dimensions" in err

    def test_unknown_table_flag(self, matched_dbs, tmp_path, capsys):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        rc = vsp.main([
            "--prod", prod, "--staging", staging,
            "--accept-list", str(accept),
            "--tables", "not_a_real_l3_table",
        ])
        assert rc == 2

    def test_json_mode_output_is_parseable(self, matched_dbs, tmp_path, capsys):
        prod, staging = matched_dbs
        accept = tmp_path / "accept.yaml"
        accept.write_text("accepted: []\n")
        rc = vsp.main([
            "--prod", prod, "--staging", staging,
            "--accept-list", str(accept),
            "--tables", "entities",
            "--json",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["summary"]["verdict"] == "PARITY"
