"""Regression test for int-04 Phase 1: issuer_name propagation in build_cusip.py.

Verifies that scripts/build_cusip.py::SECURITIES_UPDATE_SQL refreshes
securities.issuer_name from cusip_classifications.issuer_name. Covers the RC4
scope-guard fix (Phase 0 findings: docs/findings/int-04-p0-findings.md §1.3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_cusip import (  # noqa: E402
    SECURITIES_UPDATE_SQL,
    SECURITIES_UPSERT_SQL,
    update_securities_from_classifications,
)


DDL_SECURITIES = """
CREATE TABLE securities (
    cusip                 VARCHAR PRIMARY KEY,
    issuer_name           VARCHAR,
    ticker                VARCHAR,
    security_type         VARCHAR,
    exchange              VARCHAR,
    market_sector         VARCHAR,
    canonical_type        VARCHAR,
    canonical_type_source VARCHAR,
    is_equity             BOOLEAN,
    is_priceable          BOOLEAN,
    ticker_expected       BOOLEAN,
    is_active             BOOLEAN DEFAULT TRUE,
    figi                  VARCHAR
)
"""

DDL_CC = """
CREATE TABLE cusip_classifications (
    cusip                 VARCHAR PRIMARY KEY,
    canonical_type        VARCHAR NOT NULL,
    canonical_type_source VARCHAR NOT NULL,
    raw_type_mode         VARCHAR,
    market_sector         VARCHAR,
    issuer_name           VARCHAR,
    ticker                VARCHAR,
    figi                  VARCHAR,
    exchange              VARCHAR,
    is_equity             BOOLEAN NOT NULL DEFAULT FALSE,
    ticker_expected       BOOLEAN NOT NULL DEFAULT FALSE,
    is_priceable          BOOLEAN NOT NULL DEFAULT FALSE,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    classification_source VARCHAR NOT NULL,
    confidence            VARCHAR NOT NULL,
    first_seen_date       DATE NOT NULL
)
"""


def _make_db():
    con = duckdb.connect(":memory:")
    con.execute(DDL_SECURITIES)
    con.execute(DDL_CC)
    return con


def _seed_cc(con, cusip, issuer_name):
    con.execute(
        """
        INSERT INTO cusip_classifications
        (cusip, canonical_type, canonical_type_source, raw_type_mode,
         market_sector, issuer_name, ticker, figi, exchange,
         is_equity, ticker_expected, is_priceable, is_active,
         classification_source, confidence, first_seen_date)
        VALUES (?, 'COMMON', 'raw_type', 'COM', 'Equity', ?, 'FOO', 'BBG000X',
                'NASDAQ', TRUE, TRUE, TRUE, TRUE, 'openfigi', 'HIGH',
                DATE '2026-01-01')
        """,
        [cusip, issuer_name],
    )


def test_issuer_name_propagates_on_update():
    """UPDATE path refreshes securities.issuer_name when cc.issuer_name changes."""
    con = _make_db()
    _seed_cc(con, "000000001", "Old Issuer Inc")
    update_securities_from_classifications(con)

    row = con.execute(
        "SELECT issuer_name FROM securities WHERE cusip = '000000001'"
    ).fetchone()
    assert row == ("Old Issuer Inc",), "INSERT path failed to seed issuer_name"

    con.execute(
        "UPDATE cusip_classifications SET issuer_name = 'New Issuer Corp' WHERE cusip = '000000001'"
    )
    update_securities_from_classifications(con)

    row = con.execute(
        "SELECT issuer_name FROM securities WHERE cusip = '000000001'"
    ).fetchone()
    assert row == ("New Issuer Corp",), (
        "RC4 regression: securities.issuer_name did not refresh from cusip_classifications.issuer_name"
    )


def test_issuer_name_coalesce_preserves_s_value_when_cc_null():
    """UPDATE with cc.issuer_name NULL must not wipe an existing securities value."""
    con = _make_db()
    _seed_cc(con, "000000002", "Kept Issuer Inc")
    update_securities_from_classifications(con)

    con.execute(
        "UPDATE cusip_classifications SET issuer_name = NULL WHERE cusip = '000000002'"
    )
    update_securities_from_classifications(con)

    row = con.execute(
        "SELECT issuer_name FROM securities WHERE cusip = '000000002'"
    ).fetchone()
    assert row == ("Kept Issuer Inc",), (
        "COALESCE guard broken: NULL cc.issuer_name wiped securities.issuer_name"
    )


def test_sql_contains_issuer_name_update():
    """Static guard: the SQL string itself must reference issuer_name in the SET clause."""
    assert "issuer_name" in SECURITIES_UPDATE_SQL, (
        "SECURITIES_UPDATE_SQL is missing issuer_name — RC4 fix regressed"
    )
    assert "issuer_name" in SECURITIES_UPSERT_SQL, (
        "SECURITIES_UPSERT_SQL is missing issuer_name"
    )
