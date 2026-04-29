# Shareholder Intelligence — Style Guide

Dark, cinematic, institutional investment-bank aesthetic. Near-black ground, white type, geometric sans, minimal warm gold accent, large display numbers, generous whitespace, restrained color.

---

## Fonts

Import from Google Fonts:

```
Hanken Grotesk: 300, 400, 500, 600, 700
Inter: 400, 500, 600, 700
JetBrains Mono: 400, 500, 600, 700
```

| Role | Font | Fallbacks |
|------|------|-----------|
| **Display** (headings, section titles, labels) | Hanken Grotesk | Inter, -apple-system, system-ui, sans-serif |
| **Sans** (body, UI controls, buttons) | Inter | -apple-system, system-ui, sans-serif |
| **Mono** (numbers, data, tickers, stats) | JetBrains Mono | SF Mono, Menlo, monospace |

---

## Color Tokens

### Backgrounds

| Token | Value | Usage |
|-------|-------|-------|
| `bg` | `#0c0c0e` | Page / app background |
| `panel` | `#131316` | Cards, panels, dropdowns |
| `panelHi` | `#1a1a1f` | Hover state on panels/rows |
| `card` | `#18181c` | Elevated card surfaces |
| `header` | `#000000` | Top bar, sidebar, modal headers |

### Borders / Lines

| Token | Value | Usage |
|-------|-------|-------|
| `line` | `#28282e` | Primary borders, dividers |
| `lineSoft` | `#1e1e24` | Subtle row separators |

### Text

| Token | Value | Usage |
|-------|-------|-------|
| `white` | `#ffffff` | Headings, strong emphasis |
| `text` | `#e8e8ec` | Primary body text |
| `textDim` | `#9a9aa6` | Secondary / descriptive text |
| `textMute` | `#5c5c68` | Tertiary, disabled, placeholders |

### Accent — Warm Gold (use sparingly)

| Token | Value | Usage |
|-------|-------|-------|
| `gold` | `#c5a254` | Primary accent: active nav, selected controls, tickers, kicker labels |
| `goldDim` | `#7a6433` | Muted gold for secondary accents |
| `goldSoft` | `rgba(197,162,84,0.08)` | Gold tint backgrounds (active nav item, selected row) |

### Semantic

| Token | Value | Usage |
|-------|-------|-------|
| `pos` | `#5cb87a` | Positive values, buyers, upward trends |
| `neg` | `#e05a5a` | Negative values, sellers, downward trends |
| `posSoft` | `rgba(92,184,122,0.08)` | Green tint background |
| `negSoft` | `rgba(224,90,90,0.08)` | Red tint background |

### Category Colors (for badges/tags)

| Category | Foreground | Background |
|----------|-----------|------------|
| Passive / Index / ETF | `#7aadde` | `rgba(92,140,200,0.12)` |
| Active | `#5cb87a` | `rgba(92,184,122,0.08)` |
| Hedge Fund | `#e05a5a` | `rgba(224,90,90,0.08)` |
| Bank / Sector | `#c5a254` | `rgba(197,162,84,0.08)` |
| Sovereign | `#b09ee0` | `rgba(160,130,220,0.12)` |
| Default / Allocation | `#9a9aa6` | `rgba(255,255,255,0.05)` |

---

## Typography Scale

| Element | Font | Size | Weight | Letter-spacing | Extras |
|---------|------|------|--------|----------------|--------|
| Page title / app name | Display | 12px | 700 | 0.16em | uppercase |
| Section title | Display | 14px | 500 | — | — |
| Kicker / label above data | Display | 9px | 700 | 0.16em | uppercase |
| Body text | Sans | 13px | 400 | 0.02em | — |
| Secondary text | Sans | 11–12px | 400 | 0.04em | — |
| Button / control text | Sans | 10–11px | 500–700 | 0.06em | uppercase |
| Large display number | Mono | 24px | 400 | -0.01em | — |
| Data / stat value | Mono | 11–13px | 500–600 | 0.06–0.08em | — |
| Tiny label (inside charts) | Mono | 10px | 400 | 0.06em | uppercase |

---

## Spacing & Density

- **Panel padding:** 16–18px
- **Row padding (comfortable):** 8px 12px
- **Row padding (compact):** 4px 12px
- **Gap between elements:** 8–16px (tight)
- **Sidebar width:** 220px
- **Header height:** 48px

---

## Border Radius

Almost none. The aesthetic is sharp and geometric.

| Element | Radius |
|---------|--------|
| Badges / tags | 1px |
| Tweaks panel | 2px |
| Scrollbar thumb | 3px |
| Status dot | 99px (circle) |
| Everything else | 0px |

---

## Shadows

Minimal — only on floating elements:

| Element | Shadow |
|---------|--------|
| Dropdowns, tooltips, modals | `0 12px 40px rgba(0,0,0,0.5)` |
| Tweaks panel | `0 12px 40px rgba(0,0,0,0.6)` |
| Everything else | none |

---

## Interactive States

### Hover
- Rows/list items: background changes to `panelHi` (`#1a1a1f`)
- Transition: `all 0.12s`

### Selected / Active
- Segmented controls: `gold` background + `#000` text, weight 700
- Unselected: transparent background + `textDim` text, weight 400–500
- Nav items: `goldSoft` background + `white` text + `2px solid gold` left border
- Inactive nav: transparent + `textDim` text + `2px solid transparent` left border

### Table Rows
- Striped (optional): alternating rows at `rgba(255,255,255,0.015)`
- Borders: `1px solid lineSoft` between rows
- Expandable rows: gold `▶` indicator that rotates 90° on expand
- Expanded child rows: `rgba(197,162,84,0.03)` background + `2px solid gold` left border

---

## Controls

### Segmented Buttons
- No border-radius
- `1px solid line` border (adjacent segments share borders via `borderLeft: none`)
- Selected: `gold` fill, `#000` text, weight 700
- Unselected: transparent, `textDim` text, weight 400

### Text Inputs
- Background: `bg` (`#0c0c0e`)
- Border: `1px solid line`
- Text color: `text` or `white`
- Font: Sans, 11–13px
- No border-radius, no outline on focus

### Badges / Tags
- Inline-block, 2px 8px padding (small: 1px 6px)
- 9–10px, weight 600, uppercase, 0.06em spacing
- Border-radius: 1px
- Colored per category (see Category Colors above)

---

## Scrollbar

```css
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #131316; }
::-webkit-scrollbar-thumb { background: #28282e; border-radius: 3px; }
```

---

## General Principles

1. **Dark-first.** All surfaces are near-black. No light mode.
2. **Gold is the only accent.** Use it for interactive highlights, active states, kicker labels. Never for large fills.
3. **Green and red are semantic only.** Positive/negative values, buyer/seller. Never decorative.
4. **Monospace for all numbers.** Prices, percentages, counts, stats — always JetBrains Mono.
5. **Uppercase sparingly but consistently.** Kickers, nav section headers, badge labels, button text. Never body text.
6. **Sharp edges.** No rounded corners except status dots. The look is architectural, not friendly.
7. **Minimal transitions.** 0.12s for hovers and state changes. No bouncing, no spring physics.
8. **Generous whitespace.** Let elements breathe despite the dark palette.
