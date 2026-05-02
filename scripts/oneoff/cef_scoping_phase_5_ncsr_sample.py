"""
Phase 5 — N-CSR sample fetch & parse-feasibility probe (READ-ONLY).

Pulls 5 N-CSR filings spanning vintages, characterizes structure, attempts
edgartools structured extraction, falls back to HTML/PDF inspection.

NO DB writes. NO mutation. Output goes to stdout; findings written separately.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

# EDGAR identity per CLAUDE.md / project standard
os.environ.setdefault("EDGAR_IDENTITY", "Serge Tismen serge.tismen@gmail.com")

from edgar import Company, set_identity  # noqa: E402

set_identity("Serge Tismen serge.tismen@gmail.com")


SAMPLE = [
    # (CIK, name, vintage_target, vintage_label)
    ("0000002230", "Adams Diversified Equity Fund (ADX)", "latest",        "2024+"),
    ("0001230869", "ASA Gold & Precious Metals Ltd",      "latest",        "2024+"),
    ("0001912938", "First Trust Private Assets Fund",     "latest",        "2024+"),
    ("0001166258", "Pioneer High Income Fund",            "2020-2023",     "mid"),
    ("0000810943", "High Income Securities Fund",         "pre-2020",      "old"),
]


@dataclass
class Probe:
    cik: str
    name: str
    vintage_label: str
    accession: str = ""
    filing_date: str = ""
    period_of_report: str = ""
    primary_doc: str = ""
    n_attachments: int = 0
    attach_types: list[str] = field(default_factory=list)
    has_xml_holdings: bool = False
    obj_type: str = ""
    obj_repr_excerpt: str = ""
    html_doc_size: int = 0
    html_table_count: int = 0
    largest_table_rows: int = 0
    largest_table_cols: int = 0
    holdings_table_hint: bool = False
    pdf_attachments: int = 0
    error: str = ""


def pick_filing(filings, vintage_target: str):
    """Pick a filing matching the vintage target. Returns (filing, note)."""
    if not filings:
        return None, "no N-CSR filings found"
    # filings is iterable; convert to list
    flist = list(filings)
    if not flist:
        return None, "empty filing list"

    def fdate(f):
        return str(getattr(f, "filing_date", ""))

    flist.sort(key=fdate, reverse=True)  # newest first

    if vintage_target == "latest":
        return flist[0], ""
    if vintage_target == "2020-2023":
        for f in flist:
            d = fdate(f)
            if "2020" <= d[:4] <= "2023":
                return f, ""
        return flist[0], f"no 2020-2023 N-CSR; using {fdate(flist[0])}"
    if vintage_target == "pre-2020":
        for f in flist:
            d = fdate(f)
            if d[:4] < "2020":
                return f, ""
        # fallback to earliest
        oldest = sorted(flist, key=fdate)[0]
        return oldest, f"no pre-2020 N-CSR; using earliest {fdate(oldest)}"
    return flist[0], ""


def inspect_html(text: str) -> tuple[int, int, int, bool]:
    """Light HTML table inspection without bs4 dep (best-effort regex).

    Returns (table_count, largest_rows, largest_cols, holdings_hint).
    """
    if not text:
        return 0, 0, 0, False
    # crude regex; good enough for sizing
    tables = re.findall(r"<table\b[^>]*>(.*?)</table>", text, flags=re.IGNORECASE | re.DOTALL)
    largest_rows = 0
    largest_cols = 0
    for t in tables:
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", t, flags=re.IGNORECASE | re.DOTALL)
        nrows = len(rows)
        ncols = 0
        if rows:
            cells = re.findall(r"<t[dh]\b[^>]*>", rows[0], flags=re.IGNORECASE)
            ncols = len(cells)
        if nrows > largest_rows:
            largest_rows = nrows
            largest_cols = ncols
    # holdings hint: look for common SoI keywords near a table
    lower = text.lower()
    holdings_hint = any(
        kw in lower
        for kw in (
            "schedule of investments",
            "schedule of portfolio investments",
            "investments in securities",
            "consolidated schedule of investments",
        )
    )
    return len(tables), largest_rows, largest_cols, holdings_hint


def probe_one(cik: str, name: str, vintage_label: str, vintage_target: str) -> Probe:
    p = Probe(cik=cik, name=name, vintage_label=vintage_label)
    try:
        c = Company(cik)
        # N-CSR (annual) only; skip N-CSRS for this probe
        filings = c.get_filings(form="N-CSR")
        f, note = pick_filing(filings, vintage_target)
        if note:
            p.error = note
        if f is None:
            return p
        p.accession = str(getattr(f, "accession_no", "") or getattr(f, "accession_number", ""))
        p.filing_date = str(getattr(f, "filing_date", ""))
        p.period_of_report = str(getattr(f, "period_of_report", "") or getattr(f, "report_date", ""))
        p.primary_doc = str(getattr(f, "primary_document", ""))

        # Attachments
        try:
            atts = list(f.attachments)
            p.n_attachments = len(atts)
            types = []
            pdf_n = 0
            xml_holdings = False
            for a in atts:
                d = str(getattr(a, "document_type", "") or getattr(a, "type", ""))
                doc = str(getattr(a, "document", "") or getattr(a, "filename", ""))
                types.append(f"{d}:{doc}")
                if doc.lower().endswith(".pdf"):
                    pdf_n += 1
                # any holdings-tagged xml? extremely unlikely for N-CSR but check
                if doc.lower().endswith(".xml") and any(
                    k in doc.lower() for k in ("port", "holding", "schedule")
                ):
                    xml_holdings = True
            p.attach_types = types[:25]  # cap
            p.pdf_attachments = pdf_n
            p.has_xml_holdings = xml_holdings
        except Exception as e:
            p.error = (p.error + f"; attachments err: {e}").strip("; ")

        # obj() probe
        try:
            obj = f.obj()
            p.obj_type = type(obj).__name__
            p.obj_repr_excerpt = repr(obj)[:200]
        except Exception as e:
            p.obj_type = "ERROR"
            p.obj_repr_excerpt = str(e)[:200]

        # primary HTML inspection
        try:
            html = f.html() or ""
            p.html_doc_size = len(html)
            tcount, rmax, cmax, hint = inspect_html(html)
            p.html_table_count = tcount
            p.largest_table_rows = rmax
            p.largest_table_cols = cmax
            p.holdings_table_hint = hint
        except Exception as e:
            p.error = (p.error + f"; html err: {e}").strip("; ")
    except Exception as e:
        p.error = (p.error + f"; outer err: {e}").strip("; ")
    return p


def main():
    results: list[Probe] = []
    for cik, name, target, label in SAMPLE:
        print(f"=== {cik} {name} (target={target}) ===", flush=True)
        p = probe_one(cik, name, label, target)
        results.append(p)
        print(
            f"  accession={p.accession} filed={p.filing_date} period={p.period_of_report}",
            flush=True,
        )
        print(
            f"  attachments={p.n_attachments} pdf={p.pdf_attachments} xml_holdings={p.has_xml_holdings}",
            flush=True,
        )
        print(f"  obj_type={p.obj_type} excerpt={p.obj_repr_excerpt[:120]}", flush=True)
        print(
            f"  html_size={p.html_doc_size} tables={p.html_table_count} largest_rows={p.largest_table_rows} cols={p.largest_table_cols} holdings_hint={p.holdings_table_hint}",
            flush=True,
        )
        if p.error:
            print(f"  NOTE: {p.error}", flush=True)
        # also print first 8 attachment entries
        for t in p.attach_types[:8]:
            print(f"   - {t}", flush=True)
        print("", flush=True)

    # Markdown summary line
    print("\n--- COVERAGE MATRIX ---", flush=True)
    print(
        "| CIK | Vintage | Filed | Accession | obj() | Tables | Largest rows | PDFs | Holdings hint |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for p in results:
        print(
            f"| {p.cik} | {p.vintage_label} | {p.filing_date} | {p.accession} | {p.obj_type} | {p.html_table_count} | {p.largest_table_rows} | {p.pdf_attachments} | {p.holdings_table_hint} |"
        )


if __name__ == "__main__":
    sys.exit(main() or 0)
