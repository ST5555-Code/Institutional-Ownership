#!/usr/bin/env python3
"""
normalize_names.py — Standardize investor/manager name casing across the database.

Converts ALL CAPS names to Title Case while preserving:
- Legal suffixes (LLC, LP, LLP, INC, CORP, LTD, PLC, AG, SA, NA)
- Known acronyms (FMR, AQR, BNP, UBS, DFA, ETF, BMO, RBC, HSBC, etc.)
- State suffixes (/DE/, /MD/, /MN/, /PA/)
- Roman numerals (II, III, IV, VI)

Usage:
    python3 scripts/normalize_names.py          # dry-run preview
    python3 scripts/normalize_names.py --apply  # apply to database
"""

import argparse
import re
import time

import duckdb

from db import get_db_path

# Words to keep UPPERCASE
KEEP_UPPER = {
    # Legal suffixes (short, commonly written uppercase)
    'LLC', 'LP', 'LLP', 'PLC', 'AG', 'SA', 'NA',
    'NV', 'SE', 'SCA', 'KG', 'GMBH', 'BV', 'PC',
    # Financial acronyms
    'FMR', 'AQR', 'BNP', 'UBS', 'DFA', 'ETF', 'BMO', 'RBC', 'HSBC',
    'ING', 'BNY', 'DWS', 'MFS', 'PIMCO', 'PGIM', 'TIAA', 'SSGA',
    'JPM', 'CEO', 'CIO', 'CFO', 'CRD', 'ADV', 'SEC', 'SIC',
    'AMG', 'GIC', 'CPP', 'ADIA', 'KKR', 'TPG', 'EQT',
    # Roman numerals
    'II', 'III', 'IV', 'VI', 'VII', 'VIII', 'IX', 'XI', 'XII',
    # Other
    'US', 'UK', 'EU', 'HK',
}

# Words to keep lowercase (only when not first word)
KEEP_LOWER = {'of', 'the', 'and', 'for', 'in', 'de', 'du', 'van', 'von', 'del', 'la', 'le', 'et'}

# Full names to preserve exactly (known correct forms)
CANONICAL_NAMES = {
    'JPMORGAN CHASE & CO': 'JPMorgan Chase & Co',
    'JPMORGAN CHASE': 'JPMorgan Chase',
    'JPMORGAN': 'JPMorgan',
    'BLACKROCK': 'BlackRock',
    'ISHARES': 'iShares',
    'VANGUARD GROUP INC': 'Vanguard Group Inc',
    'GOLDMAN SACHS': 'Goldman Sachs',
    'MORGAN STANLEY': 'Morgan Stanley',
    'CITIGROUP INC': 'Citigroup Inc',
    'WELLS FARGO': 'Wells Fargo',
    'BANK OF AMERICA': 'Bank of America',
    'STATE STREET': 'State Street',
    'NORTHERN TRUST': 'Northern Trust',
    'CHARLES SCHWAB': 'Charles Schwab',
    'ALLIANCEBERNSTEIN': 'AllianceBernstein',
    'NEUBERGER BERMAN': 'Neuberger Berman',
    'DIMENSIONAL FUND': 'Dimensional Fund',
    'GEODE CAPITAL': 'Geode Capital',
    'SUSQUEHANNA': 'Susquehanna',
    'RENAISSANCE TECHNOLOGIES': 'Renaissance Technologies',
    'FRANKLIN TEMPLETON': 'Franklin Templeton',
    'FRANKLIN RESOURCES': 'Franklin Resources',
    'JANE STREET': 'Jane Street',
    'CITADEL ADVISORS': 'Citadel Advisors',
    'POINT72': 'Point72',
    'TWO SIGMA': 'Two Sigma',
    'BRIDGEWATER': 'Bridgewater',
    'MILLENNIUM MANAGEMENT': 'Millennium Management',
    'BALYASNY': 'Balyasny',
    'NORGES BANK': 'Norges Bank',
    'T. ROWE PRICE': 'T. Rowe Price',
    'PRICE T ROWE': 'T. Rowe Price',
    'AQR CAPITAL': 'AQR Capital',
    'BNP PARIBAS': 'BNP Paribas',
    'BNY MELLON': 'BNY Mellon',
    'BARCLAYS': 'Barclays',
}


