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
    """Path for the write DB (staging when active, test when testing, else prod)."""
    if _test_mode:
        return TEST_DB
    if _staging_mode:
        return STAGING_DB
    return PROD_DB


def get_read_db_path():
    """Path for read-only lookups — always production (or test DB in test mode).
    In staging mode, reference data (holdings, securities, managers) lives in prod.
    New/updated data is written to staging via get_db_path()."""
    if _test_mode:
        return TEST_DB
    return PROD_DB


def connect_read():
    """Open a read-only connection to the reference DB."""
    import duckdb
    return duckdb.connect(get_read_db_path(), read_only=True)


def connect_write():
    """Open a read-write connection to the write DB (staging or prod)."""
    import duckdb
    return duckdb.connect(get_db_path())


def assert_write_safe(con):
    """Raise if test mode is on but connection points to production DB."""
    if not _test_mode:
        return
    db_path = get_db_path()
    if "13f_test" not in db_path:
        raise RuntimeError(f"WRITE GUARD: test_mode=True but DB path is {db_path}")


LOG_DIR = os.path.join(BASE_DIR, "logs")

# Reference tables that staging needs read access to (copied from production)
REFERENCE_TABLES = [
    "holdings", "securities", "managers", "market_data", "filings",
    "fund_holdings", "fund_universe", "adv_managers", "parent_bridge",
]

# Entity tables — the entire entity MDM layer. The staging workflow
# (sync_staging.py / diff_staging.py / promote_staging.py) operates
# on exactly this list. Order matters for restore: parents before children
# so FKs resolve. entities is the root.
ENTITY_TABLES = [
    "entities",
    "entity_identifiers",
    "entity_relationships",
    "entity_aliases",
    "entity_classification_history",
    "entity_rollup_history",
    "entity_identifiers_staging",
    "entity_relationships_staging",
    "entity_overrides_persistent",
]

# Sequences associated with entity tables. Must be reset to MAX(id)+1
# after any sync/promote/restore so subsequent inserts don't collide.
ENTITY_SEQUENCES = [
    ("entity_id_seq", "entities", "entity_id"),
    ("relationship_id_seq", "entity_relationships", "relationship_id"),
    ("identifier_staging_id_seq", "entity_identifiers_staging", "staging_id"),
]


def seed_staging():
    """Copy reference tables from production to staging DB for read access.
    Only copies tables that don't already exist in staging."""
    import duckdb
    if not _staging_mode:
        return
    os.makedirs(os.path.dirname(STAGING_DB), exist_ok=True)
    prod = duckdb.connect(PROD_DB, read_only=True)
    staging = duckdb.connect(STAGING_DB)
    copied = 0
    for table in REFERENCE_TABLES:
        try:
            staging.execute(f"SELECT 1 FROM {table} LIMIT 1")
            continue  # already exists in staging
        except Exception:
            pass
        try:
            df = prod.execute(f"SELECT * FROM {table}").fetchdf()
            staging.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
            copied += 1
        except Exception:
            pass
    prod.close()
    staging.close()
    if copied:
        print(f"  Staging seeded: {copied} reference tables copied from production", flush=True)


def record_freshness(con, table_name, row_count=None):
    """Stamp `data_freshness` with a fresh timestamp + row_count for `table_name`.

    Used by pipeline scripts at the end of each successful rebuild so the
    React footer badge (`/api/v1/freshness`) can surface staleness per
    the Batch 3-A SLA thresholds in ARCHITECTURE_REVIEW.md.

    If `row_count` is not provided, does a `SELECT COUNT(*) FROM <table>`.
    Safe no-op (warning only) if the `data_freshness` table is missing —
    e.g., when running against a fresh DB that hasn't had the Batch 3-A
    migration applied yet.
    """
    if row_count is None:
        try:
            row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        except Exception as e:
            print(f"  [record_freshness] could not count {table_name}: {e}", flush=True)
            return
    try:
        con.execute(
            "INSERT OR REPLACE INTO data_freshness "
            "(table_name, last_computed_at, row_count) "
            "VALUES (?, CURRENT_TIMESTAMP, ?)",
            [table_name, row_count],
        )
    except Exception as e:
        # data_freshness table missing (pre-Batch-3A DB) — non-fatal.
        print(f"  [record_freshness] skipped ({table_name}): {e}", flush=True)


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
