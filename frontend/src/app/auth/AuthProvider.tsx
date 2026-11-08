import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useSyncExternalStore, type ReactNode } from 'react'

import { api } from '@/lib/api'
import { getSession, setSession, subscribeSession, type Role, type Session } from '@/lib/session'

import { AuthContext, type AuthContextValue } from './context'

interface TokenResponse {
  access_token: string
  expires_at: string
  role: Role
  email: string | null
}

function toSession(body: TokenResponse): Session {
  return { token: body.access_token, role: body.role, email: body.email, expiresAt: body.expires_at }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(subscribeSession, getSession, () => null)
  const queryClient = useQueryClient()

  const start = useCallback(
    (body: TokenResponse) => {
      // Cached data may belong to the previous role (owner sees hidden fields).
      queryClient.clear()
      setSession(toSession(body))
    },
    [queryClient],
  )

  const loginOwner = useCallback(
    async (email: string, password: string) => {
      const { data } = await api.post<TokenResponse>('/auth/login', { email, password })
      start(data)
    },
    [start],
  )

  const loginDemo = useCallback(async () => {
    const { data } = await api.post<TokenResponse>('/auth/demo')
    start(data)
  }, [start])

  const logout = useCallback(() => {
    setSession(null)
    queryClient.clear()
  }, [queryClient])

  const value = useMemo<AuthContextValue>(
    () => ({ session, isOwner: session?.role === 'owner', loginOwner, loginDemo, logout }),
    [session, loginOwner, loginDemo, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
