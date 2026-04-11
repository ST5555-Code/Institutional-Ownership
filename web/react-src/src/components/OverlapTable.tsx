import { useMemo } from 'react'
import { AgGridReact } from 'ag-grid-react'
import {
  ColGroupDef,
  ColDef,
  RowClassParams,
  ICellRendererParams,
  CellStyle,
} from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'
import { OverlapRow } from '../types/overlap'

interface Props {
  rows: OverlapRow[]
  subjectTicker: string
  secondTicker: string
  hasSecond: boolean
  type: 'inst' | 'fund'
  activeOnly: boolean
}

// Row type extension used for pinned bottom totals rows. rowPinned is the
// authoritative AG Grid signal for pinned rows; the _isTotal flag is kept
// only as a belt-and-braces marker on the row data itself.
type TotalRow = OverlapRow & { _isTotal?: boolean }

// ── locked width spec ─────────────────────────────────────────────────────
// Widened for NVDA-class dollar values ($300B = "$300,000" in millions,
// 7 chars + $ + padding → needs ~110px minimum). Holder column narrowed
// slightly to compensate. Page-level horizontal scroll may appear on
// narrow viewports — that's expected and matches "move fund right".
const W_RANK    = 36
const W_NAME    = 240
const W_PCT     = 82
const W_SPACER  = 14
const W_DOL     = 115
const W_TRAIL   = 5
// Total = 36 + 240 + 82 + 82 + 14 + 115 + 115 + 5 = 689px per table

// ── locked height spec ────────────────────────────────────────────────────
// With domLayout="autoHeight" the grid sizes itself to the sum of its
// header + body rows + pinned rows — no outer container height, no vertical
// scroll viewport, no internal scrollbar tracks.
const GROUP_HEADER_H = 28
const TICKER_HEADER_H = 28
const ROW_H = 32

function hasSecShares(row: OverlapRow): boolean {
  return row.sec_shares != null && row.sec_shares > 0
}

function fmtPct(val: number | null | undefined, ok: boolean): string {
  if (val == null || !ok) return '—'
  return val.toFixed(2) + '%'
}

function fmtDollars(val: number | null | undefined): string {
  if (val == null || val === 0) return '—'
  return '$' + Math.round(val / 1e6).toLocaleString('en-US')
}

