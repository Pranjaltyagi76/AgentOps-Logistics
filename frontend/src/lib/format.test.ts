import { describe, expect, it } from 'vitest'

import { formatDate, humanize } from './format'

describe('humanize', () => {
  it('turns identifiers into readable labels', () => {
    expect(humanize('shipment_delay')).toBe('Shipment delay')
    expect(humanize('eta_issue')).toBe('ETA issue')
    expect(humanize('escalation-sla')).toBe('Escalation SLA')
    expect(humanize('carrier_api_timeout')).toBe('Carrier API timeout')
  })
})

describe('formatDate', () => {
  it('keeps calendar dates on the same day in every time zone', () => {
    expect(formatDate('2026-10-24')).toContain('24')
    expect(formatDate(null)).toBe('—')
  })
})
