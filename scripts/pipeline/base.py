"""SourcePipeline ABC — concrete base class for the v3.2 admin refresh framework.

Canonical implementation per docs/admin_refresh_system_design.md §4. Owns:
  * the 8-step staging flow (§2a): fetch → parse → validate → diff →
    snapshot → promote → verify → cleanup
  * the async approval gate (§2b): ``run()`` halts at ``pending_approval``
    and returns a ``run_id``; ``approve_and_promote(run_id)`` resumes from
    step 5; ``reject(run_id, reason)`` is the negative gate
  * three amendment strategies — ``append_is_latest``, ``scd_type2``,
    ``direct_write`` — dispatched from ``promote()`` by
    ``self.amendment_strategy``
  * rollback via ``ingestion_impacts`` reversal; snapshot retention
    (14 days, pruned on demand); entity gate delegation; freshness stamps

Concrete pipelines subclass ``SourcePipeline``, set four class attributes
(``name``, ``target_table``, ``amendment_strategy``, ``amendment_key``),
and override three abstract methods (``fetch``, ``parse``,
``target_table_spec``). The orchestrator handles every other step.

The existing ``scripts/pipeline/protocol.py`` structural Protocols remain
in place as a compatibility shim until the six legacy pipelines migrate
to this ABC. New pipelines should subclass ``SourcePipeline`` here.

Schema adapter note — migration 001's ``ingestion_impacts`` records
``(unit_type, unit_key_json)``, pre-dating the §2b per-row action
vocabulary (``insert``, ``flip_is_latest``, ``scd_supersede``,
``upsert``). ``record_impact()`` maps action → ``unit_type`` and the
rowkey dict → JSON-encoded ``unit_key_json``. A future migration can
promote these to dedicated columns without changing caller code.
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import duckdb

from .manifest import (
    get_or_create_manifest_row,
    update_manifest_status,
    write_impact,
)


# ---------------------------------------------------------------------------
# Dataclasses (base-class variants)
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    """Outcome of ``SourcePipeline.fetch()``. Scope-level.

    Divergence from ``protocol.FetchResult``: that one is per-object
    (one row per DownloadTarget); this one is per-run (one invocation
    of ``fetch()`` covering the entire scope). Intentional — the ABC
    orchestrator drives the staging flow at run granularity.
    """
    run_id: str
    rows_staged: int
    raw_tables: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class ParseResult:
    """Outcome of ``SourcePipeline.parse()``. Matches ``FetchResult`` shape."""
    run_id: str
    rows_parsed: int
    target_staging_table: str
    qc_failures: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class PromoteResult:
    run_id: str
    rows_inserted: int = 0
    rows_flipped: int = 0
    rows_upserted: int = 0
    duration_seconds: float = 0.0


@dataclass
class ValidationResult:
    blocks: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    pending_entities: list[Any] = field(default_factory=list)

    @property
    def promote_ready(self) -> bool:
        return not self.blocks


@dataclass
class DiffSummary:
    inserts: int = 0
    updates: int = 0
    deletes: int = 0
    anomalies: list[str] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Run state machine
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"fetching", "failed"},
    "fetching": {"parsing", "failed"},
    "parsing": {"validating", "failed"},
    "validating": {"pending_approval", "failed"},
    "pending_approval": {"approved", "rejected", "expired", "failed"},
    "approved": {"promoting", "failed"},
    "promoting": {"verifying", "failed"},
    "verifying": {"complete", "failed"},
    "complete": {"rolled_back"},
    "rejected": set(),
    "expired": set(),
    "failed": set(),
    "rolled_back": set(),
}

_RESUMABLE_STATES = {
    "pending_approval", "approved", "promoting", "verifying", "complete",
}


class InvalidStateTransitionError(ValueError):
    """Raised when a run is asked to move to a status not reachable from
    its current status per ``_VALID_TRANSITIONS``."""


def _assert_valid_transition(current: str, target: str) -> None:
    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"cannot transition {current!r} -> {target!r}; "
            f"allowed from {current!r}: "
            f"{sorted(allowed) if allowed else '(terminal)'}"
        )


# ---------------------------------------------------------------------------
# SourcePipeline ABC
# ---------------------------------------------------------------------------

class SourcePipeline(ABC):
    """Canonical base class for framework-era ingest pipelines."""

    # Class attributes — subclasses set these.
    name: str = ""
    target_table: str = ""
    amendment_strategy: str = ""
    amendment_key: tuple[str, ...] = ()

    _VALID_STRATEGIES = ("append_is_latest", "scd_type2", "direct_write")

    # ---- construction --------------------------------------------------

    def __init__(
        self,
        *,
        prod_db_path: Optional[str] = None,
        staging_db_path: Optional[str] = None,
        backup_dir: Optional[str] = None,
    ) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__}.name must be set")
        if not self.target_table:
            raise ValueError(
                f"{type(self).__name__}.target_table must be set"
            )
        if self.amendment_strategy not in self._VALID_STRATEGIES:
            raise ValueError(
                f"{type(self).__name__}.amendment_strategy must be one of "
                f"{self._VALID_STRATEGIES}; got {self.amendment_strategy!r}"
            )

        if prod_db_path is not None:
            self._prod_db_path = prod_db_path
        else:
            from db import PROD_DB  # type: ignore[import-not-found]
            self._prod_db_path = PROD_DB

        if staging_db_path is not None:
            self._staging_db_path = staging_db_path
        else:
            from db import STAGING_DB  # type: ignore[import-not-found]
            self._staging_db_path = STAGING_DB

        if backup_dir is not None:
            self._backup_dir = Path(backup_dir)
        else:
            self._backup_dir = (
                Path(self._prod_db_path).parent / "backups"
            )
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger(f"pipeline.{self.name}")

    # ---- abstract contract --------------------------------------------

    @abstractmethod
    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        """Populate raw staging tables from the source.

        Writes **only** to ``staging_con``. Must not touch prod. Scope
        example: ``{"quarter": "2026Q1"}`` for 13F,
        ``{"month": "2026-03"}`` for N-PORT.
        """

    @abstractmethod
    def parse(self, staging_con: Any) -> ParseResult:
        """Transform raw staging tables into a typed staging table matching
        ``self.target_table``. Writes **only** to ``staging_con``."""

    @abstractmethod
    def target_table_spec(self) -> dict:
        """Return ``{"columns": [...], "pk": [...], "indexes": [...]}`` for
        the target fact table. Reserved for future promote-SQL generation."""

    # ---- run orchestrator (steps 1-4) ---------------------------------

    def run(self, scope: dict) -> str:
        """Steps 1-4 of the staging flow. Halts at ``pending_approval``.

        Returns the run_id; call ``approve_and_promote(run_id)`` or
        ``reject(run_id, reason)`` to continue. Idempotent: if a prior
        run for the same scope is in a resumable state
        (``pending_approval`` through ``complete``), the existing
        run_id is returned and no new fetch is executed.
        """
        scope_slug = self._scope_slug(scope)
        object_key = f"{self.name}:{scope_slug}"

        existing = self._existing_manifest(object_key)
        if existing is not None:
            _m_id, prior_run_id, status = existing
            if status in _RESUMABLE_STATES:
                self._logger.info(
                    "run(): resuming existing run_id=%s status=%s",
                    prior_run_id, status,
                )
                return prior_run_id
            # Otherwise (failed / rejected / expired): start a fresh run
            # with a new object_key suffix to avoid UNIQUE collision.
            object_key = f"{object_key}#{int(time.time())}"

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_id = f"{self.name}_{scope_slug}_{timestamp}"
        self._logger.info(
            "run(): starting run_id=%s scope=%s", run_id, scope,
        )

        prod_con = duckdb.connect(self._prod_db_path)
        try:
            manifest_id = get_or_create_manifest_row(
                prod_con,
                source_type=self.name,
                object_type="SCOPE",
                source_url=f"scope://{scope_slug}",
                accession_number=None,
                run_id=run_id,
                object_key=object_key,
                fetch_status="fetching",
            )
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

        staging_con = duckdb.connect(self._staging_db_path)
        try:
            # Step 1 — fetch
            self.fetch(scope, staging_con)
            staging_con.execute("CHECKPOINT")
            self._transition_open(manifest_id, "fetching", "parsing")

            # Step 2 — parse
            self.parse(staging_con)
            staging_con.execute("CHECKPOINT")
            self._transition_open(manifest_id, "parsing", "validating")

            # Step 3 — validate
            prod_ro = duckdb.connect(self._prod_db_path, read_only=True)
            try:
                vr = self.validate(staging_con, prod_ro)
            finally:
                prod_ro.close()
            if vr.blocks:
                self._transition_open(
                    manifest_id, "validating", "failed",
                    error_message=f"validation BLOCKs: {vr.blocks}",
                )
                raise RuntimeError(f"validation BLOCKs: {vr.blocks}")

            # Step 4 — diff + pending_approval
            prod_ro = duckdb.connect(self._prod_db_path, read_only=True)
            try:
                diff = self.compute_diff(staging_con, prod_ro, scope)
            finally:
                prod_ro.close()
            self._transition_open(
                manifest_id, "validating", "pending_approval",
            )
            self._logger.info(
                "run(): pending_approval run_id=%s inserts=%d",
                run_id, diff.inserts,
            )
            return run_id
        except Exception as e:
            try:
                self._transition_open_best_effort(
                    manifest_id, "failed",
                    error_message=str(e)[:500],
                )
            except Exception:
                pass
            raise
        finally:
            staging_con.close()

    # ---- approve / reject ---------------------------------------------

    def approve_and_promote(self, run_id: str) -> PromoteResult:
        """Resume from step 5. Snapshot → promote → verify → cleanup."""
        manifest_id, status = self._load_manifest(run_id)
        _assert_valid_transition(status, "approved")

        start = time.monotonic()

        prod_con = duckdb.connect(self._prod_db_path)
        try:
            update_manifest_status(prod_con, manifest_id, "approved")
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

        # Step 5 — snapshot
        snapshot_path = self.snapshot_before_promote(run_id)
        self._logger.info("snapshot created: %s", snapshot_path)

        # Step 6 → 7 → 8 — promote, verify, cleanup. Single prod
        # connection for the write sequence so a crash leaves the
        # manifest status pointing at the last completed step.
        prod_con = duckdb.connect(self._prod_db_path)
        try:
            self._transition(prod_con, manifest_id, "approved", "promoting")
            result = self.promote(run_id, prod_con)
            self._transition(
                prod_con, manifest_id, "promoting", "verifying",
            )
            self._transition(
                prod_con, manifest_id, "verifying", "complete",
            )
            self.stamp_freshness(prod_con)
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

        self._cleanup_staging(run_id)
        result.duration_seconds = time.monotonic() - start
        return result

    def reject(self, run_id: str, reason: str) -> None:
        manifest_id, status = self._load_manifest(run_id)
        _assert_valid_transition(status, "rejected")
        prod_con = duckdb.connect(self._prod_db_path)
        try:
            update_manifest_status(
                prod_con, manifest_id, "rejected",
                error_message=(reason or "")[:500],
            )
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

    # ---- validate / diff (subclass-overridable defaults) ---------------

    # pylint: disable=unused-argument  # ABC default stub; subclasses consume
    def validate(self, staging_con: Any, prod_con: Any) -> ValidationResult:
        """QC gates on staged data. Default implementation is a no-op
        returning PASS; subclasses override to add source-specific checks
        and to call ``entity_gate_check()``."""
        return ValidationResult()

    # pylint: disable=unused-argument  # ABC default stub; subclasses consume
    def compute_diff(
        self, staging_con: Any, prod_con: Any, scope: dict,
    ) -> DiffSummary:
        """Default diff — count staged rows. Anomaly detection is a
        placeholder; p2-06 wires it to ``cadence.py`` expected_delta."""
        try:
            staged_count = staging_con.execute(
                f"SELECT COUNT(*) FROM {self.target_table}"  # nosec B608
            ).fetchone()[0]
        except Exception:
            staged_count = 0
        return DiffSummary(inserts=int(staged_count))

    # ---- promote dispatch ---------------------------------------------

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        if self.amendment_strategy == "append_is_latest":
            return self._promote_append_is_latest(run_id, prod_con)
        if self.amendment_strategy == "scd_type2":
            return self._promote_scd_type2(run_id, prod_con)
        if self.amendment_strategy == "direct_write":
            return self._promote_direct_write(run_id, prod_con)
        raise ValueError(
            f"unknown amendment_strategy: {self.amendment_strategy!r}"
        )

    def _read_staged_rows(self):
        """Pull typed staging rows for ``self.target_table`` into a pandas
        DataFrame. Returns an empty DataFrame if the staging table is
        missing or empty."""
        con = duckdb.connect(self._staging_db_path, read_only=True)
        try:
            try:
                return con.execute(
                    f"SELECT * FROM {self.target_table}"  # nosec B608
                ).fetchdf()
            except Exception:
                import pandas as pd
                return pd.DataFrame()
        finally:
            con.close()

    def _promote_append_is_latest(
        self, run_id: str, prod_con: Any,
    ) -> PromoteResult:
        rows = self._read_staged_rows()
        if rows.empty:
            return PromoteResult(run_id=run_id)

        manifest_id = self._manifest_id_for_run(prod_con, run_id)
        key_cols = list(self.amendment_key)
        rows_flipped = 0

        if "is_latest" in rows.columns:
            rows = rows.copy()
            rows["is_latest"] = True

        col_list = ", ".join(rows.columns)

        prod_con.execute("BEGIN TRANSACTION")
        try:
            if key_cols:
                unique_keys = (
                    rows[key_cols].drop_duplicates().to_dict("records")
                )
                for key in unique_keys:
                    where_sql = " AND ".join(f"{c} = ?" for c in key_cols)
                    params = [key[c] for c in key_cols]
                    flipped_rows = prod_con.execute(
                        f"UPDATE {self.target_table} "  # nosec B608
                        f"SET is_latest = FALSE "
                        f"WHERE {where_sql} AND is_latest = TRUE "
                        f"RETURNING 1",
                        params,
                    ).fetchall()
                    rows_flipped += len(flipped_rows)
                    self.record_impact(
                        prod_con, manifest_id=manifest_id, run_id=run_id,
                        action="flip_is_latest", rowkey=key,
                    )

            prod_con.register("staged_rows", rows)
            try:
                prod_con.execute(
                    f"INSERT INTO {self.target_table} "  # nosec B608
                    f"({col_list}) SELECT {col_list} FROM staged_rows"
                )
            finally:
                prod_con.unregister("staged_rows")
            rows_inserted = len(rows)

            if key_cols:
                for key in rows[key_cols].drop_duplicates().to_dict("records"):
                    self.record_impact(
                        prod_con, manifest_id=manifest_id, run_id=run_id,
                        action="insert", rowkey=key,
                    )

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        return PromoteResult(
            run_id=run_id,
            rows_inserted=rows_inserted,
            rows_flipped=rows_flipped,
        )

    def _promote_scd_type2(
        self, run_id: str, prod_con: Any,
    ) -> PromoteResult:
        rows = self._read_staged_rows()
        if rows.empty:
            return PromoteResult(run_id=run_id)

        manifest_id = self._manifest_id_for_run(prod_con, run_id)
        key_cols = list(self.amendment_key)
        rows_flipped = 0
        col_list = ", ".join(rows.columns)

        prod_con.execute("BEGIN TRANSACTION")
        try:
            if key_cols:
                for key in rows[key_cols].drop_duplicates().to_dict("records"):
                    where_sql = " AND ".join(f"{c} = ?" for c in key_cols)
                    params = [key[c] for c in key_cols]
                    flipped_rows = prod_con.execute(
                        f"UPDATE {self.target_table} "  # nosec B608
                        f"SET valid_to = CURRENT_TIMESTAMP "
                        f"WHERE {where_sql} AND valid_to = DATE '9999-12-31' "
                        f"RETURNING 1",
                        params,
                    ).fetchall()
                    rows_flipped += len(flipped_rows)
                    self.record_impact(
                        prod_con, manifest_id=manifest_id, run_id=run_id,
                        action="scd_supersede", rowkey=key,
                    )

            prod_con.register("staged_rows", rows)
            try:
                prod_con.execute(
                    f"INSERT INTO {self.target_table} "  # nosec B608
                    f"({col_list}) SELECT {col_list} FROM staged_rows"
                )
            finally:
                prod_con.unregister("staged_rows")
            rows_inserted = len(rows)

            if key_cols:
                for key in rows[key_cols].drop_duplicates().to_dict("records"):
                    self.record_impact(
                        prod_con, manifest_id=manifest_id, run_id=run_id,
                        action="insert", rowkey=key,
                    )

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        return PromoteResult(
            run_id=run_id,
            rows_inserted=rows_inserted,
            rows_flipped=rows_flipped,
        )

    def _promote_direct_write(
        self, run_id: str, prod_con: Any,
    ) -> PromoteResult:
        rows = self._read_staged_rows()
        if rows.empty:
            return PromoteResult(run_id=run_id)

        manifest_id = self._manifest_id_for_run(prod_con, run_id)
        key_cols = list(self.amendment_key)
        col_list = ", ".join(rows.columns)

        prod_con.execute("BEGIN TRANSACTION")
        try:
            if key_cols:
                where_sql = " AND ".join(f"{c} = ?" for c in key_cols)
                for row in rows[key_cols].to_dict("records"):
                    params = [row[c] for c in key_cols]
                    prod_con.execute(
                        f"DELETE FROM {self.target_table} "  # nosec B608
                        f"WHERE {where_sql}",
                        params,
                    )

            prod_con.register("staged_rows", rows)
            try:
                prod_con.execute(
                    f"INSERT INTO {self.target_table} "  # nosec B608
                    f"({col_list}) SELECT {col_list} FROM staged_rows"
                )
            finally:
                prod_con.unregister("staged_rows")
            rows_upserted = len(rows)

            if key_cols:
                for row in rows[key_cols].drop_duplicates().to_dict("records"):
                    self.record_impact(
                        prod_con, manifest_id=manifest_id, run_id=run_id,
                        action="upsert", rowkey=row,
                    )

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        return PromoteResult(
            run_id=run_id,
            rows_upserted=rows_upserted,
        )

    # ---- rollback ------------------------------------------------------

    def rollback(self, run_id: str) -> None:
        """Reverse every impact for ``run_id``.

        Processes impacts in reverse insertion order (LIFO) so inserts
        undo cleanly before flips / SCD closures are reversed. A
        ``direct_write`` run cannot be fully rolled back from impacts
        alone — the snapshot is authoritative and the user must restore
        from it for that strategy.
        """
        manifest_id, status = self._load_manifest(run_id)
        _assert_valid_transition(status, "rolled_back")

        prod_con = duckdb.connect(self._prod_db_path)
        try:
            impacts = prod_con.execute(
                """
                SELECT unit_type, unit_key_json
                  FROM ingestion_impacts
                 WHERE manifest_id = ?
                 ORDER BY impact_id DESC
                """,
                [manifest_id],
            ).fetchall()

            for action, rowkey_json in impacts:
                rowkey = json.loads(rowkey_json)
                if action == "insert":
                    self._rollback_insert(prod_con, rowkey)
                elif action == "flip_is_latest":
                    self._rollback_flip(prod_con, rowkey)
                elif action == "scd_supersede":
                    self._rollback_scd(prod_con, rowkey)
                elif action == "upsert":
                    self._logger.warning(
                        "rollback: upsert action for run_id=%s requires "
                        "snapshot restore; impacts log is insufficient",
                        run_id,
                    )

            update_manifest_status(prod_con, manifest_id, "rolled_back")
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

    def _rollback_insert(self, prod_con: Any, rowkey: dict) -> None:
        if not self.amendment_key:
            return
        where_sql = " AND ".join(f"{c} = ?" for c in self.amendment_key)
        params = [rowkey[c] for c in self.amendment_key]
        if self.amendment_strategy == "append_is_latest":
            prod_con.execute(
                f"DELETE FROM {self.target_table} "  # nosec B608
                f"WHERE {where_sql} AND is_latest = TRUE",
                params,
            )
        else:
            prod_con.execute(
                f"DELETE FROM {self.target_table} "  # nosec B608
                f"WHERE {where_sql}",
                params,
            )

    def _rollback_flip(self, prod_con: Any, rowkey: dict) -> None:
        if not self.amendment_key:
            return
        where_sql = " AND ".join(f"{c} = ?" for c in self.amendment_key)
        params = [rowkey[c] for c in self.amendment_key]
        prod_con.execute(
            f"UPDATE {self.target_table} SET is_latest = TRUE "  # nosec B608
            f"WHERE {where_sql} AND is_latest = FALSE",
            params,
        )

    def _rollback_scd(self, prod_con: Any, rowkey: dict) -> None:
        if not self.amendment_key:
            return
        where_sql = " AND ".join(f"{c} = ?" for c in self.amendment_key)
        params = [rowkey[c] for c in self.amendment_key]
        prod_con.execute(
            f"UPDATE {self.target_table} "  # nosec B608
            f"SET valid_to = DATE '9999-12-31' "
            f"WHERE {where_sql} AND valid_to <> DATE '9999-12-31'",
            params,
        )

    # ---- impact / entity gate -----------------------------------------

    # pylint: disable=unused-argument  # run_id kept in API for logging and
    # for a future dedicated column; recoverable today via the manifest_id join
    def record_impact(
        self,
        prod_con: Any,
        *,
        manifest_id: int,
        run_id: str,
        action: str,
        rowkey: dict,
        prior_accession: Optional[str] = None,
    ) -> None:
        """Write one ingestion_impacts row using the migration-001 schema.

        ``action`` → ``unit_type``, ``rowkey`` (+ optional
        ``prior_accession``) → ``unit_key_json``. ``run_id`` is
        recoverable via the ``manifest_id`` join.
        """
        if prior_accession is not None:
            payload = dict(rowkey)
            payload["prior_accession"] = prior_accession
        else:
            payload = dict(rowkey)
        unit_key_json = json.dumps(payload, sort_keys=True, default=str)
        write_impact(
            prod_con,
            manifest_id=manifest_id,
            target_table=self.target_table,
            unit_type=action,
            unit_key_json=unit_key_json,
        )

    # pylint: disable=unused-argument  # ABC default stub; subclasses consume
    def entity_gate_check(self, staged_rows: Any, staging_con: Any) -> list:
        """Default: no entity gating. Subclasses with identifier columns
        override to call ``scripts.pipeline.shared.entity_gate_check``
        with a prod connection and the staged identifier list, and
        forward any pending entities into the orchestrator's return
        channel."""
        return []

    # ---- snapshots -----------------------------------------------------

    def snapshot_before_promote(self, run_id: str) -> str:
        snapshot_path = self._backup_dir / f"{self.name}_{run_id}.duckdb"
        if snapshot_path.exists():
            snapshot_path.unlink()

        snap = duckdb.connect(str(snapshot_path))
        try:
            snap.execute(
                f"ATTACH '{self._prod_db_path}' AS prod_ro (READ_ONLY)"
            )
            snap.execute(
                f"CREATE TABLE {self.target_table} AS "  # nosec B608
                f"SELECT * FROM prod_ro.{self.target_table}"
            )
            snap.execute("DETACH prod_ro")
            snap.execute("CHECKPOINT")
        finally:
            snap.close()
        return str(snapshot_path)

    def prune_old_snapshots(self, retention_days: int = 14) -> int:
        if not self._backup_dir.exists():
            return 0
        cutoff = time.time() - retention_days * 86400
        pruned = 0
        for p in self._backup_dir.glob(f"{self.name}_*.duckdb"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    pruned += 1
            except FileNotFoundError:
                continue
        return pruned

    # ---- freshness -----------------------------------------------------

    def stamp_freshness(self, con: Any) -> None:
        try:
            from db import record_freshness  # type: ignore[import-not-found]
        except Exception:
            return
        try:
            record_freshness(con, self.target_table)
        except Exception as e:
            self._logger.warning("stamp_freshness: %s", e)

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _scope_slug(scope: dict) -> str:
        if not scope:
            return "empty"
        parts = [f"{k}={scope[k]}" for k in sorted(scope.keys())]
        return "_".join(parts).replace("/", "-").replace(" ", "")

    def _existing_manifest(
        self, object_key: str,
    ) -> Optional[tuple[int, str, str]]:
        con = duckdb.connect(self._prod_db_path, read_only=True)
        try:
            row = con.execute(
                "SELECT manifest_id, run_id, fetch_status "
                "FROM ingestion_manifest WHERE object_key = ? "
                "ORDER BY manifest_id DESC LIMIT 1",
                [object_key],
            ).fetchone()
        finally:
            con.close()
        if not row:
            return None
        return int(row[0]), row[1], row[2]

    def _transition(
        self,
        prod_con: Any,
        manifest_id: int,
        current: str,
        target: str,
        **kwargs: Any,
    ) -> None:
        _assert_valid_transition(current, target)
        update_manifest_status(prod_con, manifest_id, target, **kwargs)
        prod_con.execute("CHECKPOINT")

    def _transition_open(
        self,
        manifest_id: int,
        current: str,
        target: str,
        **kwargs: Any,
    ) -> None:
        """Transition using a short-lived prod connection. Used inside
        ``run()`` where staging_con is the long-lived handle."""
        _assert_valid_transition(current, target)
        prod_con = duckdb.connect(self._prod_db_path)
        try:
            update_manifest_status(prod_con, manifest_id, target, **kwargs)
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

    def _transition_open_best_effort(
        self, manifest_id: int, target: str, **kwargs: Any,
    ) -> None:
        """Force status without validating transition. Used only on the
        failure path so a crashed run is visible as ``failed``."""
        prod_con = duckdb.connect(self._prod_db_path)
        try:
            update_manifest_status(prod_con, manifest_id, target, **kwargs)
            prod_con.execute("CHECKPOINT")
        finally:
            prod_con.close()

    def _load_manifest(self, run_id: str) -> tuple[int, str]:
        con = duckdb.connect(self._prod_db_path, read_only=True)
        try:
            row = con.execute(
                "SELECT manifest_id, fetch_status FROM ingestion_manifest "
                "WHERE run_id = ? AND source_type = ? "
                "ORDER BY manifest_id DESC LIMIT 1",
                [run_id, self.name],
            ).fetchone()
        finally:
            con.close()
        if not row:
            raise ValueError(f"no manifest row for run_id={run_id!r}")
        return int(row[0]), row[1]

    @staticmethod
    def _manifest_id_for_run(prod_con: Any, run_id: str) -> int:
        row = prod_con.execute(
            "SELECT manifest_id FROM ingestion_manifest "
            "WHERE run_id = ? ORDER BY manifest_id DESC LIMIT 1",
            [run_id],
        ).fetchone()
        if not row:
            raise ValueError(f"no manifest row for run_id={run_id!r}")
        return int(row[0])

    # pylint: disable=unused-argument  # run_id scoped for future per-run cleanup
    def _cleanup_staging(self, run_id: str) -> None:
        try:
            staging_con = duckdb.connect(self._staging_db_path)
            try:
                staging_con.execute(
                    f"DROP TABLE IF EXISTS {self.target_table}"  # nosec B608
                )
                staging_con.execute("CHECKPOINT")
            finally:
                staging_con.close()
        except Exception as e:
            self._logger.warning("cleanup_staging: %s", e)
