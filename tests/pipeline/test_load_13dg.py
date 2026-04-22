"""Unit tests for scripts/pipeline/load_13dg.py (w2-01).

Tests use temp DuckDB files and stubbed EDGAR helpers — no network
calls, no prod data. Proves the class is a valid SourcePipeline subclass
and that the 13D/G relaxation (unresolved filer_cik → FLAG not BLOCK)
fires as designed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import SourcePipeline  # noqa: E402
from pipeline.load_13dg import (  # noqa: E402
    Load13DGPipeline, _TARGET_TABLE_COLUMNS, _clean_text, _extract_fields,
)


# ---------------------------------------------------------------------------
# DDL — control plane + entity MDM stubs + fact/reference tables
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

DDL_PENDING = """
CREATE TABLE pending_entity_resolution (
    resolution_id     BIGINT PRIMARY KEY,
    manifest_id       BIGINT,
    source_type       VARCHAR NOT NULL,
    identifier_type   VARCHAR NOT NULL,
    identifier_value  VARCHAR NOT NULL,
    resolution_status VARCHAR NOT NULL DEFAULT 'pending',
    pending_key       VARCHAR UNIQUE
)
"""

DDL_FRESHNESS = """
CREATE TABLE data_freshness (
    table_name       VARCHAR PRIMARY KEY,
    last_computed_at TIMESTAMP,
    row_count        BIGINT
)
"""

DDL_ENTITY_IDENTIFIERS = """
CREATE TABLE entity_identifiers (
    entity_id        BIGINT,
    identifier_type  VARCHAR,
    identifier_value VARCHAR,
    valid_to         DATE
)
"""

DDL_ENTITY_ROLLUP = """
CREATE TABLE entity_rollup_history (
    entity_id        BIGINT,
    rollup_type      VARCHAR,
    rollup_entity_id BIGINT,
    valid_to         DATE
)
"""

DDL_ENTITY_CLASS = """
CREATE TABLE entity_classification_history (
    entity_id        BIGINT,
    valid_to         DATE
)
"""

DDL_ENTITY_ALIASES = """
CREATE TABLE entity_aliases (
    entity_id     BIGINT,
    alias_name    VARCHAR,
    is_preferred  BOOLEAN,
    valid_to      DATE
)
"""

DDL_ENTITY_OVERRIDES = """
CREATE TABLE entity_overrides_persistent (
    identifier_type  VARCHAR,
    identifier_value VARCHAR,
    action           VARCHAR,
    still_valid      BOOLEAN
)
"""

DDL_BO_V2 = """
CREATE TABLE beneficial_ownership_v2 (
    accession_number    VARCHAR,
    filer_cik           VARCHAR,
    filer_name          VARCHAR,
    subject_cusip       VARCHAR,
    subject_ticker      VARCHAR,
    subject_name        VARCHAR,
    filing_type         VARCHAR,
    filing_date         DATE,
    report_date         DATE,
    pct_owned           DOUBLE,
    shares_owned        BIGINT,
    aggregate_value     DOUBLE,
    intent              VARCHAR,
    is_amendment        BOOLEAN,
    prior_accession     VARCHAR,
    purpose_text        VARCHAR,
    group_members       VARCHAR,
    manager_cik         VARCHAR,
    loaded_at           TIMESTAMP,
    name_resolved       BOOLEAN,
    entity_id           BIGINT,
    rollup_entity_id    BIGINT,
    rollup_name         VARCHAR,
    dm_rollup_entity_id BIGINT,
    dm_rollup_name      VARCHAR,
    is_latest           BOOLEAN DEFAULT TRUE,
    backfill_quality    VARCHAR
)
"""

DDL_LISTED = """
CREATE TABLE listed_filings_13dg (
    accession_number  VARCHAR PRIMARY KEY,
    ticker            VARCHAR,
    form              VARCHAR,
    filing_date       VARCHAR,
    filer_cik         VARCHAR,
    subject_name      VARCHAR,
    subject_cik       VARCHAR,
    listed_at         TIMESTAMP
)
"""

DDL_FETCHED_TICKERS = """
CREATE TABLE fetched_tickers_13dg (
    ticker       VARCHAR PRIMARY KEY,
    fetched_at   TIMESTAMP
)
"""


def _init_prod_db(path: str) -> None:
    con = duckdb.connect(path)
    try:
        for ddl in (
            DDL_MANIFEST, DDL_IMPACTS, DDL_PENDING, DDL_FRESHNESS,
            DDL_ENTITY_IDENTIFIERS, DDL_ENTITY_ROLLUP, DDL_ENTITY_CLASS,
            DDL_ENTITY_ALIASES, DDL_ENTITY_OVERRIDES,
            DDL_BO_V2, DDL_LISTED, DDL_FETCHED_TICKERS,
        ):
            con.execute(ddl)
        con.execute("CHECKPOINT")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    return Load13DGPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


# ---------------------------------------------------------------------------
# Minimal fixture: one 13G filing body the parser can extract.
# ---------------------------------------------------------------------------

_FIXTURE_13G_BODY = """
<html><body>
SCHEDULE 13G
CUSIP No. 037833100
NAME OF REPORTING PERSON Acme Capital LLC
Aggregate Amount Beneficially Owned by Each Reporting Person: 1,234,567
Percent of Class Owned: 6.5%
Date of Event: 12/31/2025
</body></html>
"""


def _make_hit(acc: str, filer_cik: str = "0009999999") -> dict:
    return {
        "_id": f"{acc}:primary_doc.xml",
        "_source": {
            "root_form": "SC 13G",
            "form": "SC 13G",
            "file_date": "2026-02-14",
            "ciks": [filer_cik],
            "adsh": acc,
        },
    }


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_pipeline_attributes():
    assert Load13DGPipeline.name == "13dg_ownership"
    assert Load13DGPipeline.target_table == "beneficial_ownership_v2"
    assert Load13DGPipeline.amendment_strategy == "append_is_latest"
    assert Load13DGPipeline.amendment_key == ("filer_cik", "subject_cusip")


def test_is_source_pipeline_subclass(pipeline):
    assert isinstance(pipeline, SourcePipeline)


def test_target_table_spec_excludes_row_id(pipeline):
    spec = pipeline.target_table_spec()
    col_names = [c[0] for c in spec["columns"]]
    assert "row_id" not in col_names
    # sanity: core facts present
    for required in (
        "accession_number", "filer_cik", "subject_cusip",
        "filing_type", "filing_date", "pct_owned", "shares_owned",
        "is_latest", "loaded_at", "backfill_quality",
    ):
        assert required in col_names, f"missing {required}"
    assert col_names == [c[0] for c in _TARGET_TABLE_COLUMNS]


def test_registered_in_pipeline_registry():
    from pipeline.pipelines import PIPELINE_REGISTRY, get_pipeline
    assert "13dg_ownership" in PIPELINE_REGISTRY
    inst = get_pipeline("13dg_ownership")
    assert isinstance(inst, Load13DGPipeline)


# ---------------------------------------------------------------------------
# Scope acceptance tests — stub the EDGAR layer so no network fires.
# ---------------------------------------------------------------------------

def test_scope_since(pipeline, monkeypatch):
    """Scope ``{"since": "2026-04-01"}`` must reach _efts_search_for_subject
    with that startdt."""
    calls: list[tuple] = []

    def fake_efts(self, subject_cik, startdt, enddt):
        calls.append((subject_cik, startdt, enddt))
        return []

    monkeypatch.setattr(Load13DGPipeline, "_efts_search_for_subject", fake_efts)
    monkeypatch.setattr(Load13DGPipeline, "_fetch_filing_text",
                        lambda self, url: "")

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        fr = pipeline.fetch({"since": "2026-04-01"}, staging_con)
    finally:
        staging_con.close()
    assert fr.rows_staged == 0
    # Four default tickers, all called with the override startdt.
    assert len(calls) == 4
    for _cik, startdt, _enddt in calls:
        assert startdt == "2026-04-01"


def test_scope_tickers(pipeline, monkeypatch):
    """Scope ``{"tickers": ["AR"]}`` must restrict the fetch to that set."""
    calls: list[str] = []

    def fake_efts(self, subject_cik, startdt, enddt):
        calls.append(subject_cik)
        return []

    monkeypatch.setattr(Load13DGPipeline, "_efts_search_for_subject", fake_efts)
    monkeypatch.setattr(Load13DGPipeline, "_fetch_filing_text",
                        lambda self, url: "")

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"tickers": ["AR"]}, staging_con)
    finally:
        staging_con.close()
    # Only AR should be queried (subject CIK 0001433604).
    assert calls == ["0001433604"]


# ---------------------------------------------------------------------------
# Parse + validate — entity gate relaxation test.
# ---------------------------------------------------------------------------

def _seed_fetch_then_parse(pipeline, monkeypatch, *, filer_cik: str) -> None:
    """Wire a one-hit EDGAR response + canned body, run fetch + parse."""
    acc = "0009999999-26-000001"

    def fake_efts(self, subject_cik, startdt, enddt):
        if subject_cik == "0001433604":  # AR
            return [_make_hit(acc, filer_cik=filer_cik)]
        return []

    monkeypatch.setattr(Load13DGPipeline, "_efts_search_for_subject", fake_efts)
    monkeypatch.setattr(Load13DGPipeline, "_fetch_filing_text",
                        lambda self, url: _FIXTURE_13G_BODY)

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"tickers": ["AR"]}, staging_con)
        pipeline.parse(staging_con)
    finally:
        staging_con.close()


def test_parse_writes_target_staging_table(pipeline, monkeypatch):
    _seed_fetch_then_parse(pipeline, monkeypatch, filer_cik="0009999999")
    staging_con = duckdb.connect(pipeline._staging_db_path, read_only=True)
    try:
        rows = staging_con.execute(
            "SELECT filer_cik, subject_cusip, pct_owned, shares_owned, "
            "       is_latest, backfill_quality, filing_type "
            "FROM beneficial_ownership_v2"
        ).fetchall()
    finally:
        staging_con.close()
    assert len(rows) == 1
    (filer_cik, cusip, pct, shares, is_latest, bq, ftype) = rows[0]
    assert filer_cik == "0009999999"
    assert cusip == "037833100"
    assert pct == pytest.approx(6.5)
    assert shares == 1_234_567
    assert is_latest is True
    assert bq == "direct"
    assert ftype == "SC 13G"


def test_entity_gate_relaxation(pipeline, monkeypatch):
    """Unresolved filer_cik → FLAG, not BLOCK. A pipeline with an
    unrecognised filer must still be promote-ready (vr.blocks empty)."""
    _seed_fetch_then_parse(pipeline, monkeypatch, filer_cik="0009999999")

    staging_con = duckdb.connect(pipeline._staging_db_path)
    prod_con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()

    # 13D/G relaxation: unresolved filer → FLAG, not BLOCK.
    assert vr.blocks == [], f"unexpected blocks: {vr.blocks}"
    # The filer is not in entity_identifiers — should surface as a flag.
    assert any("filer_not_in_mdm" in f for f in vr.flags), (
        f"expected filer_not_in_mdm FLAG; got flags={vr.flags}"
    )
    assert vr.promote_ready is True


def test_validate_blocks_duplicate_accessions(pipeline, monkeypatch):
    """Structural BLOCKs (dup accession) do refuse promote."""
    _seed_fetch_then_parse(pipeline, monkeypatch, filer_cik="0009999999")
    # Manually double-insert the same accession to trigger the dup gate.
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        staging_con.execute(
            "INSERT INTO beneficial_ownership_v2 "
            "SELECT * FROM beneficial_ownership_v2"
        )
    finally:
        staging_con.close()

    staging_con = duckdb.connect(pipeline._staging_db_path)
    prod_con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()

    assert any("dup_accession" in b for b in vr.blocks)
    assert vr.promote_ready is False


def test_empty_run_is_not_a_block(pipeline, monkeypatch):
    """An event-driven pipeline with zero new filings should pass validate."""
    monkeypatch.setattr(
        Load13DGPipeline, "_efts_search_for_subject",
        lambda self, subject_cik, startdt, enddt: [],
    )
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"tickers": ["AR"]}, staging_con)
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    staging_con = duckdb.connect(pipeline._staging_db_path)
    prod_con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()
    assert vr.blocks == []


# ---------------------------------------------------------------------------
# Parser helper smoke tests
# ---------------------------------------------------------------------------

def test_clean_text_strips_html():
    out = _clean_text("<html><body>CUSIP <b>037833100</b></body></html>")
    assert "<" not in out
    assert "037833100" in out


def test_extract_fields_parses_fixture():
    text = _clean_text(_FIXTURE_13G_BODY)
    fields = _extract_fields(text, "SC 13G")
    assert fields["cusip"] == "037833100"
    assert fields["pct_owned"] == pytest.approx(6.5)
    assert fields["shares_owned"] == 1_234_567
