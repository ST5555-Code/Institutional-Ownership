"""CUSIP classification — pure logic, no DB writes.

Given a row describing a CUSIP (issuer name, raw security_type mode, inferred
seed, asset_category seed, optional market_sector), classify it into a
canonical_type with priceable/equity/permanence flags.

No DB writes — callers (`build_classifications.py`, the rewritten
`build_cusip.py`) are responsible for persistence.

Classification order (see classify_cusip() docstring for detail):
  STEP 0  normalize_raw_type → tokenize_compound
  STEP 1  derivative pre-check (BEFORE market_sector — Plan v1.4 lesson)
  STEP 2  market_sector map (only for non-Equity; Equity falls through)
  STEP 3  combined seed (security_type_inferred + asset_category_seed)
  STEP 4  CANONICAL_TYPE_RULES on normalized tokens
  STEP 5  manual overrides (applied by caller, not here)
"""
from __future__ import annotations

import re
from datetime import date as _date
from typing import Any, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 3  # OpenFIGI retry limit before marking unmappable

US_PRICEABLE_EXCHANGES = frozenset({
    # Specific exchange codes (yfinance / Yahoo)
    'NMS', 'NYQ', 'NGM', 'NCM', 'PCX', 'BATS', 'ARCX', 'ASE',
    'NYS', 'NAS', 'OBB', 'PNK',
    # OpenFIGI v3 composite — returned as 'US' for any US-listed security
    # when no exchCode filter is sent on the request.
    'US',
})

# OpenFIGI v3 per-listing exchCodes for US venues. Used to pick the
# preferred listing when the API returns multiple entries per CUSIP
# (US composite + Frankfurt/XETRA/OTC secondary listings). See
# docs/BLOCK_SECURITIES_DATA_AUDIT_FINDINGS.md RC1.
US_PRICEABLE_EXCHCODES = frozenset({
    'US', 'UN', 'UW', 'UQ', 'UR', 'UA', 'UF', 'UP', 'UV', 'UD', 'UX',
})


# N-PORT asset_category → classification seed.
#
# Corrected against actual vocabulary observed in fund_holdings_v2
# (Plan v1.4 map had three material errors: `DE` was 'debt' when it is
# Derivative-Equity; `LN` / `ABS` / `STIV` / `DBT` / `DFE` / `DIR` / `DCO`
# etc. were absent; `MM` and `ETF` don't appear in the vocabulary at all).
#
# Authoritative mapping per SEC Form N-PORT Schedule of Investments codes:
#   E*   — Equity
#   D*   — Derivative (except DBT which is straight debt)
#   DBT  — Debt (corporate bonds)
#   ABS* — Asset-Backed / mortgage-backed → 'debt'
#   LON  — Loan → 'debt'
#   SN   — Structured Note → 'debt'
#   STIV — Short-Term Investment Vehicle → 'money_market'
#   RA   — Repurchase Agreement → 'money_market'
#   RE   — Real Estate → 'equity'
ASSET_CATEGORY_SEED_MAP = {
    # Equity
    'EC':       'equity',        # Common equity
    'EP':       'equity',        # Preferred equity (further resolved in rules)
    'RE':       'equity',        # Real estate
    # Debt
    'DBT':      'debt',          # Debt (corporate bonds)
    'ABS-MBS':  'debt',          # Mortgage-Backed
    'ABS-CBDO': 'debt',          # CDO / CLO
    'ABS-O':    'debt',          # Other ABS
    'ABS-APCP': 'debt',          # Asset-backed commercial paper
    'LON':      'debt',          # Loan
    'SN':       'debt',          # Structured note
    # Derivatives — all D* except DBT
    'DE':       'derivative',    # Derivative-Equity  (was wrongly 'debt' in v1.4)
    'DIR':      'derivative',    # Derivative-Interest Rate
    'DCO':      'derivative',    # Derivative-Commodity
    'DCR':      'derivative',    # Derivative-Credit
    'DO':       'derivative',    # Derivative-Other
    'DFE':      'derivative',    # Derivative-Forex
    # Money-market-ish
    'STIV':     'money_market',
    'RA':       'money_market',
    # Other / unmapped → leave as None so classification falls through
    'COMM':     None,
    'OTHER':    None,
}


