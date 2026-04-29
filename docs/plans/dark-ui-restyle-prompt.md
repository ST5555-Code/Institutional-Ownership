# Claude Code Prompt — Dark UI Restyle

## Objective

Restyle the entire React front-end of the 13F Ownership app to match the design system in `docs/plans/DarkStyle.md`. The current UI has a dark sidebar/header shell but a **light content area** (white cards, light borders, dark text). The target is a fully dark, cinematic, institutional aesthetic — near-black surfaces throughout, white/light type, warm gold accent, monospace numbers.

**Read `docs/plans/DarkStyle.md` first.** It is the single source of truth for every color, font, spacing, and interaction pattern. This prompt maps the current codebase to that spec.

---

## Step 1 — CSS Variables (`web/react-app/src/styles/globals.css`)

Replace the existing `:root` block and body styles with:

```css
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@300;400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  /* Backgrounds */
  --bg:        #0c0c0e;
  --panel:     #131316;
  --panel-hi:  #1a1a1f;
  --card:      #18181c;
  --header:    #000000;

  /* Borders */
  --line:      #28282e;
  --line-soft: #1e1e24;

  /* Text */
  --white:     #ffffff;
  --text:      #e8e8ec;
  --text-dim:  #9a9aa6;
  --text-mute: #5c5c68;

  /* Accent — warm gold */
  --gold:      #c5a254;
  --gold-dim:  #7a6433;
  --gold-soft: rgba(197,162,84,0.08);

  /* Semantic */
  --pos:       #5cb87a;
  --neg:       #e05a5a;
  --pos-soft:  rgba(92,184,122,0.08);
  --neg-soft:  rgba(224,90,90,0.08);

  /* Legacy aliases (remove after full sweep) */
  --shell-bg:      var(--bg);
  --sidebar-bg:    var(--header);
  --sidebar-active: var(--panel-hi);
  --accent-gold:   var(--gold);
  --content-bg:    var(--bg);
  --card-bg:       var(--panel);
  --oxford-blue:   var(--header);
  --glacier-blue:  #4A90D9;
  --sandstone:     var(--gold);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background-color: var(--bg);
  color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  letter-spacing: 0.02em;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--panel); }
::-webkit-scrollbar-thumb { background: var(--line); border-radius: 3px; }
```

---

## Step 2 — Shell Components

### `components/shell/Header.tsx`

| Property | Old | New |
|---|---|---|
| `backgroundColor` | `var(--oxford-blue)` | `var(--header)` |
| `borderBottom` | `1px solid #1e2d47` | `1px solid var(--line)` |
| App name `color` | `#ffffff` | `var(--gold)` |
| App name `fontFamily` | (default) | `'Hanken Grotesk', sans-serif` |
| App name `letterSpacing` | `0.05em` | `0.16em` |
| App name `textTransform` | none | `uppercase` |
| App name `fontSize` | `14px` | `12px` |

### `components/shell/Sidebar.tsx`

| Property | Old | New |
|---|---|---|
| `backgroundColor` | `var(--sidebar-bg)` | `var(--header)` |
| `borderRight` | `1px solid #1e2d47` | `1px solid var(--line)` |
| `width` | `200px` | `220px` |
| `minWidth` | `200px` | `220px` |

### `components/shell/SidebarSection.tsx`

| Property | Old | New |
|---|---|---|
| `color` | `var(--accent-gold)` | `var(--gold)` |
| `fontSize` | `10px` | `9px` |
| `letterSpacing` | `0.08em` | `0.16em` |
| `fontFamily` | (default) | `'Hanken Grotesk', sans-serif` |

### `components/shell/SidebarItem.tsx`

| Property | Old (active) | New (active) |
|---|---|---|
| `backgroundColor` | `var(--sidebar-active)` | `var(--gold-soft)` |
| `borderLeft` | `3px solid var(--accent-gold)` | `2px solid var(--gold)` |
| `color` | `#ffffff` | `var(--white)` |

| Property | Old (inactive) | New (inactive) |
|---|---|---|
| `backgroundColor` | `transparent` | `transparent` |
| `borderLeft` | `3px solid transparent` | `2px solid transparent` |
| `color` | `#94a3b8` | `var(--text-dim)` |

Also add: `transition: 'all 0.12s'` (replace the two separate transitions).

### `components/shell/AppShell.tsx`

In `<main>`:
| Property | Old | New |
|---|---|---|
| `backgroundColor` | `var(--content-bg)` | `var(--bg)` |

---

## Step 3 — Common Components (apply token mapping)

### `components/common/typeConfig.ts` — Badge Category Colors

Replace `TYPE_CONFIG` with the DarkStyle category palette. Badges should use **translucent backgrounds with colored foreground text** instead of solid fills:

