"""Unit tests for scripts/pipeline/load_ncen.py (w2-04).

Tests use temp DuckDB files and stubbed EDGAR helpers — no network
calls, no prod data. Proves the class is a valid SourcePipeline
subclass, that the SCD Type 2 wiring is correct, and that the
(series_id, adviser_crd, role) expanded natural key prevents the
dup-open-row failure that a narrower key would produce.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import SourcePipeline  # noqa: E402
from pipeline.load_ncen import (  # noqa: E402
    LoadNCENPipeline, _TARGET_TABLE_COLUMNS, _parse_ncen_xml,
)


# ---------------------------------------------------------------------------
# DDL — minimal prod stubs
# ---------------------------------------------------------------------------

DDL_MANIFEST = """
CREATE TABLE ingestion_manifest (
    manifest_id              BIGINT PRIMARY KEY,
    source_type              VARCHAR NOT NULL,
    object_type              VARCHAR NOT NULL,
    object_key               VARCHAR NOT NULL UNIQUE,
    source_url               VARCHAR,
    accession_number         VARCHAR,
    run_id                   VARCHAR NOT NULL,
    fetch_status             VARCHAR NOT NULL DEFAULT 'pending',
    error_message            VARCHAR,
    superseded_by_manifest_id BIGINT,
    is_amendment             BOOLEAN DEFAULT FALSE,
    retry_count              INTEGER DEFAULT 0,
    filing_date              DATE
)
"""

DDL_IMPACTS = """
CREATE TABLE ingestion_impacts (
    impact_id       BIGINT PRIMARY KEY,
    manifest_id     BIGINT NOT NULL,
    target_table    VARCHAR NOT NULL,
    unit_type       VARCHAR NOT NULL,
    unit_key_json   VARCHAR NOT NULL,
    report_date     DATE,
    rows_staged     INTEGER DEFAULT 0,
    load_status     VARCHAR DEFAULT 'pending',
    validation_tier VARCHAR,
    promote_status  VARCHAR DEFAULT 'pending'
)
"""

DDL_FRESHNESS = """
CREATE TABLE data_freshness (
    table_name       VARCHAR PRIMARY KEY,
    last_computed_at TIMESTAMP,
    row_count        BIGINT
)
"""

DDL_FUND_UNIVERSE = """
CREATE TABLE fund_universe (
    fund_cik VARCHAR
)
"""

DDL_ADV_MANAGERS = """
CREATE TABLE adv_managers (
    crd_number VARCHAR
)
"""

DDL_NCEN_TARGET = """
CREATE TABLE ncen_adviser_map (
    registrant_cik    VARCHAR,
    registrant_name   VARCHAR,
    adviser_name      VARCHAR,
    adviser_sec_file  VARCHAR,
    adviser_crd       VARCHAR,
    adviser_lei       VARCHAR,
    role              VARCHAR,
    series_id         VARCHAR,
    series_name       VARCHAR,
    report_date       DATE,
    filing_date       DATE,
    loaded_at         TIMESTAMP,
    valid_from        TIMESTAMP,
    valid_to          DATE
)
"""


def _init_prod_db(path: str, *, fund_ciks: list[str] | None = None,
                  adv_crds: list[str] | None = None) -> None:
    con = duckdb.connect(path)
    try:
        for ddl in (
            DDL_MANIFEST, DDL_IMPACTS, DDL_FRESHNESS,
            DDL_FUND_UNIVERSE, DDL_ADV_MANAGERS, DDL_NCEN_TARGET,
        ):
            con.execute(ddl)
        for cik in fund_ciks or []:
            con.execute("INSERT INTO fund_universe VALUES (?)", [cik])
        for crd in adv_crds or []:
            con.execute("INSERT INTO adv_managers VALUES (?)", [crd])
        con.execute("CHECKPOINT")
    finally:
        con.close()


@pytest.fixture
def tmp_dbs(tmp_path):
    prod = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    backup = tmp_path / "backups"
    backup.mkdir()
    _init_prod_db(str(prod))
    return {
        "prod": str(prod),
        "staging": str(staging),
        "backup": str(backup),
    }


@pytest.fixture
def pipeline(tmp_dbs):
    return LoadNCENPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


# ---------------------------------------------------------------------------
# Fixture: minimal N-CEN XML with two series, same adviser in both roles for
# the first series (the configuration that breaks a narrower key).
# ---------------------------------------------------------------------------

_FIXTURE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ncen">
  <reportPeriodDate>2026-03-13</reportPeriodDate>

  <managementInvestmentQuestion>
    <mgmtInvSeriesId>S000003873</mgmtInvSeriesId>
    <mgmtInvFundName>Acme Growth Series</mgmtInvFundName>
  </managementInvestmentQuestion>
  <managementInvestmentQuestion>
    <mgmtInvSeriesId>S000003874</mgmtInvSeriesId>
    <mgmtInvFundName>Acme Income Series</mgmtInvFundName>
  </managementInvestmentQuestion>

  <investmentAdviser>
    <investmentAdviserName>Acme Capital LLC</investmentAdviserName>
    <investmentAdviserFileNo>801-12345</investmentAdviserFileNo>
    <investmentAdviserCrdNo>000106629</investmentAdviserCrdNo>
    <investmentAdviserLei>LEI-ACME</investmentAdviserLei>
  </investmentAdviser>
  <investmentAdviser>
    <investmentAdviserName>Beta Advisors LP</investmentAdviserName>
    <investmentAdviserFileNo>801-99999</investmentAdviserFileNo>
    <investmentAdviserCrdNo>000222222</investmentAdviserCrdNo>
    <investmentAdviserLei>LEI-BETA</investmentAdviserLei>
  </investmentAdviser>

  <subAdviser>
    <subAdviserName>Acme Capital LLC</subAdviserName>
    <subAdviserFileNo>801-12345</subAdviserFileNo>
    <subAdviserCrdNo>000106629</subAdviserCrdNo>
    <subAdviserLei>LEI-ACME</subAdviserLei>
  </subAdviser>
</edgarSubmission>
"""


