"""nport_parsers.py — N-PORT XML parser + fund classifier.

Canonical home for the two shared helpers that multiple N-PORT loaders
need to agree on:

  * ``parse_nport_xml``  — extract fund metadata + per-holding dicts
                           from an N-PORT XML blob.
  * ``classify_fund``     — label a parsed fund (equity / balanced /
                           index / excluded / ...).

Plus the module-global filter-flag they respect:

  * ``_include_index``    — when True, disables the
                           ``INDEX_PATTERNS`` / ``EXCLUDE_PATTERNS``
                           short-circuits inside ``classify_fund``.
                           Callers flip this directly on the module
                           (e.g. ``nport_parsers._include_index = True``);
                           the legacy pattern is preserved intentionally,
                           since ``classify_fund``'s signature is frozen
                           for parity with the pre-extraction call sites.

Extracted from ``scripts/fetch_nport.py`` as part of BLOCK-3 per
``archive/docs/SYSTEM_AUDIT_2026_04_17.md`` §10 and ``archive/docs/SYSTEM_PASS2_2026_04_17.md``
§2. Behaviour preserved bit-for-bit versus the original file so the
pre-audit backup at ``data/backups/13f_backup_20260417_172152`` remains
a valid regression baseline.
"""
from __future__ import annotations

import re
from collections import Counter

from lxml import etree

NS = {"n": "http://www.sec.gov/edgar/nport"}

# Index fund name patterns (excluded from active fund universe)
INDEX_PATTERNS = re.compile(
    r"\b(index|idx|s&p\s*500|russell\s*\d|nasdaq|dow\s*jones|"
    r"total\s*(stock|bond|market)|wilshire|msci|ftse|"
    r"barclays|aggregate|broad\s*market)\b",
    re.IGNORECASE,
)

# ETF / money market / bond-only / fund-of-funds exclusion patterns
EXCLUDE_PATTERNS = re.compile(
    r"\b(etf|exchange[\s-]*traded|money\s*market|"
    r"treasury|government\s*money|prime\s*money|"
    r"fund\s*of\s*funds|master\s*fund|feeder\s*fund)\b",
    re.IGNORECASE,
)

_include_index = False  # set via --include-index flag on fetch_nport.py CLI


def parse_nport_xml(xml_bytes):
    """Parse N-PORT XML. Returns (metadata_dict, list_of_holdings) or (None, None)."""
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return None, None

    gen = root.find(".//n:genInfo", NS)
    fund_info = root.find(".//n:fundInfo", NS)
    if gen is None:
        return None, None

    def get_text(parent, tag):
        el = parent.find(f"n:{tag}", NS)
        return el.text.strip() if el is not None and el.text else None

    metadata = {
        "reg_name": get_text(gen, "regName"),
        "reg_cik": get_text(gen, "regCik"),
        "series_name": get_text(gen, "seriesName"),
        "series_id": get_text(gen, "seriesId"),
        "rep_pd_end": get_text(gen, "repPdEnd"),
        "rep_pd_date": get_text(gen, "repPdDate"),
        "is_final": get_text(gen, "isFinalFiling"),
    }

    if fund_info is not None:
        metadata["net_assets"] = get_text(fund_info, "netAssets")
        metadata["tot_assets"] = get_text(fund_info, "totAssets")

    # Parse holdings
    holdings = []
    for inv in root.findall(".//n:invstOrSec", NS):
        h = {}
        h["name"] = get_text(inv, "name")
        h["cusip"] = get_text(inv, "cusip")
        h["balance"] = get_text(inv, "balance")
        h["units"] = get_text(inv, "units")
        h["val_usd"] = get_text(inv, "valUSD")
        h["pct_val"] = get_text(inv, "pctVal")
        h["payoff_profile"] = get_text(inv, "payoffProfile")
        h["fair_val_level"] = get_text(inv, "fairValLevel")
        h["is_restricted"] = get_text(inv, "isRestrictedSec")

        # Asset category — can be direct element or conditional attribute
        cat_el = inv.find("n:assetCat", NS)
        if cat_el is not None and cat_el.text:
            h["asset_cat"] = cat_el.text.strip()
        else:
            cond = inv.find("n:assetConditional", NS)
            if cond is not None:
                h["asset_cat"] = cond.get("assetCat", "")
            else:
                h["asset_cat"] = ""

        # ISIN — stored as attribute
        isin_el = inv.find(".//n:isin", NS)
        if isin_el is not None:
            h["isin"] = isin_el.get("value", "")
        else:
            h["isin"] = ""

        # Ticker — try multiple paths
        ticker_el = inv.find(".//n:ticker", NS)
        if ticker_el is not None:
            h["ticker"] = ticker_el.get("value", "") or (ticker_el.text or "")
        else:
            h["ticker"] = ""

        # Currency
        h["cur_cd"] = get_text(inv, "curCd") or "USD"

        holdings.append(h)

    return metadata, holdings


def classify_fund(metadata, holdings):
    """Classify a fund. Returns (is_active_equity, fund_category, is_actively_managed).

    is_actively_managed is determined by fund name patterns:
    - Names matching INDEX_PATTERNS (index, ETF, S&P 500, etc.) → False
    - All other equity funds → True
    """
    series_name = (metadata.get("series_name") or metadata.get("reg_name") or "").strip()

    # Determine active vs passive by name (independent of --include-index filter)
    is_passive_name = bool(INDEX_PATTERNS.search(series_name))
    is_actively_managed_flag = not is_passive_name

    # Exclusions (skip index AND ETF filters when --include-index is active)
    if not _include_index and INDEX_PATTERNS.search(series_name):
        return False, "index", False
    if not _include_index and EXCLUDE_PATTERNS.search(series_name):
        return False, "excluded", False
    if metadata.get("is_final") == "Y":
        return False, "final_filing", False

    # Count asset categories
    cats = Counter(h.get("asset_cat", "") for h in holdings)
    total = len(holdings)
    if total == 0:
        return False, "empty", False

    equity_count = cats.get("EC", 0) + cats.get("EP", 0)

    # Compute value-weighted equity percentage
    total_val = sum(float(h.get("val_usd") or 0) for h in holdings)
    equity_val = sum(
        float(h.get("val_usd") or 0)
        for h in holdings
        if h.get("asset_cat") in ("EC", "EP")
    )
    equity_val_pct = equity_val / total_val if total_val > 0 else 0

    # Classify
    if equity_val_pct >= 0.60:
        if equity_val_pct >= 0.90:
            category = "equity"
        else:
            category = "balanced"
        return True, category, is_actively_managed_flag
    elif equity_val_pct >= 0.30:
        return True, "multi_asset", is_actively_managed_flag

    return False, "bond_or_other", False
