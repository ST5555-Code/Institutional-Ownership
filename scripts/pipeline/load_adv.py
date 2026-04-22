"""load_adv.py — SourcePipeline for SEC bulk ADV registered-adviser data (w2-05).

Absorbs ``scripts/fetch_adv.py`` (download + parse + strategy
classification + activist flagging) and ``scripts/promote_adv.py``
(whole-table DELETE+INSERT + manifest/impacts mirror) into a single
``SourcePipeline`` subclass on ``adv_managers``.

Amendment strategy ``direct_write`` keyed on ``(crd_number,)``. ADV has
no partitioning grain — one run re-parses the full SEC bulk ZIP, so the
correct semantics is "replace the prior universe". The base-class
``_promote_direct_write`` path deletes per-key then inserts, which is
semantically equivalent to the legacy whole-table replace for a run
whose staged set covers the full universe; we override ``promote()`` to
do a single DELETE-all + INSERT-all for efficiency (16.6K rows, one
round trip) while still recording per-key ``upsert`` impacts so the
rollback pathway remains uniform.

Scope options:
  * ``{}``                                — download the latest SEC ADV
                                             bulk ZIP
  * ``{"zip_path": "/path/to/adv.zip"}``  — use a local ZIP instead
                                             of downloading

Validation gates:
  * BLOCK — staged row count is zero
  * WARN  — staged row count differs more than ±10% from prod
  * FLAG  — CRD rows with zero ``adv_5f_raum`` (informational)

Reference tables ``cik_crd_direct`` and ``lei_reference`` are **not**
touched by this pipeline — they live under ``build_managers.py`` and
``build_fund_classes.py`` respectively and are populated from entirely
different sources. A future consolidation may move them here.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from typing import Any, Optional

import duckdb
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from config import SEC_HEADERS  # noqa: E402
from pipeline.base import (  # noqa: E402
    FetchResult, ParseResult, PromoteResult, SourcePipeline,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Config — mirrored from legacy fetch_adv.py
# ---------------------------------------------------------------------------

ADV_ZIP_URL = (
    "https://www.sec.gov/files/investment/data/other/"
    "information-about-registered-investment-advisers-exempt-reporting-advisers/"
    "ia030226.zip"
)

# Ported verbatim from fetch_adv.py so behaviour is identical to the
# legacy script for the first run under the framework.
ACTIVIST_NAMES = [
    "Elliott Investment Management",
    "Elliott Management",
    "Icahn Capital",
    "Icahn Enterprises",
    "Starboard Value",
    "ValueAct Capital",
    "ValueAct Holdings",
    "Jana Partners",
    "Engine No. 1",
    "Engine No 1",
    "Third Point",
    "Pershing Square",
    "Corvex Management",
    "Legion Partners",
    "Land & Buildings",
    "Land and Buildings",
    "Sachem Head",
    "Barington Capital",
    "Blue Harbour",
    "Blue Harbor",
    "Ancora Holdings",
    "Ancora Advisors",
]

PASSIVE_KEYWORDS = ["INDEX", "ETF", "S&P", "RUSSELL", "MSCI", "PASSIVE"]
HEDGE_FUND_KEYWORDS = ["CAPITAL PARTNERS", "MASTER FUND", "OFFSHORE", "CAYMAN"]
QUANT_KEYWORDS = [
    "QUANT", "SYSTEMATIC", "ALGORITHMIC", "AQR", "TWO SIGMA",
    "RENAISSANCE", "DE SHAW", "WINTON",
]
MULTI_STRAT_KEYWORDS = ["MULTI-STRATEGY", "MULTI STRATEGY", "DIVERSIFIED"]
PE_KEYWORDS = ["PRIVATE EQUITY", "BUYOUT", "VENTURE", "GROWTH EQUITY"]

SEC_DELAY = 0.5


# ---------------------------------------------------------------------------
# Target table spec — ordered list of (column, type) for adv_managers.
# ---------------------------------------------------------------------------

_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("crd_number",                 "VARCHAR"),
    ("sec_file_number",            "VARCHAR"),
    ("cik",                        "VARCHAR"),
    ("firm_name",                  "VARCHAR"),
    ("legal_name",                 "VARCHAR"),
    ("city",                       "VARCHAR"),
    ("state",                      "VARCHAR"),
    ("address",                    "VARCHAR"),
    ("adv_5f_raum",                "DOUBLE"),
    ("adv_5f_raum_discrtnry",      "DOUBLE"),
    ("adv_5f_raum_non_discrtnry",  "DOUBLE"),
    ("adv_5f_num_accts",           "BIGINT"),
    ("pct_discretionary",          "DOUBLE"),
    ("strategy_inferred",          "VARCHAR"),
    ("is_activist",                "BOOLEAN"),
    ("has_hedge_funds",            "VARCHAR"),
    ("has_pe_funds",               "VARCHAR"),
    ("has_vc_funds",               "VARCHAR"),
]

_TARGET_COLUMN_NAMES = [c for c, _ in _TARGET_TABLE_COLUMNS]

_STG_TARGET_DDL = (
    "CREATE TABLE adv_managers (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)

_STG_RAW_DDL = (
    "CREATE TABLE IF NOT EXISTS stg_adv_raw (\n    "
    + ",\n    ".join(f"{c} {t}" for c, t in _TARGET_TABLE_COLUMNS)
    + "\n)"
)


# ---------------------------------------------------------------------------
# Parse helpers — lifted from fetch_adv.py with thin edits for testability.
# ---------------------------------------------------------------------------

def _classify_strategy(row: dict) -> str:
    name = str(row.get("firm_name", "")).upper()
    pct = row.get("pct_discretionary") or 0
    has_hf = str(row.get("has_hedge_funds", "")).upper() == "Y"
    has_pe = str(row.get("has_pe_funds", "")).upper() == "Y"
    has_vc = str(row.get("has_vc_funds", "")).upper() == "Y"

    if any(kw in name for kw in PASSIVE_KEYWORDS) or pct < 10:
        return "passive"
    if has_hf or any(kw in name for kw in HEDGE_FUND_KEYWORDS):
        return "hedge_fund"
    if any(kw in name for kw in QUANT_KEYWORDS):
        return "quantitative"
    if any(kw in name for kw in MULTI_STRAT_KEYWORDS):
        return "multi_strategy"
    if has_pe or has_vc or any(kw in name for kw in PE_KEYWORDS):
        return "private_equity"
    if pct >= 80:
        return "active"
    return "unknown"


def _flag_activists(df: pd.DataFrame) -> pd.DataFrame:
    df["is_activist"] = False
    for activist_name in ACTIVIST_NAMES:
        pattern = activist_name.upper()
        mask = df["firm_name"].astype(str).str.upper().str.contains(
            pattern, na=False, regex=False,
        )
        df.loc[mask, "is_activist"] = True
    return df


def _parse_csv_bytes(csv_bytes: bytes) -> pd.DataFrame:
    """Parse the ADV CSV into the typed adv_managers DataFrame.

    Pure function — takes raw CSV bytes, returns the final DataFrame
    with all 18 target columns filled in. Unit tests build CSV bytes
    in memory and exercise this function directly.
    """
    df_raw = pd.read_csv(
        io.BytesIO(csv_bytes),
        low_memory=False,
        dtype=str,
        encoding="latin-1",
    )
    col_map = {
        "Organization CRD#":              "crd_number",
        "SEC#":                           "sec_file_number",
        "CIK#":                           "cik",
        "Primary Business Name":          "firm_name",
        "Legal Name":                     "legal_name",
        "Main Office City":               "city",
        "Main Office State":              "state",
        "Main Office Street Address 1":   "address",
        "5F(2)(a)":                       "adv_5f_raum_discrtnry",
        "5F(2)(b)":                       "adv_5f_raum_non_discrtnry",
        "5F(2)(c)":                       "adv_5f_raum",
        "5F(2)(f)":                       "adv_5f_num_accts",
        "Any Hedge Funds":                "has_hedge_funds",
        "Any PE Funds":                   "has_pe_funds",
        "Any VC Funds":                   "has_vc_funds",
    }
    available = {k: v for k, v in col_map.items() if k in df_raw.columns}
    df = df_raw[list(available.keys())].rename(columns=available).copy()

    for col in (
        "adv_5f_raum",
        "adv_5f_raum_discrtnry",
        "adv_5f_raum_non_discrtnry",
        "adv_5f_num_accts",
    ):
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("$", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["pct_discretionary"] = 0.0
    if "adv_5f_raum" in df.columns:
        mask = df["adv_5f_raum"] > 0
        df.loc[mask, "pct_discretionary"] = (
            df.loc[mask, "adv_5f_raum_discrtnry"]
            / df.loc[mask, "adv_5f_raum"] * 100
        ).round(2)

    df["strategy_inferred"] = df.apply(
        lambda r: _classify_strategy(r.to_dict()), axis=1,
    )
    df = _flag_activists(df)

    for col, _typ in _TARGET_TABLE_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # adv_5f_num_accts is BIGINT in prod; coerce now so pandas->DuckDB
    # INSERT keeps the integer column type rather than promoting to DOUBLE.
    if "adv_5f_num_accts" in df.columns:
        df["adv_5f_num_accts"] = (
            pd.to_numeric(df["adv_5f_num_accts"], errors="coerce")
              .fillna(0).astype("int64")
        )
    df["is_activist"] = df["is_activist"].astype(bool)

    return df[_TARGET_COLUMN_NAMES].copy()


def _extract_csv_from_zip(zip_bytes: bytes) -> bytes:
    """Return the first .csv member of an ADV bulk ZIP as bytes."""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    csv_names = [n for n in z.namelist() if n.upper().endswith(".CSV")]
    if not csv_names:
        raise FileNotFoundError(
            f"No CSV found in ADV ZIP. Members: {z.namelist()}"
        )
    with z.open(csv_names[0]) as src:
        return src.read()


def _download_adv_zip() -> bytes:
    resp = requests.get(ADV_ZIP_URL, headers=SEC_HEADERS, timeout=120)
    resp.raise_for_status()
    time.sleep(SEC_DELAY)
    return resp.content


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class LoadADVPipeline(SourcePipeline):
    """SourcePipeline for SEC bulk ADV registered-adviser data.

    Whole-universe refresh — one run parses the full SEC ADV bulk ZIP.
    ``direct_write`` semantics: staged rows replace prod ``adv_managers``
    in a single transaction, keyed on ``crd_number``.
    """

    name = "adv_registrants"
    target_table = "adv_managers"
    amendment_strategy = "direct_write"
    amendment_key = ("crd_number",)

    # ---- target_table_spec --------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": ["crd_number"],
            "indexes": [["crd_number"], ["cik"], ["sec_file_number"]],
        }

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        t0 = time.monotonic()
        zip_path = scope.get("zip_path")

        if zip_path:
            with open(zip_path, "rb") as fh:
                zip_bytes = fh.read()
        else:
            zip_bytes = _download_adv_zip()

        csv_bytes = _extract_csv_from_zip(zip_bytes)

        # Stash raw rows in an intermediate staging table so parse()
        # can re-hydrate without re-downloading. The DataFrame could be
        # passed via instance state, but keeping it on disk matches the
        # 8-step flow and makes re-runs from parse() onward idempotent.
        df = _parse_csv_bytes(csv_bytes)

        staging_con.execute(_STG_RAW_DDL)
        staging_con.execute("DELETE FROM stg_adv_raw")
        staging_con.register("adv_df", df)
        try:
            col_list = ", ".join(_TARGET_COLUMN_NAMES)
            staging_con.execute(
                f"INSERT INTO stg_adv_raw ({col_list}) "  # nosec B608
                f"SELECT {col_list} FROM adv_df"
            )
        finally:
            staging_con.unregister("adv_df")

        staging_con.execute("CHECKPOINT")

        return FetchResult(
            run_id="",
            rows_staged=len(df),
            raw_tables=["stg_adv_raw"],
            duration_seconds=time.monotonic() - t0,
        )

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        t0 = time.monotonic()

        staging_con.execute(f"DROP TABLE IF EXISTS {self.target_table}")
        staging_con.execute(_STG_TARGET_DDL)

        col_list = ", ".join(_TARGET_COLUMN_NAMES)
        staging_con.execute(
            f"INSERT INTO {self.target_table} ({col_list}) "  # nosec B608
            f"SELECT {col_list} FROM stg_adv_raw"
        )
        staging_con.execute("CHECKPOINT")

        rows_parsed = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table}"  # nosec B608
        ).fetchone()[0]

        qc_failures: list[dict] = []
        if rows_parsed == 0:
            qc_failures.append({
                "field": "_", "rule": "zero_rows_parsed", "severity": "BLOCK",
            })

        missing_aum = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE adv_5f_raum IS NULL OR adv_5f_raum = 0"
        ).fetchone()[0]
        if missing_aum:
            qc_failures.append({
                "field": "adv_5f_raum",
                "rule": f"{missing_aum}_rows_missing_aum",
                "severity": "FLAG",
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

        try:
            staged_count = staging_con.execute(
                f"SELECT COUNT(*) FROM {self.target_table}"  # nosec B608
            ).fetchone()[0]
        except Exception:  # pylint: disable=broad-except
            staged_count = 0

        if staged_count == 0:
            vr.blocks.append("adv_staging_empty")
            return vr

        try:
            prod_count = prod_con.execute(
                f"SELECT COUNT(*) FROM {self.target_table}"  # nosec B608
            ).fetchone()[0]
        except Exception:  # pylint: disable=broad-except
            prod_count = 0

        if prod_count > 0:
            delta_pct = abs(staged_count - prod_count) / prod_count * 100
            if delta_pct > 10.0:
                vr.warns.append(
                    f"row_count_delta={delta_pct:.1f}% "
                    f"(staged={staged_count}, prod={prod_count})"
                )

        missing_crd = staging_con.execute(
            f"SELECT COUNT(*) FROM {self.target_table} "  # nosec B608
            f"WHERE crd_number IS NULL OR crd_number = ''"
        ).fetchone()[0]
        if missing_crd:
            vr.flags.append(f"missing_crd_number:{missing_crd}")

        return vr

    # ---- promote (override for whole-universe replace) ----------------

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        """Whole-table replace — matches legacy promote_adv.py semantics.

        ADV publishes a complete universe each run, so replacing prod
        with staged in a single transaction is both semantically correct
        and cheaper than the base class per-key DELETE loop (16K rows).
        We still record one ``upsert`` impact per CRD so rollback through
        ``ingestion_impacts`` is uniform across pipelines.
        """
        rows = self._read_staged_rows()
        if rows.empty:
            return PromoteResult(run_id=run_id)

        manifest_id = self._manifest_id_for_run(prod_con, run_id)
        col_list = ", ".join(rows.columns)

        prod_con.execute("BEGIN TRANSACTION")
        try:
            prod_con.execute(f"DELETE FROM {self.target_table}")  # nosec B608
            prod_con.register("staged_rows", rows)
            try:
                prod_con.execute(
                    f"INSERT INTO {self.target_table} "  # nosec B608
                    f"({col_list}) SELECT {col_list} FROM staged_rows"
                )
            finally:
                prod_con.unregister("staged_rows")

            for crd in rows["crd_number"].dropna().drop_duplicates().tolist():
                self.record_impact(
                    prod_con, manifest_id=manifest_id, run_id=run_id,
                    action="upsert", rowkey={"crd_number": crd},
                )

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        return PromoteResult(
            run_id=run_id,
            rows_upserted=len(rows),
        )

    # ---- cleanup override (drop raw staging too) ----------------------

    def _cleanup_staging(self, run_id: str) -> None:
        super()._cleanup_staging(run_id)
        try:
            staging_con = duckdb.connect(self._staging_db_path)
            try:
                staging_con.execute("DROP TABLE IF EXISTS stg_adv_raw")
                staging_con.execute("CHECKPOINT")
            finally:
                staging_con.close()
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning("cleanup ADV staging: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cli(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ADV SourcePipeline (w2-05)",
    )
    parser.add_argument("--zip", help="Local ADV ZIP file (skip download)")
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

    pipeline = LoadADVPipeline(prod_db_path=prod_path)

    scope: dict = {}
    if args.zip:
        scope["zip_path"] = args.zip

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
            f"upserted={result.rows_upserted}"
        )
    else:
        print(
            f"Run {run_id} ready for approval. Call "
            f"approve_and_promote({run_id!r}) or re-run with --auto-approve."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
