"""Unit tests for scripts/pipeline/load_adv.py (w2-05).

Tests run entirely against in-memory CSV bytes and temp DuckDB files —
no network, no SEC download. They prove the class is a valid
SourcePipeline subclass, registered in the pipeline registry, that
scope shapes are accepted, that parse() normalises the staged CSV into
the target table, and that validate()/promote() enforce the contract
Serge calls out (zero-row BLOCK, >10% delta WARN, whole-universe
replace semantics).
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import SourcePipeline  # noqa: E402
from pipeline.load_adv import (  # noqa: E402
    LoadADVPipeline,
    _TARGET_TABLE_COLUMNS,
    _classify_strategy,
    _extract_csv_from_zip,
    _parse_csv_bytes,
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

DDL_ADV_MANAGERS = (
    "CREATE TABLE adv_managers (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)


def _init_prod_db(path: str) -> None:
    con = duckdb.connect(path)
    try:
        for ddl in (DDL_MANIFEST, DDL_IMPACTS, DDL_ADV_MANAGERS):
            con.execute(ddl)
        con.execute("CHECKPOINT")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Sample CSV builder — tiny ADV bulk export with the columns we parse.
# ---------------------------------------------------------------------------

def _build_adv_csv(rows: list[dict]) -> bytes:
    """Build a minimal ADV-shaped CSV. Only the columns we read are needed."""
    import csv as _csv

    cols = [
        "Organization CRD#", "SEC#", "CIK#",
        "Primary Business Name", "Legal Name",
        "Main Office City", "Main Office State",
        "Main Office Street Address 1",
        "5F(2)(a)", "5F(2)(b)", "5F(2)(c)", "5F(2)(f)",
        "Any Hedge Funds", "Any PE Funds", "Any VC Funds",
    ]
    buf = io.StringIO()
    writer = _csv.DictWriter(
        buf, fieldnames=cols, quoting=_csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue().encode("latin-1")


def _build_adv_zip(rows: list[dict]) -> bytes:
    csv_bytes = _build_adv_csv(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("IA_ADV_Base_A_20260101_20260331.csv", csv_bytes)
    return out.getvalue()


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
    return LoadADVPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_pipeline_attributes():
    assert LoadADVPipeline.name == "adv_registrants"
    assert LoadADVPipeline.target_table == "adv_managers"
    assert LoadADVPipeline.amendment_strategy == "direct_write"
    assert LoadADVPipeline.amendment_key == ("crd_number",)


def test_integration_with_base_class(pipeline):
    assert isinstance(pipeline, SourcePipeline)


def test_target_table_spec(pipeline):
    spec = pipeline.target_table_spec()
    assert spec["pk"] == ["crd_number"]
    col_names = [c[0] for c in spec["columns"]]
    for required in (
        "crd_number", "cik", "firm_name",
        "adv_5f_raum", "pct_discretionary",
        "strategy_inferred", "is_activist",
    ):
        assert required in col_names


def test_registered_in_pipeline_registry():
    from pipeline.pipelines import PIPELINE_REGISTRY, get_pipeline
    assert "adv_registrants" in PIPELINE_REGISTRY
    inst = get_pipeline("adv_registrants")
    assert isinstance(inst, LoadADVPipeline)
    assert isinstance(inst, SourcePipeline)


def test_scope_zip_accepted(pipeline, tmp_path):
    """fetch() accepts {'zip_path': ...} and stages rows from the local file."""
    zip_path = tmp_path / "adv.zip"
    zip_path.write_bytes(_build_adv_zip([
        {
            "Organization CRD#": "105028",
            "Primary Business Name": "VANGUARD GROUP INC",
            "5F(2)(c)": "7000000000000",
            "5F(2)(a)": "7000000000000",
        },
        {
            "Organization CRD#": "100040",
            "Primary Business Name": "ELLIOTT INVESTMENT MANAGEMENT LP",
            "5F(2)(c)": "60000000000",
            "5F(2)(a)": "60000000000",
        },
    ]))

    staging = duckdb.connect(pipeline._staging_db_path)
    try:
        result = pipeline.fetch({"zip_path": str(zip_path)}, staging)
    finally:
        staging.close()

    assert result.rows_staged == 2
    assert "stg_adv_raw" in result.raw_tables


# ---------------------------------------------------------------------------
# Parse / classify tests
# ---------------------------------------------------------------------------

def test_parse_normalises_aum_and_classifies():
    csv_bytes = _build_adv_csv([
        {
            "Organization CRD#": "105028",
            "Primary Business Name": "VANGUARD INDEX FUNDS",
            "5F(2)(a)": "7,000,000,000",
            "5F(2)(b)": "0",
            "5F(2)(c)": "7,000,000,000",
            "5F(2)(f)": "200",
        },
        {
            "Organization CRD#": "100040",
            "Primary Business Name": "ELLIOTT INVESTMENT MANAGEMENT",
            "5F(2)(a)": "60000000000",
            "5F(2)(b)": "0",
            "5F(2)(c)": "60000000000",
            "5F(2)(f)": "10",
            "Any Hedge Funds": "Y",
        },
    ])
    df = _parse_csv_bytes(csv_bytes)
    assert len(df) == 2
    # Numeric coercion: commas stripped, integer column is int64.
    assert df["adv_5f_raum"].iloc[0] == 7_000_000_000
    assert df["adv_5f_num_accts"].dtype.kind in ("i", "u")
    # pct_discretionary correctly computed.
    assert df["pct_discretionary"].iloc[0] == 100.0
    # Strategy classifier: INDEX keyword → passive.
    assert df["strategy_inferred"].iloc[0] == "passive"
    # Elliott — activist flagged; has_hedge_funds=Y → hedge_fund.
    assert bool(df["is_activist"].iloc[1]) is True
    assert df["strategy_inferred"].iloc[1] == "hedge_fund"


def test_classify_strategy_passive_by_low_discretionary():
    row = {"firm_name": "GENERIC ADVISER", "pct_discretionary": 5}
    assert _classify_strategy(row) == "passive"


def test_classify_strategy_active_high_discretionary():
    row = {"firm_name": "BLACKROCK FUND ADVISORS", "pct_discretionary": 95}
    assert _classify_strategy(row) == "active"


def test_classify_strategy_private_equity():
    row = {
        "firm_name": "APOLLO PRIVATE EQUITY",
        "pct_discretionary": 50,
        "has_pe_funds": "Y",
    }
    assert _classify_strategy(row) == "private_equity"


def test_extract_csv_from_zip_missing_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", b"no csv here")
    with pytest.raises(FileNotFoundError):
        _extract_csv_from_zip(buf.getvalue())


# ---------------------------------------------------------------------------
# Validate tests
# ---------------------------------------------------------------------------

def test_validate_blocks_on_empty_staging(pipeline, tmp_dbs):
    staging = duckdb.connect(tmp_dbs["staging"])
    prod = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        # No staging table at all → BLOCK.
        vr = pipeline.validate(staging, prod)
    finally:
        staging.close()
        prod.close()
    assert vr.blocks == ["adv_staging_empty"]
    assert not vr.promote_ready


def test_validate_warns_on_large_row_delta(pipeline, tmp_dbs):
    # Seed prod with 1000 rows so staging=500 ⇒ 50% delta ⇒ WARN.
    prod_w = duckdb.connect(tmp_dbs["prod"])
    try:
        prod_w.executemany(
            "INSERT INTO adv_managers (crd_number) VALUES (?)",
            [[str(i)] for i in range(1000)],
        )
    finally:
        prod_w.close()

    staging = duckdb.connect(tmp_dbs["staging"])
    try:
        staging.execute(
            "CREATE TABLE adv_managers (\n    "
            + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
            + "\n)"
        )
        staging.executemany(
            "INSERT INTO adv_managers (crd_number) VALUES (?)",
            [[str(i)] for i in range(500)],
        )
    finally:
        staging.close()

    staging_ro = duckdb.connect(tmp_dbs["staging"])
    prod_ro = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        vr = pipeline.validate(staging_ro, prod_ro)
    finally:
        staging_ro.close()
        prod_ro.close()

    assert not vr.blocks
    assert any("row_count_delta" in w for w in vr.warns)


# ---------------------------------------------------------------------------
# Promote semantics test — whole-universe replace.
# ---------------------------------------------------------------------------

def test_promote_replaces_full_universe(pipeline, tmp_dbs):
    """Staged rows should fully supplant prior prod rows."""
    # Seed prod with stale universe.
    prod_w = duckdb.connect(tmp_dbs["prod"])
    try:
        prod_w.execute(
            "INSERT INTO adv_managers (crd_number, firm_name) "
            "VALUES ('111111', 'OLD FIRM A'), ('222222', 'OLD FIRM B')"
        )
    finally:
        prod_w.close()

    # Build staged universe with one overlapping CRD and one brand new one.
    staging = duckdb.connect(tmp_dbs["staging"])
    try:
        staging.execute(
            "CREATE TABLE adv_managers (\n    "
            + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
            + "\n)"
        )
        staging.execute(
            "INSERT INTO adv_managers (crd_number, firm_name) "
            "VALUES ('111111', 'NEW FIRM A'), ('333333', 'BRAND NEW FIRM')"
        )
    finally:
        staging.close()

    # Seed a manifest row so promote can record impacts.
    run_id = "adv_test_run"
    prod_w = duckdb.connect(tmp_dbs["prod"])
    try:
        prod_w.execute(
            "INSERT INTO ingestion_manifest "
            "(manifest_id, source_type, object_type, object_key, "
            " source_url, run_id, fetch_status) "
            "VALUES (1, 'adv_registrants', 'SCOPE', 'adv:test', "
            "'scope://test', ?, 'approved')",
            [run_id],
        )
        pipeline.promote(run_id, prod_w)
    finally:
        prod_w.close()

    # After promote: only staged rows should remain.
    prod_ro = duckdb.connect(tmp_dbs["prod"], read_only=True)
    try:
        rows = prod_ro.execute(
            "SELECT crd_number, firm_name FROM adv_managers "
            "ORDER BY crd_number"
        ).fetchall()
        impacts = prod_ro.execute(
            "SELECT unit_type, unit_key_json FROM ingestion_impacts "
            "ORDER BY impact_id"
        ).fetchall()
    finally:
        prod_ro.close()

    assert rows == [
        ("111111", "NEW FIRM A"),
        ("333333", "BRAND NEW FIRM"),
    ]
    # Two new impacts recorded, one per staged CRD.
    new_impacts = [i for i in impacts if i[0] == "upsert"]
    assert len(new_impacts) == 2


# ---------------------------------------------------------------------------
# CLI smoke — parser accepts documented flags.
# ---------------------------------------------------------------------------

def test_cli_parse_flags():
    from pipeline.load_adv import _parse_cli
    ns = _parse_cli(["--zip", "/tmp/foo.zip", "--auto-approve"])
    assert ns.zip == "/tmp/foo.zip"
    assert ns.auto_approve is True
    assert ns.dry_run is False
