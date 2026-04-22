"""Unit tests for scripts/pipeline/load_nport.py (w2-03).

Tests run against temp DuckDB files with in-memory raw staging rows — no
DERA ZIP download, no EDGAR XML fetch, no prod data. They prove the
class is a valid SourcePipeline subclass, registered in the pipeline
registry, that scope shapes are accepted without raising, that parse()
transforms raw staging into the typed target table, and that the two
contract tests Serge calls out (entity gate relaxation, duplicate
accession BLOCKs) fire as designed.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import SourcePipeline  # noqa: E402
from pipeline.load_nport import (  # noqa: E402
    LoadNPortPipeline,
    _TARGET_TABLE_COLUMNS,
    _assert_no_future_report_month,
)


# ---------------------------------------------------------------------------
# Prod DDL — minimum tables the pipeline touches during validate/promote.
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

DDL_FUND_HOLDINGS_V2 = (
    "CREATE TABLE fund_holdings_v2 (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + ",\n    row_id BIGINT"
    + "\n)"
)

DDL_FUND_UNIVERSE = """
CREATE TABLE fund_universe (
    fund_cik              VARCHAR,
    fund_name             VARCHAR,
    series_id             VARCHAR PRIMARY KEY,
    family_name           VARCHAR,
    total_net_assets      DOUBLE,
    fund_category         VARCHAR,
    is_actively_managed   BOOLEAN,
    total_holdings_count  INTEGER,
    equity_pct            DOUBLE,
    top10_concentration   DOUBLE,
    last_updated          TIMESTAMP,
    fund_strategy         VARCHAR,
    best_index            VARCHAR,
    strategy_narrative    VARCHAR,
    strategy_source       VARCHAR,
    strategy_fetched_at   TIMESTAMP
)
"""


def _init_prod_db(path: str) -> None:
    con = duckdb.connect(path)
    try:
        for ddl in (
            DDL_MANIFEST, DDL_IMPACTS, DDL_PENDING,
            DDL_ENTITY_IDENTIFIERS, DDL_ENTITY_ROLLUP,
            DDL_ENTITY_ALIASES, DDL_ENTITY_OVERRIDES,
            DDL_FUND_HOLDINGS_V2, DDL_FUND_UNIVERSE,
        ):
            con.execute(ddl)
        con.execute("CHECKPOINT")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Staging fixture helper — seed stg_nport_holdings rows the pipeline can parse.
# ---------------------------------------------------------------------------

_STG_HOLDINGS_DDL = """
CREATE TABLE IF NOT EXISTS stg_nport_holdings (
    fund_cik             VARCHAR,
    fund_name            VARCHAR,
    family_name          VARCHAR,
    series_id            VARCHAR,
    quarter              VARCHAR,
    report_month         VARCHAR,
    report_date          DATE,
    cusip                VARCHAR,
    isin                 VARCHAR,
    issuer_name          VARCHAR,
    ticker               VARCHAR,
    asset_category       VARCHAR,
    shares_or_principal  DOUBLE,
    market_value_usd     DOUBLE,
    pct_of_nav           DOUBLE,
    fair_value_level     VARCHAR,
    is_restricted        BOOLEAN,
    payoff_profile       VARCHAR,
    loaded_at            TIMESTAMP,
    fund_strategy        VARCHAR,
    best_index           VARCHAR,
    accession_number     VARCHAR,
    manifest_id          BIGINT,
    parse_status         VARCHAR,
    qc_flags             VARCHAR
)
"""

_STG_UNIVERSE_DDL = """
CREATE TABLE IF NOT EXISTS stg_nport_fund_universe (
    fund_cik              VARCHAR,
    fund_name             VARCHAR,
    series_id             VARCHAR,
    family_name           VARCHAR,
    total_net_assets      DOUBLE,
    fund_category         VARCHAR,
    is_actively_managed   BOOLEAN,
    total_holdings_count  INTEGER,
    equity_pct            DOUBLE,
    top10_concentration   DOUBLE,
    last_updated          TIMESTAMP,
    fund_strategy         VARCHAR,
    best_index            VARCHAR,
    manifest_id           BIGINT
)
"""


def _seed_staging(staging_path: str, rows: list[dict]) -> None:
    con = duckdb.connect(staging_path)
    try:
        con.execute(_STG_HOLDINGS_DDL)
        con.execute(_STG_UNIVERSE_DDL)
        now = datetime.utcnow()
        for r in rows:
            con.execute(
                """
                INSERT INTO stg_nport_holdings (
                    fund_cik, fund_name, family_name, series_id,
                    quarter, report_month, report_date, cusip, isin,
                    issuer_name, ticker, asset_category,
                    shares_or_principal, market_value_usd, pct_of_nav,
                    fair_value_level, is_restricted, payoff_profile,
                    loaded_at, fund_strategy, best_index,
                    accession_number, manifest_id, parse_status, qc_flags
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    r.get("fund_cik", "0000012345"),
                    r.get("fund_name", "Test Fund"),
                    r.get("family_name", "Test Family"),
                    r["series_id"],
                    r.get("quarter", "2026Q1"),
                    r["report_month"],
                    r.get("report_date", date(2026, 1, 31)),
                    r.get("cusip", "037833100"),
                    r.get("isin"),
                    r.get("issuer_name", "Test Issuer"),
                    r.get("ticker", "TEST"),
                    r.get("asset_category", "EC"),
                    r.get("shares_or_principal", 100.0),
                    r.get("market_value_usd", 1_000_000.0),
                    r.get("pct_of_nav", 0.5),
                    r.get("fair_value_level"),
                    r.get("is_restricted", False),
                    r.get("payoff_profile"),
                    now,
                    r.get("fund_strategy", "active_equity"),
                    r.get("best_index"),
                    r["accession_number"],
                    None, "complete", None,
                ],
            )
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
    return LoadNPortPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_pipeline_attributes():
    assert LoadNPortPipeline.name == "nport_holdings"
    assert LoadNPortPipeline.target_table == "fund_holdings_v2"
    assert LoadNPortPipeline.amendment_strategy == "append_is_latest"
    assert LoadNPortPipeline.amendment_key == ("series_id", "report_month")


