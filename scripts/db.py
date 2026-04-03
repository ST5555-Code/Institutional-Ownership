"""
Centralized database connection — test isolation, write guard, crash handler.

All scripts import get_db_path() instead of hardcoding DB_PATH.
When --test is active, all reads/writes go to data/13f_test.duckdb.
"""

import os
import sys
import traceback
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(BASE_DIR, "data", "13f.duckdb")
TEST_DB = os.path.join(BASE_DIR, "data", "13f_test.duckdb")
STAGING_DB = os.path.join(BASE_DIR, "data", "13f_staging.duckdb")

_test_mode = False
_staging_mode = False


def set_test_mode(enabled=True):
    global _test_mode
    _test_mode = enabled


def set_staging_mode(enabled=True):
    global _staging_mode
    _staging_mode = enabled


def is_test_mode():
    return _test_mode


def is_staging_mode():
    return _staging_mode


def get_db_path():
    if _test_mode:
        return TEST_DB
    if _staging_mode:
        return STAGING_DB
    return PROD_DB


def assert_write_safe(con):
    """Raise if test mode is on but connection points to production DB."""
    if not _test_mode:
        return
    db_path = get_db_path()
    if "13f_test" not in db_path:
        raise RuntimeError(f"WRITE GUARD: test_mode=True but DB path is {db_path}")


LOG_DIR = os.path.join(BASE_DIR, "logs")


def crash_handler(script_name):
    """Decorator/context manager: log unhandled exceptions to logs/<script>_crash.log."""
    def run_with_crash_log(main_fn):
        try:
            main_fn()
        except SystemExit:
            raise
        except BaseException:
            os.makedirs(LOG_DIR, exist_ok=True)
            crash_path = os.path.join(LOG_DIR, f"{script_name}_crash.log")
            tb = traceback.format_exc()
            ts = datetime.now().isoformat()
            entry = f"\n{'='*60}\nCRASH: {ts}\n{'='*60}\n{tb}\n"
            with open(crash_path, "a") as f:
                f.write(entry)
            print(entry, file=sys.stderr, flush=True)
            sys.exit(1)
    return run_with_crash_log