export function OverlapTable({
  rows,
  subjectTicker,
  secondTicker,
  hasSecond,
  type,
  activeOnly,
}: Props) {
  // Apply Active-Only filter at the table level. Institutional = exclude
  // manager_type='passive'. Fund = keep rows flagged is_active===true.
  const filtered = useMemo(() => {
    if (!activeOnly) return rows
    if (type === 'inst') {
      return rows.filter(r => r.manager_type !== 'passive')
    }
    return rows.filter(r => r.is_active === true)
  }, [rows, activeOnly, type])

  const display = filtered.slice(0, 15)

  // Pinned bottom: Top 15 and Top 25 totals, computed against the filtered
  // set so the visible totals line up with the visible body rows.
  const pinnedBottom = useMemo<TotalRow[]>(() => {
    return [15, 25].map((n): TotalRow => {
      const slice = filtered.slice(0, n)
      return {
        holder: `Top ${n} Total`,
        _isTotal: true,
        is_overlap: false,
        subj_shares: 0,
        subj_pct_float: slice.reduce((a, r) => a + (r.subj_pct_float || 0), 0),
        subj_dollars: slice.reduce((a, r) => a + (r.subj_dollars || 0), 0),
        sec_shares: hasSecond ? 1 : null,
        sec_pct_float: hasSecond
          ? slice.reduce((a, r) => a + (hasSecShares(r) ? (r.sec_pct_float || 0) : 0), 0)
          : null,
        sec_dollars: hasSecond
          ? slice.reduce((a, r) => a + (r.sec_dollars || 0), 0)
          : null,
      }
    })
  }, [filtered, hasSecond])

  const colDefs = useMemo<(ColDef<TotalRow> | ColGroupDef<TotalRow>)[]>(() => {
    // Common flags for every column: fixed size, immovable, non-sortable.
    const fixed = {
      sortable: false as const,
      resizable: false as const,
      suppressMovable: true as const,
      suppressSizeToFit: true as const,
    }

    // Empty spacer column factory — no header, no field, no renderer.
    const spacer = (colId: string, w: number): ColDef<TotalRow> => ({
      colId,
      headerName: '',
      width: w,
      minWidth: w,
      maxWidth: w,
      ...fixed,
      cellStyle: { backgroundColor: 'transparent' } as CellStyle,
    })

    return [
      {
        colId: 'rank',
        headerName: '#',
        width: W_RANK,
        minWidth: W_RANK,
        maxWidth: W_RANK,
        ...fixed,
        cellStyle: { textAlign: 'center', color: '#888', fontSize: '12px' } as CellStyle,
        cellRenderer: (params: ICellRendererParams<TotalRow>) => {
          if (params.node.rowPinned) return ''
          return params.node.rowIndex != null ? String(params.node.rowIndex + 1) : ''
        },
      },
      {
        colId: 'name',
        headerName: type === 'inst' ? 'Holder' : 'Fund',
        field: 'holder',
        width: W_NAME,
        minWidth: W_NAME,
        maxWidth: W_NAME,
        ...fixed,
        cellStyle: {
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: '12px',
        } as CellStyle,
        tooltipField: 'holder',
        cellRenderer: (params: ICellRendererParams<TotalRow>) => {
          const v = (params.value as string) || '—'
          if (params.node.rowPinned) {
            return <span style={{ fontWeight: 600 }}>{v}</span>
          }
          return v
        },
      },
      {
        headerName: '% Owned',
        headerClass: 'tco-group-header',
        marryChildren: true,
        children: [
          {
            colId: 'pct_subj',
            headerName: subjectTicker || 'Subject',
            field: 'subj_pct_float',
            width: W_PCT,
            minWidth: W_PCT,
            maxWidth: W_PCT,
            ...fixed,
            cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
            cellRenderer: (p: ICellRendererParams<TotalRow>) => {
              const val = p.value as number | null
              const v = p.node.rowPinned
                ? (val != null ? val.toFixed(2) + '%' : '—')
                : fmtPct(val, true)
              if (p.node.rowPinned) {
                return <span style={{ fontWeight: 600 }}>{v}</span>
              }
              return v
            },
          },
          {
            colId: 'pct_sec',
            headerName: secondTicker || (hasSecond ? 'Second' : '—'),
            field: 'sec_pct_float',
            width: W_PCT,
            minWidth: W_PCT,
            maxWidth: W_PCT,
            ...fixed,
            cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
            cellRenderer: (p: ICellRendererParams<TotalRow>) => {
              if (!hasSecond) return '—'
              const val = p.value as number | null
              const v = p.node.rowPinned
                ? (val != null && val > 0 ? val.toFixed(2) + '%' : '—')
                : fmtPct(val, p.data ? hasSecShares(p.data) : false)
              if (p.node.rowPinned) {
                return <span style={{ fontWeight: 600 }}>{v}</span>
              }
              return v
            },
          },
        ],
      },
      spacer('spacer_mid', W_SPACER),
      {
        headerName: 'Value ($M)',
        headerClass: 'tco-group-header',
        marryChildren: true,
        children: [
          {
            colId: 'dol_subj',
            headerName: subjectTicker || 'Subject',
            field: 'subj_dollars',
            width: W_DOL,
            minWidth: W_DOL,
            maxWidth: W_DOL,
            ...fixed,
            cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
            cellRenderer: (p: ICellRendererParams<TotalRow>) => {
              const v = fmtDollars(p.value as number | null)
              if (p.node.rowPinned) {
                return <span style={{ fontWeight: 600 }}>{v}</span>
              }
              return v
            },
          },
          {
            colId: 'dol_sec',
            headerName: secondTicker || (hasSecond ? 'Second' : '—'),
            field: 'sec_dollars',
            width: W_DOL,
            minWidth: W_DOL,
            maxWidth: W_DOL,
            ...fixed,
            cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
            cellRenderer: (p: ICellRendererParams<TotalRow>) => {
              if (!hasSecond) return '—'
              const v = fmtDollars(p.value as number | null)
              if (p.node.rowPinned) {
                return <span style={{ fontWeight: 600 }}>{v}</span>
              }
              return v
            },
          },
        ],
      },
      spacer('spacer_trail', W_TRAIL),
    ]
  }, [subjectTicker, secondTicker, hasSecond, type])

  const rowClassRules = useMemo(() => ({
    'tco-overlap-row': (params: RowClassParams<TotalRow>) => {
      return !params.node.rowPinned && !!(params.data as OverlapRow)?.is_overlap
    },
  }), [])

  return (
    <div className="ag-theme-alpine" style={{ width: '100%' }}>
      <AgGridReact<TotalRow>
        theme="legacy"
        rowData={display}
        columnDefs={colDefs}
        pinnedBottomRowData={pinnedBottom}
        rowClassRules={rowClassRules}
        suppressMovableColumns
        suppressColumnVirtualisation
        headerHeight={TICKER_HEADER_H}
        groupHeaderHeight={GROUP_HEADER_H}
        rowHeight={ROW_H}
        suppressHorizontalScroll={true}
        tooltipShowDelay={200}
        domLayout="autoHeight"
      />
    </div>
  )
}