def _filing_info(
    cik: str = "0001234567", accession: str = "0001234567-26-000001",
    filing_date: str = "2026-03-20",
) -> dict:
    return {
        "accession": accession,
        "primary_doc": "primary_doc.xml",
        "filing_date": filing_date,
        "registrant_name": "Acme Trust",
        "registrant_cik": cik,
    }


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_pipeline_attributes():
    assert LoadNCENPipeline.name == "ncen_advisers"
    assert LoadNCENPipeline.target_table == "ncen_adviser_map"
    assert LoadNCENPipeline.amendment_strategy == "scd_type2"
    assert LoadNCENPipeline.amendment_key == (
        "series_id", "adviser_crd", "role",
    )


def test_amendment_strategy_is_scd_type2():
    """Smoke check: confirms we did NOT regress to append_is_latest."""
    assert LoadNCENPipeline.amendment_strategy == "scd_type2"
    assert LoadNCENPipeline.amendment_strategy != "append_is_latest"


def test_is_source_pipeline_subclass(pipeline):
    assert isinstance(pipeline, SourcePipeline)


def test_target_table_spec_matches_target_columns(pipeline):
    spec = pipeline.target_table_spec()
    col_names = [c[0] for c in spec["columns"]]
    # row_id is not part of ncen_adviser_map, so nothing to exclude —
    # but the SCD columns must be present.
    assert "valid_from" in col_names
    assert "valid_to" in col_names
    assert col_names == [c[0] for c in _TARGET_TABLE_COLUMNS]


def test_registered_in_pipeline_registry():
    from pipeline.pipelines import PIPELINE_REGISTRY, get_pipeline
    assert "ncen_advisers" in PIPELINE_REGISTRY
    inst = get_pipeline("ncen_advisers")
    assert isinstance(inst, LoadNCENPipeline)


# ---------------------------------------------------------------------------
# Parser smoke
# ---------------------------------------------------------------------------

def test_parse_ncen_xml_emits_adviser_and_subadviser_rows():
    """The zip-pairing logic must emit one adviser row per series and
    (where present) one subadviser row at the matching index. The
    fixture has the same CRD in both roles for the first series —
    these must be separate rows distinguished by `role`."""
    records = _parse_ncen_xml(_FIXTURE_XML, _filing_info())
    by_key = {(r["series_id"], r["adviser_crd"], r["role"]): r
              for r in records}
    assert ("S000003873", "000106629", "adviser") in by_key
    assert ("S000003873", "000106629", "subadviser") in by_key
    assert ("S000003874", "000222222", "adviser") in by_key
    # No subadviser for the second series → no row.
    assert ("S000003874", "000222222", "subadviser") not in by_key


# ---------------------------------------------------------------------------
# Scope acceptance tests — stub EDGAR so no network fires.
# ---------------------------------------------------------------------------

