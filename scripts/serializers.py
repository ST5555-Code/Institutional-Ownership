"""Response-shaping helpers.

Split out of scripts/queries.py in Phase 4 Batch 4-B. All DataFrame →
records conversion, NaN/Inf scrubbing, and filer-name / entity-note
decoration lives here. queries.py imports from this module and re-exports
the two most-consumed helpers (`clean_for_json`, `df_to_records`) so
existing handler imports (`from queries import ...`) keep working without
touching api_*.py files.

Per spec (Phase 4 Batch 4-B): this file holds `clean_for_json()`,
`df_to_records()`, field renaming, and Pydantic schema integration. For
now it's just the shapers — `schemas.py` integration lands in Phase 4-C
(FastAPI) when routers declare `response_model`s.
"""
from __future__ import annotations

import math


# ── NaN / Inf / numpy-type scrubbing ───────────────────────────────────────


def _clean_val(v):
    """Replace NaN/Inf with None; convert numpy types to native Python."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
    # numpy scalar types — convert to native Python
    try:
        import numpy as np  # pylint: disable=import-outside-toplevel
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            if math.isnan(v) or math.isinf(v):
                return None
            return float(v)
        if isinstance(v, np.bool_):
            return bool(v)
    except ImportError:
        pass
    return v


def clean_for_json(data):
    """Recursively clean NaN/Inf/numpy types from dicts and lists."""
    if isinstance(data, list):
        return [{k: _clean_val(v) for k, v in row.items()} if isinstance(row, dict) else row
                for row in data]
    if isinstance(data, dict):
        return {k: clean_for_json(v) if isinstance(v, (dict, list))
                else _clean_val(v)
                for k, v in data.items()}
    return _clean_val(data)


def df_to_records(df):
    """Convert DataFrame to list of dicts with NaN/Inf replaced by None."""
    records = df.to_dict(orient='records')
    return clean_for_json(records)


# ── Filer-name → institutional parent resolution ──────────────────────────


# Known filing agent CIKs — these are not real beneficial owners
_FILING_AGENT_CIKS = {
    '0001104659', '0001193125', '0000902664', '0001445546', '0001213900',
    '0001493152', '0001567619', '0001062993', '0001214659', '0001398344',
    '0001072613', '0001178913', '0001193805', '0001532155', '0000929638',
    '0000950142', '0001140361', '0001564590', '0000950170', '0000950103',
    '0001437749', '0001628280',
}

# Name fragments → canonical parent name
_NAME_TO_PARENT = {
    'blackrock': 'BlackRock, Inc.',
    'ishares': 'BlackRock, Inc.',
    'bgfa': 'BlackRock, Inc.',
    'vanguard': 'Vanguard Group Inc',
    'fidelity': 'FMR LLC',
    'fmr': 'FMR LLC',
    'strategic advisers': 'FMR LLC',
    'state street': 'State Street Corp',
    'ssga': 'State Street Corp',
    'jpmorgan': 'JPMorgan Chase & Co',
    'j.p. morgan': 'JPMorgan Chase & Co',
    'goldman sachs': 'Goldman Sachs Group Inc',
    'morgan stanley': 'Morgan Stanley',
    'wellington': 'Wellington Management Group LLP',
    'dimensional': 'Dimensional Fund Advisors LP',
    't. rowe price': 'T. Rowe Price Associates',
    'price t rowe': 'T. Rowe Price Associates',
    'price associates': 'T. Rowe Price Associates',
    'capital research': 'Capital Group Companies Inc',
    'capital world': 'Capital Group Companies Inc',
    'american funds': 'Capital Group Companies Inc',
    'invesco': 'Invesco Ltd.',
    'franklin': 'Franklin Resources Inc',
    'templeton': 'Franklin Resources Inc',
    'northern trust': 'Northern Trust Corp',
    'geode': 'Geode Capital Management, LLC',
    'citadel': 'Citadel Advisors LLC',
    'renaissance': 'Renaissance Technologies LLC',
    'ubs': 'UBS Group AG',
    'pimco': 'PIMCO',
    'schwab': 'Charles Schwab Corp',
    'nuveen': 'Nuveen / TIAA',
}

# Known filing agent entity names
_FILING_AGENT_NAMES = {
    'toppan merrill', 'edgarfilings', 'edgar filing', 'edgar agents',
    'advisor consultant network', 'adviser compliance associates',
    'seward & kissel', 'shartsis friese', 'olshan frome',
}


def resolve_filer_to_parent(filer_name, filer_cik=None):
    """Map a filer_name to its institutional parent.
    Returns the parent name, or the original name if no mapping found."""
    if not filer_name:
        return filer_name

    # Filing agent detection
    if filer_cik and filer_cik in _FILING_AGENT_CIKS:
        # For filing agents, the filer_name might be the actual owner (if resolved)
        # or the agent name itself (if not resolved)
        pass

    name_lower = filer_name.lower()

    # Skip if it's a known filing agent name
    for agent in _FILING_AGENT_NAMES:
        if agent in name_lower:
            return filer_name  # can't resolve further

    # Try parent mapping
    for fragment, parent in _NAME_TO_PARENT.items():
        if fragment in name_lower:
            return parent

    return filer_name


def resolve_filer_names_in_records(records):
    """Post-process query results to apply parent rollup to filer_name."""
    for r in records:
        raw_name = r.get('filer_name', '')
        if raw_name:
            r['filer_name'] = resolve_filer_to_parent(raw_name)
    return records


# ── 13F entity footnotes — why some holders show 13F instead of N-PORT ────


# Known 13F entities that do not file N-PORT — shown as fund-equivalent with footnotes
_13F_ENTITY_NOTES = {
    'fiam': 'Institutional separate accounts \u2014 pension funds, endowments. No N-PORT.',
    'fidelity management trust': '401(k) and retirement plan trust. No N-PORT.',
    'strategic advisers': 'Multi-manager advisory arm. No N-PORT.',
    'fidelity diversifying': 'Alternative strategies. No N-PORT.',
    'blackrock fund advisors': 'iShares ETF management. Not in N-PORT scrape.',
    'blackrock institutional trust': 'Institutional index/trust products. No N-PORT.',
    'ssga funds management': 'State Street index management. No N-PORT as separate entity.',
    'geode capital': 'Index fund subadviser for Fidelity. Files under Fidelity fund trusts.',
}


def _13f_entity_footnote(entity_name):
    """Return footnote for known 13F entities that don't file N-PORT, or None."""
    if not entity_name:
        return None
    name_lower = entity_name.lower()
    for pattern, note in _13F_ENTITY_NOTES.items():
        if pattern in name_lower:
            return note
    return None


