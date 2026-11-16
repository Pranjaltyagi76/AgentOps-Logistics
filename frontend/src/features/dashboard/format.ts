import type { components } from '@/lib/api-schema'

type Kpi = components['schemas']['KpiOut']

/** Formats a KPI; null is shown as "unknown", never as 0 (FR-09.3). */
export function formatKpi(kpi: Pick<Kpi, 'unit' | 'value'>): string {
  const v = kpi.value
  if (v === null || v === undefined) return 'unknown'
  switch (kpi.unit) {
    case 'rate':
      return `${Math.round(v * 1000) / 10}%`
    case 'score':
      return (Math.round(v * 100) / 100).toFixed(2)
    case 'ms':
      return `${(v / 1000).toFixed(2)} s`
    case 'usd':
      return `$${v.toFixed(2)}`
    default:
      return v.toLocaleString()
  }
}

