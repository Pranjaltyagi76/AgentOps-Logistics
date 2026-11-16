import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { renderRoutes, signIn } from '@/test/render'

import { SettingsPage, type SettingsStatus } from './SettingsPage'

const status: SettingsStatus = {
  app_version: '0.1.0', environment: 'local',
  gemini: { configured: true, model: 'gemini-3.5-flash', thinking_level: 'minimal', requests_per_minute: 5, request_timeout_s: 20 },
  judge: { enabled: false, model: 'gemini-3.5-flash', prompt_version: 'judge_v1', advisory: true },
  limits: {
    llm_runs_per_day: 4, judge_calls_per_day: 4, concurrent_runs: 2, concurrent_llm_runs: 1, queued_runs: 60,
    run_launches_per_minute: 10, request_body_bytes: 1000000,
  },
  usage_today: { llm_runs: 1, judge_calls: 0 },
  versions: { evaluator: 'eval-v2', diagnoser: 'diag-v1' },
}

describe('settings page', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    signIn(null)
  })

  it('shows provider status, limits with today usage and versions', async () => {
    signIn('owner')
    vi.spyOn(api, 'get').mockResolvedValue({ data: status })
    renderRoutes([{ path: '/settings', element: <SettingsPage /> }], '/settings')
    expect(await screen.findByText('configured')).toBeInTheDocument()
    expect(screen.getByText('4 (1 used today)')).toBeInTheDocument()
    expect(screen.getByText('eval-v2')).toBeInTheDocument()
    expect(screen.getByText('off')).toBeInTheDocument()
  })
})