```typescript
export const TYPE_CONFIG: Record<string, TypeStyle> = {
  passive:            { label: 'passive',       bg: 'rgba(92,140,200,0.12)',  color: '#7aadde' },
  active:             { label: 'active',        bg: 'rgba(92,184,122,0.08)',  color: '#5cb87a' },
  hedge_fund:         { label: 'quant/hedge',   bg: 'rgba(224,90,90,0.08)',   color: '#e05a5a' },
  quantitative:       { label: 'quantitative',  bg: 'rgba(224,90,90,0.08)',   color: '#e05a5a' },
  wealth_management:  { label: 'wealth mgmt',   bg: 'rgba(197,162,84,0.08)',  color: '#c5a254' },
  family_office:      { label: 'family office', bg: 'rgba(197,162,84,0.08)',  color: '#c5a254' },
  pension_insurance:  { label: 'pension',        bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
  mixed:              { label: 'mixed',          bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' },
  strategic:          { label: 'strategic',      bg: 'rgba(197,162,84,0.08)', color: '#c5a254' },
  activist:           { label: 'activist',       bg: 'rgba(224,90,90,0.08)',  color: '#e05a5a' },
  private_equity:     { label: 'PE',             bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
  venture_capital:    { label: 'VC',             bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
  endowment_foundation: { label: 'endowment',   bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' },
  market_maker:       { label: 'market maker',  bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' },
  SWF:                { label: 'sovereign',      bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
}

const FALLBACK: TypeStyle = { label: '', bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' }
```

Also: badge `borderRadius` should be `1px` everywhere (currently `3` in RegisterTab).

### `components/common/QuarterSelector.tsx` — Segmented Buttons

Replace with DarkStyle segmented control pattern:

| State | Old `backgroundColor` | New `backgroundColor` |
|---|---|---|
| Active | `var(--oxford-blue)` | `var(--gold)` |
| Inactive | `#ffffff` | `transparent` |

| State | Old `color` | New `color` |
|---|---|---|
| Active | `#ffffff` | `#000000` |
| Inactive | `#64748b` | `var(--text-dim)` |

| State | Old `border` | New `border` |
|---|---|---|
| Active | `1px solid var(--oxford-blue)` | `1px solid var(--line)` |
| Inactive | `1px solid #e2e8f0` | `1px solid var(--line)` |

Active `fontWeight`: `700`. Inactive: `400`. `borderRadius`: `0`. Adjacent buttons: first child keeps all borders; subsequent children use `borderLeft: 'none'` to share edges.

### `components/common/RollupToggle.tsx`

Same segmented pattern as QuarterSelector. Replace:
- Container `backgroundColor: '#0d1526'` → `transparent`, remove `borderRadius: 6`
- Active: `var(--accent-gold)` bg, `#0a0f1e` text → `var(--gold)` bg, `#000` text, weight `700`
- Inactive: `#1a2a4a` bg, `#94a3b8` text → `transparent` bg, `var(--text-dim)` text, weight `400`
- `borderRadius: 4` → `0`
- Add `border: '1px solid var(--line)'` on each button; adjacent buttons `borderLeft: 'none'`
- Label `color: '#94a3b8'` → `var(--text-dim)`
- Label `fontFamily` → `'Hanken Grotesk', sans-serif`

### `components/common/FundViewToggle.tsx`

Same segmented pattern. Replace:
- Container: `backgroundColor: '#ffffff'` → `transparent`, `border: '1px solid #e2e8f0'` → remove, `borderRadius: 6` → remove
- Active: `var(--oxford-blue)` bg → `var(--gold)` bg, `#ffffff` text → `#000` text
- Inactive: `#f4f6f9` bg → `transparent`, `#64748b` text → `var(--text-dim)`
- `borderRadius: 4` → `0`
- Add `border: '1px solid var(--line)'` on each button; adjacent `borderLeft: 'none'`

### `components/common/ActiveOnlyToggle.tsx`

- Track on: `var(--glacier-blue)` → `var(--gold)`
- Track off: `#2d3f5e` → `var(--line)`
- Label `color: '#94a3b8'` → `var(--text-dim)`

### `components/common/InvestorTypeFilter.tsx`

Replace chip styles:
- `CHIP_BASE.border`: `1px solid #e2e8f0` → `1px solid var(--line)`
- `CHIP_BASE.borderRadius`: `12` → `1`
- Unselected `backgroundColor`: `#ffffff` → `transparent`
- Unselected `color`: `#94a3b8` → `var(--text-dim)`
- Unselected `borderColor`: `#e2e8f0` → `var(--line)`
- Selected: keep colored backgrounds but use the DarkStyle category colors (translucent fills + colored text), `borderColor` matching the category color
- "All" button active: `var(--oxford-blue)` bg → `var(--gold)` bg, text `#000`

