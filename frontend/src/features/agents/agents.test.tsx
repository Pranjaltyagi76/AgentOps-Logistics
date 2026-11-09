import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { renderRoutes, signIn } from '@/test/render'

import { AgentDetailPage } from './AgentDetailPage'
import { AgentListPage } from './AgentListPage'
import type { AgentDetail, AgentSummary, ProviderStatus } from './types'

const summary: AgentSummary = {
  id: 'ag1',
  name: 'rule-based-v1',
  version: 1,
  description: 'Rule-based baseline (no LLM).',
  provider: 'rule_based',
  model_id: 'v1',
  status: 'active',
  is_locked: false,
  tool_count: 10,
  updated_at: '2026-11-09T05:00:00Z',
}

const providers: ProviderStatus[] = [
  { provider: 'rule_based', label: 'Rule-based (no LLM)', configured: true, available: true, note: 'Always available.' },
  { provider: 'gemini', label: 'Google Gemini', configured: false, available: false, note: 'Arrives in Phase 6.' },
]

function detail(canEdit: boolean): AgentDetail {
  return {
    ...summary,
    created_at: '2026-11-09T05:00:00Z',
    can_edit: canEdit,
    versions: [{ id: 'ag1', version: 1, status: 'active', is_locked: false, created_at: '2026-11-09T05:00:00Z' }],
    config: {
      name: 'rule-based-v1',
      version: 1,
      description: summary.description,
      provider: 'rule_based',
      model_id: 'v1',
      temperature: 0,
      prompt_version: 'agent_system_v1',
      system_prompt: 'You are a customer support agent.',
      tools: ['get_shipment', 'request_refund'],
      max_steps: 12,
      max_tool_calls: 10,
      timeout_s: 30,
      max_retries: 0,
    },
  }
}

function mockApi(agent: AgentDetail) {
  vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url === '/agents') return { data: [summary] }
    if (url === '/agents/providers') return { data: providers }
    if (url === '/agents/ag1') return { data: agent }
    throw new Error(`unexpected GET ${url}`)
  })
}

const routes = [
  { path: '/agents', element: <AgentListPage /> },
  { path: '/agents/:id', element: <AgentDetailPage /> },
]

describe('agent pages', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    signIn(null)
  })

  it('lists agents and provider status without exposing keys', async () => {
    signIn('viewer')
    mockApi(detail(false))
    renderRoutes(routes, '/agents')

    const row = (await screen.findByRole('link', { name: 'rule-based-v1' })).closest('tr')!
    expect(within(row).getByText('Rule-based')).toBeInTheDocument()
    // Profile "v1" and version "v1" are both shown.
    expect(within(row).getAllByText('v1', { selector: 'td' })).toHaveLength(2)
    expect(screen.getByText(/API key not configured/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /new agent/i })).not.toBeInTheDocument()
  })

  it('shows config details; only the owner can edit', async () => {
    signIn('viewer')
    mockApi(detail(false))
    const { unmount } = renderRoutes(routes, '/agents/ag1')
    expect(await screen.findByText('You are a customer support agent.')).toBeInTheDocument()
    expect(screen.getByText('request_refund')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /edit/i })).not.toBeInTheDocument()
    unmount()

    vi.restoreAllMocks()
    signIn('owner')
    mockApi(detail(true))
    renderRoutes(routes, '/agents/ag1')
    expect(await screen.findByRole('link', { name: /edit/i })).toBeInTheDocument()
  })
})
