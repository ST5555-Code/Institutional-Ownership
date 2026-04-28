"""Unit tests for scripts/load_13f_v2.py (p2-05).

Tests use temp DuckDB files and fixture TSVs — no EDGAR network calls,
no prod data. The goal is to prove the class is a valid SourcePipeline
subclass and that parse() transforms raw TSV staging into a
stg_holdings_v2 table matching the prod schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from load_13f_v2 import Load13FPipeline, _TARGET_TABLE_COLUMNS  # noqa: E402
from pipeline.base import SourcePipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Control-plane + prod DDL (trimmed copies from tests/pipeline/test_base.py
# plus the tables this pipeline writes to).
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

# Minimal entity-MDM stand-in so entity_gate_check() has tables to query.
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

DDL_HOLDINGS_V2 = """
CREATE TABLE holdings_v2 (
    accession_number        VARCHAR,
    cik                     VARCHAR,
    manager_name            VARCHAR,
    inst_parent_name        VARCHAR,
    quarter                 VARCHAR,
    report_date             VARCHAR,
    cusip                   VARCHAR,
    ticker                  VARCHAR,
    issuer_name             VARCHAR,
    market_value_usd        BIGINT,
    shares                  BIGINT,
    pct_of_portfolio        DOUBLE,
    pct_of_so               DOUBLE,
    manager_type            VARCHAR,
    is_passive              BOOLEAN,
    is_activist             BOOLEAN,
    discretion              VARCHAR,
    vote_sole               BIGINT,
    vote_shared             BIGINT,
    vote_none               BIGINT,
    put_call                VARCHAR,
    market_value_live       DOUBLE,
    security_type_inferred  VARCHAR,
    fund_name               VARCHAR,
    classification_source   VARCHAR,
    entity_id               BIGINT,
    rollup_entity_id        BIGINT,
    rollup_name             VARCHAR,
    entity_type             VARCHAR,
    dm_rollup_entity_id     BIGINT,
    dm_rollup_name          VARCHAR,
    pct_of_so_source        VARCHAR,
    is_latest               BOOLEAN,
    loaded_at               TIMESTAMP,
    backfill_quality        VARCHAR
)
"""

DDL_FILINGS = """
CREATE TABLE filings (
    accession_number VARCHAR,
    cik              VARCHAR,
    manager_name     VARCHAR,
    crd_number       VARCHAR,
    quarter          VARCHAR,
    report_date      VARCHAR,
    filing_type      VARCHAR,
    amended          BOOLEAN,
    filed_date       VARCHAR
)
"""

DDL_OTHER_MANAGERS = """
CREATE TABLE other_managers (
    accession_number     VARCHAR,
    sequence_number      VARCHAR,
    other_cik            VARCHAR,
    form13f_file_number  VARCHAR,
    crd_number           VARCHAR,
    sec_file_number      VARCHAR,
    name                 VARCHAR,
    quarter              VARCHAR
)
"""


def _init_prod_db(path: str) -> None:
    con = duckdb.connect(path)
    try:
        for ddl in (
            DDL_MANIFEST, DDL_IMPACTS, DDL_PENDING, DDL_FRESHNESS,
            DDL_ENTITY_IDENTIFIERS, DDL_ENTITY_ROLLUP, DDL_ENTITY_CLASS,
            DDL_ENTITY_ALIASES, DDL_ENTITY_OVERRIDES,
            DDL_HOLDINGS_V2, DDL_FILINGS, DDL_OTHER_MANAGERS,
        ):
            con.execute(ddl)
        con.execute("CHECKPOINT")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fixture TSVs
# ---------------------------------------------------------------------------

SUBMISSION_TSV = (
    "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
    "0000001111-26-000001\t2026-02-14\t13F-HR\t1111\t12-31-2025\n"
    "0000002222-26-000001\t2026-02-15\t13F-HR\t2222\t12-31-2025\n"
)

COVERPAGE_TSV = (
    "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\t"
    "FILINGMANAGER_NAME\tFILINGMANAGER_CITY\tFILINGMANAGER_STATEORCOUNTRY\t"
    "CRDNUMBER\tSECFILENUMBER\n"
    "0000001111-26-000001\t12-31-2025\tN\t\tAlpha Capital\tNY\tNY\t12345\t028-12345\n"
    "0000002222-26-000001\t12-31-2025\tN\t\tBeta LLC\tCA\tCA\t67890\t028-67890\n"
)

INFOTABLE_TSV = (
    "ACCESSION_NUMBER\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\t"
    "SSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\t"
    "VOTING_AUTH_SOLE\tVOTING_AUTH_SHARED\tVOTING_AUTH_NONE\n"
    "0000001111-26-000001\tAPPLE INC\tCOM\t037833100\t\t100000\t1000\tSH\t\tSOLE\t\t1000\t0\t0\n"
    "0000001111-26-000001\tMICROSOFT CORP\tCOM\t594918104\t\t50000\t500\tSH\t\tSOLE\t\t500\t0\t0\n"
    "0000002222-26-000001\tAPPLE INC\tCOM\t037833100\t\t25000\t250\tSH\t\tSOLE\t\t250\t0\t0\n"
)

OTHERMANAGER2_TSV = (
    "ACCESSION_NUMBER\tSEQUENCENUMBER\tCIK\tFORM13FFILENUMBER\tCRDNUMBER\t"
    "SECFILENUMBER\tNAME\n"
    "0000001111-26-000001\t1\t3333\t028-99999\t11111\t\tSubadviser Co\n"
)


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
        "extract_dir": str(tmp_path / "extracted"),
    }


@pytest.fixture
def extracted_2026q1(tmp_dbs, monkeypatch):
    """Create fixture TSVs on disk and wire load_13f_v2 to read from them."""
    import load_13f_v2  # noqa: WPS433

    extract_root = Path(tmp_dbs["extract_dir"])
    q_dir = extract_root / "2026Q1"
    q_dir.mkdir(parents=True, exist_ok=True)
    (q_dir / "SUBMISSION.tsv").write_text(SUBMISSION_TSV)
    (q_dir / "COVERPAGE.tsv").write_text(COVERPAGE_TSV)
    (q_dir / "INFOTABLE.tsv").write_text(INFOTABLE_TSV)
    (q_dir / "OTHERMANAGER2.tsv").write_text(OTHERMANAGER2_TSV)

    monkeypatch.setattr(load_13f_v2, "EXTRACT_DIR", str(extract_root))
    monkeypatch.setattr(load_13f_v2, "RAW_DIR", str(tmp_dbs["extract_dir"]))
    monkeypatch.setitem(
        load_13f_v2.QUARTER_URLS, "2026Q1",
        "https://example.invalid/2026Q1.zip",
    )
    return str(q_dir)


@pytest.fixture
def pipeline(tmp_dbs):
    return Load13FPipeline(
        skip_fetch=True,
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pipeline_attributes():
    """Class-level contract: the four attributes the ABC validates."""
    assert Load13FPipeline.name == "13f_holdings"
    assert Load13FPipeline.target_table == "holdings_v2"
    assert Load13FPipeline.amendment_strategy == "append_is_latest"
    assert Load13FPipeline.amendment_key == ("cik", "quarter")


def test_is_source_pipeline_subclass(pipeline):
    assert isinstance(pipeline, SourcePipeline)


def test_target_table_spec_columns(pipeline):
    spec = pipeline.target_table_spec()
    assert "columns" in spec
    assert "pk" in spec
    assert "indexes" in spec

    col_names = [c[0] for c in spec["columns"]]
    # Core 13F facts
    for required in (
        "accession_number", "cik", "quarter", "cusip", "shares",
        "market_value_usd", "is_latest", "loaded_at", "backfill_quality",
    ):
        assert required in col_names, f"missing {required}"

    # column names must be the subset of prod columns this pipeline writes
    assert col_names == [c[0] for c in _TARGET_TABLE_COLUMNS]


def test_parse_creates_stg_holdings_v2(pipeline, extracted_2026q1):
    """End-to-end fetch+parse on fixture TSVs. fetch() is invoked with
    skip_fetch=True so no network call fires — it just loads the fixture
    TSVs into raw staging, then parse() builds stg holdings_v2."""
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"quarter": "2026Q1"}, staging_con)
        pr = pipeline.parse(staging_con)

        # holdings_v2 (staging) should have 3 rows — one per infotable row.
        rows = staging_con.execute(
            "SELECT cik, cusip, shares, is_latest, backfill_quality "
            "FROM holdings_v2 ORDER BY cik, cusip"
        ).fetchall()
    finally:
        staging_con.close()

    assert pr.rows_parsed == 3
    assert len(rows) == 3

    # CIK zero-padding to 10 digits (LPAD)
    ciks = {r[0] for r in rows}
    assert ciks == {"0000001111", "0000002222"}

    # is_latest=TRUE, backfill_quality='direct' on every staged row
    for _cik, _cusip, _shares, is_latest, bq in rows:
        assert is_latest is True
        assert bq == "direct"


def test_parse_emits_staging_reference_tables(pipeline, extracted_2026q1):
    """Reference tables — stg_13f_filings, stg_13f_filings_deduped,
    stg_13f_other_managers — must be populated by parse()."""
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"quarter": "2026Q1"}, staging_con)
        pipeline.parse(staging_con)

        filings = staging_con.execute(
            "SELECT COUNT(*) FROM stg_13f_filings"
        ).fetchone()[0]
        deduped = staging_con.execute(
            "SELECT COUNT(*) FROM stg_13f_filings_deduped"
        ).fetchone()[0]
        other = staging_con.execute(
            "SELECT COUNT(*) FROM stg_13f_other_managers"
        ).fetchone()[0]
    finally:
        staging_con.close()

    assert filings == 2
    assert deduped == 2
    assert other == 1


def test_parse_computes_market_value_in_dollars(pipeline, extracted_2026q1):
    """SEC reports VALUE in $1000s; the pipeline must promote to dollars."""
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"quarter": "2026Q1"}, staging_con)
        pipeline.parse(staging_con)
        mv = staging_con.execute(
            "SELECT market_value_usd FROM holdings_v2 "
            "WHERE cusip = '037833100' AND cik = '0000001111'"
        ).fetchone()[0]
    finally:
        staging_con.close()
    # INFOTABLE VALUE 100000 (thousands) -> 100,000,000 dollars
    assert mv == 100_000_000


def test_parse_computes_pct_of_portfolio(pipeline, extracted_2026q1):
    """pct_of_portfolio = VALUE / SUM(VALUE) PARTITION BY accession_number."""
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"quarter": "2026Q1"}, staging_con)
        pipeline.parse(staging_con)
        rows = staging_con.execute(
            "SELECT cusip, pct_of_portfolio FROM holdings_v2 "
            "WHERE cik = '0000001111' ORDER BY cusip"
        ).fetchall()
    finally:
        staging_con.close()

    # Alpha Capital (cik 1111) holdings: AAPL 100k, MSFT 50k — total 150k.
    by_cusip = dict(rows)
    assert by_cusip["037833100"] == pytest.approx(100_000 / 150_000)
    assert by_cusip["594918104"] == pytest.approx(50_000 / 150_000)


def test_parse_leaves_enrichment_columns_null(pipeline, extracted_2026q1):
    """Group 2/3 columns must be NULL — downstream enrichment fills them."""
    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        pipeline.fetch({"quarter": "2026Q1"}, staging_con)
        pipeline.parse(staging_con)
        row = staging_con.execute(
            "SELECT ticker, entity_id, rollup_entity_id, manager_type, "
            "       market_value_live, pct_of_so "
            "FROM holdings_v2 LIMIT 1"
        ).fetchone()
    finally:
        staging_con.close()
    assert all(v is None for v in row)


def test_run_halts_at_pending_approval(pipeline, extracted_2026q1):
    """The async gate: run() halts; does not promote."""
    run_id = pipeline.run({"quarter": "2026Q1"})

    con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        status = con.execute(
            "SELECT fetch_status FROM ingestion_manifest WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        prod_rows = con.execute("SELECT COUNT(*) FROM holdings_v2").fetchone()[0]
    finally:
        con.close()
    assert status == "pending_approval"
    assert prod_rows == 0, "run() must not write to prod holdings_v2"


def test_approve_promotes_to_prod(pipeline, extracted_2026q1):
    """approve_and_promote runs snapshot → promote → verify → cleanup."""
    run_id = pipeline.run({"quarter": "2026Q1"})
    result = pipeline.approve_and_promote(run_id)

    assert result.rows_inserted == 3
    assert result.rows_flipped == 0  # first load — no prior rows

    con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT COUNT(*) FROM holdings_v2 WHERE is_latest = TRUE"
        ).fetchone()[0]
        filings = con.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        ded = con.execute(
            "SELECT COUNT(*) FROM filings_deduped"
        ).fetchone()[0]
        other = con.execute("SELECT COUNT(*) FROM other_managers").fetchone()[0]
    finally:
        con.close()
    assert rows == 3
    assert filings == 2
    assert ded == 2
    assert other == 1
