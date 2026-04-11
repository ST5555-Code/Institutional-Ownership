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

// Rollup type — 'economic_control_v1' (Fund Sponsor/Voting) or 'decision_maker_v1'
let currentRollupType = 'economic_control_v1';

function setRollupType(type) {
    if (type !== 'economic_control_v1' && type !== 'decision_maker_v1') return;
    currentRollupType = type;
    // Reload current tab with new rollup type
    if (currentTicker) {
        const activeTab = document.querySelector('.tab-link.active');
        if (activeTab) activeTab.click();
    }
}

// Auto-append rollup_type to all /api/ fetch calls
const _origFetch = window.fetch;
window.fetch = function(url, opts) {
    if (typeof url === 'string' && url.startsWith('/api/') && !url.includes('rollup_type=')) {
        const sep = url.includes('?') ? '&' : '?';
        url = `${url}${sep}rollup_type=${currentRollupType}`;
    }
    return _origFetch(url, opts);
};

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
// Ownership mix stacked bar
// ---------------------------------------------------------------------------
const _typeColors = {
    active:             '#4caf50',
    passive:            '#2196f3',
    hedge_fund:         '#9c27b0',
    quantitative:       '#7c4dff',
    mixed:              '#ff9800',
    activist:           '#f44336',
    SWF:                '#00838f',
    strategic:          '#795548',
    private_equity:     '#546e7a',
    wealth_management:  '#8d6e63',
    endowment_foundation:'#a1887f',
    pension_insurance:  '#78909c',
    venture_capital:    '#607d8b',
    multi_strategy:     '#ab47bc',
    unknown:            '#bdbdbd',
};
const _typeLabels = {
    active: 'Active', passive: 'Passive', hedge_fund: 'Hedge Fund',
    quantitative: 'Quant', mixed: 'Mixed', activist: 'Activist',
    SWF: 'SWF', strategic: 'Strategic', private_equity: 'PE',
    wealth_management: 'Wealth Mgmt', endowment_foundation: 'Endow.',
    pension_insurance: 'Pension', venture_capital: 'VC',
    multi_strategy: 'Multi-Strat', unknown: 'Other',
};

function _buildTypeBar(breakdown, total) {
    const bar = document.getElementById('sum-type-bar');
    const legend = document.getElementById('sum-type-legend');
    bar.innerHTML = ''; legend.innerHTML = '';
    if (!breakdown.length || !total) return;

    // Group small slices (<2%) into Other
    const MIN_PCT = 2;
    let items = [];
    let otherVal = 0;
    breakdown.forEach(b => {
        const pct = b.value / total * 100;
        if (pct >= MIN_PCT) {
            items.push({type: b.type, value: b.value, pct});
        } else {
            otherVal += b.value;
        }
    });
    if (otherVal > 0) {
        items.push({type: 'unknown', value: otherVal, pct: otherVal / total * 100});
    }

    // Build bar segments
    items.forEach(item => {
        const seg = document.createElement('div');
        seg.className = 'type-bar-seg';
        seg.style.width = item.pct.toFixed(1) + '%';
        seg.style.background = _typeColors[item.type] || '#bdbdbd';
        const label = (_typeLabels[item.type] || item.type);
        // Show % on all segments; show $ only for active and passive
        let text = Math.round(item.pct) + '%';
        if (item.pct >= 5) {
            seg.innerHTML = `<span class="type-bar-label">${text}</span>`;
        }
        seg.title = `${label}: ${fmtDollars(item.value)} (${item.pct.toFixed(1)}%)`;
        bar.appendChild(seg);
    });

    // Legend below bar: label + $ for active/passive, label + % for others
    items.forEach(item => {
        const label = _typeLabels[item.type] || item.type;
        const el = document.createElement('span');
        el.className = 'type-bar-legend-item';
        const swatch = `<span class="type-bar-swatch" style="background:${_typeColors[item.type] || '#bdbdbd'}"></span>`;
        if (item.type === 'active' || item.type === 'passive') {
            el.innerHTML = `${swatch}${label} ${fmtDollars(item.value)}`;
        } else {
            el.innerHTML = `${swatch}${label} ${Math.round(item.pct)}%`;
        }
        legend.appendChild(el);
    });
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
        document.getElementById('sum-price').textContent = s.price != null ? '$' + s.price.toFixed(2) : '\u2014';
        document.getElementById('sum-price-date').textContent = s.price_date || '';
        document.getElementById('sum-mktcap').innerHTML = fmtDollars(s.market_cap);
        document.getElementById('sum-holdings').innerHTML = fmtDollars(s.total_value);
        document.getElementById('sum-float').innerHTML = fmtPct(s.total_pct_float);

        // Active / Passive with $ and %
        const activeVal = s.active_value || 0;
        const passiveVal = s.passive_value || 0;
        const totalVal = s.total_value || (activeVal + passiveVal) || 0;
        if (totalVal > 0) {
            const activePct = (activeVal / totalVal * 100).toFixed(0);
            const passivePct = (passiveVal / totalVal * 100).toFixed(0);
            document.getElementById('sum-active').innerHTML = fmtDollars(activeVal) + ' <span style="color:#888;font-size:11px;">(' + activePct + '%)</span>';
            document.getElementById('sum-passive').innerHTML = fmtDollars(passiveVal) + ' <span style="color:#888;font-size:11px;">(' + passivePct + '%)</span>';
        } else {
            document.getElementById('sum-active').textContent = '\u2014';
            document.getElementById('sum-passive').textContent = '\u2014';
        }

        // Row 2
        document.getElementById('sum-holders').textContent = s.num_holders != null ? s.num_holders.toLocaleString() : '\u2014';
        document.getElementById('sum-quarter').textContent = s.latest_quarter || '\u2014';
        const nportEl = document.getElementById('sum-nport');
        if (s.nport_funds != null && s.nport_funds > 0) {
            let txt = s.nport_funds.toLocaleString() + ' funds';
            if (s.nport_latest_date) {
                txt += '<br><span style="font-size:10px;color:#888;">as of ' + s.nport_latest_date + '</span>';
            }
            nportEl.innerHTML = txt;
        } else {
            nportEl.textContent = '\u2014';
        }

        // Stacked ownership mix bar
        _buildTypeBar(s.type_breakdown || [], totalVal);
    } catch (e) {
        document.getElementById('sum-company').textContent = ticker;
        ['sum-quarter','sum-holdings','sum-float','sum-holders','sum-active','sum-passive','sum-mktcap','sum-price','sum-nport']
            .forEach(id => document.getElementById(id).textContent = '\u2014');
        document.getElementById('sum-price-date').textContent = '';
        document.getElementById('sum-type-bar').innerHTML = '';
        document.getElementById('sum-type-legend').innerHTML = '';
    }

    // Load current tab
    switchTab(currentTab);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
// Tab ID → legacy query number mapping (for endpoints that use /api/queryN)
const TAB_QUERY_MAP = {
    'register': 1,
    'fund-portfolio': 7, 'cross-ownership': 8,
    'aum': 14,
};

