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


# ---------------------------------------------------------------------------
# INF50 — _cleanup_staging hard-fail + pre-fetch purge
# ---------------------------------------------------------------------------

def test_inf50_cleanup_drops_typed_and_raw_staging(pipeline, tmp_dbs):
    """_cleanup_staging must drop the typed target table AND both raw
    N-PORT staging tables. After the call, none should be queryable."""
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000001", "report_month": "2026-01",
          "accession_number": "A"}],
    )
    # Run parse() to create the typed staging table.
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    # Sanity: all three tables exist and have rows.
    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        assert staging_con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2"
        ).fetchone()[0] >= 1
        assert staging_con.execute(
            "SELECT COUNT(*) FROM stg_nport_holdings"
        ).fetchone()[0] >= 1
        assert staging_con.execute(
            "SELECT COUNT(*) FROM stg_nport_fund_universe"
        ).fetchone()[0] >= 0  # universe may be empty under default seed
    finally:
        staging_con.close()

    pipeline._cleanup_staging("test_run_50")

    # All three tables must now raise CatalogException on SELECT — they
    # were DROPped and the post-cleanup assertion confirmed it.
    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        for t in ("fund_holdings_v2", "stg_nport_holdings",
                  "stg_nport_fund_universe"):
            with pytest.raises(duckdb.CatalogException):
                staging_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
    finally:
        staging_con.close()


def test_inf50_cleanup_raises_when_table_undropped(pipeline, tmp_dbs,
                                                    monkeypatch):
    """If something subverts DROP TABLE IF EXISTS so a target table
    survives, _cleanup_staging must raise (not warn) per INF50."""
    # Seed staging with a stg_nport_holdings table containing rows.
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000001", "report_month": "2026-01",
          "accession_number": "A"}],
    )

    # Monkeypatch duckdb.DuckDBPyConnection.execute to no-op the DROP
    # statements but pass everything else through. Reproduces a case
    # where DROP fails silently — the pre-fix code would have logged
    # a warning and returned; the fix raises RuntimeError instead.
    real_execute = duckdb.DuckDBPyConnection.execute

    def fake_execute(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper().startswith(
            "DROP TABLE"
        ):
            return self  # no-op, mimics a silently-skipped DROP
        return real_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(
        duckdb.DuckDBPyConnection, "execute", fake_execute,
    )

    with pytest.raises(RuntimeError, match="staging is contaminated"):
        pipeline._cleanup_staging("test_run_50_fail")


def test_inf50_pre_fetch_purge_clears_stale_rows(pipeline, tmp_dbs):
    """_purge_stale_raw_staging must DELETE leftover rows from prior
    runs before fetch begins writing."""
    # Seed raw staging with rows from a 'prior run'.
    _seed_staging(
        tmp_dbs["staging"],
        [
            {"series_id": "S000001", "report_month": "2026-01",
             "accession_number": "PRIOR-A"},
            {"series_id": "S000002", "report_month": "2026-01",
             "accession_number": "PRIOR-B"},
        ],
    )
    # Add a universe row too so both tables get exercised.
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        staging_con.execute(
            "INSERT INTO stg_nport_fund_universe "
            "(series_id, fund_cik, fund_name, family_name, total_net_assets, "
            " fund_category, is_actively_managed, total_holdings_count, "
            " equity_pct, top10_concentration, last_updated, fund_strategy, "
            " best_index, manifest_id) VALUES "
            "('S000001','0000000001','F','Fam',1.0,'mixed',TRUE,1,NULL,"
            "NULL,NOW(),'mixed',NULL,NULL)"
        )

        pre_h = staging_con.execute(
            "SELECT COUNT(*) FROM stg_nport_holdings"
        ).fetchone()[0]
        pre_u = staging_con.execute(
            "SELECT COUNT(*) FROM stg_nport_fund_universe"
        ).fetchone()[0]
        assert pre_h >= 2 and pre_u == 1

        pipeline._purge_stale_raw_staging(staging_con)

        post_h = staging_con.execute(
            "SELECT COUNT(*) FROM stg_nport_holdings"
        ).fetchone()[0]
        post_u = staging_con.execute(
            "SELECT COUNT(*) FROM stg_nport_fund_universe"
        ).fetchone()[0]
        assert post_h == 0
        assert post_u == 0
    finally:
        staging_con.close()


# ---------------------------------------------------------------------------
# INF52 — pre-promote entity enrichment
# ---------------------------------------------------------------------------

def test_inf52_pre_promote_enrichment_populates_entity_columns(
    pipeline, tmp_dbs,
):
    """_enrich_staging_entities must populate entity_id /
    rollup_entity_id / dm_entity_id / dm_rollup_entity_id /
    dm_rollup_name on staging.fund_holdings_v2 BEFORE super().promote()
    runs the int-23 downgrade-refusal guard."""
    # Seed staging holdings + run parse() to create typed table with
    # NULL entity columns.
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000001", "report_month": "2026-01",
          "accession_number": "A"}],
    )
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    # Confirm pre-state: NULLs everywhere.
    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        ent, rec, dm_e, dm_r, dm_n = staging_con.execute(
            "SELECT entity_id, rollup_entity_id, dm_entity_id, "
            "       dm_rollup_entity_id, dm_rollup_name "
            "FROM fund_holdings_v2"
        ).fetchone()
    finally:
        staging_con.close()
    assert (ent, rec, dm_e, dm_r, dm_n) == (None, None, None, None, None)

    # Seed prod entity tables — series_id S000001 → entity_id 42 with
    # EC rollup → 100, DM rollup → 200, dm_rollup_name = "Test Family".
    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        prod_con.execute(
            "INSERT INTO entity_identifiers VALUES "
            "(42, 'series_id', 'S000001', DATE '9999-12-31')"
        )
        prod_con.execute(
            "INSERT INTO entity_rollup_history VALUES "
            "(42, 'economic_control_v1', 100, DATE '9999-12-31')"
        )
        prod_con.execute(
            "INSERT INTO entity_rollup_history VALUES "
            "(42, 'decision_maker_v1', 200, DATE '9999-12-31')"
        )
        prod_con.execute(
            "INSERT INTO entity_aliases VALUES "
            "(100, 'Test Family', TRUE, DATE '9999-12-31')"
        )
        prod_con.execute("CHECKPOINT")

        # Run pre-promote enrichment.
        n = pipeline._enrich_staging_entities(prod_con, {"S000001"})
    finally:
        prod_con.close()

    assert n == 1

    # Confirm post-state: entity columns populated.
    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        ent, rec, dm_e, dm_r, dm_n = staging_con.execute(
            "SELECT entity_id, rollup_entity_id, dm_entity_id, "
            "       dm_rollup_entity_id, dm_rollup_name "
            "FROM fund_holdings_v2"
        ).fetchone()
    finally:
        staging_con.close()
    assert ent == 42
    assert rec == 100
    assert dm_e == 42
    assert dm_r == 200
    assert dm_n == "Test Family"


