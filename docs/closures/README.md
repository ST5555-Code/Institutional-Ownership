# Per-session closure entries

New closures land here, one file per session. The historical
`ROADMAP.md § Closed items (log)` table is frozen as of 2026-04-23
and preserved in place as the pre-cutover archive.

Note: this directory is distinct from `archive/docs/closed/`, which holds
resolved proposal-style documents (a different convention that
predates the per-session closure log).

## Why per-session files

Two parallel sessions that both append to the same `### Closed items
(log)` block in `ROADMAP.md` produce a mechanical git conflict every
time — same file, same line offset, add/add. This pattern hit
multiple PRs on 2026-04-23 (PR #119 vs #120, PR #123 vs #122). The
conflicts were always trivial to resolve but never free: a fresh CI
cycle and a dispatched resolution session for each collision.

Putting each session's closure in its own file eliminates the write
contention entirely. Alphabetical sort by filename reconstructs the
timeline deterministically.

## Filename

`YYYY-MM-DD-<session-name>.md`

- `YYYY-MM-DD` — the date the session closed the item
- `<session-name>` — the branch/session name, verbatim

Examples:
- `2026-04-24-int-24.md`
- `2026-04-24-inf50.md`
- `2026-04-25-doc-hygiene-w2.md`

## File format

One Markdown table row per closed item, no header, no surrounding
prose. Keep the same four-column shape as `ROADMAP.md § Closed items
(log)` so the rows can be concatenated verbatim:

```
| <ID> | <short title> | **Done YYYY-MM-DD** (`<session-name>`…) | <notes> |
```

Multiple closures from the same session stack as multiple rows in
one file. One row per line — do not insert blank lines between rows.

## Concatenating into a flat log

When a single flat view is needed (grep, scrolling, audit), run:

```
python3 scripts/hygiene/concat_closed_log.py
```

Output: `docs/closed-items-log.md` (git-ignored; regenerate on
demand). This file is generated — do not hand-edit. It is
rebuildable at any time from `docs/closures/*.md`.

## Out of scope

Open items stay in `ROADMAP.md § Open items` as today. Only the act
of *closing* an item moves its row out of `ROADMAP.md` and into a
per-session file here.
