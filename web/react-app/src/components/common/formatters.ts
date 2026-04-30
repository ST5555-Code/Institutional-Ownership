// Shared display formatters for the React app.
//
// fmtQuarter — canonical quarter label formatter.
//   "2025Q3" → "Q3 '25"
// All quarter labels shown to the user (buttons, table headers/cells, chart
// axes, tooltips) must run through this function.

export function fmtQuarter(q: string): string {
  if (!q) return q
  const m = /^(\d{4})Q([1-4])$/.exec(q)
  if (!m) return q
  const yr = m[1].slice(-2)
  return `Q${m[2]} '${yr}`
}

// Sort quarters ascending (oldest → newest). Pure string sort works because
// the format is YYYY'Q'N which is lexicographically ordered.
export function sortQuartersAsc(quarters: string[]): string[] {
  return [...quarters].sort()
}
