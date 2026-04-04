/* ================================================================
   13F Institutional Ownership Research — Frontend
   ================================================================ */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let tickerList = [];          // [{ticker, name}]
let currentTicker = '';
let currentTab = 'register';  // tab ID string
let currentQuery = 1;         // legacy query number for old endpoints
let currentData = [];         // raw JSON from last query
let sortCol = null;
let sortDir = 'asc';
const _sortState = {};  // per-tab sort state: tabId → {col, dir}
let autocompleteIdx = -1;     // keyboard selection index

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const tickerInput   = document.getElementById('ticker-input');
const loadBtn       = document.getElementById('load-btn');
const dropdown      = document.getElementById('autocomplete-dropdown');
const summaryCard   = document.getElementById('summary-card');
const tabContainer  = document.getElementById('tab-container');
const emptyState    = document.getElementById('empty-state');
const spinner       = document.getElementById('loading-spinner');
const tableWrap     = document.getElementById('results-table-wrap');
const errorMsg      = document.getElementById('error-msg');
const copyBtn       = document.getElementById('copy-btn');
const exportBtn     = document.getElementById('export-btn');
const coPanel       = document.getElementById('cross-ownership-panel');
const coAnalyzeBtn  = document.getElementById('co-analyze-btn');
const coActiveToggle = document.getElementById('co-active-toggle');
const coToggleLabel = document.getElementById('co-toggle-label');
const managerSelector = document.getElementById('manager-selector');
const managerDropdown = document.getElementById('manager-dropdown');
const loadPortfolioBtn = document.getElementById('load-portfolio-btn');

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function _negWrap(formatted, val) {
    // Wrap negative values in span with class for red coloring
    if (val < 0) return '<span class="negative">(' + formatted + ')</span>';
    return formatted;
}

function fmtDollars(val) {
    if (val == null || val === 0) return '\u2014';
    const abs = Math.abs(val);
    let s;
    if (abs >= 1e12) s = '$' + (abs / 1e12).toFixed(1) + 'T';
    else if (abs >= 1e9) s = '$' + (abs / 1e9).toFixed(1) + 'B';
    else if (abs >= 1e6) s = '$' + (abs / 1e6).toFixed(0) + 'M';
    else if (abs >= 1e3) s = '$' + (abs / 1e3).toFixed(0) + 'K';
    else s = '$' + abs.toLocaleString('en-US', {maximumFractionDigits: 0});
    return _negWrap(s, val);
}

function fmtShares(val) {
    if (val == null || val === 0) return '\u2014';
    const abs = Math.abs(val);
    let s;
    if (abs >= 1e9) s = (abs / 1e9).toFixed(1) + 'B';
    else if (abs >= 1e6) s = (abs / 1e6).toFixed(1) + 'M';
    else if (abs >= 1e3) s = (abs / 1e3).toFixed(1) + 'K';
    else s = abs.toLocaleString('en-US', {maximumFractionDigits: 0});
    return _negWrap(s, val);
}

function fmtPct(val) {
    if (val == null || val === 0) return '\u2014';
    const abs = Math.abs(val);
    return _negWrap(abs.toFixed(2) + '%', val);
}

function fmtNum(val) {
    if (val == null) return '\u2014';
    if (typeof val === 'number') {
        if (val === 0) return '\u2014';
        return _negWrap(Math.abs(val).toLocaleString('en-US', {maximumFractionDigits: 2}), val);
    }
    return String(val);
}

// ---------------------------------------------------------------------------
// Autocomplete
// ---------------------------------------------------------------------------
async function loadTickers() {
    try {
        const res = await fetch('/api/tickers');
        tickerList = await res.json();
    } catch (e) {
        console.error('Failed to load tickers:', e);
    }
}

function filterTickers(query) {
    if (!query || query.length < 2) return [];
    const q = query.toUpperCase();
    // Score matches: ticker-starts-with ranks higher than name-contains
    const scored = [];
    for (const t of tickerList) {
        const tickerMatch = t.ticker.toUpperCase().startsWith(q);
        const nameMatch = t.name && t.name.toUpperCase().includes(q);
        if (tickerMatch || nameMatch) {
            scored.push({...t, score: tickerMatch ? 0 : 1});
        }
    }
    scored.sort((a, b) => a.score - b.score || a.ticker.localeCompare(b.ticker));
    return scored.slice(0, 10);
}

function showDropdown(items) {
    if (!items.length) { hideDropdown(); return; }
    dropdown.innerHTML = items.map((t, i) =>
        `<div class="autocomplete-item${i === autocompleteIdx ? ' selected' : ''}" data-ticker="${t.ticker}">
            <span class="ticker">${t.ticker}</span>
            <span class="name">${t.name || ''}</span>
        </div>`
    ).join('');
    dropdown.classList.add('visible');
}

function hideDropdown() {
    dropdown.classList.remove('visible');
    dropdown.innerHTML = '';
    autocompleteIdx = -1;
}

tickerInput.addEventListener('input', () => {
    const val = tickerInput.value.trim();
    autocompleteIdx = -1;
    if (val.length < 2) { hideDropdown(); return; }
    const matches = filterTickers(val);
    showDropdown(matches);
});

tickerInput.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.autocomplete-item');
    if (!items.length) {
        if (e.key === 'Enter') { e.preventDefault(); loadTicker(); }
        return;
    }
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        autocompleteIdx = Math.min(autocompleteIdx + 1, items.length - 1);
        items.forEach((el, i) => el.classList.toggle('selected', i === autocompleteIdx));
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        autocompleteIdx = Math.max(autocompleteIdx - 1, 0);
        items.forEach((el, i) => el.classList.toggle('selected', i === autocompleteIdx));
    } else if (e.key === 'Enter') {
        e.preventDefault();
        if (autocompleteIdx >= 0 && autocompleteIdx < items.length) {
            tickerInput.value = items[autocompleteIdx].dataset.ticker;
        }
        hideDropdown();
        loadTicker();
    } else if (e.key === 'Escape') {
        hideDropdown();
    }
});

dropdown.addEventListener('click', (e) => {
    const item = e.target.closest('.autocomplete-item');
    if (item) {
        tickerInput.value = item.dataset.ticker;
        hideDropdown();
        loadTicker();
    }
});

document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-input-wrap')) hideDropdown();
});

// ---------------------------------------------------------------------------
// Load ticker
// ---------------------------------------------------------------------------
loadBtn.addEventListener('click', loadTicker);

async function loadTicker() {
    const ticker = tickerInput.value.trim().toUpperCase();
    if (!ticker) return;
    currentTicker = ticker;
    tickerInput.value = ticker;

    // Show UI
    emptyState.classList.add('hidden');
    summaryCard.classList.remove('hidden');
    tabContainer.classList.remove('hidden');

    // Load summary
    try {
        const res = await fetch(`/api/summary?ticker=${ticker}`);
        if (!res.ok) throw new Error('No data');
        const s = await res.json();
        document.getElementById('sum-company').textContent = s.company_name || ticker;
        document.getElementById('sum-quarter').textContent = s.latest_quarter || '\u2014';
        document.getElementById('sum-holdings').textContent = fmtDollars(s.total_value);
        document.getElementById('sum-float').textContent = fmtPct(s.total_pct_float);
        document.getElementById('sum-holders').textContent = s.num_holders != null ? s.num_holders.toLocaleString() : '\u2014';
        document.getElementById('sum-mktcap').textContent = fmtDollars(s.market_cap);
        document.getElementById('sum-price').textContent = s.price != null ? '$' + s.price.toFixed(2) : '\u2014';
        document.getElementById('sum-nport').textContent = s.nport_coverage != null
            ? s.nport_coverage + '% (' + s.nport_funds + ' funds)'
            : '\u2014';

        // Active/Passive split
        const activeVal = s.active_value || 0;
        const passiveVal = s.passive_value || 0;
        const total = activeVal + passiveVal;
        if (total > 0) {
            document.getElementById('sum-split').textContent =
                `${fmtDollars(activeVal)} / ${fmtDollars(passiveVal)}`;
        } else {
            document.getElementById('sum-split').textContent = '\u2014';
        }
    } catch (e) {
        document.getElementById('sum-company').textContent = ticker;
        ['sum-quarter','sum-holdings','sum-float','sum-holders','sum-split','sum-mktcap','sum-price','sum-nport']
            .forEach(id => document.getElementById(id).textContent = '\u2014');
    }

    // Load current tab
    switchTab(currentTab);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
// Tab ID → legacy query number mapping (for endpoints that use /api/queryN)
const TAB_QUERY_MAP = {
    'register': 1, 'conviction': 3,
    'fund-portfolio': 7, 'cross-ownership': 8,
    'sector-rotation': 9, 'aum': 14,
};

function switchTab(tabId) {
    // Save current sort state
    if (currentTab) _sortState[currentTab] = {col: sortCol, dir: sortDir};
    currentTab = tabId;
    currentQuery = TAB_QUERY_MAP[tabId] || 0;
    // Restore sort state for this tab (or reset)
    const saved = _sortState[tabId];
    sortCol = saved ? saved.col : null;
    sortDir = saved ? saved.dir : 'asc';
    // Hide all special panels
    managerSelector.classList.add('hidden');
    coPanel.classList.add('hidden');

    // Route to the right loader
    if (tabId === 'fund-portfolio') {
        managerSelector.classList.remove('hidden');
        loadManagerDropdown();
    } else if (tabId === 'cross-ownership') {
        coPanel.classList.remove('hidden');
        initCrossOwnership();
    } else if (tabId === 'ownership-trend') {
        loadOwnershipTrend();
    } else if (tabId === 'flow-analysis') {
        loadFlowAnalysis();
    } else if (tabId === 'new-exits') {
        loadNewExits();
    } else if (tabId === 'activist') {
        loadActivistTab();
    } else if (tabId === 'crowding') {
        loadCrowding();
    } else if (tabId === 'smart-money') {
        loadSmartMoney();
    } else if (tabId === 'short-squeeze') {
        loadShortSqueeze();
    } else if (tabId === 'peer-matrix') {
        loadHeatmap();
    } else if (currentQuery > 0) {
        loadQuery(currentQuery);
    }
}

document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        switchTab(tab.dataset.tab);
    });
});

// ---------------------------------------------------------------------------
// Load query data
// ---------------------------------------------------------------------------
let _lastExtraParams = {};

async function loadQuery(qnum, extraParams) {
    showSpinner();
    clearError();
    tableWrap.classList.add('loading');
    _lastExtraParams = extraParams || {};

    const params = new URLSearchParams();
    if (currentTicker) params.set('ticker', currentTicker);
    if (extraParams) {
        for (const [k, v] of Object.entries(extraParams)) params.set(k, v);
    }
    const url = `/api/query${qnum}?${params}`;

    try {
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        let raw;
        try {
            raw = await res.json();
        } catch (parseErr) {
            throw new Error('Invalid response from server — could not parse JSON');
        }
        hideSpinner();
        tableWrap.classList.remove('loading');
        tableWrap.innerHTML = '';

        // Validate response shape
        if (raw === null || raw === undefined) {
            throw new Error('Empty response from server');
        }
        if (raw.error) {
            throw new Error(raw.error);
        }

        if (qnum === 15) {
            currentData = raw;
            renderStats(raw);
        } else if (qnum === 7) {
            currentData = raw.positions || [];
            renderQuery7(raw);
        } else {
            currentData = raw;
            renderTable(raw, qnum);
        }
    } catch (e) {
        hideSpinner();
        tableWrap.classList.remove('loading');
        showError(e.message);
    }
}

// ---------------------------------------------------------------------------
// Table rendering
// ---------------------------------------------------------------------------

