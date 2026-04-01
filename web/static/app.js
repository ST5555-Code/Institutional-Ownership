/* ================================================================
   13F Institutional Ownership Research — Frontend
   ================================================================ */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let tickerList = [];          // [{ticker, name}]
let currentTicker = '';
let currentQuery = 1;
let currentData = [];         // raw JSON from last query
let sortCol = null;
let sortDir = 'asc';
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
const managerSelector = document.getElementById('manager-selector');
const managerDropdown = document.getElementById('manager-dropdown');
const loadPortfolioBtn = document.getElementById('load-portfolio-btn');

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function fmtDollars(val) {
    if (val == null || val === 0) return '\u2014';
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1e12) return sign + '$' + (abs / 1e12).toFixed(1) + 'T';
    if (abs >= 1e9)  return sign + '$' + (abs / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6)  return sign + '$' + (abs / 1e6).toFixed(0) + 'M';
    if (abs >= 1e3)  return sign + '$' + (abs / 1e3).toFixed(0) + 'K';
    return sign + '$' + abs.toLocaleString('en-US', {maximumFractionDigits: 0});
}

function fmtShares(val) {
    if (val == null || val === 0) return '\u2014';
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1e9) return sign + (abs / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6) return sign + (abs / 1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + 'K';
    return sign + abs.toLocaleString('en-US', {maximumFractionDigits: 0});
}

function fmtPct(val) {
    if (val == null || val === 0) return '\u2014';
    return val.toFixed(2) + '%';
}

function fmtNum(val) {
    if (val == null) return '\u2014';
    if (typeof val === 'number') {
        if (val === 0) return '\u2014';
        return val.toLocaleString('en-US', {maximumFractionDigits: 2});
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
        ['sum-quarter','sum-holdings','sum-float','sum-holders','sum-split','sum-mktcap','sum-price']
            .forEach(id => document.getElementById(id).textContent = '\u2014');
    }

    // Load current tab
    if (currentQuery === 7) {
        managerSelector.classList.remove('hidden');
        loadManagerDropdown();
    } else {
        managerSelector.classList.add('hidden');
        loadQuery(currentQuery);
    }
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentQuery = parseInt(tab.dataset.query);
        sortCol = null;
        sortDir = 'asc';
        // Show/hide manager selector for Q7
        if (currentQuery === 7) {
            managerSelector.classList.remove('hidden');
            loadManagerDropdown();
        } else {
            managerSelector.classList.add('hidden');
            loadQuery(currentQuery);
        }
    });
});

// ---------------------------------------------------------------------------
// Load query data
// ---------------------------------------------------------------------------
async function loadQuery(qnum, extraParams) {
    showSpinner();
    clearError();
    tableWrap.innerHTML = '';

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
        const raw = await res.json();
        hideSpinner();

        if (qnum === 15) {
            currentData = raw;
            renderStats(raw);
        } else if (qnum === 7) {
            // Q7 returns {stats, positions}
            currentData = raw.positions || [];
            renderQuery7(raw);
        } else {
            currentData = raw;
            renderTable(raw, qnum);
        }
    } catch (e) {
        hideSpinner();
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
        {key: 'rank',        label: '#',            type: 'num'},
        {key: 'institution', label: 'Institution',  type: 'text'},
        {key: 'value_live',  label: 'Value (Live)', type: 'dollar'},
        {key: 'shares',      label: 'Shares',       type: 'shares'},
        {key: 'pct_float',   label: '% Float',      type: 'pct'},
        {key: 'type',        label: 'Type',         type: 'text'},
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
        {key: 'manager_type',     label: 'Type',            type: 'text'},
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

function renderTable(data, qnum) {
    if (!data || !data.length) {
        tableWrap.innerHTML = '<div class="error-msg">No data available.</div>';
        return;
    }

    const cols = QUERY_COLUMNS[qnum];
    if (!cols) {
        const keys = Object.keys(data[0]).filter(k => !k.startsWith('_'));
        return renderTableFromKeys(data, keys);
    }

    // Detect hierarchy: data has level/is_parent fields
    const hasHierarchy = data.some(r => r.level === 1 || r.is_parent === true);
    // Detect sections (Query 2 entries/exits)
    const hasSections = data.some(r => r.section != null);

    renderHierarchicalTable(data, cols, qnum, hasHierarchy, hasSections);
}

/**
 * Single reusable renderer for ALL tables — flat and hierarchical.
 * Auto-infers column widths and alignment from key/label names.
 * Applies: fixed layout, colgroup widths, header alignment, name ellipsis
 * with tooltip, hierarchy indent, change/delta red/green coloring, and
 * color-coding legend on tabs with a Type column.
 */
function renderHierarchicalTable(data, cols, qnum, hasHierarchy, hasSections) {
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

    // --- Header ---
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
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

    // --- Body ---
    const tbody = document.createElement('tbody');
    let lastSection = null;

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
        if (row.level === 1) tr.classList.add('level-1');
        if (row.is_parent) tr.classList.add('parent-row');

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
                        displayVal = row.institution || val || '';
                    } else if (row.level === 1) {
                        td.classList.add('col-indent');
                        const prefix = (rtype && rtype !== 'passive' && rtype !== 'unknown') ? '* ' : '';
                        displayVal = '\u21B3 ' + prefix + (val || '');
                    } else {
                        displayVal = val != null ? String(val) : '';
                    }
                } else {
                    displayVal = val != null ? String(val) : '';
                }
                td.textContent = displayVal;
                td.title = displayVal.replace(/^\u21B3 \*? ?/, '');
            }
            // --- Change/delta columns: red/green coloring ---
            else if (isChangeCol(col) && typeof val === 'number' && val !== 0) {
                td.textContent = formatCell(val, fmtType(col));
                td.style.color = val < 0 ? '#C0392B' : '#27AE60';
            }
            // --- All other columns ---
            else {
                td.textContent = formatCell(val, fmtType(col));
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    // --- Assemble ---
    tableWrap.innerHTML = '';
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
