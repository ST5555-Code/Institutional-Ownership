"""Unit tests for scripts/hygiene/audit_ticket_numbers.py.

Covers the V10 grouped-row / non-lead-cell fix (scan loop restricts table-row
definitions to tickets in the lead cell) and guards against regression on
existing single-ticket rows and B1 annotation-pattern handling.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "hygiene"))

import audit_ticket_numbers as atn  # noqa: E402


class TestLeadCellTickets:
    def test_single_ticket_lead(self):
        line = "| **DM15e — Prospectus-blocked umbrella trusts** | Gotham | DM6 or DM3 | 7 trusts |"
        assert atn.lead_cell_tickets(line) == {"DM15e"}

    def test_multi_ticket_lead_slash(self):
        line = "| **DM2 / DM3 / DM6** | ADV Schedule 7.B reparse | Pipeline work | deferred |"
        assert atn.lead_cell_tickets(line) == {"DM2", "DM3", "DM6"}

    def test_multi_ticket_lead_whitespace_variants(self):
        line = "|   **DM2/DM3 /   DM6**  | title | extra |"
        assert atn.lead_cell_tickets(line) == {"DM2", "DM3", "DM6"}

    def test_non_lead_tickets_ignored(self):
        line = "| **mig-05** (admin refresh) | P, C | SUPERSEDED (p2-01..p2-10) | stale |"
        assert atn.lead_cell_tickets(line) == {"mig-05"}

    def test_empty_line(self):
        assert atn.lead_cell_tickets("") == set()

    def test_no_tickets_in_lead(self):
        line = "| Item ID / desc | Mentioned in | Status |"
        assert atn.lead_cell_tickets(line) == set()


class TestScanTableRowAttribution:
    """Scan over an in-memory tree and check which tickets get Definitions."""

    def _scan(self, tmp_path: Path, content: str) -> dict[str, list[atn.Definition]]:
        (tmp_path / "sample.md").write_text(content, encoding="utf-8")
        return atn.scan(tmp_path)

    def test_v10_grouped_row_clears_false_positive(self, tmp_path):
        # The V10 regression case: line 152 mentions DM3/DM6 in a non-lead cell
        # and line 153's lead cell groups DM2/DM3/DM6. Pre-fix, DM3 and DM6 each
        # got two "distinct titles" (Gotham, ADV), triggering a spurious reuse
        # flag. Post-fix, only line 153's lead-cell attribution counts.
        content = (
            "| Item | Scope | Blocker | Size |\n"
            "|---|---|---|---|\n"
            "| **DM15e — Prospectus-blocked umbrella trusts** | Gotham | DM6 or DM3 | 7 trusts |\n"
            "| **DM2 / DM3 / DM6** | ADV Schedule 7.B reparse | Pipeline work | deferred |\n"
        )
        defs = self._scan(tmp_path, content)

        # DM15e defined exactly once from line 152's lead cell. The title
        # comes from the second cell per extract_table_title().
        assert len(defs["DM15e"]) == 1
        assert defs["DM15e"][0].title == "Gotham"

        # DM2/DM3/DM6 each defined exactly once, from line 153's multi-ticket lead.
        for t in ("DM2", "DM3", "DM6"):
            assert len(defs[t]) == 1, f"{t} should have exactly one def, got {defs[t]}"
            assert "ADV Schedule" in defs[t][0].title

    def test_single_ticket_row_unchanged(self, tmp_path):
        content = (
            "| Item | Title |\n"
            "|---|---|\n"
            "| **INF45** | L4 schema-parity extension |\n"
        )
        defs = self._scan(tmp_path, content)
        assert len(defs["INF45"]) == 1
        assert defs["INF45"][0].kind == "table-row"
        assert "L4 schema-parity" in defs["INF45"][0].title

    def test_heading_still_captures_all_tickets(self, tmp_path):
        # Headings are NOT affected by the lead-cell filter — cross-reference
        # suppression on headings relies on the separator-heuristic already in
        # line_kind(). A simple single-ticket heading must still register.
        content = "## INF45 schema-parity extension\n"
        defs = self._scan(tmp_path, content)
        assert len(defs["INF45"]) == 1
        assert defs["INF45"][0].kind == "heading"

    def test_bullet_unchanged(self, tmp_path):
        # Bullets are deliberately out of scope for this fix; the classifier
        # only matches bold-labelled bullets, so cross-ref text is already
        # unlikely to introduce phantoms. Confirm at least the canonical
        # bullet still registers its lead ticket.
        content = "- **INF40** — BLOCK-SCHEMA-DIFF retirement\n"
        defs = self._scan(tmp_path, content)
        assert len(defs["INF40"]) == 1
        assert defs["INF40"][0].kind == "bullet"


class TestB1AnnotationPatternIntact:
    """B1 shipped annotation-pattern recognition: `[TICKET #M of K]` on a line
    marks the Definition as ``annotated``, which the reuse reporter filters
    out. This fix must not regress that behaviour."""

    def test_annotation_re_still_matches(self):
        assert atn.ANNOTATION_RE.search("[INF40 #1 of 2 BLOCK-SCHEMA-DIFF]") is not None
        assert atn.ANNOTATION_RE.search("[DM15d #2 of 3 something]") is not None
        assert atn.ANNOTATION_RE.search("INF40 closure note") is None

    def test_annotated_table_row_lead_is_marked(self, tmp_path):
        content = (
            "| Item | Title |\n"
            "|---|---|\n"
            "| **INF40** [INF40 #1 of 2 BLOCK-SCHEMA-DIFF] | first closure |\n"
        )
        (tmp_path / "sample.md").write_text(content, encoding="utf-8")
        defs = atn.scan(tmp_path)
        assert len(defs["INF40"]) == 1
        assert defs["INF40"][0].annotated is True

    def test_dual_closure_exception_still_skipped(self):
        # B1's whitelist — INF40 is never flagged as reuse regardless of how
        # many distinct titles the scanner collects.
        assert "INF40" in atn.DUAL_CLOSURE_EXCEPTIONS
