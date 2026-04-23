#!/usr/bin/env python3
"""Audit ticket-number discipline across tracker docs.

Scans markdown files for ticket references of the form PREFIX + NUMBER
(INFxx, DMxx, BLxx, mig-xx, int-xx, obs-xx, sec-xx, ops-xx, w2-xx, p2-xx,
conv-xx). For each (prefix, number) pair, collects lines that look like a
*definition* of the ticket — section headings, bold table rows, bulleted
items with a bold ticket label. Two or more distinct definition lines for
the same number are flagged as a candidate reuse for human review.

The script is a hygiene/diagnostic tool, not ground truth. The review gate
lives in `docs/REVIEW_CHECKLIST.md § Ticket Number Discipline`.

Usage:
    python3 scripts/audit_ticket_numbers.py          # full report
    python3 scripts/audit_ticket_numbers.py --quiet  # only reuse section
    python3 scripts/audit_ticket_numbers.py --strict # exit 1 on any reuse

Exit 0 on clean audit (or without --strict). Exit 1 with --strict when
candidate reuse is found.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PREFIXES: list[str] = [
    "INF",
    "DM",
    "BL",
    "mig-",
    "int-",
    "obs-",
    "sec-",
    "ops-",
    "w2-",
    "p2-",
    "conv-",
]

# Cap the ticket number to avoid collisions with CIKs / series IDs / PK values.
MAX_TICKET_NUMBER = 999

# Historical dual-closure tickets: already-annotated reuse retained per policy.
# Candidate-reuse detection skips these outright.
DUAL_CLOSURE_EXCEPTIONS = {"INF40"}

# Matches the dual-closure annotation sentinel, e.g. `[INF40 #1 of 2 ...]`.
ANNOTATION_RE = re.compile(
    r"\[(?:INF|DM|BL|mig-|int-|obs-|sec-|ops-|w2-|p2-|conv-)\d+[a-z]?\s+#\d+\s+of\s+\d+\b"
)

# Directories we never scan.
SKIP_DIRS = {
    ".git",
    ".claude",
    "node_modules",
    "dist",
    "build",
    "venv",
    ".venv",
    "__pycache__",
    "retired",
    "snapshots",
    "coverage",
    "superpowers",  # upstream skill pack, not our doc surface
}


@dataclass(frozen=True)
class Definition:
    """One line that looks like a ticket definition."""

    file: str
    line: int
    ticket: str
    kind: str  # "heading" | "table-row" | "bullet" | "line"
    title: str
    annotated: bool = False  # True if line carries `[TICKET #M of K]` sentinel


TICKET_ALT = "|".join(re.escape(p) for p in PREFIXES)
# Allow an optional single lowercase letter suffix (INF40a, DM15d, mig-04b) —
# these qualifiers are the *recommended* way to split a concept under one base
# number per docs/REVIEW_CHECKLIST.md § Ticket Number Discipline. Treating them
# as distinct tickets prevents the audit from flagging them as reuse.
TICKET_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?P<prefix>{TICKET_ALT})(?P<num>\d+)(?P<suffix>[a-z]?)"
    r"(?![0-9A-Za-z])"
)


def iter_markdown_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & SKIP_DIRS:
            continue
        yield path


def normalize_ticket(prefix_tok: str, num: str, suffix: str = "") -> str | None:
    try:
        n = int(num)
    except ValueError:
        return None
    if n == 0 or n > MAX_TICKET_NUMBER:
        return None
    return f"{prefix_tok}{num}{suffix}"


def line_kind(line: str) -> str | None:
    """Classify a line as a ticket-defining kind, or None if not definition."""
    stripped = line.lstrip()

    # Section heading — but not a "parallel work" cross-reference, which uses
    # ∥, /, or commas to list multiple tickets ("## sec-07 ∥ sec-08 disjoint").
    if re.match(r"^#{1,6}\s", stripped):
        heading_body = re.sub(r"^#+\s*", "", stripped)
        # Count ticket mentions on this heading line.
        mentions = len(list(TICKET_RE.finditer(heading_body)))
        if mentions >= 2 and re.search(r"[∥/,;]|\bvs\b|overlaps\b|shares\b", heading_body):
            return None
        return "heading"

    # Table row that leads with a bold ticket cell: `| **INF40** | ...`
    if re.match(r"^\|\s*\*\*(?:" + TICKET_ALT + r")\d+\*?\*?", stripped):
        return "table-row"

    # Bulleted item that leads with a bold ticket span: `- **INF40** — ...`
    if re.match(r"^[-*+]\s+\*\*(?:" + TICKET_ALT + r")\d+", stripped):
        return "bullet"

    # Also accept numbered list with bold ticket: `1. **INF40** ...`
    if re.match(r"^\d+\.\s+\*\*(?:" + TICKET_ALT + r")\d+", stripped):
        return "bullet"

    return None


def extract_heading_title(line: str, ticket: str) -> str:
    # Strip leading #'s and surrounding whitespace.
    s = re.sub(r"^\s*#+\s*", "", line).strip()
    # Prefer text starting at the ticket mention.
    idx = s.find(ticket)
    if idx >= 0:
        s = s[idx:]
    return s[:140]


def extract_table_title(line: str, _ticket: str) -> str:
    # Pipe-delimited; first cell is the ticket, second cell usually holds
    # the title or description.
    cells = [c.strip() for c in line.split("|")]
    cells = [c for c in cells if c]
    if len(cells) >= 2:
        return cells[1][:140]
    return line.strip()[:140]


def extract_bullet_title(line: str, ticket: str) -> str:
    # Find the bold ticket span and take the remainder of the line.
    m = re.search(
        rf"\*\*\s*{re.escape(ticket)}[^*]*\*\*\s*[-—:–]?\s*(.*)",
        line,
    )
    if m:
        return m.group(1).strip()[:140]
    return line.strip()[:140]


def extract_title(kind: str, line: str, ticket: str) -> str:
    if kind == "heading":
        title = extract_heading_title(line, ticket)
    elif kind == "table-row":
        title = extract_table_title(line, ticket)
    elif kind == "bullet":
        title = extract_bullet_title(line, ticket)
    else:
        title = line.strip()
    title = re.sub(r"[`*_~]", "", title)
    return re.sub(r"\s+", " ", title).strip()


def normalize_title_key(title: str) -> str:
    t = title.lower()
    # Drop ticket phase suffixes that mark workflow stages on the SAME item:
    # "-p0" / "-p1" / "-export" / "-apply" / "-dedup" / "-impl" / "-design".
    t = re.sub(
        r"-(?:p\d+|export|apply|dedup|impl|design|findings|investigation|"
        r"implementation|close|open|fix)\b",
        "",
        t,
    )
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Strip phase / process / status vocabulary. These are metadata about
    # lifecycle, not distinguishing content.
    stopwords = {
        "phase",
        "findings",
        "investigation",
        "implementation",
        "implementations",
        "phase 0",
        "phase 1",
        "phase 2",
        "p0",
        "p1",
        "p2",
        "closed",
        "open",
        "deferred",
        "resolved",
        "cleared",
        "done",
        "pending",
        "wontfix",
        "shipped",
        "live",
        "status",
        "no op",
        "noop",
        "retrofit",
        "the",
        "a",
        "an",
        "for",
        "on",
        "of",
        "to",
        "in",
        "by",
        "and",
        "or",
        "with",
        "per",
        "vs",
    }
    tokens = [w for w in t.split() if w and w not in stopwords and not w.isdigit()]
    return " ".join(tokens)[:80]


def scan(root: Path) -> dict[str, list[Definition]]:
    defs: dict[str, list[Definition]] = defaultdict(list)
    for path in iter_markdown_files(root):
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            kind = line_kind(line)
            if kind is None:
                continue
            seen_on_line: set[str] = set()
            for m in TICKET_RE.finditer(line):
                ticket = normalize_ticket(
                    m.group("prefix"), m.group("num"), m.group("suffix")
                )
                if ticket is None or ticket in seen_on_line:
                    continue
                seen_on_line.add(ticket)
                title = extract_title(kind, line, ticket)
                annotated = bool(ANNOTATION_RE.search(line))
                defs[ticket].append(
                    Definition(
                        file=rel,
                        line=lineno,
                        ticket=ticket,
                        kind=kind,
                        title=title,
                        annotated=annotated,
                    )
                )
    return defs


def group_distinct(defs_for_ticket: list[Definition]) -> list[list[Definition]]:
    buckets: dict[str, list[Definition]] = defaultdict(list)
    for d in defs_for_ticket:
        buckets[normalize_title_key(d.title) or "(empty)"].append(d)
    # Merge buckets where one key is substring of another.
    keys = sorted(buckets, key=len, reverse=True)
    merged: dict[str, list[Definition]] = {}
    consumed: set[str] = set()
    for k in keys:
        if k in consumed:
            continue
        bucket = list(buckets[k])
        for k2 in keys:
            if k2 == k or k2 in consumed:
                continue
            if k2 and k2 in k:
                bucket.extend(buckets[k2])
                consumed.add(k2)
        merged[k] = bucket
        consumed.add(k)
    return list(merged.values())


def prefix_of(ticket: str) -> str:
    m = re.match(r"^([A-Za-z]+-?)", ticket)
    return m.group(1) if m else ticket


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true", help="suppress prefix summary")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if candidate reuse is detected",
    )
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    defs = scan(root)

    by_prefix: dict[str, set[int]] = defaultdict(set)
    for ticket in defs:
        m = re.match(r"^([A-Za-z]+-?)(\d+)([a-z]?)$", ticket)
        if m:
            # Treat base number and sub-letter variants as the same slot for
            # gap analysis (INF40, INF40a, INF40b all count as "40").
            by_prefix[m.group(1)].add(int(m.group(2)))

    if not args.quiet:
        total_files = sum(1 for _ in iter_markdown_files(root))
        print("=== Ticket Number Audit ===")
        print(f"Scanned {total_files} markdown files")
        print(f"Distinct ticket numbers with definitions: {len(defs)}")
        print()
        print("--- Prefix usage + gaps ---")
        for prefix in sorted(by_prefix):
            nums = sorted(by_prefix[prefix])
            if not nums:
                continue
            lo, hi = nums[0], nums[-1]
            missing = sorted(set(range(lo, hi + 1)) - set(nums))
            gap_note = f"  gaps: {missing}" if missing else ""
            print(f"  {prefix:6s}  count={len(nums):3d}  range=[{lo}..{hi}]{gap_note}")
        print()

    # Candidate reuse: same ticket, two or more distinct normalized titles,
    # spanning different files (single-file dupes are usually reformatting).
    print("--- Candidate number reuse (≥2 distinct titles) ---")
    any_reuse = False
    for ticket in sorted(defs):
        if ticket in DUAL_CLOSURE_EXCEPTIONS:
            continue
        unannotated = [d for d in defs[ticket] if not d.annotated]
        groups = group_distinct(unannotated)
        if len(groups) < 2:
            continue
        # Require at least two groups to each have a strong definition (heading
        # or table-row) to qualify as a candidate. Plain bullets are common
        # for status-update mentions and produce noise.
        strong_groups = [
            g for g in groups if any(d.kind in {"heading", "table-row"} for d in g)
        ]
        if len(strong_groups) < 2:
            continue
        any_reuse = True
        print(f"\n{ticket}  — {len(strong_groups)} distinct titles")
        for group in strong_groups:
            # Pick the first definition as the canonical title.
            sample = group[0]
            print(f"  • [{sample.kind}] {sample.title}")
            locs = sorted({(d.file, d.line) for d in group})
            for f, ln in locs[:3]:
                print(f"      {f}:{ln}")
            if len(locs) > 3:
                print(f"      (+{len(locs) - 3} more)")

    if not any_reuse:
        print("  (none)")
        print()
        return 0

    print()
    print("Review the flagged tickets above. True reuse should be retired and")
    print("re-issued under a fresh number — see docs/REVIEW_CHECKLIST.md § Ticket")
    print("Number Discipline.")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