def test_integration_with_base_class(pipeline):
    assert isinstance(pipeline, SourcePipeline)


def test_target_table_spec_excludes_row_id(pipeline):
    spec = pipeline.target_table_spec()
    col_names = [c[0] for c in spec["columns"]]
    assert "row_id" not in col_names
    # core columns must be present
    for required in (
        "fund_cik", "series_id", "report_month", "report_date",
        "cusip", "market_value_usd", "pct_of_nav",
        "is_latest", "loaded_at", "backfill_quality",
        "entity_id", "rollup_entity_id",
        "dm_entity_id", "dm_rollup_entity_id", "dm_rollup_name",
        "accession_number",
    ):
        assert required in col_names, f"missing {required}"


def test_registered_in_pipeline_registry():
    from pipeline.pipelines import PIPELINE_REGISTRY, get_pipeline
    assert "nport_holdings" in PIPELINE_REGISTRY
    instance = get_pipeline("nport_holdings")
    assert isinstance(instance, LoadNPortPipeline)


def test_imports_from_fetch_dera_nport():
    """The transport helpers must be importable so fetch() can delegate."""
    from fetch_dera_nport import (
        _STG_HOLDINGS_DDL as src_h,
        _STG_UNIVERSE_DDL as src_u,
        _ensure_staging_schema,
        build_dera_dataset,
        download_dera_zip,
        parse_quarter,
        quarter_label_for_date,
        resolve_amendments,
    )
    assert callable(_ensure_staging_schema)
    assert callable(build_dera_dataset)
    assert callable(download_dera_zip)
    assert callable(parse_quarter)
    assert callable(quarter_label_for_date)
    assert callable(resolve_amendments)
    assert "stg_nport_holdings" in src_h
    assert "stg_nport_fund_universe" in src_u


def test_imports_from_nport_parsers():
    from pipeline.nport_parsers import classify_fund, parse_nport_xml
    assert callable(classify_fund)
    assert callable(parse_nport_xml)


# ---------------------------------------------------------------------------
# Scope acceptance — the fetch() branch logic is exercised without network.
# ---------------------------------------------------------------------------