def test_inf52_pre_promote_enrichment_no_op_on_empty_set(pipeline):
    """No staged series_ids → no-op, returns 0, no exception."""
    # prod_con not even needed when series_touched is empty.
    assert pipeline._enrich_staging_entities(None, set()) == 0


def test_inf52_pre_promote_enrichment_warns_when_entity_tables_missing(
    pipeline, tmp_dbs,
):
    """If prod's entity_* tables are absent, surface as a warning and
    return 0 — int-23 guard still catches real downgrades and the
    post-promote _bulk_enrich_run logs the same condition."""
    # Build a stripped-down prod DB without entity_identifiers.
    bare_prod = tmp_dbs["staging"].replace("staging", "bare_prod")
    bare = duckdb.connect(bare_prod)
    try:
        bare.execute("CREATE TABLE other (x INTEGER)")
        bare.execute("CHECKPOINT")
    finally:
        bare.close()

    bare_con = duckdb.connect(bare_prod)
    try:
        # Should not raise; logs a warning and returns 0.
        n = pipeline._enrich_staging_entities(bare_con, {"S000001"})
    finally:
        bare_con.close()
    assert n == 0


# ---------------------------------------------------------------------------
# PR-2 — fund_strategy lock (apply + upsert preserve)
# ---------------------------------------------------------------------------

