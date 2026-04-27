#!/usr/bin/env python3
"""
promote_staging.py — promote staging entity tables to production atomically.

Workflow:
  1. Refuse to run without --approved (hard gate; the diff must have been
     reviewed by a human first).
  2. Snapshot every entity table to {table}_snapshot_{timestamp} inside
     production. Snapshots are intra-DB so rollback is a single SQL pass.
  3. Apply staging → production via DELETE-then-INSERT against the diff
     PK set per table. No full table replace.
  4. Reset entity sequences to MAX(id)+1 of the merged production state.
  5. Run validate_entities.py against production. If any structural gate
     fails, automatically restore from the snapshot taken in step 2.
  6. Append a summary to logs/promotion_history.log.

Usage:
  python3 scripts/promote_staging.py --approved
  python3 scripts/promote_staging.py --approved --rollback 20260410_143022
  python3 scripts/promote_staging.py --list-snapshots
  python3 scripts/promote_staging.py --tables entity_relationships,entity_rollup_history --approved
"""
from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

PROMOTION_LOG = ROOT / "logs" / "promotion_history.log"

# Primary key columns per promotable table — used to compute the diff
# PK set and to drive DELETE/INSERT during apply. Not all prod tables
# declare a formal PK constraint (prod's "degraded schema" pattern —
# see ENTITY_ARCHITECTURE.md), so this dict defines the logical key
# promote_staging.py uses regardless of DB-level constraints.
#
# For `securities` specifically: no DB-level PK/UNIQUE is declared in
# prod OR staging, but `cusip` is empirically unique (0 duplicates,
# 0 NULLs in both DBs as of BLOCK-SECURITIES-DATA-AUDIT Phase 2b).
# Same pattern as the entity tables above.
PK_COLUMNS = {
    # Entity MDM layer
    "entities": ["entity_id"],
    "entity_identifiers": ["entity_id", "identifier_type", "identifier_value", "valid_from"],
    "entity_relationships": ["relationship_id"],
    "entity_aliases": ["entity_id", "alias_name", "valid_from"],
    "entity_classification_history": ["entity_id", "valid_from"],
    "entity_rollup_history": ["entity_id", "rollup_type", "valid_from"],
    "entity_identifiers_staging": ["staging_id"],
    "entity_relationships_staging": ["id"],
    "entity_overrides_persistent": ["override_id"],
    # Canonical reference tables (added 2026-04-18 — Phase 3)
    "cusip_classifications": ["cusip"],
    "securities": ["cusip"],
    # build_managers.py outputs (added 2026-04-19 — Batch 3 close).
    # parent_bridge.cik and cik_crd_direct.cik are empirically unique;
    # managers and cik_crd_links route through the rebuild kind instead
    # (see PROMOTE_KIND), so they do not need PK_COLUMNS entries.
    "parent_bridge": ["cik"],
    "cik_crd_direct": ["cik"],
    # sec-05 Phase 1 (2026-04-21): build_fund_classes +
    # build_benchmark_weights outputs promoted via pk_diff.
    # See sec-05-p0-findings.md §3 for the PK rationale.
    "fund_classes": ["series_id", "class_id"],
    "lei_reference": ["lei"],
    "benchmark_weights": ["index_name", "gics_sector", "as_of_date"],
}

