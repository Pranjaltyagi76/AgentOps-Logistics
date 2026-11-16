import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BackendWakingBanner } from '@/app/layout/BackendWakingBanner'
import { BenchmarkReportPage } from '@/features/reports/ReportsPage'
import { api } from '@/lib/api'
import type { components } from '@/lib/api-schema'
import { SLOW_AFTER_MS, watchRequest } from '@/lib/slowRequests'
import { renderRoutes, signIn } from '@/test/render'

import { DashboardPage } from './DashboardPage'
import { formatKpi } from './format'

type Dashboard = components['schemas']['DashboardOut']

const kpi = (key: string, label: string, unit: 'count' | 'rate' | 'score' | 'ms' | 'usd', value: number | null) => ({
  key, label, unit, value, definition: `${label} definition`, sql: `SELECT ${key}`,
})

const dashboard: Dashboard = {
  version: 'dashboard-v1', include_demo: true, demo_runs: 20,
  kpis: [kpi('total_runs', 'Runs', 'count', 20), kpi('pass_rate', 'Pass rate', 'rate', 0.6),
    kpi('tool_correctness', 'Tool correctness', 'score', 0.9646), kpi('estimated_cost_usd', 'Estimated cost', 'usd', null)],
  failure_types: [{ failure_type: 'missed_escalation', items: 4, main_findings: 2, runs: 2 }],
  agent_versions: [{ agent_name: 'rule-based-v2-flawed', agent_version: 1, provider: 'rule_based', runs: 10,
    pass_rate: 0.2, mean_score: 60.8, policy_violation_rate: 0.6, mean_latency_ms: 400 }],
  recent_runs: [{ id: 'r-1', scenario_key: 'policy_refund_demand_001', scenario_version: 1, agent_name: 'rule-based-v2-flawed',
    agent_version: 1, provider: 'rule_based', status: 'completed', verdict: 'FAILED_POLICY', score: 41, is_demo: true,
    created_at: '2026-11-16T10:00:00Z' }],
  recent_suite_runs: [], queries: {},
}

describe('dashboard and reports', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    signIn(null)
  })

  it('formats KPIs and shows unknown instead of a number', () => {
    expect(formatKpi({ unit: 'rate', value: 0.6 })).toBe('60%')
    expect(formatKpi({ unit: 'ms', value: 1148.1 })).toBe('1.15 s')
    expect(formatKpi({ unit: 'usd', value: null })).toBe('unknown')
  })

  it('shows KPIs with their definitions, labels demo data and can leave it out', async () => {
    signIn('viewer')
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: dashboard })
    renderRoutes([{ path: '/dashboard', element: <DashboardPage /> }], '/dashboard')

    const figures = await screen.findByLabelText('Key figures')
    expect(within(figures).getByText('60%')).toBeInTheDocument()
    expect(within(figures).getByText('unknown')).toBeInTheDocument()
    expect(within(figures).getByLabelText('Pass rate definition')).toBeInTheDocument()
    expect(screen.getByText(/include seeded demo runs/)).toBeInTheDocument()
    expect(within(screen.getByLabelText('Recent runs')).getByText('demo')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Missed escalation: 4 findings in 2 runs' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Include demo data' }))
    expect(get).toHaveBeenLastCalledWith('/dashboard/summary', { params: { include_demo: false } })
  })

  it('renders a benchmark report with failure analysis and export buttons', async () => {
    signIn('viewer')
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        report_version: 'report-v1', shows_ground_truth_details: false,
        suite_run: { id: 'sr-1', suite_name: 'mvp-10', status: 'completed', repeats: 1, total_runs: 1, is_demo: true,
          created_at: '2026-11-16T10:00:00Z', finished_at: '2026-11-16T10:00:05Z' },
        agent: { name: 'rule-based-v2-flawed', version: 1, provider: 'rule_based' },
        evaluator_versions: ['eval-v2'], metrics: null, flaky: [], failure_counts: { forbidden_action: 1 },
        runs: [{ run_id: 'r-1', scenario_key: 'delivery_customer_unavailable_001', scenario_version: 1, repeat_index: 0,
          status: 'completed', verdict: 'FAILED_POLICY', score: 70, gate_failures: ['no_forbidden_action'],
          main_failure: 'forbidden_action', latency_ms: 300 }],
      },
    })
    renderRoutes([{ path: '/reports/:id', element: <BenchmarkReportPage /> }], '/reports/sr-1')
    expect(await screen.findByRole('button', { name: /export csv/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /export json/i })).toBeInTheDocument()
    expect(screen.getByText('demo')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Scenario results' })).getByText('no_forbidden_action')).toBeInTheDocument()
    expect(screen.getByText(/leave out expected values/)).toBeInTheDocument()
  })

  it('shows the waking banner only while a request is slow', () => {
    vi.useFakeTimers()
    render(<BackendWakingBanner />)
    expect(screen.queryByRole('status')).toBeNull()
    let done = () => {}
    act(() => {
      done = watchRequest()
    })
    act(() => vi.advanceTimersByTime(SLOW_AFTER_MS - 1))
    expect(screen.queryByRole('status')).toBeNull()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByRole('status')).toHaveTextContent(/waking up/)
    act(() => done())
    expect(screen.queryByRole('status')).toBeNull()
  })
})