# market_sector → (canonical_type, is_equity, is_priceable_default, is_permanent)
# 'Equity' falls through to Step 4 (equity_bucket sentinel); all others terminal.
MARKET_SECTOR_MAP = {
    'Equity':   ('equity_bucket', True,  True,  False),
    'Corp':     ('BOND',          False, False, True),
    'Govt':     ('BOND',          False, False, True),
    'Muni':     ('BOND',          False, False, True),
    'M-Mkt':    ('CASH',          False, False, True),
    'Pfd':      ('PREF',          True,  True,  False),
    'Comdty':   ('OTHER',         False, False, False),
    'Index':    ('OTHER',         False, False, False),
    'Curncy':   ('CASH',          False, False, True),
    'Mtge':     ('BOND',          False, False, True),
}


INFERRED_SEED_MAP = {
    'derivative':   ('OPTION', False, False, True),
    'money_market': ('CASH',   False, False, True),
    'etf':          ('ETF',    True,  True,  False),
    'debt':         ('BOND',   False, False, True),
    # 'equity' → fall through to CANONICAL_TYPE_RULES
}


# Compound-token precedence — earlier wins. Covers CANONICAL_TYPE_RULES'
# equity-bucket outputs so e.g. "MF Closed and MF Open" (CEF + MUTUAL_FUND)
# resolves to CEF.
CANONICAL_PRECEDENCE = ['CEF', 'ETF', 'ADR', 'REIT', 'SPAC', 'PREF', 'MUTUAL_FUND', 'COM']


# Rule format:
#   (match_strings, canonical_type, is_equity, is_priceable, is_permanent, ticker_expected)
# Matches are case-insensitive. First non-OTHER match wins for single tokens.
CANONICAL_TYPE_RULES = [
    # --- Permanent non-equity ---
    # Derivatives — mostly caught in Step 1 pre-check, these are fallback.
    (['PUT', 'CALL', 'OPT', 'OPTION', 'OPTIONS'],
     'OPTION',      False, False, True,  False),
    (['WARRANT', 'RIGHT', 'WRT', 'WT', 'RT', 'RIGHTS & WARRANTS'],
     'WARRANT',     False, False, True,  False),
    (['CLO', 'COLLATERALIZED LOAN'],
     'CLO',         False, False, True,  False),
    (['BANK LOAN', 'BANK_LOAN', 'LOAN'],
     'BANK_LOAN',   False, False, True,  False),
    (['CONVERT', 'CVT', 'CONVERTIBLE', 'CONVERTIBLE BOND'],
     'CONVERT',     False, False, True,  False),
    (['BOND', 'NOTE', 'DEBENTURE', 'MUNI', 'MUNICIPAL',
      'TREASURY', 'TREAS', 'GOVT', 'GOVERNMENT', 'AGENCY',
      'FIXED', 'FIX', 'NTF BOND FUNDS', 'BOND FUNDS',
      'FIXED INCOME', 'US DOMESTIC',
      'CORPORATE BOND - DOMESTIC', 'CORPORATE BOND - FOREIGN US$'],
     'BOND',        False, False, True,  False),
    (['USD', 'CASH', 'FX', 'CURRENCY', 'MONEY MARKET'],
     'CASH',        False, False, True,  False),

    # --- Non-permanent non-equity ---
    (['COMMON STOCK - FOREIGN', 'FOREIGN', 'FOREIGN CANADIAN', 'COMMON STOCK-FO'],
     'FOREIGN',     True,  False, False, False),

    # --- Non-permanent equity ---
    (['ADR', 'ADS', 'AMERICAN DEPOSITARY', 'SPON ADS', 'SPON ADR NEW',
      'SPONSORED ADS', 'SPONSORED ADR'],
     'ADR',         True,  True,  False, True),
    (['ETF', 'ETP', 'EXCHANGE TRADED', 'EXCHANGE-TRADED',
      'NTF EQUITY FUNDS', 'EQUITY FUNDS', 'INDX FD', 'LEVERAGE SHS 2X'],
     'ETF',         True,  True,  False, True),
    (['CEF', 'CLOSED-END', 'CLOSED END', 'MF CLOSED'],
     'CEF',         True,  True,  False, True),
    (['MUTUAL FUND', 'MF', 'MFC', 'MF OPEN', 'FUND', 'MUTUAL',
      'UNIT INVESTMENT TRUST', 'UIT EXCHANGE TRADED', 'UIT', 'UIE', 'UNIT',
      'NTF EQUITY'],
     'MUTUAL_FUND', True,  True,  False, True),
    (['REIT', 'REAL ESTATE INVESTMENT TRUST'],
     'REIT',        True,  True,  False, True),
    (['SPAC', 'SPACS', 'SPECIAL PURPOSE', 'SPAC COMBINATION'],
     'SPAC',        True,  True,  False, True),
    (['PREF', 'PREFERRED', 'PFD', 'PS', 'PREFERREDSTK',
      'PREFERRED STOCK'],
     'PREF',        True,  True,  False, True),
    (['COM', 'COMMON', 'COMMON STOCK', 'CS', 'MC',
      'STOCK', 'SHS', 'SHARES', 'ORDINARY SHARES',
      'EQUITY', 'EQUITIES', 'EQUIT',
      'CLASS A COM', 'CL A COM', 'COM SHS',
      'SHS NEW CL A', 'ORD SHS CL A', 'CL A SHS'],
     'COM',         True,  True,  False, True),
    (['0', ''],
     'OTHER',       False, False, False, False),
]


