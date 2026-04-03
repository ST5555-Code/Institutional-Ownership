"""
Centralized quarter configuration — single source of truth.

Edit this file ONLY when rolling to a new quarter. All scripts import from here.
"""

# Ordered list of quarters in the database
QUARTERS = ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]

LATEST_QUARTER = QUARTERS[-1]
PREV_QUARTER = QUARTERS[-2] if len(QUARTERS) >= 2 else QUARTERS[0]
FIRST_QUARTER = QUARTERS[0]

# SEC 13F data ZIP URLs per quarter
QUARTER_URLS = {
    "2025Q1": "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2025-31may2025_form13f.zip",
    "2025Q2": "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01jun2025-31aug2025_form13f.zip",
    "2025Q3": "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01sep2025-30nov2025_form13f.zip",
    "2025Q4": "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01dec2025-28feb2026_form13f.zip",
}

# Report period end dates per quarter (for 13F filings)
QUARTER_REPORT_DATES = {
    "2025Q1": "2025-03-31",
    "2025Q2": "2025-06-30",
    "2025Q3": "2025-09-30",
    "2025Q4": "2025-12-31",
}

# Market data snapshot dates (price lookup dates per quarter)
QUARTER_SNAPSHOT_DATES = {
    "2025Q1": "2025-05-31",
    "2025Q2": "2025-08-31",
    "2025Q3": "2025-11-30",
    "2025Q4": "2025-12-31",
}

# Flow analysis comparison periods: (label, from_quarter, to_quarter)
FLOW_PERIODS = [
    ("4Q", QUARTERS[0], QUARTERS[-1]),
]
if len(QUARTERS) >= 4:
    FLOW_PERIODS.append(("3Q", QUARTERS[-4], QUARTERS[-1]))
if len(QUARTERS) >= 3:
    FLOW_PERIODS.append(("2Q", QUARTERS[-3], QUARTERS[-1]))
if len(QUARTERS) >= 2:
    FLOW_PERIODS.append(("1Q", QUARTERS[-2], QUARTERS[-1]))