# Per-table validator registration. Each value is one of:
#   - a string naming a validator "kind" handled by _run_validators()
#   - None → promotion proceeds without validation, with an explicit warn
#     printed so the absence is visible rather than silent.
#
# Entity tables share validate_entities.py (one subprocess call covers the
# whole set). The "schema_pk" kind marks tables whose row-level invariants
# are enforced at the DDL layer (formal PRIMARY KEY constraint) — no
# subprocess validator is needed because DuckDB rejects duplicate / NULL
# inserts at the engine. Tables still mapped to None are open follow-ups;
# the explicit None entry is load-bearing — it documents the gap and
# triggers the warn path in _run_validators().
VALIDATOR_MAP = {
    # Entity tables → validate_entities.py
    "entities": "validate_entities",
    "entity_identifiers": "validate_entities",
    "entity_relationships": "validate_entities",
    "entity_aliases": "validate_entities",
    "entity_classification_history": "validate_entities",
    "entity_rollup_history": "validate_entities",
    "entity_identifiers_staging": "validate_entities",
    "entity_relationships_staging": "validate_entities",
    "entity_overrides_persistent": "validate_entities",
    # securities.cusip — formal PRIMARY KEY constraint shipped 2026-04-22
    # via migration 011 (INF28 / int-12 PR #95). DDL-level enforcement is
    # the validator: DuckDB rejects duplicate or NULL CUSIPs at insert
    # time, so promotion does not need a separate validator subprocess.
    "securities": "schema_pk",
    # Canonical tables — no validator registered yet
    "cusip_classifications": None,
    # build_managers.py outputs (2026-04-19 — Batch 3 close)
    "parent_bridge": None,
    "cik_crd_direct": None,
    "managers": None,
    "cik_crd_links": None,
}

# Promotion strategy per table. Default for any table not listed here is
# "pk_diff" — the PK-keyed DELETE-then-INSERT path established for entity
# tables and extended to canonical tables by BLOCK-SECURITIES-DATA-AUDIT
# Phase 3.
#
# "rebuild" — full-replace semantics: snapshot prod, DROP prod, CREATE AS
# SELECT * FROM staging. Use when PK-diff is semantically wrong. Added for
# build_managers.py outputs whose natural keys are not empirically unique
# (managers.cik has ~7.3% duplication from LEFT JOIN fan-out; cik_crd_links
# has 3 duplicate CIKs). See 2026-04-19-rewrite-build-managers.md §2.4.
#
# The rebuild path inherits staging's schema. Any post-hoc columns added
# by later pipeline stages (fetch_13dg `has_13dg`, fetch_ncen `adviser_cik`
# on `managers`) are wiped and must be re-applied by those stages after
# promote — identical to build_managers.py's existing DROP+CTAS semantics.
PROMOTE_KIND = {
    # build_managers.py outputs with non-unique natural keys
    "managers": "rebuild",
    "cik_crd_links": "rebuild",
}


def _kind_for(table: str) -> str:
    """Return the promote strategy for `table`. Defaults to `pk_diff`."""
    return PROMOTE_KIND.get(table, "pk_diff")


def _log(msg: str) -> None:
    PROMOTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(PROMOTION_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _snapshot_name(table: str, sid: str) -> str:
    return f"{table}_snapshot_{sid}"


def _register_snapshot(con, snap: str, base_table: str) -> None:
    """Record the snapshot in ``snapshot_registry`` under the default
    14-day retention policy. Graceful no-op if the registry table does
    not exist — allows promote_staging.py to run against a staging DB
    that has not yet applied migration 018 (the enforcement script is
    always run against production where 018 is a precondition).

    Creation metadata is fixed: every promote_staging snapshot is a
    pre-promote rollback artifact. The enforcement script (see
    ``scripts/hygiene/snapshot_retention.py``) drops rows where
    ``expiration <= today()``; carve-outs and custom purposes must be
    edited directly in the registry after the fact.
    """
    has_registry = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = 'snapshot_registry'"
    ).fetchone()
    if not has_registry:
        return
    # INSERT OR IGNORE because a rerun with the same snapshot_id will
    # DROP + recreate the snapshot table but keep the registry row —
    # the original created_at + expiration still describe the data.
    con.execute(
        """
        INSERT OR IGNORE INTO snapshot_registry (
            snapshot_table_name, base_table, created_at, created_by,
            purpose, expiration, approver, applied_policy, notes
        ) VALUES (
            ?, ?, NOW(), 'scripts/promote_staging.py',
            'Pre-promote rollback snapshot',
            CAST(NOW() AS DATE) + INTERVAL 14 DAY,
            NULL, 'default_14d', NULL
        )
        """,
        [snap, base_table],
    )