### `components/common/FreshnessBadge.tsx`

Replace the `PALETTE` with dark-compatible colors:
```typescript
const PALETTE: Record<Status, { bg: string; fg: string; label: string }> = {
  fresh: { bg: 'rgba(92,184,122,0.08)',  fg: '#5cb87a', label: 'Fresh' },
  amber: { bg: 'rgba(197,162,84,0.08)',  fg: '#c5a254', label: 'Stale' },
  red:   { bg: 'rgba(224,90,90,0.08)',   fg: '#e05a5a', label: 'Stale' },
  never: { bg: 'rgba(255,255,255,0.05)', fg: '#5c5c68', label: 'No data' },
}
```
`borderRadius: 10` → `1`.

### `components/common/ExportBar.tsx`

- Excel button `backgroundColor: '#27AE60'` → `var(--pos)` (`#5cb87a`)
- Print button `backgroundColor: '#475569'` → `var(--line)` (`#28282e`), `color: '#ffffff'` → `var(--text-dim)`

### `components/common/ColumnGroupHeader.tsx`

- `bg` (dark): `var(--oxford-blue)` → `var(--header)`
- `text` (dark): `#ffffff` → `var(--white)`
- `borderBottom`: `2px solid var(--sandstone)` → `2px solid var(--gold)`

---

## Step 4 — Table Styles (apply across ALL 12 tab files)

Every tab file defines inline `TH_STYLE`, `TD_STYLE`, `TH_RIGHT`, `TD_RIGHT` (or equivalent) constants. Apply these mappings uniformly:

### Table Headers (`TH_STYLE` / `TH_RIGHT`)

| Property | Old | New |
|---|---|---|
| `color` | `#ffffff` | `var(--text-dim)` |
| `backgroundColor` | `var(--oxford-blue)` | `var(--header)` |
| `borderBottom` | `1px solid #1e2d47` | `1px solid var(--line)` |
| `fontSize` | `11` | `9` |
| `letterSpacing` | `0.04em` | `0.16em` |
| `fontFamily` | (default) | `'Hanken Grotesk', sans-serif` |

### Table Body Cells (`TD_STYLE` / `TD_RIGHT`)

| Property | Old | New |
|---|---|---|
| `color` | `#1e293b` | `var(--text)` |
| `borderBottom` | `1px solid #e5e7eb` | `1px solid var(--line-soft)` |

Numeric cells (`TD_RIGHT` and any right-aligned data): add `fontFamily: "'JetBrains Mono', monospace"`.

### Table Row Hover

Add `onMouseEnter`/`onMouseLeave` (or a shared `<HoverRow>` wrapper) to set `backgroundColor` to `var(--panel-hi)` on hover, `transparent` on leave. Transition: `all 0.12s`.

### Expandable Child Rows

Where child rows exist (Register, Conviction, etc.):
- Child row background: `rgba(197,162,84,0.03)` (the `--gold-soft` but even more subtle)
- Left border on first cell: `2px solid var(--gold)`
- Expand indicator: gold `▶` that rotates 90° on expand

### Negative Values

Keep the existing red-parentheses pattern but use `var(--neg)` (`#e05a5a`) instead of `#c0392b` / `#c53030`.

### N-PORT Coverage Badge Colors

Replace the `nportBadgeStyle` function in RegisterTab (and any tab that uses it):
- `>= 80`: `bg: var(--pos-soft)`, `color: var(--pos)`
- `>= 50`: `bg: var(--gold-soft)`, `color: var(--gold)`
- `< 50`: `bg: rgba(255,255,255,0.05)`, `color: var(--text-dim)`

---

## Step 5 — Card / Panel Containers

Many tabs wrap content in a `div` with `backgroundColor: '#ffffff'` or `var(--card-bg)`, `border: '1px solid #e5e7eb'`, `borderRadius: 8`. Replace everywhere:

| Property | Old | New |
|---|---|---|
| `backgroundColor` | `#ffffff` / `var(--card-bg)` | `var(--panel)` |
| `border` | `1px solid #e5e7eb` / `1px solid #e2e8f0` | `1px solid var(--line)` |
| `borderRadius` | `8` / `6` / `4` | `0` |

---

## Step 6 — Loading / Empty States

Replace any `color: '#94a3b8'` or `color: '#64748b'` in loading/empty-state text with `var(--text-mute)`.
Replace any `color: '#475569'` used for secondary body text with `var(--text-dim)`.

---

## Step 7 — TableFooter.tsx

| Property | Old | New |
|---|---|---|
| `color` | `#ffffff` | `var(--white)` |
| `backgroundColor` | `var(--oxford-blue)` | `var(--header)` |
| `borderTop` | `2px solid var(--oxford-blue)` | `2px solid var(--gold)` |

---

## Step 8 — Header Components

