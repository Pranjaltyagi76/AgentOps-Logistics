import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { AxiosError, AxiosHeaders } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '@/app/queryClient'
import { api } from '@/lib/api'

import { StatusPage } from './StatusPage'

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <StatusPage />
    </QueryClientProvider>,
  )
}

function rowFor(label: string) {
  const row = screen.getByText(label).closest('div')?.parentElement
  if (!row) throw new Error(`row ${label} not found`)
  return within(row)
}

const versionPayload = {
  name: 'AgentOps Logistics API',
  version: '0.1.0',
  git_sha: 'abc1234',
  environment: 'local',
}

function axiosErrorWithStatus(status: number, data: unknown) {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, null, {
    status,
    statusText: '',
    headers: {},
    config,
    data,
  })
}

describe('StatusPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows API and database as OK when health succeeds', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url: string) =>
      url === '/health'
        ? { data: { status: 'ok', db: 'ok' } }
        : { data: versionPayload },
    )
    renderPage()

    expect(await rowFor('Backend API').findByText('OK')).toBeInTheDocument()
    expect(rowFor('Database').getByText('OK')).toBeInTheDocument()
    expect(await screen.findByText('abc1234')).toBeInTheDocument()
  })

  it('shows the database as unavailable when health returns 503', async () => {
    const { toApiError } = await import('@/lib/api')
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url === '/health') {
        throw toApiError(
          axiosErrorWithStatus(503, {
            error: { code: 'db_unavailable', message: 'Database is unreachable', details: {} },
          }),
        )
      }
      return { data: versionPayload }
    })
    renderPage()

    expect(await rowFor('Database').findByText('Unavailable')).toBeInTheDocument()
    expect(rowFor('Backend API').getByText('OK')).toBeInTheDocument()
    expect(screen.getByText('Database is unreachable')).toBeInTheDocument()
  })

  it('shows the API as unreachable on network failure', async () => {
    const { ApiError } = await import('@/lib/api')
    vi.spyOn(api, 'get').mockRejectedValue(
      new ApiError({ code: 'network_error', message: 'offline', status: null }),
    )
    renderPage()

    expect(await rowFor('Backend API').findByText('Unreachable')).toBeInTheDocument()
    expect(rowFor('Database').getByText('Unreachable')).toBeInTheDocument()
  })
})