def _take_snapshot(con, snapshot_id: str, tables: list[str]) -> None:
    _log(f"  taking snapshot {snapshot_id} ...")
    for t in tables:
        snap = _snapshot_name(t, snapshot_id)
        con.execute(f"DROP TABLE IF EXISTS {snap}")
        con.execute(f"CREATE TABLE {snap} AS SELECT * FROM {t}")
        _register_snapshot(con, snap, t)
        n = con.execute(f"SELECT COUNT(*) FROM {snap}").fetchone()[0]
        _log(f"    snapshot {snap}: {n} rows")


def _restore_snapshot(con, snapshot_id: str, tables: list[str]) -> None:
    _log(f"  RESTORING from snapshot {snapshot_id} ...")
    # Reverse order so child tables drop first (FK-safe). For pk_diff
    # tables, DELETE keeps the schema in place for the subsequent INSERT.
    # For rebuild tables, the forward path may have changed the schema
    # (DROP + CREATE AS SELECT from staging), so restore must also
    # DROP + CREATE AS SELECT from the snapshot rather than DELETE.
    for t in reversed(tables):
        snap = _snapshot_name(t, snapshot_id)
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [snap],
        ).fetchone()[0]
        if not exists:
            _log(f"    WARN: no snapshot for {t} ({snap}) — skipping")
            continue
        if _kind_for(t) == "rebuild":
            con.execute(f"DROP TABLE IF EXISTS {t}")
        else:
            con.execute(f"DELETE FROM {t}")
    for t in tables:
        snap = _snapshot_name(t, snapshot_id)
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [snap],
        ).fetchone()[0]
        if not exists:
            continue
        if _kind_for(t) == "rebuild":
            con.execute(f"CREATE TABLE {t} AS SELECT * FROM {snap}")
        else:
            con.execute(f"INSERT INTO {t} SELECT * FROM {snap}")
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        _log(f"    {t}: restored {n} rows")
    _reset_sequences(con)


def _reset_sequences(con) -> None:
    """DROP + CREATE the sequence at MAX(id)+1. DuckDB does not support
    ALTER SEQUENCE ... RESTART WITH N. Safe in prod because nextval() is
    only called explicitly by application code (entity_sync.py); none of
    the entity tables in prod's degraded schema use sequence DEFAULTs."""
    for seq, table, col in db.ENTITY_SEQUENCES:
        try:
            # Skip silently if the underlying table is missing in prod
            exists = con.execute(
                "SELECT COUNT(*) FROM duckdb_tables() "
                "WHERE database_name = current_database() AND table_name = ?",
                [table],
            ).fetchone()[0]
            if not exists:
                continue
            row = con.execute(
                f"SELECT COALESCE(MAX({col}), 0) + 1 FROM {table}"
            ).fetchone()
            next_val = int(row[0]) if row and row[0] is not None else 1
            con.execute(f"DROP SEQUENCE IF EXISTS {seq}")
            con.execute(f"CREATE SEQUENCE {seq} START WITH {next_val}")
            _log(f"    sequence {seq} restart with {next_val}")
        except Exception as e:
            _log(f"    sequence {seq}: WARN {e}")


