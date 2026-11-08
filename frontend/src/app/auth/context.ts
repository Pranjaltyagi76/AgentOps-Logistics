import { createContext, useContext } from 'react'

import type { Session } from '@/lib/session'

export interface AuthContextValue {
  session: Session | null
  isOwner: boolean
  loginOwner: (email: string, password: string) => Promise<void>
  loginDemo: () => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
