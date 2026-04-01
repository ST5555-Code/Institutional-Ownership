# 13-F Institutional Ownership Database

Local database of SEC 13-F institutional ownership filings. Downloads quarterly 13-F data sets, links filers to SEC ADV adviser records, resolves CUSIPs to tickers via OpenFIGI and SEC data, pulls live market data from yfinance, and provides a Jupyter notebook with 15 pre-built ownership analysis queries. Covers Q1-Q4 2025 with 12.3 million holdings rows across 8,600+ institutional filers.

## Prerequisites

- Python 3.9+
- pip
- ~2 GB disk space for raw data and DuckDB

## Setup

```bash
git clone <repo-url>
cd 13f-ownership
pip install -r requirements.txt
```

## Build Order

Run scripts in this sequence from the project root:

```bash
python3 scripts/fetch_adv.py          # ~30 sec  — SEC ADV adviser data
python3 scripts/fetch_13f.py          # ~5 min   — download 4 quarterly ZIPs (~350 MB)
python3 scripts/load_13f.py           # ~30 sec  — load into DuckDB
python3 scripts/build_managers.py     # ~2 min   — manager/parent tables, CIK-CRD linking
python3 scripts/build_cusip.py        # ~30 min  — CUSIP-to-ticker mapping (OpenFIGI API)
python3 scripts/fetch_market.py       # ~10 min  — yfinance market data
```

Or run the full pipeline in one command:

```bash
python3 scripts/update.py
```

This runs all six scripts in order, then runs `auto_resolve.py` to fix ticker gaps automatically.

## Updating for New Quarters

1. Add the new quarter URL to `QUARTERS` dict in `scripts/fetch_13f.py`
2. Run `python3 scripts/update.py`
3. Review any pending ticker overrides: `python3 scripts/approve_overrides.py`

## Using the Notebook

```bash
python3 -m jupyter notebook notebooks/research.ipynb
```

The notebook has 15 query cells. Change the `TICKER` variable at the top of each cell to analyze any stock. Default is AR (Antero Resources). Each query exports to `outputs/`.

### Queries

1. Current shareholder register (two-level parent/fund hierarchy)
2. 4-quarter ownership change (Q1 vs Q4 2025)
3. Active holder market cap analysis with percentile ranking
4. Passive vs active ownership split
5. Quarterly share change heatmap
6. Activist ownership tracker
7. Full portfolio for a given manager (CIK)
8. Cross-holder overlap (common ownership)
9. Sector rotation analysis
10. Largest new positions
11. Largest exits
12. Concentration analysis (top 5/10/20 % of float)
13. Energy sector institutional rotation
14. Manager AUM vs position size
15. Database statistics

## Web Dashboard

```bash
python3 -m datasette data/13f.duckdb --metadata web/datasette_config.yaml --port 8001
```

Open http://localhost:8001. See `web/README_deploy.md` for Render.com deployment.

## Ticker Overrides

`data/reference/ticker_overrides.csv` is the manual correction layer for CUSIP-to-ticker mappings. OpenFIGI sometimes returns foreign exchange codes instead of US tickers. This file overrides those with correct values.

- **Commit this file** — it contains curated manual corrections
- `auto_resolve_log.csv` is excluded from Git (regenerated on each run)
- `ticker_overrides_pending.csv` contains candidates awaiting manual review

To add a new override, see the instructions at the top of `scripts/build_cusip.py`.

## Project Structure

```
13f-ownership/
├── scripts/
│   ├── fetch_adv.py           — SEC ADV adviser data
│   ├── fetch_13f.py           — Download quarterly 13F ZIPs
│   ├── load_13f.py            — Load into DuckDB
│   ├── build_managers.py      — Manager/parent tables
│   ├── build_cusip.py         — CUSIP-to-ticker mapping
│   ├── fetch_market.py        — yfinance market data
│   ├── enrich_tickers.py      — Additional ticker enrichment
│   ├── auto_resolve.py        — Automatic ticker gap resolution
│   ├── approve_overrides.py   — Interactive override review CLI
│   └── update.py              — Master pipeline script
├── notebooks/
│   └── research.ipynb         — 15 ownership analysis queries
├── data/
│   ├── 13f.duckdb             — Main database (not in Git)
│   ├── raw/                   — Downloaded ZIPs (not in Git)
│   ├── extracted/             — Unzipped TSVs (not in Git)
│   └── reference/
│       ├── ticker_overrides.csv          — Manual ticker corrections (in Git)
│       ├── ticker_overrides_pending.csv  — Pending review (in Git)
│       ├── adv_managers.csv              — Parsed ADV data
│       └── sec_13f_list.csv              — SEC 13F securities list
├── outputs/                   — Excel exports from notebook
├── web/
│   ├── datasette_config.yaml  — Datasette configuration
│   └── README_deploy.md       — Render.com deployment guide
├── requirements.txt
└── README.md
```

## SEC API Usage

All SEC requests use User-Agent `13f-research serge.tismen@gmail.com` with 0.5 second delays between requests, per SEC fair access policy.
