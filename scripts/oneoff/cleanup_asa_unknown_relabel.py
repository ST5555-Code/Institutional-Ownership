#!/usr/bin/env python3
"""cleanup_asa_unknown_relabel.py — cef-asa-flip-and-relabel
(closes the ASA Gold side of cef-residual-cleanup, last residual after
PR #250's ADX cleanup).

Per docs/findings/cef_asa_prep_investigation.md (commit 79350a5), the
350 ASA Gold (CIK 0001230869) UNKNOWN rows in fund_holdings_v2 are
byte-identical to the 3 corresponding NPORT-P primary_doc.xml filings
($0.00 per-period delta). The data is already in place; only the
series_id label is wrong. PR-B is therefore a flip-and-relabel
operation, not a fetch-and-load.

Two-step cleanup, executed in a single transaction:
  Op A: INSERT 350 new fund_holdings_v2 rows with
        series_id='SYN_0001230869', is_latest=TRUE, real ASA N-PORT
        accession_number, and fund-level attribution copied from the
        existing 2025-11 SYN_0001230869 precedent (fund_name,
        family_name, entity_id, rollup_entity_id, dm_*); holding-level
        columns (cusip/isin/issuer_name/shares/mv/etc.) copied
        verbatim from the matching UNKNOWN row.
  Op B: UPDATE the 350 UNKNOWN rows to is_latest=FALSE.

Fund-level attribution override rationale: the UNKNOWN-side rows
carry entity_id=11278 (a fund-typed entity literally named 'N/A'
that rolls up to entity_id=63 = 'Calamos Investments'). The existing
2025-11 SYN_0001230869 row carries entity_id=26793, the canonical
ASA institution self-rollup. Literally copying 'all other column
values' from UNKNOWN would propagate the Calamos misattribution
into the new SYN rows and feed bad rollup into peer_rotation_flows.
The override mirrors the 2025-11 SYN precedent. Manifest column
``entity_id_correction='11278→26793'`` records the change per row.

Pattern precedent: scripts/oneoff/cleanup_adx_unknown_duplicates.py
(PR #250). Differs in two structural ways:
  1. ASA UNKNOWN rows have NO live SYN_0001230869 companion for the
     3 target periods (2024-11, 2025-02, 2025-08). The byte-identical
     check anchors against parsed N-PORT XML, not against an existing
     SYN_ row. The 2025-11 SYN row is informational only; out of
     scope per asa-2025-11-syn-source-investigation roadmap entry.
  2. ASA holds many foreign micro-cap miners with no US CUSIP
     (cusip='N/A'). Matching anchor is (report_date, isin) primary,
     (report_date, issuer_name) fallback for null-ISIN rows. Within a
     group, both sides are sorted by market_value_usd desc and zipped
     by rank to handle multi-lot duplicates (e.g. 2025-02
     CA7660871004 has 3 rows for Ridgeline Minerals Corp at distinct
     fair-value levels).

ingestion_manifest registration: NOT required. The existing 2025-11
SYN_0001230869 row is not registered in ingestion_manifest, neither
are the UNKNOWN-side rows, and there is no FK between
fund_holdings_v2.accession_number and ingestion_manifest. Mirrors
2025-11 SYN precedent.

Modes:
  --dry-run  (default) — fetches 3 N-PORT XMLs, builds manifest CSV +
             dryrun findings MD; no DB writes.
  --confirm  — reads manifest CSV, executes INSERT 350 + UPDATE 350
             in single transaction. Refuses if any HOLD rows.

Outputs:
  data/working/asa_unknown_relabel_manifest.csv
  docs/findings/cef_residual_cleanup_asa_dryrun.md   (dry-run)
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import requests

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = BASE_DIR / "data" / "13f.duckdb"
MANIFEST_CSV = BASE_DIR / "data" / "working" / "asa_unknown_relabel_manifest.csv"
DRYRUN_DOC = BASE_DIR / "docs" / "findings" / "cef_residual_cleanup_asa_dryrun.md"

# Path-based local imports (mirrors scripts/oneoff/cef_asa_prep_inspect.py).
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.path.insert(0, str(BASE_DIR / "scripts" / "pipeline"))

from config import EDGAR_IDENTITY  # noqa: E402
from nport_parsers import parse_nport_xml  # noqa: E402

ASA_CIK = "0001230869"
SYN_SERIES_ID = "SYN_0001230869"
EXPECTED_ROW_COUNT = 350
EXPECTED_AUM_USD = 1_752_484_930.87
TOLERANCE = 0.05  # 5% drift gate on row count + AUM
ROW_DELTA_THRESHOLD_USD = 0.01  # per-row MV delta beyond this → MISMATCH/HOLD

# ASA accessions matching UNKNOWN periods, confirmed via edgartools
# Company('0001230869').get_filings(form=['NPORT-P']) on 2026-05-02 in
# scripts/oneoff/cef_asa_prep_inspect.py (commit 79350a5).
ASA_ACCESSIONS: dict[str, str] = {
    "2024-11": "0001752724-25-018310",
    "2025-02": "0001752724-25-075250",
    "2025-08": "0001230869-25-000013",
}

# Canonical fund-level attribution from existing 2025-11 SYN_0001230869
# row. Override target for new rows; UNKNOWN-side carries the wrong
# entity_id=11278/dm_rollup_name='Calamos Investments' and must NOT be
# propagated. See script header for rationale.
SYN_FUND_NAME = "ASA Gold and Precious Metals LTD Fund"
SYN_FAMILY_NAME = "ASA GOLD & PRECIOUS METALS LTD"
SYN_ENTITY_ID = 26793
SYN_ROLLUP_ENTITY_ID = 26793
SYN_DM_ENTITY_ID = 26793
SYN_DM_ROLLUP_ENTITY_ID = 26793
SYN_DM_ROLLUP_NAME = "ASA Gold and Precious Metals LTD Fund"

UNKNOWN_ENTITY_ID = 11278  # for entity_id_correction audit column

EDGAR_HEADERS = {"User-Agent": EDGAR_IDENTITY}
NPORT_URL_FMT = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dashes}/primary_doc.xml"
)


# ---------------------------------------------------------------------------
# Phase 1 — re-validate cohort (1.1, 1.2, 1.3, 1.5)
# ---------------------------------------------------------------------------

def validate_cohort(con: duckdb.DuckDBPyConnection) -> dict:
    # 1.1 + 1.2 cohort + period coverage
    by_period = con.execute(
        f"""
        SELECT report_month, COUNT(*) AS n, SUM(market_value_usd) AS aum
        FROM fund_holdings_v2
        WHERE fund_cik = '{ASA_CIK}'
          AND series_id = 'UNKNOWN'
          AND is_latest = TRUE
        GROUP BY report_month
        ORDER BY report_month
        """
    ).fetchall()
    cohort_periods = {r[0]: {"rows": int(r[1]), "aum": float(r[2] or 0.0)} for r in by_period}
    row_count = sum(p["rows"] for p in cohort_periods.values())
    aum_usd = sum(p["aum"] for p in cohort_periods.values())

    def diverged(actual, expected, tol):
        if expected == 0:
            return actual != 0
        return abs(actual - expected) / expected > tol

    if diverged(row_count, EXPECTED_ROW_COUNT, TOLERANCE) or diverged(
        aum_usd, EXPECTED_AUM_USD, TOLERANCE
    ):
        raise SystemExit(
            f"ABORT: ASA UNKNOWN cohort drifted from investigation baseline "
            f"(>{int(TOLERANCE*100)}%). observed=(rows={row_count:,}, "
            f"aum=${aum_usd:,.2f}); expected=({EXPECTED_ROW_COUNT:,}, "
            f"~${EXPECTED_AUM_USD:,.2f})."
        )

    expected_periods = set(ASA_ACCESSIONS.keys())
    actual_periods = set(cohort_periods.keys())
    if expected_periods != actual_periods:
        raise SystemExit(
            f"ABORT: period coverage drift. expected={sorted(expected_periods)}, "
            f"actual={sorted(actual_periods)}."
        )

    # 1.3 SYN companion check: must NOT exist for the 3 target periods.
    syn_in_target = con.execute(
        f"""
        SELECT report_month, COUNT(*)
        FROM fund_holdings_v2
        WHERE fund_cik = '{ASA_CIK}'
          AND series_id = '{SYN_SERIES_ID}'
          AND is_latest = TRUE
          AND report_month IN ({','.join("'" + p + "'" for p in ASA_ACCESSIONS)})
        GROUP BY report_month
        """
    ).fetchall()
    if syn_in_target:
        raise SystemExit(
            f"ABORT: SYN_{ASA_CIK} companion exists for target period(s) "
            f"{[r[0] for r in syn_in_target]}. Relabel would create duplicates."
        )

    # 1.5 Accession verification
    acc_rows = con.execute(
        f"""
        SELECT report_month, accession_number
        FROM fund_holdings_v2
        WHERE fund_cik = '{ASA_CIK}'
          AND series_id = 'UNKNOWN'
          AND is_latest = TRUE
        GROUP BY report_month, accession_number
        ORDER BY report_month
        """
    ).fetchall()
    for period, acc in acc_rows:
        expected_prefix = f"BACKFILL_MIG015_UNKNOWN_{period}"
        if acc != expected_prefix:
            raise SystemExit(
                f"ABORT: unexpected accession_number on UNKNOWN cohort "
                f"({period}={acc!r}). Expected {expected_prefix!r}."
            )

    return {
        "row_count": row_count,
        "aum_usd": aum_usd,
        "by_period": cohort_periods,
    }


# ---------------------------------------------------------------------------
# Phase 1.4 — fetch N-PORT XMLs and parse
# ---------------------------------------------------------------------------

def _fetch_nport_xml(period: str, accession: str) -> tuple[dict, list[dict]]:
    cik_int = ASA_CIK.lstrip("0") or "0"
    url = NPORT_URL_FMT.format(cik_int=cik_int, acc_no_dashes=accession.replace("-", ""))
    time.sleep(0.2)  # SEC fair-access throttle
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
    resp.raise_for_status()
    metadata, holdings = parse_nport_xml(resp.content)
    if metadata is None or holdings is None:
        raise SystemExit(
            f"ABORT: parse_nport_xml returned None for {period} ({accession})."
        )
    return metadata, holdings


def fetch_nport_holdings() -> dict[str, dict]:
    """Fetch + parse the 3 ASA N-PORT XMLs. Returns
    {period: {'metadata': {...}, 'holdings': [...]}}.
    """
    out: dict[str, dict] = {}
    for period, accession in ASA_ACCESSIONS.items():
        metadata, holdings = _fetch_nport_xml(period, accession)
        out[period] = {
            "metadata": metadata,
            "holdings": holdings,
            "accession": accession,
        }
    return out


# ---------------------------------------------------------------------------
# Phase 2 — build per-row manifest with byte-identical classification
# ---------------------------------------------------------------------------

def _isin_clean(s) -> str:
    if s is None:
        return ""
    return str(s).strip()


def build_manifest(
    con: duckdb.DuckDBPyConnection, nport: dict[str, dict]
) -> list[dict]:
    """For each ASA UNKNOWN row, find its byte-identical N-PORT match
    by (report_date, isin) primary or (report_date, issuer_name)
    fallback. Within each group, both sides are sorted by mv desc and
    zipped by rank to handle multi-lot duplicates.

    Classification:
      byte_identical — match found, |delta| <= ROW_DELTA_THRESHOLD_USD
      mismatch       — match found, |delta| >  ROW_DELTA_THRESHOLD_USD
      orphan         — no match found
    Action: FLIP_AND_RELABEL iff byte_identical, else HOLD.
    """
    # Pull all UNKNOWN rows + the columns we need to copy through.
    unknown_rows = con.execute(
        f"""
        SELECT report_month, report_date, quarter, accession_number,
               cusip, isin, issuer_name, ticker, asset_category,
               shares_or_principal, market_value_usd, pct_of_nav,
               fair_value_level, is_restricted, payoff_profile,
               fund_strategy_at_filing, row_id
        FROM fund_holdings_v2
        WHERE fund_cik = '{ASA_CIK}'
          AND series_id = 'UNKNOWN'
          AND is_latest = TRUE
        ORDER BY report_month
        """
    ).fetchall()

    cols = [
        "report_month", "report_date", "quarter", "accession_number",
        "cusip", "isin", "issuer_name", "ticker", "asset_category",
        "shares_or_principal", "market_value_usd", "pct_of_nav",
        "fair_value_level", "is_restricted", "payoff_profile",
        "fund_strategy_at_filing", "row_id",
    ]
    unknown = [dict(zip(cols, r)) for r in unknown_rows]

    # Build N-PORT lookup, mirroring how UNKNOWN rows are grouped: each
    # holding indexed under (period, isin) if it carries an ISIN, else
    # under (period, issuer_name). UNKNOWN rows use the same key
    # (isin → primary, issuer_name → null-ISIN fallback). Per-period
    # totals match exactly per investigation (commit 79350a5), so each
    # group on the UNKNOWN side has a corresponding group on the N-PORT
    # side; within a group, both sides are sorted by mv desc and zipped
    # by rank to handle multi-lot duplicates.
    from collections import defaultdict
    nport_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for period, payload in nport.items():
        for h in payload["holdings"]:
            isin = _isin_clean(h.get("isin"))
            name = (h.get("name") or "").strip()
            mv = float(h.get("val_usd") or 0.0)
            key_kind = "isin" if isin else "name"
            key = (period, key_kind, isin if isin else name)
            nport_groups[key].append({"isin": isin, "name": name, "val_usd": mv})
    for grp in nport_groups.values():
        grp.sort(key=lambda x: x["val_usd"], reverse=True)

    unk_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for u in unknown:
        period = u["report_month"]
        isin = _isin_clean(u["isin"])
        name = (u["issuer_name"] or "").strip()
        key_kind = "isin" if isin else "name"
        key = (period, key_kind, isin if isin else name)
        unk_groups[key].append(u)
    for grp in unk_groups.values():
        grp.sort(key=lambda x: float(x["market_value_usd"] or 0.0), reverse=True)

    manifest: list[dict] = []

    def classify_row(u: dict, nport_match: dict | None, match_basis: str) -> dict:
        period = u["report_month"]
        accession_new = ASA_ACCESSIONS[period]
        unk_mv = float(u["market_value_usd"] or 0.0)
        if nport_match is None:
            syn_match = "orphan"
            mv_delta = None
            nport_mv = None
            action = "HOLD"
        else:
            nport_mv = float(nport_match["val_usd"])
            mv_delta = unk_mv - nport_mv
            if abs(mv_delta) <= ROW_DELTA_THRESHOLD_USD:
                syn_match = "byte_identical"
                action = "FLIP_AND_RELABEL"
            else:
                syn_match = "mismatch"
                action = "HOLD"
        return {
            "row_id": u["row_id"],
            "report_month": period,
            "report_date": u["report_date"].isoformat(),
            "accession_number_old": u["accession_number"],
            "accession_number_new": accession_new,
            "cusip": u["cusip"],
            "isin": u["isin"] or "",
            "issuer_name": u["issuer_name"] or "",
            "shares_or_principal": float(u["shares_or_principal"] or 0.0),
            "market_value_usd_unknown": unk_mv,
            "market_value_usd_nport": nport_mv if nport_mv is not None else "",
            "mv_delta": mv_delta if mv_delta is not None else "",
            "match_basis": match_basis,
            "syn_match": syn_match,
            "entity_id_correction": f"{UNKNOWN_ENTITY_ID}→{SYN_ENTITY_ID}",
            "action": action,
        }

    # Rank-zip each UNKNOWN group against its corresponding N-PORT group.
    for key, unk_group in unk_groups.items():
        nport_group = nport_groups.get(key, [])
        match_basis = "isin" if key[1] == "isin" else "issuer_name"
        for i, u in enumerate(unk_group):
            n = nport_group[i] if i < len(nport_group) else None
            manifest.append(classify_row(u, n, match_basis if n else "orphan"))

    # Stable sort for deterministic CSV output
    manifest.sort(key=lambda r: (r["report_date"], r["isin"], r["issuer_name"], -r["market_value_usd_unknown"]))
    return manifest


def write_manifest_csv(manifest: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "row_id",
        "report_month",
        "report_date",
        "accession_number_old",
        "accession_number_new",
        "cusip",
        "isin",
        "issuer_name",
        "shares_or_principal",
        "market_value_usd_unknown",
        "market_value_usd_nport",
        "mv_delta",
        "match_basis",
        "syn_match",
        "entity_id_correction",
        "action",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in manifest:
            row = dict(r)
            # numeric formatting for the manifest
            row["market_value_usd_unknown"] = f"{r['market_value_usd_unknown']:.2f}"
            if r["market_value_usd_nport"] != "":
                row["market_value_usd_nport"] = f"{r['market_value_usd_nport']:.2f}"
            if r["mv_delta"] != "":
                row["mv_delta"] = f"{r['mv_delta']:.6f}"
            row["shares_or_principal"] = f"{r['shares_or_principal']:.4f}"
            w.writerow(row)


def write_dryrun_doc(
    manifest: list[dict],
    cohort: dict,
    nport: dict[str, dict],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    by_match = {"byte_identical": 0, "mismatch": 0, "orphan": 0}
    by_action = {"FLIP_AND_RELABEL": 0, "HOLD": 0}
    by_match_aum = {"byte_identical": 0.0, "mismatch": 0.0, "orphan": 0.0}
    period_action_aum: dict[tuple[str, str], float] = {}
    for r in manifest:
        by_match[r["syn_match"]] += 1
        by_action[r["action"]] += 1
        by_match_aum[r["syn_match"]] += r["market_value_usd_unknown"]
        key = (r["report_month"], r["action"])
        period_action_aum[key] = period_action_aum.get(key, 0.0) + r["market_value_usd_unknown"]

    # Per-period delta sanity (unknown_total - nport_total)
    period_delta = []
    for period, payload in nport.items():
        unk_sum = cohort["by_period"][period]["aum"]
        nport_sum = sum(float(h.get("val_usd") or 0.0) for h in payload["holdings"])
        period_delta.append((period, unk_sum, nport_sum, unk_sum - nport_sum))

    lines: list[str] = []
    lines.append("# cef-residual-cleanup-asa — Phase 2 dry-run manifest")
    lines.append("")
    lines.append(f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_")
    lines.append("")
    lines.append("## Cohort re-validation (Phase 1.1–1.3, 1.5)")
    lines.append("")
    lines.append(
        f"- ASA Gold (CIK `{ASA_CIK}`) UNKNOWN rows with `is_latest=TRUE`: "
        f"**{cohort['row_count']:,}**"
    )
    lines.append(f"- AUM (sum of market_value_usd): **${cohort['aum_usd']:,.2f}**")
    lines.append(
        f"- SYN_{ASA_CIK} companion rows with `is_latest=TRUE` for target periods: **0** (verified)"
    )
    lines.append(
        f"- Expected per investigation baseline (commit 79350a5): "
        f"{EXPECTED_ROW_COUNT:,} rows / ~${EXPECTED_AUM_USD:,.2f}. "
        f"Drift gate: ±{int(TOLERANCE*100)}%."
    )
    lines.append("")
    lines.append("### Period coverage")
    lines.append("")
    lines.append("| Period | Accession (old → new) | UNKNOWN rows | UNKNOWN AUM (USD) |")
    lines.append("|---|---|---:|---:|")
    for period in sorted(cohort["by_period"]):
        acc_new = ASA_ACCESSIONS[period]
        rows = cohort["by_period"][period]["rows"]
        aum = cohort["by_period"][period]["aum"]
        lines.append(
            f"| {period} | `BACKFILL_MIG015_UNKNOWN_{period}` → `{acc_new}` | "
            f"{rows:,} | ${aum:,.2f} |"
        )
    lines.append("")
    lines.append("## Phase 1.4 — N-PORT byte-identical re-verification")
    lines.append("")
    lines.append("Per-period delta (UNKNOWN-side total minus N-PORT-side total):")
    lines.append("")
    lines.append("| Period | UNKNOWN MV | N-PORT MV | Delta |")
    lines.append("|---|---:|---:|---:|")
    for period, unk, npm, delta in sorted(period_delta):
        lines.append(f"| {period} | ${unk:,.2f} | ${npm:,.2f} | ${delta:,.6f} |")
    lines.append("")
    lines.append(
        f"Per-row threshold: ≤ ${ROW_DELTA_THRESHOLD_USD} acceptable (rounding noise); "
        f"> ${ROW_DELTA_THRESHOLD_USD} surfaces as MISMATCH and HOLD."
    )
    lines.append("")
    lines.append("Match anchor: `(report_date, isin)` primary, "
                 "`(report_date, issuer_name)` fallback for null-ISIN rows. "
                 "Multi-lot duplicates handled by rank-zip on market_value_usd "
                 "(both sides sorted desc within each (period, key) group).")
    lines.append("")
    lines.append("## Per-row classification")
    lines.append("")
    lines.append("| Classification | Rows | UNKNOWN AUM (USD) | Action |")
    lines.append("|---|---:|---:|---|")
    lines.append(
        f"| **byte_identical** | {by_match['byte_identical']:>4,} | "
        f"${by_match_aum['byte_identical']:,.2f} | FLIP_AND_RELABEL in Phase 3 |"
    )
    lines.append(
        f"| **mismatch**       | {by_match['mismatch']:>4,} | "
        f"${by_match_aum['mismatch']:,.2f} | HOLD — surfaced for chat decision |"
    )
    lines.append(
        f"| **orphan**         | {by_match['orphan']:>4,} | "
        f"${by_match_aum['orphan']:,.2f} | HOLD — no N-PORT match |"
    )
    lines.append("")
    lines.append(
        f"Action totals: **FLIP_AND_RELABEL={by_action['FLIP_AND_RELABEL']:,} rows**, "
        f"HOLD={by_action['HOLD']:,} rows."
    )
    lines.append("")
    lines.append("## Fund-level attribution override")
    lines.append("")
    lines.append(
        "UNKNOWN-side rows carry `entity_id=11278` (fund-typed entity literally "
        f"named `N/A`, rolling up to entity_id=63 = `Calamos Investments`). "
        f"New SYN rows override fund-level columns to match the existing 2025-11 "
        f"`SYN_{ASA_CIK}` precedent: "
        f"`entity_id={SYN_ENTITY_ID}`, `rollup_entity_id={SYN_ROLLUP_ENTITY_ID}`, "
        f"`dm_entity_id={SYN_DM_ENTITY_ID}`, `dm_rollup_entity_id={SYN_DM_ROLLUP_ENTITY_ID}`, "
        f"`dm_rollup_name={SYN_DM_ROLLUP_NAME!r}`, `fund_name={SYN_FUND_NAME!r}`, "
        f"`family_name={SYN_FAMILY_NAME!r}`. Holding-level columns "
        f"(cusip, isin, issuer_name, ticker, asset_category, shares_or_principal, "
        f"market_value_usd, pct_of_nav, fair_value_level, is_restricted, "
        f"payoff_profile, quarter, report_month, report_date, fund_cik, "
        f"fund_strategy_at_filing) copied verbatim from UNKNOWN row. "
        f"Per-row audit trail: manifest column "
        f"`entity_id_correction='{UNKNOWN_ENTITY_ID}→{SYN_ENTITY_ID}'`."
    )
    lines.append("")
    lines.append("## Phase 3 entry gate")
    lines.append("")
    if by_action["HOLD"] > 0:
        lines.append(
            f"**STOP.** {by_action['HOLD']:,} HOLD row(s) require chat decision "
            f"before --confirm can run."
        )
    else:
        lines.append(
            "All rows are FLIP_AND_RELABEL. Phase 3 may proceed with `--confirm`."
        )
    lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Phase 3 — execute INSERT 350 + UPDATE 350 in single transaction
# ---------------------------------------------------------------------------

def load_manifest_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"ABORT: manifest not found at {path}. Run --dry-run first.")
    out: list[dict] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["row_id"] = int(row["row_id"])
            row["market_value_usd_unknown"] = float(row["market_value_usd_unknown"])
            out.append(row)
    return out


def execute_relabel(
    con: duckdb.DuckDBPyConnection,
    manifest: list[dict],
) -> dict:
    flip_rows = [r for r in manifest if r["action"] == "FLIP_AND_RELABEL"]
    hold_rows = [r for r in manifest if r["action"] != "FLIP_AND_RELABEL"]

    if hold_rows:
        raise SystemExit(
            f"ABORT: manifest contains {len(hold_rows)} HOLD row(s). "
            f"Resolve in chat and re-run --dry-run before --confirm."
        )
    if not flip_rows:
        raise SystemExit("ABORT: no FLIP_AND_RELABEL rows in manifest.")

    expected_count = len(flip_rows)
    expected_aum = sum(r["market_value_usd_unknown"] for r in flip_rows)

    # Pre-counts
    pre_unk = con.execute(
        f"""
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE fund_cik='{ASA_CIK}' AND series_id='UNKNOWN' AND is_latest=TRUE
        """
    ).fetchone()
    pre_syn = con.execute(
        f"""
        SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
        FROM fund_holdings_v2
        WHERE fund_cik='{ASA_CIK}' AND series_id='{SYN_SERIES_ID}' AND is_latest=TRUE
        """
    ).fetchone()
    print(
        f"[confirm] pre   UNKNOWN: {pre_unk[0]:,} rows / ${pre_unk[1]:,.2f}; "
        f"SYN_{ASA_CIK}: {pre_syn[0]:,} rows / ${pre_syn[1]:,.2f}"
    )
    print(
        f"[confirm] plan: INSERT {expected_count:,} SYN rows (sum ${expected_aum:,.2f}) "
        f"+ UPDATE {expected_count:,} UNKNOWN rows to is_latest=FALSE"
    )

    flip_row_ids = [r["row_id"] for r in flip_rows]

    con.execute("BEGIN")
    try:
        # Op A: INSERT new SYN rows by SELECTing source UNKNOWN rows by row_id
        # and projecting fund-level overrides + accession remap.
        con.register("flip_row_ids", _row_ids_dataframe(flip_row_ids))
        con.register("acc_map", _acc_map_dataframe(ASA_ACCESSIONS))

        con.execute(
            f"""
            INSERT INTO fund_holdings_v2 (
                fund_cik, fund_name, family_name, series_id,
                quarter, report_month, report_date,
                cusip, isin, issuer_name, ticker, asset_category,
                shares_or_principal, market_value_usd, pct_of_nav,
                fair_value_level, is_restricted, payoff_profile,
                loaded_at, fund_strategy_at_filing,
                entity_id, rollup_entity_id, dm_entity_id, dm_rollup_entity_id,
                dm_rollup_name, row_id, accession_number, is_latest, backfill_quality
            )
            SELECT
                u.fund_cik,
                '{SYN_FUND_NAME}'                AS fund_name,
                '{SYN_FAMILY_NAME}'              AS family_name,
                '{SYN_SERIES_ID}'                AS series_id,
                u.quarter, u.report_month, u.report_date,
                u.cusip, u.isin, u.issuer_name, u.ticker, u.asset_category,
                u.shares_or_principal, u.market_value_usd, u.pct_of_nav,
                u.fair_value_level, u.is_restricted, u.payoff_profile,
                NOW()                            AS loaded_at,
                u.fund_strategy_at_filing,
                {SYN_ENTITY_ID}                  AS entity_id,
                {SYN_ROLLUP_ENTITY_ID}           AS rollup_entity_id,
                {SYN_DM_ENTITY_ID}               AS dm_entity_id,
                {SYN_DM_ROLLUP_ENTITY_ID}        AS dm_rollup_entity_id,
                '{SYN_DM_ROLLUP_NAME}'           AS dm_rollup_name,
                nextval('fund_holdings_v2_row_id_seq') AS row_id,
                am.accession_new                 AS accession_number,
                TRUE                             AS is_latest,
                'relabel_from_unknown'           AS backfill_quality
            FROM fund_holdings_v2 u
            JOIN flip_row_ids f ON f.row_id = u.row_id
            JOIN acc_map am ON am.report_month = u.report_month
            WHERE u.fund_cik='{ASA_CIK}'
              AND u.series_id='UNKNOWN'
              AND u.is_latest=TRUE
            """
        )

        # Op B: UPDATE the source UNKNOWN rows to is_latest=FALSE
        con.execute(
            f"""
            UPDATE fund_holdings_v2
               SET is_latest = FALSE
             WHERE fund_cik = '{ASA_CIK}'
               AND series_id = 'UNKNOWN'
               AND is_latest = TRUE
               AND row_id IN (SELECT row_id FROM flip_row_ids)
            """
        )

        # Sanity checks pre-commit
        post_unk = con.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
            FROM fund_holdings_v2
            WHERE fund_cik='{ASA_CIK}' AND series_id='UNKNOWN' AND is_latest=TRUE
            """
        ).fetchone()
        post_syn = con.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(market_value_usd), 0)
            FROM fund_holdings_v2
            WHERE fund_cik='{ASA_CIK}' AND series_id='{SYN_SERIES_ID}' AND is_latest=TRUE
            """
        ).fetchone()
        unk_delta_rows = pre_unk[0] - post_unk[0]
        syn_delta_rows = post_syn[0] - pre_syn[0]
        syn_delta_aum = float(post_syn[1]) - float(pre_syn[1])

        print(
            f"[confirm] post  UNKNOWN: {post_unk[0]:,} rows / ${post_unk[1]:,.2f} "
            f"(Δ={-unk_delta_rows:+,} rows); SYN: {post_syn[0]:,} rows / "
            f"${post_syn[1]:,.2f} (Δ={syn_delta_rows:+,} rows / ${syn_delta_aum:+,.2f})"
        )

        if unk_delta_rows != expected_count:
            raise SystemExit(
                f"ABORT: UNKNOWN flip count mismatch — expected -{expected_count:,}, "
                f"got -{unk_delta_rows:,}. Rolling back."
            )
        if syn_delta_rows != expected_count:
            raise SystemExit(
                f"ABORT: SYN insert count mismatch — expected +{expected_count:,}, "
                f"got +{syn_delta_rows:,}. Rolling back."
            )
        # AUM conservation: new SYN AUM delta must equal the sum of the flipped
        # UNKNOWN rows' AUM (within $0.01).
        if abs(syn_delta_aum - expected_aum) > 0.01:
            raise SystemExit(
                f"ABORT: AUM conservation failed — SYN insert delta "
                f"${syn_delta_aum:,.2f} vs expected ${expected_aum:,.2f} "
                f"(Δ=${syn_delta_aum - expected_aum:+,.2f}). Rolling back."
            )

        con.execute("COMMIT")
    except SystemExit:
        con.execute("ROLLBACK")
        raise
    except Exception as exc:
        con.execute("ROLLBACK")
        raise SystemExit(f"ABORT: write failed mid-transaction: {exc}") from exc

    return {
        "rows_flipped": expected_count,
        "rows_inserted": expected_count,
        "pre_unknown": (int(pre_unk[0]), float(pre_unk[1])),
        "post_unknown": (int(post_unk[0]), float(post_unk[1])),
        "pre_syn": (int(pre_syn[0]), float(pre_syn[1])),
        "post_syn": (int(post_syn[0]), float(post_syn[1])),
        "syn_aum_delta": syn_delta_aum,
        "expected_aum": expected_aum,
    }


def _row_ids_dataframe(row_ids: list[int]):
    import pandas as pd
    return pd.DataFrame({"row_id": row_ids})


def _acc_map_dataframe(acc_map: dict[str, str]):
    import pandas as pd
    return pd.DataFrame(
        [{"report_month": k, "accession_new": v} for k, v in acc_map.items()]
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true",
                     help="Fetch N-PORT XMLs + build manifest CSV + dryrun MD; no DB writes.")
    grp.add_argument("--confirm", action="store_true",
                     help="Read manifest CSV + execute INSERT+UPDATE in single transaction.")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB),
                        help=f"Path to DuckDB. Default: {DEFAULT_DB}")
    parser.add_argument("--manifest", type=str, default=str(MANIFEST_CSV),
                        help="Manifest CSV path.")
    parser.add_argument("--findings", type=str, default=str(DRYRUN_DOC),
                        help="Dry-run findings markdown path.")
    args = parser.parse_args()

    db_path = Path(args.db)
    manifest_path = Path(args.manifest)
    findings_path = Path(args.findings)

    if args.dry_run:
        # Phase 1 + 1.4 + 2 (read-only)
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            cohort = validate_cohort(con)
            print(
                f"[dry-run] cohort OK: rows={cohort['row_count']:,}, "
                f"aum=${cohort['aum_usd']:,.2f}"
            )
            print("[dry-run] fetching 3 ASA N-PORT XMLs from EDGAR...")
            nport = fetch_nport_holdings()
            for period, payload in nport.items():
                hcount = len(payload["holdings"])
                hsum = sum(float(h.get("val_usd") or 0.0) for h in payload["holdings"])
                print(
                    f"  {period} ({payload['accession']}): "
                    f"{hcount} holdings, total ${hsum:,.2f}"
                )
            manifest = build_manifest(con, nport)
        finally:
            con.close()

        write_manifest_csv(manifest, manifest_path)
        write_dryrun_doc(manifest, cohort, nport, findings_path)

        from collections import Counter
        c = Counter(r["syn_match"] for r in manifest)
        a = Counter(r["action"] for r in manifest)
        print(f"[dry-run] classification: byte_identical={c.get('byte_identical', 0)}, "
              f"mismatch={c.get('mismatch', 0)}, orphan={c.get('orphan', 0)}")
        print(f"[dry-run] action: FLIP_AND_RELABEL={a.get('FLIP_AND_RELABEL', 0)}, "
              f"HOLD={a.get('HOLD', 0)}")
        print(f"[dry-run] manifest CSV: {manifest_path}")
        print(f"[dry-run] dryrun doc:   {findings_path}")
        if a.get("HOLD", 0):
            print("[dry-run] STOP gate: HOLD rows present; --confirm refused "
                  "until manifest is all-FLIP_AND_RELABEL.")
        return

    if args.confirm:
        manifest = load_manifest_csv(manifest_path)
        con = duckdb.connect(str(db_path), read_only=False)
        try:
            cohort = validate_cohort(con)
            print(
                f"[confirm] cohort OK: rows={cohort['row_count']:,}, "
                f"aum=${cohort['aum_usd']:,.2f}"
            )
            stats = execute_relabel(con, manifest)
        finally:
            con.close()
        print(
            f"[confirm] DONE — flipped {stats['rows_flipped']:,} UNKNOWN rows + "
            f"inserted {stats['rows_inserted']:,} SYN_{ASA_CIK} rows. "
            f"AUM conservation Δ=${stats['syn_aum_delta'] - stats['expected_aum']:+,.2f}"
        )
        return


if __name__ == "__main__":
    main()