def list_snapshots() -> None:
    import duckdb

    con = duckdb.connect(db.PROD_DB, read_only=True)
    rows = con.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name LIKE '%_snapshot_%'
        ORDER BY table_name
        """
    ).fetchall()
    con.close()
    if not rows:
        print("No snapshots found in production DB.")
        return
    # Group by snapshot_id (the part after the last _snapshot_)
    groups: dict[str, list[str]] = {}
    for (name,) in rows:
        idx = name.find("_snapshot_")
        if idx < 0:
            continue
        sid = name[idx + len("_snapshot_") :]
        groups.setdefault(sid, []).append(name[:idx])
    print(f"Snapshots in {db.PROD_DB}:")
    for sid in sorted(groups.keys(), reverse=True):
        tables = sorted(groups[sid])
        print(f"  {sid}  ({len(tables)} tables)")
        for t in tables:
            print(f"    - {t}")


def _heal_override_ids(con, db_label: str) -> int:
    """Backfill NULL override_id in entity_overrides_persistent.

    Two bugs historically landed rows without override_id:
      * admin_bp.py's earlier INSERT omitted the column (no DEFAULT / no
        sequence in prod's degraded schema)
      * Ad-hoc SQL inserts from entity audit sessions
    Rows with NULL PK cannot be matched by promote_staging's diff tool
    (EXCEPT on (NULL) is non-deterministic), so they silently fail to
    promote. This heal runs at the top of the promote path to assign
    deterministic sequential IDs starting from MAX(override_id)+1, so
    identical content in staging + prod converges to identical IDs.

    Ordering: (applied_at, created_at, action, identifier_type,
    identifier_value, entity_cik, reason). Deterministic across DBs
    because the content of the NULL rows is identical in staging + prod
    (staging is CTAS'd from prod; this heals prod first, then staging
    is re-synced or lands on the same tuples).

    Returns the count of rows healed.
    """
    n_null = con.execute(
        "SELECT COUNT(*) FROM entity_overrides_persistent WHERE override_id IS NULL"
    ).fetchone()[0]
    if n_null == 0:
        return 0

    # Rebuild via CTAS-style to get atomic deterministic assignment.
    # Staging = True on ATTACHED; this function runs against whichever
    # connection the caller gave us. Temp table keeps both sides clean.
    con.execute("DROP TABLE IF EXISTS _heal_eop_tmp")
    con.execute("""
        CREATE TEMP TABLE _heal_eop_tmp AS
        SELECT * FROM entity_overrides_persistent WHERE override_id IS NOT NULL
        UNION ALL
        SELECT
          ROW_NUMBER() OVER (
            ORDER BY
              COALESCE(CAST(applied_at AS VARCHAR), ''),
              COALESCE(CAST(created_at AS VARCHAR), ''),
              COALESCE(action, ''),
              COALESCE(identifier_type, ''),
              COALESCE(identifier_value, ''),
              COALESCE(entity_cik, ''),
              COALESCE(reason, '')
          ) + COALESCE((SELECT MAX(override_id) FROM entity_overrides_persistent), 0)
              AS override_id,
          entity_cik, action, field, old_value, new_value, reason, analyst,
          still_valid, applied_at, created_at, identifier_type,
          identifier_value, rollup_type, relationship_context
        FROM entity_overrides_persistent WHERE override_id IS NULL
    """)
    con.execute("DELETE FROM entity_overrides_persistent")
    con.execute("INSERT INTO entity_overrides_persistent SELECT * FROM _heal_eop_tmp")
    con.execute("DROP TABLE _heal_eop_tmp")
    _log(f"    [{db_label}] healed {n_null} entity_overrides_persistent NULL override_ids")
    return n_null


def _apply_table_rebuild(con, table: str) -> dict:
    """Full-replace promote: DROP prod + CREATE AS SELECT from staging.
    Snapshot must have been taken already. Inherits staging's schema —
    see PROMOTE_KIND comment for the multi-writer implications."""
    prev = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    con.execute(f"DROP TABLE {table}")
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM stg.{table}")
    inserted = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return {
        "deleted": prev,
        "modified": 0,
        "inserted_or_replaced": inserted,
        "added_only": inserted,
    }


def _apply_table(con, table: str) -> dict:
    """Apply staging → production for one table. Dispatches on PROMOTE_KIND."""
    if _kind_for(table) == "rebuild":
        return _apply_table_rebuild(con, table)
    pk = PK_COLUMNS[table]
    pk_csv = ", ".join(pk)
    pk_join = " AND ".join(f"prod.{c} = stg.{c}" for c in pk)

    # 1. Find PKs in prod that are NOT in staging → delete
    deleted = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT {pk_csv} FROM {table}
          EXCEPT
          SELECT {pk_csv} FROM stg.{table}
        )
        """
    ).fetchone()[0]
    if deleted:
        con.execute(
            f"""
            DELETE FROM {table}
            WHERE ({pk_csv}) IN (
              SELECT {pk_csv} FROM {table}
              EXCEPT
              SELECT {pk_csv} FROM stg.{table}
            )
            """
        )

    # 2. Find rows where PK matches but content differs → DELETE+INSERT
    #    (we use EXCEPT on the full row, then re-INSERT below)
    modified = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT * FROM stg.{table}
          EXCEPT
          SELECT * FROM {table}
        ) s
        WHERE EXISTS (
          SELECT 1 FROM {table} prod
          WHERE {' AND '.join(f'prod.{c} = s.{c}' for c in pk)}
        )
        """
    ).fetchone()[0]
    if modified:
        con.execute(
            f"""
            DELETE FROM {table}
            WHERE ({pk_csv}) IN (
              SELECT {pk_csv} FROM (
                SELECT * FROM stg.{table}
                EXCEPT
                SELECT * FROM {table}
              ) s
              WHERE EXISTS (
                SELECT 1 FROM {table} p
                WHERE {' AND '.join(f'p.{c} = s.{c}' for c in pk)}
              )
            )
            """
        )

    # 3. Find PKs in staging not in prod (now includes the just-deleted modified rows) → insert
    added_or_replaced = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT {pk_csv} FROM stg.{table}
          EXCEPT
          SELECT {pk_csv} FROM {table}
        )
        """
    ).fetchone()[0]
    if added_or_replaced:
        con.execute(
            f"""
            INSERT INTO {table}
            SELECT * FROM stg.{table}
            WHERE ({pk_csv}) IN (
              SELECT {pk_csv} FROM stg.{table}
              EXCEPT
              SELECT {pk_csv} FROM {table}
            )
            """
        )

    return {
        "deleted": deleted,
        "modified": modified,
        "inserted_or_replaced": added_or_replaced,
        "added_only": added_or_replaced - modified,
    }