# Derivative keyword set for Step-1 pre-check (independent of rules above)
_DERIVATIVE_KEYWORDS = {
    'PUT', 'CALL', 'OPT', 'OPTION', 'OPTIONS',
    'WARRANT', 'WARRANTS', 'RIGHT', 'RIGHTS',
    'WRT', 'WT', 'RT',
    'RIGHTS & WARRANTS',
}

# asset_category seeds that are always derivatives (step 1 pre-check).
# Mirrors every D* in ASSET_CATEGORY_SEED_MAP mapped to 'derivative', plus
# the historical OPT/WAR codes seen in older filings.
_DERIVATIVE_ASSET_CATS = frozenset({
    'DE', 'DIR', 'DCO', 'DCR', 'DO', 'DFE',
    'OPT', 'WAR',
})


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_SHARE_CLASS_ALONE_RE = re.compile(r'^(CL|CLASS)\s+[A-Z]$')
_STRIP_PATTERNS = [
    re.compile(r'\b(?:CL|CLASS)\s+[A-Z]\b'),
    re.compile(r'\b(?:SHS\s+CL|ORD\s+SHS\s+CL|SHS\s+NEW\s+CL|CL\s+[A-Z]\s+SHS)\b'),
    re.compile(r'\bCOM\s+NEW\b'),
    re.compile(r'\bSHS\s+NEW\b'),
    re.compile(r'\bORD\s+SHS\b'),
    re.compile(r'\b(?:SHS|ORD|NEW)\b'),
    re.compile(r'\bUNIT\s+\d{2}/\d{2}/\d{4}\b'),  # UIT date suffix
    re.compile(r'\b\d{2}/\d{2}/\d{4}\b'),
]
_EQUITY_MARKER_RE = re.compile(r'\b(CL|CLASS|SHS|ORD)\b')
_COMPOUND_SPLIT_RE = re.compile(r'\s+(?:and|&|/)\s+', re.IGNORECASE)
_WHITESPACE_RE = re.compile(r'\s+')


def normalize_raw_type(raw: Optional[str]) -> str:
    """Normalize a security_type string before rule matching.

    Steps (Plan v1.4):
      1. Uppercase + strip.
      2. Standalone share-class marker: "CL A" / "CLASS A" → "COM".
      3. Strip share-class suffixes (CL [A-Z], SHS CL [A-Z], ...).
      4. Strip SHS / ORD / NEW / COM NEW / SHS NEW / ORD SHS.
      5. Strip UIT-style date suffixes.
      6. Collapse whitespace.
      7. If the result is empty AND the original contained an equity marker
         (CL/CLASS/SHS/ORD), return 'COM' (prevents "SHS CL A" → 'OTHER').
    """
    if raw is None:
        return ''
    s = str(raw).upper().strip()
    if not s:
        return ''

    # Rule 2: standalone share-class marker ("CL A", "CLASS B").
    if _SHARE_CLASS_ALONE_RE.match(s):
        return 'COM'

    original = s
    # Rules 3–5: strip patterns.
    for pat in _STRIP_PATTERNS:
        s = pat.sub(' ', s)

    # Rule 6: collapse whitespace.
    s = _WHITESPACE_RE.sub(' ', s).strip(' -,')

    # Rule 7: empty fallthrough when we stripped out equity markers.
    if not s and _EQUITY_MARKER_RE.search(original):
        return 'COM'

    return s


def tokenize_compound(normalized: str) -> list[str]:
    """Split a normalized string on " and " / " / " / " & " for
    multi-token classification.

    Example:
        'MF CLOSED and MF OPEN' → ['MF CLOSED', 'MF OPEN']
    Single-token strings are returned as a 1-element list.
    """
    if not normalized:
        return ['']
    parts = _COMPOUND_SPLIT_RE.split(normalized)
    return [p.strip() for p in parts if p.strip()] or ['']


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------