def _stub_edgar(monkeypatch, *, records_for_cik: dict[str, bytes]):
    """Stub the three EDGAR-touching methods on LoadNCENPipeline."""
    def fake_find(self, cik):
        if cik in records_for_cik:
            return _filing_info(cik=cik)
        return None

    def fake_download(self, cik, accession, primary_doc):
        return records_for_cik.get(cik)

    def fake_parse(self, xml, filing_info):
        return _parse_ncen_xml(xml, filing_info)

    monkeypatch.setattr(LoadNCENPipeline, "_find_filing", fake_find)
    monkeypatch.setattr(LoadNCENPipeline, "_download_xml", fake_download)
    monkeypatch.setattr(LoadNCENPipeline, "_parse_xml", fake_parse)


def test_scope_ciks(pipeline, monkeypatch):
    """Scope ``{"ciks": [...]}`` must drive the fetch."""
    _stub_edgar(monkeypatch, records_for_cik={"0001234567": _FIXTURE_XML})

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        fr = pipeline.fetch({"ciks": [1234567]}, staging_con)
    finally:
        staging_con.close()
    # 3 records: (S1, Acme, adviser), (S1, Acme, subadviser), (S2, Beta, adviser)
    assert fr.rows_staged == 3


def test_scope_since_filters_old_filings(pipeline, monkeypatch):
    """Scope ``{"since": "2030-01-01"}`` must filter out the 2026 fixture."""
    _stub_edgar(monkeypatch, records_for_cik={"0001234567": _FIXTURE_XML})

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        fr = pipeline.fetch(
            {"ciks": [1234567], "since": "2030-01-01"}, staging_con,
        )
    finally:
        staging_con.close()
    assert fr.rows_staged == 0


def test_parse_skips_empty_adviser_crd(pipeline, monkeypatch):
    """A staged row with NULL adviser_crd must be filtered out of
    typed staging (SCD keys cannot be NULL) and surface as a FLAG."""
    xml_with_null_crd = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ncen">
  <reportPeriodDate>2026-03-13</reportPeriodDate>
  <managementInvestmentQuestion>
    <mgmtInvSeriesId>S000003873</mgmtInvSeriesId>
    <mgmtInvFundName>Acme Growth Series</mgmtInvFundName>
  </managementInvestmentQuestion>
  <investmentAdviser>
    <investmentAdviserName>Mystery Adviser</investmentAdviserName>
    <investmentAdviserFileNo></investmentAdviserFileNo>
    <investmentAdviserCrdNo></investmentAdviserCrdNo>
    <investmentAdviserLei></investmentAdviserLei>
  </investmentAdviser>
</edgarSubmission>
"""
    _stub_edgar(monkeypatch, records_for_cik={"0001234567": xml_with_null_crd})

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"ciks": [1234567]}, staging_con)
        pr = pipeline.parse(staging_con)
    finally:
        staging_con.close()
    assert pr.rows_parsed == 0
    severities = {q["severity"] for q in pr.qc_failures}
    rules = {q["rule"] for q in pr.qc_failures}
    # Expect both the empty-CRD FLAG and the zero-rows BLOCK.
    assert "FLAG" in severities
    assert "BLOCK" in severities
    assert any("null_adviser_crd" in r for r in rules)


def test_parse_produces_expanded_key_rows(pipeline, monkeypatch):
    """End-to-end fetch+parse: the expanded (series, crd, role) key
    keeps the two same-adviser-two-role rows separate. Under the
    narrower (series, crd) key this would be a BLOCK."""
    _stub_edgar(monkeypatch, records_for_cik={"0001234567": _FIXTURE_XML})

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"ciks": [1234567]}, staging_con)
        pr = pipeline.parse(staging_con)
    finally:
        staging_con.close()

    assert pr.rows_parsed == 3
    # No BLOCK — the expanded key disambiguates Acme's two roles.
    assert all(q["severity"] != "BLOCK" for q in pr.qc_failures), (
        f"unexpected BLOCKs: {pr.qc_failures}"
    )

    staging_con = duckdb.connect(pipeline._staging_db_path, read_only=True)
    try:
        rows = staging_con.execute(
            "SELECT series_id, adviser_crd, role, valid_to "
            "FROM ncen_adviser_map "
            "ORDER BY series_id, role"
        ).fetchall()
    finally:
        staging_con.close()

    assert len(rows) == 3
    for _sid, _crd, _role, valid_to in rows:
        assert valid_to.isoformat() == "9999-12-31"
