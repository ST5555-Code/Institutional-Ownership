# Sector Rotation Tab — Redesign Spec

## Purpose

Replace the existing query13-based Sector Rotation tab with a multi-quarter institutional money flow analysis. Shows where institutions are actively moving capital by GICS sector, stripped of price effects, with drill-down to see which managers are driving the flows.

## Core Concept

For each position held across consecutive quarters, decompose value change into:

- **Active flow** = `(shares_current - shares_prior) * implied_price` — real buying/selling
- **Price effect** = `shares_prior * (price_current - price_prior)` — market movement

Only active flow is displayed. This answers "where is smart money moving" without noise from market returns.

Special cases:
- New position (no prior quarter): `active_flow = +market_value_usd` (100% inflow)
- Exit (position gone): `active_flow = -market_value_prior` (100% outflow)

## Layout

Financial-statement style: one row per GICS sector, 4 quarter-transition columns side by side, plus total.

```
┌─ By Parent ─┬─ By Fund ─┐  ┌─ Active Only ─┐
┌──────────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Sector       │  Q1->Q2  │  Q2->Q3  │  Q3->Q4  │  Q4->Q1  │  Total   │
├──────────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ > Technology │  +$2.1B  │  +$3.4B  │  +$4.2B  │  +$1.8B  │ +$11.5B  │
│ > Healthcare │  +$0.8B  │  +$1.2B  │  +$1.8B  │  +$0.5B  │  +$4.3B  │
│ > Energy     │  +$1.2B  │  -$0.5B  │  -$2.1B  │  -$3.0B  │  -$4.4B  │
└──────────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

- Green text = net inflow, red text = net outflow
- Sorted by Total (descending) by default
- Sectors with no flow data are omitted

## Expanded Detail

Click any quarter cell (or the expand arrow) to show that sector's detail for that specific quarter below the row:

```
v Technology -- Q3 -> Q4 2025                    Net: +$4.2B
  Inflow: $12.1B    Outflow: -$7.9B    New: 89    Exits: 47

  TOP 5 NET BUYING              TOP 5 NET SELLING
  Vanguard      +$1.2B (43)    Citadel       -$890M (12)
  BlackRock      +$980M (38)   Millennium    -$720M  (8)
  State Street   +$640M (31)   Two Sigma     -$510M (15)
  Fidelity       +$520M (28)   Bridgewater   -$340M  (6)
  Capital Group  +$410M (22)   Point72       -$280M  (9)
```

## Toggles

### Active Only
Filters to `manager_type IN ('active', 'hedge_fund', 'activist')`. Default: off (all managers). Applies to both summary and movers.

### By Parent / By Fund
- **By Parent** (default): aggregates by `COALESCE(inst_parent_name, manager_name)` — Vanguard Group as one entity
- **By Fund**: shows individual CIK/manager_name — each filing entity separately

Applies to the expanded movers section. The sector summary rows are always sector-level aggregates regardless of this toggle.

## Backend

### Data sources

| Table | Fields used |
|-------|------------|
| `holdings` (multiple quarters) | cik, ticker, shares, market_value_usd, quarter, manager_name, inst_parent_name, manager_type |
| `market_data` | sector (ticker -> GICS sector mapping) |

No new tables needed.

### Endpoint 1: `GET /api/sector_flows`

Params: `active_only` (0/1, default 0)

Returns all sectors x all quarter transitions in one call.

```json
{
  "periods": [
    {"label": "Q1->Q2", "from": "2025Q1", "to": "2025Q2"},
    {"label": "Q2->Q3", "from": "2025Q2", "to": "2025Q3"},
    ...
  ],
  "sectors": [
    {
      "sector": "Technology",
      "flows": {
        "2025Q1_2025Q2": {"net": 2100000000, "inflow": 8200000000, "outflow": -6100000000, "new_positions": 72, "exits": 38, "managers": 298},
        "2025Q2_2025Q3": {...},
        ...
      },
      "total_net": 11500000000
    },
    ...
  ]
}
```

Quarter pairs auto-derived: `SELECT DISTINCT quarter FROM holdings ORDER BY quarter` -> take last 5 quarters -> 4 transitions.

### Endpoint 2: `GET /api/sector_flow_movers`

Params: `from` (quarter), `to` (quarter), `sector`, `active_only` (0/1), `level` (parent/fund)

Returns top 5 net buyers + top 5 net sellers for one sector in one quarter transition.

```json
{
  "sector": "Technology",
  "period": {"from": "2025Q3", "to": "2025Q4"},
  "summary": {"net": 4200000000, "inflow": 12100000000, "outflow": -7900000000, "new_positions": 89, "exits": 47},
  "top_buyers": [
    {"institution": "Vanguard Group Inc", "net_flow": 1200000000, "positions_changed": 43},
    ...
  ],
  "top_sellers": [
    {"institution": "Citadel Advisors LLC", "net_flow": -890000000, "positions_changed": 12},
    ...
  ]
}
```

### SQL structure (sector_flows)

For each consecutive quarter pair, compute per-position active flow, then aggregate by sector:

```sql
-- Continuing/increased/decreased + new positions
SELECT c.cik, c.inst_parent_name, c.manager_name, c.manager_type, c.ticker,
       (c.shares - COALESCE(p.shares, 0))
         * (c.market_value_usd * 1.0 / NULLIF(c.shares, 0)) AS active_flow
