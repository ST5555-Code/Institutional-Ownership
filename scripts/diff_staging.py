#!/usr/bin/env python3
"""
diff_staging.py — human-readable diff between staging and production
entity tables. Names not IDs. Focused on the kinds of changes that
actually need human review before promotion.

Output: console + logs/staging_diff_YYYYMMDD.txt (overwrites the day's
file if re-run; rename in the workflow if you need history).

Usage:
  python3 scripts/diff_staging.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

LOG_PATH_FMT = ROOT / "logs" / "staging_diff_{date}.txt"


def _open_dual() -> object:
    """Return a duckdb in-memory connection with prod + staging attached."""
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{db.PROD_DB}' AS prod (READ_ONLY)")
    con.execute(f"ATTACH '{db.STAGING_DB}' AS stg (READ_ONLY)")
    return con


def _name_lookup_sql(side: str) -> str:
    """Return SQL fragment that resolves entity_id → preferred alias name in
    the given side ('prod' or 'stg')."""
    return f"""
        SELECT entity_id, alias_name
        FROM {side}.entity_aliases
        WHERE is_preferred = TRUE AND valid_to = DATE '9999-12-31'
    """


# =============================================================================
# Per-table diff routines
# =============================================================================
def diff_entities(con, out: StringIO) -> dict:
    """New / deleted entities (by entity_id)."""
    added = con.execute(f"""
        SELECT s.entity_id, s.entity_type,
               COALESCE(name.alias_name, s.canonical_name) AS name
        FROM stg.entities s
        LEFT JOIN ({_name_lookup_sql('stg')}) name USING (entity_id)
        WHERE s.entity_id NOT IN (SELECT entity_id FROM prod.entities)
        ORDER BY s.entity_id
    """).fetchall()
    deleted = con.execute(f"""
        SELECT p.entity_id, p.entity_type,
               COALESCE(name.alias_name, p.canonical_name) AS name
        FROM prod.entities p
        LEFT JOIN ({_name_lookup_sql('prod')}) name USING (entity_id)
        WHERE p.entity_id NOT IN (SELECT entity_id FROM stg.entities)
        ORDER BY p.entity_id
    """).fetchall()

    if added or deleted:
        out.write("\n## entities\n")
        if added:
            out.write(f"  ADDED ({len(added)}):\n")
            for eid, etype, name in added[:25]:
                out.write(f"    + eid={eid}  [{etype}]  {name}\n")
            if len(added) > 25:
                out.write(f"    ... and {len(added) - 25} more\n")
        if deleted:
            out.write(f"  DELETED ({len(deleted)}):\n")
            for eid, etype, name in deleted[:25]:
                out.write(f"    - eid={eid}  [{etype}]  {name}\n")
            if len(deleted) > 25:
                out.write(f"    ... and {len(deleted) - 25} more\n")
    return {"added": len(added), "deleted": len(deleted)}


def diff_relationships(con, out: StringIO) -> dict:
    """New / deleted entity_relationships, joined to alias names on both ends."""
    added = con.execute(f"""
        SELECT s.relationship_id, s.parent_entity_id, s.child_entity_id,
               s.relationship_type, s.source, s.confidence, s.is_primary,
               COALESCE(pn.alias_name, '?') AS parent_name,
               COALESCE(cn.alias_name, '?') AS child_name
        FROM stg.entity_relationships s
        LEFT JOIN ({_name_lookup_sql('stg')}) pn ON s.parent_entity_id = pn.entity_id
        LEFT JOIN ({_name_lookup_sql('stg')}) cn ON s.child_entity_id = cn.entity_id
        WHERE s.valid_to = DATE '9999-12-31'
          AND s.relationship_id NOT IN (
              SELECT relationship_id FROM prod.entity_relationships
              WHERE valid_to = DATE '9999-12-31'
          )
        ORDER BY s.relationship_id
    """).fetchall()
    deleted = con.execute(f"""
        SELECT p.relationship_id, p.parent_entity_id, p.child_entity_id,
               p.relationship_type, p.source, p.confidence, p.is_primary,
               COALESCE(pn.alias_name, '?') AS parent_name,
               COALESCE(cn.alias_name, '?') AS child_name
        FROM prod.entity_relationships p
        LEFT JOIN ({_name_lookup_sql('prod')}) pn ON p.parent_entity_id = pn.entity_id
        LEFT JOIN ({_name_lookup_sql('prod')}) cn ON p.child_entity_id = cn.entity_id
        WHERE p.valid_to = DATE '9999-12-31'
          AND p.relationship_id NOT IN (
              SELECT relationship_id FROM stg.entity_relationships
              WHERE valid_to = DATE '9999-12-31'
          )
        ORDER BY p.relationship_id
    """).fetchall()

    if added or deleted:
        out.write("\n## entity_relationships (active only)\n")
        if added:
            out.write(f"  ADDED ({len(added)}):\n")
            for r in added[:50]:
                star = "*" if r[6] else " "
                out.write(
                    f"    +{star} relid={r[0]}  {r[7]} → {r[8]}  "
                    f"({r[3]}, src={r[4]}, conf={r[5]})\n"
                )
            if len(added) > 50:
                out.write(f"    ... and {len(added) - 50} more\n")
        if deleted:
            out.write(f"  DELETED ({len(deleted)}):\n")
            for r in deleted[:50]:
                star = "*" if r[6] else " "
                out.write(
                    f"    -{star} relid={r[0]}  {r[7]} → {r[8]}  "
                    f"({r[3]}, src={r[4]}, conf={r[5]})\n"
                )
            if len(deleted) > 50:
                out.write(f"    ... and {len(deleted) - 50} more\n")
    return {"added": len(added), "deleted": len(deleted)}


def diff_rollups(con, out: StringIO) -> dict:
    """Compare CURRENT rollup state per (entity_id, rollup_type).

    SCD raw-row diffs are too noisy to be useful — what humans care
    about is "did this entity's current rollup parent change". So we
    compare the active row (valid_to = 9999-12-31) on each side.
    """
    rows = con.execute(f"""
        WITH stg_active AS (
            SELECT entity_id, rollup_type, rollup_entity_id, rule_applied,
                   source, routing_confidence
            FROM stg.entity_rollup_history
            WHERE valid_to = DATE '9999-12-31'
        ),
        prod_active AS (
            SELECT entity_id, rollup_type, rollup_entity_id, rule_applied,
                   source, routing_confidence
            FROM prod.entity_rollup_history
            WHERE valid_to = DATE '9999-12-31'
        )
        SELECT
            COALESCE(s.entity_id, p.entity_id) AS entity_id,
            COALESCE(s.rollup_type, p.rollup_type) AS rollup_type,
            p.rollup_entity_id AS prod_target,
            s.rollup_entity_id AS stg_target,
            p.rule_applied AS prod_rule,
            s.rule_applied AS stg_rule,
            p.source AS prod_source,
            s.source AS stg_source,
            CASE
                WHEN p.entity_id IS NULL THEN 'added'
                WHEN s.entity_id IS NULL THEN 'deleted'
                WHEN p.rollup_entity_id != s.rollup_entity_id THEN 'retargeted'
                WHEN COALESCE(p.rule_applied,'') != COALESCE(s.rule_applied,'')
                  OR COALESCE(p.source,'')      != COALESCE(s.source,'')
                  OR COALESCE(p.routing_confidence,'') != COALESCE(s.routing_confidence,'')
                  THEN 'metadata_changed'
                ELSE 'same'
            END AS kind
        FROM stg_active s
        FULL OUTER JOIN prod_active p
          ON s.entity_id = p.entity_id AND s.rollup_type = p.rollup_type
    """).fetchall()

    # Resolve all entity_ids referenced into names in one go
    eids = set()
    for r in rows:
        if r[8] == "same":
            continue
        eids.add(r[0])
        if r[2] is not None:
            eids.add(r[2])
        if r[3] is not None:
            eids.add(r[3])
    name_map = {}
    if eids:
        # Look up names from staging first, fall back to prod
        for side in ("stg", "prod"):
            placeholder = ",".join(str(int(e)) for e in eids if e is not None)
            if not placeholder:
                continue
            sql = f"""
                SELECT entity_id, alias_name
                FROM {side}.entity_aliases
                WHERE is_preferred = TRUE AND valid_to = DATE '9999-12-31'
                  AND entity_id IN ({placeholder})
            """
            for eid, name in con.execute(sql).fetchall():
                name_map.setdefault(eid, name)

    def n(eid):
        return name_map.get(eid, f"eid={eid}") if eid is not None else "—"

    by_kind = {"added": [], "deleted": [], "retargeted": [], "metadata_changed": []}
    for r in rows:
        kind = r[8]
        if kind == "same":
            continue
        by_kind[kind].append(r)

    if any(by_kind.values()):
        out.write("\n## entity_rollup_history (current state per worldview)\n")
        for kind in ("retargeted", "added", "deleted", "metadata_changed"):
            items = by_kind[kind]
            if not items:
                continue
            out.write(f"  {kind.upper()} ({len(items)}):\n")
            for r in items[:50]:
                eid, rt = r[0], r[1]
                if kind == "retargeted":
                    out.write(
                        f"    ~ {n(eid)} [{rt}]  {n(r[2])} → {n(r[3])}  "
                        f"({r[4]} → {r[5]}, src {r[6]} → {r[7]})\n"
                    )
                elif kind == "added":
                    out.write(f"    + {n(eid)} [{rt}] → {n(r[3])}  ({r[5]}, src {r[7]})\n")
                elif kind == "deleted":
                    out.write(f"    - {n(eid)} [{rt}] → {n(r[2])}  ({r[4]}, src {r[6]})\n")
                else:
                    out.write(
                        f"    · {n(eid)} [{rt}] {n(r[2])}  rule={r[4]}→{r[5]} "
                        f"src={r[6]}→{r[7]}\n"
                    )
            if len(items) > 50:
                out.write(f"    ... and {len(items) - 50} more\n")

    return {kind: len(v) for kind, v in by_kind.items()}


def diff_classifications(con, out: StringIO) -> dict:
    """Compare CURRENT classification per entity."""
    rows = con.execute(f"""
        WITH stg_active AS (
            SELECT entity_id, classification, is_activist, confidence
            FROM stg.entity_classification_history
            WHERE valid_to = DATE '9999-12-31'
        ),
        prod_active AS (
            SELECT entity_id, classification, is_activist, confidence
            FROM prod.entity_classification_history
            WHERE valid_to = DATE '9999-12-31'
        )
        SELECT
            COALESCE(s.entity_id, p.entity_id) AS entity_id,
            p.classification AS prod_class,
            s.classification AS stg_class,
            p.is_activist AS prod_act,
            s.is_activist AS stg_act,
            CASE
                WHEN p.entity_id IS NULL THEN 'added'
                WHEN s.entity_id IS NULL THEN 'deleted'
                WHEN COALESCE(p.classification,'') != COALESCE(s.classification,'')
                  OR p.is_activist IS DISTINCT FROM s.is_activist
                  THEN 'changed'
                ELSE 'same'
            END AS kind
        FROM stg_active s
        FULL OUTER JOIN prod_active p ON s.entity_id = p.entity_id
    """).fetchall()

    eids = {r[0] for r in rows if r[5] != "same" and r[0] is not None}
    name_map = {}
    if eids:
        placeholder = ",".join(str(int(e)) for e in eids)
        for side in ("stg", "prod"):
            sql = f"""
                SELECT entity_id, alias_name
                FROM {side}.entity_aliases
                WHERE is_preferred = TRUE AND valid_to = DATE '9999-12-31'
                  AND entity_id IN ({placeholder})
            """
            for eid, name in con.execute(sql).fetchall():
                name_map.setdefault(eid, name)

    def n(eid):
        return name_map.get(eid, f"eid={eid}")

    by_kind = {"added": [], "deleted": [], "changed": []}
    for r in rows:
        kind = r[5]
        if kind == "same":
            continue
        by_kind[kind].append(r)

    if any(by_kind.values()):
        out.write("\n## entity_classification_history (current state)\n")
        for kind in ("changed", "added", "deleted"):
            items = by_kind[kind]
            if not items:
                continue
            out.write(f"  {kind.upper()} ({len(items)}):\n")
            for r in items[:50]:
                if kind == "changed":
                    out.write(
                        f"    ~ {n(r[0])}  {r[1]} → {r[2]}"
                        f"  (activist {r[3]} → {r[4]})\n"
                    )
                elif kind == "added":
                    out.write(f"    + {n(r[0])}  {r[2]}  (activist={r[4]})\n")
                else:
                    out.write(f"    - {n(r[0])}  {r[1]}  (activist={r[3]})\n")
            if len(items) > 50:
                out.write(f"    ... and {len(items) - 50} more\n")
    return {kind: len(v) for kind, v in by_kind.items()}


def diff_aliases(con, out: StringIO) -> dict:
    """Active alias diffs (added/deleted only — name changes register as both)."""
    added = con.execute("""
        SELECT s.entity_id, s.alias_name, s.alias_type, s.is_preferred
        FROM stg.entity_aliases s
        WHERE s.valid_to = DATE '9999-12-31'
          AND NOT EXISTS (
              SELECT 1 FROM prod.entity_aliases p
              WHERE p.entity_id = s.entity_id
                AND p.alias_name = s.alias_name
                AND p.valid_to = DATE '9999-12-31'
          )
    """).fetchall()
    deleted = con.execute("""
        SELECT p.entity_id, p.alias_name, p.alias_type, p.is_preferred
        FROM prod.entity_aliases p
        WHERE p.valid_to = DATE '9999-12-31'
          AND NOT EXISTS (
              SELECT 1 FROM stg.entity_aliases s
              WHERE s.entity_id = p.entity_id
                AND s.alias_name = p.alias_name
                AND s.valid_to = DATE '9999-12-31'
          )
    """).fetchall()
    if added or deleted:
        out.write("\n## entity_aliases (active only)\n")
        if added:
            out.write(f"  ADDED ({len(added)}):\n")
            for r in added[:50]:
                pref = " [preferred]" if r[3] else ""
                out.write(f'    + eid={r[0]}  "{r[1]}"  ({r[2]}){pref}\n')
            if len(added) > 50:
                out.write(f"    ... and {len(added) - 50} more\n")
        if deleted:
            out.write(f"  DELETED ({len(deleted)}):\n")
            for r in deleted[:50]:
                pref = " [preferred]" if r[3] else ""
                out.write(f'    - eid={r[0]}  "{r[1]}"  ({r[2]}){pref}\n')
            if len(deleted) > 50:
                out.write(f"    ... and {len(deleted) - 50} more\n")
    return {"added": len(added), "deleted": len(deleted)}


def diff_identifiers(con, out: StringIO) -> dict:
    added = con.execute("""
        SELECT s.entity_id, s.identifier_type, s.identifier_value, s.source
        FROM stg.entity_identifiers s
        WHERE s.valid_to = DATE '9999-12-31'
          AND NOT EXISTS (
              SELECT 1 FROM prod.entity_identifiers p
              WHERE p.entity_id = s.entity_id
                AND p.identifier_type = s.identifier_type
                AND p.identifier_value = s.identifier_value
                AND p.valid_to = DATE '9999-12-31'
          )
    """).fetchall()
    deleted = con.execute("""
        SELECT p.entity_id, p.identifier_type, p.identifier_value, p.source
        FROM prod.entity_identifiers p
        WHERE p.valid_to = DATE '9999-12-31'
          AND NOT EXISTS (
              SELECT 1 FROM stg.entity_identifiers s
              WHERE s.entity_id = p.entity_id
                AND s.identifier_type = p.identifier_type
                AND s.identifier_value = p.identifier_value
                AND s.valid_to = DATE '9999-12-31'
          )
    """).fetchall()
    if added or deleted:
        out.write("\n## entity_identifiers (active only)\n")
        if added:
            out.write(f"  ADDED ({len(added)}):\n")
            for r in added[:30]:
                out.write(f"    + eid={r[0]}  {r[1]}={r[2]}  src={r[3]}\n")
            if len(added) > 30:
                out.write(f"    ... and {len(added) - 30} more\n")
        if deleted:
            out.write(f"  DELETED ({len(deleted)}):\n")
            for r in deleted[:30]:
                out.write(f"    - eid={r[0]}  {r[1]}={r[2]}  src={r[3]}\n")
            if len(deleted) > 30:
                out.write(f"    ... and {len(deleted) - 30} more\n")
    return {"added": len(added), "deleted": len(deleted)}


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    if not Path(db.PROD_DB).exists():
        print(f"ERROR: production DB not found: {db.PROD_DB}", file=sys.stderr)
        sys.exit(2)
    if not Path(db.STAGING_DB).exists():
        print(f"ERROR: staging DB not found: {db.STAGING_DB}", file=sys.stderr)
        sys.exit(2)

    con = _open_dual()
    body = StringIO()
    body.write(f"# Staging vs Production diff — {datetime.now().isoformat(timespec='seconds')}\n")
    body.write(f"  prod    = {db.PROD_DB}\n")
    body.write(f"  staging = {db.STAGING_DB}\n")

    counts = {}
    counts["entities"] = diff_entities(con, body)
    counts["relationships"] = diff_relationships(con, body)
    counts["rollups"] = diff_rollups(con, body)
    counts["classifications"] = diff_classifications(con, body)
    counts["aliases"] = diff_aliases(con, body)
    counts["identifiers"] = diff_identifiers(con, body)
    con.close()

    # Build the summary header
    summary = StringIO()
    summary.write("\n## SUMMARY\n")
    n_rel = counts["relationships"]["added"] + counts["relationships"]["deleted"]
    n_roll = sum(counts["rollups"].values())
    n_cls = sum(counts["classifications"].values())
    n_ent = counts["entities"]["added"] + counts["entities"]["deleted"]
    n_alias = counts["aliases"]["added"] + counts["aliases"]["deleted"]
    n_id = counts["identifiers"]["added"] + counts["identifiers"]["deleted"]
    summary.write(f"  {n_rel} relationships changed (added/deleted)\n")
    summary.write(f"  {n_roll} rollups changed (added/deleted/retargeted/metadata)\n")
    summary.write(f"  {n_cls} classifications changed\n")
    summary.write(f"  {n_ent} entities added/deleted\n")
    summary.write(f"  {n_alias} aliases added/deleted\n")
    summary.write(f"  {n_id} identifiers added/deleted\n")
    total = n_rel + n_roll + n_cls + n_ent + n_alias + n_id
    summary.write(f"  TOTAL line-level changes: {total}\n")

    out = body.getvalue() + summary.getvalue()
    print(out)

    log_path = Path(str(LOG_PATH_FMT).format(date=datetime.now().strftime("%Y%m%d")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(out, encoding="utf-8")
    print(f"\nDiff written to {log_path}")


if __name__ == "__main__":
    main()
