import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { AuthProvider } from '@/app/auth/AuthProvider'
import { createQueryClient } from '@/app/queryClient'
import { setSession, type Role } from '@/lib/session'

export function signIn(role: Role | null) {
  setSession(
    role
      ? {
          token: 'test-token',
          role,
          email: role === 'owner' ? 'owner@example.com' : null,
          expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
        }
      : null,
  )
}

/** Renders `routes` inside the real providers, starting at `path`. */
export function renderRoutes(routes: { path: string; element: ReactElement }[], path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } })
  return {
    router,
    ...render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>,
    ),
  }
}
