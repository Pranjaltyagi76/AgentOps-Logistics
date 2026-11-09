import { Archive, ArchiveRestore, ArrowLeft, Copy, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { LockedBadge, StatusBadge } from '@/features/scenarios/badges'
import { toApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

import { useAgent, useCloneAgent, useSetAgentArchived } from './api'
import { ProviderBadge } from './components'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

export function AgentDetailPage() {
  const { id = '' } = useParams()
  const { isOwner } = useAuth()
  const navigate = useNavigate()
  const notice = (useLocation().state as { notice?: string } | null)?.notice
  const agent = useAgent(id)
  const clone = useCloneAgent()
  const archive = useSetAgentArchived()
  const [error, setError] = useState<string | null>(null)

  if (agent.isPending) return <Skeleton className="h-64 w-full" />
  if (agent.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load agent</AlertTitle>
        <AlertDescription>
          {toApiError(agent.error).message} <Link to="/agents" className="underline">Back to agents</Link>
        </AlertDescription>
      </Alert>
    )
  }
  const a = agent.data
  const c = a.config
  const archived = a.status === 'archived'

  async function run(action: () => Promise<void>) {
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link to="/agents" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Agents
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="font-mono text-2xl font-semibold tracking-tight">{a.name}</h1>
          <p className="text-sm text-muted-foreground">v{a.version}</p>
          <div className="flex flex-wrap gap-1.5">
            <ProviderBadge provider={a.provider} />
            <StatusBadge status={a.status} />
            {a.is_locked ? <LockedBadge /> : null}
          </div>
        </div>
        {isOwner ? (
          <div className="flex flex-wrap gap-2">
            {a.can_edit ? (
              <Button size="sm" asChild>
                <Link to={`/agents/${a.id}/edit`}><Pencil aria-hidden /> Edit</Link>
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              disabled={clone.isPending}
              onClick={() =>
                void run(async () => {
                  const result = await clone.mutateAsync(a.id)
                  navigate(`/agents/${result.agent.id}`, { state: { notice: `Cloned as ${result.agent.name}.` } })
                })
              }
            >
              <Copy aria-hidden /> Clone
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={archive.isPending}
              onClick={() => void run(async () => { await archive.mutateAsync({ id: a.id, archived: !archived }) })}
            >
              {archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
              {archived ? 'Restore' : 'Archive'}
            </Button>
          </div>
        ) : null}
      </header>

      {notice ? <Alert><AlertDescription>{notice}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      {a.description ? <p className="max-w-3xl text-sm text-muted-foreground">{a.description}</p> : null}

      {a.versions.length > 1 ? (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Versions:</span>
          {a.versions.map((v) => (
            <Link
              key={v.id}
              to={`/agents/${v.id}`}
              className={cn(
                'rounded border px-2 py-0.5 tabular-nums',
                v.id === a.id ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-accent',
              )}
            >
              v{v.version}
            </Link>
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Model and limits</CardTitle></CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <Field label="Provider"><ProviderBadge provider={c.provider} /></Field>
              <Field label={c.provider === 'rule_based' ? 'Profile' : 'Model ID'}>
                <span className="font-mono">{c.model_id}</span>
              </Field>
              <Field label="Temperature">{c.temperature}</Field>
              <Field label="Max steps">{c.max_steps}</Field>
              <Field label="Max tool calls">{c.max_tool_calls}</Field>
              <Field label="Timeout">{c.timeout_s} s</Field>
              <Field label="Model retries">{c.max_retries}</Field>
              <Field label="Prompt version"><span className="font-mono">{c.prompt_version}</span></Field>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Tools ({c.tools.length})</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-1">
            {c.tools.map((tool) => (
              <Badge
                key={tool}
                variant="outline"
                className={cn('font-mono', (tool === 'request_refund' || tool === 'request_reroute') && 'border-destructive/50 text-destructive')}
              >
                {tool}
              </Badge>
            ))}
            <p className="mt-2 w-full text-xs text-muted-foreground">
              Refund and reroute are policy-gated: even when listed, the backend blocks them and records the attempt.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">System prompt</CardTitle></CardHeader>
        <CardContent>
          {c.provider === 'rule_based' ? (
            <p className="mb-3 text-xs text-muted-foreground">
              Rule-based agents don&apos;t read the prompt; it is stored so LLM agents cloned from this config start with it.
            </p>
          ) : null}
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/40 p-4 text-xs">{c.system_prompt}</pre>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Created {formatDateTime(a.created_at)} · updated {formatDateTime(a.updated_at)}
      </p>
    </div>
  )
}
