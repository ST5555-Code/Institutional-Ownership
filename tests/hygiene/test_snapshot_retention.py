"""Subprocess-level tests for ``scripts/hygiene/snapshot_retention.py``.

Each test builds a small, isolated DuckDB file inside a ``tmp_path``,
seeds ``snapshot_registry`` + a handful of synthetic ``%_snapshot_%``
tables, and invokes the enforcement script via the real CLI. Exercising
the script through ``subprocess`` (rather than importing its entry
points) keeps the tests honest about the CLI contract.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hygiene" / "snapshot_retention.py"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bootstrap(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Minimal fixture DB: ``snapshot_registry`` only, no ``schema_versions``."""
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE snapshot_registry (
            snapshot_table_name TEXT PRIMARY KEY,
            base_table          TEXT NOT NULL,
            created_at          TIMESTAMP NOT NULL,
            created_by          TEXT NOT NULL,
            purpose             TEXT NOT NULL,
            expiration          DATE,
            approver            TEXT,
            applied_policy      TEXT NOT NULL,
            notes               TEXT,
            registered_at       TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    return con


def _register_and_create(
    con,
    snapshot_name: str,
    base_table: str,
    *,
    created_at: datetime,
    expiration: date | None,
    policy: str = "default_14d",
    approver: str | None = None,
    purpose: str = "Pre-promote rollback snapshot",
    create_table: bool = True,
) -> None:
    """Seed a registry row and (optionally) the matching snapshot table."""
    con.execute(
        """
        INSERT INTO snapshot_registry (
            snapshot_table_name, base_table, created_at, created_by,
            purpose, expiration, approver, applied_policy
        ) VALUES (?, ?, ?, 'test', ?, ?, ?, ?)
        """,
        [snapshot_name, base_table, created_at, purpose, expiration, approver, policy],
    )
    if create_table:
        con.execute(f'CREATE TABLE "{snapshot_name}" (id INTEGER, payload TEXT)')
        con.execute(f'INSERT INTO "{snapshot_name}" VALUES (1, \'fixture\')')


def _run(db_path: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(db_path), *flags],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def _seed_standard(db_path: Path) -> None:
    """3 expired + 2 fresh + 1 carve-out pointing at a present table."""
    con = _bootstrap(db_path)
    today = date.today()
    long_ago = datetime.combine(today - timedelta(days=30), datetime.min.time())
    recent = datetime.combine(today - timedelta(days=3), datetime.min.time())

    # 3 expired (default_14d)
    for i in range(3):
        _register_and_create(
            con,
            f"alpha_snapshot_2025010{i}",
            "alpha",
            created_at=long_ago,
            expiration=today - timedelta(days=1),
        )

    # 2 fresh (default_14d)
    for i in range(2):
        _register_and_create(
            con,
            f"beta_snapshot_2026010{i}",
            "beta",
            created_at=recent,
            expiration=today + timedelta(days=11),
        )

    # 1 carve-out
    _register_and_create(
        con,
        "gamma_snapshot_20260419",
        "gamma",
        created_at=datetime(2026, 4, 19),
        expiration=today + timedelta(days=60),
        policy="carve_out",
        approver="Serge",
    )
    con.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_reports_no_change(tmp_path):
    db = tmp_path / "t.duckdb"
    _seed_standard(db)

    result = _run(db, "--dry-run")
    assert result.returncode == 0, result.stderr

    assert "SUMMARY: 3 would-delete, 3 retained" in result.stderr
    assert "DRY-RUN: no writes performed" in result.stderr

    # No DB-side changes: 6 registry rows, 6 snapshot tables still present.
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM snapshot_registry").fetchone()[0] == 6
        n = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name LIKE '%_snapshot_%'"
        ).fetchone()[0]
        assert n == 6
    finally:
        con.close()


def test_apply_deletes_expired_only(tmp_path):
    db = tmp_path / "t.duckdb"
    _seed_standard(db)

    result = _run(db, "--apply")
    assert result.returncode == 0, result.stderr
    assert "APPLY: deleted=3" in result.stderr

    con = duckdb.connect(str(db), read_only=True)
    try:
        # 3 registry rows survive: 2 fresh + 1 carve-out
        assert con.execute("SELECT COUNT(*) FROM snapshot_registry").fetchone()[0] == 3
        # Fresh + carve-out tables still exist
        survivors = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE '%_snapshot_%'"
            ).fetchall()
        }
        assert "gamma_snapshot_20260419" in survivors
        assert "beta_snapshot_20260100" in survivors
        assert "beta_snapshot_20260101" in survivors
        # Expired tables are gone
        for i in range(3):
            assert f"alpha_snapshot_2025010{i}" not in survivors
    finally:
        con.close()


def test_mutex_flags(tmp_path):
    db = tmp_path / "t.duckdb"
    _seed_standard(db)

    result = _run(db, "--dry-run", "--apply")
    assert result.returncode != 0
    assert "not allowed with" in result.stderr or "mutually exclusive" in result.stderr


def test_unregistered_is_reported_not_deleted(tmp_path):
    db = tmp_path / "t.duckdb"
    con = _bootstrap(db)
    # One registered, expired; one unregistered that must survive
    _register_and_create(
        con,
        "delta_snapshot_20250101",
        "delta",
        created_at=datetime(2025, 1, 1),
        expiration=date(2025, 1, 15),
    )
    con.execute('CREATE TABLE "mystery_snapshot_20260424" (x INTEGER)')
    con.close()

    result = _run(db, "--apply")
    assert result.returncode == 0, result.stderr
    assert "UNREGISTERED mystery_snapshot_20260424" in result.stderr
    assert "APPLY: deleted=1" in result.stderr

    con = duckdb.connect(str(db), read_only=True)
    try:
        # Registered-expired gone, unregistered survives untouched
        survivors = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE '%_snapshot_%'"
            ).fetchall()
        }
        assert "mystery_snapshot_20260424" in survivors
        assert "delta_snapshot_20250101" not in survivors
    finally:
        con.close()


def test_stale_registration_is_pruned(tmp_path):
    db = tmp_path / "t.duckdb"
    con = _bootstrap(db)
    # Registry row exists, but the table is missing on disk
    _register_and_create(
        con,
        "epsilon_snapshot_20250101",
        "epsilon",
        created_at=datetime(2025, 1, 1),
        expiration=date(2025, 1, 15),
        create_table=False,
    )
    con.close()

    # Dry-run: reports STALE_REGISTRATION but does not mutate
    result = _run(db, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "STALE_REGISTRATION epsilon_snapshot_20250101" in result.stderr
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM snapshot_registry").fetchone()[0] == 1
    finally:
        con.close()

    # Apply: registry row is pruned; no DDL on missing tables
    result = _run(db, "--apply")
    assert result.returncode == 0, result.stderr
    assert "PRUNED stale registry row: epsilon_snapshot_20250101" in result.stderr
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM snapshot_registry").fetchone()[0] == 0
    finally:
        con.close()


def test_registry_missing_exits_nonzero(tmp_path):
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE unrelated (x INTEGER)")
    con.close()

    result = _run(db, "--dry-run")
    assert result.returncode == 3
    assert "snapshot_registry missing" in result.stderr


def test_missing_db_exits_nonzero(tmp_path):
    db = tmp_path / "missing.duckdb"
    result = _run(db, "--dry-run")
    assert result.returncode == 2
    assert "does not exist" in result.stderr