def smart_title_case(name):
    """Convert a name to smart Title Case."""
    if not name or len(name) <= 3:
        return name

    # Already mixed case (not ALL CAPS) — leave it alone
    if name != name.upper():
        return name

    original = name

    # Check canonical names first (longest match wins)
    name_upper = name.upper()
    for pattern, replacement in sorted(CANONICAL_NAMES.items(), key=lambda x: -len(x[0])):
        if pattern in name_upper:
            name_upper = name_upper.replace(pattern, replacement)
            # If we replaced something, work with the partially-fixed name
            if name_upper != original.upper():
                name = name_upper
                break

    # If canonical replacement handled the whole name, return
    if name != name.upper():
        # Still need to title-case any remaining ALL CAPS segments
        pass

    # Handle state suffixes like /DE/, /MD/, /MN (with or without trailing slash)
    state_suffix = ''
    state_match = re.search(r'[/]([A-Z]{2})[/]?\s*$', name)
    if state_match:
        state_suffix = ' /' + state_match.group(1) + '/'
        name = name[:state_match.start()].rstrip('/ ')

    # Split and process each word
    words = name.split()
    result = []
    for i, word in enumerate(words):
        # Strip trailing punctuation for matching, preserve it
        clean = word.rstrip('.,;:')
        trailing = word[len(clean):]

        # Handle dotted abbreviations like L.L.C., L.P., N.A., CORP.
        if re.match(r'^[A-Z](\.[A-Z])+\.?$', clean.upper()):
            result.append(clean.upper() + trailing)
            continue

        # Strip trailing period for acronym matching (CORP. INC. LTD.)
        clean_no_dot = clean.rstrip('.')
        dot_suffix = clean[len(clean_no_dot):]
        clean_upper = clean_no_dot.upper()

        # Check if word is a known acronym (with or without trailing period)
        if clean_upper in KEEP_UPPER:
            result.append(clean_upper + dot_suffix + trailing)
        # Lowercase words (not first)
        elif clean_no_dot.lower() in KEEP_LOWER and i > 0:
            result.append(clean_no_dot.lower() + dot_suffix + trailing)
        # Already mixed case from canonical replacement
        elif clean != clean.upper():
            result.append(clean + trailing)
        # Handle hyphenated words
        elif '-' in clean_no_dot:
            parts = clean_no_dot.split('-')
            titled = '-'.join(p.upper() if p.upper() in KEEP_UPPER else p.capitalize() for p in parts)
            result.append(titled + dot_suffix + trailing)
        # Default: capitalize
        else:
            result.append(clean_no_dot.capitalize() + dot_suffix + trailing)

    return ' '.join(result) + state_suffix


def normalize_table(con, table, column, apply=False):
    """Normalize a name column in a table."""
    # Get distinct ALL CAPS names
    rows = con.execute(f"""
        SELECT DISTINCT {column}
        FROM {table}
        WHERE {column} = UPPER({column}) AND LENGTH({column}) > 5
        ORDER BY {column}
    """).fetchall()

    changes = {}
    for (name,) in rows:
        new_name = smart_title_case(name)
        if new_name != name:
            changes[name] = new_name

    if not changes:
        print(f"  {table}.{column}: no changes needed")
        return 0

    print(f"  {table}.{column}: {len(changes):,} names to normalize")

    if not apply:
        # Show samples
        for old, new in list(changes.items())[:10]:
            print(f"    {old[:45]:<45} → {new}")
        if len(changes) > 10:
            print(f"    ... and {len(changes)-10} more")
        return len(changes)

    # Apply updates
    updated_rows = 0
    for old, new in changes.items():
        result = con.execute(f"""
            UPDATE {table} SET {column} = ? WHERE {column} = ?
        """, [new, old]).fetchone()
        if result:
            updated_rows += result[0]

    print(f"    Updated {updated_rows:,} rows")
    return updated_rows


def main():
    parser = argparse.ArgumentParser(description="Normalize investor name casing")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    db_path = get_db_path()
    con = duckdb.connect(db_path)

    print(f"Database: {db_path}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Started: {time.strftime('%H:%M:%S')}\n")

    # Normalize each table/column
    tables = [
        ('holdings', 'manager_name'),
        ('holdings', 'inst_parent_name'),
        ('beneficial_ownership', 'filer_name'),
        ('beneficial_ownership_current', 'filer_name'),
        ('managers', 'manager_name'),
        ('managers', 'parent_name'),
        ('parent_bridge', 'manager_name'),
        ('parent_bridge', 'parent_name'),
    ]

    total = 0
    for table, column in tables:
        try:
            total += normalize_table(con, table, column, apply=args.apply)
        except Exception as e:
            print(f"  {table}.{column}: skipped ({e})")

    if args.apply:
        con.execute("CHECKPOINT")
        print(f"\nTotal rows updated: {total:,}")
    else:
        print(f"\nTotal names to normalize: {total:,}")
        print("Run with --apply to execute.")

    con.close()


if __name__ == '__main__':
    from db import crash_handler
    crash_handler("normalize_names")(main)