// Column definitions per query — only key, label, type (data format).
// Width, alignment, and visual role are auto-inferred from key+label names.
const QUERY_COLUMNS = {
    1: [
        {key: 'institution', label: 'Institution',  type: 'text'},
        {key: 'value_live',  label: 'Value (Live)', type: 'dollar'},
        {key: 'shares',      label: 'Shares',       type: 'shares'},
        {key: 'pct_float',   label: '% Float / NAV', type: 'pct'},
        {key: 'aum',         label: 'AUM ($M)',     type: 'num'},
        {key: 'type',        label: 'Type',         type: 'text'},
        {key: 'source',      label: 'Source',       type: 'text'},
    ],
    2: [
        {key: 'fund_name',     label: 'Institution / Fund', type: 'text'},
        {key: 'q1_shares',     label: 'Q1 Shares',          type: 'shares'},
        {key: 'q4_shares',     label: 'Q4 Shares',          type: 'shares'},
        {key: 'change_shares', label: 'Change',             type: 'shares'},
        {key: 'change_pct',    label: 'Chg%',               type: 'pct'},
        {key: 'type',          label: 'Type',               type: 'text'},
        {key: 'source',        label: 'Source',             type: 'text'},
    ],
    3: [
        {key: 'manager_name',      label: 'Active Holder',  type: 'text'},
        {key: 'position_value',    label: 'Position Value', type: 'dollar'},
        {key: 'pct_of_portfolio',  label: '% Portfolio',    type: 'pct'},
        {key: 'pct_of_float',     label: '% Float',         type: 'pct'},
        {key: 'mktcap_percentile', label: 'MktCap Pctile', type: 'pct'},
        {key: 'manager_type',     label: 'Type',            type: 'text'},
        {key: 'direction',        label: 'Direction',       type: 'text'},
        {key: 'since',            label: 'Since',           type: 'text'},
        {key: 'held_label',       label: 'Held',            type: 'text'},
        {key: 'source',           label: 'Source',          type: 'text'},
    ],
    4: [
        {key: 'category',        label: 'Category',     type: 'text'},
        {key: 'num_holders',     label: 'Holders',      type: 'num'},
        {key: 'total_shares',    label: 'Total Shares', type: 'shares'},
        {key: 'total_value',     label: 'Total Value',  type: 'dollar'},
        {key: 'total_pct_float', label: '% Float',      type: 'pct'},
        {key: 'pct_of_inst',    label: '% of Inst.',     type: 'pct'},
    ],
    5: [
        {key: 'holder',            label: 'Holder',     type: 'text'},
        {key: 'manager_type',      label: 'Type',       type: 'text'},
        {key: 'q1_shares',         label: 'Q1',         type: 'shares'},
        {key: 'q2_shares',         label: 'Q2',         type: 'shares'},
        {key: 'q3_shares',         label: 'Q3',         type: 'shares'},
        {key: 'q4_shares',         label: 'Q4',         type: 'shares'},
        {key: 'q1_to_q2',          label: 'Q1\u2192Q2', type: 'shares'},
        {key: 'q2_to_q3',          label: 'Q2\u2192Q3', type: 'shares'},
        {key: 'q3_to_q4',          label: 'Q3\u2192Q4', type: 'shares'},
        {key: 'full_year_change',   label: 'Full Yr',   type: 'shares'},
    ],
    6: [
        {key: 'manager_name',      label: 'Manager',       type: 'text'},
        {key: 'quarter',           label: 'Quarter',       type: 'text'},
        {key: 'shares',            label: 'Shares',        type: 'shares'},
        {key: 'market_value_usd',  label: 'Value (Filed)', type: 'dollar'},
        {key: 'market_value_live', label: 'Value (Live)',  type: 'dollar'},
        {key: 'pct_of_portfolio',  label: '% Portfolio',   type: 'pct'},
        {key: 'pct_of_float',     label: '% Float',        type: 'pct'},
    ],
    7: [
        {key: 'rank',              label: '#',             type: 'num'},
        {key: 'ticker',            label: 'Ticker',        type: 'text'},
        {key: 'issuer_name',       label: 'Issuer',        type: 'text'},
        {key: 'sector',            label: 'Sector',        type: 'text'},
        {key: 'shares',            label: 'Shares',        type: 'shares'},
        {key: 'market_value_live', label: 'Value (Live)',  type: 'dollar'},
        {key: 'pct_of_portfolio',  label: '% Portfolio',   type: 'pct'},
        {key: 'pct_of_float',     label: '% Float',        type: 'pct'},
        {key: 'market_cap',       label: 'Market Cap',      type: 'dollar'},
    ],
    8: [
        {key: 'ticker',         label: 'Ticker',         type: 'text'},
        {key: 'issuer_name',    label: 'Issuer',         type: 'text'},
        {key: 'shared_holders', label: 'Shared Holders', type: 'num'},
        {key: 'overlap_pct',    label: 'Overlap %',      type: 'pct'},
        {key: 'total_value',    label: 'Total Value',    type: 'dollar'},
    ],
    9: [
        {key: 'sector',       label: 'Sector',       type: 'text'},
        {key: 'num_stocks',   label: 'Stocks',       type: 'num'},
        {key: 'sector_value', label: 'Sector Value', type: 'dollar'},
        {key: 'pct_of_total', label: '% of Total',   type: 'pct'},
    ],
    10: [
        {key: 'manager_name',      label: 'Manager',      type: 'text'},
        {key: 'manager_type',      label: 'Type',         type: 'text'},
        {key: 'shares',            label: 'Shares',       type: 'shares'},
        {key: 'market_value_live', label: 'Value (Live)', type: 'dollar'},
        {key: 'pct_of_portfolio',  label: '% Portfolio',  type: 'pct'},
        {key: 'pct_of_float',     label: '% Float',       type: 'pct'},
    ],
    11: [
        {key: 'manager_name', label: 'Manager',          type: 'text'},
        {key: 'manager_type', label: 'Type',             type: 'text'},
        {key: 'q3_shares',    label: 'Q3 Shares',        type: 'shares'},
        {key: 'q3_value',     label: 'Q3 Value',         type: 'dollar'},
        {key: 'q3_pct',       label: '% Portfolio (Q3)', type: 'pct'},
    ],
    12: [
        {key: 'rank',            label: '#',            type: 'num'},
        {key: 'holder',          label: 'Holder',       type: 'text'},
        {key: 'total_pct_float', label: '% Float',      type: 'pct'},
        {key: 'cumulative_pct',  label: 'Cumulative %', type: 'pct'},
        {key: 'total_shares',    label: 'Shares',       type: 'shares'},
    ],
    13: [
        {key: 'ticker',         label: 'Ticker',   type: 'text'},
        {key: 'issuer_name',    label: 'Issuer',   type: 'text'},
        {key: 'buyers',         label: 'Buyers',   type: 'num'},
        {key: 'sellers',        label: 'Sellers',  type: 'num'},
        {key: 'new_positions',  label: 'New',      type: 'num'},
        {key: 'net_flow',       label: 'Net',      type: 'num'},
        {key: 'buy_pct',        label: 'Buy%',     type: 'pct'},
        {key: 'q4_total_value', label: 'Q4 Value', type: 'dollar'},
    ],
    14: [
        {key: 'manager_name',    label: 'Manager',       type: 'text'},
        {key: 'manager_type',    label: 'Type',          type: 'text'},
        {key: 'manager_aum_bn',  label: 'AUM ($B)',      type: 'num'},
        {key: 'position_mm',     label: 'Position ($M)', type: 'num'},
        {key: 'pct_of_portfolio', label: '% Portfolio',  type: 'pct'},
        {key: 'is_activist',     label: 'Activist',      type: 'text'},
    ],
};

// ---------------------------------------------------------------------------
// Auto-detect column visual role from key and label names
// ---------------------------------------------------------------------------
const _inferCache = {};