SUBADVISER_NOTES = {
    'wellington': 'Subadviser \u2014 fund-level holdings_v2 filed under client fund companies (Hartford, Vanguard Windsor, John Hancock, MassMutual)',
    'dodge': 'Primarily manages separate accounts \u2014 limited registered fund filings',
    'capital group': 'American Funds filed under separate CIKs \u2014 may not match via family name',
    'causeway': 'Subadviser \u2014 files under client fund companies',
    'harris': 'Oakmark funds filed under Harris Associates \u2014 check Oakmark family',
    'southeastern': 'Longleaf Partners \u2014 filed under Southeastern Asset Management',
    'grantham': 'GMO \u2014 primarily institutional separate accounts, limited N-PORT',
    'pzena': 'Primarily separate accounts \u2014 limited registered fund filings',
    'hotchkis': 'Primarily separate accounts \u2014 limited registered fund filings',
    'sanders': 'Primarily separate accounts',
    'numeric': 'Subadviser \u2014 quantitative, files under client fund companies',
    'intech': 'Subadviser \u2014 files under client fund companies',
    'acadian': 'Primarily separate accounts and subadvised mandates',
    'epoch': 'Subadviser \u2014 files under client fund companies',
    'martin currie': 'Subadviser \u2014 files under client fund companies',
    'manning': 'Primarily separate accounts',
}


def get_subadviser_note(inst_parent_name):
    """Return explanatory note for managers that show 13F instead of N-PORT."""
    if not inst_parent_name:
        return None
    name_lower = inst_parent_name.lower()
    for key, note in SUBADVISER_NOTES.items():
        if key in name_lower:
            return note
    return None