FROM holdings c
LEFT JOIN holdings p ON c.cik = p.cik AND c.ticker = p.ticker AND p.quarter = :q_from
WHERE c.quarter = :q_to

UNION ALL

-- Exits
SELECT p.cik, p.inst_parent_name, p.manager_name, p.manager_type, p.ticker,
       -p.market_value_usd AS active_flow
FROM holdings p
LEFT JOIN holdings c ON p.cik = c.cik AND p.ticker = c.ticker AND c.quarter = :q_to
WHERE p.quarter = :q_from AND c.cik IS NULL
```

Then:
```sql
SELECT md.sector,
       SUM(active_flow) AS net,
       SUM(CASE WHEN active_flow > 0 THEN active_flow ELSE 0 END) AS inflow,
       SUM(CASE WHEN active_flow < 0 THEN active_flow ELSE 0 END) AS outflow,
       COUNT(DISTINCT CASE WHEN flow_type='new' THEN cik||ticker END) AS new_positions,
       COUNT(DISTINCT CASE WHEN flow_type='exit' THEN cik||ticker END) AS exits,
       COUNT(DISTINCT cik) AS managers
FROM flows f
JOIN market_data md ON f.ticker = md.ticker
WHERE md.sector IS NOT NULL
  [AND f.manager_type IN ('active','hedge_fund','activist')]  -- if active_only
GROUP BY md.sector
```

### SQL structure (sector_flow_movers)

Same flows CTE scoped to one quarter pair + one sector, then:

```sql
-- By Parent
SELECT COALESCE(inst_parent_name, manager_name) AS institution,
       SUM(active_flow) AS net_flow,
       COUNT(DISTINCT ticker) AS positions_changed
FROM flows f
JOIN market_data md ON f.ticker = md.ticker
WHERE md.sector = :sector
GROUP BY institution
HAVING ABS(SUM(active_flow)) > 0
ORDER BY net_flow DESC  -- top 5
/ ORDER BY net_flow ASC  -- bottom 5
LIMIT 5

-- By Fund: GROUP BY cik, manager_name instead
```

## Frontend

### Files touched
- `web/static/app.js` — replace `loadSectorRotation()` + old query13 column defs
- `web/static/style.css` — green/red flow cells, expand sub-table styling
- `web/templates/index.html` — no changes (tab button already exists)
- `scripts/app.py` — replace query13 route handling with new endpoints
- `scripts/queries.py` — new functions, remove old query13

### Rendering
- New `loadSectorRotation()` function (replaces existing)
- Builds filter bar with By Parent/By Fund toggle + Active Only button
- Fetches `/api/sector_flows` on load and on toggle change
- Builds `<table>` with `<colgroup>` for sector + N period columns + total
- Each period cell formatted as `$X.XB` / `$XXXM` with green/red color
- Click on expand arrow or any period cell -> fetch `/api/sector_flow_movers` -> render sub-table below row
- Only one sector expanded at a time (clicking another collapses the previous)

### Formatting
- Dollar formatting: `$1.2B`, `$890M`, `$45M` (compact, sign prefix)
- Color: CSS class `.flow-positive { color: #2e7d32 }` `.flow-negative { color: #c62828 }`
- Expand arrow: same `.toggle-arrow` pattern as Register tab
- Sub-table: two side-by-side columns (buyers left, sellers right), sandstone background

## Cleanup

Remove:
- `query13()` function from queries.py
- Query 13 from `QUERY_FUNCTIONS` map
- `QUERY_COLUMNS[9]` definition (sector rotation was mapped to tab index 9)
- Old sector-rotation handling in app.py query dispatcher
- `'sector-rotation': 9` mapping in app.js tab-to-query map
