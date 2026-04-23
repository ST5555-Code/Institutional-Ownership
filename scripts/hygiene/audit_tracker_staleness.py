#!/usr/bin/env python3
"""Audit tracker docs for cross-doc status drift.

The repo keeps several long-lived tracker docs (ROADMAP.md,
docs/REMEDIATION_PLAN.md, docs/DEFERRED_FOLLOWUPS.md,
docs/NEXT_SESSION_CONTEXT.md). Items (INF##,
int-##, mig-##, obs-##, sec-##, ops-##, P2-FU-##) get mentioned in
several of these docs at once. When a session closes an item but only
updates one tracker, the other trackers lie.

This script grep-scans every tracker for item IDs and classifies each
mention as "closed", "open", or "reference" from surrounding tokens.
It reports IDs whose mentions disagree across docs — exactly the
staleness pattern the hygiene-tracker-sync session is trying to prevent.

Usage:
    python3 scripts/audit_tracker_staleness.py          # human-readable
    python3 scripts/audit_tracker_staleness.py --json   # machine-readable
    python3 scripts/audit_tracker_staleness.py --quiet  # exit 1 on drift,
                                                          no per-item noise

The script never modifies files. Fix-up is a separate session.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

TRACKER_DOCS: tuple[Path, ...] = (
    REPO_ROOT / "ROADMAP.md",
    REPO_ROOT / "docs" / "REMEDIATION_PLAN.md",
    REPO_ROOT / "docs" / "DEFERRED_FOLLOWUPS.md",
    REPO_ROOT / "docs" / "NEXT_SESSION_CONTEXT.md",
)

# Patterns capture the entire ID as a single token. Order matters — longer
# prefixes first so "P2-FU-01" is not truncated to "FU-01".
ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("P2-FU", re.compile(r"\bP2-FU-\d{2,3}\b")),
    ("INF", re.compile(r"\bINF\d{1,3}[a-z]?\b")),
    ("int", re.compile(r"\bint-\d{2,3}\b")),
    ("mig", re.compile(r"\bmig-\d{2,3}\b")),
    ("obs", re.compile(r"\bobs-\d{2,3}\b")),
    ("sec", re.compile(r"\bsec-\d{2,3}\b")),
    ("ops", re.compile(r"\bops-\d{2,3}\b")),
    # p2-/w2- session IDs referenced by downstream work
    ("p2", re.compile(r"\bp2-\d{2,3}\b")),
    ("w2", re.compile(r"\bw2-\d{2,3}\b")),
)

# Markers are matched with word boundaries (case-insensitive). "[x]" and
# "[ ]" are handled separately because the brackets are not word chars.
CLOSED_WORDS = (
    "CLOSED",
    "CLEARED",
    "DONE",
    "RESOLVED",
    "SHIPPED",
    "SUPERSEDED",  # replaced by another ID; effectively closed for tracking
)
OPEN_WORDS = (
    "TODO",
    # "PENDING" is intentionally excluded — it is frequently used as a
    # qualifier ("pending int-09 completion") rather than a status, and
    # produces false positives. Explicit OPEN status in these trackers
    # is conveyed by `- [ ]` checkboxes.
)
# Neutral = intentionally-open states that are NOT drift. STANDING is a
# curation queue; DEFERRED is scheduled-later; BLOCKED is acknowledged
# externally; UNBLOCKED means actionable but not yet done.
NEUTRAL_WORDS = (
    "STANDING",
    "DEFERRED",
    "SKIPPED",
    "BLOCKED",
    "UNBLOCKED",
)

# Citation patterns that superficially look like status markers but are
# actually pointers to a doc section. Strip these before classifying so
# "ROADMAP §Open items" does not get read as status="open".
CITATION_PATTERNS = (
    re.compile(r"§\s*open\s*items?", re.IGNORECASE),
    re.compile(r"open\s+items", re.IGNORECASE),
    re.compile(r"ROADMAP\s*§\s*Open", re.IGNORECASE),
)


def _make_word_re(words: Iterable[str]) -> re.Pattern[str]:
    joined = "|".join(re.escape(w) for w in words)
    return re.compile(rf"\b(?:{joined})\b", re.IGNORECASE)


CLOSED_RE = _make_word_re(CLOSED_WORDS)
OPEN_RE = _make_word_re(OPEN_WORDS)
NEUTRAL_RE = _make_word_re(NEUTRAL_WORDS)
# "COMPLETE" / "COMPLETED" as a whole word is a closure signal, but
# "COMPLETE" embedded in words like "incomplete" should not match. Add
# separately with word boundaries.
COMPLETE_RE = re.compile(r"\bCOMPLETE[D]?\b", re.IGNORECASE)
CHECKBOX_CLOSED_RE = re.compile(r"-\s*\[x\]", re.IGNORECASE)
CHECKBOX_OPEN_RE = re.compile(r"-\s*\[\s\]")


@dataclass
class Mention:
    path: Path
    lineno: int
    line: str
    status: str  # "closed" | "open" | "neutral" | "reference"

    @property
    def rel_path(self) -> str:
        return str(self.path.relative_to(REPO_ROOT))


@dataclass
class IdReport:
    id: str
    mentions: list[Mention] = field(default_factory=list)

    def statuses_by_doc(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = defaultdict(set)
        for m in self.mentions:
            out[m.rel_path].add(m.status)
        return out

    def has_drift(self) -> bool:
        """Drift = at least one doc says closed AND at least one says open,
        considering the strongest signal in each doc."""
        per_doc = self.statuses_by_doc()
        docs_with_closed: set[str] = set()
        docs_with_open: set[str] = set()
        for doc, statuses in per_doc.items():
            if "closed" in statuses:
                docs_with_closed.add(doc)
            # Only count "open" if the doc has no closed signal for this ID.
            # A single doc can list an item in both an "open" and a "closed"
            # table (RemediationChecklist does exactly that). That is
            # intra-doc annotation, not cross-doc drift.
            elif "open" in statuses:
                docs_with_open.add(doc)
        return bool(docs_with_closed and docs_with_open)


def classify_line(line: str) -> str:
    scrubbed = line
    for patt in CITATION_PATTERNS:
        scrubbed = patt.sub("", scrubbed)

    has_closed = bool(
        CLOSED_RE.search(scrubbed)
        or COMPLETE_RE.search(scrubbed)
        or CHECKBOX_CLOSED_RE.search(scrubbed)
    )
    has_open = bool(OPEN_RE.search(scrubbed) or CHECKBOX_OPEN_RE.search(scrubbed))
    has_neutral = bool(NEUTRAL_RE.search(scrubbed))

    # Precedence: CLOSED dominates (covers "- [x] CLOSED (PR #99)"). NEUTRAL
    # then OPEN — STANDING/DEFERRED items should not be flagged as drift just
    # because the surrounding prose says "ROADMAP §Open".
    if has_closed:
        return "closed"
    if has_neutral:
        return "neutral"
    if has_open:
        return "open"
    return "reference"


def find_id_spans(line: str) -> list[tuple[str, int, int]]:
    """Return (id, start, end) for every ID occurrence in the line."""
    spans: list[tuple[str, int, int]] = []
    for _prefix, pattern in ID_PATTERNS:
        for m in pattern.finditer(line):
            spans.append((m.group(0), m.start(), m.end()))
    return spans


# Two proximity windows. The post-ID narrow window (immediately after the
# ID, e.g. "int-18 standing") captures inline exception markers that
# describe this specific ID even when the surrounding paragraph lists
# many items. The wide window fills in the common case of a table row
# whose status cell is further away from the ID than 60 chars.
POST_NARROW = 60
PROXIMITY_WIDE = 120


def scan_file(path: Path) -> Iterable[tuple[str, Mention]]:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    in_code_block = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        spans = find_id_spans(raw)
        if not spans:
            continue
        for ident, start, end in spans:
            # Post-ID inline markers dominate for closed/neutral signals
            # only. "int-18 standing" right after the ID overrides the
            # sentence-level "22/23 CLOSED" that precedes it. Open-only
            # signals in a narrow window (e.g. a `- [ ]` at line start)
            # are weaker than an explicit status in the wider context.
            post = raw[end : min(len(raw), end + POST_NARROW)]
            post_status = classify_line(post)
            if post_status in ("closed", "neutral"):
                status = post_status
            else:
                wide = raw[max(0, start - PROXIMITY_WIDE) : min(len(raw), end + PROXIMITY_WIDE)]
                status = classify_line(wide)
            yield ident, Mention(
                path=path, lineno=lineno, line=raw.rstrip(), status=status
            )


def build_report(tracker_docs: Iterable[Path]) -> dict[str, IdReport]:
    by_id: dict[str, IdReport] = {}
    for path in tracker_docs:
        for ident, mention in scan_file(path):
            rep = by_id.setdefault(ident, IdReport(id=ident))
            rep.mentions.append(mention)
    return by_id


def _id_sort_key(ident: str) -> tuple[str, int, str]:
    """Sort so INF9 < INF10 and int-01 < int-02. Preserves a-suffix order."""
    m = re.match(r"([A-Za-z0-9-]+?)-?(\d+)([a-z]?)$", ident)
    if not m:
        return (ident, 0, "")
    return (m.group(1), int(m.group(2)), m.group(3))


def format_human(reports: dict[str, IdReport]) -> str:
    drift = {ident: rep for ident, rep in reports.items() if rep.has_drift()}
    lines: list[str] = []
    lines.append(f"scanned {len(TRACKER_DOCS)} tracker docs")
    lines.append(f"found {len(reports)} unique IDs")
    lines.append(f"detected {len(drift)} IDs with cross-doc status drift")
    lines.append("")
    if not drift:
        lines.append("no drift detected.")
        return "\n".join(lines)
    for ident in sorted(drift, key=_id_sort_key):
        rep = drift[ident]
        lines.append(f"--- {ident} ---")
        per_doc = rep.statuses_by_doc()
        for doc in sorted(per_doc):
            summary = sorted(per_doc[doc])
            lines.append(f"  {doc}: {', '.join(summary)}")
        for m in rep.mentions:
            if m.status in ("closed", "open"):
                excerpt = m.line.strip()
                if len(excerpt) > 160:
                    excerpt = excerpt[:157] + "..."
                lines.append(f"    {m.rel_path}:{m.lineno} [{m.status}] {excerpt}")
        lines.append("")
    return "\n".join(lines)


def format_json(reports: dict[str, IdReport]) -> str:
    drift = {ident: rep for ident, rep in reports.items() if rep.has_drift()}
    payload = {
        "tracker_docs": [str(p.relative_to(REPO_ROOT)) for p in TRACKER_DOCS],
        "total_ids": len(reports),
        "drift_count": len(drift),
        "drift": [
            {
                "id": ident,
                "statuses_by_doc": {
                    doc: sorted(statuses)
                    for doc, statuses in drift[ident].statuses_by_doc().items()
                },
                "mentions": [
                    {
                        "path": m.rel_path,
                        "lineno": m.lineno,
                        "status": m.status,
                        "line": m.line.strip(),
                    }
                    for m in drift[ident].mentions
                ],
            }
            for ident in sorted(drift, key=_id_sort_key)
        ],
    }
    return json.dumps(payload, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress per-ID listing; exit status still reflects drift",
    )
    args = parser.parse_args(argv)

    reports = build_report(TRACKER_DOCS)
    drift_count = sum(1 for rep in reports.values() if rep.has_drift())

    if args.json:
        print(format_json(reports))
    elif args.quiet:
        print(f"tracker drift: {drift_count} ID(s)")
    else:
        print(format_human(reports))

    return 1 if drift_count else 0


if __name__ == "__main__":
    sys.exit(main())
