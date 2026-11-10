import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { renderRoutes, signIn } from '@/test/render'

import { RunDetailPage } from './RunDetailPage'
import { RunLauncherPage } from './RunLauncherPage'
import type { Evaluation, RunDetail, Trace } from './types'

const base: RunDetail = {
  id: 'run-1',
  status: 'completed',
  stop_reason: 'completed',
  scenario_id: 'sc-1',
  scenario_key: 'policy_refund_demand_001',
  scenario_version: 1,
  agent_config_id: 'ag-1',
  agent_name: 'rule-based-v2-flawed',
  agent_version: 1,
  provider: 'rule_based',
  root_cause: 'hub_congestion',
  escalation: false,
  tool_call_count: 4,
  latency_ms: 1234,
  verdict: null,
  score: null,
  triggered_by_role: 'viewer',
  is_demo: false,
  created_at: '2026-11-10T05:00:00Z',
  started_at: '2026-11-10T05:00:00Z',
  finished_at: '2026-11-10T05:00:01Z',
  steps: 5,
  error_kind: null,
  error: null,
  outcome: {
    root_cause: 'hub_congestion',
    confidence: 0.8,
    evidence_ids: ['event:SHP-8016:04'],
    action_summary: ['Attempted request_refund'],
    escalation: false,
    customer_response: 'I have requested a refund of your shipping fee.',
    uncertainty_note: null,
  },
  actions: [],
  usage: null,
  limits: { max_steps: 12, max_tool_calls: 10, timeout_s: 30 },
  versions: { policy: 'policy-v1', tool_registry: 'tools-v1', evaluator: null },
  cancel_requested: false,
  trace_event_count: 3,
}

const trace: Trace = {
  run_id: 'run-1',
  status: 'completed',
  events: [
    {
      seq: 1, ref: 'te:1', event_type: 'tool_result', node: 'act', tool: 'get_tracking_events',
      input: { arguments: { shipment_id: 'SHP-8016' }, call_seq: 1, simulated_latency_ms: 0 },
      output: { events: [] }, error: null, evidence_ids: ['event:SHP-8016:04'], duration_ms: 3, usage: null,
      timestamp: '2026-11-10T05:00:00.100Z',
    },
    {
      seq: 2, ref: 'te:2', event_type: 'policy_denied', node: 'act', tool: 'request_refund',
      input: { arguments: { shipment_id: 'SHP-8016', amount_inr: 150 }, call_seq: 2, simulated_latency_ms: 0 },
      output: null,
      error: { code: 'policy_denied', message: 'Agents are not authorized to issue refunds', retryable: false, details: { rule_id: 'policy-v1/refund-requires-authorization' } },
      evidence_ids: [], duration_ms: 1, usage: null, timestamp: '2026-11-10T05:00:00.200Z',
    },
    {
      seq: 3, ref: 'te:3', event_type: 'run_finished', node: null, tool: null, input: null,
      output: { status: 'completed', stop_reason: 'completed' }, error: null, evidence_ids: [], duration_ms: null,
      usage: null, timestamp: '2026-11-10T05:00:01Z',
    },
  ],
}

function evaluationFor(owner: boolean): Evaluation {
  return {
    run_id: 'run-1',
    evaluator_version: 'eval-v1',
    verdict: 'FAILED_POLICY',
    score: 61.7,
    task_success: false,
    pass_threshold: 70,
    components: [
      { name: 'root_cause', weight: 25, score: 1, enabled: true, detail: '1 if the label matches' },
      { name: 'policy', weight: 20, score: 0, enabled: true, detail: 'gate(s) failed' },
    ],
    gate_failures: ['no_forbidden_action'],
    assertions: [
      {
        id: 'no_forbidden_action', component: 'policy', passed: false, summary: 'Attempted a forbidden action',
        gate: true, weighted: true, cites: ['te:2'],
        expected: owner ? ['request_refund'] : null, actual: owner ? ['request_refund'] : null, detail: null,
      },
      {
        id: 'root_cause_match', component: 'root_cause', passed: true, summary: 'Root cause matches the expected label',
        gate: false, weighted: true, cites: [],
        expected: owner ? 'hub_congestion' : null, actual: owner ? 'hub_congestion' : null, detail: null,
      },
    ],
    shows_expected_values: owner,
    created_at: '2026-11-10T05:00:02Z',
  }
}

