# ops-17-p1 Findings — update.py retired-script references

**Item:** ops-17 — stale references in `scripts/update.py` to retired scripts.
**Scope:** Single-session verification. Read-only check at HEAD (post obs-10 / PR #52).
**Recommendation:** **CLOSE ops-17 AS ALREADY-SATISFIED by obs-10 (`b5c04aa`).**

## Check performed

Scanned `scripts/update.py` at HEAD for references to every file currently in `scripts/retired/`:

| Retired script | Reference in update.py? |
|---|---|
| `build_cusip_legacy.py` | none |
| `fetch_nport.py` | docstring-only (line 20, "Retired steps" history note) |
| `resolve_agent_names.py` | none |
| `resolve_bo_agents.py` | none |
| `resolve_names.py` | none |
| `unify_positions.py` | docstring-only (line 21, "Retired steps" history note) |

No executable references remain. The two remaining mentions are intentional — they document the retirement history in the module docstring's "Retired steps (removed from this script)" block. These are not stale references; removing them would erase the provenance note that obs-10 deliberately added.

## Conclusion

obs-10 fully closed ops-17. No code change needed.
