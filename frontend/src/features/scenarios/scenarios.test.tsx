import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { renderRoutes, signIn } from '@/test/render'

import { ScenarioDetailPage } from './ScenarioDetailPage'
import { ScenarioListPage } from './ScenarioListPage'
import type { ScenarioDetail, ScenarioPage, Taxonomy } from './types'

const taxonomy: Partial<Taxonomy> = {
  categories: ['shipment_delay', 'eta_issue'],
  difficulties: ['easy', 'medium', 'hard'],
  statuses: ['draft', 'active', 'archived'],
  tools: [{ name: 'request_refund', kind: 'mock_write', policy_gated: true }],
  root_causes: [{ label: 'hub_congestion', family: 'delay', description: 'Hub is slow.' }],
  response_constraints: [{ name: 'must_not_invent_eta', gate: true }],
}

const summary = {
  id: 'a1',
  scenario_key: 'delay_hub_congestion_001',
  version: 1,
  title: 'Shipment stuck at a congested destination hub',
  category: 'shipment_delay',
  difficulty: 'medium' as const,
  status: 'active' as const,
  tags: ['delay', 'hub'],
  is_locked: false,
  updated_at: '2026-11-08T05:00:00Z',
}

const page: ScenarioPage = { items: [summary], next_cursor: null, total: 1 }

function detail(hidden: boolean): ScenarioDetail {
  return {
    ...summary,
    created_at: '2026-11-08T05:00:00Z',
    versions: [{ id: 'a1', version: 1, status: 'active', is_locked: false, created_at: '2026-11-08T05:00:00Z' }],
    can_edit: hidden,
    visible: {
      scenario_id: summary.scenario_key,
      version: 1,
      title: summary.title,
      description: 'Parcel stuck at Pune hub.',
      category: 'shipment_delay',
      difficulty: 'medium',
      as_of: '2026-10-21T15:00:00+05:30',
      customer_message: 'Why has my package not moved?',
      visible_context: { shipment_id: 'SHP-1042' },
      mock_data: { shipments: [], tracking_events: [], carrier_status: [], tickets: [] },
      permitted_documents: ['delay-communication'],
      available_tools: ['get_shipment', 'request_refund'],
      tags: summary.tags,
    },
    hidden: hidden
      ? {
          ground_truth: {
            root_cause: 'hub_congestion',
            required_evidence: ['event:SHP-1042:05'],
            required_tools: ['get_tracking_events'],
            required_actions: [],
            forbidden_actions: ['request_refund'],
            expected_escalation: false,
            supported_eta: null,
            sequence_constraints: [],
            response_constraints: ['must_not_invent_eta'],
          },
          evaluation: { weights: { root_cause: 25 }, pass_threshold: 70, rubric: null },
          fault_injection: [],
          author_note: 'Likely failure: inventing a date.',
        }
      : null,
  }
}

function mockApi(scenario: ScenarioDetail) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url === '/taxonomy') return { data: taxonomy }
    if (url === '/scenarios') return { data: page }
    if (url === '/scenarios/a1') return { data: scenario }
    throw new Error(`unexpected GET ${url}`)
  })
}

const routes = [
  { path: '/scenarios', element: <ScenarioListPage /> },
  { path: '/scenarios/:id', element: <ScenarioDetailPage /> },
]

describe('scenario pages', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    signIn(null)
  })

  it('lists scenarios with badges and hides owner actions from viewers', async () => {
    signIn('viewer')
    mockApi(detail(false))
    renderRoutes(routes, '/scenarios')

    const link = await screen.findByRole('link', { name: summary.title })
    const row = link.closest('tr')!
    expect(within(row).getByText('Shipment delay')).toBeInTheDocument()
    expect(within(row).getByText('Medium')).toBeInTheDocument()
    expect(within(row).getByText('v1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /import json/i })).not.toBeInTheDocument()
    expect(screen.getByText(/1 scenario\./)).toBeInTheDocument()
  })

  it('shows owner actions', async () => {
    signIn('owner')
    mockApi(detail(true))
    renderRoutes(routes, '/scenarios')
    expect(await screen.findByRole('button', { name: /import json/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /new scenario/i })).toBeInTheDocument()
  })

  it('tells viewers the ground truth is hidden', async () => {
    signIn('viewer')
    mockApi(detail(false))
    renderRoutes(routes, '/scenarios/a1')

    expect(await screen.findByText('Why has my package not moved?')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /edit/i })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Ground truth' }))
    expect(await screen.findByText('Hidden for demo viewers')).toBeInTheDocument()
    expect(screen.queryByText('hub_congestion')).not.toBeInTheDocument()
  })

  it('shows the ground truth to the owner', async () => {
    signIn('owner')
    mockApi(detail(true))
    renderRoutes(routes, '/scenarios/a1')

    await screen.findByText('Why has my package not moved?')
    expect(screen.getByRole('link', { name: /edit/i })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Ground truth' }))
    expect(await screen.findByText('hub_congestion')).toBeInTheDocument()
    expect(screen.getByText('event:SHP-1042:05')).toBeInTheDocument()
    expect(screen.getByText('Likely failure: inventing a date.')).toBeInTheDocument()
  })
})