def test_scope_monthly_topup_no_accessions_returns_empty(pipeline, monkeypatch):
    """{"monthly_topup": True} hits the XML branch. With get_filings stubbed
    to None, fetch must return 0 rows without error."""
    import pipeline.load_nport as mod  # noqa: F401

    class _StubEdgar:
        @staticmethod
        def get_filings(*args, **kwargs):
            return None

    import sys as _sys
    stub_edgar_mod = type(_sys)("edgar")
    stub_edgar_mod.get_filings = _StubEdgar.get_filings
    stub_config_mod = type(_sys)("config")

    def _noop_configure():
        return None
    stub_config_mod.configure_edgar_identity = _noop_configure
    # Preserve SEC_HEADERS required by load_nport's top-level import.
    import config as real_config  # noqa: WPS433
    stub_config_mod.SEC_HEADERS = real_config.SEC_HEADERS

    monkeypatch.setitem(_sys.modules, "edgar", stub_edgar_mod)
    monkeypatch.setitem(_sys.modules, "config", stub_config_mod)

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        fr = pipeline.fetch({"monthly_topup": True}, staging_con)
    finally:
        staging_con.close()
    assert fr.rows_staged == 0
    assert "stg_nport_holdings" in fr.raw_tables
    assert "stg_nport_fund_universe" in fr.raw_tables


def test_scope_month_accepts_specific_month(pipeline, monkeypatch):
    """{"month": "2026-03"} is accepted and routes through the XML branch."""
    import sys as _sys

    class _StubEdgar:
        @staticmethod
        def get_filings(*args, **kwargs):
            return None

    stub_edgar_mod = type(_sys)("edgar")
    stub_edgar_mod.get_filings = _StubEdgar.get_filings
    stub_config_mod = type(_sys)("config")
    stub_config_mod.configure_edgar_identity = lambda: None
    import config as real_config  # noqa: WPS433
    stub_config_mod.SEC_HEADERS = real_config.SEC_HEADERS

    monkeypatch.setitem(_sys.modules, "edgar", stub_edgar_mod)
    monkeypatch.setitem(_sys.modules, "config", stub_config_mod)

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        fr = pipeline.fetch({"month": "2026-03"}, staging_con)
    finally:
        staging_con.close()
    assert fr.rows_staged == 0


def test_scope_zip_path_passes_through(pipeline, monkeypatch):
    """{"quarter": "2026Q1", "zip_path": "/missing"} should attempt the
    DERA branch; we stub download_dera_zip + build_dera_dataset so no IO
    happens. The point is that scope is accepted without raising."""
    import pipeline.load_nport as mod  # noqa: WPS433

    calls: list[str] = []

    def fake_download(year, quarter, zip_spec=None):
        calls.append(f"dl:{year}Q{quarter}:{zip_spec}")
        return Path("/nonexistent.zip")

    def fake_build(zip_path, filter_ciks=None):
        return {"submissions": [], "holdings_by_accession": {},
                "filter_description": "stubbed"}

    def fake_resolve(submissions, staging_con=None):
        return submissions

    monkeypatch.setattr(mod, "download_dera_zip", fake_download)
    monkeypatch.setattr(mod, "build_dera_dataset", fake_build)
    monkeypatch.setattr(mod, "resolve_amendments", fake_resolve)

    staging_con = duckdb.connect(pipeline._staging_db_path)
    try:
        fr = pipeline.fetch(
            {"quarter": "2026Q1", "zip_path": "/tmp/local"},
            staging_con,
        )
    finally:
        staging_con.close()
    assert fr.rows_staged == 0
    assert calls == ["dl:2026Q1:/tmp/local"]


# ---------------------------------------------------------------------------
# parse() transforms raw staging into the typed target.
# ---------------------------------------------------------------------------

def test_parse_writes_target_staging_table(pipeline, tmp_dbs):
    _seed_staging(
        tmp_dbs["staging"],
        [
            {"series_id": "S000001", "report_month": "2026-01",
             "accession_number": "0001234567-26-000001"},
            {"series_id": "S000001", "report_month": "2026-01",
             "accession_number": "0001234567-26-000001",
             "cusip": "037833101"},
        ],
    )

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pr = pipeline.parse(staging_con)
    finally:
        staging_con.close()
    assert pr.rows_parsed == 2

    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        rows = staging_con.execute(
            "SELECT series_id, report_month, is_latest, backfill_quality, "
            "       entity_id, rollup_entity_id "
            "FROM fund_holdings_v2 ORDER BY cusip"
        ).fetchall()
    finally:
        staging_con.close()
    assert all(r[0] == "S000001" for r in rows)
    assert all(r[1] == "2026-01" for r in rows)
    assert all(r[2] is True for r in rows)
    assert all(r[3] == "direct" for r in rows)
    # Group 2 entity columns left NULL — filled at promote time.
    assert all(r[4] is None for r in rows)
    assert all(r[5] is None for r in rows)