def _match_rules(token: str) -> Optional[tuple]:
    """Return the first rule (canonical_type, is_equity, is_priceable,
    is_permanent, ticker_expected) matching ``token``, or None.

    Token is compared case-insensitively against each match string; a
    rule matches if ``token == match`` OR the match string is a
    whole-word substring of ``token``.
    """
    if token is None:
        return None
    t = token.upper().strip()
    if not t:
        # '' pattern in OTHER rule
        for matches, ct, eq, pr, perm, tx in CANONICAL_TYPE_RULES:
            if '' in matches:
                return (ct, eq, pr, perm, tx)
        return None

    for matches, ct, eq, pr, perm, tx in CANONICAL_TYPE_RULES:
        for m in matches:
            m_up = m.upper().strip()
            if not m_up:
                continue
            if t == m_up:
                return (ct, eq, pr, perm, tx)
            # Whole-word substring: use word-boundary regex.
            pat = r'\b' + re.escape(m_up) + r'\b'
            if re.search(pat, t):
                return (ct, eq, pr, perm, tx)
    return None


def _resolve_compound(tokens: list[str]) -> Optional[tuple]:
    """For a compound token list, pick the highest-precedence rule match."""
    matches: list[tuple] = []
    for tok in tokens:
        m = _match_rules(tok)
        if m is not None and m[0] != 'OTHER':
            matches.append(m)
    if not matches:
        return None
    # Sort by CANONICAL_PRECEDENCE, unknown types last.
    def prec(match_tuple):
        ct = match_tuple[0]
        try:
            return CANONICAL_PRECEDENCE.index(ct)
        except ValueError:
            return len(CANONICAL_PRECEDENCE) + 1
    matches.sort(key=prec)
    return matches[0]


# ---------------------------------------------------------------------------
# classify_cusip
# ---------------------------------------------------------------------------

_DEFAULT_FIRST_SEEN = _date.today()


