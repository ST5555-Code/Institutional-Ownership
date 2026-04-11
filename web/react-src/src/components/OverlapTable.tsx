import { useMemo } from 'react'
import { AgGridReact } from 'ag-grid-react'
import {
  ColGroupDef,
  ColDef,
  RowClassParams,
  ICellRendererParams,
  ValueFormatterParams,
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
}

// Row type extension used for pinned bottom totals rows so the renderer
// can branch on whether it's a body row or a total row.
type TotalRow = OverlapRow & { _isTotal?: boolean }

// Height constants — kept in one place so the grid container's fixed
// height stays in sync with headerHeight/groupHeaderHeight/rowHeight.
const HEADER_HEIGHT = 28       // group header row
const SUBHEADER_HEIGHT = 28    // ticker row
const ROW_HEIGHT = 32
const DATA_ROWS = 15
const PINNED_ROWS = 2
const GRID_HEIGHT =
  HEADER_HEIGHT + SUBHEADER_HEIGHT + (DATA_ROWS + PINNED_ROWS) * ROW_HEIGHT

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

export function OverlapTable({ rows, subjectTicker, secondTicker, hasSecond, type }: Props) {
  const display = rows.slice(0, 15)

  // Pinned bottom: Top 15 and Top 25 totals
  const pinnedBottom = useMemo<TotalRow[]>(() => {
    return [15, 25].map((n): TotalRow => {
      const slice = rows.slice(0, n)
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
  }, [rows, hasSecond])

  const colDefs = useMemo<(ColDef<TotalRow> | ColGroupDef<TotalRow>)[]>(() => [
    {
      headerName: '#',
      width: 36,
      minWidth: 36,
      suppressSizeToFit: true,
      sortable: false,
      resizable: false,
      cellRenderer: (params: ICellRendererParams<TotalRow>) => {
        if (params.data?._isTotal) return ''
        return params.node.rowIndex != null ? String(params.node.rowIndex + 1) : ''
      },
      cellStyle: { textAlign: 'center', color: '#888', fontSize: '12px' } as CellStyle,
      headerClass: 'ag-right-aligned-header',
    },
    {
      headerName: type === 'inst' ? 'Holder' : 'Fund',
      field: 'holder',
      width: 200,
      minWidth: 200,
      suppressSizeToFit: true,
      sortable: false,
      resizable: false,
      cellStyle: {
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        fontSize: '12px',
      } as CellStyle,
      tooltipField: 'holder',
      cellRenderer: (params: ICellRendererParams<TotalRow>) => {
        const v = (params.value as string) || '—'
        if (params.data?._isTotal) return <span style={{ fontWeight: 600 }}>{v}</span>
        return v
      },
    },
    {
      headerName: '% Owned',
      headerClass: 'tco-group-header',
      marryChildren: true,
      children: [
        {
          headerName: subjectTicker || 'Subject',
          field: 'subj_pct_float',
          width: 72,
          minWidth: 72,
          suppressSizeToFit: true,
          sortable: false,
          resizable: false,
          cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
          valueFormatter: (p: ValueFormatterParams<TotalRow>) =>
            fmtPct(p.value as number | null, true),
          cellRenderer: (p: ICellRendererParams<TotalRow>) => {
            const val = p.value as number | null
            const v = p.data?._isTotal
              ? (val != null ? val.toFixed(2) + '%' : '—')
              : fmtPct(val, true)
            return p.data?._isTotal ? <span style={{ fontWeight: 600 }}>{v}</span> : v
          },
        },
        {
          headerName: secondTicker || (hasSecond ? 'Second' : '—'),
          field: 'sec_pct_float',
          width: 72,
          minWidth: 72,
          suppressSizeToFit: true,
          sortable: false,
          resizable: false,
          cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
          cellRenderer: (p: ICellRendererParams<TotalRow>) => {
            if (!hasSecond) return '—'
            const val = p.value as number | null
            const v = p.data?._isTotal
              ? (val != null && val > 0 ? val.toFixed(2) + '%' : '—')
              : fmtPct(val, p.data ? hasSecShares(p.data) : false)
            return p.data?._isTotal ? <span style={{ fontWeight: 600 }}>{v}</span> : v
          },
        },
      ],
    },
    {
      headerName: 'Value ($M)',
      headerClass: 'tco-group-header',
      marryChildren: true,
      children: [
        {
          headerName: subjectTicker || 'Subject',
          field: 'subj_dollars',
          width: 80,
          minWidth: 80,
          suppressSizeToFit: true,
          sortable: false,
          resizable: false,
          cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
          cellRenderer: (p: ICellRendererParams<TotalRow>) => {
            const v = fmtDollars(p.value as number | null)
            return p.data?._isTotal ? <span style={{ fontWeight: 600 }}>{v}</span> : v
          },
        },
        {
          headerName: secondTicker || (hasSecond ? 'Second' : '—'),
          field: 'sec_dollars',
          width: 80,
          minWidth: 80,
          suppressSizeToFit: true,
          sortable: false,
          resizable: false,
          cellStyle: { textAlign: 'right', fontSize: '12px' } as CellStyle,
          cellRenderer: (p: ICellRendererParams<TotalRow>) => {
            if (!hasSecond) return '—'
            const v = fmtDollars(p.value as number | null)
            return p.data?._isTotal ? <span style={{ fontWeight: 600 }}>{v}</span> : v
          },
        },
      ],
    },
  ], [subjectTicker, secondTicker, hasSecond, type])

  const rowClassRules = useMemo(() => ({
    'tco-overlap-row': (params: RowClassParams<TotalRow>) => !!params.data?.is_overlap,
  }), [])

  return (
    <div
      className="ag-theme-alpine"
      style={{ height: `${GRID_HEIGHT}px`, width: '100%' }}
    >
      <AgGridReact<TotalRow>
        theme="legacy"
        rowData={display}
        columnDefs={colDefs}
        pinnedBottomRowData={pinnedBottom}
        rowClassRules={rowClassRules}
        suppressMovableColumns
        suppressColumnVirtualisation
        headerHeight={HEADER_HEIGHT}
        groupHeaderHeight={SUBHEADER_HEIGHT}
        rowHeight={ROW_HEIGHT}
        suppressHorizontalScroll={false}
        tooltipShowDelay={200}
        domLayout="normal"
      />
    </div>
  )
}
