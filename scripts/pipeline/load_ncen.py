"""load_ncen.py — SourcePipeline for N-CEN adviser-series mappings (w2-04).

Absorbs ``scripts/fetch_ncen.py`` into a ``SourcePipeline`` subclass on
``ncen_adviser_map``. First migration using
``amendment_strategy = scd_type2``.

N-CEN is the annual census filing for registered investment companies.
Each filing enumerates the managed fund series and the investment
advisers / sub-advisers attached to each series. The mapping is a
slowly-changing reference table keyed naturally on
``(series_id, adviser_crd, role)`` — the expanded form of the
``(series_id, adviser_crd)`` originally considered, needed because a
small number of real rows have the same adviser in both the
``adviser`` and ``subadviser`` roles for the same series (verified
during planning against the live 11,209-row prod population —
12 such groups).

Amendment semantics: when an existing (series, adviser, role) tuple
re-appears with any changed attribute, the base class flips the prior
row's ``valid_to = CURRENT_TIMESTAMP`` and inserts the new row with
``valid_from = NOW()`` and ``valid_to = DATE '9999-12-31'``. Migration
017 adds those columns and backfills every pre-existing row to the
open interval.

Scope options:
  * ``{}`` (empty)                 — sweep every fund CIK in
                                    ``fund_universe`` that is not
                                    already represented by a complete
                                    manifest row.
  * ``{"ciks": [12345, 67890]}``   — explicit list of registrant CIKs
                                    (bypasses the ``fund_universe``
                                    filter).
  * ``{"since": "2026-01-01"}``    — date floor. The N-CEN submissions
                                    feed is per-CIK rather than
                                    per-date, so this is applied
                                    client-side against the
                                    ``filing_date`` of the most recent
                                    N-CEN hit.

Post-promote hooks (override of ``promote()``):
  1. ``_update_managers_adviser_cik`` — fuzzy-matches adviser names to
     ``managers.manager_name``, writing the CRD into
     ``managers.adviser_cik``. Brand-token gate (INF17b) rejects
     matches that share a fuzzy-score ≥85 but no brand-token overlap.
  2. ``_check_routing_drift`` — compares freshly-loaded sub-adviser
     routings against any manual ``decision_maker_v1`` entries in
     ``entity_rollup_history`` and logs drift to
     ``logs/ncen_routing_drift.log`` for human review.

QC:
  * BLOCK: zero rows parsed after fetch.
  * BLOCK: duplicate ``(series_id, adviser_crd, role)`` inside a single
    staged batch.
  * FLAG: staged rows with NULL/empty ``adviser_crd`` — filtered out of
    the typed staging table (SCD keys cannot be NULL).
  * FLAG: CRD present in staging but absent from ``adv_managers``.

The ``scripts/fetch_ncen.py`` script is retired to
``scripts/retired/`` in the same commit.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import date, datetime
from typing import Any, Optional

import duckdb
from lxml import etree  # type: ignore[import-not-found]
from rapidfuzz import fuzz  # type: ignore[import-not-found]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from config import SEC_HEADERS  # noqa: E402
from pipeline.base import (  # noqa: E402
    FetchResult, ParseResult, PromoteResult, SourcePipeline,
    ValidationResult,
)
from pipeline.shared import sec_fetch  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NS = {"n": "http://www.sec.gov/edgar/ncen"}

# INF17b brand-token gate (mirrors build_managers.py / fetch_ncen.py).
_BRAND_STOPWORDS = frozenset({
    "llc", "lp", "inc", "ltd", "co", "corp", "fund", "capital", "management",
    "advisors", "partners", "holdings", "group", "the", "and", "of", "asset",
    "investment", "financial", "services", "wealth",
})


def _brand_tokens(name: Optional[str]) -> set[str]:
    if not name:
        return set()
    raw = re.split(r"[^a-z0-9]+", str(name).lower())
    return {t for t in raw if len(t) >= 3 and t not in _BRAND_STOPWORDS}


def _brand_tokens_overlap(a: Optional[str], b: Optional[str]) -> bool:
    ta = _brand_tokens(a)
    tb = _brand_tokens(b)
    return bool(ta and tb and (ta & tb))


# ---------------------------------------------------------------------------
# Target table spec (column list for ncen_adviser_map — no row_id on this table)
# ---------------------------------------------------------------------------

_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("registrant_cik",    "VARCHAR"),
    ("registrant_name",   "VARCHAR"),
    ("adviser_name",      "VARCHAR"),
    ("adviser_sec_file",  "VARCHAR"),
    ("adviser_crd",       "VARCHAR"),
    ("adviser_lei",       "VARCHAR"),
    ("role",              "VARCHAR"),
    ("series_id",         "VARCHAR"),
    ("series_name",       "VARCHAR"),
    ("report_date",       "DATE"),
    ("filing_date",       "DATE"),
    ("loaded_at",         "TIMESTAMP"),
    ("valid_from",        "TIMESTAMP"),
    ("valid_to",          "DATE"),
]


_STG_RAW_DDL = """
CREATE TABLE IF NOT EXISTS stg_ncen_raw (
    registrant_cik    VARCHAR,
    registrant_name   VARCHAR,
    adviser_name      VARCHAR,
    adviser_sec_file  VARCHAR,
    adviser_crd       VARCHAR,
    adviser_lei       VARCHAR,
    role              VARCHAR,
    series_id         VARCHAR,
    series_name       VARCHAR,
    report_date       DATE,
    filing_date       DATE,
    accession_number  VARCHAR,
    fetched_at        TIMESTAMP
)
"""


_STG_TARGET_DDL = (
    "CREATE TABLE ncen_adviser_map (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)


# ---------------------------------------------------------------------------
# EDGAR helpers (ported from retired fetch_ncen.py)
# ---------------------------------------------------------------------------

def _find_ncen_filing(cik: str) -> Optional[dict]:
    """Locate the most recent N-CEN filing for a registrant CIK.

    Returns a metadata dict on success, ``None`` if no N-CEN is on file
    or the SEC submissions endpoint returns an error.
    """
    padded_cik = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{padded_cik}.json"
    try:
        resp, _ = sec_fetch(url, headers=SEC_HEADERS, max_retries=3, timeout=60)
    except Exception:  # pylint: disable=broad-except
        return None
    try:
        data = resp.json()
    except Exception:  # pylint: disable=broad-except
        return None

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    dates = recent.get("filingDate", [])

    for i, form in enumerate(forms):
        if form == "N-CEN":
            return {
                "accession": accs[i],
                "primary_doc": docs[i],
                "filing_date": dates[i],
                "registrant_name": data.get("name", ""),
                "registrant_cik": padded_cik,
            }
    return None


def _download_ncen_xml(cik_raw: str, accession: str, primary_doc: str) -> Optional[bytes]:
    """Download the N-CEN primary XML. Tries the canonical
    ``primary_doc.xml`` path first, falls back to the filing manifest's
    ``primary_doc`` if the canonical path 404s."""
    cik_num = str(cik_raw).lstrip("0") or "0"
    acc_path = accession.replace("-", "")

    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_num}/"
        f"{acc_path}/primary_doc.xml"
    )
    try:
        resp, _ = sec_fetch(url, headers=SEC_HEADERS, max_retries=3, timeout=60)
        return resp.content
    except Exception:  # pylint: disable=broad-except
        pass

    clean_doc = (primary_doc or "").split("/")[-1]
    if not clean_doc:
        return None
    url2 = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_path}/{clean_doc}"
    try:
        resp, _ = sec_fetch(url2, headers=SEC_HEADERS, max_retries=3, timeout=60)
        return resp.content
    except Exception:  # pylint: disable=broad-except
        return None


def _parse_ncen_xml(xml_content: bytes, filing_info: dict) -> list[dict]:
    """Parse N-CEN XML into a flat list of adviser/subadviser → series rows.

    Zip-pairing logic mirrors the retired ``fetch_ncen.py``: the i-th
    ``managementInvestmentQuestion`` block is paired with the i-th
    ``investmentAdviser`` block and (independently) the i-th
    ``subAdviser`` block.
    """
    try:
        root = etree.fromstring(xml_content)  # pylint: disable=c-extension-no-member
    except etree.XMLSyntaxError:  # pylint: disable=c-extension-no-member
        return []

    registrant_cik = filing_info["registrant_cik"]
    registrant_name = filing_info["registrant_name"]
    filing_date = filing_info["filing_date"]
    accession = filing_info.get("accession")

    report_date = root.findtext(".//n:reportPeriodDate", namespaces=NS) or filing_date
    miq_elements = root.findall(".//n:managementInvestmentQuestion", NS)
    adviser_elements = root.findall(".//n:investmentAdviser", NS)
    subadviser_elements = root.findall(".//n:subAdviser", NS)

    records: list[dict] = []

    def _emit(role: str, name: str, sec_file: str, crd: str, lei: str,
              series_id: str, series_name: str) -> None:
        if not name:
            return
        records.append({
            "registrant_cik": registrant_cik,
            "registrant_name": registrant_name,
            "adviser_name": name,
            "adviser_sec_file": sec_file,
            "adviser_crd": crd,
            "adviser_lei": lei,
            "role": role,
            "series_id": series_id,
            "series_name": series_name,
            "report_date": report_date,
            "filing_date": filing_date,
            "accession_number": accession,
        })

    for i, miq in enumerate(miq_elements):
        series_id = miq.findtext("n:mgmtInvSeriesId", namespaces=NS) or ""
        series_name = miq.findtext("n:mgmtInvFundName", namespaces=NS) or ""

        if i < len(adviser_elements):
            adv = adviser_elements[i]
            _emit(
                "adviser",
                adv.findtext("n:investmentAdviserName", namespaces=NS) or "",
                adv.findtext("n:investmentAdviserFileNo", namespaces=NS) or "",
                adv.findtext("n:investmentAdviserCrdNo", namespaces=NS) or "",
                adv.findtext("n:investmentAdviserLei", namespaces=NS) or "",
                series_id, series_name,
            )

        if i < len(subadviser_elements):
            sub = subadviser_elements[i]
            _emit(
                "subadviser",
                sub.findtext("n:subAdviserName", namespaces=NS) or "",
                sub.findtext("n:subAdviserFileNo", namespaces=NS) or "",
                sub.findtext("n:subAdviserCrdNo", namespaces=NS) or "",
                sub.findtext("n:subAdviserLei", namespaces=NS) or "",
                series_id, series_name,
            )

    return records


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class LoadNCENPipeline(SourcePipeline):
    """SourcePipeline for N-CEN adviser-series mappings.

    First concrete ``scd_type2`` subclass in the framework. Migration 017
    adds ``valid_from`` and ``valid_to`` to ``ncen_adviser_map``; this
    class relies on the base-class ``_promote_scd_type2`` for row
    flipping + insertion.
    """

    name = "ncen_advisers"
    target_table = "ncen_adviser_map"
    amendment_strategy = "scd_type2"
    amendment_key = ("series_id", "adviser_crd", "role")

    def __init__(self, *, limit: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._limit = limit

    # ---- target_table_spec --------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": ["series_id", "adviser_crd", "role", "valid_to"],
            "indexes": [
                ["series_id", "adviser_crd", "role", "valid_to"],
                ["registrant_cik"],
                ["adviser_crd"],
            ],
        }

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        t0 = time.monotonic()

        staging_con.execute(_STG_RAW_DDL)

        cik_filter = scope.get("ciks")
        since = scope.get("since")

        if cik_filter:
            ciks = [str(c).strip().zfill(10) for c in cik_filter]
        else:
            ciks = self._universe_ciks()

        if self._limit is not None:
            ciks = ciks[: self._limit]

        already_staged = {
            r[0] for r in staging_con.execute(
                "SELECT DISTINCT registrant_cik FROM stg_ncen_raw"
            ).fetchall() if r[0]
        }

        rows_staged = 0
        now = datetime.utcnow()
        for idx, cik in enumerate(ciks):
            if cik in already_staged:
                continue

            filing = self._find_filing(cik)
            if not filing:
                continue

            if since and filing.get("filing_date") and filing["filing_date"] < since:
                continue

            xml = self._download_xml(cik, filing["accession"], filing["primary_doc"])
            if not xml:
                continue

            records = self._parse_xml(xml, filing)
            if not records:
                continue

            # Within-batch dedupe: replace any prior staged rows for this
            # registrant so the typed-staging parse step does not see
            # overlapping historical CIK batches.
            staging_con.execute(
                "DELETE FROM stg_ncen_raw WHERE registrant_cik = ?",
                [filing["registrant_cik"]],
            )
            payload = [
                [
                    r["registrant_cik"], r["registrant_name"],
                    r["adviser_name"], r["adviser_sec_file"],
                    r["adviser_crd"], r["adviser_lei"],
                    r["role"], r["series_id"], r["series_name"],
                    r["report_date"], r["filing_date"],
                    r["accession_number"], now,
                ]
                for r in records
            ]
            staging_con.executemany(
                """
                INSERT INTO stg_ncen_raw (
                    registrant_cik, registrant_name,
                    adviser_name, adviser_sec_file,
                    adviser_crd, adviser_lei,
                    role, series_id, series_name,
                    report_date, filing_date,
                    accession_number, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )
            rows_staged += len(records)

            if (idx + 1) % 25 == 0:
                staging_con.execute("CHECKPOINT")

        staging_con.execute("CHECKPOINT")

        return FetchResult(
            run_id="",
            rows_staged=rows_staged,
            raw_tables=["stg_ncen_raw"],
            duration_seconds=time.monotonic() - t0,
        )

    # Overridable for tests.
    def _find_filing(self, cik: str) -> Optional[dict]:
        return _find_ncen_filing(cik)

    def _download_xml(
        self, cik: str, accession: str, primary_doc: str,
    ) -> Optional[bytes]:
        return _download_ncen_xml(cik, accession, primary_doc)

    def _parse_xml(self, xml: bytes, filing_info: dict) -> list[dict]:
        return _parse_ncen_xml(xml, filing_info)

    def _universe_ciks(self) -> list[str]:
        """Pull the fund-CIK universe from prod (read-only)."""
        prod_ro = duckdb.connect(self._prod_db_path, read_only=True)
        try:
            rows = prod_ro.execute(
                "SELECT DISTINCT fund_cik FROM fund_universe "
                "WHERE fund_cik IS NOT NULL ORDER BY fund_cik"
            ).fetchall()
        finally:
            prod_ro.close()
        return [r[0] for r in rows]

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        t0 = time.monotonic()

        staging_con.execute("DROP TABLE IF EXISTS ncen_adviser_map")
        staging_con.execute(_STG_TARGET_DDL)

        # Count empties BEFORE the filtered insert so we can surface them
        # as a FLAG. NULL/empty adviser_crd cannot participate in SCD
        # promote (the natural key must be non-null on every column).
        empty_crd = staging_con.execute(
            "SELECT COUNT(*) FROM stg_ncen_raw "
            "WHERE adviser_crd IS NULL OR adviser_crd = ''"
        ).fetchone()[0]

        staging_con.execute(
            """
            INSERT INTO ncen_adviser_map (
                registrant_cik, registrant_name,
                adviser_name, adviser_sec_file,
                adviser_crd, adviser_lei,
                role, series_id, series_name,
                report_date, filing_date,
                loaded_at, valid_from, valid_to
            )
            SELECT
                s.registrant_cik, s.registrant_name,
                s.adviser_name, s.adviser_sec_file,
                s.adviser_crd, s.adviser_lei,
                s.role, s.series_id, s.series_name,
                s.report_date, s.filing_date,
                NOW() AS loaded_at,
                NOW() AS valid_from,
                DATE '9999-12-31' AS valid_to
            FROM stg_ncen_raw s
            WHERE s.adviser_crd IS NOT NULL
              AND s.adviser_crd <> ''
              AND s.series_id IS NOT NULL
              AND s.series_id <> ''
            """
        )
        staging_con.execute("CHECKPOINT")

        rows_parsed = staging_con.execute(
            "SELECT COUNT(*) FROM ncen_adviser_map"
        ).fetchone()[0]

        qc_failures: list[dict] = []
        if empty_crd:
            qc_failures.append({
                "field": "adviser_crd",
                "rule": f"{empty_crd}_rows_null_adviser_crd",
                "severity": "FLAG",
            })

        if rows_parsed == 0:
            qc_failures.append({
                "field": "_", "rule": "zero_rows_parsed", "severity": "BLOCK",
            })

        # Key-uniqueness guard inside this batch. Same key appearing
        # twice in a single staged run would cascade into duplicate
        # open-row sentinels after promote — BLOCK.
        dup = staging_con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT series_id, adviser_crd, role, COUNT(*) AS n "
            "  FROM ncen_adviser_map "
            "  GROUP BY 1, 2, 3 "
            "  HAVING COUNT(*) > 1"
            ") t"
        ).fetchone()[0]
        if dup:
            qc_failures.append({
                "field": "_",
                "rule": f"{dup}_dup_keys_in_batch",
                "severity": "BLOCK",
            })

        return ParseResult(
            run_id="",
            rows_parsed=int(rows_parsed),
            target_staging_table=self.target_table,
            qc_failures=qc_failures,
            duration_seconds=time.monotonic() - t0,
        )

    # ---- validate ------------------------------------------------------

    def validate(self, staging_con: Any, prod_con: Any) -> ValidationResult:
        vr = ValidationResult()

        staged_count = staging_con.execute(
            "SELECT COUNT(*) FROM ncen_adviser_map"
        ).fetchone()[0]
        if staged_count == 0:
            # No-op run (no new N-CEN filings discovered). Allow through
            # so the state machine still completes cleanly.
            return vr

        # Duplicate natural key within the batch — cannot promote.
        dupes = staging_con.execute(
            """
            SELECT series_id, adviser_crd, role, COUNT(*) AS n
              FROM ncen_adviser_map
             GROUP BY 1, 2, 3
            HAVING COUNT(*) > 1
             LIMIT 20
            """
        ).fetchall()
        for sid, crd, role, n in dupes:
            vr.blocks.append(f"dup_key:{sid}:{crd}:{role}:{n}")

        # FLAG: staged CRD not present in adv_managers (non-fatal — the
        # CRD might simply have not been loaded yet from ADV).
        try:
            unknown = prod_con.execute(
                """
                SELECT COUNT(DISTINCT s.adviser_crd)
                  FROM (
                    SELECT DISTINCT adviser_crd FROM ncen_adviser_map
                     WHERE adviser_crd IS NOT NULL AND adviser_crd <> ''
                  ) AS s
                  LEFT JOIN adv_managers a ON a.crd_number = s.adviser_crd
                 WHERE a.crd_number IS NULL
                """
            ).fetchone()[0]
        except Exception as exc:  # pylint: disable=broad-except
            vr.flags.append(f"adv_lookup_skipped:{exc}")
            unknown = 0
        if unknown:
            vr.flags.append(f"crd_not_in_adv_managers:{unknown}")

        return vr

    # ---- promote (override for post-promote hooks) --------------------

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        """Delegate SCD promote to base class, then run post-promote hooks
        in the same prod connection / transaction boundary:

          1. Fuzzy-match adviser_name → managers.manager_name and stamp
             ``managers.adviser_cik`` with the CRD (INF17b gate).
          2. Routing-drift check against ``entity_rollup_history`` manual
             decision_maker_v1 routings.
        """
        result = super().promote(run_id, prod_con)

        # Post-promote hooks. Failures here are logged — they are
        # bookkeeping side-effects, not correctness gates.
        try:
            self._update_managers_adviser_cik(prod_con)
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("_update_managers_adviser_cik: %s", exc)
        try:
            self._check_routing_drift(prod_con)
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("_check_routing_drift: %s", exc)

        return result

    @staticmethod
    def _has_table(con: Any, table_name: str) -> bool:
        try:
            con.execute(f"SELECT 1 FROM {table_name} LIMIT 0")  # nosec B608
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def _update_managers_adviser_cik(self, con: Any) -> None:
        """Fuzzy-match ncen adviser_name → managers.manager_name and
        stamp managers.adviser_cik with the normalized CRD. Brand-token
        gate (INF17b) rejects lexically-close but semantically-distinct
        firm-name pairs."""
        if not self._has_table(con, "managers"):
            self._logger.info(
                "_update_managers_adviser_cik: managers table not present — skip"
            )
            return

        try:
            con.execute("ALTER TABLE managers ADD COLUMN adviser_cik VARCHAR")
        except Exception:  # nosec B110 — column already exists on re-runs
            pass

        advisers = con.execute(
            """
            SELECT DISTINCT adviser_name, adviser_crd
              FROM ncen_adviser_map
             WHERE adviser_name IS NOT NULL AND adviser_name <> ''
               AND valid_to = DATE '9999-12-31'
            """
        ).fetchall()
        managers = con.execute(
            "SELECT cik, manager_name FROM managers"
        ).fetchall()

        rejections_path = os.path.join(BASE_DIR, "logs", "fetch_ncen_rejected_crds.csv")
        os.makedirs(os.path.dirname(rejections_path), exist_ok=True)
        matched = 0
        rejected = 0
        with open(rejections_path, "w", encoding="utf-8", newline="") as rej_file:
            rej_writer = csv.writer(rej_file)
            rej_writer.writerow(
                ["adviser_name", "adviser_crd", "matched_cik",
                 "matched_name", "score", "reason"],
            )
            for adv_name, adv_crd in advisers:
                if not adv_name or not adv_crd:
                    continue
                best_score = 0
                best_mgr_cik = None
                best_mgr_name = None
                adv_upper = adv_name.upper()
                for mgr_cik, mgr_name in managers:
                    if not mgr_name:
                        continue
                    score = fuzz.token_sort_ratio(adv_upper, mgr_name.upper())
                    if score > best_score:
                        best_score = score
                        best_mgr_cik = mgr_cik
                        best_mgr_name = mgr_name
                if best_score >= 85 and best_mgr_cik is not None:
                    if not _brand_tokens_overlap(adv_name, best_mgr_name):
                        rej_writer.writerow(
                            [adv_name, adv_crd, best_mgr_cik, best_mgr_name,
                             best_score, "brand_token_mismatch"],
                        )
                        rejected += 1
                        continue
                    # INF4b — strip leading zeros for the stored form.
                    norm_crd = str(adv_crd).lstrip("0") or "0"
                    con.execute(
                        "UPDATE managers "
                        "SET adviser_cik = ? "
                        "WHERE cik = ? AND adviser_cik IS NULL",
                        [norm_crd, best_mgr_cik],
                    )
                    matched += 1
        self._logger.info(
            "_update_managers_adviser_cik: matched=%d rejected=%d (log=%s)",
            matched, rejected, rejections_path,
        )

    def _check_routing_drift(self, con: Any) -> None:
        """Log any series where N-CEN now reports a sub-adviser that
        differs from the manual ``decision_maker_v1`` routing."""
        try:
            drifted = con.execute(
                """
                SELECT
                    erh.entity_id,
                    ei.identifier_value AS series_id,
                    ea_current.alias_name AS current_routing,
                    ncen.adviser_name    AS ncen_current,
                    erh.rule_applied,
                    erh.review_due_date
                  FROM entity_rollup_history erh
                  JOIN entity_aliases ea_current
                    ON erh.rollup_entity_id = ea_current.entity_id
                   AND ea_current.is_preferred = TRUE
                   AND ea_current.valid_to = '9999-12-31'
                  JOIN entity_identifiers ei
                    ON erh.entity_id = ei.entity_id
                   AND ei.identifier_type = 'series_id'
                   AND ei.valid_to = '9999-12-31'
                  LEFT JOIN ncen_adviser_map ncen
                    ON ei.identifier_value = ncen.series_id
                   AND ncen.role = 'subadviser'
                   AND ncen.valid_to = DATE '9999-12-31'
                 WHERE erh.rollup_type = 'decision_maker_v1'
                   AND erh.routing_confidence IN ('low', 'medium')
                   AND erh.valid_to = '9999-12-31'
                   AND ncen.adviser_name IS NOT NULL
                   AND LOWER(TRIM(ea_current.alias_name))
                       != LOWER(TRIM(ncen.adviser_name))
                """
            ).fetchall()
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.info("_check_routing_drift: skipped (%s)", exc)
            return

        if not drifted:
            return

        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "ncen_routing_drift.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as fh:
            for entity_id, sid, current, ncen_current, rule, due in drifted:
                fh.write(
                    f"{ts}|{entity_id}|{sid}|{current}|{ncen_current}|"
                    f"{rule}|{due}\n"
                )
        self._logger.info(
            "_check_routing_drift: %d drifted series — logged to %s",
            len(drifted), log_path,
        )

    # ---- cleanup override (drop N-CEN raw staging too) ----------------

    def _cleanup_staging(self, run_id: str) -> None:
        super()._cleanup_staging(run_id)
        try:
            staging_con = duckdb.connect(self._staging_db_path)
            try:
                staging_con.execute("DROP TABLE IF EXISTS stg_ncen_raw")
                staging_con.execute("CHECKPOINT")
            finally:
                staging_con.close()
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("cleanup N-CEN staging: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cli(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="N-CEN SourcePipeline (w2-04)")
    parser.add_argument(
        "--ciks", nargs="+", type=str,
        help="Registrant CIKs to fetch (bypasses fund_universe filter)",
    )
    parser.add_argument(
        "--since",
        help="Filing-date floor (YYYY-MM-DD). Filings older than this are skipped.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap total CIKs processed (useful for smoke tests).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Run through pending_approval; don't promote")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Promote immediately after run() succeeds")
    parser.add_argument("--staging", action="store_true",
                        help="Use staging DB as prod target")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_cli(argv)

    prod_path: Optional[str] = None
    if args.staging:
        from db import STAGING_DB  # type: ignore[import-not-found]
        prod_path = STAGING_DB

    pipeline = LoadNCENPipeline(
        limit=args.limit,
        prod_db_path=prod_path,
    )

    scope: dict = {}
    if args.ciks:
        scope["ciks"] = args.ciks
    if args.since:
        # Validate format early; SEC's filing_date is YYYY-MM-DD.
        try:
            date.fromisoformat(args.since)
        except ValueError as exc:
            raise SystemExit(f"--since must be YYYY-MM-DD: {exc}") from exc
        scope["since"] = args.since

    run_id = pipeline.run(scope)
    print(f"run_id: {run_id}")

    if args.dry_run:
        print(
            f"Dry run complete. Call approve_and_promote({run_id!r}) "
            f"from the admin UI/REPL when ready."
        )
        return 0

    if args.auto_approve:
        result = pipeline.approve_and_promote(run_id)
        print(
            f"Promoted run_id={run_id}: "
            f"inserted={result.rows_inserted} flipped={result.rows_flipped}"
        )
    else:
        print(
            f"Run {run_id} ready for approval. Call "
            f"approve_and_promote({run_id!r}) or re-run with --auto-approve."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