def classify_cusip(row: dict[str, Any]) -> dict[str, Any]:
    """Classify one CUSIP.

    Expected input keys (all optional except ``cusip``):
        cusip                   str (required)
        issuer_name             str | None
        raw_type_mode           str | None  (most common security_type)
        raw_type_count          int | None
        security_type_inferred  str | None  (seed from securities)
        asset_category_seed     str | None  (seed from fund_holdings_v2)
        market_sector           str | None  (from OpenFIGI; None pre-lookup)
        exchange                str | None  (from OpenFIGI; None pre-lookup)
        figi                    str | None
        ticker                  str | None

    Returns a dict populated for every cusip_classifications column except
    the timestamps (``created_at`` / ``updated_at``) which are DB defaults.

    Classification order: see module docstring.
    """
    cusip = row['cusip']
    raw = row.get('raw_type_mode')
    inferred = row.get('security_type_inferred')
    asset_cat = row.get('asset_category_seed')
    market_sector = row.get('market_sector')
    exchange = row.get('exchange')

    normalized = normalize_raw_type(raw)
    tokens = tokenize_compound(normalized)

    canonical_type: Optional[str] = None
    is_equity = False
    is_priceable = False
    is_permanent = False
    ticker_expected = False
    canonical_type_source = None
    confidence = 'low'

    # --- STEP 1: derivative pre-check (BEFORE market_sector) ---
    is_derivative_raw = any(
        re.search(r'\b' + re.escape(k) + r'\b', normalized) for k in _DERIVATIVE_KEYWORDS
    )
    is_derivative_seed = (inferred == 'derivative')
    is_derivative_asset = (asset_cat in _DERIVATIVE_ASSET_CATS)
    if is_derivative_raw or is_derivative_seed or is_derivative_asset:
        # Prefer WARRANT for explicit warrant raw_type; else OPTION.
        warrant_markers = {'WARRANT', 'WARRANTS', 'RIGHT', 'RIGHTS', 'WRT', 'WT', 'RT'}
        if normalized and any(
            re.search(r'\b' + re.escape(w) + r'\b', normalized)
            for w in warrant_markers
        ):
            canonical_type = 'WARRANT'
        else:
            canonical_type = 'OPTION'
        is_equity = False
        is_priceable = False
        is_permanent = True
        ticker_expected = False
        canonical_type_source = 'asset_category' if is_derivative_asset and not is_derivative_seed \
            else ('inferred' if is_derivative_seed else 'inferred')
        confidence = 'high' if (is_derivative_seed or is_derivative_asset) else 'medium'

    # --- STEP 2: market_sector map ---
    if canonical_type is None and market_sector:
        ms_hit = MARKET_SECTOR_MAP.get(market_sector)
        if ms_hit is not None:
            ct, eq, pr, perm = ms_hit
            canonical_type_source = 'market_sector'
            if ct == 'equity_bucket':
                # Equity → fall through to Step 4 rules (keep is_equity=True
                # as hint but leave canonical_type None).
                is_equity = True
                is_priceable = pr
                is_permanent = perm
                # ticker_expected will be set by the matched rule below.
            else:
                canonical_type = ct
                is_equity = eq
                is_priceable = pr
                is_permanent = perm
                ticker_expected = eq and pr
                confidence = 'high'

    # --- STEP 3: combined seed (security_type_inferred + asset_category_seed) ---
    seed: Optional[str] = None
    seed_source: Optional[str] = None
    if canonical_type is None:
        seed = inferred
        seed_source = 'inferred'
        if seed is None and asset_cat is not None:
            seed = ASSET_CATEGORY_SEED_MAP.get(asset_cat)
            seed_source = 'asset_category'

        if seed and seed in INFERRED_SEED_MAP:
            ct, eq, pr, perm = INFERRED_SEED_MAP[seed]
            canonical_type = ct
            is_equity = eq
            is_priceable = pr
            is_permanent = perm
            ticker_expected = eq and pr
            canonical_type_source = seed_source
            confidence = 'high' if seed_source == 'market_sector' else 'medium'

    # --- STEP 4: CANONICAL_TYPE_RULES on normalized tokens ---
    if canonical_type is None:
        if len(tokens) > 1:
            matched = _resolve_compound(tokens)
        else:
            matched = _match_rules(tokens[0])
        if matched is not None:
            ct, eq, pr, perm, tx = matched
            canonical_type = ct
            is_equity = eq
            is_priceable = pr
            is_permanent = perm
            ticker_expected = tx
            canonical_type_source = canonical_type_source or 'inferred'
            confidence = 'medium' if ct != 'OTHER' else 'low'

    # --- STEP 4b: equity-seed fallback ---
    # If the seed signals equity but rules produced OTHER (common for
    # fund-only EC/EP CUSIPs with no securities row → no raw_type_mode),
    # default to COM/PREF so ticker_expected=TRUE and the CUSIP enters
    # the retry queue for OpenFIGI resolution.
    if canonical_type in (None, 'OTHER') and seed == 'equity':
        if asset_cat == 'EP':
            canonical_type = 'PREF'
        else:
            canonical_type = 'COM'
        is_equity = True
        is_priceable = True
        is_permanent = False
        ticker_expected = True
        canonical_type_source = seed_source or 'asset_category'
        confidence = 'medium'

    # --- Fallback ---
    if canonical_type is None:
        canonical_type = 'OTHER'
        canonical_type_source = canonical_type_source or 'inferred'
        confidence = 'low'

    # --- Post-classification: FOREIGN priceability depends on exchange ---
    if canonical_type == 'FOREIGN':
        if exchange and exchange in US_PRICEABLE_EXCHANGES:
            is_priceable = True
            ticker_expected = True
        else:
            is_priceable = False
            ticker_expected = False

    # --- Mutual exclusivity safeguards (BLOCK gate aliens) ---
    if is_permanent:
        # Permanent non-equities cannot be priceable nor equity.
        is_priceable = False
        is_equity = False
        ticker_expected = False

    first_seen_date = row.get('first_seen_date') or _DEFAULT_FIRST_SEEN

    return {
        'cusip': cusip,
        'canonical_type': canonical_type,
        'canonical_type_source': canonical_type_source or 'inferred',
        'raw_type_mode': raw,
        'raw_type_count': row.get('raw_type_count'),
        'security_type_inferred': inferred,
        'asset_category_seed': asset_cat,
        'market_sector': market_sector,
        'issuer_name': row.get('issuer_name'),
        'ticker': row.get('ticker'),
        'figi': row.get('figi'),
        'exchange': exchange,
        'country_code': row.get('country_code'),
        'is_equity': bool(is_equity),
        'ticker_expected': bool(ticker_expected),
        'is_priceable': bool(is_priceable),
        'is_permanent': bool(is_permanent),
        'is_active': True,
        'classification_source': canonical_type_source or 'inferred',
        'ticker_source': row.get('ticker_source'),
        'confidence': confidence,
        'openfigi_attempts': int(row.get('openfigi_attempts') or 0),
        'last_openfigi_attempt': row.get('last_openfigi_attempt'),
        'openfigi_status': row.get('openfigi_status'),
        'last_priceable_check': row.get('last_priceable_check'),
        'first_seen_date': first_seen_date,
        'last_confirmed_date': row.get('last_confirmed_date'),
        'inactive_since': row.get('inactive_since'),
        'inactive_reason': row.get('inactive_reason'),
        'notes': row.get('notes'),
    }


