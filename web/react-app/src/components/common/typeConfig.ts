/** Shared manager-type badge configuration. Import in any tab that renders
 *  type badges so colours and labels stay consistent project-wide. */

export interface TypeStyle {
  label: string
  bg: string
  color: string
}

export const TYPE_CONFIG: Record<string, TypeStyle> = {
  passive:            { label: 'passive',       bg: '#4A90D9', color: '#fff' },
  active:             { label: 'active',        bg: '#002147', color: '#fff' },
  hedge_fund:         { label: 'quant/hedge',   bg: '#7B2D8B', color: '#fff' },
  quantitative:       { label: 'quantitative',  bg: '#7B2D8B', color: '#fff' },
  wealth_management:  { label: 'wealth mgmt',   bg: '#2D6A4F', color: '#fff' },
  pension_insurance:  { label: 'pension',        bg: '#B45309', color: '#fff' },
  mixed:              { label: 'mixed',          bg: '#475569', color: '#fff' },
}

const FALLBACK: TypeStyle = { label: '', bg: '#cbd5e1', color: '#1e293b' }

export function getTypeStyle(type: string | null): TypeStyle {
  if (!type) return { ...FALLBACK, label: 'unknown' }
  const cfg = TYPE_CONFIG[type.toLowerCase()]
  if (cfg) return cfg
  return { ...FALLBACK, label: type }
}
