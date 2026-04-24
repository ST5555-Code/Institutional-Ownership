# Peer Rotation Tab — Implementation Plan

## Context

The app has sector-level flow analysis (Sector Rotation tab) but no way to see how a **specific company** is positioned relative to its peers. When a fund sells EQT, we can't tell if the money went to COP (direct peer swap), to XOM (broader sector reallocation), or left Energy entirely. This tab answers: "Is smart money rotating out of EQT specifically, or out of E&P, or out of Energy — and who's doing it?"

## Design Decisions (from user)

- **Tab name:** Peer Rotation
- **Peer scope:** Industry peers shown first (e.g., Oil & Gas E&P for EQT), then broader sector peers below — two sections
- **Summary:** Show both dollars + % share of sector flow
- **Entity depth:** Top 10 entities with rotation stories
- **Toggles:** By Parent / By Fund, Active Only (same pattern as other tabs)

## Visual Consistency & Charts

**Must match existing UI conventions:**
- Filter bar: `.register-filter-bar` with `.register-view-toggle` button groups (same as Sector Rotation, Ownership Trend, Conviction tabs)
- Tables: `.data-table` class, Oxford Blue headers, zebra striping, `_fmtFlow()` for all dollar values (negatives in red parentheses)
- Expandable rows: `.toggle-arrow` rotation pattern, `.sector-detail-row` sandstone background
- Section boxes: reuse `box-flow` (blue border), `box-buyers` (green), `box-sellers` (red) from Sector Rotation
- Section labels: `.sector-section-label` uppercase, grey, faint separator
- Color coding: green for inflows, red for outflows, `_flowClass()` for cell styling
- Summary header: same pattern as Conviction tab's subject label (`EQT -> Sector: Energy | Industry: Oil & Gas E&P`)
- Totals row: `.register-totals-row` pattern at bottom of tables

**Charts (Chart.js, already loaded via CDN in the app):**

Three charts where visual impact exceeds what tables can convey:

1. **Subject vs Sector bar chart** (Section 1, right side of summary box):
   Grouped bar chart — EQT flow vs sector flow per quarter. Two bars per quarter (blue = subject, grey = sector). Immediately shows if EQT is moving with or against the sector. Small, inline (250px height), sits beside the summary table.

2. **Substitution waterfall** (Section 2, above the peer table):
   Horizontal bar chart showing the top 5 substitution peers as bars extending left (selling subject) and right (buying peer), or vice versa. Each bar is split: red portion = contra subject flow, green = peer flow. Visually shows the "swap" pattern. This is the hero chart — the most novel analytical view.

3. **Top 5 Sector Movers bar chart** (Section 4):
   Simple horizontal bar chart, one bar per ticker, colored green/red by net flow direction. Subject ticker bar highlighted with a distinct border. Shows relative magnitude at a glance.

**Chart conventions to follow:**
- Use `Chart.js` (already available in the app via CDN)
- Canvas wrapped in `.chart-card` div (existing CSS class, `break-inside: avoid` for print)
- `setTimeout(100)` before Chart.js init (existing pattern to let DOM render canvas first)
- Destroy previous chart instance before re-init (`if (chart) chart.destroy()`)
- Colors from CSS vars: `--oxford-blue`, `--glacier-blue`, green `#2e7d32`, red `#c62828`
- Charts are supplementary — tables carry the full data; charts provide the "at a glance" view

## Layout

