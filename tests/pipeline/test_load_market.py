"""Unit tests for scripts/pipeline/load_market.py (w2-02).

Tests use temp DuckDB files and injected stub clients — no Yahoo / SEC
network calls. The goal is to prove LoadMarketPipeline is a valid
SourcePipeline subclass, registered in PIPELINE_REGISTRY, and that
its scope resolver handles the three documented scope shapes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import SourcePipeline  # noqa: E402
from pipeline.load_market import (  # noqa: E402
    LoadMarketPipeline, _TARGET_TABLE_COLUMNS, classify_unfetchable,
)
from pipeline import pipelines as pipelines_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Prod DDL fixtures — the minimal tables the pipeline reads during
# scope resolution and parse() LEFT JOINs.
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

DDL_MARKET_DATA = (
    "CREATE TABLE market_data (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)


def _init_prod_db(path: str, *, market_rows: list[dict[str, Any]] | None = None) -> None:
    con = duckdb.connect(path)
    try:
        for tbl in ("ingestion_manifest", "ingestion_impacts", "market_data"):
            con.execute(f"DROP TABLE IF EXISTS {tbl}")
        for ddl in (DDL_MANIFEST, DDL_IMPACTS, DDL_MARKET_DATA):
            con.execute(ddl)
        if market_rows:
            df = pd.DataFrame(market_rows)
            con.register("seed_df", df)
            cols = ", ".join(df.columns)
            con.execute(
                f"INSERT INTO market_data ({cols}) SELECT {cols} FROM seed_df"
            )
            con.unregister("seed_df")
        con.execute("CHECKPOINT")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Stub clients — drop-in replacements for YahooClient / SECSharesClient.
# ---------------------------------------------------------------------------

class _StubYahoo:
    def __init__(self, quotes: dict[str, dict] | None = None,
                 metadata: dict[str, dict] | None = None) -> None:
        self._quotes = quotes or {}
        self._metadata = metadata or {}

    def fetch_quote_batch(self, chunk: list[str]) -> dict[str, dict]:
        return {t: self._quotes[t] for t in chunk if t in self._quotes}

    def fetch_metadata(self, sym: str) -> dict | None:
        return self._metadata.get(sym)


class _StubSEC:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self._rows = rows or {}

    def fetch(self, ticker: str) -> dict | None:
        return self._rows.get(ticker)


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
    return LoadMarketPipeline(
        yahoo_client=_StubYahoo(),
        sec_client=_StubSEC(),
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pipeline_attributes():
    """Class-level contract: the four attributes the ABC validates."""
    assert LoadMarketPipeline.name == "market_data"
    assert LoadMarketPipeline.target_table == "market_data"
    assert LoadMarketPipeline.amendment_strategy == "direct_write"
    assert LoadMarketPipeline.amendment_key == ("ticker",)


def test_amendment_strategy_is_direct_write(pipeline):
    """Must NOT be append_is_latest — market_data has no is_latest column."""
    assert pipeline.amendment_strategy == "direct_write"
    assert pipeline.amendment_strategy != "append_is_latest"
    assert pipeline.amendment_strategy != "scd_type2"


def test_target_table_spec_excludes_row_id(pipeline):
    """market_data has no row_id column; the spec must not invent one."""
    spec = pipeline.target_table_spec()
    col_names = [c[0] for c in spec["columns"]]
    assert "row_id" not in col_names
    assert "ticker" in col_names
    assert spec["pk"] == ["ticker"]


def test_registered_in_pipeline_registry():
    """get_pipeline('market_data') must resolve to LoadMarketPipeline."""
    assert "market_data" in pipelines_mod.available_pipelines()
    instance = pipelines_mod.get_pipeline("market_data")
    assert isinstance(instance, LoadMarketPipeline)


def test_integration_with_base_class(pipeline):
    assert isinstance(pipeline, SourcePipeline)


def test_scope_tickers_uppercases_and_dedupes(pipeline):
    """{"tickers": [...]} scope bypasses the DB lookup entirely."""
    tickers = pipeline.resolve_scope_tickers(
        {"tickers": ["aapl", "AAPL", "msft", "GOOG"]},
    )
    assert tickers == ["AAPL", "MSFT", "GOOG"]


def test_scope_stale_days_queries_prod(tmp_dbs):
    """{"stale_days": N} queries prod.market_data for stale fetch_date rows."""
    _init_prod_db(
        tmp_dbs["prod"],
        market_rows=[
            {"ticker": "FRESH", "fetch_date": "2026-04-21"},
            {"ticker": "STALE", "fetch_date": "2026-04-01"},
            {"ticker": "NULL_DATE", "fetch_date": None},
            {"ticker": "UNFETCHABLE", "fetch_date": "2026-01-01",
             "unfetchable": True},
        ],
    )
    # Reinit with seeded data — the tmp_dbs fixture already init'd empty;
    # we need the seeded version so replace the file.
    pipe = LoadMarketPipeline(
        yahoo_client=_StubYahoo(),
        sec_client=_StubSEC(),
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )
    tickers = sorted(pipe.resolve_scope_tickers({"stale_days": 7}))
    # UNFETCHABLE=TRUE excluded; FRESH (1 day old) excluded; STALE + NULL in.
    assert "STALE" in tickers
    assert "NULL_DATE" in tickers
    assert "FRESH" not in tickers
    assert "UNFETCHABLE" not in tickers


def test_fetch_writes_raw_staging_tables(pipeline, tmp_dbs):
    """fetch() must materialize the three raw staging tables even when the
    stubbed clients return nothing — parse() depends on stg_market_tickers
    existing to drive the ticker loop."""
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        result = pipeline.fetch({"tickers": ["AAPL", "MSFT"]}, staging_con)
        tables = {r[0] for r in staging_con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()}
    finally:
        staging_con.close()
    assert result.rows_staged == 2
    assert "stg_market_tickers" in tables
    assert "stg_market_yahoo_raw" in tables
    assert "stg_market_sec_raw" in tables


def test_fetch_plus_parse_emits_typed_market_data(tmp_dbs):
    """End-to-end fetch+parse with injected Yahoo + SEC results."""
    pipe = LoadMarketPipeline(
        yahoo_client=_StubYahoo(
            quotes={
                "AAPL": {"price": 170.0, "fifty_two_week_high": 200.0,
                         "fifty_two_week_low": 150.0,
                         "avg_volume_30d": 50_000_000,
                         "exchange": "NMS"},
            },
            metadata={
                "AAPL": {"sector": "Technology", "industry": "Consumer Electronics",
                         "exchange": "NMS", "float_shares": 15_000_000_000,
                         "long_name": "Apple Inc."},
            },
        ),
        sec_client=_StubSEC(rows={
            "AAPL": {
                "cik": "0000320193",
                "shares_outstanding": 15_500_000_000,
                "shares_as_of": "2026-03-31",
                "shares_form": "10-Q",
                "shares_filed": "2026-04-10",
                "shares_source_tag": "CommonStockSharesOutstanding",
                "public_float_usd": 2.5e12,
            },
        }),
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipe.fetch({"tickers": ["AAPL"]}, staging_con)
        pr = pipe.parse(staging_con)
        row = staging_con.execute(
            "SELECT ticker, price_live, shares_outstanding, market_cap, "
            "       sector, cik FROM market_data"
        ).fetchone()
    finally:
        staging_con.close()

    assert pr.rows_parsed == 1
    assert row[0] == "AAPL"
    assert row[1] == 170.0
    assert row[2] == 15_500_000_000
    # market_cap = price_live * shares_outstanding
    assert row[3] == 170.0 * 15_500_000_000
    assert row[4] == "Technology"
    assert row[5] == "0000320193"


def test_parse_preserves_prod_only_columns(tmp_dbs):
    """direct_write DELETE+INSERT on promote would wipe columns we don't
    re-emit. parse() must COALESCE against attached prod so legacy
    cached columns (price_2025Q1 etc.) and the unfetchable flag survive.
    """
    _init_prod_db(tmp_dbs["prod"], market_rows=[{
        "ticker": "AAPL",
        "price_live": 150.0,
        "price_2025Q1": 42,
        "unfetchable": False,
        "unfetchable_reason": None,
    }])
    pipe = LoadMarketPipeline(
        yahoo_client=_StubYahoo(
            quotes={"AAPL": {"price": 170.0}},
            metadata={"AAPL": {}},
        ),
        sec_client=_StubSEC(),
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )
    staging_con = duckdb.connect(tmp_dbs["staging"])
    try:
        pipe.fetch({"tickers": ["AAPL"]}, staging_con)
        pipe.parse(staging_con)
        row = staging_con.execute(
            "SELECT price_live, price_2025Q1, unfetchable FROM market_data"
        ).fetchone()
    finally:
        staging_con.close()
    assert row[0] == 170.0              # fresh Yahoo price overwrites
    assert row[1] == 42                  # legacy quarterly cache preserved
    assert row[2] is False               # unfetchable flag preserved


def test_classify_unfetchable():
    """Sanity on the pre-HTTP filter — a few representative cases."""
    assert classify_unfetchable("AAPL") is None
    assert classify_unfetchable("") == "empty"
    assert classify_unfetchable("AAPL WT") == "bond"  # whitespace -> bond
    assert classify_unfetchable("FOO-P") == "preferred"
