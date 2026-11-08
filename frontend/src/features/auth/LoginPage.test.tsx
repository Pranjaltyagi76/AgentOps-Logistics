import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '@/lib/api'
import { getSession } from '@/lib/session'
import { renderRoutes, signIn } from '@/test/render'

import { LoginPage } from './LoginPage'

const routes = [
  { path: '/login', element: <LoginPage /> },
  { path: '/scenarios', element: <p>scenario list</p> },
]

const token = (role: 'owner' | 'viewer', email: string | null) => ({
  data: { access_token: 'jwt', expires_at: new Date(Date.now() + 60_000).toISOString(), role, email },
})

describe('LoginPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    signIn(null)
  })

  it('starts a demo viewer session and continues to the app', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue(token('viewer', null))
    renderRoutes(routes, '/login')

    await userEvent.click(screen.getByRole('button', { name: /demo viewer/i }))

    expect(post).toHaveBeenCalledWith('/auth/demo')
    expect(await screen.findByText('scenario list')).toBeInTheDocument()
    expect(getSession()?.role).toBe('viewer')
  })

  it('signs the owner in with email and password', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue(token('owner', 'owner@example.com'))
    renderRoutes(routes, '/login')

    await userEvent.type(screen.getByLabelText('Email'), 'owner@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(post).toHaveBeenCalledWith('/auth/login', {
      email: 'owner@example.com',
      password: 'correct-horse-battery',
    })
    await waitFor(() => expect(getSession()?.role).toBe('owner'))
  })

  it('shows the server error for bad credentials', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(
      new ApiError({ code: 'invalid_credentials', message: 'Email or password is incorrect', status: 401 }),
    )
    renderRoutes(routes, '/login')

    await userEvent.type(screen.getByLabelText('Email'), 'owner@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Email or password is incorrect')).toBeInTheDocument()
    expect(getSession()).toBeNull()
  })
})
