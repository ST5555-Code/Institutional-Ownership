export function fmtNum(n: number | null | undefined): string {
  if (n == null) return '—'
  return Math.round(n).toLocaleString()
}

export function fmtAge(days: number | null | undefined): string {
  if (days == null) return '—'
  if (days < 1) return '<1d'
  if (days < 30) return `${Math.round(days)}d`
  if (days < 365) return `${Math.round(days / 30)}mo`
  return `${(days / 365).toFixed(1)}y`
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const diffMs = Date.now() - d.getTime()
  const diffMin = diffMs / 60000
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${Math.round(diffMin)}m ago`
  const diffH = diffMin / 60
  if (diffH < 24) return `${Math.round(diffH)}h ago`
  const diffD = diffH / 24
  if (diffD < 30) return `${Math.round(diffD)}d ago`
  return d.toISOString().slice(0, 10)
}

export function fmtScope(scope: Record<string, unknown> | null | undefined): string {
  if (!scope || Object.keys(scope).length === 0) return '(default)'
  return Object.entries(scope).map(([k, v]) => `${k}=${v}`).join(' ')
}
