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

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function fmtDollars(val) {
    if (val == null || val === 0) return '$0';
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1e12) return sign + '$' + (abs / 1e12).toFixed(1) + 'T';
    if (abs >= 1e9)  return sign + '$' + (abs / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6)  return sign + '$' + (abs / 1e6).toFixed(0) + 'M';
    if (abs >= 1e3)  return sign + '$' + (abs / 1e3).toFixed(0) + 'K';
    return sign + '$' + abs.toLocaleString('en-US', {maximumFractionDigits: 0});
}

function fmtShares(val) {
    if (val == null || val === 0) return '0';
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    if (abs >= 1e9) return sign + (abs / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6) return sign + (abs / 1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + 'K';
    return sign + abs.toLocaleString('en-US', {maximumFractionDigits: 0});
}

function fmtPct(val) {
    if (val == null) return '\u2014';
    return val.toFixed(2) + '%';
}

function fmtNum(val) {
    if (val == null) return '\u2014';
    if (typeof val === 'number') return val.toLocaleString('en-US', {maximumFractionDigits: 2});
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
    loadQuery(currentQuery);
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
        loadQuery(currentQuery);
    });
});

// ---------------------------------------------------------------------------
// Load query data
// ---------------------------------------------------------------------------
async function loadQuery(qnum) {
    showSpinner();
    clearError();
    tableWrap.innerHTML = '';

    const params = new URLSearchParams();
    if (currentTicker) params.set('ticker', currentTicker);
    const url = `/api/query${qnum}?${params}`;

    try {
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        currentData = await res.json();
        hideSpinner();

        if (qnum === 15) {
            renderStats(currentData);
        } else {
            renderTable(currentData, qnum);
        }
    } catch (e) {
        hideSpinner();
        showError(e.message);
    }
}

// ---------------------------------------------------------------------------
// Table rendering
// ---------------------------------------------------------------------------