def test_parse_excludes_listed_series(pipeline, tmp_dbs, tmp_path):
    """exclude_file series_ids must be dropped at parse time."""
    excl_path = tmp_path / "excl.txt"
    excl_path.write_text("S000002\n")

    _seed_staging(
        tmp_dbs["staging"],
        [
            {"series_id": "S000001", "report_month": "2026-01",
             "accession_number": "A"},
            {"series_id": "S000002", "report_month": "2026-01",
             "accession_number": "B"},
        ],
    )
    # Pretend we already ran fetch() so the exclude set is populated.
    pipeline._exclude = {"S000002"}

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        rows = staging_con.execute(
            "SELECT DISTINCT series_id FROM fund_holdings_v2"
        ).fetchall()
    finally:
        staging_con.close()
    assert {r[0] for r in rows} == {"S000001"}


# ---------------------------------------------------------------------------
# validate() — entity gate relaxation + dup-accession BLOCK + future-month BLOCK.
# ---------------------------------------------------------------------------

def test_entity_gate_relaxation_flags_not_blocks(pipeline, tmp_dbs):
    """Unresolved series_id → FLAG, not BLOCK (N-PORT relaxation)."""
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000UNKNOWN", "report_month": "2026-01",
          "accession_number": "A"}],
    )

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    staging_con = duckdb.connect(tmp_dbs["staging"])
    prod_con = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()

    assert vr.blocks == [], f"unexpected blocks: {vr.blocks}"
    assert any("series_not_in_mdm" in f for f in vr.flags), (
        f"expected series_not_in_mdm FLAG; got flags={vr.flags}"
    )
    assert vr.promote_ready is True


def test_dup_accession_blocks(pipeline, tmp_dbs):
    """Two distinct accessions for the same (series, month) → BLOCK."""
    _seed_staging(
        tmp_dbs["staging"],
        [
            {"series_id": "S000001", "report_month": "2026-01",
             "accession_number": "A"},
            {"series_id": "S000001", "report_month": "2026-01",
             "accession_number": "B"},
        ],
    )

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    staging_con = duckdb.connect(tmp_dbs["staging"])
    prod_con = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()

    assert any("dup_accession" in b for b in vr.blocks), (
        f"expected dup_accession BLOCK; got blocks={vr.blocks}"
    )
    assert vr.promote_ready is False


def test_future_report_month_blocks(pipeline, tmp_dbs):
    """A staged report_month > current month triggers the obs-07 BLOCK."""
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000001", "report_month": "2099-01",
          "accession_number": "A"}],
    )

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    staging_con = duckdb.connect(tmp_dbs["staging"])
    prod_con = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()

    assert any("report_month_in_future" in b for b in vr.blocks), (
        f"expected report_month_in_future BLOCK; got blocks={vr.blocks}"
    )


def test_empty_staging_is_not_a_block(pipeline, tmp_dbs):
    """An empty run (no new N-PORT filings) passes validate as a no-op."""
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        # Create empty staging tables so parse() has something to read.
        staging_con.execute(_STG_HOLDINGS_DDL)
        staging_con.execute(_STG_UNIVERSE_DDL)
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    staging_con = duckdb.connect(tmp_dbs["staging"])
    prod_con = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        vr = pipeline.validate(staging_con, prod_con)
    finally:
        staging_con.close()
        prod_con.close()
    assert vr.blocks == []


# ---------------------------------------------------------------------------
# Standalone gate helper — tested separately in test_promote_nport_gate.py.
# Keep one smoke test here to ensure the import path is intact.
# ---------------------------------------------------------------------------

def test_assert_no_future_report_month_returns_empty_for_past():
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE fund_holdings_v2 (series_id VARCHAR, report_month VARCHAR)"
    )
    con.execute("INSERT INTO fund_holdings_v2 VALUES ('S1', '2024-06')")
    assert _assert_no_future_report_month(con) == []
