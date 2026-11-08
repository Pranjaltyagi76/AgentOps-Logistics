import { CheckCircle2, CircleAlert, Loader2, RefreshCw, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { API_BASE_URL, toApiError } from '@/lib/api'

import { useHealth, useVersion } from './api'

type CheckState = 'loading' | 'ok' | 'down' | 'unreachable'

function StateBadge({ state }: { state: CheckState }) {
  switch (state) {
    case 'loading':
      return (
        <Badge variant="secondary">
          <Loader2 className="animate-spin" aria-hidden /> Checking
        </Badge>
      )
    case 'ok':
      return (
        <Badge className="bg-emerald-600 text-white">
          <CheckCircle2 aria-hidden /> OK
        </Badge>
      )
    case 'down':
      return (
        <Badge variant="destructive">
          <XCircle aria-hidden /> Unavailable
        </Badge>
      )
    case 'unreachable':
      return (
        <Badge variant="outline">
          <CircleAlert aria-hidden /> Unreachable
        </Badge>
      )
  }
}

function StatusRow({ label, state, hint }: { label: string; state: CheckState; hint?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div>
        <p className="font-medium">{label}</p>
        {hint ? <p className="text-sm text-muted-foreground">{hint}</p> : null}
      </div>
      <StateBadge state={state} />
    </div>
  )
}

export function StatusPage() {
  const health = useHealth()
  const version = useVersion()

  const healthError = health.error ? toApiError(health.error) : null
  // A 503 means the API answered but its database did not; no status means no API at all.
  const apiState: CheckState = health.isPending
    ? 'loading'
    : healthError && healthError.status === null
      ? 'unreachable'
      : 'ok'
  const dbState: CheckState = health.isPending
    ? 'loading'
    : health.data?.db === 'ok'
      ? 'ok'
      : apiState === 'unreachable'
        ? 'unreachable'
        : 'down'

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">System status</h1>
          <p className="text-sm text-muted-foreground">
            Connectivity between this app, the API and the database.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void health.refetch()}
          disabled={health.isFetching}
        >
          <RefreshCw className={health.isFetching ? 'animate-spin' : ''} aria-hidden />
          Recheck
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Services</CardTitle>
          <CardDescription className="break-all">API base URL: {API_BASE_URL}</CardDescription>
        </CardHeader>
        <CardContent className="divide-y">
          <StatusRow
            label="Backend API"
            state={apiState}
            hint={
              apiState === 'unreachable'
                ? 'No response. A free-tier backend may take up to a minute to wake up.'
                : undefined
            }
          />
          <StatusRow
            label="Database"
            state={dbState}
            hint={dbState === 'down' ? healthError?.message : undefined}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Build</CardTitle>
        </CardHeader>
        <CardContent>
          {version.data ? (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Service</dt>
              <dd>{version.data.name}</dd>
              <dt className="text-muted-foreground">Version</dt>
              <dd>{version.data.version}</dd>
              <dt className="text-muted-foreground">Commit</dt>
              <dd className="font-mono">{version.data.git_sha}</dd>
              <dt className="text-muted-foreground">Environment</dt>
              <dd>{version.data.environment}</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              {version.isPending ? 'Loading…' : 'Version information unavailable.'}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
