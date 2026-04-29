/** Shared manager-type badge configuration. Import in any tab that renders
 *  type badges so colours and labels stay consistent project-wide. */

export interface TypeStyle {
  label: string
  bg: string
  color: string
}

export const TYPE_CONFIG: Record<string, TypeStyle> = {
  passive:              { label: 'passive',       bg: 'rgba(92,140,200,0.12)',  color: '#7aadde' },
  active:               { label: 'active',        bg: 'rgba(92,184,122,0.08)',  color: '#5cb87a' },
  hedge_fund:           { label: 'quant/hedge',   bg: 'rgba(224,90,90,0.08)',   color: '#e05a5a' },
  quantitative:         { label: 'quantitative',  bg: 'rgba(224,90,90,0.08)',   color: '#e05a5a' },
  wealth_management:    { label: 'wealth mgmt',   bg: 'rgba(197,162,84,0.08)',  color: '#c5a254' },
  family_office:        { label: 'family office', bg: 'rgba(197,162,84,0.08)',  color: '#c5a254' },
  pension_insurance:    { label: 'pension',       bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
  mixed:                { label: 'mixed',         bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' },
  strategic:            { label: 'strategic',     bg: 'rgba(197,162,84,0.08)',  color: '#c5a254' },
  activist:             { label: 'activist',      bg: 'rgba(224,90,90,0.08)',   color: '#e05a5a' },
  private_equity:       { label: 'PE',            bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
  venture_capital:      { label: 'VC',            bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
  endowment_foundation: { label: 'endowment',     bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' },
  market_maker:         { label: 'market maker',  bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' },
  SWF:                  { label: 'sovereign',     bg: 'rgba(160,130,220,0.12)', color: '#b09ee0' },
}

const FALLBACK: TypeStyle = { label: '', bg: 'rgba(255,255,255,0.05)', color: '#9a9aa6' }

export function getTypeStyle(type: string | null): TypeStyle {
  if (!type) return { ...FALLBACK, label: 'unknown' }
  const cfg = TYPE_CONFIG[type.toLowerCase()] || TYPE_CONFIG[type]
  if (cfg) return cfg
  return { ...FALLBACK, label: type }
}
