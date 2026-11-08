import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

import { useAuth } from './context'

/** Sends signed-out visitors to /login, remembering where they were going. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const location = useLocation()
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

/** UI guard only; the API enforces the owner role independently. */
export function RequireOwner({ children }: { children: ReactNode }) {
  const { isOwner } = useAuth()
  if (!isOwner) {
    return (
      <Alert className="mx-auto max-w-xl">
        <AlertTitle>Owner access required</AlertTitle>
        <AlertDescription>The demo viewer can browse scenarios but not change them.</AlertDescription>
      </Alert>
    )
  }
  return <>{children}</>
}