def _seed_universe_row(staging_path: str, series_id: str,
                       fund_strategy: str) -> None:
    """Seed stg_nport_fund_universe with one row carrying the classifier
    output the pipeline would have produced for `series_id`.

    PR-3: ``fund_category`` and ``is_actively_managed`` were dropped from
    prod ``fund_universe`` (both fully redundant with ``fund_strategy``).
    Staging still has those columns; we leave them NULL so the staging
    schema stays compatible without driving prod values."""
    con = duckdb.connect(staging_path)
    try:
        con.execute(_STG_UNIVERSE_DDL)
        con.execute(
            "DELETE FROM stg_nport_fund_universe WHERE series_id = ?",
            [series_id],
        )
        con.execute(
            """
            INSERT INTO stg_nport_fund_universe (
                fund_cik, fund_name, series_id, family_name,
                total_net_assets, fund_category, is_actively_managed,
                total_holdings_count, equity_pct, top10_concentration,
                last_updated, fund_strategy, best_index, manifest_id
            ) VALUES (?,?,?,?,?,NULL,NULL,?,?,?,NOW(),?,?,NULL)
            """,
            [
                "0000000001", f"{series_id} Fund", series_id, "Family",
                1_000_000.0, 50, 0.95, 0.40,
                fund_strategy, None,
            ],
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()


def test_pr2_lock_new_series_writes_classifier_output(pipeline, tmp_dbs):
    """Branch A: series_id has no row in fund_universe yet — the
    classifier output flows through to prod unchanged."""
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000NEW", "report_month": "2026-01",
          "accession_number": "A", "fund_strategy": "equity"}],
    )
    _seed_universe_row(tmp_dbs["staging"], "S000NEW",
                       fund_strategy="equity")

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        # Lock helper is a no-op (no prior row).
        n_locked = pipeline._apply_fund_strategy_lock(
            prod_con, {"S000NEW"},
        )
        assert n_locked == 0

        n_upserted = pipeline._upsert_fund_universe(
            prod_con, {"S000NEW"},
        )
        assert n_upserted == 1

        (strategy,) = prod_con.execute(
            "SELECT fund_strategy "
            "FROM fund_universe WHERE series_id = 'S000NEW'"
        ).fetchone()
    finally:
        prod_con.close()

    assert strategy == "equity"


def test_pr2_lock_existing_nonnull_strategy_preserves_value(pipeline, tmp_dbs):
    """Branch B: series_id already has fund_strategy='passive' in prod;
    a re-classification arriving as 'equity' must be discarded — both at
    the staging-rewrite step and at the upsert COALESCE safety net."""
    # Seed prod with an existing row that has been hand-curated to passive.
    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        prod_con.execute(
            """
            INSERT INTO fund_universe (
                fund_cik, fund_name, series_id, family_name,
                total_net_assets,
                total_holdings_count, equity_pct, top10_concentration,
                last_updated, fund_strategy, best_index
            ) VALUES (?,?,?,?,?,?,?,?,NOW(),?,?)
            """,
            [
                "0000000001", "Invesco QQQ Trust", "S000QQQ", "Invesco",
                250_000_000_000.0, 100, 1.0, 0.50,
                "passive", "NDX",
            ],
        )
        prod_con.execute("CHECKPOINT")
    finally:
        prod_con.close()

    # Staging carries the (wrong) classifier output 'equity'.
    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000QQQ", "report_month": "2026-02",
          "accession_number": "QQQ-1", "fund_strategy": "equity"}],
    )
    _seed_universe_row(tmp_dbs["staging"], "S000QQQ",
                       fund_strategy="equity")

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    # Apply the lock — staging should be rewritten to 'passive'.
    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        n_locked = pipeline._apply_fund_strategy_lock(
            prod_con, {"S000QQQ"},
        )
        assert n_locked == 1
    finally:
        prod_con.close()

    # Verify staging was rewritten in lock-step.
    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        h_strategy = staging_con.execute(
            "SELECT DISTINCT fund_strategy FROM fund_holdings_v2 "
            "WHERE series_id = 'S000QQQ'"
        ).fetchall()
        (u_strategy,) = staging_con.execute(
            "SELECT fund_strategy "
            "FROM stg_nport_fund_universe WHERE series_id = 'S000QQQ'"
        ).fetchone()
    finally:
        staging_con.close()
    assert h_strategy == [("passive",)], (
        f"expected staged holdings rewritten to 'passive', got {h_strategy}"
    )
    assert u_strategy == "passive"

    # Upsert step — even if the lock helper had been bypassed, the
    # COALESCE safety net inside _upsert_fund_universe still preserves
    # the prod value. Re-seed staging back to 'equity' to simulate the
    # bypass path, then call upsert directly.
    _seed_universe_row(tmp_dbs["staging"], "S000QQQ",
                       fund_strategy="equity")

    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        pipeline._upsert_fund_universe(prod_con, {"S000QQQ"})
        (strategy,) = prod_con.execute(
            "SELECT fund_strategy "
            "FROM fund_universe WHERE series_id = 'S000QQQ'"
        ).fetchone()
    finally:
        prod_con.close()
    assert strategy == "passive", (
        f"upsert should have COALESCE'd to prod value 'passive'; got {strategy}"
    )


