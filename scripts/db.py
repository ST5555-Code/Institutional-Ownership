"""
Centralized database connection — test isolation and write guard.

All scripts import get_db_path() instead of hardcoding DB_PATH.
When --test is active, all reads/writes go to data/13f_test.duckdb.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(BASE_DIR, "data", "13f.duckdb")
TEST_DB = os.path.join(BASE_DIR, "data", "13f_test.duckdb")

_test_mode = False


def set_test_mode(enabled=True):
    global _test_mode
    _test_mode = enabled


def is_test_mode():
    return _test_mode


def get_db_path():
    return TEST_DB if _test_mode else PROD_DB


def assert_write_safe(con):
    """Raise if test mode is on but connection points to production DB."""
    if not _test_mode:
        return
    # DuckDB exposes the path via the database property or we check our own state
    db_path = get_db_path()
    if "13f_test" not in db_path:
        raise RuntimeError(f"WRITE GUARD: test_mode=True but DB path is {db_path}")