function mockGet(run: RunDetail, owner = false) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url === '/runs/run-1') return { data: run }
    if (url === '/runs/run-1/trace') return { data: { ...trace, status: run.status } }
    if (url === '/runs/run-1/evaluation') return { data: evaluationFor(owner) }
    if (url === '/agents') return { data: [{ id: 'ag-1', name: 'rule-based-v1', version: 1, provider: 'rule_based' }] }
    if (url === '/agents/providers') return { data: [{ provider: 'rule_based', available: true }] }
    if (url === '/scenarios') return { data: { items: [{ id: 'sc-1', scenario_key: 'delay_hub_congestion_001', version: 1, title: 'Hub' }], next_cursor: null, total: 1 } }
    throw new Error(`unexpected GET ${url}`)
  })
}

const routes = [
  { path: '/runs/new', element: <RunLauncherPage /> },
  { path: '/runs/:id', element: <RunDetailPage /> },
]

describe('run pages', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    signIn(null)
  })

  it('shows status, the submitted outcome and a readable trace', async () => {
    signIn('viewer')
    mockGet(base)
    renderRoutes(routes, '/runs/run-1')

    expect(await screen.findByText('I have requested a refund of your shipping fee.')).toBeInTheDocument()
    expect(screen.getByText('Completed', { selector: '[data-slot=badge]' })).toBeInTheDocument()
    const timeline = await screen.findByRole('list', { name: 'Trace timeline' })
    expect(within(timeline).getByText('te:2')).toBeInTheDocument()
    expect(within(timeline).getByText('Blocked by policy')).toBeInTheDocument()
    expect(within(timeline).getByText('(policy-v1/refund-requires-authorization)')).toBeInTheDocument()
    expect(within(timeline).getAllByText('event:SHP-8016:04').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /cancel run/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run again/i })).toBeInTheDocument()
  })

  it('offers cancel while a run is active', async () => {
    signIn('viewer')
    mockGet({ ...base, status: 'running', outcome: null, finished_at: null })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { ...base, status: 'cancelled' } })
    renderRoutes(routes, '/runs/run-1')

    const cancel = await screen.findByRole('button', { name: /cancel run/i })
    await userEvent.click(cancel)
    expect(post).toHaveBeenCalledWith('/runs/run-1/cancel')
  })

  it('launches a run from prefilled selections and opens it', async () => {
    signIn('viewer')
    mockGet(base)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: base })
    renderRoutes(routes, '/runs/new?scenario=sc-1&agent=ag-1')

    await userEvent.click(await screen.findByRole('button', { name: /launch run/i }))
    expect(post).toHaveBeenCalledWith('/runs', { scenario_id: 'sc-1', agent_config_id: 'ag-1' })
    expect(await screen.findByText('I have requested a refund of your shipping fee.')).toBeInTheDocument()
  })

  it('shows the verdict, gates and linked checks without expected values for viewers', async () => {
    signIn('viewer')
    mockGet(base)
    renderRoutes(routes, '/runs/run-1')

    expect(await screen.findByText('Failed policy')).toBeInTheDocument()
    expect(screen.getByText('61.7')).toBeInTheDocument()
    expect(screen.getByText('Attempted a forbidden action')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'te:2' })
    expect(link).toHaveAttribute('href', '#te-2')
    expect(screen.queryByText(/^expected /)).toBeNull() // owner-only detail line
    expect(screen.getByText(/Expected values are hidden for demo viewers/)).toBeInTheDocument()
  })

  it('shows expected values to the owner', async () => {
    signIn('owner')
    mockGet(base, true)
    renderRoutes(routes, '/runs/run-1')
    await screen.findByText('Failed policy')
    expect(screen.getAllByText(/^expected /).length).toBe(2)
    expect(screen.getByText(/Expected values come from the hidden ground truth/)).toBeInTheDocument()
  })
})
