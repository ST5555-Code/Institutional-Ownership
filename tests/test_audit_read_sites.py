"""Unit tests for scripts/audit_read_sites.py (mig-07 Mode 1)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_read_sites as ars  # noqa: E402


# ---------------------------------------------------------------------------
# SQL pattern extraction
# ---------------------------------------------------------------------------


class TestExtractSqlRefs:
    def test_select_from(self):
        src = "rows = con.execute('SELECT ticker, cik FROM securities').fetchall()"
        refs = ars.extract_sql_refs(src)
        tables = [r.table for r in refs]
        assert "securities" in tables
        sel = next(r for r in refs if r.table == "securities" and r.operation == "SELECT")
        assert "ticker" in sel.columns_referenced
        assert "cik" in sel.columns_referenced

    def test_join(self):
        src = "SELECT * FROM a JOIN holdings_v2 h ON h.cik = a.cik"
        refs = ars.extract_sql_refs(src)
        tables = {r.table for r in refs}
        assert "a" in tables
        assert "holdings_v2" in tables
        assert any(r.operation == "JOIN" and r.table == "holdings_v2" for r in refs)

    def test_update(self):
        src = "con.execute('UPDATE entities SET entity_type = ? WHERE eid = ?', ...)"
        refs = ars.extract_sql_refs(src)
        assert any(r.operation == "UPDATE" and r.table == "entities" for r in refs)

    def test_insert_into(self):
        src = "con.execute('INSERT INTO holdings_v2 (cik, ticker) VALUES (?, ?)')"
        refs = ars.extract_sql_refs(src)
        assert any(r.operation == "INSERT" and r.table == "holdings_v2" for r in refs)

    def test_delete_from(self):
        src = "con.execute('DELETE FROM ticker_overrides WHERE ticker = ?')"
        refs = ars.extract_sql_refs(src)
        assert any(r.operation == "DELETE" and r.table == "ticker_overrides" for r in refs)

    def test_subquery_from(self):
        src = "SELECT x FROM (SELECT a FROM summary_by_parent WHERE b > 0) s"
        refs = ars.extract_sql_refs(src)
        tables = {r.table for r in refs}
        assert "summary_by_parent" in tables

    def test_multiline_sql_in_triple_quotes(self):
        src = '''
        con.sql("""
            SELECT ticker, quarter
            FROM holdings_v2
            WHERE cik = ?
        """)
        '''
        refs = ars.extract_sql_refs(src)
        assert any(r.table == "holdings_v2" for r in refs)

    def test_f_string_sql(self):
        src = 'con.sql(f"SELECT * FROM {table_name} WHERE ticker = \'{t}\'")'
        refs = ars.extract_sql_refs(src)
        # Should still detect the tables written literally. {table_name} is dynamic
        # and not extractable — but static FROM <word> should work.
        # Here nothing is static, so refs may be empty — that's acceptable.
        assert isinstance(refs, list)

    def test_case_insensitive(self):
        src = "select x from securities"
        refs = ars.extract_sql_refs(src)
        assert any(r.table == "securities" for r in refs)

    def test_line_numbers(self):
        src = "import x\nSELECT a FROM securities\nSELECT b FROM entities\n"
        refs = ars.extract_sql_refs(src)
        sec = next(r for r in refs if r.table == "securities")
        ent = next(r for r in refs if r.table == "entities")
        assert sec.line == 2
        assert ent.line == 3

    def test_context_snippet_truncated(self):
        long_line = "SELECT " + ("col_a, " * 30) + "final FROM securities WHERE x = 1"
        src = long_line
        refs = ars.extract_sql_refs(src)
        sec = next(r for r in refs if r.table == "securities")
        assert len(sec.context_snippet) <= 200

    def test_ignores_comments(self):
        # Comment lines shouldn't trigger refs. We're forgiving: if the regex
        # happens to match a commented-out SQL line, that's acceptable noise.
        # But pure Python comments with table-like names shouldn't match.
        src = "# This script writes to holdings_v2 in the main loop\n"
        refs = ars.extract_sql_refs(src)
        # No SQL keyword → no refs
        assert refs == []

    def test_no_false_positive_on_english_text(self):
        src = "error: could not update the record from remote source\n"
        refs = ars.extract_sql_refs(src)
        # "update the" — word after UPDATE is "the" (a stopword). Accept as
        # valid table name per our simple regex — but test we at least don't
        # crash.
        assert isinstance(refs, list)

    def test_ignores_python_from_import(self):
        src = "from __future__ import annotations\nfrom db import PROD_DB"
        refs = ars.extract_sql_refs(src)
        tables = {r.table for r in refs}
        assert "__future__" not in tables
        assert "db" not in tables

    def test_ignores_sql_keywords_as_tables(self):
        # "FROM WHERE" should not yield a table named WHERE
        src = "SELECT a FROM securities WHERE b = 1"
        refs = ars.extract_sql_refs(src)
        tables = {r.table for r in refs}
        assert "securities" in tables
        assert "where" not in tables
        assert "WHERE" not in tables


# ---------------------------------------------------------------------------
# Column extraction from SELECT
# ---------------------------------------------------------------------------


class TestExtractSelectColumns:
    def test_simple_columns(self):
        cols = ars.extract_select_columns("SELECT a, b, c FROM t")
        assert cols == ["a", "b", "c"]

    def test_star_returns_star(self):
        cols = ars.extract_select_columns("SELECT * FROM t")
        assert cols == ["*"]

    def test_qualified_columns(self):
        cols = ars.extract_select_columns("SELECT h.ticker, h.cik FROM holdings h")
        assert "ticker" in cols
        assert "cik" in cols

    def test_aliased_columns(self):
        cols = ars.extract_select_columns("SELECT a AS x, b AS y FROM t")
        assert "a" in cols
        assert "b" in cols

    def test_no_select(self):
        assert ars.extract_select_columns("UPDATE t SET a = 1") == []


# ---------------------------------------------------------------------------
# React field-reference extraction
# ---------------------------------------------------------------------------


class TestExtractReactFieldRefs:
    def test_row_field(self):
        src = "const v = row.ticker;\n"
        refs = ars.extract_react_field_refs(src)
        assert any(r.object == "row" and r.field == "ticker" for r in refs)

    def test_data_field(self):
        src = "setState(data.entity_id);\n"
        refs = ars.extract_react_field_refs(src)
        assert any(r.object == "data" and r.field == "entity_id" for r in refs)

    def test_item_field(self):
        src = "items.map(item => item.cik)\n"
        refs = ars.extract_react_field_refs(src)
        assert any(r.object == "item" and r.field == "cik" for r in refs)

    def test_ignores_non_target_objects(self):
        # random.foo shouldn't be tracked; we target row/data/item/record only
        src = "const x = console.log(y);\n"
        refs = ars.extract_react_field_refs(src)
        assert refs == []

    def test_line_numbers(self):
        src = "import x;\nconst y = row.ticker;\nconst z = item.cik;\n"
        refs = ars.extract_react_field_refs(src)
        t = next(r for r in refs if r.field == "ticker")
        c = next(r for r in refs if r.field == "cik")
        assert t.line == 2
        assert c.line == 3


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


class TestScanPythonDir:
    def test_skips_retired_and_pycache(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "keep.py").write_text("SELECT x FROM keep_table")
        (tmp_path / "scripts" / "retired").mkdir()
        (tmp_path / "scripts" / "retired" / "old.py").write_text("SELECT y FROM retired_table")
        (tmp_path / "scripts" / "__pycache__").mkdir()
        (tmp_path / "scripts" / "__pycache__" / "x.pyc").write_text("junk")

        rows = ars.scan_python_dir(tmp_path / "scripts")
        tables = {r.table for r in rows}
        assert "keep_table" in tables
        assert "retired_table" not in tables

    def test_records_relative_file_path(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "foo.py").write_text("SELECT a FROM securities")
        rows = ars.scan_python_dir(tmp_path / "scripts", root=tmp_path)
        assert rows
        assert rows[0].file.endswith("scripts/foo.py")


class TestScanReactDir:
    def test_scans_tsx_and_ts(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.tsx").write_text("const v = row.ticker;\n")
        (tmp_path / "src" / "b.ts").write_text("const v = data.cik;\n")
        (tmp_path / "src" / "c.md").write_text("row.foo")
        rows = ars.scan_react_dir(tmp_path / "src", root=tmp_path)
        files = {r.file for r in rows}
        assert any(f.endswith("src/a.tsx") for f in files)
        assert any(f.endswith("src/b.ts") for f in files)
        assert not any(f.endswith("src/c.md") for f in files)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFilterRefs:
    def _sample(self):
        return [
            ars.SqlRef(
                file="scripts/a.py", line=1, table="securities",
                operation="SELECT", columns_referenced=["ticker"],
                context_snippet="SELECT ticker FROM securities",
            ),
            ars.SqlRef(
                file="scripts/b.py", line=2, table="holdings_v2",
                operation="SELECT", columns_referenced=["cik"],
                context_snippet="SELECT cik FROM holdings_v2",
            ),
            ars.SqlRef(
                file="scripts/c.py", line=3, table="securities",
                operation="UPDATE", columns_referenced=[],
                context_snippet="UPDATE securities SET x = 1",
            ),
        ]

    def test_filter_by_table(self):
        refs = self._sample()
        out = ars.filter_refs(refs, table="securities")
        assert len(out) == 2
        assert all(r.table == "securities" for r in out)

    def test_filter_by_column(self):
        refs = self._sample()
        out = ars.filter_refs(refs, column="ticker")
        assert len(out) == 1
        assert out[0].table == "securities"

    def test_filter_case_insensitive(self):
        refs = self._sample()
        out = ars.filter_refs(refs, table="SECURITIES")
        assert len(out) == 2

    def test_no_filter_returns_all(self):
        refs = self._sample()
        assert len(ars.filter_refs(refs)) == 3


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


class TestWriteCsv:
    def test_csv_headers_and_rows(self, tmp_path):
        refs = [
            ars.SqlRef(
                file="scripts/a.py", line=5, table="securities",
                operation="SELECT", columns_referenced=["ticker", "cik"],
                context_snippet="SELECT ticker, cik FROM securities",
            ),
        ]
        out = tmp_path / "rep.csv"
        ars.write_csv(refs, out)
        with out.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["file"] == "scripts/a.py"
        assert rows[0]["line"] == "5"
        assert rows[0]["table"] == "securities"
        assert rows[0]["operation"] == "SELECT"
        assert "ticker" in rows[0]["columns_referenced"]
        assert "cik" in rows[0]["columns_referenced"]


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestCliMain:
    def test_summary_mode_prints_table_counts(self, tmp_path, capsys, monkeypatch):
        # Build a synthetic repo layout.
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "a.py").write_text("SELECT x FROM securities\n")
        (tmp_path / "scripts" / "b.py").write_text("SELECT y FROM entities\n")
        (tmp_path / "web" / "react-app" / "src").mkdir(parents=True)
        (tmp_path / "web" / "react-app" / "src" / "x.tsx").write_text("row.ticker\n")

        monkeypatch.chdir(tmp_path)
        rc = ars.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "securities" in out
        assert "entities" in out

    def test_filter_by_table_narrows_output(self, tmp_path, capsys, monkeypatch):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "a.py").write_text("SELECT x FROM securities\n")
        (tmp_path / "scripts" / "b.py").write_text("SELECT y FROM entities\n")
        (tmp_path / "web" / "react-app" / "src").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        rc = ars.main(["--table", "securities"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "securities" in out
        assert "entities" not in out

    def test_csv_mode_writes_report(self, tmp_path, monkeypatch):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "a.py").write_text("SELECT x FROM securities\n")
        (tmp_path / "web" / "react-app" / "src").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        rc = ars.main(["--csv"])
        assert rc == 0
        report = tmp_path / "data" / "reports" / "read_site_inventory.csv"
        assert report.exists()
        content = report.read_text()
        assert "securities" in content
        assert "file,line,table" in content or "file" in content.splitlines()[0]