function inferColMeta(col) {
    const cacheKey = col.key + '|' + col.label + '|' + col.type;
    if (_inferCache[cacheKey]) return _inferCache[cacheKey];

    const k = (col.key || '').toLowerCase();
    const l = (col.label || '').toLowerCase();
    let result;

    // 1. Explicit type from column definition takes highest priority
    if (col.type === 'dollar')
        result = {w: '130px', align: 'right', visual: 'dollar'};
    else if (col.type === 'shares')
        result = {w: '100px', align: 'right', visual: 'shares'};
    else if (col.type === 'pct')
        result = {w: '95px', align: 'right', visual: 'pct'};

    // 2. Pattern matching on key and label for text/num columns
    else if (/^(#|rank|rn)$/.test(l) || /^rank$/.test(k))
        result = {w: '50px', align: 'right', visual: 'rank'};
    else if (/^ticker$/.test(k) && !/name|issuer|holder/.test(k))
        result = {w: '70px', align: 'left', visual: 'ticker'};
    else if (/^(type|manager_type|is_activist)$/.test(k) || /^(type|activist|strategy)$/.test(l))
        result = {w: '100px', align: 'center', visual: 'type'};
    else if (/^source$/.test(k) || /^source$/.test(l))
        result = {w: '110px', align: 'center', visual: 'source'};
    else if (/^quarter$/.test(k) || /^(quarter|date|period)$/.test(l))
        result = {w: '90px', align: 'center', visual: 'quarter'};
    else if (/^(category)$/.test(k) || /^(category)$/.test(l))
        result = {w: '200px', align: 'left', visual: 'name'};
    // Dollar detection by label/key pattern — but skip pre-scaled columns with unit in label like ($B), ($M)
    else if (/\(\$[bBmMkK]\)/.test(col.label))
        result = {w: '120px', align: 'right', visual: 'num'};
    else if (/(value|market.?cap|aum|assets|holdings)/.test(l) ||
             /(value|market_cap|aum|assets)/.test(k))
        result = {w: '130px', align: 'right', visual: 'dollar'};
    // Count columns
    else if (/^(num_|count|shared_)/.test(k) || /^(stocks|funds|holders|count|buyers|sellers|new)$/i.test(l))
        result = {w: '80px', align: 'center', visual: 'num'};
    // Change/delta columns
    else if (/(change|delta)/.test(k))
        result = {w: '100px', align: 'right', visual: 'change'};
    // Name/institution columns — widest, flex
    else if (/(name|institution|fund|holder|company|issuer|sector)/.test(k) ||
             /(institution|fund|holder|issuer|sector|manager|active holder)/.test(l))
        result = {w: null, align: 'left', visual: 'name'};
    // Percentage by label pattern
    else if (/(%|pct|float|weight|percentile|nav|chg|buy%)/.test(l) || /pct/.test(k))
        result = {w: '95px', align: 'right', visual: 'pct'};
    else if (col.type === 'num')
        result = {w: '80px', align: 'right', visual: 'num'};
    else
        result = {w: '120px', align: 'left', visual: 'default'};

    _inferCache[cacheKey] = result;
    return result;
}

/** Is this column a change/delta column that should get red/green coloring? */
function isChangeCol(col) {
    const k = (col.key || '').toLowerCase();
    const l = (col.label || '').toLowerCase();
    return /(change|delta|chg|net_flow|full_year|_to_)/.test(k) ||
           /(change|delta|chg|net|\u2192)/.test(l);
}

/** Does this query have a Type column? (for legend display) */
function queryHasType(qnum) {
    const cols = QUERY_COLUMNS[qnum];
    if (!cols) return false;
    return cols.some(c => inferColMeta(c).visual === 'type');
}

/** Find the first 'name' column key for hierarchy indent. */
function findNameKey(cols) {
    const nameCol = cols.find(c => inferColMeta(c).visual === 'name');
    return nameCol ? nameCol.key : null;
}

const PAGE_SIZE = 50;
let _currentPage = 0;
let _fullData = [];
let _currentQnum = 0;

function renderTable(data, qnum) {
    if (!data || !data.length) {
        tableWrap.innerHTML = '<div class="error-msg">No data available.</div>';
        return;
    }

    _fullData = data;
    _currentQnum = qnum;
    _currentPage = 0;
    _renderCurrentPage();
}

function _renderCurrentPage() {
    const data = _fullData;
    const qnum = _currentQnum;
    // Register tab (query1): show all rows, no pagination
    const noPagination = (qnum === 1);
    const totalPages = noPagination ? 1 : Math.ceil(data.length / PAGE_SIZE);
    const start = noPagination ? 0 : _currentPage * PAGE_SIZE;
    const pageData = noPagination ? data : (data.length > PAGE_SIZE ? data.slice(start, start + PAGE_SIZE) : data);

    const cols = QUERY_COLUMNS[qnum];

    // R16: Search filter for Register tab
    if (qnum === 1) {
        let filterBar = tableWrap.querySelector('.register-filter-bar');
        if (!filterBar) {
            filterBar = document.createElement('div');
            filterBar.className = 'register-filter-bar';
            filterBar.style.cssText = 'display:flex;gap:8px;align-items:center;padding:8px 0;';
            const searchInput = document.createElement('input');
            searchInput.type = 'text';
            searchInput.placeholder = 'Filter by institution name...';
            searchInput.style.cssText = 'padding:6px 12px;border:1px solid #ccc;border-radius:4px;font-size:13px;width:250px;';
            searchInput.autocomplete = 'off';
            searchInput.autocorrect = 'off';
            searchInput.spellcheck = false;
            searchInput.addEventListener('input', () => {
                const q = searchInput.value.toLowerCase();
                const table = tableWrap.querySelector('.data-table');
                if (!table) return;
                table.querySelectorAll('tbody tr').forEach(tr => {
                    const name = (tr.querySelector('td:nth-child(2)') || {}).textContent || '';
                    tr.style.display = !q || name.toLowerCase().includes(q) ? '' : 'none';
                });
            });
            const clearBtn = document.createElement('button');
            clearBtn.textContent = 'Clear';
            clearBtn.className = 'btn btn-secondary';
            clearBtn.style.fontSize = '12px';
            clearBtn.onclick = () => { searchInput.value = ''; searchInput.dispatchEvent(new Event('input')); };
            // R13: Heatmap toggle
            const heatmapToggle = document.createElement('button');
            heatmapToggle.className = 'btn btn-secondary';
            heatmapToggle.style.fontSize = '12px';
            heatmapToggle.textContent = 'Heatmap On';
            heatmapToggle.onclick = () => {
                const on = heatmapToggle.textContent === 'Heatmap On';
                heatmapToggle.textContent = on ? 'Heatmap Off' : 'Heatmap On';
                _applyHeatmapOverlay(on);
            };
            filterBar.appendChild(heatmapToggle);

            // R9: Source column toggle
            const sourceToggle = document.createElement('button');
            sourceToggle.className = 'btn btn-secondary';
            sourceToggle.style.fontSize = '12px';
            sourceToggle.style.marginLeft = 'auto';
            const sourceHidden = localStorage.getItem('hideSourceCol') === 'true';
            sourceToggle.textContent = sourceHidden ? 'Show Source' : 'Hide Source';
            sourceToggle.onclick = () => {
                const hide = localStorage.getItem('hideSourceCol') !== 'true';
                localStorage.setItem('hideSourceCol', hide);
                sourceToggle.textContent = hide ? 'Show Source' : 'Hide Source';
                _applySourceColumnVisibility();
            };
            filterBar.appendChild(searchInput);
            filterBar.appendChild(clearBtn);
            filterBar.appendChild(sourceToggle);
            tableWrap.appendChild(filterBar);
        }
    }

    if (!cols) {
        const keys = Object.keys(data[0]).filter(k => !k.startsWith('_'));
        renderTableFromKeys(pageData, keys);
    } else {
        const hasHierarchy = pageData.some(r => r.level === 1 || r.is_parent === true);
        const hasSections = pageData.some(r => r.section != null);
        const collapsible = hasHierarchy && (qnum === 1 || qnum === 2 || qnum === 3);
        renderHierarchicalTable(pageData, cols, qnum, hasHierarchy, hasSections, collapsible);
    }

    // R9: Apply source column visibility after render
    if (qnum === 1) _applySourceColumnVisibility();

    // R7: Add totals row at bottom of Register tab
    if (qnum === 1 && pageData.length > 0) {
        const table = tableWrap.querySelector('.data-table');
        if (table) {
            const tbody = table.querySelector('tbody');
            const parentRows = pageData.filter(r => !r.level || r.level === 0);
            const totals = document.createElement('tr');
            totals.style.cssText = 'font-weight:700;border-top:3px solid #002147;background:#f0f4f8;';
            // # col
            const tdNum = document.createElement('td');
            tdNum.className = 'col-rownum';
            totals.appendChild(tdNum);
            // Build totals per column
            const cols = QUERY_COLUMNS[1];
            cols.forEach(c => {
                const td = document.createElement('td');
                td.style.textAlign = _isNumericCol(c.type) ? 'right' : 'left';
                if (c.key === 'institution') {
                    td.textContent = 'TOTAL (' + parentRows.length + ' holders)';
                } else if (c.type === 'dollar' || c.type === 'shares') {
                    let sum = 0;
                    parentRows.forEach(r => { if (r[c.key]) sum += r[c.key]; });
                    td.textContent = sum ? _formatCellValue(sum, c.type) : '—';
                } else if (c.key === 'pct_float') {
                    let sum = 0;
                    parentRows.forEach(r => { if (r[c.key]) sum += r[c.key]; });
                    td.textContent = sum ? fmtPct(sum) : '—';
                } else {
                    td.textContent = '';
                }
                totals.appendChild(td);
            });
            tbody.appendChild(totals);
        }
    }

    // Pagination controls
    if (totalPages > 1) {
        const nav = document.createElement('div');
        nav.style.cssText = 'display:flex;justify-content:center;align-items:center;gap:8px;padding:12px;font-size:13px;';
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '← Prev';
        prevBtn.className = 'co-view-btn';
        prevBtn.disabled = _currentPage === 0;
        prevBtn.addEventListener('click', () => { _currentPage--; _renderCurrentPage(); });
        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next →';
        nextBtn.className = 'co-view-btn';
        nextBtn.disabled = _currentPage >= totalPages - 1;
        nextBtn.addEventListener('click', () => { _currentPage++; _renderCurrentPage(); });
        const info = document.createElement('span');
        info.style.color = '#666';
        info.textContent = `Page ${_currentPage + 1} of ${totalPages} (${data.length} rows)`;
        nav.appendChild(prevBtn);
        nav.appendChild(info);
        nav.appendChild(nextBtn);
        tableWrap.appendChild(nav);
    }
}

/**
 * Single reusable renderer for ALL tables — flat and hierarchical.
 * Auto-infers column widths and alignment from key/label names.
 * Applies: fixed layout, colgroup widths, header alignment, name ellipsis
 * with tooltip, hierarchy indent, change/delta red/green coloring, and
 * color-coding legend on tabs with a Type column.
 */
function renderHierarchicalTable(data, cols, qnum, hasHierarchy, hasSections, collapsible) {
    const showLegend = queryHasType(qnum);
    const nameKey = findNameKey(cols);

    // --- Table + colgroup ---
    const table = document.createElement('table');
    table.className = 'data-table';

    const colgroup = document.createElement('colgroup');
    cols.forEach(col => {
        const cg = document.createElement('col');
        const meta = inferColMeta(col);
        if (meta.w) cg.style.width = meta.w;
        colgroup.appendChild(cg);
    });
    table.appendChild(colgroup);

    // --- Header with # column ---
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    const thNum = document.createElement('th');
    thNum.textContent = '#';
    thNum.style.textAlign = 'right';
    thNum.style.width = '35px';
    headerRow.appendChild(thNum);
    cols.forEach((col, ci) => {
        const th = document.createElement('th');
        const meta = inferColMeta(col);
        th.classList.add('col-' + meta.align);
        th.textContent = col.label;
        th.dataset.colIdx = ci;
        const arrow = document.createElement('span');
        arrow.className = 'sort-arrow';
        th.appendChild(arrow);
        th.addEventListener('click', () => sortTable(data, cols, ci, qnum));
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // --- Body with row numbers and tier breaks ---
    const tbody = document.createElement('tbody');
    let lastSection = null;
    let parentIdx = 0;  // unique ID for collapsible groups
    let parentRowNum = 0;  // counts only parent-level rows

    data.forEach(row => {
        // Section headers (Query 2 entries/exits)
        if (hasSections && row.section !== lastSection) {
            lastSection = row.section;
            const sectionLabels = {
                'entries': 'NEW ENTRIES (>100K shares)',
                'exits': 'FULL EXITS (>100K shares)',
            };
            if (sectionLabels[row.section]) {
                const sectionTr = document.createElement('tr');
                sectionTr.className = 'section-header';
                const td = document.createElement('td');
                td.colSpan = cols.length;
                td.textContent = sectionLabels[row.section];
                sectionTr.appendChild(td);
                tbody.appendChild(sectionTr);
            }
        }

        const tr = document.createElement('tr');

        // Track parent ID for collapsible grouping
        if (collapsible && row.is_parent) {
            parentIdx++;
            tr.dataset.parentId = 'p' + parentIdx;
            tr.classList.add('collapsible-parent');
        } else if (collapsible && row.level === 1) {
            tr.dataset.childOf = 'p' + parentIdx;
            tr.classList.add('child-row');  // hidden by default via CSS
        }

        if (row.level === 1) tr.classList.add('level-1');
        if (row.is_parent) tr.classList.add('parent-row');

        // Row number: parent=bold rank in # column, children=blank # column (rank shown in Institution col)
        const tdRowNum = document.createElement('td');
        tdRowNum.className = 'col-rownum';
        if (!row.level || row.level === 0) {
            parentRowNum++;
            tdRowNum.textContent = parentRowNum;
            tdRowNum.style.fontWeight = '700';
            if (TIER_BREAKS.includes(parentRowNum)) {
                tr.style.borderBottom = '1px solid #ccc';
            }
        }
        tr.appendChild(tdRowNum);

        // Type tint
        const rtype = row.type || row.manager_type || '';
        if (rtype && rtype !== 'unknown') {
            tr.classList.add('type-' + rtype.replace(/[^a-z_]/gi, '').toLowerCase());
        }

        cols.forEach(col => {
            const td = document.createElement('td');
            const meta = inferColMeta(col);
            td.classList.add('col-' + meta.align);
            let val = row[col.key];

            // --- Name columns: ellipsis + tooltip + hierarchy ---
            if (meta.visual === 'name') {
                td.classList.add('col-text-overflow');
                let displayVal;
                if (hasHierarchy && col.key === nameKey) {
                    if (row.is_parent) {
                        const name = row.institution || val || '';
                        // Add toggle arrow after name for collapsible parents
                        if (collapsible) {
                            td.appendChild(document.createTextNode(name + ' '));
                            const arrow = document.createElement('span');
                            arrow.className = 'toggle-arrow';
                            arrow.textContent = '\u25B6';  // ▶
                            td.appendChild(arrow);
                        } else {
                            td.textContent = name;
                        }
                        displayVal = null; // already set via DOM
                    } else if (row.level === 1) {
                        td.classList.add('col-indent');
                        td.style.paddingLeft = '24px';
                        const childRank = row.rank ? row.rank + '. ' : '';
                        displayVal = childRank + (val || '');
                    } else {
                        displayVal = val != null ? String(val) : '';
                    }
                } else {
                    displayVal = val != null ? String(val) : '';
                }
                if (displayVal !== null) {
                    td.textContent = displayVal;
                }
                // Tooltip: clean name without arrow/prefix
                const tooltipText = (row.institution || val || '').replace(/^\u21B3 \*? ?/, '');
                td.title = tooltipText;
            }
            // --- Change/delta columns: red/green coloring ---
            else if (isChangeCol(col) && typeof val === 'number' && val !== 0) {
                td.innerHTML = formatCell(val, fmtType(col));
                td.style.color = val < 0 ? '#C0392B' : '#27AE60';
            }
            // --- Direction column: colored badge ---
            else if (col.key === 'direction') {
                if (!val) { td.innerHTML = '\u2014'; }
                else if (val === 'ADDING') td.innerHTML = '<span class="positive">\u2191 Adding</span>';
                else if (val === 'TRIMMING') td.innerHTML = '<span class="negative">\u2193 Trimming</span>';
                else if (val === 'STABLE') td.innerHTML = '<span style="color:#666">\u2192 Stable</span>';
                else if (val === 'NEW') td.innerHTML = '<span class="badge-new">NEW</span>';
                else if (val === 'EXIT') td.innerHTML = '<span class="badge-exit">EXIT</span>';
                else td.innerHTML = '\u2014';
            }
            // --- Held column: color-coded ---
            else if (col.key === 'held_label' && val) {
                const count = parseInt(val);
                const color = count >= 4 ? '#1A8A4A' : (count >= 3 ? '#27AE60' : (count >= 2 ? '#E67E22' : '#999'));
                const weight = count >= 4 ? '700' : '400';
                td.innerHTML = '<span style="color:' + color + ';font-weight:' + weight + '">' + val + '</span>';
            }
            // --- Source column: render as badge with optional tooltip ---
            else if (col.key === 'source' && val) {
                const note = row.subadviser_note;
                if (val !== 'N-PORT' && note) {
                    // 13F badge with subadviser tooltip
                    const wrapper = document.createElement('span');
                    wrapper.className = 'tooltip-wrapper';
                    const badge = document.createElement('span');
                    badge.className = 'badge badge-13f';
                    badge.textContent = val;
                    wrapper.appendChild(badge);
                    const icon = document.createElement('span');
                    icon.className = 'tooltip-icon';
                    icon.textContent = 'i';
                    wrapper.appendChild(icon);
                    const tip = document.createElement('span');
                    tip.className = 'tooltip-text';
                    tip.textContent = note;
                    wrapper.appendChild(tip);
                    td.appendChild(wrapper);
                } else {
                    const badge = document.createElement('span');
                    badge.className = val === 'N-PORT' ? 'badge badge-nport' : 'badge badge-13f';
                    badge.textContent = val;
                    td.appendChild(badge);
                }
            }
            // --- All other columns ---
            else {
                td.innerHTML = formatCell(val, fmtType(col));
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    // --- Collapsible click handlers ---
    if (collapsible) {
        tbody.addEventListener('click', (e) => {
            const parentRow = e.target.closest('tr.collapsible-parent');
            if (!parentRow) return;
            const pid = parentRow.dataset.parentId;
            const isExpanded = parentRow.classList.toggle('expanded');
            // Toggle all child rows for this parent
            tbody.querySelectorAll(`tr[data-child-of="${pid}"]`).forEach(child => {
                child.classList.toggle('visible', isExpanded);
            });
        });
    }

    // --- Assemble (don't clear — caller handles clearing) ---
    if (showLegend) tableWrap.appendChild(buildLegend());
    tableWrap.appendChild(table);
}

/** Build the color-coding legend bar. */
function buildLegend() {
    const legend = document.createElement('div');
    legend.className = 'color-legend';
    [
        ['sw-passive',      'Passive'],
        ['sw-active',       'Active'],
        ['sw-quantitative', 'Quantitative'],
        ['sw-activist',     'Activist'],
        ['sw-mixed',        'Mixed'],
        ['sw-unknown',      'Unknown'],
    ].forEach(([cls, label]) => {
        const item = document.createElement('span');
        item.className = 'legend-item';
        item.innerHTML = `<span class="legend-swatch ${cls}"></span>${label}`;
        legend.appendChild(item);
    });
    return legend;
}

/** Fallback renderer for unknown query structures — also uses inferColMeta. */
function renderTableFromKeys(data, keys) {
    const cols = keys.map(k => ({key: k, label: k, type: 'text'}));
    renderHierarchicalTable(data, cols, 0, false, false);
}

// ---------------------------------------------------------------------------
// Ownership Concentration Heatmap (Peer Matrix tab)
// ---------------------------------------------------------------------------
async function loadHeatmap() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        // Get peers from cross-ownership input if available
        const peersInput = document.getElementById('cross-tickers');
        const peers = peersInput ? peersInput.value : '';
        const res = await fetch(`/api/heatmap?ticker=${currentTicker}&peers=${peers}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        hideSpinner();
        const wrap = tableWrap;

        if (!data.cells || !data.cells.length) {
            wrap.innerHTML = '<div class="no-data">No heatmap data available.</div>';
            return;
        }

        const info = document.createElement('div');
        info.style.cssText = 'padding:12px;background:#f0f4f8;border-radius:6px;margin-bottom:16px;font-size:13px;';
        info.innerHTML = '<b>Ownership Concentration:</b> Top 15 institutional holders by % of float across selected tickers. Darker = higher concentration.';
        wrap.appendChild(info);

        // Build heatmap table
        const tickers = data.tickers;
        const managers = data.managers;
        const cellMap = {};
        data.cells.forEach(c => { cellMap[`${c.manager}|${c.ticker}`] = c; });

        const table = document.createElement('table');
        table.className = 'data-table';
        table.style.fontSize = '12px';

        // Header row
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        headerRow.innerHTML = '<th style="min-width:200px">Manager</th>';
        tickers.forEach(t => {
            headerRow.innerHTML += `<th style="text-align:center;min-width:70px">${t}</th>`;
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Data rows
        const tbody = document.createElement('tbody');
        managers.forEach(mgr => {
            const row = document.createElement('tr');
            row.innerHTML = `<td style="white-space:nowrap;font-weight:500">${mgr}</td>`;
            tickers.forEach(t => {
                const cell = cellMap[`${mgr}|${t}`];
                const pct = cell ? cell.pct_float : null;
                const val = cell ? cell.value : null;
                let bg = '#f8f9fa';
                let color = '#999';
                if (pct != null && pct > 0) {
                    const intensity = Math.min(pct / 15, 1); // 15% = max intensity
                    const r = Math.round(255 - intensity * 200);
                    const g = Math.round(255 - intensity * 100);
                    const b = Math.round(255 - intensity * 50);
                    bg = `rgb(${r},${g},${b})`;
                    color = intensity > 0.5 ? '#fff' : '#333';
                }
                const title = val ? `${fmtDollars(val)} | ${(pct||0).toFixed(2)}% of float` : '';
                row.innerHTML += `<td style="text-align:center;background:${bg};color:${color};cursor:default" title="${title}">${pct != null ? pct.toFixed(1) + '%' : '—'}</td>`;
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
    } catch (e) { hideSpinner(); showError(e.message); }
}

// ---------------------------------------------------------------------------
// Manager Profile (click-through from any manager name)
// ---------------------------------------------------------------------------
async function loadManagerProfile(managerName) {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const res = await fetch(`/api/manager_profile?manager=${encodeURIComponent(managerName)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        hideSpinner();
        const wrap = tableWrap;

        // Summary card
        const summary = document.createElement('div');
        summary.style.cssText = 'padding:16px;background:#f0f4f8;border-radius:6px;margin-bottom:16px;display:flex;gap:32px;flex-wrap:wrap;';
        summary.innerHTML = `
            <div><b>${data.manager}</b></div>
            <div>Type: <b>${data.manager_type || 'Unknown'}</b></div>
            <div>Positions: <b>${(data.num_positions || 0).toLocaleString()}</b></div>
            <div>Total Value: <b>${fmtDollars(data.total_value)}</b></div>
            <div>Sub-entities: <b>${data.num_ciks || 0}</b></div>
        `;
        wrap.appendChild(summary);

        // Quarterly trend
        if (data.quarterly_trend && data.quarterly_trend.length) {
            wrap.appendChild(sectionHeader('Quarterly Trend'));
            wrap.appendChild(buildSimpleTable(data.quarterly_trend, [
                {key: 'quarter', label: 'Quarter', type: 'text'},
                {key: 'positions', label: 'Positions', type: 'num'},
                {key: 'total_value', label: 'Total Value', type: 'dollar'},
            ]));
        }

        // Sector allocation
        if (data.sector_allocation && data.sector_allocation.length) {
            wrap.appendChild(sectionHeader('Sector Allocation'));
            wrap.appendChild(buildSimpleTable(data.sector_allocation, [
                {key: 'sector', label: 'Sector', type: 'text'},
                {key: 'tickers', label: 'Tickers', type: 'num'},
                {key: 'value', label: 'Value', type: 'dollar'},
            ]));
        }

        // Top holdings
        if (data.top_holdings && data.top_holdings.length) {
            wrap.appendChild(sectionHeader('Top 50 Holdings'));
            wrap.appendChild(buildSimpleTable(data.top_holdings, [
                {key: 'ticker', label: 'Ticker', type: 'text'},
                {key: 'issuer_name', label: 'Issuer', type: 'text'},
                {key: 'shares', label: 'Shares', type: 'shares'},
                {key: 'market_value_usd', label: 'Filed Value', type: 'dollar'},
                {key: 'market_value_live', label: 'Live Value', type: 'dollar'},
                {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
                {key: 'pct_of_float', label: '% Float', type: 'pct'},
            ]));
        }

        // Back button
        const back = document.createElement('button');
        back.className = 'btn btn-secondary';
        back.style.marginTop = '16px';
        back.textContent = '← Back to ' + document.querySelector('.tab.active').textContent;
        back.onclick = () => switchTab(document.querySelector('.tab.active').dataset.tab);
        wrap.appendChild(back);
    } catch (e) { hideSpinner(); showError(e.message); }
}

async function loadCrowding() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const res = await fetch(`/api/crowding?ticker=${currentTicker}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        hideSpinner();
        const wrap = tableWrap;
        // Top holders by % float
        if (data.holders && data.holders.length) {
            wrap.appendChild(sectionHeader('Top Holders by % of Float'));
            wrap.appendChild(buildSimpleTable(data.holders, [
                {key: 'holder', label: 'Holder', type: 'text'},
                {key: 'manager_type', label: 'Type', type: 'text'},
                {key: 'pct_float', label: '% Float', type: 'pct'},
                {key: 'value', label: 'Value', type: 'dollar'},
            ]));
        }
        // Short interest history
        if (data.short_history && data.short_history.length) {
            wrap.appendChild(sectionHeader('Daily Short Sale Volume'));
            wrap.appendChild(buildSimpleTable(data.short_history, [
                {key: 'report_date', label: 'Date', type: 'text'},
                {key: 'short_volume', label: 'Short Vol', type: 'shares'},
                {key: 'total_volume', label: 'Total Vol', type: 'shares'},
                {key: 'short_pct', label: 'Short %', type: 'pct'},
            ]));
        }
    } catch (e) { hideSpinner(); showError(e.message); }
}

async function loadSmartMoney() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const res = await fetch(`/api/smart_money?ticker=${currentTicker}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        hideSpinner();
        const wrap = tableWrap;
        // Summary
        if (data.short_pct != null) {
            const summary = document.createElement('div');
            summary.style.cssText = 'padding:12px;background:#f8f9fa;border-radius:6px;margin-bottom:16px;font-size:13px;';
            summary.innerHTML = `<b>Short Volume:</b> ${(data.short_pct || 0).toFixed(1)}% of daily volume (${data.short_date || ''})`;
            wrap.appendChild(summary);
        }
        // Long positions by type
        if (data.long_by_type && data.long_by_type.length) {
            wrap.appendChild(sectionHeader('Long Positions by Manager Type'));
            wrap.appendChild(buildSimpleTable(data.long_by_type, [
                {key: 'manager_type', label: 'Type', type: 'text'},
                {key: 'holders', label: 'Holders', type: 'num'},
                {key: 'long_shares', label: 'Long Shares', type: 'shares'},
                {key: 'long_value', label: 'Long Value', type: 'dollar'},
            ]));
        }
        // N-PORT short positions
        if (data.nport_shorts && data.nport_shorts.length) {
            wrap.appendChild(sectionHeader('Fund Short Positions (N-PORT)'));
            wrap.appendChild(buildSimpleTable(data.nport_shorts, [
                {key: 'fund_name', label: 'Fund', type: 'text'},
                {key: 'shares_short', label: 'Shares Short', type: 'shares'},
                {key: 'short_value', label: 'Short Value', type: 'dollar'},
                {key: 'quarter', label: 'Quarter', type: 'text'},
            ]));
        }
        // Long vs Short comparison
        try {
            const slRes = await fetch(`/api/short_long?ticker=${currentTicker}`);
            if (slRes.ok) {
                const slData = await slRes.json();
                if (slData.long_short_managers && slData.long_short_managers.length) {
                    wrap.appendChild(sectionHeader('Managers Both Long (13F) and Short (N-PORT)'));
                    wrap.appendChild(buildSimpleTable(slData.long_short_managers, [
                        {key: 'manager', label: 'Manager', type: 'text'},
                        {key: 'fund_name', label: 'Short Fund', type: 'text'},
                        {key: 'long_shares', label: 'Long Shares', type: 'shares'},
                        {key: 'long_value_k', label: 'Long Value', type: 'dollar'},
                        {key: 'short_shares', label: 'Short Shares', type: 'shares'},
                        {key: 'net_shares', label: 'Net Shares', type: 'shares'},
                    ]));
                }
                if (slData.short_only_funds && slData.short_only_funds.length) {
                    wrap.appendChild(sectionHeader('Short-Only Funds (No 13F Long Position)'));
                    wrap.appendChild(buildSimpleTable(slData.short_only_funds, [
                        {key: 'fund_name', label: 'Fund', type: 'text'},
                        {key: 'adviser', label: 'Adviser', type: 'text'},
                        {key: 'short_shares', label: 'Short Shares', type: 'shares'},
                        {key: 'short_value', label: 'Short Value', type: 'dollar'},
                    ]));
                }
            }
        } catch (e2) { /* short_long is optional */ }
    } catch (e) { hideSpinner(); showError(e.message); }
}

// ---------------------------------------------------------------------------
// Short Squeeze tab — shows candidates with high short + high inst ownership
// ---------------------------------------------------------------------------
async function loadShortSqueeze() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const res = await fetch('/api/short_squeeze');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        hideSpinner();
        const wrap = tableWrap;
        if (data.candidates && data.candidates.length) {
            const info = document.createElement('div');
            info.style.cssText = 'padding:12px;background:#fff3cd;border:1px solid #ffc107;border-radius:6px;margin-bottom:16px;font-size:13px;';
            info.innerHTML = '<b>Short Squeeze Candidates:</b> Tickers with high short interest (>15%) and high institutional ownership. Squeeze Score = Short% x Institutional/Float ratio.';
            wrap.appendChild(info);
            wrap.appendChild(buildSimpleTable(data.candidates, [
                {key: 'ticker', label: 'Ticker', type: 'text'},
                {key: 'max_short_pct', label: 'Short %', type: 'pct'},
                {key: 'inst_pct_float', label: 'Inst % Float', type: 'pct'},
                {key: 'squeeze_score', label: 'Squeeze Score', type: 'num'},
                {key: 'num_holders', label: 'Holders', type: 'num'},
                {key: 'total_value', label: 'Inst Value', type: 'dollar'},
                {key: 'market_cap', label: 'Market Cap', type: 'dollar'},
            ]));
        } else {
            wrap.innerHTML = '<div class="no-data">No short squeeze candidates found (requires short_interest data with >15% short).</div>';
        }
    } catch (e) { hideSpinner(); showError(e.message); }
}

// ---------------------------------------------------------------------------
// Ownership Trend tab (3 sub-views)
// ---------------------------------------------------------------------------
let _otSubView = 'summary';  // 'summary' | 'changes'

async function loadOwnershipTrend() {
    clearError(); tableWrap.innerHTML = '';
    // Render sub-view selector (2 views: Summary + Cohort combined, and Holder Changes)
    const bar = document.createElement('div');
    bar.className = 'sub-view-bar';
    ['summary', 'changes'].forEach(v => {
        const btn = document.createElement('button');
        btn.className = 'co-view-btn' + (v === _otSubView ? ' active' : '');
        btn.textContent = v === 'summary' ? 'Quarterly Summary & Cohort' : 'Holder Changes';
        btn.addEventListener('click', () => { _otSubView = v; loadOwnershipTrend(); });
        bar.appendChild(btn);
    });
    tableWrap.appendChild(bar);

    if (_otSubView === 'summary') {
        await loadOTSummary();
        // Also load cohort inline below summary
        await loadOTCohort();
    } else {
        // Reuse existing query2 — fetch and render inline
        showSpinner();
        try {
            const res = await fetch(`/api/query2?ticker=${currentTicker}`);
            if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
            currentData = await res.json();
            currentQuery = 2;
            hideSpinner();
            const savedBar = tableWrap.querySelector('.sub-view-bar');
            renderTable(currentData, 2);
            if (savedBar) tableWrap.insertBefore(savedBar, tableWrap.firstChild);
        } catch (e) { hideSpinner(); showError(e.message); }
    }
}

async function loadOTSummary() {
    showSpinner();
    try {
        const res = await fetch(`/api/ownership_trend_summary?ticker=${currentTicker}`);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        const savedBar = tableWrap.querySelector('.sub-view-bar');
        renderOTSummary(data);
        if (savedBar) tableWrap.insertBefore(savedBar, tableWrap.firstChild);
    } catch (e) { hideSpinner(); showError(e.message); }
}

function renderOTSummary(data) {
    const {quarters, summary} = data;
    // Signal card
    const card = document.createElement('div');
    card.className = 'portfolio-stats';
    if (summary && summary.trend) {
        [
            ['Trend', summary.trend],
            ['Shares Added', fmtShares(summary.total_shares_added)],
            ['Dollar Flow', fmtDollars(summary.total_dollar_flow)],
            ['Net New Holders', summary.net_new_holders != null ? (summary.net_new_holders > 0 ? '+' : '') + summary.net_new_holders : '\u2014'],
        ].forEach(([l, v]) => {
            const s = document.createElement('span');
            s.className = 'ps-item';
            s.innerHTML = `<span class="ps-label">${l}:</span><span class="ps-value">${v}</span>`;
            card.appendChild(s);
        });
    }
    // Keep sub-view bar that was already added
    tableWrap.appendChild(card);

    // Table
    const cols = [
        {key: 'quarter', label: 'Quarter', type: 'text'},
        {key: 'total_inst_shares', label: 'Inst Shares', type: 'shares'},
        {key: 'total_inst_value', label: 'Inst Value', type: 'dollar'},
        {key: 'pct_float', label: '% Float', type: 'pct'},
        {key: 'active_pct', label: 'Active %', type: 'pct'},
        {key: 'passive_pct', label: 'Passive %', type: 'pct'},
        {key: 'holder_count', label: 'Holders', type: 'num'},
        {key: 'net_shares_change', label: 'QoQ Change', type: 'shares'},
        {key: 'signal', label: 'Signal', type: 'text'},
    ];
    currentData = quarters;
    renderHierarchicalTable(quarters, cols, 0, false, false, false);
}

async function loadOTCohort() {
    // Loads inline below summary — no spinner/clear needed
    try {
        const res = await fetch(`/api/cohort_analysis?ticker=${currentTicker}`);
        if (!res.ok) return; // silently skip if cohort fails
        const data = await res.json();
        tableWrap.appendChild(sectionHeader('Cohort Analysis (Q1 → Q4)'));
        renderCohort(data);
    } catch (e) { /* cohort is optional enhancement */ }
}

function renderCohort(data) {
    const {summary, detail} = data;
    // Summary cards
    const cards = document.createElement('div');
    cards.className = 'portfolio-stats';
    [
        ['Retention Rate', summary.retention_rate != null ? summary.retention_rate + '%' : '\u2014'],
        ['New Entries', `${summary.new_entries_count} holders, +${fmtShares(summary.new_entries_shares)}`],
        ['Exits', `${summary.exits_count} holders, -${fmtShares(summary.exits_shares)}`],
        ['Net Adds', `${summary.net_adds_count} increased, +${fmtDollars(summary.net_adds_value)}`],
        ['Net Trims', `${summary.net_trims_count} decreased, ${fmtDollars(summary.net_trims_value)}`],
    ].forEach(([l, v]) => {
        const s = document.createElement('span');
        s.className = 'ps-item';
        s.innerHTML = `<span class="ps-label">${l}:</span><span class="ps-value">${v}</span>`;
        cards.appendChild(s);
    });
    tableWrap.appendChild(cards);

    // Detail table
    const cols = [
        {key: 'category', label: 'Category', type: 'text'},
        {key: 'holders', label: 'Holders', type: 'num'},
        {key: 'shares', label: 'Shares', type: 'shares'},
        {key: 'value', label: 'Value', type: 'dollar'},
        {key: 'avg_position', label: 'Avg Position', type: 'dollar'},
    ];
    currentData = detail;
    renderHierarchicalTable(detail, cols, 0, false, false, false);
}

// ---------------------------------------------------------------------------
// Flow Analysis tab — period selector, 4 sections, charts
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Activist / Beneficial Ownership tab
// ---------------------------------------------------------------------------
async function loadActivistTab() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    const params = new URLSearchParams({ticker: currentTicker});
    try {
        const res = await fetch(`/api/query6?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        hideSpinner();

        const wrap = tableWrap;

        // Section 1: 13D Activist Filers
        if (data.activist_13d && data.activist_13d.length > 0) {
            wrap.appendChild(sectionHeader('13D Activist Filers (≥5% with intent)'));
            const t1 = buildSimpleTable(data.activist_13d, [
                {key: 'filer_name', label: 'Filer', type: 'text'},
                {key: 'pct_owned', label: '% Owned', type: 'pct'},
                {key: 'shares_owned', label: 'Shares', type: 'shares'},
                {key: 'filing_date', label: 'Filed', type: 'text'},
                {key: 'filing_type', label: 'Form', type: 'text'},
                {key: 'days_since_filing', label: 'Days Ago', type: 'num'},
                {key: 'is_current', label: 'Current', type: 'text'},
            ]);
            wrap.appendChild(t1);
        }

        // Section 2: 13G Passive ≥5%
        if (data.passive_5pct && data.passive_5pct.length > 0) {
            wrap.appendChild(sectionHeader('13G Passive Holders (≥5%)'));
            const t2 = buildSimpleTable(data.passive_5pct, [
                {key: 'filer_name', label: 'Filer', type: 'text'},
                {key: 'pct_owned', label: '% Owned', type: 'pct'},
                {key: 'shares_owned', label: 'Shares', type: 'shares'},
                {key: 'filing_date', label: 'Filed', type: 'text'},
                {key: 'filing_type', label: 'Form', type: 'text'},
                {key: 'days_since_filing', label: 'Days Ago', type: 'num'},
            ]);
            wrap.appendChild(t2);
        }

        // Section 3: Filing History
        if (data.history && data.history.length > 0) {
            wrap.appendChild(sectionHeader('Filing History'));
            const t3 = buildSimpleTable(data.history, [
                {key: 'filer_name', label: 'Filer', type: 'text'},
                {key: 'filing_type', label: 'Form', type: 'text'},
                {key: 'filing_date', label: 'Filed', type: 'text'},
                {key: 'pct_owned', label: '% Owned', type: 'pct'},
                {key: 'shares_owned', label: 'Shares', type: 'shares'},
                {key: 'intent', label: 'Intent', type: 'text'},
                {key: 'purpose_text', label: 'Purpose', type: 'text'},
            ]);
            wrap.appendChild(t3);
        }

        // Section 4: 13F Activist Holdings (legacy)
        if (data.activist_13f && data.activist_13f.length > 0) {
            wrap.appendChild(sectionHeader('13F Activist Holdings'));
            const t4 = buildSimpleTable(data.activist_13f, [
                {key: 'filer_name', label: 'Manager', type: 'text'},
                {key: 'quarter', label: 'Quarter', type: 'text'},
                {key: 'shares_owned', label: 'Shares', type: 'shares'},
                {key: 'market_value_usd', label: 'Value (USD)', type: 'dollar'},
                {key: 'market_value_live', label: 'Value (Live)', type: 'dollar'},
                {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
                {key: 'pct_of_float', label: '% Float', type: 'pct'},
            ]);
            wrap.appendChild(t4);
        }

        // Empty state
        const allEmpty = (!data.activist_13d || !data.activist_13d.length) &&
                         (!data.passive_5pct || !data.passive_5pct.length) &&
                         (!data.history || !data.history.length) &&
                         (!data.activist_13f || !data.activist_13f.length);
        if (allEmpty) {
            wrap.innerHTML = '<div class="empty-state"><p>No 13D/G or activist data found for this ticker.</p></div>';
        }
    } catch (e) {
        hideSpinner(); showError(e.message);
    }
}

function sectionHeader(text) {
    const h = document.createElement('h3');
    h.style.cssText = 'margin:24px 0 8px 0;color:#002147;font-size:14px;border-bottom:1px solid #ddd;padding-bottom:4px;';
    h.textContent = text;
    return h;
}

function _formatCellValue(val, type) {
    if (val == null || val === '') return '—';
    if (type === 'dollar') return fmtDollars(val);
    if (type === 'shares') return fmtShares(val);
    if (type === 'pct') return fmtPct(val);
    if (type === 'num') return fmtNum(val);
    const s = String(val);
    return s.length > 120 ? s.slice(0, 120) + '…' : s;
}

function _isNumericCol(type) {
    return type === 'num' || type === 'dollar' || type === 'pct' || type === 'shares';
}

// R13: Heatmap overlay on Value column
function _applyHeatmapOverlay(enabled) {
    const table = tableWrap.querySelector('.data-table');
    if (!table) return;
    // Find Value column index
    const headers = table.querySelectorAll('thead th');
    let valIdx = -1;
    headers.forEach((th, i) => {
        if (th.textContent.trim().includes('Value')) valIdx = i;
    });
    if (valIdx < 0) return;

    // Get max value for scaling
    let maxVal = 0;
    if (enabled) {
        table.querySelectorAll('tbody tr').forEach(tr => {
            const cells = tr.querySelectorAll('td');
            if (cells[valIdx]) {
                const text = cells[valIdx].textContent.replace(/[$,BMKTk]/g, '');
                const num = parseFloat(text);
                if (!isNaN(num)) maxVal = Math.max(maxVal, num);
            }
        });
    }

    // Find Type column index to check for 'active'
    let typeIdx = -1;
    headers.forEach((th, i) => {
        if (th.textContent.trim() === 'Type') typeIdx = i;
    });

    table.querySelectorAll('tbody tr').forEach(tr => {
        const cells = tr.querySelectorAll('td');
        if (!cells[valIdx]) return;
        if (!enabled) {
            cells[valIdx].style.background = '';
            cells[valIdx].style.color = '';
            return;
        }
        // Only color active managers
        const typeText = (typeIdx >= 0 && cells[typeIdx]) ? cells[typeIdx].textContent.trim().toLowerCase() : '';
        if (typeText !== 'active' && typeText !== 'hedge_fund' && typeText !== 'activist') {
            cells[valIdx].style.background = '';
            cells[valIdx].style.color = '';
            return;
        }
        const text = cells[valIdx].textContent.replace(/[$,BMKTk]/g, '');
        const num = parseFloat(text);
        if (!isNaN(num) && maxVal > 0) {
            const intensity = Math.min(num / maxVal, 1);
            const r = Math.round(255 - intensity * 253);
            const g = Math.round(255 - intensity * 222);
            const b = Math.round(255 - intensity * 184);
            cells[valIdx].style.background = `rgb(${r},${g},${b})`;
            cells[valIdx].style.color = intensity > 0.5 ? '#fff' : '#333';
        }
    });
}

// R9: Toggle Source column visibility
function _applySourceColumnVisibility() {
    const hide = localStorage.getItem('hideSourceCol') === 'true';
    const table = tableWrap.querySelector('.data-table');
    if (!table) return;
    // Find Source column index (look for "Source" header text)
    const headers = table.querySelectorAll('thead th');
    let sourceIdx = -1;
    headers.forEach((th, i) => { if (th.textContent.trim() === 'Source') sourceIdx = i; });
    if (sourceIdx < 0) return;
    const display = hide ? 'none' : '';
    headers[sourceIdx].style.display = display;
    table.querySelectorAll('tbody tr').forEach(tr => {
        const cells = tr.querySelectorAll('td');
        if (cells[sourceIdx]) cells[sourceIdx].style.display = display;
    });
}

// Tier separator rows: faint line at 10/15/20
const TIER_BREAKS = [10, 15, 20];
// Subtotal rows at 10 and 25
const SUBTOTAL_AT = [10, 25];

function _buildSubtotalRow(data, cols, fromIdx, toIdx, label) {
    const tr = document.createElement('tr');
    tr.className = 'subtotal-row';
    // # column (blank)
    const tdNum = document.createElement('td');
    tdNum.className = 'col-rownum';
    tdNum.style.borderTop = '2px solid #999';
    tr.appendChild(tdNum);
    // Data columns — first text col gets the label
    let labelPlaced = false;
    cols.forEach(c => {
        const td = document.createElement('td');
        td.style.cssText = 'font-weight:700;border-top:2px solid #999;';
        td.style.textAlign = _isNumericCol(c.type) ? 'right' : 'left';
        if (!labelPlaced && !_isNumericCol(c.type)) {
            td.textContent = label;
            labelPlaced = true;
        } else if (_isNumericCol(c.type) && c.type !== 'pct') {
            let sum = 0;
            for (let i = fromIdx; i < Math.min(toIdx, data.length); i++) {
                const v = data[i][c.key];
                if (v != null && typeof v === 'number') sum += v;
            }
            td.textContent = sum !== 0 ? _formatCellValue(sum, c.type) : '—';
        } else {
            td.textContent = '';
        }
        tr.appendChild(td);
    });
    return tr;
}

function buildSimpleTable(data, cols) {
    const table = document.createElement('table');
    table.className = 'data-table';
    // Header with # column
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    const thNum = document.createElement('th');
    thNum.textContent = '#';
    thNum.className = 'col-rownum';
    hr.appendChild(thNum);
    cols.forEach(c => {
        const th = document.createElement('th');
        th.textContent = c.label;
        th.style.textAlign = _isNumericCol(c.type) ? 'right' : 'left';
        hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    // Body with row numbers, tier breaks, subtotals
    const tbody = document.createElement('tbody');
    data.forEach((row, idx) => {
        const rowNum = idx + 1;
        const tr = document.createElement('tr');
        // Tier separator: faint bottom border
        if (TIER_BREAKS.includes(rowNum)) {
            tr.style.borderBottom = '1px solid #ccc';
        }
        // Row number
        const tdNum = document.createElement('td');
        tdNum.textContent = rowNum;
        tdNum.className = 'col-rownum';
        tr.appendChild(tdNum);
        cols.forEach(c => {
            const td = document.createElement('td');
            td.style.textAlign = _isNumericCol(c.type) ? 'right' : 'left';
            td.textContent = _formatCellValue(row[c.key], c.type);
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
        // Subtotal rows
        if (SUBTOTAL_AT.includes(rowNum) && rowNum <= data.length) {
            tbody.appendChild(_buildSubtotalRow(data, cols, 0, rowNum, `Top ${rowNum}`));
        }
    });
    table.appendChild(tbody);
    return table;
}

let _flowPeriod = '4Q';

async function loadFlowAnalysis() {
    clearError(); tableWrap.innerHTML = '';

    // Period selector — "Compare from: [Q1 2025] [Q2 2025] [Q3 2025] → to Q4 2025"
    const pbar = document.createElement('div');
    pbar.className = 'period-selector';
    const label = document.createElement('span');
    label.textContent = 'Compare from:';
    pbar.appendChild(label);
    [['4Q', 'Q1 2025'], ['2Q', 'Q2 2025'], ['1Q', 'Q3 2025']].forEach(([p, lbl]) => {
        const btn = document.createElement('button');
        btn.className = 'period-btn' + (p === _flowPeriod ? ' active' : '');
        btn.textContent = lbl;
        btn.addEventListener('click', () => { _flowPeriod = p; loadFlowAnalysis(); });
        pbar.appendChild(btn);
    });
    const arrow = document.createElement('span');
    arrow.textContent = '\u2192 to Q4 2025 (latest)';
    arrow.style.marginLeft = '6px';
    pbar.appendChild(arrow);
    tableWrap.appendChild(pbar);

    showSpinner();
    // Get peers from cross-ownership if available
    const peers = getCOTickers().filter(t => t !== currentTicker).join(',');
    const url = `/api/flow_analysis?ticker=${currentTicker}&period=${_flowPeriod}&peers=${peers}`;
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        const savedBar = tableWrap.querySelector('.period-selector');
        renderFlowAnalysis(data);
        if (savedBar) tableWrap.insertBefore(savedBar, tableWrap.firstChild);
    } catch (e) { hideSpinner(); showError(e.message); }
}

function _signalBadge(signal) {
    if (!signal) return '\u2014';
    const map = {
        NEW: 'badge-new', EXIT: 'badge-exit', ACCEL: 'badge-accel',
        STEADY: 'badge-steady', FADING: 'badge-fading',
        REVERSING: 'badge-reversing', MINIMAL: 'badge-minimal',
    };
    const cls = map[signal] || 'badge-steady';
    return '<span class="' + cls + '">' + signal + '</span>';
}

function _flowTable(rows, cols, rowClass) {
    const table = document.createElement('table');
    table.className = 'data-table';
    table.style.tableLayout = 'auto';
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    const thNum = document.createElement('th');
    thNum.textContent = '#';
    thNum.className = 'col-rownum';
    hr.appendChild(thNum);
    cols.forEach(c => {
        const th = document.createElement('th');
        th.textContent = c.label;
        th.style.textAlign = (c.type === 'text') ? 'left' : 'right';
        hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    rows.forEach((row, idx) => {
        const rowNum = idx + 1;
        const tr = document.createElement('tr');
        if (rowClass) tr.classList.add(rowClass);
        if (TIER_BREAKS.includes(rowNum)) tr.style.borderBottom = '1px solid #ccc';
        // Row number
        const tdNum = document.createElement('td');
        tdNum.textContent = rowNum;
        tdNum.className = 'col-rownum';
        tr.appendChild(tdNum);
        cols.forEach(c => {
            const td = document.createElement('td');
            td.style.textAlign = (c.type === 'text') ? 'left' : 'right';
            const val = row[c.key];
            if (c.key === 'momentum_signal') {
                td.innerHTML = _signalBadge(val);
            } else if (c.key === 'pct_change') {
                if (val == null) {
                    td.innerHTML = row.is_new_entry ? _signalBadge('NEW') : (row.is_exit ? _signalBadge('EXIT') : '\u2014');
                } else {
                    const pct = (val * 100).toFixed(1);
                    td.innerHTML = val > 0
                        ? '<span class="positive">+' + pct + '%</span>'
                        : '<span class="negative">(' + Math.abs(pct) + '%)</span>';
                }
            } else {
                td.innerHTML = formatCell(val, fmtType(c));
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
}

function renderFlowAnalysis(data) {
    currentData = data.buyers || [];

    // Footnote
    const ip = data.implied_prices || {};
    const qf = data.quarter_from || '';
    const ipVal = ip[qf];
    if (ipVal) {
        const fn = document.createElement('div');
        fn.className = 'flow-footnote';
        fn.textContent = 'Price-adjusted flows use implied ' + qf + ' price of $' + ipVal.toFixed(2) + ' derived from 13F reported market values as of quarter-end';
        tableWrap.appendChild(fn);
    }

    // Charts section (flow intensity + churn) — using Chart.js
    const chartData = (data.charts && data.charts.flow_intensity) || [];
    if (chartData.length > 0 && typeof Chart !== 'undefined') {
        const row = document.createElement('div');
        row.className = 'charts-row';

        // Flow intensity chart
        const fiCard = document.createElement('div');
        fiCard.className = 'chart-card';
        fiCard.innerHTML = '<h3>Flow Intensity \u2014 Net Buying as % of Market Cap</h3>';
        const fiCanvas = document.createElement('canvas');
        fiCanvas.style.height = '250px';
        fiCanvas.style.maxHeight = '250px';
        fiCard.appendChild(fiCanvas);
        row.appendChild(fiCard);

        // Churn chart
        const chCard = document.createElement('div');
        chCard.className = 'chart-card';
        chCard.innerHTML = '<h3 title="Measures dollar value of non-passive positions that entered or exited as % of average non-passive institutional value">Value-Weighted Holder Churn \u2014 Non-Passive Managers</h3>';
        const chCanvas = document.createElement('canvas');
        chCanvas.style.height = '250px';
        chCanvas.style.maxHeight = '250px';
        chCard.appendChild(chCanvas);
        row.appendChild(chCard);

        tableWrap.appendChild(row);

        // Render charts after DOM insertion — setTimeout lets the browser lay out the canvas
        setTimeout(() => {
        const labels = chartData.map(d => d.ticker);

        // Destroy old charts
        if (window._fiChart) { window._fiChart.destroy(); window._fiChart = null; }
        if (window._chChart) { window._chChart.destroy(); window._chChart = null; }

        // Flow intensity bar chart
        window._fiChart = new Chart(fiCanvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Total',
                        data: chartData.map(d => d.flow_intensity_total ? (d.flow_intensity_total * 100) : 0),
                        backgroundColor: chartData.map(d =>
                            (d.flow_intensity_total || 0) >= 0 ? '#27AE60' : '#C0392B'
                        ),
                    },
                    {
                        label: 'Active Only',
                        data: chartData.map(d => d.flow_intensity_active ? (d.flow_intensity_active * 100) : 0),
                        backgroundColor: chartData.map(d =>
                            (d.flow_intensity_active || 0) >= 0 ? '#52BE80' : '#E74C3C'
                        ),
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: {
                        title: { display: true, text: '% of Market Cap' },
                        ticks: { callback: v => v.toFixed(1) + '%' },
                    },
                },
            },
        });

        // Churn bar chart — non-passive and active only
        window._chChart = new Chart(chCanvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Non-Passive',
                        data: chartData.map(d => d.churn_nonpassive ? (d.churn_nonpassive * 100) : 0),
                        backgroundColor: chartData.map(d => {
                            const v = d.churn_nonpassive || 0;
                            return v < 0.10 ? '#27AE60' : (v < 0.20 ? '#F39C12' : '#C0392B');
                        }),
                    },
                    {
                        label: 'Active Only',
                        data: chartData.map(d => d.churn_active ? (d.churn_active * 100) : 0),
                        backgroundColor: chartData.map(d => {
                            const v = d.churn_active || 0;
                            return v < 0.10 ? '#52BE80' : (v < 0.20 ? '#F5B041' : '#E74C3C');
                        }),
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: {
                        title: { display: true, text: 'Churn Rate %' },
                        ticks: { callback: v => v.toFixed(0) + '%' },
                    },
                },
            },
        });
        }, 100);  // end setTimeout — let DOM render before chart init

    } else if (chartData.length > 0) {
        // Fallback if Chart.js not loaded — show as table
        const row = document.createElement('div');
        row.className = 'charts-row';
        const card = document.createElement('div');
        card.className = 'chart-card';
        card.innerHTML = '<h3>Flow Intensity &amp; Churn</h3>';
        const t = document.createElement('table');
        t.className = 'data-table';
        t.style.tableLayout = 'auto';
        t.innerHTML = '<thead><tr><th>Ticker</th><th style="text-align:right">Flow Intensity</th><th style="text-align:right">Non-Passive Churn</th></tr></thead>';
        const tb = document.createElement('tbody');
        chartData.forEach(d => {
            const tr = document.createElement('tr');
            tr.innerHTML = '<td>' + d.ticker + '</td>'
                + '<td style="text-align:right">' + fmtPct(d.flow_intensity_total ? d.flow_intensity_total * 100 : null) + '</td>'
                + '<td style="text-align:right">' + fmtPct(d.churn_nonpassive ? d.churn_nonpassive * 100 : null) + '</td>';
            tb.appendChild(tr);
        });
        t.appendChild(tb);
        card.appendChild(t);
        row.appendChild(card);
        tableWrap.appendChild(row);
    }

    // Multi-period flow trend table
    const flowTrend = data.flow_trend || [];
    if (flowTrend.length > 0) {
        tableWrap.appendChild(sectionHeader('Flow Trend Across All Periods'));
        tableWrap.appendChild(buildSimpleTable(flowTrend, [
            {key: 'quarter_from', label: 'From', type: 'text'},
            {key: 'quarter_to', label: 'To', type: 'text'},
            {key: 'flow_intensity_total', label: 'Flow Intensity (Total)', type: 'pct'},
            {key: 'flow_intensity_active', label: 'Active Only', type: 'pct'},
            {key: 'flow_intensity_passive', label: 'Passive Only', type: 'pct'},
            {key: 'churn_nonpassive', label: 'Churn (Non-Passive)', type: 'pct'},
            {key: 'churn_active', label: 'Churn (Active)', type: 'pct'},
        ]));
    }

    // Buyers
    const buyerCols = [
        {key: 'inst_parent_name', label: 'Institution', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'from_shares', label: 'From Shares', type: 'shares'},
        {key: 'to_shares', label: 'To Shares', type: 'shares'},
        {key: 'net_shares', label: 'Net Shares', type: 'shares'},
        {key: 'pct_change', label: '% Change', type: 'pct'},
        {key: 'price_adj_flow', label: 'Price-Adj Flow', type: 'dollar'},
        {key: 'momentum_signal', label: 'Signal', type: 'text'},
    ];
    if (data.buyers && data.buyers.length) {
        const h = document.createElement('div');
        h.className = 'flow-section-header';
        h.innerHTML = '\u25B2 Buyers \u2014 Top 25 by Price-Adjusted Flow';
        tableWrap.appendChild(h);
        tableWrap.appendChild(_flowTable(data.buyers, buyerCols, 'row-buyer'));
    }

    // Sellers
    if (data.sellers && data.sellers.length) {
        const h = document.createElement('div');
        h.className = 'flow-section-header';
        h.innerHTML = '\u25BC Sellers \u2014 Top 25 by Price-Adjusted Flow';
        tableWrap.appendChild(h);
        tableWrap.appendChild(_flowTable(data.sellers, buyerCols, 'row-seller'));
    }

    // New Entries
    const neCols = [
        {key: 'inst_parent_name', label: 'Institution', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'to_shares', label: 'Shares', type: 'shares'},
        {key: 'to_value', label: 'Value', type: 'dollar'},
        {key: 'momentum_signal', label: 'Signal', type: 'text'},
    ];
    if (data.new_entries && data.new_entries.length) {
        const h = document.createElement('div');
        h.className = 'flow-section-header';
        h.innerHTML = '\u2605 New Entries \u2014 Initiated Positions';
        tableWrap.appendChild(h);
        tableWrap.appendChild(_flowTable(data.new_entries, neCols, 'row-new-entry'));
    }

    // Exits
    const exCols = [
        {key: 'inst_parent_name', label: 'Institution', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'from_shares', label: 'Shares Sold', type: 'shares'},
        {key: 'from_value', label: 'Value Exited', type: 'dollar'},
        {key: 'price_adj_flow', label: 'Price-Adj Flow', type: 'dollar'},
        {key: 'momentum_signal', label: 'Signal', type: 'text'},
    ];
    if (data.exits && data.exits.length) {
        const h = document.createElement('div');
        h.className = 'flow-section-header';
        h.innerHTML = '\u2715 Exits \u2014 Closed Positions';
        tableWrap.appendChild(h);
        tableWrap.appendChild(_flowTable(data.exits, exCols, 'row-seller'));
    }
}

// ---------------------------------------------------------------------------
// New/Exits tab (two sub-views reusing existing queries 10 and 11)
// ---------------------------------------------------------------------------
let _neSubView = 'new';

async function loadNewExits() {
    clearError(); tableWrap.innerHTML = '';
    currentQuery = 10;
    showSpinner();
    try {
        const res = await fetch(`/api/query10?ticker=${currentTicker}`);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        const wrap = tableWrap;
        // New entries section
        if (data.new_entries && data.new_entries.length) {
            wrap.appendChild(sectionHeader('New Positions (Quarter-over-Quarter)'));
            wrap.appendChild(buildSimpleTable(data.new_entries, [
                {key: 'manager_name', label: 'Institution', type: 'text'},
                {key: 'manager_type', label: 'Type', type: 'text'},
                {key: 'shares', label: 'Shares', type: 'shares'},
                {key: 'market_value_live', label: 'Value (Live)', type: 'dollar'},
                {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
                {key: 'pct_of_float', label: '% Float', type: 'pct'},
            ]));
        }
        // Exits section
        if (data.exits && data.exits.length) {
            wrap.appendChild(sectionHeader('Full Exits (Quarter-over-Quarter)'));
            wrap.appendChild(buildSimpleTable(data.exits, [
                {key: 'manager_name', label: 'Institution', type: 'text'},
                {key: 'manager_type', label: 'Type', type: 'text'},
                {key: 'q3_shares', label: 'Prior Shares', type: 'shares'},
                {key: 'q3_value', label: 'Prior Value', type: 'dollar'},
                {key: 'q3_pct', label: '% Portfolio', type: 'pct'},
            ]));
        }
        if ((!data.new_entries || !data.new_entries.length) && (!data.exits || !data.exits.length)) {
            wrap.innerHTML = '<div class="no-data">No position changes found.</div>';
        }
    } catch (e) { hideSpinner(); showError(e.message); }
}

// ---------------------------------------------------------------------------
// Query 7 — Fund Portfolio (manager selector + custom rendering)
// ---------------------------------------------------------------------------

// Store the manager list so we can look up by index — avoids JSON in HTML attributes
let _managerList = [];

async function loadManagerDropdown() {
    if (!currentTicker) return;
    _managerList = [];
    managerDropdown.innerHTML = '<option value="">Loading...</option>';
    try {
        const res = await fetch(`/api/fund_portfolio_managers?ticker=${currentTicker}`);
        const managers = await res.json();
        if (!managers.length || managers.error) {
            managerDropdown.innerHTML = '<option value="">No non-passive managers found</option>';
            return;
        }
        _managerList = managers;
        managerDropdown.innerHTML = managers.map((m, i) => {
            const val = fmtDollars(m.position_value);
            const fundName = m.fund_name || '';
            const label = `${fundName} \u2014 ${val} | ${m.manager_type || 'unknown'}`;
            return `<option value="${i}">${label}</option>`;
        }).join('');
        // Auto-load the first fund
        loadPortfolioFromIndex(0);
    } catch (e) {
        managerDropdown.innerHTML = '<option value="">Error loading managers</option>';
    }
}

function loadPortfolioFromIndex(idx) {
    const m = _managerList[idx];
    if (!m) return;
    loadQuery(7, {cik: m.cik, fund_name: m.fund_name});
}

loadPortfolioBtn.addEventListener('click', () => {
    const idx = parseInt(managerDropdown.value);
    if (!isNaN(idx)) loadPortfolioFromIndex(idx);
});

managerDropdown.addEventListener('change', () => {
    const idx = parseInt(managerDropdown.value);
    if (!isNaN(idx)) loadPortfolioFromIndex(idx);
});

function renderQuery7(data) {
    const stats = data.stats || {};
    const positions = data.positions || [];
    const cols = QUERY_COLUMNS[7];

    tableWrap.innerHTML = '';

    // Stats sub-header
    if (stats.manager_name) {
        const sh = document.createElement('div');
        sh.className = 'portfolio-stats';
        const items = [
            ['Manager', stats.manager_name],
            ['Type', stats.manager_type || 'unknown'],
            ['Portfolio Value', fmtDollars(stats.total_value)],
            ['Positions', stats.num_positions != null ? stats.num_positions.toLocaleString() : '\u2014'],
            ['Top 10 Concentration', stats.top10_concentration_pct != null ? stats.top10_concentration_pct.toFixed(1) + '%' : '\u2014'],
        ];
        items.forEach(([label, value]) => {
            const item = document.createElement('span');
            item.className = 'ps-item';
            item.innerHTML = `<span class="ps-label">${label}:</span><span class="ps-value">${value}</span>`;
            sh.appendChild(item);
        });
        tableWrap.appendChild(sh);
    }

    // Render table using shared function, then highlight current ticker row
    currentData = positions;
    renderHierarchicalTable(positions, cols, 7, false, false);

    // Move the table into tableWrap (renderHierarchicalTable replaces innerHTML)
    // Re-add stats header before table
    const table = tableWrap.querySelector('.data-table');
    const legend = tableWrap.querySelector('.color-legend');
    tableWrap.innerHTML = '';
    if (stats.manager_name) {
        const sh = document.createElement('div');
        sh.className = 'portfolio-stats';
        const items = [
            ['Manager', stats.manager_name],
            ['Type', stats.manager_type || 'unknown'],
            ['Portfolio Value', fmtDollars(stats.total_value)],
            ['Positions', stats.num_positions != null ? stats.num_positions.toLocaleString() : '\u2014'],
            ['Top 10 Concentration', stats.top10_concentration_pct != null ? stats.top10_concentration_pct.toFixed(1) + '%' : '\u2014'],
        ];
        items.forEach(([label, value]) => {
            const item = document.createElement('span');
            item.className = 'ps-item';
            item.innerHTML = `<span class="ps-label">${label}:</span><span class="ps-value">${value}</span>`;
            sh.appendChild(item);
        });
        tableWrap.appendChild(sh);
    }
    if (legend) tableWrap.appendChild(legend);
    if (table) {
        tableWrap.appendChild(table);
        // Highlight current ticker row
        if (currentTicker) {
            table.querySelectorAll('tbody tr').forEach(tr => {
                const tickerCell = tr.querySelector('td:nth-child(2)');
                if (tickerCell && tickerCell.textContent.trim().toUpperCase() === currentTicker) {
                    tr.classList.add('highlight-ticker');
                }
            });
        }
    }
}

/**
 * Format a cell value. Accepts either a col.type ('dollar','shares','pct','num')
 * or a visual type from inferColMeta ('dollar','shares','pct','num','change','rank').
 */
function formatCell(val, type) {
    if (val == null) return '\u2014';
    switch (type) {
        case 'dollar':  return fmtDollars(val);
        case 'shares':  return fmtShares(val);
        case 'pct':     return fmtPct(val);
        case 'change':  return (typeof val === 'number') ? fmtShares(val) : String(val);
        case 'num':
        case 'rank':    return fmtNum(val);
        default:        return String(val);
    }
}

/** Resolve the best format type for a column — prefers visual over col.type. */
function fmtType(col) {
    const meta = inferColMeta(col);
    // Visual types that map directly to formatters
    if (['dollar','shares','pct','change','num','rank'].includes(meta.visual)) {
        return meta.visual;
    }
    // Fall back to the declared data type
    return col.type;
}

// ---------------------------------------------------------------------------
// Query 15 — Stats rendering
// ---------------------------------------------------------------------------
function renderStats(data) {
    if (!data || !data.length) { tableWrap.innerHTML = '<div class="error-msg">No stats.</div>'; return; }
    const s = data[0];
    let html = '<div class="stats-grid">';

    const mainStats = {
        'Total Holdings Rows': (s.total_holdings || 0).toLocaleString(),
        'Unique Filers (CIK)': (s.unique_filers || 0).toLocaleString(),
        'Unique Securities (CUSIP)': (s.unique_securities || 0).toLocaleString(),
        'Quarters Loaded': s.quarters_loaded || 0,
        'Manager Records': (s.manager_records || 0).toLocaleString(),
        'Securities Mapped': (s.securities_mapped || 0).toLocaleString(),
        'Market Data Tickers': (s.market_data_tickers || 0).toLocaleString(),
        'ADV Records': (s.adv_records || 0).toLocaleString(),
    };

    html += '<div>';
    html += '<h3 style="margin-bottom:12px;color:var(--oxford-blue)">Database Overview</h3>';
    for (const [k, v] of Object.entries(mainStats)) {
        html += `<div class="stat-item"><span class="stat-label">${k}</span><span class="stat-value">${v}</span></div>`;
    }
    html += '</div>';

    // Coverage
    if (s.coverage) {
        html += '<div>';
        html += '<h3 style="margin-bottom:12px;color:var(--oxford-blue)">Coverage (Q4 2025)</h3>';
        const cov = s.coverage;
        html += `<div class="stat-item"><span class="stat-label">Ticker Coverage</span><span class="stat-value">${cov.ticker_pct}%</span></div>`;
        html += `<div class="stat-item"><span class="stat-label">Manager Type</span><span class="stat-value">${cov.manager_type_pct}%</span></div>`;
        html += `<div class="stat-item"><span class="stat-label">Live Market Value</span><span class="stat-value">${cov.live_value_pct}%</span></div>`;
        html += `<div class="stat-item"><span class="stat-label">Float Percentage</span><span class="stat-value">${cov.float_pct_pct}%</span></div>`;
        html += '</div>';
    }

    // Quarter breakdown table
    if (s.quarters && s.quarters.length) {
        html += '<div style="grid-column: 1 / -1">';
        html += '<h3 style="margin-bottom:12px;color:var(--oxford-blue)">Holdings by Quarter</h3>';
        html += '<table class="data-table"><thead><tr>';
        html += '<th>Quarter</th><th>Rows</th><th>Filers</th><th>Securities</th><th>Total Value ($T)</th>';
        html += '</tr></thead><tbody>';
        s.quarters.forEach(q => {
            html += `<tr>
                <td class="text">${q.quarter}</td>
                <td class="num">${(q.rows||0).toLocaleString()}</td>
                <td class="num">${(q.filers||0).toLocaleString()}</td>
                <td class="num">${(q.securities||0).toLocaleString()}</td>
                <td class="num">${q.total_value_tn != null ? q.total_value_tn.toFixed(1) : '\u2014'}</td>
            </tr>`;
        });
        html += '</tbody></table></div>';
    }

    html += '</div>';
    tableWrap.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Query 8 — Cross-Ownership Matrix (two views)
// ---------------------------------------------------------------------------

let _coView = 'anchor';  // 'anchor' or 'top'
let _coAnchor = '';       // currently selected anchor ticker
const coAnchorBar = document.getElementById('co-anchor-bar');
const coAnchorSelect = document.getElementById('co-anchor-select');

function initCrossOwnership() {
    const input0 = document.getElementById('co-ticker-0');
    if (input0) input0.value = currentTicker;
    const input1 = coPanel.querySelector('.co-ticker-input[data-idx="1"]');
    if (input1 && !input1.value && currentTicker === 'AR') input1.value = 'AM';
    _coAnchor = currentTicker;
    updateAnchorDropdown();
    loadPeerGroups();
    loadCO();
}

async function loadPeerGroups() {
    const select = document.getElementById('co-peer-select');
    if (!select || select.options.length > 1) return;  // already loaded
    try {
        const res = await fetch('/api/peer_groups');
        if (!res.ok) return;
        const groups = await res.json();
        groups.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g.group_id;
            opt.textContent = `${g.group_name} (${g.tickers.length})`;
            opt.dataset.tickers = JSON.stringify(g.tickers.map(t => t.ticker));
            select.appendChild(opt);
        });
        select.addEventListener('change', () => {
            if (!select.value) return;
            const opt = select.options[select.selectedIndex];
            const tickers = JSON.parse(opt.dataset.tickers || '[]');
            applyPeerGroup(tickers);
        });
    } catch (e) { /* ignore */ }
}

function applyPeerGroup(tickers) {
    // Set first ticker as primary if current ticker is in the group
    const inputs = coPanel.querySelectorAll('.co-ticker-input[data-idx]');
    // Clear all
    inputs.forEach(inp => { inp.value = ''; });
    // Fill with peer group tickers (skip current ticker — it's already in slot 0)
    const others = tickers.filter(t => t !== currentTicker);
    others.forEach((t, i) => {
        if (i < inputs.length) inputs[i].value = t;
    });
    updateAnchorDropdown();
    loadCO();
}

function getCOTickers() {
    const tickers = [currentTicker];
    coPanel.querySelectorAll('.co-ticker-input[data-idx]').forEach(inp => {
        const val = inp.value.trim().toUpperCase();
        if (val && !tickers.includes(val)) tickers.push(val);
    });
    return tickers;
}

function updateAnchorDropdown() {
    const tickers = getCOTickers();
    coAnchorSelect.innerHTML = tickers.map(t =>
        `<option value="${t}"${t === _coAnchor ? ' selected' : ''}>${t}</option>`
    ).join('');
}

async function loadCO() {
    const tickers = getCOTickers();
    if (!tickers.length) return;
    showSpinner();
    clearError();
    tableWrap.innerHTML = '';
    const activeOnly = coActiveToggle.checked;
    let url;
    if (_coView === 'anchor') {
        const anchor = _coAnchor || tickers[0];
        url = `/api/cross_ownership?tickers=${tickers.join(',')}&anchor=${anchor}&active_only=${activeOnly}&limit=25`;
    } else {
        url = `/api/cross_ownership_top?tickers=${tickers.join(',')}&active_only=${activeOnly}&limit=25`;
    }
    try {
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        const data = await res.json();
        hideSpinner();
        renderCOMatrix(data);
    } catch (e) {
        hideSpinner();
        showError(e.message);
    }
}

function renderCOMatrix(data) {
    const {tickers, companies, investors} = data;
    if (!investors || !investors.length) {
        tableWrap.innerHTML = '<div class="error-msg">No cross-ownership data found.</div>';
        return;
    }

    currentData = investors;

    // Reorder tickers: anchor first for View 1, original order for View 2
    let orderedTickers = [...tickers];
    if (_coView === 'anchor' && _coAnchor && tickers.includes(_coAnchor)) {
        orderedTickers = [_coAnchor, ...tickers.filter(t => t !== _coAnchor)];
    }

    const investorW = 220;
    const typeW = 80;
    const totalW = 130;
    const pctW = 100;
    const fixedW = investorW + typeW + totalW + pctW;
    const tickerColW = Math.max(100, Math.min(130, Math.floor((1200 - fixedW) / orderedTickers.length)));
    const showRank = _coView === 'top';

    const wrap = document.createElement('div');
    wrap.className = 'matrix-wrap';
    const table = document.createElement('table');
    table.className = 'matrix-table';

    // Colgroup
    const cg = document.createElement('colgroup');
    if (showRank) cg.innerHTML += '<col style="width:40px">';
    cg.innerHTML += `<col style="width:${investorW}px"><col style="width:${typeW}px">`;
    orderedTickers.forEach(() => { cg.innerHTML += `<col style="width:${tickerColW}px">`; });
    cg.innerHTML += `<col style="width:${totalW}px"><col style="width:${pctW}px">`;
    table.appendChild(cg);

    // Header
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    if (showRank) {
        const thR = document.createElement('th');
        thR.textContent = '#';
        thR.style.textAlign = 'right';
        hr.appendChild(thR);
    }
    const thInv = document.createElement('th');
    thInv.textContent = 'Investor';
    thInv.style.textAlign = 'left';
    thInv.classList.add('sticky-col');
    thInv.style.left = showRank ? '40px' : '0px';
    hr.appendChild(thInv);
    const thType = document.createElement('th');
    thType.textContent = 'Type';
    thType.style.textAlign = 'center';
    thType.classList.add('sticky-col');
    thType.style.left = (showRank ? 40 : 0) + investorW + 'px';
    hr.appendChild(thType);
    orderedTickers.forEach((t, i) => {
        const th = document.createElement('th');
        th.textContent = t;
        th.style.textAlign = 'right';
        th.title = companies[t] || t;
        if (i === 0 && _coView === 'anchor') th.style.fontWeight = '700';
        hr.appendChild(th);
    });
    const thTotal = document.createElement('th');
    thTotal.textContent = 'Total Across';
    thTotal.style.textAlign = 'right';
    hr.appendChild(thTotal);
    const thPct = document.createElement('th');
    thPct.textContent = '% Portfolio';
    thPct.style.textAlign = 'right';
    hr.appendChild(thPct);
    thead.appendChild(hr);
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    const colTotals = {};
    orderedTickers.forEach(t => { colTotals[t] = 0; });
    let grandTotal = 0;

    investors.forEach((inv, idx) => {
        const tr = document.createElement('tr');
        const rtype = (inv.type || '').toLowerCase();
        if (rtype && rtype !== 'unknown') {
            tr.classList.add('type-' + rtype.replace(/[^a-z_]/g, ''));
        }

        if (showRank) {
            const tdR = document.createElement('td');
            tdR.style.textAlign = 'right';
            tdR.textContent = idx + 1;
            tr.appendChild(tdR);
        }

        const tdInv = document.createElement('td');
        tdInv.classList.add('sticky-col', 'col-text-overflow');
        tdInv.style.left = showRank ? '40px' : '0px';
        tdInv.textContent = inv.investor || '';
        tdInv.title = inv.investor || '';
        tr.appendChild(tdInv);

        const tdType = document.createElement('td');
        tdType.classList.add('sticky-col');
        tdType.style.left = (showRank ? 40 : 0) + investorW + 'px';
        tdType.style.textAlign = 'center';
        tdType.textContent = inv.type || '';
        tr.appendChild(tdType);

        orderedTickers.forEach(t => {
            const td = document.createElement('td');
            td.style.textAlign = 'right';
            const val = inv.holdings[t];
            if (val != null) {
                td.textContent = fmtDollars(val);
                td.classList.add('cell-held');
                colTotals[t] += val;
            } else {
                td.textContent = '\u2014';
                td.classList.add('cell-empty');
            }
            tr.appendChild(td);
        });

        const tdTotal = document.createElement('td');
        tdTotal.style.textAlign = 'right';
        tdTotal.classList.add('col-total');
        tdTotal.textContent = fmtDollars(inv.total_across);
        grandTotal += (inv.total_across || 0);
        tr.appendChild(tdTotal);

        const tdPct = document.createElement('td');
        tdPct.style.textAlign = 'right';
        tdPct.textContent = inv.pct_of_portfolio != null ? inv.pct_of_portfolio.toFixed(2) + '%' : '\u2014';
        tr.appendChild(tdPct);

        tbody.appendChild(tr);
    });

    // Totals row
    const totalsRow = document.createElement('tr');
    totalsRow.className = 'totals-row';
    if (showRank) totalsRow.appendChild(document.createElement('td'));
    const tdTotLabel = document.createElement('td');
    tdTotLabel.classList.add('sticky-col');
    tdTotLabel.style.left = showRank ? '40px' : '0px';
    tdTotLabel.textContent = 'Total (Top 25)';
    totalsRow.appendChild(tdTotLabel);
    const tdTotType = document.createElement('td');
    tdTotType.classList.add('sticky-col');
    tdTotType.style.left = (showRank ? 40 : 0) + investorW + 'px';
    totalsRow.appendChild(tdTotType);
    orderedTickers.forEach(t => {
        const td = document.createElement('td');
        td.style.textAlign = 'right';
        td.textContent = fmtDollars(colTotals[t]);
        totalsRow.appendChild(td);
    });
    const tdGrand = document.createElement('td');
    tdGrand.style.textAlign = 'right';
    tdGrand.textContent = fmtDollars(grandTotal);
    totalsRow.appendChild(tdGrand);
    totalsRow.appendChild(document.createElement('td'));
    tbody.appendChild(totalsRow);

    table.appendChild(tbody);
    wrap.appendChild(table);

    tableWrap.innerHTML = '';
    tableWrap.appendChild(buildLegend());
    tableWrap.appendChild(wrap);
}

// --- Event listeners ---

coAnalyzeBtn.addEventListener('click', () => {
    updateAnchorDropdown();
    loadCO();
});

// Active/All toggle
coActiveToggle.addEventListener('change', () => {
    coToggleLabel.textContent = coActiveToggle.checked ? 'Active Only' : 'All Institutions';
    loadCO();
});

// View toggle buttons
coPanel.querySelectorAll('.co-view-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        coPanel.querySelectorAll('.co-view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _coView = btn.dataset.view;
        coAnchorBar.classList.toggle('hidden', _coView !== 'anchor');
        loadCO();
    });
});

// Anchor company dropdown
coAnchorSelect.addEventListener('change', () => {
    _coAnchor = coAnchorSelect.value;
    loadCO();
});

// Cross-ownership autocomplete on each ticker input
coPanel.querySelectorAll('.co-ticker-input[data-idx]').forEach(input => {
    const item = input.closest('.co-ticker-item');
    let dropdown = item.querySelector('.co-dropdown');
    if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.className = 'co-dropdown';
        item.style.position = 'relative';
        item.appendChild(dropdown);
    }
    let selIdx = -1;

    input.addEventListener('input', () => {
        const val = input.value.trim();
        selIdx = -1;
        if (val.length < 2) { dropdown.classList.remove('visible'); dropdown.innerHTML = ''; return; }
        const matches = filterTickers(val);
        if (!matches.length) { dropdown.classList.remove('visible'); return; }
        dropdown.innerHTML = matches.map((t, i) =>
            `<div class="autocomplete-item" data-ticker="${t.ticker}">
                <span class="ticker">${t.ticker}</span>
                <span class="name">${t.name || ''}</span>
            </div>`
        ).join('');
        dropdown.classList.add('visible');
    });

    input.addEventListener('keydown', (e) => {
        const items = dropdown.querySelectorAll('.autocomplete-item');
        if (!items.length && e.key === 'Enter') { e.preventDefault(); updateAnchorDropdown(); loadCO(); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); selIdx = Math.min(selIdx + 1, items.length - 1); items.forEach((el,i) => el.classList.toggle('selected', i === selIdx)); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); selIdx = Math.max(selIdx - 1, 0); items.forEach((el,i) => el.classList.toggle('selected', i === selIdx)); }
        else if (e.key === 'Enter') {
            e.preventDefault();
            if (selIdx >= 0 && selIdx < items.length) input.value = items[selIdx].dataset.ticker;
            dropdown.classList.remove('visible');
            updateAnchorDropdown();
            loadCO();
        }
        else if (e.key === 'Escape') { dropdown.classList.remove('visible'); }
    });

    dropdown.addEventListener('click', (e) => {
        const acItem = e.target.closest('.autocomplete-item');
        if (acItem) { input.value = acItem.dataset.ticker; dropdown.classList.remove('visible'); updateAnchorDropdown(); loadCO(); }
    });

    input.addEventListener('blur', () => { setTimeout(() => dropdown.classList.remove('visible'), 150); });
});

// Clear buttons
coPanel.querySelectorAll('.co-clear').forEach(btn => {
    btn.addEventListener('click', () => {
        const idx = btn.dataset.idx;
        const input = coPanel.querySelector(`.co-ticker-input[data-idx="${idx}"]`);
        if (input) { input.value = ''; updateAnchorDropdown(); loadCO(); }
    });
});

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------
function sortTable(data, cols, colIdx, qnum) {
    const col = cols[colIdx];
    if (sortCol === colIdx) {
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        sortCol = colIdx;
        sortDir = 'asc';
    }

    data.sort((a, b) => {
        let va = a[col.key];
        let vb = b[col.key];
        if (va == null) va = -Infinity;
        if (vb == null) vb = -Infinity;
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return sortDir === 'asc' ? -1 : 1;
        if (va > vb) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    renderTable(data, qnum);

    // Mark sorted column
    const ths = tableWrap.querySelectorAll('th');
    ths.forEach((th, i) => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        if (i === colIdx) {
            th.classList.add(sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
        }
    });
}

// ---------------------------------------------------------------------------
// Copy to clipboard
// ---------------------------------------------------------------------------
copyBtn.addEventListener('click', () => {
    if (!currentData || !currentData.length) return;

    const cols = QUERY_COLUMNS[currentQuery];
    const keys = cols ? cols.map(c => c.key) : Object.keys(currentData[0]).filter(k => !k.startsWith('_'));
    const headers = cols ? cols.map(c => c.label) : keys;

    let tsv = headers.join('\t') + '\n';
    currentData.forEach(row => {
        const vals = keys.map(k => {
            const v = row[k];
            if (v == null) return '';
            return String(v);
        });
        tsv += vals.join('\t') + '\n';
    });

    navigator.clipboard.writeText(tsv).then(() => {
        copyBtn.textContent = 'Copied';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
    }).catch(() => {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = tsv;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        copyBtn.textContent = 'Copied';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
    });
});

// ---------------------------------------------------------------------------
// Excel export
// ---------------------------------------------------------------------------
exportBtn.addEventListener('click', () => {
    if (!currentTicker && currentQuery !== 13 && currentQuery !== 15) return;
    const params = new URLSearchParams();
    if (currentTicker) params.set('ticker', currentTicker);
    // Include extra params (cik, fund_name for Query 7 Fund Portfolio)
    for (const [k, v] of Object.entries(_lastExtraParams)) params.set(k, v);
    window.location.href = `/api/export/query${currentQuery}?${params}`;
});

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function showSpinner() { spinner.classList.remove('hidden'); }
function hideSpinner() { spinner.classList.add('hidden'); }
function showError(msg) { errorMsg.textContent = msg; errorMsg.classList.remove('hidden'); }
function clearError() { errorMsg.classList.add('hidden'); errorMsg.textContent = ''; }

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
loadTickers();
