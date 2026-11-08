// Words that read better upper-cased when humanizing identifiers.
const ACRONYMS: Record<string, string> = {
  api: 'API',
  eta: 'ETA',
  id: 'ID',
  sla: 'SLA',
  sop: 'SOP',
  sops: 'SOPs',
}

/** "shipment_delay" -> "Shipment delay", "escalation-sla" -> "Escalation SLA" */
export function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, ' ').trim().split(/\s+/)
  const text = words.map((word) => ACRONYMS[word.toLowerCase()] ?? word).join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateTimeFormat.format(date)
}

/** Formats a calendar date ("2026-10-24") without shifting it across time zones. */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '—'
  const [y, m, d] = isoDate.split('-').map(Number)
  if (!y || !m || !d) return isoDate
  return dateFormat.format(new Date(y, m - 1, d))
}