```
[By Parent] [By Fund]    [Active Only]

EQT — Oil & Gas E&P | Energy
────────────────────────────────────────────────────────────────────
SECTION 1: SUBJECT vs SECTOR SUMMARY (blue border box)
┌─────────────────────────────────────┬────────────────────────────┐
│ Table (left)                        │ Chart (right, 250px)       │
│                Q1→Q2  Q2→Q3  Total  │  ██ EQT  ░░ Sector        │
│ EQT Flow       +$1.2B ($800M) ...   │  grouped bars per quarter  │
│ Sector Flow   +$20.9B +$12.2B ...   │  shows if EQT moves with  │
│ EQT % Sector    5.7%  (6.6%) ...    │  or against the sector     │
└─────────────────────────────────────┴────────────────────────────┘

SECTION 2: SUBSTITUTION WATERFALL CHART
┌──────────────────────────────────────────────────────────────────┐
│  Horizontal bars: top 5 peer swaps                               │
│  COP    ████████████████ +$800M  ◄►  ████████ ($600M)           │
│  DVN    ████████ +$400M          ◄►  ██████ ($300M)             │
│  FANG   ███ ($200M)              ◄►  ██████████ +$350M          │
│  (green = peer inflow, red = contra subject flow)                │
└──────────────────────────────────────────────────────────────────┘

SECTION 3: INDUSTRY PEER SUBSTITUTIONS — Oil & Gas E&P
  #  Peer    Direction        Net Peer Flow   Contra EQT Flow   # Funds
  1  COP     Replacing EQT      +$800M          ($600M)          28
  2  DVN     Replacing EQT      +$400M          ($300M)          15
  3  FANG    Replaced by EQT    ($200M)         +$350M           12
     ▶ expand → shows entity-level detail for that peer
────────────────────────────────────────────────────────────────────
SECTION 4: SECTOR PEER SUBSTITUTIONS — Energy (broader, outside E&P)
  Same table format, showing XOM, CVX etc. from other subsectors
────────────────────────────────────────────────────────────────────
SECTION 5: TOP 5 SECTOR MOVERS
┌─────────────────────────────────────┬────────────────────────────┐
│ Table (left)                        │ Horizontal bar chart       │
│ #  Ticker  Industry     Net Flow    │  XOM  ████████████ +$5.0B  │
│ 1  XOM     Integrated    +$5.0B     │  COP  ██████ +$2.1B       │
│ 2  COP     E&P           +$2.1B     │ ★EQT  ████ +$900M        │
│ ★  EQT     E&P           +$900M     │  DVN  ███ ($400M)         │
│    (subject highlighted)            │  (subject bar highlighted) │
└─────────────────────────────────────┴────────────────────────────┘

SECTION 6: TOP 10 ENTITY ROTATION STORIES
  #  Entity          EQT Flow    Sector Flow   Top Contra-Peers
  1  Capital Group   ($500M)     +$200M        COP +$300M, DVN +$200M
  2  Fidelity        +$800M      +$1.2B        EOG ($400M), OXY ($200M)
```

## Files to Modify

| File | Changes |
|------|---------|
| `scripts/queries.py` | New `get_peer_rotation(ticker, active_only, level)` + `get_peer_rotation_detail(ticker, peer, active_only, level)` |
| `scripts/app.py` | New `/api/peer_rotation` + `/api/peer_rotation_detail` endpoints |
| `web/static/app.js` | New `loadPeerRotation()`, `_renderPeerRotation()`, `_togglePeerDetail()` + wire into `switchTab()` |
| `web/templates/index.html` | Add `<button class="tab" data-tab="peer-rotation">Peer Rotation</button>` after Sector Rotation |
| `web/static/style.css` | `.peer-highlight` for subject ticker row in top 5; reuse `box-flow`, `box-buyers`, `box-sellers` |

## Backend: `get_peer_rotation(ticker, active_only, level)`

### Step 1: Get subject context
```sql
SELECT sector, industry FROM market_data WHERE ticker = :ticker
```

### Step 2: Compute per-entity per-ticker flows within sector

Same CTE pattern as `get_sector_flow_detail` but **retains the ticker dimension**:

```sql
WITH h_agg AS (
    -- Pre-aggregate per (cik, ticker, quarter)
    SELECT cik, inst_parent_name, manager_name, manager_type,
           ticker, quarter,
           SUM(shares) AS shares, SUM(market_value_usd) AS market_value_usd
    FROM holdings
    WHERE ticker IS NOT NULL AND quarter IN (:q_from, :q_to)
    GROUP BY cik, inst_parent_name, manager_name, manager_type, ticker, quarter
),
sector_flows AS (
    -- Continuing + new
    SELECT {group_expr} AS entity, c.ticker,
           (c.shares - COALESCE(p.shares, 0))
             * (c.market_value_usd / NULLIF(c.shares, 0)) AS active_flow
    FROM h_agg c
    LEFT JOIN h_agg p ON c.cik = p.cik AND c.ticker = p.ticker AND p.quarter = :q_from
    JOIN market_data md ON c.ticker = md.ticker AND md.sector = :sector
    WHERE c.quarter = :q_to {active_filter}
    UNION ALL
    -- Exits
    SELECT {group_expr_p} AS entity, p.ticker,
           -p.market_value_usd AS active_flow
    FROM h_agg p
    LEFT JOIN h_agg c ON p.cik = c.cik AND p.ticker = c.ticker AND c.quarter = :q_to
    JOIN market_data md ON p.ticker = md.ticker AND md.sector = :sector
    WHERE p.quarter = :q_from AND c.cik IS NULL {active_filter_p}
)
```

