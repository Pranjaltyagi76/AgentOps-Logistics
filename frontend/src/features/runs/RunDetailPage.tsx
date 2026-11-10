import { ArrowLeft, Ban, RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { toApiError } from '@/lib/api'
import { formatDateTime, humanize } from '@/lib/format'

import { isActive, useCancelRun, useLaunchRun, useRun, useTrace } from './api'
import { RunStatusBadge } from './RunStatusBadge'
import { TraceTimeline } from './TraceTimeline'
import type { RunDetail } from './types'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function Summary({ run }: { run: RunDetail }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Run</CardTitle></CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
          <Field label="Scenario">
            <Link to={`/scenarios/${run.scenario_id}`} className="font-mono hover:underline">
              {run.scenario_key} v{run.scenario_version}
            </Link>
          </Field>
          <Field label="Agent">
            <Link to={`/agents/${run.agent_config_id}`} className="font-mono hover:underline">
              {run.agent_name} v{run.agent_version}
            </Link>
          </Field>
          <Field label="Stop reason">{run.stop_reason ? humanize(run.stop_reason) : '—'}</Field>
          <Field label="Steps">{run.steps ?? '—'} / {run.limits.max_steps}</Field>
          <Field label="Tool calls">{run.tool_call_count ?? '—'} / {run.limits.max_tool_calls}</Field>
          <Field label="Latency">{run.latency_ms !== null ? `${(run.latency_ms / 1000).toFixed(2)} s` : '—'} (limit {run.limits.timeout_s} s)</Field>
          <Field label="Started">{formatDateTime(run.started_at)}</Field>
          <Field label="Finished">{formatDateTime(run.finished_at)}</Field>
          <Field label="Launched by">{run.triggered_by_role === 'owner' ? 'Owner' : 'Demo viewer'}</Field>
          <Field label="Versions">
            <span className="font-mono text-xs">
              {Object.entries(run.versions).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(' · ')}
            </span>
          </Field>
        </dl>
      </CardContent>
    </Card>
  )
}

function Outcome({ run }: { run: RunDetail }) {
  const o = run.outcome
  if (!o) return null
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Agent outcome</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <span>Root cause <span className="font-mono font-medium">{o.root_cause ?? '—'}</span></span>
          <span>Escalated <span className="font-medium">{o.escalation ? 'yes' : 'no'}</span></span>
          {o.confidence !== null ? <span>Confidence <span className="font-medium">{o.confidence}</span></span> : null}
        </div>
        <blockquote className="rounded-lg bg-muted px-4 py-3">{o.customer_response}</blockquote>
        {o.uncertainty_note ? <p className="text-muted-foreground">Note: {o.uncertainty_note}</p> : null}
        {o.action_summary.length ? (
          <ul className="list-disc pl-4">{o.action_summary.map((a) => <li key={a}>{a}</li>)}</ul>
        ) : null}
        <div className="flex flex-wrap gap-1">
          {o.evidence_ids.map((id) => <code key={id} className="rounded bg-muted px-1.5 py-0.5 text-xs">{id}</code>)}
        </div>
        <p className="text-xs text-muted-foreground">
          This is what the agent submitted. Scoring against the hidden ground truth arrives in Phase 5.
        </p>
      </CardContent>
    </Card>
  )
}

export function RunDetailPage() {
  const { id = '' } = useParams()
  const { session, isOwner } = useAuth()
  const navigate = useNavigate()
  const run = useRun(id)
  const active = isActive(run.data?.status)
  const trace = useTrace(id, active)
  const refetchTrace = trace.refetch
  // The final trace events are written just after the status flips, so fetch once more.
  const finalStatus = active ? null : run.data?.status
  useEffect(() => {
    if (finalStatus) void refetchTrace()
  }, [finalStatus, refetchTrace])
  const cancel = useCancelRun()
  const relaunch = useLaunchRun()
  const [error, setError] = useState<string | null>(null)

  if (run.isPending) return <Skeleton className="h-64 w-full" />
  if (run.isError) {
    const err = toApiError(run.error)
    return (
      <Alert variant="destructive">
        <AlertTitle>{err.status === 404 ? 'Run not found' : 'Could not load run'}</AlertTitle>
        <AlertDescription>{err.message} <Link to="/runs" className="underline">Back to runs</Link></AlertDescription>
      </Alert>
    )
  }
  const r = run.data
  const canCancel = active && (isOwner || (session?.role === 'viewer' && r.triggered_by_role === 'viewer'))

  async function act(action: () => Promise<void>) {
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link to="/runs" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Runs
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {r.agent_name} <span className="text-muted-foreground">on</span> {r.scenario_key}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <RunStatusBadge status={r.status} />
            {r.provider === 'rule_based' ? <Badge variant="outline">Rule-based baseline</Badge> : null}
            {r.cancel_requested && active ? <span>Cancelling…</span> : null}
            <span className="font-mono text-xs">{r.id}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {canCancel ? (
            <Button variant="outline" size="sm" disabled={cancel.isPending || r.cancel_requested} onClick={() => void act(async () => { await cancel.mutateAsync(r.id) })}>
              <Ban aria-hidden /> Cancel run
            </Button>
          ) : null}
          {!active ? (
            <Button
              variant="outline"
              size="sm"
              disabled={relaunch.isPending}
              onClick={() =>
                void act(async () => {
                  const next = await relaunch.mutateAsync({ scenarioId: r.scenario_id, agentId: r.agent_config_id })
                  navigate(`/runs/${next.id}`)
                })
              }
            >
              <RotateCw aria-hidden /> Run again
            </Button>
          ) : null}
        </div>
      </header>

      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      {r.error ? (
        <Alert variant={r.error_kind === 'infra' ? 'destructive' : 'default'}>
          <AlertTitle>
            {r.error_kind === 'infra' ? 'Platform error (not counted against the agent)' : 'The agent did not finish cleanly'}
          </AlertTitle>
          <AlertDescription className="font-mono text-xs">
            {String(r.error.code ?? '')} {r.error.message ? `· ${String(r.error.message)}` : ''}
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Summary run={r} />
        <Outcome run={r} />
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">
          Trace <span className="text-sm font-normal text-muted-foreground">({trace.data?.events.length ?? 0} events{active ? ', live' : ''})</span>
        </h2>
        <p className="text-sm text-muted-foreground">
          Every observable step: what the agent was told, each tool call with its arguments and result, and how the run ended. No hidden reasoning is recorded.
        </p>
        {trace.isError ? (
          <Alert variant="destructive"><AlertDescription>{toApiError(trace.error).message}</AlertDescription></Alert>
        ) : trace.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <TraceTimeline events={trace.data.events} />
        )}
      </section>
    </div>
  )
}
