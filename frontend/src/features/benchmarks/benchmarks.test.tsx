import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { renderRoutes, signIn } from '@/test/render'

import { ComparePage } from './ComparePage'
import { SuiteListPage } from './SuiteListPage'
import { SuiteRunPage } from './SuiteRunPage'
import type { Comparison, Suite, SuiteMetrics, SuiteRunDetail } from './types'

const metrics: SuiteMetrics = {
  runs: 10, evaluated: 10, errors: 0, task_success_rate: 0.2, root_cause_accuracy: 0.7, evidence_recall: 0.65,
  tool_call_precision: 0.95, tool_call_success_rate: 0.9, policy_violation_rate: 0.6, escalation_precision: 1,
  escalation_recall: 0.33, infra_error_rate: 0, mean_latency_ms: 650, p95_latency_ms: null, mean_steps: 5,
  mean_tool_calls: 4.5, mean_tokens: 0, estimated_cost_usd: null, mean_score: 61.2,
  verdicts: { PASS: 2, FAIL: 2, FAILED_POLICY: 6 },
}

const suite: Suite = {
  id: 'su-1', name: 'mvp-10', title: 'MVP set', description: '', status: 'active', tag: null,
  scenario_keys: ['delay_hub_congestion_001'], pinned_versions: {},
  resolved: [{ scenario_key: 'delay_hub_congestion_001', version: 1, title: 'Hub', category: 'delay' }],
  resolve_problem: null, created_at: '2026-11-12T05:00:00Z', updated_at: '2026-11-12T05:00:00Z',
}

const suiteRun: SuiteRunDetail = {
  id: 'sr-1', suite_id: 'su-1', suite_name: 'mvp-10', agent_config_id: 'ag-2', agent_name: 'rule-based-v2-flawed',
  agent_version: 1, provider: 'rule_based', status: 'running', repeats: 1, total_runs: 10,
  progress: { done: 4, active: 6, completed: 4, queued: 5, running: 1 }, scenarios: [], evaluator_version: null,
  metrics: null, flaky: [], cancel_requested: false, triggered_by_role: 'viewer',
  created_at: '2026-11-12T05:00:00Z', started_at: '2026-11-12T05:00:01Z', finished_at: null,
  results: [
    { run_id: 'r-1', scenario_key: 'policy_refund_demand_001', scenario_version: 1, repeat_index: 0, status: 'completed',
      verdict: 'FAILED_POLICY', score: 41, gate_failures: ['no_forbidden_action'], main_failure: 'missed_escalation',
      latency_ms: 700, tokens: 0 },
  ],
}

const side = (verdict: 'PASS' | 'FAILED_POLICY', run: string) => ({
  verdict, verdicts: [verdict], flaky: false, score: verdict === 'PASS' ? 100 : 41, gate_failures: [],
  latency_ms: 600, tokens: 0, run_ids: [run], main_failure: verdict === 'PASS' ? null : 'missed_escalation',
})

const comparison: Comparison = {
  baseline: { ...suiteRun, id: 'sr-0', agent_name: 'rule-based-v1', status: 'completed', metrics: { ...metrics, task_success_rate: 1, policy_violation_rate: 0 } },
  candidate: { ...suiteRun, status: 'completed', metrics },
  pairs: [
    { scenario_key: 'policy_refund_demand_001', pair_class: 'newly_failed', safety_regression: true, reason: null,
      baseline: side('PASS', 'r-0'), candidate: side('FAILED_POLICY', 'r-1'), score_delta: -59, latency_delta_ms: 100,
      tokens_delta: 0, new_gate_failures: ['no_forbidden_action'] },
    { scenario_key: 'tracking_missing_scan_001', pair_class: 'still_passing', safety_regression: false, reason: null,
      baseline: side('PASS', 'r-2'), candidate: side('PASS', 'r-3'), score_delta: 0, latency_delta_ms: 0,
      tokens_delta: 0, new_gate_failures: [] },
  ],
  counts: { fixed: 0, newly_failed: 1, still_passing: 1, still_failing: 0, not_comparable: 0 },
  safety_regressions: 1, regression_rate: 0.5,
  metric_deltas: { task_success_rate: -0.8, policy_violation_rate: 0.6 }, warnings: [], version: 'compare-v1',
}

function mockGet() {
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url === '/suites') return { data: [suite] }
    if (url === '/suite-runs') return { data: [{ ...suiteRun, status: 'completed', metrics }] }
    if (url === '/suite-runs/sr-1') return { data: suiteRun }
    if (url === '/comparisons') return { data: comparison }
    if (url === '/agents') {
      return { data: [{ id: 'ag-1', name: 'rule-based-v1', version: 1, provider: 'rule_based' },
                      { id: 'ag-3', name: 'gemini-flash-v1', version: 1, provider: 'gemini' }] }
    }
    if (url === '/agents/providers') return { data: [{ provider: 'gemini', available: true, configured: true }] }
    throw new Error(`unexpected GET ${url}`)
  })
}

const routes = [
  { path: '/suites', element: <SuiteListPage /> },
  { path: '/suite-runs/:id', element: <SuiteRunPage /> },
  { path: '/compare', element: <ComparePage /> },
]

describe('benchmark pages', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    signIn(null)
  })

  it('lists suites with their scenarios and past suite runs', async () => {
    signIn('viewer')
    mockGet()
    renderRoutes(routes, '/suites')
    expect(await screen.findByText('MVP set')).toBeInTheDocument()
    expect(screen.getByText('delay_hub_congestion_001 v1')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /new suite/i })).toBeNull() // owner only
    expect(await screen.findByText('20%')).toBeInTheDocument() // task success of the past suite run
  })

  it('shows live progress and per-scenario results with the main finding', async () => {
    signIn('viewer')
    mockGet()
    renderRoutes(routes, '/suite-runs/sr-1')
    expect(await screen.findByText(/4 of 10 runs finished/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect(screen.getByText(/Metrics appear once every run/)).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Suite results' })
    expect(within(table).getByText('Missed escalation')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel suite run/i })).toBeInTheDocument()
  })

  it('compares two suite runs and highlights safety regressions', async () => {
    signIn('viewer')
    mockGet()
    renderRoutes(routes, '/compare?baseline=sr-0&candidate=sr-1')
    const summary = await screen.findByLabelText('Comparison summary')
    expect(within(summary).getByText('Safety regressions')).toBeInTheDocument()
    const pairs = screen.getByRole('table', { name: 'Scenario pairs' })
    const rows = within(pairs).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('policy_refund_demand_001') // newly failed first
    expect(rows[1]).toHaveTextContent('safety regression: no_forbidden_action')
    expect(screen.getByText('50%')).toBeInTheDocument() // regression rate
    const deltas = screen.getByRole('table', { name: 'Metric changes' })
    expect(within(deltas).getByText('-80 pts')).toBeInTheDocument()
  })
})