def _count_diff(con, table: str) -> dict:
    """Read-only diff counts for a single table. Same semantics as
    _apply_table but without the DELETE/INSERT. Expects staging attached
    as 'stg'. Used by --dry-run."""
    if _kind_for(table) == "rebuild":
        prod_n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        stg_n = con.execute(f"SELECT COUNT(*) FROM stg.{table}").fetchone()[0]
        return {"deleted": prod_n, "modified": 0, "added_only": stg_n}
    pk = PK_COLUMNS[table]
    pk_csv = ", ".join(pk)

    deleted = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT {pk_csv} FROM {table}
          EXCEPT
          SELECT {pk_csv} FROM stg.{table}
        )
        """
    ).fetchone()[0]

    modified = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT * FROM stg.{table}
          EXCEPT
          SELECT * FROM {table}
        ) s
        WHERE EXISTS (
          SELECT 1 FROM {table} p
          WHERE {' AND '.join(f'p.{c} = s.{c}' for c in pk)}
        )
        """
    ).fetchone()[0]

    added_or_replaced = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT {pk_csv} FROM stg.{table}
          EXCEPT
          SELECT {pk_csv} FROM {table}
        )
        """
    ).fetchone()[0]

    return {
        "deleted": deleted,
        "modified": modified,
        "added_only": added_or_replaced,  # same-PK modifieds already in prod; this counts PKs new to prod
    }


def dry_run(tables: list[str]) -> dict:
    """Preview diff counts without snapshotting or applying. Opens both
    DBs READ_ONLY so the operation cannot perturb state."""
    import duckdb

    con = duckdb.connect(db.PROD_DB, read_only=True)
    con.execute(f"ATTACH '{db.STAGING_DB}' AS stg (READ_ONLY)")

    existing_in_prod = {
        r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name = current_database()"
        ).fetchall()
    }
    existing_in_stg = {
        r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name = 'stg'"
        ).fetchall()
    }

    summary: dict = {"dry_run": True, "tables": {}}
    try:
        for t in tables:
            if t not in existing_in_stg:
                _log(f"  SKIP {t}: not present in staging")
                continue
            if t not in existing_in_prod:
                # Full-insert scenario: staging has the table, prod doesn't yet.
                n_stg = con.execute(f"SELECT COUNT(*) FROM stg.{t}").fetchone()[0]
                _log(
                    f"  {t}: prod table MISSING — would require CREATE TABLE "
                    f"+ INSERT of {n_stg:,} rows (not supported by the current "
                    f"diff-apply path; out of dry-run scope)"
                )
                summary["tables"][t] = {"note": "prod missing; create-path unsupported"}
                continue
            stats = _count_diff(con, t)
            summary["tables"][t] = stats
            if _kind_for(t) == "rebuild":
                _log(
                    f"  {t} [rebuild]: would_replace_all  "
                    f"prod={stats['deleted']} → staging={stats['added_only']}"
                )
            else:
                _log(
                    f"  {t}: would_delete={stats['deleted']}  "
                    f"would_modify={stats['modified']}  "
                    f"would_add={stats['added_only'] - stats['modified']}  "
                    f"(PK-only delta {stats['added_only']})"
                )
    finally:
        con.execute("DETACH stg")
        con.close()

    # Validator pass-through — warn even in dry-run so reviewers see the gap.
    for t in tables:
        if t in summary["tables"] and VALIDATOR_MAP.get(t) is None:
            _log(
                f"  [warn] No validator registered for table {t}. "
                f"Actual promotion would proceed without validation for this table."
            )
    return summary


def promote(tables: list[str], snapshot_id: str) -> dict:
    import duckdb

    if not os.path.exists(db.PROD_DB):
        raise RuntimeError(f"Production DB not found: {db.PROD_DB}")
    if not os.path.exists(db.STAGING_DB):
        raise RuntimeError(f"Staging DB not found: {db.STAGING_DB}")

    con = duckdb.connect(db.PROD_DB)
    con.execute(f"ATTACH '{db.STAGING_DB}' AS stg (READ_ONLY)")

    # INF9e: ensure entity_overrides_persistent exists in prod before the
    # skip-check. This is the one-time DDL migration — idempotent via
    # CREATE TABLE IF NOT EXISTS. Uses prod's degraded schema pattern
    # (no PRIMARY KEY / DEFAULT constraints — see ENTITY_ARCHITECTURE.md).
    con.execute("""
        CREATE TABLE IF NOT EXISTS entity_overrides_persistent (
            override_id    BIGINT,
            entity_cik     VARCHAR,
            action         VARCHAR NOT NULL,
            field          VARCHAR,
            old_value      VARCHAR,
            new_value      VARCHAR NOT NULL,
            reason         VARCHAR,
            analyst        VARCHAR,
            still_valid    BOOLEAN NOT NULL DEFAULT TRUE,
            applied_at     TIMESTAMP DEFAULT NOW(),
            created_at     TIMESTAMP DEFAULT NOW()
        )
    """)

    # Skip any tables that don't exist in prod. Now that
    # entity_overrides_persistent is created above, it won't be skipped.
    existing_in_prod = {
        r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name = current_database()"
        ).fetchall()
    }
    skipped = [t for t in tables if t not in existing_in_prod]
    if skipped:
        for t in skipped:
            _log(f"  SKIP {t}: not present in production (cannot promote)")
        tables = [t for t in tables if t in existing_in_prod]

    summary = {"snapshot_id": snapshot_id, "tables": {}}
    try:
        # Step 2 — snapshot
        _take_snapshot(con, snapshot_id, tables)

        # Step 3a — heal any NULL override_id in entity_overrides_persistent.
        # Must run in BOTH prod and staging before diff: staging via the
        # ATTACH'd connection, prod via the same `con`. Deterministic
        # ordering ensures identical content gets identical IDs.
        if "entity_overrides_persistent" in tables:
            _heal_override_ids(con, "prod")
            # staging is ATTACH'd READ_ONLY — open a write handle to heal it.
            # DuckDB forbids two write handles to one DB in one process; we
            # must DETACH staging from the prod connection before opening a
            # separate write handle. Re-ATTACH afterwards so the diff has
            # access to the healed staging table.
            con.execute("DETACH stg")
            stg_rw = duckdb.connect(db.STAGING_DB)
            try:
                _heal_override_ids(stg_rw, "staging")
            finally:
                stg_rw.close()
            con.execute(f"ATTACH '{db.STAGING_DB}' AS stg (READ_ONLY)")

        # Step 3 — apply changes inside one transaction so the
        # whole promotion is atomic from prod's point of view
        _log("  applying staging → production ...")
        con.execute("BEGIN TRANSACTION")
        try:
            for t in tables:
                stats = _apply_table(con, t)
                summary["tables"][t] = stats
                _log(
                    f"    {t}: deleted={stats['deleted']}  "
                    f"modified={stats['modified']}  "
                    f"added={stats['added_only']}"
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        # Step 4 — sequence reset
        _reset_sequences(con)

    finally:
        con.execute("DETACH stg")
        con.close()

    # Step 5 — validate per VALIDATOR_MAP. Tables with None get an
    # explicit warn (load-bearing: signals a known gap, not a silent skip).
    summary.update(_run_validators(tables, snapshot_id))

    # If the validator path auto-rolled back, reflect it in the summary
    # so main() can exit non-zero. Otherwise promotion stays in place.
    return summary


def _run_validators(tables: list[str], snapshot_id: str) -> dict:
    """Run every validator referenced by VALIDATOR_MAP for the tables
    being promoted, deduplicated. Tables mapped to None get an explicit
    warn. Returns a dict merged into the outer summary.

    Current validator kinds:
      'validate_entities' → subprocess call to validate_entities.py
      'schema_pk'         → DDL-level PRIMARY KEY constraint; logged as
                            registered, no subprocess (engine enforces).
      None                → no-op with warn
    """
    import duckdb

    out: dict = {"validators_run": [], "validators_skipped": []}

    # Warn once per None-mapped table.
    for t in tables:
        if VALIDATOR_MAP.get(t) is None:
            _log(
                f"  [warn] No validator registered for table {t}. "
                f"Promotion proceeding without validation for this table."
            )
            out["validators_skipped"].append(t)

    # Log schema-PK registrations. DuckDB rejects PK violations at
    # insert time, so the constraint itself is the validator — no
    # subprocess needed. Recorded so the registration is visible in
    # promote logs alongside the entity-validator output.
    for t in tables:
        if VALIDATOR_MAP.get(t) == "schema_pk":
            _log(
                f"  schema_pk validator registered for {t} "
                "(DDL PRIMARY KEY enforced by engine)"
            )
            out["validators_run"].append(f"schema_pk:{t}")

    kinds = {VALIDATOR_MAP.get(t) for t in tables if VALIDATOR_MAP.get(t)}

    if "validate_entities" in kinds:
        # validate_entities.py exit codes:
        #   0 = all gates PASS
        #   1 = at least one non-structural gate FAILed (do NOT auto-rollback;
        #       these gates can have transient or expected failures, and a
        #       human should decide whether they block this promotion)
        #   2 = at least one STRUCTURAL gate FAILed (auto-rollback — the DB
        #       is in a logically broken state)
        _log("  running validate_entities.py against production ...")
        result = subprocess.run(  # nosec B603
            [sys.executable, "-u", "scripts/validate_entities.py", "--prod"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        out["validate_returncode"] = result.returncode
        out["validate_stdout_tail"] = "\n".join(result.stdout.splitlines()[-20:])
        out["validators_run"].append("validate_entities")

        if result.returncode == 0:
            _log("  validation PASSED (all gates green)")
        elif result.returncode == 1:
            _log("  validation: non-structural FAILs present (NOT auto-rolling back)")
            _log("    review logs/entity_validation_report.json before next session")
            for line in result.stdout.splitlines()[-6:]:
                if line.strip():
                    _log(f"    {line}")
        elif result.returncode == 2:
            _log("  validation: STRUCTURAL FAILURE (rc=2) — auto-restoring snapshot")
            for line in result.stdout.splitlines()[-6:]:
                if line.strip():
                    _log(f"    {line}")
            con = duckdb.connect(db.PROD_DB)
            try:
                con.execute("BEGIN TRANSACTION")
                try:
                    _restore_snapshot(con, snapshot_id, tables)
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
            finally:
                con.close()
            _log("  rollback complete; production restored to pre-promotion state")
            out["restored"] = True
        else:
            _log(
                f"  validation: unexpected exit code {result.returncode} "
                "— leaving promotion in place"
            )

    return out


def rollback(snapshot_id: str, tables: list[str]) -> None:
    import duckdb

    con = duckdb.connect(db.PROD_DB)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            _restore_snapshot(con, snapshot_id, tables)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--approved", action="store_true",
                   help="REQUIRED for apply path. Confirms human review of the diff.")
    p.add_argument("--tables", default=None,
                   help=(
                       "comma-separated subset of promotable tables "
                       "(default: all entity tables). See db.PROMOTABLE_TABLES."
                   ))
    p.add_argument("--dry-run", action="store_true",
                   help="Preview diff counts without snapshotting or applying. "
                        "Read-only; --approved not required.")
    p.add_argument("--rollback", metavar="SNAPSHOT_ID",
                   help="restore production from the named snapshot")
    p.add_argument("--list-snapshots", action="store_true",
                   help="list snapshot tables in production DB")
    args = p.parse_args()

    if args.list_snapshots:
        list_snapshots()
        return

    if args.tables:
        requested = [t.strip() for t in args.tables.split(",") if t.strip()]
        invalid = [t for t in requested if t not in db.PROMOTABLE_TABLES]
        if invalid:
            print(
                f"ERROR: unknown promotable tables: {invalid}. "
                f"Known: {list(db.PROMOTABLE_TABLES)}",
                file=sys.stderr,
            )
            sys.exit(2)
        tables = requested
    else:
        # Default preserves prior behaviour: promote every entity table.
        # Canonical tables must be opted in via --tables.
        tables = list(db.ENTITY_TABLES)

    if args.rollback:
        if not args.approved:
            print("ERROR: --rollback also requires --approved.", file=sys.stderr)
            sys.exit(2)
        _log(f"=== ROLLBACK START — snapshot={args.rollback} ===")
        rollback(args.rollback, tables)
        _log("=== ROLLBACK DONE ===")
        return

    if args.dry_run:
        _log(f"=== DRY-RUN — tables={tables} ===")
        summary = dry_run(tables)
        _log("=== DRY-RUN DONE — no writes performed ===")
        return

    if not args.approved:
        print(
            "ERROR: --approved is required. The staging diff MUST be reviewed "
            "by a human before promotion. Use --dry-run to preview.",
            file=sys.stderr,
        )
        sys.exit(2)

    snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log(f"=== PROMOTE START — snapshot_id={snapshot_id} tables={len(tables)} ===")
    summary = promote(tables, snapshot_id)

    if summary.get("restored"):
        _log("=== PROMOTE FAILED — production restored from snapshot ===")
        sys.exit(1)

    total_changes = sum(
        s["deleted"] + s["modified"] + s["added_only"]
        for s in summary["tables"].values()
    )
    _log(f"=== PROMOTE DONE — snapshot_id={snapshot_id} total_changes={total_changes} ===")


if __name__ == "__main__":
    main()
