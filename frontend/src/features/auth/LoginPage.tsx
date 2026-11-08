import { Eye, LogIn } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { toApiError } from '@/lib/api'

export function LoginPage() {
  const { session, loginOwner, loginDemo } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/scenarios'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState<'owner' | 'demo' | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (session) return <Navigate to={from} replace />

  async function run(kind: 'owner' | 'demo', action: () => Promise<void>) {
    setPending(kind)
    setError(null)
    try {
      await action()
      navigate(from, { replace: true })
    } catch (err) {
      setError(toApiError(err).message)
    } finally {
      setPending(null)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void run('owner', () => loginOwner(email, password))
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">AgentOps Logistics</CardTitle>
          <CardDescription>Reliability workbench for logistics AI agents</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <Button
            type="button"
            variant="secondary"
            onClick={() => void run('demo', loginDemo)}
            disabled={pending !== null}
          >
            <Eye aria-hidden /> {pending === 'demo' ? 'Opening demo…' : 'Continue as demo viewer'}
          </Button>
          <p className="-mt-3 text-xs text-muted-foreground">
            Read-only: browse scenarios and results. Hidden answers stay hidden.
          </p>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Separator className="flex-1" /> Owner sign-in <Separator className="flex-1" />
          </div>

          <form onSubmit={onSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={pending !== null}>
              <LogIn aria-hidden /> {pending === 'owner' ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