function switchTab(tabId) {
    // Save current sort state
    if (currentTab) _sortState[currentTab] = {col: sortCol, dir: sortDir};
    currentTab = tabId;
    currentQuery = TAB_QUERY_MAP[tabId] || 0;
    _legendTypeFilter = null;  // reset legend filter on tab switch
    // Restore sort state for this tab (or reset)
    const saved = _sortState[tabId];
    sortCol = saved ? saved.col : null;
    sortDir = saved ? saved.dir : 'asc';
    // Hide all special panels
    managerSelector.classList.add('hidden');
    coPanel.classList.add('hidden');

    // Any tab other than 'two-co-overlap' must deactivate the tco panel and
    // restore results-area. The tco IIFE publishes its deactivator as a
    // window global; calling it unconditionally here (before the routing
    // switch) simplifies every leaf branch below — they no longer need to
    // know the tco panel exists.
    if (tabId !== 'two-co-overlap' && typeof window._tcoDeactivate === 'function') {
        window._tcoDeactivate();
    }

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
    } else if (tabId === 'activist') {
        loadActivistTab();
    } else if (tabId === 'short-analysis') {
        loadShortAnalysis();
    } else if (tabId === 'conviction') {
        loadConviction();
    } else if (tabId === 'crowding') {
        loadCrowding();
    } else if (tabId === 'peer-matrix') {
        loadHeatmap();
    } else if (tabId === 'sector-rotation') {
        loadSectorRotation();
    } else if (tabId === 'peer-rotation') {
        loadPeerRotation();
    } else if (tabId === 'two-co-overlap') {
        // Explicit results-area hide for defense-in-depth — tcoActivate()
        // does the same but keeping this in switchTab matches the pattern
        // used for fund-portfolio / cross-ownership show/hide. If the tco
        // IIFE fails to boot for any reason, results-area still disappears.
        const resultsArea = document.getElementById('results-area');
        const actionBar = document.querySelector('.action-bar');
        if (resultsArea) resultsArea.style.display = 'none';
        if (actionBar) actionBar.style.display = 'none';
        if (typeof window.loadTwoCoOverlap === 'function') window.loadTwoCoOverlap();
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
        } else if ((qnum === 1 || qnum === 16) && raw.rows) {
            // Register / Fund Register tabs return {rows, all_totals, type_totals}
            currentData = raw.rows;
            _registerAllTotals = raw.all_totals || null;
            _registerTypeTotals = raw.type_totals || {};
            renderTable(raw.rows, qnum);
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
        {key: 'institution', label: 'Institution',  type: 'text',   group: null},
        {key: 'value_live',  label: 'Value (Live)', type: 'dollar', group: '_ticker_'},
        {key: 'shares',      label: 'Shares',       type: 'shares', group: '_ticker_'},
        {key: 'pct_float',   label: '% Float',      type: 'pct',   group: '_ticker_'},
        {key: 'aum',         label: 'AUM ($M)',     type: 'num',    group: 'Fund'},
        {key: 'pct_aum',     label: '% of AUM',    type: 'pct',    group: 'Fund'},
        {key: 'nport_cov',   label: 'N-PORT Cov.',  type: 'nport_badge', group: 'Fund',
         tooltip: "% of this manager's total 13F AUM visible at fund series level via N-PORT. High = fund-level drill-down available."},
        {key: 'type',        label: 'Type',         type: 'text',   group: 'Fund'},
    ],
    16: [
        {key: 'institution', label: 'Fund Name',    type: 'text',   group: null},
        {key: 'family',      label: 'Family',       type: 'text',   group: null},
        {key: 'value_live',  label: 'Value (Live)', type: 'dollar', group: '_ticker_'},
        {key: 'shares',      label: 'Shares',       type: 'shares', group: '_ticker_'},
        {key: 'pct_float',   label: '% Float',      type: 'pct',   group: '_ticker_'},
        {key: 'aum',         label: 'AUM ($M)',     type: 'num',    group: 'Fund'},
        {key: 'pct_aum',     label: '% of NAV',    type: 'pct',    group: 'Fund'},
        {key: 'type',        label: 'Type',         type: 'text',   group: 'Fund'},
    ],
    2: [
        {key: 'fund_name',     label: 'Institution / Fund', type: 'text'},
        {key: 'q1_shares',     label: 'Q1 Shares',          type: 'shares'},
        {key: 'q4_shares',     label: 'Q4 Shares',          type: 'shares'},
        {key: 'change_shares', label: 'Change',             type: 'shares'},
        {key: 'change_pct',    label: 'Chg%',               type: 'pct'},
        {key: 'type',          label: 'Type',               type: 'text'},
    ],
    3: [
        {key: 'manager_name',      label: 'Active Holder',  type: 'text'},
        {key: 'position_value',    label: 'Position Value', type: 'dollar'},
        {key: 'pct_of_portfolio',  label: '% Portfolio',    type: 'pct'},
        {key: 'pct_of_float',     label: '% Float',         type: 'pct'},
        {key: 'mktcap_percentile', label: 'MktCap Pctile', type: 'pct'},
        {key: 'nport_cov',        label: 'N-PORT Cov.',     type: 'nport_badge',
         tooltip: "% of this manager's total 13F AUM visible at fund series level via N-PORT. High = fund-level drill-down available."},
        {key: 'manager_type',     label: 'Type',            type: 'text'},
        {key: 'direction',        label: 'Direction',       type: 'text'},
        {key: 'since',            label: 'Since',           type: 'text'},
        {key: 'held_label',       label: 'Held',            type: 'text'},
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
    else if (col.type === 'nport_badge')
        result = {w: '100px', align: 'center', visual: 'nport_badge'};

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
    const noPagination = (qnum === 1 || qnum === 16);
    const totalPages = noPagination ? 1 : Math.ceil(data.length / PAGE_SIZE);
    const start = noPagination ? 0 : _currentPage * PAGE_SIZE;
    const pageData = noPagination ? data : (data.length > PAGE_SIZE ? data.slice(start, start + PAGE_SIZE) : data);

    const cols = QUERY_COLUMNS[qnum];

    // R16: Search filter for Register / Fund Register tab
    if (qnum === 1 || qnum === 16) {
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

            // View toggle: Parent (query1) vs Fund (query16)
            const viewToggle = document.createElement('div');
            viewToggle.className = 'register-view-toggle';
            const btnParent = document.createElement('button');
            btnParent.textContent = 'By Parent';
            btnParent.className = 'btn btn-toggle' + (qnum === 1 ? ' active' : '');
            btnParent.onclick = () => {
                if (_currentQnum === 1) return;
                _legendTypeFilter = null;
                currentQuery = 1; _currentQnum = 1;
                loadQuery(1);
            };
            const btnFund = document.createElement('button');
            btnFund.textContent = 'By Fund';
            btnFund.className = 'btn btn-toggle' + (qnum === 16 ? ' active' : '');
            btnFund.onclick = () => {
                if (_currentQnum === 16) return;
                _legendTypeFilter = null;
                currentQuery = 16; _currentQnum = 16;
                loadQuery(16);
            };
            viewToggle.appendChild(btnParent);
            viewToggle.appendChild(btnFund);

            filterBar.appendChild(viewToggle);
            filterBar.appendChild(searchInput);
            filterBar.appendChild(clearBtn);
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

    // R7: Add totals rows at bottom of Register / Fund Register tab
    if ((qnum === 1 || qnum === 16) && pageData.length > 0) {
        const table = tableWrap.querySelector('.data-table');
        if (table) {
            _buildRegisterTotals(table, pageData);
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

    // Register tabs: use proportional widths for balanced layout
    const isRegister = (qnum === 1 || qnum === 16);
    const REG_WIDTHS = {
        // query 1 — Institution takes remaining space
        1: {'#': '3%', institution: null, value_live: '13%', shares: '11%', pct_float: '8%', aum: '12%', pct_aum: '8%', type: '8%'},
        // query 16 — Fund Name + Family share the text space
        16: {'#': '3%', institution: null, family: '14%', value_live: '12%', shares: '10%', pct_float: '7%', aum: '11%', pct_aum: '8%', type: '7%'},
    };

    const colgroup = document.createElement('colgroup');
    // # column
    const cgNum = document.createElement('col');
    if (isRegister) cgNum.style.width = REG_WIDTHS[qnum]['#'];
    else cgNum.style.width = '35px';
    colgroup.appendChild(cgNum);
    cols.forEach(col => {
        const cg = document.createElement('col');
        if (isRegister && REG_WIDTHS[qnum]) {
            const w = REG_WIDTHS[qnum][col.key];
            if (w) cg.style.width = w;
            // null = auto-fill remaining space (name column)
        } else {
            const meta = inferColMeta(col);
            if (meta.w) cg.style.width = meta.w;
        }
        colgroup.appendChild(cg);
    });
    table.appendChild(colgroup);

    // --- Header with # column ---
    const thead = document.createElement('thead');

    // Group header row (Register tab only)
    const hasGroups = cols.some(c => c.group);
    if (hasGroups) {
        const groupRow = document.createElement('tr');
        groupRow.className = 'column-group-row';
        // # column spacer
        const thGNum = document.createElement('th');
        thGNum.className = 'group-header-empty';
        groupRow.appendChild(thGNum);
        let i = 0;
        while (i < cols.length) {
            const grp = cols[i].group;
            let span = 1;
            while (i + span < cols.length && cols[i + span].group === grp) span++;
            const thG = document.createElement('th');
            thG.colSpan = span;
            if (grp) {
                const label = grp === '_ticker_' ? (currentTicker || '').toUpperCase() : grp;
                thG.textContent = label;
                thG.className = 'group-header';
            } else {
                thG.className = 'group-header-empty';
            }
            groupRow.appendChild(thG);
            i += span;
        }
        thead.appendChild(groupRow);
    }

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
        if (col.tooltip) th.title = col.tooltip;
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

        // Type tint — only active/hedge_fund get color
        const rtype = row.type || row.manager_type || '';
        const rtypeClean = rtype.replace(/[^a-z_]/gi, '').toLowerCase();
        tr.dataset.rowType = rtypeClean || 'unknown';
        tr.dataset.rowLevel = String(row.level || 0);
        if (rtypeClean === 'active' || rtypeClean === 'hedge_fund') {
            tr.classList.add('type-' + rtypeClean);
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

    // Sticky header: offset column header row below group header row
    const groupRow = table.querySelector('.column-group-row');
    if (groupRow) {
        requestAnimationFrame(() => {
            const grpH = groupRow.getBoundingClientRect().height;
            const colRow = groupRow.nextElementSibling;
            if (colRow) {
                colRow.querySelectorAll('th').forEach(th => { th.style.top = grpH + 'px'; });
            }
        });
    }

    // Re-apply type filter if one was active before re-render
    if (_legendTypeFilter) _applyTypeFilter();
}

/** Active legend type filter — null means "All" (no filter). */
let _legendTypeFilter = null;
let _registerAllTotals = null;
let _registerTypeTotals = {};

/** Build the clickable color-coding legend bar. */
function buildLegend() {
    const legend = document.createElement('div');
    legend.className = 'color-legend';
    const types = [
        ['sw-all',             'All',           null],
        ['sw-passive',         'Passive',       'passive'],
        ['sw-active',          'Active',        'active'],
        ['sw-quantitative',    'Quant',         'quantitative'],
        ['sw-hedge',           'Hedge',         'hedge_fund'],
        ['sw-activist',        'Activist',      'activist'],
        ['sw-private-equity',  'PE',            'private_equity'],
        ['sw-venture',         'VC',            'venture_capital'],
        ['sw-strategic',       'Strategic',     'strategic'],
        ['sw-wealth',          'Wealth Mgr',    'wealth_management'],
        ['sw-pension',         'Pension',       'pension_insurance'],
        ['sw-endowment',       'Endowment',     'endowment_foundation'],
        ['sw-swf',             'SWF',           'swf'],
        ['sw-mixed',           'Mixed',         'mixed'],
        ['sw-unknown',         'Unknown',       'unknown'],
    ];
    const items = [];
    types.forEach(([cls, label, typeVal]) => {
        const item = document.createElement('span');
        const isSelected = typeVal === _legendTypeFilter;
        item.className = 'legend-item' + (isSelected ? ' legend-active' : '')
            + (!isSelected && _legendTypeFilter !== null ? ' legend-dimmed' : '');
        item.dataset.typeFilter = typeVal || 'all';
        item.innerHTML = `<span class="legend-swatch ${cls}"></span>${label}`;
        item.onclick = () => {
            _legendTypeFilter = typeVal;
            items.forEach(it => {
                const isMe = it === item;
                it.classList.toggle('legend-active', isMe);
                it.classList.toggle('legend-dimmed', !isMe && typeVal !== null);
            });
            _applyTypeFilter();
        };
        legend.appendChild(item);
        items.push(item);
    });
    return legend;
}

/** Apply the legend type filter: show/hide rows & re-rank visible parents. */
function _applyTypeFilter() {
    const table = tableWrap.querySelector('.data-table');
    if (!table) return;
    const rows = table.querySelectorAll('tbody tr');
    let visibleRank = 0;
    rows.forEach(tr => {
        const rtype = tr.dataset.rowType || '';
        const level = parseInt(tr.dataset.rowLevel || '0', 10);
        if (level === 1) {
            // child follows parent visibility
            const parentId = tr.dataset.childOf;
            const parentTr = parentId ? table.querySelector(`tr[data-parent-id="${parentId}"]`) : null;
            tr.style.display = parentTr && parentTr.style.display === 'none' ? 'none' : '';
            return;
        }
        // parent row — match exactly (hedge_fund now has its own legend entry)
        const show = !_legendTypeFilter || rtype === _legendTypeFilter;
        tr.style.display = show ? '' : 'none';
        // hide children of hidden parents
        const pid = tr.dataset.parentId;
        if (pid) {
            table.querySelectorAll(`tr[data-child-of="${pid}"]`).forEach(ch => {
                ch.style.display = show ? '' : 'none';
                if (!show) ch.classList.remove('visible');
            });
        }
        if (show) {
            visibleRank++;
            const numCell = tr.querySelector('.col-rownum');
            if (numCell) numCell.textContent = visibleRank;
        }
    });
    // Rebuild totals to reflect filter
    if (currentData && currentData.length) {
        _buildRegisterTotals(table, currentData);
    }
}

/** Build totals footer for Register tab. Shows top-25 total, all-investors total,
 *  and filtered category total when a legend filter is active. */
function _buildRegisterTotals(table, pageData) {
    // Remove existing totals
    table.querySelectorAll('.register-totals-row').forEach(r => r.remove());
    const tbody = table.querySelector('tbody');
    const cols = QUERY_COLUMNS[_currentQnum] || QUERY_COLUMNS[1];
    const parentRows = pageData.filter(r => !r.level || r.level === 0);

    function _makeTotalsRow(label, srcRows, extraClass) {
        const tr = document.createElement('tr');
        tr.className = 'register-totals-row ' + (extraClass || '');
        tr.style.cssText = 'font-weight:700;background:#f0f4f8;';
        const tdNum = document.createElement('td');
        tdNum.className = 'col-rownum';
        tr.appendChild(tdNum);
        cols.forEach(c => {
            const td = document.createElement('td');
            td.style.textAlign = _isNumericCol(c.type) ? 'right' : 'left';
            if (c.key === 'institution') {
                td.textContent = label;
            } else if (srcRows && (c.type === 'dollar' || c.type === 'shares')) {
                let sum = 0;
                srcRows.forEach(r => { if (r[c.key]) sum += r[c.key]; });
                td.innerHTML = sum ? _formatCellValue(sum, c.type) : '—';
            } else if (srcRows && c.key === 'pct_float') {
                let sum = 0;
                srcRows.forEach(r => { if (r[c.key]) sum += r[c.key]; });
                td.innerHTML = sum ? fmtPct(sum) : '—';
            } else {
                td.textContent = '';
            }
            tr.appendChild(td);
        });
        return tr;
    }

    function _makeTotalsRowFromObj(label, obj, extraClass) {
        const tr = document.createElement('tr');
        tr.className = 'register-totals-row ' + (extraClass || '');
        tr.style.cssText = 'font-weight:700;background:#f0f4f8;';
        const tdNum = document.createElement('td');
        tdNum.className = 'col-rownum';
        tr.appendChild(tdNum);
        cols.forEach(c => {
            const td = document.createElement('td');
            td.style.textAlign = _isNumericCol(c.type) ? 'right' : 'left';
            if (c.key === 'institution') {
                td.textContent = label;
            } else if (obj && c.key === 'value_live' && obj.value_live) {
                td.innerHTML = _formatCellValue(obj.value_live, 'dollar');
            } else if (obj && c.key === 'shares' && obj.shares) {
                td.innerHTML = _formatCellValue(obj.shares, 'shares');
            } else if (obj && c.key === 'pct_float' && obj.pct_float) {
                td.innerHTML = fmtPct(obj.pct_float);
            } else {
                td.textContent = '';
            }
            tr.appendChild(td);
        });
        return tr;
    }

    // 1. Top-25 shown total (from visible data)
    const shownRow = _makeTotalsRow(
        `TOP ${parentRows.length} SHOWN`, parentRows, 'totals-shown');
    shownRow.style.borderTop = '3px solid #002147';
    tbody.appendChild(shownRow);

    // 2. All investors total (from backend)
    if (_registerAllTotals) {
        const allRow = _makeTotalsRowFromObj(
            `ALL INVESTORS (${_registerAllTotals.count})`, _registerAllTotals, 'totals-all');
        tbody.appendChild(allRow);
    }

    // 3. Category total when legend filter is active
    if (_legendTypeFilter && _registerTypeTotals) {
        const filterType = _legendTypeFilter;
        // Combine active + hedge_fund when "active" selected
        let catTotal = null;
        if (filterType === 'active') {
            const a = _registerTypeTotals['active'];
            const h = _registerTypeTotals['hedge_fund'];
            if (a || h) {
                catTotal = {
                    value_live: (a?.value_live || 0) + (h?.value_live || 0),
                    shares: (a?.shares || 0) + (h?.shares || 0),
                    pct_float: (a?.pct_float || 0) + (h?.pct_float || 0),
                    count: (a?.count || 0) + (h?.count || 0),
                };
            }
        } else {
            catTotal = _registerTypeTotals[filterType] || null;
        }
        if (catTotal) {
            const typeName = filterType.charAt(0).toUpperCase() + filterType.slice(1);
            // Shown in category (from visible rows)
            const visibleOfType = parentRows.filter(r => {
                const rt = (r.type || '').toLowerCase();
                if (filterType === 'active') return rt === 'active' || rt === 'hedge_fund';
                return rt === filterType;
            });
            const catShown = _makeTotalsRow(
                `${typeName.toUpperCase()} SHOWN (${visibleOfType.length})`, visibleOfType, 'totals-cat-shown');
            catShown.style.borderTop = '2px solid var(--sandstone)';
            tbody.appendChild(catShown);
            // All in category
            const catAll = _makeTotalsRowFromObj(
                `${typeName.toUpperCase()} ALL (${catTotal.count})`, catTotal, 'totals-cat-all');
            tbody.appendChild(catAll);
        }
    }

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

let _convictionLevel = 'parent';
let _convictionActiveOnly = false;

async function loadConviction() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const ao = _convictionActiveOnly && _convictionLevel === 'fund' ? '&active_only=true' : '';
        const res = await fetch(`/api/portfolio_context?ticker=${currentTicker}&level=${_convictionLevel}${ao}`);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        _renderConviction(data);
    } catch (e) { hideSpinner(); showError(e.message); }
}

function _renderConviction(data) {
    const rows = data.rows || [];
    const subjSector = data.subject_sector || 'Unknown';
    const subjCode = data.subject_sector_code || '';
    const subjIndustry = data.subject_industry || '';

    // Control bar: level toggle + active only + search
    const cbar = document.createElement('div');
    cbar.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 0;flex-wrap:wrap;';

    const lvlGroup = document.createElement('div');
    lvlGroup.className = 'register-view-toggle';
    [['parent', 'By Parent'], ['fund', 'By Fund']].forEach(([v, txt]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-toggle' + (_convictionLevel === v ? ' active' : '');
        btn.textContent = txt;
        btn.onclick = () => { _convictionLevel = v; loadConviction(); };
        lvlGroup.appendChild(btn);
    });
    cbar.appendChild(lvlGroup);

    if (_convictionLevel === 'fund') {
        const aoBtn = document.createElement('button');
        aoBtn.className = 'btn btn-toggle' + (_convictionActiveOnly ? ' active' : '');
        aoBtn.textContent = 'Active Only';
        aoBtn.style.marginLeft = '6px';
        aoBtn.onclick = () => { _convictionActiveOnly = !_convictionActiveOnly; loadConviction(); };
        cbar.appendChild(aoBtn);
    }

    // Search filter
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = 'Filter by institution name...';
    searchInput.style.cssText = 'padding:6px 12px;border:1px solid #ccc;border-radius:4px;font-size:13px;width:220px;margin-left:8px;';
    searchInput.autocomplete = 'off';
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
    cbar.appendChild(searchInput);

    const subjLabel = document.createElement('span');
    subjLabel.style.cssText = 'margin-left:auto;font-size:12px;color:#666;';
    subjLabel.innerHTML = `<strong>${currentTicker}</strong> &rarr; Sector: <strong>${subjSector}</strong> (${subjCode}) &middot; Industry: <strong>${subjIndustry || '\u2014'}</strong>`;
    cbar.appendChild(subjLabel);
    tableWrap.appendChild(cbar);

    // Legend filter (click to filter by type)
    tableWrap.appendChild(buildLegend());

    if (!rows.length) {
        tableWrap.appendChild(sectionHeader('No portfolio data available'));
        return;
    }

    // Build table
    const table = document.createElement('table');
    table.className = 'data-table';
    table.style.tableLayout = 'fixed';

    // Colgroup: #, Inst, Type, Value | Sector Analysis (5 cols) | Company Analysis (2 cols) | Data Quality (2 cols)
    const colgroup = document.createElement('colgroup');
    ['3%', null, '6%', '9%', '8%', '7%', '7%', '14%', '6%', '8%', '8%', '6%', '6%'].forEach(w => {
        const cg = document.createElement('col');
        if (w) cg.style.width = w;
        colgroup.appendChild(cg);
    });
    table.appendChild(colgroup);

    const nameLabel = _convictionLevel === 'fund' ? 'Fund' : 'Institution';
    const sectorColLabel = `% in ${subjSector}`;
    const spxWeight = data.subject_spx_weight;
    const spxLabel = spxWeight != null ? `vs MKT (${spxWeight}%)` : 'vs MKT';

    // Sortable column definitions: [label, align, sortKey, group]
    const colDefs = [
        [nameLabel, 'left', 'institution', null],
        ['Type', 'left', 'type', null],
        ['Value', 'right', 'value', null],
        // Sector Analysis group
        [sectorColLabel, 'right', 'subject_sector_pct', 'Sector Analysis'],
        [spxLabel, 'right', 'vs_spx', 'Sector Analysis'],
        ['Rank in\nPortfolio', 'right', 'sector_rank', 'Sector Analysis'],
        ['Top 3 Sectors', 'center', null, 'Sector Analysis'],
        ['# Sectors', 'right', 'diversity', 'Sector Analysis'],
        // Company Analysis group
        ['Rank in\nSector', 'right', 'co_rank_in_sector', 'Company Analysis'],
        ['Rank in\nIndustry', 'right', 'industry_rank', 'Company Analysis'],
        // Data Quality group
        ['Unk %', 'right', 'unk_pct', 'Data Quality'],
        ['ETF %', 'right', 'etf_pct', 'Data Quality'],
    ];

    const thead = document.createElement('thead');

    // Group header row
    const groupRow = document.createElement('tr');
    groupRow.className = 'column-group-row';
    const thGNum = document.createElement('th');
    thGNum.className = 'group-header-empty';
    groupRow.appendChild(thGNum);
    let gi = 0;
    while (gi < colDefs.length) {
        const grp = colDefs[gi][3];
        let span = 1;
        while (gi + span < colDefs.length && colDefs[gi + span][3] === grp) span++;
        const thG = document.createElement('th');
        thG.colSpan = span;
        if (grp) {
            thG.textContent = grp;
            thG.className = 'group-header';
        } else {
            thG.className = 'group-header-empty';
        }
        groupRow.appendChild(thG);
        gi += span;
    }
    thead.appendChild(groupRow);

    const hr = document.createElement('tr');
    const thN = document.createElement('th'); thN.textContent = '#'; thN.style.textAlign = 'right'; hr.appendChild(thN);

    // Current sort state
    let sortKey = 'value';
    let sortDir = 'desc';

    colDefs.forEach(([h, align, key]) => {
        const th = document.createElement('th');
        // Support \n for line breaks in headers
        const baseHtml = h.replace(/\n/g, '<br>');
        th.innerHTML = baseHtml;
        th.dataset.baseLabel = baseHtml;
        th.style.textAlign = align;
        th.style.whiteSpace = 'normal';
        th.style.verticalAlign = 'bottom';
        th.style.lineHeight = '1.2';
        if (key) {
            th.style.cursor = 'pointer';
            th.dataset.sortKey = key;
            th.addEventListener('click', () => {
                if (sortKey === key) {
                    sortDir = sortDir === 'desc' ? 'asc' : 'desc';
                } else {
                    sortKey = key;
                    sortDir = 'desc';
                }
                _rebuildConvictionRows();
                _updateSortIndicators();
            });
        }
        hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    function _updateSortIndicators() {
        hr.querySelectorAll('th').forEach(th => {
            const key = th.dataset.sortKey;
            if (!key) return;
            const base = th.dataset.baseLabel || th.innerHTML;
            const arrow = key === sortKey ? (sortDir === 'desc' ? ' \u25BC' : ' \u25B2') : '';
            th.innerHTML = base + arrow;
        });
    }

    const tbody = document.createElement('tbody');

    // Organize rows: parents with their children grouped beneath them
    // so sorting can rearrange parent groups without breaking the hierarchy
    const parentsList = rows.filter(r => r.level === 0);
    const childrenByParent = {};
    let currentParent = null;
    rows.forEach(r => {
        if (r.level === 0) {
            currentParent = r.institution;
            childrenByParent[currentParent] = [];
        } else if (r.level === 1 && currentParent) {
            childrenByParent[currentParent].push(r);
        }
    });

    function _sortedParents() {
        const sorted = [...parentsList];
        sorted.sort((a, b) => {
            let av = a[sortKey];
            let bv = b[sortKey];
            // null handling: push nulls to end
            if (av == null && bv == null) return 0;
            if (av == null) return 1;
            if (bv == null) return -1;
            if (typeof av === 'string') {
                return sortDir === 'desc' ? bv.localeCompare(av) : av.localeCompare(bv);
            }
            return sortDir === 'desc' ? bv - av : av - bv;
        });
        return sorted;
    }

    function _rebuildConvictionRows() {
        tbody.innerHTML = '';
        let parentIdx = 0;
        const sortedParents = _sortedParents();
        let rank = 0;
        sortedParents.forEach(parentRow => {
            rank++;
            parentRow.rank = rank;
            _renderConvictionRow(parentRow, ++parentIdx, tbody);
            const kids = childrenByParent[parentRow.institution] || [];
            kids.forEach(kid => _renderConvictionRow(kid, parentIdx, tbody));
        });
        // Re-append totals row after rebuild
        _appendConvictionTotals(tbody, parentsList);
        // Re-apply type filter if active
        if (_legendTypeFilter) _applyTypeFilter();
    }

    function _renderConvictionRow(row, parentIdx, tbody) {
        const tr = document.createElement('tr');
        const isChild = row.level === 1;
        const isParent = row.is_parent === true;

        // Type tint — only active/hedge_fund
        const rtype = (row.type || '').toLowerCase();
        if (rtype === 'active' || rtype === 'hedge_fund') {
            tr.classList.add('type-' + rtype);
        }
        tr.dataset.rowType = rtype || 'unknown';
        tr.dataset.rowLevel = String(row.level || 0);

        // Collapsible setup
        if (isParent) {
            parentIdx++;
            tr.dataset.parentId = 'cvp' + parentIdx;
            tr.classList.add('collapsible-parent');
        } else if (isChild) {
            tr.dataset.childOf = 'cvp' + parentIdx;
            tr.classList.add('child-row');
            tr.style.fontSize = '11px';
            tr.style.color = '#555';
        }

        // #
        const tdN = document.createElement('td');
        tdN.className = 'col-rownum';
        if (!isChild) {
            tdN.textContent = row.rank;
            tdN.style.fontWeight = '700';
        }
        tr.appendChild(tdN);

        // Institution / Fund (with toggle arrow if parent)
        const tdName = document.createElement('td');
        tdName.classList.add('col-text-overflow');
        if (isParent) {
            tdName.appendChild(document.createTextNode((row.institution || '') + ' '));
            const arrow = document.createElement('span');
            arrow.className = 'toggle-arrow';
            arrow.textContent = '\u25B6';
            tdName.appendChild(arrow);
            tdName.style.cursor = 'pointer';
        } else if (isChild) {
            tdName.style.paddingLeft = '24px';
            tdName.textContent = row.institution || '';
        } else {
            tdName.textContent = row.institution || '';
        }
        tdName.title = row.institution || '';
        tr.appendChild(tdName);

        // Type
        const tdType = document.createElement('td');
        tdType.textContent = row.type || '';
        tdType.style.fontSize = '11px';
        tr.appendChild(tdType);

        // Value
        const tdVal = document.createElement('td');
        tdVal.style.textAlign = 'right';
        tdVal.innerHTML = fmtDollars(row.value);
        tr.appendChild(tdVal);

        // --- Sector Analysis group ---
        // % in Sector
        const tdSec = document.createElement('td');
        tdSec.style.textAlign = 'right';
        tdSec.textContent = (row.subject_sector_pct != null) ? row.subject_sector_pct.toFixed(1) + '%' : '\u2014';
        tdSec.style.fontWeight = '600';
        tr.appendChild(tdSec);

        // vs MKT (overweight/underweight)
        const tdVs = document.createElement('td');
        tdVs.style.textAlign = 'right';
        if (row.vs_spx != null) {
            const v = row.vs_spx;
            if (v > 0) {
                tdVs.innerHTML = '<span class="positive">+' + v.toFixed(1) + 'pp</span>';
            } else if (v < 0) {
                tdVs.innerHTML = '<span class="negative">(' + Math.abs(v).toFixed(1) + 'pp)</span>';
            } else {
                tdVs.textContent = '0.0pp';
                tdVs.style.color = '#999';
            }
        } else {
            tdVs.textContent = '\u2014';
            tdVs.style.color = '#999';
        }
        tr.appendChild(tdVs);

        // Rank in Portfolio (sector_rank)
        const tdSR = document.createElement('td');
        tdSR.style.textAlign = 'right';
        tdSR.textContent = row.sector_rank || '\u2014';
        if (row.sector_rank === 1) { tdSR.style.color = '#27AE60'; tdSR.style.fontWeight = '700'; }
        tr.appendChild(tdSR);

        // Top 3 Sectors — colored pills
        const tdT3 = document.createElement('td');
        tdT3.style.textAlign = 'center';
        tdT3.style.whiteSpace = 'nowrap';
        (row.top3 || []).forEach(code => {
            const pill = document.createElement('span');
            pill.className = 'sector-pill sp-' + code.toLowerCase();
            pill.textContent = code;
            tdT3.appendChild(pill);
        });
        tr.appendChild(tdT3);

        // # Sectors (diversity)
        const tdDiv = document.createElement('td');
        tdDiv.style.textAlign = 'right';
        tdDiv.textContent = row.diversity || '\u2014';
        if (row.diversity && row.diversity < 5) tdDiv.style.color = '#E67E22';
        tr.appendChild(tdDiv);

        // --- Company Analysis group ---
        // Rank in Sector
        const tdCR = document.createElement('td');
        tdCR.style.textAlign = 'right';
        tdCR.textContent = row.co_rank_in_sector || '\u2014';
        if (row.co_rank_in_sector === 1) { tdCR.style.color = '#27AE60'; tdCR.style.fontWeight = '700'; }
        tr.appendChild(tdCR);

        // Rank in Industry
        const tdIR = document.createElement('td');
        tdIR.style.textAlign = 'right';
        tdIR.textContent = row.industry_rank || '\u2014';
        if (row.industry_rank === 1) { tdIR.style.color = '#27AE60'; tdIR.style.fontWeight = '700'; }
        tr.appendChild(tdIR);

        // Unk %
        const tdUnk = document.createElement('td');
        tdUnk.style.textAlign = 'right';
        tdUnk.style.fontSize = '11px';
        tdUnk.textContent = (row.unk_pct != null) ? row.unk_pct.toFixed(0) + '%' : '\u2014';
        if (row.unk_pct && row.unk_pct > 20) tdUnk.style.color = '#E67E22';
        tr.appendChild(tdUnk);

        // ETF %
        const tdEtf = document.createElement('td');
        tdEtf.style.textAlign = 'right';
        tdEtf.style.fontSize = '11px';
        tdEtf.textContent = (row.etf_pct != null && row.etf_pct > 0) ? row.etf_pct.toFixed(0) + '%' : '\u2014';
        if (row.etf_pct && row.etf_pct > 30) tdEtf.style.color = '#E67E22';
        tr.appendChild(tdEtf);

        tbody.appendChild(tr);
    }  // end of _renderConvictionRow

    function _appendConvictionTotals(tbody, parentRows) {
        if (parentRows.length === 0) return;
        const totals = document.createElement('tr');
        totals.style.cssText = 'font-weight:700;border-top:3px solid #002147;background:#f0f4f8;';
        const tdTNum = document.createElement('td');
        tdTNum.className = 'col-rownum';
        totals.appendChild(tdTNum);
        const tdTLabel = document.createElement('td');
        tdTLabel.textContent = `TOTAL (${parentRows.length} holders)`;
        totals.appendChild(tdTLabel);
        totals.appendChild(document.createElement('td'));
        const tdTVal = document.createElement('td');
        tdTVal.style.textAlign = 'right';
        const sumVal = parentRows.reduce((a, r) => a + (r.value || 0), 0);
        tdTVal.innerHTML = sumVal ? fmtDollars(sumVal) : '\u2014';
        totals.appendChild(tdTVal);
        // Remaining 9 columns (Sec%, vsMKT, RankPort, Top3, #Sec, RankSec, RankInd, Unk, ETF)
        for (let i = 0; i < 9; i++) {
            totals.appendChild(document.createElement('td'));
        }
        tbody.appendChild(totals);
    }

    // Initial render — uses default sortKey='value', sortDir='desc' (matches Register)
    _rebuildConvictionRows();
    _updateSortIndicators();

    table.appendChild(tbody);
    tableWrap.appendChild(table);

    // Collapsible click handlers — delegated so they work after re-sort
    tbody.addEventListener('click', (e) => {
        const parentTr = e.target.closest('.collapsible-parent');
        if (!parentTr || !tbody.contains(parentTr)) return;
        const pid = parentTr.dataset.parentId;
        const arrow = parentTr.querySelector('.toggle-arrow');
        const children = tbody.querySelectorAll(`tr[data-child-of="${pid}"]`);
        const isExpanded = children[0] && children[0].classList.contains('visible');
        children.forEach(c => { c.classList.toggle('visible', !isExpanded); });
        if (arrow) arrow.textContent = isExpanded ? '\u25B6' : '\u25BC';
    });

    // Legend footnote
    const fn = document.createElement('div');
    fn.style.cssText = 'font-size:11px;color:#888;padding:10px 0;line-height:1.5;';
    fn.innerHTML = '<strong>Sorted by Value (highest first). Click any column header to re-sort.</strong> '
        + `<strong>% in ${subjSector}</strong> = holder's portfolio % allocated to ${subjSector}. `
        + `<strong>vs MKT</strong> = overweight/underweight vs US market sector weight (${subjSector} = ${data.subject_spx_weight || '?'}%). Market weight derived from Vanguard Total Stock Market Index Fund, updated per quarter. `
        + `<strong>Rank in Portfolio</strong> = where ${subjSector} ranks among this holder's sectors (1 = their top sector). `
        + `<strong>Rank in Sector</strong> = where ${currentTicker} ranks among this holder's ${subjSector} positions. `
        + `<strong>Rank in Industry</strong> = where ${currentTicker} ranks within their ${subjIndustry || 'industry'} bucket. `
        + '<strong>Top 3 Sectors</strong> = holder\'s 3 largest sector allocations as colored pills. '
        + '<strong># Sectors</strong> = count of distinct sectors held. '
        + '<strong>Unk %</strong> = % of portfolio with no sector classification. '
        + '<strong>ETF %</strong> = % of portfolio held as ETFs (excluded from sector math — ETFs are multi-sector instruments).';
    tableWrap.appendChild(fn);
}

async function loadShortAnalysis() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const res = await fetch(`/api/short_analysis?ticker=${currentTicker}`);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        _renderShortAnalysis(data);
    } catch (e) { hideSpinner(); showError(e.message); }
}

function _renderShortAnalysis(data) {
    const summary = data.summary || {};
    const qs = summary.quarters_available || [];

    // Summary card
    const card = document.createElement('div');
    card.className = 'portfolio-stats';
    [
        ['Short Funds (N-PORT)', summary.short_funds || 0],
        ['Short Shares', summary.short_shares ? fmtShares(summary.short_shares) : '0'],
        ['Avg Short Vol %', summary.avg_short_vol_pct ? summary.avg_short_vol_pct + '%' : '\u2014'],
        ['Long & Short', summary.cross_ref_count || 0],
    ].forEach(([l, v]) => {
        const s = document.createElement('span');
        s.className = 'ps-item';
        s.innerHTML = `<span class="ps-label">${l}:</span><span class="ps-value">${v}</span>`;
        card.appendChild(s);
    });
    tableWrap.appendChild(card);

    // --- Section 1: N-PORT Short Trend Chart ---
    const nportTrend = data.nport_trend || [];
    if (nportTrend.length > 0 && typeof Chart !== 'undefined') {
        tableWrap.appendChild(sectionHeader('N-PORT Short Positions — Quarterly Trend'));
        const chartRow = document.createElement('div');
        chartRow.style.cssText = 'display:flex;gap:16px;';

        // Shares chart
        const c1 = document.createElement('div');
        c1.className = 'chart-card'; c1.style.cssText = 'flex:1;';
        c1.innerHTML = '<div style="font-size:12px;font-weight:600;color:#002147;text-align:center;margin-bottom:4px;">Short Shares</div>';
        const w1 = document.createElement('div'); w1.style.cssText = 'position:relative;height:160px;';
        const cv1 = document.createElement('canvas'); w1.appendChild(cv1); c1.appendChild(w1);

        // Fund count chart
        const c2 = document.createElement('div');
        c2.className = 'chart-card'; c2.style.cssText = 'flex:1;';
        c2.innerHTML = '<div style="font-size:12px;font-weight:600;color:#002147;text-align:center;margin-bottom:4px;">Funds Shorting</div>';
        const w2 = document.createElement('div'); w2.style.cssText = 'position:relative;height:160px;';
        const cv2 = document.createElement('canvas'); w2.appendChild(cv2); c2.appendChild(w2);

        chartRow.appendChild(c1); chartRow.appendChild(c2);
        tableWrap.appendChild(chartRow);

        setTimeout(() => {
            if (window._siChart1) { window._siChart1.destroy(); }
            if (window._siChart2) { window._siChart2.destroy(); }
            const labels = nportTrend.map(d => d.quarter);
            window._siChart1 = new Chart(cv1, {
                type: 'bar',
                data: { labels, datasets: [{ data: nportTrend.map(d => d.short_shares || 0), backgroundColor: '#C0392B', borderRadius: 3, barPercentage: 0.5 }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => fmtShares(ctx.parsed.y) } } }, scales: { x: { ticks: { font: { size: 12 } } }, y: { ticks: { font: { size: 11 }, callback: v => fmtShares(v) } } } },
            });
            window._siChart2 = new Chart(cv2, {
                type: 'bar',
                data: { labels, datasets: [{ data: nportTrend.map(d => d.fund_count || 0), backgroundColor: '#E74C3C', borderRadius: 3, barPercentage: 0.5 }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { font: { size: 12 } } }, y: { ticks: { font: { size: 11 }, stepSize: 1 } } } },
            });
        }, 100);
    }

    // --- Section 2: FINRA Short Volume Chart ---
    const shortVol = data.short_volume || [];
    if (shortVol.length > 0 && typeof Chart !== 'undefined') {
        tableWrap.appendChild(sectionHeader('Daily Short Sale Volume (FINRA)'));
        const svCard = document.createElement('div');
        svCard.className = 'chart-card';
        const svWrap = document.createElement('div');
        svWrap.style.cssText = 'position:relative;height:180px;';
        const svCanvas = document.createElement('canvas');
        svWrap.appendChild(svCanvas); svCard.appendChild(svWrap);
        tableWrap.appendChild(svCard);

        // Compute 5-day moving average
        const pcts = shortVol.map(d => d.short_pct || 0);
        const ma5 = pcts.map((_, i) => {
            const start = Math.max(0, i - 4);
            const slice = pcts.slice(start, i + 1);
            return slice.reduce((a, b) => a + b, 0) / slice.length;
        });

        setTimeout(() => {
            if (window._svChart) window._svChart.destroy();
            const labels = shortVol.map(d => {
                const dt = String(d.report_date || '').slice(5, 10);
                return dt;
            });
            window._svChart = new Chart(svCanvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        { type: 'bar', label: 'Short Vol %', data: pcts, backgroundColor: pcts.map(v => v > 40 ? '#C0392B' : '#E8B8B8'), borderRadius: 1, barPercentage: 0.8, order: 2 },
                        { type: 'line', label: '5-Day Avg', data: ma5, borderColor: '#002147', borderWidth: 2, pointRadius: 0, tension: 0.3, order: 1 },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom', labels: { font: { size: 11 } } }, tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(1) + '%' } } },
                    scales: { x: { ticks: { font: { size: 10 }, maxRotation: 45 } }, y: { ticks: { font: { size: 11 }, callback: v => v.toFixed(0) + '%' } } },
                },
            });
        }, 120);

        const svNote = document.createElement('div');
        svNote.style.cssText = 'font-size:10px;color:#aaa;font-style:italic;padding:4px 0;';
        svNote.textContent = 'FINRA short volume includes market makers and hedging. 30-40% is typical for liquid stocks. Sustained >50% may signal directional shorting.';
        tableWrap.appendChild(svNote);
    }

    // --- Section 3: N-PORT Short Fund Detail ---
    const nportDetail = data.nport_detail || [];
    if (nportDetail.length > 0) {
        tableWrap.appendChild(sectionHeader('Fund-Level Short Positions (Latest Quarter)'));
        const table = _flowTable(nportDetail, [
            {key: 'fund_name', label: 'Fund', type: 'text'},
            {key: 'family_name', label: 'Family', type: 'text'},
            {key: 'type', label: 'Type', type: 'text'},
            {key: 'short_shares', label: 'Short Shares', type: 'shares'},
            {key: 'short_value', label: 'Short Value', type: 'dollar'},
            {key: 'pct_of_nav', label: '% of NAV', type: 'pct'},
        ]);
        tableWrap.appendChild(table);
    }

    // --- Section 4: Long/Short Cross-Reference ---
    const crossRef = data.cross_ref || [];
    if (crossRef.length > 0) {
        tableWrap.appendChild(sectionHeader('Institutions Both Long & Short'));
        const table = _flowTable(crossRef, [
            {key: 'institution', label: 'Institution', type: 'text'},
            {key: 'type', label: 'Type', type: 'text'},
            {key: 'long_shares', label: 'Long Shares', type: 'shares'},
            {key: 'long_value', label: 'Long Value', type: 'dollar'},
            {key: 'short_shares', label: 'Short Shares', type: 'shares'},
            {key: 'short_value', label: 'Short Value', type: 'dollar'},
            {key: 'net_exposure_pct', label: 'Net Exp %', type: 'pct'},
        ]);
        tableWrap.appendChild(table);
    }

    // --- Section 4b: Short-Only Funds (merged from Smart Money) ---
    const shortOnly = data.short_only_funds || [];
    if (shortOnly.length > 0) {
        tableWrap.appendChild(sectionHeader('Short-Only Funds (No Matching Long Position)'));
        const table = _flowTable(shortOnly, [
            {key: 'fund_name', label: 'Fund', type: 'text'},
            {key: 'family_name', label: 'Family', type: 'text'},
            {key: 'type', label: 'Type', type: 'text'},
            {key: 'short_shares', label: 'Short Shares', type: 'shares'},
            {key: 'short_value', label: 'Short Value', type: 'dollar'},
            {key: 'fund_aum_mm', label: 'Fund AUM ($M)', type: 'num'},
        ]);
        tableWrap.appendChild(table);
    }

    // --- Section 5: N-PORT Short History by Fund ---
    const nportByFund = data.nport_by_fund || [];
    if (nportByFund.length > 0 && qs.length > 0) {
        tableWrap.appendChild(sectionHeader('Short Position History by Fund'));
        const table = document.createElement('table');
        table.className = 'data-table'; table.style.tableLayout = 'fixed';
        const colgroup = document.createElement('colgroup');
        // Fund (flex), Type, then quarter columns
        const qWidth = Math.floor(55 / qs.length) + '%';
        [null, '8%'].concat(qs.map(() => qWidth)).forEach(w => {
            const cg = document.createElement('col');
            if (w) cg.style.width = w;
            colgroup.appendChild(cg);
        });
        table.appendChild(colgroup);
        const thead = document.createElement('thead');
        const hr = document.createElement('tr');
        const thFund = document.createElement('th'); thFund.textContent = 'Fund'; hr.appendChild(thFund);
        const thType = document.createElement('th'); thType.textContent = 'Type'; thType.style.textAlign = 'left'; hr.appendChild(thType);
        qs.forEach(q => { const th = document.createElement('th'); th.textContent = q; th.style.textAlign = 'right'; hr.appendChild(th); });
        thead.appendChild(hr); table.appendChild(thead);
        const tbody = document.createElement('tbody');
        nportByFund.forEach((row, idx) => {
            const tr = document.createElement('tr');
            if (idx % 2 === 1) tr.style.backgroundColor = '#FDF0F0';
            const tdN = document.createElement('td');
            tdN.classList.add('col-text-overflow');
            tdN.textContent = row.fund_name || '';
            tdN.title = row.fund_name || '';
            tr.appendChild(tdN);
            const tdT = document.createElement('td');
            tdT.textContent = row.type || '';
            tdT.style.fontSize = '11px';
            tr.appendChild(tdT);
            qs.forEach(q => {
                const td = document.createElement('td');
                td.style.textAlign = 'right';
                const v = row[q];
                td.innerHTML = v ? fmtShares(v) : '<span style="color:#ccc">\u2014</span>';
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        tableWrap.appendChild(table);
    }
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

// ---------------------------------------------------------------------------
// Sector Rotation tab — multi-quarter institutional money flows by sector
// ---------------------------------------------------------------------------
let _srActiveOnly = false;
let _srLevel = 'parent';
let _srRankBy = 'total';  // 'total' | 'latest'
let _srData = null;
let _srExpandedSector = null;

function _fmtFlow(val) {
    if (val == null || isNaN(val)) return '\u2014';
    const abs = Math.abs(val);
    let num;
    if (abs >= 1e12) num = '$' + (abs / 1e12).toFixed(1) + 'T';
    else if (abs >= 1e9)  num = '$' + (abs / 1e9).toFixed(1) + 'B';
    else if (abs >= 1e6)  num = '$' + (abs / 1e6).toFixed(0) + 'M';
    else if (abs >= 1e3)  num = '$' + (abs / 1e3).toFixed(0) + 'K';
    else num = '$' + abs.toFixed(0);
    // Negatives in red parentheses, positives with +
    return val < 0 ? '<span class="flow-negative">(' + num + ')</span>' : '+' + num;
}

function _flowClass(val) {
    if (val == null || val === 0) return '';
    return val > 0 ? 'flow-positive' : 'flow-negative';
}

async function loadSectorRotation() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    try {
        const url = `/api/sector_flows?active_only=${_srActiveOnly ? 1 : 0}&level=${_srLevel}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _srData = await res.json();
        hideSpinner();
        _srExpandedSector = null;
        _renderSectorRotation();
    } catch (e) { hideSpinner(); showError(e.message); }
}

function _renderSectorRotation() {
    const data = _srData;
    if (!data || !data.sectors) return;
    const wrap = tableWrap;
    wrap.innerHTML = '';

    // Filter bar
    const bar = document.createElement('div');
    bar.className = 'register-filter-bar';
    bar.innerHTML = `
        <div class="register-view-toggle">
            <button class="btn btn-sm ${_srLevel === 'parent' ? 'btn-primary' : 'btn-secondary'}" data-sr-level="parent">By Parent</button>
            <button class="btn btn-sm ${_srLevel === 'fund' ? 'btn-primary' : 'btn-secondary'}" data-sr-level="fund">By Fund</button>
        </div>
        <div class="register-view-toggle">
            <span style="font-size:11px;color:#888;margin-right:4px;">Rank by:</span>
            <button class="btn btn-sm ${_srRankBy === 'total' ? 'btn-primary' : 'btn-secondary'}" data-sr-rank="total">Full Year</button>
            <button class="btn btn-sm ${_srRankBy === 'latest' ? 'btn-primary' : 'btn-secondary'}" data-sr-rank="latest">Last Quarter</button>
        </div>
        <button class="btn btn-sm ${_srActiveOnly ? 'btn-primary' : 'btn-secondary'}" id="sr-active-toggle">Active Only</button>
    `;
    wrap.appendChild(bar);
    // Re-expand helper: re-renders and re-opens the same sector
    function _reExpandIfOpen(settingFn) {
        settingFn();
        const wasExpanded = _srExpandedSector;
        _srExpandedSector = null;
        _renderSectorRotation();
        if (wasExpanded) {
            setTimeout(() => {
                const row = wrap.querySelector(`tr[data-sector="${CSS.escape(wasExpanded)}"]`);
                if (row) row.click();
            }, 50);
        }
    }

    bar.querySelectorAll('[data-sr-level]').forEach(btn => {
        btn.addEventListener('click', () => {
            _srLevel = btn.dataset.srLevel;
            loadSectorRotation();  // re-fetch: different data source (13F vs N-PORT)
        });
    });
    bar.querySelectorAll('[data-sr-rank]').forEach(btn => {
        btn.addEventListener('click', () => _reExpandIfOpen(() => { _srRankBy = btn.dataset.srRank; }));
    });
    bar.querySelector('#sr-active-toggle').addEventListener('click', () => {
        _srActiveOnly = !_srActiveOnly;
        loadSectorRotation();
    });

    if (!data.periods.length) {
        wrap.innerHTML += '<div class="no-data">No quarter data available for sector flow analysis.</div>';
        return;
    }

    // Sort sectors by selected ranking
    const sortKey = _srRankBy === 'latest' ? 'latest_net' : 'total_net';
    data.sectors.sort((a, b) => (b[sortKey] || 0) - (a[sortKey] || 0));

    // Build table
    const table = document.createElement('table');
    table.className = 'data-table sector-flow-table';

    // Colgroup
    const cg = document.createElement('colgroup');
    cg.innerHTML = '<col style="width:3%"><col style="width:3%"><col style="width:auto">';
    data.periods.forEach(() => { cg.innerHTML += '<col style="width:13%">'; });
    cg.innerHTML += '<col style="width:13%">';
    table.appendChild(cg);

    // Header
    const thead = document.createElement('thead');
    let hrow = '<tr><th></th><th class="col-right">#</th><th class="col-left">Sector</th>';
    data.periods.forEach(p => { hrow += `<th class="col-right">${p.label}</th>`; });
    hrow += '<th class="col-right">Total</th></tr>';
    thead.innerHTML = hrow;
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');

    // Compute grand totals while building rows
    const grandTotals = {};
    let grandNet = 0;
    data.periods.forEach(p => { grandTotals[`${p.from}_${p.to}`] = 0; });

    data.sectors.forEach((s, idx) => {
        const tr = document.createElement('tr');
        tr.className = 'sector-flow-row';
        tr.dataset.sector = s.sector;
        tr.style.cursor = 'pointer';

        let cells = `<td class="toggle-arrow-cell"><span class="toggle-arrow">\u25B6</span></td>`;
        cells += `<td class="col-right" style="color:#888;font-size:12px;">${idx + 1}</td>`;
        cells += `<td class="col-left"><strong>${s.sector}</strong></td>`;

        data.periods.forEach(p => {
            const pk = `${p.from}_${p.to}`;
            const net = (s.flows[pk] || {}).net || 0;
            grandTotals[pk] += net;
            cells += `<td class="col-right">${_fmtFlow(net)}</td>`;
        });

        grandNet += (s.total_net || 0);
        cells += `<td class="col-right"><strong>${_fmtFlow(s.total_net)}</strong></td>`;
        tr.innerHTML = cells;
        tbody.appendChild(tr);

        tr.addEventListener('click', () => _toggleSectorDetail(s.sector, tr, tbody));
    });

    // Grand totals row
    const totRow = document.createElement('tr');
    totRow.className = 'register-totals-row';
    let totCells = '<td></td><td></td><td class="col-left"><strong>Total' +
        (_srActiveOnly ? ' (Active)' : ' (All Managers)') + '</strong></td>';
    data.periods.forEach(p => {
        const pk = `${p.from}_${p.to}`;
        const v = grandTotals[pk];
        totCells += `<td class="col-right"><strong>${_fmtFlow(v)}</strong></td>`;
    });
    totCells += `<td class="col-right"><strong>${_fmtFlow(grandNet)}</strong></td>`;
    totRow.innerHTML = totCells;
    tbody.appendChild(totRow);

    table.appendChild(tbody);
    wrap.appendChild(table);
}

async function _toggleSectorDetail(sector, parentRow, tbody) {
    // Collapse if already expanded
    const existing = tbody.querySelectorAll(`.sector-detail-row[data-sector="${CSS.escape(sector)}"]`);
    if (existing.length) {
        existing.forEach(r => r.remove());
        parentRow.querySelector('.toggle-arrow').style.transform = 'rotate(0deg)';
        _srExpandedSector = null;
        return;
    }
    // Collapse any other expanded sector
    tbody.querySelectorAll('.sector-detail-row').forEach(r => r.remove());
    tbody.querySelectorAll('.toggle-arrow').forEach(a => a.style.transform = 'rotate(0deg)');

    parentRow.querySelector('.toggle-arrow').style.transform = 'rotate(90deg)';
    _srExpandedSector = sector;

    // Loading placeholder
    const loadRow = document.createElement('tr');
    loadRow.className = 'sector-detail-row';
    loadRow.dataset.sector = sector;
    const loadTd = document.createElement('td');
    loadTd.colSpan = 3 + _srData.periods.length + 1;
    loadTd.innerHTML = '<div class="sector-detail-loading">Loading...</div>';
    loadRow.appendChild(loadTd);
    parentRow.after(loadRow);

    try {
        const url = `/api/sector_flow_detail?sector=${encodeURIComponent(sector)}` +
            `&active_only=${_srActiveOnly ? 1 : 0}&level=${_srLevel}&rank_by=${_srRankBy}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();

        loadRow.remove();
        const pks = d.periods.map(p => `${p.from}_${p.to}`);

        // Helper: build a detail row with values aligned to quarter columns
        function makeDetailRow(label, valsByPk, totalVal, extraClass) {
            const tr = document.createElement('tr');
            tr.className = 'sector-detail-row';
            if (extraClass) tr.classList.add(extraClass);
            tr.dataset.sector = sector;
            let cells = `<td></td><td></td><td class="col-left sector-detail-label">${label}</td>`;
            pks.forEach(pk => {
                const v = (valsByPk && valsByPk[pk]) || 0;
                cells += `<td class="col-right">${_fmtFlow(v)}</td>`;
            });
            const tv = totalVal || 0;
            cells += `<td class="col-right"><strong>${_fmtFlow(tv)}</strong></td>`;
            tr.innerHTML = cells;
            return tr;
        }

        // Helper: section label row (spans all columns)
        function makeLabelRow(label) {
            const tr = document.createElement('tr');
            tr.className = 'sector-detail-row sector-detail-sep';
            tr.dataset.sector = sector;
            const numCols = 3 + pks.length + 1;  // arrow + rank + sector + periods + total
            tr.innerHTML = `<td></td><td colspan="${numCols - 1}" class="col-left sector-section-label">${label}</td>`;
            return tr;
        }

        const fragment = document.createDocumentFragment();

        // Helper: apply box border classes to a group of rows
        function applyBox(rows, boxClass) {
            rows.forEach((r, i) => {
                r.classList.add(boxClass);
                if (i === 0) r.classList.add('box-first');
                if (i === rows.length - 1) r.classList.add('box-last');
            });
        }

        // Inflow / Outflow / Net rows — blue border box
        const flowRows = [
            makeDetailRow('Inflow', d.inflows, d.inflows.total),
            makeDetailRow('Outflow', d.outflows, d.outflows.total),
            makeDetailRow('<strong>Net</strong>', d.nets, d.nets.total),
        ];
        applyBox(flowRows, 'box-flow');
        flowRows.forEach(r => fragment.appendChild(r));

        // Top 5 Buying — green border box
        const buyLabel = makeLabelRow('Top 5 Buying');
        const buyRows = [buyLabel];
        (d.top_buyers || []).forEach(b => {
            buyRows.push(makeDetailRow(b.institution || '', b.flows, b.total));
        });
        applyBox(buyRows, 'box-buyers');
        buyRows.forEach(r => fragment.appendChild(r));

        // Top 5 Selling — red border box
        const sellLabel = makeLabelRow('Top 5 Selling');
        const sellRows = [sellLabel];
        (d.top_sellers || []).forEach(s => {
            sellRows.push(makeDetailRow(s.institution || '', s.flows, s.total));
        });
        applyBox(sellRows, 'box-sellers');
        sellRows.forEach(r => fragment.appendChild(r));

        parentRow.after(fragment);
    } catch (e) {
        loadRow.querySelector('td').innerHTML = `<div class="sector-detail-error">Error: ${e.message}</div>`;
    }
}

// ---------------------------------------------------------------------------
// Peer Rotation tab — per-ticker substitution analysis within sector
// ---------------------------------------------------------------------------
let _prLevel = 'parent';
let _prActiveOnly = false;
let _prData = null;
let _prCharts = [];  // track Chart.js instances for cleanup

function _prDestroyCharts() {
    _prCharts.forEach(c => { try { c.destroy(); } catch(_){} });
    _prCharts = [];
}

async function loadPeerRotation() {
    showSpinner(); clearError(); tableWrap.innerHTML = '';
    _prDestroyCharts();
    if (!currentTicker) {
        hideSpinner();
        tableWrap.innerHTML = '<div class="no-data">Enter a ticker above, then click Peer Rotation.</div>';
        return;
    }
    try {
        const url = `/api/peer_rotation?ticker=${currentTicker}&level=${_prLevel}&active_only=${_prActiveOnly ? 1 : 0}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _prData = await res.json();
        if (_prData.error) throw new Error(_prData.error);
        hideSpinner();
        _renderPeerRotation();
    } catch (e) { hideSpinner(); showError(e.message); }
}

function _renderPeerRotation() {
    const d = _prData;
    if (!d || !d.subject) return;
    const wrap = tableWrap;
    wrap.innerHTML = '';
    _prDestroyCharts();

    const pks = d.periods.map(p => `${p.from}_${p.to}`);

    // --- Filter bar ---
    const bar = document.createElement('div');
    bar.className = 'register-filter-bar';
    bar.innerHTML = `
        <div class="register-view-toggle">
            <button class="btn btn-sm ${_prLevel === 'parent' ? 'btn-primary' : 'btn-secondary'}" data-pr-level="parent">By Parent</button>
            <button class="btn btn-sm ${_prLevel === 'fund' ? 'btn-primary' : 'btn-secondary'}" data-pr-level="fund">By Fund</button>
        </div>
        <button class="btn btn-sm ${_prActiveOnly ? 'btn-primary' : 'btn-secondary'}" id="pr-active-toggle">Active Only</button>
    `;
    wrap.appendChild(bar);
    bar.querySelectorAll('[data-pr-level]').forEach(btn => {
        btn.addEventListener('click', () => { _prLevel = btn.dataset.prLevel; loadPeerRotation(); });
    });
    bar.querySelector('#pr-active-toggle').addEventListener('click', () => {
        _prActiveOnly = !_prActiveOnly; loadPeerRotation();
    });

    // --- Subject label ---
    const subjLabel = document.createElement('div');
    subjLabel.style.cssText = 'padding:8px 14px;font-size:14px;';
    subjLabel.innerHTML = `<strong>${d.subject.ticker}</strong> &mdash; ${d.subject.industry || '\u2014'} | ${d.subject.sector || '\u2014'}`;
    wrap.appendChild(subjLabel);

    // === SECTION 1: Subject vs Sector Summary ===
    _prBuildSummarySection(wrap, d, pks);

    // === SECTION 2: Substitution Waterfall Chart ===
    _prBuildWaterfallChart(wrap, d);

    // === SECTION 3: Industry Peer Substitutions ===
    if (d.industry_substitutions && d.industry_substitutions.length) {
        _prBuildSubsTable(wrap, d, pks, 'industry',
            `Industry Peer Substitutions \u2014 ${d.subject.industry || 'Same Industry'}`,
            d.industry_substitutions);
    }

    // === SECTION 4: Sector Peer Substitutions ===
    if (d.sector_substitutions && d.sector_substitutions.length) {
        _prBuildSubsTable(wrap, d, pks, 'sector',
            `Sector Peer Substitutions \u2014 ${d.subject.sector || 'Same Sector'} (broader)`,
            d.sector_substitutions);
    }

    // === SECTION 5: Top 5 Sector Movers ===
    _prBuildMoversSection(wrap, d, pks);

    // === SECTION 6: Entity Rotation Stories ===
    _prBuildEntityStories(wrap, d);
}

// --- Section 1: Summary table + grouped bar chart ---
function _prBuildSummarySection(wrap, d, pks) {
    const sec = document.createElement('div');
    sec.style.cssText = 'display:flex;gap:16px;padding:0 14px 8px;align-items:flex-start;flex-wrap:wrap;';

    // Table side
    const tblWrap = document.createElement('div');
    tblWrap.style.cssText = 'flex:1;min-width:400px;';
    const table = document.createElement('table');
    table.className = 'data-table';

    // Header
    let hdr = '<thead><tr><th class="col-left">Metric</th>';
    d.periods.forEach(p => { hdr += `<th class="col-right">${p.label}</th>`; });
    hdr += '<th class="col-right">Total</th></tr></thead>';
    table.innerHTML = hdr;

    const tbody = document.createElement('tbody');
    // Subject flow row
    _prSummaryRow(tbody, `${d.subject.ticker} Flow`, d.subject_flows, pks);
    // Sector flow row
    _prSummaryRow(tbody, `${d.subject.sector} Flow`, d.sector_flows, pks);
    // % of Sector row
    const pctRow = document.createElement('tr');
    let pctCells = `<td class="col-left">${d.subject.ticker} % of Sector</td>`;
    pks.forEach(pk => {
        const v = (d.subject_pct_of_sector || {})[pk];
        pctCells += `<td class="col-right">${v != null ? v.toFixed(1) + '%' : '\u2014'}</td>`;
    });
    const totPct = (d.subject_pct_of_sector || {}).total;
    pctCells += `<td class="col-right"><strong>${totPct != null ? totPct.toFixed(1) + '%' : '\u2014'}</strong></td>`;
    pctRow.innerHTML = pctCells;
    tbody.appendChild(pctRow);

    table.appendChild(tbody);
    tblWrap.appendChild(table);
    sec.appendChild(tblWrap);

    // Chart side — grouped bar chart
    const chartDiv = document.createElement('div');
    chartDiv.className = 'chart-card';
    chartDiv.style.cssText = 'flex:0 0 300px;height:250px;';
    const canvas = document.createElement('canvas');
    chartDiv.appendChild(canvas);
    sec.appendChild(chartDiv);
    wrap.appendChild(sec);

    setTimeout(() => {
        const labels = d.periods.map(p => p.label);
        const subjVals = pks.map(pk => ((d.subject_flows || {})[pk] || {}).net || 0);
        const sectVals = pks.map(pk => ((d.sector_flows || {})[pk] || {}).net || 0);
        // Scale sector down if it dwarfs subject
        const maxSubj = Math.max(...subjVals.map(Math.abs), 1);
        const maxSect = Math.max(...sectVals.map(Math.abs), 1);
        const useSecondary = maxSect > maxSubj * 10;

        const chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: d.subject.ticker,
                        data: subjVals.map(v => v / 1e6),
                        backgroundColor: '#1E2846',
                        yAxisID: 'y',
                    },
                    {
                        label: d.subject.sector,
                        data: sectVals.map(v => v / 1e6),
                        backgroundColor: '#b0c4de',
                        yAxisID: useSecondary ? 'y1' : 'y',
                    }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top', labels: { font: { size: 11 } } },
                    tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': $' + ctx.parsed.y.toFixed(0) + 'M' } },
                },
                scales: {
                    y: {
                        position: 'left',
                        ticks: { callback: v => '$' + v + 'M', font: { size: 10 } },
                    },
                    ...(useSecondary ? {
                        y1: {
                            position: 'right',
                            ticks: { callback: v => '$' + v + 'M', font: { size: 10 } },
                            grid: { drawOnChartArea: false },
                        }
                    } : {}),
                    x: { ticks: { font: { size: 10 } } },
                },
            }
        });
        _prCharts.push(chart);
    }, 100);
}

function _prSummaryRow(tbody, label, flowsObj, pks) {
    const tr = document.createElement('tr');
    let cells = `<td class="col-left">${label}</td>`;
    pks.forEach(pk => {
        const net = (flowsObj[pk] || {}).net || 0;
        cells += `<td class="col-right">${_fmtFlow(net)}</td>`;
    });
    const total = (flowsObj.total || {}).net || 0;
    cells += `<td class="col-right"><strong>${_fmtFlow(total)}</strong></td>`;
    tr.innerHTML = cells;
    tbody.appendChild(tr);
}

// --- Section 2: Substitution waterfall chart ---
function _prBuildWaterfallChart(wrap, d) {
    const subs = [...(d.industry_substitutions || []), ...(d.sector_substitutions || [])];
    if (!subs.length) return;
    // Take top 5 by magnitude
    const top5 = subs.slice(0, 5);
    if (!top5.length) return;

    const secDiv = document.createElement('div');
    secDiv.style.cssText = 'padding:0 14px 8px;';
    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'sector-section-label';
    sectionLabel.style.cssText = 'padding:8px 0 4px;';
    sectionLabel.textContent = 'Top Substitution Pairs';
    secDiv.appendChild(sectionLabel);

    const chartDiv = document.createElement('div');
    chartDiv.className = 'chart-card';
    chartDiv.style.height = '220px';
    const canvas = document.createElement('canvas');
    chartDiv.appendChild(canvas);
    secDiv.appendChild(chartDiv);
    wrap.appendChild(secDiv);

    setTimeout(() => {
        const labels = top5.map(s => s.ticker);
        const peerFlows = top5.map(s => (s.net_peer_flow || 0) / 1e6);
        const contraFlows = top5.map(s => (s.contra_subject_flow || 0) / 1e6);

        const chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Peer Flow',
                        data: peerFlows,
                        backgroundColor: peerFlows.map(v => v >= 0 ? '#2e7d32' : '#c62828'),
                    },
                    {
                        label: `Contra ${d.subject.ticker} Flow`,
                        data: contraFlows,
                        backgroundColor: contraFlows.map(v => v >= 0 ? '#81c784' : '#ef9a9a'),
                    }
                ]
            },
            options: {
                indexAxis: 'y',
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top', labels: { font: { size: 11 } } },
                    tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': $' + ctx.parsed.x.toFixed(0) + 'M' } },
                },
                scales: {
                    x: { ticks: { callback: v => '$' + v + 'M', font: { size: 10 } } },
                    y: { ticks: { font: { size: 11 } } },
                },
            }
        });
        _prCharts.push(chart);
    }, 100);
}

// --- Section 3/4: Substitution tables ---
function _prBuildSubsTable(wrap, d, pks, type, title, subs) {
    const secDiv = document.createElement('div');
    secDiv.style.cssText = 'padding:0 14px 12px;';

    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'sector-section-label';
    sectionLabel.style.cssText = 'padding:8px 0 4px;';
    sectionLabel.textContent = title;
    secDiv.appendChild(sectionLabel);

    const table = document.createElement('table');
    table.className = 'data-table';

    let hdr = '<thead><tr><th class="col-left" style="width:3%"></th>';
    hdr += '<th class="col-right" style="width:3%">#</th>';
    hdr += '<th class="col-left">Peer</th>';
    hdr += '<th class="col-left">Industry</th>';
    hdr += '<th class="col-left">Direction</th>';
    hdr += '<th class="col-right">Net Peer Flow</th>';
    hdr += `<th class="col-right">Contra ${d.subject.ticker}</th>`;
    hdr += '<th class="col-right"># Funds</th>';
    hdr += '</tr></thead>';
    table.innerHTML = hdr;

    const tbody = document.createElement('tbody');
    subs.forEach((s, idx) => {
        const tr = document.createElement('tr');
        tr.className = 'sector-flow-row';
        tr.style.cursor = 'pointer';
        tr.dataset.peer = s.ticker;

        const dirLabel = s.direction === 'replacing'
            ? `Replacing ${d.subject.ticker}` : `Replaced by ${d.subject.ticker}`;
        const dirColor = s.direction === 'replacing' ? '#c62828' : '#2e7d32';

        tr.innerHTML = `
            <td class="toggle-arrow-cell"><span class="toggle-arrow">\u25B6</span></td>
            <td class="col-right" style="color:#888;font-size:12px;">${idx + 1}</td>
            <td class="col-left"><strong>${s.ticker}</strong></td>
            <td class="col-left" style="font-size:12px;color:#666;">${s.industry || '\u2014'}</td>
            <td class="col-left" style="color:${dirColor};font-size:12px;">${dirLabel}</td>
            <td class="col-right">${_fmtFlow(s.net_peer_flow)}</td>
            <td class="col-right">${_fmtFlow(s.contra_subject_flow)}</td>
            <td class="col-right">${s.num_entities || 0}</td>
        `;
        tbody.appendChild(tr);

        tr.addEventListener('click', () => _togglePeerDetail(d.subject.ticker, s.ticker, tr, tbody));
    });

    table.appendChild(tbody);
    secDiv.appendChild(table);
    wrap.appendChild(secDiv);
}

async function _togglePeerDetail(ticker, peer, parentRow, tbody) {
    const existing = tbody.querySelectorAll(`.sector-detail-row[data-peer="${CSS.escape(peer)}"]`);
    if (existing.length) {
        existing.forEach(r => r.remove());
        parentRow.querySelector('.toggle-arrow').style.transform = 'rotate(0deg)';
        return;
    }
    // Collapse any other
    tbody.querySelectorAll('.sector-detail-row').forEach(r => r.remove());
    tbody.querySelectorAll('.toggle-arrow').forEach(a => a.style.transform = 'rotate(0deg)');
    parentRow.querySelector('.toggle-arrow').style.transform = 'rotate(90deg)';

    const loadRow = document.createElement('tr');
    loadRow.className = 'sector-detail-row';
    loadRow.dataset.peer = peer;
    const loadTd = document.createElement('td');
    loadTd.colSpan = 8;
    loadTd.innerHTML = '<div class="sector-detail-loading">Loading...</div>';
    loadRow.appendChild(loadTd);
    parentRow.after(loadRow);

    try {
        const url = `/api/peer_rotation_detail?ticker=${ticker}&peer=${peer}` +
            `&active_only=${_prActiveOnly ? 1 : 0}&level=${_prLevel}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        loadRow.remove();

        const fragment = document.createDocumentFragment();
        // Header row
        const hdrRow = document.createElement('tr');
        hdrRow.className = 'sector-detail-row sector-detail-sep';
        hdrRow.dataset.peer = peer;
        hdrRow.innerHTML = `<td></td><td colspan="7" class="col-left sector-section-label">Entity Detail: ${ticker} \u2194 ${peer}</td>`;
        fragment.appendChild(hdrRow);

        (data.entities || []).slice(0, 10).forEach(ent => {
            const tr = document.createElement('tr');
            tr.className = 'sector-detail-row';
            tr.dataset.peer = peer;
            tr.innerHTML = `
                <td></td><td></td>
                <td class="col-left sector-detail-label">${ent.entity}</td>
                <td></td><td></td>
                <td class="col-right">${_fmtFlow(ent.peer_flow)}</td>
                <td class="col-right">${_fmtFlow(ent.subject_flow)}</td>
                <td></td>
            `;
            fragment.appendChild(tr);
        });

        parentRow.after(fragment);
    } catch (e) {
        loadRow.querySelector('td').innerHTML = `<div class="sector-detail-error">Error: ${e.message}</div>`;
    }
}

// --- Section 5: Top 5 Sector Movers ---
function _prBuildMoversSection(wrap, d, pks) {
    const movers = d.top_sector_movers || [];
    if (!movers.length) return;

    const secDiv = document.createElement('div');
    secDiv.style.cssText = 'padding:0 14px 12px;';

    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'sector-section-label';
    sectionLabel.style.cssText = 'padding:8px 0 4px;';
    sectionLabel.textContent = `Top Movers \u2014 ${d.subject.sector}`;
    secDiv.appendChild(sectionLabel);

    const inner = document.createElement('div');
    inner.style.cssText = 'display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;';

    // Table
    const tblWrap = document.createElement('div');
    tblWrap.style.cssText = 'flex:1;min-width:300px;';
    const table = document.createElement('table');
    table.className = 'data-table';
    table.innerHTML = `<thead><tr>
        <th class="col-right">#</th>
        <th class="col-left">Ticker</th>
        <th class="col-left">Industry</th>
        <th class="col-right">Net Flow</th>
        <th class="col-right">Inflow</th>
        <th class="col-right">Outflow</th>
    </tr></thead>`;
    const tbody = document.createElement('tbody');
    movers.forEach(m => {
        const tr = document.createElement('tr');
        if (m.is_subject) tr.className = 'peer-highlight';
        tr.innerHTML = `
            <td class="col-right" style="color:#888;font-size:12px;">${m.is_subject ? '\u2605' : m.rank}</td>
            <td class="col-left"><strong>${m.ticker}</strong></td>
            <td class="col-left" style="font-size:12px;color:#666;">${m.industry || '\u2014'}</td>
            <td class="col-right ${_flowClass(m.net_flow)}">${_fmtFlow(m.net_flow)}</td>
            <td class="col-right">${_fmtFlow(m.inflow)}</td>
            <td class="col-right">${_fmtFlow(m.outflow)}</td>
        `;
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tblWrap.appendChild(table);
    inner.appendChild(tblWrap);

    // Horizontal bar chart
    const chartDiv = document.createElement('div');
    chartDiv.className = 'chart-card';
    chartDiv.style.cssText = 'flex:0 0 300px;height:220px;';
    const canvas = document.createElement('canvas');
    chartDiv.appendChild(canvas);
    inner.appendChild(chartDiv);

    secDiv.appendChild(inner);
    wrap.appendChild(secDiv);

    setTimeout(() => {
        const labels = movers.map(m => (m.is_subject ? '\u2605 ' : '') + m.ticker);
        const vals = movers.map(m => (m.net_flow || 0) / 1e6);
        const bgColors = movers.map(m => {
            if (m.is_subject) return '#1E2846';
            return (m.net_flow || 0) >= 0 ? '#2e7d32' : '#c62828';
        });

        const chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: vals,
                    backgroundColor: bgColors,
                    borderWidth: movers.map(m => m.is_subject ? 2 : 0),
                    borderColor: '#1E2846',
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => '$' + ctx.parsed.x.toFixed(0) + 'M' } },
                },
                scales: {
                    x: { ticks: { callback: v => '$' + v + 'M', font: { size: 10 } } },
                    y: { ticks: { font: { size: 11 } } },
                },
            }
        });
        _prCharts.push(chart);
    }, 100);
}