# ---------------------------------------------------------------------------
# Universe query
# ---------------------------------------------------------------------------

def get_cusip_universe(con) -> pd.DataFrame:
    """Return the three-source CUSIP union with dual classification seeds.

    Columns:
      cusip                  (9-char, N/A sentinels excluded by LENGTH=9)
      issuer_name_sample     representative issuer name (MAX across sources)
      raw_type_mode          most common security_type across securities rows
      raw_type_count         number of distinct security_type values observed
      security_type_inferred seed from securities (None for fund-only CUSIPs)
      asset_category_seed    seed from fund_holdings_v2 (None for 13F-only)

    This reads three L3 tables: securities, fund_holdings_v2,
    beneficial_ownership_v2. ``con`` must be a connection that has access
    to all three — in staging mode, pass the prod read connection.
    """
    return con.execute("""
        WITH all_sources AS (
            -- Source 1: 13F holdings via securities (has security_type + inferred)
            SELECT
                s.cusip                            AS cusip,
                s.issuer_name                      AS issuer_name_sample,
                s.security_type                    AS security_type,
                s.security_type_inferred           AS security_type_inferred,
                CAST(NULL AS VARCHAR)              AS asset_category_seed
            FROM securities s
            WHERE s.cusip IS NOT NULL AND LENGTH(s.cusip) = 9

            UNION ALL

            -- Source 2: N-PORT fund holdings (has asset_category as seed)
            SELECT
                fh.cusip                           AS cusip,
                fh.issuer_name                     AS issuer_name_sample,
                CAST(NULL AS VARCHAR)              AS security_type,
                CAST(NULL AS VARCHAR)              AS security_type_inferred,
                fh.asset_category                  AS asset_category_seed
            FROM fund_holdings_v2 fh
            WHERE fh.cusip IS NOT NULL
              AND LENGTH(fh.cusip) = 9

            UNION ALL

            -- Source 3: 13D/G beneficial ownership
            SELECT
                bo.subject_cusip                   AS cusip,
                bo.subject_name                    AS issuer_name_sample,
                CAST(NULL AS VARCHAR)              AS security_type,
                CAST(NULL AS VARCHAR)              AS security_type_inferred,
                CAST(NULL AS VARCHAR)              AS asset_category_seed
            FROM beneficial_ownership_v2 bo
            WHERE bo.subject_cusip IS NOT NULL
              AND LENGTH(bo.subject_cusip) = 9
        ),
        name_counts AS (
            -- Pre-aggregate (cusip, name) frequency so the window function
            -- below can order by a scalar column (DuckDB does not allow a
            -- window function inside another window's ORDER BY).
            SELECT
                cusip,
                issuer_name_sample,
                COUNT(*) AS name_freq
            FROM all_sources
            WHERE issuer_name_sample IS NOT NULL
            GROUP BY cusip, issuer_name_sample
        ),
        issuer_name_pick AS (
            -- RC2: pick most-common issuer_name_sample per CUSIP.
            -- Tie-breakers: longer name (less likely clipped), alphabetic.
            SELECT cusip, issuer_name_sample
            FROM (
                SELECT
                    cusip,
                    issuer_name_sample,
                    name_freq,
                    ROW_NUMBER() OVER (
                        PARTITION BY cusip
                        ORDER BY
                            name_freq DESC,
                            LENGTH(issuer_name_sample) DESC,
                            issuer_name_sample ASC
                    ) AS rn
                FROM name_counts
            ) ranked
            WHERE rn = 1
        )
        SELECT
            a.cusip,
            ip.issuer_name_sample              AS issuer_name_sample,
            MAX(a.security_type)               AS raw_type_mode,
            COUNT(DISTINCT a.security_type)    AS raw_type_count,
            MAX(a.security_type_inferred)      AS security_type_inferred,
            MAX(a.asset_category_seed)         AS asset_category_seed
        FROM all_sources a
        LEFT JOIN issuer_name_pick ip USING (cusip)
        GROUP BY a.cusip, ip.issuer_name_sample
    """).fetchdf()