def test_pr2_lock_existing_null_strategy_writes_classifier_output(
    pipeline, tmp_dbs,
):
    """Branch C: series_id has a row in prod but fund_strategy IS NULL
    (legacy backfill case) — the classifier output must be written."""
    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        prod_con.execute(
            """
            INSERT INTO fund_universe (
                fund_cik, fund_name, series_id, family_name,
                total_net_assets,
                total_holdings_count, equity_pct, top10_concentration,
                last_updated, fund_strategy, best_index
            ) VALUES (?,?,?,?,?,?,?,?,NOW(),?,?)
            """,
            [
                "0000000001", "Legacy Fund", "S000NULL", "Family",
                10_000_000.0, 30, 0.95, 0.30,
                None, None,
            ],
        )
        prod_con.execute("CHECKPOINT")
    finally:
        prod_con.close()

    _seed_staging(
        tmp_dbs["staging"],
        [{"series_id": "S000NULL", "report_month": "2026-02",
          "accession_number": "L-1", "fund_strategy": "equity"}],
    )
    _seed_universe_row(tmp_dbs["staging"], "S000NULL",
                       fund_strategy="equity")

    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipeline.parse(staging_con)
    finally:
        staging_con.close()

    # Lock skips this series (prod fund_strategy IS NULL).
    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        n_locked = pipeline._apply_fund_strategy_lock(
            prod_con, {"S000NULL"},
        )
    finally:
        prod_con.close()
    assert n_locked == 0

    # Staging holdings keep classifier output.
    staging_con = duckdb.connect(tmp_dbs["staging"], read_only=True)
    try:
        h_strategy = staging_con.execute(
            "SELECT DISTINCT fund_strategy FROM fund_holdings_v2 "
            "WHERE series_id = 'S000NULL'"
        ).fetchall()
    finally:
        staging_con.close()
    assert h_strategy == [("equity",)]

    # Upsert writes the classifier output (NULL prior + COALESCE → u value).
    prod_con = duckdb.connect(tmp_dbs["prod"])
    try:
        pipeline._upsert_fund_universe(prod_con, {"S000NULL"})
        (strategy,) = prod_con.execute(
            "SELECT fund_strategy "
            "FROM fund_universe WHERE series_id = 'S000NULL'"
        ).fetchone()
    finally:
        prod_con.close()
    assert strategy == "equity", (
        f"NULL backfill case must accept classifier output; got {strategy}"
    )


def test_pr2_lock_no_op_on_empty_set(pipeline):
    """No staged series_ids → lock helper short-circuits without DB hits."""
    assert pipeline._apply_fund_strategy_lock(None, set()) == 0


def test_pr2_lock_warns_when_fund_universe_missing(pipeline, tmp_dbs):
    """If prod's fund_universe is absent, the lock helper logs and
    returns 0 rather than raising — important for partial test fixtures."""
    bare_prod = tmp_dbs["staging"].replace("staging", "bare_prod_lock")
    bare = duckdb.connect(bare_prod)
    try:
        bare.execute("CREATE TABLE other (x INTEGER)")
        bare.execute("CHECKPOINT")
    finally:
        bare.close()

    bare_con = duckdb.connect(bare_prod)
    try:
        n = pipeline._apply_fund_strategy_lock(bare_con, {"S000QQQ"})
    finally:
        bare_con.close()
    assert n == 0