// --- Section 6: Entity Rotation Stories ---
function _prBuildEntityStories(wrap, d) {
    const stories = d.entity_stories || [];
    if (!stories.length) return;

    const secDiv = document.createElement('div');
    secDiv.style.cssText = 'padding:0 14px 12px;';

    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'sector-section-label';
    sectionLabel.style.cssText = 'padding:8px 0 4px;';
    sectionLabel.textContent = 'Top 10 Entity Rotation Stories';
    secDiv.appendChild(sectionLabel);

    const table = document.createElement('table');
    table.className = 'data-table';
    table.innerHTML = `<thead><tr>
        <th class="col-right">#</th>
        <th class="col-left">Entity</th>
        <th class="col-right">${d.subject.ticker} Flow</th>
        <th class="col-right">Sector Flow</th>
        <th class="col-left">Top Contra-Peers</th>
    </tr></thead>`;
    const tbody = document.createElement('tbody');
    stories.forEach((s, idx) => {
        const tr = document.createElement('tr');
        const contra = (s.top_contra_peers || []).map(p =>
            `<span class="${_flowClass(p.flow)}">${p.ticker} ${_fmtFlow(p.flow)}</span>`
        ).join(', ');
        tr.innerHTML = `
            <td class="col-right" style="color:#888;font-size:12px;">${idx + 1}</td>
            <td class="col-left">${s.entity}</td>
            <td class="col-right ${_flowClass(s.subject_flow)}">${_fmtFlow(s.subject_flow)}</td>
            <td class="col-right ${_flowClass(s.sector_flow)}">${_fmtFlow(s.sector_flow)}</td>
            <td class="col-left" style="font-size:12px;">${contra || '\u2014'}</td>
        `;
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    secDiv.appendChild(table);
    wrap.appendChild(secDiv);
}

// ---------------------------------------------------------------------------
// Ownership Trend tab (3 sub-views)
// ---------------------------------------------------------------------------
let _otSubView = 'summary';  // 'summary' | 'changes'
let _otLevel = 'parent';  // 'parent' | 'fund'
let _otActiveOnly = false;

async function loadOwnershipTrend() {
    clearError(); tableWrap.innerHTML = '';

    // Sub-view bar + level toggle
    const barWrap = document.createElement('div');
    barWrap.style.cssText = 'display:flex;align-items:center;gap:16px;flex-wrap:wrap;';

    const bar = document.createElement('div');
    bar.className = 'sub-view-bar';
    ['summary', 'changes'].forEach(v => {
        const btn = document.createElement('button');
        btn.className = 'co-view-btn' + (v === _otSubView ? ' active' : '');
        btn.textContent = v === 'summary' ? 'Quarterly Summary & Cohort' : 'Holder Momentum';
        btn.addEventListener('click', () => { _otSubView = v; loadOwnershipTrend(); });
        bar.appendChild(btn);
    });
    barWrap.appendChild(bar);

    // Level toggle (By Parent / By Fund)
    const lvlToggle = document.createElement('div');
    lvlToggle.className = 'register-view-toggle';
    [['parent', 'By Parent'], ['fund', 'By Fund']].forEach(([v, txt]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-toggle' + (_otLevel === v ? ' active' : '');
        btn.textContent = txt;
        btn.onclick = () => { _otLevel = v; loadOwnershipTrend(); };
        lvlToggle.appendChild(btn);
    });
    barWrap.appendChild(lvlToggle);

    if (_otLevel === 'fund') {
        const aoBtn = document.createElement('button');
        aoBtn.className = 'btn btn-toggle' + (_otActiveOnly ? ' active' : '');
        aoBtn.textContent = 'Active Only';
        aoBtn.onclick = () => { _otActiveOnly = !_otActiveOnly; loadOwnershipTrend(); };
        barWrap.appendChild(aoBtn);
    }

    tableWrap.appendChild(barWrap);

    if (_otSubView === 'summary') {
        await loadOTSummary();
        // Also load cohort inline below summary
        await loadOTCohort();
    } else {
        // Holder Momentum — full year share history
        showSpinner();
        try {
            const ao = _otActiveOnly && _otLevel === 'fund' ? '&active_only=true' : '';
            const res = await fetch(`/api/holder_momentum?ticker=${currentTicker}&level=${_otLevel}${ao}`);
            if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
            const data = await res.json();
            hideSpinner();
            currentData = data;
            _renderMomentum(data);
        } catch (e) { hideSpinner(); showError(e.message); }
    }
}

async function loadOTSummary() {
    showSpinner();
    try {
        const ao = _otActiveOnly && _otLevel === 'fund' ? '&active_only=true' : '';
        const res = await fetch(`/api/ownership_trend_summary?ticker=${currentTicker}&level=${_otLevel}${ao}`);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        renderOTSummary(data);
    } catch (e) { hideSpinner(); showError(e.message); }
}

function renderOTSummary(data) {
    const {quarters} = data;

    // Build custom table with stacked bar for Active/Passive
    const table = document.createElement('table');
    table.className = 'data-table';
    table.style.tableLayout = 'fixed';

    const colgroup = document.createElement('colgroup');
    // Quarter, Holders, +/-, Inst Shares, Inst Value, % Float, Active/Passive, QoQ Change, Signal
    ['8%', '8%', '6%', '13%', '13%', '8%', '22%', '14%', '5%'].forEach(w => {
        const cg = document.createElement('col');
        cg.style.width = w;
        colgroup.appendChild(cg);
    });
    table.appendChild(colgroup);

    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    [
        ['Quarter', 'left'], ['Holders', 'right'], ['+/\u2212', 'right'],
        ['Inst Shares', 'right'], ['Inst Value', 'right'], ['% Float', 'right'],
        ['Active / Passive', 'center'], ['QoQ Share \u0394', 'right'], ['', 'center']
    ].forEach(([h, align]) => {
        const th = document.createElement('th');
        th.textContent = h;
        th.style.textAlign = align;
        hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    quarters.forEach(row => {
        const tr = document.createElement('tr');

        // Quarter
        const tdQ = document.createElement('td');
        tdQ.textContent = row.quarter || '';
        tr.appendChild(tdQ);

        // Holders
        const tdH = document.createElement('td');
        tdH.style.textAlign = 'right';
        tdH.textContent = row.holder_count != null ? fmtNum(row.holder_count) : '\u2014';
        tr.appendChild(tdH);

        // +/- holders
        const tdHC = document.createElement('td');
        tdHC.style.textAlign = 'right';
        tdHC.style.fontSize = '11px';
        if (row.net_holder_change != null) {
            const v = row.net_holder_change;
            tdHC.textContent = (v > 0 ? '+' : '') + v;
            tdHC.style.color = v > 0 ? '#27AE60' : v < 0 ? '#C0392B' : '#999';
        } else {
            tdHC.textContent = '\u2014';
            tdHC.style.color = '#999';
        }
        tr.appendChild(tdHC);

        // Inst Shares
        const tdS = document.createElement('td');
        tdS.style.textAlign = 'right';
        tdS.textContent = fmtShares(row.total_inst_shares);
        tr.appendChild(tdS);

        // Inst Value
        const tdV = document.createElement('td');
        tdV.style.textAlign = 'right';
        tdV.textContent = fmtDollars(row.total_inst_value);
        tr.appendChild(tdV);

        // % Float
        const tdF = document.createElement('td');
        tdF.style.textAlign = 'right';
        tdF.textContent = row.pct_float != null ? row.pct_float + '%' : '\u2014';
        tr.appendChild(tdF);

        // Active/Passive stacked bar
        const tdBar = document.createElement('td');
        const aPct = row.active_pct || 0;
        const pPct = row.passive_pct || 0;
        const oPct = Math.max(0, 100 - aPct - pPct);  // other/unknown
        const barWrap = document.createElement('div');
        barWrap.className = 'ap-bar-wrap';
        barWrap.title = `Active ${aPct}% / Passive ${pPct}% / Other ${oPct.toFixed(1)}%`;
        const barA = document.createElement('div');
        barA.className = 'ap-bar ap-active';
        barA.style.width = aPct + '%';
        const barP = document.createElement('div');
        barP.className = 'ap-bar ap-passive';
        barP.style.width = pPct + '%';
        barWrap.appendChild(barA);
        barWrap.appendChild(barP);
        // Labels inside if wide enough
        if (aPct > 12) { const lbl = document.createElement('span'); lbl.className = 'ap-label'; lbl.textContent = Math.round(aPct) + '%'; barA.appendChild(lbl); }
        if (pPct > 12) { const lbl = document.createElement('span'); lbl.className = 'ap-label'; lbl.textContent = Math.round(pPct) + '%'; barP.appendChild(lbl); }
        tdBar.appendChild(barWrap);
        tr.appendChild(tdBar);

        // QoQ Share Change (use plain format to avoid HTML-in-textContent)
        const tdC = document.createElement('td');
        tdC.style.textAlign = 'right';
        if (row.net_shares_change != null) {
            const nsc = row.net_shares_change;
            const abs = Math.abs(nsc);
            let txt;
            if (abs >= 1e9) txt = (abs / 1e9).toFixed(1) + 'B';
            else if (abs >= 1e6) txt = (abs / 1e6).toFixed(1) + 'M';
            else if (abs >= 1e3) txt = (abs / 1e3).toFixed(1) + 'K';
            else txt = abs.toLocaleString('en-US', {maximumFractionDigits: 0});
            tdC.textContent = (nsc >= 0 ? '+' : '\u2212') + txt;
            tdC.style.color = nsc > 0 ? '#27AE60' : nsc < 0 ? '#C0392B' : '';
        } else {
            tdC.textContent = '\u2014';
        }
        tr.appendChild(tdC);

        // Signal arrow
        const tdSig = document.createElement('td');
        tdSig.style.textAlign = 'center';
        tdSig.style.fontSize = '14px';
        if (row.signal) {
            tdSig.textContent = row.signal;
            tdSig.style.color = row.signal === '\u2191' ? '#27AE60' : row.signal === '\u2193' ? '#C0392B' : '#999';
        }
        tr.appendChild(tdSig);

        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    currentData = quarters;
}

let _cohortPeriod = null;  // null = most recent quarter (default)
let _cohortLevel = 'parent';  // 'parent' | 'fund'
let _cohortActiveOnly = false;

async function loadOTCohort() {
    try {
        const fromQ = _cohortPeriod || '';
        const lvl = _cohortLevel;
        const ao = _cohortActiveOnly && lvl === 'fund' ? '&active_only=true' : '';
        const res = await fetch(`/api/cohort_analysis?ticker=${currentTicker}&from=${fromQ}&level=${lvl}${ao}`);
        if (!res.ok) return;
        const data = await res.json();
        tableWrap.querySelectorAll('.cohort-section').forEach(el => el.remove());
        const wrap = document.createElement('div');
        wrap.className = 'cohort-section';
        renderCohort(data, wrap);
        tableWrap.appendChild(wrap);
    } catch (e) { /* cohort is optional enhancement */ }
}

function _fmtQ(q) {
    if (!q || q.length < 6) return q || '';
    return 'Q' + q.slice(5) + ' ' + q.slice(0, 4);
}

function renderCohort(data, container) {
    const {summary, detail} = data;
    const fq = summary.from_quarter || '';
    const lq = summary.to_quarter || '';
    const lvl = summary.level || 'parent';

    // Control bar: period selector + level toggle + active-only
    const selBar = document.createElement('div');
    selBar.style.cssText = 'display:flex;align-items:center;gap:10px;margin:20px 0 8px 0;flex-wrap:wrap;';

    const label = document.createElement('span');
    label.style.cssText = 'font-size:14px;font-weight:700;color:#002147;';
    label.textContent = `Cohort: ${_fmtQ(fq)} \u2192 ${_fmtQ(lq)}`;
    selBar.appendChild(label);

    // Level toggle (By Parent / By Fund)
    const lvlToggle = document.createElement('div');
    lvlToggle.className = 'register-view-toggle';
    lvlToggle.style.marginLeft = '12px';
    [['parent', 'By Parent'], ['fund', 'By Fund']].forEach(([v, txt]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-toggle' + (lvl === v ? ' active' : '');
        btn.textContent = txt;
        btn.onclick = () => { _cohortLevel = v; loadOTCohort(); };
        lvlToggle.appendChild(btn);
    });
    selBar.appendChild(lvlToggle);

    // Active Only toggle (fund level only)
    if (lvl === 'fund') {
        const aoBtn = document.createElement('button');
        aoBtn.className = 'btn btn-toggle' + (_cohortActiveOnly ? ' active' : '');
        aoBtn.textContent = 'Active Only';
        aoBtn.style.marginLeft = '6px';
        aoBtn.onclick = () => { _cohortActiveOnly = !_cohortActiveOnly; loadOTCohort(); };
        selBar.appendChild(aoBtn);
    }

    const spacer = document.createElement('span');
    spacer.style.flex = '1';
    selBar.appendChild(spacer);

    // Period selector
    const periods = [
        ['2025Q1', 'Q1 \u2192 Q4'],
        ['2025Q2', 'Q2 \u2192 Q4'],
        ['2025Q3', 'Q3 \u2192 Q4'],
    ];
    const btnGroup = document.createElement('div');
    btnGroup.className = 'register-view-toggle';
    periods.forEach(([q, txt]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-toggle' + (fq === q ? ' active' : '');
        btn.textContent = txt;
        btn.onclick = () => { _cohortPeriod = q; loadOTCohort(); };
        btnGroup.appendChild(btn);
    });
    selBar.appendChild(btnGroup);
    container.appendChild(selBar);

    // Economic retention trend (active investors, last 3 QoQ)
    const ert = summary.econ_retention_trend || [];
    if (ert.length > 0) {
        const retLine = document.createElement('div');
        retLine.style.cssText = 'font-size:14px;color:#333;margin:8px 0 14px 0;display:flex;align-items:center;gap:20px;padding:8px 12px;background:#f8f9fa;border-radius:6px;border:1px solid #e5e7eb;';
        const retLabel = document.createElement('span');
        retLabel.style.cssText = 'font-weight:700;color:#002147;white-space:nowrap;';
        retLabel.textContent = 'Active Share Retention';
        retLine.appendChild(retLabel);
        ert.forEach(p => {
            const s = document.createElement('span');
            const pct = p.econ_retention;
            const color = pct >= 95 ? '#27AE60' : pct >= 85 ? '#F39C12' : '#C0392B';
            s.innerHTML = `<span style="color:#777">${_fmtQ(p.from)} \u2192 ${_fmtQ(p.to)}</span> `
                + `<strong style="color:${color};font-size:16px">${pct}%</strong>`
                + `<span style="color:#aaa;font-size:12px;margin-left:3px">(${p.active_holders_from}\u2192${p.active_holders_to})</span>`;
            retLine.appendChild(s);
        });
        container.appendChild(retLine);
    }

    // Detail table
    const table = document.createElement('table');
    table.className = 'data-table';
    table.style.tableLayout = 'fixed';

    const colgroup = document.createElement('colgroup');
    // Category, Holders, Shares(Q4), Value(Q4), Δ Shares, Δ Value, Avg Pos, % Inst Float
    [null, '7%', '12%', '12%', '12%', '12%', '11%', '9%'].forEach(w => {
        const cg = document.createElement('col');
        if (w) cg.style.width = w;
        colgroup.appendChild(cg);
    });
    table.appendChild(colgroup);

    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    const holderLabel = lvl === 'fund' ? 'Funds' : 'Holders';
    ['Category', holderLabel, 'Shares', 'Value', '\u0394 Shares', '\u0394 Value', 'Avg Position', '% Inst Float'].forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        th.style.textAlign = h === 'Category' ? 'left' : 'right';
        hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    /** Build a single cohort table row. */
    function _buildRow(row, indent) {
        const tr = document.createElement('tr');
        if (row.is_parent) tr.style.fontWeight = '700';
        if (row.is_total) {
            tr.style.fontWeight = '700';
            tr.style.borderTop = '3px solid #002147';
            tr.style.background = '#f0f4f8';
        }

        // Category cell
        const tdCat = document.createElement('td');
        tdCat.style.paddingLeft = indent + 'px';
        if (row.has_children && row.level !== 0) {
            // Collapsible subcategory (Increased, Decreased, etc.)
            const arrow = document.createElement('span');
            arrow.className = 'toggle-arrow';
            arrow.textContent = '\u25B6';  // ▶
            arrow.style.cssText = 'margin-right:4px;font-size:10px;cursor:pointer;';
            tdCat.appendChild(arrow);
            tdCat.appendChild(document.createTextNode(row.category));
            tdCat.style.cursor = 'pointer';
        } else if (row.has_children && row.level === 0) {
            // New Entries / Exits (top-level collapsible)
            const arrow = document.createElement('span');
            arrow.className = 'toggle-arrow';
            arrow.textContent = '\u25B6';
            arrow.style.cssText = 'margin-right:4px;font-size:10px;cursor:pointer;';
            tdCat.appendChild(arrow);
            tdCat.appendChild(document.createTextNode(row.category));
            tdCat.style.cursor = 'pointer';
        } else {
            tdCat.textContent = row.category;
        }
        tr.appendChild(tdCat);

        // Holders
        const tdH = document.createElement('td');
        tdH.style.textAlign = 'right';
        tdH.textContent = row.level === 2 ? '' : (row.holders != null ? row.holders.toLocaleString() : '\u2014');
        tr.appendChild(tdH);

        // Shares
        const tdS = document.createElement('td');
        tdS.style.textAlign = 'right';
        tdS.innerHTML = fmtShares(row.shares);
        tr.appendChild(tdS);

        // Value
        const tdV = document.createElement('td');
        tdV.style.textAlign = 'right';
        tdV.innerHTML = fmtDollars(row.value);
        tr.appendChild(tdV);

        // Δ Shares (positive = +prefix, negative = red parentheses via _negWrap)
        const tdDS = document.createElement('td');
        tdDS.style.textAlign = 'right';
        if (row.delta_shares && row.delta_shares !== 0) {
            if (row.delta_shares > 0) tdDS.innerHTML = '+' + fmtShares(row.delta_shares);
            else tdDS.innerHTML = fmtShares(row.delta_shares);
        } else { tdDS.textContent = '\u2014'; tdDS.style.color = '#999'; }
        tr.appendChild(tdDS);

        // Δ Value
        const tdDV = document.createElement('td');
        tdDV.style.textAlign = 'right';
        if (row.delta_value && row.delta_value !== 0) {
            if (row.delta_value > 0) tdDV.innerHTML = '+' + fmtDollars(row.delta_value);
            else tdDV.innerHTML = fmtDollars(row.delta_value);
        } else { tdDV.textContent = '\u2014'; tdDV.style.color = '#999'; }
        tr.appendChild(tdDV);

        // Avg Position
        const tdAvg = document.createElement('td');
        tdAvg.style.textAlign = 'right';
        tdAvg.innerHTML = fmtDollars(row.avg_position);
        tr.appendChild(tdAvg);

        // % Inst Float
        const tdPct = document.createElement('td');
        tdPct.style.textAlign = 'right';
        tdPct.textContent = row.pct_float_moved != null ? (row.pct_float_moved < 0.1 && row.pct_float_moved > 0 ? '<0.1%' : row.pct_float_moved.toFixed(1) + '%') : '\u2014';
        tr.appendChild(tdPct);

        return tr;
    }

    const tbody = document.createElement('tbody');
    let cohortIdx = 0;
    detail.forEach(row => {
        const indent = row.level === 1 ? 28 : row.level === 2 ? 52 : 0;
        const tr = _buildRow(row, indent);

        // Entity-level children: hidden by default, toggled on click
        const children = row.children || [];
        const hasKids = row.has_children && children.length > 0;
        if (hasKids) {
            const cid = 'cohort-g' + (cohortIdx++);
            tr.dataset.cohortGroup = cid;
        }
        tbody.appendChild(tr);

        if (hasKids) {
            const gid = tr.dataset.cohortGroup;
            const childRows = [];
            children.forEach(child => {
                const childIndent = row.level === 1 ? 52 : 28;
                const ctr = _buildRow(child, childIndent);
                ctr.dataset.cohortChildOf = gid;
                ctr.style.display = 'none';
                ctr.style.fontSize = '11px';
                ctr.style.color = '#555';
                childRows.push(ctr);
                tbody.appendChild(ctr);
            });
            // Click handler on category row
            tr.addEventListener('click', () => {
                const expanded = childRows[0] && childRows[0].style.display !== 'none';
                const arrow = tr.querySelector('.toggle-arrow');
                childRows.forEach(cr => { cr.style.display = expanded ? 'none' : ''; });
                if (arrow) arrow.textContent = expanded ? '\u25B6' : '\u25BC';
            });
        }
    });
    table.appendChild(tbody);
    container.appendChild(table);

    // Top 10 summary line
    const t10 = summary.top10;
    if (t10) {
        const t10Line = document.createElement('div');
        t10Line.style.cssText = 'font-size:12px;color:#666;margin:8px 0 0 0;';
        const parts = [];
        const label10 = lvl === 'fund' ? 'Top 10 funds' : 'Top 10 holders';
        if (t10.increased) parts.push(`${t10.increased} increasing`);
        if (t10.decreased) parts.push(`${t10.decreased} decreasing`);
        if (t10.new) parts.push(`${t10.new} new`);
        if (t10.unchanged) parts.push(`${t10.unchanged} unchanged`);
        t10Line.innerHTML = `<strong>${label10}:</strong> ${parts.join(', ')}`;
        container.appendChild(t10Line);
    }
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

function _renderMomentum(data) {
    if (!data || !data.length) { tableWrap.appendChild(sectionHeader('No momentum data')); return; }

    // Detect quarter columns from first row
    const qs = Object.keys(data[0]).filter(k => /^\d{4}Q\d$/.test(k)).sort();

    const table = document.createElement('table');
    table.className = 'data-table';
    table.style.tableLayout = 'fixed';

    // Colgroup: #, Institution, Q1..Q4, Change, Chg%
    const colgroup = document.createElement('colgroup');
    const numCols = 3 + qs.length + 2; // #, institution, type, quarters, change, chg%
    [
        '3%',  // #
        null,  // institution (flex)
        '7%',  // type
    ].concat(qs.map(() => Math.floor(48 / qs.length) + '%'))
     .concat(['11%', '7%'])  // change, chg%
     .forEach(w => {
        const cg = document.createElement('col');
        if (w) cg.style.width = w;
        colgroup.appendChild(cg);
    });
    table.appendChild(colgroup);

    // Header
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    hr.style.position = 'sticky';
    hr.style.top = '0';
    hr.style.zIndex = '10';
    [['#', 'right'], ['Institution', 'left'], ['Type', 'center']]
        .concat(qs.map(q => [_fmtQ(q), 'right']))
        .concat([['Change', 'right'], ['Chg%', 'right']])
        .forEach(([h, align]) => {
            const th = document.createElement('th');
            th.textContent = h;
            th.style.textAlign = align;
            hr.appendChild(th);
        });
    thead.appendChild(hr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    let parentIdx = 0;
    data.forEach(row => {
        const tr = document.createElement('tr');
        const isParent = row.is_parent || false;
        const isChild = row.level === 1;
        if (isParent || (!isChild && row.level === 0)) tr.style.fontWeight = isParent ? '700' : '500';
        if (isChild) {
            tr.style.fontSize = '11px';
            tr.style.color = '#555';
        }

        // #
        const tdNum = document.createElement('td');
        tdNum.className = 'col-rownum';
        if (!isChild && row.rank) { tdNum.textContent = row.rank; tdNum.style.fontWeight = '700'; }
        tr.appendChild(tdNum);

        // Institution
        const tdName = document.createElement('td');
        tdName.classList.add('col-text-overflow');
        if (isChild) {
            tdName.style.paddingLeft = '24px';
            tdName.textContent = row.institution || '';
        } else if (isParent) {
            tdName.appendChild(document.createTextNode((row.institution || '') + ' '));
            const arrow = document.createElement('span');
            arrow.className = 'toggle-arrow';
            arrow.textContent = '\u25B6';
            tdName.appendChild(arrow);
            tdName.style.cursor = 'pointer';
        } else {
            tdName.textContent = row.institution || '';
        }
        tdName.title = row.institution || '';
        tr.appendChild(tdName);

        // Type
        const tdType = document.createElement('td');
        tdType.style.textAlign = 'center';
        tdType.textContent = (!isChild && row.type && row.type !== 'unknown') ? row.type : '';
        tr.appendChild(tdType);

        // Quarter shares
        qs.forEach(q => {
            const td = document.createElement('td');
            td.style.textAlign = 'right';
            td.innerHTML = row[q] != null ? fmtShares(row[q]) : '\u2014';
            if (row[q] == null) td.style.color = '#ccc';
            tr.appendChild(td);
        });

        // Change
        const tdChg = document.createElement('td');
        tdChg.style.textAlign = 'right';
        if (row.change != null && row.change !== 0) {
            if (row.change > 0) tdChg.innerHTML = '+' + fmtShares(row.change);
            else tdChg.innerHTML = fmtShares(row.change);
        } else { tdChg.textContent = '\u2014'; }
        tr.appendChild(tdChg);

        // Chg%
        const tdPct = document.createElement('td');
        tdPct.style.textAlign = 'right';
        if (row.change_pct != null) {
            const v = row.change_pct;
            if (v > 0) tdPct.textContent = '+' + v.toFixed(1) + '%';
            else if (v < 0) { tdPct.innerHTML = '<span class="negative">(' + Math.abs(v).toFixed(1) + '%)</span>'; }
            else tdPct.textContent = '0.0%';
        } else { tdPct.textContent = '\u2014'; }
        tr.appendChild(tdPct);

        // Collapsible setup
        if (isParent) {
            parentIdx++;
            tr.dataset.parentId = 'mp' + parentIdx;
            tr.classList.add('collapsible-parent');
        } else if (isChild) {
            tr.dataset.childOf = 'mp' + parentIdx;
            tr.classList.add('child-row');
        }

        tbody.appendChild(tr);
    });
    // Totals row (parent-level only, no double-counting)
    const parentRows = data.filter(r => r.level === 0);
    const totalsRow = document.createElement('tr');
    totalsRow.style.cssText = 'font-weight:700;border-top:3px solid #002147;background:#f0f4f8;';
    // #
    totalsRow.appendChild(document.createElement('td'));
    // Institution
    const tdTotLabel = document.createElement('td');
    tdTotLabel.textContent = `TOTAL (${parentRows.length} holders)`;
    totalsRow.appendChild(tdTotLabel);
    // Type
    totalsRow.appendChild(document.createElement('td'));
    // Quarter columns
    qs.forEach(q => {
        const td = document.createElement('td');
        td.style.textAlign = 'right';
        const sum = parentRows.reduce((acc, r) => acc + (r[q] || 0), 0);
        td.innerHTML = fmtShares(sum);
        totalsRow.appendChild(td);
    });
    // Change
    const totalChg = parentRows.reduce((acc, r) => acc + (r.change || 0), 0);
    const tdTotChg = document.createElement('td');
    tdTotChg.style.textAlign = 'right';
    if (totalChg > 0) tdTotChg.innerHTML = '+' + fmtShares(totalChg);
    else tdTotChg.innerHTML = fmtShares(totalChg);
    totalsRow.appendChild(tdTotChg);
    // Chg%
    const firstQSum = parentRows.reduce((acc, r) => acc + (r[qs[0]] || 0), 0);
    const tdTotPct = document.createElement('td');
    tdTotPct.style.textAlign = 'right';
    if (firstQSum > 0) {
        const pct = totalChg / firstQSum * 100;
        if (pct > 0) tdTotPct.textContent = '+' + pct.toFixed(1) + '%';
        else if (pct < 0) tdTotPct.innerHTML = '<span class="negative">(' + Math.abs(pct).toFixed(1) + '%)</span>';
        else tdTotPct.textContent = '0.0%';
    }
    totalsRow.appendChild(tdTotPct);
    tbody.appendChild(totalsRow);

    table.appendChild(tbody);
    tableWrap.appendChild(table);

    // Click handlers for collapsible parents (toggle .visible class, not display)
    tbody.querySelectorAll('.collapsible-parent').forEach(parentTr => {
        parentTr.addEventListener('click', () => {
            const pid = parentTr.dataset.parentId;
            const arrow = parentTr.querySelector('.toggle-arrow');
            const children = tbody.querySelectorAll(`tr[data-child-of="${pid}"]`);
            const isExpanded = children[0] && children[0].classList.contains('visible');
            children.forEach(c => { c.classList.toggle('visible', !isExpanded); });
            if (arrow) arrow.textContent = isExpanded ? '\u25B6' : '\u25BC';
        });
    });
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
    if (type === 'nport_badge') return fmtNportBadge(val);
    const s = String(val);
    return s.length > 120 ? s.slice(0, 120) + '…' : s;
}

function _isNumericCol(type) {
    return type === 'num' || type === 'dollar' || type === 'pct' || type === 'shares';
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
            td.innerHTML = _formatCellValue(row[c.key], c.type);
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

let _flowPeriod = '1Q';
let _flowLevel = 'parent';
let _flowActiveOnly = false;
let _flowTab = 'buyers';

async function loadFlowAnalysis() {
    clearError(); tableWrap.innerHTML = '';

    // Control bar: period + level toggle + active only
    const cbar = document.createElement('div');
    cbar.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 0;flex-wrap:wrap;';

    // Period selector
    const pLabel = document.createElement('span');
    pLabel.style.cssText = 'font-size:12px;color:#666;';
    pLabel.textContent = 'Period:';
    cbar.appendChild(pLabel);
    const pGroup = document.createElement('div');
    pGroup.className = 'register-view-toggle';
    [['1Q', 'Q3 \u2192 Q4'], ['2Q', 'Q2 \u2192 Q4'], ['4Q', 'Q1 \u2192 Q4']].forEach(([p, lbl]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-toggle' + (p === _flowPeriod ? ' active' : '');
        btn.textContent = lbl;
        btn.onclick = () => { _flowPeriod = p; loadFlowAnalysis(); };
        pGroup.appendChild(btn);
    });
    cbar.appendChild(pGroup);

    // Level toggle
    const lvlGroup = document.createElement('div');
    lvlGroup.className = 'register-view-toggle';
    lvlGroup.style.marginLeft = '12px';
    [['parent', 'By Parent'], ['fund', 'By Fund']].forEach(([v, txt]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-toggle' + (_flowLevel === v ? ' active' : '');
        btn.textContent = txt;
        btn.onclick = () => { _flowLevel = v; loadFlowAnalysis(); };
        lvlGroup.appendChild(btn);
    });
    cbar.appendChild(lvlGroup);

    // Active Only (fund level)
    if (_flowLevel === 'fund') {
        const aoBtn = document.createElement('button');
        aoBtn.className = 'btn btn-toggle' + (_flowActiveOnly ? ' active' : '');
        aoBtn.textContent = 'Active Only';
        aoBtn.style.marginLeft = '6px';
        aoBtn.onclick = () => { _flowActiveOnly = !_flowActiveOnly; loadFlowAnalysis(); };
        cbar.appendChild(aoBtn);
    }

    tableWrap.appendChild(cbar);

    showSpinner();
    const peers = getCOTickers().filter(t => t !== currentTicker).join(',');
    const ao = _flowActiveOnly && _flowLevel === 'fund' ? '&active_only=true' : '';
    const url = `/api/flow_analysis?ticker=${currentTicker}&period=${_flowPeriod}&peers=${peers}&level=${_flowLevel}${ao}`;
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Error');
        const data = await res.json();
        hideSpinner();
        const savedBar = tableWrap.querySelector('div');
        renderFlowAnalysis(data);
        if (savedBar && !tableWrap.contains(savedBar)) tableWrap.insertBefore(savedBar, tableWrap.firstChild);
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

    // --- All 4 charts in one row, pairs grouped with divider ---
    const qoq = data.qoq_charts || [];
    if (qoq.length > 0 && typeof Chart !== 'undefined') {
        const labels = qoq.map(d => d.label);
        function _barColors(vals) { return vals.map(v => v >= 0 ? '#27AE60' : '#C0392B'); }

        function _chartCard(title) {
            const card = document.createElement('div');
            card.style.cssText = 'flex:1;min-width:0;';
            const h = document.createElement('div');
            h.style.cssText = 'font-size:12px;font-weight:600;color:#002147;text-align:center;margin-bottom:2px;';
            h.textContent = title;
            card.appendChild(h);
            const wrap = document.createElement('div');
            wrap.style.cssText = 'position:relative;height:130px;';
            const canvas = document.createElement('canvas');
            wrap.appendChild(canvas);
            card.appendChild(wrap);
            return {card, canvas};
        }

        // Section labels above chart row
        const labelRow = document.createElement('div');
        labelRow.style.cssText = 'display:flex;gap:0;padding:8px 0 2px 0;';
        const fiLabel = document.createElement('div');
        fiLabel.style.cssText = 'flex:1;text-align:center;';
        fiLabel.innerHTML = '<span style="font-size:12px;font-weight:700;color:#002147;">Flow Intensity</span>'
            + '<br><span style="font-size:10px;color:#888;">Net $ change as % of mkt cap</span>';
        const chLabel = document.createElement('div');
        chLabel.style.cssText = 'flex:1;text-align:center;';
        chLabel.innerHTML = '<span style="font-size:12px;font-weight:700;color:#002147;">Holder Churn</span>'
            + '<br><span style="font-size:10px;color:#888;">Turnover as % of avg inst value</span>';
        labelRow.appendChild(fiLabel);
        labelRow.appendChild(chLabel);
        tableWrap.appendChild(labelRow);

        // Single row: [FI Total] [FI Active] | [Churn NP] [Churn Active]
        const chartRow = document.createElement('div');
        chartRow.style.cssText = 'display:flex;gap:6px;align-items:stretch;padding:0 0 4px 0;';

        const fi1 = _chartCard('Total');
        const fi2 = _chartCard('Active Only');
        chartRow.appendChild(fi1.card);
        chartRow.appendChild(fi2.card);

        // Divider between pairs
        const divider = document.createElement('div');
        divider.style.cssText = 'width:2px;background:#ddd;margin:0 6px;flex-shrink:0;';
        chartRow.appendChild(divider);

        const ch1 = _chartCard('Non-Passive');
        const ch2 = _chartCard('Active Only');
        chartRow.appendChild(ch1.card);
        chartRow.appendChild(ch2.card);

        tableWrap.appendChild(chartRow);

        // Footnote
        const fn = document.createElement('div');
        fn.style.cssText = 'font-size:10px;color:#aaa;padding:2px 0 12px 0;font-style:italic;';
        fn.textContent = 'Based on net 13F position changes per quarter. Active Only excludes index and passive managers.';
        tableWrap.appendChild(fn);

        // Render charts
        setTimeout(() => {
            ['_fiChart1','_fiChart2','_chChart1','_chChart2'].forEach(k => {
                if (window[k]) { window[k].destroy(); window[k] = null; }
            });

            const fiTotalVals = qoq.map(d => (d.flow_intensity_total || 0) * 100);
            const fiActiveVals = qoq.map(d => (d.flow_intensity_active || 0) * 100);
            const allFi = fiTotalVals.concat(fiActiveVals);
            const fiMin = Math.min(0, ...allFi);
            const fiMax = Math.max(0, ...allFi);
            const fiPad = (fiMax - fiMin) * 0.15 || 1;
            const fiScale = { min: fiMin - fiPad, max: fiMax + fiPad };

            const chNpVals = qoq.map(d => (d.churn_nonpassive || 0) * 100);
            const chActVals = qoq.map(d => (d.churn_active || 0) * 100);
            const allCh = chNpVals.concat(chActVals);
            const chMax = Math.max(0, ...allCh);
            const chPad = chMax * 0.15 || 1;
            const chScale = { min: 0, max: chMax + chPad };

            function _makeBarChart(canvas, vals, yLabel, scale) {
                return new Chart(canvas, {
                    type: 'bar',
                    data: {
                        labels,
                        datasets: [{
                            data: vals,
                            backgroundColor: _barColors(vals),
                            borderRadius: 2,
                            barPercentage: 0.4,
                            categoryPercentage: 0.5,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(2) + '%' } },
                        },
                        scales: {
                            x: { ticks: { font: { size: 12 } }, grid: { display: false } },
                            y: {
                                min: scale.min, max: scale.max,
                                ticks: { font: { size: 11 }, callback: v => v.toFixed(1) + '%', maxTicksLimit: 5 },
                                grid: { color: '#f0f0f0' },
                            },
                        },
                    },
                });
            }
            window._fiChart1 = _makeBarChart(fi1.canvas, fiTotalVals, '% Mkt Cap', fiScale);
            window._fiChart2 = _makeBarChart(fi2.canvas, fiActiveVals, '% Mkt Cap', fiScale);
            window._chChart1 = _makeBarChart(ch1.canvas, chNpVals, 'Churn %', chScale);
            window._chChart2 = _makeBarChart(ch2.canvas, chActVals, 'Churn %', chScale);
        }, 100);
    }

    // --- Tabbed view with unified columns ---
    const nameLabel = (data.level === 'fund') ? 'Fund' : 'Institution';
    // Same columns for all tabs — data just has nulls where not applicable
    const unifiedCols = [
        {key: 'inst_parent_name', label: nameLabel, type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'net_shares', label: 'Net Shares', type: 'shares'},
        {key: 'from_shares', label: 'From', type: 'shares'},
        {key: 'to_shares', label: 'To', type: 'shares'},
        {key: 'pct_change', label: '% Chg', type: 'pct'},
        {key: 'pct_float', label: '% Float', type: 'pct'},
        {key: 'net_value', label: 'Net $', type: 'dollar'},
    ];

    const tabDefs = [
        {id: 'buyers', label: '\u25B2 Buyers', rows: data.buyers || [], color: '#F0FBF4'},
        {id: 'sellers', label: '\u25BC Sellers', rows: data.sellers || [], color: '#FDF0F0'},
        {id: 'new', label: '\u2605 New', rows: data.new_entries || [], color: '#EBF3FB'},
        {id: 'exits', label: '\u2715 Exits', rows: data.exits || [], color: '#FFF8EB'},
    ];

    // Tab bar
    const tabBar = document.createElement('div');
    tabBar.style.cssText = 'display:flex;gap:2px;border-bottom:2px solid #002147;margin:16px 0 0 0;';
    const tableArea = document.createElement('div');

    function _renderFlowTab(tabId) {
        _flowTab = tabId;
        tabBar.querySelectorAll('button').forEach(b => {
            b.classList.toggle('active', b.dataset.tabId === tabId);
        });
        tableArea.innerHTML = '';
        const tab = tabDefs.find(t => t.id === tabId);
        if (!tab || !tab.rows.length) {
            tableArea.innerHTML = '<div style="padding:16px;color:#999;">No data for this category.</div>';
            return;
        }

        // Build table with unified columns
        const table = document.createElement('table');
        table.className = 'data-table';
        table.style.tableLayout = 'fixed';
        // Colgroup: #, name, type, net shares, from, to, %chg, %float, net$
        const colgroup = document.createElement('colgroup');
        ['3%', null, '7%', '11%', '10%', '10%', '7%', '7%', '11%'].forEach(w => {
            const cg = document.createElement('col');
            if (w) cg.style.width = w;
            colgroup.appendChild(cg);
        });
        table.appendChild(colgroup);

        const thead = document.createElement('thead');
        const hr = document.createElement('tr');
        const thNum = document.createElement('th');
        thNum.textContent = '#';
        thNum.style.textAlign = 'right';
        hr.appendChild(thNum);
        unifiedCols.forEach(c => {
            const th = document.createElement('th');
            th.textContent = c.label;
            th.style.textAlign = (c.type === 'text') ? 'left' : 'right';
            hr.appendChild(th);
        });
        thead.appendChild(hr);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        const evenColor = tab.color;
        tab.rows.forEach((row, idx) => {
            const tr = document.createElement('tr');
            // Alternating row shading with category color
            if (idx % 2 === 1) {
                tr.style.backgroundColor = evenColor;
            }
            // # col
            const tdN = document.createElement('td');
            tdN.className = 'col-rownum';
            tdN.textContent = idx + 1;
            tr.appendChild(tdN);

            unifiedCols.forEach(c => {
                const td = document.createElement('td');
                td.style.textAlign = (c.type === 'text') ? 'left' : 'right';
                const val = row[c.key];
                if (c.key === 'pct_change') {
                    if (val == null) {
                        td.innerHTML = row.is_new_entry ? '<span style="color:#27AE60;font-size:10px;font-weight:600">NEW</span>'
                            : (row.is_exit ? '<span style="color:#C0392B;font-size:10px;font-weight:600">EXIT</span>' : '\u2014');
                    } else {
                        const pct = (val * 100).toFixed(1);
                        td.innerHTML = val > 0
                            ? '<span class="positive">+' + pct + '%</span>'
                            : '<span class="negative">(' + Math.abs(pct).toFixed(1) + '%)</span>';
                    }
                } else if (c.key === 'pct_float') {
                    // pct_float stored as percentage already (e.g. 12.68)
                    td.textContent = (val != null && val > 0) ? val.toFixed(2) + '%' : '\u2014';
                    if (val == null || val === 0) td.style.color = '#ccc';
                } else {
                    td.innerHTML = formatCell(val, fmtType(c));
                }
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });

        // Totals row
        const totals = document.createElement('tr');
        totals.style.cssText = 'font-weight:700;border-top:3px solid #002147;background:#f0f4f8;';
        const tdTNum = document.createElement('td');
        tdTNum.className = 'col-rownum';
        totals.appendChild(tdTNum);
        unifiedCols.forEach(c => {
            const td = document.createElement('td');
            td.style.textAlign = (c.type === 'text') ? 'left' : 'right';
            if (c.key === 'inst_parent_name') {
                td.textContent = 'TOTAL (' + tab.rows.length + ')';
            } else if (c.type === 'shares' || c.type === 'dollar') {
                let sum = 0;
                tab.rows.forEach(r => { if (r[c.key]) sum += r[c.key]; });
                td.innerHTML = sum ? formatCell(sum, c.type === 'dollar' ? 'dollar' : 'shares') : '\u2014';
            } else if (c.key === 'pct_float') {
                let sum = 0;
                tab.rows.forEach(r => { if (r.pct_float) sum += r.pct_float; });
                td.textContent = sum > 0 ? sum.toFixed(2) + '%' : '\u2014';
            } else {
                td.textContent = '';
            }
            totals.appendChild(td);
        });
        tbody.appendChild(totals);

        table.appendChild(tbody);
        tableArea.appendChild(table);
    }

    tabDefs.forEach(t => {
        const btn = document.createElement('button');
        btn.dataset.tabId = t.id;
        btn.style.cssText = 'padding:8px 16px;border:none;background:transparent;font-size:12px;font-weight:600;cursor:pointer;color:#666;border-bottom:2px solid transparent;margin-bottom:-2px;';
        btn.textContent = t.label + ' (' + t.rows.length + ')';
        btn.classList.toggle('active', t.id === _flowTab);
        btn.onclick = () => _renderFlowTab(t.id);
        tabBar.appendChild(btn);
    });

    tableWrap.appendChild(tabBar);
    tableWrap.appendChild(tableArea);
    _renderFlowTab(_flowTab);
}

// ---------------------------------------------------------------------------
// New/Exits tab (two sub-views reusing existing queries 10 and 11)
// ---------------------------------------------------------------------------
let _neSubView = 'new';

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

    // Fund rollup context panel — insert between stats header and table
    if (stats.cik) {
        fetch(`/api/fund_rollup_context?cik=${stats.cik}`)
            .then(r => r.ok ? r.json() : null)
            .then(ctx => {
                if (!ctx || (!ctx.economic_sponsor && !ctx.decision_maker)) return;
                const panel = document.createElement('div');
                panel.className = 'fund-rollup-context';
                if (ctx.same) {
                    panel.innerHTML = `
                        <div class="rollup-row">
                            <span class="rollup-type-label">Fund Sponsor</span>
                            <span class="rollup-type-value">${ctx.economic_sponsor || '\u2014'}</span>
                        </div>`;
                } else {
                    panel.innerHTML = `
                        <div class="rollup-row">
                            <span class="rollup-type-label">Fund Sponsor / Voting</span>
                            <span class="rollup-type-value">${ctx.economic_sponsor || '\u2014'}</span>
                        </div>
                        <div class="rollup-row">
                            <span class="rollup-type-label">Decision Maker</span>
                            <span class="rollup-type-value">${ctx.decision_maker || '\u2014'}</span>
                        </div>`;
                }
                const statsHeader = tableWrap.querySelector('.portfolio-stats');
                if (statsHeader) {
                    statsHeader.after(panel);
                } else {
                    tableWrap.insertBefore(panel, tableWrap.firstChild);
                }
            })
            .catch(() => {/* silent fail — context panel is optional */});
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
        case 'nport_badge': return fmtNportBadge(val);
        default:        return String(val);
    }
}

/** Render N-PORT coverage % as color-coded badge.
 *  ≥80% green, 50-79% amber, 1-49% grey, 0/null no badge. */
function fmtNportBadge(val) {
    if (val == null || val === 0) return '\u2014';
    const pct = Number(val);
    if (isNaN(pct)) return '\u2014';
    let cls = 'nport-badge nport-grey';
    if (pct >= 80) cls = 'nport-badge nport-green';
    else if (pct >= 50) cls = 'nport-badge nport-amber';
    return `<span class="${cls}">${Math.round(pct)}%</span>`;
}

/** Resolve the best format type for a column — prefers visual over col.type. */
function fmtType(col) {
    const meta = inferColMeta(col);
    // Visual types that map directly to formatters
    if (['dollar','shares','pct','change','num','rank','nport_badge'].includes(meta.visual)) {
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
                td.innerHTML = fmtDollars(val);
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
        tdTotal.innerHTML = fmtDollars(inv.total_across);
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
        td.innerHTML = fmtDollars(colTotals[t]);
        totalsRow.appendChild(td);
    });
    const tdGrand = document.createElement('td');
    tdGrand.style.textAlign = 'right';
    tdGrand.innerHTML = fmtDollars(grandTotal);
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


// ===========================================================================
// Entity Graph tab — appended self-contained module
// ===========================================================================
//
// All identifiers are `eg`-prefixed to avoid collisions with the rest of the
// page. The Entity Graph tab is independent of currentTicker — it activates
// the institution → filer → fund hierarchy view via vis.js. Tab activation
// is handled here without modifying the existing switchTab() function.
//
// External endpoints used:
//   GET /api/admin/quarter_config           → quarter list (existing endpoint)
//   GET /api/entity_search?q=               → institution dropdown
//   GET /api/entity_children?entity_id=&level=filer|fund&quarter=
//   GET /api/entity_graph?entity_id=&quarter=&depth=&include_sub_advisers=&top_n_funds=

(function () {
    'use strict';

    // -------- DOM refs (resolved at first tab activation, not page load) ----
    let egInitialized = false;
    let egInstInput, egInstDropdown, egInstHidden;
    let egFilerSelect, egFundSelect, egQuarterSelect;
    let egBreadcrumb, egNetworkEl, egLegend, egErrorEl;

    // -------- Module state --------------------------------------------------
    let egNetwork = null;
    let egNodesDS = null;        // vis.DataSet for nodes (allows incremental adds)
    let egEdgesDS = null;        // vis.DataSet for edges
    let egCurrentGraph = null;   // last fetched graph payload
    let egCurrentInst = null;    // {entity_id, display_name}
    let egCurrentFiler = null;   // {entity_id, display_name}
    let egCurrentFund = null;    // {entity_id, display_name}
    let egQuarter = '';          // selected quarter string
    let egSearchDebounce = null;
    let egSearchAbort = null;
    let egAutocompleteIdx = -1;

    // ------------------------------------------------------------------------
    // Tab activation — wired without touching switchTab().
    // The default tab handler at line ~409 calls switchTab(tabId); switchTab
    // has no branch for 'entity-graph' so it falls through harmlessly. This
    // listener runs alongside it and handles panel show/hide.
    // ------------------------------------------------------------------------
    function _bindTabActivation() {
        const allTabs = document.querySelectorAll('.tab');
        allTabs.forEach(tab => {
            tab.addEventListener('click', function () {
                if (tab.dataset.tab === 'entity-graph') {
                    egActivate();
                } else {
                    egDeactivate();
                }
            });
        });
    }

    function egActivate() {
        // Reveal panel, hide the regular results area + action bar
        const tabPanel = document.getElementById('entity-graph-tab');
        const resultsArea = document.getElementById('results-area');
        const actionBar = document.querySelector('.action-bar');
        const managerSel = document.getElementById('manager-selector');
        const coPanelEl = document.getElementById('cross-ownership-panel');
        if (tabPanel) tabPanel.classList.remove('hidden');
        if (resultsArea) resultsArea.style.display = 'none';
        if (actionBar) actionBar.style.display = 'none';
        if (managerSel) managerSel.classList.add('hidden');
        if (coPanelEl) coPanelEl.classList.add('hidden');

        // Lazy init on first activation
        if (!egInitialized) {
            egInit();
        }
    }

    function egDeactivate() {
        const tabPanel = document.getElementById('entity-graph-tab');
        const resultsArea = document.getElementById('results-area');
        const actionBar = document.querySelector('.action-bar');
        if (tabPanel) tabPanel.classList.add('hidden');
        if (resultsArea) resultsArea.style.display = '';
        if (actionBar) actionBar.style.display = '';
    }

    // ------------------------------------------------------------------------
    // One-time init: resolve DOM refs, wire handlers, load quarters, render
    // legend.
    // ------------------------------------------------------------------------
    function egInit() {
        egInstInput     = document.getElementById('eg-institution-input');
        egInstDropdown  = document.getElementById('eg-institution-dropdown');
        egInstHidden    = document.getElementById('eg-institution-id');
        egFilerSelect   = document.getElementById('eg-filer-select');
        egFundSelect    = document.getElementById('eg-fund-select');
        egQuarterSelect = document.getElementById('eg-quarter-select');
        egBreadcrumb    = document.getElementById('eg-breadcrumb');
        egNetworkEl     = document.getElementById('eg-network');
        egLegend        = document.getElementById('eg-legend');
        egErrorEl       = document.getElementById('eg-error');

        if (!egInstInput || !egNetworkEl) {
            console.error('[Entity Graph] DOM refs missing — aborting init');
            return;
        }

        egInstInput.addEventListener('input', egOnSearchInput);
        egInstInput.addEventListener('keydown', egOnSearchKeydown);
        egInstDropdown.addEventListener('click', egOnSearchSelect);
        document.addEventListener('click', function (e) {
            if (!e.target.closest('.eg-input-wrap')) egHideSearchDropdown();
        });

        egFilerSelect.addEventListener('change', egOnFilerChange);
        egFundSelect.addEventListener('change', egOnFundChange);
        egQuarterSelect.addEventListener('change', egOnQuarterChange);

        // Suppress browser context menu on the canvas (acts as reset highlight)
        egNetworkEl.addEventListener('contextmenu', function (e) {
            e.preventDefault();
            egResetHighlight();
        });

        egRenderLegend();
        egLoadQuarters();

        egInitialized = true;
    }

    // ------------------------------------------------------------------------
    // Quarter selector — populated from /api/admin/quarter_config
    // ------------------------------------------------------------------------
    async function egLoadQuarters() {
        try {
            const res = await fetch('/api/admin/quarter_config');
            if (!res.ok) throw new Error('quarter_config HTTP ' + res.status);
            const data = await res.json();
            const quarters = (data && data.quarters) || [];
            // Latest quarter is the LAST element in config.QUARTERS — show
            // newest first in the dropdown.
            const ordered = quarters.slice().reverse();
            egQuarterSelect.innerHTML = '';
            ordered.forEach((q, i) => {
                const opt = document.createElement('option');
                opt.value = q;
                opt.textContent = q;
                if (i === 0) opt.selected = true;
                egQuarterSelect.appendChild(opt);
            });
            egQuarterSelect.disabled = false;
            egQuarter = ordered[0] || '';
        } catch (e) {
            console.error('[Entity Graph] failed to load quarters:', e);
            egShowError('Failed to load quarter list: ' + e.message);
        }
    }

    function egOnQuarterChange() {
        egQuarter = egQuarterSelect.value;
        // Re-render the graph if an institution is currently loaded
        if (egCurrentInst) {
            egRenderGraph(egCurrentInst.entity_id);
        }
    }

    // ------------------------------------------------------------------------
    // Institution type-ahead
    // ------------------------------------------------------------------------
    function egOnSearchInput() {
        const q = egInstInput.value.trim();
        egAutocompleteIdx = -1;
        if (egSearchDebounce) clearTimeout(egSearchDebounce);
        if (q.length < 2) {
            egHideSearchDropdown();
            return;
        }
        egSearchDebounce = setTimeout(() => egDoSearch(q), 250);
    }

    async function egDoSearch(q) {
        try {
            if (egSearchAbort) egSearchAbort.abort();
            egSearchAbort = new AbortController();
            const res = await fetch('/api/entity_search?q=' + encodeURIComponent(q),
                                    { signal: egSearchAbort.signal });
            if (!res.ok) throw new Error('search HTTP ' + res.status);
            const items = await res.json();
            egShowSearchDropdown(items);
        } catch (e) {
            if (e.name !== 'AbortError') {
                console.error('[Entity Graph] search error:', e);
            }
        }
    }

    function egShowSearchDropdown(items) {
        if (!Array.isArray(items) || items.length === 0) {
            egInstDropdown.innerHTML = '<div class="eg-autocomplete-item" style="color:#999;cursor:default;">No matches</div>';
            egInstDropdown.classList.remove('hidden');
            return;
        }
        egInstDropdown.innerHTML = items.map((it, i) =>
            `<div class="eg-autocomplete-item${i === egAutocompleteIdx ? ' selected' : ''}" data-eid="${it.entity_id}" data-name="${egEscape(it.display_name)}">
                <span class="eg-ac-name">${egEscape(it.display_name)}</span>
                <span class="eg-ac-meta">${egEscape(it.entity_type || '')}${it.classification ? ' · ' + egEscape(it.classification) : ''}</span>
            </div>`
        ).join('');
        egInstDropdown.classList.remove('hidden');
    }

    function egHideSearchDropdown() {
        if (!egInstDropdown) return;
        egInstDropdown.classList.add('hidden');
        egInstDropdown.innerHTML = '';
        egAutocompleteIdx = -1;
    }

    function egOnSearchKeydown(e) {
        const items = egInstDropdown.querySelectorAll('.eg-autocomplete-item[data-eid]');
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            egAutocompleteIdx = Math.min(egAutocompleteIdx + 1, items.length - 1);
            items.forEach((el, i) => el.classList.toggle('selected', i === egAutocompleteIdx));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            egAutocompleteIdx = Math.max(egAutocompleteIdx - 1, 0);
            items.forEach((el, i) => el.classList.toggle('selected', i === egAutocompleteIdx));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (egAutocompleteIdx >= 0 && items[egAutocompleteIdx]) {
                egPickInstitution(items[egAutocompleteIdx]);
            }
        } else if (e.key === 'Escape') {
            egHideSearchDropdown();
        }
    }

    function egOnSearchSelect(e) {
        const item = e.target.closest('.eg-autocomplete-item[data-eid]');
        if (item) egPickInstitution(item);
    }

    function egPickInstitution(itemEl) {
        const eid = parseInt(itemEl.dataset.eid, 10);
        const name = itemEl.dataset.name;
        egCurrentInst = { entity_id: eid, display_name: name };
        egCurrentFiler = null;
        egCurrentFund = null;
        egInstInput.value = name;
        egInstHidden.value = String(eid);
        egHideSearchDropdown();
        egLoadFilerChildren(eid);
        egRenderGraph(eid);
    }

    // ------------------------------------------------------------------------
    // Cascading dropdowns
    // ------------------------------------------------------------------------
    async function egLoadFilerChildren(entityId) {
        try {
            const res = await fetch(`/api/entity_children?entity_id=${entityId}&level=filer&quarter=${encodeURIComponent(egQuarter)}`);
            if (!res.ok) throw new Error('filer HTTP ' + res.status);
            const items = await res.json();
            egFilerSelect.innerHTML = '<option value="">— all filers —</option>' +
                items.map(it => {
                    const aum = it.aum != null ? ' (' + egFormatAUM(it.aum) + ')' : '';
                    return `<option value="${it.entity_id}" data-name="${egEscape(it.display_name)}">${egEscape(it.display_name)}${aum}</option>`;
                }).join('');
            egFilerSelect.disabled = false;
            // Reset fund select
            egFundSelect.innerHTML = '<option value="">— select filer first —</option>';
            egFundSelect.disabled = true;
        } catch (e) {
            console.error('[Entity Graph] filer load error:', e);
            egShowError('Failed to load filers: ' + e.message);
        }
    }

    async function egOnFilerChange() {
        const eid = egFilerSelect.value;
        if (!eid) {
            egCurrentFiler = null;
            egFundSelect.innerHTML = '<option value="">— select filer first —</option>';
            egFundSelect.disabled = true;
            egUpdateBreadcrumb();
            return;
        }
        const opt = egFilerSelect.options[egFilerSelect.selectedIndex];
        egCurrentFiler = { entity_id: parseInt(eid, 10), display_name: opt.dataset.name };

        // Funds attach to the institution root in this data model — load
        // funds for the institution rather than the selected filer.
        const rootId = egCurrentInst ? egCurrentInst.entity_id : eid;
        try {
            const res = await fetch(`/api/entity_children?entity_id=${rootId}&level=fund&quarter=${encodeURIComponent(egQuarter)}&top_n=200`);
            if (!res.ok) throw new Error('fund HTTP ' + res.status);
            const data = await res.json();
            const children = (data && data.children) || [];
            egFundSelect.innerHTML = '<option value="">— all funds —</option>' +
                children.map(it => {
                    const nav = it.nav != null ? ' (' + egFormatAUM(it.nav) + ')' : '';
                    return `<option value="${it.entity_id}" data-name="${egEscape(it.display_name)}">${egEscape(it.display_name)}${nav}</option>`;
                }).join('');
            egFundSelect.disabled = false;
            egCurrentFund = null;
            egUpdateBreadcrumb();
        } catch (e) {
            console.error('[Entity Graph] fund load error:', e);
            egShowError('Failed to load funds: ' + e.message);
        }
    }

    function egOnFundChange() {
        const eid = egFundSelect.value;
        if (!eid) {
            egCurrentFund = null;
            egUpdateBreadcrumb();
            return;
        }
        const opt = egFundSelect.options[egFundSelect.selectedIndex];
        egCurrentFund = { entity_id: parseInt(eid, 10), display_name: opt.dataset.name };
        egUpdateBreadcrumb();
        // Highlight the selected fund node in the existing graph
        egHighlightNodeById('fund-' + eid);
    }

    // ------------------------------------------------------------------------
    // Graph rendering
    // ------------------------------------------------------------------------
    async function egRenderGraph(entityId) {
        egClearError();
        try {
            const url = `/api/entity_graph?entity_id=${entityId}&depth=2&include_sub_advisers=true&top_n_funds=20&quarter=${encodeURIComponent(egQuarter)}`;
            const res = await fetch(url);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || 'graph HTTP ' + res.status);
            }
            const data = await res.json();
            egCurrentGraph = data;
            egInitNetwork(data);
            egUpdateBreadcrumb();
        } catch (e) {
            console.error('[Entity Graph] render error:', e);
            egShowError('Failed to render graph: ' + e.message);
        }
    }

    function egInitNetwork(data) {
        if (typeof vis === 'undefined') {
            egShowError('vis-network library failed to load — check CDN access');
            return;
        }
        // Tear down any existing instance to avoid leaks
        if (egNetwork) {
            try { egNetwork.destroy(); } catch (e) { /* noop */ }
            egNetwork = null;
        }
        egNodesDS = new vis.DataSet(data.nodes || []);
        egEdgesDS = new vis.DataSet(data.edges || []);

        const options = {
            layout: {
                hierarchical: {
                    direction: 'LR',
                    sortMethod: 'directed',
                    levelSeparation: 220,
                    nodeSpacing: 100,
                    treeSpacing: 150,
                },
            },
            physics: { enabled: false },
            edges: {
                smooth: { type: 'cubicBezier', forceDirection: 'horizontal' },
            },
            nodes: {
                shape: 'box',
                font: { size: 12, face: 'Arial', multi: false },
                borderWidth: 1,
                widthConstraint: { maximum: 180 },
            },
            interaction: {
                hover: true,
                tooltipDelay: 100,
                multiselect: false,
            },
        };

        egNetwork = new vis.Network(egNetworkEl, { nodes: egNodesDS, edges: egEdgesDS }, options);

        egNetwork.on('click', function (params) {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                const connected = egNetwork.getConnectedNodes(nodeId);
                egHighlightNeighborhood(nodeId, connected);
                egSyncDropdownsFromNode(nodeId);
            } else {
                egResetHighlight();
            }
        });

        egNetwork.on('doubleClick', function (params) {
            if (params.nodes.length > 0) {
                egToggleExpand(params.nodes[0]);
            }
        });
    }

    // ------------------------------------------------------------------------
    // Highlighting
    // ------------------------------------------------------------------------
    function _origColors(node) {
        // Read original color out of the dataset, since vis mutates on update.
        return node._origColor || node.color;
    }

    function egHighlightNeighborhood(nodeId, connectedIds) {
        if (!egNodesDS) return;
        const keep = new Set([nodeId, ...(connectedIds || [])]);
        const updates = [];
        egNodesDS.forEach(n => {
            const isOn = keep.has(n.id);
            updates.push({
                id: n.id,
                opacity: isOn ? 1.0 : 0.25,
            });
        });
        egNodesDS.update(updates);

        const edgeUpdates = [];
        egEdgesDS.forEach(e => {
            const isOn = keep.has(e.from) && keep.has(e.to);
            edgeUpdates.push({
                id: e.id,
                color: { color: isOn ? (e.color && e.color.color) || '#002147' : '#dddddd' },
            });
        });
        egEdgesDS.update(edgeUpdates);
    }

    function egResetHighlight() {
        if (!egNodesDS || !egCurrentGraph) return;
        // Restore from the original payload
        egNodesDS.update(egCurrentGraph.nodes.map(n => ({ id: n.id, opacity: 1.0 })));
        egEdgesDS.update(egCurrentGraph.edges.map(e => ({ id: e.id, color: e.color })));
    }

    function egHighlightNodeById(nodeId) {
        if (!egNetwork || !egNodesDS) return;
        if (!egNodesDS.get(nodeId)) return;
        const connected = egNetwork.getConnectedNodes(nodeId);
        egHighlightNeighborhood(nodeId, connected);
        egNetwork.focus(nodeId, { scale: 1.0, animation: { duration: 300 } });
    }

    // ------------------------------------------------------------------------
    // Expand truncated fund list (double-click on expand_trigger)
    // ------------------------------------------------------------------------
    async function egToggleExpand(nodeId) {
        const node = egNodesDS.get(nodeId);
        if (!node || node.node_type !== 'expand_trigger') return;
        const filerEid = node.filer_entity_id;
        if (!filerEid) return;
        try {
            const res = await fetch(`/api/entity_children?entity_id=${filerEid}&level=fund&quarter=${encodeURIComponent(egQuarter)}&top_n=10000`);
            if (!res.ok) throw new Error('expand HTTP ' + res.status);
            const data = await res.json();
            const children = (data && data.children) || [];
            const existingIds = new Set();
            egNodesDS.forEach(n => existingIds.add(n.id));
            const newNodes = [];
            const newEdges = [];
            children.forEach(c => {
                const fid = 'fund-' + c.entity_id;
                if (existingIds.has(fid)) return;
                newNodes.push({
                    id: fid,
                    label: c.display_name + '\n' + egFormatAUM(c.nav),
                    title: c.display_name + '<br>Series ID: ' + (c.series_id || '—') + '<br>Fund NAV: ' + egFormatAUM(c.nav),
                    level: 2,
                    node_type: 'fund',
                    entity_id: c.entity_id,
                    series_id: c.series_id,
                    aum: c.nav,
                    color: { background: '#2E7D32', border: '#1B5E20' },
                    font: { color: '#FFFFFF' },
                });
                newEdges.push({
                    from: 'inst-' + filerEid,
                    to: fid,
                    arrows: 'to',
                    dashes: false,
                    color: { color: '#002147' },
                    relationship_type: 'fund_sponsor',
                });
            });
            // Remove the trigger node + its edge
            egNodesDS.remove(nodeId);
            const removeEdges = [];
            egEdgesDS.forEach(e => { if (e.to === nodeId || e.from === nodeId) removeEdges.push(e.id); });
            removeEdges.forEach(eid => egEdgesDS.remove(eid));

            egNodesDS.add(newNodes);
            egEdgesDS.add(newEdges);
        } catch (e) {
            console.error('[Entity Graph] expand error:', e);
            egShowError('Failed to expand: ' + e.message);
        }
    }

    // ------------------------------------------------------------------------
    // Click → sync dropdowns + breadcrumb
    // ------------------------------------------------------------------------
    function egSyncDropdownsFromNode(nodeId) {
        if (!egNodesDS) return;
        const node = egNodesDS.get(nodeId);
        if (!node) return;
        if (node.node_type === 'fund') {
            // Find the fund in the dropdown if present, set selection
            for (let i = 0; i < egFundSelect.options.length; i++) {
                if (parseInt(egFundSelect.options[i].value, 10) === node.entity_id) {
                    egFundSelect.selectedIndex = i;
                    egCurrentFund = { entity_id: node.entity_id, display_name: node.display_name };
                    break;
                }
            }
        } else if (node.node_type === 'filer') {
            for (let i = 0; i < egFilerSelect.options.length; i++) {
                if (parseInt(egFilerSelect.options[i].value, 10) === node.entity_id) {
                    egFilerSelect.selectedIndex = i;
                    egCurrentFiler = { entity_id: node.entity_id, display_name: node.display_name };
                    break;
                }
            }
        }
        egUpdateBreadcrumb();
    }

    function egUpdateBreadcrumb() {
        if (!egBreadcrumb) return;
        const parts = [];
        if (egCurrentInst) parts.push(egEscape(egCurrentInst.display_name));
        if (egCurrentFiler && egCurrentFiler.entity_id !== (egCurrentInst && egCurrentInst.entity_id)) {
            parts.push(egEscape(egCurrentFiler.display_name));
        }
        if (egCurrentFund) parts.push(egEscape(egCurrentFund.display_name));
        if (egQuarter) parts.push('<span style="color:#888;">' + egEscape(egQuarter) + '</span>');
        egBreadcrumb.innerHTML = parts.length
            ? parts.join('<span class="eg-bc-sep">›</span>')
            : '<span style="color:#aaa;">Search for an institution to begin.</span>';
    }

    // ------------------------------------------------------------------------
    // Legend
    // ------------------------------------------------------------------------
    function egRenderLegend() {
        if (!egLegend) return;
        egLegend.innerHTML = `
            <div class="eg-legend-item"><span class="eg-legend-swatch" style="background:#002147;"></span>Institution</div>
            <div class="eg-legend-item"><span class="eg-legend-swatch" style="background:#4A90D9;"></span>13F Filer</div>
            <div class="eg-legend-item"><span class="eg-legend-swatch" style="background:#2E7D32;"></span>Fund Series</div>
            <div class="eg-legend-item"><span class="eg-legend-swatch" style="background:#C9B99A;"></span>Sub-adviser</div>
            <div class="eg-legend-item"><span class="eg-legend-line"></span>Ownership / sponsor</div>
            <div class="eg-legend-item"><span class="eg-legend-line dashed"></span>Sub-adviser relationship</div>
        `;
    }

    // ------------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------------
    function egFormatAUM(val) {
        if (val == null) return '\u2014';
        const num = Number(val);
        if (!isFinite(num) || num === 0) return '\u2014';
        const a = Math.abs(num);
        if (a >= 1e12) return '$' + (num / 1e12).toFixed(1) + 'T';
        if (a >= 1e9)  return '$' + (num / 1e9).toFixed(1) + 'B';
        if (a >= 1e6)  return '$' + (num / 1e6).toFixed(0) + 'M';
        if (a >= 1e3)  return '$' + (num / 1e3).toFixed(0) + 'K';
        return '$' + num.toFixed(0);
    }

    function egEscape(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function egShowError(msg) {
        if (!egErrorEl) return;
        egErrorEl.textContent = msg;
        egErrorEl.classList.remove('hidden');
    }

    function egClearError() {
        if (!egErrorEl) return;
        egErrorEl.textContent = '';
        egErrorEl.classList.add('hidden');
    }

    // ------------------------------------------------------------------------
    // Bootstrap — wire tab activation as soon as DOM is ready, and respect
    // ?tab=entity-graph to allow direct navigation without first loading a
    // ticker (since the tab bar is gated behind a ticker load otherwise).
    // ------------------------------------------------------------------------
    function _boot() {
        _bindTabActivation();
        const params = new URLSearchParams(window.location.search);
        if (params.get('tab') === 'entity-graph') {
            // Force-reveal the tab container
            const tabContainer = document.getElementById('tab-container');
            const emptyState = document.getElementById('empty-state');
            if (tabContainer) tabContainer.classList.remove('hidden');
            if (emptyState) emptyState.classList.add('hidden');
            // Mark the tab active
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            const egTab = document.querySelector('.tab[data-tab="entity-graph"]');
            if (egTab) egTab.classList.add('active');
            egActivate();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _boot);
    } else {
        _boot();
    }
})();



// ===========================================================================
// Two Companies Overlap tab — appended self-contained module
// ===========================================================================
//
// All identifiers are `tco`-prefixed. Integration: a single `else if` branch
// added to the main switchTab() routes the 'two-co-overlap' tab through
// `window.loadTwoCoOverlap`, which is published from this IIFE. That matches
// the per-tab loader pattern every other tab uses.
//
// Autocomplete reuses the existing page-global `tickerList` array + the
// `filterTickers(val)` helper that cross-ownership already uses — no
// per-keystroke fetch of `/api/tickers`.

(function () {
    'use strict';

    // ── state ──────────────────────────────────────────────────────────────
    let _tcoSubject  = '';            // current subject ticker
    let _tcoSecond   = '';            // current second ticker (empty until selected)
    let _tcoQuarter  = '';            // currently selected quarter
    let _tcoQuartersLoaded = false;
    let _tcoBooted   = false;         // has _tcoBoot run?

    // ── boot ───────────────────────────────────────────────────────────────
    function _tcoBoot() {
        if (_tcoBooted) return;
        _tcoBooted = true;
        _buildQuarterButtons();
        _wireSecondInput();
    }

    // ── activation (called from switchTab branch) ──────────────────────────
    //
    // Shows the panel, hides results-area and action-bar, and triggers the
    // subject load if the main ticker has changed (or is newly populated).
    function tcoActivate() {
        _tcoBoot();
        const panel       = document.getElementById('two-co-overlap-tab');
        const resultsArea = document.getElementById('results-area');
        const actionBar   = document.querySelector('.action-bar');
        const managerSel  = document.getElementById('manager-selector');
        const coPanelEl   = document.getElementById('cross-ownership-panel');
        const egPanel     = document.getElementById('entity-graph-tab');
        if (panel)       panel.style.display = '';
        if (resultsArea) resultsArea.style.display = 'none';
        if (actionBar)   actionBar.style.display = 'none';
        if (managerSel)  managerSel.classList.add('hidden');
        if (coPanelEl)   coPanelEl.classList.add('hidden');
        if (egPanel)     egPanel.classList.add('hidden');

        // Sync subject from the main header ticker input.
        const mainInput = document.getElementById('ticker-input');
        const ticker = (mainInput && mainInput.value || '').trim().toUpperCase();
        if (!ticker) {
            _tcoShowError('Load a ticker in the header first.');
            return;
        }
        _tcoShowError('');

        // If subject changed since last activation, clear second company and reload.
        if (ticker !== _tcoSubject) {
            _tcoSubject = ticker;
            _tcoSecond  = '';
            const secInp = document.getElementById('tco-second-input');
            const secHid = document.getElementById('tco-second-ticker');
            if (secInp) secInp.value = '';
            if (secHid) secHid.value = '';
            _tcoLoadSubject(ticker, _tcoQuarter);
        }
    }

    function tcoDeactivate() {
        const panel       = document.getElementById('two-co-overlap-tab');
        const resultsArea = document.getElementById('results-area');
        const actionBar   = document.querySelector('.action-bar');
        if (panel) panel.style.display = 'none';
        // Unconditionally clear inline display so results-area falls back to
        // its stylesheet-default (block). The earlier guarded form only
        // restored when the current value was 'none', which could race
        // against a tab switch that didn't go through tcoActivate first.
        if (resultsArea) resultsArea.style.display = '';
        if (actionBar)   actionBar.style.display = '';
    }

    // ── quarter buttons ────────────────────────────────────────────────────
    function _buildQuarterButtons() {
        if (_tcoQuartersLoaded) return;
        const container = document.getElementById('tco-quarter-btns');
        if (!container) return;
        fetch('/api/admin/quarter_config')
            .then(r => r.json())
            .then(data => {
                const qtrs = (data && data.quarters ? data.quarters : []).slice().reverse();
                if (!qtrs.length) return;
                _tcoQuarter = qtrs[0];
                container.innerHTML = qtrs.map((q, i) => {
                    const active = i === 0;
                    return '<button class="tco-qbtn' + (active ? ' tco-qbtn-active' : '') + '"'
                        + ' data-q="' + q + '"'
                        + ' style="padding:4px 10px; font-size:12px; cursor:pointer;'
                        + ' border:1px solid #ccc; border-radius:3px;'
                        + ' background:' + (active ? '#002147' : '#fff') + ';'
                        + ' color:' + (active ? '#fff' : '#333') + ';">'
                        + q + '</button>';
                }).join('');
                _tcoQuartersLoaded = true;

                container.addEventListener('click', function (e) {
                    const btn = e.target.closest('.tco-qbtn');
                    if (!btn) return;
                    container.querySelectorAll('.tco-qbtn').forEach(b => {
                        b.style.background = '#fff';
                        b.style.color = '#333';
                    });
                    btn.style.background = '#002147';
                    btn.style.color = '#fff';
                    _tcoQuarter = btn.dataset.q;
                    // Re-load: use the overlap endpoint if a second company is
                    // already selected, otherwise subject-only.
                    if (_tcoSubject && _tcoSecond) {
                        _tcoLoadOverlap(_tcoSubject, _tcoSecond, _tcoQuarter);
                    } else if (_tcoSubject) {
                        _tcoLoadSubject(_tcoSubject, _tcoQuarter);
                    }
                });
            })
            .catch(function (e) {
                console.error('[Two Companies Overlap] quarter_config fetch failed:', e);
            });
    }

    // ── second company autocomplete ────────────────────────────────────────
    //
    // Reuses the page-global `tickerList` + `filterTickers()` pair that
    // cross-ownership already wires — no per-keystroke fetch of /api/tickers.
    function _wireSecondInput() {
        const inp  = document.getElementById('tco-second-input');
        const drop = document.getElementById('tco-second-dropdown');
        const hid  = document.getElementById('tco-second-ticker');
        if (!inp || !drop) return;

        let selIdx = -1;

        inp.addEventListener('input', function () {
            const val = inp.value.trim();
            selIdx = -1;
            if (val.length < 2) {
                drop.style.display = 'none';
                drop.innerHTML = '';
                return;
            }
            const matches = (typeof filterTickers === 'function')
                ? filterTickers(val).slice(0, 12)
                : [];
            if (!matches.length) {
                drop.style.display = 'none';
                return;
            }
            drop.innerHTML = matches.map(function (t) {
                return '<div class="tco-dd-item" data-ticker="' + t.ticker + '"'
                    + ' style="padding:6px 10px; cursor:pointer; font-size:13px;'
                    + ' border-bottom:1px solid #f0f0f0;">'
                    + '<strong>' + t.ticker + '</strong>'
                    + '<span style="color:#666; margin-left:6px; font-size:12px;">'
                    + _tcoEsc(t.name || '') + '</span>'
                    + '</div>';
            }).join('');
            drop.style.display = 'block';

            drop.querySelectorAll('.tco-dd-item').forEach(function (item) {
                item.addEventListener('mouseenter', function () { item.style.background = '#f5f8ff'; });
                item.addEventListener('mouseleave', function () { item.style.background = '#fff'; });
                item.addEventListener('click', function () {
                    const ticker = item.dataset.ticker;
                    inp.value = ticker;
                    if (hid) hid.value = ticker;
                    drop.style.display = 'none';
                    _tcoSecond = ticker;
                    if (_tcoSubject) {
                        _tcoLoadOverlap(_tcoSubject, ticker, _tcoQuarter);
                    }
                });
            });
        });

        inp.addEventListener('keydown', function (e) {
            const items = drop.querySelectorAll('.tco-dd-item');
            if (e.key === 'ArrowDown' && items.length) {
                e.preventDefault();
                selIdx = Math.min(selIdx + 1, items.length - 1);
                items.forEach((el, i) => el.style.background = (i === selIdx ? '#e8f0fa' : '#fff'));
            } else if (e.key === 'ArrowUp' && items.length) {
                e.preventDefault();
                selIdx = Math.max(selIdx - 1, 0);
                items.forEach((el, i) => el.style.background = (i === selIdx ? '#e8f0fa' : '#fff'));
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (selIdx >= 0 && items[selIdx]) {
                    items[selIdx].click();
                }
            } else if (e.key === 'Escape') {
                drop.style.display = 'none';
            }
        });

        document.addEventListener('click', function (e) {
            if (!inp.contains(e.target) && !drop.contains(e.target)) {
                drop.style.display = 'none';
            }
        });
    }

    // ── data loading ────────────────────────────────────────────────────────
    function _tcoLoadSubject(ticker, quarter) {
        _tcoSetLoading();
        const q = quarter || _tcoQuarter || '';
        fetch('/api/two_company_subject?subject=' + encodeURIComponent(ticker)
              + '&quarter=' + encodeURIComponent(q))
            .then(r => r.json())
            .then(data => {
                if (data && data.error) { _tcoShowError(data.error); return; }
                _tcoRender(data, false);
            })
            .catch(e => _tcoShowError('Request failed: ' + e.message));
    }

    function _tcoLoadOverlap(subject, second, quarter) {
        _tcoSetLoading();
        const q = quarter || _tcoQuarter || '';
        fetch('/api/two_company_overlap?subject=' + encodeURIComponent(subject)
              + '&second=' + encodeURIComponent(second)
              + '&quarter=' + encodeURIComponent(q))
            .then(r => r.json())
            .then(data => {
                if (data && data.error) { _tcoShowError(data.error); return; }
                _tcoRender(data, true);
            })
            .catch(e => _tcoShowError('Request failed: ' + e.message));
    }

    function _tcoSetLoading() {
        ['tco-inst-body', 'tco-fund-body'].forEach(function (id) {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '<tr><td colspan="8" style="padding:12px; text-align:center; color:#888;">Loading…</td></tr>';
        });
        ['tco-inst-foot', 'tco-fund-foot'].forEach(function (id) {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        });
        _tcoShowError('');
    }

    // ── render ─────────────────────────────────────────────────────────────
    function _tcoRender(data, hasSecond) {
        const meta = data.meta || {};
        const s = meta.subject || _tcoSubject || '';
        const c = hasSecond ? (meta.second || _tcoSecond || '') : '';

        ['inst', 'fund'].forEach(function (type) {
            _setTxt('tco-' + type + '-h-subj-pct', s);
            _setTxt('tco-' + type + '-h-sec-pct',  c || '\u2014');
            _setTxt('tco-' + type + '-h-subj-val', s);
            _setTxt('tco-' + type + '-h-sec-val',  c || '\u2014');
        });

        _tcoRenderPanel('inst', data.institutional || [], s, c, hasSecond);
        _tcoRenderPanel('fund', data.fund          || [], s, c, hasSecond);
    }

    function _tcoRenderPanel(type, rows, subj, sec, hasSecond) {
        const tbody = document.getElementById('tco-' + type + '-body');
        const tfoot = document.getElementById('tco-' + type + '-foot');
        if (!tbody) return;

        const display = rows.slice(0, 15);

        if (!display.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="padding:12px; text-align:center; color:#888;">No data</td></tr>';
            if (tfoot) tfoot.innerHTML = '';
            const emptySum = document.getElementById('tco-' + type + '-summary');
            if (emptySum) emptySum.style.display = 'none';
            return;
        }

        tbody.innerHTML = display.map(function (r, i) {
            const bg   = (hasSecond && r.is_overlap) ? 'background:rgba(74,144,217,0.08);' : '';
            const name = r.holder || r.fund_name || '\u2014';
            const spct = (r.subj_pct_float != null)
                ? r.subj_pct_float.toFixed(2) + '%' : '\u2014';
            const cpct = (hasSecond && r.sec_shares && r.sec_shares > 0 && r.sec_pct_float != null)
                ? r.sec_pct_float.toFixed(2) + '%' : '\u2014';
            const sval = (r.subj_dollars && r.subj_dollars > 0)
                ? '$' + _fmtM(r.subj_dollars) : '\u2014';
            const cval = (hasSecond && r.sec_dollars && r.sec_dollars > 0)
                ? '$' + _fmtM(r.sec_dollars) : '\u2014';

            return '<tr style="' + bg + '">'
                + '<td style="text-align:center; color:#888; width:36px;">' + (i + 1) + '</td>'
                + '<td style="width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"'
                + ' title="' + _tcoEsc(name) + '">' + _tcoEsc(name) + '</td>'
                + '<td style="text-align:right; padding-right:4px; width:62px;">' + spct + '</td>'
                + '<td style="text-align:right; padding-right:4px; width:62px;">' + cpct + '</td>'
                + '<td style="width:16px;"></td>'
                + '<td style="text-align:right; padding-right:4px; width:62px;">' + sval + '</td>'
                + '<td style="text-align:right; width:62px;">' + cval + '</td>'
                + '<td style="width:3px;"></td>'
                + '</tr>';
        }).join('');

        // Tfoot — two total rows (Top 15 and Top 25), identical column layout
        // to the body. Computed via _buildTotalsRow() over successively larger
        // slices of the full `rows` array (not the 15-row `display` slice).
        if (tfoot) {
            const t15 = _buildTotalsRow(rows, 15, hasSecond);
            const t25 = _buildTotalsRow(rows, 25, hasSecond);
            tfoot.innerHTML = [t15, t25].map(function (t) {
                const borderTop = t.n === 15 ? '2px solid #002147' : '1px solid #ddd';
                return '<tr style="font-weight:600; border-top:' + borderTop + '; background:#f9f9f9;">'
                    + '<td style="width:36px;"></td>'
                    + '<td style="width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Top ' + t.n + ' Total</td>'
                    + '<td style="text-align:right; padding-right:4px; width:62px;">' + t.sumSpct.toFixed(2) + '%</td>'
                    + '<td style="text-align:right; padding-right:4px; width:62px;">' + (t.sumCpct > 0 ? t.sumCpct.toFixed(2) + '%' : '\u2014') + '</td>'
                    + '<td style="width:16px;"></td>'
                    + '<td style="text-align:right; padding-right:4px; width:62px;">$' + _fmtM(t.sumSval) + '</td>'
                    + '<td style="text-align:right; width:62px;">' + (t.sumCval > 0 ? '$' + _fmtM(t.sumCval) : '\u2014') + '</td>'
                    + '<td style="width:3px;"></td>'
                    + '</tr>';
            }).join('');
        }

        // Per-panel summary
        _tcoRenderSummary(type, rows, subj, sec, hasSecond);
    }

    function _tcoRenderSummary(type, rows, subj, sec, hasSecond) {
        const div   = document.getElementById('tco-' + type + '-summary');
        const tbody = document.getElementById('tco-' + type + '-sbody');
        const sc1   = document.getElementById('tco-' + type + '-scol1');
        const sc2   = document.getElementById('tco-' + type + '-scol2');
        if (!div || !tbody) return;

        if (sc1) sc1.textContent = hasSecond ? ('% of ' + sec + ' float by ' + subj + ' top N') : '\u2014';
        if (sc2) sc2.textContent = hasSecond ? ('% of ' + subj + ' float by ' + sec + ' top N') : '\u2014';

        const results = [25, 50].map(function (n) {
            const cohort = rows.slice(0, n);
            const overlap = hasSecond ? cohort.filter(r => r.is_overlap) : [];
            const pctSecSubj = overlap.reduce(function (a, r) {
                return a + (r.sec_pct_float && r.sec_shares > 0 ? r.sec_pct_float : 0);
            }, 0);
            const bySecDol = hasSecond
                ? rows.slice().sort((a, b) => (b.sec_dollars || 0) - (a.sec_dollars || 0)).slice(0, n)
                : [];
            const pctSubjSec = bySecDol.reduce(function (a, r) {
                return a + (r.subj_pct_float != null ? r.subj_pct_float : 0);
            }, 0);
            return { n: n, overlap: overlap.length, pctSecSubj: pctSecSubj, pctSubjSec: pctSubjSec };
        });

        tbody.innerHTML = results.map(function (r) {
            return '<tr>'
                + '<td>Top ' + r.n + '</td>'
                + '<td style="text-align:right;">' + r.overlap + '</td>'
                + '<td style="text-align:right;">' + (hasSecond ? r.pctSecSubj.toFixed(2) + '%' : '\u2014') + '</td>'
                + '<td style="text-align:right;">' + (hasSecond ? r.pctSubjSec.toFixed(2) + '%' : '\u2014') + '</td>'
                + '</tr>';
        }).join('');

        div.style.display = 'block';
    }

    // ── helpers ────────────────────────────────────────────────────────────
    function _buildTotalsRow(rows, n, hasSecond) {
        // Sum % and $ columns across the top-N slice. Second-company sums
        // only include rows where the second company actually holds shares.
        const slice = rows.slice(0, n);
        const sumSpct = slice.reduce(function (a, r) {
            return a + (r.subj_pct_float || 0);
        }, 0);
        const sumCpct = hasSecond
            ? slice.reduce(function (a, r) {
                return a + (r.sec_shares > 0 && r.sec_pct_float ? r.sec_pct_float : 0);
              }, 0)
            : 0;
        const sumSval = slice.reduce(function (a, r) {
            return a + (r.subj_dollars || 0);
        }, 0);
        const sumCval = hasSecond
            ? slice.reduce(function (a, r) {
                return a + (r.sec_dollars || 0);
              }, 0)
            : 0;
        return { n: n, sumSpct: sumSpct, sumCpct: sumCpct, sumSval: sumSval, sumCval: sumCval };
    }

    function _fmtM(dollars) {
        // $M rounded integer with thousands separator. Empty/NaN → em dash.
        if (dollars == null || isNaN(dollars)) return '\u2014';
        const m = Math.round(dollars / 1e6);
        return m.toLocaleString('en-US');
    }

    function _setTxt(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function _tcoShowError(msg) {
        const el = document.getElementById('tco-error');
        if (!el) return;
        el.textContent = msg || '';
        el.style.display = msg ? 'block' : 'none';
    }

    function _tcoEsc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ── publish entry points for switchTab integration ─────────────────────
    window.loadTwoCoOverlap = tcoActivate;
    window._tcoDeactivate   = tcoDeactivate;

    // Boot on DOMContentLoaded so the main tickerList has already started loading
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _tcoBoot);
    } else {
        _tcoBoot();
    }
})();
