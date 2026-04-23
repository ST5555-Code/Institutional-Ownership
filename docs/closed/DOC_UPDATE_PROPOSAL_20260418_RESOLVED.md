# Doc Update Proposal — 2026-04-18 — **RESOLVED**

**Closure summary (doc-hygiene-w1, 2026-04-23).** All seven Phase 0 items applied and verified landed on `main` prior to this closeout. Status per item:

1. **Denormalized v2 columns — stamps not joins.** Applied. New section at `docs/data_layers.md §7 — Denormalized enrichment columns — drift risk and planned retirement`. Cross-references landed in `ENTITY_ARCHITECTURE.md` (Known Limitations + Design Decision Log) and `ROADMAP.md` INF25 (BLOCK-DENORM-RETIREMENT, subsequently deferred to Phase 2 per int-09 2026-04-22).
2. **BLOCK-OPENFIGI-RETRY-HYGIENE.** Applied. `ROADMAP.md` INF26, **Done 2026-04-22 (int-10)** — `scripts/run_openfigi_retry.py:185-208` `_update_error()` now flips `status='unmappable'` at `attempt_count >= MAX_ATTEMPTS`.
3. **BLOCK-CUSIP-COVERAGE (reduced scope).** Applied. `ROADMAP.md` INF27 in STANDING / data-quality tier; tracking tier documented in `docs/data_layers.md §11` (int-11-p1, 2026-04-22).
4. **BLOCK-SCHEMA-CONSTRAINT-HYGIENE.** Applied. `ROADMAP.md` INF28, **Done 2026-04-22 (int-12, PR #95)** — migration 011 `securities_cusip_pk.py`; `VALIDATOR_MAP` placeholder resolved.
5. **BLOCK-PRICEABILITY-REFINEMENT.** Applied. `docs/data_layers.md §6` picks up `S1` entry; `ROADMAP.md` INF29, **Done 2026-04-22 (int-13, PR #97)** — migration 012 `securities_is_otc.py` added `is_otc` classifier.
6. **`admin_bp.py:108` revisit flag.** Applied. Moved to `docs/NEXT_SESSION_CONTEXT.md` (option (b) in Phase 0 flag F1) rather than consuming an INF row.
7. **Phase 4 refetch pattern.** Applied. New H2 `## Refetch Pattern for Prod Apply` landed in `MAINTENANCE.md` (line 160).

File moved from `docs/DOC_UPDATE_PROPOSAL_20260418.md` to `docs/closed/` and renamed with `_RESOLVED` suffix during doc-hygiene-w1. Phase 0 proposal content preserved below for commit archaeology.

---

_Phase 0 output: structural review of the four canonical docs and
proposed insertion points for seven deferred items from
`BLOCK-SECURITIES-DATA-AUDIT`, `BLOCK-TICKER-BACKFILL`, and `BLOCK-3`.
No writes to the canonical docs in this phase — this file is the only
artifact of Phase 0._

Branch: `docs/architectural-updates-20260418`. Baseline: `3299a9f`.

---

## Section 1 — Canonical doc structural review

### 1.1 `ROADMAP.md` (1,095 lines)

**Last meaningful update:** 2026-04-17, session #11 close. The current-state
header block is ~14 paragraphs of dated session state stamped at
`HEAD 8323838`.

**Structural conventions.**
- Opens with a massive dated "current state" header (lines 1–21) that is
  rewritten every session. Prior headers are preserved chronologically
  inside the header block itself ("prior header…").
- Followed by "Session Summary" H2 sections, one per session, in reverse
  chronological order (2026-04-16 part 2 back through 2026-04-10).
  Narrative-heavy; read like close-out reports.
- Then a structural spine of H2 item-registry sections:
  - `## IN PROGRESS` (tiny table, currently stub)
  - `## PIPELINE 1 — 13D/G Beneficial Ownership` (Done items)
  - `## PIPELINE 8 — Short Interest`
  - `## APP — Flow Analysis Tab` / `## APP — New Features`
  - `## INFRASTRUCTURE — Performance & Reliability` — the **primary home
    for open infrastructure work**. Columns: `# | Item | Priority | Notes`.
    Items use sparse IDs (`INF1`…`INF24`, `L4-1`, `BUG`, numbered rows
    19–56). Most rows are `Done …date …commit`; a handful (`INF16`,
    low-priority items) are actually open. Priority column is typed ad
    hoc — `Done`, `Done 2026-04-12`, `Low`, `Medium`, `Recurring`,
    `Required before next …`.
  - `## Regulatory Watch`
  - `## ARCHITECTURE BACKLOG — from ARCHITECTURE_REVIEW.md (2026-04-12)`
    (sibling to `ARCHITECTURE_REVIEW.md`; mostly closed)
  - `## DECISION MAKER & VOTING ROLLUP WORLDVIEWS`
  - `## COMPLETED` (dated closed-item log)
  - `## FUTURE — Performance & Stability Hardening` (H1…H16)
  - `## FUTURE — Data Integrity & On-Demand Updates` (D1…D7 — all
    `Done`, unrelated to `data_layers.md` D5–D8)
  - `## FUTURE — Admin UI` (F1…F7)
  - `## FUTURE — New Features & Enhancements` (N1…N23)
  - `## FUTURE — Pipelines`
  - `## PIPELINE 9 — 13D/G Cleanup & Integration` / `## PIPELINE 10 —
    Monthly N-PORT Update Flow`
  - `## UI/UX Improvements` (U1…U12)
  - `## SEQUENCE — NEXT STEPS` (ordered list)

**Where each kind of work lands.**
- Architectural debt / open design decisions: no single section. Debt
  has historically been logged under `INFRASTRUCTURE` as an INF row
  (`INF9`…`INF18`), or as a design decision in `ENTITY_ARCHITECTURE.md`.
- Follow-on work on closed BLOCKs: interleaved into `INFRASTRUCTURE`
  or `FUTURE — *` tables.
- Operational patterns: not in ROADMAP — MAINTENANCE.md or
  ENTITY_ARCHITECTURE.md.
- Table metadata: `data_layers.md` — ROADMAP never carries column-level
  notes.
- Script behaviour / bugs: `INFRASTRUCTURE` rows (INF13, INF14, INF15,
  INF17b, the one `BUG` row).
- Known limitations: has no dedicated section; these live inside
  session-summary narrative or in `ENTITY_ARCHITECTURE.md → Known
  Limitations`.

**Observations.**
- The INFRASTRUCTURE table mixes closed and open work. Open work sinks
  inside a long list of `Done` rows and is easy to miss. A new
  structural home for open work (e.g., a subtable at top of the section)
  would help but isn't required — the table's conventions tolerate new
  rows.
- ID namespace for new follow-on rows should be `INF25`, `INF26`, …
  (next free IDs after `INF24`). `BLOCK-*` is not a ROADMAP-native
  prefix — historically tracking rows use `INF##` or `N##` / `H##` /
  `U##` namespaces.

---

### 1.2 `ENTITY_ARCHITECTURE.md` (557 lines)

**Last meaningful update:** 2026-04-17 (session #11 close).

**Structural conventions.**
- H1 title, then a dated revision-header paragraph.
- `## Overview` / `## Architecture Summary`.
- `## Architecture Summary` has H3 subsections: `Five Core Tables + One
  View`, `Two Strategic Principles`, `Rollup Types`, `Rollup Policy —
  Operating Asset Manager Rule`, `Classification Categories`.
- `## Implementation Phases` (H3 per phase 1, 2, 3, 3.5, 4).
- `## Operational Procedures` (H3: Standard workflow, What goes through
  staging, What does NOT, Validation gate exit codes, Rollback options,
  Backup protocol, Monthly maintenance, Schema drift caveat).
- `## Deferred Items` — **numbered table with ID/Target Phase/Reason/
  Notes columns.** Scope is entity-MDM-only. Contains `D1…D11` +
  integers `1…10`. Resolved items struck through with ✅.
- `## Validation Gates`.
- `## Known Limitations (Phase 1)` — **numbered list of architectural
  limitations, not bugs.** Good fit for architectural debt callouts.
- `## Files`.
- `## Admin Override Process`.
- `## Design Decision Log` — **append-only dated table.** Every
  meaningful architecture decision logs here with rationale + rejected
  alternative. New dated rows welcome.

**Where each kind of work lands.**
- Architectural debt: `Known Limitations` (architectural, not
  operational) and/or `Design Decision Log` (dated entry explaining
  the decision to treat something as debt).
- Follow-on work (entity scope): `Deferred Items` table with a D## ID.
- Operational patterns: `Operational Procedures`.
- Table metadata: `data_layers.md` instead — `ENTITY_ARCHITECTURE.md`
  stays at the entity-MDM level, not physical schema.
- Script behaviour: `Operational Procedures` or `Files` cross-reference.
- Known limitations: `Known Limitations` numbered list.

**Observations.**
- `Design Decision Log` is the cleanest home for a dated rationale like
  "denormalized v2 columns are stamps, not joins, and here's why, and
  here's the sequence to retire them."
- `Known Limitations` numbered list tolerates cross-references to
  `data_layers.md` for physical-schema detail.
- The scope of `Deferred Items` is entity MDM. Non-entity-MDM debt does
  not belong here.

---

### 1.3 `MAINTENANCE.md` (123 lines)

**Last meaningful update:** April 10, 2026 (file header). Hasn't been
touched during the session #10 / #11 DM audit closures — no evidence
that Batch 3, BLOCK-3, or BLOCK-TICKER-BACKFILL work has updated this
doc.

**Structural conventions.**
- Short, workflow-focused. Reference document, not a log.
- Sections: `Entity Change Workflow` (points to
  `ENTITY_ARCHITECTURE.md`), `Monthly Maintenance`, `Backup Protocol`,
  `Rollback Procedures`, `Pending Audit Work` (bulleted list of named
  audits — DM13/DM14/DM15/L5), `Stage 5 Cleanup`.

**Where each kind of work lands.**
- Operational patterns: this is the doc. Historically only covers
  entity-change workflow + backup/rollback/audit. Has no current
  section for "patterns for refetch-driven prod applies."
- Architectural debt: does not belong here.
- Follow-on work: **`Pending Audit Work`** is the nearest analogue;
  bullet list, short lines.
- Table metadata: does not belong here.
- Script behaviour: covered only where a script is named in a workflow.
- Known limitations: does not belong here.

**Observations.**
- `MAINTENANCE.md` is an unusually tidy doc. A new "Refetch Pattern"
  subsection between `Backup Protocol` and `Rollback Procedures` would
  fit the existing voice cleanly.
- `Pending Audit Work` is entity-focused (mentions DM audits, Securian,
  HC Capital Trust, CRI). It would admit a non-entity audit bullet but
  the doc's voice would strain.

---

### 1.4 `docs/data_layers.md` (476 lines)

**Last meaningful update:** 2026-04-17 (session #10 close; header block
cites `6f4fdfc` batch rewrite and 14.09M `fund_holdings_v2` rows).

**Structural conventions.**
- H1 + stacked dated revision headers (current + prior preserved
  inline).
- `## 1. Layer definitions` — L0/L1/L2/L3/L4 semantics.
- `## 2. Complete table inventory` — **authoritative table-by-table
  metadata with Layer / Owner / Promote strategy / Notes columns.**
  Every prod table is listed. Notes column is where per-table metadata
  lives (row counts, enrichment coverage, caveats, DDL migrations).
- `## 3. Column ownership — holdings_v2` / `## 4. … fund_holdings_v2`
  / `## 4b. … beneficial_ownership_v2` — column-by-column ownership
  per Group 1/2/3. **This is where denormalized enrichment column
  semantics are specified.**
- `## 5. Option B split contract` — **contract for denormalized enrichment
  columns that are allowed to be NULL.** Already carries the relevant
  architectural principle — just doesn't carry the _retirement_ principle.
- `## 6. Open decisions D5–D8` — **numbered open design decisions** with
  Decision needed / Options / Why unresolved substructure. Strong home
  for anything that's a deferred semantic decision rather than a bug.

**Where each kind of work lands.**
- Architectural debt (column-level or table-level): §2 Notes column, §5
  for boundary semantics, new section or new D-entry in §6 for open
  decisions.
- Follow-on work: §6 open decisions if it blocks a design choice;
  otherwise ROADMAP.
- Operational patterns: does not belong here.
- Table metadata: §2 is the table inventory of record.
- Script behaviour: §2 Owner-script column.
- Known limitations: embedded in §2 Notes or called out in §5 / §6.

**Observations.**
- §5 "Option B split contract" is the current definitional home for
  NULL-tolerant denormalized enrichment columns. A retirement principle
  for those same columns is the natural sequel — either extend §5 or
  add §7.
- §6 numbering (D5–D8) deliberately echoes the `ENTITY_ARCHITECTURE.md`
  D## namespace. New open decisions here should pick up at D9 if
  entity-scope, or adopt a distinct prefix (e.g., `S1…`) if
  securities-scope, to avoid collision with the entity D## series.

---

## Section 2 — Seven items, proposed placements

ID legend: items numbered 1–7 below match the order in the Phase 0
briefing. Each entry gives: primary doc + section (new or existing) +
approximate write size + secondary touch points + rationale.

### Item 1 — Denormalized v2 columns are stamps, not joins (architectural debt)

**Primary.** `docs/data_layers.md`. Add new `## 7. Denormalized
enrichment columns — drift risk and planned retirement` after §6.
Complementary to §5 (Option B): §5 says "Group 3 columns are allowed
to be NULL"; §7 says "some Group 3 columns that answer 'what is the
current mapping for this key' should be joins, not stamps — and here
is the sequence to get there." Reference BLOCK-2 entity_id backfill
and BLOCK-TICKER-BACKFILL ticker drift as observed instances. State
the keep/retire principle; list the four denormalized columns in
scope (`ticker`, `entity_id`, `rollup_*`, `lei`-if-ever); spell out
the sequence `BLOCK-TICKER-BACKFILL → BLOCK-3 → Batch 3 REWRITE →
BLOCK-DENORM-RETIREMENT`.

**Secondary.** `ENTITY_ARCHITECTURE.md`:
- Add a new bullet to `## Known Limitations (Phase 1)` (after current
  item 5) pointing readers to `data_layers.md §7`. One line.
- Add a dated row to `## Design Decision Log` stating the
  "denormalized stamps vs joins" principle, the reason (drift
  observed in BLOCK-2 / BLOCK-TICKER-BACKFILL), and the rejected
  alternative ("continue stamping on promote; accept drift"). One
  table row.

**Secondary.** `ROADMAP.md`: add `BLOCK-DENORM-RETIREMENT` sequencing
row to the end of `INFRASTRUCTURE — Performance & Reliability` table
(`INF25` or `BLOCK-DR`), priority `Sequenced`. One row, cross-links
to `data_layers.md §7`.

**Size.** Largest of the seven. New section: ~60–90 lines in
`data_layers.md`. Cross-refs: 1 bullet + 1 Design Decision Log row
+ 1 ROADMAP row.

**Rationale.** The principle belongs to the physical-schema doc; it's
a statement about how v2 tables are built. Entity MDM debt is the
most visible instance but the rule is general across L3. The cross-
refs ensure a reader starting from entity architecture or the
roadmap finds the principle.

---

### Item 2 — BLOCK-OPENFIGI-RETRY-HYGIENE

**Primary.** `ROADMAP.md → ## INFRASTRUCTURE — Performance &
Reliability`. New row `INF26` (or next free), priority `Low`,
referencing `scripts/run_openfigi_retry.py:185-208` and naming the
bug (`_update_error()` does not flip `status='unmappable'` when
`attempt_count >= MAX_ATTEMPTS`, producing permanent-pending rows on
hard errors). State observed population (the 37,925-row retry queue
noted in the session #10 header) and scope ("small code fix").

**Secondary.** `data_layers.md §2` — one-line note on `cusip_retry_queue`
row referencing `ROADMAP INF26` if desired. Optional.

**Size.** One ROADMAP row, ~3 lines of Notes. No new section.

**Rationale.** Script bug with a known file:line fix. Matches the
existing `INF13` / `INF14` / `BUG` / `INF15` / `INF17b` pattern.

---

### Item 3 — BLOCK-CUSIP-COVERAGE (reduced scope)

**Primary.** `ROADMAP.md → ## INFRASTRUCTURE — Performance &
Reliability`. New row `INF27`, priority `Low / data quality`.
Describe the scope reduction: the original 6.2M-CUSIP gap closed by
`BLOCK-SECURITIES-DATA-AUDIT Phase 3` promotion (132K→430K); what
remains is (a) 81 malformed CUSIPs and (b) legitimately-new CUSIPs
in future ingestion. Cross-reference `BLOCK_TICKER_BACKFILL_FINDINGS.md
§10.1` for the 2025-08+ `cusip_not_in_securities` step-change.

**Secondary.** `data_layers.md §2` — optional one-line note on
`securities` / `cusip_classifications` pointing to `ROADMAP INF27`
for residual coverage gaps.

**Size.** One ROADMAP row, ~3–5 lines of Notes. No new section.

**Rationale.** A follow-on with well-defined residual scope — ROADMAP
tracks the work; `data_layers.md` only needs a pointer if any future
reader of the `securities` inventory row needs to know the gap exists.

---

### Item 4 — BLOCK-SCHEMA-CONSTRAINT-HYGIENE

**Primary.** `ROADMAP.md → ## INFRASTRUCTURE — Performance &
Reliability`. New row `INF28`, priority `Medium`. Two subparts:
(a) formal `PRIMARY KEY` / `UNIQUE` declarations on `securities.cusip`
(currently empirically unique, not formally declared); (b) register
canonical-table validators in `VALIDATOR_MAP` (`promote_staging.py`
currently has `None` placeholder for `cusip_classifications` and
`securities`).

**Secondary.** `data_layers.md §2` — append Notes on the
`securities`, `cusip_classifications` rows: "PK declaration + validator
registration pending; see ROADMAP INF28."

**Secondary.** `ENTITY_ARCHITECTURE.md § Operational Procedures →
Schema drift caveat (Apr 10 2026)` — this section already admits that
prod has a degraded schema vs `entity_schema.sql`. Add a one-line
cross-reference that `securities.cusip` has the same drift pattern
in the securities layer — confines scope of the caveat and points to
ROADMAP INF28 for the fix.

**Size.** One ROADMAP row with ~5 lines of Notes. Two one-line Notes in
`data_layers.md §2`. One bullet added to the existing Schema drift
caveat in `ENTITY_ARCHITECTURE.md`.

**Rationale.** Schema constraint hygiene is script-and-schema work, so
its home is ROADMAP INFRASTRUCTURE. The `Schema drift caveat` in
`ENTITY_ARCHITECTURE.md` is the sibling callout for entity tables and
naturally wants a pointer for the non-entity counterpart.

---

### Item 5 — BLOCK-PRICEABILITY-REFINEMENT

**Primary.** `docs/data_layers.md`. Two places:
- `§2` `securities` Notes column — append: `is_priceable` semantics are
  under review; OTC grey-market rows (e.g., RSMDF) currently flagged
  `is_priceable=TRUE` but are not functionally priceable.
- `§6 Open decisions` — add **`S1 — is_priceable semantic refinement
  for OTC grey-market rows`** (or `D9` if we keep the single D-series).
  Decision needed / Options / Why unresolved in the existing §6
  format.

**Secondary.** `ROADMAP.md → ## INFRASTRUCTURE — Performance &
Reliability`. New row `INF29`, priority `Low / semantics`, pointing
to `data_layers.md §6 S1`.

**Size.** One new entry in §6 (~15–25 lines). One line in §2 Notes.
One ROADMAP row.

**Rationale.** This is a semantic refinement on a specific L3 column —
squarely a `data_layers.md §6` open-decision shape, not a bug.
ROADMAP carries a pointer row so that the work is visible alongside
other INF tracking.

---

### Item 6 — `admin_bp.py:108` revisit flag (`data[0]` pattern)

**Primary.** `ROADMAP.md → ## INFRASTRUCTURE — Performance &
Reliability`. New row `INF30`, priority `Low / conditional`. State
the revisit condition: "Diagnostic UI only, no persistent writes;
revisit if admin path gains write semantics."

**Flag (see Section 3).** This is the smallest and narrowest of the
seven — a code-level revisit note. It may fit better in
`docs/NEXT_SESSION_CONTEXT.md` or as an inline code comment than in
ROADMAP. If we strictly constrain ourselves to the four canonical
docs, ROADMAP INFRASTRUCTURE is the only home that doesn't strain,
but the signal/noise ratio is marginal.

**Secondary.** None.

**Size.** One ROADMAP row with a 2-line Note, or nothing if the team
decides to drop it from canonical-doc scope.

**Rationale.** Lowest-priority item; canonical docs admit a one-row
tracking entry, but this is close to the line where revisit flags
should stay in code comments.

---

### Item 7 — Phase 4 refetch pattern (mirror staging refetch to prod via ephemeral helper)

**Primary.** `MAINTENANCE.md`. New H2 `## Refetch Pattern for Prod
Apply` between `## Backup Protocol` and `## Rollback Procedures`.
Content: (1) principle (idempotent, deterministic, no external API
calls from prod path); (2) when to use it (Phase 4 used it
successfully in BLOCK-3); (3) the shape of the ephemeral helper;
(4) guardrails (no writes outside the target table, no new external
network calls, checkpoint before/after).

**Secondary.** `ROADMAP.md → ## COMPLETED` — no change needed; BLOCK-3
closeout is already captured in the 2026-04-17 header block.

**Secondary.** `docs/data_layers.md §2` — no changes. Pattern is
operational, not table-level.

**Size.** New section in MAINTENANCE.md, ~20–35 lines. Matches the
voice of existing `## Backup Protocol` / `## Rollback Procedures`
sections.

**Rationale.** Operational pattern → `MAINTENANCE.md` is the intended
home. Adding it there elevates it from session-memory to a
repeatable workflow.

---

### Cross-reference matrix (condensed)

| Item | ROADMAP | ENTITY_ARCHITECTURE | MAINTENANCE | data_layers |
|---|---|---|---|---|
| 1 — denorm debt | INF25 sequence row | Known Limitations bullet + Design Decision Log row | — | **Primary: new §7** |
| 2 — openfigi retry hygiene | **Primary: INF26 row** | — | — | optional §2 Note |
| 3 — cusip coverage reduced scope | **Primary: INF27 row** | — | — | optional §2 Note |
| 4 — schema constraint hygiene | **Primary: INF28 row** | Schema drift caveat cross-ref | — | §2 Notes on `securities` / `cusip_classifications` |
| 5 — priceability refinement | INF29 pointer row | — | — | **Primary: §6 new decision S1 + §2 Note** |
| 6 — admin_bp revisit flag | **Primary: INF30 row** (flagged) | — | — | — |
| 7 — refetch pattern | — | — | **Primary: new H2 `Refetch Pattern for Prod Apply`** | — |

---

## Section 3 — Flags and open questions

**F1. Item 6 (admin_bp:108 revisit flag) may be out of scope for
canonical docs.** The item is a single-line code pattern caveat with
no persistent effect and a conditional trigger. Canonical docs admit
it as a ROADMAP INF row, but signal/noise is marginal. Options: (a)
write the ROADMAP row; (b) move to `docs/NEXT_SESSION_CONTEXT.md`
which already hosts in-flight caveats; (c) skip canonical-doc write
entirely and leave as an inline code comment. **Preference:** (b),
but (a) is defensible.

**F2. ID namespace choice for Item 5 new decision in `data_layers.md §6`.**
§6 uses `D5–D8` intentionally echoing `ENTITY_ARCHITECTURE.md`'s D##
deferred-items namespace. Options: (a) continue as `D9`, which may
collide conceptually with entity-MDM D-items; (b) start a
securities-specific `S1` prefix; (c) rename §6 to "Open decisions"
and introduce sub-prefixes (`entity_D#`, `sec_S#`). **Preference:**
(b) — add `S1` with a short header note clarifying the new prefix.
Needs sign-off because it changes the §6 naming convention.

**F3. INF## numbering collision risk.** Current max is `INF24`; new
rows would take `INF25…INF30`. Need to confirm no other in-flight
branch is already claiming these IDs. **Check before Phase 1 writes.**

**F4. Item 1 placement — extend §5 or add §7 in `data_layers.md`?**
§5 is titled "Option B split contract" and is narrowly about NULL
tolerance on denormalized enrichment columns. The new principle (some
denorm columns should become joins) is adjacent but architecturally
distinct (NULL tolerance vs. denorm retirement). **Preference:** new
§7 — keep §5 as a clean contract doc, let §7 be the forward-looking
debt doc. Signals directional intent without polluting the shipped
§5 contract.

**F5. ROADMAP "open work vs closed history" readability.** Adding
five new open INF rows (items 2, 3, 4, 5, 6) to a 60-row
`INFRASTRUCTURE` table that is mostly `Done` rows will make them
hard to find. Options: (a) append as usual, accept readability cost;
(b) introduce a "## Open INFRASTRUCTURE items" subtable at the top
of the section, with full rows moving down as they close; (c) add a
single "## Open Work" index block at top of ROADMAP pointing to the
new rows. **Not blocking**, but worth discussing before Phase 1 so the
commits don't churn. **Preference:** (a) — matches existing convention;
reconsider if the "Done" rows dilute the open queue further.

**F6. No item maps onto `## DECISION MAKER & VOTING ROLLUP WORLDVIEWS`
or the `## ARCHITECTURE BACKLOG` ROADMAP sections.** That is expected
— those sections are phase-scoped and not the home for BLOCK follow-ups.
Noted here so Phase 1 doesn't try to force fit.

**F7. MAINTENANCE.md's `## Pending Audit Work` section is entity-only.**
Item 7's refetch pattern is general (the BLOCK-3 prod apply was
ticker/market-data refetch, not entity). A new H2 instead of a bullet
in `Pending Audit Work` is cleaner. **Preference confirmed** — new H2.

**F8. None of the four canonical docs "resist" any of the seven items.**
Each item has at least one plausible home. No item requires a brand-new
canonical doc.

---

## Section 4 — Proposed Phase 1 commit ordering

Grouping related items to minimize churn and let reviewers read each
commit as one coherent change.

**Commit 1 — `docs(maintenance): refetch pattern for prod apply`.**
  - File: `MAINTENANCE.md` (+ ~30 lines).
  - Item covered: **7**.
  - Rationale: small, standalone operational doc update; lowest risk;
    no cross-refs.

**Commit 2 — `docs(data_layers): priceability refinement + schema /
coverage notes`.**
  - File: `docs/data_layers.md` (§2 Notes edits; new §6 decision S1).
  - Items covered: **3, 4, 5** (the §2 Notes side + the §6 decision).
  - Rationale: all three touch `data_layers.md` at adjacent spots;
    single commit keeps the §2 Notes column edits atomic.

**Commit 3 — `docs(roadmap): infrastructure follow-ups from BLOCK
closeouts`.**
  - File: `ROADMAP.md` (new `INF25…INF30` rows). May also touch the
    current-state header if we want these flagged in the header.
  - Items covered: **2, 3, 4, 5, 6** (ROADMAP rows).
  - Rationale: all are small INFRASTRUCTURE rows; batching them avoids
    five separate tiny commits and lets the reviewer see the full set
    of follow-ups at once.

**Commit 4 — `docs(data_layers): §7 denormalized columns — drift risk
and planned retirement`.**
  - Files: `docs/data_layers.md` (new §7); `ENTITY_ARCHITECTURE.md`
    (Known Limitations bullet + Design Decision Log row); `ROADMAP.md`
    (BLOCK-DENORM-RETIREMENT sequence row).
  - Item covered: **1**.
  - Rationale: the biggest, most cross-cutting write. Isolating it
    makes review tractable (one concept, three places).

**Optional Commit 5 — `docs(roadmap): admin_bp:108 revisit flag`.**
  - Only if we decide in Phase 0 review that Item 6 belongs in
    canonical docs. If it goes to `NEXT_SESSION_CONTEXT.md` instead,
    this commit drops.

---

## Summary

- **7 items reviewed.**
- **6 items with clean placement in canonical docs** (1, 2, 3, 4, 5, 7).
- **1 item flagged as needing a design decision** (6 — may belong in
  `NEXT_SESSION_CONTEXT.md` rather than canonical docs).
- No canonical doc structurally resists any item. All placements use
  existing section conventions except `data_layers.md §7` (new) and
  `MAINTENANCE.md` new H2 (straightforward addition in existing voice).
- Phase 1 is estimated at 4 commits (5 with Item 6 kept in scope).