// Column definitions per query
const QUERY_COLUMNS = {
    1: [
        {key: 'rank', label: '#', type: 'num'},
        {key: 'institution', label: 'Institution', type: 'text'},
        {key: 'value_live', label: 'Value (Live)', type: 'dollar'},
        {key: 'shares', label: 'Shares', type: 'shares'},
        {key: 'pct_float', label: '% Float', type: 'pct'},
        {key: 'type', label: 'Type', type: 'text'},
    ],
    2: [
        {key: 'fund_name', label: 'Institution / Fund', type: 'text'},
        {key: 'q1_shares', label: 'Q1 Shares', type: 'shares'},
        {key: 'q4_shares', label: 'Q4 Shares', type: 'shares'},
        {key: 'change_shares', label: 'Change', type: 'shares'},
        {key: 'change_pct', label: 'Chg%', type: 'pct'},
        {key: 'type', label: 'Type', type: 'text'},
    ],
    3: [
        {key: 'manager_name', label: 'Active Holder', type: 'text'},
        {key: 'position_value', label: 'Position Value', type: 'dollar'},
        {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
        {key: 'pct_of_float', label: '% Float', type: 'pct'},
        {key: 'mktcap_percentile', label: 'MktCap Pctile', type: 'pct'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'source', label: 'Source', type: 'text'},
    ],
    4: [
        {key: 'category', label: 'Category', type: 'text'},
        {key: 'num_holders', label: 'Holders', type: 'num'},
        {key: 'total_shares', label: 'Total Shares', type: 'shares'},
        {key: 'total_value', label: 'Total Value', type: 'dollar'},
        {key: 'total_pct_float', label: '% Float', type: 'pct'},
        {key: 'pct_of_inst', label: '% of Inst.', type: 'pct'},
    ],
    5: [
        {key: 'holder', label: 'Holder', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'q1_shares', label: 'Q1', type: 'shares'},
        {key: 'q2_shares', label: 'Q2', type: 'shares'},
        {key: 'q3_shares', label: 'Q3', type: 'shares'},
        {key: 'q4_shares', label: 'Q4', type: 'shares'},
        {key: 'q1_to_q2', label: 'Q1\u2192Q2', type: 'shares'},
        {key: 'q2_to_q3', label: 'Q2\u2192Q3', type: 'shares'},
        {key: 'q3_to_q4', label: 'Q3\u2192Q4', type: 'shares'},
        {key: 'full_year_change', label: 'Full Yr', type: 'shares'},
    ],
    6: [
        {key: 'manager_name', label: 'Manager', type: 'text'},
        {key: 'quarter', label: 'Quarter', type: 'text'},
        {key: 'shares', label: 'Shares', type: 'shares'},
        {key: 'market_value_usd', label: 'Value (Filed)', type: 'dollar'},
        {key: 'market_value_live', label: 'Value (Live)', type: 'dollar'},
        {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
        {key: 'pct_of_float', label: '% Float', type: 'pct'},
    ],
    7: [
        {key: 'ticker', label: 'Ticker', type: 'text'},
        {key: 'issuer_name', label: 'Issuer', type: 'text'},
        {key: 'shares', label: 'Shares', type: 'shares'},
        {key: 'market_value_live', label: 'Value (Live)', type: 'dollar'},
        {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
        {key: 'pct_of_float', label: '% Float', type: 'pct'},
        {key: 'market_cap', label: 'Market Cap', type: 'dollar'},
    ],
    8: [
        {key: 'ticker', label: 'Ticker', type: 'text'},
        {key: 'issuer_name', label: 'Issuer', type: 'text'},
        {key: 'shared_holders', label: 'Shared Holders', type: 'num'},
        {key: 'overlap_pct', label: 'Overlap %', type: 'pct'},
        {key: 'total_value', label: 'Total Value', type: 'dollar'},
    ],
    9: [
        {key: 'sector', label: 'Sector', type: 'text'},
        {key: 'num_stocks', label: 'Stocks', type: 'num'},
        {key: 'sector_value', label: 'Sector Value', type: 'dollar'},
        {key: 'pct_of_total', label: '% of Total', type: 'pct'},
    ],
    10: [
        {key: 'manager_name', label: 'Manager', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'shares', label: 'Shares', type: 'shares'},
        {key: 'market_value_live', label: 'Value (Live)', type: 'dollar'},
        {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
        {key: 'pct_of_float', label: '% Float', type: 'pct'},
    ],
    11: [
        {key: 'manager_name', label: 'Manager', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'q3_shares', label: 'Q3 Shares', type: 'shares'},
        {key: 'q3_value', label: 'Q3 Value', type: 'dollar'},
        {key: 'q3_pct', label: '% Portfolio (Q3)', type: 'pct'},
    ],
    12: [
        {key: 'rank', label: '#', type: 'num'},
        {key: 'holder', label: 'Holder', type: 'text'},
        {key: 'total_pct_float', label: '% Float', type: 'pct'},
        {key: 'cumulative_pct', label: 'Cumulative %', type: 'pct'},
        {key: 'total_shares', label: 'Shares', type: 'shares'},
    ],
    13: [
        {key: 'ticker', label: 'Ticker', type: 'text'},
        {key: 'issuer_name', label: 'Issuer', type: 'text'},
        {key: 'buyers', label: 'Buyers', type: 'num'},
        {key: 'sellers', label: 'Sellers', type: 'num'},
        {key: 'new_positions', label: 'New', type: 'num'},
        {key: 'net_flow', label: 'Net', type: 'num'},
        {key: 'buy_pct', label: 'Buy%', type: 'pct'},
        {key: 'q4_total_value', label: 'Q4 Value', type: 'dollar'},
    ],
    14: [
        {key: 'manager_name', label: 'Manager', type: 'text'},
        {key: 'manager_type', label: 'Type', type: 'text'},
        {key: 'manager_aum_bn', label: 'AUM ($B)', type: 'num'},
        {key: 'position_mm', label: 'Position ($M)', type: 'num'},
        {key: 'pct_of_portfolio', label: '% Portfolio', type: 'pct'},
        {key: 'is_activist', label: 'Activist', type: 'text'},
    ],
};

function renderTable(data, qnum) {
    if (!data || !data.length) {
        tableWrap.innerHTML = '<div class="error-msg">No data available.</div>';
        return;
    }

    const cols = QUERY_COLUMNS[qnum];
    if (!cols) {
        // Fallback: auto-generate columns from data keys
        const keys = Object.keys(data[0]).filter(k => !k.startsWith('_'));
        return renderTableFromKeys(data, keys);
    }

    // Handle Q2 sections
    if (qnum === 2) return renderQuery2Table(data, cols);

    const table = document.createElement('table');
    table.className = 'data-table';

    // Header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    cols.forEach((col, ci) => {
        const th = document.createElement('th');
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

    // Body
    const tbody = document.createElement('tbody');
    data.forEach(row => {
        const tr = document.createElement('tr');
        // Hierarchy
        if (row.level === 1) tr.classList.add('level-1');
        if (row.is_parent) tr.classList.add('parent-row');
        // Type tint
        const rtype = row.type || row.manager_type || '';
        if (rtype) tr.classList.add('type-' + rtype.replace(/[^a-z_]/gi, '').toLowerCase());

        cols.forEach(col => {
            const td = document.createElement('td');
            const val = row[col.key];
            td.className = (col.type === 'text') ? 'text' : 'num';

            if (col.key === 'institution' && row.level === 1) {
                td.textContent = '\u21B3 ' + (val || '');
            } else {
                td.textContent = formatCell(val, col.type);
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    tableWrap.innerHTML = '';
    tableWrap.appendChild(table);
}

function renderQuery2Table(data, cols) {
    const table = document.createElement('table');
    table.className = 'data-table';

    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    cols.forEach((col, ci) => {
        const th = document.createElement('th');
        th.textContent = col.label;
        th.dataset.colIdx = ci;
        const arrow = document.createElement('span');
        arrow.className = 'sort-arrow';
        th.appendChild(arrow);
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    let lastSection = null;

    data.forEach(row => {
        // Section headers
        if (row.section !== lastSection) {
            lastSection = row.section;
            if (row.section === 'entries') {
                const sectionTr = document.createElement('tr');
                sectionTr.className = 'section-header';
                const td = document.createElement('td');
                td.colSpan = cols.length;
                td.textContent = 'NEW ENTRIES (>100K shares)';
                sectionTr.appendChild(td);
                tbody.appendChild(sectionTr);
            } else if (row.section === 'exits') {
                const sectionTr = document.createElement('tr');
                sectionTr.className = 'section-header';
                const td = document.createElement('td');
                td.colSpan = cols.length;
                td.textContent = 'FULL EXITS (>100K shares)';
                sectionTr.appendChild(td);
                tbody.appendChild(sectionTr);
            }
        }

        const tr = document.createElement('tr');
        if (row.level === 1) tr.classList.add('level-1');
        if (row.is_parent) tr.classList.add('parent-row');
        const rtype = row.type || '';
        if (rtype) tr.classList.add('type-' + rtype.replace(/[^a-z_]/gi, '').toLowerCase());

        cols.forEach(col => {
            const td = document.createElement('td');
            const val = row[col.key];
            td.className = (col.type === 'text') ? 'text' : 'num';

            if (col.key === 'fund_name' && row.level === 1 && !row.is_parent) {
                const prefix = (rtype && rtype !== 'passive' && rtype !== 'unknown') ? '* ' : '';
                td.textContent = '\u21B3 ' + prefix + (val || '');
            } else if (col.key === 'fund_name' && row.is_parent) {
                td.textContent = row.institution || val || '';
                td.classList.add('text');
            } else {
                td.textContent = formatCell(val, col.type);
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    tableWrap.innerHTML = '';
    tableWrap.appendChild(table);
}

function renderTableFromKeys(data, keys) {
    const table = document.createElement('table');
    table.className = 'data-table';
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    keys.forEach(k => {
        const th = document.createElement('th');
        th.textContent = k;
        hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    data.forEach(row => {
        const tr = document.createElement('tr');
        keys.forEach(k => {
            const td = document.createElement('td');
            td.textContent = formatCellAuto(row[k]);
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableWrap.innerHTML = '';
    tableWrap.appendChild(table);
}

function formatCell(val, type) {
    if (val == null) return '\u2014';
    switch (type) {
        case 'dollar': return fmtDollars(val);
        case 'shares': return fmtShares(val);
        case 'pct':    return fmtPct(val);
        case 'num':    return fmtNum(val);
        default:       return String(val);
    }
}

function formatCellAuto(val) {
    if (val == null) return '\u2014';
    if (typeof val === 'number') {
        if (Math.abs(val) > 1e6) return fmtDollars(val);
        return fmtNum(val);
    }
    return String(val);
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

    // Filter out section headers for Q2
    const sortable = data.filter(r => !r.is_parent || qnum !== 2);
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
