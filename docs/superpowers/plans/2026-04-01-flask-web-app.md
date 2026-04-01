# Flask Web Application — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Jupyter notebook with a Flask web app for browser-based 13F ownership research.

**Architecture:** Flask backend with DuckDB read-only connections, vanilla HTML/CSS/JS frontend. All 15 queries ported from research.ipynb as separate API endpoints. Single-page app with tab navigation.

**Tech Stack:** Flask, DuckDB, openpyxl, pandas, vanilla HTML/CSS/JS

---

## Session 1 Scope (this session)

Backend (app.py), frontend shell (index.html, style.css, app.js), Query 1-3 rendering, Excel export, startup script, deployment files.

## Session 2-3 Scope (future)

Queries 4-15, polish, autocomplete refinement, mobile testing.

---

## File Structure

```
scripts/
  app.py              ← Flask application (all API endpoints, query functions)
  start_app.sh         ← Startup script
web/
  templates/
    index.html         ← Main SPA template
  static/
    style.css          ← All styles
    app.js             ← Frontend logic (fetch, render, tabs, export)
render.yaml            ← Render.com deployment
Procfile               ← Heroku-style process file
README_deploy.md       ← Deployment instructions (update existing)
requirements.txt       ← Add flask
```

---

### Task 1: Flask Backend — Core Setup + Query Functions

**Files:**
- Create: `scripts/app.py`

- [ ] **Step 1: Write app.py with Flask setup, DuckDB helper, and all 15 query functions**

Core structure:
- `get_db()` — opens read-only DuckDB connection per request
- `get_cusip(ticker)` — resolves ticker to CUSIP
- `query1(ticker)` through `query15(ticker)` — each returns list of dicts
- API routes: `/api/tickers`, `/api/query1?ticker=AR` through `/api/query15`, `/api/summary?ticker=AR`
- Export routes: `/api/export/query1?ticker=AR` through `/api/export/query15`
- `--port` CLI flag defaulting to 8001
- Startup banner

All 15 queries ported exactly from research.ipynb. Query 7 uses CIK instead of ticker — accept both `?ticker=` and `?cik=` params.

- [ ] **Step 2: Verify app starts**

```bash
python3 scripts/app.py &
sleep 2
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add scripts/app.py
git commit -m "feat: Flask backend with all 15 query endpoints"
```

---

### Task 2: Frontend — HTML Shell + CSS + JavaScript

**Files:**
- Create: `web/templates/index.html`
- Create: `web/static/style.css`
- Create: `web/static/app.js`

- [ ] **Step 1: Write index.html** — header with ticker search, summary card, tab bar (15 tabs), results container

- [ ] **Step 2: Write style.css** — Oxford Blue (#002147), Glacier Blue (#4A90D9), Sandstone (#C9B99A), table styling, tab styling, color coding for manager types

- [ ] **Step 3: Write app.js** — ticker autocomplete, tab switching, fetch + render tables, copy to clipboard, Excel export trigger, column sorting, number formatting

- [ ] **Step 4: Commit**

```bash
git add web/templates/index.html web/static/style.css web/static/app.js
git commit -m "feat: frontend SPA with tabs, autocomplete, table rendering"
```

---

### Task 3: Excel Export Endpoint

**Files:**
- Modify: `scripts/app.py`

- [ ] **Step 1: Add openpyxl export** — `/api/export/queryN?ticker=AR` generates formatted .xlsx with Oxford Blue headers, alternating rows, auto-fit columns, proper number formatting

- [ ] **Step 2: Commit**

```bash
git add scripts/app.py
git commit -m "feat: Excel export with formatted .xlsx downloads"
```

---

### Task 4: Startup Script + Deployment Files

**Files:**
- Create: `scripts/start_app.sh`
- Create: `render.yaml`
- Create: `Procfile`
- Modify: `requirements.txt`

- [ ] **Step 1: Create start_app.sh, render.yaml, Procfile**
- [ ] **Step 2: Update requirements.txt to add flask**
- [ ] **Step 3: Update README.md with web interface section**
- [ ] **Step 4: Commit**

```bash
git add scripts/start_app.sh render.yaml Procfile requirements.txt README.md
git commit -m "feat: startup script, Render deployment config"
```

---

### Task 5: Smoke Test

- [ ] **Step 1: Start app, verify it loads, kill it**

```bash
python3 scripts/app.py &
sleep 2
curl -s http://localhost:8001/ | head -5
curl -s http://localhost:8001/api/tickers | head -5
kill %1
```

Report results.
