import { ArrowLeft, Ban, GitCompareArrows } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { VerdictBadge } from '@/features/runs/VerdictBadge'
import { toApiError } from '@/lib/api'
import { formatDateTime, humanize } from '@/lib/format'

import { useCancelSuiteRun, useSuiteRun } from './api'
import { MetricCards, SuiteRunStatusBadge } from './components'

export function SuiteRunPage() {
  const { id = '' } = useParams()
  const { isOwner, session } = useAuth()
  const run = useSuiteRun(id)
  const cancel = useCancelSuiteRun(id)
  const [error, setError] = useState<string | null>(null)

  if (run.isPending) return <Skeleton className="h-64 w-full" />
  if (run.isError) {
    return <Alert variant="destructive"><AlertDescription>{toApiError(run.error).message}</AlertDescription></Alert>
  }
  const r = run.data
  const active = r.status === 'queued' || r.status === 'running'
  const canCancel = active && (isOwner || (session?.role === 'viewer' && r.triggered_by_role === 'viewer'))
  const pctDone = r.total_runs ? Math.round((r.progress.done / r.total_runs) * 100) : 0

  return (
    <div className="flex flex-col gap-6">
      <Link to="/suites" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Benchmarks
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {r.agent_name} v{r.agent_version} <span className="text-muted-foreground">on</span> {r.suite_name}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <SuiteRunStatusBadge status={r.status} />
            {r.provider === 'rule_based' ? <Badge variant="outline">Rule-based baseline</Badge> : null}
            {r.repeats > 1 ? <Badge variant="outline">{r.repeats} repeats</Badge> : null}
            <span>{formatDateTime(r.created_at)}</span>
            {r.evaluator_version ? <span className="font-mono text-xs">{r.evaluator_version}</span> : null}
          </div>
        </div>
        <div className="flex gap-2">
          {canCancel ? (
            <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => {
              setError(null)
              cancel.mutateAsync().catch((err: unknown) => setError(toApiError(err).message))
            }}>
              <Ban aria-hidden /> Cancel suite run
            </Button>
          ) : null}
          {r.status === 'completed' ? (
            <Button variant="outline" size="sm" asChild>
              <Link to={`/compare?candidate=${r.id}`}><GitCompareArrows aria-hidden /> Compare</Link>
            </Button>
          ) : null}
        </div>
      </header>
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="flex flex-col gap-1.5" aria-label="Progress">
        <div className="flex justify-between text-sm">
          <span>{r.progress.done} of {r.total_runs} runs finished{active ? ` · ${r.progress.active} still queued or running` : ''}</span>
          <span className="tabular-nums text-muted-foreground">{pctDone}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pctDone} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded-full bg-sky-600 transition-all" style={{ width: `${pctDone}%` }} />
        </div>
      </div>

      {r.metrics ? (
        <MetricCards metrics={r.metrics} />
      ) : (
        <Alert><AlertDescription>Metrics appear once every run in the suite has finished.</AlertDescription></Alert>
      )}
      {r.flaky.length ? (
        <Alert><AlertDescription>Flaky (verdict changed across repeats): <span className="font-mono">{r.flaky.join(', ')}</span></AlertDescription></Alert>
      ) : null}

      <div className="rounded-lg border">
        <Table aria-label="Suite results">
          <TableHeader>
            <TableRow>
              <TableHead>Scenario</TableHead>
              {r.repeats > 1 ? <TableHead>Repeat</TableHead> : null}
              <TableHead>Status</TableHead>
              <TableHead>Verdict</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Main finding</TableHead>
              <TableHead>Latency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {r.results.map((x) => (
              <TableRow key={x.run_id}>
                <TableCell>
                  <Link to={`/runs/${x.run_id}`} className="font-mono text-xs hover:underline">{x.scenario_key} v{x.scenario_version}</Link>
                </TableCell>
                {r.repeats > 1 ? <TableCell className="tabular-nums">{x.repeat_index + 1}</TableCell> : null}
                <TableCell>{humanize(x.status)}</TableCell>
                <TableCell><VerdictBadge verdict={x.verdict} /></TableCell>
                <TableCell className="tabular-nums">{x.score ?? '—'}</TableCell>
                <TableCell className="text-sm">{x.main_failure ? humanize(x.main_failure) : '—'}</TableCell>
                <TableCell className="tabular-nums">{x.latency_ms !== null ? `${(x.latency_ms / 1000).toFixed(1)} s` : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
