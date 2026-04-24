"""Join-clause helpers for canonical-source resolution in Tier 4 queries.

Pure-Python string assembly. No DB connection at import time, no ORM, no
query builder. Matches the raw-SQL style of scripts/queries.py.

Tier 4 authors should use these helpers instead of reading stamped columns
on ``holdings_v2`` / ``fund_holdings_v2``. Keeps queries.py forward-compatible
with int-09 Step 4 (BLOCK-DENORM-RETIREMENT): when the stamped columns are
retired, callers that went through these helpers keep working.

Design + rationale: ``archive/docs/proposals/tier-4-join-pattern-proposal.md``
(merged via PR #113).

Example
-------
Canonical query5-style usage — resolve ticker via ``securities``, entity
metadata via ``entity_current``, rollup name under a caller-chosen worldview,
and manager classification via ``entity_classification_history``::

    from queries_helpers import (
        ticker_join, entity_join, rollup_join, classification_join,
    )

    sql = f'''
        SELECT ec_rollup.display_name, ech.classification, SUM(h.shares)
        FROM holdings_v2 h
        {ticker_join()}
        {entity_join()}
        {rollup_join(worldview=rollup_type)}
        {classification_join()}
        WHERE s.ticker = ? AND h.is_latest = TRUE
        GROUP BY 1, 2
    '''  # nosec B608 — bandit skip lives on the caller's closing quote

Bandit note
-----------
These helpers return static string fragments built from SQL identifiers the
caller controls (alias names, worldview constants). They do not format user
input. The caller keeps the existing project-wide ``# nosec B608`` convention
on the closing triple-quote of its SQL string.
"""
from __future__ import annotations

from typing import Literal

Worldview = Literal["economic_control_v1", "decision_maker_v1"]
_VALID_WORLDVIEWS: tuple[str, ...] = ("economic_control_v1", "decision_maker_v1")

EntityVia = Literal["entity_id", "cik"]
_VALID_ENTITY_VIA: tuple[str, ...] = ("entity_id", "cik")


def ticker_join(h: str = "h", s: str = "s") -> str:
    """Return a JOIN fragment resolving ticker from the canonical ``securities`` table.

    Parameters
    ----------
    h:
        Alias of the holdings table in the caller's FROM clause (default ``h``).
    s:
        Alias to assign to the joined ``securities`` row (default ``s``).

    The caller filters ``{s}.ticker = ?`` (not ``holdings_v2.ticker``). This
    picks up today's canonical ticker rather than the stamp-at-filing-time
    value, matching how other financial tooling resolves ticker-to-security
    identity (see §6.4 of the proposal).
    """
    return f"JOIN securities {s} ON {s}.cusip = {h}.cusip"


def entity_join(
    h: str = "h",
    ec: str = "ec",
    *,
    via: EntityVia = "entity_id",
) -> str:
    """Return a LEFT JOIN fragment resolving entity metadata from ``entity_current``.

    Parameters
    ----------
    h:
        Alias of the holdings table (default ``h``).
    ec:
        Alias to assign to the joined ``entity_current`` row (default ``ec``).
    via:
        - ``'entity_id'`` (default) — joins on the existing stamped
          ``holdings_v2.entity_id``. Breaks once int-09 Step 4 retires the
          stamped column.
        - ``'cik'`` — resolves through ``entity_identifiers`` and is
          forward-compatible with the stamped-column retirement.

    Raises
    ------
    ValueError
        If ``via`` is not one of ``'entity_id'`` or ``'cik'``.

    ``entity_current`` is a VIEW that hardcodes ``rollup_type =
    'economic_control_v1'`` on its rollup leg; see :func:`rollup_join` for the
    DM-worldview bypass.
    """
    if via not in _VALID_ENTITY_VIA:
        raise ValueError(
            f"entity_join: via must be one of {_VALID_ENTITY_VIA}, got {via!r}"
        )
    if via == "entity_id":
        return f"LEFT JOIN entity_current {ec} ON {ec}.entity_id = {h}.entity_id"
    return (
        f"LEFT JOIN entity_identifiers ei_{ec} "
        f"  ON ei_{ec}.identifier_type = 'cik' "
        f" AND ei_{ec}.identifier_value = {h}.cik "
        f" AND ei_{ec}.valid_to = DATE '9999-12-31' "
        f"LEFT JOIN entity_current {ec} ON {ec}.entity_id = ei_{ec}.entity_id"
    )


def rollup_join(
    ec: str = "ec",
    ec_rollup: str = "ec_rollup",
    *,
    worldview: Worldview = "economic_control_v1",
    h: str = "h",
) -> str:
    """Return a LEFT JOIN fragment resolving the rollup entity's display row.

    Parameters
    ----------
    ec:
        Alias of the entity_current row joined upstream by :func:`entity_join`
        (default ``ec``). Used for the EC self-join target.
    ec_rollup:
        Alias to assign to the rollup entity's ``entity_current`` row
        (default ``ec_rollup``).
    worldview:
        - ``'economic_control_v1'`` — self-join through ``entity_current``
          (the VIEW itself is EC-hardcoded, so this is free).
        - ``'decision_maker_v1'`` — bypasses the VIEW and hits
          ``entity_rollup_history`` directly with
          ``rollup_type = 'decision_maker_v1'``.
    h:
        Alias of the holdings table. Only used on the DM path for joining
        ``entity_rollup_history.entity_id = {h}.entity_id`` (default ``h``).

    Raises
    ------
    ValueError
        If ``worldview`` is not one of the two supported values. Silently
        falling through would produce wrong results — ``entity_current`` only
        exposes EC rollups, so any unknown worldview must be refused
        explicitly. See §6.3 of the proposal for the reliability finding that
        motivates this.
    """
    if worldview not in _VALID_WORLDVIEWS:
        raise ValueError(
            f"rollup_join: worldview must be one of {_VALID_WORLDVIEWS}, got {worldview!r}"
        )
    if worldview == "economic_control_v1":
        return (
            f"LEFT JOIN entity_current {ec_rollup} "
            f"  ON {ec_rollup}.entity_id = {ec}.rollup_entity_id"
        )
    return (
        f"LEFT JOIN entity_rollup_history erh_{ec_rollup} "
        f"  ON erh_{ec_rollup}.entity_id = {h}.entity_id "
        f" AND erh_{ec_rollup}.rollup_type = 'decision_maker_v1' "
        f" AND erh_{ec_rollup}.valid_to = DATE '9999-12-31' "
        f"LEFT JOIN entity_current {ec_rollup} "
        f"  ON {ec_rollup}.entity_id = erh_{ec_rollup}.rollup_entity_id"
    )


def classification_join(ec: str = "ech", h: str = "h") -> str:
    """Return a LEFT JOIN fragment for manager_type via ``entity_classification_history``.

    Parameters
    ----------
    ec:
        Alias to assign to the classification row (default ``ech``).
    h:
        Alias of the holdings table (default ``h``).

    Open-row sentinel is ``valid_to = DATE '9999-12-31'``, matching the
    project-wide SCD convention.
    """
    return (
        f"LEFT JOIN entity_classification_history {ec} "
        f"  ON {ec}.entity_id = {h}.entity_id "
        f" AND {ec}.valid_to = DATE '9999-12-31'"
    )


__all__ = [
    "Worldview",
    "EntityVia",
    "ticker_join",
    "entity_join",
    "rollup_join",
    "classification_join",
]
