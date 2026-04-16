"""Manifest read/write helpers for the v1.2 pipeline framework.

Every Source/DirectWrite/Derived pipeline goes through this module for
anything involving ingestion_manifest or ingestion_impacts. Direct INSERTs
into either table outside this module are a design violation — the column
sets shift over time and centralization is how we keep callers aligned.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# PK id generation (self-healing replacement for DEFAULT nextval)
# ---------------------------------------------------------------------------

# Allow-list of (table, pk_col) that may be id-computed via MAX+1. Prevents
# accidental misuse against tables where PK isn't a monotonic int.
_ID_TABLES = frozenset({
    ("ingestion_manifest", "manifest_id"),
    ("ingestion_impacts", "impact_id"),
})


def _next_id(con: Any, table: str, pk_col: str) -> int:
    """Return MAX(pk_col)+1 for `table`. Used in place of the DEFAULT
    nextval('*_seq') when the sequence is not trustworthy.

    Root cause this compensates for: DuckDB sequences do not auto-advance
    when rows are INSERTed with explicit PK values. The mirror paths in
    `promote_nport.py` / `promote_13dg.py` (`INSERT INTO <table> SELECT *
    FROM staging_copy`) carry the staging-assigned PK into prod without
    advancing prod's sequence. Over many runs the prod sequence drifts
    arbitrarily far behind MAX and the next DEFAULT-driven INSERT
    collides. Computing the next id inline with MAX+1 is race-safe
    because DuckDB enforces single-writer access per DB file.

    Guarded by `_ID_TABLES` so a typo (e.g. `"ingestion_manifests"`)
    can't accidentally produce invalid SQL against the wrong table.
    """
    if (table, pk_col) not in _ID_TABLES:
        raise ValueError(
            f"_next_id: ({table!r}, {pk_col!r}) not in allow-list; "
            f"extend _ID_TABLES if this is intentional."
        )
    row = con.execute(
        f"SELECT COALESCE(MAX({pk_col}), 0) + 1 FROM {table}"  # nosec B608
    ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_or_create_manifest_row(
    con: Any,
    *,
    source_type: str,
    object_type: str,
    source_url: str,
    accession_number: Optional[str],
    run_id: str,
    object_key: str,
    **kwargs: Any,
) -> int:
    """Return manifest_id, creating the row if it does not exist.

    Keyed on object_key (UNIQUE). If a manifest row already exists for
    this object_key (e.g. a partial earlier fetch), return the existing
    manifest_id so the pipeline can resume it. Caller decides whether
    to re-fetch or skip based on fetch_status.
    """
    existing = con.execute(
        "SELECT manifest_id FROM ingestion_manifest WHERE object_key = ?",
        [object_key],
    ).fetchone()
    if existing:
        return existing[0]

    # Compute manifest_id explicitly as MAX+1 rather than relying on the
    # DEFAULT nextval('manifest_id_seq'). Mirror paths in promote_nport.py
    # and promote_13dg.py (`INSERT INTO ingestion_manifest SELECT * FROM ...`)
    # copy manifest_id verbatim without advancing the sequence, so the
    # sequence drifts arbitrarily far behind MAX(manifest_id) and the
    # DEFAULT path eventually collides. Self-healing MAX+1 avoids the
    # collision and has no race — DuckDB is single-writer per DB file.
    manifest_id = _next_id(con, "ingestion_manifest", "manifest_id")

    base = {
        "manifest_id": manifest_id,
        "source_type": source_type,
        "object_type": object_type,
        "object_key": object_key,
        "source_url": source_url,
        "accession_number": accession_number,
        "run_id": run_id,
        "fetch_status": "pending",
    }
    base.update(kwargs)
    cols = ", ".join(base.keys())
    placeholders = ", ".join(["?"] * len(base))
    con.execute(
        f"INSERT INTO ingestion_manifest ({cols}) VALUES ({placeholders})",
        list(base.values()),
    )
    return manifest_id


def update_manifest_status(
    con: Any,
    manifest_id: int,
    status: str,
    **kwargs: Any,
) -> None:
    """Update fetch_status (or any other column) of an existing manifest row."""
    sets = {"fetch_status": status}
    sets.update(kwargs)
    assignments = ", ".join(f"{k} = ?" for k in sets.keys())
    con.execute(
        f"UPDATE ingestion_manifest SET {assignments} WHERE manifest_id = ?",
        list(sets.values()) + [manifest_id],
    )


def supersede_manifest(
    con: Any,
    old_manifest_id: int,
    new_manifest_id: int,
) -> None:
    """Mark an older manifest row as superseded and flag the new one as amendment.

    Called when a 13F-HR/A or N-PORT amendment arrives replacing a prior
    accession for the same filer/period. The old row stays in place as
    history; ingestion_manifest_current filters it out.
    """
    con.execute(
        "UPDATE ingestion_manifest "
        "SET superseded_by_manifest_id = ? "
        "WHERE manifest_id = ?",
        [new_manifest_id, old_manifest_id],
    )
    con.execute(
        "UPDATE ingestion_manifest "
        "SET is_amendment = TRUE "
        "WHERE manifest_id = ?",
        [new_manifest_id],
    )


# ---------------------------------------------------------------------------
# Impacts
# ---------------------------------------------------------------------------

def write_impact(
    con: Any,
    *,
    manifest_id: int,
    target_table: str,
    unit_type: str,
    unit_key_json: str,
    report_date: Optional[str] = None,
    rows_staged: int = 0,
    load_status: str = "pending",
    **kwargs: Any,
) -> int:
    """Create one ingestion_impacts row. Returns impact_id.

    Computes impact_id as MAX(impact_id)+1 rather than relying on the
    DEFAULT nextval('impact_id_seq'). See get_or_create_manifest_row for
    the sequence-drift rationale.
    """
    impact_id = _next_id(con, "ingestion_impacts", "impact_id")
    base = {
        "impact_id": impact_id,
        "manifest_id": manifest_id,
        "target_table": target_table,
        "unit_type": unit_type,
        "unit_key_json": unit_key_json,
        "report_date": report_date,
        "rows_staged": rows_staged,
        "load_status": load_status,
    }
    base.update(kwargs)
    cols = ", ".join(base.keys())
    placeholders = ", ".join(["?"] * len(base))
    con.execute(
        f"INSERT INTO ingestion_impacts ({cols}) VALUES ({placeholders})",
        list(base.values()),
    )
    return impact_id


def update_impact_status(
    con: Any,
    manifest_id: int,
    unit_type: str,
    unit_key_json: str,
    **kwargs: Any,
) -> None:
    """Update one or more fields of the impact row for this manifest+unit.

    Matching is by (manifest_id, unit_type, unit_key_json) rather than
    impact_id so callers don't have to carry the impact_id around.
    """
    if not kwargs:
        return
    assignments = ", ".join(f"{k} = ?" for k in kwargs.keys())
    con.execute(
        f"UPDATE ingestion_impacts SET {assignments} "
        f"WHERE manifest_id = ? AND unit_type = ? AND unit_key_json = ?",
        list(kwargs.values()) + [manifest_id, unit_type, unit_key_json],
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_already_fetched(
    con: Any,
    source_type: str,
    accessions: list[str],
) -> set[str]:
    """Return the subset of `accessions` already fetched (fetch_status='complete').

    Used by discover() to anti-join against the manifest without pulling
    all historical manifest rows into memory. Empty input → empty output
    with no DB round-trip.
    """
    if not accessions:
        return set()
    placeholders = ",".join(["?"] * len(accessions))
    rows = con.execute(
        f"SELECT accession_number FROM ingestion_manifest "
        f"WHERE source_type = ? AND fetch_status = 'complete' "
        f"  AND accession_number IN ({placeholders})",
        [source_type] + accessions,
    ).fetchall()
    return {r[0] for r in rows if r[0]}


def get_promotable_impacts(
    con: Any,
    source_type: str,
    run_id: str,
) -> pd.DataFrame:
    """Return impacts ready to promote for (source_type, run_id).

    An impact is promotable when:
      * load_status = 'loaded'
      * validation_tier IN ('PASS', 'WARN')
      * promote_status = 'pending'

    Joins to ingestion_manifest to pull source_type + accession_number
    for the per-unit handler.
    """
    return con.execute(
        """
        SELECT
            ii.impact_id, ii.manifest_id, ii.target_table, ii.unit_type,
            ii.unit_key_json, ii.report_date, ii.rows_staged,
            ii.validation_tier,
            m.accession_number, m.source_url, m.report_period, m.filing_date
        FROM ingestion_impacts ii
        JOIN ingestion_manifest m ON m.manifest_id = ii.manifest_id
        WHERE m.source_type = ? AND m.run_id = ?
          AND ii.load_status = 'loaded'
          AND ii.validation_tier IN ('PASS', 'WARN')
          AND ii.promote_status = 'pending'
        ORDER BY ii.impact_id
        """,
        [source_type, run_id],
    ).fetchdf()