### Step 3: Substitution detection

From `sector_flows`, find entities with opposite-direction flows on subject vs peers:

```sql
substitutions AS (
    SELECT sf.entity, sf.ticker AS peer_ticker, sf.active_flow AS peer_flow,
           subj.subj_flow
    FROM sector_flows sf
    INNER JOIN (
        SELECT entity, SUM(active_flow) AS subj_flow
        FROM sector_flows WHERE ticker = :ticker
        GROUP BY entity
    ) subj ON sf.entity = subj.entity
    WHERE sf.ticker != :ticker
      AND SIGN(sf.active_flow) != SIGN(subj.subj_flow)
)
```

Aggregate by peer_ticker → rank by `SUM(MIN(ABS(peer_flow), ABS(subj_flow)))` (substitution magnitude).

### Step 4: Split into industry peers vs sector peers

Filter substitutions by `market_data.industry = :subject_industry` for industry section; exclude those for broader sector section.

### Step 5: Top 5 sector movers

```sql
SELECT ticker, SUM(active_flow) AS net_flow, ...
FROM sector_flows GROUP BY ticker
ORDER BY ABS(SUM(active_flow)) DESC LIMIT 5
```

Highlight subject ticker in results.

### Step 6: Entity rotation stories (top 10)

For each entity, compute total subject flow + total sector flow + top 3 contra-direction peer tickers.

### N-PORT support

When `level=fund`: swap `holdings` → `fund_holdings`, `cik` → `series_id`, group by `fund_name`. Same pattern as `get_sector_flows(level='fund')`.

## API Response Shape

```json
{
  "subject": {"ticker": "EQT", "sector": "Energy", "industry": "Oil & Gas E&P"},
  "periods": [{"label": "Q1 → Q2", "from": "2025Q1", "to": "2025Q2"}, ...],
  "subject_flows": {"2025Q1_2025Q2": {"net": ...}, ..., "total": {"net": ...}},
  "sector_flows": {"2025Q1_2025Q2": {"net": ...}, ..., "total": {"net": ...}},
  "subject_pct_of_sector": {"2025Q1_2025Q2": 5.7, ..., "total": 1.0},
  "industry_substitutions": [
    {"ticker": "COP", "industry": "Oil & Gas E&P", "direction": "replacing",
     "net_peer_flow": 800e6, "contra_subject_flow": -600e6, "num_entities": 28,
     "flows": {"2025Q1_2025Q2": ...}}
  ],
  "sector_substitutions": [
    {"ticker": "XOM", "industry": "Oil & Gas Integrated", ...}
  ],
  "top_sector_movers": [
    {"ticker": "XOM", "industry": "...", "net_flow": ..., "inflow": ...,
     "outflow": ..., "is_subject": false, "rank": 1}
  ],
  "entity_stories": [
    {"entity": "Capital Group", "subject_flow": -500e6, "sector_flow": 200e6,
     "top_contra_peers": [{"ticker": "COP", "flow": 300e6}, ...]}
  ]
}
```

## Frontend: `loadPeerRotation()`

- Requires `currentTicker` (shows error if no ticker entered)
- Single API call to `/api/peer_rotation?ticker=EQT&level=parent&active_only=0`
- Builds 5 sections (filter bar + 4 content sections) using DOM APIs
- Subject vs Sector summary uses `box-flow` blue border (reuse from sector rotation)
- Industry substitutions: expandable rows (click → `/api/peer_rotation_detail?ticker=EQT&peer=COP&...` → entity-level breakdown)
- Sector substitutions: same format, separate section
- Top 5 movers: simple table, subject row gets `.peer-highlight` class
- Entity stories: compact table, contra-peers shown inline

## Verification

1. Start Flask: `python3 scripts/app.py`
2. Enter `EQT` in ticker search
3. Click Peer Rotation tab
4. Verify: subject context shows "Oil & Gas E&P | Energy"
5. Verify: summary shows EQT flow vs Energy sector flow with % share
6. Verify: industry substitutions show COP, DVN, EOG, FANG, CTRA as E&P peers
7. Verify: sector substitutions show XOM, CVX etc. from other subsectors
8. Verify: By Fund toggle switches to N-PORT fund-level data
9. Verify: Active Only filters to active/hedge/activist managers
10. Verify: expanding a substitution peer row shows entity-level detail
11. Test with AAPL (Technology sector, 148 subsectors) to verify scale