### `components/header/TickerInput.tsx`

Apply DarkStyle text input spec:
- `background`: `var(--bg)`
- `border`: `1px solid var(--line)`
- `color`: `var(--white)` or `var(--text)`
- `borderRadius`: `0`
- Placeholder color: `var(--text-mute)`

### `components/header/CompanyCard.tsx`

- Company name: `color: var(--white)`, `fontFamily: 'Hanken Grotesk'`, `fontWeight: 600`
- Secondary info (sector, exchange): `color: var(--text-dim)`
- Price / market cap numbers: `fontFamily: 'JetBrains Mono'`

---

## Files to Modify (complete list)

```
web/react-app/src/styles/globals.css
web/react-app/src/components/shell/AppShell.tsx
web/react-app/src/components/shell/Header.tsx
web/react-app/src/components/shell/Sidebar.tsx
web/react-app/src/components/shell/SidebarSection.tsx
web/react-app/src/components/shell/SidebarItem.tsx
web/react-app/src/components/header/TickerInput.tsx
web/react-app/src/components/header/CompanyCard.tsx
web/react-app/src/components/common/typeConfig.ts
web/react-app/src/components/common/QuarterSelector.tsx
web/react-app/src/components/common/RollupToggle.tsx
web/react-app/src/components/common/FundViewToggle.tsx
web/react-app/src/components/common/ActiveOnlyToggle.tsx
web/react-app/src/components/common/InvestorTypeFilter.tsx
web/react-app/src/components/common/FreshnessBadge.tsx
web/react-app/src/components/common/ExportBar.tsx
web/react-app/src/components/common/ColumnGroupHeader.tsx
web/react-app/src/components/common/TableFooter.tsx
web/react-app/src/components/tabs/RegisterTab.tsx
web/react-app/src/components/tabs/OwnershipTrendTab.tsx
web/react-app/src/components/tabs/FlowAnalysisTab.tsx
web/react-app/src/components/tabs/ConvictionTab.tsx
web/react-app/src/components/tabs/FundPortfolioTab.tsx
web/react-app/src/components/tabs/CrossOwnershipTab.tsx
web/react-app/src/components/tabs/PeerRotationTab.tsx
web/react-app/src/components/tabs/OverlapAnalysisTab.tsx
web/react-app/src/components/tabs/SectorRotationTab.tsx
web/react-app/src/components/tabs/ShortInterestTab.tsx
web/react-app/src/components/tabs/DataSourceTab.tsx
web/react-app/src/components/tabs/EntityGraphTab.tsx
web/templates/admin.html
```

## Rules

1. **Do NOT change any API calls, data logic, state management, or business logic.** This is a visual-only restyle.
2. **Do NOT rename components, props, or exports.**
3. **Do NOT delete any files.**
4. **Preserve all existing functionality** — collapsible rows, tooltips, sorting, filtering, export, print.
5. **Use CSS variables** from `:root` wherever possible. Inline hex only for category badge colors and semantic pos/neg where CSS vars are not practical.
6. **Font stacks:** Display headings/labels → `'Hanken Grotesk', sans-serif`. Body/UI → `'Inter', sans-serif`. Numbers/data → `'JetBrains Mono', monospace`.
7. **Border radius:** `0px` everywhere except status dots (`50%`) and scrollbar thumb (`3px`). Badges: `1px`.
8. **Build and test** after all changes: `cd web/react-app && npm run build`. Fix any TypeScript or build errors before committing.
9. **Single branch:** `dark-ui-restyle`. Commit all changes together. Push and open PR. Do not merge.
10. After build succeeds, start the app (`./scripts/start_app.sh`) and visually verify at least: Register tab, Conviction tab, Flow Analysis tab, Sidebar navigation, and header.

## Global Find-Replace Cheat Sheet

These hex values appear across multiple files. Search-and-replace them project-wide within `web/react-app/src/`:

| Old Value | New Value | Context |
|---|---|---|
| `#1e293b` | `var(--text)` | Body text color |
| `#e5e7eb` | `var(--line-soft)` | Row borders |
| `#e2e8f0` | `var(--line)` | Control borders |
| `#94a3b8` | `var(--text-dim)` | Secondary/label text |
| `#64748b` | `var(--text-dim)` | Secondary text alternate |
| `#475569` | `var(--text-mute)` | Tertiary text |
| `#ffffff` (as background) | `var(--panel)` | Card/panel backgrounds |
| `#f4f6f9` | `var(--bg)` | Content area background |
| `#c0392b` / `#c53030` | `var(--neg)` | Negative value red |
| `#27AE60` / `#27ae60` | `var(--pos)` | Positive value green |
| `#1e2d47` | `var(--line)` | Dark-mode borders |
| `#2d3f5e` | `var(--line)` | Scrollbar / subtle borders |
