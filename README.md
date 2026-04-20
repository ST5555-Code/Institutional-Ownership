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

The full quarterly refresh is driven by the `Makefile`. Individual steps
are runnable standalone; the `quarterly-update` target chains them in the
correct order.

```bash
make quarterly-update         # Steps 1-9: fetch → build-entities → compute-flows →
                              # fetch-market → build-summaries → build-classifications →
                              # backup-db → validate
DRY_RUN=1 make quarterly-update   # print the plan without executing
```

Individual steps (each standalone):

```bash
make fetch-13f              # Step 1 — holdings_v2 refresh (scripts/fetch_13f.py)
make fetch-nport            # Step 2 — fund_holdings_v2 via N-PORT XML (scripts/fetch_nport_v2.py)
make fetch-dera-nport       # Step 2 alt — fund_holdings_v2 via DERA ZIP bulk
make build-entities         # Step 3 — entity MDM sync (scripts/build_entities.py)
make compute-flows          # Step 4 — investor_flows + ticker_flow_stats
make fetch-market           # Step 5 — market_data + securities
make build-summaries        # Step 6 — summary_by_parent
make build-classifications  # Step 7 — manager_type + entity classifications
make backup-db              # Step 8 — EXPORT DATABASE
make validate               # Step 9 — validate_entities.py --prod
```

Run `make help` for the full target list, including supplementary targets
(`fetch-13dg`, `fetch-adv`, `fetch-ncen`, `build-managers`, `build-cusip`, …)
and the `schema-parity-check` pre-flight gate.

`scripts/update.py` is deprecated — retained on disk only for reference
in open item INF32 (it references retired scripts in `scripts/retired/`
and is not failing-fast). The Makefile is the single entry point for
pipeline orchestration.

## Updating for New Quarters

1. Add the new quarter URL to `QUARTERS` dict in `scripts/fetch_13f.py`
2. Run `make quarterly-update`
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

## Web Interface

Start the research app:

```bash
./scripts/start_app.sh
```

Open http://localhost:8001. The app provides a browser-based interface with all 15
ownership queries, ticker autocomplete, sortable tables, copy-to-clipboard, and
Excel export. See `web/README_deploy.md` for Render.com deployment.

**One-command startup alias.** Add to `~/.zshrc` for boot-and-open from any terminal:

```bash
alias 13f='cd ~/ClaudeWorkspace/Projects/13f-ownership && ./scripts/start_app.sh && open http://localhost:8001'
```

Then run `13f` to start the server and launch the UI in the default browser.

### Legacy Datasette Dashboard

```bash
python3 -m datasette data/13f.duckdb --metadata web/datasette_config.yaml --port 8002
```

## Ticker Overrides

`data/reference/ticker_overrides.csv` is the manual correction layer for CUSIP-to-ticker mappings. OpenFIGI sometimes returns foreign exchange codes instead of US tickers. This file overrides those with correct values.

- **Commit this file** — it contains curated manual corrections
- `auto_resolve_log.csv` is excluded from Git (regenerated on each run)
- `ticker_overrides_pending.csv` contains candidates awaiting manual review

To add a new override, see the instructions at the top of `scripts/build_cusip.py`.

## Project Structure

```
13f-ownership/
├── Makefile                   — quarterly-update orchestrator + per-step targets
├── scripts/
│   ├── app.py                 — FastAPI entry point
│   ├── app_db.py              — shared DB helpers (get_db, has_table, …)
│   ├── api_common.py          — respond helpers + shared route plumbing
│   ├── api_config.py          — /api/config/* router
│   ├── api_register.py        — /api/register, /api/conviction routers
│   ├── api_fund.py            — /api/fund_portfolio* routers
│   ├── api_flows.py           — /api/flow_analysis, /api/peer_rotation routers
│   ├── api_entities.py        — /api/entity_graph, /api/entity_* routers
│   ├── api_market.py          — /api/market, /api/short_* routers
│   ├── api_cross.py           — /api/cross_ownership, /api/overlap routers
│   ├── admin_bp.py            — /api/admin/* router (token-authed)
│   ├── fetch_13f.py           — Step 1: holdings_v2 (quarterly 13F ZIPs)
│   ├── fetch_nport_v2.py      — Step 2: fund_holdings_v2 via N-PORT XML
│   ├── fetch_dera_nport.py    — Step 2 alt: fund_holdings_v2 via DERA ZIP bulk
│   ├── build_entities.py      — Step 3: entity MDM sync
│   ├── compute_flows.py       — Step 4: investor_flows + ticker_flow_stats
│   ├── fetch_market.py        — Step 5: market_data + securities (yfinance + SEC)
│   ├── build_summaries.py     — Step 6: summary_by_parent rollups
│   ├── build_classifications.py — Step 7: manager/entity classifications
│   ├── validate_entities.py   — Step 9: validation gates
│   ├── fetch_adv.py           — SEC ADV adviser data (supplementary)
│   ├── fetch_13dg.py + fetch_13dg_v2.py — 13D/G beneficial ownership
│   ├── fetch_ncen.py          — N-CEN adviser map
│   ├── build_managers.py      — managers table
│   ├── build_cusip.py         — CUSIP → ticker mapping (OpenFIGI)
│   ├── approve_overrides.py   — interactive override review CLI
│   ├── pipeline/              — pipeline framework (discover, manifest, validate)
│   │   ├── discover.py
│   │   ├── manifest.py
│   │   ├── protocol.py
│   │   ├── shared.py
│   │   ├── validate_schema_parity.py
│   │   └── nport_parsers.py
│   └── migrations/            — numbered schema migrations (001-008, …)
├── web/
│   ├── react-app/             — React 19 + TypeScript + Vite frontend (served from dist/)
│   │   ├── src/               — components, tabs, store, types
│   │   ├── dist/              — production build (Flask→FastAPI serves this)
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   └── playwright.config.ts
│   ├── templates/             — admin.html (token-gated) only
│   ├── datasette_config.yaml  — legacy Datasette dashboard config
│   └── README_deploy.md       — Render.com deployment guide
├── notebooks/
│   └── research.ipynb         — 15 ownership analysis queries (legacy)
├── data/
│   ├── 13f.duckdb             — main database (prod, not in Git)
│   ├── 13f_staging.duckdb     — staging database (not in Git)
│   ├── 13f_readonly.duckdb    — snapshot for query failover (not in Git)
│   ├── raw/                   — downloaded ZIPs (not in Git)
│   ├── nport_raw/             — N-PORT XML files (not in Git)
│   ├── 13dg_raw/              — 13D/G filings (not in Git)
│   ├── extracted/             — unzipped TSVs (not in Git)
│   └── reference/             — curated CSVs (in Git)
│       ├── ticker_overrides.csv
│       ├── ticker_overrides_pending.csv
│       ├── parent_seeds.csv
│       └── …
├── docs/                      — architecture, audits, process rules
├── tests/                     — smoke + fixture tests (pytest)
├── outputs/                   — Excel exports
├── requirements.txt
└── README.md
```

See `scripts/app.py:6-20` for the full router registration manifest.


## SEC API Usage

All SEC requests use User-Agent `13f-research serge.tismen@gmail.com` with 0.5 second delays between requests, per SEC fair access policy.
